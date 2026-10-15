"""작업 꾸러미 내보내기의 조립 — 작업 여러 개를 manifest 와 템플릿 bytes 로 모은다(#1188 WP-03).

무엇을 싣고 무엇을 싣지 않는지는 manifest 값 모델(:mod:`hwpxfiller.domain.work_package`)이 고정한다.
이 모듈은 저장된 작업에서 그 값을 **사본으로** 짓는다 — 저장된 작업은 건드리지 않는다.

- 템플릿은 작업이 실제로 생성에 쓰는 bytes 다(포트 :meth:`ExportSourcePort.template_bytes`). 같은
  bytes(같은 sha256)는 한 번만 담고, 표시 이름은 그 bytes 를 처음 낸 작업의 파일 이름이다.
- 연결(field-binding/v5)·파일명 규칙은 그대로, 연결의 출처 메타(``provenance``)만 비운 사본이다.
- 선택 구성은 작업의 지금 선언 선택 하나를 작업 이름의 선택 프리셋으로 싣는다(없으면 없다).
- 데이터 계약은 작업이 쓰는 데이터를 같은 해석기로 돌린 값 없는 통계다. 데이터를 읽지 못했거나
  결속이 없는 작업은 계약 없이 실리고 :attr:`WorkPackageDraft.without_contract` 에 이름이 남는다 —
  그대로 내보낼지는 호출자가 사람에게 묻는다.

데이터 결속·권위 id·검토 기준선·판본·즐겨찾기·그룹·태그·최근 실행·필터 프리셋·시험 자료는
manifest 에 자리가 없어 실리지 않는다. 이 모듈은 Domain 만 안다 — 파일·저장소는 포트 뒤에 있다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PureWindowsPath
from typing import Protocol

from ..domain.data_contract import encode_data_contract
from ..domain.data_contract_check import profile_data_contract
from ..domain.job import Job, has_data_binding
from ..domain.mapping import MappingProfile
from ..domain.preset import SelectionPreset
from ..domain.slot_selection import SlotSelectionSet
from ..domain.work_package import (
    PackagedJob,
    PackagedTemplate,
    WorkPackageManifest,
)


class ExportDataUnavailable(Exception):
    """작업의 데이터를 읽을 수 없다 — 계약 없이 내보낼지 사람에게 물을 사유(실패가 아니다)."""


class ExportSourcePort(Protocol):
    """내보내기가 읽는 사실 — External(:mod:`hwpxfiller.external.work_package_sources`)이 구현한다."""

    def template_bytes(self, job: Job) -> bytes:
        """작업이 생성에 쓰는 템플릿 bytes. 읽을 수 없으면 사유가 담긴 예외(내보내기 중단)."""
        ...

    def declared_selection(self, job: Job) -> "SlotSelectionSet | None":
        """작업의 지금 선언 선택 — 선택이 없으면 ``None``."""
        ...

    def records(self, job: Job) -> "Sequence[Mapping[str, object]]":
        """작업이 쓰는 데이터 전 행. 읽을 수 없으면 :class:`ExportDataUnavailable`."""
        ...


@dataclass(frozen=True)
class WorkPackageDraft:
    """쓰기 직전의 꾸러미 — manifest·``{digest: bytes}``·계약 없이 실린 작업 이름."""

    manifest: WorkPackageManifest
    templates: Mapping[str, bytes]
    without_contract: tuple[str, ...]


def portable_mapping(profile: MappingProfile) -> MappingProfile:
    """연결 사본 — 출처 메타만 비운다. 원본 프로파일은 그대로 둔다."""
    return MappingProfile.from_dict({**profile.to_dict(), "provenance": {}})


def template_display_name(job: Job) -> str:
    """꾸러미에 적을 템플릿 표시 이름 — 작업이 가리키는 파일의 이름 한 조각(경로 아님)."""
    return PureWindowsPath(job.template_path).name


def _contract_of(job: Job, sources: ExportSourcePort) -> "dict | None":
    if not has_data_binding(job):
        return None
    try:
        records = sources.records(job)
    except ExportDataUnavailable:
        return None
    return encode_data_contract(profile_data_contract(job.mapping, records))


def _presets_of(
    job: Job, sources: ExportSourcePort, created_at: str
) -> tuple[SelectionPreset, ...]:
    selection = sources.declared_selection(job)
    if selection is None:
        return ()
    return (
        SelectionPreset(
            name=job.name, selection_set=selection, provenance={}, created_at=created_at
        ),
    )


def draft_work_package(
    jobs: Sequence[Job], sources: ExportSourcePort, *, created_at: str
) -> WorkPackageDraft:
    """작업들 → 꾸러미 초안. 값 불변식 위반은 :class:`~hwpxfiller.domain.work_package.WorkPackageError`."""
    declared: dict[str, PackagedTemplate] = {}
    blobs: dict[str, bytes] = {}
    packaged: list[PackagedJob] = []
    without: list[str] = []
    for job in jobs:
        blob = sources.template_bytes(job)
        digest = sha256(blob).hexdigest()
        if digest not in declared:
            declared[digest] = PackagedTemplate(
                digest=digest, media=job.media,
                display_name=template_display_name(job), size=len(blob),
            )
            blobs[digest] = blob
        contract = _contract_of(job, sources)
        if contract is None:
            without.append(job.name)
        packaged.append(PackagedJob(
            name=job.name,
            media=job.media,
            template_digest=digest,
            mapping=portable_mapping(job.mapping),
            filename_pattern=job.filename_pattern,
            selection_presets=_presets_of(job, sources, created_at),
            data_contract=contract,
        ))
    manifest = WorkPackageManifest(
        created_at=created_at, templates=tuple(declared.values()), jobs=tuple(packaged)
    )
    return WorkPackageDraft(manifest=manifest, templates=blobs, without_contract=tuple(without))


__all__ = [
    "ExportDataUnavailable",
    "ExportSourcePort",
    "WorkPackageDraft",
    "draft_work_package",
    "portable_mapping",
    "template_display_name",
]
