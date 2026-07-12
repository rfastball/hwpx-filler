"""컴파일 상태 배지 시각 매핑 — Qt 비의존(링1). CompileState → (라벨, 레벨) 단일 출처.

같은 도메인 파생(상태→배지 심각도)이 홈(:mod:`home`)과 템플릿 관리
(:mod:`template_manager_state`)에 서로 다른 어휘로 이중 존재하던 것을 여기로 통합한다
(RC-29). 색 팔레트 자체는 :mod:`style` 의 QSS 셀렉터(``QLabel[level=…]``·
``QLabel[pill=…]``)가 소유하고, 이 모듈은 **상태 → 레벨 어휘**만 결정한다:

- ``muted``  — RAW(원문·할 일, 심각도 아님)
- ``warn``   — PARTIAL(다 된 것 같지만 아닌 상태)
- ``ok``     — COMPILED/FILLED(실행 준비)
- ``danger`` — 상태 없음(부재·손상·읽기 실패) = 시끄러운 주의

두 화면이 같은 상태에 다른 심각도 신호를 내지 않도록, 상태별 레벨은 반드시
:func:`badge_level` 을 거친다(수동 이중화 금지).
"""

from __future__ import annotations

from ..core.template_status import CompileState

# 상태 → 사람이 읽는 배지 라벨(단일 출처).
BADGE_LABELS: "dict[CompileState, str]" = {
    CompileState.RAW: "원문",
    CompileState.PARTIAL: "부분 변환",
    CompileState.COMPILED: "변환됨",
    CompileState.FILLED: "채워짐",
}

# 상태 → QSS 배지 레벨(style.py 의 QLabel[level=…]/[pill=…] 팔레트와 통일).
BADGE_LEVELS: "dict[CompileState, str]" = {
    CompileState.RAW: "muted",
    CompileState.PARTIAL: "warn",
    CompileState.COMPILED: "ok",
    CompileState.FILLED: "ok",
}

# 상태를 판정할 수 없는 행(템플릿 부재·손상·읽기 실패) — 조용히 감추지 않고 시끄럽게.
ERROR_BADGE_LABEL = "오류"
ERROR_BADGE_LEVEL = "danger"


def badge_label(state: "CompileState | None") -> str:
    """상태의 배지 라벨. ``None``(부재/오류)은 시끄러운 오류 라벨."""
    if state is None:
        return ERROR_BADGE_LABEL
    return BADGE_LABELS.get(state, state.value)


def badge_level(state: "CompileState | None") -> str:
    """상태의 QSS 배지 레벨. ``None``(부재/오류)은 ``danger`` — never silent."""
    if state is None:
        return ERROR_BADGE_LEVEL
    return BADGE_LEVELS.get(state, ERROR_BADGE_LEVEL)
