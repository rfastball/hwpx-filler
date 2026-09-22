"""Editor screen facade: public bridge calls, dispatch, and snapshot pushes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from ..external.dataset_store import DatasetPoolRegistry
from ..external.job_store import JobRegistry
from ..external.template_root import TemplateRoot
from ..gui.edit_session import (
    SECTION_TEMPLATE,
    EditSaveOperation,
    EditSession,
    make_context,
)
from ..gui.tutorial_state import Milestone
from .editor_session import EditorLoader, EditorProjection
from .screens import PushSink, TutorialSink, source_label, unwired_tutorial


class EditorController:
    """Public editor bridge over one ``EditSession`` and its I/O operations."""

    name = "editor"
    _NONMUTATING_ACTIONS = frozenset({"goto_section", "step_preview", "mapping_reset_stakes"})

    def __init__(
        self,
        registry: JobRegistry,
        push: PushSink,
        *,
        clock: Callable[[], datetime],
        pool_registry: "DatasetPoolRegistry | None" = None,
        template_root: "TemplateRoot | None" = None,
        remembered_output_directory: "Callable[[], str] | None" = None,
        is_library_path: "Callable[[str, str], bool] | None" = None,
        after_mapping_saved: "Callable[[str], object] | None" = None,
        binding_confirm_pending: "Callable[[str], bool] | None" = None,
        tutorial: TutorialSink = unwired_tutorial,
    ) -> None:
        self.edit = EditSession(context=make_context(""), section=SECTION_TEMPLATE)
        self._push_sink = push
        self._tutorial = tutorial
        self.projection = EditorProjection(
            self.edit,
            pool_registry=pool_registry,
            template_root=template_root,
            remembered_output_directory=remembered_output_directory,
            is_library_path=is_library_path,
            clock=clock,
        )
        self.loader = EditorLoader(
            self.edit,
            self.projection,
            registry,
            pool_registry=pool_registry,
            tutorial=tutorial,
            binding_confirm_pending=binding_confirm_pending,
        )
        self.save_operation = EditSaveOperation(
            self.edit,
            registry,
            clock=clock,
            template_exists=lambda path: Path(path).is_file(),
            data_display_name=self.projection.data_display_name,
            restore_saved=self.loader.restore_saved,
            refresh_binding=self.loader._refresh_binding_confirm_pending,
            saved=lambda job: tutorial(
                Milestone.SAVE_TXT_JOB if job.media == "txt" else Milestone.SAVE_JOB
            ),
            after_mapping_saved=after_mapping_saved,
        )
        self.projection.push = self._push
        self.loader.push = self._push
        self.refresh_panel()

    def refresh_panel(self) -> None:
        """Capture external reads and one clock tick for the next pure snapshot."""
        self.projection.prepare()

    def mounted_data_descriptor(self, path: str, sheet: str = "") -> dict:
        """Return the bridge wire shape for the mounted file data."""
        return {
            "label": source_label("file", Path(path).name),
            "path": path,
            "sheet": sheet,
            "rows": len(self.edit.records),
        }

    def owned_session_paths(self) -> "tuple[str, ...]":
        """Exact editor paths eligible for native locate/open actions."""
        return self.edit.template_path, self.edit.data_path

    def _push(self) -> None:
        self.refresh_panel()
        self._push_sink(self.name, self.snapshot())

    def snapshot(self) -> dict:
        return self.projection.snapshot()

    def initial(self) -> dict:
        self.refresh_panel()
        return self.snapshot()

    def has_unsaved_work(self) -> bool:
        return self.edit.has_unsaved_work()

    def new_draft_with_data(self, source_ref: dict, **context) -> None:
        self.loader.new_draft_with_data(source_ref, **context)
        self.refresh_panel()

    def adopt_imported_template(self, dest: str) -> str:
        result = self.loader.adopt_imported_template(dest)
        return result

    def reconcile_template_mutation(self, kind: str, path: str) -> None:
        self.loader.reconcile_template_mutation(kind, path)

    def load_data_path(
        self,
        path: str,
        *,
        sheet: "str | None" = None,
        header_row: int = 0,
        emit_push: bool = True,
    ) -> None:
        self.loader.load_data_path(path, sheet=sheet, header_row=header_row, emit_push=emit_push)
        if not emit_push:
            self.refresh_panel()

    def load_job(self, name: str, **context) -> None:
        self.loader.load_job(name, **context)
        if context.get("emit_push") is False:
            self.refresh_panel()

    def dispatch(self, action: str, payload: dict):
        if action not in self._NONMUTATING_ACTIONS:
            self.edit.clean = False
        was_complete = self.edit.mapping_complete()
        result = self._dispatch(action, payload)
        if not was_complete and self.edit.mapping_complete():
            self._tutorial(Milestone.CONFIRM_MAPPING)
        self._push()
        return result

    def _dispatch(self, action: str, payload: dict):
        loader_actions = {
            "use_library_template": self.loader._do_use_library_template,
            "new_session": self.loader._do_new_session,
            "discard_session": self.loader._do_discard_session,
            "goto_section": self.loader._do_goto_section,
            "discard_patch": self.loader._do_discard_patch,
            "dismiss_notice": self.loader._do_dismiss_notice,
            "ack_gate": self.loader._do_ack_gate,
            "use_pool_data": self.loader._do_use_pool_data,
        }
        if action in loader_actions:
            return loader_actions[action](payload)
        if action == "save":
            return self.save_operation.save(payload)
        handled, result, confirmed_empty = self.edit.apply_mapping_action(action, payload)
        if not handled:
            raise ValueError(f"알 수 없는 editor 액션: {action!r}")
        if confirmed_empty:
            self._tutorial(Milestone.CONFIRM_EMPTY_FIELD)
        return result
