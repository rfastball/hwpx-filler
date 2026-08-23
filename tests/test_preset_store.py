"""Selection Preset 값 모델·codec·레지스트리 헤드리스 테스트(S9-01 · #827).

Preset 은 선택 값의 보관이지 Template 정의가 아니다 — 직렬화 필드 집합 봉쇄 계약이 그
경계를 파일 형상으로 못박는다. 손상 항목은 숨기지 않고 값 객체로 함께 나오고, 이름 충돌·
경로 탈출·digest 드리프트는 전부 loud 거절이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwpxfiller.domain.preset import (
    PRESET_SCHEMA_VERSION,
    CorruptPresetEntry,
    PresetError,
    SelectionPreset,
    decode_preset,
    encode_preset,
)
from hwpxfiller.domain.slot_selection import (
    SlotSelection,
    SlotSelectionSet,
    declared_selection_digest,
)
from hwpxfiller.external import preset_store
from hwpxfiller.external.preset_store import PresetRegistry, load_preset, save_preset

NOW = "2026-08-24T09:00:00"


def _selection(slot: str = "s1", option: str = "o1") -> SlotSelectionSet:
    return SlotSelectionSet((SlotSelection(slot_id=slot, selected_option_ids=(option,)),))


def _preset(name: str = "표준 서식", **kw) -> SelectionPreset:
    return SelectionPreset(
        name=name,
        selection_set=kw.pop("selection_set", _selection()),
        provenance=kw.pop("provenance", {"template_application_id": "A17"}),
        created_at=kw.pop("created_at", NOW),
    )


# ------------------------------------------------------------------ 값 모델
def test_roundtrip_is_lossless_including_provenance() -> None:
    """encode→decode 왕복이 무손실 — provenance 도 값 동일성을 유지한다."""
    preset = _preset(provenance={"template_application_id": "A17", "note": "6월분"})
    back = decode_preset(encode_preset(preset))
    assert back == preset
    assert back.provenance_map == {"template_application_id": "A17", "note": "6월분"}


def test_provenance_order_does_not_change_identity() -> None:
    """정렬-무관 불변 표현 — 같은 매핑이면 삽입 순서가 달라도 같은 Preset 이다."""
    a = _preset(provenance={"a": "1", "b": "2"})
    b = _preset(provenance={"b": "2", "a": "1"})
    assert a == b
    assert a.provenance_map == b.provenance_map


def test_provenance_map_is_a_copy() -> None:
    """dict 사본을 준다 — 반환값 변형이 frozen 값을 오염시키지 못한다."""
    preset = _preset()
    got = preset.provenance_map
    got["template_application_id"] = "오염"
    assert preset.provenance_map == {"template_application_id": "A17"}


def test_provenance_accepts_normalized_pairs() -> None:
    """이미 정규화된 tuple 표현도 그대로 받는다(왕복 재구성 경로)."""
    preset = _preset(provenance=(("a", "1"), ("b", "2")))
    assert preset.provenance_map == {"a": "1", "b": "2"}


def test_empty_provenance_is_allowed() -> None:
    """provenance 는 advisory — 어떤 키도 필수가 아니다."""
    assert _preset(provenance={}).provenance_map == {}


@pytest.mark.parametrize("field", ["name", "created_at"])
def test_blank_identity_fields_rejected(field: str) -> None:
    with pytest.raises(PresetError):
        _preset(**{field: ""})


def test_non_string_name_rejected() -> None:
    with pytest.raises(PresetError):
        _preset(name=None)


def test_empty_selection_set_rejected() -> None:
    """빈 선택 묶음은 Preset 이 될 수 없다 — 조용한 무동작 Preset 의 구조적 봉쇄."""
    with pytest.raises(PresetError):
        _preset(selection_set=SlotSelectionSet(()))


def test_selection_set_type_rejected() -> None:
    with pytest.raises(PresetError):
        _preset(selection_set={"selections": []})


@pytest.mark.parametrize(
    "provenance",
    [
        {"nested": {"slot": "s1"}},  # 중첩 dict = Template 구조 밀수 통로
        {"options": ["o1", "o2"]},  # 리스트 값
        {"count": 3},  # 수치 값
        {"": "빈 키"},
        {1: "정수 키"},
        "문자열",  # 매핑도 쌍 tuple 도 아님
        (("a", "1", "x"),),  # 2-tuple 아님
        ("ab",),  # 항목이 tuple 아님
        (("a", "1"), ("a", "2")),  # 키 중복
    ],
)
def test_non_flat_provenance_rejected(provenance: object) -> None:
    with pytest.raises(PresetError):
        _preset(provenance=provenance)


# ------------------------------------------------------------------ codec 봉쇄 계약
def test_serialized_field_set_is_sealed() -> None:
    """Preset 파일에는 Slot 구조·label·cardinality·Option 목록이 들어갈 자리가 없다."""
    data = encode_preset(_preset())
    assert set(data) == {
        "schema_version",
        "name",
        "selection_set",
        "declared_selection_digest",
        "provenance",
        "created_at",
    }
    assert data["schema_version"] == PRESET_SCHEMA_VERSION
    assert data["declared_selection_digest"] == declared_selection_digest(_selection())
    entries = data["selection_set"]["selections"]
    assert [set(e) for e in entries] == [{"slot_id", "selected_option_ids"}]


def test_unknown_top_level_field_rejected() -> None:
    """조용한 무시 금지 — 미지 필드는 밀수 시도로 보고 거절한다."""
    data = encode_preset(_preset())
    data["slots"] = [{"slot_id": "s1", "label": "수신처", "cardinality": "EXACTLY_ONE"}]
    with pytest.raises(PresetError, match="미지 preset 필드"):
        decode_preset(data)


def test_schema_version_mismatch_rejected() -> None:
    data = encode_preset(_preset())
    data["schema_version"] = "selection-preset/v99"
    with pytest.raises(PresetError, match="미상 preset schema_version"):
        decode_preset(data)


def test_digest_mismatch_rejected() -> None:
    """저장 digest 와 복원 selection 의 대조 — 손상·드리프트를 시끄럽게 잡는다."""
    data = encode_preset(_preset())
    data["selection_set"]["selections"][0]["selected_option_ids"] = ["다른옵션"]
    with pytest.raises(PresetError, match="불일치"):
        decode_preset(data)


def test_malformed_selection_set_rejected() -> None:
    data = encode_preset(_preset())
    data["selection_set"] = {"selections": "리스트가 아님"}
    with pytest.raises(PresetError, match="selection set 복원 실패"):
        decode_preset(data)


def test_non_mapping_payload_rejected() -> None:
    with pytest.raises(PresetError, match="malformed"):
        decode_preset(["선택 묶음"])


def test_missing_provenance_field_rejected() -> None:
    data = encode_preset(_preset())
    del data["provenance"]
    with pytest.raises(PresetError):
        decode_preset(data)


def test_corrupt_entry_value_object() -> None:
    entry = CorruptPresetEntry(file_name="a.preset.json", error="boom")
    assert (entry.file_name, entry.error) == ("a.preset.json", "boom")


# ------------------------------------------------------------------ 파일 codec
def test_file_codec_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "k.preset.json"
    preset = _preset()
    save_preset(path, preset)
    assert json.loads(path.read_text(encoding="utf-8")) == encode_preset(preset)
    assert load_preset(path) == preset


# ------------------------------------------------------------------ 레지스트리
def test_add_list_load_roundtrip(tmp_path: Path) -> None:
    reg = PresetRegistry(tmp_path / "presets")
    key = reg.add(_preset("나중"))
    other = reg.add(_preset("가장먼저"))
    assert reg.slot_path(key).name.endswith(PresetRegistry.SUFFIX)
    assert reg.exists(key) and reg.exists(other)
    assert [p.name for _k, p in reg.list_entries()] == ["가장먼저", "나중"]
    assert reg.load(key).name == "나중"


def test_duplicate_name_rejected_loudly(tmp_path: Path) -> None:
    """조용한 덮기 금지의 store 백스톱 — 거절 후 파일 수가 변하지 않는다."""
    reg = PresetRegistry(tmp_path)
    reg.add(_preset("표준"))
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(ValueError, match="같은 이름의 프리셋이 이미 있습니다"):
        reg.add(_preset("표준"))
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_save_at_updates_same_slot(tmp_path: Path) -> None:
    reg = PresetRegistry(tmp_path)
    key = reg.add(_preset("표준"))
    reg.save_at(key, _preset("표준", selection_set=_selection("s2", "o9")))
    assert len(reg.list_entries()) == 1
    assert reg.load(key).selection_set == _selection("s2", "o9")


def test_save_at_cannot_take_another_slots_name(tmp_path: Path) -> None:
    """덮어쓰기 확정이 옆 항목의 이름을 침범하지 못한다(유일성 불변식)."""
    reg = PresetRegistry(tmp_path)
    reg.add(_preset("표준"))
    key_b = reg.add(_preset("대안"))
    with pytest.raises(ValueError, match="같은 이름의 프리셋이 이미 있습니다"):
        reg.save_at(key_b, _preset("표준"))
    assert reg.load(key_b).name == "대안"


def test_save_at_creates_directory(tmp_path: Path) -> None:
    reg = PresetRegistry(tmp_path / "missing")
    reg.save_at("k1", _preset())
    assert reg.load("k1") == _preset()


def test_delete_is_idempotent(tmp_path: Path) -> None:
    reg = PresetRegistry(tmp_path)
    key = reg.add(_preset())
    reg.delete(key)
    assert not reg.exists(key)
    reg.delete(key)  # 없는 키 삭제는 무해


@pytest.mark.parametrize("key", ["../x", "a/b", "a\\b", "", ".", ".."])
def test_path_escape_keys_rejected(tmp_path: Path, key: str) -> None:
    reg = PresetRegistry(tmp_path)
    with pytest.raises(ValueError, match="올바른 프리셋 키가 아닙니다"):
        reg.slot_path(key)


def test_missing_directory_lists_empty(tmp_path: Path) -> None:
    reg = PresetRegistry(tmp_path / "없음")
    assert reg.list_presets() == ([], [])
    assert reg.find_name("표준") is None


class _StubUUID:
    """``uuid.uuid4()`` 대역 — 발급 시퀀스를 결정론으로 고정한다."""

    def __init__(self, stem: str) -> None:
        self.hex = stem + "0" * 16


def test_new_slot_key_reissues_then_gives_up(tmp_path: Path, monkeypatch) -> None:
    """키가 이미 점유돼 있으면 재발급하고, 끝내 못 얻으면 조용히 덮지 않고 실패한다."""
    reg = PresetRegistry(tmp_path)
    reg.slot_path("a" * 16).write_text("{}", encoding="utf-8")

    stems = iter(["a" * 16, "b" * 16])
    monkeypatch.setattr(preset_store.uuid, "uuid4", lambda: _StubUUID(next(stems)))
    assert reg.new_slot_key() == "b" * 16  # 점유된 첫 키를 건너뛰고 빈 키 확보

    monkeypatch.setattr(preset_store.uuid, "uuid4", lambda: _StubUUID("a" * 16))
    with pytest.raises(RuntimeError, match="발급하지 못했습니다"):
        reg.new_slot_key()


# ------------------------------------------------------------------ 손상 항목
def _plant_corruption(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ("z" * 16 + PresetRegistry.SUFFIX)).write_text(
        "{ 깨진 JSON", encoding="utf-8"
    )
    tampered = encode_preset(_preset("변조본"))
    tampered["declared_selection_digest"] = "sha256:0000"
    (directory / ("y" * 16 + PresetRegistry.SUFFIX)).write_text(
        json.dumps(tampered, ensure_ascii=False), encoding="utf-8"
    )


def test_list_presets_surfaces_corruption_without_hiding_healthy(tmp_path: Path) -> None:
    """손상은 숨기지 않고 정상 항목과 **둘 다** 나온다 — 비활성 + 사유 병기의 원천."""
    reg = PresetRegistry(tmp_path)
    reg.add(_preset("멀쩡"))
    _plant_corruption(tmp_path)
    entries, corrupted = reg.list_presets()
    assert [p.name for _k, p in entries] == ["멀쩡"]
    assert {c.file_name for c in corrupted} == {
        "y" * 16 + PresetRegistry.SUFFIX,
        "z" * 16 + PresetRegistry.SUFFIX,
    }
    assert all(isinstance(c, CorruptPresetEntry) and c.error for c in corrupted)


def test_list_entries_without_collector_raises(tmp_path: Path) -> None:
    """C5 — 수집처를 안 넘긴 호출자에게 손상 항목을 무표시로 드롭하지 않는다."""
    reg = PresetRegistry(tmp_path)
    _plant_corruption(tmp_path)
    with pytest.raises(ValueError):
        reg.list_entries()


def test_find_name_skips_corruption(tmp_path: Path) -> None:
    reg = PresetRegistry(tmp_path)
    key = reg.add(_preset("멀쩡"))
    _plant_corruption(tmp_path)
    found = reg.find_name("멀쩡")
    assert found is not None and found[0] == key
    assert reg.find_name("없는이름") is None


def test_add_survives_corrupt_neighbour(tmp_path: Path) -> None:
    """손상 이웃 1건이 새 Preset 저장(이름 유일성 스캔)을 죽이지 않는다."""
    reg = PresetRegistry(tmp_path)
    _plant_corruption(tmp_path)
    key = reg.add(_preset("새것"))
    assert reg.load(key).name == "새것"


# ------------------------------------------------------------------ 원자성
def test_writes_leave_no_temp_debris(tmp_path: Path) -> None:
    """저장은 ``write_text_atomic`` 경유 — 임시 파일 잔해가 남지 않는다."""
    reg = PresetRegistry(tmp_path)
    key = reg.add(_preset("표준"))
    reg.save_at(key, _preset("표준", created_at="2026-08-25T00:00:00"))
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    assert len(list(tmp_path.glob("*" + PresetRegistry.SUFFIX))) == 1
