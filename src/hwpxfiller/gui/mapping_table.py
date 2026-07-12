"""매핑 테이블 뷰 — MappingModel 을 QTableWidget 으로 렌더/편집한다.

열: [확정 | 템플릿 필드 | 소스 | 변환 | 구분자·상수 | 미리보기].
행 색: 미확정=노랑, 소스 없는 미확정(미매칭)=빨강, 확정=기본.
모든 편집은 MappingModel 편집 API 를 거치고(편집 → 확정 해제 규칙 포함),
변경 시 ``completeChanged`` 시그널을 쏜다(위저드 isComplete 연동용).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.format_engine import presets as format_presets
from ..core.mapping import TRANSFORMS
from .mapping_state import MappingModel
from .style import DATA_EMPTY_FG, UNCONFIRMED_BG, UNMATCHED_BG

# 변환 코드 → 한국어 라벨(콤보 표시 순서는 TRANSFORMS 그대로).
TRANSFORM_LABELS = {"join": "그대로", "datetime": "일시", "amount": "금액", "const": "상수"}

(
    _COL_CONFIRM, _COL_FIELD, _COL_SOURCE, _COL_TRANSFORM, _COL_FORMAT, _COL_ARG,
    _COL_PREVIEW,
) = range(7)
_HEADERS = ("확정", "템플릿 필드", "데이터 항목", "변환", "표시형", "구분자·상수", "미리보기")
_NO_FORMAT_ITEM = "—"          # 표시형 변형이 없는 변환(그대로/상수)
_CUSTOM_FORMAT_ITEM = "직접 입력…"  # 고급: 서식 코드 직접 입력(액션 항목)

# 색은 style 의 토큰 상수에서(단일 출처 gui/design_tokens.json) — 리터럴 중복 금지.
_BG_UNCONFIRMED = QBrush(QColor(UNCONFIRMED_BG))  # 미확정 = 노랑
_BG_UNMATCHED = QBrush(QColor(UNMATCHED_BG))      # 미매칭 미확정 = 빨강
_BG_DEFAULT = QBrush()

# 미리보기 전경색: 내용은 매핑됐으나 이 레코드에서 값이 빈 경우 빨강으로 고지.
_FG_DATA_EMPTY = QBrush(QColor(DATA_EMPTY_FG))
_FG_DEFAULT = QBrush()

_EMPTY_ITEM = "(비움)"
_MULTI_ITEM = "여러 데이터 항목 선택…"

# 이 미만의 제안 점수는 툴팁으로 신뢰도를 고지한다(정확 일치 1.0 은 조용히).
_LOW_CONFIDENCE = 1.0


def _row_brush(row) -> QBrush:
    """행 상태 배경색 결정식(단일 출처) — 확정=기본, 미확정=노랑, 내용 없는 미확정=빨강.

    ``_sync_row`` 와 ``_on_arg_edited``(포커스 보존을 위한 부분 갱신)가 공유한다 —
    결정식이 두 곳에서 따로 진화하지 않게 한다(RC-28).
    """
    if row.confirmed:
        return _BG_DEFAULT
    return _BG_UNCONFIRMED if row.has_content() else _BG_UNMATCHED


def _source_label(key: str, aliases: "dict[str, str]") -> str:
    """영문 소스 키를 alias 한글 라벨과 병기(``opengDate — 개찰일자``)."""
    label = aliases.get(key)
    if label and label != key:
        return f"{key} — {label}"
    return key


def _sources_display(sources: "list[str]", aliases: "dict[str, str]") -> str:
    """현재 데이터 항목 선택의 표시 문자열 — 여러 항목은 ``opengDate + opengTm`` 식으로."""
    if not sources:
        return _EMPTY_ITEM
    if len(sources) == 1:
        return _source_label(sources[0], aliases)
    return " + ".join(sources)


class _SourcePickerDialog(QDialog):
    """다중 데이터 항목 선택 다이얼로그(체크 리스트).

    선택 순서는 리스트(소스 필드) 순서를 따른다 — 나라장터 키는 날짜가 시각보다
    앞에 오므로 datetime 합성의 기대 순서(날짜, 시각)와 일치한다.
    """

    def __init__(self, source_fields, aliases, selected, parent=None):
        super().__init__(parent)
        self.setWindowTitle("여러 데이터 항목 선택")
        self.resize(360, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("이 템플릿 필드에 함께 사용할 데이터 항목을 순서대로 체크하세요."))
        self.list = QListWidget()
        chosen = set(selected)
        for key in source_fields:
            item = QListWidgetItem(_source_label(key, aliases))
            item.setData(Qt.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if key in chosen else Qt.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_sources(self) -> "list[str]":
        out: "list[str]" = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out


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
        self.table.setColumnWidth(_COL_TRANSFORM, 90)
        self.table.setColumnWidth(_COL_FORMAT, 80)
        self.table.setColumnWidth(_COL_ARG, 110)
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
            # RC-10 2차 방어: 미지 변환은 apply_transform 이 시끄럽게 raise 한다 —
            # 뷰가 통째로 죽는 대신 해당 행에 오류를 빨갛게 재진술한다.
            item.setText(f"(변환 오류: {exc})")
            item.setForeground(_FG_DATA_EMPTY)
            return
        if value == "" and row.has_content():
            item.setText("(이 레코드에서 빈 값)")
            item.setForeground(_FG_DATA_EMPTY)
        else:
            item.setText(value)
            item.setForeground(_FG_DEFAULT)

    # ----------------------------------------------------------------- 렌더링
    def _rebuild(self):
        model = self._model
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

                # 템플릿 필드(이름 + 타입 배지, 전체 이름 상시 툴팁 + context 병기).
                # 긴 필드명은 좁은 열에서 말줄임돼 유사 접두 필드끼리 오인 확정될 수
                # 있다(RC-36) — 툴팁이 전체 이름을 항상 보여준다.
                spec = row.spec
                type_badge = spec.inferred_type if spec else "text"
                fld = QTableWidgetItem(f"{row.template_field}  [{type_badge}]")
                fld.setFlags(Qt.ItemIsEnabled)
                tip = f"필드: {row.template_field}"
                if spec and spec.context:
                    tip += f"\n문맥: {spec.context}"
                fld.setToolTip(tip)
                self.table.setItem(ri, _COL_FIELD, fld)

                # 소스 콤보.
                combo = QComboBox()
                combo.activated.connect(
                    lambda idx, ri=ri: self._on_source_activated(ri, idx)
                )
                self.table.setCellWidget(ri, _COL_SOURCE, combo)

                # 변환 콤보(한국어 라벨).
                tr = QComboBox()
                for kind in TRANSFORMS:
                    tr.addItem(TRANSFORM_LABELS.get(kind, kind), kind)
                tr.activated.connect(
                    lambda idx, ri=ri: self._on_transform_activated(ri, idx)
                )
                self.table.setCellWidget(ri, _COL_TRANSFORM, tr)

                # 표시형 콤보(변환에 딸린 프리셋; 변형 없는 변환이면 비활성).
                fmtc = QComboBox()
                fmtc.activated.connect(
                    lambda idx, ri=ri: self._on_format_activated(ri, idx)
                )
                self.table.setCellWidget(ri, _COL_FORMAT, fmtc)

                # 구분자·상수(변환 종류에 따라 의미·활성이 바뀜).
                arg = QLineEdit()
                arg.textEdited.connect(lambda text, ri=ri: self._on_arg_edited(ri, text))
                self.table.setCellWidget(ri, _COL_ARG, arg)

                # 미리보기(읽기 전용).
                pv = QTableWidgetItem()
                pv.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(ri, _COL_PREVIEW, pv)
        finally:
            self._updating = False
        for ri in range(len(model.rows)):
            self._sync_row(ri)

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

            # 소스 콤보 재구성: (비움) + 각 소스 + [현재 다중 표시] + 다중 선택….
            combo: QComboBox = self.table.cellWidget(ri, _COL_SOURCE)
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(_EMPTY_ITEM)
            for key in model.source_fields:
                combo.addItem(_source_label(key, model.aliases))
            if len(row.sources) > 1:
                combo.addItem(_sources_display(row.sources, model.aliases))
                combo.setCurrentIndex(combo.count() - 1)
            elif len(row.sources) == 1 and row.sources[0] in model.source_fields:
                combo.setCurrentIndex(1 + model.source_fields.index(row.sources[0]))
            elif len(row.sources) == 1:
                # 프로파일이 기억한 소스가 현 샘플 데이터에 없음 — (비움) 오표시 대신
                # 실제 이름을 보여 상태를 숨기지 않는다(실행 사전검증이 잡기 전에 에디터가 고지).
                combo.addItem(
                    _source_label(row.sources[0], model.aliases) + " (데이터에 없음)"
                )
                combo.setCurrentIndex(combo.count() - 1)
            else:
                combo.setCurrentIndex(0)
            combo.addItem(_MULTI_ITEM)
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

            # 변환 콤보.
            tr: QComboBox = self.table.cellWidget(ri, _COL_TRANSFORM)
            tr.blockSignals(True)
            # 이전 동기화가 남긴 '지원 안 함' 마커를 걷어내고 표준 항목만 남긴다.
            while tr.count() > len(TRANSFORMS):
                tr.removeItem(tr.count() - 1)
            if row.transform in TRANSFORMS:
                tr.setCurrentIndex(TRANSFORMS.index(row.transform))
            else:
                # RC-10 2차 방어: 직렬화 경계(from_dict)가 1차로 거부하지만, 프로그램
                # 경로로 미지 변환이 스며도 미처리 크래시(Qt 가 예외를 삼켜 통지 0)나
                # 조용한 오표시 대신 실제 값을 그대로 노출한다 — 사람이 고치게.
                tr.addItem(f"{row.transform} (지원 안 함)", row.transform)
                tr.setCurrentIndex(tr.count() - 1)
            tr.blockSignals(False)

            # 표시형 콤보 — 프리셋(라벨→코드) + 커스텀 코드 + '직접 입력…' 액션.
            fmtc: QComboBox = self.table.cellWidget(ri, _COL_FORMAT)
            fmtc.blockSignals(True)
            fmtc.clear()
            opts = format_presets(row.transform)  # [(라벨, 코드)]
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

            # 구분자·상수 — join 이면 구분자, const 면 상수, 그 외 비활성.
            arg: QLineEdit = self.table.cellWidget(ri, _COL_ARG)
            arg.blockSignals(True)
            if row.transform == "join":
                arg.setEnabled(True)
                arg.setPlaceholderText("구분자")
                arg.setText(row.sep)
            elif row.transform == "const":
                arg.setEnabled(True)
                arg.setPlaceholderText("상수 값")
                arg.setText(row.const)
            else:
                arg.setEnabled(False)
                arg.setPlaceholderText("")
                arg.setText("")
            arg.blockSignals(False)

            # 미리보기(현재 기준 레코드).
            self._render_preview(ri, row)

            # 행 상태 색(결정식은 _row_brush 단일 출처).
            brush = _row_brush(row)
            for col in (_COL_CONFIRM, _COL_FIELD, _COL_PREVIEW):
                self.table.item(ri, col).setBackground(brush)
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
        combo: QComboBox = self.table.cellWidget(ri, _COL_SOURCE)
        n = len(model.source_fields)
        if combo.itemText(idx) == _MULTI_ITEM:
            dlg = _SourcePickerDialog(
                model.source_fields, model.aliases, model.rows[ri].sources, self
            )
            if dlg.exec() == QDialog.Accepted:
                model.set_sources(ri, dlg.selected_sources())
        elif idx == 0:
            model.set_sources(ri, [])
        elif 1 <= idx <= n:
            model.set_sources(ri, [model.source_fields[idx - 1]])
        else:
            # 현재 다중 선택 표시 아이템 재선택 — 변경 없음.
            self._sync_row(ri)
            return
        self._sync_row(ri)
        self.completeChanged.emit()

    def _on_transform_activated(self, ri: int, idx: int):
        if idx >= len(TRANSFORMS):
            # '지원 안 함' 마커 항목(RC-10 2차 방어) 재선택 — 변경 없음, 표시만 재동기화.
            self._sync_row(ri)
            return
        self._model.set_transform(ri, TRANSFORMS[idx])
        self._sync_row(ri)
        self.completeChanged.emit()

    def _on_format_activated(self, ri: int, idx: int):
        combo: QComboBox = self.table.cellWidget(ri, _COL_FORMAT)
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
        if row.transform == "join":
            self._model.set_sep(ri, text)
        elif row.transform == "const":
            self._model.set_const(ri, text)
        else:
            return
        # 입력 중 포커스 유지를 위해 라인에디트 자체는 다시 만지지 않는다.
        self._updating = True
        try:
            self.table.item(ri, _COL_CONFIRM).setCheckState(Qt.Unchecked)
            self._render_preview(ri, row)
            brush = _row_brush(row)  # set_sep/set_const 가 확정을 해제한 뒤라 미확정 색
            for col in (_COL_CONFIRM, _COL_FIELD, _COL_PREVIEW):
                self.table.item(ri, col).setBackground(brush)
        finally:
            self._updating = False
        self.completeChanged.emit()

    def _on_confirm_all(self):
        if self._model is None:
            return
        self._model.confirm_all()
        self.refresh()
        self.completeChanged.emit()

    def _on_unconfirm_all(self):
        if self._model is None:
            return
        self._model.unconfirm_all()
        self.refresh()
        self.completeChanged.emit()
