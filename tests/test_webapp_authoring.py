"""Headless authoring session, file conflict, and private trial storage boundary."""

from pathlib import Path
from types import SimpleNamespace
import base64
import json
import xml.etree.ElementTree as ET

import pytest

from hwpxfiller.external.authoring_store import digest
from hwpxfiller.webapp.screen_authoring import AuthoringController
from hwpxfiller.domain.template_authoring import COMMAND_TYPES, apply as apply_txt
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


def test_linked_jobs_projection_decides_the_impact_tab_from_the_impact_source(tmp_path: Path) -> None:
    """NG-09 — 「변경 영향·작업 적용」 독 탭은 연결 작업이 있는 문서에만 선다. 판정은 ``impact`` 와 같은 원천
    (`_linked_jobs`)의 투영 ``has_linked_jobs`` 이고, 스냅숏마다 작업 파일을 다시 훑지 않는다."""
    linked_path = tmp_path / "linked.txt"
    linked_path.write_text("{{필드}}", encoding="utf-8")
    alone_path = tmp_path / "alone.txt"
    alone_path.write_text("{{필드}}", encoding="utf-8")
    plain_path = tmp_path / "plain.txt"
    plain_path.write_text("계약 상대방 정보", encoding="utf-8")
    job = SimpleNamespace(name="연결 작업", template_path=str(linked_path), media="txt",
                          template_fields=lambda: ["필드"])

    class Registry:
        def __init__(self):
            self.jobs = [job]
            self.corrupted: list = []
            self.scans = 0

        def list_jobs(self, *, corrupted):
            self.scans += 1
            corrupted.extend(self.corrupted)
            return list(self.jobs)

    class Change:
        def zone(self, name, media, missing):
            return {}

    registry = Registry()
    ctrl = AuthoringController(lambda _name, _snapshot: None, directory=tmp_path / "home",
                               job_registry=registry, template_change=Change())
    linked = ctrl.open_path(linked_path)["session_id"]
    alone = ctrl.open_path(alone_path)["session_id"]
    plain = ctrl.open_path(plain_path, as_template=False)["session_id"]

    def tabs() -> dict:
        return {tab["id"]: tab["has_linked_jobs"] for tab in ctrl.snapshot()["tabs"]}

    def impact(sid: str) -> dict:
        return ctrl.dispatch("impact", {"session_id": sid, "revision": 0})

    # 기존 작업의 템플릿이면 선다 — impact 가 그 작업을 싣는 것과 같다.
    assert tabs() == {linked: True, alone: False, plain: False}
    assert [entry["name"] for entry in impact(linked)["jobs"]] == ["연결 작업"]
    assert impact(alone)["jobs"] == [] and impact(alone)["unverified_jobs"] == 0
    # 일반 문서로 연 새 템플릿은 저장 경로가 없어 어떤 작업의 템플릿도 아니다 — 작업 목록을 읽지도 않는다.
    assert ctrl.snapshot()["tabs"][2]["save_as_required"] is True

    # 스냅숏은 캐시를 쓴다(push 마다 작업 파일을 훑지 않는다).
    scans = registry.scans
    for _ in range(3):
        tabs()
    assert registry.scans == scans

    # 다른 화면이 연결을 바꾸면 활성화·외부 변경 확인(창 초점)·첫 스냅숏에서 다시 잰다.
    registry.jobs = []
    ctrl.dispatch("activate", {"session_id": linked})
    assert tabs()[linked] is False
    registry.jobs = [SimpleNamespace(name="새 작업", template_path=str(alone_path), media="txt",
                                     template_fields=lambda: ["필드"])]
    ctrl.dispatch("check_external", {"session_id": alone})
    assert tabs()[alone] is True
    registry.jobs = [job]
    ctrl.initial()
    assert tabs() == {linked: True, alone: False, plain: False}

    # 손상된 작업 파일은 연결을 모르는 것이다 — impact 의 unverified_jobs 와 같이 탭을 숨기지 않는다.
    registry.jobs = []
    registry.corrupted = [(tmp_path / "broken.job.json", "손상")]
    assert impact(alone)["unverified_jobs"] == 1
    assert tabs()[alone] is True


def test_linked_jobs_are_not_hidden_when_the_job_store_is_not_wired(tmp_path: Path) -> None:
    """작업 저장소가 없으면 연결을 확인할 수 없다 — 저장 경로가 있는 문서의 탭은 숨기지 않는다
    (탭 안의 impact 가 「작업 연결을 확인할 수 없습니다.」를 말한다). 저장 경로가 없는 새 템플릿은 서지 않는다."""
    path = tmp_path / "template.txt"
    path.write_text("{{필드}}", encoding="utf-8")
    ctrl = _controller(tmp_path)
    saved = ctrl.open_path(path)["session_id"]
    fresh = ctrl.dispatch("new", {"media": "txt", "content": ""})["session_id"]
    assert {tab["id"]: tab["has_linked_jobs"] for tab in ctrl.snapshot()["tabs"]} == {saved: True, fresh: False}
    assert ctrl.dispatch("impact", {"session_id": saved, "revision": 0})["available"] is False


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
    # 손대지 않은 필드는 결과 시험을 막지 않는다(IDE-01 결정 1(a)) — 생성 경로와 같은 빈 값 표식으로 렌더하고
    # 보고의 empty_fields 로 알린다. 시험 탭의 공백 수(trial_missing)는 그대로 남는다.
    blank = ctrl.dispatch("trial", {"session_id": sid, "revision": 0})
    field_names = [field["name"] for field in opened["analysis"]["fields"]]
    assert sorted(blank["report"]["empty_fields"]) == sorted(field_names) and blank["report"]["missing_fields"] == []
    blank_package = HwpxPackage.from_bytes(base64.b64decode(blank["content"]))
    blank_text = "".join("".join(ET.fromstring(blank_package.entries[entry]).itertext())
                         for entry in blank["section_entries"])
    assert f"〘미입력·{name}〙" in blank_text
    assert {entry["value"] for entry in blank["occurrences"] if entry["name"] == name} == {f"〘미입력·{name}〙"}
    assert ctrl.snapshot()["tabs"][0]["trial_state"] == "current"
    assert sorted(ctrl.snapshot()["tabs"][0]["trial_missing"]["fields"]) == sorted(field_names)
    # 실패한 시험(없는 항목 선택)은 내보낼 수 없다 — 결과는 최신 성공에만 묶인다.
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 0, "values": {}, "selected": {"없는 항목": "x"}})
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
        assert invalid["matches"] == [] and invalid["context"]["reason"] == "고른 위치가 유효하지 않습니다."


# ── 저작 UX 계약(#1015 후속): 명령 가용성·구조화 거절·준비 상태·문제 목록·영향·문법 보기 ──
def _structured_txt() -> str:
    source = "머리 {{이름}}\n본문\n차선\n끝\n"
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
    return structured


