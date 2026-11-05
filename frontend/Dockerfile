# Build locally or in CI. Never run `nuxt build` on the VM: 1 GiB is tight.
FROM node:22-bookworm-slim AS build

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NODE_OPTIONS=--max-old-space-size=1024

RUN corepack enable && corepack prepare pnpm@10.12.3 --activate

WORKDIR /app
COPY . .
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile
RUN pnpm build

FROM node:22-bookworm-slim AS runtime

ENV NODE_ENV=production \
    NITRO_HOST=0.0.0.0 \
    NITRO_PORT=3000

RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --create-home app

WORKDIR /app
COPY --from=build --chown=app:app /app/.output ./.output

USER app
EXPOSE 3000

# `node` is the only binary guaranteed in the runtime image.
HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=15s \
    CMD node -e "fetch('http://127.0.0.1:3000/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", ".output/server/index.mjs"]
