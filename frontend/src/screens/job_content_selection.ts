/* 「문서 만들기」 "포함할 내용" zone (SX-02 #725) — S4 Working Slot Configuration 소비 표면.
 *
 * 이 파일은 렌더/마운트를 진다: `createSlotConfigService`(순수 상태·4 dispatch 왕복)를 job 화면
 * React composition(product_screens.ts JobScreen)에 잇고, backend projection 을 사용자 어휘로
 * 그린다. 새 shell/screen id/React root/navigation 을 만들지 않는다 — 기존 JobScreen subtree 에
 * zone 하나를 더한다.
 *
 * 경계(#725 · #744):
 *   - **render/mount 는 durable write 0**: 컴포넌트는 mount 에서 open()/refresh() 를 부르지 않는다.
 *     초기 자료는 Python snapshot 의 `slot_configuration` **read-only** current view 에서 hydrate 한다
 *     (#744 write-on-read 를 UI effect 로 되살리지 않는다). 사용자 select 만 durable S4 command 다.
 *   - **local optimistic authority 0 / 재판정 0**: 선택은 backend fresh view 로 통째 교체(service 소유).
 *     컴포넌트는 projection 필드(slots·options·configuration_status·detached·blocking_items)를
 *     읽어 그리기만 한다 — Active Field·currentness·validity 를 계산하지 않는다(SX-03 소유).
 *   - **내부어 미노출**: display_text 만 그린다(slot_id/option_id 는 command 용 내부 key).
 */

