"""실행 ViewModel — Qt 불필요(헤드리스). 대상 전환·사전검증·게이트·표식 주입 계약.

위젯의 QThread/QMessageBox 없이 백엔드 결정 로직을 여기서 못박는다(누수 제거의 회귀 방어).
"""
from __future__ import annotations

from datetime import datetime

from pathlib import Path

import pytest
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths

from hwpxfiller.domain.job import Job, rules_fingerprints
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.data.factory import source_for_path
from hwpxfiller.gui.review_state import review_requirement
from hwpxfiller.gui.run_state import RunViewModel
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

MULTI_SHEET = Path(__file__).parent / "fixtures" / "multi_sheet.xlsx"


class _Src:
    """빈값 1필드를 포함한 가짜 DataSource(포트 준수)."""

    def records(self):
        return [
            {"bidNtceNm": "가", "presmptPrce": ""},
            {"bidNtceNm": "나", "presmptPrce": "2000"},
        ]

    def fields(self):
        return ["bidNtceNm", "presmptPrce"]


def _job(tmp_path) -> Job:
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "추정가격"])
    return Job(
        name="실행",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce"),
        ]),
        filename_pattern="doc-{{공고명}}",
        # 실행 게이트가 데이터 결속을 요구한다(#932 U4-C) — 미결속이면 「연결 필요」가
        # 앞서 서서, 이 파일이 재려는 뒤 단들(드리프트·토큰·폴더·선택)에 도달하지 못한다.
        data_path=str(tmp_path / "d.csv"), data_sheet="", data_header_row=0,
    )


def _write_template(path, fields):
    body = []
    for name in fields:
        body.append(
            f'<hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>'
            f'<hp:run><hp:t>{{{{{name}}}}}</hp:t></hp:run>'
            '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + "".join(body) + '</hp:p></hs:sec>'
    ).encode()
    write_hwpx_package(
        path,
        HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}),
    )


def _vm(tmp_path) -> RunViewModel:
    vm = RunViewModel(_job(tmp_path), engine=make_hwpx_engine())
    vm.datasource = _Src()
    vm.records = vm.datasource.records()
    return vm


def test_effective_template_switches_with_target_mode(tmp_path):
    vm = _vm(tmp_path)
    assert vm.effective_template() == vm.job.template_path  # 기본 신규
    prev = tmp_path / "prev.hwpx"
    prev.write_bytes(b"dummy")
    vm.set_target_mode("continue")
    vm.template_override = str(prev)
    assert vm.effective_template() == str(prev)
    vm.set_target_mode("new")                 # 신규 복귀 → override 해제
    assert vm.template_override is None
    assert vm.effective_template() == vm.job.template_path


def test_preflight_and_blank_fields(tmp_path):
    vm = _vm(tmp_path)
    pf = vm.preflight([0, 1])
    assert pf.empty_valued == ["추정가격"]     # rec0 에서 빈 값
    assert not pf.missing_columns             # 소스키 모두 존재
    assert pf.level == "warn"
    assert vm.blank_fields([0, 1]) == ["추정가격"]


def test_preflight_empty_when_no_datasource(tmp_path):
    vm = RunViewModel(_job(tmp_path), engine=make_hwpx_engine())          # 데이터 미겨눔
    assert vm.preflight([0]).level == "" and vm.blank_fields([0]) == []


# ------------------------------------------------------------ T2 시트 옵션 관통(링1)
def test_load_data_targets_confirmed_sheet(tmp_path):
    """sheet= 관통 — 확정 시트의 레코드가 겨눠진다(확정은 링2, 여기는 관통만).

    factory 는 **주입 seam 을 실제로 탔는지**까지 봉인한다(P2-16) — concrete 만 넣으면
    링1 안 잔존 import 로의 우회를 놓친다(호출 1회 + kwargs 관통을 기록으로 확인).
    """
    calls: list = []

    def recording_factory(path, *, sheet=None):
        calls.append((path, sheet))
        return source_for_path(path, sheet=sheet)

    vm = RunViewModel(_job(tmp_path), engine=make_hwpx_engine())
    recs = vm.load_data(str(MULTI_SHEET), sheet="낙찰현황", source_factory=recording_factory)
    assert [r["업체명"] for r in recs] == ["가나상사", "다라물산", "마바테크"]
    assert calls == [(str(MULTI_SHEET), "낙찰현황")]  # 주입 factory 경유 1회·sheet 관통
    # 대조군: 미지정(기본 첫 시트)은 다른 시트 내용 — 조용한 동치 금지.
    vm2 = RunViewModel(_job(tmp_path), engine=make_hwpx_engine())
    assert vm2.load_data(str(MULTI_SHEET), source_factory=source_for_path)[0] == {
        "공고명": "전산장비", "추정가격": "1000"
    }


