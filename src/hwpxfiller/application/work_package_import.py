"""작업 꾸러미 불러오기의 계획 — 무엇이 어떤 이름으로 들어오는지와 그 지문(#1188 WP-04).

불러오기는 두 단계다. 확인(``inspect``)은 꾸러미를 읽어 **계획**을 세우고 지문(``basis``)을 함께
돌려준다. 확정(``commit``)은 꾸러미를 다시 읽어 계획을 다시 세우고, 지문이 사람이 본 것과 다르면
아무것도 하지 않는다 — 그 사이 같은 이름의 작업이 생겼거나 서식 폴더가 바뀌었으면 사람이 본 계획이
더는 사실이 아니다. 이 모듈은 그 계획과 지문을 짓는다(순수 계산 — 받는 쪽 사실은 포트로 묻는다).

계획의 규칙:

- **덮어쓰지 않는다.** 작업·선택 프리셋 이름이 이미 있으면 ``이름 (2)``·``이름 (3)``… 으로 들인다
  (:mod:`hwpxfiller.domain.copy_name`). 꾸러미 안에서 먼저 정한 이름도 「이미 있음」으로 센다.
- 템플릿은 받는 쪽 서식 폴더에 **같은 sha256** 의 파일이 있으면 그 파일을 쓰고(``reuse``), 없으면
  새 파일로 들인다(``new``). 새 파일 이름은 표시 이름에서 Windows 예약 장치 이름을 피하고 서식 폴더
  가져오기와 같은 사본 이름 규칙을 쓴다.
- 데이터 계약은 이 단계에서 엄격 해독한다 — 손상·변조된 계약은 아무것도 설치하기 전에 거절된다.

불러온 작업(:func:`imported_job`)은 데이터 결속이 비어 「데이터 연결 필요」로 착지하고, 권위 id·
검토 기준선·판본·즐겨찾기·그룹·태그·최근 실행은 새 작업의 기본값이다. 템플릿의 생성 자격은
꾸러미가 들고 오지 않는다 — 받는 쪽의 첫 사용이 기존 초기 등록(capture·qualification)을 그대로 탄다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from ..domain.copy_name import (
    device_safe_file_name,
    first_free,
    numbered_file_name,
    numbered_label,
)
from ..domain.data_contract import DataContract, DataContractError, decode_data_contract
from ..domain.job import Job
from ..domain.mapping import MappingProfile
from ..domain.preset import SelectionPreset
from ..domain.work_package import (
    PackagedJob,
    PackagedTemplate,
    WorkPackageError,
    WorkPackageManifest,
    encode_work_package,
)

#: 템플릿 처리 — 서식 폴더의 같은 bytes 를 쓴다 / 새 파일로 들인다.
TEMPLATE_REUSE = "reuse"
TEMPLATE_NEW = "new"


class ReceivingSidePort(Protocol):
    """받는 쪽의 지금 사실 — External 이 저장소·서식 폴더를 읽어 구현한다."""

    def job_taken(self, name: str) -> bool:
        """그 이름의 작업 자리가 이미 있는가(손상 파일 포함)."""
        ...

    def job_key(self, name: str) -> str:
        """두 이름이 같은 작업 자리를 가리키는지 가르는 열쇠(저장 파일 이름 규칙)."""
        ...

    def preset_taken(self, name: str) -> bool:
        """그 이름의 선택 프리셋이 이미 있는가."""
        ...

    def file_taken(self, file_name: str) -> bool:
        """서식 폴더에 그 파일 이름이 이미 있는가."""
        ...

    def existing_template(self, template: PackagedTemplate) -> "str | None":
        """서식 폴더에서 같은 bytes(같은 sha256·형식)인 파일의 경로 — 없으면 ``None``."""
        ...


@dataclass(frozen=True)
class PlannedTemplate:
    """템플릿 하나의 처리 — ``target`` 은 ``reuse`` 면 기존 파일 경로, ``new`` 면 새 파일 이름."""

    template: PackagedTemplate
    action: str
    target: str


@dataclass(frozen=True)
class PlannedJob:
    """작업 하나의 착지 — 들어올 이름과 해독한 데이터 계약."""

    source: PackagedJob
    final_name: str
    contract: "DataContract | None"

    @property
    def renamed(self) -> bool:
        return self.final_name != self.source.name


@dataclass(frozen=True)
class PlannedPreset:
    """선택 프리셋 하나의 착지 — ``preset`` 은 들어올 이름으로 고친 값이다."""

    job_name: str
    original_name: str
    preset: SelectionPreset

    @property
    def renamed(self) -> bool:
        return self.preset.name != self.original_name


@dataclass(frozen=True)
class ImportPlan:
    """불러오기 계획 전체와 그 지문."""

    templates: tuple[PlannedTemplate, ...]
    jobs: tuple[PlannedJob, ...]
    presets: tuple[PlannedPreset, ...]
    basis: str

    def template_for(self, digest: str) -> PlannedTemplate:
        return next(item for item in self.templates if item.template.digest == digest)


def _free_label(name: str, taken: Callable[[str], bool]) -> str:
    return first_free(lambda number: numbered_label(name, number), taken)


def _free_file_name(name: str, taken: Callable[[str], bool]) -> str:
    return first_free(lambda number: numbered_file_name(name, number), taken)


def _decode_contract(job: PackagedJob) -> "DataContract | None":
    if job.data_contract is None:
        return None
    try:
        return decode_data_contract(job.data_contract)
    except DataContractError as exc:
        raise WorkPackageError(f"작업 {job.name!r}의 데이터 계약을 읽을 수 없습니다: {exc}") from exc


def _plan_templates(
    manifest: WorkPackageManifest, side: ReceivingSidePort
) -> tuple[PlannedTemplate, ...]:
    planned: list[PlannedTemplate] = []
    claimed: set[str] = set()
    for template in manifest.templates:
        existing = side.existing_template(template)
        if existing is not None:
            planned.append(PlannedTemplate(template, TEMPLATE_REUSE, existing))
            continue
        name = _free_file_name(
            device_safe_file_name(template.display_name),
            lambda candidate: side.file_taken(candidate) or candidate.casefold() in claimed,
        )
        claimed.add(name.casefold())
        planned.append(PlannedTemplate(template, TEMPLATE_NEW, name))
    return tuple(planned)


def _plan_jobs(manifest: WorkPackageManifest, side: ReceivingSidePort) -> tuple[PlannedJob, ...]:
    planned: list[PlannedJob] = []
    claimed: set[str] = set()
    for job in manifest.jobs:
        name = _free_label(
            job.name,
            lambda candidate: side.job_taken(candidate) or side.job_key(candidate) in claimed,
        )
        claimed.add(side.job_key(name))
        planned.append(PlannedJob(job, name, _decode_contract(job)))
    return tuple(planned)


def _plan_presets(
    jobs: tuple[PlannedJob, ...], side: ReceivingSidePort
) -> tuple[PlannedPreset, ...]:
    planned: list[PlannedPreset] = []
    claimed: set[str] = set()
    for job in jobs:
        for preset in job.source.selection_presets:
            name = _free_label(
                preset.name,
                lambda candidate: side.preset_taken(candidate) or candidate in claimed,
            )
            claimed.add(name)
            planned.append(PlannedPreset(
                job_name=job.final_name,
                original_name=preset.name,
                preset=SelectionPreset(
                    name=name,
                    selection_set=preset.selection_set,
                    provenance={},
                    created_at=preset.created_at,
                ),
            ))
    return tuple(planned)


def _basis(
    manifest: WorkPackageManifest,
    templates: tuple[PlannedTemplate, ...],
    jobs: tuple[PlannedJob, ...],
    presets: tuple[PlannedPreset, ...],
) -> str:
    """사람이 본 계획의 지문 — 꾸러미 내용과 착지(이름·템플릿 처리)가 하나라도 갈리면 갈린다."""
    payload = {
        "package": encode_work_package(manifest),
        "templates": [[item.template.digest, item.action, item.target] for item in templates],
        "jobs": [item.final_name for item in jobs],
        "presets": [[item.job_name, item.preset.name] for item in presets],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return sha256(text.encode("utf-8")).hexdigest()


def plan_import(manifest: WorkPackageManifest, side: ReceivingSidePort) -> ImportPlan:
    """꾸러미 manifest + 받는 쪽 사실 → 불러오기 계획. 계약 손상은 :class:`WorkPackageError`."""
    templates = _plan_templates(manifest, side)
    jobs = _plan_jobs(manifest, side)
    presets = _plan_presets(jobs, side)
    return ImportPlan(
        templates=templates,
        jobs=jobs,
        presets=presets,
        basis=_basis(manifest, templates, jobs, presets),
    )


def imported_job(planned: PlannedJob, template_path: str) -> Job:
    """불러온 작업 — 연결·파일명 규칙·계약만 싣고 나머지는 새 작업의 기본값(데이터 연결 필요)."""
    source = planned.source
    return Job(
        name=planned.final_name,
        template_path=template_path,
        mapping=MappingProfile.from_dict(source.mapping.to_dict()),
        filename_pattern=source.filename_pattern,
        data_contract=planned.contract,
    )


__all__ = [
    "TEMPLATE_NEW",
    "TEMPLATE_REUSE",
    "ImportPlan",
    "PlannedJob",
    "PlannedPreset",
    "PlannedTemplate",
    "ReceivingSidePort",
    "imported_job",
    "plan_import",
]
