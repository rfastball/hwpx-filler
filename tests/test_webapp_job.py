"""「작업」 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스, R-flow 슬라이스 1 #90).

패널 4존이 소비하는 링1 배선(부록 A-1)을 창 없이 되읽는다: 좌 목록 → 작업 선택 → 데이터 겨눔
→ 미입력 강제 확인 게이트(ADR-E) → 덮어쓰기 재진술(RC-02) → 생성 end-to-end. JobController 는
실행 화면(screen_run)을 재사용하지 않는 별개 링2 표면이되 **같은 링1 계약**을 소비하므로,
실행 화면 회귀 심(test_webapp_run)과 평행한 단언으로 배선 동등을 못박는다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.run_state import RunViewModel
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.webapp.screen_job import JobController
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

MULTI_SHEET = Path(__file__).resolve().parents[0] / "fixtures" / "multi_sheet.xlsx"


def _write_template(path, fields) -> None:
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


def _registry(tmp_path) -> JobRegistry:
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "추정가격"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce"),
        ]),
        filename_pattern="doc-{{seq:001}}",
    ))
    return reg


def _controller(tmp_path):
    pushes: list = []
    ctrl = JobController(_registry(tmp_path), lambda s, snap: pushes.append((s, snap)))
    return ctrl, pushes


def _data_csv(tmp_path) -> str:
    # rec0 은 추정가격 빈값(→ '미입력'), rec1 은 채움 — 강제 확인 게이트를 태운다.
    csv = tmp_path / "d.csv"
    csv.write_text("bidNtceNm,presmptPrce\n전산장비,\n사무비품,2000000\n", encoding="utf-8")
    return str(csv)


# ---------------------------------------------------------------- 좌 목록 + 스냅샷 골격
def test_initial_lists_jobs_and_loud_gate(tmp_path):
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["has_job"] is False
    # 좌 master 목록 = 저장된 작업(선택 표지 포함).
    assert snap["job_rows"] == [{"name": "공고서", "selected": False}]
    assert snap["gate"]["enabled"] is False and "작업을 선택" in snap["gate"]["text"]


def test_select_job_marks_master_and_sets_session(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["job_name"] == "공고서"
    assert snap["job_rows"] == [{"name": "공고서", "selected": True}]  # 좌 목록 선택 표지
    # 저장 폴더 기본값 = 템플릿 폴더/Results(실행 화면 동형).
    assert snap["out_dir"].endswith("Results")


def test_select_job_then_data_populates_records_and_badges(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["has_data"] is True and snap["record_count"] == 2
    assert snap["selected_count"] == 2  # 데이터 겨눔 = 전체 선택 초기화
    assert snap["template_path"].endswith("t.hwpx")  # 추적성 로케이트용 전체 경로(#53-B)
    # 본문 존 거울 행(비-drift 필드) — 이름·상태·값 병기.
    states = {s["name"]: s["state"] for s in snap["mirror"]}
    assert states["공고명"] == "filled"
    assert states["추정가격"] == "missing"  # rec0 빈값 → 미입력


# ------------------------------------------------------ 식별 요약 링1 소비(A-1-15, PR-1)
def test_record_summary_consumes_ring1_identity_not_keyed_temp(tmp_path):
    """식별 요약은 링1 ``identity_summary`` 소비 — 원본 값만 병기(임시 'key: value' 판 폐기).

    슬라이스 1의 임시 요약은 ``bidNtceNm: 전산장비`` 처럼 키를 접두했다. 링1 판은 사용자가
    데이터에서 본 값만 ``' · '`` 로 병기한다(A-1-15) — 키 접두가 사라졌음을 못박는다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    summaries = [r["summary"] for r in ctrl.snapshot()["records"]]
    assert all("bidNtceNm" not in s for s in summaries)  # 임시 판의 키 접두 폐기(값만 병기)
    # display_for: rec0 은 presmptPrce 빈값이라 마커로 자리 보존(매달린 구분자 아님), rec1 은
    # 두 값 병기. 인지층 = 왼쪽 2열(bidNtceNm·presmptPrce).
    assert summaries == ["전산장비 · (빈칸)", "사무비품 · 2000000"]


