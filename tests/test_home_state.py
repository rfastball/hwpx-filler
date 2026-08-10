"""홈 ViewModel — Qt 불필요(헤드리스). 목록 성형·메타·선택·통지 계약을 못박는다.

이 표면(JobRow 필드 + 메서드)이 목업 홈이 겨누는 seam 이므로, 위젯 없이 여기서 회귀를 잡는다.
"""
from __future__ import annotations

from lxml import etree

from hwpxfiller.core.authoring import compile_document
from hwpxfiller.core.fields import FieldDocument
from hwpxfiller.core.job import Job
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.template_status import CompileState
from hwpxfiller.gui.home_state import (
    BADGE_ERROR,
    BADGE_MISSING,
    BADGE_RAW,
    BADGE_READY,
    MODE_HWPX,
    MODE_TXT,
    NO_SOURCE_LABEL,
    VIEW_ALL,
    VIEW_FAVORITES,
    VIEW_NEEDS,
    VIEW_RECENT,
    HomeViewModel,
    JobRow,
    field_binding_rows,
    library_health,
    library_health_causes,
    library_mode_of,
)
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage


def _reg(tmp_path) -> JobRegistry:
    reg = JobRegistry(tmp_path)
    reg.save(Job(
        name="공고서",
        template_path="/none/t.hwpx",  # 존재 안 함 → template_missing
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="bidNtceNm")]),
        filename_pattern="공고-{{ID}}",
        last_run_at="2026-07-09T15:42:00",
    ))
    reg.save(Job(name="낙찰", template_path="", filename_pattern="낙찰-{{ID}}"))
    return reg


def test_rows_shape_meta_and_missing_template(tmp_path):
    vm = HomeViewModel(_reg(tmp_path), engine=make_hwpx_engine())
    rows = {r.name: r for r in vm.rows()}
    assert vm.count_label() == "2건"
    assert not vm.is_empty()

    g = rows["공고서"]
    assert g.template_name == "t.hwpx"
    assert g.template_missing is True
    assert g.field_count == 1
    # 최근 사용 문구는 방식이 정한다(§19.4 · `last_use_label` 단일 출처) — hwpx 는 생성
    # 완주에서 찍히므로 "실행"이 아니라 **성공한 실행**이라고 말한다.
    assert g.last_run_display == "마지막 성공 실행 2026-07-09"
    assert g.meta_line() == "템플릿 t.hwpx · 필드 1개 · 파일명 공고-{{ID}}"

    n = rows["낙찰"]
    assert n.template_name == "—"          # 빈 템플릿 경로
    assert n.template_missing is False      # 경로 없음 = 부재 배지 아님
    assert n.last_run_display == "성공한 실행 없음"


def test_empty_registry(tmp_path):
    vm = HomeViewModel(JobRegistry(tmp_path), engine=make_hwpx_engine())
    assert vm.is_empty() and vm.count_label() == "" and vm.rows() == []


def test_selection_and_delete_notify(tmp_path):
    vm = HomeViewModel(_reg(tmp_path), engine=make_hwpx_engine())
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
    vm = HomeViewModel(reg, engine=make_hwpx_engine())
    vm.select("공고서")
    reg.save(Job(name="추가작업", template_path=""))
    vm.refresh()
    assert vm.selected_name == "공고서"  # 여전히 존재 → 선택 보존
    assert vm.count_label() == "3건"


def test_jobrow_from_job_direct():
    row = JobRow.from_job(Job(name="x", template_path="", filename_pattern="p-{{ID}}"), engine=make_hwpx_engine())
    assert row.name == "x" and row.template_name == "—" and row.field_count == 0


def test_corrupt_job_file_surfaces_as_corrupt_row_not_crash(tmp_path):
    """손상 .job.json → 홈 VM 이 죽지 않고 '손상됨' 행으로 시끄럽게 노출한다(RC-05)."""
    reg = _reg(tmp_path)
    (tmp_path / "깨진작업.job.json").write_text('{"name": "깨진', encoding="utf-8")

    vm = HomeViewModel(reg, engine=make_hwpx_engine())  # 생성자 refresh 가 JSONDecodeError 로 죽지 않는다
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
    vm = HomeViewModel(JobRegistry(jobs_dir), engine=make_hwpx_engine())
    assert vm.rows() == []
    assert vm.corrupt_rows()
    assert not vm.is_empty()  # 빈 상태 패널 대신 손상 행이 노출돼야 한다


def test_dashboard_kpi_from_real_data_and_empty_defaults(tmp_path):
    from hwpxfiller.core.text_registry import TextTemplateRegistry

    td = tmp_path / "tt"
    td.mkdir()
    (td / "온나라.txt").write_text("{{a}}", encoding="utf-8")
    vm = HomeViewModel(_reg(tmp_path), TextTemplateRegistry(td), engine=make_hwpx_engine())
    k = vm.kpi()
    assert k.job_count == 2
    assert k.missing_template_count == 1        # '/none/t.hwpx' 부재
    assert k.txt_template_count == 1
    assert k.recent_run.startswith("07-09") and "공고서" in k.recent_run  # 최신 실행
    reg = JobRegistry(tmp_path / "no-runs")
    reg.save(Job(name="미실행", template_path=""))
    empty = HomeViewModel(reg, engine=make_hwpx_engine()).kpi()  # txt 레지스트리 없음
    assert empty.recent_run == "—" and empty.txt_template_count == 0


