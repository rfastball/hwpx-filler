"""GUI 스모크 — PySide6 설치 환경에서만 실행(미설치면 전체 skip, 헤드리스 offscreen).

깊은 UI 상호작용 테스트가 아니라, 위저드/테이블이 임포트·인스턴스화되고
모델 편집이 뷰 시그널로 전파되는 최소 배선을 확인한다.
로직 자체는 test_mapping_state.py 가 헤드리스로 검증한다.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hwpxfiller.core.mapping import NARA_ALIASES  # noqa: E402
from hwpxfiller.core.schema import FieldSpec, TemplateSchema  # noqa: E402
from hwpxfiller.gui.mapping_state import MappingModel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _model() -> MappingModel:
    schema = TemplateSchema(
        fields=[
            FieldSpec("공고명", "text", 1, False, "공 고 명:"),
            FieldSpec("개찰일시", "date", 1, True),
            FieldSpec("미매칭필드qq", "text", 1, False),
        ]
    )
    return MappingModel.from_suggestions(schema, list(NARA_ALIASES), NARA_ALIASES)


def test_wizard_instantiates_with_four_pages(qapp):
    from hwpxfiller.gui.wizard import MappingWizard

    wiz = MappingWizard()
    assert len(wiz.pageIds()) == 4
    # 1단계는 템플릿 선택 전이라 미완료 — 다음 비활성.
    assert not wiz.page(wiz.pageIds()[0]).isComplete()


def test_mapping_table_renders_model_and_emits_complete_changed(qapp):
    from hwpxfiller.gui.mapping_table import MappingTable

    model = _model()
    table = MappingTable()
    table.set_model(model, {"bidNtceNm": "테스트 공고", "opengDate": "2026-06-15"})
    assert table.table.rowCount() == len(model.rows)

    emitted = []
    table.completeChanged.connect(lambda: emitted.append(True))
    table.btn_confirm_all.click()
    assert emitted
    assert model.is_complete()
    table.btn_unconfirm_all.click()
    assert not model.is_complete()


def test_worker_and_main_window_modules_import(qapp):
    from hwpxfiller.gui.main_window import MainWindow  # noqa: F401
    from hwpxfiller.gui.worker import GenerateWorker  # noqa: F401
