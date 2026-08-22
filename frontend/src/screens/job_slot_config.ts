/* S4 Working Slot Configuration 패널 서비스(SX-02 #725) — 「문서 만들기」 content 선택 표면.
 *
 * 신설 격리 파일이다(SX-03/04·job_run.ts 라인 충돌 회피). DOM 배선·셸 통합은 이 파일이 지지
 * 않는다 — 순수 상태 reducer + 4개 dispatch 왕복만 소유하고, 렌더·마운트는 소비 슬라이스가 잇는다.
 *
 * 계약(#725 §2·§3):
 *   - **local optimistic authority 0**: 사용자가 Option 을 누르면 로컬에서 선택을 미리 켜지 않는다.
 *     응답 전에는 phase='pending'(반영 중)만 세우고, 응답이 오면 backend fresh view 로 상태를 **통째
 *     교체**한다(재판정 0 — projection 이 이미 낸 값을 읽기만 한다).
 *   - **command 실패를 성공 UI 뒤에 숨기지 않는다**: 예외·거절은 phase='error' + 사유로 시끄럽게.
 *   - **stale 복구(§4 D)**: 응답의 refresh_required 를 소비해 phase='stale' 로 알리고, 되받은 fresh
 *     current view 로 교체한다(옛 Application 유령 반영 0).
 *   - **configuration_token 왕복**: 매 응답의 new_configuration_token 을 보관해 다음 mutation 에
 *     되돌려준다(프런트가 token 을 짓지 않는다 — opaque).
 *   - **Active Field 계산 0 / 내부어 노출 0**: Slot/Plan 판정을 재구현하지 않고 backend projection
 *     필드(slots·detached_selections·blocking_items·configuration_status)를 shape 만 한다.
 */

import type { BridgeClient } from "../runtime/client.ts";
import type { HostResult } from "../runtime/adapter.ts";
import { expectHostValue } from "./runtime.ts";

/* ── backend Product 응답 shape(Python SlotConfigurationProduct asdict) — 소비 필드만 형태화 ── */
export type ProjectedOption = {
  option_id: string;
  display_text: string;
  selected: boolean;
  effective: boolean;
  structurally_associated_field_ids: string[];
};

export type ProjectedSlot = {
  slot_id: string;
  display_text: string;
  selection_policy: string | null;
  status: string;
  declared_option_ids: string[];
  effective_option_ids: string[];
  options: ProjectedOption[];
  shared_field_ids: string[];
};

export type ProjectedDetachedSelection = {
  slot_id: string;
  selected_option_ids: string[];
  clearable: boolean;
  status: string;
};

/** 이전에 고른 것이 successor 에서 어떻게 됐는지 — 판정은 backend, 문안만 여기(#777). */
export type ProjectedRetainedSelection = {
  slot_id: string;
  slot_display_text: string | null;
  option_ids: string[];
  option_display_texts: (string | null)[];
  fate: string;
};

export type SlotProjection = {
  view_status: string;
  configuration_status: string;
  configuration_present: boolean;
  slots: ProjectedSlot[];
  detached_selections: ProjectedDetachedSelection[];
  blocking_items: { slot_id: string; kind: string; option_id: string | null }[];
  informational_changes: { slot_id: string; kind: string; option_id: string | null }[];
  retained_selections?: ProjectedRetainedSelection[];
};

export type SlotCurrentView = {
  view_status: string;
  configuration_status: string;
  context_error: string | null;
  context_error_message: string | null;
  new_configuration_token: string | null;
  projection: SlotProjection | null;
};

export type SlotCommandResponse = {
  mutation_outcome:
    | { outcome_code: string; changed: boolean; outcome_replayed: boolean; request_relation: string }
    | null;
  current_view: SlotCurrentView;
  refresh_required: boolean;
};

/** snapshot read 실패 projection — 의미·문안·복구 행동은 backend가 정하고 웹은 운반만 한다. */
export type SlotZoneError = {
  code: string;
  message: string;
  action: { key: string; label: string } | null;
};

/** 패널 phase — backend 상태를 재판정하지 않고 **왕복 진행**만 표현한다(#725 §3). */
export type SlotPhase = "idle" | "pending" | "stale" | "error";

