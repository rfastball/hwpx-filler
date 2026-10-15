"""데이터 계약 값 모델·codec·관찰·판정(#1188 WP-02) — 순수 도메인, 창·디스크 불필요.

계약은 꾸러미에 실려 남에게 가므로 **값이 새지 않는 것**과 **틀린 계약을 관대하게 읽지 않는 것**이
먼저다. 관찰은 미리보기·생성과 같은 해석기(``source_value_outcome``)를 쓰므로 빈 값(표식)과 실패가
그 해석기의 사실로 갈린다.
"""
from __future__ import annotations

import json

import pytest

from hwpxfiller.domain import format_engine
from hwpxfiller.domain.data_contract import (
    DATA_CONTRACT_SCHEMA,
    DataContract,
    DataContractError,
    FieldContract,
    binding_fingerprint,
    decode_data_contract,
    encode_data_contract,
)
from hwpxfiller.domain.data_contract_check import (
    judge_binding,
    judge_fixed_binding,
    judge_job_binding,
    observe_binding,
    profile_data_contract,
    value_shape,
)
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile, apply_transform
from hwpxfiller.domain.text_slice import TextSlice

SENDER = [
    {"공고명": "전산장비 구매", "추정가격": "24750000", "계약일자": "2026-06-15",
     "입찰공고번호": "R26BK09017075-000", "담당코드": "1001"},
    {"공고명": "사무용품", "추정가격": "1,200,000원", "계약일자": "2026.7.1",
     "입찰공고번호": "R26BK09017076-000", "담당코드": "1002"},
    {"공고명": "  ", "추정가격": "", "계약일자": "", "입찰공고번호": "", "담당코드": ""},
]
COLUMNS = list(SENDER[0])

TITLE = FieldMapping("건명", "공고명")
AMOUNT = FieldMapping("금액", "추정가격", type="amount")
DATE = FieldMapping("계약일", "계약일자", type="date")
NOTICE_NO = FieldMapping(
    "공고번호", "입찰공고번호", slice=TextSlice(mode="before", delimiter="-", on_missing="keep")
)
OWNER = FieldMapping("담당", "담당코드")
FIXED = FieldMapping("작성자", type="const", const="홍길동")
TODAY = FieldMapping("작성일", type="today")
PROFILE = MappingProfile(mappings=[TITLE, AMOUNT, DATE, NOTICE_NO, OWNER, FIXED, TODAY])


def _contract() -> DataContract:
    return profile_data_contract(PROFILE, SENDER)


def _entry(name: str) -> FieldContract:
    entry = _contract().entry_for(name)
    assert entry is not None
    return entry


# ───────────────────────────────────────────── 표시형 해석기의 「읽었는가」
@pytest.mark.parametrize(
    ("kind", "code", "value", "readable"),
    [
        ("date", "", "2026-06-15", True),
        ("date", "%Y-%m-%d", "2026-06-15", True),     # 같은 글자로 나와도 읽은 것이다
        ("date", "%H:%M", "1400", True),               # 시각 단독값은 시각 서식에서 읽힌다
        ("date", "", "미정", False),
        ("date", "kor", "미정", False),
        ("amount", "", "1,200원", True),
        ("amount", "", "협의", False),
        ("amount", "{:q}", "1200", False),             # 잘못된 서식 코드도 degrade
        ("text", "", "아무거나", True),
        ("text", "phone", "01012345678", True),
        ("text", "phone", "12", False),
        ("text", "biz", "1234567890", True),
        ("text", "nope", "값", False),                 # 모르는 마스크 코드
    ],
)
def test_render_outcome_reports_degrade_without_changing_the_rendered_text(kind, code, value, readable):
    outcome = format_engine.render_outcome(kind, code, value)
    assert outcome.readable is readable
    assert outcome.text == format_engine.render(kind, code, value)   # 생성 글자는 그대로다
    if not readable:
        assert outcome.text == value


def test_apply_transform_text_is_the_outcome_text():
    for mapping in (TITLE, AMOUNT, DATE, NOTICE_NO):
        for record in SENDER:
            raw = str(record.get(mapping.source, ""))
            assert mapping.value_for(record) == apply_transform(
                mapping.type, raw, mapping.const, mapping.fmt, text_slice=mapping.slice
            )


# ───────────────────────────────────────────── 관찰: 빈 값 ≠ 실패
def test_profile_counts_rows_blanks_and_shapes_per_field():
    contract = _contract()
    assert [e.field for e in contract.fields] == ["건명", "금액", "계약일", "공고번호", "담당"]
    title, amount, date = _entry("건명"), _entry("금액"), _entry("계약일")
    assert (title.rows, title.blanks, title.failures, title.shape) == (3, 1, 0, "text")
    assert title.length == (4, 7)
    assert (amount.blanks, amount.failures, amount.shape) == (1, 0, "number")
    assert (date.blanks, date.failures, date.shape) == (1, 0, "date")
    notice = _entry("공고번호")
    assert (notice.failures, notice.shape, notice.length) == (0, "text", (13, 13))
    assert _entry("담당").shape == "number"


