"""Deterministic packaged-network control proxy tests."""

from __future__ import annotations

import json
import http.client
import threading
from pathlib import Path

from scripts.selftest_http_proxy import _EXPECTED_HOST, _EXPECTED_TARGET, _ProxyServer


def test_control_proxy_observes_and_succeeds_for_external_http_target(
    tmp_path: Path,
) -> None:
    hit_file = tmp_path / "hit.json"
    server = _ProxyServer(hit_file)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("GET", _EXPECTED_TARGET, headers={"Host": _EXPECTED_HOST})
        response = connection.getresponse()
        assert response.status == 204
        response.read()
        connection.close()
        hit = json.loads(hit_file.read_text(encoding="utf-8"))
        assert hit == {
            "method": "GET",
            "target": _EXPECTED_TARGET,
            "host": _EXPECTED_HOST,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_proxy_rejects_wrong_target_and_connect_without_marker(
    tmp_path: Path,
) -> None:
    hit_file = tmp_path / "hit.json"
    server = _ProxyServer(hit_file)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        for method, target, header_host in (
            ("GET", "http://example.com/wrong", _EXPECTED_HOST),
            ("GET", _EXPECTED_TARGET, "wrong.example"),
            ("CONNECT", "example.com:443", _EXPECTED_HOST),
        ):
            connection = http.client.HTTPConnection(host, port, timeout=5)
            connection.request(method, target, headers={"Host": header_host})
            response = connection.getresponse()
            assert response.status == 502
            response.read()
            connection.close()
            assert not hit_file.exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
