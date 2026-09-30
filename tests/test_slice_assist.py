"""「가공」 편집 보조 — 문장·방식 목록·끌어 고르기 제안·미리보기 (:mod:`hwpxfiller.viewmodel.slice_assist`).

이 모듈은 판정 자체(도메인 :mod:`hwpxfiller.domain.text_slice`)를 사람이 읽을 문장·표로 옮길
뿐이다 — 여기서 재는 것은 문장의 정확한 철자, 제안이 실데이터에서 고르는 방식, 미리보기 상태·
표식·접근성 문안이다.
"""
from __future__ import annotations

import pytest

from hwpxfiller.domain.job import MISSING_MARKER
from hwpxfiller.domain.text_slice import TextSlice
from hwpxfiller.viewmodel.slice_assist import (
    GROUP_EDIT_LABEL,
    GROUP_PART_LABEL,
    NO_CANDIDATE_MESSAGE,
    NO_SLICE_HINT,
    SLICE_ADD_LABEL,
    SLICE_PREVIEW_ROWS,
    code_point_offset,
    ordinal_label,
    preview_slice,
    propose_slices,
    slice_label,
    slice_methods,
    slice_query,
    slice_values,
    split_index_options,
    value_shape,
)

AMOUNTS = [
    "170,309,180원 (VAT 포함)",
    "48,500,000원 (VAT 포함)",
    "9,900,000원",
    "1,230,000원 (VAT 별도)",
    "",
]
BIDS = ["R26BK09017075-000", "R26BK09017076-001", "R26BK09017077-002", ""]


# ─── 몇째 조각 — 사람 말 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (1, "첫째"), (2, "둘째"), (3, "셋째"), (4, "넷째"), (5, "다섯째"),
        (6, "여섯째"), (7, "일곱째"), (8, "여덟째"), (9, "아홉째"), (10, "열째"),
        (11, "11번째"), (-1, "마지막"), (-2, "끝에서 둘째"), (-3, "끝에서 셋째"),
    ],
)
def test_ordinal_labels(index, expected) -> None:
    assert ordinal_label(index) == expected


def test_split_index_options_default_and_unusual_stored_index() -> None:
    """기본 넷(1·2·3·마지막)에 저장 명세의 번째가 없으면 더한다 — 양수 오름차순·음수 내림차순."""
    assert split_index_options(None) == [
        {"value": 1, "label": "첫째"}, {"value": 2, "label": "둘째"},
        {"value": 3, "label": "셋째"}, {"value": -1, "label": "마지막"},
    ]
    with_5 = split_index_options(TextSlice("split", delimiter="-", index=5))
    assert with_5 == [
        {"value": 1, "label": "첫째"}, {"value": 2, "label": "둘째"},
        {"value": 3, "label": "셋째"}, {"value": 5, "label": "다섯째"},
        {"value": -1, "label": "마지막"},
    ]
    with_neg2 = split_index_options(TextSlice("split", delimiter="-", index=-2))
    assert with_neg2 == [
        {"value": 1, "label": "첫째"}, {"value": 2, "label": "둘째"},
        {"value": 3, "label": "셋째"}, {"value": -1, "label": "마지막"},
        {"value": -2, "label": "끝에서 둘째"},
    ]
    # 기본에 이미 있는 값이면 더하지 않는다(중복 없음).
    assert split_index_options(TextSlice("split", delimiter="-", index=1)) == split_index_options(None)


# ─── 문장 — 방식마다 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (None, SLICE_ADD_LABEL),
        (TextSlice("before", delimiter="-"), "‘-’ 앞까지"),
        (TextSlice("after", delimiter="("), "‘(’ 뒤부터"),
        (TextSlice("between", open="(", close=")"), "‘(’ 뒤부터 ‘)’ 앞까지"),
        (TextSlice("split", delimiter=",", index=1), "‘,’로 나눈 조각 중 첫째"),
        (TextSlice("head", count=11), "앞에서 11글자"),
        (TextSlice("tail", count=8), "뒤에서 8글자"),
        (TextSlice("chars", start=3, length=4), "3번째 글자부터 4글자"),
        (TextSlice("chars", start=3), "3번째 글자부터"),
        (TextSlice("replace", find="(주)", replace="주식회사"), "‘(주)’ 대신 ‘주식회사’"),
        (TextSlice("remove", find="(VAT 포함)"), "‘(VAT 포함)’ 지우기"),
    ],
)
def test_slice_label_sentences(spec, expected) -> None:
    assert slice_label(spec) == expected


