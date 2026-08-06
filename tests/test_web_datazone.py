"""R4-01 React DataZone 정적 계약.

구 ``frontend/js/datazone.js`` 팩토리는 ``screens/data_zone.ts``의 React producer와
``screens/job_read.ts``의 controller로 분리됐다. 이 파일은 삭제된 구현의 문자열 모양이 아니라
새 producer/controller 경계, Python snapshot 소비, semantic DOM, pending edit 정산을 지킨다.
실 거동 패리티는 R4 Node 테스트와 WebView2 selftest가 맡는다.
"""
from __future__ import annotations

import re

from _web_source import SOURCE_JS_DIR, SOURCE_ROOT, app_css


DATA_ZONE = SOURCE_ROOT / "src" / "screens" / "data_zone.ts"
JOB_READ = SOURCE_ROOT / "src" / "screens" / "job_read.ts"
BOOTSTRAP = SOURCE_ROOT / "src" / "bootstrap.js"
LEGACY_JOB = SOURCE_JS_DIR / "screens" / "job.js"

ZONE_ACTIONS = (
    "filter_panel",
    "filter_col_text",
    "filter_col_values",
    "filter_clear_col",
    "filter_col_range",
    "filter_search",
    "filter_reapply",
    "filter_prune",
    "filter_clear",
    "toggle_record",
    "select_range",
    "set_all",
    "set_none",
)


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|\s)//.*$", r"\1", text)


def test_factory_exists_and_exposes_create():
    """React producer와 controller factory가 서로 다른 모듈에서 명시적으로 노출된다."""
    assert "export function JobDataZone" in _read(DATA_ZONE)
    assert "export function createJobReadController" in _read(JOB_READ)
    assert not (SOURCE_JS_DIR / "datazone.js").exists()


def test_load_order_esc_then_shared_then_screens():
    """ESM 간선과 합성 루트가 DataZone producer를 제품의 단일 React root에 연결한다."""
    job = _read(JOB_READ)
    bootstrap = _read(BOOTSTRAP)
    assert 'import { JobDataZone } from "./data_zone.ts";' in job
    assert 'from "./screens/job_read.ts";' in bootstrap
    assert 'screenPortal("jobDataBodyReactHost", JobDataBody' in bootstrap
    assert 'screenPortal("dataSheetSlot", JobDataBody' in bootstrap


def test_job_consumes_factory_with_job_identity():
    """job read producer가 안정 행 ID와 선두 문서 열을 직접 소유한다."""
    src = _read(DATA_ZONE)
    assert "h(JobDataZone as any" in _read(JOB_READ)
    assert "id: `jobRow-${row.index}`" in src
    assert 'h("th", { className: "doccol" }, "문서"' in src


def test_zone_dispatch_actions_single_sourced_in_factory():
    """데이터 존 액션은 React producer/controller 쌍에만 있고 run remainder에는 없다."""
    owner = _read(DATA_ZONE) + _read(JOB_READ)
    remainder = _strip_js_comments(_read(LEGACY_JOB))
    for action in ZONE_ACTIONS:
        assert f'"{action}"' in owner, f"R4 DataZone 소유자에 {action!r}가 없습니다."
        assert f'"{action}"' not in remainder, f"run remainder에 {action!r}가 재유입됐습니다."


def test_factory_is_screen_agnostic():
    """DOM producer는 bridge/document 조회를 하지 않고 주입된 snapshot/controller만 소비한다."""
    src = _strip_js_comments(_read(DATA_ZONE))
    assert "Bridge" not in src and "pywebview" not in src
    assert "getElementById(" not in src and "document.querySelector(" not in src
    assert "snapshot: Obj" in src and "controller: JobReadController" in src


def test_popover_dismiss_mechanism_single_sourced():
    """React 표면은 legacy 전역 dismiss listener나 suppress 상태를 복제하지 않는다."""
    for path in (DATA_ZONE, JOB_READ):
        src = _strip_js_comments(_read(path))
        assert "Popover.wireDismiss" not in src
        assert "suppressNextClick" not in src
        assert "document.addEventListener(" not in src
    assert "candidateMenu" in _read(JOB_READ), "후보 메뉴 open 상태는 controller UI model이 소유해야 합니다."


