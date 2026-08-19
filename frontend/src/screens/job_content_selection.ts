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
} from "./job_slot_config.ts";

type Obj = Record<string, unknown>;
const h = (
  tag: string | ((props: any) => ReactNode),
  props: Obj | null,
  ...children: ReactNode[]
) => createElement(tag as any, props, ...children);

/* ── snapshot 의 slot_configuration zone → read-only current view(없으면 null) ──────────────── */
function readSlotZone(full: unknown): SlotCurrentView | null {
  if (full === null || typeof full !== "object") return null;
  const zone = (full as Obj).slot_configuration;
  if (zone === null || typeof zone !== "object") return null;
  const z = zone as Obj;
  // 미초기화·미지원(템플릿 확인 전·비-hwpx·미주입)은 passive baseline 이 없다 — 빈 상태로 hydrate.
  if (z.initialized !== true) return null;
  const view = z.current_view;
  if (view === null || typeof view !== "object") return null;
  return view as SlotCurrentView;
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

  function hydrateFromModel(): void {
    // 진행 중 command(pending)은 authoritative round-trip 이 소유 — passive snapshot 이 덮지 않는다.
    // 그 밖(idle·stale·error)은 job 전체 스냅샷의 read-only view 가 최신 durable 사실이라 재hydrate.
    if (deps.service.state().phase === "pending") return;
    const snap = model.getSnapshot();
    deps.service.hydrate(readSlotZone(snap ? snap.full : null));
  }

  // job 스냅샷 변화(최초 로드·Template 변경·command 뒤 재푸시)마다 read-only view 를 재hydrate 한다.
  // 모듈 싱글턴 수명이라 해제하지 않는다(다른 job 화면 controller 와 동일 규율).
  model.subscribe(hydrateFromModel);
  hydrateFromModel(); // 이미 도착한 스냅샷을 즉시 seed — mount 에서 open() 을 부르지 않기 위함.

  return {
    subscribe: deps.service.subscribe,
    getSnapshot: deps.service.state,
    selectOption: (slotId, optionId) => deps.service.selectOption(slotId, optionId),
    clearSelection: (slotId) => deps.service.clearSelection(slotId),
    refresh: () => deps.service.refresh(),
  };
}

/* ── 표현 파생(재판정 0 — backend status/kind 를 사용자 어휘로 사상만 한다) ───────────────────── */
const _BROKEN_KIND_LABEL = "다시 선택해야 합니다";
const _MISSING_KIND_LABEL = "선택이 필요합니다";

/** slot_id → 이 Slot 이 행동 대상인 사유 문안(backend blocking_items.kind 소비). */
function blockingBySlot(view: SlotCurrentView | null): Map<string, string> {
  const out = new Map<string, string>();
  const items = view?.projection?.blocking_items ?? [];
  for (const item of items) {
    if (out.has(item.slot_id)) continue; // Slot 당 첫 사유만.
    out.set(
      item.slot_id,
      item.kind === "MISSING_REQUIRED_SELECTION" ? _MISSING_KIND_LABEL : _BROKEN_KIND_LABEL,
    );
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
  attention: string | undefined;
  pending: boolean;
  onSelect: (slotId: string, optionId: string) => void;
}): ReactNode {
  const { slot, attention, pending } = props;
  const groupName = `cs-slot-${slot.slot_id}`;
  return h(
    "fieldset",
    { className: `cs-slot${attention !== undefined ? " cs-slot-attention" : ""}` },
    h("legend", { className: "cs-slot-legend" }, slot.display_text),
    attention !== undefined
      ? h("p", { className: "cs-slot-note", role: "note" }, attention)
      : null,
    h(
      "div",
      { className: "cs-options" },
      ...slot.options.map((opt) => {
        const inputId = `cs-opt-${slot.slot_id}-${opt.option_id}`;
        return h(
          "label",
          { key: opt.option_id, className: "cs-option", htmlFor: inputId },
          h("input", {
            type: "radio",
            id: inputId,
            name: groupName,
            className: "cs-option-input",
            checked: opt.effective,
            disabled: pending,
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

  // view 부재(미지원·미초기화 zone)면 이 zone 은 적용 대상이 아니다 — 조용히 비운다(빈칸 누수 0).
  if (projection === null) {
    if (status?.kind === "error") {
      return h(
        "section",
        { className: "content-selection", "aria-label": "포함할 내용" },
        h("h2", { className: "cs-title" }, "포함할 내용"),
        h("p", { className: "cs-status cs-status-error", role: "alert" }, status.text),
      );
    }
    return null;
  }

  const attention = blockingBySlot(state.view);
  const detached = projection.detached_selections;

  return h(
    "section",
    { className: "content-selection", "aria-label": "포함할 내용", "aria-busy": pending },
    h("h2", { className: "cs-title" }, "포함할 내용"),
    status !== null
      ? h(
          "p",
          {
            className: `cs-status cs-status-${status.kind}`,
            role: status.kind === "error" ? "alert" : "status",
            "aria-live": "polite",
          },
          status.text,
        )
      : null,
    projection.slots.length === 0
      ? h("p", { className: "cs-empty" }, "이 문서 작업에는 선택할 내용이 없습니다.")
      : h(
          "div",
          { className: "cs-slots" },
          ...projection.slots.map((slot) =>
            h(SlotFieldset as any, {
              key: slot.slot_id,
              slot,
              attention: attention.get(slot.slot_id),
              pending,
              onSelect: controller.selectOption,
            }),
          ),
        ),
    // detached = 사라졌지만 의도로 보존된 이전 선택 — 현재 포함 내용처럼 표시하지 않고, 사용자
    // label 이 없는 내부 key 를 노출하지 않으며, 정직한 일반 문안으로 informational 분리한다(#725 §3).
    detached.length > 0
      ? h(
          "aside",
          { className: "cs-detached", "aria-label": "현재 문서와 분리된 이전 선택" },
          h(
            "p",
            { className: "cs-detached-note" },
            "이전 템플릿에서 유지된 선택이 있으나 현재 문서에는 적용되지 않습니다.",
          ),
        )
      : null,
  );
}
