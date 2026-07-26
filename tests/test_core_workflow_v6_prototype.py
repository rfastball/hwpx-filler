from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs" / "core-workflow-ui-mvp-demo-v6.html"
SCRIPT = ROOT / "docs" / "core-workflow-prototype" / "v6.js"
STYLE = ROOT / "docs" / "core-workflow-prototype" / "v6.css"
CONTRACT_DOC = ROOT / "docs" / "core-workflow.md"
PREVIOUS_HTML = ROOT / "docs" / "core-workflow-ui-mvp-demo-v5.html"
PREVIOUS_SCRIPT = ROOT / "docs" / "core-workflow-prototype" / "v5.js"


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


def extension_contract() -> dict:
    html = read(HTML)
    block = re.search(
        r'<script type="application/json" id="prototype-extension-contract">(.*?)</script>',
        html,
        re.S,
    )
    assert block, "확장 계약 JSON 블록이 있어야 한다"
    return json.loads(block.group(1))


def test_v6_is_distinct_and_keeps_v5_for_comparison() -> None:
    for path in (HTML, SCRIPT, STYLE, PREVIOUS_HTML, PREVIOUS_SCRIPT):
        assert path.exists(), f"{path.name} 이(가) 있어야 한다"
    html = read(HTML)
    assert 'href="core-workflow-prototype/v6.css' in html
    assert 'src="core-workflow-prototype/v6.js' in html
    assert "v5.js" not in html and "v5.css" not in html
    assert "시안 v6" in html


def test_work_mode_is_derived_only_from_template_suffix() -> None:
    script = read(SCRIPT)
    assert 'HWPX:"hwpx_generate"' in script
    assert 'TEXT_REVIEW_COPY:"text_review_copy"' in script
    assert 'UNSUPPORTED:"unsupported"' in script
    body = re.search(r"function workModeFor\(work\) \{(.*?)\n  \}", script, re.S)
    assert body, "workModeFor 단일 파생 함수가 있어야 한다"
    assert '.endsWith(".hwpx")' in body.group(1)
    assert '.endsWith(".txt")' in body.group(1)
    assert "return WORK_MODE.UNSUPPORTED" in body.group(1)
    # v5의 "txt가 아니면 모두 hwpx" fallback은 남지 않는다.
    assert 'endsWith(".txt") ? "txt" : "hwpx"' not in script
    assert "지원 작업 방식 확인 필요" in script


def test_unsupported_work_mode_is_fail_closed() -> None:
    script = read(SCRIPT)
    assert "unsupportedMode:{severity:3" in script
    assert "blocking:true" in script
    candidates = re.search(r"function compatibleWorks\(\) \{(.*?)\n\t  \}", script, re.S)
    assert candidates and "libraryHealthFor(work).blocking" in candidates.group(1)
    can_use = re.search(r"function canUseWork\(workId\) \{(.*?)\n\t  \}", script, re.S)
    assert can_use and "libraryHealthFor(works[workId]).blocking" in can_use.group(1)
    assert "if(workModeOf(state.activeWorkId)!==WORK_MODE.HWPX)" in script


def test_single_source_decision_functions_exist_and_stay_separate() -> None:
    script = read(SCRIPT)
    for name in (
        "function workModeFor(",
        "function workModeLabel(",
        "function markWorkUsed(",
        "function rankAvailableWorks(",
        "function mainTopWorks(",
        "function modeSections(",
        "function libraryHealthFor(",
        "function libraryVisibleWorks(",
        "function libraryProjection(",
        "function compatibilityFor(",
    ):
        assert name in script, f"{name} 판정 함수가 있어야 한다"
    health = re.search(r"function libraryHealthFor\(work\) \{(.*?)\n\t  \}", script, re.S)
    assert health and "compatibilityFor" not in health.group(1)
    compatibility = re.search(
        r"function compatibilityFor\(workId,currentFields=currentColumns\(\)\) \{(.*?)\n\t  \}",
        script,
        re.S,
    )
    assert compatibility and "libraryHealthFor" not in compatibility.group(1)


