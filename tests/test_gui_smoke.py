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

from hwpxfiller.core.schema import FieldSpec, TemplateSchema  # noqa: E402
from hwpxfiller.data.nara import NaraStdDataSource  # noqa: E402
from hwpxfiller.gui.mapping_state import MappingModel  # noqa: E402

# 어휘는 이제 소스가 소유한다(코어 아님) — V1 승격 후 새 출처.
NARA_ALIASES = NaraStdDataSource.field_labels()


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


def test_mapping_table_renders_model_and_emits_complete_changed(qapp, monkeypatch):
    """UD-05 — '모두 확정'은 내용 행만 즉시 확정하고, 미매칭 빈 행의 의도적 비움
    승격은 이름 재진술 확인을 거친다. '모두 해제'는 확정본이 있으면 파괴 확인 경유."""
    from hwpxfiller.gui import mapping_table as mt
    from hwpxfiller.gui.mapping_table import MappingTable

    model = _model()  # 공고명·개찰일시(내용) + 미매칭필드qq(빈)
    table = MappingTable()
    table.set_model(model, {"bidNtceNm": "테스트 공고", "opengDate": "2026-06-15"})
    assert table.table.rowCount() == len(model.rows)
    blank = next(r for r in model.rows if r.template_field == "미매칭필드qq")

    emitted = []
    table.completeChanged.connect(lambda: emitted.append(True))

    # 비움 확정 거부 → 내용 행만 확정, 미매칭 빈 행 미확정(게이트 닫힘).
    monkeypatch.setattr(mt, "confirm_destructive", lambda *a, **k: False)
    table.btn_confirm_all.click()
    assert emitted
    assert not model.is_complete()
    assert not blank.confirmed
    assert all(r.confirmed for r in model.rows if r.has_content())

    # 비움 확정 수락 → 미매칭 빈 행도 의도적 비움으로 확정 → 완료.
    monkeypatch.setattr(mt, "confirm_destructive", lambda *a, **k: True)
    table.btn_confirm_all.click()
    assert model.is_complete()

    # '모두 해제' 거부 → 확정 유지(무확인 파기 없음).
    monkeypatch.setattr(mt, "confirm_destructive", lambda *a, **k: False)
    table.btn_unconfirm_all.click()
    assert model.is_complete()

    # '모두 해제' 수락 → 전 행 해제.
    monkeypatch.setattr(mt, "confirm_destructive", lambda *a, **k: True)
    table.btn_unconfirm_all.click()
    assert not model.is_complete()
    assert all(not r.confirmed for r in model.rows)


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
    fmtc = table.cell_control(ri, _COL_FORMAT)
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
    from hwpxfiller.gui.home import JobCard, JobListHome

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
    assert isinstance(card, JobCard)
    joined = " ".join(lbl.text() for lbl in card.findChildren(QLabel))
    assert "카드작업" in joined
    assert "필드 0개" in joined          # 메타 노출
    assert "아직 실행 안 함" in joined    # 미실행 상태
    assert "템플릿 없음" in joined        # 부재 템플릿 선고지


def _saved_job(tmp_path):
    """편집 프리로드 테스트용 저장 작업 — 매핑 2행(공고명·추정가격) 확정본."""
    from hwpxfiller.core.job import Job, JobRegistry
    from hwpxfiller.gui.mapping_state import MappingModel

    model = _model()
    for i, row in enumerate(model.rows):
        if row.template_field == "공고명":
            model.set_source(i, "bidNtceNm")
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
    assert rows["미매칭필드qq"].confirmed      # 과거 비움 확정 = blank 선언으로 복원
    assert rows["미매칭필드qq"].is_empty_confirmed()
    assert "확정" in mapping_page.lbl_progress.text()


def test_save_page_prefills_default_pattern_and_gates_empty(qapp, tmp_path):
    """RC-20 — 프리필은 단일 출처 상수, 빈 패턴은 isComplete 게이트가 차단한다."""
    from hwpxfiller.core.job import DEFAULT_FILENAME_PATTERN, JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    wiz = JobEditorWizard(JobRegistry(tmp_path))
    page = wiz.page(wiz.pageIds()[-1])
    assert page.ed_pattern.text() == DEFAULT_FILENAME_PATTERN  # 프리필 = 단일 출처
    wiz.model = _model()
    wiz.model.confirm_all()
    page.ed_name.setText("작업")
    assert page.isComplete()
    page.ed_pattern.setText("   ")            # 공백뿐인 패턴 = 빈 패턴
    assert not page.isComplete()


def test_editor_accept_blocks_empty_pattern_no_silent_fallback(qapp, tmp_path, monkeypatch):
    """RC-20 — 빈 패턴 저장 시도는 화면에 없던 'output-{{ID}}' 무고지 폴백 대신 경고+차단."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    reg = JobRegistry(tmp_path)
    wiz = JobEditorWizard(reg)
    wiz.template_path = "/t.hwpx"
    wiz.model = _model()
    for i, row in enumerate(wiz.model.rows):
        if row.template_field == "공고명":
            wiz.model.set_source(i, "bidNtceNm")
    wiz.model.confirm_all()
    wiz._save_page.ed_name.setText("빈패턴작업")
    wiz._save_page.ed_pattern.setText("")
    warned: "list[str]" = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    wiz.accept()
    assert warned and "파일명 패턴" in warned[-1]
    assert not reg.exists("빈패턴작업")       # 조용한 폴백 저장이 일어나지 않았다


def test_editor_edit_mode_accept_same_name_no_prompt(qapp, tmp_path, monkeypatch):
    """편집 모드 자기 자신 재저장은 덮어쓰기 프롬프트 없음 + last_run_at 이월."""
    from hwpxfiller.gui import job_editor as je
    from hwpxfiller.gui.job_editor import JobEditorWizard

    reg, job = _saved_job(tmp_path)
    job.last_run_at = "2026-07-01T09:00:00"
    reg.save(job)

    monkeypatch.setattr(
        je, "confirm_destructive",
        lambda *a, **k: pytest.fail("자기 자신 갱신에 덮어쓰기 프롬프트가 떴다"),
    )
    wiz = JobEditorWizard(reg, initial_job=reg.load("편집대상"))
    # 매핑 확정 세션 상태를 직접 구성(위저드 통과 대신 accept 전제 충족).
    wiz.template_path = "/t.hwpx"
    wiz.model = _model()
    for i, row in enumerate(wiz.model.rows):
        if row.template_field == "공고명":
            wiz.model.set_source(i, "bidNtceNm")
    wiz.model.confirm_all()
    wiz._save_page.ed_name.setText("편집대상")
    wiz.accept()

    saved = reg.load("편집대상")
    assert saved.last_run_at == "2026-07-01T09:00:00"  # 사용 메타 이월


def test_app_controller_records_last_run(qapp, tmp_path, monkeypatch):
    """성공 실행(run_finished) → last_run_at 저장·홈 갱신. RunView 는 레지스트리 무지."""
    from hwpxfiller.core.job import Job, JobRegistry
    from hwpxfiller.gui.app import AppController

    reg = JobRegistry(tmp_path)
    reg.save(Job(name="실행기록", template_path="/t.hwpx"))
    ctrl = AppController(reg)

    class _Batch:
        succeeded = 2

    ctrl._record_run("실행기록", _Batch())
    assert reg.load("실행기록").last_run_at != ""

    class _Failed:
        succeeded = 0

    before = reg.load("실행기록").last_run_at
    ctrl._record_run("실행기록", _Failed())
    assert reg.load("실행기록").last_run_at == before  # 실패 실행은 갱신 안 함


# ------------------------------------------------------- 템플릿 관리 워크숍(C5)
def _hwpx_pkg(section_inner: str):
    from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

    hp = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    hs = "http://www.hancom.co.kr/hwpml/2011/section"
    sec = f'<hs:sec xmlns:hs="{hs}" xmlns:hp="{hp}">{section_inner}</hs:sec>'.encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries["Contents/section0.xml"] = sec
    return pkg


def _P(inner: str):
    return f"<hp:p><hp:run><hp:t>{inner}</hp:t></hp:run></hp:p>"


def test_template_manager_panel_renders_badges_and_gated_actions(qapp, tmp_path):
    """관리 패널이 라이브러리 행을 카드로 렌더하고 상태별 게이트 버튼을 배선한다."""
    from PySide6.QtWidgets import QPushButton

    from hwpxfiller.core.authoring import compile_document
    from hwpxfiller.gui.template_manager import TemplateCard, TemplateManagerPanel

    _hwpx_pkg(_P("계약명: {{계약명}}")).save(str(tmp_path / "raw.hwpx"))
    pkg, _ = compile_document(_hwpx_pkg(_P("계약명: {{계약명}}")))
    pkg.save(str(tmp_path / "comp.hwpx"))

    panel = TemplateManagerPanel(library_dir=tmp_path)
    assert panel.list.count() == 2
    by_name = {}
    for i in range(panel.list.count()):
        it = panel.list.item(i)
        card = panel.list.itemWidget(it)
        assert isinstance(card, TemplateCard)
        by_name[it.text()] = card

    raw_labels = [b.text() for b in by_name["raw.hwpx"].findChildren(QPushButton)]
    comp_labels = [b.text() for b in by_name["comp.hwpx"].findChildren(QPushButton)]
    assert raw_labels == ["누름틀 변환"]
    assert comp_labels == ["미리보기", "작업 만들기"]


def test_template_manager_compile_dry_run_then_apply(qapp, tmp_path, monkeypatch):
    """컴파일 버튼 = dry-run 확인 → 거절이면 무변형, 확정이면 컴파일·상태 진행(명시성)."""
    from hwpxfiller.core.template_status import CompileState, compile_status
    from hwpxfiller.gui import template_manager as tm
    from hwpxfiller.gui.template_manager import TemplateManagerPanel

    path = tmp_path / "raw.hwpx"
    _hwpx_pkg(_P("계약명: {{계약명}}")).save(str(path))
    panel = TemplateManagerPanel(library_dir=tmp_path)
    before = path.read_bytes()

    # 확인 거절 → dry-run 만, 파일 무변형(파괴 확인은 공용 헬퍼 경유 — RC-15).
    monkeypatch.setattr(tm, "confirm_destructive", lambda *a, **k: False)
    panel._dispatch("compile", str(path))
    assert path.read_bytes() == before
    assert compile_status(str(path)).state == CompileState.RAW

    # 확인 수락 → 컴파일·저장, RAW → COMPILED.
    monkeypatch.setattr(tm, "confirm_destructive", lambda *a, **k: True)
    panel._dispatch("compile", str(path))
    assert compile_status(str(path)).state == CompileState.COMPILED
    assert panel.list.count() == 1  # 재렌더됨


def test_home_template_button_emits_manage_templates(qapp, tmp_path):
    """홈 헤더 [템플릿 관리] 버튼 = manage_templates_requested — 워크숍 진입점(RC-04)."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.home import JobListHome

    home = JobListHome(JobRegistry(tmp_path))
    emitted = []
    home.manage_templates_requested.connect(lambda: emitted.append(True))
    home.btn_templates.click()
    assert emitted


