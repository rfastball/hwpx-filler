"""txt 즉시 기안 ViewModel — Qt 불필요(헤드리스). 템플릿 선택·데이터 소스 겨눔.

렌더·토큰 상태·레코드 커서는 컨트롤러의 전-선언 큐(작업점 카드, R-flow 블록 3)가 대체했으므로
이 VM 에서 사라졌다(고아 커서 API 삭제) — 렌더/토큰 회귀는 ``test_webapp_txt_zone``(카드 스냅샷)·
``test_text_render``(render_segments) 소관. 여기는 템플릿·데이터 겨눔 계약만 본다.
"""
from __future__ import annotations

from pathlib import Path

from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.gui.txt_state import TxtDraftViewModel

MULTI_SHEET = Path(__file__).parent / "fixtures" / "multi_sheet.xlsx"


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


def test_template_selection_and_names(tmp_path):
    vm = _vm(tmp_path)
    assert vm.template_names() == ["기안"]
    assert "{{공고명}}" in vm.template_text


def test_paste_text_clears_name(tmp_path):
    vm = _vm(tmp_path)
    vm.set_template_text("자유 {{필드}}")
    assert vm.template_name is None and "자유" in vm.template_text


# ------------------------------------------------- UD-25 데이터 겨눔 대칭화(V12)
def test_template_field_names_lists_tokens_in_order(tmp_path):
    vm = _vm(tmp_path)
    assert vm.template_field_names() == ["공고명", "추정가격", "담당자", "비고"]


class _ExcelPoolItem:
    # 풀 항목(참조) 덕타입 — kind+opts 만 노출(레코드·키 없음).
    kind = "excel"

    def __init__(self, path):
        self.opts = {"path": path}


def test_load_pool_item_restores_and_targets_records(tmp_path):
    """풀 겨눔(UD-25) — 공용 팩토리로 참조를 복원해 렌더 소스로 겨눈다."""
    csv = tmp_path / "pool.csv"
    csv.write_text("공고명,추정가격\n전산장비,1000\n", encoding="utf-8-sig")
    vm = _vm(tmp_path)
    records = vm.load_pool_item(_ExcelPoolItem(str(csv)))
    assert records == [{"공고명": "전산장비", "추정가격": "1000"}]
    assert vm.record_count() == 1
    assert vm.records[0]["공고명"] == "전산장비"


def test_load_data_targets_confirmed_sheet(tmp_path):
    """T2 시트 옵션 관통(링1) — 확정 시트의 레코드가 렌더 소스로 겨눠진다."""
    vm = _vm(tmp_path)
    recs = vm.load_data(str(MULTI_SHEET), sheet="낙찰현황")
    assert recs[0]["업체명"] == "가나상사"
    assert vm.record_count() == 3
    # 대조군: 미지정(기본 첫 시트)은 다른 내용.
    assert vm.load_data(str(MULTI_SHEET))[0]["공고명"] == "전산장비"


def test_load_pool_item_with_sheet_restores_that_sheet(tmp_path):
    """풀 항목 opts 의 sheet 임베딩이 txt 풀 겨눔 복원에도 관통한다(T2)."""

    class _SheetPoolItem:
        kind = "excel"
        opts = {"path": str(MULTI_SHEET), "sheet": "낙찰현황"}

    vm = _vm(tmp_path)
    recs = vm.load_pool_item(_SheetPoolItem())
    assert recs[0]["업체명"] == "가나상사"
    assert vm.record_count() == 3


def test_set_acquired_targets_records(tmp_path):
    """수기·애드혹 직접 겨눔 — datasource/records 원자 대입(부분 대입 방지)."""
    vm = _vm(tmp_path)
    marker = object()
    vm.set_acquired(marker, [{"공고명": "수기건"}])
    assert vm.datasource is marker
    assert vm.records == [{"공고명": "수기건"}]
    assert vm.record_count() == 1
