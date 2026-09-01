"""시스템 작업 방식의 **표시 어휘**(링1) — 계약 §19.1 표의 단일 출처.

값 자체(3값)와 파생은 링0 :mod:`hwpxfiller.domain.job` 이 소유하고, 여기는 그 값을 사람이
읽는 문자열로 옮기는 층만 진다. 두 층을 가르는 이유는 소비자가 다르기 때문이다 — 판정은
후보·게이트·편집기 탭이 쓰고, 문자열은 표면 셋(후보 카드·문서 탐색·라이브러리)이 쓴다.

**왜 한 자리인가**(지도 §10.15 판정 A). F6 이전에는 이 표가 링2
(:mod:`hwpxfiller.webapp.screen_library`)에만 있었고 「문서 만들기」는 방식 문구가 아예
없었다. TXT 가 후보로 합류하면 같은 축을 세 표면이 그리는데, 각자 문구를 지으면 같은 상태를
다르게 부르는 자리가 셋이 된다(§10.5 판정 단일 출처). 그래서 라벨을 링1으로 올리고 표면은
읽기만 한다.

**짧은 표시 / 전체 표시의 용도**는 계약 §19.1 표 그대로다: 짧은 쪽은 카드 부제·칩처럼 폭이
좁고 문맥이 이미 있는 자리, 전체 쪽은 목록 행·필터 칩처럼 그 문자열만으로 뜻이 서야 하는
자리다. 색만으로 방식을 구별하지 않는다(§19.3 마지막 문장) — 텍스트가 늘 함께 선다.
"""

from ..domain.job import (
    WORK_MODE_HWPX,
    WORK_MODE_TEXT,
    WORK_MODE_UNSUPPORTED,
    work_mode,
)

__all__ = [
    "WORK_MODE_HWPX",
    "WORK_MODE_TEXT",
    "WORK_MODE_UNSUPPORTED",
    "WORK_MODE_ORDER",
    "mode_sections",
    "seat_kinds",
    "work_mode_label",
    "work_mode_of_filter_value",
]

#: 구획·필터가 방식을 나열할 때의 고정 순서(§19.1 표 순서). 구획 **선택**은 순위가 하고
#: (§19.3 — 구획 순서는 각 구획 최고 순위 항목의 위치), 이 상수는 필터 칩처럼 순위가 없는
#: 자리의 나열 순서만 정한다.
WORK_MODE_ORDER = (WORK_MODE_HWPX, WORK_MODE_TEXT, WORK_MODE_UNSUPPORTED)

#: (짧은 표시, 전체 표시) — 계약 §19.1 표를 그대로 옮긴다.
_LABELS = {
    WORK_MODE_HWPX: ("HWPX 생성", "HWPX 문서 생성"),
    WORK_MODE_TEXT: ("온나라 기안", "온나라 기안 검토·복사"),
    WORK_MODE_UNSUPPORTED: ("작업 방식 확인", "지원 작업 방식 확인 필요"),
}


def work_mode_label(mode: str, *, short: bool = False) -> str:
    """작업 방식 코드 → 표시 문구. 모르는 코드는 ``unsupported`` 문구로 접는다.

    폴백이 ``unsupported`` 인 것은 관용이 아니라 fail-closed 다 — 새 값이 생겼는데 배선을
    빠뜨리면 「확인 필요」로 보이지 「HWPX 생성」으로 보이지 않는다.
    """
    pair = _LABELS.get(mode) or _LABELS[WORK_MODE_UNSUPPORTED]
    return pair[0] if short else pair[1]


def seat_kinds(template_path: str) -> "tuple[bool, bool]":
    """작업의 착석 분류 ``(TXT 인가, 미상 매체인가)`` — 세 값짜리 축의 단일 판정(링1, P2-24).

    실행 표면은 셋이다: hwpx 실행뷰 · TXT 작업대 · **어느 쪽도 아님**. 앞의 둘만 세면 세
    번째가 hwpx 로 접혀 ``RunViewModel`` 이 ``require_hwpx`` 에서 loud raise 하고, 그 예외는
    재적재·재연결처럼 **사용자가 실행을 시작하지도 않은** 경로에서 튄다.

    빈 경로는 미상이지만 **저작 중인 hwpx 작업**이라 실행뷰를 세운다 — ``require_hwpx`` 도
    빈 경로만 관용하고, 라이브러리 ``library_mode_of`` 도 같은 귀속을 쓴다.
    """
    mode = work_mode(template_path)
    unsupported = bool(template_path) and mode not in (WORK_MODE_HWPX, WORK_MODE_TEXT)
    return mode == WORK_MODE_TEXT, unsupported


def work_mode_of_filter_value(value: str) -> str:
    """라이브러리 **필터 값**(매체 어휘 ``hwpx``/``txt``/``''``) → 작업 방식 코드.

    두 어휘가 남아 있는 이유는 축이 둘이기 때문이다(지도 §10.15 판정 A): 필터 값은
    :func:`~hwpxfiller.gui.home_state.library_mode_of` 가 내는 **귀속**이라 미연결 작업을
    일부러 hwpx 로 세고, 작업 방식은 확장자에서만 파생한다. 그 귀속을 여기서 되돌리지
    않는다 — 필터가 hwpx 칸에 놓기로 한 행에 「지원 작업 방식 확인 필요」라고 쓰면 목록과
    필터가 서로 다른 말을 한다. 이 함수는 *번역*이지 재판정이 아니다.
    """
    if value == "hwpx":
        return WORK_MODE_HWPX
    if value == "txt":
        return WORK_MODE_TEXT
    return WORK_MODE_UNSUPPORTED


def mode_sections(items: "list[dict]", *, key: str = "mode") -> "list[dict]":
    """항목 목록 → 작업 방식 구획(§19.3·§19.5). **순서는 첫 등장 순**이다.

    계약이 정한 구획 순서는 "각 구획에 포함된 항목 중 가장 높은 전역 순위의 위치"이고,
    입력이 이미 순위순이면 첫 등장 순이 곧 그 순서다 — 별도 정렬을 얹으면 순위 판정이 두
    곳에 살게 된다(문서 탐색처럼 이름순인 목록에서도 같은 규칙이 그대로 성립한다).

    **한 방식만 있으면 구획하지 않는다**(반환 1개 + 호출측이 `len(sections) > 1` 로 판단):
    중복 정보를 줄이려는 계약의 퇴화 규칙이다. 카드 부제의 방식 텍스트는 그때도 유지되므로
    (§19.3 마지막 문장) 정보가 사라지는 것이 아니라 **머리글만** 사라진다.
    """
    order: "list[str]" = []
    buckets: "dict[str, list[dict]]" = {}
    for item in items:
        mode = str(item.get(key, "")) or WORK_MODE_UNSUPPORTED
        if mode not in buckets:
            order.append(mode)
            buckets[mode] = []
        buckets[mode].append(item)
    return [
        {"mode": m, "mode_label": work_mode_label(m), "names": [i["name"] for i in buckets[m]]}
        for m in order
    ]
