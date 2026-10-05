"""Native HWPX authoring: fields responsibilities."""

from __future__ import annotations

import copy
from collections.abc import Mapping

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.field_occurrence import resolve_field_occurrences
from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.text_extract import HP_NS

from ..domain import authoring as _authoring
from ..domain.fields import FieldDocument, is_fill_target_field_type
from ..domain.structure_scan import normalize_field_id
from ..domain.template_authoring import (
    REASON_FIX_STALE,
    REASON_FIELD_OVERLAP,
    REASON_INVALID_SELECTION,
    INVALID_FIELD_NAME,
    REASON_NO_FILLED_VALUE,
    InvalidName,
    NameConflict,
    field_placeholder,
    is_filled_value,
    whole_field_unset,
)
from .hwpx_product_inspection import (
    inspect_slots,
)

_HP = f"{{{HP_NS}}}"
from .hwpx_authoring_reading import (
    PARAGRAPH_UNRESOLVED as _PARAGRAPH_UNRESOLVED,
    body_hit_context as _body_hit_context,
    field_marks as _field_marks,
    field_range_refusal as _field_range_refusal,
    paragraph_pieces as _paragraph_pieces,
    paragraph_sites as _paragraph_sites,
    roots as _roots,
    selected_paragraph as _selected_paragraph,
)
from .hwpx_authoring_analysis import (
    fields as _fields,
)

_MULTI_PARAGRAPH_FIELD = "여러 문단에 걸친 필드는 HWPX 누름틀 경계로 만들 수 없습니다."
_COMPLEX_FIELD = "이 필드에는 복합 요소가 있어 내용 보존을 확인할 수 없습니다."

def _compile_token(package, command: Mapping[str, object]) -> str:
    """One token through the same 누름틀 변환 as the whole document — nothing else changes."""
    entry, path, start = command.get("entry"), command.get("paragraph_path"), command.get("token_start")
    name = normalize_field_id(command.get("name"))
    if not isinstance(entry, str) or not isinstance(path, str) or type(start) is not int or name is None:
        raise ValueError(REASON_FIX_STALE)
    assert isinstance(start, int)
    _, report = _authoring.compile_document(package, only=(entry, path, start))
    if len(report.compiled) != 1 or normalize_field_id(report.compiled[0]) != name:
        raise ValueError(REASON_FIX_STALE)
    return "{{" + report.compiled[0] + "}}"


def _require_clean(package) -> None:
    _slots, diagnostics = inspect_slots(package)
    if diagnostics:
        raise ValueError("문서 구조 오류를 먼저 수정하세요.")


def _field_name(raw: object) -> str:
    name = normalize_field_id(raw)
    if name is None or "{{" in name or "}}" in name or name.startswith(("#", "/")):
        raise InvalidName("name", INVALID_FIELD_NAME)
    return name


def _field_paragraph(package, roots: dict, site: Mapping[str, object]) -> tuple[str, etree._Element, int, int]:
    """한 필드 자리의 문단 — 문단 경로(``paragraph_path``), 또는 본문 문단 번호와 셀 경로(``cell_path``)."""
    entry = site.get("entry")
    if not isinstance(entry, str) or entry not in package.entries:
        raise ValueError("HWPX 문서 영역을 찾을 수 없습니다.")
    start, end = site.get("start"), site.get("end")
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in (start, end)):
        raise ValueError("문단 안의 정확한 문자 범위를 고르세요.")
    assert isinstance(start, int) and isinstance(end, int)
    if entry not in roots:
        roots[entry] = etree.fromstring(package.entries[entry])
    root = roots[entry]
    paragraph = _site_paragraph(root, site)
    if site.get("end_paragraph", site.get("paragraph")) != site.get("paragraph"):
        raise ValueError(_MULTI_PARAGRAPH_FIELD)
    return entry, paragraph, start, end


def _site_paragraph(root, site: Mapping[str, object]):
    paragraph_index = site.get("paragraph")
    paragraph_path = site.get("paragraph_path")
    if isinstance(paragraph_path, str):
        paragraphs = root.xpath(paragraph_path, namespaces=root.nsmap)
        if len(paragraphs) != 1 or paragraphs[0].tag != f"{_HP}p":
            raise ValueError(_PARAGRAPH_UNRESOLVED)
        paragraph = paragraphs[0]
    else:
        paragraph = _selected_paragraph(root, paragraph_index, site.get("cell_path"))
    return paragraph


