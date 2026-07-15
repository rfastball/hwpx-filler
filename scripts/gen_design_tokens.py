#!/usr/bin/env python3
"""디자인 토큰 단일 출처 → 웹 CSS + 목업 CSS 재생성/검증.

색·상태색은 ``src/hwpxfiller/gui/design_tokens.json`` 한 곳에만 손으로 둔다. 이 스크립트가
그 값을 웹 프론트엔드 CSS(``web/css/tokens.css``·``web-diff/css/tokens.css``)와 목업 HTML
(``docs/UI_PROTOTYPE_APPB.html``)의 ``<gen:tokens>`` 영역(앱윈도 ``--a-*`` CSS 변수)에 찍는다.
디자인 색 변경 = JSON 1곳 편집 + regen. 백엔드(core/data)는 손대지 않는다.

Qt ``style.py``·``hwpxdiff/style.py`` 생성 타깃은 PySide6 제거(#23)로 폐기됐다 — 두 제품
모두 pywebview 웹이라 팔레트는 CSS 변수로만 소비된다.

    python scripts/gen_design_tokens.py           # 세 영역 재작성
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
MOCKUP = ROOT / "docs" / "UI_PROTOTYPE_APPB.html"
# 웹 프론트엔드(pywebview) CSS 변수 단일 출처(에픽 #20). 실앱은 스튜디오 셸 없이 앱윈도 자체라
# --a-* 팔레트를 주 테마로 쓰고, 배지/중성 틴트까지 토큰에서 받는다(스파이크 임시색 교체).
WEBCSS = ROOT / "web" / "css" / "tokens.css"
# 앱 A(diff) 웹 번들도 같은 --a-* 팔레트를 쓴다 — diff 는 별도 exe·별도 web-diff/ 번들이라
# 자립 사본이 필요하되, 값의 단일 출처는 이 JSON 이다(web/tokens.css 와 동일 _WEB_MAP).
WEBCSS_DIFF = ROOT / "web-diff" / "css" / "tokens.css"

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

# 웹 CSS 변수 이름 ← 토큰 경로. --a-* 핵심 팔레트(목업과 동일)에 배지/상태/중성 틴트를 더한다.
# 실앱 CSS(web/css/app.css)는 이 변수만 참조 — 색 리터럴 하드코딩 금지(스파이크 임시색 교체).
_WEB_MAP = [
    ("--a-primary", "color.primary"), ("--a-primary-h", "color.primary_hover"),
    ("--a-warn", "color.warn"), ("--a-danger", "color.danger"), ("--a-ok", "color.ok"),
    ("--a-muted", "color.muted"), ("--a-border", "color.border"), ("--a-card", "color.card_bg"),
    ("--a-window", "color.window_bg"), ("--a-ink", "color.ink"),
    ("--a-unconf", "state.unconfirmed_bg"), ("--a-unmatch", "state.unmatched_bg"),
    ("--a-empty", "state.data_empty_fg"), ("--a-sel", "state.select_bg"),
    ("--fb-fill-bg", "badge.fill_bg"), ("--fb-fill-bd", "badge.fill_border"),
    ("--fb-blank-bg", "badge.blank_bg"), ("--fb-blank-bd", "badge.blank_border"),
    ("--fb-missing-bg", "badge.missing_bg"), ("--fb-missing-bd", "badge.missing_border"),
    ("--fb-ack-bg", "badge.ack_bg"), ("--fb-ack-fg", "badge.ack_fg"),
    ("--fb-ack-bd", "badge.ack_border"),
    ("--n-surface-alt", "neutral.surface_alt"), ("--n-hover", "neutral.hover"),
    ("--n-pressed", "neutral.pressed"), ("--n-track", "neutral.track"),
    ("--n-header-bg", "neutral.header_bg"), ("--n-border-strong", "neutral.border_strong"),
    ("--n-border-control", "neutral.border_control"), ("--n-ink-soft", "neutral.ink_soft"),
    ("--n-header-ink", "neutral.header_ink"), ("--n-ink-control", "neutral.ink_control"),
    # 실행 화면 로그박스(웹 전용) — 어두운 콘솔 톤. style.py(Qt)는 QPlainTextEdit 기본이라 미사용.
    ("--log-surface", "log.surface"), ("--log-ink", "log.ink"),
]

OPEN_CSS, CLOSE_CSS = "/* <gen:tokens> */", "/* </gen:tokens> */"
_MOCKUP_INDENT = "    "
_WEB_INDENT = "  "


def load_tokens() -> dict:
    return json.loads(TOKENS.read_text(encoding="utf-8"))


def _dig(tokens: dict, path: str):
    group, key = path.split(".")
    return tokens[group][key]


def render_mockup_region(tokens: dict) -> str:
    """목업 ``:root`` 안 ``<gen:tokens>`` 영역 전문(4칸 들여쓰기 포함)."""
    lines = [_MOCKUP_INDENT + OPEN_CSS]
    lines += [f"{_MOCKUP_INDENT}{name}:{_dig(tokens, path)};" for name, path in _MOCKUP_MAP]
    lines.append(_MOCKUP_INDENT + CLOSE_CSS)
    return "\n".join(lines)


def render_web_region(tokens: dict) -> str:
    """웹 ``web/css/tokens.css`` 의 ``:root`` 안 ``<gen:tokens>`` 영역 전문(2칸 들여쓰기)."""
    lines = [_WEB_INDENT + OPEN_CSS]
    lines += [f"{_WEB_INDENT}{name}:{_dig(tokens, path)};" for name, path in _WEB_MAP]
    lines.append(_WEB_INDENT + CLOSE_CSS)
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
    """디스크의 세 CSS 영역이 토큰과 일치하는지. 문제 목록 반환(빈 리스트=동기화됨)."""
    tokens = load_tokens()
    problems: "list[str]" = []
    for path, open_m, close_m, render in (
        (MOCKUP, OPEN_CSS, CLOSE_CSS, render_mockup_region),
        (WEBCSS, OPEN_CSS, CLOSE_CSS, render_web_region),
        (WEBCSS_DIFF, OPEN_CSS, CLOSE_CSS, render_web_region),
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
    MOCKUP.write_text(
        _splice(MOCKUP.read_text(encoding="utf-8"), OPEN_CSS, CLOSE_CSS, render_mockup_region(tokens)),
        encoding="utf-8", newline="\n",
    )
    WEBCSS.write_text(
        _splice(WEBCSS.read_text(encoding="utf-8"), OPEN_CSS, CLOSE_CSS, render_web_region(tokens)),
        encoding="utf-8", newline="\n",
    )
    WEBCSS_DIFF.write_text(
        _splice(WEBCSS_DIFF.read_text(encoding="utf-8"), OPEN_CSS, CLOSE_CSS, render_web_region(tokens)),
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
        print("토큰 동기화 OK (목업 · web/tokens.css · web-diff/tokens.css)")
        return 0
    rewrite()
    print("재생성 완료: docs/UI_PROTOTYPE_APPB.html · "
          "web/css/tokens.css · web-diff/css/tokens.css")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
