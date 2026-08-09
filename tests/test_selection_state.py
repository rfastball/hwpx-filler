"""레코드 선택 모델 테스트 — Qt 불필요(헤드리스)."""

from __future__ import annotations

from hwpxfiller.gui.selection_state import SelectionModel


def test_defaults_and_length():
    m = SelectionModel(3)
    assert m.selected_indices() == [0, 1, 2]
    assert m.selected_count() == 3
    assert len(m) == 3
    assert SelectionModel(3, all_selected=False).selected_indices() == []
    assert len(SelectionModel(0)) == 0


def test_mutations_cover_bulk_and_explicit_selection():
    m = SelectionModel(3, all_selected=False)
    m.set_all()
    assert m.selected_count() == 3
    m.toggle(0)  # True → False
    assert not m.is_selected(0)
    m.toggle(0)  # False → True
    assert m.is_selected(0)
    m.toggle(1, False)
    assert not m.is_selected(1)
    m.set_none()
    assert m.selected_count() == 0


def test_selected_records_preserves_source_order_and_handles_empty():
    m = SelectionModel(4, all_selected=False)
    m.toggle(2, True)
    m.toggle(0, True)
    records = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
    assert m.selected_records(records) == [{"id": "a"}, {"id": "c"}]
    m.set_none()
    assert m.selected_records(records) == []
