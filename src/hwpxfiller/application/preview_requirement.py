"""PreviewRequirement v1 정책 + semantic/value preview 경계 (SX-01 · #724 §6·§7 · #719 D6).

이 모듈은 **순수 application 계약**이다 — store/webapp/gui/pywebview 를 모르고, 새 durable state·
`current_plan_id`·UI-only validity 를 만들지 않는다. 어휘 문자열의 정본은
:mod:`hwpxfiller.application.document_creation_vocabulary` 이고 여기서는 **import 만** 한다
(``PREVIEW_REQUIREMENT_KINDS``·preview 라벨). 이 모듈이 소유하는 것 둘:

1. **PreviewRequirement 합타입 + v1 정책 matrix**(#724 §6) — 변경 종류(입력)를 받아
   ``NOT_REQUIRED | OPTIONAL | REQUIRED(reason, exact_basis_ref)`` 를 판정하는 순수 함수.
2. **semantic/value preview 경계 DTO**(#724 §7) — current Plan + representative/current VDR 의
   **사용자 투영**. 실제 생성된 결과(Artifact)·HWPX bytes·layout 이 **아니다**. 라벨은
   vocabulary preview 라벨이라 "실제 생성된 결과"처럼 읽히지 않는다.

**경계 규율 두 가지.**

- **Artifact/ManagedGenerationPlan 미import**(#724 §7·D6). preview 는 semantic/value projection 이지
  Artifact 가 아니다 — 그래서 이 모듈은 :mod:`hwpxfiller.application.generation_delivery` 의
  ``ManagedGenerationPlan``·resolved delivery·HWPX bytes 타입을 참조하지 않고 **opaque ref(문자열)**
  만 담는다. (docstring 이 그 이름들을 **언급**은 하지만 import 하지는 않는다 — 정적 단언은 AST
  import 검사로 한다.)
- **record-level 검토를 삼키지 않는다**(#724 §6). 여기서 판정하는 것은 **Work-level** preview
  approval 뿐이다. record별 값 검토는 :class:`hwpxfiller.domain.raw_data_record.RecordReviewEvidence`
  경계가 소유하고 이 Work-level approval 과 **합치지 않는다**. 그래서 :class:`WorkLevelPreviewApproval`
  은 record identity·raw_record_digest·review_basis_digest 를 **의도적으로 담지 않는다**.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from hwpxfiller.application.document_creation_vocabulary import (
    PREVIEW_REQUIREMENT_KINDS,
    SEMANTIC_PREVIEW_LABEL,
    VALUE_PREVIEW_LABEL,
)

# PreviewRequirement 종류 — vocabulary 정본에서 풀어 쓴다(재정의 아님).
NOT_REQUIRED, OPTIONAL, REQUIRED = PREVIEW_REQUIREMENT_KINDS


# ─── PreviewRequirement 합타입 ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PreviewNotRequired:
    """이 변경은 생성 전 확인을 요구하지 않는다."""

    kind: ClassVar[str] = NOT_REQUIRED


@dataclass(frozen=True)
class PreviewOptional:
    """확인은 도움이 되지만 강제하지 않는다(예: 같은 실행 의미에서 record selection 변경)."""

    kind: ClassVar[str] = OPTIONAL


@dataclass(frozen=True)
class PreviewRequired:
    """생성 전 확인이 필요하다 — ``reason`` 과 ``exact_basis_ref``(opaque ref)를 담는다.

    빈 reason·빈 basis ref 는 **hollow requirement** 라 시끄럽게 거절한다(조용히 틀리지 않는다):
    "확인이 필요하다"고 말하면서 무엇을 확인해야 하는지 근거가 없으면 계약이 비어 있다.
    """

    reason: str
    exact_basis_ref: str
    kind: ClassVar[str] = REQUIRED

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or self.reason == "":
            raise ValueError("REQUIRED preview 는 reason 이 필요하다")
        if not isinstance(self.exact_basis_ref, str) or self.exact_basis_ref == "":
            raise ValueError("REQUIRED preview 는 exact_basis_ref(opaque ref)가 필요하다")


PreviewRequirement = PreviewNotRequired | PreviewOptional | PreviewRequired


# ─── v1 정책 matrix 입력(변경 종류) ────────────────────────────────────────────────────────
# 변경 종류 코드는 이 모듈이 소유한다(vocabulary 는 requirement 종류만 소유). REQUIRED 행의
# reason 은 변경 종류 코드를 그대로 쓴다 — 왜 확인이 필요한지가 곧 변경 종류다.
GENERAL_OPTION_SELECTION = "GENERAL_OPTION_SELECTION"
RECORD_SELECTION_CHANGE_SAME_EXECUTION = "RECORD_SELECTION_CHANGE_SAME_EXECUTION"
NEW_WORK_FIRST_RUN = "NEW_WORK_FIRST_RUN"
TEMPLATE_APPLICATION_CHANGED_FIRST_RUN = "TEMPLATE_APPLICATION_CHANGED_FIRST_RUN"
ACTIVE_BINDING_OUTPUT_IMPACT_CHANGE = "ACTIVE_BINDING_OUTPUT_IMPACT_CHANGE"
DESTRUCTIVE_DELIVERY_POLICY = "DESTRUCTIVE_DELIVERY_POLICY"
DETACHED_INACTIVE_ONLY_SAME_BASIS = "DETACHED_INACTIVE_ONLY_SAME_BASIS"

#: v1 정책 matrix 의 7 개 변경 종류(정의 순서 = 이슈 §6 표 순서).
WORKBENCH_CHANGE_KINDS: tuple[str, ...] = (
    GENERAL_OPTION_SELECTION,
    RECORD_SELECTION_CHANGE_SAME_EXECUTION,
    NEW_WORK_FIRST_RUN,
    TEMPLATE_APPLICATION_CHANGED_FIRST_RUN,
    ACTIVE_BINDING_OUTPUT_IMPACT_CHANGE,
    DESTRUCTIVE_DELIVERY_POLICY,
    DETACHED_INACTIVE_ONLY_SAME_BASIS,
)

#: REQUIRED 를 내는 변경 종류(전부 exact_basis_ref 를 요구한다).
REQUIRED_CHANGE_KINDS: frozenset[str] = frozenset(
    {
        NEW_WORK_FIRST_RUN,
        TEMPLATE_APPLICATION_CHANGED_FIRST_RUN,
        ACTIVE_BINDING_OUTPUT_IMPACT_CHANGE,
        DESTRUCTIVE_DELIVERY_POLICY,
    }
)


def evaluate_preview_requirement(
    change_kind: str, *, exact_basis_ref: str | None = None
) -> PreviewRequirement:
    """v1 정책 matrix(#724 §6) — 변경 종류 → PreviewRequirement 순수 판정.

    ::

        일반 Option 선택                              → NOT_REQUIRED
        동일 실행 의미에서 record selection 변경        → OPTIONAL
        새 Work 첫 실행                               → REQUIRED
        Template Application 변경 뒤 첫 실행           → REQUIRED
        output-impact Active Binding 의미 변경         → REQUIRED
        파괴적 delivery policy(OVERWRITE_EXPLICIT)     → REQUIRED
        detached/inactive-only same basis             → NOT_REQUIRED(기존 approval 재사용 가능)

    마지막 행은 effective basis 가 바뀌지 않으므로 **새 확인을 강제하지 않는다** — 같은 basis 의
    기존 Work-level approval(:class:`WorkLevelPreviewApproval`)이 그대로 유효하다
    (:func:`work_level_approval_still_valid` 로 판정). 그래서 requirement 값은 ``NOT_REQUIRED`` 다.

    REQUIRED 행은 ``exact_basis_ref``(opaque ref)를 **반드시** 받는다 — 없으면 근거 없는 요구라
    ``ValueError`` 로 닫는다(조용히 틀리지 않는다). 이 판정은 record-level 검토와 무관하다 —
    record 값 검토는 ``RecordReviewEvidence`` 경계 소관이다.
    """
    if change_kind not in WORKBENCH_CHANGE_KINDS:
        raise ValueError(f"미지원 change_kind: {change_kind!r}")
    if change_kind == GENERAL_OPTION_SELECTION:
        return PreviewNotRequired()
    if change_kind == DETACHED_INACTIVE_ONLY_SAME_BASIS:
        # same effective basis → 기존 approval 재사용 가능 → 새 확인 강제 없음.
        return PreviewNotRequired()
    if change_kind == RECORD_SELECTION_CHANGE_SAME_EXECUTION:
        return PreviewOptional()
    # 나머지 4 행은 REQUIRED — exact_basis_ref 가 반드시 있어야 한다.
    if exact_basis_ref is None or exact_basis_ref == "":
        raise ValueError(
            f"{change_kind} 는 REQUIRED preview 라 exact_basis_ref 가 필요하다"
        )
    return PreviewRequired(reason=change_kind, exact_basis_ref=exact_basis_ref)


# ─── Work-level preview approval(record-level 검토와 분리된 경계) ────────────────────────────
@dataclass(frozen=True)
class WorkLevelPreviewApproval:
    """Work-level preview approval — exact_basis_ref(opaque ref)에 결속.

    **record별 값 검토와 합치지 않는다**(#724 §6). record identity·raw_record_digest·
    review_basis_digest 를 **의도적으로 담지 않는다** — 그것은
    :class:`hwpxfiller.domain.raw_data_record.RecordReviewEvidence` 의 경계다. 이 approval 은
    "이 basis 의 생성 내용을 사용자가 확인했다"만 증언하고, record별 검토 상태는 삼키지 않는다.
    """

    exact_basis_ref: str
    approved_at: str

    def __post_init__(self) -> None:
        for name in ("exact_basis_ref", "approved_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or value == "":
                raise ValueError(f"{name} 는 비어 있지 않은 문자열이어야 한다")


def work_level_approval_still_valid(
    approval: WorkLevelPreviewApproval, current_exact_basis_ref: str
) -> bool:
    """기존 Work-level approval 이 현재 basis 에서 재사용 가능한지 — basis ref 동일 여부로만 판정.

    detached/inactive-only same-basis 변화에서 effective basis 가 그대로면 이 함수가 ``True`` 를
    내어 새 REQUIRED preview 없이 기존 approval 을 재사용한다(#724 §6). record identity 를 보지
    않는다 — record 검토는 별도 축이다.
    """
    return approval.exact_basis_ref == current_exact_basis_ref


# ─── semantic/value preview 경계 DTO(#724 §7 · D6) ──────────────────────────────────────────
SEMANTIC_PREVIEW = "SEMANTIC"
VALUE_PREVIEW = "VALUE"

#: preview 종류 → vocabulary 라벨. 라벨은 "확인" 계열이라 "실제 생성된 결과"(Artifact)처럼 읽히지 않는다.
_PREVIEW_LABEL_BY_KIND: dict[str, str] = {
    SEMANTIC_PREVIEW: SEMANTIC_PREVIEW_LABEL,
    VALUE_PREVIEW: VALUE_PREVIEW_LABEL,
}


@dataclass(frozen=True)
class SemanticValuePreviewProjection:
    """current Plan + representative/current VDR 의 **사용자 투영** — Artifact 가 아니다(#724 §7).

    ::

        semantic/value preview
        = current Plan + representative/current VDR 의 사용자 투영
        ≠ HWPX bytes ≠ actual layout ≠ Artifact ≠ Artifact View

    **opaque ref(문자열)만** 담는다 — 실제 Plan/VDR 객체나 ``ManagedGenerationPlan``/HWPX bytes 를
    참조하지 않는다. ``label`` 은 vocabulary preview 라벨이라 실제 생성 결과처럼 보이지 않는다.
    :data:`is_artifact` 는 항상 ``False`` — 이 DTO 가 Artifact 표현이 아님을 타입 수준에서 못박는다.
    """

    preview_kind: str  # SEMANTIC | VALUE
    label: str
    current_plan_ref: str  # opaque ref to current Sealed Plan(객체·bytes 아님)
    representative_vdr_ref: str | None = None
    is_artifact: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if self.preview_kind not in _PREVIEW_LABEL_BY_KIND:
            raise ValueError(f"미지원 preview_kind: {self.preview_kind!r}")
        expected = _PREVIEW_LABEL_BY_KIND[self.preview_kind]
        if self.label != expected:
            raise ValueError(
                f"{self.preview_kind} preview 라벨은 {expected!r} 여야 한다(vocabulary 정본)"
            )
        if not isinstance(self.current_plan_ref, str) or self.current_plan_ref == "":
            raise ValueError("current_plan_ref(opaque ref)는 비어 있지 않은 문자열이어야 한다")
        if self.representative_vdr_ref is not None and (
            not isinstance(self.representative_vdr_ref, str)
            or self.representative_vdr_ref == ""
        ):
            raise ValueError("representative_vdr_ref 는 None 이거나 비어 있지 않은 문자열이어야 한다")


def build_semantic_value_preview(
    preview_kind: str,
    *,
    current_plan_ref: str,
    representative_vdr_ref: str | None = None,
) -> SemanticValuePreviewProjection:
    """preview 종류 + opaque ref → projection DTO. 라벨은 vocabulary 정본에서 자동 부여한다."""
    if preview_kind not in _PREVIEW_LABEL_BY_KIND:
        raise ValueError(f"미지원 preview_kind: {preview_kind!r}")
    return SemanticValuePreviewProjection(
        preview_kind=preview_kind,
        label=_PREVIEW_LABEL_BY_KIND[preview_kind],
        current_plan_ref=current_plan_ref,
        representative_vdr_ref=representative_vdr_ref,
    )
