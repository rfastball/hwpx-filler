"""튜토리얼 과정을 실제 제품 동작으로 끝까지 걷는다(#1127).

한 단계 = 상자 하나 = 동작 하나. 그래서 걸음마다 **지금 단계가 무엇인지 먼저 확인하고**
그 단계가 가리키는 동작 하나만 보낸 뒤, 정확히 다음 단계로 한 칸 넘어갔는지 본다. 제품 명령이
없는 누르기(독 열기·시트 체크 등)는 웹이 보내는 UI 사실(``observe_ui``)로 넘어간다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    return WebFrontend()


class Walk:
    def __init__(self, app, lesson: str) -> None:
        self.app = app
        self.tutorial = app.controllers["tutorial"]
        app.dispatch("tutorial", "select", {"scenario_id": lesson})
        self.lesson = lesson

    @property
    def ctx(self) -> dict:
        return self.tutorial._context()

    def asset(self, name: str) -> str:
        return self.ctx["assets"][name]["path"]

    def beat(self) -> dict:
        return self.app.initial("tutorial")["beat"]

    def step(self, beat_id: str, act) -> None:
        """Expect ``beat_id`` now, perform its one action, expect exactly the next beat."""
        snap = self.app.initial("tutorial")
        assert snap["beat"] and snap["beat"]["id"] == beat_id, (beat_id, snap["beat"])
        checkpoint = snap["checkpoint"]
        act()
        after = self.app.initial("tutorial")
        assert after["checkpoint"] == checkpoint + 1, (beat_id, after["beat"])

    def press(self, beat_id: str) -> None:
        def report():
            beat = self.beat()
            assert beat["press"], beat
            self.app.dispatch("tutorial", "observe_ui", {
                "scenario_id": self.lesson, "checkpoint": self.app.initial("tutorial")["checkpoint"],
                "anchor": beat["target"]})
        self.step(beat_id, report)

    def send(self, screen: str, action: str, payload: "dict | None" = None):
        result = self.app.dispatch(screen, action, payload or {})
        assert not (isinstance(result, dict) and "__hwpx_dispatch_rejection_v1__" in result), result
        return result

    def row(self, field: str) -> int:
        rows = self.app.controllers["editor"].edit.model.rows
        return next(i for i, row in enumerate(rows) if row.template_field == field)

    def option(self, slot_label: str, option_label: str) -> None:
        view = self.send("job", "open_slot_configuration")["current_view"]
        slot = next(item for item in view["projection"]["slots"] if item["display_text"] == slot_label)
        option = next(item for item in slot["options"] if item["display_text"] == option_label)
        self.send("job", "select_slot_option", {
            "configuration_token": view["new_configuration_token"], "slot_id": slot["slot_id"],
            "option_id": option["option_id"], "request_id": f"{slot_label}-{option_label}"})

    def finished(self) -> dict:
        snap = self.app.initial("tutorial")
        assert snap["checkpoint"] == snap["beat_count"] and not snap["active"]
        assert snap["result"] is not None
        return snap["result"]


def test_lesson_one_walks_single_actions_to_three_documents(app, tmp_path):
    walk = Walk(app, "first_hwpx")
    assert walk.ctx["pool_keys"].keys() == {"공고", "계약"}
    walk.step("intro", lambda: walk.send("tutorial", "next"))
    walk.step("new_job", lambda: walk.send("editor", "new_session"))
    walk.step("template", lambda: walk.send("editor", "use_library_template",
                                            {"path": walk.asset("물품 구매입찰 공고.hwpx")}))
    assert walk.beat()["arg"] == walk.ctx["pool_keys"]["공고"]
    walk.step("data", lambda: walk.send("editor", "use_pool_data", {"key": walk.ctx["pool_keys"]["공고"]}))
    walk.step("to_binding", lambda: walk.send("editor", "goto_section", {"section": "binding"}))
    walk.step("confirm_method", lambda: walk.send("editor", "set_confirmed",
                                                  {"index": walk.row("낙찰자결정방법"), "confirmed": True}))
    walk.step("confirm_phone", lambda: walk.send("editor", "set_confirmed",
                                                 {"index": walk.row("담당자 전화번호"), "confirmed": True}))
    walk.step("to_filename", lambda: walk.send("editor", "goto_section", {"section": "filename"}))
    walk.step("pattern", lambda: walk.send("editor", "set_pattern", {"pattern": "구매입찰공고-{{입찰공고번호}}"}))

    def save_and_open():
        assert walk.send("editor", "save")["ok"]
        walk.send("job", "prefer_work", {"name": app.controllers["editor"].edit.job_name or walk.ctx["job_name"]})
    walk.step("save", save_and_open)
    walk.step("memo_filter", lambda: walk.send("job", "filter_panel", {"column": "메모"}))
    walk.step("filter", lambda: walk.send("job", "filter_col_text", {"column": "메모", "text": "소상공인"}))
    walk.step("rows", lambda: walk.send("job", "set_all"))
    walk.step("qualification", lambda: walk.option("입찰참가자격", "소기업·소상공인"))
    walk.step("method", lambda: walk.option("낙찰자 결정방법", "고시 미만"))
    pick_output_folder(app.controllers["job"], tmp_path / "out")
    walk.step("generate", lambda: app.generate("job"))
    walk.step("result", lambda: walk.send("job", "artifact_open", {"ordinal": 0}))
    result = walk.finished()
    assert result["count"] == 3 and result["next_scenario_id"] == "repeat_hwpx"


def test_lesson_two_reopens_the_seeded_job_and_filters_by_value_list(app, tmp_path):
    walk = Walk(app, "repeat_hwpx")
    assert walk.ctx["job_name"] == "공고서 작업"
    walk.step("pick_job", lambda: walk.send("library", "select_work", {"name": "공고서 작업"}))
    walk.step("use_job", lambda: walk.send("job", "prefer_work", {"name": "공고서 작업"}))
    walk.step("memo_filter", lambda: walk.send("job", "filter_panel", {"column": "메모"}))
    walk.step("values_off", lambda: walk.send("job", "filter_col_values", {"column": "메모", "values": []}))
    value = "포함할 내용: 중·소기업 / 고시 미만"
    assert walk.beat()["arg"] == value
    walk.step("filter", lambda: walk.send("job", "filter_col_values", {"column": "메모", "values": [value]}))
    walk.step("rows", lambda: walk.send("job", "set_all"))
    walk.step("qualification", lambda: walk.option("입찰참가자격", "중·소기업"))
    walk.step("method", lambda: walk.option("낙찰자 결정방법", "고시 미만"))
    walk.step("names", lambda: walk.send("tutorial", "next"))
    pick_output_folder(app.controllers["job"], tmp_path / "out")
    walk.step("generate", lambda: app.generate("job"))
    assert walk.finished()["count"] == 3


def test_lesson_three_contract_txt_copies_two_rows(app, monkeypatch):
    import hwpxfiller.webapp.app as app_module

    monkeypatch.setattr(app_module, "set_clipboard_text", lambda _text: None)
    walk = Walk(app, "contract_txt")
    walk.step("new_job", lambda: walk.send("editor", "new_session"))
    walk.step("template", lambda: walk.send("editor", "use_library_template",
                                            {"path": walk.asset("낙찰자 선정 및 계약체결 안내.txt")}))
    walk.step("data", lambda: walk.send("editor", "use_pool_data", {"key": walk.ctx["pool_keys"]["계약"]}))
    walk.step("to_binding", lambda: walk.send("editor", "goto_section", {"section": "binding"}))
    walk.step("firm_source", lambda: walk.send("editor", "set_source",
                                               {"index": walk.row("대표계약업체"), "source": "계약상대자"}))
    walk.step("firm_confirm", lambda: walk.send("editor", "set_confirmed",
                                                {"index": walk.row("대표계약업체"), "confirmed": True}))
    walk.step("currency", lambda: walk.send("editor", "set_display",
                                            {"index": walk.row("계약보증금"), "type": "amount", "fmt": ""}))
    walk.step("currency_confirm", lambda: walk.send("editor", "set_confirmed",
                                                    {"index": walk.row("계약보증금"), "confirmed": True}))
    walk.step("to_filename", lambda: walk.send("editor", "goto_section", {"section": "filename"}))

    def save_and_open():
        assert walk.send("editor", "save")["ok"]
        walk.send("job", "prefer_work", {"name": walk.ctx["job_name"]})
    walk.step("save", save_and_open)
    walk.step("rows", lambda: walk.send("job", "set_all"))
    assert len(app.controllers["job"].data.selected_indices()) == 6
    walk.step("workbench", lambda: walk.send("job", "open_workbench"))
    copy = lambda: app.copy_clipboard("workbench", app.controllers["workbench"].copy_token())  # noqa: E731
    walk.step("copy_first", copy)
    walk.step("next_row", lambda: walk.send("workbench", "step", {"delta": 1}))
    walk.step("copy_second", copy)
    assert walk.finished()["count"] == 2


def test_lesson_four_purchase_txt_starts_in_the_editor_and_slices(app, monkeypatch):
    import hwpxfiller.webapp.app as app_module

    monkeypatch.setattr(app_module, "set_clipboard_text", lambda _text: None)
    walk = Walk(app, "purchase_txt")
    editor = app.controllers["editor"]
    assert walk.ctx["job_name"] == "구매추진 안내 작업"
    assert editor.edit.editing_origin == "구매추진 안내 작업" and editor.edit.section == "binding"
    index = walk.row("군품명")
    walk.step("slice_open", lambda: walk.send("editor", "preview_slice", {"index": index, "sample": 0}))

    def drag():
        proposal = walk.send("editor", "propose_slice", {"index": index, "sample": 0, "start": 0, "end": 2})
        walk.send("editor", "set_slice", {"index": index, "slice": proposal["candidates"][0]["slice"]})
    walk.step("slice_pick", drag)
    walk.press("slice_done")
    walk.step("slice_confirm", lambda: walk.send("editor", "set_confirmed", {"index": index, "confirmed": True}))
    walk.step("format", lambda: walk.send("editor", "step_preview", {"delta": 1}))

    def save_and_open():
        assert walk.send("editor", "save")["ok"]
        walk.send("job", "prefer_work", {"name": "구매추진 안내 작업"})
    walk.step("save", save_and_open)
    walk.step("rows", lambda: walk.send("job", "set_all"))
    walk.step("workbench", lambda: walk.send("job", "open_workbench"))
    walk.step("copy", lambda: app.copy_clipboard("workbench", app.controllers["workbench"].copy_token()))
    assert walk.finished()["count"] == 1


def assert_stakes(stakes: dict) -> None:
    # The swap left every carried row to confirm by hand: re-suggesting asks first (a dialog).
    assert stakes["resuggest_manual"] > 0, stakes


def test_lesson_five_replaces_the_data_file_through_the_editor(app, monkeypatch):
    import hwpxfiller.webapp.app as app_module

    walk = Walk(app, "replace_data")
    derived = walk.ctx["derived_data_path"]
    assert Path(derived).name == "공고목록(새 판).xlsx"
    walk.step("pick_job", lambda: walk.send("library", "select_work", {"name": "공고서 작업"}))
    walk.step("edit_job", lambda: app.open_job_in_editor("공고서 작업"))
    walk.step("to_template", lambda: walk.send("editor", "goto_section", {"section": "template"}))
    walk.step("browse", lambda: walk.send("editor", "mapping_reset_stakes"))
    hints = []
    monkeypatch.setattr(app_module, "_file_dialog", lambda *_a, **kw: hints.append(kw.get("initial_path")) or derived)
    walk.step("reset", lambda: app.pick_data_file("editor"))
    assert hints == [derived]
    walk.press("sheet")
    walk.step("import", lambda: app.load_data_sheet("editor", derived, ["공고"]))
    walk.step("to_binding", lambda: walk.send("editor", "goto_section", {"section": "binding"}))
    walk.press("menu")
    walk.step("resuggest", lambda: assert_stakes(walk.send("editor", "mapping_reset_stakes")))
    walk.step("resuggest_confirm", lambda: walk.send("editor", "resuggest_all"))
    walk.step("confirm_all", lambda: walk.send("editor", "confirm_suggested"))

    def save_and_open():
        assert walk.send("editor", "save")["ok"]
        walk.send("job", "prefer_work", {"name": "공고서 작업"})
    walk.step("save", save_and_open)
    result = walk.finished()
    assert result["target"] == "data-label"
    assert app.controllers["job"].data.path == derived


def test_lesson_six_compares_the_blank_marker_with_a_declared_blank(app):
    walk = Walk(app, "blank_values")
    assert Path(walk.ctx["derived_data_path"]).name == "공고목록(빈 칸).xlsx"
    walk.step("pick_job", lambda: walk.send("library", "select_work", {"name": "계약 안내 작업(빈 칸)"}))
    walk.step("use_job", lambda: walk.send("job", "prefer_work", {"name": "계약 안내 작업(빈 칸)"}))
    walk.step("rows", lambda: walk.send("job", "set_all"))
    walk.step("workbench", lambda: walk.send("job", "open_workbench"))
    unit = next(row for row in app.controllers["workbench"].snapshot()["rows"] if row["name"] == "단위")
    assert unit["blank_declared"]
    walk.step("blank", lambda: walk.send("tutorial", "next"))
    walk.step("declared", lambda: walk.send("tutorial", "next"))
    assert walk.finished()["next_scenario_id"] == "field_trial"


class Authoring:
    """The authoring screen's own dispatch shapes: a range is asked as ``locate``, a command is
    previewed and its content applied as ``update`` (what ``applyPreview`` sends)."""

    def __init__(self, walk: Walk) -> None:
        self.walk = walk
        self.ctrl = walk.app.controllers["authoring"]

    @property
    def sid(self) -> str:
        return self.ctrl.active_id

    def fence(self, **extra) -> dict:
        return {"session_id": self.sid, "revision": self.ctrl.sessions[self.sid].revision, **extra}

    def text(self) -> str:
        return self.ctrl.sessions[self.sid].content.decode("utf-8")

    def select(self, start: int, end: int):
        return lambda: self.walk.send("authoring", "locate", self.fence(selection={"start": start, "end": end}))

    def apply(self, start: int, end: int, command: dict, enter_twice: bool = False):
        def run():
            selection = {"start": start, "end": end}
            context = self.walk.send("authoring", "locate", self.fence(selection=selection)).get("context", {})
            full = {**selection, **command}
            if command["type"] == "create_option":
                full["slot_id"] = context.get("slot_id")
            preview = self.walk.send("authoring", "preview", self.fence(command=full))
            assert preview.get("confirm") == ("enter" if enter_twice else "none"), preview
            self.walk.send("authoring", "update", self.fence(content=preview["content"]))
        return run


def _open_practice_txt(walk: Walk) -> None:
    """The lesson starts with the practice TXT open as its library template: '저장' writes it in place."""
    authoring = walk.app.controllers["authoring"]
    session = authoring.sessions[authoring.active_id]
    assert session.source_path == session.save_path == walk.asset("낙찰자 선정 및 계약체결 안내.txt")


def _named(name: str) -> dict:
    return {"name": name, "label": name, "id": name}


def test_lesson_seven_makes_a_field_and_saves_after_the_trial(app):
    walk = Walk(app, "field_trial")
    _open_practice_txt(walk)
    doc = Authoring(walk)
    at = doc.text().index("10일")
    walk.step("range", doc.select(at, at + 3))
    walk.press("create")
    walk.step("name", doc.apply(at, at + 3, {"type": "create_field", **_named("재배정기한")}))
    walk.send("authoring", "trial_input", doc.fence(values={"재배정기한": "10일"}, selected={}))
    walk.press("trial_open")

    def fill():
        walk.send("authoring", "trial_fill_names", doc.fence())
        walk.send("authoring", "trial", doc.fence())
    walk.step("fill", fill)
    walk.step("save", lambda: walk.send("authoring", "save", doc.fence()))
    assert walk.finished()["next_scenario_id"] == "option_apply"
    assert walk.tutorial._resources()[0], "저장한 연습 서식이 수정된 파일로 오인됐습니다"


def test_lesson_eight_builds_an_item_with_two_choices(app):
    walk = Walk(app, "option_apply")
    _open_practice_txt(walk)
    doc = Authoring(walk)
    text = doc.text()
    begin = text.index("\n3. ") + 1
    finish = text.index("\n", begin)
    assert text[finish:finish + 4] == "\n\n\n붙", "연습 서식에 항목 안 빈 줄이 깔리지 않았습니다"
    walk.step("item_range", doc.select(begin, finish + 2))
    walk.press("item_create")
    walk.step("item_name", doc.apply(begin, finish + 2, {"type": "create_slot", **_named("예산재배정")}))
    text = doc.text()
    begin = text.index("\n3. ") + 1
    finish = text.index("\n", begin)
    walk.step("include_range", doc.select(begin, finish))
    walk.press("include_create")
    walk.step("include_name", doc.apply(begin, finish, {"type": "create_option", **_named("안내포함")}, enter_twice=True))
    text = doc.text()
    blank = text.index("{{/선택}}\n") + len("{{/선택}}\n")
    walk.step("omit_range", doc.select(blank, blank))
    walk.press("omit_create")
    walk.step("omit_name", doc.apply(blank, blank, {"type": "create_option", **_named("안내생략")}, enter_twice=True))
    walk.press("trial_open")
    walk.step("fill", lambda: walk.send("authoring", "trial_fill_names", doc.fence()))
    slot = next(item for item in doc.ctrl.sessions[doc.sid].analysis["slots"] if item["label"] == "예산재배정")
    values = doc.ctrl.sessions[doc.sid].values

    def trial(option_label: str):
        option = next(item["id"] for item in slot["options"] if item["label"] == option_label)

        def run():
            walk.send("authoring", "trial_input", doc.fence(values=dict(values), selected={slot["id"]: option}))
            walk.send("authoring", "trial", doc.fence())
        return run
    walk.step("trial_include", trial("안내포함"))
    walk.step("trial_omit", trial("안내생략"))
    walk.step("save", lambda: walk.send("authoring", "save", doc.fence()))
    assert walk.finished()["next_scenario_id"] == "change_apply"


def test_lesson_nine_applies_the_seeded_change_and_reviews_the_choice(app):
    walk = Walk(app, "change_apply")
    doc = Authoring(walk)
    assert walk.ctx["job_name"] == "계약 안내 작업"
    _open_practice_txt(walk)
    assert app.controllers["job"].work.name == "계약 안내 작업"
    walk.step("impact", lambda: walk.send("authoring", "impact", doc.fence()))
    token = {}

    def check():
        token.update(walk.send("authoring", "prepare_apply", doc.fence(job_name="계약 안내 작업")))
    walk.step("check", check)
    walk.step("apply", lambda: walk.send("authoring", "apply_job", doc.fence(
        job_name="계약 안내 작업", change_token=token["change_token"])))
    walk.press("to_job")
    walk.step("include", lambda: walk.option("예산재배정", "안내포함"))
    walk.step("rows", lambda: walk.send("job", "set_all"))
    walk.step("workbench", lambda: walk.send("job", "open_workbench"))
    assert walk.finished()["title"] == "변경 적용 결과"
