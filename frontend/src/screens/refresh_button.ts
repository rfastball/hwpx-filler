import { createElement, useRef, useState } from "react";
import type { ReactNode } from "react";

/** 목록과 현재 데이터의 공통 새로고침 동사. */
export function RefreshButton(props: {
  label: string;
  onRefresh(): Promise<unknown> | void;
  notify(message: string): void;
  id?: string;
  side?: "tpl" | "dat";
  disabled?: boolean;
}): ReactNode {
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  async function refresh(): Promise<void> {
    if (pending.current || props.disabled) return;
    pending.current = true;
    setBusy(true);
    try {
      const result = await props.onRefresh();
      if (result === false) return; // 선택 초기화 확인 취소
      if (result && typeof result === "object" && "ok" in result && result.ok === false) {
        throw new Error("error" in result ? String(result.error) : `${props.label} 실패`);
      }
      props.notify(`${props.label} 완료`);
    } catch (error) {
      props.notify(`${props.label} 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return createElement("button", {
    className: "btn sm reload refresh-button", type: "button", id: props.id,
    "data-act": props.side ? "refresh" : undefined, "data-side": props.side,
    "data-busy-lock": true, disabled: props.disabled || busy,
    title: props.label, "aria-label": props.label, "aria-busy": busy,
    onClick: () => { void refresh(); },
  }, createElement("svg", {
    viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false",
  }, createElement("path", { d: "M20 7v5h-5M20 12a8 8 0 1 0-2.3 5.7" })));
}
