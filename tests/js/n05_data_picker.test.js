/* N-05 data picker tests translated at R4-01. The retired imperative module had
   31 cases; this file keeps 31 behavior cases against the React controller. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createDataPickerController } from "../../frontend/src/screens/data_picker.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

const SRC_URL = new URL("../../frontend/src/screens/data_picker.ts", import.meta.url);
const SRC = readFileSync(SRC_URL, "utf8");
const tick = () => new Promise((resolve) => setImmediate(resolve));

const SURFACE = [
  "init", "poolModel", "model", "regModel", "open", "close", "browseFile", "openPin",
  "poolAction", "resolveDuplicate", "openRegDialog", "patchReg", "closeReg",
  "browseRegPath", "submitReg", "client", "notify",
];

function build(options = {}) {
  let pool = options.pool ?? { rows: [], duplicates: [], corrupted: [] };
  const poolListeners = new Set();
  const dispatchCalls = [];
  const invokeCalls = [];
  const modalCalls = [];
  const confirms = [];
  const sheetCalls = [];
  const notifications = [];
  const initialCalls = [];
  const services = createServiceHandoffPorts();
  services.sheetPicker.bindLegacy({
    async choose(screen, request) {
      sheetCalls.push([screen, request]);
      return options.choose ? options.choose(screen, request) : null;
    },
  });
  const client = {
    async dispatch(screen, action, payload) {
      dispatchCalls.push([screen, action, payload]);
      const value = options.dispatch ? await options.dispatch(screen, action, payload) : {};
      return { ok: true, value };
    },
    async invoke(method, ...args) {
      invokeCalls.push([method, ...args]);
      const value = options.invoke ? await options.invoke(method, ...args) : null;
      return { ok: true, value };
    },
  };
  const modal = {
    async confirm(spec) {
      confirms.push(spec);
      return typeof options.confirm === "function" ? options.confirm(spec) : (options.confirm ?? false);
    },
    open: (id, spec) => modalCalls.push(["open", id, spec]),
    close: (id) => modalCalls.push(["close", id]),
  };
  const controller = createDataPickerController({
    doc: { getElementById: (id) => ({ id }) },
    runtime: {
      model: () => ({
        getSnapshot: () => pool,
        subscribe(listener) { poolListeners.add(listener); return () => poolListeners.delete(listener); },
      }),
      async loadInitial(screen) { initialCalls.push(screen); return pool; },
    },
    client, services, modal,
    notify: (message) => notifications.push(String(message)),
  });
  return {
    controller, client, dispatchCalls, invokeCalls, modalCalls, confirms, sheetCalls,
    notifications, initialCalls,
    setPool(value) { pool = value; for (const listener of poolListeners) listener(); },
  };
}

async function opened(h, options = {}) {
  const result = h.controller.open({ screen: "job", ...options });
  await tick(); // pool/refresh rejection handler까지 정산
  return { result };
}

test("공개 표면 — React data picker controller 키가 정확하다", () => {
  assert.deepEqual(Object.keys(build().controller), SURFACE);
});

test("파일 export — controller와 두 React content producer만 named export다", () => {
  assert.equal(/export\s+default/.test(SRC), false);
  for (const name of ["createDataPickerController", "DataPickerDialog", "PoolRegistrationDialog"]) {
    assert.ok(SRC.includes(`export function ${name}`), name);
  }
});

test("구조 음성 — legacy 제품 전역과 imperative listener 소유가 없다", () => {
  assert.equal(/(?:window|globalThis)\.(?:Bridge|Modal|SheetPicker|PathTrack|DataPicker)\b/.test(SRC), false);
  assert.equal(SRC.includes("addEventListener("), false);
  assert.ok(SRC.includes("useSyncExternalStore"));
});

test("init — pool initial pull은 screen runtime에 위임한다", async () => {
  const h = build();
  await h.controller.init();
  assert.deepEqual(h.initialCalls, ["pool"]);
});

test("controller model — subscribe 해제 뒤에는 알림이 오지 않는다", () => {
  const h = build();
  let count = 0;
  const release = h.controller.model.subscribe(() => { count += 1; });
  const result = h.controller.open({ screen: "job" });
  assert.equal(count, 1);
  release();
  h.controller.close();
  assert.equal(count, 1);
  return result;
});

test("open — session을 만들고 dataPickerModal을 연다", async () => {
  const h = build();
  const { result } = await opened(h, { current: { label: "현재" } });
  assert.equal(h.controller.model.getSnapshot().session.current.label, "현재");
  assert.equal(h.modalCalls[0][1], "dataPickerModal");
  h.controller.close();
  await result;
});

test("둘째 open — 열린 session 위에 조용히 겹치지 않는다", async () => {
  const h = build();
  const { result: first } = await opened(h);
  await assert.rejects(h.controller.open({ screen: "job" }), /이미 열려/);
  h.controller.close();
  await first;
});

test("close — 미선택 session은 null로 정확히 한 번 settle된다", async () => {
  const h = build();
  const { result } = await opened(h);
  h.controller.close();
  assert.equal(await result, null);
  h.controller.close();
  assert.equal(h.modalCalls.filter((row) => row[0] === "close" && row[1] === "dataPickerModal").length, 1);
});

test("파일 mount 뒤 close — label settle과 onLoaded는 각각 한 번이다", async () => {
  const h = build({ invoke: async () => ({ label: "목록.xlsx", rows: 3, path: "C:/목록.xlsx" }) });
  const loaded = [];
  const { result } = await opened(h, { onLoaded: (label) => loaded.push(label) });
  await h.controller.browseFile();
  h.controller.close();
  assert.equal(await result, "목록.xlsx");
  assert.deepEqual(loaded, ["목록.xlsx"]);
});

test("confirmSwap 거절 — 파일 선택 호출 전에 중단한다", async () => {
  const h = build();
  const { result } = await opened(h, { confirmSwap: async () => false });
  await h.controller.browseFile();
  assert.deepEqual(h.invokeCalls, []);
  h.controller.close(); await result;
});

test("파일 선택 취소 — session을 유지하고 상태를 비운다", async () => {
  const h = build({ invoke: async () => null });
  const { result } = await opened(h);
  await h.controller.browseFile();
  assert.notEqual(h.controller.model.getSnapshot().session, null);
  assert.equal(h.controller.model.getSnapshot().status, "");
  h.controller.close(); await result;
});

test("파일 선택 ERROR 문자열 — danger 상태로 재진술한다", async () => {
  const h = build({ invoke: async () => "ERROR: 손상" });
  const { result } = await opened(h);
  await h.controller.browseFile();
  assert.match(h.controller.model.getSnapshot().status, /손상/);
  assert.equal(h.controller.model.getSnapshot().level, "danger");
  h.controller.close(); await result;
});

test("파일 선택 throw — modal을 닫지 않고 오류를 재진술한다", async () => {
  const h = build({ invoke: async () => { throw new Error("pick down"); } });
  const { result } = await opened(h);
  await h.controller.browseFile();
  assert.match(h.controller.model.getSnapshot().status, /pick down/);
  assert.notEqual(h.controller.model.getSnapshot().session, null);
  h.controller.close(); await result;
});

test("다중 시트 취소 — 데이터는 그대로이고 면은 열린다", async () => {
  const h = build({ invoke: async () => ({ needs_sheet: true, sheets: ["S1"] }), choose: async () => null });
  const { result } = await opened(h);
  await h.controller.browseFile();
  assert.equal(h.sheetCalls.length, 1);
  assert.match(h.controller.model.getSnapshot().status, /취소/);
  h.controller.close(); await result;
});

test("다중 시트 성사 — 선택 결과를 현재 session에 싣는다", async () => {
  const chosen = { label: "목록.xlsx / S2", rows: 3, path: "C:/목록.xlsx", sheet: "S2" };
  const h = build({ invoke: async () => ({ needs_sheet: true }), choose: async () => chosen });
  const { result } = await opened(h);
  await h.controller.browseFile();
  assert.equal(h.controller.model.getSnapshot().session.current.sheet, "S2");
  h.controller.close();
  assert.equal(await result, chosen.label);
});

test("고정 목록 선택 성사 — 면을 닫고 label로 해소한다", async () => {
  const h = build({ dispatch: async (_screen, action) => action === "load_pool" ? { ok: true, label: "고정 목록" } : {} });
  const loaded = [];
  const { result } = await opened(h, { onLoaded: (label) => loaded.push(label) });
  await h.controller.poolAction("use", { key: "k", name: "등록명" });
  assert.equal(await result, "고정 목록");
  assert.deepEqual(loaded, ["고정 목록"]);
});

test("고정 목록 load 실패 — session을 유지하고 danger 상태를 낸다", async () => {
  const h = build({ dispatch: async (_screen, action) => action === "load_pool" ? { ok: false, error: "읽기 실패" } : {} });
  const { result } = await opened(h);
  await h.controller.poolAction("use", { key: "k", name: "등록명" });
  assert.match(h.controller.model.getSnapshot().status, /읽기 실패/);
  assert.notEqual(h.controller.model.getSnapshot().session, null);
  h.controller.close(); await result;
});

test("고정 목록 load throw — 오류를 재진술하고 loading을 해제한다", async () => {
  const h = build({ dispatch: async (_screen, action) => { if (action === "load_pool") throw new Error("mount down"); return {}; } });
  const { result } = await opened(h);
  await h.controller.poolAction("use", { key: "k", name: "등록명" });
  assert.match(h.controller.model.getSnapshot().status, /mount down/);
  assert.equal(h.controller.model.getSnapshot().loading, false);
  h.controller.close(); await result;
});

test("mount 진행 중 close — 닫지 않고 busy 오류를 재진술한다", async () => {
  let release;
  const deferred = new Promise((resolve) => { release = resolve; });
  const h = build({ dispatch: async (_screen, action) => action === "load_pool" ? deferred : {} });
  const { result } = await opened(h);
  const mounting = h.controller.poolAction("use", { key: "k", name: "등록명" });
  await tick();
  h.controller.close();
  assert.match(h.controller.model.getSnapshot().status, /불러오는 중/);
  release({ ok: false, error: "중단" });
  await mounting;
  h.controller.close(); await result;
});

test("이 데이터 고정 — 현재 path가 없으면 등록면을 열지 않는다", async () => {
  const h = build();
  const { result } = await opened(h, { current: { label: "현재" } });
  h.controller.openPin();
  assert.equal(h.controller.regModel.getSnapshot(), null);
  h.controller.close(); await result;
});

test("이 데이터 고정 — 현재 label/path/sheet를 registration state로 옮긴다", async () => {
  const h = build();
  const { result } = await opened(h, { current: { label: "현재", path: "C:/a.xlsx", sheet: "S1" } });
  h.controller.openPin();
  assert.deepEqual(
    Object.fromEntries(Object.entries(h.controller.regModel.getSnapshot()).filter(([key]) => ["name", "path", "sheet", "pinMode"].includes(key))),
    { name: "현재", path: "C:/a.xlsx", sheet: "S1", pinMode: true },
  );
  h.controller.closeReg(); h.controller.close(); await result;
});

test("등록 validation — 이름·경로가 비면 발신하지 않고 오류를 보인다", async () => {
  const h = build();
  h.controller.openRegDialog({});
  await h.controller.submitReg();
  assert.match(h.controller.regModel.getSnapshot().error, /이름과 파일 경로/);
  assert.deepEqual(h.dispatchCalls, []);
});

test("등록 확정 — trim된 register_excel payload를 보낸다", async () => {
  const h = build();
  h.controller.openRegDialog({ name: " 이름 ", path: " C:/a.xlsx ", sheet: " S1 ", note: " 메모 " });
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls[0], ["pool", "register_excel", { name: "이름", path: "C:/a.xlsx", sheet: "S1", note: "메모" }]);
  assert.equal(h.controller.regModel.getSnapshot(), null);
});

test("등록 overwrite 거절 — basis 2차 발신 없이 modal을 유지한다", async () => {
  const h = build({ dispatch: async () => ({ needs_confirm: true, basis: "b", confirm_text: "겹침" }), confirm: false });
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx" });
  await h.controller.submitReg();
  assert.equal(h.dispatchCalls.length, 1);
  assert.notEqual(h.controller.regModel.getSnapshot(), null);
});

test("등록 overwrite 승인 — confirm+basis를 실은 2차 발신만 확정한다", async () => {
  let count = 0;
  const h = build({ dispatch: async () => (++count === 1 ? { needs_confirm: true, basis: "b", confirm_text: "겹침" } : { ok: true }), confirm: true });
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx" });
  await h.controller.submitReg();
  assert.equal(h.dispatchCalls.length, 2);
  assert.equal(h.dispatchCalls[1][2].confirm, true);
  assert.equal(h.dispatchCalls[1][2].basis, "b");
});

test("다시 연결 — 같은 slot key와 편집한 경로를 relink payload로 보낸다", async () => {
  const h = build();
  h.controller.openRegDialog({ targetKey: "slot", name: "이름", path: "C:/old.xlsx" });
  h.controller.patchReg({ path: "C:/new.xlsx" });
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls[0], ["pool", "relink", {
    key: "slot", name: "이름", path: "C:/new.xlsx", sheet: "", note: "",
  }]);
});

test("등록 path 찾아보기 — invoke 결과를 현재 registration state에 반영한다", async () => {
  const h = build({ invoke: async (method) => method === "pick_pool_data_file" ? "C:/picked.xlsx" : null });
  h.controller.openRegDialog({ name: "이름", path: "C:/old.xlsx" });
  await h.controller.browseRegPath();
  assert.equal(h.controller.regModel.getSnapshot().path, "C:/picked.xlsx");
});

test("삭제 — needs_confirm 뒤 basis를 보존한 2단 왕복이다", async () => {
  let count = 0;
  const h = build({ dispatch: async (_screen, action) => action === "delete" && ++count === 1
    ? { needs_confirm: true, basis: "fingerprint", confirm_text: "사용 중" } : { ok: true }, confirm: true });
  await h.controller.poolAction("delete", { key: "k" });
  assert.deepEqual(h.dispatchCalls.map((row) => row[2]), [
    { key: "k" }, { key: "k", confirm: true, basis: "fingerprint" },
  ]);
});

test("중복 정리 — 남길 key와 basis를 보존한 2단 왕복이다", async () => {
  let count = 0;
  const h = build({ dispatch: async (_screen, action) => action === "resolve_duplicate" && ++count === 1
    ? { needs_confirm: true, basis: "dupe", confirm_text: "중복" } : { ok: true }, confirm: true });
  await h.controller.resolveDuplicate("keep");
  assert.deepEqual(h.dispatchCalls.map((row) => row[2]), [
    { keep: "keep" }, { keep: "keep", confirm: true, basis: "dupe" },
  ]);
});

test("비활성·끊김 항목 — React producer가 이유를 병기하고 use를 disabled한다", () => {
  assert.ok(SRC.includes('if (row.status !== "active")'));
  assert.ok(SRC.includes("if (row.missing)"));
  assert.ok(SRC.includes("disabled: !!reason"));
});

test("registration close — state를 비우고 poolRegModal만 닫는다", () => {
  const h = build();
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx" });
  h.controller.closeReg();
  assert.equal(h.controller.regModel.getSnapshot(), null);
  assert.deepEqual(h.modalCalls.at(-1).slice(0, 2), ["close", "poolRegModal"]);
});