def test_txt_rows(tmp_path):
    from hwpxfiller.core.text_registry import TextTemplateRegistry

    td = tmp_path / "tt"
    td.mkdir()
    (td / "기안.txt").write_text("{{공고명}} {{담당자}}", encoding="utf-8")
    vm = HomeViewModel(_reg(tmp_path), TextTemplateRegistry(td), engine=make_hwpx_engine())
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
    return JobRow.from_job(Job(name="작업", template_path=template_path), engine=make_hwpx_engine())


def test_badge_matrix_also_owns_the_runnable_decision(tmp_path):
    """컴파일 상태 → 배지·실행 가능 판정은 하나의 표로 같이 검증한다."""
    bad = tmp_path / "corrupt.hwpx"
    bad.write_bytes(b"not a real hwpx zip")
    cases = [
        (_raw_hwpx(tmp_path), CompileState.RAW, BADGE_RAW, False, True),
        (_partial_hwpx(tmp_path), CompileState.PARTIAL, "⚠ 미확인 토큰 1개", False, True),
        (_compiled_hwpx(tmp_path), CompileState.COMPILED, BADGE_READY, False, True),
        (_filled_hwpx(tmp_path), CompileState.FILLED, BADGE_READY, False, True),
        (str(tmp_path / "does_not_exist.hwpx"), None, BADGE_MISSING, True, False),
        ("", None, "", False, False),
        (str(bad), None, BADGE_ERROR, False, False),
    ]
    for path, state, badge, missing, runnable in cases:
        row = _row(path)
        assert (row.compile_state, row.compile_badge) == (state, badge)
        assert row.template_missing is missing
        assert row.is_runnable() is runnable


def test_badge_recomputed_on_refresh_reflects_drift(tmp_path):
    """COMPILED 템플릿에 stray 토큰을 주입 → refresh 재산출 → 배지가 ⚠ 로 뒤집힌다.

    저장 도장이 아니라 매 refresh 재계산임을 증명(한글 재편집 드리프트 반영).
    """
    path = _compiled_hwpx(tmp_path, name="drift.hwpx")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="드리프트", template_path=path))
    vm = HomeViewModel(reg, engine=make_hwpx_engine())
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


# ============================================================ 작업 브라우저(tag facet)
# JOB_BROWSER_DESIGN §4 — 태그 발견(D3)·패싯 의미론(D10). group-by 렌즈(D4·D12)는 재작성
# F2 PR-A 에서 은퇴했다(지도 §10.8 판정 B · §9.4 A안): 「모든 작업」 보기의 primary grouping
# 은 사용자 group 하나뿐이고, 태그는 좁히는 축으로만 남는다. 그래서 facet 의미론은 이제
# ``library_sections()`` 결과로 관찰한다. 위젯 없이 링1 VM 에서 회귀를 잡는다.
from hwpxfiller.gui.home_state import discover_tag_axes  # noqa: E402
from hwpxfiller.external.hwpx_engine import make_hwpx_engine


def _tagged_reg(tmp_path) -> JobRegistry:
    """금액구간·낙찰방법 두 축이 섞인 코퍼스(일부 미태깅)."""
    reg = JobRegistry(tmp_path)
    reg.save(Job(name="적격-소액", template_path="", tags={"금액구간": "1억미만", "낙찰방법": "적격심사"}))
    reg.save(Job(name="적격-고시", template_path="", tags={"금액구간": "고시이상", "낙찰방법": "적격심사"}))
    reg.save(Job(name="협상-소액", template_path="", tags={"금액구간": "1억미만", "낙찰방법": "협상"}))
    reg.save(Job(name="무태그", template_path="", tags={}))  # 미태깅 — facet 밖
    return reg


def _shown(vm) -> "set[str]":
    """현재 축(보기·방식·검색·facet)이 남긴 작업 이름들."""
    return {r.name for sec in vm.library_sections() for r in sec.rows}


def test_axes_discovered_from_tags_union(tmp_path):
    """축은 authored 레지스트리가 아니라 붙은 태그 키의 합집합에서 발견(D3), 정렬."""
    vm = HomeViewModel(_tagged_reg(tmp_path), engine=make_hwpx_engine())
    assert vm.axes() == ["금액구간", "낙찰방법"]


def test_group_by_lens_is_retired_and_every_axis_is_a_facet(tmp_path):
    """렌즈 은퇴(§10.8 판정 B) — 축을 섹션으로 쓰는 소비자가 없으니 전부 facet 이다.

    씨앗 축 상수·`active_group_by`·`grouped_rows`·`set_group_by` 는 함께 죽었다. 남겨 두면
    아무도 보지 않는 제2 구획 축이 되어 다음 세션이 되살린다.
    """
    vm = HomeViewModel(_tagged_reg(tmp_path), engine=make_hwpx_engine())
    for dead in ("active_group_by", "effective_group_by", "grouped_rows", "set_group_by"):
        assert not hasattr(vm, dead), f"은퇴한 group-by 표면이 남아 있습니다: {dead}"
    # 승계 의무 ①: facet 칩은 그대로 살아 **모든 축**으로 좁히기가 계속 가능하다.
    assert {f.axis for f in vm.facets()} == {"금액구간", "낙찰방법"}