def test_main_ranks_all_candidates_before_capping_and_sections_by_mode() -> None:
    script = read(SCRIPT)
    rank = re.search(r"function rankAvailableWorks\((.*?)\n\t  \}", script, re.S)
    assert rank
    body = rank.group(1)
    assert "favoritedAt" in body and "lastUsedAt" in body and "workNameCompare" in body
    assert "last_run_at" not in body, "메인 순위는 lastUsedAt을 사용한다"
    assert "function mainTopWorks(list=compatibleWorks(),limit=MAIN_DOCUMENT_LIMIT)" in script
    assert "const MAIN_DOCUMENT_LIMIT = 5;" in script
    chooser = re.search(r"function renderWorkChooser\(\) \{(.*?)\n\t  \}", script, re.S)
    assert chooser
    chooser_body = chooser.group(1)
    assert "mainTopWorks(eligible)" in chooser_body
    assert "modeSections(visible)" in chooser_body
    assert 'sections.length>1?`<h3>' in chooser_body, "한 방식이면 헤더를 생략한다"
    assert "즐겨찾기" not in chooser_body and "다른 문서" not in chooser_body


def test_current_data_browser_keeps_tabs_and_adds_mode_sections() -> None:
    html = read(HTML)
    script = read(SCRIPT)
    assert 'data-document-tab="available"' in html
    assert 'data-document-tab="needsAction"' in html
    browser = re.search(r"function renderDocumentBrowser\(\) \{(.*?)\n\t  \}", script, re.S)
    assert browser
    body = browser.group(1)
    assert "modeSections(visible,entryMode)" in body
    assert "document-mode-heading" in body
    assert "state.libraryBrowser" not in body, "현재 데이터 탐색은 그룹·태그 facet을 쓰지 않는다"


def test_usage_events_are_result_shaped_not_entry_shaped() -> None:
    script = read(SCRIPT)
    assert 'const WORK_USAGE_KEY="narmi.prototype.work-usage.v1";' in script
    run = re.search(r"async function runCurrent\(\) \{(.*?)\n  \}", script, re.S)
    assert run
    assert (
        'if(["completed","partiallyCompleted"].includes(result.status)&&result.succeeded>0)'
        "markWorkUsed(state.activeWorkId);" in run.group(1)
    )
    setup = re.search(r"function setupWorkbench\(\) \{(.*?)\n  \}", script, re.S)
    assert setup and "markWorkUsed" not in setup.group(1), "작업대 진입은 최근 사용이 아니다"
    copy_handler = re.search(
        r'\$\("copyRecord"\)\.addEventListener\("click",\(\)=>\{(.*?)\n  \}\);', script, re.S
    )
    assert copy_handler and "markWorkUsed(workbenchWorkId())" in copy_handler.group(1)


def test_workbench_is_bound_to_the_session_work_not_a_single_txt_job() -> None:
    script = read(SCRIPT)
    render = re.search(r"function renderWorkbench\(\) \{(.*?)\n  \}", script, re.S)
    assert render
    body = render.group(1)
    assert "fieldDefs[workId]" in body and "state.bindings[workId]" in body
    assert "fieldDefs.order" not in body and "state.bindings.order" not in body
    assert "textTemplates[workId]" in body
    html = read(HTML)
    assert "복사는 시안 mock 완료 사건입니다" in html


def test_library_browser_state_axes_and_projection_rules() -> None:
    script = read(SCRIPT)
    assert "libraryBrowser:{" in script
    for key in (
        'view:"all"',
        'modeFilter:"all"',
        'query:""',
        "tagFilters:{}",
        "collapsedGroups:new Set()",
        "selectedWorkId:null",
        "scrollY:0",
        "focusTarget:null",
    ):
        assert key in script, f"libraryBrowser.{key} 축이 있어야 한다"
    assert "librarySearch:" not in script, "v5의 단일 검색 상태는 남지 않는다"
    projection = re.search(r"function libraryProjection\((.*?)\n  \}", script, re.S)
    assert projection
    body = projection.group(1)
    assert 'browser.view==="recent"' in body and "lastUsedAt" in body
    assert 'browser.view==="favorites"' in body and "favoritedAt" in body
    assert 'browser.view==="needsAction"' in body and "libraryHealthFor" in body
    assert "NO_GROUP_KEY" in body, "그룹 없음은 마지막 구획이다"
    assert "if(!savedGroups.length)return {kind:\"flat\"" in body


