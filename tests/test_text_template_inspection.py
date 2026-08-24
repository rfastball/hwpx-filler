"""TXT qualification inspector(S10-02 #859) — 순수 자격 경계.

여기서 보는 것은 **자격 하나**다: 같은 bytes 를 받아 제품 구조를 내거나 진단을 낸다.
그 위의 Candidate·Preparation·Application 생애주기는 매체를 모르는 S2/S3 기계가 이미
지고 있고 그 왕복은 ``tests/test_webapp_template_change.py`` 가 본다 — 두 층을 한
파일에서 겸하면 어느 층이 깨졌는지 실패가 말해 주지 않는다.

지키는 것: structure XOR diagnostics · 진단 어휘가 코어 그대로 · 필드 소유권이 줄
좌표에서 유도된다 · label 이 projection 을 통과한다 · manifest identity.
"""
from __future__ import annotations

import pytest

from hwpxfiller.application.qualification_evidence import (
    QualificationEvidenceError,
    project_structure,
)
from hwpxfiller.application.template_qualification import (
    CandidateRevisionSnapshot,
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
    TemplateQualificationFailed,
    TemplateQualificationPassed,
    qualify_template,
)
from hwpxfiller.domain.structure_scan import StructureDiagnosticKind
from hwpxfiller.external.text_template_inspection import (
    TXT_ENCODING_DIAGNOSTIC_KIND,
    TXT_QUALIFICATION_PROFILE,
    TXT_STRUCTURE_PROJECTION_SCHEMA,
    inspect_txt_qualification,
    txt_qualification_manifest,
)

_FULL = (
    "머리말 {{제목}}\r\n"                # \r\n 도 한 줄 경계다(splitlines 와 같은 분할)
    "{{#항목 첨부 첨부 목록}}\n"
    "공유 {{담당자}}\n"
    "{{#선택 있음 붙임 있음}}\n"
    "붙임 {{파일명}} · {{담당자}}\n"
    "{{/선택}}\n"
    "{{#선택 없음 붙임 없음}}\n"
    "해당 없음\n"
    "{{/선택}}\n"
    "{{/항목}}\n"
    "꼬리 {{제목}} {{기관명}}\n"
)


def _inspect(text: str):
    return inspect_txt_qualification(text.encode("utf-8"))


# ─── PASS: 구조·소유권·label ────────────────────────────────────────────────


def test_field_ownership_follows_the_scanned_line_ranges():
    inspection = _inspect(_FULL)
    assert inspection.diagnostics == ()
    assert inspection.structure == TemplateStructure(
        # 항목 밖 = root. 두 번 나온 {{제목}} 은 목록 안에서 한 번(등장순).
        root_fields=("제목", "기관명"),
        slots=(
            TemplateSlot(
                "첨부",
                shared_fields=("담당자",),  # 항목 안·선택 밖
                options=(
                    # 선택 안의 {{담당자}} 는 공유가 아니라 **그 선택**의 것이다.
                    TemplateOption("있음", ("파일명", "담당자"), label="붙임 있음"),
                    TemplateOption("없음", (), label="붙임 없음"),
                ),
                label="첨부 목록",
            ),
        ),
    )


def test_pass_carries_no_execution_structure():
    """composition fact 를 낼 수 있는 profile 만 그것을 싣는다 — TXT 물질화는 S10-04."""
    assert _inspect(_FULL).execution_structure is None


def test_label_bearing_structure_survives_the_txt_projection():
    """label 이 projection 을 통과한다 — schema 이름이 label 허용 집합에 등재돼 있다."""
    structure = _inspect(_FULL).structure
    assert structure is not None
    payload = project_structure(structure, TXT_STRUCTURE_PROJECTION_SCHEMA).payload
    assert payload["slots"][0]["label"] == "첨부 목록"
    assert payload["slots"][0]["options"][0]["label"] == "붙임 있음"
    # 반대 방향: label 을 못 싣는 schema 로 실으면 조용히 버리지 않고 거절한다.
    with pytest.raises(QualificationEvidenceError):
        project_structure(structure, "hwpx-structure-projection-v1")


def test_plain_template_without_markers_is_all_root():
    inspection = _inspect("{{공고명}} 건에 대해 {{담당자}} 가 알립니다.\n{{공고명}}\n")
    assert inspection.structure == TemplateStructure(
        root_fields=("공고명", "담당자"), slots=()
    )