def test_resolve_file_source_passes_sheet(tmp_path):
    """공용 리졸버도 같은 관통 — VM 경로와 갈라지는 드리프트 방지."""
    from hwpxfiller.gui.run_state import resolve_file_source

    _source, recs = resolve_file_source(
        str(MULTI_SHEET), sheet="낙찰현황", source_factory=source_for_path
    )
    assert recs[0]["업체명"] == "가나상사"


def test_mapped_records_injects_marker_only_on_empty(tmp_path):
    vm = _vm(tmp_path)
    marked = vm.mapped_records([0, 1], mark_missing="〘미입력·{field}〙")
    assert marked[0]["추정가격"] == "〘미입력·추정가격〙"  # 미충족 공란 → 표식
    assert marked[0]["공고명"] == "가"                    # 비빈 값 불변
    assert marked[1]["추정가격"] == "2000"
    # 표식 없이(기본) 부르면 빈 값 그대로.
    assert vm.mapped_records([0])[0]["추정가격"] == ""


def test_validate_generate_gate_order(tmp_path):
    prev = tmp_path / "prev.hwpx"
    _write_template(prev, ["공고명", "추정가격"])

    # 데이터 없음 = 첫 차단.
    vm0 = RunViewModel(_job(tmp_path), engine=make_hwpx_engine())
    assert "데이터" in vm0.validate_generate([0], "out")[0].message

    vm = _vm(tmp_path)
    assert vm.validate_generate([], "out")[0].message.startswith("생성할 문서")  # 선택 0
    assert vm.validate_generate([0], "")[0].message.startswith("저장 폴더")        # 폴더 미지정
    assert vm.validate_generate([0, 1], "out") == []                              # 신규 다건 OK

    # 누적: 이어채울 기존 문서 미선택 → 차단.
    vm.set_target_mode("continue")
    assert "기존 문서" in vm.validate_generate([0], "out")[0].message
    # 누적 + 2건 선택 → 단건 게이트.
    vm.template_override = str(prev)
    errs = vm.validate_generate([0, 1], "out")
    assert errs and "1건" in errs[0].message
    assert vm.validate_generate([0], "out") == []  # 누적 단건 OK


def test_missing_template_is_danger(tmp_path):
    vm = _vm(tmp_path)
    vm.job.template_path = str(tmp_path / "gone.hwpx")  # 존재하지 않음
    errs = vm.validate_generate([0], "out")
    assert errs and errs[0].level == "danger"


def test_field_states_report_missing_without_an_ack_axis(tmp_path):
    """U2 §2.13 — 필드축 ack 는 폐기됐다: 빈 값은 상태(missing)로 보고되고, 그 자체로
    게이트를 닫지 않는다(닫는 것은 blank_set 검토 요구 — screen_job 소관)."""
    vm = _vm(tmp_path)
    states = {s.name: s for s in vm.field_states([0, 1])}
    assert states["공고명"].state == "filled"
    assert states["추정가격"].state == "missing"
    assert vm.blank_fields([0, 1]) == ["추정가격"]      # 빈 값 판정의 단일 원천
    # ack 상태기계는 사망했다 — 부활하면 승인(blank_set)과 판정이 두 벌이 된다.
    for dead in ("acknowledge", "unacknowledge", "reset_acks", "acked_count", "unmet_blanks"):
        assert not hasattr(vm, dead), f"폐기된 ack 표면이 부활했습니다: {dead}"
    assert not hasattr(states["추정가격"], "acknowledged")
    # 빈 값이 있어도 링1 게이트는 전제조건만 본다(§2.13 — 승인 단이 blank_set 을 진다).
    assert vm.gate_state([0, 1], "out").enabled is True


