"""가공(글자 범위·구분자 나누기) — 도메인 판정기·적용·직렬화, 그리고 실데이터 값 (field-binding/v4).

실데이터(계약 목록)가 드러낸 요구를 그대로 고정한다: ``입찰공고번호`` 의 ``-000`` 꼬리 떼기,
쉼표로 붙어 온 ``조달요구번호`` 의 마지막 것, 설명이 붙은 금액 칸에서 숫자만 뽑아 금액 표시형.
"""
from __future__ import annotations

import pytest

from hwpxfiller.domain.mapping import FieldMapping, MappingProfile, apply_transform
from hwpxfiller.domain.text_slice import (
    TextSlice,
    TextSliceError,
    apply_text_slice,
    text_slice_from_payload,
)


# ─── 적용 ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("spec", "text", "expected"),
    [
        (TextSlice("chars", start=1, length=3), "R26BK09017075", "R26"),
        (TextSlice("chars", start=4), "R26BK09017075", "BK09017075"),
        (TextSlice("chars", start=2, length=2), "계약 후 90일", "약 "),
        (TextSlice("chars", start=50), "짧은 값", ""),  # 범위 밖 = 빈 문자열(오류 아님)
        (TextSlice("chars", start=3, length=100), "abcd", "cd"),
        (TextSlice("split", delimiter="-", index=1), "R26BK09017075-000", "R26BK09017075"),
        (TextSlice("split", delimiter="-", index=2), "R26BK09017075-000", "000"),
        (TextSlice("split", delimiter="-", index=3), "R26BK09017075-000", ""),
        (TextSlice("split", delimiter=",", index=-1), "A, B ,C", "C"),  # 조각은 앞뒤 공백을 걷는다
        (TextSlice("split", delimiter=",", index=2), "A, B ,C", "B"),
        (TextSlice("split", delimiter=",", index=-3), "A,B,C", "A"),
        (TextSlice("split", delimiter=",", index=-4), "A,B,C", ""),
        (TextSlice("split", delimiter="|", index=1), "구분자 없음", "구분자 없음"),
        (TextSlice("split", delimiter=".", index=2), "a.b", "b"),  # 정규식이 아니라 글자 그대로
        (TextSlice("split", delimiter="-", index=1), "", ""),
    ],
)
def test_slice_takes_the_described_part(spec, text, expected) -> None:
    assert spec.apply(text) == expected
    assert apply_text_slice(spec, text) == expected


def test_no_slice_is_the_whole_text() -> None:
    assert apply_text_slice(None, " 그대로 ") == " 그대로 "


# ─── v5 새 방식(before·after·between·head·tail·replace·remove) — 값·자리 표 ────────────
@pytest.mark.parametrize(
    ("spec", "text", "expected_text", "expected_span"),
    [
        (TextSlice("before", delimiter="-"), "R26BK09017075-000", "R26BK09017075", (0, 13)),
        (TextSlice("before", delimiter="원"), "170,309,180원 (VAT 포함)", "170,309,180", (0, 11)),
        (TextSlice("after", delimiter="-"), "R26BK09017075-000", "000", (14, 17)),
        (TextSlice("after", delimiter="("), "170,309,180원 (VAT 포함)", "VAT 포함)", (14, 21)),
        (
            TextSlice("between", open="(", close=")"), "170,309,180원 (VAT 포함)",
            "VAT 포함", (14, 20),
        ),
        (TextSlice("head", count=3), "R26BK09017075", "R26", (0, 3)),
        (TextSlice("head", count=100), "짧음", "짧음", (0, 2)),  # 짧은 값은 그대로 — 빠짐이 아니다
        (TextSlice("tail", count=3), "R26BK09017075", "075", (10, 13)),
        (TextSlice("tail", count=100), "짧음", "짧음", (0, 2)),
        (TextSlice("replace", find="(주)", replace="주식회사"), "(주) 대한", "주식회사 대한", None),
        (TextSlice("remove", find="(VAT 포함)"), "170,309,180원 (VAT 포함)", "170,309,180원", None),
    ],
)
def test_new_mode_apply_and_span(spec, text, expected_text, expected_span) -> None:
    outcome = spec.evaluate(text)
    assert outcome.text == expected_text
    assert outcome.span == expected_span
    assert outcome.missed is False
    assert spec.apply(text) == expected_text


