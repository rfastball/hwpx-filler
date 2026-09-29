"""Pure template authoring commands over the existing TXT grammar.

Positions at this public boundary are UTF-16 offsets, matching CodeMirror.
The existing structure scanner and renderer remain the semantic authority.

This module also owns the **media-shared vocabulary** of the authoring surface:
command types and display names, availability reasons, undo labels, problem
taxonomy constants, the structured refusals (:class:`NameConflict`,
:class:`CascadeRequired`, :class:`InvalidName`), the field-name suggestion and the
confirmation tier of a previewed command. The HWPX adapter imports them so both media return
the same words and shapes; the frontend never re-decides any of it.
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .job import MISSING_MARKER
from .lint import near_duplicate_pairs
from .structure_scan import (
    CONTEXT_MAX,
    PLACEMENT_OPTION,
    PLACEMENT_SLOT,
    StructureDiagnosticKind,
    iter_structure_markers,
    normalize_field_id,
)
from .text_render import iter_field_token_matches
from .text_structure import (
    marker_lines,
    scan_text_token_spans,
    scan_text_structure,
    unselected_option_lines,
)

# --------------------------------------------------------------- shared vocabulary
#: Command types in the fixed order the frontend renders them (F40/P07).
COMMAND_TYPES: tuple[str, ...] = (
    "create_field", "create_slot", "create_option",
    "rename_field", "relink_field", "unset_field",
    "rename_slot", "rename_option", "adjust_range",
    "unwrap", "delete", "duplicate", "move",
)
#: Display names — the same words the frontend COMMANDS list shows.
COMMAND_NAMES: dict[str, str] = {
    "create_field": "필드로 만들기", "create_slot": "항목으로 만들기", "create_option": "선택으로 만들기",
    "rename_field": "필드 이름 변경", "relink_field": "필드 연결 변경", "unset_field": "필드 의미 해제",
    "rename_slot": "항목 속성 변경", "rename_option": "선택 속성 변경", "adjust_range": "범위 조정",
    "unwrap": "의미만 해제", "delete": "내용까지 삭제", "duplicate": "복제", "move": "이동",
}
FIELD_COMMANDS = frozenset({"create_field", "rename_field", "relink_field", "unset_field"})
REGION_COMMANDS = frozenset({"rename_slot", "rename_option", "adjust_range", "unwrap", "delete",
                             "duplicate", "move"})

# Availability reasons (spec §6.1 / §13 sentences where they exist).
REASON_INVALID_SELECTION = "고른 위치가 올바르지 않습니다."
REASON_MULTI_REGION = "고른 범위가 여러 독립 영역에 걸쳐 있습니다. 한 범위를 고르세요."
REASON_OPTION_OUTSIDE_SLOT = "선택은 항목 안에 만들 수 있습니다. 먼저 항목 안의 내용을 고르세요."
REASON_NEED_FIELD = "필드를 고르세요."
REASON_ONE_FIELD = "필드를 하나만 고르세요."
REASON_NEED_REGION = "항목이나 선택 영역을 고르세요."
REASON_NEED_OPTION = "선택 영역을 고르세요."
REASON_REGION_OVERLAP = "고른 범위가 기존 영역과 겹칩니다. 범위를 다시 고르세요."
REASON_FIELD_OVERLAP = "고른 범위에 기존 필드가 포함되어 있습니다."
REASON_STRUCTURE_FIRST = "구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요."
REASON_NO_CONTENT_LINE = "고를 내용 줄이 없습니다."
REASON_NEED_OCCURRENCE = "필드 사용 위치를 하나 고르세요."
_FIELD_NOT_FOUND = "필드를 찾을 수 없습니다."
REASON_NEED_RANGE = "문서에서 범위를 고르세요."
ALTERNATIVE_CREATE_SLOT = {"label": "먼저 항목 만들기", "command_type": "create_slot"}
CASCADE_MESSAGE = "항목 의미를 해제하면 하위 선택 의미도 해제됩니다. 함께 해제를 확인하세요."

# Problem taxonomy (spec §7.1–7.2).
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
CATEGORY_STRUCTURE = "structure"
CATEGORY_COMPATIBILITY = "compatibility"
CATEGORY_AUTHORING = "authoring"
ACTION_NAVIGATE_LABEL = "원문으로 이동"
# Authoring lint (IDE-05 #1051) — warnings that never change draft/ready. The row's target cell shows the
# name, so the sentences carry none.
MESSAGE_NEAR_DUPLICATE = "공백만 다른 필드 이름이 있습니다."
MESSAGE_STRAY_TOKEN = "평문으로 남은 필드 표기입니다."
KIND_NEAR_DUPLICATE = "near_duplicate"
KIND_STRAY_TOKEN = "stray_token"
#: The one-token 누름틀 변환 (vocabulary `ui-style.md`: 평문 토큰의 누름틀 전환 → 누름틀 변환).
COMPILE_TOKEN = "compile_token"
COMPILE_TOKEN_LABEL = "누름틀 변환"
REASON_FIX_STALE = "이 문제의 자동 수정이 더는 적용되지 않습니다. 문제 목록을 다시 확인하세요."


class NameConflict(ValueError):
    """Renaming onto an existing field is never merged silently (AC08)."""

    def __init__(self, name: str, existing_count: int) -> None:
        self.name = name
        self.existing_count = existing_count
        self.message = f"‘{name}’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요."
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {"code": "name_conflict", "name": self.name,
                "existing_count": self.existing_count, "message": self.message}


class CascadeRequired(ValueError):
    """Unwrapping a slot that still owns options needs an explicit cascade (AC10)."""

    def __init__(self, children: list[dict]) -> None:
        self.children = children
        self.message = CASCADE_MESSAGE
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {"code": "cascade_required", "children": self.children, "message": self.message}


#: 필드 이름 문법 거절(§13) — 비었거나 문법 기호가 든 이름.
INVALID_FIELD_NAME = "필드 이름을 확인하세요. 비어 있거나 문법 기호가 포함되어 있습니다."
#: 항목·선택 식별자가 빈 거절 — 만들기와 속성 변경이 각자의 문장을 쓴다(HWPX 가 먼저 쓰던 그 문장).
REASON_NEED_IDENTIFIER = "항목이나 선택의 식별자를 입력하세요."
REASON_NEED_NEW_IDENTIFIER = "항목이나 선택의 새 식별자를 입력하세요."


class InvalidName(ValueError):
    """A name or identifier the grammar cannot carry — refused in place, not raised as an error (P-06).

    ``field`` names the input the sentence belongs to: ``"name"`` (필드 이름·표시 이름) or
    ``"identifier"`` (연결 식별자). The surface puts the sentence right under that input.
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"code": "invalid_name", "field": self.field, "message": self.message}


def region_identifier(raw: object, *, renaming: bool = False) -> str:
    """항목·선택 식별자 — 구간 표기로 되읽히는 값만 통과한다(두 매체 공유). 거절은 식별자 칸의 것이다."""
    from .authoring import marker_identifier

    if not isinstance(raw, str) or not raw.strip():
        raise InvalidName("identifier", REASON_NEED_NEW_IDENTIFIER if renaming else REASON_NEED_IDENTIFIER)
    try:
        return marker_identifier(raw)
    except ValueError as exc:
        raise InvalidName("identifier", str(exc)) from exc


def _region_label(raw: object) -> None:
    """항목·선택 표시 이름(이름 칸) — 되읽기 동등이 아니면 이름 칸의 거절이다."""
    from .authoring import marker_label

    try:
        marker_label(raw)
    except ValueError as exc:
        raise InvalidName("name", str(exc)) from exc


