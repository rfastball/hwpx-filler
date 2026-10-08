/* 등록 시트 탭 띠 — 작업 화면 하단과 편집기 「연결 확인」이 같은 한 벌을 그린다.
   행(`data_sheet_tabs`)·활성·고를 수 있는가·사유는 Python 투영(`screens.registered_sheet_tabs`)
   그대로다. 여기서는 그리고, 누른 행을 호출자에게 넘길 뿐이다. 등록이 손상되면 Python 이
   고를 수 없는 탭 하나에 `damaged` 와 손상 문장을 실어 보낸다 — 그 문장은 툴팁에만 두지 않고
   띠 아래에 드러낸다(손상이 「시트 없음」처럼 보이지 않게). */
import { Fragment, createElement, useEffect, useRef, useState } from "react";
import type { DragEvent, KeyboardEvent, ReactNode } from "react";

type Obj = Record<string, any>;

export { saveSheetOrder } from "./pool_verbs.ts";

function canReorder(rows: Obj[], enabled: boolean, ...locks: boolean[]): boolean {
  return enabled && !locks.some(Boolean) && rows.every((row) => row.selectable !== false);
}

export function SheetTabs(props: {
  rows: Obj[]; busy?: boolean; locked?: boolean; onPick: (row: Obj) => void;
  onReorder?: (key: string, sheets: string[]) => void | Promise<void>;
}): ReactNode {
  const { rows, busy = false, locked = false, onPick, onReorder } = props;
  const activeTab = useRef<HTMLButtonElement>(null);
  const dragging = useRef<string | null>(null);
  const [dropSheet, setDropSheet] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const movable = canReorder(rows, !!onReorder, busy, locked, saving);
  function move(from: string, to: string): void {
    if (!movable || from === to) return;
    const sheets = rows.map((row) => String(row.sheet));
    const index = sheets.indexOf(from), target = sheets.indexOf(to);
    if (index < 0 || target < 0) return;
    sheets.splice(index, 1);
    sheets.splice(target, 0, from);
    setSaving(true);
    Promise.resolve(onReorder?.(String(rows[0].key), sheets)).finally(() => setSaving(false));
  }
  const busyState = [busy, saving].some(Boolean);
  const active = rows.find((row) => row.active);
  useEffect(() => {
    activeTab.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [active?.key, active?.sheet]);
  if (!rows.length) return null;
  const damaged = rows.find((row) => row.damaged);
  const strip = createElement("div", { className: "data-tabs", role: "group", "aria-label": "사용할 시트",
    "aria-busy": busyState },
    ...rows.map((row) => createElement("button", {
      type: "button", key: row.sheet, className: "data-tab", "data-busy-lock": true,
      "data-drop-target": dropSheet === row.sheet || undefined, draggable: movable,
      "aria-keyshortcuts": movable ? "Alt+ArrowLeft Alt+ArrowRight" : undefined,
      ref: row.active ? activeTab : undefined, "aria-pressed": row.active,
      disabled: row.selectable === false || locked, title: row.reason || row.sheet,
      "aria-disabled": busyState || undefined,
      onClick: () => { if (!saving && !busy) onPick(row); },
      onDragStart: (event: DragEvent<HTMLButtonElement>) => {
        dragging.current = row.sheet;
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", row.sheet);
      },
      onDragOver: (event: DragEvent<HTMLButtonElement>) => {
        if (!movable || dragging.current === null) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        setDropSheet(row.sheet);
      },
      onDrop: (event: DragEvent<HTMLButtonElement>) => {
        event.preventDefault();
        if (dragging.current !== null) move(dragging.current, row.sheet);
        dragging.current = null;
        setDropSheet(null);
      },
      onDragEnd: () => { dragging.current = null; setDropSheet(null); },
      onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => {
        if (!event.altKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        const target = rows[rows.indexOf(row) + (event.key === "ArrowLeft" ? -1 : 1)];
        if (target) move(row.sheet, target.sheet);
      },
    }, row.sheet)));
  if (!damaged) return strip;
  return createElement(Fragment, null, strip,
    createElement("p", { className: "note dangerbox", role: "alert" }, damaged.reason));
}