def test_before_after_between_strip_the_result() -> None:
    assert TextSlice("before", delimiter="-").apply(" R26 -000") == "R26"
    assert TextSlice("after", delimiter="-").apply("R26- 000 ") == "000"
    assert TextSlice("between", open="(", close=")").apply("x( y )z") == "y"


def test_chars_head_tail_do_not_strip() -> None:
    assert TextSlice("chars", start=1, length=4).apply(" abc ") == " abc"
    assert TextSlice("head", count=3).apply("  ab") == "  a"
    assert TextSlice("tail", count=3).apply("ab  ") == "b  "


def test_replace_and_remove_replace_every_occurrence_then_strip() -> None:
    assert TextSlice("replace", find="a", replace="b").apply(" aaa ") == "bbb"
    assert TextSlice("remove", find="a").apply(" a a a ") == ""  # 지운 뒤 공백뿐이면 strip 이 전부 걷는다
    assert TextSlice("remove", find="a").apply(" a b a ") == "b"


# ─── 빠짐(missable modes): 키 없음=empty, "empty" 명시=원문과 동형, "keep"=원본 그대로 ───────
@pytest.mark.parametrize(
    ("spec", "text"),
    [
        (TextSlice("before", delimiter="X"), "abc"),
        (TextSlice("after", delimiter="X"), "abc"),
        (TextSlice("between", open="(", close=")"), "no parens"),
        (TextSlice("split", delimiter="-", index=5), "a-b"),
        (TextSlice("chars", start=50), "abc"),
    ],
)
def test_missable_modes_default_to_empty_on_miss(spec, text) -> None:
    assert spec.on_missing == "empty"
    outcome = spec.evaluate(text)
    assert outcome.missed is True
    assert outcome.text == ""
    assert outcome.span is None
    assert spec.apply(text) == ""


@pytest.mark.parametrize(
    ("mode", "kwargs", "text"),
    [
        ("before", {"delimiter": "X"}, "abc"),
        ("after", {"delimiter": "X"}, "abc"),
        ("between", {"open": "(", "close": ")"}, "no parens"),
        ("split", {"delimiter": "-", "index": 5}, "a-b"),
        ("chars", {"start": 50}, "abc"),
    ],
)
def test_keep_on_missing_returns_the_original_text(mode, kwargs, text) -> None:
    spec = TextSlice(mode, on_missing="keep", **kwargs)
    outcome = spec.evaluate(text)
    assert outcome.missed is True
    assert outcome.text == text
    assert outcome.span is None


def test_explicit_empty_on_missing_normalizes_away() -> None:
    """저장 표현에서 ``"on_missing": "empty"`` 는 키 없음과 같은 뜻으로 정규화된다."""
    explicit = TextSlice.from_dict({"mode": "before", "delimiter": "X", "on_missing": "empty"})
    implicit = TextSlice.from_dict({"mode": "before", "delimiter": "X"})
    assert explicit == implicit
    assert "on_missing" not in explicit.to_dict()


def test_head_tail_replace_remove_never_miss() -> None:
    for spec, text in (
        (TextSlice("head", count=5), ""),
        (TextSlice("tail", count=5), ""),
        (TextSlice("replace", find="x", replace="y"), "no match"),
        (TextSlice("remove", find="x"), "no match"),
    ):
        assert spec.evaluate(text).missed is False


