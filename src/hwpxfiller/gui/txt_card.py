"""TXT 작업점 카드의 공유 판정(링1) — 「보이는 것 = 복사되는 것」의 단일 통로.

두 표면이 이 함수들을 소비한다: 「기안」 화면 세션
(F6 PR-B 에서 사망)과 검토·복사 작업대
(:mod:`hwpxfiller.webapp.screen_workbench`). 옮긴 것은 **판정**이고 스냅샷 성형은 각
표면이 계속 소유한다.

**왜 링1으로 올렸나**(지도 §10.15 판정 G). 작업대가 카드 렌더를 자기 몫으로 다시 짜면
같은 문장이 두 곳에서 만들어진다 — 그리고 그 둘 중 하나만 전각 치환을 타거나 확정-비움을
빼면, 화면이 보여 준 것과 클립보드에 실린 것이 갈린다. 결정 17(치환의 계약)이 세그먼트
경로 하나로 묶어 둔 것을 표면이 늘었다고 풀지 않는다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..domain.text_render import (
    RenderReport,
    align_segments,
    render_segments,
    segments_have_space_run,
)

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ["CardRender", "render_card", "card_text", "gate_empty_fields"]


@dataclass(frozen=True)
class CardRender:
    """카드 1건의 렌더 결과 — 표시·클립보드·린트가 **한 번의 렌더**를 나눠 쓴다."""

    #: 전각 치환까지 끝낸 세그먼트 — 화면이 그리고 클립보드가 이어붙이는 바로 그것.
    segments: list
    report: RenderReport
    #: 연속 공백 런의 존재 — **치환 전 원문** 기준(결정 17). 치환하면 런이 사라지므로
    #: 치환 후로 재면 「적용됨 · 되돌리기」 상태에서 무엇을 고쳤는지 말할 수 없게 된다.
    space_run: bool
    #: 전각 치환이 실제로 걸렸는가(세션 옵션) — 표면이 글꼴 이름으로 재판별하지 않게.
    fullwidth: bool


def render_card(
    template_text: str, mapping, record: dict, *, fullwidth: bool,
    now: "datetime | None" = None,
) -> CardRender:
    """레코드 1건 → :class:`CardRender`. 카드 렌더·클립보드·린트의 공용 통로.

    이음매는 **레코드 → 맞추기 매핑 → 값 사전 → render_segments** 다(#148 슬라이스 3b):
    항등 매핑(토큰명 = 열명)이 아니라 결속·표시형·상수를 얹은 값 사전이 들어간다.
    전각 치환은 세션 옵션이 켜졌을 때만, 그리고 **여기 한 곳에서만** 걸린다.

    ``now`` 는 ``today``(오늘 날짜) 유형의 기준 시각이다 — 표면이 렌더 1회마다 한 번만
    잡아 넘긴다(「보이는 것 = 복사되는 것」: 카드와 클립보드가 같은 렌더를 나눠 쓰므로
    시각도 한 벌이어야 한다). 미지정이면 적용 시점으로 폴백한다.
    """
    segments, report = render_segments(
        template_text, mapping.live_profile().apply(record, now=now)
    )
    space_run = segments_have_space_run(segments)
    return CardRender(
        segments=align_segments(segments) if fullwidth else segments,
        report=report,
        space_run=space_run,
        fullwidth=fullwidth,
    )


def card_text(segments: list) -> str:
    """세그먼트 → 클립보드·카드 텍스트. 이어붙이기 규칙도 한 자리에 둔다."""
    return "".join(s.text for s in segments)


def gate_empty_fields(report: "RenderReport", mapping) -> "list[str]":
    """리포트의 빈 값 집합에서 **확정-비움을 뺀** 게이트·완료 노트용 집합(결정 12).

    렌더는 확정-비움도 〈빈 값〉으로 **그대로 그린다** — 갈리는 것은 "보이는가"가 아니라
    "확인해야 하는가"다. 데이터가 비어서 생긴 빈 값은 선언이 아니라 그 행의 사실이라
    남는다. 판정 단일 출처는 :meth:`~hwpxfiller.gui.mapping_state.MappingModel.
    declared_empty_fields` 이고, 카드 스냅샷의 게이트 집합도 같은 술어를 쓴다.
    """
    declared = set(mapping.declared_empty_fields())
    return [f for f in report.empty_fields if f not in declared]
