"""튜토리얼 패널의 **실렌더 겹침** 게이트 — #918-B.

## 왜 정적 계약으로 안 되는가

`tests/js/tutorial_panel.test.js` 는 패널 루트가 `data-screen` 을 싣는다는 **사실**을 잰다.
그 검사가 초록인 채로 그 표식을 소비하는 CSS·JS 는 0곳이었고, 패널은 화면이 무엇이든 뷰포트
우하단 같은 자리에 섰다. 제품의 확정 동사들이 전부 같은 구석에 앵커돼 있으므로(몰입 표면의
`.wfoot`, 「문서 만들기」의 `.session-actionbar`) 그 자리는 **비어 있지 않다** — T15·T17 이
「저장을 누르세요」라고 안내하는 그 저장 버튼을 안내 패널이 덮었다. 회피 훅의 존재는 회피의
결과를 말해 주지 않는다(U2 §2.11 과 같은 결함류).

## 무엇을 재는가

sealed `build/web/` CSS 를 loopback 으로 제공한 **뷰포트 골격**(`.app` = 100vh 그리드)에 실
클래스를 실제 구조대로 세우고, 대표 폭 세 곳에서 `getBoundingClientRect` 교집합을 잰다.
`_press_probe` 의 폭 고정 문서(`#probe-host`)로는 이걸 물을 수 없다 — 뷰포트에 붙는 표면
(fixed 패널·sticky 액션바·토스트)의 자리가 질문이기 때문이다.

## 양성·음성 대조

음성 대조(:func:`test_probe_sees_the_overlap_when_the_avoidance_is_removed`)는 패널을 수리 전
앵커(`bottom:16px`)로 되돌려 **교집합 > 0 을 실측**한다. 그 단언이 없으면 위 검사들의 초록이
「패널이 비켰다」가 아니라 「이 프로브는 겹침을 못 본다」일 수 있다.

## 「덮였는가」는 z 값 비교가 아니다

`.undo-toast` 는 `--z-modal`(200)을, `.tut-root` 는 `--z-popover`(100)을 든다. 숫자만 보면
토스트가 이긴다. 실제로는 토스트가 `#reactOverlayHost`(z:90 — 쌓임 맥락)에 갇혀 있어 패널이
**위에** 그려진다. 그래서 판정은 `elementFromPoint` 적중이고, 계약은 「둘이 겹치지 않는다」다
— 토스트는 확정 취소 동선이라 가려서도 안 되고, 패널의 안내도 잃으면 안 된다.
"""

from __future__ import annotations

import os
from functools import lru_cache

import pytest

_MOTION_GATE = bool(os.environ.get("HWPX_SKIP_MOTION_TESTS"))
_GATE_REASON = (
    "튜토리얼 겹침 기하 게이트 — Playwright + 설치 Chrome 필요"
    "(HWPX_SKIP_MOTION_TESTS=1 로 명시 옵트아웃)"
)

#: 대표 폭. 1272 는 토스트(max 560)와 좌우 패널 여백이 정확히 맞닿는 폭
#: (2×(16+340)+560)이라 그 아래에서 토스트가 패널 자리로 들어온다 — 경계를 사이에 두고
#: 아래(1000)·위(1600)를 함께 잰다.
WIDTHS: tuple[int, ...] = (1000, 1272, 1600)
VIEWPORT_HEIGHT = 800

#: 패널이 비켜야 하는 확정 띠 — 화면별 소유자와 그 안의 주 확정 버튼.
CONFIRM_BANDS: dict[str, tuple[str, str]] = {
    "editor": (".wfoot", ".wfoot .btn.primary"),
    # 몰입 표면 둘은 같은 부류지만 **띠 클래스가 다르다**(`.wfoot` ↔ `.wb-foot`) — 회피를
    # 「몰입이면 같은 값」으로 뭉뚱그리면 그 차이가 검사되지 않는다.
    "workbench": (".wb-foot", ".wb-foot .btn.primary"),
    "job": (".session-actionbar", ".session-actionbar .btn.primary"),
}