# ─── v5 검증 — 새 방식·on_missing 위반 ─────────────────────────────────────────────
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"mode": "before", "delimiter": ""}, "구분자를 비울 수 없습니다"),
        ({"mode": "before"}, "구분자를 비울 수 없습니다"),
        ({"mode": "after", "delimiter": ""}, "구분자를 비울 수 없습니다"),
        ({"mode": "between", "open": "", "close": ")"}, "가공 기준 글자가 비었음"),
        ({"mode": "between", "open": "(", "close": ""}, "가공 기준 글자가 비었음"),
        ({"mode": "between", "open": "("}, "가공 기준 글자가 비었음"),
        ({"mode": "head", "count": 0}, "글자 수는 1 이상이어야 합니다"),
        ({"mode": "head"}, "글자 수는 1 이상이어야 합니다"),
        ({"mode": "tail", "count": 0}, "글자 수는 1 이상이어야 합니다"),
        ({"mode": "head", "count": True}, "정수가 아님"),
        ({"mode": "head", "count": "3"}, "정수가 아님"),
        ({"mode": "replace", "find": "", "replace": "y"}, "찾을 글자가 비었음"),
        ({"mode": "replace", "find": "x", "replace": ""}, "바꿀 글자가 비었음"),
        ({"mode": "replace", "find": "x"}, "바꿀 글자가 비었음"),
        ({"mode": "remove", "find": ""}, "찾을 글자가 비었음"),
        ({"mode": "remove"}, "찾을 글자가 비었음"),
        # from_dict 는 빠짐 없는 방식에 on_missing 키 자체를 허용하지 않는다(모르는 키로 거절).
        ({"mode": "head", "count": 3, "on_missing": "keep"}, "모르는 키"),
        ({"mode": "tail", "count": 3, "on_missing": "empty"}, "모르는 키"),
        ({"mode": "replace", "find": "x", "replace": "y", "on_missing": "keep"}, "모르는 키"),
        ({"mode": "remove", "find": "x", "on_missing": "keep"}, "모르는 키"),
        ({"mode": "before", "delimiter": "x", "on_missing": "vanish"}, "알 수 없는 빠짐 처리"),
        ({"mode": "before", "delimiter": "\ud800"}, "유효하지 않은 Unicode"),
        ({"mode": "between", "open": "(", "close": ")", "start": 1}, "모르는 키"),
    ],
)
def test_v5_malformed_spec_is_rejected_loudly(payload, message) -> None:
    with pytest.raises(TextSliceError, match=message):
        text_slice_from_payload(payload)


def test_constructor_rejects_on_missing_on_a_non_missable_mode() -> None:
    """생성자로 직접 지어도 같은 판정기다 — ``from_dict`` 의 키 거절과는 다른 경로(모양은 맞되 뜻이 없음)."""
    with pytest.raises(TextSliceError, match="빠짐 처리가 없음"):
        TextSlice("head", count=3, on_missing="keep")
    with pytest.raises(TextSliceError, match="빠짐 처리가 없음"):
        TextSlice("replace", find="x", replace="y", on_missing="keep")


# ─── 판정(모양) — 잘못된 명세는 고치지 않고 거절 ─────────────────────────────────
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"mode": "split", "delimiter": "", "index": 1}, "구분자를 비울 수 없습니다"),
        ({"mode": "split", "index": 1}, "구분자를 비울 수 없습니다"),
        ({"mode": "split", "delimiter": "-", "index": 0}, "번째는 0이 될 수 없습니다"),
        ({"mode": "split", "delimiter": "-"}, "번째는 0이 될 수 없습니다"),
        ({"mode": "chars", "start": 0}, "시작은 1 이상이어야 합니다"),
        ({"mode": "chars"}, "시작은 1 이상이어야 합니다"),
        ({"mode": "chars", "start": 1, "length": 0}, "글자 수는 1 이상이어야 합니다"),
        ({"mode": "regex", "pattern": ".*"}, "알 수 없는 가공 방식"),
        ({"mode": "chars", "start": "1"}, "정수가 아님"),
        ({"mode": "chars", "start": True}, "정수가 아님"),  # bool 은 int 의 하위형이라 명시로 막는다
        ({"mode": "chars", "start": 1.0}, "정수가 아님"),
        ({"mode": "split", "delimiter": "-", "index": "1"}, "정수가 아님"),
        ({"mode": "split", "delimiter": 3, "index": 1}, "문자열이 아님"),
        ({"mode": "chars", "start": 1, "index": 1}, "모르는 키"),
        ({"mode": "split", "delimiter": "-", "index": 1, "start": 1}, "모르는 키"),
        ("chars", "사전이 아님"),
    ],
)
def test_malformed_spec_is_rejected_loudly(payload, message) -> None:
    with pytest.raises(TextSliceError, match=message):
        text_slice_from_payload(payload)


