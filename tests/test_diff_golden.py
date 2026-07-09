"""GOLDEN diff 회귀 — 실제 v1/v2 페어의 diff 가 커밋된 골든 JSON 과 일치.

form_purchase_v1/v2 는 실제 템플릿 변이본이다. 다만 이 페어는 트리비얼하게 다르다
(v1: 2개 문단 '{{진행상태}} - ...' / v2: 단일 문단 '테스트'). 실제 규격서 개정의
대규모 델타는 아니므로 정밀 커버리지는 test_diff_synthetic 이 담당하고, 여기서는
실제 추출 트리 위에서 엔진이 결정적으로 동작함을 못박는다.

골든 재생성: ``HWPX_UPDATE_GOLDEN=1 pytest tests/test_diff_golden.py``
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from hwpxfiller.core.diff import diff_files

CORPUS = Path(__file__).parent / "corpus" / "real"
GOLDEN = Path(__file__).parent / "corpus" / "golden_diff"
OLD = CORPUS / "form_purchase_v1.hwpx"
NEW = CORPUS / "form_purchase_v2.hwpx"
GOLDEN_JSON = GOLDEN / "form_purchase_v1_to_v2.json"


def _serialize() -> str:
    result = diff_files(str(OLD), str(NEW))
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"


def test_golden_diff_matches():
    current = _serialize()

    if os.environ.get("HWPX_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        GOLDEN_JSON.write_text(current, encoding="utf-8")
        import pytest
        pytest.skip(f"골든 재생성: {GOLDEN_JSON.name}")

    assert GOLDEN_JSON.exists(), (
        f"골든 없음: {GOLDEN_JSON} (HWPX_UPDATE_GOLDEN=1 로 생성)"
    )
    expected = GOLDEN_JSON.read_text(encoding="utf-8")
    assert current == expected, "골든 불일치 (의도된 변경이면 재생성)"


def test_golden_diff_reports_real_changes():
    """골든이 실제로 의미 있는 변경을 담는다(빈 diff 회귀 방지)."""
    result = diff_files(str(OLD), str(NEW))
    assert result.summary["changed"] + result.summary["removed"] >= 1
    assert result.change_items, "변경 항목이 하나도 없다"
