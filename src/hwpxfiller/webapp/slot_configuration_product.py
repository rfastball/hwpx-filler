"""S4 Slot Configuration Product API (S4-09 · #679).

durable workspace identity, route-bound expected Work, restart-verifiable **HMAC-signed** token,
fresh current view 를 잇는다. token 은 권한이나 요청 대상 Work 를 대신하지 않는다 — route 가 정한
expected Work 와 token 이 담은 Work 를 **독립 비교**해 다르면 CROSS_WORK 로 거절한다.

배치: pure token codec/claims 는 application(`slot_token`), secret provider·store 어댑터는 external,
이 Product API 는 webapp(work_ref·actor 해석 + 응답 조립)이다. #677 command engine 과 #678 projection
을 소비하고 새 token 을 발급한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..application.jobs import (
    JobStorePort,
    ensure_job_authority_id,
    load_job,
)
from ..application.slot_command import (
    STALE_CONFIGURATION,
    STALE_TEMPLATE_APPLICATION,
    ConfigurationCommandContext,
)
from ..application.slot_configuration_context import (
    AppliedTemplateContentIntegrityError,
    CrossWorkContext,
    SlotConfigurationContext,
    SlotConfigurationContextError,
    StaleTemplateApplication,
    TemplateInitializationRequired,
    TemplateStructureIntegrityError,
    UnsupportedTemplateStructureProjection,
    resolve_slot_configuration_context,
)
from ..application.preset_command import (
    PresetListing,
    PresetSaveResult,
    PresetStorePort,
    REJECTED,
    list_selection_presets as list_presets_from_store,
)
from ..application.slot_configuration_projection import (
    CONTEXT_ERROR,
    NOT_APPLICABLE,
    CurrentSlotConfigurationView,
    ProjectedDetachedSelection,
    project_context_error,
    project_current_slot_configuration,
)
from ..application.slot_reconciliation import (
    ReconciliationApplication,
    ReconciliationIntegrityError,
    SlotConfigurationResolution,
    find_nearest_predecessor_configuration,
    resolve_slot_configuration,
)
from ..application.work_slot_configuration import WorkSlotConfigurationDraft
from ..domain.slot_selection import SlotSelectionSet
from ..host.locations import default_preset_dir
from ..host.per_work_fence import per_work_mutation_fence
from ..application.slot_token import (
    TOKEN_PURPOSE,
    TOKEN_SCHEMA_VERSION,
    ConfigurationTokenClaims,
    ConfigurationTokenError,
    InvalidConfigurationToken,
    TokenPurposeMismatch,
    actor_binding_digest,
    open_configuration_token,
    sign_configuration_token,
)
from ..external.candidate_store import CandidateObjectStore
from ..external.preset_store import PresetRegistry
from ..external.qualification_store import QualificationObjectStore
from ..external.slot_command_runner import (
    SlotCommandResult,
    apply_selection_preset as run_apply_selection_preset,
    ensure_current_slot_configuration,
    save_selection_preset as run_save_selection_preset,
    select_slot_option,
)
from ..external.slot_token_secret import SlotTokenSecretError, SlotTokenSecretStore
from ..external.work_configuration_store import WorkSlotConfigurationStore
from ..external.work_template_store import (
    AtomicWorkTemplateStateStore,
    WorkAggregateNotFound,
    WorkTemplateStateAggregate,
)
from ..external.work_configuration_store import WorkspaceMetadataStore

#: 단일 사용자 데스크톱 로컬 actor(권위 subject) — token·session 과 독립으로 매 요청 확인한다.
LOCAL_ACTOR = "local-user"

CURRENT = "CURRENT"

_CONTEXT_ERROR_FALLBACK = (
    "포함할 내용을 불러오지 못했습니다. "
    "문서 작업을 다시 열고 템플릿을 확인하세요."
)
_CONTEXT_ERROR_MESSAGES = {
    TemplateInitializationRequired.code: (
        "템플릿 확인이 끝나지 않아 포함할 내용을 불러오지 못했습니다. "
        "템플릿을 확인하세요."
    ),
    StaleTemplateApplication.code: (
        "템플릿이 바뀌어 포함할 내용을 불러오지 못했습니다. "
        "템플릿을 다시 확인하세요."
    ),
    UnsupportedTemplateStructureProjection.code: (
        "이 템플릿 구조에서는 포함할 내용을 선택할 수 없습니다. "
        "다른 템플릿을 적용하세요."
    ),
    TemplateStructureIntegrityError.code: (
        "템플릿 구조를 확인할 수 없어 포함할 내용을 불러오지 못했습니다. "
        "템플릿을 다시 확인하세요."
    ),
    AppliedTemplateContentIntegrityError.code: (
        "적용된 템플릿 파일을 확인할 수 없어 포함할 내용을 불러오지 못했습니다. "
        "템플릿을 다시 확인하세요."
    ),
    CrossWorkContext.code: (
        "현재 문서 작업과 템플릿이 맞지 않아 포함할 내용을 불러오지 못했습니다. "
        "문서 작업을 다시 연 뒤 템플릿을 확인하세요."
    ),
}


class SlotConfigurationProductError(Exception):
    """Product API 거절 — code 로 원인 구분(ledger 에 기록하지 않는다)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject(code: str, message: str) -> SlotConfigurationProductError:
    return SlotConfigurationProductError(code, message)


