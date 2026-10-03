"""In-memory state for one template document and its independent trial data."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AuthoringSession:
    id: str
    media: str
    #: TXT is held with LF line breaks only — the editor's (CodeMirror's) coordinate space.
    content: bytes
    source_path: str = ""
    save_path: str = ""
    baseline: str | None = None
    source_baseline: str | None = None
    saved_content: bytes = b""
    revision: int = 0
    analysis: dict = field(default_factory=dict)
    #: Analysis of ``saved_content`` — the baseline every "since save" impact is read against.
    saved_analysis: dict = field(default_factory=dict)
    #: Identifier renames applied since the last save, in order (F19). Recorded only when an
    #: ``update`` commits exactly the content a preview produced; reset on save/reload.
    identifier_changes: list[dict] = field(default_factory=list)
    #: ``(content, renamed)`` of the latest preview, consumed by the next ``update``.
    last_preview: tuple[bytes, list[dict]] | None = None
    #: The file's own line break (TXT) — restored on every write so a CRLF file stays CRLF.
    eol: str = "\n"
    external_changed: bool = False
    rhwp_editable: bool | None = None
    rhwp_diagnostics: list[dict] = field(default_factory=list)
    cases: list[dict] = field(default_factory=list)
    cases_error: str = ""
    cases_dirty: bool = False
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

    @property
    def trial_inputs_dirty(self) -> bool:
        return bool(self.values or self.selected) and not any(
            case.get("values") == self.values and case.get("selected") == self.selected
            for case in self.cases
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