def test_filename_token_mode_back_resolves_and_excludes_non_carriers(tmp_path):
    """파일명이 나르는 템플릿 필드를 매핑 ``source``(원본 열)로 역해소(결정 37 토큰 모드).

    파일명 토큰은 **매핑 후** 네임스페이스(``공고명``)인데 식별 요약은 **원본 열**(``bidNtceNm``)
    을 본다 — 역해소가 없으면 토큰 모드가 엉뚱한 네임스페이스로 오발한다(confirm-or-alarm).
    세 배제 가드를 모두 태운다: ``const``(리터럴, source 무의존)·``blank``·부재 source.
    """
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "상수", "빈칸", "유령"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),          # text·present → 포함
            FieldMapping(template_field="상수", source="dmndInsttNm", type="const", const="고정"),  # const → 배제
            FieldMapping(template_field="빈칸", source="ntceInsttNm", type="blank"),  # blank → 배제
            FieldMapping(template_field="유령", source="does_not_exist"),        # 부재 source → 배제
        ]),
        # 네 템플릿 필드를 모두 파일명이 요구(가드가 없으면 넷 다 토큰 모드로 샘).
        filename_pattern="{{공고명}}-{{상수}}-{{빈칸}}-{{유령}}-{{seq:001}}",
    ))
    csv = tmp_path / "d.csv"
    csv.write_text(
        "bidNtceNm,presmptPrce,dmndInsttNm,ntceInsttNm\n전산장비,,조달청,조달청\n사무비품,2000000,경찰청,경찰청\n",
        encoding="utf-8",
    )
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(str(csv))
    # text·present 인 공고명(→bidNtceNm)만 나르는 열. const·blank·부재 source 는 배제.
    assert ctrl._filename_source_columns() == ["bidNtceNm"]


# ---------------------------------------------------------------- 게이트·생성(링1 계약)
def test_missing_gate_blocks_generate_until_acked(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))

    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False and "미입력" in snap["gate"]["text"]

    # 생성 시도도 방어적으로 차단(worker/API 우회 방지).
    res = ctrl.generate()
    assert res["ok"] is False and "미입력" in res["error"]

    # 배지 클릭 = 직접 확인 → 게이트 열림.
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.snapshot()["gate"]["enabled"] is True


def test_generate_writes_documents_and_marks_missing(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    res = ctrl.generate()
    assert res["ok"] is True
    assert res["succeeded"] == 2 and res["failed"] == 0
    assert "미입력 표시 필드" in res["summary"]  # 낙관 서사 해소
    made = sorted(p.name for p in out.glob("*.hwpx"))
    assert made == ["doc-001.hwpx", "doc-002.hwpx"]
    # 진행 델타가 최소 1회 푸시됐다(진행바 갱신 계약).
    assert any(isinstance(snap, dict) and "progress" in snap for _s, snap in pushes)


def test_overwrite_confirm_flow(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.generate()["ok"] is True  # 최초 생성

    # 같은 폴더 재생성 → 조용한 덮어쓰기 금지: 수치 합성 재진술 요구(총량·파괴분·신규분).
    res = ctrl.generate()
    assert res["ok"] is False and res.get("needs_overwrite") is True
    assert res["total"] == 2 and res["overwrite_count"] == 2 and res["new_count"] == 0
    assert len(res["conflict_names"]) == 2 and res["conflict_more"] == 0
    # 확인 후 재호출 → 생성.
    assert ctrl.generate(confirm_overwrite=True)["ok"] is True


# ---------------------------------------------- 본문 존 거울(블록 6 D2 ⓑ, PR-2)
def _mirror_job(tmp_path) -> JobRegistry:
    """거울 케이스용 작업 — 채움(text)·미입력(amount, rec0 빈값)·의도적 빈칸 3필드."""
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "추정가격", "비고"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce", type="amount"),
            FieldMapping(template_field="비고", type="blank"),
        ]),
        filename_pattern="doc-{{seq:001}}",
    ))
    return reg


