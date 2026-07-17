"""실행 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 화면 #18 이관의 회귀 심. 작업 선택 → 데이터 겨눔 → 미입력 강제 확인 게이트(ADR-E)
→ 덮어쓰기 재진술(RC-02) → 생성 end-to-end 를 창 없이 확인한다. 실 HWPX 를 만들어 실제
문서 생성까지 되읽는다(파일 다이얼로그·폴더 피커만 브리지가 담당 — 여기선 경로 직접 주입).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.webapp.screen_run import RunController
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage


def _write_template(path: Path, fields) -> None:
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


def _registry(tmp_path: Path) -> JobRegistry:
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


def _controller(tmp_path: Path) -> "tuple[RunController, list]":
    pushes: list = []
    ctrl = RunController(_registry(tmp_path), lambda s, snap: pushes.append((s, snap)))
    return ctrl, pushes


def _data_csv(tmp_path: Path) -> str:
    # rec0 은 추정가격 빈값(→ '미입력'), rec1 은 채움 — 강제 확인 게이트를 태운다.
    csv = tmp_path / "d.csv"
    csv.write_text("bidNtceNm,presmptPrce\n전산장비,\n사무비품,2000000\n", encoding="utf-8")
    return str(csv)


def test_initial_has_no_job_and_loud_gate(tmp_path):
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["has_job"] is False and snap["jobs"] == ["공고서"]
    assert snap["gate"]["enabled"] is False and "작업" in snap["gate"]["text"]


def test_select_job_then_data_populates_records_and_badges(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["has_data"] is True and snap["record_count"] == 2
    assert snap["selected_count"] == 2  # 데이터 겨눔 = 전체 선택 초기화
    states = {s["name"]: s["state"] for s in snap["field_states"]}
    assert states["공고명"] == "filled"
    assert states["추정가격"] == "missing"  # rec0 빈값 → 미입력
    # 저장 폴더 기본값 = 템플릿 폴더/Results(Qt 동형)
    assert snap["out_dir"].endswith("Results")


MULTI_SHEET = Path(__file__).resolve().parents[0] / "fixtures" / "multi_sheet.xlsx"


def test_load_data_honors_confirmed_sheet(tmp_path):
    """다중 시트 확정 게이트(#33, 리뷰 P1) — run load_data_path(sheet=) 가 확정 시트를 관통.

    작업 선택 후 낙찰현황(3건)을 확정하면 첫 시트(공고목록 2건)가 아니라 그 시트가 실린다 —
    조용한 첫 시트 강등이 아니라 확정값 반영.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    snap = ctrl.snapshot()
    assert snap["data_label"] == "multi_sheet.xlsx"
    assert snap["has_data"] is True and snap["record_count"] == 3


def test_missing_gate_blocks_generate_until_acked(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))

    # 게이트 닫힘: 미확인 미입력(추정가격) → 버튼 비활성 + 인라인 사유.
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
    # 미입력(추정가격)은 표식이 들어갔음을 완료 요약이 병기(낙관 서사 해소).
    assert "미입력 표시 필드" in res["summary"]
    # 실제 문서 2건이 저장 폴더에 생성됐다.
    made = sorted(p.name for p in out.glob("*.hwpx"))
    assert made == ["doc-001.hwpx", "doc-002.hwpx"]
    # 진행 델타가 최소 1회 푸시됐다(진행바 갱신 계약).
    assert any(isinstance(snap, dict) and "progress" in snap for _s, snap in pushes)


