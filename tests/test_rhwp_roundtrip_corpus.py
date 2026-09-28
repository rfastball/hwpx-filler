"""rhwp 왕복 보존 코퍼스 — 동봉 편집기가 실제로 내보낸 바이트를 제품 비교기로 판정한다.

## 왜 실 편집기인가

`compare_rhwp_roundtrip` 의 단위 테스트(`tests/test_authoring.py`)는 **비교기의 규칙**만 잰다.
어떤 문서가 저작 작업대에서 편집 가능하게 열리는지는 vendor rhwp 직렬화기의 실측 사실이라
단위 테스트로는 알 수 없다. 실습 표본(`examples/quickstart-101/templates`)이 「읽기 전용 ·
보존 확인 필요」로 열리던 결함(#1022)이 그 틈으로 출하됐다 — 비교기 단위 테스트는 전부
초록이었고, 직렬화기는 원본에 없는 단 정의(`hp:colPr`)를 덧붙이고 있었다.

## 무엇을 재는가

봉인된 웹 산출물의 rhwp Studio(`build/web/rhwp/studio`)를 제품과 같은 SDK·같은
``createStudio`` 옵션으로 띄우고(`frontend/src/editorview/rhwp_editor.ts` 의 ``mountRhwp``),
코퍼스 문서마다 ``loadFile`` → ``exportHwpx`` 한 번을 거친 바이트를 제품 비교기에 넣는다.
판정표(:data:`NOT_EDITABLE`)에 없는 문서는 **전부 편집 가능**해야 하고, 판정표의 문서는
적힌 이유 그대로 막혀야 한다. 문서가 늘면 자동으로 편집 가능 쪽에 들어가므로 새 코퍼스가
조용히 빠지지 않는다.

설치 Chrome + Playwright 가 필요하다(`browser` 축). 자원이 없는 로컬만
``HWPX_SKIP_MOTION_TESTS=1`` 로 명시 옵트아웃한다 — CI(`browser-render`)는 옵트아웃 없이 돈다.
"""

from __future__ import annotations

import base64
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from _web_source import REPO_ROOT
from hwpxfiller.external.rhwp_preflight import compare_rhwp_roundtrip
from hwpxfiller.web_artifact import resolve_web_artifact

CORPUS = REPO_ROOT / "tests" / "corpus"
QUICKSTART_TEMPLATES = REPO_ROOT / "examples" / "quickstart-101" / "templates"
SDK_ROOT = REPO_ROOT / "frontend" / "vendor" / "rhwp" / "editor"

#: 실습 표본의 코퍼스 사본 — 학습자가 처음 여는 문서라 편집 가능이 계약이다(#1022).
QUICKSTART_CASES = ("quickstart/구매요청서.hwpx", "quickstart/발주요청서.hwpx")

#: 편집 가능하지 **않아야** 하는 문서와 그 이유. 여기 없는 코퍼스 문서는 전부 편집 가능해야 한다.
#:
#: - G3: 제품 밖 패키지 항목(``Contents/hwpxfiller-s1-*.json``)과 그 매니페스트 항목을 rhwp 가
#:   내보내지 않는다 — 실제 손실이므로 읽기 전용이 옳다.
#: - marine: ZIP 규격 밖(백슬래시 엔트리 이름·압축된 ``mimetype``)이라 편집기가 읽지 못한다.
NOT_EDITABLE: dict[str, tuple[str, ...]] = {
    "metatag_s1/G3-package-carriers.hwpx": (
        "entry_set_changed", "entry_set_changed", "xml_changed"),
    "real/filled_notice_marine.hwpx": ("load_failed",),
}

_GATE = bool(os.environ.get("HWPX_SKIP_MOTION_TESTS"))
_GATE_REASON = (
    "rhwp 왕복 코퍼스 — Playwright + 설치 Chrome 필요"
    "(HWPX_SKIP_MOTION_TESTS=1 로 명시 옵트아웃)"
)
_HARNESS_PATH = "/__rhwp_roundtrip__.html"
_HARNESS = """<!doctype html><meta charset="utf-8">
<div id="editor" style="width:1200px;height:900px"></div>
<script type="module">
import { createStudio } from "/__sdk__/index.js";
const b64 = (bytes) => {
  let s = "";
  for (let i = 0; i < bytes.length; i += 32768) s += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return btoa(s);
};
let editor = null;
window.roundtrip = async (url, name) => {
  if (editor) editor.destroy();
  document.querySelector("#editor").innerHTML = "";
  /* 제품 mountRhwp 와 같은 옵션이다 — 편집 가능 판정 전의 마운트는 도구 모음을 켠다. */
  editor = await createStudio(document.querySelector("#editor"), {
    studioUrl: new URL("/rhwp/studio/index.html", location.href).href,
    plugins: ["hwpctrl"], chrome: { menu: false, toolbar: true, statusbar: false } });
  const bytes = new Uint8Array(await (await fetch(url)).arrayBuffer());
  try {
    await editor.loadFile(bytes, name, { skipUnsavedGuard: true });
  } catch (error) {
    return { error: String((error && error.message) || error) };
  }
  return { exported: b64(await editor.exportHwpx()) };
};
window.harnessReady = true;
</script>"""


