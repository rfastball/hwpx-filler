"""txt 즉시 기안 ViewModel — Qt 불필요(헤드리스). 렌더·토큰 상태·레코드 스텝.

미입력 토큰은 {{}} 유지(누락 시끄럽게), 값은 치환 — render_record 미러 계약을 못박는다.
"""
from __future__ import annotations

from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.gui.txt_state import TxtDraftViewModel


def _vm(tmp_path):
    d = tmp_path / "tt"
    d.mkdir()
    (d / "기안.txt").write_text(
        "제목: {{공고명}}\n가격: {{추정가격}}\n담당: {{담당자}}\n붙임: {{비고}}",
        encoding="utf-8",
    )
    vm = TxtDraftViewModel(TextTemplateRegistry(d))
    vm.select_template("기안")
    return vm


class _Src:
    # 담당자는 데이터에 없음(→ missing), 비고는 빈 값(→ blank).
    def records(self):
        return [
            {"공고명": "전산장비 구매", "추정가격": "85,000,000원", "비고": ""},
            {"공고명": "사무가구", "추정가격": "1,200,000원", "비고": "긴급"},
        ]

    def fields(self):
        return ["공고명", "추정가격", "비고"]


def test_template_selection_and_names(tmp_path):
    vm = _vm(tmp_path)
    assert vm.template_names() == ["기안"]
    assert "{{공고명}}" in vm.template_text


def test_render_substitutes_and_keeps_missing_tokens(tmp_path):
    vm = _vm(tmp_path)
    vm.records = _Src().records()
    text, report = vm.render()
    assert "제목: 전산장비 구매" in text          # 채움 → 값 치환
    assert "가격: 85,000,000원" in text
    assert "{{담당자}}" in text                    # 미입력 → 토큰 그대로(시끄럽게)
    assert report.missing_fields == ["담당자"]     # 데이터에 없는 필드
    assert report.empty_fields == ["비고"]         # 있으나 빈 값


def test_token_states(tmp_path):
    vm = _vm(tmp_path)
    vm.records = _Src().records()
    states = {t.name: t.state for t in vm.token_states()}
    assert states == {"공고명": "fill", "추정가격": "fill", "담당자": "missing", "비고": "blank"}


def test_record_stepper_wraps(tmp_path):
    vm = _vm(tmp_path)
    vm.records = _Src().records()
    assert vm.current_record()["공고명"] == "전산장비 구매"
    vm.step(1)
    assert vm.current_record()["공고명"] == "사무가구"
    vm.step(1)  # 2건 → 랩어라운드
    assert vm.current_record()["공고명"] == "전산장비 구매"


def test_paste_text_clears_name(tmp_path):
    vm = _vm(tmp_path)
    vm.set_template_text("자유 {{필드}}")
    assert vm.template_name is None and "자유" in vm.template_text
