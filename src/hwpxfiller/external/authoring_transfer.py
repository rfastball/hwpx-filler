"""Explicit semantic copy/paste between authoring document snapshots.

The controller keeps captured data in memory; no generic OS clipboard or
unreviewed native paste is part of this boundary.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.field_occurrence import resolve_field_occurrences
from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.package import HwpxPackage
from hwpxcore.text_extract import HP_NS, require_package, section_xml_names

from ..domain.authoring import begin_marker_text
from ..domain.template_authoring import analyze as analyze_txt
from ..domain.text_render import iter_field_token_matches
from ..domain.text_structure import scan_text_token_spans
from .authoring_transfer_block import block_paste, next_id as _next_id, section_root as _root
from .hwpx_authoring import analyze_hwpx

_HP = f"{{{HP_NS}}}"


def _offset(text: str, units: object) -> int:
    if not isinstance(units, int) or units < 0:
        raise ValueError("고른 위치가 올바르지 않습니다.")
    position = 0
    for index, char in enumerate(text):
        if position == units:
            return index
        position += 2 if ord(char) > 0xFFFF else 1
        if position > units:
            break
    if position == units:
        return len(text)
    raise ValueError("고른 위치가 문자 경계에 있지 않습니다.")


def _units(text: str, index: int) -> int:
    return len(text[:index].encode("utf-16-le")) // 2


def _txt_capture(text: str, selector: Mapping[str, object]) -> dict:
    kind = selector.get("kind")
    detail = analyze_txt("txt", text)
    if kind == "field":
        position = _offset(text, selector.get("start"))
        match = next((item for item in iter_field_token_matches(text)
                      if item.start() <= position < item.end()), None)
        if match is None:
            raise ValueError("복사할 필드 사용 위치를 고르세요.")
        return {"kind": "field", "name": match.group(1).strip(), "text": match.group(0),
                "plain": match.group(1).strip()}
    if kind == "text":
        start, end = _offset(text, selector.get("start")), _offset(text, selector.get("end"))
        if start >= end:
            raise ValueError("복사할 본문을 고르세요.")
        snippet = text[start:end]
        if any(span.start < end and start < span.end for span in scan_text_token_spans(text)):
            raise ValueError("의미를 포함한 범위는 필드·항목·선택으로 복사하세요.")
        return {"kind": "text", "text": snippet, "plain": snippet}
    if kind not in {"slot", "option"}:
        raise ValueError("복사할 의미 요소를 고르세요.")
    location = next((item["location"] for slot in detail["slots"]
                     for item in ([slot] if kind == "slot" else slot["options"])
                     if (slot["id"] == selector.get("slot_id")
                         and (kind == "slot" or item["id"] == selector.get("option_id")))), None)
    if location is None or detail["diagnostics"]:
        raise ValueError("구조 오류가 있어 의미 영역을 복사할 수 없습니다.")
    start, end = _offset(text, location["start"]), _offset(text, location["end"])
    snippet = text[start:end]
    lines = snippet.splitlines(keepends=True)
    plain = "".join(line for line in lines if not line.lstrip().startswith(("{{#항목", "{{#선택", "{{/항목", "{{/선택")))
    for match in reversed(list(iter_field_token_matches(plain))):
        plain = plain[:match.start()] + match.group(1).strip() + plain[match.end():]
    return {"kind": kind, "id": selector.get("slot_id") if kind == "slot" else selector.get("option_id"),
            "label": next((item["label"] for slot in detail["slots"]
                           for item in ([slot] if kind == "slot" else slot["options"])
                           if slot["id"] == selector.get("slot_id")
                           and (kind == "slot" or item["id"] == selector.get("option_id"))), ""),
            "text": snippet, "plain": plain}


def capture_semantic(media: str, content: str | object, selector: Mapping[str, object]) -> dict:
    """Capture one exact semantic unit from a source snapshot."""
    if media == "txt" and isinstance(content, str):
        return {"media": media, **_txt_capture(content, selector)}
    if media == "hwpx":
        package = require_package(content)
        assert isinstance(package, HwpxPackage)
        detail = analyze_hwpx(package)
        kind = selector.get("kind")
        if detail["diagnostics"]:
            raise ValueError("구조 오류가 있어 의미를 복사할 수 없습니다.")
        if kind == "field":
            found = any(occurrence["entry"] == selector.get("entry")
                        and occurrence["occurrence"] == selector.get("occurrence")
                        and occurrence["pairing_id"] == selector.get("pairing_id")
                        for field in detail["fields"] for occurrence in field["occurrences"])
        elif kind == "slot":
            found = any(slot["id"] == selector.get("slot_id") for slot in detail["slots"])
        elif kind == "option":
            found = any(slot["id"] == selector.get("slot_id") and
                        any(option["id"] == selector.get("option_id") for option in slot["options"])
                        for slot in detail["slots"])
        else:
            found = False
        if not found:
            raise ValueError("복사할 의미 요소를 찾을 수 없습니다.")
        return {"media": media, "kind": kind, "source_bytes": package.to_bytes(),
                "selector": dict(selector)}
    raise ValueError("지원하지 않는 복사 형식입니다.")


def _txt_paste(text: str, captured: Mapping[str, object], destination: Mapping[str, object],
               with_meaning: bool) -> tuple[str, dict]:
    start, end = _offset(text, destination.get("start")), _offset(text, destination.get("end"))
    if start > end:
        raise ValueError("붙여넣을 범위가 올바르지 않습니다.")
    kind = captured["kind"]
    snippet = str(captured["text"] if with_meaning else captured["plain"])
    before = analyze_txt("txt", text)
    if with_meaning:
        names = {match.group(1).strip() for match in iter_field_token_matches(snippet)}
        existing = {item["name"] for item in before["fields"]}
        if names & existing and destination.get("link_existing") is not True:
            raise ValueError("같은 이름의 필드가 있습니다. 기존 필드 연결을 확인하세요.")
    if with_meaning and kind in {"slot", "option"}:
        if before["diagnostics"]:
            raise ValueError("대상 문서의 구조 오류를 먼저 수정하세요.")
        if start != end or (start != 0 and text[start - 1] not in "\r\n"):
            raise ValueError("의미 영역은 줄 시작 위치에 붙여넣으세요.")
        identifier = destination.get("new_id") or captured["id"]
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("새 식별자를 입력하세요.")
        if kind == "slot" and any(slot["id"] == identifier for slot in before["slots"]):
            raise ValueError("같은 항목 식별자가 있습니다. 새 식별자를 입력하세요.")
        if kind == "option":
            slot_id = destination.get("slot_id")
            owner = next((slot for slot in before["slots"] if slot["id"] == slot_id), None)
            if owner is None or any(option["id"] == identifier for option in owner["options"]):
                raise ValueError("상위 항목이나 선택 식별자를 확인하세요.")
        lines = snippet.splitlines(keepends=True)
        eol = "\r\n" if "\r\n" in lines[0] else "\n"
        lines[0] = begin_marker_text(str(kind), identifier, str(captured.get("label") or "")) + eol
        snippet = "".join(lines)
    result = text[:start] + snippet + text[end:]
    after = analyze_txt("txt", result)
    if with_meaning and kind in {"slot", "option"} and after["diagnostics"]:
        raise ValueError("이 위치에 붙여넣으면 항목·선택 구조가 깨집니다.")
    return result, {"edits": [{"start": _units(text, start), "end": _units(text, end), "text": snippet}],
                    "affected": 1, "before": text[start:end], "after": snippet,
                    "original": text[start:end], "captured_text": text[start:end],
                    "result": after, "expanded": False}


def _styles_compatible(source: HwpxPackage, target: HwpxPackage) -> bool:
    def dependencies(package: HwpxPackage) -> dict[str, bytes]:
        sections = set(section_xml_names(package))
        return {entry: raw for entry, raw in package.entries.items()
                if entry not in sections and entry != "mimetype"}
    return dependencies(source) == dependencies(target)


def _field_paste(source: HwpxPackage, target: HwpxPackage, selector: Mapping[str, object],
                 destination: Mapping[str, object], with_meaning: bool) -> tuple[str, str]:
    source_entry = selector.get("entry")
    entry = destination.get("entry")
    ordinal = selector.get("occurrence")
    paragraph_index = destination.get("paragraph")
    start, end = destination.get("start"), destination.get("end")
    if not isinstance(source_entry, str) or not isinstance(entry, str) or not isinstance(ordinal, int):
        raise ValueError("복사할 필드나 붙여넣을 영역을 확인하세요.")
    source_root = _root(source, source_entry)
    occurrences = resolve_field_occurrences(source_entry, source_root).require_usable()
    if not 0 <= ordinal < len(occurrences):
        raise ValueError("복사한 필드 위치를 찾을 수 없습니다.")
    occurrence = occurrences[ordinal]
    if occurrence.begin.get("id") != selector.get("pairing_id"):
        raise ValueError("복사한 필드 사용 위치가 바뀌었습니다.")
    name = occurrence.raw_name
    if not isinstance(name, str) or not name.strip():
        raise ValueError("필드 이름을 확인할 수 없습니다.")
    field_runs = [node for node in occurrence.paragraph if node.tag == f"{_HP}run"]
    first, last = field_runs.index(occurrence.begin_run), field_runs.index(occurrence.end_run)
    selected_texts = []
    for run in field_runs[first:last + 1]:
        children = list(run)
        lower = children.index(occurrence.begin_ctrl) + 1 if run is occurrence.begin_run else 0
        upper = children.index(occurrence.end_ctrl) if run is occurrence.end_run else len(children)
        for child in children[lower:upper]:
            if child.tag != f"{_HP}t" or len(child):
                raise ValueError("복사한 필드 안에 지원하지 않는 제어 요소가 있습니다.")
            selected_texts.append(child)
    if selected_texts != list(occurrence.texts):
        raise ValueError("복사한 필드 내용을 온전히 확인할 수 없습니다.")
    if (with_meaning and any(field["name"] == name for field in analyze_hwpx(target)["fields"])
            and destination.get("link_existing") is not True):
        raise ValueError("같은 이름의 필드가 있습니다. 기존 필드 연결을 확인하세요.")
    root = _root(target, entry)
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if not isinstance(paragraph_index, int) or not 0 <= paragraph_index < len(paragraphs):
        raise ValueError("붙여넣을 문단을 확인하세요.")
    if not isinstance(start, int) or not isinstance(end, int) or start > end:
        raise ValueError("붙여넣을 문자 범위를 확인하세요.")
    paragraph = paragraphs[paragraph_index]
    runs = [node for node in paragraph if node.tag == f"{_HP}run"]
    if len(runs) != 1 or len(runs[0]) != 1 or runs[0][0].tag != f"{_HP}t" or len(runs[0][0]):
        raise ValueError("복합 문단에는 의미 필드를 붙여넣을 수 없습니다.")
    original = runs[0][0].text or ""
    if not 0 <= start <= end <= len(original):
        raise ValueError("붙여넣을 문자 범위가 문단 밖에 있습니다.")
    copied_text = "".join(node.text or "" for node in occurrence.texts)
    new_runs = []
    if original[:start]:
        prefix = copy.deepcopy(runs[0])
        prefix[0].text = original[:start]
        new_runs.append(prefix)
    if with_meaning:
        next_id = _next_id(target)
        begin = etree.Element(f"{_HP}run", dict(occurrence.begin_run.attrib))
        begin_ctrl = copy.deepcopy(occurrence.begin_ctrl)
        begin_ctrl[0].set("id", str(next_id))
        begin_ctrl[0].set("fieldid", str(next_id + 1))
        begin.append(begin_ctrl)
        new_runs.append(begin)
    for node in occurrence.texts:
        run = etree.Element(f"{_HP}run", dict(node.getparent().attrib))
        run.append(copy.deepcopy(node))
        new_runs.append(run)
    if with_meaning:
        finish = etree.Element(f"{_HP}run", dict(occurrence.end_run.attrib))
        end_ctrl = copy.deepcopy(occurrence.end_ctrl)
        end_ctrl[0].set("beginIDRef", str(next_id))
        end_ctrl[0].set("fieldid", str(next_id + 1))
        finish.append(end_ctrl)
        new_runs.append(finish)
    if original[end:]:
        suffix = copy.deepcopy(runs[0])
        suffix[0].text = original[end:]
        new_runs.append(suffix)
    index = paragraph.index(runs[0])
    paragraph.remove(runs[0])
    for offset, run in enumerate(new_runs):
        paragraph.insert(index + offset, run)
    target.entries[entry] = serialize_modified_section(root)
    resolve_field_occurrences(entry, _root(target, entry)).require_usable()
    return original[start:end], copied_text


def paste_semantic(
    media: str, target_content: str | object, captured: Mapping[str, object],
    destination: Mapping[str, object], *, with_meaning: bool = True,
) -> tuple[str | HwpxPackage, dict]:
    """Paste a captured semantic unit into a disposable target snapshot."""
    if captured.get("media") != media:
        raise ValueError("서로 다른 파일 형식 사이의 의미 붙여넣기는 지원하지 않습니다.")
    if media == "txt" and isinstance(target_content, str):
        return _txt_paste(target_content, captured, destination, with_meaning)
    if media != "hwpx":
        raise ValueError("지원하지 않는 붙여넣기 형식입니다.")
    source_bytes = captured.get("source_bytes")
    selector = captured.get("selector")
    if not isinstance(source_bytes, bytes) or not isinstance(selector, Mapping):
        raise ValueError("복사한 의미 데이터가 올바르지 않습니다.")
    source = HwpxPackage.from_bytes(source_bytes)
    target = copy.deepcopy(require_package(target_content))
    assert isinstance(target, HwpxPackage)
    if not _styles_compatible(source, target):
        raise ValueError("두 HWPX 문서의 서식 참조가 달라 원래 모양을 보존할 수 없습니다.")
    if analyze_hwpx(target)["diagnostics"]:
        raise ValueError("대상 문서의 구조 오류를 먼저 수정하세요.")
    before = dict(target.entries)
    if captured["kind"] == "field":
        previous, inserted = _field_paste(source, target, selector, destination, with_meaning)
    else:
        previous, inserted = block_paste(source, target, selector, destination, with_meaning)
    result = analyze_hwpx(target)
    if result["diagnostics"]:
        raise ValueError("붙여넣으면 대상 문서의 의미 구조가 깨집니다.")
    changed = [entry for entry, raw in target.entries.items() if before.get(entry) != raw]
    return target, {"changed_entries": changed, "affected": 1, "before": previous,
                    "after": inserted, "original": previous, "captured_text": previous,
                    "result": result, "expanded": False}
