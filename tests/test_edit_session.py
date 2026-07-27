"""편집 거래(EditContext·patch) — 계약 §5·§8, 불변식 §13-16. 재작성 F7 PR-A(§10.13).

여기서 지키는 것은 셋이다: ①진입 문맥이 fail-closed 로 검증된다(문맥 없는 편집기 금지)
②patch 는 **유도**되고 그 원재료가 판본·검토 요구와 같다(판정 주체 단일화) ③"저장하면
달라지는 것"과 "손댄 자리"가 **다른 값**이다(가드는 후자를 봐야 한다).
"""
from __future__ import annotations

import pytest

from hwpxfiller.core.job import Job
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.edit_session import (
    DEFERRED_ENTRY_REASONS,
    ENTRY_REASONS,
    LIVE_ENTRY_REASONS,
    EditSession,
    dirty_sections,
    make_context,
    section_changes,
    sections_for,
)


def _job(**over) -> Job:
    job = Job(
        name="입찰공고서",
        template_path="/tmp/t.hwpx",
        filename_pattern="공고서-{{공고명}}",
        mapping=MappingProfile(
            name="",
            mappings=[
                FieldMapping(template_field="공고명", source="사업명", type="text"),
                FieldMapping(template_field="금액", source="추정가격", type="amount", fmt="won"),
            ],
        ),
    )
    for k, v in over.items():
        setattr(job, k, v)
    return job


def _edited(**field_over) -> Job:
    job = _job()
    job.mapping = MappingProfile(
        name="",
        mappings=[
            FieldMapping(
                template_field="공고명",
                source=field_over.get("source", "사업명"),
                type="text",
                fmt=field_over.get("fmt", ""),
            ),
            FieldMapping(template_field="금액", source="추정가격", type="amount", fmt="won"),
        ],
    )
    return job


# ------------------------------------------------------------------ 탭 구성
def test_sections_are_derived_from_media_and_never_guessed():
    """§3.1·§3.2 — TXT 는 파일 이름 탭이 없고, 모르는 매체를 HWPX 로 추측하지 않는다(§19.11-2).

    「시험」은 어느 매체에도 없다: F8 이 세우기 전까지 빈 탭을 두지 않는다(§8.2 ②).
    """
    assert sections_for("hwpx") == ("template", "binding", "filename")
    assert sections_for("txt") == ("template", "binding")
    assert sections_for("") == ("template",)
    assert all("test" not in sections_for(m) for m in ("hwpx", "txt", ""))


# ------------------------------------------------------------------ 진입 문맥
def test_every_entry_reason_is_either_live_or_declared_deferred():
    """계약 10종은 전부 열거하되 **배제는 선언**이다(§10.13 판정 K).

    조용한 무시와 선언된 배제는 다르다 — 선언이 없으면 표면을 지을 때 사유를 새로
    발명하게 되고 발명된 어휘는 계약과 갈린다.
    """
    assert LIVE_ENTRY_REASONS | set(DEFERRED_ENTRY_REASONS) == set(ENTRY_REASONS)
    assert not (LIVE_ENTRY_REASONS & set(DEFERRED_ENTRY_REASONS))
    assert all(DEFERRED_ENTRY_REASONS.values())  # 배제엔 사유가 붙는다(빈 문자열 금지)


@pytest.mark.parametrize("reason", sorted(DEFERRED_ENTRY_REASONS))
def test_deferred_entry_reasons_are_refused_loudly(reason):
    """미배선 사유로 열리면 배너가 아무 말도 못 한다 — 조용한 폴백 대신 거절."""
    with pytest.raises(ValueError, match="배선"):
        make_context("작업", entry_reason=reason)


def test_unknown_entry_reason_and_return_surface_are_refused():
    with pytest.raises(ValueError, match="진입 사유"):
        make_context("작업", entry_reason="어쩌다")
    with pytest.raises(ValueError, match="복귀 표면"):
        make_context("작업", return_context={"surface": "어딘가"})


def test_context_carries_evidence_verbatim():
    """증거는 **보낸 표면이 본 것**이다 — 편집기가 다시 계산하면 배너와 화면이 갈린다."""
    ctx = make_context(
        "입찰공고서",
        entry_reason="preview_result",
        evidence={"지급일 표시형": "2026. 07. 25."},
        return_context={"surface": "preview", "focus_target": "preview-date"},
    )
    assert ctx.to_dict()["evidence"] == {"지급일 표시형": "2026. 07. 25."}
    assert ctx.to_dict()["return_context"]["focus_target"] == "preview-date"


# ------------------------------------------------------------------ patch 유도
def test_section_changes_names_the_axis_and_carries_before_after():
    base = _job()
    assert section_changes(base, _job()) == {}                       # 같으면 patch 없음

    renamed = _job(filename_pattern="공고서-{{공고명}}-2")
    assert section_changes(base, renamed) == {
        "filename": {"before": "공고서-{{공고명}}", "after": "공고서-{{공고명}}-2"}
    }

    moved = _job(template_path="/tmp/other.hwpx")
    assert set(section_changes(base, moved)) == {"template"}

    fmt = section_changes(base, _edited(fmt="dateLongKo"))
    assert set(fmt) == {"binding"}
    assert fmt["binding"]["공고명"]["before"]["fmt"] == ""
    assert fmt["binding"]["공고명"]["after"]["fmt"] == "dateLongKo"


def test_field_addition_and_removal_are_not_flattened_into_empty_axes():
    """필드가 **없었다/없어진다**는 「축이 전부 빈 필드」와 전혀 다른 사건이다."""
    base = _job()
    dropped = _job()
    dropped.mapping = MappingProfile(
        name="", mappings=[FieldMapping(template_field="공고명", source="사업명", type="text")]
    )
    changes = section_changes(base, dropped)["binding"]
    assert changes["금액"]["after"] is None and changes["금액"]["before"]["source"] == "추정가격"
    back = section_changes(dropped, base)["binding"]
    assert back["금액"]["before"] is None


def test_a_new_draft_has_no_patch_at_all():
    """비교 대상이 없는 것을 「전부 변경」으로 부르지 않는다 — 첫 저장의 그 재진술은 정보가 0이다."""
    assert section_changes(None, _job()) == {}
    assert dirty_sections(None, _job()) == ()


def test_dirty_counts_unconfirmed_work_that_changes_would_miss():
    """가드는 **잃을 것이 있는지**를 묻지, 저장 가능한지를 묻지 않는다.

    확정하지 않은 매핑 편집은 저장되지 않지만(저장 게이트가 막는다) 버려지면 사라진다 —
    저장될 것만 세면 그 편집이 아무 확인 없이 증발한다.
    """
    base = _job()
    assert section_changes(base, _job()) == {}                       # 저장될 차이는 없고
    assert dirty_sections(base, _job(), pending_binding=True) == ("binding",)  # 잃을 것은 있다


def test_blocking_section_is_the_other_dirty_tab_only():
    """§13-16 은 전이 시점의 규율이다 — 같은 탭에 머무는 편집은 막지 않는다."""
    session = EditSession(context=make_context("입찰공고서"), base=_job())
    edited = _edited(source="사업명2")
    assert session.blocking_section(edited, "binding") == ""          # 제자리
    assert session.blocking_section(edited, "filename") == "binding"  # 다른 탭 = 처분 먼저

    draft = EditSession(context=make_context(""), base=None)
    assert draft.blocking_section(edited, "filename") == ""           # 초안은 거래 밖(판정 P)
