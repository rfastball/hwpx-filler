"""필터 선언 상태 모델 회귀 — R-flow 블록 4(결정 23~25) + 미결 3항 확정(2026-07-19).

시안 ``https://github.com/rfastball/hwpx-filler/blob/5f51e442dde87891b68fbbdc1519a04e01211b8e/docs/r-flow-mockups/block4-filter-crystallize-demo.html`` 상태 기계의 이식 검증 + 확정 편차의 명문:
프루닝=텍스트 수명(열 편집 생존) · 연속 검색=그룹 교체 · 가지 1 정규화 안 함 · 범위
조건=엑셀 사용자 지정 동형(동적 프리셋 제외, 피연산자 설정 시점 시끄러운 거절).
"""
from __future__ import annotations

import pytest

from hwpxfiller.viewmodel.filter_state import (
    KIND_AMOUNT,
    KIND_DATE,
    KIND_TEXT,
    FilterModel,
    SEARCH_DIMENSION,
    PresetStateError,
    RangeClause,
    RangeCondition,
    range_condition_from_payload,
    sniff_column_kinds,
)

# 시안 걷기 코퍼스 축소판 — 공고명·수요기관(텍스트)·마감일(날짜)·금액(수)·비고(빈값 보유).
ROWS = [
    {"공고명": "행정도시 청사 이전", "수요기관": "행복도시건설청", "마감일": "2026-07-20",
     "금액": "1,000,000원", "비고": ""},
    {"공고명": "물품 구매", "수요기관": "세종청사관리소", "마감일": "2026-07-25",
     "금액": "2,500,000원", "비고": "행복도시 납품"},
    {"공고명": "닭고기 급식 납품", "수요기관": "행복도시건설청", "마감일": "2026-08-01",
     "금액": "500,000원", "비고": ""},
    {"공고명": "사무용품", "수요기관": "조달청", "마감일": "2026-08-10",
     "금액": "3,000,000원", "비고": "긴급"},
]
COLS = list(ROWS[0].keys())
KINDS = {"공고명": KIND_TEXT, "수요기관": KIND_TEXT, "마감일": KIND_DATE,
         "금액": KIND_AMOUNT, "비고": KIND_TEXT}


def model() -> FilterModel:
    return FilterModel(COLS, KINDS)


# ------------------------------------------------------------------ 유형 스니핑
def test_sniff_amount_and_date() -> None:
    kinds = sniff_column_kinds(ROWS)
    assert kinds["금액"] == KIND_AMOUNT
    assert kinds["마감일"] == KIND_DATE
    assert kinds["공고명"] == KIND_TEXT
    assert kinds["비고"] == KIND_TEXT  # 빈값 혼재 — 텍스트


def test_sniff_compact_date() -> None:
    """8자리 압축 날짜(20260715)는 날짜로 승격 — 정부 데이터 통용 형태."""
    rows = [{"d": "20260715"}, {"d": "20260801"}]
    # 압축 날짜는 수로도 읽히므로 amount 가 먼저 이긴다 — 비교는 어느 쪽이든 순서 보존
    # (YYYYMMDD 수 비교 = 날짜 순). 구분자 있는 날짜만 date 로 간다.
    assert sniff_column_kinds(rows)["d"] == KIND_AMOUNT
    rows2 = [{"d": "2026-07-15"}, {"d": "2026.8.1"}]
    assert sniff_column_kinds(rows2)["d"] == KIND_DATE


def test_sniff_id_run_is_not_date() -> None:
    """공고번호류 연속 숫자런(20260715623-00)은 날짜 오판하지 않는다(앵커 검사)."""
    rows = [{"no": "20260715623-00"}, {"no": "20260716001-01"}]
    assert sniff_column_kinds(rows)["no"] == KIND_TEXT


def test_sniff_hint_wins() -> None:
    """매핑 확정 유형(힌트)이 값 스니핑보다 우선 — 사용자 확정 존중."""
    rows = [{"c": "1000"}, {"c": "2000"}]
    assert sniff_column_kinds(rows)["c"] == KIND_AMOUNT
    assert sniff_column_kinds(rows, hints={"c": KIND_TEXT})["c"] == KIND_TEXT


def test_sniff_all_blank_is_text() -> None:
    rows = [{"c": ""}, {"c": ""}]
    assert sniff_column_kinds(rows)["c"] == KIND_TEXT


def test_sniff_codelike_text_not_promoted_to_amount() -> None:
    """「1차」·「A-1」·「3층」류 코드성 텍스트는 금액 승격 금지(리뷰 #2).

    승격의 대가 = 전열 검색 가지 제외(침묵 배제) — 오판의 안전 방향은 text 뿐이다.
    """
    assert sniff_column_kinds([{"c": "1차"}, {"c": "2차"}])["c"] == KIND_TEXT
    assert sniff_column_kinds([{"c": "A-1"}, {"c": "B-2"}])["c"] == KIND_TEXT
    assert sniff_column_kinds([{"c": "3층"}, {"c": "5층"}])["c"] == KIND_TEXT
    assert sniff_column_kinds([{"c": "1억"}, {"c": "2억"}])["c"] == KIND_TEXT
    # 엄격 형태는 승격 유지 — 콤마 그룹·원 접미·소수점.
    assert sniff_column_kinds([{"c": "1,000,000원"}, {"c": "500원"}])["c"] == KIND_AMOUNT
    assert sniff_column_kinds([{"c": "1.5"}, {"c": "-3"}])["c"] == KIND_AMOUNT


# ------------------------------------------------------------- 열 조건(AND·OR)
def test_value_checklist_or_within_column() -> None:
    m = model()
    m.set_values("수요기관", {"행복도시건설청", "조달청"})
    assert m.visible_indices(ROWS) == [0, 2, 3]


def test_blank_is_first_class_value() -> None:
    """(빈값) 일급 — 빈 비고 행만 남기기(여집합 표현, 결정 23)."""
    m = model()
    m.set_values("비고", {""})
    assert m.visible_indices(ROWS) == [0, 2]


def test_columns_are_anded() -> None:
    m = model()
    m.set_values("수요기관", {"행복도시건설청"})
    m.set_text("공고명", "닭")
    assert m.visible_indices(ROWS) == [2]


