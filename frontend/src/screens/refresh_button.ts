import { createElement, useEffect, useRef, useState } from "react";
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
  const [done, setDone] = useState(false);
  const pending = useRef(false);
  const completionTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(completionTimer.current), []);
  /** 거절된 새로고침인가 — 「선택 초기화 확인 취소」(`false`)와 서버 `ok:false` 거절을 한
   *  판정으로 모은다. `ok:false` 는 그 사유를 실어 던진다. */
  function rejectedRefresh(result: unknown, label: string): boolean {
    if (result === false) return true; // 선택 초기화 확인 취소
    if (result && typeof result === "object" && "ok" in result && result.ok === false) {
      throw new Error("error" in result ? String(result.error) : `${label} 실패`);
    }
    return false;
  }
  async function refresh(): Promise<void> {
    if (pending.current || props.disabled) return;
    pending.current = true;
    clearTimeout(completionTimer.current);
    setDone(false);
    setBusy(true);
    try {
      const result = await props.onRefresh();
      if (rejectedRefresh(result, props.label)) return;
      setDone(true);
      completionTimer.current = setTimeout(() => setDone(false), 700);
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
    title: props.label, "aria-label": done ? `${props.label} 완료` : props.label,
    "aria-busy": busy, "data-refresh-done": done,
    onClick: () => { void refresh(); },
  }, createElement("svg", {
    viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false",
  }, createElement("path", {
    d: done ? "M5 12l4 4L19 6" : "M20 7v5h-5M20 12a8 8 0 1 0-2.3 5.7",
  })));
}
