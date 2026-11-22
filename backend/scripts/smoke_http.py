from __future__ import annotations

import argparse
import os
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import uvicorn

from app.config import Settings
from app.main import create_app


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def running_server(database_url: str | None, timeout_seconds: float) -> Iterator[str]:
    port = free_port()
    settings = Settings(
        database_url=database_url,
        database_timeout_seconds=timeout_seconds,
    )
    config = uvicorn.Config(
        create_app(settings),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=0.5)
        except httpx.HTTPError:
            time.sleep(0.05)
            continue
        if response.status_code == 200:
            break
    else:
        raise RuntimeError("The smoke server did not become healthy in 10 seconds.")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the health and readiness endpoints.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="Database probe timeout in seconds.",
    )
    parser.add_argument(
        "--expect-ready",
        action="store_true",
        help="Require /readyz to return 200 using DATABASE_URL from the environment.",
    )
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")

    with running_server(database_url, args.timeout) as base_url:
        health = httpx.get(f"{base_url}/health", timeout=5.0)
        if health.status_code != 200 or health.json() != {"status": "ok"}:
            raise SystemExit(f"/health failed with status {health.status_code}")

        readiness = httpx.get(
            f"{base_url}/readyz",
            timeout=max(5.0, args.timeout + 5.0),
        )
        expected_status = 200 if args.expect_ready else 503
        if readiness.status_code != expected_status:
            raise SystemExit(
                f"/readyz returned {readiness.status_code}, expected {expected_status}"
            )

        expected_state = "ok" if args.expect_ready else "unavailable"
        expected_payload = {
            "status": expected_state,
            "checks": {"database": expected_state},
        }
        if readiness.json() != expected_payload:
            raise SystemExit("/readyz returned an unexpected payload")

        if database_url and database_url in readiness.text:
            raise SystemExit("/readyz leaked the database URL.")

        print(f"health=200 readyz={readiness.status_code} database={expected_state} url={base_url}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
