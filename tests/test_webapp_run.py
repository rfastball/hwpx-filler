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
