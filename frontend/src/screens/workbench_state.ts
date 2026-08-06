/* R4-02 작업대 draft 투영 — reducer 는 편집기와 **같은 것**을 쓴다(`editor_state.ts`).

   두 화면의 문제가 같기 때문이다: 값 입력은 blur 에서만 발신하고, 그사이 도착한 push 가
   그 값을 덮으면 안 되며, 늦게 온 응답이 지금 치는 값을 지우면 안 된다. 두 벌 쓰면 한쪽만
   늙는다 — 이 파일이 드는 것은 **작업대 스냅샷을 그 reducer 의 입력으로 사영하는 규칙**뿐이다.

   legacy 는 여기서 `Preserve.around(renderMap)` 과 안정 id(`wbMap-val-…`)로 캐럿을 되찾았다.
   React 소유에서는 같은 노드가 살아 있어 되찾을 것이 없다 — 대신 「누가 값의 주인인가」를
   reducer 가 든다. */

import type { DraftState, ServerValues } from "./editor_state.ts";

export const TARGET_FONT_FIELD = "targetFont";

export type MapAxis = "source" | "type" | "fmt" | "value" | "confirmed";

/** 작업대 행은 index 가 아니라 **토큰 이름**이 정체다(겨눔·복사 전 확인이 이름으로 말한다). */
export function mapField(name: string, axis: MapAxis): string {
  return `map:${name}:${axis}`;
}

export function workbenchServerValues(snapshot: Record<string, any>): ServerValues {
  const values: Record<string, string> = {
    [TARGET_FONT_FIELD]: String(snapshot.target_font ?? ""),
  };
  for (const row of (snapshot.rows || []) as Array<Record<string, any>>) {
    const name = String(row.name ?? "");
    values[mapField(name, "source")] = row.own === "auto" ? String(row.source ?? "") : "";
    values[mapField(name, "type")] = String(row.fmt_kind ?? "");
    values[mapField(name, "fmt")] = String(row.fmt_code ?? "");
    values[mapField(name, "value")] = String(row.value ?? "");
    values[mapField(name, "confirmed")] = row.confirmed ? "1" : "";
  }
  return values;
}

/** 작업대 세션 = 진입 시 받은 고정 사본. 닫히면 draft 를 들고 가지 않는다. */
export function workbenchSession(snapshot: Record<string, any>): string {
  return snapshot.open ? `wb:${String(snapshot.job_name ?? "")}` : "";
}

export function workbenchRevision(snapshot: Record<string, any>): number {
  const revision = snapshot.revision || {};
  return Number(revision.binding ?? 0) * 1000 + Number(revision.template ?? 0);
}

/** 체크박스 축의 표시값 — reducer 는 문자열만 들므로 경계에서 한 번만 번역한다. */
export function checked(state: DraftState, key: string): boolean {
  return (state.fields[key]?.draftValue ?? "") === "1";
}
