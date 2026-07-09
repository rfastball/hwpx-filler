"""레코드 선택 모델 테스트 — Qt 불필요(헤드리스)."""

from __future__ import annotations

from hwpxfiller.gui.selection_state import SelectionModel


def test_default_all_selected():
    m = SelectionModel(3)
    assert m.selected_indices() == [0, 1, 2]
    assert m.selected_count() == 3


def test_default_none_when_requested():
    m = SelectionModel(3, all_selected=False)
    assert m.selected_indices() == []


def test_set_all_and_set_none():
    m = SelectionModel(3, all_selected=False)
    m.set_all()
    assert m.selected_count() == 3
    m.set_none()
    assert m.selected_count() == 0


def test_toggle_flips_and_sets_explicit():
    m = SelectionModel(2)
    m.toggle(0)  # True → False
    assert not m.is_selected(0)
    m.toggle(0)  # False → True
    assert m.is_selected(0)
    m.toggle(1, False)
    assert not m.is_selected(1)


def test_selected_records_preserves_order():
    m = SelectionModel(4, all_selected=False)
    m.toggle(2, True)
    m.toggle(0, True)
    records = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
    assert m.selected_records(records) == [{"id": "a"}, {"id": "c"}]


def test_empty_selection_returns_empty_list():
    m = SelectionModel(3)
    m.set_none()
    assert m.selected_records([{"x": 1}, {"x": 2}, {"x": 3}]) == []


def test_len_reflects_count():
    assert len(SelectionModel(5)) == 5
    assert len(SelectionModel(0)) == 0
