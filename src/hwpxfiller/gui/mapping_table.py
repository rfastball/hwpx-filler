"""매핑 테이블 뷰 — MappingModel 을 QTableWidget 으로 렌더/편집한다.

열: [확정 | 템플릿 필드 | 데이터 항목 | 타입/고정값 | 표시형 | 미리보기].
행 색: 미확정=노랑, 소스 없는 미확정(미매칭)=빨강, 확정=기본.
모든 편집은 MappingModel 편집 API 를 거치고(편집 → 확정 해제 규칙 포함),
변경 시 ``completeChanged`` 시그널을 쏜다(위저드 isComplete 연동용).

**엄격한 1:1 계약.** 한 템플릿 필드는 정확히 한 데이터 항목(단일 소스)에서 값을
취한다 — 구분자 결합(N→1)·다중선택은 없다. 고정값 입력은 타입이 ``const`` 일 때만
타입 선택 옆에 나타나며 소스와 무관한 리터럴을 담는다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.format_engine import presets as format_presets
from ..core.mapping import TYPES
from .confirm import confirm_destructive
from .mapping_state import MappingModel
from .style import DATA_EMPTY_FG, UNCONFIRMED_BG, UNMATCHED_BG, mark

# 값 유형 코드 → 한국어 라벨(콤보 표시 순서는 TYPES 그대로).
TYPE_LABELS = {"text": "텍스트", "date": "날짜", "amount": "금액", "const": "고정값"}
# 스키마가 템플릿 내용에서 **추정한** 타입 라벨. 실제 변환 타입(TYPE_LABELS)과 구분해
# 표시한다(C08AD62D) — number 추정도 실제 기본 변환은 text일 수 있다.
INFERRED_TYPE_LABELS = {
    "text": "텍스트", "date": "날짜", "amount": "금액", "number": "숫자",
    "phone": "전화번호",
}


class _NoScrollComboBox(QComboBox):
    """휠 스크롤로 선택이 바뀌지 않게 하는 콤보 — 이벤트를 위(표)로 넘겨 표가 스크롤되게 한다.

    표 셀에 얹힌 콤보는 마우스 휠을 삼켜 사용자가 화면을 내리려는 순간 엉뚱하게
    선택이 바뀐다(의도치 않은 값 변경). 휠 이벤트를 무시(``ignore``)하면 부모 스크롤
    영역(표 뷰포트)으로 전파돼 표가 스크롤되고, 선택은 오직 클릭으로만 바뀐다.
    """

    def wheelEvent(self, event):  # noqa: N802 (Qt 시그니처)
        event.ignore()

(
    _COL_CONFIRM, _COL_FIELD, _COL_SOURCE, _COL_TYPE, _COL_FORMAT, _COL_PREVIEW,
) = range(6)
_HEADERS = ("확정", "템플릿 필드", "데이터 항목", "타입 / 고정값", "표시형", "미리보기")
_NO_FORMAT_ITEM = "—"          # 표시형 변형이 없는 유형(고정값)
_CUSTOM_FORMAT_ITEM = "직접 입력…"  # 고급: 서식 코드 직접 입력(액션 항목)

# 색은 style 의 토큰 상수에서(단일 출처 gui/design_tokens.json) — 리터럴 중복 금지.
_BG_UNCONFIRMED = QBrush(QColor(UNCONFIRMED_BG))  # 미확정 = 노랑
_BG_UNMATCHED = QBrush(QColor(UNMATCHED_BG))      # 미매칭 미확정 = 빨강
_BG_DEFAULT = QBrush()

# 미리보기 전경색: 내용은 매핑됐으나 이 레코드에서 값이 빈 경우 빨강으로 고지.
_FG_DATA_EMPTY = QBrush(QColor(DATA_EMPTY_FG))
_FG_DEFAULT = QBrush()

_EMPTY_ITEM = "(비움)"

# 이 미만의 제안 점수는 툴팁으로 신뢰도를 고지한다(정확 일치 1.0 은 조용히).
_LOW_CONFIDENCE = 1.0


def _row_brush(row, schema_only: bool = False) -> QBrush:
    """행 상태 배경색 결정식(단일 출처) — 확정=기본, 미확정=노랑, 내용 없는 미확정=빨강.

    ``_sync_row`` 와 ``_on_arg_edited``(포커스 보존을 위한 부분 갱신)가 공유한다 —
    결정식이 두 곳에서 따로 진화하지 않게 한다(RC-28).

    ``schema_only`` (데이터 미연결 세션, UD-28): 내용 없는 미확정 행의 빨강 '미매칭'
    경보를 중립(기본)으로 강등한다 — 매칭할 데이터가 없으니 '못 맞춤'이 아니라 '아직
    연결 안 함'이라, 빨강은 오경보다('데이터 미연결'은 상단 배너가 설명). 이로써
    '데이터 미연결'(중립)과 '미매칭'(데이터 有 + 빨강)이 시각적으로 분리된다.
    """
    if row.confirmed:
        return _BG_DEFAULT
    if row.has_content():
        return _BG_UNCONFIRMED
    return _BG_DEFAULT if schema_only else _BG_UNMATCHED


def _row_state_color(row, schema_only: bool = False) -> "QColor | None":
    """행 상태 밴드 색(위젯 열 컨테이너용, UD-38) — ``_row_brush`` 와 같은 결정식.

    아이템 배경(QBrush)과 달리 위젯 셀 컨테이너는 팔레트 색으로 칠하므로 ``QColor``
    또는 ``None``(확정 = 밴드 없음)을 돌려준다. 상태색이 아이템 3열에만 닿고 cellWidget
    3열(데이터 항목·타입/고정값·표시형)에서 끊겨 미매칭 빨강이 좌우로 찢기던 것을,
    같은 색을 셀 컨테이너에도 칠해 **연속 밴드**로 잇는다. ``schema_only`` 강등은
    ``_row_brush`` 와 동형(데이터 미연결 세션의 빈 행 = 밴드 없음).
    """
    if row.confirmed:
        return None
    if row.has_content():
        return QColor(UNCONFIRMED_BG)
    return None if schema_only else QColor(UNMATCHED_BG)


def _source_label(key: str, aliases: "dict[str, str]") -> str:
    """영문 소스 키를 alias 한글 라벨과 병기(``opengDate — 개찰일자``)."""
    label = aliases.get(key)
    if label and label != key:
        return f"{key} — {label}"
    return key


class MappingTable(QWidget):
    """MappingModel 렌더/편집 위젯 — 테이블 + 모두 확정/해제 버튼."""

    completeChanged = Signal()  # 모델 변경(확정 상태 포함) 시마다 발신

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: "MappingModel | None" = None
        self._preview_record: dict = {}
        self._updating = False  # 프로그램적 갱신 중 itemChanged 재진입 방지

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_inferred_help = QLabel(
            "필드명 옆 ‘추정: …’은 템플릿 내용에서 얻은 초기 제안입니다. "
            "실제 채움 방식은 ‘타입 / 고정값’에서 확인하거나 바꿀 수 있습니다."
        )
        self.lbl_inferred_help.setWordWrap(True)
        mark(self.lbl_inferred_help, "muted", True)
        self.lbl_inferred_help.setVisible(False)
        layout.addWidget(self.lbl_inferred_help)

        # 데이터 미연결(스키마온리) 안내 배너(UD-28) — 데이터 스텝을 건너뛴 세션에서만
        # 노출. 빈 행이 중립색인 이유(매칭할 데이터가 없음)를 설명하고 다음 행동을
        # 제안해, 전면 빨강을 오류로 오인하던 문제를 해소한다. 평상시 숨김.
        self.lbl_schema_only = QLabel(
            "데이터 미연결 — 스키마만 편집 중입니다. 연결된 데이터가 없어 데이터 항목을 "
            "고를 수 없습니다(빈 행은 오류가 아닙니다). 고정값으로 채우거나 각 필드를 (비움)으로 "
            "확정하세요 — 실제 데이터는 실행할 때 연결합니다."
        )
        self.lbl_schema_only.setWordWrap(True)
        mark(self.lbl_schema_only, "muted", True)
        self.lbl_schema_only.setVisible(False)
        layout.addWidget(self.lbl_schema_only)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_CONFIRM, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_PREVIEW, QHeaderView.Stretch)
        self.table.setColumnWidth(_COL_FIELD, 170)
        self.table.setColumnWidth(_COL_SOURCE, 220)
        self.table.setColumnWidth(_COL_TYPE, 210)
        self.table.setColumnWidth(_COL_FORMAT, 80)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.btn_confirm_all = QPushButton("모두 확정")
        self.btn_confirm_all.clicked.connect(self._on_confirm_all)
        self.btn_unconfirm_all = QPushButton("모두 해제")
        self.btn_unconfirm_all.clicked.connect(self._on_unconfirm_all)
        buttons.addWidget(self.btn_confirm_all)
        buttons.addWidget(self.btn_unconfirm_all)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    # ---------------------------------------------------------------- 공개 API
    def set_model(self, model: MappingModel, preview_record: "dict | None" = None):
        """모델 교체 후 전체 재렌더. preview_record 는 미리보기 기준 레코드."""
        self._model = model
        self._preview_record = dict(preview_record or {})
        self._rebuild()

    def refresh(self):
        """모델이 밖에서 바뀐 뒤(프로파일 로드 등) 전체 행 시각 동기화."""
        if self._model is None:
            return
        for ri in range(len(self._model.rows)):
            self._sync_row(ri)

    def set_preview_record(self, record: "dict | None"):
        """미리보기 기준 레코드를 교체한다(스텝퍼가 호출). 미리보기 열만 갱신 —
        콤보·포커스는 건드리지 않아 편집 중에도 안전하다."""
        self._preview_record = dict(record or {})
        self._refresh_previews()

    def _refresh_previews(self):
        """미리보기 열(_COL_PREVIEW)만 현재 기준 레코드로 다시 계산.

        내용이 매핑됐는데 이 레코드에서 값이 비면 '(이 레코드에서 빈 값)' 을 빨강으로
        표시(의도적 비움과 구분). 그 외는 값 그대로.
        """
        model = self._model
        if model is None:
            return
        self._updating = True
        try:
            for ri, row in enumerate(model.rows):
                self._render_preview(ri, row)
        finally:
            self._updating = False

    def _render_preview(self, ri: int, row):
        """한 행의 미리보기 셀을 현재 기준 레코드로 렌더(호출자가 _updating 관리)."""
        item = self.table.item(ri, _COL_PREVIEW)
        if item is None:
            return
        try:
            value = row.to_mapping().value_for(self._preview_record)
        except ValueError as exc:
            # RC-10 2차 방어: 미지 타입은 apply_transform 이 시끄럽게 raise 한다 —
            # 뷰가 통째로 죽는 대신 해당 행에 오류를 빨갛게 재진술한다(조용한 오표시 금지).
            item.setText(f"(미리보기 오류: {exc})")
            item.setForeground(_FG_DATA_EMPTY)
            return
        if value == "" and row.has_content():
            item.setText("(이 레코드에서 빈 값)")
            item.setForeground(_FG_DATA_EMPTY)
        else:
            item.setText(value)
            item.setForeground(_FG_DEFAULT)

    def _schema_only(self) -> bool:
        """현재 모델이 데이터 미연결(스키마온리) 세션인가(UD-28) — 행 색 강등의 근거."""
        return self._model is not None and self._model.is_schema_only()

    # ----------------------------------------------------------------- 렌더링
    def _rebuild(self):
        model = self._model
        # 데이터 미연결 세션에서만 스키마온리 안내 배너 노출(UD-28).
        self.lbl_schema_only.setVisible(self._schema_only())
        self.lbl_inferred_help.setVisible(
            model is not None and any(row.spec is not None for row in model.rows)
        )
        self._updating = True
        try:
            self.table.setRowCount(0)
            if model is None:
                return
            self.table.setRowCount(len(model.rows))
            for ri, row in enumerate(model.rows):
                # 확정 체크(체크 가능한 아이템).
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                self.table.setItem(ri, _COL_CONFIRM, chk)

                # 템플릿 필드(이름 + **추정** 타입, 전체 이름 상시 툴팁 + context 병기).
                # 긴 필드명은 좁은 열에서 말줄임돼 유사 접두 필드끼리 오인 확정될 수
                # 있다(RC-36) — 툴팁이 전체 이름을 항상 보여준다.
                spec = row.spec
                if spec is not None:
                    inferred = INFERRED_TYPE_LABELS.get(spec.inferred_type, spec.inferred_type)
                    field_text = f"{row.template_field}  [추정: {inferred}]"
                else:
                    field_text = row.template_field
                fld = QTableWidgetItem(field_text)
                fld.setFlags(Qt.ItemIsEnabled)
                tip = f"필드: {row.template_field}"
                if spec is not None:
                    tip += f"\n추정 타입: {inferred} — 템플릿 내용에서 얻은 초기 제안"
                if spec and spec.context:
                    tip += f"\n문맥: {spec.context}"
                fld.setToolTip(tip)
                self.table.setItem(ri, _COL_FIELD, fld)

                # 데이터 항목 콤보(단일선택) + 퍼지(저신뢰) 제안 인라인 신호(UD-15).
                # 상태색 밴드가 닿도록 셀 컨테이너로 감싼다(UD-38). 휠은 표 스크롤로
                # (선택은 클릭만).
                combo = _NoScrollComboBox()
                combo.activated.connect(
                    lambda idx, ri=ri: self._on_source_activated(ri, idx)
                )
                conf = QLabel("")
                mark(conf, "level", "warn")  # 퍼지 제안 = 주황 주의(정확 일치는 무표시)
                conf.setVisible(False)
                src_box = self._wrap_cell(combo, extra=conf)
                src_box._conf = conf
                self.table.setCellWidget(ri, _COL_SOURCE, src_box)

                # 타입 콤보(한국어 라벨) + 조건부 고정값 입력. 입력은 별도 상시 열이 아니라
                # '고정값' 선택 시 콤보 바로 옆에 나타나 정보량과 발견성을 함께 지킨다.
                tc = _NoScrollComboBox()
                for kind in TYPES:
                    tc.addItem(TYPE_LABELS.get(kind, kind), kind)
                tc.activated.connect(
                    lambda idx, ri=ri: self._on_type_activated(ri, idx)
                )
                arg = QLineEdit()
                arg.setPlaceholderText("고정값 입력")
                arg.textEdited.connect(lambda text, ri=ri: self._on_arg_edited(ri, text))
                type_box = self._wrap_cell(tc, extra=arg)
                type_box._arg = arg
                self.table.setCellWidget(ri, _COL_TYPE, type_box)

                # 표시형 콤보(타입에 딸린 프리셋; 변형 없는 타입이면 비활성). 휠은 표 스크롤로.
                fmtc = _NoScrollComboBox()
                fmtc.activated.connect(
                    lambda idx, ri=ri: self._on_format_activated(ri, idx)
                )
                self.table.setCellWidget(ri, _COL_FORMAT, self._wrap_cell(fmtc))

                # 미리보기(읽기 전용).
                pv = QTableWidgetItem()
                pv.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(ri, _COL_PREVIEW, pv)
        finally:
            self._updating = False
        for ri in range(len(model.rows)):
            self._sync_row(ri)

    # ------------------------------------------------------- 셀 컨테이너(UD-38)
    def _wrap_cell(self, control, *, extra=None) -> QWidget:
        """cellWidget 을 상태색 밴드가 닿는 컨테이너로 감싼다(UD-38).

        컨테이너에 여백을 둬 행 상태색이 컨트롤 둘레로 이어져 아이템 열의 밴드와
        연속된다. 실제 컨트롤은 ``_control`` 로 보관해 :meth:`cell_control` 이 되찾는다.
        """
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(4)
        lay.addWidget(control, 1)
        if extra is not None:
            lay.addWidget(extra)
        box._control = control
        return box

    def cell_control(self, ri: int, col: int):
        """셀 위젯 컨테이너 안의 실제 컨트롤(콤보/라인에디트)을 돌려준다(UD-38 래핑)."""
        w = self.table.cellWidget(ri, col)
        return getattr(w, "_control", w)

    def fixed_value_control(self, ri: int) -> QLineEdit:
        """타입 셀 안 조건부 고정값 입력(test seam)."""
        return self.table.cellWidget(ri, _COL_TYPE)._arg

    def _apply_band(self, ri: int, color: "QColor | None") -> None:
        """위젯 열 컨테이너를 행 상태색으로 칠해 아이템 열 밴드와 연속화(UD-38)."""
        for col in (_COL_SOURCE, _COL_TYPE, _COL_FORMAT):
            box = self.table.cellWidget(ri, col)
            if box is None:
                continue
            if color is None:
                box.setAutoFillBackground(False)
            else:
                box.setAutoFillBackground(True)
                pal = box.palette()
                pal.setColor(QPalette.Window, color)
                box.setPalette(pal)

    def _sync_row(self, ri: int):
        """행 위젯/아이템을 모델 상태로 동기화(색·미리보기·활성 포함)."""
        model = self._model
        row = model.rows[ri]
        self._updating = True
        try:
            # 확정 체크 상태.
            self.table.item(ri, _COL_CONFIRM).setCheckState(
                Qt.Checked if row.confirmed else Qt.Unchecked
            )

            # 데이터 항목 콤보 재구성(단일선택): (비움) + 각 소스.
            combo: QComboBox = self.cell_control(ri, _COL_SOURCE)
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(_EMPTY_ITEM)
            for key in model.source_fields:
                combo.addItem(_source_label(key, model.aliases))
            if row.source and row.source in model.source_fields:
                combo.setCurrentIndex(1 + model.source_fields.index(row.source))
            elif row.source:
                # 프로파일이 기억한 소스가 현 샘플 데이터에 없음 — (비움) 오표시 대신
                # 실제 이름을 보여 상태를 숨기지 않는다(실행 사전검증이 잡기 전에 에디터가 고지).
                combo.addItem(
                    _source_label(row.source, model.aliases) + " (데이터에 없음)"
                )
                combo.setCurrentIndex(combo.count() - 1)
            else:
                combo.setCurrentIndex(0)
            # 현재 선택 전체 문자열 상시 툴팁(RC-36) — 콤보 고정폭(220px)에서 잘린
            # 선택을 확인할 수단. 저신뢰 자동 제안 경고는 병기 유지.
            tip = f"현재 선택: {combo.currentText()}"
            if 0.0 < row.suggestion_score < _LOW_CONFIDENCE:
                tip += (
                    f"\n자동 제안 신뢰도 {row.suggestion_score:.0%} — "
                    "초안입니다. 확인 후 확정하세요."
                )
            combo.setToolTip(tip)
            combo.blockSignals(False)

            # 퍼지(모호) 제안의 상시 인라인 신호(UD-15) — 정확 일치(1.0)·무제안(0.0)은
            # 무표시, 그 사이만 신뢰도 배지. 툴팁에만 있던 2등급 분류를 시각 채널로.
            src_box = self.table.cellWidget(ri, _COL_SOURCE)
            conf = getattr(src_box, "_conf", None)
            if conf is not None:
                if 0.0 < row.suggestion_score < _LOW_CONFIDENCE:
                    conf.setText(f"제안 {row.suggestion_score:.0%}")
                    conf.setVisible(True)
                else:
                    conf.setText("")
                    conf.setVisible(False)

            # 타입 콤보.
            tc: QComboBox = self.cell_control(ri, _COL_TYPE)
            tc.blockSignals(True)
            # 이전 동기화가 남긴 '지원 안 함' 마커를 걷어내고 표준 항목만 남긴다.
            while tc.count() > len(TYPES):
                tc.removeItem(tc.count() - 1)
            if row.type in TYPES:
                tc.setCurrentIndex(TYPES.index(row.type))
            else:
                # RC-10 2차 방어: 직렬화 경계(from_dict)가 1차로 거부하지만, 프로그램
                # 경로로 미지 타입이 스며도 미처리 크래시(Qt 가 예외를 삼켜 통지 0)나
                # 조용한 오표시 대신 실제 값을 그대로 노출한다 — 사람이 고치게.
                tc.addItem(f"{row.type} (지원 안 함)", row.type)
                tc.setCurrentIndex(tc.count() - 1)
            tc.blockSignals(False)

            # 표시형 콤보 — 프리셋(라벨→코드) + 커스텀 코드 + '직접 입력…' 액션.
            fmtc: QComboBox = self.cell_control(ri, _COL_FORMAT)
            fmtc.blockSignals(True)
            fmtc.clear()
            opts = format_presets(row.type)  # [(라벨, 코드)]
            if opts:
                codes = [code for _, code in opts]
                for label, code in opts:
                    fmtc.addItem(label, code)
                # 프리셋에 없는 커스텀 코드면 별도 항목으로 노출(코드 그대로 보여줌).
                if row.fmt and row.fmt not in codes:
                    fmtc.addItem(f"직접: {row.fmt}", row.fmt)
                fmtc.addItem(_CUSTOM_FORMAT_ITEM, None)  # 액션(코드 데이터 None)
                sel = next((i for i in range(fmtc.count())
                            if fmtc.itemData(i) == row.fmt), 0)
                fmtc.setCurrentIndex(sel)
                fmtc.setEnabled(True)
            else:
                fmtc.addItem(_NO_FORMAT_ITEM, "")
                fmtc.setEnabled(False)
            fmtc.blockSignals(False)

            # 고정값 입력 — const 면 콤보 바로 옆에 노출, 그 외에는 셀에서 완전히 숨긴다.
            arg = self.fixed_value_control(ri)
            arg.blockSignals(True)
            if row.type == "const":
                arg.setEnabled(True)
                arg.setVisible(True)
                arg.setText(row.const)
            else:
                arg.setEnabled(False)
                arg.setVisible(False)
                arg.setText("")
            arg.blockSignals(False)

            # 미리보기(현재 기준 레코드).
            self._render_preview(ri, row)

            # 행 상태 색(결정식은 _row_brush 단일 출처) — 아이템 3열 + 위젯 4열 컨테이너
            # 를 함께 칠해 상태색 밴드를 행 전폭으로 연속화(UD-38). 데이터 미연결
            # 세션이면 빈 행 빨강을 중립으로 강등(UD-28).
            so = self._schema_only()
            brush = _row_brush(row, so)
            for col in (_COL_CONFIRM, _COL_FIELD, _COL_PREVIEW):
                self.table.item(ri, col).setBackground(brush)
            self._apply_band(ri, _row_state_color(row, so))
        finally:
            self._updating = False

    # --------------------------------------------------------------- 핸들러
    def _on_item_changed(self, item: QTableWidgetItem):
        if self._updating or item.column() != _COL_CONFIRM:
            return
        ri = item.row()
        self._model.set_confirmed(ri, item.checkState() == Qt.Checked)
        self._sync_row(ri)
        self.completeChanged.emit()

    def _on_source_activated(self, ri: int, idx: int):
        model = self._model
        n = len(model.source_fields)
        if idx == 0:
            model.set_source(ri, "")
        elif 1 <= idx <= n:
            model.set_source(ri, model.source_fields[idx - 1])
        else:
            # '(데이터에 없음)' 잔존 표시 아이템 재선택 — 변경 없음.
            self._sync_row(ri)
            return
        self._sync_row(ri)
        self.completeChanged.emit()

    def _on_type_activated(self, ri: int, idx: int):
        if idx >= len(TYPES):
            # '지원 안 함' 마커 항목(RC-10 2차 방어) 재선택 — 변경 없음, 표시만 재동기화.
            self._sync_row(ri)
            return
        self._model.set_type(ri, TYPES[idx])
        self._sync_row(ri)
        self.completeChanged.emit()

    def _on_format_activated(self, ri: int, idx: int):
        combo: QComboBox = self.cell_control(ri, _COL_FORMAT)
        if combo.itemText(idx) == _CUSTOM_FORMAT_ITEM:
            self._prompt_custom_format(ri)
            return
        code = combo.itemData(idx)
        if code is None:  # 비활성('—') 항목
            self._sync_row(ri)
            return
        self._model.set_fmt(ri, code)
        self._sync_row(ri)
        self.completeChanged.emit()

    def _prompt_custom_format(self, ri: int):
        """고급: 서식 코드 직접 입력. WYSIWYG 미리보기가 결과를 즉시 보여준다."""
        row = self._model.rows[ri]
        hint = ("금액 예: {:,}원 · {:,.2f}   ·   날짜 예: %Y-%m-%d · %Y년 %m월 %d일")
        code, ok = QInputDialog.getText(
            self, "표시형 코드 직접 입력", f"서식 코드\n({hint}):", text=row.fmt
        )
        if ok:
            self._model.set_fmt(ri, code)
            self.completeChanged.emit()
        self._sync_row(ri)

    def _on_arg_edited(self, ri: int, text: str):
        row = self._model.rows[ri]
        if row.type != "const":
            return
        self._model.set_const(ri, text)
        # 입력 중 포커스 유지를 위해 라인에디트 자체는 다시 만지지 않는다.
        self._updating = True
        try:
            self.table.item(ri, _COL_CONFIRM).setCheckState(Qt.Unchecked)
            self._render_preview(ri, row)
            so = self._schema_only()
            brush = _row_brush(row, so)  # set_const 가 확정을 해제한 뒤라 미확정 색
            for col in (_COL_CONFIRM, _COL_FIELD, _COL_PREVIEW):
                self.table.item(ri, col).setBackground(brush)
            self._apply_band(ri, _row_state_color(row, so))  # 위젯 열 밴드도 함께(UD-38)
        finally:
            self._updating = False
        self.completeChanged.emit()

    def _on_confirm_all(self):
        """'모두 확정' — 내용 있는 행만 즉시 확정하고, 미매칭 빈 행의 **의도적 비움
        승격**은 이름 재진술 확인(ADR-E)을 거친다(UD-05: 무경고 대량 우회 방지)."""
        model = self._model
        if model is None:
            return
        model.confirm_content_rows()  # ADR-D 고신뢰 일괄 수락(내용 행만)
        blanks = model.unconfirmed_blank_fields()
        if blanks:
            # 값이 주입되지 않을 필드를 구체 이름으로 재진술 — 기본 버튼은 '취소'.
            names = ", ".join(blanks)
            if confirm_destructive(
                self, "비움 확정 확인",
                f"다음 {len(blanks)}개 필드는 채울 데이터 항목이 없습니다:\n\n{names}\n\n"
                "이 필드들을 비우고 확정(의도적 비움)하는 것이 맞습니까? "
                "확정하면 미매칭 경고가 사라지고 다음으로 진행할 수 있습니다.",
                "비우고 확정",
            ):
                model.confirm_fields(blanks)
        self.refresh()
        self.completeChanged.emit()

    def _on_unconfirm_all(self):
        """'모두 해제' — 확정한 작업이 있으면 파괴 확인을 거친다(UD-05: 무확인 파기 방지)."""
        model = self._model
        if model is None:
            return
        n = model.confirmed_count()
        if n > 0 and not confirm_destructive(
            self, "모두 해제 확인",
            f"확정한 {n}개 행의 확정을 모두 해제합니다.\n"
            "해제하면 각 행을 다시 검토·확정해야 다음으로 진행할 수 있습니다.",
            "모두 해제",
        ):
            return
        model.unconfirm_all()
        self.refresh()
        self.completeChanged.emit()
