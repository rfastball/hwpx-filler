/* R4-02 — 시트 선택 확정 게이트(`frontend/src/screens/sheet_picker.ts`)의 계약.
 *
 * 전신은 `n05_services.test.js` 의 SheetPicker 절이었다. 그쪽은 「재사용 서비스 팩토리」를
 * 묻는 파일이고, 시트 선택은 R4-02 에서 그 주어를 떠나 화면 표면이 됐다 — 같은 성질을 두
 * 곳이 재면 한쪽만 늙는다.
 *
 * 계약은 한 줄로 안 바뀐다(#33 · confirm-or-alarm): **조용한 첫 시트 로드 금지**.
 * `pick_data_file` 이 `{needs_sheet, …}` 를 돌려주면 사용자가 시트를 명시로 고른 뒤에만
 * `load_data_sheet` 가 나간다. 취소·Escape·배경 닫기는 겨눔 전체를 중단한다 — 첫 시트로
 * 강등하지 않는다. 로드가 **아예 일어나지 않는 것**이 취소의 의미다.
 *
 * 관측점이 옮겨졌다. legacy 는 「확정 즉시 클릭 리스너를 걷는다」로 이중 로드를 막았고 그
 * 리스너 수가 관측면이었다. React 소유에서는 리스너가 없다 — 같은 성질이 **버튼 disabled +
 * settled 플래그**로 서므로 여기서는 「두 번째 클릭이 로드를 늘리지 않는다」를 직접 잰다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createSheetPickerController } from "../../frontend/src/screens/sheet_picker.ts";

const SRC = readFileSync(
  new URL("../../frontend/src/screens/sheet_picker.ts", import.meta.url), "utf8");

const PAYLOAD = {
  name: "d.xlsx", path: "D:\\d.xlsx",
  sheets: [{ name: "S1", rows: 1, cols: 1 }, { name: "S2", rows: 2, cols: 2 }],
};

function build(options = {}) {
  const loads = [];
  const modalCalls = [];
  let openSpec = null;
  const controller = createSheetPickerController({
    doc: { querySelector: () => null },
    client: {
      async invoke(method, ...args) {
        loads.push([method, ...args]);
        if (options.invoke) return options.invoke(method, ...args);
        return { ok: true, value: { label: "L" } };
      },
    },
    modal: {
      open(id, spec) { modalCalls.push(["open", id]); openSpec = spec; },
      close(id) { modalCalls.push(["close", id]); },
    },
  });
  return {
    controller, loads, modalCalls,
    close: () => openSpec?.onClose?.(),
    session: () => controller.model.getSnapshot(),
  };
}

test("공개 표면 — port 는 choose 하나뿐이고 상태는 controller 가 든다", () => {
  const h = build();
  assert.deepEqual(Object.keys(h.controller.port), ["choose"]);
  assert.deepEqual(Object.keys(h.controller).sort(), ["cancel", "doc", "model", "pick", "port"]);
});

test("명시 클릭 뒤에만 load_data_sheet 가 나가고 descriptor 를 그대로 돌려준다", async () => {
  const h = build();
  const promise = h.controller.port.choose("job", PAYLOAD);
  assert.deepEqual(h.loads, [], "창이 열린 것만으로는 아무것도 로드하지 않는다");
  assert.equal(h.session().sheets.length, 2);

  await h.controller.pick("S2");
  assert.deepEqual(h.loads, [["load_data_sheet", "job", "D:\\d.xlsx", "S2"]],
    "고른 그 시트가 인자로 나간다");
  assert.deepEqual(await promise, { label: "L" });
  assert.deepEqual(h.modalCalls, [["open", "sheetModal"], ["close", "sheetModal"]]);
});

test("음성 — 취소는 null 로 중단한다(첫 시트 강등 0)", async () => {
  const h = build();
  const promise = h.controller.port.choose("job", PAYLOAD);
  h.close();
  assert.equal(await promise, null);
  assert.deepEqual(h.loads, [], "취소의 의미는 「로드가 아예 일어나지 않는 것」이다");
  assert.equal(h.session(), null);
});

test("음성 — 닫힘은 경로를 가리지 않는다(취소 버튼·Escape·배경이 같은 통지)", async () => {
  const h = build();
  const promise = h.controller.port.choose("job", PAYLOAD);
  h.controller.cancel();                 // 취소 버튼 → modal.close
  assert.deepEqual(h.modalCalls.at(-1), ["close", "sheetModal"]);
  h.close();                             // 모달이 되돌리는 닫힘 통지
  assert.equal(await promise, null);
  assert.deepEqual(h.loads, []);
});

test("음성 — 확정 뒤 추가 클릭이 둘째 로드를 태우지 않는다(이중 로드 금지)", async () => {
  const h = build();
  const promise = h.controller.port.choose("job", PAYLOAD);
  await h.controller.pick("S1");
  await promise;
  await h.controller.pick("S2");
  await h.controller.pick("S1");
  assert.equal(h.loads.length, 1, "정산이 끝난 겨눔은 다시 로드하지 않는다");
});

test("음성 — 로드가 나가는 동안 온 둘째 클릭도 삼켜진다(picking 잠금)", async () => {
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const h = build({ invoke: async () => { await held; return { ok: true, value: { label: "L" } }; } });
  const promise = h.controller.port.choose("job", PAYLOAD);
  const first = h.controller.pick("S1");
  assert.equal(h.session().picking, true, "잠금은 표면에도 보인다(버튼 disabled 의 근거)");
  await h.controller.pick("S2");
  assert.equal(h.loads.length, 1);
  release();
  await first;
  assert.deepEqual(await promise, { label: "L" });
});

test("음성 — 정산 뒤 늦게 온 닫힘 통지는 약속을 다시 해소하지 않는다(settle-once)", async () => {
  const h = build();
  const promise = h.controller.port.choose("job", PAYLOAD);
  await h.controller.pick("S1");
  assert.deepEqual(await promise, { label: "L" });
  h.close();
  h.close();
  assert.equal(h.modalCalls.filter((row) => row[0] === "close").length, 1,
    "close 는 정산 때 1회뿐 — 늦은 통지가 두 번째 정산을 만들지 않는다");
  assert.deepEqual(await promise, { label: "L" }, "이미 해소된 약속의 값은 안 바뀐다");
});

test("실패는 ERROR: 문자열로 되돌아온다 — 조용한 null 로 접히지 않는다", async () => {
  const h = build({ invoke: async () => ({ ok: false, failure: { message: "시트를 읽지 못했습니다" } }) });
  const promise = h.controller.port.choose("job", PAYLOAD);
  await h.controller.pick("S1");
  const result = await promise;
  assert.equal(typeof result, "string");
  assert.match(result, /^ERROR:/);
  assert.match(result, /시트를 읽지 못했습니다/);
});

test("음성 — 창이 열려 있는 동안 둘째 choose 는 시끄럽게 거절된다", async () => {
  const h = build();
  const promise = h.controller.port.choose("job", PAYLOAD);
  await assert.rejects(() => h.controller.port.choose("editor", PAYLOAD), /이미 열려 있습니다/);
  h.close();
  assert.equal(await promise, null);
});

test("포트 교체 — 갈아끼운 client.invoke 를 다음 로드가 본다(프로브 경로 생존)", async () => {
  const seen = [];
  const client = {
    async invoke(_method, ...args) { seen.push(["A", ...args]); return { ok: true, value: { label: "L" } }; },
  };
  let openSpec = null;
  const controller = createSheetPickerController({
    doc: { querySelector: () => null },
    client,
    modal: { open: (_id, spec) => { openSpec = spec; }, close: () => {} },
  });
  const pick = async () => {
    const promise = controller.port.choose("job", PAYLOAD);
    await controller.pick("S1");
    return promise;
  };
  assert.deepEqual(await pick(), { label: "L" });
  client.invoke = async (_method, ...args) => {   // 프로브가 하는 일
    seen.push(["B", ...args]);
    return { ok: true, value: { label: "L2" } };
  };
  assert.deepEqual(await pick(), { label: "L2" });
  assert.deepEqual(seen.map((row) => row[0]), ["A", "B"]);
  void openSpec;
});

test("모델 구독 — 해제 뒤에는 알림이 오지 않는다", async () => {
  const h = build();
  let count = 0;
  const release = h.controller.model.subscribe(() => { count += 1; });
  const promise = h.controller.port.choose("job", PAYLOAD);
  assert.equal(count, 1, "세션이 서면 표면이 다시 그려진다");
  release();
  h.close();
  assert.equal(count, 1);
  assert.equal(await promise, null);
});

test("소스 음성 — 제품 전역 조회 0, 자기 listener 소유 0, 첫 시트 자동 선택 0", () => {
  const code = SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.equal(/(?:window|globalThis)\.[A-Za-z_$]/.test(code), false, "제품 전역 조회·생산 0");
  assert.equal(code.includes("addEventListener("), false, "리스너 소유는 React event props 다");
  /* 「첫 시트」 라는 개념이 코드에 없다 — `data-first` 는 **포커스**의 자리이지 선택이 아니다.
     그 둘이 한 이름을 쓰면 언젠가 포커스가 선택으로 승격한다. */
  assert.ok(code.includes('"data-first"'), "첫 옵션은 포커스만 받는다(양성 대조)");
  assert.equal(/pick\(\s*sheets\[0\]/.test(code), false, "첫 시트 자동 선택 금지");
  assert.equal(/sheets\[0\]\.name/.test(code), false, "첫 시트 이름을 값으로 집지 않는다");
  const names = [...SRC.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual(names, ["createSheetPickerController", "SheetPickerDialog"]);
});