def test_constructor_rejects_mixed_fields() -> None:
    with pytest.raises(TextSliceError):
        TextSlice("chars", start=1, delimiter="-")
    with pytest.raises(TextSliceError):
        TextSlice("split", delimiter="-", index=1, length=2)


def test_lone_surrogate_delimiter_is_rejected() -> None:
    with pytest.raises(TextSliceError):
        TextSlice("split", delimiter="\ud800", index=1)


# ─── 직렬화 — 쓰지 않는 칸은 적지 않는다 ──────────────────────────────────────────
@pytest.mark.parametrize(
    ("spec", "encoded"),
    [
        (TextSlice("chars", start=1, length=3), {"mode": "chars", "start": 1, "length": 3}),
        (TextSlice("chars", start=2), {"mode": "chars", "start": 2}),
        (TextSlice("split", delimiter=", ", index=-1),
         {"mode": "split", "delimiter": ", ", "index": -1}),
    ],
)
def test_round_trip(spec, encoded) -> None:
    assert spec.to_dict() == encoded
    assert TextSlice.from_dict(encoded) == spec
    assert text_slice_from_payload(spec) is spec
    assert text_slice_from_payload(None) is None


@pytest.mark.parametrize(
    ("spec", "encoded"),
    [
        (TextSlice("before", delimiter="-"), {"mode": "before", "delimiter": "-"}),
        (
            TextSlice("before", delimiter="-", on_missing="keep"),
            {"mode": "before", "delimiter": "-", "on_missing": "keep"},
        ),
        (TextSlice("after", delimiter="("), {"mode": "after", "delimiter": "("}),
        (
            TextSlice("between", open="(", close=")"),
            {"mode": "between", "open": "(", "close": ")"},
        ),
        (
            TextSlice("between", open="(", close=")", on_missing="keep"),
            {"mode": "between", "open": "(", "close": ")", "on_missing": "keep"},
        ),
        (TextSlice("split", delimiter="-", index=1), {"mode": "split", "delimiter": "-", "index": 1}),
        (
            TextSlice("split", delimiter="-", index=1, on_missing="keep"),
            {"mode": "split", "delimiter": "-", "index": 1, "on_missing": "keep"},
        ),
        (TextSlice("head", count=4), {"mode": "head", "count": 4}),
        (TextSlice("tail", count=8), {"mode": "tail", "count": 8}),
        (TextSlice("chars", start=3, length=4), {"mode": "chars", "start": 3, "length": 4}),
        (
            TextSlice("chars", start=3, on_missing="keep"),
            {"mode": "chars", "start": 3, "on_missing": "keep"},
        ),
        (
            TextSlice("replace", find="(주)", replace="주식회사"),
            {"mode": "replace", "find": "(주)", "replace": "주식회사"},
        ),
        (
            TextSlice("remove", find="(VAT 포함)"),
            {"mode": "remove", "find": "(VAT 포함)"},
        ),
    ],
)
def test_round_trip_every_mode(spec, encoded) -> None:
    """9 방식 전부 — 쓰지 않는 칸은 적지 않고 ``on_missing`` 은 ``keep`` 일 때만 적는다."""
    assert spec.to_dict() == encoded
    assert TextSlice.from_dict(encoded) == spec
    assert text_slice_from_payload(encoded) == spec


