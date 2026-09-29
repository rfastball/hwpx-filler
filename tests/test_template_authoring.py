"""Pure authoring boundary: one edit plan, structure safety, trial provenance."""

from __future__ import annotations

import pytest

from hwpxfiller.domain.template_authoring import (
    COMMAND_TYPES,
    CascadeRequired,
    InvalidName,
    NameConflict,
    analyze,
    apply,
    available_commands,
    confirm_tier,
    created_target,
    preview,
    suggest_field_name,
    trial,
    trial_document_values,
)
from hwpxfiller.domain.job import MISSING_MARKER
from hwpxfiller.external.text_materialization_conformance import trial_txt_authoring
from hwpxfiller.external.authoring_transfer import capture_semantic, paste_semantic


def test_field_commands_preserve_occurrence_scope_and_utf16_offsets() -> None:
    source = "😀 이름 {{이름}}"
    result, plan = apply("txt", source, {"type": "create_field", "start": 3, "end": 5, "name": "이름"})
    assert result == "😀 {{이름}} {{이름}}"
    assert plan["edits"] == [{"start": 3, "end": 5, "text": "{{이름}}"}]
    result, plan = apply("txt", result, {"type": "rename_field", "old_name": "이름", "name": "성명"})
    assert result == "😀 {{성명}} {{성명}}"
    assert plan["affected"] == 2
    result, _ = apply("txt", result, {"type": "relink_field", "start": 4, "name": "담당자"})
    assert result == "😀 {{담당자}} {{성명}}"
    with pytest.raises(NameConflict) as conflict:
        preview("txt", "{{성명}} {{담당자}} {{담당자}}",
                {"type": "rename_field", "old_name": "성명", "name": "담당자"})
    assert conflict.value.to_dict() == {
        "code": "name_conflict", "name": "담당자", "existing_count": 2,
        "message": "‘담당자’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요."}
    assert plan["label"] == "‘이름’ 이름 변경" and plan["before"] == "이름" and plan["after"] == "성명"


def test_txt_create_field_links_existing_name_and_lists_candidates() -> None:
    source = "{{이름}} 값 {{주소}}\n"
    fresh = preview("txt", source, {"type": "create_field", "start": 7, "end": 8, "name": "연락처"})
    assert (fresh["links_existing"], fresh["existing_count"]) == (False, 0)
    assert fresh["candidates"] == [{"name": "이름", "count": 1}, {"name": "주소", "count": 1}]
    assert fresh["label"] == "‘연락처’를 필드로 만들기"
    linked = preview("txt", source, {"type": "create_field", "start": 7, "end": 8, "name": "이름"})
    assert (linked["links_existing"], linked["existing_count"]) == (True, 1)
    assert linked["result"]["fields"][0]["count"] == 2 and linked["label"] == "‘이름’을 필드로 만들기"


def _slot_template() -> str:
    base = "머리\n공통 {{F}}\n첫째\n둘째\n끝\n"
    base, _ = apply("txt", base, {"type": "create_slot", "start": base.index("공통"),
                                  "end": base.index("끝"), "id": "s", "label": "특약"})
    base, _ = apply("txt", base, {"type": "create_option", "start": base.index("첫째"),
                                  "end": base.index("첫째") + 2, "slot_id": "s", "id": "a"})
    base, _ = apply("txt", base, {"type": "create_option", "start": base.index("둘째"),
                                  "end": base.index("둘째") + 2, "slot_id": "s", "id": "b", "label": "둘"})
    return base


def test_txt_region_previews_show_children_counts_text_and_labels() -> None:
    base = _slot_template()
    region = base[base.index("{{#항목"):base.index("{{/항목}}") + len("{{/항목}}\n")]
    unwrap = preview("txt", base, {"type": "unwrap", "kind": "slot", "slot_id": "s"})
    assert unwrap["requires_cascade"] is True
    assert [(child["kind"], child["id"], child["label"]) for child in unwrap["children"]] == [
        ("option", "a", "a"), ("option", "b", "둘"), ("field", "F", "F")]
    assert unwrap["counts"] == {"paragraphs": 3, "fields": 1, "options": 2, "tables": 0}
    assert unwrap["included"] == region and unwrap["before"] == region
    assert unwrap["after"] == "공통 {{F}}\n첫째\n둘째\n"
    assert unwrap["label"] == "‘특약’ 항목 의미만 해제"
    with pytest.raises(CascadeRequired) as refused:
        apply("txt", base, {"type": "unwrap", "kind": "slot", "slot_id": "s"})
    assert [child["id"] for child in refused.value.to_dict()["children"]] == ["a", "b"]
    cascaded = preview("txt", base, {"type": "unwrap", "kind": "slot", "slot_id": "s", "cascade": True})
    assert cascaded["requires_cascade"] is False and cascaded["edits"] == unwrap["edits"]
    deleted = preview("txt", base, {"type": "delete", "kind": "option", "slot_id": "s", "option_id": "b"})
    assert deleted["before"] == "{{#선택 b 둘}}\n둘째\n{{/선택}}\n" and deleted["after"] == ""
    assert deleted["counts"]["paragraphs"] == 1 and deleted["label"] == "‘둘’ 선택 내용까지 삭제"
    moved = preview("txt", base, {"type": "move", "kind": "slot", "slot_id": "s", "destination": 0})
    assert moved["before"] == region and moved["after"] == region and moved["label"] == "‘특약’ 항목 이동"
    copied = preview("txt", base, {"type": "duplicate", "kind": "slot", "slot_id": "s",
                                   "new_id": "s2", "destination": len(base)})
    assert copied["after"].startswith("{{#항목 s2}}") and copied["included"] == region
    renamed = preview("txt", base, {"type": "rename_option", "kind": "option", "slot_id": "s",
                                    "option_id": "a", "id": "first"})
    assert (renamed["before"], renamed["after"]) == ("{{#선택 a}}\n", "{{#선택 first}}\n")
    assert deleted["children"] == [] and deleted["counts"]["options"] == 0
    adjusted = preview("txt", base, {"type": "adjust_range", "kind": "slot", "slot_id": "s",
                                     "start": 0, "end": base.index("끝")})
    assert adjusted["included"].startswith("머리\n") and adjusted["before"] == region
    assert adjusted["counts"]["paragraphs"] == 4 and adjusted["label"] == "‘특약’ 범위 조정"
    unset = preview("txt", base, {"type": "unset_field", "start": base.index("{{F}}") + 1, "text": "값"})
    assert (unset["before"], unset["after"], unset["label"]) == ("{{F}}", "값", "‘F’ 필드 의미 해제")
    for command in ({"type": "create_slot", "start": 0, "end": 1, "id": "top"},
                    {"type": "rename_slot", "kind": "slot", "slot_id": "s", "id": "terms"}):
        assert preview("txt", base, command)["label"]


