"""Editor session I/O and snapshot owners.

편집기 세션 하나(:class:`~hwpxfiller.viewmodel.edit_session.EditSession`)를 두 소유자가 다룬다.

- :class:`EditorProjection` — 스냅샷 **조립**만 한다. 판정과 조회는 협력자가 진다:
  데이터 정체(등록 조회·표시명·시트 탭·세션 행)는 :class:`~.editor_sources.EditorDataIdentity`,
  템플릿의 서식 폴더 쪽 사실(표시명·관문·항목 상세·저장 폴더)은
  :class:`~.editor_sources.EditorTemplateLibrary`, 단계 관문과 표면 모양 성형은
  :mod:`.editor_presentation`.
- :class:`EditorLoader` — 세션 진입·템플릿 반입·저장본 복원·탭 이동·되돌리기 동사.
  템플릿 읽기는 :func:`~.editor_sources.read_template_intake`, 데이터 채택은
  :class:`~.editor_transitions.EditorDataMount`, 매핑 초안 재조립·되돌리기와 그 재진술은
  :mod:`.editor_transitions` 의 함수가 진다.
"""

# ruff: noqa: BLE001
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..domain.job import Job, data_binding_of, has_data_binding
from ..domain.schema import extract_schema
from ..external.hwpx_package_io import read_hwpx_package
from ..external.job_store import JobRegistry
from ..external.template_root import TemplateRoot
from ..viewmodel.edit_session import (
    SECTION_BINDING,
    SECTION_FILENAME,
    SECTION_TEMPLATE,
    EditSession,
    make_context,
)
from ..viewmodel.job_editor_state import (
    BINDING_CONFIRM_LABEL,
    NAME_DERIVED_HINT,
    derive_job_name,
    preserved_meta,
)
from ..viewmodel.mapping_state import RAW_BLOCK_MESSAGE
from ..viewmodel.template_manager_state import CONVERT_ACTION_LABEL as RAW_CONVERT_LABEL
from ..viewmodel.tutorial_state import Milestone
from .editor_presentation import (
    advance_block_reason,
    binding_snapshot,
    can_advance,
    data_column_options,
    editor_sections,
    filename_preview,
    gate_snapshot,
    pairing_counts,
    provenance_drift,
    sample_rows,
    template_shape,
)
from .editor_sources import EditorDataIdentity, EditorTemplateLibrary, read_template_intake
from .editor_transitions import (
    EditorDataMount,
    binding_source_ref,
    discard_data_line,
    ensure_model,
    restore_job_mapping,
    restore_report_lines,
    revert_binding,
    set_notice,
)
from .screens import MUTATION_KINDS, load_pool_into
from .template_groups import norm_library_path, rel_key

_SAMPLE_ROWS = 3
POOL_UNWIRED_TEXT = "등록 데이터 목록을 읽을 수 없습니다."


