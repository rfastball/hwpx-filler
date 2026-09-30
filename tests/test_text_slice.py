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
