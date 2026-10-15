"""작업 꾸러미 내보내기·불러오기(#1188 WP-03·WP-04) — 제품 조립(:class:`WebFrontend`)으로 두 홈을 오간다.

보내는 홈 A 에서 예제 템플릿 하나를 함께 쓰는 작업 둘을 만들어 내보내고, 빈 홈 B 에서 불러와
같은 열의 데이터를 연결하면 계약을 통과한 행이 전부 자동확정되어 추가 확정 없이 저장·생성까지
간다. 같은 bytes 의 템플릿 재사용·이름 충돌·계획 지문 대조·변조 거절·중간 실패 되돌리기·꾸러미
내용(값·경로·출처 메타 없음)도 같은 조립으로 고정한다.
"""
from __future__ import annotations

import csv
import json
import shutil
import uuid
import zipfile
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.preset_store import PresetRegistry
from hwpxfiller.external.work_package_io import read_work_package
from hwpxfiller.host.locations import default_jobs_dir, default_preset_dir, home_dir
from hwpxfiller.webapp.work_package_panel import (
    DATA_NOTICE, EXPORT_WITHOUT_CONTRACT, NOTHING_TO_EXPORT, PACKAGE_FILTERS,
    pick_package_path, skipped_line,
)

CONTRACT_LABEL = "자동확정 · 꾸러미 조건 일치"
SHARED_TEMPLATE = "계약체결안내.hwpx"
DATA = "계약목록.csv"


def _frontend():
    from hwpxfiller.webapp.app import WebFrontend

    return WebFrontend()


def _use_home(monkeypatch, path: Path) -> None:
    monkeypatch.setenv("HWPXFILLER_HOME", str(path))


def _asset(name: str) -> Path:
    return next(home_dir().rglob(name))


def _save_new_work(app, name: str, template: str, data: Path) -> None:
    """편집기 새 작업 한 바퀴 — 자동 제안을 확정하고 저장한다(표면이 밟는 동선 그대로)."""
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    app.dispatch("editor", "use_library_template", {"path": str(_asset(template))})
    editor.load_data_path(str(data))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_name", {"name": name})
    assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": name}


def _sender_home(monkeypatch, tmp_path: Path, *names: str):
    """홈 A — 예제를 설치하고 같은 템플릿을 쓰는 작업들을 만든 뒤 착석시켜 적용 판본을 세운다."""
    _use_home(monkeypatch, tmp_path / "home-a")
    app = _frontend()
    assert app.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    data = tmp_path / "a-data" / DATA
    data.parent.mkdir()
    shutil.copy2(_asset(DATA), data)
    for name in names:
        _save_new_work(app, name, SHARED_TEMPLATE, data)
        app.dispatch("job", "select_job", {"name": name})
        assert JobRegistry(default_jobs_dir()).load(name).authority_id, "전제: 착석이 적용 판본을 세운다"
    return app, data


def _export(app, names, path: Path, **extra) -> dict:
    return app.dispatch(
        "library", "export_work_package", {"names": list(names), "path": str(path), **extra}
    )


def _inspect(app, path: Path) -> dict:
    return app.dispatch("library", "inspect_work_package", {"path": str(path)})


def _import(app, path: Path, basis: str) -> dict:
    return app.dispatch("library", "import_work_package", {"path": str(path), "basis": basis})


def _rows(editor) -> "dict[str, dict]":
    return {row["template_field"]: row for row in editor.snapshot()["rows"]}


def _templates_root() -> Path:
    return home_dir() / "templates"


def _home_state() -> tuple:
    """설치가 남기는 흔적 전부 — 작업 파일·서식 폴더 파일·프리셋 파일."""
    def listing(root: Path, pattern: str) -> tuple:
        return tuple(sorted(p.name for p in root.rglob(pattern))) if root.exists() else ()

    return (
        listing(default_jobs_dir(), "*.job.json"),
        listing(_templates_root(), "*.*"),
        listing(default_preset_dir(), "*.preset.json"),
    )


