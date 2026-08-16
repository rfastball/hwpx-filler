"""S4-01(#671) 선택 언어·의미 계약·canonical bytes 계약.

golden vector(`tests/fixtures/slot_selection_v1_golden.json`)는 Python·TypeScript
공통 오러클이다 — 여기서 Python 이, `tests/js/slot_selection.test.js` 에서 TS 가
같은 파일을 재현한다. 한쪽만 바뀌면 그쪽 스위트가 빨강이 된다.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from hwpxfiller.domain.slot_selection import (
    CARDINALITY_VIOLATION,
    DEFAULT_SELECTION_SEMANTIC_REGISTRY,
    EXACTLY_ONE,
    MISSING_REQUIRED_SELECTION,
    NO_AVAILABLE_OPTIONS,
    SATISFIED,
    CanonicalSelectionEncodingError,
    InvalidSelectionSetError,
    SelectionContractIntegrityError,
    SelectionSemanticBindingKey,
    SelectionSemanticContractManifest,
    SelectionSemanticContractRegistry,
    SlotSelection,
    SlotSelectionSet,
    UnsupportedSelectionPolicyError,
    UnsupportedSelectionSemanticContractError,
    canonicalize_selection_set,
    digest_selection_set,
    evaluate_slot,
    resolve_selection_policy,
    semantic_selection_equal,
)

_GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "slot_selection_v1_golden.json").read_text(
        encoding="utf-8"
    )
)
_V1_KEY = SelectionSemanticBindingKey(
    "hwpx-template-qualification-v1", "hwpx-structure-projection-v1"
)


def _set(pairs: list[tuple[str, list[str]]]) -> SlotSelectionSet:
    return SlotSelectionSet(
        tuple(SlotSelection(s, tuple(o)) for s, o in pairs)
    )


# ── registry ────────────────────────────────────────────────────────────────
def test_v1_binding_resolves_slot_selection_v1() -> None:
    manifest = DEFAULT_SELECTION_SEMANTIC_REGISTRY.resolve(_V1_KEY)
    assert manifest.contract_id == "slot-selection/v1"
    assert manifest.default_selection_policy == EXACTLY_ONE
    assert manifest.supported_selection_policies == (EXACTLY_ONE,)


def test_unknown_binding_does_not_fall_back_to_latest() -> None:
    with pytest.raises(UnsupportedSelectionSemanticContractError):
        DEFAULT_SELECTION_SEMANTIC_REGISTRY.resolve(
            SelectionSemanticBindingKey("unknown-profile", "unknown-schema")
        )


def test_registry_rejects_same_key_different_contract() -> None:
    v1 = DEFAULT_SELECTION_SEMANTIC_REGISTRY.get("slot-selection/v1")
    other = SelectionSemanticContractManifest(
        "slot-selection/v2", "s", "c", EXACTLY_ONE, (EXACTLY_ONE,), "v"
    )
    with pytest.raises(SelectionContractIntegrityError):
        SelectionSemanticContractRegistry([(_V1_KEY, v1), (_V1_KEY, other)])


def test_registry_rejects_same_contract_id_different_manifest() -> None:
    v1 = DEFAULT_SELECTION_SEMANTIC_REGISTRY.get("slot-selection/v1")
    clashing = SelectionSemanticContractManifest(
        "slot-selection/v1", "OTHER", "c", EXACTLY_ONE, (EXACTLY_ONE,), "v"
    )
    with pytest.raises(SelectionContractIntegrityError):
        SelectionSemanticContractRegistry(
            [(_V1_KEY, v1), (SelectionSemanticBindingKey("p2", "s2"), clashing)]
        )


# ── value model ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "pairs",
    [
        [("s", [])],  # empty selected options
        [("s", ["o", "o"])],  # duplicate option id
        [("", ["o"])],  # empty slot id
        [("s", [""])],  # empty option id
    ],
)
def test_invalid_selection_rejected(pairs: list[tuple[str, list[str]]]) -> None:
    with pytest.raises(InvalidSelectionSetError):
        _set(pairs)


def test_non_tuple_shapes_rejected() -> None:
    with pytest.raises(InvalidSelectionSetError):
        SlotSelection("s", ["o"])  # list, not tuple  # type: ignore[arg-type]
    with pytest.raises(InvalidSelectionSetError):
        SlotSelectionSet([SlotSelection("s", ("o",))])  # type: ignore[arg-type]
    with pytest.raises(InvalidSelectionSetError):
        SlotSelectionSet(("not-a-selection",))  # type: ignore[arg-type]


def test_registry_rejects_manifest_with_default_outside_supported() -> None:
    inconsistent = SelectionSemanticContractManifest(
        "slot-selection/bad", "s", "c", EXACTLY_ONE, (), "v"
    )
    with pytest.raises(SelectionContractIntegrityError):
        SelectionSemanticContractRegistry([(_V1_KEY, inconsistent)])


def test_registry_get_unknown_contract_rejected() -> None:
    with pytest.raises(UnsupportedSelectionSemanticContractError):
        DEFAULT_SELECTION_SEMANTIC_REGISTRY.get("slot-selection/nope")


def test_supported_declared_policy_passes_through() -> None:
    v1 = DEFAULT_SELECTION_SEMANTIC_REGISTRY.get("slot-selection/v1")
    assert resolve_selection_policy(v1, EXACTLY_ONE) == EXACTLY_ONE


def test_duplicate_slot_entry_rejected() -> None:
    with pytest.raises(InvalidSelectionSetError):
        SlotSelectionSet(
            (SlotSelection("s", ("a",)), SlotSelection("s", ("b",)))
        )


def test_lone_surrogate_rejected() -> None:
    with pytest.raises(InvalidSelectionSetError):
        SlotSelection("\ud800", ("o",))


def test_semantic_equality_ignores_order() -> None:
    a = _set([("s", ["A", "B"])])
    b = _set([("s", ["B", "A"])])
    assert semantic_selection_equal(a, b)
    assert semantic_selection_equal(
        _set([("s1", ["o"]), ("s2", ["o"])]),
        _set([("s2", ["o"]), ("s1", ["o"])]),
    )


# ── policy ───────────────────────────────────────────────────────────────────
def test_v1_slot_without_cardinality_is_exactly_one() -> None:
    v1 = DEFAULT_SELECTION_SEMANTIC_REGISTRY.get("slot-selection/v1")
    assert resolve_selection_policy(v1, None) == EXACTLY_ONE


def test_unsupported_declared_policy_not_replaced_by_exactly_one() -> None:
    v1 = DEFAULT_SELECTION_SEMANTIC_REGISTRY.get("slot-selection/v1")
    with pytest.raises(UnsupportedSelectionPolicyError):
        resolve_selection_policy(v1, "ZERO_OR_ONE")


@pytest.mark.parametrize(
    "available,selected,outcome",
    [
        (0, 0, NO_AVAILABLE_OPTIONS),
        (0, 1, NO_AVAILABLE_OPTIONS),  # no options blocks even if intent exists
        (3, 0, MISSING_REQUIRED_SELECTION),  # 단일 자동선택 없음: 0 은 항상 missing
        (3, 1, SATISFIED),
        (3, 2, CARDINALITY_VIOLATION),
    ],
)
def test_evaluate_slot(available: int, selected: int, outcome: str) -> None:
    assert evaluate_slot(EXACTLY_ONE, available, selected) == outcome


def test_evaluate_slot_rejects_unknown_policy() -> None:
    with pytest.raises(UnsupportedSelectionPolicyError):
        evaluate_slot("MANY", 3, 2)


# ── canonical bytes / digest (golden vectors) ────────────────────────────────
@pytest.mark.parametrize("vector", _GOLDEN["vectors"], ids=lambda v: v["name"])
def test_golden_vector_reproduced(vector: dict) -> None:
    ss = _set([(s, list(o)) for s, o in vector["selections"]])
    canonical = canonicalize_selection_set(_GOLDEN["contract_id"], ss)
    assert canonical.hex() == vector["canonical_hex"]
    assert digest_selection_set(_GOLDEN["contract_id"], ss) == vector["digest"]


def test_storage_order_does_not_change_bytes() -> None:
    forward = _set([("s1", ["o1a", "o1b"]), ("s2", ["o2"])])
    reversed_ = _set([("s2", ["o2"]), ("s1", ["o1b", "o1a"])])
    cid = _GOLDEN["contract_id"]
    assert canonicalize_selection_set(cid, forward) == canonicalize_selection_set(
        cid, reversed_
    )


def test_nfc_and_nfd_not_unified() -> None:
    base = "가"  # precomposed 가
    nfc = _set([(unicodedata.normalize("NFC", base), ["o"])])
    nfd = _set([(unicodedata.normalize("NFD", base), ["o"])])
    cid = _GOLDEN["contract_id"]
    assert canonicalize_selection_set(cid, nfc) != canonicalize_selection_set(cid, nfd)


def test_u32_count_overflow_rejected() -> None:
    from hwpxfiller.domain.slot_selection import _encode_u32

    with pytest.raises(CanonicalSelectionEncodingError):
        _encode_u32(0x1_0000_0000)


# ── selection-set JSON codec + structural digest (S4-02 소비 seam) ────────────
def test_selection_set_json_roundtrip() -> None:
    from hwpxfiller.domain.slot_selection import (
        decode_selection_set,
        encode_selection_set,
    )

    original = _set([("s2", ["o2"]), ("s1", ["o1a", "o1b"])])
    assert decode_selection_set(encode_selection_set(original)) == original


def test_decode_selection_set_rejects_malformed() -> None:
    from hwpxfiller.domain.slot_selection import decode_selection_set

    with pytest.raises(InvalidSelectionSetError):
        decode_selection_set({"selections": "nope"})


def test_declared_digest_ignores_order() -> None:
    from hwpxfiller.domain.slot_selection import declared_selection_digest

    assert declared_selection_digest(_set([("s", ["a", "b"])])) == (
        declared_selection_digest(_set([("s", ["b", "a"])]))
    )
