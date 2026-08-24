"""구간 표기 문법 v1 스캐너 + sigil 선행 분류 테스트(S8-01 #832).

두 가지를 증명한다:

1. **보호** — 구조 마커(``{{#항목 …}}``)는 필드 토큰 후보에서 빠진다. 「누름틀로
   변환」이 마커를 그 이름의 누름틀로 오변환하지 않고, 마커 문단은 무변형이다.
2. **표기 스캔** — ``scan_structure`` 가 선언 구조를 복원하고, 이상 형태는 하나도
   조용히 흘리지 않고 진단으로 남긴다(무변형).
"""

from __future__ import annotations

import json

from lxml import etree

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxcore.text_extract import extract_document, full_text
from hwpxfiller.domain.authoring import (
    StructureDiagnosticKind as Kind,
)
from hwpxfiller.domain.authoring import (
    compile_document,
    scan_structure,
    scan_tokens,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
ENTRY = "Contents/section0.xml"


def _pkg(section_inner: str) -> HwpxPackage:
    sec = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>'
    ).encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries[ENTRY] = sec
    return pkg


def _multi_entry_pkg(section_inner: str, header_inner: str) -> HwpxPackage:
    """section0 + header0 두 content XML 을 가진 패키지(파일 경계 대조용)."""
    pkg = _pkg(section_inner)
    pkg.entries["Contents/header0.xml"] = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{header_inner}</hs:sec>'
    ).encode("utf-8")
    return pkg


def _p(text: str) -> str:
    return f'<hp:p><hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run></hp:p>'


def _doc(*paragraphs: str) -> HwpxPackage:
    return _pkg("".join(paragraphs))


def _in_table(*paragraphs: str) -> str:
    """표 셀(``hp:tbl>tr>tc>subList``) 안에 문단을 중첩한 본문 직계 문단 1개."""
    inner = "".join(paragraphs)
    return (
        "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>"
        f"{inner}"
        "</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
    )


def _in_shape(*paragraphs: str) -> str:
    """표가 아닌 중첩 구조(글상자) 안에 문단을 중첩한 본문 직계 문단 1개."""
    inner = "".join(paragraphs)
    return (
        "<hp:p><hp:run><hp:drawText><hp:subList>"
        f"{inner}"
        "</hp:subList></hp:drawText></hp:run></hp:p>"
    )


def _root(pkg: HwpxPackage) -> etree._Element:
    return etree.fromstring(pkg.entries[ENTRY])


def _paragraph_xml(pkg: HwpxPackage) -> "list[bytes]":
    return [etree.tostring(p) for p in _root(pkg).iter(f"{{{HP}}}p")]


def _kinds(scan) -> "list[Kind]":
    return [d.kind for d in scan.diagnostics]


def _scan_unchanged(pkg: HwpxPackage):
    """스캔이 무변형임을 확인하며 스캔한다(모든 진단 fixture 공용)."""
    before = pkg.entries[ENTRY]
    scan = scan_structure(pkg)
    assert pkg.entries[ENTRY] == before
    return scan


# ------------------------------------------------- A. 보호 — sigil 선행 분류
def test_structure_markers_are_not_field_token_candidates():
    """음성 대조 ① — scan 은 마커를 compilable/skipped 어디에도 올리지 않는다."""
    pkg = _doc(
        _p("{{#항목 특약 특약 사항}}"),
        _p("계약명: {{계약명}}"),
        _p("{{/항목}}"),
    )
    before = pkg.entries[ENTRY]
    sites = scan_tokens(pkg)

    assert pkg.entries[ENTRY] == before  # 무변형
    assert [(s.name, s.compilable) for s in sites] == [("계약명", True)]


