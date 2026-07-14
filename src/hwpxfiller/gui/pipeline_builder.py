"""파이프라인 빌더 대화상자 — 조립 파이프라인 저작·미리보기(얇은 렌더러).

레이어링: 저작 로직·미리보기·저장은 전부 :class:`~hwpxfiller.gui.pipeline_builder_state.
PipelineBuilderViewModel`(Qt 비의존, 링1)이 소유. 이 위젯은 소스/스텝 리스트를 렌더하고
버튼을 배선할 뿐이다(dataset_pool_panel 분리 미러).

- **미리보기 = 실행 경로**(divergence 0): 표가 보여주는 것이 저장 후 실행이 복원하는
  그 파이프라인이다(뷰모델 build_source 단일 경로).
- **merge 제안은 게이트**: [키 제안] 은 공유 컬럼을 콤보에 채울 뿐 — 스텝 추가는 사용자의
  [스텝 추가] 클릭(명시 확정)으로만 일어난다(ADR D, 추측 조인 자동실행 금지).
- **조립 실패는 시끄럽게**: 미리보기 오류를 경고 라벨로 표면화(빈 표로 조용히 두지 않음).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from .confirm import confirm_destructive
from .pipeline_builder_state import PipelineBuilderViewModel
from .style import BASE_QSS, mark
from .view_helpers import restate_preview_item

_HOW_LABELS = [
    ("일치하는 행만 남김", "inner"),
    ("기준 데이터의 모든 행 유지", "left"),
]
_HOW_TEXT = {code: label for label, code in _HOW_LABELS}
_KIND_TEXT = {"excel": "엑셀/CSV", "nara": "나라장터"}


def _friendly_error(message: object) -> str:
    """링1의 안정된 내부 용어는 보존하고 사용자에게 보일 때만 쉬운 말로 바꾼다."""
    text = str(message)
    for old, new in (
        ("조인 키", "같은 행을 찾을 기준 항목"),
        ("append", "행 추가"),
        ("merge", "열 결합"),
        ("inner", "일치하는 행만 남김"),
        ("left", "기준 데이터의 모든 행 유지"),
        ("소스", "데이터"),
    ):
        text = text.replace(old, new)
    return text


class PipelineBuilderDialog(QDialog):
    """조립 파이프라인 저작 대화상자. :class:`PipelineBuilderViewModel` 을 렌더한다."""

    def __init__(
        self,
        registry,
        parent=None,
        *,
        store=None,
        fetcher=None,
        on_register_excel=None,
        on_register_nara=None,
    ):
        super().__init__(parent)
        self.vm = PipelineBuilderViewModel(
            registry, secret_store=store, fetcher=fetcher
        )
        self.saved_name: "str | None" = None  # 수용 시 저장된 항목 이름(패널이 읽음)
        self._register_excel_callback = on_register_excel
        self._register_nara_callback = on_register_nara
        # 미리보기가 한 번이라도 표시된 뒤에만 스테일 무효화 경고를 낸다(취득 전에는
        # 무효화할 스냅샷이 없다 — nara_view._on_query_edited 의 last_result 가드 미러).
        self._preview_shown = False

        self.setWindowTitle("데이터 조립")
        self.resize(760, 640)
        self.setStyleSheet(BASE_QSS)
        root = QVBoxLayout(self)

        # ------------------------------------------------------------ 소스
        src_head = QHBoxLayout()
        lbl = QLabel("등록 데이터 (첫 데이터가 기준)")
        mark(lbl, "heading", True)
        src_head.addWidget(lbl)
        src_head.addStretch(1)
        self.cmb_pool = QComboBox()
        src_head.addWidget(self.cmb_pool, 1)
        self.btn_add_source = QPushButton("조립에 추가")
        self.btn_add_source.clicked.connect(self._on_add_source)
        src_head.addWidget(self.btn_add_source)
        self.btn_del_source = QPushButton("조립에서 제거")
        self.btn_del_source.clicked.connect(self._on_remove_source)
        src_head.addWidget(self.btn_del_source)
        root.addLayout(src_head)
        register_row = QHBoxLayout()
        register_row.addStretch(1)
        register_row.addWidget(QLabel("필요한 데이터가 목록에 없나요?"))
        self.btn_register_excel = QPushButton("엑셀/CSV 새로 등록…")
        self.btn_register_excel.setEnabled(callable(self._register_excel_callback))
        self.btn_register_excel.clicked.connect(
            lambda _checked=False: self._on_register_source(self._register_excel_callback)
        )
        register_row.addWidget(self.btn_register_excel)
        self.btn_register_nara = QPushButton("나라장터 새로 등록…")
        self.btn_register_nara.setEnabled(callable(self._register_nara_callback))
        self.btn_register_nara.clicked.connect(
            lambda _checked=False: self._on_register_source(self._register_nara_callback)
        )
        register_row.addWidget(self.btn_register_nara)
        root.addLayout(register_row)
        self.lst_sources = QListWidget()
        self.lst_sources.setMaximumHeight(90)
        root.addWidget(self.lst_sources)

        # ------------------------------------------------------------ 스텝
        step_head = QHBoxLayout()
        lbl2 = QLabel("결합 방법")
        mark(lbl2, "heading", True)
        step_head.addWidget(lbl2)
        step_head.addStretch(1)
        self.cmb_op = QComboBox()
        self.cmb_op.addItem("같은 값끼리 열 결합", "merge")
        self.cmb_op.addItem("아래에 행 추가", "append")
        self.cmb_op.currentIndexChanged.connect(self._on_op_changed)
        step_head.addWidget(self.cmb_op)
        self.cmb_target = QComboBox()  # 스텝 대상 소스(인덱스)
        # 대상이 바뀌면 이전 대상 기준의 제안 후보는 무효 — 잔존 키로 오조인 방지.
        self.cmb_target.currentIndexChanged.connect(lambda _i: self.cmb_key.clear())
        step_head.addWidget(QLabel("대상 데이터"))
        step_head.addWidget(self.cmb_target, 1)
        root.addLayout(step_head)

        merge_row = QHBoxLayout()
        self.cmb_key = QComboBox()
        self.cmb_key.setEditable(True)  # 제안 밖 키도 명시 입력 가능
        merge_row.addWidget(QLabel("같은 행을 찾을 항목:"))
        merge_row.addWidget(self.cmb_key, 1)
        self.btn_suggest = QPushButton("항목 제안")
        self.btn_suggest.setToolTip(
            "두 데이터에 공통으로 있는 항목을 후보로 보여 줍니다. 결합 방법은 추가하지 않습니다."
        )
        self.btn_suggest.clicked.connect(self._on_suggest)
        merge_row.addWidget(self.btn_suggest)
        self.cmb_how = QComboBox()
        for label, code in _HOW_LABELS:
            self.cmb_how.addItem(label, code)
        merge_row.addWidget(self.cmb_how)
        self.btn_add_step = QPushButton("결합 방법 추가")
        # 화면당 primary 1개 규율(UD-22): '스텝 추가'와 '풀에 저장' 2개가 경쟁하던 것을,
        # 완료 액션인 [풀에 저장]만 primary 로 두고 조립 중 반복 액션인 [스텝 추가]는 일반
        # 버튼으로 강등한다(조립은 반복, 저장은 종결 — 주 행동은 저장).
        self.btn_add_step.clicked.connect(self._on_add_step)
        merge_row.addWidget(self.btn_add_step)
        self.btn_del_step = QPushButton("결합 방법 제거")
        self.btn_del_step.clicked.connect(self._on_remove_step)
        merge_row.addWidget(self.btn_del_step)
        root.addLayout(merge_row)
        self.lst_steps = QListWidget()
        self.lst_steps.setMaximumHeight(90)
        root.addWidget(self.lst_steps)

        # ------------------------------------------------------- 미리보기
        pv_head = QHBoxLayout()
        self.lbl_preview_title = QLabel("미리보기")
        mark(self.lbl_preview_title, "heading", True)
        pv_head.addWidget(self.lbl_preview_title)
        pv_head.addStretch(1)
        self.btn_preview = QPushButton("미리보기")
        self.btn_preview.clicked.connect(self._on_preview)
        pv_head.addWidget(self.btn_preview)
        root.addLayout(pv_head)
        self.lbl_error = QLabel("")
        self.lbl_error.setWordWrap(True)
        mark(self.lbl_error, "level", "danger")
        self.lbl_error.hide()
        root.addWidget(self.lbl_error)
        self.tbl_preview = QTableWidget()
        root.addWidget(self.tbl_preview, 1)
        self.lbl_total = QLabel("")
        mark(self.lbl_total, "muted", True)
        root.addWidget(self.lbl_total)

        # ------------------------------------------------------------ 저장
        foot = QHBoxLayout()
        foot.addWidget(QLabel("이름:"))
        self.edt_name = QLineEdit()
        self.edt_name.setPlaceholderText("조립 이름 (등록 데이터로 저장)")
        foot.addWidget(self.edt_name, 1)
        self.btn_save = QPushButton("등록 데이터로 저장")
        mark(self.btn_save, "primary", True)
        self.btn_save.clicked.connect(self._on_save)
        foot.addWidget(self.btn_save)
        btn_cancel = QPushButton("닫기")
        btn_cancel.clicked.connect(self.reject)
        foot.addWidget(btn_cancel)
        root.addLayout(foot)

        self._on_op_changed()
        self._render()

    # ------------------------------------------------------------- 렌더
    def _render(self) -> None:
        self.lst_sources.clear()
        for i, s in enumerate(self.vm.sources):
            role = "기준 데이터" if i == 0 else f"추가 데이터 {i}"
            self.lst_sources.addItem(f"[{role}] {s.name} ({_KIND_TEXT.get(s.kind, s.kind)})")
        self._refresh_source_picker()
        # 대상 콤보 재구성 — 이전 선택(인덱스)을 보존한다. clear() 가 선택을 첫 항목으로
        # 리셋하면 연속 [스텝 추가]가 조용히 씨앗(0) 대상 자기스텝을 만들 수 있다.
        prev_target = self.cmb_target.currentData()
        self.cmb_target.clear()
        for i, s in enumerate(self.vm.sources):
            self.cmb_target.addItem(f"{i}: {s.name}", i)
        if prev_target is not None and 0 <= prev_target < self.cmb_target.count():
            self.cmb_target.setCurrentIndex(prev_target)
        self.lst_steps.clear()
        for st in self.vm.steps:
            if st["op"] == "merge":
                self.lst_steps.addItem(
                    f"열 결합 ← 데이터 {st['source']} · 기준 항목 {st['on']} · "
                    f"{_HOW_TEXT.get(st['how'], st['how'])}"
                )
            else:
                self.lst_steps.addItem(f"행 추가 ← 데이터 {st['source']}")

    def _refresh_source_picker(self, preferred: str = "") -> None:
        """이미 추가한 데이터는 선택지에서 빼고, 제거하면 다시 선택지에 돌려놓는다."""
        current = preferred or self.cmb_pool.currentText()
        used = {source.name for source in self.vm.sources}
        names = [name for name in self.vm.available_source_names() if name not in used]
        self.cmb_pool.clear()
        self.cmb_pool.addItems(names)
        if current in names:
            self.cmb_pool.setCurrentText(current)
        self.btn_add_source.setEnabled(bool(names))

    def _on_op_changed(self) -> None:
        is_merge = self.cmb_op.currentData() == "merge"
        self.cmb_key.setEnabled(is_merge)
        self.cmb_how.setEnabled(is_merge)
        self.btn_suggest.setEnabled(is_merge)

    # ------------------------------------------------------------- 액션
    def _on_add_source(self) -> None:
        name = self.cmb_pool.currentText()
        if not name:
            return
        if any(source.name == name for source in self.vm.sources):
            QMessageBox.information(
                self, "이미 추가됨", f"'{name}' 데이터는 이미 이 조립에 들어 있습니다."
            )
            self._refresh_source_picker()
            return
        try:
            self.vm.add_source(name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"데이터 추가 실패:\n{_friendly_error(exc)}")
            return
        self._render()
        self._invalidate_preview()

    def _on_remove_source(self) -> None:
        idx = self.lst_sources.currentRow()
        if idx < 0:
            return
        try:
            self.vm.remove_source(idx)
        except Exception as exc:  # noqa: BLE001 — 스텝이 참조 중이면 시끄럽게
            QMessageBox.warning(self, "제거 불가", _friendly_error(exc))
            return
        self._render()
        self._invalidate_preview()

    def _on_suggest(self) -> None:
        """공유 컬럼 감지 → 키 콤보에 **후보만** 채움(스텝 미생성 — 사람 확정 게이트)."""
        idx = self.cmb_target.currentData()
        if idx is None:
            QMessageBox.information(self, "항목 제안", "대상 데이터를 먼저 추가·선택하세요.")
            return
        try:
            keys = self.vm.suggest_merge_keys(idx)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "항목 제안 실패", _friendly_error(exc))
            return
        self.cmb_key.clear()
        if keys:
            self.cmb_key.addItems(keys)
        else:
            QMessageBox.information(
                self,
                "항목 제안",
                "두 데이터에 공통 항목이 없습니다 — 기준 항목을 직접 입력하거나 "
                "'아래에 행 추가'를 사용하세요.",
            )

    def _on_register_source(self, callback) -> None:
        """조립을 닫지 않고 새 데이터를 등록한 뒤 선택 목록을 즉시 갱신한다."""
        if not callable(callback):
            return
        before = set(self.vm.available_source_names())
        callback(self)
        after = self.vm.available_source_names()
        added = [name for name in after if name not in before]
        self._refresh_source_picker(added[-1] if added else "")

    def _on_add_step(self) -> None:
        idx = self.cmb_target.currentData()
        if idx is None:
            QMessageBox.information(self, "결합 방법 추가", "대상 데이터를 먼저 추가·선택하세요.")
            return
        op = self.cmb_op.currentData()
        try:
            if op == "merge":
                self.vm.add_step(
                    "merge", idx,
                    on=self.cmb_key.currentText().strip(),
                    how=self.cmb_how.currentData(),
                )
            else:
                self.vm.add_step("append", idx)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "결합 방법 추가 실패", _friendly_error(exc))
            return
        self._render()
        self._invalidate_preview()

    def _on_remove_step(self) -> None:
        idx = self.lst_steps.currentRow()
        if idx < 0:
            return
        self.vm.remove_step(idx)
        self._render()
        self._invalidate_preview()

    def _invalidate_preview(self) -> None:
        """소스·스텝 편집 → 이전 미리보기 스테일 무효화(RC-13 이식; nara_view._on_query_edited).

        표·총행을 비우고 warn 으로 재미리보기를 요구한다 — '저장 후 실행 결과가 이 표다'
        단언은 **신선한** 미리보기에서만 성립하므로, 편집으로 어긋난 스냅샷을 조용히
        잔존시키지 않는다(confirm-or-alarm). 미리보기가 한 번도 없었으면 무효화할 스냅샷이
        없어 조용히 통과(취득 전 nara 게이트가 이미 잠겨 있는 것과 같은 상태).
        """
        if not self._preview_shown:
            return
        self._preview_shown = False
        self.tbl_preview.clearContents()
        self.tbl_preview.setRowCount(0)
        self.tbl_preview.setColumnCount(0)
        self.lbl_total.setText("")
        mark(self.lbl_error, "level", "warn")
        self.lbl_error.setText("조립이 변경됨 — 다시 미리보기하세요.")
        self.lbl_error.show()

    def _on_preview(self) -> None:
        from .view_helpers import busy_cursor

        with busy_cursor():  # 조립 미리보기(소스 로드·나라 서브소스 네트워크 포함, ST-16)
            result = self.vm.preview()
        if not result.ok:
            self._preview_shown = False  # 실패한 미리보기는 신선한 스냅샷이 아니다
            mark(self.lbl_error, "level", "danger")  # 무효화 경고(warn)에서 오류(danger)로 복원
            self.lbl_error.setText(f"조립 실패: {_friendly_error(result.error)}")
            self.lbl_error.show()
            self.tbl_preview.clearContents()
            self.tbl_preview.setRowCount(0)
            self.tbl_preview.setColumnCount(0)
            self.lbl_total.setText("")
            return
        self._preview_shown = True  # 신선한 미리보기 표시됨 — 이후 편집이 이를 무효화한다
        self.lbl_error.hide()
        self.tbl_preview.setColumnCount(len(result.fields))
        self.tbl_preview.setHorizontalHeaderLabels(result.fields)
        self.tbl_preview.setRowCount(len(result.rows))
        for r, rec in enumerate(result.rows):
            for c, f in enumerate(result.fields):
                # left 조인 무매칭 결측·원본 빈 문자열을 무표시 공백으로 렌더하던 것을
                # '(결측)'·'(비움)' 으로 명시 재진술한다(UD-26 D6c — '실행 결과와 동일'을
                # 자처하는 검수 표면에서 무매칭 행을 놓치지 않게).
                self.tbl_preview.setItem(r, c, restate_preview_item(rec, f))
        shown = len(result.rows)
        self.lbl_total.setText(
            f"총 {result.total}건" + (f" (상위 {shown}건 표시)" if result.total > shown else "")
        )

    def _on_save(self) -> None:
        name = self.edt_name.text().strip()
        # 동명 항목은 조용히 덮지 않는다 — 사람 확정 후에만 overwrite(confirm-or-alarm).
        overwrite = False
        if name and self.vm.registry.exists(name):
            if not confirm_destructive(
                self, "이름 충돌",
                f"'{name}' 데이터셋이 이미 있습니다 — 이 파이프라인으로 덮어쓰면 "
                "기존 참조는 사라집니다.",
                "덮어쓰기",
            ):
                return
            overwrite = True
        try:
            item = self.vm.save(name, overwrite=overwrite)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "저장 실패", _friendly_error(exc))
            return
        self.saved_name = item.name
        self.accept()

    def _is_dirty(self) -> bool:
        """조립 중 작업물이 있는가 — 소스나 스텝이 하나라도 있으면 더티."""
        return bool(self.vm.sources or self.vm.steps)

    def reject(self) -> None:
        """닫기·Esc 이탈 경로(UD-45) — 더티 상태면 무확인 폐기하지 않는다.

        같은 다이얼로그가 이름 충돌 덮어쓰기에는 confirm_destructive 를 요구하면서(_on_save)
        이탈 경로만 무확인으로 두던 비대칭을 없앤다. 반사적 Esc 한 번에 수 클릭 분량의
        조립이 사라지지 않도록, 이탈도 같은 파괴 확인 게이트를 경유한다(RC-15 확장).
        """
        if self._is_dirty() and not confirm_destructive(
            self, "조립 폐기",
            "조립 중인 파이프라인을 버리고 닫을까요? 추가한 소스·스텝이 사라집니다.",
            "폐기",
        ):
            return
        super().reject()
