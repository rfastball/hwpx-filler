"""마일스톤 I #217 — 즉답 표지와 로컬 보기 토글의 정적 계약."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


def test_press_feedback_covers_round_trip_surfaces_and_reduced_motion() -> None:
    css = _read("css/app.css")
    selectors = (
        ".job-item", ".job-grp-head", ".jobtb tbody tr", ".mir-row.miss",
        ".fico", ".fchip button", ".wstep-tab.as-tab", ".rail-toggle", ".rail-theme",
    )
    active = css[css.index(".btn:active:not(:disabled)"):css.index("/* 부유 메뉴")]
    reduced = css[css.index("@media (prefers-reduced-motion:reduce)"):css.index("/* ---- 공통 컨트롤")]
    for selector in selectors:
        assert f"{selector}:active" in active, f"{selector} 눌림 표지가 없습니다(#217 R5)."
        assert selector in reduced, f"{selector} reduced-motion 강등이 없습니다(#217 R5)."


def test_data_rows_flip_locally_before_dispatch_and_use_live_dom_state() -> None:
    src = _read("js/datazone.js")
    body = src[src.index("function toggleRow("):src.index("function onTableClick(")]
    assert 'tr.getAttribute("aria-selected")' in body
    assert body.index("applyRowSelection(tr, selAnchorState)") < body.index(
        'Bridge.call(SCREEN, "toggle_record"'
    )
    apply = src[src.index("function applyRowSelection("):src.index("function toggleRow(")]
    for needle in ('classList.toggle("on"', 'setAttribute("aria-selected"', "box.checked = value"):
        assert needle in apply


def test_filter_panel_renders_loading_shell_before_query() -> None:
    src = _read("js/datazone.js")
    body = src[src.index("async function openColPanel("):src.index("function panelHead(")]
    assert body.index("renderColPanelShell(col)") < body.index(
        'await Bridge.call(SCREEN, "filter_panel"'
    )
    assert "panelEpoch" in body and "renderColPanelError" in body


def test_group_collapse_uses_one_optimistic_helper_on_all_three_surfaces() -> None:
    helper = _read("js/grouplist.js")
    assert "function toggleGroup(button, persist, errorMessage)" in helper
    assert helper.index("setGroupExpanded(button, !wasExpanded)") < helper.index("request = persist()")
    assert "Promise.resolve(request).catch" in helper and "window.alert" in helper
    for rel in ("js/screens/job.js", "js/screens/draft.js", "js/screens/template.js"):
        src = _read(rel)
        assert "GroupList.toggleGroup(" in src, f"{rel}이 공용 즉답 토글을 쓰지 않습니다."
        assert 'sec.collapsed ? " hidden" : ""' in src, (
            f"{rel}이 접힌 본문을 DOM에 보존하지 않아 로컬 펼침이 불가능합니다."
        )


def test_job_opening_marker_precedes_search_flush_and_backend_load() -> None:
    src = _read("js/screens/job.js")
    body = src[src.index("async function selectJobFromItem("):src.index("function onMasterClick(")]
    assert body.index("setJobOpening(item, true)") < body.index("await dz.flushPendingSearch()")
    assert "여는 중…" in src and 'setAttribute("aria-busy", "true")' in src
    assert "작업 열기 실패:" in src