# --------------------------------------------------------------- field-name suggestion (P-06)
#: 제안 이름의 길이 상한 — 넘으면 라벨이 아니라 문장이다.
SUGGESTION_MAX = 20
_LABEL_END = re.compile(r"[:：]\s*$")
#: 라벨 토막을 끊는 앞 경계 — 앞 라벨의 쌍점, 필드 토큰의 끝, 탭.
_LABEL_BREAK = re.compile(r"[:：\t]|\}\}")
#: 앞 번호 머리 — 가. 1. 1) (1) (가) ① □ ○ - • 등. 여러 겹이면 차례로 뗀다.
_ENUMERATOR = re.compile(
    r"^(?:[가-힣]\.|\d+[.)]|\(\d+\)|\([가-힣]\)|[①-⑳㉠-㉻]"
    r"|[□■○●◦▪▫◆◇▶►※\-•·*])\s*")
_COLUMN_GAP = re.compile(r"\s{2,}")


def _syllable(token: str) -> bool:
    return len(token) == 1 and "가" <= token <= "힣"


def suggest_field_name(before: str, selected: str, existing: Iterable[str] = ()) -> str | None:
    """「라벨: 값」에서 값을 고르면 그 라벨을 필드 이름으로 제안한다(P-06 규칙 ①만).

    같은 문단(셀) 안에서 선택 앞 글자가 ``…라벨 :``/``：``(뒤 공백 허용)로 끝날 때만 제안한다.
    라벨은 앞 쌍점·필드 토큰·탭 뒤의 토막이다. 끝의 한 음절 토막이 둘 이상 이어지면(균등 배분
    띄어쓰기 「수  요  기  관」) 붙이고, 아니면 칸 사이 넓은 공백 뒤만 남긴 채 앞 번호 머리를
    떼고 공백을 접는다. 선택 문구 자체는 이름이 되지 않는다(값 문구가 이름이 되는 길 삭제).
    기존 필드 이름과 공백만 다르면 그 이름을 쓴다. 비거나 20자를 넘거나 문법이 거절하면 None.
    """
    if not isinstance(before, str) or not isinstance(selected, str) or not selected.strip():
        return None
    if "{{" in selected or "}}" in selected or "\n" in selected or "\r" in selected:
        return None
    if not _LABEL_END.search(before):
        return None
    segment = _LABEL_BREAK.split(_LABEL_END.sub("", before))[-1]
    tokens = segment.split()
    run = 0
    while run < len(tokens) and _syllable(tokens[len(tokens) - 1 - run]):
        run += 1
    if run >= 2:
        label = "".join(tokens[len(tokens) - run:])
    else:
        label = _COLUMN_GAP.split(segment.strip())[-1]
        previous = None
        while previous != label:
            previous, label = label, _ENUMERATOR.sub("", label, count=1)
        label = " ".join(label.split())
    if not label or len(label) > SUGGESTION_MAX:
        return None
    try:
        label = _identifier(label)
    except InvalidName:
        return None
    compact = "".join(label.split())
    return next((str(name) for name in existing if "".join(str(name).split()) == compact), label)


# --------------------------------------------------------------- confirmation tier (P-01)
#: 확인 등급 — ``none`` 은 미리보기를 받자마자 적용, ``enter`` 는 영향을 본 뒤 Enter 한 번 더,
#: ``button`` 은 위험 단추 누름으로만 적용한다. ui-style 의 계약 명령(이름 변경·범위 확장·삭제)은
#: 늘 ``enter`` 이상이다.
CONFIRM_NONE = "none"
CONFIRM_ENTER = "enter"
CONFIRM_BUTTON = "button"
_ENTER_COMMANDS = frozenset({"rename_field", "adjust_range", "move", "duplicate", "unwrap", "unset_field",
                             "relink_field", "paste", "repair_marker"})


def _identifier_changes(command: Mapping[str, object]) -> bool:
    action = command.get("type")
    own = "slot_id" if action == "rename_slot" else "option_id" if action == "rename_option" else None
    return own is not None and "id" in command and command["id"] != command.get(own)


def confirm_tier(command: Mapping[str, object], preview: Mapping[str, object],
                 impact: Mapping[str, object] | None = None) -> str:
    """미리보기 한 건의 확인 등급(P-01) — 두 매체가 같은 표를 쓴다. 표면은 이 값으로만 가른다."""
    action = command.get("type")
    impact = impact or {}
    if action == "delete" or (action == "unwrap" and (preview.get("requires_cascade") or command.get("cascade"))):
        return CONFIRM_BUTTON
    if action in _ENTER_COMMANDS or _identifier_changes(command) or preview.get("expanded"):
        return CONFIRM_ENTER
    # 여러 자리 명령(IDE-07): 같은 문구 N곳(``ranges``)은 포함 자리를 본 뒤 확정한다.
    if action == "create_field" and command.get("ranges"):
        return CONFIRM_ENTER
    if action == "create_field" and preview.get("links_existing"):
        return CONFIRM_ENTER
    field_delta = impact.get("field_delta")
    if isinstance(field_delta, Mapping) and field_delta.get("removed_fields"):
        return CONFIRM_ENTER
    structure_delta = impact.get("structure_delta")
    if impact.get("linked_jobs") and isinstance(structure_delta, Mapping) and any(structure_delta.values()):
        return CONFIRM_ENTER
    unverified = impact.get("impact_unverified")
    if isinstance(unverified, int) and unverified > 0:
        return CONFIRM_ENTER
    return CONFIRM_NONE


def created_target(command: Mapping[str, object], result: Mapping[str, Any]) -> dict | None:
    """만들기 명령이 적용 뒤 남길 대상(NG-14) — 결과 분석 안의 새 필드·항목·선택. 없으면 None."""
    action = command.get("type")
    if action == "create_field":
        name = normalize_field_id(command.get("name"))
        fields = result.get("fields") or []
        field = next((item for item in fields if isinstance(item, Mapping) and item.get("name") == name), None)
        occurrences = list((field or {}).get("occurrences") or [])
        if field is None or not occurrences:
            return None
        return {"kind": "field", "name": name, "count": field.get("count", len(occurrences)),
                "occurrences": occurrences, "location": occurrences[0]}
    if action in {"create_slot", "create_option"}:
        slot_id = command.get("id") if action == "create_slot" else command.get("slot_id")
        slots = result.get("slots") or []
        slot = next((item for item in slots if isinstance(item, Mapping) and item.get("id") == slot_id), None)
        if slot is None:
            return None
        if action == "create_slot":
            return {"kind": "slot", "slot_id": slot_id, "location": slot.get("location")}
        option = next((item for item in slot.get("options") or []
                       if isinstance(item, Mapping) and item.get("id") == command.get("id")), None)
        if option is None:
            return None
        return {"kind": "option", "slot_id": slot_id, "option_id": option["id"], "location": option.get("location")}
    return None


