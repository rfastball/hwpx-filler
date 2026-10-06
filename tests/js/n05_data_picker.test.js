/* Data-picker controller behavior: lifecycle, validation, and settle-once flows. */
import test from "node:test";
import assert from "node:assert/strict";

import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

import {
  DataPickerDialog,
  PoolRegistrationDialog,
  createDataPickerController,
} from "../../frontend/src/screens/data_picker.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

const tick = () => new Promise((resolve) => setImmediate(resolve));

const SURFACE = [
  "init", "poolModel", "model", "regModel", "open", "close", "browseFile", "openPin",
  "openPclm", "choose", "refresh", "poolAction", "resolveDuplicate", "noticeAction",
  "rowContextMenu", "toggleRowMenu", "closeRowMenu", "handleRowMenu",
  "openDetail", "closeDetail", "handleDetailVerb", "popover",
  "openRegDialog", "patchReg", "inspectRegSheets", "selectRegSheets", "closeReg", "browseRegPath", "submitReg", "client", "notify",
];

/** 스냅샷이 낸 세션 행 하나(`webapp/pool_column.session_data_row` 와 같은 키 집합).
 *
 *  **부제는 Python 이 짓는다** — 이 파일이 시트·헤더 행·행 수를 잇지 않는 것이 계약이다. */
function sessionRow(overrides) {
  return Object.assign({
    key: "session", name: "대장.xlsx", sub: "시트: 물품 · 3행", reason: "", warns: [],
    badge_label: "사용 중", badge_level: "ok", icon: "excel", selectable: true,
    path: "C:/d/대장.xlsx", actions: [],
  }, overrides || {});
}

/** 여는 쪽이 넘기는 세션 판독기 — 값이 아니라 **함수**다(면 안에서 마운트가 바뀐다). */
function sessionRead(value) {
  return () => Object.assign(
    { data_row: null, data_pool_key: "", sheet: "" }, value || {},
  );
}

/** 백엔드 `inspect_sheets(kind=pclm)` 가 사용자가 적은 DB 에서 **실제로 나열한** 시트(뷰 먼저,
 * 다음 표). 고정 허용목록과 제목·설명표는 사용자 결정(2026-09-30)으로 걷혔다 — 항목은 시트
 * 이름 하나다. 스냅샷은 기본 DB 자리도 시트도 싣지 않는다(기본 자리 추측은 걷혔다). */
const PCLM_SHEETS = ["v_통합_v2", "v_접수_v1", "계약"];

