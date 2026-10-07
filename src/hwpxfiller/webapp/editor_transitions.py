"""편집기 세션의 상태 전이 — 데이터 채택과 매핑 초안의 재조립·되돌리기.

두 전이는 늘 짝으로 움직인다: 데이터가 서면 매핑 초안이 다시 지어지고, 저장본으로 되돌리면
연결이 다시 선다. 로더(:class:`~hwpxfiller.webapp.editor_session.EditorLoader`)는 동사를
조합할 뿐이고 전이 자체는 여기 있다.

- 데이터 채택: 어느 길로 오든(파일 피커·등록 데이터 겨눔·저장본 결속 재읽기·「이 데이터로
  새 작업」 승계) :meth:`EditorDataMount.adopt` 한 곳을 지난다. 경로·시트·헤더 행·종류를
  **같은 시점의 한 벌**로 포획하고, 매핑 재조립과 작업 이름 재유도를 같은 자리에서 태운다 —
  길마다 각자 하면 한쪽만 재조립을 빠뜨린다. 데이터 닻(새 템플릿을 골라도 살리는 진입
  데이터)의 포획·복원도 여기 산다.
- 매핑 초안: 템플릿이나 데이터가 바뀌면 다시 짓고(사람이 손댄 행은 값만 이월하고 미확정으로),
  저장본으로 되돌리면 그 연결을 다시 세운다. 재조립의 판정(정확 일치 재판정·값 이월)은
  :func:`ensure_model` 하나가 진다. 통지 문장도 같은 자리에서 낸다 — 무엇을 이월했고 무엇이
  빠졌는지는 재조립한 쪽만 안다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..data.factory import pclm_reference, source_for_binding, source_for_path, source_from_pool_item
from ..domain.job import Job, data_binding_of, has_data_binding
from ..viewmodel.edit_session import DATA_ANCHORED_ENTRY_REASONS, EditSession
from ..viewmodel.mapping_state import MappingModel, profile_source_vocabulary
from .screens import NO_ROWS_TEXT, pool_reference_quad


# ------------------------------------------------------------------ 매핑 초안


def set_notice(edit: EditSession, text: str, level: str = "muted") -> None:
    """편집기 세션 통지 한 칸을 세운다(빈 문장이면 통지가 없다)."""
    edit.notice_text = text
    edit.notice_level = level


def _carried_state(model: "MappingModel | None", source_fields: "list[str]"):
    """재조립 전 모델에서 이월할 것 — ``(이월 프로필, 미확정으로 둔 필드, 정확 일치 소실)``."""
    if model is None:
        return None, set(), False
    unconfirmed_fields = {row.template_field for row in model.rows if row.manual_unconfirmed}
    lost_auto_source = any(
        row.auto_confirmed_exact and row.source not in source_fields for row in model.rows
    )
    carried_prior = model.carry_profile()
    return (carried_prior if carried_prior.mappings else None), unconfirmed_fields, lost_auto_source


def ensure_model(edit: EditSession) -> None:
    """지금 템플릿·데이터 조합의 매핑 초안을 세운다 — 조합이 같으면 무동작."""
    if edit.schema is None:
        raise ValueError("템플릿이 로드되지 않았습니다.")
    key = edit.model_key_now()
    if edit.model is not None and edit.model_key == key:
        return
    prior, unconfirmed_fields, lost_auto_source = _carried_state(edit.model, edit.source_fields)
    edit.model = MappingModel.from_suggestions(edit.schema, edit.source_fields)
    edit.unconfirm_undo = []
    carried = edit.model.apply_profile(prior, confirm=False) if prior is not None else 0
    if prior is not None or lost_auto_source:
        set_notice(
            edit,
            f"템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다. 직접 확인하거나 편집한 {carried}개 행의 소스·유형·서식은 이월했습니다. 확인이 필요한 행을 다시 확정하세요.",
            "warn",
        )
    for index, row in enumerate(edit.model.rows):
        if row.template_field in unconfirmed_fields:
            edit.model.set_confirmed(index, False)
    edit.model_key = key


def revert_binding(edit: EditSession, base: Job) -> None:
    """「연결 확인」만 저장본으로 되돌린다 — 데이터가 없으면 저장본의 어휘로 선다."""
    if edit.schema is None:
        return
    vocabulary = list(edit.source_fields) or profile_source_vocabulary(base.mapping)
    if not edit.data_path:
        edit.source_fields = profile_source_vocabulary(base.mapping)
        vocabulary = edit.source_fields
    edit.model = MappingModel.from_suggestions(edit.schema, vocabulary)
    edit.model.apply_profile(base.mapping)
    edit.model_key = edit.model_key_now()


def restore_job_mapping(edit: EditSession, job: Job, *, carried_data: bool) -> None:
    """저장본의 연결로 매핑 모델을 세운다 — 데이터가 없으면 저장본의 어휘가 열이다."""
    assert edit.schema is not None  # 호출자가 템플릿을 읽고 RAW 를 이미 거절했다
    if not carried_data:
        edit.source_fields = profile_source_vocabulary(job.mapping)
    edit.model = MappingModel.from_suggestions(edit.schema, edit.source_fields)
    edit.model.apply_profile(job.mapping, require_source=carried_data)
    edit.model_key = edit.model_key_now()


def _dropped_fields(job: Job, model: MappingModel) -> "list[str]":
    row_fields = {r.template_field for r in model.rows}
    return [m.template_field for m in job.mapping.mappings if m.template_field not in row_fields]


def _unconfirmed_split(job: Job, model: MappingModel) -> "tuple[list[str], list[str]]":
    """확정되지 않은 행을 ``(새로 생긴 필드, 저장본에 있던 필드)`` 로 가른다(행 순서 유지)."""
    saved_fields = {m.template_field for m in job.mapping.mappings}
    unconfirmed = [r.template_field for r in model.rows if not r.confirmed]
    return (
        [name for name in unconfirmed if name not in saved_fields],
        [name for name in unconfirmed if name in saved_fields],
    )


def restore_report_lines(job: Job, model: MappingModel, handoff_failure: str) -> "list[str]":
    """저장본을 다시 세운 뒤의 재진술 — 빠진 필드·새 필드·끊긴 연결·데이터 재읽기 실패."""
    dropped = _dropped_fields(job, model)
    fresh, detached = _unconfirmed_split(job, model)
    lines: list[str] = []
    if dropped:
        lines.append(
            f"템플릿에 더는 없는 저장 필드 {len(dropped)}개는 제외했습니다: " + ", ".join(dropped)
        )
    if fresh:
        lines.append(
            f"템플릿에 새로 생긴 필드 {len(fresh)}개는 확정이 필요합니다: " + ", ".join(fresh)
        )
    if detached:
        lines.append(
            f"불러온 데이터에 없는 열을 쓰던 필드 {len(detached)}개는 확정이 필요합니다: "
            + ", ".join(detached)
        )
    if handoff_failure:
        lines.append(f"연결된 데이터를 다시 읽지 못했습니다: {handoff_failure}")
    return lines


def discard_data_line(data_changed: bool, base_bound: bool) -> str:
    """세션 전체 되돌리기 통지의 둘째 줄 — 데이터도 함께 되돌렸는가."""
    if not data_changed:
        return ""
    if base_bound:
        return "\n데이터도 이 작업에 연결된 것으로 되돌렸습니다."
    return "\n고른 데이터도 함께 내려놨습니다."


# ------------------------------------------------------------------ 데이터 채택


@dataclass(frozen=True)
class EditorDataSnapshot:
    path: str
    sheet: str
    header_row: int
    kind: str
    pool_key: str
    fields: list[str]
    records: list[dict]


def binding_source_ref(job: Job) -> dict | None:
    """저장본의 데이터 결속을 다시 읽을 참조 — 결속이 없으면 ``None``."""
    if not has_data_binding(job):
        return None
    path, sheet, header_row, kind = data_binding_of(job)
    return {"path": path, "sheet": sheet, "header_row": header_row, "kind": kind}


class EditorDataMount:
    """세션 데이터의 채택·포획·복원을 소유한다."""

    def __init__(
        self,
        edit: EditSession,
        *,
        rederive_job_name: Callable[[], None],
        push: Callable[[], None],
    ) -> None:
        self.edit = edit
        self._rederive_job_name = rederive_job_name
        self._push = push

    def load_path(
        self, path: str, *, sheet: "str | None" = None, header_row: int = 0, emit_push: bool = True
    ) -> None:
        """파일(엑셀/CSV) 하나를 이 세션의 데이터로."""
        opts: "dict[str, object]" = {"sheet": sheet}
        if header_row:
            opts["header_row"] = header_row
        source = source_for_path(path, **opts)
        self.adopt(
            source,
            source.records(),
            path=path,
            sheet=sheet or "",
            header_row=header_row,
            kind="",
            emit_push=emit_push,
        )

    def adopt_pclm(self, db: str, view: str, *, emit_push: bool = True) -> None:
        """계약 목록 db 의 뷰 하나를 이 세션의 데이터로."""
        source = source_from_pool_item(pclm_reference(db, view))
        self.adopt(
            source,
            source.records(),
            path=db,
            sheet=view,
            header_row=0,
            kind="pclm",
            emit_push=emit_push,
        )

    def adopt(
        self,
        source,
        records: list,
        *,
        path: str,
        sheet: str,
        header_row: int,
        kind: str,
        emit_push: bool = True,
    ) -> None:
        """읽은 소스를 채택한다 — 행이 없으면 세션을 바꾸지 않고 거절한다."""
        if not records:
            raise ValueError(NO_ROWS_TEXT)
        self.edit.data_path = path
        self.edit.data_sheet = sheet
        self.edit.data_header_row = header_row
        self.edit.data_kind = kind
        self.edit.data_pool_key = ""
        self.edit.data_name_cache = None
        self.edit.source_fields = source.fields()
        self.edit.records = records
        self.edit.preview_index = 0
        if self.edit.model is not None:
            before = self.edit.model_key
            ensure_model(self.edit)
            if self.edit.model_key == before:
                self.edit.model.apply_active_sources(
                    self.edit.source_fields, vocabulary=self.edit.source_fields
                )
        self._rederive_job_name()
        if emit_push:
            self._push()

    def load_source_ref(self, source_ref: dict, *, emit_push: bool = True) -> None:
        """포획한 결속 참조(경로·시트·헤더 행·종류 한 벌)를 다시 읽어 채택한다."""
        source = source_for_binding(source_ref)
        header = source_ref.get("header_row")
        kind = str(source_ref.get("kind") or "")
        self.adopt(
            source,
            source.records(),
            path=str(source_ref.get("path") or ""),
            sheet=str(source_ref.get("sheet") or ""),
            header_row=header
            if not kind and isinstance(header, int) and (not isinstance(header, bool))
            else 0,
            kind=kind,
            emit_push=emit_push,
        )

    def mount_pool_item(self, item) -> list:
        """등록 데이터 항목 하나를 마운트한다(``load_pool_into`` 의 loader)."""
        path, sheet, header_row, kind = pool_reference_quad(item)
        if not path:
            raise ValueError(f"'{item.name}' 은(는) 파일 참조가 아니라 연결할 수 없습니다.")
        if kind == "pclm":
            self.adopt_pclm(path, sheet, emit_push=False)
        else:
            self.load_path(path, sheet=sheet or None, header_row=header_row, emit_push=False)
        return self.edit.records

    def capture(self) -> EditorDataSnapshot:
        """지금 세션 데이터를 한 벌로 포획한다(되돌리기·닻의 재료)."""
        return EditorDataSnapshot(
            path=self.edit.data_path,
            sheet=self.edit.data_sheet,
            header_row=self.edit.data_header_row,
            kind=self.edit.data_kind,
            pool_key=self.edit.data_pool_key,
            fields=list(self.edit.source_fields),
            records=self.edit.records,
        )

    def restore(self, data: EditorDataSnapshot, *, rebuild_mapping: bool) -> None:
        """포획한 데이터를 다시 세운다 — 비어 있던 포획이면 무동작."""
        if not data.path:
            return
        self.edit.data_path = data.path
        self.edit.data_sheet = data.sheet
        self.edit.data_header_row = data.header_row
        self.edit.data_kind = data.kind
        self.edit.data_pool_key = data.pool_key
        self.edit.source_fields = data.fields
        self.edit.records = data.records
        if rebuild_mapping:
            ensure_model(self.edit)

    def anchor_stash(self) -> dict:
        """데이터로 연 진입이면 새 템플릿을 골라도 살릴 닻(문맥·데이터·진입 데이터)."""
        context = self.edit.context
        if context.entry_reason not in DATA_ANCHORED_ENTRY_REASONS or not self.edit.data_path:
            return {}
        return {
            "context": context,
            "data": self.capture(),
            "entry_data": dict(self.edit.entry_data),
        }

    def restore_anchor(self, anchor: dict) -> None:
        """:meth:`anchor_stash` 가 포획한 닻을 새 초안 위에 다시 세운다."""
        if not anchor:
            return
        self.restore(anchor["data"], rebuild_mapping=False)
        self.edit.entry_data = dict(anchor["entry_data"])
        self.edit.context = anchor["context"]
        self.edit.base = None


__all__ = [
    "EditorDataMount",
    "EditorDataSnapshot",
    "binding_source_ref",
    "discard_data_line",
    "ensure_model",
    "restore_job_mapping",
    "restore_report_lines",
    "revert_binding",
    "set_notice",
]
