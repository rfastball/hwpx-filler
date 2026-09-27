"""저작 보조(토큰→누름틀 컴파일) 테스트 — 라운드트립·멱등·명시성·충실도.

핵심 증명: 작성자가 타이핑한 평문 ``{{X}}`` 를 컴파일하면 기존 파이프라인(schema 인식 +
fields 채우기)이 그대로 동작하고, 재컴파일은 무해(멱등)하다.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree
import pytest

from hwpxfiller.domain.authoring import compile_document, scan_tokens
from hwpxfiller.domain.fields import FieldDocument
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.external.hwpx_package_io import read_hwpx_package, write_hwpx_package
from hwpxfiller.domain.schema import extract_schema
from hwpxfiller.domain.template_authoring import COMMAND_TYPES, CascadeRequired, NameConflict
from hwpxfiller.external.hwpx_authoring import (
    analyze_hwpx,
    apply_hwpx,
    available_commands_hwpx,
    preview_hwpx,
    search_hwpx,
    syntax_view_hwpx,
    trial_hwpx,
)
from hwpxfiller.external.authoring_transfer import capture_semantic, paste_semantic
from hwpxfiller.external.materialization_conformance_vocabulary import ConformanceFailure
from hwpxfiller.external.rhwp_preflight import compare_rhwp_roundtrip

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
CORPUS = Path(__file__).parent / "corpus" / "real"
FRAG_CORPUS = Path(__file__).parent / "corpus" / "frag"


def _pkg(section_inner: str) -> HwpxPackage:
    sec = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>'
    ).encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries["Contents/section0.xml"] = sec
    return pkg


def _root(pkg: HwpxPackage) -> etree._Element:
    return etree.fromstring(pkg.entries["Contents/section0.xml"])


def _frag(name: str) -> str:
    return (FRAG_CORPUS / name).read_text(encoding="utf-8")


# --------------------------------------------------------------- 미리보기(scan)
def test_scan_is_readonly_and_lists_compilable():
    """scan 은 워크북을 변형하지 않고 컴파일 가능한 토큰을 나열한다(명시성: 미리보기)."""
    xml = '<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>'
    pkg = _pkg(xml)
    before = pkg.entries["Contents/section0.xml"]
    sites = scan_tokens(pkg)
    assert pkg.entries["Contents/section0.xml"] == before  # 무변형
    assert [(s.name, s.compilable) for s in sites] == [("계약명", True)]
    assert sites[0].context == "계약명: {{계약명}}"


def test_native_authoring_field_keeps_content_and_trials_value():
    pkg = _pkg('<hp:p><hp:run charPrIDRef="7"><hp:t>앞 원문 뒤</hp:t></hp:run></hp:p>')
    original = pkg.entries["Contents/section0.xml"]
    result, impact = apply_hwpx(pkg, {
        "type": "create_field", "entry": "Contents/section0.xml",
        "paragraph": 0, "start": 2, "end": 4, "name": "내용",
    })
    assert impact["captured_text"] == "원문"
    assert original != result.entries["Contents/section0.xml"]
    assert analyze_hwpx(result)["fields"][0]["name"] == "내용"
    assert {key: analyze_hwpx(result)["fields"][0]["occurrences"][0][key] for key in ("start", "end")} == {"start": 2, "end": 4}
    assert trial_hwpx(result, {"내용": "새값"}, {})["bytes"]


def test_native_preview_exposes_captured_paragraphs_without_changing_source() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:t>첫 문단</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>둘째 문단</hp:t></hp:run></hp:p>'
    )
    before = package.entries["Contents/section0.xml"]
    projected = preview_hwpx(package, {"type": "create_slot", "entry": "Contents/section0.xml",
                                       "start_paragraph": 0, "end_paragraph": 1,
                                       "start": 1, "end": 2, "id": "s"})
    assert projected["expanded"] is True
    assert projected["included"] == "첫 문단\n둘째 문단"
    assert "문단 2개" in projected["before"]
    assert projected["result"]["slots"][0]["id"] == "s"
    assert package.entries["Contents/section0.xml"] == before


def test_native_semantic_transfer_preserves_field_style_and_rebases_ids() -> None:
    source = _pkg('<hp:p><hp:run charPrIDRef="7"><hp:t>앞 원문 뒤</hp:t></hp:run></hp:p>')
    apply_hwpx(source, {"type": "create_field", "entry": "Contents/section0.xml",
                        "paragraph": 0, "start": 2, "end": 4, "name": "내용"})
    occurrence = analyze_hwpx(source)["fields"][0]["occurrences"][0]
    captured = capture_semantic("hwpx", source, {"kind": "field", "entry": occurrence["entry"],
                                                 "occurrence": occurrence["occurrence"],
                                                 "pairing_id": occurrence["pairing_id"]})
    target = _pkg('<hp:p><hp:run charPrIDRef="1"><hp:t>시작 끝</hp:t></hp:run></hp:p>')
    pasted, impact = paste_semantic("hwpx", target, captured,
                                    {"entry": "Contents/section0.xml", "paragraph": 0,
                                     "start": 3, "end": 3})
    assert impact["after"] == "원문"
    assert analyze_hwpx(pasted)["fields"][0]["name"] == "내용"
    assert "charPrIDRef=\"7\"" in pasted.entries["Contents/section0.xml"].decode("utf-8")
    plain, _ = paste_semantic("hwpx", target, captured,
                              {"entry": "Contents/section0.xml", "paragraph": 0,
                               "start": 3, "end": 3}, with_meaning=False)
    assert analyze_hwpx(plain)["fields"] == []


def test_native_semantic_transfer_rebases_slot_ids_across_documents() -> None:
    source = _pkg('<hp:p><hp:run><hp:t>원문</hp:t></hp:run></hp:p>')
    apply_hwpx(source, {"type": "create_slot", "entry": "Contents/section0.xml",
                        "start_paragraph": 0, "end_paragraph": 0, "id": "s"})
    captured = capture_semantic("hwpx", source, {"kind": "slot", "slot_id": "s"})
    with pytest.raises(ValueError, match="새 식별자"):
        paste_semantic("hwpx", source, captured,
                       {"entry": "Contents/section0.xml", "destination_paragraph": 1})
    target = _pkg('<hp:p><hp:run><hp:t>기존</hp:t></hp:run></hp:p>')
    for destination, message in (
        ({"entry": "Contents/section0.xml", "destination_paragraph": 1, "start": 1}, "문단 시작"),
        ({"entry": "Contents/section0.xml", "destination_paragraph": 3}, "문단 경계"),
        ({"entry": "Contents/missing.xml", "destination_paragraph": 1}, "문서 영역"),
    ):
        with pytest.raises(ValueError, match=message):
            paste_semantic("hwpx", target, captured, destination)
    with pytest.raises(ValueError, match="구조 오류"):
        paste_semantic("hwpx", _pkg(""), captured,
                       {"entry": "Contents/section0.xml", "destination_paragraph": 0})
    pasted, _ = paste_semantic("hwpx", target, captured,
                               {"entry": "Contents/section0.xml", "destination_paragraph": 1,
                                "start": 0, "new_id": "s2"})
    assert [slot["id"] for slot in analyze_hwpx(pasted)["slots"]] == ["s2"]
    assert len(list(_root(pasted).iter(f"{{{HP}}}p"))) == 2


def test_native_slot_transfer_keeps_child_bookmark_separator() -> None:
    # 붙여넣은 항목의 하위 선택 책갈피는 `slot/option` 구분자를 지켜야 복제본 개명이 하위를 찾는다.
    entry = "Contents/section0.xml"
    source = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>선택</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(source, {"type": "create_slot", "entry": entry,
                        "start_paragraph": 0, "end_paragraph": 1, "id": "s"})
    apply_hwpx(source, {"type": "create_option", "entry": entry,
                        "start_paragraph": 1, "end_paragraph": 1, "slot_id": "s", "id": "a"})
    captured = capture_semantic("hwpx", source, {"kind": "slot", "slot_id": "s"})
    target = _pkg('<hp:p><hp:run><hp:t>기존</hp:t></hp:run></hp:p>')
    pasted, _ = paste_semantic("hwpx", target, captured,
                               {"entry": entry, "destination_paragraph": 1, "start": 0, "new_id": "s2"})
    names = {node.get("name") for node in _root(pasted).iter(f"{{{HP}}}fieldBegin")
             if "/" in (node.get("name") or "")}
    assert names == {"s2/a"}, names
    apply_hwpx(pasted, {"type": "rename_slot", "slot_id": "s2", "id": "s3"})
    assert [item["id"] for item in analyze_hwpx(pasted)["slots"][0]["options"]] == ["a"]


def test_native_slot_transfer_requires_explicit_link_for_contained_fields() -> None:
    entry = "Contents/section0.xml"
    source = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>값</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(source, {"type": "create_field", "entry": entry,
                        "paragraph": 1, "start": 0, "end": 1, "name": "F"})
    apply_hwpx(source, {"type": "create_slot", "entry": entry,
                        "start_paragraph": 0, "end_paragraph": 1, "id": "s"})
    captured = capture_semantic("hwpx", source, {"kind": "slot", "slot_id": "s"})
    target = _pkg('<hp:p><hp:run><hp:t>기존</hp:t></hp:run></hp:p>')
    apply_hwpx(target, {"type": "create_field", "entry": entry,
                        "paragraph": 0, "start": 0, "end": 2, "name": "F"})
    destination = {"entry": entry, "destination_paragraph": 1, "new_id": "s2"}
    with pytest.raises(ValueError, match="기존 필드 연결"):
        paste_semantic("hwpx", target, captured, destination)
    linked, _ = paste_semantic("hwpx", target, captured, destination | {"link_existing": True})
    assert analyze_hwpx(linked)["fields"][0]["count"] == 2


def test_native_semantic_transfer_places_option_under_requested_owner() -> None:
    source = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>선택 문장</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(source, {"type": "create_slot", "entry": "Contents/section0.xml",
                        "start_paragraph": 0, "end_paragraph": 2, "id": "s"})
    apply_hwpx(source, {"type": "create_option", "entry": "Contents/section0.xml",
                        "start_paragraph": 1, "end_paragraph": 1, "slot_id": "s", "id": "a"})
    captured = capture_semantic("hwpx", source, {"kind": "option", "slot_id": "s", "option_id": "a"})
    target = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>여기</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(target, {"type": "create_slot", "entry": "Contents/section0.xml",
                        "start_paragraph": 0, "end_paragraph": 2, "id": "t"})
    destination = {"entry": "Contents/section0.xml", "destination_paragraph": 1,
                   "start": 0, "slot_id": "t", "new_id": "b"}
    with pytest.raises(ValueError, match="상위 항목"):
        paste_semantic("hwpx", target, captured, destination | {"slot_id": "missing"})
    with pytest.raises(ValueError, match="상위 항목 안"):
        paste_semantic("hwpx", target, captured, destination | {"destination_paragraph": 3})
    pasted, _ = paste_semantic("hwpx", target, captured,
                               destination)
    assert [(slot["id"], [option["id"] for option in slot["options"]])
            for slot in analyze_hwpx(pasted)["slots"]] == [("t", ["b"])]
    assert "선택 문장" in "".join(_root(pasted).itertext())
    with pytest.raises(ValueError, match="상위 항목이나 선택 식별자"):
        paste_semantic("hwpx", pasted, captured, destination)
    slot = capture_semantic("hwpx", source, {"kind": "slot", "slot_id": "s"})
    with pytest.raises(ValueError, match="다른 의미 영역"):
        paste_semantic("hwpx", target, slot, destination | {"new_id": "other"})


def test_native_semantic_transfer_rejects_style_mismatch_and_complex_field_target() -> None:
    source = _pkg('<hp:p><hp:run><hp:t>원문</hp:t></hp:run></hp:p>')
    apply_hwpx(source, {"type": "create_field", "entry": "Contents/section0.xml",
                        "paragraph": 0, "start": 0, "end": 2, "name": "F"})
    occurrence = analyze_hwpx(source)["fields"][0]["occurrences"][0]
    captured = capture_semantic("hwpx", source, {"kind": "field", "entry": occurrence["entry"],
                                                 "occurrence": occurrence["occurrence"],
                                                 "pairing_id": occurrence["pairing_id"]})
    target = _pkg('<hp:p><hp:run><hp:t>기존</hp:t></hp:run></hp:p>')
    destination = {"entry": "Contents/section0.xml", "paragraph": 0, "start": 0, "end": 0}
    target.entries["Contents/header.xml"] = b"<header/>"
    with pytest.raises(ValueError, match="서식 참조"):
        paste_semantic("hwpx", target, captured, destination)
    del target.entries["Contents/header.xml"]
    target.entries["Contents/section0.xml"] = target.entries["Contents/section0.xml"].replace(
        b"<hp:t>", b"<hp:tab/><hp:t>")
    with pytest.raises(ValueError, match="복합 문단"):
        paste_semantic("hwpx", target, captured, destination)


def test_native_semantic_transfer_requires_link_and_can_paste_body_without_meaning() -> None:
    source = _pkg('<hp:p><hp:run><hp:t>값</hp:t></hp:run></hp:p>'
                  '<hp:p><hp:run><hp:t>여기</hp:t></hp:run></hp:p>')
    apply_hwpx(source, {"type": "create_field", "entry": "Contents/section0.xml",
                        "paragraph": 0, "start": 0, "end": 1, "name": "F"})
    occurrence = analyze_hwpx(source)["fields"][0]["occurrences"][0]
    captured = capture_semantic("hwpx", source, {"kind": "field", "entry": occurrence["entry"],
                                                 "occurrence": occurrence["occurrence"],
                                                 "pairing_id": occurrence["pairing_id"]})
    destination = {"entry": "Contents/section0.xml", "paragraph": 1, "start": 0, "end": 0}
    with pytest.raises(ValueError, match="기존 필드 연결"):
        paste_semantic("hwpx", source, captured, destination)
    linked, _ = paste_semantic("hwpx", source, captured, destination | {"link_existing": True})
    assert analyze_hwpx(linked)["fields"][0]["count"] == 2
    slot_source = _pkg('<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>')
    apply_hwpx(slot_source, {"type": "create_slot", "entry": "Contents/section0.xml",
                             "start_paragraph": 0, "end_paragraph": 0, "id": "s"})
    block = capture_semantic("hwpx", slot_source, {"kind": "slot", "slot_id": "s"})
    target = _pkg('<hp:p><hp:run><hp:t>앞</hp:t></hp:run></hp:p>')
    plain, _ = paste_semantic("hwpx", target, block,
                              {"entry": "Contents/section0.xml", "destination_paragraph": 1,
                               "start": 0}, with_meaning=False)
    assert analyze_hwpx(plain)["slots"] == []
    assert "본문" in "".join(_root(plain).itertext())


def test_native_semantic_transfer_refuses_unrepresentable_field_content() -> None:
    source = _pkg('<hp:p><hp:run><hp:t>값</hp:t></hp:run></hp:p>')
    apply_hwpx(source, {"type": "create_field", "entry": "Contents/section0.xml",
                        "paragraph": 0, "start": 0, "end": 1, "name": "F"})
    root = _root(source)
    content_run = next(run for run in root.iter(f"{{{HP}}}run") if run.find(f"{{{HP}}}t") is not None)
    control = etree.Element(f"{{{HP}}}ctrl")
    etree.SubElement(control, f"{{{HP}}}tab")
    content_run.insert(len(content_run) - 1, control)
    source.entries["Contents/section0.xml"] = etree.tostring(root)
    occurrence = analyze_hwpx(source)["fields"][0]["occurrences"][0]
    assert "start" not in occurrence and "end" not in occurrence
    captured = capture_semantic("hwpx", source, {"kind": "field", "entry": occurrence["entry"],
                                                 "occurrence": occurrence["occurrence"],
                                                 "pairing_id": occurrence["pairing_id"]})
    target = _pkg('<hp:p><hp:run><hp:t>여기</hp:t></hp:run></hp:p>')
    before = target.entries["Contents/section0.xml"]
    with pytest.raises(ValueError, match="지원하지 않는 제어 요소"):
        paste_semantic("hwpx", target, captured,
                       {"entry": "Contents/section0.xml", "paragraph": 0, "start": 0, "end": 0})
    assert target.entries["Contents/section0.xml"] == before


def test_native_transfer_refuses_stale_source_and_unsafe_target_ranges() -> None:
    source = _pkg('<hp:p><hp:run><hp:t>값</hp:t></hp:run></hp:p>')
    apply_hwpx(source, {"type": "create_field", "entry": "Contents/section0.xml",
                        "paragraph": 0, "start": 0, "end": 1, "name": "F"})
    occurrence = analyze_hwpx(source)["fields"][0]["occurrences"][0]
    selector = {"kind": "field", "entry": occurrence["entry"],
                "occurrence": occurrence["occurrence"], "pairing_id": occurrence["pairing_id"]}
    captured = capture_semantic("hwpx", source, selector)
    target = _pkg('<hp:p><hp:run><hp:t>여기</hp:t></hp:run></hp:p>')
    before = target.entries["Contents/section0.xml"]
    destination = {"entry": "Contents/section0.xml", "paragraph": 0, "start": 0, "end": 0}
    invalid_sources = (
        ({"occurrence": 50}, "필드 위치"),
        ({"pairing_id": "stale"}, "사용 위치가 바뀌"),
        ({"entry": "Contents/missing.xml"}, "문서 영역"),
    )
    for override, message in invalid_sources:
        with pytest.raises(ValueError, match=message):
            paste_semantic("hwpx", target,
                           captured | {"selector": selector | override}, destination)
    invalid_destinations = (
        ({"entry": "Contents/missing.xml"}, "문서 영역"),
        ({"paragraph": 1}, "문단을 확인"),
        ({"start": 2, "end": 1}, "문자 범위"),
        ({"start": 3, "end": 3}, "문단 밖"),
    )
    for override, message in invalid_destinations:
        with pytest.raises(ValueError, match=message):
            paste_semantic("hwpx", target, captured, destination | override)
    assert target.entries["Contents/section0.xml"] == before
    malformed = _pkg('<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="열림"/></hp:ctrl>'
                     '<hp:t>본문</hp:t></hp:run></hp:p>')
    with pytest.raises(ValueError, match="구조 오류"):
        paste_semantic("hwpx", malformed, captured, destination)
    with pytest.raises(ValueError, match="복사한 의미 데이터"):
        paste_semantic("hwpx", target, {"media": "hwpx"}, destination)
    with pytest.raises(ValueError, match="의미 요소"):
        capture_semantic("hwpx", source, selector | {"pairing_id": "stale"})


def test_native_block_transfer_refuses_content_it_cannot_copy_losslessly() -> None:
    target = _pkg('<hp:p><hp:run><hp:t>대상</hp:t></hp:run></hp:p>')
    destination = {"entry": "Contents/section0.xml", "destination_paragraph": 1, "start": 0}
    for shape, message in (("outside", "문단 일부"), ("table", "복합 문서 요소"),
                           ("control", "지원하지 않는 제어")):
        source = _pkg('<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>')
        apply_hwpx(source, {"type": "create_slot", "entry": "Contents/section0.xml",
                            "start_paragraph": 0, "end_paragraph": 0, "id": "s"})
        root = _root(source)
        paragraph = root.find(f"{{{HP}}}p")
        assert paragraph is not None
        run = paragraph.find(f"{{{HP}}}run")
        assert run is not None
        if shape == "outside":
            leading = etree.Element(f"{{{HP}}}t")
            leading.text = "범위 밖"
            run.insert(0, leading)
        elif shape == "table":
            paragraph.insert(0, etree.Element(f"{{{HP}}}tbl"))
        else:
            control = etree.Element(f"{{{HP}}}ctrl")
            etree.SubElement(control, f"{{{HP}}}tab")
            run.insert(1, control)
        source.entries["Contents/section0.xml"] = etree.tostring(root)
        captured = capture_semantic("hwpx", source, {"kind": "slot", "slot_id": "s"})
        with pytest.raises(ValueError, match=message):
            paste_semantic("hwpx", target, captured, destination)


def test_native_authoring_field_preserves_mixed_run_and_text_attributes():
    pkg = _pkg(
        '<hp:p><hp:run charPrIDRef="1"><hp:t custom="a">앞 원</hp:t>'
        '<hp:t custom="b">문</hp:t></hp:run>'
        '<hp:run charPrIDRef="2"><hp:t custom="c">구 뒤</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(pkg, {"type": "create_field", "entry": "Contents/section0.xml",
                     "paragraph": 0, "start": 2, "end": 5, "name": "내용"})
    root = _root(pkg)
    assert "".join(node.text or "" for node in root.iter(f"{{{HP}}}t")) == "앞 원문구 뒤"
    assert [(node.get("custom"), node.text) for node in root.iter(f"{{{HP}}}t")] == [
        ("a", "앞 "), ("a", "원"), ("b", "문"), ("c", "구"), ("c", " 뒤")]
    assert extract_schema(pkg).field_names() == ["내용"]
    occurrence = analyze_hwpx(pkg)["fields"][0]["occurrences"][0]
    assert (occurrence["start"], occurrence["end"]) == (2, 5)


def test_native_field_rename_relink_and_unset_are_occurrence_scoped() -> None:
    pkg = _pkg(
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="1" fieldid="2" name="F" type="CLICK_HERE"/>'
        '</hp:ctrl><hp:t>가</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="1" fieldid="2"/></hp:ctrl></hp:run></hp:p>'
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="3" fieldid="4" name="F" type="CLICK_HERE"/>'
        '</hp:ctrl><hp:t>나</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="3" fieldid="4"/></hp:ctrl></hp:run></hp:p>'
    )
    entry = "Contents/section0.xml"
    apply_hwpx(pkg, {"type": "rename_field", "old_name": "F", "name": "G"})
    assert analyze_hwpx(pkg)["fields"][0]["count"] == 2
    with pytest.raises(ValueError, match="다시 선택"):
        apply_hwpx(pkg, {"type": "relink_field", "entry": entry, "occurrence": 0,
                         "pairing_id": "3", "name": "잘못된 대상"})
    apply_hwpx(pkg, {"type": "relink_field", "entry": entry, "occurrence": 0, "name": "H"})
    assert {field["name"] for field in analyze_hwpx(pkg)["fields"]} == {"G", "H"}
    apply_hwpx(pkg, {"type": "unset_field", "entry": entry, "occurrence": 1, "text": "남김"})
    assert [field["name"] for field in analyze_hwpx(pkg)["fields"]] == ["H"]
    assert "남김" in "".join(_root(pkg).itertext())


def test_native_authoring_slot_uses_product_bookmark():
    pkg = _pkg('<hp:p><hp:run><hp:t>공통 문장</hp:t></hp:run></hp:p>')
    result, impact = apply_hwpx(pkg, {
        "type": "create_slot", "entry": "Contents/section0.xml",
        "start_paragraph": 0, "end_paragraph": 0, "start": 1, "end": 2,
        "id": "특약", "label": "특약 사항",
    })
    assert impact["expanded"] is True
    assert impact["included"] == "공통 문장"
    assert "공통 문장" in impact["before"]
    assert [(slot["id"], slot["label"], slot["options"])
            for slot in analyze_hwpx(result)["slots"]] == [("특약", "특약 사항", [])]
    assert analyze_hwpx(result)["slots"][0]["raw"]["meta_tags"]
    result, _ = apply_hwpx(result, {"type": "rename_slot", "slot_id": "특약", "id": "추가", "label": "추가 사항"})
    assert [(slot["id"], slot["label"], slot["options"])
            for slot in analyze_hwpx(result)["slots"]] == [("추가", "추가 사항", [])]


def test_native_authoring_option_and_identifier_roundtrip():
    pkg = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="12" fieldid="13" name="F"'
        ' type="CLICK_HERE"/></hp:ctrl><hp:t>A</hp:t><hp:ctrl><hp:fieldEnd'
        ' beginIDRef="12" fieldid="13"/></hp:ctrl></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>B</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(pkg, {"type": "create_slot", "entry": "Contents/section0.xml",
                     "start_paragraph": 0, "end_paragraph": 2, "id": "s"})
    apply_hwpx(pkg, {"type": "create_option", "entry": "Contents/section0.xml",
                     "start_paragraph": 1, "end_paragraph": 1, "slot_id": "s", "id": "a"})
    apply_hwpx(pkg, {"type": "create_option", "entry": "Contents/section0.xml",
                     "start_paragraph": 2, "end_paragraph": 2, "slot_id": "s", "id": "b"})
    apply_hwpx(pkg, {"type": "adjust_range", "kind": "option", "slot_id": "s",
                     "option_id": "a", "start_paragraph": 0, "end_paragraph": 1})
    apply_hwpx(pkg, {"type": "rename_slot", "slot_id": "s", "id": "terms"})
    apply_hwpx(pkg, {"type": "rename_option", "slot_id": "terms", "option_id": "a", "id": "first"})
    assert [item["id"] for item in analyze_hwpx(pkg)["slots"][0]["options"]] == ["first", "b"]
    checked = trial_hwpx(pkg, {"F": "값"}, {"terms": "first"})
    assert checked["excluded"][0]["option_id"] == "b"
    assert search_hwpx(pkg, "first", "structure")["hits"][0]["option_id"] == "first"
    apply_hwpx(pkg, {"type": "duplicate", "kind": "slot", "slot_id": "terms",
                     "new_id": "terms_copy", "destination_paragraph": 3,
                     "destination_entry": "Contents/section0.xml"})
    assert [slot["id"] for slot in analyze_hwpx(pkg)["slots"]] == ["terms", "terms_copy"]
    assert analyze_hwpx(pkg)["fields"][0]["count"] == 2
    begins = [node.get("id") for node in _root(pkg).iter(f"{{{HP}}}fieldBegin")]
    assert len(begins) == len(set(begins))
    # 복제본의 하위 선택 책갈피도 `slot/option` 구분자를 지킨다 — 빠지면 복제본 개명이 하위를 못 찾는다.
    names = {node.get("name") for node in _root(pkg).iter(f"{{{HP}}}fieldBegin") if "/" in (node.get("name") or "")}
    assert {"terms_copy/first", "terms_copy/b"} <= names, names
    apply_hwpx(pkg, {"type": "rename_slot", "slot_id": "terms_copy", "id": "terms2"})
    assert [item["id"] for item in analyze_hwpx(pkg)["slots"][1]["options"]] == ["first", "b"]
    apply_hwpx(pkg, {"type": "rename_slot", "slot_id": "terms2", "id": "terms_copy"})
    apply_hwpx(pkg, {"type": "move", "kind": "slot", "slot_id": "terms_copy",
                     "destination_paragraph": 0, "destination_entry": "Contents/section0.xml"})
    assert [slot["id"] for slot in analyze_hwpx(pkg)["slots"]] == ["terms_copy", "terms"]
    with pytest.raises(ValueError, match="문단 시작"):
        apply_hwpx(pkg, {"type": "duplicate", "kind": "slot", "slot_id": "terms",
                         "new_id": "bad", "destination_paragraph": 0, "start": 1})


def test_native_analysis_keeps_malformed_and_nested_text_accessible():
    pkg = _pkg(
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="미완"/></hp:ctrl>'
        '<hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>셀 내용</hp:t>'
        '</hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝 문장</hp:t></hp:run></hp:p>'
    )
    detail = analyze_hwpx(pkg)
    assert any(item["kind"] == "unmatched-begin" for item in detail["diagnostics"])
    assert next(item for item in detail["diagnostics"] if item["kind"] == "unmatched-begin")["location"] == {
        "entry": "Contents/section0.xml", "paragraph": 0}
    assert next(item for item in detail["diagnostics"] if item["kind"] == "unmatched-begin")["message"] == "닫는 필드 경계가 없습니다."
    with pytest.raises(ValueError, match="구조 오류"):
        capture_semantic("hwpx", pkg, {"kind": "field", "entry": "Contents/section0.xml",
                                        "occurrence": 0, "pairing_id": None})
    assert search_hwpx(pkg, "끝")["hits"][0]["paragraph"] == 1
    nested = search_hwpx(pkg, "셀")["hits"][0]
    # 셀 문단은 rhwp 셀 경로로 주소화된다 — 미완 fieldBegin ctrl 이 control 0, 표가 control 1.
    assert nested["paragraph"] == 0 and nested["paragraph_path"]
    assert nested["cell_path"] == [{"parent_paragraph": 0, "control": 1, "cell": 0, "paragraph": 0}]


def test_native_authoring_duplicates_option_without_cloning_parent_boundary():
    pkg = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>가</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>나</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(pkg, {"type": "create_slot", "entry": "Contents/section0.xml",
                     "start_paragraph": 0, "end_paragraph": 2, "id": "s"})
    apply_hwpx(pkg, {"type": "create_option", "entry": "Contents/section0.xml",
                     "start_paragraph": 1, "end_paragraph": 1, "slot_id": "s", "id": "a"})
    apply_hwpx(pkg, {"type": "create_option", "entry": "Contents/section0.xml",
                     "start_paragraph": 2, "end_paragraph": 2, "slot_id": "s", "id": "b"})
    apply_hwpx(pkg, {"type": "duplicate", "kind": "option", "slot_id": "s", "option_id": "a",
                     "new_id": "a_copy", "destination_paragraph": 2})
    assert [item["id"] for item in analyze_hwpx(pkg)["slots"][0]["options"]] == ["a", "a_copy", "b"]
    apply_hwpx(pkg, {"type": "duplicate", "kind": "option", "slot_id": "s", "option_id": "b",
                     "new_id": "b_copy"})
    assert [item["id"] for item in analyze_hwpx(pkg)["slots"][0]["options"]] == [
        "a", "a_copy", "b", "b_copy"]


def test_native_structure_unwrap_delete_and_trial_use_actual_output() -> None:
    xml = (
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>첫째</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>둘째</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    package = _pkg(xml)
    apply_hwpx(package, {"type": "create_slot", "entry": "Contents/section0.xml",
                         "start_paragraph": 0, "end_paragraph": 2, "id": "s"})
    for index, identifier in ((1, "a"), (2, "b")):
        apply_hwpx(package, {"type": "create_option", "entry": "Contents/section0.xml",
                             "start_paragraph": index, "end_paragraph": index,
                             "slot_id": "s", "id": identifier})
    before = package.entries["Contents/section0.xml"]
    with pytest.raises(ValueError, match="시험 선택"):
        trial_hwpx(package, {}, {})
    trial = trial_hwpx(package, {}, {"s": "b"})
    assert package.entries["Contents/section0.xml"] == before
    assert [(item["option_id"], item["selected_option_id"]) for item in trial["excluded"]] == [("a", "b")]
    assert trial["excluded"][0]["source"]["entry"] == "Contents/section0.xml"
    output = HwpxPackage.from_bytes(trial["bytes"])
    output_text = "".join(_root(output).itertext())
    assert "첫째" not in output_text and "둘째" in output_text

    with pytest.raises(ValueError, match="하위 선택"):
        apply_hwpx(package, {"type": "unwrap", "kind": "slot", "slot_id": "s"})
    apply_hwpx(package, {"type": "unwrap", "kind": "option", "slot_id": "s", "option_id": "a"})
    assert "첫째" in "".join(_root(package).itertext())
    apply_hwpx(package, {"type": "delete", "kind": "option", "slot_id": "s", "option_id": "b"})
    assert "둘째" not in "".join(_root(package).itertext())
    apply_hwpx(package, {"type": "unwrap", "kind": "slot", "slot_id": "s"})
    assert analyze_hwpx(package)["slots"] == []
    assert "첫째" in "".join(_root(package).itertext())

    deleting = _pkg(xml)
    apply_hwpx(deleting, {"type": "create_slot", "entry": "Contents/section0.xml",
                          "start_paragraph": 0, "end_paragraph": 2, "id": "s"})
    apply_hwpx(deleting, {"type": "delete", "kind": "slot", "slot_id": "s"})
    assert "공통" not in "".join(_root(deleting).itertext())
    assert "끝" in "".join(_root(deleting).itertext())


def test_native_trial_does_not_require_values_only_in_excluded_option() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>첫 값</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>둘째</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_field", "entry": entry,
                         "paragraph": 1, "start": 0, "end": 3, "name": "첫필드"})
    apply_hwpx(package, {"type": "create_slot", "entry": entry,
                         "start_paragraph": 0, "end_paragraph": 2, "id": "s"})
    for index, identifier in ((1, "a"), (2, "b")):
        apply_hwpx(package, {"type": "create_option", "entry": entry,
                             "start_paragraph": index, "end_paragraph": index,
                             "slot_id": "s", "id": identifier})
    rendered = trial_hwpx(package, {}, {"s": "b"})
    assert rendered["report"]["missing_fields"] == []
    assert rendered["occurrences"] == []
    assert "둘째" in "".join(_root(HwpxPackage.from_bytes(rendered["bytes"])).itertext())


def test_native_structure_command_boundaries_fail_without_mutating_source() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>선택</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>뒤</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    entry = "Contents/section0.xml"
    apply_hwpx(package, {"type": "create_slot", "entry": entry,
                         "start_paragraph": 0, "end_paragraph": 2, "id": "s"})
    apply_hwpx(package, {"type": "create_option", "entry": entry,
                         "start_paragraph": 1, "end_paragraph": 1, "slot_id": "s", "id": "a"})
    before = package.entries[entry]
    cases = (
        ({"type": "create_option", "entry": entry, "start_paragraph": 1,
          "end_paragraph": 1, "slot_id": "missing", "id": "b"}, "상위 항목"),
        ({"type": "create_option", "entry": entry, "start_paragraph": 1,
          "end_paragraph": 1, "slot_id": "s", "id": "a"}, "식별자"),
        ({"type": "rename_option", "slot_id": "s", "option_id": "missing", "id": "b"}, "영역을 찾"),
        ({"type": "adjust_range", "kind": "option", "slot_id": "s", "option_id": "a",
          "start_paragraph": 3, "end_paragraph": 3}, "상위 항목"),
        ({"type": "adjust_range", "kind": "slot", "slot_id": "s",
          "start_paragraph": 0, "end_paragraph": 0}, "하위 선택"),
        ({"type": "move", "kind": "slot", "slot_id": "s", "destination_paragraph": 1}, "현재 영역"),
        ({"type": "move", "kind": "slot", "slot_id": "s", "destination_paragraph": 9}, "문단 경계"),
        ({"type": "move", "kind": "slot", "slot_id": "s", "destination_paragraph": 4,
          "destination_entry": "Contents/section1.xml"}, "다른 문서 영역"),
        ({"type": "duplicate", "kind": "slot", "slot_id": "s", "new_id": "s"}, "같은 이름"),
        ({"type": "duplicate", "kind": "slot", "slot_id": "s", "new_id": "other",
          "destination_entry": "Contents/section1.xml"}, "다른 문서 영역"),
        ({"type": "duplicate", "kind": "option", "slot_id": "s", "option_id": "a",
          "new_id": "b", "destination_paragraph": 4}, "같은 항목"),
    )
    for command, message in cases:
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command)
        assert package.entries[entry] == before

    apply_hwpx(package, {"type": "adjust_range", "kind": "slot", "slot_id": "s",
                         "start_paragraph": 0, "end_paragraph": 3})
    apply_hwpx(package, {"type": "adjust_range", "kind": "option", "slot_id": "s",
                         "option_id": "a", "start_paragraph": 0, "end_paragraph": 1})
    assert analyze_hwpx(package)["slots"][0]["options"][0]["location"] == {
        "entry": entry, "start_paragraph": 0, "end_paragraph": 1}
    apply_hwpx(package, {"type": "adjust_range", "kind": "option", "slot_id": "s",
                         "option_id": "a", "start_paragraph": 2, "end_paragraph": 3})
    assert analyze_hwpx(package)["slots"][0]["options"][0]["location"]["end_paragraph"] == 3


def test_native_rename_preserves_bookmark_identity_and_rejects_collisions() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>A</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>B</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>다른 항목</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_slot", "entry": entry,
                         "start_paragraph": 0, "end_paragraph": 2, "id": "s"})
    for index, identifier in ((1, "a"), (2, "b")):
        apply_hwpx(package, {"type": "create_option", "entry": entry,
                             "start_paragraph": index, "end_paragraph": index,
                             "slot_id": "s", "id": identifier})
    apply_hwpx(package, {"type": "create_slot", "entry": entry,
                         "start_paragraph": 3, "end_paragraph": 3, "id": "t"})
    original_ids = [node.get("id") for node in _root(package).iter(f"{{{HP}}}fieldBegin")]
    for command, message in (
        ({"type": "rename_slot", "slot_id": "s", "id": "t"}, "이미 있습니다"),
        ({"type": "rename_option", "slot_id": "s", "option_id": "a", "id": "b"}, "이미 있습니다"),
    ):
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command)
    apply_hwpx(package, {"type": "rename_slot", "slot_id": "s", "id": "s2", "label": "새 항목"})
    apply_hwpx(package, {"type": "rename_option", "slot_id": "s2", "option_id": "a",
                         "id": "first", "label": "첫 선택"})
    detail = analyze_hwpx(package)
    assert (detail["slots"][0]["id"], detail["slots"][0]["label"]) == ("s2", "새 항목")
    assert [(item["id"], item["label"]) for item in detail["slots"][0]["options"]] == [
        ("first", "첫 선택"), ("b", "")]
    assert [node.get("id") for node in _root(package).iter(f"{{{HP}}}fieldBegin")] == original_ids


def test_native_create_region_requires_valid_ids_labels_and_parent() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>선택</hp:t></hp:run></hp:p>'
    )
    command = {"type": "create_slot", "entry": entry,
               "start_paragraph": 0, "end_paragraph": 1, "id": "s"}
    before = package.entries[entry]
    for override, message in (
        ({"id": ""}, "식별자"),
        ({"label": 3}, "표시 이름"),
        ({"entry": None}, "문단 범위"),
    ):
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command | override)
        assert package.entries[entry] == before
    apply_hwpx(package, command)
    with pytest.raises(ValueError, match="이미 있습니다"):
        apply_hwpx(package, command)
    with pytest.raises(ValueError, match="상위 항목"):
        apply_hwpx(package, {"type": "create_option", "entry": entry,
                             "start_paragraph": 1, "end_paragraph": 1,
                             "slot_id": "missing", "id": "a"})


def test_native_duplicate_refuses_complex_block_without_losing_original() -> None:
    entry = "Contents/section0.xml"
    package = _pkg('<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>')
    apply_hwpx(package, {"type": "create_slot", "entry": entry,
                         "start_paragraph": 0, "end_paragraph": 0, "id": "s"})
    root = _root(package)
    paragraph = root.find(f"{{{HP}}}p")
    assert paragraph is not None
    paragraph.append(etree.Element(f"{{{HP}}}tbl"))
    package.entries[entry] = etree.tostring(root)
    before = package.entries[entry]
    with pytest.raises(ValueError, match="복제할 수 없는 문서 요소"):
        apply_hwpx(package, {"type": "duplicate", "kind": "slot", "slot_id": "s",
                             "new_id": "copy", "destination_paragraph": 1})
    assert package.entries[entry] == before


def test_native_field_selection_refuses_ambiguous_or_invalid_ranges() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:t>앞뒤</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>다음</hp:t></hp:run></hp:p>'
    )
    before = package.entries[entry]
    base = {"type": "create_field", "entry": entry, "paragraph": 0,
            "start": 0, "end": 1, "name": "F"}
    cases = (
        ({"entry": "Contents/missing.xml"}, "문서 영역"),
        ({"paragraph": 3}, "문단이 문서 영역 밖"),
        ({"start": -1}, "문단 밖"),
        ({"end": 9}, "문단 밖"),
        ({"end_paragraph": 1}, "여러 문단"),
        ({"name": "#F"}, "문법 기호"),
    )
    for override, message in cases:
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, base | override)
        assert package.entries[entry] == before

    controlled = _pkg('<hp:p><hp:run><hp:ctrl><hp:tab/></hp:ctrl><hp:t>본문</hp:t></hp:run></hp:p>')
    with pytest.raises(ValueError, match="제어 요소"):
        apply_hwpx(controlled, base)
    empty = _pkg('<hp:p><hp:run><hp:ctrl><hp:tab/></hp:ctrl></hp:run></hp:p>')
    with pytest.raises(ValueError, match="편집 가능한 텍스트"):
        apply_hwpx(empty, base | {"end": 0})


def test_native_field_name_and_occurrence_edits_are_stale_safe() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:t>첫째</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>둘째</hp:t></hp:run></hp:p>'
    )
    for index, name in ((0, "F"), (1, "G")):
        apply_hwpx(package, {"type": "create_field", "entry": entry,
                             "paragraph": index, "start": 0, "end": 2, "name": name})
    before = package.entries[entry]
    cases = (
        ({"type": "rename_field", "old_name": "F", "name": "G"}, "‘G’ 필드가 이미 있습니다"),
        ({"type": "rename_field", "old_name": "missing", "name": "N"}, "찾을 수"),
        ({"type": "relink_field", "entry": entry, "occurrence": 5, "name": "N"}, "찾을 수"),
        ({"type": "relink_field", "entry": entry, "occurrence": 0,
          "pairing_id": "stale", "name": "N"}, "바뀌었"),
        ({"type": "unset_field", "entry": entry, "occurrence": 0}, "본문을 입력"),
    )
    for command, message in cases:
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command)
        assert package.entries[entry] == before


def test_native_search_and_trial_report_semantic_locations_and_missing_inputs() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_field", "entry": entry,
                         "paragraph": 1, "start": 0, "end": 2, "name": "이름"})
    field_only = HwpxPackage.from_bytes(package.to_bytes())
    apply_hwpx(package, {"type": "create_slot", "entry": entry,
                         "start_paragraph": 0, "end_paragraph": 1, "id": "s", "label": "공통 항목"})
    assert search_hwpx(package, "이름", "field")["hits"][0]["paragraph"] == 1
    assert search_hwpx(package, "공통 항목", "structure")["hits"][0]["start_paragraph"] == 0
    with pytest.raises(ValueError, match="검색어"):
        search_hwpx(package, "")
    with pytest.raises(ValueError, match="검색 종류"):
        search_hwpx(package, "본문", "unknown")
    with pytest.raises(ValueError, match="시험값"):
        trial_hwpx(package, {}, {})
    with pytest.raises(ValueError, match="존재하지 않는 항목"):
        trial_hwpx(package, {"이름": "A"}, {"missing": "x"})
    with pytest.raises(ValueError, match="문서 구조 오류"):
        trial_hwpx(package, {"이름": "A"}, {})
    rendered = trial_hwpx(field_only, {"이름": "A"}, {})
    assert rendered["occurrences"][0]["source"]["paragraph"] == 1
    assert rendered["occurrences"][0]["output"]["paragraph"] == 1
    empty = trial_hwpx(field_only, {"이름": None}, {})
    assert empty["report"]["empty_fields"] == ["이름"]


def test_native_field_path_targets_exact_table_cell_paragraph() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>'
        '<hp:p><hp:run><hp:t>셀값</hp:t></hp:run></hp:p>'
        '</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
    )
    root = _root(package)
    nested = next(node for node in root.iter(f"{{{HP}}}p") if node.getparent().tag == f"{{{HP}}}subList")
    path = root.getroottree().getpath(nested)
    with pytest.raises(ValueError, match="문단의 위치"):
        apply_hwpx(package, {"type": "create_field", "entry": entry,
                             "paragraph_path": "/missing", "start": 0, "end": 2, "name": "셀"})
    apply_hwpx(package, {"type": "create_field", "entry": entry,
                         "paragraph_path": path, "start": 0, "end": 2, "name": "셀"})
    occurrence = analyze_hwpx(package)["fields"][0]["occurrences"][0]
    assert occurrence["paragraph"] == 0 and occurrence["paragraph_path"] == path
    assert occurrence["cell_path"] == [{"parent_paragraph": 0, "control": 0, "cell": 0, "paragraph": 0}]
    assert occurrence["start"] == 0 and occurrence["end"] == 2


def test_native_analysis_separates_invalid_and_nonfillable_field_controls() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="1" beginIDRef="1"'
        ' type="CLICK_HERE" name=""/></hp:ctrl><hp:t>빈 이름</hp:t>'
        '<hp:ctrl><hp:fieldEnd beginIDRef="1"/></hp:ctrl></hp:run></hp:p>'
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="2" type="HYPERLINK" name="url"/>'
        '</hp:ctrl><hp:t>링크</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="2"/>'
        '</hp:ctrl></hp:run></hp:p>'
    )
    detail = analyze_hwpx(package)
    assert detail["fields"] == []
    invalid = next(item for item in detail["diagnostics"] if item["kind"] == "invalid-field-id")
    assert invalid["location"] == {"entry": "Contents/section0.xml", "paragraph": 0}


def test_native_structure_diagnostic_location_is_only_projected_when_unique() -> None:
    marker = '<hp:p><hp:run><hp:t>{{/항목}}</hp:t></hp:run></hp:p>'
    unique = analyze_hwpx(_pkg(marker + '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'))
    item = next(row for row in unique["diagnostics"] if row["kind"] == "unbalanced_marker")
    assert item["location"] == {"entry": "Contents/section0.xml", "paragraph": 0}
    duplicated = analyze_hwpx(_pkg(marker + marker))
    assert all(row["location"] is None for row in duplicated["diagnostics"]
               if row["kind"] == "unbalanced_marker")
    for row in duplicated["diagnostics"] + unique["diagnostics"]:
        assert (row["severity"], row["category"]) == ("error", "structure")
        assert row["actions"][0] == {"label": "원문으로 이동", "kind": "navigate", "location": row["location"]}


def test_native_problem_taxonomy_covers_field_and_bookmark_diagnostics() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="1" type="CLICK_HERE" name=""/></hp:ctrl>'
        '<hp:t>빈 이름</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="1"/></hp:ctrl></hp:run></hp:p>'
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="2" type="BOOKMARK" name="s">'
        '<hp:metaTag>{bad json</hp:metaTag></hp:fieldBegin></hp:ctrl><hp:t>본문</hp:t>'
        '<hp:ctrl><hp:fieldEnd beginIDRef="2"/></hp:ctrl></hp:run></hp:p>'
    )
    detail = analyze_hwpx(package)
    kinds = {item["kind"] for item in detail["diagnostics"]}
    assert {"invalid-field-id", "malformed-json"} <= kinds
    for item in detail["diagnostics"]:
        assert item["severity"] in {"error", "warning"} and item["category"] in {"structure", "compatibility", "authoring"}
        assert "target" in item and "location" in item and item["actions"]
        assert item["actions"][0]["kind"] == "navigate"
    invalid = next(item for item in detail["diagnostics"] if item["kind"] == "invalid-field-id")
    assert invalid["actions"][1]["kind"] == "command"
    assert invalid["actions"][1]["command"] == {"type": "unset_field", "entry": "Contents/section0.xml",
                                                "occurrence": 0, "pairing_id": "1", "text": "빈 이름"}
    bookmark = next(item for item in detail["diagnostics"] if "BOOKMARK 's'" in item["message"])
    assert bookmark["target"] == "s" and bookmark["location"] == {"entry": "Contents/section0.xml", "paragraph": 1}


def _slot_package() -> HwpxPackage:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통 값</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>첫째</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>둘째</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 0, "start": 3, "end": 4, "name": "F"})
    apply_hwpx(package, {"type": "create_slot", "entry": entry, "start_paragraph": 0,
                         "end_paragraph": 2, "id": "s", "label": "특약"})
    for index, identifier, label in ((1, "a", None), (2, "b", "둘")):
        apply_hwpx(package, {"type": "create_option", "entry": entry, "start_paragraph": index,
                             "end_paragraph": index, "slot_id": "s", "id": identifier, "label": label})
    return package


def test_native_unwrap_cascade_lists_children_and_unwraps_options_in_one_apply() -> None:
    package = _slot_package()
    before = package.entries["Contents/section0.xml"]
    projected = preview_hwpx(package, {"type": "unwrap", "kind": "slot", "slot_id": "s"})
    assert projected["requires_cascade"] is True
    assert [(child["kind"], child["id"], child["label"]) for child in projected["children"]] == [
        ("option", "a", "a"), ("option", "b", "둘"), ("field", "F", "F")]
    assert projected["counts"] == {"paragraphs": 3, "fields": 1, "options": 2, "tables": 0}
    assert projected["included"] == "공통 값\n첫째\n둘째" and projected["label"] == "‘특약’ 항목 의미만 해제"
    assert projected["result"]["slots"] == [] and package.entries["Contents/section0.xml"] == before
    with pytest.raises(CascadeRequired) as refused:
        apply_hwpx(package, {"type": "unwrap", "kind": "slot", "slot_id": "s"})
    assert [child["id"] for child in refused.value.children] == ["a", "b"]
    assert package.entries["Contents/section0.xml"] == before
    apply_hwpx(package, {"type": "unwrap", "kind": "slot", "slot_id": "s", "cascade": True})
    detail = analyze_hwpx(package)
    assert detail["slots"] == [] and detail["diagnostics"] == [] and detail["fields"][0]["count"] == 1
    assert "".join(_root(package).itertext()) == "공통 값첫째둘째끝"
    deleted = preview_hwpx(_slot_package(), {"type": "delete", "kind": "option", "slot_id": "s", "option_id": "b"})
    assert deleted["children"] == [] and deleted["counts"]["paragraphs"] == 1
    assert deleted["label"] == "‘둘’ 선택 내용까지 삭제" and deleted["included"] == "둘째"
    renamed = preview_hwpx(_slot_package(), {"type": "rename_slot", "slot_id": "s", "id": "terms"})
    assert renamed["label"] == "‘특약’ 항목 속성 변경"


def test_native_create_field_links_existing_name_and_rename_conflict_is_structured() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:t>첫째</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>둘째</hp:t></hp:run></hp:p>'
    )
    first = preview_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 0,
                                   "start": 0, "end": 2, "name": "F"})
    assert (first["links_existing"], first["existing_count"], first["candidates"]) == (False, 0, [])
    assert first["label"] == "‘F’을(를) 필드로 만들기"
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 0, "start": 0, "end": 2, "name": "F"})
    linked = preview_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 1,
                                    "start": 0, "end": 2, "name": "F"})
    assert (linked["links_existing"], linked["existing_count"]) == (True, 1)
    assert linked["candidates"] == [{"name": "F", "count": 1}]
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 1, "start": 0, "end": 2, "name": "F"})
    detail = analyze_hwpx(package)
    assert detail["fields"][0]["count"] == 2 and detail["diagnostics"] == []
    pairing = [occurrence["pairing_id"] for occurrence in detail["fields"][0]["occurrences"]]
    assert len(set(pairing)) == 2
    assert trial_hwpx(package, {"F": "값"}, {})["bytes"]
    apply_hwpx(package, {"type": "relink_field", "entry": entry, "occurrence": 1, "name": "G"})
    renamed = preview_hwpx(package, {"type": "rename_field", "old_name": "G", "name": "H"})
    assert (renamed["affected"], renamed["before"], renamed["after"], renamed["label"]) == (1, "G", "H", "‘G’ 이름 변경")
    with pytest.raises(NameConflict) as conflict:
        apply_hwpx(package, {"type": "rename_field", "old_name": "G", "name": "F"})
    assert conflict.value.to_dict() == {
        "code": "name_conflict", "name": "F", "existing_count": 1,
        "message": "‘F’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요."}


def test_native_available_commands_share_txt_vocabulary() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:t>밖</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>공통 값</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>첫째</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>둘째</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 1, "start": 3, "end": 4, "name": "F"})
    apply_hwpx(package, {"type": "create_slot", "entry": entry, "start_paragraph": 1, "end_paragraph": 3, "id": "s"})
    for index, identifier in ((2, "a"), (3, "b")):
        apply_hwpx(package, {"type": "create_option", "entry": entry, "start_paragraph": index,
                             "end_paragraph": index, "slot_id": "s", "id": identifier})

    def decide(selection: dict, context: dict | None = None) -> dict:
        entries = available_commands_hwpx(package, selection, context)
        assert [item["type"] for item in entries] == list(COMMAND_TYPES)
        return {item["type"]: item for item in entries}

    outside = decide({"entry": entry, "paragraph": 0, "start": 0, "end": 1})
    assert outside["create_field"]["enabled"] and outside["create_slot"]["enabled"]
    assert outside["create_option"] == {
        "type": "create_option", "enabled": False,
        "reason": "선택은 항목 안에 만들 수 있습니다. 먼저 항목 안의 내용을 선택하세요.",
        "alternative": {"label": "먼저 항목 만들기", "command_type": "create_slot"}}
    assert outside["rename_field"]["reason"] == "필드를 선택하세요."
    assert outside["delete"]["reason"] == "항목이나 선택 영역을 선택하세요."
    crossing = decide({"entry": entry, "start_paragraph": 0, "end_paragraph": 1, "start": 0, "end": 1})
    assert crossing["create_field"]["reason"] == "이 선택은 여러 독립 영역에 걸쳐 있습니다. 한 범위를 선택하세요."
    assert crossing["create_slot"]["reason"] == "선택 범위가 기존 영역과 겹칩니다. 범위를 다시 고르세요."
    assert crossing["create_option"]["reason"] == "이 선택은 여러 독립 영역에 걸쳐 있습니다. 한 범위를 선택하세요."
    inside = decide({"entry": entry, "paragraph": 1, "start": 0, "end": 0})
    assert inside["create_option"]["enabled"] and inside["unwrap"]["enabled"] and inside["create_slot"]["enabled"] is False
    # A region boundary paragraph starts with the bookmark control, so no field fits there yet.
    assert inside["create_field"]["reason"] == "선택 범위 앞이나 안에 제어 요소가 있어 문자 위치를 확정할 수 없습니다."
    assert inside["rename_field"]["reason"] == "필드를 선택하세요."
    assert inside["rename_option"]["reason"] == "선택 영역을 선택하세요."
    plain = decide({"entry": entry, "paragraph": 0, "start": 0, "end": 1})
    assert plain["create_field"]["enabled"] is True
    on_field = decide({"entry": entry, "paragraph": 1, "start": 3, "end": 4})
    assert all(on_field[kind]["enabled"] for kind in ("rename_field", "relink_field", "unset_field"))
    assert on_field["create_field"]["reason"] == "선택 범위 앞이나 안에 제어 요소가 있어 문자 위치를 확정할 수 없습니다."
    option = decide({"entry": entry, "paragraph": 2, "start": 0, "end": 0}, {"slot_id": "s", "option_id": "a"})
    assert option["rename_option"]["enabled"] and option["create_option"]["reason"] == "선택 범위가 기존 영역과 겹칩니다. 범위를 다시 고르세요."
    two_options = decide({"entry": entry, "start_paragraph": 2, "end_paragraph": 3, "start": 0, "end": 0})
    assert two_options["create_field"]["reason"] == "이 선택은 여러 독립 영역에 걸쳐 있습니다. 한 범위를 선택하세요."
    plain_pair = _pkg('<hp:p><hp:run><hp:t>하나</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>둘</hp:t></hp:run></hp:p>')
    multi = {item["type"]: item for item in available_commands_hwpx(
        plain_pair, {"entry": entry, "start_paragraph": 0, "end_paragraph": 1, "start": 0, "end": 0})}
    assert multi["create_field"]["reason"] == "여러 문단에 걸친 필드는 HWPX 누름틀 경계로 만들 수 없습니다."
    assert multi["create_slot"]["enabled"] is True
    assert all(item["reason"] == "선택 위치가 올바르지 않습니다."
               for item in available_commands_hwpx(package, {"entry": "Contents/missing.xml", "paragraph": 0,
                                                             "start": 0, "end": 0}))


def test_native_syntax_view_renders_fields_and_region_markers_read_only() -> None:
    package = _slot_package()
    before = package.entries["Contents/section0.xml"]
    view = syntax_view_hwpx(package)
    assert package.entries["Contents/section0.xml"] == before
    assert view["note"] is None
    assert view["sections"] == [{"entry": "Contents/section0.xml", "text": (
        "{{#항목 s 특약}}\n공통 {{F}}\n{{#선택 a}}\n첫째\n{{/선택}}\n{{#선택 b 둘}}\n둘째\n{{/선택}}\n{{/항목}}\n끝")}]
    tabled = _pkg(
        '<hp:p><hp:run><hp:t>앞 </hp:t><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>셀</hp:t>'
        '</hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
    )
    tabled_view = syntax_view_hwpx(tabled)
    assert tabled_view["sections"][0]["text"] == "앞 셀"
    assert tabled_view["note"] == "표 안의 문단은 소속된 본문 문단 줄에 이어서 표시됩니다."


# ------------------------------------------------------------- 컴파일 + 라운드트립
def test_compile_makes_token_a_real_field():
    """토큰이 진짜 누름틀이 되어 스키마가 인식한다."""
    xml = '<hp:p><hp:run><hp:t>{{공고명}}</hp:t></hp:run></hp:p>'
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["공고명"]
    assert report.modified is True
    assert extract_schema(pkg).field_names() == ["공고명"]


def test_roundtrip_compile_then_fill():
    """컴파일된 필드를 fields.set_field 로 채우면 값이 들어간다(전체 파이프라인)."""
    xml = '<hp:p><hp:run><hp:t>계약명: {{계약명}} / 예산 {{사업예산}}</hp:t></hp:run></hp:p>'
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명", "사업예산"]

    doc = FieldDocument(pkg.entries["Contents/section0.xml"])
    assert doc.set_field("계약명", "정보시스템 구축") is True
    assert doc.set_field("사업예산", "1억원") is True
    filled = doc.to_bytes().decode("utf-8")
    assert "정보시스템 구축" in filled and "1억원" in filled


def test_surrounding_text_preserved():
    """토큰 전후 평문과 순서가 보존된다."""
    xml = '<hp:p><hp:run><hp:t>앞 {{계약명}} 뒤</hp:t></hp:run></hp:p>'
    pkg, _ = compile_document(_pkg(xml))
    # 문단 전체 텍스트(placeholder 유지)가 원문과 동일해야 한다.
    from hwpxcore.text_extract import extract_document, full_text

    assert full_text(extract_document(pkg)) == "앞 {{계약명}} 뒤"


# ------------------------------------------------------------------- 충실도
def test_generated_field_mirrors_corpus_attrs_and_links():
    """생성 누름틀은 실코퍼스 속성(type=CLICK_HERE 등) + begin/end id 링크를 갖는다."""
    xml = '<hp:p><hp:run charPrIDRef="7"><hp:t>{{계약명}}</hp:t></hp:run></hp:p>'
    pkg, _ = compile_document(_pkg(xml))
    root = _root(pkg)
    fb = root.find(f".//{{{HP}}}fieldBegin")
    fe = root.find(f".//{{{HP}}}fieldEnd")
    assert fb.get("type") == "CLICK_HERE"
    assert fb.get("name") == "계약명"
    assert fb.get("editable") == "1"
    # fieldEnd 가 fieldBegin 을 정확히 참조(id 링크 무결성).
    assert fe.get("beginIDRef") == fb.get("id")
    assert fe.get("fieldid") == fb.get("fieldid")
    # 생성 런들이 원본 서식(charPrIDRef)을 승계.
    for run in root.iter(f"{{{HP}}}run"):
        assert run.get("charPrIDRef") == "7"


def test_generated_ids_do_not_collide_with_existing():
    """id 는 기존 정수 id 최댓값 위에서 할당돼 충돌하지 않는다."""
    xml = (
        '<hp:p><hp:run charPrIDRef="1"><hp:t id="9000">{{계약명}}</hp:t></hp:run></hp:p>'
    )
    pkg, _ = compile_document(_pkg(xml))
    fb = _root(pkg).find(f".//{{{HP}}}fieldBegin")
    assert int(fb.get("id")) > 9000


# ------------------------------------------------------------------- 멱등성
def test_idempotent_recompile_noop():
    """이미 누름틀이 된 문서를 재컴파일하면 아무것도 바뀌지 않는다."""
    xml = '<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>'
    pkg, _ = compile_document(_pkg(xml))
    pkg2, report2 = compile_document(pkg)
    assert report2.compiled == []
    assert report2.modified is False


def test_token_already_in_field_not_recompiled():
    """이미 누름틀 값으로 든 ``{{X}}`` 는 이중 래핑하지 않는다(멱등의 핵심)."""
    xml = """
    <hp:p>
      <hp:run><hp:ctrl><hp:fieldBegin name="수요기관"/></hp:ctrl></hp:run>
      <hp:run><hp:t>{{수요기관}}</hp:t></hp:run>
      <hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>
    </hp:p>
    """
    assert scan_tokens(_pkg(xml)) == []  # 이미 field 영역 안 → 미리보기에 안 뜸
    _, report = compile_document(_pkg(xml))
    assert report.compiled == []


# ----------------------------------------------------- 못 바꾸는 토큰 시끄럽게 신고
def test_same_format_split_token_is_compiled_losslessly():
    """인접·동일 서식 런의 허위 파편은 논리적으로 접어 컴파일한다."""
    from hwpxcore.text_extract import extract_document, full_text

    xml = _frag("same_charpr_split.xml")
    pkg = _pkg(xml)
    before_text = full_text(extract_document(pkg))

    sites = scan_tokens(pkg)
    assert [(site.name, site.compilable) for site in sites] == [("계약명", True)]
    pkg, report = compile_document(pkg)

    assert report.compiled == ["계약명"]
    assert report.skipped == []
    assert full_text(extract_document(pkg)) == before_text
    assert extract_schema(pkg).field_names() == ["계약명"]


def test_fragment_compile_roundtrip_fill_and_idempotence():
    """파편 정규화 뒤에도 compile→fill 라운드트립과 재컴파일 멱등이 성립한다."""
    pkg, report = compile_document(_pkg(_frag("same_charpr_split.xml")))
    assert report.compiled == ["계약명"]
    compiled_bytes = pkg.entries["Contents/section0.xml"]

    _, second_report = compile_document(pkg)
    assert second_report.compiled == []
    assert second_report.modified is False
    assert pkg.entries["Contents/section0.xml"] == compiled_bytes

    doc = FieldDocument(compiled_bytes)
    assert doc.set_field("계약명", "정보시스템 구축") is True
    assert "앞 정보시스템 구축 뒤" in "".join(etree.fromstring(doc.to_bytes()).itertext())


def test_fragment_compile_preserves_each_source_run_attributes():
    """오프셋 역매핑은 charPr 외 런 속성도 원래 토큰 조각별로 보존한다."""
    xml = """
    <hp:p>
      <hp:run charPrIDRef="7" custom="left"><hp:t>{{계약</hp:t></hp:run>
      <hp:run charPrIDRef="7" custom="right"><hp:t>명}}</hp:t></hp:run>
    </hp:p>
    """
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명"]
    value_runs = [
        run
        for run in _root(pkg).iter(f"{{{HP}}}run")
        if any(_local.tag == f"{{{HP}}}t" for _local in run)
    ]
    assert [(run.get("custom"), "".join(run.itertext())) for run in value_runs] == [
        ("left", "{{계약"),
        ("right", "명}}"),
    ]


def test_fragment_pathology_taxonomy_stays_loud():
    """구조/혼합서식 경계는 추측하지 않고 병리별 이유로 skip 한다."""
    expected = {
        "tab_inserted.xml": "탭/줄바꿈",
        "linebreak_inserted.xml": "탭/줄바꿈",
        "mixed_charpr.xml": "혼합 서식",
        "ctrl_between.xml": "제어 요소",
        "noncontiguous_run_boundary.xml": "비연속",
    }
    for fixture, reason in expected.items():
        pkg = _pkg(_frag(fixture))
        before = pkg.entries["Contents/section0.xml"]
        sites = scan_tokens(pkg)
        assert pkg.entries["Contents/section0.xml"] == before
        assert len(sites) == 1
        assert sites[0].compilable is False
        assert reason in sites[0].reason

        _, report = compile_document(pkg)
        assert report.compiled == []
        assert report.modified is False
        assert len(report.skipped) == 1
        assert reason in report.skipped[0].reason


# ------------------------------------------------- 복합 런 skip 축소 (#9)
def test_composite_multi_t_single_run_compiles_losslessly():
    """한 런에 여러 hp:t 로 쪼개진 토큰(복합 런)도 구간이 깨끗하면 무손실 컴파일한다."""
    from hwpxcore.text_extract import extract_document, full_text

    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계약</hp:t><hp:t>명}}</hp:t>"
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    before = full_text(extract_document(pkg))

    sites = scan_tokens(pkg)
    assert [(s.name, s.compilable) for s in sites] == [("계약명", True)]

    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]
    assert report.skipped == []
    assert full_text(extract_document(pkg)) == before
    assert extract_schema(pkg).field_names() == ["계약명"]


def test_composite_preserves_trailing_control_outside_token():
    """토큰 바깥(뒤)의 제어 요소는 복합 컴파일 중에도 원형 보존된다."""
    from hwpxcore.text_extract import extract_document, full_text

    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계약명}}</hp:t>"
        '<hp:ctrl><hp:bookmark note="KEEP"/></hp:ctrl>'
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    before = full_text(extract_document(pkg))

    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]
    out = pkg.entries["Contents/section0.xml"].decode("utf-8")
    assert 'note="KEEP"' in out  # 토큰 밖 구조 보존
    assert full_text(extract_document(pkg)) == before
    assert extract_schema(pkg).field_names() == ["계약명"]


def test_composite_preserves_inline_tab_outside_token():
    """토큰 뒤 인라인 탭·평문(같은 hp:t 안)이 복합 컴파일 중에도 보존된다."""
    from hwpxcore.text_extract import extract_document, full_text

    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계약명}}<hp:tab/>뒤</hp:t>"
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    before = full_text(extract_document(pkg))

    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]
    out = pkg.entries["Contents/section0.xml"].decode("utf-8")
    assert "<hp:tab" in out  # 토큰 밖 탭 보존
    assert full_text(extract_document(pkg)) == before  # "{{계약명}}\t뒤"
    assert extract_schema(pkg).field_names() == ["계약명"]


def test_composite_compile_roundtrip_fill_and_idempotence():
    """복합 컴파일 뒤에도 compile→fill 라운드트립과 재컴파일 멱등이 성립한다."""
    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계약</hp:t><hp:t>명}}</hp:t>"
        '<hp:ctrl><hp:bookmark/></hp:ctrl>'
        "</hp:run></hp:p>"
    )
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명"]
    compiled_bytes = pkg.entries["Contents/section0.xml"]

    _, second = compile_document(pkg)
    assert second.compiled == []
    assert second.modified is False
    assert pkg.entries["Contents/section0.xml"] == compiled_bytes  # 멱등

    doc = FieldDocument(compiled_bytes)
    assert doc.set_field("계약명", "정보시스템 구축") is True
    assert "정보시스템 구축" in "".join(etree.fromstring(doc.to_bytes()).itertext())


def test_composite_structure_inside_token_stays_loud():
    """복합 런이라도 토큰 **안**에 구조가 끼면 추측하지 않고 병리별로 skip 한다."""
    xml_tab = (
        '<hp:p><hp:run charPrIDRef="7"><hp:t>{{계약<hp:tab/>명}}</hp:t></hp:run></hp:p>'
    )
    xml_ctrl = (
        "<hp:p>"
        '<hp:run charPrIDRef="7"><hp:t>{{계약</hp:t></hp:run>'
        "<hp:run charPrIDRef=\"7\"><hp:ctrl><hp:bookmark/></hp:ctrl></hp:run>"
        '<hp:run charPrIDRef="7"><hp:t>명}}</hp:t></hp:run>'
        "</hp:p>"
    )
    xml_struct = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계약</hp:t><hp:tbl/><hp:t>명}}</hp:t>"
        "</hp:run></hp:p>"
    )
    for xml, reason in (
        (xml_tab, "탭/줄바꿈"),
        (xml_ctrl, "제어 요소"),
        (xml_struct, "구조 요소"),
    ):
        pkg = _pkg(xml)
        before = pkg.entries["Contents/section0.xml"]
        sites = scan_tokens(pkg)
        assert pkg.entries["Contents/section0.xml"] == before  # 무변형
        assert len(sites) == 1 and sites[0].compilable is False
        assert reason in sites[0].reason

        _, report = compile_document(pkg)
        assert report.compiled == []
        assert report.modified is False
        assert len(report.skipped) == 1 and reason in report.skipped[0].reason


def test_composite_mixed_format_stays_skipped():
    """복합 런 확장이 혼합 서식(charPrIDRef 상이) 규칙을 느슨하게 만들지 않는다.

    값 서식 상속이 애매하므로 조용히 추측하지 않고 skip 유지(ROADMAP 원칙).
    """
    xml = (
        "<hp:p>"
        '<hp:run charPrIDRef="7"><hp:t>{{계약</hp:t></hp:run>'
        '<hp:run charPrIDRef="8"><hp:t>명}}</hp:t><hp:ctrl><hp:bookmark/></hp:ctrl></hp:run>'
        "</hp:p>"
    )
    pkg = _pkg(xml)
    before = pkg.entries["Contents/section0.xml"]
    _, report = compile_document(pkg)
    assert report.compiled == []
    assert report.modified is False
    assert len(report.skipped) == 1
    assert "혼합 서식" in report.skipped[0].reason
    assert pkg.entries["Contents/section0.xml"] == before  # 무변형


def test_composite_preserves_empty_attributed_t_outside_token():
    """속성만 있고 텍스트·자식이 없는 hp:t(예: marker)가 복합 런에 있어도 소실되지 않는다.

    회귀: ``_clip_t`` 가 폭-0 요소를 문자/자식 단위로만 취급하면 세 구간(토큰
    앞/값/뒤) 호출 모두 ``None`` 을 반환해 요소가 통째로 사라진다.
    """
    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계약명}}</hp:t>"
        '<hp:t marker="KEEP"/>'
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]
    out = pkg.entries["Contents/section0.xml"].decode("utf-8")
    assert 'marker="KEEP"' in out


def _marker_t(root: etree._Element, value: str) -> "etree._Element | None":
    for t in root.iter(f"{{{HP}}}t"):
        if t.get("marker") == value:
            return t
    return None


def test_composite_preserves_empty_attributed_t_before_token_outside_field():
    """토큰 **앞**의 폭-0 속성 hp:t 는 필드 값 밖(fieldBegin 앞)에 남아야 한다.

    회귀(PR#37 병합 후 발견): 폭-0 보존이 오프셋만 보면 토큰 앞 마커의 시작
    오프셋이 토큰 첫 글자와 같아 값 구간 ``[tstart, tend)`` 로 빨려 들어간다. 그러면
    ``set_field`` 가 이 마커를 필드의 첫 텍스트 노드로 인식해 주입값이 마커에 실리고
    (마커 속성이 값 텍스트를 오염) 필드 경계가 조용히 밀린다. 형제 순서를 반영한
    경계 배정으로 마커가 fieldBegin 밖에 남아야 한다.
    """
    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        '<hp:t marker="BEFORE"/>'
        "<hp:t>{{계약명}}</hp:t>"
        "</hp:run></hp:p>"
    )
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명"]

    # 구조: 마커 런이 fieldBegin 보다 문서상 앞에 있어야 한다.
    root = _root(pkg)
    marker = _marker_t(root, "BEFORE")
    begin = root.find(f".//{{{HP}}}fieldBegin")
    assert marker is not None and begin is not None
    all_elems = list(root.iter())
    assert all_elems.index(marker) < all_elems.index(begin), "마커가 fieldBegin 앞에 없다"

    # 라운드트립: 주입값이 실제 토큰 노드로 가고 마커는 비어 있어야 한다.
    doc = FieldDocument(pkg.entries["Contents/section0.xml"])
    assert doc.set_field("계약명", "정보시스템 구축") is True
    filled = etree.fromstring(doc.to_bytes())
    assert "정보시스템 구축" in "".join(filled.itertext())
    assert not (_marker_t(filled, "BEFORE").text or ""), "마커 노드에 주입값이 새어 들어갔다"


def test_composite_preserves_empty_attributed_t_between_fragments():
    """토큰 조각 사이의 폭-0 속성 hp:t 는 소실 없이 보존된다(값 구간 내부 유지)."""
    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계</hp:t>"
        '<hp:t marker="MID"/>'
        "<hp:t>약명}}</hp:t>"
        "</hp:run></hp:p>"
    )
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명"]
    assert 'marker="MID"' in pkg.entries["Contents/section0.xml"].decode("utf-8")


def test_composite_leading_run_level_tab_field_boundary_exact():
    """런의 첫 자식(hp:t 안이 아니라 런-레벨)이 탭인 경우에도 필드 경계가 정확하다.

    회귀: run_base 를 런의 실제 시작이 아니라 첫 hp:t 위치로 잡으면, 선행
    런-레벨 탭이 _clip_run 순회에서 이중 계산돼 한 칸 밀린다 — 탭이 필드값에
    삼켜지고 닫는 중괄호가 값 밖으로 샌다. full_text 비교는 경계-무관이라
    이 손상을 잡지 못하므로 set_field 라운드트립으로 직접 확인한다.
    """
    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:tab/>"
        "<hp:t>{{계약명}}</hp:t>"
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]

    doc = FieldDocument(pkg.entries["Contents/section0.xml"])
    assert doc.set_field("계약명", "정보시스템 구축") is True
    out = etree.fromstring(doc.to_bytes())
    filled = "".join(out.itertext())
    assert "정보시스템 구축" in filled
    assert "}" not in filled  # 닫는 중괄호가 값 밖으로 새면 안 된다
    assert out.find(f".//{{{HP}}}tab") is not None  # 선행 탭 보존


def test_composite_leading_text_preserved_and_field_created():
    """토큰 앞 평문 + 뒤 제어를 동시에 가진 복합 런에서 순서·필드가 모두 옳다."""
    from hwpxcore.text_extract import extract_document, full_text

    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>계약: {{계약명}}</hp:t>"
        "<hp:ctrl><hp:bookmark/></hp:ctrl>"
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    before = full_text(extract_document(pkg))
    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]
    assert full_text(extract_document(pkg)) == before  # "계약: {{계약명}}"
    assert extract_schema(pkg).field_names() == ["계약명"]


def test_dangling_open_brace_reported_not_silent():
    """미완결 여는 괄호({{ 만 있고 닫는 }} 없음)는 조용히 흘리지 않고 신고한다.

    Fix 1 회귀: 병합 경로가 완전 매치에만 신고를 걸어 미완결 {{ 가 조용히 사라졌다.
    """
    xml = '<hp:p><hp:run charPrIDRef="7"><hp:t>계약명 {{ 없음</hp:t></hp:run></hp:p>'
    pkg = _pkg(xml)
    before = pkg.entries["Contents/section0.xml"]
    sites = scan_tokens(pkg)
    assert pkg.entries["Contents/section0.xml"] == before  # 무변형
    assert len(sites) == 1
    assert sites[0].compilable is False
    assert "파편" in sites[0].reason

    _, report = compile_document(_pkg(xml))
    assert report.compiled == []
    assert len(report.skipped) == 1
    assert "파편" in report.skipped[0].reason


def test_empty_attr_run_preserved_through_merge():
    """길이 0 빈 런(속성 포함)이 인접 토큰 병합 중 삼켜지지 않고 보존된다.

    Fix 2 회귀: 슬라이스 재발행이 빈 슬라이스를 건너뛰어 속성 있는 빈 런이 사라졌다.
    """
    xml = (
        "<hp:p>"
        '<hp:run charPrIDRef="7" note="EMPTY_MARKER"><hp:t></hp:t></hp:run>'
        '<hp:run charPrIDRef="7"><hp:t>{{계약명}}</hp:t></hp:run>'
        "</hp:p>"
    )
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명"]
    out = pkg.entries["Contents/section0.xml"].decode("utf-8")
    assert 'note="EMPTY_MARKER"' in out  # 소스 요소·속성 보존
    # 인접 토큰은 여전히 진짜 누름틀로 컴파일된다.
    assert extract_schema(pkg).field_names() == ["계약명"]


# ------------------------------------------------------------- 실제 코퍼스 멱등
def test_corpus_already_compiled_yields_no_new_fields():
    """실제 입찰공고(이미 누름틀 완비)를 스캔하면 새로 컴파일할 토큰이 없다."""
    path = CORPUS / "bid_notice_limited_under100m.hwpx"
    compilable = [s for s in scan_tokens(read_hwpx_package(path)) if s.compilable]
    assert compilable == []


# ---------------------------------------------------- 컴파일본 옆저장(compile_to_sibling)
def test_compile_to_sibling_saves_next_to_original_and_keeps_original(tmp_path):
    """컴파일본을 <이름>.compiled.hwpx 로 저장하고 원본은 무변형(RC-28 코어 이관)."""
    from hwpxfiller.external.template_inspection import compile_to_sibling

    src = tmp_path / "tpl.hwpx"
    write_hwpx_package(src, _pkg('<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>'))
    before = src.read_bytes()

    compiled_path, report = compile_to_sibling(str(src))

    assert compiled_path == str(tmp_path / "tpl.compiled.hwpx")
    assert Path(compiled_path).exists()
    assert report.modified and report.compiled == ["계약명"]
    assert src.read_bytes() == before                        # 원본 무변형
    assert extract_schema(read_hwpx_package(compiled_path)).field_names() == ["계약명"]


def test_compile_to_sibling_noop_writes_nothing(tmp_path):
    """바꿀 토큰이 없으면 (None, report) — 어떤 파일도 쓰지 않는다(조용한 산출물 금지)."""
    from hwpxfiller.external.template_inspection import compile_to_sibling

    src = tmp_path / "plain.hwpx"
    write_hwpx_package(src, _pkg('<hp:p><hp:run><hp:t>토큰 없음</hp:t></hp:run></hp:p>'))

    compiled_path, report = compile_to_sibling(str(src))

    assert compiled_path is None
    assert not report.modified
    assert sorted(p.name for p in tmp_path.iterdir()) == ["plain.hwpx"]  # 사이드카 없음


def test_compile_to_sibling_collision_is_loud_until_overwrite(tmp_path):
    """기존 컴파일본이 있으면 FileExistsError(경로 재진술) — overwrite 확정 시에만 덮는다(RC-02)."""
    import pytest

    from hwpxfiller.external.template_inspection import compile_to_sibling

    src = tmp_path / "tpl.hwpx"
    write_hwpx_package(src, _pkg('<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>'))
    sibling = tmp_path / "tpl.compiled.hwpx"
    sibling.write_bytes(b"human-edited")
    before = sibling.read_bytes()

    with pytest.raises(FileExistsError) as exc:
        compile_to_sibling(str(src))
    assert str(sibling) in str(exc.value)         # 충돌 경로 재진술
    assert sibling.read_bytes() == before          # 무변형(조용한 덮어쓰기 없음)

    compiled_path, report = compile_to_sibling(str(src), overwrite=True)
    assert compiled_path == str(sibling)
    assert report.modified
    assert sibling.read_bytes() != before          # 명시 확정 후에만 교체


# ------------------------------------------------------- stale 줄배치 캐시(#95)
def test_compile_strips_stale_lineseg_only_in_compiled_sections():
    """런 재편으로 stale 이 된 캐시는 컴파일된 섹션에서만 스트립, 미변경 섹션은 보존(#95)."""
    tokened = (
        '<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run>'
        "<hp:linesegarray><hp:lineseg/></hp:linesegarray></hp:p>"
    )
    plain = '<hp:p><hp:run><hp:t>토큰 없음</hp:t></hp:run><hp:linesegarray/></hp:p>'
    pkg = _pkg(tokened)
    pkg.entries["Contents/section1.xml"] = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{plain}</hs:sec>'
    ).encode("utf-8")
    untouched_before = pkg.entries["Contents/section1.xml"]

    out, report = compile_document(pkg)

    assert report.compiled == ["계약명"]
    assert b"linesegarray" not in out.entries["Contents/section0.xml"]  # 컴파일 섹션 스트립
    # 미변경 섹션은 스트립도 재직렬화 churn 도 없이 바이트 그대로(부분문자열 잔존만으론 미핀)
    assert out.entries["Contents/section1.xml"] == untouched_before
    # 스트립이 컴파일 결과를 훼손하지 않는다 — 스키마 인식 + 채움 라운드트립
    assert extract_schema(out).field_names() == ["계약명"]
    doc = FieldDocument(out.entries["Contents/section0.xml"])
    assert doc.set_field("계약명", "정보시스템 구축") is True
    assert "계약명: 정보시스템 구축" in "".join(etree.fromstring(doc.to_bytes()).itertext())


# ------------------------------------------------------ 표 셀 좌표(cell_path)
def _cell_grid() -> str:
    """본문 0 = 텍스트, 본문 1 = bookmark ctrl(control 0) + 2×2 표(control 1)."""
    def cell(*lines: str) -> str:
        return ('<hp:tc><hp:subList>'
                + ''.join(f'<hp:p><hp:run><hp:t>{line}</hp:t></hp:run></hp:p>' for line in lines)
                + '</hp:subList></hp:tc>')
    return (
        '<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:ctrl><hp:bookmark name="표시"/></hp:ctrl></hp:run>'
        '<hp:run><hp:tbl>'
        f'<hp:tr>{cell("가")}{cell("나")}</hp:tr>'
        f'<hp:tr>{cell("다")}{cell("첫줄", "셀값")}</hp:tr>'
        '</hp:tbl></hp:run></hp:p>'
    )


def _nested_paragraph(package: HwpxPackage, text: str) -> tuple[etree._Element, str]:
    root = _root(package)
    paragraph = next(node for node in root.iter(f"{{{HP}}}p")
                     if node.getparent().tag == f"{{{HP}}}subList"
                     and "".join(child.text or "" for run in node for child in run
                                 if child.tag == f"{{{HP}}}t") == text)
    return root, root.getroottree().getpath(paragraph)


def test_native_cell_field_reports_rhwp_cell_path_with_offsets() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(_cell_grid())
    _, path = _nested_paragraph(package, "셀값")
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph": 0,
                         "start": 0, "end": 1, "name": "본"})
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph_path": path,
                         "start": 0, "end": 2, "name": "셀"})
    fields = {field["name"]: field["occurrences"][0] for field in analyze_hwpx(package)["fields"]}
    expected = [{"parent_paragraph": 1, "control": 1, "cell": 3, "paragraph": 1}]
    assert fields["셀"]["paragraph"] == 1 and fields["셀"]["cell_path"] == expected
    assert fields["셀"]["start"] == 0 and fields["셀"]["end"] == 2
    assert fields["셀"]["paragraph_path"] == path
    assert fields["본"]["paragraph"] == 0 and "cell_path" not in fields["본"]
    hit = search_hwpx(package, "셀값")["hits"][0]
    assert hit["paragraph"] == 1 and hit["cell_path"] == expected and hit["paragraph_path"] == path
    body_hit = search_hwpx(package, "본문")["hits"][0]
    assert body_hit["paragraph"] == 0 and "cell_path" not in body_hit