def test_gate_absorbs_preconditions_inline(tmp_path):
    """UD-06: 데이터·폴더·레코드 전제조건을 게이트로 흡수 — '버튼 비활성 + 인라인 사유'.

    이전에는 활성 primary + 클릭 후 차단 모달로 이원화됐다(초기 상태 침묵).
    """
    # 데이터 미겨눔 → 닫힌 인라인 게이트('먼저 데이터를 선택하세요').
    vm_nodata = RunViewModel(_job(tmp_path), engine=make_hwpx_engine())
    gate = vm_nodata.gate_state([0])
    assert gate.enabled is False and gate.level == "warn" and "데이터" in gate.text

    vm = _vm(tmp_path)
    # 저장 폴더 미지정 → 인라인 warn(모달 아님).
    gate = vm.gate_state([0, 1])
    assert gate.enabled is False and gate.level == "warn" and "저장 폴더" in gate.text
    # 선택 0건 → 인라인 warn(문구는 사용자 어휘 '문서', R-copy PR #85 리뷰).
    gate = vm.gate_state([], "out")
    assert gate.enabled is False and gate.level == "warn" and "생성할 문서" in gate.text
    # 이어채우기 모드 + 문서 미선택 → 인라인 warn.
    vm.set_target_mode("continue")
    gate = vm.gate_state([0], "out")
    assert gate.enabled is False and "기존 문서" in gate.text


def test_field_states_empty_without_data(tmp_path):
    vm = RunViewModel(_job(tmp_path), engine=make_hwpx_engine())                    # 데이터 미겨눔
    assert vm.field_states([0]) == []
    assert vm.blank_fields([0]) == []


def test_declared_blank_is_quiet_but_uncovered_template_field_is_drift(tmp_path):
    job = _job(tmp_path)
    job.mapping.mappings[1] = FieldMapping("추정가격", type="blank")
    vm = RunViewModel(job, engine=make_hwpx_engine())
    vm.datasource = _Src()
    vm.records = vm.datasource.records()
    states = {s.name: s.state for s in vm.field_states([0])}
    assert states == {"공고명": "filled", "추정가격": "blank"}
    assert vm.validate_generate([0], "out") == []

    _write_template(job.template_path, ["공고명", "추정가격", "신규필드"])
    states = {s.name: s.state for s in vm.field_states([0])}
    assert states["신규필드"] == "drift"
    errs = vm.validate_generate([0], "out")
    assert errs and errs[0].level == "danger" and "신규필드" in errs[0].message


def test_mapping_orphan_is_drift_and_hard_gate(tmp_path):
    vm = _vm(tmp_path)
    _write_template(vm.job.template_path, ["공고명"])
    drift = vm.structure_drift()
    assert drift.mapping_orphaned == ("추정가격",)
    assert {s.name: s.state for s in vm.field_states([0])}["추정가격"] == "drift"
    assert "소멸" in vm.validate_generate([0], "out")[0].message


def test_structure_is_reread_and_parse_failure_fails_closed(tmp_path):
    vm = _vm(tmp_path)
    assert not vm.structure_drift().has_drift
    _write_template(vm.job.template_path, ["공고명", "추정가격", "재편집유입"])
    assert vm.structure_drift().template_uncovered == ("재편집유입",)

    vm.job.template_path = str(tmp_path / "broken.hwpx")
    (tmp_path / "broken.hwpx").write_bytes(b"not a zip")
    errs = vm.validate_generate([0], "out")
    assert errs and errs[0].level == "danger" and "읽을 수 없음" in errs[0].message


def test_load_data_empty_returns_empty_without_committing(tmp_path):
    vm = RunViewModel(_job(tmp_path), engine=make_hwpx_engine())
    csv = tmp_path / "empty.csv"
    csv.write_text("공고명,추정가격\n", encoding="utf-8-sig")  # 헤더만
    assert vm.load_data(str(csv), source_factory=source_for_path) == []
    assert vm.datasource is None  # 빈 데이터는 상태 미변경


# ------------------------------------------------------------- 덮어쓰기 확인(RC-02)
def test_output_conflicts_lists_existing_targets_only(tmp_path):
    """생성과 동일 규칙으로 계산한 대상 중 **디스크에 이미 있는** 파일만 보고(무변형).

    위젯 확인 대화상자의 원천 — 빈 목록이면 확인 없이 진행, 비면 안 되는 목록이면
    사용자 확정 후에만 overwrite=True(링1 계약).
    """
    vm = _vm(tmp_path)
    out = tmp_path / "out"
    assert vm.output_conflicts(
        [0, 1], str(out), existing_outputs=existing_output_paths
    ) == []

    out.mkdir()
    sentinel = out / "doc-가.hwpx"  # 패턴 doc-{{공고명}} × 레코드0(공고명=가)의 대상
    sentinel.write_bytes(b"user-edited")
    conflicts = vm.output_conflicts(
        [0, 1], str(out), existing_outputs=existing_output_paths
    )
    assert conflicts == [str(sentinel)]
    assert sentinel.read_bytes() == b"user-edited"  # 검출은 무변형