def test_compile_leaves_structure_marker_paragraphs_untouched():
    """음성 대조 ② — 컴파일은 마커 문단을 바이트 그대로 두고 필드만 변환한다."""
    pkg = _doc(
        _p("{{#항목 특약 특약 사항}}"),
        _p("계약명: {{계약명}}"),
        _p("{{/항목}}"),
    )
    before = _paragraph_xml(pkg)

    pkg, report = compile_document(pkg)
    after = _paragraph_xml(pkg)

    assert report.compiled == ["계약명"]  # 마커는 컴파일 대상이 아니다
    assert report.skipped == []
    assert after[0] == before[0]  # {{#항목 …}} 문단 무변형
    assert after[2] == before[2]  # {{/항목}} 문단 무변형
    # 마커 이름을 가진 누름틀이 생기지 않았다.
    names = [fb.get("name") for fb in _root(pkg).iter(f"{{{HP}}}fieldBegin")]
    assert names == ["계약명"]


def test_incomplete_structure_marker_stays_loud_as_fragment():
    """미완결 sigil(닫는 괄호 없음)은 종전대로 파편으로 시끄럽게 신고된다."""
    sites = scan_tokens(_doc(_p("{{#항목 특약")))
    assert len(sites) == 1
    assert sites[0].compilable is False
    assert "파편" in sites[0].reason


def test_complete_structure_marker_is_not_reported_as_fragment():
    """완결된 구조 마커는 「파편」으로 오신고되지 않는다(match_starts 기준 유지)."""
    assert scan_tokens(_doc(_p("{{#항목 특약}}"), _p("{{/항목}}"))) == []


# ------------------------------------------------------- B5. 긍정 대조
def _canonical_document() -> HwpxPackage:
    return _doc(
        _p("계약 일반사항"),
        _p("{{#항목 특약 특약 사항}}"),
        _p("{{#선택 지체상금 지체상금 조항}}"),
        _p("지체상금은 {{지체상금률}} 로 한다."),
        _p("{{/선택}}"),
        _p("{{#선택 하자보수 하자보수 조항}}"),
        _p("하자보수 기간은 {{하자기간}} 이다."),
        _p("{{/선택}}"),
        _p("{{/항목}}"),
        _p("발주자: {{수요기관}}"),
    )


def test_positive_control_restores_declaration_and_summary():
    """진단 0 · 선언 전건 복원(id·label·option 순서) · summary 수치 정확."""
    pkg = _canonical_document()
    scan = _scan_unchanged(pkg)

    assert scan.diagnostics == ()
    assert scan.to_dict()["slots"] == [
        {
            "id": "특약",
            "label": "특약 사항",
            "options": [
                {"id": "지체상금", "label": "지체상금 조항"},
                {"id": "하자보수", "label": "하자보수 조항"},
            ],
        }
    ]
    assert scan.summary.to_dict() == {"slots": 1, "options": 2, "fields": 3}
    # 「누름틀 k」는 같은 스캔의 필드 토큰 수와 정합한다.
    assert scan.summary.fields == sum(1 for s in scan_tokens(pkg) if s.compilable)
    assert json.dumps(scan.to_dict())  # 상위 링 직렬화 가능


def test_positive_control_compiles_fields_without_touching_markers():
    """같은 문서를 컴파일하면 마커는 무변형, 필드 토큰만 누름틀이 된다."""
    pkg = _canonical_document()
    before = _paragraph_xml(pkg)
    before_text = full_text(extract_document(pkg))

    pkg, report = compile_document(pkg)
    after = _paragraph_xml(pkg)

    assert report.compiled == ["지체상금률", "하자기간", "수요기관"]
    for index in (1, 2, 4, 5, 7, 8):  # 마커 문단만 골라 바이트 대조
        assert after[index] == before[index]
    assert full_text(extract_document(pkg)) == before_text  # 텍스트 총량 보존


def test_label_is_optional():
    """label 은 선택 — 없으면 빈 문자열로 직렬화된다."""
    scan = _scan_unchanged(
        _doc(_p("{{#항목 특약}}"), _p("본문"), _p("{{/항목}}"))
    )
    assert scan.diagnostics == ()
    assert scan.to_dict()["slots"] == [{"id": "특약", "label": "", "options": []}]


