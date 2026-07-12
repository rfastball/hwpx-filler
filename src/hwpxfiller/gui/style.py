"""앱 B 공통 스타일 — 팔레트 상수 + 기본 QSS(단일 출처).

인라인 ``setStyleSheet`` 산재 금지: 색·상태 표현은 여기 상수와 QSS **동적 프로퍼티
셀렉터**(``QPushButton[primary="true"]``·``QLabel[level="warn"]``)로 통일한다.
각 최상위 창(홈·에디터·실행)이 생성자에서 :data:`BASE_QSS` 를 적용한다 — 앱 B는
자식 창 구조(app.py)라 QApplication 레벨보다 창 자립이 부분 적용·스모크에 유리.

diff 리뷰어(앱 A)의 배지색은 여기가 아니라 ``core.diff.CATEGORY_COLORS`` 가 원천이다
(HTML 리포트와 공유하는 팔레트라 코어 소유).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QProgressBar

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

/* 레코드 선택 목록 — 체크박스를 또렷하게(선택 하이라이트 제거 대신 체크가 유일한 신호). */
QListWidget#recordList::item {{ padding: 3px 4px; }}
QListWidget#recordList::indicator {{
    width: 15px; height: 15px; border: 1px solid #adb3bb; border-radius: 3px; background: #ffffff;
}}
QListWidget#recordList::indicator:hover {{ border-color: {PRIMARY}; }}
QListWidget#recordList::indicator:checked {{ border-color: {PRIMARY}; background: {PRIMARY}; }}

/* 대시보드 카드/KPI 타일 */
QFrame[card="true"] {{ background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 9px; }}
QLabel[kpi="value"] {{ font-size: 22px; font-weight: 800; }}
QLabel[kpi="label"] {{ color: {MUTED}; font-size: 11px; }}

QPushButton[primary="true"] {{
    background: {PRIMARY}; color: #ffffff; font-weight: 600;
    border: none; border-radius: 4px; padding: 6px 16px;
}}
QPushButton[primary="true"]:hover {{ background: {PRIMARY_HOVER}; }}
/* 비활성 주 버튼은 일반 버튼 disabled 문법으로 수렴(UD-23): MUTED 채움을 재전용하면
   비활성 primary 가 활성 보조 버튼보다 시각 무게가 커지는 위계 역전이 난다.
   비활성은 활성보다 항상 약하게 — 채움 해제 + 회색 글자 + 옅은 테두리. */
QPushButton[primary="true"]:disabled {{
    background: #f6f7f9; color: {MUTED}; border: 1px solid {BORDER};
}}

/* 파괴(삭제) 버튼 등급(UD-12): DANGER 텍스트 + 붉은 외곽선, hover 시 미입력 배경.
   home/pool/vocab 이 삭제 버튼에 mark(btn,'level','danger') 를 걸어도 QPushButton
   레벨 셀렉터가 없어 죽은 표식이던 것을 소생시킨다(확인 다이얼로그는 마지막 방어선,
   이 시각 등급이 첫 신호다). */
QPushButton[level="danger"] {{
    color: {DANGER}; border: 1px solid #e6a49c; font-weight: 600;
}}
QPushButton[level="danger"]:hover {{ background: {MISSING_BG}; }}
QPushButton[level="danger"]:pressed {{ background: #f9d9d4; }}

/* muted 기본 하강은 명시 level(warn/danger/ok)보다 **먼저** 선언한다(UD-02): Qt QSS 는
   동일 특이도(속성 셀렉터 1개)에서 후순위 규칙이 이기므로, muted 를 앞에 두어야 뒤의
   level 이 muted 를 덮는다. 순서가 뒤바뀌면(muted 가 뒤) 완료 라벨의 level=ok 녹색이
   muted 회색(#7a7f87)에 패배해 성공 신호가 회색으로 죽던 함정이 재발한다. */
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[level="warn"] {{ color: {WARN}; }}
QLabel[level="danger"] {{ color: {DANGER}; }}
QLabel[level="ok"] {{ color: {OK}; }}
/* level='muted' 는 RAW·보관·무참조 배지가 발화(dataset_pool/vocab 상태 배지)하나
   셀렉터가 없어 기본 INK 검정 평문으로 렌더되던 무스타일 상태였다(UD-13) — 의도색
   (부차 회색)으로 소생시켜 조용한 상태 소실을 막는다. */
QLabel[level="muted"] {{ color: {MUTED}; }}
QLabel[heading="true"] {{ font-size: 15px; font-weight: 700; }}
/* 상태 배지 pill — 레벨 어휘(muted/warn/ok/danger)는 compile_badge.badge_level 이
   단일 출처(홈 카드·템플릿 관리가 같은 상태에 같은 심각도 신호 — RC-29). */
QLabel[pill="warn"] {{
    background: {BLANK_BG}; color: {WARN}; border: 1px solid #e6c98f;
    border-radius: 9px; padding: 1px 8px; font-weight: 600;
}}
QLabel[pill="ok"] {{
    background: {FILL_BG}; color: {OK}; border: 1px solid #bfe0cb;
    border-radius: 9px; padding: 1px 8px; font-weight: 600;
}}
QLabel[pill="muted"] {{
    background: #eef0f3; color: {MUTED}; border: 1px solid {BORDER};
    border-radius: 9px; padding: 1px 8px; font-weight: 600;
}}
QLabel[pill="danger"] {{
    background: {MISSING_BG}; color: {DANGER}; border: 1px solid #e6a49c;
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
/* 구조 드리프트 배지(UD-16): missing 색을 차용하던 4번째 상태에 전용 정체성을 준다.
   drift 는 레코드별 '값' 문제가 아니라 '구조' 문제(매핑 재확정) — 같은 danger 심각도
   계열이되 점선 테두리로 클릭형 미입력(실선 pill)과 시각 분리(정적 QLabel·비클릭). */
QLabel[fb="drift"] {{
    background: {MISSING_BG}; color: {DANGER}; border: 1px dashed {DANGER};
    border-radius: 11px; padding: 3px 10px; font-weight: 600;
}}
/* fb 버튼 :disabled 변형(UD-16): [fb] 규칙이 일반 :disabled 를 특이도로 덮어
   비활성 ack 버튼이 완전 채도의 '눌러 보이는' pill 로 렌더되던 문제 — 비활성 버튼은
   글자 채도를 낮춰 '지금 상호작용 불가(정지 상태)'를 신호한다(drift 는 QLabel 이라
   버튼 크롬이 없고 위 점선 정체성을 상태 불문 유지하므로 별도 dim 하지 않는다). */
QPushButton[fb="ack"]:disabled, QPushButton[fb="missing"]:disabled {{
    color: {MUTED}; border-color: {BORDER};
}}
"""