def test_native_nested_table_cell_path_chains_parent_paragraphs() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>'
        '<hp:p><hp:run><hp:t>바깥</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>'
        '<hp:p><hp:run><hp:t>안쪽</hp:t></hp:run></hp:p>'
        '</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
        '</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
    )
    _, path = _nested_paragraph(package, "안쪽")
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph_path": path,
                         "start": 0, "end": 2, "name": "안"})
    occurrence = analyze_hwpx(package)["fields"][0]["occurrences"][0]
    assert occurrence["cell_path"] == [
        {"parent_paragraph": 0, "control": 0, "cell": 0, "paragraph": 1},
        {"parent_paragraph": 1, "control": 0, "cell": 0, "paragraph": 0},
    ]
    assert occurrence["cell_path"][1]["parent_paragraph"] == occurrence["cell_path"][0]["paragraph"]
    assert occurrence["paragraph"] == 0 and occurrence["start"] == 0 and occurrence["end"] == 2


def test_native_create_field_resolves_cell_path_without_paragraph_path() -> None:
    entry = "Contents/section0.xml"
    cell_path = [{"parent_paragraph": 1, "control": 1, "cell": 3, "paragraph": 1}]
    for broken in ([{**cell_path[0], "control": 0}], [{**cell_path[0], "cell": 2}],
                   [{"control": 1}], []):
        package = _pkg(_cell_grid())
        with pytest.raises(ValueError, match="문단의 위치"):
            apply_hwpx(package, {"type": "create_field", "entry": entry, "cell_path": broken,
                                 "paragraph": 1, "start": 0, "end": 2, "name": "셀"})
        assert package.entries[entry] == _pkg(_cell_grid()).entries[entry]
    with pytest.raises(ValueError, match="문단의 위치"):
        apply_hwpx(_pkg(_cell_grid()), {"type": "create_field", "entry": entry, "cell_path": cell_path,
                                        "paragraph": 0, "start": 0, "end": 2, "name": "셀"})
    package = _pkg(_cell_grid())
    _, path = _nested_paragraph(package, "셀값")
    _, impact = apply_hwpx(package, {"type": "create_field", "entry": entry, "cell_path": cell_path,
                                     "paragraph": 1, "end_paragraph": 1,
                                     "start": 0, "end": 2, "name": "셀"})
    assert impact["captured_text"] == "셀값"
    occurrence = analyze_hwpx(package)["fields"][0]["occurrences"][0]
    assert occurrence["cell_path"] == cell_path and occurrence["paragraph"] == 1
    assert occurrence["paragraph_path"] == path