class _WorkStateReadAdapter:
    """AtomicWorkTemplateStateStore → WorkTemplateStateReadPort.

    store 는 부재를 WorkAggregateNotFound 로 raise 하지만 Port 계약은 load()->None 이다 —
    이 번역이 #674·#678 이 소비 슬라이스로 미룬 배선이다(TEMPLATE_INITIALIZATION_REQUIRED 가
    production 에서 도달 가능해진다).
    """

    def __init__(self, store: AtomicWorkTemplateStateStore) -> None:
        self._store = store

    def load(self, work_id: str) -> "WorkTemplateStateAggregate | None":
        try:
            return self._store.load(work_id)
        except WorkAggregateNotFound:
            return None


@dataclass(frozen=True)
class _CurrentSnapshot:
    application_id: str
    selection_contract_id: str
    configuration_presence: bool
    configuration_version: int | None


@dataclass(frozen=True)
class MutationOutcomeView:
    outcome_code: str
    changed: bool
    outcome_replayed: bool
    request_relation: str


@dataclass(frozen=True)
class CurrentViewResponse:
    view_status: str
    configuration_status: str
    context_error: str | None
    context_error_message: str | None
    new_configuration_token: str | None
    projection: CurrentSlotConfigurationView | None
    blocking_items: tuple
    informational_changes: tuple


@dataclass(frozen=True)
class SlotConfigurationCommandResponse:
    mutation_outcome: MutationOutcomeView | None
    current_view: CurrentViewResponse
    refresh_required: bool


@dataclass(frozen=True)
class PresetApplyResponse:
    """Preset 적용 응답 — mutation 축은 select/clear 와 **같은 형**이고 수치는 관통이다(S9-03 · #829).

    ``applied_count``·``broken_count``·``applied_slot_ids``·``broken`` 은
    :class:`~hwpxfiller.application.preset_command.PresetApplyDecision` 이 낸 값을 runner 를 거쳐
    **그대로** 싣는다 — 링2 가 slot 목록을 다시 훑어 세면 같은 상태를 두 곳이 판정하게 된다(#828).

    거절(``rejection_code``)이면 mutation 도 view 도 없다: 적용된 것이 없으니 새 token 을 발급할
    근거도, 되돌려 그릴 새 view 도 없다. 무엇이 거절했는지는 code·detail 이 재진술한다.
    """

    mutation_outcome: MutationOutcomeView | None
    current_view: CurrentViewResponse | None
    refresh_required: bool
    applied_slot_ids: tuple[str, ...]
    broken: tuple[ProjectedDetachedSelection, ...]
    applied_count: int
    broken_count: int
    rejection_code: str | None
    rejection_detail: str | None


def _request_relation(outcome_code: str) -> str:
    if outcome_code in (STALE_TEMPLATE_APPLICATION, STALE_CONFIGURATION):
        return outcome_code
    return CURRENT