def test_locate_and_commands_carry_domain_availability_for_both_media(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt", "content": _structured_txt()})
    sid = opened["session_id"]
    picked = ctrl.dispatch("locate", {"session_id": sid, "revision": 0, "selection": {"start": 0, "end": 2}})
    by_type = {item["type"]: item for item in picked["commands"]}
    assert len(by_type) == 13 and set(by_type["create_field"]) == {"type", "enabled", "reason", "alternative"}
    assert by_type["create_field"]["enabled"] is True and by_type["create_field"]["reason"] is None
    assert by_type["rename_slot"] == {"type": "rename_slot", "enabled": False,
                                      "reason": "항목이나 선택 영역을 고르세요.", "alternative": None}
    assert by_type["create_option"]["alternative"] == {"label": "먼저 항목 만들기", "command_type": "create_slot"}
    standalone = ctrl.dispatch("commands", {"session_id": sid, "revision": 0,
                                            "selection": {"start": 0, "end": 2},
                                            "context": picked["context"]})
    assert standalone == {"commands": picked["commands"]}
    location = opened["analysis"]["slots"][0]["options"][0]["location"]
    inside = ctrl.dispatch("locate", {"session_id": sid, "revision": 0,
                                      "selection": {"start": location["content_start_offset"],
                                                    "end": location["content_start_offset"]}})
    # UX-10 R2: 문맥 줄은 담긴 항목/선택 이름과 사람이 읽는 행 범위다. 캐럿(빈 범위)에는 고른 문구가 없다.
    assert inside["context"] == {"slot_id": "항목1", "option_id": "안1", "reason": "",
                                 "location_label": "표시 / 안1 · 4행", "selected_text": None}
    assert {item["type"] for item in inside["commands"] if item["enabled"]} >= {"rename_slot", "rename_option", "unwrap"}
    invalid = ctrl.dispatch("locate", {"session_id": sid, "revision": 0, "selection": {"start": -1, "end": 0}})
    assert invalid["matches"] == [] and all(
        not item["enabled"] and item["reason"] == "고른 위치가 올바르지 않습니다." for item in invalid["commands"])
    with pytest.raises(ValueError):
        ctrl.dispatch("commands", {"session_id": sid, "revision": 0, "selection": {"start": 0}, "context": []})

    fixture = Path(__file__).parent / "fixtures" / "template_v1.hwpx"
    hwpx = ctrl.open_path(fixture)
    first = hwpx["analysis"]["fields"][0]["occurrences"][0]
    selection = {"entry": first["entry"], "paragraph": first["paragraph"],
                 "start_paragraph": first["paragraph"], "end_paragraph": first["paragraph"],
                 "start": 0, "end": 0}
    native = ctrl.dispatch("locate", {"session_id": hwpx["session_id"], "revision": 0, "selection": selection})
    assert [item["type"] for item in native["commands"]] == [item["type"] for item in picked["commands"]]
    assert next(item for item in native["commands"] if item["type"] == "rename_field")["enabled"] is True
    assert ctrl.dispatch("commands", {"session_id": hwpx["session_id"], "revision": 0,
                                      "selection": selection}) == {"commands": native["commands"]}


# ── #1021: 구조 목록·검색 대상은 좌표가 아니라 정체로 locate 한다(§3.3·§6.1·§6.2, AC18 두 형식 동일) ──
_TARGET_ENABLED = {
    "field": {"rename_field"},
    "occurrence": {"rename_field", "relink_field", "unset_field"},
    "slot": {"rename_slot", "adjust_range", "unwrap", "delete", "duplicate", "move"},
    "option": {"rename_slot", "rename_option", "adjust_range", "unwrap", "delete", "duplicate", "move"},
}


def _native_structured() -> str:
    from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE
    from hwpxfiller.external.hwpx_authoring import apply_hwpx

    hp = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    hs = "http://www.hancom.co.kr/hwpml/2011/section"
    entry = "Contents/section0.xml"
    package = HwpxPackage()
    package.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    package.stored.add(MIMETYPE_NAME)
    package.entries[entry] = (
        f'<hs:sec xmlns:hs="{hs}" xmlns:hp="{hp}">'
        '<hp:p><hp:run><hp:t>머리</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>본문 값</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p></hs:sec>'
    ).encode("utf-8")
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 1,
                         "start": 3, "end": 4, "name": "이름"})
    apply_hwpx(package, {"type": "create_slot", "entry": entry,
                         "start_paragraph": 0, "end_paragraph": 2, "id": "항목1", "label": "표시"})
    apply_hwpx(package, {"type": "create_option", "entry": entry,
                         "start_paragraph": 1, "end_paragraph": 1, "slot_id": "항목1", "id": "안1"})
    return base64.b64encode(package.to_bytes()).decode("ascii")


def _outline_targets(analysis: dict) -> dict[str, tuple[dict, dict]]:
    """구조 목록이 보내는 (정체, 좌표) — 필드 전체는 첫 사용 위치를 좌표로 싣는다(authoring_controller.select)."""
    field = analysis["fields"][0]
    slot = analysis["slots"][0]
    option = slot["options"][0]
    return {
        "field": ({"kind": "field", "name": field["name"]}, field["occurrences"][0]),
        "occurrence": ({"kind": "occurrence", "name": field["name"]}, field["occurrences"][0]),
        "slot": ({"kind": "slot", "slot_id": slot["id"]}, slot["location"]),
        "option": ({"kind": "option", "slot_id": slot["id"], "option_id": option["id"]},
                   option["location"]),
    }


@pytest.mark.parametrize("media", ["txt", "hwpx"])
def test_outline_targets_locate_by_identity_with_domain_availability(tmp_path: Path, media: str) -> None:
    ctrl = _controller(tmp_path)
    content = _structured_txt() if media == "txt" else _native_structured()
    opened = ctrl.dispatch("new", {"media": media, "content": content})
    sid = opened["session_id"]
    if media == "hwpx":
        assert ctrl.dispatch("rhwp_roundtrip_preflight", {"session_id": sid, "revision": 0,
                                                           "content": content})["editable"]
    located = {}
    for kind, (target, selection) in _outline_targets(opened["analysis"]).items():
        result = ctrl.dispatch("locate", {"session_id": sid, "revision": 0,
                                          "selection": selection, "target": target})
        located[kind] = result
        assert [item["type"] for item in result["commands"]] == list(COMMAND_TYPES)
        assert {item["type"] for item in result["commands"] if item["enabled"]} == _TARGET_ENABLED[kind], kind
        assert all(item["reason"] and item["reason"] != "고른 위치가 올바르지 않습니다."
                   for item in result["commands"] if not item["enabled"]), kind
    field = located["field"]
    assert field["selected"]["kind"] == "field" and field["selected"]["occurrences"]
    assert {item["type"]: item["reason"] for item in field["commands"]
            if item["type"] in {"relink_field", "unset_field", "create_field", "create_slot"}} == {
        "relink_field": "필드 사용 위치를 하나 고르세요.",
        "unset_field": "필드 사용 위치를 하나 고르세요.",
        "create_field": "고른 범위에 기존 필드가 포함되어 있습니다.",
        "create_slot": "문서에서 범위를 고르세요.",
    }
    slot_commands = {item["type"]: item for item in located["slot"]["commands"]}
    assert slot_commands["create_option"] == {
        "type": "create_option", "enabled": False, "alternative": None,
        "reason": "선택은 항목 안에 만들 수 있습니다. 먼저 항목 안의 내용을 고르세요."}
    assert slot_commands["rename_option"]["reason"] == "선택 영역을 고르세요."
    labels = {kind: located[kind]["context"].pop("location_label") for kind in ("slot", "option")}
    assert located["slot"]["context"] == {"slot_id": "항목1", "option_id": None, "reason": ""}
    assert located["option"]["context"] == {"slot_id": "항목1", "option_id": "안1", "reason": ""}
    # UX-10 R2: 항목의 문맥은 범위만, 선택의 문맥은 상위 항목 이름과 범위다(자기 이름은 대상 카드가 보인다).
    assert labels["slot"] == ("문단 1–3" if media == "hwpx" else "2–9행")
    assert labels["option"].startswith("표시 · ")
    assert located["option"]["selected"]["option_id"] == "안1"

    # 필드 전체 선택에서 곧바로 이름 변경 미리보기가 선다(U07/F17) — 우회 없이.
    name = opened["analysis"]["fields"][0]["name"]
    rename = ctrl.dispatch("preview", {"session_id": sid, "revision": 0, "command": {
        **field["selected"], "type": "rename_field", "old_name": name, "name": "새이름"}})
    assert rename["affected"] == 1 and "refusal" not in rename
    # 사용 위치 한 곳에서는 그 자리의 연결 변경이 선다.
    relink = ctrl.dispatch("preview", {"session_id": sid, "revision": 0, "command": {
        **located["occurrence"]["selected"], "type": "relink_field", "name": "다른필드"}})
    assert relink["affected"] == 1 and "refusal" not in relink
    # 되짚지 못하는 정체는 좌표 선택과 같은 무효다.
    for target in ({"kind": "field", "name": "없음"}, {"kind": "slot", "slot_id": "없음"},
                   {"kind": "option", "slot_id": "항목1", "option_id": "없음"}, {"kind": "text"},
                   {"kind": "occurrence", "name": name}):
        invalid = ctrl.dispatch("locate", {"session_id": sid, "revision": 0,
                                           "selection": {"start": 999, "end": 999}, "target": target})
        assert invalid["matches"] == [] and not any(item["enabled"] for item in invalid["commands"])
    with pytest.raises(ValueError):
        ctrl.dispatch("locate", {"session_id": sid, "revision": 0, "selection": {}, "target": "field"})


