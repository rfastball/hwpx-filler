"""HWPX 본문 추출 트리의 데이터 모델과 커버리지 원장.

:mod:`hwpxcore.text_extract`(순회)와 :mod:`hwpxcore.shape_text`(도형·캡션 결정표)가 함께
쓰는 바닥 층이다. 블록 트리(:class:`Paragraph`·:class:`Table`·:class:`TextBox`)는 랜덤
ID 없이 결정적으로 직렬화되고, 모델링하지 않은 구조는 :class:`CoverageLedger` 에 소리 나게
남는다. 공개 import 경로는 :mod:`hwpxcore.text_extract` 가 그대로 다시 내보낸다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import lxml.etree as etree

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"

#: 도형 기하 점(``hc:pt0`` 등)·그림 원본(``hc:img``)이 쓰는 core 네임스페이스.
HC_NS = "http://www.hancom.co.kr/hwpml/2011/core"

#: ``fieldBegin@type`` 을 받아 그 누름틀 이름을 ``Paragraph.fields`` 에 실을지 정하는 거름.
type FieldFilter = Callable[[str | None], bool] | None


def local_name(tag: object) -> str:
    """요소의 로컬 태그명(네임스페이스 제거). 주석/PI 등 비문자 태그는 빈 문자열."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def namespace_of(tag: object) -> str:
    """요소 태그의 네임스페이스 URI. 없으면 빈 문자열."""
    if not isinstance(tag, str) or not tag.startswith("{"):
        return ""
    return tag[1:].split("}", 1)[0]


# ---------------------------------------------------------------- 커버리지 원장
@dataclass
class CoverageLedger:
    """모델링하지 않은 구조를 소리 나게 남기는 원장.

    각 순회 결정 지점(섹션/문단/런/표/행/셀/도형 직속 자식)에서 HANDLED 도 KNOWN_IGNORED 도
    아닌 태그를 만나면 여기에 태그->횟수, 태그->첫 등장 경로로 기록한다. 원장이 비어야
    '모든 자식을 의식적으로 처리 또는 허용했다'는 뜻이다.
    """

    counts: "dict[str, int]" = field(default_factory=dict)
    examples: "dict[str, str]" = field(default_factory=dict)

    def record(self, tag: str, path: str) -> None:
        self.counts[tag] = self.counts.get(tag, 0) + 1
        self.examples.setdefault(tag, path)

    def classify(
        self,
        child: etree._Element,
        handled: "frozenset[str]",
        known_ignored: "frozenset[str]",
        path: str,
    ) -> str:
        """자식 요소를 분류하고, 미처리면 기록. 로컬 태그명을 반환(비-요소는 '')."""
        tag = child.tag
        if not isinstance(tag, str):  # 주석/PI 등
            return ""
        local = local_name(tag)
        ns = namespace_of(tag)
        if ns and ns != HP_NS:
            # 본문 결정 지점에 나타난 비-hp 요소도 침묵 누락 방지 위해 기록.
            self.record(f"{{{ns}}}{local}", f"{path}/{local}")
            return local
        if local in handled or local in known_ignored:
            return local
        self.record(local, f"{path}/{local}")
        return local

    def to_dict(self) -> dict:
        return {
            "counts": {k: self.counts[k] for k in sorted(self.counts)},
            "examples": {k: self.examples[k] for k in sorted(self.examples)},
        }


# ----------------------------------------------------------------- data model
@dataclass
class Paragraph:
    """복원된 문단. ``text`` 는 파편을 이어붙인 최종 문자열(탭/줄바꿈 보존).

    ``fields`` 는 이 문단 안에서 텍스트를 담은 누름틀 이름의 순서 있는 중복 없는 목록
    (의미론적 이름이므로 랜덤 ID 가 아니다). BOOKMARK 는 Field 가 아니라 구간 경계라 넣지
    않고, 그 밖의 ``type`` 거름은 :func:`extract_document` 의 ``field_filter`` 가 정한다.
    """

    text: str
    fields: "list[str]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"type": "paragraph", "text": self.text, "fields": list(self.fields)}


@dataclass
class Cell:
    """표 셀. 자체 문단/표 블록(표 중첩 지원)과 병합 메타를 갖는다.

    ``span``/``addr`` 은 원문 ``cellSpan``/``cellAddr`` 숫자를 그대로 보존한다(그리드
    기하는 해석하지 않음 — diff/생성기가 정렬에 쓰도록).
    """

    blocks: "list[Block]" = field(default_factory=list)
    span: "dict[str, int]" = field(default_factory=dict)  # {"colSpan":n,"rowSpan":n}
    addr: "dict[str, int]" = field(default_factory=dict)  # {"colAddr":n,"rowAddr":n}

    def to_dict(self) -> dict:
        return {
            "blocks": [b.to_dict() for b in self.blocks],
            "span": {k: self.span[k] for k in sorted(self.span)},
            "addr": {k: self.addr[k] for k in sorted(self.addr)},
        }


@dataclass
class Table:
    """표. ``rows`` 는 행 목록, 각 행은 셀 목록."""

    rows: "list[list[Cell]]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": "table",
            "rows": [[c.to_dict() for c in row] for row in self.rows],
        }


@dataclass
class TextBox:
    """도형 글상자(``drawText`` > ``subList``)의 본문. ``blocks`` 는 그 안의 블록 목록.

    글상자는 문단 안 런에 앵커된 도형이 품은 자체 문단 흐름이다(셀과 동형 ``subList``).
    문서 순서의 앵커 자리에 놓이며 표·중첩 도형을 담을 수 있다.
    """

    blocks: "list[Block]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"type": "textbox", "blocks": [b.to_dict() for b in self.blocks]}


#: 블록 트리의 한 마디 — 문단·표·글상자.
type Block = Paragraph | Table | TextBox


@dataclass
class Section:
    """섹션/머리말/꼬리말 본문. ``blocks`` 는 문서 순서의 Paragraph/Table/TextBox 목록."""

    blocks: "list[Block]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"blocks": [b.to_dict() for b in self.blocks]}


@dataclass
class Document:
    """추출된 문서 전체.

    ``sections`` 는 본문 섹션(section0, section1, ...). ``headers``/``footers`` 는 본문
    문단을 실제로 담은 머리말/꼬리말 영역(스타일 전용 ``hp:head`` 파일은 제외). 본문에
    섞지 않고 종류별로 분리해 라벨링한다. ``unhandled``/``unhandled_examples`` 는 미처리
    구조 원장이다(정상 문서에서는 비어 있어야 한다).
    """

    sections: "list[Section]" = field(default_factory=list)
    headers: "list[Section]" = field(default_factory=list)
    footers: "list[Section]" = field(default_factory=list)
    unhandled: "dict[str, int]" = field(default_factory=dict)
    unhandled_examples: "dict[str, str]" = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "sections": [s.to_dict() for s in self.sections],
            "headers": [s.to_dict() for s in self.headers],
            "footers": [s.to_dict() for s in self.footers],
            "unhandled": {k: self.unhandled[k] for k in sorted(self.unhandled)},
            "unhandled_examples": {
                k: self.unhandled_examples[k] for k in sorted(self.unhandled_examples)
            },
        }

