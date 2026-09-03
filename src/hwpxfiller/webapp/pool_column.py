"""고르기 열 공용 스냅샷 형 — 좌(템플릿)·우(데이터) 두 열이 같은 키 집합으로 선다.

편집기 1단계 「고르기」의 좌 열과 우 열은 **한 컴포넌트의 두 인스턴스**가 된다. 그러면 두
채널(:mod:`~hwpxfiller.webapp.screen_template` 의 ``tpl`` ·
:mod:`~hwpxfiller.webapp.screen_pool` 의 ``pool``)이 내는 행·존의 키 집합은 **여기 하나**가
소유해야 한다 — 두 곳이 각자 자기 모양을 내면 컴포넌트가 「이 열은 어느 채널인가」를 다시
묻게 되고, 그 물음이 곧 표면 안에 판정이 도로 생기는 자리다.

규율 셋:

- **판정은 링1 이 낸다**(``reason``). 여기서 하는 일은 옮기기뿐이다: 사유를 짓지도,
  ``selectable`` 을 상태에서 다시 유도하지도 않는다 —
  ``selectable = not reason`` 은 파생이지 판정이 아니다.
- **추가 키를 몰래 얹지 않는다.** 한 채널만 아는 키를 하나 더 실으면 그 자리가 두 열이
  갈리는 첫 자리가 된다. 필요한 것이 생기면 여기 키 집합을 **함께** 넓힌다.
- **미지 값은 조용히 통과시키지 않는다.** 아이콘·통지 레벨은 표면 CSS 클래스로 그대로
  나가므로, 표에 없는 값을 넘기면 화면에는 아무것도 안 그려지고 아무도 모른다 —
  ``ValueError`` 로 시끄럽게 거절한다(confirm-or-alarm).

옛 밴드·행 키(``hwpx``/``txt``/``rows``…)는 웹이 이 존으로 옮겨 갈 때까지 그대로 산다.
"""
from __future__ import annotations

#: 열 행 하나가 드는 키 **전부**. 순서는 문서 순서일 뿐이고 계약은 집합이다.
POOL_ROW_KEYS = (
    "key",
    "name",
    "sub",
    "reason",
    "warns",
    "badge_label",
    "badge_level",
    "icon",
    "selectable",
    "path",
    "actions",
)

#: 행 앞머리 표지 — 매체·종류를 가리키는 어휘 전수. 표면 CSS 가 이 값으로 그린다.
#:
#: ``other`` 가 있는 이유: 풀에는 자기 표지가 없는 종류(조립 파이프라인)와, 손편집한
#: ``.dataset.json`` 이 남긴 **미지 종류**가 실재한다. 그것들을 다른 표지로 접으면 화면이
#: 거짓말을 하고(엑셀이 아닌 것을 엑셀로), 표에 없다고 존을 통째로 죽이면 **숨김**이 된다
#: — 그 행은 숨기지 않고 서되 고를 수는 없다는 것이 이 저장소의 처분이다(사유는 링1 이 낸다).
POOL_ICONS = ("hwpx", "txt", "excel", "pclm", "nara", "other")

#: 존 통지의 심각도 — 「사용자가 정리해야 하는 것」(warn)과 「지금 못 읽는 것」(danger).
POOL_NOTICE_LEVELS = ("warn", "danger")


def pool_row_view(
    *,
    key: str,
    name: str,
    sub: str,
    reason: str,
    badge_label: str,
    badge_level: str,
    icon: str,
    path: str,
    actions: "list[dict]",
    warns: "list[str]",
) -> dict:
    """열 행 하나 — 키 집합은 :data:`POOL_ROW_KEYS` 그대로다.

    ``reason`` 은 링1 이 낸 「고를 수 없는 사유」이고 ``selectable`` 은 그 값에서 파생한다.
    두 축을 따로 받지 않는 이유가 여기 있다: 따로 받으면 사유가 서 있는데 고를 수 있다고
    말하는 행이 만들어질 수 있고, 그 모순은 화면에서만 드러난다.

    ``warns`` 는 **고를 수 있는 행이 그래도 미리 알려야 하는 것**이다(채움 완화 사전
    고지 #154). ``reason`` 과 한 축으로 접지 않는 이유는 둘이 서로 다른 말을 하기
    때문이다 — 사유는 「못 고른다」이고 고지는 「골라도 되지만 이렇게 된다」다. 접으면
    한쪽이 조용히 사라진다(빈 값이 빈칸으로 새지 않는다는 계약의 목록 쪽 얼굴).

    ``actions`` 는 ``{"key","label"}`` 목록이고 링1 행이 낸 것을 옮기기만 한다(표면이 제
    판정으로 동사를 더하지 않는다는 계약의 백엔드 쪽 자리).
    """
    if icon not in POOL_ICONS:
        raise ValueError(f"알 수 없는 고르기 행 아이콘: {icon!r} (쓸 수 있는 값: {POOL_ICONS})")
    return {
        "key": key,
        "name": name,
        "sub": sub,
        "reason": reason,
        "warns": [str(w) for w in warns],
        "badge_label": badge_label,
        "badge_level": badge_level,
        "icon": icon,
        "selectable": not reason,
        "path": path,
        "actions": [{"key": a["key"], "label": a["label"]} for a in actions],
    }


def pool_column_view(
    *,
    rows: "list[dict]",
    notices: "list[dict]",
    empty_hint: str,
    count_label: str,
    result: dict,
) -> dict:
    """열 하나 — 행 목록 + 통지 + 빈 상태 문안 + 개수 라벨 + 결과 줄.

    통지는 ``{"level","text","actions"}`` 이고 ``actions`` 는 ``{"key","label","payload"}``
    다: 통지가 지시하는 처분(중복 정리 등)이 그 통지와 같은 자리에 서야 사람이 「무엇을
    하라는 것인가」를 다른 곳에서 찾지 않는다. payload 는 그 채널 액션이 받는 키 그대로다.
    """
    checked: "list[dict]" = []
    for notice in notices:
        level = notice["level"]
        if level not in POOL_NOTICE_LEVELS:
            raise ValueError(
                f"알 수 없는 고르기 열 통지 레벨: {level!r} "
                f"(쓸 수 있는 값: {POOL_NOTICE_LEVELS})"
            )
        checked.append({
            "level": level,
            "text": notice["text"],
            "actions": [
                {"key": a["key"], "label": a["label"], "payload": a["payload"]}
                for a in notice.get("actions", ())
            ],
        })
    return {
        "rows": list(rows),
        "notices": checked,
        "empty_hint": empty_hint,
        "count_label": count_label,
        "result": result,
    }


__all__ = [
    "POOL_ICONS",
    "POOL_NOTICE_LEVELS",
    "POOL_ROW_KEYS",
    "pool_column_view",
    "pool_row_view",
]
