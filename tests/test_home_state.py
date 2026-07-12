"""홈 ViewModel — Qt 불필요(헤드리스). 목록 성형·메타·선택·통지 계약을 못박는다.

이 표면(JobRow 필드 + 메서드)이 목업 홈이 겨누는 seam 이므로, 위젯 없이 여기서 회귀를 잡는다.
"""
from __future__ import annotations

from lxml import etree

from hwpxfiller.core.authoring import compile_document
from hwpxfiller.core.fields import FieldDocument
from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.template_status import CompileState
from hwpxfiller.gui.home_state import (
    BADGE_ERROR,
    BADGE_MISSING,
    BADGE_RAW,
    BADGE_READY,
    HomeViewModel,
    JobRow,
)
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage


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
    assert "최근 실행 2026-07-09 15:42" == g.last_run_display
    assert g.meta_line() == "템플릿 t.hwpx · 필드 1개 · 파일명 공고-{{ID}}"

    n = rows["낙찰"]
    assert n.template_name == "—"          # 빈 템플릿 경로
    assert n.template_missing is False      # 경로 없음 = 부재 배지 아님
    assert n.last_run_display == "아직 실행 안 함"


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


def test_corrupt_job_file_surfaces_as_corrupt_row_not_crash(tmp_path):
    """손상 .job.json → 홈 VM 이 죽지 않고 '손상됨' 행으로 시끄럽게 노출한다(RC-05)."""
    reg = _reg(tmp_path)
    (tmp_path / "깨진작업.job.json").write_text('{"name": "깨진', encoding="utf-8")

    vm = HomeViewModel(reg)  # 생성자 refresh 가 JSONDecodeError 로 죽지 않는다
    assert {r.name for r in vm.rows()} == {"공고서", "낙찰"}  # 정상 작업은 계속 표시
    crows = vm.corrupt_rows()
    assert len(crows) == 1
    assert crows[0].file_name == "깨진작업.job.json"  # 원인 파일 지목
    assert crows[0].error                              # 오류 사유 동반
    assert "읽을 수 없습니다" in crows[0].detail_line()


