"""Headless authoring session, file conflict, and private trial storage boundary."""

from pathlib import Path
from types import SimpleNamespace
import base64
import xml.etree.ElementTree as ET

import pytest

from hwpxfiller.webapp.screen_authoring import AuthoringController
from hwpxfiller.domain.template_authoring import apply as apply_txt
from hwpxcore.package import HwpxPackage


def _controller(tmp_path: Path) -> AuthoringController:
    return AuthoringController(lambda _name, _snapshot: None, directory=tmp_path / "home")


def test_preview_waits_for_editor_commit_and_revision_blocks_old_tab_write(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    a = ctrl.dispatch("new", {"media": "txt", "content": "😀 이름"})
    b = ctrl.dispatch("new", {"media": "txt", "content": "둘째"})
    plan = ctrl.dispatch(
        "preview",
        {"session_id": a["session_id"], "revision": 0,
         "command": {"type": "create_field", "start": 3, "end": 5, "name": "이름"}},
    )
    assert plan["content"] == "😀 {{이름}}"
    assert ctrl.dispatch("content", {"session_id": a["session_id"]})["content"] == "😀 이름"
    updated = ctrl.dispatch("update", {"session_id": a["session_id"], "revision": 0, "content": plan["content"]})
    assert updated["revision"] == 1
    picked = ctrl.dispatch("locate", {"session_id": a["session_id"], "revision": 1,
                                      "selection": {"start": 4, "end": 4}})
    assert [match["name"] for match in picked["matches"] if match["kind"] == "field"] == ["이름"]
    with pytest.raises(ValueError, match="변경"):
        ctrl.dispatch("update", {"session_id": a["session_id"], "revision": 0, "content": "stale"})
    with pytest.raises(ValueError, match="변경"):
        ctrl.dispatch("update", {"session_id": a["session_id"], "revision": True, "content": "stale"})
    assert ctrl.dispatch("content", {"session_id": b["session_id"]})["content"] == "둘째"


def test_external_change_refuses_save_and_restart_recovers_draft(tmp_path: Path) -> None:
    path = tmp_path / "example.txt"
    path.write_text("원본", encoding="utf-8")
    ctrl = _controller(tmp_path)
    opened = ctrl.open_path(path)
    sid = opened["session_id"]
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": "내 편집"})
    assert ctrl.snapshot()["tabs"][0]["recovery_saved_at"]
    path.write_text("외부 편집", encoding="utf-8")
    blocked = ctrl.dispatch("save", {"session_id": sid, "revision": 1})
    assert blocked["external_changed"] is True
    assert path.read_text(encoding="utf-8") == "외부 편집"
    restarted = _controller(tmp_path)
    assert restarted.initial()["recoverable"][0]["path"] == str(path)
    key = restarted.initial()["recoverable"][0]["key"]
    comparison = restarted.dispatch("recovery_content", {"key": key})
    assert comparison["content"] == "내 편집"
    assert comparison["original_content"] == "외부 편집"
    assert comparison["external_changed"] is True
    assert restarted.sessions == {}
    recovered = restarted.dispatch("recover_draft", {"key": key})
    assert recovered["content"] == "내 편집"
    assert restarted.dispatch("check_external", {"session_id": recovered["session_id"]})["changed"] is True


def test_imported_source_tracks_external_change_without_becoming_save_target(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("원본", encoding="utf-8")
    ctrl = _controller(tmp_path)
    opened = ctrl.open_path(source, as_template=False)
    sid = opened["session_id"]
    assert ctrl.snapshot()["tabs"][0]["save_as_required"] is True
    assert ctrl.dispatch("check_external", {"session_id": sid})["changed"] is False
    assert ctrl.dispatch("external_content", {"session_id": sid})["content"] == "원본"
    source.write_text("외부 변경", encoding="utf-8")
    assert ctrl.dispatch("check_external", {"session_id": sid})["changed"] is True
    reloaded = ctrl.dispatch("reload", {"session_id": sid, "revision": 0})
    assert reloaded["content"] == "외부 변경"
    assert ctrl.dispatch("check_external", {"session_id": sid})["changed"] is False
    assert ctrl.snapshot()["tabs"][0]["save_as_required"] is True


def test_corrupt_local_recovery_and_cases_do_not_block_document_open(tmp_path: Path) -> None:
    path = tmp_path / "example.txt"
    path.write_text("{{이름}}", encoding="utf-8")
    home = tmp_path / "home"
    drafts = home / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "broken.json").write_text("{", encoding="utf-8")
    from hwpxfiller.external.authoring_store import AuthoringStore

    key = AuthoringStore.key(path)
    (drafts / f"{key}.json").write_text("{", encoding="utf-8")
    cases = home / "cases"
    cases.mkdir()
    (cases / f"{key}.json").write_text("[]", encoding="utf-8")
    ctrl = _controller(tmp_path)
    pending = {item["key"]: item for item in ctrl.initial()["recoverable"]}
    assert pending["broken"]["error"] and pending[key]["error"]
    with pytest.raises(ValueError):
        ctrl.dispatch("recovery_content", {"key": "broken"})
    opened = ctrl.open_path(path)
    tab = ctrl.snapshot()["tabs"][0]
    assert opened["content"] == "{{이름}}" and tab["cases_error"] and tab["recovery"]
    assert ctrl.dispatch("save_cases", {"session_id": opened["session_id"]})["needs_case_repair"]
    assert (cases / f"{key}.json").read_text(encoding="utf-8") == "[]"
    assert ctrl.dispatch("discard_draft", {"key": "broken"}) == {"ok": True}
    assert ctrl.dispatch("discard_draft", {"key": key}) == {"ok": True}
    assert ctrl.initial()["recoverable"] == []


def test_cases_have_an_independent_explicit_save_and_close_guard(tmp_path: Path) -> None:
    path = tmp_path / "template.txt"
    path.write_text("{{이름}}", encoding="utf-8")
    ctrl = _controller(tmp_path)
    opened = ctrl.open_path(path)
    sid = opened["session_id"]
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 0,
                                  "values": {"이름": "홍길동"}, "selected": {}})
    assert ctrl.dispatch("save_cases", {"session_id": sid}) == {"needs_case_name": True}
    assert ctrl.snapshot()["tabs"][0]["trial_inputs_dirty"] is True
    ctrl.dispatch("case_upsert", {"session_id": sid, "revision": 0, "name": "검토", "values": {"이름": "홍길동"}, "selected": {}})
    assert ctrl.dispatch("close", {"session_id": sid}) == {
        "needs_confirm": True, "document_dirty": False, "dirty": False,
        "cases_dirty": True, "trial_inputs_dirty": False,
    }
    assert _controller(tmp_path).open_path(path)["analysis"]["fields"][0]["name"] == "이름"
    assert _controller(tmp_path).snapshot()["recoverable"] == []
    ctrl.dispatch("save_cases", {"session_id": sid})
    again = _controller(tmp_path)
    again.open_path(path)
    assert again.snapshot()["tabs"][0]["cases"][0]["values"] == {"이름": "홍길동"}
    assert path.read_text(encoding="utf-8") == "{{이름}}"


