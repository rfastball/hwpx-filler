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

from hwpxcore.bookmark_region import BookmarkRegion, resolve_bookmark_topology
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

_CARDINALITIES = frozenset({"zero_or_one", "exactly_one", "many"})
_NATIVE_NAMES = {"slot": "#hf_slot", "slot_option": "#hf_slot_option"}


class _ProductTag(NamedTuple):
    region: BookmarkRegion
    kind: str
    id: str
    label: str
    cardinality: str | None = None
    min_options: int | None = None
    ordering: str | None = None


def _diagnostic(kind: str, region: BookmarkRegion, detail: str) -> TemplateDiagnostic:
    return TemplateDiagnostic(kind, f"{region.section}: BOOKMARK {region.name!r}: {detail}")


def _ancestors(region: BookmarkRegion) -> list[BookmarkRegion]:
    ancestors: list[BookmarkRegion] = []
    current = region.parent
    while current is not None:
        ancestors.append(current)
        current = current.parent
    return ancestors


def _serialize_product_metatag(body: dict[str, object], name: str) -> str:
    return json.dumps(
        {"hwpxFiller": body, "name": name},
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
    _require_text(slot.label, "Slot label")
    if not isinstance(slot.cardinality, str) or slot.cardinality not in _CARDINALITIES:
        raise ValueError(f"unknown Slot cardinality {slot.cardinality!r}")
    if type(slot.min_options) is not int or slot.min_options < 0:
        raise ValueError("Slot min_options must be a non-negative integer")
    if slot.ordering != "template_order":
        raise ValueError("Slot ordering must be 'template_order'")
    return _serialize_product_metatag(
        {
            "v": 1,
            "kind": "slot",
            "id": slot.id,
            "label": slot.label,
            "cardinality": slot.cardinality,
            "minOptions": slot.min_options,
            "ordering": slot.ordering,
        },
        _NATIVE_NAMES["slot"],
    )


def serialize_slot_option_metatag(option: SlotOption) -> str:
    """Serialize one canonical object-local Slot Option payload."""
    _require_text(option.id, "Slot Option id")
    _require_text(option.label, "Slot Option label")
    return _serialize_product_metatag(
        {"v": 1, "kind": "slot_option", "id": option.id, "label": option.label},
        _NATIVE_NAMES["slot_option"],
    )


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
            if value.get("name") in _NATIVE_NAMES.values():
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
            or attribute.get("name") in _NATIVE_NAMES.values()
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
            and attribute.get("name") in _NATIVE_NAMES.values()
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
    version = body.get("v")
    if not isinstance(version, int) or isinstance(version, bool):
        diagnostics.append(
            _diagnostic("invalid-product-payload", region, "v must be an integer")
        )
        return None
    if version != 1:
        diagnostics.append(
            _diagnostic("unsupported-version", region, f"unsupported hwpxFiller.v {version!r}")
        )
        return None
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in _NATIVE_NAMES:
        diagnostics.append(_diagnostic("unknown-kind", region, f"unknown kind {kind!r}"))
        return None
    recognised[region] = kind

    identifier, label = body.get("id"), body.get("label")
    if not isinstance(identifier, str) or not identifier.strip():
        diagnostics.append(_diagnostic("invalid-id", region, "id must be a non-empty string"))
        return None
    if not isinstance(label, str) or not label.strip():
        diagnostics.append(
            _diagnostic("invalid-label", region, "label must be a non-empty string")
        )
        return None
    native_name = root.get("name")
    if native_name != _NATIVE_NAMES[kind]:
        diagnostics.append(
            _diagnostic(
                "native-name-mismatch",
                region,
                f"name must be {_NATIVE_NAMES[kind]!r}, got {native_name!r}",
            )
        )

    if kind == "slot_option":
        return _ProductTag(region, kind, identifier, label)

    cardinality = body.get("cardinality")
    if not isinstance(cardinality, str) or cardinality not in _CARDINALITIES:
        diagnostics.append(
            _diagnostic("unknown-cardinality", region, f"unknown cardinality {cardinality!r}")
        )
        return None
    min_options = body.get("minOptions")
    if (
        not isinstance(min_options, int)
        or isinstance(min_options, bool)
        or min_options < 0
    ):
        diagnostics.append(
            _diagnostic(
                "invalid-min-options", region, "minOptions must be a non-negative integer"
            )
        )
        return None
    ordering = body.get("ordering")
    if ordering != "template_order":
        diagnostics.append(
            _diagnostic(
                "unsupported-ordering", region, "ordering must be 'template_order'"
            )
        )
        return None
    return _ProductTag(
        region, kind, identifier, label, cardinality, min_options, ordering
    )


def inspect_slots(pkg: object) -> tuple[tuple[Slot, ...], tuple[TemplateDiagnostic, ...]]:
    """Inspect one open package; diagnostics are blocking but do not hide valid Slots."""
    diagnostics: list[TemplateDiagnostic] = []
    try:
        regions = resolve_bookmark_topology(pkg)
    except (ValueError, etree.XMLSyntaxError) as exc:
        kind = (
            "crossing-range"
            if "crossing BOOKMARK regions" in str(exc)
            else "bookmark-resolve-failed"
        )
        return (), (TemplateDiagnostic(kind, str(exc)),)

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
            options.append(SlotOption(option_tag.id, option_tag.label, len(options)))
        assert slot_tag.min_options is not None
        if slot_tag.min_options > len(options):
            diagnostics.append(
                _diagnostic(
                    "min-options-unsatisfied",
                    slot_tag.region,
                    f"minOptions {slot_tag.min_options} exceeds {len(options)} Options",
                )
            )
        assert slot_tag.cardinality is not None and slot_tag.ordering is not None
        slots.append(
            Slot(
                id=slot_tag.id,
                label=slot_tag.label,
                cardinality=slot_tag.cardinality,
                min_options=slot_tag.min_options,
                options=tuple(options),
                ordering=slot_tag.ordering,
            )
        )
    return tuple(slots), tuple(diagnostics)


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