def test_untagged_corpus_is_degenerate_flat(tmp_path):
    """태그 0 → 축 0 → facet UI 전무 + 헤더 없는 평면(퇴화-코퍼스 불변식, 승계 의무 ③)."""
    vm = HomeViewModel(_reg(tmp_path), engine=make_hwpx_engine())  # 태그도 그룹도 없는 기존 픽스처
    assert vm.axes() == []
    assert vm.facets() == []
    secs = vm.library_sections()
    assert len(secs) == 1 and secs[0].value == "" and not secs[0].is_untagged


def test_library_renders_despite_type_corrupt_job(tmp_path):
    """타입 손상 작업 1건이 목록·facet 렌더의 지뢰가 되지 않는다(내구성 라운드 지뢰 방어).

    강화된 from_dict 경계가 손상(비문자열 tags 값)을 corrupt_rows 로 loud 격리하므로
    library_sections()/facets() 는 정상 작업만 보고 혼합타입 sorted 크래시 없이 렌더된다."""
    import json as _json

    reg = JobRegistry(tmp_path)
    reg.save(Job(name="정상", template_path="", tags={"금액구간": "1억미만"}))
    (tmp_path / "정수태그.job.json").write_text(
        _json.dumps({"name": "정수태그", "tags": {"금액구간": 123}}), encoding="utf-8"
    )
    vm = HomeViewModel(reg, engine=make_hwpx_engine())
    assert [r.name for r in vm.rows()] == ["정상"]  # 정상만 rows
    assert len(vm.corrupt_rows()) == 1              # 손상은 loud 격리
    assert vm.library_sections()                    # 혼합타입 크래시 없이 구획 반환
    assert isinstance(vm.facets(), list)


def test_facets_carry_every_axis_with_counts(tmp_path):
    """발견된 모든 축이 facet 으로, 값별 건수 동반(D10)."""
    vm = HomeViewModel(_tagged_reg(tmp_path), engine=make_hwpx_engine())
    facets = {f.axis: {v.value: v.count for v in f.values} for f in vm.facets()}
    assert set(facets) == {"금액구간", "낙찰방법"}
    assert facets["낙찰방법"] == {"적격심사": 2, "협상": 1}
    assert facets["금액구간"] == {"1억미만": 2, "고시이상": 1}


def test_facet_filter_narrows_list_and_notifies(tmp_path):
    """facet 토글 → 목록이 좁혀지고 재렌더 통지(select 와 달리 표시가 바뀌므로)."""
    vm = HomeViewModel(_tagged_reg(tmp_path), engine=make_hwpx_engine())
    beats = []
    vm.subscribe(lambda: beats.append(1))
    vm.toggle_facet("낙찰방법", "적격심사")
    assert beats  # 통지됨
    assert _shown(vm) == {"적격-소액", "적격-고시"}  # 협상·무태그 제외
    active = {v.value for f in vm.facets() for v in f.values if v.active}
    assert active == {"적격심사"}


def test_facet_internal_or_cross_and(tmp_path):
    """facet 내 OR(같은 축 여러 값), facet 간 AND(다른 축은 모두 통과)."""
    reg = JobRegistry(tmp_path)
    reg.save(Job(name="a", template_path="", tags={"목적물": "물품", "낙찰방법": "적격심사"}))
    reg.save(Job(name="b", template_path="", tags={"목적물": "용역", "낙찰방법": "적격심사"}))
    reg.save(Job(name="c", template_path="", tags={"목적물": "물품", "낙찰방법": "협상"}))
    vm = HomeViewModel(reg, engine=make_hwpx_engine())
    vm.toggle_facet("목적물", "물품")
    vm.toggle_facet("목적물", "용역")  # 목적물 내 OR → 물품 or 용역
    assert _shown(vm) == {"a", "b", "c"}
    vm.toggle_facet("낙찰방법", "적격심사")  # 축 간 AND
    assert _shown(vm) == {"a", "b"}


def test_facet_own_selection_does_not_narrow_own_counts(tmp_path):
    """표준 패싯 의미론 — 한 facet 의 선택은 그 facet 자신의 카운트를 좁히지 않는다."""
    vm = HomeViewModel(_tagged_reg(tmp_path), engine=make_hwpx_engine())
    vm.toggle_facet("낙찰방법", "적격심사")
    facets = {f.axis: {v.value: v.count for v in f.values} for f in vm.facets()}
    # 낙찰방법 자신의 카운트는 자기 선택에 안 좁혀짐 — 여전히 전체 기준.
    assert facets["낙찰방법"] == {"적격심사": 2, "협상": 1}
    # 그러나 금액구간(다른 축)은 적격심사 제약을 받아 좁혀진다.
    assert facets["금액구간"] == {"1억미만": 1, "고시이상": 1}


def test_clear_and_set_facets_bulk(tmp_path):
    """clear_facets 일괄 해제 · set_facets 일괄 지정(INI 복원, 통지 1회)."""
    vm = HomeViewModel(_tagged_reg(tmp_path), engine=make_hwpx_engine())
    vm.toggle_facet("낙찰방법", "적격심사")
    vm.clear_facets()
    assert vm.active_facets == {}
    beats = []
    vm.subscribe(lambda: beats.append(1))
    vm.set_facets({"낙찰방법": {"협상"}, "빈축": set()})  # 빈 집합은 버려짐
    assert vm.active_facets == {"낙찰방법": {"협상"}}
    assert len(beats) == 1  # 일괄 통지 1회
    assert _shown(vm) == {"협상-소액"}


