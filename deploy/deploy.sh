#!/bin/sh
# Build the image, push it, roll it out to the k3s cluster, verify, roll back on failure.
#
# Required: kubectl context with access to the cluster (kubeconfig), Docker with buildx.
# Optional config: deploy/deploy.env (sourced if present) or environment variables:
#   IMAGE_REPO     ghcr.io/andrewganzha/keep-rollin-frontend
#   IMAGE_TAG      defaults to the full git commit
#   PLATFORM       linux/amd64 (k3s node arch)
#   KUBE_CONTEXT   kubectl context name
#   INGRESS_HOST   enables/render the Ingress (DNS name for the app)
#   SMOKE_PORT     local port for the port-forward smoke check (18080)
#   DEPLOY_ALLOW_DIRTY=1  allow deploying an uncommitted tree (tag gets -dirty)
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
if [ -f "$repo_root/deploy/deploy.env" ]; then
    # shellcheck disable=SC1091
    . "$repo_root/deploy/deploy.env"
fi
[ -n "${KUBECONFIG:-}" ] && export KUBECONFIG

IMAGE_REPO=${IMAGE_REPO:-ghcr.io/andrewganzha/keep-rollin-frontend}
IMAGE_TRANSPORT=${IMAGE_TRANSPORT:-registry}
PLATFORM=${PLATFORM:-linux/amd64}
NAMESPACE=${NAMESPACE:-keep-rollin}
SMOKE_PORT=${SMOKE_PORT:-18080}
IMAGE_REPO=$(printf '%s' "$IMAGE_REPO" | tr '[:upper:]' '[:lower:]')

ssh_remote() {
    ssh -F /dev/null \
        -i "${K3S_SSH_KEY:-$HOME/.ssh/id_rsa}" \
        -o IdentitiesOnly=yes \
        -o UserKnownHostsFile="${K3S_SSH_KNOWN_HOSTS:-$HOME/.ssh/known_hosts}" \
        -o StrictHostKeyChecking=yes \
        -o BatchMode=yes \
        -o ConnectTimeout=15 \
        "$K3S_SSH_TARGET" "$@"
}

kubectl_cmd() {
    if [ -n "${KUBE_CONTEXT:-}" ]; then
        kubectl --context "$KUBE_CONTEXT" "$@"
    else
        kubectl "$@"
    fi
}

revision=$(git -C "$repo_root" rev-parse HEAD)
if [ -n "$(git -C "$repo_root" status --porcelain)" ]; then
    if [ "${DEPLOY_ALLOW_DIRTY:-0}" != 1 ]; then
        echo 'Working tree is dirty; commit or set DEPLOY_ALLOW_DIRTY=1.' >&2
        exit 1
    fi
    # Reusing the commit tag would leave the rollout unchanged and the old pod
    # running the previous image; a dirty tree is unreproducible anyway.
    revision="$revision-dirty-$(date -u +%Y%m%d%H%M%S)"
fi
IMAGE_TAG=${IMAGE_TAG:-$revision}
image="$IMAGE_REPO:$IMAGE_TAG"

echo "==> Build $image ($PLATFORM)"
if docker buildx version >/dev/null 2>&1; then
    if [ "$IMAGE_TRANSPORT" = registry ]; then
        docker buildx build --platform "$PLATFORM" --push -t "$image" "$repo_root/frontend"
    else
        docker buildx build --platform "$PLATFORM" --load -t "$image" "$repo_root/frontend"
    fi
else
    docker build --platform "$PLATFORM" -t "$image" "$repo_root/frontend"
    if [ "$IMAGE_TRANSPORT" = registry ]; then
        docker push "$image"
    fi
fi

if [ "$IMAGE_TRANSPORT" = ssh-import ]; then
    [ -n "${K3S_SSH_TARGET:-}" ] || { echo 'K3S_SSH_TARGET is required for IMAGE_TRANSPORT=ssh-import' >&2; exit 1; }
    echo "==> Import $image into k3s on $K3S_SSH_TARGET"
    docker save "$image" | gzip -1 | ssh_remote 'gunzip | sudo -n k3s ctr images import -'
fi

if [ "${BUILD_ONLY:-0}" = 1 ]; then
    echo "Image is ready; cluster deployment skipped (BUILD_ONLY=1)."
    exit 0
fi