def test_mirror_value_display_filled_sample_missing_blank(tmp_path):
    """거울 행 = 필드별 값 집계(재구현 아님, mapped_records 소비). 상태별 값·표시형 병기."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    m = {r["name"]: r for r in ctrl.snapshot()["mirror"]}
    # 공고명: 선택 2행 값이 달라 표본 명시 병기(S10) — 서로 다른 값 1개 더, text 라 표시형 아님.
    assert m["공고명"]["state"] == "filled"
    assert m["공고명"]["value"] == "전산장비 (표본 · 외 1개 값)"
    assert m["공고명"]["formatted"] is False
    # 추정가격: rec0 빈값 → missing, 값 = 빈 행수 재진술(낙관 서사 해소), amount → 표시형.
    assert m["추정가격"]["state"] == "missing"
    assert "선택 2행 중 1행" in m["추정가격"]["value"]
    assert m["추정가격"]["formatted"] is True
    # 비고: 의도적 빈칸 표지.
    assert m["비고"]["state"] == "blank" and m["비고"]["value"] == "(의도적 빈칸)"


def test_mirror_filled_same_value_is_not_labeled_sample(tmp_path):
    """선택 N>1 이라도 값이 다 같으면 표본 라벨 없이 그냥 값(허위 '행마다 다름' 금지)."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    csv = tmp_path / "same.csv"
    csv.write_text("bidNtceNm,presmptPrce\n동일공고,100\n동일공고,200\n", encoding="utf-8")
    ctrl.load_data_path(str(csv))
    m = {r["name"]: r for r in ctrl.snapshot()["mirror"]}
    assert m["공고명"]["value"] == "동일공고"  # 표본 라벨 없음


def test_mirror_sample_counts_distinct_values_not_rows(tmp_path):
    """표본 병기 '외 K개 값'은 서로 다른 값 수로 센다 — 대부분 같고 하나만 달라도 과장 없음."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    csv = tmp_path / "mostly_same.csv"
    # 4행 '전산장비' + 1행 '사무비품' → 서로 다른 값은 2종(외 1개), 행 수(5)로 세면 과장(외 4).
    csv.write_text(
        "bidNtceNm,presmptPrce\n전산장비,1\n전산장비,2\n전산장비,3\n전산장비,4\n사무비품,5\n",
        encoding="utf-8",
    )
    ctrl.load_data_path(str(csv))
    m = {r["name"]: r for r in ctrl.snapshot()["mirror"]}
    assert m["공고명"]["value"] == "전산장비 (표본 · 외 1개 값)"  # 행 수 아님(외 4행 금지)


def test_mirror_empty_when_no_selection(tmp_path):
    """선택 0 = 생성될 문서 없음 → 거울 행 없음(빈 값을 '채움'으로 오도하지 않는다)."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("set_none", {})
    snap = ctrl.snapshot()
    assert snap["mirror"] == [] and snap["drift"] == []


def test_mirror_drift_split_into_blocking_list(tmp_path):
    """drift(구조 불일치) 필드는 거울 표에서 빠져 별도 drift 목록으로 — 차단 배너 분리(결정 36)."""
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "유령"])  # 유령 = 템플릿 전용(매핑 미커버) → drift
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="bidNtceNm")]),
        filename_pattern="doc-{{seq:001}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["drift"] == ["유령"]
    assert [r["name"] for r in snap["mirror"]] == ["공고명"]  # drift 필드는 표에서 제외


