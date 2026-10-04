"""온보딩 튜토리얼 체크리스트의 링2 계약 — 컨트롤러·영속·마일스톤 배선(슬라이스 E · #894).

정본은 ``https://github.com/rfastball/hwpx-filler/blob/5f51e442dde87891b68fbbdc1519a04e01211b8e/docs/ONBOARDING_TUTORIAL.md`` §3.3–3.6(단계별 달성 판정)·§4.3–4.4(통신·영속)다.

이 스위트의 지배 위험은 **조용한 미배선**이다. 통지는 원인 동사의 성공 옆에 한 줄로 붙으므로,
빠져도 화면이 깨지지 않고 그냥 체크가 영영 서지 않는다 — 사용자에게는 "여기까지 했는데 왜
안 넘어가지"로만 보이고 어떤 게이트도 울지 않는다. 그래서 두 방향을 함께 센다:

1. **성립 전이에는 통지가 있다** — 각 배선 지점이 올바른 T 를 낸다.
2. **실패·무변이 전이에는 통지가 없다** — 확인 1차(재진술), 무변이 거절, 차단된 저장에서
   체크가 서면 그것은 하지 않은 일을 했다고 말하는 것이다.

배선 **완전성**(제품 조립이 통지 지점을 가진 컨트롤러 전부에 실물 sink 를 주는가)은 기본값이
조용한 no-op 이라 따로 센다 — 그 기본값은 통지를 안 쓰는 기존 헤드리스 테스트를 위한 것이지
미배선 허용이 아니다.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.domain.job import JOB_MAPPING_AUTHORITY, Job, rules_fingerprints
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.external import settings
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.template_files import TemplateFileStore
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.external.template_root import TemplateRoot
from hwpxfiller.viewmodel.tutorial_state import STEPS, Milestone
from hwpxfiller.webapp.action_registry import validate_dispatch
from hwpxfiller.webapp.screen_editor import EditorController
from hwpxfiller.webapp.screen_template import TemplateController
from hwpxfiller.webapp.screen_tutorial import TutorialController
from hwpxfiller.webapp.tutorial_loop import GenerationLoopLedger
from hwpxfiller.webapp.screen_workbench import TargetFontSetting, WorkbenchController


# ============================================================ 하니스
def _tutorial() -> "tuple[TutorialController, list, list]":
    """컨트롤러 1대 + 푸시 수집 + 저장 호출 수집(영속은 값 왕복이라 대역으로 잰다)."""
    pushes: list = []
    saved: list = []
    ctrl = TutorialController(
        lambda screen, snap: pushes.append((screen, snap)),
        load_progress=lambda: {"achieved": [], "dismissed": False},
        save_progress=lambda **kw: saved.append(kw),
    )
    return ctrl, pushes, saved


def _send(ctrl, action: str, payload: "dict | None" = None):
    """동결된 링1 컨트롤러의 내부 동작만 검사한다(제품 브리지는 새 과정 소유)."""
    return ctrl.dispatch(action, payload or {})


def _collector() -> "tuple[list, object]":
    """마일스톤 수집 sink — 컨트롤러가 무엇을 통지했는지만 본다(링1 재구동 없이)."""
    seen: list = []

    def notify(milestone) -> bool:
        seen.append(str(milestone))
        return True

    return seen, notify


# ============================================================ 1. 컨트롤러 자체
def test_snapshot_is_the_ring1_projection_and_channel_is_tutorial():
    ctrl, _, _ = _tutorial()
    assert ctrl.name == "tutorial"
    snap = ctrl.initial()
    assert snap["kind"] == "tutorial-checklist/v1"
    assert snap["started"] is False and snap["active"] is False
    assert snap["step_count"] == len(STEPS)


def test_notify_records_persists_and_pushes_once_per_new_fact():
    ctrl, pushes, saved = _tutorial()

    assert ctrl.notify(Milestone.INSTALL_EXAMPLES) is True
    assert saved == [{"achieved": ["T0"], "dismissed": False}]
    assert [screen for screen, _ in pushes] == ["tutorial"]
    assert pushes[-1][1]["active"] is True

    # 같은 사실의 재통지는 무해하고 **조용하다** — 생성 한 번이 통지 여럿인 경로에서
    # 디스크 쓰기와 렌더가 곱해지지 않는다.
    assert ctrl.notify(Milestone.INSTALL_EXAMPLES) is False
    assert len(saved) == 1 and len(pushes) == 1


def test_unknown_milestone_is_loud_not_silently_dropped():
    ctrl, _, _ = _tutorial()
    with pytest.raises(ValueError, match="알 수 없는 튜토리얼 단계"):
        ctrl.notify("T999")


def test_unknown_action_is_loud():
    ctrl, _, _ = _tutorial()
    with pytest.raises(ValueError, match="알 수 없는 tutorial 액션"):
        ctrl.dispatch("없는액션", {})


def test_dismiss_and_resume_persist_and_keep_progress():
    ctrl, _, saved = _tutorial()
    ctrl.notify(Milestone.INSTALL_EXAMPLES)
    _send(ctrl, "dismiss")
    assert saved[-1] == {"achieved": ["T0"], "dismissed": True}
    assert ctrl.snapshot()["active"] is False

    _send(ctrl, "resume")
    assert saved[-1] == {"achieved": ["T0"], "dismissed": False}
    snap = ctrl.snapshot()
    assert snap["active"] is True and snap["achieved_count"] == 1


def test_dismissed_session_records_progress_but_queues_no_cards():
    """닫아 둔 사용자가 재개하는 순간 밀린 카드가 쏟아지지 않는다(§1 D3 설계 결정)."""
    ctrl, _, _ = _tutorial()
    _send(ctrl, "dismiss")
    ctrl.notify(Milestone.INSTALL_EXAMPLES)
    ctrl.notify(Milestone.PICK_TEMPLATE)
    _send(ctrl, "resume")
    snap = ctrl.snapshot()
    assert snap["achieved_count"] == 2, "닫힌 동안의 진행이 사라졌습니다"
    assert snap["moment_queue"] == [], "재개 순간 밀린 카드가 쏟아졌습니다"


def test_consume_moment_is_a_round_trip_not_a_frontend_local_erase():
    ctrl, _, _ = _tutorial()
    ctrl.notify(Milestone.INSTALL_EXAMPLES)
    assert [m["milestone"] for m in ctrl.snapshot()["moment_queue"]] == ["T0"]

    assert _send(ctrl, "consume_moment", {"milestone": "T0"}) == {"consumed": True}
    assert ctrl.snapshot()["moment_queue"] == []
    # 이미 소비된 장의 재소비는 거짓을 낸다(조용한 성공 금지).
    assert _send(ctrl, "consume_moment", {"milestone": "T0"}) == {"consumed": False}
    # 문안은 사라지지 않는다 — 완료 단계 펼침에 같은 말이 남는다(§1 D3).
    basic = ctrl.snapshot()["tiers"][0]
    done = next(s for s in basic["steps"] if s["milestone"] == "T0")
    assert done["achieved"] is True and done["moment_copy"]


def test_focus_actions_move_the_aim_without_touching_the_record(tmp_path):
    """#918 C — 초점은 「무엇을 보여줄까」다. 달성 기록도 영속도 건드리지 않는다."""
    ctrl, pushes, saved = _tutorial()
    for step in STEPS:
        ctrl.notify(step.milestone)
    achieved = ctrl.snapshot()["achieved_count"]
    writes = len(saved)

    _send(ctrl, "focus_tier", {"tier": "basic"})
    snap = ctrl.snapshot()
    assert snap["focus_tier"] == "basic" and snap["guided_tier"] == "basic"
    assert snap["focus_caveat"], "기본 과정의 한계 문안이 서지 않았습니다"
    assert snap["achieved_count"] == achieved
    assert len(saved) == writes, "초점 지정이 진행 파일을 다시 썼습니다"
    assert pushes[-1][1]["focus_tier"] == "basic", "초점 전이가 화면에 밀리지 않았습니다"

    _send(ctrl, "clear_focus")
    assert ctrl.snapshot()["focus_tier"] == ""
    assert len(saved) == writes


