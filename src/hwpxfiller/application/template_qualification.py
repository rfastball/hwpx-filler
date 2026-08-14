"""Native-free values crossing the HWPX qualification port."""

from __future__ import annotations

from dataclasses import dataclass


class TemplateInspectionContractError(RuntimeError):
    """External inspection evidence contradicts its pair-local contract."""


@dataclass(frozen=True)
class TemplateOption:
    id: str
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateSlot:
    id: str
    shared_fields: tuple[str, ...] = ()
    options: tuple[TemplateOption, ...] = ()


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
