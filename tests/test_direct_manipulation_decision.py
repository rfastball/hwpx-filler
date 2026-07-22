from pathlib import Path


DECISION = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "MILESTONE_I_DIRECT_MANIPULATION_DECISION.md"
)


def test_direct_manipulation_candidates_have_explicit_decisions_and_owners() -> None:
    text = DECISION.read_text(encoding="utf-8")
    assert "파일 드래그-드롭 등록 | 채택" in text and "#274" in text
    assert "필터 테이블 드래그 범위 선택 | 채택" in text and "#275" in text
    assert "마스터 목록 폭 스플리터 | 채택" in text and "#221 S7" in text
    assert "작업 카드→그룹 드래그 | 기각" in text
    assert "재론하지 않는다" in text
