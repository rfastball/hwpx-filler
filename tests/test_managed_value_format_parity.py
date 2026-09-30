"""managed 가 legacy 와 **같은 문서**를 낸다 — 값 표시형 동등성의 golden 고정 (#1081 PR0b·PR2·PR3).

legacy 생성은 Mapping 의 ``type``·``fmt`` 로 값을 서식했다(``24750000`` → ``24,750,000원``).
field-binding/v3 는 표시형 kind 를 판본에 싣고 legacy 와 같은 해석기로 렌더한다. PR2 까지는
같은 작업을 legacy·managed 로 한 번씩 만들어 ``Contents/section0.xml`` 이 byte 동일한지 봤다.

PR3 에서 legacy 생성기가 삭제되며 그 비교의 한쪽이 사라졌다. 그래서 **삭제 직전 legacy 가 쓴
section0.xml bytes** 를 ``tests/fixtures/slotless_section0_golden/<사례>/<순번>.section0.xml``
로 박제하고(slot 없는 동봉 예제 3 사례), managed 제품 경로(:class:`WebFrontend` + 동봉 예제,
술어·배선 교체 0)가 그 bytes 를 그대로 내는지 본다 — 동등성은 여전히 고정된다.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxfiller.host.locations import home_dir

WORK = "동등성"
GOLDEN = Path(__file__).parent / "fixtures" / "slotless_section0_golden"


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
    ("case", "template", "data", "overrides", "expected_texts"),
    [
        # 편집기 제안 그대로 — 계약금액은 amount 기본(「원」 붙임).
        ("contract-default", "계약체결안내.hwpx", "계약목록.csv", {}, ["24,750,000원"]),
        # 표시형 코드를 고른 작업 — amount 코드·date 한글·text 마스크. 빈 칸(납품조건)은 표식.
        (
            "contract-formats",
            "계약체결안내.hwpx",
            "계약목록_2.csv",
            {
                "계약금액": ("amount", "{:,}"),
                "납품조건": ("date", "kor"),
                "공고번호": ("text", "biz"),
            },
            ["41,200,000"],
        ),
        # 다른 slot 없는 동봉 예제 — 편집기 제안 그대로(제안이 못 이은 칸은 표식).
        ("purchase-default", "구매추진안내.hwpx", "계약목록.csv", {}, []),
    ],
)
def test_managed_writes_the_section_xml_legacy_wrote(
    app, tmp_path, case, template, data, overrides, expected_texts
):
    _save_work(app, template, data)
    _override_formats(app, overrides)
    job = app.controllers["job"]
    app.dispatch("job", "select_job", {"name": WORK})
    app.dispatch("job", "set_all", {})
    snapshot = job.refresh_panel()
    assert snapshot["managed_hwpx"] is True, "slot 없는 예제도 managed 하나로 간다(#1081 PR2)"
    assert not snapshot["slot_configuration"]["current_view"]["projection"]["slots"], (
        "전제: slot 없는 예제"
    )

    managed_out = tmp_path / "managed"
    pick_output_folder(job, managed_out)
    managed = app.generate("job")
    assert managed["ok"] is True and managed["status"] == "completed", managed

    managed_sections = list(_sections(managed_out).values())  # 파일 이름순 = 순번순
    golden = [path.read_bytes() for path in sorted((GOLDEN / case).glob("*.section0.xml"))]
    assert golden, f"golden 이 없다: {GOLDEN / case}"
    assert len(managed_sections) == len(golden), "문서 수가 legacy 와 다르다"
    for ordinal, (body, expected) in enumerate(zip(managed_sections, golden, strict=True), 1):
        assert body == expected, f"{case} {ordinal:03d} 의 section0.xml 이 legacy golden 과 다르다"
    joined = b"".join(managed_sections).decode("utf-8")
    for text in expected_texts:
        assert text in joined, f"표시형 결과 {text!r} 가 문서에 없다"


def test_managed_writes_the_sliced_value_the_editor_previews(app, tmp_path):
    """가공(field-binding/v4)이 걸린 작업 — 문서·파일 이름이 편집기 미리보기와 같은 글자다.

    legacy 생성기는 사라졌으므로 비교의 다른 쪽은 편집기 미리보기가 쓰는 ``FieldMapping.value_for``
    다(연결 표의 「미리보기」 칸이 곧 이것). 가공은 편집기 동사(`set_slice`)로 걸고 저장한다 —
    제품 동선 그대로. 파일 이름 토큰도 같은 가공을 거친다.
    """
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    app.dispatch("editor", "use_library_template", {"path": str(_asset("계약체결안내.hwpx"))})
    editor.load_data_path(str(_asset("계약목록.csv")))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    app.dispatch("editor", "confirm_suggested", {})
    rows = {row["template_field"]: row for row in editor.snapshot()["rows"]}
    slices = {
        "공고번호": {"mode": "split", "delimiter": "-", "index": 1},
        "계약금액": {"mode": "chars", "start": 1, "length": 3},  # 금액 기본 표시형과 함께
    }
    for name, spec in slices.items():
        assert rows[name]["slice_enabled"] is True
        app.dispatch("editor", "set_slice", {"index": rows[name]["index"], "slice": spec})
        app.dispatch("editor", "set_confirmed", {"index": rows[name]["index"], "confirmed": True})
    after = {row["template_field"]: row for row in editor.snapshot()["rows"]}
    assert after["공고번호"]["preview"] == "20260812"
    assert after["공고번호"]["slice_label"] == "구분자 '-' 1번째"
    app.dispatch("editor", "set_pattern", {"pattern": "{{공고번호}}-{{seq:001}}"})
    app.dispatch("editor", "set_name", {"name": WORK})
    assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": WORK}

    job = app.controllers["job"]
    saved = job.registry.load(WORK)
    by_field = {m.template_field: m for m in saved.mapping.mappings}
    assert by_field["공고번호"].slice is not None and by_field["계약금액"].slice is not None
    app.dispatch("job", "select_job", {"name": WORK})
    app.dispatch("job", "set_all", {})
    out = tmp_path / "sliced"
    pick_output_folder(job, out)
    result = app.generate("job")
    assert result["ok"] is True and result["status"] == "completed", result

    sections = _sections(out)
    records = job.data.records
    assert len(sections) == len(records)
    # 가공 전이면 ``20260812-001-001.hwpx`` 다 — 토큰 자리에 가공된 ``20260812`` 만 선다.
    assert all(re.fullmatch(r"20260812-\d{3}\.hwpx", name) for name in sections), sorted(sections)
    for record in records:
        # 문서와 레코드를 가공되지 않은 칸(수요기관)으로 잇는다 — 출력 순서에 기대지 않는다.
        (text,) = [
            body.decode("utf-8") for body in sections.values()
            if f">{record['수요기관']}<" in body.decode("utf-8")
        ]
        for field in slices:
            expected = by_field[field].value_for(record)
            assert f">{expected}<" in text, f"{field} 가 미리보기 값 {expected!r} 와 다르다"
        assert f">{record['공고번호']}<" not in text, "가공 전 칸 전체가 문서에 남았다"