def test_frozen_focus_refuses_unknown_tier_and_is_not_a_public_action():
    ctrl, _, _ = _tutorial()
    with pytest.raises(ValueError, match="알 수 없는 튜토리얼 과정"):
        _send(ctrl, "focus_tier", {"tier": "초급"})
    # 동결 UI 동사는 새 제품 브리지에 노출되지 않는다.
    with pytest.raises(ValueError):
        validate_dispatch("tutorial", "focus_tier", {"tier": "basic"})
    with pytest.raises(KeyError):
        _send(ctrl, "focus_tier", {"teir": "basic"})


def test_completion_snapshot_stops_pointing_at_a_next_step(tmp_path):
    """#918 A — 18/18 인데 「다음 걸음」을 계속 가리키던 상태의 반대 증거."""
    ctrl, _, _ = _tutorial()
    for step in STEPS[:17]:
        ctrl.notify(step.milestone)
    standard = ctrl.snapshot()
    assert standard["standard_complete"] is True and standard["all_complete"] is False
    assert standard["completion_title"] and "심화" in standard["completion_copy"]

    ctrl.notify(Milestone.CHANGE_COMPOSITION)
    done = ctrl.snapshot()
    assert done["all_complete"] is True
    assert done["guided_tier"] == "", "다 걸었는데 안내가 아직 어딘가를 겨눕니다"
    assert done["revisit_prompt"], "다시 볼 과정을 고를 자리가 없습니다"

    # 완주 뒤 닫았다 열면 완주 상태로 열린다(초점은 세션 값이라 재개가 지난 겨눔을 되살리지
    # 않는다). 재개 문은 완주·미완주 어느 쪽에서도 남는다.
    _send(ctrl, "focus_tier", {"tier": "advanced"})
    _send(ctrl, "dismiss")
    _send(ctrl, "resume")
    reopened = ctrl.snapshot()
    assert reopened["active"] is True and reopened["focus_tier"] == ""
    assert reopened["all_complete"] is True


def test_boot_restores_persisted_progress():
    pushes: list = []
    ctrl = TutorialController(
        lambda screen, snap: pushes.append((screen, snap)),
        load_progress=lambda: {"achieved": ["T0", "T1"], "dismissed": True},
        save_progress=lambda **kw: None,
    )
    snap = ctrl.initial()
    assert snap["achieved_count"] == 2
    assert snap["started"] is True and snap["dismissed"] is True and snap["active"] is False
    assert snap["moment_queue"] == [], "복원한 달성이 옛 카드를 되살렸습니다"


