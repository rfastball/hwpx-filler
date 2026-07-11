"""홈 ViewModel — Qt 불필요(헤드리스). 목록 성형·메타·선택·통지 계약을 못박는다.

이 표면(JobRow 필드 + 메서드)이 목업 홈이 겨누는 seam 이므로, 위젯 없이 여기서 회귀를 잡는다.
"""
from __future__ import annotations

from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.home_state import HomeViewModel, JobRow


def _reg(tmp_path) -> JobRegistry:
    reg = JobRegistry(tmp_path)
    reg.save(Job(
        name="공고서",
        template_path="/none/t.hwpx",  # 존재 안 함 → template_missing
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", sources=["bidNtceNm"])]),
        filename_pattern="공고-{{ID}}",
        last_run_at="2026-07-09T15:42:00",
    ))
    reg.save(Job(name="낙찰", template_path="", filename_pattern="낙찰-{{ID}}"))
    return reg


def test_rows_shape_meta_and_missing_template(tmp_path):
    vm = HomeViewModel(_reg(tmp_path))
    rows = {r.name: r for r in vm.rows()}
    assert vm.count_label() == "2건"
    assert not vm.is_empty()

    g = rows["공고서"]
    assert g.template_name == "t.hwpx"
    assert g.template_missing is True
    assert g.field_count == 1
    assert "최근 집행 2026-07-09 15:42" == g.last_run_display
    assert g.meta_line() == "템플릿 t.hwpx · 필드 1개 · 파일명 공고-{{ID}}"

    n = rows["낙찰"]
    assert n.template_name == "—"          # 빈 템플릿 경로
    assert n.template_missing is False      # 경로 없음 = 부재 배지 아님
    assert n.last_run_display == "아직 집행 안 함"


def test_empty_registry(tmp_path):
    vm = HomeViewModel(JobRegistry(tmp_path))
    assert vm.is_empty() and vm.count_label() == "" and vm.rows() == []


def test_selection_and_delete_notify(tmp_path):
    vm = HomeViewModel(_reg(tmp_path))
    beats = []
    vm.subscribe(lambda: beats.append(1))

    vm.select("공고서")
    assert vm.has_selection() and vm.selected_name == "공고서"
    vm.select("없는작업")               # 존재하지 않는 이름은 선택 해제
    assert not vm.has_selection()

    vm.select("낙찰")
    vm.delete("낙찰")                    # 선택 대상 삭제 → 해제 + 재적재 통지
    assert not vm.has_selection()
    assert vm.count_label() == "1건"
    assert beats  # delete → refresh → _notify


def test_refresh_preserves_live_selection(tmp_path):
    reg = _reg(tmp_path)
    vm = HomeViewModel(reg)
    vm.select("공고서")
    reg.save(Job(name="추가작업", template_path=""))
    vm.refresh()
    assert vm.selected_name == "공고서"  # 여전히 존재 → 선택 보존
    assert vm.count_label() == "3건"


def test_jobrow_from_job_direct():
    row = JobRow.from_job(Job(name="x", template_path="", filename_pattern="p-{{ID}}"))
    assert row.name == "x" and row.template_name == "—" and row.field_count == 0


def test_dashboard_kpi_from_real_data(tmp_path):
    from hwpxfiller.core.text_registry import TextTemplateRegistry

    td = tmp_path / "tt"
    td.mkdir()
    (td / "온나라.txt").write_text("{{a}}", encoding="utf-8")
    vm = HomeViewModel(_reg(tmp_path), TextTemplateRegistry(td))
    k = vm.kpi()
    assert k.job_count == 2
    assert k.missing_template_count == 1        # '/none/t.hwpx' 부재
    assert k.txt_template_count == 1
    assert k.recent_run.startswith("07-09") and "공고서" in k.recent_run  # 최신 집행


def test_dashboard_kpi_no_runs_no_txt(tmp_path):
    from hwpxfiller.core.job import Job, JobRegistry

    reg = JobRegistry(tmp_path / "j")
    reg.save(Job(name="미집행", template_path=""))
    vm = HomeViewModel(reg)  # txt 레지스트리 없음
    k = vm.kpi()
    assert k.recent_run == "—" and k.txt_template_count == 0


def test_txt_rows(tmp_path):
    from hwpxfiller.core.text_registry import TextTemplateRegistry

    td = tmp_path / "tt"
    td.mkdir()
    (td / "기안.txt").write_text("{{공고명}} {{담당자}}", encoding="utf-8")
    vm = HomeViewModel(_reg(tmp_path), TextTemplateRegistry(td))
    rows = vm.txt_rows()
    assert len(rows) == 1 and rows[0].name == "기안" and rows[0].field_count == 2
