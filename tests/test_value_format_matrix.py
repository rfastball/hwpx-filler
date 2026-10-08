"""표시형 전 프리셋 × 진입 경로 매트릭스 — 사람이 고른 표시형이 산출물 글자까지 간다.

「금액 · 원」·「날짜 · 표준」·「텍스트 · 원문」은 표시형 코드가 **빈 문자열**이다. 빈 코드는
「표시형 없음」이 아니라 「그 유형의 기본 표시」라는 결정이다(``24750000`` → ``24,750,000원``).
field-binding/v2 판본은 유형을 버리고 ``fmt or None`` 만 적어서 managed 산출이 ``24750000`` 이
됐다(편집기 미리보기는 ``24,750,000원``) — v3(#1081 PR0b)가 유형을 판본에 싣고, PR2·PR3 에서
GUI·CLI 생성이 모두 managed 로 모였다. 이 파일은 그 결손류가 되돌아오지 못하게 **모든 프리셋**을
사람이 실제로 지나는 입구마다 산출물까지 따라간다:

- 편집기 표시형 select(``set_display``) → 데이터 교체 이월 → 저장 → 다시 열기 → HWPX 생성
  (본문 글자와 파일 이름 토큰), 그리고 편집기 미리보기 == 산출물.
- TXT 검토·복사 작업대 — 저장된 매핑의 유형·표시형(연결 편집이 저장하는 그 값, #1148) →
  봉인된 물질화로 복사한 글자 == 카드가 보인 글자.
- CLI 프로파일(``type``·``fmt``) → managed 생성.

기대값은 표시형 해석기(``format_engine.render``) 하나에서 얻는다 — 경로마다 기대를 따로 적으면
그 사본이 해석기와 함께 틀려도 초록이다. 대신 비공허 조건을 둔다: 「원문」 외의 모든 프리셋은
원문과 **다른** 글자를 내야 하고, 빈 코드 프리셋 셋은 글자 그대로 못박는다.

「오늘 날짜」는 아직 연결 판본으로 옮기지 않는다(#950) — 표시형 select 의 왕복만 여기서 잰다.
"""
from __future__ import annotations

import csv
import re
import threading
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxfiller.cli import main as cli_main
from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.domain import format_engine
from hwpxfiller.domain.job import JOB_MAPPING_AUTHORITY, Job
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.mapping_store import save_mapping_profile
from hwpxfiller.external.seal_execution_plan_service import SealExecutionPlanService
from hwpxfiller.external.template_change import TemplateChangeCoordinator
from hwpxfiller.host.locations import home_dir
from hwpxfiller.viewmodel.mapping_state import RowState, display_options
from hwpxfiller.webapp.workspace_graph import _content_selection_reader, _txt_materialization_port
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.screen_workbench import TargetFontSetting, WorkbenchController
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct

#: 열에서 값을 받는 행이 고를 수 있는 (유형, 표시형 코드) 전건 — 표면과 같은 표에서 뽑는다.
PRESETS = [
    (kind, code)
    for kind in ("text", "date", "amount")
    for _label, code in format_engine.presets(kind)
]
_PRESET_IDS = [f"{kind}:{code or '(기본)'}" for kind, code in PRESETS]

#: 빈 코드 프리셋의 글자 — 해석기에 기대지 않고 못박는다(이 결손류의 표본).
EMPTY_CODE_GOLDEN = {
    ("amount", ""): ("24750000", "24,750,000원"),
    ("date", ""): ("2026/7/17 18:05", "2026. 7. 17."),
    ("text", ""): ("대한상사", "대한상사"),
}


def _raw(kind: str, code: str) -> str:
    """프리셋이 실제로 무언가를 바꾸는 원문 — 표시형이 걸렸는지가 글자로 드러나야 한다."""
    if kind == "amount":
        return "24750000" if code != "{:.1%}" else "0.0525"
    if kind == "date":
        return "2026/7/17 18:05"
    return {"": "대한상사", "phone": "01012345678", "biz": "1234567890"}[code]


def _expected(kind: str, code: str) -> str:
    raw = _raw(kind, code)
    expected = format_engine.render(kind, code, raw)
    if (kind, code) in EMPTY_CODE_GOLDEN:
        assert EMPTY_CODE_GOLDEN[(kind, code)] == (raw, expected), "빈 코드 프리셋의 글자가 바뀌었다"
    if (kind, code) != ("text", ""):
        assert expected != raw, f"{kind}:{code!r} 가 원문을 그대로 낸다 — 이 표본은 아무것도 재지 못한다"
    return expected


