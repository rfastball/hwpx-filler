"""Editor session I/O and snapshot owners."""

# ruff: noqa: BLE001
from __future__ import annotations

import json
import shutil
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..data.factory import (
    pclm_reference,
    source_for_binding,
    source_for_path,
    source_from_pool_item,
)
from ..domain.dataset_reference import STATUS_ACTIVE
from ..domain.job import Job, data_binding_of, has_data_binding, template_media
from ..domain.schema import FieldSpec, TemplateSchema, extract_schema, infer_type
from ..domain.template_status import library_display_name
from ..domain.text_render import SEG_MISSING, render_segments, template_fields
from ..external.dataset_store import DatasetPoolRegistry
from ..external.hwpx_package_io import read_hwpx_package
from ..external.job_store import JobRegistry
from ..external.template_root import TemplateRoot
from ..gui.edit_session import (
    DATA_ANCHORED_ENTRY_REASONS,
    SECTION_BINDING,
    SECTION_FILENAME,
    SECTION_TEMPLATE,
    EditSession,
    make_context,
    sections_for,
)
from ..gui.job_editor_state import (
    BINDING_CONFIRM_LABEL,
    EMPTY_PRESERVED,
    NAME_DERIVED_HINT,
    build_provenance,
    derive_job_name,
    needs_overwrite_confirm,
    overwrite_confirm_text,
    preserved_meta,
    validate_save,
)
from ..gui.mapping_state import (
    RAW_BLOCK_MESSAGE,
    MappingModel,
    gate_for_template,
    pairing_preview,
    profile_source_vocabulary,
    row_projection,
)
from ..gui.template_manager_state import CONVERT_ACTION_LABEL as RAW_CONVERT_LABEL
from ..gui.tutorial_state import Milestone
from ..gui.work_mode import work_mode_label
from .editor_presentation import binding_head, data_column_options, pattern_preview, sample_rows
from .output_folder_zone import output_folder_zone
from .pool_column import session_data_row
from .screens import (
    MUTATION_KINDS,
    NO_ROWS_TEXT,
    TXT_RAW_BLOCK,
    dataset_reference_identity,
    load_pool_into,
    pool_reference_quad,
    reference_missing,
    registered_dataset_entry,
)
from .template_groups import norm_library_path, rel_key

_SAMPLE_ROWS = 3
POOL_UNWIRED_TEXT = "등록 데이터 목록을 읽을 수 없습니다."
SESSION_DETAIL_OUTSIDE_TEXT = (
    "서식 폴더 밖의 템플릿이라 항목 상세를 열 수 없습니다. 설정에서 서식 폴더를 확인하세요."
)
SESSION_DETAIL_UNWIRED_TEXT = "템플릿 라이브러리 관문이 배선되지 않아 항목 상세를 열 수 없습니다."
PROVENANCE_DRIFT_TEXT = "작성 당시와 템릿 필드 구성이 다릅니다. 매핑 재검토가 필요할 수 있습니다."


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
    if not has_data_binding(job):
        return None
    path, sheet, header_row, kind = data_binding_of(job)
    return {"path": path, "sheet": sheet, "header_row": header_row, "kind": kind}


