"""실행 ViewModel — Qt 불필요(헤드리스). 대상 전환·사전검증·게이트·표식 주입 계약.

위젯의 QThread/QMessageBox 없이 백엔드 결정 로직을 여기서 못박는다(누수 제거의 회귀 방어).
"""
from __future__ import annotations

import pytest

from hwpxfiller.core.job import Job
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.run_state import RunViewModel
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage


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
            FieldMapping(template_field="공고명", sources=["bidNtceNm"]),
            FieldMapping(template_field="추정가격", sources=["presmptPrce"]),
        ]),
        filename_pattern="doc-{{공고명}}",
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
    HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}).save(str(path))


def _vm(tmp_path) -> RunViewModel:
    vm = RunViewModel(_job(tmp_path))
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
    vm = RunViewModel(_job(tmp_path))          # 데이터 미겨눔
    assert vm.preflight([0]).level == "" and vm.blank_fields([0]) == []


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
    vm0 = RunViewModel(_job(tmp_path))
    assert "데이터" in vm0.validate_generate([0], "out")[0].message

    vm = _vm(tmp_path)
    assert vm.validate_generate([], "out")[0].message.startswith("생성할 레코드")  # 선택 0
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


def test_field_states_unmet_and_acknowledge(tmp_path):
    vm = _vm(tmp_path)
    states = {s.name: s for s in vm.field_states([0, 1])}
    assert states["공고명"].state == "filled"
    assert states["추정가격"].state == "missing" and not states["추정가격"].acknowledged
    assert vm.unmet_blanks([0, 1]) == ["추정가격"]      # 미확인 미입력 = 게이트 닫힘

    vm.acknowledge("추정가격")
    acked = {s.name: s.acknowledged for s in vm.field_states([0, 1])}
    assert acked["추정가격"] is True
    assert vm.unmet_blanks([0, 1]) == []               # 확인 → 게이트 열림

    vm.reset_acks()
    assert vm.unmet_blanks([0, 1]) == ["추정가격"]      # 초기화 → 다시 닫힘


def test_field_states_empty_without_data(tmp_path):
    vm = RunViewModel(_job(tmp_path))                    # 데이터 미겨눔
    assert vm.field_states([0]) == []
    assert vm.unmet_blanks([0]) == []


def test_declared_blank_is_quiet_but_uncovered_template_field_is_drift(tmp_path):
    job = _job(tmp_path)
    job.mapping.mappings[1] = FieldMapping("추정가격", transform="blank")
    vm = RunViewModel(job)
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
    vm = RunViewModel(_job(tmp_path))
    csv = tmp_path / "empty.csv"
    csv.write_text("공고명,추정가격\n", encoding="utf-8-sig")  # 헤더만
    assert vm.load_data(str(csv)) == []
    assert vm.datasource is None  # 빈 데이터는 상태 미변경


# ------------------------------------------------------------- 덮어쓰기 확인(RC-02)
def test_output_conflicts_lists_existing_targets_only(tmp_path):
    """생성과 동일 규칙으로 계산한 대상 중 **디스크에 이미 있는** 파일만 보고(무변형).

    위젯 확인 대화상자의 원천 — 빈 목록이면 확인 없이 진행, 비면 안 되는 목록이면
    사용자 확정 후에만 overwrite=True(링1 계약).
    """
    vm = _vm(tmp_path)
    out = tmp_path / "out"
    assert vm.output_conflicts([0, 1], str(out)) == []  # 폴더 자체가 없음 → 무충돌

    out.mkdir()
    sentinel = out / "doc-가.hwpx"  # 패턴 doc-{{공고명}} × 레코드0(공고명=가)의 대상
    sentinel.write_bytes(b"user-edited")
    conflicts = vm.output_conflicts([0, 1], str(out))
    assert conflicts == [str(sentinel)]
    assert sentinel.read_bytes() == b"user-edited"  # 검출은 무변형