def test_orphaned_active_facet_surfaces_as_on_chip_count_zero(tmp_path):
    """고아 활성 facet — 어떤 행도 안 지닌 축/값이 렌즈에 남으면 count=0·active=True 로
    표면화돼 사용자가 보고 끌 수 있다(confirm-or-alarm: 범인 필터를 조용히 숨기지 않음).

    시나리오: 낙찰방법=협상 을 INI 에 지속 → 유일한 협상 작업이 삭제/재태깅 → 렌즈가
    active_facets={낙찰방법:{협상}} 복원. axes() 는 그 축을 빼지만 _passes_facets 는
    강제해 목록이 전부 빈다 — 칩이 없으면 범인이 보이지 않는다.
    """
    reg = JobRegistry(tmp_path)
    reg.save(Job(name="적격", template_path="", tags={"금액구간": "1억미만"}))
    vm = HomeViewModel(reg, engine=make_hwpx_engine())
    # 어떤 행도 '낙찰방법' 축을 지니지 않는다 → axes() 에 없다.
    assert "낙찰방법" not in vm.axes()
    # 그런데 렌즈가 그 축/값을 복원했다(삭제된 작업의 잔재).
    vm.set_facets({"낙찰방법": {"협상"}})
    facets = {f.axis: {v.value: (v.count, v.active) for v in f.values} for f in vm.facets()}
    # 고아 축이 FacetAxis 로 표면화되고, 그 값이 켜진(active) count=0 칩으로 보인다.
    assert "낙찰방법" in facets
    assert facets["낙찰방법"]["협상"] == (0, True)
    # 실제로 목록은 이 강제 때문에 비어 보인다 — 칩이 그 범인을 지목한다.
    assert _shown(vm) == set()


def test_facet_counts_unchanged_by_single_pass_rewrite(tmp_path):
    """단일 패스 재작성이 카운트 의미론을 바꾸지 않음(자기 축 제외 보존) — 다축 코퍼스에서
    옛 중첩 스캔과 동일한 결과. 카운트 0 값도 유지된다."""
    vm = HomeViewModel(_tagged_reg(tmp_path), engine=make_hwpx_engine())
    vm.toggle_facet("낙찰방법", "협상")  # 협상: 협상-소액(1억미만)만
    facets = {f.axis: {v.value: v.count for v in f.values} for f in vm.facets()}
    # 낙찰방법 자신은 자기 선택에 안 좁혀짐(자기 축 제외) — 전체 기준.
    assert facets["낙찰방법"] == {"적격심사": 2, "협상": 1}
    # 금액구간(다른 축)은 협상 제약을 받는다: 협상은 1억미만 1건뿐 → 고시이상 count=0 유지.
    assert facets["금액구간"] == {"1억미만": 1, "고시이상": 0}




def test_discover_tag_axes_helper(tmp_path):
    """discover_tag_axes — 축→정렬된 값 리스트(에디터 태그 편집 후보 공급, 링1 순수)."""
    reg = _tagged_reg(tmp_path)
    axes = discover_tag_axes(reg.list_jobs())
    assert axes == {
        "금액구간": ["1억미만", "고시이상"],
        "낙찰방법": ["적격심사", "협상"],
    }
    assert discover_tag_axes([]) == {}


def _library_reg(tmp_path) -> JobRegistry:
    """보기 4종을 가르는 표본 — 즐겨찾기·최근 사용·미사용·확인 필요·txt 매체."""
    reg = JobRegistry(tmp_path)
    tpl = _compiled_hwpx(tmp_path, "lib.hwpx")   # 실 템플릿(건강 판정이 실물을 읽는다)
    # 템플릿(_compiled_hwpx)의 실제 필드에 맞춘 매핑 — 안 맞추면 구조 드리프트로 잡힌다
    # (그게 정상 판정이다: 건강 보기가 실행 차단을 미리 말한다).
    common = dict(mapping=MappingProfile(mappings=[FieldMapping("계약명", "bidNtceNm")]))
    reg.save(Job(name="즐겨공고", template_path=tpl, group="조달",
                 favorited_at="2026-07-20T09:00:00", **common))
    reg.save(Job(name="최근계약", template_path=tpl, group="조달",
                 last_run_at="2026-07-25T09:00:00", **common))
    reg.save(Job(name="미사용문서", template_path=tpl, tags={"물품": "의약품"}, **common))
    reg.save(Job(name="깨진연결", template_path="/none/x.hwpx", **common))   # 확인 필요
    reg.save(Job(name="기안문", template_path=str(tmp_path / "t.txt"), **common))
    return reg


def test_library_views_project_without_new_state(tmp_path):
    """보기 4종은 저장 상태가 아니라 투영이다 — 정렬 근거도 이미 있는 필드뿐."""
    vm = HomeViewModel(_library_reg(tmp_path), engine=make_hwpx_engine())
    counts = vm.library_counts()
    assert counts[VIEW_ALL] == 5 and counts[VIEW_RECENT] == 1
    assert counts[VIEW_FAVORITES] == 1 and counts[VIEW_NEEDS] == 2  # 깨진연결 + txt 아닌 미상

    vm.set_library_view(VIEW_FAVORITES)
    assert [r.name for sec in vm.library_sections() for r in sec.rows] == ["즐겨공고"]
    vm.set_library_view(VIEW_RECENT)
    assert [r.name for sec in vm.library_sections() for r in sec.rows] == ["최근계약"]
    vm.set_library_view(VIEW_NEEDS)
    names = [r.name for sec in vm.library_sections() for r in sec.rows]
    assert "깨진연결" in names
    assert library_health({r.name: r for r in vm.rows()}["깨진연결"])[0] == 3


