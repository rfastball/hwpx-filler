"""diff 엔진 파일 불문 INVARIANTS — tests/corpus/real/ 모든 파일에서 성립.

가장 강력한 안전장치: 같은 문서를 자기 자신과 비교하면 변경이 0 이어야 한다.
변경을 헛집어내는(hallucinate) diff 는 여기서 즉시 실패한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.diff import diff_documents, diff_files
from hwpxfiller.core.text_extract import extract_document

CORPUS = Path(__file__).parent / "corpus" / "real"
REAL_FILES = sorted(CORPUS.glob("*.hwpx"))


def test_corpus_not_empty():
    assert REAL_FILES, "코퍼스에 실제 HWPX 파일이 없다"


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_identity_zero_changes(path: Path):
    """diff(A, A) 는 변경 0, 변경 항목 0 (모든 코퍼스 파일)."""
    doc = extract_document(str(path))
    result = diff_documents(doc, doc)
    assert result.changes == []
    assert result.change_items == []
    assert result.summary == {
        "added": 0, "removed": 0, "changed": 0, "change_items": 0
    }


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_identity_via_files(path: Path):
    """파일 경로 편의 함수로도 자기 비교는 변경 0."""
    result = diff_files(str(path), str(path))
    assert result.to_dict()["changes"] == []


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_deterministic_to_dict(path: Path):
    """같은 페어를 두 번 diff 하면 to_dict() 가 완전히 동일(랜덤·정렬 안정)."""
    other = REAL_FILES[0]
    first = diff_files(str(path), str(other)).to_dict()
    second = diff_files(str(path), str(other)).to_dict()
    assert first == second


def test_cross_pair_has_changes():
    """서로 다른 두 파일 비교는 최소한 하나의 변경을 보고한다(엔진이 죽지 않았음)."""
    if len(REAL_FILES) < 2:
        pytest.skip("코퍼스 파일이 2개 미만")
    result = diff_files(str(REAL_FILES[0]), str(REAL_FILES[1]))
    assert result.changes, "서로 다른 문서인데 변경이 하나도 없다"
