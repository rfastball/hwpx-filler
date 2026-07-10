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


def test_job_editor_instantiates_with_four_pages(qapp, tmp_path):
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    wiz = JobEditorWizard(JobRegistry(tmp_path))
    assert len(wiz.pageIds()) == 4  # 템플릿/데이터/매핑/저장
    # 1단계는 템플릿 선택 전이라 미완료 — 다음 비활성.
    assert not wiz.page(wiz.pageIds()[0]).isComplete()
    # 마지막 스텝은 '생성'이 아니라 '작업 저장'.
    from hwpxfiller.gui.job_editor import SaveJobPage

    assert isinstance(wiz.page(wiz.pageIds()[-1]), SaveJobPage)


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


def test_mapping_table_set_preview_record_updates_preview_column(qapp):
    from hwpxfiller.gui.mapping_table import _COL_PREVIEW, MappingTable

    model = _model()
    table = MappingTable()
    table.set_model(model, {"bidNtceNm": "첫 공고", "opengDate": "2026-06-15"})
    ri = next(i for i, r in enumerate(model.rows) if r.template_field == "공고명")
    first = table.table.item(ri, _COL_PREVIEW).text()
    assert first == "첫 공고"

    table.set_preview_record({"bidNtceNm": "둘째 공고", "opengDate": "2026-07-01"})
    assert table.table.item(ri, _COL_PREVIEW).text() == "둘째 공고"


def test_record_selector_all_none_and_toggle(qapp):
    from hwpxfiller.gui.record_select import RecordSelector

    sel = RecordSelector()
    sel.set_records([{"ID": "A"}, {"ID": "B"}, {"ID": "C"}], "doc-{{ID}}")
    assert sel.selected_indices() == [0, 1, 2]  # 기본 전체 선택

    sel._on_none()
    assert sel.selected_indices() == []
    sel._on_all()
    assert sel.selected_indices() == [0, 1, 2]

    # 항목 체크 해제가 모델에 반영.
    from PySide6.QtCore import Qt

    sel.list.item(1).setCheckState(Qt.Unchecked)
    assert sel.selected_indices() == [0, 2]

    # 라벨은 파일명 미리보기.
    assert sel.list.item(0).text() == "1. doc-A.hwpx"


def test_record_selector_relabel_preserves_selection(qapp):
    from PySide6.QtCore import Qt

    from hwpxfiller.gui.record_select import RecordSelector

    records = [{"ID": "A"}, {"ID": "B"}]
    sel = RecordSelector()
    sel.set_records(records, "doc-{{ID}}")
    sel.list.item(0).setCheckState(Qt.Unchecked)
    assert sel.selected_indices() == [1]

    sel.relabel(records, "새-{{ID}}")
    assert sel.selected_indices() == [1]  # 선택 보존
    assert sel.list.item(0).text() == "1. 새-A.hwpx"


def test_mapping_table_format_combo_drives_preview(qapp):
    from hwpxfiller.gui.mapping_table import _COL_FORMAT, _COL_PREVIEW, MappingTable

    schema = TemplateSchema(fields=[FieldSpec("추정가격", "amount", 1, False)])
    model = MappingModel.from_suggestions(schema, ["presmptPrce"], {"presmptPrce": "추정가격"})
    table = MappingTable()
    table.set_model(model, {"presmptPrce": "21326800"})
    ri = 0
    # 기본 표시형(원)일 때 미리보기.
    assert table.table.item(ri, _COL_PREVIEW).text() == "21,326,800원"
    # 표시형 콤보에서 '숫자' 프리셋(코드 "{:,}") 선택 → 모델·미리보기 반영.
    fmtc = table.table.cellWidget(ri, _COL_FORMAT)
    plain_idx = next(i for i in range(fmtc.count()) if fmtc.itemData(i) == "{:,}")
    table._on_format_activated(ri, plain_idx)
    assert model.rows[ri].fmt == "{:,}"
    assert table.table.item(ri, _COL_PREVIEW).text() == "21,326,800"


def test_worker_module_imports(qapp):
    from hwpxfiller.gui.worker import GenerateWorker  # noqa: F401


def test_home_exposes_navigation_signals_and_lists_jobs(qapp, tmp_path):
    from hwpxfiller.core.job import Job, JobRegistry
    from hwpxfiller.gui.home import JobListHome

    reg = JobRegistry(tmp_path)
    reg.save(Job(name="샘플작업", template_path="/t.hwpx"))
    home = JobListHome(reg)
    # 네비게이션 시그널 계약 존재 확인.
    for sig in ("new_job_requested", "edit_job_requested", "run_job_requested", "delete_job_requested"):
        assert hasattr(home, sig)
    # 레지스트리 작업이 목록에 바인딩됨.
    assert home.list.count() == 1
    assert home.list.item(0).text() == "샘플작업"


