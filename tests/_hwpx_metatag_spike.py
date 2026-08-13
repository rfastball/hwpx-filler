"""Test-only S1 spike: observe and author HWPX native metadata carriers.

The dump side is carrier-agnostic — it reports every ``metaTag`` element, every
``metaTag``/``metatag`` attribute, every ``opf:meta`` document property and the
package entry list, without deciding which one is "the" carrier.  The authoring
side writes one candidate carrier per probe file so a single Hancom open/save
round-trip can be read as independent cells.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lxml import etree

from _hwpx_structure_probe import _path
from hwpxcore.bookmark_region import append_bookmark_metatag, resolve_bookmark_regions
from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.package import HwpxPackage
from hwpxcore.text_extract import HP_NS, local_name, require_package
from hwpxfiller.domain.slot import Slot, SlotOption
from hwpxfiller.external.template_inspection import (
    serialize_slot_metatag,
    serialize_slot_option_metatag,
)

SECTION = "Contents/section0.xml"
HEADER = "Contents/header.xml"
MANIFEST = "Contents/content.hpf"
HH_NS = "http://www.hancom.co.kr/hwpml/2011/head"
OPF_NS = "http://www.idpf.org/2007/opf/"
XML_ENTRIES = (".xml", ".hpf")

# Package-level probes: an opf:meta name and package entries Hancom never writes.
CATALOG_META_NAME = "hwpxFiller:s1probe"
DECLARED_ENTRY = "Contents/hwpxfiller-s1-declared.json"
UNDECLARED_ENTRY = "Contents/hwpxfiller-s1-undeclared.json"

# Three adjacent, non-overlapping BOOKMARK regions over R0's BBB/CCC/DDD.
REGIONS = (
    ("HF_S1_ANCHOR", "BBB", "1700000001"),
    ("HF_S1_OPT_BONUS", "CCC", "1700000002"),
    ("HF_S1_OPT_SPECIAL", "DDD", "1700000003"),
)


def metatag_carriers(pkg: object) -> dict[str, str]:
    """Return every observed native metadata carrier value, keyed by location."""
    package = require_package(pkg)
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    found: dict[str, str] = {"#entries": ", ".join(sorted(package.entries))}

    for entry in sorted(package.entries):
        if not entry.endswith(XML_ENTRIES):
            continue
        for node in etree.fromstring(package.entries[entry], parser).iter():
            for name, value in node.attrib.items():
                if local_name(name).lower() == "metatag":
                    found[f"{entry}|{_path(node)}|@{local_name(name)}"] = value
            if local_name(node.tag) == "metaTag":
                found[f"{entry}|{_path(node)}|#text"] = "".join(node.itertext())
            elif node.tag == f"{{{OPF_NS}}}meta":
                found[f"{entry}|opf:meta[@name={node.get('name')}]"] = node.text or ""
    return found


def _payload(tag: str, **extra: object) -> str:
    """Hancom-shaped metaTag payload carrying extra properties Hancom never wrote.

    ``name`` is serialized last and ``#`` appears only inside it, so Hancom's own
    metatag-ex slice (first ``#`` to last ``"``) still recovers the bare tag name.
    """
    return json.dumps(
        {
            "hwpxFiller": {
                "v": 1,
                "label": "추가 지급 안내",
                "quoted": 'he said "yes" & <no>',
                "uuid": "7fa3c0de-0000-4000-8000-0123456789ab",
                "spaced": "  leading and trailing  ",
                "long": "가" * 512,
                **extra,
            },
            "name": f"#{tag}",
        },
        ensure_ascii=False,
    )


def _catalog_payload() -> str:
    """Document-level catalog referencing the three regions by bookmark name."""
    return json.dumps(
        {
            "hwpxFiller": {
                "v": 1,
                "slots": [
                    {
                        "id": "extra_notice",
                        "label": "추가 지급 안내",
                        "cardinality": "exactly_one",
                        "min_options": 2,
                        "anchor": "HF_S1_ANCHOR",
                        "options": [
                            {"id": "bonus", "anchor": "HF_S1_OPT_BONUS"},
                            {"id": "special", "anchor": "HF_S1_OPT_SPECIAL"},
                        ],
                    }
                ],
            },
            "name": "#hf_s1_catalog",
        },
        ensure_ascii=False,
    )


def _paragraph_text(paragraph: etree._Element) -> str:
    return "".join(
        "".join(node.itertext())
        for node in paragraph.iter()
        if local_name(node.tag) == "t"
    )


def _parse(package: HwpxPackage, entry: str) -> etree._Element:
    return etree.fromstring(
        package.entries[entry],
        etree.XMLParser(remove_blank_text=False, resolve_entities=False),
    )


def _write(package: HwpxPackage, entry: str, root: etree._Element) -> None:
    package.entries[entry] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )


def _meta_tag(parent: etree._Element, namespace: str, value: str) -> None:
    """Append the modelled ``metaTag`` child element, which OWPML orders last."""
    child = etree.SubElement(parent, f"{{{namespace}}}metaTag")
    child.text = value


def build_element_probe(pkg: object) -> None:
    """Author three BOOKMARK regions carrying ``hp:metaTag``, plus ``hh:metaTag``."""
    package = require_package(pkg)
    root = _parse(package, SECTION)
    paragraphs = [child for child in root if local_name(child.tag) == "p"]

    for name, text, pairing_id in REGIONS:
        matches = [p for p in paragraphs if _paragraph_text(p) == text]
        if len(matches) != 1:
            raise ValueError(f"expected one top-level paragraph {text!r}; found {len(matches)}")
        runs = [child for child in matches[0] if local_name(child.tag) == "run"]
        if len(runs) != 1:
            raise ValueError(f"paragraph {text!r} must contain exactly one run")

        begin_ctrl = etree.Element(f"{{{HP_NS}}}ctrl")
        begin = etree.SubElement(
            begin_ctrl, f"{{{HP_NS}}}fieldBegin", id=pairing_id, type="BOOKMARK", name=name
        )
        _meta_tag(begin, HP_NS, _payload(name.lower(), anchor=name))
        runs[0].insert(0, begin_ctrl)

        end_ctrl = etree.Element(f"{{{HP_NS}}}ctrl")
        etree.SubElement(end_ctrl, f"{{{HP_NS}}}fieldEnd", beginIDRef=pairing_id)
        runs[0].append(end_ctrl)
    package.entries[SECTION] = serialize_modified_section(root)

    header = _parse(package, HEADER)
    _meta_tag(header, HH_NS, _catalog_payload())
    _write(package, HEADER, header)


def build_attribute_probe(pkg: object) -> None:
    """Fill the two attribute-shaped carriers on Hancom's own R3 objects."""
    package = require_package(pkg)
    root = _parse(package, SECTION)

    fields = [
        node
        for node in root.iter(f"{{{HP_NS}}}fieldBegin")
        if node.get("metaTag") == ""
    ]
    tables = list(root.iter(f"{{{HP_NS}}}tbl"))
    sublists = list(root.iter(f"{{{HP_NS}}}subList"))
    if not (fields and tables and sublists):
        raise ValueError(f"{SECTION}: needs a fieldBegin@metaTag, a tbl and a subList")

    # Out-of-model camel attribute Hancom itself emits; not in the OWPML model.
    fields[0].set("metaTag", _payload("hf_s1_field_attr"))
    # Modelled child element on a table object.
    _meta_tag(tables[0], HP_NS, _payload("hf_s1_table"))
    # Modelled lowercase attribute, the only one OWPML declares (on ParaListType).
    sublists[0].set("metatag", _payload("hf_s1_sublist"))
    package.entries[SECTION] = serialize_modified_section(root)


def build_package_probe(pkg: object) -> None:
    """Add a custom ``opf:meta`` and two package-local catalog entries."""
    package = require_package(pkg)
    payload = _catalog_payload().encode()
    package.entries[DECLARED_ENTRY] = payload
    package.entries[UNDECLARED_ENTRY] = payload

    manifest = _parse(package, MANIFEST)
    metadata = manifest.find(f"{{{OPF_NS}}}metadata")
    items = manifest.find(f"{{{OPF_NS}}}manifest")
    if metadata is None or items is None:
        raise ValueError(f"{MANIFEST}: no opf:metadata or opf:manifest element")
    meta = etree.SubElement(
        metadata, f"{{{OPF_NS}}}meta", name=CATALOG_META_NAME, content="text"
    )
    meta.text = _catalog_payload()
    etree.SubElement(
        items,
        f"{{{OPF_NS}}}item",
        id="hwpxfiller-s1",
        href=DECLARED_ENTRY,
        attrib={"media-type": "application/json"},
    )
    _write(package, MANIFEST, manifest)


def build_slot_probe(pkg: object) -> None:
    """Author canonical Slot/Option payloads on S0's nested BOOKMARK corpus."""
    package = require_package(pkg)
    options = (
        SlotOption("성과급 안내", 0),
        SlotOption("특별수당 안내", 1),
    )
    payloads = (
        (
            "S0_SLOT",
            serialize_slot_metatag(Slot("추가 지급 안내", options)),
        ),
        ("S0_OPT_A", serialize_slot_option_metatag(options[0])),
        ("S0_OPT_B", serialize_slot_option_metatag(options[1])),
    )
    for name, payload in payloads:
        matches = [region for region in resolve_bookmark_regions(package) if region.name == name]
        if len(matches) != 1:
            raise ValueError(f"expected one BOOKMARK named {name!r}; found {len(matches)}")
        append_bookmark_metatag(package, matches[0], payload)


BUILDERS = {
    "build-element": build_element_probe,
    "build-attribute": build_attribute_probe,
    "build-package": build_package_probe,
    "build-slot": build_slot_probe,
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 2 and args[0] == "dump":
        package = HwpxPackage.from_bytes(Path(args[1]).read_bytes())
        for key, value in sorted(metatag_carriers(package).items()):
            print(f"{key}\t{value!r}")
        return 0
    if len(args) == 3 and args[0] in BUILDERS:
        package = HwpxPackage.from_bytes(Path(args[1]).read_bytes())
        BUILDERS[args[0]](package)
        Path(args[2]).write_bytes(package.to_bytes())
        return 0
    print(
        "usage: python tests/_hwpx_metatag_spike.py "
        f"(dump FILE | {' | '.join(f'{name} IN OUT' for name in BUILDERS)})",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
