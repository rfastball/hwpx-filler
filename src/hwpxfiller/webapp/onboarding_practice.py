"""Practice workspace steps of the onboarding controller (#1126).

Free functions over :class:`~hwpxfiller.webapp.onboarding.OnboardingController`, the same shape
as :mod:`.onboarding_match_results`: seeding a lesson home, checking its files, and returning
the user to the screen the web left. The controller keeps ownership of state and persistence.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..domain.job import JOB_MAPPING_AUTHORITY, Job
from ..domain.mapping import FieldMapping, MappingProfile
from ..external.job_store import JobRegistry
from ..external.tutorial_practice import ORIGINALS, fingerprint
from ..external.tutorial_workspace import DATA_NAME
from ..viewmodel.tutorial_lessons import BY_ID

__all__ = ["NO_RETURN_SCREEN", "capture_return", "practice_resources", "restore_screen", "start_fresh"]

NO_RETURN_SCREEN = "돌아갈 화면을 확인할 수 없습니다."

from ..external.tutorial_workspace import MODIFIED_REASON as _MODIFIED

_READY = "연습 파일 4건이 준비됐습니다."


def practice_resources(tutorial: Any) -> tuple[bool, str]:
    """Are the current lesson's practice files the ones it seeded (or recorded saves of them)?"""
    if not tutorial.progress.selected:
        return False, "과정을 고르세요."
    ctx = tutorial._context()
    entries, home = ctx.get("assets"), ctx.get("home")
    if not isinstance(home, str) or not isinstance(entries, dict) or set(entries) != set(ORIGINALS):
        return False, "연습 파일이 준비되지 않았습니다. 예제로 시작하세요."
    saved = ctx.get("saved_fingerprints", {})
    for entry in entries.values():
        ok, reason = _entry_ready(tutorial.workspace, entry, home, saved)
        if not ok:
            return False, reason
    return _derived_ready(tutorial.workspace, ctx.get("derived_entry"), home)


def _entry_ready(workspace: Any, entry: dict, home: str, saved: dict) -> tuple[bool, str]:
    ok, reason = workspace.validate(entry, home)
    if ok or reason != _MODIFIED:
        return ok, reason
    # Saved authoring edits are allowed only if their exact new digest was recorded.
    path = Path(entry.get("path", ""))
    expected = saved.get(str(path))
    if expected and path.is_file() and not path.is_symlink() and fingerprint(path) == expected:
        return True, ""
    return False, reason


def _derived_ready(workspace: Any, derived_entry: Any, home: str) -> tuple[bool, str]:
    if derived_entry is None:
        return True, _READY
    if not isinstance(derived_entry, dict):
        return False, "다른 연습 데이터 기록을 확인할 수 없습니다."
    valid, reason = workspace.validate(derived_entry, home)
    return (True, _READY) if valid else (False, reason)


def start_fresh(tutorial: Any, lesson_id: str) -> None:
    """Seed a new lesson home with this lesson's preconditions and switch to it."""
    tutorial.progress.restart(lesson_id)
    derived = {"replace_data": "replacement", "blank_values": "blank"}.get(lesson_id, "")
    seeded = tutorial.workspace.seed(lesson_id, derived=derived)
    ctx = tutorial._context()
    ctx.clear()
    ctx.update(home=seeded["home"], batch=seeded["batch"], assets=seeded["assets"])
    if seeded["derived_entry"] is not None:
        ctx.update(derived_entry=seeded["derived_entry"],
                   derived_data_path=seeded["derived_entry"]["path"],
                   derived_sheet="계약" if derived == "blank" else "공고")
    if lesson_id in {"repeat_hwpx", "replace_data", "option_apply", "blank_values"}:
        _seed_job(tutorial, lesson_id, Path(seeded["home"]))
    tutorial.switch.enter(Path(seeded["home"]))
    if lesson_id == "option_apply":
        # Establish the pre-edit template basis through the normal select_job seam.
        job_controller = tutorial._job()
        job_controller.work.prepare_for_seat(job_controller.work.load(ctx["job_name"]))
        tutorial.switch.refresh()
    tutorial.workspace.sweep(lesson_id, seeded["home"])