# ------------------------------------------------------------ 생성 계획(RC-07)
def test_generation_plan_is_immutable_snapshot(tmp_path):
    """계획은 클릭 시점 스냅샷 — 이후 VM/데이터가 바뀌어도 불변(라이브 재독 금지)."""
    import dataclasses

    from hwpxfiller.domain.job import MISSING_MARKER

    vm = _vm(tmp_path)
    plan = vm.build_generation_plan(
        [0, 1], str(tmp_path / "outA"), marker=MISSING_MARKER, ledger=True
    )
    assert plan.template == vm.job.template_path
    assert plan.out_dir == str(tmp_path / "outA")
    assert plan.records[0]["추정가격"] == MISSING_MARKER.format(field="추정가격")
    assert plan.source_pointer == "_Src"
    assert plan.indices == (0, 1)
    assert plan.job_name == "실행" and plan.source_keys == ("bidNtceNm", "presmptPrce")

    # 실행 중 데이터 재로드 모사(프로브2) — 계획은 옛 스냅샷 그대로.
    class _Swapped:
        def records(self):
            return [{"bidNtceNm": "바뀐공고", "presmptPrce": "9"}] * 2

        def fields(self):
            return ["bidNtceNm", "presmptPrce"]

    vm.datasource = _Swapped()
    vm.records = vm.datasource.records()
    assert plan.records[0]["공고명"] == "가"          # 재독 없음
    assert plan.source_records[0]["bidNtceNm"] == "가"
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.out_dir = "elsewhere"  # type: ignore[misc]


def test_export_plan_ledger_consumes_plan_not_live_state(tmp_path):
    """원장은 계획만 소비(RC-07) — 실행 중 out_dir 편집·데이터 교체가 증거에 못 낀다."""
    import json
    from pathlib import Path

    from hwpxfiller.batch import generate_batch
    from hwpxfiller.domain.job import MISSING_MARKER
    from hwpxfiller.external.ledger_export import export_plan_ledger

    vm = _vm(tmp_path)
    out = tmp_path / "outA"
    plan = vm.build_generation_plan(
        [0, 1], str(out), marker=MISSING_MARKER, ledger=True
    )
    batch = generate_batch(
        plan.template, list(plan.records), plan.out_dir, plan.pattern,
        make_hwpx_engine(), mapping=plan.mapping,
        existing_outputs=existing_output_paths, ensure_output_dir=ensure_output_directory,
    )
    assert batch.failed == 0

    # 프로브1·2 — 완료 전 위젯/VM 조작 모사: 원장은 여전히 계획(outA·옛 데이터)을 증거.
    vm.datasource = None
    vm.records = []
    sidecar = export_plan_ledger(plan, batch)
    assert Path(sidecar).parent == out                   # ed_out 재독 없음
    payload = json.loads(Path(sidecar).read_text(encoding="utf-8"))
    assert payload["job"] == "실행" and payload["source"] == "_Src"
    first = {r["field"]: r for r in payload["outputs"][0]["rows"]}
    assert first["공고명"]["preview_text"] == "가"       # 생성물과 같은 데이터의 증거
    assert first["공고명"]["injected"] is True
    # 표식 주입도 미충족으로 분류하되, 실제 들어간 값(표식)의 증거는 남는다.
    assert first["추정가격"]["status"] == "missing"
    assert first["추정가격"]["injected"] is True
    second = {r["field"]: r for r in payload["outputs"][1]["rows"]}
    assert second["추정가격"]["status"] == "filled" and second["추정가격"]["injected"] is True

    profs = {p["key"]: p for p in payload["profiles"]}
    assert set(profs) == {"bidNtceNm", "presmptPrce"}   # 매핑이 읽는 소스 키만 관측
    assert profs["presmptPrce"]["samples"] == ["2000"]


def test_export_plan_ledger_partial_batch_keeps_evidence(tmp_path):
    """취소된 부분 배치(RC-06)도 처리된 산출물만큼 증거를 남긴다 — strict zip 붕괴 금지."""
    from hwpxfiller.batch import generate_batch
    from hwpxfiller.external.ledger_export import export_plan_ledger

    vm = _vm(tmp_path)
    out = tmp_path / "out"
    plan = vm.build_generation_plan([0, 1], str(out), marker="", ledger=True)
    flag = {"stop": False}

    def progress(done, total):
        flag["stop"] = True  # 레코드 1 직후 취소

    batch = generate_batch(
        plan.template, list(plan.records), plan.out_dir, plan.pattern,
        make_hwpx_engine(),
        progress=progress, cancelled=lambda: flag["stop"],
        existing_outputs=existing_output_paths, ensure_output_dir=ensure_output_directory,
    )
    assert batch.cancelled and batch.attempted == 1

    import json
    from pathlib import Path
    sidecar = export_plan_ledger(plan, batch)
    payload = json.loads(Path(sidecar).read_text(encoding="utf-8"))
    assert len(payload["outputs"]) == 1  # 처리된 1건만 — 예외 없이 부분 증거


