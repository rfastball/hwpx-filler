"""SX-03(#726) — 「문서 만들기」 패널에 배선된 execution admission·readiness 헤드리스 가드 (post-R2 #740).

seal 판정·admission 파생은 SealExecutionPlanService·SealExecutionPlanProduct 테스트가 소유한다.
여기가 잰다: JobController 가 `self._seal_execution`(SX-SEAL) 을 소비해 (1) 확인 증거 없이
NO_EVIDENCE 로 서고, (2) `resolve_execution` 이 실 seal 을 돌려 binding 있는 Work 는
CURRENT+ADMITTED+READY(S6-03 #810 정식 주입)로, binding 없는 Work 는 정직한 blocked 로 관찰되며, (3) 어느 경우도
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

from hwpxfiller.application.document_creation_vocabulary import (
    DEFAULT_COLLISION_POLICY,
)
from hwpxfiller.application.jobs import Job
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths
from hwpxfiller.external.settings import (
    load_last_output_directory,
    save_last_output_directory,
)
from hwpxfiller.domain.template_status import OUTPUT_SUBDIR_NAME
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
from hwpxfiller.application.execution_structure import ExecutionStructureError
from hwpxfiller.application.document_creation_workbench import InputRequirement
from hwpxfiller.application.field_binding_input import (
    BROKEN,
    INACTIVE_ONLY,
    NEW_ACTIVE_FIELD,
    PRESERVED,
    build_field_binding_input,
)
from hwpxfiller.application.run_delivery_intent import RunDeliveryIntent
from hwpxfiller.application.preview_requirement import PreviewNotRequired, PreviewRequired
from hwpxfiller.domain.field_binding import (
    DATE,
    DECIMAL,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    EXACT_TEXT,
    SOURCE,
    FieldBindingInputIntegrityError,
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
TEMPLATE_FIXTURE = Path(__file__).parent / "fixtures" / "template_v1.hwpx"


def _clock():
    return lambda: NOW


def _controller(
    tmp_path: Path,
    *,
    with_binding: bool,
    wire_seal: bool = True,
    seed: bool = True,
    template_path: str = "managed.hwpx",
):
    """실 SlotConfigurationProduct + SealExecutionPlanService 를 **같은 authority root** 로 배선.

    v2 Work 를 그 root 에 직접 seed 하고 registry 의 WorkAuthorityId 를 그 Work 에 못박아, 컨트롤러의
    job_name → seal 서비스 route 가 seed 한 Work 에 닿게 한다(test_seal_execution_plan_service 패턴).
    R2(#740): admission store seed 는 필요 없다 — runtime admission 은 materializer conformance
    capability(S6-03 정식 주입 → 실제 봉인 Plan 은 ADMITTED)만 본다.
    """
    root = default_template_authority_dir()
    if seed:
        _seed_v2_work(root, with_binding=with_binding)
    reg = JobRegistry(tmp_path / "jobs")
    # 기본 template_path 는 상대 경로다 — 저장 폴더 기본값이 서지 **않는** 형상(U3-06 #879).
    # 기본값 도출을 재는 테스트만 전체 경로를 건넨다.
    # 데이터 결속(#932 U4-C) — 미결속이면 `CONNECT_DATA` blocker 가 앞서 서서 이 파일이
    # 재려는 관리 배달·미리보기·실행 축에 도달하지 못한다. 이 축들이 결속 유무와
    # 무관하다는 사실 자체가 픽스처를 결속시키는 근거다.
    reg.save(Job(
        name=WORK_REF, template_path=template_path,
        data_path=str(tmp_path / "d.csv"), data_sheet="", data_header_row=0,
    ))
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
    """확인 전 상태는 **정직한 사유 + 그것을 지울 활성 동사**를 함께 낸다(#912 D1).

    종전 단언은 `primary_action != "CREATE_DOCUMENTS"` 뿐이라 「무엇이 서 있는가」를 못 박지
    않았고, 그 틈으로 두 거짓이 함께 살았다: (a) 확인 동사(`execution_action`)가 `null` 이라
    「현재 설정을 확인해야 합니다」를 지울 수단이 화면에 없고, (b) 생성 버튼 사유가 「현재
    환경에서는 문서를 만들 수 없습니다」라 사용자가 지금 풀 수 있는 상태를 못 푸는 상태로
    오보했다. 둘 다 여기서 못 박는다.
    """
    ctrl = _controller(tmp_path, with_binding=True)
    zone = _zone(ctrl)
    assert zone["supported"] is True and zone["kind"] == "observation"
    assert zone["execution_status_code"] == "NO_EVIDENCE"
    assert zone["execution_status_phrase"] == "현재 설정을 확인해야 합니다"
    # 아직 확인 전이라 READY 를 주장하지 않는다(materialization NOT_READY).
    assert zone["materialization_readiness"] == "NOT_READY"

    # (a) 확인 축이 blocker 로 서고, 그것을 지울 동사가 **활성으로** 실린다. 앞선 blocker
    #     (여기서는 데이터 미선택)가 Primary Action 을 가져가도 동사는 사라지지 않는다.
    assert zone["primary_action"] == "SELECT_DATA"
    assert "EXECUTION_NO_EVIDENCE" in zone["blockers"]
    assert zone["execution_action"] == {
        "label": "현재 설정 확인",
        "enabled": True,
        "disabled_reason": None,
    }
    # (b) 아직 확인하지 않았을 뿐 runtime 이 거절한 것이 아니다 — 사유도 admission 사유도 정직하다.
    assert zone["create_action"]["enabled"] is False
    assert zone["create_action"]["disabled_reason"] == "필요한 준비를 먼저 완료해 주세요"
    assert zone["admission"] == {
        "state": "NOT_ADMITTED",
        "reasons": ["EXECUTION_EVIDENCE_NOT_OBSERVED"],
    }
    assert "RUNTIME_NOT_ADMITTED" not in zone["blockers"]


def test_no_evidence_keeps_the_check_verb_after_data_is_mounted(tmp_path: Path) -> None:
    """데이터가 갖춰져 Primary Action 이 확인으로 넘어와도 같은 동사 하나가 계속 선다(#912 D1)."""
    ctrl = _controller(tmp_path, with_binding=True)
    _mount_rows(ctrl, [{"name": "A"}])
    ctrl.dispatch("set_all", {})
    zone = _zone(ctrl)
    assert zone["execution_status_code"] == "NO_EVIDENCE"
    assert zone["primary_action"] == "RESOLVE_EXECUTION"
    assert zone["execution_action"]["enabled"] is True
    assert zone["create_action"]["disabled_reason"] == "필요한 준비를 먼저 완료해 주세요"


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
    with pytest.raises(ValueError, match='현재 데이터 확인 결과가 없습니다'):
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


def _delivery_controller(
    tmp_path: Path, *, template_path: str = "managed.hwpx"
) -> tuple[JobController, Path]:
    ctrl = _controller(tmp_path, with_binding=True, template_path=template_path)
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
        "collision_policy": DEFAULT_COLLISION_POLICY,
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
    # S6-03(#810): runtime admission 이 정식 주입으로 ADMITTED 라, 준비가 끝난 이 시나리오에서
    # create 는 열린다. 실제 클릭은 S6-05 가드 철거 전까지 시끄럽게 거절된다(#806 R1 계약 —
    # 조용한 진행 경로는 없다). 이 간극은 S6-05 가 닫고, HWPX 릴리스는 #807 완주 전 없다.
    assert zone["create_action"]["enabled"] is True


# ── U3-06(#879) 저장 폴더 도출 — ① 명시 지정 ② 기억한 지정 ③ 템플릿 옆 Results ──────────
def _sited_delivery_controller(tmp_path: Path) -> "tuple[JobController, Path]":
    """템플릿이 실제 자리를 가진 관리 작업 — 기본값(템플릿 옆 ``Results``)이 서는 형상.

    반환하는 폴더는 **아직 없다**: 도출·관찰이 폴더를 만들지 않는다는 것도 계약이다.
    """
    template = tmp_path / "서고" / "managed.hwpx"
    template.parent.mkdir(parents=True, exist_ok=True)
    ctrl, _picked = _delivery_controller(tmp_path, template_path=str(template))
    return ctrl, template.parent / OUTPUT_SUBDIR_NAME


def test_unset_output_folder_defaults_beside_the_template_and_says_so(
    tmp_path: Path,
) -> None:
    """미지정이 곧 차단이던 축이 기본값으로 선다 — 그 폴더는 화면에 **표시된다**."""
    ctrl, results = _sited_delivery_controller(tmp_path)

    zone = _zone(ctrl)

    assert ctrl._run_delivery_intent is None  # 세션 명시 지정은 여전히 없다
    assert zone["output_folder"] == {
        "directory": str(results),
        "source": "template_default",
        "source_label": "기본값",
        "notice": "",
    }
    assert zone["run_delivery_intent"] == {
        "output_directory": str(results),
        "collision_policy": DEFAULT_COLLISION_POLICY,
    }
    assert zone["delivery"]["resolvable"] is True
    assert zone["delivery"]["blockers"] == []
    assert [item["relative_path"] for item in zone["delivery"]["planned_documents"]] == [
        "공고서-20260818-001.hwpx",
        "공고서-20260818-002.hwpx",
    ]
    assert not results.exists()  # 관찰은 폴더를 만들지 않는다


def test_collision_policy_is_the_fixed_default_and_has_no_selector(tmp_path: Path) -> None:
    """충돌 처리는 **고르는 값이 아니다**(U4 계열2-27).

    이름 충돌 자체는 blocker 가 아니라서 고를 것이 없다 — 같은 이름이 있으면 덮어쓰고,
    무엇을 덮어쓰는지는 확인 면이 묻는다. 그래서 정책을 바꾸는 액션도 사라졌고, 도출된
    기본값 위에서도 intent 는 그 하나로 선다(기본값이 '직접 지정'으로 승격되지도 않는다).
    """
    ctrl, results = _sited_delivery_controller(tmp_path)

    zone = _zone(ctrl)
    assert zone["run_delivery_intent"] == {
        "output_directory": str(results),
        "collision_policy": DEFAULT_COLLISION_POLICY,
    }
    assert DEFAULT_COLLISION_POLICY == "OVERWRITE_EXPLICIT"
    assert zone["output_folder"]["source"] == "template_default"
    assert ctrl._run_delivery_intent is None

    with pytest.raises(ValueError, match="알 수 없는 작업 화면 액션"):
        ctrl.dispatch("set_delivery_collision", {"collision_policy": "FAIL"})
    with pytest.raises(ValueError, match="알 수 없는 작업 화면 액션"):
        ctrl.dispatch("refresh_delivery", {})


def test_explicit_pick_wins_and_is_remembered_for_the_next_session(
    tmp_path: Path,
) -> None:
    ctrl, results = _sited_delivery_controller(tmp_path)
    picked = tmp_path / "직접-고른-폴더"
    picked.mkdir()

    ctrl.set_output_folder(str(picked))

    zone = _zone(ctrl)
    assert zone["output_folder"] == {
        "directory": str(picked),
        "source": "explicit",
        "source_label": "직접 지정",
        "notice": "",
    }
    assert zone["run_delivery_intent"]["output_directory"] == str(picked)
    assert str(results) not in str(zone["run_delivery_intent"])
    # 기억은 설정 층 소유다 — 다음 세션의 도출 재료.
    assert load_last_output_directory() == str(picked)


def test_remembered_folder_is_restored_as_the_default_on_a_new_controller(
    tmp_path: Path,
) -> None:
    """재시작(새 컨트롤러) — 세션 명시 지정은 없지만 기억한 폴더가 기본값으로 산다."""
    remembered = tmp_path / "지난번-폴더"
    remembered.mkdir()
    save_last_output_directory(str(remembered))

    ctrl, _results = _sited_delivery_controller(tmp_path)

    zone = _zone(ctrl)
    assert zone["output_folder"] == {
        "directory": str(remembered),
        "source": "remembered",
        "source_label": "기억한 폴더",
        "notice": "",
    }
    assert zone["run_delivery_intent"]["output_directory"] == str(remembered)
    assert zone["delivery"]["resolvable"] is True


def test_vanished_remembered_folder_falls_back_loudly_not_silently(
    tmp_path: Path,
) -> None:
    save_last_output_directory(str(tmp_path / "사라진-폴더"))

    ctrl, results = _sited_delivery_controller(tmp_path)

    zone = _zone(ctrl)
    assert zone["output_folder"]["directory"] == str(results)
    assert zone["output_folder"]["source"] == "template_default"
    assert zone["output_folder"]["notice"] == (
        "지난번에 지정한 저장 폴더를 찾을 수 없습니다. 기본 폴더로 되돌렸습니다."
    )
    assert zone["delivery"]["resolvable"] is True


def test_underivable_default_keeps_the_output_directory_requirement(
    tmp_path: Path,
) -> None:
    """도출 재료가 없으면(전체 경로 아닌 템플릿) 저장 폴더 지정이 전제조건으로 남는다."""
    ctrl, _out = _delivery_controller(tmp_path)  # template_path 는 상대 경로

    zone = _zone(ctrl)
    assert zone["output_folder"] == {
        "directory": "",
        "source": "",
        "source_label": "",
        "notice": "",
    }
    assert zone["run_delivery_intent"] is None
    assert zone["delivery"] == {
        "resolvable": False,
        "planned_documents": [],
        "blockers": [
            {
                "code": "OUTPUT_DIRECTORY_REQUIRED",
                "message": "저장 폴더를 선택하세요.",
                "item_ordinal": None,
                "field_id": None,
                "conflicting_relative_path": None,
            }
        ],
    }


def test_releasing_the_work_drops_the_explicit_pick_but_not_the_memory(
    tmp_path: Path,
) -> None:
    """명시 지정 소거 규약은 그대로. 기억은 설정에 남아 다음 도출에서 다시 후보가 된다."""
    ctrl, _results = _sited_delivery_controller(tmp_path)
    picked = tmp_path / "고른-폴더"
    picked.mkdir()
    ctrl.set_output_folder(str(picked))

    ctrl.dispatch("select_job", {"name": ""})

    assert ctrl._run_delivery_intent is None
    assert ctrl._run_delivery_collision == DEFAULT_COLLISION_POLICY
    assert load_last_output_directory() == str(picked)


def test_managed_generation_creates_the_derived_default_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """관찰은 안 만들고 **생성이** 만든다 — 구식 축의 `ensure_output_directory` 와 같은 시점."""
    import hwpxfiller.webapp.screen_job as sj
    from hwpxfiller.external.delivery_coordinator import (
        DeliveredDocument,
        DeliveryCompleted,
    )

    template = tmp_path / "서고" / "managed.hwpx"
    template.parent.mkdir(parents=True, exist_ok=True)
    results = template.parent / OUTPUT_SUBDIR_NAME
    ctrl = _controller(tmp_path, with_binding=True, template_path=str(template))
    ctrl.dispatch("select_job", {"name": WORK_REF})
    ctrl.dispatch("resolve_execution", {})
    rows = [{"이름": "A"}]
    _mount_rows(ctrl, rows)

    class Source:
        def records(self) -> list[dict]:
            return rows

    ctrl.datasource = Source()
    assert ctrl.vm is not None
    ctrl.vm.set_acquired(ctrl.datasource, rows)

    captured: dict = {}

    def fake_run(**kw):
        captured.update(kw)
        assert results.is_dir(), "생성이 저장 폴더를 만들지 않고 진입했다"
        return DeliveryCompleted(
            output_directory=str(results),
            delivered=(
                DeliveredDocument(0, "rec-0", "a.hwpx", str(results / "a.hwpx"),
                                  "WRITE_NEW", "sha256:" + "0" * 64, ()),
            ),
        )

    monkeypatch.setattr(sj, "run_managed_generation", fake_run)
    assert not results.exists()

    result = ctrl.generate(run_token="tk-default")

    assert result["ok"] is True, result.get("error")
    assert captured["resolved_delivery"].output_directory == str(results)
    assert results.is_dir()


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
    ctrl.dispatch("preview_move", {"delta": 1})
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
    assert before["semantic_preview"] is None
    ctrl.dispatch("preview_open", {})
    assert _zone(ctrl)["semantic_preview"] == {
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
    legacy_approvals = set(ctrl.review.approved)
    with pytest.raises(ValueError, match="토큰이 필요"):
        ctrl.dispatch("preview_approve", {})
    assert ctrl._approved_preview_token is None
    assert ctrl.review.approved == legacy_approvals
    ctrl.dispatch("preview_approve", {"preview_token": current.preview_token})

    zone = _zone(ctrl)
    assert "REVIEW_PREVIEW" not in zone["blockers"]
    assert zone["preview_satisfied"] is True
    assert ctrl._approved_preview_token == current.preview_token
    assert ctrl.review.approved == legacy_approvals


def test_stale_execution_invalidates_preview_and_rejects_old_token(
    tmp_path: Path,
) -> None:
    from hwpxfiller.application.automatic_seal_orchestration import (
        AutomaticSealOrchestration,
    )

    ctrl, out = _delivery_controller(tmp_path)
    (out / "공고서-20260818-001.hwpx").write_bytes(b"occupied")
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("preview_open", {})
    current = ctrl._current_preview_preparation
    assert current is not None
    ctrl.dispatch("preview_approve", {"preview_token": current.preview_token})

    ctrl._session_orchestration = AutomaticSealOrchestration(state="STALE")
    with pytest.raises(ValueError, match="더 이상 구성"):
        ctrl.dispatch("preview_approve", {"preview_token": current.preview_token})

    assert ctrl._current_record_preparation is None
    assert ctrl._current_delivery_preparation is None
    assert ctrl._current_preview_preparation is None
    assert ctrl._approved_preview_token is None
    assert not ctrl.review.approved
    zone = _zone(ctrl)
    assert zone["primary_action"] == "RESOLVE_EXECUTION"
    assert zone["preview_requirement"] == {"kind": "NOT_REQUIRED"}
    assert zone["semantic_preview"] is None


def test_delivery_refresh_replaces_token_and_stale_approval_writes_nothing(
    tmp_path: Path,
) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    (out / "공고서-20260818-001.hwpx").write_bytes(b"occupied")
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("preview_open", {})
    old = ctrl._current_preview_preparation
    assert old is not None

    ctrl.set_output_folder(str(out))
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


def test_output_directory_and_policy_changes_replace_preview_token(tmp_path: Path) -> None:
    ctrl, first_out = _delivery_controller(tmp_path)
    second_out = tmp_path / "delivery-2"
    second_out.mkdir()
    ctrl.set_output_folder(str(first_out))
    _zone(ctrl)
    first = ctrl._current_preview_preparation
    assert first is not None

    ctrl.set_output_folder(str(second_out))
    _zone(ctrl)
    second = ctrl._current_preview_preparation
    assert second is not None and second.preview_token != first.preview_token
    # 같은 폴더를 다시 지정해도 delivery 는 다시 관찰된다 — 토큰은 관찰의 정체이지
    # 경로의 정체가 아니다(U4 계열2-28 이후 이 재관찰이 「목록 새로 확인」의 승계자다).
    ctrl.set_output_folder(str(second_out))
    _zone(ctrl)
    third = ctrl._current_preview_preparation
    assert third is not None
    assert third.preview_token not in (first.preview_token, second.preview_token)


def test_preview_becoming_unconstructable_rejects_old_token(tmp_path: Path) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    (out / "공고서-20260818-001.hwpx").write_bytes(b"occupied")
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("preview_open", {})
    current = ctrl._current_preview_preparation
    assert current is not None

    ctrl.selection.set_none()
    with pytest.raises(ValueError, match="더 이상 구성"):
        ctrl.dispatch("preview_approve", {"preview_token": current.preview_token})
    assert ctrl._current_preview_preparation is None
    assert ctrl._approved_preview_token is None
    assert not ctrl.review.approved


def test_new_controller_never_restores_preview_approval(tmp_path: Path) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    (out / "공고서-20260818-001.hwpx").write_bytes(b"occupied")
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("preview_open", {})
    current = ctrl._current_preview_preparation
    assert current is not None
    ctrl.dispatch("preview_approve", {"preview_token": current.preview_token})
    assert ctrl._approved_preview_token == current.preview_token

    restart_root = tmp_path / "restart"
    restart_root.mkdir()
    restarted = _controller(restart_root, with_binding=True, seed=False)
    assert restarted._approved_preview_token is None
    assert restarted._current_preview_preparation is None


def test_s6_new_overwrite_target_requires_fresh_token_and_approval(
    tmp_path: Path,
) -> None:
    """Preview approval is no reservation: S6 handoff must refresh occupancy before write."""
    ctrl, out = _delivery_controller(tmp_path)
    (out / "공고서-20260818-001.hwpx").write_bytes(b"occupied")
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("preview_open", {})
    approved = ctrl._current_preview_preparation
    assert approved is not None
    ctrl.dispatch("preview_approve", {"preview_token": approved.preview_token})

    (out / "공고서-20260818-002.hwpx").write_bytes(b"late collision")
    # 재관찰의 트리거는 delivery 를 무효화하는 전이다 — 사람이 눌러 새로 세는 동사는
    # U4 계열2-28 에서 걷혔고, 최종 방어는 여전히 S6 handoff 의 쓰기 직전 재확인이다.
    ctrl.set_output_folder(str(out))
    zone = _zone(ctrl)
    current = ctrl._current_preview_preparation
    assert current is not None and current.preview_token != approved.preview_token
    assert ctrl._approved_preview_token is None
    assert [
        item["collision_disposition"]
        for item in zone["semantic_preview"]["ordered_records"]
    ] == ["WRITE_OVERWRITE", "WRITE_OVERWRITE"]
    assert zone["primary_action"] == "REVIEW_PREVIEW"


def test_preview_final_recheck_fails_closed_on_delivery_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    ctrl.set_output_folder(str(out))
    _zone(ctrl)
    original = screen_job_module.build_current_preview_projection

    def race(**kwargs):
        projection = original(**kwargs)
        ctrl._current_delivery_preparation = None
        return projection

    monkeypatch.setattr(screen_job_module, "build_current_preview_projection", race)
    ctrl.set_output_folder(str(out))
    zone = _zone(ctrl)
    assert zone["kind"] == "context_error"
    assert zone["code"] == "CURRENT_PREVIEW_PREPARATION_STALE"
    assert ctrl._current_preview_preparation is None
    assert ctrl._approved_preview_token is None


def test_non_regular_collision_keeps_delivery_ahead_of_preview(tmp_path: Path) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    (out / "공고서-20260818-001.hwpx").mkdir()
    ctrl.set_output_folder(str(out))

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
    ctrl.set_output_folder(str(second_out))
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
    ctrl.set_output_folder(str(second_out))
    assert ctrl._current_delivery_preparation is not prepared


def test_delivery_occupancy_is_read_only_and_name_conflicts_are_not_blockers(
    tmp_path: Path,
) -> None:
    """점유 관찰은 폴더를 건드리지 않고, 같은 이름은 **막지 않고 덮어쓸 계획**이 된다.

    U4 계열2-27 이전에는 이 자리가 정책 셋을 오가며 「번호 붙이기 / 막기 / 덮어쓰기」를
    각각 증명했다. 이제 제품이 세우는 정책은 하나이고, 그 하나가 이름 충돌을 blocker 로
    만들지 않는다 — 파괴 승인은 이름이 아니라 **처분**(`WRITE_OVERWRITE`)이 요구한다.
    """
    ctrl, out = _delivery_controller(tmp_path)
    existing = out / "공고서-20260818-001.hwpx"
    existing.write_text("existing", encoding="utf-8")
    second_existing = out / "공고서-20260818-002.hwpx"
    second_existing.write_text("existing", encoding="utf-8")
    before = tuple(item.name for item in out.iterdir())

    ctrl.set_output_folder(str(out))
    zone = _zone(ctrl)
    assert zone["delivery"]["resolvable"] is True
    assert zone["delivery"]["blockers"] == []
    assert zone["delivery"]["planned_documents"][0] == {
        "record_identity": ctrl._current_record_identity(ctrl._snapshot_gen, 1),
        "item_ordinal": 0,
        "relative_path": "공고서-20260818-001.hwpx",
        "collision_disposition": "WRITE_OVERWRITE",
    }
    # 번호를 붙여 피해 가지 않는다 — 사용자가 본 이름과 만들 이름이 같다.
    assert [item["relative_path"] for item in zone["delivery"]["planned_documents"]] == [
        "공고서-20260818-001.hwpx",
        "공고서-20260818-002.hwpx",
    ]
    # 그래도 조용하지 않다: 덮어쓸 항목이 섰으므로 확인이 REQUIRED 로 선다.
    assert zone["preview_requirement"] == {
        "kind": "REQUIRED",
        "reason": "DESTRUCTIVE_OVERWRITE",
    }
    assert zone["primary_action"] == "REVIEW_PREVIEW"
    # 관찰도 계획도 디스크를 만지지 않는다.
    assert tuple(item.name for item in out.iterdir()) == before
    assert existing.read_text(encoding="utf-8") == "existing"


def test_directory_collision_blocks_explicit_overwrite_with_exact_path(tmp_path: Path) -> None:
    ctrl, out = _delivery_controller(tmp_path)
    conflict = out / "공고서-20260818-001.hwpx"
    conflict.mkdir()

    ctrl.set_output_folder(str(out))
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


# ── binding seed → resolve_execution → CURRENT + ADMITTED + READY(S6-03 정식 주입) ─────────────
def test_resolve_execution_reaches_current_admitted_ready(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    zone = _zone(ctrl)
    assert zone["execution_status_code"] == "CURRENT"
    assert zone["execution_status_phrase"] == "현재 설정이 반영됐습니다"
    # S6-03(#810): shipping capability manifest 가 정식 주입돼 실제 봉인 Plan 은 ADMITTED·READY.
    assert zone["admission"]["state"] == "ADMITTED"
    assert zone["materialization_readiness"] == "READY"
    # seal 루프가 닫혔다: 마지막 sealed basis digest 가 세션에 잡혔다(durable 아님).
    assert ctrl._last_sealed_basis_digest is not None
    # runtime 이 열려도 CREATE 로 조용히 새지 않는다 — 데이터 미장착이 다음 정직한 blocker 다.
    assert zone["primary_action"] != "CREATE_DOCUMENTS"
    assert zone["create_action"] == {
        "label": "\ubb38\uc11c \ub9cc\ub4e4\uae30",
        "enabled": False,
        "disabled_reason": "\ud544\uc694\ud55c \uc900\ube44\ub97c \uba3c\uc800 \uc644\ub8cc\ud574 \uc8fc\uc138\uc694",
    }


def test_create_documents_never_reached_with_current(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    obs = ctrl.workbench_observation()
    # CURRENT + READY(S6-03) 여도 데이터·delivery 미해결이라 CREATE_DOCUMENTS 아님(조용한 진행 0).
    assert obs.primary_action != "CREATE_DOCUMENTS"
    assert obs.materialization_readiness == "READY"


def test_snapshot_marks_durable_work_as_managed_hwpx(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("select_job", {"name": WORK_REF})

    assert ctrl.snapshot()["managed_hwpx"] is True


def test_managed_hwpx_generate_never_reaches_legacy_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # S6-05(#812): slot-bearing managed Work \ub294 managed \uac08\ub798\ub85c \uac04\ub2e4 \u2014 legacy generator \ub3c4\ub2ec
    # 0(S6-9)\uc740 \uc720\uc9c0\ub418\uace0, \uc900\ube44 \ubbf8\ub2ec\uc758 \uac70\uc808 \uc0ac\uc720\ub294 \uac00\ub4dc \ud558\ub4dc\ucf54\ub529\uc774 \uc544\ub2c8\ub77c workbench
    # observation \uc758 disabled_reason \uc7ac\uc9c4\uc220\uc774\ub2e4(\ub370\uc774\ud130 \ubbf8\uc7a5\ucc29).
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("select_job", {"name": WORK_REF})

    def forbidden(*args, **kwargs):
        pytest.fail("managed HWPX reached legacy generator")

    monkeypatch.setattr(ctrl, "_generate_locked", forbidden)
    result = ctrl._generate_with_token()
    assert result["ok"] is False
    assert result["error"] == "\ud544\uc694\ud55c \uc900\ube44\ub97c \uba3c\uc800 \uc644\ub8cc\ud574 \uc8fc\uc138\uc694"

def test_managed_generate_wires_session_facts_into_the_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S6-05(#812) managed 갈래 배선 수직 — 세션 사실이 재조립 없이 파이프라인에 닿는다.

    bytes 진실은 test_managed_generation(실 store)·live101(actual WebView2)이 소유한다 —
    여기는 컨트롤러 층의 seam 계약을 잰다: 실 seal 이 세운 payload·digest·delivery 준비가
    그대로 넘어가고, reader 는 실제 authority 관찰로 sealed digest 와 동치이며, legacy
    generator 는 도달 0 이고, 결과 dict 는 legacy 키 집합으로 번역된다.
    """
    import hwpxfiller.webapp.screen_job as sj
    from hwpxfiller.external.delivery_coordinator import (
        DeliveredDocument,
        DeliveryCompleted,
    )

    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("select_job", {"name": WORK_REF})
    ctrl.dispatch("resolve_execution", {})  # 실 seal — payload·digest·workspace 가 세션에 선다
    assert ctrl._last_sealed_plan_payload is not None
    rows = [{"이름": "A"}, {"이름": "B"}]  # 실 plan 의 source schema 그대로
    _mount_rows(ctrl, rows)

    class Source:
        def records(self) -> list[dict]:
            return rows

    ctrl.datasource = Source()
    assert ctrl.vm is not None
    ctrl.vm.set_acquired(ctrl.datasource, rows)
    out = tmp_path / "delivery"
    out.mkdir()
    ctrl.set_output_folder(str(out))

    captured: dict = {}

    def fake_run(**kw):
        captured.update(kw)
        return DeliveryCompleted(
            output_directory=str(out),
            delivered=(
                DeliveredDocument(0, "rec-0", "a.hwpx", str(out / "a.hwpx"),
                                  "WRITE_NEW", "sha256:" + "0" * 64, ()),
                DeliveredDocument(1, "rec-1", "b.hwpx", str(out / "b.hwpx"),
                                  "WRITE_NEW", "sha256:" + "1" * 64, ()),
            ),
        )

    monkeypatch.setattr(sj, "run_managed_generation", fake_run)

    def forbidden(*args, **kwargs):
        pytest.fail("managed 갈래가 legacy generator 에 도달했다")

    monkeypatch.setattr(ctrl, "_generate_locked", forbidden)
    result = ctrl.generate(run_token="tk-1")
    assert result["ok"] is True, result.get("error")
    assert result["status"] == "completed", result
    assert (result["succeeded"], result["failed"], result["total"]) == (2, 0, 2)
    assert result["run_token"] == "tk-1"
    # 세션 사실이 재조립 없이 그대로 넘어갔다.
    assert captured["plan_payload"] is ctrl._last_sealed_plan_payload
    prep = ctrl._current_delivery_preparation
    assert prep is not None
    assert captured["ordered_raw_snapshots"] == prep.record_preparation.raw_records
    assert captured["resolved_delivery"] is prep.result
    # reader 는 실 authority 관찰이다 — 방금 봉인된 digest 와 동치(자기 비교가 아니다).
    assert captured["current_basis_digest_reader"]() == ctrl._last_sealed_basis_digest
    # 실행 증거가 작업대의 부차 축으로 남는다(S7 선행 없이 세션 요약만).
    assert _zone(ctrl)["historical_outcome"]["outcome_kind"] == "DOCUMENTS_DELIVERED"


def test_managed_read_back_failure_maps_to_a_distinct_loud_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S7-01(#823): 되읽기 실패 → legacy 키 집합 그대로의 실패 1건 결과(JobResultZone 무변경).

    안착은 전건 됐으므로 미착수는 0 이고 원장도 평소 경로로 기록된다 — 다른 것은 성공 수에서
    한 건이 빠지고 사유가 「만든 뒤 다시 읽어 확인」 실패로 재진술된다는 점이다.
    """
    import hwpxfiller.webapp.screen_job as sj
    from hwpxfiller.external.artifact_observation import ARTIFACT_DIGEST_MISMATCH
    from hwpxfiller.external.delivery_coordinator import DeliveredDocument
    from hwpxfiller.webapp.managed_generation import ManagedReadBackFailed

    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("select_job", {"name": WORK_REF})
    ctrl.dispatch("resolve_execution", {})
    rows = [{"이름": "A"}, {"이름": "B"}]
    _mount_rows(ctrl, rows)

    class Source:
        def records(self) -> list[dict]:
            return rows

    ctrl.datasource = Source()
    assert ctrl.vm is not None
    ctrl.vm.set_acquired(ctrl.datasource, rows)
    out = tmp_path / "delivery"
    out.mkdir()
    ctrl.set_output_folder(str(out))

    delivered = (
        DeliveredDocument(0, "rec-0", "a.hwpx", str(out / "a.hwpx"),
                          "WRITE_NEW", "sha256:" + "0" * 64, ()),
        DeliveredDocument(1, "rec-1", "b.hwpx", str(out / "b.hwpx"),
                          "WRITE_NEW", "sha256:" + "1" * 64, ()),
    )

    def fake_run(**kw):
        return ManagedReadBackFailed(
            code=ARTIFACT_DIGEST_MISMATCH,
            detail="b.hwpx 의 내용이 안착 기록과 다르다",
            failed_item_ordinal=1,
            delivered=delivered,
        )

    monkeypatch.setattr(sj, "run_managed_generation", fake_run)
    result = ctrl.generate(run_token="tk-rb")

    assert result["ok"] is True, result.get("error")
    assert result["status"] == "partiallyCompleted"
    assert result["level"] == "danger"
    # 안착은 전건 — 미착수 0, 시도 = 전체. 실패는 되읽기 1건뿐이다.
    assert (result["succeeded"], result["failed"], result["total"]) == (1, 1, 2)
    assert (result["unstarted"], result["attempted"]) == (0, 2)
    assert len(result["failures"]) == 1
    failure = result["failures"][0]
    prep = ctrl._current_delivery_preparation
    assert prep is not None
    # ordinal → 표시 index·파일 이름 투영은 실 준비의 것이다(중단 갈래와 같은 방식).
    assert failure["index"] == prep.record_preparation.ordered_model_indices[1]
    assert (
        failure["filename"] == prep.result.ordered_items[1].resolved_output_relative_path
    )
    assert failure["reason"] == "b.hwpx 의 내용이 안착 기록과 다르다"
    # 중단(부분 안착)과 문안이 갈린다 — 유지 안내가 아니라 확인 요청이다.
    assert ARTIFACT_DIGEST_MISMATCH in result["summary"]
    assert "앉은 문서는 그대로 유지됩니다" not in result["summary"]
    # 문서가 disk 에 있으므로 원장은 평소 경로로 기록된다(기록 실패 병기 없음).
    assert list(out.glob("fill-ledger-*.json")), "managed 원장이 기록되지 않았다"


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


# ── U3-03(#876) 「입력이 필요한 항목」 존 = 조치 필요만(분류표 전건 아님) ─────────────────────────
def test_input_requirements_zone_carries_only_action_required_items(tmp_path: Path) -> None:
    """혼재 분류표 → 존에는 BROKEN·NEW_ACTIVE_FIELD 만 실린다(링1 분류표는 그대로).

    술어는 링1 의 ``action_required`` 다 — 직렬화 경계가 분류값을 재해석하지 않는다.
    """
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    observation = ctrl.workbench_observation()
    mixed = tuple(
        InputRequirement(
            field_id=field_id,
            display_label=field_id,
            binding_state=state,
            exact_target=f"binding/{field_id}",
        )
        for field_id, state in (
            ("보존", PRESERVED),
            ("깨짐", BROKEN),
            ("신규", NEW_ACTIVE_FIELD),
            ("비활성", INACTIVE_ONLY),
        )
    )
    mixed_observation = dataclasses.replace(observation, input_requirements=mixed)
    zone = ctrl._serialize_observation(mixed_observation)

    assert [item["field_id"] for item in zone["input_requirements"]] == ["깨짐", "신규"]
    assert all(item["action_required"] is True for item in zone["input_requirements"])
    # 필터는 표시 경계 한 자리뿐 — 링1 분류표(전건)는 손대지 않는다.
    assert len(mixed_observation.input_requirements) == 4


def test_sealed_current_input_requirements_zone_is_empty(tmp_path: Path) -> None:
    """봉인 성공(전건 PRESERVED) → 조치 필요 0건이라 존은 빈 목록으로 나간다."""
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    observation = ctrl.workbench_observation()
    zone = _zone(ctrl)

    assert zone["execution_status_code"] == "CURRENT"
    # 링1 은 여전히 활성 누름틀 전건의 분류표를 든다 — 비워진 건 표시 경계다.
    assert observation.input_requirements, "봉인 성공 경로의 분류표가 비었다"
    assert all(item.binding_state == PRESERVED for item in observation.input_requirements)
    assert zone["input_requirements"] == []
    # 라벨 자체는 불변(구획을 세울지는 프런트가 표시 항목 수로 정한다).
    assert zone["input_requirements_label"] == "입력이 필요한 항목"


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
    """blank 는 **pre-guard 만** 잰다 — 미선택은 준비 부족이지 무결성 실패가 아니다(#775)."""
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.job_name = ""  # 미선택 → unsupported(조용히 비우지 않는다).
    zone = _zone(ctrl)
    assert zone["supported"] is False and zone["kind"] is None


# ── 무결성 예외를 「지원 안 함」으로 접지 않는다(#775) ────────────────────────────────────────────
class _RaisingBindingReview:
    """`current_binding_review` 가 context/무결성 예외를 던지는 seal 서비스 대역.

    실 경로 재현: `_binding_review_projection` → `read_current_field_binding_review` 는
    capture seam 과 달리 context-error 가드가 없어 예외가 존까지 올라온다.
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def current_binding_review(self, work_ref: str):
        raise self._exc


def _wire_raising_binding_review(ctrl: JobController, exc: Exception) -> None:
    # 분류표를 **읽는 조건**을 세운다(봉인 계획이 아닌 current-work 관찰).
    ctrl._last_fresh_observation = CurrentWorkExecutionObservation(
        work_authority_ref=WORK,
        current_sealability="DOMAIN_BLOCKED",
        observed_at=NOW.isoformat(),
    )
    ctrl._seal_execution = _RaisingBindingReview(exc)


def test_zone_surfaces_value_error_integrity_failure_as_context_error(
    tmp_path: Path,
) -> None:
    """ValueError 자손 무결성 예외(ExecutionStructureError)가 blank 로 접히지 않는다."""
    ctrl = _controller(tmp_path, with_binding=True)
    _wire_raising_binding_review(
        ctrl, ExecutionStructureError("v2 projection 이 깨졌습니다")
    )
    zone = _zone(ctrl)
    assert zone["supported"] is True  # blank(supported=False, kind=None)와 구분된다
    assert zone["kind"] == "context_error"
    assert zone["code"] == ExecutionStructureError.code
    assert zone["detail"] == "v2 projection 이 깨졌습니다"
    assert zone["user_fixable"] is False
    assert zone["primary_action"] == "RECOVER_CONTEXT"
    assert zone["create_action"]["enabled"] is False
    # 저장 폴더 사실은 관찰이 무너져도 실린다(U3-06 #879 계약 유지).
    assert "output_folder" in zone


def test_zone_surfaces_non_value_error_integrity_failure_without_killing_snapshot(
    tmp_path: Path,
) -> None:
    """ValueError 가 **아닌** 무결성 예외도 같은 결과 — 스냅샷 조립을 죽이지 않는다."""
    # 실 템플릿을 둔다 — 템플릿 부재면 pre-guard 가 blank 로 답해 이 축이 안 재진다.
    ctrl = _controller(tmp_path, with_binding=True, template_path=str(TEMPLATE_FIXTURE))
    exc = FieldBindingInputIntegrityError("binding input 무결성 위반")
    assert not isinstance(exc, ValueError)  # 옛 그물(except ValueError)이 못 잡던 절반
    ctrl.dispatch("select_job", {"name": WORK_REF})  # 실 스냅샷 조립 경로를 탄다
    _wire_raising_binding_review(ctrl, exc)
    zone = ctrl.snapshot()["workbench_observation"]
    assert zone["supported"] is True and zone["kind"] == "context_error"
    assert zone["code"] == FieldBindingInputIntegrityError.code
    assert zone["detail"] == "binding input 무결성 위반"
    assert zone["user_fixable"] is False


def test_zone_does_not_swallow_unexpected_exception(tmp_path: Path) -> None:
    """집합 밖 예외는 화면 값으로 번역하지 않고 그대로 전파한다(조용한 추측 금지)."""
    ctrl = _controller(tmp_path, with_binding=True)
    _wire_raising_binding_review(ctrl, RuntimeError("예기치 못한 실패"))
    with pytest.raises(RuntimeError):
        _zone(ctrl)


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


# ── 편집기 확정 동사의 근거 = REVIEW_BINDING 과 **같은 사실**(#911) ────────────────────────
def test_editor_confirm_pending_rises_with_the_review_binding_blocker(
    tmp_path: Path,
) -> None:
    """확정 대기는 관리 검토 blocker 와 **함께** 선다(양성 값).

    증거가 없는 동안에는 주장하지 않는다 — 관리 검토도 그때는 결속을 요구하지 않는다.
    """
    ctrl = _controller(tmp_path, with_binding=False)
    assert ctrl.editor_binding_confirm_pending(WORK_REF) is False, (
        "증거가 없는 세션은 확정 대기를 주장하지 않는다"
    )

    ctrl.dispatch("resolve_execution", {})
    assert "REVIEW_BINDING" in _zone(ctrl)["blockers"]
    assert ctrl.editor_binding_confirm_pending(WORK_REF) is True


def test_editor_confirm_pending_is_false_on_a_sealed_plan(tmp_path: Path) -> None:
    """봉인된 계획 위에서는 거짓이다(음성 값) — 확정할 것이 없는데 동사를 세우지 않는다.

    #911 의 거울상 결함이다. 이 값을 함께 재지 않으면 「무장 사유를 더한다」가 조용히
    「늘 무장한다」로 미끄러진다.
    """
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})

    assert "REVIEW_BINDING" not in _zone(ctrl)["blockers"]
    assert ctrl.editor_binding_confirm_pending(WORK_REF) is False


def test_editor_confirm_pending_is_false_for_another_work(tmp_path: Path) -> None:
    """세션 증거가 겨눈 작업이 아니면 거짓 — 남의 작업 상태를 이 세션 증거로 답하지 않는다."""
    ctrl = _controller(tmp_path, with_binding=False)
    ctrl.dispatch("resolve_execution", {})
    assert ctrl.editor_binding_confirm_pending(WORK_REF) is True

    assert ctrl.editor_binding_confirm_pending("다른작업") is False


def test_editor_confirm_pending_needs_the_seal_seam(tmp_path: Path) -> None:
    """seal 미배선이면 확정 대기는 거짓이다 — 없는 표면을 있다고 말하지 않는다."""
    ctrl = _controller(tmp_path, with_binding=False, wire_seal=False)
    assert ctrl.editor_binding_confirm_pending(WORK_REF) is False


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
        def apply_for_seated_context(job_name: str, change_token: str) -> tuple[dict, str]:
            assert job_name == WORK_REF and change_token == "token"
            return {"status": "applied", "is_current": True}, "app-applied"

    ctrl._template_change = AppliedTemplateChange()
    result = ctrl.dispatch("template_apply", {"change_token": "token"})

    assert result["status"] == "applied"
    assert ctrl._last_fresh_observation is not before
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"
