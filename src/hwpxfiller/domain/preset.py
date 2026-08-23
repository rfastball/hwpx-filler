"""Selection Preset — Work 밖에서 재사용하는 Slot 선택 값의 **보관**(S9-01 · #827).

Preset 은 선택 값의 보관이지 **Template 정의가 아니다**(이중 권위 차단, #821 D1). 그래서
Slot 구조·label·cardinality·Option 목록을 저장하지 않는다 — 그것들의 권위는 Template
authority 하나이고, Preset 이 사본을 들면 「어느 쪽이 진짜인가」를 사용자에게 물어야 하는
두 번째 권위가 생긴다. 여기 담기는 것은 `slot_id → 선택된 option_id` 뿐이다.

적용 시점의 판정(선택이 지금 구조에 실재하는가·정책을 만족하는가·무엇이 끊겼는가)은 전부
S4 reconciliation 이 진다 — **이 모듈에 판정 기계는 0 개**다. 값 불변식·codec 무결성
(digest 재계산 대조)만 소유한다.

적용 경로·command·진단 코드 문자열 표면은 S9-02, UI 는 S9-03 소관이라 여기 없다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hwpxfiller.domain.slot_selection import (
    SlotSelectionError,
    SlotSelectionSet,
    decode_selection_set,
    declared_selection_digest,
    encode_selection_set,
)

PRESET_SCHEMA_VERSION = "selection-preset/v1"

#: 직렬화 최상위 필드 집합 — decode 가 **정확히** 이것만 받는다(구조 밀수 봉쇄).
_PRESET_FIELDS = frozenset(
    {
        "schema_version",
        "name",
        "selection_set",
        "declared_selection_digest",
        "provenance",
        "created_at",
    }
)


class PresetError(ValueError):
    """Preset 불변식·codec 위반의 뿌리."""


def _require_nonempty(value: object, what: str) -> str:
    """``work_slot_configuration._require_nonempty`` 동형의 로컬 헬퍼(ring 경계 유지)."""
    if not isinstance(value, str) or value == "":
        raise PresetError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    return value


def _normalize_provenance(value: object) -> tuple[tuple[str, str], ...]:
    """평평한 ``str→str`` 매핑만 통과시켜 정렬-무관 불변 표현으로 정규화한다.

    frozen dataclass 가 dict 를 그대로 들면 가변 유출이라 ``tuple(sorted(items))`` 로
    보관한다. 중첩 dict·리스트·수치 값은 거절한다 — provenance 는 advisory 캡처 시점
    정보이지 Template 구조를 실어 나르는 통로가 아니다(#821 D1).
    """
    if isinstance(value, Mapping):
        items: list[Any] = list(value.items())
    elif isinstance(value, tuple):
        items = []
        for pair in value:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise PresetError("provenance 항목은 (키, 값) 쌍이어야 한다")
            items.append(pair)
    else:
        raise PresetError("provenance 는 평평한 문자열 매핑이어야 한다")
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, item in items:
        if not isinstance(key, str) or key == "":
            raise PresetError("provenance 키는 비어 있지 않은 문자열이어야 한다")
        if not isinstance(item, str):
            raise PresetError(f"provenance 값은 문자열이어야 한다: {key!r}")
        if key in seen:
            raise PresetError(f"provenance 키 중복: {key!r}")
        seen.add(key)
        normalized.append((key, item))
    normalized.sort()
    return tuple(normalized)


@dataclass(frozen=True)
class SelectionPreset:
    """이름 붙은 선택 묶음 1건.

    ``name`` 은 레지스트리 안에서 유일하지만 **유일성 집행은 store** 가 진다(값 하나는
    다른 값의 존재를 모른다). ``provenance`` 는 advisory 다 — 필수 키가 없고 store·codec
    은 내용을 판정하지 않는다. 생성자에는 dict 를 넘겨도 되고(정규화됨) 읽을 때는
    :attr:`provenance_map` 이 dict 를 준다.
    """

    name: str
    selection_set: SlotSelectionSet
    provenance: "Mapping[str, str] | tuple[tuple[str, str], ...]"
    created_at: str

    def __post_init__(self) -> None:
        _require_nonempty(self.name, "name")
        _require_nonempty(self.created_at, "created_at")
        if not isinstance(self.selection_set, SlotSelectionSet):
            raise PresetError("selection_set 은 SlotSelectionSet 이어야 한다")
        if len(self.selection_set.selections) == 0:
            # 빈 선택 묶음은 Preset 이 될 수 없다 — 「적용해도 아무 일도 안 일어나는 Preset」은
            # 사용자에게 조용한 무동작으로 보인다(#821 §3 의 구조적 봉쇄).
            raise PresetError("selection_set 은 비어 있을 수 없다")
        object.__setattr__(self, "provenance", _normalize_provenance(self.provenance))

    @property
    def provenance_map(self) -> dict[str, str]:
        """advisory provenance 의 dict-형 사본 — 변형해도 Preset 은 불변이다."""
        return {key: item for key, item in tuple(self.provenance)}


@dataclass(frozen=True)
class CorruptPresetEntry:
    """파싱 실패한 Preset 파일 1건의 사실 — 나열 API 가 주는 값 객체.

    ``application.dataset_pool.CorruptDatasetEntry`` 동형이되 **Domain 에 산다**: S9-02
    application 소비자가 손상 항목을 표면화(비활성 + 사유 병기)하려고 external 을 import
    하지 않아도 되게 하기 위해서다.
    """

    file_name: str
    error: str


# ─── codec ────────────────────────────────────────────────────────────────────

def encode_preset(preset: SelectionPreset) -> dict[str, Any]:
    """JSON-safe 표현 — 최상위 필드는 :data:`_PRESET_FIELDS` 정확히 그 집합이다."""
    return {
        "schema_version": PRESET_SCHEMA_VERSION,
        "name": preset.name,
        "selection_set": encode_selection_set(preset.selection_set),
        # decode 시 재검증 가능한 seam — 저장 bytes 손상·의미 드리프트를 시끄럽게 잡는다
        # (``work_slot_configuration._encode_config`` 의 digest 대조 seam 미러).
        "declared_selection_digest": declared_selection_digest(preset.selection_set),
        "provenance": preset.provenance_map,
        "created_at": preset.created_at,
    }


def decode_preset(data: object) -> SelectionPreset:
    """JSON 표현 → :class:`SelectionPreset`. 미상 버전·미지 필드·digest 불일치는 loud.

    미지 최상위 필드를 조용히 무시하면 Slot 구조·Option 목록이 Preset 파일에 밀수돼도
    무증상으로 흘러간다 — 그 파일을 쓴 쪽은 「저장됐다」고 믿고 읽는 쪽은 버린다.
    """
    if not isinstance(data, Mapping):
        raise PresetError("preset 표현이 malformed")
    schema = data.get("schema_version")
    if schema != PRESET_SCHEMA_VERSION:
        raise PresetError(f"미상 preset schema_version {schema!r}")
    unknown = sorted(set(data) - _PRESET_FIELDS)
    if unknown:
        raise PresetError(f"미지 preset 필드: {unknown}")
    try:
        selection_set = decode_selection_set(data.get("selection_set"))
    except SlotSelectionError as exc:
        raise PresetError(f"selection set 복원 실패: {exc}") from exc
    if data.get("declared_selection_digest") != declared_selection_digest(selection_set):
        raise PresetError(
            "저장된 selection digest 가 복원 selection 과 불일치(손상·드리프트)"
        )
    return SelectionPreset(
        name=data.get("name"),  # None·비문자열은 __post_init__ 이 거절
        selection_set=selection_set,
        provenance=data.get("provenance"),
        created_at=data.get("created_at"),
    )
