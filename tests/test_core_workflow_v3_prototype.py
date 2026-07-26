from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "docs" / "core-workflow-ui-mvp-demo-v3.html"
DOC_PATH = ROOT / "docs" / "core-workflow.md"
CONTRACT_PATH = ROOT / "docs" / "core-workflow-prototype" / "contracts.js"
MOCK_PATH = ROOT / "docs" / "core-workflow-prototype" / "mock-backend.js"


class _ContractParser(HTMLParser):
    interactive = {"button", "a", "input", "select", "textarea"}

    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.references: list[tuple[str, str]] = []
        self.stack: list[str] = []
        self.nested_interactive: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        for key in ("aria-labelledby", "aria-describedby", "aria-controls", "for"):
            if values.get(key):
                for target in str(values[key]).split():
                    self.references.append((key, target))
        if tag in self.interactive:
            parent = next((item for item in reversed(self.stack) if item in self.interactive), None)
            if parent is not None:
                self.nested_interactive.append((parent, tag))
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            reverse_index = self.stack[::-1].index(tag)
            del self.stack[len(self.stack) - reverse_index - 1 :]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v3_is_a_new_standalone_prototype() -> None:
    html = _read(HTML_PATH)

    assert HTML_PATH.exists()
    assert "편집 워크플로 시안 v3" in html
    assert "core-workflow-ui-mvp-demo-v2.html" not in html
    assert html.index("core-workflow-prototype/contracts.js") < html.index(
        "core-workflow-prototype/mock-backend.js"
    ) < html.index("<script>\n(()=>")


def test_global_information_architecture_replaces_settings_mode() -> None:
    html = _read(HTML_PATH)

    assert 'data-nav="data"' in html
    assert 'data-nav="library"' in html
    assert 'data-nav="settings"' not in html
    assert ">문서 설정</button>" not in html
    assert 'id="documentSettingsButton"' not in html
    assert 'id="connectionButton"' not in html
    assert "템플릿 변경" in html
    assert "데이터 연결 변경" in html
    assert "생성 방식 변경" in html


def test_v3_edit_and_return_context_contract_is_centralized() -> None:
    html = _read(HTML_PATH)
    contract = _read(CONTRACT_PATH)

    assert "const workflowV3" in contract
    assert "const editContract" in contract
    for section in ("template", "binding", "execution", "test"):
        assert f'"{section}"' in contract
    for reason in (
        "schema_new_field",
        "schema_missing_field",
        "preview_result",
        "run_failure",
        "output_result",
        "workbench_result",
    ):
        assert f'"{reason}"' in contract
        assert reason in html
    assert "function openWorkEditor(editContext)" in html
    assert "function returnFromWorkEditor(" in html
    assert "returnContext.surface" in html
    assert "previewIndex" in html
    assert "workIndex" in html


def test_canonical_workflow_document_defines_the_v3_contract() -> None:
    document = _read(DOC_PATH)

    assert "문서 설정은 독립 단계가 아니다." in document
    assert "### 7.3 EditContext 계약" in document
    assert "### 7.4 적용 범위" in document
    assert "### 7.5 ReturnContext와 복귀 불변식" in document
    assert "`RunDraftOverride`" in document
    assert "`ExecutionProfile`" in document
    assert "미리보기 지급일 deep-link" in document
    assert "온나라 작업대 영구 규칙" in document
    assert document.count("```mermaid") == 9


def test_scope_model_separates_override_and_revisions() -> None:
    html = _read(HTML_PATH)
    mock = _read(MOCK_PATH)

    assert "runOverrides:{}" in html
    assert "executionProfiles:clone(initialProfiles)" in html
    assert "schemaSuggestionDismissed:new Set()" in html
    assert "saveRunOverride" in mock
    assert "saveEditorChange" in mock
    assert "storeRunOverride" in html
    assert "applyBindingDraftToBase" in html
    assert "delete state.runOverrides[docId].fields[target.id]" in html
    assert "delete state.runOverrides[docId].execution[target.id]" in html
    assert "state.preview.approved=false" in html
    assert "PreviewCreated이며 PreviewApproved는 아닙니다." in html
    assert "저장하지 않은 변경은 적용하지 않았습니다." in html


def test_required_evidence_deep_links_are_present() -> None:
    html = _read(HTML_PATH)

    for copy in (
        "상여금에 연결",
        "이번에는 사용하지 않음",
        "이름 연결 복구",
        "원본 파일에서 수정",
        "표시 변경",
        "이름 규칙 변경",
        "문서 내용·구조 · 템플릿 열기",
        "충돌 정책 변경",
        "원인 진단 미연결",
    ):
        assert copy in html
    assert 'data-preview-edit="binding:date"' in html
    assert 'data-preview-edit="execution:filenamePattern"' in html
    assert 'data-preview-edit="template:structure"' in html
    assert 'id="failed-output-5"' in html
    assert "실패 당시 충돌 정책은 ‘중단’이었습니다." in html


def test_workbench_session_and_permanent_rules_are_distinct() -> None:
    html = _read(HTML_PATH)

    assert "이번 작업에만 적용 중" in html
    assert "이후에도 이 규칙 사용" in html
    assert "Template 저장이 아닙니다." in html
    assert 'data-work-result-target="${key}"' in html
    assert "state.workIndex=returnContext.workIndex" in html
    assert "saveTemplateButton" not in html


def test_static_ids_references_and_interactive_nesting_are_valid() -> None:
    html = _read(HTML_PATH)
    parser = _ContractParser()
    parser.feed(html)

    assert len(parser.ids) == len(set(parser.ids))
    known_ids = set(parser.ids)
    assert all(target in known_ids for _, target in parser.references)
    assert parser.nested_interactive == []

    referenced_ids = set(re.findall(r'\$\("([^"]+)"\)', html)) - {"selectAll"}
    assert referenced_ids <= known_ids


def test_accessibility_and_responsive_contracts_are_retained() -> None:
    html = _read(HTML_PATH)

    assert 'aria-modal="true"' in html
    assert 'aria-hidden="true" inert' in html
    assert "document.querySelector(\".app\").inert=true" in html
    assert "document.querySelector(\".app\").inert=false" in html
    assert 'event.key!=="Escape"' in html
    assert "@media(max-width:920px)" in html
    assert "@media(max-width:580px)" in html
    assert "@media(prefers-reduced-motion:reduce)" in html