# ─── 값 모양·좌표 ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("R26BK09017075-000", "a9a9-9"),
        ("  트림  ", "가"),
        ("", ""),
        ("가나다 123 ABC", "가 9 a"),
    ],
)
def test_value_shape(text, expected) -> None:
    assert value_shape(text) == expected


def test_code_point_offset_maps_utf16_units_to_python_indices() -> None:
    text = "a" + "\U00020000" + "b"  # 비 BMP 글자 하나(UTF-16 서로게이트 쌍)
    assert code_point_offset(text, 0) == 0
    assert code_point_offset(text, 1) == 1  # 서로게이트 쌍 시작
    assert code_point_offset(text, 3) == 2  # 쌍 뒤 — 'b'
    assert code_point_offset(text, 4) == 3  # 끝
    with pytest.raises(ValueError, match="글자 가운데"):
        code_point_offset(text, 2)  # 서로게이트 쌍 한가운데
    with pytest.raises(ValueError, match="올바르지 않음"):
        code_point_offset(text, -1)
    with pytest.raises(ValueError, match="올바르지 않음"):
        code_point_offset(text, True)  # bool 은 int 의 하위형이라 명시로 막는다
    with pytest.raises(ValueError, match="값 밖"):
        code_point_offset(text, 100)


# ─── 방식 목록 — 무리·빠짐 칸 ────────────────────────────────────────────────────
def test_slice_methods_groups_and_miss_choice() -> None:
    groups = slice_methods(None)
    assert [g["label"] for g in groups] == [GROUP_PART_LABEL, GROUP_EDIT_LABEL]
    part_modes = [m["mode"] for m in groups[0]["methods"]]
    edit_modes = [m["mode"] for m in groups[1]["methods"]]
    assert part_modes == ["before", "after", "between", "split", "head", "tail", "chars"]
    assert edit_modes == ["replace", "remove"]
    by_mode = {m["mode"]: m for g in groups for m in g["methods"]}
    for mode in ("before", "after", "between", "split", "chars"):
        assert by_mode[mode]["on_missing"] == "keep"
    for mode in ("head", "tail", "replace", "remove"):
        assert by_mode[mode]["on_missing"] is None
    for mode in ("before", "after", "between"):
        assert by_mode[mode]["miss_choice"] is True
    for mode in ("split", "head", "tail", "chars", "replace", "remove"):
        assert by_mode[mode]["miss_choice"] is False


# ─── 불러온 행 값 — 앞 SLICE_PREVIEW_ROWS 행, 걷은 문자열 ──────────────────────────
def test_slice_values_windows_to_preview_rows_and_strips() -> None:
    records = [{"금액": f" {i} "} for i in range(SLICE_PREVIEW_ROWS + 5)]
    values = slice_values(records, "금액")
    assert len(values) == SLICE_PREVIEW_ROWS
    assert values[0] == "0"
    assert values == [str(i) for i in range(SLICE_PREVIEW_ROWS)]
    assert slice_values([{"다른": "x"}], "금액") == [""]


# ─── 제안 — 예시 값에서 고른 부분을 재현하는 방식 ─────────────────────────────────
def test_proposal_prefers_the_candidate_that_fits_most_rows() -> None:
    """‘원’ 앞까지(4/4)가 앞에서 11글자(1/4)를 앞선다 — 불러온 행 중 같은 모양 수로 정렬한다."""
    result = propose_slices(AMOUNTS, 0, 0, 11)
    assert result["ok"] is True
    assert [c["mode"] for c in result["candidates"]] == ["before", "head"]
    first = result["candidates"][0]
    assert first["label"] == "‘원’ 앞까지"
    assert first["slice"] == {"mode": "before", "delimiter": "원", "on_missing": "keep"}
    assert (first["matched"], first["total"], first["full"]) == (4, 4, True)
    assert first["tag"] == "4/4행 맞음"
    assert first["tip"] == "맞는 행: 값 있는 4행 중 4행"
    second = result["candidates"][1]
    assert (second["mode"], second["matched"], second["full"]) == ("head", 1, False)


