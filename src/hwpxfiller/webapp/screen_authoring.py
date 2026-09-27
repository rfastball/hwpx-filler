"""Template authoring bridge controller. Paths enter through trusted native methods only."""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from pathlib import PurePosixPath
from uuid import uuid4

from hwpxcore.package import HwpxPackage

from ..application.template_authoring_session import AuthoringSession
from ..domain import template_authoring as semantics
from ..external.authoring_store import AuthoringStore, ExternalChangeError, digest
from ..external.authoring_transfer import capture_semantic, paste_semantic
from ..external.hwpx_authoring import (
    analyze_hwpx,
    apply_hwpx,
    available_commands_hwpx,
    search_hwpx,
    syntax_view_hwpx,
    trial_hwpx,
)
from ..external.rhwp_preflight import compare_rhwp_roundtrip
from ..external.text_materialization_conformance import trial_txt_authoring
from ..host.locations import default_authoring_dir
from .screens import MutationSink, PushSink

_INVALID_SELECTION = "선택 위치가 유효하지 않습니다."
_BAD_PAYLOAD = "액션 입력이 올바르지 않습니다."
_SAVE_FIRST = "문서를 저장한 뒤 기존 작업에 적용하세요."
_EXTERNAL_CHANGED = "파일이 외부에서 변경되었습니다. 다시 확인하세요."
# 문제 목록(§7.1) 중 webapp 이 투영하는 두 종류. 구조 진단은 domain/external 이 그대로 낸다.
_CATEGORY_TRIAL_INPUT = "trial_input"
_TRIAL_VALUE_MISSING = "시험값이 없습니다."
_TRIAL_SELECTION_MISSING = "시험 선택을 지정하세요."
_COMPATIBILITY_SUMMARY = "이 요소는 표시할 수 있지만 변경 후 보존을 확인할 수 없습니다. 원본을 유지한 채 확인하세요."
#: 본문(내용)을 바꾸는 명령 — 의미 경계만 바꾸는 명령과 구별한다(F38). `paste` 는 붙여넣기 미리보기.
_BODY_CHANGING = frozenset({"delete", "unset_field", "repair_marker", "duplicate", "move", "paste"})