def test_txt_preview_included_location_is_the_expanded_or_target_range() -> None:
    """IDE-06 P-16: 편집면이 미리보기 동안 칠할 실제 범위 — 넓힌 줄 전체 또는 대상 영역(UTF-16 좌표)."""
    source = "머리\n본문 한 줄\n끝\n"
    line = source.index("본문")
    partial = preview("txt", source, {"type": "create_slot", "start": line + 1, "end": line + 3, "id": "s"})
    assert partial["expanded"] is True
    assert partial["included_location"] == {"start": line, "end": source.index("끝")}
    base = _slot_template()
    region = base[base.index("{{#항목 s"):base.index("끝")]
    for command in ({"type": "unwrap", "kind": "slot", "slot_id": "s", "cascade": True},
                    {"type": "delete", "kind": "slot", "slot_id": "s"},
                    {"type": "rename_slot", "kind": "slot", "slot_id": "s", "id": "t"}):
        assert preview("txt", base, command)["included_location"] == {
            "start": base.index(region), "end": base.index(region) + len(region)}, command["type"]
    adjusted = preview("txt", base, {"type": "adjust_range", "kind": "slot", "slot_id": "s",
                                     "start": 0, "end": base.index("끝")})
    assert adjusted["included_location"] == {"start": 0, "end": base.index("끝")}
    assert preview("txt", base, {"type": "unset_field", "start": base.index("{{F}}") + 1,
                                 "text": "값"})["included_location"] is None


def test_txt_whole_field_unset_replaces_every_occurrence_in_one_plan() -> None:
    """IDE-06 P-20: 필드 전체(occurrences 를 실은 대상)의 해제는 모든 사용 위치를 한 계획으로 치환한다."""
    source = "가 {{F}}\n{{G}} 나 {{F}}\n끝 {{F}}\n"
    occurrences = analyze("txt", source)["fields"][0]["occurrences"]
    command = {"type": "unset_field", "old_name": "F", "name": "F", "occurrences": occurrences,
               "start": occurrences[0]["start"], "end": occurrences[0]["end"], "text": "값"}
    projected = preview("txt", source, command)
    assert projected["affected"] == 3 and len(projected["edits"]) == 3
    assert projected["label"] == "‘F’ 필드 의미 해제"
    assert projected["included"] == [item["context"] for item in occurrences]
    assert (projected["before"], projected["after"]) == ("{{F}}", "값")
    assert [field["name"] for field in projected["result"]["fields"]] == ["G"]
    result, _ = apply("txt", source, command)
    assert result == "가 값\n{{G}} 나 값\n끝 값\n"
    single = dict(command)
    single.pop("occurrences")
    assert apply("txt", source, single)[0] == "가 값\n{{G}} 나 {{F}}\n끝 {{F}}\n"


def test_txt_available_commands_are_decided_here_with_spec_reasons() -> None:
    base = _slot_template()
    outside = {name: item for item in available_commands("txt", base, {"start": 0, "end": 2}, {})
               for name in (item["type"],)}
    assert [item["type"] for item in available_commands("txt", base, {"start": 0, "end": 2})] == list(COMMAND_TYPES)
    assert outside["create_field"]["enabled"] is True and outside["create_slot"]["enabled"] is True
    assert outside["create_option"] == {
        "type": "create_option", "enabled": False,
        "reason": "선택은 항목 안에 만들 수 있습니다. 먼저 항목 안의 내용을 고르세요.",
        "alternative": {"label": "먼저 항목 만들기", "command_type": "create_slot"}}
    assert outside["rename_field"]["reason"] == "필드를 고르세요."
    assert outside["unwrap"]["reason"] == "항목이나 선택 영역을 고르세요."
    assert outside["rename_option"]["reason"] == "선택 영역을 고르세요."
    crossing = {item["type"]: item for item in available_commands(
        "txt", base, {"start": 0, "end": base.index("첫째")})}
    assert crossing["create_field"]["reason"] == "고른 범위가 여러 독립 영역에 걸쳐 있습니다. 한 범위를 고르세요."
    assert crossing["create_slot"]["reason"] == "고른 범위가 기존 영역과 겹칩니다. 범위를 다시 고르세요."
    inside = {item["type"]: item for item in available_commands(
        "txt", base, {"start": base.index("공통"), "end": base.index("공통") + 2})}
    assert inside["create_option"]["enabled"] is True and inside["create_slot"]["enabled"] is False
    assert inside["unwrap"]["enabled"] is True and inside["rename_option"]["enabled"] is False
    on_field = {item["type"]: item for item in available_commands(
        "txt", base, {"start": base.index("{{F}}") + 1, "end": base.index("{{F}}") + 1},
        {"slot_id": "s", "option_id": None})}
    assert all(on_field[kind]["enabled"] for kind in ("rename_field", "relink_field", "unset_field"))
    assert on_field["create_field"]["reason"] == "고른 범위에 기존 필드가 포함되어 있습니다."
    option = {item["type"]: item for item in available_commands(
        "txt", base, {"start": base.index("첫째"), "end": base.index("첫째")}, {"slot_id": "s", "option_id": "a"})}
    assert option["rename_option"]["enabled"] and option["create_option"]["reason"] == "고른 범위가 기존 영역과 겹칩니다. 범위를 다시 고르세요."
    broken = {item["type"]: item for item in available_commands("txt", "{{#항목 s}}\n본문\n", {"start": 12, "end": 12})}
    assert broken["create_slot"]["reason"] == "구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요."
    assert all(item["reason"] == "고른 위치가 올바르지 않습니다."
               for item in available_commands("txt", base, {"start": -1, "end": 0}))


