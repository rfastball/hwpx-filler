"""토큰 재유입 가드(V14 / UD-33) — raw hex·인라인 setStyleSheet 의 QSS/위젯 재유입 차단.

UD-33 은 토큰 파이프라인이 상수 생성까지만 책임지고 **소비측**(BASE_QSS 본문·위젯 리터럴·
인라인 탈출구)에 소유자·가드가 없어 raw hex 12종·인라인 setStyleSheet 2곳·제3의 미입력색이
산재하던 사각지대였다. 색을 :mod:`design_tokens` 단일 출처로 환원한 뒤, 이 테스트가 정규식/
tokenize 로 소비측 재유입을 정적 차단한다(생성 규율만으로는 소비측을 못 막던 구멍을 봉함).

정책:
  1. BASE_QSS 본문에 raw hex 직접 등장 금지 — 색은 전부 ``{CONST}`` f-string 참조.
  2. gui/*.py(style.py 제외) 문자열/HTML 에 hex 색 리터럴 금지(QColor("#..")·인라인 HTML).
     주석 안 hex(안티패턴 문서화)는 tokenize 가 COMMENT 로 분리해 제외한다.
  3. 인라인 ``setStyleSheet`` 금지 — ``setStyleSheet(BASE_QSS)`` 창 자립 적용만 허용.

순수 소스 스캔이라 QApplication 불필요하나 style 임포트가 PySide6 를 요구하므로 미설치 시 skip.
"""
from __future__ import annotations

import re
import tokenize
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from hwpxfiller.gui import style  # noqa: E402

GUI_DIR = Path(style.__file__).parent
STYLE_PY = Path(style.__file__)
# 6자리(모든 앱 색) + 3자리 hex 색 리터럴. 단어경계로 라우트 조각 등 오검출을 줄인다.
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_QSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _base_qss_source() -> str:
    """style.py 소스에서 BASE_QSS f-string 본문(치환 전)을 그대로 떼어 온다.

    ``style.BASE_QSS`` 는 f-string 이 이미 상수를 hex 로 치환한 **렌더 결과**라 스캔하면
    전부 hex 로 보인다 — 재유입 검사는 반드시 소스 텍스트(``{CONST}`` 참조가 남은)를 본다.
    """
    src = STYLE_PY.read_text(encoding="utf-8")
    m = re.search(r'BASE_QSS = f"""(.*?)"""', src, re.DOTALL)
    assert m, "BASE_QSS f-string 블록을 찾을 수 없음"
    return m.group(1)


def _string_token_texts(path: Path) -> "list[tuple[int, str]]":
    """파일의 문자열·f-string 리터럴 토큰만 (라인, 텍스트)로. 주석(COMMENT)은 제외."""
    out: "list[tuple[int, str]]" = []
    string_types = {tokenize.STRING}
    if hasattr(tokenize, "FSTRING_MIDDLE"):
        string_types.add(tokenize.FSTRING_MIDDLE)
    with open(path, encoding="utf-8") as f:
        for tok in tokenize.generate_tokens(f.readline):
            if tok.type in string_types:
                out.append((tok.start[0], tok.string))
    return out


def test_base_qss_has_no_raw_hex():
    """BASE_QSS 본문에 raw hex 직접 등장 금지(색은 <gen:tokens> 상수 참조만)."""
    qss = _QSS_COMMENT.sub("", _base_qss_source())  # QSS /* */ 주석 속 예시 hex 제외
    hits = _HEX.findall(qss)
    assert not hits, (
        "BASE_QSS 에 raw hex 재유입: " + ", ".join(sorted(set(hits)))
        + " — design_tokens.json 토큰을 추가하고 {CONST} 로 참조하세요(직접 hex 금지)."
    )


def test_view_widgets_have_no_raw_hex():
    """gui/*.py(style.py 제외) 문자열/HTML 에 hex 색 리터럴 금지 — 주석은 제외(tokenize)."""
    offenders = []
    for path in sorted(GUI_DIR.glob("*.py")):
        if path == STYLE_PY:
            continue  # 팔레트 단일 출처(<gen:tokens>)+BASE_QSS 는 위 테스트가 담당
        for line, text in _string_token_texts(path):
            if _HEX.search(text):
                offenders.append(f"{path.name}:{line} → {text.strip()[:60]}")
    assert not offenders, (
        "위젯/HTML 문자열에 raw hex 재유입(setStyleSheet·QColor·인라인 span 등) — "
        "style 상수를 임포트해 참조하세요:\n  " + "\n  ".join(offenders)
    )


def test_no_inline_setstylesheet_in_views():
    """gui/*.py(style.py 제외)의 setStyleSheet 는 창 자립 적용(BASE_QSS)만 허용."""
    offenders = []
    for path in sorted(GUI_DIR.glob("*.py")):
        if path == STYLE_PY:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "setStyleSheet(" not in line:
                continue
            if "setStyleSheet(BASE_QSS)" in line:
                continue
            offenders.append(f"{path.name}:{i} → {line.strip()[:70]}")
    assert not offenders, (
        "인라인 setStyleSheet 재유입(색·타이포 인라인 탈출구) — 동적 프로퍼티 셀렉터"
        "(mark())로 통일하세요:\n  " + "\n  ".join(offenders)
    )


def test_v14_new_style_seams_exist():
    """V14 가 신설한 소비측 seam(보조 등급 셀렉터·metric/neutral 토큰)이 실재(회귀 가드)."""
    # UD-22 카드 반복 액션 보조 시각 등급
    assert 'QPushButton[emphasis="card"]' in style.BASE_QSS
    # UD-33 metric 스케일 실배선(정수 상수)
    assert isinstance(style.RADIUS_PILL, int) and style.RADIUS_PILL == 11
    assert isinstance(style.SPACE_MD, int)
    assert isinstance(style.TYPE_KPI, int)
    # UD-33 중성 회색 스케일 토큰
    assert style.NEUTRAL_INK_CONTROL.startswith("#")
    # UD-43 fb 배지 클램프 회피 — 전 fb 셀렉터에 min-height 배선(균일 24px)
    assert style.BASE_QSS.count("min-height") >= 5
