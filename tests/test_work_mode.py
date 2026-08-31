"""시스템 작업 방식의 표시 어휘(링1) — 계약 §19.1 표의 단일 출처 경계.

정본: lab `docs/core-workflow.md` §19.1 · 지도 §10.15 판정 A.
"""

import pytest

from hwpxfiller.domain.job import (
    WORK_MODE_HWPX,
    WORK_MODE_TEXT,
    WORK_MODE_UNSUPPORTED,
)
from hwpxfiller.gui.work_mode import (
    WORK_MODE_ORDER,
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


# (최근 사용 **문안**의 매체별 술어 테스트는 산출자와 함께 걷혔다 — 실행 이력을 문구로
#  말하던 표면이 사라져 `last_use_label` 의 소비자가 0 이 됐다. `Job.last_run_at` 은 남고
#  「최근 사용」 보기의 정렬 재료로만 산다.)


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