def test_analysis_spans_carry_name_tags_in_utf16_coordinates() -> None:
    """FB-03(#1079): 표면이 원문 대신 그릴 이름표(이름·범위 종류·여닫음·짝)를 분석이 싣는다. 좌표는 UTF-16 이다."""
    source = "😀 {{공고명}}\n{{#항목 사유 변경 사유}}\n본문\n{{/항목}}\n"
    spans = analyze("txt", source)["spans"]
    assert [(span["label"], span.get("region"), span.get("role"), span.get("paired")) for span in spans] == [
        ("공고명", None, None, None), ("변경 사유", "slot", "open", True), ("변경 사유", "slot", "close", True)]
    # 😀 는 UTF-16 두 단위다 — 오프셋이 편집기 좌표로 번역돼 있다.
    assert (spans[0]["start"], spans[0]["end"]) == (3, 10)


def test_structure_commands_and_trial_keep_source_to_output_evidence() -> None:
    source = "시작\n첫째 {{이름}}\n둘째 {{이름}}\n끝\n"
    source, _ = apply("txt", source, {"type": "create_slot", "start": source.index("첫째"), "end": source.index("끝"), "id": "항목1", "label": "표시"})
    first = source.index("첫째")
    source, _ = apply("txt", source, {"type": "create_option", "start": first, "end": first + len("첫째 {{이름}}"), "slot_id": "항목1", "id": "가"})
    second = source.index("둘째")
    source, _ = apply("txt", source, {"type": "create_option", "start": second, "end": second + len("둘째 {{이름}}"), "slot_id": "항목1", "id": "나"})
    detail = analyze("txt", source)
    assert detail["diagnostics"] == []
    assert detail["fields"][0]["count"] == 2
    assert [item["id"] for item in detail["slots"][0]["options"]] == ["가", "나"]
    assert detail["slots"][0]["options"][0]["location"]["content_start"] == 3
    assert [span["kind"] for span in detail["spans"]].count("field") == 2
    checked = trial_txt_authoring(source, {"이름": "홍길동"}, {"항목1": "나"})
    assert "둘째 홍길동" in checked["text"] and "첫째" not in checked["text"]
    assert len(checked["occurrences"]) == 1
    occurrence = checked["occurrences"][0]
    assert source[occurrence["source_start"]:occurrence["source_end"]] == "{{이름}}"
    assert checked["text"][occurrence["output_start"]:occurrence["output_end"]] == "홍길동"
    assert [(item["option_id"], item["selected_option_id"]) for item in checked["excluded"]] == [("가", "나")]


def test_partial_txt_selection_previews_full_included_line() -> None:
    text = "앞\n가나다\n끝\n"
    result = preview("txt", text, {"type": "create_slot", "start": 3, "end": 4, "id": "s"})
    assert result["expanded"] is True
    assert result["before"] == "나"
    assert result["included"] == "가나다\n"


def test_txt_structure_commands_keep_boundaries_and_content() -> None:
    base = "머리\n공통\n첫째\n둘째\n끝\n"
    base, _ = apply("txt", base, {"type": "create_slot", "start": base.index("공통"),
                                  "end": base.index("끝"), "id": "s"})
    base, _ = apply("txt", base, {"type": "create_option", "start": base.index("첫째"),
                                  "end": base.index("첫째") + 2, "slot_id": "s", "id": "a"})
    renamed, _ = apply("txt", base, {"type": "rename_slot", "kind": "slot", "slot_id": "s",
                                     "id": "terms", "label": "표시 이름"})
    assert analyze("txt", renamed)["slots"][0]["id"] == "terms"
    renamed_option, _ = apply("txt", base, {"type": "rename_option", "kind": "option",
                                            "slot_id": "s", "option_id": "a", "id": "first"})
    assert analyze("txt", renamed_option)["slots"][0]["options"][0]["id"] == "first"
    copied, _ = apply("txt", base, {"type": "duplicate", "kind": "slot", "slot_id": "s",
                                    "new_id": "s_copy", "destination": len(base)})
    assert [slot["id"] for slot in analyze("txt", copied)["slots"]] == ["s", "s_copy"]
    moved, _ = apply("txt", base, {"type": "move", "kind": "slot", "slot_id": "s",
                                   "destination": 0})
    assert moved.startswith("{{#항목 s") and "머리\n" in moved
    unwrapped, _ = apply("txt", base, {"type": "unwrap", "kind": "slot", "slot_id": "s",
                                       "cascade": True})
    assert "첫째\n" in unwrapped and not analyze("txt", unwrapped)["slots"]
    deleted, _ = apply("txt", base, {"type": "delete", "kind": "slot", "slot_id": "s"})
    assert deleted == "머리\n끝\n"
    adjusted, _ = apply("txt", base, {"type": "adjust_range", "kind": "option",
                                      "slot_id": "s", "option_id": "a",
                                      "start": base.index("첫째"), "end": base.index("둘째") + 2})
    assert analyze("txt", adjusted)["diagnostics"] == []


