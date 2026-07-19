"""자모 분해 부분일치 회귀 — 결정 23 · 부록 B-6·B-7 의 링1 유틸.

사양 정본 = ``docs/r-flow-mockups/block4-filter-crystallize-demo.html`` 의
``jamoMap``/``jamoFind``. 자모 테이블은 그 시안 HTML 에서 **그대로 회수**해 파이썬
상수와 대조한다(식별 요약의 naraData 회수 관례 동형 — "충실 이식" 주장을 기계 비준).
행동 케이스는 시안 걷기(「행복도ㅅ」 단계 매치)와 결정 23 문언(겹받침 성분 확장·음절
역매핑 하이라이트)에서 왔다.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

import pytest

from hwpxfiller.core.jamo import (
    CHOSEONG,
    JONGSEONG,
    JUNGSEONG,
    decompose,
    jamo_contains,
    jamo_find,
)

MOCKUP = (
    Path(__file__).resolve().parent.parent
    / "docs" / "r-flow-mockups" / "block4-filter-crystallize-demo.html"
)


# ---------------------------------------------------------------- 시안 패리티
@functools.cache
def _mockup_text() -> str:
    """시안 HTML 1회 읽기 캐시 — 파라미터 케이스마다 재읽지 않는다(고효율 리뷰 #2)."""
    return MOCKUP.read_text(encoding="utf-8")


def _mockup_table(name: str) -> "tuple[str, ...]":
    """시안 JS 의 ``var CHO=[...]`` 테이블을 원문에서 회수한다(줄바꿈 허용)."""
    m = re.search(rf"var {name}=\[(.*?)\];", _mockup_text(), re.DOTALL)
    assert m, f"시안에서 {name} 테이블을 찾지 못했습니다(사양 정본 이동?)"
    return tuple(re.findall(r'"([^"]*)"', m.group(1)))


@pytest.mark.parametrize(
    ("name", "ours"),
    [("CHO", CHOSEONG), ("JUNG", JUNGSEONG), ("JONG", JONGSEONG)],
)
def test_tables_match_mockup_spec(name: str, ours: "tuple[str, ...]") -> None:
    """자모 테이블 = 시안 테이블(충실 이식의 기계 비준 — 겹받침 확장 포함)."""
    assert ours == _mockup_table(name)


def test_table_shapes() -> None:
    """산술 분해 전제 — 초 19 · 중 21 · 종 28(= 588/28/1 나눗셈의 성립 조건)."""
    assert len(CHOSEONG) == 19
    assert len(JUNGSEONG) == 21
    assert len(JONGSEONG) == 28
    assert JONGSEONG[0] == ""  # 받침 없음


# ---------------------------------------------------------- 분해(산술·확장·통과)
def test_decompose_syllable_arithmetic() -> None:
    assert decompose("가") == "ㄱㅏ"
    assert decompose("행") == "ㅎㅐㅇ"
    assert decompose("힣") == "ㅎㅣㅎ"


def test_decompose_compound_jongseong_expands() -> None:
    """겹받침 성분 확장(결정 23) — ㄺ→ㄹㄱ, ㄳ→ㄱㅅ."""
    assert decompose("닭") == "ㄷㅏㄹㄱ"
    assert decompose("몫") == "ㅁㅗㄱㅅ"
    assert decompose("앉") == "ㅇㅏㄴㅈ"


def test_decompose_passthrough_non_syllable() -> None:
    """비음절(숫자·라틴·낱자모·기호)은 1:1 통과 — 낱자 질의가 같은 평면에서 만난다."""
    assert decompose("제2026-15호") == "ㅈㅔ2026-15ㅎㅗ"
    assert decompose("ㅅ") == "ㅅ"
    assert decompose("abc") == "abc"
    assert decompose("") == ""


# ------------------------------------------------- 부분일치(조립 중간 상태 매치)
def test_ime_intermediate_query_matches() -> None:
    """정본 걷기 — 「행복도시」를 치는 도중 「행복도ㅅ」 단계에서 이미 맞는다."""
    assert jamo_contains("행복도시", "행복도ㅅ")
    assert jamo_contains("행복도시", "행복도시")
    assert jamo_contains("세종특별자치시 행복도시", "행복도ㅅ")


def test_compound_jongseong_intermediate() -> None:
    """「닭」을 겨눠 「달」까지 친 상태(ㄷㅏㄹ ⊂ ㄷㅏㄹㄱ)가 이미 맞는다."""
    assert jamo_contains("닭고기", "달")
    assert jamo_contains("닭고기", "닭")
    assert not jamo_contains("닭고기", "담")  # ㅁ 은 ㄹㄱ 어디에도 없다


def test_partial_syllable_prefix_matches() -> None:
    """음절 내부 접두 — 「각」을 겨눠 「가」까지 친 상태."""
    assert jamo_contains("각하", "가")
    assert not jamo_contains("강남", "간")  # ㄱㅏㄴ ⊄ ㄱㅏㅇㄴㅏㅁ(경계 안 넘어감)


def test_cross_syllable_match() -> None:
    assert jamo_contains("행복도시", "복도")
    assert jamo_contains("정문", "정ㅁ")  # 다음 음절 초성을 조립 중


def test_non_hangul_passthrough_match() -> None:
    assert jamo_contains("제2026-15호", "2026")
    assert jamo_contains("제2026-15호", "제2026")
    assert not jamo_contains("제2026-15호", "2027")


def test_case_sensitive_boundary() -> None:
    """비한글은 원문 그대로 비교(시안 동형) — 경계의 명문."""
    assert jamo_contains("ABC상사", "ABC")
    assert not jamo_contains("ABC상사", "abc")


def test_choseong_search_not_supported() -> None:
    """초성 나열(ㅎㅂㄷ)은 연속 부분열이 아니다 — 결정 23 은 부분일치이지 초성검색 아님."""
    assert not jamo_contains("행복도시", "ㅎㅂㄷ")


def test_empty_query_is_no_match() -> None:
    """빈 질의 = 매치 아님(시안 동형) — '조건 없음' 해석은 필터 모델 소관."""
    assert jamo_find("행복도시", "") is None
    assert not jamo_contains("행복도시", "")
    assert jamo_find("", "가") is None
    assert jamo_find("", "") is None


# ------------------------------------------------- 역매핑(하이라이트 원문 범위)
def test_find_returns_original_char_range() -> None:
    """매치 구간은 원문 문자 범위 [start, end) — 하이라이트가 그대로 자른다."""
    assert jamo_find("세종특별자치시", "자치") == (4, 6)
    assert jamo_find("행복도시", "복도") == (1, 3)
    assert jamo_find("제2026-15호", "2026") == (1, 5)


def test_find_partial_syllable_covers_whole_char() -> None:
    """음절 중간에서 끝난 매치는 그 음절을 통째로 포함(반쪽 하이라이트 없음)."""
    assert jamo_find("행복도시", "행복도ㅅ") == (0, 4)  # 「시」 전체 포함
    assert jamo_find("닭고기", "달") == (0, 1)  # 「닭」 내부에서 끝남


def test_find_first_match_only() -> None:
    """첫 매치 하나만(시안 indexOf 동형) — 다중 하이라이트는 소비처 반복 호출 소관."""
    assert jamo_find("도시도시", "도시") == (0, 2)


def test_highlight_slice_roundtrip() -> None:
    """범위로 원문을 실제로 잘라도 성립한다(소비처가 할 그 일)."""
    hay = "세종특별자치시 이전"
    start, end = jamo_find(hay, "자치")
    assert hay[start:end] == "자치"


def test_index_unit_is_python_codepoint_not_utf16() -> None:
    """인덱스 단위 = 파이썬 코드포인트(선언된 시안 편차, 고효율 리뷰 #1).

    비-BMP 문자(이모지)가 매치 앞에 오면 시안 JS(UTF-16)와 인덱스가 갈라진다 —
    시안이라면 [4, 6). 그래서 계약은 '파이썬 슬라이싱 전용'이고 하이라이트는 Python
    이 잘라 세그먼트로 싣는다(인덱스를 웹으로 건네지 않는다). 이 테스트는 그 단위
    선언 자체를 못박는다 — 파이썬 슬라이싱으로는 정확해야 한다.
    """
    hay = "\U0001f4cb 행복도시"  # 이모지(비-BMP) + 공백 + 본문
    rng = jamo_find(hay, "복도")
    assert rng == (3, 5)  # 코드포인트 인덱스(UTF-16 이라면 (4, 6))
    assert hay[rng[0]:rng[1]] == "복도"  # 파이썬 슬라이싱은 정확
