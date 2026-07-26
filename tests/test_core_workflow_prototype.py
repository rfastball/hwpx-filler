from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "docs" / "core-workflow-ui-mvp-demo-v2.html"
CONTRACT_PATH = ROOT / "docs" / "core-workflow-prototype" / "contracts.js"
MOCK_PATH = ROOT / "docs" / "core-workflow-prototype" / "mock-backend.js"


class _IdAndReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.references: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        for key in ("aria-labelledby", "aria-describedby", "for"):
            if values.get(key):
                for target in str(values[key]).split():
                    self.references.append((key, target))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_prototype_contract_and_mock_are_loaded_before_ui() -> None:
    html = _read(HTML_PATH)
    contracts = "core-workflow-prototype/contracts.js"
    mock_backend = "core-workflow-prototype/mock-backend.js"

    assert html.index(contracts) < html.index(mock_backend) < html.index("<script>\n(()")
    assert "const workflow=window.WorkflowContract.workflow;" in html
    assert "const actions=window.documentActions;" in html
    assert "window.documentActions = mockDocumentWorkflow;" in _read(MOCK_PATH)


def test_workflow_contract_has_required_transition_metadata() -> None:
    contract = _read(CONTRACT_PATH)

    for step in ("data", "settings", "connection", "preview", "workbench", "result"):
        assert f"{step}: {{" in contract
    for field in (
        "entryCondition:",
        "completionCondition:",
        "primaryAction:",
        "next:",
        "back:",
        "failure:",
        "actions:",
        "restrictions:",
    ):
        assert field in contract


def test_capability_contract_uses_all_support_states() -> None:
    contract = _read(CONTRACT_PATH)

    for status in ("supported", "composed", "unsupported", "deferred", "removed"):
        assert f'status: "{status}"' in contract
    assert "pixelPerfectHwpxPreview" in contract
    assert "editTxtTemplate" in contract
    assert "liveCollaboration" in contract


def test_runtime_state_axes_and_recovery_scenarios_are_explicit() -> None:
    html = _read(HTML_PATH)
    contract = _read(CONTRACT_PATH)

    for axis in ("validation:{", "backend:{", "save:{", "preview:{"):
        assert axis in html
    for scenario in (
        "previewFailure",
        "saveFailure",
        "partialResult",
        "processingFailure",
    ):
        assert scenario in contract
        assert scenario in html
    for recovery_control in (
        'id="resolvePreviewFailureButton"',
        'id="resolveFailureButton"',
        'id="cancelRunButton"',
        'id="connectionSaveState"',
    ):
        assert recovery_control in html
    assert "원인 확인 전 재실행을 주 행동으로 두지 않음" in contract
    assert "실패 항목 다시 실행</button>" not in html


def test_preview_open_and_approval_are_separate_events() -> None:
    html = _read(HTML_PATH)
    open_preview = html[html.index("async function openPreview()"): html.index(
        "function closePreview()"
    )]
    approve_preview = html[html.index("function approvePreview()"): html.index(
        "async function executeDocuments"
    )]

    assert "approved=true" not in open_preview
    assert "state.preview.approved=true" in approve_preview
    assert 'id="approvePreviewButton"' in html
    assert "HWPX 생성 미리보기" not in html
    assert "생성 값 미리보기" in html


def test_native_confirm_is_replaced_and_dialog_references_are_valid() -> None:
    html = _read(HTML_PATH)
    parser = _IdAndReferenceParser()
    parser.feed(html)

    assert "window.confirm" not in html
    assert "window.prompt" not in html
    assert len(parser.ids) == len(set(parser.ids))
    known_ids = set(parser.ids)
    assert all(target in known_ids for _, target in parser.references)
    assert 'id="missingValueDialog"' in html
    assert 'aria-labelledby="missingValueTitle"' in html
    assert 'id="previewDrawer" role="dialog" aria-modal="true"' in html