def test_txt_field_refusals_leave_original_untouched() -> None:
    source = "{{F}} 본문\n"
    for command in (
        {"type": "create_field", "start": 0, "end": 5, "name": "G"},
        {"type": "rename_field", "old_name": "없음", "name": "G"},
        {"type": "relink_field", "start": 7, "name": "G"},
        {"type": "unset_field", "start": 1},
    ):
        with pytest.raises(ValueError):
            apply("txt", source, command)
    assert source == "{{F}} 본문\n"


@pytest.mark.parametrize("source,expected", [
    ("앞\n{{/항목}}\n뒤\n", "앞\n뒤\n"),
    ("{{#항목 s}}\n본문\n", "{{#항목 s}}\n본문\n{{/항목}}\n"),
])
def test_single_unbalanced_marker_has_exact_repair_proposal(source: str, expected: str) -> None:
    diagnostic = analyze("txt", source)["diagnostics"][0]
    assert diagnostic["location"]["line"] == (1 if "{{/항목}}" in source else 0)
    assert (diagnostic["severity"], diagnostic["category"]) == ("error", "structure")
    assert diagnostic["target"] == (None if "{{/항목}}" in source else "s")
    assert [action["kind"] for action in diagnostic["actions"]] == ["navigate", "command"]
    assert diagnostic["actions"][0]["location"] == diagnostic["location"]
    suggestion = diagnostic["suggestion"]
    assert diagnostic["actions"][1] == {"label": suggestion["label"], "kind": "command",
                                        "command": suggestion["command"]}
    projected = preview("txt", source, suggestion["command"])
    assert projected["before"] is not None and projected["after"]
    assert projected["label"] == suggestion["label"]
    fixed, _ = apply("txt", source, suggestion["command"])
    assert fixed == expected
    assert analyze("txt", fixed)["diagnostics"] == []
    with pytest.raises(ValueError, match="더는 적용되지"):
        apply("txt", fixed, suggestion["command"])


def test_txt_semantic_transfer_requires_explicit_link_and_rebases_structure_id() -> None:
    captured = capture_semantic("txt", "{{이름}}\n", {"kind": "field", "start": 1})
    with pytest.raises(ValueError, match="기존 필드 연결"):
        paste_semantic("txt", "{{이름}}\n", captured, {"start": 7, "end": 7})
    linked, impact = paste_semantic("txt", "{{이름}}\n", captured,
                                    {"start": 7, "end": 7, "link_existing": True})
    assert linked == "{{이름}}\n{{이름}}" and impact["affected"] == 1
    plain, _ = paste_semantic("txt", "", captured, {"start": 0, "end": 0}, with_meaning=False)
    assert plain == "이름" and analyze("txt", plain)["fields"] == []

    source = "{{#항목 s 표시}}\n본문\n{{/항목}}\n"
    block = capture_semantic("txt", source, {"kind": "slot", "slot_id": "s"})
    target = "{{#항목 s}}\n기존\n{{/항목}}\n"
    with pytest.raises(ValueError, match="새 식별자"):
        paste_semantic("txt", target, block, {"start": len(target), "end": len(target)})
    with pytest.raises(ValueError, match="구조가 깨집니다"):
        paste_semantic("txt", target, block,
                       {"start": target.index("기존"), "end": target.index("기존"), "new_id": "nested"})
    pasted, _ = paste_semantic("txt", target, block,
                               {"start": len(target), "end": len(target), "new_id": "other"})
    assert [slot["id"] for slot in analyze("txt", pasted)["slots"]] == ["s", "other"]
    nested = capture_semantic("txt", "{{#항목 n}}\n{{F}}\n{{/항목}}\n",
                              {"kind": "slot", "slot_id": "n"})
    plain_block, _ = paste_semantic("txt", "", nested, {"start": 0, "end": 0},
                                    with_meaning=False)
    assert plain_block == "F\n" and analyze("txt", plain_block)["fields"] == []


def test_txt_option_transfer_and_plain_text_are_context_checked() -> None:
    source = "{{#항목 s}}\n{{#선택 a}}\n본문\n{{/선택}}\n{{/항목}}\n"
    option = capture_semantic("txt", source, {"kind": "option", "slot_id": "s", "option_id": "a"})
    target = "{{#항목 t}}\n기존\n{{/항목}}\n"
    position = target.index("기존")
    pasted, _ = paste_semantic("txt", target, option,
                               {"start": position, "end": position, "slot_id": "t", "new_id": "b"})
    assert [item["id"] for item in analyze("txt", pasted)["slots"][0]["options"]] == ["b"]
    with pytest.raises(ValueError, match="상위 항목"):
        paste_semantic("txt", target, option, {"start": position, "end": position,
                                               "slot_id": "missing"})
    plain = capture_semantic("txt", "앞 문장 뒤", {"kind": "text", "start": 2, "end": 4})
    result, _ = paste_semantic("txt", "", plain, {"start": 0, "end": 0}, with_meaning=False)
    assert result == "문장"
    with pytest.raises(ValueError, match="의미를 포함"):
        capture_semantic("txt", "{{F}}", {"kind": "text", "start": 0, "end": 5})
    with pytest.raises(ValueError, match="의미를 포함"):
        capture_semantic("txt", "{{F}}", {"kind": "text", "start": 0, "end": 2})