@pytest.fixture
def package(monkeypatch, tmp_path):
    """홈 A 가 내보낸 꾸러미(작업 둘 · 템플릿 하나)와 A 의 데이터 파일."""
    app, data = _sender_home(monkeypatch, tmp_path, "계약A", "계약B")
    path = tmp_path / "보낸작업.narumi"
    result = _export(app, ["계약A", "계약B"], path)
    assert result == {
        "ok": True, "path": str(path), "jobs": 2, "templates": 1, "skipped": [],
        "without_contract": [],
    }
    return path, data


def test_exported_jobs_land_in_an_empty_home_and_generate_with_auto_confirmed_bindings(
    package, monkeypatch, tmp_path,
):
    """수용 기준 1 — 빈 홈 B 에서 불러와 같은 열의 데이터를 연결하면 추가 확정 없이 생성까지 간다."""
    path, sender_data = package
    _use_home(monkeypatch, tmp_path / "home-b")
    app = _frontend()

    inspected = _inspect(app, path)
    assert inspected["ok"] is True
    view = inspected["view"]
    assert view["title"] == "작업 2개를 불러옵니다"
    assert [job["final_name"] for job in view["jobs"]] == ["계약A", "계약B"]
    assert all(job["note"] == "" and job["has_contract"] for job in view["jobs"])
    assert [(job["template"], job["template_label"]) for job in view["jobs"]] == [
        (SHARED_TEMPLATE, "새로 추가"), (SHARED_TEMPLATE, "새로 추가"),
    ], "작업 줄마다 그 작업이 쓰는 템플릿의 처리 표지가 실린다(웹은 짝을 맞추지 않는다)"
    assert [(t["display_name"], t["action"], t["label"]) for t in view["templates"]] == [
        (SHARED_TEMPLATE, "new", "새로 추가"),
    ]
    assert view["data_notice"] == DATA_NOTICE

    imported = _import(app, path, inspected["basis"])
    assert imported == {
        "ok": True, "imported": ["계약A", "계약B"],
        "message": "데이터 연결이 필요합니다.",
    }
    registry = JobRegistry(default_jobs_dir())
    jobs = [registry.load(name) for name in ("계약A", "계약B")]
    assert jobs[0].template_path == jobs[1].template_path == str(_templates_root() / SHARED_TEMPLATE)
    for job in jobs:
        assert (job.data_path, job.authority_id, job.reviewed_rules) == ("", "", {})
        assert (job.template_revision, job.binding_revision, job.previous_rules) == (1, 1, {})
        assert job.data_contract is not None
    rows = {
        row["name"]: row
        for section in app.controllers["library"].snapshot()["sections"]
        for row in section["rows"]
    }
    assert rows["계약A"]["data_bound"] is False, "불러온 작업은 「데이터 연결 필요」로 착지한다"

    receiver_data = tmp_path / "b-data" / "받은데이터.csv"
    receiver_data.parent.mkdir()
    shutil.copy2(sender_data, receiver_data)
    editor = app.controllers["editor"]
    for name in ("계약A", "계약B"):
        editor.load_job(name)
        editor.load_data_path(str(receiver_data))
        rows = _rows(editor)
        assert rows and all(row["confirmed"] for row in rows.values())
        assert {row["state_label"] for row in rows.values()} == {CONTRACT_LABEL}
        assert editor.snapshot()["is_complete"] is True
        assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": name}

    for index, name in enumerate(("계약A", "계약B")):
        app.dispatch("job", "select_job", {"name": name})
        app.dispatch("job", "set_all", {})
        pick_output_folder(app.controllers["job"], tmp_path / f"out-{index}")
        app.dispatch("job", "resolve_execution", {})
        result = app.generate("job")
        assert result["ok"] is True and result["succeeded"] == 3 and result["failed"] == 0
        # 생성 자격은 꾸러미가 아니라 받는 쪽의 초기 등록(capture·qualification)이 세웠다.
        landed = JobRegistry(default_jobs_dir()).load(name)
        assert landed.authority_id and "template_authority" in landed.template_path