def test_factory_snapshot_observed_unconditionally():
    """raw store 하류 model을 useSyncExternalStore로 읽고 full snapshot을 DataZone에 넘긴다."""
    src = _read(JOB_READ)
    assert "useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot)" in src
    assert "return fullSnapshot(model);" in src
    assert "h(JobDataZone as any" in src and "snapshot, controller: props.controller" in src
    assert "if (hasJob)" not in src


def test_moved_surfaces_not_redefined_in_job():
    """legacy job.js에는 R4 read renderer와 DataZone 상태가 다시 생기지 않는다."""
    job = _strip_js_comments(_read(LEGACY_JOB))
    for symbol in (
        "function renderTable(",
        "function renderChips(",
        "function renderStrip(",
        "function openColPanel(",
        "function toggleRow(",
        "function flushPendingSearch(",
        "jobTableBody",
        "jobFilterSearch",
    ):
        assert symbol not in job, f"run remainder에 R4 read 소유자 {symbol!r}가 재유입됐습니다."


def test_table_rows_keep_native_semantics_and_checkbox_in_lead_cell():
    """행 선택 상태와 native checkbox 의미가 React producer에서 함께 유지된다."""
    src = _read(DATA_ZONE)
    css = app_css()
    assert '"aria-selected": selectedFor(row) ? "true" : "false"' in src
    assert "checked: selectedFor(row)" in src
    assert 'h("input", {' in src and "type: \"checkbox\"" in src
    assert 'h("td", { className: "doccol" }' in src
    assert ".jobtb td.doccol{display:flex" not in css
    assert ".jobtb .doccell{display:flex" in css
    assert ".jobtb tbody tr.on{background:var(--a-sel)}" in css


def test_table_consumes_snapshot_column_kind_without_web_inference():
    """금액·날짜 조판은 snapshot column.kind를 소비하고 웹 추론기를 만들지 않는다."""
    src = _read(DATA_ZONE)
    css = app_css()
    assert 'kind: "text"' in src
    assert 'className: `col-${column.kind || "text"}`' in src
    assert ".jobtb .col-amount,.jobtb .col-date" in css
    assert "font-variant-numeric:tabular-nums" in css


def test_unselected_lead_guidance_is_single_sourced_in_headers():
    """비선택 안내는 선두 머리에 한 번 있고 행에는 대시만 있다."""
    src = _strip_js_comments(_read(DATA_ZONE))
    assert src.count("선택하면 파일명이 정해집니다") == 1
    assert 'className: "doc-off", "aria-hidden": "true" }, "—"' in src


def test_filter_roles_have_distinct_labels_and_surface_hierarchy():
    """정의·가지·선택 역할은 텍스트 라벨과 서로 다른 CSS 면을 유지한다."""
    src = _read(DATA_ZONE)
    css = app_css()
    for role in ("필터", "가지", "선택"):
        assert f'className: "chip-role" }}, "{role}"' in src
    assert ".fchip.definition{" in css and "var(--a-primary) 10%" in css
    assert ".fchip.branch{background:var(--n-surface-alt)" in css
    assert ".fstrip{border:1px solid var(--a-border)" in css
    assert ".filter-reapply{" in css


def test_session_change_drops_pending_column_text() -> None:
    """range 취소·controller dispose는 timer와 pending search/column 소재를 함께 버린다."""
    src = _read(JOB_READ)
    drop = src.split("function dropPendingEdits(): void {", 1)[1].split("async function discardRange", 1)[0]
    assert "clearTimeout(searchTimer)" in drop and "clearTimeout(columnTimer)" in drop
    assert "patchUi({ pendingSearch: null, pendingColumn: null })" in drop
    discard = src.split("async function discardRange(): Promise<void> {", 1)[1][:500]
    assert "dropPendingEdits();" in discard
