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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _ProxyHandler(BaseHTTPRequestHandler):
    server: "_ProxyServer"

    def _record_and_respond(self) -> None:
        evidence = {
            "method": self.command,
            "target": self.path,
            "host": self.headers.get("Host", ""),
        }
        self.server.hit_file.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler protocol
        self._record_and_respond()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler protocol
        self._record_and_respond()

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler protocol
        self._record_and_respond()

    def do_CONNECT(self) -> None:  # noqa: N802 - plain HTTP is the required probe
        self.send_error(502, "CONNECT is not part of the HTTP control contract")

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
    args.ready_file.write_text(
        json.dumps({"host": host, "port": port}, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