def test_column_text_is_jamo_partial() -> None:
    """열 텍스트 = 자모 부분일치 — 「달」 단계에서 「닭고기」가 이미 맞는다."""
    m = model()
    m.set_text("공고명", "달")
    assert m.visible_indices(ROWS) == [2]


def test_unknown_column_is_loud() -> None:
    m = model()
    with pytest.raises(ValueError, match="알 수 없는 열"):
        m.set_text("없는열", "x")


# ------------------------------------------------------------- 전열 검색(그룹)
def test_search_installs_branches_only_where_matches() -> None:
    """재현 OR 그룹 — 실매치 있는 텍스트 열에만 가지(시안 동형), 일자·금액 열 제외."""
    m = model()
    m.set_search("행복도")
    assert m.group_branches(ROWS) == ["수요기관", "비고"]  # 공고명엔 「행복도」 없음
    assert m.visible_indices(ROWS) == [0, 1, 2]


def test_search_ime_intermediate() -> None:
    """「행복도ㅅ」 단계에서 이미 걸린다(결정 23 문언의 그 장면)."""
    m = model()
    m.set_search("행복도ㅅ")
    assert m.visible_indices(ROWS) == [0, 1, 2]


def test_search_no_match_is_empty_view() -> None:
    """어느 열에도 매치 없음 = 전멸(빈 화면이 정직한 재진술)."""
    m = model()
    m.set_search("존재하지않는말")
    assert m.group_branches(ROWS) == []
    assert m.visible_indices(ROWS) == []


def test_branch_respects_column_conditions() -> None:
    """가지 설치는 열 조건 통과 행 기준 — 배제된 행에서만 맞는 열에 가지를 안 세운다."""
    m = model()
    m.set_values("수요기관", {"행복도시건설청"})  # 비고에 「행복도」 있는 1행 배제
    m.set_search("행복도")
    assert m.group_branches(ROWS) == ["수요기관"]


def test_pruning_survives_column_edit_dies_on_text_edit() -> None:
    """프루닝 = 텍스트 수명(미결 확정 1) — 열 편집엔 생존, 검색어 수정에 복귀."""
    m = model()
    m.set_search("행복도")
    m.prune_branch("비고", ROWS)
    assert m.group_branches(ROWS) == ["수요기관"]
    m.set_values("마감일", None)  # 열 편집 — 프루닝 생존
    assert m.group_branches(ROWS) == ["수요기관"]
    m.set_search("행복도시")  # 그룹 재정의 — 프루닝 복귀
    assert "비고" in m.group_branches(ROWS)


def test_search_replaces_group() -> None:
    """연속 검색 = 교체(미결 확정 2) — 그룹은 항상 최대 1개."""
    m = model()
    m.set_search("행복도")
    m.set_search("긴급")
    assert m.group_branches(ROWS) == ["비고"]
    assert m.visible_indices(ROWS) == [3]


def test_single_branch_group_is_not_normalized() -> None:
    """가지 1 정규화 안 함(미결 확정 3) — 그룹으로 잔존, 열-조건은 비어 있다."""
    m = model()
    m.set_search("긴급")
    assert m.group_branches(ROWS) == ["비고"]
    assert not m.has_condition("비고")
    assert "(비고) 포함 '긴급'" in m.describe(ROWS)


def test_pruning_last_branch_dissolves_group() -> None:
    """마지막 가지 프루닝 = 그룹 해산(시안 동형, 리뷰 #3) — 빈 화면 함정 아님."""
    m = model()
    m.set_search("긴급")
    m.prune_branch("비고", ROWS)  # 유일 가지 — 검색 해제 의사
    assert m.search_text == ""
    assert not m.is_active()
    assert m.visible_indices(ROWS) == [0, 1, 2, 3]  # 전 행 복귀(빈 화면·거짓 정의줄 없음)


def test_search_and_text_inputs_are_trimmed() -> None:
    """양끝 공백 트리밍(시안 동형, 리뷰 #4) — 보이지 않는 문자가 조건이 되지 않는다."""
    m = model()
    m.set_search("  ")
    assert not m.is_active()
    assert m.visible_indices(ROWS) == [0, 1, 2, 3]
    m.set_search(" 행복도 ")
    assert m.search_text == "행복도"
    m.set_text("공고명", "  ")
    assert not m.has_condition("공고명")


# ------------------------------------------------------------------ 범위 조건
def test_range_amount_comparisons() -> None:
    m = model()
    m.set_range("금액", RangeCondition(RangeClause("ge", "1,000,000")))
    assert m.visible_indices(ROWS) == [0, 1, 3]  # 콤마 그룹은 엄격 형태에 포함
    m.set_range("금액", RangeCondition(RangeClause("lt", "1000000")))
    assert m.visible_indices(ROWS) == [2]
    m.set_range("금액", RangeCondition(RangeClause("eq", "2500000")))
    assert m.visible_indices(ROWS) == [1]


def test_range_two_clauses_and_or() -> None:
    m = model()
    m.set_range("금액", RangeCondition(
        RangeClause("ge", "1000000"), RangeClause("le", "2500000"), joiner="and"))
    assert m.visible_indices(ROWS) == [0, 1]  # 해당 범위(Between) 동형
    m.set_range("금액", RangeCondition(
        RangeClause("lt", "600000"), RangeClause("gt", "2900000"), joiner="or"))
    assert m.visible_indices(ROWS) == [2, 3]


def test_range_date_comparison() -> None:
    m = model()
    m.set_range("마감일", RangeCondition(RangeClause("le", "2026-07-31")))
    assert m.visible_indices(ROWS) == [0, 1]


def test_range_on_text_column_is_loud() -> None:
    m = model()
    with pytest.raises(ValueError, match="일자·금액 열 전용"):
        m.set_range("공고명", RangeCondition(RangeClause("ge", "1")))


def test_range_bad_operand_is_loud() -> None:
    """피연산자 파싱 불가 = 설정 시점 시끄러운 거절(엑셀의 조용한 문자열 강등 대신)."""
    m = model()
    with pytest.raises(ValueError, match="읽을 수 없습니다"):
        m.set_range("마감일", RangeCondition(RangeClause("ge", "다음주")))
    with pytest.raises(ValueError, match="읽을 수 없습니다"):
        m.set_range("금액", RangeCondition(RangeClause("ge", "많이")))


