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


# ---- 다크 팔레트 대비 — 손으로 산출한 다크값의 기계 비준(미학 아닌 하한) ----
# 라이트와 같은 계약을 다크 표면에 강제한다. 이 가드가 있어 다크 hex 를 조정할 때 대비가
# 조용히 깨지지 않는다(다시 옅어지면 시끄럽게 실패). AA 소형 텍스트 4.5, 비텍스트 3.


def test_dark_muted_and_indicator_meet_aa():
    """다크에서도 MUTED 텍스트 4.5:1(카드·창·트랙) · 인디케이터 보더 3:1(카드)."""
    d = gen.load_tokens()["dark"]
    for bg_path, bg in (
        ("color.card_bg", d["color"]["card_bg"]),
        ("color.window_bg", d["color"]["window_bg"]),
        ("neutral.track", d["neutral"]["track"]),
    ):
        ratio = contrast(d["color"]["muted"], bg)
        assert ratio >= 4.5, f"dark MUTED on {bg_path}({bg}) = {ratio:.2f}:1 < 4.5:1"
    b = contrast(d["neutral"]["border_control"], d["color"]["card_bg"])
    assert b >= 3.0, f"dark indicator border on card = {b:.2f}:1 < 3:1"


def test_disabled_primary_text_meets_aa_on_neutral_track_in_both_themes():
    """H-11: disabled primary의 muted 글자/track 면 조합은 라이트·다크 모두 4.5:1."""
    t = gen.load_tokens()
    for label, palette in (("light", t), ("dark", t["dark"])):
        ratio = contrast(palette["color"]["muted"], palette["neutral"]["track"])
        assert ratio >= 4.5, f"{label} disabled primary = {ratio:.2f}:1 < 4.5:1"


def test_dark_semantic_text_on_card_meets_aa():
    """다크에서 의미 색(primary/warn/danger/ok/empty)이 카드 위 텍스트로 4.5:1 이상.

    라이트에선 이들이 어두워 흰 배경 텍스트였다 — 다크에선 밝혀 어두운 카드 위에서 읽혀야 한다.
    (primary·ok 는 accent 필로도 쓰이나, 그 필 위 글씨는 on_accent 잉크가 담당 → 아래 별도 가드.)
    """
    d = gen.load_tokens()["dark"]
    card = d["color"]["card_bg"]
    for name, hexv in (
        ("primary", d["color"]["primary"]),
        ("warn", d["color"]["warn"]),
        ("danger", d["color"]["danger"]),
        ("ok", d["color"]["ok"]),
        ("data_empty_fg", d["state"]["data_empty_fg"]),
    ):
        ratio = contrast(hexv, card)
        assert ratio >= 4.5, f"dark {name}({hexv}) on card = {ratio:.2f}:1 < 4.5:1"


def test_dark_badge_foreground_on_tint_meets_aa():
    """다크 배지 전경(상태색·ack 잉크)이 같은 배지의 어두운 틴트 배경 위에서 4.5:1 이상."""
    d = gen.load_tokens()["dark"]
    for fg, bg, label in (
        (d["color"]["ok"], d["badge"]["fill_bg"], "ok/fill"),
        (d["color"]["warn"], d["badge"]["blank_bg"], "warn/blank"),
        (d["color"]["danger"], d["badge"]["missing_bg"], "danger/missing"),
        (d["badge"]["ack_fg"], d["badge"]["ack_bg"], "ack_fg/ack"),
    ):
        ratio = contrast(fg, bg)
        assert ratio >= 4.5, f"dark badge {label} = {ratio:.2f}:1 < 4.5:1"


def test_dark_on_accent_ink_reads_on_accent_fills():
    """다크 on_accent(어두운 잉크)가 밝은 accent 필(primary/ok) 위에서 4.5:1 이상.

    라이트는 accent 가 어두워 흰 글씨였다 — 다크는 accent 를 밝혀 텍스트로도 읽히게 하므로
    필 위 글씨는 흰색 대신 어두운 잉크여야 대비가 산다(app.css 의 --a-on-accent 로 배선).
    """
    d = gen.load_tokens()["dark"]
    ink = d["color"]["on_accent"]
    for name in ("primary", "ok"):
        ratio = contrast(ink, d["color"][name])
        assert ratio >= 4.5, f"dark on_accent({ink}) on {name}({d['color'][name]}) = {ratio:.2f}:1 < 4.5:1"