def test_empty_template_passes_with_an_empty_structure():
    inspection = _inspect("")
    assert inspection.diagnostics == ()
    assert inspection.structure == TemplateStructure()


def test_structure_markers_are_not_counted_as_fields():
    """마커는 필드 토큰과 같은 괄호 문법을 쓰지만 필드가 아니다(sigil 선행 분류)."""
    structure = _inspect(_FULL).structure
    assert structure is not None
    named = set(structure.root_fields)
    for slot in structure.slots:
        named |= set(slot.shared_fields)
        for option in slot.options:
            named |= set(option.fields)
    assert not any(name.startswith(("#", "/")) for name in named)


def test_qualify_template_passes_the_txt_profile():
    """port 를 통과한 결과도 PASS 다 — profile 결속은 S2 가 진다."""
    result = qualify_template(
        CandidateRevisionSnapshot("rev-1", _FULL.encode("utf-8")),
        TXT_QUALIFICATION_PROFILE,
    )
    assert isinstance(result, TemplateQualificationPassed)
    assert result.qualification_profile_id == TXT_QUALIFICATION_PROFILE.id
    assert result.execution_structure is None


# ─── FAIL: 진단 있으면 구조 없음 ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("{{#항목 첨부}}\n내용\n", StructureDiagnosticKind.UNBALANCED_MARKER),
        ("{{#선택 있음}}\n내용\n{{/선택}}\n", StructureDiagnosticKind.OPTION_OUTSIDE_SLOT),
        ("{{#항목}}\n내용\n{{/항목}}\n", StructureDiagnosticKind.EMPTY_SLOT_ID),
        ("{{#항목 첨부}}\n{{/항목}}\n", StructureDiagnosticKind.EMPTY_RANGE),
        ("앞 {{#항목 첨부}} 뒤\n내용\n{{/항목}}\n", StructureDiagnosticKind.MARKER_NOT_ALONE),
        ("{{#몰라 첨부}}\n내용\n", StructureDiagnosticKind.UNKNOWN_KEYWORD),
    ],
)
def test_marker_diagnostics_replace_the_structure(text, kind):
    inspection = _inspect(text)
    assert inspection.structure is None  # 부분 구조 추측 금지
    assert inspection.execution_structure is None
    assert str(kind) in {d.kind for d in inspection.diagnostics}
    assert all(d.message for d in inspection.diagnostics)


def test_diagnostics_keep_the_core_kind_vocabulary():
    """kind 는 코어 안정 식별자 그대로다 — 매체가 다시 이름 지으면 한 결함이 두 이름을 갖는다."""
    inspection = _inspect("{{#항목 첨부}}\n내용\n")
    assert {d.kind for d in inspection.diagnostics} <= {
        str(k) for k in StructureDiagnosticKind
    }


def test_non_utf8_bytes_are_a_named_diagnostic_not_an_empty_structure():
    inspection = inspect_txt_qualification("본문 {{공고명}}".encode("cp949"))
    assert inspection.structure is None
    assert [d.kind for d in inspection.diagnostics] == [TXT_ENCODING_DIAGNOSTIC_KIND]
    assert "UTF-8" in inspection.diagnostics[0].message  # 사유 재진술(조용한 통과 금지)


def test_qualify_template_fails_on_broken_markers():
    result = qualify_template(
        CandidateRevisionSnapshot("rev-2", "{{#항목 x}}\n".encode("utf-8")),
        TXT_QUALIFICATION_PROFILE,
    )
    assert isinstance(result, TemplateQualificationFailed)
    assert result.diagnostics


def test_non_bytes_input_is_a_loud_type_error():
    with pytest.raises(TypeError):
        inspect_txt_qualification("본문")  # type: ignore[arg-type]


# ─── identity ───────────────────────────────────────────────────────────────


def test_manifest_declares_the_txt_identity():
    manifest = txt_qualification_manifest("2026-08-24T09:00:00")
    assert manifest.qualification_profile_id == TXT_QUALIFICATION_PROFILE.id
    assert manifest.media == "txt"
    assert manifest.projection_schema_version == TXT_STRUCTURE_PROJECTION_SCHEMA
    assert manifest.created_at == "2026-08-24T09:00:00"
    # HWPX profile 이름을 재사용하지 않는다 — 좌표계도 자격 규칙도 다르다.
    assert "hwpx" not in manifest.qualification_profile_id
    assert "hwpx" not in manifest.projection_schema_version