def test_package_carries_no_data_values_paths_provenance_or_local_metadata(package):
    """수용 기준 4 — 꾸러미 안에 데이터 값·경로·출처 메타·권위/검토 메타가 없다."""
    path, data = package
    with zipfile.ZipFile(path) as archive:
        names = sorted(archive.namelist())
        text = archive.read("manifest.json").decode("utf-8")
    assert names[0] == "manifest.json" and len(names) == 2
    manifest = json.loads(text)
    assert set(manifest) == {"schema_version", "created_at", "templates", "jobs"}
    for job in manifest["jobs"]:
        assert set(job) == {
            "name", "media", "template_digest", "mapping", "filename_pattern",
            "selection_presets", "data_contract",
        }
        assert job["mapping"]["provenance"] == {}
        assert all(preset["provenance"] == {} for preset in job["selection_presets"])
    for forbidden in ("data_path", "authority_id", "reviewed_rules", "previous_rules",
                      "last_run_at", "favorited_at", "template_revision", str(data.parent),
                      data.name, str(home_dir())):
        assert forbidden not in text
    with data.open(encoding="utf-8-sig", newline="") as handle:
        values = {cell for row in csv.DictReader(handle) for cell in row.values()}
    leaked = {value for value in values if len(value) > 1 and not value.isdigit() and value in text}
    assert not leaked, f"데이터 값이 꾸러미에 새었다: {sorted(leaked)}"


def test_same_template_bytes_are_reused_and_name_collision_imports_as_numbered_copy(
    package, monkeypatch, tmp_path,
):
    """같은 bytes 의 템플릿은 그 파일을 쓰고(복사본 없음), 같은 이름의 작업은 `이름 (2)` 로 들어온다."""
    path, _data = package
    _use_home(monkeypatch, tmp_path / "home-c")
    app = _frontend()
    assert app.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    existing = _asset(SHARED_TEMPLATE)

    first = _inspect(app, path)
    assert first["view"]["templates"] == [{
        "display_name": SHARED_TEMPLATE, "action": "reuse", "label": "이미 있는 파일 사용",
        "target": str(existing),
    }]
    assert {job["template_label"] for job in first["view"]["jobs"]} == {"이미 있는 파일 사용"}
    before = sorted(p.name for p in _templates_root().rglob("*.hwpx"))
    assert _import(app, path, first["basis"])["ok"] is True
    assert sorted(p.name for p in _templates_root().rglob("*.hwpx")) == before
    assert JobRegistry(default_jobs_dir()).load("계약A").template_path == str(existing)

    second = _inspect(app, path)
    assert [(j["final_name"], j["note"]) for j in second["view"]["jobs"]] == [
        ("계약A (2)", "‘계약A (2)’ 이름으로 불러옵니다"),
        ("계약B (2)", "‘계약B (2)’ 이름으로 불러옵니다"),
    ]
    assert _import(app, path, second["basis"])["imported"] == ["계약A (2)", "계약B (2)"]
    assert JobRegistry(default_jobs_dir()).load("계약A").data_contract is not None


def test_stale_basis_is_refused_without_changes_and_returns_the_current_plan(
    package, monkeypatch, tmp_path,
):
    path, _data = package
    _use_home(monkeypatch, tmp_path / "home-d")
    app = _frontend()
    seen = _inspect(app, path)
    assert _import(app, path, _inspect(app, path)["basis"])["ok"] is True  # 그사이 같은 이름이 생겼다
    state = _home_state()

    refused = _import(app, path, seen["basis"])
    assert refused["ok"] is False and refused["stale"] is True
    assert refused["basis"] != seen["basis"]
    assert [job["final_name"] for job in refused["view"]["jobs"]] == ["계약A (2)", "계약B (2)"]
    assert _home_state() == state


def test_tampered_package_is_refused_and_installs_nothing(package, monkeypatch, tmp_path):
    path, _data = package
    tampered = tmp_path / "변조.narumi"
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            blob = source.read(info)
            if info.filename.startswith("templates/"):
                blob = blob[:-1] + bytes([blob[-1] ^ 0xFF])
            target.writestr(info, blob)
    _use_home(monkeypatch, tmp_path / "home-e")
    app = _frontend()
    state = _home_state()

    inspected = _inspect(app, tampered)
    assert inspected["ok"] is False
    assert inspected["error"].startswith("작업 꾸러미를 읽을 수 없습니다: ")
    assert "digest" in inspected["error"]
    refused = _import(app, tampered, "0" * 64)
    assert refused["ok"] is False and refused["error"].startswith("작업 꾸러미를 읽을 수 없습니다: ")
    assert _home_state() == state


