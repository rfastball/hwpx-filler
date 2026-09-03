"""고르기 열 공용 형(`webapp/pool_column.py`) 계약 — 키 집합 하나, 미지 값은 시끄럽게.

좌(템플릿)·우(데이터) 두 열이 같은 컴포넌트의 두 인스턴스가 되므로, 행·존의 키 집합은
이 모듈 하나가 소유한다. 여기서 재는 것은 그 소유의 두 얼굴이다: ⑴ 나오는 키가 정확히
선언된 집합인가(몰래 얹은 키가 두 열이 갈리는 첫 자리다) ⑵ 표에 없는 아이콘·레벨이
조용히 통과하지 않는가(표면 CSS 클래스로 그대로 나가므로 화면에는 아무것도 안 그려지고
아무도 모른다).
"""
from __future__ import annotations

import pytest

from hwpxfiller.webapp.pool_column import (
    POOL_ICONS,
    POOL_NOTICE_LEVELS,
    POOL_ROW_KEYS,
    pool_column_view,
    pool_row_view,
)


def _row(**over) -> dict:
    base = dict(
        key="a.hwpx", name="공고서", sub="필드 3개", reason="",
        badge_label="변환 완료", badge_level="ok", icon="hwpx",
        path="C:/lib/a.hwpx", actions=[{"key": "compile", "label": "누름틀·구간 변환"}],
    )
    base.update(over)
    return pool_row_view(**base)


def test_row_view_carries_exactly_the_declared_keys():
    row = _row()
    assert tuple(row) == POOL_ROW_KEYS
    assert row["actions"] == [{"key": "compile", "label": "누름틀·구간 변환"}]


def test_selectable_is_derived_from_the_reason_not_received_twice():
    """가부는 사유의 파생이다 — 따로 받으면 「사유가 서 있는데 고를 수 있는」 행이 난다."""
    assert _row(reason="")["selectable"] is True
    assert _row(reason="누름틀·구간 변환을 해야 고를 수 있습니다.")["selectable"] is False


def test_unknown_icon_is_refused_loudly():
    with pytest.raises(ValueError, match="알 수 없는 고르기 행 아이콘"):
        _row(icon="pipeline")


def test_every_declared_icon_is_accepted():
    for icon in POOL_ICONS:
        assert _row(icon=icon)["icon"] == icon


def test_column_view_carries_exactly_five_zones_and_copies_notices():
    column = pool_column_view(
        rows=[_row()],
        notices=[
            {"level": "danger", "text": "⚠ 손상된 등록 데이터: a.json — bad", "actions": []},
            {
                "level": "warn", "text": "같은 데이터…",
                "actions": [
                    {"key": "resolve_duplicate", "label": "'A' 남기기",
                     "payload": {"keep": "k1"}},
                ],
            },
        ],
        empty_hint="",
        count_label="1개",
        result={"text": "", "level": "muted"},
    )
    assert tuple(column) == ("rows", "notices", "empty_hint", "count_label", "result")
    assert [n["level"] for n in column["notices"]] == ["danger", "warn"]
    assert column["notices"][1]["actions"] == [
        {"key": "resolve_duplicate", "label": "'A' 남기기", "payload": {"keep": "k1"}}
    ]
    assert tuple(column["notices"][0]) == ("level", "text", "actions")


def test_unknown_notice_level_is_refused_loudly():
    with pytest.raises(ValueError, match="알 수 없는 고르기 열 통지 레벨"):
        pool_column_view(
            rows=[], notices=[{"level": "info", "text": "x", "actions": []}],
            empty_hint="", count_label="", result={"text": "", "level": "muted"},
        )
    assert POOL_NOTICE_LEVELS == ("warn", "danger")