def test_hwpx_occurrence_target_reports_its_owner_and_template_field_is_renamable(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "hwpx", "content": _native_structured()})
    field = opened["analysis"]["fields"][0]
    occurrence = ctrl.dispatch("locate", {"session_id": opened["session_id"], "revision": 0,
                                          "selection": field["occurrences"][0],
                                          "target": {"kind": "occurrence", "name": field["name"]}})
    assert occurrence["context"] == {"slot_id": "항목1", "option_id": "안1", "reason": "",
                                     "location_label": "표시 / 안1 · 문단 2"}
    # 좌표 없는 누름틀(template_v1) — 좌표 locate 는 무효였지만 정체 locate 는 이름 변경을 연다.
    fixture = ctrl.open_path(Path(__file__).parent / "fixtures" / "template_v1.hwpx")
    first = fixture["analysis"]["fields"][0]
    whole = ctrl.dispatch("locate", {"session_id": fixture["session_id"], "revision": 0,
                                     "selection": first["occurrences"][0],
                                     "target": {"kind": "field", "name": first["name"]}})
    assert next(item for item in whole["commands"] if item["type"] == "rename_field")["enabled"] is True
    hits = ctrl.dispatch("search", {"session_id": fixture["session_id"], "revision": 0,
                                    "query": first["name"], "kind": "field"})["hits"]
    assert hits and all(hit["kind"] == "field" and hit["name"] == first["name"] for hit in hits)
    # 실 브리지 관문도 정체 키를 받는다 — 헤드리스 dispatch 는 이 관문 아래로 들어가므로 따로 잰다.
    from hwpxfiller.webapp.action_registry import validate_dispatch

    validate_dispatch("authoring", "locate", {"session_id": "s", "revision": 0, "selection": {},
                                              "target": {"kind": "field", "name": first["name"]}})


def test_preview_returns_structured_refusals_without_changing_content(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    fields = ctrl.dispatch("new", {"media": "txt", "content": "{{이름}} {{날짜}}"})
    conflict = ctrl.dispatch("preview", {"session_id": fields["session_id"], "revision": 0,
                                         "command": {"type": "rename_field", "old_name": "이름", "name": "날짜"}})
    assert conflict == {
        "ok": False, "session_id": fields["session_id"], "revision": 0,
        "refusal": {"code": "name_conflict", "name": "날짜", "existing_count": 1,
                    "message": "‘날짜’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요."},
    }
    assert ctrl.dispatch("content", {"session_id": fields["session_id"]})["content"] == "{{이름}} {{날짜}}"
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        ctrl.dispatch("preview", {"session_id": fields["session_id"], "revision": 0,
                                  "command": {"type": "rename_field", "old_name": "없음", "name": "새것"}})

    structured = ctrl.dispatch("new", {"media": "txt", "content": _structured_txt()})
    unwrap = {"type": "unwrap", "kind": "slot", "slot_id": "항목1"}
    cascade = ctrl.dispatch("preview", {"session_id": structured["session_id"], "revision": 0, "command": unwrap})
    assert cascade["ok"] is False and cascade["refusal"]["code"] == "cascade_required"
    assert [child["id"] for child in cascade["refusal"]["children"]] == ["안1", "안2"]
    assert cascade["refusal"]["message"] == "항목 의미를 해제하면 하위 선택 의미도 해제됩니다. 함께 해제를 확인하세요."
    confirmed = ctrl.dispatch("preview", {"session_id": structured["session_id"], "revision": 0,
                                          "command": {**unwrap, "cascade": True}})
    assert "refusal" not in confirmed and "{{#" not in confirmed["content"]
    assert confirmed["structure_delta"]["removed_slots"] == ["항목1"] and confirmed["body_changed"] is False


def test_readiness_and_save_notice_follow_structure_errors(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt", "content": "{{#항목 a}}\n본문\n"})
    sid = opened["session_id"]
    tab = ctrl.snapshot()["tabs"][0]
    errors = len([item for item in tab["analysis"]["diagnostics"] if item["severity"] == "error"])
    assert errors >= 1
    assert tab["readiness"] == {"state": "draft", "errors": errors, "warnings": 0,
                                "message": f"사용 전에 구조 오류 {errors}개를 확인하세요."}
    saved = ctrl.save_to_path(sid, 0, tmp_path / "draft.txt")
    assert saved["ok"] is True
    assert saved["notice"] == f"초안은 저장되었습니다. 사용 전에 구조 오류 {errors}개를 확인하세요."
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": "{{이름}}"})
    assert ctrl.snapshot()["tabs"][0]["readiness"] == {"state": "ready", "errors": 0, "warnings": 0, "message": None}
    assert ctrl.dispatch("save", {"session_id": sid, "revision": 1})["notice"] is None


def test_problems_are_template_defects_and_trial_gaps_project_to_trial_missing(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt", "content": _structured_txt()})
    sid = opened["session_id"]
    tab = ctrl.snapshot()["tabs"][0]
    assert tab["problems"] == opened["analysis"]["diagnostics"] == []
    # 시험 입력의 공백은 문제 목록이 아니라 결과 시험 탭의 trial_missing 이다(IDE-01) — 키 부재 = 손대지 않음.
    assert tab["trial_missing"] == {"fields": ["이름"], "slots": ["항목1"]}
    # 선택 공백은 지금처럼 시험 거절 사유다(상태 칩·문장), 문제 목록에는 서지 않는다.
    assert ctrl.dispatch("trial", {"session_id": sid, "revision": 0})["ok"] is False
    tab = ctrl.snapshot()["tabs"][0]
    assert tab["problems"] == [] and all(item.get("category") != "trial_input" for item in tab["problems"])
    assert tab["trial_state"] == "failed" and "시험 선택" in tab["trial_state_message"]
    # 필드 공백은 시험을 막지 않는다 — 빈 값 표식으로 렌더하고 empty_fields 로 알린다(결정 1(a)).
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 0, "values": {}, "selected": {"항목1": "안1"}})
    assert ctrl.snapshot()["tabs"][0]["trial_missing"] == {"fields": ["이름"], "slots": []}
    rendered = ctrl.dispatch("trial", {"session_id": sid, "revision": 0})
    assert rendered["report"] == {"missing_fields": [], "empty_fields": ["이름"]}
    assert rendered["text"].startswith("머리 〘미입력·이름〙\n")
    assert ctrl.snapshot()["tabs"][0]["trial_state"] == "current"
    # 빈 칸("")은 사용자가 손댄 값이다 — 공백 목록에서 빠지지만 결과는 같은 표식이다.
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 0, "values": {"이름": ""}, "selected": {"항목1": "안1"}})
    assert ctrl.snapshot()["tabs"][0]["trial_missing"] == {"fields": [], "slots": []}
    assert ctrl.dispatch("trial", {"session_id": sid, "revision": 0})["report"]["empty_fields"] == ["이름"]
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 0,
                                  "values": {"이름": "홍길동"}, "selected": {"항목1": "안1"}})
    assert ctrl.snapshot()["tabs"][0]["problems"] == []
    assert ctrl.snapshot()["tabs"][0]["analysis"]["diagnostics"] == []

    fixture = Path(__file__).parent / "fixtures" / "template_v1.hwpx"
    hwpx = ctrl.open_path(fixture)
    changed = HwpxPackage.from_bytes(fixture.read_bytes())
    changed.entries["Contents/header.xml"] = changed.entries["Contents/header.xml"].replace(b"paraPr", b"paraXX", 1)
    blocked = ctrl.dispatch("rhwp_roundtrip_preflight", {
        "session_id": hwpx["session_id"], "revision": 0,
        "content": base64.b64encode(changed.to_bytes()).decode("ascii")})
    ctrl.dispatch("trial_input", {"session_id": hwpx["session_id"], "revision": 0, "values": {}, "selected": {"없는 항목": "x"}})
    ctrl.dispatch("trial", {"session_id": hwpx["session_id"], "revision": 0})
    tab = next(item for item in ctrl.snapshot()["tabs"] if item["id"] == hwpx["session_id"])
    structural = len(tab["analysis"]["diagnostics"])
    assert len(tab["problems"]) == structural + 1 + len(blocked["diagnostics"])
    compat = tab["problems"][structural:]
    assert compat[0] == {"severity": "warning", "category": "compatibility",
                         "message": "이 요소는 표시할 수 있지만 변경 후 보존을 확인할 수 없습니다. 원본을 유지한 채 확인하세요.",
                         "target": None, "location": None, "actions": []}
    assert [(item["target"], item["message"]) for item in compat[1:]] == [
        (entry["entry"], entry["message"]) for entry in blocked["diagnostics"]]
    assert all(item["severity"] == "error" for item in tab["analysis"]["diagnostics"])
    # 상태 막대의 수는 문제 탭 배지와 같다 — 같은 problems 에서 센다(호환성 경고는 경고로만).
    readiness = tab["readiness"]
    assert readiness["errors"] + readiness["warnings"] == len(tab["problems"])
    assert readiness["warnings"] == len(compat)
    assert readiness["state"] == ("draft" if structural else "ready")