def test_library_all_view_sections_by_group_and_degenerates(tmp_path):
    """모든 작업만 사용자 group 으로 구획하고, 이름 있는 group 이 없으면 평면으로 퇴화한다."""
    vm = HomeViewModel(_library_reg(tmp_path), engine=make_hwpx_engine())
    vm.set_library_view(VIEW_ALL)
    secs = vm.library_sections()
    assert [s.value for s in secs] == ["조달", ""]          # 「그룹 없음」 마지막
    assert {r.name for r in secs[0].rows} == {"즐겨공고", "최근계약"}

    plain = JobRegistry(tmp_path / "plain")
    plain.save(Job(name="가", template_path=""))
    flat = HomeViewModel(plain, engine=make_hwpx_engine())
    flat.set_library_view(VIEW_ALL)
    assert [s.value for s in flat.library_sections()] == [""]   # 헤더 없는 평면


def test_library_mode_filter_and_search_are_anded(tmp_path):
    """작업 방식 필터는 모든 보기와 AND, 검색은 이름·그룹·태그 값만(§19.6)."""
    vm = HomeViewModel(_library_reg(tmp_path), engine=make_hwpx_engine())
    vm.set_library_mode(MODE_TXT)
    assert {r.name for sec in vm.library_sections() for r in sec.rows} == {"기안문"}
    assert vm.library_counts()[VIEW_ALL] == 1                  # 탭 건수도 방식은 반영

    vm.set_library_mode(MODE_HWPX)
    vm.set_library_query("조달")                               # 그룹 이름으로 검색
    assert {r.name for sec in vm.library_sections() for r in sec.rows} == {"즐겨공고", "최근계약"}
    vm.set_library_query("의약품")                             # 태그 값으로 검색
    assert {r.name for sec in vm.library_sections() for r in sec.rows} == {"미사용문서"}
    # 검색은 탭 건수를 흔들지 않는다(라이브러리에 대한 사실).
    assert vm.library_counts()[VIEW_ALL] == 4
    vm.set_library_query("bidNtceNm")                          # 소스 키는 검색 대상 아님
    assert vm.library_sections()[0].rows == []


def test_unlinked_template_is_not_reported_as_unsupported_media(tmp_path):
    """경로가 빈 작업은 **아직 연결하지 않은** 저작 중 hwpx 작업이다(리뷰 P2).

    "지원하지 않는 작업 방식"으로 진단하면 처방도 틀린다 — 사용자는 「템플릿 다시 연결」로
    복구할 수 있는데 지원 범위 밖이라는 막다른 문안을 받는다.
    """
    reg = JobRegistry(tmp_path / "unlinked")
    reg.save(Job(name="저작중", template_path=""))                 # 미연결(정상 상태)
    reg.save(Job(name="미상", template_path=str(tmp_path / "x.doc")))  # 실제 미상 확장자
    rows = {r.name: r for r in HomeViewModel(reg, engine=make_hwpx_engine()).rows()}
    assert library_health(rows["저작중"]) == (3, "템플릿을 아직 연결하지 않았습니다.")
    assert library_health(rows["미상"])[1] == "템플릿 파일을 찾을 수 없습니다."

    # 미연결은 HWPX 필터에 **남는다**(리뷰 P2): 진단만 내고 사용자가 고치러 오는 필터에서
    # 빼면 손 닿는 곳이 없어진다. 실제 미상 확장자는 그대로 미상이다.
    vm = HomeViewModel(reg, engine=make_hwpx_engine())
    vm.set_library_mode(MODE_HWPX)
    assert "저작중" in {r.name for sec in vm.library_sections() for r in sec.rows}
    assert vm.library_counts()[VIEW_NEEDS] >= 1
    assert library_mode_of(rows["저작중"]) == MODE_HWPX
    assert library_mode_of(rows["미상"]) == ""


def test_partial_template_lands_in_needs_action(tmp_path):
    """미확인 토큰이 남은 템플릿(PARTIAL)은 「확인 필요」에 든다(리뷰 P2).

    기존 신호가 이미 warn 배지로 말하는데 이 보기에서만 빼면 그 경고가 증발한다. 차단은
    하지 않으므로 심각도는 2(§19.7 "확인된 drift" 자리)이고, 문구는 배지를 그대로 쓴다.
    """
    reg = JobRegistry(tmp_path / "partial")
    # 매핑을 템플릿 필드에 맞춘다 — 비워 두면 "매핑 미확정"(3)이 먼저 잡혀 PARTIAL 분기가
    # 가려진다(둘 다 참일 땐 실행이 막히는 쪽이 먼저 말한다).
    reg.save(Job(name="부분컴파일", template_path=_partial_hwpx(tmp_path),
                 mapping=MappingProfile(mappings=[FieldMapping("계약명", "src")])))
    vm = HomeViewModel(reg, engine=make_hwpx_engine())
    row = vm.rows()[0]
    sev, text = library_health(row)
    assert sev == 2 and text == row.compile_badge
    assert vm.library_counts()[VIEW_NEEDS] == 1
    vm.set_library_view(VIEW_NEEDS)
    assert [r.name for sec in vm.library_sections() for r in sec.rows] == ["부분컴파일"]


