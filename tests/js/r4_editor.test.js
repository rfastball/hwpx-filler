/* R4-02 — React 편집기 controller 의 행동 계약.
 *
 * `n06_editor.test.js` 가 화면의 **경계**(표면·멱등·포트·음성 구조)를 재고, 이 파일은 그
 * 안에서 일어나는 일을 잰다: draft 소유, 커밋 정산, 탭 이동 3택, 라이브러리 관리 동사,
 * TXT 저작 모달, 그룹 이동 다이얼로그, 어포던스 잠금.
 *
 * 두 축이 이 파일의 이유다:
 *
 *  ① legacy 가 DOM 안에 숨겨 둔 상태(열린 메뉴 · 커밋 전 타이핑 · 진행 중 가져오기)가 전부
 *     값이 됐다. 값이 되면 잴 수 있다 — 그래서 여기 음성 대조가 선다.
 *  ② `createMoveDialog` 의 후계(`GroupMoveDialog`)와 그 **순서 계약**(확정 mutation 은 초점을
 *     되돌린 뒤에 나간다)이 여기로 옮겨 왔다. legacy 짝은 `n05_services.test.js` 의
 *     「인스턴스는 자기 confirm 상태만 든다」 였다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ContextMenu } from "../../frontend/src/screens/context_menu.ts";
import { createEditorController } from "../../frontend/src/screens/editor.ts";
import { createGroupMoveDialog } from "../../frontend/src/screens/group_move_dialog.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";
import { createScreenRuntime } from "../../frontend/src/screens/runtime.ts";
import { createSnapshotStore } from "../../frontend/src/state/store.ts";
import { Intent } from "../../frontend/js/intent.js";
import {
  NAME_FIELD, rowField, valueOf,
} from "../../frontend/src/screens/editor_state.ts";

const tick = () => new Promise((resolve) => setImmediate(resolve));

/* 조준은 선택자를 조립하며 표준 Web API `CSS.escape` 를 쓴다(legacy `job.js` 와 같은 형태).
   node 에는 그 전역이 없어 여기서만 최소 대역을 깐다 — 제품 전역이 아니라 플랫폼 API 다. */