def test_range_misreadable_operand_is_loud() -> None:
    """관대 파싱의 조용한 오독도 거절(리뷰 #1) — 「1억」이 1로 읽혀 전 행 매치되는 함정."""
    m = model()
    with pytest.raises(ValueError, match="읽을 수 없습니다"):
        m.set_range("금액", RangeCondition(RangeClause("ge", "1억")))
    with pytest.raises(ValueError, match="읽을 수 없습니다"):
        m.set_range("마감일", RangeCondition(RangeClause("le", "제2026-15호")))


def test_range_none_first_clause_is_loud() -> None:
    """첫 절 None = 설정 시점 거절(리뷰 #5) — 평가 중 지연 폭발 금지."""
    m = model()
    with pytest.raises(ValueError, match="첫 절"):
        m.set_range("금액", RangeCondition(None))  # type: ignore[arg-type]


def test_range_date_granularity_follows_operand() -> None:
    """날짜 입도(리뷰 #0) — 시각 없는 피연산자는 날짜 입도, 시각 쓰면 분 입도."""
    rows = [{"마감": "2026-07-15 14:00"}, {"마감": "2026-07-16 09:00"}]
    m = FilterModel(["마감"], {"마감": KIND_DATE})
    m.set_range("마감", RangeCondition(RangeClause("le", "2026-07-15")))
    assert m.visible_indices(rows) == [0]  # 당일 14:00 이 자정 비교로 탈락하지 않는다
    m.set_range("마감", RangeCondition(RangeClause("eq", "2026-07-15")))
    assert m.visible_indices(rows) == [0]  # 같은 날 = 매치
    m.set_range("마감", RangeCondition(RangeClause("le", "2026-07-15 13:00")))
    assert m.visible_indices(rows) == []  # 시각 선언 = 분 입도 그대로


def test_range_bad_op_or_joiner_is_loud() -> None:
    m = model()
    with pytest.raises(ValueError, match="비교 연산자"):
        m.set_range("금액", RangeCondition(RangeClause("like", "1")))
    with pytest.raises(ValueError, match="조건 연결 방식"):
        m.set_range("금액", RangeCondition(
            RangeClause("ge", "1"), RangeClause("le", "2"), joiner="xor"))


def test_range_unparseable_cell_never_matches() -> None:
    """파싱 불가 셀은 불매치(엑셀 동형) — ne 로도 안 들어온다."""
    rows = [{"c": "1000"}, {"c": "미정"}, {"c": ""}]
    m = FilterModel(["c"], {"c": KIND_AMOUNT})
    m.set_range("c", RangeCondition(RangeClause("ne", "9999")))
    assert m.visible_indices(rows) == [0]


# ------------------------------------------------------------------ 값 목록
def test_column_values_excludes_own_condition() -> None:
    """체크리스트 값 목록 = 자기 열 조건 제외(엑셀 동형 — 체크를 풀 수 있어야 한다)."""
    m = model()
    m.set_values("수요기관", {"조달청"})
    assert m.column_values("수요기관", ROWS) == ["행복도시건설청", "세종청사관리소", "조달청"]


def test_column_values_context_and_blank_last() -> None:
    m = model()
    m.set_values("수요기관", {"행복도시건설청"})
    assert m.column_values("비고", ROWS) == [""]  # 남은 행의 비고는 빈값뿐 — 말미(여기선 유일)
    m2 = model()
    assert m2.column_values("비고", ROWS) == ["행복도시 납품", "긴급", ""]  # (빈값) 말미


# ------------------------------------------------------------- 정의줄·칩 문안
def test_describe_parts_shapes() -> None:
    m = model()
    m.set_values("수요기관", {"조달청"})
    m.set_text("공고명", "사무")
    m.set_range("금액", RangeCondition(
        RangeClause("ge", "1000"), RangeClause("le", "4000000"), joiner="and"))
    m.set_search("긴급")  # 조건 통과 행(3행)의 비고에 실매치 — 가지 = 비고
    parts = m.describe_parts(ROWS)
    assert "수요기관 = 조달청" in parts
    assert "공고명 포함 '사무'" in parts
    assert "금액 ≥ '1000' ∧ ≤ '4000000'" in parts
    assert "(비고) 포함 '긴급'" in parts
    assert " · ".join(parts) == m.describe(ROWS)


def test_describe_multi_values_and_blank_label() -> None:
    m = model()
    m.set_values("비고", ["긴급", ""])
    (part,) = m.describe_parts(ROWS)
    assert part == "비고 ∈ {긴급, (빈값)}"


def test_describe_search_without_match_is_honest() -> None:
    m = model()
    m.set_search("없는말")
    assert m.describe_parts(ROWS) == ["검색 '없는말' (매치 없음)"]


# ------------------------------------------------------------- 층화 표본(결정 5)
def test_stratified_sample_covers_minority_branch() -> None:
    """소수 가지(비고 1행)가 반드시 표본에 등장 — 표본 뒤에 숨는 오버매치 소멸."""
    rows = (
        [{"공고명": f"행복도시 사업 {i}", "비고": ""} for i in range(10)]
        + [{"공고명": "무관", "비고": "행복도시 납품"}]
    )
    m = FilterModel(["공고명", "비고"])
    m.set_search("행복도시")
    indices = m.visible_indices(rows)
    sample = m.stratified_sample(indices, rows, 3)
    assert 10 in sample  # 소수 가지(비고) 매치 — 단순 앞 표본이면 절대 안 나옴
    assert len(sample) == 3
    assert sample == sorted(sample)  # 원본 순서 보존


def test_stratified_sample_without_group_is_front() -> None:
    m = model()
    assert m.stratified_sample([0, 1, 2, 3], ROWS, 2) == [0, 1]
    assert m.stratified_sample([2, 3], ROWS, 0) == []