def test_structure_drift_surfaces_in_needs_action(tmp_path):
    """템플릿 구조가 확정 매핑과 달라지면 「확인 필요」에 든다(리뷰 P2).

    COMPILED 라도 필드가 늘거나 빠지면 실행은 `validate_generate` 가 차단한다 — 건강 보기가
    건강으로 분류하면 사용자는 실행을 눌러 보고서야 안다. 단 **매핑이 아직 없는** 작업은
    "달라진" 게 아니라 "아직 안 맞춘" 상태라 드리프트로 부르지 않는다.
    """
    reg = JobRegistry(tmp_path / "drift")
    tpl = _compiled_hwpx(tmp_path, "drift.hwpx")           # 필드 = 계약명
    reg.save(Job(name="어긋난작업", template_path=tpl,
                 mapping=MappingProfile(mappings=[FieldMapping("없는필드", "src")])))
    reg.save(Job(name="맞춘작업", template_path=tpl,
                 mapping=MappingProfile(mappings=[FieldMapping("계약명", "src")])))
    reg.save(Job(name="매핑없음", template_path=tpl))       # 확정 매핑 0 = 드리프트 아님
    rows = {r.name: r for r in HomeViewModel(reg, engine=make_hwpx_engine()).rows()}
    assert library_health(rows["어긋난작업"]) == (2, "템플릿 구조가 확정 매핑과 달라졌습니다.")
    assert library_health(rows["맞춘작업"])[0] == 0
    # 매핑이 아직 없는 작업은 드리프트가 **아니지만 건강도 아니다**(리뷰 P2): 실행 게이트는
    # 그 상태를 template_only 드리프트로 막으므로 숨기면 숨은 차단이 된다. 이름만 다르게.
    assert library_health(rows["매핑없음"]) == (3, "매핑을 아직 확정하지 않았습니다.")


def test_unreadable_txt_template_is_not_healthy(tmp_path):
    """파일이 있다고 열리는 건 아니다(리뷰 P2) — 깨진 인코딩·`.txt` 디렉터리는 확인 필요."""
    reg = JobRegistry(tmp_path / "txtjobs")
    bad = tmp_path / "깨진.txt"
    bad.write_bytes(bytes([0xFF, 0xFE, 0x80, 0x81]))   # UTF-8 로 못 읽는 바이트열
    as_dir = tmp_path / "폴더.txt"
    as_dir.mkdir()                                    # 존재하지만 읽을 수 없는 경로
    ok = tmp_path / "정상.txt"
    ok.write_text("제목: {{공고명}}", encoding="utf-8")
    for name, path in (("깨짐", bad), ("폴더", as_dir), ("정상", ok)):
        reg.save(Job(name=name, template_path=str(path)))
    rows = {r.name: r for r in HomeViewModel(reg, engine=make_hwpx_engine()).rows()}
    assert library_health(rows["깨짐"]) == (3, "템플릿을 읽을 수 없습니다.")
    assert library_health(rows["폴더"]) == (3, "템플릿을 읽을 수 없습니다.")
    assert library_health(rows["정상"])[0] == 0


def test_unresolved_filename_tokens_surface_in_health(tmp_path):
    """파일명 토큰을 못 채우는 작업은 「확인 필요」에 든다(리뷰 P2).

    실행 게이트가 danger 로 차단하는 **데이터 무관** 상태라 라이브러리에서 먼저 말할 수 있다.
    판정 몸통은 실행 게이트와 공유한다(두 표면이 같은 상태를 다르게 부르지 않게).
    """
    reg = JobRegistry(tmp_path / "tokens")
    tpl = _compiled_hwpx(tmp_path, "tok.hwpx")             # 필드 = 계약명
    mapping = MappingProfile(mappings=[FieldMapping("계약명", "src")])
    reg.save(Job(name="토큰불일치", template_path=tpl, mapping=mapping,
                 filename_pattern="계약-{{추정가격}}"))     # 매핑이 못 채우는 토큰
    reg.save(Job(name="토큰정상", template_path=tpl, mapping=mapping,
                 filename_pattern="계약-{{계약명}}"))
    rows = {r.name: r for r in HomeViewModel(reg, engine=make_hwpx_engine()).rows()}
    assert library_health(rows["토큰불일치"]) == (3, "파일명 패턴의 토큰을 채우지 못합니다.")
    assert library_health(rows["토큰정상"])[0] == 0