def test_structure_search_returns_analyzer_location_for_navigation(tmp_path: Path) -> None:
    source = "머리\n본문\n차선\n끝\n"
    structured, _ = apply_txt("txt", source, {
        "type": "create_slot", "start": source.index("본문"), "end": source.index("끝"),
        "id": "항목1", "label": "표시",
    })
    structured, _ = apply_txt("txt", structured, {
        "type": "create_option", "start": structured.index("본문"),
        "end": structured.index("본문") + 2, "slot_id": "항목1", "id": "안1",
    })
    structured, _ = apply_txt("txt", structured, {
        "type": "create_option", "start": structured.index("차선"),
        "end": structured.index("차선") + 2, "slot_id": "항목1", "id": "안2",
    })
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt", "content": structured})
    found = ctrl.dispatch("search", {"session_id": opened["session_id"], "revision": 0,
                                     "query": "표시", "kind": "structure"})
    location = opened["analysis"]["slots"][0]["location"]
    assert found["hits"][0]["start"] == location["start"]
    assert found["hits"][0]["end"] == location["end"]
    picked = ctrl.dispatch("locate", {"session_id": opened["session_id"], "revision": 0,
                                      "selection": {"start": location["content_start_offset"],
                                                    "end": location["content_start_offset"]}})
    assert picked["context"]["slot_id"] == "항목1"
    assert any(item["kind"] == "slot" for item in picked["matches"])
    ctrl.dispatch("trial_input", {"session_id": opened["session_id"], "revision": 0,
                                  "values": {}, "selected": {"항목1": "안1"}})
    tested = ctrl.dispatch("trial", {"session_id": opened["session_id"], "revision": 0})
    assert tested["tested_selection"] == {"항목1": "안1"}
    assert tested["source_revision"] == 0
    assert ctrl.snapshot()["tabs"][0]["trial_coverage"] == [
        {"slot_id": "항목1", "option_id": "안1", "state": "current"},
        {"slot_id": "항목1", "option_id": "안2", "state": "untried"},
    ]
    ctrl.dispatch("trial_input", {"session_id": opened["session_id"], "revision": 0,
                                  "values": {}, "selected": {"항목1": "안2"}})
    ctrl.dispatch("trial", {"session_id": opened["session_id"], "revision": 0})
    assert ctrl.snapshot()["tabs"][0]["trial_coverage"][0]["state"] == "stale"
    assert ctrl.snapshot()["tabs"][0]["trial_coverage"][1]["state"] == "current"
    ctrl.dispatch("trial_input", {"session_id": opened["session_id"], "revision": 0,
                                  "values": {"확인": "변경"}, "selected": {"항목1": "안2"}})
    assert [item["state"] for item in ctrl.snapshot()["tabs"][0]["trial_coverage"]] == [
        "stale", "stale"
    ]


