"""색 토큰의 사용자 안전 하한만 검증한다."""

from __future__ import annotations

import gen_design_tokens as gen


def _linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def _contrast(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
        return 0.2126 * _linear(red) + 0.7152 * _linear(green) + 0.0722 * _linear(blue)

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_text_and_control_colors_meet_wcag_contrast_floors() -> None:
    """작은 텍스트는 4.5:1, 조작 경계는 3:1 이상이어야 한다."""
    tokens = gen.load_tokens()
    light = tokens
    dark = tokens["dark"]
    checks = [
        *(
            (f"light muted/{name}", light["color"]["muted"], background, 4.5)
            for name, background in (
                ("card", light["color"]["card_bg"]),
                ("window", light["color"]["window_bg"]),
                ("track", light["neutral"]["track"]),
            )
        ),
        ("light control border", light["neutral"]["border_control"], light["color"]["card_bg"], 3.0),
        # 입력(.field) 테두리가 이 토큰이다(UX-08 #1027) — 카드뿐 아니라 창 바탕 위에도 선다.
        ("light control border/window", light["neutral"]["border_control"], light["color"]["window_bg"], 3.0),
        ("light control border/surface alt", light["neutral"]["border_control"], light["neutral"]["surface_alt"], 3.0),
        *(
            (f"dark muted/{name}", dark["color"]["muted"], background, 4.5)
            for name, background in (
                ("card", dark["color"]["card_bg"]),
                ("window", dark["color"]["window_bg"]),
                ("track", dark["neutral"]["track"]),
            )
        ),
        ("dark control border", dark["neutral"]["border_control"], dark["color"]["card_bg"], 3.0),
        # 입력(.field) 테두리가 이 토큰이다(UX-08 #1027) — 카드뿐 아니라 창 바탕 위에도 선다.
        ("dark control border/window", dark["neutral"]["border_control"], dark["color"]["window_bg"], 3.0),
        ("dark control border/surface alt", dark["neutral"]["border_control"], dark["neutral"]["surface_alt"], 3.0),
        *(
            (f"dark {name}/card", foreground, dark["color"]["card_bg"], 4.5)
            for name, foreground in (
                ("primary", dark["color"]["primary"]),
                ("warn", dark["color"]["warn"]),
                ("danger", dark["color"]["danger"]),
                ("ok", dark["color"]["ok"]),
                ("empty", dark["state"]["data_empty_fg"]),
            )
        ),
        ("dark ok/fill badge", dark["color"]["ok"], dark["badge"]["fill_bg"], 4.5),
        ("dark warn/blank badge", dark["color"]["warn"], dark["badge"]["blank_bg"], 4.5),
        ("dark danger/missing badge", dark["color"]["danger"], dark["badge"]["missing_bg"], 4.5),
        ("dark ack badge", dark["badge"]["ack_fg"], dark["badge"]["ack_bg"], 4.5),
        ("dark accent ink/primary", dark["color"]["on_accent"], dark["color"]["primary"], 4.5),
        ("dark accent ink/ok", dark["color"]["on_accent"], dark["color"]["ok"], 4.5),
        # 저작 상태 막대의 입구(.authoring-status-link, IDE-01)는 조작 잉크 글자다 — 창 바탕·카드 위 모두 작은 글자 하한.
        *(
            (f"{theme} control ink/{name}", palette["neutral"]["ink_control"], palette["color"][background], 4.5)
            for theme, palette in (("light", light), ("dark", dark))
            for name, background in (("window", "window_bg"), ("card", "card_bg"))
        ),
        # 같은 문구 목록(IDE-07 .authoring-same-text mark)은 선택 바탕 위의 본문 잉크 글자다 — 작은 글자 하한.
        *(
            (f"{theme} ink/select", palette["color"]["ink"], palette["state"]["select_bg"], 4.5)
            for theme, palette in (("light", light), ("dark", dark))
        ),
        # TXT 편집면의 문제 밑줄(IDE-05 .cm-authoring-problem-error/-warning)은 글자가 아닌 그래픽 표지다 — 3:1.
        # 편집면 바탕은 카드다. 강제 색상에서는 CanvasText 로 바뀐다(authoring.css forced-colors 블록).
        *(
            (f"{theme} problem underline {name}/card", palette["color"][name], palette["color"]["card_bg"], 3.0)
            for theme, palette in (("light", light), ("dark", dark))
            for name in ("danger", "warn")
        ),
    ]

    failures = [
        f"{label}: {_contrast(foreground, background):.2f}:1 < {floor}:1"
        for label, foreground, background, floor in checks
        if _contrast(foreground, background) < floor
    ]
    assert not failures, "\n".join(failures)