def test_proposal_orders_ties_by_generation_order() -> None:
    """‘R26BK09017075-000’ 형 값에서 앞까지·나누기·자리(앞에서 N)가 모두 재현하면 그 순서다."""
    result = propose_slices(BIDS, 0, 0, 13)
    assert [c["mode"] for c in result["candidates"]] == ["before", "split", "head"]
    for candidate in result["candidates"]:
        assert candidate["full"] is True and candidate["matched"] == candidate["total"] == 3


def test_proposal_no_candidate_message_for_whitespace_only_selection() -> None:
    values = ["a   b", "c   d"]
    result = propose_slices(values, 0, 1, 4)  # 고른 부분이 공백뿐 — strip 하면 빈 문자열
    assert result == {"ok": True, "candidates": [], "message": NO_CANDIDATE_MESSAGE}


def test_proposal_rejects_an_invalid_or_empty_sample() -> None:
    values = ["a", "b"]
    with pytest.raises(ValueError):
        propose_slices(values, 5, 0, 1)  # 범위 밖 행
    with pytest.raises(ValueError):
        propose_slices(["", ""], 0, 0, 1)  # 예시 행이 빈 값
    with pytest.raises(ValueError):
        propose_slices(values, 0, 1, 0)  # 거꾸로 된 범위 UTF-16 오프셋 (end < start)


# ─── 미리보기 — 상태·표식·접근성 ────────────────────────────────────────────────
def test_preview_hit_status_and_summary_omits_zero_parts() -> None:
    result = preview_slice("금액", TextSlice("before", delimiter="원"), AMOUNTS)
    statuses = [row["status"] for row in result["rows"]]
    assert statuses == ["hit", "hit", "hit", "hit", "empty"]
    assert result["summary"] == "맞음 4행 · 빈 값 1행"  # 형식 다름·확인 필요 0행은 문장에 없다
    assert result["rows_label"] == f"불러온 {len(AMOUNTS)}행 미리보기"
    assert result["hint"] == ""
    miss_choice = result["miss_choice"]
    assert miss_choice["label"] == "‘원’ 없는 행"
    assert miss_choice["value"] == "empty"


def test_preview_odd_status_when_shape_differs_from_the_sample() -> None:
    values = ["ABC123", "12X456", "가나123", ""]
    result = preview_slice("f", TextSlice("chars", start=1, length=3), values)
    statuses = [row["status"] for row in result["rows"]]
    assert statuses == ["hit", "odd", "odd", "empty"]
    assert result["rows"][1]["tags"] == ["형식 다름"]
    assert result["summary"] == "맞음 1행 · 형식 다름 2행 · 빈 값 1행"


def test_preview_miss_status_and_tags_by_mode() -> None:
    values = ["a-b", "no-dash-removed", "just"]
    result = preview_slice("f", TextSlice("split", delimiter="-", index=3), values)
    assert [row["status"] for row in result["rows"]] == ["miss", "hit", "miss"]
    assert result["rows"][0]["tags"] == ["조각 없음"]
    assert result["rows"][0]["marker"] is True
    assert result["rows"][0]["result"] == MISSING_MARKER.format(field="f")

    before_miss = preview_slice("f", TextSlice("before", delimiter="X"), ["abc"])
    assert before_miss["rows"][0]["tags"] == ["‘X’ 없음"]

    between_miss = preview_slice("f", TextSlice("between", open="(", close=")"), ["no parens"])
    assert between_miss["rows"][0]["tags"] == ["‘(’ 또는 ‘)’ 없음"]

    chars_miss = preview_slice("f", TextSlice("chars", start=50), ["abc"])
    assert chars_miss["rows"][0]["status"] == "miss"
    assert chars_miss["rows"][0]["tags"] == ["확인 필요"]


