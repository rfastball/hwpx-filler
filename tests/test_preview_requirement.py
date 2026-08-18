"""PreviewRequirement v1 정책 matrix + semantic/value preview 경계 (SX-01 · #724 §6·§7).

순수 application 계약만 검증한다(store·webapp 무관). Artifact/ManagedGenerationPlan 미import 는
AST import 검사로 정적 단언한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import hwpxfiller.application.preview_requirement as pr_module
from hwpxfiller.application.document_creation_vocabulary import (
    PREVIEW_REQUIREMENT_KINDS,
    SEMANTIC_PREVIEW_LABEL,
    VALUE_PREVIEW_LABEL,
)
from hwpxfiller.application.preview_requirement import (
    ACTIVE_BINDING_OUTPUT_IMPACT_CHANGE,
    DESTRUCTIVE_DELIVERY_POLICY,
    DETACHED_INACTIVE_ONLY_SAME_BASIS,
    GENERAL_OPTION_SELECTION,
    NEW_WORK_FIRST_RUN,
    NOT_REQUIRED,
    OPTIONAL,
    RECORD_SELECTION_CHANGE_SAME_EXECUTION,
    REQUIRED,
    SEMANTIC_PREVIEW,
    TEMPLATE_APPLICATION_CHANGED_FIRST_RUN,
    VALUE_PREVIEW,
    WORKBENCH_CHANGE_KINDS,
    PreviewNotRequired,
    PreviewOptional,
    PreviewRequired,
    SemanticValuePreviewProjection,
    WorkLevelPreviewApproval,
    build_semantic_value_preview,
    evaluate_preview_requirement,
    work_level_approval_still_valid,
)

_BASIS = "opaque-basis-ref-abc123"


# ─── 7 행 정책 matrix ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("change_kind", "expected_kind", "expected_reason"),
    [
        (GENERAL_OPTION_SELECTION, NOT_REQUIRED, None),
        (RECORD_SELECTION_CHANGE_SAME_EXECUTION, OPTIONAL, None),
        (NEW_WORK_FIRST_RUN, REQUIRED, NEW_WORK_FIRST_RUN),
        (
            TEMPLATE_APPLICATION_CHANGED_FIRST_RUN,
            REQUIRED,
            TEMPLATE_APPLICATION_CHANGED_FIRST_RUN,
        ),
        (
            ACTIVE_BINDING_OUTPUT_IMPACT_CHANGE,
            REQUIRED,
            ACTIVE_BINDING_OUTPUT_IMPACT_CHANGE,
        ),
        (DESTRUCTIVE_DELIVERY_POLICY, REQUIRED, DESTRUCTIVE_DELIVERY_POLICY),
        (DETACHED_INACTIVE_ONLY_SAME_BASIS, NOT_REQUIRED, None),
    ],
)
def test_policy_matrix_all_seven_rows(change_kind, expected_kind, expected_reason):
    result = evaluate_preview_requirement(change_kind, exact_basis_ref=_BASIS)
    assert result.kind == expected_kind
    if expected_kind == REQUIRED:
        assert isinstance(result, PreviewRequired)
        assert result.reason == expected_reason
        assert result.exact_basis_ref == _BASIS
    elif expected_kind == OPTIONAL:
        assert isinstance(result, PreviewOptional)
    else:
        assert isinstance(result, PreviewNotRequired)


def test_matrix_covers_exactly_seven_kinds():
    assert len(WORKBENCH_CHANGE_KINDS) == 7
    assert len(set(WORKBENCH_CHANGE_KINDS)) == 7


def test_required_kinds_come_from_vocabulary():
    # 종류 어휘는 vocabulary 정본에서 온다(재정의 아님).
    assert (NOT_REQUIRED, OPTIONAL, REQUIRED) == PREVIEW_REQUIREMENT_KINDS


@pytest.mark.parametrize(
    "change_kind",
    [
        NEW_WORK_FIRST_RUN,
        TEMPLATE_APPLICATION_CHANGED_FIRST_RUN,
        ACTIVE_BINDING_OUTPUT_IMPACT_CHANGE,
        DESTRUCTIVE_DELIVERY_POLICY,
    ],
)
def test_required_without_basis_ref_is_rejected(change_kind):
    # hollow requirement 금지: 근거 없는 REQUIRED 는 시끄럽게 거절한다.
    with pytest.raises(ValueError):
        evaluate_preview_requirement(change_kind, exact_basis_ref=None)
    with pytest.raises(ValueError):
        evaluate_preview_requirement(change_kind, exact_basis_ref="")


def test_non_required_ignores_missing_basis_ref():
    # NOT_REQUIRED/OPTIONAL 은 basis ref 없이도 판정된다.
    assert evaluate_preview_requirement(GENERAL_OPTION_SELECTION).kind == NOT_REQUIRED
    assert (
        evaluate_preview_requirement(RECORD_SELECTION_CHANGE_SAME_EXECUTION).kind
        == OPTIONAL
    )
    assert (
        evaluate_preview_requirement(DETACHED_INACTIVE_ONLY_SAME_BASIS).kind
        == NOT_REQUIRED
    )


def test_unknown_change_kind_rejected():
    with pytest.raises(ValueError):
        evaluate_preview_requirement("NOPE", exact_basis_ref=_BASIS)


def test_preview_required_rejects_empty_fields():
    with pytest.raises(ValueError):
        PreviewRequired(reason="", exact_basis_ref=_BASIS)
    with pytest.raises(ValueError):
        PreviewRequired(reason=NEW_WORK_FIRST_RUN, exact_basis_ref="")


# ─── Work-level approval 재사용(same basis) + record-level 분리 ──────────────────────────────
def test_work_level_approval_reused_on_same_basis():
    approval = WorkLevelPreviewApproval(exact_basis_ref=_BASIS, approved_at="2026-08-18T00:00:00")
    assert work_level_approval_still_valid(approval, _BASIS) is True
    assert work_level_approval_still_valid(approval, "other-basis") is False


def test_work_level_approval_does_not_carry_record_identity():
    # record-level 검토(RecordReviewEvidence)를 삼키지 않는다 — record 축 필드가 없어야 한다.
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(WorkLevelPreviewApproval)}
    assert field_names == {"exact_basis_ref", "approved_at"}
    for forbidden in ("record_identity", "raw_record_digest", "review_basis_digest"):
        assert forbidden not in field_names


# ─── semantic/value preview 경계 DTO ────────────────────────────────────────────────────────
def test_semantic_preview_uses_vocabulary_label():
    proj = build_semantic_value_preview(SEMANTIC_PREVIEW, current_plan_ref="plan-ref-1")
    assert proj.label == SEMANTIC_PREVIEW_LABEL
    assert proj.preview_kind == SEMANTIC_PREVIEW
    assert proj.current_plan_ref == "plan-ref-1"
    assert proj.representative_vdr_ref is None
    assert proj.is_artifact is False


def test_value_preview_uses_vocabulary_label():
    proj = build_semantic_value_preview(
        VALUE_PREVIEW, current_plan_ref="plan-ref-1", representative_vdr_ref="vdr-ref-9"
    )
    assert proj.label == VALUE_PREVIEW_LABEL
    assert proj.representative_vdr_ref == "vdr-ref-9"


def test_preview_projection_rejects_mismatched_label():
    with pytest.raises(ValueError):
        SemanticValuePreviewProjection(
            preview_kind=SEMANTIC_PREVIEW,
            label=VALUE_PREVIEW_LABEL,  # 종류와 라벨 불일치
            current_plan_ref="plan-ref-1",
        )


def test_preview_projection_rejects_empty_plan_ref():
    with pytest.raises(ValueError):
        build_semantic_value_preview(SEMANTIC_PREVIEW, current_plan_ref="")


def test_preview_projection_carries_only_refs_not_bytes():
    # opaque ref(문자열)만 담는다 — bytes/객체 필드가 없어야 한다.
    import dataclasses

    field_types = {f.name: f.type for f in dataclasses.fields(SemanticValuePreviewProjection)}
    assert set(field_types) == {"preview_kind", "label", "current_plan_ref", "representative_vdr_ref"}


# ─── Artifact/ManagedGenerationPlan 미import 정적 단언(AST import 검사) ──────────────────────
def _imported_module_names(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
    return modules


def _imported_symbol_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_module_does_not_import_artifact_or_managed_plan():
    source = Path(pr_module.__file__).read_text(encoding="utf-8")
    modules = _imported_module_names(source)
    symbols = _imported_symbol_names(source)

    # generation_delivery(ManagedGenerationPlan·resolved delivery·HWPX 타입 소유)를 import 하지 않는다.
    assert "hwpxfiller.application.generation_delivery" not in modules
    assert not any("generation_delivery" in m for m in modules)
    # Artifact/ManagedGenerationPlan/ResolvedGenerationDeliveryPlan 심볼을 import 하지 않는다.
    for forbidden in (
        "ManagedGenerationPlan",
        "ResolvedGenerationDeliveryPlan",
        "MaterializationInput",
    ):
        assert forbidden not in symbols
    assert not any("Artifact" in s for s in symbols)


def test_module_only_imports_vocabulary_from_project():
    source = Path(pr_module.__file__).read_text(encoding="utf-8")
    modules = _imported_module_names(source)
    project_modules = {m for m in modules if m.startswith("hwpxfiller")}
    assert project_modules == {"hwpxfiller.application.document_creation_vocabulary"}
