"""Backend-owned onboarding guidance over successful, scoped product actions."""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from contextlib import nullcontext
import re
import threading
from typing import Any
from uuid import uuid4

from ..domain.job import JOB_MAPPING_AUTHORITY, Job
from ..domain.mapping import FieldMapping, MappingProfile

from ..external import settings
from ..external.tutorial_practice import PracticeFiles, fingerprint
from ..viewmodel.tutorial_lessons import BY_ID, LessonProgress
from .onboarding_match_results import match_event


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

    def __init__(self, push, practice: PracticeFiles, *, first_launch: bool) -> None:
        self._push = push
        self.practice = practice
        self.progress = LessonProgress(settings.load_tutorial_lessons(), first_launch=first_launch)
        self.controllers: dict = {}
        self._recovery: str | None = None
        self._lock = threading.RLock()
        self._return_context: dict | None = None
        self._pending_transition: dict | None = None

    def bind(self, controllers: dict) -> None:
        self.controllers = controllers

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
        settings.save_tutorial_lessons(self.progress.progress())

    def _emit(self) -> None:
        self._push(self.name, self.snapshot())

    def _context(self) -> dict:
        selected = self.progress.selected
        return self.progress.record(selected)["context"] if selected else {}

    def _resources(self) -> tuple[bool, str]:
        selected = self.progress.selected
        if not selected:
            return False, "과정을 고르세요."
        ctx = self._context()
        entries = ctx.get("assets")
        if not isinstance(entries, dict) or set(entries) != set(self.practice_names()):
            return False, "연습 파일이 준비되지 않았습니다. 예제로 시작하세요."
        for entry in entries.values():
            ok, reason = self.practice.validate(entry)
            if not ok:
                # Saved authoring edits are allowed only if their exact new digest was recorded.
                path = Path(entry.get("path", ""))
                expected = ctx.get("saved_fingerprints", {}).get(str(path))
                if not (reason == "연습 파일이 수정됐습니다. 현재 파일을 보존합니다."
                        and expected and path.is_file() and not path.is_symlink()
                        and fingerprint(path) == expected):
                    return False, reason
        derived_entry = ctx.get("derived_entry")
        if derived_entry is not None:
            if not isinstance(derived_entry, dict):
                return False, "다른 연습 데이터 기록을 확인할 수 없습니다."
            valid, reason = self.practice.validate(derived_entry)
            if not valid:
                return False, reason
        return True, "연습 파일 4건이 준비됐습니다."

    @staticmethod
    def practice_names() -> tuple[str, ...]:
        from ..external.tutorial_practice import ORIGINALS

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
            self._guide(snap["beat"])
        return snap

    def _capture_return(self, screen: str) -> dict:
        job = self._job()
        data = job.data
        return {"screen": screen, "job_name": job.work.name,
                "editor_job": self._editor().edit.base.name if self._editor().edit.base else "",
                "source": {"path": data.path, "sheet": data.sheet, "header_row": data.header_row,
                           "kind": data.kind, "source_kind": data.source_kind, "pool_key": data.pool_key},
                "records": deepcopy(data.records), "range": data.committed_range().copy(),
                "hidden_columns": set(data.hidden_columns),
                "remembered_data": deepcopy(job._remembered_data_source),
                "output_directory": job.remembered_output_directory(),
                "authoring_id": self.controllers["authoring"].active_id,
                "workbench_row": (self._workbench().snapshot().get("card") or {}).get("source_row")}

    def _preflight(self, payload: dict) -> dict:
        self._pending_transition = None
        screen = payload["screen"]
        action = payload["action"]
        if screen not in {"job", "library", "editor", "workbench", "authoring"}:
            raise ValueError("돌아갈 화면을 확인할 수 없습니다.")
        if action not in {"start", "select", "restart", "resume", "exit", "navigate"}:
            raise ValueError("튜토리얼 전환을 다시 시도하세요.")
        scenario = payload.get("scenario_id")
        if scenario is not None and scenario not in BY_ID:
            raise ValueError("과정을 다시 고르세요.")
        self._job().raise_if_generating_before_swap("튜토리얼을 전환하세요")
        destination = payload.get("destination_screen", "job") if action == "navigate" else "job"
        if destination not in {"job", "library", "editor", "workbench", "authoring"}:
            raise ValueError("돌아갈 화면을 확인할 수 없습니다.")
        token = uuid4().hex
        if action != "navigate":
            self._pending_transition = {"token": token, "action": action, "scenario_id": scenario,
                                        "basis": self._transition_basis(),
                                        "context": self._capture_return(screen) if self._return_context is None else None}
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
            return self._capture_return("job") if self._return_context is None else None
        pending = self._pending_transition
        if (not pending or token != pending["token"] or action != pending["action"]
                or payload.get("scenario_id") != pending["scenario_id"]
                or pending["basis"] != self._transition_basis()):
            raise ValueError("튜토리얼 전환을 다시 시도하세요.")
        self._pending_transition = None
        return pending["context"]

    def _exit(self) -> dict:
        original = self._return_context
        if original is None:
            self.progress.pause()
            return {"ok": True, "screen": "job", "notice": ""}
        job = self._job()
        self.progress.pause()
        try:
            job.raise_if_generating_before_swap("연습을 종료하세요")
            job.dispatch("select_job", {"name": "", "confirm": True})
            source = original["source"]
            if source["source_kind"] == "pool":
                result = job.dispatch("load_pool", {"key": source["pool_key"], "sheet": source["sheet"]})
                if isinstance(result, dict) and result.get("ok") is False:
                    raise ValueError(result.get("error", "데이터를 불러오지 못했습니다."))
            elif source["source_kind"]:
                job._mount_by_kind(source["path"], source["sheet"], source["header_row"], source["kind"])
            else:
                from .data_zone import JobDataSession

                job.data = JobDataSession(job.data.pool_registry)
            if original["job_name"]:
                restored = job.dispatch("prefer_work", {"name": original["job_name"]})
                if not restored.get("promoted"):
                    raise ValueError(f"'{original['job_name']}' 작업을 현재 데이터에 연결할 수 없습니다.")
            notice = ""
            same_source = all(getattr(job.data, key) == value for key, value in source.items())
            if same_source and job.data.records == original["records"]:
                saved_range = original["range"].copy()
                job.data.selection = saved_range.selection
                job.data.filter = saved_range.filter
                job.data.view_order = saved_range.view_order
                job.data.hidden_columns = original["hidden_columns"]
            else:
                notice = "원래 데이터가 변경되어 필터와 행 선택을 복원하지 않았습니다."
                job.data.set_notice(notice)
            screen = original["screen"]
            if screen == "editor" and original["editor_job"]:
                self._editor().load_job(original["editor_job"])
            elif screen == "authoring" and original["authoring_id"]:
                self.controllers["authoring"].dispatch("activate", {"session_id": original["authoring_id"]})
            elif screen == "workbench":
                opened = job.dispatch("open_workbench", {})
                if opened.get("ok") is True:
                    card = self._workbench().snapshot().get("card") or {}
                    index = next((item["index"] for item in card.get("index_map", [])
                                  if item["row"] == original["workbench_row"]), None)
                    if index is not None:
                        self._workbench().dispatch("set_current", {"index": index})
                else:
                    screen = "job"
                    notice = " ".join(filter(None, (notice, opened.get("error"))))
            elif screen == "editor":
                screen = "job" if original["job_name"] else "library"
            settings.restore_tutorial_preferences(original["remembered_data"], original["output_directory"])
            job._remembered_data_source = original["remembered_data"]
            job._remembered_output_directory = original["output_directory"]
            job.runs.out_dir = job._output_folder_resolution().directory
            job._push()
        except (ValueError, OSError, KeyError) as exc:
            self._recovery = f"원래 작업으로 돌아오지 못했습니다: {exc}. 연습 종료를 다시 시도하세요."
            return {"ok": False, "error": self._recovery, "screen": "library"}
        self._return_context = None
        self._recovery = None
        self.progress.result = None
        return {"ok": True, "screen": screen, "notice": notice}

    def _guide(self, beat: dict) -> None:
        """Project intermediate product actions; the browser only locates their controls."""
        ctx = self._context()
        lesson = self.progress.selected
        template_name = {"first_hwpx": "물품 구매입찰 공고.hwpx",
                         "purchase_txt": "계약방법 결정 및 구매추진 안내.txt",
                         "contract_txt": "낙찰자 선정 및 계약체결 안내.txt"}.get(lesson or "")
        body = beat["body"]
        if beat["screen"] == "editor" and template_name and lesson:
            editor = self._editor().edit
            sheet = "계약" if lesson == "contract_txt" else "공고"
            if editor.template_path != self._asset(template_name):
                prerequisite = next(item for item in BY_ID[lesson].beats if item.target == "template-list")
                beat["target"], beat["title"], body = prerequisite.target, prerequisite.title, prerequisite.body
            elif editor.data_path != self._asset("공고목록.xlsx") or editor.data_sheet != sheet:
                prerequisite = next(item for item in BY_ID[lesson].beats
                                    if item.target == ("data-picker" if lesson == "first_hwpx" else "template-list"))
                beat["target"], beat["title"], body = "data-picker", prerequisite.title, prerequisite.body
        for name in self.practice_names():
            path = self._asset(name)
            if path:
                body = body.replace(name, Path(path).name)
        if template_name and beat["target"] == "template-list":
            body += f"\n서식: {Path(self._asset(template_name)).name}"
            if lesson != "first_hwpx":
                body += f"\n데이터: {Path(self._asset('공고목록.xlsx')).name}"
            if self._editor().edit.template_path == self._asset(template_name):
                beat["target"] = "data-picker"
        if template_name and beat["target"] == "data-picker":
            data_name = Path(self._asset("공고목록.xlsx")).name
            if data_name not in body:
                body += f"\n데이터: {data_name}"
        if ctx.get("derived_data_path") and lesson in {"replace_data", "blank_values"}:
            body += f"\n데이터: {Path(ctx['derived_data_path']).name} · {ctx['derived_sheet']}"
        if lesson in {"field_trial", "option_apply"} and beat["id"] == "open":
            beat["target"] = "authoring-open"
            body += f"\n서식: {Path(self._asset('낙찰자 선정 및 계약체결 안내.txt')).name}"
        if ctx.get("job_name"):
            body += f"\n작업: {ctx['job_name']}"
        beat["body"] = body
        guidance = {}
        if beat["screen"]:
            guidance[beat["screen"]] = {"body": body, "target": beat["target"]}
        if beat["target"] == "prepare-examples":
            beat["primary"] = {"action": "prepare_examples", "label": "연습 파일 새로 준비"}
        if beat["screen"] == "editor" and not ctx.get("job_name"):
            guidance["library"] = {"body": body, "target": "new-job"}
            guidance["job"] = {"body": body, "target": "new-job"}
        elif beat["screen"] == "editor":
            guidance["library"] = {"body": body, "target": "edit-job"}
            guidance["job"] = {"body": body, "target": None,
                               "primary": {"action": "navigate", "screen": "library",
                                           "label": "현재 단계로 돌아가기"}}
            beat["entry_screen"] = "library"
            if self._editor().edit.job_name != ctx["job_name"]:
                guidance["editor"] = {"body": body, "target": None,
                                      "primary": {"action": "navigate", "screen": "library",
                                                  "label": "현재 단계로 돌아가기"}}
        if beat["screen"] in {"job", "workbench"} and ctx.get("job_name"):
            guidance["library"] = {"body": body, "target": "library-jobs"}
            if self._job().work.name != ctx["job_name"]:
                guidance["job"] = {"body": body, "target": "job-list"}
            elif beat["screen"] == "workbench":
                target = "open-workbench" if self._job().data.selection.selected_count() else "row-selection"
                guidance["job"] = {"body": body, "target": target}
            beat["entry_screen"] = "job"
        beat["guidance"] = guidance

    def initial(self) -> dict:
        return self.snapshot()

    def file_picker_hint(self, kind: str, screen: str = "") -> str:
        """Suggest the current practice asset without restricting the native file picker."""
        with self._lock:
            if self._return_context is None or not self.progress.active or not self._resources()[0]:
                return ""
            beat = self._snapshot()["beat"]
            if not beat or (screen and screen != beat["screen"]):
                return ""
            target = beat["guidance"].get(screen or beat["screen"], {}).get("target", beat["target"])
            if kind == "data" and target == "data-picker":
                if self.progress.selected == "replace_data":
                    return self._context().get("derived_data_path", "")
                return self._asset("공고목록.xlsx")
            if kind == "template" and target == "authoring-open":
                return self._asset("낙찰자 선정 및 계약체결 안내.txt")
            return ""

    def _prepare(self, *, derived: str = "") -> dict:
        batch = self.practice.prepare(derived=derived)
        ctx = self._context()
        if derived:
            pass  # independent data copy; the original practice template remains linked.
        elif ctx and self.progress.selected and self.progress.record(self.progress.selected)["checkpoint"] > 0:
            # Hold a fresh batch for this lesson only until guidance restarts.
            ctx["pending_assets"] = {entry["name"]: entry for entry in batch["entries"]}
            ctx["pending_batch"] = batch["batch"]
            self._recovery = "새 연습 파일을 준비했습니다. 이 파일로 시작하려면 해당 과정의 안내를 처음부터 시작하세요."
        elif ctx is not None:
            self._adopt_batch(batch["batch"], {entry["name"]: entry for entry in batch["entries"]})
            self._persist()
        return batch

    def _adopt_batch(self, batch: str, assets: dict) -> None:
        ctx = self._context()
        ctx["assets"] = assets
        ctx["batch"] = batch
        for key in ("pending_assets", "pending_batch", "saved_fingerprints", "job_name", "seeded",
                    "seed_notice", "derived_data_path", "derived_entry", "derived_sheet"):
            ctx.pop(key, None)
        if self.progress.selected in {"repeat_hwpx", "replace_data", "option_apply"}:
            self._seed_job(self.progress.selected)

    def _select(self, scenario_id: str, *, start: bool) -> None:
        if scenario_id not in BY_ID:
            raise ValueError("과정을 다시 고르세요.")
        self.progress.select(scenario_id)
        if not self.progress.active:
            self.progress.restart(scenario_id)
            self._prepare()
        ctx = self._context()
        if "assets" not in ctx:
            self._prepare()
        if scenario_id in {"repeat_hwpx", "replace_data", "option_apply"} and not ctx.get("job_name"):
            self._seed_job(scenario_id)
        beat = self.progress.beat()
        if scenario_id == "blank_values" and beat is not None and beat.id == "prepare":
            self._dispatch("prepare_examples", {})
        ready, reason = self._resources()
        self._recovery = None if ready else reason
        if not ready:
            self.progress.pause()
        self._persist()

    def _seed_job(self, lesson_id: str) -> None:
        """Explicit course prerequisite; never awards a prior lesson's evidence."""
        ctx = self._context()
        is_txt = lesson_id in {"option_apply", "blank_values"}
        template_name = ("낙찰자 선정 및 계약체결 안내.txt" if is_txt
                         else "물품 구매입찰 공고.hwpx")
        template_path = self._asset(template_name)
        data_path = ctx.get("derived_data_path") if lesson_id == "blank_values" else self._asset("공고목록.xlsx")
        sheet = "계약" if is_txt else "공고"
        if not template_path or not data_path:
            raise ValueError("연습 파일을 먼저 준비하세요.")
        if is_txt:
            content = Path(template_path).read_text(encoding="utf-8")
            fields = list(dict.fromkeys(re.findall(r"\{\{([^{}]+)\}\}", content)))
        else:
            from ..domain.schema import extract_schema
            from ..external.hwpx_package_io import read_hwpx_package

            fields = [field.name for field in extract_schema(read_hwpx_package(template_path)).fields]
        source_overrides = {"낙찰자결정방법": "낙찰방법", "담당자 전화번호": "담당자전화",
                            "대표계약업체": "계약상대자"}
        mapping = MappingProfile(mappings=[FieldMapping(field, source_overrides.get(field, field))
                                           for field in fields])
        if lesson_id == "blank_values":
            mapping.mappings = [FieldMapping("단위", type="const") if item.template_field == "단위" else item
                                for item in mapping.mappings]
        # Each blank round prepares a fresh data copy, so the job takes that copy's batch:
        # a restart seeds a new job beside the user's saved one instead of re-saving over it.
        batch = ctx["derived_entry"]["batch"] if lesson_id == "blank_values" else ctx["batch"]
        name = f"튜토리얼 {BY_ID[lesson_id].title} {batch}"
        job = Job(name=name, template_path=template_path, mapping=mapping,
                  filename_pattern="구매입찰공고-{{입찰공고번호}}" if not is_txt else "",
                  data_path=data_path, data_sheet=sheet,
                  binding_authority=JOB_MAPPING_AUTHORITY)
        self.practice.jobs.save(job)
        if lesson_id == "option_apply":
            # Establish the pre-edit template basis without seating or replacing the
            # user's current job session (the normal select_job preparation seam).
            job_controller = self._job()
            job_controller.work.prepare_for_seat(job_controller.work.load(name))
        ctx["job_name"] = name
        ctx["seeded"] = True
        ctx["seed_notice"] = f"이 과정용 연습 작업 '{name}'을 준비했습니다. 다른 과정의 완료 기록은 바꾸지 않습니다."

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
        context = None
        if action in {"start", "select", "restart", "resume"}:
            context = self._transition_context(action, payload)
            if context is not None:
                # Keep the escape route even when preparing a lesson fails after guarded leave.
                self._return_context = context
        if action == "later":
            self.progress.later()
        elif action in {"start", "select"}:
            self._select(payload["scenario_id"], start=action == "start")
        elif action in {"pause", "skip"}:
            self.progress.pause()
        elif action == "resume":
            ready, reason = self._resources()
            if not ready:
                self._recovery = reason
                raise ValueError(reason)
            self._recovery = None
            if self.progress.selected:
                self.progress.select(self.progress.selected)
        elif action == "restart":
            scenario_id = payload["scenario_id"]
            completed = self.progress.record(scenario_id)["completed"]
            self.progress.restart(scenario_id)
            ctx = self._context()
            if "assets" not in ctx or (completed and "pending_assets" not in ctx):
                self._prepare()
            if isinstance(ctx.get("pending_assets"), dict) and isinstance(ctx.get("pending_batch"), str):
                assets = ctx["pending_assets"]
                if set(assets) != set(self.practice_names()) or not all(
                        self.practice.validate(entry)[0] for entry in assets.values()):
                    self.progress.pause()
                    self._recovery = "새 연습 파일을 확인할 수 없습니다. 사본을 다시 준비하세요."
                else:
                    self._adopt_batch(ctx["pending_batch"], assets)
                    self._recovery = None
            else:
                ready, reason = self._resources()
                self._recovery = None if ready else reason
                if not ready:
                    self.progress.pause()
            if scenario_id == "blank_values" and self.progress.active:
                self._dispatch("prepare_examples", {})
        elif action == "next":
            self.progress.next()
            if (self.progress.selected == "blank_values"
                    and self.progress.record("blank_values")["completed"]):
                self._finish_result("빈 값 확인 완료", "빈 값 표식과 직접 입력 결과를 확인했습니다.",
                                    "workbench", "txt-review", [], count=1)
        elif action == "prepare_examples":
            beat = self.progress.beat()
            derived = ("replacement" if beat and beat.event == "derived_data_prepared"
                       else "blank" if beat and beat.event == "blank_data_prepared"
                       else payload.get("derived", ""))
            batch = self._prepare(derived=derived)
            data_path = next(e["path"] for e in batch["entries"] if e["name"].endswith(".xlsx"))
            if beat and beat.event in {"derived_data_prepared", "blank_data_prepared"}:
                if ((beat.event == "derived_data_prepared" and derived == "replacement")
                        or (beat.event == "blank_data_prepared" and derived == "blank")):
                    self.progress.observed(beat.event, context={
                        "derived_data_path": data_path,
                        "derived_entry": batch["entries"][0],
                        "derived_sheet": "계약" if beat.event == "blank_data_prepared" else "공고",
                    })
                    if beat.event == "blank_data_prepared":
                        self._seed_job("blank_values")
            self._persist()
            self._emit()
            return {"batch": batch["batch"], "path": data_path}
        elif action == "cleanup_preview":
            return self.practice.cleanup_preview()
        elif action == "cleanup":
            result = self.practice.cleanup(payload["token"])
            self._emit()
            return result
        elif action == "reset_progress":
            if payload.get("confirm") is not True:
                raise ValueError("모든 학습 기록을 지울지 확인하세요.")
            self.progress = LessonProgress({"version": 1, "invite_seen": True})
            self._recovery = None
        else:
            raise ValueError(f"알 수 없는 tutorial 액션: {action!r}")
        self._persist()
        self._emit()
        if action in {"start", "select", "restart", "resume"}:
            beat = self.snapshot()["beat"] or {}
            return {"ok": True, "screen": beat.get("entry_screen") or beat.get("screen") or "job"}
        return None

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
        if (self.progress.selected in {"field_trial", "option_apply"}
                and screen == "authoring" and action in {"save", "save_authoring_document"}
                and isinstance(result, dict) and result.get("ok") is True):
            path = result.get("path")
            authoring = self.controllers["authoring"]
            session = authoring.sessions.get(authoring.active_id)
            if (isinstance(path, str) and path == self._asset("낙찰자 선정 및 계약체결 안내.txt")
                    and session is not None and session.source_path == path):
                self._context().setdefault("saved_fingerprints", {})[path] = fingerprint(Path(path))
        ready, reason = self._resources()
        if not ready:
            self._recovery = reason
            self.progress.pause()
            self._persist()
            self._emit()
            return False
        advanced = False
        before = repr(self._context())
        # A single successful command can establish adjacent facts (e.g. template+sheet).
        for _ in range(2):
            beat = self.progress.beat()
            if beat is None or beat.event is None:
                break
            context = self._matches(beat.event, screen, action, payload, result)
            if context is None or not self.progress.observed(beat.event, context=context):
                break
            advanced = True
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
                                "documents": documents,
                                "actions": [{"label": "결과 확인", "target": target}]}
        lessons = list(BY_ID)
        if self.progress.selected in lessons and lessons.index(self.progress.selected) + 1 < len(lessons):
            next_id = lessons[lessons.index(self.progress.selected) + 1]
            self.progress.result["next_scenario_id"] = next_id
            self.progress.result["next_scenario_label"] = BY_ID[next_id].title
