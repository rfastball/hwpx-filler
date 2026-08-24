"""TXT 구간 표기 스캐너 — 줄 기반(S10-01 #858).

TXT 템플릿에서 S8 이 세운 **구간 표기 문법 v1**(``{{#항목 <id> <label…>}}`` …
``{{/항목}}`` / ``{{#선택 <id> <label…>}}`` … ``{{/선택}}``)을 읽어 선언 구조와 진단을
낸다. **무변형** — 입력 문자열을 읽기만 하고 마커를 지우거나 접지 않는다(생애주기·
admission 은 S10-02 소관).

**HWPX 와 같은 몸통·다른 자격.** 전이·진단 어휘·id 규칙은 lxml-free 코어
:mod:`~hwpxfiller.domain.structure_scan` 이 한 몸통으로 소유한다 — 그래야 같은 선언이
두 매체에서 **같은 Slot** 으로 복원된다(그 동등성이 이 슬라이스의 검증 축이다).
갈리는 것은 매체가 물을 수 있는 **자격**뿐이다:

- HWPX 의 「본문 직계 문단 단독」 술어는 여기서 **「줄 단독」** 이 된다. TXT 에는 문단
  트리가 없으므로 ``MARKER_IN_TABLE``·``MARKER_NOT_TOP_LEVEL`` 은 **생성 경로 자체가
  없다**(조용히 통과시키는 것이 아니라 물음이 성립하지 않는다).
- 좌표는 ``str.splitlines()`` 의 **0-기반 줄 번호**이고 배치 타입도 따로 선다
  (:class:`TextStructurePlacement`) — #856 D2. HWPX 배치의 인덱스는 본문 직계 ``hp:p``
  순번이자 쓰기 커널 bookmark 주소라, 같은 이름에 다른 뜻을 실으면 매체를 오간 좌표가
  조용히 틀린다.
- 닫히지 않은 범위의 ``scope`` 는 「파일」이다(HWPX 는 「content XML」).

빈 줄도 **내용 줄**로 센다 — HWPX 스캐너가 빈 문단을 내용으로 세는 것과 동형이라,
같은 선언의 「비었는가」 판정이 매체를 건너도 뒤집히지 않는다.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from .slot import Slot
from .structure_scan import (
    CONTEXT_MAX,
    PLACEMENT_OPTION,
    StructureDiagnostic,
    StructureDiagnosticKind,
    StructureReader,
    StructureSummary,
    iter_structure_markers,
)
from .text_render import template_fields


@dataclass(frozen=True)
class TextStructurePlacement:
    """범위 1건의 **0-기반 줄 번호** 배치.

    HWPX 의 :class:`~hwpxfiller.domain.authoring.StructurePlacement` 와 좌표계를
    **공유하지 않는다**(#856 D2): 그쪽 인덱스는 본문 직계 ``hp:p`` 순번이고 쓰기 커널
    ``hwpxcore.bookmark_region`` 이 받는 주소지만, TXT 에는 문단 트리도 그 커널도 없다.
    한 타입에 두 좌표계를 실으면 매체를 오간 배치가 조용히 틀리므로 타입을 가른다.

    ``content_start``/``content_end`` 는 이 범위의 **내용 줄** 처음과 끝(포함)이다 —
    마커 줄은 내용이 아니다. 내용이 하나도 없으면 마커 사이 전체
    (``begin_marker_line + 1`` … ``end_marker_line - 1``)로 되돌아가지만, 그때는
    ``EMPTY_RANGE`` 진단이 이미 서 있어 배치가 신뢰 대상이 아니다.
    """

    kind: str
    slot_id: str
    option_id: "str | None"
    begin_marker_line: int
    end_marker_line: int
    content_start: int
    content_end: int

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "slot_id": self.slot_id,
            "option_id": self.option_id,
            "begin_marker_line": self.begin_marker_line,
            "end_marker_line": self.end_marker_line,
            "content_start": self.content_start,
            "content_end": self.content_end,
        }


@dataclass(frozen=True)
class TextStructureScan:
    """TXT 구간 표기 스캔 결과(무변형).

    ``slots`` 는 **진단이 하나도 없을 때만 신뢰 대상**이다. 표기가 깨진 템플릿에서는
    파서가 복원할 수 있었던 부분 구조만 담기므로 선언 의도와 다를 수 있다. 그래서
    소비자는 **``diagnostics`` 가 1건 이상이면 변환 불가**로 판정하고 ``slots`` 를
    쓰지 않는다 — 조용히 추측해 반쪽 구조를 만들지 않는다.

    ``placements`` 도 **같은 조건**을 진다. 배치는 ``slots`` 의 줄 좌표 얼굴이라
    선언이 못 미더우면 좌표도 못 미덥다. 순서는 HWPX 와 같다 — 항목 1건 다음에 그
    항목의 선택들이 온다.
    """

    slots: "tuple[Slot, ...]"
    diagnostics: "tuple[StructureDiagnostic, ...]"
    summary: StructureSummary
    placements: "tuple[TextStructurePlacement, ...]" = ()

    def to_dict(self) -> dict:
        return {
            "slots": [
                {
                    "id": slot.id,
                    "label": slot.label or "",
                    "options": [
                        {"id": option.id, "label": option.label or ""}
                        for option in slot.options
                    ],
                }
                for slot in self.slots
            ],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "summary": self.summary.to_dict(),
            "placements": [p.to_dict() for p in self.placements],
        }


class TextStructureProjectionError(ValueError):
    """선택 투영 불가 — 스캔 진단이 있어 좌표를 믿을 수 없다.

    :class:`TextStructureScan` 의 계약("진단 1건 이상이면 ``slots``/``placements`` 는 신뢰
    대상이 아니다")을 투영 쪽에서 집행한다. 깨진 표기를 「보이는 줄」로 접으면 사용자가 고른
    적 없는 내용이 사라지거나 고르지 않은 내용이 남는다 — 조용히 반쪽을 그리느니 거절하고
    호출자가 원문을 그대로 들게 한다.
    """


def marker_lines(scan: TextStructureScan) -> "frozenset[int]":
    """구간 마커(여는·닫는) 줄 번호 전부 — 표시 투영과 물질화 2단계의 **공통 원천**.

    ``scan.summary.markers`` 는 자격 거절된 마커까지 세지만(파일에 남아 있으므로) 여기서 내는
    것은 **짝지어진 범위의 경계 줄**이다. 진단 0 인 스캔에서는 둘이 같은 집합을 가리킨다 —
    진단이 있으면 좌표 자체가 신뢰 대상이 아니라 소비자가 먼저 거절한다.
    """
    lines: "set[int]" = set()
    for placement in scan.placements:
        lines.add(placement.begin_marker_line)
        lines.add(placement.end_marker_line)
    return frozenset(lines)


def unselected_option_lines(
    scan: TextStructureScan, selected: "Mapping[str, Collection[str]]"
) -> "frozenset[int]":
    """고르지 않은 「선택」 범위가 차지한 줄 전부 — **자기 마커 줄까지 포함**한다.

    표시 투영(:func:`visible_lines`)은 마커를 어차피 전부 숨기므로 경계를 포함하든 말든 같은
    그림을 낸다. 물질화는 다르다: 1단계가 complement 를 지운 **직후 재스캔**이 구조 검증의
    자리이고, 그때 지워진 선택의 마커가 남아 있으면 「남은 Option 집합 == authorized」라는
    술어가 성립하지 않는다(지운 것이 여전히 선언돼 있고, 게다가 빈 범위가 된다). 그래서 제거
    단위는 선언 전체다 — 「항목」 마커는 그대로 남아 1단계 재스캔이 구조를 볼 수 있다.

    ``selected`` 는 항목 id → 고른 선택 id 들이다. 없는 키는 「아무것도 안 골랐다」이고 그
    항목의 선택 범위는 전부 여기 든다(:func:`visible_lines` 와 같은 규율).
    """
    lines: "set[int]" = set()
    for placement in scan.placements:
        if placement.kind != PLACEMENT_OPTION:
            continue
        if placement.option_id in selected.get(placement.slot_id, ()):
            continue
        lines.update(
            range(placement.begin_marker_line, placement.end_marker_line + 1)
        )
    return frozenset(lines)


def drop_lines(text: str, lines: "Collection[int]") -> str:
    """``lines`` 의 0-기반 줄만 뺀 텍스트(무변형 — 남는 줄은 줄 끝 문자까지 원문 그대로).

    ``keepends`` 로 이어붙이므로 CRLF 템플릿이 이 연산을 지나며 조용히 줄바꿈을 갈아입지
    않는다(:func:`project_selected_text` 와 같은 규율).
    """
    drop = set(lines)
    pieces = text.splitlines(keepends=True)
    return "".join(p for i, p in enumerate(pieces) if i not in drop)


def visible_lines(
    text: str,
    scan: TextStructureScan,
    selected: "Mapping[str, Collection[str]]",
) -> "tuple[int, ...]":
    """선택을 반영했을 때 **보이는 줄**의 0-기반 번호(오름차순, 무변형).

    규칙 넷이 전부다:

    - 구간 마커 줄(여는·닫는)은 전부 숨는다 — 마커는 저작 표기이지 내용이 아니다.
    - 고른 「선택」 범위의 내용 줄은 보인다.
    - 고르지 않은 「선택」 범위의 내용 줄은 숨는다.
    - 어느 항목 밖의 줄과 항목 직속(선택 밖) 줄은 언제나 보인다 — 항목을 열었다는 것이
      그 안의 공통 문구까지 고르게 만들지는 않는다.

    ``selected`` 는 항목 id → 고른 선택 id 들이다. **없는 키는 「아무것도 안 골랐다」**이고
    그때 그 항목의 선택 범위는 전부 숨는다(선택 1개짜리 항목도 자동 선택하지 않는다 —
    :func:`~hwpxfiller.domain.slot_selection.evaluate_slot` 과 같은 규율).

    진단이 1건이라도 있으면 :class:`TextStructureProjectionError` 다(fail-closed).

    숨김 집합은 :func:`marker_lines` 와 :func:`unselected_option_lines` 의 합집합이다 — 물질화
    (:mod:`hwpxfiller.external.text_materialization_runner`)가 두 단계로 나눠 쓰는 바로 그
    두 집합이라, 「보이는 것」과 「나가는 것」이 **같은 원천**에서 나온다(L22).
    """
    if scan.diagnostics:
        raise TextStructureProjectionError(
            f"구간 표기 진단이 {len(scan.diagnostics)}건 있어 선택을 반영할 수 없다"
        )
    hidden = marker_lines(scan) | unselected_option_lines(scan, selected)
    return tuple(i for i in range(len(text.splitlines())) if i not in hidden)


def project_selected_text(
    text: str,
    scan: TextStructureScan,
    selected: "Mapping[str, Collection[str]]",
) -> str:
    """``text`` 에서 :func:`visible_lines` 가 남긴 줄만 이어붙인 투영 텍스트(무변형).

    줄 끝 문자는 **원문 그대로** 옮긴다(``keepends``) — ``"\\n"`` 으로 다시 이으면 CRLF
    템플릿이 투영을 지날 때마다 조용히 줄바꿈을 갈아입는다.
    """
    pieces = text.splitlines(keepends=True)
    return "".join(pieces[i] for i in visible_lines(text, scan, selected))


def _text_placement(
    *,
    kind: str,
    opened,
    slot_id: str,
    option_id: "str | None",
    end_index: int,
    content_start: int,
    content_end: int,
) -> TextStructurePlacement:
    """코어가 확정한 범위 1건을 **줄 좌표** 배치로 성형한다(매체 주입분)."""
    return TextStructurePlacement(
        kind=kind,
        slot_id=slot_id,
        option_id=option_id,
        begin_marker_line=opened.begin_index,
        end_marker_line=end_index,
        content_start=content_start,
        content_end=content_end,
    )


def scan_text_structure(text: str) -> TextStructureScan:
    """TXT 템플릿 문자열의 구간 표기를 읽어 선언 구조와 진단을 낸다(무변형).

    ``text`` 는 손대지 않는다 — 반환값만 낸다. 반환 계약은
    :class:`TextStructureScan` 이 진다: **진단 1건 이상이면 변환 불가**이고
    ``slots``/``placements`` 는 신뢰 대상이 아니다.
    """
    reader = StructureReader(scope="파일이", placement=_text_placement)
    for index, line in enumerate(text.splitlines()):
        reader.position(index=index)
        context = line.strip()[:CONTEXT_MAX]
        markers = list(iter_structure_markers(line))
        reader.note_markers(len(markers))  # 자격 판정 **앞** — 거절될 마커도 파일에 남아 있다
        if not markers:
            # 빈 줄도 내용이다(HWPX 가 빈 문단을 세는 것과 동형).
            reader.count_content()
            continue
        if len(markers) > 1:
            reader.note(
                StructureDiagnosticKind.MARKER_NOT_ALONE,
                "한 줄에 구간 마커가 2개 이상입니다 — 마커는 줄을 단독으로 차지해야 합니다.",
                context,
            )
            continue
        match = markers[0]
        if (line[: match.start()] + line[match.end() :]).strip():
            reader.note(
                StructureDiagnosticKind.MARKER_NOT_ALONE,
                "구간 마커가 다른 텍스트와 같은 줄에 있습니다 — 마커는 줄을 단독으로 "
                "차지해야 합니다.",
                context,
            )
            continue
        reader.read_marker(match.group(1), context)
    # 짝짓기는 파일 경계에서 닫는다 — 열린 채 끝난 범위는 UNBALANCED_MARKER 다.
    reader.close_entry()
    return TextStructureScan(
        slots=tuple(reader.slots),
        diagnostics=tuple(reader.diagnostics),
        summary=StructureSummary(
            slots=len(reader.slots),
            options=sum(len(slot.options) for slot in reader.slots),
            # 「누름틀 k」는 렌더가 실제로 채울 필드의 단일 출처(sigil 보호된
            # ``template_fields``)에서 센다 — 여기서 토큰을 다시 세지 않는다.
            fields=len(template_fields(text)),
            markers=reader.markers,
        ),
        placements=tuple(reader.placements),
    )
