"""눌림 표지의 **실렌더 기하** 게이트 — U2 §2.11.

## 왜 정적 계약으로 안 되는가

`test_interaction_responsiveness.test_press_feedback_covers_round_trip_surfaces_and_reduced_motion`
은 눌림 표지의 **존재**를 강제한다. 그 검사가 초록인 채로 `.jobtb tbody tr:active` 의
`transform:scale(.97)` 이 실사용자 환경에서 표 행을 부수고 있었다 — 990px 행에서 3% 는 좌변이
14.85px 움직인다는 뜻이고, 그러면 행이 sticky 표 머리·이웃 행과 **기준면을 잃는다**. 규칙이
있다는 사실은 그 규칙의 결과를 말해 주지 않는다.

## 계약 — 상자 크기가 관용구를 가른다

32px 버튼에서 3% 는 1px 다(정확한 눌림). 990px 행에서 3% 는 30px 다(레이아웃 파손). 그래서
눌림 표면은 두 갈래이고, 이 파일이 그 갈림을 소유한다:

- :data:`ROW_SURFACES` — **컨테이너를 채우는** 표면. 이웃·머리와 기준면을 공유하므로 중심
  기준 축소를 **쓰지 못한다**. 눌림은 폭을 바꾸지 않는 축(배경)이 말한다.
- :data:`BOX_SURFACES` — 자기 폭만 갖는 작은 조작 상자. `scale(.97)` 이 맞다.

두 목록의 합은 `base.css` 눌림 블록의 선택자 전수와 **정확히 같아야** 한다. 새 선택자를
평면으로 밀어 넣으면 여기서 멈춘다 — 결정 없이 늘어나는 것을 막는 것이 이 단언의 존재 이유다.

## `prefers-reduced-motion` 강제가 계약이다

이 층은 `@media (prefers-reduced-motion:reduce)` 에서 통째로 꺼진다(`base.css:129-141`).
개발 기기가 Windows 「애니메이션 표시」를 꺼 두면 Chromium 이 `reduce` 를 보고하고 모션 층은
**한 번도 돌지 않는다** — 그 상태에서 프로브를 붙이면 영영 초록이다(U2 §2.11 후속 규칙). 그래서
기하는 `no-preference` 를 **명시로 강제**해서 재고, 같은 프로브를 `reduce` 로도 돌려 **Δ 0**
음성 대조를 먼저 세운다. 두 값이 다르지 않으면 프로브가 아무것도 못 재고 있다는 뜻이다.

실앱(WebView2)은 OS 설정을 따르고 테스트는 사용자 OS 설정을 변이하지 않으므로, 강제의 매체는
Playwright + 설치 Chrome 의 ``reduced_motion`` 컨텍스트다. 데스크톱 Chrome 이 없는 러너는
``HWPX_SKIP_MOTION_TESTS=1`` 로 **명시** 옵트아웃한다 — 자동 감지 스킵은 만들지 않는다.
"""

from __future__ import annotations

import os
import re

import pytest

from _web_css import WEB_CSS_DIR, app_css, strip_comments

WEB = WEB_CSS_DIR.parent
INDEX = WEB / "index.html"

_MOTION_GATE = bool(os.environ.get("HWPX_SKIP_MOTION_TESTS"))
_GATE_REASON = (
    "눌림 기하 게이트 — Playwright + 설치 Chrome 필요"
    "(HWPX_SKIP_MOTION_TESTS=1 로 명시 옵트아웃)"
)

#: 컨테이너를 채우는 눌림 표면. 값은 U2 §2.11 전수조사가 실 레이아웃(1440×900)에서 잰
#: 실폭이다 — 파손 크기가 폭에 비례하므로 근거로 남긴다. 이 표면들은 `scale` 을 쓰지 않는다.
ROW_SURFACES: dict[str, int] = {
    ".job-grp-head": 1170,     # 라이브러리 그룹 머리 — 전수조사 최악(Δ좌변 +17.56px)
    # (.mir-row.miss — 거울 빈 값 행 — 은 필드축 ack 폐기(U2 §2.13)로 산출자가 0곳이 되어
    #  내려갔다. 죽은 선택자를 계약이 부양하면 다음 사람이 그 표면이 산다고 읽는다.)
    ".jobtb tbody tr": 910,    # 데이터 표 행 — U2 §2.11 원 제보
    ".ctx-menu button": 140,   # 메뉴 항목은 메뉴 폭을 채운다(채움비 0.93)
}

