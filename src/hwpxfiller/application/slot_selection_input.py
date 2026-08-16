"""S5 입력 capture 경계 — SlotSelectionInput 합타입과 순수 capture 판정 (S4-10 · #680).

S5 에는 **complete effective selections(slot-bearing)** 또는 **explicit slotless evidence
(0-slot)** 만 넘어간다. `None` 을 slotless 의미로 쓰지 않는다 — 두 변형 중 하나가 명시된다.

이 모듈은 순수하다: store·fence·token·HWPX 를 모른다. fence 아래 context resolve 는
`external/slot_command_runner.py` 의 capture entry 가 지고, 여기서는 복원된 (context, config)
로 version 검증·resolution·slotless/complete 판정·digest 만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from hwpxfiller.application.slot_configuration_context import SlotConfigurationContext
from hwpxfiller.application.slot_reconciliation import resolve_slot_configuration
from hwpxfiller.application.work_slot_configuration import WorkSlotConfigurationDraft
from hwpxfiller.domain.slot_selection import (
    SlotSelectionSet,
    digest_selection_set,
)


class SlotSelectionCaptureError(Exception):
    """capture 실패 — `.code` 로 분기한다(context error 는 별도 계층)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SlotlessSelectionContext:
    """current Slot count 가 0 임을 증명한 exact current Application context.

    의미하지 않음: Configuration 미생성·Structure 복원 실패·unknown contract·Mapping/Data
    유효·legacy 허용. Configuration 이 없거나 detached selections 만 있어도 slot count 0 이면
    만들 수 있다.
    """

    work_id: str
    template_application_id: str
    selection_semantic_contract_id: str
    structure_projection_schema_version: str
    template_structure_digest: str
    source_configuration_version: int | None
    declared_selection_digest: str | None
    captured_at: str


@dataclass(frozen=True)
class SlotConfigurationSnapshot:
    """slot-bearing 이고 resolution 이 complete 인 effective selection 스냅샷."""

    work_id: str
    template_application_id: str
    source_configuration_version: int
    selection_semantic_contract_id: str
    structure_projection_schema_version: str
    effective_selections: SlotSelectionSet
    effective_selection_digest: str
    declared_selection_digest: str
    template_structure_digest: str
    captured_at: str


# None 을 slotless 로 쓰지 않는다 — 합타입은 두 변형 중 하나다.
SlotSelectionInput = SlotlessSelectionContext | SlotConfigurationSnapshot


def plan_capture(
    context: SlotConfigurationContext,
    config: WorkSlotConfigurationDraft | None,
    captured_at: str,
    *,
    expected_configuration_presence: bool | None = None,
    expected_configuration_version: int | None = None,
) -> SlotSelectionInput:
    """복원된 context 로 slotless 또는 complete snapshot 을 낸다(순수 5~8 단계).

    stale Application(단계 2)은 caller 의 context resolve 가 이미 거절한다. 여기서는 caller 가
    관찰한 Configuration 상태의 exact CAS(단계 5)·slotless/complete 판정(단계 7)만 한다:
    presence=True → Configuration 존재 + version 일치, presence=False → 부재(그 사이 생기면
    STALE), presence=None → CAS 없음(내부 caller). version 은 presence=True 일 때만 의미가 있다.
    digest 는 exact contract ID 로 slot-selection-canonical/v1 — detached 는 declared 에 들고
    effective 엔 빠진다.
    """
    contract_id = context.selection_semantic_contract_id
    actual_version = config.version if config is not None else None
    if expected_configuration_presence is True:
        # 관찰했던 Configuration 이 사라졌거나 version 이 어긋나면 STALE.
        if config is None or actual_version != expected_configuration_version:
            raise SlotSelectionCaptureError(
                "STALE_CONFIGURATION",
                f"expected present version {expected_configuration_version}, "
                f"current {actual_version}",
            )
    elif expected_configuration_presence is False:
        # 부재를 관찰했는데 그 사이 Configuration 이 생겼으면 STALE(캡처가 미관찰 선택을 담지 않게).
        if config is not None:
            raise SlotSelectionCaptureError(
                "STALE_CONFIGURATION",
                "expected absent Configuration but one now exists",
            )

    selections = config.selections if config is not None else SlotSelectionSet(())
    resolution = resolve_slot_configuration(
        selections, context.template_structure, context.selection_semantic_contract
    )

    if len(context.template_structure.slots) == 0:
        # slotless — Configuration presence·detached intent 는 실행 selection 의미를 안 바꾼다.
        return SlotlessSelectionContext(
            work_id=context.work_id,
            template_application_id=context.template_application_id,
            selection_semantic_contract_id=contract_id,
            structure_projection_schema_version=context.structure_projection_schema_version,
            template_structure_digest=context.template_structure_digest,
            source_configuration_version=actual_version,
            declared_selection_digest=(
                digest_selection_set(contract_id, selections)
                if config is not None
                else None
            ),
            captured_at=captured_at,
        )

    # slot-bearing: Configuration 존재 + resolution complete 만 스냅샷이 된다.
    if config is None or not resolution.slot_selections_complete:
        raise SlotSelectionCaptureError(
            "SLOT_CONFIGURATION_INCOMPLETE",
            "current selection 이 complete 하지 않아 snapshot 을 만들지 않는다",
        )
    return SlotConfigurationSnapshot(
        work_id=context.work_id,
        template_application_id=context.template_application_id,
        source_configuration_version=config.version,
        selection_semantic_contract_id=contract_id,
        structure_projection_schema_version=context.structure_projection_schema_version,
        effective_selections=resolution.effective_selections,
        effective_selection_digest=digest_selection_set(
            contract_id, resolution.effective_selections
        ),
        declared_selection_digest=digest_selection_set(contract_id, selections),
        template_structure_digest=context.template_structure_digest,
        captured_at=captured_at,
    )