def _field_ranges(command: Mapping[str, object]) -> list[Mapping[str, object]]:
    """``create_field`` 의 자리 목록 — ``ranges`` 가 없으면 고른 자리 하나다."""
    ranges = command.get("ranges")
    if ranges is None:
        return [command]
    if not isinstance(ranges, list) or not all(isinstance(item, Mapping) for item in ranges):
        raise ValueError(REASON_INVALID_SELECTION)
    return ranges


def _create_field(package, command: Mapping[str, object]) -> str:
    """고른 자리(와 ``ranges`` 의 자리들, IDE-07 P-07)에 같은 이름의 누름틀을 한 패키지 변형으로 끼운다.

    ``ranges`` 는 고른 자리를 포함한 자리 전부다. 자리마다 판정(제어 요소·문단 밖)은 **바꾸기 전** 문서에서 하고,
    같은 문단의 자리는 뒤에서부터 끼우며 끼울 때마다 문단 글자 자리를 다시 센다(앞 자리의 offset 은 밀리지 않는다).
    """
    roots: dict = {}
    primary = _field_paragraph(package, roots, command)
    sites = [_field_paragraph(package, roots, item) for item in _field_ranges(command)]
    if primary not in sites:
        raise ValueError(REASON_INVALID_SELECTION)
    captured = _paragraph_sites(primary[1])[2][primary[2]:primary[3]]
    _validate_create_sites(sites, captured)
    name = _field_name(command.get("name"))
    _insert_create_sites(roots, sites, name)
    for entry, root in roots.items():
        resolve_field_occurrences(entry, root).require_usable()
        package.entries[entry] = serialize_modified_section(root)
    return captured


def _create_fields(package, fields: list[Mapping[str, object]]) -> int:
    """이름이 다른 누름틀 여럿을 한 패키지 변형으로 끼운다(#1156 「모두 필드로」) — 자리 수를 돌려준다.

    이름마다 자리 판정은 :func:`_create_field` 와 같고 **바꾸기 전** 문서에서 한다. 끼우기는 모든 이름의 자리를 모아
    뒤에서부터 한다 — 같은 문단에 여러 이름의 자리가 있어도 앞 자리의 글자 위치가 밀리지 않는다.
    """
    roots: dict = {}
    planned: list[tuple] = []
    for item in fields:
        sites = [_field_paragraph(package, roots, site) for site in _field_ranges(item)]
        if not sites:
            raise ValueError(REASON_INVALID_SELECTION)
        _validate_create_sites(sites, _paragraph_sites(sites[0][1])[2][sites[0][2]:sites[0][3]])
        name = _field_name(item.get("name"))
        planned.extend((entry, paragraph, start, end, name) for entry, paragraph, start, end in sites)
    _validate_create_sites([site[:4] for site in planned], None)
    allocators = {entry: _authoring._make_id_allocator(root) for entry, root in roots.items()}
    for entry, paragraph, start, end, name in sorted(planned, key=lambda site: -site[2]):
        _insert_create_site(paragraph, start, end, name, allocators[entry])
    for entry, root in roots.items():
        resolve_field_occurrences(entry, root).require_usable()
        package.entries[entry] = serialize_modified_section(root)
    return len(planned)


def _validate_create_sites(sites, captured: str | None) -> None:
    for index, (_entry, paragraph, start, end) in enumerate(sites):
        text_sites, hazards, text = _paragraph_sites(paragraph)
        refusal = _field_range_refusal(text_sites, hazards, text, start, end)
        if refusal is not None:
            raise ValueError(refusal)
        # 같은 문구 N곳이다 — 다른 글자의 자리(옛 좌표)는 짐작해 끼우지 않는다(여러 이름이면 글자를 대조하지 않는다).
        if captured is not None and text[start:end] != captured:
            raise ValueError(REASON_INVALID_SELECTION)
        if any(other is paragraph and (lo < end and start < hi or (lo, hi) == (start, end))
               for _e, other, lo, hi in sites[index + 1:]):
            raise ValueError(REASON_FIELD_OVERLAP)


