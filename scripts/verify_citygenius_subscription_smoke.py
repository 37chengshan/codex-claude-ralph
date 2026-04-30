#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


REQUIRED_MARKERS = [
    'data-subscribe-tier="monthly"',
    'data-subscribe-tier="yearly"',
    "data-billing-portal-link",
]


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fetch_text(url: str, timeout: float = 3.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def process_exit_message(process: subprocess.Popen[str]) -> str:
    stdout = ""
    stderr = ""
    if process.stdout is not None:
        stdout = process.stdout.read()
    if process.stderr is not None:
        stderr = process.stderr.read()
    return f"Preview server exited early with code {process.returncode}. stdout={stdout!r} stderr={stderr!r}"


def wait_for_server(process: subprocess.Popen[str], url: str, timeout_seconds: float = 30.0) -> str:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(process_exit_message(process))
        try:
            return fetch_text(url)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = str(exc)
            time.sleep(0.5)
    raise RuntimeError(f"Preview server did not become ready: {last_error}")


def main() -> None:
    repo_path = Path.cwd()
    port = reserve_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.setdefault("CI", "1")

    process = subprocess.Popen(
        ["npm", "run", "preview", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(repo_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    try:
        time.sleep(1.0)
        html = wait_for_server(process, f"{base_url}/")
        missing = [marker for marker in REQUIRED_MARKERS if marker not in html]
        if missing:
            payload = {
                "status": "failed",
                "message": "Missing required subscription markers on the homepage.",
                "missing_markers": missing,
                "returncode": 1,
            }
            print(json.dumps(payload))
            return

        payload = {
            "status": "passed",
            "message": "Homepage rendered the subscription smoke markers.",
            "checked_url": f"{base_url}/",
            "returncode": 0,
        }
        print(json.dumps(payload))
    except Exception as exc:  # noqa: BLE001
        payload = {
            "status": "failed",
            "message": str(exc),
            "returncode": 1,
        }
        print(json.dumps(payload))
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
