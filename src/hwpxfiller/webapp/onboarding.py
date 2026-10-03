"""Backend-owned onboarding guidance over successful, scoped product actions."""

from __future__ import annotations

from pathlib import Path
import re
import threading
from typing import Any

from ..domain.job import Job
from ..domain.mapping import FieldMapping, MappingProfile

from ..external import settings
from ..external.tutorial_practice import PracticeFiles, fingerprint
from ..viewmodel.tutorial_lessons import BY_ID, LessonProgress


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
        return snap

    def initial(self) -> dict:
        return self.snapshot()

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
        ctx = self._context()
        if "assets" not in ctx:
            self._prepare()
        if scenario_id in {"repeat_hwpx", "replace_data", "option_apply"} and not ctx.get("job_name"):
            self._seed_job(scenario_id)
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
        name = f"튜토리얼 {BY_ID[lesson_id].title} {ctx['batch']}"
        job = Job(name=name, template_path=template_path, mapping=mapping,
                  filename_pattern="구매입찰공고-{{입찰공고번호}}" if not is_txt else "",
                  data_path=data_path, data_sheet=sheet)
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
            return self._dispatch(action, payload)

    def _dispatch(self, action: str, payload: dict):
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
            self.progress.restart(scenario_id)
            ctx = self._context()
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

    def _editor_scope(self, editor, lesson: str) -> bool:
        template = {
            "first_hwpx": "물품 구매입찰 공고.hwpx",
            "contract_txt": "낙찰자 선정 및 계약체결 안내.txt",
            "purchase_txt": "계약방법 결정 및 구매추진 안내.txt",
            "replace_data": "물품 구매입찰 공고.hwpx",
        }.get(lesson)
        if not template or editor.edit.template_path != self._asset(template):
            return False
        beat = self.progress.beat()
        expected_data = (self._context().get("derived_data_path")
                         if lesson == "replace_data" and beat is not None
                         and beat.id in {"connect", "rebind", "reopen"}
                         else self._asset("공고목록.xlsx"))
        expected_sheet = "계약" if lesson == "contract_txt" else "공고"
        return editor.edit.data_path == expected_data and editor.edit.data_sheet == expected_sheet

    @staticmethod
    def _chosen_slot_labels(job) -> dict[str, set[str]]:
        current = job.execution.current_slot_view(job.work.name)
        projection = current.current_view.projection if current else None
        return {
            slot.display_text: {option.display_text for option in slot.options
                                if option.selected and option.effective}
            for slot in projection.slots
        } if projection else {}

    def _correct_notice_options(self, job, lesson: str) -> bool:
        labels = self._chosen_slot_labels(job)
        expected = "소기업·소상공인" if lesson == "first_hwpx" else "중·소기업"
        return expected in labels.get("입찰참가자격", set()) and "고시 미만" in labels.get("낙찰자 결정방법", set())

    def _matches(self, event: str, screen: str, action: str, payload: dict, result) -> dict | None:
        ctx = self._context()
        editor = self._editor()
        job = self._job()
        wb = self._workbench()
        if event == "template_selected" and screen == "editor" and action == "use_library_template":
            return {} if editor.edit.template_path == self._asset("물품 구매입찰 공고.hwpx") else None
        if event in {"notice_data_selected", "contract_inputs_selected", "purchase_inputs_selected"}:
            template = {"notice_data_selected": "물품 구매입찰 공고.hwpx",
                        "contract_inputs_selected": "낙찰자 선정 및 계약체결 안내.txt",
                        "purchase_inputs_selected": "계약방법 결정 및 구매추진 안내.txt"}[event]
            sheet = "계약" if event == "contract_inputs_selected" else "공고"
            if screen == "editor" and action in {"load_data_sheet", "use_pool_data", "use_library_template"}:
                if (editor.edit.template_path == self._asset(template)
                        and editor.edit.data_path == self._asset("공고목록.xlsx")
                        and editor.edit.data_sheet == sheet):
                    return {}
            return None
        if screen == "editor":
            if not self.progress.selected or not self._editor_scope(editor, self.progress.selected):
                return None
            mapping = editor.edit.model
            rows = {r.template_field: r for r in mapping.rows} if mapping else {}
            if event == "notice_mapping_confirmed" and action in {"set_confirmed", "confirm_suggested"}:
                expected = {"낙찰자결정방법": "낙찰방법", "담당자 전화번호": "담당자전화"}
                return {} if all((r := rows.get(k)) and r.source == v and r.confirmed for k, v in expected.items()) else None
            if event == "notice_pattern_set" and action == "set_pattern":
                return {} if editor.edit.pattern == "구매입찰공고-{{입찰공고번호}}" else None
            if event in {"notice_job_saved", "contract_job_saved", "purchase_job_saved", "derived_job_rebound"} and action == "save":
                if not isinstance(result, dict) or result.get("ok") is not True:
                    return None
                expected = {"notice_job_saved": "물품 구매입찰 공고.hwpx",
                            "contract_job_saved": "낙찰자 선정 및 계약체결 안내.txt",
                            "purchase_job_saved": "계약방법 결정 및 구매추진 안내.txt"}.get(event)
                if expected and editor.edit.template_path != self._asset(expected):
                    return None
                if event == "derived_job_rebound" and editor.edit.data_path != ctx.get("derived_data_path"):
                    return None
                if event == "notice_job_saved":
                    links = {"낙찰자결정방법": "낙찰방법", "담당자 전화번호": "담당자전화"}
                    if (editor.edit.pattern != "구매입찰공고-{{입찰공고번호}}"
                            or not all((r := rows.get(k)) and r.source == v and r.confirmed
                                       for k, v in links.items())):
                        return None
                if event == "contract_job_saved":
                    firm, amount = rows.get("대표계약업체"), rows.get("계약보증금")
                    if not (firm and firm.source == "계약상대자" and firm.confirmed
                            and amount and amount.type == "amount" and amount.fmt == ""):
                        return None
                if event == "purchase_job_saved":
                    item = rows.get("군품명")
                    if not (item and item.slice is not None and editor.edit.records
                            and item.to_mapping().value_for(editor.edit.records[0]) == "드릴"):
                        return None
                return {"job_name": editor.edit.job_name}
            if event == "contract_mapping_set" and action in {"set_source", "set_confirmed"}:
                r = rows.get("대표계약업체")
                return {} if r and r.source == "계약상대자" and r.confirmed else None
            if event == "contract_currency_set" and action == "set_display":
                r = rows.get("계약보증금")
                return {} if r and r.type == "amount" and r.fmt == "" else None
            if event == "purchase_slice_set" and action == "set_slice":
                r = rows.get("군품명")
                sample = editor.edit.records[0] if editor.edit.records else None
                return {} if r and r.source == "군품명" and r.slice is not None and sample and r.to_mapping().value_for(sample) == "드릴" else None
            if event == "purchase_formats_checked" and action in {"set_display", "step_preview"}:
                return {} if any(r.type == "date" for r in rows.values()) and any(r.type == "amount" for r in rows.values()) else None
            if event == "derived_data_selected" and action in {"load_data_sheet", "use_pool_data"}:
                return {} if editor.edit.data_path == ctx.get("derived_data_path") else None
        if screen == "job":
            selected = set(job.data.selected_indices())
            records = job.data.records
            expected_rows = {"first_hwpx": {0, 1, 2}, "repeat_hwpx": {3, 4, 5}}
            lesson = self.progress.selected
            required = expected_rows.get(lesson) if lesson else None
            same_job = job.work.name == ctx.get("job_name") and bool(ctx.get("job_name"))
            if event in {"notice_job_opened", "derived_reopened"} and action == "select_job":
                if event == "notice_job_opened":
                    return {} if same_job else None
                if same_job and job.data.path == ctx.get("derived_data_path") and job.data.sheet == ctx.get("derived_sheet"):
                    self._finish_result("새 데이터 연결 완료", "저장한 작업을 다시 열어 새 파일과 시트를 확인했습니다.",
                                        "job", "data-picker", [], count=1)
                    return {}
                return None
            if event == "rows_cleared" and action in {"set_none", "toggle_record", "select_range"}:
                return {} if same_job and not selected else None
            if event in {"notice_first_filtered", "notice_second_filtered"} and action.startswith("filter_"):
                visible = set(job.data.filter.visible_indices(records)) if job.data.filter else set(range(len(records)))
                return {} if same_job and payload.get("column") == "메모" and visible == required else None
            if event in {"notice_first_rows", "notice_second_rows"} and action in {"toggle_record", "select_range", "set_all", "range_draft_apply"}:
                return {} if same_job and selected == required else None
            if event in {"notice_first_options", "notice_second_options"} and action == "select_slot_option":
                return {} if same_job and lesson and self._correct_notice_options(job, lesson) else None
            if event in {"notice_first_generated", "notice_second_generated"} and action == "generate":
                if (not same_job or selected != required or job.data.path != self._asset("공고목록.xlsx")
                        or job.data.sheet != "공고" or not lesson or not self._correct_notice_options(job, lesson)
                        or job.work.vm.job.filename_pattern != "구매입찰공고-{{입찰공고번호}}"
                        or not isinstance(result, dict) or result.get("succeeded") != 3):
                    return None
                documents = self._result_documents(job)
                expected_ids = {records[i]["입찰공고번호"] for i in required or ()}
                if len(documents) != 3 or not all(any(identifier in doc["name"] for doc in documents)
                                                  for identifier in expected_ids):
                    return None
                ctx["generated"] = documents
                if event == "notice_second_generated":
                    self._finish_result("다시 만든 문서 3건", "새 행의 입찰공고번호로 문서를 만들었습니다.",
                                        "job", "results", ctx["generated"])
                return {}
            if event == "notice_result_opened" and action == "artifact_open":
                artifact = job.runs.artifact_payload()
                if (not same_job or result != {"ok": True} or not ctx.get("generated")
                        or artifact.get("status") != "observed" or not artifact.get("structure")
                        or not any(Path(doc["path"]).name == Path(artifact.get("filename", "")).name
                                   for doc in ctx["generated"])):
                    return None
                self._finish_result("생성한 문서 3건", "결과 문서의 내용을 확인했습니다.", "job", "results", ctx["generated"])
                return {}
            if event == "option_result_reviewed" and action in {"select_slot_option", "open_slot_configuration"}:
                return None
            if event == "option_result_reviewed" and action == "open_workbench":
                if not same_job or not ctx.get("applied") or not isinstance(result, dict) or result.get("ok") is not True:
                    return None
                current = job.execution.current_slot_view(job.work.name)
                projection = current.current_view.projection if current else None
                option_set = [option for slot in projection.slots
                              if slot.display_text == "예산 재배정 안내"
                              for option in slot.options if option.selected and option.effective] if projection else []
                card = wb.snapshot().get("card") or {}
                rendered = "".join(segment.get("text", "") for segment in card.get("segments", []))
                if (any(option.display_text == "안내 포함" for option in option_set)
                        and wb.is_open and wb.job_name == ctx.get("job_name")
                        and "예산 재배정 여부" in rendered):
                    self._finish_result("변경 적용 결과", "고른 안내 문단의 채운 내용을 확인했습니다.",
                                        "workbench", "txt-review", [], count=1)
                    return {}
        if screen == "workbench" or action in {"open_workbench", "copy_clipboard"}:
            if not wb or not wb.is_open or wb.job_name != ctx.get("job_name"):
                return None
            card = wb.snapshot().get("card") or {}
            source_row = card.get("source_row")
            if event in {"contract_two_reviewed", "purchase_two_reviewed"} and action in {"set_current", "step", "open_workbench"}:
                if source_row is not None and wb.view == "filled":
                    seen = set(ctx.get("reviewed_rows", []))
                    seen.add(source_row)
                    ctx["reviewed_rows"] = sorted(seen)
                    return {} if len(seen) >= 2 else None
            if event in {"contract_two_copied", "purchase_copied"} and action == "copy_clipboard":
                if not isinstance(result, dict) or result.get("copied") is not True:
                    return None
                last = wb.snapshot().get("card", {}).get("last_copy") or {}
                copied = set(ctx.get("copied_rows", []))
                copied.add(last.get("row"))
                copied.discard(None)
                ctx["copied_rows"] = sorted(copied)
                target = 2 if event == "contract_two_copied" else 1
                if len(copied) >= target:
                    self._finish_result("TXT 복사 완료", f"서로 다른 {len(copied)}개 행을 복사했습니다.",
                                        "workbench", "txt-copy", [], count=len(copied))
                    return {}
            if event == "blank_observed" and action in {"set_current", "step", "open_workbench"}:
                return {} if "계약보증금" in card.get("empty_fields", []) else None
            if event == "blank_repaired" and action == "set_map_value":
                return {} if "계약보증금" not in card.get("empty_fields", []) else None
        if event in {"derived_data_prepared", "blank_data_prepared"} and screen == "tutorial" and action == "prepare_examples":
            return {"derived_data_path": result["path"], "derived_sheet": "계약" if event == "blank_data_prepared" else "공고"} if isinstance(result, dict) and result.get("path") else None
        return self._match_authoring(event, screen, action, result)

    def _result_documents(self, job) -> list[dict]:
        return [{"name": Path(path).name, "path": str(path), "kind": "hwpx"}
                for path in job.delivered_artifact_paths()]

    def _finish_result(self, title: str, body: str, screen: str, target: str,
                       documents: list[dict], *, count: int | None = None) -> None:
        self.progress.result = {"screen": screen, "target": target, "title": title,
                                "body": body, "count": len(documents) if count is None else count,
                                "documents": documents,
                                "actions": [{"label": "결과 보기", "target": target}]}

    def _match_authoring(self, event: str, screen: str, action: str, result) -> dict | None:
        if screen != "authoring" or not isinstance(result, dict):
            return None
        authoring: Any = self.controllers["authoring"]
        session = authoring.sessions.get(authoring.active_id)
        if session is None or session.media != "txt":
            return None
        ctx = self._context()
        source = self._asset("낙찰자 선정 및 계약체결 안내.txt")
        if session.source_path != source:
            return None
        analysis = session.analysis
        fields = {f.get("name") for f in analysis.get("fields", [])}
        slots = analysis.get("slots", [])
        if event in {"field_practice_opened", "option_practice_opened"} and action == "open_authoring_document":
            return {}
        if event == "practice_field_created" and action == "update":
            return {} if "재배정기한" in fields and "10일" not in session.content.decode("utf-8") else None
        if event == "field_trial_input" and action == "trial_input":
            return {} if session.values.get("재배정기한") else None
        if event == "field_trial_passed" and action == "trial":
            report = result.get("report") or {}
            return {} if result.get("ok") is not False and not report.get("missing_fields") and not report.get("errors") else None
        if event in {"field_practice_saved", "option_practice_saved"} and action in {"save", "save_authoring_document"}:
            if result.get("ok") is True and authoring._readiness(session)["state"] == "ready":
                ctx.setdefault("saved_fingerprints", {})[result["path"]] = fingerprint(Path(result["path"]))
                if event == "field_practice_saved":
                    self._finish_result("내 필드 준비 완료", "재배정기한 필드를 시험하고 사용 준비 상태로 저장했습니다.",
                                        "authoring", "save-template", [], count=1)
                return {}
        if event == "practice_item_created" and action == "update":
            return {} if any(slot.get("label") == "예산 재배정 안내" for slot in slots) else None
        if event == "practice_options_created" and action == "update":
            return {} if any({o.get("label") for o in slot.get("options", [])} >= {"안내 포함", "안내 생략"} for slot in slots) else None
        if event == "practice_both_trials_passed" and action == "trial":
            report = result.get("report") or {}
            if result.get("ok") is False or report.get("missing_fields") or report.get("errors"):
                return None
            for slot in slots:
                if slot.get("label") == "예산 재배정 안내":
                    options = {option.get("id") for option in slot.get("options", [])}
                    tested = {option for (slot_id, option), (revision, _fingerprint)
                              in session.trial_coverage_evidence.items()
                              if slot_id == slot.get("id") and revision == session.revision}
                    return {} if options == tested and len(options) == 2 else None
        if event == "option_change_applied" and action == "apply_job":
            if result.get("job_name") == ctx.get("job_name") and result.get("is_current") is True:
                return {"applied": True}
        return None