#: 재는 화면 전수. `library` 는 **바닥 확정 띠가 없는** 화면이라 세로 회피를 받지 않는다 —
#: 그래서 이 화면에서 초록인 토스트 단언은 세로 여백이 우연히 벌어 준 것이 아니라 가로 띠
#: 규칙이 실제로 서 있다는 증거다(세 화면의 `--tut-clear` 가 같았다면 그 규칙은 검사되지 않는다).
SCREENS: tuple[str, ...] = ("editor", "workbench", "job", "library")

_PANEL_BODY = (
    '<div id="tutorialBody" class="tut-body">'
    '<p id="tutorialNextStep" class="tut-next">데이터를 고르고 「이 작업으로 문서 생성」을 누르세요.</p>'
    '<section class="tut-tier" data-tier="basic" data-complete="0">'
    '<h4 class="tut-tier-head"><span class="tut-tier-label">기본</span>'
    '<span class="tut-tier-title">첫 문서</span><span class="tut-tier-count">2/4</span></h4>'
    '<p class="tut-tier-invite">예제로 한 건을 끝까지 만들어 볼 수 있습니다.</p>'
    '<ul class="tut-steps">'
    '<li class="tut-step is-done" data-milestone="T0"><span class="tut-step-mark">✓</span>'
    '<span class="tut-step-body"><span class="tut-step-title">예제 설치</span>'
    '<span class="tut-step-note">예제가 홈에 들어왔습니다.</span></span></li>'
    '<li class="tut-step is-done" data-milestone="T1"><span class="tut-step-mark">✓</span>'
    '<span class="tut-step-body"><span class="tut-step-title">템플릿 고르기</span></span></li>'
    '<li class="tut-step" data-milestone="T2"><span class="tut-step-mark">○</span>'
    '<span class="tut-step-body"><span class="tut-step-title">데이터 연결</span></span></li>'
    '<li class="tut-step" data-milestone="T3"><span class="tut-step-mark">○</span>'
    '<span class="tut-step-body"><span class="tut-step-title">문서 생성</span></span></li>'
    "</ul></section>"
    '<section class="tut-tier" data-tier="deep" data-complete="0">'
    '<h4 class="tut-tier-head"><span class="tut-tier-label">심화</span>'
    '<span class="tut-tier-title">되풀이</span><span class="tut-tier-count">0/3</span></h4>'
    '<ul class="tut-steps">'
    '<li class="tut-step" data-milestone="T10"><span class="tut-step-mark">○</span>'
    '<span class="tut-step-body"><span class="tut-step-title">작업 저장</span></span></li>'
    '<li class="tut-step" data-milestone="T15"><span class="tut-step-mark">○</span>'
    '<span class="tut-step-body"><span class="tut-step-title">누름틀 고치기</span></span></li>'
    '<li class="tut-step" data-milestone="T17"><span class="tut-step-mark">○</span>'
    '<span class="tut-step-body"><span class="tut-step-title">관리 문서 저장</span></span></li>'
    "</ul></section></div>"
)


def _shell_overlays(screen: str, root_style: str = "", toast_style: str = "") -> str:
    """`#reactRoot` 안의 셸 표면 둘 — overlay host(토스트)와 튜토리얼 패널(그 뒤 형제).

    DOM 순서·중첩은 `frontend/src/react/boundary.ts` 의 `createAppElement` 그대로다.
    두 `*_style` 은 음성 대조 전용이다 — 인라인 선언이 회피 규칙을 이기므로 같은 골격에서
    **수리 전 기하를 그대로 되살린다**.
    """
    style = f' style="{root_style}"' if root_style else ""
    toast = f' style="{toast_style}"' if toast_style else ""
    return (
        '<div id="reactRoot">'
        '<div id="reactOverlayHost">'
        f'<div id="undoToast" class="undo-toast" role="status" aria-live="polite"{toast}>'
        '<span id="undoToastText">「2026 상반기 계약서」 12건 생성을 되돌릴 수 있습니다.</span>'
        '<button class="btn sm" id="undoToastBtn">되돌리기</button></div></div>'
        f'<div id="tutorialPanelRoot" class="tut-root" data-screen="{screen}"{style}>'
        '<aside id="tutorialPanel" class="tut-panel" aria-labelledby="tutorialPanelTitle"'
        ' data-collapsed="0">'
        '<header class="tut-head"><h3 id="tutorialPanelTitle" class="tut-title">튜토리얼</h3>'
        '<span id="tutorialProgress" class="tut-progress">2/7</span>'
        '<button type="button" id="tutorialCollapse" class="btn sm tut-collapse">접기</button>'
        '<button type="button" id="tutorialDismiss" class="btn sm tut-dismiss">튜토리얼 닫기</button>'
        "</header>"
        f"{_PANEL_BODY}</aside></div></div>"
    )