def test_library_search_targets_are_name_group_and_tag_only() -> None:
    script = read(SCRIPT)
    match = re.search(r"function libraryQueryMatch\(work,query\) \{(.*?)\n  \}", script, re.S)
    assert match
    body = match.group(1)
    assert "work.name" in body and "work.group" in body and "work.tags" in body
    assert "templatePath" not in body and "source" not in body


def test_library_tag_facets_combine_or_within_axis_and_and_across_axes() -> None:
    script = read(SCRIPT)
    match = re.search(r"function libraryTagMatch\(work,tagFilters\) \{(.*?)\n  \}", script, re.S)
    assert match
    body = match.group(1)
    assert ".every(" in body and "values.includes(work.tags?.[axis])" in body
    facets = re.search(r"function renderLibraryFacets\(\) \{(.*?)\n  \}", script, re.S)
    assert facets and '$("libraryFacets").hidden=!axes.length' in facets.group(1)


def test_library_navigation_does_not_touch_execution_state() -> None:
    script = read(SCRIPT)
    select = re.search(r"function selectLibraryRow\(workId\) \{(.*?)\n  \}", script, re.S)
    assert select
    body = select.group(1)
    for forbidden in ("activeWorkId", "validation", "preview", "recordRange", "result"):
        assert forbidden not in body, f"행 선택이 {forbidden}을 바꾸면 안 된다"
    group_dialog = re.search(r"function applyGroupDialog\(\) \{(.*?)\n  \}", script, re.S)
    assert group_dialog and "validation" not in group_dialog.group(1)
    tag_dialog = re.search(r"function applyTagDialog\(\) \{(.*?)\n  \}", script, re.S)
    assert tag_dialog and "activeWorkId" not in tag_dialog.group(1)


def test_use_in_document_creation_routes_by_data_and_compatibility() -> None:
    script = read(SCRIPT)
    match = re.search(r"function useWorkInDataScreen\(workId\) \{(.*?)\n  \}", script, re.S)
    assert match
    body = match.group(1)
    assert 'dataState.runtimeData.loadState!=="ready"' in body
    assert "dataState.preferredWorkId=workId" in body
    assert 'compatibilityFor(workId).kind!=="available"' in body
    assert 'state.documentBrowser.tab="needsAction"' in body
    assert "selectDocumentWork(workId,{fromBrowser:true})" in body
    assert "loadCandidate" not in body, "확인 없이 데이터를 자동 교체하지 않는다"


def test_duplicate_copies_definition_but_not_history() -> None:
    script = read(SCRIPT)
    match = re.search(r"function duplicateWork\(workId\) \{(.*?)\n  \}", script, re.S)
    assert match
    body = match.group(1)
    assert 'favoritedAt:""' in body and 'lastUsedAt:""' in body and 'last_run_at:""' in body
    assert "fieldDefs[newId]" in body and "state.bindings[newId]" in body


def test_library_return_context_restores_every_browser_axis() -> None:
    script = read(SCRIPT)
    ret = re.search(r"function libraryReturn\(workId,focusTarget=null\) \{(.*?)\n  \}", script, re.S)
    assert ret
    for key in (
        "libraryView",
        "libraryModeFilter",
        "libraryQuery",
        "libraryTagFilters",
        "libraryCollapsedGroups",
        "librarySelectedWorkId",
        "libraryVisibleIds",
        "scrollY",
        "focusTarget",
    ):
        assert key in ret.group(1), f"ReturnContext에 {key}가 있어야 한다"
    restore = re.search(
        r"function restoreLibrarySurface\(ret,\{cancelled=false\}=\{\}\) \{(.*?)\n  \}", script, re.S
    )
    assert restore
    body = restore.group(1)
    assert "showLibraryNotice" in body, "해결된 항목이 사라지면 조용하지 않게 알린다"
    assert "libraryVisibleIds" in body and "neighbor" in body


