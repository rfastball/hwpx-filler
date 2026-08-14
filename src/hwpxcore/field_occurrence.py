"""Resolve native ordinary Field occurrences on the supported HWPX lanes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from lxml import etree

from .text_extract import HP_NS, local_name

_HP = f"{{{HP_NS}}}"


class FieldDiagnosticKind(StrEnum):
    """Format failures that make an entry's ordinary Field pairing unusable."""

    UNMATCHED_BEGIN = "unmatched-begin"
    ORPHAN_END = "orphan-end"
    AMBIGUOUS_END = "ambiguous-end"
    NESTED_FIELD = "nested-field"
    NON_NATIVE_FIELD_CONTROL = "non-native-field-control"
    UNSUPPORTED_CONTROL_SHAPE = "unsupported-control-shape"
    UNSUPPORTED_TRAVERSAL_LANE = "unsupported-traversal-lane"
    PARAGRAPH_CROSSING = "paragraph-crossing"
    UNSUPPORTED_CONTAINER_CROSSING = "unsupported-container-crossing"


@dataclass(frozen=True)
class FieldDiagnostic:
    entry: str
    kind: FieldDiagnosticKind
    order: int
    detail: str = ""

    def __str__(self) -> str:
        suffix = f" ({self.detail})" if self.detail else ""
        return f"{self.entry}: {self.kind.value} at element {self.order}{suffix}"


class FieldPairingError(ValueError):
    """Raised when a consumer requires a trustworthy Field pairing."""

    def __init__(self, diagnostics: "tuple[FieldDiagnostic, ...]") -> None:
        self.diagnostics = diagnostics
        super().__init__("; ".join(map(str, diagnostics)))


@dataclass(frozen=True)
class FieldOccurrence:
    """One native ordinary Field pair in entry-local XML order."""

    entry: str
    raw_name: str | None
    begin_order: int
    end_order: int
    begin: etree._Element
    end: etree._Element
    paragraph: etree._Element
    begin_ctrl: etree._Element
    end_ctrl: etree._Element
    begin_run: etree._Element
    end_run: etree._Element
    texts: "tuple[etree._Element, ...]"


@dataclass(frozen=True)
class FieldResolution:
    """Entry-local ordinary Field pairs plus fail-closed format diagnostics."""

    entry: str
    occurrences: "tuple[FieldOccurrence, ...]"
    diagnostics: "tuple[FieldDiagnostic, ...]"

    @property
    def pairing_usable(self) -> bool:
        return not self.diagnostics

    def require_usable(self) -> "tuple[FieldOccurrence, ...]":
        if self.diagnostics:
            raise FieldPairingError(self.diagnostics)
        return self.occurrences


@dataclass(frozen=True)
class _Position:
    ctrl: etree._Element
    run: etree._Element
    paragraph: etree._Element
    container: etree._Element


def paragraph_container(
    paragraph: etree._Element, root: etree._Element
) -> "etree._Element | None":
    parent = paragraph.getparent()
    if parent is root:
        return root
    if parent is None or parent.tag != f"{_HP}subList":
        return None

    owner = parent.getparent()
    if owner is None:
        return None
    if owner.tag == f"{_HP}tc":
        tr = owner.getparent()
        if tr is None or tr.tag != f"{_HP}tr":
            return None
        table = tr.getparent()
    elif owner.tag == f"{_HP}caption":
        table = owner.getparent()
    else:
        return None

    owner_run = table.getparent() if table is not None else None
    owner_paragraph = owner_run.getparent() if owner_run is not None else None
    if (
        table is None
        or owner_run is None
        or owner_paragraph is None
        or table.tag != f"{_HP}tbl"
        or owner_run.tag != f"{_HP}run"
        or owner_paragraph.tag != f"{_HP}p"
        or paragraph_container(owner_paragraph, root) is None
    ):
        return None
    return parent