class EditorProjection:
    def __init__(
        self,
        edit: EditSession,
        *,
        pool_registry=None,
        template_root=None,
        remembered_output_directory=None,
        is_library_path=None,
        clock: Callable[[], datetime],
    ):
        self.edit = edit
        self._pool_registry = pool_registry
        self._template_root_holder = template_root
        self._remembered_output_directory = remembered_output_directory
        self._is_library_path = is_library_path
        self._clock = clock
        self.push: Callable[[], None] = lambda: None
        self._prepared: dict = {}

    def template_display_name(self) -> str:
        if not self.edit.template_path:
            return ""
        return library_display_name(self.template_root().path(), self.edit.template_path)

    def data_display_name(self) -> str:
        if not self.edit.data_path:
            return ""
        registered = self._registered_data_name()
        return registered or Path(self.edit.data_path).stem

    def _registered_data_entry(self) -> "tuple[str, str]":
        if self._pool_registry is None:
            return ("", "")
        ident = dataset_reference_identity(
            path=self.edit.data_path, sheet=self.edit.data_sheet, kind=self.edit.data_kind
        )
        if not ident:
            return ("", "")
        cached = self.edit.data_name_cache
        if cached is not None and cached[0] == ident:
            return (cached[1], cached[2])
        key, name = registered_dataset_entry(
            self._pool_registry,
            path=self.edit.data_path,
            sheet=self.edit.data_sheet,
            kind=self.edit.data_kind,
        )
        self.edit.data_name_cache = (ident, key, name)
        return (key, name)

    def _registered_data_name(self) -> str:
        return self._registered_data_entry()[1]

    def _derived_job_name(self) -> str:
        return derive_job_name(
            self.template_display_name().rsplit("/", 1)[-1], self.data_display_name()
        )

    def _rederive_job_name(self) -> None:
        if self.edit.job_name_is_derived:
            self.edit.job_name = self._derived_job_name()
            self.edit.derived_name_baseline = self.edit.job_name

    def template_root(self) -> TemplateRoot:
        if self._template_root_holder is None:
            self._template_root_holder = TemplateRoot()
        return self._template_root_holder

    def assert_library_path(self, path: str) -> None:
        gate = self._is_library_path
        if gate is None:
            raise ValueError("템플릿 라이브러리 관문이 배선되지 않아 경로를 확인할 수 없습니다.")
        if not gate(template_media(path), path):
            self.push()
            raise ValueError("라이브러리에 없는 템플릿입니다. 목록을 새로 고쳤으니 다시 고르세요.")

    def _template_ready(self) -> bool:
        return (
            self.edit.schema is not None
            and bool(self.edit.schema.fields)
            and (not self.edit.gate_error)
            and (self.edit.gate is None or self.edit.gate.can_proceed())
        )

    def sections(self) -> "tuple[str, ...]":
        return sections_for(
            template_media(self.edit.template_path) if self.edit.template_path else "hwpx"
        )

    def can_advance(self, from_section: str) -> bool:
        if from_section == SECTION_TEMPLATE:
            return self._template_ready() and bool(self.edit.data_path)
        if from_section == SECTION_BINDING:
            return self.edit.model is not None and self.edit.model.is_complete()
        return False

    def _advance_block_reason(self) -> str:
        if self.edit.raw_block:
            return self.edit.raw_block
        if self.edit.gate_error:
            return "템플릿 상태를 확인할 수 없습니다."
        if not self.edit.template_path:
            return "왼쪽에서 템플릿을 고르세요."
        if self.edit.schema is None or not self.edit.schema.fields:
            return RAW_BLOCK_MESSAGE
        if not self._template_ready():
            return "이 템플릿은 아직 진행할 수 없습니다. 미해결 토큰을 확인하세요."
        if not self.edit.data_path:
            return "오른쪽에서 데이터를 고르세요."
        return ""

    def _pairing_snapshot(self) -> dict:
        template_name = self.template_display_name()
        data_name = self.data_display_name()
        field_names = [f.name for f in self.edit.schema.fields] if self.edit.schema else []
        ready = bool(self.edit.template_path) and bool(self.edit.data_path) and bool(field_names)
        auto = confirm = 0
        basis = ""
        if ready and self.edit.section == SECTION_TEMPLATE:
            if self.edit.model is not None and self.edit.model_key == self.edit.model_key_now():
                auto = sum((1 for r in self.edit.model.rows if r.confirmed))
                confirm = len(self.edit.model.rows) - auto
                basis = "model"
            else:
                auto, confirm = self._pairing_preview_cached(field_names)
                basis = "preview"
        return {
            "ready": ready,
            "template_name": template_name,
            "data_name": data_name,
            "template_key": rel_key(self.edit.template_path, self.template_root().path())
            if self.edit.template_path
            else "",
            "data_key": self._registered_data_entry()[0],
            "data_row": self._pairing_data_row(),
            "field_count": len(field_names),
            "column_count": len(self.edit.source_fields),
            "auto_count": auto,
            "confirm_count": confirm,
            "basis": basis,
            "advance_block_reason": self._advance_block_reason(),
        }

    def _pairing_data_row(self) -> "dict | None":
        if not self.edit.data_path or self._registered_data_entry()[0]:
            return None
        return session_data_row(
            name=self.data_display_name(),
            kind=self.edit.data_kind,
            path=self.edit.data_path,
            sheet=self.edit.data_sheet,
            header_row=self.edit.data_header_row,
            record_count=len(self.edit.records),
        )

    def _pairing_preview_cached(self, field_names: "list[str]") -> "tuple[int, int]":
        key = self.edit.model_key_now()
        cached = self.edit.pairing_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        counts = pairing_preview(field_names, self.edit.source_fields)
        self.edit.pairing_cache = (key, counts)
        return counts

    def _row_snapshot(
        self, index: int, row, record: "dict", *, now: "datetime | None" = None
    ) -> dict:
        return row_projection(
            row,
            record,
            index=index,
            source_fields=self.edit.source_fields,
            has_records=bool(self.edit.records),
            now=now,
        )

    def prepare(self) -> None:
        now = self._clock()
        sections = self.sections()
        dirty = self.edit.dirty_sections()
        snap: dict = {
            "section": self.edit.section,
            "sections": list(sections),
            "reachable": {
                s: True if self.edit.editing_origin else self.can_advance(s) for s in sections
            },
            "is_draft": self.edit.is_draft,
            "dirty_sections": list(dirty),
            "dirty": bool(dirty) or self.edit.has_unsaved_work(),
            "changes": self.edit.changes(self.edit.draft_job()),
            "context": self.edit.context.to_dict(),
            "revisions": {
                "template": self.edit.base.template_revision,
                "binding": self.edit.base.binding_revision,
            }
            if self.edit.base is not None
            else {},
            "template_path": self.edit.template_path,
            "template_name": self.template_display_name(),
            "template_media": template_media(self.edit.template_path)
            if self.edit.template_path
            else "",
            "field_count": len(self.edit.schema.fields) if self.edit.schema else 0,
            "fields": [f.to_dict() for f in self.edit.schema.fields] if self.edit.schema else [],
            "raw_block": self.edit.raw_block,
            "session_detail": self._session_detail(),
            "schema_drift": self._provenance_drift(),
            "gate": self._gate_snapshot(),
            "gate_error": self.edit.gate_error,
            "data_path": self.edit.data_path,
            "data_name": self.data_display_name(),
            "data_sheet": self.edit.data_sheet,
            "data_header_row": self.edit.data_header_row,
            "data_kind": self.edit.data_kind,
            "data_pool_key": self.edit.data_pool_key,
            "record_count": len(self.edit.records),
            "source_fields": self.edit.source_fields,
            "data_column_options": data_column_options(self.edit.source_fields),
            "sample_rows": sample_rows(self.edit.source_fields, self.edit.records, _SAMPLE_ROWS),
            "name": self.edit.job_name,
            "job_name_is_derived": self.edit.job_name_is_derived,
            "name_hint": NAME_DERIVED_HINT if self.edit.job_name_is_derived else "",
            "pattern": self.edit.pattern,
            "output_folder": self._output_folder_zone(),
            "binding_confirm": {
                "pending": self.edit.binding_confirm_pending,
                "label": BINDING_CONFIRM_LABEL,
            },
            "unconfirm_undo_count": len(self.edit.unconfirm_undo),
            "editing_origin": self.edit.editing_origin,
            "pairing": self._pairing_snapshot(),
            "pattern_preview": pattern_preview(
                self.edit.pattern, self.edit.model, self.edit.records, now
            )
            if self.edit.section == SECTION_FILENAME
            and template_media(self.edit.template_path) != "txt"
            and self.edit.pattern
            else "",
            "notice": {"text": self.edit.notice_text, "level": self.edit.notice_level}
            if self.edit.notice_text
            else None,
        }
        if self.edit.model is not None:
            schema_only = self.edit.model.is_schema_only()
            record = self.edit.current_record()
            snap["rows"] = [
                self._row_snapshot(i, r, record, now=now)
                for i, r in enumerate(self.edit.model.rows)
            ]
            filled, empty, unmapped = self.edit.model.preview_counts(record, now=now)
            snap["counts"] = {"filled": filled, "empty": empty, "unmapped": unmapped}
            snap["preview_empties"] = self.edit.model.preview_empties(record, now=now)
            snap["preview_index"] = (
                self.edit.preview_index % len(self.edit.records) + 1 if self.edit.records else 0
            )
            snap["preview_count"] = len(self.edit.records)
            snap["is_complete"] = self.edit.model.is_complete()
            snap["schema_only"] = schema_only
            snap["binding_head"] = binding_head(self.edit.model)
        else:
            snap["rows"] = []
            snap["is_complete"] = False
            snap["binding_head"] = binding_head(self.edit.model)
        self._prepared = deepcopy(snap)

    def snapshot(self) -> dict:
        """Return the last operation-prepared projection without I/O or clocks."""
        return deepcopy(self._prepared)

    def _output_folder_zone(self) -> "dict[str, str] | None":
        if not self.edit.template_path or template_media(self.edit.template_path) == "txt":
            return None
        remembered = self._remembered_output_directory
        return output_folder_zone(
            template_path=self.edit.template_path,
            remembered_directory=remembered() if remembered is not None else "",
        )

    def _session_detail(self) -> dict:
        if not self.edit.template_path:
            return {"available": False, "reason": ""}
        cached = self.edit.session_detail_cache
        if cached is not None and cached[0] == self.edit.template_path:
            return cached[1]
        gate = self._is_library_path
        if gate is None:
            value = {"available": False, "reason": SESSION_DETAIL_UNWIRED_TEXT}
        else:
            try:
                live = bool(gate(template_media(self.edit.template_path), self.edit.template_path))
            except Exception:
                live = False
            value = (
                {"available": True, "reason": ""}
                if live
                else {"available": False, "reason": SESSION_DETAIL_OUTSIDE_TEXT}
            )
        self.edit.session_detail_cache = (self.edit.template_path, value)
        return value

    def _provenance_drift(self) -> str:
        recorded = self.edit.loaded_provenance.get("template_fields", "")
        if not recorded or self.edit.schema is None or (not self.edit.schema.fields):
            return ""
        if recorded == " · ".join(self.edit.schema.field_names()):
            return ""
        return PROVENANCE_DRIFT_TEXT

    def _gate_snapshot(self) -> "dict | None":
        g = self.edit.gate
        if g is None or not g.needs_gate():
            return None
        return {"message": g.message(), "unmet": list(g.unmet_tokens), "acked": g.is_acked()}

    def initial(self) -> dict:
        self.prepare()
        return self.snapshot()


