"""P1-03 migration-unit characterization oracles for previously uncovered modules."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hwpxcore.native import _debug
from hwpxfiller.data.inline import InlineDataSource
from hwpxfiller.gui.mapping_state import MappingModel, RowState
from hwpxfiller.gui.record_range import RecordRange, RecordRangeDraft
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.gui.txt_card import card_text, gate_empty_fields
from hwpxfiller.webapp.data_zone import DataZoneMixin
from hwpxfiller.webapp.job_list import drift_note
from hwpxfiller.webapp.mapping_verbs import MappingVerbsMixin


def test_debug_log_is_gated_and_appends_a_diagnostic_line(tmp_path, monkeypatch) -> None:
    path = tmp_path / "native.log"
    monkeypatch.setattr(_debug, "_PATH", None)
    _debug.log("silent")
    assert not path.exists()

    monkeypatch.setattr(_debug, "_PATH", str(path))
    _debug.log("dialog-open")
    assert "dialog-open" in path.read_text(encoding="utf-8")


def test_inline_source_preserves_field_order_and_defensively_copies() -> None:
    original = [{"name": "A", "amount": "1"}, {"amount": "2", "note": "ok"}]
    source = InlineDataSource(original)
    original[0]["name"] = "mutated"
    fetched = source.records()
    fetched[0]["name"] = "also-mutated"

    assert source.records()[0]["name"] == "A"
    assert source.fields() == ["name", "amount", "note"]
    assert source.field_labels() == {}


def test_record_range_draft_is_isolated_and_detects_dirty_changes() -> None:
    selection = SelectionModel(3, all_selected=False)
    selection.toggle(1, True)
    committed = RecordRange(selection=selection, filter=None, view_order="source")
    draft_range = committed.copy()
    draft = RecordRangeDraft(draft_range, snapshot_gen=7, base_fingerprint=draft_range.fingerprint())

    assert not draft.is_dirty()
    draft.range.selection.toggle(2, True)
    assert draft.is_dirty()
    assert committed.selection.selected_indices() == [1]


def test_txt_card_helpers_share_visible_text_and_declared_blank_gate() -> None:
    segments = [SimpleNamespace(text="A"), SimpleNamespace(text="B")]
    report = SimpleNamespace(empty_fields=["optional", "required"])
    mapping = SimpleNamespace(declared_blank_fields=lambda: ["optional"])

    assert card_text(segments) == "AB"
    assert gate_empty_fields(report, mapping) == ["required"]


class _DataZoneHarness(DataZoneMixin):
    def _records(self) -> list:
        return []


def test_data_zone_handoff_fails_closed_and_preserves_reference_tuple() -> None:
    zone = _DataZoneHarness()
    zone.data_source = ""
    zone.data_path = ""
    zone.data_label = ""
    zone.data_sheet = ""
    zone.data_header_row = 0
    assert zone.new_work_handoff() == ({}, "데이터를 먼저 고르세요.")

    zone.data_source = "file"
    zone.data_path = "C:/data/source.xlsx"
    zone.data_sheet = "Sheet2"
    zone.data_header_row = 3
    handoff, error = zone.new_work_handoff()
    assert error == ""
    assert handoff == {
        "path": "C:/data/source.xlsx",
        "sheet": "Sheet2",
        "header_row": 3,
    }


def test_job_list_drift_note_only_reports_a_real_count_drift() -> None:
    assert drift_note(2, 2) == ""
    assert drift_note(None, 2) == ""
    assert drift_note(2, 3) == " · 확인 시점 2건과 다릅니다"


class _MappingHarness(MappingVerbsMixin):
    def __init__(self) -> None:
        self.mapping = MappingModel(rows=[RowState("amount")])
        self.edits = 0

    def _map_source_fields(self) -> list[str]:
        return ["amount_col"]

    def _map_kind_of(self, source: str) -> str:
        return "amount" if source == "amount_col" else ""

    def _after_mapping_edit(self) -> None:
        self.edits += 1


def test_mapping_verbs_validate_source_and_preserve_edit_hook() -> None:
    harness = _MappingHarness()
    with pytest.raises(ValueError, match="데이터에 없는 열"):
        harness._do_set_source({"name": "amount", "col": "missing"})

    assert harness._do_set_source({"name": "amount", "col": "amount_col"}) is None
    assert harness.mapping.rows[0].source == "amount_col"
    assert harness.mapping.rows[0].type == "amount"
    assert harness.edits == 1