class EditorProjection:
    """편집기 스냅샷의 조립자 — 연산마다 한 번 :meth:`prepare` 해 두고 그대로 낸다."""

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
        self.data = EditorDataIdentity(edit, pool_registry=pool_registry)
        self.library = EditorTemplateLibrary(
            edit,
            template_root=template_root,
            is_library_path=is_library_path,
            remembered_output_directory=remembered_output_directory,
        )
        self._clock = clock
        self.push: Callable[[], None] = lambda: None
        self._prepared: dict = {}

    def template_root(self) -> TemplateRoot:
        return self.library.root()

    def data_display_name(self) -> str:
        return self.data.display_name()

    def rederive_job_name(self) -> None:
        """이름을 사람이 고치지 않았으면 템플릿·데이터 표시명에서 다시 짓는다."""
        if self.edit.job_name_is_derived:
            self.edit.job_name = derive_job_name(
                self.library.display_name().rsplit("/", 1)[-1], self.data.display_name()
            )
            self.edit.derived_name_baseline = self.edit.job_name

    def assert_library_path(self, path: str) -> None:
        if not self.library.is_live(path):
            self.push()
            raise ValueError("라이브러리에 없는 템플릿입니다. 목록을 새로 고쳤으니 다시 고르세요.")

    def sections(self) -> "tuple[str, ...]":
        return editor_sections(self.edit)

    def can_advance(self, from_section: str) -> bool:
        return can_advance(self.edit, from_section)

    def _pairing_snapshot(self) -> dict:
        """고르기 단계의 조합 카드 — 두 열의 「지금 선 행」 키와 자동·확인 수."""
        field_names = [f.name for f in self.edit.schema.fields] if self.edit.schema else []
        ready = bool(self.edit.template_path) and bool(self.edit.data_path) and bool(field_names)
        auto, confirm, basis = pairing_counts(self.edit, field_names, ready)
        return {
            "ready": ready,
            "template_name": self.library.display_name(),
            "data_name": self.data.display_name(),
            "template_key": rel_key(self.edit.template_path, self.library.root().path())
            if self.edit.template_path
            else "",
            "data_key": self.data.registered_entry()[0],
            "data_row": self.data.session_row(),
            "field_count": len(field_names),
            "column_count": len(self.edit.source_fields),
            "auto_count": auto,
            "confirm_count": confirm,
            "basis": basis,
            "advance_block_reason": advance_block_reason(self.edit),
        }

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
            "template_name": self.library.display_name(),
            **template_shape(self.edit),
            "raw_block": self.edit.raw_block,
            "session_detail": self.library.session_detail(),
            "schema_drift": provenance_drift(self.edit.loaded_provenance, self.edit.schema),
            "gate": gate_snapshot(self.edit.gate),
            "gate_error": self.edit.gate_error,
            "data_path": self.edit.data_path,
            "data_name": self.data.display_name(),
            "data_sheet": self.edit.data_sheet,
            "data_header_row": self.edit.data_header_row,
            "data_kind": self.edit.data_kind,
            "data_pool_key": self.edit.data_pool_key,
            "data_sheet_tabs": self.data.sheet_tabs(),
            "record_count": len(self.edit.records),
            "source_fields": self.edit.source_fields,
            "data_column_options": data_column_options(self.edit.source_fields),
            "sample_rows": sample_rows(self.edit.source_fields, self.edit.records, _SAMPLE_ROWS),
            "name": self.edit.job_name,
            "job_name_is_derived": self.edit.job_name_is_derived,
            "name_hint": NAME_DERIVED_HINT if self.edit.job_name_is_derived else "",
            "pattern": self.edit.pattern,
            "output_folder": self.library.output_folder(),
            "binding_confirm": {
                "pending": self.edit.binding_confirm_pending,
                "label": BINDING_CONFIRM_LABEL,
            },
            "unconfirm_undo_count": len(self.edit.unconfirm_undo),
            "editing_origin": self.edit.editing_origin,
            "pairing": self._pairing_snapshot(),
            "pattern_preview": filename_preview(self.edit, now),
            "notice": {"text": self.edit.notice_text, "level": self.edit.notice_level}
            if self.edit.notice_text
            else None,
        }
        snap.update(binding_snapshot(self.edit, now))
        self._prepared = deepcopy(snap)

    def snapshot(self) -> dict:
        """Return the last operation-prepared projection without I/O or clocks."""
        return deepcopy(self._prepared)

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
        # 데이터 채택의 push 는 늦게 배선되는 ``self.push`` 를 그때그때 부른다.
        self.data = EditorDataMount(
            edit, rederive_job_name=projection.rederive_job_name, push=lambda: self.push()
        )

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
        anchor = self.data.anchor_stash()
        self.edit.reset()
        self.data.restore_anchor(anchor)
        self.load_template_path(path)

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
        self.data.load_source_ref(source_ref)
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
                set_notice(
                    self.edit,
                    f"'{path.name}' 을 가져왔지만 읽을 수 없습니다. 목록의 행 ⋮ → '자세히…'에서 사유를 보거나 '폴더에서 보기'로 파일을 확인하세요.",
                    "warn",
                )
                self.push()
                return path.name
            if not schema.fields:
                set_notice(
                    self.edit,
                    f"'{path.name}' 은 누름틀이 없는 원본(RAW)입니다. 목록의 행 ⋮ → '{RAW_CONVERT_LABEL}'을 거친 뒤 시작하세요.",
                    "warn",
                )
                self.push()
                return path.name
        else:
            try:
                path.read_text(encoding="utf-8")
            except Exception:
                set_notice(
                    self.edit,
                    f"'{path.name}' 을 가져왔지만 읽을 수 없습니다(UTF-8 아님). 목록의 행 ⋮ → '자세히…'에서 사유를 보거나 '폴더에서 보기'로 파일을 확인하세요.",
                    "warn",
                )
                self.push()
                return path.name
        self.new_job_session(str(path))
        set_notice(self.edit, f"'{path.name}' 을 라이브러리로 복사해 시작합니다.", "ok")
        self.push()
        return path.name

    def load_template_path(self, path: str, *, emit_push: bool = True) -> None:
        self.edit.session_detail_cache = None
        self.edit.template_path = path
        self.projection.rederive_job_name()
        # 읽기가 실패해도 앞 템플릿의 관문·사유가 남지 않게 먼저 비운다.
        self.edit.gate = None
        self.edit.gate_error = False
        self.edit.raw_block = ""
        intake = read_template_intake(path)
        self.edit.schema = intake.schema
        self.edit.gate = intake.gate
        self.edit.gate_error = intake.gate_error
        self.edit.raw_block = intake.raw_block
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
            set_notice(
                self.edit,
                "편집 중인 템플릿이 삭제됐습니다. 되돌리거나 다른 템플릿을 선택하세요.",
                "danger",
            )
            self.push()
            return
        self.load_template_path(self.edit.template_path, emit_push=False)
        if self.edit.schema is None:
            self.edit.model = None
            self.edit.model_key = None
            self.edit.unconfirm_undo = []
            set_notice(
                self.edit,
                "편집 중인 템플릿 파일이 바뀌어 채울 항목이 없어졌습니다. 되돌리거나 다른 템플릿을 선택하세요.",
                "danger",
            )
            self.push()
            return
        message = "편집 중인 템플릿 파일이 바뀌어 세션을 다시 읽었습니다."
        if self.edit.model is not None:
            before = self.edit.notice_text
            self.edit.model_key = None
            ensure_model(self.edit)
            if self.edit.notice_text != before:
                message = f"{message}\n{self.edit.notice_text}"
        set_notice(self.edit, message, "warn")
        self.push()

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
        """저장본 하나로 세션을 다시 세운다 — 템플릿·데이터·연결·문맥·통지 순서.

        ``keep_data`` 는 지금 세션 데이터를 살린 채 템플릿·연결만 저장본으로 되돌리는 갈래다
        (「고르기」 단계만 되돌리기). 실패하는 판정(템플릿 부재·RAW·관문 불명)은 세션을 비우기
        전에 또는 템플릿을 읽는 자리에서 시끄럽게 막는다.
        """
        if not Path(job.template_path).exists():
            raise ValueError(
                f"템플릿 파일을 찾을 수 없습니다: {job.template_path}\n파일을 되돌리거나, 홈/작업 화면의 [템플릿 다시 연결…]로 경로를 바꾸세요."
            )
        data_snapshot = self.data.capture() if keep_data else None
        entry_data = dict(self.edit.entry_data) if keep_data else None
        self.edit.reset()
        self._load_job_template(job)
        handoff_failure = self._carry_job_data(job, keep_data=keep_data, source_ref=source_ref)
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
        restore_job_mapping(self.edit, job, carried_data=carried_data)
        self.edit.context = replace(context, work=job.name)
        self.edit.base = job
        self.edit.section = (
            landing_section if landing_section in self.projection.sections() else SECTION_BINDING
        )
        if data_snapshot is not None:
            self.data.restore(data_snapshot, rebuild_mapping=True)
        if entry_data is not None:
            self.edit.entry_data = entry_data
        self.edit.reload_failure = handoff_failure
        model = self.edit.model
        assert model is not None  # 위에서 저장본의 연결로 세웠다(데이터 복원의 재조립도 모델을 남긴다)
        lines = restore_report_lines(job, model, handoff_failure)
        set_notice(self.edit, "\n".join(lines), "warn" if lines else "ok")
        if probe_binding:
            self._refresh_binding_confirm_pending()
        if emit_push:
            self.push()

    def _load_job_template(self, job: "Job") -> None:
        """저장본의 템플릿을 읽는다 — 채울 필드가 없거나 상태를 모르면 편집을 열지 않는다."""
        self.load_template_path(job.template_path, emit_push=False)
        if self.edit.schema is None:
            raise ValueError(self.edit.raw_block or RAW_BLOCK_MESSAGE)
        if self.edit.gate_error:
            raise ValueError("템플릿 상태를 확인할 수 없어 편집을 열 수 없습니다.")

    def _carry_job_data(
        self, job: "Job", *, keep_data: bool, source_ref: "dict | None"
    ) -> str:
        """다시 세울 데이터 결속을 읽는다 — 실패는 세션을 막지 않고 사유로 돌려준다.

        건넨 참조(``source_ref``)가 우선이고, 데이터를 살리는 갈래면 읽지 않으며, 그 밖에는
        저장본의 결속을 다시 읽는다.
        """
        carried_ref = source_ref if source_ref else None if keep_data else binding_source_ref(job)
        if not carried_ref:
            return ""
        try:
            self.data.load_source_ref(carried_ref, emit_push=False)
        except Exception as exc:
            return str(exc)
        return ""

    def restore_saved(self, job: Job) -> None:
        """Land a committed job without push or a nested binding-store probe."""
        self._restore_from(
            job,
            landing_section=self.edit.section,
            context=self.edit.context,
            emit_push=False,
            probe_binding=False,
        )

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
            ensure_model(self.edit)
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
            data_line = discard_data_line(data_changed, base_bound)
            set_notice(self.edit, "바꾼 내용을 버리고 저장된 상태로 되돌렸습니다." + data_line, "ok")
            return
        if section not in self.projection.sections():
            raise ValueError(f"이 작업에는 '{section}' 탭이 없습니다.")
        if section == SECTION_FILENAME:
            self.edit.pattern = base.filename_pattern
        elif section == SECTION_BINDING:
            revert_binding(self.edit, base)
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
        set_notice(
            self.edit,
            f"「{self.SECTION_LABELS.get(section, section)}」 에서 바꾼 것만 되돌렸습니다.", "ok"
        )

    def _do_dismiss_notice(self, p: dict) -> None:
        set_notice(self.edit, "", "muted")

    def _do_ack_gate(self, p: dict) -> None:
        if self.edit.gate is None:
            raise ValueError("확인할 항목이 없습니다.")
        self.edit.gate.acknowledge(self.edit.gate.unmet_tokens)

    def _do_use_pool_data(self, p: dict) -> dict:
        if self._pool_registry is None:
            return {"ok": False, "error": POOL_UNWIRED_TEXT}
        key = str(p["key"])
        # `sheet` 은 「연결 확인」 시트 탭 — 등록이 선언하지 않은 시트는 마운트 전에 거절된다.
        res = load_pool_into(self._pool_registry, key, self.data.mount_pool_item, sheet=p.get("sheet"))
        if not res["ok"]:
            return {"ok": False, "error": res["error"]}
        self.edit.data_pool_key = key
        self.edit.data_name_cache = None
        self.projection.rederive_job_name()
        return {"ok": True, "label": res["item"].name}


__all__ = ["EditorLoader", "EditorProjection"]