def _position(
    node: etree._Element, root: etree._Element
) -> "tuple[_Position | None, FieldDiagnosticKind | None]":
    ctrl = node.getparent()
    run = ctrl.getparent() if ctrl is not None else None
    paragraph = run.getparent() if run is not None else None
    if (
        ctrl is None
        or run is None
        or paragraph is None
        or ctrl.tag != f"{_HP}ctrl"
        or run.tag != f"{_HP}run"
        or paragraph.tag != f"{_HP}p"
    ):
        return None, FieldDiagnosticKind.UNSUPPORTED_CONTROL_SHAPE

    container = paragraph_container(paragraph, root)
    if container is None:
        return None, FieldDiagnosticKind.UNSUPPORTED_TRAVERSAL_LANE
    return _Position(ctrl, run, paragraph, container), None


def resolve_field_occurrences(
    entry: str, root: etree._Element
) -> FieldResolution:
    """Resolve non-BOOKMARK Fields without guessing past malformed markers.

    Pairing is entry-local and limited to one supported paragraph lane. Native
    ``id``/``beginIDRef`` links win when present; the legacy id-less shape is
    paired only by an unambiguous begin-then-end sequence on that same lane.
    Invalid names remain occurrences because name semantics belong to the
    product layer, not this format kernel.
    """
    nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    order = {node: index for index, node in enumerate(nodes)}
    diagnostics: "list[FieldDiagnostic]" = []
    reported: "set[tuple[FieldDiagnosticKind, int, str]]" = set()

    def report(
        kind: FieldDiagnosticKind, node: etree._Element, detail: str = ""
    ) -> None:
        key = kind, order[node], detail
        if key not in reported:
            reported.add(key)
            diagnostics.append(FieldDiagnostic(entry, kind, order[node], detail))

    ordinary_begins = [
        node
        for node in nodes
        if local_name(node.tag) == "fieldBegin" and node.get("type") != "BOOKMARK"
    ]
    ordinary_ids = {
        pair_id for node in ordinary_begins if (pair_id := node.get("id"))
    }
    bookmark_ids = {
        pair_id
        for node in nodes
        if local_name(node.tag) == "fieldBegin"
        and node.get("type") == "BOOKMARK"
        and (pair_id := node.get("id"))
    }

    positions: "dict[etree._Element, _Position]" = {}
    valid_begins: "list[etree._Element]" = []
    for begin in ordinary_begins:
        if begin.tag != f"{_HP}fieldBegin":
            report(FieldDiagnosticKind.NON_NATIVE_FIELD_CONTROL, begin)
            continue
        position, failure = _position(begin, root)
        if failure is not None:
            report(failure, begin)
            continue
        assert position is not None
        positions[begin] = position
        valid_begins.append(begin)

    valid_ends: "list[etree._Element]" = []
    for end in (node for node in nodes if local_name(node.tag) == "fieldEnd"):
        begin_ref = end.get("beginIDRef")
        if begin_ref in bookmark_ids and begin_ref not in ordinary_ids:
            continue
        if end.tag != f"{_HP}fieldEnd":
            report(FieldDiagnosticKind.NON_NATIVE_FIELD_CONTROL, end)
            continue
        position, failure = _position(end, root)
        if failure is not None:
            report(failure, end)
            continue
        assert position is not None
        positions[end] = position
        valid_ends.append(end)

    begins_by_id: "dict[str, list[etree._Element]]" = {}
    ends_by_ref: "dict[str, list[etree._Element]]" = {}
    for begin in valid_begins:
        if pair_id := begin.get("id"):
            begins_by_id.setdefault(pair_id, []).append(begin)
    for end in valid_ends:
        if begin_ref := end.get("beginIDRef"):
            ends_by_ref.setdefault(begin_ref, []).append(end)

    blocked: "set[etree._Element]" = set()
    for begin_ref, ends in ends_by_ref.items():
        begins = begins_by_id.get(begin_ref, [])
        if begin_ref in bookmark_ids or len(begins) > 1 or len(ends) > 1:
            report(
                FieldDiagnosticKind.AMBIGUOUS_END,
                ends[0],
                f"beginIDRef={begin_ref!r}",
            )
            blocked.update(begins)
            blocked.update(ends)
            continue
        if len(begins) != 1:
            continue
        begin, end = begins[0], ends[0]
        begin_position, end_position = positions[begin], positions[end]
        if begin_position.paragraph is end_position.paragraph:
            continue
        kind = (
            FieldDiagnosticKind.PARAGRAPH_CROSSING
            if begin_position.container is end_position.container
            else FieldDiagnosticKind.UNSUPPORTED_CONTAINER_CROSSING
        )
        report(kind, end, f"beginIDRef={begin_ref!r}")
        blocked.update((begin, end))

    lanes: "dict[etree._Element, list[tuple[str, etree._Element]]]" = {}
    for begin in valid_begins:
        if begin not in blocked:
            lanes.setdefault(positions[begin].paragraph, []).append(("begin", begin))
    for end in valid_ends:
        if end not in blocked:
            lanes.setdefault(positions[end].paragraph, []).append(("end", end))

    occurrences: "list[FieldOccurrence]" = []
    for markers in sorted(lanes.values(), key=lambda lane: min(order[node] for _, node in lane)):
        markers.sort(key=lambda marker: order[marker[1]])
        opened: "etree._Element | None" = None
        poisoned = False
        for marker_kind, node in markers:
            if poisoned:
                continue
            if marker_kind == "begin":
                if opened is not None:
                    report(FieldDiagnosticKind.NESTED_FIELD, node)
                    poisoned = True
                    opened = None
                else:
                    opened = node
                continue

            if opened is None:
                report(FieldDiagnosticKind.ORPHAN_END, node)
                poisoned = True
                continue
            begin_ref = node.get("beginIDRef")
            begin_id = opened.get("id")
            if (begin_id is None) != (begin_ref is None) or (
                begin_ref is not None and begin_ref != begin_id
            ):
                report(
                    FieldDiagnosticKind.ORPHAN_END,
                    node,
                    f"beginIDRef={begin_ref!r}",
                )
                poisoned = True
                opened = None
                continue

            begin_position, end_position = positions[opened], positions[node]
            first_run = begin_position.paragraph.index(begin_position.run)
            last_run = begin_position.paragraph.index(end_position.run)
            if any(
                child.tag != f"{_HP}run"
                for child in list(begin_position.paragraph)[first_run : last_run + 1]
            ):
                report(FieldDiagnosticKind.UNSUPPORTED_TRAVERSAL_LANE, node)
                poisoned = True
                opened = None
                continue
            begin_order, end_order = order[opened], order[node]
            texts = tuple(
                child
                for run in begin_position.paragraph
                if run.tag == f"{_HP}run"
                for child in run
                if child.tag == f"{_HP}t"
                and begin_order < order[child] < end_order
            )
            occurrences.append(
                FieldOccurrence(
                    entry=entry,
                    raw_name=opened.get("name"),
                    begin_order=begin_order,
                    end_order=end_order,
                    begin=opened,
                    end=node,
                    paragraph=begin_position.paragraph,
                    begin_ctrl=begin_position.ctrl,
                    end_ctrl=end_position.ctrl,
                    begin_run=begin_position.run,
                    end_run=end_position.run,
                    texts=texts,
                )
            )
            opened = None
        if opened is not None and not poisoned:
            report(FieldDiagnosticKind.UNMATCHED_BEGIN, opened)

    resolved = tuple(sorted(occurrences, key=lambda item: item.begin_order))
    for previous, current in zip(resolved, resolved[1:], strict=False):
        if current.begin_order < previous.end_order:
            report(FieldDiagnosticKind.NESTED_FIELD, current.begin)

    diagnostics.sort(key=lambda item: (item.order, item.kind.value, item.detail))
    return FieldResolution(entry, () if diagnostics else resolved, tuple(diagnostics))