def test_v4_shaped_specs_serialize_byte_identically_to_before() -> None:
    """v4 가 적던 두 방식(글자 범위·구분자 나누기, 빠짐은 빈 값)의 dict 모양은 v5 에서 그대로다."""
    assert TextSlice("split", delimiter="-", index=1).to_dict() == {
        "mode": "split", "delimiter": "-", "index": 1,
    }
    assert TextSlice("chars", start=1, length=3).to_dict() == {
        "mode": "chars", "start": 1, "length": 3,
    }
    assert TextSlice("chars", start=2).to_dict() == {"mode": "chars", "start": 2}


# ─── Mapping — 저장·적용 ──────────────────────────────────────────────────────────
def test_field_mapping_serializes_slice_only_when_set() -> None:
    plain = FieldMapping("공고번호", "입찰공고번호")
    assert "slice" not in plain.to_dict()  # 가공 없는 작업의 저장 bytes 는 v4 이전 그대로
    assert FieldMapping.from_dict(plain.to_dict()) == plain
    sliced = FieldMapping(
        "공고번호", "입찰공고번호", slice=TextSlice("split", delimiter="-", index=1)
    )
    data = sliced.to_dict()
    assert data["slice"] == {"mode": "split", "delimiter": "-", "index": 1}
    assert FieldMapping.from_dict(data) == sliced
    # 사전으로 넣어도 같은 판정기를 지난다.
    assert FieldMapping("f", "k", slice={"mode": "chars", "start": 1}).slice == TextSlice(
        "chars", start=1
    )


def test_profile_round_trip_keeps_slices() -> None:
    profile = MappingProfile(
        name="계약",
        mappings=[
            FieldMapping("a", "k", slice=TextSlice("chars", start=1, length=3)),
            FieldMapping("b", "k"),
        ],
    )
    assert MappingProfile.from_dict(profile.to_dict()).mappings == profile.mappings


def test_field_mapping_refuses_a_slice_on_non_carrier_types() -> None:
    with pytest.raises(ValueError, match="가공"):
        FieldMapping("f", type="const", const="x", slice=TextSlice("chars", start=1))
    with pytest.raises(ValueError, match="가공"):
        FieldMapping.from_dict(
            {"template_field": "f", "type": "today", "slice": {"mode": "chars", "start": 1}}
        )
    with pytest.raises(TextSliceError):
        FieldMapping.from_dict(
            {"template_field": "f", "source": "k", "slice": {"mode": "split", "index": 1}}
        )


def test_apply_transform_order_is_strip_then_slice_then_format() -> None:
    spec = TextSlice("split", delimiter="원", index=1)
    assert apply_transform(
        "amount", "  170,309,180원 (VAT 포함) ", fmt="", text_slice=spec
    ) == "170,309,180원"
    # 고정값·오늘 날짜는 원본 칸이 없다 — 가공을 보지 않는다.
    assert apply_transform("const", "무시", const="고정", text_slice=spec) == "고정"


# ─── 실데이터 스모크(계약 목록) ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("column", "raw", "type_", "fmt", "spec", "expected"),
    [
        ("입찰공고번호", "R26BK09017075-000", "text", "",
         {"mode": "split", "delimiter": "-", "index": 1}, "R26BK09017075"),
        ("계약번호", "R26TA0911050700", "text", "",
         {"mode": "chars", "start": 1, "length": 3}, "R26"),
        ("조달요구번호", "MPKPLA26910290, MPKPLA26910291", "text", "",
         {"mode": "split", "delimiter": ", ", "index": -1}, "MPKPLA26910291"),
        ("납품기한", "계약 후 90일 이내", "text", "",
         {"mode": "split", "delimiter": " ", "index": 3}, "90일"),
        # 금액 칸에 설명이 붙어 온다 — 「원」 앞 조각을 금액 기본 표시형(「원」 붙임)으로.
        ("계약금액", "170,309,180원 (VAT 포함)", "amount", "",
         {"mode": "split", "delimiter": "원", "index": 1}, "170,309,180원"),
    ],
)
def test_real_contract_list_values(column, raw, type_, fmt, spec, expected) -> None:
    mapping = FieldMapping("필드", column, type=type_, fmt=fmt, slice=spec)
    assert mapping.value_for({column: raw}) == expected