def test_template_transition_is_a_separate_atomic_draft() -> None:
    script = read(SCRIPT)
    assert "templateTransition:null" in script
    start = re.search(r"function startTemplateTransition\(\) \{(.*?)\n  \}", script, re.S)
    assert start
    body = start.group(1)
    for key in (
        "sourceWorkId",
        "originReturnContext",
        "candidateTemplateId",
        "candidateTemplatePath",
        "fromMode",
        "toMode",
        "choice:null",
        'stage:"pick"',
        "candidateFields",
        "candidateBindings",
        "fieldDiff",
        "dirty:false",
    ):
        assert key in body, f"templateTransitionDraft에 {key}가 있어야 한다"
    assert "state.editSession?.patch" in body, "일반 patch와 섞지 않는다"
    assert 'const TRANSITION_STAGES = ["pick","impact","mapping","review"];' in script


def test_different_mode_candidate_explains_impact_and_offers_three_choices() -> None:
    script = read(SCRIPT)
    impact = re.search(r"function renderTransitionImpact\(draft,work\) \{(.*?)\n  \}", script, re.S)
    assert impact
    body = impact.group(1)
    assert "이 템플릿을 사용하면 작업 방식이 바뀝니다" in body
    assert "변경되는 것" in body and "유지되는 것" in body and "다시 확인할 것" in body
    assert 'data-transition-choice="fork"' in body
    assert 'data-transition-choice="convert_current"' in body
    assert "data-transition-cancel" in body
    choose = re.search(r"function chooseTransitionCandidate\(templateId\) \{(.*?)\n  \}", script, re.S)
    assert choose
    assert "WORK_MODE.UNSUPPORTED" in choose.group(1), "지원하지 않는 확장자는 후보로 받지 않는다"
    assert "returnToEditorWithTemplateCandidate" in choose.group(1)


def test_transition_commit_is_atomic_and_keeps_dormant_filename_rule() -> None:
    script = read(SCRIPT)
    commit = re.search(r"async function commitTemplateTransition\(\) \{(.*?)\n  \}", script, re.S)
    assert commit
    body = commit.group(1)
    assert "dormantFilenamePattern" in body, "TXT 전환에서 파일 이름 규칙을 삭제하지 않는다"
    assert "if(isActive)invalidateRunEvidence();" in body
    assert "if(isActive)requestValidation();" in body
    assert "workbenchState.session=null" in body
    assert "catch(error)" in body and "기존 작업과 초안은 그대로 보존" in body
    cancel = re.search(r"function cancelTemplateTransition\(\) \{(.*?)\n  \}", script, re.S)
    assert cancel
    cancel_body = cancel.group(1)
    assert "openWorkEditor(context)" in cancel_body
    for forbidden in ("templatePath=", "fieldDefs[", "bindingRevision"):
        assert forbidden not in cancel_body, "취소는 draft만 버린다"


def test_extension_contract_declares_the_v6_decisions() -> None:
    contract = extension_contract()
    assert contract["version"] == "v6-work-mode-library"
    mode = contract["workMode"]
    assert mode["source"] == "template_path suffix"
    assert mode["values"]["unsupported"]["policy"] == "fail-closed"
    assert mode["primaryGrouping"]["data"] == "work mode"
    assert mode["primaryGrouping"]["library"] == "user group"
    usage = contract["workUsage"]
    assert usage["field"] == "lastUsedAt"
    assert usage["prototypeKey"] == "narmi.prototype.work-usage.v1"
    assert usage["productOwner"] is None, "제품 저장 소유자는 아직 없다고 밝힌다"
    assert "workbench entry" in usage["notCounted"]
    browser = contract["libraryBrowser"]
    assert browser["views"] == ["all", "recent", "favorites", "needsAction"]
    assert browser["queryTargets"] == ["work name", "user group name", "tag value"]
    health = contract["libraryHealth"]
    assert health["separateFrom"] == "compatibilityFor"
    assert set(health["blocking"]) == {"damaged", "templateMissing", "unsupportedMode"}
    transition = contract["templateTransition"]
    assert transition["stages"] == ["pick", "impact", "mapping", "review"]
    assert transition["choices"] == ["fork", "convert_current"]
    assert transition["cancel"] == "templateTransitionDraft만 폐기"
    assert "새 home 화면" in contract["outOfScope"]
    assert "실제 clipboard 검증" in contract["outOfScope"]


def test_extension_contract_invariants_cover_the_new_boundaries() -> None:
    invariants = " ".join(extension_contract()["invariants"])
    for phrase in (
        "template_path 확장자",
        "activeWorkId",
        "다른 작업 방식 템플릿",
        "templateTransitionDraft만 폐기",
        "비활성 보관",
    ):
        assert phrase in invariants, f"불변식에 {phrase} 문장이 있어야 한다"


