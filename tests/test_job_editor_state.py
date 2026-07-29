"""작업 저장 게이트(링1) 헤드리스 테스트 — RC-28.

에디터 ``accept()`` 의 술어(매핑 확정·이름·패턴·전부 비움·덮어쓰기 확인 필요)와
확인 문구 성형을 Qt 없이 검증한다 — RC-08 류의 dead guard 가 위젯 사각에서
시그널 없이 썩지 않게 한다.
"""

from __future__ import annotations

from hwpxfiller.gui.job_editor_state import (
    needs_overwrite_confirm,
    overwrite_confirm_text,
    validate_save,
)
from hwpxfiller.gui.mapping_state import MappingModel, RowState


def _model(*rows: RowState) -> MappingModel:
    return MappingModel(rows=list(rows))


def _content_row(name: str = "공고명", confirmed: bool = True) -> RowState:
    return RowState(template_field=name, source="bidNtceNm", confirmed=confirmed)


def _blank_row(name: str = "비고") -> RowState:
    return RowState(template_field=name, confirmed=True)  # 의도적 비움 확정


# ------------------------------------------------------------------ validate_save
def test_validate_save_blocks_when_model_missing():
    verdict = validate_save(None, "작업1", "doc-{{ID}}")
    assert not verdict.ok
    assert "확정" in verdict.block_reason
    assert verdict.profile is None


def test_validate_save_blocks_when_not_all_confirmed():
    model = _model(_content_row(), _content_row("추정가격", confirmed=False))
    verdict = validate_save(model, "작업1", "doc-{{ID}}")
    assert not verdict.ok
    assert "모든 매핑 행" in verdict.block_reason


def test_validate_save_blocks_on_empty_name():
    verdict = validate_save(_model(_content_row()), "", "doc-{{ID}}")
    assert not verdict.ok
    assert "이름" in verdict.block_reason


def test_validate_save_blocks_on_empty_pattern():
    """RC-20 — 빈 패턴을 화면에 없던 값으로 조용히 폴백하지 않는다."""
    verdict = validate_save(_model(_content_row()), "작업1", "")
    assert not verdict.ok
    assert "패턴" in verdict.block_reason


def test_validate_save_pattern_gate_is_media_aware():
    """F6 PR-B — TXT 작업은 파일을 만들지 않아 파일 이름 축이 없다(§3.2): 패턴 게이트가
    서지 않는다. 없는 규칙의 차단 문구는 고칠 표면이 없는 문구다. 그 외 게이트는 동일."""
    assert validate_save(_model(_content_row()), "작업1", "", media="txt").ok
    assert "이름" in validate_save(_model(_content_row()), "", "", media="txt").block_reason
    assert "전부 비움" in validate_save(_model(_blank_row()), "작업1", "", media="txt").block_reason


def test_validate_save_blocks_all_blank_job():
    """RC-08 회귀 — 전부 비움 확정 작업은 emits_any_value 질의로 시끄럽게 차단."""
    verdict = validate_save(
        _model(_blank_row("갑"), _blank_row("을")), "작업1", "doc-{{ID}}"
    )
    assert not verdict.ok
    assert "전부 비움" in verdict.block_reason


def test_validate_save_passes_with_profile():
    verdict = validate_save(_model(_content_row(), _blank_row()), "작업1", "doc-{{ID}}")
    assert verdict.ok and verdict.block_reason == ""
    assert verdict.profile is not None
    assert verdict.profile.name == "작업1"
    # 확정 2행(값 1 + 명시 blank 1) 전부 프로파일로 영속화(L1).
    assert len(verdict.profile.mappings) == 2


def test_blocked_field_names_the_input_to_fix():
    """차단은 **고칠 칸**을 함께 말한다(U2 §2.4) — "입력하세요"만으로는 지시가 절반이다.

    표면이 차단 문구를 파싱해 어느 칸인지 알아내면 문안을 고칠 때마다 조준이 조용히
    깨진다. 판정이 이름을 내고 표면은 그것을 겨눈다.

    칸을 겨눌 수 없는 차단(미확정·스키마 불일치·전부 비움)은 **빈 문자열**이다 — 없는
    칸을 겨눈 척하지 않는다. 그것들은 표 전체가 대상이라 지목할 입력이 없다.
    """
    assert validate_save(_model(_content_row()), "", "doc-{{ID}}").blocked_field == "name"
    assert validate_save(_model(_content_row()), "작업1", "").blocked_field == "pattern"
    # TXT 는 파일 이름 축이 없어 패턴 차단 자체가 없다 — 겨눌 칸도 없다.
    assert validate_save(_model(_content_row()), "작업1", "", media="txt").ok
    for verdict in (
        validate_save(_model(_content_row(confirmed=False)), "작업1", "doc-{{ID}}"),
        validate_save(_model(_blank_row()), "작업1", "doc-{{ID}}"),
    ):
        assert not verdict.ok and verdict.blocked_field == ""


def test_validate_save_predicate_order_is_stable():
    """차단 사유 순서 고정: 미확정 → 이름 → 패턴 → 전부 비움(종전 accept 와 동일)."""
    unconfirmed = _model(_content_row(confirmed=False))
    assert "모든 매핑 행" in validate_save(unconfirmed, "", "").block_reason
    all_blank = _model(_blank_row())
    assert "이름" in validate_save(all_blank, "", "").block_reason
    assert "패턴" in validate_save(all_blank, "작업1", "").block_reason
    assert "전부 비움" in validate_save(all_blank, "작업1", "doc-{{ID}}").block_reason


