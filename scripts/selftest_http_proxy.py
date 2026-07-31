"""Serve a deterministic loopback HTTP proxy response for the packaged network control.

The control target remains an external HTTP origin (``http://example.com/``), but
the request is routed through this loopback responder.  The packaged gate then
uses a dead proxy for the same target.  Requiring both an observed control
request and the dead-proxy failure proves that the browser probe can distinguish
reachable from blocked without depending on CI internet egress.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_EXPECTED_HOST = "example.com"
_EXPECTED_TARGET = "http://example.com/__n03_network_control__"


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


class _ProxyHandler(BaseHTTPRequestHandler):
    server: "_ProxyServer"

    def _empty_response(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler protocol
        if self.path != _EXPECTED_TARGET or self.headers.get("Host") != _EXPECTED_HOST:
            self._empty_response(502)
            return
        evidence = {
            "method": self.command,
            "target": self.path,
            "host": self.headers.get("Host", ""),
        }
        _write_json_atomic(self.server.hit_file, evidence)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler protocol
        self._empty_response(502)

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler protocol
        self._empty_response(502)

    def do_CONNECT(self) -> None:  # noqa: N802 - plain HTTP is the required probe
        self._empty_response(502)

    def log_message(self, _format: str, *args: object) -> None:
        return


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, hit_file: Path) -> None:
        super().__init__(("127.0.0.1", 0), _ProxyHandler)
        self.hit_file = hit_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--hit-file", type=Path, required=True)
    args = parser.parse_args(argv)

    args.ready_file.parent.mkdir(parents=True, exist_ok=True)
    args.hit_file.parent.mkdir(parents=True, exist_ok=True)
    server = _ProxyServer(args.hit_file)
    host, port = server.server_address
    _write_json_atomic(args.ready_file, {"host": host, "port": port})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