def test_native_caption_field_keeps_unaddressed_paragraph_without_cell_path() -> None:
    entry = "Contents/section0.xml"
    package = _pkg(
        '<hp:p><hp:run><hp:tbl><hp:caption><hp:subList>'
        '<hp:p><hp:run><hp:t>캡션</hp:t></hp:run></hp:p>'
        '</hp:subList></hp:caption><hp:tr><hp:tc><hp:subList>'
        '<hp:p><hp:run><hp:t>셀</hp:t></hp:run></hp:p>'
        '</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
    )
    _, path = _nested_paragraph(package, "캡션")
    apply_hwpx(package, {"type": "create_field", "entry": entry, "paragraph_path": path,
                         "start": 0, "end": 2, "name": "캡"})
    occurrence = analyze_hwpx(package)["fields"][0]["occurrences"][0]
    assert occurrence["paragraph"] is None and "cell_path" not in occurrence
    assert "start" not in occurrence and "end" not in occurrence
    hit = search_hwpx(package, "캡션")["hits"][0]
    assert hit["paragraph"] is None and "cell_path" not in hit


# -------------------------------------------- 깨진 제품 메타데이터·진단 좌표(#1016)
ENTRY = "Contents/section0.xml"


def _bad_bookmark(name: str, pairing: int) -> str:
    """제품 메타데이터가 JSON이 아닌 책갈피 한 쌍 — malformed-json 진단을 만든다."""
    return (f'<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="{pairing}" type="BOOKMARK" name="{name}">'
            '<hp:metaTag>제품 JSON 아님</hp:metaTag></hp:fieldBegin></hp:ctrl>'
            f'<hp:t>깨진 영역</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="{pairing}"/></hp:ctrl>'
            '</hp:run></hp:p>')