def test_home_empty_state_and_job_cards(qapp, tmp_path):
    """빈 상태 ↔ 카드 목록 전환, 빈 상태 버튼 = new_job_requested 동일 시그널."""
    from PySide6.QtWidgets import QLabel

    from hwpxfiller.core.job import Job, JobRegistry
    from hwpxfiller.gui.home import _JobCard, JobListHome

    reg = JobRegistry(tmp_path)
    home = JobListHome(reg)
    assert home.stack.currentIndex() == 1  # 작업 0개 → 빈 상태

    emitted = []
    home.new_job_requested.connect(lambda: emitted.append(True))
    home.btn_empty_new.click()
    assert emitted  # 빈 상태 버튼도 같은 계약 시그널

    reg.save(Job(name="카드작업", template_path="/t.hwpx", filename_pattern="doc-{{ID}}"))
    home.refresh()
    assert home.stack.currentIndex() == 0  # 목록 페이지로
    item = home.list.item(0)
    card = home.list.itemWidget(item)
    assert isinstance(card, _JobCard)
    joined = " ".join(lbl.text() for lbl in card.findChildren(QLabel))
    assert "카드작업" in joined
    assert "필드 0개" in joined          # 메타 노출
    assert "아직 집행 안 함" in joined    # 미집행 상태
    assert "템플릿 없음" in joined        # 부재 템플릿 선고지


def test_app_controller_records_last_run(qapp, tmp_path, monkeypatch):
    """성공 집행(run_finished) → last_run_at 저장·홈 갱신. RunView 는 레지스트리 무지."""
    from hwpxfiller.core.job import Job, JobRegistry
    from hwpxfiller.gui.app import _AppController

    reg = JobRegistry(tmp_path)
    reg.save(Job(name="집행기록", template_path="/t.hwpx"))
    ctrl = _AppController(reg)

    class _Batch:
        succeeded = 2

    ctrl._record_run("집행기록", _Batch())
    assert reg.load("집행기록").last_run_at != ""

    class _Failed:
        succeeded = 0

    before = reg.load("집행기록").last_run_at
    ctrl._record_run("집행기록", _Failed())
    assert reg.load("집행기록").last_run_at == before  # 실패 집행은 갱신 안 함


def test_run_view_instantiates_with_a_job(qapp):
    from hwpxfiller.core.job import Job
    from hwpxfiller.gui.run_view import RunView

    view = RunView(Job(name="집행테스트", template_path="/t.hwpx", filename_pattern="doc-{{ID}}"))
    assert view.datasource is None  # 데이터 미겨눔 상태로 시작
    assert hasattr(view, "run_finished")


