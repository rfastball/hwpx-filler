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
- :func:`ask_sheet_choice` — 다중 시트 통합문서의 시트 확정 다이얼로그(T2). 5표면
  (위저드·실행·매트릭스·txt·풀 등록)이 같은 확정 규율을 공유한다(첫-시트 추측 금지).
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
    QInputDialog,
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


# ---------------------------------------------------------- T2: 시트 확정 다이얼로그
def ask_sheet_choice(parent, path) -> "str | None":
    """다중 시트 통합문서의 사용 시트를 사용자에게 확정받는다(확인-또는-경보).

    생략 판정 단일 출처는 T1 :func:`~hwpxfiller.data.excel.sheet_overview` 다 —
    CSV(빈 목록)·단일 시트(길이 1)는 물을 것이 없어 ``""`` 를 돌려주고 호출자는
    기본(첫/유일 시트) 로드로 진행한다. 시트가 2개 이상이면
    ``QInputDialog.getItem`` (:meth:`~hwpxfiller.gui.batch_run.DataAcquireController
    .pick_from_pool` 의 풀 선택 getItem 선례 동형)으로 묻되, 항목 문구에 시트별
    행×열 **근사치**(저장 시점 dimension 기반)를 병기해 눈으로 고를 근거를 준다.

    반환 계약: 확정 시트명(str) / ``""`` = 물을 것 없음(기본 로드) / **None = 취소**
    — 호출자는 파일 겨눔 **전체를 중단**해야 한다(조용한 첫-시트 추측 금지).
    통합문서 열거 실패(손상 파일 등)는 raise — 호출자의 로드 실패 경로가 시끄럽게
    알린다(조용한 생략 금지).
    """
    from ..data import sheet_overview

    overview = sheet_overview(path)
    if len(overview) < 2:
        return ""
    items = [f"{name} — 약 {rows}행×{cols}열" for name, rows, cols in overview]
    choice, ok = QInputDialog.getItem(
        parent, "시트 선택",
        "이 파일에는 시트가 여러 개 있습니다 — 사용할 시트를 확정하세요.\n"
        "(행×열은 저장 시점 근사치)",
        items, 0, False,
    )
    if not ok or not choice:
        return None
    return overview[items.index(choice)][0]


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


# ---------------------------------------------------- T3: 용도별 마지막 디렉터리 지속
def last_dir(purpose: str) -> str:
    """용도별 마지막 디렉터리를 읽는다(T3) — 파일 다이얼로그 **시작 디렉터리** 전용.

    지오메트리(ST-11)와 동급 규율: 편의라 실패는 조용히 폴백한다 — 미저장·손상 값·
    삭제된 디렉터리는 빈 문자열(OS 기본 시작 위치)로 돌아가고 예외를 내지 않는다.
    용도(purpose: template/data/mapping/prev_doc/output/txt_save/library)별로 키를
    분리해 서로 다른 용도의 선택이 섞이지 않게 한다. 반환은 디렉터리뿐이다 —
    파일 경로 프리필 금지(시작 위치만 제공, 파일명은 항상 사용자 몫).
    """
    from pathlib import Path

    raw = _ui_settings().value(f"last_dir/{purpose}")
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        if Path(raw).is_dir():
            return raw
    except OSError:
        pass  # 접근 불가 드라이브 등 — 조용한 폴백(편의 지속의 실패는 시끄럽지 않게)
    return ""


def save_last_dir(purpose: str, path) -> None:
    """성공 선택된 경로의 **부모 디렉터리**를 용도별로 저장한다(T3).

    호출자는 다이얼로그가 확정 경로를 돌려줬을 때만 부른다 — 취소(빈 값)는 호출하지
    않아 직전 기억이 보존된다. 파일·디렉터리 선택 모두 부모를 저장한다(다음 열기가
    직전 선택을 목록에서 바로 보게). sync 는 :func:`save_geometry` 와 동일 근거 —
    각 호출이 QSettings 를 새로 만들므로 즉시 flush 해야 다음 읽기에 보인다.
    """
    from pathlib import Path

    if not path:
        return
    parent = str(Path(path).parent)
    st = _ui_settings()
    st.setValue(f"last_dir/{purpose}", parent)
    st.sync()


# ---------------------------- 작업 브라우저 렌즈 지속(JOB_BROWSER_DESIGN D4)
def load_home_lens() -> "tuple[str | None, dict[str, set[str]]]":
    """홈 좌 트랙 group-by 렌즈 + facet 선택을 INI 에서 복원(D4 사용자 소유 지속 상태).

    지오메트리·last_dir 과 동급 규율: 편의 지속이라 미저장·손상 값은 조용히 폴백한다.
    group_by 반환은 ``str | None`` — **None 은 '미저장'**(위젯이 씨앗 렌즈를 유지)이고,
    ""(빈 문자열)은 '사용자가 flat 을 명시 선택'이라 구별한다. 링1 VM 은 지속을 모르고
    확정된 값만 위젯이 주입한다(링 경계).
    """
    import json

    st = _ui_settings()
    gb = st.value("lens/home_group_by")
    group_by = gb if isinstance(gb, str) else None
    facets: "dict[str, set[str]]" = {}
    raw = st.value("lens/home_facets")
    if isinstance(raw, str) and raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            for axis, values in data.items():
                if isinstance(axis, str) and isinstance(values, list):
                    vs = {v for v in values if isinstance(v, str)}
                    if vs:
                        facets[axis] = vs
    return group_by, facets


