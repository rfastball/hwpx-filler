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