#: 자기 폭만 갖는 작은 조작 상자 — `scale(.97)` 유지. 공유 기준면이 없어 드리프트가 무해하다.
BOX_SURFACES: tuple[str, ...] = (
    ".btn", ".navbtn", ".job-more", ".grp-more", ".tpl-assign", "button.pill",
    ".fico", ".fchip button", ".wstep-tab.as-tab", ".shell-tool",
)

#: `.job-item` 은 산출자가 0곳이다(F2 PR-B 로 좌 master 목록 사망). `.mir-row.miss` 는
#: 필드축 ack 폐기(U2 §2.13)로 클릭형 거울 행이 죽어 같은 자격이 됐다. `base.css` 밖에서
#: 이 이름들을 내는 곳이 웹 자산 전체에 없으므로 눌림 목록에 있을 수 없다.
DEAD_SELECTORS: tuple[str, ...] = (".job-item", ".mir-row.miss")

# 선택자별 최소 골격 — `<tr>` 은 표 조상이 있어야 행이 되고, 메뉴 항목은 `.ctx-menu` 안에
# 있어야 한다. 실 산출자의 구조만 남기고 내용은 지운 형태다(값이 아니라 상자를 재는 검사다).
SCAFFOLDS: dict[str, str] = {
    ".jobtb tbody tr": (
        '<div class="tbwrap jobtbwrap"><table class="tb jobtb"><tbody>'
        '<tr id="probe"><td class="doccol">문서</td><td class="col-text">값</td></tr>'
        '<tr><td class="doccol">문서</td><td class="col-text">값</td></tr>'
        "</tbody></table></div>"
    ),
    ".job-grp-head": (
        '<div class="job-grp"><button class="job-grp-head" id="probe" aria-expanded="true">'
        '<span class="tw">▾</span>조달<span class="cnt">3</span></button></div>'
    ),
    ".ctx-menu button": (
        '<div class="ctx-menu" style="display:block;position:static">'
        '<button id="probe">이름 변경…</button><button>삭제…</button></div>'
    ),
}

_PRESS_BLOCK_START = ".btn:active:not(:disabled)"
_PRESS_BLOCK_END = "/* 부유 메뉴"


def _press_block() -> str:
    """`base.css` 의 눌림 선언 구간(원문 순서 컷 — `_web_css` 독스트링의 계약)."""
    css = app_css()
    # 컷은 주석 텍스트로 하고 **자른 뒤에** 산문을 걷는다 — 주석은 죽은 선택자 이름을
    # 일부러 남기므로(아래 DEAD_SELECTORS 근거) 그것을 규칙으로 세면 거짓 실패가 난다.
    return strip_comments(css[css.index(_PRESS_BLOCK_START):css.index(_PRESS_BLOCK_END)])


def _scale_selectors() -> set[str]:
    """눌림 구간에서 `transform:scale(...)` 을 받는 선택자 전수(`:active` 를 벗긴 형태)."""
    block = _press_block()
    found: set[str] = set()
    for chunk in re.findall(r"([^{}]+)\{[^{}]*transform:\s*scale\([^)]*\)[^{}]*\}", block):
        for sel in chunk.split(","):
            sel = sel.strip()
            if not sel:
                continue
            sel = sel.replace(":active:not(:disabled)", "").replace(":active", "").strip()
            found.add(sel)
    return found


# --------------------------------------------------------------- 정적 계약(갈림)

def test_press_scale_selectors_are_exactly_the_declared_box_surfaces() -> None:
    """`scale` 눌림은 **작은 조작 상자에만** 선다 — 목록이 평면으로 자라지 못한다."""
    scaled = _scale_selectors()
    rows_in_scale = sorted(scaled & set(ROW_SURFACES))
    assert not rows_in_scale, (
        "컨테이너를 채우는 표면에 중심 기준 scale 이 걸려 있습니다(U2 §2.11): "
        f"{rows_in_scale}. 폭이 변하면 이웃·표 머리와 기준면을 잃습니다 — 눌림은 폭을 "
        "바꾸지 않는 축(배경)이 말해야 합니다."
    )
    assert scaled == set(BOX_SURFACES), (
        "눌림 scale 목록이 선언과 다릅니다. 새 표면은 ROW_SURFACES(전폭 행) 또는 "
        f"BOX_SURFACES(작은 상자) 중 **하나로 결정**해서 등재하세요. "
        f"CSS 에만 있는 것={sorted(scaled - set(BOX_SURFACES))} · "
        f"선언에만 있는 것={sorted(set(BOX_SURFACES) - scaled)}"
    )