def test_trial_fill_names_fills_only_untouched_fields_in_one_input_transition(tmp_path: Path) -> None:
    path = tmp_path / "template.txt"
    path.write_text("{{다}} {{가}}\n{{나}} {{다}}\n", encoding="utf-8")
    ctrl = _controller(tmp_path)
    opened = ctrl.open_path(path)
    sid = opened["session_id"]
    assert ctrl.snapshot()["tabs"][0]["trial_missing"] == {"fields": ["다", "가", "나"], "slots": []}
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 0, "values": {"가": "기존", "나": ""}, "selected": {}})
    before = ctrl.sessions[sid].trial_input_revision
    filled = ctrl.dispatch("trial_fill_names", {"session_id": sid, "revision": 0})
    # 기존 값과 손댄 빈 칸은 그대로, 손대지 않은 필드만 그 이름을 받는다 — 한 번의 입력 전이다.
    assert filled["values"] == {"가": "기존", "나": "", "다": "다"} and filled["selected"] == {}
    assert filled["input_revision"] == before + 1 == ctrl.sessions[sid].trial_input_revision
    tab = ctrl.snapshot()["tabs"][0]
    assert tab["values"] == filled["values"] and tab["trial_missing"] == {"fields": [], "slots": []}
    # 시험 자료 입력이 바뀌었으므로 닫기 보호가 선다(저장하지 않은 시험 자료).
    assert tab["trial_inputs_dirty"] is True
    assert ctrl.dispatch("close", {"session_id": sid})["needs_confirm"] is True
    # 채울 필드가 없으면 거절한다 — 표면의 비활성과 같은 판정이고, 입력 전이는 없다.
    with pytest.raises(ValueError, match="시험 입력"):
        ctrl.dispatch("trial_fill_names", {"session_id": sid, "revision": 0})
    assert ctrl.sessions[sid].trial_input_revision == before + 1
    with pytest.raises(ValueError, match="변경"):
        ctrl.dispatch("trial_fill_names", {"session_id": sid, "revision": 5})


def test_export_result_name_marks_the_file_as_a_trial_copy(tmp_path: Path) -> None:
    path = tmp_path / "구매요청서.txt"
    path.write_text("{{이름}}", encoding="utf-8")
    ctrl = _controller(tmp_path)
    opened = ctrl.open_path(path)
    assert ctrl.export_result_name(opened["session_id"]) == "구매요청서_시험 결과.txt"
    fresh = ctrl.dispatch("new", {"media": "txt"})
    assert ctrl.export_result_name(fresh["session_id"]) == "새 템플릿_시험 결과.txt"