def mark(widget, prop: str, value) -> None:
    """동적 프로퍼티를 지정하고 스타일을 재적용한다(QSS 셀렉터 갱신 트리거)."""
    widget.setProperty(prop, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ContrastProgressBar(QProgressBar):
    """퍼센트 텍스트를 청크/그루브 경계로 2색 클리핑해 그리는 진행바(UD-31).

    QSS 로 ``::chunk`` 를 칠하는 순간 Qt(QStyleSheetStyle)는 텍스트를 단색 1패스로
    그려 네이티브의 청크-클리핑 대비 반전이 소실된다 — :data:`BASE_QSS` 의 MUTED 단색
    퍼센트 글자는 PRIMARY 청크 위에서 대비 ~1.3:1 로 붕괴한다(그루브 위 3.5:1 도 AA
    미달). 단일 텍스트색으로는 진한 청크·밝은 그루브 양쪽 4.5:1 을 동시 충족할 수
    없으므로, 여기서 텍스트를 직접 2패스로 그린다: 청크 위는 흰색(≈5:1), 그루브 위는
    INK(≈13:1). ``setTextVisible(False)`` 로 QSS 단색 텍스트는 끈다.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTextVisible(False)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — Qt 오버라이드
        super().paintEvent(event)  # 그루브·청크(QSS)만 그려짐(텍스트 꺼짐)
        span = self.maximum() - self.minimum()
        text = self.text()
        if span <= 0 or not text:
            return
        frac = (self.value() - self.minimum()) / span
        rect = self.rect()
        split = round(rect.width() * frac)
        align = int(Qt.AlignmentFlag.AlignCenter)
        painter = QPainter(self)
        painter.setFont(self.font())
        # 그루브(밝은 배경) 구간 — INK 짙은 글자
        painter.setPen(QColor(INK))
        painter.setClipRect(QRect(split, 0, rect.width() - split, rect.height()))
        painter.drawText(rect, align, text)
        # 청크(PRIMARY 짙은 배경) 구간 — 흰 글자
        painter.setPen(QColor("#ffffff"))
        painter.setClipRect(QRect(0, 0, split, rect.height()))
        painter.drawText(rect, align, text)
        painter.end()
