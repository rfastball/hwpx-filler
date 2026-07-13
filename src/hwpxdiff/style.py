"""앱 A(diff 리뷰어) 공통 스타일 — 팔레트 상수 + 기본 QSS(자립 단일 출처).

앱 B(hwpxfiller) 의 목업 디자인 문법을 diff 앱에도 그대로 입힌다: 색·상태 표현은
인라인 ``setStyleSheet`` 산재 대신 여기 상수와 QSS **동적 프로퍼티 셀렉터**
(``QPushButton[primary="true"]``·``QLabel[heading="true"]``·``QFrame[card="true"]``)로
통일하고, 위젯은 :func:`mark` 로 프로퍼티만 찍는다(app B ``gui/style.py`` 와 같은 관용).

**왜 사본인가** — diff 는 별도 앱/별도 exe 로, ``hwpxcore`` 만 공유하고 ``hwpxfiller``
는 패키징에서 통째로 제외된다(``packaging/hwpx_diff.spec`` excludes). 따라서 앱 B 의
``gui/style.py`` 를 런타임에 임포트할 수 없어 이 모듈이 자립한다. 대신 아래
``<gen:tokens>`` 팔레트 상수는 앱 B 와 **같은 단일 출처**(``gui/design_tokens.json``)에서
``scripts/gen_design_tokens.py`` 가 찍는다 — 색 드리프트는 ``tests/test_design_tokens.py``
가 막는다(직접 편집 금지).

diff 배지색(추가/삭제/변경/번호변경)은 여기가 아니라 ``core.diff.KIND_COLORS`` 가 원천이다
(HTML 리포트·전문 뷰·리스트 배지가 공유하는 팔레트라 코어 소유).
"""

from __future__ import annotations

# ---- 팔레트 상수 (단일 출처: hwpxfiller/gui/design_tokens.json) ----
# 아래 <gen:tokens> 영역은 scripts/gen_design_tokens.py 가 design_tokens.json 에서
# 생성한다 — 색을 바꾸려면 JSON 을 고치고 ``python scripts/gen_design_tokens.py`` 를
# 돌린다(직접 편집 금지). BASE_QSS·mark() 는 수작성이며 이 상수들을 참조한다.
# 의미 참고: PRIMARY=주 액션·WARN=비차단 경고·DANGER=치명·OK=통과·MUTED=부차·
# SELECT_BG=목록 선택 하이라이트.
# <gen:tokens> — scripts/gen_design_tokens.py 가 생성. 직접 편집 금지.
PRIMARY = "#2874a6"
PRIMARY_HOVER = "#1f5a80"
WARN = "#a05a00"
DANGER = "#c0392b"
OK = "#1e8449"
MUTED = "#656a72"
BORDER = "#e2e4e8"
CARD_BG = "#ffffff"
WINDOW_BG = "#f6f7f9"
INK = "#1c2126"
SELECT_BG = "#dce9f5"
# </gen:tokens>

BASE_QSS = f"""
QMainWindow {{ background: {WINDOW_BG}; }}
QLabel {{ color: {INK}; }}
QCheckBox {{ color: {INK}; }}

/* ── 공통 컨트롤(디자인 시스템 Qt 표면) — 목업의 카드/입력/버튼 룩으로 통일 ── */
QLineEdit {{
    background: #ffffff; border: 1px solid {BORDER}; border-radius: 4px;
    padding: 5px 8px; color: {INK};
    selection-background-color: {SELECT_BG}; selection-color: {INK};
}}
QLineEdit:focus {{ border: 1px solid {PRIMARY}; }}
QLineEdit:read-only {{ background: #f3f4f6; color: #5c626b; }}
QLineEdit:disabled {{ background: #f3f4f6; color: {MUTED}; }}

QPushButton {{
    background: #ffffff; color: #2b3038; border: 1px solid #cbd0d6;
    border-radius: 4px; padding: 6px 13px;
}}
QPushButton:hover {{ background: #f0f2f5; }}
QPushButton:pressed {{ background: #e6e9ee; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: #f6f7f9; }}
QPushButton::menu-indicator {{ subcontrol-position: right center; subcontrol-origin: padding; right: 6px; }}

QPushButton[primary="true"] {{
    background: {PRIMARY}; color: #ffffff; font-weight: 600;
    border: none; border-radius: 4px; padding: 6px 18px;
}}
QPushButton[primary="true"]:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton[primary="true"]:disabled {{ background: {MUTED}; }}

QHeaderView::section {{
    background: #eef1f4; color: #4a505a; padding: 5px 8px; border: none;
    border-bottom: 1px solid {BORDER}; font-weight: 600;
}}
QTableWidget {{
    background: #ffffff; gridline-color: #eef0f3;
    border: 1px solid {BORDER}; border-radius: 6px;
}}
QTableWidget::item:selected {{ background: {SELECT_BG}; color: {INK}; }}
QTextBrowser {{ background: #ffffff; border: 1px solid {BORDER}; border-radius: 6px; }}
QSplitter::handle {{ background: transparent; }}

/* 카드/KPI 타일(대시보드 문법) */
QFrame[card="true"] {{ background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 9px; }}
QLabel[kpi="value"] {{ font-size: 22px; font-weight: 800; }}
QLabel[kpi="label"] {{ color: {MUTED}; font-size: 11px; }}

QLabel[level="warn"] {{ color: {WARN}; }}
QLabel[level="danger"] {{ color: {DANGER}; }}
QLabel[level="ok"] {{ color: {OK}; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[heading="true"] {{ font-size: 15px; font-weight: 700; }}
QLabel[subheading="true"] {{ color: {MUTED}; font-size: 11px; font-weight: 600; }}
QLabel[pill="warn"] {{
    background: #f6ecdb; color: {WARN}; border: 1px solid #e6c98f;
    border-radius: 9px; padding: 1px 8px; font-weight: 600;
}}
"""


def mark(widget, prop: str, value) -> None:
    """동적 프로퍼티를 지정하고 스타일을 재적용한다(QSS 셀렉터 갱신 트리거)."""
    widget.setProperty(prop, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
