from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs" / "core-workflow-ui-mvp-demo-v4.html"
SCRIPT = ROOT / "docs" / "core-workflow-prototype" / "v4.js"
STYLE = ROOT / "docs" / "core-workflow-prototype" / "v4.css"
CONTRACT = ROOT / "docs" / "core-workflow-prototype" / "contracts.js"
DOCUMENT = ROOT / "docs" / "core-workflow.md"


class ContractParser(HTMLParser):
    interactive = {"button", "a", "input", "select", "textarea"}
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.references: list[str] = []
        self.stack: list[str] = []
        self.nested: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        for key in ("aria-labelledby", "aria-describedby", "aria-controls", "for"):
            if values.get(key):
                self.references.extend(str(values[key]).split())
        if tag in self.interactive:
            parent = next((item for item in reversed(self.stack) if item in self.interactive), None)
            if parent:
                self.nested.append((parent, tag))
        if tag not in self.void:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[index:]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v4_is_a_distinct_prototype_with_shared_backend_boundary() -> None:
    html = read(HTML)
    assert "편집 워크플로 시안 v4" in html
    assert "core-workflow-prototype/contracts.js" in html
    assert "core-workflow-prototype/mock-backend.js" in html
    assert "core-workflow-prototype/v4.js" in html
    assert (ROOT / "docs" / "core-workflow-ui-mvp-demo-v3.html").exists()


def test_media_specific_editor_and_actions() -> None:
    html, script = read(HTML), read(SCRIPT)
    for label in ("템플릿", "필드 연결·표시", "파일 이름", "시험"):
        assert label in html
    assert 'endsWith(".txt")' in script
    assert 'section==="filename"&&mediaFor(context.workId)==="txt"' in script
    assert "workMenuItems" in script
    for removed in ("실행 모드", "출력 위치", "충돌 정책", "다음부터 저장 방식 변경"):
        assert removed not in html
        assert removed not in script


def test_patch_only_transaction_and_dynamic_scopes() -> None:
    script, contract = read(SCRIPT), read(CONTRACT)
    for token in ("baseSnapshot", "inheritedRunOverrides", "patch", "effectiveDraft", "applyPatchToRun", "applyPatchToBase"):
        assert token in script
    assert "scopeActions()" in script
    assert "availableScopes" not in script
    assert "state.bindings[workId]=clone" not in script
    assert "const editContractV4" in contract
    assert '"saveUnit": "patch"' not in contract  # object literal, not JSON fiction
    assert 'saveUnit: "patch"' in contract


def test_removed_feature_has_no_v4_state_or_copy() -> None:
    source = read(HTML) + read(SCRIPT)
    for text in ("지급합계", "계산 근거", "기본급 + 상여금", "field.calc", "calculation"):
        assert text not in source
    assert not re.search(r"\bcalc\b", source)


def test_preview_actions_are_consistent_and_precise() -> None:
    script = read(SCRIPT)
    assert 'aria-label="${esc(field.label)} 수정">수정</button>' in script
    assert 'aria-label="파일 이름 수정">수정</button>' in script
    assert ">템플릿 열기</button>" in script
    assert "previewIndex:state.preview.index" in script
    assert "focusTarget:`preview-${key}`" in script
    assert "preview-filename-block" in script
    assert script.index("preview-template") < script.index("preview-filename-block")


def test_text_inputs_preserve_focus_and_missing_repair_uses_effective_binding() -> None:
    script = read(SCRIPT)
    assert "function renderEditorMeta()" in script
    assert "setPatch(section,key,change,{preserveInput=false}={})" in script
    assert 'setPatch("filename","filenamePattern",{filenamePattern:event.target.value},{preserveInput:true})' in script
    assert 'setPatch("binding",key,{constant:event.target.value,provenance:"user"},{preserveInput:true})' in script
    assert "const binding=effectiveField(workId,field.key)" in script
    assert 'state.preview.required=state.activeWorkId===context.workId' in script
    assert "if(hasRequiredIssue(context.workId))" in script


def test_new_field_missing_customer_and_runtime_recovery_paths() -> None:
    html, script = read(HTML), read(SCRIPT)
    for text in ("상여금에 연결", "이번에는 사용하지 않음", "이름 연결 복구", "원본 파일에서 수정", "이 데이터로 새 문서 작업 만들기"):
        assert text in html + script
    assert "createCustomerDraft" in script
    assert "draft:true" in script
    assert "completeNewWork" in script
    assert "records[recordId]={filename}" in script
    assert "retryFailedDocuments" in script
    assert "recordCount:1" in script
    assert "원인 진단 미연결" in html + script


def test_static_markup_is_accessible_and_references_exist() -> None:
    parser = ContractParser()
    parser.feed(read(HTML))
    assert len(parser.ids) == len(set(parser.ids))
    assert set(parser.references) <= set(parser.ids)
    assert parser.nested == []
    script_ids = set(re.findall(r'\$\("([^"]+)"\)', read(SCRIPT))) - {"selectAll", "resultMoreMenu"}
    assert script_ids <= set(parser.ids)
    html = read(HTML)
    assert 'aria-hidden="true" inert' in html
    assert 'role="tablist"' in html
    assert 'role="menu"' in html
    assert 'aria-live="polite"' in html
    style = read(STYLE)
    assert "@media(max-width:920px)" in style
    assert "@media(max-width:580px)" in style
    assert "@media(prefers-reduced-motion:reduce)" in style


def test_canonical_document_has_v4_contract_and_valid_mermaid_shape() -> None:
    document = read(DOCUMENT)
    for text in ("template_path", "filename_pattern", "baseSnapshot", "inheritedRunOverrides", "current patch", "PreviewCreated != PreviewApproved"):
        assert text in document
    assert document.count("```mermaid") == 9
    assert "## 15. 수용 시나리오" in document

    blocks = re.findall(r"```mermaid\n(.*?)```", document, flags=re.DOTALL)
    assert len(blocks) == 9
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        assert lines[0] in {"flowchart LR", "stateDiagram-v2"}
        assert block.count('"') % 2 == 0
        assert block.count("[") == block.count("]")
        assert block.count("{") == block.count("}")
        assert all(not line.endswith("-->") for line in lines)
        if lines[0] == "flowchart LR":
            declarations = re.findall(r"^\s*([A-Z][A-Z0-9_]*)\[", block, flags=re.MULTILINE)
            assert len(declarations) == len(set(declarations))
