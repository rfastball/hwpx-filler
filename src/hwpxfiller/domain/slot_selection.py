"""S4 선택 언어 — 매체 고유 구조를 모르는 Slot 선택 값·의미 계약(S4-01·#671).

이 모듈이 소유하는 것: `SlotSelection`/`SlotSelectionSet` 값 모델과 구문 불변식,
불변 `SelectionSemanticContractRegistry`, `slot-selection/v1` 의 `EXACTLY_ONE` 의미,
Python·TypeScript 가 공유하는 canonical byte framing 과 digest.

여기는 Work·Application 결속, Configuration store, TemplateStructure decoder,
reconciliation, token, Snapshot 을 모른다. resolver 는 저장소·native HWPX 타입을
import 하지 않는다(불변식: Domain 에 HWPX native 타입 노출 0).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

_U32_MAX = 0xFFFF_FFFF

# canonical encoding v1 상수 — 코드·문서·golden vector 단일 출처.
_MAGIC = b"HFPSEL1\0"  # exact 8 bytes
SELECTION_SET_SCHEMA_VERSION = "slot-selection-set/v1"
CANONICAL_ENCODING_VERSION = "slot-selection-canonical/v1"

# 정책 어휘.
EXACTLY_ONE = "EXACTLY_ONE"


class SlotSelectionError(Exception):
    """S4-01 선택 언어 오류의 뿌리."""

    code = "INVALID_SELECTION_SET"


class InvalidSelectionSetError(SlotSelectionError):
    code = "INVALID_SELECTION_SET"


class CanonicalSelectionEncodingError(SlotSelectionError):
    code = "CANONICAL_SELECTION_ENCODING_ERROR"


class UnsupportedSelectionSemanticContractError(SlotSelectionError):
    code = "UNSUPPORTED_SELECTION_SEMANTIC_CONTRACT"


class SelectionContractIntegrityError(SlotSelectionError):
    code = "SELECTION_CONTRACT_INTEGRITY_ERROR"


class UnsupportedSelectionPolicyError(SlotSelectionError):
    code = "UNSUPPORTED_SELECTION_POLICY"


def _require_scalar_text(value: object, what: str) -> str:
    """비어 있지 않은 유효 Unicode scalar sequence 만 통과(lone surrogate 거절)."""
    if not isinstance(value, str) or value == "":
        raise InvalidSelectionSetError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogate·invalid scalar
        raise InvalidSelectionSetError(f"{what} 에 유효하지 않은 Unicode scalar") from exc
    return value


@dataclass(frozen=True)
class SlotSelection:
    slot_id: str
    selected_option_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_scalar_text(self.slot_id, "slot_id")
        if not isinstance(self.selected_option_ids, tuple):
            raise InvalidSelectionSetError("selected_option_ids 는 tuple 이어야 한다")
        if len(self.selected_option_ids) == 0:
            raise InvalidSelectionSetError("selected_option_ids 는 비어 있을 수 없다")
        seen: set[str] = set()
        for option_id in self.selected_option_ids:
            _require_scalar_text(option_id, "option_id")
            if option_id in seen:
                raise InvalidSelectionSetError(
                    f"한 entry 안에서 option ID 중복: {option_id!r}"
                )
            seen.add(option_id)


@dataclass(frozen=True)
class SlotSelectionSet:
    selections: tuple[SlotSelection, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.selections, tuple):
            raise InvalidSelectionSetError("selections 는 tuple 이어야 한다")
        seen: set[str] = set()
        for selection in self.selections:
            if not isinstance(selection, SlotSelection):
                raise InvalidSelectionSetError("selection 은 SlotSelection 이어야 한다")
            if selection.slot_id in seen:
                raise InvalidSelectionSetError(
                    f"같은 slot_id entry 중복: {selection.slot_id!r}"
                )
            seen.add(selection.slot_id)


@dataclass(frozen=True)
class SelectionSemanticContractManifest:
    contract_id: str
    selection_set_schema_version: str
    canonical_encoding_version: str
    default_selection_policy: str
    supported_selection_policies: tuple[str, ...]
    created_semantics_version: str


@dataclass(frozen=True)
class SelectionSemanticBindingKey:
    qualification_profile_id: str
    structure_projection_schema_version: str


# slot-selection/v1 정본 manifest.
_SLOT_SELECTION_V1 = SelectionSemanticContractManifest(
    contract_id="slot-selection/v1",
    selection_set_schema_version=SELECTION_SET_SCHEMA_VERSION,
    canonical_encoding_version=CANONICAL_ENCODING_VERSION,
    default_selection_policy=EXACTLY_ONE,
    supported_selection_policies=(EXACTLY_ONE,),
    created_semantics_version="s4-selection-semantics/v1",
)


class SelectionSemanticContractRegistry:
    """immutable binding registry — unknown key 를 latest 로 fallback 하지 않는다."""

    def __init__(
        self,
        bindings: Iterable[
            tuple[SelectionSemanticBindingKey, SelectionSemanticContractManifest]
        ],
    ) -> None:
        self._by_key: dict[SelectionSemanticBindingKey, str] = {}
        self._by_id: dict[str, SelectionSemanticContractManifest] = {}
        for key, manifest in bindings:
            existing = self._by_id.get(manifest.contract_id)
            if existing is not None and existing != manifest:
                raise SelectionContractIntegrityError(
                    f"같은 contract ID 의 다른 manifest: {manifest.contract_id}"
                )
            if key in self._by_key and self._by_key[key] != manifest.contract_id:
                raise SelectionContractIntegrityError(
                    f"같은 binding key 를 다른 contract 로 재매핑: {key}"
                )
            self._by_key[key] = manifest.contract_id
            self._by_id[manifest.contract_id] = manifest

    def resolve(
        self, key: SelectionSemanticBindingKey
    ) -> SelectionSemanticContractManifest:
        contract_id = self._by_key.get(key)
        if contract_id is None:
            raise UnsupportedSelectionSemanticContractError(
                f"미지원 selection semantic binding: {key}"
            )
        return self._by_id[contract_id]

    def get(self, contract_id: str) -> SelectionSemanticContractManifest:
        manifest = self._by_id.get(contract_id)
        if manifest is None:
            raise UnsupportedSelectionSemanticContractError(
                f"미지원 selection semantic contract: {contract_id}"
            )
        return manifest


_V1_BINDING_KEY = SelectionSemanticBindingKey(
    qualification_profile_id="hwpx-template-qualification-v1",
    structure_projection_schema_version="hwpx-structure-projection-v1",
)

DEFAULT_SELECTION_SEMANTIC_REGISTRY = SelectionSemanticContractRegistry(
    [(_V1_BINDING_KEY, _SLOT_SELECTION_V1)]
)


def resolve_selection_policy(
    contract: SelectionSemanticContractManifest,
    declared_cardinality: str | None,
) -> str:
    """Slot 의 정책을 contract 로 복원한다.

    현재 `hwpx-structure-projection-v1` 에는 cardinality 필드가 없다 —
    `declared_cardinality` 가 None 이면 contract default(v1 = EXACTLY_ONE)다.
    선언된 정책이 contract 미지원이면 EXACTLY_ONE 으로 대체하지 않고 거절한다.
    """
    if declared_cardinality is None:
        return contract.default_selection_policy
    if declared_cardinality not in contract.supported_selection_policies:
        raise UnsupportedSelectionPolicyError(
            f"contract {contract.contract_id} 미지원 정책: {declared_cardinality!r}"
        )
    return declared_cardinality


# slot-selection/v1 판정 어휘 — option 존재 여부(reconciliation)는 여기 소유 아님.
SATISFIED = "SATISFIED"
MISSING_REQUIRED_SELECTION = "MISSING_REQUIRED_SELECTION"
CARDINALITY_VIOLATION = "CARDINALITY_VIOLATION"
NO_AVAILABLE_OPTIONS = "NO_AVAILABLE_OPTIONS"


def evaluate_slot(
    policy: str,
    available_option_count: int,
    selected_option_count: int,
) -> str:
    """EXACTLY_ONE 정책 하 한 Slot 의 cardinality 판정.

    단일 Option 도 자동 선택하지 않는다 — 선택 0 개는 항상 MISSING 이다.
    Option 정확히 1 개는 policy 만족 후보(선택 option 의 실재는 reconciliation 소유).
    """
    if policy != EXACTLY_ONE:
        raise UnsupportedSelectionPolicyError(f"미지원 정책: {policy!r}")
    if available_option_count == 0:
        return NO_AVAILABLE_OPTIONS
    if selected_option_count == 0:
        return MISSING_REQUIRED_SELECTION
    if selected_option_count == 1:
        return SATISFIED
    return CARDINALITY_VIOLATION


def _encode_text(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > _U32_MAX:
        raise CanonicalSelectionEncodingError("UTF-8 byte length 가 u32 범위 초과")
    return len(raw).to_bytes(4, "big") + raw


def _encode_u32(value: int) -> bytes:
    if value < 0 or value > _U32_MAX:
        raise CanonicalSelectionEncodingError("count 가 u32 범위 초과")
    return value.to_bytes(4, "big")


def canonicalize_selection_set(
    contract_id: str, selection_set: SlotSelectionSet
) -> bytes:
    """slot-selection-canonical/v1 정본 bytes — 저장 순서와 무관, 같은 의미는 같은 bytes."""
    _require_scalar_text(contract_id, "contract_id")
    out = bytearray()
    out += _MAGIC
    out += _encode_text(SELECTION_SET_SCHEMA_VERSION)
    out += _encode_text(contract_id)
    out += _encode_u32(len(selection_set.selections))
    for selection in sorted(
        selection_set.selections, key=lambda s: s.slot_id.encode("utf-8")
    ):
        out += _encode_text(selection.slot_id)
        out += _encode_u32(len(selection.selected_option_ids))
        for option_id in sorted(
            selection.selected_option_ids, key=lambda o: o.encode("utf-8")
        ):
            out += _encode_text(option_id)
    return bytes(out)


def digest_selection_set(contract_id: str, selection_set: SlotSelectionSet) -> str:
    """canonical bytes 의 sha256 content-address."""
    canonical = canonicalize_selection_set(contract_id, selection_set)
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def semantic_selection_equal(a: SlotSelectionSet, b: SlotSelectionSet) -> bool:
    """저장 순서 무관 semantic equality — 같은 canonical bytes 면 같다."""
    schema = SELECTION_SET_SCHEMA_VERSION
    return canonicalize_selection_set(schema, a) == canonicalize_selection_set(schema, b)