def test_app_controller_wires_all_home_routes_via_signal_emit(qapp, tmp_path, monkeypatch):
    """배선 완결성 전수(RC-04) — 사용자 경로(홈 시그널 emit) 기점으로 전 라우트 검증.

    과거 hasattr 전방호환 가드 + 내부 메서드 직접 호출 테스트가 홈 측 시그널 미착지를
    3중으로 은폐했다 — 여기서는 emit 이 실제로 자식 창을 여는지 라우트별로 못박는다
    (배선이 빠지면 AppController 생성 자체가 AttributeError 로 시끄럽게 실패).
    """
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))  # 표준 루트 전부 임시 홈으로
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.app import AppController
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel
    from hwpxfiller.gui.job_editor import JobEditorWizard
    from hwpxfiller.gui.matrix_view import MatrixRunView
    from hwpxfiller.gui.template_manager import TemplateManagerPanel
    from hwpxfiller.gui.txt_view import TxtDraftView
    from hwpxfiller.gui.vocab_workbench import VocabWorkbenchPanel

    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    routes = [
        ("new_job_requested", JobEditorWizard),
        ("new_txt_requested", TxtDraftView),
        ("manage_templates_requested", TemplateManagerPanel),
        ("manage_pool_requested", DatasetPoolPanel),
        ("matrix_run_requested", MatrixRunView),
        ("manage_vocab_requested", VocabWorkbenchPanel),
    ]
    for sig, cls in routes:
        getattr(ctrl.home, sig).emit()
        opened = [c for c in ctrl._children if isinstance(c, cls)]
        assert opened, f"{sig} emit 이 {cls.__name__} 을(를) 열지 못했다(배선 부재)"


def test_app_controller_boots_single_window_shell_with_home_page(qapp, tmp_path, monkeypatch):
    """단일창 셸 기동(ST-01, SHELL_DESIGN S3) — 홈이 셸 스택의 첫 페이지로 임베드된다.

    홈은 더 이상 최상위 창이 아니다: 셸(레일+스택)이 유일한 창이고, 현재 위치는
    current_key() 로 노출된다(레일 하이라이트의 테스트 seam).
    """
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.app import AppController

    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    assert ctrl.shell.current_key() == "home"
    assert ctrl.shell.stack.currentWidget() is ctrl.home
    assert ctrl.home.parent() is not None  # 임베드됨 — 독립 창 아님


def test_pool_register_overwrite_is_gated(qapp, tmp_path, monkeypatch):
    """동명 데이터셋 등록은 확인 게이트를 거친다(ST-09) — 파이프라인 저장과 대칭.

    ``_confirm_pool_overwrite``: 신규 이름은 즉시 통과, 동명은 ``confirm_destructive``
    결과를 반영(취소=차단). VM.register_* 는 exists 무검사 save 라, 이 위젯 게이트가
    유일한 무통보 덮어쓰기 방어다(durable 참조 소실 방지·confirm-or-alarm).
    """
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.core.dataset_pool import DatasetPoolRegistry
    from hwpxfiller.gui import dataset_pool_panel as dpp

    panel = dpp.DatasetPoolPanel(DatasetPoolRegistry(tmp_path / "pool"))
    panel.vm.register_excel("공고자료", "C:/x/first.csv")
    assert panel.vm.registry.exists("공고자료")

    assert panel._confirm_pool_overwrite("다른이름") is True  # 신규 → 게이트 없이 통과
    monkeypatch.setattr(dpp, "confirm_destructive", lambda *a, **k: False)
    assert panel._confirm_pool_overwrite("공고자료") is False  # 동명+취소 → 차단
    monkeypatch.setattr(dpp, "confirm_destructive", lambda *a, **k: True)
    assert panel._confirm_pool_overwrite("공고자료") is True  # 동명+확정 → 진행 허용


def test_window_geometry_persists_across_sessions(qapp, tmp_path, monkeypatch):
    """창 크기·위치가 세션 간 지속된다(ST-11) — HWPXFILLER_HOME INI 로 사용자 설정 비접촉.

    save→restore 왕복은 지오메트리 바이트가 동일함으로 확인(스크린 비의존). 미저장 키는
    default_size 로 폴백한다(첫 실행·손상 값).
    """
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from PySide6.QtWidgets import QMainWindow

    from hwpxfiller.gui.view_helpers import _ui_settings, restore_geometry, save_geometry

    # 저장: 창 지오메트리 바이트가 설정에 그대로 기록된다(스크린 비의존·결정적).
    w1 = QMainWindow()
    w1.resize(1111, 777)
    save_geometry(w1, "probe")
    assert _ui_settings().value("geometry/probe") == w1.saveGeometry()

    # 복원: 저장 데이터가 있으면 default_size 를 무시하고 복원한다(프레임 보정은 허용).
    w2 = QMainWindow()
    w2.resize(200, 200)
    restore_geometry(w2, "probe", default_size=(640, 480))
    assert (w2.width(), w2.height()) != (640, 480)  # 기본 폴백이 아니라 복원됨

    # 미저장 키: default_size 로 폴백(첫 실행·손상 값).
    w3 = QMainWindow()
    restore_geometry(w3, "unseen", default_size=(640, 480))
    assert (w3.width(), w3.height()) == (640, 480)


def test_wizard_discard_guard_confirms_when_mapping_confirmed(qapp, tmp_path, monkeypatch):
    """위저드 이탈이 확정 매핑을 무확인 폐기하지 못한다(ST-08).

    model 미도달·확정 0행이면 잃을 게 없어 통과, 확정 행이 있으면 confirm_destructive
    결과를 반영(취소=폐기 안 함). reject/closeEvent 가 이 술어를 공유한다.
    """
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui import job_editor as je

    wiz = je.JobEditorWizard(JobRegistry(tmp_path / "jobs"))
    assert wiz._confirm_discard() is True  # model None → 통과

    class _Model:
        def confirmed_count(self):
            return 2

    wiz.model = _Model()
    monkeypatch.setattr(je, "confirm_destructive", lambda *a, **k: False)
    assert wiz._confirm_discard() is False  # 확정 행 + 취소 → 폐기 차단
    monkeypatch.setattr(je, "confirm_destructive", lambda *a, **k: True)
    assert wiz._confirm_discard() is True  # 확정 → 폐기 허용


def test_run_view_leave_while_running_confirms(qapp, monkeypatch):
    """생성 진행 중 이탈(can_leave, SHELL_DESIGN D8)은 협조적 취소 확인을 거친다(ST-21).

    거부 시 이탈 무산·생성 계속, 수락 시 취소 요청+teardown(R4 — QThread 누수 방지).
    셸 페이지 전환·셸 닫기·run 슬롯 교체가 전부 이 단일 술어를 공유한다."""
    from hwpxfiller.core.job import Job
    from hwpxfiller.gui import run_view as rv

    view = rv.RunView(Job(name="실행중", template_path="/t.hwpx", filename_pattern="d-{{ID}}"))
    view._running = True
    monkeypatch.setattr(rv, "confirm_destructive", lambda *a, **k: False)
    assert view.can_leave() is False  # 확인 취소 → 이탈 무산
    assert view._running is True  # 생성 계속(중단 안 함)
    monkeypatch.setattr(rv, "confirm_destructive", lambda *a, **k: True)
    assert view.can_leave() is True  # 수락 → 취소 요청+teardown
    assert view._running is False


def test_accessible_names_and_buddies_present(qapp, tmp_path, monkeypatch):
    """글리프 버튼·폼 입력에 접근가능 이름/버디가 설정된다(ST-06/07) + 상태 통지 헬퍼(ST-18)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from PySide6.QtWidgets import QLabel

    from hwpxfiller.core.text_registry import TextTemplateRegistry
    from hwpxfiller.gui.job_editor import SaveJobPage
    from hwpxfiller.gui.txt_view import TxtDraftView
    from hwpxfiller.gui.view_helpers import announce_status

    tv = TxtDraftView(TextTemplateRegistry(tmp_path / "txt"))
    assert tv.btn_prev.accessibleName() == "이전 레코드"  # ST-06
    assert tv.btn_next.accessibleName() == "다음 레코드"

    page = SaveJobPage()
    assert page.ed_name.accessibleName() == "작업 이름"  # ST-07
    assert page.ed_pattern.accessibleName() == "파일명 패턴"

    lbl = QLabel()
    announce_status(lbl, "등록 완료")  # ST-18 — 텍스트 설정 + Alert(리더 없으면 no-op)
    assert lbl.text() == "등록 완료"


def test_managed_windows_are_singletons(qapp, tmp_path, monkeypatch):
    """관리 능력 재요청은 새 인스턴스를 만들지 않는다 — 셸 스택 페이지 재사용이
    구 ST-10 싱글턴을 구조로 승계한다(ST-01, SHELL_DESIGN §3)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.app import AppController
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel

    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    ctrl.home.manage_pool_requested.emit()
    ctrl.home.manage_pool_requested.emit()  # 두 번째 요청 → 중복 생성 금지
    pools = [c for c in ctrl._children if isinstance(c, DatasetPoolPanel)]
    assert len(pools) == 1