def test_select_none_closes_record_gate(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.snapshot()["gate"]["enabled"] is True
    ctrl.dispatch("set_none", {})
    snap = ctrl.snapshot()
    assert snap["selected_count"] == 0
    assert snap["gate"]["enabled"] is False and "생성할 문서" in snap["gate"]["text"]


def test_deselect_job_returns_to_empty_panel(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("select_job", {"name": ""})  # 선택 해제
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["job_name"] == ""
    assert snap["job_rows"] == [{"name": "공고서", "selected": False}]


def test_refresh_invalidates_session_when_job_deleted(tmp_path):
    """master-detail 불변식(리뷰 #2): 선택된 작업이 다른 화면에서 삭제돼 레지스트리에서 사라지면
    refresh 가 세션을 무효화한다 — 존재하지 않는 작업의 라이브 세션이 활성 생성 버튼과 함께
    남아 유령 작업에서 생성되는 것을 막는다."""
    reg = _registry(tmp_path)
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.snapshot()["has_job"] is True

    reg.delete("공고서")  # 다른 화면이 삭제(그 화면으로 가려면 작업 화면 이탈 → 복귀 시 refresh)
    ctrl.dispatch("refresh", {})
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["job_name"] == ""
    assert snap["job_rows"] == []  # 좌 목록에서도 사라져 상실이 보인다
    # 유령 작업 생성 시도도 loud 차단(세션 무효화 후).
    res = ctrl.generate()
    assert res["ok"] is False


def test_refresh_keeps_session_when_job_still_present(tmp_path):
    """refresh 가 멀쩡한 세션을 건드리지 않는다 — 무효화는 삭제/개명된 작업에만(과잉 리셋 방지)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("refresh", {})
    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["job_name"] == "공고서"
    assert snap["record_count"] == 2  # 데이터 겨눔도 보존


def test_unknown_action_is_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 작업 화면 액션"):
        ctrl.dispatch("frobnicate", {})


def test_generate_without_job_is_loud_not_silent(tmp_path):
    ctrl, _ = _controller(tmp_path)
    res = ctrl.generate()
    assert res["ok"] is False and "작업" in res["error"]


# ---------------------------------------------------------------- #87 구조 가드(링1 위임)
def test_panel_delegates_to_ring1_view_models(tmp_path):
    """#87: 패널이 링1 VM 을 **소유·위임**한다 — 재구현이 아니라 임포트한 VM 인스턴스.

    작업 선택 시 세션의 결정 상태가 RunViewModel/SelectionModel 그 자체여야 한다(별도
    스냅샷 클래스로 우회 재구현하지 않는다). 정적 임포트·무재구현 가드는 test_architecture.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert isinstance(ctrl.vm, RunViewModel)
    assert isinstance(ctrl.selection, SelectionModel)


# ---------------------------------------------------------------- #26 #6 — 2소스(등록 데이터)
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry


def _pool_controller(tmp_path):
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pushes: list = []
    ctrl = JobController(
        _registry(tmp_path), lambda s, snap: pushes.append((s, snap)),
        pool_registry=pool,
    )
    return ctrl, pool


def test_load_pool_targets_excel_reference(tmp_path):
    """등록 데이터 겨눔 성공 — 실행 시점 재읽기(싱크) + 소스 병기 라벨 + 선택 초기화."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert res["ok"] is True and res["label"] == "등록 데이터: 7월공고"
    snap = ctrl.snapshot()
    assert snap["data_source_label"] == "등록 데이터: 7월공고"
    assert snap["record_count"] == 2


def test_load_pool_without_job_is_loud(tmp_path):
    """겨눔 전제 = 작업 선택 — 미선택이면 공용 래퍼가 오류 dict 로 재진술(조용한 실패 금지)."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    res = ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert res["ok"] is False and "작업" in res["error"]


# --------------------------------------- 기본 데이터셋 자동 조준(#53-A, A-1-11) — 리뷰 F4
# 실행 화면 사망(슬라이스 3)으로 test_webapp_run 의 자동 조준 회귀 심이 사라졌다 — JobController
# 의 '조용한 폴백 금지'(성공=ok 재진술 / 실패=warn 미겨눔) 계약을 여기서 이어 가드한다.
def _job_with_default(ctrl, pool, tmp_path, ref, *, register=True):
    """'공고서' 작업에 기본 데이터셋 참조를 붙여 재저장. register=True 면 동명 CSV 풀 항목 등록."""
    job = ctrl.registry.load("공고서")
    job.default_dataset_ref = ref
    ctrl.registry.save(job, allow_overwrite=True)
    if register:
        pool.save(DatasetPoolItem(name=ref, kind="excel", opts={"path": _data_csv(tmp_path)}))


def test_select_job_auto_aims_default_dataset(tmp_path):
    """기본 데이터셋 참조가 있으면 작업 선택 시 실행 시점에 다시 읽어 자동 조준(#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "7월공고")
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is True and snap["record_count"] == 2      # 자동 재읽기(싱크)
    assert snap["data_source_label"] == "등록 데이터: 7월공고"
    assert snap["selected_count"] == 2                                  # 겨눔 = 전체 선택 초기화
    assert snap["data_notice"]["level"] == "ok" and "자동" in snap["data_notice"]["text"]


def test_select_job_dead_default_ref_is_loud_no_silent_fallback(tmp_path):
    """죽은 기본 참조는 조용한 폴백 금지 — 미겨눔 + 원인·복구 동선(다시 연결)을 재진술(#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "없는참조", register=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is False                       # 자동 겨눔 실패 = 미겨눔(폴백 없음)
    assert snap["data_source_label"] == ""
    assert snap["data_notice"]["level"] == "warn"
    assert "없는참조" in snap["data_notice"]["text"] and "다시 연결" in snap["data_notice"]["text"]


def test_auto_aim_nara_ref_is_frozen_warn(tmp_path):
    """기본 참조가 나라 항목이면 자동 조준도 동결 거절 warn — 공유 관문 문구 그대로(#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(
        name="나라기본", kind="nara", opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    _job_with_default(ctrl, pool, tmp_path, "나라기본", register=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is False and snap["data_notice"]["level"] == "warn"
    assert "동결" in snap["data_notice"]["text"]


def test_auto_aim_ambiguous_sheet_ref_is_warn(tmp_path):
    """기본 참조가 시트 미지정 다중시트면 자동 조준도 조용한 첫 시트 대신 warn 거절(#33·#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="모호기본", kind="excel", opts={"path": str(MULTI_SHEET)}))
    _job_with_default(ctrl, pool, tmp_path, "모호기본", register=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is False and snap["data_notice"]["level"] == "warn"
    assert "시트" in snap["data_notice"]["text"]


def test_manual_data_clears_auto_aim_notice(tmp_path):
    """자동 조준 후 사용자가 직접 데이터를 겨누면 자동 조준 재진술이 소거된다(임시 데이터=기본 불변)."""
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "7월공고")
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert ctrl.snapshot()["data_notice"] is not None
    ctrl.load_data_path(_data_csv(tmp_path))               # 수동 파일 겨눔
    snap = ctrl.snapshot()
    assert snap["data_notice"] is None
    assert snap["data_source_label"].startswith("파일:")
    assert ctrl.registry.load("공고서").default_dataset_ref == "7월공고"  # 임시 override, 기본 불변


# --------------------------------------------- 템플릿 다시 연결(#67, A-1-2 계열) — 리뷰 F5
# 실행 화면 사망으로 test_webapp_run 의 relink 회귀 심(x6)이 사라졌다 — 패널의 재연결 흐름
# (경로 재진술·드리프트 병기·읽기불가 하드차단·선택 작업 stale VM 재적재)을 여기서 잇는다.
def test_relink_template_needs_confirm_restates_paths(tmp_path):
    """1차 호출 = 기존→새 경로 재진술 확인 요구. 구조 동일이면 드리프트 문구 없음(#67)."""
    ctrl, _ = _controller(tmp_path)
    new_tpl = tmp_path / "moved.hwpx"
    _write_template(new_tpl, ["공고명", "추정가격"])       # 같은 구조 — 드리프트 0
    res = ctrl.dispatch("relink_template", {"name": "공고서", "path": str(new_tpl)})
    assert res["ok"] is True and res["needs_confirm"] is True
    assert "t.hwpx" in res["confirm_text"] and "moved.hwpx" in res["confirm_text"]  # 양경로 재진술
    assert "구조가" not in res["confirm_text"]             # 무드리프트 = 소음 금지
    assert ctrl.registry.load("공고서").template_path.endswith("t.hwpx")  # 확인 전 durable 불변


def test_relink_template_drift_restated_in_confirm(tmp_path):
    """새 파일 구조가 확정 매핑과 다르면 확인 문구에 드리프트 상세+생성 차단 경고 병기(#67)."""
    ctrl, _ = _controller(tmp_path)
    new_tpl = tmp_path / "changed.hwpx"
    _write_template(new_tpl, ["공고명", "낙찰자"])         # 추정가격 소멸 + 낙찰자 유입
    res = ctrl.dispatch("relink_template", {"name": "공고서", "path": str(new_tpl)})
    assert res["needs_confirm"] is True and "구조가" in res["confirm_text"]
    assert "낙찰자" in res["confirm_text"] and "추정가격" in res["confirm_text"]  # describe() 단일 출처
    assert "생성이 차단됩니다" in res["confirm_text"]      # 기존 게이트 백스톱 재진술


def test_relink_template_unreadable_is_blocked(tmp_path):
    """읽을 수 없는 파일은 확인으로도 템플릿이 될 수 없다 — 하드 차단 + JSON 불변(#67)."""
    ctrl, _ = _controller(tmp_path)
    res = ctrl.dispatch(
        "relink_template",
        {"name": "공고서", "path": str(tmp_path / "없는파일.hwpx"), "confirm": True})
    assert res["ok"] is False and "연결을 바꾸지 않았습니다" in res["error"]
    assert ctrl.registry.load("공고서").template_path.endswith("t.hwpx")


def test_relink_selected_job_reloads_vm_and_restates(tmp_path):
    """지금 선택된 작업을 재연결하면 stale VM 을 재적재하고 상태 초기화를 재진술한다(#67)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))               # 데이터 겨눔(재적재로 초기화될 상태)
    new_tpl = tmp_path / "moved.hwpx"
    _write_template(new_tpl, ["공고명", "추정가격"])
    res = ctrl.dispatch(
        "relink_template", {"name": "공고서", "path": str(new_tpl), "confirm": True})
    assert res["relinked"] is True
    assert "다시 불러왔으니" in res["restated"]             # 조용한 상태 소실 금지(재적재 재진술)
    assert ctrl.vm.job.template_path == str(new_tpl)       # VM 재구성


# ---- 실행 화면 사망(슬라이스 3)으로 test_webapp_run 에서 유실된 confirm-or-alarm 회귀 심 승계
# ---- (별도세션 리뷰 #99-1~5, CONFIRMED). JobController 동작은 살아 있으나 무테스트였다.
def test_load_data_honors_confirmed_sheet(tmp_path):
    """다중 시트 확정 게이트(#33, 리뷰 #99-1) — load_data_path(sheet=) 가 확정 시트를 관통.

    작업 선택 후 낙찰현황(3건)을 확정하면 첫 시트(공고목록 2건)가 아니라 그 시트가 실린다 —
    조용한 첫 시트 강등이 아니라 확정값 반영(test_webapp_bridge 의 job 컨트롤러측 대응물).
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    snap = ctrl.snapshot()
    assert snap["data_label"] == "multi_sheet.xlsx"
    assert snap["has_data"] is True and snap["record_count"] == 3


def test_record_names_follow_selection_not_invented(tmp_path):
    """미선택 행 이름은 지어내지 않는다(F33, 리뷰 #99-2) — {{seq}}·충돌 접미사는 선택 집합에
    따라 달라지므로 선택 변경 시 남은 행 이름이 생성 결과대로 재계산된다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("toggle_record", {"index": 0, "value": False})
    rows = ctrl.snapshot()["records"]
    assert rows[0]["name"] == "" and rows[0]["selected"] is False   # 미선택 = 이름 없음
    # 남은 1건만 생성하면 그 파일이 doc-001 — 미리보기도 같은 사실을 말한다.
    assert rows[1]["name"] == "doc-001.hwpx" and rows[1]["selected"] is True


def test_generate_uses_previewed_name_timestamp(tmp_path):
    """미리보기가 보여준 시각 = 생성 파일명 시각(RC-02 표시=확인=생성, 리뷰 #99-3).

    시·분·초 date 토큰 패턴에서 미리보기 스냅샷과 생성 클릭 사이 시계가 흘러도, generate 는
    마지막 미리보기(``_names_now``)의 시각을 재사용해 화면이 보여준 실파일명 그대로 생성한다.
    """
    ctrl, _ = _controller(tmp_path)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "doc-{{date:HHmmSS}}-{{seq}}"
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    # 스냅샷 미리보기가 시각을 캡처 → 이후 시계 전진을 결정적으로 모사(주입) → 생성이 캡처값 재사용.
    assert ctrl.snapshot()["records"][0]["name"].startswith("doc-")
    ctrl._names_now = datetime(2026, 1, 2, 3, 4, 5)
    res = ctrl.generate()
    assert res["ok"] is True
    made = sorted(p.name for p in out.glob("*.hwpx"))
    assert made and all(n.startswith("doc-030405-") for n in made)  # 주입 시각 그대로


def test_snapshot_reports_template_missing_only_when_file_gone(tmp_path):
    """template_missing 은 파일이 실제로 없을 때만 True(F30, 리뷰 #99-4) — 웹이 이 플래그로
    「템플릿 다시 연결」 복구 동선을 조건부 노출한다(Python 층 실행 — JS 렌더 가드와 별개)."""
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["template_missing"] is False               # 미선택 = 버튼 표면 자체가 없음
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["template_missing"] is False               # 정상 = 복구 동선 숨김
    Path(snap["template_path"]).unlink()                    # 템플릿 파일 소실 재현
    assert ctrl.snapshot()["template_missing"] is True      # 부재 = 복구 동선 노출


def test_unresolved_pattern_gate_surfaces_in_snapshot(tmp_path):
    """미해소 파일명 토큰 작업 = 스냅샷 게이트 danger 차단 + 생성 백스톱(F34, 리뷰 #99-5)."""
    ctrl, _ = _controller(tmp_path)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "공고서-{{ID}}"                 # 101 워크스루 실증 지뢰(데이터에 ID 없음)
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False and snap["gate"]["level"] == "danger"
    assert "{{ID}}" in snap["gate"]["text"]
    res = ctrl.generate()
    assert res["ok"] is False and "{{ID}}" in res["error"]  # 생성 백스톱도 리터럴 방지


# ------------------------------------------------- 필터 배선(블록 4, 슬라이스 4 PR-2b)
def _session(tmp_path):
    """작업 선택 + 데이터 겨눔까지 마친 컨트롤러 — 필터 계약 테스트 공용."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    return ctrl, pushes


def test_filter_lifecycle_session_scoped(tmp_path):
    """필터 = 세션 수명(결정 24): 데이터 겨눔에 생성, 작업 전환에 소멸, 재겨눔에 재생성."""
    ctrl, _ = _session(tmp_path)
    assert ctrl.filter is not None
    # 매핑 확정 유형(text)이 힌트로 우선한다 — 수치 열이어도 사용자 확정 존중.
    snap = ctrl.snapshot()
    kinds = {c["name"]: c["kind"] for c in snap["filter"]["columns"]}
    assert kinds == {"bidNtceNm": "text", "presmptPrce": "text"}
    ctrl.dispatch("filter_search", {"text": "전산"})
    assert ctrl.filter.is_active()
    ctrl.dispatch("select_job", {"name": ""})  # 작업 전환 = 필터 소멸(세션 휘발, 결정 8)
    assert ctrl.filter is None
    assert ctrl.snapshot()["filter"] == {
        "active": False, "search": "", "chips": [], "definition": "",
        "branches": [], "columns": [],
    }


def test_filter_search_shapes_table_and_chips(tmp_path):
    """전열 검색 → 재현 OR 그룹: 가시 행·가지·칩·셀 세그먼트가 스냅샷으로 온다."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    snap = ctrl.snapshot()
    t = snap["table"]
    assert t["columns"] == ["bidNtceNm", "presmptPrce"]
    assert t["visible_count"] == 1 and [r["index"] for r in t["rows"]] == [0]
    assert snap["filter"]["branches"] == ["bidNtceNm"]
    assert any("전산" in c for c in snap["filter"]["chips"])
    # 셀 = 하이라이트 세그먼트(파이썬이 잘라 조각으로 — 인덱스 무전달, jamo 계약).
    # 파이썬 층에선 튜플, json.dumps 가 배열로 직렬화한다.
    cells = t["rows"][0]["cells"]
    assert cells[0] == [("전산", True), ("장비", False)]
    assert cells[1] == []  # 빈 셀 = 빈 세그먼트


def test_set_all_is_additive_over_matches(tmp_path):
    """「전체 선택」 = 매치 전체 가산(결정 4·26) — 필터 밖 기존 선택은 유지(관통, 결정 3)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})   # 매치 = 0행뿐
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 필터 밖 행 직접 선택
    ctrl.dispatch("set_all", {})                        # 매치(0행) 가산
    snap = ctrl.snapshot()
    assert snap["selected_count"] == 2                  # 1행 선택이 지워지지 않았다
    # 필터 밖 선택 = 스트립 소재(결정 3 — 상시 가시).
    assert [r["index"] for r in snap["table"]["hidden_selected"]] == [1]


def test_select_range_propagates_anchor_state(tmp_path):
    """Shift 범위 = 앵커 상태 전파(결정 2) — 선택도 해제도 범위로."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("select_range", {"indices": [0, 1], "value": True})
    assert ctrl.snapshot()["selected_count"] == 2
    ctrl.dispatch("select_range", {"indices": [1], "value": False})
    assert ctrl.snapshot()["selected_count"] == 1


def test_restate_origin_by_set_comparison(tmp_path):
    """선택 유래 = 집합 비교 무상태 판정: 매치 전체=정의-유래, 이탈=직접+수치 병기(S4)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("set_all", {})
    r = ctrl.snapshot()["restate"]
    assert r["origin"] == "definition" and r["filter_active"] is True
    assert r["in_def"] == 1 and r["extra"] == 0
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 정의 밖 가산 → 혼합
    r = ctrl.snapshot()["restate"]
    assert r["origin"] == "manual" and r["in_def"] == 1 and r["extra"] == 1
    assert set(r["sample"]) <= {0, 1} and len(r["sample"]) <= 3


def test_filter_range_on_amount_column_and_inline_error(tmp_path):
    """범위 조건 배선 — 매핑 amount 확정 열, 오독 피연산자는 인라인 오류 dict(비폭발)."""
    template = tmp_path / "t2.hwpx"
    _write_template(template, ["공고명", "추정가격"])
    reg = JobRegistry(tmp_path / "jobs2")
    reg.save(Job(
        name="금액작업", template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce", type="amount"),
        ]),
        filename_pattern="doc-{{seq:001}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "금액작업"})
    ctrl.load_data_path(_data_csv(tmp_path))
    kinds = {c["name"]: c["kind"] for c in ctrl.snapshot()["filter"]["columns"]}
    assert kinds["presmptPrce"] == "amount"              # 매핑 확정 유형 힌트
    res = ctrl.dispatch("filter_col_range", {
        "column": "presmptPrce", "first": {"op": "ge", "operand": "1억"}})
    assert res["ok"] is False and "읽을 수 없습니다" in res["error"]
    res = ctrl.dispatch("filter_col_range", {
        "column": "presmptPrce", "first": {"op": "ge", "operand": "1000000"}})
    assert res["ok"] is True
    assert ctrl.snapshot()["table"]["visible_count"] == 1  # 2000000 행만
    # 빈 첫 절 = 조건 해제.
    res = ctrl.dispatch("filter_col_range", {"column": "presmptPrce", "first": None})
    assert res["ok"] is True and ctrl.snapshot()["table"]["visible_count"] == 2


def test_filter_panel_query_returns_options_and_state(tmp_path):
    """열 패널 질의 — 현 조건 + 값 목록((빈값)="" 일급, 말미)."""
    ctrl, _ = _session(tmp_path)
    res = ctrl.dispatch("filter_panel", {"column": "presmptPrce"})
    assert res["kind"] == "text" and res["checked"] is None and res["range"] is None
    assert res["options"] == ["2000000", ""]             # 빈 셀 = 정식 값, 말미
    ctrl.dispatch("filter_col_values", {"column": "presmptPrce", "values": [""]})
    res = ctrl.dispatch("filter_panel", {"column": "presmptPrce"})
    assert res["checked"] == [""]
    assert ctrl.snapshot()["table"]["visible_count"] == 1  # 빈값 행(0행)만


def test_filter_actions_without_data_are_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    with pytest.raises(ValueError, match="데이터를 먼저"):
        ctrl.dispatch("filter_search", {"text": "x"})


def test_set_all_reports_added_count_for_dead_button_honesty(tmp_path):
    """「전체 선택」 반환 added — 전멸 필터의 무동작(0)을 표면이 알린다(리뷰 #9)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    assert ctrl.dispatch("set_all", {}) == {"added": 2}      # 필터 없음 = 전체
    ctrl.dispatch("filter_search", {"text": "존재하지않는말"})  # 전멸
    assert ctrl.dispatch("set_all", {}) == {"added": 0}      # 무동작 정직 보고
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.dispatch("set_none", {})
    assert ctrl.dispatch("set_all", {}) == {"added": 1}      # 매치만 가산


def test_table_cell_preserves_falsy_values(tmp_path):
    """셀 텍스트 = cell_text 단일 출처(리뷰 #8) — 0 이 빈칸으로 붕괴하지 않는다."""
    ctrl, _ = _session(tmp_path)
    ctrl.vm.records[1]["presmptPrce"] = 0                    # 풀(JSON) 유래 수치형 재현
    snap = ctrl.snapshot()
    row1 = next(r for r in snap["table"]["rows"] if r["index"] == 1)
    assert row1["cells"][1] == [("0", False)]                # 필터가 보는 그대로 표면도
