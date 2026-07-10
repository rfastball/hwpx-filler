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


def _saved_job(tmp_path):
    """편집 프리로드 테스트용 저장 작업 — 매핑 2행(공고명·추정가격) 확정본."""
    from hwpxfiller.core.job import Job, JobRegistry
    from hwpxfiller.gui.mapping_state import MappingModel

    model = _model()
    for i, row in enumerate(model.rows):
        if row.template_field == "공고명":
            model.set_sources(i, ["bidNtceNm"])
    model.confirm_all()
    reg = JobRegistry(tmp_path)
    job = Job(
        name="편집대상", template_path="/t.hwpx",
        mapping=model.to_profile("편집대상"), filename_pattern="공고-{{공고명}}",
    )
    reg.save(job)
    return reg, job


def test_editor_edit_mode_prefills_and_preseeds(qapp, tmp_path):
    """편집 모드 — SaveJobPage 이름·패턴 프리필 + MappingPage 매핑 프리시드(일치 행 확정)."""
    from hwpxfiller.gui.job_editor import JobEditorWizard

    reg, job = _saved_job(tmp_path)
    wiz = JobEditorWizard(reg, initial_job=job)
    assert "편집" in wiz.windowTitle()

    # SaveJobPage 프리필(1회) — 사용자 수정을 되돌리지 않는다.
    save_page = wiz.page(wiz.pageIds()[-1])
    save_page.initializePage()
    assert save_page.job_name() == "편집대상"
    assert save_page.pattern() == "공고-{{공고명}}"
    save_page.ed_name.setText("바꾼이름")
    save_page.initializePage()
    assert save_page.job_name() == "바꾼이름"  # 재진입이 프리필로 덮지 않음

    # MappingPage 프리시드 — 위저드 세션 상태를 심고 initializePage 호출.
    from hwpxfiller.core.mapping import NARA_ALIASES

    wiz.template_path = "/t.hwpx"
    wiz.data_path = "/d.xlsx"
    wiz.schema = TemplateSchema(
        fields=[
            FieldSpec("공고명", "text", 1, False),
            FieldSpec("개찰일시", "date", 1, True),
            FieldSpec("미매칭필드qq", "text", 1, False),
        ]
    )
    wiz.source_fields = list(NARA_ALIASES)
    wiz.records = [{"bidNtceNm": "샘플"}]
    mapping_page = wiz.page(wiz.pageIds()[2])
    mapping_page.initializePage()
    rows = {r.template_field: r for r in wiz.model.rows}
    assert rows["공고명"].confirmed          # 프로파일 일치 행 = 확정 복원
    assert not rows["미매칭필드qq"].confirmed  # 프로파일 밖(과거 비움 확정) = 미확정 유지
    assert "확정" in mapping_page.lbl_progress.text()