render_dir=
forward_pid=
tunnel_pid=
cleanup() {
    if [ -n "$render_dir" ]; then
        rm -rf "$render_dir"
    fi
    # No `wait`: kubectl/ssh may outlive SIGTERM and would block the deploy.
    if [ -n "$forward_pid" ]; then
        kill "$forward_pid" 2>/dev/null || true
    fi
    if [ -n "$tunnel_pid" ]; then
        kill "$tunnel_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# k3s often listens on 127.0.0.1:6443 only; raise the SSH tunnel ourselves.
if [ -n "${K3S_SSH_TARGET:-}" ] && [ "${K3S_TUNNEL:-1}" = 1 ]; then
    if ! curl -sk --max-time 2 -o /dev/null "https://127.0.0.1:6443/version"; then
        echo "==> SSH tunnel to $K3S_SSH_TARGET (127.0.0.1:6443)"
        ssh -F /dev/null \
            -i "${K3S_SSH_KEY:-$HOME/.ssh/id_rsa}" \
            -o IdentitiesOnly=yes \
            -o UserKnownHostsFile="${K3S_SSH_KNOWN_HOSTS:-$HOME/.ssh/known_hosts}" \
            -o StrictHostKeyChecking=yes \
            -o BatchMode=yes \
            -o ExitOnForwardFailure=yes \
            -N -L 6443:127.0.0.1:6443 "$K3S_SSH_TARGET" &
        tunnel_pid=$!
        attempt=0
        until curl -sk --max-time 2 -o /dev/null "https://127.0.0.1:6443/version"; do
            attempt=$((attempt + 1))
            if [ "$attempt" -ge 30 ]; then
                echo 'SSH tunnel did not come up.' >&2
                exit 1
            fi
            sleep 1
        done
    fi
fi

echo "==> Cluster access"
kubectl_cmd version --client >/dev/null
kubectl_cmd get nodes >/dev/null || { echo 'kubectl cannot reach the cluster.' >&2; exit 1; }

echo "==> Apply manifests"
kubectl_cmd apply -f "$repo_root/deploy/k8s/namespace.yaml"

render_dir=$(mktemp -d)

# The image is rendered per release: applying the raw manifest would otherwise
# revert the Deployment to the placeholder tag.
sed "s|__IMAGE__|$image|g" "$repo_root/deploy/k8s/app.yaml" > "$render_dir/app.yaml"
kubectl_cmd apply -f "$render_dir/app.yaml"

if [ -n "${INGRESS_HOST:-}" ]; then
    sed "s|__INGRESS_HOST__|$INGRESS_HOST|g" "$repo_root/deploy/k8s/ingress.yaml" > "$render_dir/ingress.yaml"
    kubectl_cmd apply -f "$render_dir/ingress.yaml"
fi

echo "==> Roll out $image"
kubectl_cmd -n "$NAMESPACE" annotate deployment/web kubernetes.io/change-cause="deploy $IMAGE_TAG" --overwrite

if ! kubectl_cmd -n "$NAMESPACE" rollout status deployment/web --timeout=180s; then
    echo 'Rollout failed; recent events:' >&2
    kubectl_cmd -n "$NAMESPACE" get pods -o wide >&2 || true
    kubectl_cmd -n "$NAMESPACE" describe deployment/web >&2 || true
    echo 'Rolling back.' >&2
    kubectl_cmd -n "$NAMESPACE" rollout undo deployment/web
    kubectl_cmd -n "$NAMESPACE" rollout status deployment/web --timeout=180s || true
    exit 1
fi

echo "==> Smoke /health and SSR through the newest pod"
# Service port-forward can pick a terminating pod from the previous ReplicaSet,
# so address the pod created by this rollout directly.
check_target=$(kubectl_cmd -n "$NAMESPACE" get pods -l app=web \
    --sort-by=.metadata.creationTimestamp -o name | tail -1)
[ -n "$check_target" ] || { echo 'No web pod found for smoke check.' >&2; exit 1; }
pf_log="$render_dir/port-forward.log"
kubectl_cmd -n "$NAMESPACE" port-forward "$check_target" "$SMOKE_PORT:3000" >"$pf_log" 2>&1 &
forward_pid=$!

attempt=0
until curl -fsS --max-time 2 "http://127.0.0.1:$SMOKE_PORT/health" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo 'Service smoke check failed; rolling back.' >&2
        cat "$pf_log" >&2 || true
        kubectl_cmd -n "$NAMESPACE" rollout undo deployment/web
        kubectl_cmd -n "$NAMESPACE" rollout status deployment/web --timeout=180s || true
        exit 1
    fi
    sleep 1
done

# /health alone stays green when SSR hangs or OOMs; render the page too.
if ! curl -fsS --max-time 30 -o /dev/null "http://127.0.0.1:$SMOKE_PORT/"; then
    echo 'SSR smoke check failed; rolling back.' >&2
    cat "$pf_log" >&2 || true
    kubectl_cmd -n "$NAMESPACE" logs --tail=50 -l app=web >&2 || true
    kubectl_cmd -n "$NAMESPACE" rollout undo deployment/web
    kubectl_cmd -n "$NAMESPACE" rollout status deployment/web --timeout=180s || true
    exit 1
fi

echo "Deployed $image to namespace $NAMESPACE."
if [ -n "${INGRESS_HOST:-}" ]; then
    echo "Public URL: http://$INGRESS_HOST"
fi