def _object_particle(name: str) -> str:
    if not name:
        return "을"
    code = ord(name[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return "을" if (code - 0xAC00) % 28 else "를"
    return "을(를)"


def _direction_particle(name: str) -> str:
    """방향 조사 「(으)로」 — 받침 없음·ㄹ 받침은 「로」, 그 밖의 받침은 「으로」(§13)."""
    code = ord(name[-1]) if name else 0
    if 0xAC00 <= code <= 0xD7A3:
        return "로" if (code - 0xAC00) % 28 in (0, 8) else "으로"
    return "(으)로"


def rename_field_message(affected: int, name: str) -> str:
    """전체 필드 이름 변경 미리보기의 문장(§13) — 조사는 새 이름의 끝소리로 고른다."""
    return f"현재 문서의 사용 위치 {affected}곳이 ‘{name}’{_direction_particle(name)} 변경됩니다."


#: 사용 위치·검색 결과 문맥에 싣는 앞뒤 본문 글자 수(§7.2·P10).
CONTEXT_SPAN = 12


def occurrence_context_parts(before: str, focus: str, after: str,
                             span: int = CONTEXT_SPAN) -> tuple[str, str, str]:
    """:func:`occurrence_context` 의 세 조각(앞·가운데·뒤) — 표면이 가운데를 강조해 같은 문맥의 두 자리를 가른다."""
    before, after = (re.sub(r"\s+", " ", part) for part in (before, after))
    lead = ("…" if len(before) > span else "") + before[-span:]
    trail = after[:span] + ("…" if len(after) > span else "")
    return lead, focus, trail


def occurrence_context(before: str, focus: str, after: str, span: int = CONTEXT_SPAN) -> str:
    """사용 위치 한 곳의 사람이 읽는 문맥 — 앞뒤 본문 몇 글자와 가운데 표지(§7.2·P10).

    필드 명령 문법·원문 표기는 싣지 않는다. 그것은 ``raw`` 와 원문 표기 패널의 몫이다.
    공백 연속은 한 칸으로 줄이고, 잘린 쪽에는 말줄임표를 둔다.
    """
    return "".join(occurrence_context_parts(before, focus, after, span))


def context_focus(parts: tuple[str, str, str]) -> dict:
    """문맥 문자열 안의 가운데 조각 위치(UTF-16) — 표면이 그 글자만 강조한다(판정 아님)."""
    lead = _unit_length(parts[0])
    return {"start": lead, "end": lead + _unit_length(parts[1])}


def humanize_field_tokens(text: str) -> str:
    """TXT 문맥 조각의 필드 토큰(``{{이름}}``)을 문법 없이 ``[이름]`` 으로 보인다."""
    parts: list[str] = []
    end = 0
    for match in iter_field_token_matches(text):
        parts.append(text[end:match.start()])
        parts.append(f"[{match.group(1).strip()}]")
        end = match.end()
    parts.append(text[end:])
    return "".join(parts)


def text_hit_context(source: str, start: int, end: int) -> str:
    """TXT 본문 검색 결과 한 건의 문맥 — 같은 줄의 앞뒤 본문과 찾은 글자(§6.3). 인자는 code point 위치다."""
    return "".join(text_hit_parts(source, start, end))


def text_hit_parts(source: str, start: int, end: int) -> tuple[str, str, str]:
    """:func:`text_hit_context` 의 세 조각(앞·찾은 글자·뒤)."""
    line_start = max(source.rfind("\n", 0, start), source.rfind("\r", 0, start)) + 1
    line_end = min((index for index in (source.find("\n", end), source.find("\r", end)) if index >= 0),
                   default=len(source))
    line = source[line_start:line_end]
    focus = source[start:end]
    # 찾은 글자가 필드 토큰 안에 있으면 토큰 전체를 표지로 보인다 — 문법 조각이 문맥에 새지 않게.
    for match in iter_field_token_matches(line):
        if match.start() < end - line_start and start - line_start < match.end():
            start, end = min(start, line_start + match.start()), max(end, line_start + match.end())
            focus = humanize_field_tokens(source[start:end])
    return occurrence_context_parts(humanize_field_tokens(source[line_start:start]), focus,
                                    humanize_field_tokens(source[end:line_end]))


def command_label(command: Mapping[str, object], target: object = None) -> str:
    """Human name of one authoring action for undo menus (F34, §9.3)."""
    action = str(command.get("type", ""))
    quoted = f"‘{target}’" if target not in (None, "") else ""
    if action == "create_field":
        name = str(command.get("name", ""))
        return f"‘{name}’{_object_particle(name)} {COMMAND_NAMES[action]}"
    if action in {"create_slot", "create_option"}:
        subject = str(target if target not in (None, "") else command.get("label") or command.get("id") or "")
        return f"‘{subject}’{_object_particle(subject)} {COMMAND_NAMES[action]}"
    if action == "rename_field":
        return f"{quoted} 이름 변경".strip()
    if action in {"unwrap", "delete", "duplicate", "move"}:
        noun = "선택" if command.get("kind") == "option" else "항목"
        return f"{quoted} {noun} {COMMAND_NAMES[action]}".strip()
    if action in COMMAND_NAMES:
        return f"{quoted} {COMMAND_NAMES[action]}".strip()
    if action == "repair_marker":
        return str(target or "마커 수정")
    if action == COMPILE_TOKEN:
        name = str(command.get("name", ""))
        return f"‘{name}’ {COMPILE_TOKEN_LABEL}"
    return action


def navigate_action(location: object) -> dict:
    return {"label": ACTION_NAVIGATE_LABEL, "kind": "navigate", "location": location}


def command_action(command: Mapping[str, object], label: str | None = None) -> dict:
    return {"label": label or COMMAND_NAMES.get(str(command.get("type")), str(command.get("type"))),
            "kind": "command", "command": dict(command)}


def _occurrence_location(media: str, occurrence: Mapping[str, object] | None) -> dict | None:
    """Where one field use sits, in the shape the problem rows navigate with (§7.2)."""
    if occurrence is None:
        return None
    if media == "txt":
        return {key: occurrence[key] for key in ("line", "start", "end") if key in occurrence}
    paragraph, anchor = occurrence.get("paragraph"), occurrence.get("anchor_paragraph")
    if type(paragraph) is not int:
        return {"entry": occurrence.get("entry"), "paragraph": anchor} if type(anchor) is int else None
    location: dict = {"entry": occurrence.get("entry"), "paragraph": paragraph}
    if occurrence.get("cell_path") is not None:
        location["cell_path"] = occurrence["cell_path"]
    if type(occurrence.get("start")) is int and type(occurrence.get("end")) is int:
        location.update(start=occurrence["start"], end=occurrence["end"])
    return location


def _relink_command(media: str, occurrence: Mapping[str, object], old: str, name: str) -> dict:
    if media == "txt":
        return {"type": "relink_field", "start": occurrence["start"], "end": occurrence["end"], "name": name}
    return {"type": "relink_field", "entry": occurrence.get("entry"), "occurrence": occurrence.get("occurrence"),
            "pairing_id": occurrence.get("pairing_id"), "old_name": old, "name": name}


def authoring_lint(media: str, analysis: dict) -> list[dict]:
    """Field names that differ only in whitespace (IDE-05 #1051) — the same judgment as `lint.near_duplicate_pairs`.

    One warning per pair. The target is the name with fewer uses (on a tie, the one that first appears later —
    the likelier typo). Its first use is where the row navigates; a one-use target also carries 「필드 연결 변경」
    onto the other name. `normalize_field_id` folds but keeps inner whitespace, so 「공고 명」 is a separate field.
    """
    by_name = {str(item.get("name")): item for item in analysis.get("fields", []) if isinstance(item, dict)}
    counts = {name: int(item.get("count", len(item.get("occurrences", [])))) for name, item in by_name.items()}
    problems: list[dict] = []
    for first, second in near_duplicate_pairs(list(by_name)):
        target, other = (first, second) if counts[first] < counts[second] else (second, first)
        occurrences = list(by_name[target].get("occurrences", []))
        location = _occurrence_location(media, occurrences[0] if occurrences else None)
        actions = [navigate_action(location)]
        if counts[target] == 1 and occurrences:
            actions.append(command_action(_relink_command(media, occurrences[0], target, other)))
        problems.append({"kind": KIND_NEAR_DUPLICATE, "severity": SEVERITY_WARNING,
                         "category": CATEGORY_AUTHORING, "message": MESSAGE_NEAR_DUPLICATE,
                         "target": target, "location": location, "actions": actions})
    return problems


def marker_target(context: str) -> str | None:
    """Identifier declared by a begin marker in a diagnostic context line, if any."""
    match = next(iter_structure_markers(context or ""), None)
    if match is None:
        return None
    tokens = match.group(1).split()
    return tokens[1] if tokens and tokens[0].startswith("#") and len(tokens) > 1 else None


def availability_entries(reasons: Mapping[str, str | None],
                         alternatives: Mapping[str, dict] | None = None) -> list[dict]:
    """Shape one entry per command type in the fixed order."""
    alternatives = alternatives or {}
    return [{"type": kind, "enabled": reasons.get(kind) is None, "reason": reasons.get(kind),
             "alternative": alternatives.get(kind) if reasons.get(kind) is not None else None}
            for kind in COMMAND_TYPES]


def shared_reasons(*, field_hits: list[str], target_kind: str | None, has_slot: bool,
                   structure_broken: bool) -> dict[str, str | None]:
    """Media-independent availability of field and region commands."""
    reasons: dict[str, str | None] = {}
    reasons["rename_field"] = (REASON_NEED_FIELD if not field_hits
                               else REASON_ONE_FIELD if len(set(field_hits)) > 1 else None)
    for kind in ("relink_field", "unset_field"):
        reasons[kind] = (REASON_NEED_FIELD if not field_hits
                         else REASON_ONE_FIELD if len(field_hits) > 1 else None)
    blocked = REASON_STRUCTURE_FIRST if structure_broken else None
    reasons["rename_slot"] = blocked or (None if has_slot else REASON_NEED_REGION)
    reasons["rename_option"] = blocked or (None if target_kind == "option" else REASON_NEED_OPTION)
    for kind in ("adjust_range", "unwrap", "delete", "duplicate", "move"):
        reasons[kind] = blocked or (None if target_kind else REASON_NEED_REGION)
    return reasons


#: Meaning elements chosen by identity (outline·search·match) rather than by a text range (§3.3).
TARGET_KINDS: frozenset[str] = frozenset({"field", "occurrence", "slot", "option"})


def target_availability(kind: str, *, name: str | None = None,
                        structure_broken: bool) -> list[dict]:
    """Availability for one meaning element chosen by identity, not by coordinates (§3.3·§6.1·§6.2).

    필드 전체는 이름 변경과 전체 의미 해제를 연다 — 연결 변경은 사용 위치 한 곳의 명령이다(U07).
    전체 의미 해제는 모든 사용 위치를 한 계획·한 실행 취소로 치환하는 전체 대상의 명령이다(IDE-06 P-20).
    사용 위치는 그 자리의 연결 변경·의미 해제와 필드 전체 이름 변경을 연다(§6.2 첫 행).
    항목·선택은 영역 명령을 연다. 대상은 글자 범위가 아니므로 만들기 명령은 필요한 범위를 안내한다.
    """
    if kind not in TARGET_KINDS:
        raise ValueError(REASON_INVALID_SELECTION)
    field = kind in {"field", "occurrence"}
    region = None if field else kind
    reasons = shared_reasons(field_hits=[name or ""] if field else [], target_kind=region,
                             has_slot=region is not None, structure_broken=structure_broken)
    if kind == "field":
        reasons["relink_field"] = REASON_NEED_OCCURRENCE
    reasons["create_field"] = REASON_FIELD_OVERLAP if field else REASON_NEED_RANGE
    if structure_broken:
        reasons["create_slot"] = reasons["create_option"] = REASON_STRUCTURE_FIRST
    else:
        reasons["create_slot"] = REASON_NEED_RANGE if field else REASON_REGION_OVERLAP
        reasons["create_option"] = (REASON_OPTION_OUTSIDE_SLOT if kind == "slot"
                                    else REASON_REGION_OVERLAP if kind == "option"
                                    else REASON_NEED_RANGE)
    return availability_entries(reasons)


def whole_field_unset(command: Mapping[str, object]) -> bool:
    """필드 전체(구조 목록의 필드 행 — ``occurrences`` 를 실은 대상)의 의미 해제인가(IDE-06 P-20).

    전체 대상은 이름(``old_name``)이 같은 모든 사용 위치를 한 계획으로 치환한다. 사용 위치 한 곳의
    해제는 좌표(TXT)나 차례(HWPX)로 그 자리만 고친다.
    """
    return command.get("type") == "unset_field" and isinstance(command.get("occurrences"), list)


def available_target_commands(media: str, content: str | object, kind: str,
                              name: str | None = None) -> list[dict]:
    """TXT availability for an identity-chosen target; structure errors come from the same scan."""
    if media != "txt" or not isinstance(content, str):
        raise ValueError(f"지원하지 않는 저작 형식입니다: {media}")
    return target_availability(kind, name=name,
                               structure_broken=bool(scan_text_structure(content).diagnostics))


def field_candidates(fields: list[dict]) -> list[dict]:
    return [{"name": item["name"], "count": item["count"]} for item in fields]


# ------------------------------------------------------------------- TXT media
def _unit_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _to_utf16(text: str, offset: int) -> int:
    return _unit_length(text[:offset])


def _from_utf16(text: str, offset: object) -> int:
    # ponytail: linear conversion is enough for ordinary templates; build an offset map if large documents make command latency visible.
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError(REASON_INVALID_SELECTION)
    units = 0
    for index, char in enumerate(text):
        if units == offset:
            return index
        units += _unit_length(char)
        if units > offset:
            raise ValueError("고른 위치가 문자 중간에 있습니다.")
    if units == offset:
        return len(text)
    raise ValueError("고른 위치가 문서 밖에 있습니다.")


def from_utf16(text: str, offset: object) -> int:
    """편집기 선택의 UTF-16 단위 위치 → code point 위치. 문자 중간·문서 밖·잘못된 값은 ValueError."""
    return _from_utf16(text, offset)


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


def _line_at(starts: list[int], offset: int) -> int:
    return max(0, next((i - 1 for i, start in enumerate(starts) if start > offset), len(starts) - 2))


def _line_range(text: str, start: int, end: int) -> tuple[int, int, int, int]:
    starts = _line_starts(text)
    if len(starts) == 1:
        raise ValueError(REASON_NO_CONTENT_LINE)
    first = _line_at(starts, start)
    last = _line_at(starts, max(start, end - 1))
    return first, last, starts[first], starts[last + 1]


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _identifier(raw: object) -> str:
    name = normalize_field_id(raw)
    if not name or "{{" in name or "}}" in name or "|" in name or name.startswith(("#", "/")):
        raise InvalidName("name", INVALID_FIELD_NAME)
    return name


def _marker(kind: str, identifier: object, label: object = None) -> str:
    from .authoring import begin_marker_text

    return begin_marker_text(kind, identifier, label)


def _end_marker(kind: str) -> str:
    from .authoring import end_marker_text

    return end_marker_text(kind)


def _occurrences(text: str) -> list[dict]:
    scan = scan_text_structure(text)
    starts = _line_starts(text)
    result = []
    for match in iter_field_token_matches(text):
        line = _line_at(starts, match.start())
        owner = next(
            (place for place in reversed(scan.placements)
             if place.begin_marker_line < line < place.end_marker_line),
            None,
        )
        name = match.group(1).strip()
        line_text = text.splitlines()[line]
        column = match.start() - starts[line]
        result.append({
            "name": name,
            "start": _to_utf16(text, match.start()),
            "end": _to_utf16(text, match.end()),
            "line": line,
            "slot_id": owner.slot_id if owner else None,
            "option_id": owner.option_id if owner else None,
            # 사람이 읽는 문맥은 필드 문법 없이 앞뒤 본문만(§7.2). 원문 줄은 raw 에 둔다.
            "context": occurrence_context(humanize_field_tokens(line_text[:column]), f"[{name}]",
                                          humanize_field_tokens(line_text[column + len(match.group(0)):])),
            "raw": {"text": line_text[:CONTEXT_MAX]},
        })
    return result


def _fields(text: str) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in _occurrences(text):
        grouped[item["name"]].append(item)
    return [{"name": name, "count": len(items), "occurrences": items}
            for name, items in grouped.items()]


def analyze(media: str, content: str | object) -> dict:
    """Return a JSON-ready semantic projection without changing the document."""
    if media != "txt":
        raise ValueError(f"지원하지 않는 저작 형식입니다: {media}")
    if not isinstance(content, str):
        raise TypeError("TXT content must be text")
    scan = scan_text_structure(content)
    starts = _line_starts(content)
    placements = [place.to_dict() | {
        "start": _to_utf16(content, starts[place.begin_marker_line]),
        "end": _to_utf16(content, starts[place.end_marker_line + 1]),
        "content_start_offset": _to_utf16(content, starts[place.content_start]),
        "content_end_offset": _to_utf16(content, starts[place.content_end + 1]),
    } for place in scan.placements]
    slots = scan.to_dict()["slots"]
    for slot in slots:
        slot["kind"] = "slot"
        slot["location"] = next((place for place in placements if place["kind"] == "slot"
                                 and place["slot_id"] == slot["id"]), None)
        for option in slot["options"]:
            option["kind"] = "option"
            option["slot_id"] = slot["id"]
            option["location"] = next((place for place in placements if place["kind"] == "option"
                                       and place["slot_id"] == slot["id"]
                                       and place["option_id"] == option["id"]), None)
    return {
        "fields": _fields(content),
        "slots": slots,
        "placements": placements,
        "spans": [{"kind": span.kind, "start": _to_utf16(content, span.start),
                   "end": _to_utf16(content, span.end), "source": span.source}
                  for span in scan_text_token_spans(content)],
        "diagnostics": [_diagnostic_entry(content, scan, item) for item in scan.diagnostics],
        "summary": scan.summary.to_dict(),
    }


def _diagnostic_entry(text: str, scan, item) -> dict:
    """One problem with severity, category, target, location and next actions (§7.2)."""
    location = _diagnostic_location(text, item.context)
    suggestion = _repair_suggestion(text, scan, item)
    actions = [navigate_action(location)]
    if suggestion is not None:
        actions.append(command_action(suggestion["command"], suggestion["label"]))
    return item.to_dict() | {
        "severity": SEVERITY_ERROR,
        "category": CATEGORY_STRUCTURE,
        "target": marker_target(item.context),
        "location": location,
        "actions": actions,
    } | ({"suggestion": suggestion} if suggestion else {})


def _diagnostic_location(text: str, context: str) -> dict | None:
    if not context:
        return None
    lines = text.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.strip()[:CONTEXT_MAX] == context]
    if len(matches) != 1:
        return None
    starts = _line_starts(text)
    line = matches[0]
    return {"line": line, "start": _to_utf16(text, starts[line]),
            "end": _to_utf16(text, starts[line + 1])}


def _repair_suggestion(text: str, scan, diagnostic) -> dict | None:
    """Offer only an exact, single-diagnostic marker repair that rescans cleanly."""
    if len(scan.diagnostics) != 1 or diagnostic.kind != StructureDiagnosticKind.UNBALANCED_MARKER:
        return None
    starts = _line_starts(text)
    eol = _eol(text)
    if "여는" in diagnostic.message and "없이 닫는" in diagnostic.message:
        marker = "{{/선택}}" if "선택" in diagnostic.message else "{{/항목}}"
        matches = [(starts[index], starts[index + 1])
                   for index, line in enumerate(text.splitlines(keepends=True))
                   if line.strip() == marker]
        if len(matches) != 1:
            return None
        start, end = matches[0]
        replacement = ""
        label = "짝이 없는 닫는 마커 제거"
    elif "열린 채" in diagnostic.message:
        marker = "{{/선택}}" if diagnostic.context.startswith("{{#선택 ") else (
            "{{/항목}}" if diagnostic.context.startswith("{{#항목 ") else None)
        if marker is None:
            return None
        start = end = len(text)
        replacement = ("" if not text or text.endswith(("\n", "\r")) else eol) + marker + eol
        label = "파일 끝에 닫는 마커 추가"
    else:
        return None
    candidate = _apply_edits(text, [(start, end, replacement)])
    if scan_text_structure(candidate).diagnostics:
        return None
    return {"label": label, "command": {"type": "repair_marker", "start": _to_utf16(text, start),
                                         "end": _to_utf16(text, end), "text": replacement,
                                         "diagnostic": diagnostic.to_dict()}}


def _target(scan, command: Mapping[str, object]):
    kind = str(command.get("kind", "slot"))
    slot_id = str(command.get("slot_id", ""))
    option_id = str(command.get("option_id", "")) if kind == "option" else None
    return next(
        (place for place in scan.placements if place.kind == kind
         and place.slot_id == slot_id and place.option_id == option_id),
        None,
    )


def _target_name(scan, target) -> str:
    slot = next((item for item in scan.slots if item.id == target.slot_id), None)
    if target.kind == "option":
        option = next((item for item in (slot.options if slot else ()) if item.id == target.option_id), None)
        return (option.label if option and option.label else None) or str(target.option_id)
    return (slot.label if slot and slot.label else None) or target.slot_id


def _line_block_children(text: str, scan, first: int, last: int) -> tuple[list[dict], dict]:
    """Children and counts of the content lines ``first..last`` (inclusive)."""
    markers = marker_lines(scan)
    children: list[dict] = []
    # An option acted on by itself spans exactly ``first..last``; it is not its own child.
    options = [place for place in scan.placements if place.kind == PLACEMENT_OPTION
               and first <= place.begin_marker_line and place.end_marker_line <= last
               and (place.begin_marker_line, place.end_marker_line) != (first, last)]
    for place in options:
        children.append({"kind": "option", "id": place.option_id, "label": _target_name(scan, place),
                         "count": sum(1 for line in range(place.begin_marker_line + 1, place.end_marker_line)
                                      if line not in markers)})
    grouped: dict[str, int] = defaultdict(int)
    for item in _occurrences(text):
        if first <= item["line"] <= last:
            grouped[item["name"]] += 1
    children.extend({"kind": "field", "id": name, "label": name, "count": count}
                    for name, count in grouped.items())
    counts = {"paragraphs": sum(1 for line in range(first, last + 1) if line not in markers),
              "fields": sum(grouped.values()), "options": len(options), "tables": 0}
    return children, counts


def _edits(text: str, command: Mapping[str, object], *,
           projecting: bool = False) -> tuple[list[tuple[int, int, str]], bool, bool]:
    """Edit plan, whether the range expanded, and whether a cascade is still unconfirmed."""
    action = command.get("type")
    scan = scan_text_structure(text)
    if action == "repair_marker":
        for diagnostic in scan.diagnostics:
            suggestion = _repair_suggestion(text, scan, diagnostic)
            if suggestion is not None and command == suggestion["command"]:
                return [(_from_utf16(text, command["start"]),
                         _from_utf16(text, command["end"]), str(command["text"]))], False, False
        raise ValueError(REASON_FIX_STALE)
    if scan.diagnostics and action not in FIELD_COMMANDS:
        raise ValueError(REASON_STRUCTURE_FIRST)
    matches = list(iter_field_token_matches(text))
    starts = _line_starts(text)
    start = _from_utf16(text, command.get("start", 0))
    end = _from_utf16(text, command.get("end", command.get("start", 0)))
    if start > end:
        raise ValueError("고른 범위의 시작과 끝이 뒤바뀌었습니다.")
    expanded = False
    if action == "create_field":
        name = _identifier(command.get("name"))
        spans = _field_spans(text, command, start, end)
        if any(match.start() < hi and lo < match.end() for lo, hi in spans for match in matches):
            raise ValueError(REASON_FIELD_OVERLAP)
        return [(lo, hi, "{{" + name + "}}") for lo, hi in spans], False, False
    if action == "rename_field":
        old = _identifier(command.get("old_name"))
        new = _identifier(command.get("name"))
        existing = [match for match in matches if match.group(1).strip() == old]
        if not existing:
            raise ValueError(_FIELD_NOT_FOUND)
        if old == new:
            return [], False, False
        taken = [match for match in matches if match.group(1).strip() == new]
        if taken:
            raise NameConflict(new, len(taken))
        edits = [(match.start(), match.end(), "{{" + new + "}}")
                 for match in existing]
        return edits, False, False
    if action in {"relink_field", "unset_field"}:
        replacement = ("{{" + _identifier(command.get("name")) + "}}") if action == "relink_field" else command.get("text")
        if whole_field_unset(command):
            # 필드 전체의 의미 해제(P-20): 이름이 같은 모든 사용 위치를 한 계획으로 치환한다.
            name = _identifier(command.get("old_name"))
            sites = [match for match in matches if match.group(1).strip() == name]
            if not sites:
                raise ValueError(_FIELD_NOT_FOUND)
        else:
            match = next((item for item in matches if item.start() <= start < item.end()), None)
            if match is None:
                raise ValueError("고른 필드 사용 위치를 찾을 수 없습니다.")
            sites = [match]
        if not isinstance(replacement, str):
            raise ValueError("의미를 해제한 뒤 남길 본문을 입력하세요.")
        return [(match.start(), match.end(), replacement) for match in sites], False, False
    if action in {"create_slot", "create_option"}:
        kind = PLACEMENT_SLOT if action == "create_slot" else PLACEMENT_OPTION
        region_identifier(command.get("id"))
        _region_label(command.get("label"))
        first, last, lo, hi = _line_range(text, start, end)
        expanded = (lo != start or hi != end)
        if any(place.begin_marker_line <= last and first <= place.end_marker_line
               for place in scan.placements if place.kind == kind):
            raise ValueError(REASON_REGION_OVERLAP)
        if kind == PLACEMENT_OPTION:
            owners = [place for place in scan.placements if place.kind == PLACEMENT_SLOT
                      and place.begin_marker_line < first <= last < place.end_marker_line]
            if len(owners) != 1 or owners[0].slot_id != command.get("slot_id"):
                raise ValueError("고른 범위는 하나의 항목 안에 있어야 합니다.")
            if any(option.id == command.get("id") for slot in scan.slots
                   if slot.id == owners[0].slot_id for option in slot.options):
                raise ValueError("같은 항목에 해당 선택 식별자가 이미 있습니다.")
        elif any(slot.id == command.get("id") for slot in scan.slots):
            raise ValueError("항목 식별자가 이미 있습니다.")
        eol = _eol(text)
        if hi == len(text) and not text.endswith(("\r", "\n")):
            return [(lo, lo, _marker(kind, command.get("id"), command.get("label")) + eol),
                    (hi, hi, eol + _end_marker(kind))], expanded, False
        return [(lo, lo, _marker(kind, command.get("id"), command.get("label")) + eol),
                (hi, hi, _end_marker(kind) + eol)], expanded, False
    target = _target(scan, command)
    if target is None:
        raise ValueError("항목이나 선택 영역을 찾을 수 없습니다.")
    begin = target.begin_marker_line
    finish = target.end_marker_line
    if action in {"rename_slot", "rename_option"}:
        new_id = command.get("id", target.option_id if target.kind == "option" else target.slot_id)
        if new_id != (target.option_id if target.kind == "option" else target.slot_id):
            region_identifier(new_id, renaming=True)
        _region_label(command.get("label"))
        if target.kind == "slot" and any(slot.id == new_id and slot.id != target.slot_id for slot in scan.slots):
            raise ValueError("항목 식별자가 이미 있습니다.")
        if target.kind == "option" and any(opt.id == new_id and opt.id != target.option_id
                                           for slot in scan.slots if slot.id == target.slot_id
                                           for opt in slot.options):
            raise ValueError("같은 항목에 해당 선택 식별자가 이미 있습니다.")
        existing = next(
            (slot if target.kind == "slot" else option
             for slot in scan.slots if slot.id == target.slot_id
             for option in (slot.options if target.kind == "option" else (slot,))
             if target.kind == "slot" or option.id == target.option_id),
            None,
        )
        label = command.get("label", existing.label if existing else None)
        replacement = _marker(target.kind, new_id, label)
        return [(starts[begin], starts[begin + 1], replacement + _eol(text))], False, False
    if action in {"unwrap", "delete", "duplicate", "move"}:
        requires_cascade = False
        child_options = [place for place in scan.placements if place.kind == "option"
                         and place.slot_id == target.slot_id]
        if target.kind == "slot" and action == "unwrap" and child_options and not command.get("cascade"):
            if not projecting:
                children, _ = _line_block_children(text, scan, begin, finish)
                raise CascadeRequired([child for child in children if child["kind"] == "option"])
            requires_cascade = True
        lo, hi = starts[begin], starts[finish + 1]
        if action == "delete":
            return [(lo, hi, "")], False, False
        if action == "unwrap":
            child_lines = {begin, finish}
            if target.kind == "slot":
                child_lines |= {line for place in child_options
                                for line in (place.begin_marker_line, place.end_marker_line)}
            return [(starts[line], starts[line + 1], "") for line in sorted(child_lines)], False, requires_cascade
        destination = _from_utf16(text, command.get("destination", hi))
        if destination not in starts:
            raise ValueError("옮기거나 복제할 위치는 줄 경계여야 합니다.")
        if action == "move":
            if lo <= destination <= hi:
                raise ValueError("영역을 자기 안으로 옮길 수 없습니다.")
            return [(lo, hi, ""), (destination, destination, text[lo:hi])], False, False
        new_id = command.get("new_id")
        if not new_id:
            raise ValueError("복제할 영역의 새 식별자를 입력하세요.")
        copied = text[lo:hi]
        old_marker = text[starts[begin]:starts[begin + 1]].strip()
        copied = copied.replace(old_marker, _marker(target.kind, new_id, command.get("label")), 1)
        return [(destination, destination, copied)], False, False
    if action == "adjust_range":
        first, last, _, _ = _line_range(text, start, end)
        if first > last:
            raise ValueError("조정한 범위에 본문이 없습니다.")
        begin_text = text[starts[begin]:starts[begin + 1]]
        end_text = text[starts[finish]:starts[finish + 1]]
        return [(starts[begin], starts[begin + 1], ""),
                (starts[finish], starts[finish + 1], ""),
                (starts[first], starts[first], begin_text),
                (starts[last + 1], starts[last + 1], end_text)], True, False
    raise ValueError(f"알 수 없는 저작 명령입니다: {action!r}")


def _field_spans(text: str, command: Mapping[str, object], start: int, end: int) -> list[tuple[int, int]]:
    """``create_field`` 의 자리들(code point) — ``ranges`` 가 있으면 고른 자리를 포함한 전부다(IDE-07 P-07).

    고른 자리(``start/end``)는 ``ranges`` 안에 있어야 한다. 서로 겹치거나 같은 자리는 필드 겹침 거절이다.
    """
    ranges = command.get("ranges")
    if ranges is None:
        return [(start, end)]
    if not isinstance(ranges, list) or not all(isinstance(item, Mapping) for item in ranges):
        raise ValueError(REASON_INVALID_SELECTION)
    spans = sorted((_from_utf16(text, item.get("start")), _from_utf16(text, item.get("end"))) for item in ranges)
    # 같은 문구 N곳이다 — 고른 자리가 들어 있고 모든 자리의 글자가 같아야 한다(옛 좌표를 짐작해 끼우지 않는다).
    if (start, end) not in spans or any(lo > hi or text[lo:hi] != text[start:end] for lo, hi in spans):
        raise ValueError(REASON_INVALID_SELECTION)
    if any(first[1] > second[0] or first == second for first, second in itertools.pairwise(spans)):
        raise ValueError(REASON_FIELD_OVERLAP)
    return spans


def _apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    for start, end, replacement in sorted(edits, key=lambda edit: (edit[0], edit[1]), reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def _project(content: str, command: Mapping[str, object], *, projecting: bool) -> dict:
    action = command.get("type")
    scan = scan_text_structure(content)
    edits, expanded, requires_cascade = _edits(content, command, projecting=projecting)
    result = _apply_edits(content, edits)
    if not scan.diagnostics and scan_text_structure(result).diagnostics:
        raise ValueError("명령을 적용하면 구조가 깨집니다: " + scan_text_structure(result).diagnostics[0].message)
    starts = _line_starts(content)
    start = _from_utf16(content, command.get("start", 0))
    end = _from_utf16(content, command.get("end", command.get("start", 0)))
    original = content[start:end] if action == "create_field" else None
    before: str | None = None
    after: str | None = None
    included: str | list[str] | None = None
    # 편집면이 미리보기 동안 칠할 실제 범위(P-16) — 넓힌 범위 또는 대상 영역, UTF-16 좌표.
    included_location: dict | None = None
    children: list[dict] = []
    counts: dict | None = None
    label = command_label(command)
    extra: dict = {}
    if action == "create_field":
        name = _identifier(command.get("name"))
        fields = _fields(content)
        existing = next((item["count"] for item in fields if item["name"] == name), 0)
        before, after = original, f"[ {name} ]"
        extra = {"links_existing": existing > 0, "existing_count": existing,
                 "candidates": field_candidates(fields)}
        if command.get("ranges") is not None:
            # 같은 문구 N곳(P-07): 포함될 자리마다 검색 결과와 같은 문맥 한 줄(문서 차례).
            included = [text_hit_context(content, lo, hi) for lo, hi, _ in sorted(edits)]
    elif action == "rename_field":
        old = _identifier(command.get("old_name"))
        before, after = old, _identifier(command.get("name"))
        label = command_label(command, old)
    elif whole_field_unset(command):
        name = _identifier(command.get("old_name"))
        before, after = "{{" + name + "}}", edits[0][2]
        # 모든 사용 위치의 문맥(P-20) — 구조 목록의 사용 위치 행과 같은 문장이다.
        included = [item["context"] for item in _occurrences(content) if item["name"] == name]
        label = command_label(command, name)
    elif action in {"relink_field", "unset_field"}:
        match = next(item for item in iter_field_token_matches(content) if item.start() <= start < item.end())
        before, after = match.group(0), edits[0][2]
        label = command_label(command, match.group(1).strip())
    elif action == "repair_marker":
        lo, hi, replacement = edits[0]
        before, after = content[lo:hi], replacement or "마커 제거"
        label = command_label(command, next(
            suggestion["label"] for diagnostic in scan.diagnostics
            for suggestion in (_repair_suggestion(content, scan, diagnostic),)
            if suggestion is not None and suggestion["command"] == command))
    elif action in {"create_slot", "create_option"}:
        first, last, lo, hi = _line_range(content, start, end)
        before, included = content[start:end], content[lo:hi]
        after = included
        included_location = {"start": _to_utf16(content, lo), "end": _to_utf16(content, hi)}
        children, counts = _line_block_children(content, scan, first, last)
        label = command_label(command)
    else:
        target = _target(scan, command)
        assert target is not None
        begin, finish = target.begin_marker_line, target.end_marker_line
        region = content[starts[begin]:starts[finish + 1]]
        included = region
        included_location = {"start": _to_utf16(content, starts[begin]),
                             "end": _to_utf16(content, starts[finish + 1])}
        children, counts = _line_block_children(content, scan, begin, finish)
        label = command_label(command, _target_name(scan, target))
        if action == "delete":
            before, after = region, ""
        elif action == "unwrap":
            removed = {lo for lo, _, _ in edits}
            pieces = content.splitlines(keepends=True)
            before = region
            after = "".join(piece for line, piece in enumerate(pieces)
                            if begin <= line <= finish and starts[line] not in removed)
        elif action == "move":
            before = after = region
        elif action == "duplicate":
            before, after = region, edits[0][2]
        elif action in {"rename_slot", "rename_option"}:
            before, after = content[starts[begin]:starts[begin + 1]], edits[0][2]
        elif action == "adjust_range":
            first, last, lo, hi = _line_range(content, start, end)
            before, included = region, content[lo:hi]
            after = included
            included_location = {"start": _to_utf16(content, lo), "end": _to_utf16(content, hi)}
            children, counts = _line_block_children(content, scan, first, last)
    return {
        "edits": [{"start": _to_utf16(content, lo), "end": _to_utf16(content, hi), "text": value}
                  for lo, hi, value in sorted(edits, reverse=True)],
        "affected": len(edits),
        "expanded": expanded,
        "result": analyze("txt", result),
        "captured_text": original,
        "original": original,
        "before": before,
        "after": after,
        "included": included,
        "included_location": included_location,
        "children": children,
        "counts": counts,
        "label": label,
        "requires_cascade": requires_cascade,
        **extra,
    }


def preview(media: str, content: str | object, command: Mapping[str, object]) -> dict:
    """Project a command without applying it; an unconfirmed cascade is flagged, not refused."""
    if media != "txt" or not isinstance(content, str):
        raise ValueError(f"지원하지 않는 저작 형식입니다: {media}")
    return _project(content, command, projecting=True)


def apply(media: str, content: str | object, command: Mapping[str, object]) -> tuple[str, dict]:
    if media != "txt" or not isinstance(content, str):
        raise ValueError(f"지원하지 않는 저작 형식입니다: {media}")
    projection = _project(content, command, projecting=False)
    edits = [(_from_utf16(content, item["start"]), _from_utf16(content, item["end"]), item["text"])
             for item in projection["edits"]]
    return _apply_edits(content, edits), projection


def _overlaps(lo: int, hi: int, start: int, end: int) -> bool:
    """고른 범위(빈 범위면 캐럿)가 ``lo..hi`` 에 닿는가 — 명령 가용성의 겹침 규칙."""
    return lo <= start <= hi if start == end else lo < end and start < hi


def _placement_hits(scan, starts: list[int], start: int, end: int) -> tuple[list, bool]:
    """범위를 품은 항목·선택, 그리고 범위가 영역 경계를 가로지르는가."""
    placed = [(place, starts[place.begin_marker_line], starts[place.end_marker_line + 1])
              for place in scan.placements]
    hit = [(place, lo, hi) for place, lo, hi in placed if _overlaps(lo, hi, start, end)]
    containing = [place for place, lo, hi in hit if lo <= start and end <= hi]
    return containing, any(not (lo <= start and end <= hi) for _, lo, hi in hit)


def _create_field_reason(scan, starts: list[int], matches: list, start: int, end: int) -> str | None:
    """한 범위의 ``create_field`` 판정(TXT) — 명령 가용성과 같은 문구 자리(``same_text``)가 같은 규칙을 쓴다."""
    if _placement_hits(scan, starts, start, end)[1]:
        return REASON_MULTI_REGION
    inside_field = any((match.start() < start < match.end()) if start == end
                       else (match.start() < end and start < match.end()) for match in matches)
    return REASON_FIELD_OVERLAP if inside_field else None


def same_text_sites(media: str, content: str | object, selection: Mapping[str, object]) -> list[dict]:
    """고른 문구와 같은 평문 자리 전부(IDE-07 P-07) — 검색의 「같은 문맥은 한 건」 병합 없이 원시 자리다.

    고른 자리와 겹치는 자리, 필드 토큰·구간 표기(문법) 안의 자리는 뺀다. 자리마다 ``enabled/reason`` 은 그 자리를
    범위로 한 ``create_field`` 판정이다. 문맥이 같은 두 자리는 ``line``(행)과 문맥 안의 찾은 글자 위치(``focus``)로
    갈린다. 고른 범위가 비었거나 공백뿐이거나 글자를 확정할 수 없으면 빈 목록이다(짐작하지 않는다).
    """
    if media != "txt" or not isinstance(content, str):
        raise ValueError(f"지원하지 않는 저작 형식입니다: {media}")
    try:
        start = _from_utf16(content, selection.get("start"))
        end = _from_utf16(content, selection.get("end"))
    except ValueError:
        return []
    phrase = content[start:end]
    if not phrase.strip():
        return []
    scan = scan_text_structure(content)
    starts = _line_starts(content)
    matches = list(iter_field_token_matches(content))
    grammar = scan_text_token_spans(content)
    sites: list[dict] = []
    for found in re.finditer(re.escape(phrase), content):
        lo, hi = found.span()
        if (lo < end and start < hi) or any(span.start < hi and lo < span.end for span in grammar):
            continue
        parts = text_hit_parts(content, lo, hi)
        reason = _create_field_reason(scan, starts, matches, lo, hi)
        sites.append({"location": {"start": _to_utf16(content, lo), "end": _to_utf16(content, hi)},
                      "line": _line_at(starts, lo), "context": "".join(parts), "focus": context_focus(parts),
                      "enabled": reason is None, "reason": reason})
    return sites


def available_commands(media: str, content: str | object, selection: Mapping[str, object],
                       context: Mapping[str, object] | None = None) -> list[dict]:
    """Decide which commands the current TXT selection allows and why not (F40, §6.1)."""
    if media != "txt" or not isinstance(content, str):
        raise ValueError(f"지원하지 않는 저작 형식입니다: {media}")
    context = context or {}
    try:
        start = _from_utf16(content, selection.get("start"))
        end = _from_utf16(content, selection.get("end", selection.get("start")))
        if start > end:
            raise ValueError(REASON_INVALID_SELECTION)
    except ValueError:
        return availability_entries(dict.fromkeys(COMMAND_TYPES, REASON_INVALID_SELECTION))
    scan = scan_text_structure(content)
    starts = _line_starts(content)
    matches = list(iter_field_token_matches(content))
    field_hits = [match.group(1).strip() for match in matches
                  if _overlaps(match.start(), match.end(), start, end)]
    containing, _ = _placement_hits(scan, starts, start, end)
    slot_id = context["slot_id"] if "slot_id" in context else next(
        (place.slot_id for place in containing if place.kind == PLACEMENT_SLOT), None)
    option_id = context["option_id"] if "option_id" in context else next(
        (place.option_id for place in containing if place.kind == PLACEMENT_OPTION), None)
    if slot_id is not None and not any(slot.id == slot_id for slot in scan.slots):
        slot_id = option_id = None
    target_kind = "option" if option_id is not None and slot_id is not None else "slot" if slot_id else None
    broken = bool(scan.diagnostics)
    reasons = shared_reasons(field_hits=field_hits, target_kind=target_kind, has_slot=slot_id is not None,
                             structure_broken=broken)
    alternatives: dict[str, dict] = {}
    reasons["create_field"] = _create_field_reason(scan, starts, matches, start, end)
    if broken:
        reasons["create_slot"] = reasons["create_option"] = REASON_STRUCTURE_FIRST
        return availability_entries(reasons, alternatives)
    try:
        first, last, _, _ = _line_range(content, start, end)
    except ValueError as exc:
        reasons["create_slot"] = reasons["create_option"] = str(exc)
        return availability_entries(reasons, alternatives)
    line_hits = [place for place in scan.placements
                 if place.begin_marker_line <= last and first <= place.end_marker_line]
    reasons["create_slot"] = REASON_REGION_OVERLAP if line_hits else None
    owners = [place for place in scan.placements if place.kind == PLACEMENT_SLOT
              and place.begin_marker_line < first <= last < place.end_marker_line]
    slot_hits = [place for place in line_hits if place.kind == PLACEMENT_SLOT]
    if len(owners) == 1:
        reasons["create_option"] = (REASON_REGION_OVERLAP if any(place.kind == PLACEMENT_OPTION
                                                                 for place in line_hits) else None)
    elif slot_hits:
        reasons["create_option"] = REASON_MULTI_REGION
    else:
        reasons["create_option"] = REASON_OPTION_OUTSIDE_SLOT
        alternatives["create_option"] = dict(ALTERNATIVE_CREATE_SLOT)
    return availability_entries(reasons, alternatives)


def trial_document_values(
    names: Iterable[str], values: Mapping[str, object],
) -> tuple[dict[str, str], list[str]]:
    """결과 시험이 문서에 넣을 필드 값 — 생성 경로와 같은 빈 값 규칙이다(#957 신뢰 정책).

    값이 없거나(키 부재·null) 비었거나 공백뿐인 필드는 막지 않고 빈 값 표식
    (:data:`~hwpxfiller.domain.job.MISSING_MARKER`)을 받는다. 두 매체(TXT·HWPX)가 이 한 함수를
    써서 시험 결과가 실제 생성과 같은 자리를 같은 글로 보인다. 반환: (필드 → 문서 값, 표식을
    받은 필드 이름 — ``names`` 차례·중복 제거). 표식 필드는 결과 보고의 ``empty_fields`` 다.
    """
    document: dict[str, str] = {}
    empty: list[str] = []
    for name in names:
        if name in document:
            continue
        value = values.get(name)
        text = "" if value is None else str(value)
        if text.strip():
            document[name] = text
        else:
            document[name] = MISSING_MARKER.format(field=name)
            empty.append(name)
    return document, empty


def trial(
    media: str,
    content: str | object,
    values: Mapping[str, object],
    selected: Mapping[str, str],
    *,
    output: str,
) -> dict:
    """Project source/output provenance after the materialization port has run."""
    if media != "txt" or not isinstance(content, str):
        raise ValueError(f"지원하지 않는 결과 시험 형식입니다: {media}")
    scan = scan_text_structure(content)
    if scan.diagnostics:
        raise ValueError("구조 오류를 수정한 뒤 결과를 시험하세요.")
    for slot in scan.slots:
        choice = selected.get(slot.id)
        if slot.options and choice not in {option.id for option in slot.options}:
            raise ValueError(f"'{slot.id}' 항목의 시험 선택을 지정하세요.")
    chosen = {key: (value,) for key, value in selected.items()}
    hidden = marker_lines(scan) | unselected_option_lines(scan, chosen)
    pieces = content.splitlines(keepends=True)
    starts = _line_starts(content)
    names = [match.group(1).strip() for line, piece in enumerate(pieces) if line not in hidden
             for match in iter_field_token_matches(piece)]
    document_values, empty_fields = trial_document_values(names, values)
    occurrences = []
    output_pos = 0
    for line, piece in enumerate(pieces):
        if line in hidden:
            continue
        cursor = 0
        for match in iter_field_token_matches(piece):
            output_pos += _unit_length(piece[cursor:match.start()])
            name = match.group(1).strip()
            value = document_values[name]
            occurrences.append({
                "name": name,
                "source_start": _to_utf16(content, starts[line] + match.start()),
                "source_end": _to_utf16(content, starts[line] + match.end()),
                "output_start": output_pos,
                "output_end": output_pos + _unit_length(value),
                "value": value,
            })
            output_pos += _unit_length(value)
            cursor = match.end()
        output_pos += _unit_length(piece[cursor:])
    excluded = []
    for place in scan.placements:
        if place.kind != PLACEMENT_OPTION or place.option_id == selected.get(place.slot_id):
            continue
        owner = next(slot for slot in scan.slots if slot.id == place.slot_id)
        chosen_option = next(option for option in owner.options if option.id == selected[place.slot_id])
        omitted = next(option for option in owner.options if option.id == place.option_id)
        excluded.append({
            "slot_id": place.slot_id,
            "option_id": place.option_id,
            "selected_option_id": selected.get(place.slot_id),
            "label": omitted.label or omitted.id,
            "reason": (f"현재 시험에서 '{chosen_option.label or chosen_option.id}'을 골라 "
                       f"'{omitted.label or omitted.id}'은 제외되었습니다."),
            "start": _to_utf16(content, starts[place.begin_marker_line]),
            "end": _to_utf16(content, starts[place.end_marker_line + 1]),
        })
    return {
        "text": output,
        # 값이 없는 필드는 거절하지 않고 빈 값 표식으로 렌더한다(trial_document_values) — 누락은 없다.
        "report": {"missing_fields": [], "empty_fields": empty_fields},
        "occurrences": occurrences,
        "excluded": excluded,
    }

