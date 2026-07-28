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
        ".fico", ".fchip button", ".wstep-tab.as-tab", ".shell-tool",
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
    # 발신은 존 공용 통로(`call`)를 지난다(재작성 F3: 변이 직렬화) — 낙관 표지가 **먼저**다.
    assert body.index("applyRowSelection(tr, selAnchorState)") < body.index(
        'call("toggle_record"'
    )
    apply = src[src.index("function applyRowSelection("):src.index("function toggleRow(")]
    for needle in ('classList.toggle("on"', 'setAttribute("aria-selected"', "box.checked = value"):
        assert needle in apply


def test_filter_panel_renders_loading_shell_before_query() -> None:
    src = _read("js/datazone.js")
    body = src[src.index("async function openColPanel("):src.index("function panelHead(")]
    assert body.index("renderColPanelShell(col)") < body.index(
        'await call("filter_panel"'
    )
    assert "panelEpoch" in body and "renderColPanelError" in body


def test_group_collapse_uses_one_optimistic_helper_on_all_three_surfaces() -> None:
    helper = _read("js/grouplist.js")
    assert "function toggleGroup(button, persist, errorMessage)" in helper
    assert helper.index("setGroupExpanded(button, !wasExpanded)") < helper.index("request = persist()")
    assert "Promise.resolve(request).catch" in helper and "window.alert" in helper
    # 소비 표면 — 「문서 만들기」 좌 목록(F2 PR-B)·「기안」 좌 목록(F6 PR-B)·「템플릿
    # 관리」(F8 §10.17)가 차례로 죽어 즉답 토글의 소비 표면은 라이브러리 하나다. 편집기
    # 「템플릿」 탭의 접힘은 설계상 백엔드 왕복(toggle_library_group — 공유 그룹 모델
    # 영속)이라 이 기제의 소비자가 아니다.
    for rel in ("js/screens/library.js",):
        src = _read(rel)
        assert "GroupList.toggleGroup(" in src, f"{rel}이 공용 즉답 토글을 쓰지 않습니다."
        assert 'sec.collapsed ? " hidden" : ""' in src, (
            f"{rel}이 접힌 본문을 DOM에 보존하지 않아 로컬 펼침이 불가능합니다."
        )


def test_job_opening_marker_precedes_search_flush_and_backend_load() -> None:
    """「여는 중」 표지는 검색 정산·백엔드 왕복보다 **먼저** 선다(#217 R1).

    좌 목록 사망(F2 PR-B)으로 이 계약의 거처가 후보 카드·문서 탐색 행으로 옮겼다 —
    몸통은 하나(selectJobWithMarker)이고 두 표면이 그것을 쓴다(지도 §10.9 판정 E).
    """
    src = _read("js/screens/job.js")
    body = src[src.index("async function selectJobWithMarker("):src.index("function onMasterClick(")
               if "function onMasterClick(" in src else len(src)]
    assert body.index("setJobOpening(btn, true)") < body.index("await dz.flushPendingSearch()")
    assert "여는 중…" in src and 'setAttribute("aria-busy", "true")' in src
    assert "작업 열기 실패:" in src
    # 두 소비처가 같은 몸통을 쓴다 — 한쪽만 표지를 잃는 드리프트 금지.
    assert src.count("selectJobWithMarker(") >= 3  # 정의 1 + 후보 카드 + 탐색 행
