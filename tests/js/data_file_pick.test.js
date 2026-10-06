/* 「파일 찾아보기…」 응답 해석 — 데이터 선택 면·편집기가 한 벌로 쓰는 `pickDataFile`. */
import test from "node:test";
import assert from "node:assert/strict";

import { pickDataFile } from "../../frontend/src/screens/data_file_pick.ts";

function ports(choice = null) {
  const calls = [];
  return {
    calls,
    ports: {
      sheetPicker: { choose: async (screen, payload) => { calls.push(["choose", screen, payload]); return choice; } },
      openContractList: (db) => { calls.push(["contract", db]); },
    },
  };
}

const answering = (value) => async (method, screen) => {
  assert.equal(method, "pick_data_file");
  assert.equal(screen, "job");
  return value;
};

test("계약 목록 갈래는 Python 표지 그대로 등록 폼으로 넘기고 데이터는 그대로다", async () => {
  /* 확장자를 보지 않는다 — 표지(`contract_list`)만 본다. 그래서 확장자 없는 경로도 넘어간다. */
  const h = ports();
  const picked = await pickDataFile(answering({ contract_list: true, path: "C:/d/계약목록" }), "job", h.ports);
  assert.deepEqual(picked, { kind: "none" });
  assert.deepEqual(h.calls, [["contract", "C:/d/계약목록"]]);
  // 표지가 없으면 같은 확장자라도 등록 갈래로 가지 않는다(판정은 Python 하나).
  const mounted = await pickDataFile(answering({ label: "파일: a.db", path: "C:/d/a.db", rows: 1 }), "job", h.ports);
  assert.equal(mounted.kind, "mounted");
  assert.equal(h.calls.length, 1);
});

test("다중 시트는 시트 확정을 거치고, 확정 취소·실패·대화상자 취소를 갈라 돌려준다", async () => {
  const request = { needs_sheet: true, path: "C:/d/a.xlsx", sheets: [{ name: "S1" }] };
  const chosen = ports({ label: "파일: a.xlsx", rows: 3 });
  assert.deepEqual(await pickDataFile(answering(request), "job", chosen.ports),
    { kind: "mounted", value: { label: "파일: a.xlsx", rows: 3 } });
  assert.deepEqual(chosen.calls, [["choose", "job", request]]);
  assert.deepEqual(await pickDataFile(answering(request), "job", ports(null).ports), { kind: "sheet_cancelled" });
  assert.deepEqual(await pickDataFile(answering(request), "job", ports("ERROR: 시트 없음").ports),
    { kind: "error", message: "시트 없음" });
  assert.deepEqual(await pickDataFile(answering("ERROR: 깨진 파일"), "job", ports().ports),
    { kind: "error", message: "깨진 파일" });
  assert.deepEqual(await pickDataFile(answering(null), "job", ports().ports), { kind: "none" });
});
