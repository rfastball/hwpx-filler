"""작업 꾸러미 manifest 값 모델·codec 테스트(WP-01 · #1188).

꾸러미가 싣지 않는 것(데이터 결속·권위·검토 상태·개인 메타)은 작업 항목의 정확한 필드
집합으로 고정된다. 미지 필드·미상 버전·참조 위반은 전부 loud 거절이다.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest

from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.domain.preset import SelectionPreset, encode_preset
from hwpxfiller.domain.slot_selection import SlotSelection, SlotSelectionSet
from hwpxfiller.domain.text_slice import TextSlice
from hwpxfiller.domain.work_package import (
    JOB_ENTRY_FIELDS,
    MANIFEST_FIELDS,
    TEMPLATE_ENTRY_FIELDS,
    WORK_PACKAGE_SCHEMA_VERSION,
    PackagedJob,
    PackagedTemplate,
    WorkPackageError,
    WorkPackageManifest,
    decode_work_package,
    encode_work_package,
)

NOW = "2026-10-15T09:00:00"
HWPX_DIGEST = hashlib.sha256(b"hwpx template").hexdigest()
TXT_DIGEST = hashlib.sha256(b"txt template").hexdigest()


def _mapping() -> MappingProfile:
    return MappingProfile(
        name="공고",
        mappings=[
            FieldMapping(template_field="공고명", source="공고명"),
            FieldMapping(
                template_field="기관",
                source="수요기관",
                slice=TextSlice.from_dict({"mode": "head", "count": 4}),
            ),
            FieldMapping(template_field="비고", type="const", const=""),
        ],
    )


def _preset(name: str = "표준", provenance: dict[str, str] | None = None) -> SelectionPreset:
    return SelectionPreset(
        name=name,
        selection_set=SlotSelectionSet(
            (SlotSelection(slot_id="s1", selected_option_ids=("o1",)),)
        ),
        provenance=provenance or {},
        created_at=NOW,
    )


def _template(digest: str = HWPX_DIGEST, media: str = "hwpx", **kw: Any) -> PackagedTemplate:
    return PackagedTemplate(
        digest=digest,
        media=media,
        display_name=kw.pop("display_name", f"공고서.{media}"),
        size=kw.pop("size", 13),
    )


def _job(name: str = "공고서 작성", **kw: Any) -> PackagedJob:
    return PackagedJob(
        name=name,
        media=kw.pop("media", "hwpx"),
        template_digest=kw.pop("template_digest", HWPX_DIGEST),
        mapping=kw.pop("mapping", _mapping()),
        filename_pattern=kw.pop("filename_pattern", "공고서-{{date}}-{{seq:001}}"),
        selection_presets=kw.pop("selection_presets", (_preset(),)),
        data_contract=kw.pop("data_contract", None),
    )


def _manifest(**kw: Any) -> WorkPackageManifest:
    return WorkPackageManifest(
        created_at=NOW,
        templates=kw.pop("templates", (_template(),)),
        jobs=kw.pop("jobs", (_job(),)),
    )


def _encoded(**kw: Any) -> dict[str, Any]:
    return encode_work_package(_manifest(**kw))


# ------------------------------------------------------------------ 왕복
def test_roundtrip_is_lossless_for_shared_template_and_contract() -> None:
    """작업 둘이 템플릿 하나를 공유하고 TXT 작업·데이터 계약이 섞여도 왕복이 무손실이다."""
    manifest = _manifest(
        templates=(_template(), _template(TXT_DIGEST, "txt", size=12)),
        jobs=(
            _job("가", data_contract={"columns": {"공고명": {"kind": "text"}}}),
            _job("나", selection_presets=()),
            _job("다", media="txt", template_digest=TXT_DIGEST),
        ),
    )
    encoded = encode_work_package(manifest)
    decoded = decode_work_package(copy.deepcopy(encoded))
    assert encode_work_package(decoded) == encoded
    assert decoded.jobs[0].mapping.to_dict() == _mapping().to_dict()
    assert decoded.jobs[0].data_contract == {"columns": {"공고명": {"kind": "text"}}}
    assert decoded.jobs[0].selection_presets[0].name == "표준"


def test_encoded_field_sets_are_exact() -> None:
    encoded = _encoded()
    assert set(encoded) == MANIFEST_FIELDS
    assert encoded["schema_version"] == WORK_PACKAGE_SCHEMA_VERSION
    assert set(encoded["templates"][0]) == TEMPLATE_ENTRY_FIELDS
    assert set(encoded["jobs"][0]) == JOB_ENTRY_FIELDS


def test_job_entry_excludes_data_binding_authority_review_and_personal_meta() -> None:
    """데이터 결속·권위·검토 상태·판본·개인 메타·필터·시험 자료는 작업 항목에 자리가 없다."""
    assert JOB_ENTRY_FIELDS == {
        "name",
        "media",
        "template_digest",
        "mapping",
        "filename_pattern",
        "selection_presets",
        "data_contract",
    }
    excluded = {
        "data_path", "data_sheet", "data_header_row", "data_kind", "authority_id",
        "reviewed_rules", "previous_rules", "template_revision", "binding_revision",
        "version", "favorited_at", "group", "tags", "last_run_at", "template_path",
        "filter_presets", "test_data",
    }
    for field in sorted(excluded):
        encoded = _encoded()
        encoded["jobs"][0][field] = "x"
        with pytest.raises(WorkPackageError, match="모르는 필드"):
            decode_work_package(encoded)


def test_data_contract_absent_decodes_as_none() -> None:
    encoded = _encoded()
    del encoded["jobs"][0]["data_contract"]
    assert decode_work_package(encoded).jobs[0].data_contract is None


@pytest.mark.parametrize("value", [[], "계약", 3])
def test_data_contract_must_be_object(value: object) -> None:
    encoded = _encoded()
    encoded["jobs"][0]["data_contract"] = value
    with pytest.raises(WorkPackageError, match="데이터 계약"):
        decode_work_package(encoded)


def test_data_contract_is_isolated_from_caller() -> None:
    contract: dict[str, Any] = {"columns": {"a": {"n": 1}}}
    job = _job(data_contract=contract)
    contract["columns"]["a"]["n"] = 2
    assert job.data_contract == {"columns": {"a": {"n": 1}}}


# ------------------------------------------------------------------ 버전·필드
@pytest.mark.parametrize("version", [None, "work-package/v2", "work-package/v0", 1])
def test_unknown_version_is_rejected(version: object) -> None:
    encoded = _encoded()
    encoded["schema_version"] = version
    with pytest.raises(WorkPackageError, match="모르는 꾸러미 버전"):
        decode_work_package(encoded)


def test_non_object_manifest_is_rejected() -> None:
    with pytest.raises(WorkPackageError, match="객체가 아닙니다"):
        decode_work_package([])


@pytest.mark.parametrize("where", ["top", "template"])
def test_unknown_field_is_rejected(where: str) -> None:
    encoded = _encoded()
    target = encoded if where == "top" else encoded["templates"][0]
    target["data_path"] = "C:/개인/자료.xlsx"
    with pytest.raises(WorkPackageError, match="모르는 필드"):
        decode_work_package(encoded)


@pytest.mark.parametrize("field", sorted(JOB_ENTRY_FIELDS - {"data_contract"}))
def test_missing_job_field_is_rejected(field: str) -> None:
    encoded = _encoded()
    del encoded["jobs"][0][field]
    with pytest.raises(WorkPackageError, match="빠졌습니다"):
        decode_work_package(encoded)


def test_missing_top_field_is_rejected() -> None:
    encoded = _encoded()
    del encoded["created_at"]
    with pytest.raises(WorkPackageError, match="빠졌습니다"):
        decode_work_package(encoded)


@pytest.mark.parametrize("value", [{}, "templates"])
def test_entries_must_be_lists(value: object) -> None:
    encoded = _encoded()
    encoded["templates"] = value
    with pytest.raises(WorkPackageError, match="목록이 아닙니다"):
        decode_work_package(encoded)


# ------------------------------------------------------------------ 연결·프리셋
def test_mapping_unknown_or_noncanonical_shape_is_rejected() -> None:
    encoded = _encoded()
    encoded["jobs"][0]["mapping"]["mappings"][0]["alias"] = "x"
    with pytest.raises(WorkPackageError, match="정규형"):
        decode_work_package(encoded)
    encoded = _encoded()
    del encoded["jobs"][0]["mapping"]["mappings"][0]["fmt"]
    with pytest.raises(WorkPackageError, match="정규형"):
        decode_work_package(encoded)


@pytest.mark.parametrize(
    "mapping", ["연결", {"mappings": [{"template_field": "a", "type": "모름"}]}, {"mappings": [3]}]
)
def test_malformed_mapping_is_rejected(mapping: object) -> None:
    encoded = _encoded()
    encoded["jobs"][0]["mapping"] = mapping
    with pytest.raises(WorkPackageError, match="연결"):
        decode_work_package(encoded)


def test_mapping_provenance_must_be_empty() -> None:
    """연결의 출처 메타(데이터 파일 이름 등)는 꾸러미로 건너가지 않는다."""
    with pytest.raises(WorkPackageError, match="출처 메타"):
        _job(mapping=MappingProfile(name="m", provenance={"dataset": "6월 자료.xlsx"}))
    encoded = _encoded()
    encoded["jobs"][0]["mapping"]["provenance"] = {"dataset": "6월 자료.xlsx"}
    with pytest.raises(WorkPackageError, match="출처 메타"):
        decode_work_package(encoded)


def test_preset_provenance_must_be_empty() -> None:
    with pytest.raises(WorkPackageError, match="출처 메타"):
        _job(selection_presets=(_preset(provenance={"template_application_id": "A1"}),))


def test_preset_names_unique_within_job() -> None:
    with pytest.raises(WorkPackageError, match="선택 프리셋 이름이 겹칩니다"):
        _job(selection_presets=(_preset("표준"), _preset("표준")))


def test_corrupt_preset_is_rejected() -> None:
    encoded = _encoded()
    encoded["jobs"][0]["selection_presets"][0]["declared_selection_digest"] = "0" * 64
    with pytest.raises(WorkPackageError, match="선택 프리셋을 읽을 수 없습니다"):
        decode_work_package(encoded)


def test_preset_entries_must_be_values() -> None:
    with pytest.raises(WorkPackageError, match="선택 프리셋 값이 아닙니다"):
        _job(selection_presets=(encode_preset(_preset()),))


# ------------------------------------------------------------------ 불변식
def test_job_names_must_be_unique() -> None:
    with pytest.raises(WorkPackageError, match="작업 이름이 겹칩니다"):
        _manifest(jobs=(_job("가"), _job("가")))


@pytest.mark.parametrize("name", ["", "   ", "가\n나", 3])
def test_job_name_must_be_plain_text(name: object) -> None:
    with pytest.raises(WorkPackageError, match="작업 이름"):
        _job(name)  # type: ignore[arg-type]


def test_filename_pattern_must_be_nonempty() -> None:
    with pytest.raises(WorkPackageError, match="파일명 규칙"):
        _job(filename_pattern="")


def test_package_needs_at_least_one_job() -> None:
    with pytest.raises(WorkPackageError, match="작업이 없습니다"):
        _manifest(templates=(), jobs=())


def test_undeclared_template_is_rejected() -> None:
    with pytest.raises(WorkPackageError, match="템플릿이 꾸러미에 없습니다"):
        _manifest(templates=(_template(TXT_DIGEST, "txt"),), jobs=(_job(),))


def test_unreferenced_template_is_rejected() -> None:
    with pytest.raises(WorkPackageError, match="쓰지 않는 템플릿"):
        _manifest(templates=(_template(), _template(TXT_DIGEST, "txt")))


def test_duplicate_template_declaration_is_rejected() -> None:
    with pytest.raises(WorkPackageError, match="두 번 선언"):
        _manifest(templates=(_template(), _template()))


def test_job_media_must_match_template_media() -> None:
    with pytest.raises(WorkPackageError, match="형식이 템플릿 형식과 다릅니다"):
        _manifest(
            templates=(_template(TXT_DIGEST, "txt"),),
            jobs=(_job(media="hwpx", template_digest=TXT_DIGEST),),
        )


def test_manifest_entries_must_be_values() -> None:
    with pytest.raises(WorkPackageError, match="템플릿 선언이 아닙니다"):
        _manifest(templates=({"digest": HWPX_DIGEST},))
    with pytest.raises(WorkPackageError, match="작업 값이 아닙니다"):
        _manifest(jobs=({"name": "가"},))


@pytest.mark.parametrize("digest", ["", "A" * 64, "0" * 63, "g" * 64, None])
def test_digest_must_be_lowercase_sha256_hex(digest: object) -> None:
    with pytest.raises(WorkPackageError, match="sha256"):
        _template(digest)  # type: ignore[arg-type]


def test_unknown_media_is_rejected() -> None:
    with pytest.raises(WorkPackageError, match="모르는 템플릿 형식"):
        _template(media="docx", display_name="a.docx")


@pytest.mark.parametrize("size", [0, -1, True, 1.5, "13"])
def test_size_must_be_positive_int(size: object) -> None:
    with pytest.raises(WorkPackageError, match="크기"):
        _template(size=size)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "../공고서.hwpx",
        "폴더/공고서.hwpx",
        "폴더\\공고서.hwpx",
        "C:공고서.hwpx",
        "공고서.txt",
        ".hwpx",
        " 공고서.hwpx",
        "공고서\u202excod.hwpx",
        "공고\n서.hwpx",
        "가" * 300 + ".hwpx",
    ],
)
def test_display_name_is_sanitized(name: str) -> None:
    with pytest.raises(WorkPackageError, match="표시 이름"):
        _template(display_name=name)


def test_display_name_extension_is_case_insensitive() -> None:
    assert _template(display_name="공고서.HWPX").display_name == "공고서.HWPX"
