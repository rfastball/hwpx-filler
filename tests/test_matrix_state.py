"""매트릭스 실행 ViewModel(J2) 헤드리스 테스트 — Qt 무접촉.

작업 다중선택·데이터 겨눔(파일/풀)·사전검증을 못박는다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.batch import generate_matrix
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.matrix_state import MatrixRunViewModel
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage


def _template(path, fields=()):
    body = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{name}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for name in fields
    )
    xml = (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + '</hp:p></hs:sec>'
    ).encode()
    HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}).save(str(path))


def _registry(tmp_path):
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고", template_path="/공고.hwpx", filename_pattern="공고-{{ID}}"))
    reg.save(Job(name="요청", template_path="/요청.hwpx", filename_pattern="요청-{{ID}}"))
    return reg


def _vm(tmp_path, **kw):
    return MatrixRunViewModel(_registry(tmp_path), **kw)


def test_job_multiselect(tmp_path):
    vm = _vm(tmp_path)
    assert set(vm.all_job_names()) == {"공고", "요청"}
    assert vm.selection_count() == 0
    vm.set_job_selected("요청", True)
    vm.set_job_selected("공고", True)
    # 선택 순서는 레지스트리 순서(이름순) 유지.
    assert vm.selected_job_names() == ["공고", "요청"]
    vm.set_job_selected("공고", False)
    assert vm.selected_job_names() == ["요청"]
    assert [j.name for j in vm.selected_jobs()] == ["요청"]


def test_load_file_sets_datasource(tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_text("ID,공고명\n1,전산\n2,비품\n", encoding="utf-8")
    vm = _vm(tmp_path)
    recs = vm.load_file(str(csv))
    assert len(recs) == 2 and vm.datasource is not None
    assert vm.records[0]["공고명"] == "전산"


def test_load_pool_by_name(tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_text("ID\n1\n", encoding="utf-8")
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(DatasetPoolItem(name="6월", kind="excel", opts={"path": str(csv)}))
    vm = _vm(tmp_path, pool_registry=pool)
    assert vm.active_pool_names() == ["6월"]
    recs = vm.load_pool_by_name("6월")
    assert len(recs) == 1 and vm.datasource is not None


def test_validate_reports_all_violations(tmp_path):
    vm = _vm(tmp_path)
    errs = vm.validate([], "")
    assert any("작업" in e for e in errs)
    assert any("데이터" in e for e in errs)
    assert any("레코드" in e for e in errs)
    assert any("저장 폴더" in e for e in errs)


def test_validate_flags_missing_template(tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_text("ID\n1\n", encoding="utf-8")
    vm = _vm(tmp_path)
    vm.set_job_selected("공고", True)  # /공고.hwpx 부재
    vm.load_file(str(csv))
    errs = vm.validate([0], str(tmp_path / "out"))
    assert any("찾을 수 없는" in e for e in errs)


def test_validate_flags_empty_template_path(tmp_path):
    """템플릿 경로가 비어 있는 작업도 게이트에서 막는다(생성 단계로 흘리지 않음)."""
    csv = tmp_path / "d.csv"
    csv.write_text("ID\n1\n", encoding="utf-8")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="무템플릿", template_path="", filename_pattern="d-{{ID}}"))
    vm = MatrixRunViewModel(reg)
    vm.set_job_selected("무템플릿", True)
    vm.load_file(str(csv))
    errs = vm.validate([0], str(tmp_path / "out"))
    assert any("템플릿이 없거나" in e for e in errs)


def test_validate_passes_when_ready(tmp_path):
    tpl = tmp_path / "t.hwpx"
    _template(tpl)
    csv = tmp_path / "d.csv"
    csv.write_text("ID\n1\n", encoding="utf-8")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="작업", template_path=str(tpl), filename_pattern="d-{{ID}}"))
    vm = MatrixRunViewModel(reg)
    vm.set_job_selected("작업", True)
    vm.load_file(str(csv))
    assert vm.validate([0], str(tmp_path / "out")) == []


def test_validate_hard_gates_matrix_template_drift_but_blank_is_quiet(tmp_path):
    tpl = tmp_path / "t.hwpx"
    _template(tpl, ["공고명", "비고"])
    csv = tmp_path / "d.csv"
    csv.write_text("name\n테스트\n", encoding="utf-8")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="작업", template_path=str(tpl), mapping=MappingProfile(mappings=[
        FieldMapping("공고명", "name"), FieldMapping("비고", type="blank")
    ])))
    vm = MatrixRunViewModel(reg)
    vm.set_job_selected("작업", True)
    vm.load_file(str(csv))
    assert vm.validate([0], str(tmp_path / "out")) == []
    _template(tpl, ["공고명", "비고", "신규"])
    assert any("구조 드리프트" in e and "신규" in e for e in vm.validate([0], str(tmp_path / "out")))


def test_generate_boundary_rechecks_after_validate_toctou(tmp_path):
    tpl = tmp_path / "t.hwpx"
    _template(tpl, ["공고명"])
    csv = tmp_path / "d.csv"
    csv.write_text("name\n테스트\n", encoding="utf-8")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="작업", template_path=str(tpl), mapping=MappingProfile(mappings=[
        FieldMapping("공고명", "name")
    ]), filename_pattern="d-{{seq}}"))
    vm = MatrixRunViewModel(reg)
    vm.set_job_selected("작업", True)
    vm.load_file(str(csv))
    out = tmp_path / "out"
    assert vm.validate([0], str(out)) == []

    # validate 직후 외부 편집 — worker/API 생성 경계가 다시 읽어 원자 차단해야 한다.
    _template(tpl, ["공고명", "검증후유입"])
    with pytest.raises(ValueError, match="검증후유입"):
        generate_matrix(vm.selected_jobs(), vm.datasource, [0], str(out))
    assert not out.exists()


def test_output_conflicts_ring1_reports_existing_subfolder_targets(tmp_path):
    """RC-02 — 뷰모델이 작업별 하위폴더 규칙으로 기존 파일 충돌을 보고(무변형, 링1).

    위젯 확인 대화상자의 원천: 빈 목록이면 확인 없이 진행, 비지 않으면 사용자 확정
    후에만 overwrite=True 로 생성한다.
    """
    tpl = tmp_path / "t.hwpx"
    _template(tpl, ["공고명"])
    csv = tmp_path / "d.csv"
    csv.write_text("공고명\n전산\n", encoding="utf-8")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="작업", template_path=str(tpl), mapping=MappingProfile(mappings=[
        FieldMapping("공고명", "공고명")
    ]), filename_pattern="d-{{공고명}}"))
    vm = MatrixRunViewModel(reg)
    vm.set_job_selected("작업", True)
    vm.load_file(str(csv))

    out = tmp_path / "out"
    assert vm.output_conflicts([0], str(out)) == []  # 아무것도 없으면 무충돌

    (out / "작업").mkdir(parents=True)
    sentinel = out / "작업" / "d-전산.hwpx"
    sentinel.write_bytes(b"user-edited")
    assert vm.output_conflicts([0], str(out)) == [str(sentinel)]
    assert sentinel.read_bytes() == b"user-edited"  # 검출은 무변형


# --------------------------- UD-04: 작업별 필드 3상태 배지·미입력 확인 게이트(ADR-B/E)
def _missing_job(tmp_path):
    """공고명=채움 · 추정가격=미입력(빈값) · 비고=의도적 빈칸 인 단일 작업 VM."""
    tpl = tmp_path / "t.hwpx"
    _template(tpl, ["공고명", "추정가격", "비고"])
    csv = tmp_path / "d.csv"
    csv.write_text("공고명,추정가격\n전산장비,\n", encoding="utf-8")  # 추정가격 빈값
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="작업", template_path=str(tpl), mapping=MappingProfile(mappings=[
        FieldMapping("공고명", "공고명"),
        FieldMapping("추정가격", "추정가격"),
        FieldMapping("비고", type="blank"),
    ]), filename_pattern="d-{{공고명}}"))
    vm = MatrixRunViewModel(reg)
    vm.set_job_selected("작업", True)
    vm.load_file(str(csv))
    return vm


def test_field_summaries_three_states_reuse_run_layer(tmp_path):
    """작업별 필드 스냅샷이 단일 실행과 같은 3상태(채움/빈칸/미입력)를 집계한다."""
    vm = _missing_job(tmp_path)
    summaries = vm.field_summaries([0])
    assert len(summaries) == 1
    js = summaries[0]
    assert js.job_name == "작업"
    states = {s.name: s.state for s in js.field_states}
    assert states == {"공고명": "filled", "추정가격": "missing", "비고": "blank"}
    assert (js.filled, js.blank, js.missing, js.drift) == (1, 1, 1, 0)
    assert js.unmet() == ["추정가격"]


def test_field_summaries_empty_without_data(tmp_path):
    """데이터 미겨눔이면 빈 집계 — 게이트는 열림(기본 전제는 validate 가 소유)."""
    vm = _vm(tmp_path)
    vm.set_job_selected("공고", True)
    assert vm.field_summaries([0]) == []
    assert vm.unmet_missing([0]) == []
    assert vm.missing_gate([0]).enabled is True


def test_missing_gate_blocks_until_ack_and_toggles(tmp_path):
    """미확인 미입력이 게이트를 닫고(재진술 문구), 확인/철회가 게이트를 여닫는다(ADR-E)."""
    vm = _missing_job(tmp_path)
    assert vm.unmet_missing([0]) == [("작업", "추정가격")]
    gate = vm.missing_gate([0])
    assert gate.enabled is False and gate.level == "warn"
    assert "추정가격" in gate.text and "작업" in gate.text

    vm.acknowledge("작업", "추정가격")
    assert vm.unmet_missing([0]) == []
    assert vm.missing_gate([0]).enabled is True

    vm.unacknowledge("작업", "추정가격")               # 철회 → 재계상
    assert vm.missing_gate([0]).enabled is False


def test_ack_is_reset_on_new_data(tmp_path):
    """새 데이터 겨눔이 확인을 초기화한다 — 스테일 ack 로 게이트가 무단 통과하지 않는다."""
    vm = _missing_job(tmp_path)
    vm.acknowledge("작업", "추정가격")
    assert vm.missing_gate([0]).enabled is True
    vm.load_file(str(tmp_path / "d.csv"))              # 재겨눔 → reset_acks
    assert vm.missing_gate([0]).enabled is False


def test_missing_ack_is_keyed_per_job(tmp_path):
    """확인은 (작업, 필드) 단위 — 한 작업 확인이 다른 작업 미입력을 통과시키지 않는다."""
    tpl = tmp_path / "t.hwpx"
    _template(tpl, ["추정가격"])
    csv = tmp_path / "d.csv"
    csv.write_text("id,추정가격\n1,\n", encoding="utf-8")  # 추정가격 빈값 → 두 작업 모두 미입력
    reg = JobRegistry(tmp_path / "jobs")
    mp = MappingProfile(mappings=[FieldMapping("추정가격", "추정가격")])
    reg.save(Job(name="공고", template_path=str(tpl), mapping=mp, filename_pattern="공고-{{seq}}"))
    reg.save(Job(name="요청", template_path=str(tpl), mapping=mp, filename_pattern="요청-{{seq}}"))
    vm = MatrixRunViewModel(reg)
    vm.set_job_selected("공고", True)
    vm.set_job_selected("요청", True)
    vm.load_file(str(csv))
    assert vm.unmet_missing([0]) == [("공고", "추정가격"), ("요청", "추정가격")]
    vm.acknowledge("공고", "추정가격")                  # 공고만 확인
    assert vm.unmet_missing([0]) == [("요청", "추정가격")]
    assert vm.missing_gate([0]).enabled is False       # 요청 미확인 → 여전히 닫힘
