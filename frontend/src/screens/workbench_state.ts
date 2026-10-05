/* R4-02 작업대 draft 투영 — reducer 는 편집기와 **같은 것**을 쓴다(`editor_state.ts`).

   이 화면에서 초안을 드는 칸은 대상 글꼴 하나다(필드 연결 표는 #1148 에서 걷혔다). 그래도
   reducer 를 따로 짓지 않는다: 늦게 온 응답이 지금 고른 값을 지우면 안 된다는 문제가 편집기와
   같고, 두 벌 쓰면 한쪽만 늙는다 — 이 파일이 드는 것은 **작업대 스냅샷을 그 reducer 의
   입력으로 사영하는 규칙**뿐이다. */

import type { ServerValues } from "./editor_state.ts";

export const TARGET_FONT_FIELD = "targetFont";

export function workbenchServerValues(snapshot: Record<string, any>): ServerValues {
  return { [TARGET_FONT_FIELD]: String(snapshot.target_font ?? "") };
}

/** 작업대 세션 = 진입 시 받은 고정 사본. 닫히면 draft 를 들고 가지 않는다. */
export function workbenchSession(snapshot: Record<string, any>): string {
  return snapshot.open ? `wb:${String(snapshot.job_name ?? "")}` : "";
}