def _corpus_documents() -> list[str]:
    return sorted(path.relative_to(CORPUS).as_posix()
                  for path in CORPUS.rglob("*") if path.suffix.lower() == ".hwpx")


@contextmanager
def _loopback() -> Iterator[str]:
    """봉인 산출물(rhwp Studio 포함)·동봉 SDK·코퍼스를 한 loopback 원점에서 내준다."""
    artifact = resolve_web_artifact(repo_root=REPO_ROOT)
    studio = artifact.root / "rhwp" / "studio" / "index.html"
    assert studio.is_file(), f"봉인 산출물에 rhwp Studio 가 없습니다: {studio}"
    payload = _HARNESS.encode("utf-8")
    mounts = {"/__sdk__/": SDK_ROOT, "/__corpus__/": CORPUS}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(artifact.root), **kwargs)

        def translate_path(self, path: str) -> str:
            route = unquote(urlsplit(path).path)
            for prefix, root in mounts.items():
                if route.startswith(prefix):
                    target = (root / route[len(prefix):]).resolve()
                    return str(target) if target.is_relative_to(root.resolve()) else ""
            return super().translate_path(path)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler protocol
            if urlsplit(self.path).path == _HARNESS_PATH:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            super().do_GET()

        def log_message(self, _format: str, *args) -> None:
            return

    Handler.extensions_map = {**Handler.extensions_map, ".js": "text/javascript",
                              ".mjs": "text/javascript", ".wasm": "application/wasm"}
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _verdict(document: str, result: dict) -> tuple[str, ...]:
    if "error" in result:
        return ("load_failed",)
    original = (CORPUS / document).read_bytes()
    verdict = compare_rhwp_roundtrip(original, base64.b64decode(result["exported"]))
    assert verdict["editable"] is (not verdict["diagnostics"]), verdict
    return tuple(sorted(item["kind"] for item in verdict["diagnostics"]))


@pytest.fixture(scope="module")
def roundtrip_verdicts() -> dict[str, tuple[str, ...]]:
    from playwright.sync_api import sync_playwright  # 지역 import — 옵트아웃 러너에 playwright 불요

    documents = _corpus_documents()
    verdicts: dict[str, tuple[str, ...]] = {}
    with _loopback() as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 1000})
            page.goto(base + _HARNESS_PATH, wait_until="load")
            page.wait_for_function("() => window.harnessReady === true")
            for document in documents:
                url = base + "/__corpus__/" + document
                result = page.evaluate("([u, n]) => window.roundtrip(u, n)",
                                       [url, Path(document).name])
                verdicts[document] = _verdict(document, result)
        finally:
            browser.close()
    return verdicts


def test_quickstart_samples_are_corpus_copies_of_the_shipped_templates() -> None:
    """코퍼스 사본이 학습자가 여는 파일과 한 바이트도 다르지 않아야 판정이 그 파일의 것이다."""
    for case in QUICKSTART_CASES:
        shipped = QUICKSTART_TEMPLATES / Path(case).name
        assert (CORPUS / case).read_bytes() == shipped.read_bytes(), (
            f"{case} 가 {shipped} 와 다릅니다 — 표본을 다시 만들었다면 코퍼스 사본도 갱신하세요.")


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_GATE_REASON)
def test_quickstart_samples_open_editable(
        roundtrip_verdicts: dict[str, tuple[str, ...]]) -> None:
    """#1022 — 101 실습이 처음 여는 두 표본은 보존 확인 배너 없이 편집 가능하게 열린다."""
    assert {case: roundtrip_verdicts.get(case) for case in QUICKSTART_CASES} == {
        case: () for case in QUICKSTART_CASES}


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_GATE_REASON)
def test_every_other_corpus_document_roundtrips_editable(
        roundtrip_verdicts: dict[str, tuple[str, ...]]) -> None:
    blocked = {document: kinds for document, kinds in roundtrip_verdicts.items() if kinds}
    assert blocked == NOT_EDITABLE
    assert set(NOT_EDITABLE) <= set(roundtrip_verdicts)
