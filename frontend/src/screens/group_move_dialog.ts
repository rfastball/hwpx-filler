/* R4-02 템플릿 그룹 이동 다이얼로그(`#tplMoveModal`)의 React 후계.

   legacy 는 `GroupList.createMoveDialog` 팩토리였다 — 소비자가 둘(작업 그룹·템플릿 그룹)이라
   id 를 cfg 로 받아 문자열로 조립했다. #414 가 작업 쪽 소비자를 React `LibraryMoveDialog` 로
   옮겼으므로 남은 소비자는 편집기 하나다: 여기서는 id 를 그대로 쓴다(간접이 지킬 것이 없다).

   지키는 계약 셋:

   - 목록 = 기존 그룹 + 「그룹 없음(해제)」 + 「새 그룹」(값 센티넬 충돌을 `data-new` 로 봉쇄).
   - 새 이름 입력을 만지면 새 그룹 라디오가 자동 선택된다(입력 = 의도).
   - 빈 새 이름은 **조용히 넘기지 않고** 모달을 연 채 인라인 재진술한다.

   그리고 순서 하나: 확정 mutation 은 모달이 **원 트리거로 초점을 되돌린 뒤에** 나간다(H-16).
   먼저 보내면 push 재렌더가 트리거를 파괴해 복귀가 body 로 추락한다. */
import { createElement, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = { open(id: string, spec?: Obj): void; close(id: string): void };

export type GroupMoveRequest = {
  nameText: string;
  groups: readonly string[];
  current: string;
  returnFocus?: HTMLElement | null;
  onConfirm(group: string): void | Promise<unknown>;
};

type State = {
  nameText: string;
  groups: readonly string[];
  choice: string;
  fresh: string;
  useFresh: boolean;
  error: string;
};

export function createGroupMoveDialog(deps: { modal: ModalPort }) {
  let state: State | null = null;
  let request: GroupMoveRequest | null = null;
  let confirmed: { group: string } | null = null;
  const listeners = new Set<Listener>();

  function emit(): void {
    for (const listener of [...listeners]) listener();
  }

  function open(next: GroupMoveRequest): void {
    request = next;
    confirmed = null;
    state = {
      nameText: next.nameText,
      groups: next.groups,
      choice: next.current,
      fresh: "",
      useFresh: false,
      error: "",
    };
    emit();
    deps.modal.open("tplMoveModal", {
      returnFocus: next.returnFocus || null,
      onClose: () => {
        const pending = request;
        const accepted = confirmed;
        request = null;
        confirmed = null;
        state = null;
        emit();
        /* 초점이 돌아간 **뒤**에만 변이를 보낸다 — 순서가 계약이다. */
        if (accepted !== null && pending !== null) void pending.onConfirm(accepted.group);
      },
    });
  }

  function patch(next: Partial<State>): void {
    if (state === null) return;
    state = { ...state, ...next };
    emit();
  }

  function confirm(): void {
    if (state === null) return;
    const group = state.useFresh ? state.fresh.trim() : state.choice;
    if (state.useFresh && group === "") {
      patch({ error: "새 그룹 이름이 비어 있습니다. 이름을 넣거나 다른 항목을 고르세요." });
      return;
    }
    confirmed = { group };
    deps.modal.close("tplMoveModal");
  }

  return {
    open,
    patch,
    confirm,
    cancel(): void { deps.modal.close("tplMoveModal"); },
    model: {
      getSnapshot: (): State | null => state,
      subscribe(listener: Listener): () => void {
        listeners.add(listener);
        return () => { listeners.delete(listener); };
      },
    },
  };
}

export type GroupMoveDialogController = ReturnType<typeof createGroupMoveDialog>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

export function GroupMoveDialog(props: { controller: GroupMoveDialogController }): ReactNode {
  const { controller } = props;
  const state = useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot);
  const options: ReactNode[] = [];
  for (const group of state?.groups || []) {
    options.push(h("label", { className: "grp-opt", key: `g:${group}` },
      h("input", {
        type: "radio", name: "tplMove", value: group,
        checked: !!state && !state.useFresh && state.choice === group,
        onChange: () => controller.patch({ choice: group, useFresh: false, error: "" }),
      }), ` ${group}`));
  }
  options.push(h("label", { className: "grp-opt", key: "none" },
    h("input", {
      type: "radio", name: "tplMove", value: "",
      checked: !!state && !state.useFresh && state.choice === "",
      onChange: () => controller.patch({ choice: "", useFresh: false, error: "" }),
    }), " 그룹 없음(해제)"));
  options.push(h("label", { className: "grp-opt", key: "new" },
    h("input", {
      type: "radio", name: "tplMove", "data-new": "1", id: "tplMoveNewRadio",
      checked: !!state?.useFresh,
      onChange: () => controller.patch({ useFresh: true, error: "" }),
    }), " 새 그룹: ",
    h("input", {
      className: "field", id: "tplMoveNewName", type: "text", placeholder: "새 그룹 이름",
      value: state?.fresh || "",
      onFocus: () => controller.patch({ useFresh: true }),
      onChange: (event: Obj) => controller.patch({
        fresh: String(event.currentTarget.value), useFresh: true, error: "",
      }),
    })));
  return h("div", { className: "modal-card" },
    h("h3", { id: "tplMoveTitle" }, "그룹으로 이동"),
    h("p", { className: "modal-sub", id: "tplMoveName" }, state?.nameText || ""),
    h("div", { id: "tplMoveList", className: "sheet-list" }, ...options),
    h("p", {
      id: "tplMoveErr", className: "note dangerbox",
      style: { display: state?.error ? "" : "none" },
    }, state?.error || ""),
    h("div", { className: "modal-actions" },
      h("button", { className: "btn", id: "tplMoveCancel", onClick: controller.cancel }, "취소"),
      h("button", { className: "btn primary", id: "tplMoveOk", onClick: controller.confirm }, "이동")));
}