def test_health_translation_covers_every_data_independent_gate_reason():
    """**근본 조치**(리뷰 7라운드): 실행 게이트의 데이터-무관 차단 사유를 건강 번역이 전부 덮는다.

    이 PR 의 라운드들은 같은 결함류를 하나씩 잡았다 — 실행은 차단하는데 라이브러리는 건강으로
    분류하는 상태(미연결·못 읽는 템플릿·PARTIAL·구조 드리프트·미해소 토큰·못 읽는 txt).
    개별 대응 대신 **누락을 세는 가드**를 둔다: run_state 가 새 차단 사유(GateState.reason)를
    만들면, home_state 의 번역이 그 이름을 알고 있어야 이 테스트가 통과한다.
    """
    import re
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[1] / "src" / "hwpxfiller" / "gui"
    reasons = set(re.findall(r'reason="([a-z_]+)"', (root / "run_state.py").read_text(encoding="utf-8")))
    assert reasons, "run_state 에서 게이트 사유를 찾지 못했습니다(정규식 stale)."
    covered = (root / "home_state.py").read_text(encoding="utf-8")
    # 번역이 각 사유에 대응하는 근거를 갖는지 — 이름 자체 또는 그 사유의 판정 입력이 보이면 통과.
    evidence = {
        "name_tokens": "unresolved_name_tokens",
        "drift": "structure_drift",
        "template_unreadable": "compile_state is None",
    }
    # **건강 사유가 아니라고 선언한** 차단 사유 — 이유를 여기 적는다. 가드의 이빨은 그대로다:
    # 새 사유는 번역을 얻든 여기서 배제 근거를 얻든, 둘 중 하나를 **명시적으로** 해야 한다.
    not_health = {
        # 검토 요구(재작성 F5)는 결함이 아니라 **정상 흐름의 한 단계**다. 계약 §19.7 의 원인
        # 표는 손상·경로 없음·미지원·드리프트·끊어진 참조뿐인 **결함의 닫힌 목록**이고, 여기
        # 검토를 끼우면 새로 만든 모든 작업이 「확인 필요」에 서서 그 구획이 뜻을 잃는다
        # (경보 인플레이션 — 진짜 고장 난 작업이 새 작업들 사이에 묻힌다).
        "review_required",
    }
    missing = [
        r for r in reasons if r not in not_health and evidence.get(r, r) not in covered
    ]
    assert not missing, (
        "실행 게이트가 차단하는데 라이브러리 건강 번역이 모르는 사유입니다 — "
        f"library_health() 에 분기를 더하거나 evidence·not_health 표를 갱신하세요: {missing}"
    )


def test_library_projection_ands_active_tag_facets(tmp_path):
    """태그 facet 은 보기 4종 전부와 AND(§19.6) — 보기를 바꿨다고 켜 둔 칩이 풀리지 않는다."""
    vm = HomeViewModel(_library_reg(tmp_path), engine=make_hwpx_engine())
    vm.toggle_facet("물품", "의약품")
    assert {r.name for sec in vm.library_sections() for r in sec.rows} == {"미사용문서"}
    assert vm.library_counts()[VIEW_ALL] == 1        # 탭 건수도 켜진 칩 안에서 센다
    vm.set_library_view(VIEW_FAVORITES)
    assert vm.library_sections()[0].rows == []       # 즐겨찾기 ∧ 그 태그 = 0건


def test_library_ungrouped_section_is_identified_apart_from_flat_degenerate(tmp_path):
    """``value=""`` 두 뜻을 ``is_untagged`` 가 가른다(지도 §10.8 — 상세/목록 헤더 판정).

    「그룹 없음」 구획과 "나눌 group 이 없어 퇴화한 평면"은 둘 다 빈 값이라, 표면이 값으로만
    키잉하면 퇴화 평면에 헤더가 붙거나 「그룹 없음」이 헤더를 잃는다.
    """
    vm = HomeViewModel(_library_reg(tmp_path), engine=make_hwpx_engine())
    vm.set_library_view(VIEW_ALL)
    secs = vm.library_sections()
    assert [(s.value, s.is_untagged) for s in secs] == [("조달", False), ("", True)]

    plain = JobRegistry(tmp_path / "flatgrp")
    plain.save(Job(name="가", template_path=""))
    flat = HomeViewModel(plain, engine=make_hwpx_engine()).library_sections()
    assert [(s.value, s.is_untagged) for s in flat] == [("", False)]  # 퇴화 평면 ≠ 그룹 없음


def test_health_causes_are_the_source_and_list_badge_is_derived(tmp_path):
    """§19.7 "목록은 최고 심각도 1건, 상세는 모든 실제 원인" — 파생이지 별 판정이 아니다."""
    reg = JobRegistry(tmp_path / "causes")
    tpl = _compiled_hwpx(tmp_path, "cause.hwpx")               # 필드 = 계약명
    # 템플릿 계보(파일 부재) + 작업 정의 계보(못 채우는 토큰) 두 원인이 함께 참인 작업.
    reg.save(Job(name="두원인", template_path=str(tmp_path / "gone.hwpx"),
                 mapping=MappingProfile(mappings=[FieldMapping("계약명", "src")]),
                 filename_pattern="계약-{{추정가격}}"))
    reg.save(Job(name="한원인", template_path=tpl,
                 mapping=MappingProfile(mappings=[FieldMapping("계약명", "src")]),
                 filename_pattern="계약-{{추정가격}}"))
    reg.save(Job(name="건강", template_path=tpl,
                 mapping=MappingProfile(mappings=[FieldMapping("계약명", "src")]),
                 filename_pattern="계약-{{계약명}}"))
    rows = {r.name: r for r in HomeViewModel(reg, engine=make_hwpx_engine()).rows()}

    # 원인 열거가 정본이고, 목록 1건은 그 최댓값이다 — 같은 상태에 두 판정을 두지 않는다.
    for name in ("두원인", "한원인", "건강"):
        causes = library_health_causes(rows[name])
        assert library_health(rows[name]) == (causes[0] if causes else (0, ""))
    assert library_health_causes(rows["건강"]) == []

    # 두 계보는 **함께** 실린다(상세가 둘 다 본다) — 목록만 보면 하나만 아는 상태였다.
    both = library_health_causes(rows["두원인"])
    assert [t for _, t in both] == [
        "템플릿 파일을 찾을 수 없습니다.",
        "파일명 패턴의 토큰을 채우지 못합니다.",
    ]
    # 그래도 목록 대표는 종전과 같다 — 정렬은 심각도 내림 + 발견 순 안정.
    assert library_health(rows["두원인"]) == (3, "템플릿 파일을 찾을 수 없습니다.")
    assert [s for s, _ in both] == sorted((s for s, _ in both), reverse=True)