def test_failure_mid_commit_rolls_back_everything_this_commit_created(
    package, monkeypatch, tmp_path,
):
    path, _data = package
    _use_home(monkeypatch, tmp_path / "home-f")
    app = _frontend()
    basis = _inspect(app, path)["basis"]
    state = _home_state()
    calls = {"n": 0}
    real_save = JobRegistry.save

    def failing_save(self, job, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("디스크가 가득 찼습니다")
        return real_save(self, job, **kwargs)

    monkeypatch.setattr(JobRegistry, "save", failing_save)
    result = _import(app, path, basis)
    assert result == {"ok": False, "error": "작업 꾸러미를 읽을 수 없습니다: 디스크가 가득 찼습니다"}
    assert calls["n"] == 2, "전제: 첫 작업과 템플릿은 실제로 만들어졌다"
    assert _home_state() == state


def test_export_without_readable_data_asks_first_then_exports_without_contract(
    monkeypatch, tmp_path,
):
    """데이터를 읽지 못한 작업은 확인을 먼저 돌려주고, 확인 뒤에만 계약 없이 쓴다."""
    app, data = _sender_home(monkeypatch, tmp_path, "계약A")
    data.unlink()
    path = tmp_path / "계약없음.narumi"

    asked = _export(app, ["계약A"], path)
    assert asked == {
        "ok": True, "needs_confirm": True,
        "confirm_text": EXPORT_WITHOUT_CONTRACT, "skipped": [], "without_contract": ["계약A"],
    }
    assert not path.exists()

    done = _export(app, ["계약A"], path, confirm=True)
    assert done["ok"] is True and done["without_contract"] == ["계약A"]
    (job,) = read_work_package(path).manifest.jobs
    assert job.data_contract is None


def test_export_failure_is_loud_and_writes_nothing(monkeypatch, tmp_path):
    app, _data = _sender_home(monkeypatch, tmp_path, "계약A")
    path = tmp_path / "없는작업.narumi"
    result = _export(app, ["없는 작업"], path)
    assert result["ok"] is False
    assert result["error"].startswith("작업 꾸러미를 만들 수 없습니다: ")
    assert not path.exists()


def test_selection_preset_travels_with_the_job_and_collides_like_jobs(monkeypatch, tmp_path):
    """구간 작업의 지금 선택은 작업 이름의 선택 프리셋으로 실리고, 이름이 겹치면 `이름 (2)` 다."""
    _use_home(monkeypatch, tmp_path / "home-a")
    app = _frontend()
    assert app.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    practice = _asset("공고서_연습.hwpx")
    assert app.dispatch("tpl", "compile", {"path": str(practice), "confirm": True})["mutated"]
    _save_new_work(app, "공고작업", "공고서_연습.hwpx", _asset(DATA))
    app.dispatch("job", "select_job", {"name": "공고작업"})
    view = app.dispatch("job", "open_slot_configuration", {})["current_view"]
    for slot in view["projection"]["slots"]:
        if not slot["effective_option_ids"]:
            view = app.dispatch("job", "select_slot_option", {
                "configuration_token": view["new_configuration_token"],
                "slot_id": slot["slot_id"], "option_id": slot["options"][0]["option_id"],
                "request_id": uuid.uuid4().hex,
            })["current_view"]
    path = tmp_path / "구간.narumi"
    assert _export(app, ["공고작업"], path)["ok"] is True
    (job,) = read_work_package(path).manifest.jobs
    (preset,) = job.selection_presets
    assert preset.name == "공고작업" and preset.provenance == ()

    _use_home(monkeypatch, tmp_path / "home-b")
    receiver = _frontend()
    for expected in ("공고작업", "공고작업 (2)"):
        plan = _inspect(receiver, path)
        assert plan["view"]["presets"][0]["final_name"] == expected
        assert _import(receiver, path, plan["basis"])["ok"] is True
    names = sorted(p.name for _key, p in PresetRegistry(default_preset_dir()).list_entries())
    assert names == ["공고작업", "공고작업 (2)"]


def test_package_file_picker_routes_through_the_host_dialog_seams(monkeypatch, tmp_path):
    """「작업 내보내기…」·「작업 불러오기…」의 선택 창 — 호스트 단일 입구를 지나 경로만 돌려준다."""
    from hwpxfiller.webapp import app as app_mod

    _use_home(monkeypatch, tmp_path / "home-pick")
    asked: list = []
    monkeypatch.setattr(app_mod, "_save_dialog", lambda *args: asked.append(("save", *args)) or "C:/out/a.narumi")
    monkeypatch.setattr(app_mod, "_file_dialog", lambda *args: asked.append(("open", *args)) or None)
    app = _frontend()

    assert app.pick_work_package_path("export") == "C:/out/a.narumi"
    assert app.pick_work_package_path("import") is None, "취소는 None 그대로다"
    assert asked == [
        ("save", "작업 꾸러미.narumi", PACKAGE_FILTERS, "narumi"),
        ("open", PACKAGE_FILTERS),
    ]
    assert PACKAGE_FILTERS == [("작업 꾸러미 (*.narumi)", "*.narumi")]


def test_package_file_picker_refuses_an_unknown_action():
    def never(*_args):
        raise AssertionError("선택 창을 열면 안 된다")

    with pytest.raises(ValueError, match="export·import"):
        pick_package_path("delete", open_file=never, save_file=never)


# ───────────────────────────────────── 모든 작업 내보내기(#1188 후속) ──

TXT_TEMPLATE = "계약안내_기안.txt"


def _save_draft_job(app, name: str, template: str, data: Path) -> None:
    """착석 없이 저장만 — 적용 이력이 없으니 내보내기는 연결된 템플릿 파일 bytes 를 읽는다."""
    _save_new_work(app, name, template, data)


def _break_template(name: str, tmp_path: Path) -> None:
    """작업이 가리키는 템플릿을 없는 파일로 돌린다(적용 이력 없는 작업이라 그 파일이 곧 원천)."""
    from dataclasses import replace

    registry = JobRegistry(default_jobs_dir())
    job = registry.load(name)
    registry.save(replace(job, template_path=str(tmp_path / "사라진" / Path(job.template_path).name)))


def test_export_all_carries_every_job_and_round_trips_with_shared_and_txt_templates(
    monkeypatch, tmp_path,
):
    """이름 없이 부르면 이 작업 공간의 모든 작업(HWPX·TXT)이 한 꾸러미로 가고, 빈 홈이 전부 받는다."""
    app, data = _sender_home(monkeypatch, tmp_path, "계약A", "계약B")
    _save_draft_job(app, "구매안내", "구매추진안내.hwpx", data)
    _save_draft_job(app, "기안A", TXT_TEMPLATE, data)
    _save_draft_job(app, "기안B", TXT_TEMPLATE, data)
    names = ["계약A", "계약B", "구매안내", "기안A", "기안B"]
    media = {job.name: job.media for job in JobRegistry(default_jobs_dir()).list_jobs()}
    assert sorted(media) == sorted(names) and media["기안A"] == media["기안B"] == "txt"
    app.dispatch("library", "refresh", {})
    assert app.controllers["library"].snapshot()["export_all_enabled"] is True

    path = tmp_path / "모든작업.narumi"
    result = app.dispatch("library", "export_work_package", {"path": str(path)})
    assert result == {
        "ok": True, "path": str(path), "jobs": 5, "templates": 3, "skipped": [],
        "without_contract": [],
    }
    manifest = read_work_package(path).manifest
    assert sorted(job.name for job in manifest.jobs) == sorted(names)
    assert sorted(t.media for t in manifest.templates) == ["hwpx", "hwpx", "txt"]

    _use_home(monkeypatch, tmp_path / "home-b")
    receiver = _frontend()
    receiver.dispatch("library", "refresh", {})
    assert receiver.controllers["library"].snapshot()["export_all_enabled"] is False
    inspected = _inspect(receiver, path)
    assert inspected["view"]["title"] == "작업 5개를 불러옵니다"
    assert sorted(job["final_name"] for job in inspected["view"]["jobs"]) == sorted(names)
    assert {job["template_label"] for job in inspected["view"]["jobs"]} == {"새로 추가"}
    assert len(inspected["view"]["templates"]) == 3
    imported = _import(receiver, path, inspected["basis"])
    assert imported["ok"] is True and sorted(imported["imported"]) == sorted(names)
    landed = {job.name: job for job in JobRegistry(default_jobs_dir()).list_jobs()}
    assert sorted(landed) == sorted(names)
    assert landed["기안A"].media == "txt" and landed["기안A"].template_path == landed["기안B"].template_path
    assert all(job.data_path == "" for job in landed.values())


def test_export_all_skips_jobs_whose_template_cannot_be_read_after_one_confirm(
    monkeypatch, tmp_path,
):
    """템플릿을 못 읽는 작업은 꾸러미를 깨지 않고 빠진다 — 쓰기 전에 한 번 묻고, 계약 없음 확인과 한 창이다."""
    app, data = _sender_home(monkeypatch, tmp_path, "계약A")
    _save_draft_job(app, "깨진작업", "구매추진안내.hwpx", data)
    _break_template("깨진작업", tmp_path)
    path = tmp_path / "빠짐.narumi"

    asked = app.dispatch("library", "export_work_package", {"path": str(path)})
    assert asked == {
        "ok": True, "needs_confirm": True,
        "confirm_text": skipped_line(["깨진작업"]),
        "skipped": ["깨진작업"], "without_contract": [],
    }
    assert skipped_line(["깨진작업"]) == "템플릿을 읽을 수 없는 작업은 빠집니다: 깨진작업"
    assert not path.exists()

    data.unlink()  # 데이터도 못 읽으면 두 사실이 한 확인 창에 함께 선다
    both = app.dispatch("library", "export_work_package", {"path": str(path)})
    assert both["confirm_text"] == (
        f"{skipped_line(['깨진작업'])}\n\n{EXPORT_WITHOUT_CONTRACT}"
    )
    assert not path.exists()

    done = app.dispatch("library", "export_work_package", {"path": str(path), "confirm": True})
    assert done["ok"] is True and done["skipped"] == ["깨진작업"] and done["jobs"] == 1
    assert [job.name for job in read_work_package(path).manifest.jobs] == ["계약A"]


def test_export_all_refuses_without_writing_when_nothing_can_be_carried(monkeypatch, tmp_path):
    """실을 작업이 하나도 없으면(빈 작업 공간·전부 템플릿을 못 읽음) 확인을 받아도 쓰지 않는다."""
    _use_home(monkeypatch, tmp_path / "home-empty")
    empty = _frontend()
    path = tmp_path / "빈.narumi"
    refused = empty.dispatch("library", "export_work_package", {"path": str(path), "confirm": True})
    assert refused == {
        "ok": False, "error": f"작업 꾸러미를 만들 수 없습니다: {NOTHING_TO_EXPORT}", "skipped": [],
    }

    app, data = _sender_home(monkeypatch, tmp_path, "계약A")
    _save_draft_job(app, "깨진작업", "구매추진안내.hwpx", data)
    _break_template("깨진작업", tmp_path)
    for name in ("계약A",):
        assert app.dispatch("library", "delete_job", {"name": name, "confirm": True})["ok"] is not False
    refused = app.dispatch("library", "export_work_package", {"path": str(path), "confirm": True})
    assert refused["ok"] is False and refused["skipped"] == ["깨진작업"]
    assert refused["error"] == (
        f"작업 꾸러미를 만들 수 없습니다: {NOTHING_TO_EXPORT}\n"
        f"{skipped_line(['깨진작업'])}"
    )
    assert not path.exists()