# ------------------------------------------------------------ 생성 계획(RC-07)
def test_generation_plan_is_immutable_snapshot(tmp_path):
    """계획은 클릭 시점 스냅샷 — 이후 VM/데이터가 바뀌어도 불변(라이브 재독 금지)."""
    import dataclasses

    from hwpxfiller.core.job import MISSING_MARKER

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
    from hwpxfiller.core.job import MISSING_MARKER
    from hwpxfiller.gui.run_state import export_plan_ledger

    vm = _vm(tmp_path)
    out = tmp_path / "outA"
    plan = vm.build_generation_plan(
        [0, 1], str(out), marker=MISSING_MARKER, ledger=True
    )
    batch = generate_batch(
        plan.template, list(plan.records), plan.out_dir, plan.pattern,
        mapping=plan.mapping,
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


def test_export_plan_ledger_partial_batch_keeps_evidence(tmp_path):
    """취소된 부분 배치(RC-06)도 처리된 산출물만큼 증거를 남긴다 — strict zip 붕괴 금지."""
    from hwpxfiller.batch import generate_batch
    from hwpxfiller.gui.run_state import export_plan_ledger

    vm = _vm(tmp_path)
    out = tmp_path / "out"
    plan = vm.build_generation_plan([0, 1], str(out), marker="", ledger=True)
    flag = {"stop": False}

    def progress(done, total):
        flag["stop"] = True  # 레코드 1 직후 취소

    batch = generate_batch(
        plan.template, list(plan.records), plan.out_dir, plan.pattern,
        progress=progress, cancelled=lambda: flag["stop"],
    )
    assert batch.cancelled and batch.attempted == 1

    import json
    from pathlib import Path
    sidecar = export_plan_ledger(plan, batch)
    payload = json.loads(Path(sidecar).read_text(encoding="utf-8"))
    assert len(payload["outputs"]) == 1  # 처리된 1건만 — 예외 없이 부분 증거


# ------------------------------------------------------------------ 생성 원장(L2)
def test_export_run_ledger_writes_evidence_sidecar(tmp_path):
    import json
    from pathlib import Path

    from hwpxfiller.batch import generate_batch
    from hwpxfiller.core.job import MISSING_MARKER

    vm = _vm(tmp_path)
    indices = [0, 1]
    mapped = vm.mapped_records(indices, MISSING_MARKER)  # 위젯의 생성 경로와 동일 표식
    out = tmp_path / "out"
    batch = generate_batch(
        vm.job.template_path, mapped, str(out), vm.job.filename_pattern
    )
    assert batch.failed == 0

    sidecar = vm.export_run_ledger(
        str(out), indices, batch, mark_missing=MISSING_MARKER
    )
    payload = json.loads(Path(sidecar).read_text(encoding="utf-8"))
    assert payload["job"] == "실행"
    assert payload["source"] == "_Src"                  # 포인터-온리(값·쿼리 박제 없음)

    first = {r["field"]: r for r in payload["outputs"][0]["rows"]}
    assert first["공고명"]["status"] == "filled" and first["공고명"]["injected"] is True
    # 표식 주입도 미충족으로 분류하되, 실제 들어간 값(표식)의 증거는 남는다.
    assert first["추정가격"]["status"] == "missing"
    assert first["추정가격"]["injected"] is True
    second = {r["field"]: r for r in payload["outputs"][1]["rows"]}
    assert second["추정가격"]["status"] == "filled" and second["추정가격"]["injected"] is True

    profs = {p["key"]: p for p in payload["profiles"]}
    assert set(profs) == {"bidNtceNm", "presmptPrce"}   # 매핑이 읽는 소스 키만 관측
    assert profs["presmptPrce"]["samples"] == ["2000"]


# ------------------------------------------------ 상태 스냅샷·게이트 단일 산출(RC-23)
def test_gate_state_single_decision_drift_unmet_open(tmp_path):
    """게이트 표시 결정(활성/level/text)이 vm 단일 산출 — 위젯 재조립 없음(RC-23)."""
    vm = _vm(tmp_path)

    # 미확인 미입력 → warn 차단.
    gate = vm.gate_state([0, 1])
    assert gate.enabled is False and gate.level == "warn"
    assert "미입력" in gate.text and "추정가격" in gate.text

    # 확인(ack) → 열림(문구 없음).
    vm.acknowledge("추정가격")
    gate = vm.gate_state([0, 1])
    assert gate.enabled is True and gate.level == "" and gate.text == ""

    # 드리프트 → danger 차단(미입력보다 우선).
    _write_template(vm.job.template_path, ["공고명", "추정가격", "신규필드"])
    gate = vm.gate_state([0, 1])
    assert gate.enabled is False and gate.level == "danger"
    assert "매핑을 다시 확정" in gate.text and "신규필드" in gate.text


def test_gate_state_read_error_fails_closed(tmp_path):
    vm = _vm(tmp_path)
    vm.acknowledge("추정가격")
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
    from hwpxfiller.core.engine import HwpxEngine

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


def test_set_acquired_resets_acks_atomically(tmp_path):
    """RC-22 — 직접 겨눔(set_acquired)이 reset_acks 를 내장: stale ack 게이트 통과 차단."""
    vm = _vm(tmp_path)
    vm.acknowledge("추정가격")
    assert vm.unmet_blanks([0, 1]) == []          # 확인됨(게이트 열림)

    vm.set_acquired(_Src(), _Src().records())     # 새 데이터 직접 겨눔
    assert vm.unmet_blanks([0, 1]) == ["추정가격"]  # ack 이월 없음 — 다시 닫힘


# ------------------------------------------------ 소스 포인터 선언 프로토콜(RC-25)
def test_source_pointer_uses_declared_protocol_not_type_name(tmp_path):
    """소스가 선언한 source_pointer() 가 우선 — 타입명 검사 아님(개명 내성, RC-25)."""
    from hwpxfiller.gui.nara_state import AcquiredNaraData

    vm = RunViewModel(_job(tmp_path))
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
    vm = RunViewModel(_job(tmp_path))

    class _PathSrc(_Src):
        path = "C:/data/d.xlsx"

    vm.datasource = _PathSrc()
    assert vm.source_pointer() == "file:C:/data/d.xlsx"
    vm.datasource = _Src()
    assert vm.source_pointer() == "_Src"
    vm.datasource = None
    assert vm.source_pointer() == ""
