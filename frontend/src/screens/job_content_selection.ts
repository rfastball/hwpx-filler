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
 *     컴포넌트는 projection 필드(slots·options·configuration_status·retained·blocking_items)를
 *     읽어 그리기만 한다 — Active Field·currentness·validity 를 계산하지 않는다(SX-03 소유).
 *   - **내부어 미노출**: display_text 만 그린다(slot_id/option_id 는 command 용 내부 key).
 */

import { createElement, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { JobScreenModel, ScreenRuntime } from "./runtime.ts";
import { emptyPresetZone } from "./job_slot_config.ts";
import type {
  PresetNotice,
  PresetZone,
  ProjectedRetainedSelection,
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

/* ── snapshot 의 content_presets zone → 보관된 선택 묶음 목록(손상 포함) ────────────────── */
function readPresetZone(full: unknown): PresetZone {
  if (full === null || typeof full !== "object") return emptyPresetZone;
  const zone = (full as Obj).content_presets;
  if (zone === null || typeof zone !== "object") return emptyPresetZone;
  const z = zone as Obj;
  if (z.supported !== true) return emptyPresetZone;
  return {
    supported: true,
    // 노출 술어는 Python 이 낸다(U4 13번) — 목록 길이를 여기서 다시 세지 않는다.
    actionable: z.actionable === true,
    items: Array.isArray(z.items) ? (z.items as PresetZone["items"]) : [],
    // 손상 항목을 목록에서 지우지 않는다 — 표면이 비활성 + 사유 병기로 재진술한다.
    corrupt: Array.isArray(z.corrupt) ? (z.corrupt as PresetZone["corrupt"]) : [],
  };
}

/* ── controller — job model(read-only view)로 passive hydrate + command 위임 ────────────────── */
export type JobContentSelectionController = {
  subscribe(listener: () => void): () => void;
  getSnapshot(): SlotConfigState;
  selectOption(slotId: string, optionId: string): Promise<SlotConfigState>;
  refresh(): Promise<SlotConfigState>;
  /** 「현재 선택을 프리셋으로 저장」 — 이름 입력·덮어쓰기 확인 UI 는 이 컨트롤러가 소유하고
   *  (문안·확인 UI 는 웹), 충돌 판정·확정 근거(key)는 backend 가 낸 값을 그대로 되돌려준다. */
  savePreset(): Promise<SlotConfigState>;
  applyPreset(presetKey: string): Promise<SlotConfigState>;
};

/** 확인·입력 다이얼로그 포트(`overlay/modal.js` 파사드) — 다른 화면 컨트롤러와 같은 계약. */
export type ContentSelectionModalPort = {
  prompt(spec: Record<string, unknown>): Promise<string | null>;
  confirm(spec: Record<string, unknown>): Promise<boolean>;
};

export function createJobContentSelectionController(deps: {
  runtime: ScreenRuntime;
  service: SlotConfigService;
  modal?: ContentSelectionModalPort;
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
    const full = snap ? snap.full : null;
    const zone = readSlotZone(full);
    deps.service.hydrate(zone.view, {
      zoneError: zone.error,
      preserveNotice,
      presets: readPresetZone(full),
    });
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

  /** 이름 입력 → 저장 → (이름 충돌이면) 덮어쓰기 확인 → 확정 저장. **조용한 덮기 경로 0**.
   *
   *  판정은 전부 backend 다(빈 선택 거절·이름 충돌·확정 근거 대조). 여기가 소유하는 것은
   *  문안과 확인 UI 뿐이고, 확정은 backend 가 낸 **그 항목의 key** 를 되돌려 보낸다 — 이름만
   *  다시 보내면 그 사이 다른 항목이 그 이름을 차지했을 때 남의 것을 덮는다. */
  async function savePreset(): Promise<SlotConfigState> {
    const modal = deps.modal;
    if (modal === undefined) {
      // 입력 창이 없으면 저장하지 않는다 — 이름 없는 보관을 지어내지 않고 시끄럽게 알린다.
      return deps.service.reportFailure(
        new Error("이름 입력 창을 열 수 없어 저장하지 않았습니다."),
      );
    }
    const typed = await modal.prompt({
      title: "프리셋으로 저장",
      body: "지금 고른 내용을 어떤 이름으로 보관할까요?",
      validate: (raw: unknown) =>
        String(raw ?? "").trim() === "" ? "이름을 입력하세요." : "",
    });
    if (typed === null) return deps.service.state(); // 취소 = 아무 일도 하지 않는다
    const name = typed.trim();
    if (name === "") return deps.service.state();
    const after = await deps.service.savePreset(name);
    const notice = after.presetNotice;
    if (notice === null || notice.kind !== "save_conflict") return after;
    const accepted = await modal.confirm({
      title: "같은 이름이 이미 있습니다",
      body:
        `'${notice.name}' 이름의 프리셋이 이미 있습니다.\n`
        + "덮어쓰면 그 프리셋에 보관된 이전 선택은 사라지고 되돌릴 수 없습니다.",
      confirmLabel: "덮어쓰기",
      cancelLabel: "취소",
      danger: true,
    });
    if (!accepted) return deps.service.state();
    if (notice.existingKey === null) {
      // 확인 왕복 사이에 그 항목이 사라졌다(backend 가 근거를 못 냈다) — 지금 상태로 다시
      // 시도하고, 여전히 충돌이면 또 묻는다. 근거 없는 확정으로 덮지 않는다.
      return deps.service.savePreset(name);
    }
    return deps.service.savePreset(name, notice.existingKey);
  }

  return {
    subscribe: deps.service.subscribe,
    getSnapshot: deps.service.state,
    selectOption: (slotId, optionId) => deps.service.selectOption(slotId, optionId),
    savePreset,
    applyPreset: (presetKey) => deps.service.applyPreset(presetKey),
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

/** 이전에 고른 것의 운명 → 사용자 문안. **판정은 backend 가 이미 했다**(fate) — 여기는 문장만 고른다.
 *
 *  이전에 고른 Option 의 **이름을 대지 않는다**. 남아 있는 것은 같은 ID 뿐이고 그 ID 의 현재
 *  라벨은 이전 라벨이 아니다 — successor 가 같은 ID 를 다른 뜻으로 다시 쓴 경우(compatibility
 *  gate 가 의미 동일성 증명을 거절한 바로 그 경우) 현재 라벨을 「이전에 고르신 것」이라 부르면
 *  없는 역사를 지어낸다. Slot 은 지금 있는 것이므로 그 자리에서 말하는 것으로 족하다.
 *
 *  「유지됩니다」라고도 쓰지 않는다: Template 이 바뀌면 자동 승계되지 않고 사용자가 다시 확인해야
 *  한다(SG-01 fail-closed). 있는 것을 「이어졌다」고 말하면 그것이 곧 새 거짓말이다. */
function retainedNoteText(retained: ProjectedRetainedSelection): string {
  const count = retained.option_ids.length;
  switch (retained.fate) {
    case "SELECTED_OPTION_REMOVED":
      return "이전에 이 항목에서 고르신 것이 이 템플릿에는 없습니다. 다른 것을 골라 주세요.";
    case "NO_AVAILABLE_OPTIONS":
    case "UNSUPPORTED_SELECTION_POLICY":
      // 고를 수 있는 것이 없다 — 여기서 「다시 고르세요」는 할 수 없는 일을 시키는 문안이다.
      return "이전에 이 항목에서 고르신 것이 있으나, 이 템플릿에서는 선택할 수 없습니다.";
    default:
      return `이전에 이 항목에서 ${count}개를 고르셨습니다. 템플릿이 바뀌어 다시 확인이 필요합니다.`;
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

/** 상단 상태 한 줄 — phase(왕복)와 configuration_status(backend 판정)를 그대로 사상.
 *
 * ``pending`` 은 **줄을 세우지 않는다**(U4 계열1-26). 한 번의 선택에서 이 줄이 섰다가
 * 다시 사라지면 구획 높이가 두 번 튀어 「접혔다 깜빡인다」로 보인다 — 그 사이 실제로 바뀐
 * 것은 아무것도 없다. 왕복 중이라는 사실은 레이아웃을 안 건드리는 두 채널이 이미 말한다:
 * 구획의 ``aria-busy`` 와 비활성된 radio. 진짜 상태 전이(error·stale·needs·broken)만
 * 줄을 세우므로 남는 높이 변화는 **정말 바뀐 것**뿐이다.
 */
function statusLine(state: SlotConfigState): { kind: string; text: string } | null {
  if (state.phase === "error") {
    return { kind: "error", text: state.error ?? "오류가 발생했습니다" };
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
  retained: ProjectedRetainedSelection | undefined;
  pending: boolean;
  onSelect: (slotId: string, optionId: string) => void;
}): ReactNode {
  const { slot, slotIndex, attention, retained, pending } = props;
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
    // 이전에 고른 것의 운명 — 판정(fate)은 backend 가 이미 내렸고 여기는 문안만 고른다(#777).
    // 라벨이 없으면 이름 대신 개수로 말한다: 내부 key 를 사용자에게 보이지 않는다.
    retained !== undefined
      ? h(
          "p",
          { className: "cs-retained-note", "data-fate": retained.fate, role: "note" },
          retainedNoteText(retained),
        )
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

/* ── 보관된 선택 묶음(Preset) 구획 — 저장·적용 두 동사(S9-03 #829) ───────────────────────── */

/** preset 왕복 결과 → 사용자 문장. **수치는 응답 값 그대로**이고 여기는 문장만 고른다.
 *
 *  거절 코드에 문안을 붙이는 이유: backend 의 `detail` 은 사실 서술(파일 경로·예외 문자열)이라
 *  그대로 그리면 내부어가 샌다. 아는 코드는 사용자 어휘로 말하고, 모르는 코드는 backend 가 낸
 *  사유를 그대로 재진술한다 — 어느 쪽도 조용히 삼키지 않는다. */
function presetNoticeText(notice: PresetNotice): { kind: string; text: string } {
  switch (notice.kind) {
    case "saved":
      return { kind: "saved", text: `'${notice.name}' 이름으로 보관했습니다.` };
    case "save_conflict":
      return {
        kind: "conflict",
        text: `'${notice.name}' 이름의 프리셋이 이미 있어 저장하지 않았습니다.`,
      };
    case "save_rejected":
      return {
        kind: "rejected",
        text:
          notice.code === "PRESET_EMPTY_SELECTION"
            ? "고른 내용이 없어 저장하지 않았습니다. 먼저 포함할 내용을 고르세요."
            : (notice.detail ?? "프리셋을 저장하지 못했습니다."),
      };
    case "apply_rejected":
      return {
        kind: "rejected",
        text:
          notice.code === "PRESET_NOT_FOUND"
            ? "그 프리셋을 찾을 수 없습니다. 목록을 다시 확인하세요."
            : notice.code === "PRESET_ENTRY_CORRUPT"
              ? "그 프리셋을 읽을 수 없어 적용하지 않았습니다."
              : (notice.detail ?? "프리셋을 적용하지 못했습니다."),
      };
    default:
      // 적용 n · 깨짐 m — 깨진 것이 있으면 숨기지 않고 같은 줄에서 함께 말한다.
      return {
        kind: notice.broken > 0 ? "partial" : "applied",
        text:
          notice.broken > 0
            ? `${notice.applied}개를 적용했고 ${notice.broken}개는 현재 문서에 적용되지 않습니다.`
            : `${notice.applied}개를 적용했습니다.`,
      };
  }
}

function PresetSection(props: {
  presets: PresetZone;
  notice: PresetNotice | null;
  pending: boolean;
  onSave: () => void;
  onApply: (presetKey: string) => void;
}): ReactNode {
  const { presets, notice, pending } = props;
  const noticeLine = notice === null ? null : presetNoticeText(notice);
  return h(
    "section",
    { className: "cs-presets", "aria-label": "보관된 선택" },
    h("h3", { className: "cs-presets-title" }, "보관된 선택"),
    h(
      "button",
      {
        type: "button",
        className: "cs-preset-save",
        disabled: pending,
        onClick: props.onSave,
      },
      "현재 선택을 프리셋으로 저장",
    ),
    // 결과 재진술 — 깨짐이 있는 적용도 성공 UI 뒤에 숨지 않는다(같은 자리에서 시끄럽게).
    noticeLine === null
      ? null
      : h(
          "p",
          {
            className: `cs-preset-notice cs-preset-notice-${noticeLine.kind}`,
            role: noticeLine.kind === "rejected" ? "alert" : "status",
            "aria-live": "polite",
          },
          noticeLine.text,
        ),
    presets.items.length === 0 && presets.corrupt.length === 0
      ? h("p", { className: "cs-presets-empty" }, "보관된 선택이 아직 없습니다.")
      : h(
          "ul",
          { className: "cs-preset-list" },
          ...presets.items.map((item) =>
            h(
              "li",
              { key: item.key, className: "cs-preset-item" },
              h("span", { className: "cs-preset-name" }, item.name),
              h(
                "button",
                {
                  type: "button",
                  className: "cs-preset-apply",
                  disabled: pending,
                  onClick: () => props.onApply(item.key),
                },
                "적용",
              ),
            ),
          ),
          // 손상 항목은 목록에서 지우지 않는다 — 비활성 + 사유 병기(숨기면 사용자가 못 묻는다).
          ...presets.corrupt.map((entry) =>
            h(
              "li",
              { key: entry.file_name, className: "cs-preset-item cs-preset-corrupt" },
              h("span", { className: "cs-preset-name" }, "읽을 수 없는 프리셋"),
              h(
                "button",
                { type: "button", className: "cs-preset-apply", disabled: true },
                "적용",
              ),
              h(
                "span",
                { className: "cs-preset-corrupt-note" },
                "파일이 손상돼 적용할 수 없습니다.",
              ),
            ),
          ),
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

  // **노출 술어는 Python 이 낸다**(U4 13번). 고를 항목이 없으면 이 구획에는 사용자가 확인할
  // 것도 할 것도 없다 — slot 없는 작업에서 「선택할 내용이 없습니다」 한 줄로 영영 서 있던
  // 자리다. 여기서 `slots.length` 를 다시 세면 같은 상태를 두 곳이 판정하게 된다.
  //
  // 술어가 숨겨도 **시끄러운 재진술은 남는다**: 실패·stale 사유(`statusNode`·`backendErrorNode`)
  // 와 직전 preset 왕복 결과는 웹이 수명을 소유하는 채널이라(#659), 술어만으로 지우면 사용자가
  // 방금 겪은 거절이 화면에서 증발한다.
  if (
    projection.zone_actionable !== true
    && statusNode === null
    && backendErrorNode === null
    && state.presetNotice === null
  ) {
    return null;
  }

  const attention = blockingBySlot(state.view);
  const retained = projection.retained_selections ?? [];
  const retainedBySlot = new Map(
    retained.filter((r) => r.fate !== "SLOT_REMOVED").map((r) => [r.slot_id, r]),
  );
  const retainedGone = retained.filter((r) => r.fate === "SLOT_REMOVED");

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
              retained: retainedBySlot.get(slot.slot_id),
              pending,
              onSelect: controller.selectOption,
            }),
          ),
        ),
    // 항목 자체가 사라진 이전 선택 — blocking 이 아니라 정보다. 현재 구성의 일부가 아니고
    // 자동으로 되살아나지도 않는다. 이름을 댈 수 없으므로(현재 구조에 없다) 개수로만 말한다.
    retainedGone.length > 0
      ? h(
          "aside",
          { className: "cs-retained-gone", "aria-label": "이 템플릿에서 사라진 이전 선택" },
          h(
            "p",
            { className: "cs-retained-gone-note" },
            `이전에 고르신 항목 ${retainedGone.length}개가 이 템플릿에는 없습니다. 현재 문서에는 반영되지 않습니다.`,
          ),
        )
      : null,
    // 「이전 선택 모두 제거」(detached 정리 액션)는 #903 에서 제거됐다. 그것이 막던 사고 —
    // 사라진 Slot 이 다시 등장하면 backend 가 옛 선택을 같은 ID 라는 이유로 자동 복원하는 것 —
    // 은 SG-01(#733)이 compatibility gate 로 닫았고, 그 뒤로 승계 선언집합에는 target 에 있는
    // Option 만(AUTO_KEEP) 실린다. 그래서 detached 는 제품 경로에서 만들어지지 않고, 이전 선택의
    // 운명은 위 `cs-retained-gone` 이 정보로 재진술한다.
    // 보관된 선택(S9-03 #829) — slot 목록 아래에 선다. 목록·손상은 snapshot 존이 낸 사실이고
    // 적용 결과의 수치는 command 응답 값 그대로다(웹 재계산 0).
    // 보관된 선택 구획도 같은 규율이다(U4 13번): 보관·손상 항목이 있거나 **지금 저장할 선택이
    // 있을 때** 선다. 저장 동사를 목록 건수로 지우면 프리셋을 처음 만들 입구가 사라진다 —
    // #932 B5 가 템플릿 존에서 거절한 스위치 트랩이라 술어의 입력에 저장 게이트를 함께 넣었다.
    state.presets.supported && (state.presets.actionable || state.presetNotice !== null)
      ? h(PresetSection as any, {
          presets: state.presets,
          notice: state.presetNotice,
          pending,
          onSave: () => { void controller.savePreset(); },
          onApply: (presetKey: string) => { void controller.applyPreset(presetKey); },
        })
      : null,
  );
}