def test_semantic_clipboard_is_token_fenced_and_preview_only(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    source = ctrl.dispatch("new", {"media": "txt", "content": "{{이름}}"})
    target = ctrl.dispatch("new", {"media": "txt", "content": "안녕 "})
    copied = ctrl.dispatch("copy", {"session_id": source["session_id"], "revision": 0,
                                   "selector": {"kind": "field", "start": 1}})
    pasted = ctrl.dispatch("preview_paste", {"session_id": target["session_id"],
                                             "revision": 0, "clipboard_token": copied["clipboard_token"],
                                             "destination": {"start": 3, "end": 3},
                                             "with_meaning": True})
    assert pasted["content"] == "안녕 {{이름}}"
    assert ctrl.dispatch("content", {"session_id": target["session_id"]})["content"] == "안녕 "
    ctrl.dispatch("copy", {"session_id": target["session_id"], "revision": 0,
                           "selector": {"kind": "text", "start": 0, "end": 2}})
    with pytest.raises(ValueError, match="변경"):
        ctrl.dispatch("preview_paste", {"session_id": target["session_id"],
                                        "revision": 0, "clipboard_token": copied["clipboard_token"],
                                        "destination": {"start": 3, "end": 3},
                                        "with_meaning": False})


def test_rhwp_roundtrip_preflight_blocks_mutation_on_document_loss(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    fixture = Path(__file__).parent / "fixtures" / "template_v1.hwpx"
    opened = ctrl.open_path(fixture)
    sid = opened["session_id"]
    same = ctrl.dispatch("rhwp_roundtrip_preflight", {"session_id": sid, "revision": 0,
                                                      "content": opened["content"]})
    assert same == {"editable": True, "diagnostics": []}
    changed = HwpxPackage.from_bytes(fixture.read_bytes())
    changed.entries["Contents/header.xml"] = changed.entries["Contents/header.xml"].replace(
        b"paraPr", b"paraXX", 1
    )
    blocked = ctrl.dispatch("rhwp_roundtrip_preflight", {"session_id": sid, "revision": 0,
                                                         "content": base64.b64encode(changed.to_bytes()).decode("ascii")})
    assert blocked["editable"] is False
    assert blocked["diagnostics"][0]["entry"] == "Contents/header.xml"
    with pytest.raises(ValueError, match="보존 검증"):
        ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": opened["content"]})
    assert ctrl.save_to_path(sid, 0, tmp_path / "safe-copy.hwpx")["ok"] is True
    assert (tmp_path / "safe-copy.hwpx").read_bytes() == fixture.read_bytes()


def test_existing_job_impact_uses_shared_coordinator_after_file_save(tmp_path: Path) -> None:
    path = tmp_path / "template.txt"
    path.write_text("{{새필드}}", encoding="utf-8")
    related = SimpleNamespace(name="연결 작업", template_path=str(path), media="txt",
                              template_fields=lambda: ["옛필드"])
    unrelated = SimpleNamespace(name="다른 작업", template_path=str(tmp_path / "other.txt"),
                                media="txt", template_fields=lambda: [])

    class Registry:
        def list_jobs(self, *, corrupted):
            return [related, unrelated]

    class Change:
        def __init__(self):
            self.calls = []

        def zone(self, name, media, missing):
            return {"source_drift": "changed", "actionable": True}

        def check(self, name, request_id):
            self.calls.append(("check", name, request_id))
            return {"ok": True, "preparation": {"change_token": "token"}}

        def apply(self, name, token):
            self.calls.append(("apply", name, token))
            return {"ok": True}

    change = Change()
    ctrl = AuthoringController(lambda _name, _snapshot: None, directory=tmp_path / "home",
                               job_registry=Registry(), template_change=change)
    opened = ctrl.open_path(path)
    sid = opened["session_id"]
    impact = ctrl.dispatch("impact", {"session_id": sid, "revision": 0})
    preview = ctrl.dispatch("preview", {"session_id": sid, "revision": 0,
                                        "command": {"type": "rename_field",
                                                    "old_name": "새필드", "name": "변경필드"}})
    assert preview["linked_jobs"] == ["연결 작업"]
    assert preview["field_delta"] == {
        "added_fields": ["변경필드"], "removed_fields": ["새필드"]
    }
    assert ctrl.dispatch("content", {"session_id": sid})["content"] == "{{새필드}}"
    assert [(job["name"], job["added_fields"], job["unmapped_fields"])
            for job in impact["jobs"]] == [("연결 작업", ["새필드"], ["옛필드"])]
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        ctrl.dispatch("prepare_apply", {"session_id": sid, "revision": 0, "job_name": "다른 작업"})
    checked = ctrl.dispatch("prepare_apply", {"session_id": sid, "revision": 0, "job_name": "연결 작업"})
    assert checked["preparation"]["change_token"] == "token"
    assert ctrl.dispatch("apply_job", {"session_id": sid, "revision": 0,
                                       "job_name": "연결 작업", "change_token": "token"})["ok"] is True
    assert [call[0] for call in change.calls] == ["check", "apply"]


def test_hwpx_trial_export_is_fenced_to_the_latest_success(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    fixture = Path(__file__).parent / "fixtures" / "template_v1.hwpx"
    opened = ctrl.open_path(fixture)
    sid = opened["session_id"]
    assert ctrl.dispatch("rhwp_roundtrip_preflight", {"session_id": sid, "revision": 0,
                                                       "content": opened["content"]})["editable"]
    name = opened["analysis"]["fields"][0]["name"]
    first = opened["analysis"]["fields"][0]["occurrences"][0]
    picked = ctrl.dispatch("locate", {"session_id": sid, "revision": 0,
                                      "selection": {"entry": first["entry"],
                                                    "paragraph": first["paragraph"],
                                                    "start_paragraph": first["paragraph"],
                                                    "end_paragraph": first["paragraph"],
                                                    "start": 0, "end": 0}})
    assert any(item["kind"] == "field" and item["name"] == name for item in picked["matches"])
    assert ctrl.dispatch("trial", {"session_id": sid, "revision": 0})["ok"] is False
    assert ctrl.snapshot()["tabs"][0]["trial_state"] == "failed"
    with pytest.raises(ValueError, match="최신"):
        ctrl.export_result_path(sid, 0, tmp_path / "missing.hwpx")
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 0,
                                  "values": {name: "검토값"}, "selected": {}})
    result = ctrl.dispatch("trial", {"session_id": sid, "revision": 0})
    assert HwpxPackage.from_bytes(base64.b64decode(result["content"])).content_xml_names()
    assert result["section_entries"] == AuthoringController._section_entries(
        base64.b64decode(result["content"])
    )
    external = ctrl.dispatch("external_content", {"session_id": sid})
    assert external["section_entries"] == opened["section_entries"]
    target = tmp_path / "result.hwpx"
    assert ctrl.export_result_path(sid, 0, target)["ok"] is True
    assert target.read_bytes() == base64.b64decode(result["content"])
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": opened["content"]})
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 0,
                                  "values": {name: "다른 값"}, "selected": {}})
    with pytest.raises(ValueError, match="최신"):
        ctrl.export_result_path(sid, 0, tmp_path / "stale.hwpx")


