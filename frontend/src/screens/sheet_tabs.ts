/* 등록 시트 탭 띠 — 작업 화면 하단과 편집기 「연결 확인」이 같은 한 벌을 그린다.
   행(`data_sheet_tabs`)·활성·고를 수 있는가·사유는 Python 투영(`screens.registered_sheet_tabs`)
   그대로다. 여기서는 그리고, 누른 행을 호출자에게 넘길 뿐이다. */
import { createElement, useEffect, useRef } from "react";
import type { ReactNode } from "react";

type Obj = Record<string, any>;

export function SheetTabs(props: {
  rows: Obj[]; busy?: boolean; locked?: boolean; onPick: (row: Obj) => void;
}): ReactNode {
  const { rows, busy = false, locked = false, onPick } = props;
  const activeTab = useRef<HTMLButtonElement>(null);
  const active = rows.find((row) => row.active);
  useEffect(() => {
    activeTab.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [active?.key, active?.sheet]);
  if (!rows.length) return null;
  return createElement("div", { className: "data-tabs", role: "group", "aria-label": "사용할 시트",
    "aria-busy": busy },
    ...rows.map((row) => createElement("button", {
      type: "button", key: row.sheet, className: "data-tab", "data-busy-lock": true,
      ref: row.active ? activeTab : undefined, "aria-pressed": row.active,
      disabled: row.selectable === false || locked, title: row.reason || row.sheet,
      onClick: () => onPick(row),
    }, row.sheet)));
}