# ------------------------------------------- B3. 진단 전수 (각 종 1+ fixture)
def test_diagnostic_unbalanced_begin_without_end():
    """1(전) — 여는 마커의 닫는 짝이 없다."""
    scan = _scan_unchanged(_doc(_p("{{#항목 특약}}"), _p("본문")))
    assert _kinds(scan) == [Kind.UNBALANCED_MARKER]
    assert "닫는 마커가 없습니다" in scan.diagnostics[0].message
    assert scan.slots == ()  # 미완결 선언은 복원하지 않는다


def test_diagnostic_unbalanced_option_begin_without_end():
    """1(전, 선택) — 열린 선택 범위가 닫히지 않고 문서가 끝난다."""
    scan = _scan_unchanged(_doc(_p("{{#항목 특약}}"), _p("{{#선택 가 가안}}"), _p("본문")))
    assert _kinds(scan) == [Kind.UNBALANCED_MARKER, Kind.UNBALANCED_MARKER]


def test_diagnostic_unbalanced_end_without_begin():
    """1(후) — 닫는 마커의 여는 짝이 없다(항목·선택 양방향)."""
    scan = _scan_unchanged(_doc(_p("본문"), _p("{{/항목}}"), _p("{{/선택}}")))
    assert _kinds(scan) == [Kind.UNBALANCED_MARKER, Kind.UNBALANCED_MARKER]
    assert "여는 「항목」 마커 없이" in scan.diagnostics[0].message
    assert "여는 「선택」 마커 없이" in scan.diagnostics[1].message


def test_diagnostic_crossed_range():
    """2 — 항목·선택 범위가 교차한다."""
    scan = _scan_unchanged(
        _doc(
            _p("{{#항목 특약 특약}}"),
            _p("{{#선택 가 가안}}"),
            _p("본문"),
            _p("{{/항목}}"),
            _p("{{/선택}}"),
        )
    )
    assert Kind.CROSSED_RANGE in _kinds(scan)
    assert "범위가 교차합니다" in scan.diagnostics[0].message


def test_diagnostic_unknown_keyword():
    """3 — 미지 키워드(``{{#조건}}``·``{{/조건}}``)."""
    scan = _scan_unchanged(_doc(_p("{{#조건 x}}"), _p("본문"), _p("{{/조건}}")))
    assert _kinds(scan) == [Kind.UNKNOWN_KEYWORD, Kind.UNKNOWN_KEYWORD]
    assert "조건" in scan.diagnostics[0].message


def test_diagnostic_unknown_keyword_when_marker_body_is_empty():
    """3 — sigil 뿐인 마커도 조용히 흘리지 않는다."""
    scan = _scan_unchanged(_doc(_p("{{#}}")))
    assert _kinds(scan) == [Kind.UNKNOWN_KEYWORD]
    assert "(없음)" in scan.diagnostics[0].message


def test_diagnostic_empty_slot_id():
    """4 — 빈 Slot id."""
    scan = _scan_unchanged(_doc(_p("{{#항목}}"), _p("본문"), _p("{{/항목}}")))
    assert _kinds(scan) == [Kind.EMPTY_SLOT_ID, Kind.UNBALANCED_MARKER]


def test_diagnostic_empty_option_id():
    """4(선택) — 빈 Option id."""
    scan = _scan_unchanged(
        _doc(_p("{{#항목 특약}}"), _p("{{#선택}}"), _p("본문"), _p("{{/항목}}"))
    )
    assert Kind.EMPTY_OPTION_ID in _kinds(scan)


def test_diagnostic_duplicate_slot_id():
    """5 — 같은 문서에서 Slot id 중복."""
    scan = _scan_unchanged(
        _doc(
            _p("{{#항목 특약}}"),
            _p("본문 1"),
            _p("{{/항목}}"),
            _p("{{#항목 특약}}"),
            _p("본문 2"),
            _p("{{/항목}}"),
        )
    )
    assert _kinds(scan) == [Kind.DUPLICATE_SLOT_ID]
    assert "두 번 선언" in scan.diagnostics[0].message


