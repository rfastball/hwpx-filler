"""「포함할 내용」 존의 Selection Preset 배선 가드(S9-03 · #829) — 헤드리스 컨트롤러.

판정·수치·코드는 S9-02(:mod:`hwpxfiller.application.preset_command` ·
``external/slot_command_runner``)가 소유하고 그 테스트가 잰다. 여기가 잰다: 두 동사가
**dispatch 경로**로 Product 에 도달하고, 저장의 확인 왕복(조용한 덮기 0)과 적용의 수치
(적용 n·깨짐 m)가 **재조립 없이 그대로** 관통하며, 스냅샷 존이 손상 항목을 숨기지 않고,
적용이 select 와 같은 규율(생성 상호배제·자동 확인 진입)로 서는지.

하네스는 :mod:`tests.test_webapp_job_slot_configuration` 의 slot-bearing 컨트롤러를 그대로
쓴다 — 같은 seam 을 두 번 지어 두 판정이 갈라지는 것을 막는다. Preset 레지스트리는 주입하지
않는다: 홈 기본 위치 해석(:func:`~hwpxfiller.host.locations.default_preset_dir`)까지가 이
슬라이스의 배선이고, autouse 홈 격리가 개발자 실설정을 지킨다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwpxfiller.host.locations import default_preset_dir

from tests.test_slot_configuration_product import (
    _O_DROP,
    _O_KEEP,
    _O_ONLY,
    _S_GONE,
    _S_KEEP,
    _two_slot_template,
)
from tests.test_webapp_job_slot_configuration import _slot_bearing_controller


def _token(ctrl) -> str:
    token = ctrl.dispatch("open_slot_configuration", {})["current_view"][
        "new_configuration_token"
    ]
    assert token
    return str(token)


def _select(ctrl, token: str, slot_id: str, option_id: str, request_id: str) -> str:
    res = ctrl.dispatch("select_slot_option", {
        "configuration_token": token, "slot_id": slot_id,
        "option_id": option_id, "request_id": request_id,
    })
    fresh = res["current_view"]["new_configuration_token"]
    assert fresh
    return str(fresh)


def _seated(tmp_path: Path):
    """Slot 둘짜리 managed Work + 선택 둘이 서 있는 상태의 (컨트롤러, 최신 token, 템플릿)."""
    ctrl, _reg, tpl = _slot_bearing_controller(tmp_path)
    token = _token(ctrl)
    token = _select(ctrl, token, _S_KEEP, _O_KEEP, "r1")
    token = _select(ctrl, token, _S_GONE, _O_ONLY, "r2")
    return ctrl, token, tpl


def _advance_to_successor(ctrl, tpl: Path) -> None:
    """실 템플릿 파일을 successor 로 바꾸고 화면이 시키는 확인·적용으로 앞세운다."""
    _two_slot_template(tpl, successor=True)
    prepared = ctrl.dispatch("template_check", {"request_id": "k-succ"})["preparation"]
    ctrl.dispatch("template_apply", {"change_token": prepared["change_token"]})


def _presets_zone(ctrl) -> dict:
    return ctrl.snapshot()["content_presets"]


# ── 저장: 도달·확인 왕복·거절 ────────────────────────────────────────────────────────────
def test_save_reaches_product_and_lands_in_registry_and_snapshot(tmp_path: Path) -> None:
    ctrl, token, _tpl = _seated(tmp_path)

    res = ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "표준 구성",
    })
    assert res["status"] == "SAVED" and res["code"] is None and res["saved_key"]

    zone = _presets_zone(ctrl)
    assert zone["supported"] is True
    assert [item["name"] for item in zone["items"]] == ["표준 구성"]
    assert zone["items"][0]["key"] == res["saved_key"]
    assert zone["items"][0]["created_at"]
    assert zone["corrupt"] == []
    # provenance 는 내부 정보라 존에 싣지 않는다(Application·contract id 는 사용자 어휘가 아니다).
    assert "provenance" not in zone["items"][0]
    # 레지스트리에 실제로 앉았다 — 스냅샷이 메모리 사본을 그린 것이 아니다.
    files = list(default_preset_dir().glob("*.preset.json"))
    assert len(files) == 1 and "표준 구성" in files[0].read_text(encoding="utf-8")


def test_name_conflict_needs_confirm_writes_nothing_then_confirmed_overwrites_same_key(
    tmp_path: Path,
) -> None:
    ctrl, token, _tpl = _seated(tmp_path)
    first = ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "표준 구성",
    })
    saved_key = first["saved_key"]
    before = (default_preset_dir() / f"{saved_key}.preset.json").read_bytes()

    # 다른 선택으로 바꾼 뒤 같은 이름으로 저장 → 확인 왕복(쓰기 0).
    token = _select(ctrl, token, _S_KEEP, _O_DROP, "r3")
    conflict = ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "표준 구성",
    })
    assert conflict["status"] == "NEEDS_CONFIRM"
    assert conflict["code"] == "PRESET_NAME_CONFLICT"
    assert conflict["saved_key"] is None
    assert conflict["existing_key"] == saved_key and conflict["existing_created_at"]
    assert (default_preset_dir() / f"{saved_key}.preset.json").read_bytes() == before
    assert len(_presets_zone(ctrl)["items"]) == 1  # 유령 항목 0

    confirmed = ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "표준 구성",
        "confirmed_overwrite_key": saved_key,
    })
    assert confirmed["status"] == "SAVED" and confirmed["saved_key"] == saved_key
    assert (default_preset_dir() / f"{saved_key}.preset.json").read_bytes() != before
    assert len(_presets_zone(ctrl)["items"]) == 1  # 덮었지 늘리지 않았다


def test_empty_selection_save_is_rejected_with_reason(tmp_path: Path) -> None:
    ctrl, _reg, _tpl = _slot_bearing_controller(tmp_path)
    token = _token(ctrl)  # 아직 아무것도 고르지 않았다
    res = ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "빈 구성",
    })
    assert res["status"] == "REJECTED"
    assert res["code"] == "PRESET_EMPTY_SELECTION"
    assert res["saved_key"] is None and res["detail"]
    assert _presets_zone(ctrl)["items"] == []


# ── 적용: outcome·fresh view·새 token·수치 관통 ──────────────────────────────────────────
def test_apply_reaches_product_with_outcome_fresh_token_and_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, token, _tpl = _seated(tmp_path)
    key = ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "표준 구성",
    })["saved_key"]
    # 다른 것으로 바꿔 둔다 — 적용이 실제로 되돌리는지 보려면 지금이 저장 시점과 달라야 한다.
    token = _select(ctrl, token, _S_KEEP, _O_DROP, "r3")

    seen: list = []
    monkeypatch.setattr(ctrl, "_maybe_auto_check", lambda response: seen.append(response))

    res = ctrl.dispatch("apply_selection_preset", {
        "configuration_token": token, "preset_key": key,
    })
    assert res["rejection_code"] is None and res["rejection_detail"] is None
    assert res["mutation_outcome"]["outcome_code"] == "CHANGED"
    assert res["mutation_outcome"]["changed"] is True
    assert res["current_view"]["view_status"] == "CURRENT"
    fresh = res["current_view"]["new_configuration_token"]
    assert fresh and fresh != token  # view 가 갈렸으니 새 token 이 함께 온다
    # 수치는 backend 값 그대로다(재조립 0) — id 목록과 개수가 같은 출처에서 나온다.
    assert res["applied_count"] == len(res["applied_slot_ids"]) == 2
    assert set(res["applied_slot_ids"]) == {_S_KEEP, _S_GONE}
    assert res["broken_count"] == len(res["broken"]) == 0
    # 저장 시점 선택으로 복귀했다.
    effective = {
        slot["slot_id"]: slot["effective_option_ids"]
        for slot in res["current_view"]["projection"]["slots"]
    }
    assert tuple(effective[_S_KEEP]) == (_O_KEEP,)

    # 자동 확인 진입 — select 와 **같은 규율**이고, preset 응답이 그 판정의 입력 형을 만족한다.
    assert len(seen) == 1
    assert seen[0].mutation_outcome is not None and seen[0].mutation_outcome.changed is True


def test_partial_match_passes_applied_and_broken_counts_through_unchanged(
    tmp_path: Path,
) -> None:
    """부분 일치: 적용 n>0 · 깨짐 m>0 이 응답에 **그대로** 실린다(링2 가 다시 세지 않는다)."""
    ctrl, token, tpl = _seated(tmp_path)
    key = ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "표준 구성",
    })["saved_key"]
    _advance_to_successor(ctrl, tpl)  # Option 하나·Slot 하나가 사라진다

    token = _token(ctrl)
    res = ctrl.dispatch("apply_selection_preset", {
        "configuration_token": token, "preset_key": key,
    })
    assert res["rejection_code"] is None
    assert res["applied_slot_ids"] == (_S_KEEP,)
    assert res["applied_count"] == 1
    assert res["broken_count"] == 1
    assert [item["slot_id"] for item in res["broken"]] == [_S_GONE]
    # 깨진 항목은 detached 어휘로 재진술된다 — 조용히 버려지지 않는다.
    assert res["broken"][0]["selected_option_ids"] == (_O_ONLY,)


def test_apply_of_missing_preset_is_rejected_loudly_without_view(tmp_path: Path) -> None:
    ctrl, token, _tpl = _seated(tmp_path)
    res = ctrl.dispatch("apply_selection_preset", {
        "configuration_token": token, "preset_key": "0" * 16,
    })
    assert res["rejection_code"] == "PRESET_NOT_FOUND" and res["rejection_detail"]
    assert res["mutation_outcome"] is None and res["current_view"] is None
    assert res["applied_count"] == 0 and res["broken_count"] == 0


# ── 손상 항목: 숨기지 않고 병기 + 적용 거절 코드 ────────────────────────────────────────
def test_corrupt_entry_is_listed_beside_healthy_items_and_rejects_on_apply(
    tmp_path: Path,
) -> None:
    ctrl, token, _tpl = _seated(tmp_path)
    ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "표준 구성",
    })
    broken_key = "cafe0000cafe0000"
    (default_preset_dir() / f"{broken_key}.preset.json").write_text(
        json.dumps({"schema_version": "selection-preset/v1", "name": "망가진 것"}),
        encoding="utf-8",
    )

    zone = _presets_zone(ctrl)
    assert [item["name"] for item in zone["items"]] == ["표준 구성"]  # 정상 항목은 그대로
    assert [entry["file_name"] for entry in zone["corrupt"]] == [
        f"{broken_key}.preset.json"
    ]
    assert zone["corrupt"][0]["error"]  # 사유 병기(숨기지 않는다)
    assert zone["corrupt_code"] == "PRESET_ENTRY_CORRUPT"

    res = ctrl.dispatch("apply_selection_preset", {
        "configuration_token": token, "preset_key": broken_key,
    })
    # 「없다」와 「읽을 수 없다」는 다른 사실이라 코드를 가른다.
    assert res["rejection_code"] == "PRESET_ENTRY_CORRUPT" and res["rejection_detail"]


# ── 생성 상호배제 · 미지원 조건 · 미주입 ────────────────────────────────────────────────
def test_apply_rejected_while_generating(tmp_path: Path) -> None:
    ctrl, token, _tpl = _seated(tmp_path)
    key = ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "표준 구성",
    })["saved_key"]
    assert ctrl._generation_lock.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match="문서 생성이 진행 중"):
            ctrl.dispatch("apply_selection_preset", {
                "configuration_token": token, "preset_key": key,
            })
    finally:
        ctrl._generation_lock.release()


def test_zone_unsupported_without_selected_job(tmp_path: Path) -> None:
    ctrl, _reg, _tpl = _slot_bearing_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": ""})
    zone = _presets_zone(ctrl)
    assert zone == {"supported": False, "items": [], "corrupt": []}


def test_unwired_preset_commands_reject_loudly(tmp_path: Path) -> None:
    from tests.test_webapp_job_slot_configuration import _controller

    ctrl, _pushes = _controller(tmp_path, wire=False, bootstrap=False)
    with pytest.raises(ValueError):
        ctrl.dispatch("save_selection_preset", {"configuration_token": "t", "name": "n"})
    with pytest.raises(ValueError):
        ctrl.dispatch("apply_selection_preset", {"configuration_token": "t", "preset_key": "k"})
    assert ctrl.snapshot()["content_presets"]["supported"] is False


# ── dispatch 스키마: 미등록 키·필수 키 누락은 조용히 무시되지 않는다 ────────────────────
def test_action_registry_rejects_unregistered_and_missing_payload_keys() -> None:
    from hwpxfiller.webapp.action_registry import validate_dispatch

    with pytest.raises(ValueError, match="미등록 키"):
        validate_dispatch("job", "apply_selection_preset", {
            "configuration_token": "t", "preset_key": "k", "request_id": "r",
        })
    with pytest.raises(ValueError, match="필수 키 누락"):
        validate_dispatch("job", "save_selection_preset", {"configuration_token": "t"})
    # 등록된 형태는 통과한다(확인 키는 선택).
    assert validate_dispatch("job", "save_selection_preset", {
        "configuration_token": "t", "name": "n", "confirmed_overwrite_key": "k",
    })
