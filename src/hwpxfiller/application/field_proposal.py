"""「데이터로 필드 찾기」(#1156) 쓰임새 — 데이터 행 고르기, 제안 스냅숏, 필드 만들기 명령과 연결 초안.

판정은 :mod:`hwpxfiller.domain.field_induction` 이 하고, 문서 읽기·좌표 변환은 어댑터가 한다. 여기는 세션이 든
상태(데이터·행·「그대로 두기」)로 그 둘을 이어 계약의 ``proposal`` 스냅숏을 짓고, 묶음을 ``create_field``
명령으로 바꾼다. 모든 문장은 Python 이 완성한다 — 화면은 등급을 다시 판정하지 않는다.

스냅숏의 묶음 사전은 열린 모양이다: 뒤에 올 층(예: 보류 묶음을 다시 보는 판단)이 보류 묶음에 ``"ai": {...}`` 같은
키를 더해도 지금 키의 뜻은 바뀌지 않는다 — 화면은 모르는 키를 무시한다.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from ..domain.field_induction.candidates import ParagraphText, found_columns
from ..domain.field_induction.grading import KIND_HELD, KIND_PROPOSAL, REASON_BAD_NAME
from ..domain.field_induction.proposal import Group, Proposal, field_name, note_for, propose
from ..domain.field_induction.transforms import TRANSFORMS
from ..domain.mapping import FieldMapping
from ..domain.template_authoring import REASON_INVALID_SELECTION
from ..domain.template_authoring_primitives import CREATE_FIELDS

STATE_READY = "ready"
STATE_NEEDS_DATA = "needs_data"
STATE_FAILED = "failed"
ROW_LIMIT = 500
ROW_SHOWN = 20
NO_PROPOSAL_LEFT = "남은 제안이 없습니다."
_ONLY_CELL = "표 칸 1곳만 필드로"
_ONLY_SPOT = "이 자리만 필드로"


def row_label(index: int) -> str:
    return f"{index}행"


def hint_best(count: int) -> str:
    return f"값이 가장 많이 맞는 행 · {count}개"


def hint_other(count: int) -> str:
    return f"맞는 값 {count}개"


def source_text(row: int, column: str) -> str:
    """팝오버 머리 아래 출처 줄 — 고른 행과 연결 열."""
    return f"{row_label(row)} ‘{column}’ 열과 같은 값입니다."


#: 같은 이름 필드가 이미 있는 묶음 — 만들면 그 필드에 자리가 더해진다(``links_existing``).
LINKS_NOTE = "같은 이름 필드에 자리를 더합니다."
#: 열 고르기가 묶음의 열이 아닌 열을 가리킬 때.
REASON_NOT_SAME_VALUE = "이 값과 같은 열 가운데서 고르세요."


def toast_one(name: str) -> str:
    return f"‘{name}’ 필드를 만들고 연결 초안에 열과 표시형을 넣었습니다."


def toast_many(count: int) -> str:
    return f"필드 {count}개를 만들고 연결 초안에 열과 표시형을 넣었습니다."


@dataclass(frozen=True)
class LoadedRows:
    """데이터 풀 항목 하나를 읽은 결과 — 실패면 ``error`` 문장만 있다."""

    name: str = ""
    columns: tuple[str, ...] = ()
    rows: tuple[dict[str, str | None], ...] = ()
    truncated: bool = False  # 행이 상한(500)보다 많아 앞 500행만 본다
    error: str = ""


class ProposalDataPort(Protocol):
    """데이터 풀을 읽는 환경 효과 — 화면 조립부가 실제 풀 레지스트리로 채운다."""

    def datasets(self) -> list[dict]: ...

    def load(self, key: str, sheet: str | None) -> LoadedRows: ...

    def current(self) -> tuple[str, str | None] | None: ...


@dataclass
class FieldProposalState:
    """세션이 든 제안 상태 — 데이터·행·「그대로 두기」. 계산 결과는 문서 revision 별로 한 벌만 든다."""

    pool_key: str = ""
    sheet: str | None = None
    row: int | None = None  # 1부터 — 사람이 고른 행. None 이면 가장 많이 맞는 행
    loaded: LoadedRows | None = None
    dismissed: set[tuple[str, str]] = field(default_factory=set)
    #: 사람이 같은 값의 열 가운데 고른 열 — 묶음 열쇠(같은 값을 낸 열들) → 열. 문서가 바뀌어도 남는다.
    picks: dict[str, str] = field(default_factory=dict)
    cache: tuple[object, dict] | None = None


def normalize_rows(name: str, records: Sequence[Mapping[str, object]]) -> LoadedRows:
    """풀 레코드 → 열 차례와 행(앞 500행). 값은 타입 없는 텍스트다 — None 은 빈 값으로 남는다."""
    columns: dict[str, None] = {}
    rows: list[dict[str, str | None]] = []
    for record in records[:ROW_LIMIT]:
        columns.update(dict.fromkeys(str(key) for key in record))
        rows.append({str(key): None if value is None else str(value) for key, value in record.items()})
    return LoadedRows(name, tuple(columns), tuple(rows), truncated=len(records) > ROW_LIMIT)


def rank_rows(paragraphs: Sequence[ParagraphText], rows: Sequence[Mapping[str, str | None]]) -> list[int]:
    return [found_columns(paragraphs, row) for row in rows]


def _rows_view(counts: Sequence[int], chosen: int) -> list[dict]:
    best = max(range(len(counts)), key=lambda index: (counts[index], -index))
    order = sorted(range(len(counts)), key=lambda index: (-counts[index], index))[:ROW_SHOWN]
    shown = sorted(set(order) | {chosen - 1})
    return [{"index": index + 1, "label": row_label(index + 1),
             "hint": hint_best(counts[index]) if index == best else hint_other(counts[index])}
            for index in shown]


def chosen_row(state: FieldProposalState, counts: Sequence[int]) -> int:
    if state.row is not None and 1 <= state.row <= len(counts):
        return state.row
    return max(range(len(counts)), key=lambda index: (counts[index], -index)) + 1


def _only_label(group: Group, spots: list[dict]) -> str | None:
    """보류 묶음의 「이 자리만」 단추 이름 — 고를 수 있는 한 자리(``only``)가 표 칸이면 「표 칸 1곳만 필드로」.

    ``only`` 가 없으면 연 자리 하나다. 열 이름이 필드 이름이 될 수 없거나 자리가 없으면 단추가 없다.
    """
    if group.kind != KIND_HELD or not spots or group.reason == REASON_BAD_NAME:
        return None
    only = next((spot for spot in spots if spot["id"] == group.only), None)
    return _ONLY_CELL if only is not None and only.get("cell_path") else _ONLY_SPOT


def _group_view(group: Group, locate: Callable[[int, int, int], dict], row: int) -> dict:
    spots = [{"id": spot.id, **locate(spot.paragraph, spot.start, spot.end), "text": spot.text,
              "where": spot.where} for spot in group.spots]
    return {
        "id": group.id, "kind": group.kind, "name": group.name, "column": group.column,
        "columns": note_for(group), "value": group.value, "raw": group.raw,
        "binding": TRANSFORMS[group.transform].binding(), "reason": group.reason, "note": group.note,
        "source_text": source_text(row, group.column),
        "links_note": LINKS_NOTE if group.links_existing else "",
        "only": group.only, "only_label": _only_label(group, spots),
        "links_existing": group.links_existing, "count_text": group.count_text, "spots": spots,
    }


def proposal_view(*, state: FieldProposalState, revision: int, paragraphs: Sequence[ParagraphText],
                  locate: Callable[[int, int, int], dict], existing: Sequence[str],
                  datasets: list[dict]) -> dict:
    """계약 ``proposal`` 스냅숏 한 벌(``ready``) — ``state.loaded`` 가 읽힌 뒤에만 부른다."""
    loaded = state.loaded
    assert loaded is not None and not loaded.error and loaded.rows
    counts = rank_rows(paragraphs, loaded.rows)
    # 고른 행은 고정한다 — 필드를 만들면 그 값이 문서 밖 글자에서 빠져 「가장 많이 맞는 행」이 바뀔 수 있다.
    row = state.row = chosen_row(state, counts)
    result: Proposal = propose(paragraphs, loaded.rows[row - 1], loaded.columns,
                               existing_fields=existing, dismissed=state.dismissed, picks=state.picks)
    return {
        "state": STATE_READY, "error": "", "revision": revision, "datasets": datasets,
        "data": {"pool_key": state.pool_key, "name": loaded.name, "sheet": state.sheet, "row": row,
                 "rows": _rows_view(counts, row), "rows_truncated": loaded.truncated},
        "counts": {"proposal": result.count(KIND_PROPOSAL), "held": result.count(KIND_HELD)},
        "groups": [_group_view(group, locate, row) for group in result.groups],
        "missing": [{"column": item.column, "reason": item.reason} for item in result.missing],
    }


def empty_view(state_name: str, revision: int, datasets: list[dict], error: str = "",
               state: FieldProposalState | None = None) -> dict:
    """데이터가 없거나(``needs_data``) 읽지 못한(``failed``) 스냅숏 — 묶음이 없다."""
    data = None if state is None or not state.pool_key else {
        "pool_key": state.pool_key, "name": state.loaded.name if state.loaded else "", "sheet": state.sheet,
        "row": None, "rows": [], "rows_truncated": False}
    return {"state": state_name, "error": error, "revision": revision, "datasets": datasets, "data": data,
            "counts": {"proposal": 0, "held": 0}, "groups": [], "missing": []}


# ------------------------------------------------------------------ commands
def _site(spot: Mapping[str, object]) -> dict:
    return {key: spot[key] for key in ("entry", "paragraph", "cell_path", "start", "end") if key in spot}


def group_command(group: Mapping[str, object], spot_id: object = None) -> dict:
    """묶음(또는 그 자리 하나) → ``create_field`` 명령. 자리가 여럿이면 ``ranges`` 로 한 명령이다."""
    if field_name(str(group["column"])) is None:
        raise ValueError(REASON_BAD_NAME)
    spots = [spot for spot in group["spots"] if spot_id is None or spot["id"] == spot_id]  # type: ignore[union-attr]
    if not spots:
        raise ValueError(REASON_INVALID_SELECTION)
    command = {"type": "create_field", "name": group["name"], **_site(spots[0])}
    if len(spots) > 1:
        command["ranges"] = [_site(spot) for spot in spots]
    return command


def pick_column(state: FieldProposalState, group: Mapping[str, object], column: object) -> None:
    """같은 값의 열 가운데 하나를 고른다 — 묶음의 지금 열이나 「열도 같은 값」 열만 받는다."""
    allowed = [str(group["column"])] + [str(item["name"]) for item in group["columns"]]  # type: ignore[union-attr]
    if not isinstance(column, str) or column not in allowed:
        raise ValueError(REASON_NOT_SAME_VALUE)
    state.picks[str(group["id"])] = column


def all_command(view: Mapping[str, object]) -> tuple[dict, list[Mapping[str, object]]]:
    """제안 묶음 전부(보류 제외) → ``create_fields`` 한 명령과 그 묶음들."""
    groups = [group for group in view["groups"] if group["kind"] == KIND_PROPOSAL and group["spots"]]  # type: ignore[union-attr]
    if not groups:
        raise ValueError(NO_PROPOSAL_LEFT)
    fields = [{"name": group["name"], "ranges": [_site(spot) for spot in group["spots"]]} for group in groups]
    return {"type": CREATE_FIELDS, "fields": fields}, groups


def drafts(groups: Sequence[Mapping[str, object]]) -> tuple[dict[str, dict], dict[str, str]]:
    """만들 묶음들의 연결 초안과 시험 값 — ``{필드: {"source", "type", "fmt"}}``, ``{필드: 행의 원시 값}``."""
    bindings: dict[str, dict] = {}
    values: dict[str, str] = {}
    for group in groups:
        binding = group["binding"]
        assert isinstance(binding, Mapping)
        name = str(group["name"])
        bindings[name] = {"source": group["column"], "type": binding["type"], "fmt": binding["fmt"]}
        values[name] = str(group["raw"])
    return bindings, values


#: 작업 적용 결과 가운데 그 템플릿이 작업의 현재 템플릿이 된 상태 — 이때만 연결 초안을 심는다.
SEEDABLE_APPLY = frozenset({"applied", "already_applied"})


def seed_mappings(existing: Sequence[FieldMapping], fields: Collection[str],
                  bindings: Mapping[str, Mapping[str, str]]) -> list[FieldMapping]:
    """연결 초안 → 작업에 더할 새 필드 연결. 적용한 템플릿에 있는 필드이고 작업에 연결이 아직 없는 것만이다.

    작업에 이미 있는 연결(빈 결정 포함)은 건드리지 않는다 — 새 필드만 채운다(#1156 결정).
    """
    mapped = {item.template_field for item in existing}
    return [FieldMapping(name, source=draft["source"], type=draft["type"], fmt=draft["fmt"])
            for name, draft in bindings.items() if name in fields and name not in mapped]
