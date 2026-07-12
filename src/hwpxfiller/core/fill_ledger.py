"""생성 원장 척추 — 매핑 전건 커버와 구조 드리프트의 순수 파생.

별도 스냅샷을 저장하지 않는다. 사람이 확정한 매핑 커버가 기준선이고, 현재 템플릿
누름틀과의 대칭차가 곧 템플릿-구조 드리프트다. 소스-구조와 값 공란은 서로 다른
상태축으로 유지해 템플릿 드리프트만 하드게이트하고 값 공란은 ADR-E 확인을 보존한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from .engine import HwpxEngine
from .mapping import MappingProfile


class StructureState(str, Enum):
    """구조 이상 축. 템플릿과 소스의 처방이 달라 합쳐 버리지 않는다."""

    OK = "ok"
    TEMPLATE_DRIFT = "template_drift"
    SOURCE_DRIFT = "source_drift"
    TEMPLATE_AND_SOURCE_DRIFT = "template_and_source_drift"


class ValueState(str, Enum):
    """레코드 값 축(구조 드리프트와 독립, ADR-E 확인 대상)."""

    OK = "ok"
    EMPTY = "empty"


@dataclass(frozen=True)
class TemplateStructureDrift:
    """현재 템플릿 누름틀과 매핑 커버의 양방향 대칭차."""

    template_only: "tuple[str, ...]" = ()
    mapping_only: "tuple[str, ...]" = ()
    conflicting: "tuple[str, ...]" = ()
    read_error: str = ""

    @property
    def has_drift(self) -> bool:
        return bool(self.template_only or self.mapping_only or self.conflicting or self.read_error)

    @property
    def introduced(self) -> "tuple[str, ...]":
        """템플릿에 새로 유입됐으나 매핑이 커버하지 않는 필드."""
        return self.template_only

    @property
    def removed(self) -> "tuple[str, ...]":
        """매핑 계약에는 있으나 현재 템플릿에서 소멸한 필드."""
        return self.mapping_only

    @property
    def symmetric_difference(self) -> "set[str]":
        return set(self.template_only) | set(self.mapping_only)

    @property
    def template_uncovered(self) -> "tuple[str, ...]":
        """방향을 드러내는 별칭: ``T - C``."""
        return self.template_only

    @property
    def mapping_orphaned(self) -> "tuple[str, ...]":
        """방향을 드러내는 별칭: ``C - T``."""
        return self.mapping_only


def template_structure_drift(
    template_fields: "Iterable[str]", mapping: MappingProfile
) -> TemplateStructureDrift:
    """``현재 템플릿 Δ effective mapping 커버``를 순서 안정적으로 계산한다."""
    template_order = list(dict.fromkeys(template_fields))
    cover_order = mapping.cover_fields()
    template_set = set(template_order)
    cover_set = set(cover_order)
    return TemplateStructureDrift(
        template_only=tuple(f for f in template_order if f not in cover_set),
        mapping_only=tuple(f for f in cover_order if f not in template_set),
        conflicting=tuple(mapping.coverage_conflicts()),
    )


# 간결한 호출명도 제공한다. L2가 원장 행을 확장할 때 같은 seam을 그대로 소비한다.
mapping_drift = template_structure_drift


def template_path_drift(path: "str", mapping: MappingProfile) -> TemplateStructureDrift:
    """HWPX 경로를 매 호출 다시 읽어 구조 드리프트를 fail-closed로 계산한다.

    단건 실행·매트릭스·CLI가 공유하는 경계다. 파일 부재/손상/파싱 실패를 정상
    빈 템플릿으로 오인하지 않고 ``read_error`` 로 반환한다.
    """
    if not path:
        return TemplateStructureDrift(read_error="템플릿 경로가 비어 있습니다.")
    try:
        fields = HwpxEngine().required_fields(path)
    except Exception as exc:  # noqa: BLE001 - 구조를 증명 못 하면 fail-closed
        return TemplateStructureDrift(read_error=str(exc))
    return template_structure_drift(fields, mapping)


@dataclass(frozen=True)
class FillLedger:
    """생성 전 구조/값 상태의 최소 원장. L2 export가 확장할 척추."""

    template_drift: TemplateStructureDrift = field(default_factory=TemplateStructureDrift)
    missing_sources: "tuple[str, ...]" = ()
    empty_values: "tuple[str, ...]" = ()

    @property
    def structure_state(self) -> StructureState:
        template_bad = self.template_drift.has_drift
        source_bad = bool(self.missing_sources)
        if template_bad and source_bad:
            return StructureState.TEMPLATE_AND_SOURCE_DRIFT
        if template_bad:
            return StructureState.TEMPLATE_DRIFT
        if source_bad:
            return StructureState.SOURCE_DRIFT
        return StructureState.OK

    @property
    def value_state(self) -> ValueState:
        return ValueState.EMPTY if self.empty_values else ValueState.OK

    @property
    def template_structure_drift(self) -> bool:
        return self.template_drift.has_drift

    @property
    def source_structure_drift(self) -> bool:
        return bool(self.missing_sources)


def build_fill_ledger(
    template_fields: "Iterable[str]",
    mapping: MappingProfile,
    *,
    source_fields: "Iterable[str] | None" = None,
    empty_values: "Iterable[str]" = (),
) -> FillLedger:
    """구조/값 축을 한 번에 파생한다.

    소스의 추가 열은 정상이다. 매핑이 요구하는 소스가 사라진 경우만 소스-구조
    드리프트이며, 이는 loud 진단이되 템플릿 하드게이트와 달리 실행 하드락 사유가 아니다.
    """
    missing_sources: "tuple[str, ...]" = ()
    if source_fields is not None:
        available = set(source_fields)
        required = list(dict.fromkeys(s for m in mapping.mappings if not m.is_blank for s in m.sources))
        missing_sources = tuple(s for s in required if s not in available)
    return FillLedger(
        template_drift=template_structure_drift(template_fields, mapping),
        missing_sources=missing_sources,
        empty_values=tuple(dict.fromkeys(empty_values)),
    )