def test_static_markup_accessibility_contract() -> None:
    parser = ContractParser()
    parser.feed(read(HTML))
    assert not parser.nested, f"중첩 인터랙티브 요소 금지: {parser.nested}"
    missing = sorted(set(parser.references) - set(parser.ids))
    assert not missing, f"참조된 id가 없음: {missing}"
    html = read(HTML)
    assert 'role="tablist" aria-labelledby="libraryViewLabel"' in html
    assert 'role="group" aria-labelledby="libraryModeLabel"' in html
    assert html.count('data-library-view="') == 4
    assert html.count('data-library-mode="') == 3
    script = read(SCRIPT)
    assert 'aria-expanded="${!collapsed}"' in script, "그룹 접힘은 aria-expanded로 알린다"
    assert 'aria-pressed="${on}"' in script, "태그 facet은 aria-pressed로 알린다"
    assert "ArrowLeft" in script and "libraryViewTabs" in script


def test_mode_signal_is_not_color_only() -> None:
    script = read(SCRIPT)
    tag = re.search(r"function modeTag\(workOrId,\{short=true\}=\{\}\) \{(.*?)\n  \}", script, re.S)
    assert tag
    body = tag.group(1)
    assert "entry.icon" in body and "entry.short" in body
    style = read(STYLE)
    assert ".mode-tag[data-mode=hwpx_generate]" in style
    assert ".mode-tag[data-mode=text_review_copy]" in style


def test_library_panes_split_the_viewport_and_pin_primary_actions() -> None:
    style = read(STYLE)
    assert "@media(min-width:921px) and (min-height:760px)" in style
    fixed = style.split("@media(min-width:921px) and (min-height:760px)")[1].split("}\n.")[0]
    assert "#screen-library.on{display:flex" in fixed and "height:calc(100vh - 64px)" in fixed
    assert ".library-browser{flex:1;min-height:0" in fixed
    assert ".library-list-pane{min-height:0;overflow:auto}" in fixed
    assert ".library-detail-body{flex:1;min-height:0;overflow:auto}" in fixed
    script = read(SCRIPT)
    detail = re.search(r"function renderLibraryDetail\(\) \{(.*?)\n  \}", script, re.S)
    assert detail
    body = detail.group(1)
    assert "library-detail-body" in body and "library-detail-footer" in body
    footer = body.split("library-detail-footer")[1]
    assert 'data-library-action="edit"' in footer and 'data-library-action="use"' in footer
    assert 'data-library-action="duplicate"' not in footer, "관리 행동은 고정 영역에 두지 않는다"


def test_library_detail_shows_saved_bindings_without_inventing_values() -> None:
    script = read(SCRIPT)
    block = re.search(r"function libraryBindingBlock\(work\) \{(.*?)\n  \}", script, re.S)
    assert block
    body = block.group(1)
    assert "fieldDefs[work.id]" in body and "state.bindings[work.id]" in body
    assert 'dataState.runtimeData.loadState==="ready"' in body
    assert "저장된 항목 키를 그대로 표시합니다" in body
    assert "연결 안 함" in body and "의도적 미사용" in body
    assert "읽을 수 있는 필드 정의가 없습니다" in body


def test_responsive_rules_exist_for_new_surfaces() -> None:
    style = read(STYLE)
    assert "@media(max-width:920px)" in style and "@media(max-width:580px)" in style
    narrow = style.split("@media(max-width:920px)")[-1]
    assert ".library-browser{grid-template-columns:1fr}" in narrow
    assert ".transition-map-row{grid-template-columns:1fr}" in narrow


def test_core_workflow_doc_records_the_v6_contract() -> None:
    doc = read(CONTRACT_DOC)
    assert "## 19." in doc, "v6 장이 있어야 한다"
    for phrase in (
        "hwpx_generate",
        "text_review_copy",
        "지원 작업 방식 확인 필요",
        "lastUsedAt",
        "libraryHealthFor",
        "templateTransitionDraft",
        "사용자 그룹",
    ):
        assert phrase in doc, f"정본 문서에 {phrase} 계약이 있어야 한다"
    assert "```mermaid" in doc
