"""템플릿 변경 확인·적용 코디네이터 — S3 권위를 opaque Product Contract 로 잇는 첫 브리지 (S3-09 #659).

사용자 능력은 「[변경사항 확인] → 준비 상태·진단 → [변경사항 적용]」 둘뿐이다. revision
목록·선택기는 없고, 외부로 나가는 것은 opaque token 과 제품 status 뿐이다(내부 ID·경로·
base·generation 비노출). 판정·상태 전이는 전부 S3-04~08 의 runner 가 소유하고, 여기는:

- **Work identity = Job durable 필드**(``Job.authority_id``): 이름은 identity 가 아니다 —
  개명되고, 삭제 후 같은 이름이 **다른 작업**으로 재사용된다(이름을 키로 쓰면 재활용된
  이름이 남의 권위 이력·token 을 물려받는다 — 리뷰 P1). 첫 확인이 불투명 id 를 발급해
  작업 실체에 결속하므로 개명·보존 삭제 복원에 생존하고 재활용 이름은 새 Work 다.
  발급이 bootstrap 보다 **먼저** durable 하다(id-first — 중간 crash 시 같은 id 로 재개).
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.job import Job
from ..application.candidate_revision import (
    MutableSourceBinding,
    TemplateLineage,
    blob_digest,
)
from ..application.slot_configuration_context import (
    SlotConfigurationContextError,
    resolve_exact_applied_template_input,
)
from ..application.jobs import JobStorePort, ensure_job_authority_id, load_job
from ..application.prepare_orchestration import (
    APPLY_INTEGRITY_ERROR,
    find_application,
    find_change,
)
from ..application.prepare_template_change import PreparePins
from ..application.template_qualification import QualificationProfile
from ..application.template_change_product import (
    CAPABILITY_INITIALIZATION_REQUIRED,
    CAPABILITY_UNSUPPORTED_MEDIA,
    preparation_view,
    product_apply_status,
)
from ..application.work_bootstrap import (
    BOOTSTRAP_OK,
    TEMPLATE_INITIALIZATION_REQUIRED,
    BootstrapOutcome,
)
from ..application.slot_selection_input import SlotSelectionCaptureError
from ..application.slotless_run_bridge import (
    SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE,
    SlotlessRunAdmissionError,
)
from ..application.work_template_state import (
    INITIALIZATION,
    DocumentWork,
    PREP_CAPTURING,
    PREP_QUALIFYING,
    TemplateChangePreparation,
    WorkTemplateStateAggregate,
)
from ..external.candidate_store import CandidateObjectStore
from ..external.slot_command_runner import admit_managed_slotless_run
from ..external.work_configuration_store import (
    WorkSlotConfigurationStore,
    WorkspaceMetadataStore,
)
from ..external.work_template_store import WorkAggregateNotFound
from ..external.prepare_orchestration_runner import (
    admit_preparation,
    apply_prepared_change,
    bootstrap_work,
    recover_session,
    run_capture_stage,
    run_qualification_stage,
)
from ..external.qualification_store import ObjectNotFound, QualificationObjectStore
from ..host.staged_template import clear_run_staging
from ..external.template_inspection import (
    HWPX_QUALIFICATION_PROFILE,
    hwpx_qualification_manifest,
)
from ..external.text_template_inspection import (
    TXT_QUALIFICATION_PROFILE,
    txt_qualification_manifest,
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


#: 매체 → (qualification profile, durable manifest 팩토리). **지원 매체의 단일 출처**다
#: (S10-02 #859). 사건 경계·상태 전이는 매체를 모르는 S2/S3 기계가 그대로 지고, 매체가
#: 가르는 것은 「그 bytes 를 무엇으로 자격 심사하는가」 하나뿐이다 — 그래서 이 표만 늘고
#: 아래 게이트들은 전부 이 표의 키 집합을 묻는다. 미등록 매체는 조용한 추측 없이 거절된다
#: (:func:`unsupported_zone` · :class:`TemplateChangeError`).
_MEDIA_QUALIFICATION: "dict[str, tuple[QualificationProfile, Callable[[str], Any]]]" = {
    "hwpx": (HWPX_QUALIFICATION_PROFILE, hwpx_qualification_manifest),
    "txt": (TXT_QUALIFICATION_PROFILE, txt_qualification_manifest),
}

#: 「변경사항 확인/적용」이 서는 매체 집합 — 표면·테스트가 문자열을 재조립하지 않게 한다.
SUPPORTED_MEDIA = frozenset(_MEDIA_QUALIFICATION)


def _profile_for(media: str, what: str) -> QualificationProfile:
    """매체의 qualification profile — 미지원 매체는 시끄럽게 거절(fail-closed)."""
    entry = _MEDIA_QUALIFICATION.get(media)
    if entry is None:
        raise TemplateChangeError(
            f"지원하지 않는 템플릿 형식이라 {what}을(를) 지원하지 않습니다"
            f"(형식={media or '미상'})"
        )
    return entry[0]


@dataclass(frozen=True)
class _AdvanceResult:
    preparation: TemplateChangePreparation
    aggregate: WorkTemplateStateAggregate
    final_job_snapshot: Job | None
    current_application_id: str


def unsupported_zone() -> dict[str, Any]:
    """지원 매체가 아니거나 템플릿 미연결·작업 미선택 — capability 비노출(명시적 unsupported)."""
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


class _WorkStateReadPort:
    """``AtomicWorkTemplateStateStore`` → #674 read Port(load()->None on missing)."""

    def __init__(self, store: "AtomicWorkTemplateStateStore") -> None:
        self._store = store

    def load(self, work_id: str) -> "WorkTemplateStateAggregate | None":
        try:
            return self._store.load(work_id)
        except WorkAggregateNotFound:
            return None