def test_stratified_sample_branch_reps_may_exceed_limit() -> None:
    """가지 대표가 상한을 넘으면 표본이 상한을 넘는다(결정 5 — 커버리지가 상한 우선)."""
    rows = [
        {"a": "공통어 하나", "b": "", "c": ""},
        {"a": "", "b": "공통어 둘", "c": ""},
        {"a": "", "b": "", "c": "공통어 셋"},
    ]
    m = FilterModel(["a", "b", "c"])
    m.set_search("공통어")
    sample = m.stratified_sample([0, 1, 2], rows, 1)
    assert sample == [0, 1, 2]  # 가지 3개 전부 대표


# ------------------------------------------------- 하이라이트 세그먼트(PR-1 계약)
def test_segments_split_match() -> None:
    m = model()
    m.set_text("공고명", "청사")
    assert m.segments("공고명", "행정도시 청사 이전", ROWS) == [
        ("행정도시 ", False), ("청사", True), (" 이전", False),
    ]


def test_segments_group_term_only_on_branch_column() -> None:
    """전열 검색어는 가지 열에서만 칠한다 — 가지 아닌 열은 통짜."""
    m = model()
    m.set_search("행복도")
    assert m.segments("수요기관", "행복도시건설청", ROWS)[0] == ("행복도", True)
    assert m.segments("마감일", "2026-07-20", ROWS) == [("2026-07-20", False)]


def test_segments_search_term_wins_over_column_term() -> None:
    """적용 순서 = 전열 검색 → 열 텍스트(첫 매치 하나만, 시안 mark 동형 — 리뷰 #6)."""
    m = model()
    m.set_text("수요기관", "건설청")
    m.set_search("행복도")
    segs = m.segments("수요기관", "행복도시건설청", ROWS)
    assert segs == [("행복도", True), ("시건설청", False)]


def test_segments_empty_value() -> None:
    m = model()
    assert m.segments("비고", "", ROWS) == []


# ------------------------------------------------------------------ 평가 뷰
def test_view_caches_branches_and_matches_model_delegates() -> None:
    """렌더 경로 계약(리뷰 #9) — view() 가 가지를 1회 산출·캐시, 위임과 결과 동일."""
    m = model()
    m.set_search("행복도")
    v = m.view(ROWS)
    assert v.branches == m.group_branches(ROWS)
    assert v.visible_indices() == m.visible_indices(ROWS)
    assert v.describe() == m.describe(ROWS)
    # 셀 반복 호출(렌더 루프의 그 패턴)이 같은 뷰에서 일관 — 가지 재산출 없음.
    for r in ROWS:
        assert v.segments("수요기관", r["수요기관"]) == m.segments("수요기관", r["수요기관"], ROWS)


# ------------------------------------------------------------------ 초기화·해제
def test_clear_column_and_clear_all() -> None:
    m = model()
    m.set_values("수요기관", {"조달청"})
    m.set_search("긴급")
    m.prune_branch("공고명", ROWS)
    assert m.is_active()
    m.clear_column("수요기관")
    assert not m.has_condition("수요기관")
    assert m.is_active()  # 검색은 남아 있다
    m.clear()
    assert not m.is_active()
    assert m.visible_indices(ROWS) == [0, 1, 2, 3]


# ------------------------------------------- 정의 이송(직전 필터 슬롯, 결정 28)
def test_export_apply_roundtrip_including_pruning() -> None:
    """정의 왕복 — 검색·프루닝·값 순서·텍스트·범위가 그대로 복원된다(결정 27 소실 창 복원)."""
    m = model()
    m.set_values("수요기관", ["조달청", "행복도시건설청"])
    m.set_text("공고명", "물품")
    m.set_range("금액", RangeCondition(RangeClause("ge", "1000"), RangeClause("le", "2000000"), joiner="and"))
    m.set_search("행복도")
    m.prune_branch("비고", ROWS)
    state = m.export_state()
    m2 = model()
    installed, dropped = m2.apply_state(state)
    assert set(installed) == {"수요기관", "공고명", "금액"} and dropped == []
    assert m2.describe(ROWS) == m.describe(ROWS)          # 정의줄 동일 = 재현 담보
    assert m2.group_branches(ROWS) == m.group_branches(ROWS)  # 프루닝 포함(비고 제외)


def test_apply_state_partial_column_loss() -> None:
    """열 결손 백스톱(결정 28) — 부분 설치 + 탈락 목록, 유형 변경 범위는 그 조건만 탈락."""
    m = model()
    m.set_values("수요기관", ["조달청"])
    m.set_range("금액", RangeCondition(RangeClause("ge", "1000")))
    m.set_search("긴급")
    state = m.export_state()
    # 새 지형: 수요기관 없음, 금액은 텍스트 열로 변함.
    m2 = FilterModel(["공고명", "금액"], {"공고명": KIND_TEXT, "금액": KIND_TEXT})
    installed, dropped = m2.apply_state(state)
    assert installed == []                                 # 값·범위 다 못 섰다
    assert set(dropped) == {"수요기관", "금액(범위)"}
    assert m2.search_text == "긴급"                        # 검색은 열 불가지 — 생존


def test_apply_state_prunes_only_existing_columns() -> None:
    m = model()
    m.set_search("행복도")
    m.prune_branch("비고", ROWS)
    state = m.export_state()
    m2 = FilterModel(["공고명", "수요기관"])                # 비고 없음
    m2.apply_state(state)
    assert m2.search_text == "행복도"
    assert "수요기관" in m2.group_branches(
        [{"공고명": "x", "수요기관": "행복도시청"}])        # 부재 열 프루닝은 조용히 소거


# ------------------------------------------------ 저장한 필터(이름 붙인 칩, 2026-09-30)
# 사용자 사례: 추정가격 1억 미만 = 소기업, 1억 이상 고시금액 미만 = 중소기업. 자동 추론은 없고
# 고시금액(여기선 2억 2천만)은 사용자가 직접 친다. 값은 콤마 서식 원문 그대로다.
# 합성 규칙(2026-09-30 사용자 확정, 슬라이서 관례): 같은 열을 보는 저장본끼리 「또는」,
# 다른 열과는 「그리고」, 열 머리 조건은 늘 「그리고」.
PRICE_ROWS = [
    {"공고명": "청사 청소", "추정가격": "95,000,000", "계약일자": "2026-03-02"},
    {"공고명": "전산 유지보수", "추정가격": "150,000,000", "계약일자": "2026-08-14"},
    {"공고명": "공용차량 임차", "추정가격": "230,000,000", "계약일자": "2026-05-20"},
    {"공고명": "사무용품", "추정가격": "50,000,000", "계약일자": "2026-09-01"},
    {"공고명": "방역 용역", "추정가격": "219,999,999", "계약일자": "2026-06-30"},
]