def test_txt_transfer_refuses_stale_or_unsafe_selection_boundaries() -> None:
    capture_cases = (
        ("😀본문", {"kind": "text", "start": 1, "end": 3}, "문자 경계"),
        ("본문", {"kind": "field", "start": 0}, "필드 사용 위치"),
        ("본문", {"kind": "text", "start": 1, "end": 1}, "본문을 고르"),
        ("본문", {"kind": "unknown"}, "의미 요소"),
        ("{{#항목 s}}\n본문\n", {"kind": "slot", "slot_id": "s"}, "구조 오류"),
    )
    for source, selector, message in capture_cases:
        with pytest.raises(ValueError, match=message):
            capture_semantic("txt", source, selector)

    block = capture_semantic("txt", "{{#항목 s}}\n본문\n{{/항목}}\n",
                             {"kind": "slot", "slot_id": "s"})
    paste_cases = (
        ("본문", {"start": 2, "end": 1}, "범위"),
        ("본문", {"start": 1, "end": 1}, "줄 시작"),
        ("본문", {"start": 0, "end": 1}, "줄 시작"),
        ("{{#항목 broken}}\n", {"start": 0, "end": 0}, "구조 오류"),
    )
    for target, destination, message in paste_cases:
        with pytest.raises(ValueError, match=message):
            paste_semantic("txt", target, block, destination)
    with pytest.raises(ValueError, match="다른 파일 형식"):
        paste_semantic("hwpx", "", block, {"start": 0, "end": 0})


def test_txt_structure_commands_refuse_ambiguous_ranges_without_changes() -> None:
    source = "앞\n공통\n첫째\n둘째\n끝\n"
    source, _ = apply("txt", source, {"type": "create_slot", "start": source.index("공통"),
                                      "end": source.index("끝"), "id": "s"})
    source, _ = apply("txt", source, {"type": "create_option", "start": source.index("첫째"),
                                      "end": source.index("둘째"), "slot_id": "s", "id": "a"})
    cases = (
        ({"type": "create_slot", "start": source.index("공통"), "end": source.index("둘째"),
          "id": "other"}, "겹칩니다"),
        ({"type": "create_option", "start": 0, "end": 1, "slot_id": "s", "id": "b"}, "하나의 항목"),
        ({"type": "create_option", "start": source.index("둘째"), "end": source.index("둘째") + 2,
          "slot_id": "s", "id": "a"}, "식별자"),
        ({"type": "rename_slot", "slot_id": "missing", "id": "other"}, "영역을 찾"),
        ({"type": "unwrap", "kind": "slot", "slot_id": "s"}, "함께 해제"),
        ({"type": "move", "kind": "slot", "slot_id": "s",
          "destination": source.index("공통")}, "자기 안"),
        ({"type": "move", "kind": "slot", "slot_id": "s", "destination": 1}, "줄 경계"),
        ({"type": "duplicate", "kind": "slot", "slot_id": "s"}, "새 식별자"),
    )
    for command, message in cases:
        with pytest.raises(ValueError, match=message):
            apply("txt", source, command)
    assert [slot["id"] for slot in analyze("txt", source)["slots"]] == ["s"]
    with pytest.raises(ValueError, match="문자 중간"):
        apply("txt", "😀본문", {"type": "create_field", "start": 1, "end": 2, "name": "F"})
    with pytest.raises(ValueError, match="문서 밖"):
        apply("txt", "본문", {"type": "create_field", "start": 10, "end": 10, "name": "F"})
    with pytest.raises(ValueError, match="시험 선택"):
        trial("txt", source, {}, {}, output="")
    with pytest.raises(ValueError, match="구조가 깨집니다"):
        apply("txt", source, {"type": "adjust_range", "kind": "slot", "slot_id": "s",
                              "start": source.index("공통"), "end": source.index("공통") + 2})
    with pytest.raises(ValueError, match="구조 오류"):
        trial("txt", "{{#항목 broken}}\n", {}, {}, output="")


def test_txt_field_noop_and_final_line_structure_preserve_editor_text() -> None:
    source = "😀 {{F}}\r\n본문"
    unchanged, impact = apply("txt", source, {"type": "rename_field", "old_name": "F", "name": "F"})
    assert unchanged == source and impact["edits"] == []
    result, _ = apply("txt", source, {"type": "create_slot", "start": source.index("본문") + 1,
                                      "end": len(source) + 1, "id": "s"})
    assert result.endswith("{{#항목 s}}\r\n본문\r\n{{/항목}}")
    with pytest.raises(ValueError, match="필드 이름"):
        apply("txt", source, {"type": "create_field", "start": 0, "end": 2, "name": "#bad"})
    with pytest.raises(ValueError, match="지원하지 않는 저작 형식"):
        preview("hwpx", source, {"type": "create_field", "start": 0, "end": 0, "name": "F"})


def test_txt_trial_provenance_uses_utf16_for_astral_source_and_value() -> None:
    rendered = trial_txt_authoring("😀 {{F}}\n", {"F": "🟢"}, {})
    assert rendered["text"] == "😀 🟢\n"
    assert rendered["occurrences"] == [{"name": "F", "source_start": 3, "source_end": 8,
                                         "output_start": 3, "output_end": 5, "value": "🟢"}]


