"""CompileState→(라벨, 레벨) 단일 출처(링1) 테스트 — RC-29.

홈 카드와 템플릿 관리 배지가 같은 상태에 같은 심각도 신호를 내는지, 그리고
상태 판정 불가(None)가 조용히 감춰지지 않고 danger 로 승격되는지 못박는다.
"""

from __future__ import annotations

from pathlib import Path

from hwpxfiller.domain.template_status import CompileState, TemplateStatus
from hwpxfiller.gui.compile_badge import (
    BADGE_LABELS,
    BADGE_LEVELS,
    badge_label,
    badge_level,
)
from hwpxfiller.gui.template_manager_state import TemplateRow


def test_every_compile_state_has_label_and_level():
    for state in CompileState:
        assert badge_label(state) == BADGE_LABELS[state]
        assert badge_level(state) == BADGE_LEVELS[state]
        assert badge_level(state) in {"muted", "warn", "ok", "danger"}


def test_severity_vocabulary_is_unified():
    """RAW=muted(할 일)·PARTIAL=warn·COMPILED/FILLED=ok — 화면별 상이 어휘 금지."""
    assert badge_level(CompileState.RAW) == "muted"
    assert badge_level(CompileState.PARTIAL) == "warn"
    assert badge_level(CompileState.COMPILED) == "ok"
    assert badge_level(CompileState.FILLED) == "ok"


def test_none_state_is_loud_danger():
    """부재·손상·읽기 실패(state=None)는 조용한 강등이 아니라 danger/오류."""
    assert badge_level(None) == "danger"
    assert badge_label(None) == "오류"


def test_template_manager_rows_derive_from_single_source():
    """템플릿 관리 행 성형이 이 모듈을 관통한다 — 자체 매핑 이중화 회귀 방지."""
    status = TemplateStatus(
        state=CompileState.PARTIAL, field_n=2, compilable_n=1, skipped_n=0, stray_n=0
    )
    row = TemplateRow.from_status(Path("t.hwpx"), status)
    assert row.badge_label == badge_label(CompileState.PARTIAL)
    assert row.badge_level == badge_level(CompileState.PARTIAL) == "warn"

    err = TemplateRow.from_error(Path("broken.hwpx"), "읽기 실패")
    assert err.badge_label == badge_label(None) == "오류"
    assert err.badge_level == badge_level(None) == "danger"


def test_structure_notation_status_routes_through_the_same_badge_source():
    """구간 표기만 남은 PARTIAL 도 배지 어휘를 새로 만들지 않는다(S8-04 #835).

    새 수치는 상세 줄이 말하고 심각도 신호는 기존 단일 출처가 그대로 낸다 — 잔존 종류마다
    배지를 새로 만들면 같은 위험이 화면마다 다른 색·다른 말로 보인다.
    """
    status = TemplateStatus(
        state=CompileState.PARTIAL, field_n=1, compilable_n=0, skipped_n=0, stray_n=0,
        structure_marker_n=2,
    )
    row = TemplateRow.from_status(Path("notation.hwpx"), status)

    assert (row.badge_label, row.badge_level) == (badge_label(CompileState.PARTIAL), "warn")
    assert row.structure_marker_n == 2
    assert row.detail_line() == "필드 1개 · 구간 표기 2개"
