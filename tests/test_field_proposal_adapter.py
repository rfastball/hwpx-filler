"""「데이터로 필드 찾기」(#1156) 문서 어댑터 — 읽기 좌표가 필드 만들기 좌표와 같고, 여러 필드가 한 변형이다."""

from __future__ import annotations

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.domain.field_induction.proposal import propose
from hwpxfiller.external.hwpx_authoring import analyze_hwpx, apply_hwpx
from hwpxfiller.external.hwpx_field_proposal import apply_authoring_command, read_hwpx, read_txt, spot_location

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
ENTRY = "Contents/section0.xml"


def para(*children: str) -> str:
    return "<hp:p><hp:run>" + "".join(children) + "</hp:run></hp:p>"


def t(text: str) -> str:
    return f"<hp:t>{text}</hp:t>"


def cell(text: str, row: int, col: int) -> str:
    return (f"<hp:tc><hp:subList>{para(t(text))}</hp:subList>"
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/><hp:cellSpan colSpan="1" rowSpan="1"/></hp:tc>')


def table(*rows: list[str]) -> str:
    return "<hp:tbl>" + "".join("<hp:tr>" + "".join(row) + "</hp:tr>" for row in rows) + "</hp:tbl>"


def package(*paragraphs: str) -> HwpxPackage:
    result = HwpxPackage()
    result.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    result.stored.add(MIMETYPE_NAME)
    result.entries[ENTRY] = f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{"".join(paragraphs)}</hs:sec>'.encode()
    return result


NOTICE = (
    para(t("1. 입찰에 부치는 사항")),
    para(t("가. 공고명: 청사 보안 장비 구매")),
    para(t("나. 추정가격: 170,309,180원")),
    para(t("다. 수요기관: 조달청"), t(" (담당: 김다온 주무관)")),
    para(table([cell("계약방법", 0, 0), cell("제한경쟁", 0, 1)])),
    para(t("청사 보안 장비 구매")),
)
ROW = {"공고명": "청사 보안 장비 구매", "추정가격": "170309180", "수요기관": "조달청", "계약방법": "제한경쟁",
       "담당자": "김다온"}


def proposals(document: HwpxPackage):
    paragraphs, places = read_hwpx(document)
    result = propose(paragraphs, ROW, list(ROW))
    return paragraphs, places, result


def test_reading_matches_create_field_coordinates_for_every_proposed_spot() -> None:
    document = package(*NOTICE)
    _paragraphs, places, result = proposals(document)
    assert result.count("proposal") == 5
    for group in result.groups:
        for spot in group.spots:
            location = spot_location("hwpx", document, places[spot.paragraph], spot.start, spot.end)
            fresh = HwpxPackage.from_bytes(document.to_bytes())
            _changed, impact = apply_hwpx(fresh, {"type": "create_field", "name": group.name, **location})
            assert impact["captured_text"] == spot.text  # 엔진의 expect 검사
    method = next(group for group in result.groups if group.column == "계약방법")
    location = spot_location("hwpx", document, places[method.spots[0].paragraph], 0, 4)
    assert location["cell_path"][0]["parent_paragraph"] == 4 and method.spots[0].where == "표 칸, 1. 다"


def test_controls_mark_the_editable_end_and_field_values_are_excluded() -> None:
    document = package(para("<hp:secPr/>", t("공고명: 청사 보안 장비 구매")), para(t("앞<hp:tab/>추정가격: 170,309,180")))
    paragraphs, _places = read_hwpx(document)
    assert paragraphs[0].editable_end == 0 and paragraphs[1].editable_end == 0
    assert paragraphs[1].text == "앞\t추정가격: 170,309,180"
    made, _ = apply_hwpx(package(*NOTICE), {"type": "create_field", "name": "수요기관", "entry": ENTRY,
                                            "paragraph": 3, "start": 9, "end": 12})
    paragraphs, _places = read_hwpx(made)
    field = paragraphs[3]
    assert field.field_spans == ((9, 12),) and field.editable_end == 9
    _paragraphs, _places, result = proposals(made)
    groups = {group.column: group for group in result.groups}
    assert "수요기관" not in groups  # 이미 필드 값이다
    # 같은 문단의 뒤 자리는 필드(제어 요소) 뒤라 만들 수 없다 — 보류와 그 이유.
    assert groups["담당자"].kind == "held" and not groups["담당자"].spots


def test_text_boxes_are_read_but_never_offered() -> None:
    box = "<hp:rect><hp:drawText><hp:subList>" + para(t("공고명: 청사 보안 장비 구매")) + "</hp:subList></hp:drawText></hp:rect>"
    paragraphs, places = read_hwpx(package(para(box)))
    assert [paragraph.editable_end for paragraph in paragraphs] == [0, 0]
    assert places[1] == {"entry": ENTRY, "paragraph": None}


def test_create_fields_is_one_package_change_in_any_order() -> None:
    document = package(para(t("공고명: 장비 · 수요기관: 조달청 · 담당: 김다온")), para(t("장비")), para(t("다른 장비")))
    command = {"type": "create_fields", "fields": [
        {"name": "공고명", "ranges": [{"entry": ENTRY, "paragraph": 0, "start": 5, "end": 7},
                                    {"entry": ENTRY, "paragraph": 1, "start": 0, "end": 2}]},
        {"name": "담당자", "ranges": [{"entry": ENTRY, "paragraph": 0, "start": 26, "end": 29}]},
        {"name": "수요기관", "ranges": [{"entry": ENTRY, "paragraph": 0, "start": 15, "end": 18}]},
    ]}
    changed, preview = apply_authoring_command("hwpx", document, command)
    fields = {field["name"]: field["count"] for field in analyze_hwpx(changed)["fields"]}
    assert fields == {"공고명": 2, "담당자": 1, "수요기관": 1}
    assert (preview["affected"], preview["label"], preview["links_existing"]) == (4, "필드로 만들기", False)
    again, preview = apply_authoring_command("hwpx", changed, {"type": "create_fields", "fields": [
        {"name": "공고명", "ranges": [{"entry": ENTRY, "paragraph": 2, "start": 3, "end": 5}]}]})
    assert preview["links_existing"] is True
    assert {field["name"]: field["count"] for field in analyze_hwpx(again)["fields"]}["공고명"] == 3


@pytest.mark.parametrize("fields", [None, [], ["x"], [{"name": "a", "ranges": []}]])
def test_create_fields_refuses_malformed_commands(fields) -> None:
    with pytest.raises(ValueError):
        apply_authoring_command("hwpx", package(*NOTICE), {"type": "create_fields", "fields": fields})


def test_create_fields_refuses_overlap_and_keeps_the_original() -> None:
    document = package(*NOTICE)
    before = document.to_bytes()
    overlap = {"type": "create_fields", "fields": [
        {"name": "a", "ranges": [{"entry": ENTRY, "paragraph": 1, "start": 7, "end": 10}]},
        {"name": "b", "ranges": [{"entry": ENTRY, "paragraph": 1, "start": 8, "end": 12}]}]}
    with pytest.raises(ValueError):
        apply_authoring_command("hwpx", document, overlap)
    assert document.to_bytes() == before


def test_txt_reading_excludes_tokens_and_markers_and_maps_utf16() -> None:
    text = "😀 보안 장비\n{{#항목 가 가}}\n수요기관: {{기존}} 조달청\n{{/항목}}\n"
    paragraphs, places = read_txt(text)
    assert [paragraph.text for paragraph in paragraphs][:3] == ["😀 보안 장비", "{{#항목 가 가}}", "수요기관: {{기존}} 조달청"]
    assert paragraphs[1].field_spans == ((0, 11),) and paragraphs[2].field_spans == ((6, 12),)
    assert spot_location("txt", text, places[0], 2, 7) == {"start": 3, "end": 8}
    result = propose(paragraphs, {"장비": "보안 장비", "기관": "조달청", "기존": "기존"}, ["장비", "기관", "기존"])
    assert {group.column for group in result.groups} == {"장비", "기관"}


def test_txt_create_fields_applies_back_to_front() -> None:
    text = "공고명: 장비\n수요기관: 조달청\n장비\n"
    command = {"type": "create_fields", "fields": [
        {"name": "공고명", "ranges": [{"start": 5, "end": 7}, {"start": 18, "end": 20}]},
        {"name": "수요기관", "ranges": [{"start": 14, "end": 17}]}]}
    changed, preview = apply_authoring_command("txt", text, command)
    assert changed == "공고명: {{공고명}}\n수요기관: {{수요기관}}\n{{공고명}}\n"
    assert (preview["affected"], preview["edits"], preview["links_existing"]) == (3, [], False)
    with pytest.raises(ValueError):
        apply_authoring_command("txt", text, {"type": "create_fields", "fields": [{"name": "x"}]})
    single, _ = apply_authoring_command("txt", text, {"type": "create_field", "name": "기관", "start": 14, "end": 17})
    assert "{{기관}}" in single


def test_a_cell_without_an_address_still_reads() -> None:
    bare = "<hp:tc><hp:subList>" + para(t("제한경쟁")) + "</hp:subList></hp:tc>"
    paragraphs, places = read_hwpx(package(para(table([bare]))))
    assert paragraphs[1].cell is not None and (paragraphs[1].cell.row, paragraphs[1].cell.col) == (-1, -1)
    assert places[1]["cell_path"][0]["cell"] == 0
