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
