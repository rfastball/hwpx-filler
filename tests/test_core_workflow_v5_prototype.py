from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs" / "core-workflow-ui-mvp-demo-v5.html"
SCRIPT = ROOT / "docs" / "core-workflow-prototype" / "v5.js"
STYLE = ROOT / "docs" / "core-workflow-prototype" / "v5.css"
CONTRACT = ROOT / "docs" / "core-workflow-prototype" / "contracts.js"
MOCK = ROOT / "docs" / "core-workflow-prototype" / "mock-backend.js"


class ContractParser(HTMLParser):
    interactive = {"button", "a", "input", "select", "textarea"}
    void = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.references: list[str] = []
        self.stack: list[str] = []
        self.nested: list[tuple[str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        for key in ("aria-labelledby", "aria-describedby", "aria-controls", "for"):
            if values.get(key):
                self.references.extend(str(values[key]).split())
        if tag in self.interactive:
            parent = next(
                (item for item in reversed(self.stack) if item in self.interactive),
                None,
            )
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


def test_v5_is_distinct_and_keeps_v4_as_comparison() -> None:
    html = read(HTML)
    assert "데이터 선택 통합 시안 v5" in html
    assert "core-workflow-prototype/v5.css?v=" in html
    assert "core-workflow-prototype/v5.js?v=" in html
    assert (ROOT / "docs" / "core-workflow-ui-mvp-demo-v4.html").exists()


def test_data_identity_state_axes_and_reference_persistence_contract() -> None:
    html, script = read(HTML), read(SCRIPT)
    for token in (
        "documentWorkState",
        "editState",
        "runState",
        "workbenchState",
        "dataState",
        "mountedDataRef",
        "pendingMount",
        "runtimeData",
        "datasetRefName",
    ):
        assert token in script
    assert "state.scenario" not in script
    assert "scenarioSelect" not in html + script
    assert "narmi.prototype.mounted-data.v2" in script
    assert "narmi.prototype.dataset-pool.v1" in script
    assert "localStorage.setItem" in script
    for forbidden in ("PinnedDataRegistry", "pinId", "직원 데이터로 인식됨"):
        assert forbidden not in html + script


def test_data_picker_sheet_choice_atomic_switch_and_guard_are_clickable() -> None:
    html, script, mock = read(HTML), read(SCRIPT), read(MOCK)
    for element_id in (
        "currentDataCard",
        "changeData",
        "pinCurrentData",
        "dataPickerDialog",
        "sheetPickerDialog",
        "dataSwitchGuardDialog",
        "pinDataDialog",
        "pinnedDataList",
        "mockFileList",
        "sheetList",
    ):
        assert f'id="{element_id}"' in html
    for element_id in (
        "changeData",
        "pinCurrentData",
        "dataPickerDialog",
        "sheetPickerDialog",
        "dataSwitchGuardDialog",
        "pinDataDialog",
        "pinnedDataList",
        "mockFileList",
        "sheetList",
    ):
        assert f'$("{element_id}")' in script
    for token in (
        "inspectDataFile",
        "mountDataTarget",
        "commitPreparedMount",
        "switchLosses",
        "resetDataOwnedState",
    ):
        assert token in script + mock
    assert "file.sheets.length > 1 && !sheet" in mock
    assert "SHEET_REQUIRED" in mock
    load_candidate = re.search(
        r"async function loadCandidate\(.*?\n  \}", script, flags=re.DOTALL
    )
    assert load_candidate
    assert load_candidate.group(0).index(
        "await actions.mountDataTarget"
    ) < load_candidate.group(0).index("acceptPreparedMount")
    for label in ("약 ${sheet.rows}행×${sheet.columns}열", "header-sample"):
        assert label in script
    assert "시안용 샘플 목록" in html
    assert "Windows 탐색기를 엽니다." in html
    assert "이 샘플 선택" in script
    assert "#dataPickerDialog,#helpDialog" in read(STYLE)
    assert "width:min(820px,calc(100vw - 32px))" in read(STYLE)


def test_compatible_works_use_required_sources_not_dataset_labels() -> None:
    script = read(SCRIPT)
    assert "function compatibilityFor(workId,currentFields=currentColumns())" in script
    for reason in ("source_missing", "constant_missing", "source_not_present"):
        assert reason in script
    assert 'selected==="__direct__"?"selected":""' in script
    assert 'compatibilityFor(workId).kind==="needsAction"' in script
    assert 'compatibilityFor(work.id).kind==="available"' in script
    assert "compatibleWorks()" in script
    assert "dataset.startsWith" not in script
    assert "필요 항목이 일치합니다." not in script
    assert "필요 항목 일치 ·" not in script
    assert '$("compatNote").hidden=true' in script
    assert '$("validationCard").hidden=!noSelection&&!noWork&&!bad&&!pending&&!gated' in script
    assert '$("workflowStrip").hidden=' in script
    for file_name in (
        "8월_ERP급여.xlsx",
        "9월_ERP급여.xlsx",
        "인사자료.xlsx",
        "고객_요청목록.csv",
        "손상된_급여.xlsx",
    ):
        assert file_name in script
    for sheet_name in ("급여현황", "부서별 합계", "안내", "재직자", "퇴직자"):
        assert sheet_name in script


def test_job_default_dataset_is_a_confirmed_hint_not_an_auto_switch() -> None:
    html, script = read(HTML), read(SCRIPT)
    assert "default_dataset_ref" in script
    assert 'id="browseOtherWorks"' in html
    assert 'id="defaultDataSuggestionDialog"' in html
    assert "기본 데이터 참조는 조준 힌트입니다." in html
    assert "사용자 확인 없이 현재 데이터를 바꾸지 않습니다." in html
    assert '$("defaultDataSuggestionDialog").returnValue!=="switch"' in script
    assert "preferredWorkId" in script


def test_extension_contract_is_valid_json_and_self_contained() -> None:
    html = read(HTML)
    match = re.search(
        r'<script type="application/json" id="prototype-extension-contract">\s*'
        r"(.*?)\s*</script>",
        html,
        flags=re.DOTALL,
    )
    assert match
    contract = json.loads(match.group(1))
    assert contract["version"] == "v5-record-range"
    assert contract["dataTarget"]["excel"] == ["path", "sheet", "headerRow?"]
    assert "DatasetPoolRegistry" in contract["reuseBackend"]
    assert "LoadedDataSnapshot records" in contract["notPersisted"]
    assert contract["testOnlyControls"] == {
        "includedInProductMock": False,
        "purpose": "ordered mock scenario switching",
        "productionEquivalent": None,
    }
    for heading in (
        "현재 데이터의 정체성",
        "영속되는 것",
        "영속되지 않는 것",
        "실행 데이터와 범위",
        "백엔드 경계",
        "구현하지 않는 것",
    ):
        assert heading in html


def test_test_harness_is_explicitly_outside_product_mock_and_ordered() -> None:
    html, script, style = read(HTML), read(SCRIPT), read(STYLE)
    assert 'id="testHarness" data-prototype-only="true"' in html
    assert "테스트 전용" in html
    assert "제품 UI 아님" in html
    assert "제품 목업·구현 범위에서 제외됩니다." in html
    assert html.index("</main>\n</div>") < html.index('id="testHarness"')
    assert "prototype-controls" not in html + style
    assert "data-prototype-state" not in html + script
    assert html.index('id="testHarness"') < html.index('id="outcomeSelect"')
    assert "const testScenarios = [" in script
    expected = (
        "① 데이터 없이 시작",
        "② 기존 형식 데이터 연결",
        "③ 새 항목이 추가된 데이터",
        "④ 다른 구조의 시트 선택",
        "⑤ 작업에 맞지 않는 시트 선택",
        "⑥ 기존 작업과 맞지 않는 데이터",
        "⑦ 고정 데이터 다시 사용",
        "⑧ 고정 데이터 연결 끊김",
        "⑨ 손상 파일 실패",
        "⑩ 작업 중 데이터 바꾸기",
        "⑪ 누적 직원 데이터 · 320건",
    )
    positions = [script.index(label) for label in expected]
    assert positions == sorted(positions)
    for element_id in (
        "testScenarioCurrent",
        "testScenarioPrev",
        "testScenarioNext",
        "testScenarioList",
    ):
        assert f'id="{element_id}"' in html
    for element_id in ("testScenarioCurrent", "testScenarioList"):
        assert f'$("{element_id}")' in script
    assert '#testScenarioPrev' in script
    assert '#testScenarioNext' in script
    assert "applyTestScenario" in script
    assert 'data-test-scenario="' in script
    assert ".test-harness" in style


def test_static_markup_accessibility_and_responsive_contract() -> None:
    parser = ContractParser()
    parser.feed(read(HTML))
    assert len(parser.ids) == len(set(parser.ids))
    assert set(parser.references) <= set(parser.ids)
    assert parser.nested == []
    script_ids = set(re.findall(r'\$\("([^"]+)"\)', read(SCRIPT))) - {
        "selectAll",
        "rangeEditorSelectAll",
        "resultMoreMenu",
    }
    assert script_ids <= set(parser.ids)
    style = read(STYLE)
    assert "@media(max-width:920px)" in style
    assert "@media(max-width:580px)" in style
    assert "@media(prefers-reduced-motion:reduce)" in style
    script = read(SCRIPT)
    assert 'event.key!=="Tab"' in script
    assert "dialogOpeners" in script
    assert 'event.key!=="Escape"' in script


def test_central_contract_preserves_v4_and_adds_v5_data_stage() -> None:
    contract = read(CONTRACT)
    assert "const workflowV4" in contract
    assert "const workflowV5" in contract
    assert "const dataExtensionV5" in contract
    assert "const recordRangeV5" in contract
    for token in (
        "inspectDataFile",
        "chooseSheet",
        "mountDataTarget",
        "atomicCommit",
        "datasetPoolProjection",
        "automaticDatasetCatalog",
    ):
        assert token in contract


def test_current_data_document_browser_is_a_distinct_spa_surface() -> None:
    html, script, style, contract = (
        read(HTML), read(SCRIPT), read(STYLE), read(CONTRACT)
    )
    for element_id in (
        "screen-documents",
        "documentsTitle",
        "documentsBack",
        "documentsAvailableTab",
        "documentsNeedsActionTab",
        "documentSearch",
        "documentsPanel",
        "documentBrowserList",
        "documentsNotice",
    ):
        assert f'id="{element_id}"' in html
        if element_id != "screen-documents":
            assert f'$("{element_id}")' in script
    assert 'role="tablist"' in html
    assert 'role="tabpanel"' in html
    assert "ArrowLeft" in script and "ArrowRight" in script
    assert 'const navView=["documents","record-range"].includes(view)?"data":view' in script
    assert 'id="incompatibleWorkDialog"' not in html
    assert "incompatibleWorkList" not in script
    assert "이 데이터에 사용할 문서 보기" in html
    assert "documentSelectionV5" in contract
    for selector in (
        ".documents-shell",
        ".document-tabs",
        ".document-card",
        ".document-search",
    ):
        assert selector in style


def test_main_document_candidates_are_ranked_and_capped_without_auto_selection() -> None:
    html, script = read(HTML), read(SCRIPT)
    assert "const MAIN_DOCUMENT_LIMIT = 5" in script
    assert "sortedAvailableWorks()" in script
    assert "visible=eligible.slice(0,MAIN_DOCUMENT_LIMIT)" in script
    assert '["즐겨찾기",visible.filter' in script
    assert '["최근 사용",visible.filter' in script
    assert '["다른 문서",visible.filter' in script
    assert "favoritedAt" in script
    assert "last_run_at" in script
    assert "eligible[0]?.id" not in script
    assert "else if(eligible.length===1)state.activeWorkId=eligible[0].id" in script
    assert "else state.activeWorkId=null" in script
    assert 'id="workCount" aria-live="polite"' in html


def test_favorite_controls_are_separate_metadata_only_actions() -> None:
    script = read(SCRIPT)
    assert "narmi.prototype.work-favorites.v1" in script
    assert 'aria-pressed="${favorite}"' in script
    assert "즐겨찾기에 추가" in script
    assert "즐겨찾기에서 제거" in script
    toggle = re.search(
        r"function toggleFavorite\(workId\) \{.*?\n\s*\}", script, flags=re.DOTALL
    )
    assert toggle
    body = toggle.group(0)
    for forbidden in (
        "state.activeWorkId=",
        "state.validation=",
        "state.preview=",
        "bindingRevision",
        "templateRevision",
    ):
        assert forbidden not in body
    assert "event.stopPropagation();toggleFavorite" in script


def test_needs_action_routes_do_not_collapse_to_binding_repair() -> None:
    script = read(SCRIPT)
    for reason_kind in (
        "bindingDrift",
        "defaultData",
        "brokenReference",
        "differentData",
        "templateOnly",
        "damaged",
    ):
        assert f'reasonKind:"{reason_kind}"' in script
    for action in (
        "openBindingRepair",
        "proposeDefaultData",
        "startNewWorkFromEntry",
        "relinkDefault",
    ):
        assert action in script
    assert 'entryReason:"document_browser_repair"' in script
    assert 'entryReason:returnContext.surface==="documents"?' in script
    assert "makeDocumentBrowserReturn" in script
    assert 'context.returnContext.surface==="documents"' in script
    assert 'ret.surface==="documents"' in script
    assert 'state.documentBrowser.tab=updatedEntry.status' in script


def test_document_search_is_name_only_and_selection_preserves_data_context() -> None:
    script = read(SCRIPT)
    assert "entry.name.toLowerCase().includes(query)" in script
    select = re.search(
        r"function selectDocumentWork\(.*?\n\s*\}", script, flags=re.DOTALL
    )
    assert select
    body = select.group(0)
    assert "state.activeWorkId=workId" in body
    assert "requestValidation()" in body
    for forbidden in (
        "dataState.runtimeData=",
        "state.records=",
        "state.selected=",
        "state.search=",
    ):
        assert forbidden not in body


def test_core_workflow_integrates_v4_editor_and_v5_document_loop() -> None:
    workflow = read(ROOT / "docs" / "core-workflow.md")
    for token in (
        "Excel DataTarget = path + sheet + optional headerRow",
        'dataState.runtimeData.loadState === "ready"',
        "compatibilityFor(workId, runtimeFields)",
        "메인에는 draft와 손상 작업을 제외한 `available` 저장 작업만 최대 5개",
        '`screen-documents`',
        '`surface = "documents"`',
        "`document_browser_repair`",
        "`document_browser_new_work`",
        "우선 노출은 활성 작업 선택 사건이 아니다",
        "LoadedDataSnapshot",
        "RecordRangeState",
        "OrderedSelection",
        "선택 0건",
        "CreateRun이나",
    ):
        assert token in workflow


def test_record_range_has_one_owner_and_pure_ordered_derivations() -> None:
    script = read(SCRIPT)
    assert "recordRange:emptyRecordRange()" in script
    assert 'viewOrder:"sourceDesc"' in script
    assert "selectedIds:new Set()" in script
    assert "runtimeData:{loadState:\"empty\",snapshotId:null" in script
    for forbidden in (
        "selectedRecordIds",
        "runState.records",
        "runState.selected",
        "runState.filters",
        "selectedRecords()",
        "state.records[0]",
    ):
        assert forbidden not in script
    for helper in (
        "orderedSnapshotRecords",
        "filteredRecordIds",
        "visibleOrderedRecords",
        "orderedSelectedRecords",
        "hiddenSelectedRecords",
        "headerSelectionState",
        "selectionFingerprint",
    ):
        assert f"function {helper}" in script
    assert "snapshotRecordId" in script
    assert "snapshotOrdinal" in script
    assert "sourceRowNumber" in script


def test_record_range_main_editor_and_filter_contract_are_clickable() -> None:
    html, script, style = read(HTML), read(SCRIPT), read(STYLE)
    for element_id in (
        "recordFilterButton",
        "recordOrder",
        "recordRangeButton",
        "clearRecordSelection",
        "hiddenSelectionSummary",
        "screen-record-range",
        "rangeEditorSearch",
        "rangeEditorFilterButton",
        "rangeEditorOrder",
        "rangeEditorSelectedOnly",
        "rangeEditorApply",
        "rangeEditorCancel",
        "recordFilterDialog",
        "recordRangeGuardDialog",
    ):
        assert f'id="{element_id}"' in html
        if element_id != "screen-record-range":
            assert f'$("{element_id}")' in script
    assert "현재 검색·필터 결과 모두 선택" in script
    assert "slice(0,3)" in script
    assert "Array.isArray(filter.values)" in script
    assert "Object.entries(rangeState.columnFilters).every" in script
    assert ".record-range-editor-tools" in style
    assert ".range-table-wrap" in style


def test_ordered_selection_drives_preview_hwpx_and_txt_session() -> None:
    script = read(SCRIPT)
    assert "records=orderedSelectedRecords()" in script
    assert "recordIds:records.map(recordKey)" in script
    assert "workbenchState.session={snapshotId:dataState.runtimeData.snapshotId,records:records.map(clone),index:0}" in script
    assert "function workRecord(){return workbenchState.session?.records[state.workIndex]||null}" in script
    assert "if(!records.length){showNotice(\"처리할 항목을 선택하세요.\"" in script
    assert '$("previewButton").disabled=noSelection' in script


def test_mount_resets_to_none_and_switch_guard_describes_real_range_losses() -> None:
    script = read(SCRIPT)
    reset = re.search(
        r"function resetDataOwnedState\(.*?\n\s*\}", script, flags=re.DOTALL
    )
    assert reset
    assert "runState.recordRange=emptyRecordRange(snapshotId)" in reset.group(0)
    assert "workbenchState.session=null" in reset.group(0)
    assert "range.selectedIds.size" in script
    assert "activeFilterCount(range)" in script
    assert 'range.viewOrder!=="sourceDesc"' in script
    assert "rangeEditor?.dirty" in script
    assert "state.selected.size!==state.records.length" not in script


def test_record_scale_fixture_and_benchmark_helpers_exist() -> None:
    html, script = read(HTML), read(SCRIPT)
    assert "누적_직원_데이터.xlsx" in script
    assert "records:makeScaleRecords(320)" in script
    assert "window.loadRecordScale" in script
    assert "window.measureRecordRangePerformance" in script
    assert "Math.min(3000" in script
    for scale in (50, 100, 300, 500, 1000, 3000):
        assert f'data-record-scale="{scale}"' in html
    for metric in (
        "renderMs",
        "searchMs",
        "filterMs",
        "orderMs",
        "selectVisibleMs",
        "unselectVisibleMs",
        "clearAllMs",
        "editorEnterMs",
        "selectedOnlyMs",
        "applyMainMs",
        "domRows",
        "htmlBytes",
    ):
        assert f"result.{metric}" in script
