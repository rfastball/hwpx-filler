"""Read-only HWPX XML structure observer for S0 experiments.

JSON Lines are facts only: package entry, XML position, containment, text, and
attributes.  The probe never joins two markers into a range.  Synthetic input
can validate this observer, but cannot establish Hancom's native semantics.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lxml import etree

from hwpxcore.package import HwpxPackage
from hwpxcore.text_extract import local_name, section_xml_names

_CONTAINERS = frozenset({"tbl", "tr", "tc", "subList", "caption"})
_SPECIAL = frozenset({"bookmark", "metaTag", "fieldBegin", "fieldEnd"})


def _path(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None:
        name = local_name(current.tag) or "#node"
        parent = current.getparent()
        siblings = (
            [child for child in parent if local_name(child.tag) == name]
            if parent is not None
            else [current]
        )
        parts.append(f"{name}[{siblings.index(current)}]")
        current = parent
    return "/".join(reversed(parts))


def _attrs(node: etree._Element) -> dict[str, str]:
    return {
        local_name(name): value
        for name, value in sorted(node.attrib.items(), key=lambda item: local_name(item[0]))
    }


def _children(node: etree._Element) -> list[str]:
    return [local_name(child.tag) or "#node" for child in node]


def _is_boundary_marker(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith(("begin", "end", "start"))


def dump_structure(pkg: object) -> str:
    """Return deterministic JSON Lines for every section's structural facts."""
    records: list[dict[str, object]] = []
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)

    for section, entry in enumerate(section_xml_names(pkg)):
        root = etree.fromstring(pkg.entries[entry], parser=parser)  # type: ignore[attr-defined]
        records.append({"entry": entry, "kind": "section", "section": section})
        paragraph_order = 0

        def control(
            node: etree._Element,
            paragraph: int,
            run: int,
            entry: str = entry,
            section: int = section,
        ) -> None:
            name = local_name(node.tag) or "#node"
            record: dict[str, object] = {
                "attrs": _attrs(node),
                "child_index": node.getparent().index(node) if node.getparent() is not None else 0,
                "children": _children(node),
                "entry": entry,
                "kind": "control",
                "paragraph": paragraph,
                "path": _path(node),
                "run": run,
                "section": section,
                "tag": name,
            }
            if name in _SPECIAL or _is_boundary_marker(name):
                record["role"] = name
            if name == "metaTag":
                record["value"] = "".join(node.itertext())
            records.append(record)
            for child in node:
                child_name = local_name(child.tag)
                if name == "ctrl" or child_name in _SPECIAL or _is_boundary_marker(child_name):
                    control(child, paragraph, run)

        def walk(
            node: etree._Element,
            entry: str = entry,
            section: int = section,
        ) -> None:
            nonlocal paragraph_order
            name = local_name(node.tag)
            if name in _CONTAINERS:
                records.append(
                    {
                        "attrs": _attrs(node),
                        "children": _children(node),
                        "entry": entry,
                        "kind": "container",
                        "parent": _path(node.getparent()) if node.getparent() is not None else None,
                        "path": _path(node),
                        "section": section,
                        "tag": name,
                    }
                )
            if name == "p":
                paragraph = paragraph_order
                paragraph_order += 1
                parent = node.getparent()
                records.append(
                    {
                        "entry": entry,
                        "id": node.get("id"),
                        "kind": "paragraph",
                        "paragraph": paragraph,
                        "parent": _path(parent) if parent is not None else None,
                        "path": _path(node),
                        "section": section,
                    }
                )
                runs = [child for child in node if local_name(child.tag) == "run"]
                for run, run_node in enumerate(runs):
                    text = "".join(
                        "".join(child.itertext())
                        for child in run_node
                        if local_name(child.tag) == "t"
                    )
                    records.append(
                        {
                            "entry": entry,
                            "kind": "run",
                            "paragraph": paragraph,
                            "path": _path(run_node),
                            "run": run,
                            "section": section,
                            "text": text,
                        }
                    )
                    for child in run_node:
                        child_name = local_name(child.tag)
                        if child_name == "t":
                            for inline in child:
                                control(inline, paragraph, run)
                        elif child_name == "ctrl":
                            control(child, paragraph, run)
                        elif child_name not in _CONTAINERS:
                            control(child, paragraph, run)
            for child in node:
                walk(child)

        walk(root)

    return "\n".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for record in records
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python tests/_hwpx_structure_probe.py FILE.hwpx", file=sys.stderr)
        return 2
    print(dump_structure(HwpxPackage.from_bytes(Path(args[0]).read_bytes())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
