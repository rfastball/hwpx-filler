"""테스트 공용 — 작업 꾸러미를 두 홈 사이에 오가게 하는 제품 조립 동선(#1188·#1193).

보내는 홈은 예제를 설치하고 같은 템플릿을 쓰는 작업을 편집기로 저장·착석해 적용 판본을 세운다.
받는 홈은 같은 :class:`~hwpxfiller.webapp.app.WebFrontend` 의 library 액션으로 확인·확정한다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.host.locations import default_jobs_dir, home_dir

SHARED_TEMPLATE = "계약체결안내.hwpx"
DATA = "계약목록.csv"


def frontend():
    from hwpxfiller.webapp.app import WebFrontend

    return WebFrontend()


def use_home(monkeypatch, path: Path) -> None:
    monkeypatch.setenv("HWPXFILLER_HOME", str(path))


def asset(name: str) -> Path:
    return next(home_dir().rglob(name))


def save_new_work(app, name: str, template: str, data: Path) -> None:
    """편집기 새 작업 한 바퀴 — 자동 제안을 확정하고 저장한다(표면이 밟는 동선 그대로)."""
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    app.dispatch("editor", "use_library_template", {"path": str(asset(template))})
    editor.load_data_path(str(data))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_name", {"name": name})
    assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": name}


def sender_home(monkeypatch, tmp_path: Path, *names: str):
    """홈 A — 예제를 설치하고 같은 템플릿을 쓰는 작업들을 만든 뒤 착석시켜 적용 판본을 세운다."""
    use_home(monkeypatch, tmp_path / "home-a")
    app = frontend()
    assert app.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    data = tmp_path / "a-data" / DATA
    data.parent.mkdir()
    shutil.copy2(asset(DATA), data)
    for name in names:
        save_new_work(app, name, SHARED_TEMPLATE, data)
        app.dispatch("job", "select_job", {"name": name})
        assert JobRegistry(default_jobs_dir()).load(name).authority_id, "전제: 착석이 적용 판본을 세운다"
    return app, data


def export(app, names, path: Path, **extra) -> dict:
    return app.dispatch(
        "library", "export_work_package", {"names": list(names), "path": str(path), **extra}
    )


def inspect(app, path: Path) -> dict:
    return app.dispatch("library", "inspect_work_package", {"path": str(path)})


def import_package(app, path: Path, basis: str) -> dict:
    return app.dispatch("library", "import_work_package", {"path": str(path), "basis": basis})
