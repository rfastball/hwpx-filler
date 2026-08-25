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


# ── 목록 필터: 현재 템플릿 구조 호환만 실린다(U3 §2 · #875) ─────────────────────────────
# 프리셋 보관은 Work 밖(홈 레지스트리)이라 종전에는 전량이 매 작업에 떴다 — 다른 템플릿에서
# 만든 것까지 「적용」 버튼을 달고. 여기가 재는 것은 존이 구조 호환으로 좁혀지는가, 그러면서도
# 읽을 수 없는 항목은 계속 시끄럽게 남는가다. 호환 판정 자체는 application 층 테스트가 잰다.


def _clear(ctrl, token: str, slot_id: str, request_id: str) -> str:
    res = ctrl.dispatch("clear_slot_selection", {
        "configuration_token": token, "slot_id": slot_id, "request_id": request_id,
    })
    fresh = res["current_view"]["new_configuration_token"]
    assert fresh
    return str(fresh)


def _seat_second_work(ctrl, reg, tmp_path: Path, name: str) -> None:
    """구조가 **다른** 두 번째 작업(후속 구조 템플릿)을 세우고 그리로 옮긴다."""
    from hwpxfiller.domain.job import Job

    other = tmp_path / f"{name}.hwpx"
    _two_slot_template(other, successor=True)  # _S_GONE 없음 · _O_DROP 없음
    reg.save(Job(name=name, template_path=str(other)))
    ctrl.dispatch("select_job", {"name": name})
    ctrl.dispatch("template_check", {"request_id": "k-other"})


def test_zone_lists_only_presets_the_current_structure_can_fully_apply(
    tmp_path: Path,
) -> None:
    """A 구조에서 저장한 두 프리셋이 A 에는 다 실리고, 구조가 다른 B 에는 맞는 것만 남는다."""
    ctrl, token, _tpl = _seated(tmp_path)  # _S_KEEP=_O_KEEP · _S_GONE=_O_ONLY
    ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "두 칸",
    })
    # _S_GONE 을 비워 **후속 구조에서도 서는** 프리셋을 하나 더 만든다(양성 대조).
    token = _clear(ctrl, token, _S_GONE, "r-clear")
    ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "한 칸",
    })
    assert [item["name"] for item in _presets_zone(ctrl)["items"]] == ["두 칸", "한 칸"]

    _seat_second_work(ctrl, reg=ctrl.registry, tmp_path=tmp_path, name="다른 공고서")

    zone = _presets_zone(ctrl)
    assert zone["supported"] is True  # 구획 자격은 그대로다(호환 0건이어도 진다)
    # 「두 칸」은 이 구조에 _S_GONE 이 없어 부분 적용밖에 못 한다 → 목록에서 빠진다.
    assert [item["name"] for item in zone["items"]] == ["한 칸"]
    # 뺀 것이지 지운 것이 아니다 — 파일은 그대로고 원래 작업으로 돌아가면 다시 뜬다.
    assert len(list(default_preset_dir().glob("*.preset.json"))) == 2
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert [item["name"] for item in _presets_zone(ctrl)["items"]] == ["두 칸", "한 칸"]


def test_incompatible_zone_still_lists_corrupt_entries_loudly(tmp_path: Path) -> None:
    """손상 항목은 호환 판정의 대상이 아니라 표시 대상이다 — 호환 0건이어도 그대로 선다."""
    ctrl, token, _tpl = _seated(tmp_path)
    ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "두 칸",
    })
    broken_key = "cafe0000cafe0000"
    (default_preset_dir() / f"{broken_key}.preset.json").write_text(
        json.dumps({"schema_version": "selection-preset/v1", "name": "망가진 것"}),
        encoding="utf-8",
    )

    _seat_second_work(ctrl, reg=ctrl.registry, tmp_path=tmp_path, name="다른 공고서")

    zone = _presets_zone(ctrl)
    assert zone["items"] == []  # 호환 0건 → 구획은 기존 빈 상태로 선다
    assert [entry["file_name"] for entry in zone["corrupt"]] == [
        f"{broken_key}.preset.json"
    ]
    assert zone["corrupt"][0]["error"] and zone["corrupt_code"] == "PRESET_ENTRY_CORRUPT"