def test_the_matrix_is_exactly_what_the_display_select_offers():
    """매트릭스 = 열 행의 표시형 select 항목 전부. 새 프리셋이 생기면 여기가 먼저 넓어진다."""
    offered = [
        (option["type"], option["fmt"])
        for group in display_options(RowState(template_field="필드"), "column")
        for option in group["options"]
    ]
    assert offered == PRESETS
    assert set(EMPTY_CODE_GOLDEN) <= set(PRESETS)


# ─── HWPX: 편집기 → 이월 → 저장 → 다시 열기 → managed 생성 ─────────────────────────
WORK = "표시형"
TARGET = "계약상대자"  # 이름에 「금액」이 없다 — 추정은 text, 사람이 유형을 고른다.
HEADERS = ["공고번호", "수요기관", "품명", "사업명", "계약방법", TARGET, "계약금액", "납품조건"]


@pytest.fixture
def app():
    # conftest 가 ``HWPXFILLER_HOME`` 을 테스트별 임시 폴더로 못박는다.
    from hwpxfiller.webapp.app import WebFrontend

    frontend = WebFrontend()
    assert frontend.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    return frontend


def _csv(path: Path, raw: str, number: str) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADERS)
        writer.writerow([number, "미리내교육진흥원", "복합기", "물품 구매", "일반", raw, "1", "즉시"])
    return path


def _row(editor, field: str) -> dict:
    return next(r for r in editor.snapshot()["rows"] if r["template_field"] == field)


def _assert_select_shows(row: dict, kind: str, code: str) -> None:
    """select 의 값이 그 행 항목 중 하나와 정확히 같아야 선택이 화면에 남는다."""
    assert row["display_value"] == f"{kind}:{code}"
    options = {
        (o["value"], o["type"], o["fmt"])
        for group in row["display_options"]
        for o in group["options"]
    }
    assert (row["display_value"], kind, code) in options


def _texts(docs: "list[Path]") -> "list[str]":
    texts: "list[str]" = []
    for doc in docs:
        with zipfile.ZipFile(doc) as package:
            xml = package.read("Contents/section0.xml").decode("utf-8")
        texts.extend(re.findall(r"<hp:t>([^<]*)</hp:t>", xml))
    return texts


@pytest.mark.parametrize(("kind", "code"), PRESETS, ids=_PRESET_IDS)
def test_editor_display_choice_reaches_the_generated_hwpx(app, tmp_path, kind, code):
    raw, expected = _raw(kind, code), _expected(kind, code)
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    template = next(home_dir().rglob("계약체결안내.hwpx"))
    app.dispatch("editor", "use_library_template", {"path": str(template)})
    editor.load_data_path(str(_csv(tmp_path / "첫.csv", raw, "A-1")))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    index = _row(editor, TARGET)["index"]
    assert _row(editor, TARGET)["display_value"] == "text:", "전제: 이름 추정은 텍스트"

    # 표면이 보내는 그 한 발 — 다른 표시형을 거쳐 목표로 온다(select 를 두 번 바꾼 사람).
    app.dispatch("editor", "set_display", {"index": index, "type": "amount", "fmt": "{:,.2f}"})
    app.dispatch("editor", "set_display", {"index": index, "type": kind, "fmt": code})
    _assert_select_shows(_row(editor, TARGET), kind, code)

    # 데이터 교체 재초안은 사람이 고른 유형·표시형을 이월한다.
    editor.load_data_path(str(_csv(tmp_path / "둘.csv", raw, "B-2")))
    carried = _row(editor, TARGET)
    _assert_select_shows(carried, kind, code)
    assert carried["preview"] == expected, "편집기 미리보기가 산출물과 다른 글자를 말한다"

    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_confirmed", {"index": index, "confirmed": True})
    app.dispatch("editor", "set_name", {"name": WORK})
    app.dispatch("editor", "set_pattern", {"pattern": "문서-{{공고번호}}"})
    assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": WORK}

    # 다시 열면 select 가 같은 항목에 선다.
    assert app.open_job_in_editor(WORK, {}) == WORK
    _assert_select_shows(_row(editor, TARGET), kind, code)

    job = app.controllers["job"]
    app.dispatch("job", "select_job", {"name": WORK})
    app.dispatch("job", "set_all", {})
    assert job.refresh_panel()["managed_hwpx"] is True
    out = pick_output_folder(job, tmp_path / "out")
    result = app.generate("job")
    assert result["ok"] is True and result["status"] == "completed", result
    docs = sorted(Path(out).glob("*.hwpx"))
    assert [doc.name for doc in docs] == ["문서-B-2.hwpx"]
    assert expected in _texts(docs), f"{kind}:{code!r} → {expected!r} 가 문서 본문에 없다"


