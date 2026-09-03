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
  "rowContextMenu", "toggleRowMenu", "closeRowMenu", "handleRowMenu", "popover",
  "openRegDialog", "patchReg", "closeReg", "browseRegPath", "submitReg", "client", "notify",
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

/** 스냅샷이 내려주는 계약 목록 블록(실 백엔드 `_pclm_block` 과 같은 모양).
 *
 * `views` 는 **새로 고르게 할** 것이고(품목 뷰는 1계약 N줄이라 반복 표가 서기 전까지 제외),
 * `titles` 는 이미 선 마운트를 제목으로 그리기 위한 **뷰 전수** 매핑이라 넷이다. */
const PCLM_BLOCK = {
  default_db: "C:/AppData/Local/Pclm/pclm.db",
  views: [
    { name: "v_통합_v1", title: "통합", desc: "공고와 계약을 이어 붙인 표" },
    { name: "v_공고_v1", title: "공고", desc: "공고 정보" },
    { name: "v_계약_v1", title: "계약", desc: "계약 정보" },
  ],
  titles: {
    "v_통합_v1": "통합", "v_공고_v1": "공고", "v_계약_v1": "계약", "v_품목_v1": "품목",
  },
};

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
  services.sheetPicker.bind({
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

/* ── 계약 목록(pclm) 등록 — 엑셀과 좌표만 다른 거울(#937) ──────────────────────────── */

test("계약 목록 진입 — pclm 모드로 열고 기본 DB 자리를 프리필하며 시트는 비운다", async () => {
  const h = build({ pool: { rows: [], duplicates: [], corrupted: [], pclm: PCLM_BLOCK } });
  const { result } = await opened(h);
  h.controller.openPclm();
  const reg = h.controller.regModel.getSnapshot();
  assert.equal(reg.mode, "pclm");
  assert.equal(reg.db, PCLM_BLOCK.default_db);
  assert.equal(reg.view, "");            // 시트는 사용자가 확정한다(첫 항목 기본 금지)
  assert.equal(reg.title, "계약 목록 등록");
  h.controller.closeReg(); h.controller.close(); await result;
});

test("계약 목록 진입 — 스냅샷에 블록이 없으면 열지 않고 사유를 말한다", async () => {
  const h = build({ pool: { rows: [], duplicates: [], corrupted: [] } });
  const { result } = await opened(h);
  h.controller.openPclm();
  assert.equal(h.controller.regModel.getSnapshot(), null);
  assert.match(h.controller.model.getSnapshot().status, /계약 목록 정보/);
  h.controller.close(); await result;
});

test("계약 목록 등록 — register_pclm payload는 name·db·view·note다", async () => {
  const h = build({ pool: { rows: [], duplicates: [], corrupted: [], pclm: PCLM_BLOCK } });
  h.controller.openRegDialog({ mode: "pclm", name: " 계약 ", db: " C:/d/pclm.db ", note: " 메모 " });
  h.controller.patchReg({ view: "v_공고_v1" });
  await h.controller.submitReg();
  assert.deepEqual(h.dispatchCalls[0], ["pool", "register_pclm", {
    name: "계약", db: "C:/d/pclm.db", view: "v_공고_v1", note: "메모",
  }]);
  assert.equal(h.controller.regModel.getSnapshot(), null);
});

test("계약 목록 등록 — 시트가 비면 발신하지 않고 확정을 요구한다", async () => {
  const h = build();
  h.controller.openRegDialog({ mode: "pclm", name: "계약", db: "C:/d/pclm.db" });
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
  h.controller.openRegDialog({ mode: "pclm", name: "통합면", db: "C:/d/pclm.db", view: "v_통합_v1" });
  await h.controller.submitReg();
  assert.equal(h.dispatchCalls.length, 2);
  assert.equal(h.dispatchCalls[1][0] + "/" + h.dispatchCalls[1][1], "pool/register_pclm");
  assert.equal(h.dispatchCalls[1][2].confirm, true);
  assert.equal(h.dispatchCalls[1][2].basis, "b");
});

test("계약 목록 폼 렌더 — db 프리필·시트 select(placeholder 포함)가 서고 경로·시트칸은 없다", () => {
  const h = build({ pool: { rows: [], duplicates: [], corrupted: [], pclm: PCLM_BLOCK } });
  h.controller.openRegDialog({ mode: "pclm", db: PCLM_BLOCK.default_db });
  const markup = renderToStaticMarkup(
    createElement(PoolRegistrationDialog, { controller: h.controller }));
  assert.ok(markup.includes('id="poolRegDb"'), "DB 자리 입력이 서야 한다");
  assert.ok(markup.includes(PCLM_BLOCK.default_db), "기본 자리를 프리필한다");
  assert.ok(markup.includes("읽을 시트"), "라벨은 표면 어휘(시트)로 말한다");
  assert.ok(markup.includes('id="poolRegView"'), "시트 select 가 서야 한다");
  assert.equal(markup.split("<option").length - 1, PCLM_BLOCK.views.length + 1,
    "고르게 할 시트 + 빈 placeholder");
  assert.ok(markup.includes("시트를 고르세요"), "빈 선택의 문안이 서야 한다");
  // 값은 실 뷰 이름(백엔드 계약), 보이는 글자는 제목 — 표면에 내부 이름은 서지 않는다.
  for (const view of PCLM_BLOCK.views) {
    assert.ok(markup.includes(`value="${view.name}"`), view.name);
    assert.ok(markup.includes(`${view.title} — ${view.desc}`), view.title);
  }
  assert.equal(/>[^<]*v_[^<]*</.test(markup), false, "옵션 글자에 내부 이름이 새면 안 된다");
  // 좌표가 다른 종류라 경로·시트칸은 묻지 않는다(엑셀 모드에서만 산다).
  assert.equal(markup.includes('id="poolRegPath"'), false);
  assert.equal(markup.includes('id="poolRegSheet"'), false);
  // 등록 모달의 설명 부제는 사라졌다(U4 표면 감량) — 형식 설명은 폼이 이미 말한다.
  assert.equal(markup.includes("modal-sub"), false);
});

test("엑셀 폼 렌더 — 기존 좌표만 서고 pclm 필드는 나오지 않는다", () => {
  const h = build({ pool: { rows: [], duplicates: [], corrupted: [], pclm: PCLM_BLOCK } });
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx" });
  const markup = renderToStaticMarkup(
    createElement(PoolRegistrationDialog, { controller: h.controller }));
  assert.ok(markup.includes('id="poolRegPath"') && markup.includes('id="poolRegSheet"'));
  assert.equal(markup.includes('id="poolRegDb"'), false);
  assert.equal(markup.includes('id="poolRegView"'), false);
  assert.equal(markup.includes("modal-sub"), false);   // 부제는 두 모드 다 사라졌다
});

test("데이터 선택 면 — pclm 진입 버튼은 블록이 있을 때만 활성이고 사유를 병기한다", async () => {
  const withBlock = build({ pool: { rows: [], duplicates: [], corrupted: [], pclm: PCLM_BLOCK } });
  const a = await opened(withBlock);
  const on = renderToStaticMarkup(
    createElement(DataPickerDialog, { controller: withBlock.controller }));
  assert.ok(on.includes('id="dataPickerPclm"'), "진입 버튼이 실재해야 한다");
  assert.equal(on.includes('id="dataPickerPclm" disabled'), false);
  // 괄호는 확장자다 — 저쪽 프로그램 이름은 이 제품의 표면 어휘가 아니다.
  assert.ok(on.includes("계약 목록(.db) 등록…"), "진입 라벨은 확장자로 말한다");
  assert.equal(on.includes("계약 목록(pclm)"), false, "프로젝트 이름은 표면에 서지 않는다");
  // 표면 감량(U4) — 다이얼로그 부제와 「다른 데이터」 설명 두 줄은 사라졌다.
  assert.equal(on.includes("modal-sub"), false);
  assert.equal(on.includes("한 번만 쓸 파일"), false);
  assert.equal(on.includes("DB 자리와 뷰로 가리킵니다"), false);
  withBlock.controller.close(); await a.result;

  const without = build({ pool: { rows: [], duplicates: [], corrupted: [] } });
  const b = await opened(without);
  const off = renderToStaticMarkup(
    createElement(DataPickerDialog, { controller: without.controller }));
  assert.ok(off.includes('id="dataPickerPclm"'), "숨기지 않는다 — 비활성 + 사유다");
  assert.ok(/id="dataPickerPclm"[^>]*disabled/.test(off), "블록이 없으면 비활성이다");
  assert.ok(off.includes("계약 목록 정보를 아직 읽지 못했습니다"), "사유를 title 로 병기한다");
  without.controller.close(); await b.result;
});

/* 「현재 데이터」는 목록 **첫 행**이다(③b) — 종전 카드의 승계처다. 그 행이 무엇을 말하는지
   (시트·헤더 행·행 수, 계약 목록의 뷰 이름 제목화)는 **Python 이 짓는다**
   (`webapp/pool_column.session_data_row` · 계약은 `tests/test_webapp_job.py`). 여기서 재는
   것은 이 면이 그 문장을 **그대로 옮기는가** 하나다. */
test("현재 데이터 행 — 부제는 Python 문안 그대로이고 웹이 제목표를 다시 조회하지 않는다", async () => {
  const h = build({ pool: { rows: [], duplicates: [], corrupted: [], pclm: PCLM_BLOCK } });
  /* 양성·음성 한 쌍: 스냅샷이 이미 제목으로 옮긴 부제는 그대로 서고, 스냅샷이 원문
     그대로 둔 이름(구판·손편집)도 **감추거나 다시 옮기지 않는다**. 웹이 `pclm.titles` 를
     다시 조회하고 있으면 아래 둘째 단언이 빨강이 된다(같은 상태 두 곳 판정). */
  const { result } = await opened(h, {
    session: sessionRead({
      data_row: sessionRow({ name: "계약 목록", sub: "시트: 통합 · 12행", icon: "pclm" }),
    }),
  });
  const markup = renderToStaticMarkup(createElement(DataPickerDialog, { controller: h.controller }));
  assert.ok(markup.includes("시트: 통합 · 12행"), markup);
  assert.equal(markup.includes("v_통합_v1"), false, "내부 이름은 행에 서지 않는다");
  h.controller.close(); await result;

  const legacy = build({ pool: { rows: [], duplicates: [], corrupted: [], pclm: PCLM_BLOCK } });
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
  const h = build({ pool: { rows: [], duplicates: [], corrupted: [], column } });
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

test("registration close — state를 비우고 poolRegModal만 닫는다", () => {
  const h = build();
  h.controller.openRegDialog({ name: "이름", path: "C:/a.xlsx" });
  h.controller.closeReg();
  assert.equal(h.controller.regModel.getSnapshot(), null);
  assert.deepEqual(h.modalCalls.at(-1).slice(0, 2), ["close", "poolRegModal"]);
});
