"""「가공」 팝오버 JS 테스트의 입력이 Python 투영 그대로인가 — 픽스처 드리프트 가드.

`tests/js/slice_popover.test.js` 는 Python 을 부를 수 없어 방식 목록·미리보기·후보를 JSON 픽스처로
받는다. 픽스처를 손으로 고치면 웹이 Python 이 내지 않는 모양을 그리는지 재게 된다(무동작 측정) —
그래서 픽스처는 이 파일이 :mod:`hwpxfiller.viewmodel.slice_assist` 로 **다시 짓고** 대조한다.

    uv run python tests/test_slice_popover_fixture.py   # 픽스처 재생성
"""
from __future__ import annotations

import json
from pathlib import Path

from hwpxfiller.domain.text_slice import TextSlice
from hwpxfiller.viewmodel.slice_assist import preview_slice, propose_slices, slice_methods

FIXTURE = Path(__file__).parent / "js" / "fixtures" / "slice_popover.json"

AMOUNTS = [
    "170,309,180원 (VAT 포함)",
    "48,500,000원 (VAT 포함)",
    "9,900,000원",
    "1,230,000원 (VAT 별도)",
    "",
]


def build() -> dict:
    keep_before = TextSlice("before", delimiter="원", on_missing="keep")
    between = TextSlice("between", open="(", close=")")
    return {
        "methods": slice_methods(None),
        "methods_split5": slice_methods(TextSlice("split", delimiter=",", index=5)),
        "preview_none": preview_slice("계약금액", None, AMOUNTS),
        "preview_before": preview_slice("계약금액", keep_before, AMOUNTS, sample=0),
        "preview_between": preview_slice("계약금액", between, AMOUNTS, sample=2),
        "propose_amount": propose_slices(AMOUNTS, 0, 0, 11),
        "propose_none": propose_slices(AMOUNTS, 0, 12, 13),
    }


def _render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def test_js_fixture_is_the_python_projection() -> None:
    assert FIXTURE.read_text(encoding="utf-8") == _render(build()), (
        "tests/js/fixtures/slice_popover.json 이 Python 투영과 다릅니다 — "
        "`uv run python tests/test_slice_popover_fixture.py` 로 다시 지으세요"
    )


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(_render(build()), encoding="utf-8", newline="\n")
    print(f"재생성: {FIXTURE}")
