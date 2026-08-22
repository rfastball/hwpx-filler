"""Native-free values crossing the HWPX qualification port."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 런타임 cycle 방지 — execution_structure 가 이 모듈을 import 한다.
    from .execution_structure import ExecutionTemplateStructure


INSPECTION_CONTRACT_ERROR_CODE = "inspection-contract-error"
INSPECTION_ERROR_CODE = "inspection-error"


class TemplateInspectionContractError(RuntimeError):
    """External inspection evidence contradicts its pair-local contract."""


@dataclass(frozen=True)
class CandidateRevisionSnapshot:
    revision_id: str
    canonical_bytes: bytes


@dataclass(frozen=True)
class TemplateOption:
    id: str
    fields: tuple[str, ...] = ()
    label: str | None = None


@dataclass(frozen=True)
class TemplateSlot:
    id: str
    shared_fields: tuple[str, ...] = ()
    options: tuple[TemplateOption, ...] = ()
    label: str | None = None


@dataclass(frozen=True)
class TemplateStructure:
    root_fields: tuple[str, ...] = ()
    slots: tuple[TemplateSlot, ...] = ()


@dataclass(frozen=True)
class TemplateDiagnostic:
    kind: str
    message: str


@dataclass(frozen=True)
class QualificationInspection:
    structure: TemplateStructure | None
    diagnostics: tuple[TemplateDiagnostic, ...]
    #: composition-ready projection(#773). 같은 read-only inspection **한 번**에서 나온
    #: label-bearing execution structure다 — 두 번째 parse 도, 두 번째 Candidate 읽기도 없다.
    #: composition fact 를 못 내는 profile 은 None 을 둔다(그 profile 은 v1/v3 로 남는다).
    execution_structure: ExecutionTemplateStructure | None = None


TemplateInspectorPort = Callable[[bytes], QualificationInspection]


@dataclass(frozen=True)
class QualificationProfile:
    id: str
    inspect: TemplateInspectorPort


@dataclass(frozen=True)
class TemplateQualificationPassed:
    revision_id: str
    qualification_profile_id: str
    structure: TemplateStructure
    #: exact 같은 Candidate bytes·같은 inspection 에서 나온 composition-ready structure(#773).
    execution_structure: ExecutionTemplateStructure | None = None


@dataclass(frozen=True)
class TemplateQualificationFailed:
    revision_id: str
    qualification_profile_id: str
    diagnostics: tuple[TemplateDiagnostic, ...]


@dataclass(frozen=True)
class TemplateQualificationAttemptErrored:
    revision_id: str
    qualification_profile_id: str
    error_code: str


TemplateQualificationResult = (
    TemplateQualificationPassed
    | TemplateQualificationFailed
    | TemplateQualificationAttemptErrored
)


def qualify_template(
    snapshot: CandidateRevisionSnapshot,
    profile: QualificationProfile,
) -> TemplateQualificationResult:
    """Bind one read-only inspection outcome to its Candidate revision and profile."""
    try:
        inspection = profile.inspect(snapshot.canonical_bytes)
        structure = inspection.structure
        diagnostics = inspection.diagnostics
        execution_structure = inspection.execution_structure
    except TemplateInspectionContractError:
        return TemplateQualificationAttemptErrored(
            snapshot.revision_id,
            profile.id,
            INSPECTION_CONTRACT_ERROR_CODE,
        )
    except Exception:
        return TemplateQualificationAttemptErrored(
            snapshot.revision_id,
            profile.id,
            INSPECTION_ERROR_CODE,
        )

    if (structure is None and not diagnostics) or (
        structure is not None and bool(diagnostics)
    ):
        return TemplateQualificationAttemptErrored(
            snapshot.revision_id,
            profile.id,
            INSPECTION_CONTRACT_ERROR_CODE,
        )
    if structure is None:
        # FAIL 은 structure 를 안 낸다 — composition structure 가 딸려 오면 계약 위반이다.
        if execution_structure is not None:
            return TemplateQualificationAttemptErrored(
                snapshot.revision_id,
                profile.id,
                INSPECTION_CONTRACT_ERROR_CODE,
            )
        return TemplateQualificationFailed(
            snapshot.revision_id,
            profile.id,
            diagnostics,
        )
    # 두 view 가 같은 inspection 에서 나왔음을 구조로 확인한다 — product structure 가 어긋나면
    # label 과 composition fact 가 다른 사실을 말하는 것이라 조용히 넘기지 않는다.
    if (
        execution_structure is not None
        and execution_structure.product_structure != structure
    ):
        return TemplateQualificationAttemptErrored(
            snapshot.revision_id,
            profile.id,
            INSPECTION_CONTRACT_ERROR_CODE,
        )
    return TemplateQualificationPassed(
        snapshot.revision_id,
        profile.id,
        structure,
        execution_structure,
    )
