"""앱 B 공통 스타일 — 팔레트 상수 + 기본 QSS(단일 출처).

인라인 ``setStyleSheet`` 산재 금지: 색·상태 표현은 여기 상수와 QSS **동적 프로퍼티
셀렉터**(``QPushButton[primary="true"]``·``QLabel[level="warn"]``)로 통일한다.
각 최상위 창(홈·에디터·실행)이 생성자에서 :data:`BASE_QSS` 를 적용한다 — 앱 B는
자식 창 구조(app.py)라 QApplication 레벨보다 창 자립이 부분 적용·스모크에 유리.

diff 리뷰어(앱 A)의 배지색은 여기가 아니라 ``core.diff.CATEGORY_COLORS`` 가 원천이다
(HTML 리포트와 공유하는 팔레트라 코어 소유).
"""

from __future__ import annotations

# ---- 팔레트 상수 (단일 출처: gui/design_tokens.json) ----
# 아래 <gen:tokens> 영역은 scripts/gen_design_tokens.py 가 design_tokens.json 에서
# 생성한다 — 색을 바꾸려면 JSON 을 고치고 ``python scripts/gen_design_tokens.py`` 를
# 돌린다(직접 편집 금지). BASE_QSS·mark() 는 수작성이며 이 상수들을 참조한다.
# 상태색(미확정 UNCONFIRMED_BG / 미매칭 UNMATCHED_BG / 데이터빈값 DATA_EMPTY_FG)은
# mapping_table 이 여기서 임포트한다 — 색 리터럴 중복 금지(드리프트 방지).
# 의미 참고: PRIMARY=주 액션·WARN=비차단 경고·DANGER=치명·OK=통과·MUTED=부차·
# SELECT_BG=목록 선택 하이라이트(리포트 text_changed/removed/added 계열과 통일).
# <gen:tokens> — scripts/gen_design_tokens.py 가 생성. 직접 편집 금지.
PRIMARY = "#2874a6"
PRIMARY_HOVER = "#1f5a80"
WARN = "#a05a00"
DANGER = "#c0392b"
OK = "#1e8449"
MUTED = "#7a7f87"
BORDER = "#e2e4e8"
CARD_BG = "#ffffff"
WINDOW_BG = "#f6f7f9"
INK = "#1c2126"
UNCONFIRMED_BG = "#fff3bf"
UNMATCHED_BG = "#ffd8d8"
DATA_EMPTY_FG = "#b00020"
SELECT_BG = "#dce9f5"
FILL_BG = "#e5f2ea"
BLANK_BG = "#f6ecdb"
MISSING_BG = "#fbe6e3"
ACK_BG = "#ecebf4"
ACK_FG = "#4a3f8a"
# </gen:tokens>

BASE_QSS = f"""
QMainWindow, QWizard {{ background: {WINDOW_BG}; }}
QLabel {{ color: {INK}; }}

/* ── 공통 컨트롤(디자인 시스템 Qt 표면) — 목업의 카드/입력/버튼 룩으로 통일 ── */
QGroupBox {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 7px;
    margin-top: 12px; padding: 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left; left: 10px;
    padding: 0 6px; color: {MUTED};
}}

QLineEdit, QPlainTextEdit {{
    background: #ffffff; border: 1px solid {BORDER}; border-radius: 4px;
    padding: 5px 8px; color: {INK};
    selection-background-color: {SELECT_BG}; selection-color: {INK};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {PRIMARY}; }}
QLineEdit:read-only {{ background: #f3f4f6; color: #5c626b; }}
QLineEdit:disabled {{ background: #f3f4f6; color: {MUTED}; }}

QPushButton {{
    background: #ffffff; color: #2b3038; border: 1px solid #cbd0d6;
    border-radius: 4px; padding: 6px 13px;
}}
QPushButton:hover {{ background: #f0f2f5; }}
QPushButton:pressed {{ background: #e6e9ee; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: #f6f7f9; }}

QProgressBar {{
    border: 1px solid {BORDER}; border-radius: 6px; background: #eef0f3;
    text-align: center; color: {MUTED};
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 5px; }}

QHeaderView::section {{
    background: #eef1f4; color: #4a505a; padding: 5px 8px; border: none;
    border-bottom: 1px solid {BORDER}; font-weight: 600;
}}
QTableWidget {{ background: #ffffff; gridline-color: #eef0f3; }}
QListWidget {{ background: #ffffff; border: 1px solid {BORDER}; border-radius: 6px; }}

/* 대시보드 카드/KPI 타일 */
QFrame[card="true"] {{ background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 9px; }}
QLabel[kpi="value"] {{ font-size: 22px; font-weight: 800; }}
QLabel[kpi="label"] {{ color: {MUTED}; font-size: 11px; }}

QPushButton[primary="true"] {{
    background: {PRIMARY}; color: #ffffff; font-weight: 600;
    border: none; border-radius: 4px; padding: 6px 16px;
}}
QPushButton[primary="true"]:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton[primary="true"]:disabled {{ background: {MUTED}; }}

QLabel[level="warn"] {{ color: {WARN}; }}
QLabel[level="danger"] {{ color: {DANGER}; }}
QLabel[level="ok"] {{ color: {OK}; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[heading="true"] {{ font-size: 15px; font-weight: 700; }}
QLabel[pill="warn"] {{
    background: {BLANK_BG}; color: {WARN}; border: 1px solid #e6c98f;
    border-radius: 9px; padding: 1px 8px; font-weight: 600;
}}

QListWidget#jobList {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 6px;
}}
QListWidget#jobList::item {{ border-bottom: 1px solid {BORDER}; }}
QListWidget#jobList::item:selected {{
    background: {SELECT_BG}; border-left: 3px solid {PRIMARY};
}}

/* 실행 화면 인라인 필드 상태 배지(ADR-E/B): 채움/의도적 빈칸/미입력(클릭 확인)/확인됨. */
QLabel[fb="fill"] {{
    background: {FILL_BG}; color: {OK}; border: 1px solid #bfe0cb;
    border-radius: 11px; padding: 3px 10px; font-weight: 600;
}}
QLabel[fb="blank"] {{
    background: {BLANK_BG}; color: {WARN}; border: 1px solid #e6c98f;
    border-radius: 11px; padding: 3px 10px; font-weight: 600;
}}
QLabel[fb="missing"] {{
    background: {MISSING_BG}; color: {DANGER}; border: 1px solid #e6a49c;
    border-radius: 11px; padding: 3px 10px; font-weight: 600;
}}
QPushButton[fb="missing"] {{
    background: {MISSING_BG}; color: {DANGER}; border: 1px solid #e6a49c;
    border-radius: 11px; padding: 3px 11px; font-weight: 600; text-align: left;
}}
QPushButton[fb="missing"]:hover {{ background: #f9d9d4; }}
QPushButton[fb="ack"] {{
    background: {ACK_BG}; color: {ACK_FG}; border: 1px solid #c8c3e6;
    border-radius: 11px; padding: 3px 11px; font-weight: 600; text-align: left;
}}
"""


def mark(widget, prop: str, value) -> None:
    """동적 프로퍼티를 지정하고 스타일을 재적용한다(QSS 셀렉터 갱신 트리거)."""
    widget.setProperty(prop, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