@pytest.mark.parametrize(
    ("kind", "code"),
    [(kind, code) for kind, code in PRESETS if kind == "amount"],
    ids=[i for i in _PRESET_IDS if i.startswith("amount")],
)
def test_amount_display_reaches_the_filename_token(app, tmp_path, kind, code):
    """파일 이름 토큰도 같은 해석기로 푼다 — 본문과 파일 이름이 다른 글자를 쓰지 않는다."""
    raw, expected = _raw(kind, code), _expected(kind, code)
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    template = next(home_dir().rglob("계약체결안내.hwpx"))
    app.dispatch("editor", "use_library_template", {"path": str(template)})
    editor.load_data_path(str(_csv(tmp_path / "첫.csv", raw, "A-1")))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    index = _row(editor, TARGET)["index"]
    app.dispatch("editor", "set_display", {"index": index, "type": kind, "fmt": code})
    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_confirmed", {"index": index, "confirmed": True})
    app.dispatch("editor", "set_name", {"name": WORK})
    app.dispatch("editor", "set_pattern", {"pattern": "문서-{{" + TARGET + "}}"})
    assert app.dispatch("editor", "save", {})["ok"] is True
    job = app.controllers["job"]
    app.dispatch("job", "select_job", {"name": WORK})
    app.dispatch("job", "set_all", {})
    out = pick_output_folder(job, tmp_path / "out")
    result = app.generate("job")
    assert result["ok"] is True and result["status"] == "completed", result
    assert [doc.name for doc in Path(out).glob("*.hwpx")] == [f"문서-{expected}.hwpx"]


@pytest.mark.parametrize("code", [code for _label, code in format_engine.presets("today")])
def test_today_display_choice_round_trips_through_save(app, tmp_path, code):
    """「오늘 날짜」의 표시형도 select 가 고른 그 항목으로 저장·복원된다(판본 대응은 #950)."""
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    template = next(home_dir().rglob("계약체결안내.hwpx"))
    app.dispatch("editor", "use_library_template", {"path": str(template)})
    editor.load_data_path(str(_csv(tmp_path / "첫.csv", "대한상사", "A-1")))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    index = _row(editor, "납품조건")["index"]
    app.dispatch("editor", "set_display", {"index": index, "type": "today", "fmt": code})
    _assert_select_shows(_row(editor, "납품조건"), "today", code)
    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_confirmed", {"index": index, "confirmed": True})
    app.dispatch("editor", "set_name", {"name": WORK})
    app.dispatch("editor", "set_pattern", {"pattern": "문서-{{공고번호}}"})
    assert app.dispatch("editor", "save", {})["ok"] is True
    assert app.open_job_in_editor(WORK, {}) == WORK
    _assert_select_shows(_row(editor, "납품조건"), "today", code)


# ─── TXT: 작업대 동사 → 기본 규칙 저장 → 봉인된 물질화로 복사 ─────────────────────
NOW = datetime(2026, 8, 25, 9, 0, 0)
TXT_BODY = "\n".join(
    [
        "수신: {{수신}}",
        "{{#항목 첨부 첨부 서류}}",
        "{{#선택 계약서 계약서}}",
        "값: {{건명}}",
        "{{/선택}}",
        "{{#선택 견적서 견적서}}",
        "견적서를 첨부합니다.",
        "{{/선택}}",
        "{{/항목}}",
        "끝.",
        "",
    ]
)


def _txt_work(tmp_path: Path, *, kind: str, code: str) -> "tuple[JobRegistry, SlotConfigurationProduct, SealExecutionPlanService]":
    """실 store 세벌을 한 authority root 로 배선한다(앱 조립과 같은 포트).

    유형·표시형은 **저장된 매핑에 미리 싣는다**(#1148) — 작업대가 걷은 `set_map_type`·
    `set_map_fmt`·「기본 규칙으로 저장」은 더 이상 없다. 연결을 고치는 축은 편집기로 나갔고
    (「연결 편집」), 이 계약이 재는 것은 "저장된 규칙이 카드·복사본까지 간다"지 "작업대에서
    규칙을 고칠 수 있다"가 아니다.
    """
    root = tmp_path / "authority"
    template = tmp_path / "안내문.txt"
    template.write_text(TXT_BODY, encoding="utf-8", newline="\n")
    registry = JobRegistry(tmp_path / "jobs")
    registry.save(Job(name="안내문", template_path=str(template), mapping=MappingProfile(mappings=[
        FieldMapping(template_field="수신", source="수신처"),
        FieldMapping(template_field="건명", source="값", type=kind, fmt=code),
    ]), binding_authority=JOB_MAPPING_AUTHORITY))
    slots = SlotConfigurationProduct(registry, root=root, clock=lambda: NOW)
    job = JobController(
        registry, lambda s, snap: None,
        clock=lambda: NOW, engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        template_change=TemplateChangeCoordinator(registry, root=root, clock=lambda: NOW),
        slot_configuration=slots,
    )
    job.dispatch("select_job", {"name": "안내문"})
    job.dispatch("template_check", {"request_id": "k1"})
    token = job.dispatch("open_slot_configuration", {})["current_view"]["new_configuration_token"]
    job.dispatch("select_slot_option", {
        "configuration_token": token, "slot_id": "첨부", "option_id": "계약서", "request_id": "r1",
    })
    seal = SealExecutionPlanService(registry, root=root, clock=lambda: NOW)
    return registry, slots, seal


