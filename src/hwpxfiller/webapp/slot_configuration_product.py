"""S4 Slot Configuration Product API (S4-09 · #679).

durable workspace identity, route-bound expected Work, restart-verifiable **HMAC-signed** token,
fresh current view 를 잇는다. token 은 권한이나 요청 대상 Work 를 대신하지 않는다 — route 가 정한
expected Work 와 token 이 담은 Work 를 **독립 비교**해 다르면 CROSS_WORK 로 거절한다.

배치: pure token codec/claims 는 application(`slot_token`), secret provider·store 어댑터는 external,
이 Product API 는 webapp(work_ref·actor 해석 + 응답 조립)이다. #677 command engine 과 #678 projection
을 소비하고 새 token 을 발급한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..application.jobs import (
    JobStorePort,
    assign_job_authority_id,
    load_job,
)
from ..application.slot_command import (
    STALE_CONFIGURATION,
    STALE_TEMPLATE_APPLICATION,
    ConfigurationCommandContext,
)
from ..application.slot_configuration_context import (
    SlotConfigurationContextError,
    resolve_slot_configuration_context,
)
from ..application.slot_configuration_projection import (
    CONTEXT_ERROR,
    NOT_APPLICABLE,
    CurrentSlotConfigurationView,
    project_context_error,
    project_current_slot_configuration,
)
from ..application.slot_reconciliation import resolve_slot_configuration
from ..domain.slot_selection import SlotSelectionSet
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
from ..external.qualification_store import QualificationObjectStore
from ..external.slot_command_runner import (
    SlotCommandResult,
    clear_slot_selection,
    ensure_current_slot_configuration,
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
    new_configuration_token: str | None
    projection: CurrentSlotConfigurationView | None
    blocking_items: tuple
    informational_changes: tuple


@dataclass(frozen=True)
class SlotConfigurationCommandResponse:
    mutation_outcome: MutationOutcomeView | None
    current_view: CurrentViewResponse
    refresh_required: bool


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
        으로 정직하게 표시하고 새 config 를 만들지 않는다. token 은 발급하되(편집 진입 seam) slot
        config 를 저장하지 않으므로 basis 변경도 없다(``_maybe_auto_check`` 진입 근거를 만들지 않는다).
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

    def clear_slot_selection(
        self, work_ref: str, configuration_token: str, slot_id: str, request_id: str
    ) -> SlotConfigurationCommandResponse:
        work_id, ws = self._route(work_ref)
        claims = self._verify_token(configuration_token, ws, work_id)
        return self._run(work_id, ws, token_app=claims.template_application_id, mutating=True, call=lambda: (
            clear_slot_selection(
                self._configs, self._works, self._quals, self._candidates,
                context=self._command_context(ws, work_id, claims),
                request_id=request_id, slot_id=slot_id, now=self._now(),
            )
        ))

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
            current_view=CurrentViewResponse(
                view_status=view.view_status, configuration_status=view.configuration_status,
                context_error=view.context_error, new_configuration_token=None,
                projection=None, blocking_items=view.blocking_items,
                informational_changes=view.informational_changes,
            ),
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
        work_id = job.authority_id or assign_job_authority_id(
            self._registry, work_ref, uuid.uuid4().hex
        ).authority_id
        assert work_id is not None
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
            config = None
            if self._configs.exists(work_id):
                for cfg in self._configs.load(work_id).configurations.configurations:
                    if cfg.base_template_application_id == ctx.template_application_id:
                        config = cfg
                        break
            selections = config.selections if config is not None else SlotSelectionSet(())
            resolution = resolve_slot_configuration(
                selections, ctx.template_structure, ctx.selection_semantic_contract
            )
            view = project_current_slot_configuration(ctx, config, resolution)
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
    "LOCAL_ACTOR",
    "NOT_APPLICABLE",
]