_TOPBAR = (
    '<header class="topbar"><div class="brand"><span class="brand-lockup">'
    '<span class="brand-name">문서나르미</span></span></div>'
    '<nav class="nav"><button class="navbtn">문서 만들기</button>'
    '<button class="navbtn">문서 작업</button></nav><div></div></header>'
)

_EDITOR_STAGE = (
    '<section class="scr on" id="scr-editor"><div class="editor-shell">'
    '<button class="btn back">◀ 돌아가기</button>'
    '<div class="wbody"><div style="height:1200px">누름틀 목록</div></div>'
    '<footer class="wfoot" id="editor-foot">'
    '<button class="btn" data-act="discard-patch">변경 버리기</button>'
    '<span class="spacer"></span>'
    '<button class="btn primary" data-act="save">변경 저장</button></footer>'
    "</div></section>"
)

_WORKBENCH_STAGE = (
    '<section class="scr on" id="scr-workbench"><div class="wb-shell">'
    '<button class="btn back">◀ 돌아가기</button>'
    '<div class="wb-body"><div class="wb-left"><div id="wbMapPanel" '
    'style="height:1200px">필드 연결</div></div>'
    '<div class="wb-right"><div class="wb-preview">채운 모습</div></div></div>'
    '<footer class="wb-foot">'
    '<label class="wb-adv"><input type="checkbox" id="wbAdvance"> 복사 후 다음 항목으로 이동</label>'
    '<span class="muted" id="wbNote">12건 중 3번째</span>'
    '<div class="wb-foot-nav"><button class="btn" id="wbPrev">이전</button>'
    '<button class="btn" id="wbNext">다음</button>'
    '<button class="btn primary" id="wbCopy">복사</button></div></footer>'
    "</div></section>"
)

_JOB_STAGE = (
    '<section class="scr on" id="scr-job"><div class="job-layout">'
    '<aside class="job-master">작업 목록</aside>'
    '<section class="job-panel"><div class="job-zones"><div class="zone">'
    '<h3 class="zone-cap">현재 데이터</h3><div style="height:1200px"></div>'
    "</div></div>"
    '<div class="session-actionbar"><div class="actionbar-row">'
    '<span class="actionbar-identity">'
    '<span class="actionbar-job" id="jobActionName">2026 상반기 계약</span></span>'
    '<button class="btn primary" id="jobGenBtn">이 작업으로 문서 생성</button>'
    '<span class="muted capnote" id="jobGate">선택 3건</span>'
    "</div></div></section></div></section>"
)

_LIBRARY_STAGE = (
    '<section class="scr on" id="scr-library"><div class="library-toolbar">'
    '<div class="library-search-field"><input class="field" placeholder="검색"></div>'
    '<div class="library-tabs"><button aria-selected="true">전체</button>'
    "<button>최근</button></div></div>"
    '<div style="height:1200px">작업 목록</div></section>'
)

_STAGES: dict[str, tuple[str, str]] = {
    # 화면 → (stage 내용, body 클래스). 몰입 표면은 `body.editor-open` 이 셸 표지를 걷는다.
    "editor": (_EDITOR_STAGE, "editor-open"),
    "workbench": (_WORKBENCH_STAGE, "workbench-open"),
    "job": (_JOB_STAGE, ""),
    "library": (_LIBRARY_STAGE, ""),
}


def _scaffold(screen: str, root_style: str = "", toast_style: str = "") -> tuple[str, str]:
    stage, body_class = _STAGES[screen]
    markup = (
        f'<div class="app">{_TOPBAR}<main class="stage">{stage}</main></div>'
        f"{_shell_overlays(screen, root_style, toast_style)}"
    )
    return markup, body_class