def _append_section_xml(package: HwpxPackage, xml: str, entry: str = ENTRY) -> HwpxPackage:
    """serialize_modified_section 을 지나지 않고 원본 XML을 그대로 덧붙인다."""
    root = etree.fromstring(package.entries[entry])
    for node in etree.fromstring(f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{xml}</hs:sec>'):
        root.append(node)
    package.entries[entry] = etree.tostring(root)
    return package


def test_native_broken_product_metadata_blocks_structure_commands_and_hides_regions() -> None:
    """제품 메타데이터가 깨지면 변경 손잡이를 확정할 수 없다 — 위치를 감추고 전 명령을 막는다."""
    package = _pkg('<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>')
    apply_hwpx(package, {"type": "create_slot", "entry": ENTRY,
                         "start_paragraph": 0, "end_paragraph": 0, "id": "s"})
    _append_section_xml(package, _bad_bookmark("bad", 901))
    detail = analyze_hwpx(package)
    problem = next(item for item in detail["diagnostics"] if item["kind"] == "malformed-json")
    assert (problem["target"], problem["location"]) == ("bad", {"entry": ENTRY, "paragraph": 1})
    assert [(slot["id"], slot["location"], slot["raw"]) for slot in detail["slots"]] == [
        ("s", None, None)]
    before = package.entries[ENTRY]
    for command, message in (
        ({"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
          "end_paragraph": 0, "id": "t"}, "구조 오류를 먼저"),
        ({"type": "rename_slot", "slot_id": "s", "id": "t"}, "구조 오류를 먼저"),
        ({"type": "adjust_range", "slot_id": "s", "entry": ENTRY,
          "start_paragraph": 0, "end_paragraph": 0}, "구조 오류를 먼저"),
        ({"type": "move", "slot_id": "s", "destination_paragraph": 2}, "구조 오류가 있어"),
        ({"type": "duplicate", "slot_id": "s", "new_id": "t"}, "구조 오류가 있어"),
        ({"type": "unwrap", "slot_id": "s"}, "구조 오류를 먼저"),
    ):
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command)
        assert package.entries[ENTRY] == before
    with pytest.raises(ValueError, match="구조 오류를 수정한 뒤"):
        trial_hwpx(package, {}, {})
    assert syntax_view_hwpx(package)["note"] == "구조 오류가 있어 항목·선택 경계를 표기하지 않았습니다."
    blocked = {item["type"]: item for item in available_commands_hwpx(
        package, {"entry": ENTRY, "paragraph": 1, "start": 0, "end": 0})}
    assert blocked["create_slot"]["reason"] == blocked["create_option"]["reason"]
    assert blocked["create_slot"]["reason"] == "구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요."


