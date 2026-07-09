"""GOLDEN diff 회귀 — 실제 페어의 diff 가 커밋된 골든 JSON 과 일치.

두 페어를 못박는다:
  - ``form_purchase_v1/v2``: 실제 템플릿 변이본이지만 트리비얼하게 다르다(v1: 2개 문단
    '{{진행상태}} - ...' / v2: 단일 문단 '테스트'). 실제 규격서 개정의 대규모 델타는
    아니므로 여기서는 엔진이 실제 추출 트리 위에서 결정적으로 동작함만 못박는다.
  - ``spec_revision_2025/2026``: 같은 공개 규격서의 진짜 연차 개정본(표 8개·문단 385개
    규모). 요율·기준일수 등 실질 변경을 담아 실데이터에서 diff 가치가 드러난다.

골든 재생성: ``HWPX_UPDATE_GOLDEN=1 pytest tests/test_diff_golden.py``
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hwpxfiller.core.diff import diff_files

CORPUS = Path(__file__).parent / "corpus" / "real"
GOLDEN = Path(__file__).parent / "corpus" / "golden_diff"

# (old 파일 stem, new 파일 stem) — 골든명은 f"{old}_to_{new}.json".
PAIRS = [
    ("form_purchase_v1", "form_purchase_v2"),
    ("spec_revision_2025", "spec_revision_2026"),
]


def _serialize(old_stem: str, new_stem: str) -> str:
    result = diff_files(
        str(CORPUS / f"{old_stem}.hwpx"), str(CORPUS / f"{new_stem}.hwpx")
    )
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"


def _golden_path(old_stem: str, new_stem: str) -> Path:
    return GOLDEN / f"{old_stem}_to_{new_stem}.json"


@pytest.mark.parametrize("old_stem,new_stem", PAIRS,
                         ids=[f"{o}_to_{n}" for o, n in PAIRS])
def test_golden_diff_matches(old_stem: str, new_stem: str):
    current = _serialize(old_stem, new_stem)
    gp = _golden_path(old_stem, new_stem)

    if os.environ.get("HWPX_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        gp.write_text(current, encoding="utf-8")
        pytest.skip(f"골든 재생성: {gp.name}")

    assert gp.exists(), f"골든 없음: {gp} (HWPX_UPDATE_GOLDEN=1 로 생성)"
    expected = gp.read_text(encoding="utf-8")
    assert current == expected, f"골든 불일치: {gp.name} (의도된 변경이면 재생성)"


@pytest.mark.parametrize("old_stem,new_stem", PAIRS,
                         ids=[f"{o}_to_{n}" for o, n in PAIRS])
def test_golden_diff_reports_real_changes(old_stem: str, new_stem: str):
    """골든이 실제로 의미 있는 변경을 담는다(빈 diff 회귀 방지)."""
    result = diff_files(
        str(CORPUS / f"{old_stem}.hwpx"), str(CORPUS / f"{new_stem}.hwpx")
    )
    assert result.summary["changed"] + result.summary["removed"] >= 1
    assert result.change_items, "변경 항목이 하나도 없다"
