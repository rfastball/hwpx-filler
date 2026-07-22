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
    # on_accent = 컬러 accent(primary/ok) 필 위 글씨. 라이트=흰색, 다크=어두운 잉크(accent 를
    # 밝혀 텍스트로도 읽히게 하므로 흰글씨가 대비 미달 → 잉크로 뒤집는다). shadow = 모달 승강 그림자.
    ("--a-on-accent", "color.on_accent"), ("--a-shadow", "color.shadow"),
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

# 스케일 변수(여백·모서리·폰트크기) ← JSON space/radius/type. 색과 달리 **테마 불변** —
# 라이트 :root 블록에만 방출하고 다크 블록엔 중복하지 않는다. 값은 무단위 정수 → px 부착.
# space 는 수치키(--sp-8 = 8px, 촘촘한 px 그리드), radius/type 은 역할 의미키.
_SCALE_MAP = [
    # 여백은 2px 기저 수치 사다리 — 희소 오드볼(14·20·28)은 꼬리청소로 퇴역(#60), 인접값 스냅.
    # 6·8·10·12·16 유지(현행 밀도가 스위트스팟, A/B/C 실화면 왕복 검증). 엄격 4px 격자는 기각.
    ("--sp-2", "space.2"), ("--sp-4", "space.4"), ("--sp-6", "space.6"),
    ("--sp-8", "space.8"), ("--sp-10", "space.10"), ("--sp-12", "space.12"),
    ("--sp-16", "space.16"), ("--sp-24", "space.24"), ("--sp-40", "space.40"),
    # 모서리는 크기 사다리가 아니라 역할 문법(#59) — 이름이 역할을 강제해 "같은 컨트롤인데 다른
    # 모서리"류 자의적 배정을 구조로 차단. control=버튼·필드·탭·행·칩·메뉴항목, surface=카드·판·
    # 콜아웃·placeholder, overlay=모달·메뉴, pill=완전 둥금.
    ("--rad-control", "radius.control"), ("--rad-surface", "radius.surface"),
    ("--rad-overlay", "radius.overlay"), ("--rad-pill", "radius.pill"),
    # 타이포는 크기 사다리(12/14/15/19)+kpi 역할 — 층위는 크기, 역할은 색(--a-muted)·굵기(600)로
    # 진다(#58). caption=muted 라벨·배지·캡션, body=주 읽기 본문·버튼·입력(#179 가독성 14px),
    # dense=고밀도 데이터 그리드 전용(본문 14px 승격 시 표가 너무 커지지 않게 13px 유지, #179),
    # strong=헤딩·강조, section=화면/섹션 제목, kpi=대시보드 수치.
    ("--fs-caption", "type.caption"), ("--fs-body", "type.body"), ("--fs-dense", "type.dense"),
    ("--fs-strong", "type.strong"), ("--fs-section", "type.section"), ("--fs-kpi", "type.kpi"),
]

# 모션 변수(#179 슬라이스 4) — 스케일과 같은 **테마 불변**이라 라이트 :root 만 방출한다.
# 스케일(_SCALE_MAP)과 달리 단위가 갈린다: dur_*=정수 → ms 부착, ease_*=cubic-bezier 문자열은
# 그대로(단위 없음). unit 열이 그 차이를 담는다("ms" 또는 "").
_MOTION_MAP = [
    ("--dur-press", "motion.dur_press", "ms"), ("--dur-pop", "motion.dur_pop", "ms"),
    ("--dur-modal", "motion.dur_modal", "ms"),
    ("--ease-out", "motion.ease_out", ""), ("--ease-in-out", "motion.ease_in_out", ""),
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


def _web_vars(root: dict, indent: str) -> "list[str]":
    """``_WEB_MAP`` 을 ``root`` 기준으로 판 CSS 변수 선언들(indent 접두)."""
    return [f"{indent}{name}:{_dig(root, path)};" for name, path in _WEB_MAP]


def _scale_vars(tokens: dict, indent: str) -> "list[str]":
    """``_SCALE_MAP`` 을 판 스케일 CSS 변수 선언들(무단위 정수 → ``px`` 부착)."""
    return [f"{indent}{name}:{_dig(tokens, path)}px;" for name, path in _SCALE_MAP]


def _motion_vars(tokens: dict, indent: str) -> "list[str]":
    """``_MOTION_MAP`` 을 판 모션 CSS 변수 선언들(dur=``ms`` 부착, ease=문자열 그대로)."""
    return [f"{indent}{name}:{_dig(tokens, path)}{unit};" for name, path, unit in _MOTION_MAP]


def render_web_region(tokens: dict) -> str:
    """웹 ``web/css/tokens.css`` 의 ``<gen:tokens>`` 영역 전문(:root 래퍼까지 생성물).

    표준 견고 패턴을 방출한다 — OS 기본은 미디어쿼리, 앱 토글([data-theme])이 양방향으로 이긴다:
      :root{ 라이트; color-scheme:light }
      @media(prefers-color-scheme:dark){ :root:not([data-theme=light]){ 다크; color-scheme:dark } }
      :root[data-theme=dark]{ 다크; color-scheme:dark }
    다크 선언은 미디어쿼리·명시 셀렉터에 두 번 실린다(CSS 변수는 재사용 include 가 없어 반복이 정답).
    color-scheme 로 WebView2 네이티브 크롬(스크롤바·<select>·체크박스)도 테마를 추종한다.
    마커(<gen:tokens>)는 이제 :root 를 포함한 전체 영역을 감싼다 — tokens.css 의 :root 수기 래퍼는 제거됨.
    스케일·모션 변수(--sp-*·--rad-*·--fs-*·--dur-*·--ease-*)는 테마 불변이라 이 라이트 :root 블록에만 실린다(다크 두 블록 미중복)."""
    dark = tokens["dark"]
    lines = [OPEN_CSS, ":root{"]
    lines += _web_vars(tokens, "  ")
    lines += _scale_vars(tokens, "  ")
    lines += _motion_vars(tokens, "  ")
    lines += ["  color-scheme:light;", "}",
              "@media (prefers-color-scheme:dark){",
              '  :root:not([data-theme="light"]){']
    lines += _web_vars(dark, "    ")
    lines += ["    color-scheme:dark;", "  }", "}",
              ':root[data-theme="dark"]{']
    lines += _web_vars(dark, "  ")
    lines += ["  color-scheme:dark;", "}", CLOSE_CSS]
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
