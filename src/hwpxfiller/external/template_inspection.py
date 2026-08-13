"""HWPX 템플릿 판독·컴파일 파일 효과의 외부 어댑터.

파서 의미론 층(schema·authoring·template_status·lint·fields)은 **열린 package 전용**이다
(P2-19R, #576). 경로를 받아 package adapter로 한 번 열고 Domain 순수
함수를 부르는 path 진입 함수들이 여기 산다 — ring 2/Host 는 직접 부르고, Application VM
(gui)은 External 을 import 할 수 없어 ring 2 가 이 함수들을 포트로 결속해 주입한다
(P2-12 ``inspect_hwpx_template`` 동형).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from hwpxcore.bookmark_region import (
    BookmarkRegion,
    remove_bookmark_region,
    resolve_bookmark_topology,
)
from hwpxcore.text_extract import require_package
from lxml import etree

from ..domain.authoring import CompileReport, TokenSite, compile_document, scan_tokens
from ..domain.fields import fill_precheck, read_fields
from ..domain.lint import LintReport, SchemaDrift, diff_schema, lint_template
from ..domain.schema import extract_schema
from ..domain.slot import Slot, SlotOption
from ..domain.template_status import TemplateStatus, compile_status
from ..gui.template_manager_state import (
    TemplateDiagnostic,
    TemplateFileOps,
    TemplateInspection,
)
from .hwpx_package_io import read_hwpx_package, write_hwpx_package

_PRODUCT_KINDS = frozenset({"slot", "slot_option"})
_NATIVE_NAME = "#hf"


class _ProductTag(NamedTuple):
    region: BookmarkRegion
    kind: str
    id: str


class _SlotSnapshot(NamedTuple):
    slots: tuple[Slot, ...]
    diagnostics: tuple[TemplateDiagnostic, ...]
    slot_regions: dict[str, BookmarkRegion]
    option_regions: dict[tuple[str, str], BookmarkRegion]


def _diagnostic(kind: str, region: BookmarkRegion, detail: str) -> TemplateDiagnostic:
    return TemplateDiagnostic(kind, f"{region.section}: BOOKMARK {region.name!r}: {detail}")


def _ancestors(region: BookmarkRegion) -> list[BookmarkRegion]:
    ancestors: list[BookmarkRegion] = []
    current = region.parent
    while current is not None:
        ancestors.append(current)
        current = current.parent
    return ancestors


def _serialize_product_metatag(kind: str, identifier: str) -> str:
    return json.dumps(
        {"hwpxFiller": {"kind": kind, "id": identifier}, "name": _NATIVE_NAME},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def serialize_slot_metatag(slot: Slot) -> str:
    """Serialize one canonical object-local Slot payload; native ``name`` is last."""
    _require_text(slot.id, "Slot id")
    return _serialize_product_metatag("slot", slot.id)


def serialize_slot_option_metatag(option: SlotOption) -> str:
    """Serialize one canonical object-local Slot Option payload."""
    _require_text(option.id, "Slot Option id")
    return _serialize_product_metatag("slot_option", option.id)


def _product_tag(
    region: BookmarkRegion,
    diagnostics: list[TemplateDiagnostic],
    recognised: dict[BookmarkRegion, str],
) -> _ProductTag | None:
    parsed: list[dict[str, object]] = []
    for raw in region.meta_tags:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            diagnostics.append(_diagnostic("malformed-json", region, "invalid MetaTag JSON"))
            continue
        if not isinstance(value, dict):
            continue
        if "hwpxFiller" not in value:
            if value.get("name") == _NATIVE_NAME:
                diagnostics.append(
                    _diagnostic(
                        "invalid-product-payload",
                        region,
                        "canonical product MetaTag has no hwpxFiller object",
                    )
                )
            continue
        parsed.append(value)

    if region.meta_tag_attribute:
        try:
            attribute = json.loads(region.meta_tag_attribute)
        except (json.JSONDecodeError, TypeError):
            diagnostics.append(
                _diagnostic("malformed-json", region, "invalid fieldBegin@metaTag JSON")
            )
            attribute = None
        if isinstance(attribute, dict) and (
            "hwpxFiller" in attribute
            or attribute.get("name") == _NATIVE_NAME
        ):
            diagnostics.append(
                _diagnostic(
                    "unsupported-carrier",
                    region,
                    "product metadata cannot use fieldBegin@metaTag",
                )
            )
        if (
            isinstance(attribute, dict)
            and attribute.get("name") == _NATIVE_NAME
            and "hwpxFiller" not in attribute
        ):
            diagnostics.append(
                _diagnostic(
                    "invalid-product-payload",
                    region,
                    "fieldBegin@metaTag has no hwpxFiller object",
                )
            )

    if len(parsed) > 1:
        diagnostics.append(
            _diagnostic("conflicting-product-metatag", region, "multiple product MetaTags")
        )
        return None
    if not parsed:
        return None

    root = parsed[0]
    body = root.get("hwpxFiller")
    if not isinstance(body, dict):
        diagnostics.append(
            _diagnostic("invalid-product-payload", region, "hwpxFiller must be an object")
        )
        return None
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in _PRODUCT_KINDS:
        diagnostics.append(_diagnostic("unknown-kind", region, f"unknown kind {kind!r}"))
        return None
    recognised[region] = kind

    identifier = body.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        diagnostics.append(_diagnostic("invalid-id", region, "id must be a non-empty string"))
        return None
    native_name = root.get("name")
    if native_name != _NATIVE_NAME:
        diagnostics.append(
            _diagnostic(
                "native-name-mismatch",
                region,
                f"name must be {_NATIVE_NAME!r}, got {native_name!r}",
            )
        )

    return _ProductTag(region, kind, identifier)


def _inspect_slot_snapshot(pkg: object) -> _SlotSnapshot:
    diagnostics: list[TemplateDiagnostic] = []
    try:
        regions = resolve_bookmark_topology(pkg)
    except (ValueError, etree.XMLSyntaxError) as exc:
        kind = (
            "crossing-range"
            if "crossing BOOKMARK regions" in str(exc)
            else "bookmark-resolve-failed"
        )
        return _SlotSnapshot(
            (), (TemplateDiagnostic(kind, str(exc)),), {}, {}
        )

    recognised: dict[BookmarkRegion, str] = {}
    tags = {
        tag.region: tag
        for region in regions
        if (tag := _product_tag(region, diagnostics, recognised)) is not None
    }
    slot_tags = [tag for tag in tags.values() if tag.kind == "slot"]
    option_tags = [tag for tag in tags.values() if tag.kind == "slot_option"]

    for region, kind in recognised.items():
        if kind == "slot" and any(
            recognised.get(ancestor) == "slot" for ancestor in _ancestors(region)
        ):
            diagnostics.append(
                _diagnostic("nested-slot", region, "Slot is inside another Slot")
            )

    membership: dict[BookmarkRegion, _ProductTag] = {}
    for region, kind in recognised.items():
        if kind != "slot_option":
            continue
        ancestors = _ancestors(region)
        if any(recognised.get(ancestor) == "slot_option" for ancestor in ancestors):
            diagnostics.append(
                _diagnostic("nested-option", region, "Option is inside another Option")
            )
        slot_ancestors = [
            ancestor for ancestor in ancestors if recognised.get(ancestor) == "slot"
        ]
        if not slot_ancestors:
            diagnostics.append(
                _diagnostic("orphan-option", region, "Option has no product Slot ancestor")
            )
        elif len(slot_ancestors) > 1:
            diagnostics.append(
                _diagnostic(
                    "ambiguous-membership",
                    region,
                    "Option has more than one product Slot ancestor",
                )
            )
        elif (option_tag := tags.get(region)) is not None and (
            slot_tag := tags.get(slot_ancestors[0])
        ) is not None:
            membership[option_tag.region] = slot_tag

    slots: list[Slot] = []
    seen_slots: set[str] = set()
    for slot_tag in slot_tags:
        if slot_tag.id in seen_slots:
            diagnostics.append(
                _diagnostic("duplicate-slot-id", slot_tag.region, f"duplicate Slot id {slot_tag.id!r}")
            )
        seen_slots.add(slot_tag.id)
        owned = [tag for tag in option_tags if membership.get(tag.region) == slot_tag]
        options: list[SlotOption] = []
        seen_options: set[str] = set()
        for option_tag in owned:
            if option_tag.id in seen_options:
                diagnostics.append(
                    _diagnostic(
                        "duplicate-option-id",
                        option_tag.region,
                        f"duplicate Option id {option_tag.id!r} in Slot {slot_tag.id!r}",
                    )
                )
            seen_options.add(option_tag.id)
            options.append(SlotOption(option_tag.id, len(options)))
        slots.append(
            Slot(
                id=slot_tag.id,
                options=tuple(options),
            )
        )
    return _SlotSnapshot(
        tuple(slots),
        tuple(diagnostics),
        {tag.id: tag.region for tag in slot_tags},
        {
            (owner.id, tag.id): tag.region
            for tag in option_tags
            if (owner := membership.get(tag.region)) is not None
        },
    )


def inspect_slots(pkg: object) -> tuple[tuple[Slot, ...], tuple[TemplateDiagnostic, ...]]:
    """Inspect one open package; diagnostics are blocking but do not hide valid Slots."""
    snapshot = _inspect_slot_snapshot(pkg)
    return snapshot.slots, snapshot.diagnostics


def _require_mutable_snapshot(pkg: object) -> tuple[object, _SlotSnapshot]:
    package = require_package(pkg)
    snapshot = _inspect_slot_snapshot(package)
    if snapshot.diagnostics:
        details = "; ".join(
            f"{item.kind}: {item.message}" for item in snapshot.diagnostics
        )
        raise ValueError(f"Slot mutation blocked by diagnostics: {details}")
    return package, snapshot


def _remove_product_region(
    package: object,
    region: BookmarkRegion,
    expected: tuple[Slot, ...],
) -> None:
    entries = package.entries  # type: ignore[attr-defined]
    original = dict(entries)
    try:
        remove_bookmark_region(package, region)
        actual, diagnostics = inspect_slots(package)
        if diagnostics or actual != expected:
            raise ValueError(
                "Slot removal postcondition failed: "
                f"expected {expected!r}, got {actual!r} with {diagnostics!r}"
            )
    except Exception:
        entries.clear()
        entries.update(original)
        raise


def remove_slot(pkg: object, slot_id: str) -> None:
    """Remove one canonical Slot region selected by its product id."""
    identifier = _require_text(slot_id, "Slot id")
    package, snapshot = _require_mutable_snapshot(pkg)
    region = snapshot.slot_regions.get(identifier)
    if region is None:
        raise ValueError(f"Slot {identifier!r} was not found")
    expected = tuple(slot for slot in snapshot.slots if slot.id != identifier)
    _remove_product_region(package, region, expected)


def remove_slot_option(pkg: object, slot_id: str, option_id: str) -> None:
    """Remove one canonical Slot Option selected by its Slot-local product id."""
    owner_id = _require_text(slot_id, "Slot id")
    target_id = _require_text(option_id, "Slot Option id")
    package, snapshot = _require_mutable_snapshot(pkg)
    region = snapshot.option_regions.get((owner_id, target_id))
    if region is None:
        raise ValueError(
            f"Option {target_id!r} was not found in Slot {owner_id!r}"
        )
    expected = tuple(
        slot
        if slot.id != owner_id
        else Slot(
            slot.id,
            tuple(
                SlotOption(option.id, order)
                for order, option in enumerate(
                    item for item in slot.options if item.id != target_id
                )
            ),
        )
        for slot in snapshot.slots
    )
    _remove_product_region(package, region, expected)


def inspect_hwpx_template(path: str) -> TemplateInspection:
    """경로를 한 번 열고 같은 패키지 스냅샷에서 상태와 사전고지를 계산한다."""
    package = read_hwpx_package(path)
    slots, diagnostics = inspect_slots(package)
    return TemplateInspection(
        status=compile_status(package),
        precheck_notes=tuple(fill_precheck(package)),
        fields=tuple(extract_schema(package).field_names()),
        slots=slots,
        diagnostics=diagnostics,
    )


def template_compile_status(path: str) -> TemplateStatus:
    """경로 → 컴파일 수명주기 상태(C2). 홈/라이브러리 배지 파생 포트의 concrete."""
    return compile_status(read_hwpx_package(path))


def scan_template_tokens(path: str) -> "list[TokenSite]":
    """경로 → 토큰 스캔 미리보기(읽기 전용, 파일 무변형)."""
    return scan_tokens(read_hwpx_package(path))


def compile_template_file(path: str) -> CompileReport:
    """경로의 토큰을 누름틀로 컴파일해 **같은 경로에 저장**(변경이 있을 때만).

    바뀐 게 없으면(``modified=False``) 아무것도 쓰지 않는다 — 종전
    ``TemplateManagerViewModel.apply_fieldize`` 의 저장 판정 그대로.
    """
    pkg, report = compile_document(read_hwpx_package(path))
    if report.modified:
        write_hwpx_package(path, pkg)
    return report


def compile_to_sibling(path: str, *, overwrite: bool = False) -> "tuple[str | None, CompileReport]":
    """토큰을 컴파일해 **원본 옆** ``<이름>.compiled.hwpx`` 로 저장(원본 무변형).

    출력 경로 파생·저장·충돌 정책을 뷰가 하드코딩하지 않는다(RC-28). 정책:

    - 바꿀 토큰이 없으면(``modified=False``) 아무것도 쓰지 않고 ``(None, report)``.
    - 컴파일본이 이미 있으면 ``overwrite=True`` 없이는 :class:`FileExistsError`
      (메시지 = 충돌 경로)로 시끄럽게 차단 — 조용한 덮어쓰기 금지(RC-02). 호출측이
      사용자 확정을 받은 뒤 ``overwrite=True`` 로 재호출한다.
    - 컴파일·저장 실패는 그대로 raise(호출측이 시끄럽게 표시).

    (P2-19R 에서 ``domain.authoring`` 과 분리 — 경로 열기·충돌 검사·저장이 파일 IO 개시라
    Domain 에 둘 수 없다. 의미 불변.)
    """
    pkg, report = compile_document(read_hwpx_package(path))
    if not report.modified:
        return None, report
    compiled_path = str(Path(path).with_suffix(".compiled.hwpx"))
    if Path(compiled_path).exists() and not overwrite:
        raise FileExistsError(compiled_path)
    write_hwpx_package(compiled_path, pkg)
    return compiled_path, report


def lint_template_file(
    path: str, vocabulary: "list[str] | set[str] | None" = None
) -> LintReport:
    """경로 → 단일 템플릿 위생 점검(읽기 전용)."""
    return lint_template(read_hwpx_package(path), vocabulary=vocabulary)


def diff_template_schemas(old_path: str, new_path: str) -> SchemaDrift:
    """두 경로의 판본 간 필드셋 드리프트(추가/삭제/개명 추정). 읽기 전용."""
    return diff_schema(read_hwpx_package(old_path), read_hwpx_package(new_path))


def read_template_fields(path: str) -> "dict[str, str]":
    """경로 → 모든 누름틀 현재 값(C1 read_fields)."""
    return read_fields(read_hwpx_package(path))


#: :class:`~hwpxfiller.gui.template_manager_state.TemplateFileOps` 의 concrete 결속 —
#: ring 2 가 ``TemplateManagerViewModel(file_ops=HWPX_TEMPLATE_OPS)`` 로 주입한다.
HWPX_TEMPLATE_OPS = TemplateFileOps(
    scan_tokens=scan_template_tokens,
    compile_file=compile_template_file,
    lint=lint_template_file,
    diff=diff_template_schemas,
    read_fields=read_template_fields,
)