def test_trial_renders_values_that_are_absent_or_blank_with_the_generation_marker() -> None:
    """결과 시험의 빈 값 규칙은 생성 경로와 같다(IDE-01 결정 1(a)) — 없거나 빈 값은 막지 않고 표식이다."""
    document, empty = trial_document_values(["다", "가", "나", "다", "라"], {"가": "", "나": "  ", "라": "값", "무관": None})
    marker = MISSING_MARKER.format
    assert document == {"다": marker(field="다"), "가": marker(field="가"), "나": marker(field="나"), "라": "값"}
    assert empty == ["다", "가", "나"], "차례는 받은 이름 차례, 중복 없음"
    rendered = trial_txt_authoring("{{이름}}·{{값}}\n", {"값": "1"}, {})
    assert rendered["text"] == f"{marker(field='이름')}·1\n"
    assert rendered["report"] == {"missing_fields": [], "empty_fields": ["이름"]}
    first = rendered["occurrences"][0]
    assert first["value"] == marker(field="이름")
    assert rendered["text"][first["output_start"]:first["output_end"]] == marker(field="이름")
    # 선택 공백은 두 매체 모두 지금처럼 거절이다.
    with pytest.raises(ValueError, match="시험 선택"):
        trial_txt_authoring("{{#항목 s 표시}}\n{{#선택 a 가}}\n가\n{{/선택}}\n{{/항목}}\n", {}, {})


# ------------------------------------------------------------------ P-06 이름 제안 · 이름 거절 제자리
@pytest.mark.parametrize(("before", "selected", "expected"), [
    ("수요기관: ", "○○시청", "수요기관"),
    ("품명 ：", "볼펜", "품명"),
    ("  가. 공고번호   :", "제2026-1호", "공고번호"),
    (" 수  요  기  관:", "○○시청", "수요기관"),
    ("1. 계약 기간 :", "30일", "계약 기간"),
    ("□ 품 명:", "볼펜", "품명"),
    ("① 납품장소：", "본관", "납품장소"),
    ("공고번호: 제1호   공고일: ", "2026. 3. 1.", "공고일"),       # 한 문단 두 쌍 — 칸 사이 넓은 공백 뒤만
    ("수요기관: {{기관}} 품명: ", "볼펜", "품명"),                 # 앞 필드 토큰 뒤의 라벨만
    ("", "계약명", None),                                          # 규칙 ② 삭제 — 선택 문구는 이름이 아니다
    ("수요기관 ", "○○시청", None),                                 # 쌍점으로 끝나지 않으면 라벨이 아니다
    ("수요기관: ", "{{기관}}", None),                              # 문법이 든 선택
    ("수요기관: ", "  ", None),                                    # 빈 선택
    ("수요기관: ", "둘\n줄", None),                                # 여러 줄
    ("가" * 21 + ":", "값", None),                                 # 20자 초과는 라벨이 아니다
    ("#기관: ", "값", None),                                       # 문법 기호로 시작하는 이름은 거절된다
])
def test_suggest_field_name_reads_only_the_label_before_the_selection(before, selected, expected) -> None:
    assert suggest_field_name(before, selected, []) == expected


def test_suggest_field_name_adopts_an_existing_spelling_that_differs_only_in_spaces() -> None:
    assert suggest_field_name("수요 기관: ", "○○시청", ["수요기관", "품명"]) == "수요기관"
    assert suggest_field_name("수요기관: ", "○○시청", ["품명"]) == "수요기관"


def test_invalid_names_are_structured_in_place_refusals_naming_their_input() -> None:
    with pytest.raises(InvalidName) as empty:
        preview("txt", "수요기관: ○○시청", {"type": "create_field", "start": 6, "end": 10, "name": "  "})
    assert empty.value.to_dict() == {"code": "invalid_name", "field": "name",
                                     "message": "필드 이름을 확인하세요. 비어 있거나 문법 기호가 포함되어 있습니다."}
    with pytest.raises(InvalidName) as syntax:
        preview("txt", "{{이름}}", {"type": "rename_field", "old_name": "이름", "name": "a|b"})
    assert syntax.value.field == "name"
    # 항목·선택 식별자는 식별자 칸의 거절이다 — 이름 칸 곁이 아니다.
    with pytest.raises(InvalidName) as identifier:
        preview("txt", "본문\n끝\n", {"type": "create_slot", "start": 0, "end": 2, "id": "a b", "label": "표시"})
    assert identifier.value.field == "identifier"
    with pytest.raises(InvalidName) as missing:
        preview("txt", "본문\n끝\n", {"type": "create_slot", "start": 0, "end": 2, "id": "", "label": ""})
    assert missing.value.to_dict() == {"code": "invalid_name", "field": "identifier",
                                       "message": "항목이나 선택의 식별자를 입력하세요."}
    # 표시 이름(이름 칸)이 되읽기 동등을 깨면 이름 칸의 거절이다.
    with pytest.raises(InvalidName) as label:
        preview("txt", "본문\n끝\n", {"type": "create_slot", "start": 0, "end": 2, "id": "a", "label": "표  시"})
    assert label.value.field == "name"
    assert isinstance(label.value, ValueError), "거절은 여전히 ValueError 다 — 판정 밖 호출자는 그대로 멈춘다"


# ------------------------------------------------------------------ P-01 확인 등급
_NO_IMPACT = {"linked_jobs": [], "impact_unverified": 0,
              "field_delta": {"added_fields": [], "removed_fields": []},
              "structure_delta": {"added_slots": [], "removed_slots": [], "added_options": [],
                                  "removed_options": [], "renamed": []}}


