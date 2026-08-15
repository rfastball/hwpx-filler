"""템플릿 변경 확인·적용 코디네이터 — S3 권위를 opaque Product Contract 로 잇는 첫 브리지 (S3-09 #659).

사용자 능력은 「[변경사항 확인] → 준비 상태·진단 → [변경사항 적용]」 둘뿐이다. revision
목록·선택기는 없고, 외부로 나가는 것은 opaque token 과 제품 status 뿐이다(내부 ID·경로·
base·generation 비노출). 판정·상태 전이는 전부 S3-04~08 의 runner 가 소유하고, 여기는:

- **이름→work_id 인덱스**: work aggregate 는 ``_SAFE_ID`` 키라 한글 작업 이름을 직접 못 쓴다.
  works 루트의 인덱스 파일 하나가 이름→불투명 work_id 를 소유하고, 작업 개명은 유일 호출지
  (:meth:`~hwpxfiller.webapp.screen_job.JobController._do_rename_job`)가 :meth:`on_job_renamed`
  로 인덱스를 따라 옮긴다 — aggregate 내부 work_id 는 이름과 무관해 개명에 불변.
- **lazy bootstrap**: 첫 확인 시 현재 bytes 를 epoch 1 INITIALIZATION 으로 세운다. legacy 실행은
  source 파일을 직접 읽으므로 「지금 파일」이 곧 현재 권위라는 기재는 정직하다(실행 배선은
  S4 — 이 슬라이스는 기존 실행·편집 권위를 바꾸지 않는다).
- **동기 실행**: capture·qualification 은 로컬 zip 읽기+검사라 dispatch 스레드에서 끝까지 돌고
  종결 상태 하나를 돌려준다(중단 crash 는 다음 접근의 :func:`recover_session` 이 INTERRUPTED 로
  닫는다).
- **opaque token**: ``secrets.token_urlsafe`` 인메모리 map. token 은 권한이 아니다 — 각 요청이
  actor·Work 접근·Work 소속을 별도 확인하고, cross-Work misuse 는 두 Work 무변경으로 거절한다.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..application.candidate_revision import MutableSourceBinding, TemplateLineage
from ..application.jobs import JobStorePort, load_job
from ..application.prepare_orchestration import (
    APPLY_INTEGRITY_ERROR,
    find_application,
    find_change,
)
from ..application.prepare_template_change import PreparePins
from ..application.template_change_product import (
    CAPABILITY_INITIALIZATION_REQUIRED,
    CAPABILITY_UNSUPPORTED_MEDIA,
    preparation_view,
    product_apply_status,
)
from ..application.work_bootstrap import BOOTSTRAP_OK, BootstrapOutcome
from ..application.work_template_state import (
    DocumentWork,
    PREP_CAPTURING,
    PREP_QUALIFYING,
    TemplateChangePreparation,
    WorkTemplateStateAggregate,
)
from ..external.candidate_store import CandidateObjectStore
from ..external.prepare_orchestration_runner import (
    admit_preparation,
    apply_prepared_change,
    bootstrap_work,
    recover_session,
    run_capture_stage,
    run_qualification_stage,
)
from ..external.qualification_store import ObjectNotFound, QualificationObjectStore
from ..external.template_inspection import (
    HWPX_QUALIFICATION_PROFILE,
    hwpx_qualification_manifest,
)
from ..external.template_source_reader import FileTemplateSourceReader
from ..external.work_template_store import (
    AtomicWorkTemplateStateStore,
    start_prepare,
)

#: 단일 사용자 데스크톱 앱의 로컬 세션 actor. 권위 기록(Application·Provenance)에 남는다.
LOCAL_ACTOR = "local-user"

#: 요청 키(사용자 prepare intent 재전송 단위) 서식 — store id 파생에 쓰이므로 fail-closed 검증.
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

_ENGINE_METADATA = {"engine": "hwpxfiller"}


class TemplateChangeError(ValueError):
    """제품 계약 위반·권한 실패·무결성 오류 — 정상 domain status 와 분리된 시끄러운 실패."""


def unsupported_zone() -> dict[str, Any]:
    """HWPX 가 아니거나 템플릿 미연결·작업 미선택 — capability 비노출(명시적 unsupported)."""
    return {
        "supported": False,
        "reason": CAPABILITY_UNSUPPORTED_MEDIA,
        "checkable": False,
        "diagnostics": [],
        "epoch": None,
        "preparation": None,
    }


def _authorize(work: DocumentWork, actor: str) -> None:
    """actor 의 Work 접근·Template 변경 권한 — token 과 독립으로 매 요청 확인한다."""
    if actor != LOCAL_ACTOR:
        raise TemplateChangeError(f"actor {actor!r} 는 이 Work 에 접근할 수 없습니다")


class TemplateChangeCoordinator:
    """job 화면이 소비하는 prepare/apply/query 서비스 — webview 비의존, 헤드리스 구동."""

    def __init__(
        self,
        registry: JobStorePort,
        *,
        root: Path,
        clock: Callable[[], datetime],
    ) -> None:
        self._registry = registry
        self._root = Path(root)
        self._works = AtomicWorkTemplateStateStore(self._root / "works")
        self._candidates = CandidateObjectStore(self._root / "candidates")
        self._quals = QualificationObjectStore(self._root / "qualification")
        self._clock = clock
        self._index_path = self._root / "work_index.json"
        #: process 세션 identity — 이전 세션의 미완 Preparation 을 INTERRUPTED 로 닫는 기준.
        self._session_id = "s-" + uuid.uuid4().hex
        self._recovered: set[str] = set()
        #: bootstrap 실패 기록(메모리) — 같은 template 판본 동안 확인 버튼을 사유와 함께 비활성.
        self._init_failures: dict[str, dict[str, Any]] = {}
        # token ↔ 내부 id 양방향 map(세션 로컬 — 재시작 후 current 조회가 새 token 을 발급한다).
        self._prep_token_by_id: dict[tuple[str, str], str] = {}
        self._change_token_by_id: dict[tuple[str, str], str] = {}
        self._change_id_by_token: dict[str, tuple[str, str]] = {}
        self._lock = threading.RLock()
        self._manifest_seeded = False

    # ─── 시각·인덱스 ────────────────────────────────────────────────────────

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    def _load_index(self) -> dict[str, str]:
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        return dict(raw.get("by_name", {}))

    def _save_index(self, index: dict[str, str]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self._index_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"by_name": index}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        os.replace(tmp, self._index_path)

    def _work_id_for(self, job_name: str, *, create: bool) -> "str | None":
        """이름→work_id. ``create=True`` 면 **bootstrap 전에** 발급·영속한다(index-first —
        중간 crash 시 다음 시도가 같은 id 로 재개하고, 반대 순서는 orphan aggregate 를 남긴다)."""
        with self._lock:
            index = self._load_index()
            work_id = index.get(job_name)
            if work_id is None and create:
                work_id = "w-" + uuid.uuid4().hex
                index[job_name] = work_id
                self._save_index(index)
            return work_id

    def on_job_renamed(self, old_name: str, new_name: str) -> None:
        """작업 개명을 인덱스가 따라간다 — aggregate 는 불변(내부 work_id 가 이름과 무관)."""
        with self._lock:
            index = self._load_index()
            work_id = index.pop(old_name, None)
            if work_id is not None:
                index[new_name] = work_id
                self._save_index(index)

    # ─── 공통 재료 ──────────────────────────────────────────────────────────

    def _ensure_manifest(self) -> None:
        if self._manifest_seeded:
            return
        try:
            self._quals.get_manifest(HWPX_QUALIFICATION_PROFILE.id)
        except ObjectNotFound:
            self._quals.put_manifest(hwpx_qualification_manifest(self._now()))
        self._manifest_seeded = True

    def _binding(self, work_id: str, job) -> MutableSourceBinding:
        return MutableSourceBinding(
            source_binding_id=f"{work_id}.binding",
            media="hwpx",
            host_reference=job.template_path,
            display_metadata={},
            generation=job.binding_revision,
        )

    def _lineage(self, work_id: str, binding: MutableSourceBinding) -> TemplateLineage:
        return TemplateLineage(
            template_lineage_id=f"{work_id}.lineage",
            media="hwpx",
            mutable_source_binding_id=binding.source_binding_id,
            source_binding_generation=binding.generation,
            updated_at=self._now(),
        )

    def _reader(self, job_name: str) -> FileTemplateSourceReader:
        def probe(_binding_id: str) -> int:
            return load_job(self._registry, job_name).binding_revision

        return FileTemplateSourceReader(probe)

    def _recover(self, work_id: str) -> None:
        if work_id in self._recovered or not self._works.exists(work_id):
            return
        recover_session(
            self._works, self._quals,
            work_id=work_id, current_session_id=self._session_id, completed_at=self._now(),
        )
        self._recovered.add(work_id)

    # ─── token ──────────────────────────────────────────────────────────────

    def _mint_prep_token(self, work_id: str, preparation_id: str) -> str:
        with self._lock:
            key = (work_id, preparation_id)
            token = self._prep_token_by_id.get(key)
            if token is None:
                token = secrets.token_urlsafe(16)
                self._prep_token_by_id[key] = token
            return token

    def _mint_change_token(self, work_id: str, change_id: str) -> str:
        with self._lock:
            key = (work_id, change_id)
            token = self._change_token_by_id.get(key)
            if token is None:
                token = secrets.token_urlsafe(16)
                self._change_token_by_id[key] = token
                self._change_id_by_token[token] = key
            return token

    # ─── 조회(스냅샷 존) ────────────────────────────────────────────────────

    def zone(self, job_name: str, media: str, template_missing: bool) -> dict[str, Any]:
        """job 스냅샷의 ``template_change`` 존 — capability·현재 Preparation·epoch."""
        if media != "hwpx" or template_missing:
            return unsupported_zone()
        work_id = self._work_id_for(job_name, create=False)
        failure = self._init_failures.get(work_id or "")
        if failure is not None:
            job = load_job(self._registry, job_name)
            if self._template_signature(job.template_path) == failure["signature"]:
                # 같은 template 실물이 그대로다 — 확인 버튼 비활성 + 사유 병기(#659 회귀,
                # S3-08 「repair 전 prepare/apply 비활성」). 실물이 바뀌면(한글에서 수정·
                # 재연결) 아래에서 기록을 지워 재확인이 열린다.
                return {
                    "supported": True,
                    "reason": CAPABILITY_INITIALIZATION_REQUIRED,
                    "checkable": False,
                    "diagnostics": failure["diagnostics"],
                    "epoch": None,
                    "preparation": None,
                }
            del self._init_failures[work_id or ""]
        base = {
            "supported": True,
            "reason": "",
            "checkable": True,
            "diagnostics": [],
            "epoch": None,
            "preparation": None,
        }
        if work_id is None or not self._works.exists(work_id):
            return base
        self._recover(work_id)
        aggregate = self._works.load(work_id)
        base["epoch"] = find_application(
            aggregate, aggregate.work.current_template_application_id
        ).application_epoch
        base["preparation"] = self._current_preparation_view(aggregate, work_id)
        return base

    def get_current_template_change_preparation(self, job_name: str) -> "dict[str, Any] | None":
        """current Preparation 조회 — ``work.current_template_preparation_id`` 역참조만 쓴다
        (latest 검색·ORDER BY 금지 계약 #659)."""
        work_id = self._work_id_for(job_name, create=False)
        if work_id is None or not self._works.exists(work_id):
            return None
        self._recover(work_id)
        return self._current_preparation_view(self._works.load(work_id), work_id)

    def _current_preparation_view(
        self, aggregate: WorkTemplateStateAggregate, work_id: str
    ) -> "dict[str, Any] | None":
        prep_id = aggregate.work.current_template_preparation_id
        if prep_id is None:
            return None
        prep = next(
            p for p in aggregate.preparations if p.preparation_id == prep_id
        )
        return self._view(aggregate, work_id, prep)

    def _view(
        self,
        aggregate: WorkTemplateStateAggregate,
        work_id: str,
        prep: TemplateChangePreparation,
    ) -> dict[str, Any]:
        change_status = None
        change_token = None
        if prep.prepared_change_id is not None:
            change = find_change(aggregate, prep.prepared_change_id)
            change_status = change.status
            change_token = self._mint_change_token(work_id, change.prepared_change_id)
        return preparation_view(
            prep,
            change_status,
            preparation_token=self._mint_prep_token(work_id, prep.preparation_id),
            change_token=change_token,
            diagnostics=self._diagnostics(prep),
        )

    def _diagnostics(self, prep: TemplateChangePreparation) -> tuple[tuple[str, str], ...]:
        """capture 실패 사유(Preparation)·FAIL 진단(Evidence)을 (kind, message) 로 정규화.

        Evidence.diagnostics 는 계약상 mapping({"kind","message"})이다 — S2 codec 이 그렇게
        직렬화한다(:mod:`~hwpxfiller.application.qualification_evidence`).
        """
        found = [(str(d.get("reason", "")), "") for d in prep.diagnostics]
        if prep.evidence_id is not None:
            try:
                evidence = self._quals.get_evidence(prep.evidence_id)
            except ObjectNotFound:
                evidence = None
            if evidence is not None:
                found.extend(
                    (str(d.get("kind", "")), str(d.get("message", "")))
                    for d in evidence.diagnostics
                )
        return tuple(found)

    # ─── prepare ────────────────────────────────────────────────────────────

    def check(self, job_name: str, prepare_request_id: str, actor: str = LOCAL_ACTOR) -> dict:
        """[변경사항 확인] — bootstrap(최초)·capture·qualification·admission 을 동기로 완주한다.

        반환은 ``{"ok": True, "preparation": view}`` 또는 초기 등록 실패의
        ``{"ok": False, "reason": "initialization_required"}`` — 후자는 오류가 아니라 정상
        결과라 raise 하지 않는다(진단·비활성 사유는 스냅샷 존이 병기한다).
        """
        if not _REQUEST_ID.fullmatch(prepare_request_id or ""):
            raise TemplateChangeError(f"잘못된 확인 요청 키 {prepare_request_id!r}")
        job = load_job(self._registry, job_name)  # 없으면 loud(포트가 raise)
        if job.media != "hwpx":
            raise TemplateChangeError("HWPX 작업이 아니라 변경사항 확인을 지원하지 않습니다")
        self._ensure_manifest()
        work_id = self._work_id_for(job_name, create=True)
        assert work_id is not None
        self._recover(work_id)

        if not self._works.exists(work_id):
            outcome = self._bootstrap(work_id, job_name, job, prepare_request_id)
            if outcome.result != BOOTSTRAP_OK:
                return {"ok": False, "reason": CAPABILITY_INITIALIZATION_REQUIRED}

        binding = self._binding(work_id, job)
        prep = start_prepare(
            self._works,
            work_id=work_id,
            prepare_request_id=prepare_request_id,
            actor=actor,
            resolve_pins=lambda _work: PreparePins(
                binding.source_binding_id, binding.generation, HWPX_QUALIFICATION_PROFILE.id
            ),
            preparation_id=f"p-{prepare_request_id}",
            execution_session_id=self._session_id,
            started_at=self._now(),
            authorize=_authorize,
        )
        prep = self._advance(work_id, job_name, prep)
        return {"ok": True, "preparation": self._view(self._works.load(work_id), work_id, prep)}

    def _advance(
        self, work_id: str, job_name: str, prep: TemplateChangePreparation
    ) -> TemplateChangePreparation:
        """CAPTURING→QUALIFYING→admission 을 순서대로 전진 — 각 stage 는 멱등 short-circuit."""
        job = load_job(self._registry, job_name)
        if prep.status == PREP_CAPTURING:
            # pin 된 generation 으로 capture 한다(현재 job 값이 아니라) — pin 불일치는
            # runner 의 신뢰 경계가 SOURCE_BINDING_CHANGED 로 판정할 몫이다.
            pinned = MutableSourceBinding(
                source_binding_id=prep.source_binding_id,
                media="hwpx",
                host_reference=job.template_path,
                display_metadata={},
                generation=prep.source_binding_generation,
            )
            prep = run_capture_stage(
                self._works, self._candidates,
                work_id=work_id, preparation_id=prep.preparation_id,
                lineage=self._lineage(work_id, pinned), binding=pinned,
                reader=self._reader(job_name),
                resolve_current_generation=lambda _w: load_job(
                    self._registry, job_name
                ).binding_revision,
                captured_at=self._now(), created_at=self._now(),
            )
        if prep.status == PREP_QUALIFYING:
            prep = run_qualification_stage(
                self._works, self._candidates, self._quals,
                work_id=work_id, preparation_id=prep.preparation_id,
                profile=HWPX_QUALIFICATION_PROFILE, engine_metadata=dict(_ENGINE_METADATA),
                started_at=self._now(), completed_at=self._now(), qualified_at=self._now(),
            )
        if prep.status == PREP_QUALIFYING and prep.attempt_id is not None:
            # PASS checkpoint 는 QUALIFYING 을 유지한다 — READY 승격/terminal 은 admission 몫.
            admit_preparation(
                self._works, self._candidates, self._quals,
                work_id=work_id, preparation_id=prep.preparation_id,
                resolve_current_binding=lambda _w: (
                    f"{work_id}.binding",
                    load_job(self._registry, job_name).binding_revision,
                ),
                prepared_change_id=f"{prep.preparation_id}-chg", prepared_at=self._now(),
            )
            prep = next(
                p
                for p in self._works.load(work_id).preparations
                if p.preparation_id == prep.preparation_id
            )
        return prep

    def _bootstrap(
        self, work_id: str, job_name: str, job, request_id: str
    ) -> BootstrapOutcome:
        binding = self._binding(work_id, job)
        boot_id = f"boot-{request_id}"
        ids = {
            "observation_id": f"{work_id}.{boot_id}.obs",
            "revision_id": f"{work_id}.{boot_id}.rev",
            "attempt_id": f"{work_id}.{boot_id}.att",
            "evidence_id": f"{work_id}.{boot_id}.ev",
            "application_id": f"{work_id}.{boot_id}.app",
        }
        outcome = bootstrap_work(
            self._works, self._candidates, self._quals,
            work_id=work_id, bootstrap_request_id=boot_id,
            lineage=self._lineage(work_id, binding), binding=binding,
            reader=self._reader(job_name), profile=HWPX_QUALIFICATION_PROFILE,
            legacy_template_revision=job.template_revision,
            legacy_binding_revision=job.binding_revision,
            legacy_source_reference=job.template_path,
            engine_metadata=dict(_ENGINE_METADATA), actor=LOCAL_ACTOR,
            captured_at=self._now(), created_at=self._now(), started_at=self._now(),
            completed_at=self._now(), qualified_at=self._now(),
            **ids,
        )
        if outcome.result != BOOTSTRAP_OK:
            diagnostics = [(str(outcome.reason or ""), "")]
            try:
                evidence = self._quals.get_evidence(ids["evidence_id"])
                diagnostics.extend(
                    (str(d.get("kind", "")), str(d.get("message", "")))
                    for d in evidence.diagnostics
                )
            except ObjectNotFound:
                pass
            self._init_failures[work_id] = {
                # repair 판정은 **파일 실물 서명**이다 — job revision 은 한글에서 바이트만
                # 고친 수정(레지스트리 무접촉)에 안 오르므로 그걸 키로 쓰면 정당한 수리
                # 뒤에도 확인이 영영 닫힌다.
                "signature": self._template_signature(job.template_path),
                "diagnostics": [
                    {"kind": kind, "message": message} for kind, message in diagnostics
                ],
            }
        else:
            self._init_failures.pop(work_id, None)
        return outcome

    @staticmethod
    def _template_signature(template_path: str) -> "tuple | None":
        """template 실물의 변경 감지 서명 — 부재는 None(그 자체가 한 상태)."""
        try:
            stat = os.stat(template_path)
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    # ─── apply ──────────────────────────────────────────────────────────────

    def apply(self, job_name: str, change_token: str, actor: str = LOCAL_ACTOR) -> dict:
        """[변경사항 적용] — token 해석·독립 권한 확인·cross-Work 거절 뒤 원자 apply."""
        resolved = self._change_id_by_token.get(str(change_token or ""))
        if resolved is None:
            raise TemplateChangeError("적용 대상이 유효하지 않습니다 — 변경사항을 다시 확인하세요")
        token_work_id, change_id = resolved
        work_id = self._work_id_for(job_name, create=False)
        if work_id is None or work_id != token_work_id:
            # cross-Work misuse: request 거절, 두 Work·Change 상태 무변경.
            raise TemplateChangeError("이 변경사항은 현재 작업의 것이 아닙니다")
        outcome = apply_prepared_change(
            self._works, self._candidates, self._quals,
            work_id=work_id, change_id=change_id, actor=actor, authorize=_authorize,
            new_application_id=f"{change_id}-app", provenance_id=f"{change_id}-prov",
            outbox_event_id=f"{change_id}-evt", applied_at=self._now(),
        )
        if outcome.result == APPLY_INTEGRITY_ERROR:
            raise TemplateChangeError(
                "적용 무결성 확인에 실패했습니다 — 저장된 확인 결과를 신뢰할 수 없습니다"
            )
        aggregate = self._works.load(work_id)
        current = find_application(
            aggregate, aggregate.work.current_template_application_id
        )
        return {
            "status": product_apply_status(outcome.result),
            "current_template_application_epoch": current.application_epoch,
            "is_current": outcome.resulting_application_id
            == aggregate.work.current_template_application_id,
        }
