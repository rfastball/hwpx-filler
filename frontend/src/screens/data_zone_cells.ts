/* R4-01 DataZone 의 셀 조각 표시와 열 메타 판독 — 표·열 머리 패널·열 고르기 목록이 같은 형식
   (`[글자, 강조]` 조각 배열·열 메타 객체)을 읽는다. 형식이 손상되면 던진다. */
import { createElement, Fragment } from "react";
import type { ReactNode } from "react";

type Obj = Record<string, any>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

function asObject(value: unknown, label: string): Obj {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}: 객체가 아닙니다.`);
  }
  return value as Obj;
}

export function columnMeta(column: unknown): Obj {
  return typeof column === "string"
    ? { name: column, kind: "text", visible: true }
    : asObject(column, "job table column");
}

export function Segments({ value }: { value: unknown }): ReactNode {
  if (!Array.isArray(value)) return null;
  return createElement(Fragment, null, ...value.map((segment, index) => {
    if (!Array.isArray(segment)) throw new Error("job table segment 형식이 손상됐습니다.");
    return segment[1]
      ? h("mark", { key: index }, String(segment[0] ?? ""))
      : String(segment[0] ?? "");
  }));
}