SMALL = {"columns": {"추정가격": {"range": {
    "first": {"op": "lt", "operand": "100,000,000"}, "second": None, "joiner": "and",
}}}}
MEDIUM = {"columns": {"추정가격": {"range": {
    "first": {"op": "ge", "operand": "100,000,000"},
    "second": {"op": "lt", "operand": "220,000,000"}, "joiner": "and",
}}}}
FIRST_HALF = {"columns": {"계약일자": {"range": {
    "first": {"op": "ge", "operand": "2026-01-01"},
    "second": {"op": "le", "operand": "2026-06-30"}, "joiner": "and",
}}}}


def price_model() -> FilterModel:
    kinds = sniff_column_kinds(PRICE_ROWS)
    assert kinds["추정가격"] == KIND_AMOUNT  # 콤마 서식 = 엄격 금액 형태
    assert kinds["계약일자"] == KIND_DATE
    return FilterModel(list(PRICE_ROWS[0]), kinds)


def _save_small_and_medium(m: FilterModel) -> None:
    """빌더 경로로 두 저장본을 세운다 — 만들기는 켜므로 곧바로 끈다."""
    assert m.create_preset("소기업", SMALL) == "소기업"
    m.deactivate_preset("소기업")
    assert m.create_preset(" 중소기업 ", MEDIUM) == "중소기업"  # 이름 양끝 공백은 다듬는다
    m.deactivate_preset("중소기업")


def test_preset_dimension_is_the_constrained_columns_plus_search() -> None:
    m = price_model()
    _save_small_and_medium(m)
    m.create_preset("상반기", FIRST_HALF)
    m.create_preset("청소 상반기", {
        "columns": {
            "공고명": {"text": "청소", "values": None, "range": None},
            "계약일자": FIRST_HALF["columns"]["계약일자"],
        },
    })
    m.create_preset("전산 검색", {"search": "전산"})
    m.create_preset("소액 전산", {"search": "전산", "columns": SMALL["columns"]})
    assert m.preset_columns("소기업") == frozenset({"추정가격"})
    assert m.preset_dimension("소기업") == m.preset_dimension("중소기업") == frozenset({"추정가격"})
    assert m.preset_dimension("청소 상반기") == frozenset({"공고명", "계약일자"})
    assert m.preset_columns("전산 검색") == frozenset()
    assert m.preset_dimension("전산 검색") == frozenset({SEARCH_DIMENSION})
    assert m.preset_dimension("소액 전산") == frozenset({"추정가격", SEARCH_DIMENSION})
    # 무리 = 차원별(첫 등장 순), 표지는 열 순서·열쇠는 정렬, 검색은 「검색」.
    assert m.preset_groups() == [
        ["소기업", "중소기업"], ["상반기"], ["청소 상반기"], ["전산 검색"], ["소액 전산"],
    ]
    assert m.dimension_label("청소 상반기") == "공고명·계약일자"
    assert m.dimension_key("청소 상반기") == "계약일자·공고명"
    assert m.dimension_label("소액 전산") == m.dimension_key("소액 전산") == "추정가격·검색"
    assert m.dimension_label("전산 검색") == "검색"
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        m.preset_dimension("없음")


def test_same_dimension_presets_combine_with_or() -> None:
    """같은 열을 보는 두 칩을 함께 켜면 두 구간이 모두 보인다 — 합집합."""
    m = price_model()
    _save_small_and_medium(m)
    assert not m.is_active() and m.visible_indices(PRICE_ROWS) == [0, 1, 2, 3, 4]

    m.toggle_preset("소기업")
    assert m.visible_indices(PRICE_ROWS) == [0, 3]  # 1억 미만만
    m.toggle_preset("중소기업")
    view = m.view(PRICE_ROWS)
    assert view.visible_indices() == [0, 1, 3, 4]  # 고시금액 미만 전부(합집합)
    assert view.describe() == "필터 '소기업' 또는 '중소기업'"
    assert view.preset_parts() == ["필터 '소기업' 또는 '중소기업'"]
    assert m.active_preset_groups() == [["소기업", "중소기업"]]

    m.toggle_preset("소기업")  # 소기업만 끄면 중소기업 행이 남는다
    assert m.visible_indices(PRICE_ROWS) == [1, 4]
    assert m.describe(PRICE_ROWS) == "필터 '중소기업'"


def test_different_dimensions_combine_with_and() -> None:
    m = price_model()
    _save_small_and_medium(m)
    m.create_preset("상반기", FIRST_HALF)  # 만들기 = 켜짐
    m.deactivate_preset("상반기")
    m.toggle_preset("소기업")
    m.toggle_preset("상반기")
    view = m.view(PRICE_ROWS)
    assert view.visible_indices() == [0]  # 1억 미만 ∩ 상반기
    assert view.preset_parts() == ["필터 '소기업'", "필터 '상반기'"]
    m.toggle_preset("중소기업")  # (소기업 ∨ 중소기업) ∧ 상반기
    view = m.view(PRICE_ROWS)
    assert view.visible_indices() == [0, 4]
    assert view.describe() == "필터 '소기업' 또는 '중소기업' · 필터 '상반기'"


def test_a_dimension_without_active_presets_imposes_nothing() -> None:
    m = price_model()
    _save_small_and_medium(m)
    m.create_preset("상반기", FIRST_HALF)
    m.deactivate_preset("상반기")
    m.toggle_preset("상반기")  # 추정가격 무리는 전부 꺼짐 — 금액은 조이지 않는다
    assert m.visible_indices(PRICE_ROWS) == [0, 2, 4]
    assert m.describe(PRICE_ROWS) == "필터 '상반기'"