@pytest.mark.parametrize(("command", "projection", "impact", "tier"), [
    ({"type": "create_field", "name": "수요기관"}, {}, _NO_IMPACT, "none"),
    ({"type": "create_field", "name": "수요기관"}, {"links_existing": True}, _NO_IMPACT, "enter"),
    ({"type": "create_field", "name": "수요기관"}, {}, {**_NO_IMPACT, "impact_unverified": 1}, "enter"),
    ({"type": "create_slot", "id": "a"}, {"expanded": False}, _NO_IMPACT, "none"),
    ({"type": "create_slot", "id": "a"}, {"expanded": True}, _NO_IMPACT, "enter"),
    ({"type": "create_option", "id": "a", "slot_id": "s"}, {}, _NO_IMPACT, "none"),
    ({"type": "rename_field", "old_name": "a", "name": "b"}, {}, _NO_IMPACT, "enter"),
    ({"type": "rename_slot", "slot_id": "s", "id": "s", "label": "새 표시"}, {}, _NO_IMPACT, "none"),
    ({"type": "rename_slot", "slot_id": "s", "id": "t"}, {}, _NO_IMPACT, "enter"),
    ({"type": "rename_option", "slot_id": "s", "option_id": "o", "id": "p"}, {}, _NO_IMPACT, "enter"),
    ({"type": "adjust_range", "slot_id": "s"}, {"expanded": True}, _NO_IMPACT, "enter"),
    ({"type": "unwrap", "slot_id": "s"}, {}, _NO_IMPACT, "enter"),
    ({"type": "unwrap", "slot_id": "s"}, {"requires_cascade": True}, _NO_IMPACT, "button"),
    ({"type": "unwrap", "slot_id": "s", "cascade": True}, {}, _NO_IMPACT, "button"),
    ({"type": "delete", "slot_id": "s"}, {}, _NO_IMPACT, "button"),
    # IDE-06 P-20: 필드 전체의 의미 해제는 모든 사용 위치를 한 번에 없앤다 — 영향을 보이는 enter 등급이다.
    ({"type": "unset_field", "old_name": "F", "occurrences": [{}, {}, {}], "text": "값"}, {}, _NO_IMPACT, "enter"),
    ({"type": "unset_field", "old_name": "F", "occurrences": [{}, {}, {}], "text": "값"}, {},
     {**_NO_IMPACT, "field_delta": {"added_fields": [], "removed_fields": ["F"]}}, "enter"),
    ({"type": "rename_slot", "slot_id": "s", "id": "s"}, {},
     {**_NO_IMPACT, "field_delta": {"added_fields": [], "removed_fields": ["이름"]}}, "enter"),
    ({"type": "rename_slot", "slot_id": "s", "id": "s"}, {},
     {**_NO_IMPACT, "linked_jobs": ["작업"],
      "structure_delta": {**_NO_IMPACT["structure_delta"], "added_slots": ["t"]}}, "enter"),
    ({"type": "rename_slot", "slot_id": "s", "id": "s"}, {}, {**_NO_IMPACT, "linked_jobs": ["작업"]}, "none"),
])
def test_confirm_tier_table(command, projection, impact, tier) -> None:
    assert confirm_tier(command, projection, impact) == tier


def test_contract_commands_always_show_their_impact_before_apply() -> None:
    """ui-style 미리보기 계약: 이름 변경·범위 확장·삭제는 적용 전에 영향이 보인다 — 어느 입력에서도 none 이 아니다."""
    contract = [
        ({"type": "rename_field", "old_name": "a", "name": "b"}, {}),
        ({"type": "rename_slot", "slot_id": "s", "id": "t"}, {}),
        ({"type": "rename_option", "slot_id": "s", "option_id": "o", "id": "p"}, {}),
        ({"type": "adjust_range", "slot_id": "s"}, {}),
        ({"type": "create_slot", "id": "a"}, {"expanded": True}),
        ({"type": "create_option", "id": "a", "slot_id": "s"}, {"expanded": True}),
        ({"type": "delete", "slot_id": "s"}, {}),
        ({"type": "delete", "kind": "option", "slot_id": "s", "option_id": "o"}, {}),
    ]
    for command, projection in contract:
        for impact in (None, _NO_IMPACT):
            assert confirm_tier(command, projection, impact) != "none", command


def test_real_txt_previews_carry_the_facts_the_tier_reads() -> None:
    source = "수요기관: ○○시청\n본문\n끝\n"
    create = preview("txt", source, {"type": "create_field", "start": 6, "end": 10, "name": "수요기관"})
    assert confirm_tier({"type": "create_field"}, create, _NO_IMPACT) == "none"
    partial = preview("txt", source, {"type": "create_slot", "start": 12, "end": 13, "id": "a"})
    assert partial["expanded"] is True and confirm_tier({"type": "create_slot"}, partial, _NO_IMPACT) == "enter"
    whole = preview("txt", source, {"type": "create_slot", "start": 11, "end": 14, "id": "a"})
    assert whole["expanded"] is False and confirm_tier({"type": "create_slot"}, whole, _NO_IMPACT) == "none"


def test_created_target_names_the_new_field_slot_or_option_in_the_result() -> None:
    source = "수요기관: ○○시청\n본문\n끝\n"
    result, _ = apply("txt", source, {"type": "create_field", "start": 6, "end": 10, "name": "수요기관"})
    created = created_target({"type": "create_field", "name": " 수요기관 "}, analyze("txt", result))
    assert created is not None and created["kind"] == "field" and created["name"] == "수요기관"
    assert created["location"] == created["occurrences"][0]
    assert (created["location"]["start"], created["location"]["end"]) == (6, 14)
    slotted, _ = apply("txt", source, {"type": "create_slot", "start": 11, "end": 14, "id": "구분"})
    slot = created_target({"type": "create_slot", "id": "구분"}, analyze("txt", slotted))
    assert slot is not None and slot["kind"] == "slot" and slot["slot_id"] == "구분" and slot["location"]
    assert created_target({"type": "rename_field", "name": "수요기관"}, analyze("txt", result)) is None
    assert created_target({"type": "create_field", "name": "없음"}, analyze("txt", result)) is None