def test_preview_and_impact_report_structure_delta_and_body_change(tmp_path: Path) -> None:
    path = tmp_path / "template.txt"
    path.write_text(_structured_txt(), encoding="utf-8")
    job = SimpleNamespace(name="연결 작업", template_path=str(path), media="txt", template_fields=lambda: ["이름"])

    class Registry:
        def list_jobs(self, *, corrupted):
            return [job]

    class Change:
        def zone(self, name, media, missing):
            return {"source_drift": "changed", "actionable": True,
                    "preparation": {"status": "review-required"}}

    ctrl = AuthoringController(lambda _name, _snapshot: None, directory=tmp_path / "home",
                               job_registry=Registry(), template_change=Change())
    sid = ctrl.open_path(path)["session_id"]
    rename = ctrl.dispatch("preview", {"session_id": sid, "revision": 0,
                                       "command": {"type": "rename_slot", "kind": "slot",
                                                   "slot_id": "항목1", "id": "항목A"}})
    assert rename["structure_delta"] == {
        "added_slots": ["항목A"], "removed_slots": ["항목1"],
        "added_options": [["항목A", "안1"], ["항목A", "안2"]],
        "removed_options": [["항목1", "안1"], ["항목1", "안2"]],
        "renamed": [{"kind": "slot", "from": "항목1", "to": "항목A"}],
    }
    assert rename["body_changed"] is False
    delete = ctrl.dispatch("preview", {"session_id": sid, "revision": 0,
                                       "command": {"type": "delete", "kind": "option",
                                                   "slot_id": "항목1", "option_id": "안2"}})
    assert delete["body_changed"] is True
    assert delete["structure_delta"]["removed_options"] == [["항목1", "안2"]] and delete["structure_delta"]["renamed"] == []
    label_only = ctrl.dispatch("preview", {"session_id": sid, "revision": 0,
                                           "command": {"type": "rename_slot", "kind": "slot",
                                                       "slot_id": "항목1", "label": "다른 표시"}})
    assert label_only["structure_delta"]["renamed"] == [] and label_only["body_changed"] is False

    # 미리보기 내용을 그대로 확정하면 식별자 변경이 영향에 남는다; 저장이 원장을 비운다.
    ctrl.dispatch("preview", {"session_id": sid, "revision": 0,
                              "command": {"type": "rename_slot", "kind": "slot", "slot_id": "항목1", "id": "항목A"}})
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": rename["content"]})
    impact = ctrl.dispatch("impact", {"session_id": sid, "revision": 1})
    assert impact["usable"] is False and impact["content_changed_since_save"] is True
    assert impact["identifier_changes"] == [{"kind": "slot", "from": "항목1", "to": "항목A"}]
    assert impact["structure_delta"]["removed_slots"] == ["항목1"] and impact["structure_delta"]["added_slots"] == ["항목A"]
    assert impact["structure_delta"]["renamed"] == impact["identifier_changes"]
    assert impact["jobs"][0]["blocked_reason"] == "문서를 저장한 뒤 기존 작업에 적용하세요."
    assert impact["jobs"][0]["change_status"] == "review-required" and "change" in impact["jobs"][0]
    ctrl.dispatch("save", {"session_id": sid, "revision": 1})
    saved = ctrl.dispatch("impact", {"session_id": sid, "revision": 1})
    assert saved["usable"] is True and saved["jobs"][0]["blocked_reason"] is None
    assert saved["identifier_changes"] == [] and saved["content_changed_since_save"] is False
    assert saved["structure_delta"] == {"added_slots": [], "removed_slots": [], "added_options": [],
                                        "removed_options": [], "renamed": []}
    # 되돌려진 이름 변경(옛 식별자가 다시 있음)은 영향에서 빠진다.
    back = ctrl.dispatch("preview", {"session_id": sid, "revision": 1,
                                     "command": {"type": "rename_slot", "kind": "slot", "slot_id": "항목A", "id": "항목1"}})
    ctrl.dispatch("update", {"session_id": sid, "revision": 1, "content": back["content"]})
    ctrl.dispatch("update", {"session_id": sid, "revision": 2, "content": rename["content"]})
    assert ctrl.dispatch("impact", {"session_id": sid, "revision": 3})["identifier_changes"] == []
    # 구조 오류가 있으면 저장돼 있어도 사용 가능이 아니다.
    broken = ctrl.dispatch("update", {"session_id": sid, "revision": 3, "content": "{{#항목 a}}\n본문\n"})
    ctrl.dispatch("save", {"session_id": sid, "revision": broken["revision"]})
    draft = ctrl.dispatch("impact", {"session_id": sid, "revision": broken["revision"]})
    assert draft["usable"] is False and draft["jobs"][0]["blocked_reason"].startswith("사용 전에 구조 오류")


def test_syntax_view_for_both_media(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    text = ctrl.dispatch("new", {"media": "txt", "content": _structured_txt()})
    assert ctrl.dispatch("syntax", {"session_id": text["session_id"]}) == {
        "sections": [{"entry": "", "text": _structured_txt()}], "note": None}
    fixture = Path(__file__).parent / "fixtures" / "template_v1.hwpx"
    hwpx = ctrl.open_path(fixture)
    view = ctrl.dispatch("syntax", {"session_id": hwpx["session_id"]})
    name = hwpx["analysis"]["fields"][0]["name"]
    body = {section["entry"]: section["text"] for section in view["sections"]}
    assert set(body) >= set(hwpx["section_entries"]) and "note" in view
    assert "{{" + name + "}}" in body[hwpx["section_entries"][0]]
    assert ctrl.dispatch("content", {"session_id": hwpx["session_id"]})["content"] == hwpx["content"]


def test_close_guard_separates_document_and_test_material(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    path = tmp_path / "template.txt"
    path.write_text("{{이름}}", encoding="utf-8")
    sid = ctrl.open_path(path)["session_id"]
    assert ctrl.close_guard_reason() == ""
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": "{{이름}} 수정"})
    assert ctrl.dispatch("close", {"session_id": sid}) == {
        "needs_confirm": True, "document_dirty": True, "dirty": True,
        "cases_dirty": False, "trial_inputs_dirty": False}
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 1, "values": {"이름": "값"}, "selected": {}})
    assert ctrl.dispatch("close", {"session_id": sid})["cases_dirty"] is True
    assert ctrl.close_guard_reason() == "저작 작업대: 미저장 문서 1개 · 시험 자료 1개"
    assert ctrl.dispatch("close", {"session_id": sid, "force": True}) == {"ok": True}


def _tab(ctrl: AuthoringController, sid: str) -> dict:
    return next(item for item in ctrl.snapshot()["tabs"] if item["id"] == sid)


def test_reopen_restores_last_position_and_mode_from_the_app_home(tmp_path: Path) -> None:
    """U02: 최근 작업 위치·표시 방식은 앱 홈에 문서별로 남고, 재시작 뒤 같은 문서에서 복원된다."""
    path = tmp_path / "template.txt"
    path.write_text("😀 {{이름}} 끝", encoding="utf-8")
    before = path.read_bytes()
    ctrl = _controller(tmp_path)
    sid = ctrl.open_path(path)["session_id"]
    assert _tab(ctrl, sid)["restore"] is None
    remembered = ctrl.dispatch("remember_view", {"session_id": sid, "revision": 0, "mode": "structure",
                                                 "selection": {"start": 3, "end": 9}})
    assert remembered == {"stored": True}
    assert path.read_bytes() == before, "작업 위치는 템플릿 파일에 들어가지 않는다"
    ctrl.dispatch("close", {"session_id": sid})

    restarted = _controller(tmp_path)
    reopened = restarted.open_path(path)["session_id"]
    expected = {"state": "restored", "mode": "structure", "selection": {"start": 3, "end": 9},
                "message": None}
    assert _tab(restarted, reopened)["restore"] == expected
    assert restarted.dispatch("activate", {"session_id": reopened})["restore"] == expected
    # 다시 연 문서에서 커서가 비면 기록도 새 값으로 바뀐다(마지막 값이 이긴다).
    restarted.dispatch("remember_view", {"session_id": reopened, "revision": 0, "mode": "document",
                                         "selection": {}})
    third = _controller(tmp_path)
    assert _tab(third, third.open_path(path)["session_id"])["restore"] == {
        "state": "restored", "mode": "document", "selection": None, "message": None}