def _insert_create_sites(roots: dict, sites, name: str) -> None:
    allocators = {entry: _authoring._make_id_allocator(root) for entry, root in roots.items()}
    for entry, paragraph, start, end in sorted(sites, key=lambda site: -site[2]):
        _insert_create_site(paragraph, start, end, name, allocators[entry])


def _insert_create_site(paragraph, start: int, end: int, name: str, allocate) -> None:
    sites_now = _paragraph_sites(paragraph)[0]
    begin_id, field_id = allocate()
    begin_site = next((node for node, lo, hi in sites_now if lo <= start < hi), sites_now[-1][0])
    end_site = next((node for node, lo, hi in sites_now if lo < end <= hi), sites_now[0][0])
    begin_ctrl = _authoring._begin_run(dict(begin_site.getparent().attrib), name, begin_id, field_id)[0]
    end_ctrl = _authoring._end_run(dict(end_site.getparent().attrib), begin_id, field_id)[0]
    if start == end == 0:
        _insert_field_boundary(sites_now, start, begin_ctrl, beginning=True)
        _insert_field_boundary(sites_now, end, end_ctrl, beginning=False)
    else:
        _insert_field_boundary(sites_now, end, end_ctrl, beginning=False)
        _insert_field_boundary(sites_now, start, begin_ctrl, beginning=True)


def _insert_field_boundary(
    sites: list[tuple[etree._Element, int, int]],
    offset: int,
    control: etree._Element,
    *,
    beginning: bool,
) -> None:
    if beginning:
        site = next(((node, lo, hi) for node, lo, hi in sites if lo <= offset < hi), sites[-1])
    else:
        site = next(((node, lo, hi) for node, lo, hi in sites if lo < offset <= hi), sites[0])
    node, lo, _hi = site
    run = node.getparent()
    assert run is not None
    index = run.index(node)
    inner = offset - lo
    value = node.text or ""
    if inner == 0:
        run.insert(index, control)
    elif inner == len(value):
        run.insert(index + 1, control)
    else:
        suffix = copy.deepcopy(node)
        suffix.text = value[inner:]
        suffix.tail = node.tail
        node.text = value[:inner]
        node.tail = None
        run.insert(index + 1, control)
        run.insert(index + 2, suffix)


def _field_occurrence(root, entry: str, ordinal: object, pairing_id: object = None):
    if not isinstance(ordinal, int) or ordinal < 0:
        raise ValueError("필드 사용 위치가 올바르지 않습니다.")
    occurrences = resolve_field_occurrences(entry, root).require_usable()
    if ordinal >= len(occurrences):
        raise ValueError("필드 사용 위치를 찾을 수 없습니다.")
    target = occurrences[ordinal]
    if pairing_id is not None and target.begin.get("id") != pairing_id:
        raise ValueError("고른 필드 사용 위치가 바뀌었습니다. 다시 고르세요.")
    if not is_fill_target_field_type(target.field_type):
        raise ValueError("고른 요소는 채울 수 있는 필드가 아닙니다.")
    return target


def _change_field(package, command: Mapping[str, object]) -> int:
    action = command["type"]
    whole = whole_field_unset(command)
    old, new = _change_names(package, command, action, whole)
    if whole:
        _validate_whole_unset(package, old)
    count = 0
    for entry, root in _roots(package):
        targets = _change_targets(root, entry, command, action, whole, old)
        for target in targets:
            _change_target(target, command, action, new)
            count += 1
        if targets:
            resolve_field_occurrences(entry, root).require_usable()
            package.entries[entry] = serialize_modified_section(root)
    if not count:
        raise ValueError("필드를 찾을 수 없습니다.")
    return count


def _change_names(package, command, action, whole):
    old = _field_name(command.get("old_name")) if action == "rename_field" or whole else None
    new = _field_name(command.get("name")) if action in {"rename_field", "relink_field"} else None
    if action == "rename_field" and new != old:
        taken = next((item["count"] for item in _fields(package) if item["name"] == new), 0)
        if taken:
            assert isinstance(new, str)
            raise NameConflict(new, taken)
    return old, new