def test_fixed_value_and_today_rows_have_no_contract_entry():
    contract = _contract()
    assert contract.entry_for("작성자") is None and contract.entry_for("작성일") is None


def test_blank_is_not_a_failure_but_unreadable_values_are():
    records = [{"d": ""}, {"d": "   "}, {"d": None}, {"d": "미정"}, {"d": "2026-01-02"}]
    seen = observe_binding(FieldMapping("날짜", "d", type="date"), records)
    assert (seen.rows, seen.blanks, seen.format_failures, seen.slice_misses) == (5, 3, 1, 0)
    amount = observe_binding(FieldMapping("금액", "a", type="amount"), [{"a": "협의"}, {"a": "100"}])
    assert (amount.blanks, amount.failures, amount.shape) == (0, 1, "number")


def test_slice_miss_is_a_failure_whatever_on_missing_says_and_empty_pick_is_blank():
    records = [{"n": "A-1"}, {"n": "B2"}, {"n": "-tail"}]
    for policy in ("keep", "empty"):
        spec = TextSlice(mode="before", delimiter="-", on_missing=policy)
        seen = observe_binding(FieldMapping("번호", "n", slice=spec), records)
        # 'B2' 는 기준 글자가 없어 실패, '-tail' 은 기준 앞이 비어 빈 값(생성은 표식을 넣는다).
        assert (seen.slice_misses, seen.blanks, seen.shape) == (1, 1, "text")


def test_value_shape_classes():
    assert value_shape("24750000") == "number"
    assert value_shape("-1,200.5원") == "number"
    assert value_shape("2026-06-15") == "date"
    assert value_shape("2026.7.1") == "date"
    # 등급은 날짜 해석기가 읽는 대로다 — 해석기가 못 읽는 꼴은 날짜 모양이 아니다.
    assert value_shape("2026년 6월 15일") == "text"
    assert value_shape("R26BK0901") == "text"


# ───────────────────────────────────────────── codec
def test_codec_round_trip_through_json():
    contract = _contract()
    encoded = json.loads(json.dumps(encode_data_contract(contract), ensure_ascii=False))
    assert encoded["schema"] == DATA_CONTRACT_SCHEMA
    assert decode_data_contract(encoded) == contract


def test_contract_carries_no_values_or_samples():
    """꾸러미에 실리는 계약에는 데이터 값·가공 조각·고정값이 한 글자도 없다(열·필드 이름만)."""
    dumped = json.dumps(encode_data_contract(_contract()), ensure_ascii=False)
    leaked = [
        token
        for record in SENDER
        for value in record.values()
        for token in (value.strip(), value.strip().split("-")[0])
        if len(token) >= 2 and token in dumped
    ]
    assert leaked == []
    assert "홍길동" not in dumped
    allowed = {"schema", "fields", "field", "column", "binding", "rows", "blanks", "failures",
               "shape", "length"}
    for entry in json.loads(dumped)["fields"]:
        assert set(entry) <= allowed


def _encoded_entry(**changes) -> dict:
    raw = encode_data_contract(_contract())
    raw["fields"][0].update(changes)
    return raw


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"schema": DATA_CONTRACT_SCHEMA},
        {"schema": "data-contract/v2", "fields": []},
        {"schema": DATA_CONTRACT_SCHEMA, "fields": [], "extra": 1},
        {"schema": DATA_CONTRACT_SCHEMA, "fields": {}},
        _encoded_entry(sample="전산장비"),
        _encoded_entry(rows=True),
        _encoded_entry(rows=0),
        _encoded_entry(blanks=-1),
        _encoded_entry(blanks=3, failures=1),
        _encoded_entry(shape="phone"),
        _encoded_entry(length=None),
        _encoded_entry(length=[7, 4]),
        _encoded_entry(length=[4]),
        _encoded_entry(binding="md5:abc"),
        _encoded_entry(column=""),
    ],
)
def test_decode_rejects_unknown_or_malformed_contracts_loudly(raw):
    with pytest.raises(DataContractError):
        decode_data_contract(raw)


def test_empty_shape_must_not_carry_a_length_and_fields_are_unique():
    raw = _encoded_entry(shape="empty")
    with pytest.raises(DataContractError):
        decode_data_contract(raw)
    raw = encode_data_contract(_contract())
    raw["fields"].append(dict(raw["fields"][0]))
    with pytest.raises(DataContractError, match="두 번"):
        decode_data_contract(raw)