_SELECTORS: tuple[str, ...] = (".tut-panel", ".undo-toast", *sum(
    (list(pair) for pair in CONFIRM_BANDS.values()), [],
))


@lru_cache(maxsize=None)
def _measure(screen: str, width: int, root_style: str = "", toast_style: str = "") -> dict:
    """(화면, 폭) 한 조합당 브라우저 한 번 — 여러 단언이 같은 측정을 나눠 쓴다."""
    from _press_probe import measure_viewport_rects  # 지역 import — 옵트아웃 러너에 불요

    markup, body_class = _scaffold(screen, root_style, toast_style)
    return measure_viewport_rects(
        markup, width=width, height=VIEWPORT_HEIGHT,
        selectors=_SELECTORS, body_class=body_class,
    )


def overlap_area(a: dict, b: dict) -> float:
    """두 상자의 교집합 넓이(px²). 안 겹치면 0."""
    dx = min(a["right"], b["right"]) - max(a["left"], b["left"])
    dy = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
    return round(dx * dy, 2) if dx > 0 and dy > 0 else 0.0


def _rect(measured: dict, selector: str) -> dict:
    rect = measured["rects"][selector]
    assert rect is not None, f"{selector} 가 골격에 렌더되지 않았습니다 — 프로브 미달입니다."
    assert rect["width"] > 0 and rect["height"] > 0, f"{selector} 가 폭·높이 0 입니다: {rect}"
    return rect


# ------------------------------------------------------- 실렌더 기하(양성 = 비켰다)

@pytest.mark.browser
@pytest.mark.skipif(_MOTION_GATE, reason=_GATE_REASON)
@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("screen", sorted(CONFIRM_BANDS))
def test_tutorial_panel_clears_the_confirm_band(screen: str, width: int) -> None:
    """ⓐ 패널이 확정 띠(와 그 안의 주 확정 버튼)와 **교집합 0** 이다."""
    measured = _measure(screen, width)
    band_selector, primary_selector = CONFIRM_BANDS[screen]
    panel = _rect(measured, ".tut-panel")
    band = _rect(measured, band_selector)
    primary = _rect(measured, primary_selector)

    assert overlap_area(panel, primary) == 0, (
        f"{screen}@{width}px: 튜토리얼 패널이 주 확정 버튼({primary_selector})을 "
        f"{overlap_area(panel, primary):.0f}px² 덮습니다 — 안내가 가리키는 그 버튼입니다(#918-B). "
        f"패널={panel} 버튼={primary}"
    )
    assert overlap_area(panel, band) == 0, (
        f"{screen}@{width}px: 튜토리얼 패널이 확정 띠({band_selector})를 "
        f"{overlap_area(panel, band):.0f}px² 덮습니다 — 띠 전체가 확정 동선입니다. "
        f"패널={panel} 띠={band}"
    )
    assert primary["covered"] is False, (
        f"{screen}@{width}px: 주 확정 버튼의 중심이 {primary['covered_by']!r} 에 덮였습니다."
    )


@pytest.mark.browser
@pytest.mark.skipif(_MOTION_GATE, reason=_GATE_REASON)
@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("screen", SCREENS)
def test_tutorial_panel_and_undo_toast_keep_each_other_whole(screen: str, width: int) -> None:
    """ⓑ 토스트와 패널이 서로를 잃지 않는다 — 겹치지 않고, 둘 다 적중 가능하다."""
    measured = _measure(screen, width)
    panel = _rect(measured, ".tut-panel")
    toast = _rect(measured, ".undo-toast")

    assert overlap_area(panel, toast) == 0, (
        f"{screen}@{width}px: 되돌리기 토스트와 튜토리얼 패널이 "
        f"{overlap_area(panel, toast):.0f}px² 겹칩니다. 쌓임 맥락상 패널이 위라 가려지는 쪽은 "
        f"**확정 취소 동선**입니다. 패널={panel} 토스트={toast}"
    )
    assert toast["covered"] is False, (
        f"{screen}@{width}px: 토스트 중심이 {toast['covered_by']!r} 에 덮였습니다."
    )
    assert panel["covered"] is False, (
        f"{screen}@{width}px: 패널 중심이 {panel['covered_by']!r} 에 덮였습니다."
    )