function build(options = {}) {
  let pool = options.pool ?? {};
  const poolListeners = new Set();
  const dispatchCalls = [];
  const inspectionCalls = [];
  const invokeCalls = [];
  const modalCalls = [];
  const confirms = [];
  const sheetCalls = [];
  const notifications = [];
  const initialCalls = [];
  const services = createServiceHandoffPorts();
  services.sheetPicker.bind({
    async choose(screen, request) {
      sheetCalls.push([screen, request]);
      return options.choose ? options.choose(screen, request) : null;
    },
  });
  const client = {
    async dispatch(screen, action, payload) {
      if (action === "inspect_sheets") {
        inspectionCalls.push([screen, action, payload]);
        return { ok: true, value: options.inspect ? await options.inspect(payload) : {
          ok: true, sheets: payload.path.endsWith(".csv") ? [] : (payload.kind === "pclm"
            ? PCLM_SHEETS : ["S1", "S2", "물품"]).map((name) => ({ name, rows: 3, cols: 2 })),
        } };
      }
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
    popover: { place: () => {}, wireDismiss: () => () => {} },
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
    controller, client, dispatchCalls, inspectionCalls, invokeCalls, modalCalls, confirms, sheetCalls,
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
  const { result } = await opened(h, {
    session: sessionRead({ data_row: sessionRow({ name: "현재" }) }),
  });
  assert.equal(
    h.controller.model.getSnapshot().session.read().data_row.name, "현재");
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

/* 전환 착지의 **증언자**를 못박는다(#728 H7 오진의 자리).
   이 면은 열릴 때 세션 행(`data_row`)으로 *이전* 데이터를 이미 세운다. 그래서 「세션 행이
   있다」·「고정 버튼이 있다」는 새 적재를 증언하지 못한다 — 실 대본이 그 존재로 기다리면
   즉시 통과해 적재 도중에 [닫기]를 누르고, 그 닫기는 busy 계약대로 거절된다(바로 위
   테스트가 그 거절을 이미 못박는다). 이번 적재를 증언하는 것은 **문안** 하나뿐이다:
   open 이 `status:""` 로 비워 두므로 「불러왔습니다」는 이번 browse 가 끝났을 때만 선다. */
test("전환 착지 표식 — 이전 행은 여는 순간 이미 서 있고, 이번 적재는 문안만 증언한다", async () => {
  const h = build({ invoke: async () => ({ label: "파일: 새.csv", rows: 3, path: "C:/새.csv" }) });
  const { result } = await opened(h, {
    session: sessionRead({ data_row: sessionRow({ name: "이전.csv", path: "C:/이전.csv" }) }),
  });

  // 여는 순간: 행을 그리는 값이 **이미** 차 있다. 그 존재는 새 적재를 증언하지 못한다.
  const atOpen = h.controller.model.getSnapshot();
  assert.equal(atOpen.current === undefined, true);
  assert.equal(atOpen.session.read().data_row.name, "이전.csv");
  assert.equal(atOpen.status, "", "open 은 문안을 비운다 — 그래서 문안만이 이번 적재를 증언한다");

  await h.controller.browseFile();

  const landed = h.controller.model.getSnapshot();
  assert.match(landed.status, /불러왔습니다/, "적재 완료 문안이 실 대본의 착지 표식이다");
  assert.equal(landed.loading, false, "착지 문안이 선 시점에 loading 은 이미 풀려 있다");

  h.controller.close();
  await result;
});

/* 세션 행은 **여는 순간의 사본이 아니다**(③b): 이 면 안에서 파일을 새로 열면 마운트가
   바뀌고 작업 스냅샷이 다시 온다. 값으로 얼려 두면 목록 맨 위 행이 이제는 쓰지 않는
   데이터를 「사용 중」이라 말한다 — 조용히 틀리는 자리라 판독기를 함수로 받는다. */
test("세션 행은 렌더마다 다시 읽는다 — 여는 순간의 값을 얼리지 않는다", async () => {
  const h = build();
  let seen = { data_row: sessionRow({ name: "이전.csv" }), data_pool_key: "", sheet: "" };
  const { result } = await opened(h, { session: () => seen });
  const before = renderToStaticMarkup(
    createElement(DataPickerDialog, { controller: h.controller }));
  assert.ok(before.includes("이전.csv"));

  seen = { data_row: sessionRow({ name: "새.csv" }), data_pool_key: "", sheet: "" };
  const after = renderToStaticMarkup(
    createElement(DataPickerDialog, { controller: h.controller }));
  assert.ok(after.includes("새.csv"), "새 마운트가 행에 서지 않았습니다");
  assert.equal(after.includes("이전.csv"), false, "옛 마운트가 「사용 중」으로 남았습니다");

  h.controller.close();
  await result;
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

test("다중 시트 성사 — 확정한 시트의 마운트가 이 session의 착지가 된다", async () => {
  const chosen = { label: "목록.xlsx / S2", rows: 3, path: "C:/목록.xlsx", sheet: "S2" };
  const h = build({ invoke: async () => ({ needs_sheet: true }), choose: async () => chosen });
  const { result } = await opened(h);
  await h.controller.browseFile();
  /* 확정한 시트를 이 면이 따로 기억하지 않는다(③b) — 마운트는 Python 에서 성사했고
     그 재진술은 작업 스냅샷이 든다. 여기 남는 것은 이 세션의 착지 라벨 하나다. */
  assert.match(h.controller.model.getSnapshot().status, /불러왔습니다/);
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
  const { result } = await opened(h, {
    session: sessionRead({ data_row: sessionRow({ name: "현재", path: "" }) }),
  });
  h.controller.openPin();
  assert.equal(h.controller.regModel.getSnapshot(), null);
  h.controller.close(); await result;
});

test("이 데이터 고정 — 세션 행의 이름·경로와 스냅샷 시트를 registration state로 옮긴다", async () => {
  const h = build();
  const { result } = await opened(h, {
    session: sessionRead({
      data_row: sessionRow({ name: "현재", path: "C:/a.xlsx" }), sheet: "S1",
    }),
  });
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

test("등록 확정 — 선언한 여러 시트와 기본 시트를 한 register_excel payload로 보낸다", async () => {
  const h = build();
  h.controller.openRegDialog({ name: " 이름 ", path: " C:/a.xlsx ", sheet: " S1 ", sheets: ["S1", "S2"], note: " 메모 " });
  await tick();
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls[0], ["pool", "register_excel", { name: "이름", path: "C:/a.xlsx", sheet: "S1", sheets: ["S1", "S2"], note: "메모" }]);
  assert.equal(h.controller.regModel.getSnapshot(), null);
});

test("등록 overwrite 거절 — basis 2차 발신 없이 modal을 유지한다", async () => {
  const h = build({ dispatch: async () => ({ needs_confirm: true, basis: "b", confirm_text: "겹침" }), confirm: false });
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx", sheet: "S1" });
  await tick();
  await h.controller.submitReg();
  assert.equal(h.dispatchCalls.length, 1);
  assert.notEqual(h.controller.regModel.getSnapshot(), null);
});

test("등록 overwrite 승인 — confirm+basis를 실은 2차 발신만 확정한다", async () => {
  let count = 0;
  const h = build({ dispatch: async () => (++count === 1 ? { needs_confirm: true, basis: "b", confirm_text: "겹침" } : { ok: true }), confirm: true });
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx", sheet: "S1" });
  await tick();
  await h.controller.submitReg();
  assert.equal(h.dispatchCalls.length, 2);
  assert.equal(h.dispatchCalls[1][2].confirm, true);
  assert.equal(h.dispatchCalls[1][2].basis, "b");
});

test("다시 연결 — 같은 slot key와 편집한 경로를 relink payload로 보낸다", async () => {
  const h = build();
  h.controller.openRegDialog({ targetKey: "slot", name: "이름", path: "C:/old.xlsx" });
  h.controller.patchReg({ path: "C:/new.xlsx" });
  await h.controller.inspectRegSheets();
  h.controller.selectRegSheets(["S2"]);
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls[0], ["pool", "relink", {
    key: "slot", name: "이름", path: "C:/new.xlsx", sheet: "S2", sheets: ["S2"], note: "",
  }]);
});

test("등록 path 찾아보기 — invoke 결과를 현재 registration state에 반영한다", async () => {
  const h = build({ invoke: async (method) => method === "pick_pool_data_file" ? "C:/picked.xlsx" : null });
  h.controller.openRegDialog({ name: "이름", path: "C:/old.xlsx" });
  await h.controller.browseRegPath();
  assert.equal(h.controller.regModel.getSnapshot().path, "C:/picked.xlsx");
  assert.deepEqual(h.inspectionCalls.at(-1), ["pool", "inspect_sheets", { path: "C:/picked.xlsx" }]);
  assert.deepEqual(h.controller.regModel.getSnapshot().sheets, []);

  let picked;
  const late = build({ invoke: () => new Promise((resolve) => { picked = resolve; }) });
  late.controller.openRegDialog({ name: "이름", path: "C:/old.xlsx" });
  const browse = late.controller.browseRegPath();
  late.controller.closeReg();
  late.controller.openRegDialog({ name: "새 등록", path: "C:/new.xlsx" });
  picked("C:/picked.xlsx");
  await browse;
  assert.equal(late.controller.regModel.getSnapshot().path, "C:/new.xlsx");
});

test("등록 시트 선택 — 검사 전·미선택·변경한 경로를 막고 CSV는 빈 선언으로 보낸다", async () => {
  let resolveInspection;
  const h = build({ inspect: () => new Promise((resolve) => { resolveInspection = resolve; }) });
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx" });
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls, []);
  resolveInspection({ ok: true, sheets: [{ name: "S1", rows: 3, cols: 2 }] });
  await tick();
  assert.deepEqual(h.controller.regModel.getSnapshot().sheets, [], "첫 시트는 자동 선택하지 않는다");
  await h.controller.submitReg();
  assert.match(h.controller.regModel.getSnapshot().error, /읽을 시트를 고르세요/);
  h.controller.selectRegSheets(["S1"]);
  h.controller.patchReg({ path: "C:/data.csv" });
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls, [], "경로 변경 뒤 재검사 없는 등록을 막는다");
  const inspection = h.controller.inspectRegSheets();
  resolveInspection({ ok: true, sheets: [] });
  await inspection;
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls[0][2], { name: "이름", path: "C:/data.csv", sheet: "", sheets: [], note: "" });
});

test("등록 검사 — 늦게 온 이전 경로·닫은 창의 결과는 버리고 현재 실패는 표시한다", async () => {
  const pending = [];
  const h = build({ inspect: () => new Promise((resolve) => { pending.push(resolve); }) });
  h.controller.openRegDialog({ name: "이름", path: "C:/old.xlsx", sheet: "S1" });
  h.controller.patchReg({ path: "C:/new.xlsx" });
  const inspection = h.controller.inspectRegSheets();
  pending[0]({ ok: true, sheets: [{ name: "OLD", rows: 1, cols: 1 }] });
  await tick();
  assert.equal(h.controller.regModel.getSnapshot().inspecting, true);
  assert.deepEqual(h.controller.regModel.getSnapshot().availableSheets, []);
  pending[1]({ ok: false, error: "파일 확인 실패" });
  await inspection;
  assert.equal(h.controller.regModel.getSnapshot().error, "파일 확인 실패");
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls, []);
  const retry = h.controller.inspectRegSheets();
  h.controller.closeReg();
  h.controller.openRegDialog({ name: "다른 등록", path: "C:/new.xlsx" });
  pending[2]({ ok: true, sheets: [{ name: "OLD", rows: 1, cols: 1 }] });
  await retry;
  assert.equal(h.controller.regModel.getSnapshot().inspecting, true);
  assert.deepEqual(h.controller.regModel.getSnapshot().availableSheets, []);
  pending[3]({ ok: true, sheets: [{ name: "NEW", rows: 1, cols: 1 }] });
  await tick();
  assert.equal(h.controller.regModel.getSnapshot().availableSheets[0].name, "NEW");
});

test("등록 제출 — 중복 발신을 막고 이전 창의 완료는 새 창을 닫지 않는다", async () => {
  let complete;
  const h = build({ dispatch: () => new Promise((resolve) => { complete = resolve; }) });
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx", sheet: "S1" });
  await tick();
  const submission = h.controller.submitReg();
  await h.controller.submitReg();
  assert.equal(h.dispatchCalls.length, 1);
  assert.equal(h.controller.regModel.getSnapshot().submitting, true);
  h.controller.closeReg();
  h.controller.openRegDialog({ name: "새 등록", path: "C:/new.xlsx" });
  complete({ ok: true });
  await submission;
  assert.equal(h.controller.regModel.getSnapshot().name, "새 등록");
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

/* ── 계약 목록(pclm) 등록 — 엑셀과 좌표만 다른 거울(#937) ──────────────────────────── */

test("계약 목록 진입 — pclm 모드로 열되 DB 자리를 미리 채우지 않고 시트도 비운다", async () => {
  const h = build();
  const { result } = await opened(h);
  h.controller.openPclm();
  await tick();
  const reg = h.controller.regModel.getSnapshot();
  assert.equal(reg.mode, "pclm");
  assert.equal(reg.db, "");              // 다른 프로그램의 설치 자리를 추측하지 않는다
  assert.equal(reg.view, "");            // 시트는 사용자가 확정한다(첫 항목 기본 금지)
  assert.equal(reg.title, "계약 목록 등록");
  assert.deepEqual(h.inspectionCalls, [], "적힌 자리가 없으면 나열하지 않는다");
  h.controller.closeReg(); h.controller.close(); await result;
});

test("계약 목록 등록 — DB를 검사하고 선언한 views와 기본 view를 전달한다", async () => {
  const h = build();
  h.controller.openRegDialog({ mode: "pclm", name: " 계약 ", db: " C:/d/pclm.db ", note: " 메모 " });
  await tick();
  assert.deepEqual(h.inspectionCalls[0], ["pool", "inspect_sheets", { path: "C:/d/pclm.db", kind: "pclm" }]);
  h.controller.selectRegSheets(["v_통합_v2", "v_접수_v1"]);
  h.controller.patchReg({ db: " C:/d/new.db " });
  assert.deepEqual(h.controller.regModel.getSnapshot().sheets, []);
  assert.equal(h.controller.regModel.getSnapshot().view, "");
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls, [], "DB 경로 변경 뒤 검사 없이 이전 시트를 보내지 않는다");
  await h.controller.inspectRegSheets();
  assert.deepEqual(h.inspectionCalls.at(-1)[2], { path: "C:/d/new.db", kind: "pclm" });
  h.controller.selectRegSheets(["v_통합_v2", "v_접수_v1"]);
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls[0], ["pool", "register_pclm", {
    name: "계약", db: "C:/d/new.db", view: "v_통합_v2", views: ["v_통합_v2", "v_접수_v1"], note: "메모",
  }]);
  assert.equal(h.controller.regModel.getSnapshot(), null);
});

test("계약 목록 등록 — 시트가 비면 발신하지 않고 확정을 요구한다", async () => {
  const h = build();
  h.controller.openRegDialog({ mode: "pclm", name: "계약", db: "C:/d/pclm.db" });
  await tick();
  await h.controller.submitReg();
  assert.match(h.controller.regModel.getSnapshot().error, /읽을 시트를 고르세요/);
  assert.deepEqual(h.dispatchCalls, []);
  // 이름이 비어도 같은 자리에서 막는다(파일 경로를 묻지 않는 종류다).
  h.controller.patchReg({ name: "", view: "v_통합_v1", error: "" });
  await h.controller.submitReg();
  assert.match(h.controller.regModel.getSnapshot().error, /이름을 입력하세요/);
  assert.deepEqual(h.dispatchCalls, []);
});

test("계약 목록 등록 — 라벨 갱신 확정도 같은 basis 왕복을 쓴다", async () => {
  let count = 0;
  const h = build({
    dispatch: async () => (++count === 1
      ? { needs_confirm: true, basis: "b", confirm_text: "이미 고정" } : { ok: true }),
    confirm: true,
  });
  h.controller.openRegDialog({ mode: "pclm", name: "통합면", db: "C:/d/pclm.db", view: "v_통합_v2" });
  await tick();
  await h.controller.submitReg();
  assert.equal(h.dispatchCalls.length, 2);
  assert.equal(h.dispatchCalls[1][0] + "/" + h.dispatchCalls[1][1], "pool/register_pclm");
  assert.equal(h.dispatchCalls[1][2].confirm, true);
  assert.equal(h.dispatchCalls[1][2].basis, "b");
});

test("계약 목록 폼 렌더 — 적은 db·미선택 체크박스가 서고 엑셀 경로칸은 없다", async () => {
  const h = build();
  h.controller.openRegDialog({ mode: "pclm", db: "C:/d/pclm.db" });
  await tick();
  const markup = renderToStaticMarkup(
    createElement(PoolRegistrationDialog, { controller: h.controller }));
  assert.ok(markup.includes('id="poolRegDb"'), "DB 자리 입력이 서야 한다");
  assert.ok(markup.includes("C:/d/pclm.db"), "적은 DB 자리를 그대로 보인다");
  assert.ok(markup.includes("사용할 시트"), "라벨은 표면 어휘(시트)로 말한다");
  assert.ok(markup.includes('id="poolRegView"'), "시트 체크박스 그룹이 서야 한다");
  assert.equal(markup.split('type="checkbox"').length - 1, PCLM_SHEETS.length + 1);
  assert.equal(markup.includes('checked=""'), false);
  assert.ok(markup.includes("0개 시트 선택"));
  assert.ok(markup.indexOf('id="poolRegDb"') < markup.indexOf('id="poolRegName"'));
  assert.ok(markup.includes("시트를 고르세요"), "빈 선택의 문안이 서야 한다");
  // 값도 보이는 글자도 그 DB 의 시트 이름 그대로다(엑셀 시트처럼) — 웹이 다시 옮기지 않는다.
  for (const view of PCLM_SHEETS) {
    assert.ok(markup.includes(`>${view}</span>`), view);
  }
  // 좌표가 다른 종류라 경로·시트칸은 묻지 않는다(엑셀 모드에서만 산다).
  assert.equal(markup.includes('id="poolRegPath"'), false);
  assert.equal(markup.includes('id="poolRegSheet"'), false);
  // 등록 모달의 설명 부제는 사라졌다(U4 표면 감량) — 형식 설명은 폼이 이미 말한다.
  assert.equal(markup.includes("modal-sub"), false);
});

test("엑셀 폼 렌더 — 파일의 시트를 이름 있는 체크박스로 보여 주고 등록 선언을 표시한다", async () => {
  const h = build();
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx", sheets: ["S2"] });
  await tick();
  const markup = renderToStaticMarkup(
    createElement(PoolRegistrationDialog, { controller: h.controller }));
  assert.ok(markup.includes('id="poolRegPath"') && markup.includes('id="poolRegSheet"'));
  assert.ok(markup.includes("<legend") && markup.includes("사용할 시트"));
  assert.equal(markup.split('type="checkbox"').length - 1, 4);
  assert.equal(markup.split('checked=""').length - 1, 1);
  assert.ok(markup.includes("1개 시트 선택"));
  const fieldOrder = ["poolRegPath", "poolRegName", "poolRegSheet", "poolRegNote", "poolRegOk"].map((id) => markup.indexOf(`id="${id}"`));
  assert.deepEqual(fieldOrder, [...fieldOrder].sort((a, b) => a - b));
  h.controller.selectRegSheets(["S1", "S2", "물품"]);
  const all = renderToStaticMarkup(createElement(PoolRegistrationDialog, { controller: h.controller }));
  assert.ok(all.includes("3개 시트 선택"));
  assert.ok(markup.includes("전체 선택") && markup.includes("S1") && markup.includes("S2"));
  assert.equal(markup.includes('id="poolRegDb"'), false);
  assert.equal(markup.includes('id="poolRegView"'), false);
  assert.equal(markup.includes("modal-sub"), false);   // 부제는 두 모드 다 사라졌다
});

test("데이터 선택 면 — pclm 진입 버튼은 스냅샷에 기대지 않고 늘 열려 있다", async () => {
  const h = build();
  const a = await opened(h);
  const on = renderToStaticMarkup(
    createElement(DataPickerDialog, { controller: h.controller }));
  assert.ok(on.includes('id="dataPickerPclm"'), "진입 버튼이 실재해야 한다");
  assert.equal(/id="dataPickerPclm"[^>]*disabled/.test(on), false, "물을 좌표는 폼이 묻는다");
  // 괄호는 확장자다 — 저쪽 프로그램 이름은 이 제품의 표면 어휘가 아니다.
  assert.ok(on.includes("계약 목록(.db) 등록…"), "진입 라벨은 확장자로 말한다");
  assert.equal(on.includes("계약 목록(pclm)"), false, "프로젝트 이름은 표면에 서지 않는다");
  // 표면 감량(U4) — 다이얼로그 부제와 「다른 데이터」 설명 두 줄은 사라졌다.
  assert.equal(on.includes("modal-sub"), false);
  assert.equal(on.includes("한 번만 쓸 파일"), false);
  assert.equal(on.includes("DB 자리와 뷰로 가리킵니다"), false);
  h.controller.close(); await a.result;
});

/* 「현재 데이터」는 목록 **첫 행**이다(③b) — 종전 카드의 승계처다. 그 행이 무엇을 말하는지
   (시트·헤더 행·행 수)는 **Python 이 짓는다** (`webapp/pool_column.session_data_row` · 계약은
   `tests/test_webapp_job.py`). 여기서 재는 것은 이 면이 그 문장을 **그대로 옮기는가** 하나다. */
test("현재 데이터 행 — 부제는 Python 문안 그대로이고 웹이 시트 이름을 다시 옮기지 않는다", async () => {
  const h = build();
  /* 계약 목록 시트 이름은 DB 가 가진 이름 그대로 온다(제목표 퇴역, 2026-09-30). 웹이 무엇이든
     다시 옮기고 있으면 원문 부제가 깨진다. */
  const { result } = await opened(h, {
    session: sessionRead({
      data_row: sessionRow({ name: "계약 목록", sub: "시트: v_통합_v2 · 12행", icon: "pclm" }),
    }),
  });
  const markup = renderToStaticMarkup(createElement(DataPickerDialog, { controller: h.controller }));
  assert.ok(markup.includes("시트: v_통합_v2 · 12행"), markup);
  h.controller.close(); await result;

  const legacy = build();
  const b = await opened(legacy, {
    session: sessionRead({ data_row: sessionRow({ sub: "시트: v_구판 · 3행", icon: "pclm" }) }),
  });
  const raw = renderToStaticMarkup(
    createElement(DataPickerDialog, { controller: legacy.controller }));
  assert.ok(raw.includes("시트: v_구판 · 3행"), raw);
  legacy.controller.close(); await b.result;
});

test("고름 표지는 작업 스냅샷이 정한다 — 풀 겨눔이면 그 슬롯 행이 선다", async () => {
  const column = {
    rows: [{
      key: "k1", name: "7월 공고목록", sub: "C:/d/7월.xlsx (물품)", reason: "", warns: [],
      badge_label: "활성", badge_level: "ok", icon: "excel", selectable: true,
      path: "C:/d/7월.xlsx", actions: [{ key: "archive", label: "보관" }],
    }],
    notices: [], empty_hint: "", count_label: "1개", result: { text: "", level: "muted" },
  };
  const h = build({ pool: { column } });
  const { result } = await opened(h, {
    session: sessionRead({ data_row: sessionRow({ name: "7월 공고목록" }), data_pool_key: "k1" }),
  });
  const markup = renderToStaticMarkup(createElement(DataPickerDialog, { controller: h.controller }));
  /* 겨눔이 있는 마운트는 그 슬롯 행이 고름 표지를 든다(세션 행이 아니다) — 그리고 이미
     고정된 참조라 「이 데이터 고정…」은 서지 않는다(같은 파일의 참조가 둘로 갈린다). */
  const pressed = markup.slice(markup.indexOf('aria-pressed="true"'));
  assert.ok(markup.includes('data-key="k1"') && pressed.includes("7월 공고목록"));
  assert.equal(markup.includes('id="dataPickerPin"'), false, "이미 고정된 참조에 고정 문이 섰습니다");
  h.controller.close(); await result;
});

/* ── 등록 데이터 「자세히…」 — 시트의 주인은 이 컨트롤러다(고르기 열 공용 ④) ─────────── */

/** 열 행 하나 + 그 항목의 상세 투영을 든 `pool` 스냅샷(실 백엔드 `screen_pool` 과 같은 모양). */
function poolWithDetail(overrides) {
  const detail = Object.assign({
    key: "k1", name: "7월 공고목록", kind: "excel", kind_label: "엑셀/CSV", status: "active",
    badge_label: "활성", badge_level: "ok", path: "C:/d/7월.xlsx", sheet: "물품",
    sheet_title: "물품", header_row: 2, note: "분기 집계", column_count: 2,
    facts: ["종류 엑셀/CSV", "시트: 물품", "헤더 2행", "메모: 분기 집계"],
    column_summary: "열 2개", columns: ["공고명", "금액"],
    actions: [{ key: "relink", label: "다시 연결…" }, { key: "archive", label: "보관" }],
    error: "",
  }, overrides || {});
  return {
    detail,
    column: {
      rows: [{
        key: "k1", name: "7월 공고목록", sub: "파일: 7월.xlsx · 시트 물품", reason: "",
        warns: [], badge_label: "활성", badge_level: "ok", icon: "excel", selectable: true,
        path: "C:/d/7월.xlsx",
        actions: [{ key: "relink", label: "다시 연결…" }, { key: "archive", label: "보관" }],
      }],
      notices: [], empty_hint: "", count_label: "1개", result: { text: "", level: "muted" },
    },
  };
}

test("행 ⋯ 는 공용 목록 하나다 — 링1 동사 · 「폴더에서 보기」 · 「자세히…」", async () => {
  const h = build({ pool: poolWithDetail() });
  const { result } = await opened(h);
  const row = h.controller.poolModel.getSnapshot().column.rows[0];

  h.controller.toggleRowMenu(row, { id: "more" });
  const items = h.controller.rowContextMenu.model.getSnapshot().items;
  assert.deepEqual(items.map((item) => item.action),
    ["act:relink", "act:archive", "reveal", "detail"]);
  assert.equal(items.at(-1).label, "자세히…");
  h.controller.closeRowMenu();
  h.controller.close(); await result;
});

test("「자세히…」 — 검토 왕복 뒤에 시트를 연다(순서가 계약)", async () => {
  const h = build({ pool: poolWithDetail() });
  const { result } = await opened(h);
  h.dispatchCalls.length = 0;
  h.modalCalls.length = 0;

  await h.controller.openDetail("k1", null);

  assert.deepEqual(h.dispatchCalls.map((row) => [row[0], row[1], row[2]]),
    [["pool", "review", { key: "k1" }]]);
  assert.deepEqual(h.modalCalls.map((row) => [row[0], row[1]]), [["open", "poolDetailModal"]]);
  h.controller.close(); await result;
});

test("「자세히…」 — 상세가 남의 항목이면 시트를 열지 않고 사유를 남긴다", async () => {
  const h = build({ pool: poolWithDetail({ key: "다른키" }) });
  const { result } = await opened(h);
  h.modalCalls.length = 0;

  await h.controller.openDetail("k1", null);

  assert.deepEqual(h.modalCalls, [], "남의 항목 상세 위에 시트가 섰습니다");
  assert.ok(h.controller.model.getSnapshot().status.includes("데이터를 찾을 수 없습니다"));
  h.controller.close(); await result;
});

test("다이얼로그 「다시 연결」 프리필도 상세 투영을 읽는다(옛 목록 소비 0)", async () => {
  const h = build({ pool: poolWithDetail({ sheets: ["물품", "S2"] }) });
  const { result } = await opened(h);
  const row = h.controller.poolModel.getSnapshot().column.rows[0];
  h.dispatchCalls.length = 0;

  h.controller.toggleRowMenu(row, { id: "more" });
  await h.controller.handleRowMenu("act:relink");

  assert.deepEqual(h.dispatchCalls.map((row) => [row[1], row[2]]),
    [["review", { key: "k1" }]]);
  const reg = h.controller.regModel.getSnapshot();
  assert.deepEqual(
    [reg.targetKey, reg.name, reg.path, reg.sheet, reg.note],
    ["k1", "7월 공고목록", "C:/d/7월.xlsx", "물품", "분기 집계"]);
  assert.deepEqual(reg.sheets, ["물품", "S2"]);
  h.controller.close(); await result;
});

test("시트가 열려 있는 동안 동사 실패는 **시트 안**에 선다(스크림 뒤 채널 금지)", async () => {
  const h = build({
    pool: poolWithDetail(),
    dispatch: async (_screen, action) => {
      if (action === "archive") throw new Error("ARCHIVE_REFUSAL");
      return {};
    },
  });
  const { result } = await opened(h);
  await h.controller.openDetail("k1", null);

  await h.controller.handleDetailVerb("act:archive", null);

  const state = h.controller.model.getSnapshot();
  assert.ok(state.detailMessage.includes("ARCHIVE_REFUSAL"), state.detailMessage);
  assert.equal(state.status.includes("ARCHIVE_REFUSAL"), false,
    "같은 문장이 스크림 뒤 상태줄에도 섰습니다");
  h.controller.close(); await result;
});

test("registration close — state를 비우고 poolRegModal만 닫는다", () => {
  const h = build();
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx" });
  h.controller.closeReg();
  assert.equal(h.controller.regModel.getSnapshot(), null);
  assert.deepEqual(h.modalCalls.at(-1).slice(0, 2), ["close", "poolRegModal"]);
});
