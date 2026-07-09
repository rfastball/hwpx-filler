"""GOLDEN 스냅샷 회귀 — 실제 코퍼스 추출 결과가 커밋된 골든 JSON 과 일치.

골든 재생성: ``HWPX_UPDATE_GOLDEN=1 pytest tests/test_corpus_golden.py``
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hwpxfiller.core.text_extract import extract_document

CORPUS = Path(__file__).parent / "corpus" / "real"
GOLDEN = Path(__file__).parent / "corpus" / "golden"
REAL_FILES = sorted(CORPUS.glob("*.hwpx"))


def _serialize(path: Path) -> str:
    """추출 결과를 결정적 JSON 문자열로 직렬화(키 정렬, 한글 원문 유지)."""
    doc = extract_document(str(path))
    return json.dumps(doc.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _golden_path(path: Path) -> Path:
    return GOLDEN / (path.stem + ".json")


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_golden_matches(path: Path):
    current = _serialize(path)
    gp = _golden_path(path)

    if os.environ.get("HWPX_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        gp.write_text(current, encoding="utf-8")
        pytest.skip(f"골든 재생성: {gp.name}")

    assert gp.exists(), f"골든 없음: {gp} (HWPX_UPDATE_GOLDEN=1 로 생성)"
    expected = gp.read_text(encoding="utf-8")
    assert current == expected, f"골든 불일치: {gp.name} (의도된 변경이면 재생성)"
