"""Test-only S0-D6 spike for a minimal block BOOKMARK encoding."""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.package import HwpxPackage
from hwpxcore.text_extract import HP_NS, local_name, require_package

SECTION = "Contents/section0.xml"
PAIRING_ID = "1600000001"
BOOKMARK_NAME = "S0_GENERATED"


def _paragraph_text(paragraph: etree._Element) -> str:
    return "".join(
        "".join(node.itertext())
        for node in paragraph.iter()
        if local_name(node.tag) == "t"
    )


def add_minimal_bookmark(pkg: object) -> None:
    """Add one BBB-through-DDD BOOKMARK to the known R0 experiment shape."""
    package = require_package(pkg)
    root = etree.fromstring(
        package.entries[SECTION],
        parser=etree.XMLParser(remove_blank_text=False, resolve_entities=False),
    )
    paragraphs = [child for child in root if local_name(child.tag) == "p"]

    def unique_paragraph(text: str) -> etree._Element:
        matches = [paragraph for paragraph in paragraphs if _paragraph_text(paragraph) == text]
        if len(matches) != 1:
            raise ValueError(f"expected one top-level paragraph {text!r}; found {len(matches)}")
        return matches[0]

    start, end = unique_paragraph("BBB"), unique_paragraph("DDD")
    start_runs = [child for child in start if local_name(child.tag) == "run"]
    end_runs = [child for child in end if local_name(child.tag) == "run"]
    if len(start_runs) != 1 or len(end_runs) != 1:
        raise ValueError("R0 boundary paragraphs must each contain exactly one run")

    begin_ctrl = etree.Element(f"{{{HP_NS}}}ctrl")
    etree.SubElement(
        begin_ctrl,
        f"{{{HP_NS}}}fieldBegin",
        id=PAIRING_ID,
        type="BOOKMARK",
        name=BOOKMARK_NAME,
    )
    start_runs[0].insert(0, begin_ctrl)

    end_ctrl = etree.Element(f"{{{HP_NS}}}ctrl")
    etree.SubElement(end_ctrl, f"{{{HP_NS}}}fieldEnd", beginIDRef=PAIRING_ID)
    end_runs[0].append(end_ctrl)
    package.entries[SECTION] = serialize_modified_section(root)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python tests/_hwpx_bookmark_creation_spike.py INPUT OUTPUT")
        return 2
    package = HwpxPackage.from_bytes(Path(args[0]).read_bytes())
    add_minimal_bookmark(package)
    Path(args[1]).write_bytes(package.to_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