def test_export_plan_ledger_without_mapping_snapshot_is_loud():
    """계획에 매핑 스냅샷이 없으면 증거를 추정으로 조립하지 않고 시끄럽게 거절한다."""
    from hwpxfiller.external.ledger_export import export_plan_ledger
    from hwpxfiller.gui.run_state import GenerationPlan

    plan = GenerationPlan(
        template="t.hwpx", records=(), out_dir="out", pattern="p-{{seq}}",
        marker="", indices=(), source_pointer="",
    )
    with pytest.raises(ValueError, match="매핑 스냅샷"):
        export_plan_ledger(plan, batch=None)


# ------------------------------------------------ 상태 스냅샷·게이트 단일 산출(RC-23)
def test_gate_state_single_decision_drift_open(tmp_path):
    """게이트 표시 결정(활성/level/text)이 vm 단일 산출 — 위젯 재조립 없음(RC-23).

    구 「미확인 미입력(warn)」 단은 필드축 ack 폐기(U2 §2.13)로 죽었다 — 빈 값이 있어도
    링1 게이트는 전제조건 축만 보고, 표식 승인은 blank_set 검토 요구(호출측)가 진다.
    """
    vm = _vm(tmp_path)

    # 빈 값(추정가격)이 있어도 전제조건이 충족되면 링1 게이트는 열린다(§2.13).
    gate = vm.gate_state([0, 1], "out")
    assert gate.enabled is True and gate.level == "" and gate.text == ""

    # 드리프트 → danger 차단.
    _write_template(vm.job.template_path, ["공고명", "추정가격", "신규필드"])
    gate = vm.gate_state([0, 1])
    assert gate.enabled is False and gate.level == "danger"
    assert "매핑을 다시 확정" in gate.text and "신규필드" in gate.text


def test_gate_state_read_error_fails_closed(tmp_path):
    vm = _vm(tmp_path)
    (tmp_path / "broken.hwpx").write_bytes(b"not a zip")
    vm.job.template_path = str(tmp_path / "broken.hwpx")
    gate = vm.gate_state([0])
    assert gate.enabled is False and gate.level == "danger"
    assert "읽을 수 없어" in gate.text


def test_preflight_reflects_drift_no_green_pass_during_block(tmp_path):
    """RC-23 모순 신호 해소 — 드리프트 차단 중 사전검증이 '통과' 녹색으로 남지 않는다."""
    vm = _vm(tmp_path)
    _write_template(vm.job.template_path, ["공고명", "추정가격", "신규필드"])
    pf = vm.preflight([0, 1])
    assert pf.level == "danger"
    assert "구조" in pf.text and "통과" not in pf.text


def test_refresh_is_single_snapshot_and_parses_template_once(tmp_path, monkeypatch):
    """상태 리프레시 1회 = 템플릿 구조 1회 재읽기(RC-23: zip 5회 재파싱 해소).

    스냅샷의 세 표시면(사전검증·필드 상태·게이트)이 같은 계산에서 나온다.
    """
    from hwpxfiller.domain.engine import HwpxEngine

    vm = _vm(tmp_path)
    calls = {"n": 0}
    original = HwpxEngine.required_fields

    def counting(self, path):
        calls["n"] += 1
        return original(self, path)

    monkeypatch.setattr(HwpxEngine, "required_fields", counting)
    snap = vm.refresh([0, 1])
    assert calls["n"] == 1                       # 표시면별 재질의 없음
    assert snap.preflight.level == "warn"        # 빈 값 1필드(추정가격)
    assert {s.name: s.state for s in snap.field_states} == {
        "공고명": "filled", "추정가격": "missing",
    }
    assert snap.gate.enabled is False and snap.gate.level == "warn"


def test_set_acquired_swaps_data_atomically(tmp_path):
    """RC-22 — 직접 겨눔(set_acquired)이 datasource·records 를 원자 교체한다.

    구 「reset_acks 내장」 계약은 필드축 ack 폐기(U2 §2.13)로 대상이 사라졌다 — 빈 값
    집합은 이제 승인 지문 성분이라 데이터가 갈리면 승인이 키 결속으로 자동 무효가 된다.
    """
    vm = _vm(tmp_path)
    fresh = _Src()
    vm.set_acquired(fresh, fresh.records())       # 새 데이터 직접 겨눔
    assert vm.datasource is fresh
    assert vm.blank_fields([0, 1]) == ["추정가격"]  # 빈 값 판정은 새 데이터 기준


