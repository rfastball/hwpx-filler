"""마일스톤 I #217 — 즉답 표지와 로컬 보기 토글의 정적 계약."""
from __future__ import annotations

from _web_source import SOURCE_ROOT, app_css, strip_comments


WEB = SOURCE_ROOT


def _read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


def test_press_feedback_covers_round_trip_surfaces_and_reduced_motion() -> None:
    """왕복 표면 전부에 눌림 표지가 서고 reduced-motion 강등이 붙는다(#217 R5).

    **이 검사가 종전에 결함을 고정시켰다(U2 §2.11).** 8선택자에 `:active` 표지가 있으라고만
    요구했고, 그 초록 아래에서 `.jobtb tbody tr:active{transform:scale(.97)}` 이 910px 행의
    좌변을 13.65px 옮기고 있었다 — 규칙의 **존재**는 그 규칙의 **결과**를 말해 주지 않는다.
    그래서 여기서는 「표지가 있다 + 강등이 있다」까지만 보고, **어느 축의 표지인가**와 그
    기하 결과는 `tests/test_web_press_geometry.py` 가 진다. 한 파일에 합치지 않는 이유는
    이쪽이 정적이고 저쪽이 브라우저를 요구하기 때문이다.

    `.job-item` 은 목록에서 내려갔다 — 산출자가 웹 자산 전체에 0곳이다(F2 PR-B 로 좌 master
    목록 사망). 죽은 선택자를 계약이 부양하면 다음 사람이 그 표면이 산다고 읽는다.
    `.mir-row.miss`(클릭형 거울 행)도 같은 이유로 내려갔다 — 필드축 ack 폐기(U2 §2.13)로
    산출자가 0곳이다.
    """
    # 이 검사는 **원문 순서와 주석 텍스트**로 자른다(`/* 부유 메뉴`·`/* ---- 공통 컨트롤`).
    # 순서 보존 컷이라 그 구간(모션층)은 통째로 base.css 안에 그대로 있다.
    css = app_css()
    # 눌림 표지는 두 축 중 하나로 선다 — scale(작은 상자) 또는 background(컨테이너를 채움).
    scale_surfaces = (
        ".fico", ".fchip button", ".wstep-tab.as-tab", ".shell-tool",
        ".btn", ".navbtn", ".job-more", ".grp-more", ".tpl-assign", "button.pill",
    )
    fill_surfaces = (".job-grp-head", ".jobtb tbody tr", ".ctx-menu button")
    # 컷은 주석 텍스트로 하고(순서 보존 컷의 계약) **자른 뒤에** 산문을 걷는다 — 주석이
    # 일부러 남긴 죽은 선택자 이름을 규칙으로 세지 않기 위해서다(`_web_source.strip_comments`).
    active = strip_comments(css[css.index(".btn:active:not(:disabled)"):css.index("/* 부유 메뉴")])
    reduced = strip_comments(
        css[css.index("@media (prefers-reduced-motion:reduce)"):css.index("/* ---- 공통 컨트롤")]
    )
    rules = strip_comments(css)
    for selector in scale_surfaces:
        assert f"{selector}:active" in active, f"{selector} 눌림 표지가 없습니다(#217 R5)."
        assert selector in reduced, f"{selector} reduced-motion 강등이 없습니다(#217 R5)."
    for selector in fill_surfaces:
        # 전폭 표면은 눌림 **색**을 소유자 파일에서 내므로 모션 구간엔 전이 대상으로만 나온다.
        # 전이가 없으면 색이 즉시 튀고, 강등이 없으면 모션 설정을 무시한다.
        assert f"{selector}:active" in rules, f"{selector} 눌림 색이 어디에도 없습니다(U2 §2.11)."
        assert selector in active, f"{selector} 눌림 전이 대상이 빠졌습니다(U2 §2.11)."
        assert selector in reduced, f"{selector} reduced-motion 강등이 없습니다(#217 R5)."
    assert ".job-item" not in active, "산출자 0곳인 .job-item 이 눌림 계약에 되살아났습니다."
    assert ".mir-row.miss" not in active, (
        "산출자 0곳인 .mir-row.miss(구 클릭형 거울 행 — U2 §2.13 사망)가 눌림 계약에 되살아났습니다."
    )