def test_only_corrupt_files_is_not_empty_state(tmp_path):
    """손상 파일만 있어도 빈 상태로 위장하지 않는다 — 손상 행이 보여야 한다(RC-05)."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "부서진.job.json").write_text("[1, 2, 3]", encoding="utf-8")
    vm = HomeViewModel(JobRegistry(jobs_dir))
    assert vm.rows() == []
    assert vm.corrupt_rows()
    assert not vm.is_empty()  # 빈 상태 패널 대신 손상 행이 노출돼야 한다


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
    assert k.recent_run.startswith("07-09") and "공고서" in k.recent_run  # 최신 실행


def test_dashboard_kpi_no_runs_no_txt(tmp_path):
    from hwpxfiller.core.job import Job, JobRegistry

    reg = JobRegistry(tmp_path / "j")
    reg.save(Job(name="미실행", template_path=""))
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


# ============================================================ C4: 컴파일 상태 배지
# JobRow.compile_badge/compile_state 는 C2 compile_status 에서 refresh 마다 재산출된다.
# 여기서 4-상태 + 부재 + 재편집 드리프트를 헤드리스로 못박는다(위젯 불필요).

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"


def _pkg(section_inner: str) -> HwpxPackage:
    sec = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>'
    ).encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries[SECTION] = sec
    return pkg


def _save(pkg: HwpxPackage, path) -> str:
    pkg.save(str(path))
    return str(path)


def _raw_hwpx(tmp_path) -> str:
    """필드 0개 + 평문 토큰(미컴파일 원문) → RAW."""
    xml = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
    return _save(_pkg(xml), tmp_path / "raw.hwpx")


def _compiled_hwpx(tmp_path, name="compiled.hwpx") -> str:
    """평문 토큰을 컴파일만(채우지 않음) → COMPILED."""
    xml = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
    pkg, _ = compile_document(_pkg(xml))
    return _save(pkg, tmp_path / name)


def _partial_hwpx(tmp_path) -> str:
    """컴파일 + 값 자리에 미해결 토큰 → 잔존 토큰 有 → PARTIAL."""
    xml = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
    pkg, _ = compile_document(_pkg(xml))
    doc = FieldDocument(pkg.entries[SECTION])
    doc.set_field("계약명", "{{미결}}")
    pkg.entries[SECTION] = doc.to_bytes()
    return _save(pkg, tmp_path / "partial.hwpx")


def _filled_hwpx(tmp_path) -> str:
    """컴파일 + 실제 값 주입 → FILLED."""
    xml = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
    pkg, _ = compile_document(_pkg(xml))
    doc = FieldDocument(pkg.entries[SECTION])
    doc.set_field("계약명", "정보시스템 구축 사업")
    pkg.entries[SECTION] = doc.to_bytes()
    return _save(pkg, tmp_path / "filled.hwpx")


def _row(template_path: str) -> JobRow:
    return JobRow.from_job(Job(name="작업", template_path=template_path))


def test_badge_raw(tmp_path):
    row = _row(_raw_hwpx(tmp_path))
    assert row.compile_state == CompileState.RAW
    assert row.compile_badge == BADGE_RAW


def test_badge_partial_counts_leftover_tokens(tmp_path):
    row = _row(_partial_hwpx(tmp_path))
    assert row.compile_state == CompileState.PARTIAL
    # N = skipped_n + stray_n + compilable_n; 이 픽스처는 stray 1개.
    assert row.compile_badge == "⚠ 미확인 토큰 1개"


def test_badge_compiled_is_ready(tmp_path):
    row = _row(_compiled_hwpx(tmp_path))
    assert row.compile_state == CompileState.COMPILED
    assert row.compile_badge == BADGE_READY


def test_badge_filled_is_ready(tmp_path):
    row = _row(_filled_hwpx(tmp_path))
    assert row.compile_state == CompileState.FILLED
    assert row.compile_badge == BADGE_READY


def test_badge_missing_template_does_not_call_compile_status(tmp_path):
    # 존재하지 않는 경로 → 부재 배지, compile_state None(compile_status 미호출).
    row = _row(str(tmp_path / "does_not_exist.hwpx"))
    assert row.template_missing is True
    assert row.compile_state is None
    assert row.compile_badge == BADGE_MISSING


def test_badge_empty_path_has_no_badge():
    row = _row("")
    assert row.template_missing is False
    assert row.compile_state is None
    assert row.compile_badge == ""


def test_badge_corrupt_template_degrades_loudly(tmp_path):
    # 손상 .hwpx(zip 아님) → 조용한 ✅ 금지, 시끄러운 오류 배지로 강등.
    bad = tmp_path / "corrupt.hwpx"
    bad.write_bytes(b"not a real hwpx zip")
    row = _row(str(bad))
    assert row.compile_state is None
    assert row.compile_badge == BADGE_ERROR


def test_is_runnable_gates_on_badge_level(tmp_path):
    """UD-03 — 실행 진입 판정은 badge_level 단일 술어: danger(부재·손상·오류·미설정)만
    차단하고 RAW·PARTIAL·COMPILED·FILLED 는 진입 가능(카드 CTA·더블클릭 공유 술어)."""
    assert _row(_raw_hwpx(tmp_path)).is_runnable() is True          # RAW(muted)
    assert _row(_partial_hwpx(tmp_path)).is_runnable() is True      # PARTIAL(warn)
    assert _row(_compiled_hwpx(tmp_path)).is_runnable() is True     # COMPILED(ok)
    assert _row(_filled_hwpx(tmp_path)).is_runnable() is True       # FILLED(ok)
    # 실행 불가(danger) — 세 경로 모두 compile_state None → 차단.
    assert _row(str(tmp_path / "does_not_exist.hwpx")).is_runnable() is False  # 부재
    assert _row("").is_runnable() is False                          # 템플릿 미설정
    bad = tmp_path / "corrupt.hwpx"
    bad.write_bytes(b"not a real hwpx zip")
    assert _row(str(bad)).is_runnable() is False                    # 손상/컴파일 오류


def test_badge_recomputed_on_refresh_reflects_drift(tmp_path):
    """COMPILED 템플릿에 stray 토큰을 주입 → refresh 재산출 → 배지가 ⚠ 로 뒤집힌다.

    저장 도장이 아니라 매 refresh 재계산임을 증명(한글 재편집 드리프트 반영).
    """
    path = _compiled_hwpx(tmp_path, name="drift.hwpx")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="드리프트", template_path=path))
    vm = HomeViewModel(reg)
    assert vm.rows()[0].compile_badge == BADGE_READY  # 처음엔 실행 준비

    # 사용자가 한글에서 새 평문 토큰을 타이핑(파일 밖에서 드리프트).
    pkg = HwpxPackage.open(path)
    root = etree.fromstring(pkg.entries[SECTION])
    newp = etree.SubElement(root, f"{{{HP}}}p")
    run = etree.SubElement(newp, f"{{{HP}}}run")
    t = etree.SubElement(run, f"{{{HP}}}t")
    t.text = "추가항목: {{추가}}"
    pkg.entries[SECTION] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    pkg.save(path)

    vm.refresh()  # 재적재 → JobRow.from_job → compile_status 재산출
    row = vm.rows()[0]
    assert row.compile_state == CompileState.PARTIAL
    assert row.compile_badge.startswith("⚠ 미확인 토큰")  # ✅ → ⚠ 로 뒤집힘