def test_preview_empty_status_for_blank_cells() -> None:
    result = preview_slice("f", TextSlice("before", delimiter="-"), [""])
    assert result["rows"][0] == {
        "index": 0, "label": "1행", "pre": "", "keep": "", "post": "",
        "result": MISSING_MARKER.format(field="f"), "marker": True, "status": "empty", "tags": [],
    }


def test_preview_replace_and_remove_never_go_odd() -> None:
    values = ["a1", "c1", ""]
    result = preview_slice("f", TextSlice("replace", find="a", replace="b"), values)
    assert [row["status"] for row in result["rows"]] == ["hit", "hit", "empty"]
    assert result["miss_choice"] is None  # 바꾸기·지우기에는 빠짐 처리가 없다


def test_preview_no_slice_hint_and_plain_status() -> None:
    result = preview_slice("f", None, ["a", "b"])
    assert result["hint"] == NO_SLICE_HINT
    assert [row["status"] for row in result["rows"]] == ["plain", "plain"]
    assert [row["result"] for row in result["rows"]] == ["a", "b"]


def test_preview_empty_result_gets_the_missing_marker_and_marker_flag() -> None:
    """가공이 고른 부분이 빈 문자열이면(빠짐이 아니어도) 생성과 같은 표식을 낸다."""
    result = preview_slice("금액", TextSlice("remove", find="x"), ["xxx"])
    assert result["rows"][0]["result"] == MISSING_MARKER.format(field="금액")
    assert result["rows"][0]["marker"] is True


def test_preview_keep_on_missing_returns_the_original_text() -> None:
    spec = TextSlice("before", delimiter="X", on_missing="keep")
    result = preview_slice("f", spec, ["abc"])
    assert result["rows"][0]["result"] == "abc"
    assert result["rows"][0]["marker"] is False
    assert result["rows"][0]["status"] == "miss"


def test_preview_samples_aria_and_disabled_and_sample_fallback() -> None:
    values = ["", "b", "c"]
    result = preview_slice("f", TextSlice("before", delimiter="X"), values)
    assert result["samples"] == [
        {"index": 0, "label": "1", "aria": "1행, 빈 값", "disabled": True, "pressed": False},
        {"index": 1, "label": "2", "aria": "2행", "disabled": False, "pressed": True},
        {"index": 2, "label": "3", "aria": "3행", "disabled": False, "pressed": False},
    ]
    # 요청한 행(0)이 빈 값이라 값 있는 첫 행(1)으로 대체된다.
    assert result["sample"]["index"] == 1
    requested = preview_slice("f", TextSlice("before", delimiter="X"), values, sample=2)
    assert requested["sample"]["index"] == 2


def test_preview_window_is_bounded_by_slice_preview_rows() -> None:
    values = [str(i) for i in range(SLICE_PREVIEW_ROWS + 3)]
    result = preview_slice("f", None, values)
    assert len(result["rows"]) == len(values)  # preview_slice 는 이미 창이 씌워진 값을 받는다
    assert result["rows_label"] == f"불러온 {len(values)}행 미리보기"


# ─── 무변이 질의 — 원본 칸이 없으면 거절 ─────────────────────────────────────────
def test_slice_query_refuses_when_the_row_has_no_source_cell() -> None:
    with pytest.raises(ValueError, match="가공은 데이터 열 값에만"):
        slice_query(
            "preview", field="f", source="k", spec=None, enabled=False,
            records=[], payload={},
        )


def test_slice_query_preview_and_propose_share_the_same_body() -> None:
    records = [{"금액": v} for v in AMOUNTS]
    preview = slice_query(
        "preview", field="금액", source="금액",
        spec=TextSlice("before", delimiter="원"), enabled=True,
        records=records, payload={},
    )
    assert preview["ok"] is True and preview["rows"][0]["status"] == "hit"
    propose = slice_query(
        "propose", field="금액", source="금액", spec=None, enabled=True,
        records=records, payload={"sample": 0, "start": 0, "end": 11},
    )
    assert propose["ok"] is True and propose["candidates"][0]["mode"] == "before"
    with pytest.raises(ValueError, match="알 수 없는 가공 질의"):
        slice_query(
            "delete", field="금액", source="금액", spec=None, enabled=True,
            records=records, payload={},
        )
