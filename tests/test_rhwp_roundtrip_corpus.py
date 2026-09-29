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
def _loopback(generated: Path | None = None) -> Iterator[str]:
    """봉인 산출물(rhwp Studio 포함)·동봉 SDK·코퍼스(와 만든 문서)를 한 loopback 원점에서 내준다."""
    artifact = resolve_web_artifact(repo_root=REPO_ROOT)
    studio = artifact.root / "rhwp" / "studio" / "index.html"
    assert studio.is_file(), f"봉인 산출물에 rhwp Studio 가 없습니다: {studio}"
    payload = _HARNESS.encode("utf-8")
    mounts = {"/__sdk__/": SDK_ROOT, "/__corpus__/": CORPUS,
              **({"/__generated__/": generated} if generated is not None else {})}

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


def _batch_outputs() -> dict[str, bytes]:
    """IDE-07 반복 명령의 산출물 — 실습 표본에 한 명령을 적용한다(같은 문구 4곳을 한 필드로)."""
    from hwpxfiller.external.hwpx_authoring import apply_hwpx, same_text_hwpx
    from hwpxfiller.external.hwpx_package_io import read_hwpx_package

    source = CORPUS / QUICKSTART_CASES[0]
    entry = "Contents/section0.xml"
    package = read_hwpx_package(source)
    selection = {"entry": entry, "paragraph": 2, "start_paragraph": 2, "end_paragraph": 2, "start": 4, "end": 5}
    sites = [hit["location"] for hit in same_text_hwpx(package, selection) if hit["enabled"]]
    assert len(sites) == 3, sites
    fields, _ = apply_hwpx(package, {"type": "create_field", "name": "구분", **selection,
                                     "ranges": [selection, *sites]})
    return {"batch-fields.hwpx": fields.to_bytes()}


def _generated_verdicts(tmp_path: Path, outputs: dict[str, bytes]) -> dict[str, tuple[str, ...]]:
    """제품이 만든 문서를 동봉 편집기로 한 번 왕복해 보존 판정 종류를 모은다."""
    from playwright.sync_api import sync_playwright  # 지역 import — 옵트아웃 러너에 playwright 불요

    for name, content in outputs.items():
        (tmp_path / name).write_bytes(content)
    verdicts: dict[str, tuple[str, ...]] = {}
    with _loopback(tmp_path) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 1000})
            page.goto(base + _HARNESS_PATH, wait_until="load")
            page.wait_for_function("() => window.harnessReady === true")
            for name, content in outputs.items():
                result = page.evaluate("([u, n]) => window.roundtrip(u, n)", [base + "/__generated__/" + name, name])
                assert "error" not in result, result
                verdict = compare_rhwp_roundtrip(content, base64.b64decode(result["exported"]))
                verdicts[name] = tuple(sorted(item["kind"] for item in verdict["diagnostics"]))
        finally:
            browser.close()
    return verdicts


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_GATE_REASON)
def test_batch_command_outputs_roundtrip_editable(tmp_path: Path) -> None:
    """IDE-07 — 한 명령 안의 여러 누름틀 삽입이 rhwp 왕복 보존 판정을 깨지 않는다."""
    outputs = _batch_outputs()
    assert _generated_verdicts(tmp_path, outputs) == {name: () for name in outputs}


#: 입찰 공고 표본의 문단 35·36 은 ``<hp:t> </hp:t>`` 앞글자 뒤에 글자처럼 취급한 1x1 표가 오는
#: 문단이다. 영역이 이 문단에서 끝나면 책갈피 종료가 표 **뒤**에 놓인다(문단 전체가 영역).
_TABLE_END_SOURCE = "real/bid_notice_limited_under100m.hwpx"


def _table_end_region_outputs() -> dict[str, bytes]:
    """문단 말미 표로 끝나는 영역 — 편집기가 종료를 표 앞으로 당기면 영역이 표를 잃는다.

    ``{{/선택}}`` 을 표 바로 다음 문단에 둔 템플릿을 컴파일하면 선택 영역이 이렇게 끝난다.
    당겨진 문서는 커널이 부분 문단 종료로 거절해 생성에서 지울 수 없게 되므로, 보존 판정이
    읽기 전용으로 막은 것이 옳았다 — 고칠 곳은 편집기 직렬화기다(``OrphanFieldEnd``).
    """
    from hwpxfiller.external.hwpx_authoring import apply_hwpx
    from hwpxfiller.external.hwpx_package_io import read_hwpx_package

    entry = "Contents/section0.xml"
    outputs: dict[str, bytes] = {}
    for end in (35, 36):
        package = read_hwpx_package(CORPUS / _TABLE_END_SOURCE)
        created, _ = apply_hwpx(package, {"type": "create_slot", "entry": entry, "start_paragraph": 20,
                                          "end_paragraph": end, "id": "a"})
        outputs[f"slot-20-{end}-table-end.hwpx"] = created.to_bytes()
    return outputs


