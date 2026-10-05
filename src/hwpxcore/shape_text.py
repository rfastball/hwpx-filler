"""도형·그림 개체의 본문 텍스트 — 글상자·캡션 결정표와 순회.

:mod:`hwpxcore.text_extract` 의 런 결정 지점이 도형(``hp:rect`` 등)·그림(``hp:pic``)을
만나면 여기로 위임한다. 개체가 품는 본문은 두 갈래뿐이다.

  - 글상자 ``drawText`` > ``subList`` > ``hp:p`` — 셀과 동형인 자체 문단 흐름이다.
    :class:`~hwpxcore.text_model.TextBox` 하나로 복원한다(안의 표·중첩 도형까지 재귀).
  - 캡션 ``caption`` > ``subList`` > ``hp:p`` — 표 캡션과 같은 규칙이다. 개체 블록
    앞(문서 순서)에 놓는다.

묶음 ``hp:container`` 는 자식 도형을 문서 순서로 재귀한다. 그 밖의 자식은 기하·렌더 메타라
본문이 없고, 결정표에 없는 자식은 커버리지 원장에 소리 나게 남는다. 기하 점(``hc:pt0``
등)·그림 원본(``hc:img``)은 core 네임스페이스로 오므로 같은 허용목록을 그 네임스페이스에도
적용한다.

순환 import 를 피하려 문단 컨테이너 순회 함수(``blocks_of``)를 인자로 받는다.
"""

from __future__ import annotations

from collections.abc import Callable

import lxml.etree as etree

from .text_model import (
    HC_NS,
    Block,
    CoverageLedger,
    FieldFilter,
    TextBox,
    local_name,
    namespace_of,
)

#: 문단 컨테이너(``subList``)를 블록 목록으로 바꾸는 순회 함수(``text_extract`` 가 준다).
type BlocksOf = Callable[[etree._Element, CoverageLedger, str, FieldFilter], list[Block]]

#: 런 직속(그리고 묶음 직속) 도형 개체. 본문은 :func:`shape_blocks` 가 정한다.
SHAPE_TAGS = frozenset(
    {"rect", "ellipse", "arc", "polygon", "curve", "line", "connectLine", "container", "pic"}
)

# 도형 직속 자식. 본문을 운반하는 것은 글상자 drawText 와 캡션 caption 뿐이다.
_HANDLED_SHAPE = frozenset({"drawText", "caption"})
# 묶음(container)은 여기에 자식 도형을 더해 문서 순서로 재귀한다.
_HANDLED_GROUP = _HANDLED_SHAPE | SHAPE_TAGS
# 기하·렌더 메타 — 본문 텍스트 없음.
#   크기·위치·여백: sz pos outMargin inMargin offset orgSz curSz
#   변환·선·채우기: flip rotationInfo renderingInfo lineShape fillBrush shadow
#   기하 점(hc: 로도 온다): pt pt0~pt3(사각형 꼭짓점) center ax1 ax2 start1 end1 start2
#     end2(타원·호) startPt endPt(선·연결선) controlPoints point(연결선 제어점) seg(곡선)
#   shapeComment: 개체 설명(대체 텍스트) 메타 — 화면에 그려지는 본문이 아니다.
#   metaTag: 개체에 붙인 메타데이터 문자열 — 본문이 아니다.
_IGNORE_SHAPE = frozenset({
    "sz", "pos", "outMargin", "inMargin", "offset", "orgSz", "curSz",
    "flip", "rotationInfo", "renderingInfo", "lineShape", "fillBrush", "shadow",
    "pt", "pt0", "pt1", "pt2", "pt3", "center", "ax1", "ax2",
    "start1", "end1", "start2", "end2", "startPt", "endPt", "controlPoints", "point", "seg",
    "shapeComment", "metaTag",
})
# 그림(pic)은 여기에 원본 이미지 참조·자르기·크기·효과 메타를 더한다(본문 텍스트 없음).
_IGNORE_PIC = _IGNORE_SHAPE | frozenset({"img", "imgRect", "imgClip", "imgDim", "effects"})