def test_restore_drops_coordinates_when_the_document_changed_since_they_were_taken(tmp_path: Path) -> None:
    path = tmp_path / "template.txt"
    path.write_text("{{이름}}", encoding="utf-8")
    ctrl = _controller(tmp_path)
    sid = ctrl.open_path(path)["session_id"]
    # 미저장 편집 위에서 잡은 좌표는 그 편집 내용의 것이다 — 저장하지 않고 닫으면 파일과 어긋난다.
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": "{{이름}} 아주 긴 추가 문장"})
    ctrl.dispatch("remember_view", {"session_id": sid, "revision": 1, "mode": "structure",
                                    "selection": {"start": 12, "end": 14}})
    ctrl.dispatch("close", {"session_id": sid, "force": True})
    stale = _controller(tmp_path)
    reopened = stale.open_path(path)["session_id"]
    assert _tab(stale, reopened)["restore"] == {
        "state": "stale", "mode": "structure", "selection": None,
        "message": "마지막 작업 이후 문서가 바뀌어 작업 위치를 복원하지 않았습니다."}

    # 외부 프로그램이 파일을 바꾼 경우도 같다.
    stale.dispatch("remember_view", {"session_id": reopened, "revision": 0, "mode": "template",
                                     "selection": {"start": 0, "end": 2}})
    stale.dispatch("close", {"session_id": reopened})
    path.write_text("외부에서 바뀐 {{이름}}", encoding="utf-8")
    outside = _controller(tmp_path)
    assert _tab(outside, outside.open_path(path)["session_id"])["restore"]["state"] == "stale"


def test_unreadable_or_out_of_range_positions_are_diagnosed_not_ignored(tmp_path: Path) -> None:
    path = tmp_path / "template.txt"
    path.write_text("{{이름}}", encoding="utf-8")
    ctrl = _controller(tmp_path)
    record = tmp_path / "home" / "workspace" / f"{ctrl.store.key(path)}.json"
    record.parent.mkdir(parents=True)
    fingerprint = digest(path.read_bytes())
    for payload in (
        "{",
        json.dumps({"version": 9, "fingerprint": fingerprint, "mode": "template", "selection": None}),
        json.dumps({"version": 1, "fingerprint": fingerprint, "mode": "표", "selection": None}),
        json.dumps({"version": 1, "fingerprint": fingerprint, "mode": "template",
                    "selection": {"start": 0, "end": 99}}),
        json.dumps({"version": 1, "fingerprint": fingerprint, "mode": "template",
                    "selection": {"start": 0, "end": 1, "extra": True}}),
    ):
        record.write_text(payload, encoding="utf-8")
        fresh = _controller(tmp_path)
        restore = _tab(fresh, fresh.open_path(path)["session_id"])["restore"]
        assert restore["state"] == "unreadable" and restore["selection"] is None, payload
        assert restore["message"].startswith("최근 작업 위치를 읽을 수 없습니다: "), restore