def _trailing_empty_field_outputs() -> dict[str, bytes]:
    """문단 끝 빈 누름틀 뒤에서 끝나는 영역 — 종료가 누름틀 ``fieldBegin`` 앞으로 당겨지면
    누름틀이 영역 밖으로 빠진다. 코퍼스에 이 모양이 없어 표본 문단 34 끝에 제품 누름틀
    표기(``domain.authoring``)로 빈 누름틀을 덧붙여 만든다. 누름틀만 있는 문서도 함께 잰다 —
    그 문서가 왕복에서 변하면 영역 판정이 무엇을 재는지 흐려진다.
    """
    import lxml.etree as etree

    from hwpxfiller.external.hwpx_authoring import apply_hwpx
    from hwpxfiller.external.hwpx_package_io import read_hwpx_package
    from hwpxcore.lineseg import serialize_modified_section

    entry = "Contents/section0.xml"
    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    package = read_hwpx_package(CORPUS / _TABLE_END_SOURCE)
    root = etree.fromstring(package.entries[entry])
    paragraph = [child for child in root if child.tag == f"{hp}p"][34]
    run = [child for child in paragraph if child.tag == f"{hp}run"][-1]
    begin = etree.SubElement(etree.SubElement(run, f"{hp}ctrl"), f"{hp}fieldBegin")
    for name, value in (("id", "1700000001"), ("type", "CLICK_HERE"), ("name", "끝"), ("editable", "1"),
                        ("dirty", "1"), ("zorder", "-1"), ("fieldid", "1700000002"), ("metaTag", "")):
        begin.set(name, value)
    end = etree.SubElement(etree.SubElement(run, f"{hp}ctrl"), f"{hp}fieldEnd")
    end.set("beginIDRef", "1700000001")
    end.set("fieldid", "1700000002")
    package.entries[entry] = serialize_modified_section(root)
    field_only = package.to_bytes()
    created, _ = apply_hwpx(package, {"type": "create_slot", "entry": entry, "start_paragraph": 20,
                                      "end_paragraph": 34, "id": "a"})
    return {"trailing-empty-field.hwpx": field_only, "slot-20-34-trailing-empty-field.hwpx": created.to_bytes()}


def test_generated_region_ends_really_follow_the_trailing_object() -> None:
    """위 두 표본이 재려는 모양 그대로다 — 종료가 문단 마지막 표·누름틀 **뒤**에 있다."""
    import zipfile
    from io import BytesIO

    import lxml.etree as etree

    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    cases = {**_table_end_region_outputs(), **_trailing_empty_field_outputs()}
    del cases["trailing-empty-field.hwpx"]
    for name, content in cases.items():
        root = etree.fromstring(zipfile.ZipFile(BytesIO(content)).read("Contents/section0.xml"))
        end = next(node for node in root.iter(f"{hp}fieldEnd")
                   if node.get("beginIDRef") == next(node.get("id") for node in root.iter(f"{hp}fieldBegin")
                                                     if node.get("type") == "BOOKMARK"))
        paragraph = end.getparent().getparent().getparent()
        trailing = [node for run in paragraph if run.tag == f"{hp}run" for node in run
                    if not (node.tag == f"{hp}t" and not len(node) and not node.text)]
        before = trailing[trailing.index(end.getparent()) - 1]
        kinds = {etree.QName(child).localname for child in before.iter()}
        assert kinds & {"tbl", "fieldEnd"}, (name, kinds)


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_GATE_REASON)
def test_region_ending_after_trailing_object_roundtrips_editable(tmp_path: Path) -> None:
    """영역 종료가 문단 끝 표·빈 누름틀 뒤에 있어도 편집기 왕복이 그 자리를 지킨다."""
    outputs = {**_table_end_region_outputs(), **_trailing_empty_field_outputs()}
    assert _generated_verdicts(tmp_path, outputs) == {name: () for name in outputs}
