"""식별 요약 휴리스틱 v2 회귀 — 결정 37 · 부록 B-4 의 4장면 정본.

케이스 정본 = ``docs/r-flow-mockups/block6-d1-d2-compare-demo.html`` 부록 4장면(시연
JS ``iPick`` 라이브 계산). 이 테스트는 그 4장면을 링1 :func:`identity_summary` 로 이식해
**결과 일치**를 못박는다:

1. 나라장터 실수확 12행×53열 — 잉여 ID·차수·상수 무리를 뚫고 공고번호·공고명 도달.
2. 합성 함정(연번·상수·저구별·품명 중복) — 자격 문턱 없이 품명이 살아남는가(v1 반증).
3. 토큰 모드 — 파일명이 품명을 나르면 인지층 생략, 구별층만.
4. 진성 중복 백스톱 — 데이터가 정말 같은 두 행은 요약이 못 가른다(그래도 됨).

장면 1의 나라 12행은 시연 HTML 임베드(``id="naraData"``)에서 그대로 회수해 라이브 JS
계산과 같은 입력을 보장한다. 나머지 3장면 데이터는 시연 스크립트의 생성자와 동형이다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwpxfiller.core.identity_summary import (
    COGNITION_WIDTH,
    MAX_COLUMNS,
    DisqualifierStats,
    IdentitySummary,
    identity_summary,
)

_MOCKUP = (
    Path(__file__).resolve().parents[1]
    / "docs" / "r-flow-mockups" / "block6-d1-d2-compare-demo.html"
)


def _load_nara_rows() -> list[dict]:
    """시연 HTML 의 ``<script id="naraData">`` 에서 정본 12행을 회수(라이브 JS 와 동일 입력)."""
    html = _MOCKUP.read_text(encoding="utf-8")
    anchor = html.index('id="naraData"')
    body_open = html.index(">", anchor) + 1
    body_close = html.index("</script>", body_open)
    rows = json.loads(html[body_open:body_close])
    assert len(rows) == 12 and len(rows[0]) == 53  # 12행×53열 — 정본 형상 못박기
    return rows


def _synth_rows() -> list[dict]:
    """장면 2·3 합성 함정 — 연번(순번)·부서(상수)·담당자/품명(저구별 반복)·금액(유일)."""
    dam = ["김OO", "김OO", "이OO", "이OO"]
    pum = ["사무용 소모품 일괄", "OO의약품 외 2행", "사무용 소모품 일괄", "실험기자재"]
    gyu = ["A형", "-", "B형", "C형"]
    return [
        {
            "연번": str(i + 1),
            "부서": "재무과",
            "담당자": dam[i % 4],
            "품명": pum[i % 4],
            "규격": gyu[i % 4],
            "기초금액": str(10000000 + i * 137),
        }
        for i in range(8)
    ]


_SYNTH_COLS = ["연번", "부서", "담당자", "품명", "규격", "기초금액"]

_DUP_ROWS = [
    {"품명": "A4 복사용지", "규격": "80g", "수량": "100"},
    {"품명": "A4 복사용지", "규격": "80g", "수량": "100"},  # 1행과 전 열 동일(진성 중복)
    {"품명": "프린터 토너", "규격": "HP정품", "수량": "2"},
    {"품명": "무선 마우스", "규격": "2.4GHz", "수량": "10"},
]


# ─────────────────────────────────────────────────────── 4장면 회귀(정본)

def test_scene1_nara_53col_reaches_notice_number_and_name() -> None:
    """장면 1 — 53열 잉여 ID·상수 무리를 뚫고 인지층이 공고번호·공고명에 도달.

    ``bidNtceOrd``/``refNtceOrd``(상수 "000") 건너뜀 · ``refNtceNo``(공고번호와 12행
    전부 동일)는 **중복 열** 결격 · 공고명 중복(Adobe 2건)은 공고번호가 가른다 → 잔여 0.
    """
    rows = _load_nara_rows()
    res = identity_summary(rows, list(rows[0].keys()))

    assert res.columns == ("bidNtceNo", "bidNtceNm")  # 인지층 2 고정
    assert res.token_mode is False
    assert res.residual_collisions == 0  # 공고번호가 유일 키 → 충돌 소멸
    assert res.disqualified.duplicate == ("refNtceNo",)  # 공고번호 중복 열
    assert res.disqualified.empty == 6
    assert res.disqualified.constant == 10
    assert res.summary_for(rows[0]) == (
        "R26BK01621756 · Adobe Creative Cloud 라이선스 연간사용권 구매"
    )


def test_scene2_synthetic_trap_keeps_pumyeong_without_threshold() -> None:
    """장면 2 — 자격 문턱 폐기의 실증: v1 이 잃던 품명이 v2 에선 인지층으로 산다.

    연번=순번 결격 · 부서=상수 결격 → 인지층 = 담당자·품명(왼쪽 첫 두 비결격).
    담당자×품명만으론 8행 전부 충돌(2벌 반복) → 구별층이 유일값 기초금액 1열로 해소.
    """
    rows = _synth_rows()
    res = identity_summary(rows, _SYNTH_COLS)

    assert res.columns == ("담당자", "품명", "기초금액")  # 인지 2 + 구별 1 = 상한 3
    assert res.token_mode is False
    assert res.residual_collisions == 0
    assert res.disqualified.ordinal == ("연번",)
    assert res.disqualified.constant == 1  # 부서
    assert res.summary_for(rows[0]) == "김OO · 사무용 소모품 일괄 · 10000000"
    # 체인 흔적: 인지층 2 + 구별층 1
    assert [s.layer for s in res.steps] == ["cognition", "cognition", "discrimination"]


def test_scene3_token_mode_skips_cognition() -> None:
    """장면 3 — 파일명이 품명을 나르면(``filename_tokens=["품명"]``) 인지층 생략.

    요약은 순수 구분자 → 조건부 이득 최대인 기초금액 1열만. 쌍(파일명·요약)이 재인과
    구별을 나눠 진다.
    """
    rows = _synth_rows()
    res = identity_summary(rows, _SYNTH_COLS, filename_tokens=["품명"])

    assert res.token_mode is True
    assert res.columns == ("기초금액",)  # 인지층 없음, 구별층만
    assert res.residual_collisions == 0
    assert res.summary_for(rows[0]) == "10000000"
    assert res.steps[0].layer == "token-mode"  # 인지층 생략 흔적
    assert "품명" not in res.columns  # 파일명 토큰은 요약에서 배제


def test_scene4_true_duplicate_backstop_stops_quietly() -> None:
    """장면 4 — 진성 중복(1·2행 전 열 동일)은 요약이 못 가르고, 그래도 됨.

    인지층 품명·규격까지 붙여도 1·2행 충돌 잔존 → 수량을 더해도 이득 0 → **조용히 정지**.
    잔여 충돌 2행은 파일명 접미사(-001/-002)가 최후 담보(완화 조항 자리 — 시끄럽지 않다).
    """
    rows = _DUP_ROWS
    res = identity_summary(rows, ["품명", "규격", "수량"])

    assert res.columns == ("품명", "규격")  # 이득 0 열(수량)은 안 붙는다
    assert res.residual_collisions == 2  # 1·2행 잔존 충돌 — 정직 표기
    assert res.token_mode is False
    assert res.steps[-1].layer == "stop"  # 조용한 정지 흔적
    # 1·2행은 요약이 겹치고(정직), 3·4행은 고유 — Counter 1회 구성 일괄 판정(리뷰 #5)
    assert res.collision_flags(rows) == (True, True, False, False)


# ─────────────────────────────────────────────────────── 결격 5종 단위

def test_empty_column_disqualified() -> None:
    rows = [{"a": "x", "b": ""}, {"a": "y", "b": "  "}]
    res = identity_summary(rows, ["a", "b"])
    assert res.columns == ("a",)
    assert res.disqualified.empty == 1


def test_constant_column_disqualified() -> None:
    rows = [{"a": "1", "k": "same"}, {"a": "2", "k": "same"}]
    res = identity_summary(rows, ["k", "a"])
    assert "k" not in res.columns
    assert res.disqualified.constant == 1


def test_ordinal_column_disqualified() -> None:
    """값이 행 서수(1..N)와 일치하는 순번 열은 결격(연번·행번호)."""
    rows = [{"seq": str(i + 1), "name": f"n{i % 2}"} for i in range(4)]
    res = identity_summary(rows, ["seq", "name"])
    assert "seq" not in res.columns
    assert res.disqualified.ordinal == ("seq",)


def test_non_unit_increment_is_not_ordinal() -> None:
    """1씩 증가가 아니면 순번 아님 — 정상 후보로 산다(수량 100,100,2,10 등)."""
    rows = [{"q": "100"}, {"q": "100"}, {"q": "2"}, {"q": "10"}]
    res = identity_summary(rows, ["q"])
    assert res.disqualified.ordinal == ()  # 순번 아님


def test_duplicate_column_disqualified_against_chosen() -> None:
    """이미 고른 열과 행별 값이 전부 같은 열은 중복 결격(직교성 0)."""
    rows = [{"id": "A", "copy": "A", "x": "1"}, {"id": "B", "copy": "B", "x": "1"}]
    res = identity_summary(rows, ["id", "copy", "x"])
    assert res.columns[0] == "id"
    assert "copy" not in res.columns  # id 의 복사본
    assert res.disqualified.duplicate == ("copy",)


def test_filename_token_column_excluded() -> None:
    rows = [{"품명": "볼펜", "가격": "500"}, {"품명": "연필", "가격": "300"}]
    res = identity_summary(rows, ["품명", "가격"], filename_tokens=["품명"])
    assert res.token_mode is True
    assert "품명" not in res.columns


# ─────────────────────────────────────────────────────── API 경계·계약

def test_layer_caps_are_two_and_three() -> None:
    assert COGNITION_WIDTH == 2
    assert MAX_COLUMNS == 3


def test_columns_default_to_first_row_keys() -> None:
    rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    res = identity_summary(rows)  # columns 생략
    assert res.columns == ("a", "b")


def test_empty_rows_yield_empty_summary() -> None:
    res = identity_summary([], ["a"])
    assert res == IdentitySummary((), 0, False, (), DisqualifierStats())
    assert res.summary_for({"a": "x"}) == ""


def test_all_disqualified_yields_no_columns() -> None:
    """모든 열이 결격이면 요약 없이 파일명만(빈 columns)."""
    rows = [{"c": "same", "s": "1"}, {"c": "same", "s": "2"}]
    res = identity_summary(rows, ["c", "s"])  # c=상수, s=순번
    assert res.columns == ()
    assert res.residual_collisions == len(rows)  # 요약이 아무도 못 가름
    assert res.summary_for(rows[0]) == ""


def test_summary_for_joins_normalized_values_without_skipping_blanks() -> None:
    """고른 열의 개별 셀이 비어도 건너뛰지 않고 이어붙인다(시연 iOut 동형)."""
    rows = [{"a": "x", "b": "9"}, {"a": "", "b": "4"}]  # b 는 비순번(9→4)
    res = identity_summary(rows, ["a", "b"])
    assert res.columns == ("a", "b")  # a 는 전열 빈칸 아님 → 후보
    assert res.summary_for(rows[1]) == " · 4"  # 빈 셀도 자리 유지


def test_cognition_cap_leaves_room_for_one_discrimination() -> None:
    """인지층 2 + 구별층은 상한 3까지 — 4열째는 붙지 않는다."""
    # 4열 모두 저구별이라 3열까지 붙어도 잔여가 남게 구성
    rows = [
        {"a": "p", "b": "q", "c": "r", "d": "s"},
        {"a": "p", "b": "q", "c": "r", "d": "s"},
        {"a": "p", "b": "q", "c": "r", "d": "s"},
    ]
    res = identity_summary(rows, ["a", "b", "c", "d"])
    # a,b,c,d 전부 상수 → 결격 → 빈 요약(상한 회로가 무한루프 안 도는지 확인)
    assert len(res.columns) <= MAX_COLUMNS


@pytest.mark.parametrize("val,expected", [(None, ""), (123, "123"), ("  x  ", "x")])
def test_normalization_matches_js_inorm(val: object, expected: str) -> None:
    """정규화가 시연 inorm 과 동형(None→빈, 숫자→문자열, 좌우 공백 제거)."""
    rows = [{"k": val}, {"k": "other"}]
    res = identity_summary(rows, ["k"])
    assert res.summary_for(rows[0]) == expected


# ─────────────────────────────────────── 리뷰 회귀(PR #91 — 발견 1~4)

def test_review1_collision_key_separator_prevents_phantom_collisions() -> None:
    """리뷰 #1 — 값 연쇄 모호성: '1'+'23' 과 '12'+'3' 은 충돌이 아니다.

    구분자 없는 키잉(시연 iColl 의 join(""))은 둘 다 '123' 으로 키잉해 유령 충돌을
    만들고(잔여 과대·불필요 열 첨부), 표시(' · ')와 판정이 갈라진다. 모호성 없는
    구분자 키잉으로 잔여 0 이어야 한다.
    """
    rows = [{"a": "1", "b": "23"}, {"a": "12", "b": "3"}]
    res = identity_summary(rows, ["a", "b"])
    assert res.columns == ("a", "b")
    assert res.residual_collisions == 0  # 종전엔 키 '123' 동일로 유령 충돌 2
    assert res.collision_flags(rows) == (False, False)
    assert res.steps[-1].layer != "stop"  # 유령 잔여로 인한 정지 흔적 없음


def test_review2_auto_increment_id_survives_as_identifier() -> None:
    """리뷰 #2 — 순번 결격은 '값=행 서수'만(결정 37 문언): 1001 시작 자동증가 ID 는
    유일 식별자로 산다. 종전엔 임의 +1 등차를 전부 기각해 유일 구별 열을 조용히 잃었다."""
    rows = [{"공고번호": str(1001 + i), "부서": "총무과"} for i in range(3)]
    res = identity_summary(rows, ["공고번호", "부서"])
    assert res.columns == ("공고번호",)  # 종전: () — 식별 불능
    assert res.residual_collisions == 0
    assert res.disqualified.ordinal == ()
    assert res.disqualified.constant == 1  # 부서


def test_review2_zero_based_row_ordinal_still_disqualified() -> None:
    """행 서수는 0 기점(0..N-1)도 순번이다 — 결격 유지."""
    rows = [{"idx": str(i), "name": f"n{i % 2}"} for i in range(4)]
    res = identity_summary(rows, ["idx", "name"])
    assert "idx" not in res.columns
    assert res.disqualified.ordinal == ("idx",)


def test_review3_token_mode_zero_gain_appends_nothing() -> None:
    """리뷰 #3 — 토큰 모드 첫 픽도 이득 0이면 조용히 정지.

    적격 열(등급)이 있어도 어떤 충돌 행도 못 가르면(4→4) 덧붙이지 않는다 — 비구별
    열을 구별자인 양 제시 금지. 재인·구별은 파일명(품명 토큰+접미사)이 담보.
    """
    rows = [
        {"품명": "P1", "등급": "상"},
        {"품명": "P2", "등급": "상"},
        {"품명": "P3", "등급": "하"},
        {"품명": "P4", "등급": "하"},
    ]
    res = identity_summary(rows, ["품명", "등급"], filename_tokens=["품명"])
    assert res.token_mode is True
    assert res.columns == ()  # 종전: ('등급',) — 여전히 전행 충돌인데 첨부
    assert res.steps[-1].layer == "stop"
    assert res.residual_collisions == 4


def test_review4_single_row_residual_is_zero() -> None:
    """리뷰 #4 — 1행 집합: 충돌 상대가 없으니 잔여 0(종전 len(rows)=1 과대집계)."""
    rows = [{"품명": "볼펜", "수량": "10"}]
    res = identity_summary(rows, ["품명", "수량"])
    assert res.columns == ()  # 1행 → 전 열 상수 결격
    assert res.residual_collisions == 0
    assert res.collision_flags(rows) == (False,)