def test_native_bookmark_diagnostic_location_needs_one_addressable_begin() -> None:
    """같은 이름이 둘이거나 본문 문단 밖이면 진단 위치를 추측하지 않는다."""
    duplicated = _pkg('<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>')
    _append_section_xml(duplicated, _bad_bookmark("bad", 901) + _bad_bookmark("bad", 902))
    assert [item["location"] for item in analyze_hwpx(duplicated)["diagnostics"]
            if item["kind"] == "malformed-json"] == [None, None]
    celled = _pkg(
        '<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>'
        + _bad_bookmark("celled", 903) +
        '</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
    )
    celled_problem = next(item for item in analyze_hwpx(celled)["diagnostics"]
                          if item["kind"] == "malformed-json")
    assert (celled_problem["target"], celled_problem["location"]) == ("celled", None)


def test_native_field_diagnostics_locate_cells_and_omit_unaddressable_controls() -> None:
    """필드 진단 좌표는 셀 경로까지 투영하고, 주소화할 수 없는 위치는 비운다."""
    celled = _pkg(
        '<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run>'
        '<hp:ctrl><hp:fieldBegin id="1" type="CLICKHERE" name="F"/></hp:ctrl>'
        '<hp:t>셀 값</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
    )
    in_cell = next(item for item in analyze_hwpx(celled)["diagnostics"]
                   if item["kind"] == "unmatched-begin")
    assert in_cell["location"] == {
        "entry": ENTRY, "paragraph": 0,
        "cell_path": [{"parent_paragraph": 0, "control": 0, "cell": 0, "paragraph": 0}]}
    outside_run = _pkg('<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>')
    _append_section_xml(outside_run,
                        '<hp:ctrl><hp:fieldBegin id="2" type="CLICKHERE" name="F"/></hp:ctrl>')
    assert [item["location"] for item in analyze_hwpx(outside_run)["diagnostics"]
            if item["kind"] == "unsupported-control-shape"] == [None]
    unaddressable = _pkg(
        '<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:p><hp:run>'
        '<hp:ctrl><hp:fieldBegin id="3" type="CLICKHERE" name="F"/></hp:ctrl>'
        '<hp:t>셀 값</hp:t></hp:run></hp:p></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
    )
    assert all(item["location"] is None for item in analyze_hwpx(unaddressable)["diagnostics"])