def test_preset_and_adhoc_conditions_combine_with_and() -> None:
    m = price_model()
    _save_small_and_medium(m)
    m.toggle_preset("중소기업")
    m.toggle_preset("소기업")
    m.set_text("공고명", "전산")
    view = m.view(PRICE_ROWS)
    assert view.visible_indices() == [1]
    assert view.preset_parts() == ["필터 '중소기업' 또는 '소기업'"]
    assert view.adhoc_parts() == ["공고명 포함 '전산'"]
    assert view.describe_parts() == ["필터 '중소기업' 또는 '소기업'", "공고명 포함 '전산'"]
    # 값 목록(체크리스트 소재)도 켜진 저장본을 통과한 행만 본다.
    m.set_text("공고명", "")
    assert m.view(PRICE_ROWS).column_values("공고명") == [
        "청사 청소", "전산 유지보수", "사무용품", "방역 용역",
    ]
    # 같은 열이라도 열 머리 조건은 저장본과 「그리고」다(차원 무리에 끼지 않는다).
    m.set_range("추정가격", RangeCondition(RangeClause("ge", "100,000,000")))
    assert m.visible_indices(PRICE_ROWS) == [1, 4]


def test_column_headers_see_saved_filter_groups_and_header_edits_keep_the_chip_on() -> None:
    """켜진 저장본은 이 모델의 무리다 — 그 열의 머리도 조건 표지(무리 문안)를 세우고, 그 열의
    머리 편집은 지금 조건(그리고)을 더할 뿐 칩을 끄지 않는다. 「열 조건」 칩은 머리 조건만이다."""
    m = price_model()
    _save_small_and_medium(m)
    assert m.column_constraints("추정가격") == []
    m.toggle_preset("소기업")
    m.toggle_preset("중소기업")
    assert m.column_constraints("추정가격") == ["필터 '소기업' 또는 '중소기업'"]
    assert m.column_constraints("공고명") == [] and not m.has_condition("추정가격")
    m.set_range("추정가격", RangeCondition(RangeClause("ge", "100,000,000")))
    assert m.active_presets == ["소기업", "중소기업"]  # 머리 편집은 칩을 끄지 않는다
    assert m.column_constraints("추정가격") == [
        "필터 '소기업' 또는 '중소기업'", "추정가격 ≥ '100,000,000'",
    ]
    view = m.view(PRICE_ROWS)
    assert view.visible_indices() == [1, 4]  # (소기업 ∨ 중소기업) ∧ 머리 조건
    assert [chip["column"] for chip in view.adhoc_chips()] == ["추정가격"]
    assert view.adhoc_chips()[0]["text"] == "추정가격 ≥ '100,000,000'"
    m.set_search("청")
    chips = m.view(PRICE_ROWS).adhoc_chips()
    assert [chip["column"] for chip in chips] == ["추정가격", ""]  # 검색 칩은 열이 없다(× 없음)
    assert chips[-1]["text"] == "검색 '청' (매치 없음)"
    m.clear()  # 「모두 보기」 — 머리 조건·검색·켜진 저장본 전부(정의는 남는다)
    assert not m.is_active() and m.column_constraints("추정가격") == [] and len(m.presets) == 2


def test_saved_filter_search_is_a_group_member_evaluated_by_the_same_predicates() -> None:
    """검색을 든 저장본도 곁 모델 없이 평가된다 — 가지는 그 저장본 자신의 열 조건을 통과한 행에서."""
    m = price_model()
    m.create_preset("소액 청소", {"columns": SMALL["columns"], "search": "청소"})
    assert m.visible_indices(PRICE_ROWS) == [0]
    assert m.preset_description("소액 청소", PRICE_ROWS) == (
        "추정가격 < '100,000,000' · (공고명) 포함 '청소'"
    )
    assert m.count_state({"search": "용", "columns": {}}, PRICE_ROWS) == 3  # 공용·사무용품·용역
    m.set_search("방역")  # 지금 검색은 그리고 — 저장본의 가지 산출을 바꾸지 않는다
    assert m.visible_indices(PRICE_ROWS) == []
    assert not hasattr(m, "_preset_models")  # 곁 평가 모델을 들지 않는다


def test_create_preset_from_adhoc_crystallizes_the_current_conditions() -> None:
    """지금 조건으로 채워 연 빌더의 저장 = 칩 하나로 접힌다. 보이는 행은 그대로다."""
    m = price_model()
    m.set_range("추정가격", RangeCondition(RangeClause("lt", "100,000,000")))
    m.set_search("청")
    before = m.visible_indices(PRICE_ROWS)
    m.create_preset("소기업 청소", m.adhoc_state(), from_adhoc=True)
    assert m.visible_indices(PRICE_ROWS) == before == [0]
    assert not m.has_adhoc() and m.active_presets == ["소기업 청소"]
    saved = m.presets[0]["state"]
    assert saved["search"] == "청" and "추정가격" in saved["columns"]
    assert "active_presets" not in saved  # 저장본은 지금 조건만 — 중첩 없음
    # from_adhoc 가 아니면 지금 조건은 그대로 남는다(빌더가 새 조건을 들고 왔다).
    m.set_text("공고명", "사무")
    m.create_preset("상반기", FIRST_HALF)
    assert m.has_adhoc() and m.active_presets == ["소기업 청소", "상반기"]