def test_data_rows_flip_locally_before_dispatch_and_use_live_dom_state() -> None:
    src = _read("src/screens/data_zone.ts")
    body = src[src.index("function toggleRow("):src.index("const selected =")]
    assert "const value = !selectedFor(row);" in body, (
        "미결 낙관 상태를 포함한 현재 행 상태에서 다음 의도를 읽지 않습니다."
    )
    # React producer는 DOM을 직접 뒤집지 않고 낙관 상태와 anchor를 먼저 세운 뒤 직렬화 통로로 보낸다.
    assert body.index("showSelection(row.index, value);") < body.index(
        'sendSelection("toggle_record"'
    )
    assert body.index("anchor.current = { index: row.index, value };") < body.index(
        'sendSelection("toggle_record"'
    )
    producer = src[src.index("...(table.rows || []).map"):src.index("h(RangeFooter")]
    for needle in ('className: selectedFor(row) ? "on" : ""',
                   '"aria-selected": selectedFor(row) ? "true" : "false"',
                   "checked: selectedFor(row)"):
        assert needle in producer


def test_filter_panel_renders_loading_shell_before_query() -> None:
    src = _read("src/screens/data_zone.ts")
    body = src[src.index("async function openPanel("):src.index("function toggleRow(")]
    assert body.index("setPanel({ column, data: null })") < body.index(
        'await controller.zone("filter_panel"'
    )
    assert "current?.column === column" in body and "controller.notify" in body


def test_group_collapse_uses_one_optimistic_helper_on_all_three_surfaces() -> None:
    helper = _read("src/screens/library.ts")
    # 소비 표면 — 「문서 만들기」 좌 목록(F2 PR-B)·「기안」 좌 목록(F6 PR-B)·「템플릿
    # 관리」(F8 §10.17)가 차례로 죽어 즉답 토글의 소비 표면은 라이브러리 하나다. 편집기
    # 「템플릿」 탭의 접힘은 설계상 백엔드 왕복(toggle_library_group — 공유 그룹 모델
    # 영속)이라 이 기제의 소비자가 아니다.
    body = helper[helper.index('className: "lib-grp-head"'):
                  helper.index('className: "lib-grp-rows"')]
    assert body.index('target.setAttribute("aria-expanded"') < body.index(
        'controller.axis("toggle_group"'
    )
    assert 'hidden: !!section.collapsed' in helper, (
        "React 라이브러리가 접힌 본문을 DOM에 보존하지 않습니다."
    )


def test_job_opening_marker_precedes_search_flush_and_backend_load() -> None:
    """「여는 중」 표지는 검색 정산·백엔드 왕복보다 **먼저** 선다(#217 R1).

    좌 목록 사망(F2 PR-B)으로 이 계약의 거처가 후보 카드·문서 탐색 행으로 옮겼다 —
    몸통은 하나(selectJobWithMarker)이고 두 표면이 그것을 쓴다(지도 §10.9 판정 E).
    """
    src = _read("src/screens/job_read.ts")
    body = src[src.index("async function selectJob("):src.index("function currentData(")]
    assert body.index("patchUi({ openingName: name })") < body.index("await flushPendingEdits()")
    assert body.index("await flushPendingEdits()") < body.index('await call("job", "select_job"')
    assert "여는 중…" in src and "openingName === row.name" in src
    assert "작업 열기 실패:" in src
    # 두 소비처가 같은 몸통을 쓴다 — 한쪽만 표지를 잃는 드리프트 금지.
    assert src.count("selectJob(") >= 4  # 정의 1 + 후보 카드 + 탐색 행 + 다시 연결 후 선택