def _validate_whole_unset(package, old) -> None:
    # 필드 전체의 의미 해제(P-20)는 전부 아니면 전무다 — 한 자리라도 복합 요소면 아무 자리도 고치지 않는다.
    for entry, root in _roots(package):
        for item in resolve_field_occurrences(entry, root).require_usable():
            if (is_fill_target_field_type(item.field_type) and normalize_field_id(item.raw_name) == old
                    and (not item.texts or any(len(node) for node in item.texts))):
                raise ValueError(_COMPLEX_FIELD)


def _change_targets(root, entry, command, action, whole, old):
    if action == "rename_field" or whole:
        return [item for item in resolve_field_occurrences(entry, root).require_usable()
                if is_fill_target_field_type(item.field_type) and normalize_field_id(item.raw_name) == old]
    if entry == command.get("entry"):
        return [_field_occurrence(root, entry, command.get("occurrence"), command.get("pairing_id"))]
    return []


def _change_target(target, command, action, new) -> None:
    if action != "unset_field":
        target.begin.set("name", new)
        return
    replacement = command.get("text")
    if not isinstance(replacement, str):
        raise ValueError("의미를 해제한 뒤 남길 본문을 입력하세요.")
    if not target.texts or any(len(node) for node in target.texts):
        raise ValueError(_COMPLEX_FIELD)
    target.texts[0].text = replacement
    for node in target.texts[1:]:
        node.text = ""
    target.begin_ctrl.getparent().remove(target.begin_ctrl)
    target.end_ctrl.getparent().remove(target.end_ctrl)


def _revert_template(package) -> int:
    """모든 필드 값을 ``{{이름}}`` 원형으로 되돌린다(#1078) — 되돌린 사용 위치 수를 돌려준다.

    값 쓰기는 생성과 같은 채움 경로(:meth:`FieldDocument.set_field`)다 — 빈 누름틀·값 런의 인라인 요소를 생성과 같은
    규칙으로 다룬다. 실제 값이 든 이름만 쓴다(이미 원형인 자리는 바이트까지 그대로다). 한 자리라도 쓸 수 없으면 아무
    자리도 고치지 않는다(``_execute`` 가 원래 bytes 로 되돌린다) — 일부만 되돌린 문서를 성공으로 내지 않는다.
    """
    count = 0
    for entry in package.content_xml_names():
        count += _revert_section(package, entry)
    if not count:
        raise ValueError(REASON_NO_FILLED_VALUE)
    return count


def _revert_section(package, entry: str) -> int:
    document = FieldDocument(package.entries[entry], entry=entry)
    filled = [(name, value) for name, value in document.field_values() if is_filled_value(value, name)]
    for name in dict.fromkeys(name for name, _ in filled):
        if not document.set_field(name, field_placeholder(name)):
            raise ValueError(_COMPLEX_FIELD)
    if any(note.kind == "occurrence_unfillable" for note in document.notes):
        raise ValueError(_COMPLEX_FIELD)
    if document.modified:
        package.entries[entry] = document.to_bytes()
    return len(filled)


def _field_site_contexts(package, command: Mapping[str, object]) -> list[str]:
    """``ranges`` 자리마다 바꾸기 전 문맥 한 줄(문서 차례) — 좌표가 틀리면 ``_create_field`` 와 같은 거절이다."""
    roots: dict = {}
    sites = [_field_paragraph(package, roots, item) for item in _field_ranges(command)]
    order = {entry: {id(node): index for index, node in enumerate(root.iter(f"{_HP}p"))}
             for entry, root in roots.items()}
    marks = {entry: _field_marks(entry, root) for entry, root in roots.items()}
    return [_body_hit_context(_paragraph_pieces(paragraph, marks[entry]), start, end)
            for entry, paragraph, start, end in sorted(
                sites, key=lambda site: (site[0], order[site[0]][id(site[1])], site[2]))]


MULTI_PARAGRAPH_FIELD = _MULTI_PARAGRAPH_FIELD
change_field = _change_field
compile_token = _compile_token
create_field = _create_field
create_fields = _create_fields
field_site_contexts = _field_site_contexts
require_clean = _require_clean
revert_template = _revert_template
