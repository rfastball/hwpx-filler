"""진행 감지 체크리스트 링1 코어 테스트 — #893(설계 정본 ONBOARDING_TUTORIAL.md §1 D3·§3).

못박는 것: 전 단계 전이·티어 졸업·전체 완주, 순서 비강제와 중복 통지 무해, 닫힘/재개의
설계 결정(기록은 하되 카드는 큐잉하지 않는다), 스냅샷의 JSON 왕복, settings 왕복과 비유효
입력의 loud 거절, 그리고 사용자 문안의 금지어 부재.
"""

from __future__ import annotations

import json

import pytest

from hwpxfiller.external import settings
from hwpxfiller.gui.tutorial_state import (
    STEPS,
    TIERS,
    Milestone,
    Tier,
    TutorialViewModel,
)


def _all_milestones() -> "list[Milestone]":
    return [step.milestone for step in STEPS]


def _achieve_all(vm: TutorialViewModel) -> None:
    for milestone in _all_milestones():
        vm.notify(milestone)


def test_step_table_covers_every_milestone_once():
    """열거와 정의표가 1:1 — 문안 없는 단계도, 정의만 있고 통지 못 하는 단계도 없다."""
    assert _all_milestones() == list(Milestone)
    assert len({step.milestone for step in STEPS}) == len(STEPS) == 18


def test_tier_structure_is_the_documented_four_tiers():
    """T0~T8 기본 · T9~T14 응용 · T15~T16 고급 · T17 심화(선택 진입, 한 걸음 — #284)."""
    by_tier: "dict[Tier, list[str]]" = {}
    for step in STEPS:
        by_tier.setdefault(step.tier, []).append(str(step.milestone))
    assert by_tier[Tier.BASIC] == [f"T{n}" for n in range(0, 9)]
    assert by_tier[Tier.APPLIED] == [f"T{n}" for n in range(9, 15)]
    assert by_tier[Tier.ADVANCED] == ["T15", "T16"]
    assert by_tier[Tier.DEEP] == ["T17"]
    assert [d.optional for d in TIERS] == [False, False, False, True]


def test_every_milestone_transitions_exactly_once():
    """전 단계 전이 — 첫 통지는 True, 달성 집합이 하나씩 자란다."""
    vm = TutorialViewModel()
    for index, milestone in enumerate(_all_milestones(), start=1):
        assert vm.notify(milestone) is True
        assert vm.is_achieved(milestone)
        assert vm.snapshot()["achieved_count"] == index


def test_tier_graduation_and_full_completion():
    vm = TutorialViewModel()
    for milestone in _all_milestones()[:9]:
        vm.notify(milestone)
    assert vm.tier_complete(Tier.BASIC)
    assert not vm.tier_complete(Tier.APPLIED)
    assert vm.suggested_tier == "applied"
    assert not vm.standard_complete

    for milestone in _all_milestones()[9:17]:
        vm.notify(milestone)
    assert vm.tier_complete(Tier.APPLIED) and vm.tier_complete("advanced")
    assert vm.standard_complete is True
    assert vm.all_complete is False
    assert vm.suggested_tier == "deep"  # 심화는 앞 세 티어 졸업 뒤에야 제안된다

    vm.notify(Milestone.CHANGE_COMPOSITION)
    assert vm.all_complete is True
    assert vm.suggested_tier == ""


def test_partial_tier_is_not_graduated():
    vm = TutorialViewModel()
    vm.notify(Milestone.COMPILE_TEMPLATE)
    assert not vm.tier_complete(Tier.ADVANCED)
    assert vm.suggested_tier == "basic"


def test_order_is_not_enforced_and_earlier_steps_are_not_backfilled():
    """T4 가 T1 보다 먼저 와도 그대로 기록하고, 앞 단계를 대신 채우지 않는다."""
    vm = TutorialViewModel()
    vm.notify(Milestone.MOUNT_DATA)
    vm.notify(Milestone.PICK_TEMPLATE)
    assert vm.is_achieved("T4") and vm.is_achieved("T1")
    assert not vm.is_achieved(Milestone.INSTALL_EXAMPLES)
    assert vm.progress()["achieved"] == ["T1", "T4"]  # 정본 순서로 정규화


