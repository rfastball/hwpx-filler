"""session-scoped RunDeliveryIntent + delivery resolver 어댑터 (SX-01 · #724 §8 · #719 D5).

순수 계약만 검증한다 — 실 파일 write 없이, resolver 시그니처가 Plan/VDR digest 를 delivery 인자와
**독립한 입력**으로 다룸을 계약 단언으로 고정한다.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from hwpxfiller.application.document_creation_vocabulary import (
    COLLISION_POLICIES,
    DEFAULT_COLLISION_POLICY,
)
from hwpxfiller.application.generation_delivery import (
    FAIL_ON_EXISTING,
    OVERWRITE_EXISTING,
    ResolvedGenerationDeliveryPlan,
    resolve_generation_delivery_plan,
)
import hwpxfiller.application.run_delivery_intent as run_delivery_intent_module
from hwpxfiller.application.run_delivery_intent import (
    ADD_SUFFIX,
    FAIL,
    OVERWRITE_EXPLICIT,
    DeliveryResolutionInputs,
    RunDeliveryIntent,
    map_run_delivery_intent_to_resolution_inputs,
)


# ─── 기본 OVERWRITE_EXPLICIT — 파괴 승인은 의도가 아니라 처분이 요구한다(U4 계열2-27) ────────
def test_default_collision_is_overwrite_and_says_so():
    intent = RunDeliveryIntent(output_directory="C:/out")
    assert intent.collision_policy == DEFAULT_COLLISION_POLICY == OVERWRITE_EXPLICIT
    assert intent.is_destructive is True


def test_destructive_intent_is_only_a_restatement_of_the_chosen_policy():
    """의도가 파괴적인 것과 **이번 delivery 가 실제로 무엇을 덮어쓰는가**는 다른 사실이다.

    기본이 덮어쓰기가 된 뒤 ``is_destructive`` 는 거의 언제나 참이라 그 자체로는 아무것도
    판정하지 못한다 — 고른 정책의 재진술일 뿐이다. 실제 파괴 집합은 파일 시스템을 본 쪽만
    말할 수 있고 이 모듈은 그것을 보지 않는다. 종전 이 자리를 지던 단언(승인 요구를 세우는
    ``preview_requirement`` 가 이 모듈을 읽지 않는다)은 그 모듈이 #957 슬라이스 ③ 에서
    사라져 겨눌 대상이 없다 — 여전히 참인 사실, 곧 **의도 모듈의 무지**로 다시 겨눈다.
    """
    intent = RunDeliveryIntent(output_directory="C:/out", collision_policy=ADD_SUFFIX)
    assert intent.is_destructive is False
    source = inspect.getsource(run_delivery_intent_module)
    for probe in ("os.path", "pathlib", "Path(", "exists(", "listdir", "scandir"):
        assert probe not in source, f"session 의도 모듈이 파일 시스템을 관측한다: {probe}"


def test_collision_policy_vocabulary_is_from_single_source():
    assert (ADD_SUFFIX, FAIL, OVERWRITE_EXPLICIT) == COLLISION_POLICIES


def test_unknown_collision_policy_rejected():
    with pytest.raises(ValueError):
        RunDeliveryIntent(output_directory="C:/out", collision_policy="NOPE")


def test_empty_output_directory_rejected():
    with pytest.raises(ValueError):
        RunDeliveryIntent(output_directory="")


# ─── 어댑터 사상 ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("collision", "expected_overwrite"),
    [
        (OVERWRITE_EXPLICIT, OVERWRITE_EXISTING),
        (FAIL, FAIL_ON_EXISTING),
        (ADD_SUFFIX, FAIL_ON_EXISTING),  # on-disk add-suffix 어휘 부재 → 보수적 비파괴 사상(확인 필요)
    ],
)
def test_adapter_maps_collision_to_overwrite_policy(collision, expected_overwrite):
    intent = RunDeliveryIntent(output_directory="C:/out/dir", collision_policy=collision)
    inputs = map_run_delivery_intent_to_resolution_inputs(intent)
    assert isinstance(inputs, DeliveryResolutionInputs)
    assert inputs.output_directory_basis == "C:/out/dir"
    assert inputs.overwrite_policy == expected_overwrite


def test_only_explicit_overwrite_maps_to_destructive_disposition():
    # ADD_SUFFIX·FAIL 은 파괴적 disposition 으로 사상되지 않는다.
    for collision in (ADD_SUFFIX, FAIL):
        inputs = map_run_delivery_intent_to_resolution_inputs(
            RunDeliveryIntent(output_directory="C:/out", collision_policy=collision)
        )
        assert inputs.overwrite_policy != OVERWRITE_EXISTING


# ─── Plan/VDR identity 불참(계약 단언) ──────────────────────────────────────────────────────
def test_intent_has_no_digest_and_no_plan_or_vdr_fields():
    field_names = {f.name for f in dataclasses.fields(RunDeliveryIntent)}
    assert field_names == {"output_directory", "collision_policy"}
    # digest·plan·vdr 어느 것도 intent identity 에 들어가지 않는다.
    for f in field_names:
        lowered = f.lower()
        assert "digest" not in lowered
        assert "plan" not in lowered
        assert "vdr" not in lowered


def test_resolver_treats_delivery_and_plan_vdr_as_independent_inputs():
    # resolver 시그니처: delivery 인자(output_directory_basis·overwrite_policy)와 Plan/VDR 인자
    # (sealed_execution_plan·ordered_validated_records)가 서로 독립한 파라미터다. 따라서
    # RunDeliveryIntent 를 바꿔 delivery 인자만 갈아끼워도 Plan/VDR 입력은 손대지 않는다.
    params = inspect.signature(resolve_generation_delivery_plan).parameters
    assert "output_directory_basis" in params
    assert "overwrite_policy" in params
    assert "sealed_execution_plan" in params
    assert "ordered_validated_records" in params
    # 어댑터가 채우는 것은 delivery 인자뿐이다.
    delivery_fields = {f.name for f in dataclasses.fields(DeliveryResolutionInputs)}
    assert delivery_fields == {"output_directory_basis", "overwrite_policy"}
    assert "sealed_execution_plan" not in delivery_fields
    assert "ordered_validated_records" not in delivery_fields


def test_resolved_plan_echoes_bound_plan_digest_as_input_identity():
    # ResolvedGenerationDeliveryPlan 은 bound_plan_semantic_digest(Plan identity)를 담는다 —
    # Plan digest 는 resolver 입력에서 온 것이지 delivery intent 에서 파생되지 않는다.
    plan_fields = {f.name for f in dataclasses.fields(ResolvedGenerationDeliveryPlan)}
    assert "bound_plan_semantic_digest" in plan_fields
