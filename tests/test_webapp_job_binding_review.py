"""SX-03(#726) — 「문서 만들기」 패널에 배선된 execution admission·readiness 헤드리스 가드 (post-R2 #740).

seal 판정·admission 파생은 SealExecutionPlanService·SealExecutionPlanProduct 테스트가 소유한다.
여기가 잰다: JobController 가 `self._seal_execution`(SX-SEAL) 을 소비해 (1) 확인 증거 없이
NO_EVIDENCE 로 서고, (2) `resolve_execution` 이 실 seal 을 돌려 binding 있는 Work 는
CURRENT+NOT_ADMITTED+NOT_READY 로, binding 없는 Work 는 정직한 blocked 로 관찰되며, (3) 어느 경우도
Primary Action 이 CREATE_DOCUMENTS 로 조용히 새지 않고, (4) snapshot 존이 그 관계를 그대로 나른다는 것.

R2(#740): currentness 축이 orchestration 으로 흡수됐다 — CURRENT/STALE 은 orchestration 상태가
나르고, opaque Plan ref·resolve_plan_reference·Profile admission store 는 사라졌다. seal 은 durable
side effect 없는 순수 재계산이라 마지막 sealed basis 는 digest 로만 잡힌다(_last_sealed_basis_digest).

**하드코딩 0**: admission/readiness/7상태는 전부 seal 서비스 fresh_observation 소비다.
"""
from __future__ import annotations

import dataclasses
import threading
from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.application.jobs import Job
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths
from hwpxfiller.host.locations import default_template_authority_dir
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp import screen_job as screen_job_module
from hwpxfiller.webapp.seal_execution_plan_service import SealExecutionPlanService
from hwpxfiller.application.fresh_execution_observation import (
    CurrentSealedPlanObservation,
    CurrentWorkExecutionObservation,
    ExecutionObservationContextError,
)
from hwpxfiller.application.execution_compilation import FromSource, encode_value_expression
from hwpxfiller.application.field_binding_input import build_field_binding_input
from hwpxfiller.application.run_delivery_intent import RunDeliveryIntent
from hwpxfiller.application.preview_requirement import PreviewNotRequired, PreviewRequired
from hwpxfiller.domain.field_binding import (
    DATE,
    DECIMAL,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    EXACT_TEXT,
    SOURCE,
    FieldBindingRule,
)
from hwpxfiller.domain.raw_data_record import source_value_type_of
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct
from hwpxfiller.application.slot_configuration_projection import (
    HAS_BROKEN_SELECTIONS,
    NEEDS_SELECTION,
    SLOT_SELECTIONS_COMPLETE,
)
from hwpxfiller.webapp.workbench_observation_product import (
    WorkbenchObservationProduct,
    content_selection_from_view,
    execution_verdicts_from_fresh,
)

from tests.test_execution_compilation import WORK
from tests.test_seal_execution_capture_runner import _seed_v2_work

WORK_REF = "봉인작업"
NOW = datetime(2026, 8, 18, 9, 0, 0)


def _clock():
    return lambda: NOW


def _controller(tmp_path: Path, *, with_binding: bool, wire_seal: bool = True):
    """실 SlotConfigurationProduct + SealExecutionPlanService 를 **같은 authority root** 로 배선.

    v2 Work 를 그 root 에 직접 seed 하고 registry 의 WorkAuthorityId 를 그 Work 에 못박아, 컨트롤러의
    job_name → seal 서비스 route 가 seed 한 Work 에 닿게 한다(test_seal_execution_plan_service 패턴).
    R2(#740): admission store seed 는 필요 없다 — runtime admission 은 materializer conformance
    capability(S6 미출하 → NOT_ADMITTED)만 본다.
    """
    root = default_template_authority_dir()
    _seed_v2_work(root, with_binding=with_binding)
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name=WORK_REF, template_path="managed.hwpx"))
    reg.assign_authority_id(WORK_REF, WORK)
    kwargs = dict(
        clock=_clock(),
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
        slot_configuration=SlotConfigurationProduct(reg, root=root, clock=_clock()),
        workbench_observation=WorkbenchObservationProduct(),
    )
    if wire_seal:
        kwargs["seal_execution"] = SealExecutionPlanService(reg, root=root, clock=datetime.now)
    ctrl = JobController(reg, lambda s, snap: None, **kwargs)
    ctrl.job_name = WORK_REF
    return ctrl


def _zone(ctrl) -> dict:
    return ctrl._workbench_observation_zone(tmissing=False)


# ── 확인 증거 없음 → NO_EVIDENCE(정직한 disabled) ─────────────────────────────────────────────
def _wire_source_plan(ctrl: JobController) -> None:
    ctrl.dispatch("resolve_execution", {})
    fresh = ctrl._last_fresh_observation
    assert isinstance(fresh, CurrentSealedPlanObservation)
    requirement = {
        "field_id": "f_name",
        "expected_active_occurrence_count": 1,
        "value_expression": encode_value_expression(
            FromSource("name", EXACT_TEXT, None, "document-content-value/v1")
        ),
    }
    plan = dataclasses.replace(
        fresh.sealed_plan_value,
        active_field_requirements=(requirement,),
    )
    ctrl._last_fresh_observation = dataclasses.replace(fresh, sealed_plan_value=plan)


def _mount_rows(ctrl: JobController, rows: list[dict]) -> None:
    ctrl.datasource = object()
    ctrl.records = rows
    ctrl.selection = SelectionModel(len(rows))
    ctrl._install_filter(rows, {})


