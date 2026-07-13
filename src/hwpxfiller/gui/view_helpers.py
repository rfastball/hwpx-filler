"""공용 뷰 헬퍼(링2, Qt) — 화면별 1회성으로 흩어진 공용 규율을 단일 출처로 모은다(V13).

여러 화면이 같은 규율(카드 높이 재동기·빈 상태·말줄임·빈 값 재진술)을 각자 1회성으로
구현(또는 미구현)하던 것을 공용 헬퍼로 통합한다. 신규 표면이 추가돼도 패턴이 자동
이식되도록 소유자를 여기 한 곳에 둔다.

- :func:`resync_card_item_heights` — QListWidget 카드의 item sizeHint 를 폴리시 후
  재계산(UD-11). 미폴리시 시점에 박제된 sizeHint 로 액션 버튼(보관/은퇴/삭제·마저
  변환/검토)이 세로 압착돼 판독 불가이던 것을, 홈의 지연 재동기 패턴을 추출해 전 패널에
  이식한다.
- :class:`ElidedLabel` — 가변 길이 사용자 문자열을 폭에 맞춰 말줄임하고 전체 이름을
  툴팁으로 노출(UD-30). RC-36(매핑 테이블 툴팁) 처치의 미이식 부위 이식.
- :func:`build_empty_state` — 스택 교체형 빈 상태 뷰(상태 재진술 + 선택적 CTA, UD-17).
- :func:`restate_preview_item`·마커 상수 — 미리보기·검수 표면의 빈 값/결측을 명시
  재진술(UD-26 · ADR-B '빈 공간으로 보이면 안 됨').

**style.py 무접촉(V14 소관)**: 신규 QSS 셀렉터를 만들지 않고 기존 상수(DATA_EMPTY_FG)·
기존 어휘((비움))·기존 QLabel 위계(heading/muted/primary)만 재사용한다.
"""

from __future__ import annotations

import contextlib

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .style import DATA_EMPTY_FG, mark

# 투명 전경(아이템 텍스트 숨김) — 카드 리스트 4패널이 각자 복제하던 이디엄의 단일 출처.
_TRANSPARENT = QColor(0, 0, 0, 0)


def hide_item_text(item: QListWidgetItem) -> None:
    """QListWidget 아이템의 텍스트를 투명 전경으로 숨긴다(UD-33 ④ 이디엄 승격).

    카드 목록은 아이템 ``text`` 를 계약(findItems 로 이름 조회·스모크)으로 유지하되 화면
    표시는 ``setItemWidget`` 카드가 담당한다 — 아이템 자체 텍스트가 카드 뒤로 비쳐 이중
    렌더되지 않게 전경을 투명색으로 눌러 온다. home/dataset_pool/vocab/template_manager
    4파일이 ``item.setForeground(QColor(0, 0, 0, 0))`` 을 주석까지 3중 복제하던 것을
    한 곳으로 모은다(신규 카드 리스트가 마법 호출을 빠뜨리는 조용한 회귀 방지)."""
    item.setForeground(_TRANSPARENT)

# 빈 값/결측 명시 재진술 어휘(UD-26) — mapping_table 의 '(비움)' 어휘를 검수 파생 표면과
# 공유한다(신규 어휘 발명 없음). 결측(키 부재, left 조인 무매칭)은 빈 값과 구별해 재진술.
EMPTY_VALUE_MARKER = "(비움)"
MISSING_VALUE_MARKER = "(결측)"


# --------------------------------------------------------------- UD-11: 카드 높이
def resync_card_item_heights(*list_widgets: QListWidget) -> None:
    """카드 폭을 뷰포트에 고정한 뒤 그 폭에서의 높이로 item sizeHint 를 재계산한다(UD-11).

    ``setItemWidget`` 직후(생성자 렌더) 시점의 ``card.sizeHint()`` 는 QSS 패딩·레이아웃이
    아직 반영되지 않아 실제보다 낮다 — 이 값을 item 에 박제하면 카드 액션 버튼이 세로로
    압착돼 라벨을 읽을 수 없다. 홈(``JobListHome._sync_item_widths``)에만 있던 지연 재동기를
    공용으로 추출해, 폴리시·레이아웃이 자리잡은 시점(``QTimer.singleShot(0)``·resizeEvent)에
    다시 불러 온전한 높이로 잡는다. 폭도 뷰포트에 고정해 가로 스크롤·메타 줄바꿈 결손을 막는다.
    """
    for lst in list_widgets:
        vp = lst.viewport().width()
        for i in range(lst.count()):
            it = lst.item(i)
            widget = lst.itemWidget(it)
            if widget is None:
                continue
            widget.ensurePolished()  # QSS 패딩 반영 후 높이를 재도록 강제 폴리시
            if vp > 0:
                widget.setFixedWidth(vp)  # 폭 고정 → 줄바꿈·높이 재계산
                it.setSizeHint(QSize(vp, widget.sizeHint().height()))
            else:
                hint = widget.sizeHint()
                it.setSizeHint(QSize(hint.width(), hint.height()))


