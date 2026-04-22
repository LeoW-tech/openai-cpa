#!/usr/bin/env python3

import argparse
import json
import os
import pathlib
import signal
import socket
import socketserver
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import suppress

import yaml


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.local_network import build_host_relay_specs


RELAY_DIR_NAME = "local-relays"


def _relay_dir(project_root: pathlib.Path) -> pathlib.Path:
    relay_dir = project_root / "data" / RELAY_DIR_NAME
    relay_dir.mkdir(parents=True, exist_ok=True)
    return relay_dir


def _load_config(project_root: pathlib.Path) -> dict:
    config_path = project_root / "data" / "config.yaml"
    if not config_path.exists():
        return _load_config_from_sqlite(project_root)
    with config_path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh) or {}
    if loaded:
        return loaded
    return _load_config_from_sqlite(project_root)


def _load_config_from_sqlite(project_root: pathlib.Path) -> dict:
    db_path = project_root / "data" / "data.db"
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT value FROM system_kv WHERE `key` = ?",
                ("global_app_config",),
            ).fetchone()
        if not row or not row[0]:
            return {}
        return json.loads(row[0]) or {}
    except Exception:
        return {}


def _pid_file(relay_dir: pathlib.Path, name: str) -> pathlib.Path:
    return relay_dir / f"{name}.pid"


def _meta_file(relay_dir: pathlib.Path, name: str) -> pathlib.Path:
    return relay_dir / f"{name}.json"


def _log_file(relay_dir: pathlib.Path, name: str) -> pathlib.Path:
    return relay_dir / f"{name}.log"


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _stop_existing_relays(project_root: pathlib.Path) -> None:
    relay_dir = _relay_dir(project_root)
    for pid_path in relay_dir.glob("*.pid"):
        with suppress(Exception):
            pid = int(pid_path.read_text(encoding="utf-8").strip())
            if _is_process_alive(pid):
                os.kill(pid, signal.SIGTERM)
                for _ in range(20):
                    if not _is_process_alive(pid):
                        break
                    time.sleep(0.1)
                if _is_process_alive(pid):
                    os.kill(pid, signal.SIGKILL)
        with suppress(FileNotFoundError):
            pid_path.unlink()
    for meta_path in relay_dir.glob("*.json"):
        with suppress(FileNotFoundError):
            meta_path.unlink()


def _start_relays(project_root: pathlib.Path) -> int:
    relay_dir = _relay_dir(project_root)
    config = _load_config(project_root)
    specs = build_host_relay_specs(config)
    if not specs:
        return 0

    for spec in specs:
        name = spec["name"]
        log_path = _log_file(relay_dir, name)
        with log_path.open("a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(pathlib.Path(__file__).resolve()),
                    "serve",
                    "--listen-host",
                    str(spec["listen_host"]),
                    "--listen-port",
                    str(spec["listen_port"]),
                    "--target-host",
                    str(spec["target_host"]),
                    "--target-port",
                    str(spec["target_port"]),
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _pid_file(relay_dir, name).write_text(str(proc.pid), encoding="utf-8")
        _meta_file(relay_dir, name).write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


class _RelayTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_cls, target_host: str, target_port: int):
        super().__init__(server_address, handler_cls)
        self.target_host = target_host
        self.target_port = target_port


class _RelayHandler(socketserver.BaseRequestHandler):
    def handle(self):
        upstream = None
        try:
            upstream = socket.create_connection((self.server.target_host, self.server.target_port), timeout=10)
            upstream.settimeout(None)
            self.request.settimeout(None)
            threads = [
                threading.Thread(target=self._pipe, args=(self.request, upstream), daemon=True),
                threading.Thread(target=self._pipe, args=(upstream, self.request), daemon=True),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            with suppress(Exception):
                self.request.close()
            if upstream is not None:
                with suppress(Exception):
                    upstream.close()

    @staticmethod
    def _pipe(source: socket.socket, target: socket.socket) -> None:
        try:
            while True:
                data = source.recv(65536)
                if not data:
                    break
                target.sendall(data)
        except Exception:
            pass
        finally:
            with suppress(Exception):
                target.shutdown(socket.SHUT_WR)


def _serve_relay(listen_host: str, listen_port: int, target_host: str, target_port: int) -> int:
    server = _RelayTCPServer((listen_host, listen_port), _RelayHandler, target_host, target_port)
    stop_event = threading.Event()

    def _shutdown(*_args):
        if stop_event.is_set():
            return
        stop_event.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    print(
        f"[relay] listening on {listen_host}:{listen_port} -> {target_host}:{target_port}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage local host relays for mac container networking.")
    parser.add_argument("command", choices=["start", "stop", "restart", "serve"])
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=0)
    parser.add_argument("--target-host", default="")
    parser.add_argument("--target-port", type=int, default=0)
    args = parser.parse_args()

    project_root = pathlib.Path(args.project_root).resolve()

    if args.command == "stop":
        _stop_existing_relays(project_root)
        return 0
    if args.command == "start":
        _stop_existing_relays(project_root)
        return _start_relays(project_root)
    if args.command == "restart":
        _stop_existing_relays(project_root)
        return _start_relays(project_root)
    return _serve_relay(args.listen_host, args.listen_port, args.target_host, args.target_port)


if __name__ == "__main__":
    raise SystemExit(main())
