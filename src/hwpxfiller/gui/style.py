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
MUTED = "#656a72"
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
FILL_BORDER = "#bfe0cb"
BLANK_BORDER = "#e6c98f"
MISSING_BORDER = "#e6a49c"
ACK_BORDER = "#c8c3e6"
MISSING_PRESS = "#f9d9d4"
NEUTRAL_SURFACE_ALT = "#f3f4f6"
NEUTRAL_HOVER = "#f0f2f5"
NEUTRAL_PRESSED = "#e6e9ee"
NEUTRAL_TRACK = "#eef0f3"
NEUTRAL_HEADER_BG = "#eef1f4"
NEUTRAL_BORDER_STRONG = "#cbd0d6"
NEUTRAL_BORDER_CONTROL = "#767b83"
NEUTRAL_INK_SOFT = "#5c626b"
NEUTRAL_HEADER_INK = "#4a505a"
NEUTRAL_INK_CONTROL = "#2b3038"
RADIUS_XS = 3
RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 9
RADIUS_PILL = 11
SPACE_XS = 2
SPACE_SM = 6
SPACE_MD = 12
SPACE_LG = 18
TYPE_LABEL = 11
TYPE_SMALL = 12
TYPE_BODY = 13
TYPE_TITLE = 14
TYPE_HEADING = 15
TYPE_KPI = 22
# </gen:tokens>

