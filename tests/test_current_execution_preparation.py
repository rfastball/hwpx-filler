"""``hwpxfiller.external.current_execution_preparation`` — 낮은 층위 branch 실측.

이 모듈은 job/webapp 통합 경로(다른 test 파일들)가 대부분 커버하지만, 방어적 raise·loop
탈출·경계 값 갈래는 통합 경로가 거의 밟지 않는다. 여기는 그 갈래만 직접, 최소 구성으로 잰다
— exact 상위 계약(``SealedExecutionPlanValue`` 전체)이 필요 없는 함수는 duck-typed
``SimpleNamespace`` 로, 실제 검증 파이프라인을 타야 하는 함수는 ``tests.test_record_validation``
의 실 Plan builder 를 재사용한다.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from hwpxfiller.application.document_creation_workbench import WorkbenchContextIntegrity
from hwpxfiller.application.record_validation import RAW_RECORD_INTEGRITY_ERROR
from hwpxfiller.application.run_delivery_intent import RunDeliveryIntent
from hwpxfiller.domain.raw_data_record import SourceNull, SourceText
from hwpxfiller.external.current_execution_preparation import (
    CurrentRecordCaptureError,
    CurrentRecordPreparation,
    capture_selected_records,
    capture_source_value,
    observe_path_occupancy,
    prepare_current_records,
    record_issue,
    record_source_key,
)

from tests.test_record_validation import _current_plan, _snapshot


# ══ record_source_key ══════════════════════════════════════════════════════════════════
def test_record_source_key_raises_when_no_requirement_matches():
    plan = SimpleNamespace(active_field_requirements=())
    with pytest.raises(CurrentRecordCaptureError):
        record_source_key(plan, "계약명")


def test_record_source_key_skips_non_matching_requirements_then_returns():
    plan = SimpleNamespace(
        active_field_requirements=(
            {"field_id": "다른항목", "value_expression": {"source_key": "무관"}},
            {"field_id": "계약명", "value_expression": {"source_key": "이름열"}},
        )
    )
    assert record_source_key(plan, "계약명") == "이름열"


def test_record_source_key_raises_when_matching_requirements_lack_a_usable_source_key():
    plan = SimpleNamespace(
        active_field_requirements=(
            {"field_id": "계약명", "value_expression": "not-a-mapping"},  # not a Mapping
            {"field_id": "계약명", "value_expression": {"source_key": ""}},  # falsy
            {"field_id": "계약명", "value_expression": {"source_key": 5}},  # not a str
        )
    )
    with pytest.raises(CurrentRecordCaptureError):
        record_source_key(plan, "계약명")


# ══ record_issue ═══════════════════════════════════════════════════════════════════════
def _blocker(**over):
    from hwpxfiller.application.record_validation import RecordValidationBlocker

    kw = dict(code="RECORD_REQUIRED_VALUE_MISSING", field_id="계약명", detail="")
    kw.update(over)
    return RecordValidationBlocker(**kw)


def test_record_issue_raises_when_blocker_field_id_is_not_a_string():
    plan = SimpleNamespace(active_field_requirements=())
    with pytest.raises(CurrentRecordCaptureError):
        record_issue(
            plan=plan,
            blocker=_blocker(field_id=None),
            generation=0,
            model_index=0,
            record_identity="rec-0",
            columns=[],
        )


def test_record_issue_raises_when_blocker_code_is_unknown():
    plan = SimpleNamespace(active_field_requirements=())
    with pytest.raises(CurrentRecordCaptureError):
        record_issue(
            plan=plan,
            blocker=_blocker(code="어떤_미지_코드"),
            generation=0,
            model_index=0,
            record_identity="rec-0",
            columns=[],
        )


# ══ capture_source_value ═══════════════════════════════════════════════════════════════
def test_capture_source_value_none_becomes_source_null():
    assert capture_source_value(None) == SourceNull()


def test_capture_source_value_str_becomes_source_text():
    assert capture_source_value("값") == SourceText("값")


def test_capture_source_value_raises_for_unsupported_types():
    with pytest.raises(CurrentRecordCaptureError):
        capture_source_value(123)


# ══ capture_selected_records ═══════════════════════════════════════════════════════════
def test_capture_selected_records_raises_for_out_of_range_index():
    with pytest.raises(CurrentRecordCaptureError):
        capture_selected_records(
            snapshot_generation=0,
            ordered_model_indices=(5,),
            rows=[{"이름": "가"}],
            source_schema_keys=("이름",),
            captured_at="2026-01-01T00:00:00+09:00",
        )


def test_capture_selected_records_raises_for_non_string_key():
    with pytest.raises(CurrentRecordCaptureError):
        capture_selected_records(
            snapshot_generation=0,
            ordered_model_indices=(0,),
            rows=[{1: "가"}],
            source_schema_keys=("1",),
            captured_at="2026-01-01T00:00:00+09:00",
        )


def test_capture_selected_records_raises_for_non_str_non_none_value():
    with pytest.raises(CurrentRecordCaptureError):
        capture_selected_records(
            snapshot_generation=0,
            ordered_model_indices=(0,),
            rows=[{"이름": 123}],
            source_schema_keys=("이름",),
            captured_at="2026-01-01T00:00:00+09:00",
        )


def test_capture_selected_records_accepts_none_and_str_values():
    captured = capture_selected_records(
        snapshot_generation=0,
        ordered_model_indices=(0,),
        rows=[{"이름": "가", "금액": None}],
        source_schema_keys=("이름", "금액"),
        captured_at="2026-01-01T00:00:00+09:00",
    )
    assert len(captured) == 1


# ══ prepare_current_records — context error 갈래 ═══════════════════════════════════════
def test_prepare_current_records_returns_context_integrity_on_tampered_snapshot():
    plan = _current_plan()
    snap = _snapshot()
    diverged = dataclasses.replace(
        snap, _values={**dict(snap._values), "name": SourceText("TAMPERED")}
    )
    result = prepare_current_records(
        snapshot_generation=0,
        work_ref="work",
        ordered_model_indices=(0,),
        plan=plan,
        raw_records=(diverged,),
        project_issue=lambda blocker, model_index, record_identity: (_ for _ in ()).throw(
            AssertionError("project_issue must not be called on a context error")
        ),
    )
    assert isinstance(result, WorkbenchContextIntegrity)
    assert result.restore_failure is True
    assert result.code == RAW_RECORD_INTEGRITY_ERROR


def test_prepare_current_records_succeeds_for_a_clean_snapshot():
    plan = _current_plan()
    snap = _snapshot()
    result = prepare_current_records(
        snapshot_generation=0,
        work_ref="work",
        ordered_model_indices=(0,),
        plan=plan,
        raw_records=(snap,),
        project_issue=lambda blocker, model_index, record_identity: (_ for _ in ()).throw(
            AssertionError("no blocking issue expected")
        ),
    )
    assert isinstance(result, CurrentRecordPreparation)
    assert result.record_validation.has_blocking_issues is False


# ══ observe_path_occupancy ═════════════════════════════════════════════════════════════
def test_observe_path_occupancy_rejects_a_relative_output_directory():
    intent = RunDeliveryIntent(output_directory="relative/out")
    with pytest.raises(ValueError):
        observe_path_occupancy(intent, "2026-01-01T00:00:00+09:00")
