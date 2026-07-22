"""H-10 sticky 크롬 재질의 정적 계약.

액션바와 datazone 표 머리가 한 재질 문법을 공유하고, 투명도 축소 환경에서는
불투명 표면과 명시적 경계로 강등되는지 가드한다.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _rule(selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, f"CSS 규칙이 없습니다: {selector}"
    return _compact(match.group(1))


def test_actionbar_and_table_header_share_one_material_rule() -> None:
    rule = _rule(".session-actionbar,.jobtb th")
    assert "background:color-mix(insrgb,var(--a-card)82%,transparent)" in rule
    assert "backdrop-filter:blur(14px)" in rule


def test_reduced_transparency_downgrades_the_whole_material_set() -> None:
    compact = _compact(CSS)
    marker = "@media(prefers-reduced-transparency:reduce){.session-actionbar,.jobtbth{"
    start = compact.find(marker)
    assert start >= 0, "투명도 축소 강등 미디어 쿼리가 없습니다."
    block = compact[start : start + 280]
    assert ".session-actionbar,.jobtbth{" in block
    assert "background:var(--a-card)" in block
    assert "border-color:var(--a-border)" in block
    assert "backdrop-filter:none" in block


def test_only_the_shared_rule_applies_backdrop_material() -> None:
    assert CSS.count("backdrop-filter:blur(14px)") == 2
