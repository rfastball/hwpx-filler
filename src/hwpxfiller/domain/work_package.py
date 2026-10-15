"""작업 꾸러미(``.narumi``) manifest 의 값 모델과 codec (WP-01 · #1188).

꾸러미는 작업 여러 개와 그 템플릿 bytes 를 다른 사용자에게 건네는 그릇이다. 이 모듈은
그 안의 ``manifest.json`` 이 무엇을 싣고 무엇을 싣지 않는지를 값 불변식으로 고정한다 —
zip 배치·digest 재계산·크기 상한 같은 bytes 경계는 External(:mod:`hwpxfiller.external.
work_package_io`)이 진다. 이 모듈에 I/O 는 0 개다.

**싣지 않는 것이 계약의 절반이다.** 데이터 결속(경로·시트·헤더 행·종류), 권위 id, 검토
지문·판본, 즐겨찾기·그룹·태그·최근 실행, 필터 프리셋·시험 자료는 manifest 에 자리가 없다.
작업 항목의 필드 집합이 :data:`JOB_ENTRY_FIELDS` 정확히 그것이라, 그런 값이 끼어 들어오면
decode 가 미지 필드로 거절한다. 매핑·선택 프리셋의 ``provenance`` 도 비어 있어야 한다 —
데이터 파일 이름·로컬 id 같은 보낸 쪽 출처 메타가 실려 나가지 않게 한다.

매핑은 기존 :class:`~hwpxfiller.domain.mapping.MappingProfile` codec, 선택 프리셋은
:func:`~hwpxfiller.domain.preset.encode_preset`/:func:`~hwpxfiller.domain.preset.decode_preset`
을 그대로 쓴다(두 번째 codec 을 만들지 않는다). 데이터 계약(``data_contract``)은 WP-02 소관이라
여기서는 JSON 객체인지까지만 보고 안쪽 모양은 판정하지 않는다.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .mapping import MappingProfile
from .preset import PresetError, SelectionPreset, decode_preset, encode_preset

WORK_PACKAGE_SCHEMA_VERSION = "work-package/v1"

#: 꾸러미가 싣는 템플릿 매체 — 확장자와 같은 이름이다.
TEMPLATE_MEDIA = frozenset({"hwpx", "txt"})

#: 직렬화 최상위 필드 집합 — decode 가 **정확히** 이것만 받는다(구조 밀수 봉쇄).
MANIFEST_FIELDS = frozenset({"schema_version", "created_at", "templates", "jobs"})
#: 템플릿 항목 필드 집합.
TEMPLATE_ENTRY_FIELDS = frozenset({"digest", "media", "display_name", "size"})
#: 작업 항목 필드 집합. 여기 없는 작업 속성은 꾸러미로 건너가지 않는다(모듈 docstring).
JOB_ENTRY_FIELDS = frozenset(
    {
        "name",
        "media",
        "template_digest",
        "mapping",
        "filename_pattern",
        "selection_presets",
        "data_contract",
    }
)
_JOB_OPTIONAL_FIELDS = frozenset({"data_contract"})

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_DISPLAY_NAME_FORBIDDEN = frozenset('<>:"/\\|?*')
_DISPLAY_NAME_MAX = 255


class WorkPackageError(ValueError):
    """꾸러미 manifest 불변식·codec 위반, 또는 꾸러미 파일을 받아들일 수 없는 사유."""


# ─── 값 검사 헬퍼 ──────────────────────────────────────────────────────────────

def _require_text(value: object, what: str) -> str:
    """앞뒤 공백만이 아닌, 제어 문자 없는 문자열."""
    if not isinstance(value, str) or not value.strip():
        raise WorkPackageError(f"{what}이(가) 비어 있습니다")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise WorkPackageError(f"{what}에 제어 문자가 있습니다")
    return value


def _require_digest(value: object, what: str) -> str:
    if not isinstance(value, str) or _SHA256_HEX.fullmatch(value) is None:
        raise WorkPackageError(f"{what}이(가) sha256 소문자 16진 64자가 아닙니다: {value!r}")
    return value


def _require_media(value: object) -> str:
    if value not in TEMPLATE_MEDIA:
        raise WorkPackageError(f"모르는 템플릿 형식: {value!r}")
    return str(value)


def _require_display_name(value: object, media: str) -> str:
    """표시 전용 원래 파일 이름 — 경로·예약 문자·서식 문자 없는 한 조각, 확장자는 매체와 같다.

    받는 쪽이 이 이름을 파일 이름 후보로 쓸 수 있으므로 경로 탈출·확장자 위장(방향 바꿈
    문자 등)을 값 단계에서 막는다.
    """
    if not isinstance(value, str) or not value or len(value) > _DISPLAY_NAME_MAX:
        raise WorkPackageError("템플릿 표시 이름의 길이가 맞지 않습니다")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise WorkPackageError(f"템플릿 표시 이름에 제어·서식 문자가 있습니다: {value!r}")
    if _DISPLAY_NAME_FORBIDDEN.intersection(value):
        raise WorkPackageError(f"템플릿 표시 이름에 쓸 수 없는 문자가 있습니다: {value!r}")
    suffix = f".{media}"
    stem = value[: -len(suffix)]
    if not value.lower().endswith(suffix) or not stem.strip(" ."):
        raise WorkPackageError(f"템플릿 표시 이름이 {media} 파일 이름이 아닙니다: {value!r}")
    if value != value.strip():
        raise WorkPackageError(f"템플릿 표시 이름의 앞뒤가 공백입니다: {value!r}")
    return value


def _require_size(value: object) -> int:
    if type(value) is not int or value < 1:
        raise WorkPackageError(f"템플릿 크기가 양의 정수가 아닙니다: {value!r}")
    return value


def _require_entries(value: object, what: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise WorkPackageError(f"{what}이(가) 목록이 아닙니다")
    return tuple(value)


def _require_record(
    data: object, fields: frozenset[str], optional: frozenset[str], what: str
) -> Mapping[str, Any]:
    """필드 집합이 정확히 ``fields`` 인 객체 — 미지 필드·빠진 필드 모두 loud."""
    if not isinstance(data, Mapping):
        raise WorkPackageError(f"{what}이(가) 객체가 아닙니다")
    unknown = sorted(set(data) - fields)
    if unknown:
        raise WorkPackageError(f"{what}에 모르는 필드가 있습니다: {unknown}")
    missing = sorted(fields - optional - set(data))
    if missing:
        raise WorkPackageError(f"{what}에 필드가 빠졌습니다: {missing}")
    return data


def _duplicates(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        (repeated if value in seen else seen).add(value)
    return sorted(repeated)


# ─── 값 모델 ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PackagedTemplate:
    """꾸러미에 담긴 템플릿 bytes 한 개의 선언 — bytes 자체는 zip 이 싣는다.

    ``digest`` 가 정체성이다(같은 bytes 는 한 번만 담는다). ``display_name`` 은 표시용
    원래 파일 이름일 뿐 경로가 아니다.
    """

    digest: str
    media: str
    display_name: str
    size: int

    def __post_init__(self) -> None:
        _require_digest(self.digest, "템플릿 digest")
        _require_media(self.media)
        _require_display_name(self.display_name, self.media)
        _require_size(self.size)


@dataclass(frozen=True)
class PackagedJob:
    """꾸러미에 담긴 작업 한 개 — 템플릿 참조·연결·파일명 규칙·선택 프리셋·데이터 계약.

    ``mapping`` 은 기존 :class:`MappingProfile` 이다(가변 dataclass 라 decode 가 새로 만든
    사본을 든다). ``data_contract`` 는 ``None`` 이거나 JSON 객체이며 깊은 사본으로 보관한다.
    """

    name: str
    media: str
    template_digest: str
    mapping: MappingProfile
    filename_pattern: str
    selection_presets: tuple[SelectionPreset, ...] = ()
    data_contract: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "작업 이름")
        _require_media(self.media)
        _require_digest(self.template_digest, "작업의 템플릿 digest")
        _require_text(self.filename_pattern, f"작업 {self.name!r}의 파일명 규칙")
        self._check_mapping()
        object.__setattr__(self, "selection_presets", self._checked_presets())
        if self.data_contract is not None:
            if not isinstance(self.data_contract, Mapping):
                raise WorkPackageError(f"작업 {self.name!r}의 데이터 계약이 객체가 아닙니다")
            object.__setattr__(self, "data_contract", copy.deepcopy(dict(self.data_contract)))

    def _check_mapping(self) -> None:
        if not isinstance(self.mapping, MappingProfile):
            raise WorkPackageError(f"작업 {self.name!r}의 연결이 MappingProfile 이 아닙니다")
        if self.mapping.provenance:
            raise WorkPackageError(f"작업 {self.name!r}의 연결에 출처 메타가 남아 있습니다")

    def _checked_presets(self) -> tuple[SelectionPreset, ...]:
        presets = _require_entries(self.selection_presets, "선택 프리셋")
        for preset in presets:
            if not isinstance(preset, SelectionPreset):
                raise WorkPackageError(f"작업 {self.name!r}의 선택 프리셋 값이 아닙니다")
            if preset.provenance:
                raise WorkPackageError(
                    f"작업 {self.name!r}의 선택 프리셋 {preset.name!r}에 출처 메타가 남아 있습니다"
                )
        duplicated = _duplicates([preset.name for preset in presets])
        if duplicated:
            raise WorkPackageError(f"작업 {self.name!r}의 선택 프리셋 이름이 겹칩니다: {duplicated}")
        return presets


@dataclass(frozen=True)
class WorkPackageManifest:
    """꾸러미 한 개의 manifest — 작업 1개 이상과 그 작업들이 참조하는 템플릿 선언 전부.

    불변식: 작업 이름 유일, 템플릿 digest 유일, 모든 작업의 digest 가 선언돼 있고 매체가
    같으며, 어느 작업도 참조하지 않는 템플릿은 없다.
    """

    created_at: str
    templates: tuple[PackagedTemplate, ...]
    jobs: tuple[PackagedJob, ...]

    def __post_init__(self) -> None:
        _require_text(self.created_at, "created_at")
        templates = _require_entries(self.templates, "templates")
        jobs = _require_entries(self.jobs, "jobs")
        if not all(isinstance(item, PackagedTemplate) for item in templates):
            raise WorkPackageError("templates 항목이 템플릿 선언이 아닙니다")
        if not all(isinstance(item, PackagedJob) for item in jobs):
            raise WorkPackageError("jobs 항목이 작업 값이 아닙니다")
        if not jobs:
            raise WorkPackageError("꾸러미에 작업이 없습니다")
        object.__setattr__(self, "templates", templates)
        object.__setattr__(self, "jobs", jobs)
        self._check_references()

    def _check_references(self) -> None:
        duplicated = _duplicates([job.name for job in self.jobs])
        if duplicated:
            raise WorkPackageError(f"작업 이름이 겹칩니다: {duplicated}")
        if _duplicates([template.digest for template in self.templates]):
            raise WorkPackageError("같은 템플릿이 두 번 선언됐습니다")
        declared = self.template_by_digest()
        for job in self.jobs:
            template = declared.get(job.template_digest)
            if template is None:
                raise WorkPackageError(f"작업 {job.name!r}의 템플릿이 꾸러미에 없습니다")
            if template.media != job.media:
                raise WorkPackageError(f"작업 {job.name!r}의 형식이 템플릿 형식과 다릅니다")
        unused = sorted(set(declared) - {job.template_digest for job in self.jobs})
        if unused:
            raise WorkPackageError(f"어느 작업도 쓰지 않는 템플릿이 있습니다: {unused}")

    def template_by_digest(self) -> dict[str, PackagedTemplate]:
        """digest → 템플릿 선언 사본(선언 순서 유지)."""
        return {template.digest: template for template in self.templates}


# ─── codec ────────────────────────────────────────────────────────────────────

def _encode_template(template: PackagedTemplate) -> dict[str, Any]:
    return {
        "digest": template.digest,
        "media": template.media,
        "display_name": template.display_name,
        "size": template.size,
    }


def _encode_job(job: PackagedJob) -> dict[str, Any]:
    return {
        "name": job.name,
        "media": job.media,
        "template_digest": job.template_digest,
        "mapping": job.mapping.to_dict(),
        "filename_pattern": job.filename_pattern,
        "selection_presets": [encode_preset(preset) for preset in job.selection_presets],
        "data_contract": copy.deepcopy(job.data_contract),
    }


def encode_work_package(manifest: WorkPackageManifest) -> dict[str, Any]:
    """JSON-safe 표현 — 최상위·항목 필드 집합은 각 ``*_FIELDS`` 정확히 그 집합이다."""
    return {
        "schema_version": WORK_PACKAGE_SCHEMA_VERSION,
        "created_at": manifest.created_at,
        "templates": [_encode_template(template) for template in manifest.templates],
        "jobs": [_encode_job(job) for job in manifest.jobs],
    }


def _decode_template(data: object) -> PackagedTemplate:
    record = _require_record(data, TEMPLATE_ENTRY_FIELDS, frozenset(), "템플릿 항목")
    return PackagedTemplate(
        digest=record["digest"],
        media=record["media"],
        display_name=record["display_name"],
        size=record["size"],
    )


def _decode_mapping(data: object, job_name: object) -> MappingProfile:
    """기존 codec 으로 읽고, 다시 쓴 모양이 입력과 같을 때만 받는다.

    ``MappingProfile.from_dict`` 는 저장소 하위호환을 위해 빠진 키를 기본값으로 채우고 모르는
    키를 무시한다. 꾸러미는 새로 쓰인 파일이라 그 관용이 필요 없다 — 왕복 동일성으로 미지
    필드·비정규 모양을 새 codec 없이 거절한다.
    """
    if not isinstance(data, Mapping):
        raise WorkPackageError(f"작업 {job_name!r}의 연결이 객체가 아닙니다")
    try:
        profile = MappingProfile.from_dict(dict(data))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise WorkPackageError(f"작업 {job_name!r}의 연결을 읽을 수 없습니다: {exc}") from exc
    if profile.to_dict() != data:
        raise WorkPackageError(f"작업 {job_name!r}의 연결 모양이 정규형이 아닙니다")
    return profile


def _decode_presets(data: object, job_name: object) -> tuple[SelectionPreset, ...]:
    try:
        return tuple(decode_preset(item) for item in _require_entries(data, "선택 프리셋"))
    except PresetError as exc:
        raise WorkPackageError(f"작업 {job_name!r}의 선택 프리셋을 읽을 수 없습니다: {exc}") from exc


def _decode_job(data: object) -> PackagedJob:
    record = _require_record(data, JOB_ENTRY_FIELDS, _JOB_OPTIONAL_FIELDS, "작업 항목")
    name = record["name"]
    return PackagedJob(
        name=name,
        media=record["media"],
        template_digest=record["template_digest"],
        mapping=_decode_mapping(record["mapping"], name),
        filename_pattern=record["filename_pattern"],
        selection_presets=_decode_presets(record["selection_presets"], name),
        data_contract=record.get("data_contract"),
    )


def decode_work_package(data: object) -> WorkPackageManifest:
    """JSON 표현 → :class:`WorkPackageManifest`. 미상 버전·미지 필드·참조 위반은 loud.

    버전을 먼저 본다 — 다른 버전의 필드 집합으로 이 버전의 판정을 내리지 않는다.
    """
    if not isinstance(data, Mapping):
        raise WorkPackageError("꾸러미 manifest 가 객체가 아닙니다")
    schema = data.get("schema_version")
    if schema != WORK_PACKAGE_SCHEMA_VERSION:
        raise WorkPackageError(f"모르는 꾸러미 버전: {schema!r}")
    record = _require_record(data, MANIFEST_FIELDS, frozenset(), "꾸러미 manifest")
    return WorkPackageManifest(
        created_at=record["created_at"],
        templates=tuple(
            _decode_template(item) for item in _require_entries(record["templates"], "templates")
        ),
        jobs=tuple(_decode_job(item) for item in _require_entries(record["jobs"], "jobs")),
    )


__all__ = [
    "JOB_ENTRY_FIELDS",
    "MANIFEST_FIELDS",
    "TEMPLATE_ENTRY_FIELDS",
    "TEMPLATE_MEDIA",
    "WORK_PACKAGE_SCHEMA_VERSION",
    "PackagedJob",
    "PackagedTemplate",
    "WorkPackageError",
    "WorkPackageManifest",
    "decode_work_package",
    "encode_work_package",
]