import { createElement, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { JobScreenModel, ScreenRuntime } from "./runtime.ts";
import type {
  ProjectedSlot,
  SlotConfigService,
  SlotConfigState,
  SlotCurrentView,
  SlotZoneError,
} from "./job_slot_config.ts";

type Obj = Record<string, unknown>;
const h = (
  tag: string | ((props: any) => ReactNode),
  props: Obj | null,
  ...children: ReactNode[]
) => createElement(tag as any, props, ...children);

type SlotZoneSnapshot = { view: SlotCurrentView | null; error: SlotZoneError | null };

/* ── snapshot 의 slot_configuration zone → read-only current 사실 ─────────────────────────── */
function readSlotZone(full: unknown): SlotZoneSnapshot {
  const empty = { view: null, error: null };
  if (full === null || typeof full !== "object") return empty;
  const zone = (full as Obj).slot_configuration;
  if (zone === null || typeof zone !== "object") return empty;
  const z = zone as Obj;
  const error = z.error !== null && typeof z.error === "object"
    ? z.error as SlotZoneError
    : null;
  // 미초기화·미지원에는 view가 없지만, 실패 projection은 정상 빈 상태와 구분해 함께 운반한다.
  if (z.initialized !== true) return { view: null, error };
  const view = z.current_view;
  if (view === null || typeof view !== "object") return { view: null, error };
  return { view: view as SlotCurrentView, error };
}

/* ── controller — job model(read-only view)로 passive hydrate + command 위임 ────────────────── */
export type JobContentSelectionController = {
  subscribe(listener: () => void): () => void;
  getSnapshot(): SlotConfigState;
  selectOption(slotId: string, optionId: string): Promise<SlotConfigState>;
  clearSelection(slotId: string): Promise<SlotConfigState>;
  refresh(): Promise<SlotConfigState>;
};

export function createJobContentSelectionController(deps: {
  runtime: ScreenRuntime;
  service: SlotConfigService;
}): JobContentSelectionController {
  const model = deps.runtime.model<JobScreenModel>("job");
  // pending 중 도착해 건너뛴 스냅샷이 있었는지 — settle 뒤 최신 model 로 재hydrate 하기 위한 표식.
  let skippedWhilePending = false;

  function hydrateFromModel(preserveNotice = false): void {
    // 진행 중 command(pending)은 authoritative round-trip 이 소유 — passive snapshot 이 덮지 않는다.
    // 다만 그 사이 도착한 스냅샷(Work 전환·Template 갱신)을 통째로 버리면, 옛 command 응답이
    // 커밋된 뒤 새 Work 의 slot view·token 이 영영 반영되지 않아 다음 선택이 옛 token 으로 새
    // Work 를 건드린다(#725 리뷰 P2). 그래서 건너뛴 사실을 남겨 settle 뒤 재hydrate 한다.
    if (deps.service.state().phase === "pending") {
      skippedWhilePending = true;
      return;
    }
    skippedWhilePending = false; // 실제 hydrate → 최신 model 을 반영하므로 밀린 delivery 없음.
    const snap = model.getSnapshot();
    const zone = readSlotZone(snap ? snap.full : null);
    deps.service.hydrate(zone.view, { zoneError: zone.error, preserveNotice });
  }

  // job 스냅샷 변화(최초 로드·Template 변경·command 뒤 재푸시)마다 read-only view 를 재hydrate 한다.
  // 모듈 싱글턴 수명이라 해제하지 않는다(다른 job 화면 controller 와 동일 규율).
  model.subscribe(hydrateFromModel);
  // 서비스 상태 전이 감시 — 어느 settle 이든 건너뛴 최신 model을 채택한다. stale/error는 command
  // notice만 보존하고 view/token/error projection은 latest snapshot으로 바꾼다(#749).
  deps.service.subscribe(() => {
    const phase = deps.service.state().phase;
    if (skippedWhilePending && phase !== "pending") {
      // hydrate commit이 listener를 다시 부르므로 nested commit 전에 먼저 내린다.
      skippedWhilePending = false;
      hydrateFromModel(phase === "stale" || phase === "error");
    }
  });
  hydrateFromModel(); // 이미 도착한 스냅샷을 즉시 seed — mount 에서 open() 을 부르지 않기 위함.

  return {
    subscribe: deps.service.subscribe,
    getSnapshot: deps.service.state,
    selectOption: (slotId, optionId) => deps.service.selectOption(slotId, optionId),
    clearSelection: (slotId) => deps.service.clearSelection(slotId),
    refresh: async () => {
      try {
        // passive 실패 복구는 read-only full snapshot 재당김이다. Product refresh(ensure)는 쓰지 않는다.
        await deps.runtime.refresh("job");
        return deps.service.state();
      } catch (error) {
        return deps.service.reportFailure(error);
      }
    },
  };
}

/* ── 표현 파생(재판정 0 — backend status/kind 를 사용자 어휘로 사상만 한다) ───────────────────── */
type SlotAttention = { label: string; selectable: boolean };

/** backend blocking kind → 정직한 사유 문안 + 사용자가 재선택으로 고칠 수 있는지(#725 리뷰 P2).
 *  NO_AVAILABLE_OPTIONS(고를 게 없음)·UNSUPPORTED_SELECTION_POLICY(현재 방식에서 선택 불가)는
 *  재선택이 불가능하다 — "다시 선택"으로 오안내하지 않고 선택 자체를 비활성화한다(무동작 no-op 방지). */
function attentionForKind(kind: string): SlotAttention {
  switch (kind) {
    case "MISSING_REQUIRED_SELECTION":
      return { label: "선택이 필요합니다", selectable: true };
    case "NO_AVAILABLE_OPTIONS":
      return { label: "선택할 수 있는 항목이 없습니다", selectable: false };
    case "UNSUPPORTED_SELECTION_POLICY":
      return { label: "이 항목은 현재 방식에서 선택할 수 없습니다", selectable: false };
    default: // SELECTED_OPTION_REMOVED · CARDINALITY_VIOLATION 등 재선택으로 고칠 수 있는 것.
      return { label: "다시 선택해야 합니다", selectable: true };
  }
}

/** slot_id → 이 Slot 의 행동 사유·선택 가능 여부(backend blocking_items.kind 소비). */
function blockingBySlot(view: SlotCurrentView | null): Map<string, SlotAttention> {
  const out = new Map<string, SlotAttention>();
  const items = view?.projection?.blocking_items ?? [];
  for (const item of items) {
    if (out.has(item.slot_id)) continue; // Slot 당 첫 사유만.
    out.set(item.slot_id, attentionForKind(item.kind));
  }
  return out;
}

/** 상단 상태 한 줄 — phase(왕복)와 configuration_status(backend 판정)를 그대로 사상. */
function statusLine(state: SlotConfigState): { kind: string; text: string } | null {
  if (state.phase === "error") {
    return { kind: "error", text: state.error ?? "오류가 발생했습니다" };
  }
  if (state.phase === "pending") {
    return { kind: "pending", text: "선택 반영 중…" };
  }
  if (state.phase === "stale") {
    return { kind: "stale", text: "설정이 갱신되어 최신 내용을 다시 불러왔습니다" };
  }
  const status = state.view?.projection?.configuration_status;
  if (status === "NEEDS_SELECTION") {
    return { kind: "needs", text: "선택이 필요한 항목이 있습니다" };
  }
  if (status === "HAS_BROKEN_SELECTIONS") {
    return { kind: "broken", text: "다시 선택해야 하는 항목이 있습니다" };
  }
  return null;
}

/* ── slot 하나 → fieldset/legend + native radio(EXACTLY_ONE) ────────────────────────────────── */
function SlotFieldset(props: {
  slot: ProjectedSlot;
  slotIndex: number;
  attention: SlotAttention | undefined;
  pending: boolean;
  onSelect: (slotId: string, optionId: string) => void;
}): ReactNode {
  const { slot, slotIndex, attention, pending } = props;
  // DOM id/name 은 render-local index 로만 만든다 — slot_id/option_id 는 임의 문자열이라 이어붙이면
  // 충돌한다("a-b"+"c" == "a"+"b-c"). index 는 injective 라 htmlFor 가 엉뚱한 radio 를 가리키지 않는다.
  const groupName = `cs-slot-${slotIndex}`;
  // 재선택으로 고칠 수 없는 kind(고를 게 없음·현재 방식 미지원)는 선택을 비활성화한다(무동작 no-op 방지).
  const disabled = pending || attention?.selectable === false;
  return h(
    "fieldset",
    { className: `cs-slot${attention !== undefined ? " cs-slot-attention" : ""}` },
    h("legend", { className: "cs-slot-legend" }, slot.display_text),
    attention !== undefined
      ? h("p", { className: "cs-slot-note", role: "note" }, attention.label)
      : null,
    h(
      "div",
      { className: "cs-options" },
      ...slot.options.map((opt, optIndex) => {
        const inputId = `cs-opt-${slotIndex}-${optIndex}`;
        return h(
          "label",
          { key: opt.option_id, className: "cs-option", htmlFor: inputId },
          h("input", {
            type: "radio",
            id: inputId,
            name: groupName,
            className: "cs-option-input",
            checked: opt.effective,
            disabled,
            // 선택 자체를 로컬에서 켜지 않는다 — backend command 로만 반영(local optimistic 0).
            onChange: () => props.onSelect(slot.slot_id, opt.option_id),
          }),
          h("span", { className: "cs-option-text" }, opt.display_text),
        );
      }),
    ),
  );
}

/* ── zone 컴포넌트 — JobScreen composition 이 마운트한다 ─────────────────────────────────────── */
export function JobContentSelection(props: {
  controller: JobContentSelectionController;
}): ReactNode {
  const { controller } = props;
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );

  const projection = state.view?.projection ?? null;
  const status = statusLine(state);
  const pending = state.phase === "pending";
  const backendError = state.zoneError?.message ?? state.view?.context_error_message ?? null;
  const statusNode = status === null
    ? null
    : h(
        "p",
        {
          className: `cs-status cs-status-${status.kind}`,
          role: status.kind === "error" ? "alert" : "status",
          "aria-live": "polite",
        },
        status.text,
      );
  const backendErrorNode = backendError === null || backendError === status?.text
    ? null
    : h("p", { className: "cs-status cs-status-error", role: "alert" }, backendError);
  const recoveryNode = state.zoneError?.action?.key === "refresh"
    ? h(
        "button",
        {
          type: "button",
          className: "btn",
          disabled: pending,
          onClick: () => { void controller.refresh(); },
        },
        state.zoneError.action.label,
      )
    : null;

  // view 부재(미지원·미초기화 zone)면 이 zone 은 적용 대상이 아니다 — 조용히 비운다(빈칸 누수 0).
  if (projection === null) {
    if (statusNode === null && backendErrorNode === null) return null;
    return h(
      "section",
      { className: "content-selection", "aria-label": "포함할 내용" },
      h("h2", { className: "cs-title" }, "포함할 내용"),
      statusNode,
      backendErrorNode,
      recoveryNode,
    );
  }

  const attention = blockingBySlot(state.view);
  const detached = projection.detached_selections;
  const clearableDetached = detached.filter((d) => d.clearable);

  return h(
    "section",
    { className: "content-selection", "aria-label": "포함할 내용", "aria-busy": pending },
    h("h2", { className: "cs-title" }, "포함할 내용"),
    statusNode,
    backendErrorNode,
    projection.slots.length === 0
      ? h("p", { className: "cs-empty" }, "이 문서 작업에는 선택할 내용이 없습니다.")
      : h(
          "div",
          { className: "cs-slots" },
          ...projection.slots.map((slot, slotIndex) =>
            h(SlotFieldset as any, {
              key: slot.slot_id,
              slot,
              slotIndex,
              attention: attention.get(slot.slot_id),
              pending,
              onSelect: controller.selectOption,
            }),
          ),
        ),
    // detached = 사라졌지만 의도로 보존된 이전 선택 — 현재 포함 내용처럼 표시하지 않고, 사용자
    // label 이 없는 내부 key 를 노출하지 않으며, 정직한 일반 문안으로 informational 분리한다(#725 §3).
    // detached 는 label 이 없어 개별 구분이 안 된다 — 항목별 버튼은 어느 선택을 지우는지 모호하다
    // (#725 리뷰). 그래서 clearable 전체를 지우는 **단일 명시 액션** 하나만 둔다. 두지 않으면 그
    // slot 재등장 시 backend 가 옛 선택을 자동 복원해 사용자 모르게 반영된다(조용히 틀리지 않는다).
    detached.length > 0
      ? h(
          "aside",
          { className: "cs-detached", "aria-label": "현재 문서와 분리된 이전 선택" },
          h(
            "p",
            { className: "cs-detached-note" },
            "이전 템플릿에서 유지된 선택이 있으나 현재 문서에는 적용되지 않습니다.",
          ),
          clearableDetached.length > 0
            ? h(
                "button",
                {
                  type: "button",
                  className: "cs-detached-clear",
                  disabled: pending,
                  // clearable 을 순차로 지운다 — 각 command 뒤 token 이 갱신되므로 await 로 직렬화한다
                  // (동기 다발 발사는 2번째부터 옛 token 을 써 거절된다). slot_id 는 command 용 내부
                  // key 로만 쓰고 화면 텍스트로 노출하지 않는다.
                  onClick: async () => {
                    for (const d of clearableDetached) {
                      await controller.clearSelection(d.slot_id);
                    }
                  },
                },
                "이전 선택 모두 제거",
              )
            : null,
        )
      : null,
  );
}