def test_zone_before_template_check_claims_no_compatible_item_without_issuing_id(
    tmp_path: Path,
) -> None:
    """템플릿 확인 전(복제본)은 대고 물을 구조가 없다 — 호환 0건이고 durable id 도 안 난다.

    렌더가 durable id 를 발급하면 write-on-read 다(`_slot_configuration_zone` 과 같은 규율).
    """
    ctrl, token, _tpl = _seated(tmp_path)
    ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "두 칸",
    })
    clone = ctrl.registry.clone("공고서")
    ctrl.dispatch("select_job", {"name": clone})

    assert _presets_zone(ctrl) == {
        "supported": True, "items": [], "corrupt": [], "corrupt_code": "PRESET_ENTRY_CORRUPT",
    }
    assert ctrl.registry.load(clone).authority_id == ""  # 렌더가 발급하지 않았다


def test_product_claims_no_compatible_item_when_the_structure_cannot_be_resolved(
    tmp_path: Path,
) -> None:
    """구조를 세우지 못하는 Work 는 호환 0건이다 — 전량 노출로 새지 않는다.

    존은 durable id 미발급 Work 를 Product 에 넘기지도 않지만(위 테스트), 그 가드가 **없어도**
    아래가 안전한지를 여기서 직접 잰다: 확인을 지나지 않아 template application 이 없으면
    대고 물을 구조가 없고, 손상 항목만 그대로 남는다.
    """
    from hwpxfiller.domain.job import Job

    ctrl, token, _tpl = _seated(tmp_path)
    ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "두 칸",
    })
    (default_preset_dir() / "cafe0000cafe0000.preset.json").write_text(
        json.dumps({"schema_version": "selection-preset/v1"}), encoding="utf-8"
    )
    unchecked = tmp_path / "미확인.hwpx"
    _two_slot_template(unchecked)
    ctrl.registry.save(Job(name="미확인", template_path=str(unchecked)))

    listing = ctrl._slot_configuration.list_selection_presets("미확인")
    assert listing.items == ()
    assert listing.corrupt_count == 1 and listing.corrupt[0].error


def test_apply_path_still_defends_after_the_list_is_filtered(tmp_path: Path) -> None:
    """목록이 걸러져도 적용 경로의 부분 적용·깨짐 보고는 그대로다(방어층 불변 · #875 요구 4)."""
    ctrl, token, _tpl = _seated(tmp_path)
    key = ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "두 칸",
    })["saved_key"]

    _seat_second_work(ctrl, reg=ctrl.registry, tmp_path=tmp_path, name="다른 공고서")
    assert _presets_zone(ctrl)["items"] == []  # 목록에는 없지만

    token = _token(ctrl)
    res = ctrl.dispatch("apply_selection_preset", {  # 키를 직접 부르면 여전히 판정한다
        "configuration_token": token, "preset_key": key,
    })
    assert res["rejection_code"] is None
    assert res["applied_slot_ids"] == (_S_KEEP,) and res["broken_count"] == 1
    assert [item["slot_id"] for item in res["broken"]] == [_S_GONE]


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


# ── S10-03(#860): Preset 이 TXT 작업에서도 선다 — **게이트 개방만으로** ─────────────────
# Preset 기계(도메인 값·store·명령·수치)는 어디에도 매체가 없다. 그 사실의 검사 가능한
# 얼굴이 이 왕복이다: TXT 전용 코드를 한 줄도 더하지 않고 저장·나열·적용이 성사된다.


def test_txt_work_saves_and_applies_a_selection_preset_with_no_extra_machinery(
    tmp_path: Path,
) -> None:
    from tests.test_webapp_job_slot_configuration import _txt_slot_bearing_controller

    ctrl, _reg, _tpl = _txt_slot_bearing_controller(tmp_path)
    token = _token(ctrl)
    token = _select(ctrl, token, "첨부", "견적서", "r1")

    saved = ctrl.dispatch("save_selection_preset", {
        "configuration_token": token, "name": "견적 안내",
    })
    assert saved["status"] == "SAVED" and saved["saved_key"]

    zone = _presets_zone(ctrl)
    assert zone["supported"] is True
    assert [item["name"] for item in zone["items"]] == ["견적 안내"]

    # 다른 선택으로 옮긴 뒤 Preset 을 적용하면 저장 당시 선택으로 되돌아온다.
    token = _select(ctrl, token, "첨부", "계약서", "r2")
    applied = ctrl.dispatch("apply_selection_preset", {
        "configuration_token": token, "preset_key": saved["saved_key"],
    })
    assert applied["rejection_code"] is None
    assert (applied["applied_count"], applied["broken_count"]) == (1, 0)
    assert applied["current_view"]["projection"]["slots"][0]["effective_option_ids"] == (
        "견적서",
    )