def test_dead_selectors_carry_no_press_marker() -> None:
    """산출자가 없는 선택자는 눌림 계약을 늘리지 않는다 — 죽은 규칙은 다음 사람을 속인다."""
    block = _press_block()
    assets = [p.read_text(encoding="utf-8") for p in (WEB / "js").rglob("*.js")]
    assets.append(INDEX.read_text(encoding="utf-8"))
    for selector in DEAD_SELECTORS:
        name = selector.lstrip(".")
        producers = [t for t in assets if name in t]
        assert not producers, (
            f"{selector} 의 산출자가 되살아났습니다 — DEAD_SELECTORS 에서 내리고 "
            "ROW_SURFACES/BOX_SURFACES 중 하나로 판정하세요."
        )
        assert selector not in block, (
            f"{selector} 는 웹 자산 어디에서도 만들어지지 않는데 눌림 표지를 들고 있습니다."
        )


def test_row_surfaces_are_all_covered_by_the_sweep_widths() -> None:
    """전수조사가 잰 실폭을 근거로 남긴다 — 파손 크기는 폭에 비례하므로 수치가 판정의 일부다."""
    for selector, width in ROW_SURFACES.items():
        assert width >= 100, f"{selector} 의 실폭 근거가 비었습니다."
        assert selector in SCAFFOLDS, f"{selector} 의 렌더 골격이 없어 기하를 잴 수 없습니다."


# ------------------------------------------------------- 실렌더 기하(양성·음성 대조)

@pytest.mark.skipif(_MOTION_GATE, reason=_GATE_REASON)
@pytest.mark.parametrize("selector", list(ROW_SURFACES))
def test_row_surface_left_edge_does_not_move_while_held(selector: str) -> None:
    """눌림을 **유지한 채** 전폭 행의 좌변이 움직이지 않는다(`no-preference` 강제).

    음성 대조를 같은 프로브로 함께 세운다 — `reduce` 에서도 Δ 0 이면 그건 "안 움직인다"의
    증거가 아니라 "이 프로브는 모션이 꺼진 세계를 보고 있다"의 증거다.
    """
    from _press_probe import measure_press  # 지역 import — 옵트아웃 러너에 playwright 불요

    width = ROW_SURFACES[selector]
    live = measure_press(SCAFFOLDS[selector], width, motion="no-preference")
    control = measure_press(SCAFFOLDS[selector], width, motion="reduce")

    assert control["d_left"] == pytest.approx(0, abs=0.05), (
        f"{selector}: reduced-motion 대조가 Δ좌변 {control['d_left']:+.2f}px 를 냈습니다 — "
        "모션 층 밖에서 기하가 변하고 있다는 뜻이라 이 프로브의 판정이 무효입니다."
    )
    assert live["active"], (
        f"{selector}: 눌림이 요소에 걸리지 않았습니다(:active 미적용) — 측정값이 아니라 "
        "프로브 미달입니다. 골격이 요소를 덮고 있는지 확인하세요."
    )
    assert abs(live["d_left"]) <= 1.0, (
        f"{selector}: 눌림 중 좌변이 {live['d_left']:+.2f}px 움직였습니다(폭 {width}px). "
        f"Δ폭 {live['d_width']:+.2f}px. 이웃 행·표 머리와 기준면을 잃습니다 — U2 §2.11."
    )


@pytest.mark.skipif(_MOTION_GATE, reason=_GATE_REASON)
def test_press_marker_actually_fires_on_a_box_surface() -> None:
    """양성 대조 — 작은 상자에서는 눌림이 **실제로 그려진다**.

    이 단언이 없으면 위 검사의 초록이 "행이 안전하다"가 아니라 "이 환경에서 모션이 꺼져
    있다"일 수 있다. 프로브의 판별력을 프로브가 스스로 증명한다.
    """
    from _press_probe import measure_press

    scaffold = '<button class="btn" id="probe" style="width:200px">미리보기</button>'
    live = measure_press(scaffold, 400, motion="no-preference")
    control = measure_press(scaffold, 400, motion="reduce")
    assert live["transform"] != "none", (
        "작은 상자에서도 눌림이 안 그려졌습니다 — reduced_motion 강제가 먹지 않고 있습니다."
    )
    assert control["transform"] == "none", (
        "reduced-motion 에서 눌림이 남아 있습니다 — 강등 규칙(base.css:129-141)이 깨졌습니다."
    )
    assert abs(live["d_left"]) > 0.5, "눌림이 기하에 나타나지 않아 프로브가 눈이 없습니다."