def test_progress_round_trips_through_real_settings(tmp_path, monkeypatch):
    """영속 어댑터 실물 왕복 — 대역이 아니라 ``settings`` 가 같은 값을 되돌려주는가."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    first = TutorialController(
        lambda screen, snap: None,
        load_progress=settings.load_tutorial_progress,
        save_progress=settings.save_tutorial_progress,
    )
    first.notify(Milestone.INSTALL_EXAMPLES)
    first.notify(Milestone.SAVE_JOB)

    second = TutorialController(
        lambda screen, snap: None,
        load_progress=settings.load_tutorial_progress,
        save_progress=settings.save_tutorial_progress,
    )
    restored = second.snapshot()
    assert restored["achieved_count"] == 2 and restored["started"] is True
    assert {s["milestone"] for tier in restored["tiers"]
            for s in tier["steps"] if s["achieved"]} == {"T0", "T3"}


# ============================================================ 2. 배선 완전성
def test_product_assembly_wires_every_notifying_controller(tmp_path, monkeypatch):
    """미배선 기본값은 **정상 상태가 아니다** — 제품 조립이 넷 전부에 실물 sink 를 준다.

    기본값(:func:`unwired_tutorial`)은 통지를 쓰지 않는 기존 헤드리스 테스트를 위한 것이지
    조용한 미배선의 허가가 아니다. 그 구분을 세우는 것이 이 테스트다.
    """
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.webapp.app import WebFrontend

    frontend = WebFrontend()
    tutorial = frontend.controllers["tutorial"]
    for name in ("job", "editor", "tpl", "workbench"):
        assert frontend.controllers[name]._tutorial == tutorial.notify, (
            f"{name} 컨트롤러가 튜토리얼 통지에 배선되지 않았습니다"
        )
    # 누름틀 변환 성립 → 「문서 만들기」 기억. 변이 sink 와 **갈라** 붙는다(slot 개명이
    # 「변환본으로 생성」을 켜지 않게).
    assert frontend.controllers["job"].note_template_compiled in (
        frontend.controllers["tpl"].compile_sinks
    )


#: 발신자가 **명시로** 철거된 단계(#957) — 승인 축. 링1 단계 정의는 동결 자산이라 그대로
#: 서 있고(#941), 링2 통지 지점만 없다. 목록으로 못박는 이유는 아래 전수 스캔이 「배선을
#: 빠뜨렸다」와 「일부러 걷었다」를 가릴 수 있어야 하기 때문이다 — 예외를 목록 없이 풀면
#: 그 스캔이 아무것도 못 잡는다.
RETIRED_MILESTONE_NAMES = frozenset({"APPROVE_VALUES", "APPROVE_WITH_BLANKS"})


def test_every_milestone_has_a_notifying_site_in_the_product():
    """T0~T17 **전수**가 어딘가에서 통지된다 — 등록만 되고 아무도 안 켜는 단계 금지.

    정적 스캔인 이유는 그 결함이 런타임에 침묵이기 때문이다(F7 판정 K: "열거값을 만들어 두고
    아무도 안 쓰면, 나중에 배선을 빠뜨려도 아무 테스트도 울지 않는다").
    """
    root = Path(__file__).resolve().parents[1] / "src" / "hwpxfiller" / "webapp"
    notification_owners = (*sorted(root.glob("screen_*.py")), root / "editor_session.py")
    text = "\n".join(path.read_text(encoding="utf-8") for path in notification_owners)
    missing = [
        step.milestone.name for step in STEPS
        if f"Milestone.{step.milestone.name}" not in text
    ]
    # 명시 철거분만 예외다 — 목록에 있는데 통지 지점이 되살아나도 어긋남으로 선다.
    assert set(missing) == RETIRED_MILESTONE_NAMES, (
        f"통지 지점 형상이 선언과 다릅니다: {sorted(missing)}"
    )


# ============================================================ 3. tpl 배선(T0·T15)
def _tpl(tmp_path: Path, notify):
    lib = tmp_path / "lib"
    lib.mkdir()
    root = TemplateRoot(default_root=lib)      # U6-A: hwpx·txt 가 같은 서식 폴더
    registry = TextTemplateRegistry(root.path)
    ctrl = TemplateController(
        registry,
        lambda screen, snap: None,
        file_store=TemplateFileStore(root.path, registry),
        template_root=root,
        pool_registry=DatasetPoolRegistry(tmp_path / "datasets"),
        tutorial=notify,
    )
    return ctrl


def test_install_examples_notifies_only_after_the_confirm_round(tmp_path):
    seen, notify = _collector()
    ctrl = _tpl(tmp_path, notify)

    ask = ctrl.dispatch("install_examples", {})
    assert ask.get("needs_confirm") is True
    assert seen == [], "1차 재진술에서 시작이 선언됐습니다 — 홈에 아무것도 쓰지 않은 시점입니다"

    done = ctrl.dispatch("install_examples", {"confirm": True})
    assert done["ok"] is True
    assert seen == [str(Milestone.INSTALL_EXAMPLES)]


def test_compile_notifies_only_on_real_mutation(tmp_path):
    """통지 축은 링1 의 ``mutated`` 하나다 — 무변이 거절에서 T15 가 서면 거짓 경보다."""
    seen, notify = _collector()
    ctrl = _tpl(tmp_path, notify)
    ctrl.dispatch("install_examples", {"confirm": True})
    seen.clear()
    compiled: list = []
    ctrl.compile_sinks.append(compiled.append)

    target = next(p for p in (tmp_path / "lib").glob("*.hwpx") if "공고서" in p.name)
    ctrl.dispatch("compile", {"path": str(target), "confirm": True})
    assert seen == [str(Milestone.COMPILE_TEMPLATE)]
    assert compiled == [str(target)], "변환 성립이 「문서 만들기」에 전달되지 않았습니다"

    # 이미 변환된 파일을 다시 변환하면 바꿀 것이 없다 — 그 무변이에는 통지가 없다.
    seen.clear()
    compiled.clear()
    ctrl.dispatch("compile", {"path": str(target), "confirm": True})
    assert seen == [] and compiled == []


# ============================================================ 4. editor 배선(T1·T2·T3/T10·T14)
def _editor(tmp_path: Path, notify, lib_dir: "Path | None" = None):
    """편집기 — 라이브러리 소속 관문은 `tpl` 채널 하나가 진다(U6-E #979).

    종전에는 VM 을 직접 주입했다. 그 자리가 사라졌으므로 격리 루트 위의 실 컨트롤러를
    세워 그 공개 술어를 넘긴다(제품 조립과 같은 짝).
    """
    reg = JobRegistry(tmp_path / "jobs")
    root_dir = lib_dir if lib_dir is not None else tmp_path / "text_templates"
    registry = TextTemplateRegistry(root_dir)
    root = TemplateRoot(default_root=root_dir)
    gate = TemplateController(
        registry, lambda s, snap: None,
        file_store=TemplateFileStore(root.path, registry),
        template_root=root,
        pool_registry=DatasetPoolRegistry(tmp_path / "datasets"),
    )
    ctrl = EditorController(
        reg, lambda s, snap: None,
        clock=lambda: datetime(2026, 8, 25, 9, 0, 0),
        is_library_path=gate.is_live_path,
        template_root=root,
        tutorial=notify,
    )
    return ctrl, reg


#: 편집기 저장 게이트가 요구하는 데이터 결속의 재료(#932 U4-C) — 매핑 판정은 안 바꾼다.
MULTI_SHEET = Path(__file__).parent / "fixtures" / "multi_sheet.xlsx"


def _txt_template(tmp_path: Path, name: str, body: str) -> Path:
    root = tmp_path / "text_templates"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.txt"
    path.write_text(body, encoding="utf-8")
    return path


def test_editor_notifies_template_pick_mapping_completion_and_txt_save(tmp_path):
    seen, notify = _collector()
    ctrl, reg = _editor(tmp_path, notify)
    tpl = _txt_template(tmp_path, "기안", "건명: {{건명}}\n금액: {{금액}}")

    ctrl.dispatch("use_library_template", {"path": str(tpl)})
    assert str(Milestone.PICK_TEMPLATE) in seen
    # 저장 게이트가 데이터 결속을 요구한다(#932 U4-C S2-3). 편집기 마운트는 T4 를 세우지
    # 않는다 — 그 이정표의 축은 「문서 만들기」의 마운트이고 여기서 세우면 온보딩이 실제
    # 진행보다 앞선다. 이 줄은 저장 단언이 도달하게 하는 전제일 뿐이다.
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")

    # 매핑 전확정은 **상승 모서리**다: 확정이 여러 갈래로 도달하므로 액션마다 훅을 달지 않고
    # 링1 ``is_complete()`` 의 false→true 만 읽는다.
    seen.clear()
    ctrl.dispatch("goto_section", {"section": "binding"})   # 매핑 진입(모델 초안 생성)
    ctrl.dispatch("set_display", {"index": 0, "type": "const", "fmt": ""})
    ctrl.dispatch("set_const", {"index": 0, "const": "복사기 임차"})
    ctrl.dispatch("set_display", {"index": 1, "type": "const", "fmt": ""})
    ctrl.dispatch("set_const", {"index": 1, "const": "1,200,000"})
    _confirm_every_row(ctrl)
    assert ctrl.snapshot()["is_complete"] is True
    assert str(Milestone.CONFIRM_MAPPING) in seen
    before = len(seen)
    ctrl.dispatch("confirm_suggested", {})
    assert len(seen) == before, "이미 전확정인데 상승 모서리가 또 잡혔습니다"

    seen.clear()
    ctrl.dispatch("set_name", {"name": "기안작업"})
    result = ctrl.dispatch("save", {})
    assert result.get("ok") is True, result
    # TXT 작업이라 T10 이고 T3(HWPX)이 아니다 — 매체 갈림은 링0 파생 사실을 읽는다.
    assert str(Milestone.SAVE_TXT_JOB) in seen
    assert str(Milestone.SAVE_JOB) not in seen
    assert reg.load("기안작업").media == "txt"


def _confirm_every_row(ctrl) -> None:
    """전 행 확인 — 내용 행은 배지(`set_confirmed`), 빈 행은 빈 고정값 선언 뒤 배지.

    구 「모두 확정」 2발(`confirm_all` + 비움 이름게이트 `confirm_blanks`)의 후계다(U6-C
    #977) — 일괄 승격은 자동 제안만 올리므로 전 행 확인은 행별 답으로 완성된다.
    """
    for row in ctrl.snapshot()["rows"]:
        if not row["confirmable"]:
            ctrl.dispatch("set_display", {"index": row["index"], "type": "const", "fmt": ""})
        ctrl.dispatch("set_confirmed", {"index": row["index"], "confirmed": True})


def test_blocked_save_does_not_notify(tmp_path):
    """차단된 저장은 레지스트리를 건드리지 않는다 — 그 자리에 체크가 서면 거짓말이다."""
    seen, notify = _collector()
    ctrl, _ = _editor(tmp_path, notify)
    tpl = _txt_template(tmp_path, "기안2", "건명: {{건명}}")
    ctrl.dispatch("use_library_template", {"path": str(tpl)})
    seen.clear()

    blocked = ctrl.dispatch("save", {})  # 이름 없음 → 게이트 차단
    assert blocked.get("ok") is not True
    assert str(Milestone.SAVE_JOB) not in seen and str(Milestone.SAVE_TXT_JOB) not in seen


def test_confirming_an_empty_constant_notifies_only_when_a_row_actually_moves(tmp_path):
    """T14 비움 확정의 새 자리는 **빈 고정값을 확인하는 것**이다(「비워 둠」 항목 퇴역).

    체크는 **상태가 실제로 옮겨갔을 때만** 선다: 이미 확인한 행을 다시 확인해도 지나지
    않은 게이트를 지났다고 말하면 안 된다.
    """
    seen, notify = _collector()
    ctrl, _ = _editor(tmp_path, notify)
    tpl = _txt_template(tmp_path, "결핍", "건명: {{건명}}\n보증금: {{계약보증금}}")
    ctrl.dispatch("use_library_template", {"path": str(tpl)})
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")   # 1단계 게이트(U6-B #976)
    ctrl.dispatch("goto_section", {"section": "binding"})
    seen.clear()
    assert ctrl.edit.model is not None
    index = ctrl.edit.model.index_of("계약보증금")

    ctrl.dispatch("set_display", {"index": index, "type": "const", "fmt": ""})
    assert str(Milestone.CONFIRM_EMPTY_FIELD) not in seen, "확인 전에 게이트가 켜졌습니다"
    ctrl.dispatch("set_confirmed", {"index": index, "confirmed": True})
    assert str(Milestone.CONFIRM_EMPTY_FIELD) in seen

    seen.clear()
    ctrl.dispatch("set_confirmed", {"index": index, "confirmed": True})
    assert str(Milestone.CONFIRM_EMPTY_FIELD) not in seen, "이미 비운 행이 다시 게이트를 켰습니다"


# ============================================================ 5. workbench 배선(T11)
def test_copy_notifies_when_the_counter_actually_moves(tmp_path):
    seen, notify = _collector()
    reg = JobRegistry(tmp_path / "jobs")
    ctrl = WorkbenchController(
        reg, lambda s, snap: None,
        clock=lambda: datetime(2026, 8, 25, 9, 0, 0),
        target_font=TargetFontSetting(),
        tutorial=notify,
    )
    tpl = tmp_path / "기안.txt"
    tpl.write_text("수신: {{수신}}", encoding="utf-8")
    job = Job(
        name="복사작업", template_path=str(tpl),
        mapping=MappingProfile(mappings=[FieldMapping(template_field="수신", source="부서")]),
    )
    reg.save(job)
    ctrl.open(reg.load(job.name), [(0, {"부서": "회계과"}), (1, {"부서": "총무과"})])
    assert seen == [], "진입만으로 복사가 체크됐습니다"

    written: list = []
    ctrl.copy_to(ctrl.copy_token(), written.append)
    assert written, "복사가 성사되지 않았습니다"
    assert seen == [str(Milestone.COPY_DRAFT)]
    assert ctrl.snapshot()["copied_count"] == 1


# ============================================================ 6. 루프 이력(T8·T9·T17 재료)
def test_generation_loop_ledger_answers_facts_not_milestones():
    """이력은 **사실**을 답하고 어느 T 인지는 호출자가 정한다(커리큘럼 재판정 금지)."""
    ledger = GenerationLoopLedger()

    first = ledger.note_generated("작업A", mount_key="file:a.csv", slot_shape=None)
    assert first.repeat_job is False and first.other_job_same_mount is False

    # 같은 작업 두 번째 — §3.3 T8 「한 바퀴 더」의 사실.
    again = ledger.note_generated("작업A", mount_key="file:a.csv", slot_shape=None)
    assert again.repeat_job is True and again.other_job_same_mount is False

    # 같은 마운트를 **유지한 채** 다른 작업 — §3.4 T9 작업 전환.
    switched = ledger.note_generated("작업B", mount_key="file:a.csv", slot_shape=None)
    assert switched.other_job_same_mount is True

    # 데이터를 바꾸면 그 마운트의 이력은 새로 시작한다 — 교체 뒤 첫 작업은 전환이 아니다.
    replaced = ledger.note_generated("작업C", mount_key="file:b.csv", slot_shape=None)
    assert replaced.other_job_same_mount is False


def test_generation_loop_ledger_reads_composition_change_as_one_axis():
    """§3.6 T17 — 축은 「직전 실행과 갈래 구성이 다른가」 하나다(#284 병합).

    형상은 실제 예제 자산이 낼 수 있는 것만 쓴다: 항목 1개(`현장설명회`)에 갈래 2개
    (`실시`/`생략`). v1 제어면은 EXACTLY_ONE 이라 항목의 선택이 빈 실행은 서지 않고,
    「절을 뺀다」가 곧 `생략` 을 고르는 것이다.
    """
    ledger = GenerationLoopLedger()
    first = ledger.note_generated(
        "작업A", mount_key="m", slot_shape={"현장설명회": frozenset({"실시"})},
    )
    assert first.options_changed is False, "첫 실행에는 견줄 직전이 없다"

    # 같은 구성으로 한 바퀴 더 — 구성은 그대로라 심화 단계가 서면 거짓이다.
    same = ledger.note_generated(
        "작업A", mount_key="m", slot_shape={"현장설명회": frozenset({"실시"})},
    )
    assert same.options_changed is False

    # 갈래를 바꾼다(절이 빠진 문서) → 구성 변화.
    omitted = ledger.note_generated(
        "작업A", mount_key="m", slot_shape={"현장설명회": frozenset({"생략"})},
    )
    assert omitted.options_changed is True

    # 다른 작업의 구성은 이 작업의 직전이 아니다.
    other = ledger.note_generated(
        "작업B", mount_key="m", slot_shape={"현장설명회": frozenset({"실시"})},
    )
    assert other.options_changed is False

    # 구간을 모르는 실행(조회 불가·구간 없음)은 추측으로 체크하지 않는다.
    unknown = ledger.note_generated("작업A", mount_key="m", slot_shape=None)
    assert unknown.options_changed is False


def test_compiled_memory_is_scoped_to_what_was_actually_converted():
    ledger = GenerationLoopLedger()
    assert ledger.was_compiled("a.hwpx") is False
    ledger.note_compiled("a.hwpx")
    assert ledger.was_compiled("a.hwpx") is True
    assert ledger.was_compiled("b.hwpx") is False
    assert ledger.was_compiled("") is False


# ============================================================ 7. job 배선(T4·T12·T5·T6·T7·T8·T9)
_JOB_NOW = datetime(2026, 8, 25, 9, 0, 0)


def _job_clock():
    current = _JOB_NOW

    def tick():
        nonlocal current
        value = current
        current += timedelta(seconds=1)
        return value

    return tick


def _hwpx_template(path: Path, fields: "list[str]") -> None:
    body = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{name}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for name in fields
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + '</hp:p></hs:sec>'
    ).encode()
    write_hwpx_package(
        path,
        HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}),
    )


def _job_controller(
    tmp_path: Path, notify, *, names=("공고서",), generating: "str | None" = None,
):
    """작업 화면 컨트롤러 — ``generating`` 에 데이터 파일 이름을 주면 문서까지 만든다.

    HWPX 문서 생성은 managed 하나라(#1081 PR2) 문서를 만드는 테스트는 실제 앱처럼 작업
    권위·구성·봉인·작업대 관찰을 한 authority root 로 배선하고, 작업을 그 데이터에 결속한다
    (managed 생성은 결속된 데이터를 요구한다). 그 밖의 테스트는 가벼운 기본 배선이다.
    """
    reg = JobRegistry(tmp_path / "jobs")
    binding = (
        {"data_path": str(tmp_path / generating), "data_sheet": "", "data_header_row": 0}
        if generating
        else {}
    )
    for index, name in enumerate(names):
        template = tmp_path / f"t{index}.hwpx"
        _hwpx_template(template, ["공고명", "추정가격"])
        job = Job(
            name=name,
            template_path=str(template),
            mapping=MappingProfile(mappings=[
                FieldMapping(template_field="공고명", source="bidNtceNm"),
                FieldMapping(template_field="추정가격", source="presmptPrce"),
            ]),
            filename_pattern=f"{name}-{{{{seq:001}}}}",
            binding_authority=JOB_MAPPING_AUTHORITY,
            **binding,
        )
        job.reviewed_rules = rules_fingerprints(job)
        reg.save(job)
    services: dict = {}
    if generating:
        from hwpxfiller.external.seal_execution_plan_service import SealExecutionPlanService
        from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct
        from hwpxfiller.external.template_change import TemplateChangeCoordinator
        from hwpxfiller.webapp.workbench_observation_product import (
            WorkbenchObservationProduct,
        )

        root = tmp_path / "authority"
        services = {
            "template_change": TemplateChangeCoordinator(reg, root=root, clock=_job_clock()),
            "slot_configuration": SlotConfigurationProduct(reg, root=root, clock=_job_clock()),
            "seal_execution": SealExecutionPlanService(reg, root=root, clock=_job_clock()),
            "workbench_observation": WorkbenchObservationProduct(),
        }
    ctrl = JobController(
        reg, lambda s, snap: None,
        clock=_job_clock(),
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        tutorial=notify,
        **services,
    )
    return ctrl, reg


def _csv(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


_CLEAN = "bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n"
_BLANK = "bidNtceNm,presmptPrce\n전산장비,\n사무비품,2000000\n"


def test_mount_notifies_on_every_mount_and_replacement_only_on_a_second_one(tmp_path):
    """§3.2 부기 — 판정 축은 **마운트 성립 사실**이다(자동 마운트도 달성으로 친다)."""
    seen, notify = _collector()
    ctrl, _ = _job_controller(tmp_path, notify)

    ctrl.load_data_path(_csv(tmp_path, "a.csv", _CLEAN))
    assert seen.count(str(Milestone.MOUNT_DATA)) == 1
    assert str(Milestone.REPLACE_DATA) not in seen, "첫 마운트가 교체로 읽혔습니다"

    # 같은 데이터를 다시 세우는 것은 교체가 아니다(부팅 복원이 이 모양이다).
    seen.clear()
    ctrl.load_data_path(_csv(tmp_path, "a.csv", _CLEAN))
    assert str(Milestone.REPLACE_DATA) not in seen

    seen.clear()
    ctrl.load_data_path(_csv(tmp_path, "b.csv", _CLEAN))
    assert str(Milestone.REPLACE_DATA) in seen


def test_select_rows_needs_both_a_seated_job_and_a_non_empty_selection(tmp_path):
    seen, notify = _collector()
    ctrl, _ = _job_controller(tmp_path, notify)
    ctrl.load_data_path(_csv(tmp_path, "a.csv", _CLEAN))
    seen.clear()

    # 작업만 앉혀서는 서지 않는다 — 마운트 직후 선택은 0건이다.
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert str(Milestone.SELECT_ROWS) not in seen

    ctrl.dispatch("set_all", {})
    assert str(Milestone.SELECT_ROWS) in seen


def test_generation_notifies_its_own_event_and_no_approval_event_remains(tmp_path):
    """생성 완주는 그 자체로 통지된다 — 그 앞에 승인이라는 사건은 없다(#957).

    종전 이 자리는 「승인과 생성은 다른 사건」(불변식 §13-4)을 쟀다. 승인 축이 철거되면서
    잴 것이 뒤집혔다: 이 채널이 내는 것은 생성 완주뿐이고, 승인축 T6/T13 은 **어느 전이도
    내지 않는다**. 링1 단계 정의는 동결 자산이라 그대로 서 있으므로(#941) 여기서 재는 것은
    링2 발신자의 부재다 — 남아 있으면 사용자가 하지 않은 일을 했다고 말하게 된다.

    빈 값 있는 데이터를 쓰는 이유는 그것이 종전 승인을 **세우던** 축이기 때문이다.
    """
    seen, notify = _collector()
    ctrl, _ = _job_controller(tmp_path, notify, generating="blank.csv")
    ctrl.load_data_path(_csv(tmp_path, "blank.csv", _BLANK))
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("set_all", {})
    pick_output_folder(ctrl, tmp_path / "out")
    seen.clear()

    assert ctrl.generate()["ok"] is True
    assert str(Milestone.GENERATE) in seen
    assert str(Milestone.SECOND_LAP) not in seen, "첫 바퀴가 두 바퀴로 읽혔습니다"
    for gone in (Milestone.APPROVE_VALUES, Milestone.APPROVE_WITH_BLANKS):
        assert str(gone) not in seen, f"철거된 승인 사건이 통지됐습니다: {gone}"


def test_second_lap_is_the_same_job_generated_again(tmp_path):
    """§3.3 T8 — 「한 바퀴 더」. 앱이 횟수를 어디에도 안 들고 있어 세션이 직접 센다."""
    seen, notify = _collector()
    ctrl, _ = _job_controller(tmp_path, notify, generating="a.csv")
    ctrl.load_data_path(_csv(tmp_path, "a.csv", _CLEAN))
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("set_all", {})
    pick_output_folder(ctrl, tmp_path / "out")
    assert ctrl.generate()["ok"] is True
    seen.clear()

    # 두 번째 바퀴가 가르치는 것: 같은 이름을 조용히 덮지 않는다 — 덮어쓰기 확인을 지나야
    # 성사된다(§3.3 T8).
    assert ctrl.generate()["needs_overwrite"] is True
    assert str(Milestone.SECOND_LAP) not in seen, "확인 왕복 1차에서 체크가 섰습니다"
    assert ctrl.generate(confirm_overwrite=True)["ok"] is True
    assert str(Milestone.SECOND_LAP) in seen


def test_switch_job_is_a_second_work_on_the_same_mount(tmp_path):
    """§3.4 T9 — 데이터를 다시 고르지 않고 작업만 갈아 끼운 생성."""
    seen, notify = _collector()
    ctrl, _ = _job_controller(
        tmp_path, notify, names=("공고서", "구매추진"), generating="a.csv",
    )
    ctrl.load_data_path(_csv(tmp_path, "a.csv", _CLEAN))
    pick_output_folder(ctrl, tmp_path / "out")

    for name in ("공고서", "구매추진"):
        ctrl.dispatch("select_job", {"name": name})
        ctrl.dispatch("set_all", {})
        if name == "구매추진":
            seen.clear()
        assert ctrl.generate()["ok"] is True

    assert str(Milestone.SWITCH_JOB) in seen


def test_frozen_approval_steps_still_stand_in_ring1_but_have_no_producer(tmp_path):
    """T6·T13 은 링1 에 살아 있고(동결 #941) 링2 발신자만 없다(#957).

    종전 이 자리는 「빈 값 포함 승인 **+** 생성 완료」를 링2 왕복으로 쟀다. 승인 사건이
    사라졌으므로 단계 정의는 **링1 을 직접 구동해** 확인하고(동결 자산 삭제 금지), 발신자
    부재는 생성 왕복 쪽 테스트가 잰다. 둘을 함께 두는 이유: 정의만 지우면 되살릴 때 근거가
    사라지고, 정의만 남기고 아무도 안 재면 그 정의가 언제 죽었는지 알 수 없다.
    """
    steps = {step.milestone: step for step in STEPS if step.milestone is not None}
    assert Milestone.APPROVE_VALUES in steps
    assert Milestone.APPROVE_WITH_BLANKS in steps

    # 링1 직접 구동 — 통지를 받으면 그 단계는 여전히 달성으로 선다(구동 경로는 살아 있다).
    ctrl, _pushes, _saved = _tutorial()
    before = ctrl.snapshot()["achieved_count"]
    assert ctrl.notify(Milestone.APPROVE_VALUES) is True
    snap = ctrl.snapshot()
    assert snap["achieved_count"] == before + 1
    achieved = {
        step["milestone"]
        for tier in snap["tiers"] for step in tier["steps"] if step["achieved"]
    }
    assert str(Milestone.APPROVE_VALUES) in achieved


def test_generation_from_a_template_compiled_in_this_session(tmp_path):
    """§3.5 T16 — 변환의 출구가 첫 티어의 입구였음을 세션이 안다(tpl→job seam)."""
    seen, notify = _collector()
    ctrl, reg = _job_controller(tmp_path, notify, generating="a.csv")
    ctrl.load_data_path(_csv(tmp_path, "a.csv", _CLEAN))
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("set_all", {})
    pick_output_folder(ctrl, tmp_path / "out")

    # 변환 사실을 모르면 T16 은 서지 않는다.
    assert ctrl.generate()["ok"] is True
    assert str(Milestone.GENERATE_FROM_COMPILED) not in seen

    # tpl 채널이 그 템플릿의 변환 성립을 알리면 다음 생성이 그 사실을 안다.
    ctrl.note_template_compiled(reg.load("공고서").template_path)
    seen.clear()
    assert ctrl.generate(confirm_overwrite=True)["ok"] is True
    assert str(Milestone.GENERATE_FROM_COMPILED) in seen


def test_new_lessons_invite_once_and_ignore_legacy_progress(tmp_path, monkeypatch):
    from hwpxfiller.viewmodel.tutorial_lessons import LessonProgress
    from hwpxfiller.webapp.onboarding import first_launch_candidate

    new_home = tmp_path / "new"
    assert first_launch_candidate(new_home)
    state = LessonProgress({"achieved": ["T0", "T17"], "dismissed": False}, first_launch=True)
    assert state.snapshot()["invitation"]["visible"]
    assert not any(row["completed"] for row in state.snapshot()["scenarios"])
    state.later()
    restored = LessonProgress(state.progress(), first_launch=True)
    assert not restored.snapshot()["invitation"]["visible"]

    old_home = tmp_path / "old"
    old_home.mkdir()
    (old_home / "settings.json").write_text("{}", encoding="utf-8")
    assert not first_launch_candidate(old_home)
    malformed = LessonProgress({"version": 1, "selected": []}, first_launch=False)
    assert malformed.selected is None


def test_new_lessons_restart_keeps_completion_but_clears_round_evidence():
    from hwpxfiller.viewmodel.tutorial_lessons import LessonProgress

    state = LessonProgress()
    state.select("option_apply")
    record = state.record("option_apply")
    record["checkpoint"] = 7
    record["completed"] = True
    record["context"] = {
        "assets": {"keep": "resource"}, "job_name": "keep-job", "trial_options": ["A", "B"],
        "reviewed_rows": [0, 1], "copied_rows": [0, 1], "applied": True,
    }
    state.restart("option_apply")
    assert record["checkpoint"] == 0 and record["completed"]
    assert record["context"] == {"assets": {"keep": "resource"}, "job_name": "keep-job"}
    assert state.snapshot()["active"] and not state.snapshot()["show_result"]


def test_fresh_practice_is_adopted_only_by_its_own_lesson_restart(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    frontend = WebFrontend()
    tutorial = frontend.controllers["tutorial"]
    tutorial.dispatch("select", {"scenario_id": "field_trial"})
    original = tutorial.snapshot()["resources"]["files"]
    record = tutorial.progress.record("field_trial")
    record["checkpoint"] = 2
    record["completed"] = True
    tutorial.dispatch("prepare_examples", {})
    pending = record["context"]["pending_assets"]
    assert tutorial.snapshot()["resources"]["files"] == original
    tutorial.dispatch("select", {"scenario_id": "contract_txt"})
    assert tutorial.progress.record("contract_txt")["context"].get("pending_assets") is None
    tutorial.dispatch("restart", {"scenario_id": "field_trial"})
    assert tutorial.snapshot()["resources"]["files"][0]["path"] == pending["물품 구매입찰 공고.hwpx"]["path"]
    assert record["completed"] and record["checkpoint"] == 0
    assert all(Path(item["path"]).exists() for item in original)


def test_old_product_completion_cannot_advance_a_new_lesson(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    frontend = WebFrontend()
    tutorial = frontend.controllers["tutorial"]
    tutorial.dispatch("select", {"scenario_id": "contract_txt"})
    old_token = tutorial.observation_token()
    tutorial.dispatch("select", {"scenario_id": "purchase_txt"})
    checkpoint = tutorial.progress.record("purchase_txt")["checkpoint"]
    assert not tutorial.observe_product("editor", "use_library_template", {}, {"ok": True}, token=old_token)
    assert tutorial.progress.record("purchase_txt")["checkpoint"] == checkpoint


def test_modified_practice_file_pauses_guidance_without_erasing_checkpoint(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    app = WebFrontend()
    tutorial = app.controllers["tutorial"]
    tutorial.dispatch("select", {"scenario_id": "first_hwpx"})
    tutorial.dispatch("next", {})
    record = tutorial.progress.record("first_hwpx")
    data = Path(record["context"]["assets"]["공고목록.xlsx"]["path"])
    data.write_bytes(data.read_bytes() + b"user-edit")
    token = tutorial.observation_token()
    assert not tutorial.observe_product("editor", "use_library_template", {}, {"ok": True}, token=token)
    snap = tutorial.snapshot()
    assert not snap["active"] and snap["paused"]
    assert "수정" in snap["recovery"]["body"]
    assert record["checkpoint"] == 1 and data.is_file()


@pytest.mark.parametrize("lesson_id,template_prefix,sheet", [
    ("contract_txt", "낙찰자 선정", "계약"),
    ("purchase_txt", "계약방법 결정", "공고"),
])
def test_txt_lesson_reaches_verified_copy_via_product_actions(
    tmp_path, monkeypatch, lesson_id, template_prefix, sheet,
):
    from hwpxfiller.webapp import app as app_module
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    copied = []
    monkeypatch.setattr(app_module, "set_clipboard_text", copied.append)
    frontend = WebFrontend()
    send = frontend.dispatch
    send("tutorial", "select", {"scenario_id": lesson_id})
    files = frontend.initial("tutorial")["resources"]["files"]
    template = next(item["path"] for item in files if item["name"].startswith(template_prefix))
    data = next(item["path"] for item in files if item["name"] == "공고목록.xlsx")
    beat = frontend.initial("tutorial")["beat"]
    assert beat["guidance"]["library"]["target"] == "new-job"
    assert Path(template).name in beat["body"] and Path(data).name in beat["body"]
    send("editor", "new_session", {})
    send("editor", "use_library_template", {"path": template})
    assert frontend.initial("tutorial")["beat"]["target"] == "data-picker"
    frontend.load_data_sheet("editor", data, sheet)
    send("editor", "goto_section", {"section": "binding"})
    editor = frontend.controllers["editor"]
    rows = {row.template_field: (index, row) for index, row in enumerate(editor.edit.model.rows)}
    if lesson_id == "contract_txt":
        firm = rows["대표계약업체"][0]
        amount = rows["계약보증금"][0]
        send("editor", "set_source", {"index": firm, "source": "계약상대자"})
        send("editor", "set_confirmed", {"index": firm, "confirmed": True})
        send("editor", "set_display", {"index": amount, "type": "amount", "fmt": ""})
        send("editor", "set_confirmed", {"index": amount, "confirmed": True})
    else:
        item = rows["군품명"][0]
        send("editor", "set_slice", {"index": item, "slice": {"mode": "split", "delimiter": ",", "index": 1}})
        send("editor", "set_confirmed", {"index": item, "confirmed": True})
        for index, row in enumerate(editor.edit.model.rows):
            if row.type in {"date", "amount"}:
                send("editor", "set_display", {"index": index, "type": row.type, "fmt": ""})
                send("editor", "set_confirmed", {"index": index, "confirmed": True})
        send("editor", "set_confirmed", {"index": rows["낙찰자결정방법"][0], "confirmed": True})
    send("editor", "set_name", {"name": f"튜토리얼 {lesson_id}"})
    assert send("editor", "save", {})["ok"]
    send("job", "select_job", {"name": editor.edit.job_name, "confirm": True})
    send("job", "set_none", {})
    assert frontend.initial("tutorial")["beat"]["guidance"]["job"]["target"] == "row-selection"
    for index in (0, 1):
        send("job", "toggle_record", {"index": index, "value": True})
    assert frontend.initial("tutorial")["beat"]["guidance"]["job"]["target"] == "open-workbench"
    send("job", "open_workbench", {})
    send("workbench", "step", {"delta": 1})
    assert frontend.initial("tutorial")["checkpoint"] == 5
    precheck = send("workbench", "copy_precheck", {})
    assert frontend.copy_clipboard("workbench", precheck["token"])["copied"]
    if lesson_id == "contract_txt":
        card = frontend.controllers["workbench"].snapshot()["card"]
        other = next(item["index"] for item in card["index_map"] if item["row"] != card["source_row"])
        send("workbench", "set_current", {"index": other})
        precheck = send("workbench", "copy_precheck", {})
        assert frontend.copy_clipboard("workbench", precheck["token"])["copied"]
        assert len(copied) == 2 and copied[0] != copied[1]
        assert all("원" in text for text in copied)
    else:
        assert len(copied) == 1 and "드릴" in copied[0]
        assert "드릴,전동식,휴대용" not in copied[0]
    snap = frontend.initial("tutorial")
    assert snap["checkpoint"] == snap["beat_count"] == 6
    assert snap["result"]["count"] == len(copied)


def _authoring_lesson(tmp_path, monkeypatch, lesson_id):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    app = WebFrontend()
    app.dispatch("tutorial", "select", {"scenario_id": lesson_id})
    assert app.initial("tutorial")["beat"]["target"] == "authoring-open"
    path = next(item["path"] for item in app.initial("tutorial")["resources"]["files"]
                if item["name"].startswith("낙찰자 선정"))
    opened = app.open_authoring_document(path, True)
    return app, opened


def _authoring_command(app, session_id, command):
    current = app.dispatch("authoring", "content", {"session_id": session_id})
    preview = app.dispatch("authoring", "preview", {
        "session_id": session_id, "revision": current["revision"], "command": command,
    })
    return app.dispatch("authoring", "update", {
        "session_id": session_id, "revision": current["revision"], "content": preview["content"],
    })


def test_field_lesson_trials_and_saves_practice_txt(tmp_path, monkeypatch):
    app, opened = _authoring_lesson(tmp_path, monkeypatch, "field_trial")
    sid = opened["session_id"]
    content = opened["content"]
    start = len(content[:content.index("10일")].encode("utf-16-le")) // 2
    updated = _authoring_command(app, sid, {
        "type": "create_field", "start": start, "end": start + 3, "name": "재배정기한",
    })
    rev = updated["revision"]
    values = {row["name"]: "연습값" for row in updated["analysis"]["fields"]}
    app.dispatch("authoring", "trial_input", {
        "session_id": sid, "revision": rev, "values": values, "selected": {},
    })
    trial = app.dispatch("authoring", "trial", {"session_id": sid, "revision": rev})
    assert not trial["report"].get("errors")
    saved = app.dispatch("authoring", "save", {"session_id": sid, "revision": rev})
    assert saved["ok"] and Path(saved["path"]).is_file()
    snap = app.initial("tutorial")
    assert snap["checkpoint"] == snap["beat_count"] == 5
    assert snap["result"]["count"] == 1


def test_option_lesson_trials_both_then_applies_and_reviews_content(tmp_path, monkeypatch):
    app, opened = _authoring_lesson(tmp_path, monkeypatch, "option_apply")
    sid, content = opened["session_id"], opened["content"]
    start = content.index("3. ")
    end = content.index("\n\n붙임", start)
    _authoring_command(app, sid, {"type": "create_slot", "start": start, "end": end,
                                  "id": "예산재배정", "label": "예산 재배정 안내"})
    content = app.dispatch("authoring", "content", {"session_id": sid})["content"]
    start = content.index("3. ")
    _authoring_command(app, sid, {"type": "create_option", "start": start,
                                  "end": content.index("\n", start), "slot_id": "예산재배정",
                                  "id": "안내포함", "label": "안내 포함"})
    current = app.dispatch("authoring", "content", {"session_id": sid})
    content = current["content"].replace("{{/선택}}\n{{/항목}}", "{{/선택}}\n\n{{/항목}}", 1)
    app.dispatch("authoring", "update", {"session_id": sid, "revision": current["revision"], "content": content})
    empty = content.index("\n\n{{/항목}}") + 1
    updated = _authoring_command(app, sid, {"type": "create_option", "start": empty,
                                           "end": empty + 1, "slot_id": "예산재배정",
                                           "id": "안내생략", "label": "안내 생략"})
    values = {row["name"]: "연습값" for row in updated["analysis"]["fields"]}

    def trial(option):
        rev = app.dispatch("authoring", "content", {"session_id": sid})["revision"]
        app.dispatch("authoring", "trial_input", {"session_id": sid, "revision": rev,
                                                  "values": values, "selected": {"예산재배정": option}})
        return app.dispatch("authoring", "trial", {"session_id": sid, "revision": rev})

    trial("안내포함")
    current = app.dispatch("authoring", "content", {"session_id": sid})
    app.dispatch("authoring", "update", {"session_id": sid, "revision": current["revision"],
                                         "content": current["content"] + "\n"})
    trial("안내생략")
    assert app.initial("tutorial")["checkpoint"] == 3  # old revision cannot count
    trial("안내포함")
    rev = app.dispatch("authoring", "content", {"session_id": sid})["revision"]
    assert app.dispatch("authoring", "save", {"session_id": sid, "revision": rev})["ok"]
    impact = app.dispatch("authoring", "impact", {"session_id": sid, "revision": rev})
    name = impact["jobs"][0]["name"]
    prepared = app.dispatch("authoring", "prepare_apply", {"session_id": sid, "revision": rev,
                                                             "job_name": name})
    assert prepared["preparation"]["status"] == "ready"
    applied = app.dispatch("authoring", "apply_job", {"session_id": sid, "revision": rev,
                                                       "job_name": name,
                                                       "change_token": prepared["change_token"]})
    assert applied["status"] == "applied"
    app.dispatch("job", "select_job", {"name": name, "confirm": True})
    app.dispatch("job", "set_all", {})
    view = app.dispatch("job", "open_slot_configuration", {})["current_view"]
    slot_id = view["projection"]["slots"][0]["slot_id"]
    app.dispatch("job", "select_slot_option", {"configuration_token": view["new_configuration_token"],
                                                "slot_id": slot_id, "option_id": "안내포함",
                                                "request_id": "tutorial-include"})
    app.dispatch("job", "open_workbench", {})
    card = app.controllers["workbench"].snapshot()["card"]
    assert "예산 재배정 여부" in "".join(part["text"] for part in card["segments"])
    snap = app.initial("tutorial")
    assert snap["checkpoint"] == snap["beat_count"] == 7
    assert snap["result"]["count"] == 1


def test_replace_data_lesson_persists_new_job_link_not_only_pool_mount(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    app = WebFrontend()
    send = app.dispatch
    send("tutorial", "select", {"scenario_id": "replace_data"})
    tutorial = app.controllers["tutorial"]
    name = tutorial._context()["job_name"]
    original = tutorial._context()["assets"]["공고목록.xlsx"]["path"]
    derived = send("tutorial", "prepare_examples", {})["path"]
    assert derived != original and app.initial("tutorial")["checkpoint"] == 1
    guide = app.initial("tutorial")["beat"]["guidance"]
    assert guide["job"]["primary"]["screen"] == "library"
    assert guide["library"]["target"] == "edit-job"
    assert tutorial.file_picker_hint("data", "job") == ""
    assert not str(app.open_job_in_editor(name)).startswith("ERROR:")
    assert app.initial("tutorial")["beat"]["guidance"]["editor"]["target"] == "data-picker"
    assert tutorial.file_picker_hint("data", "editor") == derived
    app.load_data_sheet("editor", derived, "공고")
    assert app.initial("tutorial")["checkpoint"] == 2
    send("editor", "goto_section", {"section": "binding"})
    send("editor", "resuggest_all", {})
    send("editor", "confirm_suggested", {})
    assert send("editor", "save", {})["ok"]
    assert app.initial("tutorial")["checkpoint"] == 3
    send("job", "select_job", {"name": name, "confirm": True})
    snap = app.initial("tutorial")
    assert snap["checkpoint"] == snap["beat_count"] == 4
    assert app.controllers["job"].data.path == derived
    assert app.controllers["job"].data.sheet == "공고"
    assert snap["result"]["count"] == 1


def test_blank_lesson_observes_missing_value_and_direct_input_repair(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    app = WebFrontend()
    send = app.dispatch
    send("tutorial", "select", {"scenario_id": "blank_values"})
    derived = app.controllers["tutorial"]._context()["derived_data_path"]
    assert Path(derived).is_file() and app.initial("tutorial")["checkpoint"] == 1
    name = app.controllers["tutorial"]._context()["job_name"]
    send("job", "select_job", {"name": name, "confirm": True})
    send("job", "set_none", {})
    send("job", "toggle_record", {"index": 0, "value": True})
    send("job", "open_workbench", {})
    send("workbench", "set_current", {"index": 0})
    card = app.controllers["workbench"].snapshot()["card"]
    assert "계약보증금" in card["empty_fields"]
    assert "단위" not in card["empty_fields"]
    unit = next(row for row in app.controllers["workbench"].snapshot()["rows"] if row["name"] == "단위")
    assert unit["blank_declared"] and unit["value"] == ""
    assert app.initial("tutorial")["checkpoint"] == 2
    send("workbench", "set_map_value", {"name": "계약보증금", "text": "1000000"})
    assert "계약보증금" not in app.controllers["workbench"].snapshot()["card"]["empty_fields"]
    assert app.initial("tutorial")["checkpoint"] == 3
    send("tutorial", "next", {})
    snap = app.initial("tutorial")
    assert snap["checkpoint"] == snap["beat_count"] == 4
    assert snap["result"]["count"] == 1
    assert snap["result"]["next_scenario_id"] == "field_trial"


def _select_notice_options(app, company_label, request_prefix):
    for slot_label, option_label in (("입찰참가자격", company_label), ("낙찰자 결정방법", "고시 미만")):
        view = app.dispatch("job", "open_slot_configuration", {})["current_view"]
        slot = next(item for item in view["projection"]["slots"] if item["display_text"] == slot_label)
        option = next(item for item in slot["options"] if item["display_text"] == option_label)
        app.dispatch("job", "select_slot_option", {
            "configuration_token": view["new_configuration_token"], "slot_id": slot["slot_id"],
            "option_id": option["option_id"], "request_id": f"{request_prefix}-{slot_label}",
        })


@pytest.mark.parametrize("lesson_id,indices,memo,company", [
    ("first_hwpx", (0, 1, 2), "소기업·소상공인", "소기업·소상공인"),
    ("repeat_hwpx", (3, 4, 5), "중·소기업", "중·소기업"),
])
def test_notice_lesson_generates_exact_three_rows_with_options(
    tmp_path, monkeypatch, lesson_id, indices, memo, company,
):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    app = WebFrontend()
    send = app.dispatch
    send("tutorial", "select", {"scenario_id": lesson_id})
    tutorial = app.controllers["tutorial"]
    if lesson_id == "first_hwpx":
        send("tutorial", "next", {})
        files = app.initial("tutorial")["resources"]["files"]
        template = next(item["path"] for item in files if item["name"].endswith(".hwpx"))
        data = next(item["path"] for item in files if item["name"] == "공고목록.xlsx")
        send("editor", "new_session", {})
        send("editor", "use_library_template", {"path": template})
        app.load_data_sheet("editor", data, "공고")
        send("editor", "goto_section", {"section": "binding"})
        send("editor", "confirm_suggested", {})
        send("editor", "goto_section", {"section": "filename"})
        send("editor", "set_pattern", {"pattern": "구매입찰공고-{{입찰공고번호}}"})
        send("editor", "set_name", {"name": "튜토리얼 공고서"})
        assert send("editor", "save", {})["ok"]
        name = app.controllers["editor"].edit.job_name
    else:
        name = tutorial._context()["job_name"]
    send("job", "select_job", {"name": name, "confirm": True})
    if lesson_id == "repeat_hwpx":
        send("job", "set_none", {})
    send("job", "filter_col_text", {"column": "메모", "text": memo})
    for index in indices:
        send("job", "toggle_record", {"index": index, "value": True})
    _select_notice_options(app, company, lesson_id)
    app.controllers["job"].set_output_folder(str(tmp_path / "out"))
    generated = app.generate("job")
    assert generated["ok"] and generated["succeeded"] == 3
    snap = app.initial("tutorial")
    if lesson_id == "first_hwpx":
        assert snap["checkpoint"] == 11
        # The product reopens the delivered bytes and checks their structure.
        job = app.controllers["job"]
        ordinal = job.runs.delivered[0].item_ordinal
        send("job", "artifact_open", {"ordinal": ordinal + 1000})
        assert app.initial("tutorial")["checkpoint"] == 11
        send("job", "artifact_open", {"ordinal": ordinal})
        snap = app.initial("tutorial")
    assert snap["checkpoint"] == snap["beat_count"]
    assert snap["result"]["count"] == 3
    assert len(snap["result"]["documents"]) == 3


@pytest.mark.parametrize("origin,changed", [
    ("job", False), ("job", True), ("job", "missing"),
    ("editor", False), ("authoring", False), ("workbench", False),
])
def test_practice_exit_restores_original_context_only_on_identical_data(tmp_path, monkeypatch, origin, changed):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    app = WebFrontend()
    tutorial = app.controllers["tutorial"]
    job = app.controllers["job"]
    template = tutorial.practice.template_root / "원래 서식.txt"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("{{이름}}", encoding="utf-8")
    data = tmp_path / "original.csv"
    data.write_text("이름\n원래\n다른\n", encoding="utf-8-sig")
    saved = Job(name="원래 작업", template_path=str(template), data_path=str(data),
                mapping=MappingProfile(mappings=[FieldMapping("이름", "이름")]),
                binding_authority=JOB_MAPPING_AUTHORITY)
    job.registry.save(saved)
    job.load_data_path(str(data))
    assert job.dispatch("prefer_work", {"name": saved.name})["promoted"]
    job.dispatch("filter_col_text", {"column": "이름", "text": "원래"})
    job.dispatch("toggle_record", {"index": 0, "value": True})
    original_range = job.data.committed_range().fingerprint()
    original_source = settings.load_last_data_source()
    if origin == "editor":
        app.controllers["editor"].load_job(saved.name)
    if origin == "authoring":
        authoring_id = app.open_authoring_document(str(template), True)["session_id"]
    if origin == "workbench":
        assert job.dispatch("open_workbench", {})["ok"]
    guard = tutorial.dispatch("preflight", {"screen": origin, "action": "select", "scenario_id": "blank_values"})
    assert guard["ok"] and not guard["needs_confirm"]
    if origin == "editor":
        app.controllers["editor"].dispatch("new_session", {})
    tutorial.dispatch("select", {"scenario_id": "blank_values", "transition_token": guard["transition_token"]})
    practice_name = tutorial._context()["job_name"]
    job.dispatch("select_job", {"name": practice_name})
    tutorial.dispatch("select", {"scenario_id": "field_trial"})  # must not replace the original return context
    if origin == "authoring":
        app.open_authoring_document(tutorial._asset("낙찰자 선정 및 계약체결 안내.txt"), True)
    job.set_output_folder(str(tmp_path / "practice-output"))
    settings.save_theme("dark")
    if changed is True:
        data.write_text("이름\n바뀐\n다른\n", encoding="utf-8-sig")
    elif changed == "missing":
        data.unlink()
    result = tutorial.dispatch("exit", {})
    if changed == "missing":
        assert result["ok"] is False and result["error"]
        assert tutorial.snapshot()["practice"]["active"]
        data.write_text("이름\n원래\n다른\n", encoding="utf-8-sig")
        result = tutorial.dispatch("exit", {})
    assert result["ok"] and result["screen"] == origin
    assert job.work.name == saved.name and job.data.path == str(data)
    assert settings.load_last_data_source() == original_source
    assert settings.load_last_output_directory() == "" and job.remembered_output_directory() == ""
    assert settings.load_theme() == "dark"
    assert not tutorial.snapshot()["practice"]["active"]
    assert not tutorial.snapshot()["show_result"]
    if changed is True:
        assert job.data.selected_indices() == [] and not job.data.filter.is_active()
        assert "변경" in result["notice"]
    else:
        assert job.data.committed_range().fingerprint() == original_range
    if origin == "editor":
        assert app.controllers["editor"].edit.base.name == saved.name
    if origin == "authoring":
        assert app.controllers["authoring"].active_id == authoring_id
    if origin == "workbench":
        assert app.controllers["workbench"].job_name == saved.name
    assert job.registry.load(practice_name)  # no automatic practice deletion


def test_practice_transition_guards_stale_tokens_and_keeps_exit_after_setup_failure(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    app = WebFrontend()
    tutorial = app.controllers["tutorial"]
    editor = app.controllers["editor"]
    editor.dispatch("set_name", {"name": "미저장 작업"})
    before = tutorial.progress.progress()
    guard = tutorial.dispatch("preflight", {"screen": "editor", "action": "select", "scenario_id": "first_hwpx"})
    assert guard["needs_confirm"] and tutorial.progress.progress() == before
    with pytest.raises(ValueError, match="저장하지 않은"):
        tutorial.dispatch("select", {"scenario_id": "first_hwpx"})
    tutorial.dispatch("preflight", {"screen": "editor", "action": "navigate", "destination_screen": "library"})
    editor.dispatch("new_session", {})
    with pytest.raises(ValueError, match="다시 시도"):
        tutorial.dispatch("select", {"scenario_id": "first_hwpx", "transition_token": guard["transition_token"]})
    guard = tutorial.dispatch("preflight", {"screen": "library", "action": "select", "scenario_id": "first_hwpx"})
    monkeypatch.setattr(tutorial.practice, "prepare", lambda **_kw: (_ for _ in ()).throw(OSError("prepare failure")))
    with pytest.raises(OSError, match="prepare failure"):
        tutorial.dispatch("select", {"scenario_id": "first_hwpx", "transition_token": guard["transition_token"]})
    assert tutorial.snapshot()["practice"]["active"]
    assert tutorial.progress.selected is None
    assert tutorial.dispatch("exit", {}) == {"ok": True, "screen": "library", "notice": ""}
    assert settings.load_last_data_source() is None