def test_overwrite_confirm_flow(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
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
    assert snap["gate"]["enabled"] is False and "레코드" in snap["gate"]["text"]


def test_unknown_run_action_is_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 run 액션"):
        ctrl.dispatch("frobnicate", {})


def test_generate_without_job_is_loud_not_silent(tmp_path):
    ctrl, _ = _controller(tmp_path)
    res = ctrl.generate()
    assert res["ok"] is False and "작업" in res["error"]


# ============================================================ #26 #6 — 2소스(등록 데이터)
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry


def _pool_controller(tmp_path):
    """풀 레지스트리를 tmp 로 격리 주입한 실행 컨트롤러 + 풀."""
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pushes: list = []
    ctrl = RunController(
        _registry(tmp_path), lambda s, snap: pushes.append((s, snap)),
        pool_registry=pool,
    )
    return ctrl, pool


def test_pool_sources_lists_active_only_including_nara(tmp_path):
    """실행 후보 목록 = **active 만**(ADR J) — nara 항목도 숨기지 않고 표시(거절은 겨눔 시점)."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    pool.save(DatasetPoolItem(name="나라쿼리", kind="nara", opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    archived = DatasetPoolItem(name="지난분기", kind="excel", opts={"path": "x.csv"})
    archived.archive()
    pool.save(archived)
    items = ctrl.dispatch("pool_sources", {})["items"]
    names = [i["name"] for i in items]
    assert "7월공고" in names and "나라쿼리" in names   # nara 표시(은닉 금지)
    assert "지난분기" not in names                       # archived 는 실행 후보 아님


def test_load_pool_targets_excel_reference(tmp_path):
    """등록 데이터 겨눔 성공 — 실행 시점 재읽기(싱크) + 소스 병기 라벨 + 선택 초기화."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert res["ok"] is True and res["label"] == "등록 데이터: 7월공고"
    snap = ctrl.snapshot()
    assert snap["data_source_label"] == "등록 데이터: 7월공고"
    assert snap["record_count"] == 2                     # d.csv 2행 재읽기


def test_load_pool_rejects_nara_frozen_loudly(tmp_path):
    """나라장터 항목 겨눔 = 동결 거절 문구 재진술(조용한 실패 금지)."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="나라쿼리", kind="nara", opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("load_pool", {"name": "나라쿼리"})
    assert res["ok"] is False and "동결" in res["error"]


def test_load_pool_dead_reference_is_restated(tmp_path):
    """죽은 참조(파일 이동·삭제)는 사용자 문구로 재진술 — 기존 겨눔은 무변경."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="유실참조", kind="excel", opts={"path": str(tmp_path / "없음.csv")}))
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("load_pool", {"name": "유실참조"})
    assert res["ok"] is False and "불러올 수 없습니다" in res["error"]
    assert ctrl.snapshot()["data_source_label"] == ""    # 실패가 상태를 오염시키지 않음


def test_load_pool_multi_sheet_without_sheet_is_rejected_loudly(tmp_path):
    """시트 미지정 다중시트 참조 겨눔 = 조용한 첫 시트 로드 대신 loud 거절(#26 #3, #33 재확립).

    등록 시점 게이트가 있어도 그 이전에 만들어진 모호 항목까지 겨눔 시점 단일 관문이 잡는다.
    """
    multi = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "multi_sheet.xlsx"
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="모호참조", kind="excel", opts={"path": str(multi)}))
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("load_pool", {"name": "모호참조"})
    assert res["ok"] is False and "시트" in res["error"]
    assert ctrl.snapshot()["data_source_label"] == ""    # 실패가 상태를 오염시키지 않음
    # 확정 시트가 참조에 있으면 관문이 존중해 통과.
    pool.save(DatasetPoolItem(
        name="확정참조", kind="excel", opts={"path": str(multi), "sheet": "낙찰현황"}))
    assert ctrl.dispatch("load_pool", {"name": "확정참조"})["ok"] is True


def test_load_pool_missing_item_is_loud(tmp_path):
    ctrl, _pool = _pool_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("load_pool", {"name": "없는이름"})
    assert res["ok"] is False and "찾을 수 없습니다" in res["error"]


def test_load_pool_without_job_is_loud(tmp_path):
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    res = ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert res["ok"] is False and "작업" in res["error"]


def test_file_load_sets_source_label_too(tmp_path):
    """파일 겨눔도 소스 병기 라벨을 낸다 — 두 소스의 라벨 문법 대칭."""
    ctrl, _pool = _pool_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.snapshot()["data_source_label"] == "파일: d.csv"


# ------------------------------------------- 기본 데이터셋 자동 조준(#53-A)
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
    assert snap["data_notice"]["level"] == "ok" and "자동 연결" in snap["data_notice"]["text"]


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


def test_select_job_without_default_ref_keeps_manual(tmp_path):
    """참조 없는 작업은 현행처럼 데이터 미겨눔으로 시작 — 자동 재진술도 없음."""
    ctrl, _pool = _pool_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})       # 기본 참조 없음
    snap = ctrl.snapshot()
    assert snap["has_data"] is False and snap["data_notice"] is None


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
    # 실행 화면은 작업 JSON 을 쓰지 않으므로 기본 데이터 참조는 그대로다(임시 override).
    assert ctrl.registry.load("공고서").default_dataset_ref == "7월공고"