def test_managed_page_reentry_refreshes_and_moves_rail(qapp, tmp_path, monkeypatch):
    """관리 페이지 재진입 시 refresh 로 은닉 중 스테일 해소(SHELL_DESIGN D6) +
    현재 위치 표지(current_key)가 라우트를 따라 이동한다(ST-01)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.app import AppController

    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    ctrl.home.manage_pool_requested.emit()
    assert ctrl.shell.current_key() == "pool"
    pool_page = ctrl.shell.stack.currentWidget()
    calls = []
    monkeypatch.setattr(pool_page, "refresh", lambda: calls.append(1))
    ctrl.shell.go_home()
    assert ctrl.shell.current_key() == "home"
    ctrl.home.manage_pool_requested.emit()  # 재진입 → refresh 1회
    assert ctrl.shell.current_key() == "pool"
    assert calls == [1]


def test_editor_wizard_is_application_modal_window(qapp, tmp_path, monkeypatch):
    """에디터 위저드는 임베드하지 않는 유일한 표면 — 애플리케이션 모달 창(SHELL_DESIGN D3·D4).

    모달성이 동일 작업 동시 편집(last-save-wins)을 상위 호환으로 차단한다(구 ST-10
    editor:{name} 싱글턴 대체). exec() 는 어디서도 호출하지 않는다(offscreen hang, R1)
    — 여기서도 속성만 검증한다.
    """
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from PySide6.QtCore import Qt

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.app import AppController
    from hwpxfiller.gui.job_editor import JobEditorWizard

    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    ctrl.home.new_job_requested.emit()
    wiz = next(c for c in ctrl._children if isinstance(c, JobEditorWizard))
    assert wiz.isWindow()  # 임베드 아님 — 독립 창 유지
    assert wiz.windowModality() == Qt.ApplicationModal
    assert wiz.parent() is None  # parent 무부여(R5) — 수명은 _track 소유
    wiz.close()


def test_run_route_embeds_and_replaces_in_run_slot(qapp, tmp_path, monkeypatch):
    """실행 라우트가 run 파라미터 슬롯에 임베드된다(ST-01, SHELL_DESIGN §2) —
    새 최상위 창 0개 · 같은 작업 재사용 · 다른 작업 교체."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.core.job import Job, JobRegistry
    from hwpxfiller.gui.app import AppController
    from hwpxfiller.gui.run_view import RunView

    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="보고서", template_path="/t.hwpx", filename_pattern="a-{{ID}}"))
    reg.save(Job(name="계약서", template_path="/t.hwpx", filename_pattern="b-{{ID}}"))
    ctrl = AppController(reg)
    before = len(QApplication.topLevelWidgets())
    ctrl.home.run_job_requested.emit("보고서")
    assert ctrl.shell.current_key() == "run"
    first = ctrl.shell.stack.currentWidget()
    assert isinstance(first, RunView)
    assert len(QApplication.topLevelWidgets()) == before  # 인-윈도 전환 — 새 창 없음
    ctrl.home.run_job_requested.emit("보고서")  # 같은 작업 재요청 → 재사용
    assert ctrl.shell.stack.currentWidget() is first
    ctrl.home.run_job_requested.emit("계약서")  # 다른 작업 → 슬롯 교체
    second = ctrl.shell.stack.currentWidget()
    assert isinstance(second, RunView)
    assert second is not first
    assert second.job.name == "계약서"


def test_txt_page_state_preserved_across_navigation(qapp, tmp_path, monkeypatch):
    """txt 페이지 은닉 보존(SHELL_DESIGN D6) — 전환 후 복귀해도 같은 인스턴스."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.app import AppController

    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    ctrl.home.new_txt_requested.emit()
    assert ctrl.shell.current_key() == "txt"
    txt = ctrl.shell.stack.currentWidget()
    ctrl.shell.go_home()
    ctrl.home.new_txt_requested.emit()  # 복귀 — 새 인스턴스 아님(상태 보존)
    assert ctrl.shell.stack.currentWidget() is txt


def test_matrix_page_leave_while_running_gated(qapp, tmp_path, monkeypatch):
    """일괄 생성 진행 중 셸 이탈은 협조적 취소 확인을 거친다(ST-21 → SHELL_DESIGN D8)
    — 거부 시 페이지 유지, 수락 시 취소+teardown 후 전환."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui import matrix_view as mv
    from hwpxfiller.gui.app import AppController

    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    ctrl.home.matrix_run_requested.emit()
    assert ctrl.shell.current_key() == "matrix"
    view = ctrl.shell.stack.currentWidget()
    view._running = True
    monkeypatch.setattr(mv, "confirm_destructive", lambda *a, **k: False)
    ctrl.shell.go_home()
    assert ctrl.shell.current_key() == "matrix"  # 이탈 거부 → 전환 무산
    assert view._running is True
    monkeypatch.setattr(mv, "confirm_destructive", lambda *a, **k: True)
    ctrl.shell.go_home()
    assert ctrl.shell.current_key() == "home"  # 수락 → 취소·teardown 후 전환
    assert view._running is False


def test_keyboard_affordances_present(qapp, tmp_path, monkeypatch):
    """니모닉(&)·F5 새로고침 단축키가 배선된다(ST-12)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from PySide6.QtGui import QShortcut
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.home import JobListHome

    home = JobListHome(JobRegistry(tmp_path / "jobs"))
    assert "&" in home.btn_new.text()  # Alt 니모닉
    assert "&" in home.btn_templates.text()
    seqs = [sc.key().toString() for sc in home.findChildren(QShortcut)]
    assert "F5" in seqs  # F5 → refresh


def test_busy_cursor_sets_and_restores(qapp):
    """무거운 동기 작업 동안 대기 커서를 표시하고, 예외에도 반드시 복원한다(ST-16)."""
    from PySide6.QtWidgets import QApplication

    from hwpxfiller.gui.view_helpers import busy_cursor

    assert QApplication.overrideCursor() is None
    with busy_cursor():
        assert QApplication.overrideCursor() is not None
    assert QApplication.overrideCursor() is None
    try:
        with busy_cursor():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert QApplication.overrideCursor() is None  # finally 복원


def test_nara_progress_visible_only_while_busy(qapp):
    """나라 취득 진행바는 취득 중에만 보인다(ST-17)."""
    from hwpxfiller.data.secret_store import NARA_SERVICE_KEY_NAME, MemorySecretStore
    from hwpxfiller.gui.nara_view import NaraAcquireDialog

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "K"})
    dlg = NaraAcquireDialog(store=store, fetcher=lambda url: b"")
    assert dlg.progress.isVisibleTo(dlg) is False  # 초기 숨김
    dlg._set_busy(True)
    assert dlg.progress.isVisibleTo(dlg) is True
    dlg._set_busy(False)
    assert dlg.progress.isVisibleTo(dlg) is False


def test_describe_exception_shapes_common_errors(qapp):
    """예외를 유형별 사용자 문구로 성형한다(ST-20) — 미지 유형은 원문 보존."""
    import zipfile

    from hwpxfiller.gui.view_helpers import describe_exception

    assert "다른 프로그램" in describe_exception(PermissionError("x"))
    assert "찾을 수 없" in describe_exception(FileNotFoundError("x"))
    assert "손상" in describe_exception(zipfile.BadZipFile("x"))
    assert describe_exception(ValueError("고유메시지")) == "고유메시지"  # 미지 유형 원문


def test_template_manager_route_seeds_default_library_and_make_job(qapp, tmp_path, monkeypatch):
    """emit → 패널이 기본 라이브러리를 겨눔(RC-14) + '작업 만들기' → 템플릿 시드 에디터."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.core.template_status import default_templates_dir
    from hwpxfiller.gui.app import AppController
    from hwpxfiller.gui.job_editor import JobEditorWizard
    from hwpxfiller.gui.template_manager import TemplateManagerPanel

    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    ctrl.home.manage_templates_requested.emit()
    panels = [c for c in ctrl._children if isinstance(c, TemplateManagerPanel)]
    assert len(panels) == 1
    assert panels[0].vm.library_dir == default_templates_dir()  # 백지(None) 금지

    panels[0].make_job_requested.emit("/lib/tpl.hwpx")
    wizards = [c for c in ctrl._children if isinstance(c, JobEditorWizard)]
    assert len(wizards) == 1
    assert wizards[0].template_path == "/lib/tpl.hwpx"  # 세션에 시드됨


def test_open_editor_from_base_failure_is_loud_not_silent(qapp, tmp_path, monkeypatch):
    """베이스 로드 실패 → 침묵 no-op 이 아니라 경고 모달 + 위저드 미개방(RC-04)."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.app import AppController
    from hwpxfiller.gui.job_editor import JobEditorWizard

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    ctrl._open_editor_from_base("존재하지-않는-베이스")
    assert warnings and "존재하지-않는-베이스" in warnings[0]  # 시끄럽게 알림
    assert not [c for c in ctrl._children if isinstance(c, JobEditorWizard)]  # 창 미개방


def test_home_surfaces_corrupt_job_file_as_badge_row(qapp, tmp_path):
    """절단 .job.json → 홈이 죽지 않고 '손상됨' 배지 카드로 시끄럽게 노출(RC-05)."""
    from PySide6.QtWidgets import QLabel

    from hwpxfiller.core.job import Job, JobRegistry
    from hwpxfiller.gui.home import _CorruptJobCard, JobListHome

    reg = JobRegistry(tmp_path)
    reg.save(Job(name="정상작업", template_path="/t.hwpx"))
    (tmp_path / "절단.job.json").write_text('{"name": "절단", "template_pa', encoding="utf-8")

    home = JobListHome(reg)  # 생성이 JSONDecodeError 로 죽지 않는다(앱 시작 경로)
    texts = [home.list.item(i).text() for i in range(home.list.count())]
    assert "정상작업" in texts                      # 나머지 작업은 정상 표시
    assert "절단.job.json" in texts                 # 손상 행이 목록에 실재
    card = home.list.itemWidget(home.list.item(texts.index("절단.job.json")))
    assert isinstance(card, _CorruptJobCard)
    joined = " ".join(lbl.text() for lbl in card.findChildren(QLabel))
    assert "손상됨" in joined                        # 배지
    assert "절단.job.json" in joined                 # 원인 파일 지목
    assert home.stack.currentIndex() == 0            # 빈 상태 아님(목록 페이지)


def _home_with_ready_and_absent(tmp_path):
    """홈 + 실행 가능(컴파일된 실존 템플릿) '정상작업' + 실행 불가(부재) '부재작업'."""
    from hwpxfiller.core.authoring import compile_document
    from hwpxfiller.core.job import Job, JobRegistry
    from hwpxfiller.gui.home import JobListHome

    reg = JobRegistry(tmp_path)
    pkg, _ = compile_document(_hwpx_pkg(_P("계약명: {{계약명}}")))
    good = tmp_path / "good.hwpx"
    pkg.save(str(good))
    reg.save(Job(name="정상작업", template_path=str(good)))
    reg.save(Job(name="부재작업", template_path=str(tmp_path / "missing.hwpx")))
    return JobListHome(reg)


def test_home_double_click_shares_run_gate_with_button(qapp, tmp_path, monkeypatch):
    """UD-03 — 더블클릭이 버튼과 같은 게이트 공유: 실행 가능 행만 run_job_requested(작업명)
    방출, 실행 불가(부재) 행은 조용한 크래시 대신 시끄러운 사유 고지 + 무방출."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    home = _home_with_ready_and_absent(tmp_path)
    emitted: "list[str]" = []
    home.run_job_requested.connect(emitted.append)
    infos: "list[str]" = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a[2]))

    def _item(name):
        return home.list.findItems(name, Qt.MatchExactly)[0]

    home._on_job_double_click(_item("부재작업"))
    assert emitted == [] and infos          # 무방출 + 사유 고지(stderr 침묵 아님)
    home._on_job_double_click(_item("정상작업"))
    assert emitted == ["정상작업"]           # 실행 가능 행만 방출(파일명 아님)