def test_editor_edit_mode_accept_same_name_no_prompt(qapp, tmp_path, monkeypatch):
    """편집 모드 자기 자신 재저장은 덮어쓰기 프롬프트 없음 + last_run_at 이월."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.gui.job_editor import JobEditorWizard

    reg, job = _saved_job(tmp_path)
    job.last_run_at = "2026-07-01T09:00:00"
    reg.save(job)

    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: pytest.fail("자기 자신 갱신에 덮어쓰기 프롬프트가 떴다"),
    )
    wiz = JobEditorWizard(reg, initial_job=reg.load("편집대상"))
    # 매핑 확정 세션 상태를 직접 구성(위저드 통과 대신 accept 전제 충족).
    wiz.template_path = "/t.hwpx"
    wiz.model = _model()
    for i, row in enumerate(wiz.model.rows):
        if row.template_field == "공고명":
            wiz.model.set_sources(i, ["bidNtceNm"])
    wiz.model.confirm_all()
    wiz._save_page.ed_name.setText("편집대상")
    wiz.accept()

    saved = reg.load("편집대상")
    assert saved.last_run_at == "2026-07-01T09:00:00"  # 사용 메타 이월


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


def _run_view_with_data(tmp_path):
    """집행 화면 + 가짜 데이터소스(빈값 1필드 포함) — 다이얼로그 없이 직접 겨눔."""
    from hwpxfiller.core.job import Job
    from hwpxfiller.core.mapping import FieldMapping, MappingProfile
    from hwpxfiller.gui.run_view import RunView

    template = tmp_path / "t.hwpx"
    template.write_bytes(b"dummy")  # 존재 검사 통과용(가짜 워커라 열지 않음)
    job = Job(
        name="집행",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", sources=["bidNtceNm"]),
            FieldMapping(template_field="추정가격", sources=["presmptPrce"]),
        ]),
        filename_pattern="doc-{{공고명}}",
    )

    class _Src:
        def records(self):
            return [
                {"bidNtceNm": "가", "presmptPrce": ""},
                {"bidNtceNm": "나", "presmptPrce": "2000"},
            ]

        def fields(self):
            return ["bidNtceNm", "presmptPrce"]

    view = RunView(job)
    view.datasource = _Src()
    view.records = view.datasource.records()
    view.selector.set_records(view.records, job.filename_pattern)
    view.ed_out.setText(str(tmp_path / "out"))
    return view


def test_run_view_effective_template_switches_with_target_mode(qapp, tmp_path):
    """대상 문서 선택 — 신규=작업 템플릿, 누적=이전 출력. datasource 이음새 무관."""
    view = _run_view_with_data(tmp_path)
    assert view._effective_template() == view.job.template_path  # 기본 신규

    prev = tmp_path / "prev.hwpx"
    prev.write_bytes(b"dummy")
    view.rb_cont.setChecked(True)
    view._template_override = str(prev)
    assert view._effective_template() == str(prev)

    view.rb_new.setChecked(True)  # 신규 복귀 → override 해제
    assert view._template_override is None
    assert view._effective_template() == view.job.template_path


def test_run_view_cumulative_mode_requires_single_record(qapp, tmp_path, monkeypatch):
    """누적 v1 = 단건 게이트 — 2건 선택이면 생성 중단(배치 파일키 매칭은 파킹)."""
    from PySide6.QtWidgets import QMessageBox

    view = _run_view_with_data(tmp_path)
    prev = tmp_path / "prev.hwpx"
    prev.write_bytes(b"dummy")
    view.rb_cont.setChecked(True)
    view._template_override = str(prev)

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    assert len(view.selector.selected_indices()) == 2  # 기본 전체 선택
    view._on_generate()
    assert any("1건" in w for w in warnings)
    assert view._thread is None  # 워커 미기동


def test_run_view_blank_gate_injects_markers_on_confirm(qapp, tmp_path, monkeypatch):
    """능동 빈칸 게이트 — 문구에 필드·건수, 승인 시 워커 레코드에 표식 주입."""
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.gui import run_view as rv

    view = _run_view_with_data(tmp_path)

    questions = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: (questions.append(a[2]), QMessageBox.Yes)[1],
    )

    captured = {}

    class _FakeWorker(QObject):
        progress = Signal(int, int)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, template, records, out_dir, pattern):
            super().__init__()
            captured["template"] = template
            captured["records"] = records

        def run(self):
            pass

    monkeypatch.setattr(rv, "GenerateWorker", _FakeWorker)
    view._on_generate()
    try:
        assert questions and "빈칸 1필드" in questions[0] and "추정가격" in questions[0]
        assert captured["template"] == view.job.template_path
        recs = captured["records"]
        assert recs[0]["추정가격"] == "〘미입력·추정가격〙"  # 미충족 공란 → 표식
        assert recs[0]["공고명"] == "가"                    # 비빈 값 불변
        assert recs[1]["추정가격"] == "2000"
    finally:
        view._teardown_thread()


# ------------------------------------------------------------------ 앱 A(diff)
def _diff_window_for_test(tmp_path, monkeypatch):
    """실패 모달 즉시 fail + QSettings 를 임시 파일로(사용자 설정 오염 방지)한 창."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    from hwpxdiff.app import DiffReviewWindow

    # 실패 경로의 모달은 offscreen 에서 exec 루프로 영원히 블록 — 행 대신 즉시 실패.
    monkeypatch.setattr(
        QMessageBox, "critical",
        lambda *a, **k: pytest.fail(f"비교 실패 다이얼로그가 떴다: {a[2] if len(a) > 2 else a}"),
    )
    win = DiffReviewWindow()
    win._settings = QSettings(str(tmp_path / "recent.ini"), QSettings.IniFormat)
    return win


