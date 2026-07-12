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
