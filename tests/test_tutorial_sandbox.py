"""튜토리얼 연습 환경 — 사용자 환경 무변경과 같은 창 전환의 계약(#1126).

지배 위험은 **연습이 사용자 자산에 흔적을 남기는 것**이다: 서식 폴더의 사본, 작업 목록의 연습
작업, 데이터 풀 등록, 마지막 데이터·저장 폴더 같은 설정. 그래서 진입부터 이탈까지 실제 제품
동작(작업 저장·데이터 등록·문서 생성·과정 전환·처음부터)을 한 바퀴 돌린 뒤 사용자 홈의 해당
자산을 **바이트 단위로** 비교한다.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hwpxfiller.domain.job import JOB_MAPPING_AUTHORITY, Job
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external import settings
from hwpxfiller.external.tutorial_workspace import TutorialWorkspace
from hwpxfiller.host import locations
from hwpxfiller.viewmodel.tutorial_lessons import NOTICE_CONSTANTS


def _tree(root: Path) -> dict:
    if not root.exists():
        return {"<missing>": None}
    if root.is_file():
        return {"": root.read_bytes()}
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else "<dir>"
            for path in sorted(root.rglob("*"))}


def _user_state(app, home: Path) -> dict:
    places = {
        "templates": app._workspaces.user.template_root.path(),
        "settings": home / "settings.json",
        **{name: home / name for name in (
            "jobs", "datasets", "template_authority", "presets", "authoring", "example_data",
        )},
    }
    return {name: _tree(path) for name, path in places.items()}


def _listed(controller) -> str:
    return json.dumps(controller.snapshot(), ensure_ascii=False, default=str)


def _user_environment(app, tmp_path: Path) -> Job:
    """사용자 서식·작업·데이터 마운트·행 선택·저장 폴더가 있는 평범한 환경."""
    job = app.controllers["job"]
    template = app._template_root.path() / "내 서식.txt"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("{{이름}} 님", encoding="utf-8")
    data = tmp_path / "내 데이터.csv"
    data.write_text("이름\n가\n나\n", encoding="utf-8-sig")
    saved = Job(name="내 작업", template_path=str(template), data_path=str(data),
                mapping=MappingProfile(mappings=[FieldMapping("이름", "이름")]),
                binding_authority=JOB_MAPPING_AUTHORITY)
    job.registry.save(saved)
    job.load_data_path(str(data))
    assert job.dispatch("prefer_work", {"name": saved.name})["promoted"]
    job.dispatch("toggle_record", {"index": 1, "value": True})
    out = tmp_path / "내 결과"
    out.mkdir()
    job.set_output_folder(str(out))
    return saved


def _first_hwpx_round(app) -> None:
    """첫 HWPX 과정을 실제 제품 동작으로 — 작업 저장·데이터 등록·생성까지."""
    send = app.dispatch
    send("tutorial", "next", {})
    files = app.initial("tutorial")["resources"]["files"]
    template = next(item["path"] for item in files if item["name"].endswith(".hwpx"))
    data = next(item["path"] for item in files if item["name"] == "공고목록.xlsx")
    send("editor", "new_session", {})
    send("editor", "use_library_template", {"path": template})
    app.load_data_sheet("editor", data, "공고")
    send("editor", "goto_section", {"section": "binding"})
    for index, row in enumerate(app.controllers["editor"].edit.model.rows):
        if row.template_field in NOTICE_CONSTANTS:
            send("editor", "set_display", {"index": index, "type": "const", "fmt": ""})
            send("editor", "set_const", {"index": index, "const": NOTICE_CONSTANTS[row.template_field]})
        elif row.template_field == "게시일":
            send("editor", "set_source", {"index": index, "source": "게시일시"})
        send("editor", "set_confirmed", {"index": index, "confirmed": True})
    send("editor", "goto_section", {"section": "filename"})
    send("editor", "set_pattern", {"pattern": "구매입찰공고-{{입찰공고번호}}"})
    send("editor", "set_name", {"name": "튜토리얼 공고서"})
    assert send("editor", "save", {})["ok"]
    registered = app.load_data_sheet("job", data, ["공고"])
    assert registered["mount"] and not registered["error"]
    send("job", "select_job", {"name": "튜토리얼 공고서", "confirm": True})
    send("job", "set_none", {})
    for index in (0, 1):
        send("job", "toggle_record", {"index": index, "value": True})
    for slot_label, option_label in (("입찰참가자격", "소기업·소상공인"), ("낙찰자 결정방법", "고시 미만")):
        view = send("job", "open_slot_configuration", {})["current_view"]
        slot = next(item for item in view["projection"]["slots"] if item["display_text"] == slot_label)
        option = next(item for item in slot["options"] if item["display_text"] == option_label)
        send("job", "select_slot_option", {
            "configuration_token": view["new_configuration_token"], "slot_id": slot["slot_id"],
            "option_id": option["option_id"], "request_id": f"sandbox-{slot_label}",
        })
    generated = app.generate("job")
    assert generated["ok"] and generated["succeeded"] == 2, generated
    lesson_home = Path(app.controllers["tutorial"]._context()["home"])
    assert Path(generated["out_dir"]).is_relative_to(lesson_home)


def test_tutorial_round_trip_leaves_user_environment_byte_identical(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    home = tmp_path / "home"
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))
    app = WebFrontend()
    tutorial = app.controllers["tutorial"]
    user = dict(app.controllers)
    _user_environment(app, tmp_path)
    app.controllers["library"].vm.refresh()
    assert "내 작업" in _listed(app.controllers["library"])
    before = _user_state(app, home)
    remembered = (user["job"].data.path, user["job"].data.selected_indices(), user["job"].work.name)

    guard = tutorial.dispatch("preflight", {"screen": "job", "action": "start", "scenario_id": "first_hwpx"})
    tutorial.dispatch("start", {"scenario_id": "first_hwpx", "transition_token": guard["transition_token"]})
    assert tutorial.snapshot()["practice"]["active"]
    assert locations.workspace_home() != home
    # 연습 환경에서는 사용자 서식·작업이 목록에 없다.
    assert "내 작업" not in _listed(app.controllers["library"])
    assert "내 서식" not in _listed(app.controllers["tpl"])
    assert "물품 구매입찰 공고" in _listed(app.controllers["tpl"])
    _first_hwpx_round(app)
    tutorial.dispatch("select", {"scenario_id": "blank_values"})
    tutorial.dispatch("restart", {"scenario_id": "blank_values"})
    app.controllers["job"].set_output_folder(str(tmp_path / "연습 결과"))
    assert tutorial.dispatch("exit", {})["ok"]

    assert _user_state(app, home) == before, "튜토리얼이 사용자 환경을 바꿨습니다"
    assert locations.workspace_home() == home
    assert all(app.controllers[name] is controller for name, controller in user.items())
    job = app.controllers["job"]
    assert (job.data.path, job.data.selected_indices(), job.work.name) == remembered
    assert "내 작업" in _listed(app.controllers["library"])
    assert "튜토리얼" not in _listed(app.controllers["library"])
    assert "내 서식" in _listed(app.controllers["tpl"])
    assert "물품 구매입찰 공고" not in _listed(app.controllers["tpl"])
    assert job.remembered_output_directory() == str(tmp_path / "내 결과")


def test_switch_pushes_only_the_active_workspace(tmp_path, monkeypatch):
    """비활성 그래프의 푸시는 화면에 닿지 않고, 활성화 때 모든 채널이 새 스냅샷으로 간다."""
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    app = WebFrontend()
    pushed: list = []
    monkeypatch.setattr(app, "_window", object())
    monkeypatch.setattr("hwpxfiller.webapp.app.product_api.ProductApiClient.for_window",
                        lambda _window: type("Sink", (), {"push": lambda _s, screen, snap: pushed.append(screen)})())
    user_job = app.controllers["job"]
    app.dispatch("tutorial", "select", {"scenario_id": "field_trial"})
    assert {"job", "library", "tpl", "pool", "editor", "workbench", "authoring"} <= set(pushed)
    pushed.clear()
    user_job._push()
    assert pushed == [], "비활성 사용자 그래프의 푸시가 연습 화면에 닿았습니다"
    app.controllers["job"]._push()
    assert pushed == ["job"]


def _assert_boot_shaped(app, pushed: list, phase: str) -> None:
    """Every channel pushed on activation keeps the screen contract of a boot pull."""
    channels = {screen: snap for screen, snap in pushed if screen != "tutorial"}
    assert {"job", "library", "tpl", "pool", "editor", "workbench", "authoring"} <= set(channels), phase
    for screen, snap in channels.items():
        assert isinstance(snap, dict) and snap, f"{phase}: {screen} 채널에 빈 스냅샷이 갔습니다"
        # Same shape the web already accepts at boot (`initial`) — not a stale or empty cache.
        assert set(snap) == set(app.initial(screen)), f"{phase}: {screen} 스냅샷 형상이 부팅과 다릅니다"
    job = channels["job"]
    # frontend/src/screens/job_read.ts fullSnapshot(): the render throws without these two.
    assert isinstance(job["has_data"], bool) and isinstance(job["has_job"], bool), phase


def test_activation_pushes_boot_shaped_snapshots_on_enter_and_leave(tmp_path, monkeypatch):
    """#1126 회귀: 막 조립한 연습 그래프의 「문서 만들기」 캐시는 빈 ``{}`` 였고, 그것이 그대로 밀려
    웹이 「job snapshot: has_data/has_job 판정이 없습니다」로 렌더를 멈췄다."""
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    app = WebFrontend()
    for screen in ("job", "editor", "library"):  # what the web pulls at boot
        app.initial(screen)
    tutorial = app.controllers["tutorial"]
    pushed: list = []
    monkeypatch.setattr(app, "_window", object())
    monkeypatch.setattr("hwpxfiller.webapp.app.product_api.ProductApiClient.for_window",
                        lambda _window: type("Sink", (), {"push": lambda _s, screen, snap: pushed.append((screen, snap))})())
    guard = tutorial.dispatch("preflight", {"screen": "job", "action": "start", "scenario_id": "first_hwpx"})
    tutorial.dispatch("start", {"scenario_id": "first_hwpx", "transition_token": guard["transition_token"]})
    _assert_boot_shaped(app, pushed, "enter")
    pushed.clear()
    tutorial.dispatch("select", {"scenario_id": "option_apply"})  # lesson switch inside practice
    _assert_boot_shaped(app, pushed, "switch")
    pushed.clear()
    assert tutorial.dispatch("exit", {})["ok"]
    _assert_boot_shaped(app, pushed, "leave")


def test_crash_in_practice_boots_into_user_environment_and_resumes(tmp_path, monkeypatch):
    """연습 중 비정상 종료 — 다음 기동은 사용자 환경, 과정은 같은 연습 홈에서 이어진다."""
    from hwpxfiller.webapp.app import WebFrontend

    home = tmp_path / "home"
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))
    first = WebFrontend()
    first.dispatch("tutorial", "select", {"scenario_id": "blank_values"})
    tutorial = first.controllers["tutorial"]
    tutorial.dispatch("pause", {})
    lesson_home = tutorial._context()["home"]
    job_name = tutorial._context()["job_name"]
    tutorial.progress.record("blank_values")["checkpoint"] = 1
    tutorial._persist()
    assert locations.workspace_home() == Path(lesson_home)
    # 프로세스가 죽은 자리: 메모리 값(활성 작업 공간)은 사라지고 디스크만 남는다.
    monkeypatch.setattr(locations, "_active_workspace", None)

    second = WebFrontend()
    assert locations.workspace_home() == home
    restarted = second.controllers["tutorial"]
    assert not restarted.snapshot()["practice"]["active"]
    assert not restarted.snapshot()["active"]
    assert second._job_registry.names() == []
    restarted.dispatch("resume", {})
    assert restarted._context()["home"] == lesson_home
    assert second._job_registry.names() == [job_name]
    assert restarted.snapshot()["checkpoint"] == 1 and restarted.snapshot()["practice"]["active"]


def test_progress_lives_outside_user_settings_and_migrates_legacy_once(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))
    legacy = {"version": 1, "invite_seen": True, "selected": "first_hwpx", "records": {
        "first_hwpx": {"checkpoint": 3, "completed": True, "context": {
            "assets": {"물품 구매입찰 공고.hwpx": {"path": "C:/사용자/서식/옛 사본.hwpx"}}}}}}
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"tutorial": {"lessons": legacy}}), encoding="utf-8")
    workspace = TutorialWorkspace()
    migrated = workspace.load_progress()
    assert migrated["records"]["first_hwpx"] == {"checkpoint": 3, "completed": True}
    workspace.save_progress({"version": 1, "invite_seen": True, "selected": None, "records": {}})
    assert workspace.load_progress()["records"] == {}
    assert json.loads((home / "settings.json").read_text(encoding="utf-8")) == {"tutorial": {"lessons": legacy}}
    assert settings.load_legacy_tutorial_lessons() == legacy


def _capture_pushes(app, monkeypatch) -> list:
    pushed: list = []
    monkeypatch.setattr(app, "_window", object())
    monkeypatch.setattr("hwpxfiller.webapp.app.product_api.ProductApiClient.for_window",
                        lambda _window: type("Sink", (), {"push": lambda _s, screen, snap: pushed.append(screen)})())
    return pushed


def test_exit_returns_to_user_env_even_when_the_left_screen_cannot_reopen(tmp_path, monkeypatch):
    """Once the switch has left practice, a screen that cannot reopen never keeps the practice badge."""
    from hwpxfiller.webapp.app import WebFrontend

    home = tmp_path / "home"
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))
    app = WebFrontend()
    tutorial = app.controllers["tutorial"]
    saved = _user_environment(app, tmp_path)
    app.controllers["editor"].load_job(saved.name)
    guard = tutorial.dispatch("preflight", {"screen": "editor", "action": "select", "scenario_id": "first_hwpx"})
    app.controllers["editor"].dispatch("new_session", {})  # the web leaves the editor
    tutorial.dispatch("select", {"scenario_id": "first_hwpx", "transition_token": guard["transition_token"]})
    assert tutorial.snapshot()["practice"]["active"]
    for job_file in (home / "jobs").glob("*.json"):  # the captured job disappears meanwhile
        job_file.unlink()
    before = _user_state(app, home)

    result = tutorial.dispatch("exit", {})
    assert result == {"ok": True, "screen": "library", "notice": "돌아갈 화면을 확인할 수 없습니다."}
    assert not tutorial.snapshot()["practice"]["active"]
    assert locations.workspace_home() == locations.home_dir() == home
    assert app.controllers is app._workspaces.user.controllers
    assert _user_state(app, home) == before


def test_failed_practice_build_keeps_the_active_workspace_and_drops_its_pushes(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    home = tmp_path / "home"
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))
    app = WebFrontend()
    tutorial = app.controllers["tutorial"]
    user = dict(app.controllers)
    pushed = _capture_pushes(app, monkeypatch)

    def broken_build(_home, push, _token):
        push("job", {"from": "half-built graph"})
        raise OSError("graph build failed")

    monkeypatch.setattr(app._workspaces, "_build", broken_build)
    tutorial.snapshot()  # materialize every lesson record before comparing
    before = copy.deepcopy(tutorial.progress.progress())
    with pytest.raises(OSError, match="graph build failed"):
        tutorial.dispatch("select", {"scenario_id": "first_hwpx"})
    assert "job" not in pushed, "조립 중인 그래프의 푸시가 화면에 닿았습니다"
    assert locations.workspace_home() == home
    assert app._workspaces.active is app._workspaces.user
    assert all(app.controllers[name] is controller for name, controller in user.items())
    assert not tutorial.snapshot()["practice"]["active"]
    assert tutorial.progress.progress() == before


def test_lesson_seeding_failure_leaves_progress_and_workspace_unchanged(tmp_path, monkeypatch):
    from hwpxfiller.webapp import onboarding_practice
    from hwpxfiller.webapp.app import WebFrontend

    home = tmp_path / "home"
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))
    app = WebFrontend()
    tutorial = app.controllers["tutorial"]
    user = dict(app.controllers)
    tutorial.snapshot()  # materialize every lesson record before comparing
    before = copy.deepcopy(tutorial.progress.progress())

    def broken_seed(*_args):
        raise ValueError("seed failed")

    monkeypatch.setattr(onboarding_practice, "seed_before_switch", broken_seed)
    with pytest.raises(ValueError, match="seed failed"):
        tutorial.dispatch("select", {"scenario_id": "blank_values"})
    assert tutorial.progress.progress() == before
    assert locations.workspace_home() == home
    assert all(app.controllers[name] is controller for name, controller in user.items())
    assert not tutorial.snapshot()["practice"]["active"]
    assert app._workspaces.practice is None



def test_practice_entry_validation_rejects_unknown_moved_missing_and_modified(tmp_path):
    workspace = TutorialWorkspace(tmp_path / "tutorial")
    seeded = workspace.seed("first_hwpx")
    home = seeded["home"]
    entry = seeded["assets"]["공고목록.xlsx"]
    assert workspace.validate(entry, home) == (True, "")
    assert workspace.validate({**entry, "name": "남의 파일.xlsx"}, home)[1] == "연습 파일 경로를 확인할 수 없습니다."
    elsewhere = tmp_path / "공고목록.xlsx"
    elsewhere.write_bytes(Path(entry["path"]).read_bytes())
    assert workspace.validate({**entry, "path": str(elsewhere)}, home)[1] == "연습 파일이 다른 위치를 가리킵니다."
    Path(entry["path"]).write_bytes(b"changed")
    assert workspace.validate(entry, home)[1] == "연습 파일이 수정됐습니다. 현재 파일을 보존합니다."
    Path(entry["path"]).unlink()
    assert workspace.validate(entry, home)[1] == "연습 파일이 없거나 이동했습니다."
    assert workspace.validate({"name": "공고목록.xlsx"}, home)[1] == "연습 파일 상태를 확인할 수 없습니다."


def test_sweep_without_a_lesson_folder_is_a_no_op_and_keeps_the_current_home(tmp_path):
    workspace = TutorialWorkspace(tmp_path / "tutorial")
    workspace.sweep("first_hwpx", tmp_path / "없음")  # 그 과정을 한 번도 시작하지 않았다
    assert not (tmp_path / "tutorial").exists()
    first = workspace.seed("first_hwpx")["home"]
    second = workspace.seed("first_hwpx")["home"]
    workspace.sweep("first_hwpx", second)
    assert not Path(first).exists() and Path(second).is_dir()