def test_remember_view_refuses_bad_input_and_skips_pathless_or_stale_sessions(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    new = ctrl.dispatch("new", {"media": "txt", "content": "본문"})["session_id"]
    assert ctrl.dispatch("remember_view", {"session_id": new, "revision": 0, "mode": "template",
                                           "selection": {"start": 0, "end": 1}}) == {"stored": False}
    assert not (tmp_path / "home" / "workspace").exists()
    path = tmp_path / "template.txt"
    path.write_text("본문", encoding="utf-8")
    sid = ctrl.open_path(path)["session_id"]
    assert ctrl.dispatch("remember_view", {"session_id": sid, "revision": 7, "mode": "template",
                                           "selection": {"start": 0, "end": 1}}) == {"stored": False}
    for mode, selection in (("표", {"start": 0, "end": 1}), ("template", {"start": -1, "end": 1}),
                            ("template", {"start": True, "end": 1}), ("template", {"end": 1}),
                            ("template", {"start": 0, "end": 1, "entry": 3}),
                            ("template", {"start": 0, "end": 1, "cell_path": []}),
                            ("template", "0-1")):
        with pytest.raises(ValueError):
            ctrl.dispatch("remember_view", {"session_id": sid, "revision": 0, "mode": mode,
                                            "selection": selection})
    with pytest.raises(ValueError):
        ctrl.dispatch("remember_view", {"session_id": sid, "revision": "0", "mode": "template",
                                        "selection": {}})


def test_hwpx_positions_restore_with_section_coordinates(tmp_path: Path) -> None:
    fixture = tmp_path / "template.hwpx"
    fixture.write_bytes((Path(__file__).parent / "fixtures" / "template_v1.hwpx").read_bytes())
    ctrl = _controller(tmp_path)
    opened = ctrl.open_path(fixture)
    entry = opened["section_entries"][0]
    selection = {"entry": entry, "paragraph": 0, "start_paragraph": 0, "end_paragraph": 0,
                 "start": 1, "end": 2,
                 "cell_path": [{"parent_paragraph": 0, "control": 0, "cell": 1, "paragraph": 0}]}
    assert ctrl.dispatch("remember_view", {"session_id": opened["session_id"], "revision": 0,
                                           "mode": "template", "selection": selection}) == {"stored": True}
    again = _controller(tmp_path)
    assert _tab(again, again.open_path(fixture)["session_id"])["restore"]["selection"] == selection
    record = tmp_path / "home" / "workspace" / f"{ctrl.store.key(fixture)}.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["selection"]["entry"] = "Contents/없는.xml"
    record.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    broken = _controller(tmp_path)
    assert _tab(broken, broken.open_path(fixture)["session_id"])["restore"]["state"] == "unreadable"


def test_compatibility_projection_is_pushed_the_moment_python_judges(tmp_path: Path) -> None:
    """U01·§7.1: 보존 판정은 Python 이 내리는 즉시 스냅샷에 선다 — 편집기 마운트를 기다리지 않는다."""
    pushes: list[dict] = []
    ctrl = AuthoringController(lambda _name, snapshot: pushes.append(snapshot), directory=tmp_path / "home")
    txt = ctrl.dispatch("new", {"media": "txt", "content": "본문"})["session_id"]
    assert _tab(ctrl, txt)["compatibility"]["state"] == "not_applicable"
    fixture = Path(__file__).parent / "fixtures" / "template_v1.hwpx"
    opened = ctrl.open_path(fixture)
    sid = opened["session_id"]
    assert _tab(ctrl, sid)["compatibility"] == {
        "state": "checking", "editable": False, "message": None, "diagnostics": []}
    changed = HwpxPackage.from_bytes(fixture.read_bytes())
    changed.entries["Contents/header.xml"] = changed.entries["Contents/header.xml"].replace(
        b"paraPr", b"paraXX", 1)
    pushes.clear()
    ctrl.dispatch("rhwp_roundtrip_preflight", {
        "session_id": sid, "revision": 0,
        "content": base64.b64encode(changed.to_bytes()).decode("ascii")})
    pushed = next(item for item in pushes[-1]["tabs"] if item["id"] == sid)
    assert pushed["compatibility"]["state"] == "limited"
    assert pushed["compatibility"]["message"] == (
        "이 요소는 표시할 수 있지만 변경 후 보존을 확인할 수 없습니다. 원본을 유지한 채 확인하세요.")
    assert pushed["compatibility"]["diagnostics"][0]["entry"] == "Contents/header.xml"
    assert any(problem["category"] == "compatibility" for problem in pushed["problems"])
    ctrl.dispatch("rhwp_roundtrip_preflight", {"session_id": sid, "revision": 0,
                                               "content": opened["content"]})
    assert _tab(ctrl, sid)["compatibility"]["state"] == "editable"


def test_editor_mount_failure_locks_editing_and_keeps_the_guidance(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    fixture = Path(__file__).parent / "fixtures" / "template_v1.hwpx"
    opened = ctrl.open_path(fixture)
    sid = opened["session_id"]
    ctrl.dispatch("rhwp_roundtrip_preflight", {"session_id": sid, "revision": 0,
                                               "content": opened["content"]})
    # 판정이 통과였어도 편집기가 뒤이어 무너지면 수정은 잠긴다(판정 없는 편집 금지).
    assert ctrl.dispatch("rhwp_unverified", {"session_id": sid, "revision": 0,
                                             "detail": "Error: studio 적재 실패"}) == {"applied": True}
    tab = _tab(ctrl, sid)
    assert tab["rhwp_editable"] is False and tab["compatibility"]["state"] == "limited"
    assert tab["compatibility"]["diagnostics"] == [{
        "kind": "preflight_unavailable", "message": "HWPX 보존 검사를 실행할 수 없습니다.",
        "detail": "Error: studio 적재 실패"}]
    assert [p["message"] for p in tab["problems"] if p["category"] == "compatibility"] == [
        "이 요소는 표시할 수 있지만 변경 후 보존을 확인할 수 없습니다. 원본을 유지한 채 확인하세요.",
        "HWPX 보존 검사를 실행할 수 없습니다."]
    with pytest.raises(ValueError, match="보존 검증"):
        ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": opened["content"]})
    # 원본 보존 경로: 다른 이름으로 저장은 원본 그대로의 사본을 쓴다.
    assert ctrl.save_to_path(sid, 0, tmp_path / "copy.hwpx")["ok"] is True
    assert (tmp_path / "copy.hwpx").read_bytes() == fixture.read_bytes()
    # 다시 연(revision 이 오른) 뒤 옛 편집기의 늦은 보고는 새 판정을 덮지 않는다.
    reloaded = ctrl.dispatch("reload", {"session_id": sid, "revision": 0, "force": True})
    assert _tab(ctrl, sid)["compatibility"]["state"] == "checking"
    assert ctrl.dispatch("rhwp_unverified", {"session_id": sid, "revision": reloaded["revision"] - 1,
                                             "detail": "늦은 보고"}) == {"applied": False}
    assert _tab(ctrl, sid)["compatibility"]["state"] == "checking"
    txt = ctrl.dispatch("new", {"media": "txt", "content": "본문"})["session_id"]
    with pytest.raises(ValueError, match="HWPX"):
        ctrl.dispatch("rhwp_unverified", {"session_id": txt, "revision": 0, "detail": ""})
    with pytest.raises(ValueError):
        ctrl.dispatch("rhwp_unverified", {"session_id": sid, "revision": reloaded["revision"],
                                          "detail": 3})


def test_read_only_actions_do_not_repush_an_unchanged_snapshot(tmp_path: Path) -> None:
    """UX-05: locate·commands 같은 읽기 동작은 같은 판을 다시 밀지 않는다 — 바뀐 동작만 나간다."""
    pushes: list[dict] = []
    ctrl = AuthoringController(lambda _name, snapshot: pushes.append(snapshot), directory=tmp_path / "home")
    path = tmp_path / "example.txt"
    path.write_text("이름 본문", encoding="utf-8")
    sid = ctrl.open_path(path)["session_id"]
    assert len(pushes) == 1
    selection = {"start": 0, "end": 2}
    ctrl.dispatch("locate", {"session_id": sid, "revision": 0, "selection": selection})
    ctrl.dispatch("commands", {"session_id": sid, "revision": 0, "selection": selection, "context": {}})
    ctrl.dispatch("search", {"session_id": sid, "revision": 0, "query": "이름", "kind": "body"})
    assert ctrl.dispatch("check_external", {"session_id": sid})["changed"] is False
    assert len(pushes) == 1
    # 읽기 동작이라도 상태를 바꿨으면 나간다 — 외부 변경을 발견한 check_external.
    path.write_text("외부 편집", encoding="utf-8")
    assert ctrl.dispatch("check_external", {"session_id": sid})["changed"] is True
    assert len(pushes) == 2
    assert pushes[-1]["tabs"][0]["external_changed"] is True
    ctrl.dispatch("check_external", {"session_id": sid})
    assert len(pushes) == 2
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": "{{이름}} 본문"})
    assert len(pushes) == 3
    assert pushes[-1]["tabs"][0]["revision"] == 1


def test_undelivered_push_is_not_remembered_as_sent(tmp_path: Path) -> None:
    """전달 실패로 판정된 push 는 지문을 남기지 않는다 — 다음 동작이 같은 판을 다시 보낸다."""
    delivered: list[bool] = []
    outcomes = iter([SimpleNamespace(ok=False), SimpleNamespace(ok=True), SimpleNamespace(ok=True)])

    def sink(_name: str, _snapshot: dict) -> object:
        outcome = next(outcomes)
        delivered.append(outcome.ok)
        return outcome

    ctrl = AuthoringController(sink, directory=tmp_path / "home")
    sid = ctrl.dispatch("new", {"media": "txt", "content": "본문"})["session_id"]
    ctrl.dispatch("content", {"session_id": sid})
    ctrl.dispatch("content", {"session_id": sid})
    assert delivered == [False, True]


def test_trial_result_and_analysis_carry_revisions_that_change_only_with_the_object(tmp_path: Path) -> None:
    """UX-05: 시험 결과·분석의 revision 은 같은 객체의 재투영에서 그대로이고 새 객체에서만 오른다."""
    ctrl = _controller(tmp_path)
    fixture = Path(__file__).parent / "fixtures" / "template_v1.hwpx"
    opened = ctrl.open_path(fixture)
    sid = opened["session_id"]
    ctrl.dispatch("rhwp_roundtrip_preflight", {"session_id": sid, "revision": 0, "content": opened["content"]})
    name = opened["analysis"]["fields"][0]["name"]
    assert _tab(ctrl, sid)["trial_result"] is None
    analysis = _tab(ctrl, sid)["analysis"]["revision"]
    assert "revision" not in ctrl.sessions[sid].analysis
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 0, "values": {name: "검토값"}, "selected": {}})
    result = ctrl.dispatch("trial", {"session_id": sid, "revision": 0})
    assert result["revision"] == 0  # 디스패치 반환의 revision 은 여전히 문서 revision 이다.
    first = _tab(ctrl, sid)["trial_result"]
    assert first["content"] == result["content"]
    assert "revision" not in (ctrl.sessions[sid].trial_result or {})
    assert _tab(ctrl, sid)["trial_result"]["revision"] == first["revision"]
    assert _tab(ctrl, sid)["analysis"]["revision"] == analysis
    ctrl.dispatch("trial", {"session_id": sid, "revision": 0})
    second = _tab(ctrl, sid)["trial_result"]["revision"]
    assert second > first["revision"]
    txt = ctrl.dispatch("new", {"media": "txt", "content": "본문"})["session_id"]
    before = _tab(ctrl, txt)["analysis"]["revision"]
    ctrl.dispatch("update", {"session_id": txt, "revision": 0, "content": "{{이름}}"})
    assert _tab(ctrl, txt)["analysis"]["revision"] > before
    assert _tab(ctrl, txt)["analysis"]["revision"] != _tab(ctrl, sid)["analysis"]["revision"]