globalThis.CSS ??= { escape: (value) => String(value).replace(/["\\]/g, "\\$&") };

const BASE = {
  section: "binding",
  sections: ["template", "binding", "filename"],
  name: "작업A", pattern: "{{이름}}", editing_origin: "작업A",
  revisions: { binding: 1, template: 1 },
  rows: [{ index: 0, source: "성명", type: "text", fmt: "", const: "" }],
  library: {},
};

function build(options = {}) {
  const trace = [];
  const notices = [];
  const modalOpens = [];
  const undoToasts = [];
  let openSpec = null;
  const client = {
    async initial() { return { ok: true, value: options.snapshot ?? BASE }; },
    async dispatch(screen, action, payload) {
      trace.push(["dispatch", screen, action, payload]);
      if (options.dispatchFails?.(screen, action)) throw new Error("백엔드 거절");
      if (options.dispatch) return { ok: true, value: await options.dispatch(screen, action, payload) };
      return { ok: true, value: {} };
    },
    async invoke(method, ...args) {
      trace.push(["invoke", method, ...args]);
      if (options.invoke) return { ok: true, value: await options.invoke(method, ...args) };
      return { ok: true, value: null };
    },
  };
  const store = createSnapshotStore({ alarm: assert.fail });
  const runtime = createScreenRuntime({ client, store });
  const ports = createScreenPorts();
  ports.jobRead.bindReact({ refreshList() {}, openBrowseNeedsAction: async () => {} });
  ports.editorEntry.bindReact({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {},
    confirmDiscard: async () => options.confirmDiscard ?? true,
    restoreEntryFocus() {},
  });
  const services = createServiceHandoffPorts();
  services.sheetPicker.bindReact({
    choose: async (screen, payload) => {
      trace.push(["sheetPicker.choose", screen, payload]);
      return options.sheetChoice ?? null;
    },
  });
  const groupMove = createGroupMoveDialog({
    modal: {
      open: (id, spec) => { modalOpens.push(id); openSpec = spec; },
      close: (id) => { trace.push(["modal.close", id]); openSpec?.onClose?.(); },
    },
  });
  const controller = createEditorController({
    doc: { getElementById: () => null, querySelector: () => null },
    runtime, client, ports, services,
    modal: {
      confirm: async (spec) => { trace.push(["modal.confirm", spec]); return options.confirm ?? false; },
      prompt: async (spec) => { trace.push(["modal.prompt", spec]); return options.prompt ?? null; },
      choose: async (spec) => { trace.push(["modal.choose", spec]); return options.choose ?? null; },
      open: (id, spec) => { modalOpens.push(id); openSpec = spec; },
      close: (id) => { trace.push(["modal.close", id]); },
    },
    undo: { show: (message, action) => undoToasts.push([message, action]) },
    popover: { place() {}, wireDismiss: () => () => {} },
    groupMove,
    chain: Intent,
    navigation: { go() {}, refresh: async () => {} },
    notify: (message) => notices.push(String(message)),
  });
  return {
    controller, groupMove, store, trace, notices, modalOpens, undoToasts,
    actions: () => trace.filter((row) => row[0] === "dispatch").map((row) => [row[1], row[2], row[3]]),
    editorSpec: () => openSpec,
    async ready() { await controller.init(); },
  };
}

/* ================= draft 소유 — controller 층 통합 ================= */

test("push 는 타이핑 중인 칸을 덮지 않고 이웃 칸만 갱신한다", async () => {
  const h = build();
  await h.ready();
  h.controller.type(NAME_FIELD, "치는 중");
  h.store.ingest("editor", { ...BASE, name: "서버가 민 이름", pattern: "{{새 규칙}}" });
  assert.equal(valueOf(h.controller.draftModel.getSnapshot(), NAME_FIELD), "치는 중");
  assert.equal(valueOf(h.controller.draftModel.getSnapshot(), "pattern"), "{{새 규칙}}");
});

test("commitField — dirty 가 아니면 발신하지 않는다(무변경 왕복 0)", async () => {
  const h = build();
  await h.ready();
  h.controller.commitField(NAME_FIELD);
  assert.deepEqual(h.actions(), []);
  h.controller.type(NAME_FIELD, "새 이름");
  h.controller.commitField(NAME_FIELD);
  await tick();
  assert.deepEqual(h.actions(), [["editor", "set_name", { name: "새 이름" }]]);
});

test("flushPendingEdits — blur 없이 온 행동도 dirty draft를 먼저 발신한다", async () => {
  const h = build();
  await h.ready();
  h.controller.type(NAME_FIELD, "버튼보다 먼저 친 이름");
  await h.controller.flushPendingEdits();
  assert.deepEqual(h.actions(), [
    ["editor", "set_name", { name: "버튼보다 먼저 친 이름" }],
  ]);
});

test("flushPendingEdits — blur가 이미 올린 field를 중복 발신하지 않는다", async () => {
  const h = build();
  await h.ready();
  h.controller.type(NAME_FIELD, "한 번만 보낼 이름");
  h.controller.commitField(NAME_FIELD);
  await h.controller.flushPendingEdits();
  assert.deepEqual(h.actions(), [
    ["editor", "set_name", { name: "한 번만 보낼 이름" }],
  ]);
});

test("commit 성공은 Python 확인 전까지 draft 를 clean 으로 올리지 않는다", async () => {
  const h = build();
  await h.ready();
  h.controller.type(NAME_FIELD, "새 이름");
  h.controller.commitField(NAME_FIELD);
  await tick();
  const afterCommit = h.controller.draftModel.getSnapshot();
  assert.equal(afterCommit.fields[NAME_FIELD].dirty, true, "보낸 것이 곧 저장된 것은 아니다");
  assert.equal(afterCommit.fields[NAME_FIELD].pendingToken, 0, "대기는 풀렸다");

  h.store.ingest("editor", { ...BASE, name: "새 이름" });
  assert.equal(h.controller.draftModel.getSnapshot().fields[NAME_FIELD].dirty, false,
    "Python 이 새 값을 확인해 주면 그때 clean 이다");
});

test("음성 — 커밋 실패는 draft 를 되돌리지 않고 사유를 재진술한다", async () => {
  const h = build({ dispatchFails: (_s, action) => action === "set_name" });
  await h.ready();
  h.controller.type(NAME_FIELD, "중복 이름");
  h.controller.commitField(NAME_FIELD);
  await tick();
  assert.equal(valueOf(h.controller.draftModel.getSnapshot(), NAME_FIELD), "중복 이름");
  assert.deepEqual(h.notices, ["백엔드 거절"]);
});

test("행 커밋은 축마다 자기 액션·페이로드로 나간다(표로 감추지 않는다)", async () => {
  const h = build();
  await h.ready();
  h.controller.commitRow(0, "type", "date");
  h.controller.commitRow(0, "const", "고정값");
  await tick();
  assert.deepEqual(h.actions(), [
    ["editor", "set_type", { index: 0, type: "date" }],
    ["editor", "set_const", { index: 0, const: "고정값" }],
  ]);
});

test("commitRowOnBlur — 손대지 않은 칸에서 떠나도 발신 0", async () => {
  const h = build();
  await h.ready();
  h.controller.commitRowOnBlur(0, "source");
  await tick();
  assert.deepEqual(h.actions(), []);
  h.controller.type(rowField(0, "source"), "이름");
  h.controller.commitRowOnBlur(0, "source");
  await tick();
  assert.deepEqual(h.actions(), [["editor", "set_source", { index: 0, source: "이름" }]]);
});

test("음성 — 구독 해제 뒤 도착한 push 는 옛 구독자에게 알리지 않는다(unmount 뒤 late push)", async () => {
  const h = build();
  await h.ready();
  let draftNotices = 0;
  let viewNotices = 0;
  const releaseDraft = h.controller.draftModel.subscribe(() => { draftNotices += 1; });
  const releaseView = h.controller.viewModel.subscribe(() => { viewNotices += 1; });
  h.store.ingest("editor", { ...BASE, name: "1" });
  assert.equal(draftNotices, 1);
  releaseDraft();
  releaseView();
  h.store.ingest("editor", { ...BASE, name: "2" });
  h.controller.setFold(true);
  assert.equal(draftNotices, 1, "해제된 구독자에게 알림 0");
  assert.equal(viewNotices, 0);
  assert.equal(h.controller.model.getSnapshot().name, "2", "화면 상태 자체는 계속 산다");
});

/* ================= 탭 이동 3택 ================= */

test("gotoSection — 가드가 없으면 곧장 이동한다", async () => {
  const h = build();
  await h.ready();
  await h.controller.gotoSection("filename");
  assert.deepEqual(h.actions(), [["editor", "goto_section", { section: "filename" }]]);
});

test("gotoSection — 가드가 서면 3택을 묻고 처분을 실어 다시 보낸다", async () => {
  const h = build({
    choose: "discard",
    dispatch: (_s, action) => (action === "goto_section"
      ? { needs_section_guard: true, section: "binding", section_label: "필드 연결·표시" }
      : {}),
  });
  await h.ready();
  await h.controller.gotoSection("filename");
  assert.deepEqual(h.actions().map((row) => row[1]),
    ["goto_section", "discard_patch", "goto_section"]);
  assert.deepEqual(h.actions().at(-1)[2], { section: "filename", disposition: "discard" });
});

test("음성 — gotoSection 의 stay 는 아무것도 버리지 않고 탭도 안 바뀐다", async () => {
  const h = build({
    choose: "stay",
    dispatch: (_s, action) => (action === "goto_section"
      ? { needs_section_guard: true, section: "binding", section_label: "필드 연결·표시" }
      : {}),
  });
  await h.ready();
  await h.controller.gotoSection("filename");
  assert.deepEqual(h.actions().map((row) => row[1]), ["goto_section"]);
});

/* ================= 라이브러리 관리 메뉴 ================= */

test("메뉴 토글 — 같은 자리를 다시 누르면 닫힌다(#215 동류의 경합 방지)", async () => {
  const h = build({
    snapshot: {
      ...BASE,
      library: { hwpx: { sections: [{ items: [{ key: "k1", name: "T1", path: "P", group: "가" }] }], group_names: ["가"] } },
    },
  });
  await h.ready();
  const trigger = { id: "btn" };
  h.controller.toggleLibMenu("hwpx", "row", "k1", trigger);
  assert.equal(h.controller.isLibMenuOpen(), true);
  h.controller.toggleLibMenu("hwpx", "row", "k1", trigger);
  assert.equal(h.controller.isLibMenuOpen(), false);
  assert.equal(h.controller.libContextMenu.model.getSnapshot(), null);
});

test("메뉴의 Python 유래 값은 React text node로 렌더되어 markup이 될 수 없다", async () => {
  const hostile = '<img src=x onerror="alert(1)">';
  const h = build({
    snapshot: {
      ...BASE,
      library: {
        hwpx: {
          sections: [{ items: [{
            key: "k1", name: "T1", path: "P",
            actions: [{ key: "compile", label: hostile }],
          }] }],
        },
      },
    },
  });
  await h.ready();
  h.controller.toggleLibMenu("hwpx", "row", "k1", { id: "btn" });

  const html = renderToStaticMarkup(createElement(ContextMenu, {
    id: "tplRowMenu",
    controller: h.controller.libContextMenu,
    popover: { place() {}, wireDismiss: () => () => {} },
    triggerSelector: ".job-more",
    onDismiss() {},
    onSelect() {},
  }));
  assert.equal(html.includes("<img"), false, "Python 문안이 element markup으로 해석되면 안 된다");
  assert.ok(html.includes("&lt;img"), "React text node가 위험 문자를 escape한다");
  assert.ok(html.includes('data-context-menu-action="act:compile"'));
});

test("삭제는 되돌리기 토스트를 세우고 되돌리기가 실패하면 시끄럽다", async () => {
  const h = build({
    snapshot: {
      ...BASE,
      library: { hwpx: { sections: [{ items: [{ key: "k1", name: "T1", path: "P" }] }] } },
    },
    dispatch: (_s, action) => {
      if (action === "delete") return { undo: true };
      if (action === "undo_delete") return { ok: false, error: "이미 덮어썼습니다" };
      return {};
    },
  });
  await h.ready();
  h.controller.toggleLibMenu("hwpx", "row", "k1", { id: "btn" });
  await h.controller.handleLibMenu("delete");
  assert.equal(h.undoToasts.length, 1);
  assert.match(h.undoToasts[0][0], /템플릿 'T1'/);
  await assert.rejects(() => h.undoToasts[0][1](), /이미 덮어썼습니다/,
    "되돌리기 실패는 토스트 소비자가 재진술하도록 올라간다");
});

test("refreshLibrary 는 tpl 채널로 나가고 화면은 재당김으로 되그린다", async () => {
  const h = build();
  await h.ready();
  await h.controller.refreshLibrary();
  assert.deepEqual(h.actions(), [["tpl", "refresh", {}]]);
});

/* ================= 그룹 이동 다이얼로그 — createMoveDialog 의 후계 ================= */

test("그룹 이동 — 확정 mutation 은 초점을 되돌린 **뒤에** 나간다(H-16 순서)", async () => {
  const h = build({
    snapshot: {
      ...BASE,
      library: {
        hwpx: {
          sections: [{ items: [{ key: "k1", name: "T1", path: "P", group: "가" }] }],
          group_names: ["가", "나"],
        },
      },
    },
  });
  await h.ready();
  h.controller.toggleLibMenu("hwpx", "row", "k1", { id: "btn" });
  await h.controller.handleLibMenu("move");
  assert.deepEqual(h.modalOpens, ["tplMoveModal"]);
  assert.deepEqual(h.groupMove.model.getSnapshot().groups, ["가", "나"]);
  assert.equal(h.groupMove.model.getSnapshot().choice, "가", "현재 그룹이 초기 선택이다");
  assert.deepEqual(h.actions(), [], "여는 것만으로는 아무것도 안 바뀐다");

  h.groupMove.patch({ choice: "나" });
  h.groupMove.confirm();
  await tick();
  const closeAt = h.trace.findIndex((row) => row[0] === "modal.close");
  const setAt = h.trace.findIndex((row) => row[2] === "set_group");
  assert.ok(closeAt >= 0 && setAt > closeAt, "닫힘(=초점 복귀) 뒤에 변이가 나간다");
  assert.deepEqual(h.actions().at(-1), ["tpl", "set_group", { media: "hwpx", key: "k1", group: "나" }]);
});

test("음성 — 확정 없이 닫으면 onConfirm 이 나가지 않는다", () => {
  const calls = [];
  const closes = [];
  let spec = null;
  const dialog = createGroupMoveDialog({
    modal: { open: (_id, value) => { spec = value; }, close: (id) => { closes.push(id); spec?.onClose?.(); } },
  });
  dialog.open({ nameText: "T1", groups: ["가"], current: "가", onConfirm: (g) => calls.push(g) });
  dialog.cancel();
  assert.deepEqual(closes, ["tplMoveModal"]);
  assert.deepEqual(calls, []);
  assert.equal(dialog.model.getSnapshot(), null);
});

test("음성 — 빈 새 그룹 이름은 조용히 넘어가지 않고 창을 연 채 재진술한다", () => {
  const calls = [];
  let closed = 0;
  let spec = null;
  const dialog = createGroupMoveDialog({
    modal: { open: (_id, value) => { spec = value; }, close: () => { closed += 1; spec?.onClose?.(); } },
  });
  dialog.open({ nameText: "T1", groups: ["가"], current: "", onConfirm: (g) => calls.push(g) });
  dialog.patch({ useFresh: true, fresh: "   " });
  dialog.confirm();
  assert.equal(closed, 0, "창은 열린 채로 남는다");
  assert.deepEqual(calls, []);
  assert.match(dialog.model.getSnapshot().error, /비어 있습니다/);
});

test("다이얼로그 둘은 자기 confirm 상태만 든다(legacy 인스턴스 격리의 후계)", () => {
  const seen = [];
  const make = (label) => {
    let spec = null;
    const dialog = createGroupMoveDialog({
      modal: { open: (_id, value) => { spec = value; }, close: () => spec?.onClose?.() },
    });
    dialog.open({
      nameText: label, groups: [label], current: label,
      onConfirm: (group) => seen.push([label, group]),
    });
    return dialog;
  };
  const a = make("A");
  const b = make("B");
  assert.equal(a.model.getSnapshot().nameText, "A");
  assert.equal(b.model.getSnapshot().nameText, "B");
  a.confirm();
  assert.deepEqual(seen, [["A", "A"]], "B 는 자기 확정만 낸다");
});

/* ================= TXT 저작 모달 ================= */

async function openedTxt(h) {
  h.controller.toggleLibMenu("txt", "row", "k1", { id: "btn" });
  await h.controller.handleLibMenu("edit");
  return h.editorSpec();
}

function txtHarness(options = {}) {
  return build({
    ...options,
    snapshot: {
      ...BASE,
      library: { txt: { sections: [{ items: [{ key: "k1", name: "T1", path: "P.txt" }] }] } },
    },
    dispatch: options.dispatch ?? ((_s, action) => (action === "txt_content" ? { content: "본문" } : {})),
  });
}

test("TXT 편집 — 손대지 않은 창은 그대로 닫힌다", async () => {
  const h = txtHarness();
  await h.ready();
  const spec = await openedTxt(h);
  assert.equal(spec.beforeClose(), true);
  assert.equal(h.controller.viewModel.getSnapshot().txtEdit, null);
});

test("음성 — dirty 한 TXT 편집 창은 닫힘을 막고 확인을 띄운다", async () => {
  const h = txtHarness({ confirm: false });
  await h.ready();
  const spec = await openedTxt(h);
  h.controller.patchTxtEdit({ content: "고친 본문" });
  assert.equal(spec.beforeClose(), false, "확인 없이 닫히지 않는다");
  await tick();
  assert.ok(h.trace.some((row) => row[0] === "modal.confirm"));
  assert.notEqual(h.controller.viewModel.getSnapshot().txtEdit, null, "취소하면 편집이 살아 있다");
});

test("dirty 한 TXT 편집을 확인하면 닫힘이 허용된다", async () => {
  const h = txtHarness({ confirm: true });
  await h.ready();
  await openedTxt(h);
  h.controller.patchTxtEdit({ content: "고친 본문" });
  await h.controller.confirmDiscardTxtEdit();
  assert.equal(h.controller.viewModel.getSnapshot().txtEdit.allowClose, true);
  assert.ok(h.trace.some((row) => row[0] === "modal.close" && row[1] === "txtEditModal"));
});

test("음성 — TXT 저장 실패는 창을 닫지 않고 인라인으로 재진술한다", async () => {
  const h = txtHarness({
    dispatch: (_s, action) => {
      if (action === "txt_content") return { content: "본문" };
      return {};
    },
    dispatchFails: (_s, action) => action === "txt_edit",
  });
  await h.ready();
  await openedTxt(h);
  h.controller.patchTxtEdit({ content: "고친 본문" });
  await h.controller.submitTxtEdit();
  const state = h.controller.viewModel.getSnapshot().txtEdit;
  assert.notEqual(state, null, "실패 뒤에도 내용을 들고 있다");
  assert.match(state.error, /백엔드 거절/);
  assert.equal(state.allowClose, false);
});

/* ================= 어포던스 잠금·확인 관문 ================= */

test("음성 — 폴더 가져오기는 진행 중 둘째 클릭을 삼키고 어느 출구로든 해제된다", async () => {
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  let scans = 0;
  const h = build({
    invoke: async (method) => {
      if (method === "import_templates_folder") { scans += 1; await held; return null; }
      return null;
    },
  });
  await h.ready();
  const first = h.controller.importFolder({ id: "btn" });
  await tick();
  await h.controller.importFolder({ id: "btn" });
  assert.equal(scans, 1, "진행 중에는 둘째 스캔이 나가지 않는다");
  release();
  await first;
  assert.equal(h.controller.viewModel.getSnapshot().folderImportInFlight, false, "취소 출구도 해제한다");
});

test("데이터 고르기 — needs_sheet 는 시트 port 로 넘기고 취소는 중단이다", async () => {
  const h = build({
    invoke: async (method) => (method === "pick_data_file"
      ? { needs_sheet: true, name: "d.xlsx", sheets: [] } : null),
    sheetChoice: null,
  });
  await h.ready();
  await h.controller.pickData();
  assert.ok(h.trace.some((row) => row[0] === "sheetPicker.choose"));
  assert.deepEqual(h.notices, [], "취소는 실패가 아니다");
});

test("음성 — 확정한 매핑이 있으면 전체 미사용은 확인을 열기 전에 막힌다", async () => {
  const h = build({
    dispatch: (_s, action) => (action === "mapping_reset_stakes" ? { confirmed: 3 } : {}),
  });
  await h.ready();
  await h.controller.useNone();
  assert.equal(h.trace.some((row) => row[0] === "modal.confirm"), false,
    "파괴를 승인시킨 뒤 거부하는 순서를 만들지 않는다");
  assert.equal(h.actions().some((row) => row[1] === "use_none"), false);
  assert.match(h.notices[0], /확정한 매핑 3개/);
});

test("다시 제안 — 아무것도 안 바뀌면 무동작으로 두지 않고 말한다", async () => {
  const h = build({
    dispatch: (_s, action) => {
      if (action === "mapping_reset_stakes") return { resuggest_manual: 0, confirmed: 2 };
      if (action === "resuggest_all") return { resuggested: 0, kept_confirmed: 2 };
      return {};
    },
  });
  await h.ready();
  await h.controller.resuggestAll();
  assert.match(h.notices[0], /다시 받을 행이 없습니다/);
});

test("guarded — 화면 행동의 rejection 은 한 자리에서 재진술된다", async () => {
  const h = build();
  await h.ready();
  h.controller.guarded(() => Promise.reject(new Error("터짐")));
  await tick();
  assert.deepEqual(h.notices, ["터짐"]);
  h.controller.guarded(() => { throw new Error("동기 터짐"); });
  assert.deepEqual(h.notices, ["터짐", "동기 터짐"]);
});

/* ================= 조준(deep-link) ================= */

test("aimAt — 문맥이 아직 안 왔으면 다음 렌더가 정확히 한 번 소비한다", async () => {
  const h = build();
  await h.ready();
  h.controller.aimAt("binding/납품기한");
  assert.equal(h.controller.viewModel.getSnapshot().aim, "binding/납품기한", "겨눔이 예약된다");

  h.controller.consumeAim();
  assert.equal(h.controller.viewModel.getSnapshot().aim, "binding/납품기한",
    "문맥이 그 대상을 말하기 전에는 소비하지 않는다");

  h.store.ingest("editor", { ...BASE, context: { target: "binding/납품기한" } });
  h.controller.consumeAim();
  assert.equal(h.controller.viewModel.getSnapshot().aim, "", "도착한 렌더에서 한 번 소비된다");
  h.controller.consumeAim();
  assert.equal(h.controller.viewModel.getSnapshot().aim, "");
});