def test_diff_window_compares_real_corpus_and_binds_groups(qapp, tmp_path, monkeypatch):
    """앱 A 단일 화면 — 실코퍼스 비교가 그룹 리스트·전문 뷰에 바인딩되고 클릭 이동이 돈다."""
    from pathlib import Path

    from PySide6.QtCore import Qt

    from hwpxdiff.app import _group_changes

    corpus = Path(__file__).parent / "corpus" / "real"
    win = _diff_window_for_test(tmp_path, monkeypatch)
    assert not win.btn_compare.isEnabled()  # 판본 선택 전

    win.ed_old.setText(str(corpus / "spec_revision_2025.hwpx"))
    win.ed_new.setText(str(corpus / "spec_revision_2026.hwpx"))
    win._on_compare()

    assert win.result is not None
    assert win.items.rowCount() == len(_group_changes(win.result.changes)) > 0
    # 전문 뷰 계약: equal 원문이 실제로 포함된다(본문 맥락 보존).
    assert len(win.result.rows) > len(win.result.changes)
    # 클릭 이동 계약: 각 그룹의 표적(Qt.UserRole == 첫 Change.seq)이 뷰 앵커로 실재.
    # scrollToAnchor 는 없는 앵커를 조용히 무시하므로, 표적 실재를 직접 못박는다.
    for r in range(win.items.rowCount()):
        seq = win.items.item(r, 0).data(Qt.UserRole)
        assert f"<a name='chg-{seq}'></a>" in win._html, f"행 {r}: 앵커 chg-{seq} 없음"
    win.items.selectRow(0)  # 선택 시그널 경로가 예외 없이 동작


def test_diff_visible_predicate_headless():
    """그룹 행 표시 판정 — renumber 는 전용 토글, 나머지는 종류(kind) 체크."""
    from hwpxdiff.app import _visible

    assert _visible("added", {"added"}, False)
    assert not _visible("added", set(), False)
    assert not _visible("renumber", {"renumber"}, False)  # 종류 체크가 아니라 토글만 따름
    assert _visible("renumber", set(), True)


def test_group_changes_merges_adjacent_same_kind():
    """인접(연속 seq)·같은 종류 변경은 리스트 1행으로 — 파편화 완화(순수 함수)."""
    from hwpxdiff.diff import Change
    from hwpxdiff.app import _group_changes

    chs = [
        Change(0, "changed", "paragraph", {}, "본문 1 · 문단 3", "a", "b"),
        Change(1, "changed", "paragraph", {}, "본문 1 · 문단 4", "c", "d"),
        Change(2, "added", "paragraph", {}, "본문 1 · 문단 5", "", "e"),
        Change(4, "changed", "paragraph", {}, "본문 1 · 문단 9", "f", "g"),  # seq 갭 → 새 그룹
    ]
    gs = _group_changes(chs)
    assert [(g.kind, len(g.seqs)) for g in gs] == [
        ("changed", 2), ("added", 1), ("changed", 1)
    ]
    assert gs[0].seqs == [0, 1] and "연속 2건" in gs[0].detail
    assert gs[0].label == "본문 1 · 문단 3"  # 그룹 라벨 = 첫 변경 위치


def test_coalesce_ops_absorbs_short_equal_between_changes():
    """변경 사이 한두 글자 equal 은 흡수, 낱말 경계(선두/후미/공백)는 보존."""
    from hwpxdiff.diff import WordOp
    from hwpxdiff.app import _coalesce_ops

    ops = [
        WordOp("equal", old="제"),
        WordOp("replace", old="3", new="4"),
        WordOp("equal", old="조"),
        WordOp("replace", old="갑", new="을"),
        WordOp("equal", old=" 이하 같다"),
    ]
    out = _coalesce_ops(ops)
    assert [o.op for o in out] == ["equal", "replace", "equal"]
    assert out[1].old == "3조갑" and out[1].new == "4조을"

    # 공백 equal 은 낱말 경계 — 흡수하지 않는다.
    ops2 = [
        WordOp("replace", old="가", new="나"),
        WordOp("equal", old=" "),
        WordOp("replace", old="다", new="라"),
    ]
    assert [o.op for o in _coalesce_ops(ops2)] == ["replace", "equal", "replace"]


