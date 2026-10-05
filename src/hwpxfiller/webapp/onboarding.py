"""Backend-owned onboarding guidance over successful, scoped product actions.

Practice runs in its own workspace (#1126): each lesson start seeds a fresh lesson home and
the same window switches to a controller graph rooted there (:mod:`.workspace_switch`).
Nothing the tutorial does is written to the user's templates, jobs, data pool or settings.
"""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from contextlib import nullcontext
import threading
from typing import Any
from uuid import uuid4

from ..external.tutorial_practice import ORIGINALS, PracticeFiles
from ..external.tutorial_workspace import TutorialWorkspace
from ..viewmodel.tutorial_lessons import BY_ID, LessonProgress
from .onboarding_guide import advance_current, guide_beat, observe_ui_press, picker_hint, rewind_unmet_inputs
from .onboarding_match_results import match_event
from .onboarding_practice import (
    NO_RETURN_SCREEN, capture_return, note_practice_save, practice_resources, restore_screen, start_fresh,
)


def first_launch_candidate(home: Path) -> bool:
    """Fail closed for upgrades, unreadable homes, or any prior user material."""
    try:
        if not home.exists():
            return True
        return not any(home.iterdir())
    except OSError:
        return False


class OnboardingController:
    name = "tutorial"

    def __init__(self, push, workspace: TutorialWorkspace, *, first_launch: bool) -> None:
        self._push = push
        self.workspace = workspace
        #: Cleanup of copies older versions left in the user's templates folder (legacy only).
        self.practice: PracticeFiles | None = None
        self.switch: Any = None
        self.progress = LessonProgress(workspace.load_progress(), first_launch=first_launch)
        self.controllers: dict = {}
        self._recovery: str | None = None
        self._lock = threading.RLock()
        self._return_context: dict | None = None
        self._pending_transition: dict | None = None

    def bind(self, controllers: dict) -> None:
        """The active workspace's controllers — rebound on every workspace switch."""
        self.controllers = controllers

    def attach(self, switch, legacy: PracticeFiles) -> None:
        self.switch = switch
        self.practice = legacy

    def notify(self, _milestone) -> bool:
        """Frozen T0–T17 producers cannot satisfy a new lesson."""
        return False

    def observation_failed(self, detail: str) -> None:
        with self._lock:
            self.progress.pause()
            self._recovery = f"안내 진행을 확인하지 못했습니다: {detail}. 작업 결과는 보존됐습니다. 튜토리얼에서 다시 확인하세요."
            self._persist()
            self._emit()

    def _persist(self) -> None:
        self.workspace.save_progress(self.progress.progress())

    def _emit(self) -> None:
        self._push(self.name, self.snapshot())

    def _context(self) -> dict:
        selected = self.progress.selected
        return self.progress.record(selected)["context"] if selected else {}

    def _resources(self) -> tuple[bool, str]:
        return practice_resources(self)

    @staticmethod
    def practice_names() -> tuple[str, ...]:
        return ORIGINALS

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot()

    def _snapshot(self) -> dict:
        snap = self.progress.snapshot()
        ready, summary = self._resources()
        entries = self._context().get("assets", {}) if self.progress.selected else {}
        files = [{"name": name, "path": entry.get("path", ""),
                  "kind": "data" if name.endswith(".xlsx") else "template"}
                 for name, entry in entries.items()] if isinstance(entries, dict) else []
        derived = self._context().get("derived_entry") if self.progress.selected else None
        if isinstance(derived, dict):
            files.append({"name": "추가 연습 데이터", "path": derived.get("path", ""), "kind": "data"})
        notice = self._context().get("seed_notice", "") if self.progress.selected else ""
        snap["resources"] = {"ready": ready, "summary": f"{summary} {notice}".strip(), "files": files}
        reason = self._recovery or (None if ready or not self.progress.selected else summary)
        snap["recovery"] = {"title": "연습 파일을 확인하세요", "body": reason} if reason else None
        snap["practice"] = {"active": self._return_context is not None,
                            "return_screen": self._return_context.get("screen") if self._return_context else None}
        if snap["beat"]:
            guide_beat(self, snap["beat"])
        return snap

    def _preflight(self, payload: dict) -> dict:
        self._pending_transition = None
        screen = payload["screen"]
        action = payload["action"]
        if screen not in {"job", "library", "editor", "workbench", "authoring"}:
            raise ValueError(NO_RETURN_SCREEN)
        if action not in {"start", "select", "restart", "resume", "exit", "navigate"}:
            raise ValueError("튜토리얼 전환을 다시 시도하세요.")
        scenario = payload.get("scenario_id")
        if scenario is not None and scenario not in BY_ID:
            raise ValueError("과정을 다시 고르세요.")
        self._job().raise_if_generating_before_swap("튜토리얼을 전환하세요")
        destination = payload.get("destination_screen", "job") if action == "navigate" else "job"
        if destination not in {"job", "library", "editor", "workbench", "authoring"}:
            raise ValueError(NO_RETURN_SCREEN)
        token = uuid4().hex
        if action != "navigate":
            self._pending_transition = {"token": token, "action": action, "scenario_id": scenario,
                                        "basis": self._transition_basis(),
                                        "context": capture_return(self, screen) if self._return_context is None else None}
        dirty = screen == "editor" and self._editor().has_unsaved_work()
        return {"ok": True, "transition_token": token, "needs_confirm": dirty, "target_screen": destination,
                "confirm_text": "저장하지 않은 작업 편집 내용이 사라집니다. 계속할까요?" if dirty else ""}

    def _transition_basis(self) -> tuple:
        job = self._job()
        return (job.work.name, id(job.data), job.data.snapshot_generation,
                job.data.committed_range().fingerprint())

    def _transition_context(self, action: str, payload: dict) -> dict | None:
        self._job().raise_if_generating_before_swap("튜토리얼을 전환하세요")
        token = payload.get("transition_token")
        if token is None:
            if self._editor().has_unsaved_work():
                raise ValueError("저장하지 않은 작업 편집 내용이 사라집니다. 계속할까요?")
            return capture_return(self, "job") if self._return_context is None else None
        pending = self._pending_transition
        if (not pending or token != pending["token"] or action != pending["action"]
                or payload.get("scenario_id") != pending["scenario_id"]
                or pending["basis"] != self._transition_basis()):
            raise ValueError("튜토리얼 전환을 다시 시도하세요.")
        self._pending_transition = None
        return pending["context"]

    def _exit(self) -> dict:
        original = self._return_context
        self.progress.pause()
        if original is None:
            return {"ok": True, "screen": "job", "notice": ""}
        try:
            self._job().raise_if_generating_before_swap("연습을 종료하세요")
            self.switch.leave()
        except (ValueError, OSError, KeyError) as exc:
            self._recovery = f"원래 작업으로 돌아오지 못했습니다: {exc}. 연습 종료를 다시 시도하세요."
            return {"ok": False, "error": self._recovery, "screen": "library"}
        # Back in the user's workspace from here on, whatever happens to the screen below.
        self._return_context = None
        self._recovery = None
        self.progress.result = None
        screen, notice = restore_screen(self, original)
        return {"ok": True, "screen": screen, "notice": notice}

    def initial(self) -> dict:
        return self.snapshot()

    def file_picker_hint(self, kind: str, screen: str = "") -> str:
        """Suggest the current practice asset without restricting the native file picker."""
        with self._lock:
            if self._return_context is None or not self.progress.active or not self._resources()[0]:
                return ""
            return picker_hint(self, kind, screen)

    def _select(self, scenario_id: str) -> None:
        if scenario_id not in BY_ID:
            raise ValueError("과정을 다시 고르세요.")
        self.progress.select(scenario_id)
        home = self._context().get("home")
        if (not self.progress.active or self.progress.record(scenario_id)["checkpoint"] == 0
                or not isinstance(home, str) or not Path(home).is_dir()):
            start_fresh(self, scenario_id)
        else:
            self.switch.enter(Path(home))
        ready, reason = self._resources()
        self._recovery = None if ready else reason
        if not ready:
            self.progress.pause()
        self._persist()

    def dispatch(self, action: str, payload: dict):
        with self._lock:
            transition = action in {"preflight", "start", "select", "restart", "resume", "exit"}
            with self._job()._state_lock if transition else nullcontext():
                before = deepcopy(self.progress) if transition else None
                try:
                    return self._dispatch(action, payload)
                except Exception:
                    if before is not None:
                        self.progress = before
                        self._persist()
                        self._emit()
                    raise

    def _dispatch(self, action: str, payload: dict):
        if action == "preflight":
            return self._preflight(payload)
        if action == "exit":
            self._transition_context(action, payload)
            result = self._exit()
            self._persist()
            self._emit()
            return result
        if action in {"start", "select", "restart", "resume"}:
            return self._enter(action, payload)
        if action in {"cleanup_preview", "cleanup"}:
            return self._legacy_cleanup(action, payload)
        if action == "observe_ui":
            observe_ui_press(self, payload)
        elif action == "next":
            self._next()
        elif action == "reset_progress":
            if payload.get("confirm") is not True:
                raise ValueError("모든 학습 기록을 지울지 확인하세요.")
            self.progress = LessonProgress({"version": 1, "invite_seen": True})
            self._recovery = None
        elif action == "later":
            self.progress.later()
        elif action in {"pause", "skip"}:
            self.progress.pause()
        else:
            raise ValueError(f"알 수 없는 tutorial 액션: {action!r}")
        self._persist()
        self._emit()
        return None

    def _next(self) -> None:
        self.progress.next()
        if self.progress.selected == "blank_values" and self.progress.record("blank_values")["completed"]:
            self._finish_result("빈 값 확인 완료", "〈빈 값〉 표식과 비움 확정을 확인했습니다.",
                                "workbench", "txt-review", [], count=1)

    def _enter(self, action: str, payload: dict) -> dict:
        """Start, switch or resume a lesson inside the practice workspace."""
        context = self._transition_context(action, payload)
        try:
            if action == "resume":
                self._resume()
            elif action == "restart":
                start_fresh(self, payload["scenario_id"])
                self._recovery = None
            else:
                self._select(payload["scenario_id"])
        finally:
            # The escape route exists exactly while a practice workspace is the active one.
            if context is not None and self.switch.practice_home is not None:
                self._return_context = context
        self._persist()
        self._emit()
        beat = self.snapshot()["beat"] or {}
        return {"ok": True, "screen": beat.get("entry_screen") or beat.get("screen") or "job"}

    def _resume(self) -> None:
        ready, reason = self._resources()
        if not ready:
            self._recovery = reason
            raise ValueError(reason)
        self._recovery = None
        self.switch.enter(Path(self._context()["home"]))
        if self.progress.selected:
            self.progress.select(self.progress.selected)

    def _legacy_cleanup(self, action: str, payload: dict):
        """Copies older versions left in the user's templates folder; new practice never adds any."""
        assert self.practice is not None, "legacy cleanup is attached at assembly"
        if action == "cleanup_preview":
            return self.practice.cleanup_preview()
        result = self.practice.cleanup(payload["token"])
        self._emit()
        return result

    def observation_token(self) -> tuple[str | None, str | None, int]:
        with self._lock:
            selected = self.progress.selected
            return (selected, self._context().get("batch") if selected else None,
                    self.progress.record(selected)["checkpoint"] if selected else 0)

    def observe_product(self, screen: str, action: str, payload: dict, result,
                        *, token: tuple[str | None, str | None, int] | None = None) -> bool:
        with self._lock:
            if token is not None and token != self.observation_token():
                return False
            return self._observe_product(screen, action, payload, result)

    def _observe_product(self, screen: str, action: str, payload: dict, result) -> bool:
        """Called only after a product command actually returned; never from a UI click."""
        if not self.progress.active or self.progress.beat() is None:
            return False
        if isinstance(result, dict) and (result.get("ok") is False
                                         or result.get("needs_confirm") or result.get("needs_overwrite")):
            return False
        note_practice_save(self, screen, action, result)
        ready, reason = self._resources()
        if not ready:
            self._recovery = reason
            self.progress.pause()
            self._persist()
            self._emit()
            return False
        before = repr(self._context())
        rewound = rewind_unmet_inputs(self)
        advanced = advance_current(self, screen, action, payload, result) or rewound
        if advanced or repr(self._context()) != before:
            self._persist()
        if advanced or repr(self._context()) != before or action in {
                "use_library_template", "select_job", "prefer_work", "toggle_record", "set_all", "set_none"}:
            self._emit()
        return advanced

    def _asset(self, name: str) -> str:
        return self._context().get("assets", {}).get(name, {}).get("path", "")

    def _editor(self) -> Any:
        return self.controllers["editor"]

    def _job(self) -> Any:
        return self.controllers["job"]

    def _workbench(self) -> Any:
        return self.controllers["workbench"]

    def _matches(self, event: str, screen: str, action: str, payload: dict, result) -> dict | None:
        return match_event(self, event, screen, action, payload, result)

    def _finish_result(self, title: str, body: str, screen: str, target: str,
                       documents: list[dict], *, count: int | None = None) -> None:
        self.progress.result = {"screen": screen, "target": target, "title": title,
                                "body": body, "count": len(documents) if count is None else count,
                                "documents": documents}
        lessons = list(BY_ID)
        if self.progress.selected in lessons and lessons.index(self.progress.selected) + 1 < len(lessons):
            next_id = lessons[lessons.index(self.progress.selected) + 1]
            self.progress.result["next_scenario_id"] = next_id