def _seed_job(tutorial: Any, lesson_id: str, home: Path) -> None:
    """Explicit course prerequisite saved in the lesson home; never awards prior evidence."""
    ctx = tutorial._context()
    is_txt = lesson_id in {"option_apply", "blank_values"}
    template_path = tutorial._asset("낙찰자 선정 및 계약체결 안내.txt" if is_txt else "물품 구매입찰 공고.hwpx")
    data_path = ctx.get("derived_data_path") if lesson_id == "blank_values" else tutorial._asset(DATA_NAME)
    if not template_path or not data_path:
        raise ValueError("연습 파일을 먼저 준비하세요.")
    name = f"튜토리얼 {BY_ID[lesson_id].title} {ctx['batch']}"
    job = Job(name=name, template_path=template_path,
              mapping=_lesson_mapping(_template_fields(template_path, is_txt), lesson_id),
              filename_pattern="구매입찰공고-{{입찰공고번호}}" if not is_txt else "",
              data_path=data_path, data_sheet="계약" if is_txt else "공고",
              binding_authority=JOB_MAPPING_AUTHORITY)
    JobRegistry(home / "jobs", template_root=lambda: home / "templates").save(job)
    ctx["job_name"] = name
    ctx["seeded"] = True
    ctx["seed_notice"] = f"이 과정용 연습 작업 '{name}'을 준비했습니다. 다른 과정의 완료 기록은 바꾸지 않습니다."


def _template_fields(template_path: str, is_txt: bool) -> list[str]:
    if is_txt:
        content = Path(template_path).read_text(encoding="utf-8")
        return list(dict.fromkeys(re.findall(r"\{\{([^{}]+)\}\}", content)))
    from ..domain.schema import extract_schema
    from ..external.hwpx_package_io import read_hwpx_package

    return [field.name for field in extract_schema(read_hwpx_package(template_path)).fields]


def _lesson_mapping(fields: list[str], lesson_id: str) -> MappingProfile:
    source_overrides = {"낙찰자결정방법": "낙찰방법", "담당자 전화번호": "담당자전화",
                        "대표계약업체": "계약상대자"}
    mapping = MappingProfile(mappings=[FieldMapping(field, source_overrides.get(field, field))
                                       for field in fields])
    if lesson_id == "blank_values":
        mapping.mappings = [FieldMapping("단위", type="const") if item.template_field == "단위" else item
                            for item in mapping.mappings]
    return mapping


def capture_return(tutorial: Any, screen: str) -> dict:
    """Only the screen the web is about to leave; the user's workspace stays in memory."""
    return {"screen": screen,
            "editor_job": tutorial._editor().edit.base.name if tutorial._editor().edit.base else "",
            "authoring_id": tutorial.controllers["authoring"].active_id,
            "workbench_row": (tutorial._workbench().snapshot().get("card") or {}).get("source_row")}


def restore_screen(tutorial: Any, original: dict) -> tuple[str, str]:
    """Reopen the screen the web left; data, rows and job selection were never touched.

    Called after the switch is already back in the user's workspace: a screen that cannot
    reopen (e.g. its job was deleted meanwhile) lands on the library with that said, never
    on a failed exit that would keep the practice badge over the user's real data.
    """
    try:
        return _reopen_screen(tutorial, original)
    except (ValueError, OSError, KeyError):
        return "library", NO_RETURN_SCREEN


def _reopen_screen(tutorial: Any, original: dict) -> tuple[str, str]:
    screen = original["screen"]
    if screen == "editor" and original["editor_job"]:
        tutorial._editor().load_job(original["editor_job"])
    elif screen == "editor":
        screen = "job" if tutorial._job().work.name else "library"
    elif screen == "authoring" and original["authoring_id"]:
        tutorial.controllers["authoring"].dispatch("activate", {"session_id": original["authoring_id"]})
    elif screen == "workbench":
        return _reopen_workbench(tutorial, original["workbench_row"])
    return screen, ""


def _reopen_workbench(tutorial: Any, row) -> tuple[str, str]:
    opened = tutorial._job().dispatch("open_workbench", {})
    if opened.get("ok") is not True:
        return "job", opened.get("error") or ""
    card = tutorial._workbench().snapshot().get("card") or {}
    index = next((item["index"] for item in card.get("index_map", []) if item["row"] == row), None)
    if index is not None:
        tutorial._workbench().dispatch("set_current", {"index": index})
    return "workbench", ""