def test_health_causes_do_not_misdiagnose_unlinked_as_unsupported(tmp_path):
    """전 원인 열거가 **오진을 늘리지 않는다** — 앞 사유가 참이면 뒤는 판정 근거가 없다.

    경로가 비면 ``Job.media`` 도 비는데, 그것을 "지원하지 않는 작업 방식"으로 함께 실으면
    사용자는 「템플릿 다시 연결」로 고칠 수 있는 작업에 막다른 문안을 하나 더 받는다.
    """
    reg = JobRegistry(tmp_path / "misdiag")
    reg.save(Job(name="저작중", template_path=""))
    row = next(r for r in HomeViewModel(reg, engine=make_hwpx_engine()).rows() if r.name == "저작중")
    texts = [t for _, t in library_health_causes(row)]
    assert texts == ["템플릿을 아직 연결하지 않았습니다."]
    assert "지원하지 않는 작업 방식입니다." not in texts


def test_field_binding_rows_read_saved_binding_without_current_data(tmp_path):
    """상세 「필드 연결」 표는 **저장된 Binding 그대로**(지도 §10.8 판정 C).

    현재 데이터는 「문서 만들기」 세션 소유라 라이브러리가 원본 열 표시 이름을 쓰면 화면 간
    결합이 생긴다 — 항상 저장된 항목 키를 보이고, 값은 계산하지 않는다(미리보기는 F5).
    """
    job = Job(name="상세", template_path="", mapping=MappingProfile(mappings=[
        FieldMapping("계약명", source="bidNtceNm"),
        FieldMapping("추정가격", source="presmptPrce", type="amount", fmt="{:,}"),
        FieldMapping("공고일", source="bidNtceDt", type="date"),
        FieldMapping("발주처", type="const", const="조달청"),
        FieldMapping("비고", type="blank"),
        FieldMapping("담당자", type="text", fmt="phone"),
        FieldMapping("미정", source=""),
    ]))
    rows = {r.template_field: r for r in field_binding_rows(job)}
    assert rows["계약명"].source_label == "bidNtceNm"          # 저장 키 그대로(열 이름 아님)
    assert rows["추정가격"].format_label == "금액 · 숫자"       # 프리셋 라벨은 링0 단일 출처
    assert rows["공고일"].format_label == "날짜 · 표준"         # 빈 코드 = 기본 프리셋
    assert rows["담당자"].format_label == "텍스트 · 전화"
    assert rows["발주처"].source_label == "고정값 「조달청」" and rows["발주처"].format_label == "—"
    assert rows["비고"].blank and rows["비고"].source_label == "비움(명시)"
    # 소스를 아직 안 고른 항목은 "없음"이 아니라 **미지정**이다(조용한 빈칸 금지).
    assert rows["미정"].source_label == NO_SOURCE_LABEL and not rows["미정"].blank


def test_field_binding_rows_keep_unknown_format_code_verbatim():
    """프리셋 밖 직접 입력 코드는 원문 그대로 — 모르는 것을 아는 척하지 않는다."""
    job = Job(name="고급", template_path="", mapping=MappingProfile(
        mappings=[FieldMapping("납기", source="dlvrDt", type="date", fmt="%y/%m")]))
    assert field_binding_rows(job)[0].format_label == "날짜 · %y/%m"


def test_unknown_library_view_and_mode_degenerate(tmp_path):
    vm = HomeViewModel(_library_reg(tmp_path), engine=make_hwpx_engine())
    vm.set_library_view("엉뚱")
    vm.set_library_mode("엉뚱")
    assert vm.library_view == VIEW_ALL and vm.library_mode == "all"


def test_last_use_wording_follows_the_work_mode(tmp_path):
    """저장 필드는 하나(`last_run_at`)지만 그 뜻은 방식이 정한다(§19.4).

    hwpx 는 생성 완주에서, txt 는 작업대 **복사 완료** 1건에서 찍힌다. 한 문구로 뭉치면
    문서를 한 번도 만든 적 없는 TXT 작업이 라이브러리에서 「최근 실행」으로 보인다.
    """
    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "기안.txt"
    tpl.write_text("공고: {{공고명}}", encoding="utf-8")
    reg.save(Job(name="기안", template_path=str(tpl),
                 last_run_at="2026-07-28T09:10:00"))
    reg.save(Job(name="빈기안", template_path=str(tpl)))
    rows = {r.name: r for r in HomeViewModel(reg, engine=make_hwpx_engine()).rows()}
    assert rows["기안"].last_run_display == "마지막 복사 2026-07-28"
    assert rows["빈기안"].last_run_display == "복사한 적 없음"