def test_home_run_cta_enabled_and_emphasis_by_state(qapp, tmp_path):
    """UD-03/UD-22 — 실행 CTA 활성/강조가 badge_level 연동: 부재=비활성, 준비(ok)=활성 강조.

    강조는 화면 전역 primary(채움)가 아니라 카드 반복 액션용 보조 등급(emphasis=card, UD-22)
    — 카드 곱셈으로 primary 가 11개까지 번지던 것을 화면당 primary 1개 규율로 되돌린다.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    home = _home_with_ready_and_absent(tmp_path)

    def _run_btn(name):
        card = home.list.itemWidget(home.list.findItems(name, Qt.MatchExactly)[0])
        return next(b for b in card.findChildren(QPushButton) if b.text() == "실행")

    ready, absent = _run_btn("정상작업"), _run_btn("부재작업")
    # 준비(ok) = 활성 + 카드 보조 강조. 화면 전역 primary(채움)로 승격하지 않는다.
    assert ready.isEnabled() and ready.property("emphasis") == "card"
    assert not ready.property("primary")                     # 카드 곱셈 primary 금지(UD-22)
    assert not absent.isEnabled()                            # 부재 = 비활성(더블클릭도 차단)


def test_home_corrupt_card_offers_resolution_affordances(qapp, tmp_path):
    """UD-44 — 손상 카드에 [폴더 열기]·[삭제] 해소 동선 + 손상 파일 경로를 나르는 시그널."""
    from PySide6.QtWidgets import QPushButton

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.home import _CorruptJobCard, JobListHome

    reg = JobRegistry(tmp_path)
    bad = tmp_path / "절단.job.json"
    bad.write_text('{"name": "절단", "template_pa', encoding="utf-8")
    home = JobListHome(reg)

    card = None
    for i in range(home.list.count()):
        widget = home.list.itemWidget(home.list.item(i))
        if isinstance(widget, _CorruptJobCard):
            card = widget
    assert card is not None
    btns = {b.text(): b for b in card.findChildren(QPushButton)}
    assert "폴더 열기" in btns and "삭제" in btns
    assert btns["삭제"].property("level") == "danger"       # 파괴 등급 시각(정상 카드와 동일 어휘)

    reveal: "list[str]" = []
    dele: "list[str]" = []
    home.reveal_corrupt_requested.connect(reveal.append)
    home.delete_corrupt_requested.connect(dele.append)
    btns["폴더 열기"].click()
    btns["삭제"].click()
    assert reveal == [str(bad)] and dele == [str(bad)]      # 경로를 나른다


def test_open_run_guards_missing_job_loudly(qapp, tmp_path, monkeypatch):
    """UD-03 — _open_run 은 exists() 가드로 사라진 작업을 조용한 크래시 대신 경고 + 무개방."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui import run_view as rv
    from hwpxfiller.gui.app import AppController

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    warnings: "list[str]" = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    monkeypatch.setattr(
        rv, "RunView", lambda *a, **k: pytest.fail("사라진 작업에 RunView 를 열면 안 된다")
    )
    ctrl._open_run("없는작업")
    assert warnings and "없는작업" in warnings[0]  # 시끄럽게 알림, load 직행 크래시 아님


def test_app_resolves_corrupt_job_file(qapp, tmp_path, monkeypatch):
    """UD-44 — 컨트롤러가 손상 파일 해소: 폴더 열기 공용 유틸 호출, 확인 경유 삭제 후 새로고침."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui import batch_run, confirm
    from hwpxfiller.gui.app import AppController

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    jobs = tmp_path / "jobs"
    jobs.mkdir(parents=True)
    bad = jobs / "절단.job.json"
    bad.write_text('{"name": "절단", "template_pa', encoding="utf-8")
    ctrl = AppController(JobRegistry(jobs))

    opened: "list[str]" = []
    monkeypatch.setattr(batch_run, "open_folder", opened.append)
    ctrl._reveal_corrupt(str(bad))
    assert opened == [str(bad.parent)]                     # 폴더(부모) 열기

    monkeypatch.setattr(confirm, "confirm_destructive", lambda *a, **k: False)
    ctrl._delete_corrupt(str(bad))
    assert bad.exists()                                    # 확인 거부 → 잔존(무손상)

    monkeypatch.setattr(confirm, "confirm_destructive", lambda *a, **k: True)
    ctrl._delete_corrupt(str(bad))
    assert not bad.exists()                                # 확인 수락 → 삭제


def test_template_manager_empty_state_offers_folder_choice(qapp, tmp_path):
    """빈 라이브러리 → 백지가 아니라 빈상태 안내('폴더 없음' 구분) + 폴더 선택(RC-14)."""
    from hwpxfiller.gui.template_manager import TemplateManagerPanel

    missing = tmp_path / "없는폴더"
    panel = TemplateManagerPanel(library_dir=missing)
    assert panel.stack.currentIndex() == 1                  # 빈 상태 페이지
    assert "폴더가 없습니다" in panel.lbl_empty_hint.text()  # 원인 구분 안내
    assert panel.btn_dir.text() == "폴더 선택"               # 헤더 진입 수단
    assert panel.btn_empty_dir.text() == "폴더 선택"         # 빈 상태 진입 수단

    lib = tmp_path / "lib"
    lib.mkdir()
    _hwpx_pkg(_P("계약명: {{계약명}}")).save(str(lib / "t.hwpx"))
    panel.vm.set_library_dir(lib)  # 다이얼로그 대신 VM 계약 직접 호출(재스캔 경로 동일)
    assert panel.stack.currentIndex() == 0
    assert panel.list.count() == 1


def test_template_manager_action_failure_is_loud_and_clears_stale_result(
    qapp, tmp_path, monkeypatch
):
    """액션 예외 → critical 모달 + '실패: 파일명+사유' 라벨, 직전 성공 문구 잔존 금지(RC-14)."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.gui.template_manager import TemplateManagerPanel

    path = tmp_path / "raw.hwpx"
    _hwpx_pkg(_P("계약명: {{계약명}}")).save(str(path))
    panel = TemplateManagerPanel(library_dir=tmp_path)
    criticals = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: criticals.append(a[2]))

    panel.lbl_result.setText("컴파일 완료 — 직전 성공 문구")  # 스테일 결과 시뮬레이션

    def _boom(*_a, **_k):
        raise PermissionError("액세스가 거부되었습니다")

    monkeypatch.setattr(panel.vm, "lint", _boom)
    panel._dispatch("review", str(path))

    assert criticals                                     # 침묵 소멸 금지 — 모달 통지
    assert panel.lbl_result.text().startswith("실패:")    # 직전 성공 문구 잔존 금지
    assert "raw.hwpx" in panel.lbl_result.text()          # 대상 파일명 지목
    assert "액세스가 거부되었습니다" in panel.lbl_result.text()


def test_run_view_instantiates_with_a_job(qapp):
    from hwpxfiller.core.job import Job
    from hwpxfiller.gui.run_view import RunView

    view = RunView(Job(name="실행테스트", template_path="/t.hwpx", filename_pattern="doc-{{ID}}"))
    assert view.datasource is None  # 데이터 미겨눔 상태로 시작
    assert hasattr(view, "run_finished")


def _run_view_with_data(tmp_path):
    """실행 화면 + 가짜 데이터소스(빈값 1필드 포함) — 다이얼로그 없이 직접 겨눔."""
    from hwpxfiller.core.job import Job
    from hwpxfiller.core.mapping import FieldMapping, MappingProfile
    from hwpxfiller.gui.run_view import RunView

    template = tmp_path / "t.hwpx"
    _write_run_template(template, ["공고명", "추정가격"])
    job = Job(
        name="실행",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce"),
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


def _write_run_template(path, fields):
    """실행뷰 구조 게이트용 최소 유효 HWPX."""
    from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

    body = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{name}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for name in fields
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + '</hp:p></hs:sec>'
    ).encode()
    HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}).save(str(path))


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
    _write_run_template(prev, ["공고명", "추정가격"])
    view.rb_cont.setChecked(True)
    view._template_override = str(prev)

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    assert len(view.selector.selected_indices()) == 2  # 기본 전체 선택
    view._on_generate()
    assert any("1건" in w for w in warnings)
    assert view._thread is None  # 워커 미기동


def test_run_view_structure_drift_is_disabled_danger_not_ack(qapp, tmp_path):
    view = _run_view_with_data(tmp_path)
    _write_run_template(view.job.template_path, ["공고명", "추정가격", "신규필드"])
    view._refresh_field_panel()
    assert not view.btn_generate.isEnabled()
    assert view.lbl_gate.property("level") == "danger"
    assert "매핑을 다시 확정" in view.lbl_gate.text()
    # RC-23 — 차단 중 상단 사전검증이 '통과' 녹색으로 남지 않는다(모순 신호 해소).
    assert view.lbl_preflight.property("level") == "danger"
    assert "통과" not in view.lbl_preflight.text()
    chips = [view.badge_flow.itemAt(i).widget() for i in range(view.badge_flow.count())]
    drift = [w for w in chips if "신규필드" in w.text()][0]
    assert not drift.isEnabled() and "재확정" in drift.text()


