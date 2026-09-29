"""legacy·managed 가 같은 작업에서 **같은 문서**를 낸다 — 값 표시형 동등성 (#1081 PR0b).

legacy 생성은 Mapping 의 ``type``·``fmt`` 로 값을 서식한다(``24750000`` → ``24,750,000원``).
field-binding/v2 는 그 ``type`` 을 버려서 managed 경로가 같은 작업에서 서식 없는 값을 냈다.
v3 는 표시형 kind 를 판본에 싣고 legacy 와 같은 해석기로 렌더한다 — 그 사실을 여기서 실제
제품 조립(:class:`WebFrontend`)과 동봉 예제로 고정한다: 한 작업을 legacy 로 한 번, managed 로
한 번 만들고 두 문서의 ``Contents/section0.xml`` 이 byte 동일한지 본다.

slot 없는 예제는 오늘 legacy 로 간다. managed 갈래 술어만 갈아 끼워(라우팅은 PR2 몫) 같은
Work·같은 판본·같은 데이터가 두 경로를 지나게 한다.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxfiller.host.locations import home_dir

WORK = "동등성"


@pytest.fixture
def app(tmp_path):
    # conftest 가 ``HWPXFILLER_HOME`` 을 테스트별 임시 폴더로 못박는다 — 실 홈을 건드리지 않는다.
    from hwpxfiller.webapp.app import WebFrontend

    frontend = WebFrontend()
    assert frontend.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    return frontend


def _asset(name: str) -> Path:
    return next(home_dir().rglob(name))


def _save_work(app, template: str, data: str) -> None:
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    app.dispatch("editor", "use_library_template", {"path": str(_asset(template))})
    editor.load_data_path(str(_asset(data)))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_name", {"name": WORK})
    assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": WORK}


def _override_formats(app, overrides: dict[str, tuple[str, str]]) -> None:
    """편집기 저장과 같은 사건으로 표시형을 바꾼다 — Mapping 을 고치고 저장 hook 을 부른다."""
    if not overrides:
        return
    job_ctrl = app.controllers["job"]

    def change(job) -> None:
        for item in job.mapping.mappings:
            if item.template_field in overrides:
                item.type, item.fmt = overrides[item.template_field]

    job_ctrl.registry.mutate(WORK, change)
    app.dispatch("job", "select_job", {"name": WORK})
    assert job_ctrl.on_editor_mapping_saved(WORK)["binding_commit_ok"] is True


def _sections(out: Path) -> dict[str, bytes]:
    docs = sorted(out.glob("*.hwpx"))
    assert docs, f"{out} 에 문서가 없다"
    result: dict[str, bytes] = {}
    for doc in docs:
        with zipfile.ZipFile(doc) as package:
            result[doc.name] = package.read("Contents/section0.xml")
    return result


@pytest.mark.parametrize(
    ("template", "data", "overrides", "expected_texts"),
    [
        # 편집기 제안 그대로 — 계약금액은 amount 기본(「원」 붙임).
        ("계약체결안내.hwpx", "계약목록.csv", {}, ["24,750,000원"]),
        # 표시형 코드를 고른 작업 — amount 코드·date 한글·text 마스크. 빈 칸(납품조건)은 표식.
        (
            "계약체결안내.hwpx",
            "계약목록_2.csv",
            {
                "계약금액": ("amount", "{:,}"),
                "납품조건": ("date", "kor"),
                "공고번호": ("text", "biz"),
            },
            ["41,200,000"],
        ),
    ],
)
def test_legacy_and_managed_write_identical_section_xml(
    app, tmp_path, template, data, overrides, expected_texts
):
    _save_work(app, template, data)
    _override_formats(app, overrides)
    job = app.controllers["job"]
    app.dispatch("job", "select_job", {"name": WORK})
    app.dispatch("job", "set_all", {})
    assert job.snapshot()["managed_hwpx"] is False, "전제: slot 없는 예제는 legacy 갈래"

    legacy_out = tmp_path / "legacy"
    pick_output_folder(job, legacy_out)
    legacy = app.generate("job")
    assert legacy["ok"] is True and legacy["status"] == "completed", legacy

    # 같은 Work 를 managed 갈래로 보낸다 — 판정 술어만 바꾸고(라우팅은 PR2) 나머지는 실제 조립.
    job.execution.is_managed_hwpx = lambda _ref, j: bool(j.media == "hwpx" and j.authority_id)
    managed_out = tmp_path / "managed"
    pick_output_folder(job, managed_out)
    app.dispatch("job", "resolve_execution", {})
    managed = app.generate("job")
    assert managed["ok"] is True and managed["status"] == "completed", managed
    assert "delivered" in managed, "전제: managed 파이프라인이 문서를 앉혔다"

    legacy_sections = _sections(legacy_out)
    managed_sections = _sections(managed_out)
    assert list(managed_sections) == list(legacy_sections), "파일 이름이 갈렸다"
    for name, body in legacy_sections.items():
        assert managed_sections[name] == body, f"{name} 의 section0.xml 이 legacy 와 다르다"
    joined = b"".join(managed_sections.values()).decode("utf-8")
    for text in expected_texts:
        assert text in joined, f"표시형 결과 {text!r} 가 문서에 없다"
