"""데이터셋 풀 워크숍 위젯 — durable 데이터 참조의 등록·수명 관리면(얇은 렌더러).

레이어링: 위젯은 얇은 렌더러 — 등록·상태 전이·행 성형은 전부
:class:`~hwpxfiller.gui.dataset_pool_state.DatasetPoolViewModel`(Qt 비의존, 링1)이 소유.
이 위젯은 행을 카드로 얹고 상태별 버튼을 배선하며, 등록 대화(엑셀 파일 선택 / 나라장터
:class:`~hwpxfiller.gui.nara_view.NaraAcquireDialog` 재사용)를 오케스트레이션한다.

**참조만 저장**: 엑셀=경로, 나라=쿼리(기간·건수). 레코드·ServiceKey 는 저장하지 않는다.
나라 등록은 N2 대화상자로 키 등록/연결시험 + 기간·건수를 받고, **취득 데이터가 아니라
쿼리 참조**만 풀에 넣는다(실행 때 키 주입·재읽기).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .confirm import confirm_destructive
from .dataset_pool_state import DatasetPoolRow, DatasetPoolViewModel
from .file_filters import EXCEL_FILTER
from .style import BASE_QSS, mark


class _PoolCard(QWidget):
    """풀 1항목 카드 — 이름 + 종류·상태 배지 + 참조 요약 + 상태별 액션 버튼."""

    def __init__(self, row: DatasetPoolRow, on_action, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(3)

        name_row = QHBoxLayout()
        lbl_name = QLabel(row.name)
        mark(lbl_name, "heading", True)
        name_row.addWidget(lbl_name)
        kind_badge = QLabel(row.kind_label)
        mark(kind_badge, "muted", True)
        name_row.addWidget(kind_badge)
        badge = QLabel(row.badge_label)
        mark(badge, "level", row.badge_level)
        name_row.addWidget(badge)
        name_row.addStretch(1)
        root.addLayout(name_row)

        lbl_ref = QLabel(row.reference)
        mark(lbl_ref, "muted", True)
        lbl_ref.setWordWrap(True)
        root.addWidget(lbl_ref)

        foot = QHBoxLayout()
        foot.addStretch(1)
        for act in row.actions():
            btn = QPushButton(act.label)
            if act.key == "delete":
                mark(btn, "level", "danger")
            btn.clicked.connect(
                lambda _checked=False, k=act.key, n=row.name: on_action(k, n)
            )
            foot.addWidget(btn)
        root.addLayout(foot)


class DatasetPoolPanel(QMainWindow):
    """데이터셋 풀 워크숍. :class:`DatasetPoolViewModel` 을 렌더한다."""

    pool_changed = Signal()  # 등록/상태변경/삭제 후 — 홈이 KPI 갱신용으로 연결(app.py)

    def __init__(self, registry=None, parent=None, *, store=None, fetcher=None):
        super().__init__(parent)
        self.vm = DatasetPoolViewModel(registry)
        self._store = store
        self._fetcher = fetcher

        self.setWindowTitle("HWPX Filler — 데이터 풀")
        self.resize(720, 560)
        self.setStyleSheet(BASE_QSS)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        title = QLabel("데이터 풀")
        mark(title, "heading", True)
        self.lbl_count = QLabel("")
        mark(self.lbl_count, "muted", True)
        header.addWidget(title)
        header.addWidget(self.lbl_count)
        header.addStretch(1)
        self.btn_add_excel = QPushButton("엑셀/CSV 등록…")
        self.btn_add_excel.clicked.connect(self._on_register_excel)
        self.btn_add_nara = QPushButton("나라장터 등록…")
        self.btn_add_nara.clicked.connect(self._on_register_nara)
        self.btn_add_pipeline = QPushButton("파이프라인 조립…")
        self.btn_add_pipeline.clicked.connect(self._on_build_pipeline)
        mark(self.btn_add_excel, "primary", True)
        header.addWidget(self.btn_add_excel)
        header.addWidget(self.btn_add_nara)
        header.addWidget(self.btn_add_pipeline)
        root.addLayout(header)

        self.list = QListWidget()
        self.list.setObjectName("jobList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.list, 1)

        self.lbl_empty = QLabel(
            "등록된 데이터가 없습니다 — 엑셀/CSV 파일이나 나라장터 쿼리를 참조로 등록하세요.\n"
            "데이터는 복사되지 않고 참조만 저장됩니다(실행할 때 다시 읽습니다)."
        )
        self.lbl_empty.setWordWrap(True)
        mark(self.lbl_empty, "muted", True)
        root.addWidget(self.lbl_empty)

        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        mark(self.lbl_result, "muted", True)
        root.addWidget(self.lbl_result)

        self.vm.subscribe(self._render)
        self._render()

    # ------------------------------------------------------------- 렌더
    def refresh(self) -> None:
        self.vm.refresh()

    def _render(self) -> None:
        self.lbl_count.setText(self.vm.count_label())
        self.lbl_empty.setVisible(self.vm.is_empty())
        self.list.clear()
        for row in self.vm.rows():
            self.list.addItem(row.name)
            item = self.list.item(self.list.count() - 1)
            item.setForeground(QColor(0, 0, 0, 0))  # 이름은 아이템 text, 표시는 카드
            card = _PoolCard(row, on_action=self._dispatch)
            item.setSizeHint(card.sizeHint())
            self.list.setItemWidget(item, card)

    # ---------------------------------------------------- 액션 디스패치
    def _dispatch(self, key: str, name: str) -> None:
        if key == "delete":
            if not confirm_destructive(
                self, "데이터셋 삭제", f"데이터셋 '{name}' 참조를 삭제할까요?", "삭제"
            ):
                return
        try:
            self.vm.dispatch(key, name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"작업 실패:\n{exc}")
            return
        self.pool_changed.emit()

    # ------------------------------------------------------------- 등록
    def _on_register_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "데이터 파일 선택", "", EXCEL_FILTER
        )
        if not path:
            return
        from pathlib import Path

        name, ok = QInputDialog.getText(
            self, "데이터셋 이름", "이름:", text=Path(path).stem
        )
        if not ok or not name.strip():
            return
        try:
            self.vm.register_excel(name, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"등록 실패:\n{exc}")
            return
        self.lbl_result.setText(f"등록 완료: {name}")
        self.pool_changed.emit()

    def _on_build_pipeline(self) -> None:
        """파이프라인 조립(KB) — 빌더 대화상자로 저작·미리보기, 수용 시 풀 갱신.

        저장은 빌더 뷰모델이 레지스트리에 직접 한다(참조·레시피만) — 여기선 대화
        오케스트레이션과 수용 후 새로고침·통지뿐.
        """
        from .pipeline_builder import PipelineBuilderDialog

        dlg = PipelineBuilderDialog(
            self.vm.registry, self, store=self._store, fetcher=self._fetcher
        )
        if dlg.exec() != dlg.Accepted:
            return
        self.vm.refresh()
        self.lbl_result.setText(f"등록 완료: {dlg.saved_name} (조립 파이프라인)")
        self.pool_changed.emit()

    def _on_register_nara(self) -> None:
        """나라장터 등록 — N2 대화상자로 키·기간·건수를 받고 **쿼리 참조**만 풀에 저장.

        대화상자는 취득 성공(키·쿼리 유효)에서만 수용되므로 등록 전에 사실상 연결 검증이
        된다. 취득 데이터는 버리고 opts(기간·건수)만 저장한다(스냅샷 금지·키 비저장).
        """
        from .nara_view import NaraAcquireDialog

        dlg = NaraAcquireDialog(self, store=self._store, fetcher=self._fetcher)
        if dlg.exec() != dlg.Accepted:
            return
        self._register_nara_from_dialog(dlg)

    def _register_nara_from_dialog(self, dlg) -> None:
        """대화상자 수용 결과에서 쿼리 참조를 만들어 등록(헤드리스 테스트용 분리).

        저장하는 기간·건수는 **취득 시점 스냅샷**(``query_options``) — 위젯 현재값을
        재독하지 않는다(취득으로 검증된 쿼리만 풀에 들어간다, RC-13).
        """
        name, ok = QInputDialog.getText(self, "데이터셋 이름", "이름:")
        if not ok or not name.strip():
            return
        try:
            opts = dlg.query_options()  # 스냅샷 부재 시 시끄럽게 실패(조용한 위젯값 폴백 금지)
            self.vm.register_nara(
                name, str(opts["bgn_dt"]), str(opts["end_dt"]),
                num_rows=int(opts["num_rows"]), page_no=int(opts["page_no"]),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"등록 실패:\n{exc}")
            return
        self.lbl_result.setText(f"등록 완료: {name} (나라장터 쿼리 참조)")
        self.pool_changed.emit()