def test_native_structure_marker_diagnostic_locates_table_cell_paragraphs() -> None:
    celled = _pkg(
        '<hp:p><hp:run><hp:t>앞</hp:t><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run>'
        '<hp:t>{{/항목}}</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl>'
        '</hp:run></hp:p>'
    )
    item = next(row for row in analyze_hwpx(celled)["diagnostics"]
                if row["kind"] == "marker_in_table")
    assert item["location"] == {
        "entry": ENTRY, "paragraph": 0,
        "cell_path": [{"parent_paragraph": 0, "control": 0, "cell": 0, "paragraph": 0}]}


def test_native_cell_path_counts_section_and_switch_controls_like_rhwp() -> None:
    """rhwp 의 control 세기: secPr 는 colPr 까지 2, chart 를 가진 switch 는 1."""
    package = _pkg(
        '<hp:p><hp:lineSegArray/><hp:run><hp:secPr><hp:colPr/></hp:secPr>'
        '<hp:switch><hp:chart/></hp:switch>'
        '<hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>셀 값</hp:t>'
        '</hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
    )
    hit = search_hwpx(package, "셀 값")["hits"][0]
    assert hit["cell_path"] == [{"parent_paragraph": 0, "control": 3, "cell": 0, "paragraph": 0}]
    without_sublist = _pkg(
        '<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:p><hp:run><hp:t>셀 값</hp:t>'
        '</hp:run></hp:p></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
    )
    plain = search_hwpx(without_sublist, "셀 값")["hits"][0]
    assert plain["paragraph"] is None and "cell_path" not in plain


def test_native_field_offsets_survive_paragraph_level_line_segments() -> None:
    package = _pkg('<hp:p><hp:run><hp:t>앞 원문 뒤</hp:t></hp:run></hp:p>')
    apply_hwpx(package, {"type": "create_field", "entry": ENTRY, "paragraph": 0,
                         "start": 2, "end": 4, "name": "내용"})
    root = etree.fromstring(package.entries[ENTRY])
    paragraph = root.find(f"{{{HP}}}p")
    assert paragraph is not None
    paragraph.insert(0, etree.Element(f"{{{HP}}}lineSegArray"))
    package.entries[ENTRY] = etree.tostring(root)
    occurrence = analyze_hwpx(package)["fields"][0]["occurrences"][0]
    assert (occurrence["start"], occurrence["end"]) == (2, 4)


def _two_section_package(first: str, second: str) -> HwpxPackage:
    package = _pkg(first)
    package.entries["Contents/section1.xml"] = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{second}</hs:sec>').encode("utf-8")
    return package


def test_native_create_field_accepts_empty_selection_and_rejects_non_integer_range() -> None:
    package = _pkg('<hp:p><hp:run><hp:t>앞뒤</hp:t></hp:run></hp:p>')
    with pytest.raises(ValueError, match="정확한 문자 범위"):
        apply_hwpx(package, {"type": "create_field", "entry": ENTRY, "paragraph": 0,
                             "start": "0", "end": 1, "name": "F"})
    _, impact = apply_hwpx(package, {"type": "create_field", "entry": ENTRY, "paragraph": 0,
                                     "start": 0, "end": 0, "name": "빈값"})
    assert impact["captured_text"] == ""
    occurrence = analyze_hwpx(package)["fields"][0]["occurrences"][0]
    assert (occurrence["start"], occurrence["end"]) == (0, 0)
    # 내용이 없는 필드는 남길 본문을 확인할 수 없어 의미 해제를 거절한다
    with pytest.raises(ValueError, match="복합 요소"):
        apply_hwpx(package, {"type": "unset_field", "entry": ENTRY,
                             "occurrence": 0, "text": "본문"})


def test_native_unset_field_merges_every_captured_text_node() -> None:
    package = _pkg('<hp:p><hp:run><hp:t>앞</hp:t><hp:t>뒤</hp:t></hp:run></hp:p>')
    apply_hwpx(package, {"type": "create_field", "entry": ENTRY, "paragraph": 0,
                         "start": 0, "end": 2, "name": "F"})
    assert len(analyze_hwpx(package)["fields"][0]["occurrences"][0]["raw"]["value"]) == 2
    apply_hwpx(package, {"type": "unset_field", "entry": ENTRY, "occurrence": 0, "text": "하나로"})
    assert analyze_hwpx(package)["fields"] == []
    assert "".join(_root(package).itertext()) == "하나로"


def test_native_field_occurrence_edits_refuse_bad_ordinals_and_nonfillable_controls() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="1" type="HYPERLINK" name="링크"/></hp:ctrl>'
        '<hp:t>주소</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="1"/></hp:ctrl></hp:run></hp:p>'
    )
    before = package.entries[ENTRY]
    for command, message in (
        ({"type": "relink_field", "entry": ENTRY, "occurrence": -1, "name": "N"}, "올바르지 않"),
        ({"type": "relink_field", "entry": ENTRY, "occurrence": 0, "name": "N"}, "채울 수 있는 필드"),
    ):
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command)
        assert package.entries[ENTRY] == before


def test_native_field_edits_only_touch_the_named_document_area() -> None:
    package = _two_section_package('<hp:p><hp:run><hp:t>첫 장</hp:t></hp:run></hp:p>',
                                   '<hp:p><hp:run><hp:t>둘째 장</hp:t></hp:run></hp:p>')
    apply_hwpx(package, {"type": "create_field", "entry": "Contents/section1.xml",
                         "paragraph": 0, "start": 0, "end": 2, "name": "F"})
    untouched = package.entries[ENTRY]
    apply_hwpx(package, {"type": "relink_field", "entry": "Contents/section1.xml",
                         "occurrence": 0, "name": "G"})
    assert package.entries[ENTRY] == untouched
    assert [field["name"] for field in analyze_hwpx(package)["fields"]] == ["G"]


def test_native_rename_region_requires_identifiers_and_text_labels() -> None:
    package = _slot_package()
    before = package.entries[ENTRY]
    for command, message in (
        ({"type": "rename_slot", "id": "t"}, "식별자가 필요"),
        ({"type": "rename_option", "slot_id": "s", "id": "t"}, "식별자가 필요"),
        ({"type": "rename_slot", "slot_id": "s", "id": " "}, "새 식별자를 입력"),
        ({"type": "rename_slot", "slot_id": "s", "id": "t", "label": 3}, "표시 이름"),
    ):
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command)
        assert package.entries[ENTRY] == before


def test_native_adjust_region_validation_keeps_the_document_untouched() -> None:
    package = _slot_package()
    before = package.entries[ENTRY]
    for command, message in (
        ({"type": "adjust_range", "start_paragraph": 0, "end_paragraph": 1}, "항목 식별자가 필요"),
        ({"type": "adjust_range", "kind": "option", "slot_id": "s",
          "start_paragraph": 1, "end_paragraph": 1}, "선택 식별자가 필요"),
        ({"type": "adjust_range", "slot_id": "없음", "start_paragraph": 0,
          "end_paragraph": 1}, "영역을 찾을 수 없"),
        ({"type": "adjust_range", "slot_id": "s", "start_paragraph": 2,
          "end_paragraph": 1}, "문단 범위를 정확히"),
        ({"type": "adjust_range", "slot_id": "s", "start_paragraph": 0,
          "end_paragraph": 9}, "문서 영역 밖"),
    ):
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command)
        assert package.entries[ENTRY] == before


def test_native_adjust_region_needs_editable_runs_at_both_boundaries() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>'
        '<hp:p/>'
    )
    apply_hwpx(package, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
                         "end_paragraph": 1, "id": "s"})
    before = package.entries[ENTRY]
    with pytest.raises(ValueError, match="편집 가능한 텍스트 런"):
        apply_hwpx(package, {"type": "adjust_range", "slot_id": "s", "entry": ENTRY,
                             "start_paragraph": 0, "end_paragraph": 2})
    assert package.entries[ENTRY] == before


def test_native_move_region_validation_and_bookmark_ownership() -> None:
    package = _slot_package()
    before = package.entries[ENTRY]
    for command, message in (
        ({"type": "move", "destination_paragraph": 4}, "항목 식별자가 필요"),
        ({"type": "move", "kind": "option", "slot_id": "s",
          "destination_paragraph": 4}, "선택 식별자가 필요"),
        ({"type": "move", "slot_id": "없음", "destination_paragraph": 4}, "영역을 찾을 수 없"),
        ({"type": "move", "slot_id": "s", "destination_paragraph": 4,
          "start": 2}, "문단 시작에 놓으세요"),
        ({"type": "move", "kind": "option", "slot_id": "s", "option_id": "a",
          "destination_paragraph": 4}, "책갈피 소속이 달라"),
    ):
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command)
        assert package.entries[ENTRY] == before


def test_native_move_refuses_blocks_cut_by_another_field_boundary() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>앞</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>뒤</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 1,
                         "end_paragraph": 1, "id": "s"})
    root = etree.fromstring(package.entries[ENTRY])
    paragraphs = [node for node in root if node.tag == f"{{{HP}}}p"]
    opening = etree.SubElement(etree.SubElement(paragraphs[1], f"{{{HP}}}run"), f"{{{HP}}}ctrl")
    etree.SubElement(opening, f"{{{HP}}}fieldBegin", {"id": "5", "type": "CLICKHERE", "name": "F"})
    closing = etree.SubElement(etree.SubElement(paragraphs[2], f"{{{HP}}}run"), f"{{{HP}}}ctrl")
    etree.SubElement(closing, f"{{{HP}}}fieldEnd", {"beginIDRef": "5"})
    package.entries[ENTRY] = etree.tostring(root)
    before = package.entries[ENTRY]
    with pytest.raises(ValueError, match="걸친 문단은 이동할 수 없"):
        apply_hwpx(package, {"type": "move", "slot_id": "s", "destination_paragraph": 4})
    assert package.entries[ENTRY] == before


def test_native_unwrap_reports_a_missing_region_without_guessing_a_name() -> None:
    package = _slot_package()
    before = package.entries[ENTRY]
    with pytest.raises(ValueError, match="영역을 찾을 수 없"):
        preview_hwpx(package, {"type": "unwrap", "kind": "slot", "slot_id": "없음"})
    with pytest.raises(ValueError, match="영역을 찾을 수 없"):
        apply_hwpx(package, {"type": "unwrap", "kind": "slot", "slot_id": "없음"})
    assert package.entries[ENTRY] == before


def _hp(xml: str) -> etree._Element:
    return etree.fromstring(f'<hp:wrap xmlns:hp="{HP}">{xml}</hp:wrap>')[0]


def _single_slot_package(tail: str = '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>') -> HwpxPackage:
    package = _pkg('<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>' + tail)
    apply_hwpx(package, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
                         "end_paragraph": 0, "id": "s"})
    return package


def test_native_duplicate_region_validation_keeps_the_document_untouched() -> None:
    package = _slot_package()
    before = package.entries[ENTRY]
    for command, message in (
        ({"type": "duplicate", "slot_id": "s"}, "새 식별자가 필요"),
        ({"type": "duplicate", "slot_id": "s", "new_id": "t",
          "destination_paragraph": "4"}, "문단 경계가 올바르지 않"),
        ({"type": "duplicate", "kind": "option", "slot_id": "s", "option_id": "a",
          "new_id": "b", "destination_paragraph": 2}, "같은 이름의 선택"),
    ):
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command)
        assert package.entries[ENTRY] == before


def test_native_duplicate_refuses_control_shapes_it_cannot_clone() -> None:
    for extra, target, message in (
        ('<hp:lineSegArray/>', "paragraph", None),
        ('<hp:tbl/>', "run", "복제할 수 없는 제어 요소"),
        ('<hp:ctrl><hp:tab/></hp:ctrl>', "run", "복제할 수 없는 제어 요소"),
        ('<hp:junk/>', "begin", "필드 메타데이터는 복제할 수 없"),
    ):
        package = _single_slot_package()
        root = etree.fromstring(package.entries[ENTRY])
        paragraph = root.find(f"{{{HP}}}p")
        assert paragraph is not None
        if target == "paragraph":
            paragraph.append(_hp(extra))
        elif target == "run":
            next(node for node in paragraph if node.tag == f"{{{HP}}}run").append(_hp(extra))
        else:
            next(root.iter(f"{{{HP}}}fieldBegin")).append(_hp(extra))
        package.entries[ENTRY] = etree.tostring(root)
        before = package.entries[ENTRY]
        command = {"type": "duplicate", "slot_id": "s", "new_id": "복제",
                   "destination_paragraph": 1}
        if message is None:      # 줄 배치 정보는 복제를 막지 않는다
            apply_hwpx(package, command)
            assert [slot["id"] for slot in analyze_hwpx(package)["slots"]] == ["s", "복제"]
            continue
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, command)
        assert package.entries[ENTRY] == before


def test_native_duplicate_refuses_fields_that_cross_the_region_boundary() -> None:
    for inside_first, message in ((True, "가로지르는 필드"), (False, "가로지르는 필드")):
        package = _single_slot_package()
        root = etree.fromstring(package.entries[ENTRY])
        paragraphs = [node for node in root if node.tag == f"{{{HP}}}p"]
        opening, closing = (paragraphs[0], paragraphs[1]) if inside_first else (paragraphs[1],
                                                                               paragraphs[0])
        begin_ctrl = etree.SubElement(etree.SubElement(opening, f"{{{HP}}}run"), f"{{{HP}}}ctrl")
        etree.SubElement(begin_ctrl, f"{{{HP}}}fieldBegin",
                         {"id": "5", "type": "CLICKHERE", "name": "F"})
        end_ctrl = etree.SubElement(etree.SubElement(closing, f"{{{HP}}}run"), f"{{{HP}}}ctrl")
        etree.SubElement(end_ctrl, f"{{{HP}}}fieldEnd", {"beginIDRef": "5"})
        package.entries[ENTRY] = etree.tostring(root)
        before = package.entries[ENTRY]
        with pytest.raises(ValueError, match=message):
            apply_hwpx(package, {"type": "duplicate", "slot_id": "s", "new_id": "복제",
                                 "destination_paragraph": 2})
        assert package.entries[ENTRY] == before