@pytest.mark.browser
@pytest.mark.skipif(_MOTION_GATE, reason=_GATE_REASON)
@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("screen", SCREENS)
def test_tutorial_panel_stays_whole_inside_the_viewport(screen: str, width: int) -> None:
    """ⓒ 회피가 패널을 화면 밖으로 밀지 않는다 — 네 변이 전부 뷰포트 안이다."""
    measured = _measure(screen, width)
    panel = _rect(measured, ".tut-panel")
    viewport = measured["viewport"]
    assert panel["top"] >= 0 and panel["left"] >= 0, (
        f"{screen}@{width}px: 회피가 패널을 뷰포트 밖으로 밀었습니다: {panel}"
    )
    assert panel["right"] <= viewport["width"] + 0.5, (
        f"{screen}@{width}px: 패널 우변이 뷰포트를 넘습니다: {panel} / {viewport}"
    )
    assert panel["bottom"] <= viewport["height"] + 0.5, (
        f"{screen}@{width}px: 패널 하변이 뷰포트를 넘습니다: {panel} / {viewport}"
    )


@pytest.mark.browser
@pytest.mark.skipif(_MOTION_GATE, reason=_GATE_REASON)
def test_data_screen_hook_actually_moves_the_panel() -> None:
    """회피 배선이 **있으나 마나**가 되지 않는다 — 화면 표식이 실제로 기하를 가른다.

    세 화면의 바닥 여백이 같아지면 `data-screen` 소비는 이름만 남고, 그때 토스트 단언의
    초록은 가로 띠 규칙이 아니라 우연히 벌어진 세로 여백이 낸 것이 된다.
    """
    bottoms = {
        screen: _rect(_measure(screen, 1600), ".tut-panel")["bottom"] for screen in SCREENS
    }
    assert bottoms["library"] > bottoms["editor"] > bottoms["job"], (
        "화면별 확정 띠 회피가 기하로 나타나지 않습니다(띠가 큰 화면일수록 더 들려야 합니다): "
        f"{bottoms}"
    )
    assert bottoms["workbench"] < bottoms["library"], (
        f"몰입 표면 workbench 가 회피를 받지 못했습니다: {bottoms}"
    )


# ------------------------------------------------- 음성 대조(프로브가 겹침을 실제로 본다)

@pytest.mark.browser
@pytest.mark.skipif(_MOTION_GATE, reason=_GATE_REASON)
def test_probe_sees_the_overlap_when_the_avoidance_is_removed() -> None:
    """수리 전 앵커(`bottom:16px`)로 되돌리면 교집합이 **실측된다**.

    이 대조가 없으면 위 초록이 「비켰다」가 아니라 「이 프로브는 눈이 없다」일 수 있다.
    인라인 style 이 회피 규칙을 이기므로 같은 골격에서 수리 전 기하가 그대로 재현된다.
    """
    before = _measure(
        "editor", 1000,
        root_style="bottom:16px",
        toast_style="left:50%;max-width:min(560px,calc(100vw - 32px))",
    )
    panel = _rect(before, ".tut-panel")
    band = _rect(before, ".wfoot")
    primary = _rect(before, ".wfoot .btn.primary")
    toast = _rect(before, ".undo-toast")

    assert overlap_area(panel, primary) > 0, (
        "수리 전 앵커에서도 주 확정 버튼과의 교집합이 0 입니다 — 프로브가 겹침을 못 봅니다."
    )
    assert overlap_area(panel, band) > 0
    assert overlap_area(panel, toast) > 0, (
        "수리 전 앵커에서 토스트와의 교집합이 0 입니다 — 1000px 는 경계(1272px) 아래입니다."
    )
    assert primary["covered"] is True and primary["covered_by"], (
        "수리 전 앵커에서 주 확정 버튼이 덮이지 않았습니다 — 적중 판정이 눈이 없습니다."
    )