# ───────────────────────────────────────────── 판정
RECEIVED = [
    {"공고명": "청소용역", "추정가격": "5,000,000", "계약일자": "2026-09-01",
     "입찰공고번호": "R26BK1-001", "담당코드": "2001"},
    {"공고명": "", "추정가격": "700000원", "계약일자": "2026/10/2",
     "입찰공고번호": "R26BK2-002", "담당코드": "2002"},
]


def _judge(mapping: FieldMapping, records=None, columns=None):
    return judge_binding(
        _entry(mapping.template_field), mapping,
        COLUMNS if columns is None else columns, RECEIVED if records is None else records,
    )


def test_clean_received_data_passes_every_source_binding():
    for mapping in (TITLE, AMOUNT, DATE, NOTICE_NO, OWNER):
        verdict = _judge(mapping)
        assert verdict.passed, (mapping.template_field, verdict.reason)
        assert verdict.reason == "" and verdict.binding == binding_fingerprint(mapping)


def test_unreadable_dates_fail_with_the_row_count():
    records = [dict(RECEIVED[0]), dict(RECEIVED[1], 계약일자="추후 협의")]
    verdict = _judge(DATE, records)
    assert not verdict.passed and verdict.reason == "날짜로 읽히지 않는 값 1행"
    records = [dict(RECEIVED[0], 추정가격="협의")]
    assert _judge(AMOUNT, records).reason == "금액으로 읽히지 않는 값 1행"


def test_missing_slice_anchor_fails_with_the_anchor_named():
    records = [dict(r, 입찰공고번호="R26BK0901") for r in RECEIVED]
    assert _judge(NOTICE_NO, records).reason == "기준 글자 ‘-’가 없는 행 2"


def test_missing_column_fails():
    columns = [c for c in COLUMNS if c != "계약일자"]
    assert _judge(DATE, columns=columns).reason == "열 없음"


def test_edited_binding_never_auto_confirms():
    edited = FieldMapping("계약일", "계약일자", type="date", fmt="kor")
    verdict = _judge(edited)
    assert not verdict.passed and verdict.reason == "꾸러미와 연결이 다름"
    other_column = FieldMapping("건명", "입찰공고번호")
    assert _judge(other_column).reason == "꾸러미와 연결이 다름"


def test_shape_change_and_all_blank_fail():
    records = [dict(r, 담당코드="A-1") for r in RECEIVED]
    assert _judge(OWNER, records).reason == "값 모양이 다름"
    records = [dict(r, 담당코드="") for r in RECEIVED]
    assert _judge(OWNER, records).reason == "값이 모두 비어 있음"


def test_failure_rate_no_worse_than_the_sender_passes():
    sender = [{"d": "2026-01-01"}, {"d": "미정"}]          # 보낸 쪽 실패율 1/2
    mapping = FieldMapping("날짜", "d", type="date")
    entry = profile_data_contract(MappingProfile(mappings=[mapping]), sender).fields[0]
    same = [{"d": "2026-02-02"}, {"d": "추후"}]
    assert judge_binding(entry, mapping, ["d"], same).passed
    worse = [{"d": "2026-02-02"}, {"d": "추후"}, {"d": "미상"}]
    assert judge_binding(entry, mapping, ["d"], worse).reason == "날짜로 읽히지 않는 값 2행"


def test_sender_without_values_requires_zero_failures():
    mapping = FieldMapping("날짜", "d", type="date")
    entry = profile_data_contract(MappingProfile(mappings=[mapping]), [{"d": ""}]).fields[0]
    assert entry.shape == "empty" and entry.length is None
    assert judge_binding(entry, mapping, ["d"], [{"d": ""}]).passed
    assert not judge_binding(entry, mapping, ["d"], [{"d": "미정"}]).passed


def test_fixed_rows_pass_only_when_unchanged_from_the_saved_mapping():
    assert judge_fixed_binding(FIXED, FIXED).passed
    changed = FieldMapping("작성자", type="const", const="김철수")
    assert judge_fixed_binding(changed, FIXED).reason == "꾸러미와 연결이 다름"
    assert not judge_fixed_binding(FIXED, None).passed


def test_job_binding_without_a_contract_entry_is_not_judged():
    contract = _contract()
    extra = FieldMapping("비고", "공고명")
    assert judge_job_binding(contract, PROFILE, extra, COLUMNS, RECEIVED) is None
    verdict = judge_job_binding(contract, PROFILE, TODAY, COLUMNS, RECEIVED)
    assert verdict is not None and verdict.passed