def test_duplicate_notification_is_harmless():
    vm = TutorialViewModel()
    assert vm.notify(Milestone.SAVE_JOB) is True
    assert vm.notify("T3") is False
    assert vm.snapshot()["achieved_count"] == 1
    assert len(vm.pending_moments()) == 1


def test_unknown_milestone_is_loud():
    vm = TutorialViewModel()
    with pytest.raises(ValueError):
        vm.notify("T99")
    with pytest.raises(ValueError):
        vm.is_achieved("설치")


def test_start_is_the_example_install_and_surface_waits_for_it():
    vm = TutorialViewModel()
    vm.notify(Milestone.SAVE_JOB)
    assert vm.started is False and vm.active is False  # 평소 사용이 패널을 불러내지 않는다
    vm.notify(Milestone.INSTALL_EXAMPLES)
    assert vm.started is True and vm.active is True


def test_dismiss_keeps_recording_but_queues_no_moment_and_resume_restores_surface():
    vm = TutorialViewModel()
    vm.notify(Milestone.INSTALL_EXAMPLES)
    vm.dismiss()
    assert vm.dismissed is True and vm.active is False
    assert vm.pending_moments() == ()  # 대기 카드는 종료와 함께 버려진다

    assert vm.notify(Milestone.PICK_TEMPLATE) is True  # 기록은 계속된다
    assert vm.pending_moments() == ()  # 닫힌 동안의 카드는 큐에 쌓지 않는다

    vm.resume()
    assert vm.dismissed is False and vm.active is True
    assert vm.is_achieved(Milestone.PICK_TEMPLATE)
    assert vm.snapshot()["achieved_count"] == 2


def test_moment_queue_is_session_only_and_consumed_by_the_surface():
    vm = TutorialViewModel()
    vm.notify(Milestone.INSTALL_EXAMPLES)
    vm.notify(Milestone.PICK_TEMPLATE)
    assert [str(m) for m in vm.pending_moments()] == ["T0", "T1"]

    assert vm.consume_moment("T0") is True
    assert vm.consume_moment(Milestone.INSTALL_EXAMPLES) is False  # 두 번 소비되지 않는다
    assert [str(m) for m in vm.pending_moments()] == ["T1"]

    # 소비해도 문안은 완료 단계 펼침에 그대로 남는다(§1 D3).
    basic = vm.snapshot()["tiers"][0]
    installed = next(s for s in basic["steps"] if s["milestone"] == "T0")
    assert installed["achieved"] is True and installed["moment_copy"]


def test_restored_progress_does_not_replay_old_moment_cards():
    vm = TutorialViewModel.from_progress({"achieved": ["T0", "T1"], "dismissed": False})
    assert vm.snapshot()["achieved_count"] == 2
    assert vm.pending_moments() == ()
    assert vm.snapshot()["moment_queue"] == []


def test_restore_tolerates_dead_and_absent_values():
    """옛 버전이 남긴 죽은 단계 키·손상 형상이 부팅을 막지 않는다."""
    vm = TutorialViewModel.from_progress({"achieved": ["T0", "T99", 7], "dismissed": True})
    assert vm.progress() == {"achieved": ["T0"], "dismissed": True}

    assert TutorialViewModel.from_progress(None).progress() == {"achieved": [], "dismissed": False}
    assert TutorialViewModel.from_progress({"achieved": "T0"}).progress()["achieved"] == []


def test_retired_deep_tier_step_needs_no_migration():
    """심화 티어 병합 전(#284)에 저장된 ``T18`` 기록은 무해하게 걸러진다.

    마이그레이션을 쓰지 않는 근거를 코드로 고정한다: 죽은 키 관용(#899)이 이미 계약이라
    옛 진행이 부팅을 막지도, 없는 단계를 달성으로 세지도 않는다.
    """
    vm = TutorialViewModel.from_progress({"achieved": ["T16", "T17", "T18"], "dismissed": False})
    assert vm.progress()["achieved"] == ["T16", "T17"]
    assert vm.snapshot()["achieved_count"] == 2
    assert vm.all_complete is False