def test_run_view_inline_blank_gate_and_marker_injection(qapp, tmp_path, monkeypatch):
    """ADR-E 인라인 게이트 — 미입력은 차단 모달이 아니라 배지 클릭으로 확인.
    확인 전엔 생성 버튼 비활성·생성 무동작, 확인 후 워커 레코드에 표식 주입."""
    from PySide6.QtCore import QObject, Signal

    from hwpxfiller.gui import run_view as rv

    view = _run_view_with_data(tmp_path)
    idx = view.selector.selected_indices()

    # 미입력(추정가격, rec0 빈 값)이 게이트를 닫는다 — 상시 인라인, 생성 버튼 비활성.
    assert "추정가격" in view.vm.unmet_blanks(idx)
    assert not view.btn_generate.isEnabled()
    assert "미입력" in view.lbl_gate.text() and "추정가격" in view.lbl_gate.text()

    captured = {}

    class _FakeWorker(QObject):
        progress = Signal(int, int)
        stage = Signal(str)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, plan):
            super().__init__()
            captured["template"] = plan.template
            captured["records"] = list(plan.records)
            captured["overwrite"] = plan.overwrite

        def run(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(rv, "GenerateWorker", _FakeWorker)

    # 확인 전 생성 시도 = 게이트에 막혀 무동작(모달 없음, 워커 미생성).
    view._on_generate()
    assert "records" not in captured
    assert view._thread is None

    # 미입력 배지 직접 클릭 = 강제 확인 → 게이트 열림.
    view._ack_field("추정가격")
    assert view.vm.unmet_blanks(idx) == []
    assert view.btn_generate.isEnabled()

    view._on_generate()
    try:
        assert captured["template"] == view.job.template_path
        recs = captured["records"]
        assert recs[0]["추정가격"] == "〘미입력·추정가격〙"  # 미충족 공란 → 표식
        assert recs[0]["공고명"] == "가"                    # 비빈 값 불변
        assert recs[1]["추정가격"] == "2000"
    finally:
        view._teardown_thread()


def test_run_view_overwrite_requires_confirmation(qapp, tmp_path, monkeypatch):
    """RC-02 — 기존 산출물과 충돌 시 확인 대화상자: 거부=워커 미기동·무손상, 확정=overwrite 전달."""
    from PySide6.QtCore import QObject, Signal

    from hwpxfiller.gui import run_view as rv

    view = _run_view_with_data(tmp_path)
    view._ack_field("추정가격")  # 빈칸 게이트 통과(rec0 빈 값 확인)
    out = tmp_path / "out"
    out.mkdir()
    sentinel = out / "doc-가.hwpx"  # 패턴 doc-{{공고명}} × rec0 의 대상
    sentinel.write_bytes(b"user-edited")

    captured = {}

    class _FakeWorker(QObject):
        progress = Signal(int, int)
        stage = Signal(str)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, plan):
            super().__init__()
            captured["overwrite"] = plan.overwrite

        def run(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(rv, "GenerateWorker", _FakeWorker)

    # 1) 거부 — 워커 미기동, 기존 파일 무손상(파괴 확인은 공용 헬퍼 경유 — RC-15).
    monkeypatch.setattr(rv, "confirm_destructive", lambda *a, **k: False)
    view._on_generate()
    assert "overwrite" not in captured and view._thread is None
    assert sentinel.read_bytes() == b"user-edited"

    # 2) 확정 — 워커가 overwrite=True 로 기동.
    monkeypatch.setattr(rv, "confirm_destructive", lambda *a, **k: True)
    view._on_generate()
    try:
        assert captured["overwrite"] is True
    finally:
        view._teardown_thread()


def test_run_view_failed_path_cleans_state_loudly(qapp, tmp_path, monkeypatch):
    """RC-07 — 실패 경로도 성공과 대칭: 모달 휘발이 아니라 라벨(danger)·로그·진행바 정리."""
    from PySide6.QtWidgets import QMessageBox

    view = _run_view_with_data(tmp_path)
    criticals = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: criticals.append(a[2]))
    view.progress.setMaximum(3)
    view.progress.setValue(2)
    view._running = True
    view.btn_cancel.setEnabled(True)

    view._on_failed("디스크 오류")
    assert criticals                                        # 경보(모달)는 유지
    assert view.lbl_result.property("level") == "danger"    # 모달 닫아도 증거 잔존
    assert "디스크 오류" in view.lbl_result.text()
    assert "디스크 오류" in view.log.toPlainText()           # 로그에도 박제
    assert view.progress.value() == 0                        # 진행바 리셋
    assert not view._running and not view.btn_cancel.isEnabled()


def test_run_view_cancel_button_gated_by_running(qapp, tmp_path):
    """RC-06 — 취소 버튼 존재 + 평시 비활성(실행 중에만 열린다)."""
    view = _run_view_with_data(tmp_path)
    assert view.btn_cancel.text() == "생성 취소"
    assert not view.btn_cancel.isEnabled()


def _plan_view(tmp_path, *, ledger=False):
    """계획 캡처까지 마친 RunView + GenerationPlan (rec1만 — 빈값 게이트 회피)."""
    view = _run_view_with_data(tmp_path)
    out = tmp_path / "out"
    plan = view.vm.build_generation_plan([1], str(out), marker="", ledger=ledger)
    return view, plan


def test_generate_worker_runs_ledger_tail_off_ui_thread(qapp, tmp_path):
    """RC-07 — 원장 검증·export 는 워커 run() 꼬리: stage 고지 + 파일 생성 + 경로 보고."""
    from pathlib import Path

    from hwpxfiller.gui.worker import GenerateWorker

    _view, plan = _plan_view(tmp_path, ledger=True)
    worker = GenerateWorker(plan)
    stages: "list[str]" = []
    done = {}
    worker.stage.connect(stages.append)
    worker.finished.connect(lambda b: done.setdefault("batch", b))
    worker.run()  # 동일 스레드 직접 실행(직결 시그널) — 계약만 검증

    batch = done["batch"]
    assert batch.succeeded == 1 and not batch.cancelled
    assert worker.ledger_error is None
    assert worker.ledger_path and Path(worker.ledger_path).exists()
    assert any("원장 검증 중" in s for s in stages)  # '검증 중' 단계 고지


def test_generate_worker_cancel_short_circuits(qapp, tmp_path):
    """RC-06 — 스레드-세이프 취소 플래그: 시작 전 취소면 산출물 0 + cancelled 배치."""
    from hwpxfiller.gui.worker import GenerateWorker

    _view, plan = _plan_view(tmp_path)
    worker = GenerateWorker(plan)
    worker.cancel()
    done = {}
    worker.finished.connect(lambda b: done.setdefault("batch", b))
    worker.run()
    batch = done["batch"]
    assert batch.cancelled is True and batch.attempted == 0
    assert not list((tmp_path / "out").glob("*.hwpx"))


def test_run_view_cancelled_batch_shows_partial_summary(qapp, tmp_path):
    """RC-06 — 취소 완료는 '완료' 서사가 아니라 부분 결과 요약(warn) + 폴더 모달 억제."""
    from hwpxfiller.batch import BatchResult
    from hwpxfiller.core.engine import GenerateResult

    view, plan = _plan_view(tmp_path)
    view._plan = plan
    view._running = True
    results = [GenerateResult(True, str(tmp_path / f"d{i}.hwpx")) for i in range(2)]
    view._on_finished(
        BatchResult(total=5, succeeded=2, results=results, cancelled=True)
    )
    assert "취소됨" in view.lbl_result.text()
    assert view.lbl_result.property("level") == "warn"
    assert "미처리 3건" in view.lbl_result.text()


def test_run_view_partial_failure_modal_mentions_failures(qapp, tmp_path, monkeypatch):
    """RC-30 — 부분 실패 완료 모달이 '완료' 서사로 실패를 덮지 않는다.

    2성공·1실패 배치(S4 재현): 모달은 경고형으로 실패 건수·로그 안내를 병기하고,
    개별 실패 사유는 원시 errno 대신 행동 지향 문구로 로그에 남는다.
    """
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.batch import BatchResult
    from hwpxfiller.core.engine import GenerateResult
    from hwpxfiller.gui import batch_run

    view, plan = _plan_view(tmp_path)
    view._plan = plan
    view._running = True
    seen = {}
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda parent, title, text, *a, **k: (seen.update(title=title, text=text),
                                              QMessageBox.Yes)[1],
    )
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: pytest.fail("부분 실패는 경고형 모달이어야 한다(RC-30)"),
    )
    opened = []
    monkeypatch.setattr(batch_run, "open_folder", opened.append)

    results = [
        GenerateResult(True, "a.hwpx"),
        GenerateResult(True, "b.hwpx"),
        GenerateResult(False, "c.hwpx",
                       error="저장 실패: [Errno 13] Permission denied: 'c.hwpx'"),
    ]
    view._on_finished(BatchResult(total=3, succeeded=2, results=results))

    assert "2건 성공" in seen["text"] and "1건 실패" in seen["text"] and "로그" in seen["text"]
    assert "일부 실패" in seen["title"]
    assert opened == [plan.out_dir]                      # 확정(Yes) → 공용 open_folder 경유
    assert view.lbl_result.property("level") == "danger"  # 요약 라벨과 정보 대칭
    log = view.log.toPlainText()
    assert "파일 접근이 거부됐습니다" in log               # 행동 지향 문구(RC-30)
    assert "Permission denied" in log                     # 원문도 증거로 보존


def test_run_view_all_success_modal_keeps_question(qapp, tmp_path, monkeypatch):
    """전건 성공은 기존 question 모달 유지(회귀 불변) — 실패 무언급이 정당한 유일 경우."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.batch import BatchResult
    from hwpxfiller.core.engine import GenerateResult

    view, plan = _plan_view(tmp_path)
    view._plan = plan
    view._running = True
    seen = {}
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda parent, title, text, *a, **k: (seen.update(text=text), QMessageBox.No)[1],
    )
    view._on_finished(BatchResult(
        total=2, succeeded=2,
        results=[GenerateResult(True, f"d{i}.hwpx") for i in range(2)],
    ))
    assert "2건 생성 완료" in seen["text"] and "실패" not in seen["text"]
    assert view.lbl_result.property("level") == "ok"


def _partial_template_file(
    tmp_path, extra_token: str = "{{미컴파일필드}}", filename: str = "tpl.hwpx"
) -> str:
    """진짜 필드 1개(계약명) + 미컴파일 평문 ``extra_token`` 을 담은 PARTIAL .hwpx 파일."""
    from lxml import etree

    from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
    from hwpxfiller.core.authoring import compile_document

    HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    HS = "http://www.hancom.co.kr/hwpml/2011/section"
    section = "Contents/section0.xml"
    token = "{{계약명}}"
    sec = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        f"<hp:p><hp:run><hp:t>{token}</hp:t></hp:run></hp:p></hs:sec>"
    ).encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries[section] = sec
    pkg, _ = compile_document(pkg)  # {{계약명}} → 누름틀 필드
    # 미컴파일 평문 토큰을 덧붙여 PARTIAL 로 만든다.
    root = etree.fromstring(pkg.entries[section])
    p = etree.SubElement(root, f"{{{HP}}}p")
    run = etree.SubElement(p, f"{{{HP}}}run")
    t = etree.SubElement(run, f"{{{HP}}}t")
    t.text = extra_token
    pkg.entries[section] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    path = tmp_path / filename
    pkg.save(str(path))
    return str(path)


def test_template_page_partial_gates_until_acked(qapp, tmp_path):
    """PARTIAL 템플릿 로드 → isComplete False; 명시 ack 후 True(다이얼로그 우회)."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    path = _partial_template_file(tmp_path)
    wiz = JobEditorWizard(JobRegistry(tmp_path))
    page = wiz.page(wiz.pageIds()[0])  # TemplatePage
    page._load_template(path)

    assert page._gate is not None and page._gate.state.name == "PARTIAL"
    assert not page.isComplete()  # PARTIAL 차단
    assert "미컴파일필드" in page.lbl_warn.text()  # 구체 이름 재진술
    assert not page.btn_ack.isHidden()  # offscreen: 최상위 미표시라 isVisible 대신 isHidden

    # 명시 ack(다이얼로그 대신 정확한 이름 전체를 직접 확인).
    page._gate.acknowledge(page._gate.unmet_tokens)
    page._refresh_gate_ui()
    assert page.isComplete()