def test_hwpx_section_mapping_uses_manifest_spine_order() -> None:
    fixture = Path(__file__).parent / "fixtures" / "template_v1.hwpx"
    package = HwpxPackage.from_bytes(fixture.read_bytes())
    package.entries["Contents/section1.xml"] = package.entries["Contents/section0.xml"]
    root = ET.fromstring(package.entries["Contents/content.hpf"])
    namespace = "{http://www.idpf.org/2007/opf/}"
    manifest = root.find(f"{namespace}manifest")
    spine = root.find(f"{namespace}spine")
    assert manifest is not None and spine is not None
    ET.SubElement(manifest, f"{namespace}item", {"id": "section1", "href": "Contents/section1.xml"})
    spine.insert(1, ET.Element(f"{namespace}itemref", {"idref": "section1"}))
    package.entries["Contents/content.hpf"] = ET.tostring(root)
    assert AuthoringController._section_entries(package.to_bytes()) == [
        "Contents/section1.xml", "Contents/section0.xml",
    ]


def test_save_to_path_notifies_mutation_sinks_and_lets_their_failure_propagate(tmp_path: Path) -> None:
    """저장은 템플릿 bytes 변이다 — tpl 채널과 같은 ``(kind, path)`` 통지가 나가고 sink 실패는 삼키지 않는다."""
    path = tmp_path / "template.txt"
    path.write_text("{{이름}}", encoding="utf-8")
    ctrl = _controller(tmp_path)
    seen: list[tuple[str, str]] = []
    ctrl.mutation_sinks.append(lambda kind, mutated: seen.append((kind, mutated)))
    sid = ctrl.open_path(path)["session_id"]
    updated = ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": "{{이름}} {{날짜}}"})

    assert ctrl.save_to_path(sid, updated["revision"], path)["ok"] is True
    assert seen == [("mutated", str(path.resolve()))]

    def explode(kind: str, mutated: str) -> None:
        raise RuntimeError("재정산 실패")

    ctrl.mutation_sinks.append(explode)
    updated = ctrl.dispatch("update", {"session_id": sid, "revision": updated["revision"], "content": "{{이름}}"})
    with pytest.raises(RuntimeError, match="재정산 실패"):
        ctrl.save_to_path(sid, updated["revision"], path)
    assert path.read_text(encoding="utf-8") == "{{이름}}"  # 쓰기는 끝났고 통지 실패만 시끄럽다