def test_normalize_preset_state_takes_the_header_editors_strict_path() -> None:
    m = price_model()
    normalized = m.normalize_preset_state({
        "columns": {
            "공고명": {"values": ["청사 청소", "청사 청소", ""], "text": "  "},
            "추정가격": {"range": {"first": {"op": "lt", "operand": " 100,000,000원 "},
                                   "second": {"op": "ge", "operand": ""}, "joiner": "or"}},
        },
        "search": "  청  ",
        "pruned": ["추정가격", "없는 열"],
    })
    assert normalized == {
        "search": "청",
        "pruned": ["추정가격"],
        "columns": {
            "공고명": {"text": "", "values": ["청사 청소", ""], "range": None},
            "추정가격": {"text": "", "values": None, "range": {
                "first": {"op": "lt", "operand": "100,000,000원"}, "second": None, "joiner": "or",
            }},
        },
    }
    with pytest.raises(ValueError, match="이 필터의 열이 지금 데이터에 없습니다: 지역"):
        m.normalize_preset_state({"columns": {"지역": {"values": ["세종"]}}})
    with pytest.raises(ValueError, match="'1억' 을\\(를\\) 금액\\(으\\)로 읽을 수 없습니다"):
        m.normalize_preset_state({"columns": {"추정가격": {"range": {
            "first": {"op": "lt", "operand": "1억"}}}}})
    with pytest.raises(ValueError, match="'내일' 을\\(를\\) 날짜\\(으\\)로 읽을 수 없습니다"):
        m.normalize_preset_state({"columns": {"계약일자": {"range": {
            "first": {"op": "ge", "operand": "내일"}}}}})
    with pytest.raises(ValueError, match="범위 조건은 일자·금액 열 전용입니다"):
        m.normalize_preset_state({"columns": {"공고명": {"range": {
            "first": {"op": "ge", "operand": "1"}}}}})
    with pytest.raises(ValueError, match="저장할 조건이 없습니다"):
        m.normalize_preset_state({"columns": {"공고명": {"text": " "}}, "search": " "})
    assert m.normalize_preset_state({}, allow_empty=True)["columns"] == {}
    for broken in ("x", {"columns": ["추정가격"]}, {"columns": {"공고명": "청"}},
                   {"columns": {"공고명": {"values": "청"}}}, {"search": 3},
                   {"columns": {"추정가격": {"range": ["lt"]}}}, {"active_presets": ["a"]}):
        with pytest.raises(ValueError, match="이 필터의 저장 형식을 읽을 수 없습니다"):
            m.normalize_preset_state(broken)


def test_count_state_evaluates_the_candidate_alone() -> None:
    m = price_model()
    _save_small_and_medium(m)
    m.toggle_preset("소기업")
    m.set_text("공고명", "전산")  # 지금 조건·켜진 칩은 빌더의 수에 끼지 않는다
    assert m.count_state(MEDIUM, PRICE_ROWS) == 2
    assert m.count_state({"columns": {}}, PRICE_ROWS) == 5  # 빈 조건 = 전 행(저장이 거절)
    with pytest.raises(ValueError, match="금액"):
        m.count_state({"columns": {"추정가격": {"range": {
            "first": {"op": "lt", "operand": "1억"}}}}}, PRICE_ROWS)


def test_create_preset_refuses_loudly() -> None:
    m = price_model()
    with pytest.raises(ValueError, match="저장할 조건이 없습니다"):
        m.create_preset("빈 필터", {"columns": {}})
    with pytest.raises(ValueError, match="저장할 조건이 없습니다"):
        m.create_preset("   ", {"columns": {}})  # 빈 이름 + 빈 조건 — 지을 요약도 없다
    m.create_preset("전산", {"columns": {"공고명": {"text": "전산"}}})
    with pytest.raises(ValueError, match="같은 이름의 필터가 있습니다"):
        m.create_preset("전산", {"columns": {"공고명": {"text": "청"}}})  # 덮어쓰지 않는다
    assert m.presets[0]["state"]["columns"]["공고명"]["text"] == "전산"
    assert [p["name"] for p in m.presets] == ["전산"]  # 거절은 아무것도 남기지 않는다


def test_empty_name_takes_the_short_condition_summary() -> None:
    """이름을 비우고 저장하면 짧은 조건 요약이 이름이 된다 — 같은 이름 규칙 그대로, 전문은 title 이 든다."""
    m = price_model()
    assert m.name_state(SMALL) == "추정가격 < 100,000,000"
    assert m.name_state({"columns": {}}) == ""
    assert m.create_preset("  ", SMALL) == "추정가격 < 100,000,000"
    with pytest.raises(ValueError, match="같은 이름의 필터가 있습니다"):
        m.create_preset("", SMALL)
    # 「사이」(≥ a 그리고 < b)는 ``a~b`` 다 — 단위를 줄여 쓰지 않는다(피연산자는 쓴 그대로).
    assert m.update_preset("추정가격 < 100,000,000", "", MEDIUM) == "추정가격 100,000,000~220,000,000"
    # 전문은 칩 title(정의줄 조각과 같은 생산자)이 든다.
    assert m.preset_description("추정가격 100,000,000~220,000,000", PRICE_ROWS) == (
        "추정가격 ≥ '100,000,000' ∧ < '220,000,000'"
    )


def test_short_names_count_extra_values_and_keep_other_shapes() -> None:
    m = price_model()
    many = {"columns": {"공고명": {"values": ["청사 청소", "전산 유지보수", "", "방역 용역"]}}}
    assert m.name_state(many) == "공고명 청사 청소 외 3개"
    assert m.name_state({"columns": {"공고명": {"values": [""]}}}) == "공고명 (빈값)"
    assert m.name_state({"columns": {"공고명": {"text": "전산"}}, "search": "청"}) == (
        "공고명 포함 '전산' · 검색 '청'"
    )
    two = {"columns": {"계약일자": {"range": {
        "first": {"op": "ge", "operand": "2026-01-01"},
        "second": {"op": "le", "operand": "2026-06-30"}, "joiner": "and"}}}}
    assert m.name_state(two) == "계약일자 ≥ 2026-01-01 ∧ ≤ 2026-06-30"  # 「사이」 모양이 아니면 기호 그대로
    # 열 순서로 잇는다(빌더 카드 순서가 아니라 표의 열 순서).
    assert m.name_state({"columns": {
        "추정가격": SMALL["columns"]["추정가격"], "공고명": {"values": ["사무용품"]},
    }}) == "공고명 사무용품 · 추정가격 < 100,000,000"


def test_state_refusals_point_at_their_column() -> None:
    """거절은 가리키는 열을 싣는다 — 빌더가 그 카드 아래에 문장을 세운다(문장은 설치 규칙 그대로)."""
    m = price_model()
    with pytest.raises(PresetStateError) as caught:
        m.normalize_preset_state({"columns": {"추정가격": {"range": {"first": {"op": "lt", "operand": "1억"}}}}})
    assert caught.value.column == "추정가격" and "금액(으)로 읽을 수 없습니다" in str(caught.value)
    with pytest.raises(PresetStateError) as caught:
        m.normalize_preset_state({"columns": {"지역": {"values": ["세종"]}}})
    assert caught.value.column == "지역"
    with pytest.raises(PresetStateError) as caught:
        m.normalize_preset_state({"columns": {}})
    assert caught.value.column == ""