export type SlotConfigState = {
  view: SlotCurrentView | null;
  token: string | null;
  phase: SlotPhase;
  /** phase='error' 일 때의 사유(조용한 거절 금지). */
  error: string | null;
  /** 최신 backend snapshot의 zone 실패. command notice와 별도 축으로 보존한다. */
  zoneError: SlotZoneError | null;
};

export const initialSlotConfigState: SlotConfigState = {
  view: null,
  token: null,
  phase: "idle",
  error: null,
  zoneError: null,
};

/* ── backend fresh view 로 **통째 교체**(local optimistic authority 0) ────────────────────── */
function replaceFromResponse(res: SlotCommandResponse): SlotConfigState {
  const view = res.current_view;
  // refresh_required(옛 Application stale) → 'stale' 로 알린다. context error → 'error'.
  const phase: SlotPhase =
    view.view_status === "CONTEXT_ERROR"
      ? "error"
      : res.refresh_required
        ? "stale"
        : "idle";
  return {
    view,
    // token 은 backend 가 낸 새 값으로만 갱신한다(없으면 유지하지 않는다 — 무효 상태를 시끄럽게).
    token: view.new_configuration_token,
    phase,
    error: view.context_error_message,
    zoneError: null,
  };
}

/* ── 표현 파생(재판정 0 — projection 필드를 읽기만 한다) ───────────────────────────────────── */
export function currentProjection(state: SlotConfigState): SlotProjection | null {
  return state.view?.projection ?? null;
}

/** 선택 필요(필수 Slot 미선택) — configuration_status 를 그대로 읽는다(웹이 재판정하지 않는다). */
export function needsSelection(state: SlotConfigState): boolean {
  return currentProjection(state)?.configuration_status === "NEEDS_SELECTION";
}

/** 다시 결정 필요(broken 선택) — 마찬가지로 backend status 소비. */
export function hasBrokenSelections(state: SlotConfigState): boolean {
  return currentProjection(state)?.configuration_status === "HAS_BROKEN_SELECTIONS";
}

/** 사라졌지만 의도로 보존됨(detached informational) — **현재 포함 내용처럼 표시하지 않는다**(#725 §3).
 *  호출자는 이 목록을 별도 informational 영역에 그린다(현재 선택 목록과 섞지 않는다). */
export function detachedSelections(state: SlotConfigState): ProjectedDetachedSelection[] {
  return currentProjection(state)?.detached_selections ?? [];
}

