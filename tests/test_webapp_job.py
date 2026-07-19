"""「작업」 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스, R-flow 슬라이스 1 #90).

패널 4존이 소비하는 링1 배선(부록 A-1)을 창 없이 되읽는다: 좌 목록 → 작업 선택 → 데이터 겨눔
→ 미입력 강제 확인 게이트(ADR-E) → 덮어쓰기 재진술(RC-02) → 생성 end-to-end. JobController 는
실행 화면(screen_run)을 재사용하지 않는 별개 링2 표면이되 **같은 링1 계약**을 소비하므로,
실행 화면 회귀 심(test_webapp_run)과 평행한 단언으로 배선 동등을 못박는다.
"""
from __future__ import annotations

import pytest

from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.run_state import RunViewModel
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.webapp.screen_job import JobController
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage


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
    states = {s["name"]: s["state"] for s in snap["field_states"]}
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

    # 같은 폴더 재생성 → 조용한 덮어쓰기 금지: 재진술 요구.
    res = ctrl.generate()
    assert res["ok"] is False and res.get("needs_overwrite") is True
    assert "덮어" in res["overwrite_text"]
    # 확인 후 재호출 → 생성.
    assert ctrl.generate(confirm_overwrite=True)["ok"] is True


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