def test_native_duplicate_keeps_foreign_metadata_and_rebases_nested_names() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>선택 내용</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
                         "end_paragraph": 1, "id": "s"})
    apply_hwpx(package, {"type": "create_option", "entry": ENTRY, "start_paragraph": 1,
                         "end_paragraph": 1, "slot_id": "s", "id": "a"})
    root = etree.fromstring(package.entries[ENTRY])
    foreign = etree.SubElement(next(root.iter(f"{{{HP}}}fieldBegin")), f"{{{HP}}}metaTag")
    foreign.text = "[]"          # 제품 payload 가 아닌 메타데이터는 그대로 남는다
    package.entries[ENTRY] = etree.tostring(root)
    apply_hwpx(package, {"type": "duplicate", "slot_id": "s", "new_id": "s2",
                         "destination_paragraph": 2})
    detail = analyze_hwpx(package)
    assert [(slot["id"], [option["id"] for option in slot["options"]])
            for slot in detail["slots"]] == [("s", ["a"]), ("s2", ["a"])]
    assert detail["diagnostics"] == []
    assert _root(package).xpath("count(//hp:metaTag[text()='[]'])",
                                namespaces={"hp": HP}) == 2
    apply_hwpx(package, {"type": "rename_option", "slot_id": "s2", "option_id": "a",
                         "id": "a2"})
    assert [option["id"] for option in analyze_hwpx(package)["slots"][1]["options"]] == ["a2"]


def test_native_duplicate_option_sharing_the_slot_paragraph_is_refused() -> None:
    """상위 항목 경계까지 한 문단에 있으면 복제본이 항목을 둘로 만든다 — 적용 전에 막는다."""
    package = _single_slot_package()
    apply_hwpx(package, {"type": "create_option", "entry": ENTRY, "start_paragraph": 0,
                         "end_paragraph": 0, "slot_id": "s", "id": "a"})
    before = package.entries[ENTRY]
    with pytest.raises(ValueError, match="문서 구조가 깨집니다"):
        apply_hwpx(package, {"type": "duplicate", "kind": "option", "slot_id": "s",
                             "option_id": "a", "new_id": "b", "destination_paragraph": 1})
    assert package.entries[ENTRY] == before


def test_native_duplicate_option_at_the_slot_start_moves_the_parent_boundary() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>선택</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>뒤</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
                         "end_paragraph": 2, "id": "s"})
    apply_hwpx(package, {"type": "create_option", "entry": ENTRY, "start_paragraph": 1,
                         "end_paragraph": 1, "slot_id": "s", "id": "a"})
    apply_hwpx(package, {"type": "duplicate", "kind": "option", "slot_id": "s",
                         "option_id": "a", "new_id": "b", "destination_paragraph": 0})
    detail = analyze_hwpx(package)
    assert detail["diagnostics"] == []
    assert [option["id"] for option in detail["slots"][0]["options"]] == ["b", "a"]
    assert detail["slots"][0]["location"] == {"entry": ENTRY, "start_paragraph": 0,
                                             "end_paragraph": 3}


def test_native_execute_refuses_unknown_commands_and_meaning_breaking_edits() -> None:
    package = _pkg('<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>')
    with pytest.raises(ValueError, match="지원하지 않는 HWPX 저작 명령"):
        apply_hwpx(package, {"type": "없는명령"})
    apply_hwpx(package, {"type": "create_field", "entry": ENTRY, "paragraph": 0,
                         "start": 0, "end": 2, "name": "F"})
    before = package.entries[ENTRY]
    with pytest.raises(ValueError, match="문서 구조가 깨집니다"):
        apply_hwpx(package, {"type": "unset_field", "entry": ENTRY, "occurrence": 0,
                             "text": "{{#항목 x}}"})
    assert package.entries[ENTRY] == before
    broken = _pkg('<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="1" type="CLICKHERE" name="F"/>'
                  '</hp:ctrl><hp:t>값</hp:t></hp:run></hp:p>')
    with pytest.raises(ValueError, match="구조나 선택 범위 때문에"):
        apply_hwpx(broken, {"type": "rename_field", "old_name": "F", "name": "G"})


def test_native_available_commands_reject_impossible_frames_and_stale_context() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:t>머리</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_field", "entry": ENTRY, "paragraph": 1,
                         "start": 0, "end": 2, "name": "F"})
    for selection in ({"entry": ENTRY, "start_paragraph": 2, "end_paragraph": 1},
                      {"entry": ENTRY, "paragraph": 0, "start": 2, "end": 1},
                      {"entry": ENTRY, "paragraph": 9, "start": 0, "end": 0}):
        assert all(item["reason"] == "선택 위치가 올바르지 않습니다."
                   for item in available_commands_hwpx(package, selection))
    spanning = {item["type"]: item for item in available_commands_hwpx(
        package, {"entry": ENTRY, "start_paragraph": 0, "end_paragraph": 2,
                  "start": 0, "end": 0})}
    assert spanning["create_field"]["reason"] == (
        "여러 문단에 걸친 필드는 HWPX 누름틀 경계로 만들 수 없습니다.")
    assert spanning["unset_field"]["enabled"] is True
    stale = {item["type"]: item for item in available_commands_hwpx(
        package, {"entry": ENTRY, "paragraph": 0, "start": 0, "end": 0}, {"slot_id": "없음"})}
    assert stale["delete"]["reason"] == "항목이나 선택 영역을 선택하세요."


def test_native_syntax_view_omits_markers_for_unwritable_identifiers() -> None:
    package = _pkg('<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>')
    apply_hwpx(package, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
                         "end_paragraph": 0, "id": "a}}b"})
    view = syntax_view_hwpx(package)
    assert view["note"] == "구간 표기로 되쓸 수 없는 식별자가 있어 해당 경계를 생략했습니다."
    assert view["sections"][0]["text"] == "본문"


def test_native_trial_surfaces_materialization_failure_loudly(monkeypatch) -> None:
    package = _pkg('<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>')
    apply_hwpx(package, {"type": "create_field", "entry": ENTRY, "paragraph": 0,
                         "start": 0, "end": 2, "name": "F"})
    monkeypatch.setattr("hwpxfiller.external.hwpx_authoring.materialize_authoring_trial",
                        lambda **kwargs: ConformanceFailure("trial-mismatch", "출력 불일치"))
    with pytest.raises(ValueError, match="결과 시험 검증에 실패했습니다: 출력 불일치"):
        trial_hwpx(package, {"F": "값"}, {})


def test_native_marker_diagnostic_without_addressable_text_has_no_location() -> None:
    """표가 앞선 문단의 마커는 좌표로 되짚을 직속 텍스트가 없다 — 위치를 비운다."""
    beside_table = _pkg('<hp:p><hp:run><hp:tbl/><hp:t>{{/항목}}</hp:t></hp:run></hp:p>')
    assert [item["location"] for item in analyze_hwpx(beside_table)["diagnostics"]
            if item["kind"] == "marker_not_alone"] == [None]
    outside_lane = _pkg(
        '<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:p><hp:run><hp:t>{{/항목}}</hp:t>'
        '</hp:run></hp:p></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
    )
    assert [item["location"] for item in analyze_hwpx(outside_lane)["diagnostics"]
            if item["kind"] == "marker_in_table"] == [None]


def test_native_rename_slot_requires_one_bookmark_per_child_option() -> None:
    """하위 선택 책갈피 이름이 상위 항목과 어긋나면 이름 변경을 멈춘다(조용한 유실 금지)."""
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>선택</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
                         "end_paragraph": 1, "id": "s"})
    apply_hwpx(package, {"type": "create_option", "entry": ENTRY, "start_paragraph": 1,
                         "end_paragraph": 1, "slot_id": "s", "id": "a"})
    root = etree.fromstring(package.entries[ENTRY])
    child = next(node for node in root.iter(f"{{{HP}}}fieldBegin") if node.get("name") == "s/a")
    child.set("name", "s|a")
    package.entries[ENTRY] = etree.tostring(root)
    before = package.entries[ENTRY]
    with pytest.raises(ValueError, match="하위 선택 책갈피"):
        apply_hwpx(package, {"type": "rename_slot", "slot_id": "s", "id": "t"})
    assert package.entries[ENTRY] == before


def test_native_duplicate_keeps_foreign_bookmarks_inside_the_copied_region() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(package, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
                         "end_paragraph": 0, "id": "s"})
    root = etree.fromstring(package.entries[ENTRY])
    paragraph = root.find(f"{{{HP}}}p")
    assert paragraph is not None
    run = next(node for node in paragraph if node.tag == f"{{{HP}}}run")
    opening = etree.SubElement(run, f"{{{HP}}}ctrl")
    etree.SubElement(opening, f"{{{HP}}}fieldBegin",
                     {"id": "7", "type": "BOOKMARK", "name": "독립"})
    closing = etree.SubElement(run, f"{{{HP}}}ctrl")
    etree.SubElement(closing, f"{{{HP}}}fieldEnd", {"beginIDRef": "7"})
    package.entries[ENTRY] = etree.tostring(root)
    assert analyze_hwpx(package)["diagnostics"] == []
    apply_hwpx(package, {"type": "duplicate", "slot_id": "s", "new_id": "s2",
                         "destination_paragraph": 1})
    detail = analyze_hwpx(package)
    assert [slot["id"] for slot in detail["slots"]] == ["s", "s2"]
    assert detail["diagnostics"] == []
    assert [node.get("name") for node in _root(package).iter(f"{{{HP}}}fieldBegin")].count(
        "독립") == 2


def test_native_syntax_view_notes_unwritable_identifiers_only_once() -> None:
    package = _pkg(
        '<hp:p><hp:run><hp:t>하나</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>둘</hp:t></hp:run></hp:p>'
    )
    for index, identifier in ((0, "a}}b"), (1, "c}}d")):
        apply_hwpx(package, {"type": "create_slot", "entry": ENTRY, "start_paragraph": index,
                             "end_paragraph": index, "id": identifier})
    view = syntax_view_hwpx(package)
    assert view["note"] == "구간 표기로 되쓸 수 없는 식별자가 있어 해당 경계를 생략했습니다."
    assert view["sections"][0]["text"] == "하나\n둘"


# ------------------------------------------------------- 의미 복사·붙여넣기 경계
def test_native_transfer_rejects_unsupported_media_and_unknown_selectors() -> None:
    package = _single_slot_package()
    with pytest.raises(ValueError, match="지원하지 않는 복사 형식"):
        capture_semantic("docx", package, {"kind": "slot", "slot_id": "s"})
    with pytest.raises(ValueError, match="복사할 의미 요소를 찾을 수 없"):
        capture_semantic("hwpx", package, {"kind": "없는종류"})
    with pytest.raises(ValueError, match="선택 위치가 올바르지 않"):
        capture_semantic("txt", "본문", {"kind": "text", "start": -1, "end": 2})
    captured = capture_semantic("hwpx", package, {"kind": "slot", "slot_id": "s"})
    with pytest.raises(ValueError, match="지원하지 않는 붙여넣기 형식"):
        paste_semantic("docx", package, {**captured, "media": "docx"},
                       {"entry": ENTRY, "destination_paragraph": 1})


def test_txt_block_paste_needs_a_usable_identifier() -> None:
    captured = {"media": "txt", "kind": "slot", "id": None, "label": "",
                "text": "{{#항목 a}}\n본문\n{{/항목}}\n", "plain": "본문\n"}
    with pytest.raises(ValueError, match="새 식별자를 입력"):
        paste_semantic("txt", "머리\n", captured, {"start": 3, "end": 3})


def test_native_field_paste_needs_a_named_source_and_a_target_area() -> None:
    source = _pkg(
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="7" type="CLICKHERE" name=" "/></hp:ctrl>'
        '<hp:t>값</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="7"/></hp:ctrl></hp:run></hp:p>'
    )
    target = _pkg('<hp:p><hp:run><hp:t>대상</hp:t></hp:run></hp:p>')
    captured = {"media": "hwpx", "kind": "field", "source_bytes": source.to_bytes(),
                "selector": {"kind": "field", "entry": ENTRY, "occurrence": 0,
                             "pairing_id": "7"}}
    with pytest.raises(ValueError, match="복사할 필드나 붙여넣을 영역"):
        paste_semantic("hwpx", target, captured, {"paragraph": 0, "start": 0, "end": 0})
    with pytest.raises(ValueError, match="필드 이름을 확인할 수 없"):
        paste_semantic("hwpx", target, captured,
                       {"entry": ENTRY, "paragraph": 0, "start": 0, "end": 0})


def test_native_field_paste_at_the_paragraph_end_keeps_the_text_whole() -> None:
    source = _pkg('<hp:p><hp:run><hp:t>원본</hp:t></hp:run></hp:p>')
    apply_hwpx(source, {"type": "create_field", "entry": ENTRY, "paragraph": 0,
                        "start": 0, "end": 2, "name": "F"})
    occurrence = analyze_hwpx(source)["fields"][0]["occurrences"][0]
    captured = capture_semantic("hwpx", source, {"kind": "field", "entry": occurrence["entry"],
                                                "occurrence": occurrence["occurrence"],
                                                "pairing_id": occurrence["pairing_id"]})
    target = _pkg('<hp:p><hp:run><hp:t>대상</hp:t></hp:run></hp:p>')
    pasted, impact = paste_semantic("hwpx", target, captured,
                                    {"entry": ENTRY, "paragraph": 0, "start": 2, "end": 2})
    assert "".join(_root(pasted).itertext()) == "대상원본"
    assert (impact["before"], impact["after"]) == ("", "원본")
    assert analyze_hwpx(pasted)["fields"][0]["count"] == 1


def test_native_block_paste_requires_the_captured_region_to_still_exist() -> None:
    source = _single_slot_package()
    target = _pkg('<hp:p><hp:run><hp:t>대상</hp:t></hp:run></hp:p>')
    captured = {"media": "hwpx", "kind": "slot", "source_bytes": source.to_bytes(),
                "selector": {"kind": "slot", "slot_id": "없음"}}
    with pytest.raises(ValueError, match="복사할 영역을 찾을 수 없"):
        paste_semantic("hwpx", target, captured, {"entry": ENTRY, "destination_paragraph": 0})


def test_native_block_paste_rebases_nested_names_and_carries_foreign_metadata() -> None:
    source = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>선택 내용</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(source, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
                        "end_paragraph": 1, "id": "s"})
    apply_hwpx(source, {"type": "create_option", "entry": ENTRY, "start_paragraph": 1,
                        "end_paragraph": 1, "slot_id": "s", "id": "a"})
    root = etree.fromstring(source.entries[ENTRY])
    paragraph = root.find(f"{{{HP}}}p")
    assert paragraph is not None
    paragraph.append(_hp('<hp:lineSegArray/>'))
    foreign = etree.SubElement(next(root.iter(f"{{{HP}}}fieldBegin")), f"{{{HP}}}metaTag")
    foreign.text = "[]"
    source.entries[ENTRY] = etree.tostring(root)
    captured = capture_semantic("hwpx", source, {"kind": "slot", "slot_id": "s"})
    target = _pkg('<hp:p><hp:run><hp:t>대상</hp:t></hp:run></hp:p>')
    with pytest.raises(ValueError, match="새 식별자를 입력"):
        paste_semantic("hwpx", target, captured,
                       {"entry": ENTRY, "destination_paragraph": 1, "new_id": 3})
    pasted, impact = paste_semantic("hwpx", target, captured,
                                    {"entry": ENTRY, "destination_paragraph": 1,
                                     "new_id": "s2"})
    detail = analyze_hwpx(pasted)
    assert [(slot["id"], [option["id"] for option in slot["options"]])
            for slot in detail["slots"]] == [("s2", ["a"])]
    assert detail["diagnostics"] == [] and impact["after"] == "공통\n선택 내용"


def test_native_block_paste_refuses_a_destination_area_without_paragraphs() -> None:
    header = f'<hh:head xmlns:hh="{HS}"/>'.encode("utf-8")
    source = _single_slot_package()
    source.entries["Contents/header.xml"] = header
    target = _pkg('<hp:p><hp:run><hp:t>대상</hp:t></hp:run></hp:p>')
    target.entries["Contents/header.xml"] = header
    captured = capture_semantic("hwpx", source, {"kind": "slot", "slot_id": "s"})
    with pytest.raises(ValueError, match="붙여넣을 문단이 없습니다"):
        paste_semantic("hwpx", target, captured,
                       {"entry": "Contents/header.xml", "destination_paragraph": 0,
                        "new_id": "s2"})


def test_native_plain_paste_that_completes_a_marker_is_refused() -> None:
    """의미 없이 붙인 본문이 구간 마커를 완성하면 대상 문서의 의미가 깨진다 — 막는다."""
    source = _pkg('<hp:p><hp:run><hp:t>x}}</hp:t></hp:run></hp:p>')
    apply_hwpx(source, {"type": "create_field", "entry": ENTRY, "paragraph": 0,
                        "start": 0, "end": 3, "name": "F"})
    occurrence = analyze_hwpx(source)["fields"][0]["occurrences"][0]
    captured = capture_semantic("hwpx", source, {"kind": "field", "entry": occurrence["entry"],
                                                "occurrence": occurrence["occurrence"],
                                                "pairing_id": occurrence["pairing_id"]})
    target = _pkg('<hp:p><hp:run><hp:t>{{#항목 </hp:t></hp:run></hp:p>')
    before = target.entries[ENTRY]
    with pytest.raises(ValueError, match="의미 구조가 깨집니다"):
        paste_semantic("hwpx", target, captured,
                       {"entry": ENTRY, "paragraph": 0, "start": 6, "end": 6},
                       with_meaning=False)
    assert target.entries[ENTRY] == before