# ------------------------------------------------------------- IDE-07 반복 명령 (#1053)
def _undo(source: str, result: str, plan: dict) -> str:
    """편집기의 실행 취소 한 번 — 한 계획의 edit 전부를 한 번에 뒤집는다(BMP 본문이라 UTF-16 == code point)."""
    shift = 0
    inverse = []
    for edit in sorted(plan["edits"], key=lambda item: item["start"]):
        start = edit["start"] + shift
        inverse.append((start, start + len(edit["text"]), source[edit["start"]:edit["end"]]))
        shift += len(edit["text"]) - (edit["end"] - edit["start"])
    for start, end, text in reversed(inverse):
        result = result[:start] + text + result[end:]
    return result


def test_txt_same_text_is_raw_sites_with_create_field_verdicts() -> None:
    from hwpxfiller.domain.template_authoring import same_text_sites

    source = "○○시청 귀하\n서명 ○○시청 (인)\n○○시청 ○○시청\n{{○○시청}}\n{{#항목 ○○시청}}\n본문\n{{/항목}}\n"
    sites = same_text_sites("txt", source, {"start": 0, "end": 4})
    # 고른 자리·필드 토큰·구간 표기 안의 자리는 빠지고, 같은 줄의 두 자리는 합치지 않는다(검색의 한 건 병합 아님).
    assert [(site["location"], site["line"], site["context"], site["focus"]) for site in sites] == [
        ({"start": 11, "end": 15}, 1, "서명 ○○시청 (인)", {"start": 3, "end": 7}),
        ({"start": 20, "end": 24}, 2, "○○시청 ○○시청", {"start": 0, "end": 4}),
        ({"start": 25, "end": 29}, 2, "○○시청 ○○시청", {"start": 5, "end": 9}),
    ]
    assert all(site["enabled"] is True and site["reason"] is None for site in sites)
    assert same_text_sites("txt", source, {"start": 4, "end": 5}) == [], "공백뿐인 문구"
    assert same_text_sites("txt", source, {"start": 2, "end": 2}) == [], "빈 범위"
    assert same_text_sites("txt", source, {"start": 0, "end": 999}) == [], "문서 밖"
    with pytest.raises(ValueError, match="지원하지 않는"):
        same_text_sites("hwpx", source, {"start": 0, "end": 4})


def test_txt_create_field_ranges_is_one_plan_with_one_undo() -> None:
    source = "○○시청 귀하\n서명 ○○시청 (인)\n○○시청 ○○시청\n"
    ranges = [{"start": 0, "end": 4}, {"start": 25, "end": 29}, {"start": 11, "end": 15}]
    command = {"type": "create_field", "name": "수요기관", "start": 0, "end": 4, "ranges": ranges}
    result, plan = apply("txt", source, command)
    field = next(item for item in analyze("txt", result)["fields"] if item["name"] == "수요기관")
    assert field["count"] == 3
    assert result == "{{수요기관}} 귀하\n서명 {{수요기관}} (인)\n○○시청 {{수요기관}}\n"
    assert plan["affected"] == 3 and len(plan["edits"]) == 3
    assert plan["included"] == ["○○시청 귀하", "서명 ○○시청 (인)", "○○시청 ○○시청"]
    assert _undo(source, result, plan) == source
    assert confirm_tier(command, plan) == "enter"
    assert confirm_tier({**command, "ranges": []}, {}) == "none"
    assert "included" in preview("txt", source, {**command, "ranges": None}) and \
        preview("txt", source, {"type": "create_field", "name": "a", "start": 0, "end": 4})["included"] is None


@pytest.mark.parametrize(("ranges", "message"), [
    ([{"start": 0, "end": 4}, {"start": 0, "end": 4}], "기존 필드가 포함"),
    ([{"start": 11, "end": 15}], "고른 위치가 올바르지"),
    ([{"start": 0, "end": 4}, {"start": 5, "end": 9}], "고른 위치가 올바르지"),
    ([{"start": 0, "end": 4}, {"start": 15, "end": 11}], "고른 위치가 올바르지"),
    ([{"start": 0, "end": 4}, {"start": 0}], "고른 위치가 올바르지"),
    ([{"start": 0, "end": 4}, "x"], "고른 위치가 올바르지"),
    ({"start": 0, "end": 4}, "고른 위치가 올바르지"),
    ([{"start": 0, "end": 4}, {"start": 32, "end": 36}], "기존 필드가 포함"),
])
def test_txt_create_field_ranges_refusals_leave_source_untouched(ranges, message) -> None:
    source = "○○시청 귀하\n서명 ○○시청 (인)\n○○시청 ○○시청\n{{○○시청}}\n"
    assert source[32:36] == "○○시청"
    with pytest.raises(ValueError, match=message):
        apply("txt", source, {"type": "create_field", "name": "수요기관", "start": 0, "end": 4, "ranges": ranges})


def test_txt_create_field_ranges_that_overlap_each_other_are_refused() -> None:
    with pytest.raises(ValueError, match="기존 필드가 포함"):
        apply("txt", "아아아", {"type": "create_field", "name": "a", "start": 0, "end": 2,
                               "ranges": [{"start": 0, "end": 2}, {"start": 1, "end": 3}]})
    # 맞닿은 두 자리는 겹침이 아니다.
    result, _ = apply("txt", "아아아아", {"type": "create_field", "name": "a", "start": 0, "end": 2,
                                         "ranges": [{"start": 2, "end": 4}, {"start": 0, "end": 2}]})
    assert result == "{{a}}{{a}}"