# ------------------------------------------------------- needs_overwrite_confirm
def test_overwrite_confirm_only_when_covering_another_job():
    # 새 작업이 기존 이름과 충돌 → 확인 필요.
    assert needs_overwrite_confirm("작업1", None, exists=True)
    # 새 이름(미존재) → 확인 불필요.
    assert not needs_overwrite_confirm("작업1", None, exists=False)
    # 편집 모드 자기 자신 갱신(이름 그대로) → 자명, 확인 없음.
    assert not needs_overwrite_confirm("작업1", "작업1", exists=True)
    # 편집 모드에서 이름을 바꿔 다른 기존 작업을 덮음 → 확인 필요.
    assert needs_overwrite_confirm("작업2", "작업1", exists=True)
    assert not needs_overwrite_confirm("작업2", "작업1", exists=False)


# --------------------------------------------------------- overwrite_confirm_text
def test_overwrite_confirm_text_restates_actual_victim():
    """RC-15 P6 — 확인 문구는 실제 파괴 대상을 재진술한다(slug 충돌·손상 구분)."""
    same = overwrite_confirm_text("작업1", "작업1")
    assert "작업 '작업1' 이(가) 이미 있습니다" in same

    slug = overwrite_confirm_text("예산/2026", "예산_2026")
    assert "예산/2026" in slug and "예산_2026" in slug  # 입력·파괴 대상 모두 재진술

    corrupt = overwrite_confirm_text("작업1", "")
    assert "손상" in corrupt  # 이름 불명을 추측하지 않고 그대로 고지


# --------- 근본 조치(리뷰 3R): durable Job 필드의 **분류 완전성** 구조 가드 ---------
#: 에디터 저장이 세션 값으로 **다시 짓는** 필드 — 곧 편집기가 소유하는 규칙·정체다.
_EDITOR_REBUILDS = {
    "version", "name", "template_path", "mapping", "filename_pattern",
    "default_dataset_ref",
}
#: 저장이 **되싣는** 비-편집 메타 — `_preserved_meta` 가 소유한다.
_EDITOR_PRESERVES = {"tags", "last_run_at", "group", "favorited_at", "reviewed_rules"}
#: 레지스트리가 **계산해 쓰는** 파생 메타(재작성 F7) — 어느 편집 표면도 값을 싣지 않고
#: :func:`~hwpxfiller.core.job.advance_revisions` 가 저장 잠금 안에서 정산한다. 세 번째
#: 갈래를 만든 이유: 이 셋을 '보존'으로 선언하면 편집 세션이 든 옛 판본이 디스크의 최신
#: 세대를 되돌리고, '다시 짓는다'로 선언하면 편집기가 판본을 발명하게 된다.
_REGISTRY_DERIVES = {"template_revision", "binding_revision", "previous_rules"}


def test_every_durable_job_field_is_classified_by_the_editor_save():
    """durable Job 필드는 저장이 **다시 짓거나 보존하거나 계산하거나** 셋 중 하나여야 한다.

    같은 결함이 두 번 났다: 그룹이 조용히 초기화되던 자리(슬라이스 2)와 검토 기준선이
    비워지던 자리(재작성 F5 3R). 두 번이면 목록이 아니라 **규율**이 문제다 — 새 durable
    필드를 더할 때 어느 쪽인지 **선언하지 않으면** 여기서 걸린다. 선언을 강제하면 다음
    누락은 사람이 아니라 게이트가 잡는다.
    """
    from dataclasses import fields as dataclass_fields

    from hwpxfiller.core.job import Job
    from hwpxfiller.webapp.screen_editor import _EMPTY_PRESERVED, _preserved_meta

    durable = {f.name for f in dataclass_fields(Job)}
    classified = _EDITOR_REBUILDS | _EDITOR_PRESERVES | _REGISTRY_DERIVES
    assert durable == classified, (
        "durable Job 필드가 분류되지 않았습니다 — 저장이 다시 짓는지(_EDITOR_REBUILDS) "
        "보존하는지(_EDITOR_PRESERVES + _preserved_meta) 레지스트리가 계산하는지"
        "(_REGISTRY_DERIVES) 선언하세요: "
        f"미분류={sorted(durable - classified)}, 유령={sorted(classified - durable)}"
    )
    # 세 갈래는 배타적이다 — 한 필드가 두 갈래에 들면 어느 쪽이 이기는지가 코드 순서에
    # 달리고, 그 순서는 리팩터링에 조용히 뒤집힌다.
    assert not (_EDITOR_REBUILDS & _EDITOR_PRESERVES)
    assert not (_REGISTRY_DERIVES & (_EDITOR_REBUILDS | _EDITOR_PRESERVES))
    # 선언과 실물이 갈리지 않게: 보존 목록의 두 표현(빈 기본값·추출기)이 같은 키를 든다.
    assert set(_EMPTY_PRESERVED) == _EDITOR_PRESERVES
    assert set(_preserved_meta(Job(name="x"))) == _EDITOR_PRESERVES
