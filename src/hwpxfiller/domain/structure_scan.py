"""구간 표기 코어 — 매체 독립 절반(lxml·OCF 비의존).

S8 이 세운 **구간 표기 문법 v1**(``{{#항목 <id> <label…>}}`` … ``{{/항목}}`` /
``{{#선택 <id> <label…>}}`` … ``{{/선택}}``)에서 **매체를 모르는 부분**이 여기 산다:
토큰 문법, sigil 선행 분류, 진단 어휘, 그리고 마커 스트림을 선언 구조로 접는
상태기계(:class:`StructureReader`).

**왜 갈라 두는가.** 같은 표기를 읽는 스캐너가 둘이다 — HWPX 문단 트리를 걷는
:mod:`~hwpxfiller.domain.authoring` 과 TXT 줄을 걷는
:mod:`~hwpxfiller.domain.text_structure`. 두 매체가 각자 상태기계를 조립하면 같은
선언이 매체마다 다르게 읽힌다(진단 종별·id 중복 판정·빈 범위 판정·배치 폴백이
갈린다). 그러면 저작자는 어느 쪽이 맞는지 알 수 없고, 「같은 표기 = 같은 구조」라는
S10 의 전제 자체가 무너진다. 그래서 전이는 **한 몸통**이고 매체는 입력만 준다.

**lxml 을 import 하지 않는다** — 그것이 이 분리의 검사 가능한 얼굴이다.
:mod:`~hwpxfiller.domain.text_render`(「lxml·OCF 없이 순수 문자열」)와
:mod:`~hwpxfiller.domain.text_structure` 는 이 모듈을 통과해 sigil 술어와 상태기계를
쓰되 XML 커널을 딸려오지 않는다. 토큰 문법(``{{ }}``)의 단일 출처가 여기라
:func:`normalize_field_id` — ``{{…}}`` 한 겹을 벗기는 Field ID 정규화 — 도 함께 산다
(:mod:`~hwpxfiller.domain.fields` 가 이름을 재노출해 기존 소비자는 무변경이다).

**매체가 주입하는 것은 둘뿐**이다:

- ``scope`` — 범위가 닫히지 않은 채 끝난 단위의 **조사까지 실은 주어구**
  (HWPX=``content XML 이``·TXT=``파일이``) — 코어가 「{scope} 끝났습니다」로 잇는다.
- ``placement`` — 닫힌 범위 1건을 그 매체의 좌표 값으로 만드는 factory. 내용 경계의
  폴백 규칙(내용이 하나도 없으면 마커 사이 전체)은 **코어가** 계산해 넘긴다 — 그
  규칙이 매체마다 갈리면 빈 범위의 배치가 두 얼굴을 갖는다.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .slot import Slot, SlotOption

#: 완전 토큰 1개 — 필드 토큰과 구조 마커가 **같은 괄호 문법**을 공유한다.
TOKEN_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

#: 진단 ``context`` 의 최대 길이 — 매체 불문 같은 절단 규칙.
CONTEXT_MAX = 120


# --------------------------------------------------- sigil 선행 분류(S8-01 #832)
# 구간 표기 마커(``{{#항목 …}}``·``{{/항목}}``)는 필드 토큰과 **같은 괄호 문법**을 쓴다.
# 그래서 sigil 판정이 필드 토큰화보다 **먼저** 서야 한다 — 그러지 않으면 구조 마커가
# 「#항목 …」 이라는 이름의 누름틀(HWPX)이나 미치환 필드(TXT)로 조용히 오변환된다.
# 토큰 발견 지점이 여럿이므로 술어와 필터를 **한 곳**에 두고 전 지점이 그것만 쓴다.
_STRUCTURE_SIGILS = ("#", "/")


def is_structure_sigil(raw: str) -> bool:
    """토큰 내용이 구간 표기 마커인가 — 앞 공백을 뗀 첫 글자가 ``#``/``/``.

    **공개 술어**(S8-04): 완전 토큰을 발견하는 자리는 이 모듈 밖에도 있다
    (:func:`~hwpxfiller.domain.schema.extract_schema` 의 미치환 잔존 분류,
    :func:`~hwpxfiller.domain.text_render.template_fields` 의 TXT 필드 목록). 그
    자리들이 각자 sigil 을 다시 판정하면 「구조 마커인가」가 여러 곳에서 갈린다 —
    같은 토큰이 한 표면에선 구간 표기, 다른 표면에선 미치환 필드 토큰으로 세어져 한
    잔존물이 두 번 보고된다. 그래서 술어는 여기 하나이고 전 발견 지점이 그것만 쓴다.
    """
    body = raw.lstrip()
    return bool(body) and body[0] in _STRUCTURE_SIGILS


def iter_field_tokens(text: str):
    """완전 토큰 매치 중 **필드 토큰**만 yield(구조 마커 제외).

    ``TOKEN_RE.finditer`` 를 그대로 쓰는 자리는 「완전 매치 집합」이 필요한 파편
    신고뿐이다 — 필드 토큰 후보를 세는 자리는 전부 이 필터를 통과한다.
    """
    for match in TOKEN_RE.finditer(text):
        if is_structure_sigil(match.group(1)):
            continue
        yield match


def iter_structure_markers(text: str):
    """완전 토큰 매치 중 **구조 마커**만 yield(필드 토큰의 정확한 여집합)."""
    for match in TOKEN_RE.finditer(text):
        if is_structure_sigil(match.group(1)):
            yield match


# ------------------------------------------------------------ Field ID 정규화
def collapse_field_id(raw: object) -> "str | None":
    if not isinstance(raw, str):
        return None
    value = " ".join(raw.split())
    return value or None


def normalize_field_id(raw: object) -> "str | None":
    """제품 Field ID를 정규화하고 빈 값·비문자열은 거절한다.

    앞뒤와 내부의 Unicode 공백을 접고, 전체를 감싼 ``{{...}}`` 표기 한 겹만
    벗긴 뒤 다시 공백을 접는다. 문자열 안쪽의 중괄호는 Field ID의 일부다.

    구간 마커의 id 도 같은 규칙을 탄다(:meth:`StructureReader._begin`) — 「id 는
    무엇인가」가 누름틀과 구간 표기에서 갈리면 같은 이름이 두 뜻을 갖는다.
    """
    name = collapse_field_id(raw)
    if name is None:
        return None
    if name.startswith("{{") and name.endswith("}}"):
        return collapse_field_id(name[2:-2])
    return name


# --------------------------------------------------- 구간 표기 문법 v1(S8-01 #832)
# 문법(#822 D2): 마커는 **자기 단위(HWPX=본문 직계 문단·TXT=줄)를 단독으로 차지**하고
# 쌍으로 범위를 감싼다 — ``{{#항목 <id> <label…>}}`` … ``{{/항목}}`` / ``{{#선택 <id>
# <label…>}}`` … ``{{/선택}}``. 「선택」은 「항목」 직속만, 「항목」 중첩은 없다.
# 이 상태기계는 **읽기만** 한다 — 마커 소거 같은 변형은 매체별 컴파일러 몫이다.
SLOT_KEYWORD = "항목"
OPTION_KEYWORD = "선택"
STRUCTURE_KEYWORDS = (SLOT_KEYWORD, OPTION_KEYWORD)


class StructureDiagnosticKind(StrEnum):
    """구간 표기 진단의 안정 식별자 — 상위 링이 문안 대신 이 값으로 분기한다."""

    UNBALANCED_MARKER = "unbalanced_marker"
    CROSSED_RANGE = "crossed_range"
    UNKNOWN_KEYWORD = "unknown_keyword"
    EMPTY_SLOT_ID = "empty_slot_id"
    EMPTY_OPTION_ID = "empty_option_id"
    DUPLICATE_SLOT_ID = "duplicate_slot_id"
    DUPLICATE_OPTION_ID = "duplicate_option_id"
    OPTION_OUTSIDE_SLOT = "option_outside_slot"
    NESTED_SLOT = "nested_slot"
    NESTED_OPTION = "nested_option"
    MARKER_IN_TABLE = "marker_in_table"
    MARKER_NOT_TOP_LEVEL = "marker_not_top_level"
    MARKER_NOT_ALONE = "marker_not_alone"
    EMPTY_RANGE = "empty_range"
    END_MARKER_EXTRA_TEXT = "end_marker_extra_text"


@dataclass(frozen=True)
class StructureDiagnostic:
    """표기 이상 1건 — ``kind`` 는 안정 식별자, ``message`` 는 한국어 재진술."""

    kind: StructureDiagnosticKind
    message: str
    context: str

    def to_dict(self) -> dict:
        return {"kind": str(self.kind), "message": self.message, "context": self.context}


@dataclass(frozen=True)
class StructureSummary:
    """확인 왕복 원료 — 「항목 n·선택 m·누름틀 k」 + 마커 총수.

    ``markers`` 는 이 문서에서 발견된 **완전 구조 마커 토큰의 총수**다(유효·무효 불문:
    표 셀 안·중첩 문단·짝이 안 맞는 마커도 전부 센다). ``slots``/``options`` 는 진단이
    없을 때만 신뢰할 수 있는 **선언** 수라, 「표기가 아직 남아 있는가」를 그것으로 물으면
    깨진 표기가 0 으로 보인다 — 그 질문의 단일 출처가 이 수치다(S8-04 #835). 마커를 세는
    코드는 :func:`iter_structure_markers` 를 도는 매체 어댑터뿐이고 그것들은
    :meth:`StructureReader.note_markers` 하나로 누적한다 — 상태·admission 은 이 값
    (또는 그 파생)을 **소비만** 한다.
    """

    slots: int
    options: int
    fields: int
    markers: int

    def to_dict(self) -> dict:
        return {
            "slots": self.slots,
            "options": self.options,
            "fields": self.fields,
            "markers": self.markers,
        }


#: 배치 값의 ``kind`` 어휘 — 상위 링이 문안 대신 이 값으로 분기한다(매체 공용).
PLACEMENT_SLOT = "slot"
PLACEMENT_OPTION = "option"


@dataclass
class _OpenRange:
    """열려 있는 범위의 진행 상태 — 닫힐 때 Slot/SlotOption 으로 확정된다.

    ``entry``·``begin_index`` 는 배치의 절반이다 — 닫는 마커를 만나야 나머지 절반이
    정해지므로 여는 시점에 함께 붙들어 둔다(``entry`` 는 여러 content XML 을 가진
    매체만 쓰고 TXT 는 빈 문자열이다).
    ``first_content``/``last_content`` 는 이 범위가 실제로 감싼 **내용 단위**의 처음과
    끝이다(마커 단위는 내용이 아니다).
    """

    id: str
    label: str
    context: str
    entry: str
    begin_index: int
    content: int = 0
    first_content: "int | None" = None
    last_content: "int | None" = None

    def note_content(self, index: int) -> None:
        """내용 단위 1개의 위치를 범위 경계에 반영한다."""
        if self.first_content is None:
            self.first_content = index
        self.last_content = index


#: 닫힌 범위 1건을 매체 좌표 값으로 만드는 factory. 코어가 keyword 로만 부른다 —
#: ``kind``·``opened``·``slot_id``·``option_id``·``end_index``·``content_start``·
#: ``content_end``. 내용 경계는 폴백까지 **코어가 계산한 결과**다.
PlacementFactory = Callable[..., object]


class StructureReader:
    """마커 스트림을 받아 선언 구조와 진단을 누적하는 상태기계(무변형).

    조용히 무시하는 경로 0 — 자격을 잃은 마커는 「없던 것」이 되지 않고 반드시
    진단 1건을 남긴다.

    매체 어댑터가 단위(HWPX=문단·TXT=줄)마다 부르는 것은 네 가지다:
    :meth:`position`(좌표) → :meth:`note_markers`(마커 총수, **자격 판정 앞**) →
    :meth:`count_content` 또는 :meth:`read_marker`(전이). 자격을 잃은 마커의 진단
    문안만 매체가 :meth:`note` 로 직접 남긴다(「문단」/「줄」 처럼 매체 명사가 드는
    자리는 거기뿐이다).
    """

    def __init__(self, *, scope: str, placement: PlacementFactory) -> None:
        self.slots: "list[Slot]" = []
        self.diagnostics: "list[StructureDiagnostic]" = []
        self.placements: "list" = []
        # 본 마커 토큰의 총수(유효·무효 불문) — 「표기가 아직 남아 있는가」의 단일 출처.
        # 자격을 잃어 진단만 남은 마커도 문서에는 그대로 있으므로 함께 센다.
        self.markers = 0
        self._scope = scope
        self._make_placement = placement
        self._slot: "_OpenRange | None" = None
        self._option: "_OpenRange | None" = None
        self._options: "list[SlotOption]" = []
        self._option_placements: "list" = []
        self._seen_slot_ids: "set[str]" = set()
        self._entry = ""
        self._index = -1

    # ---------------------------------------------------------------- 진단
    def note(self, kind: StructureDiagnosticKind, message: str, context: str) -> None:
        """진단 1건을 남긴다 — 매체 명사가 드는 문안은 어댑터가 직접 부른다."""
        self.diagnostics.append(StructureDiagnostic(kind, message, context))

    # ---------------------------------------------------------------- 입력
    def position(self, *, entry: str = "", index: "int | None" = None) -> None:
        """다음 단위의 좌표를 세운다. ``index`` 가 ``None`` 이면 직전 좌표를 유지한다.

        HWPX 는 본문 직계가 아닌 문단에서 번호를 올리지 않으므로 그 경우 ``None`` 을
        준다 — 배치 좌표는 **번호를 받은 단위**만 가리켜야 한다.
        """
        self._entry = entry
        if index is not None:
            self._index = index

    def note_markers(self, count: int) -> None:
        """이 단위에서 발견한 구조 마커 토큰 수를 누적한다 — **자격 판정 앞**."""
        self.markers += count

    def count_content(self) -> None:
        """내용 단위 1개 누적 — 「선택」이 열려 있으면 그쪽이 먼저 가져간다.

        「비었는가」 판정은 가장 안쪽 범위 하나만 세지만, **배치 경계**는 열려 있는
        범위 전부가 함께 넓힌다 — 선택 안의 단위도 그 선택을 품은 항목의 내용이다.
        """
        if self._option is not None:
            self._option.content += 1
        elif self._slot is not None:
            self._slot.content += 1
        for opened in (self._slot, self._option):
            if opened is not None:
                opened.note_content(self._index)

    def read_marker(self, raw: str, context: str) -> None:
        """단독으로 선 마커 1개의 본문(``{{ }}`` 안쪽)을 읽어 전이한다."""
        body = raw.lstrip()
        sigil, rest = body[0], body[1:].strip()
        parts = rest.split(None, 1)
        keyword = parts[0] if parts else ""
        tail = parts[1] if len(parts) > 1 else ""
        if keyword not in STRUCTURE_KEYWORDS:
            self.note(
                StructureDiagnosticKind.UNKNOWN_KEYWORD,
                f"알 수 없는 구간 키워드입니다: 「{keyword or '(없음)'}」 — 「항목」·「선택」만 "
                "쓸 수 있습니다.",
                context,
            )
            return
        if sigil == "#":
            self._begin(keyword, tail, context)
        else:
            self._end(keyword, tail, context)

    def close_entry(self) -> None:
        """스캔 단위 하나의 끝 — 닫히지 않은 범위를 불균형으로 신고한다.

        **범위는 한 ``scope`` 안에서 닫혀야 한다.** HWPX 에서 그 단위는 content XML
        이다(쓰기 커널의 region 이 한 XML 안에 사는 단위라, 파일 경계를 넘어 짝지어진
        범위는 컴파일할 수 없다 — 그런 구조를 「균형」으로 통과시키면 진단 계층이
        조용히 틀린다). TXT 에서는 파일 하나다. 그래서 짝짓기는 그 단위마다 닫고,
        id 중복 검사와 누적 결과만 문서 전역이다.
        """
        if self._option is not None:
            self.note(
                StructureDiagnosticKind.UNBALANCED_MARKER,
                f"「선택 {self._option.id}」 범위가 열린 채 {self._scope} 끝났습니다 — "
                "닫는 마커가 없습니다(범위는 한 파일 안에서 닫혀야 합니다).",
                self._option.context,
            )
            self._option = None
        if self._slot is not None:
            self.note(
                StructureDiagnosticKind.UNBALANCED_MARKER,
                f"「항목 {self._slot.id}」 범위가 열린 채 {self._scope} 끝났습니다 — "
                "닫는 마커가 없습니다(범위는 한 파일 안에서 닫혀야 합니다).",
                self._slot.context,
            )
            self._slot = None
            self._options = []
            self._option_placements = []

    # ------------------------------------------------------------ 내부 전이
    def _placement(
        self,
        kind: str,
        opened: _OpenRange,
        slot_id: str,
        option_id: "str | None",
    ):
        """닫는 마커 위치(``self._index``)를 붙여 배치 1건을 확정한다.

        내용 경계가 비어 있는 경우(``EMPTY_RANGE`` 진단이 이미 선 경우)에만 마커
        사이 전체로 되돌린다 — 그때 배치는 어차피 신뢰 대상이 아니다. 이 폴백은
        매체가 아니라 **코어**가 계산한다(두 매체가 빈 범위를 다르게 배치하지 않게).
        """
        return self._make_placement(
            kind=kind,
            opened=opened,
            slot_id=slot_id,
            option_id=option_id,
            end_index=self._index,
            content_start=(
                opened.begin_index + 1
                if opened.first_content is None
                else opened.first_content
            ),
            content_end=(
                self._index - 1
                if opened.last_content is None
                else opened.last_content
            ),
        )

    def _begin(self, keyword: str, tail: str, context: str) -> None:
        parts = tail.split(None, 1)
        ident = normalize_field_id(parts[0] if parts else "")
        label = " ".join(parts[1].split()) if len(parts) > 1 else ""
        if ident is None:
            kind = (
                StructureDiagnosticKind.EMPTY_SLOT_ID
                if keyword == SLOT_KEYWORD
                else StructureDiagnosticKind.EMPTY_OPTION_ID
            )
            self.note(kind, f"「{keyword}」 마커에 id 가 없습니다 — id 는 필수입니다.", context)
            return
        if keyword == SLOT_KEYWORD:
            self._begin_slot(ident, label, context)
        else:
            self._begin_option(ident, label, context)

    def _begin_slot(self, ident: str, label: str, context: str) -> None:
        if self._slot is not None:
            self.note(
                StructureDiagnosticKind.NESTED_SLOT,
                f"「항목 {self._slot.id}」 안에서 다시 「항목 {ident}」 을 열었습니다 — "
                "항목 중첩은 없습니다.",
                context,
            )
            return
        if ident in self._seen_slot_ids:
            self.note(
                StructureDiagnosticKind.DUPLICATE_SLOT_ID,
                f"같은 문서에서 항목 id 「{ident}」 가 두 번 선언됐습니다.",
                context,
            )
        self._seen_slot_ids.add(ident)
        self._slot = _OpenRange(ident, label, context, self._entry, self._index)
        self._options = []
        self._option_placements = []

    def _begin_option(self, ident: str, label: str, context: str) -> None:
        if self._slot is None:
            self.note(
                StructureDiagnosticKind.OPTION_OUTSIDE_SLOT,
                f"「선택 {ident}」 이 항목 범위 밖에 있습니다 — 선택은 항목 직속만 가능합니다.",
                context,
            )
            return
        if self._option is not None:
            self.note(
                StructureDiagnosticKind.NESTED_OPTION,
                f"「선택 {self._option.id}」 이 닫히기 전에 「선택 {ident}」 을 열었습니다.",
                context,
            )
            return
        if any(option.id == ident for option in self._options):
            self.note(
                StructureDiagnosticKind.DUPLICATE_OPTION_ID,
                f"항목 「{self._slot.id}」 안에서 선택 id 「{ident}」 가 두 번 선언됐습니다.",
                context,
            )
        self._option = _OpenRange(ident, label, context, self._entry, self._index)

    def _end(self, keyword: str, tail: str, context: str) -> None:
        if tail.strip():
            self.note(
                StructureDiagnosticKind.END_MARKER_EXTRA_TEXT,
                f"닫는 「{keyword}」 마커에 남은 텍스트가 있습니다: 「{' '.join(tail.split())}」 — "
                "닫는 마커는 키워드만 가집니다.",
                context,
            )
        if keyword == OPTION_KEYWORD:
            if self._option is None:
                self.note(
                    StructureDiagnosticKind.UNBALANCED_MARKER,
                    "여는 「선택」 마커 없이 닫는 「선택」 마커가 나왔습니다.",
                    context,
                )
                return
            self._close_option(context)
            return
        if self._slot is None:
            self.note(
                StructureDiagnosticKind.UNBALANCED_MARKER,
                "여는 「항목」 마커 없이 닫는 「항목」 마커가 나왔습니다.",
                context,
            )
            return
        if self._option is not None:
            self.note(
                StructureDiagnosticKind.CROSSED_RANGE,
                f"「선택 {self._option.id}」 이 닫히기 전에 「항목 {self._slot.id}」 이 "
                "닫혔습니다 — 범위가 교차합니다.",
                context,
            )
            self._close_option(context)
        slot = self._slot
        if slot.content == 0:
            self.note(
                StructureDiagnosticKind.EMPTY_RANGE,
                f"「항목 {slot.id}」 범위에 내용 문단이 없습니다.",
                context,
            )
        self.slots.append(Slot(id=slot.id, options=tuple(self._options), label=slot.label or None))
        # 배치는 컴파일 순서대로 쌓는다 — 항목이 먼저 서야 그 안에 선택이 들어간다.
        self.placements.append(self._placement(PLACEMENT_SLOT, slot, slot.id, None))
        self.placements.extend(self._option_placements)
        self._slot = None
        self._options = []
        self._option_placements = []

    def _close_option(self, context: str) -> None:
        option = self._option
        assert option is not None  # 호출자가 열림을 확인한 뒤에만 부른다
        if option.content == 0:
            self.note(
                StructureDiagnosticKind.EMPTY_RANGE,
                f"「선택 {option.id}」 범위에 내용 문단이 없습니다.",
                context,
            )
        self._options.append(
            SlotOption(id=option.id, order=len(self._options), label=option.label or None)
        )
        assert self._slot is not None  # 선택은 항목 직속에서만 열린다
        self._option_placements.append(
            self._placement(PLACEMENT_OPTION, option, self._slot.id, option.id)
        )
        self._option = None
        if self._slot is not None:
            # 닫힌 선택 범위 자체가 항목의 내용 1건이다(빈 항목 오판 방지).
            self._slot.content += 1
