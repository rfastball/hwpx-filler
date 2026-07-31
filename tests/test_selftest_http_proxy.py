"""Deterministic packaged-network control proxy tests."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from scripts.selftest_http_proxy import _ProxyServer


def test_control_proxy_observes_and_succeeds_for_external_http_target(
    tmp_path: Path,
) -> None:
    hit_file = tmp_path / "hit.json"
    server = _ProxyServer(hit_file)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": f"http://{host}:{port}"})
        )
        with opener.open("http://example.com/", timeout=5) as response:
            assert response.status == 204
        hit = json.loads(hit_file.read_text(encoding="utf-8"))
        assert hit == {
            "method": "GET",
            "target": "http://example.com/",
            "host": "example.com",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
