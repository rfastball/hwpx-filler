/* R4-04 — React 화면 공용 문맥 메뉴.

   항목·열림 정체·선택·첫 포커스는 React 트리가 소유한다. 공용 Popover 에서는 화면 전역
   dismissal registry 와 실제 렌더 크기에 따른 위치 계산만 주입받아 재사용한다. 문자열 HTML,
   정적 menu host, document 위임 클릭은 이 경계 안에 없다. */
import {
  Fragment,
  createElement,
  useEffect,
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";

type Listener = () => void;

export type ContextMenuItem = Readonly<{
  action: string;
  label: string;
  danger?: boolean;
  separatorBefore?: boolean;
}>;

type ContextMenuState = Readonly<{
  trigger: HTMLElement;
  items: readonly ContextMenuItem[];
}> | null;

export type ContextMenuPopoverPort = {
  place(
    menu: HTMLElement,
    trigger: HTMLElement,
    options?: Readonly<{ gap?: number; margin?: number; offsetParent?: HTMLElement }>,
  ): unknown;
  wireDismiss(spec: {
    isOpen(): boolean;
    contains(target: Element): boolean;
    close(): void;
  }): () => void;
};

export function createContextMenu() {
  let state: ContextMenuState = null;
  const listeners = new Set<Listener>();

  function emit(): void {
    listeners.forEach((listener) => listener());
  }

  function close(): void {
    if (state === null) return;
    state = null;
    emit();
  }

  return {
    model: {
      getSnapshot: (): ContextMenuState => state,
      subscribe(listener: Listener): () => void {
        listeners.add(listener);
        return () => { listeners.delete(listener); };
      },
    },
    open(trigger: HTMLElement, items: readonly ContextMenuItem[]): void {
      state = { trigger, items: [...items] };
      emit();
    },
    close,
    isOpen: (): boolean => state !== null,
  };
}

export type ContextMenuController = ReturnType<typeof createContextMenu>;

export function ContextMenu(props: {
  id: string;
  controller: ContextMenuController;
  popover: ContextMenuPopoverPort;
  triggerSelector: string;
  onDismiss(): void;
  onSelect(action: string): void;
}): ReactNode {
  const { controller, id, onDismiss, onSelect, popover, triggerSelector } = props;
  const state = useSyncExternalStore(
    controller.model.subscribe,
    controller.model.getSnapshot,
    controller.model.getSnapshot,
  );
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => popover.wireDismiss({
    isOpen: controller.isOpen,
    contains(target: Element): boolean {
      const menu = menuRef.current;
      const current = controller.model.getSnapshot();
      return !!menu?.contains(target) || !!current?.trigger.contains(target) ||
        target.closest(triggerSelector) !== null;
    },
    close: onDismiss,
  }), [controller, onDismiss, popover, triggerSelector]);

  /* 측정·초점은 React commit 뒤에만 가능하다. 같은 trigger 에서 내용만 바뀐 경우도 새
     snapshot 이므로 다시 실제 크기를 재고 첫 항목을 겨눈다. */
  useLayoutEffect(() => {
    const menu = menuRef.current;
    if (menu === null || state === null) return;
    popover.place(menu, state.trigger);
    menu.querySelector<HTMLElement>("button")?.focus();
  }, [popover, state]);

  if (state === null) return null;
  return createElement("div", {
    className: "ctx-menu",
    id,
    ref: menuRef,
    role: "menu",
  }, ...state.items.map((item) => createElement(Fragment, { key: item.action },
    item.separatorBefore
      ? createElement("div", { className: "sep", role: "separator" })
      : null,
    createElement("button", {
      className: item.danger ? "danger" : undefined,
      type: "button",
      role: "menuitem",
      "data-context-menu-action": item.action,
      onClick: () => onSelect(item.action),
    }, item.label),
  )));
}