def test_diagnostic_duplicate_option_id():
    """6 — 같은 Slot 안 Option id 중복."""
    scan = _scan_unchanged(
        _doc(
            _p("{{#항목 특약}}"),
            _p("{{#선택 가}}"),
            _p("본문 1"),
            _p("{{/선택}}"),
            _p("{{#선택 가}}"),
            _p("본문 2"),
            _p("{{/선택}}"),
            _p("{{/항목}}"),
        )
    )
    assert _kinds(scan) == [Kind.DUPLICATE_OPTION_ID]


def test_diagnostic_option_outside_slot():
    """7 — Slot 밖 Option 마커."""
    scan = _scan_unchanged(_doc(_p("{{#선택 가}}"), _p("본문"), _p("{{/선택}}")))
    assert _kinds(scan) == [Kind.OPTION_OUTSIDE_SLOT, Kind.UNBALANCED_MARKER]


def test_diagnostic_nested_slot():
    """8 — Slot 중첩 시도."""
    scan = _scan_unchanged(
        _doc(_p("{{#항목 갑}}"), _p("{{#항목 을}}"), _p("본문"), _p("{{/항목}}"))
    )
    assert _kinds(scan) == [Kind.NESTED_SLOT]
    assert "항목 중첩은 없습니다" in scan.diagnostics[0].message


def test_diagnostic_nested_option():
    """8(선택) — 선택 범위 안에서 다시 선택을 연다."""
    scan = _scan_unchanged(
        _doc(
            _p("{{#항목 특약}}"),
            _p("{{#선택 가}}"),
            _p("{{#선택 나}}"),
            _p("본문"),
            _p("{{/선택}}"),
            _p("{{/항목}}"),
        )
    )
    assert Kind.NESTED_OPTION in _kinds(scan)


def test_diagnostic_marker_in_table_cell():
    """9 — 표 셀 안 마커는 인지하되 자격을 거절한다(조용히 필드 취급 금지)."""
    pkg = _pkg(
        _p("{{#항목 특약}}")
        + _in_table(_p("{{#선택 가 셀 안}}"), _p("셀 본문 {{계약명}}"))
        + _p("{{/항목}}")
    )
    scan = _scan_unchanged(pkg)
    assert _kinds(scan) == [Kind.MARKER_IN_TABLE]
    assert "표 셀 안에는" in scan.diagnostics[0].message
    # sigil 선행 분류는 위치와 무관하게 전역 — 셀 안 마커도 필드 토큰이 아니다.
    assert [(s.name, s.compilable) for s in scan_tokens(pkg)] == [("계약명", True)]


def test_diagnostic_marker_not_top_level_outside_table():
    """9(표 밖 중첩) — 글상자 등 본문 직계가 아닌 문단의 마커도 loud 하게 거절."""
    scan = _scan_unchanged(_pkg(_in_shape(_p("{{#항목 특약}}"))))
    assert _kinds(scan) == [Kind.MARKER_NOT_TOP_LEVEL]


def test_diagnostic_marker_not_alone_with_other_text():
    """10(전) — 마커가 같은 문단의 다른 텍스트와 섞여 있다."""
    scan = _scan_unchanged(_doc(_p("서두 {{#항목 특약}}"), _p("본문"), _p("{{/항목}}")))
    assert _kinds(scan) == [Kind.MARKER_NOT_ALONE, Kind.UNBALANCED_MARKER]


def test_diagnostic_marker_not_alone_two_markers():
    """10(후) — 한 문단에 마커가 2개."""
    scan = _scan_unchanged(_doc(_p("{{#항목 특약}}{{/항목}}")))
    assert _kinds(scan) == [Kind.MARKER_NOT_ALONE]


def test_diagnostic_empty_slot_range():
    """11 — begin 바로 다음이 end(내용 문단 0)."""
    scan = _scan_unchanged(_doc(_p("{{#항목 특약}}"), _p("{{/항목}}")))
    assert _kinds(scan) == [Kind.EMPTY_RANGE]
    assert "「항목 특약」 범위에 내용 문단이 없습니다." == scan.diagnostics[0].message


