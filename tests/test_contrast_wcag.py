"""WCAG 2.1 대비 계약 가드 — 표준 관행 라운드 ST-04/05(QApplication 불필요·순수 stdlib).

`design_tokens.json` 단일 출처의 색으로 명도 대비비를 계산해 AA 임계를 강제한다.
수리 전(MUTED=#7a7f87·border_control=#adb3bb)엔 실패하고, 수리 후(#656a72·#767b83)엔
통과한다 — 토큰이 다시 옅어지면 이 가드가 시끄럽게 잡는다(조용한 드리프트 방지).

- SC 1.4.3 Contrast (Minimum): 소형 텍스트 4.5:1 — MUTED 는 카드·창·pill[muted] 배경 위.
- SC 1.4.11 Non-text Contrast: UI 컴포넌트 경계 3:1 — 체크박스 인디케이터 테두리.
"""
from __future__ import annotations

import gen_design_tokens as gen


def _lin(c8: int) -> float:
    c = c8 / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hex_str: str) -> float:
    r, g, b = (int(hex_str[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_muted_text_meets_aa_4_5_on_all_backgrounds():
    """MUTED 소형 텍스트가 카드·창·pill[muted] 배경 위에서 4.5:1 이상(SC 1.4.3)."""
    t = gen.load_tokens()
    muted = t["color"]["muted"]
    for bg_path, bg in (
        ("color.card_bg", t["color"]["card_bg"]),
        ("color.window_bg", t["color"]["window_bg"]),
        ("neutral.track", t["neutral"]["track"]),  # pill[muted] 배경
    ):
        ratio = contrast(muted, bg)
        assert ratio >= 4.5, f"MUTED({muted}) on {bg_path}({bg}) = {ratio:.2f}:1 < 4.5:1"


def test_indicator_border_meets_non_text_3_1():
    """체크박스 인디케이터 테두리가 흰 배경 대비 3:1 이상(SC 1.4.11)."""
    t = gen.load_tokens()
    border = t["neutral"]["border_control"]
    ratio = contrast(border, t["color"]["card_bg"])
    assert ratio >= 3.0, f"indicator border({border}) on card = {ratio:.2f}:1 < 3:1"