# hp:drawText 직속 자식. 글상자 본문은 subList 밑 문단에 담긴다(표 셀과 동형).
_HANDLED_DRAWTEXT = frozenset({"subList"})
_IGNORE_DRAWTEXT = frozenset({"textMargin"})  # 글상자 안쪽 여백 렌더 메타

# hp:caption 직속 자식. 캡션 텍스트는 subList 밑 문단에 담긴다(표 셀과 동형).
_HANDLED_CAPTION = frozenset({"subList"})
_IGNORE_CAPTION: "frozenset[str]" = frozenset()


def _classify(
    ledger: CoverageLedger,
    child: etree._Element,
    handled: "frozenset[str]",
    ignored: "frozenset[str]",
    path: str,
) -> str:
    """도형 결정 지점 분류. core(``hc:``) 네임스페이스의 허용 메타도 의식적 무시로 친다."""
    if namespace_of(child.tag) == HC_NS and local_name(child.tag) in ignored:
        return local_name(child.tag)
    return ledger.classify(child, handled, ignored, path)


def _sublist_blocks(
    owner: etree._Element,
    handled: "frozenset[str]",
    ignored: "frozenset[str]",
    ctx: "tuple[CoverageLedger, str, FieldFilter, BlocksOf]",
) -> "list[Block]":
    """``owner`` 직속 ``subList`` 들의 문단을 문서 순서로 블록화(캡션·글상자 공용)."""
    ledger, path, field_filter, blocks_of = ctx
    blocks: "list[Block]" = []
    for sub in owner:
        if ledger.classify(sub, handled, ignored, path) == "subList":
            blocks.extend(blocks_of(sub, ledger, f"{path}/subList", field_filter))
    return blocks


def caption_blocks(
    cap_el: etree._Element,
    ledger: CoverageLedger,
    path: str,
    field_filter: FieldFilter,
    blocks_of: BlocksOf,
) -> "list[Block]":
    """``hp:caption`` -> 캡션 문단 블록 목록. 텍스트는 ``hp:subList`` 밑 문단에 담긴다.

    캡션은 표·그림·도형에 붙는 제목·설명(예: ``<표 1> 유압식 잭(30톤) 주요제원``)으로 본문
    텍스트다. 셀 subList 와 동형이라 같은 컨테이너 순회로 문단을 복원한다.
    """
    ctx = (ledger, path, field_filter, blocks_of)
    return _sublist_blocks(cap_el, _HANDLED_CAPTION, _IGNORE_CAPTION, ctx)


def shape_blocks(
    shape_el: etree._Element,
    ledger: CoverageLedger,
    path: str,
    field_filter: FieldFilter,
    blocks_of: BlocksOf,
) -> "list[Block]":
    """도형 하나가 낳는 블록 — 캡션 문단, 이어서 본문(글상자 또는 묶음의 자식 도형).

    글상자가 없는 도형(폴리곤·캡션 없는 그림 등)은 빈 목록이다 — 호출부는 그때 문단을
    쪼개지 않는다. ``path`` 는 도형 자신의 경로(예: ``section0/p/run/rect``)다.
    """
    kind = local_name(shape_el.tag)
    handled = _HANDLED_GROUP if kind == "container" else _HANDLED_SHAPE
    ignored = _IGNORE_PIC if kind == "pic" else _IGNORE_SHAPE
    captions: "list[Block]" = []
    body: "list[Block]" = []
    for child in shape_el:
        ln = _classify(ledger, child, handled, ignored, path)
        ctx = (ledger, f"{path}/{ln}", field_filter, blocks_of)
        if ln == "caption":
            captions.extend(_sublist_blocks(child, _HANDLED_CAPTION, _IGNORE_CAPTION, ctx))
        elif ln == "drawText":
            body.append(TextBox(_sublist_blocks(child, _HANDLED_DRAWTEXT, _IGNORE_DRAWTEXT, ctx)))
        elif kind == "container" and ln in SHAPE_TAGS:
            body.extend(shape_blocks(child, ledger, f"{path}/{ln}", field_filter, blocks_of))
    return captions + body