# ------------------------------------------------ 소스 포인터 선언 프로토콜(RC-25)
def test_source_pointer_uses_declared_protocol_not_type_name(tmp_path):
    """소스가 선언한 source_pointer() 가 우선 — 타입명 검사 아님(개명 내성, RC-25)."""
    from hwpxfiller.application.nara_acquire import AcquiredNaraData

    vm = RunViewModel(_job(tmp_path), engine=make_hwpx_engine())
    vm.datasource = AcquiredNaraData([{"bidNtceNm": "가"}], ["bidNtceNm"])
    assert vm.source_pointer() == "nara:취득 스냅샷(키 미포함)"

    # 클래스를 개명해도(서브클래스 = 다른 __name__) 원장 표기는 선언값 그대로 —
    # 종전 type(src).__name__ == "AcquiredNaraData" 비교였다면 침묵 오기록되던 자리.
    class RenamedSnapshot(AcquiredNaraData):
        pass

    vm.datasource = RenamedSnapshot([], [])
    assert vm.source_pointer() == "nara:취득 스냅샷(키 미포함)"


def test_source_pointer_falls_back_to_path_then_type_name(tmp_path):
    """미선언 소스 강등 순서: path 속성(file:) → 타입명(포트 명세의 폴백 계약)."""
    vm = RunViewModel(_job(tmp_path), engine=make_hwpx_engine())

    class _PathSrc(_Src):
        path = "C:/data/d.xlsx"

    vm.datasource = _PathSrc()
    assert vm.source_pointer() == "file:C:/data/d.xlsx"
    vm.datasource = _Src()
    assert vm.source_pointer() == "_Src"
    vm.datasource = None
    assert vm.source_pointer() == ""


# ------------------------------------------------ 파일명 토큰 계약 게이트(F34, RC-20 GUI 짝)
def _job_with_pattern(tmp_path, pattern, *, blank_price=False):
    """파일명 패턴만 바꾼 실행 작업 — blank_price=True 면 추정가격을 '비움' 선언."""
    job = _job(tmp_path)
    job.filename_pattern = pattern
    if blank_price:
        job.mapping = MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", type="blank"),
        ])
    return job


def test_unresolved_name_token_closes_gate_danger(tmp_path):
    """매핑이 채우지 않는 파일명 토큰 = danger 차단 + 사전검증 녹색 금지(F34).

    101 워크스루 실증 결함: '공고서-{{ID}}' 패턴이 무경고 통과해 미해소 {{ID}} 가
    실파일명으로 출하됐다(CLI 엔 게이트 있음 — 표면 비대칭).
    """
    vm = RunViewModel(_job_with_pattern(tmp_path, "공고서-{{ID}}"), engine=make_hwpx_engine())
    vm.datasource = _Src()
    vm.records = vm.datasource.records()
    status = vm.refresh([0, 1], str(tmp_path / "out"))
    assert status.gate.enabled is False and status.gate.level == "danger"
    assert "{{ID}}" in status.gate.text and "파일명 패턴" in status.gate.text
    assert status.preflight.level == "danger"              # '검증 완료' 녹색과 공존 금지
    assert "파일명" in status.preflight.text


def test_unresolved_name_token_fires_before_data_selection(tmp_path):
    """토큰 계약은 작업 정의 수준 — 데이터 미겨눔에서도 danger 로 먼저 발화한다(F34).

    고칠 수 없는 작업에 데이터부터 고르게 하지 않는다(경고 순서의 정직성)."""
    vm = RunViewModel(_job_with_pattern(tmp_path, "공고서-{{ID}}"), engine=make_hwpx_engine())  # 데이터 없음
    status = vm.refresh([])
    assert status.gate.enabled is False and status.gate.level == "danger"
    assert "{{ID}}" in status.gate.text


def test_unresolved_name_token_blocks_generate_backstop(tmp_path):
    """validate_generate 백스톱 — 게이트 우회(워커/API 직접 호출)도 danger 차단(F34)."""
    vm = RunViewModel(_job_with_pattern(tmp_path, "공고서-{{ID}}"), engine=make_hwpx_engine())
    vm.datasource = _Src()
    vm.records = vm.datasource.records()
    errors = vm.validate_generate([0, 1], str(tmp_path / "out"))
    assert errors and errors[0].level == "danger" and "{{ID}}" in errors[0].message