def test_update_preset_renames_and_rewrites_keeping_order_and_activation() -> None:
    m = price_model()
    _save_small_and_medium(m)
    m.toggle_preset("중소기업")
    assert m.update_preset("중소기업", "중소", MEDIUM) == "중소"
    assert [p["name"] for p in m.presets] == ["소기업", "중소"]  # 칩 순서 유지
    assert m.active_presets == ["중소"]  # 켜짐도 잇는다
    with pytest.raises(ValueError, match="같은 이름의 필터가 있습니다"):
        m.update_preset("중소", "소기업", MEDIUM)
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        m.update_preset("없음", "없음", MEDIUM)
    # 조건을 바꾸면 차원도 바뀐다 — 칩이 다른 무리로 옮기고 평가도 새 정의를 쓴다.
    assert m.update_preset("중소", "중소", FIRST_HALF) == "중소"
    assert m.preset_dimension("중소") == frozenset({"계약일자"})
    assert m.visible_indices(PRICE_ROWS) == [0, 2, 4]
    m.delete_preset("중소")  # 켜져 있던 칩을 지우면 함께 꺼진다
    assert m.active_presets == [] and m.visible_indices(PRICE_ROWS) == [0, 1, 2, 3, 4]
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        m.toggle_preset("중소")


def test_preset_on_missing_column_is_refused_with_reason() -> None:
    """지금 데이터에 없는 열을 가리키는 저장본은 켤 수 없다 — 조용히 무시하지 않는다."""
    m = price_model()
    _save_small_and_medium(m)
    other = FilterModel(["공고명", "금액"], {"공고명": KIND_TEXT, "금액": KIND_AMOUNT})
    assert other.set_presets(m.presets) == []
    usable, reason = other.preset_status("소기업")
    assert usable is False and reason == "이 필터의 열이 지금 데이터에 없습니다: 추정가격"
    with pytest.raises(ValueError, match="열이 지금 데이터에 없습니다"):
        other.activate_preset("소기업")
    assert other.active_presets == []
    # 쓸 수 없는 저장본도 자기 차원(정의 유래)에 선다 — 칩 줄의 무리는 그대로다.
    assert other.preset_groups() == [["소기업", "중소기업"]]
    assert other.dimension_label("소기업") == "추정가격"
    # 열은 있으나 유형이 바뀌어 범위가 서지 않는 경우도 부분 설치 없이 막는다.
    texty = FilterModel(["공고명", "추정가격"], {"공고명": KIND_TEXT, "추정가격": KIND_TEXT})
    texty.set_presets(m.presets)
    assert texty.preset_status("중소기업") == (
        False, "이 필터의 범위 조건을 지금 데이터 열에 적용할 수 없습니다: 추정가격",
    )


def test_set_presets_reseeds_and_reports_deactivated() -> None:
    m = price_model()
    _save_small_and_medium(m)
    m.toggle_preset("소기업")
    m.toggle_preset("중소기업")
    kept = [p for p in m.presets if p["name"] == "중소기업"]
    assert m.set_presets(kept) == ["소기업"]  # 사라진 정의의 켜짐은 꺼지고 이름이 돌아온다
    assert m.active_presets == ["중소기업"]
    renamed = [{"name": "중소", "state": kept[0]["state"]}]
    assert m.set_presets(renamed, renamed={"중소기업": "중소"}) == []
    assert m.active_presets == ["중소"]
    with pytest.raises(ValueError, match="같은 이름의 필터가 있습니다"):
        m.set_presets(renamed + [{"name": " 중소 ", "state": {}}])
    broken = FilterModel(list(PRICE_ROWS[0]))
    broken.set_presets([
        {"name": "망가짐", "state": {"columns": ["추정가격"]}},
        {"name": "망가짐2", "state": {"columns": ["추정가격"]}},
    ])
    assert broken.preset_status("망가짐") == (False, "이 필터의 저장 형식을 읽을 수 없습니다.")
    # 손상된 저장본은 차원이 없어 저마다 홀로 선다(빈 이름의 무리로 뭉치지 않는다).
    assert broken.preset_dimension("망가짐") == frozenset()
    assert broken.preset_groups() == [["망가짐"], ["망가짐2"]]


def test_export_apply_carry_active_preset_names_only() -> None:
    """세션 이송은 켜진 **이름**만 — 정의는 등록 데이터가 든다. 복제는 정의까지 무손실."""
    m = price_model()
    _save_small_and_medium(m)
    m.toggle_preset("중소기업")
    m.toggle_preset("소기업")
    m.set_text("공고명", "방역")
    state = m.export_state()
    assert state["active_presets"] == ["중소기업", "소기업"]
    assert "presets" not in state
    twin = m.clone()
    assert twin.export_state() == state and twin.presets == m.presets
    assert twin.visible_indices(PRICE_ROWS) == [4]
    assert twin.describe(PRICE_ROWS) == "필터 '중소기업' 또는 '소기업' · 공고명 포함 '방역'"
    bare = FilterModel(list(PRICE_ROWS[0]), sniff_column_kinds(PRICE_ROWS))
    installed, dropped = bare.apply_state(state)  # 정의 없는 모델엔 이름이 탈락으로 돌아온다
    assert installed == ["공고명"] and dropped == ["필터 '중소기업'", "필터 '소기업'"]
    blank = m.blank_copy()
    assert not blank.is_active() and blank.presets == m.presets
    installed, dropped = blank.apply_state(state)
    assert installed == ["공고명", "필터 '중소기업'", "필터 '소기업'"] and dropped == []
    m.clear()  # 「모두 보기」는 켜진 칩도 끈다(정의는 남는다)
    assert not m.is_active() and len(m.presets) == 2


def test_range_condition_from_payload_shapes_both_editors() -> None:
    assert range_condition_from_payload(None) is None
    assert range_condition_from_payload({"op": "lt", "operand": "  "}) is None
    cond = range_condition_from_payload(
        {"op": "ge", "operand": " 1 "}, {"op": "lt", "operand": ""}, "or",
    )
    assert cond == RangeCondition(RangeClause("ge", "1"), None, "or")
    with pytest.raises(ValueError, match="저장 형식"):
        range_condition_from_payload("ge")