class EditorLoader:
    SECTION_LABELS = {
        SECTION_TEMPLATE: "고르기",
        SECTION_BINDING: "연결 확인",
        SECTION_FILENAME: "이름·저장",
    }

    def __init__(
        self,
        edit: EditSession,
        projection: EditorProjection,
        registry: JobRegistry,
        *,
        pool_registry=None,
        tutorial=None,
        binding_confirm_pending=None,
    ):
        self.edit = edit
        self.projection = projection
        self.registry = registry
        self._pool_registry = pool_registry
        self._tutorial = tutorial or (lambda milestone: None)
        self._binding_confirm_pending_probe = binding_confirm_pending
        self.push: Callable[[], None] = lambda: None

    def _set_notice(self, text: str, level: str = "muted") -> None:
        self.edit.notice_text = text
        self.edit.notice_level = level

    def _refresh_binding_confirm_pending(self) -> None:
        probe = self._binding_confirm_pending_probe
        if probe is None or not self.edit.editing_origin or (not self.edit.job_name):
            self.edit.binding_confirm_pending = False
            return
        try:
            self.edit.binding_confirm_pending = bool(probe(self.edit.job_name))
        except Exception:
            self.edit.binding_confirm_pending = False

    def new_job_session(self, path: str) -> None:
        anchor = self._anchor_stash()
        self.edit.reset()
        self._restore_anchor(anchor)
        self.load_template_path(path)

    def _anchor_stash(self) -> "dict":
        context = self.edit.context
        if context.entry_reason not in DATA_ANCHORED_ENTRY_REASONS or not self.edit.data_path:
            return {}
        return {
            "context": context,
            "data": self._data_snapshot(),
            "entry_data": dict(self.edit.entry_data),
        }

    def _restore_anchor(self, anchor: "dict") -> None:
        if not anchor:
            return
        self._restore_data_snapshot(anchor["data"], rebuild_mapping=False)
        self.edit.entry_data = dict(anchor["entry_data"])
        self.edit.context = anchor["context"]
        self.edit.base = None

    def new_draft_with_data(
        self,
        source_ref: dict,
        *,
        entry_reason: str = "voluntary",
        evidence: "dict | None" = None,
        return_context: "dict | None" = None,
    ) -> None:
        context = make_context(
            "", entry_reason=entry_reason, evidence=evidence, return_context=return_context
        )
        self.edit.reset()
        self.edit.context = context
        self._load_source_ref(source_ref)
        self.edit.entry_data = {
            "data_path": self.edit.data_path,
            "data_sheet": self.edit.data_sheet,
        }

    def _do_use_library_template(self, p: dict) -> None:
        path = str(p["path"])
        self.projection.assert_library_path(path)
        if self.edit.template_path and norm_library_path(path) == norm_library_path(
            self.edit.template_path
        ):
            return
        self.new_job_session(path)
        self._tutorial(Milestone.PICK_TEMPLATE)

    def adopt_imported_template(self, dest: str) -> str:
        path = Path(dest)
        if path.suffix.lower() == ".hwpx":
            try:
                schema = extract_schema(read_hwpx_package(path))
            except Exception:
                self._set_notice(
                    f"'{path.name}' 을 가져왔지만 읽을 수 없습니다. 목록의 행 ⋮ → '자세히…'에서 사유를 보거나 '폴더에서 보기'로 파일을 확인하세요.",
                    "warn",
                )
                self.push()
                return path.name
            if not schema.fields:
                self._set_notice(
                    f"'{path.name}' 은 누름틀이 없는 원본(RAW)입니다. 목록의 행 ⋮ → '{RAW_CONVERT_LABEL}'을 거친 뒤 시작하세요.",
                    "warn",
                )
                self.push()
                return path.name
        else:
            try:
                path.read_text(encoding="utf-8")
            except Exception:
                self._set_notice(
                    f"'{path.name}' 을 가져왔지만 읽을 수 없습니다(UTF-8 아님). 목록의 행 ⋮ → '자세히…'에서 사유를 보거나 '폴더에서 보기'로 파일을 확인하세요.",
                    "warn",
                )
                self.push()
                return path.name
        self.new_job_session(str(path))
        self._set_notice(f"'{path.name}' 을 라이브러리로 복사해 시작합니다.", "ok")
        self.push()
        return path.name

    def load_template_path(self, path: str, *, emit_push: bool = True) -> None:
        self.edit.clean = False
        self.edit.session_detail_cache = None
        self.edit.template_path = path
        self.projection._rederive_job_name()
        self.edit.gate = None
        self.edit.gate_error = False
        self.edit.raw_block = ""
        if template_media(path) == "txt":
            self._load_txt_template(path)
            if emit_push:
                self.push()
            return
        pkg = read_hwpx_package(path)
        self.edit.schema = extract_schema(pkg)
        if not self.edit.schema.fields:
            self.edit.raw_block = RAW_BLOCK_MESSAGE
            self.edit.schema = None
            if emit_push:
                self.push()
            return
        try:
            self.edit.gate = gate_for_template(pkg)
        except Exception:
            self.edit.gate_error = True
        if emit_push:
            self.push()

    def reconcile_template_mutation(self, kind: str, path: str) -> None:
        if kind not in MUTATION_KINDS:
            raise ValueError(f"알 수 없는 템플릿 변이 종류: {kind!r}")
        if not self.edit.template_path:
            return
        if norm_library_path(self.edit.template_path) != norm_library_path(path):
            return
        if kind == "deleted":
            self._set_notice(
                "편집 중인 템플릿이 삭제됐습니다. 되돌리거나 다른 템플릿을 선택하세요.", "danger"
            )
            self.push()
            return
        self.load_template_path(self.edit.template_path, emit_push=False)
        if self.edit.schema is None:
            self.edit.model = None
            self.edit.model_key = None
            self.edit.unconfirm_undo = []
            self._set_notice(
                "편집 중인 템플릿 파일이 바뀌어 채울 항목이 없어졌습니다. 되돌리거나 다른 템플릿을 선택하세요.",
                "danger",
            )
            self.push()
            return
        message = "편집 중인 템플릿 파일이 바뀌어 세션을 다시 읽었습니다."
        if self.edit.model is not None:
            before = self.edit.notice_text
            self.edit.model_key = None
            self._ensure_model()
            if self.edit.notice_text != before:
                message = f"{message}\n{self.edit.notice_text}"
        self._set_notice(message, "warn")
        self.push()

    def _load_txt_template(self, path: str) -> None:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"TXT 템플릿을 읽을 수 없습니다: {exc}") from exc
        segments, _report = render_segments(text, {})
        occurrences: "dict[str, int]" = {}
        for seg in segments:
            if seg.kind == SEG_MISSING:
                occurrences[seg.name] = occurrences.get(seg.name, 0) + 1
        names = template_fields(text)
        if not names:
            self.edit.raw_block = TXT_RAW_BLOCK
            self.edit.schema = None
            return
        self.edit.schema = TemplateSchema(
            fields=[
                FieldSpec(
                    name=n,
                    inferred_type=infer_type(n),
                    occurrences=occurrences.get(n, 1),
                    in_table=False,
                )
                for n in names
            ]
        )

    def load_data_path(
        self, path: str, *, sheet: "str | None" = None, header_row: int = 0, emit_push: bool = True
    ) -> None:
        opts: "dict[str, object]" = {"sheet": sheet}
        if header_row:
            opts["header_row"] = header_row
        source = source_for_path(path, **opts)
        self._adopt_datasource(
            source,
            source.records(),
            path=path,
            sheet=sheet or "",
            header_row=header_row,
            kind="",
            emit_push=emit_push,
        )

    def _adopt_pclm(self, db: str, view: str, *, emit_push: bool = True) -> None:
        source = source_from_pool_item(pclm_reference(db, view))
        self._adopt_datasource(
            source,
            source.records(),
            path=db,
            sheet=view,
            header_row=0,
            kind="pclm",
            emit_push=emit_push,
        )

    def _adopt_datasource(
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
        if not records:
            raise ValueError(NO_ROWS_TEXT)
        self.edit.clean = False
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
            self._ensure_model()
            if self.edit.model_key == before:
                self.edit.model.apply_active_sources(
                    self.edit.source_fields, vocabulary=self.edit.source_fields
                )
        self.projection._rederive_job_name()
        if emit_push:
            self.push()

    def _load_source_ref(self, source_ref: dict, *, emit_push: bool = True) -> None:
        source = source_for_binding(source_ref)
        header = source_ref.get("header_row")
        kind = str(source_ref.get("kind") or "")
        self._adopt_datasource(
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

    def load_job(
        self,
        name: str,
        *,
        landing_section: str = SECTION_BINDING,
        emit_push: bool = True,
        entry_reason: str = "voluntary",
        evidence: "dict | None" = None,
        return_context: "dict | None" = None,
        target: str = "",
        source_ref: "dict | None" = None,
    ) -> None:
        job = self.registry.load(name)
        context = make_context(
            job.name,
            entry_reason=entry_reason,
            evidence=evidence,
            return_context=return_context,
            target=target,
        )
        if context.target:
            landing_section = context.target.partition("/")[0]
        self._restore_from(
            job,
            landing_section=landing_section,
            context=context,
            emit_push=emit_push,
            source_ref=source_ref,
        )

    def _restore_from(
        self,
        job: "Job",
        *,
        landing_section: str,
        context,
        emit_push: bool = True,
        keep_data: bool = False,
        source_ref: "dict | None" = None,
        probe_binding: bool = True,
    ) -> None:
        if not Path(job.template_path).exists():
            raise ValueError(
                f"템플릿 파일을 찾을 수 없습니다: {job.template_path}\n파일을 되돌리거나, 홈/작업 화면의 [템플릿 다시 연결…]로 경로를 바꾸세요."
            )
        data_snapshot = self._data_snapshot() if keep_data else None
        entry_data = dict(self.edit.entry_data) if keep_data else None
        self.edit.reset()
        self.load_template_path(job.template_path, emit_push=False)
        if self.edit.schema is None:
            raise ValueError(self.edit.raw_block or RAW_BLOCK_MESSAGE)
        if self.edit.gate_error:
            raise ValueError("템플릿 상태를 확인할 수 없어 편집을 열 수 없습니다.")
        handoff_failure = ""
        carried_ref = source_ref if source_ref else None if keep_data else binding_source_ref(job)
        if carried_ref:
            try:
                self._load_source_ref(carried_ref, emit_push=False)
            except Exception as exc:
                handoff_failure = str(exc)
        carried_data = bool(self.edit.data_path)
        self.edit.entry_data = {
            "data_path": self.edit.data_path,
            "data_sheet": self.edit.data_sheet,
        }
        self.edit.job_name = job.name
        self.edit.job_name_is_derived = False
        self.edit.pattern = job.filename_pattern
        self.edit.editing_origin = job.name
        self.edit.preserved_meta = preserved_meta(job)
        self.edit.editing_fingerprint = self.registry.content_fingerprint(job)
        self.edit.loaded_provenance = dict(job.mapping.provenance)
        if not carried_data:
            self.edit.source_fields = profile_source_vocabulary(job.mapping)
        self.edit.model = MappingModel.from_suggestions(self.edit.schema, self.edit.source_fields)
        self.edit.model.apply_profile(job.mapping, require_source=carried_data)
        self.edit.model_key = self.edit.model_key_now()
        self.edit.context = replace(context, work=job.name)
        self.edit.base = job
        self.edit.section = (
            landing_section if landing_section in self.projection.sections() else SECTION_BINDING
        )
        if data_snapshot is not None:
            self._restore_data_snapshot(data_snapshot, rebuild_mapping=True)
        if entry_data is not None:
            self.edit.entry_data = entry_data
        row_fields = {r.template_field for r in self.edit.model.rows}
        dropped = [
            m.template_field for m in job.mapping.mappings if m.template_field not in row_fields
        ]
        saved_fields = {m.template_field for m in job.mapping.mappings}
        fresh = [
            r.template_field
            for r in self.edit.model.rows
            if not r.confirmed and r.template_field not in saved_fields
        ]
        detached = [
            r.template_field
            for r in self.edit.model.rows
            if not r.confirmed and r.template_field in saved_fields
        ]
        lines: list[str] = []
        if dropped:
            lines.append(
                f"템플릿에 더는 없는 저장 필드 {len(dropped)}개는 제외했습니다: "
                + ", ".join(dropped)
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
        self.edit.reload_failure = handoff_failure
        if handoff_failure:
            lines.append(f"연결된 데이터를 다시 읽지 못했습니다: {handoff_failure}")
        self._set_notice("\n".join(lines), "warn" if lines else "ok")
        self.edit.clean = True
        if probe_binding:
            self._refresh_binding_confirm_pending()
        if emit_push:
            self.push()

    def restore_saved(self, job: Job) -> None:
        """Land a committed job without push or a nested binding-store probe."""
        self._restore_from(
            job,
            landing_section=self.edit.section,
            context=self.edit.context,
            emit_push=False,
            probe_binding=False,
        )

    def _data_snapshot(self) -> EditorDataSnapshot:
        return EditorDataSnapshot(
            path=self.edit.data_path,
            sheet=self.edit.data_sheet,
            header_row=self.edit.data_header_row,
            kind=self.edit.data_kind,
            pool_key=self.edit.data_pool_key,
            fields=list(self.edit.source_fields),
            records=self.edit.records,
        )

    def _restore_data_snapshot(self, data: EditorDataSnapshot, *, rebuild_mapping: bool) -> None:
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
            self._ensure_model()

    def _do_new_session(self, p: dict) -> None:
        self.edit.reset()

    def _do_discard_session(self, p: dict) -> None:
        if self.edit.editing_origin:
            raise ValueError("저장된 작업 편집은 신규 마법사 취소로 닫을 수 없습니다.")
        self.edit.reset()

    def _do_goto_section(self, p: dict) -> None:
        target = str(p["section"])
        sections = self.projection.sections()
        if target not in sections:
            raise ValueError(f"이 작업에는 '{target}' 탭이 없습니다.")
        discarded: "set[str]" = set()
        while True:
            blocking = self.edit.blocking_section(
                self.edit.draft_job(), target, pending_binding=self.edit.pending_binding()
            )
            if not blocking:
                break
            if blocking in discarded:
                raise ValueError(
                    f"「{self.SECTION_LABELS.get(blocking, blocking)}」 에서 바꾼 것을 되돌리지 못해 이동할 수 없습니다."
                )
            discarded.add(blocking)
            self._do_discard_patch({"section": blocking})
        if not self.edit.editing_origin:
            here, there = (sections.index(self.edit.section), sections.index(target))
            for s in sections[here:there]:
                if not self.projection.can_advance(s):
                    raise ValueError(
                        f"「{self.SECTION_LABELS.get(s, s)}」 조건을 아직 채우지 못해 다음으로 갈 수 없습니다."
                    )
        if target == SECTION_BINDING:
            self._ensure_model()
        self.edit.section = target
        self.edit.section = target

    def _do_discard_patch(self, p: dict) -> None:
        if self.edit.is_draft or self.edit.base is None:
            raise ValueError("아직 저장하지 않은 새 작업이라 되돌릴 이전 상태가 없습니다.")
        base = self.edit.base
        section = str(p.get("section") or "")
        if not section:
            restored_ref = data_binding_of(base)
            data_changed = (
                self.edit.data_path,
                self.edit.data_sheet,
                self.edit.data_header_row,
                self.edit.data_kind,
            ) != restored_ref
            if not data_changed and (not self.edit.has_unsaved_work()):
                return
            base_bound = has_data_binding(base)
            self._restore_from(
                base, landing_section=self.edit.section, context=self.edit.context, emit_push=False
            )
            if not data_changed:
                data_line = ""
            elif base_bound:
                data_line = "\n데이터도 이 작업에 연결된 것으로 되돌렸습니다."
            else:
                data_line = "\n고른 데이터도 함께 내려놨습니다."
            self._set_notice("바꾼 내용을 버리고 저장된 상태로 되돌렸습니다." + data_line, "ok")
            return
        if section not in self.projection.sections():
            raise ValueError(f"이 작업에는 '{section}' 탭이 없습니다.")
        if section == SECTION_FILENAME:
            self.edit.pattern = base.filename_pattern
        elif section == SECTION_BINDING:
            self._revert_binding(base)
        else:
            name = self.edit.job_name
            self._restore_from(
                base,
                landing_section=self.edit.section,
                context=self.edit.context,
                emit_push=False,
                keep_data=True,
            )
            self.edit.job_name = name
        self._set_notice(
            f"「{self.SECTION_LABELS.get(section, section)}」 에서 바꾼 것만 되돌렸습니다.", "ok"
        )

    def _revert_binding(self, base: "Job") -> None:
        if self.edit.schema is None:
            return
        vocabulary = list(self.edit.source_fields) or profile_source_vocabulary(base.mapping)
        if not self.edit.data_path:
            self.edit.source_fields = profile_source_vocabulary(base.mapping)
            vocabulary = self.edit.source_fields
        self.edit.model = MappingModel.from_suggestions(self.edit.schema, vocabulary)
        self.edit.model.apply_profile(base.mapping)
        self.edit.model_key = self.edit.model_key_now()

    def _do_dismiss_notice(self, p: dict) -> None:
        self._set_notice("", "muted")

    def _do_ack_gate(self, p: dict) -> None:
        if self.edit.gate is None:
            raise ValueError("확인할 항목이 없습니다.")
        self.edit.gate.acknowledge(self.edit.gate.unmet_tokens)

    def _mount_pool_item(self, item) -> list:
        path, sheet, header_row, kind = pool_reference_quad(item)
        if not path:
            raise ValueError(f"'{item.name}' 은(는) 파일 참조가 아니라 연결할 수 없습니다.")
        if kind == "pclm":
            self._adopt_pclm(path, sheet, emit_push=False)
        else:
            self.load_data_path(path, sheet=sheet or None, header_row=header_row, emit_push=False)
        return self.edit.records

    def _do_use_pool_data(self, p: dict) -> dict:
        if self._pool_registry is None:
            return {"ok": False, "error": POOL_UNWIRED_TEXT}
        key = str(p["key"])
        res = load_pool_into(self._pool_registry, key, self._mount_pool_item)
        if not res["ok"]:
            return {"ok": False, "error": res["error"]}
        self.edit.data_pool_key = key
        self.edit.data_name_cache = None
        self.projection._rederive_job_name()
        return {"ok": True, "label": res["item"].name}

    def _ensure_model(self) -> None:
        if self.edit.schema is None:
            raise ValueError("템플릿이 로드되지 않았습니다.")
        key = self.edit.model_key_now()
        if self.edit.model is not None and self.edit.model_key == key:
            return
        prior = None
        if self.edit.model is not None:
            carried_prior = self.edit.model.carry_profile()
            if carried_prior.mappings:
                prior = carried_prior
        self.edit.model = MappingModel.from_suggestions(self.edit.schema, self.edit.source_fields)
        self.edit.unconfirm_undo = []
        if prior is not None:
            carried = self.edit.model.apply_profile(prior, confirm=False)
            self._set_notice(
                f"템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다. 확정했거나 직접 편집한 {carried}개 행의 소스·유형·서식은 이월했지만, 저장하려면 전 행을 다시 확정하세요.",
                "warn",
            )
        self.edit.model_key = key


__all__ = ["EditorLoader", "EditorProjection"]
