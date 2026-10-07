"""「데이터로 필드 찾기」(#1156) 도메인 — 표시 형식 프로그램·후보·라벨 증거(엔진 이식)와 등급 규칙·문장.

엔진(template-induction) ``tests/test_core.py``(후보·프로그램·구체성)·``test_gongmun.py``·``test_decision.py``
(라벨 부분)를 옮기고, 계약의 등급 규칙과 문장마다 한 번씩 확인한다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.domain.field_induction.candidates import (
    CellRef,
    ParagraphText,
    boundary_ok,
    find_candidates,
    found_columns,
    mask,
    specificity,
)
from hwpxfiller.domain.field_induction.labels import (
    CUE_FIXED,
    CUE_GENERIC,
    CUE_REPEAT,
    data_cue,
    extract_label,
    glued_left,
    is_label_cell,
    label_before,
    label_matches,
    leading_marker,
    name_overlap,
    names_literally,
    normalize_label,
    raw_label,
    slot_elsewhere,
    static_cue,
    strip_markers,
    word_windows,
)
from hwpxfiller.domain.field_induction.grading import REASON_PROSE_ONCE, note_prose, note_short
from hwpxfiller.domain.field_induction.proposal import field_name, note_for, propose
from hwpxfiller.domain.field_induction.transforms import TRANSFORMS, renderings
from hwpxfiller.domain.format_engine import render as product_render


def doc(*lines: str) -> list[ParagraphText]:
    return [ParagraphText(f"p{index}", line, len(line) + 1) for index, line in enumerate(lines)]


def groups_by_column(result) -> dict:
    return {group.column: group for group in result.groups}


# ------------------------------------------------------------------ transforms (engine test_core)
def test_leading_zero_identifier_is_not_numeric() -> None:
    assert {t.id for t, _ in renderings("00123")} == {"identity"}


def test_iso_date_identity_is_one_program_not_an_ambiguity() -> None:
    ids = [t.id for t, _ in renderings("2026-01-05")]
    assert "identity" in ids and "date_iso" not in ids
    assert "date_slash" not in {t.id for t, _ in renderings("2026/09/15")}


def test_database_date_strings_and_no_date_only_format_on_a_datetime_value() -> None:
    out = {t.id: text for t, text in renderings("2026/09/11 10:00:00")}
    assert out["datetime_dot_spaced"] == "2026. 9. 11. 10:00"
    assert out["datetime_korean"] == "2026년 9월 11일 10:00"
    # 시각이 있는 값을 날짜 전용 형식으로 제안해 시간을 소실시키지 않는다.
    assert not {"date_korean", "date_dot_spaced", "date_iso"} & set(out)


def test_number_grouping_and_its_domain() -> None:
    out = {t.id: text for t, text in renderings("170309180")}
    assert out == {"identity": "170309180", "number_grouping": "170,309,180"}
    assert {t.id: text for t, text in renderings("-1234.5")}["number_grouping"] == "-1,234.5"
    # 제품 엔진은 끝자리 0 을 지운다(-1,234.5) — 같은 글자를 못 내는 프로그램은 쓰지 않는다.
    assert "number_grouping" not in {t.id for t, _ in renderings("-1234.50")}
    assert [t.id for t, _ in renderings("물품내역서 참조")] == ["identity"]
    assert renderings("   ") == [] and TRANSFORMS["number_grouping"].render("1e5") is None


def test_invalid_dates_render_nothing() -> None:
    assert TRANSFORMS["date_iso"].render("2026-13-40") is None
    assert TRANSFORMS["datetime_iso"].render("2026-02-30 10:00") is None
    assert TRANSFORMS["date_korean"].render("내일") is None


@pytest.mark.parametrize("value", ["2026-09-05", "2026-09-05 08:07", "1234567", "12.5", "육군"])
def test_every_kept_program_renders_identically_in_the_product_format_engine(value: str) -> None:
    kept = renderings(value)
    assert kept
    for transform, text in kept:
        binding = transform.binding()
        assert product_render(binding["type"], binding["fmt"], value) == text


def test_binding_labels_come_from_the_product_preset_table() -> None:
    labels = {t.id: t.binding()["label"] for t in TRANSFORMS.values()}
    assert labels["identity"] == ""  # 화면이 형식 줄을 숨기는 신호
    assert labels["number_grouping"] == "숫자"
    assert labels["date_iso"] == "ISO"
    assert labels["date_dot"] == "점"
    assert labels["date_dot_spaced"] == "표준"
    assert labels["date_korean"] == "한글"
    assert labels["date_slash"] == "%Y/%m/%d"  # 프리셋 표에 없는 코드는 코드 자체
    assert labels["date_korean_padded"] == "%Y년 %m월 %d일"
    assert labels["datetime_iso"] == "날짜+시각"
    assert labels["datetime_dot_spaced"] == "표준(시간 포함)"
    assert labels["datetime_korean"] == "한글(시간 포함)"
    assert TRANSFORMS["number_grouping"].binding() == {"type": "amount", "fmt": "{:,}", "label": "숫자"}


def test_note_short_note_prose_and_reason_prose_once_texts() -> None:
    assert note_short("수량:", 1, 2) == "라벨 ‘수량:’ 옆 1곳만 골랐습니다. 다른 2곳은 라벨이 없어 고르지 않았습니다."
    assert note_prose(4, 3) == "값만 있는 자리 4곳을 골랐습니다. 문장 속 3곳은 고르지 않았습니다."
    assert REASON_PROSE_ONCE == "문장 속 자리입니다. 문서마다 바뀌는 값인지 데이터 행 하나로는 알 수 없습니다."


# ------------------------------------------------------------------ candidates (engine test_core)
def test_year_is_not_matched_inside_an_amount() -> None:
    assert not find_candidates(doc("금액 2026000원"), {"year": "2026"})
    assert not find_candidates(doc("금액 2,026,000원"), {"year": "2026"})
    assert find_candidates(doc("2026년도 예산"), {"year": "2026"})


def test_boundaries() -> None:
    assert not boundary_ok("abc12345", 3, 5)  # 숫자가 숫자에 붙었다
    assert not boundary_ok("INV-12a", 4, 6)
    assert boundary_ok("한국상사귀하", 0, 4)  # 한국어 조사는 붙는다
    assert not boundary_ok("xAB", 1, 3) and not boundary_ok("AB9", 0, 2)
    assert not boundary_ok("1.25", 2, 4) and not boundary_ok("25,1", 0, 2)


def test_empty_values_are_no_evidence_and_field_values_are_not_candidates() -> None:
    assert not find_candidates(doc("메모: "), {"memo": "", "none": None})
    paragraph = ParagraphText("p", "수요기관: 조달청", 3, ((6, 9),))
    assert not find_candidates([paragraph], {"agency": "조달청"})


def test_mask_keeps_the_longest_span_and_groups_programs_of_one_span() -> None:
    paragraphs = doc("기간 2026-09-15 까지")
    candidates = find_candidates(paragraphs, {"d": "2026-09-15", "y": "2026", "same": "2026-09-15"})
    slots = mask(candidates)
    assert [(slot.start, slot.end) for slot in slots] == [(3, 13)]
    assert {candidate.column for candidate in slots[0].candidates} == {"d", "same"}


def test_specificity_prior() -> None:
    assert specificity("3") == 0.0 and specificity("") == 0.0
    assert specificity("2026년 9월 30일") == 1.0 and specificity("서울특별시") == 1.0
    assert specificity("12") == 0.2 and specificity("170,309,180") == 1.0


def test_found_columns_counts_columns_seen_in_the_document() -> None:
    paragraphs = doc("수요기관: 조달청", "금액 1,000원")
    assert found_columns(paragraphs, {"a": "조달청", "b": "1000", "c": "없는 값", "d": None}) == 2


# ------------------------------------------------------------------ labels (engine test_gongmun / test_decision)
def test_kordoc_ports() -> None:
    assert normalize_label(" 품          명: ") == "품명"
    assert strip_markers("  ① 입찰방식: 전자입찰") == "입찰방식: 전자입찰"
    assert strip_markers("가. 개찰일시") == "개찰일시" and strip_markers("는. 이하") == "는. 이하"
    assert is_label_cell("업 체 명") and not is_label_cell("6개월") and not is_label_cell("(주)원트리즈뮤직")
    assert not is_label_cell("") and not is_label_cell("가" * 31)


def test_label_extraction_handles_letter_spacing_markers_and_cells() -> None:
    assert extract_label(" 사  업  예  산:  ") == ("사업예산", "colon")
    assert extract_label(" 수 량 및 단 위:  6 ") == ("수량및단위", "colon")  # 값 위의 복합 라벨
    assert extract_label("○ 계약방법 : 일반경쟁 / ")[0] == ""  # 라벨은 첫 값의 것
    assert extract_label("1) 품명 및 수량\n -") == ("품명및수량", "cell")
    assert extract_label("이 입찰은 ") == ("이입찰은", "before")
    assert extract_label("다음과 같이 공고합니다.\n") == ("", "none")
    assert extract_label("단위: 대\n") == ("", "none")  # 「라벨: 값」 줄은 라벨 칸이 아니다
    long_head = "가나다라마바사아자차카타파하 거너더러, 수요기관: "
    assert extract_label(long_head) == ("수요기관", "colon")


def test_raw_label_is_what_a_person_reads() -> None:
    assert raw_label(" 다. 수 량: ", "colon") == "수 량:"
    assert raw_label("계약방법\n", "cell") == "계약방법"
    assert raw_label("가. 이 입찰은 ", "before") == "이 입찰은"


def test_label_matching_rules() -> None:
    assert label_matches("품명", "세부품명", fuzzy=False) == "head-final"
    assert label_matches("수량및단위", "단위", fuzzy=False) == "exact"
    assert label_matches("요청건명", "공고명", fuzzy=False) == "synonym"
    assert label_matches("입찰방식", "계약방법", fuzzy=False) == "synonym"
    assert label_matches("공고명칭", "공고명", fuzzy=False) == "prefix"
    assert label_matches("공고", "공고명", fuzzy=False) is None
    assert label_matches("입찰공고", "입찰공고번", fuzzy=False) == "prefix-reverse"
    assert label_matches("담당자전화번호", "전화번호", fuzzy=False) == "head-final-label"
    assert label_matches("", "x", fuzzy=True) is None


def test_prose_words_are_not_fuzzy_labels() -> None:
    assert label_matches("낙찰자결정방식", "낙찰자결정방법", fuzzy=True) == "bigram"
    assert label_matches("낙찰자결정을위한", "낙찰자결정방법", fuzzy=False) is None


def test_heuristic_label_signal() -> None:
    assert label_before("\n납부기한: ") == "납부기한"
    assert name_overlap("납부기한", "납부기한") == 1.0
    assert name_overlap("", "납부기한") == 0.0


def test_static_cues() -> None:
    def cue(left: str, span: str, right: str = "", repeats: int = 1, prefixes=()) -> str | None:
        return static_cue(left, span, right, repeats=repeats, prefixes=prefixes)

    assert cue("근거: “조달청 군수품 구매 ", "적격심사", " 세부기준” 제4조") == CUE_FIXED
    assert cue("전자입찰특별유의서 (", "조달청", " 고시)") == CUE_FIXED
    assert cue("제목  「", "선박 개선", "」 낙찰자 선정") is None  # 따옴표가 값만 감싸면 값이다
    assert cue("4. 변경 ", "가능", " 여부: 가능") == CUE_FIXED
    assert cue("계약상대자는 ", "조달청", "의 승인을 받아야 하며 이를 위반한 경우에는 해지할 수 있다") == CUE_GENERIC
    assert cue("수요기관 ", "조달청", "에서 요청한 물품을 다음과 같이 공고합니다") is None


def test_genericity_and_one_value_one_slot() -> None:
    prefixes = ["수요기관: ", "관련 문의는 ", "(", "각 지방", "근거: ", "서약서 "]
    assert slot_elsewhere("관련 문의는 ", repeats=6, prefixes=prefixes)
    # 「한 값 한 자리」는 약한 단서다 — 묶음을 보류하지 않고 문장 속 자리만 뺀다.
    assert static_cue("관련 문의는 ", "조달청", " 콜센터로", repeats=6, prefixes=prefixes) == CUE_REPEAT
    assert not slot_elsewhere("관련 문의는 ", repeats=3, prefixes=prefixes)  # 진짜 반복 값(2~4번)
    assert not slot_elsewhere("수요기관: ", repeats=6, prefixes=prefixes)  # 라벨 자리 그 자체


def test_data_cues_and_glue() -> None:
    assert data_cue("", "042-481-1234", "")
    assert data_cue("", "김다온", " 주무관 (042)") and data_cue("", "양문석 준위", "")
    assert not data_cue("", "김다온", "에게") and not data_cue("", "화생방과", "")
    assert not data_cue("주무관 ", "홍길동", " (☎ 042)")  # 직함이 앞에 오는 이름은 양식에 박힌 줄일 수 있다
    assert data_cue("조달청 물품공고 제", "R26BK99000001-000", "호")  # 번호 틀 「제…호」
    assert not data_cue("제", "12", "조")
    assert glued_left("제", "R26") and not glued_left("", "R26") and not glued_left("번호 ", "R26")


def test_leading_marker_levels() -> None:
    assert leading_marker("1. 입찰에 부치는 사항") == (0, "1.")
    assert leading_marker(" 나. 추정가격: 1") == (1, "나.")
    assert leading_marker("(1) 세부") == (4, "(1)")
    assert leading_marker("□ 상자") is None and leading_marker("는. 이하") is None


# ------------------------------------------------------------------ the mockup notice (계약 시안)
MOCKUP = [
    "물품 구매 입찰 공고",
    "공고번호 R26BK01234567",
    "청사 보안 출입통제시스템 구매",
    "입찰을 다음과 같이 공고합니다.",
    "1. 입찰에 부치는 사항",
    "가. 공고명: 청사 보안 출입통제시스템 구매",
    "나. 추정가격: 170,309,180원 (부가가치세 포함)",
    "다. 수량: 12 식",
    "라. 납품장소: 정부대전청사 3동",
    "2. 입찰 일정",
    "가. 현장설명회: 2026. 9. 12. 14:00 (대전지방조달청 2층 회의실)",
    "나. 입찰서 제출 시작: 2026. 9. 12. 09:00",
    "다. 입찰마감일시: 2026. 9. 17. 18:00",
    "라. 개찰일시: 2026. 9. 18. 10:00",
    "3. 입찰 참가자격",
    "가. 이 입찰은 제한경쟁 입찰로서 아래 자격을 모두 갖춘 자가 참가할 수 있습니다.",
    "나. 「국가를 당사자로 하는 계약에 관한 법률 시행령」 제42조에 따른 적격심사 대상자로서 결격 사유가 없는 자",
    "4. 입찰 방법",
    "가. 이 입찰은 전자입찰로 하며, 국가종합전자조달시스템에서 공고번호 R26BK01234567 을 조회하여 입찰서를 제출합니다.",
    "나. 전자입찰 이용 방법은 「국가종합전자조달시스템 이용약관」을 따릅니다.",
    "다. 낙찰자는 적격심사 결과 종합평점이 85점 이상인 자로 합니다.",
    "라. 적격심사 서류는 입찰마감일까지 제출합니다.",
    "담당: 김다온 주무관 (042-481-1234)",
    "2026. 9. 11.",
]
MOCKUP_CELLS = [("계약방법", 0), ("제한경쟁", 1), ("낙찰자결정방법", 2), ("적격심사", 3)]
MOCKUP_ROW = {
    "입찰공고번호": "R26BK01234567", "현행공고": "R26BK01234567", "공고명": "청사 보안 출입통제시스템 구매",
    "추정가격": "170309180", "수량": "12", "납품장소": "정부대전청사 3동", "입찰마감일시": "2026-09-17 18:00",
    "개찰일시": "2026-09-18 10:00", "계약방법": "제한경쟁", "담당자": "김다온", "낙찰자결정방법": "적격심사",
    "입찰방식": "전자입찰", "품명": "", "비고": None,
}


def mockup_paragraphs() -> list[ParagraphText]:
    body = doc(*MOCKUP)
    cells = [ParagraphText(f"c{col}", text, len(text) + 1, cell=CellRef("t0", 0, col))
             for text, col in MOCKUP_CELLS]
    return body[:14] + cells + body[14:]


def test_mockup_notice_has_ten_proposals_and_one_held() -> None:
    result = propose(mockup_paragraphs(), MOCKUP_ROW, list(MOCKUP_ROW))
    groups = groups_by_column(result)
    assert (result.count("proposal"), result.count("held")) == (10, 1)
    assert {column for column, group in groups.items() if group.kind == "proposal"} == {
        "입찰공고번호", "공고명", "추정가격", "수량", "납품장소", "입찰마감일시", "개찰일시", "계약방법", "담당자",
        "낙찰자결정방법"}
    number = groups["입찰공고번호"]
    assert len(number.spots) == 2 and note_for(number) == [
        {"name": "현행공고", "note": "‘현행공고’ 열도 같은 값입니다."}]
    assert len(groups["공고명"].spots) == 2 and groups["공고명"].count_text == "2곳"
    price = groups["추정가격"]
    assert (price.value, price.raw, price.transform, price.spots[0].text) == (
        "170,309,180원", "170309180", "number_grouping", "170,309,180")
    assert price.spots[0].where == "1. 나"
    quantity = groups["수량"]
    # 점 날짜(「2026. 9. 12.」)의 토막 「12」는 자리가 아니다 — 라벨 자리 하나뿐이라 뺀 자리도 없다.
    assert len(quantity.spots) == 1 and (quantity.note, quantity.count_text) == ("", "1곳")
    assert groups["입찰마감일시"].transform == "datetime_dot_spaced"
    method = groups["계약방법"]
    # 표 칸 라벨 자리 하나 — 규정 문장(「…할 수 있습니다」) 속 반복은 싣지 않는다.
    assert [spot.where for spot in method.spots] == ["표 칸, 2. 라"]
    judge = groups["낙찰자결정방법"]
    # 라벨 자리가 있는 묶음은 늘 제안이다 — 문장 속 3곳은 빼고 그 사실을 한 문장으로 단다.
    assert (judge.kind, judge.only, judge.count_text) == ("proposal", None, "라벨 옆 1곳만")
    assert [spot.where for spot in judge.spots] == ["표 칸, 2. 라"]
    assert judge.note == "라벨 ‘낙찰자결정방법’ 옆 1곳만 골랐습니다. 다른 3곳은 라벨이 없어 고르지 않았습니다."
    bidding = groups["입찰방식"]
    assert bidding.kind == "held"
    assert bidding.reason == "같은 값 2곳이 모두 문장 속에 있어 일반 낱말로 보입니다."
    assert [(item.column, item.reason) for item in result.missing] == [
        ("품명", "이 행에서 값이 비어 있습니다."), ("비고", "이 행에서 값이 비어 있습니다.")]


# ------------------------------------------------------------------ grading rules and sentences
def test_two_columns_with_one_value_and_no_label_are_held_as_a_tie() -> None:
    result = propose(doc("한국상사"), {"상호": "한국상사", "거래처": "한국상사"}, ["상호", "거래처"])
    (group,) = result.groups
    assert group.kind == "held" and group.column == "상호" and group.others == ["거래처"]
    assert group.reason == "값이 같은 열이 여럿입니다. 연결할 열을 고르세요."


def test_fixed_wording_and_generic_sentences_are_held() -> None:
    quoted = propose(doc("근거: “조달청 군수품 구매 적격심사 세부기준” 제4조"), {"방법": "적격심사"}, ["방법"])
    assert quoted.groups[0].reason == "고정 문구 안의 낱말로 보입니다."
    generic = propose(doc("계약상대자는 납품장소 하차도 조건을 지켜야 하며 위반한 경우에는 해지합니다."),
                      {"인도조건": "납품장소 하차도"}, ["인도조건"])
    assert generic.groups[0].reason == "규정·안내 문장 안의 낱말로 보입니다."


def test_unlabelled_values_by_place() -> None:
    once = propose(doc("이번 사업은 정부대전청사 3동 이전을 위한 구매입니다"), {"장소": "정부대전청사 3동"}, ["장소"])
    assert once.groups[0].reason == "문장 속 자리입니다. 문서마다 바뀌는 값인지 데이터 행 하나로는 알 수 없습니다."
    alone = propose(doc("정부대전청사 3동"), {"장소": "정부대전청사 3동"}, ["장소"])
    assert alone.groups[0].kind == "proposal"
    many = propose(doc("정부대전청사 3동", "정부대전청사 3동", "정부대전청사 3동"), {"장소": "정부대전청사 3동"}, ["장소"])
    assert many.groups[0].kind == "proposal" and len(many.groups[0].spots) == 3 and not many.groups[0].note
    mixed = propose(doc("정부대전청사 3동", "이번 사업은 정부대전청사 3동 이전을 위한 구매입니다"),
                    {"장소": "정부대전청사 3동"}, ["장소"])
    (group,) = mixed.groups
    assert (group.kind, [spot.paragraph for spot in group.spots]) == ("proposal", [0])
    assert group.note == "값만 있는 자리 1곳을 골랐습니다. 문장 속 1곳은 고르지 않았습니다." and group.count_text == "1곳"
    phone = propose(doc("문의는 담당 부서(042-481-1234)로 연락 바람"), {"전화": "042-481-1234"}, ["전화"])
    assert phone.groups[0].kind == "proposal"  # 전화번호는 자료 단서(엔진 G3)


def test_range_values_on_one_line_are_each_their_own_slot() -> None:
    result = propose(doc("① 전자입찰서 접수일시: 2026. 9. 11. 10:00 ~ 2026. 9. 15. 10:00"),
                     {"개시": "2026-09-11 10:00", "마감": "2026-09-15 10:00"}, ["개시", "마감"])
    assert [group.kind for group in result.groups] == ["proposal", "proposal"]


def test_short_values_keep_only_the_label_spot() -> None:
    word = propose(doc("단위: 대", "대한민국 대표 대학"), {"단위": "대"}, ["단위"])
    assert word.groups[0].note == "라벨 ‘단위:’ 옆 1곳만 골랐습니다. 다른 3곳은 라벨이 없어 고르지 않았습니다."
    lone = propose(doc("단위: 대"), {"단위": "대"}, ["단위"])
    assert (lone.groups[0].note, lone.groups[0].count_text) == ("", "1곳")
    unlabelled = propose(doc("총 12 건"), {"수량": "12"}, ["수량"])
    assert not unlabelled.groups
    assert [(item.column, item.reason) for item in unlabelled.missing] == [("수량", "문서에서 같은 값을 찾지 못했습니다.")]


def test_column_names_become_field_names_or_are_held() -> None:
    assert field_name(" 담당자   전화번호 ") == "담당자 전화번호"
    assert field_name("#번호") == "번호" and field_name("{a|b}") == "a b" and field_name("{{}}") is None
    result = propose(doc("공고명: 장비 구매"), {"{{}}": "장비 구매"}, ["{{}}"])
    assert result.groups[0].kind == "held" and result.groups[0].reason == "열 이름을 필드 이름으로 쓸 수 없습니다. 문구를 고르고 직접 필드로 만드세요."


def test_spots_after_a_control_are_not_offered() -> None:
    paragraphs = [ParagraphText("p0", "공고명: 장비 구매", 2)]
    (group,) = propose(paragraphs, {"공고명": "장비 구매"}, ["공고명"]).groups
    assert group.kind == "held" and not group.spots
    assert group.reason == "고른 범위 앞이나 안에 제어 요소가 있어 문자 위치를 확정할 수 없습니다."


def test_dismissed_existing_and_one_group_per_column() -> None:
    paragraphs = doc("공고명: 장비 구매", "개찰일: 2026-09-18", "2026년 9월 18일 개찰")
    row = {"공고명": "장비 구매", "개찰일": "2026-09-18"}
    result = propose(paragraphs, row, list(row), existing_fields=["공고명"])
    groups = groups_by_column(result)
    assert groups["공고명"].links_existing is True
    assert groups["개찰일"].transform == "identity"  # 라벨 자리 묶음이 산문 속 다른 형식 묶음을 이긴다
    dismissed = propose(paragraphs, row, list(row), dismissed={("공고명", "장비 구매")})
    assert "공고명" not in groups_by_column(dismissed) and not dismissed.missing
    held = propose(doc("근거: “장비 구매 세부기준”"), {"공고명": "장비 구매"}, ["공고명"], existing_fields=["공고명"])
    assert not held.groups and not held.missing


def test_values_only_inside_existing_fields_are_not_missing() -> None:
    paragraphs = [ParagraphText("p0", "수요기관: 조달청", 6, ((6, 9),))]
    assert not propose(paragraphs, {"수요기관": "조달청"}, ["수요기관"]).missing


def test_where_marks_numbering_and_table_cells() -> None:
    paragraphs = doc("1. 사항", "가. 공고명: 장비 구매", "(1) 세부: 첫째 장비") + [
        ParagraphText("c", "둘째 장비", 9, cell=CellRef("t", 0, 1)),
        ParagraphText("l", "세부", 3, cell=CellRef("t", 0, 0))]
    result = propose(paragraphs, {"공고명": "장비 구매", "세부": "첫째 장비", "둘": "둘째 장비"}, ["공고명", "세부", "둘"])
    groups = groups_by_column(result)
    assert groups["공고명"].spots[0].where == "1. 가"
    assert groups["세부"].spots[0].where == "1. 가. (1)"
    assert groups["둘"].spots[0].where == "표 칸, 1. 가. (1)"


def test_label_cell_above_a_value_cell() -> None:
    paragraphs = [
        ParagraphText("h", "납품장소", 5, cell=CellRef("t", 0, 0, col_span=2)),
        ParagraphText("x", "비고 없음", 6, cell=CellRef("t", 1, 0)),
        ParagraphText("v", "정부대전청사 3동", 10, cell=CellRef("t", 1, 1)),
    ]
    (group,) = propose(paragraphs, {"납품장소": "정부대전청사 3동"}, ["납품장소"]).groups
    assert group.kind == "proposal" and group.spots[0].where == "표 칸"


def test_label_extraction_edges() -> None:
    assert strip_markers("1. 가. 1) (1) 깊은 항목") == "깊은 항목"  # 기호는 네 겹까지만 걷는다
    assert strip_markers("1. 가. 1) (1) ① 다섯째") == "① 다섯째"
    assert extract_label("비고: " + "가" * 26 + " ")[1] == "before"  # 쌍점 뒤가 길면 라벨이 아니다
    assert extract_label("(): ")[1] != "colon"  # 쌍점 앞에 라벨 글자가 없다


def test_long_prose_repeats_and_cells_without_a_label_neighbour() -> None:
    paragraphs = doc("수요기관: 조달청", *["조달청 안내 문장입니다" for _ in range(55)])
    (group,) = propose(paragraphs, {"수요기관": "조달청"}, ["수요기관"]).groups
    assert (group.kind, len(group.spots), group.count_text) == ("proposal", 1, "라벨 옆 1곳만")
    assert group.note == "라벨 ‘수요기관:’ 옆 1곳만 골랐습니다. 다른 55곳은 라벨이 없어 고르지 않았습니다."
    cells = [ParagraphText("a", "1,234,567", 10, cell=CellRef("t", 0, 0)),
             ParagraphText("b", "1,234,567", 10, cell=CellRef("t", 0, 1))]
    (group,) = propose(cells, {"금액": "1234567"}, ["금액"]).groups
    assert group.value == "1,234,567" and group.kind == "proposal" and len(group.spots) == 2


# ------------------------------------------------------------------ rules v2 (인식률: 누름틀을 걷은 문서에서 자리 복원)
def test_year_month_program_and_its_product_binding() -> None:
    out = {t.id: text for t, text in renderings("2026/10/12 09:00:00")}
    assert out["date_dot_ym"] == "2026. 10."  # 제품 ym 은 시각을 붙이지 않는다 — 일시 값도 받는다
    assert TRANSFORMS["date_dot_ym"].binding() == {"type": "date", "fmt": "ym", "label": "표준(연·월)"}
    assert TRANSFORMS["date_dot_ym"].partial and not TRANSFORMS["date_dot"].partial


def test_year_month_is_a_candidate_only_when_the_whole_date_is_absent() -> None:
    row = {"게시일시": "2026-10-12 09:00", "개찰일시": "2026-10-21 11:00"}
    paragraphs = doc("입찰에 부치고자 다음과 같이 공고합니다.        2026. 10.", "개찰일시: 2026. 10. 21. 11:00")
    found = {(candidate.column, candidate.transform) for candidate in find_candidates(paragraphs, row)}
    assert ("게시일시", "date_dot_ym") in found and ("개찰일시", "date_dot_ym") not in found
    assert not find_candidates(doc("개찰일시: 2026. 10. 21. 11:00"), {"게시일시": "2026-10-12"})
    groups = groups_by_column(propose(paragraphs, row, list(row)))
    # 줄 끝에 정렬된 값은 값만 있는 자리다
    assert (groups["게시일시"].kind, groups["게시일시"].transform) == ("proposal", "date_dot_ym")


def test_dot_date_pieces_are_not_slots_but_a_time_after_a_date_is() -> None:
    text = "2026. 10. 19. 10:00"
    assert not boundary_ok(text, 6, 8) and not boundary_ok(text, 10, 12)  # 월·일 토막
    assert not boundary_ok(text, 0, 9)  # 연·월 뒤에 일이 이어진다
    assert boundary_ok(text, 14, 19)  # 날짜 뒤 시각은 제 자리일 수 있다
    assert boundary_ok("1. 2026. 10.", 3, 12) and boundary_ok("가. 12 대", 3, 5)


def test_contact_line_values_are_value_only_once_the_other_values_are_masked() -> None:
    paragraphs = doc("   - 조달청 구매사업국 국방물자구매과 주무관 홍길동 (☎ 042-000-0000)",
                     " ②  수요기관 연락처: 육군 한빛보급부대 물자관리과 홍길동 (☎ 042-000-1001) ")
    row = {"수요기관": "육군 한빛보급부대", "담당부서": "물자관리과", "담당자": "홍길동", "전화": "042-000-1001"}
    groups = groups_by_column(propose(paragraphs, row, list(row)))
    assert {column: group.kind for column, group in groups.items()} == dict.fromkeys(row, "proposal")
    person = groups["담당자"]
    # 직함이 앞에 오는 조달청 담당자 줄의 이름은 양식에 박힌 글자일 수 있다 — 싣지 않는다.
    assert [spot.paragraph for spot in person.spots] == [1]
    assert person.note == "값만 있는 자리 1곳을 골랐습니다. 문장 속 1곳은 고르지 않았습니다."
    assert [spot.paragraph for spot in groups["담당부서"].spots] == [1]


def test_number_frame_and_a_parenthetical_name_after_another_value() -> None:
    paragraphs = doc("조달청 물품공고 제R26BK99000001-000호",
                     "1) 시스템에 세부품명번호 10자리 9901000101(전동드릴)를 등록한 자",
                     " 품          명:  전동드릴")
    row = {"공고번호": "R26BK99000001-000", "세부품명": "전동드릴", "세부품명번호": "9901000101"}
    groups = groups_by_column(propose(paragraphs, row, list(row)))
    assert {column: group.kind for column, group in groups.items()} == dict.fromkeys(row, "proposal")
    # 「제…호」 번호 틀 안의 값은 낱말 가운데가 아니고, 「번호(이름)」의 이름은 값에 붙은 풀이다.
    assert [spot.paragraph for spot in groups["세부품명"].spots] == [1, 2] and not groups["세부품명"].note
    assert [spot.paragraph for spot in groups["세부품명번호"].spots] == [1]


def test_word_windows_and_literal_label_names() -> None:
    assert word_windows("시스템에 세부품명번호 10자리") == ["10자리", "세부품명번호 10자리", "시스템에 세부품명번호 10자리"]
    assert word_windows("") == []
    assert names_literally("품명및수량", "세부품명") and names_literally("수요기관연락처", "수요기관")
    assert not names_literally("입찰방식", "입찰방법") and not names_literally("", "x")
    # 쌍점 라벨과 자리 사이에 다른 값이 있어도 바로 앞 낱말이 열을 부를 수 있다.
    result = propose(doc("세부품명: 선박용 소화기  (품명번호 1234567890)"), {"세부품명번호": "1234567890"}, ["세부품명번호"])
    assert result.groups[0].kind == "proposal"


def test_the_label_cell_above_names_the_column_when_the_left_one_does_not() -> None:
    cells = [ParagraphText("a", "구분", 3, cell=CellRef("t", 0, 0)), ParagraphText("b", "품명", 3, cell=CellRef("t", 0, 1)),
             ParagraphText("c", "동등이상 물품", 8, cell=CellRef("t", 1, 0)),
             ParagraphText("d", "전동드릴", 5, cell=CellRef("t", 1, 1))]
    (group,) = propose(cells, {"세부품명": "전동드릴", "비고": "전동드릴"}, ["세부품명", "비고"]).groups
    assert (group.kind, group.column, group.others) == ("proposal", "세부품명", ["비고"])


def test_a_synonym_label_is_another_item_when_the_column_name_labels_a_spot() -> None:
    paragraphs = doc(" 입  찰  방  법:  전자입찰", " ① 입찰방식: 전자입찰(국내입찰)", "1) 전자입찰서")
    (group,) = propose(paragraphs, {"입찰방법": "전자입찰"}, ["입찰방법"]).groups
    assert [spot.paragraph for spot in group.spots] == [0]
    assert group.note == "라벨 ‘입 찰 방 법:’ 옆 1곳만 골랐습니다. 다른 2곳은 라벨이 없어 고르지 않았습니다."
    alone = propose(doc(" ① 입찰방식: 전자입찰(국내입찰)"), {"입찰방법": "전자입찰"}, ["입찰방법"])
    assert alone.groups[0].kind == "proposal"  # 열 이름 라벨이 없으면 동의어 라벨이 이 열의 것이다
    # 한글로 끝나는 값 뒤에 한글이 붙으면 낱말의 일부다(「전자입찰서」).
    word = propose(doc("1) 전자입찰서"), {"입찰방법": "전자입찰"}, ["입찰방법"])
    assert word.groups[0].reason == REASON_PROSE_ONCE


def test_short_values_take_value_only_spots_outside_words() -> None:
    paragraphs = doc(" 수 량 및 단 위:  40 대", " -전동드릴 / 40 대", "대한민국 대표 대학", "총 40 대를 구매")
    row = {"수량": "40", "단위": "대", "품명": "전동드릴"}  # 같은 줄의 다른 값(품명)은 가리고 본다
    groups = groups_by_column(propose(paragraphs, row, list(row)))
    assert [spot.paragraph for spot in groups["수량"].spots] == [0, 1]
    assert groups["수량"].note == "값만 있는 자리 2곳을 골랐습니다. 문장 속 1곳은 고르지 않았습니다."
    assert [spot.paragraph for spot in groups["단위"].spots] == [0, 1]


def test_blank_date_frame_numbers_are_fixed_wording() -> None:
    assert static_cue("", "20", "  .   .   .", repeats=1, prefixes=()) == CUE_FIXED
    assert static_cue("", "20", "  년   월   일", repeats=1, prefixes=()) == CUE_FIXED
    (group,) = propose(doc("수량: 20", "20  .   .   ."), {"수량": "20"}, ["수량"]).groups
    assert [spot.paragraph for spot in group.spots] == [0] and group.count_text == "라벨 옆 1곳만"