# ------------------------------------------------------------- UD-30: 말줄임+툴팁
class ElidedLabel(QLabel):
    """가변 길이 문자열을 현재 폭에 맞춰 말줄임하고, 잘리면 전체 문자열을 툴팁으로 준다(UD-30).

    KPI 값·카드 제목·실행 요약 헤딩·txt 토큰 배지·템플릿 파일명 등 실데이터 길이가 고정
    위계 라벨을 밀어내거나 가로 스크롤을 유발하던 것을 RC-36(매핑 테이블 툴팁)과 동형인
    '말줄임 + 전체 이름 툴팁' 계약으로 봉합한다.

    ``max_width`` 를 주면 ``sizeHint`` 폭을 그 상한으로 눌러, 긴 문자열이 형제 위젯(상태
    배지 등)을 밀어내지 못하게 한다. ``minimumSizeHint`` 폭은 항상 작게 둬 좁은 레이아웃
    에서도 말줄임 여지를 남긴다(가로 스크롤·형제 압착 방지).
    """

    def __init__(
        self,
        text: str = "",
        *,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
        max_width: "int | None" = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self._max_width = max_width
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 — Qt 오버라이드
        self._full = text or ""
        self._relayout()

    def full_text(self) -> str:
        """말줄임 이전의 전체 문자열(테스트·호출자용 seam)."""
        return self._full

    def _avail_width(self) -> int:
        w = self.contentsRect().width()
        return w if w > 0 else self.width()

    def _relayout(self) -> None:
        fm = self.fontMetrics()
        avail = self._avail_width()
        if avail > 0 and fm.horizontalAdvance(self._full) > avail:
            super().setText(fm.elidedText(self._full, self._mode, avail))
            self.setToolTip(self._full)  # 잘렸을 때만 전체 이름 툴팁
        else:
            super().setText(self._full)
            self.setToolTip("")

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt 오버라이드
        super().resizeEvent(event)
        self._relayout()

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt 오버라이드
        fm = self.fontMetrics()
        h = super().sizeHint().height()
        w = fm.horizontalAdvance(self._full) + 2
        if self._max_width is not None:
            w = min(w, self._max_width)
        return QSize(w, h)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 — Qt 오버라이드
        fm = self.fontMetrics()
        h = super().minimumSizeHint().height()
        return QSize(fm.horizontalAdvance("…") + 4, h)


# ---------------------------------------------------------------- UD-17: 빈 상태
def build_empty_state(
    title: str,
    body: str = "",
    *,
    cta_text: str = "",
    on_cta=None,
) -> QWidget:
    """스택 교체형 빈 상태 뷰(상태 재진술 + 선택적 CTA, UD-17).

    home/template_manager 에만 있던 '스택 교체 + 중앙 안내 + CTA' 빈 상태 패턴을 공용으로
    추출한다 — 안내문 없는 백지·푸터 잔글씨(txt 트랙·데이터 풀·매핑 프로파일·매트릭스 작업
    목록)를 상태 재진술 + 다음 행동으로 통일한다.

    생성 경로가 다른 화면에만 있는 표면(매핑 프로파일: 작업 편집기에서만 생성)은
    ``cta_text`` 를 비워 안내만 준다 — 없던 진입점을 발명하지 않는다(핸드오프 관통 원리).
    생성한 CTA 버튼은 ``panel.cta`` 로 되찾을 수 있다(``None`` 이면 안내 전용).
    """
    panel = QWidget()
    box = QVBoxLayout(panel)
    box.addStretch(2)

    lbl = QLabel(title)
    mark(lbl, "heading", True)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    box.addWidget(lbl)

    if body:
        sub = QLabel(body)
        mark(sub, "muted", True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        box.addWidget(sub)

    cta: "QPushButton | None" = None
    if cta_text:
        cta = QPushButton(cta_text)
        mark(cta, "primary", True)
        if on_cta is not None:
            cta.clicked.connect(on_cta)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cta)
        row.addStretch(1)
        box.addLayout(row)

    box.addStretch(3)
    panel.cta = cta  # type: ignore[attr-defined]  # 빈 상태 CTA seam(테스트·호출자)
    return panel


# ---------------------------------------------------------- UD-26: 빈 값 재진술
def restate_preview_item(record: "dict", field: str) -> QTableWidgetItem:
    """미리보기 표 셀을 빈 값/결측을 명시 재진술해 만든다(UD-26 · ADR-B).

    파이프라인 left 조인 무매칭 결측과 원본 빈 문자열을 동일한 무표시 공백으로 렌더하던
    것을, mapping_table 의 빈 값 규율(``DATA_EMPTY_FG`` 빨강 + '(비움)')과 동형으로 봉합한다.
    키 부재(결측)와 빈 문자열(비움)을 구별해 재진술 — 검수자가 무매칭 행을 놓치지 않게 한다.
    """
    present = field in record
    raw = record.get(field, "")
    value = "" if raw is None else str(raw)
    item = QTableWidgetItem()
    if not present:
        item.setText(MISSING_VALUE_MARKER)
        item.setForeground(QBrush(QColor(DATA_EMPTY_FG)))
    elif value.strip() == "":
        item.setText(EMPTY_VALUE_MARKER)
        item.setForeground(QBrush(QColor(DATA_EMPTY_FG)))
    else:
        item.setText(value)
    return item


# ---------------------------------------------------------- ST-11: 창 지오메트리 지속
def _ui_settings():
    """UI 설정 저장소(INI) — ``HWPXFILLER_HOME`` 을 존중해 테스트가 tmp 로 격리된다.

    hwpxdiff 는 QSettings 네이티브(레지스트리)를 쓰나, 앱 B 는 표준 루트(``~/.hwpxfiller``
    또는 ``HWPXFILLER_HOME``) 아래 INI 파일을 써서 테스트가 사용자 레지스트리를 건드리지
    않게 한다(스모크가 HWPXFILLER_HOME 을 tmp 로 지정).
    """
    import os
    from pathlib import Path

    from PySide6.QtCore import QSettings

    home = os.environ.get("HWPXFILLER_HOME")
    base = Path(home) if home else Path.home() / ".hwpxfiller"
    return QSettings(str(base / "ui_settings.ini"), QSettings.Format.IniFormat)


def restore_geometry(win, key: str, *, default_size=None) -> None:
    """저장된 창 지오메트리를 복원한다(ST-11). 없거나 손상 시 default_size 로 폴백.

    지오메트리는 편의라 실패(손상 값·읽기 불가)는 조용히 폴백한다 — 시끄러운 예외 대신
    합리적 기본 크기로 연다. 생성자의 하드코딩 resize 를 이 호출로 대체한다.
    """
    from PySide6.QtCore import QByteArray

    raw = _ui_settings().value(f"geometry/{key}")
    if isinstance(raw, (QByteArray, bytes, bytearray)) and win.restoreGeometry(QByteArray(raw)):
        return
    if default_size is not None:
        win.resize(*default_size)


def save_geometry(win, key: str) -> None:
    """현재 창 지오메트리를 저장한다(closeEvent 에서 호출) — 세션 간 크기·위치 유지.

    새 QSettings 인스턴스가 곧바로 읽어도 보이도록 sync 로 디스크에 flush 한다(각 호출이
    QSettings 를 새로 만들어 소멸 지연 시 쓰기가 안 보이던 것 방지).
    """
    st = _ui_settings()
    st.setValue(f"geometry/{key}", win.saveGeometry())
    st.sync()


# ---------------------------------------------------------- ST-18: 상태 통지(live-region)
def announce_status(label, text: str) -> None:
    """상태 라벨 텍스트를 갱신하고 보조기술에 통지한다(ST-18, WCAG 4.1.3 Status Messages).

    동적 상태 메시지(취득 결과·완료 요약 등)는 화면엔 뜨지만 스크린리더엔 조용히 지나간다.
    텍스트 설정 후 QAccessible Alert 이벤트를 발신해 live-region 상당의 즉시 통지를 준다.
    보조기술이 비활성(리더 없음)이면 무해한 no-op — 시각 렌더는 무영향.
    """
    label.setText(text)
    from PySide6.QtGui import QAccessible, QAccessibleEvent

    QAccessible.updateAccessibility(QAccessibleEvent(label, QAccessible.Event.Alert))


# ---------------------------------------------------------- ST-12: 키보드 가속기
def wire_refresh_shortcut(win) -> None:
    """F5 → ``win.refresh()`` 단축키를 배선한다(ST-12, Nielsen H7).

    외부에서 파일이 바뀐 뒤 목록을 명시적으로 새로고침하는 표준 데스크톱 관행. 대상 창은
    인자 없는 공개 ``refresh()`` 를 가져야 한다(home·template·pool·vocab).
    """
    from PySide6.QtGui import QKeySequence, QShortcut

    QShortcut(QKeySequence("F5"), win, win.refresh)


def wire_submit_shortcut(win, button) -> None:
    """Ctrl+Return → 주 액션 버튼 실행(활성 시)(ST-12) — Enter 관성으로 제출.

    QMainWindow 에선 setDefault 가 효과가 약해, 포커스와 무관하게 도는 단축키로 주
    행동(문서 생성 등)을 키보드로 실행한다. 비활성이면 무동작(게이트 존중)."""
    from PySide6.QtGui import QKeySequence, QShortcut

    def _fire():
        if button.isEnabled():
            button.click()

    QShortcut(QKeySequence("Ctrl+Return"), win, _fire)


# ---------------------------------------------------------- ST-16: 동기 작업 대기 커서
@contextlib.contextmanager
def busy_cursor():
    """무거운 동기 작업 동안 대기 커서를 표시한다(ST-16, Nielsen H1 — 상태 가시성).

    1초 초과 가능 동기 IO(HWPX 재파싱·스키마 추출·컴파일·드리프트)를 이 컨텍스트로 감싸면
    UI 가 응답 없음처럼 얼어도 최소한 '처리 중' 신호가 뜬다. 예외가 나도 커서를 반드시
    복원한다(finally). 무거운 작업의 백그라운드 오프로드는 후속(worker 이식) 대상이다.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()