def test_snapshot_is_json_serialisable_and_carries_tier_copy():
    vm = TutorialViewModel()
    vm.notify(Milestone.INSTALL_EXAMPLES)
    snapshot = vm.snapshot()
    assert json.loads(json.dumps(snapshot, ensure_ascii=False)) == snapshot

    assert snapshot["kind"] == "tutorial-checklist/v1"
    assert snapshot["step_count"] == len(STEPS)
    assert snapshot["suggested_tier"] == "basic"
    assert snapshot["moment_queue"][0]["milestone"] == "T0"
    basic = snapshot["tiers"][0]
    assert basic["tier"] == "basic" and basic["optional"] is False
    assert basic["achieved_count"] == 1 and basic["step_count"] == 9
    assert basic["graduation_copy"] and basic["invitation"]
    for step in basic["steps"]:
        assert step["title"] and step["next_step"] and step["moment_copy"]
    assert snapshot["tiers"][3]["optional"] is True


def test_moment_copy_names_what_did_not_happen():
    """부재의 의미를 짚는 네 자리(§1 D3) — 문안이 통째로 사라지지 않게 못박는다."""
    by_id = {str(step.milestone): step.moment_copy for step in STEPS}
    assert "승인을 묻지 않았습니다" in by_id["T8"]
    assert "데이터를 다시 고르지 않았습니다" in by_id["T9"]
    assert "〘미입력·납품조건〙" in by_id["T13"]  # 빈 값은 빈칸으로 새지 않는다
    assert "절이 빠진 문서" in by_id["T17"]


def test_user_copy_never_exposes_the_internal_slot_word():
    """구간의 사용자 어휘는 '항목'·'선택'이다(UI_VOCABULARY 정본)."""
    texts = [
        text
        for step in STEPS
        for text in (step.title, step.next_step, step.moment_copy)
    ]
    texts += [t for tier in TIERS for t in (tier.label, tier.title, tier.graduation_copy, tier.invitation)]
    for text in texts:
        assert "슬롯" not in text
        assert "slot" not in text.lower()
        assert "—" not in text  # em dash 전면 금지(COPY_STYLE_GUIDE §3)
        assert "「" not in text and "」" not in text


def test_settings_roundtrip_preserves_other_keys_in_the_same_bucket():
    assert settings.load_tutorial_progress() == {"achieved": [], "dismissed": False}

    settings.save_tutorial_progress(achieved=["T0", "T1", "T0"], dismissed=False)
    assert settings.load_tutorial_progress() == {"achieved": ["T0", "T1"], "dismissed": False}

    # 슬라이스 B 가 뒤에 붙일 manifest 칸이 진행 저장으로 지워지지 않는다.
    settings._save_nested("tutorial", "manifest", {"templates": ["a.hwpx"]})
    settings.save_tutorial_progress(achieved=["T0"], dismissed=True)
    assert settings.load_tutorial_progress() == {"achieved": ["T0"], "dismissed": True}
    assert settings._read()["tutorial"]["manifest"] == {"templates": ["a.hwpx"]}


def test_settings_tolerates_partial_corruption_but_rejects_invalid_saves():
    settings._save_key("tutorial", "망가진 값")
    assert settings.load_tutorial_progress() == {"achieved": [], "dismissed": False}

    settings._save_key("tutorial", {"achieved": ["T0", 3, None], "dismissed": "yes"})
    assert settings.load_tutorial_progress() == {"achieved": ["T0"], "dismissed": False}

    with pytest.raises(ValueError):
        settings.save_tutorial_progress(achieved="T0", dismissed=False)
    with pytest.raises(ValueError):
        settings.save_tutorial_progress(achieved=["T0", 3], dismissed=False)
    with pytest.raises(ValueError):
        settings.save_tutorial_progress(achieved=["T0"], dismissed="yes")


def test_view_model_progress_is_the_settings_payload():
    """링1 은 settings 를 모른다 — 왕복은 값으로만 이뤄진다."""
    vm = TutorialViewModel()
    _achieve_all(vm)
    vm.dismiss()
    settings.save_tutorial_progress(**vm.progress())

    restored = TutorialViewModel.from_progress(settings.load_tutorial_progress())
    assert restored.all_complete is True
    assert restored.dismissed is True and restored.active is False
    assert restored.progress() == vm.progress()
