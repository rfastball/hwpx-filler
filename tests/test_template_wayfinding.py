"""H-02 템플릿 소비 진입과 사용자 카피 계약."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "js" / "screens" / "template.js").read_text(encoding="utf-8")


def test_template_band_copy_names_live_destinations() -> None:
    visible_html = re.sub(r"<!--.*?-->", "", INDEX, flags=re.DOTALL)
    assert "선택한 서식으로 새 작업을 시작합니다" in visible_html
    assert "선택한 서식으로 기안을 시작" in visible_html
    for dead in ("작업 에디터", "빠른 기안", "기안문 채우기"):
        assert dead not in visible_html


def test_shared_row_menu_puts_use_cta_before_management_actions() -> None:
    assert 'data-menu="use"' in SCRIPT
    assert 'media === "hwpx" ? "이 서식으로 새 작업" : "이 서식으로 기안 시작"' in SCRIPT
    use = SCRIPT.index('`<button data-menu="use"')
    separator = SCRIPT.index('`<div class="sep"></div>`', use)
    edit = SCRIPT.index('`<button data-menu="edit">', separator)
    move = SCRIPT.index('`<button data-menu="move">', separator)
    delete = SCRIPT.index('`<button data-menu="delete"', separator)
    assert use < separator < edit < move < delete


def test_menu_ctas_route_with_preselected_template() -> None:
    assert 'act === "use" && m.media === "hwpx"' in SCRIPT
    assert "makeJob(m.item.path)" in SCRIPT
    assert "openDraftTemplate(m.item.name)" in SCRIPT
    assert 'Bridge.call("draft", "select_template", { name })' in SCRIPT
    assert 'window.Nav.go("draft")' in SCRIPT


def test_card_surface_no_longer_duplicates_consume_ctas() -> None:
    assert 'filter((a) => a.key !== "make_job")' in SCRIPT
    assert 'data-txt="open"' not in SCRIPT
    assert "기안문 채우기에서 열기" not in SCRIPT
