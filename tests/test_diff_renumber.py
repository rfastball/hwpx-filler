"""재번호(renumber) 정렬 인수 테스트 — 실제 개정본 spec_revision_2025 → 2026.

결함: 조항 하나가 삽입/삭제돼 뒤 번호가 통째로 밀리면(3.2.8 Tripod → 3.2.7 Tripod)
예전엔 **원문 전체**로 정렬해 equal 로 안 잡히고 replace 로 흘러, 위치 1:1 로 엉뚱한
조항끼리 짝지었다(3.2.8 Tripod ↔ 3.2.9 유압계통). 그래서 거짓 changed 와 거짓 숫자변경
(8→9)이 캐스케이드로 쏟아지고 진짜 변경을 파묻었다.

수정(정렬 계층): ① 정렬 키에서 선두 서수를 벗겨 본문으로 맞춘다 → 본문이 같은 재번호는
equal 로 붙어 renumber 로만 표면화. ② replace 구간은 위치가 아니라 정규화 본문 유사도로
짝지어, 삽입으로 밀린 뒤 조항이 엉뚱하게 짝지지 않게 한다(신설은 added, 재작성은 changed).

기준 수치(수동 확인, 이 코퍼스 한정):
  · 수정 전: change_items 155, number 50 (이 중 ~11 건이 서수 N→N+1 거짓 변경).
  · 수정 후: change_items 162, number 38, renumber 7.
    number 카테고리 50→38 로 거짓 서수 변경이 사라졌고 엉뚱한 조항 짝이 없어졌다.
    총계가 오른 것은 오짝됐던 changed 하나가 올바른 added+removed 로 분리됐기 때문
    (개수보다 '정확도'가 오른 것 — 재번호는 별도 카테고리로 데모트).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.diff import _norm_key, diff_files

CORPUS = Path(__file__).parent / "corpus" / "real"
OLD = str(CORPUS / "spec_revision_2025.hwpx")
NEW = str(CORPUS / "spec_revision_2026.hwpx")

# 실제 개정에서 서수만 밀린 Tripod 조항(본문 동일)과, 같은 자리에 원래 거짓 짝지어졌던 신설 조항.
TRIPOD_OLD = "3.2.8 Tripod 형식이며 잭킹 포인트가 있어야 한다."
TRIPOD_NEW = "3.2.7 Tripod 형식이며 잭킹 포인트가 있어야 한다."
HYDRAULIC_FRAGMENT = "유압계통이 고장나도"  # 2026 신설 조항(3.2.9)


@pytest.fixture(scope="module")
def result():
    return diff_files(OLD, NEW)


def test_tripod_is_renumber_not_bogus_pairing(result):
    """Tripod 조항은 renumber 로 잡히고, 신설 유압계통 조항과 절대 짝지어지지 않는다."""
    tripod = [c for c in result.changes if c.old_text == TRIPOD_OLD]
    assert len(tripod) == 1, "Tripod 조항 변경이 정확히 하나여야 한다"
    c = tripod[0]
    # 재번호로 분류(문구변경/숫자변경 아님), 본문은 동일하고 서수만 다름.
    assert c.kind == "renumber"
    assert c.new_text == TRIPOD_NEW
    assert _norm_key(c.old_text) == _norm_key(c.new_text)

    # 핵심: Tripod(old) 가 유압계통(new) 과 짝지어진 어떤 변경도 없어야 한다.
    for ch in result.changes:
        assert not (TRIPOD_OLD in ch.old_text
                    and HYDRAULIC_FRAGMENT in ch.new_text), \
            "Tripod 조항이 유압계통 신설 조항과 거짓 짝지어졌다(캐스케이드 회귀)"

    # change_items 에서도 Tripod 는 renumber 카테고리로만 나타난다.
    tripod_items = [it for it in result.change_items if it.old == TRIPOD_OLD]
    assert tripod_items and all(it.category == "renumber" for it in tripod_items)


def test_inserted_hydraulic_clause_is_added(result):
    """신설된 유압계통 안전장치 조항은 changed 가 아니라 added(신설)로 잡힌다."""
    hits = [c for c in result.changes if HYDRAULIC_FRAGMENT in c.new_text]
    assert hits, "유압계통 신설 조항을 찾지 못했다"
    assert all(c.kind == "added" for c in hits)
    assert all(c.old_text == "" for c in hits)


def test_genuine_180_to_300_still_number_change(result):
    """진짜 실질 변경(납기 180일 → 300일)은 그대로 number 항목으로 살아있다."""
    nums = [it for it in result.change_items if it.category == "number"]
    hit = [it for it in nums if "180일" in it.detail and "300일" in it.detail]
    assert hit, "180일 → 300일 숫자 변경이 사라졌다"


def test_table_rate_changes_survive(result):
    """표 셀 값 변경(1,500 → 1,600)도 number 로 유지된다(재번호 수정이 표를 건드리지 않음)."""
    nums = [it for it in result.change_items if it.category == "number"]
    assert any("1,500" in it.detail and "1,600" in it.detail for it in nums)


def test_renumber_cascade_collapsed_and_noise_dropped(result):
    """캐스케이드 붕괴의 정량 확인 — renumber 표면화 + 거짓 서수 숫자변경 제거."""
    cats = [it.category for it in result.change_items]
    renumber = cats.count("renumber")
    numbers = cats.count("number")

    # 본문 동일·서수만 바뀐 재번호가 별도 카테고리로 여러 건 표면화(수정 전엔 0).
    assert renumber >= 5, f"재번호 항목이 너무 적다: {renumber}"
    assert renumber == result.summary["renumber"]

    # 거짓 서수 N→N+1 변경이 사라져 number 카테고리가 크게 줄었다(수정 전 50).
    assert numbers <= 42, f"number 항목이 여전히 많다(거짓 서수 잔존?): {numbers}"

    # 모든 renumber 항목은 실제로 본문 동일·서수만 다른, 정당한 재번호다.
    for c in result.changes:
        if c.kind == "renumber":
            assert _norm_key(c.old_text) == _norm_key(c.new_text)
            assert c.old_text != c.new_text