def save_home_lens(group_by: str, facets: "dict[str, set[str]]") -> None:
    """홈 렌즈 상태를 INI 에 저장(사용자 조작 시 위젯이 호출). facet 은 축→정렬 값리스트 JSON.

    sync 근거는 :func:`save_geometry` 와 동일(각 호출이 QSettings 를 새로 만들어 즉시 flush).
    """
    import json

    payload = {axis: sorted(vs) for axis, vs in facets.items() if vs}
    st = _ui_settings()
    st.setValue("lens/home_group_by", group_by or "")
    st.setValue("lens/home_facets", json.dumps(payload, ensure_ascii=False))
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

    컨텍스트는 WidgetWithChildrenShortcut(SHELL_DESIGN D9): 셸 임베드(ST-01) 후 한
    창에 F5 대상 페이지가 여럿 공존한다 — 기본 WindowShortcut 이면 Qt 모호 활성
    (activatedAmbiguously)으로 **전부 무동작**하는 조용한 회귀. 포커스를 가진
    페이지에서만 발화한다(독립 창으로 쓰일 때는 의미 동일).
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence, QShortcut

    sc = QShortcut(QKeySequence("F5"), win, win.refresh)
    sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)


def wire_submit_shortcut(win, button) -> None:
    """Ctrl+Return → 주 액션 버튼 실행(활성 시)(ST-12) — Enter 관성으로 제출.

    QMainWindow 에선 setDefault 가 효과가 약해, 포커스와 무관하게 도는 단축키로 주
    행동(문서 생성 등)을 키보드로 실행한다. 비활성이면 무동작(게이트 존중).

    컨텍스트는 WidgetWithChildrenShortcut(SHELL_DESIGN D9) — 셸 임베드 후 run·matrix
    의 Ctrl+Return 공존 모호 활성을 막는다(wire_refresh_shortcut 과 동일 근거)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence, QShortcut

    def _fire():
        if button.isEnabled():
            button.click()

    sc = QShortcut(QKeySequence("Ctrl+Return"), win, _fire)
    sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)


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


# ---------------------------------------------------------- ST-20: 오류 메시지 성형
def describe_exception(exc: BaseException) -> str:
    """예외를 사용자 대면 한국어 문구로 성형한다(ST-20, Nielsen H9·WCAG 3.3.3).

    원시 ``str(exc)``(PermissionError·BadZipFile·WinError)는 개발자용이라 사용자에게 다음
    행동을 주지 못한다 — 유형별로 무엇이 잘못됐고 어떻게 회복하는지 안내한다. 미지 유형은
    원문을 돌려준다(조용한 은폐 금지 — 원인 전문은 :func:`show_error` 가 접어서 병기).
    """
    import zipfile

    if isinstance(exc, PermissionError):
        return "파일에 접근할 수 없습니다 — 다른 프로그램(한글 등)에서 열려 있지 않은지 확인하세요."
    if isinstance(exc, FileNotFoundError):
        return "파일을 찾을 수 없습니다 — 경로가 바뀌었거나 삭제되었을 수 있습니다."
    if isinstance(exc, zipfile.BadZipFile):
        return "손상되었거나 HWPX(zip) 형식이 아닌 파일입니다."
    if isinstance(exc, (IsADirectoryError, NotADirectoryError)):
        return "경로가 올바른 파일이 아닙니다."
    if isinstance(exc, UnicodeDecodeError):
        return "파일 인코딩을 해석할 수 없습니다 — 형식·인코딩을 확인하세요."
    return str(exc)


def show_error(parent, title: str, exc: BaseException) -> None:
    """유형별 문구 + 원시 예외를 함께 실은 오류 모달을 띄운다(ST-20).

    사용자 대면 문구(:func:`describe_exception`)를 앞에 두고, 진단용 원문은 뒤에 병기한다 —
    평이한 안내와 원인을 모두 잃지 않는다. 표시는 ``QMessageBox.critical`` 로 통일해 다른
    실패 통지와 같은 이음새를 쓴다(테스트가 이 정적 메서드를 가로채 무모달로 검증).
    """
    from PySide6.QtWidgets import QMessageBox

    friendly = describe_exception(exc)
    raw = str(exc)
    message = friendly if friendly == raw else f"{friendly}\n\n{raw}"
    QMessageBox.critical(parent, title, message)
