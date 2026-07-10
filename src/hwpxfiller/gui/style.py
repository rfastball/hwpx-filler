"""앱 B 공통 스타일 — 팔레트 상수 + 기본 QSS(단일 출처).

인라인 ``setStyleSheet`` 산재 금지: 색·상태 표현은 여기 상수와 QSS **동적 프로퍼티
셀렉터**(``QPushButton[primary="true"]``·``QLabel[level="warn"]``)로 통일한다.
각 최상위 창(홈·에디터·집행)이 생성자에서 :data:`BASE_QSS` 를 적용한다 — 앱 B는
자식 창 구조(app.py)라 QApplication 레벨보다 창 자립이 부분 적용·스모크에 유리.

diff 리뷰어(앱 A)의 배지색은 여기가 아니라 ``core.diff.CATEGORY_COLORS`` 가 원천이다
(HTML 리포트와 공유하는 팔레트라 코어 소유).
"""

from __future__ import annotations

# ---- 팔레트 상수 ----
PRIMARY = "#2874a6"        # 주 액션(리포트의 text_changed 파랑과 같은 계열)
PRIMARY_HOVER = "#1f5a80"
WARN = "#a05a00"           # 비차단 경고(구 wizard.py 인라인 색을 승격)
DANGER = "#c0392b"         # 치명(리포트 number/removed 빨강 계열)
OK = "#1e8449"             # 통과/성공(리포트 added 초록 계열)
MUTED = "#7a7f87"          # 부차 텍스트
BORDER = "#e2e4e8"
CARD_BG = "#ffffff"
WINDOW_BG = "#f6f7f9"

BASE_QSS = f"""
QMainWindow, QWizard {{ background: {WINDOW_BG}; }}

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

QListWidget#jobList {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 6px;
}}
QListWidget#jobList::item {{ border-bottom: 1px solid {BORDER}; }}
QListWidget#jobList::item:selected {{
    background: #dce9f5; border-left: 3px solid {PRIMARY};
}}
"""


def mark(widget, prop: str, value) -> None:
    """동적 프로퍼티를 지정하고 스타일을 재적용한다(QSS 셀렉터 갱신 트리거)."""
    widget.setProperty(prop, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