class _InitialApplicationProvenance:
    """execution-config base = bootstrap 시 확립된 INITIALIZATION Application.

    Mapping·execution 구성은 bootstrap 시점 Application 에 대고 세워졌고, 그 base 를 다른
    Application 으로 다시 지정하는 review command 는 아직 없다(#681 비범위) — 그러니 지금은
    INITIALIZATION Application 이 정본 base 다. S3 Apply 로 current 가 앞서면 base≠current 라
    guard 가 NEEDS_CONFIGURATION 으로 막는다. 별도 durable 필드는 두지 않는다(초기 Application
    이 이미 그 base 를 영속한다). Work 미부트스트랩 → None(UNKNOWN, 정직).
    """

    def __init__(self, works: "AtomicWorkTemplateStateStore") -> None:
        self._works = works

    def resolve_base_template_application_id(self, work_id: str) -> "str | None":
        if not self._works.exists(work_id):
            return None
        for app in self._works.load(work_id).applications:
            if app.origin == INITIALIZATION:
                return app.application_id
        return None


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
        self._workspace = WorkspaceMetadataStore(self._root)
        self._clock = clock
        #: process 세션 identity — 이전 세션의 미완 Preparation 을 INTERRUPTED 로 닫는 기준.
        self._session_id = "s-" + uuid.uuid4().hex
        self._recovered: set[str] = set()
        #: bootstrap 실패 기록 — **durable**(재시작 뒤에도 같은 실물이면 비활성+사유 유지,
        #: 리뷰 P2). 파일이 정본이고 이 dict 는 lazy 캐시(write-through).
        self._failures_path = self._root / "init_failures.json"
        self._init_failures: "dict[str, dict[str, Any]] | None" = None
        # token ↔ 내부 id 양방향 map(세션 로컬 — 재시작 후 current 조회가 새 token 을 발급한다).
        self._prep_token_by_id: dict[tuple[str, str], str] = {}
        self._change_token_by_id: dict[tuple[str, str], str] = {}
        self._change_id_by_token: dict[str, tuple[str, str]] = {}
        self._lock = threading.RLock()
        self._manifest_seeded = False

    # ─── 시각·인덱스 ────────────────────────────────────────────────────────

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    def _work_id_for(self, job_name: str, *, create: bool) -> "str | None":
        """작업의 Work identity — ``Job.authority_id`` 가 정본. ``create=True`` 면
        **bootstrap 전에** 발급·영속한다(id-first — 중간 crash 시 같은 id 로 재개).
        경합 화해는 저장소 멱등 결속이 진다(먼저 커밋된 id 반환)."""
        current = load_job(self._registry, job_name).authority_id
        if current:
            return current
        if not create:
            return None
        # 발급 형태·결속은 단일 helper(S6-05 · #812) — 형태 재타이핑 금지.
        return ensure_job_authority_id(self._registry, job_name)

    def _failures(self) -> dict[str, dict[str, Any]]:
        if self._init_failures is None:
            try:
                self._init_failures = dict(
                    json.loads(self._failures_path.read_text(encoding="utf-8"))
                )
            except FileNotFoundError:
                self._init_failures = {}
        return self._init_failures

    def _record_failure(self, work_id: str, entry: "dict[str, Any] | None") -> None:
        """실패 기록의 durable write-through — ``entry=None`` 은 해소(삭제)다."""
        with self._lock:
            failures = self._failures()
            if entry is None:
                if failures.pop(work_id, None) is None:
                    return
            else:
                failures[work_id] = entry
            self._root.mkdir(parents=True, exist_ok=True)
            tmp = self._failures_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(failures, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._failures_path)

    # ─── 공통 재료 ──────────────────────────────────────────────────────────

    def _ensure_manifest(self) -> None:
        """지원 매체 **전부**의 immutable manifest 를 create-once 로 세운다.

        매체별로 늦게 seed 하지 않는다 — Work 는 매체를 못 바꾸지만 한 홈에 두 매체의 Work
        가 함께 살고, 어느 쪽이 먼저 오든 apply 의 무결성 검사가 자기 manifest 를 찾아야
        한다. 표(``_MEDIA_QUALIFICATION``)를 도는 것이 그 보장의 얼굴이다.
        """
        if self._manifest_seeded:
            return
        for profile, manifest in _MEDIA_QUALIFICATION.values():
            try:
                self._quals.get_manifest(profile.id)
            except ObjectNotFound:
                self._quals.put_manifest(manifest(self._now()))
        # S5F R2-05a(#740): mutable Profile admission bootstrap-to-ADMITTED 를 제거했다 — S3 Apply 는
        # 이제 mutable admission gate 가 아니라 exact PASS QualificationEvidence + Work-local currentness
        # 로 fail-closed 한다(immutable qualification manifest 만 seed 한다).
        self._manifest_seeded = True

    def _binding(self, work_id: str, job) -> MutableSourceBinding:
        # media 는 Job 파생이다(S10-02) — 「무슨 bytes 를 캡처했는가」는 매체 사실이고,
        # 그 값이 revision·manifest·apply 무결성까지 관통하므로 하드코딩하면 TXT Work 가
        # hwpx 로 기재된 채 통과한다(선언과 실제가 갈리는 이 저장소의 지배 결함류).
        return MutableSourceBinding(
            source_binding_id=f"{work_id}.binding",
            media=job.media,
            host_reference=job.template_path,
            display_metadata={},
            generation=job.binding_revision,
        )

    def _lineage(self, work_id: str, binding: MutableSourceBinding) -> TemplateLineage:
        return TemplateLineage(
            template_lineage_id=f"{work_id}.lineage",
            media=binding.media,
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

    def current_template_application_id(self, work_id: "str | None") -> "str | None":
        """Durable Work authority가 가리키는 현재 Template Application을 읽는다."""
        if work_id is None or not self._works.exists(work_id):
            return None
        self._recover(work_id)
        return self._works.load(work_id).work.current_template_application_id

    def zone(self, job_name: str, media: str, template_missing: bool) -> dict[str, Any]:
        """job 스냅샷의 ``template_change`` 존 — capability·현재 Preparation·epoch."""
        if media not in SUPPORTED_MEDIA or template_missing:
            return unsupported_zone()
        job = load_job(self._registry, job_name)
        work_id = job.authority_id or None
        failure = self._failures().get(work_id or "")
        if failure is not None:
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
            self._record_failure(work_id or "", None)
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
        result, _job, _application_id = self.check_for_seated_context(
            job_name, prepare_request_id, actor
        )
        return result

    def check_for_seated_context(
        self, job_name: str, prepare_request_id: str, actor: str = LOCAL_ACTOR
    ) -> "tuple[dict, Job | None, str | None]":
        """확인 결과와 같은 command Job/Application identity를 낸다."""
        if not _REQUEST_ID.fullmatch(prepare_request_id or ""):
            raise TemplateChangeError(f"잘못된 확인 요청 키 {prepare_request_id!r}")
        job = load_job(self._registry, job_name)  # 없으면 loud(포트가 raise)
        profile = _profile_for(job.media, "변경사항 확인")
        self._ensure_manifest()
        work_id = self._work_id_for(job_name, create=True)
        assert work_id is not None
        job = load_job(self._registry, job_name)
        if job.authority_id != work_id:
            raise TemplateChangeError("문서 작업 권위를 다시 확인할 수 없습니다")
        self._recover(work_id)

        if not self._works.exists(work_id):
            outcome = self._bootstrap(work_id, job_name, job, prepare_request_id, profile)
            if outcome.result != BOOTSTRAP_OK:
                return (
                    {"ok": False, "reason": CAPABILITY_INITIALIZATION_REQUIRED},
                    None,
                    None,
                )

        binding = self._binding(work_id, job)
        prep = start_prepare(
            self._works,
            work_id=work_id,
            prepare_request_id=prepare_request_id,
            actor=actor,
            resolve_pins=lambda _work: PreparePins(
                binding.source_binding_id, binding.generation, profile.id
            ),
            preparation_id=f"p-{prepare_request_id}",
            execution_session_id=self._session_id,
            started_at=self._now(),
            authorize=_authorize,
        )
        advanced = self._advance(work_id, job_name, prep, profile)
        # `_advance` 반환 뒤 Preparation/Application은 이미 durable 하다. 그 뒤 registry를
        # 재조회하지 않고, 마지막 load-bearing gate가 실제로 본 Job snapshot을 함께 반환한다.
        if (
            advanced.final_job_snapshot is not None
            and advanced.final_job_snapshot.authority_id != work_id
        ):
            return ({"ok": False, "reason": "work_context_changed"}, None, None)
        return (
            {
                "ok": True,
                "preparation": self._view(
                    advanced.aggregate, work_id, advanced.preparation
                ),
            },
            advanced.final_job_snapshot,
            advanced.current_application_id,
        )

    def resolve_generation_template(self, job_name: str) -> str:
        """managed Product Work 생성의 정본 템플릿 경로 — current Application 의 exact applied
        Candidate bytes 를 staging 한 read-only 경로다(#681 G11).

        mutable ``job.template_path`` 를 직접 소비하지 않는다: bootstrap-on-demand 로 Work·
        current Application 을 세우고(첫 생성이 exact bytes 를 Candidate store 에 확립),
        slotless admission gate(exact context·provenance·bytes 무결성)를 통과할 때만 staged
        경로를 낸다. 실패는 fallback 없이 시끄럽게 오른다(confirm-or-alarm):
        bootstrap 실패는 ``SlotlessRunAdmissionError(TEMPLATE_INITIALIZATION_REQUIRED)``,
        gate 차단은 그 verdict code(NEEDS_CONFIGURATION[_REVIEW]·STALE·SLOT_CONFIGURATION_
        EXECUTION_NOT_AVAILABLE·SLOTLESS_SELECTION_CONTEXT_REQUIRED)로 오른다.
        """
        return self.resolve_generation_template_for_seated_context(job_name)

    def resolve_generation_template_for_seated_context(
        self,
        job_name: str,
        *,
        on_context: "Callable[[Job, str], None] | None" = None,
    ) -> str:
        """생성 admission 전에 이미 확립된 Work/Application identity를 알린다."""
        job = load_job(self._registry, job_name)
        # **여기만 여전히 hwpx 전용이다**(S10-02 #859 범위 밖): 이 경로는 managed HWPX 문서
        # 생성이 겨눌 staged 템플릿을 낸다. TXT 의 산출은 문서 생성이 아니라 작업대 복사라
        # 물질화·복사 인수는 S10-04 소관이고, 그 전에 여는 것은 없는 기능을 있는 척하는 것이다.
        if job.media != "hwpx":
            raise TemplateChangeError("HWPX 작업이 아니라 생성을 이 경로로 지원하지 않습니다")
        profile = _profile_for(job.media, "생성")
        self._ensure_manifest()
        work_id = self._work_id_for(job_name, create=True)
        assert work_id is not None
        job = load_job(self._registry, job_name)
        if job.authority_id != work_id:
            raise TemplateChangeError("문서 작업 권위를 다시 확인할 수 없습니다")
        self._recover(work_id)
        if not self._works.exists(work_id):
            # 매 Generate 시도는 fresh id 다 — bootstrap 이 qualification 에서 실패하며 create-once
            # Candidate/qualification object 를 남겨도, 템플릿을 고쳐 다시 누르면 새 id 로 재부트스트랩
            # 된다(고정 id 면 ObjectAlreadyExists 로 복구 불가). 진짜 중복 클릭은 generation_lock 이
            # 막으므로 여기서 재전송-멱등을 따로 지킬 필요가 없다.
            outcome = self._bootstrap(
                work_id, job_name, job, f"gen-{uuid.uuid4().hex}", profile
            )
            if outcome.result != BOOTSTRAP_OK:
                raise SlotlessRunAdmissionError(TEMPLATE_INITIALIZATION_REQUIRED)
        aggregate = self._works.load(work_id)
        if on_context is not None:
            job = load_job(self._registry, job_name)
            if job.authority_id != work_id:
                raise TemplateChangeError("문서 작업 권위를 다시 확인할 수 없습니다")
            on_context(job, aggregate.work.current_template_application_id)
        ws = self._workspace.get_or_create(self._now())
        try:
            run = admit_managed_slotless_run(
                WorkSlotConfigurationStore(self._root / "slot_configs"),
                _WorkStateReadPort(self._works),
                self._quals, self._candidates, self._candidates,
                _InitialApplicationProvenance(self._works),
                str(self._root),
                workspace_instance_id=ws,
                expected_work_authority_id=work_id,
                expected_template_application_id=aggregate.work.current_template_application_id,
                captured_at=self._now(),
            )
        except SlotSelectionCaptureError as exc:
            # slot-bearing 이고 slot config 가 미완이면 capture 가 admit 앞에서 SLOT_CONFIGURATION_
            # INCOMPLETE 로 던진다 — 구조화된 제품 상태로 번역한다(raw 예외가 프런트로 새지 않게).
            raise SlotlessRunAdmissionError(
                SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE, str(exc)
            ) from exc
        return run.staged_template_path

    def clear_generation_staging(self) -> None:
        """run 이 끝나 아무 실행도 staged 경로를 참조하지 않을 때 staging 사본을 정리한다
        (#681 「cleanup 은 Host lifecycle 소유」). content-addressed 라 다음 run 이 다시
        stage 하므로 run 뒤 지우는 것은 안전하다 — 안 지우면 판본마다 read-only 사본이 영구
        누적된다."""
        clear_run_staging(self._root)

    def source_drift_note(self, job_name: str) -> "str | None":
        """이미 부트스트랩된 Work 의 현재 원본 파일 bytes 가 캡처된 applied Candidate bytes 와
        다르면 시끄러운 경고 문안을 낸다 — 생성은 캡처본을 쓰므로(#681 F1) 사용자가 「검토한
        원본 편집분이 반영 안 됨」을 조용히 겪지 않게 한다(confirm-or-alarm). digest 비교뿐:
        seat 시점에 gate/stage 를 돌리지 않는다(applied-work NEEDS_CONFIGURATION 회귀 방지).

        미부트스트랩(원본=실행본이라 일관)·미지원 매체·무편집·값싸게 못 구하는 경우는 None.
        """
        job = load_job(self._registry, job_name)
        work_id = job.authority_id or None
        if (
            job.media not in SUPPORTED_MEDIA
            or not work_id
            or not self._works.exists(work_id)
        ):
            return None
        try:
            aggregate = self._works.load(work_id)
            applied = resolve_exact_applied_template_input(
                _WorkStateReadPort(self._works), self._quals, self._candidates,
                work_id, aggregate.work.current_template_application_id,
            )
            # ponytail: 부트스트랩된 Work 는 snapshot 마다 원본을 해시한다(hwpx 는 클 수 있다).
            # 지금은 그런 Work 가 드물어 무시할 비용 — 지연이 문제되면 (mtime_ns,size) 로 캐시.
            source_digest = blob_digest(Path(job.template_path).read_bytes())
        except (SlotConfigurationContextError, OSError):
            return None  # 값싸게 못 구하면 경고 없음(preview 를 막지 않는다)
        if source_digest == applied.exact_content_digest:
            return None
        return (
            "원본 파일이 캡처 이후 편집되었습니다 — 생성은 캡처된 버전을 사용합니다. "
            "편집분을 반영하려면 다시 가져오세요."
        )

    def _advance(
        self,
        work_id: str,
        job_name: str,
        prep: TemplateChangePreparation,
        profile: QualificationProfile,
    ) -> _AdvanceResult:
        """CAPTURING→QUALIFYING→admission 을 순서대로 전진 — 각 stage 는 멱등 short-circuit."""
        initial_job_snapshot = load_job(self._registry, job_name)
        final_job_snapshot = None

        def capture_gate_generation(_work: DocumentWork) -> int:
            return load_job(self._registry, job_name).binding_revision

        def admission_gate_binding(_work: DocumentWork) -> tuple[str, int]:
            nonlocal final_job_snapshot
            final_job_snapshot = load_job(self._registry, job_name)
            return f"{work_id}.binding", final_job_snapshot.binding_revision

        if prep.status == PREP_CAPTURING:
            # pin 된 generation 으로 capture 한다(현재 job 값이 아니라) — pin 불일치는
            # runner 의 신뢰 경계가 SOURCE_BINDING_CHANGED 로 판정할 몫이다.
            pinned = MutableSourceBinding(
                source_binding_id=prep.source_binding_id,
                media=initial_job_snapshot.media,
                host_reference=initial_job_snapshot.template_path,
                display_metadata={},
                generation=prep.source_binding_generation,
            )
            prep = run_capture_stage(
                self._works, self._candidates,
                work_id=work_id, preparation_id=prep.preparation_id,
                lineage=self._lineage(work_id, pinned), binding=pinned,
                reader=self._reader(job_name),
                resolve_current_generation=capture_gate_generation,
                captured_at=self._now(), created_at=self._now(),
            )
        if prep.status == PREP_QUALIFYING:
            prep = run_qualification_stage(
                self._works, self._candidates, self._quals,
                work_id=work_id, preparation_id=prep.preparation_id,
                profile=profile, engine_metadata=dict(_ENGINE_METADATA),
                started_at=self._now(), completed_at=self._now(), qualified_at=self._now(),
            )
        if prep.status == PREP_QUALIFYING and prep.attempt_id is not None:
            # PASS checkpoint 는 QUALIFYING 을 유지한다 — READY 승격/terminal 은 admission 몫.
            admission = admit_preparation(
                self._works, self._candidates, self._quals,
                work_id=work_id, preparation_id=prep.preparation_id,
                resolve_current_binding=admission_gate_binding,
                prepared_change_id=f"{prep.preparation_id}-chg", prepared_at=self._now(),
            )
            aggregate = admission.aggregate
        else:
            aggregate = self._works.load(work_id)
        prep = next(
            p for p in aggregate.preparations if p.preparation_id == prep.preparation_id
        )
        return _AdvanceResult(
            prep,
            aggregate,
            final_job_snapshot,
            aggregate.work.current_template_application_id,
        )

    def _bootstrap(
        self,
        work_id: str,
        job_name: str,
        job,
        request_id: str,
        profile: QualificationProfile,
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
            reader=self._reader(job_name), profile=profile,
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
            self._record_failure(work_id, {
                # repair 판정은 **파일 실물 서명**이다 — job revision 은 한글에서 바이트만
                # 고친 수정(레지스트리 무접촉)에 안 오르므로 그걸 키로 쓰면 정당한 수리
                # 뒤에도 확인이 영영 닫힌다.
                "signature": self._template_signature(job.template_path),
                "diagnostics": [
                    {"kind": kind, "message": message} for kind, message in diagnostics
                ],
            })
        else:
            self._record_failure(work_id, None)
        return outcome

    @staticmethod
    def _template_signature(template_path: str) -> "list[int] | None":
        """template 실물의 변경 감지 서명 — 부재는 None(그 자체가 한 상태).

        JSON 왕복(durable 실패 기록)과 직접 동치 비교가 되도록 list 로 낸다."""
        try:
            stat = os.stat(template_path)
        except OSError:
            return None
        return [stat.st_mtime_ns, stat.st_size]

    # ─── apply ──────────────────────────────────────────────────────────────

    def apply(self, job_name: str, change_token: str, actor: str = LOCAL_ACTOR) -> dict:
        """[변경사항 적용] — token 해석·독립 권한 확인·cross-Work 거절 뒤 원자 apply."""
        result, _application_id = self.apply_for_seated_context(
            job_name, change_token, actor
        )
        return result

    def apply_for_seated_context(
        self, job_name: str, change_token: str, actor: str = LOCAL_ACTOR
    ) -> "tuple[dict, str]":
        """Apply 결과와 같은 atomic aggregate의 current Application ID를 낸다."""
        resolved = self._change_id_by_token.get(str(change_token or ""))
        if resolved is None:
            raise TemplateChangeError("적용 대상이 유효하지 않습니다 — 변경사항을 다시 확인하세요")
        token_work_id, change_id = resolved
        work_id = self._work_id_for(job_name, create=False)
        if work_id is None or work_id != token_work_id:
            # cross-Work misuse: request 거절, 두 Work·Change 상태 무변경.
            raise TemplateChangeError("이 변경사항은 현재 작업의 것이 아닙니다")
        # immutable qualification manifest 를 seed 한다(R2-05a: mutable admission bootstrap 없음).
        self._ensure_manifest()
        now = self._now()
        # create-once durable WorkspaceInstanceId — S3 Apply·S4 mutation 이 같은 fence 를 공유한다.
        workspace_instance_id = self._workspace.get_or_create(now)
        # fence 아래에서 apply 하고, commit 된 aggregate 도 같은 fence 아래에서 받는다 —
        # fence 밖에서 reload 하면 다른 apply 가 끼어들어 outcome↔view 가 어긋날 수 있다.
        outcome, aggregate = apply_prepared_change(
            self._works, self._candidates, self._quals,
            workspace_instance_id=workspace_instance_id,
            work_id=work_id, change_id=change_id, actor=actor, authorize=_authorize,
            new_application_id=f"{change_id}-app", provenance_id=f"{change_id}-prov",
            outbox_event_id=f"{change_id}-evt", applied_at=now,
        )
        if outcome.result == APPLY_INTEGRITY_ERROR:
            raise TemplateChangeError(
                "적용 무결성 확인에 실패했습니다 — 저장된 확인 결과를 신뢰할 수 없습니다"
            )
        current = find_application(
            aggregate, aggregate.work.current_template_application_id
        )
        return {
            "status": product_apply_status(outcome.result),
            "current_template_application_epoch": current.application_epoch,
            "is_current": outcome.resulting_application_id
            == aggregate.work.current_template_application_id,
        }, current.application_id