def test_template_page_inline_compile_flips_to_compiled(qapp, tmp_path, monkeypatch):
    """[여기서 컴파일] → 컴파일본 전환, COMPILED 로 승격되어 진행 가능."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(
        QMessageBox, "critical",
        lambda *a, **k: pytest.fail(f"컴파일 실패 다이얼로그가 떴다: {a[2] if len(a) > 2 else a}"),
    )
    path = _partial_template_file(tmp_path)
    wiz = JobEditorWizard(JobRegistry(tmp_path))
    page = wiz.page(wiz.pageIds()[0])
    page._load_template(path)
    assert not page.isComplete()
    assert not page.btn_compile.isHidden()  # offscreen: isVisible 대신 isHidden

    page._compile_here()

    assert page._gate is not None and page._gate.state.name == "COMPILED"
    assert page.isComplete()
    assert page.ed_path.text().endswith(".compiled.hwpx")
    assert wiz.template_path == page.ed_path.text()  # 컴파일본으로 전환


def test_template_page_compile_here_confirms_before_overwriting(qapp, tmp_path, monkeypatch):
    """RC-02 — 기존 .compiled.hwpx(사람이 손봤을 수 있음)를 확인 없이 덮지 않는다.

    거부하면 기존 컴파일본 무손상 + 경로 전환 없음, 확정 시에만 덮어쓰고 전환한다.
    """
    from pathlib import Path

    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui import wizard as wz
    from hwpxfiller.gui.job_editor import JobEditorWizard

    path = _partial_template_file(tmp_path)
    stale = Path(path).with_suffix(".compiled.hwpx")
    stale.write_bytes(b"user-edited-compiled")

    wiz = JobEditorWizard(JobRegistry(tmp_path))
    page = wiz.page(wiz.pageIds()[0])
    page._load_template(path)

    # 1) 거부 — 기존 컴파일본 무손상, 원본 경로 유지(파괴 확인은 공용 헬퍼 — RC-15).
    monkeypatch.setattr(wz, "confirm_destructive", lambda *a, **k: False)
    page._compile_here()
    assert stale.read_bytes() == b"user-edited-compiled"
    assert page.ed_path.text() == path

    # 2) 확정 — 덮어쓰고 컴파일본으로 전환.
    monkeypatch.setattr(wz, "confirm_destructive", lambda *a, **k: True)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    page._compile_here()
    assert stale.read_bytes()[:2] == b"PK"  # 유효 HWPX 로 교체
    assert page.ed_path.text().endswith(".compiled.hwpx")


def test_template_page_ack_does_not_carry_across_templates(qapp, tmp_path):
    """PARTIAL A 를 ack 한 뒤 다른 미해결 집합의 PARTIAL B 로드 → A의 ack 가 B를 만족 못함."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    path_a = _partial_template_file(tmp_path, "{{토큰에이}}", "a.hwpx")
    path_b = _partial_template_file(tmp_path, "{{토큰비}}", "b.hwpx")
    wiz = JobEditorWizard(JobRegistry(tmp_path))
    page = wiz.page(wiz.pageIds()[0])

    page._load_template(path_a)
    assert "토큰에이" in page._gate.unmet_tokens
    page._gate.acknowledge(page._gate.unmet_tokens)
    page._refresh_gate_ui()
    assert page.isComplete()  # A ack 후 진행 가능

    # 미해결 집합이 다른 템플릿 B 로드 → 게이트가 새로 계산되어 A의 ack 는 무효.
    page._load_template(path_b)
    assert "토큰비" in page._gate.unmet_tokens
    assert "토큰에이" not in page._gate.unmet_tokens
    assert not page.isComplete()  # 스테일 ack 이월 금지


def test_template_page_fails_closed_on_gate_compute_error(qapp, tmp_path, monkeypatch):
    """게이트 계산이 실패하면 PARTIAL 여부를 배제 못하므로 fail-closed(진행 불가 + 시끄럽게).

    Finding-1 회귀: 수정 전에는 _valid=True·_gate=None·경고 삭제로 조용히 통과했다.
    """
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui import wizard as wz
    from hwpxfiller.gui.job_editor import JobEditorWizard

    path = _partial_template_file(tmp_path)
    wiz = JobEditorWizard(JobRegistry(tmp_path))
    page = wiz.page(wiz.pageIds()[0])

    def _boom(*a, **k):
        raise RuntimeError("상태 계산 폭발")

    monkeypatch.setattr(wz, "gate_for_template", _boom)
    page._load_template(path)

    assert not page.isComplete()  # fail-closed: 진행 불가
    assert page._gate_error  # 오류 상태 명시
    assert "계산할 수 없습니다" in page.lbl_warn.text()  # 경고를 지우지 않고 시끄럽게 유지


def test_txt_view_renders_and_keeps_missing_tokens(qapp, tmp_path):
    """즉시 기안 화면 — 템플릿 자동 선택·토큰 상태·실시간 렌더에 미입력 토큰 노출."""
    from hwpxfiller.core.text_registry import TextTemplateRegistry
    from hwpxfiller.gui.txt_view import TxtDraftView

    d = tmp_path / "tt"
    d.mkdir()
    (d / "기안.txt").write_text("제목: {{공고명}}\n담당: {{담당자}}", encoding="utf-8")
    view = TxtDraftView(TextTemplateRegistry(d))
    assert view.cbo.count() == 1  # 루트 템플릿 1개 로드

    class _Src:
        def records(self):
            return [{"공고명": "전산장비 구매"}]  # 담당자 없음 → missing

        def fields(self):
            return ["공고명"]

    view.vm.datasource = _Src()
    view.vm.records = _Src().records()
    view._render()

    states = {t.name: t.state for t in view.vm.token_states()}
    assert states == {"공고명": "fill", "담당자": "missing"}
    rendered = view.view.toPlainText()
    assert "전산장비 구매" in rendered      # 값 치환
    assert "{{담당자}}" in rendered          # 미입력 토큰 그대로(시끄럽게)


def test_txt_view_data_affordances_are_symmetric(qapp, tmp_path):
    """UD-25(V12): txt 데이터 겨눔이 파일 1종 → 풀·파일·수기 3종으로 대칭화."""
    from hwpxfiller.core.text_registry import TextTemplateRegistry
    from hwpxfiller.gui.txt_view import ManualRecordDialog, TxtDraftView

    d = tmp_path / "tt"
    d.mkdir()
    (d / "기안.txt").write_text("제목: {{공고명}}\n담당: {{담당자}}", encoding="utf-8")

    class _Pool:  # 풀 레지스트리 스텁 — 구성만 검증(홈 무접촉).
        def list_items(self, status=None):
            return []

    view = TxtDraftView(TextTemplateRegistry(d), pool_registry=_Pool())
    # 3종 겨눔 버튼이 실행 표면(풀·파일·나라)과 동형으로 출현한다.
    assert view.btn_pool.text() == "데이터 풀에서…"
    assert view.btn_data.text() == "파일 선택…"
    assert view.btn_manual.text() == "수기 입력…"

    # 수기 1건 — 인라인 소스로 겨눠 실시간 렌더에 반영(파일 강제 없이).
    # 폼은 템플릿 토큰 전량을 담는다 → 미입력 칸은 '빈 값'(blank)으로 겨눠진다.
    dlg = ManualRecordDialog(view, view.vm.template_field_names())
    dlg._edits["공고명"].setText("친환경 소화장비")
    rec = dlg.record()
    assert set(rec) == {"공고명", "담당자"}  # 템플릿 토큰 전량이 폼에 있다
    view.vm.set_acquired(None, [rec])
    view._after_data_loaded("수기 입력 1건")
    assert view.ed_data.text() == "수기 입력 1건"
    assert "친환경 소화장비" in view.view.toPlainText()
    # 채운 값은 fill, 빈 칸은 blank(missing 아님 — 폼에 존재하므로) — 상태 배지로 확인.
    states = {t.name: t.state for t in view.vm.token_states()}
    assert states == {"공고명": "fill", "담당자": "blank"}


# ------------------------------------------- U3 매핑 정확성 회귀(RC-08·09·10)
def test_job_editor_accept_warns_and_blocks_all_blank_job(qapp, tmp_path, monkeypatch):
    """RC-08 회귀: 전 행 비움 확정 작업은 저장 전 경고로 차단 — 종전 술어
    (not profile.mappings)는 blank 영속화(L1) 이후 dead code 라 무경고 저장됐다."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard
    from hwpxfiller.gui.mapping_state import RowState

    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: warnings.append(a[2] if len(a) > 2 else ""),
    )
    reg = JobRegistry(tmp_path)
    wiz = JobEditorWizard(reg)
    wiz.template_path = "/t.hwpx"
    wiz.model = MappingModel(rows=[RowState("공고명"), RowState("비고")])
    wiz.model.confirm_all()  # 소스·상수 없이 전 행 확정 = '전부 비움'
    assert wiz.model.is_complete()
    assert wiz.model.to_profile().mappings  # blank 도 영속화 — 옛 술어는 여기서 불발
    saved = []
    wiz.job_saved.connect(lambda name: saved.append(name))
    wiz._save_page.ed_name.setText("전부비움작업")

    wiz.accept()

    assert warnings and "채울 값이 없습니다" in warnings[0]
    assert not reg.exists("전부비움작업")  # 무의미 작업 저장 차단
    assert not saved                       # job_saved 미방출

    # 반대 방향(과차단 금지): 값을 방출하는 행이 생기면 그대로 저장된다.
    wiz.model.set_source(0, "bidNtceNm")
    wiz.model.confirm_all()
    wiz.accept()
    assert saved == ["전부비움작업"]
    assert reg.exists("전부비움작업")


def _authoring_wizard(tmp_path):
    """RC-09 회귀용 위저드 — 템플릿 스텝은 세션 직주입으로 건너뛴다."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    wiz = JobEditorWizard(JobRegistry(tmp_path))
    wiz.template_path = "/t.hwpx"
    wiz.schema = TemplateSchema(fields=[FieldSpec("공고명", "text", 1, False)])
    data_page = wiz.page(wiz.pageIds()[1])
    mapping_page = wiz.page(wiz.pageIds()[2])
    return wiz, data_page, mapping_page