def test_hwpx_locate_matches_cell_field_only_with_same_cell_path(tmp_path: Path) -> None:
    from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE
    from hwpxfiller.external.hwpx_authoring import apply_hwpx

    hp = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    hs = "http://www.hancom.co.kr/hwpml/2011/section"
    package = HwpxPackage()
    package.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    package.stored.add(MIMETYPE_NAME)
    entry = "Contents/section0.xml"
    package.entries[entry] = (
        f'<hs:sec xmlns:hs="{hs}" xmlns:hp="{hp}">'
        '<hp:p><hp:run><hp:t>본문</hp:t></hp:run>'
        '<hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>'
        '<hp:p><hp:run><hp:t>셀값</hp:t></hp:run></hp:p>'
        '</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hs:sec>'
    ).encode("utf-8")
    # 본문 필드의 fieldBegin ctrl 이 표 앞에 놓이므로 표는 rhwp control 1 이 된다.
    cell_path = [{"parent_paragraph": 0, "control": 1, "cell": 0, "paragraph": 0}]
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 0,
                         "start": 0, "end": 1, "name": "본"})
    apply_hwpx(package, {"type": "create_field", "entry": entry, "cell_path": cell_path,
                         "paragraph": 0, "start": 0, "end": 2, "name": "셀"})
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "hwpx",
                                   "content": base64.b64encode(package.to_bytes()).decode("ascii")})
    sid = opened["session_id"]
    selection = {"entry": entry, "paragraph": 0, "start_paragraph": 0, "end_paragraph": 0,
                 "start": 0, "end": 1}

    def names(result: dict) -> list[str]:
        return sorted(match["name"] for match in result["matches"] if match["kind"] == "field")

    body = ctrl.dispatch("locate", {"session_id": sid, "revision": 0, "selection": selection})
    assert names(body) == ["본"]
    cell = ctrl.dispatch("locate", {"session_id": sid, "revision": 0,
                                    "selection": {**selection, "cell_path": cell_path}})
    assert names(cell) == ["셀"]
    assert cell["matches"][0]["location"]["cell_path"] == cell_path
    other_cell = ctrl.dispatch("locate", {"session_id": sid, "revision": 0,
                                          "selection": {**selection,
                                                        "cell_path": [{**cell_path[0], "cell": 1}]}})
    assert names(other_cell) == []
    for broken in ([], [{"control": 0}], [{**cell_path[0], "cell": True}], [{**cell_path[0], "cell": -1}]):
        invalid = ctrl.dispatch("locate", {"session_id": sid, "revision": 0,
                                           "selection": {**selection, "cell_path": broken}})
        assert invalid["matches"] == [] and invalid["context"]["reason"] == "선택 위치가 유효하지 않습니다."