class SlotConfigurationProduct:
    """job 화면이 소비하는 slot configuration Product 서비스 — webview 비의존, 헤드리스 구동."""

    def __init__(
        self,
        registry: JobStorePort,
        *,
        root: "str | Path",
        clock: Callable[[], datetime],
        presets: "PresetStorePort | None" = None,
    ) -> None:
        self._registry = registry
        self._root = Path(root)
        self._configs = WorkSlotConfigurationStore(self._root / "slot_configs")
        self._works = _WorkStateReadAdapter(
            AtomicWorkTemplateStateStore(self._root / "works")
        )
        self._quals = QualificationObjectStore(self._root / "qualification")
        self._candidates = CandidateObjectStore(self._root / "candidates")
        self._workspace = WorkspaceMetadataStore(self._root)
        self._secrets = SlotTokenSecretStore(self._root)
        # Preset 레지스트리는 **Work authority root 아래가 아니라 홈**이다(#821 D2 — Work 밖
        # 재사용이 존재 이유라 Work 저장소와 수명·경계를 공유하지 않는다). 미주입이면 홈
        # 기본 위치로 해석한다(테스트는 autouse 홈 격리가 지킨다).
        self._presets: PresetStorePort = (
            presets if presets is not None else PresetRegistry(default_preset_dir())
        )
        self._clock = clock

    # ── public Product API ──────────────────────────────────────────────────────
    def open_slot_configuration(self, work_ref: str) -> SlotConfigurationCommandResponse:
        work_id, ws = self._route(work_ref)
        return self._run(work_id, ws, token_app=None, mutating=False, call=lambda: (
            ensure_current_slot_configuration(
                self._configs, self._works, self._quals, self._candidates,
                context=self._read_context(ws, work_id), now=self._now(),
            )
        ))

    def refresh_slot_configuration(
        self, work_ref: str, configuration_token: "str | None" = None
    ) -> SlotConfigurationCommandResponse:
        work_id, ws = self._route(work_ref)
        token_app = None
        if configuration_token is not None:
            token_app = self._verify_token(configuration_token, ws, work_id).template_application_id
        return self._run(work_id, ws, token_app=token_app, mutating=False, call=lambda: (
            ensure_current_slot_configuration(
                self._configs, self._works, self._quals, self._candidates,
                context=self._read_context(ws, work_id), now=self._now(),
            )
        ))

    def current_slot_configuration_view(
        self, work_ref: str
    ) -> SlotConfigurationCommandResponse:
        """render/snapshot 전용 **read-only** projection — durable S4 authority 를 mutate 하지 않는다.

        #744: open/refresh 는 ``ensure_current_slot_configuration`` 을 태워 stored config 부재 시
        successor reconciliation 을 물질화(CHANGED persist)한다. 그 durable materialization 은
        **명시적 사용자 open/refresh command 에만** 남긴다 — passive 한 화면 렌더/네비게이션 스냅샷은
        이 경로로 현재 authority 를 그대로 투영한다. stored config 가 없으면 빈 선택(NEEDS_SELECTION)
        으로 표시하고 새 config 를 만들지 않는다. token 은 발급하되(편집 진입 seam) slot
        config 를 저장하지 않으므로 basis 변경도 없다(``_maybe_auto_check`` 진입 근거를 만들지 않는다).

        #777: 빈 선택을 그리는 것만으로는 **정직하지 않다**. successor 로 넘어온 직후가 정확히
        그 상태인데, 그때 사용자는 자기가 고른 것이 어떻게 됐는지 묻지도 못한 채 「아직 선택 안
        함」만 봤다. 그래서 이전 Configuration 의 선언 선택을 현재 구조에 대고 다시 분류해
        ``retained_selections`` 로 함께 싣는다 — 판정만 하고 **저장은 여전히 0** 이다.
        """
        work_id, ws = self._route(work_ref)
        view, new_token, _current_app = self._current_view_and_token(ws, work_id)
        return SlotConfigurationCommandResponse(
            mutation_outcome=None,
            current_view=self._current_view_response(view, new_token),
            refresh_required=view.view_status == CONTEXT_ERROR,
        )

    def select_slot_option(
        self,
        work_ref: str,
        configuration_token: str,
        slot_id: str,
        option_id: str,
        request_id: str,
    ) -> SlotConfigurationCommandResponse:
        work_id, ws = self._route(work_ref)
        claims = self._verify_token(configuration_token, ws, work_id)
        return self._run(work_id, ws, token_app=claims.template_application_id, mutating=True, call=lambda: (
            select_slot_option(
                self._configs, self._works, self._quals, self._candidates,
                context=self._command_context(ws, work_id, claims),
                request_id=request_id, slot_id=slot_id, option_id=option_id, now=self._now(),
            )
        ))

    # 선택 해제 Product 동사는 #903 에서 제거됐다. 그것을 부르던 유일한 표면은 detached 정리
    # 버튼이었고 detached 는 SG-01(#733) 이후 제품 경로에서 생기지 않는다 — command engine 의
    # clear(`slot_command.decide_clear`·`slot_command_runner.clear_slot_selection`)는 S4 명령
    # 대수의 절반으로 남고, 여기 제품 표면만 사라진다.

    # ── Selection Preset(S9-03 · #829) — 저장·나열·적용 ──────────────────────────────
    def save_selection_preset(
        self,
        work_ref: str,
        configuration_token: str,
        name: str,
        confirmed_overwrite_key: "str | None" = None,
    ) -> PresetSaveResult:
        """현재 선택을 이름 붙여 Preset 으로 보관한다 — 판정·코드는 S9-02 값 **그대로**.

        Work durable 상태는 읽기만 한다(선택의 사본을 뜬다). 그래도 token 을 요구하는 이유는
        route/Work/actor 결속과 「지금 화면이 보고 있는 그 구성」의 exact context 를 세우기
        위해서다 — token 없이 부르면 어느 Application 의 선택을 떴는지 말할 수 없다.

        문안을 조립하지 않는다: ``status``/``code``/``existing_key`` 만 나가고 덮어쓰기 확인
        문구·거절 재진술은 웹이 소유한다(#829 — 판정·수치는 Python, 문안·확인 UI 는 웹).
        """
        work_id, ws = self._route(work_ref)
        claims = self._verify_token(configuration_token, ws, work_id)
        try:
            return run_save_selection_preset(
                self._configs, self._works, self._quals, self._candidates, self._presets,
                context=self._command_context(ws, work_id, claims),
                name=name,
                confirmed_overwrite_key=confirmed_overwrite_key,
                now=self._now(),
            )
        except SlotConfigurationContextError as exc:
            # `_run` 과 같은 규율로 접는다(mutation 미발생·무저장). 저장 응답에는 view 축이
            # 없으므로 사실은 거절로 실린다 — 사유 코드는 보존하고 사용자 문안은 context
            # 문안 지도에서 온다(빈칸으로 새지 않는다).
            return PresetSaveResult(
                status=REJECTED,
                code=exc.code,
                saved_key=None,
                existing_key=None,
                existing_created_at=None,
                detail=_CONTEXT_ERROR_MESSAGES.get(exc.code, _CONTEXT_ERROR_FALLBACK),
            )

    def list_selection_presets(self, work_ref: "str | None") -> PresetListing:
        """이 Work 의 **현재 구조에 전부 적용 가능한** Preset 목록 + 손상 항목(#875).

        보관은 Work 밖(홈 레지스트리)이지만 소비는 Work 안이다 — 그래서 나열은 Work 를 받는다.
        호환 판정은 적용 경로가 쓰는 :func:`~hwpxfiller.application.preset_command.fit_preset_selections`
        하나가 지고 여기는 구조 context 를 세워 넘기기만 한다(slot·option 재순회 0).

        ``work_ref`` 가 없거나 그 Work 의 구조를 세울 수 없으면(초기화 전·context error·접근
        불가) 호환을 **주장할 수 있는** 항목이 0 이다 — 무필터 전량 노출로 되돌아가지 않는다.
        그 사유는 같은 스냅샷의 「포함할 내용」 존이 이미 시끄럽게 재진술하고 있고, 적용 경로도
        같은 사유로 거절한다.

        손상 항목을 목록에서 지우지 않는다: 소비 표면이 비활성 + 사유 병기로 재진술한다.

        **어느 항목이 지금 적용돼 있는가**(``applied_key`` · #945 F3)도 같은 왕복에서 나온다.
        그래서 현재 Configuration 을 함께 읽어 넘긴다 — 구조를 세운 그 자리에서 draft 도 집으면
        목록·호환·표지가 **같은 한 순간**을 말한다(표면이 나중에 따로 조회하면 갈릴 수 있다).
        판정 자체는 application 층이 지고 여기는 재료를 모아 넘기기만 한다.
        """
        context: SlotConfigurationContext | None = None
        config: WorkSlotConfigurationDraft | None = None
        if work_ref is not None:
            try:
                work_id, ws = self._route(work_ref)
                context = resolve_slot_configuration_context(
                    self._works, self._quals, self._candidates, ws, work_id
                )
                config = self._stored_draft(work_id, context.template_application_id)
            except (SlotConfigurationProductError, SlotConfigurationContextError):
                # 구조를 세우지 못하는 모든 사유는 「호환을 주장할 수 있는 항목 0」 하나로
                # 접힌다 — 여기서 목록을 그리려고 판정을 지어내지 않는다.
                context = None
                config = None
        return list_presets_from_store(self._presets, context, config)

    def _stored_draft(
        self, work_id: str, application_id: str
    ) -> "WorkSlotConfigurationDraft | None":
        """이 Work 의 CURRENT application 앞에 서 있는 Configuration(없으면 None) — 읽기만 한다.

        물질화하지 않는다(:meth:`_current_view_and_token` 과 같은 write-on-read 회피). 부재는
        「아직 아무것도 고르지 않았다」라는 정상 상태다.
        """
        if not self._configs.exists(work_id):
            return None
        for cfg in self._configs.load(work_id).configurations.configurations:
            if cfg.base_template_application_id == application_id:
                return cfg
        return None

    def apply_selection_preset(
        self, work_ref: str, configuration_token: str, preset_key: str
    ) -> PresetApplyResponse:
        """Preset 을 현재 Configuration 에 제안으로 적용하고 fresh view + 새 token 을 낸다.

        성공 축의 성형은 select/clear 의 :meth:`_respond` 와 **동형**이다 — view 가 갈렸으니
        새 token 을 함께 낸다(다음 command 가 옛 token 으로 서면 STALE 로 거절된다). 여기에
        S9-02 가 낸 수치(적용 n·깨짐 m)를 얹기만 한다(재조립 0).
        """
        work_id, ws = self._route(work_ref)
        claims = self._verify_token(configuration_token, ws, work_id)
        try:
            result = run_apply_selection_preset(
                self._configs, self._works, self._quals, self._candidates, self._presets,
                context=self._command_context(ws, work_id, claims),
                preset_key=preset_key,
                now=self._now(),
            )
        except SlotConfigurationContextError as exc:
            return self._preset_apply_rejected(
                exc.code, _CONTEXT_ERROR_MESSAGES.get(exc.code, _CONTEXT_ERROR_FALLBACK)
            )
        if result.rejection_code is not None:
            return self._preset_apply_rejected(
                result.rejection_code, result.rejection_detail
            )
        assert result.outcome is not None  # 거절이 아니면 runner 는 terminal outcome 을 낸다
        base = self._respond(
            ws,
            work_id,
            SlotCommandResult(result.outcome, result.view, result.view_error),
            token_app=claims.template_application_id,
        )
        return PresetApplyResponse(
            mutation_outcome=base.mutation_outcome,
            current_view=base.current_view,
            refresh_required=base.refresh_required,
            applied_slot_ids=result.applied_slot_ids,
            broken=result.broken,
            applied_count=result.applied_count,
            broken_count=result.broken_count,
            rejection_code=None,
            rejection_detail=None,
        )

    @staticmethod
    def _preset_apply_rejected(code: str, detail: "str | None") -> PresetApplyResponse:
        return PresetApplyResponse(
            mutation_outcome=None,
            current_view=None,
            refresh_required=False,
            applied_slot_ids=(),
            broken=(),
            applied_count=0,
            broken_count=0,
            rejection_code=code,
            rejection_detail=detail,
        )

    def _run(
        self, work_id: str, ws: str, *, token_app: "str | None", mutating: bool,
        call: "Callable[[], SlotCommandResult]",
    ) -> SlotConfigurationCommandResponse:
        try:
            result = call()
        except SlotConfigurationContextError as exc:
            # init-required·integrity·unsupported = context error(mutation 미발생, 무저장).
            # STALE 은 runner 가 stored terminal 로 삼켜 여기 안 온다.
            return self._context_error_response(exc.code)
        return self._respond(ws, work_id, result, token_app=token_app)

    def _context_error_response(self, code: str) -> SlotConfigurationCommandResponse:
        view = project_context_error(code)
        return SlotConfigurationCommandResponse(
            mutation_outcome=None,
            current_view=self._current_view_response(view, None),
            refresh_required=True,
        )

    # ── route-bound Work verification ─────────────────────────────────────────────
    def _route(self, work_ref: str) -> tuple[str, str]:
        """work_ref → expected WorkAuthorityId + workspace. authorization 을 token 과 독립 확인한다.

        SG-03(#735) C7: authorization 은 여기(job load)가 지고 ``_verify_token`` 보다 **앞선다** —
        유효 서명 token 을 쥐어도 접근 불가 work_ref 는 AUTHORIZATION_FAILURE 다. HMAC 은 authz
        경계가 아니다(정본 `docs/CONTROL_PLANE_SCOPE.md` §HMAC).
        """
        try:
            job = load_job(self._registry, work_ref)
        except Exception as exc:  # 부재·손상 = 접근 불가
            raise _reject("AUTHORIZATION_FAILURE", f"work {work_ref!r} 접근 불가") from exc
        # 단일 사용자 desktop: actor 는 항상 LOCAL_ACTOR. 다른 actor 면 거절.
        # lazy 발급은 의미 1·2(Work identity·durable 표식)의 성질이라 라우팅에서 옳다 —
        # 발급 형태·결속은 단일 helper(S6-05 · #812).
        work_id = job.authority_id or ensure_job_authority_id(self._registry, work_ref)
        ws = self._workspace.get_or_create(self._now())
        return work_id, ws

    def _verify_token(
        self, token: str, ws: str, expected_work_id: str
    ) -> ConfigurationTokenClaims:
        """token open·integrity·purpose·schema·actor binding·workspace·Work 를 검증한다(#679 3~6).

        SG-03(#735): 이 검증은 context integrity·claim authenticity·route/Work·workspace·actor
        binding 까지다. authorization 은 ``_route``(앞선다)가, currentness·expected version·per-Work
        fence·semantic validity 는 runner(`_command_context`→context resolve/CAS)가 **독립** 진다.
        유효 token 은 이들을 대체하지 못한다(정본 `docs/CONTROL_PLANE_SCOPE.md` §HMAC).
        """
        secret = self._load_secret()
        try:
            claims = open_configuration_token(token, secret)
        except TokenPurposeMismatch as exc:
            raise _reject("TOKEN_PURPOSE_MISMATCH", str(exc)) from exc
        except (InvalidConfigurationToken, ConfigurationTokenError) as exc:
            raise _reject("INVALID_CONFIGURATION_TOKEN", str(exc)) from exc
        if claims.actor_binding_digest != self._actor_binding(ws):
            raise _reject("TOKEN_ACTOR_BINDING_MISMATCH", "token actor binding 불일치")
        if claims.workspace_instance_id != ws:
            raise _reject("CROSS_WORKSPACE_CONFIGURATION_TOKEN", "token workspace 불일치")
        if claims.work_authority_id != expected_work_id:
            # token 이 가리키는 Work 를 요청 대상으로 채택하지 않는다.
            raise _reject("CROSS_WORK_CONFIGURATION_TOKEN", "token Work 가 route Work 와 다르다")
        return claims

    # ── context / token issuance ──────────────────────────────────────────────────
    def _load_secret(self) -> bytes:
        # secret 손상은 외부 store 오류를 새지 않고 INVALID_CONFIGURATION_TOKEN 으로 정규화한다.
        try:
            return self._secrets.load_or_create_active_secret()
        except SlotTokenSecretError as exc:
            raise _reject("INVALID_CONFIGURATION_TOKEN", "token secret 손상") from exc

    def _actor_binding(self, ws: str) -> str:
        return actor_binding_digest(LOCAL_ACTOR, ws)

    def _read_context(self, ws: str, work_id: str) -> ConfigurationCommandContext:
        """token 없는 open/refresh 용 context — 현재 상태를 그대로 담는다(exact match 자명)."""
        snap, _err = self._current_snapshot(ws, work_id)
        if snap is None:
            # context 부재/오류라도 ensure 를 부르면 runner 가 STALE/CONTEXT_ERROR 를 낸다.
            return ConfigurationCommandContext(
                workspace_instance_id=ws, expected_work_authority_id=work_id,
                token_work_authority_id=work_id, token_template_application_id="",
                token_selection_contract_id="", token_configuration_presence=False,
                token_configuration_version=None, actor_binding_digest=self._actor_binding(ws),
            )
        return ConfigurationCommandContext(
            workspace_instance_id=ws, expected_work_authority_id=work_id,
            token_work_authority_id=work_id,
            token_template_application_id=snap.application_id,
            token_selection_contract_id=snap.selection_contract_id,
            token_configuration_presence=snap.configuration_presence,
            token_configuration_version=snap.configuration_version,
            actor_binding_digest=self._actor_binding(ws),
        )

    def _command_context(
        self, ws: str, work_id: str, claims: ConfigurationTokenClaims
    ) -> ConfigurationCommandContext:
        return ConfigurationCommandContext(
            workspace_instance_id=ws, expected_work_authority_id=work_id,
            token_work_authority_id=claims.work_authority_id,
            token_template_application_id=claims.template_application_id,
            token_selection_contract_id=claims.selection_semantic_contract_id,
            token_configuration_presence=claims.configuration_presence,
            token_configuration_version=claims.configuration_version,
            actor_binding_digest=claims.actor_binding_digest,
        )

    def _current_snapshot(
        self, ws: str, work_id: str
    ) -> tuple["_CurrentSnapshot | None", "str | None"]:
        try:
            ctx = resolve_slot_configuration_context(
                self._works, self._quals, self._candidates, ws, work_id
            )
        except SlotConfigurationContextError as exc:
            return None, exc.code
        presence, version = False, None
        if self._configs.exists(work_id):
            stored = self._configs.load(work_id)
            for cfg in stored.configurations.configurations:
                if cfg.base_template_application_id == ctx.template_application_id:
                    presence, version = True, cfg.version
                    break
        return (
            _CurrentSnapshot(
                ctx.template_application_id, ctx.selection_semantic_contract_id,
                presence, version,
            ),
            None,
        )

    def _issue_token(self, ws: str, work_id: str, snap: _CurrentSnapshot) -> str:
        claims = ConfigurationTokenClaims(
            token_schema_version=TOKEN_SCHEMA_VERSION,
            token_purpose=TOKEN_PURPOSE,
            workspace_instance_id=ws,
            work_authority_id=work_id,
            template_application_id=snap.application_id,
            selection_semantic_contract_id=snap.selection_contract_id,
            configuration_presence=snap.configuration_presence,
            configuration_version=snap.configuration_version,
            actor_binding_digest=self._actor_binding(ws),
            issued_at=self._now(),
        )
        return sign_configuration_token(claims, self._load_secret())

    def _retained_fate(
        self,
        ctx: SlotConfigurationContext,
        stored: "tuple[WorkSlotConfigurationDraft, ...]",
    ) -> "SlotConfigurationResolution | None":
        """이전에 고른 것이 successor 에서 **어떻게 됐는지**를 read-only 로 판정한다(#777).

        nearest predecessor 의 **선언 선택**을 현재 구조에 대고 다시 분류한다. 종전에는 그
        사실이 아무 데도 안 남아 선택 셋이 조용히 사라졌다.

        **current Configuration 의 존재를 「다 해결됐다」로 읽지 않는다.** successor 에서 한 칸을
        고르는 순간 Configuration 이 생기는데, 그때 남은 이전 선택들(아직 안 고른 것·사라진 항목)의
        사연까지 같이 지우면 첫 클릭 한 번에 나머지가 조용히 증발한다. 게다가 명시적
        open/refresh 는 view 를 만들기 **전에** Configuration 을 물질화하므로, 존재로 끊으면 그
        경로에서는 이 정보가 아예 안 보인다. 항목별로 닫혔는지는 projection 이 현재 resolution 과
        대조해 판정한다.

        읽기만 한다. 새 Configuration 을 만들지 않고(그건 명시적 open/refresh 의 몫 — #744),
        predecessor 의 **구조를 복원하지도 않는다**: 필요한 것은 「이전 선언 선택」과 「현재
        구조」뿐이고, 둘 다 이미 손에 있다. predecessor Configuration 이 애초에 없으면(대다수의
        정상 상태) 이미 읽은 ``stored`` 만 보고 그 자리에서 돌아서므로 추가 store read 는 0 이다.

        chain 무결성이 깨져 있으면(:class:`ReconciliationIntegrityError`) 판정을 **지어내지
        않는다** — 이 자리는 현재 구조를 멀쩡히 그릴 수 있는 렌더 경로라, 여기서 CONTEXT_ERROR 로
        올리면 고칠 화면 자체를 지운다. 이전 선택 이야기만 비운다.
        """
        # predecessor Configuration 후보가 없으면 chain 을 걸을 이유가 없다 — nearest 는 반드시
        # current 아닌 Application 의 것이므로, 그런 항목이 하나도 없으면 결과는 확정적으로 None 이다.
        if not any(
            cfg.base_template_application_id != ctx.template_application_id for cfg in stored
        ):
            return None
        aggregate = self._works.load(ctx.work_id)
        if aggregate is None:  # pragma: no cover - context resolve 가 이미 보장
            return None
        apps = {
            a.application_id: ReconciliationApplication(
                a.application_id, a.previous_application_id, a.application_epoch,
                a.work_id, aggregate.work.template_lineage_id,
            )
            for a in aggregate.applications
        }
        if ctx.template_application_id not in apps:  # pragma: no cover - 방어
            return None
        try:
            source = find_nearest_predecessor_configuration(
                ctx.template_application_id,
                apps,
                {c.base_template_application_id: c for c in stored},
            )
        except ReconciliationIntegrityError:
            return None
        if source is None or not source.selections.selections:
            return None
        return resolve_slot_configuration(
            source.selections, ctx.template_structure, ctx.selection_semantic_contract
        )

    def _current_view_and_token(
        self, ws: str, work_id: str
    ) -> tuple[CurrentSlotConfigurationView, "str | None", "str | None"]:
        """CURRENT application 을 **한 fence 아래에서** 다시 읽어 projection·token 을 함께 만든다.

        projection 과 token 이 같은 (context, config) 스냅샷에서 나오므로 서로 어긋날 수 없다
        (F1: 사이에 낀 commit 이 view 는 옛 version·token 은 새 version 으로 갈라놓는 걸 막는다).
        token 의 application 이 아니라 CURRENT application 을 풀므로 stale-token mutation 도
        fresh current view 를 얻는다(F2). runner 는 자기 fence 를 이미 놓아 여기가 새 획득이다
        (non-reentrant 안전).
        """
        with per_work_mutation_fence(ws, work_id):
            try:
                ctx = resolve_slot_configuration_context(
                    self._works, self._quals, self._candidates, ws, work_id
                )
            except SlotConfigurationContextError as exc:
                return project_context_error(exc.code), None, None
            stored = (
                self._configs.load(work_id).configurations.configurations
                if self._configs.exists(work_id)
                else ()
            )
            config = None
            for cfg in stored:
                if cfg.base_template_application_id == ctx.template_application_id:
                    config = cfg
                    break
            selections = config.selections if config is not None else SlotSelectionSet(())
            resolution = resolve_slot_configuration(
                selections, ctx.template_structure, ctx.selection_semantic_contract
            )
            view = project_current_slot_configuration(
                ctx, config, resolution, retained=self._retained_fate(ctx, stored)
            )
            token = self._issue_token(
                ws, work_id,
                _CurrentSnapshot(
                    ctx.template_application_id, ctx.selection_semantic_contract_id,
                    config is not None, config.version if config is not None else None,
                ),
            )
            return view, token, ctx.template_application_id

    # ── response assembly ─────────────────────────────────────────────────────────
    def _respond(
        self, ws: str, work_id: str, result: SlotCommandResult, *, token_app: "str | None"
    ) -> SlotConfigurationCommandResponse:
        outcome = result.outcome
        mutation = None
        if outcome is not None:
            mutation = MutationOutcomeView(
                outcome_code=outcome.outcome_code, changed=outcome.changed,
                outcome_replayed=outcome.outcome_replayed,
                request_relation=_request_relation(outcome.outcome_code),
            )
        # current_view·token 은 runner 의 token-application view 가 아니라 CURRENT application 을
        # 한 fence 아래 다시 읽어 조립한다(#679: "current view 는 같은 fence 아래 현재 Work 재조립").
        view, new_token, current_app = self._current_view_and_token(ws, work_id)
        refresh_required = (
            view.view_status == CONTEXT_ERROR
            or (token_app is not None and token_app != current_app)
            or (outcome is not None and outcome.application_id != current_app)
        )
        return SlotConfigurationCommandResponse(
            mutation_outcome=mutation,
            current_view=self._current_view_response(view, new_token),
            refresh_required=refresh_required,
        )

    def _current_view_response(
        self, view: CurrentSlotConfigurationView, new_token: "str | None"
    ) -> CurrentViewResponse:
        """CurrentSlotConfigurationView → 프런트 소비 CurrentViewResponse(mutation 축과 무관한 view 성형).

        command 응답(:meth:`_respond`)과 read-only projection(:meth:`current_slot_configuration_view`)
        이 같은 성형을 공유해 view/token 조립이 갈라지지 않게 한다.
        """
        return CurrentViewResponse(
            view_status=view.view_status,
            configuration_status=view.configuration_status,
            context_error=view.context_error,
            context_error_message=(
                _CONTEXT_ERROR_MESSAGES.get(view.context_error, _CONTEXT_ERROR_FALLBACK)
                if view.context_error is not None
                else None
            ),
            new_configuration_token=new_token,
            projection=view if view.view_status != CONTEXT_ERROR else None,
            blocking_items=view.blocking_items,
            informational_changes=view.informational_changes,
        )

    def _now(self) -> str:
        return self._clock().isoformat()


# NOT_APPLICABLE re-export 로 소비자(테스트·컨트롤러)가 상태 상수를 한 곳에서 참조.
__all__ = [
    "SlotConfigurationProduct",
    "SlotConfigurationProductError",
    "SlotConfigurationCommandResponse",
    "MutationOutcomeView",
    "CurrentViewResponse",
    "PresetApplyResponse",
    "LOCAL_ACTOR",
    "NOT_APPLICABLE",
]