def test_diagnostic_empty_option_range():
    """11(선택) — 빈 선택 범위. 닫힌 선택은 항목의 내용 1건으로 친다."""
    scan = _scan_unchanged(
        _doc(
            _p("{{#항목 특약}}"),
            _p("{{#선택 가}}"),
            _p("{{/선택}}"),
            _p("{{/항목}}"),
        )
    )
    assert _kinds(scan) == [Kind.EMPTY_RANGE]  # 항목은 선택 1건을 내용으로 가진다
    assert "「선택 가」" in scan.diagnostics[0].message


def test_diagnostic_end_marker_extra_text():
    """전수 밖 이상 형태도 조용히 무시하지 않는다 — end 마커 잔여 텍스트."""
    scan = _scan_unchanged(
        _doc(_p("{{#항목 특약}}"), _p("본문"), _p("{{/항목 특약}}"))
    )
    assert _kinds(scan) == [Kind.END_MARKER_EXTRA_TEXT]
    assert "닫는 마커는 키워드만" in scan.diagnostics[0].message
    # 진단은 냈지만 범위 자체는 닫아 뒤이은 유령 불균형을 만들지 않는다.
    assert [slot.id for slot in scan.slots] == ["특약"]


# --------------------------------------------------- 파일 경계 음성 대조
def test_range_does_not_pair_across_content_xml_boundary():
    """범위는 한 content XML 안에서 닫혀야 한다 — 파일을 넘는 짝짓기는 불균형이다.

    쓰기 커널의 region 은 한 XML 안에 사는 단위라, section0 의 여는 마커를 header0
    의 고아 닫는 마커가 닫아 「균형」으로 통과하면 S8-02 가 컴파일할 수 없는 구조를
    진단 계층이 조용히 승인하는 셈이 된다.
    """
    pkg = _multi_entry_pkg(
        _p("{{#항목 특약}}") + _p("본문"),
        _p("{{/항목}}"),
    )
    snapshot = dict(pkg.entries)
    scan = scan_structure(pkg)

    assert pkg.entries == snapshot  # 무변형
    assert _kinds(scan) == [Kind.UNBALANCED_MARKER, Kind.UNBALANCED_MARKER]
    assert "content XML 이 끝났습니다" in scan.diagnostics[0].message  # 열린 begin
    assert "여는 「항목」 마커 없이" in scan.diagnostics[1].message  # 고아 end
    assert scan.slots == ()  # 파일을 넘어 짝지어진 항목은 복원되지 않는다
    assert scan.summary.to_dict() == {"slots": 0, "options": 0, "fields": 0}


def test_slot_id_duplication_is_still_detected_across_content_xml():
    """짝짓기만 파일 단위로 닫힌다 — id 중복 검사·결과 누적은 문서 전역 그대로."""
    body = _p("{{#항목 특약}}") + _p("본문") + _p("{{/항목}}")
    scan = scan_structure(_multi_entry_pkg(body, body))

    assert _kinds(scan) == [Kind.DUPLICATE_SLOT_ID]
    assert [slot.id for slot in scan.slots] == ["특약", "특약"]


# --------------------------------------------------------- 기타 계약
def test_id_normalization_reuses_field_id_rule():
    """id 정규화는 ``normalize_field_id`` 재사용 — 별도 규칙을 발명하지 않는다."""
    scan = _scan_unchanged(
        _doc(_p("{{#항목  특약  라벨  둘 }}"), _p("본문"), _p("{{/항목}}"))
    )
    assert scan.diagnostics == ()
    assert scan.to_dict()["slots"] == [
        {"id": "특약", "label": "라벨 둘", "options": []}
    ]


def test_scan_structure_reads_only():
    """진단이 있는 문서에서도 파일을 변형하는 경로가 없다."""
    pkg = _doc(_p("{{#조건 x}}"), _p("{{/항목}}"))
    snapshot = dict(pkg.entries)
    scan_structure(pkg)
    assert pkg.entries == snapshot