def test_mapping_page_rebuilds_when_same_path_content_changes(qapp, tmp_path, monkeypatch):
    """RC-09 §B 회귀: 같은 경로의 수정된 파일 재선택 → 매핑 초안이 새 어휘로 재구성.

    종전 캐시 키는 (template_path, data_path) 경로쌍뿐이라 내용 불감 — 신규 컬럼은
    매핑 불가, 삭제 컬럼은 계속 제안되는 옛 어휘로 조용히 구동됐다.
    """
    from PySide6.QtWidgets import QFileDialog

    csv = tmp_path / "d.csv"
    csv.write_text("colA,colB\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(csv), ""))
    wiz, data_page, mapping_page = _authoring_wizard(tmp_path)

    data_page._pick()
    assert wiz.source_fields == ["colA", "colB"]
    mapping_page.initializePage()
    assert wiz.model.source_fields == ["colA", "colB"]

    # 같은 경로, 내용 교체 후 재선택 — 소스 어휘가 새것으로 갈려야 한다.
    csv.write_text("colA,colC,colD\n1,3,4\n", encoding="utf-8")
    data_page._pick()
    assert wiz.source_fields == ["colA", "colC", "colD"]
    mapping_page.initializePage()
    assert wiz.model.source_fields == ["colA", "colC", "colD"]  # 옛 colB 잔존 금지


def test_datapage_source_toggle_resets_session_atomically(qapp, tmp_path, monkeypatch):
    """RC-09 §C 회귀 + UD-08: 소스 전환은 뷰(경로칸·요약)만이 아니라 위저드 세션 사본
    (data_path·datasource·records·source_fields)까지 원자적으로 무효화한다 — 단 불러온
    데이터가 있으면 무확인 파기가 아니라 확인을 거치고, 거부 시 라디오를 되돌린다."""
    from PySide6.QtWidgets import QFileDialog

    from hwpxfiller.gui import wizard as wz

    csv = tmp_path / "d.csv"
    csv.write_text("colA,colB\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(csv), ""))
    wiz, data_page, mapping_page = _authoring_wizard(tmp_path)

    data_page._pick()
    assert wiz.records and wiz.datasource is not None

    # UD-08 — 전환 확인 거부: 데이터 보존 + 라디오 되돌림(무확인·무고지 파기 금지).
    monkeypatch.setattr(wz, "confirm_destructive", lambda *a, **k: False)
    data_page.rb_nara.setChecked(True)
    assert wiz.records and wiz.datasource is not None        # 파기되지 않음
    assert data_page.rb_excel.isChecked()                     # 라디오 원위치
    assert not data_page.rb_nara.isChecked()

    # 확인 수락 → 뷰·세션 원자적 무효화(RC-09).
    monkeypatch.setattr(wz, "confirm_destructive", lambda *a, **k: True)
    data_page.rb_nara.setChecked(True)
    assert wiz.data_path == ""
    assert wiz.datasource is None
    assert wiz.source_fields == []
    assert wiz.records == []
    assert data_page.ed_path.text() == "" and data_page.lbl_summary.text() == ""
    # 매핑 스텝 재진입도 지운 데이터로 구동되지 않는다(캐시 키·레코드 모두 초기화).
    mapping_page.initializePage()
    assert wiz.model.source_fields == []
    assert mapping_page.lbl_index.text() == "레코드 0/0"


def test_mapping_table_unknown_type_renders_loudly_without_crash(qapp):
    """RC-10 2차 방어 회귀: 미지 타입 행도 뷰가 죽지 않고(Qt 가 예외를 삼켜 통지 0 이던
    크래시 금지) 타입 콤보·미리보기에 시끄럽게 재진술한다 — 조용한 오표시 금지."""
    from hwpxfiller.core.mapping import TYPES
    from hwpxfiller.gui.mapping_state import RowState
    from hwpxfiller.gui.mapping_table import _COL_PREVIEW, _COL_TYPE, MappingTable

    model = MappingModel(
        rows=[RowState("추정가격", source="presmptPrce", type="amonut")],
        source_fields=["presmptPrce"],
    )
    table = MappingTable()
    # 종전: TYPES.index("amonut") 미처리 ValueError 로 렌더 중단.
    table.set_model(model, {"presmptPrce": "123456789"})

    tc = table.cell_control(0, _COL_TYPE)
    assert "amonut" in tc.currentText() and "지원 안 함" in tc.currentText()
    assert "미리보기 오류" in table.table.item(0, _COL_PREVIEW).text()

    # 마커 항목 재선택은 변경 없음 — 재동기화가 마커를 증식시키지도 않는다.
    table._on_type_activated(0, tc.currentIndex())
    assert model.rows[0].type == "amonut"
    assert table.cell_control(0, _COL_TYPE).count() == len(TYPES) + 1

    # 지원 타입으로 바꾸면 정상 복귀(마커 제거·미리보기 재계산).
    table._on_type_activated(0, TYPES.index("amount"))
    assert model.rows[0].type == "amount"
    assert table.cell_control(0, _COL_TYPE).count() == len(TYPES)
    assert "미리보기 오류" not in table.table.item(0, _COL_PREVIEW).text()


def test_mapping_table_combos_ignore_wheel_so_table_scrolls(qapp):
    """사용성 회귀: 셀 콤보 위에서 휠을 굴려도 선택이 바뀌지 않고 이벤트가 표로 전파된다
    (선택은 클릭만). 종전엔 휠이 콤보에 흡수돼 스크롤 대신 값이 엉뚱하게 바뀌었다."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QWheelEvent

    from hwpxfiller.gui.mapping_state import RowState
    from hwpxfiller.gui.mapping_table import (
        _COL_FORMAT,
        _COL_SOURCE,
        _COL_TYPE,
        MappingTable,
        _NoScrollComboBox,
    )

    model = MappingModel(
        rows=[RowState("개찰일시", source="opengDate", type="date")],
        source_fields=["opengDate", "opengTm", "presmptPrce"],
    )
    table = MappingTable()
    table.set_model(model, {"opengDate": "20260713"})

    for col in (_COL_SOURCE, _COL_TYPE, _COL_FORMAT):
        combo = table.cell_control(0, col)
        assert isinstance(combo, _NoScrollComboBox)
        before = combo.currentIndex()
        ev = QWheelEvent(
            QPoint(5, 5), combo.mapToGlobal(QPoint(5, 5)), QPoint(0, -120),
            QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
        )
        combo.wheelEvent(ev)
        assert not ev.isAccepted()          # 위(표)로 전파됨
        assert combo.currentIndex() == before  # 선택 불변


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

    corpus = Path(__file__).parent / "corpus" / "real"
    win = _diff_window_for_test(tmp_path, monkeypatch)
    assert not win.btn_compare.isEnabled()  # 판본 선택 전

    win.ed_old.setText(str(corpus / "spec_revision_2025.hwpx"))
    win.ed_new.setText(str(corpus / "spec_revision_2026.hwpx"))
    win._on_compare()

    assert win.result is not None
    # 그룹화는 코어 소유 — 리스트 행 수 = 코어가 계산한 rows 기반 그룹 수.
    assert win.items.rowCount() == len(win.result.change_groups) > 0
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


# 순수 함수(coalesce_word_ops·group_changes)는 core.diff 로 이관 — 헤드리스 테스트도
# 함께 이동했다: tests/test_diff_render.py(coalesce)·tests/test_diff_rows.py(그룹화).


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


def test_diff_view_css_uses_core_inline_palette(qapp):
    """전문 뷰 del/ins 팔레트 = 코어 KIND_COLORS/KIND_TINTS — CLI HTML 과 표면 간 일치."""
    from hwpxdiff.app import _QT_VIEW_CSS
    from hwpxdiff.diff import KIND_COLORS, KIND_TINTS

    assert f"del{{background-color:{KIND_TINTS['removed']};color:{KIND_COLORS['removed']};}}" \
        in _QT_VIEW_CSS
    assert f"ins{{background-color:{KIND_TINTS['added']};color:{KIND_COLORS['added']};" \
        in _QT_VIEW_CSS


def test_diff_first_compare_failure_sets_inline_message(qapp, tmp_path, monkeypatch):
    """RC-31: 새 창 첫 비교 실패 — 모달을 닫은 뒤에도 실패 사유가 요약 라벨에 남는다.

    _invalidate_result 의 조기 반환('지울 결과 없음')이 메시지 표시까지 삼키면
    초기 안내문('판본 2개를 선택하고…')이 손상 경로 위에 그대로 잔존한다.
    """
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    from hwpxdiff.app import DiffReviewWindow

    calls: "list[tuple]" = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: calls.append(a))
    win = DiffReviewWindow()
    win._settings = QSettings(str(tmp_path / "recent.ini"), QSettings.IniFormat)
    initial = win.lbl_summary.text()

    bad_old = tmp_path / "bad_old.hwpx"
    bad_old.write_bytes(b"not a zip")
    bad_new = tmp_path / "bad_new.hwpx"
    bad_new.write_bytes(b"still not a zip")
    win.ed_old.setText(str(bad_old))
    win.ed_new.setText(str(bad_new))
    win._on_compare()

    assert calls, "실패 모달이 뜨지 않았다"
    assert win.result is None
    assert win.lbl_summary.text() != initial
    assert "비교 실패" in win.lbl_summary.text()
    assert not win.lbl_summary.isHidden()


def test_diff_zero_changes_shows_shared_no_changes_copy(qapp, tmp_path, monkeypatch):
    """RC-32: 변경 0건이면 GUI 도 확정 문장(3표면 공유 카피)을 노출 — 빈 리스트 모호성 제거."""
    from pathlib import Path

    from hwpxdiff.diff import NO_CHANGES_MESSAGE

    corpus = Path(__file__).parent / "corpus" / "real"
    same = str(corpus / "spec_revision_2025.hwpx")
    win = _diff_window_for_test(tmp_path, monkeypatch)
    win.ed_old.setText(same)
    win.ed_new.setText(same)
    win._on_compare()

    assert win.result is not None and not win.result.changes
    assert win.lbl_summary.text() == NO_CHANGES_MESSAGE
    assert not win.lbl_summary.isHidden()
    assert not win.kpi_wrap.isHidden()          # 수치 근거(0/0/0/0)도 함께
    assert win.lbl_filter_notice.isHidden()     # 필터 안내와 혼동 금지


def test_diff_filter_all_off_shows_notice_not_silence(qapp, tmp_path, monkeypatch):
    """RC-32: 필터 3종+번호변경 전부 꺼서 0행이면 안내 라벨 — '진짜 동일'과 구분."""
    from pathlib import Path

    corpus = Path(__file__).parent / "corpus" / "real"
    win = _diff_window_for_test(tmp_path, monkeypatch)
    win.ed_old.setText(str(corpus / "spec_revision_2025.hwpx"))
    win.ed_new.setText(str(corpus / "spec_revision_2026.hwpx"))
    win._on_compare()
    assert win.items.rowCount() > 0
    assert win.lbl_filter_notice.isHidden()     # 기본 필터에선 안내 없음

    for cb in win._filter_checks.values():
        cb.setChecked(False)
    win.chk_renumber.setChecked(False)
    assert all(win.items.isRowHidden(r) for r in range(win.items.rowCount()))
    assert not win.lbl_filter_notice.isHidden()

    win._filter_checks["changed"].setChecked(True)  # 하나라도 켜면 안내 해제
    assert win.lbl_filter_notice.isHidden()


# ------------------------------------------------- U10 링 경계(RC-25·28·29) 배선
def test_job_editor_declares_nara_injection_contract(qapp, tmp_path):
    """RC-25 — 주입은 생성자 계약: 오타는 TypeError, 미주입도 None 으로 선언 존재."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    store = object()
    fetcher = lambda url: b""  # noqa: E731
    wiz = JobEditorWizard(
        JobRegistry(tmp_path), secret_store=store, nara_fetcher=fetcher
    )
    assert wiz.secret_store is store and wiz.nara_fetcher is fetcher

    wiz2 = JobEditorWizard(JobRegistry(tmp_path))
    assert wiz2.secret_store is None and wiz2.nara_fetcher is None  # 선언된 기본

    with pytest.raises(TypeError):  # 키워드 오타 = 시끄러운 실패(조용한 실 폴백 금지)
        JobEditorWizard(JobRegistry(tmp_path), secret_stre=store)  # type: ignore[call-arg]


def test_editor_accept_blocks_all_blank_job_loudly(qapp, tmp_path, monkeypatch):
    """RC-28 — accept 가드가 링1(validate_save)을 관통: 전부 비움 저장은 경고 + 무저장."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard
    from hwpxfiller.gui.mapping_state import MappingModel, RowState

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    reg = JobRegistry(tmp_path)
    wiz = JobEditorWizard(reg)
    wiz.template_path = "/t.hwpx"
    wiz.model = MappingModel(rows=[RowState(template_field="공고명", confirmed=True)])
    wiz._save_page.ed_name.setText("빈작업")

    wiz.accept()

    assert warnings and "전부 비움" in warnings[0]
    assert not reg.exists("빈작업")  # 조용한 저장 없음


def test_mapping_table_arg_edit_shares_row_brush(qapp):
    """RC-28 — _on_arg_edited 의 행 색이 _sync_row 와 같은 결정식(_row_brush)을 쓴다."""
    from hwpxfiller.gui.mapping_table import _COL_FIELD, _row_brush, MappingTable

    model = _model()
    table = MappingTable()
    table.set_model(model, {"bidNtceNm": "테스트"})
    ri = 0
    model.set_type(ri, "const")  # 고정값 입력이 활성인 행
    model.set_confirmed(ri, True)
    table._sync_row(ri)

    table._on_arg_edited(ri, "고정값")  # 고정값 편집 → 확정 해제

    row = model.rows[ri]
    assert not row.confirmed
    assert table.table.item(ri, _COL_FIELD).background() == _row_brush(row)


def test_mapping_table_schema_only_demotes_red_and_shows_banner(qapp):
    """UD-28 — 데이터 미연결(source_fields=[]) 세션에선 빈 미확정 행의 '미매칭' 빨강이
    중립으로 강등되고 스키마온리 안내 배너가 노출된다. 데이터 연결 세션에선 빨강 유지·
    배너 숨김('데이터 미연결'과 '미매칭'을 시각 분리)."""
    from PySide6.QtGui import QColor

    from hwpxfiller.gui.mapping_state import MappingModel, RowState
    from hwpxfiller.gui.mapping_table import _COL_FIELD, MappingTable
    from hwpxfiller.gui.style import UNMATCHED_BG

    red = QColor(UNMATCHED_BG).rgb()

    # 데이터 미연결 — 빈 행 중립 강등 + 배너 노출.
    so = MappingModel(rows=[RowState("공고명"), RowState("추정가격")], source_fields=[])
    t = MappingTable()
    t.set_model(so)
    assert so.is_schema_only()
    assert not t.lbl_schema_only.isHidden()  # 배너 노출
    for ri in range(len(so.rows)):
        assert t.table.item(ri, _COL_FIELD).background().color().rgb() != red

    # 데이터 연결 — 빈 행은 여전히 미매칭 빨강, 배너 숨김.
    conn = MappingModel(rows=[RowState("공고명")], source_fields=["bidNtceNm"])
    t2 = MappingTable()
    t2.set_model(conn)
    assert not conn.is_schema_only()
    assert t2.lbl_schema_only.isHidden()
    assert t2.table.item(0, _COL_FIELD).background().color().rgb() == red


def test_wizard_readonly_path_fields_excluded_from_focus_chain(qapp):
    """UD-37 — 스텝1·2의 읽기전용 경로 필드는 포커스 정책 NoFocus 로 포커스 체인에서
    빠져 첫 포커스가 회색 read-only 필드에 착지하지 않는다. style 에 read-only:focus
    규칙이 있어 혹시 포커스를 받아도 회색 룩을 유지한다(2차 방어)."""
    from PySide6.QtCore import Qt

    from hwpxfiller.gui import style
    from hwpxfiller.gui.wizard import DataPage, TemplatePage

    tp = TemplatePage()
    assert tp.ed_path.isReadOnly()
    assert tp.ed_path.focusPolicy() == Qt.FocusPolicy.NoFocus
    dp = DataPage()
    assert dp.ed_path.isReadOnly()
    assert dp.ed_path.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert "QLineEdit:read-only:focus" in style.BASE_QSS


def test_template_page_compile_here_delegates_io_to_core(qapp, tmp_path, monkeypatch):
    """RC-28 — [여기서 컴파일]의 경로 파생·저장은 코어 compile_to_sibling 경유.

    기존 컴파일본 충돌은 FileExistsError 로 도착해 명시 확정 후에만 덮는다(RC-02 유지).
    """
    from pathlib import Path

    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui import wizard as wz
    from hwpxfiller.gui.job_editor import JobEditorWizard

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    path = _partial_template_file(tmp_path)
    sibling = Path(path).with_suffix(".compiled.hwpx")
    sibling.write_bytes(b"human-edited")  # 충돌 유도

    wiz = JobEditorWizard(JobRegistry(tmp_path))
    page = wiz.page(wiz.pageIds()[0])
    page._load_template(path)

    # 확정 거절 → 기존 컴파일본 무변형(조용한 덮어쓰기 없음).
    asked = []
    monkeypatch.setattr(wz, "confirm_destructive", lambda *a, **k: asked.append(a) or False)
    page._compile_here()
    assert asked and sibling.read_bytes() == b"human-edited"

    # 확정 수락 → 컴파일본 교체 + COMPILED 전환.
    monkeypatch.setattr(wz, "confirm_destructive", lambda *a, **k: True)
    page._compile_here()
    assert sibling.read_bytes() != b"human-edited"
    assert page._gate is not None and page._gate.state.name == "COMPILED"
    assert wiz.template_path == str(sibling)


def test_home_card_badge_uses_unified_level_palette(qapp, tmp_path):
    """RC-29 — 홈 카드 배지가 fb 재전용 대신 compile_badge 레벨(pill)로 칠해진다."""
    from PySide6.QtWidgets import QLabel

    from hwpxfiller.core.authoring import compile_document
    from hwpxfiller.core.job import Job, JobRegistry
    from hwpxfiller.gui.home import JobListHome
    from hwpxfiller.gui.home_state import BADGE_MISSING, BADGE_READY

    pkg, _ = compile_document(_hwpx_pkg(_P("계약명: {{계약명}}")))
    comp = tmp_path / "comp.hwpx"
    pkg.save(str(comp))
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="준비작업", template_path=str(comp)))
    reg.save(Job(name="부재작업", template_path=str(tmp_path / "ghost.hwpx")))
    home = JobListHome(reg)

    badges = {}
    for i in range(home.list.count()):
        card = home.list.itemWidget(home.list.item(i))
        for lbl in card.findChildren(QLabel):
            if lbl.text() in (BADGE_READY, BADGE_MISSING):
                badges[lbl.text()] = lbl
    assert badges[BADGE_READY].property("pill") == "ok"        # COMPILED → ok
    assert badges[BADGE_MISSING].property("pill") == "danger"  # 부재(state None) → danger
    # fb 셀렉터(실행 화면 필드 상태 어휘)는 더 이상 홈 배지에 재전용되지 않는다.
    assert badges[BADGE_READY].property("fb") is None


def test_public_class_names_with_underscore_compat_aliases(qapp):
    """RC-35 — 사실상 공용 API 인 컨트롤러·카드류 공개화 + 언더스코어 별칭 무파괴.

    기존 크로스모듈 임포트·docs 스니펫(`_AppController` 등)은 별칭으로 계속 동작한다.
    """
    from hwpxfiller.gui import app as app_mod
    from hwpxfiller.gui import home as home_mod
    from hwpxfiller.gui import template_manager as tm_mod

    assert app_mod._AppController is app_mod.AppController
    assert home_mod._JobCard is home_mod.JobCard
    assert tm_mod._TemplateCard is tm_mod.TemplateCard


def test_mapping_table_tooltips_expose_full_names(qapp):
    """RC-36 — 필드 셀 전체 이름 상시 툴팁(문맥 병기), 소스 콤보 현재 선택 툴팁.

    좁은 열에서 말줄임된 유사 접두 필드를 오인 확정하지 않도록 툴팁이 전체 문자열을
    항상 보여준다. 기존 저신뢰 자동 제안 경고는 병기 유지.
    """
    from hwpxfiller.gui.mapping_table import _COL_FIELD, _COL_SOURCE, MappingTable

    model = _model()
    table = MappingTable()
    table.set_model(model, {})
    for ri, row in enumerate(model.rows):
        assert row.template_field in table.table.item(ri, _COL_FIELD).toolTip()
        combo = table.cell_control(ri, _COL_SOURCE)
        assert combo.currentText() in combo.toolTip()  # 현재 선택 전체 문자열

    # 문맥(spec.context)은 병기 유지 — '공고명' 필드는 문맥 "공 고 명:" 을 갖는다.
    ri = next(i for i, r in enumerate(model.rows) if r.template_field == "공고명")
    assert "문맥: 공 고 명:" in table.table.item(ri, _COL_FIELD).toolTip()

    # 저신뢰 자동 제안 경고 병기 유지(툴팁 대체가 아니라 병기).
    model.rows[ri].suggestion_score = 0.6
    table.refresh()
    tip = table.cell_control(ri, _COL_SOURCE).toolTip()
    assert "현재 선택:" in tip
    assert "신뢰도 60%" in tip
