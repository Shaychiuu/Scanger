"""One command to run everything: `python -m scanger.dev`.

Starts the database (Docker Compose), applies migrations, then runs the
VisualMatch API, the Scanger API and the frontend as child processes with
prefixed, interleaved logs. Ctrl-C (or any child exiting) stops all of them.
The database container is left running (data is kept); stop it with
`docker compose stop db`.
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from scanger.config import REPO_ROOT, scanger_api_url, visualmatch_api_url

FRONTEND_PORT = 7861
HOST = "127.0.0.1"


@dataclass
class Service:
    name: str
    cmd: list[str]
    cwd: str
    port: int
    proc: subprocess.Popen | None = None


def _port(url: str) -> int:
    return urlparse(url).port or 80


def _services() -> list[Service]:
    py = sys.executable
    return [
        Service(
            "visualmatch",
            [py, "-m", "uvicorn", "api.app:app", "--host", HOST, "--port", str(_port(visualmatch_api_url()))],
            str(REPO_ROOT / "upstream" / "visualmatch"),
            _port(visualmatch_api_url()),
        ),
        Service(
            "scanger-api",
            [py, "-m", "uvicorn", "scanger.api:app", "--host", HOST, "--port", str(_port(scanger_api_url()))],
            str(REPO_ROOT),
            _port(scanger_api_url()),
        ),
        Service("frontend", [py, "-m", "scanger.frontend"], str(REPO_ROOT), FRONTEND_PORT),
    ]


def _say(msg: str) -> None:
    print(f"[dev] {msg}", flush=True)


def _port_in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((HOST, port)) == 0


def _pump(svc: Service) -> None:
    assert svc.proc and svc.proc.stdout
    for line in svc.proc.stdout:
        print(f"[{svc.name}] {line}", end="", flush=True)


def _prepare_database() -> None:
    _say("starting database (docker compose up -d --wait db)")
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "db"], cwd=REPO_ROOT, check=True)
    _say("applying migrations (alembic upgrade head)")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=REPO_ROOT, check=True)


def _stop_all(services: list[Service]) -> None:
    for svc in services:
        if svc.proc and svc.proc.poll() is None:
            try:
                os.killpg(svc.proc.pid, signal.SIGINT)  # graceful, like Ctrl-C in its own terminal
            except ProcessLookupError:
                pass
    deadline = time.time() + 10
    for svc in services:
        if svc.proc:
            try:
                svc.proc.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                os.killpg(svc.proc.pid, signal.SIGKILL)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the whole Scanger stack in one terminal.")
    parser.add_argument("--no-db", action="store_true", help="skip docker compose and migrations (database already up)")
    args = parser.parse_args()

    services = _services()
    busy = [f"{s.name} (port {s.port})" for s in services if _port_in_use(s.port)]
    if busy:
        _say(f"already in use: {', '.join(busy)}. Stop the old processes first.")
        return 1

    if not args.no_db:
        try:
            _prepare_database()
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            _say(f"database setup failed: {exc}")
            return 1

    def _terminate(signum, frame):
        raise KeyboardInterrupt

    # Closing the terminal (SIGHUP) or `kill` (SIGTERM) must also stop the children.
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _terminate)
    signal.signal(signal.SIGINT, _terminate)

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    try:
        for svc in services:
            _say(f"starting {svc.name}")
            svc.proc = subprocess.Popen(
                svc.cmd,
                cwd=svc.cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,  # own process group so we can stop uvicorn reloaders etc. cleanly
            )
            threading.Thread(target=_pump, args=(svc,), daemon=True).start()

        announced = False
        while True:
            for svc in services:
                code = svc.proc.poll()
                if code is not None:
                    _say(f"{svc.name} exited with code {code}; stopping everything")
                    return code or 1
            if not announced and all(_port_in_use(s.port) for s in services):
                _say(f"all up. Open http://{HOST}:{FRONTEND_PORT}  (Ctrl-C to stop)")
                announced = True
            time.sleep(0.5)
    except KeyboardInterrupt:
        _say("stopping...")
        return 0
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)  # a second Ctrl-C must not abort cleanup
        _stop_all(services)


if __name__ == "__main__":
    sys.exit(main())
