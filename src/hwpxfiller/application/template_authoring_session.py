"""In-memory state for one template document and its independent trial data."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AuthoringSession:
    id: str
    media: str
    content: bytes
    source_path: str = ""
    save_path: str = ""
    baseline: str | None = None
    source_baseline: str | None = None
    saved_content: bytes = b""
    revision: int = 0
    analysis: dict = field(default_factory=dict)
    draft_key: str = ""
    recovery: bool = False
    recovery_saved_at: str = ""
    external_changed: bool = False
    rhwp_editable: bool | None = None
    rhwp_diagnostics: list[dict] = field(default_factory=list)
    cases: list[dict] = field(default_factory=list)
    cases_error: str = ""
    cases_dirty: bool = False
    trial_inputs_dirty: bool = False
    values: dict = field(default_factory=dict)
    selected: dict = field(default_factory=dict)
    trial_input_revision: int = 0
    trial_result: dict | None = None
    trial_coverage_evidence: dict[tuple[str, str], tuple[int, str]] = field(default_factory=dict)
    trial_error: str = ""
    trial_document_revision: int = -1
    trial_values_revision: int = -1

    @property
    def dirty(self) -> bool:
        return self.content != self.saved_content

    @property
    def trial_stale(self) -> bool:
        return (
            self.trial_result is None
            or self.trial_document_revision != self.revision
            or self.trial_values_revision != self.trial_input_revision
        )

    def replace_content(self, content: bytes, analysis: dict) -> None:
        if content == self.content:
            return
        self.content = content
        self.analysis = analysis
        self.revision += 1

    def replace_trial_input(self, values: dict, selected: dict) -> None:
        if values == self.values and selected == self.selected:
            return
        self.values = dict(values)
        self.selected = dict(selected)
        self.trial_input_revision += 1
        self.trial_inputs_dirty = bool(self.values or self.selected) and not any(
            case.get("values") == self.values and case.get("selected") == self.selected
            for case in self.cases
        )