class AuthoringController:
    name = "authoring"

    def __init__(
        self, push: PushSink, *, directory: Path | None = None,
        job_registry=None, template_change=None,
    ) -> None:
        self._push_sink = push
        self.store = AuthoringStore(directory or default_authoring_dir())
        self._job_registry = job_registry
        self._template_change = template_change
        self.sessions: dict[str, AuthoringSession] = {}
        self.active_id = ""
        self._lock = threading.RLock()
        self._recoverable = self.store.list_drafts()
        self._clipboard: tuple[str, dict] | None = None
        # 템플릿 bytes 변이 통지 sink — tpl 채널의 `mutation_sinks` 와 같은 `(kind, path)`
        # 형태다. 저장은 파일을 제자리에서 바꾸므로 같은 파일을 든 편집 세션이 되읽어야
        # 한다(#320). 배선은 앱 조립부가 한다(`app.py`).
        self.mutation_sinks: list[MutationSink] = []

    def _refresh_recoverable(self) -> None:
        self._recoverable = self.store.list_drafts()

    @staticmethod
    def _media(path: Path) -> str:
        media = path.suffix.lower().lstrip(".")
        if media not in {"hwpx", "txt"}:
            raise ValueError("HWPX 또는 TXT 파일만 열 수 있습니다.")
        return media

    @staticmethod
    def _parse(media: str, content: bytes):
        if media == "txt":
            return content.decode("utf-8")
        if media == "hwpx":
            return HwpxPackage.from_bytes(content)
        raise ValueError("알 수 없는 문서 형식입니다.")

    @staticmethod
    def _wire(media: str, content: bytes) -> str:
        return content.decode("utf-8") if media == "txt" else base64.b64encode(content).decode("ascii")

    @staticmethod
    def _unwire(media: str, content: object) -> bytes:
        if not isinstance(content, str):
            raise ValueError("문서 내용은 문자열이어야 합니다.")
        if media == "txt":
            return content.encode("utf-8")
        return base64.b64decode(content, validate=True)

    @staticmethod
    def _section_entries(content: bytes) -> list[str]:
        package = HwpxPackage.from_bytes(content)
        manifest = package.entries.get("Contents/content.hpf")
        if manifest is None:
            sections = [entry for entry in package.content_xml_names()
                        if PurePosixPath(entry).name.lower().startswith("section")]
            if len(sections) == 1:
                return sections
            raise ValueError("HWPX 본문 차례를 확인할 수 없습니다.")
        root = ET.fromstring(manifest)
        items = {element.get("id"): element.get("href") for element in root.iter()
                 if element.tag.rsplit("}", 1)[-1] == "item"}
        ordered = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "itemref":
                continue
            href = items.get(element.get("idref"))
            if not href:
                raise ValueError("HWPX 본문 차례에 없는 항목입니다.")
            name = PurePosixPath(href).name
            if not name.lower().startswith("section") or not name.lower().endswith(".xml"):
                continue
            entry = href if href in package.entries else str(PurePosixPath("Contents") / href)
            if entry not in package.entries:
                raise ValueError("HWPX 본문 차례가 없는 파일을 가리킵니다.")
            ordered.append(entry)
        if not ordered or len(set(ordered)) != len(ordered):
            raise ValueError("HWPX 본문 차례가 비었거나 중복되었습니다.")
        return ordered

    def _analyze(self, media: str, content: bytes) -> dict:
        parsed = self._parse(media, content)
        return semantics.analyze(media, parsed) if media == "txt" else analyze_hwpx(parsed)

    def _session(self, payload: dict, *, revision: bool = False) -> AuthoringSession:
        sid = payload.get("session_id")
        if not isinstance(sid, str) or sid not in self.sessions:
            raise ValueError("열려 있지 않은 문서 세션입니다.")
        session = self.sessions[sid]
        if revision and (
            type(payload.get("revision")) is not int
            or payload["revision"] != session.revision
        ):
            raise ValueError("문서가 변경되었습니다. 최신 상태에서 다시 시도하세요.")
        return session

    def _contents(self, session: AuthoringSession) -> dict:
        result = {
            "session_id": session.id,
            "revision": session.revision,
            "media": session.media,
            "content": self._wire(session.media, session.content),
            "analysis": session.analysis,
        }
        if session.media == "hwpx":
            result["section_entries"] = self._section_entries(session.content)
        return result

    def _tab(self, session: AuthoringSession) -> dict:
        path = session.save_path or session.source_path
        return {
            "id": session.id,
            "media": session.media,
            "path": path,
            "save_path": session.save_path,
            "save_as_required": not bool(session.save_path),
            "name": Path(path).name if path else "새 템플릿",
            "revision": session.revision,
            "dirty": session.dirty,
            "cases_dirty": session.cases_dirty or session.trial_inputs_dirty,
            "trial_inputs_dirty": session.trial_inputs_dirty,
            "analysis": session.analysis,
            "values": dict(session.values),
            "selected": dict(session.selected),
            "cases": [self._case_view(session, case) for case in session.cases],
            "cases_error": session.cases_error,
            "trial_state": (
                "failed" if session.trial_error else
                "untried" if session.trial_result is None else
                "stale" if session.trial_stale else
                "failed" if session.trial_result.get("report", {}).get("missing_fields")
                or session.trial_result.get("report", {}).get("errors") else "current"
            ),
            "trial_result": session.trial_result,
            "trial_coverage": self._trial_coverage(session),
            "trial_error": session.trial_error,
            "recovery": session.recovery,
            "recovery_saved_at": session.recovery_saved_at,
            "recovery_key": session.draft_key if session.recovery else "",
            "external_changed": session.external_changed,
            "rhwp_editable": session.rhwp_editable,
            "rhwp_diagnostics": session.rhwp_diagnostics,
            "readiness": self._readiness(session),
            "problems": self._problems(session),
        }

    @staticmethod
    def _readiness(session: AuthoringSession) -> dict:
        """Draft vs ready is decided by the structure diagnostics alone (F35, §9.1, AC14)."""
        severities = [item.get("severity") for item in session.analysis.get("diagnostics", [])]
        errors = severities.count(semantics.SEVERITY_ERROR)
        warnings = severities.count(semantics.SEVERITY_WARNING)
        return {
            "state": "draft" if errors else "ready",
            "errors": errors,
            "warnings": warnings,
            "message": f"사용 전에 구조 오류 {errors}개를 확인하세요." if errors else None,
        }

    @staticmethod
    def _problems(session: AuthoringSession) -> list[dict]:
        """Union of structure diagnostics, trial-input problems and compatibility warnings (F24, §7.1)."""
        problems = list(session.analysis.get("diagnostics", []))
        trial_attempted = (session.trial_result is not None or bool(session.trial_error)
                           or bool(session.values) or bool(session.selected))
        if trial_attempted:
            for field in session.analysis.get("fields", []):
                if session.values.get(field["name"]) is None:
                    occurrences = field.get("occurrences") or [None]
                    problems.append({
                        "severity": semantics.SEVERITY_ERROR, "category": _CATEGORY_TRIAL_INPUT,
                        "message": _TRIAL_VALUE_MISSING, "target": field["name"],
                        "location": occurrences[0],
                        "actions": [semantics.navigate_action(occurrences[0])],
                    })
            for slot in session.analysis.get("slots", []):
                options = slot.get("options", [])
                if options and session.selected.get(slot["id"]) not in {o["id"] for o in options}:
                    problems.append({
                        "severity": semantics.SEVERITY_ERROR, "category": _CATEGORY_TRIAL_INPUT,
                        "message": _TRIAL_SELECTION_MISSING, "target": slot["id"],
                        "location": slot.get("location"),
                        "actions": [semantics.navigate_action(slot.get("location"))],
                    })
        if session.rhwp_editable is False:
            problems.append({
                "severity": semantics.SEVERITY_WARNING, "category": semantics.CATEGORY_COMPATIBILITY,
                "message": _COMPATIBILITY_SUMMARY, "target": None, "location": None, "actions": [],
            })
            problems.extend({
                "severity": semantics.SEVERITY_WARNING, "category": semantics.CATEGORY_COMPATIBILITY,
                "message": item.get("message", ""), "target": item.get("entry"),
                "location": None, "actions": [],
            } for item in session.rhwp_diagnostics)
        return problems

    @staticmethod
    def _trial_coverage(session: AuthoringSession) -> list[dict]:
        fingerprint = AuthoringController._trial_input_fingerprint(session)
        return [
            {"slot_id": slot["id"], "option_id": option["id"],
             "state": ("untried" if evidence is None else "current"
                       if evidence == (session.revision, fingerprint) else "stale")}
            for slot in session.analysis.get("slots", [])
            for option in slot.get("options", [])
            for evidence in (session.trial_coverage_evidence.get((slot["id"], option["id"])),)
        ]

    @staticmethod
    def _trial_input_fingerprint(session: AuthoringSession) -> str:
        inputs = {"values": session.values, "selected": session.selected}
        return digest(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    @staticmethod
    def _schema_key(analysis: dict) -> str:
        shape = {
            "fields": sorted(field["name"] for field in analysis.get("fields", [])),
            "slots": sorted(
                (slot.get("id", ""), tuple(sorted(o.get("id", "") for o in slot.get("options", []))))
                for slot in analysis.get("slots", [])
            ),
        }
        return digest(json.dumps(shape, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def _case_view(self, session: AuthoringSession, case: dict) -> dict:
        return {**case, "needs_review": case.get("schema") != self._schema_key(session.analysis)}

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "tabs": [self._tab(session) for session in self.sessions.values()],
                "active_id": self.active_id,
                "recoverable": list(self._recoverable),
            }

    def initial(self) -> dict:
        return self.snapshot()

    def close_guard_reason(self) -> str:
        with self._lock:
            documents = sum(session.dirty for session in self.sessions.values())
            cases = sum(
                session.cases_dirty or session.trial_inputs_dirty
                for session in self.sessions.values()
            )
            if documents or cases:
                return f"저작 작업대: 미저장 문서 {documents}개 · 시험 자료 {cases}개"
            return ""

    def close_flush_required(self) -> bool:
        with self._lock:
            return bool(self.sessions)

    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def open_path(self, path: str | Path, *, as_template: bool = True) -> dict:
        """Native dialog/library handoff only; never register as a frontend action."""
        with self._lock:
            source = Path(path).resolve(strict=True)
            media = self._media(source)
            for session in self.sessions.values():
                if session.source_path == str(source):
                    self.active_id = session.id
                    self._push()
                    return self._contents(session)
            content, baseline = self.store.read_document(source)
            analysis = self._analyze(media, content)
            key = self.store.key(source)
            draft_meta = next((item for item in self._recoverable if item["key"] == key), None)
            cases: list[dict] = []
            cases_error = ""
            if as_template:
                try:
                    cases = self.store.read_cases(key)
                    self._validate_cases(cases)
                except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
                    cases_error = f"시험 케이스를 읽을 수 없습니다: {exc}"
            session = AuthoringSession(
                id=uuid4().hex,
                media=media,
                content=content,
                source_path=str(source),
                save_path=str(source) if as_template else "",
                baseline=baseline if as_template else None,
                source_baseline=baseline,
                saved_content=content,
                analysis=analysis,
                saved_analysis=analysis,
                draft_key=key,
                recovery=draft_meta is not None,
                recovery_saved_at=draft_meta.get("updated_at", "") if draft_meta else "",
                external_changed=False,
                cases=cases,
                cases_error=cases_error,
            )
            self.sessions[session.id] = session
            self.active_id = session.id
            self._push()
            return self._contents(session)

    def save_to_path(self, session_id: str, revision: int, path: str | Path) -> dict:
        """Native Save As handoff. Existing destination is never silently replaced."""
        with self._lock:
            session = self._session({"session_id": session_id, "revision": revision}, revision=True)
            if session.recovery:
                raise ValueError("복구 초안을 복원하거나 폐기한 뒤 저장하세요.")
            target = Path(path).resolve()
            if self._media(target) != session.media:
                raise ValueError("저장할 파일 형식이 열린 문서와 다릅니다.")
            current_path = Path(session.save_path).resolve() if session.save_path else None
            expected = session.baseline if current_path == target else None
            try:
                new_baseline = self.store.save_document(target, session.content, expected)
            except ExternalChangeError as exc:
                if current_path != target:
                    return {"conflict": "destination_exists",
                            "message": "선택한 위치에 파일이 이미 있습니다. 다른 이름을 선택하세요."}
                session.external_changed = True
                self._push()
                return {"external_changed": True, "fingerprint": exc.fingerprint,
                        "message": _EXTERNAL_CHANGED}
            old_draft = session.draft_key
            old_save_path = session.save_path
            session.save_path = str(target)
            session.baseline = new_baseline
            session.saved_content = session.content
            session.saved_analysis = session.analysis
            session.identifier_changes = []
            session.draft_key = self.store.key(target)
            session.recovery = False
            session.recovery_saved_at = ""
            session.external_changed = False
            if old_save_path != session.save_path and session.cases:
                session.cases_dirty = True
            self.store.discard_draft(old_draft)
            self.store.discard_draft(session.draft_key)
            self._refresh_recoverable()
            # sink 의 실패는 삼키지 않는다(confirm-or-alarm) — 조용한 미정산이 더 나쁘다.
            for sink in self.mutation_sinks:
                sink("mutated", str(target))
            self._push()
            errors = self._readiness(session)["errors"]
            return {"ok": True, "path": str(target), "revision": session.revision,
                    "notice": (f"초안은 저장되었습니다. 사용 전에 구조 오류 {errors}개를 확인하세요."
                               if errors else None)}

    def import_cases_path(self, session_id: str, path: str | Path) -> dict:
        """Native picker handoff only."""
        with self._lock:
            session = self._session({"session_id": session_id})
            cases = self.store.import_cases(Path(path))
            self._validate_cases(cases)
            session.cases = cases
            session.cases_error = ""
            session.cases_dirty = True
            self._push()
            return {"ok": True, "cases": [self._case_view(session, c) for c in cases]}

    def export_cases_path(self, session_id: str, path: str | Path) -> dict:
        """Native picker handoff only; export never implies home save."""
        with self._lock:
            session = self._session({"session_id": session_id})
            self.store.export_cases(Path(path), session.cases)
            return {"ok": True, "path": str(path)}

    def export_result_path(self, session_id: str, revision: int, path: str | Path) -> dict:
        """Native picker handoff; stale or failed trial output cannot leave the app."""
        with self._lock:
            session = self._session({"session_id": session_id, "revision": revision}, revision=True)
            if session.trial_stale or session.trial_result is None or session.trial_error:
                raise ValueError("최신 결과 시험을 먼저 완료하세요.")
            report = session.trial_result.get("report", {})
            if report.get("missing_fields") or report.get("errors"):
                raise ValueError("실패한 시험 결과는 내보낼 수 없습니다.")
            target = Path(path)
            if self._media(target) != session.media:
                raise ValueError("결과 파일 형식이 문서와 다릅니다.")
            if session.media == "txt":
                data = session.trial_result["text"].encode("utf-8")
            else:
                data = base64.b64decode(session.trial_result["content"], validate=True)
            self.store.export_result(target, data)
            return {"ok": True, "path": str(target)}

    @staticmethod
    def _validate_cases(cases: list[dict]) -> None:
        names: set[str] = set()
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("name"), str):
                raise ValueError("시험 케이스 이름이 올바르지 않습니다.")
            name = case["name"].strip()
            if not name or name in names:
                raise ValueError("시험 케이스 이름이 비었거나 중복되었습니다.")
            if not isinstance(case.get("values"), dict) or not isinstance(case.get("selected"), dict):
                raise ValueError("시험 케이스 입력이 올바르지 않습니다.")
            names.add(name)

    def dispatch(self, action: str, payload: dict):
        handlers = {
            "new": self._do_new,
            "activate": self._do_activate,
            "content": self._do_content,
            "update": self._do_update,
            "preview": self._do_preview,
            "copy": self._do_copy,
            "preview_paste": self._do_preview_paste,
            "rhwp_roundtrip_preflight": self._do_rhwp_roundtrip_preflight,
            "trial_input": self._do_trial_input,
            "trial": self._do_trial,
            "search": self._do_search,
            "locate": self._do_locate,
            "commands": self._do_commands,
            "syntax": self._do_syntax,
            "case_upsert": self._do_case_upsert,
            "case_remove": self._do_case_remove,
            "save_cases": self._do_save_cases,
            "save": self._do_save,
            "check_external": self._do_check_external,
            "external_content": self._do_external_content,
            "reload": self._do_reload,
            "recover": self._do_recover,
            "recover_draft": self._do_recover_draft,
            "recovery_content": self._do_recovery_content,
            "discard_recovery": self._do_discard_recovery,
            "discard_draft": self._do_discard_draft,
            "close": self._do_close,
            "impact": self._do_impact,
            "prepare_apply": self._do_prepare_apply,
            "apply_job": self._do_apply_job,
        }
        if action not in handlers:
            raise ValueError(f"알 수 없는 authoring 액션: {action!r}")
        if not isinstance(payload, dict):
            raise ValueError(_BAD_PAYLOAD)
        with self._lock:
            result = handlers[action](payload)
            self._push()
            return result

    def _do_new(self, p: dict) -> dict:
        media = p.get("media")
        if media not in {"txt", "hwpx"}:
            raise ValueError("HWPX 또는 TXT 형식만 만들 수 있습니다.")
        content = self._unwire(media, p.get("content", ""))
        session = AuthoringSession(
            id=uuid4().hex,
            media=media,
            content=content,
            analysis=self._analyze(media, content),
            draft_key=uuid4().hex,
        )
        self.sessions[session.id] = session
        self.active_id = session.id
        return self._contents(session)

    def _do_activate(self, p: dict) -> dict:
        session = self._session(p)
        self.active_id = session.id
        return self._contents(session)

    def _do_content(self, p: dict) -> dict:
        return self._contents(self._session(p))

    def _do_update(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        if session.recovery:
            raise ValueError("복구 초안을 복원하거나 폐기한 뒤 편집하세요.")
        if session.media == "hwpx" and session.rhwp_editable is not True:
            raise ValueError("문서 보존 검증이 끝나지 않아 HWPX를 수정할 수 없습니다.")
        content = self._unwire(session.media, p.get("content"))
        analysis = self._analyze(session.media, content)
        if content != session.saved_content:
            session.recovery_saved_at = self.store.write_draft(
                session.draft_key,
                path=session.save_path or session.source_path,
                media=session.media,
                baseline=session.baseline,
                source_baseline=session.source_baseline,
                content=content,
            )
        else:
            self.store.discard_draft(session.draft_key)
            session.recovery_saved_at = ""
        # 미리보기가 낸 내용이 그대로 확정되면 그 미리보기의 식별자 변경을 원장에 적는다(F19).
        # 다른 내용이 오면 미리보기는 폐기된 것이다 — 추측으로 이름 변경을 복원하지 않는다.
        if session.last_preview is not None and content == session.last_preview[0]:
            session.identifier_changes.extend(session.last_preview[1])
        session.last_preview = None
        session.replace_content(content, analysis)
        session.trial_error = ""
        self._refresh_recoverable()
        session.recovery = False
        return {"session_id": session.id, "revision": session.revision, "analysis": analysis}

    def _do_preview(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        if session.recovery:
            raise ValueError("복구 초안을 복원하거나 폐기한 뒤 편집하세요.")
        if session.media == "hwpx" and session.rhwp_editable is not True:
            raise ValueError("문서 보존 검증이 끝나지 않아 HWPX를 수정할 수 없습니다.")
        command = p.get("command")
        if not isinstance(command, dict):
            raise ValueError("명령이 올바르지 않습니다.")
        parsed = self._parse(session.media, session.content)
        try:
            changed, preview = (
                semantics.apply(session.media, parsed, command)
                if session.media == "txt" else apply_hwpx(parsed, command)
            )
        except (semantics.NameConflict, semantics.CascadeRequired) as exc:
            # 구조화된 거절(AC08·AC10) — 문서는 바뀌지 않았고 프런트가 해결 경로를 그린다.
            return {"ok": False, "refusal": exc.to_dict(),
                    "session_id": session.id, "revision": session.revision}
        if session.media == "txt":
            if not isinstance(changed, str):
                raise TypeError("TXT 편집 결과가 문자열이 아닙니다.")
            content = changed.encode("utf-8")
        else:
            if not isinstance(changed, HwpxPackage):
                raise TypeError("HWPX 편집 결과가 문서가 아닙니다.")
            content = changed.to_bytes()
        impact = self._preview_impact(session, preview, command)
        session.last_preview = (content, impact["structure_delta"]["renamed"])
        return {
            **preview,
            "session_id": session.id,
            "revision": session.revision,
            "content": self._wire(session.media, content),
            **impact,
        }

    def _preview_impact(self, session: AuthoringSession, preview: dict, command: dict) -> dict:
        linked_jobs, corrupted_jobs = self._linked_jobs(session)
        before_fields = {item["name"] for item in session.analysis.get("fields", [])}
        after_fields = {item["name"] for item in preview["result"].get("fields", [])}
        action = str(command.get("type", ""))
        return {
            "linked_jobs": [job.name for job in linked_jobs],
            "impact_unverified": len(corrupted_jobs),
            "field_delta": {
                "added_fields": sorted(after_fields - before_fields),
                "removed_fields": sorted(before_fields - after_fields),
            },
            "structure_delta": self._structure_delta(session.analysis, preview["result"],
                                                     self._renamed(command)),
            "body_changed": (action in _BODY_CHANGING
                             or (action == "create_field" and bool(preview.get("original")))),
        }

    @staticmethod
    def _renamed(command: dict) -> list[dict]:
        """A rename command whose identifier actually changes (label-only edits are not renames)."""
        action = command.get("type")
        if action == "rename_slot" and "id" in command and command["id"] != command.get("slot_id"):
            return [{"kind": "slot", "from": command.get("slot_id"), "to": command["id"]}]
        if action == "rename_option" and "id" in command and command["id"] != command.get("option_id"):
            return [{"kind": "option", "slot_id": command.get("slot_id"),
                     "from": command.get("option_id"), "to": command["id"]}]
        return []

    @staticmethod
    def _structure_delta(before: dict, after: dict, renamed: list[dict]) -> dict:
        def slots(analysis: dict) -> set[str]:
            return {slot["id"] for slot in analysis.get("slots", [])}

        def options(analysis: dict) -> set[tuple[str, str]]:
            return {(slot["id"], option["id"]) for slot in analysis.get("slots", [])
                    for option in slot.get("options", [])}

        return {
            "added_slots": sorted(slots(after) - slots(before)),
            "removed_slots": sorted(slots(before) - slots(after)),
            "added_options": [list(pair) for pair in sorted(options(after) - options(before))],
            "removed_options": [list(pair) for pair in sorted(options(before) - options(after))],
            "renamed": list(renamed),
        }

    def _do_rhwp_roundtrip_preflight(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        if session.media != "hwpx":
            raise ValueError("HWPX 문서만 보존 검증을 합니다.")
        exported = self._unwire("hwpx", p.get("content"))
        result = compare_rhwp_roundtrip(session.content, exported)
        session.rhwp_editable = result["editable"]
        session.rhwp_diagnostics = result["diagnostics"]
        return result

    def _do_copy(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        selector = p.get("selector")
        if not isinstance(selector, dict):
            raise ValueError("복사할 의미 요소를 선택하세요.")
        captured = capture_semantic(session.media, self._parse(session.media, session.content), selector)
        token = uuid4().hex
        self._clipboard = (token, captured)
        return {"clipboard_token": token, "kind": captured["kind"], "media": session.media}

    def _do_preview_paste(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        if session.recovery or (session.media == "hwpx" and session.rhwp_editable is not True):
            raise ValueError("이 문서는 현재 붙여넣을 수 없습니다.")
        if (self._clipboard is None or not isinstance(p.get("clipboard_token"), str)
                or p["clipboard_token"] != self._clipboard[0]):
            raise ValueError("복사한 내용이 변경되었습니다. 다시 복사하세요.")
        destination = p.get("destination")
        if not isinstance(destination, dict) or type(p.get("with_meaning")) is not bool:
            raise ValueError("붙여넣을 위치와 방식을 확인하세요.")
        captured = self._clipboard[1]
        if captured.get("media") != session.media:
            raise ValueError("다른 문서 형식으로 의미 요소를 붙여넣을 수 없습니다.")
        changed, preview = paste_semantic(
            session.media, self._parse(session.media, session.content), captured,
            destination, with_meaning=p["with_meaning"],
        )
        content = changed.encode("utf-8") if isinstance(changed, str) else changed.to_bytes()
        return {**preview, "session_id": session.id, "revision": session.revision,
                "content": self._wire(session.media, content),
                "clipboard_token": self._clipboard[0],
                **self._preview_impact(session, preview, {"type": "paste"})}

    def _do_trial_input(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        values, selected = p.get("values"), p.get("selected")
        if not isinstance(values, dict) or not isinstance(selected, dict):
            raise ValueError("시험 입력이 올바르지 않습니다.")
        session.replace_trial_input(values, selected)
        session.trial_error = ""
        return {"input_revision": session.trial_input_revision, "stale": session.trial_stale}

    def _do_trial(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        parsed = self._parse(session.media, session.content)
        session.trial_document_revision = -1
        session.trial_values_revision = -1
        try:
            if session.media == "txt":
                assert isinstance(parsed, str)
                result = trial_txt_authoring(parsed, session.values, session.selected)
            else:
                assert isinstance(parsed, HwpxPackage)
                result = trial_hwpx(parsed, session.values, session.selected)
        except (ValueError, TypeError) as exc:
            session.trial_error = str(exc)
            return {"ok": False, "message": session.trial_error}
        if session.media == "hwpx":
            result = {
                **result,
                "content": base64.b64encode(result["bytes"]).decode("ascii"),
                "section_entries": self._section_entries(result["bytes"]),
            }
            del result["bytes"]
        result["tested_selection"] = dict(session.selected)
        result["source_revision"] = session.revision
        report = result.get("report") or {}
        if not report.get("missing_fields") and not report.get("errors"):
            fingerprint = self._trial_input_fingerprint(session)
            for slot in session.analysis.get("slots", []):
                for option in slot.get("options", []):
                    if session.selected.get(slot["id"]) == option["id"]:
                        session.trial_coverage_evidence[(slot["id"], option["id"])] = (
                            session.revision, fingerprint
                        )
        session.trial_result = result
        session.trial_error = ""
        session.trial_document_revision = session.revision
        session.trial_values_revision = session.trial_input_revision
        return {"session_id": session.id, "revision": session.revision, "input_revision": session.trial_input_revision, **result}

    def _do_search(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        query = p.get("query")
        kind = p.get("kind", "text")
        if kind == "body":
            kind = "text"
        if not isinstance(query, str) or kind not in {"text", "field", "structure", "all"}:
            raise ValueError("검색 조건이 올바르지 않습니다.")
        if not query:
            return {"hits": []}
        if session.media == "hwpx":
            package = self._parse(session.media, session.content)
            if kind == "all":
                return {"hits": [*search_hwpx(package, query, "text")["hits"],
                                 *search_hwpx(package, query, "field")["hits"],
                                 *search_hwpx(package, query, "structure")["hits"]]}
            return search_hwpx(package, query, kind)
        hits = []
        if kind in {"field", "all"}:
            for field in session.analysis.get("fields", []):
                if query.casefold() in field["name"].casefold():
                    hits.extend(
                        {"kind": "field", "label": field["name"], **occurrence}
                        for occurrence in field["occurrences"]
                    )
        if kind in {"structure", "all"}:
            for slot in session.analysis.get("slots", []):
                if any(query.casefold() in str(slot.get(key, "")).casefold()
                       for key in ("id", "label")):
                    location = slot.get("location") or {}
                    hits.append({"kind": "slot", "slot_id": slot["id"],
                                 "label": slot.get("label") or slot["id"], **{
                                     key: location[key] for key in ("start", "end")
                                     if key in location
                                 }, "line": location.get("begin_marker_line")})
                for option in slot.get("options", []):
                    if any(query.casefold() in str(option.get(key, "")).casefold()
                           for key in ("id", "label")):
                        location = option.get("location") or {}
                        hits.append({"kind": "option", "slot_id": slot["id"],
                                     "option_id": option["id"],
                                     "label": option.get("label") or option["id"], **{
                                         key: location[key] for key in ("start", "end")
                                         if key in location
                                     }, "line": location.get("begin_marker_line")})
        if kind in {"text", "all"} and session.media == "txt":
            source = session.content.decode("utf-8")
            for match in re.finditer(re.escape(query), source, flags=re.IGNORECASE):
                index, end = match.span()
                start_unit = len(source[:index].encode("utf-16-le")) // 2
                end_unit = len(source[:end].encode("utf-16-le")) // 2
                hits.append({"kind": "text", "start": start_unit, "end": end_unit,
                             "context": source[max(0, index - 20):min(len(source), end + 20)]})
        return {"hits": hits}

    def _commands(self, session: AuthoringSession, selection: dict, context: dict) -> list[dict]:
        """Availability of every command for one selection — the domain decides, we carry (F40)."""
        parsed = self._parse(session.media, session.content)
        if session.media == "txt":
            return semantics.available_commands("txt", parsed, selection, context)
        return available_commands_hwpx(parsed, selection, context)

    @staticmethod
    def _invalid_locate() -> dict:
        return {"matches": [], "context": {"slot_id": None, "option_id": None,
                                           "reason": _INVALID_SELECTION},
                "commands": semantics.availability_entries(
                    dict.fromkeys(semantics.COMMAND_TYPES, semantics.REASON_INVALID_SELECTION))}

    def _do_commands(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        selection, context = p.get("selection"), p.get("context", None)
        if not isinstance(selection, dict):
            raise ValueError(semantics.REASON_INVALID_SELECTION)
        if context is not None and not isinstance(context, dict):
            raise ValueError(_BAD_PAYLOAD)
        return {"commands": self._commands(session, selection, context or {})}

    def _do_syntax(self, p: dict) -> dict:
        """Read-only TXT-grammar view of the current meaning (F26, §3.2)."""
        session = self._session(p)
        parsed = self._parse(session.media, session.content)
        if session.media == "txt":
            return {"sections": [{"entry": "", "text": parsed}], "note": None}
        return syntax_view_hwpx(parsed)

    def _do_locate(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        selection = p.get("selection")
        if not isinstance(selection, dict):
            raise ValueError("선택 위치가 올바르지 않습니다.")
        start, end = selection.get("start"), selection.get("end")
        if type(start) is not int or type(end) is not int or start < 0 or end < 0:
            return self._invalid_locate()
        native = session.media == "hwpx"
        entry = selection.get("entry")
        first = selection.get("start_paragraph", selection.get("paragraph"))
        last = selection.get("end_paragraph", first)
        if native and (not isinstance(entry, str) or type(first) is not int
                       or type(last) is not int or first < 0 or last < first
                       or entry not in self._section_entries(session.content)):
            return self._invalid_locate()
        first_paragraph = first if isinstance(first, int) else -1
        last_paragraph = last if isinstance(last, int) else -1
        if (not native or first == last) and end < start:
            return self._invalid_locate()
        # 표 셀 안 선택은 rhwp 커서 경로(cell_path)를 함께 싣는다 — 없으면 본문 문단이다.
        cell_path = selection.get("cell_path") if native else None
        if cell_path is not None and not (
            isinstance(cell_path, list) and 0 < len(cell_path) <= 16
            and all(isinstance(step, dict)
                    and set(step) == {"parent_paragraph", "control", "cell", "paragraph"}
                    and all(type(value) is int and value >= 0 for value in step.values())
                    for step in cell_path)
        ):
            return self._invalid_locate()

        def hits(place: dict | None) -> bool:
            if not place:
                return False
            if native:
                # 항목·선택 영역(책갈피)은 본문 문단 단위다 — 셀 안 선택은 영역에 속하지 않는다.
                return (cell_path is None
                        and place.get("entry") == entry
                        and type(place.get("start_paragraph")) is int
                        and type(place.get("end_paragraph")) is int
                        and place["start_paragraph"] <= last_paragraph
                        and first_paragraph <= place["end_paragraph"])
            low, high = place.get("start"), place.get("end")
            return (type(low) is int and type(high) is int
                    and (low <= start <= high if start == end
                         else low < end and start < high))

        def contains(place: dict | None) -> bool:
            if not hits(place):
                return False
            assert place is not None
            if native:
                return (place["start_paragraph"] <= first_paragraph
                        and last_paragraph <= place["end_paragraph"])
            return place["start"] <= start and end <= place["end"]

        matches: list[dict] = []
        containing_slots: list[str] = []
        containing_options: list[tuple[str, str]] = []
        for field in session.analysis.get("fields", []):
            for occurrence in field.get("occurrences", []):
                if native:
                    paragraph = occurrence.get("paragraph")
                    if (occurrence.get("entry") != entry or type(paragraph) is not int
                            or occurrence.get("cell_path") != cell_path
                            or not first_paragraph <= paragraph <= last_paragraph):
                        continue
                    low, high = occurrence.get("start"), occurrence.get("end")
                    if type(low) is not int or type(high) is not int:
                        matches.append({"kind": "field", "name": field["name"],
                                        "location": occurrence, "source": occurrence,
                                        "approximate": True})
                    elif ((first_paragraph < paragraph < last_paragraph)
                          or (first_paragraph == last_paragraph == paragraph
                              and (low <= start <= high if start == end
                                   else low < end and start < high))
                          or (paragraph == first_paragraph < last_paragraph and start <= high)
                          or (paragraph == last_paragraph > first_paragraph and low <= end)):
                        matches.append({"kind": "field", "name": field["name"],
                                        "location": occurrence, "source": occurrence})
                    continue
                if hits(occurrence):
                    matches.append({"kind": "field", "name": field["name"],
                                    "location": occurrence, "source": occurrence})
        for slot in session.analysis.get("slots", []):
            location = slot.get("location")
            if hits(location):
                matches.append({"kind": "slot", "slot_id": slot["id"],
                                "label": slot.get("label") or slot["id"], "location": location})
            if contains(location):
                containing_slots.append(slot["id"])
            for option in slot.get("options", []):
                location = option.get("location")
                if hits(location):
                    matches.append({"kind": "option", "slot_id": slot["id"],
                                    "option_id": option["id"],
                                    "label": option.get("label") or option["id"],
                                    "location": location})
                if contains(location):
                    containing_options.append((slot["id"], option["id"]))
        slot_id = containing_slots[0] if len(containing_slots) == 1 else None
        option_id = (containing_options[0][1] if len(containing_options) == 1
                     and containing_options[0][0] == slot_id else None)
        context = {"slot_id": slot_id, "option_id": option_id}
        return {"matches": matches,
                "context": {**context,
                            "reason": ("" if slot_id else "선택한 위치가 교체 묶음 안에 없습니다.")},
                "commands": self._commands(session, selection, context)}

    def _do_case_upsert(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        case = {
            "name": p.get("name"),
            "values": p.get("values", session.values),
            "selected": p.get("selected", session.selected),
            "schema": self._schema_key(session.analysis),
        }
        self._validate_cases([case])
        session.cases = [c for c in session.cases if c["name"] != case["name"]] + [case]
        session.cases_dirty = True
        if case["values"] == session.values and case["selected"] == session.selected:
            session.trial_inputs_dirty = False
        return {"ok": True, "case": case}

    def _do_case_remove(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        before = len(session.cases)
        session.cases = [case for case in session.cases if case["name"] != p.get("name")]
        if len(session.cases) == before:
            raise ValueError("시험 케이스를 찾을 수 없습니다.")
        session.cases_dirty = True
        session.trial_inputs_dirty = bool(session.values or session.selected) and not any(
            case["values"] == session.values and case["selected"] == session.selected
            for case in session.cases
        )
        return {"ok": True}

    def _do_save_cases(self, p: dict) -> dict:
        session = self._session(p)
        if not session.save_path:
            return {"needs_document_save": True}
        if session.cases_error:
            return {"needs_case_repair": True, "message": session.cases_error}
        if session.trial_inputs_dirty:
            return {"needs_case_name": True}
        self.store.write_cases(self.store.key(Path(session.save_path)), session.cases)
        session.cases_dirty = False
        return {"ok": True}

    def _do_save(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        if not session.save_path:
            return {"needs_path": True, "needs_save_as": True}
        return self.save_to_path(session.id, session.revision, session.save_path)

    def _do_check_external(self, p: dict) -> dict:
        session = self._session(p)
        path = session.save_path or session.source_path
        expected = session.baseline if session.save_path else session.source_baseline
        actual = self.store.current_fingerprint(Path(path)) if path else None
        session.external_changed = bool(path and actual != expected)
        return {"changed": session.external_changed, "fingerprint": actual}

    def _do_external_content(self, p: dict) -> dict:
        session = self._session(p)
        path = session.save_path or session.source_path
        if not path:
            raise ValueError("원본 파일이 없습니다.")
        content, fingerprint = self.store.read_document(Path(path))
        result: dict[str, object] = {
            "content": self._wire(session.media, content),
            "fingerprint": fingerprint,
        }
        if session.media == "hwpx":
            result["section_entries"] = self._section_entries(content)
        return result

    def _do_reload(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        path = session.save_path or session.source_path
        if not path:
            raise ValueError("다시 열 파일이 없습니다.")
        if (session.dirty or session.recovery) and p.get("force") is not True:
            return {"needs_confirm": True, "document_dirty": session.dirty,
                    "recovery": session.recovery}
        content, baseline = self.store.read_document(Path(path))
        analysis = self._analyze(session.media, content)
        session.content = content
        session.saved_content = content
        if session.save_path:
            session.baseline = baseline
        else:
            session.source_baseline = baseline
        session.analysis = analysis
        session.saved_analysis = analysis
        session.identifier_changes = []
        session.last_preview = None
        session.revision += 1
        session.recovery = False
        session.recovery_saved_at = ""
        session.rhwp_editable = None
        session.rhwp_diagnostics = []
        session.external_changed = False
        self.store.discard_draft(session.draft_key)
        self._refresh_recoverable()
        return self._contents(session)

    def _do_recover(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        draft = self.store.read_draft(session.draft_key)
        if draft is None:
            raise ValueError("복구 초안이 없습니다.")
        if draft["media"] != session.media:
            raise ValueError("복구 초안의 형식이 다릅니다.")
        analysis = self._analyze(session.media, draft["content"])
        session.replace_content(draft["content"], analysis)
        session.baseline = draft["baseline"]
        session.source_baseline = draft.get("source_baseline")
        session.external_changed = bool(
            (session.save_path or session.source_path)
            and self.store.current_fingerprint(Path(session.save_path or session.source_path))
            != (session.baseline if session.save_path else session.source_baseline)
        )
        session.recovery = False
        session.recovery_saved_at = next((item.get("updated_at", "") for item in self._recoverable
                                          if item["key"] == session.draft_key), "")
        session.rhwp_editable = None
        session.rhwp_diagnostics = []
        return self._contents(session)

    def _do_recover_draft(self, p: dict) -> dict:
        key = p.get("key")
        if not isinstance(key, str) or key not in {item["key"] for item in self._recoverable}:
            raise ValueError("복구 초안을 찾을 수 없습니다.")
        draft = self.store.read_draft(key)
        assert draft is not None
        path = draft["path"]
        if path and Path(path).is_file():
            result = self.open_path(path, as_template=draft["baseline"] is not None)
            return self._do_recover({"session_id": result["session_id"], "revision": result["revision"]})
        media = draft["media"]
        content = draft["content"]
        session = AuthoringSession(
            id=uuid4().hex, media=media, content=content,
            source_path=path, saved_content=b"", analysis=self._analyze(media, content),
            draft_key=key,
            recovery_saved_at=next((item.get("updated_at", "") for item in self._recoverable
                                    if item["key"] == key), ""),
        )
        self.sessions[session.id] = session
        self.active_id = session.id
        return self._contents(session)

    def _do_recovery_content(self, p: dict) -> dict:
        key = p.get("key")
        if not isinstance(key, str) or key not in {item["key"] for item in self._recoverable}:
            raise ValueError("복구 초안을 찾을 수 없습니다.")
        draft = self.store.read_draft(key)
        if draft is None:
            raise ValueError("복구 초안을 찾을 수 없습니다.")
        media = draft["media"]
        content = draft["content"]
        result: dict[str, object] = {
            "key": key,
            "media": media,
            "content": self._wire(media, content),
            "path": draft["path"],
            "original_content": None,
            "external_changed": False,
        }
        if media == "hwpx":
            result["section_entries"] = self._section_entries(content)
        path = Path(draft["path"])
        if draft["path"] and self.store.key(path) != key:
            raise ValueError("복구 초안의 원본 경로가 일치하지 않습니다.")
        if draft["path"] and path.is_file():
            original, fingerprint = self.store.read_document(path)
            if self._media(path) != media:
                raise ValueError("복구 초안과 원본의 형식이 다릅니다.")
            result["original_content"] = self._wire(media, original)
            expected = draft["baseline"] if draft["baseline"] is not None else draft.get("source_baseline")
            result["external_changed"] = fingerprint != expected
            if media == "hwpx":
                result["original_section_entries"] = self._section_entries(original)
        return result

    def _do_discard_recovery(self, p: dict) -> dict:
        session = self._session(p)
        if not session.recovery:
            raise ValueError("적용 전 복구 초안이 없습니다.")
        self.store.discard_draft(session.draft_key)
        self._refresh_recoverable()
        session.recovery = False
        session.recovery_saved_at = ""
        return {"ok": True}

    def _do_discard_draft(self, p: dict) -> dict:
        key = p.get("key")
        if not isinstance(key, str) or key not in {item["key"] for item in self._recoverable}:
            raise ValueError("복구 초안을 찾을 수 없습니다.")
        if any(session.draft_key == key and session.dirty for session in self.sessions.values()):
            raise ValueError("편집 중인 문서의 복구 초안은 폐기할 수 없습니다.")
        self.store.discard_draft(key)
        self._refresh_recoverable()
        for session in self.sessions.values():
            if session.draft_key == key:
                session.recovery = False
                session.recovery_saved_at = ""
        return {"ok": True}

    def _do_close(self, p: dict) -> dict:
        session = self._session(p)
        cases_dirty = session.cases_dirty or session.trial_inputs_dirty
        if (session.dirty or cases_dirty) and p.get("force") is not True:
            return {"needs_confirm": True, "document_dirty": session.dirty,
                    "dirty": session.dirty, "cases_dirty": cases_dirty,
                    "trial_inputs_dirty": session.trial_inputs_dirty}
        if p.get("force") is True and not session.recovery:
            self.store.discard_draft(session.draft_key)
            self._refresh_recoverable()
        del self.sessions[session.id]
        if self.active_id == session.id:
            self.active_id = next(reversed(self.sessions), "")
        return {"ok": True}

    def _linked_jobs(self, session: AuthoringSession) -> tuple[list, list]:
        if self._job_registry is None or not session.save_path:
            return [], []
        target = os.path.normcase(os.path.abspath(session.save_path))
        corrupted: list = []
        jobs = [
            job for job in self._job_registry.list_jobs(corrupted=corrupted)
            if job.template_path
            and os.path.normcase(os.path.abspath(job.template_path)) == target
        ]
        return jobs, corrupted

    def _saved_for_jobs(self, session: AuthoringSession) -> None:
        if not session.save_path or session.dirty:
            raise ValueError(_SAVE_FIRST)
        if self.store.current_fingerprint(Path(session.save_path)) != session.baseline:
            session.external_changed = True
            raise ValueError(_EXTERNAL_CHANGED)

    def _blocked_reason(self, session: AuthoringSession) -> str | None:
        """Why the saved file cannot be handed to existing jobs yet (U11); None when usable."""
        readiness = self._readiness(session)
        if readiness["state"] != "ready":
            return readiness["message"]
        if not session.save_path or session.dirty:
            return _SAVE_FIRST
        if session.external_changed:
            return _EXTERNAL_CHANGED
        return None

    def _do_impact(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        if self._job_registry is None or self._template_change is None:
            return {"available": False, "reason": "작업 연결을 확인할 수 없습니다.", "jobs": []}
        jobs, corrupted = self._linked_jobs(session)
        current_fields = {field["name"] for field in session.analysis.get("fields", [])}
        blocked_reason = self._blocked_reason(session)
        current_slots = {slot["id"] for slot in session.analysis.get("slots", [])}
        current_options = {(slot["id"], option["id"]) for slot in session.analysis.get("slots", [])
                           for option in slot.get("options", [])}
        # 되돌려진 이름 변경(옛 식별자가 다시 있음)은 더는 영향이 아니다.
        identifier_changes = [
            change for change in session.identifier_changes
            if (change["from"] not in current_slots if change["kind"] == "slot"
                else (change.get("slot_id"), change["from"]) not in current_options)
        ]
        jobs_view = []
        for job in jobs:
            change = self._template_change.zone(job.name, job.media, not Path(job.template_path).is_file())
            preparation = change.get("preparation") or {}
            jobs_view.append({
                "name": job.name,
                "added_fields": sorted(current_fields - set(job.template_fields())),
                "unmapped_fields": sorted(set(job.template_fields()) - current_fields),
                "removed_fields": sorted(set(job.template_fields()) - current_fields),
                "change": change,
                "change_status": (str(preparation["status"]) if preparation.get("status") is not None
                                  else None),
                "blocked_reason": blocked_reason,
            })
        return {
            "available": True,
            "save_required": session.dirty or not session.save_path,
            "usable": blocked_reason is None,
            "content_changed_since_save": session.dirty,
            "structure_delta": self._structure_delta(session.saved_analysis, session.analysis,
                                                     identifier_changes),
            "identifier_changes": identifier_changes,
            "unverified_jobs": len(corrupted),
            "jobs": jobs_view,
        }

    def _linked_job(self, session: AuthoringSession, name: object):
        if not isinstance(name, str) or not name:
            raise ValueError("적용할 작업 이름이 없습니다.")
        jobs, _corrupted = self._linked_jobs(session)
        job = next((job for job in jobs if job.name == name), None)
        if job is None:
            raise ValueError("이 문서를 사용하는 작업을 찾을 수 없습니다.")
        return job

    def _do_prepare_apply(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        if self._template_change is None:
            raise ValueError("작업 변경 확인이 연결되지 않았습니다.")
        self._saved_for_jobs(session)
        job = self._linked_job(session, p.get("job_name"))
        result = self._template_change.check(job.name, uuid4().hex)
        preparation = result.get("preparation") or {}
        return {"job_name": job.name, **result,
                "change_token": preparation.get("change_token")}

    def _do_apply_job(self, p: dict) -> dict:
        session = self._session(p, revision=True)
        if self._template_change is None:
            raise ValueError("작업 변경 적용이 연결되지 않았습니다.")
        self._saved_for_jobs(session)
        job = self._linked_job(session, p.get("job_name"))
        token = p.get("change_token")
        if not isinstance(token, str) or not token:
            raise ValueError("변경 확인 토큰이 없습니다.")
        return {"job_name": job.name, **self._template_change.apply(job.name, token)}