def test_no_evidence_before_any_check(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    zone = _zone(ctrl)
    assert zone["supported"] is True and zone["kind"] == "observation"
    assert zone["execution_status_code"] == "NO_EVIDENCE"
    assert zone["execution_status_phrase"] == "현재 설정을 확인해야 합니다"
    # 아직 확인 전이라 READY 를 주장하지 않는다(materialization NOT_READY).
    assert zone["materialization_readiness"] == "NOT_READY"
    assert zone["primary_action"] != "CREATE_DOCUMENTS"


def test_selected_record_capture_preserves_order_and_never_rereads_source(
    tmp_path: Path,
) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    _wire_source_plan(ctrl)
    fresh = ctrl._last_fresh_observation
    assert isinstance(fresh, CurrentSealedPlanObservation)
    rows = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    _mount_rows(ctrl, rows)
    ctrl.view_order = "sourceDesc"

    class NoReadSource:
        def __getattribute__(self, name):
            raise AssertionError(f"mutable source reread: {name}")

    ctrl.datasource = NoReadSource()
    generation, indices, snapshots = ctrl._capture_current_selected_records(
        fresh.sealed_plan_value
    )
    assert generation == ctrl._snapshot_gen
    assert indices == (2, 1, 0)
    assert [snapshot.value_for("name").text for snapshot in snapshots] == ["C", "B", "A"]
    rows[2]["name"] = "changed after capture"
    assert snapshots[0].value_for("name").text == "C"


def test_generation_move_rejects_mixed_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    _wire_source_plan(ctrl)
    fresh = ctrl._last_fresh_observation
    assert isinstance(fresh, CurrentSealedPlanObservation)
    _mount_rows(ctrl, [{"name": "A"}, {"name": "B"}])
    original = screen_job_module.build_raw_record_snapshot
    calls = 0

    def moving_capture(**kwargs):
        nonlocal calls
        calls += 1
        result = original(**kwargs)
        if calls == 1:
            ctrl._snapshot_gen += 1
        return result

    monkeypatch.setattr(screen_job_module, "build_raw_record_snapshot", moving_capture)
    with pytest.raises(ValueError, match="다시 불러와져"):
        ctrl._capture_current_selected_records(fresh.sealed_plan_value)
    assert ctrl._current_record_preparation is None


def test_capture_uses_current_declared_date_and_decimal_types(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    _wire_source_plan(ctrl)
    fresh = ctrl._last_fresh_observation
    assert isinstance(fresh, CurrentSealedPlanObservation)
    requirements = tuple(
        {
            'field_id': field_id,
            'expected_active_occurrence_count': 1,
            'value_expression': encode_value_expression(
                FromSource(source_key, value_type, None, 'document-content-value/v1')
            ),
        }
        for field_id, source_key, value_type in (
            ('f_amount', 'amount', DECIMAL),
            ('f_date', 'date', DATE),
        )
    )
    plan = dataclasses.replace(
        fresh.sealed_plan_value, active_field_requirements=requirements
    )
    ctrl._last_fresh_observation = dataclasses.replace(
        fresh, sealed_plan_value=plan
    )
    _mount_rows(ctrl, [{'amount': '1500.00', 'date': '2026-08-19'}])

    _, _, snapshots = ctrl._capture_current_selected_records(plan)
    amount = snapshots[0].value_for('amount')
    date = snapshots[0].value_for('date')
    assert amount is not None and source_value_type_of(amount) == DECIMAL
    assert date is not None and source_value_type_of(date) == DATE
    assert _zone(ctrl)['record_validation']['validated_count'] == 1


def test_shared_source_column_is_interpreted_per_current_requirement(
    tmp_path: Path,
) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    _wire_source_plan(ctrl)
    fresh = ctrl._last_fresh_observation
    assert isinstance(fresh, CurrentSealedPlanObservation)
    requirements = tuple(
        {
            'field_id': field_id,
            'expected_active_occurrence_count': 1,
            'value_expression': encode_value_expression(
                FromSource('value', value_type, None, 'document-content-value/v1')
            ),
        }
        for field_id, value_type in (
            ('f_text', EXACT_TEXT),
            ('f_decimal', DECIMAL),
        )
    )
    plan = dataclasses.replace(
        fresh.sealed_plan_value, active_field_requirements=requirements
    )
    ctrl._last_fresh_observation = dataclasses.replace(
        fresh, sealed_plan_value=plan
    )
    _mount_rows(ctrl, [{'value': '1'}])

    zone = _zone(ctrl)
    assert zone['record_validation']['validated_count'] == 1
    preparation = ctrl._current_record_preparation
    assert preparation is not None
    assert preparation.validated_records[0].document_values_in_order() == (
        ('f_text', '1'),
        ('f_decimal', '1'),
    )


def test_current_record_blocker_projects_exact_backend_target(
    tmp_path: Path,
) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    _wire_source_plan(ctrl)
    _mount_rows(ctrl, [{"name": "정상"}, {"name": " "}])

    zone = _zone(ctrl)
    validation = zone["record_validation"]
    assert validation["validated_count"] == 1
    assert validation["blocked_count"] == 1
    assert zone["primary_action"] == "REVIEW_RECORD_DATA"
    issue = validation["issues"][0]
    assert issue["record_display_locator"] == "데이터 2행"
    assert issue["field_id"] == "f_name"
    assert issue["field_display_label"] == "name"
    assert issue["message"] == "빈 값이나 공백만 있는 값은 사용할 수 없습니다."
    target = issue["recovery_target"]
    assert target == {
        'target_kind': 'cell',
        "snapshot_generation": ctrl._snapshot_gen,
        "record_identity": ctrl._current_record_identity(ctrl._snapshot_gen, 1),
        "model_index": 1,
        "field_id": "name",
    }
    assert ctrl.dispatch("recover_record_issue", {"target": target}) == {
        "ok": True,
        "element_id": "jobCell-1-0",
        "fallback_element_id": "jobRow-1",
    }
    ctrl._snapshot_gen += 1
    with pytest.raises(ValueError, match="위치를 복원할 수 없습니다"):
        ctrl.dispatch("recover_record_issue", {"target": target})


def test_missing_source_column_projects_reachable_row_target(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    _wire_source_plan(ctrl)
    _mount_rows(ctrl, [{'other': '값'}])

    issue = _zone(ctrl)['record_validation']['issues'][0]
    target = issue['recovery_target']
    assert target['field_id'] == 'name'
    assert target['target_kind'] == 'row'
    assert ctrl.dispatch('recover_record_issue', {'target': target}) == {
        'ok': True,
        'element_id': 'jobRow-0',
        'fallback_element_id': 'jobRow-0',
    }


def test_stale_orchestration_hides_old_record_validation_and_target(
    tmp_path: Path,
) -> None:
    from hwpxfiller.application.automatic_seal_orchestration import (
        AutomaticSealOrchestration,
    )

    ctrl = _controller(tmp_path, with_binding=True)
    _wire_source_plan(ctrl)
    _mount_rows(ctrl, [{'name': ' '}])
    target = _zone(ctrl)['record_validation']['issues'][0]['recovery_target']

    ctrl._session_orchestration = AutomaticSealOrchestration(state='STALE')
    assert _zone(ctrl)['record_validation']['issue_count'] == 0
    with pytest.raises(ValueError, match='위치를 복원할 수 없습니다'):
        ctrl.dispatch('recover_record_issue', {'target': target})


def test_current_preparation_is_reused_until_existing_basis_moves(
    tmp_path: Path,
) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    _wire_source_plan(ctrl)
    rows = [{"name": "정상"}, {"name": " "}]
    _mount_rows(ctrl, rows)
    assert _zone(ctrl)["record_validation"]["blocked_count"] == 1
    first = ctrl._current_record_preparation
    rows[1]["name"] = "원본에서 수정됨"
    assert _zone(ctrl)["record_validation"]["blocked_count"] == 1
    assert ctrl._current_record_preparation is first

    fresh = ctrl._last_fresh_observation
    assert isinstance(fresh, CurrentSealedPlanObservation)
    moved = dataclasses.replace(fresh.sealed_plan_value, qualification_profile_id="profile-moved")
    ctrl._last_fresh_observation = dataclasses.replace(fresh, sealed_plan_value=moved)
    assert _zone(ctrl)["record_validation"]["validated_count"] == 2
    assert ctrl._current_record_preparation is not first


def _delivery_controller(tmp_path: Path) -> tuple[JobController, Path]:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("select_job", {"name": WORK_REF})
    _wire_source_plan(ctrl)
    rows = [{"name": "A"}, {"name": "B"}]
    _mount_rows(ctrl, rows)

    class Source:
        def records(self) -> list[dict]:
            return rows

    ctrl.datasource = Source()
    assert ctrl.vm is not None
    ctrl.vm.set_acquired(ctrl.datasource, rows)
    out = tmp_path / "delivery"
    out.mkdir()
    return ctrl, out


def test_managed_delivery_projects_session_intent_and_exact_backend_paths(
    tmp_path: Path,
) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    legacy_out = ctrl.out_dir

    ctrl.set_output_folder(str(out))

    zone = _zone(ctrl)
    assert ctrl.out_dir == legacy_out
    assert zone["run_delivery_intent"] == {
        "output_directory": str(out),
        "collision_policy": "ADD_SUFFIX",
    }
    assert zone["delivery"] == {
        "resolvable": True,
        "planned_documents": [
            {
                "record_identity": ctrl._current_record_identity(ctrl._snapshot_gen, 1),
                "item_ordinal": 0,
                "relative_path": "공고서-20260818-001.hwpx",
                "collision_disposition": "WRITE_NEW",
            },
            {
                "record_identity": ctrl._current_record_identity(ctrl._snapshot_gen, 0),
                "item_ordinal": 1,
                "relative_path": "공고서-20260818-002.hwpx",
                "collision_disposition": "WRITE_NEW",
            },
        ],
        "blockers": [],
    }
    assert zone["create_action"]["enabled"] is False  # S6 absent 보존


def test_optional_preview_token_is_stable_across_passive_render_and_drawer(
    tmp_path: Path,
) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    ctrl.set_output_folder(str(out))
    _zone(ctrl)

    first = ctrl._current_preview_preparation
    assert first is not None
    assert first.requirement.kind == "OPTIONAL"
    assert "REVIEW_PREVIEW" not in _zone(ctrl)["blockers"]
    assert ctrl._current_preview_preparation is first

    ctrl.dispatch("preview_open", {})
    assert ctrl._current_preview_preparation is first
    ctrl.dispatch("preview_close", {})
    assert ctrl._current_preview_preparation is first
    assert ctrl._approved_preview_token is None


def test_required_preview_approval_is_current_token_only_and_legacy_review_isolated(
    tmp_path: Path,
) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    (out / "공고서-20260818-001.hwpx").write_bytes(b"occupied")
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("set_delivery_collision", {"collision_policy": "OVERWRITE_EXPLICIT"})
    _zone(ctrl)

    current = ctrl._current_preview_preparation
    assert current is not None and isinstance(current.requirement, PreviewRequired)
    before = _zone(ctrl)
    assert before["primary_action"] == "REVIEW_PREVIEW"
    assert before["preview_requirement"] == {
        "kind": "REQUIRED",
        "reason": "DESTRUCTIVE_OVERWRITE",
    }
    assert before["preview_satisfied"] is False
    assert before["semantic_preview"] == {
        "preview_token": current.preview_token,
        "requirement": {"kind": "REQUIRED", "reason": "DESTRUCTIVE_OVERWRITE"},
        "included_content_summary": "데이터 2건 · 항목 1개",
        "ordered_records": [
            {
                "record_identity": ctrl._current_record_identity(ctrl._snapshot_gen, 1),
                "record_display_locator": "데이터 2행",
                "logical_field_values": [
                    {"field_id": "f_name", "display_label": "f_name", "value": "B"}
                ],
                "planned_document_relative_path": "공고서-20260818-001.hwpx",
                "collision_disposition": "WRITE_OVERWRITE",
            },
            {
                "record_identity": ctrl._current_record_identity(ctrl._snapshot_gen, 0),
                "record_display_locator": "데이터 1행",
                "logical_field_values": [
                    {"field_id": "f_name", "display_label": "f_name", "value": "A"}
                ],
                "planned_document_relative_path": "공고서-20260818-002.hwpx",
                "collision_disposition": "WRITE_NEW",
            },
        ],
    }
    ctrl.dispatch("preview_open", {})
    legacy_approvals = set(ctrl.review.approved)
    ctrl.dispatch("preview_approve", {"preview_token": current.preview_token})

    zone = _zone(ctrl)
    assert "REVIEW_PREVIEW" not in zone["blockers"]
    assert zone["preview_satisfied"] is True
    assert ctrl._approved_preview_token == current.preview_token
    assert ctrl.review.approved == legacy_approvals


def test_delivery_refresh_replaces_token_and_stale_approval_writes_nothing(
    tmp_path: Path,
) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    (out / "공고서-20260818-001.hwpx").write_bytes(b"occupied")
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("set_delivery_collision", {"collision_policy": "OVERWRITE_EXPLICIT"})
    ctrl.dispatch("preview_open", {})
    old = ctrl._current_preview_preparation
    assert old is not None

    ctrl.dispatch("refresh_delivery", {})
    _zone(ctrl)
    current = ctrl._current_preview_preparation
    assert current is not None
    assert current.preview_token != old.preview_token
    assert ctrl._approved_preview_token is None
    with pytest.raises(ValueError, match="바뀌었습니다"):
        ctrl.dispatch("preview_approve", {"preview_token": old.preview_token})
    assert ctrl._approved_preview_token is None
    assert not ctrl.review.approved


def test_record_preparation_identity_change_replaces_preview_token(tmp_path: Path) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    ctrl.set_output_folder(str(out))
    _zone(ctrl)
    first = ctrl._current_preview_preparation
    assert first is not None

    ctrl.selection.toggle(0, False)
    _zone(ctrl)
    current = ctrl._current_preview_preparation
    assert current is not None
    assert current.record_preparation is not first.record_preparation
    assert current.preview_token != first.preview_token


def test_non_regular_collision_keeps_delivery_ahead_of_preview(tmp_path: Path) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    (out / "공고서-20260818-001.hwpx").mkdir()
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("set_delivery_collision", {"collision_policy": "OVERWRITE_EXPLICIT"})

    zone = _zone(ctrl)
    assert zone["primary_action"] == "REVIEW_DELIVERY"
    assert "REVIEW_PREVIEW" not in zone["blockers"]
    assert ctrl._current_preview_preparation is None
    obs = ctrl.workbench_observation()
    assert obs.preview_requirement.kind == "NOT_REQUIRED"
    assert obs.semantic_preview is None


def test_delivery_intent_changes_reuse_record_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, first_out = _delivery_controller(tmp_path)
    second_out = tmp_path / "delivery-2"
    second_out.mkdir()
    ctrl.set_output_folder(str(first_out))
    _zone(ctrl)
    record_preparation = ctrl._current_record_preparation
    assert record_preparation is not None

    monkeypatch.setattr(
        screen_job_module,
        "validate_data_records_against_current_value",
        lambda **_kwargs: pytest.fail("delivery change reran record validation"),
    )
    ctrl.set_output_folder(str(second_out))
    _zone(ctrl)
    assert ctrl._current_record_preparation is record_preparation
    ctrl.dispatch("set_delivery_collision", {"collision_policy": "FAIL"})
    _zone(ctrl)
    assert ctrl._current_record_preparation is record_preparation


def test_delivery_clock_is_pinned_until_delivery_invalidation(tmp_path: Path) -> None:
    ctrl, first_out = _delivery_controller(tmp_path)
    second_out = tmp_path / "delivery-2"
    second_out.mkdir()
    ctrl.set_output_folder(str(first_out))
    calls = 0

    def counting_clock() -> datetime:
        nonlocal calls
        calls += 1
        return NOW

    ctrl._clock = counting_clock
    ctrl._run_delivery_intent = dataclasses.replace(
        ctrl._run_delivery_intent, output_directory=str(second_out)
    )
    ctrl._current_delivery_preparation = None
    record_validation, context = ctrl._current_record_validation()
    assert context is None
    calls = 0
    ctrl._current_delivery(record_validation)
    assert calls == 1
    prepared = ctrl._current_delivery_preparation
    ctrl._current_delivery(record_validation)
    assert calls == 1
    assert ctrl._current_delivery_preparation is prepared
    ctrl.dispatch("refresh_delivery", {})
    assert ctrl._current_delivery_preparation is not prepared


def test_delivery_occupancy_is_read_only_and_collision_policy_is_backend_owned(
    tmp_path: Path,
) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    existing = out / "공고서-20260818-001.hwpx"
    existing.write_text("existing", encoding="utf-8")
    second_existing = out / "공고서-20260818-002.hwpx"
    second_existing.write_text("existing", encoding="utf-8")
    before = tuple(item.name for item in out.iterdir())

    ctrl.set_output_folder(str(out))
    zone = _zone(ctrl)
    assert zone["delivery"]["planned_documents"][0]["relative_path"] == (
        "공고서-20260818-001_1.hwpx"
    )
    assert tuple(item.name for item in out.iterdir()) == before
    ctrl.dispatch("set_delivery_collision", {"collision_policy": "FAIL"})
    zone = _zone(ctrl)
    assert zone["delivery"]["resolvable"] is False
    assert zone["delivery"]["blockers"][0]["code"] == (
        "OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED"
    )
    assert [
        blocker["conflicting_relative_path"]
        for blocker in zone["delivery"]["blockers"]
    ] == ["공고서-20260818-001.hwpx", "공고서-20260818-002.hwpx"]
    assert tuple(item.name for item in out.iterdir()) == before

    ctrl.dispatch(
        "set_delivery_collision", {"collision_policy": "OVERWRITE_EXPLICIT"}
    )
    zone = _zone(ctrl)
    assert zone["delivery"]["planned_documents"][0] == {
        "record_identity": ctrl._current_record_identity(ctrl._snapshot_gen, 1),
        "item_ordinal": 0,
        "relative_path": "공고서-20260818-001.hwpx",
        "collision_disposition": "WRITE_OVERWRITE",
    }
    assert tuple(item.name for item in out.iterdir()) == before


def test_directory_collision_blocks_explicit_overwrite_with_exact_path(tmp_path: Path) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    conflict = out / "공고서-20260818-001.hwpx"
    conflict.mkdir()

    ctrl.set_output_folder(str(out))
    ctrl.dispatch(
        "set_delivery_collision", {"collision_policy": "OVERWRITE_EXPLICIT"}
    )
    zone = _zone(ctrl)

    assert zone["delivery"]["resolvable"] is False
    assert zone["delivery"]["blockers"][0]["code"] == "OUTPUT_PATH_NON_REGULAR_CONFLICT"
    assert zone["delivery"]["blockers"][0]["message"] == (
        "같은 이름의 폴더나 바로가기 등이 있어 덮어쓸 수 없습니다:"
    )
    assert zone["delivery"]["blockers"][0]["conflicting_relative_path"] == conflict.name
    assert conflict.is_dir()


def test_path_occupancy_classifies_symlink_without_following_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "symlink-observation"
    out.mkdir()

    class SymlinkEntry:
        name = "보고서.hwpx"

        @staticmethod
        def is_symlink() -> bool:
            return True

        @staticmethod
        def is_file() -> bool:
            raise AssertionError("symlink target was followed")

    monkeypatch.setattr(Path, "iterdir", lambda _path: iter((SymlinkEntry(),)))
    observation = JobController._observe_path_occupancy(
        RunDeliveryIntent(str(out)), NOW.isoformat()
    )

    assert observation.occupied_entries[0].relative_name == SymlinkEntry.name
    assert observation.occupied_entries[0].kind == screen_job_module.NON_REGULAR


def test_inactive_typed_filename_uses_frozen_record_without_source_reread(
    tmp_path: Path,
) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("select_job", {"name": WORK_REF})
    _wire_source_plan(ctrl)
    fresh = ctrl._last_fresh_observation
    assert isinstance(fresh, CurrentSealedPlanObservation)
    binding = fresh.current_field_binding
    assert binding is not None
    typed_rule = FieldBindingRule(
        field_id="f_date",
        binding_kind=SOURCE,
        document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
        source_key="typed_date",
        value_type=DATE,
    )
    current_binding = build_field_binding_input(
        workspace_instance_id=binding.workspace_instance_id,
        work_authority_id=binding.work_authority_id,
        base_template_application_id=binding.base_template_application_id,
        binding_rules=(*binding.binding_rules, typed_rule),
        source_schema_keys=(*binding.source_schema_keys, "typed_date"),
        raw_record_contract_id=binding.raw_record_contract_id,
        captured_at=binding.captured_at,
    )
    ctrl._last_fresh_observation = dataclasses.replace(
        fresh, current_field_binding=current_binding
    )
    _mount_rows(ctrl, [{"name": "A", "typed_date": "2026-08-20"}])
    assert ctrl.vm is not None
    ctrl.vm.job.filename_pattern = "{{f_date}}"

    class NoReadSource:
        def __getattribute__(self, name):
            raise AssertionError(f"delivery-time mutable source reread: {name}")

    out = tmp_path / "typed-delivery"
    out.mkdir()
    record_validation, context = ctrl._current_record_validation()
    assert context is None
    ctrl.datasource = NoReadSource()
    ctrl._run_delivery_intent = RunDeliveryIntent(str(out))

    delivery, context = ctrl._current_delivery(record_validation)
    assert context is None
    assert delivery.resolvable is True
    assert delivery.planned_documents[0].relative_path == (
        "2026-08-20.hwpx"
    )


def test_delivery_unreadable_directory_is_loud_and_never_created(tmp_path: Path) -> None:
    ctrl, _out = _delivery_controller(tmp_path)
    missing = tmp_path / "missing-output"

    ctrl.set_output_folder(str(missing))
    zone = _zone(ctrl)

    assert zone["kind"] == "context_error"
    assert zone["code"] == "PATH_OCCUPANCY_OBSERVATION_FAILED"
    assert zone["detail"] == "저장 폴더의 현재 파일 목록을 읽을 수 없습니다."
    assert not missing.exists()


def test_stale_projects_backend_execution_action_when_it_is_primary(
    tmp_path: Path,
) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    from hwpxfiller.application.automatic_seal_orchestration import (
        AutomaticSealOrchestration,
    )

    ctrl.datasource = object()
    ctrl.records = [{}]
    ctrl.selection = SelectionModel(1)

    ctrl._session_orchestration = AutomaticSealOrchestration(state="STALE")
    zone = _zone(ctrl)

    assert zone["primary_action"] == "RESOLVE_EXECUTION"
    assert zone["execution_action"] == {
        "label": "\ud604\uc7ac \uc124\uc815 \ud655\uc778",
        "enabled": True,
        "disabled_reason": None,
    }


def test_select_managed_work_automatically_prepares_current_value(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.job_name = ""

    ctrl.dispatch("select_job", {"name": WORK_REF})

    assert _zone(ctrl)["execution_status_code"] == "CURRENT"


# ── binding seed → resolve_execution → CURRENT + NOT_ADMITTED + NOT_READY(S6 미출하 정직) ───────
def test_resolve_execution_reaches_current_not_admitted_not_ready(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    zone = _zone(ctrl)
    assert zone["execution_status_code"] == "CURRENT"
    assert zone["execution_status_phrase"] == "현재 설정이 반영됐습니다"
    assert zone["admission"]["state"] == "NOT_ADMITTED"
    assert zone["materialization_readiness"] == "NOT_READY"
    # seal 루프가 닫혔다: 마지막 sealed basis digest 가 세션에 잡혔다(durable 아님).
    assert ctrl._last_sealed_basis_digest is not None
    # CREATE 로 조용히 새지 않는다(honest disabled) — delivery anchor + runtime.
    assert zone["primary_action"] != "CREATE_DOCUMENTS"
    assert zone["create_action"] == {
        "label": "\ubb38\uc11c \ub9cc\ub4e4\uae30",
        "enabled": False,
        "disabled_reason": "\ud604\uc7ac \ud658\uacbd\uc5d0\uc11c\ub294 \ubb38\uc11c\ub97c \ub9cc\ub4e4 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4",
    }


def test_create_documents_never_reached_with_current(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    obs = ctrl.workbench_observation()
    # CURRENT 여도 admission NOT_ADMITTED + delivery 미해결이라 CREATE_DOCUMENTS 아님.
    assert obs.primary_action != "CREATE_DOCUMENTS"
    assert obs.materialization_readiness == "NOT_READY"


def test_snapshot_marks_durable_work_as_managed_hwpx(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("select_job", {"name": WORK_REF})

    assert ctrl.snapshot()["managed_hwpx"] is True


def test_managed_hwpx_generate_never_reaches_legacy_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("select_job", {"name": WORK_REF})

    def forbidden(*args, **kwargs):
        pytest.fail("managed HWPX reached legacy generator")

    monkeypatch.setattr(ctrl, "_generate_locked", forbidden)
    result = ctrl._generate_with_token()
    assert result["ok"] is False
    assert result["error"] == "\ud604\uc7ac \ud658\uacbd\uc5d0\uc11c\ub294 \ubb38\uc11c\ub97c \ub9cc\ub4e4 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4"

# ── binding 없음 → 정직한 blocked(NO_EVIDENCE 를 CURRENT/READY 로 위장하지 않는다) ─────────────
def test_resolve_execution_without_binding_is_honestly_blocked(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=False)
    ctrl.dispatch("resolve_execution", {})
    zone = _zone(ctrl)
    # 미봉인 — current Work 만 관찰(domain block). 7상태는 CURRENT/READY 가 아니다.
    assert zone["execution_status_code"] != "CURRENT"
    assert zone["execution_status_code"] in ("DOMAIN_BLOCKED", "POLICY_BLOCKED", "NO_EVIDENCE", "STALE")
    assert zone["materialization_readiness"] == "NOT_READY"
    assert zone["primary_action"] != "CREATE_DOCUMENTS"
    assert ctrl._last_sealed_basis_digest is None  # sealed 안 됨 → digest 없음
    assert "REVIEW_BINDING" in zone["blockers"]
    assert zone["input_requirements"]
    assert all(item["binding_state"] == "NEW_ACTIVE_FIELD" for item in zone["input_requirements"])
    assert all(item["action_required"] is True for item in zone["input_requirements"])
    assert all(item["exact_target"].startswith("binding/") for item in zone["input_requirements"])


# ── refresh_observation: 지금 이 순간을 재관찰(orchestration 전이 없음) ──────────────────────────
def test_refresh_observation_reobserves_current(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    digest_after_seal = ctrl._last_sealed_basis_digest
    ctrl.dispatch("refresh_observation", {})
    # 재관찰은 같은 basis 를 재계산한다(같은 digest) — orchestration 은 SETTLED_CURRENT 유지.
    assert ctrl._last_sealed_basis_digest == digest_after_seal
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"


def test_refresh_observation_standalone_observes_without_orchestration_transition(
    tmp_path: Path,
) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    # 사전 resolve 없이 refresh 만 해도 seal(순수 재계산)이 돌아 관찰을 얻는다 — orchestration 은
    # 건드리지 않으므로 IDLE 유지(자동 확인 궤도와 분리).
    ctrl.dispatch("refresh_observation", {})
    assert ctrl._last_fresh_observation is not None
    assert ctrl._session_orchestration.state == "IDLE"


# ── 반복 resolve 는 same-basis 를 같은 digest 로 재봉인(recompute 안정성) ──────────────────────────
def test_repeated_resolve_keeps_stable_basis_digest(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    first = ctrl._last_sealed_basis_digest
    ctrl.dispatch("resolve_execution", {})
    # basis 가 안 움직였으면 순수 재계산은 같은 execution_basis_digest 를 낸다.
    assert ctrl._last_sealed_basis_digest == first
    assert ctrl._session_orchestration.state == "SETTLED_CURRENT"


# ── 미주입 loud 거절(조용한 no-op 금지) ─────────────────────────────────────────────────────────
def test_resolve_execution_unwired_rejects_loudly(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True, wire_seal=False)
    with pytest.raises(ValueError):
        ctrl.dispatch("resolve_execution", {})


# ── fresh_observation → verdict 추출(순수 재라벨, 재판정 0) ──────────────────────────────────────
def test_verdicts_from_context_error_observation() -> None:
    v = execution_verdicts_from_fresh(ExecutionObservationContextError("C_ERR", "detail"))
    # fresh 축 실패 → admission CONTEXT_ERROR(composer/status 가 ContextError 로 표현).
    assert v.admission.state == "CONTEXT_ERROR"
    assert v.materialization_readiness == "NOT_READY"


def test_verdicts_from_current_work_observation() -> None:
    obs = CurrentWorkExecutionObservation(
        work_authority_ref="w",
        current_sealability="DOMAIN_BLOCKED",
        observed_at="t",
        normalized_blockers_or_policy=("NEEDS_FIELD_BINDING_APPLICATION_REVIEW",),
    )
    v = execution_verdicts_from_fresh(obs)
    assert v.current_work_sealability == "DOMAIN_BLOCKED"
    assert v.admission.state == "NOT_ADMITTED"  # 미봉인 → 정직한 NOT_ADMITTED(READY 아님)

    assert v.normalized_blockers_or_policy == (
        "NEEDS_FIELD_BINDING_APPLICATION_REVIEW",
    )


def test_normalized_binding_blocker_selects_review_binding() -> None:
    from hwpxfiller.application.automatic_seal_orchestration import (
        AutomaticSealOrchestration,
    )

    fresh = CurrentWorkExecutionObservation(
        work_authority_ref="w",
        current_sealability="DOMAIN_BLOCKED",
        observed_at="t",
        normalized_blockers_or_policy=("NEEDS_FIELD_BINDING_APPLICATION_REVIEW",),
    )
    result = WorkbenchObservationProduct().compose(
        data_mounted=True,
        selected_record_count=1,
        total_record_count=1,
        active_work_ref="w",
        slot_view=_FakeView(SLOT_SELECTIONS_COMPLETE),
        orchestration=AutomaticSealOrchestration(),
        fresh_observation=fresh,
        preview_requirement=PreviewNotRequired(),
        preview_satisfied=True,
        semantic_preview=None,
    )
    assert result.primary_action == "REVIEW_BINDING"



# ── 깨진 슬롯 선택도 content blocker(사용자를 고쳐야 할 구성 너머로 지나치게 하지 않는다) ─────────
class _FakeView:
    def __init__(self, status: str) -> None:
        self.configuration_status = status
        self.slots = ()


def test_broken_selections_count_as_unselected_required_content() -> None:
    assert content_selection_from_view(
        _FakeView(HAS_BROKEN_SELECTIONS)
    ).has_unselected_required_content is True
    assert content_selection_from_view(
        _FakeView(NEEDS_SELECTION)
    ).has_unselected_required_content is True
    assert content_selection_from_view(
        _FakeView(SLOT_SELECTIONS_COMPLETE)
    ).has_unselected_required_content is False


# ── automatic checking 트리거(durable slot mutation CHANGED → 자동 확인) ─────────────────────────
class _ChangedOutcome:
    changed = True


class _UnchangedOutcome:
    changed = False


class _SlotResp:
    def __init__(self, changed: bool) -> None:
        self.mutation_outcome = _ChangedOutcome() if changed else _UnchangedOutcome()


def test_changed_slot_mutation_triggers_auto_seal(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    # durable mutation CHANGED → effective_basis_changed True → CHECKING → seal → SETTLED_CURRENT.
    ctrl._maybe_auto_check(_SlotResp(changed=True))
    assert ctrl._last_fresh_observation is not None
    assert ctrl._last_sealed_basis_digest is not None  # binding 있으니 sealed
    assert ctrl._session_orchestration.state == "SETTLED_CURRENT"
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"


def test_unchanged_slot_mutation_does_not_trigger_seal(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl._maybe_auto_check(_SlotResp(changed=False))
    # 무변경 mutation → 반응할 basis 변경 없음(seal 미실행, 증거 없음 유지).
    assert ctrl._last_fresh_observation is None
    assert ctrl._session_orchestration.state == "IDLE"


def test_changed_mutation_without_binding_settles_not_current(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=False)
    ctrl._maybe_auto_check(_SlotResp(changed=True))
    # seal 은 돌았지만 binding 미검토 → 미봉인(current-work 관찰). CURRENT 아님, digest 없음.
    assert ctrl._last_fresh_observation is not None
    assert ctrl._last_sealed_basis_digest is None
    assert _zone(ctrl)["execution_status_code"] != "CURRENT"


def test_auto_check_noop_without_seal_service(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True, wire_seal=False)
    # seal 미주입이면 자동 확인 없음(honest — 표면 부재, 조용한 crash 아님).
    ctrl._maybe_auto_check(_SlotResp(changed=True))
    assert ctrl._last_fresh_observation is None


# ── context error 를 user-fixable blocker 로 낮추지 않는다(§즉시 상향 계약) ──────────────────────
def test_context_error_observation_is_not_lowered_to_user_blocker(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl._last_fresh_observation = ExecutionObservationContextError("E_CTX", "복원 실패")
    zone = _zone(ctrl)
    assert zone["kind"] == "context_error"
    assert zone["user_fixable"] is False
    assert zone["primary_action"] == "RECOVER_CONTEXT"


def test_zone_blank_without_selected_job(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.job_name = ""  # 미선택 → unsupported(조용히 비우지 않는다).
    zone = _zone(ctrl)
    assert zone["supported"] is False and zone["kind"] is None


# ── resolve_execution: FAILED 에서 수동 복구 후 재확인 ───────────────────────────────────────────
def test_resolve_execution_recovers_from_failed(tmp_path: Path) -> None:
    from hwpxfiller.application.automatic_seal_orchestration import AutomaticSealOrchestration

    ctrl = _controller(tmp_path, with_binding=True)
    ctrl._session_orchestration = AutomaticSealOrchestration(
        state="FAILED", consecutive_seal_failures=3
    )
    ctrl.dispatch("resolve_execution", {})
    # FAILED → 수동 복구(IDLE) → CHECKING → 실 seal → SETTLED_CURRENT(binding 있음).
    assert ctrl._session_orchestration.state == "SETTLED_CURRENT"
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"


# ── fresh 축 degrade(seal 실패는 조용히 CURRENT 로 두지 않는다) ─────────────────────────────────
class _RaisingSeal:
    """seal 이 예외를 던지는 fake seal 서비스 — degrade 경로 가드."""

    def seal_execution_plan(self, work, req):
        raise RuntimeError("seal boom")


def test_auto_seal_failure_leaves_last_observation(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True, wire_seal=False)
    ctrl._seal_execution = _RaisingSeal()
    # route/context 예외 = 전이 실패(수동 복구 상한). 조용한 crash 아님, 마지막 관찰 보존(None).
    ctrl._maybe_auto_check(_SlotResp(changed=True))
    assert ctrl._last_fresh_observation is None


def test_refresh_observation_failure_surfaces_context_error(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True, wire_seal=False)
    ctrl._seal_execution = _RaisingSeal()
    # 확인 실패를 조용히 이전 관찰로 두지 않는다 — context error 로 시끄럽게(CURRENT 유지 금지).
    ctrl.dispatch("refresh_observation", {})
    assert isinstance(ctrl._last_fresh_observation, ExecutionObservationContextError)
    assert _zone(ctrl)["kind"] == "context_error"
    zone = _zone(ctrl)
    assert zone["execution_status_code"] == "CONTEXT_ERROR"
    assert zone["execution_status_phrase"] == "\ud604\uc7ac \uc2e4\ud589 \uc0c1\ud0dc\ub97c \ud655\uc778\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4"
    assert zone["user_fixable"] is False
    assert zone["create_action"]["enabled"] is False


def test_refresh_failure_after_current_does_not_keep_claiming_current(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"
    # 이후 refresh 가 실패하면 이전 CURRENT 를 계속 주장하지 않고 context error 로 전환.
    ctrl._seal_execution = _RaisingSeal()
    ctrl.dispatch("refresh_observation", {})
    assert _zone(ctrl)["kind"] == "context_error"


# ── 세션 실행 증거는 Work 에 묶인다(전환 시 무효화 — A 의 관찰로 B 를 CURRENT 라 하지 않는다) ──────
def test_work_switch_resets_execution_evidence(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"
    assert ctrl._last_sealed_basis_digest is not None
    # 다른 Work 로 전환 → 세션 실행 증거 무효화(orchestration IDLE·관찰/디지스트 None).
    ctrl.job_name = "다른작업"
    assert ctrl._last_fresh_observation is None
    assert ctrl._last_sealed_basis_digest is None
    assert ctrl._session_orchestration.state == "IDLE"


def test_same_work_reassignment_keeps_evidence(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    obs = ctrl._last_fresh_observation
    ctrl.job_name = WORK_REF  # 같은 값 재대입은 재설정하지 않는다.
    assert ctrl._last_fresh_observation is obs
    assert ctrl._session_orchestration.state == "SETTLED_CURRENT"


# ── 사용자 문안 내부어 노출 0(#725 §테스트 12 계약 유지) ─────────────────────────────────────────
def test_observation_exposes_no_internal_vocabulary(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    zone = _zone(ctrl)
    banned = ("Slot", "Sealed", "Plan", "digest", "Application", "VDR", "Candidate")
    texts = [zone["execution_status_phrase"], zone["content_section_label"],
             zone["input_requirements_label"], zone["delivery_label"]]
    if zone["disabled_reason"]:
        texts.append(zone["disabled_reason"])
    for text in texts:
        for word in banned:
            assert word not in text, (word, text)


def _saved_active_mapping() -> MappingProfile:
    return MappingProfile(
        mappings=[
            FieldMapping(field_id, type="const", const="v")
            for field_id in (
                "\uc131\uba85",
                "\uc8fc\uc18c",
                "\ud56d\ubaa9",
                "\uae08\uc561",
            )
        ]
    )


def test_binding_commit_reuses_auto_check_and_reaches_current(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=False)
    job = ctrl.registry.load(WORK_REF)
    job.mapping = _saved_active_mapping()
    ctrl.registry.save(job, allow_overwrite=True)

    result = ctrl.on_editor_mapping_saved(WORK_REF)

    assert result["binding_commit_ok"] is True
    assert ctrl._last_sealed_basis_digest is not None
    assert ctrl._session_orchestration.state == "SETTLED_CURRENT"
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"


def test_binding_commit_for_other_work_does_not_absorb_observation(
    tmp_path: Path,
) -> None:
    ctrl = _controller(tmp_path, with_binding=False)
    job = ctrl.registry.load(WORK_REF)
    job.mapping = _saved_active_mapping()
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.job_name = "\ub2e4\ub978\uc791\uc5c5"

    result = ctrl.on_editor_mapping_saved(WORK_REF)

    assert result["binding_commit_ok"] is True
    assert ctrl._last_fresh_observation is None
    assert ctrl._last_sealed_basis_digest is None
    assert ctrl._session_orchestration.state == "IDLE"


def test_template_apply_rechecks_same_work_execution_evidence(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    before = ctrl._last_fresh_observation

    class AppliedTemplateChange:
        @staticmethod
        def apply(job_name: str, change_token: str) -> dict:
            assert job_name == WORK_REF and change_token == "token"
            return {"status": "applied"}

    ctrl._template_change = AppliedTemplateChange()
    result = ctrl.dispatch("template_apply", {"change_token": "token"})

    assert result["status"] == "applied"
    assert ctrl._last_fresh_observation is not before
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"