def test_diff_kind_filter_and_renumber_toggle(qapp, tmp_path, monkeypatch):
    """종류 필터(추가/삭제/변경 3종 고정) — 기본: 전부 표시 + renumber 숨김(개수는 노출)."""
    from pathlib import Path

    corpus = Path(__file__).parent / "corpus" / "real"
    win = _diff_window_for_test(tmp_path, monkeypatch)
    win.ed_old.setText(str(corpus / "spec_revision_2025.hwpx"))
    win.ed_new.setText(str(corpus / "spec_revision_2026.hwpx"))
    win._on_compare()

    assert set(win._filter_checks) == {"added", "removed", "changed"}  # 세분 범주 없음
    groups = win._groups
    renumber_rows = [r for r, g in enumerate(groups) if g.kind == "renumber"]
    hidden = [r for r in range(win.items.rowCount()) if win.items.isRowHidden(r)]
    assert hidden == renumber_rows  # 기본: renumber 만 숨김
    if renumber_rows:
        assert "건 표시" in win.chk_renumber.text()  # 조용히 버리지 않음(개수 노출)
        win.chk_renumber.setChecked(True)
        assert not any(win.items.isRowHidden(r) for r in renumber_rows)

    # 특정 종류 해제 → 해당 그룹만 추가로 숨김.
    win._filter_checks["changed"].setChecked(False)
    for r, g in enumerate(groups):
        if g.kind == "changed":
            assert win.items.isRowHidden(r)

    # 판본 변경 → 결과·리스트·토글 라벨 무효화.
    win._invalidate_result("변경")
    assert win.items.rowCount() == 0 and win._html == ""
    assert win.chk_renumber.text() == "번호변경 표시"


def test_diff_doc_view_renders_full_text_side_by_side(qapp, tmp_path, monkeypatch):
    """전문 뷰 — equal 원문이 좌우 동일하게, 변경은 구판 del/신판 ins 로 갈라 렌더."""
    from hwpxdiff.diff import DocRow, WordOp
    from hwpxdiff.app import _render_doc_html

    rows = [
        DocRow("equal", "paragraph", "본문 1 · 문단 1", "서문 그대로", "서문 그대로"),
        DocRow("changed", "paragraph", "본문 1 · 문단 2", "요율 3%", "요율 3.5%",
               [WordOp("equal", old="요율 "), WordOp("replace", old="3", new="3.5"),
                WordOp("equal", old="%")], seq=0),
        DocRow("added", "paragraph", "본문 1 · 문단 3", "", "신설 조항", seq=1),
    ]
    html_text = _render_doc_html(rows)
    assert html_text.count("서문 그대로") == 2          # equal = 좌우 모두 원문
    assert "<del>3</del>" in html_text                  # 구판 측 삭제 강조
    assert "<ins>3.5</ins>" in html_text                # 신판 측 삽입 강조
    assert "<a name='chg-0'></a>" in html_text          # 변경 행 앵커
    assert "신설 조항" in html_text and "<a name='chg-1'></a>" in html_text


def test_diff_ingest_paths_and_recent_pairs(qapp, tmp_path):
    """DnD/최근 목록 공용 투입 — 2개=구→신, 1개=빈 칸 우선, 비-hwpx 무시, 결과 무효화."""
    from PySide6.QtCore import QSettings

    from hwpxdiff.app import DiffReviewWindow

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
    """리스트 배지색 = 코어 KIND_COLORS — 팔레트 단일 출처 계약(전문 뷰 표식과 공유)."""
    from pathlib import Path

    from hwpxdiff.diff import KIND_COLORS

    corpus = Path(__file__).parent / "corpus" / "real"
    win = _diff_window_for_test(tmp_path, monkeypatch)
    win.ed_old.setText(str(corpus / "spec_revision_2025.hwpx"))
    win.ed_new.setText(str(corpus / "spec_revision_2026.hwpx"))
    win._on_compare()

    assert win.items.rowCount() > 0
    for r, g in enumerate(win._groups):
        cell = win.items.item(r, 0)
        assert cell.background().color().name() == KIND_COLORS[g.kind], (
            f"행 {r} ({g.kind}): 배지색이 코어 팔레트와 다름"
        )