@pytest.mark.parametrize(("kind", "code"), PRESETS, ids=_PRESET_IDS)
def test_workbench_display_verbs_reach_the_copied_text(tmp_path, kind, code):
    """저장된 유형·표시형이 작업대 카드와 복사본까지 같은 글자로 간다(#1148 재표현).

    작업대는 연결을 편집하지 않으므로(판정 E 뒤집기) 유형·표시형은 「연결 편집」(편집기)이
    저장하는 규칙이다 — 여기서는 그 결과(저장된 ``Job.mapping``)를 바로 연다.
    """
    raw, expected = _raw(kind, code), _expected(kind, code)
    registry, slots, seal = _txt_work(tmp_path, kind=kind, code=code)

    controller = WorkbenchController(
        registry, lambda s, snap: None, clock=lambda: NOW,
        target_font=TargetFontSetting(),
        content_selection=_content_selection_reader(slots, registry),
        txt_materialization=_txt_materialization_port(registry, seal),
    )
    controller.open(registry.load("안내문"), [(0, {"수신처": "○○청", "값": raw})])
    card = controller.snapshot()["card"]
    mark = next(m for m in card["marks"] if m["name"] == "건명")
    assert card["text"][mark["start"]:mark["end"]] == expected

    # 봉인된 물질화 bytes 를 복사한다 — 카드가 보인 글자와 같다(결정 17).
    written: "list[str]" = []
    result = controller.copy_to(controller.copy_token(), written.append)
    assert result["copied"] is True, result
    assert written == [f"수신: ○○청\n값: {expected}\n끝.\n"]


# ─── CLI: 프로파일의 유형·표시형 → managed 생성 ───────────────────────────────────
CLI_TEMPLATE = Path(__file__).parent / "corpus" / "real" / "bid_notice_limited_under100m.hwpx"
#: 이 실 코퍼스에서 표 셀(``hp:tc``) 안에 선 누름틀 — 셀 안 채움도 같은 해석기를 지난다.
CLI_CELL_FIELD = "담당자"


@pytest.mark.parametrize(("kind", "code"), PRESETS, ids=_PRESET_IDS)
def test_cli_profile_display_reaches_the_generated_hwpx(tmp_path, kind, code):
    raw, expected = _raw(kind, code), _expected(kind, code)
    data = tmp_path / "data.csv"
    with data.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["번호", "값"])
        writer.writerow(["R-1", raw])
    engine = make_hwpx_engine()
    mappings = [
        FieldMapping("입찰공고번호", "번호"),
        FieldMapping("계약방법", "값", type=kind, fmt=code),  # 본문 문단의 누름틀
        FieldMapping(CLI_CELL_FIELD, "값", type=kind, fmt=code),  # 표 셀 안의 누름틀
    ]
    covered = {m.template_field for m in mappings}
    mappings += [
        FieldMapping(field, type="const")
        for field in engine.required_fields(str(CLI_TEMPLATE))
        if field not in covered
    ]
    profile = tmp_path / "map.json"
    save_mapping_profile(MappingProfile(name="p", mappings=mappings), profile)
    out = tmp_path / "out"
    rc = cli_main([
        "--template", str(CLI_TEMPLATE), "--data", str(data), "--profile", str(profile),
        "--out", str(out), "--pattern", "p-{{입찰공고번호}}",
    ])
    assert rc == 0
    docs = sorted(out.glob("*.hwpx"))
    assert [doc.name for doc in docs] == ["p-R-1.hwpx"]
    with zipfile.ZipFile(docs[0]) as package:
        xml = "".join(
            package.read(name).decode("utf-8")
            for name in package.namelist()
            if name.startswith("Contents/section")
        )
    cells = re.findall(r"<hp:tc\b.*?</hp:tc>", xml, re.S)
    outside = re.sub(r"<hp:tbl\b.*?</hp:tbl>", "", xml, flags=re.S)
    in_cells = [t for cell in cells for t in re.findall(r"<hp:t>([^<]*)</hp:t>", cell)]
    in_body = re.findall(r"<hp:t>([^<]*)</hp:t>", outside)
    assert expected in in_body, f"{kind}:{code!r} → {expected!r} 가 CLI 산출물 본문에 없다"
    assert expected in in_cells, f"{kind}:{code!r} → {expected!r} 가 CLI 산출물 표 셀에 없다"
