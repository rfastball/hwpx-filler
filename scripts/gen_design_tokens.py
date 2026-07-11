#!/usr/bin/env python3
"""디자인 토큰 단일 출처 → Qt ``style.py`` + 목업 CSS 재생성/검증.

색·상태색은 ``src/hwpxfiller/gui/design_tokens.json`` 한 곳에만 손으로 둔다. 이 스크립트가
그 값을 ``gui/style.py`` 의 ``<gen:tokens>`` 영역(팔레트 상수)과 목업 HTML
(``docs/UI_PROTOTYPE_APPB.html``)의 ``<gen:tokens>`` 영역(앱윈도 ``--a-*`` CSS 변수)에 찍는다.
디자인 색 변경 = JSON 1곳 편집 + regen. 백엔드(core/data)·QSS 구조는 손대지 않는다.

    python scripts/gen_design_tokens.py           # 두 영역 재작성
    python scripts/gen_design_tokens.py --check    # 드리프트 검사(CI/pytest; 어긋나면 non-zero)

생성물은 **커밋되는 소스**다(패키징된 exe 는 쓰기 가능한 프로젝트 폴더가 없어 런타임 생성 불가).
이 스크립트는 dev/CI 전용이며 앱 실행 시 돌지 않는다. stdlib 만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "src" / "hwpxfiller" / "gui" / "design_tokens.json"
STYLE = ROOT / "src" / "hwpxfiller" / "gui" / "style.py"
MOCKUP = ROOT / "docs" / "UI_PROTOTYPE_APPB.html"

# style.py 팔레트 상수 이름 ← 토큰 경로("그룹.키").
# badge.* 는 style 전용(집행 화면 인라인 필드 배지) — 목업은 .fb 클래스 CSS 로 같은 값을
# 직접 렌더하므로 _MOCKUP_MAP 엔 넣지 않는다(값은 목업 .fb 톤과 일치).
_STYLE_MAP = [
    ("PRIMARY", "color.primary"), ("PRIMARY_HOVER", "color.primary_hover"),
    ("WARN", "color.warn"), ("DANGER", "color.danger"), ("OK", "color.ok"),
    ("MUTED", "color.muted"), ("BORDER", "color.border"), ("CARD_BG", "color.card_bg"),
    ("WINDOW_BG", "color.window_bg"), ("INK", "color.ink"),
    ("UNCONFIRMED_BG", "state.unconfirmed_bg"), ("UNMATCHED_BG", "state.unmatched_bg"),
    ("DATA_EMPTY_FG", "state.data_empty_fg"), ("SELECT_BG", "state.select_bg"),
    ("FILL_BG", "badge.fill_bg"), ("BLANK_BG", "badge.blank_bg"),
    ("MISSING_BG", "badge.missing_bg"), ("ACK_BG", "badge.ack_bg"), ("ACK_FG", "badge.ack_fg"),
]
# 목업 앱윈도 CSS 변수 이름 ← 토큰 경로(고정 팔레트; 스튜디오 셸 테마변수는 수작성 유지).
_MOCKUP_MAP = [
    ("--a-primary", "color.primary"), ("--a-primary-h", "color.primary_hover"),
    ("--a-warn", "color.warn"), ("--a-danger", "color.danger"),
    ("--a-ok", "color.ok"), ("--a-muted", "color.muted"),
    ("--a-border", "color.border"), ("--a-card", "color.card_bg"),
    ("--a-window", "color.window_bg"), ("--a-ink", "color.ink"),
    ("--a-unconf", "state.unconfirmed_bg"), ("--a-unmatch", "state.unmatched_bg"),
    ("--a-empty", "state.data_empty_fg"), ("--a-sel", "state.select_bg"),
]

OPEN_PY, CLOSE_PY = "# <gen:tokens>", "# </gen:tokens>"
OPEN_CSS, CLOSE_CSS = "/* <gen:tokens> */", "/* </gen:tokens> */"
_MOCKUP_INDENT = "    "


def load_tokens() -> dict:
    return json.loads(TOKENS.read_text(encoding="utf-8"))


def _dig(tokens: dict, path: str) -> str:
    group, key = path.split(".")
    return tokens[group][key]


def render_style_region(tokens: dict) -> str:
    """style.py 의 ``<gen:tokens>`` 영역 전문(마커 포함)."""
    lines = [OPEN_PY + " — scripts/gen_design_tokens.py 가 생성. 직접 편집 금지."]
    lines += [f'{name} = "{_dig(tokens, path)}"' for name, path in _STYLE_MAP]
    lines.append(CLOSE_PY)
    return "\n".join(lines)


def render_mockup_region(tokens: dict) -> str:
    """목업 ``:root`` 안 ``<gen:tokens>`` 영역 전문(4칸 들여쓰기 포함)."""
    lines = [_MOCKUP_INDENT + OPEN_CSS]
    lines += [f"{_MOCKUP_INDENT}{name}:{_dig(tokens, path)};" for name, path in _MOCKUP_MAP]
    lines.append(_MOCKUP_INDENT + CLOSE_CSS)
    return "\n".join(lines)


def _region_re(open_m: str, close_m: str) -> "re.Pattern[str]":
    # 열림 마커 직전의 같은 줄 들여쓰기까지 소비 → 치환 시 들여쓰기 중복 방지.
    return re.compile(r"[ \t]*" + re.escape(open_m) + r".*?" + re.escape(close_m), re.DOTALL)


def _splice(text: str, open_m: str, close_m: str, block: str) -> str:
    pat = _region_re(open_m, close_m)
    if not pat.search(text):
        raise SystemExit(f"마커({open_m} … {close_m})를 파일에서 찾을 수 없습니다.")
    return pat.sub(lambda _m: block, text, count=1)


def check() -> "list[str]":
    """디스크의 두 영역이 토큰과 일치하는지. 문제 목록 반환(빈 리스트=동기화됨)."""
    tokens = load_tokens()
    problems: "list[str]" = []
    for path, open_m, close_m, render in (
        (STYLE, OPEN_PY, CLOSE_PY, render_style_region),
        (MOCKUP, OPEN_CSS, CLOSE_CSS, render_mockup_region),
    ):
        text = path.read_text(encoding="utf-8")  # read_text 가 CRLF→\n 정규화
        m = _region_re(open_m, close_m).search(text)
        if m is None:
            problems.append(f"{path.name}: <gen:tokens> 마커 없음")
        elif m.group(0).strip() != render(tokens).strip():
            problems.append(f"{path.name}: 토큰 드리프트(design_tokens.json 과 불일치)")
    return problems


def rewrite() -> None:
    tokens = load_tokens()
    STYLE.write_text(
        _splice(STYLE.read_text(encoding="utf-8"), OPEN_PY, CLOSE_PY, render_style_region(tokens)),
        encoding="utf-8", newline="\n",
    )
    MOCKUP.write_text(
        _splice(MOCKUP.read_text(encoding="utf-8"), OPEN_CSS, CLOSE_CSS, render_mockup_region(tokens)),
        encoding="utf-8", newline="\n",
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="드리프트만 검사(쓰지 않음)")
    args = ap.parse_args(argv)
    if args.check:
        problems = check()
        if problems:
            print("토큰 드리프트:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        print("토큰 동기화 OK (style.py · 목업)")
        return 0
    rewrite()
    print("재생성 완료: style.py · docs/UI_PROTOTYPE_APPB.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