def test_blank_declared_field_token_is_unresolved(tmp_path):
    """'비움' 선언 필드의 토큰도 미해소다 — 매핑 출력 dict 에서 빠져 리터럴로 남는다(F34)."""
    vm = RunViewModel(_job_with_pattern(tmp_path, "doc-{{추정가격}}", blank_price=True), engine=make_hwpx_engine())
    assert vm.unresolved_name_tokens() == ["추정가격"]


def test_name_token_gate_points_at_a_screen_that_exists(tmp_path):
    """게이트 문안이 사망한 화면을 지시하지 않는다(#128) — 「작업 에디터」는 결정 39·40 으로 사망.

    같은 자리 드리프트 배너는 이미 "편집에서…"로 개정돼 있었다. 두 danger 가 같은 목적지를
    다르게 부르면 둘 중 하나는 반드시 존재하지 않는 곳을 가리킨다.
    """
    vm = RunViewModel(_job_with_pattern(tmp_path, "공고서-{{ID}}"), engine=make_hwpx_engine())
    vm.datasource = _Src()
    vm.records = vm.datasource.records()
    text = vm.refresh([0, 1], str(tmp_path / "out")).gate.text
    assert "작업 에디터" not in text, f"사망한 화면을 지시합니다: {text!r}"
    assert "편집에서 파일명 패턴을 고쳐야" in text, text


def test_mapped_and_reserved_tokens_open_gate(tmp_path):
    """매핑 커버 토큰·예약 토큰({{date}}/{{seq}})·기본 패턴은 게이트를 닫지 않는다(F34b)."""
    from hwpxfiller.domain.job import DEFAULT_FILENAME_PATTERN

    for pattern in ("doc-{{공고명}}", "doc-{{date}}-{{seq:001}}", DEFAULT_FILENAME_PATTERN):
        vm = RunViewModel(_job_with_pattern(tmp_path, pattern), engine=make_hwpx_engine())
        vm.datasource = _Src()
        vm.records = vm.datasource.records()
        assert vm.unresolved_name_tokens() == []
        status = vm.refresh([0, 1], str(tmp_path / "out"), now=datetime(2026, 7, 21))
        assert "파일명 패턴" not in status.gate.text


# ------------------------------------------------ 검토는 게이트가 아니라 고지다(#957)
def test_review_requirement_no_longer_closes_the_gate(tmp_path):
    """#957 정책 선회 — 검토 요구가 서 있어도 **게이트는 열린다**.

    U4 §34(「빈 값도 확인하면 생성 허용 — 게이트 유지 확정」)의 명시적 뒤집기다: 이상은
    알리되 생성을 막지 않고, 사용자가 결과 문서를 한 번 더 본다. 게이트 서열에서 검토 단이
    사라졌으므로 전제조건이 다 갖춰진 새 작업은 그대로 실행 가능하다.
    """
    vm = _vm(tmp_path)
    req = review_requirement(vm.job)  # 완주 이력 없음 = 새 작업(§13-3)
    assert req.required

    # 전제조건은 그대로 게이트다 — 검토만 걷혔다.
    gate = vm.refresh([], "out", review_notice=req).gate
    assert "선택하세요" in gate.text and gate.reason == ""
    gate = vm.refresh([1], "", review_notice=req).gate
    assert "저장 폴더" in gate.text and gate.reason == ""

    # 빈 값 없는 레코드만 골라 다른 경고와 섞이지 않는 자리를 만든다.
    status = vm.refresh([1], "out", review_notice=req)
    assert status.gate.enabled is True and status.gate.reason == ""
    # 그리고 **아무 말도 하지 않는다**: 첫 실행 고지는 간소화 라운드에서 퇴역했다 —
    # 결과 확인은 상수라 「첫 실행입니다」가 바꾸는 행동이 없다. 요구는 서 있어도
    # 사전검증은 조용하고, 없는 실행을 들먹이는 일반 문안으로 새지도 않는다.
    assert status.preflight.notices == ()
    assert "첫 실행" not in status.preflight.text
    assert "마지막 실행" not in status.preflight.text
    assert status.preflight.level == "ok"


def test_changed_rules_notice_names_the_targets(tmp_path):
    """바뀐 규칙 고지는 **무엇이 바뀌었는지**를 적는다 — 이름 없는 알림은 확인을 못 시킨다."""
    vm = _vm(tmp_path)
    vm.job.last_run_at = "2026-08-01T09:00:00"
    vm.job.reviewed_rules = dict(rules_fingerprints(vm.job))
    vm.job.mapping.mappings[0].source = "presmptPrce"   # source 축 변경 = semantic_binding
    status = vm.refresh([1], "out", review_notice=review_requirement(vm.job))
    assert status.gate.enabled is True
    assert status.preflight.notices == (
        "[알림] 마지막 실행 이후 바뀐 규칙이 있습니다: 공고명(연결). "
        "결과 문서를 열어 확인하세요.",
    )