# ------------------------------------------------------------- rhwp 왕복 사전검사
def _bookmarked(attributes: str = "") -> HwpxPackage:
    return _pkg(
        f'<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="1" type="BOOKMARK" name="s"{attributes}/>'
        '</hp:ctrl><hp:t>본문</hp:t>'
        '<hp:ctrl><hp:fieldEnd beginIDRef="1"/></hp:ctrl></hp:run></hp:p>'
    )


def test_rhwp_roundtrip_ignores_proven_serializer_defaults() -> None:
    original = _bookmarked()
    exported = _bookmarked(' editable="0" dirty="0"')
    assert original.entries[ENTRY] != exported.entries[ENTRY]
    assert compare_rhwp_roundtrip(original.to_bytes(), exported.to_bytes()) == {
        "editable": True, "diagnostics": []}


def test_rhwp_roundtrip_blocks_every_other_change() -> None:
    original = _bookmarked()
    assert compare_rhwp_roundtrip(original.to_bytes(), b"PK not a package") == {
        "editable": False, "diagnostics": [{
            "kind": "invalid_package",
            "message": "편집기가 내보낸 문서를 읽을 수 없습니다: File is not a zip file"}]}
    changed = _pkg('<hp:p><hp:run><hp:t>다른 본문</hp:t></hp:run></hp:p>')
    assert [item["kind"] for item in
            compare_rhwp_roundtrip(original.to_bytes(), changed.to_bytes())["diagnostics"]] == [
        "xml_changed"]
    with_binary = _bookmarked()
    with_binary.entries["BinData/image1.png"] = b"\x89PNG-old"
    exported_binary = _bookmarked()
    exported_binary.entries["BinData/image1.png"] = b"\x89PNG-new"
    assert [item["kind"] for item in compare_rhwp_roundtrip(
        with_binary.to_bytes(), exported_binary.to_bytes())["diagnostics"]] == ["binary_changed"]
    dropped = compare_rhwp_roundtrip(with_binary.to_bytes(), original.to_bytes())
    assert [(item["kind"], item["entry"]) for item in dropped["diagnostics"]] == [
        ("entry_set_changed", "BinData/image1.png")]


def _with_foreign_bookmark(package: HwpxPackage, index: int, pairing: str) -> HwpxPackage:
    """제품 메타데이터가 없는 이웃 책갈피 한 쌍을 문단 안에 넣는다."""
    root = etree.fromstring(package.entries[ENTRY])
    paragraph = [node for node in root if node.tag == f"{{{HP}}}p"][index]
    run = next(node for node in paragraph if node.tag == f"{{{HP}}}run")
    etree.SubElement(etree.SubElement(run, f"{{{HP}}}ctrl"), f"{{{HP}}}fieldBegin",
                     {"id": pairing, "type": "BOOKMARK", "name": "독립"})
    etree.SubElement(etree.SubElement(run, f"{{{HP}}}ctrl"), f"{{{HP}}}fieldEnd",
                     {"beginIDRef": pairing})
    package.entries[ENTRY] = etree.tostring(root)
    assert analyze_hwpx(package)["diagnostics"] == []
    return package


def test_native_block_paste_carries_neighbour_bookmarks_without_renaming_them() -> None:
    source = _single_slot_package(tail="")
    _with_foreign_bookmark(source, 0, "7")
    captured = capture_semantic("hwpx", source, {"kind": "slot", "slot_id": "s"})
    target = _pkg('<hp:p><hp:run><hp:t>대상</hp:t></hp:run></hp:p>')
    pasted, _ = paste_semantic("hwpx", target, captured,
                               {"entry": ENTRY, "destination_paragraph": 1, "new_id": "s2"})
    detail = analyze_hwpx(pasted)
    assert [slot["id"] for slot in detail["slots"]] == ["s2"] and detail["diagnostics"] == []
    assert [node.get("name") for node in etree.fromstring(pasted.entries[ENTRY]).iter(
        f"{{{HP}}}fieldBegin")].count("독립") == 1


def test_native_option_paste_carries_neighbour_bookmarks_without_renaming_them() -> None:
    source = _pkg(
        '<hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>선택</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(source, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
                        "end_paragraph": 1, "id": "s"})
    apply_hwpx(source, {"type": "create_option", "entry": ENTRY, "start_paragraph": 1,
                        "end_paragraph": 1, "slot_id": "s", "id": "a"})
    _with_foreign_bookmark(source, 1, "7")
    captured = capture_semantic("hwpx", source, {"kind": "option", "slot_id": "s",
                                                "option_id": "a"})
    target = _pkg(
        '<hp:p><hp:run><hp:t>대상 공통</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>대상 선택</hp:t></hp:run></hp:p>'
    )
    apply_hwpx(target, {"type": "create_slot", "entry": ENTRY, "start_paragraph": 0,
                        "end_paragraph": 1, "id": "t"})
    pasted, _ = paste_semantic("hwpx", target, captured,
                               {"entry": ENTRY, "destination_paragraph": 1, "slot_id": "t",
                                "new_id": "a2"})
    detail = analyze_hwpx(pasted)
    assert [(slot["id"], [option["id"] for option in slot["options"]])
            for slot in detail["slots"]] == [("t", ["a2"])]
    assert detail["diagnostics"] == []
    assert [node.get("name") for node in etree.fromstring(pasted.entries[ENTRY]).iter(
        f"{{{HP}}}fieldBegin")].count("독립") == 1


# ------------------------------------------- rhwp 왕복 사전검사: 범주별 수용/거절 쌍
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
OPF = "http://www.idpf.org/2007/opf/"


def _rt_pkg(**parts: str) -> HwpxPackage:
    """이름 인자 section/header/content 로 최소 HWPX 패키지를 만든다."""
    pkg = _pkg(parts.get("section", '<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>'))
    if "header" in parts:
        pkg.entries["Contents/header.xml"] = (
            f'<hh:head xmlns:hh="{HH}" xmlns:hc="{HC}" xmlns:hp="{HP}">{parts["header"]}'
            "</hh:head>").encode("utf-8")
    if "content" in parts:
        pkg.entries["Contents/content.hpf"] = (
            f'<opf:package xmlns:opf="{OPF}"><opf:manifest>{parts["content"]}'
            "</opf:manifest></opf:package>").encode("utf-8")
    return pkg


def _rt_verdict(original: HwpxPackage, exported: HwpxPackage) -> list[tuple[str, str]]:
    result = compare_rhwp_roundtrip(original.to_bytes(), exported.to_bytes())
    assert result["editable"] is (not result["diagnostics"])
    return [(item["kind"], item.get("entry", "")) for item in result["diagnostics"]]


_EMPTY_RUN_SOURCE = (
    '<hp:p><hp:run charPrIDRef="3"><hp:t>앞</hp:t></hp:run><hp:run charPrIDRef="72"/></hp:p>'
    '<hp:p><hp:run charPrIDRef="4"><hp:tbl id="9"/><hp:t/></hp:run></hp:p>'
)


def test_rhwp_roundtrip_accepts_empty_text_element_placement() -> None:
    """rhwp 는 빈 run 에 ``<hp:t></hp:t>`` 를 넣고 컨트롤 뒤의 빈 ``hp:t`` 는 쓰지 않는다.

    문자가 0개인 ``hp:t`` 는 run 의 텍스트·컨트롤 순서·charPrIDRef 를 바꾸지 않는다.
    """
    exported = (
        '<hp:p><hp:run charPrIDRef="3"><hp:t>앞</hp:t></hp:run>'
        '<hp:run charPrIDRef="72"><hp:t></hp:t></hp:run></hp:p>'
        '<hp:p><hp:run charPrIDRef="4"><hp:tbl id="9"/></hp:run></hp:p>'
    )
    assert _rt_verdict(_rt_pkg(section=_EMPTY_RUN_SOURCE), _rt_pkg(section=exported)) == []


@pytest.mark.parametrize("exported", [
    # 같은 자리의 빈 run 에 글자가 들어가면 편집이다.
    '<hp:p><hp:run charPrIDRef="3"><hp:t>앞</hp:t></hp:run>'
    '<hp:run charPrIDRef="72"><hp:t>x</hp:t></hp:run></hp:p>'
    '<hp:p><hp:run charPrIDRef="4"><hp:tbl id="9"/></hp:run></hp:p>',
    # 공백도 문자다.
    '<hp:p><hp:run charPrIDRef="3"><hp:t>앞</hp:t></hp:run>'
    '<hp:run charPrIDRef="72"><hp:t> </hp:t></hp:run></hp:p>'
    '<hp:p><hp:run charPrIDRef="4"><hp:tbl id="9"/></hp:run></hp:p>',
    # 줄바꿈 같은 인라인 표식을 담은 hp:t 는 비어 있지 않다.
    '<hp:p><hp:run charPrIDRef="3"><hp:t>앞</hp:t></hp:run>'
    '<hp:run charPrIDRef="72"><hp:t><hp:lineBreak/></hp:t></hp:run></hp:p>'
    '<hp:p><hp:run charPrIDRef="4"><hp:tbl id="9"/></hp:run></hp:p>',
    # 빈 run 의 글자 모양 참조가 바뀌면 편집이다.
    '<hp:p><hp:run charPrIDRef="3"><hp:t>앞</hp:t></hp:run>'
    '<hp:run charPrIDRef="73"><hp:t></hp:t></hp:run></hp:p>'
    '<hp:p><hp:run charPrIDRef="4"><hp:tbl id="9"/></hp:run></hp:p>',
    # 빈 run 자체가 사라지면 편집이다.
    '<hp:p><hp:run charPrIDRef="3"><hp:t>앞</hp:t></hp:run></hp:p>'
    '<hp:p><hp:run charPrIDRef="4"><hp:tbl id="9"/></hp:run></hp:p>',
    # 텍스트가 있던 hp:t 를 비우면 편집이다.
    '<hp:p><hp:run charPrIDRef="3"><hp:t></hp:t></hp:run>'
    '<hp:run charPrIDRef="72"><hp:t></hp:t></hp:run></hp:p>'
    '<hp:p><hp:run charPrIDRef="4"><hp:tbl id="9"/></hp:run></hp:p>',
    # 컨트롤과 텍스트 순서가 바뀌면 편집이다.
    '<hp:p><hp:run charPrIDRef="3"><hp:t>앞</hp:t></hp:run>'
    '<hp:run charPrIDRef="72"><hp:t></hp:t></hp:run></hp:p>'
    '<hp:p><hp:run charPrIDRef="4"><hp:t>뒤</hp:t><hp:tbl id="9"/></hp:run></hp:p>',
])
def test_rhwp_roundtrip_empty_text_normalization_keeps_edits_visible(exported: str) -> None:
    assert _rt_verdict(_rt_pkg(section=_EMPTY_RUN_SOURCE), _rt_pkg(section=exported)) == [
        ("xml_changed", ENTRY)]


def test_rhwp_roundtrip_empty_text_normalization_keeps_attributes_and_tails() -> None:
    with_attribute = '<hp:p><hp:run charPrIDRef="1"><hp:t charPrIDRef="2"/></hp:run></hp:p>'
    with_tail = '<hp:p><hp:run charPrIDRef="1"><hp:t/>꼬리</hp:run></hp:p>'
    exported = '<hp:p><hp:run charPrIDRef="1"></hp:run></hp:p>'
    for source in (with_attribute, with_tail):
        assert _rt_verdict(_rt_pkg(section=source), _rt_pkg(section=exported)) == [
            ("xml_changed", ENTRY)]


# rhwp 직렬화기에서 원본 표기를 보존하도록 고친 범주다. 비교기는 이것들을 정규화하지
# 않으므로, 직렬화기가 다시 표기를 바꾸면 편집이 차단된다(수용은 실 rhwp 왕복이 증명한다).
_GRADATION = ('<hh:borderFill id="1"><hc:fillBrush><hc:gradation type="LINEAR" angle="0" '
              'centerX="0" centerY="0" step="255"{} stepCenter="50" alpha="0">'
              '<hc:color value="#F2F2F2"/><hc:color value="#D8D8D8"/></hc:gradation>'
              '</hc:fillBrush></hh:borderFill>')
_CASE_MARGIN = ('<hh:paraPr id="46"><hp:switch><hp:case hp:required-namespace='
                '"http://www.hancom.co.kr/hwpml/2016/HwpUnitChar"><hh:margin>'
                '<hc:left value="200" unit="{}"/></hh:margin></hp:case><hp:default><hh:margin>'
                '<hc:left value="401" unit="HWPUNIT"/></hh:margin></hp:default></hp:switch>'
                '</hh:paraPr>')
_STRIKE = '<hh:charPr id="78"><hh:strikeout shape="{}" color="#000000"/></hh:charPr>'
_MANIFEST = ('<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
             '<opf:item id="image1" href="BinData/image1.jpg" media-type="{}" isEmbeded="1"/>'
             '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>')
_MANIFEST_REORDERED = (
    '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
    '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
    '<opf:item id="image1" href="BinData/image1.jpg" media-type="image/jpg" isEmbeded="1"/>')
_CR = chr(13)


@pytest.mark.parametrize(("part", "source", "exported"), [
    ("header", _GRADATION.format(' colorNum="2"'), _GRADATION.format("")),
    ("header", _CASE_MARGIN.format("CHAR"), _CASE_MARGIN.format("HWPUNIT")),
    ("header", _STRIKE.format("3D"), _STRIKE.format("NONE")),
    ("content", _MANIFEST.format("image/jpg"), _MANIFEST.format("image/jpeg")),
    ("content", _MANIFEST.format("image/jpg"), _MANIFEST_REORDERED),
    ("section",
     '<hp:p><hp:run><hp:pic id="1"><hp:renderingInfo/><hc:img binaryItemIDRef="image1"/>'
     '<hp:imgRect/><hp:imgDim dimwidth="1" dimheight="1"/></hp:pic></hp:run></hp:p>'
     .replace("<hp:p>", f'<hp:p xmlns:hc="{HC}">', 1),
     '<hp:p><hp:run><hp:pic id="1"><hp:renderingInfo/><hp:imgRect/>'
     '<hp:imgDim dimwidth="1" dimheight="1"/><hc:img binaryItemIDRef="image1"/></hp:pic>'
     '</hp:run></hp:p>'.replace("<hp:p>", f'<hp:p xmlns:hc="{HC}">', 1)),
    # 원문 CRLF 는 XML 파서가 LF 로 읽지만 문자 참조 CR 은 CR 로 남는다.
    ("section",
     f'<hp:p><hp:run><hp:pic id="1"><hp:shapeComment>그림입니다.{_CR}\n이름</hp:shapeComment>'
     '</hp:pic></hp:run></hp:p>',
     '<hp:p><hp:run><hp:pic id="1"><hp:shapeComment>그림입니다.&#13;\n이름</hp:shapeComment>'
     '</hp:pic></hp:run></hp:p>'),
    ("section",
     '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="1" type="BOOKMARK" name="s"><hp:parameters '
     'cnt="0" name=""/><hp:metaTag>{"name":"#hf"}</hp:metaTag></hp:fieldBegin></hp:ctrl>'
     '</hp:run></hp:p>',
     '<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="1" type="BOOKMARK" name="s"><hp:metaTag>'
     '{"name":"#hf"}</hp:metaTag><hp:parameters cnt="0" name=""/></hp:fieldBegin></hp:ctrl>'
     '</hp:run></hp:p>'),
])
def test_rhwp_roundtrip_blocks_categories_fixed_in_the_serializer(
        part: str, source: str, exported: str) -> None:
    entry = {"header": "Contents/header.xml", "content": "Contents/content.hpf",
             "section": ENTRY}[part]
    assert _rt_verdict(_rt_pkg(**{part: source}), _rt_pkg(**{part: exported})) == [
        ("xml_changed", entry)]
    assert _rt_verdict(_rt_pkg(**{part: source}), _rt_pkg(**{part: source})) == []


def _rhwp_style_empty_text(section: bytes) -> bytes:
    """rhwp 직렬화기의 빈 ``hp:t`` 배치만 흉내 낸다(다른 바이트는 원본 그대로)."""
    root = etree.fromstring(section)
    for run in root.iter(f"{{{HP}}}run"):
        children = list(run)
        if not children:
            etree.SubElement(run, f"{{{HP}}}t")
        elif (len(children) > 1 and children[-1].tag == f"{{{HP}}}t"
              and not children[-1].text and not len(children[-1])
              and children[-2].tag != f"{{{HP}}}t"):
            run.remove(children[-1])
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def test_rhwp_roundtrip_real_notice_accepts_empty_text_but_blocks_one_character() -> None:
    original = HwpxPackage.from_bytes((CORPUS / "bid_notice_limited_under100m.hwpx").read_bytes())
    exported = HwpxPackage.from_bytes(original.to_bytes())
    exported.entries[ENTRY] = _rhwp_style_empty_text(original.entries[ENTRY])
    assert exported.entries[ENTRY] != original.entries[ENTRY]
    assert _rt_verdict(original, exported) == []

    edited = HwpxPackage.from_bytes(exported.to_bytes())
    root = etree.fromstring(edited.entries[ENTRY])
    text = next(t for t in root.iter(f"{{{HP}}}t") if t.text and t.text.strip())
    text.text = "가" + text.text
    edited.entries[ENTRY] = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                                           standalone=True)
    assert _rt_verdict(original, edited) == [("xml_changed", ENTRY)]