BASE_QSS = f"""
QMainWindow, QWizard {{ background: {WINDOW_BG}; }}
QLabel {{ color: {INK}; }}

/* ── 공통 컨트롤(디자인 시스템 Qt 표면) — 목업의 카드/입력/버튼 룩으로 통일 ── */
/* 색·radius 리터럴은 전부 <gen:tokens> 상수 참조다(UD-33): BASE_QSS 에 raw hex·스케일
   밖 radius 직접 등장 금지 — tests/test_token_reentry 정규식 가드가 재유입을 차단한다. */
QGroupBox {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px;
    margin-top: {SPACE_MD}px; padding: {SPACE_MD}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left; left: 10px;
    padding: 0 6px; color: {MUTED};
}}

QLineEdit, QPlainTextEdit {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
    padding: 5px 8px; color: {INK};
    selection-background-color: {SELECT_BG}; selection-color: {INK};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {PRIMARY}; }}
QLineEdit:read-only {{ background: {NEUTRAL_SURFACE_ALT}; color: {NEUTRAL_INK_SOFT}; }}
/* 읽기전용 필드가 포커스를 받아도 회색 룩을 유지한다(UD-37): :focus 파랑 테두리가
   :read-only 회색을 덮어 '편집 가능'을 오발신하던 신호 충돌 해소. 포커스 정책
   (wizard 의 setFocusPolicy NoFocus)이 1차 방어, 이 규칙이 QSS 상속 2차 방어 —
   :read-only:focus(의사상태 2개)가 :focus(1개)보다 특이도 높고 뒤에 선언돼 이긴다. */
QLineEdit:read-only:focus, QPlainTextEdit:read-only:focus {{ border: 1px solid {BORDER}; }}
QLineEdit:disabled {{ background: {NEUTRAL_SURFACE_ALT}; color: {MUTED}; }}

QPushButton {{
    background: {CARD_BG}; color: {NEUTRAL_INK_CONTROL}; border: 1px solid {NEUTRAL_BORDER_STRONG};
    border-radius: {RADIUS_SM}px; padding: 6px 13px;
}}
QPushButton:hover {{ background: {NEUTRAL_HOVER}; }}
QPushButton:pressed {{ background: {NEUTRAL_PRESSED}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: {WINDOW_BG}; }}

QProgressBar {{
    border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px; background: {NEUTRAL_TRACK};
    text-align: center; color: {MUTED};
}}
/* 청크는 그루브(radius md) 안에 1px 얹히므로 한 단 낮은 radius 로 중첩 인셋을 준다. */
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: {RADIUS_MD - 1}px; }}

QHeaderView::section {{
    background: {NEUTRAL_HEADER_BG}; color: {NEUTRAL_HEADER_INK}; padding: 5px 8px; border: none;
    border-bottom: 1px solid {BORDER}; font-weight: 600;
}}
QTableWidget {{ background: {CARD_BG}; gridline-color: {NEUTRAL_TRACK}; }}
/* outline: none — 네이티브 아이템뷰 포커스 사각형(Fusion 검은 라운드 박스)을 억제한다.
   키보드 포커스 가시성(ST-03)은 아래 ``QListWidget::item:focus`` 의 PRIMARY 테두리가
   담당하므로 접근성 손실 없이 잔재 검은 띠만 제거된다(navRail·jobList·recordList 공통). */
QListWidget {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px;
    outline: none;
}}

/* 레코드 선택 목록 — 체크박스를 또렷하게(선택 하이라이트 제거 대신 체크가 유일한 신호).
   인디케이터 18px + 행 세로 여백으로 행 높이를 24px 이상 확보한다(ST-15, WCAG 2.5.8 Target
   Size): 인디케이터당 행이 한 줄뿐이라 24px 원이 세로로 겹치지 않아 간격 예외를 충족한다. */
QListWidget#recordList::item {{ padding: 6px 4px; }}
QListWidget#recordList::indicator {{
    width: 18px; height: 18px; border: 1px solid {NEUTRAL_BORDER_CONTROL};
    border-radius: {RADIUS_XS}px; background: {CARD_BG};
}}
QListWidget#recordList::indicator:hover {{ border-color: {PRIMARY}; }}
QListWidget#recordList::indicator:checked {{ border-color: {PRIMARY}; background: {PRIMARY}; }}

/* 대시보드 카드/KPI 타일 */
QFrame[card="true"] {{ background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px; }}
QLabel[kpi="value"] {{ font-size: {TYPE_KPI}px; font-weight: 800; }}
QLabel[kpi="label"] {{ color: {MUTED}; font-size: {TYPE_LABEL}px; }}

QPushButton[primary="true"] {{
    background: {PRIMARY}; color: {CARD_BG}; font-weight: 600;
    border: none; border-radius: {RADIUS_SM}px; padding: 6px 16px;
}}
QPushButton[primary="true"]:hover {{ background: {PRIMARY_HOVER}; }}
/* 비활성 주 버튼은 일반 버튼 disabled 문법으로 수렴(UD-23): MUTED 채움을 재전용하면
   비활성 primary 가 활성 보조 버튼보다 시각 무게가 커지는 위계 역전이 난다.
   비활성은 활성보다 항상 약하게 — 채움 해제 + 회색 글자 + 옅은 테두리. */
QPushButton[primary="true"]:disabled {{
    background: {WINDOW_BG}; color: {MUTED}; border: 1px solid {BORDER};
}}

/* 카드 반복 액션 보조 시각 등급(UD-22): 카드마다 반복되는 주 액션(실행·기안 작성·편집·
   컴파일·작업 만들기)을 화면 전역 primary(채운 강조)로 두면 한 뷰포트에 강조가 곱절로
   늘어(홈 11개) 시선 유도가 소실된다. 화면당 primary 는 1개로 두고, 카드 반복 액션은 이
   중간 등급(accent 텍스트·테두리·무채움)으로 강등해 '카드 안의 주 액션'과 '화면의 주
   행동'을 시각 분리한다. 채도는 primary(채움) > emphasis(외곽) > 일반(회색) 순. */
QPushButton[emphasis="card"] {{
    background: {CARD_BG}; color: {PRIMARY}; border: 1px solid {PRIMARY};
    border-radius: {RADIUS_SM}px; padding: 6px 13px; font-weight: 600;
}}
QPushButton[emphasis="card"]:hover {{ background: {NEUTRAL_HOVER}; }}
QPushButton[emphasis="card"]:pressed {{ background: {NEUTRAL_PRESSED}; }}
QPushButton[emphasis="card"]:disabled {{ color: {MUTED}; border-color: {BORDER}; }}

/* 파괴(삭제) 버튼 등급(UD-12): DANGER 텍스트 + 붉은 외곽선, hover 시 미입력 배경.
   home/pool/vocab 이 삭제 버튼에 mark(btn,'level','danger') 를 걸어도 QPushButton
   레벨 셀렉터가 없어 죽은 표식이던 것을 소생시킨다(확인 다이얼로그는 마지막 방어선,
   이 시각 등급이 첫 신호다). */
QPushButton[level="danger"] {{
    color: {DANGER}; border: 1px solid {MISSING_BORDER}; font-weight: 600;
}}
QPushButton[level="danger"]:hover {{ background: {MISSING_BG}; }}
QPushButton[level="danger"]:pressed {{ background: {MISSING_PRESS}; }}

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
QLabel[heading="true"] {{ font-size: {TYPE_HEADING}px; font-weight: 700; }}
/* 상태 배지 pill — 레벨 어휘(muted/warn/ok/danger)는 compile_badge.badge_level 이
   단일 출처(홈 카드·템플릿 관리가 같은 상태에 같은 심각도 신호 — RC-29). */
QLabel[pill="warn"] {{
    background: {BLANK_BG}; color: {WARN}; border: 1px solid {BLANK_BORDER};
    border-radius: {RADIUS_LG}px; padding: 1px 8px; font-weight: 600;
}}
QLabel[pill="ok"] {{
    background: {FILL_BG}; color: {OK}; border: 1px solid {FILL_BORDER};
    border-radius: {RADIUS_LG}px; padding: 1px 8px; font-weight: 600;
}}
QLabel[pill="muted"] {{
    background: {NEUTRAL_TRACK}; color: {MUTED}; border: 1px solid {BORDER};
    border-radius: {RADIUS_LG}px; padding: 1px 8px; font-weight: 600;
}}
QLabel[pill="danger"] {{
    background: {MISSING_BG}; color: {DANGER}; border: 1px solid {MISSING_BORDER};
    border-radius: {RADIUS_LG}px; padding: 1px 8px; font-weight: 600;
}}

QListWidget#jobList {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px;
}}
QListWidget#jobList::item {{ border-bottom: 1px solid {BORDER}; }}
QListWidget#jobList::item:selected {{
    background: {SELECT_BG}; border-left: 3px solid {PRIMARY};
}}

/* 셸 네비 레일(ST-01, SHELL_DESIGN D1·D10): 현재 위치 표지 = 선택 하이라이트.
   기존 토큰만 재사용(ST-14 보류 존중 — 다크 레일 등 새 팔레트 발명 금지). 선택
   표기는 jobList 와 같은 SELECT_BG + PRIMARY 좌측 바 문법으로 통일한다. */
QListWidget#navRail {{
    background: {CARD_BG}; border: none; border-right: 1px solid {BORDER};
}}
QListWidget#navRail::item {{ padding: 10px 12px; color: {INK}; }}
QListWidget#navRail::item:hover {{ background: {NEUTRAL_HOVER}; }}
QListWidget#navRail::item:selected {{
    background: {SELECT_BG}; color: {INK}; border-left: 3px solid {PRIMARY};
}}

/* 실행 화면 인라인 필드 상태 배지(ADR-E/B): 채움/의도적 빈칸/미입력(클릭 확인)/확인됨.
   fb 전종은 radius(pill=11)의 절반 경계(2*11=22px)에 걸려 글리프 메트릭에 따라 필/직각
   으로 분열했다(UD-43: missing 칩만 자연높이 21px<22 라 클램프→직각·3px 낮음). min-height
   를 클램프 경계 위(2*RADIUS_PILL+2=24px)로 고정해 모든 상태·폰트에서 동일 높이·라운드로
   통일한다 — V1 계측(21→직각)이 지목한 안전 마진. min-height 는 content-box 라 실제 칩
   높이는 여기에 padding·border 가 더해지지만, 짧은 글리프를 24 바닥으로 끌어올려 이웃과
   높이·코너를 맞춘다. */
QLabel[fb="fill"] {{
    background: {FILL_BG}; color: {OK}; border: 1px solid {FILL_BORDER};
    border-radius: {RADIUS_PILL}px; padding: 3px 10px; min-height: {2 * RADIUS_PILL - 6}px;
    font-weight: 600;
}}
QLabel[fb="blank"] {{
    background: {BLANK_BG}; color: {WARN}; border: 1px solid {BLANK_BORDER};
    border-radius: {RADIUS_PILL}px; padding: 3px 10px; min-height: {2 * RADIUS_PILL - 6}px;
    font-weight: 600;
}}
QLabel[fb="missing"] {{
    background: {MISSING_BG}; color: {DANGER}; border: 1px solid {MISSING_BORDER};
    border-radius: {RADIUS_PILL}px; padding: 3px 10px; min-height: {2 * RADIUS_PILL - 6}px;
    font-weight: 600;
}}
QPushButton[fb="missing"] {{
    background: {MISSING_BG}; color: {DANGER}; border: 1px solid {MISSING_BORDER};
    border-radius: {RADIUS_PILL}px; padding: 3px 11px; min-height: {2 * RADIUS_PILL - 6}px;
    font-weight: 600; text-align: left;
}}
QPushButton[fb="missing"]:hover {{ background: {MISSING_PRESS}; }}
QPushButton[fb="ack"] {{
    background: {ACK_BG}; color: {ACK_FG}; border: 1px solid {ACK_BORDER};
    border-radius: {RADIUS_PILL}px; padding: 3px 11px; min-height: {2 * RADIUS_PILL - 6}px;
    font-weight: 600; text-align: left;
}}
/* 구조 드리프트 배지(UD-16): missing 색을 차용하던 4번째 상태에 전용 정체성을 준다.
   drift 는 레코드별 '값' 문제가 아니라 '구조' 문제(매핑 재확정) — 같은 danger 심각도
   계열이되 점선 테두리로 클릭형 미입력(실선 pill)과 시각 분리(정적 QLabel·비클릭). */
QLabel[fb="drift"] {{
    background: {MISSING_BG}; color: {DANGER}; border: 1px dashed {DANGER};
    border-radius: {RADIUS_PILL}px; padding: 3px 10px; min-height: {2 * RADIUS_PILL - 6}px;
    font-weight: 600;
}}
/* fb 버튼 :disabled 변형(UD-16): [fb] 규칙이 일반 :disabled 를 특이도로 덮어
   비활성 ack 버튼이 완전 채도의 '눌러 보이는' pill 로 렌더되던 문제 — 비활성 버튼은
   글자 채도를 낮춰 '지금 상호작용 불가(정지 상태)'를 신호한다(drift 는 QLabel 이라
   버튼 크롬이 없고 위 점선 정체성을 상태 불문 유지하므로 별도 dim 하지 않는다). */
QPushButton[fb="ack"]:disabled, QPushButton[fb="missing"]:disabled {{
    color: {MUTED}; border-color: {BORDER};
}}

/* ── 키보드 포커스 가시성(ST-03, WCAG 2.4.7 Focus Visible) ──
   BASE_QSS 가 컨트롤을 전면 재스타일하면서 QLineEdit/QPlainTextEdit(:focus 기존)을 뺀
   버튼·리스트 아이템·인디케이터의 네이티브 포커스 링이 억제됐다. Tab 이동 위치를 다시
   보이게 복원한다 — 전부 기존과 동일 폭 테두리를 재색(레이아웃 불변)하거나, 채운 primary
   만 padding 1px 보정해 총 박스 크기를 유지한다. 스타일 안 한 bare QComboBox/QCheckBox/
   QRadioButton 은 네이티브 포커스가 살아 있어 여기 대상이 아니다. 이 블록은 버튼/리스트
   규칙 뒤에 두어 동일 특이도(type+pseudo)에서 후순위로 이긴다. */
QPushButton:focus {{ border: 1px solid {PRIMARY}; }}
QPushButton[primary="true"]:focus {{ border: 1px solid {INK}; padding: 5px 15px; }}
QListWidget::item:focus {{ border: 1px solid {PRIMARY}; }}
QListWidget#recordList::indicator:focus {{ border-color: {PRIMARY}; }}
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
        # 청크(PRIMARY 짙은 배경) 구간 — 흰 글자(CARD_BG=최명도 표면색, raw hex 미사용)
        painter.setPen(QColor(CARD_BG))
        painter.setClipRect(QRect(0, 0, split, rect.height()))
        painter.drawText(rect, align, text)
        painter.end()
