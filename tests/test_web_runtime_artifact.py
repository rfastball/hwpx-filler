"""N-03 제품 runtime이 sealed build/web 하나만 소비하는 중앙 seam 계약."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hwpxfiller.web_artifact import VerifiedWebArtifact, WebArtifactViolation
from hwpxfiller.webapp import app as app_mod

ROOT = Path(__file__).resolve().parents[1]


def test_source_product_resolves_fresh_build_web() -> None:
    artifact = app_mod.web_artifact()

    assert artifact.root.parent == (ROOT / "build").resolve()
    assert artifact.root.name == "web"
    assert artifact.index_path == artifact.root / "index.html"
    assert len(artifact.artifact_id) == 64
    assert len(artifact.tree_sha256) == 64


def test_artifact_failure_is_loud_before_webview_window_creation(
    monkeypatch,
) -> None:
    messages: list[str] = []

    def reject_artifact():
        raise WebArtifactViolation("seal missing")

    def reject_window(*_args, **_kwargs):
        raise AssertionError("artifact 검증 실패 뒤 창을 생성했습니다")

    monkeypatch.setattr(app_mod, "web_artifact", reject_artifact)
    monkeypatch.setattr(app_mod, "_alarm", lambda message, window=None: messages.append(message))
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(create_window=reject_window),
    )

    assert app_mod.main() == 2
    assert messages and "창을 열지 않습니다" in messages[0]
    assert "seal missing" in messages[0]


def test_main_and_selftest_share_the_single_resolver() -> None:
    source = Path(app_mod.__file__).read_text(encoding="utf-8")
    main_region = source[source.index("def main()") :]
    runtime_region = source[
        source.index("def _runtime_selftest_evidence") : source.index("def _selftest_drive")
    ]

    assert main_region.index("artifact = web_artifact()") < main_region.index("import webview")
    assert "str(artifact.index_path)" in main_region
    assert "current_artifact = web_artifact()" in runtime_region
    assert "current_artifact.artifact_id != launched_artifact.artifact_id" in runtime_region
    assert "(window, artifact)" in main_region
    assert "HWPXFILLER_WEB_DIR" not in source
    assert '_repo_root() / "web"' not in source
    assert '_repo_root() / "frontend"' not in source


def test_selftest_rejects_artifact_swap_after_window_creation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    launched = VerifiedWebArtifact(
        root=tmp_path,
        index_path=tmp_path / "index.html",
        artifact_id="a" * 64,
        tree_sha256="b" * 64,
    )
    swapped = VerifiedWebArtifact(
        root=tmp_path,
        index_path=tmp_path / "index.html",
        artifact_id="c" * 64,
        tree_sha256="d" * 64,
    )
    monkeypatch.setattr(app_mod, "web_artifact", lambda: swapped)

    class Window:
        def evaluate_js(self, _script):
            raise AssertionError("artifact swap 거절 전에 DOM을 읽었습니다")

    with pytest.raises(WebArtifactViolation, match="changed after"):
        app_mod._runtime_selftest_evidence(Window(), launched)


def test_packaging_requires_artifact_parity_node_free_boot_and_offline_probe() -> None:
    build = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    app = Path(app_mod.__file__).read_text(encoding="utf-8")
    entry = (ROOT / "packaging" / "hwpx_filler_web_entry.py").read_text(
        encoding="utf-8"
    )
    proxy = (ROOT / "scripts" / "selftest_http_proxy.py").read_text(
        encoding="utf-8"
    )
    verifier = (ROOT / "scripts" / "verify_packaged_web.py").read_text(
        encoding="utf-8"
    )

    assert "scripts\\verify_packaged_web.py" in build
    assert build.index("scripts\\verify_packaged_web.py") < build.index("--selfcheck")
    assert "Node-free packaged gate PATH" in build
    assert "HWPX_SELFTEST_OFFLINE_PROBE" in build
    assert "--proxy-server=127.0.0.1:9 --disable-background-networking" in build
    assert "scripts\\selftest_http_proxy.py" in build
    assert "network-control-proxy-hit.json" in build
    assert "proxyHit.target -ne 'http://example.com/'" in build
    assert "packaged-network-control.json" in build
    assert "network_control_external_fetch_succeeded" in build
    assert "network_control_proxy_observed" in build
    assert "responsibilities.Count -ne 42" in build
    assert "falseResponsibilities.Count -ne 0" in build
    assert "resources_same_origin" in build
    assert "external_fetch_blocked" in build
    assert "String.fromCharCode(104, 116, 116, 112)" in app
    assert "['example', 'com'].join('.')" in app
    assert "ThreadingHTTPServer" in proxy and "self.send_response(204)" in proxy
    assert "artifact = web_artifact()" in entry
    assert "artifact.artifact_id" in entry and "artifact.tree_sha256" in entry
    assert "resolve_web_artifact(repo_root=args.repo_root)" in verifier
    assert "resolve_web_artifact(frozen_root=args.bundle_root)" in verifier