/* ── request_id 발급(프런트 소유 재전송 단위) ─────────────────────────────────────────────── */
function makeRequestId(): string {
  return `slot-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export type SlotConfigService = {
  open(): Promise<SlotConfigState>;
  refresh(): Promise<SlotConfigState>;
  selectOption(slotId: string, optionId: string): Promise<SlotConfigState>;
  clearSelection(slotId: string): Promise<SlotConfigState>;
  /** 마지막 커밋 상태(구독 렌더가 참조). `useSyncExternalStore` 의 getSnapshot 으로도 쓴다. */
  state(): SlotConfigState;
  /** React 구독(수명주기 인터페이스) — 상태 커밋마다 listener 를 부른다. semantic 아님. */
  subscribe(listener: () => void): () => void;
  /** passive render 초기 자료 seed — snapshot 의 read-only current view 를 dispatch 없이 실는다.
   *  #744 write-on-read 방지: mount 는 open() 을 부르지 않고 이 read-only view 로 hydrate 한다.
   *  view=null(미지원/미초기화) → 빈 idle. command 축(pending)을 덮지 않도록 호출자가 게이트한다. */
  hydrate(
    view: SlotCurrentView | null,
    options?: { zoneError?: SlotZoneError | null; preserveNotice?: boolean },
  ): SlotConfigState;
  /** snapshot 재당김 transport 실패를 기존 loud 채널과 상태에 함께 남긴다. */
  reportFailure(error: unknown): SlotConfigState;
};

export type SlotConfigDeps = {
  client: BridgeClient;
  /** 상태 전이 알림(pending·완료·error) — 호출자 렌더 채널. */
  onChange?: (state: SlotConfigState) => void;
  /** loud 실패 채널 — 예외를 조용히 삼키지 않는다. */
  alarm?: (message: string) => void;
};

/** 패널 서비스 factory — 상태를 든 4개 dispatch 왕복. token 은 서비스가 보관하고 되돌려준다. */
export function createSlotConfigService(deps: SlotConfigDeps): SlotConfigService {
  let current: SlotConfigState = initialSlotConfigState;
  const listeners = new Set<() => void>();

  function commit(next: SlotConfigState): SlotConfigState {
    current = next;
    deps.onChange?.(current);
    for (const listener of [...listeners]) listener();
    return current;
  }

  function requireToken(): string {
    if (current.token === null || current.token === "") {
      // token 이 없으면 mutation 을 보낼 수 없다 — 조용히 무동작하지 않고 시끄럽게 open 을 요구한다.
      throw new Error("configuration_token 이 없습니다 — 먼저 구성을 열어야 합니다");
    }
    return current.token;
  }

  function reportFailure(error: unknown): SlotConfigState {
    const message = String((error as { message?: unknown })?.message ?? error);
    deps.alarm?.(message);
    return commit({ ...current, phase: "error", error: message });
  }

  // dispatch 는 화면×액션별 exact payload 타입을 요구하므로(생성 계약 SCREEN_ACTIONS), 각 왕복은
  // literal action 으로 호출부에서 부른다. 공통(pending 세움·fresh view 교체·loud error)만 여기 모은다.
  async function apply(
    label: string,
    call: () => Promise<HostResult>,
    { pending }: { pending: boolean },
  ): Promise<SlotConfigState> {
    if (pending) {
      // 응답 전 '반영 중'만 세운다 — 선택 자체를 로컬에서 미리 켜지 않는다(local optimistic 0).
      commit({ ...current, phase: "pending", error: null });
    }
    try {
      const raw = expectHostValue(await call(), label);
      return commit(replaceFromResponse(raw as SlotCommandResponse));
    } catch (error) {
      // 실패를 성공 UI 뒤에 숨기지 않는다 — 상태는 view 를 보존하되 phase='error' + 사유.
      return reportFailure(error);
    }
  }

  return {
    open() {
      return apply(
        "open_slot_configuration",
        () => deps.client.dispatch("job", "open_slot_configuration", {}),
        { pending: false },
      );
    },
    refresh() {
      // 보관 token 을 되돌려 stale 여부 판정을 backend 에 맡긴다(없으면 최초 조회).
      const token = current.token;
      return apply(
        "refresh_slot_configuration",
        () =>
          token
            ? deps.client.dispatch("job", "refresh_slot_configuration", {
                configuration_token: token,
              })
            : deps.client.dispatch("job", "refresh_slot_configuration", {}),
        { pending: false },
      );
    },
    selectOption(slotId, optionId) {
      const token = requireToken();
      return apply(
        "select_slot_option",
        () =>
          deps.client.dispatch("job", "select_slot_option", {
            configuration_token: token,
            slot_id: slotId,
            option_id: optionId,
            request_id: makeRequestId(),
          }),
        { pending: true },
      );
    },
    clearSelection(slotId) {
      const token = requireToken();
      return apply(
        "clear_slot_selection",
        () =>
          deps.client.dispatch("job", "clear_slot_selection", {
            configuration_token: token,
            slot_id: slotId,
            request_id: makeRequestId(),
          }),
        { pending: true },
      );
    },
    state() {
      return current;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    hydrate(view, options = {}) {
      const zoneError = options.zoneError ?? null;
      const isError = view?.view_status === "CONTEXT_ERROR" || zoneError !== null;
      const next: SlotConfigState = {
        view,
        token: view?.new_configuration_token ?? null,
        phase: isError ? "error" : "idle",
        error: view?.context_error_message ?? zoneError?.message ?? null,
        zoneError,
      };
      // replay는 최신 snapshot 사실(view/token/zoneError)을 채택하되 command notice를 지우지 않는다.
      if (options.preserveNotice && (current.phase === "stale" || current.phase === "error")) {
        next.phase = current.phase;
        next.error = current.error;
      }
      return commit(next);
    },
    reportFailure,
  };
}