def test_blank_values_do_not_get_a_second_notice(tmp_path):
    """빈 값의 자리는 「[경고] 빈 값 필드」 하나다 — 한 사실이 한 면에 두 줄로 서지 않는다."""
    vm = _vm(tmp_path)
    vm.job.last_run_at = "2026-08-01T09:00:00"
    vm.job.reviewed_rules = dict(rules_fingerprints(vm.job))
    blanks = tuple(vm.blank_fields([0, 1]))
    req = review_requirement(vm.job, blank_fields=blanks)
    assert req.risk_class == "blank_set"
    status = vm.refresh([0, 1], "out", review_notice=req)
    assert status.gate.enabled is True
    assert status.preflight.notices == ()
    assert "[알림]" not in status.preflight.text


def test_drift_still_outranks_and_blocks(tmp_path):
    """구조 불일치(danger)는 그대로 차단이다 — 걷힌 것은 검토 단뿐이다."""
    vm = _vm(tmp_path)
    _write_template(vm.job.template_path, ["공고명", "추정가격", "신규필드"])
    gate = vm.refresh([0, 1], "out", review_notice=review_requirement(vm.job)).gate
    assert gate.reason == "drift" and gate.level == "danger"


def test_no_review_requirement_leaves_the_gate_open(tmp_path):
    """§13-2 — 규칙이 그대로면 게이트는 열려 있고 고지도 없다."""
    vm = _vm(tmp_path)
    status = vm.refresh([1], "out", review_notice=None)
    assert status.gate.enabled is True and status.preflight.notices == ()


def test_path_length_warns_without_blocking_generation(tmp_path):
    """C-01 미충족분(재작성 F5 판정 K) — 사전에 말하되 **막지는 않는다**(2R P2).

    막으면 확장 경로·`longPathsEnabled` 환경에서 **실제로 성공하는** 사용자가 UI 로는
    아예 만들 수 없다. 그렇다고 침묵하면 생성 중 OSError 로만 드러난다. 그래서 게이트가
    아니라 사전검증 경고이고, 문안도 단정하지 않는다("실패한다"가 아니라 "할 수 있다").
    """
    vm = _vm(tmp_path)
    vm.job.filename_pattern = "{{공고명}}" + "가" * 250
    status = vm.refresh([0, 1], "C:/out")
    assert status.gate.enabled is True, "휴리스틱이 생성을 막고 있습니다."
    assert status.preflight.level == "warn"
    assert "저장에 실패할 수 있는 문서 2건" in status.preflight.text
    assert len(status.audit.too_long) == 2


def test_path_length_is_silent_where_the_limit_does_not_exist(tmp_path, monkeypatch):
    """휴리스틱은 그것이 참인 환경에서만 말한다 — POSIX 에 260 은 없다."""
    monkeypatch.setattr("hwpxfiller.naming.os.name", "posix")
    vm = _vm(tmp_path)
    vm.job.filename_pattern = "{{공고명}}" + "가" * 250
    status = vm.refresh([0, 1], "/out")
    # 이 픽스처는 빈 값이 있어 preflight 자체는 warn 이다 — 재는 것은 **경로 길이 절이
    # 붙지 않는다**는 사실이다(존재하지 않는 한계로 경보하지 않는다).
    assert status.audit.too_long == ()
    assert "저장에 실패할 수 있는" not in status.preflight.text


def test_short_paths_do_not_warn(tmp_path):
    vm = _vm(tmp_path)
    status = vm.gate_state([0, 1], "C:/out")
    assert status.enabled is True


def test_audit_and_table_share_one_captured_timestamp(tmp_path):
    """2R P2 — 게이트 감사와 표 「문서」 열이 다른 시각을 잡으면 `{{date:SS}}` 가 초
    경계를 넘는 순간 미리보기가 승인시킨 이름과 생성물이 갈린다(덮어쓰기 대상까지)."""
    from datetime import datetime as _dt

    vm = _vm(tmp_path)
    vm.job.filename_pattern = "doc-{{date:HHmmSS}}"
    fixed = _dt(2026, 1, 2, 3, 4, 5)
    audit = vm.refresh([0, 1], "C:/out", now=fixed).audit
    assert audit.names[0] == "doc-030405.hwpx"
