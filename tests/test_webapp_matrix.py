"""여러 작업 실행(matrix) 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 화면 #14 이관의 회귀 심. 작업 다중선택 → 공통 데이터 겨눔 → 작업별 미입력 강제 확인
게이트(ADR-E·UD-04) → 덮어쓰기 재진술(RC-02) → 작업별 하위폴더 생성 end-to-end 를 창 없이
확인한다. 실 HWPX 를 만들어 실제 문서 생성까지 되읽는다(파일 다이얼로그·폴더 피커만 브리지가
담당 — 여기선 경로 직접 주입).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.webapp.screen_matrix import MatrixController
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
    """두 작업(공고서·낙찰통지) — 공고서는 미입력 유발 필드를 둬 게이트를 태운다."""
    t1 = tmp_path / "gonggo.hwpx"
    _write_template(t1, ["공고명", "추정가격"])
    t2 = tmp_path / "nakchal.hwpx"
    _write_template(t2, ["업체명"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서",
        template_path=str(t1),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce"),
        ]),
        filename_pattern="gong-{{seq:001}}",
    ))
    reg.save(Job(
        name="낙찰통지",
        template_path=str(t2),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="업체명", source="bidNtceNm"),
        ]),
        filename_pattern="nak-{{seq:001}}",
    ))
    return reg


def _controller(tmp_path: Path) -> "tuple[MatrixController, list]":
    pushes: list = []
    ctrl = MatrixController(_registry(tmp_path), lambda s, snap: pushes.append((s, snap)))
    return ctrl, pushes


def _data_csv(tmp_path: Path) -> str:
    # rec0 은 추정가격 빈값(→ 공고서 '미입력'), rec1 은 채움 — 작업별 강제 확인 게이트를 태운다.
    csv = tmp_path / "d.csv"
    csv.write_text("bidNtceNm,presmptPrce\n전산장비,\n사무비품,2000000\n", encoding="utf-8")
    return str(csv)


def test_initial_lists_jobs_and_loud_gate(tmp_path):
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert [j["name"] for j in snap["jobs"]] == ["공고서", "낙찰통지"]
    assert snap["selection_count"] == 0
    # 아무 작업도 없으면 게이트가 시끄럽게 닫힌다(조용한 활성 금지).
    assert snap["gate"]["enabled"] is False and "작업" in snap["gate"]["text"]


def test_select_jobs_then_data_populates_per_job_badges(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("toggle_job", {"name": "공고서", "value": True})
    ctrl.dispatch("toggle_job", {"name": "낙찰통지", "value": True})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["selection_count"] == 2
    assert snap["has_data"] is True and snap["record_count"] == 2
    assert snap["selected_count"] == 2  # 데이터 겨눔 = 전체 선택 초기화
    # 작업별 필드 요약 — 공고서에 미입력(추정가격), 낙찰통지는 채움.
    by_job = {js["job_name"]: {s["name"]: s["state"] for s in js["states"]}
              for js in snap["field_summaries"]}
    assert by_job["공고서"]["공고명"] == "filled"
    assert by_job["공고서"]["추정가격"] == "missing"
    assert by_job["낙찰통지"]["업체명"] == "filled"


def test_missing_gate_blocks_generate_until_acked(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("toggle_job", {"name": "공고서", "value": True})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))

    # 게이트 닫힘: 미확인 미입력(공고서·추정가격) → 버튼 비활성 + 인라인 사유.
    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False and "미입력" in snap["gate"]["text"]

    # 생성 시도도 방어적으로 차단(worker/API 우회 방지).
    res = ctrl.generate()
    assert res["ok"] is False and "미입력" in res["error"]

    # 배지 클릭 = (작업, 필드) 직접 확인 → 게이트 열림.
    ctrl.dispatch("ack_field", {"job": "공고서", "field": "추정가격"})
    assert ctrl.snapshot()["gate"]["enabled"] is True


def test_generate_writes_per_job_subfolders_and_marks_missing(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("set_all_jobs", {})           # 전체 선택 = 두 작업
    ctrl.load_data_path(_data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("ack_field", {"job": "공고서", "field": "추정가격"})

    res = ctrl.generate()
    assert res["ok"] is True
    assert res["succeeded"] == 4 and res["failed"] == 0   # 2작업 × 2행
    # 미입력(공고서·추정가격)은 표식이 들어갔음을 완료 요약이 병기(낙관 서사 해소).
    assert "미입력 표시 필드" in res["summary"]
    # 작업별 하위폴더에 문서가 생성됐다(교차 충돌 차단).
    assert sorted(p.name for p in (out / "공고서").glob("*.hwpx")) == ["gong-001.hwpx", "gong-002.hwpx"]
    assert sorted(p.name for p in (out / "낙찰통지").glob("*.hwpx")) == ["nak-001.hwpx", "nak-002.hwpx"]
    # 진행 델타가 최소 1회 푸시됐다(진행바 갱신 계약).
    assert any(isinstance(snap, dict) and "progress" in snap for _s, snap in pushes)


def test_overwrite_confirm_flow(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("toggle_job", {"name": "낙찰통지", "value": True})  # 미입력 없는 작업만
    ctrl.load_data_path(_data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    assert ctrl.generate()["ok"] is True  # 최초 생성

    # 같은 폴더 재생성 → 조용한 덮어쓰기 금지: 재진술 요구.
    res = ctrl.generate()
    assert res["ok"] is False and res.get("needs_overwrite") is True
    assert "덮어" in res["overwrite_text"]
    # 확인 후 재호출 → 생성.
    assert ctrl.generate(confirm_overwrite=True)["ok"] is True


def test_select_none_jobs_closes_gate(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("toggle_job", {"name": "낙찰통지", "value": True})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    assert ctrl.snapshot()["gate"]["enabled"] is True
    ctrl.dispatch("set_none_jobs", {})
    snap = ctrl.snapshot()
    assert snap["selection_count"] == 0
    assert snap["gate"]["enabled"] is False and "작업" in snap["gate"]["text"]


def test_unknown_matrix_action_is_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 matrix 액션"):
        ctrl.dispatch("frobnicate", {})
