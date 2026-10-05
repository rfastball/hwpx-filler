"""In-memory state for one template document and its independent trial data."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def content_digest(content: bytes) -> str:
    """문서 본문의 지문 — 제안 미리보기 본문과 확정 본문이 같은지 가른다."""
    return hashlib.sha256(content).hexdigest()


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
    #: 「데이터로 필드 찾기」(#1156) — 켜져 있으면 데이터·행·「그대로 두기」 집합(``FieldProposalState``).
    proposal: object | None = None
    #: 제안으로 만든 필드의 연결 초안 ``{필드: {"source", "type", "fmt"}}`` — 필드가 문서에 있는 동안만 산다.
    proposal_bindings: dict[str, dict] = field(default_factory=dict)
    #: 제안 미리보기가 기다리는 연결 초안 ``(미리보기 본문 지문, {필드: 초안}, {필드: 시험 값})`` — 확정된 본문이
    #: **그 미리보기 본문과 같을 때만** 기록한다(다른 확정은 초안을 물려받지 않는다).
    proposal_pending: tuple[str, dict[str, dict], dict[str, str]] | None = None
    #: 실행 취소로 필드가 사라진 연결 초안과 시험 값 — 다시 실행으로 필드가 돌아오면 되살린다.
    proposal_retired: dict[str, tuple[dict, str]] = field(default_factory=dict)
    #: 제안이 시험 값에 넣은 원시 값 — 필드가 사라질 때 사람이 고치지 않은 값만 거둔다.
    proposal_seeded: dict[str, str] = field(default_factory=dict)

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
        self._settle_proposal_bindings()

    def _settle_proposal_bindings(self) -> None:
        """문서가 바뀔 때 연결 초안을 정산한다 — 제안 미리보기가 확정됐으면 기록, 필드가 사라지면 거두고 돌아오면 되살린다."""
        fields = {item.get("name") for item in self.analysis.get("fields", []) if isinstance(item, dict)}
        values = dict(self.values)
        pending = self.proposal_pending
        if pending is not None and pending[0] == content_digest(self.content):
            self.proposal_pending = None
            self._record_proposal(pending, fields, values)
        self._retire_proposal(fields, values)
        self._restore_proposal(fields, values)
        self.replace_trial_input(values, self.selected)

    def _record_proposal(self, pending: tuple[str, dict[str, dict], dict[str, str]], fields: set,
                         values: dict) -> None:
        for name in pending[1]:
            if name in fields:
                self.proposal_bindings[name] = pending[1][name]
                self.proposal_seeded[name] = values[name] = pending[2][name]
                self.proposal_retired.pop(name, None)

    def _retire_proposal(self, fields: set, values: dict) -> None:
        """실행 취소 등으로 필드가 사라지면 초안을 거두고, 사람이 고치지 않은 시험 값도 거둔다."""
        for name in [name for name in self.proposal_bindings if name not in fields]:
            seeded = self.proposal_seeded.pop(name, "")
            self.proposal_retired[name] = (self.proposal_bindings.pop(name), seeded)
            if values.get(name) == seeded:
                values.pop(name)

    def _restore_proposal(self, fields: set, values: dict) -> None:
        """다시 실행으로 필드가 돌아오면 거둔 초안과 시험 값을 되살린다."""
        for name in [name for name in self.proposal_retired if name in fields]:
            binding, seeded = self.proposal_retired.pop(name)
            self.proposal_bindings[name] = binding
            self.proposal_seeded[name] = seeded
            values.setdefault(name, seeded)

    def replace_trial_input(self, values: dict, selected: dict) -> None:
        if values == self.values and selected == self.selected:
            return
        self.values = dict(values)
        self.selected = dict(selected)
        self.trial_input_revision += 1