# ── U09: 문서 척추(구조 보기)를 위한 사용 위치 소속·문서 순서·위치 문구 투영 ──
def _outline_txt_content() -> str:
    """항목(2 선택) 안팎에 걸친 필드 — 「단가」는 두 선택 모두에 있고, 바깥 필드는 앞뒤에 하나씩."""
    source = "안내 문구\n저가안 단가값1\n고가안 단가값2\n끝 문구\n"
    structured, _ = apply_txt("txt", source, {
        "type": "create_slot", "start": source.index("저가안"),
        "end": source.index("고가안") + len("고가안 단가값2"), "id": "항목", "label": "가격",
    })
    structured, _ = apply_txt("txt", structured, {
        "type": "create_option", "start": structured.index("저가안"),
        "end": structured.index("저가안") + len("저가안 단가값1"), "slot_id": "항목", "id": "저가",
    })
    structured, _ = apply_txt("txt", structured, {
        "type": "create_option", "start": structured.index("고가안"),
        "end": structured.index("고가안") + len("고가안 단가값2"), "slot_id": "항목", "id": "고가",
    })
    idx = structured.index("안내 ") + len("안내 ")
    structured, _ = apply_txt("txt", structured, {
        "type": "create_field", "start": idx, "end": idx + len("문구"), "name": "바깥앞",
    })
    idx = structured.index("단가값1")
    structured, _ = apply_txt("txt", structured, {
        "type": "create_field", "start": idx, "end": idx + len("단가값1"), "name": "단가",
    })
    idx = structured.index("단가값2")
    structured, _ = apply_txt("txt", structured, {
        "type": "create_field", "start": idx, "end": idx + len("단가값2"), "name": "단가",
    })
    idx = structured.index("끝 ") + len("끝 ")
    structured, _ = apply_txt("txt", structured, {
        "type": "create_field", "start": idx, "end": idx + len("문구"), "name": "바깥뒤",
    })
    return structured


def test_outline_projection_orders_the_document_spine_for_txt(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt", "content": _outline_txt_content()})
    sid = opened["session_id"]
    raw = ctrl.sessions[sid].analysis
    analysis = _tab(ctrl, sid)["analysis"]

    slot = analysis["slots"][0]
    cheap, pricey = slot["options"]
    fields = {field["name"]: field for field in analysis["fields"]}
    price = fields["단가"]["occurrences"]
    outer_before = fields["바깥앞"]["occurrences"][0]
    outer_after = fields["바깥뒤"]["occurrences"][0]

    assert (price[0]["slot_id"], price[0]["option_id"]) == ("항목", "저가")
    assert (price[1]["slot_id"], price[1]["option_id"]) == ("항목", "고가")
    assert outer_before["slot_id"] is None and outer_before["option_id"] is None
    assert outer_after["slot_id"] is None and outer_after["option_id"] is None

    assert slot["location_label"] == "2–9행"
    assert cheap["location_label"] == "3–5행"
    assert pricey["location_label"] == "6–8행"

    ordered = sorted(
        [outer_before, slot, cheap, price[0], pricey, price[1], outer_after],
        key=lambda item: item["order"],
    )
    assert [item.get("name") or item.get("id") for item in ordered] == [
        "바깥앞", "항목", "저가", "단가", "고가", "단가", "바깥뒤",
    ]
    assert [item["order"] for item in ordered] == list(range(7))

    # session.analysis 자체는 손대지 않는다 — 투영은 별도 사본이다.
    assert "order" not in raw["slots"][0] and "location_label" not in raw["slots"][0]
    assert "order" not in raw["slots"][0]["options"][0]
    assert "order" not in raw["fields"][0]["occurrences"][0]


def _native_outline_content() -> str:
    """본문 밖 필드·항목 안 본문 필드·항목 안 표 셀 필드를 갖춘 HWPX 본문(base64)."""
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
        '<hp:p><hp:run><hp:t>머리 안내값</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>본문</hp:t></hp:run>'
        '<hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>'
        '<hp:p><hp:run><hp:t>표값</hp:t></hp:run></hp:p>'
        '</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>본문값</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p></hs:sec>'
    ).encode("utf-8")
    cell_path = [{"parent_paragraph": 1, "control": 0, "cell": 0, "paragraph": 0}]
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 0,
                         "start": 3, "end": 6, "name": "바깥"})
    apply_hwpx(package, {"type": "create_field", "entry": entry, "cell_path": cell_path,
                         "paragraph": 0, "start": 0, "end": 2, "name": "표단가"})
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 2,
                         "start": 0, "end": 3, "name": "본단가"})
    apply_hwpx(package, {"type": "create_slot", "entry": entry,
                         "start_paragraph": 1, "end_paragraph": 2, "id": "슬롯", "label": "표시"})
    apply_hwpx(package, {"type": "create_option", "entry": entry,
                         "start_paragraph": 1, "end_paragraph": 2, "slot_id": "슬롯", "id": "옵션"})
    return base64.b64encode(package.to_bytes()).decode("ascii")


def test_outline_projection_orders_the_document_spine_for_hwpx(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "hwpx", "content": _native_outline_content()})
    sid = opened["session_id"]
    raw = ctrl.sessions[sid].analysis
    analysis = _tab(ctrl, sid)["analysis"]

    slot = analysis["slots"][0]
    option = slot["options"][0]
    fields = {field["name"]: field["occurrences"][0] for field in analysis["fields"]}
    outer = fields["바깥"]
    cell = fields["표단가"]
    body = fields["본단가"]

    assert outer["anchor_paragraph"] == 0
    assert cell["anchor_paragraph"] == 1
    assert body["anchor_paragraph"] == 2
    assert outer["slot_id"] is None and outer["option_id"] is None
    assert (cell["slot_id"], cell["option_id"]) == ("슬롯", "옵션")
    assert (body["slot_id"], body["option_id"]) == ("슬롯", "옵션")

    assert slot["location_label"] == "문단 2–3"
    assert option["location_label"] == "문단 2–3"

    labeled = {id(outer): "바깥", id(slot): "슬롯", id(option): "옵션",
               id(cell): "표단가", id(body): "본단가"}
    ordered = sorted([outer, slot, option, cell, body], key=lambda item: item["order"])
    assert [labeled[id(item)] for item in ordered] == ["바깥", "슬롯", "옵션", "표단가", "본단가"]
    assert [item["order"] for item in ordered] == list(range(5))

    assert "anchor_paragraph" in raw["fields"][0]["occurrences"][0]  # HWPX 분석기가 낸 원본 키
    assert "slot_id" not in raw["fields"][0]["occurrences"][0]
    assert "order" not in raw["slots"][0]


def test_outline_projection_is_cached_until_analysis_is_replaced(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt", "content": "머리 {{이름}}\n"})
    sid = opened["session_id"]
    first_slots = _tab(ctrl, sid)["analysis"]["slots"]
    second_slots = _tab(ctrl, sid)["analysis"]["slots"]
    assert first_slots is second_slots  # 같은 analysis 객체 → 재사용, 다시 짓지 않는다.
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": "새 {{이름}}\n"})
    third_slots = _tab(ctrl, sid)["analysis"]["slots"]
    assert third_slots is not first_slots  # update 가 analysis 객체를 바꿨다 → 다시 짓는다.
