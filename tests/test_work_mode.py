"""시스템 작업 방식의 표시 어휘(링1) — 계약 §19.1 표의 단일 출처 경계.

정본: lab `docs/core-workflow.md` §19.1 · 지도 §10.15 판정 A.
"""

import pytest

from hwpxfiller.core.job import (
    WORK_MODE_HWPX,
    WORK_MODE_TEXT,
    WORK_MODE_UNSUPPORTED,
)
from hwpxfiller.gui.work_mode import (
    WORK_MODE_ORDER,
    last_use_label,
    mode_sections,
    work_mode_label,
    work_mode_of_filter_value,
)


@pytest.mark.parametrize(
    ("mode", "short", "full"),
    [
        (WORK_MODE_HWPX, "HWPX 생성", "HWPX 문서 생성"),
        (WORK_MODE_TEXT, "온나라 기안", "온나라 기안 검토·복사"),
        (WORK_MODE_UNSUPPORTED, "작업 방식 확인", "지원 작업 방식 확인 필요"),
    ],
)
def test_labels_match_the_contract_table(mode, short, full):
    """§19.1 표 그대로 — 표면이 문구를 다시 짓지 않게 여기가 정본이다."""
    assert work_mode_label(mode, short=True) == short
    assert work_mode_label(mode) == full


def test_unknown_mode_falls_back_to_unsupported_not_to_hwpx():
    """폴백은 관용이 아니라 fail-closed — 배선을 빠뜨리면 「확인 필요」로 보인다."""
    assert work_mode_label("새로운방식") == work_mode_label(WORK_MODE_UNSUPPORTED)
    assert work_mode_label("", short=True) == work_mode_label(
        WORK_MODE_UNSUPPORTED, short=True
    )


def test_filter_value_translation_keeps_the_library_attribution():
    """필터 어휘 → 방식 어휘는 **번역**이지 재판정이 아니다(지도 §10.15 판정 A).

    라이브러리 필터가 미연결을 hwpx 칸에 놓기로 했으면 그 행의 문구도 「HWPX 문서
    생성」이어야 한다 — 여기서 되돌려 「확인 필요」라고 쓰면 목록과 필터가 서로 다른
    말을 하고, 사용자는 hwpx 필터 안에서 hwpx 가 아니라는 행을 보게 된다.
    """
    assert work_mode_of_filter_value("hwpx") == WORK_MODE_HWPX
    assert work_mode_of_filter_value("txt") == WORK_MODE_TEXT
    assert work_mode_of_filter_value("") == WORK_MODE_UNSUPPORTED


def test_order_lists_every_mode_exactly_once():
    """나열 순서 상수가 값 집합과 어긋나면 새 방식이 조용히 안 보인다."""
    assert set(WORK_MODE_ORDER) == {
        WORK_MODE_HWPX, WORK_MODE_TEXT, WORK_MODE_UNSUPPORTED,
    }
    assert len(WORK_MODE_ORDER) == 3


# ------------------------------------------------ 최근 사용 문안(§19.4) — 매체별 술어
def test_last_use_label_says_which_event_it_recorded():
    """두 매체가 다른 술어를 쓴다는 사실을 문안이 말한다(지도 §10.15 판정 I).

    HWPX 스탬프는 성공 뒤 실패 런이 있어도 앞선 성공 시각에 머무르므로 "마지막 실행"이
    아니고, TXT 스탬프는 애초에 실행이 아니라 복사다. 같은 문구로 뭉치면 하필 구별이
    중요한 자리에서 이력을 거짓으로 말한다.
    """
    assert last_use_label(WORK_MODE_HWPX, "2026-07-28T10:00:00") == "마지막 성공 실행 2026-07-28"
    assert last_use_label(WORK_MODE_HWPX, "") == "성공한 실행 없음"
    assert last_use_label(WORK_MODE_TEXT, "2026-07-28T10:00:00") == "마지막 복사 2026-07-28"
    assert last_use_label(WORK_MODE_TEXT, "") == "복사한 적 없음"


# ------------------------------------------------------- 방식 구획(§19.3·§19.5)
def test_sections_follow_first_appearance_not_a_fixed_mode_order():
    """구획 순서 = 각 구획 최고 순위 항목의 위치 — 방식별 고정 순서·할당이 아니다."""
    ranked = [
        {"name": "기안A", "mode": WORK_MODE_TEXT},
        {"name": "문서A", "mode": WORK_MODE_HWPX},
        {"name": "기안B", "mode": WORK_MODE_TEXT},
    ]
    secs = mode_sections(ranked)
    assert [s["mode"] for s in secs] == [WORK_MODE_TEXT, WORK_MODE_HWPX]
    assert secs[0]["names"] == ["기안A", "기안B"] and secs[1]["names"] == ["문서A"]
    assert secs[0]["mode_label"] == "온나라 기안 검토·복사"


def test_one_mode_degenerates_to_a_single_section():
    """한 방식뿐이면 구획이 1개 — 표면이 머리글 없는 평면으로 퇴화한다(§19.3)."""
    secs = mode_sections([{"name": "문서A", "mode": WORK_MODE_HWPX}])
    assert len(secs) == 1 and secs[0]["names"] == ["문서A"]
    assert mode_sections([]) == []