def test_deferred_features_are_not_presented_as_successful_current_actions() -> None:
    html = _read(HTML_PATH)

    assert '>텍스트 템플릿 편집</button>' not in html
    assert "텍스트 편집 지원 범위" in html
    assert "현재 범위에서 연기되었습니다" in html
    assert "이 HTML 시안은 파일을 열지 않으며" in html
    assert "시안 상태 전환:" in html


def test_user_visible_mapping_term_is_consistent() -> None:
    html = _read(HTML_PATH)

    assert "<span>데이터 열</span>" not in html
    assert " 데이터 열\">" not in html
    assert "데이터 항목" in html


def test_inferred_type_can_be_corrected_and_limits_format_options() -> None:
    html = _read(HTML_PATH)
    contract = _read(CONTRACT_PATH)

    assert 'data-kind="type"' in html
    assert "샘플 값으로 추론됨 · 다르면 변경" in html
    assert "const formatCatalog" in html
    assert "recommendedFormat" in html
    assert "추론된 유형이 실제와 다름" not in html
    assert "typeReview" not in html
    assert "inferValueType" in contract


def test_direct_input_is_a_source_option_with_literal_value() -> None:
    html = _read(HTML_PATH)
    contract = _read(CONTRACT_PATH)

    assert '>직접 입력</option>' in html
    assert 'data-kind="constant"' in html
    assert 'data-work-kind="constant"' in html
    assert "directValue" in contract


def test_unknown_schema_has_no_automatic_document_recommendation() -> None:
    html = _read(HTML_PATH)
    contract = _read(CONTRACT_PATH)

    assert 'id="newConnectionEmpty"' in html
    assert "유사 스키마 자동 추천은 하지 않으며" in html
    assert 'newConnection:{phase:"idle",targetDocument:null}' in html
    for phase in (
        "unselected",
        "choosing",
        "targetSelected",
        "editing",
        "savedPendingPreview",
        "ready",
    ):
        assert f"{phase}: {{" in contract
    assert "recommendDocumentWork" in contract


def test_new_connection_notice_keeps_one_working_primary_action() -> None:
    html = _read(HTML_PATH)

    assert 'const customerNeedsTarget=state.scenario==="customer"&&!state.document;' in html
    assert 'customerNeedsConnection=state.scenario==="customer"&&s.level==="missing"' in html
    assert '"compatAction").classList.toggle("primary"' in html
    assert 'state.scenario==="customer"&&!state.document?revealDocumentCatalog():openConnection()' in html


def test_selected_document_highlights_existing_connection_action_in_place() -> None:
    html = _read(HTML_PATH)

    assert 'const needsNewConnection=state.scenario==="customer"&&s.level==="missing";' in html
    assert '$("runActions").classList.toggle("one",isCopy);' in html
    assert '$("primaryRunButton").disabled=blocked;' in html
    assert '$("connectionButton").hidden=false;' in html
    assert '$("connectionButton").classList.toggle("primary",needsNewConnection);' in html
    assert '$("connectionButton").classList.toggle("ghost",!needsNewConnection);' in html
    assert '$("primaryRunButton").textContent=needsNewConnection?"새 연결 만들기"' not in html


def test_unsupported_template_and_output_samples_fail_loudly() -> None:
    html = _read(HTML_PATH)

    assert 'id="structureBoundary" hidden' in html
    assert "다른 문서의 구조를 대신 표시하지 않습니다." in html
    assert 'documentId==="employment"' in html
    assert "급여명세서 구조를 대신 표시하지 않습니다." in html
    assert 'if(state.scenario==="customer")return `<h3>새 연결 결과 확인 범위</h3>' in html
    assert "다른 데이터의 값을 대신 표시하지 않습니다." in html
    assert "실제 매핑 결과는 표시하지 않습니다." in html


def test_document_field_counts_match_prototype_field_definitions() -> None:
    html = _read(HTML_PATH)

    assert 'salary:{name:"급여명세서",mode:"batch",format:"한글 문서 HWPX",dataset:"직원 데이터",fieldCount:5,requiredCount:4}' in html
    assert 'employment:{name:"재직증명서",mode:"batch",format:"한글 문서 HWPX",dataset:"직원 데이터",fieldCount:3,requiredCount:2}' in html
