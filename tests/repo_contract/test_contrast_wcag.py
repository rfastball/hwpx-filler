"""색 토큰의 사용자 안전 하한만 검증한다."""

from __future__ import annotations

import re
from pathlib import Path

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
        # TXT 이름표(FB-03 #1079): 필드 밑줄·항목/선택 테두리와 범위 막대는 카드 위 그래픽 표지다 — 3:1.
        *(
            (f"{theme} semantic {name}/card", palette["semantic"][name], palette["color"]["card_bg"], 3.0)
            for theme, palette in (("light", light), ("dark", dark))
            for name in ("field", "slot", "option")
        ),
        # 여는 표기 칩의 이름은 칩 바탕 위 작은 글자다 — 4.5:1.
        *(
            (f"{theme} semantic {name} ink", palette["semantic"][f"{name}_ink"], palette["semantic"][name], 4.5)
            for theme, palette in (("light", light), ("dark", dark))
            for name in ("slot", "option")
        ),
    ]

    failures = [
        f"{label}: {_contrast(foreground, background):.2f}:1 < {floor}:1"
        for label, foreground, background, floor in checks
        if _contrast(foreground, background) < floor
    ]
    assert not failures, "\n".join(failures)


def _mix(color: str, percent: float, base: str) -> str:
    """CSS ``color-mix(in srgb, color percent%, base)`` — sRGB 채널을 그대로 섞는다."""
    channels = (
        round(int(color[index : index + 2], 16) * percent / 100 + int(base[index : index + 2], 16) * (1 - percent / 100))
        for index in (1, 3, 5)
    )
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def _declaration(css: str, selector: str, prop: str) -> str:
    """``selector{...}`` 규칙 하나의 속성 값(첫 규칙)."""
    found = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    assert found, selector
    values = dict(part.split(":", 1) for part in found[1].split(";") if ":" in part)
    return values[prop].strip()


def test_proposal_marks_derived_colors_meet_contrast_floors() -> None:
    """「데이터로 필드 찾기」(#1156)의 color-mix 파생 쌍 — 이름표·표시형 알약 글자는 제안 면 위 작은 글자(4.5:1), 보류 밑줄은
    카드 위 그래픽 표지(3:1)다. 글자 색은 authoring.css 의 선언을 읽어 푼다 — 초록(--proposal-ink)을 글자에 쓰면 밝은 테마에서
    3.86:1 로 떨어진다(감사 P1-4)."""
    css = (Path(__file__).resolve().parents[2] / "frontend" / "css" / "authoring.css").read_text(encoding="utf-8")
    shell = re.search(r"\.authoring-shell\{(--proposal-ink:[^}]*)\}", css)
    assert shell, "제안 색 토큰"
    face_percent = float(re.search(r"--proposal-face:color-mix\(in srgb,var\(--a-sem-field\) (\d+)%,var\(--a-card\)\)", shell[1])[1])
    held_percent = float(re.search(r"--proposal-held:color-mix\(in srgb,var\(--a-muted\) (\d+)%,var\(--a-card\)\)", shell[1])[1])
    tokens = gen.load_tokens()
    checks = []
    for theme, palette in (("light", tokens), ("dark", tokens["dark"])):
        card = palette["color"]["card_bg"]
        face = _mix(palette["semantic"]["field"], face_percent, card)
        ink = {"var(--a-ink)": palette["color"]["ink"], "var(--proposal-ink)": palette["semantic"]["field"],
               "var(--n-ink-soft)": palette["neutral"]["ink_soft"]}
        for name, selector in (("tag", ".authoring-document .cm-authoring-proposal-tag"), ("format pill", ".authoring-proposal-fmt")):
            checks.append((f"{theme} proposal {name} text/face", ink[_declaration(css, selector, "color")], face, 4.5))
        held_tag = ".authoring-document .cm-authoring-proposal-tag.cm-authoring-proposal-held"
        checks.append((f"{theme} held tag text/card", ink[_declaration(css, held_tag, "color")], card, 4.5))
        checks.append((f"{theme} proposal underline/card", palette["semantic"]["field"], card, 3.0))
        checks.append((f"{theme} held underline/card", _mix(palette["color"]["muted"], held_percent, card), card, 3.0))
    failures = [
        f"{label}: {_contrast(foreground, background):.2f}:1 < {floor}:1"
        for label, foreground, background, floor in checks
        if _contrast(foreground, background) < floor
    ]
    assert not failures, "\n".join(failures)