# ------------------------------------------------------------------ 앱 A(diff)
def _diff_window_for_test(tmp_path, monkeypatch):
    """실패 모달 즉시 fail + QSettings 를 임시 파일로(사용자 설정 오염 방지)한 창."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.gui.diff_app import DiffReviewWindow

    # 실패 경로의 모달은 offscreen 에서 exec 루프로 영원히 블록 — 행 대신 즉시 실패.
    monkeypatch.setattr(
        QMessageBox, "critical",
        lambda *a, **k: pytest.fail(f"비교 실패 다이얼로그가 떴다: {a[2] if len(a) > 2 else a}"),
    )
    win = DiffReviewWindow()
    win._settings = QSettings(str(tmp_path / "recent.ini"), QSettings.IniFormat)
    return win


def test_diff_window_compares_real_corpus_and_binds_items(qapp, tmp_path, monkeypatch):
    """앱 A 단일 화면 — 실코퍼스 개정 쌍 비교가 리스트·뷰에 바인딩되고 클릭 이동이 돈다."""
    from pathlib import Path

    from PySide6.QtCore import Qt

    corpus = Path(__file__).parent / "corpus" / "real"
    win = _diff_window_for_test(tmp_path, monkeypatch)
    assert not win.btn_compare.isEnabled()  # 판본 선택 전

    win.ed_old.setText(str(corpus / "spec_revision_2025.hwpx"))
    win.ed_new.setText(str(corpus / "spec_revision_2026.hwpx"))
    win._on_compare()

    assert win.result is not None
    assert win.items.rowCount() == len(win.result.change_items) > 0
    # 클릭 이동 계약: 각 행의 표적(Qt.UserRole == Change.seq)이 리포트 앵커로 실재.
    # scrollToAnchor 는 없는 앵커를 조용히 무시하므로, 표적 실재를 직접 못박는다.
    for r in range(win.items.rowCount()):
        seq = win.items.item(r, 0).data(Qt.UserRole)
        assert f"id='chg-{seq}'" in win._html, f"행 {r}: 앵커 chg-{seq} 없음"
    win.items.selectRow(0)  # 선택 시그널 경로가 예외 없이 동작
    assert win.btn_browser.isEnabled() and win.btn_save.isEnabled()


def test_diff_visible_predicate_headless():
    """행 표시 판정 — renumber 는 전용 토글, 나머지는 범주 체크."""
    from hwpxfiller.gui.diff_app import _visible

    assert _visible("number", {"number"}, False)
    assert not _visible("number", set(), False)
    assert not _visible("renumber", {"renumber"}, False)  # 범주 체크가 아니라 토글만 따름
    assert _visible("renumber", set(), True)


def test_diff_category_filter_and_renumber_toggle(qapp, tmp_path, monkeypatch):
    """범주 필터·번호변경 접기 — 기본: 실질 범주 전부 표시 + renumber 숨김(개수는 노출)."""
    from pathlib import Path

    corpus = Path(__file__).parent / "corpus" / "real"
    win = _diff_window_for_test(tmp_path, monkeypatch)
    win.ed_old.setText(str(corpus / "spec_revision_2025.hwpx"))
    win.ed_new.setText(str(corpus / "spec_revision_2026.hwpx"))
    win._on_compare()

    items = win.result.change_items
    renumber_rows = [r for r, it in enumerate(items) if it.category == "renumber"]
    hidden = [r for r in range(win.items.rowCount()) if win.items.isRowHidden(r)]
    assert hidden == renumber_rows  # 기본: renumber 만 숨김
    if renumber_rows:
        assert win.chk_renumber is not None
        assert f"{len(renumber_rows)}건" in win.chk_renumber.text()  # 조용히 버리지 않음
        win.chk_renumber.setChecked(True)
        assert not any(win.items.isRowHidden(r) for r in renumber_rows)

    # 특정 범주 해제 → 해당 행만 추가로 숨김.
    cat, cb = next(iter(win._filter_checks.items()))
    cb.setChecked(False)
    for r, it in enumerate(items):
        if it.category == cat:
            assert win.items.isRowHidden(r)

    # 판본 변경 → 결과·필터 바 무효화.
    win._invalidate_result("변경")
    assert win.filter_bar.count() == 0 and win.chk_renumber is None


def test_diff_ingest_paths_and_recent_pairs(qapp, tmp_path):
    """DnD/최근 목록 공용 투입 — 2개=구→신, 1개=빈 칸 우선, 비-hwpx 무시, 결과 무효화."""
    from PySide6.QtCore import QSettings

    from hwpxfiller.gui.diff_app import DiffReviewWindow

    win = DiffReviewWindow()
    win._settings = QSettings(str(tmp_path / "recent.ini"), QSettings.IniFormat)

    a, b = str(tmp_path / "a.hwpx"), str(tmp_path / "b.hwpx")
    win._ingest_paths([a, b])
    assert win.ed_old.text() == a and win.ed_new.text() == b
    assert win.btn_compare.isEnabled()

    win.ed_old.clear(); win.ed_new.clear()
    win._ingest_paths([a])                    # 1개 → 빈 구판부터
    assert win.ed_old.text() == a and not win.ed_new.text()
    win._ingest_paths([b])                    # 1개 더 → 빈 신판
    assert win.ed_new.text() == b
    win._ingest_paths([str(tmp_path / "x.txt")])  # 비-hwpx 무시
    assert win.ed_old.text() == a and win.ed_new.text() == b
    win._html = "<html>이전 결과</html>"
    win._ingest_paths([b])                    # 둘 다 차 있으면 구판 교체 + 결과 무효화
    assert win.ed_old.text() == b and win._html == ""

    # 최근 쌍: 중복 제거·앞 삽입·최대 5개.
    for i in range(7):
        win._push_recent(f"o{i}.hwpx", f"n{i}.hwpx")
    win._push_recent("o6.hwpx", "n6.hwpx")    # 중복 재푸시 → 맨 앞 유지, 증식 없음
    pairs = win._recent_pairs()
    assert len(pairs) == 5
    assert pairs[0] == ("o6.hwpx", "n6.hwpx")


def test_diff_list_badge_colors_match_core_palette(qapp, tmp_path, monkeypatch):
    """리스트 배지색 = HTML 리포트의 b-{category} — 코어 팔레트 단일 출처 계약."""
    from pathlib import Path

    from hwpxfiller.core.diff import CATEGORY_COLORS

    corpus = Path(__file__).parent / "corpus" / "real"
    win = _diff_window_for_test(tmp_path, monkeypatch)
    win.ed_old.setText(str(corpus / "spec_revision_2025.hwpx"))
    win.ed_new.setText(str(corpus / "spec_revision_2026.hwpx"))
    win._on_compare()

    assert win.items.rowCount() > 0
    for r in range(win.items.rowCount()):
        it = win.result.change_items[r]
        cell = win.items.item(r, 0)
        assert cell.background().color().name() == CATEGORY_COLORS[it.category], (
            f"행 {r} ({it.category}): 배지색이 코어 팔레트와 다름"
        )
