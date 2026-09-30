"""창 없는 managed 생성(:mod:`hwpxfiller.external.headless_generation`) — CLI 척추의 헤드리스 owner.

CLI 가 GUI 와 같은 managed 파이프라인을 임시 작업공간에서 탄다(#1081 PR3). 여기서 재는 것은
그 조립의 결과 합타입과, 종전 legacy 엔진(``HwpxEngine.generate``)이 지던 채움 사실 중 managed
가 그대로 이어받아야 하는 것들이다 — 줄배치 캐시 제거(#95)·채움 완화 노트(#154)·기입 불가
자리의 노트·깨진 템플릿의 시끄러운 거절. 표면 문장·종료 코드는 ``test_cli`` 가 잰다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.domain.fields import FillNote, read_fields
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.delivery_coordinator import DeliveryCompleted
from hwpxfiller.external.headless_generation import (
    EXECUTION_NOT_SEALABLE,
    RECORD_VALIDATION,
    TEMPLATE_INITIALIZATION,
    HeadlessExecuted,
    HeadlessNeedsOverwrite,
    HeadlessRefused,
    run_headless_generation,
)
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.hwpx_package_io import read_hwpx_package, write_hwpx_package

CORPUS_NOTICE = Path(__file__).parent / "corpus" / "real" / "bid_notice_limited_under100m.hwpx"
_SECTION = (
    '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
    ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">{}</hs:sec>'
)


def _run(tmp_path: Path, template: Path, records, *, mapping=None, overwrite=False, n=0):
    fields = make_hwpx_engine().required_fields(str(template))
    return run_headless_generation(
        workspace=tmp_path / f"ws{n}",
        template_path=str(template),
        mapping=mapping or MappingProfile(mappings=[FieldMapping(f, f) for f in fields]),
        filename_pattern="doc-{{seq:001}}",
        records=records,
        source_schema_keys=tuple(dict.fromkeys(k for r in records for k in r)),
        output_directory=str(tmp_path / "out"),
        overwrite=overwrite,
        clock=datetime.now,
    )


def _template(tmp_path: Path, *sections: str) -> Path:
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    for index, body in enumerate(sections):
        pkg.entries[f"Contents/section{index}.xml"] = _SECTION.format(body).encode("utf-8")
    path = tmp_path / "tpl.hwpx"
    write_hwpx_package(path, pkg)
    return path


def _field(name: str, inner: str = "") -> str:
    return (
        f'<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>{inner}'
        "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"
    )


def _completed(result) -> DeliveryCompleted:
    assert isinstance(result, HeadlessExecuted), result
    assert isinstance(result.outcome, DeliveryCompleted), result.outcome
    return result.outcome


# ------------------------------------------------------- 실행·재실행·거절
def test_second_run_asks_to_overwrite_and_overwrite_rewrites(tmp_path):
    tpl = _template(tmp_path, _field("계약명", "<hp:run><hp:t>구값</hp:t></hp:run>"))
    records = [{"계약명": "가"}, {"계약명": "나"}]
    first = _completed(_run(tmp_path, tpl, records))
    assert [doc.relative_path for doc in first.delivered] == ["doc-001.hwpx", "doc-002.hwpx"]

    asked = _run(tmp_path, tpl, records, n=1)
    assert asked == HeadlessNeedsOverwrite(("doc-001.hwpx", "doc-002.hwpx"))

    again = _completed(_run(tmp_path, tpl, records, overwrite=True, n=2))
    assert [doc.collision_disposition for doc in again.delivered] == ["WRITE_OVERWRITE"] * 2


def test_a_record_the_plan_cannot_validate_writes_nothing(tmp_path):
    """연결한 열이 한 레코드에서라도 빠지면 배달 전 거절 — 문서 0건(전건 검증 뒤 배달)."""
    tpl = _template(tmp_path, _field("계약명", "<hp:run><hp:t>구값</hp:t></hp:run>"))
    mapping = MappingProfile(mappings=[FieldMapping("계약명", "이름")])
    result = _run(tmp_path, tpl, [{"이름": "가"}, {"다른": "나"}], mapping=mapping)
    assert isinstance(result, HeadlessRefused) and result.stage == RECORD_VALIDATION
    assert result.details  # 어느 행·어느 열인지 말한다
    assert not (tmp_path / "out").exists()


def test_a_broken_template_is_refused_at_initialization(tmp_path):
    """짝 없는 fieldBegin — 종전 legacy 엔진이 결과 실패(unmatched-begin)로 내던 것을 managed 는
    초기 등록 거절로 낸다. 어느 쪽이든 문서는 만들지 않는다."""
    begin_only = (
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run></hp:p>'
    )
    tpl = _template(tmp_path, begin_only)
    result = run_headless_generation(
        workspace=tmp_path / "ws",
        template_path=str(tpl),
        mapping=MappingProfile(mappings=[FieldMapping("계약명", "계약명")]),
        filename_pattern="doc-{{seq:001}}",
        records=[{"계약명": "새값"}],
        source_schema_keys=("계약명",),
        output_directory=str(tmp_path / "out"),
        overwrite=False,
        clock=datetime.now,
    )
    assert isinstance(result, HeadlessRefused) and result.stage == TEMPLATE_INITIALIZATION
    assert not (tmp_path / "out").exists()


# ------------------------------------------------------- 줄배치 캐시(#95)
def test_filling_strips_stale_lineseg_from_modified_sections(tmp_path):
    """#95 실코퍼스 회귀 — 캐시를 무겁게 지닌 실제 공고서 템플릿을 채우면 변경된 XML 의
    stale 줄배치 캐시가 전량 제거되고, 미변경 XML 은 바이트 그대로다(legacy 엔진에서 이어받음)."""
    fields = make_hwpx_engine().required_fields(str(CORPUS_NOTICE))
    assert fields  # 템플릿에 누름틀 실재(양성 대조 1)
    done = _completed(_run(tmp_path, CORPUS_NOTICE, [{f: "값" for f in fields}]))

    src = read_hwpx_package(CORPUS_NOTICE)
    dst = read_hwpx_package(done.delivered[0].absolute_path)
    changed = [n for n in dst.content_xml_names() if dst.entries[n] != src.entries[n]]
    assert changed  # 채움이 실제로 일어났다
    # 변경 전 XML 에 stale 후보 캐시가 실재했다(양성 대조 2 — 스트립 무의미 방지)
    assert sum(src.entries[n].count(b"linesegarray") for n in changed) > 0
    for name in changed:
        assert dst.entries[name].count(b"linesegarray") == 0


# ------------------------------------------------------- 채움 완화 노트(#154)
def test_empty_field_is_filled_and_the_synthesized_slot_is_noted(tmp_path):
    """빈 누름틀 채움 — 값이 들어가고 그 완화는 노트로 올라온다(#154)."""
    tpl = _template(tmp_path, _field("계약명"))
    done = _completed(_run(tmp_path, tpl, [{"계약명": "새값"}]))
    (doc,) = done.delivered
    assert doc.execution_notes == (FillNote("계약명", "slot_synthesized"),)
    assert read_fields(read_hwpx_package(doc.absolute_path))["계약명"] == "새값"


def test_inline_elements_stripped_by_the_fill_are_named(tmp_path):
    tpl = _template(
        tmp_path,
        _field("계약명", "<hp:run><hp:t>OLD<hp:markpenBegin/>X<hp:markpenEnd/></hp:t></hp:run>"),
    )
    done = _completed(_run(tmp_path, tpl, [{"계약명": "NEW"}]))
    (doc,) = done.delivered
    assert [(n.field, n.kind, n.detail) for n in doc.execution_notes] == [
        ("계약명", "inline_stripped", ("markpenBegin", "markpenEnd"))
    ]
    assert read_fields(read_hwpx_package(doc.absolute_path))["계약명"] == "NEW"


def test_pending_binding_decisions_are_named_in_the_refusal(tmp_path):
    """활성 Field 에 매핑 결정이 없으면(NEW_ACTIVE_FIELD) 그 필드 이름을 사유에 더한다."""
    tpl = _template(tmp_path, _field("계약명"))
    result = run_headless_generation(
        workspace=tmp_path / "ws",
        template_path=str(tpl),
        mapping=MappingProfile(mappings=[]),  # 활성 Field 「계약명」에 결정이 없다
        filename_pattern="doc-{{seq:001}}",
        records=[{"계약명": "값"}],
        source_schema_keys=("계약명",),
        output_directory=str(tmp_path / "out"),
        overwrite=False,
        clock=datetime.now,
    )
    assert isinstance(result, HeadlessRefused)
    assert result.stage == EXECUTION_NOT_SEALABLE
    assert any("계약명" in detail for detail in result.details)
    assert not (tmp_path / "out").exists()


def test_seal_blocked_for_other_reasons_names_no_pending_field_when_mapping_is_complete(
    tmp_path, monkeypatch
):
    """매핑이 활성 Field 를 전부 덮으면(결정 미비 없음) 사유에 필드 이름을 더하지 않는다 —
    다른 사유(정책·구성)로 막힌 경우의 음성 대조.
    """
    import dataclasses

    from hwpxfiller.application.fresh_execution_observation import (
        CurrentWorkExecutionObservation,
    )
    from hwpxfiller.external.seal_execution_plan_service import SealExecutionPlanService

    tpl = _template(tmp_path, _field("계약명", "<hp:run><hp:t>구값</hp:t></hp:run>"))
    original = SealExecutionPlanService.seal_execution_plan

    def patched(self, work_ref, request_id):
        resp = original(self, work_ref, request_id)
        return dataclasses.replace(
            resp,
            fresh_observation=CurrentWorkExecutionObservation(
                work_authority_ref="w",
                current_sealability="POLICY_BLOCKED",
                observed_at="now",
                normalized_blockers_or_policy=("SOME_POLICY_CODE",),
            ),
        )

    monkeypatch.setattr(SealExecutionPlanService, "seal_execution_plan", patched)
    result = _run(tmp_path, tpl, [{"계약명": "새값"}])
    assert isinstance(result, HeadlessRefused)
    assert result.stage == EXECUTION_NOT_SEALABLE
    assert result.details == ("SOME_POLICY_CODE",)  # 필드 이름 안내가 더해지지 않았다
    assert not (tmp_path / "out").exists()


def test_a_record_the_capture_cannot_read_is_refused_before_any_write(tmp_path):
    """record 값이 str/None 이 아니면 capture 단계에서 write 0 로 거절한다."""
    tpl = _template(tmp_path, _field("계약명", "<hp:run><hp:t>구값</hp:t></hp:run>"))
    result = _run(tmp_path, tpl, [{"계약명": 123}])
    assert isinstance(result, HeadlessRefused)
    assert result.stage == RECORD_VALIDATION
    assert result.details
    assert not (tmp_path / "out").exists()


def test_sealed_payload_of_the_wrong_type_is_refused(tmp_path, monkeypatch):
    """방어적 갈래 — seal 이 성공을 보고했는데 payload 가 계약 타입이 아니면 조용히 진행하지
    않는다. 정상 흐름에서는 나지 않는 상태라 seal seam 하나만 주입해 직접 잰다."""
    import dataclasses

    from hwpxfiller.application.execution_contract_set import (
        SealedExecutionPlanSemanticPayload,
    )
    from hwpxfiller.external.seal_execution_plan_product import (
        ExecutionPlanSealedProductOutcome,
    )
    from hwpxfiller.external.seal_execution_plan_service import SealExecutionPlanService

    tpl = _template(tmp_path, _field("계약명", "<hp:run><hp:t>구값</hp:t></hp:run>"))
    original = SealExecutionPlanService.seal_execution_plan

    def patched(self, work_ref, request_id):
        resp = original(self, work_ref, request_id)
        outcome = resp.command_outcome
        assert isinstance(outcome, ExecutionPlanSealedProductOutcome), outcome
        assert isinstance(outcome.plan_payload, SealedExecutionPlanSemanticPayload)
        return dataclasses.replace(
            resp,
            command_outcome=dataclasses.replace(outcome, plan_payload="not-a-payload"),
        )

    monkeypatch.setattr(SealExecutionPlanService, "seal_execution_plan", patched)
    result = _run(tmp_path, tpl, [{"계약명": "새값"}])
    assert isinstance(result, HeadlessRefused)
    assert result.stage == EXECUTION_NOT_SEALABLE
    assert result.code == "SEALED_PLAN_PAYLOAD_MISSING"
    assert not (tmp_path / "out").exists()


def test_missing_current_field_binding_is_refused_before_delivery(tmp_path, monkeypatch):
    """방어적 갈래 — sealed 관찰에 current Field Binding 이 실리지 않으면 배달을 계획하지 않는다."""
    import dataclasses

    from hwpxfiller.application.fresh_execution_observation import (
        CurrentSealedPlanObservation,
    )
    from hwpxfiller.external.seal_execution_plan_service import SealExecutionPlanService

    tpl = _template(tmp_path, _field("계약명", "<hp:run><hp:t>구값</hp:t></hp:run>"))
    original = SealExecutionPlanService.seal_execution_plan

    def patched(self, work_ref, request_id):
        resp = original(self, work_ref, request_id)
        fresh = resp.fresh_observation
        assert isinstance(fresh, CurrentSealedPlanObservation), fresh
        return dataclasses.replace(
            resp, fresh_observation=dataclasses.replace(fresh, current_field_binding=None)
        )

    monkeypatch.setattr(SealExecutionPlanService, "seal_execution_plan", patched)
    result = _run(tmp_path, tpl, [{"계약명": "새값"}])
    assert isinstance(result, HeadlessRefused)
    assert result.stage == "DELIVERY_PLAN"
    assert result.code == "CURRENT_DELIVERY_BINDING_CONTEXT_MISSING"
    assert not (tmp_path / "out").exists()


def test_unavailable_managed_run_context_is_refused_after_delivery_is_planned(
    tmp_path, monkeypatch
):
    """방어적 갈래 — managed run context 를 못 얻으면(권위 미확정) 실행을 시작하지 않는다."""
    from hwpxfiller.external.seal_execution_plan_service import SealExecutionPlanService

    tpl = _template(tmp_path, _field("계약명", "<hp:run><hp:t>구값</hp:t></hp:run>"))
    monkeypatch.setattr(
        SealExecutionPlanService, "managed_run_context", lambda self, *a, **k: None
    )
    result = _run(tmp_path, tpl, [{"계약명": "새값"}])
    assert isinstance(result, HeadlessRefused)
    assert result.stage == EXECUTION_NOT_SEALABLE
    assert result.code == "MANAGED_RUN_CONTEXT_UNAVAILABLE"
    assert not (tmp_path / "out").exists()


def test_record_preparation_context_error_is_restated_not_swallowed(tmp_path, monkeypatch):
    """방어적 갈래 — record 준비가 context/무결성 실패를 내면 그 code·detail 을 그대로 올린다."""
    import hwpxfiller.external.headless_generation as hg
    from hwpxfiller.application.document_creation_workbench import (
        WorkbenchContextIntegrity,
    )

    tpl = _template(tmp_path, _field("계약명", "<hp:run><hp:t>구값</hp:t></hp:run>"))
    monkeypatch.setattr(
        hg,
        "prepare_current_records",
        lambda **kw: WorkbenchContextIntegrity(
            restore_failure=True, code="RAW_RECORD_INTEGRITY_ERROR", detail="손상됨"
        ),
    )
    result = _run(tmp_path, tpl, [{"계약명": "새값"}])
    assert isinstance(result, HeadlessRefused)
    assert result.stage == RECORD_VALIDATION
    assert result.code == "RAW_RECORD_INTEGRITY_ERROR"
    assert result.details == ("손상됨",)
    assert not (tmp_path / "out").exists()


def test_a_degenerate_occurrence_in_another_section_is_refused_not_left_blank(tmp_path):
    """다른 섹션의 기입 불가 자리(fieldBegin·fieldEnd 가 한 ctrl 에 붙은 빈 자리).

    종전 legacy 엔진은 한 섹션을 채우고 그 자리를 ``occurrence_unfillable`` 노트로 남겼다
    (2라운드 F1 — 노트가 유일 신호). managed 는 한 단계 앞에서 닫는다: 초기 등록(자격 심사)이
    그 템플릿을 받지 않아 빈 자리가 남은 문서 자체가 나오지 않는다.
    """
    degenerate = (
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="계약명"/><hp:fieldEnd/></hp:ctrl>'
        "</hp:run></hp:p>"
    )
    tpl = _template(
        tmp_path, _field("계약명", "<hp:run><hp:t>구값</hp:t></hp:run>"), degenerate
    )
    result = _run(tmp_path, tpl, [{"계약명": "새값"}])
    assert isinstance(result, HeadlessRefused) and result.stage == TEMPLATE_INITIALIZATION
    assert not (tmp_path / "out").exists()
