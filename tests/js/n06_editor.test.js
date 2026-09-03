/* Editor controller behavior: retries, late-bound ports, ordering, and draft races. */
import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  createEditorController, EditorScreen, libRowMenuItems, ROW_STATE_CLASS,
  TplDetailSheet, TxtEditDialog,
} from "../../frontend/src/screens/editor.ts";
import { usableSpans } from "../../frontend/src/editorview/txt_lintpad.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";
import { createScreenRuntime } from "../../frontend/src/screens/runtime.ts";
import { createSnapshotStore } from "../../frontend/src/state/store.ts";
import {
  NAME_FIELD,
  PATTERN_FIELD,
  emptyDraft,
  fieldError,
  hasInFlight,
  ingestSnapshot,
  issueToken,
  markField,
  settle,
  typeInto,
  valueOf,
} from "../../frontend/src/screens/editor_state.ts";
import { Intent } from "../../frontend/js/intent.js";

/** 셸이 직접 쓰는 controller 핵심 4키. */
const SHELL_FACADE = ["init", "rerender", "leaveTo", "aimAt"];

/* 렌더가 통과할 최소 스냅샷 — 신규 초안 1단계.
   구 `library` 존은 U6-B(#976)에서 퇴역했다: 좌 열의 정본이 `tpl` 채널이라 목록·결과 줄·
   구간 항목은 이제 그 채널 스냅샷(`tplSnap`)이 진다. */
function snap(extra) {
  return Object.assign({
    section: "template",
    sections: ["template", "binding", "filename"],
    name: "테스트 작업",
    rows: [],
  }, extra || {});
}

/** 밴드 행 → 공용 열 행(`webapp/pool_column.py` 의 키 집합).
 *
 *  Python 이 하는 접기를 여기서 되풀이하는 이유는 하나다: 이 파일의 픽스처가 오래전부터
 *  밴드로 쓰여 있고, 좌 열이 `column` 존으로 옮겨 갔어도 **같은 사실**을 말해야 한다.
 *  두 존이 어긋난 픽스처는 실제로는 있을 수 없는 상태를 시험하는 것이다. */
function columnRowOf(item, icon) {
  return {
    key: item.key, name: item.name, sub: item.detail || "",
    reason: item.select_block_reason || "", warns: item.fill_warns || [],
    badge_label: icon === "txt" ? "TXT" : (item.badge_label || ""),
    badge_level: icon === "txt" ? "muted" : (item.badge_level || "muted"),
    icon, selectable: !!item.selectable, path: item.path, actions: item.actions || [],
  };
}

/** `tpl` 채널 스냅샷 — 고르기 단계 좌 열이 구독하는 정본.
 *
 *  좌 열의 정본은 **공용 열 존**(`column`)이고 옛 밴드(`hwpx`·`txt`)는 아직 다른 소비자가
 *  있다. 픽스처가 둘을 따로 쓰면 갈리므로 밴드에서 존을 **유도한다**(명시로 준 `column`
 *  은 그대로 존중한다 — 어긋남 자체를 시험하는 자리가 있을 수 있다). */
function tplSnap(extra) {
  const snapshot = Object.assign({
    hwpx: { flat: true, count: 0, dir: "C:/lib", empty_hint: "비었습니다", sections: [] },
    txt: { flat: true, count: 0, dir: "C:/lib", empty_hint: "비었습니다", sections: [] },
    templates_root: { directory: "C:/lib", source: "settings", source_label: "설정", notice: "" },
    result: { text: "", level: "muted" },
    detail: null,
  }, extra || {});
  if (snapshot.column === undefined) {
    const rows = [];
    for (const icon of ["hwpx", "txt"]) {
      for (const section of (snapshot[icon] || {}).sections || []) {
        for (const item of section.items || []) rows.push(columnRowOf(item, icon));
      }
    }
    snapshot.column = {
      rows, notices: [], empty_hint: (snapshot.hwpx || {}).empty_hint || "",
      count_label: `${rows.length}개`, result: snapshot.result,
    };
  }
  return snapshot;
}

/** `pool` 채널 스냅샷 — 고르기 단계 **우 열**이 구독하는 정본.
 *
 *  좌 열과 같은 이유로 존을 **유도한다**(`tplSnap` 주석 참조): 옛 목록 키(`rows`)는 아직
 *  관리 동사의 프리필 재료라 살아 있고, 우 열이 그리는 것은 공용 열 존(`column`)이다. 두
 *  존을 픽스처가 따로 쓰면 실제로는 있을 수 없는 상태(목록에 있는 행이 열에는 없는)를
 *  시험하게 된다. 손으로 준 `column` 은 그대로 존중한다. */
function poolSnap(rows, extra) {
  const list = rows || [];
  const snapshot = Object.assign({
    rows: list, count: `${list.length}건`, empty: !list.length,
    corrupted: [], duplicates: [],
    pclm: { default_db: "C:/d/pclm.db", views: [], titles: {} },
    result: { text: "", level: "muted" },
  }, extra || {});
  if (snapshot.column === undefined) {
    snapshot.column = {
      rows: (snapshot.rows || []).map((row) => ({
        key: row.key, name: row.name, sub: row.reference || "",
        reason: row.select_block_reason || "", warns: [],
        badge_label: row.badge_label || "", badge_level: row.badge_level || "muted",
        icon: row.kind === "pclm" ? "pclm" : "excel",
        selectable: !!row.selectable, path: row.locate_path || "",
        actions: row.actions || [],
      })),
      notices: (snapshot.duplicates || []).map((group) => ({
        level: "warn",
        text: `같은 데이터(${group.reference})를 가리키는 등록이 ${group.entries.length}건입니다.`,
        actions: group.entries.map((entry) => ({
          key: "resolve_duplicate", label: `'${entry.name}' 남기기`,
          payload: { keep: entry.key },
        })),
      })),
      empty_hint: "고정한 데이터가 없습니다.",
      count_label: snapshot.count, result: snapshot.result,
    };
  }
  return snapshot;
}

/** 파일로 연 데이터의 세션 행 — Python `pairing.data_row` 와 **같은 계약**이다(③a). */
function sessionRow(extra) {
  return Object.assign({
    key: "session", name: "7월목록", sub: "시트: 물품 · 헤더 1행 · 12행",
    reason: "", warns: [], badge_label: "사용 중", badge_level: "ok",
    icon: "excel", selectable: true, path: "C:/d/7월목록.xlsx", actions: [],
  }, extra || {});
}

/** 1단계 pairing 존 — 두 열의 선택 표지가 여기서 온다. */
function pairing(extra) {
  return Object.assign({
    ready: false, template_name: "", data_name: "",
    template_key: "", data_key: "", data_row: null,
    field_count: 0, column_count: 0, auto_count: 0, confirm_count: 0,
    basis: "", advance_block_reason: "왼쪽에서 템플릿을 고르세요.",
  }, extra || {});
}

function harness(cfg) {
  const opts = cfg || {};
  const trace = [];
  const notices = [];
  const counts = { initial: 0 };
  const client = {
    /* 대역도 포트를 온전히 만족해야 한다 — `loadInitial` 은 호스트 준비를 **구조로**
       기다린다(U6-A 리뷰: 관례 주석이 아니라 코드가 순서를 진다). */
    whenReady: () => (opts.whenReady ? opts.whenReady() : Promise.resolve()),
    async initial(screen) {
      counts.initial += 1;
      trace.push(["initial", screen]);
      const value = await (opts.initial || (async () => snap()))(screen);
      return { ok: true, value };
    },
    async dispatch(screen, action, payload) {
      trace.push(["dispatch", screen, action, payload]);
      const value = opts.call ? await opts.call(screen, action, payload) : {};
      return { ok: true, value };
    },
    async invoke(method, ...args) {
      trace.push(["invoke", method, ...args]);
      const value = opts.invoke ? await opts.invoke(method, ...args) : null;
      return { ok: true, value };
    },
  };
  const store = createSnapshotStore({ alarm: assert.fail });
  const runtime = createScreenRuntime({ client, store });
  /* 고르기 단계의 두 열은 자기 채널을 직접 읽는다(U6-B #976) — 대역도 그 채널로 값을
     세운다. 편집기 스냅샷에 목록을 실어 주던 길은 이제 없다. */
  if (opts.tpl !== undefined) store.ingest("tpl", opts.tpl);
  if (opts.pool !== undefined) store.ingest("pool", opts.pool);
  const ports = createScreenPorts();
  const services = createServiceHandoffPorts();
  services.sheetPicker.bind({ choose: async () => null });
  const navigation = {
    refresh: async (target) => {
      trace.push(["navigation.refresh", target]);
      if (opts.refreshFails) throw new Error("stale disk");
    },
    go: (target, options) => { trace.push(["navigation.go", target, options]); },
  };
  const controller = createEditorController({
    doc: opts.doc || { getElementById: () => null, querySelector: () => null },
    runtime, client, ports, services,
    modal: {
      confirm: async (spec) => { trace.push(["modal.confirm", spec]); return opts.confirm?.(spec) ?? false; },
      prompt: async (spec) => { trace.push(["modal.prompt", spec]); return opts.prompt?.(spec) ?? null; },
      choose: async (spec) => { trace.push(["modal.choose", spec]); return opts.choose?.(spec) ?? null; },
      /* 여닫기도 자취에 남긴다(U6-E #979) — 항목 상세 시트는 「왕복 먼저, 열기 나중」이
         계약이라 그 **순서**를 재려면 두 사건이 같은 줄에 있어야 한다. */
      open(id, spec) { trace.push(["modal.open", id, spec]); },
      close(id) { trace.push(["modal.close", id]); },
    },
    undo: { show() {} },
    popover: { wireDismiss: () => () => {} },
    rowMenu: { show() {}, hide() {} },
    groupMove: { open() {} },
    chain: Intent,
    navigation,
    poolRegistration: {
      openRegDialog: (options) => { trace.push(["poolReg.open", options]); },
      openPclm: () => { trace.push(["poolReg.pclm"]); },
    },
    notify: (message) => notices.push(String(message)),
  });
  return {
    controller, client, store, runtime, ports, services, navigation, trace, notices, counts,
    names: () => trace.map((row) => row[0]),
  };
}

/* ---------------- ① 공개 표면 ---------------- */

test("controller 는 핵심 4키(init·rerender·leaveTo·aimAt)를 전부 낸다", () => {
  assert.equal(typeof createEditorController, "function");
  const { controller } = harness();
  for (const key of SHELL_FACADE) {
    assert.equal(typeof controller[key], "function", `${key} 는 함수여야 한다`);
  }
  /* 셸이 부르는 이름이 controller 표면 안에 실재하는지까지 본다 — facade 조립은
     `bootstrap.test.js` 가 별도로 재고, 여기서는 그 조립이 가리킬 자리가 있는지를 잰다. */
  const keys = Object.keys(controller);
  assert.deepEqual(SHELL_FACADE.filter((key) => keys.includes(key)), SHELL_FACADE);
});

/* ---------------- ② init 멱등 — 등록 delta 실측 ---------------- */

test("init 2회 — initial 추가 등록 0, 같은 promise 공유", async () => {
  const h = harness();
  const first = h.controller.init();
  await first;
  assert.equal(h.counts.initial, 1, "initial 당김 1회");
  /* U6-B(#976): 좌 열의 정본이 `tpl` 채널이라 편집기는 그 채널을 **구독한다**. 계약은
     「구독하지 않는다」가 아니라 「정확히 하나」다 — 중복 설치가 곧 두 벌 갱신이다. */
  assert.equal(h.store.listenerCount("tpl"), 1, "tpl 구독은 정확히 하나");
  assert.equal(h.store.listenerCount("pool"), 1, "pool 구독도 정확히 하나");

  const second = h.controller.init();
  assert.equal(second, first, "성공한 init 재호출은 같은 promise 를 공유한다");
  await second;
  await h.controller.init();
  assert.equal(h.counts.initial, 1, "initial 추가 당김 0");
  assert.equal(h.store.listenerCount("tpl"), 1, "tpl 구독 재유입 0");
});

/** 재스캔 발신만 뽑는다 — 채널 순서(tpl → pool)까지 계약이다. */
const rescansOf = (h) => h.trace
  .filter((row) => row[0] === "dispatch" && row[2] === "refresh")
  .map((row) => row[1]);

test("재스캔은 **진입 사건**에 걸린다 — 렌더가 아니라(U6-B 리뷰 4)", async () => {
  const h = harness();
  await h.controller.init();
  /* 부팅 당김 자체는 진입이 아니다: 셸이 편집기 화면에 들어설 때 `rerender` 가 그 문이다. */
  assert.deepEqual(rescansOf(h), [], "스냅샷 도착만으로는 디스크를 훑지 않는다");

  await h.controller.rerender();                      // 셸의 편집기 착지(shell/nav.ts)
  assert.deepEqual(rescansOf(h), ["tpl", "pool"], "진입 한 번에 채널별 한 발");

  /* 같은 단계에서 스냅샷이 다시 와도 재스캔이 늘지 않는다(진입 수 ≠ 렌더 수). */
  h.store.ingest("editor", snap({ name: "다른 이름" }));
  h.store.ingest("editor", snap({ section: "binding" }));
  h.store.ingest("editor", snap({ section: "template" }));
  assert.deepEqual(rescansOf(h), ["tpl", "pool"], "렌더마다 디스크를 훑지 않는다");

  /* 같은 세션 안의 1단계 재진입은 **이동 동사**가 낸다. */
  await h.controller.gotoSection("template");
  assert.deepEqual(rescansOf(h), ["tpl", "pool", "tpl", "pool"], "재진입은 다시 읽는다");
  await h.controller.gotoSection("binding");
  assert.deepEqual(rescansOf(h), ["tpl", "pool", "tpl", "pool"], "2단계 진입은 훑지 않는다");
});

test("초안 → 취소 → 새 초안: 두 번째 새 작업도 재스캔한다(리뷰 4 회귀 심)", async () => {
  /* 종전 트리거는 마지막으로 본 `(editorSession(), section)` 을 기억했는데 초안의 세션
     표지는 **언제나 `"draft"`** 라 두 초안이 같은 값으로 읽혔다 — 두 번째 새 작업부터
     재스캔이 조용히 빠졌다(선언은 살고 결과가 죽는 자리). */
  const h = harness({ initial: async () => snap({ is_draft: true }) });
  h.ports.editorEntry.bind({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {},
    restoreEntryFocus() {},
  });
  await h.controller.init();

  await h.controller.rerender();                      // 첫 초안 진입
  assert.equal(rescansOf(h).length, 2);

  await h.controller.cancelNewDraft();                // 취소 — 편집기를 떠난다
  assert.equal(rescansOf(h).length, 2, "이탈은 재스캔이 아니다");

  await h.controller.rerender();                      // 두 번째 새 초안 진입
  assert.deepEqual(rescansOf(h), ["tpl", "pool", "tpl", "pool"],
    "같은 세션 표지의 두 번째 진입이 조용히 빠졌습니다");
});

test("같은 템플릿 재선택은 아무 일도 하지 않는다(리뷰 1)", async () => {
  const h = harness({
    initial: async () => snap({ template_path: "C:/lib/a.hwpx" }),
    tpl: tplSnap({
      hwpx: {
        flat: true, count: 1, dir: "C:/lib", empty_hint: "",
        sections: [{
          group: "", collapsed: false, count: 1,
          items: [{
            key: "a.hwpx", name: "a", path: "C:/lib/a.hwpx", detail: "필드 3개",
            actions: [], selectable: true, select_block_reason: "",
          }],
        }],
      },
    }),
  });
  await h.controller.init();

  await h.controller.chooseTemplate("a.hwpx");
  const sent = h.trace.filter((row) => row[0] === "dispatch" && row[1] === "editor");
  assert.deepEqual(sent, [], "이미 고른 템플릿을 다시 눌러 세션이 끊겼습니다");
});

test("템플릿 **교체**는 데이터 교체와 같은 확인 왕복을 지난다(리뷰 2)", async () => {
  const h = harness({
    initial: async () => snap({ template_path: "C:/lib/a.hwpx" }),
    tpl: tplSnap({
      hwpx: {
        flat: true, count: 1, dir: "C:/lib", empty_hint: "",
        sections: [{
          group: "", collapsed: false, count: 1,
          items: [{
            key: "b.hwpx", name: "b", path: "C:/lib/b.hwpx", detail: "필드 3개",
            actions: [], selectable: true, select_block_reason: "",
          }],
        }],
      },
    }),
    call: async (_screen, action) => (
      action === "mapping_reset_stakes" ? { human: 2 } : {}),
    confirm: () => false,
  });
  await h.controller.init();

  await h.controller.chooseTemplate("b.hwpx");
  const actions = h.trace
    .filter((row) => row[0] === "dispatch" && row[1] === "editor").map((row) => row[2]);
  assert.deepEqual(actions, ["mapping_reset_stakes"],
    "확정 매핑을 확인 없이 버렸습니다(데이터 교체와 다른 규칙)");
  const asked = h.trace.find((row) => row[0] === "modal.confirm");
  assert.ok(asked && asked[1].body.includes("템플릿을 바꾸면"), "확인 문안이 서지 않았습니다");

  /* 승낙하면 그때 발행한다 — 순서가 계약이다(승인 뒤 발신). */
  const yes = harness({
    initial: async () => snap({ template_path: "C:/lib/a.hwpx" }),
    tpl: h.store.get("tpl"),
    call: async (_screen, action) => (
      action === "mapping_reset_stakes" ? { human: 2 } : {}),
    confirm: () => true,
  });
  await yes.controller.init();
  await yes.controller.chooseTemplate("b.hwpx");
  assert.deepEqual(
    yes.trace.filter((row) => row[0] === "dispatch" && row[1] === "editor").map((row) => row[2]),
    ["mapping_reset_stakes", "use_library_template"]);
});

test("목록에서 사라진 키는 조용히 반환하지 않는다 + 끌어 놓기는 한 문장으로 말한다(리뷰 5)", async () => {
  const h = harness({ tpl: tplSnap(), pool: poolSnap([]) });
  await h.controller.init();

  await h.controller.chooseData("사라진키");
  const first = h.controller.viewModel.getSnapshot().saveMessage;
  assert.ok(first && first.text.includes("목록이 바뀌었습니다"), "조용히 삼켰습니다");

  /* 끌어 놓기의 두 반쪽이 각자 쓰면 앞 문장이 사라진다 — 하나로 모아 말한다. */
  await h.controller.dropPair("tpl", "없는템플릿", "없는데이터");
  const both = h.controller.viewModel.getSnapshot().saveMessage;
  assert.ok(both.text.includes("템플릿을 찾을 수 없습니다"), both.text);
  assert.ok(both.text.includes("데이터를 찾을 수 없습니다"), both.text);
  assert.deepEqual(h.notices, [], "구조화 거절은 window.alert 로 새지 않는다");
});

test("tpl 재스캔은 editor 재당김을 태우지 않고, 변이 동사는 정확히 한 번 태운다", async () => {
  const h = harness({ tpl: tplSnap({ detail: {
    path: "C:/lib/구간.hwpx", name: "구간", media: "hwpx",
    state: "compiled", badge_label: "누름틀", badge_level: "ok",
    field_count: 0, field_summary: "채울 필드가 없습니다.", fields: [], actions: [],
    diagnostics: [],
    slots: {
      summary: "항목 1개",
      rows: [{ id: "특약", label: "특약 사항", option_count: 1, options: [] }],
    },
    error: "",
  } }) });
  await h.controller.init();

  /* 재스캔은 `tpl` 채널의 push 하나로 끝난다 — 편집기 스냅샷을 또 묻는 것은 같은 진입에서
     디스크를 두 번 읽는 일이다(U6-B). */
  const beforeRefresh = h.counts.initial;
  await h.controller.refreshLibrary();
  assert.equal(h.counts.initial - beforeRefresh, 0, "재스캔은 editor 재당김을 안 태운다");

  /* 반대로 파일을 변이시키는 동사는 이 세션의 스키마·게이트를 흔들 수 있어 종전대로 하나. */
  const beforeMutate = h.counts.initial;
  await h.controller.handleSlotVerb("decompile", "특약", {});
  assert.equal(h.counts.initial - beforeMutate, 1,
    "변이 동사 완료가 재당김 하나를 소유한다");
  assert.equal(h.store.listenerCount("tpl"), 1);
});

test("동시 2회 init — 같은 초기화 promise, initial 1회", async () => {
  const h = harness();
  const first = h.controller.init();
  const second = h.controller.init();
  assert.equal(first, second);
  await Promise.all([first, second]);
  assert.equal(h.counts.initial, 1);
  assert.equal(h.store.listenerCount("tpl"), 1);
});

test("첫 initial reject — 실패는 전파되고, 명시적 재-init 이 initial 만 다시 당긴다", async () => {
  let fail = true;
  const h = harness({
    initial: async () => {
      if (fail) throw new Error("boot fail");
      return snap();
    },
  });

  await assert.rejects(h.controller.init(), /boot fail/, "rejection 은 호출자에게 전파된다");
  assert.equal(h.counts.initial, 1);
  const afterFail = h.store.listenerCount("tpl");
  assert.equal(afterFail, 1, "실패해도 구독은 하나다");

  fail = false;
  await h.controller.init();   // 회복 — 스스로 재시도하지 않고 명시적 호출이 다시 당긴다
  assert.equal(h.counts.initial, 2, "재-init 이 initial 을 다시 당겼다");
  assert.equal(h.store.listenerCount("tpl"), afterFail, "tpl 구독 중복 설치 0");
});

test("rerender — 재당김 하나를 태우고 구독을 늘리지 않는다", async () => {
  const h = harness();
  await h.controller.init();
  await h.controller.rerender();
  assert.equal(h.counts.initial, 2, "rerender 는 스냅샷을 다시 묻는다");
  assert.equal(h.store.listenerCount("tpl"), 1, "rerender 는 구독을 새로 설치하지 않는다");
});

test("저장은 blur 없는 이름 draft를 set_name 뒤에 정산한다", async () => {
  const h = harness({
    initial: async () => snap({
      section: "binding", sections: ["template", "binding"], name: "", is_draft: true,
    }),
    call: async (_screen, action) => (
      action === "save" ? { ok: false, block_reason: "저장 게이트 대역" } : {}
    ),
  });
  await h.controller.init();

  h.controller.type(NAME_FIELD, "발주요청 기안");
  await h.controller.doSave({});

  const edits = h.trace
    .filter((row) => row[0] === "dispatch" && row[1] === "editor")
    .map((row) => [row[2], row[3]]);
  assert.deepEqual(edits, [
    ["set_name", { name: "발주요청 기안" }],
    ["save", {}],
  ], "버튼이 blur보다 먼저 와도 이름 변경이 저장 판정보다 먼저 착지해야 한다");
});

/* ---------------- ③④ 교차 포트·landOn 순서 ---------------- */

test("이탈 — discard_patch → refresh→go(refreshed:true) → 초점 복원, late-binding", async () => {
  const h = harness({
    initial: async () => snap({
      dirty: true,
      context: {
        entry_reason: "run_failure",
        target: "binding/납품기한",
        return_context: { surface: "result" },
      },
    }),
  });
  await h.controller.init();

  /* late-binding: 구성·init **뒤에** 포트를 채운다 — 호출 시점에 잡혀야 한다. */
  h.ports.jobRead.bind({
    refreshList: () => { h.trace.push(["ports.refreshList"]); },
    openBrowseNeedsAction: async () => {},
  });
  h.ports.jobRun.bind({ attach: () => () => {} });
  h.ports.editorEntry.bind({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {},
    restoreEntryFocus: () => { h.trace.push(["ports.restoreEntryFocus"]); },
  });

  await h.controller.leaveTo("job");

  const names = h.names();
  const iDiscard = h.trace.findIndex((row) => row[0] === "dispatch" && row[2] === "discard_patch");
  assert.ok(iDiscard >= 0, "이탈이 세션 되돌리기를 발신했다");
  assert.equal(names.includes("modal.choose"), false, "이탈이 3택을 묻지 않는다");
  assert.equal(names.includes("modal.confirm"), false, "이탈이 확인을 묻지 않는다");

  const iRefresh = names.indexOf("navigation.refresh");
  const iGo = names.indexOf("navigation.go");
  assert.ok(iRefresh >= 0 && iGo >= 0, "refresh·go 둘 다 발화");
  assert.ok(iDiscard < iRefresh, "되돌리기가 착지보다 먼저다");
  assert.ok(iRefresh < iGo, "landOn 순서: refresh 가 go 보다 먼저(8R P1)");
  assert.equal(h.trace[iGo][1], "job");
  assert.deepEqual(h.trace[iGo][2], { force: true, refreshed: true });

  assert.ok(names.indexOf("ports.restoreEntryFocus") > iGo, "착지 뒤 진입 초점 복원");

  /* 복귀 **상태** 복원(구 `restoreReturnState` → `ports.openPreview`)은 미리보기 드로어
     재개 하나뿐이었고 #957 에서 함께 사망했다 — 착지 화면은 자기 스냅샷으로 선다. */
  assert.equal(names.includes("ports.openPreview"), false,
    "이탈이 사라진 미리보기 면을 되열려 하지 않는다");
});

test("navigation.refresh 실패 — 나가지 않는다(loud 통지, go 0회)", async () => {
  const h = harness({
    initial: async () => snap({ dirty: false, is_draft: false }),
    refreshFails: true,
  });
  h.ports.editorEntry.bind({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {},
    restoreEntryFocus() {},
  });
  await h.controller.init();

  await h.controller.leaveTo("job");
  assert.equal(h.names().includes("navigation.go"), false, "재적재 실패 시 전환하지 않는다");
  assert.ok(h.notices.some((message) => message.includes("머무릅니다")),
    "실패를 시끄럽게 재진술한다");
});

test("이탈 — 손댄 세션도 묻지 않고 버리고 나간다(자동 버리기 양성)", async () => {
  const h = harness({ initial: async () => snap({ dirty: true, is_draft: false }) });
  h.ports.editorEntry.bind({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {},
    restoreEntryFocus() {},
  });
  await h.controller.init();
  await h.controller.leaveTo("job");
  const actions = h.trace.filter((row) => row[0] === "dispatch").map((row) => row[2]);
  assert.ok(actions.includes("discard_patch"), "손댄 세션은 되돌리고 나간다");
  assert.equal(actions.includes("save"), false, "이탈이 저장을 대신하지 않는다");
  assert.equal(h.names().includes("modal.choose"), false, "3택 0");
  assert.equal(h.names().includes("modal.confirm"), false, "확인 0");
  assert.ok(h.names().includes("navigation.go"), "막히지 않고 나간다");
});

test("이탈 — 초안은 세션째 끊고 나간다(비초안과 다른 동사)", async () => {
  const h = harness({ initial: async () => snap({ dirty: true, is_draft: true }) });
  h.ports.editorEntry.bind({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {},
    restoreEntryFocus() {},
  });
  await h.controller.init();
  await h.controller.leaveTo("job");
  const actions = h.trace.filter((row) => row[0] === "dispatch").map((row) => row[2]);
  assert.ok(actions.includes("new_session"), "초안 이탈은 세션 폐기다");
  assert.equal(actions.includes("discard_patch"), false, "초안엔 되돌릴 base 가 없다");
  assert.equal(h.names().includes("modal.confirm"), false, "확인 0");
  assert.ok(h.names().includes("navigation.go"), "막히지 않고 나간다");
});

/* ---------------- 인라인 알림 채널(#323) ---------------- */

/* 편집기의 세 탭 전부에서 통지가 화면 안(`#save-msg`)에 서야 한다. 종전에는 파일 이름
   탭에서만 인라인이었고 나머지 두 탭은 `window.alert` 로 샜다 — 모달 경보는 읽는 순간
   사라지고, 그 뒤 화면은 왜 저장이 막혔는지 아무 말도 하지 않는다. */
const NOTICE_SECTIONS = ["template", "binding", "filename"];

function blockedSaveHarness(section) {
  return harness({
    initial: async () => snap({
      section, is_draft: false, editing_origin: "공고서", dirty: true,
      reachable: { template: true, binding: true, filename: true },
    }),
    call: async (_screen, action) => (
      action === "save"
        ? { ok: false, block_reason: "이름을 입력해야 저장할 수 있습니다.", blocked_field: "name" }
        : {}
    ),
  });
}

for (const section of NOTICE_SECTIONS) {
  test(`#323 '${section}' 탭의 저장 차단은 인라인으로 서고 window.alert 는 0 이다`, async () => {
    const h = blockedSaveHarness(section);
    await h.controller.init();

    assert.equal(await h.controller.doSave({}), false);

    const message = h.controller.viewModel.getSnapshot().saveMessage;
    assert.ok(message, "차단 사유가 인라인 채널에 실려야 한다");
    assert.equal(message.text, "이름을 입력해야 저장할 수 있습니다.");
    assert.deepEqual(h.notices, [], "구조화 거절은 window.alert 로 새지 않는다");
  });

  test(`#323 '${section}' 탭 렌더에 #save-msg 노드가 실재한다`, async () => {
    const h = blockedSaveHarness(section);
    await h.controller.init();
    await h.controller.doSave({});

    const markup = renderToStaticMarkup(
      createElement(EditorScreen, { controller: h.controller }),
    );
    assert.ok(markup.includes('id="save-msg"'),
      `${section} 탭 본문에 통지가 갈 노드가 없다 — 셸 자리가 아니면 탭마다 증발한다`);
    assert.ok(markup.includes("이름을 입력해야 저장할 수 있습니다."),
      "노드는 있는데 문안이 안 실리면 사용자는 여전히 아무것도 못 읽는다");
  });
}

/* ---------------- 수동 소멸 알림의 닫기 문법(U4 §2.12 · #945 F4) ---------------- */

/* `saveMessage` 는 사유가 해소될 때까지 남는 채널인데 끄는 동사가 없었다(#874 이후에도
   JS 전용 상태 쪽은 그대로였다). NoticeBox 로 이행해 닫기를 상자 문법이 강제한다. */
test("#945 F4 인라인 알림에는 닫기 단추가 서고 눌리면 채널이 비워진다", async () => {
  const h = blockedSaveHarness("filename");
  await h.controller.init();
  await h.controller.doSave({});

  const markup = renderToStaticMarkup(
    createElement(EditorScreen, { controller: h.controller }),
  );
  assert.ok(markup.includes('id="saveMsgClose"'),
    "닫을 수 없는 알림은 사유가 지나간 뒤에도 과거를 계속 서술한다");
  assert.ok(markup.includes('aria-label="알림 닫기"'), "닫기 단추에 이름이 없다");

  assert.equal(typeof h.controller.clearSaveMessage, "function");
  h.controller.clearSaveMessage();
  assert.equal(h.controller.viewModel.getSnapshot().saveMessage, null);
  /* 통지가 없어도 노드는 남는다 — #323 이 재는 것은 「통지가 갈 자리」의 존재다. */
  const after = renderToStaticMarkup(
    createElement(EditorScreen, { controller: h.controller }),
  );
  assert.ok(after.includes('id="save-msg"'));
  assert.equal(after.includes('id="saveMsgClose"'), false);
});

test("#323 구조화 거절(무동작 일괄 재제안)도 인라인 채널로 간다", async () => {
  // 「돌릴 행이 없다」는 던져진 예외가 아니라 **판정 결과**다. catch 백스톱(`deps.notify`)이
  // 아니라 화면이 붙들 수 있는 자리로 가야 한다(무동작을 조용히 넘기지 않는다).
  const h = harness({
    initial: async () => snap({ section: "binding" }),
    call: async (_screen, action) => {
      if (action === "mapping_reset_stakes") return { resuggest_manual: 0, confirmed: 3 };
      if (action === "resuggest_all") return { resuggested: 0, kept_confirmed: 3 };
      return {};
    },
  });
  await h.controller.init();

  await h.controller.handleBindingMenu("resuggest-all");

  const message = h.controller.viewModel.getSnapshot().saveMessage;
  assert.ok(message && message.text.includes("확정한 3개는 그대로 둡니다"));
  assert.deepEqual(h.notices, []);
});

test("#323 던져진 예외는 여전히 catch 백스톱(window.alert)이 받는다", async () => {
  // 인라인 채널이 **모든** 통지를 삼키면 반대 결함이 된다: 화면이 그릴 수 없는 실패
  // (발신 자체가 죽은 경우)를 조용히 잃는다. 백스톱은 남는다.
  const h = harness({
    initial: async () => snap({ section: "binding" }),
    call: async (_screen, action) => {
      if (action === "save") throw new Error("브리지 단절");
      return {};
    },
  });
  await h.controller.init();

  assert.equal(await h.controller.doSave({}), false);
  assert.equal(h.controller.viewModel.getSnapshot().saveMessage, null);
  assert.equal(h.notices.length, 1);
  assert.ok(h.notices[0].includes("브리지 단절"));
});

/* ---------------- 알림의 해소 전이(#874) ---------------- */

/* 세우는 전이만 있고 지우는 전이가 없으면 인라인 채널은 과거를 계속 서술한다: 「⚠ 작업
   이름을 입력하세요.」가 한 번 서면 이름을 채워도, 저장이 성사돼도, 편집기를 다시 세워도
   그대로 남았다(컨트롤러는 부팅 1회 싱글턴이다). 사유가 해소되는 세 자리에서 걷는다. */

test("#874 겨눈 칸을 고치면 그 차단 알림이 사라진다 — 겨눔과 사유를 함께 걷는다", async () => {
  /* 겨눔은 그 칸이 **보이는 단계**에서만 선다(U6-D #978) — 이름은 3단계 폼에 산다. */
  const h = blockedSaveHarness("filename");
  await h.controller.init();

  assert.equal(await h.controller.doSave({}), false);
  assert.ok(h.controller.viewModel.getSnapshot().saveMessage, "차단 알림이 먼저 서 있어야 한다");
  assert.equal(h.controller.viewModel.getSnapshot().invalidField, NAME_FIELD);

  h.controller.type(NAME_FIELD, "채운 이름");

  const view = h.controller.viewModel.getSnapshot();
  assert.equal(view.saveMessage, null, "고친 칸을 계속 나무라지 않는다");
  assert.equal(view.invalidField, "");
});

test("U6-D 거절된 저장은 단계를 옮기지 않는다 — 지나온 단계의 편집을 파괴하지 않는다", async () => {
  /* 표면이 사람을 3단계로 데려가면 Python `_do_goto_section` 이 지나온 단계의 patch 를
     자동으로 버린다 — 연결 확인에서 방금 선언한 「비워 둠」이 **저장 거절 하나로** 사라진다.
     거절은 아무것도 파괴하지 않는 전이라 이동은 사람의 몫이고, 어느 단계인지는 차단 문안이
     말한다. 여기서 재는 것은 발신 집합(음성)과 화면 상태의 불변이다. */
  const calls = [];
  const h = harness({
    initial: async () => snap({
      section: "binding", is_draft: false, editing_origin: "공고서", dirty: true,
      reachable: { template: true, binding: true, filename: true },
    }),
    call: async (_screen, action) => {
      calls.push(action);
      return action === "save"
        ? { ok: false, block_reason: "'이름·저장' 단계에서 작업 이름을 입력하세요.", blocked_field: "name" }
        : {};
    },
  });
  h.ports.jobRead.bind({ refreshList() {}, openBrowseNeedsAction: async () => {} });
  await h.controller.init();

  assert.equal(await h.controller.doSave({}), false);

  assert.ok(!calls.includes("goto_section"),
    `거절이 단계 이동을 발신했습니다: ${calls.join(",")} — 그 이동이 지나온 patch 를 버립니다`);
  assert.equal(h.controller.model.getSnapshot().section, "binding", "화면이 옮겨갔습니다");
  assert.equal(h.controller.viewModel.getSnapshot().invalidField, "",
    "안 보이는 칸에 표지를 남기면 다음에 그 단계로 갔을 때 고치지도 않은 칸이 빨갛습니다");
  const message = h.controller.viewModel.getSnapshot().saveMessage;
  assert.ok(message && message.text.includes("'이름·저장' 단계"),
    `차단 문안이 고칠 단계를 지목하지 않습니다: ${message && message.text}`);
});

test("U6-D 단계를 옮기면 겨눔 표지가 걷힌다 — 끈적한 aria-invalid 금지", async () => {
  const h = blockedSaveHarness("filename");
  await h.controller.init();
  assert.equal(await h.controller.doSave({}), false);
  assert.equal(h.controller.viewModel.getSnapshot().invalidField, NAME_FIELD);

  await h.controller.gotoSection("binding");

  assert.equal(h.controller.viewModel.getSnapshot().invalidField, "");
});

test("#874 저장 성공은 앞선 차단 알림을 걷는다 — 겨눔 없는 차단도 성사에서 사라진다", async () => {
  // 겨눌 칸이 없는 차단(`blocked_field` 공백)은 타이핑 전이가 닿지 않는다 — 그 사유가
  // 사라졌음을 말하는 것은 저장 성사뿐이다. 성공 문구를 새로 짓지는 않는다.
  let blocked = true;
  const h = harness({
    initial: async () => snap({ section: "template", is_draft: false, editing_origin: "공고서" }),
    call: async (_screen, action) => {
      if (action !== "save") return {};
      return blocked
        ? { ok: false, block_reason: "템플릿을 먼저 골라야 저장할 수 있습니다.", blocked_field: "" }
        : { ok: true };
    },
  });
  h.ports.jobRead.bind({ refreshList() {}, openBrowseNeedsAction: async () => {} });
  await h.controller.init();

  assert.equal(await h.controller.doSave({}), false);
  assert.ok(h.controller.viewModel.getSnapshot().saveMessage);
  h.controller.type(PATTERN_FIELD, "무관한 칸");
  assert.ok(h.controller.viewModel.getSnapshot().saveMessage,
    "사유가 그대로면 알림도 그대로다 — 아무 타이핑이나 지우지 않는다");

  blocked = false;                       // 사유 해소(템플릿 선택)
  assert.equal(await h.controller.doSave({}), true);
  assert.equal(h.controller.viewModel.getSnapshot().saveMessage, null,
    "성사된 저장 뒤에 차단 문안이 남으면 사용자는 실패했다고 읽는다");
});

test("#874 편집기 세션이 다시 서면 앞 세션의 알림은 남지 않는다", async () => {
  const h = blockedSaveHarness("template");
  await h.controller.init();

  assert.equal(await h.controller.doSave({}), false);
  assert.ok(h.controller.viewModel.getSnapshot().saveMessage);

  // 새 작업 초안으로 편집기가 다시 선다(session `job:공고서` → `draft`).
  h.store.ingest("editor", snap({ section: "template", is_draft: true }));

  assert.equal(h.controller.viewModel.getSnapshot().saveMessage, null,
    "컨트롤러가 싱글턴이라 세션 전이에서 걷지 않으면 앞 작업의 경고가 새 작업에 실린다");
});

/* ---------------- ⑤ 통로는 객체째 ---------------- */

test("client.dispatch 프로퍼티 교체가 관측된다 — 메서드 사전 추출 없음", async () => {
  const h = harness();
  await h.controller.init();

  const seen = [];
  h.client.dispatch = async (screen, action, payload) => {
    seen.push([screen, action, payload]);
    return { ok: true, value: {} };
  };
  await h.controller.refreshLibrary();   // Bridge.call("tpl","refresh",{}) 직행의 후계
  assert.deepEqual(seen, [["tpl", "refresh", {}]], "교체된 client.dispatch 가 호출을 받았다");
});

/* ---------------- local draft reducer ---------------- */

const DRAFT_SESSION = "job:작업A";

function draft(values, revision = 1) {
  return ingestSnapshot(emptyDraft(), { session: DRAFT_SESSION, revision, values });
}

test("push는 편집 중인 field를 보존하고 손대지 않은 이웃만 갱신한다", () => {
  const protect = [
    (state) => typeInto(state, NAME_FIELD, "내 값"),
    (state) => markField(state, NAME_FIELD, { focused: true }),
    (state) => markField(state, NAME_FIELD, { composing: true }),
  ];
  for (const prepare of protect) {
    let state = prepare(draft({ [NAME_FIELD]: "옛 값", [PATTERN_FIELD]: "옛 규칙" }));
    const held = valueOf(state, NAME_FIELD);
    state = ingestSnapshot(state, {
      session: DRAFT_SESSION,
      revision: 2,
      values: { [NAME_FIELD]: "서버 값", [PATTERN_FIELD]: "새 규칙" },
    });
    assert.equal(valueOf(state, NAME_FIELD), held);
    assert.equal(valueOf(state, PATTERN_FIELD), "새 규칙");
  }
});

test("token/session이 낡은 응답은 draft를 바꾸지 않고 stale로 관측된다", () => {
  let state = typeInto(draft({ [NAME_FIELD]: "서버" }), NAME_FIELD, "첫 편집");
  const first = issueToken(state, NAME_FIELD);
  state = typeInto(first.state, NAME_FIELD, "둘째 편집");
  const second = issueToken(state, NAME_FIELD);
  const late = settle(second.state, {
    ok: true,
    session: DRAFT_SESSION,
    token: first.token,
    key: NAME_FIELD,
    serverValue: "첫 편집",
  });
  assert.equal(valueOf(late, NAME_FIELD), "둘째 편집");
  assert.equal(late.fields[NAME_FIELD].pendingToken, second.token);
  assert.equal(late.staleResponses, 1);

  const moved = ingestSnapshot(late, {
    session: "job:작업B",
    revision: 1,
    values: { [NAME_FIELD]: "B" },
  });
  assert.equal(valueOf(moved, NAME_FIELD), "B");
  assert.equal(moved.staleResponses, 0);
});

test("성공은 Python 확인값이 draft와 같을 때만 clean으로 승격한다", () => {
  let state = typeInto(draft({ [NAME_FIELD]: "서버" }), NAME_FIELD, "새 이름");
  const issued = issueToken(state, NAME_FIELD);
  assert.equal(hasInFlight(issued.state), true);

  const unconfirmed = settle(issued.state, {
    ok: true,
    session: DRAFT_SESSION,
    token: issued.token,
    key: NAME_FIELD,
  });
  assert.equal(unconfirmed.fields[NAME_FIELD].dirty, true);

  const confirmed = settle(issued.state, {
    ok: true,
    session: DRAFT_SESSION,
    token: issued.token,
    key: NAME_FIELD,
    serverValue: "새 이름",
  });
  assert.equal(confirmed.fields[NAME_FIELD].dirty, false);
  assert.equal(valueOf(confirmed, NAME_FIELD), "새 이름");
  assert.equal(hasInFlight(confirmed), false);

  const failed = settle(issued.state, {
    ok: false,
    session: DRAFT_SESSION,
    token: issued.token,
    key: NAME_FIELD,
    error: "이름 중복",
  });
  assert.equal(fieldError(failed, NAME_FIELD), "이름 중복");
  assert.equal(valueOf(failed, NAME_FIELD), "새 이름");
});

/* ---------------- 겨눔은 행이 설 때까지 살아 있는다 ---------------- */

test("겨눔 요청은 그 행이 실제로 렌더될 때까지 살아 있는다", async () => {
  // 진입 성사 직후에는 매핑 표가 아직 DOM 에 없다(렌더는 다음 틱이다). 그 순간 한 번 겨누고
  // 요청을 버리면 초점은 **영영** 서지 않는다 — 행은 나중에 생기는데 아무도 다시 겨누지 않는다.
  // 실측으로 SX-05 actual shell 이 여기서 20s 시한으로 죽었다: 행은 있고 초점만 없었다.
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    let row = null; // 아직 렌더 전
    const rowSelector = '#editor-body table.map tr[data-field="추가확인"]';
    const doc = {
      getElementById: () => null,
      querySelector: (selector) => (selector === rowSelector ? row : null),
      activeElement: null,
    };
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();

    h.controller.aimAt("binding/추가확인");
    assert.deepEqual(focused, [], "없는 행에 가짜 초점을 세우지 않는다");

    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    row = { scrollIntoView() {}, querySelector: () => select };
    h.controller.consumeAim(); // 행이 선 렌더

    assert.deepEqual(focused, ["row-source"], "행이 선 뒤에도 겨누지 않으면 초점은 영영 안 선다");
  } finally {
    globalThis.CSS = previous;
  }
});

test("겨눔은 성사되면 소비된다 — 나중 렌더가 남의 행을 다시 낚아채지 않는다", async () => {
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    const doc = { getElementById: () => null, querySelector: () => null, activeElement: null };
    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    const row = { scrollIntoView() {}, querySelector: () => select };
    doc.querySelector = () => row;
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();

    h.controller.aimAt("binding/추가확인");
    assert.deepEqual(focused, ["row-source"]);
    h.controller.consumeAim();
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source"], "한 번 선 초점을 매 렌더 다시 빼앗지 않는다");
  } finally {
    globalThis.CSS = previous;
  }
});

test("#789 진입 문맥이 지목한 자리를 보낸 화면의 호출 없이 스스로 겨눈다", async () => {
  // 종전에는 보낸 화면이 port 너머로 `aimAt` 을 불러 주기를 기다렸는데, 그 메서드는
  // `EditorEntryPort` 표면에 **없었다**. `typeof` 확인에 걸려 조용히 지나갔고, 그래서
  // deep-link 초점은 한 번도 선 적이 없다. 문맥은 이미 목표를 담아 여기 도착한다.
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    const doc = { getElementById: () => null, querySelector: () => row, activeElement: null };
    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    const row = { scrollIntoView() {}, querySelector: () => select };
    doc.querySelector = () => row;
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();

    h.controller.consumeAim(); // 렌더 훅 — 바깥에서 aimAt 을 부른 적이 없다

    assert.deepEqual(focused, ["row-source"]);
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source"], "문맥당 한 번만 겨눈다");
  } finally {
    globalThis.CSS = previous;
  }
});

test("#789 문맥이 없으면 겨누지 않고, 떠났다 다시 들어오면 또 겨눈다", async () => {
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    const doc = { getElementById: () => null, querySelector: () => null, activeElement: null };
    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    const row = { scrollIntoView() {}, querySelector: () => select };
    doc.querySelector = () => row;
    let context = {};
    const h = harness({ initial: async () => snap({ context }), doc });
    await h.controller.init();
    h.controller.consumeAim();
    assert.deepEqual(focused, [], "겨눌 자리를 안 지목한 진입은 초점을 옮기지 않는다");

    // 같은 자리로 **다시** 들어오면 그때도 겨눠야 한다. 문맥이 사라진 렌더가 기억을 비우므로
    // 두 번째 진입이 조용히 안 서는 일이 없다.
    context = { target: "binding/추가확인" };
    h.store.ingest("editor", snap({ context }));
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source"]);

    context = {};
    h.store.ingest("editor", snap({ context }));
    h.controller.consumeAim(); // 편집기를 떠났다 — 기억이 비워진다

    context = { target: "binding/추가확인" };
    h.store.ingest("editor", snap({ context }));
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source", "row-source"], "두 번째 진입부터 조용히 안 섭니다");
  } finally {
    globalThis.CSS = previous;
  }
});

test("#791 초점이 실제로 안 옮겨졌으면 성사로 치지 않고 다음 렌더가 다시 시도한다", async () => {
  // 요소가 **있다**는 것과 초점이 **섰다**는 것은 다르다. 비활성·숨김·전이 중이면 `focus()` 는
  // 조용한 no-op 다. 존재만 보고 성사했다고 답하면 조준은 「했다」고 말하면서 초점은 아무 데도
  // 안 서고, 그 거짓 성공이 재시도까지 막는다 — 실측으로 SX-05 가 정확히 그 상태였다.
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const attempts = [];
    let focusable = false;
    const doc = { getElementById: () => null, querySelector: () => null, activeElement: null };
    const select = {
      focus() {
        attempts.push("try");
        if (focusable) doc.activeElement = select; // 비활성 요소의 focus() 는 조용한 no-op
      },
    };
    const row = { scrollIntoView() {}, querySelector: () => select };
    doc.querySelector = () => row;
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();

    h.controller.consumeAim(); // 아직 초점을 못 받는 상태
    assert.equal(attempts.length, 1);
    assert.equal(doc.activeElement, null);

    focusable = true; // 다음 렌더에서 활성화됐다
    h.controller.consumeAim();
    assert.equal(doc.activeElement, select, "거짓 성공이 재시도를 막았습니다");
    assert.equal(attempts.length, 2);

    h.controller.consumeAim();
    assert.equal(attempts.length, 2, "성사한 뒤에는 매 렌더 다시 겨누지 않는다");
  } finally {
    globalThis.CSS = previous;
  }
});

test("#793 리렌더가 초점을 떨어뜨리면 지목한 자리를 다시 세운다", async () => {
  // 조준이 성사한 뒤에도 리렌더가 그 노드를 갈아 끼우면 초점이 조용히 `body` 로 떨어지고,
  // 그 틈을 면 닫힘의 대안 착지가 화면 루트로 채운다 — 그러면 사용자가 지목한 자리는 영영
  // 비어 있다. 실측으로 SX-05 의 focus 사건이 정확히 ['SELECT', 'SECTION#scr-editor'] 였다.
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    const screenRoot = { id: "scr-editor" };
    const doc = {
      getElementById: () => null,
      body: { id: "body" },
      activeElement: null,
      querySelector: (selector) => (String(selector) === ".scr.on" ? screenRoot : row),
    };
    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    const row = { scrollIntoView() {}, querySelector: () => select };
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();

    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source"]);

    // 면 닫힘의 대안 착지가 화면 루트를 잡았다(사용자가 고른 자리가 아니다).
    doc.activeElement = screenRoot;
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source", "row-source"], "지목한 자리가 비어 있는 채 끝났습니다");

    // 이제는 우리 자리가 잡고 있으므로 매 렌더 다시 겨누지 않는다.
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source", "row-source"]);
  } finally {
    globalThis.CSS = previous;
  }
});

test("#793 사용자가 스스로 옮긴 초점은 빼앗지 않는다", async () => {
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    const screenRoot = { id: "scr-editor" };
    const doc = {
      getElementById: () => null,
      body: { id: "body" },
      activeElement: null,
      querySelector: (selector) => (String(selector) === ".scr.on" ? screenRoot : row),
    };
    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    const row = { scrollIntoView() {}, querySelector: () => select };
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();
    h.controller.consumeAim();

    // 사용자가 다른 입력칸으로 갔다 — 여기서 되돌리면 남의 손을 잡아채는 것이다.
    doc.activeElement = { id: "editorName" };
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source"]);
  } finally {
    globalThis.CSS = previous;
  }
});

/* -------- ⑦ 항목 상세 시트 — 구간 항목 동사 3종 + 밴드 동사(S8-03 #834 · U6-E #979) -------- */

/** 검토가 낸 상세가 실린 **`tpl` 채널** 스냅샷(U6-E — 편집기 스냅샷이 아니다). */
function detailTpl(detail) {
  return tplSnap({
    detail: detail === undefined ? {
      path: "C:/lib/구간.hwpx", name: "구간", media: "hwpx",
      state: "compiled", badge_label: "누름틀", badge_level: "ok",
      field_count: 1, field_summary: "필드 1개",
      fields: [{ name: "계약명", type_hint: "text" }],
      actions: [{ key: "review", label: "검토" }],
      diagnostics: [],
      slots: {
        summary: "항목 1개 · 선택 1개",
        rows: [{
          id: "특약", label: "특약 사항", option_count: 1, options: ["지체상금 조항"],
        }],
      },
      error: "",
    } : detail,
  });
}

/** 그 상세를 보는 「고르기」 단계 편집기 스냅샷. */
function slotSnap(extra) {
  return snap(Object.assign({ section: "template" }, extra || {}));
}

/** 시트는 화면이 아니라 overlay portal 이라 **따로** 렌더한다(제품 배선과 같은 짝). */
function renderSheet(h) {
  return renderToStaticMarkup(createElement(TplDetailSheet, { controller: h.controller }));
}

function renderEditor(h) {
  return renderToStaticMarkup(createElement(EditorScreen, { controller: h.controller }));
}

test("U6-E 상세 시트가 머리·필드 표·구간 항목 표·동사 줄을 한 장에 세운다", async () => {
  const h = harness({ initial: async () => slotSnap(), tpl: detailTpl() });
  await h.controller.init();

  const markup = renderSheet(h);
  assert.ok(markup.includes('id="tplDetailTitle"') && markup.includes("구간"),
    "머리에 표시명이 서야 한다");
  assert.ok(markup.includes("C:/lib/구간.hwpx"), "경로를 재진술해야 한다");
  /* 필드는 표다 — 나열식 금지(#16)의 좌표를 시트가 잇는다. */
  assert.ok(markup.includes('class="schema-fields"'), "필드 표가 실재해야 한다");
  assert.ok(markup.includes("계약명") && markup.includes("텍스트"),
    "필드 이름과 추정 유형 라벨이 실린다");
  assert.ok(markup.includes("필드 1개"), "필드 표 머리는 Python 문안 그대로다");
  assert.ok(markup.includes('id="tplDetailSlots"'), "구간 항목 표가 실재해야 한다");
  assert.ok(markup.includes("특약 사항") && markup.includes("선택 1"),
    "투영된 이름·선택 수가 그대로 실린다");
  for (const act of ["slot-rename", "slot-decompile", "slot-remove"]) {
    assert.ok(markup.includes(`data-act="${act}"`), `${act} 트리거가 없다`);
  }
  assert.ok(markup.includes('data-slot="특약"'), "동사가 겨눌 항목 id 가 실려야 한다");
  /* 동사 줄은 행 ⋮ 와 같은 목록에서 「자세히…」만 걷은 것이다. */
  assert.ok(markup.includes('data-act="detail-act:review"'), "상태 동사가 시트에도 선다");
  assert.equal(markup.includes('data-act="detail-detail"'), false,
    "지금 서 있는 시트를 여는 동사를 시트 안에 또 세우지 않는다");
});

test("U6-E 상세가 없으면 시트는 빈 사유를 말한다(조용한 백지 금지)", async () => {
  const h = harness({ initial: async () => slotSnap(), tpl: tplSnap() });
  await h.controller.init();

  const markup = renderSheet(h);
  assert.ok(markup.includes('id="tplDetailEmpty"'), "빈 사유가 서야 한다");
  assert.equal(markup.includes('id="tplDetailSlots"'), false);
});

test("U6-E 판독 실패 항목의 시트는 사유를 보인다(오류 행의 「자세히…」가 답할 것)", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: detailTpl({
      path: "C:/txt/깨진.txt", name: "깨진", media: "txt",
      state: "", badge_label: "", badge_level: "muted",
      field_count: 0, field_summary: "읽기 실패: UTF-8 이 아닙니다",
      fields: [], actions: [], diagnostics: [], slots: null,
      error: "UTF-8 이 아닙니다",
    }),
  });
  await h.controller.init();

  const markup = renderSheet(h);
  assert.ok(markup.includes('id="tplDetailError"') && markup.includes("UTF-8 이 아닙니다"),
    "사유는 숨기지 않는다");
  assert.equal(markup.includes('id="tplDetailSlots"'), false,
    "구간 축이 없는 매체에 항목 표를 세우지 않는다");
  assert.equal(markup.includes('id="tplDetailVerbs"'), false,
    "읽을 수 없는 항목에 동사를 권하지 않는다");
});

test("S8-03 진단이 있으면 사유만 서고 동사 버튼은 없다", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: detailTpl({
      path: "C:/lib/구간.hwpx", name: "구간", media: "hwpx",
      state: "compiled", badge_label: "누름틀", badge_level: "ok",
      field_count: 0, field_summary: "채울 필드가 없습니다.", fields: [],
      actions: [], diagnostics: ["BOOKMARK '특약': invalid MetaTag JSON"],
      slots: { summary: "구간 구조를 읽을 수 없습니다: 구간", rows: [] },
      error: "",
    }),
  });
  await h.controller.init();

  const markup = renderSheet(h);
  assert.ok(markup.includes("invalid MetaTag JSON"), "사유는 숨기지 않는다");
  assert.equal(markup.includes('data-act="slot-remove"'), false,
    "못 믿는 구조 위에서 변이를 권하지 않는다");
});

test("S8-03 개명은 프롬프트 하나로 끝난다(확인 왕복 없음)", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: detailTpl(),
    prompt: () => "새 이름",
  });
  await h.controller.init();

  await h.controller.handleSlotVerb("rename", "특약", {});

  const sent = h.trace.filter((row) => row[0] === "dispatch" && row[1] === "tpl" && row[2] !== "refresh");
  assert.deepEqual(sent.map((row) => [row[2], row[3]]), [
    ["slot_rename", { path: "C:/lib/구간.hwpx", slot_id: "특약", label: "새 이름" }],
  ]);
  const prompted = h.trace.find((row) => row[0] === "modal.prompt");
  assert.equal(prompted[1].value, "특약 사항", "현재 이름이 초기값이어야 한다");
  assert.equal(h.trace.some((row) => row[0] === "modal.confirm"), false);
});

test("S8-03 개명 프롬프트 취소는 아무것도 보내지 않는다", async () => {
  const h = harness({ initial: async () => slotSnap(), tpl: detailTpl(), prompt: () => null });
  await h.controller.init();

  await h.controller.handleSlotVerb("rename", "특약", {});

  assert.equal(
    h.trace.some((row) => row[0] === "dispatch" && row[1] === "tpl" && row[2] !== "refresh"), false);
});

for (const [verb, action] of [["decompile", "slot_decompile"], ["remove", "slot_remove"]]) {
  test(`S8-03 '${verb}' 는 2왕복이고 확인 본문은 Python 이 싣는다`, async () => {
    const h = harness({
      initial: async () => slotSnap(),
      tpl: detailTpl(),
      call: async (_screen, name) => (
        name === action
          ? { needs_confirm: true, confirm_text: `${action} 재진술` }
          : {}
      ),
      confirm: () => true,
    });
    await h.controller.init();

    await h.controller.handleSlotVerb(verb, "특약", {});

    const sent = h.trace
      .filter((row) => row[0] === "dispatch" && row[1] === "tpl" && row[2] !== "refresh")
      .map((row) => [row[2], row[3]]);
    assert.deepEqual(sent, [
      [action, { path: "C:/lib/구간.hwpx", slot_id: "특약" }],
      [action, { path: "C:/lib/구간.hwpx", slot_id: "특약", confirm: true }],
    ]);
    const asked = h.trace.find((row) => row[0] === "modal.confirm");
    assert.ok(asked[1].body.includes(`${action} 재진술`),
      "확인 문안을 웹이 다시 조립하지 않는다");
    assert.equal(asked[1].danger, true);
  });

  test(`S8-03 '${verb}' 확인 취소는 확정 호출을 보내지 않는다`, async () => {
    const h = harness({
      initial: async () => slotSnap(),
      tpl: detailTpl(),
      call: async () => ({ needs_confirm: true, confirm_text: "재진술" }),
      confirm: () => false,
    });
    await h.controller.init();

    await h.controller.handleSlotVerb(verb, "특약", {});

    const sent = h.trace.filter((row) => row[0] === "dispatch" && row[1] === "tpl" && row[2] !== "refresh");
    assert.equal(sent.length, 1, "1차 질의 하나뿐이어야 한다");
    assert.equal(sent[0][3].confirm, undefined);
  });
}

test("S8-03 Slot 동사의 실패는 인라인 채널로 간다(#323 라우팅)", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: detailTpl(),
    prompt: () => "새 이름",
    call: async (_screen, action) => {
      if (action === "slot_rename") throw new Error("항목이 없습니다");
      return {};
    },
  });
  await h.controller.init();

  await h.controller.handleSlotVerb("rename", "특약", {});

  const message = h.controller.viewModel.getSnapshot().saveMessage;
  assert.ok(message && message.text.includes("항목이 없습니다"));
  assert.deepEqual(h.notices, [], "구조화 실패는 window.alert 로 새지 않는다");
});

/* ---- U4-E3 #939 밴드 동사 「전부 표기로 되돌리기」 ---- */

test("U4-E3 밴드 동사는 행 동사와 같은 술어로 선다(진단 0 · 행 1건 이상)", async () => {
  const h = harness({ initial: async () => slotSnap(), tpl: detailTpl() });
  await h.controller.init();

  /* 항목 1건이어도 선다 — 개수 문턱을 새로 두면 2→1 이 되는 순간 손 밑에서 사라진다. */
  assert.ok(renderSheet(h).includes('data-act="slot-decompile-all"'), "행 1건에서도 서야 한다");
  /* 대상은 파일이라 겨눌 항목 id 가 없다. */
  assert.equal(renderSheet(h).includes('data-act="slot-decompile-all" data-slot'), false);

  const broken = harness({
    initial: async () => slotSnap(),
    tpl: detailTpl({
      path: "C:/lib/구간.hwpx", name: "구간", media: "hwpx",
      state: "compiled", badge_label: "누름틀", badge_level: "ok",
      field_count: 0, field_summary: "채울 필드가 없습니다.", fields: [], actions: [],
      diagnostics: ["BOOKMARK '특약': invalid MetaTag JSON"],
      slots: { summary: "읽을 수 없습니다", rows: [] }, error: "",
    }),
  });
  await broken.controller.init();
  assert.equal(renderSheet(broken).includes('data-act="slot-decompile-all"'), false,
    "못 믿는 구조 위에서 일괄 변이를 권하지 않는다");
});

test("U4-E3 밴드 동사는 2왕복이고 payload 에 slot_id 가 없다", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: detailTpl(),
    call: async (_screen, name) => (
      name === "slot_decompile_all"
        ? { needs_confirm: true, confirm_text: "항목 1개를 전부 …" }
        : {}
    ),
    confirm: () => true,
  });
  await h.controller.init();

  await h.controller.handleSlotVerb("decompile-all", "", {});

  const sent = h.trace
    .filter((row) => row[0] === "dispatch" && row[1] === "tpl" && row[2] !== "refresh")
    .map((row) => [row[2], row[3]]);
  assert.deepEqual(sent, [
    ["slot_decompile_all", { path: "C:/lib/구간.hwpx" }],
    ["slot_decompile_all", { path: "C:/lib/구간.hwpx", confirm: true }],
  ]);
  const asked = h.trace.find((row) => row[0] === "modal.confirm");
  assert.ok(asked[1].body.includes("항목 1개를 전부 …"),
    "확인 문안을 웹이 다시 조립하지 않는다");
  assert.equal(asked[1].danger, true);
});

test("U4-E3 밴드 동사 확인 취소는 확정 호출을 보내지 않는다", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: detailTpl(),
    call: async () => ({ needs_confirm: true, confirm_text: "재진술" }),
    confirm: () => false,
  });
  await h.controller.init();

  await h.controller.handleSlotVerb("decompile-all", "", {});

  const sent = h.trace.filter((row) => row[0] === "dispatch" && row[1] === "tpl" && row[2] !== "refresh");
  assert.equal(sent.length, 1, "1차 질의 하나뿐이어야 한다");
  assert.equal(sent[0][3].confirm, undefined);
});

/* -------- ⑦-b 「자세히…」의 도달성과 닫힌 집합 — U6-E #979 -------- */

test("U6-E 「자세히…」는 어떤 행에서도 선다(동사 0 인 행이 없다)", () => {
  /* U6-B 뒤 COMPILED 행의 동사가 0 이 되며 ⋮ 가 비활성이던 자리다 — 그 상태에서만 존재하는
     구간 동사에 닿을 길이 함께 사라졌었다. 이제 어느 행이든 답할 것이 하나 있다. */
  const compiled = libRowMenuItems("hwpx", { actions: [] });
  assert.deepEqual(compiled.map((entry) => entry.action), ["detail"]);
  const raw = libRowMenuItems("hwpx", { actions: [{ key: "compile", label: "누름틀·구간 변환" }] });
  assert.deepEqual(raw.map((entry) => entry.action), ["act:compile", "detail"]);
  assert.deepEqual(libRowMenuItems("txt", { error: "" }).map((entry) => entry.action),
    ["edit", "detail"]);
  assert.deepEqual(libRowMenuItems("txt", { error: "UTF-8 아님" }).map((entry) => entry.action),
    ["detail"]);
  /* 항목이 아예 없을 때만 빈 목록이다(방어). */
  assert.deepEqual(libRowMenuItems("hwpx", null), []);
});

test("U6-E 동사 0 인 행의 ⋮ 도 활성이다(비활성 + 사유는 근거와 함께 걷혔다)", async () => {
  const h = harness({
    initial: async () => slotSnap({ template_path: "C:/lib/a.hwpx" }),
    tpl: tplSnap({
      hwpx: {
        flat: true, count: 1, dir: "C:/lib", empty_hint: "",
        sections: [{
          group: "", collapsed: false, count: 1,
          items: [{
            key: "a.hwpx", name: "a", path: "C:/lib/a.hwpx", detail: "필드 3개",
            badge_label: "누름틀", badge_level: "ok",
            actions: [], selectable: true, select_block_reason: "",
          }],
        }],
      },
    }),
  });
  await h.controller.init();

  const markup = renderEditor(h);
  const more = markup.slice(markup.indexOf('data-act="lib-more"'));
  assert.ok(more, "행 ⋮ 가 서야 한다");
  assert.equal(more.slice(0, more.indexOf("</button>")).includes("disabled"), false,
    "동사 0 인 행이 없으므로 ⋮ 를 잠그지 않는다");
});

test("좌 열의 고른 행은 `pairing.template_key` 가 정한다(경로 대조를 표면이 다시 하지 않는다)", async () => {
  const twoRows = tplSnap({
    hwpx: {
      flat: true, count: 2, dir: "C:/lib", empty_hint: "",
      sections: [{
        group: "", collapsed: false, count: 2,
        items: [
          { key: "a.hwpx", name: "a", path: "C:/lib/a.hwpx", detail: "필드 3개",
            badge_label: "누름틀", badge_level: "ok",
            actions: [], selectable: true, select_block_reason: "" },
          { key: "b.hwpx", name: "b", path: "C:/lib/b.hwpx", detail: "필드 1개",
            badge_label: "누름틀", badge_level: "ok",
            actions: [], selectable: true, select_block_reason: "" },
        ],
      }],
    },
  });
  const h = harness({
    initial: async () => slotSnap({
      template_path: "C:/lib/a.hwpx",
      /* 경로는 a 를 가리키는데 키는 b 다 — 표면이 경로로 다시 판정하면 여기서 갈린다. */
      pairing: { template_key: "b.hwpx", data_key: "", ready: false },
    }),
    tpl: twoRows,
  });
  await h.controller.init();

  const markup = renderEditor(h);
  const pressed = markup.match(/data-key="([^"]+)"[^>]*aria-pressed="true"|aria-pressed="true"[^>]*data-key="([^"]+)"/g) || [];
  assert.equal(pressed.length, 1, "고른 행은 하나여야 한다");
  assert.ok(/b\.hwpx/.test(pressed[0]), `키가 정한 행이 서야 한다: ${pressed[0]}`);
});

test("U6-E 「자세히…」는 검토 왕복 뒤에 시트를 연다(순서가 계약)", async () => {
  const h = harness({ initial: async () => slotSnap(), tpl: detailTpl() });
  await h.controller.init();

  await h.controller.openDetail("C:/lib/구간.hwpx", {});

  const sent = h.trace.filter((row) => row[0] === "dispatch" && row[1] === "tpl" && row[2] !== "refresh");
  assert.deepEqual(sent.map((row) => [row[2], row[3]]), [
    ["review", { path: "C:/lib/구간.hwpx" }],
  ]);
  const opened = h.trace.filter((row) => row[0] === "modal.open");
  assert.deepEqual(opened.map((row) => row[1]), ["tplDetailModal"]);
  assert.ok(
    h.trace.indexOf(sent[0]) < h.trace.indexOf(opened[0]),
    "왕복이 먼저다 — 먼저 열면 지난 항목의 상세가 한 프레임 선다");
});

test("U6-E 행 ⋮ 의 모르는 키는 조용히 떨어지지 않는다(닫힌 집합)", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: tplSnap({
      hwpx: {
        flat: true, count: 1, dir: "C:/lib", empty_hint: "",
        sections: [{
          group: "", collapsed: false, count: 1,
          items: [{
            key: "a.hwpx", name: "a", path: "C:/lib/a.hwpx", detail: "필드 3개",
            actions: [], selectable: true, select_block_reason: "",
          }],
        }],
      },
    }),
  });
  await h.controller.init();
  h.controller.toggleLibMenu("tpl", "hwpx", "a.hwpx", { });

  await h.controller.handleLibMenu("act:없는동사");

  assert.equal(h.notices.length, 1, "던진 예외가 백스톱까지 올라와야 한다");
  assert.ok(h.notices[0].includes("알 수 없는 항목 동사"), h.notices[0]);
});

test("U6-E 게이트 존은 필드 수 한 줄 + 「자세히…」로 접힌다(스키마 표는 시트로 갔다)", async () => {
  const h = harness({
    initial: async () => slotSnap({
      template_path: "C:/lib/a.hwpx", template_name: "a", field_count: 3,
      session_detail: { available: true, reason: "" },
    }),
    tpl: tplSnap(),
  });
  await h.controller.init();

  const markup = renderEditor(h);
  assert.ok(markup.includes('id="editorTplGate"'), "게이트 존이 서야 한다");
  assert.ok(markup.includes("필드 3개"), "남는 수치는 field_count 하나다");
  assert.ok(markup.includes('data-act="session-detail"'), "세션 템플릿의 시트 문이 서야 한다");
  assert.equal(markup.includes('data-act="session-detail" disabled'), false,
    "열 수 있는 항목의 문을 잠그지 않는다");
  /* 걷힌 표면들 — 되살아나면 같은 사실이 두 자리에서 그려진다. */
  assert.equal(markup.includes('class="schema-fields"'), false, "스키마 표는 시트로 갔다");
  assert.equal(markup.includes('id="tplSlots"'), false, "구간 항목 밴드는 시트로 갔다");
  assert.equal(markup.includes('id="editorSlotSummary"'), false, "구간 요약은 시트로 갔다");
  assert.equal(markup.includes("작성 출처"), false, "작성 출처 블록은 퇴역했다");
  assert.equal(markup.includes('class="filechip"'), false, "선택 chip 은 퇴역했다");
});

test("U6-E 리뷰 5 — 서식 폴더 밖 템플릿은 시트 문이 잠기고 사유가 병기된다", async () => {
  const h = harness({
    initial: async () => slotSnap({
      template_path: "C:/밖/저장본.hwpx", template_name: "저장본", field_count: 3,
      session_detail: { available: false, reason: "서식 폴더 밖의 템플릿이라 …" },
    }),
    tpl: tplSnap(),
  });
  await h.controller.init();

  const markup = renderEditor(h);
  const button = markup.slice(markup.indexOf('data-act="session-detail"'));
  assert.ok(button.slice(0, button.indexOf("</button>")).includes("disabled"),
    "열리지 않는 문을 활성으로 두지 않는다");
  assert.ok(markup.includes('id="editorTplDetailBlock"') && markup.includes("서식 폴더 밖"),
    "사유를 병기해야 한다(조용히 잠그지 않는다)");
});

test("U6-E 리뷰 6 — 작성 출처 드리프트 경고는 세션 게이트 존에 산다", async () => {
  const h = harness({
    initial: async () => slotSnap({
      template_path: "C:/lib/a.hwpx", template_name: "a", field_count: 3,
      session_detail: { available: true, reason: "" },
      schema_drift: "작성 당시와 템플릿 필드 구성이 다릅니다. 매핑 재검토가 필요할 수 있습니다.",
    }),
    tpl: tplSnap(),
  });
  await h.controller.init();

  const markup = renderEditor(h);
  assert.ok(markup.includes('id="editorSchemaDrift"'), "경고 자리가 실재해야 한다");
  assert.ok(markup.includes("매핑 재검토가 필요할 수 있습니다"), "문안은 Python 값 그대로다");
  /* 판정이 없으면 자리도 서지 않는다 — 웹이 필드 목록을 다시 대조하지 않는다. */
  const quiet = harness({
    initial: async () => slotSnap({
      template_path: "C:/lib/a.hwpx", template_name: "a", field_count: 3,
      session_detail: { available: true, reason: "" }, schema_drift: "",
    }),
    tpl: tplSnap(),
  });
  await quiet.controller.init();
  assert.equal(renderEditor(quiet).includes('id="editorSchemaDrift"'), false);
});

test("U6-E 리뷰 8 — RAW·판독 실패에서도 이름과 「폴더에서 보기」가 남는다", async () => {
  for (const state of [
    { raw_block: "누름틀이 없는 원본입니다.", gate_error: false },
    { raw_block: "", gate_error: true },
  ]) {
    const h = harness({
      initial: async () => slotSnap(Object.assign({
        template_path: "C:/lib/원본.hwpx", template_name: "원본", field_count: 0,
        session_detail: { available: true, reason: "" },
      }, state)),
      tpl: tplSnap(),
    });
    await h.controller.init();

    const markup = renderEditor(h);
    assert.ok(markup.includes('id="editorTplGate"'), "게이트 존이 서야 한다");
    assert.ok(markup.includes("원본"), "고칠 파일의 이름이 그 문장 옆에 있어야 한다");
    assert.ok(markup.includes("폴더에서 보기"),
      "「파일을 고치세요」라고 말하면서 고치러 갈 길을 지우지 않는다");
    assert.ok(markup.includes('data-act="session-detail"'), "시트 문도 그대로 선다");
  }
});

test("U6-E 리뷰 3 — 시트가 열려 있으면 결과·동사 실패가 그 면 안에 선다", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: detailTpl(),
    prompt: () => "새 이름",
    call: async (_screen, action) => {
      if (action === "slot_rename") throw new Error("항목이 없습니다");
      return {};
    },
  });
  await h.controller.init();
  await h.controller.openDetail("C:/lib/구간.hwpx", {});

  await h.controller.handleSlotVerb("rename", "특약", {});

  const markup = renderSheet(h);
  assert.ok(markup.includes('id="tplDetailMsg"') && markup.includes("항목이 없습니다"),
    "시트가 덮은 화면 뒤가 아니라 시트 안에 서야 한다");
  assert.equal(h.controller.viewModel.getSnapshot().saveMessage, null,
    "스크림 뒤 채널(#save-msg)에는 쓰지 않는다");
  assert.deepEqual(h.notices, [], "구조화 실패는 window.alert 로 새지 않는다");
});

test("U6-E 리뷰 3 — 시트는 tpl 결과 줄을 자기 안에 그린다", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: tplSnap({ result: { text: "변환할 수 없습니다 구간.hwpx: …", level: "warn" } }),
  });
  await h.controller.init();

  const markup = renderSheet(h);
  assert.ok(markup.includes('id="tplDetailResult"'), "시트 결과 줄이 실재해야 한다");
  assert.ok(markup.includes("변환할 수 없습니다"), "문안은 Python 값 그대로다");
});

test("U6-E 리뷰 3 — 시트가 닫히면 그 면의 사유는 남지 않는다", async () => {
  const h = harness({ initial: async () => slotSnap(), tpl: detailTpl() });
  await h.controller.init();
  await h.controller.openDetail("C:/lib/구간.hwpx", {});
  const opened = h.trace.find((row) => row[0] === "modal.open");

  /* 닫힘은 모달 엔진의 `beforeClose` 가 지른다 — 그 한 자리가 열림 표지와 사유를 함께 걷는다. */
  opened[2].beforeClose();

  assert.equal(h.controller.viewModel.getSnapshot().detailOpen, false);
  assert.equal(h.controller.viewModel.getSnapshot().detailMessage, null);
});

test("U6-E 리뷰 9·10 — 행 ⋮ 와 시트 동사 줄이 같은 분기표를 지난다", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: detailTpl(),
    call: async () => ({}),
  });
  await h.controller.init();
  await h.controller.openDetail("C:/lib/구간.hwpx", {});

  /* 같은 모르는 키가 두 진입에서 **둘 다** 던진다(한쪽만 조용하지 않다). */
  await h.controller.handleDetailVerb("act:없는동사", {});
  assert.ok(String(h.controller.viewModel.getSnapshot().detailMessage || "")
    .includes("알 수 없는 항목 동사"), "시트 동사의 미지 키가 조용히 떨어졌습니다");

  /* `act:review` 는 퇴역했다 — 검토 왕복은 「자세히…」 하나가 진다(리뷰 10). */
  await h.controller.handleDetailVerb("act:review", {});
  assert.ok(String(h.controller.viewModel.getSnapshot().detailMessage || "")
    .includes("알 수 없는 항목 동사"), "act:review 가 살아 있습니다");
});

test("U6-E 결과 줄은 관리 동사가 나가는 좌 열 바닥에 선다", async () => {
  const h = harness({
    initial: async () => slotSnap(),
    tpl: tplSnap({ result: { text: "검토: 문제 없음", level: "ok" } }),
  });
  await h.controller.init();

  const markup = renderEditor(h);
  assert.ok(markup.includes("검토: 문제 없음"), "결과 줄이 그려져야 한다");
  const pool = markup.indexOf('id="editorTplPool"');
  const data = markup.indexOf('id="editorDataPool"');
  const result = markup.indexOf("run-result");
  assert.ok(pool < result && result < data,
    "결과 줄이 좌 열 안에 서야 한다(고르기 존 아래가 아니다)");
});

/* ------- ⑦b 우 데이터 열 — 좌 열과 **같은 컴포넌트**(고르기 열 공용 ③a) ------- */

/** 우 열 픽스처 한 벌 — 활성 1 · 끊김 1(고를 수 없는 행). */
const DAT_ROWS = [
  {
    key: "d1", name: "7월목록", kind: "excel", kind_label: "엑셀/CSV", status: "active",
    badge_label: "활성", badge_level: "ok", reference: "파일: 7월목록.xlsx · 시트 물품",
    locate_path: "C:/d/7월목록.xlsx", sheet: "물품", note: "", missing: false,
    actions: [{ key: "archive", label: "보관" }, { key: "delete", label: "삭제" }],
    selectable: true, select_block_reason: "",
  },
  {
    key: "d2", name: "지난목록", kind: "excel", kind_label: "엑셀/CSV", status: "active",
    badge_label: "참조 끊김", badge_level: "danger", reference: "파일: 지난목록.xlsx",
    locate_path: "C:/d/지난목록.xlsx", sheet: "", note: "", missing: true,
    actions: [{ key: "relink", label: "다시 연결…" }],
    selectable: false,
    select_block_reason: "참조가 끊겼습니다. '다시 연결' 뒤에 쓸 수 있습니다.",
  },
];

test("우 열은 `pool.column` 을 좌 열과 같은 `.pitem` 문법으로 그린다", async () => {
  const h = harness({
    initial: async () => snap({ pairing: pairing({ data_key: "d1" }) }),
    tpl: tplSnap(),
    pool: poolSnap(DAT_ROWS),
  });
  await h.controller.init();
  const markup = renderEditor(h);

  assert.ok(markup.includes('id="editorDataList"'), "우 열 목록 좌표가 없습니다");
  const marked = markup.match(/data-side="dat"/g) || [];
  /* 항목 2 × (본체 + ⋮) + 머리의 「새로 읽기」 1 = 5 — 두 열이 같은 컴포넌트라 ⋮ 도
     「새로 읽기」도 대칭으로 서고, 셋 다 자기 side 를 말한다. */
  assert.equal(marked.length, 5, markup.slice(markup.indexOf('id="editorDataPool"'), 400));
  assert.ok(markup.includes('data-key="d1"') && markup.includes('data-key="d2"'));
  /* 고름 표지는 **키 대조 하나**다(pairing.data_key). 행의 정체 좌표(`data-key`)는 끌기
     결속과 무관하게 행 자신이 들므로(③b) 상태 축은 그 **뒤**에 선다. */
  const from = (key) => markup.slice(markup.indexOf(`data-key="${key}"`),
    markup.indexOf(`data-key="${key}"`) + 300);
  const d1 = from("d1");
  assert.ok(d1.includes('aria-pressed="true"'), "겨눈 풀 행에 고름 표지가 없습니다");
  /* 못 고르는 행은 **숨기지 않고 눌린다** — `disabled` 면 사유를 말할 자리가 없다. */
  const d2 = from("d2");
  assert.ok(d2.includes('aria-disabled="true"'), "끊긴 행이 비활성 표시를 잃었습니다");
  assert.ok(!d2.includes(" disabled"), "끊긴 행이 `disabled` 라 클릭이 오지 않습니다");
  assert.ok(markup.includes("참조가 끊겼습니다"), "사유가 목록에서 사라졌습니다");
  /* 바닥 동사 줄 — 좌표는 불변이고, 「이 데이터 고정…」은 세션 행이 없으면 서지 않는다. */
  assert.ok(markup.includes('id="editorPoolBrowse"') && markup.includes('id="editorPoolPclm"'));
  assert.equal(markup.includes('id="editorPoolPin"'), false,
    "고정할 것이 없는데 「이 데이터 고정…」이 섰습니다");
  /* 「새로 읽기」도 대칭이다 — 우 열에도 같은 문이 선다. */
  assert.ok(markup.includes('data-act="refresh" data-side="dat"'), "우 열 「새로 읽기」 부재");
});

test("파일로 연 데이터는 세션 행으로 **맨 위**에 서고 「이 데이터 고정…」을 세운다", async () => {
  const h = harness({
    initial: async () => snap({
      data_path: "C:/d/7월목록.xlsx",
      pairing: pairing({ data_key: "", data_row: sessionRow() }),
    }),
    tpl: tplSnap(),
    pool: poolSnap(DAT_ROWS),
  });
  await h.controller.init();
  const markup = renderEditor(h);

  const session = markup.indexOf('data-key="session"');
  assert.ok(session > 0 && session < markup.indexOf('data-key="d1"'),
    "세션 행이 목록 맨 위에 서지 않았습니다");
  assert.ok(markup.includes("시트: 물품 · 헤더 1행 · 12행"),
    "현재 데이터의 재진술(시트·헤더 행·행 수)이 사라졌습니다");
  assert.ok(markup.includes("사용 중"), "「사용 중」 배지가 사라졌습니다");
  const head = markup.slice(session, session + 300);
  assert.ok(head.includes('aria-pressed="true"'), "세션 행에 고름 표지가 없습니다");
  assert.ok(markup.includes('id="editorPoolPin"'),
    "파일로 연 데이터인데 「이 데이터 고정…」이 서지 않았습니다");
});

test("세션 행은 다시 눌러도 **무동작**이다(거절도 발신도 없다)", async () => {
  const h = harness({
    initial: async () => snap({
      data_path: "C:/d/7월목록.xlsx",
      pairing: pairing({ data_key: "", data_row: sessionRow() }),
    }),
    tpl: tplSnap(), pool: poolSnap(DAT_ROWS),
  });
  await h.controller.init();

  assert.equal(await h.controller.chooseData("session"), false);
  assert.equal(h.controller.viewModel.getSnapshot().saveMessage, null,
    "지금 쓰고 있는 데이터를 「고를 수 없다」고 말했습니다");
  assert.deepEqual(
    h.trace.filter((row) => row[0] === "dispatch" && row[1] === "editor"), [],
    "세션 행 재선택이 세션을 다시 마운트했습니다");

  /* 끌어 놓기의 상대가 세션 행이면 **템플릿만** 바뀐다(데이터는 그대로). */
  await h.controller.dropPair("tpl", "없는템플릿", "session");
  const message = h.controller.viewModel.getSnapshot().saveMessage;
  assert.ok(message && message.text.includes("템플릿을 찾을 수 없습니다"), message);
  assert.ok(!message.text.includes("데이터를 찾을 수 없습니다"),
    "세션 행을 「사라진 데이터」로 거절했습니다");
});

test("고를 수 없는 우 열 행의 클릭은 조용히 삼켜지지 않는다(Python 사유 재진술)", async () => {
  const h = harness({
    initial: async () => snap({ pairing: pairing() }),
    tpl: tplSnap(), pool: poolSnap(DAT_ROWS),
  });
  await h.controller.init();

  assert.equal(await h.controller.chooseData("d2"), false);
  const message = h.controller.viewModel.getSnapshot().saveMessage;
  assert.ok(message && message.text.includes("'지난목록' 은(는) 고를 수 없습니다"), message);
  assert.ok(message.text.includes("참조가 끊겼습니다"), "Python 사유가 재진술되지 않았습니다");
  assert.deepEqual(
    h.trace.filter((row) => row[0] === "dispatch" && row[1] === "editor"), [],
    "고를 수 없는 행이 발신을 냈습니다");
});

test("우 열 ⋯ 는 링1 동사 뒤에 「폴더에서 보기」를 세운다(세션 행은 그 문 하나)", async () => {
  const h = harness({
    initial: async () => snap({
      data_path: "C:/d/7월목록.xlsx",
      pairing: pairing({ data_key: "", data_row: sessionRow() }),
    }),
    tpl: tplSnap(), pool: poolSnap(DAT_ROWS),
    call: async () => ({}),
  });
  await h.controller.init();
  const items = () => (h.controller.libContextMenu.model.getSnapshot() || {}).items || [];

  h.controller.toggleLibMenu("dat", "excel", "d1", {});
  assert.deepEqual(items().map((item) => item.action),
    ["act:archive", "act:delete", "reveal"],
    "링1 동사 목록을 표면이 다시 지었습니다");
  assert.deepEqual(items().map((item) => item.label), ["보관", "삭제", "폴더에서 보기"]);

  /* 세션 행은 풀 항목이 아니라 상태 동사가 없다 — 남는 것은 경로 문 하나다. */
  h.controller.toggleLibMenu("dat", "excel", "session", {});
  assert.deepEqual(items().map((item) => item.action), ["reveal"]);

  /* 상태 동사는 공용 `pool` 채널로 나간다(다이얼로그와 같은 몸통). */
  h.controller.toggleLibMenu("dat", "excel", "d1", {});
  await h.controller.handleLibMenu("act:archive");
  assert.deepEqual(
    h.trace.filter((row) => row[0] === "dispatch" && row[1] === "pool")
      .map((row) => [row[2], row[3]]),
    [["archive", { key: "d1" }]]);

  /* 「폴더에서 보기」는 좌 열 바닥 동사와 **같은 브리지**를 지난다. */
  h.controller.toggleLibMenu("dat", "excel", "session", {});
  await h.controller.handleLibMenu("reveal");
  assert.deepEqual(
    h.trace.filter((row) => row[0] === "invoke" && row[1] === "reveal_path"),
    [["invoke", "reveal_path", "C:/d/7월목록.xlsx"]]);

  /* 모르는 키는 조용히 떨어지지 않는다(좌 열과 같은 닫힌 집합 규율). */
  h.controller.toggleLibMenu("dat", "excel", "d1", {});
  await h.controller.handleLibMenu("없는동사");
  assert.ok(h.notices.some((text) => text.includes("알 수 없는 데이터 동사")), h.notices);
});

test("우 열 존 통지의 동사는 `pool/resolve_duplicate` 로 나가고 미지 키는 시끄럽다", async () => {
  const h = harness({
    initial: async () => snap({ pairing: pairing() }),
    tpl: tplSnap(),
    pool: poolSnap(DAT_ROWS, {
      duplicates: [{
        reference: "파일: 7월목록.xlsx · 시트 물품",
        entries: [{ key: "d1", name: "7월목록" }, { key: "d3", name: "7월분" }],
      }],
    }),
    call: async () => ({}),
  });
  await h.controller.init();

  const markup = renderEditor(h);
  assert.ok(markup.includes("같은 데이터"), "중복 통지가 우 열에 서지 않았습니다");
  assert.ok(markup.includes('data-notice-act="resolve_duplicate"'), "정리 동사가 없습니다");

  h.controller.poolNoticeAction("resolve_duplicate", { keep: "d1" });
  await new Promise((resolve) => { setTimeout(resolve, 0); });
  assert.deepEqual(
    h.trace.filter((row) => row[0] === "dispatch" && row[1] === "pool")
      .map((row) => [row[2], row[3]]),
    [["resolve_duplicate", { keep: "d1" }]]);

  h.controller.poolNoticeAction("없는통지동사", {});
  assert.ok(h.notices.some((text) => text.includes("알 수 없는 통지 동사")), h.notices);
});

/* ---------------- ⑧ TXT 저작 린트메모장(S10-05 #862 · #299 회수) ---------------- */

const LINT_CONTENT = "제목: {{공고명}}\n{{#항목 사유}}";
const LINT_REPLY = {
  slots: [],
  diagnostics: [{
    kind: "unbalanced_marker",
    message: "「항목 사유」 범위가 열린 채 파일이 끝났습니다 — 닫는 마커가 없습니다.",
    context: "{{#항목 사유}}",
  }],
  summary: { slots: 0, options: 0, fields: 1, markers: 1 },
  placements: [],
  spans: [
    { kind: "field", start: 4, end: 11, source: "{{공고명}}" },
    { kind: "marker", start: 12, end: 22, source: "{{#항목 사유}}" },
  ],
};

/** 디바운스(180ms) 뒤의 왕복까지 기다린다 — 고정 지연이 아니라 상한이다. */
async function awaitLint(controller, tries = 40) {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    if (controller.viewModel.getSnapshot().txtEdit?.lint !== null) return true;
    await new Promise((resolve) => { setTimeout(resolve, 20); });
  }
  return controller.viewModel.getSnapshot().txtEdit?.lint !== null;
}

/* ---------------- 연결 확정 대기가 무장 사유를 더한다(#911) ---------------- */

/** 편집 모드(탭) footer 가 서는 최소 스냅샷 — `binding_confirm` 만 갈아 끼운다. */
function footSnap(bindingConfirm, extra) {
  return snap(Object.assign({
    section: "binding", is_draft: false, editing_origin: "공고서", dirty: false,
    reachable: { template: true, binding: true, filename: true },
    binding_confirm: bindingConfirm,
  }, extra || {}));
}

async function footMarkup(bindingConfirm, extra) {
  const h = harness({ initial: async () => footSnap(bindingConfirm, extra) });
  await h.controller.init();
  return renderToStaticMarkup(createElement(EditorScreen, { controller: h.controller }));
}

const CONFIRM = { pending: true, label: "연결 확정", hint: "바꿀 것이 없어도 지금 연결을 확정해야 합니다." };

test("#911 확정 대기가 참이면 손대지 않은 세션에서도 저장 동사가 활성이다", async () => {
  const markup = await footMarkup(CONFIRM);

  const save = markup.slice(markup.indexOf('data-act="save"'));
  assert.equal(save.slice(0, save.indexOf(">")).includes("disabled"), false,
    "확정을 요구받는데 그 확정을 수행할 동사가 잠겨 있다(#911 그 결함)");
  assert.ok(markup.includes("연결 확정"), "무변경 확정을 「변경 저장」이라 부르지 않는다");
  assert.equal(markup.includes("변경 저장"), false);
  assert.ok(markup.includes(CONFIRM.hint), "왜 눌러야 하는지는 Python 문안 그대로 선다");
});

test("#911 확정 대기여도 「변경 버리기」는 dirty 술어 그대로다", async () => {
  const markup = await footMarkup(CONFIRM);

  const discard = markup.slice(markup.indexOf('data-act="discard-patch"'));
  assert.ok(discard.slice(0, discard.indexOf(">")).includes("disabled"),
    "확정 대기는 버릴 것을 만들지 않는다");
});

test("#911 손댄 세션은 확정 대기여도 「변경 저장」으로 남는다(라벨이 참말)", async () => {
  const markup = await footMarkup(CONFIRM, { dirty: true });

  assert.ok(markup.includes("변경 저장"), "고친 것이 있으면 그 저장이 확정도 겸한다");
  assert.equal(markup.includes(">연결 확정<"), false);
});

test("#911 확정 대기가 거짓이면 종전 무장 술어가 그대로다(무회귀)", async () => {
  const markup = await footMarkup({ pending: false, label: "연결 확정", hint: "…" });

  const save = markup.slice(markup.indexOf('data-act="save"'));
  assert.ok(save.slice(0, save.indexOf(">")).includes("disabled"),
    "클린 세션의 저장은 버리기와 같은 술어여야 한다");
  assert.equal(markup.includes('data-role="binding-confirm-hint"'), false,
    "대기가 아니면 설명 줄도 서지 않는다");
});

test("#911 스냅샷에 사실이 없으면 프런트가 확정을 발명하지 않는다", async () => {
  const h = harness({
    initial: async () => snap({
      section: "binding", is_draft: false, editing_origin: "공고서", dirty: false,
      reachable: { template: true, binding: true, filename: true },
    }),
  });
  await h.controller.init();
  const markup = renderToStaticMarkup(createElement(EditorScreen, { controller: h.controller }));

  const save = markup.slice(markup.indexOf('data-act="save"'));
  assert.ok(save.slice(0, save.indexOf(">")).includes("disabled"));
  assert.ok(markup.includes("변경 저장"));
});

test("S10-05 저작 창은 textarea 가 아니라 린트메모장 호스트를 세운다", async () => {
  const h = harness();
  await h.controller.init();
  h.controller.openTxtEdit("edit", "C:/t/기안.txt", "기안", LINT_CONTENT, {});

  const markup = renderToStaticMarkup(
    createElement(TxtEditDialog, { controller: h.controller }),
  );
  assert.ok(markup.includes('id="txtLintpad"'), "메모장이 붙을 자리가 없다");
  assert.ok(!markup.includes("<textarea"),
    "textarea 가 남아 있으면 두 편집 표면이 같은 값을 두고 다툰다");
  /* 「새 파일로 저장」은 편집 모드의 동사다 — 새 생성 창에는 원본이 없으므로 뜨지 않는다. */
  assert.ok(markup.includes('id="txtEditSaveAs"'), "편집 모드에 「새 파일로 저장」이 없다");
});

test("S10-05 새 TXT 창에는 「새 파일로 저장」이 서지 않는다(원본이 없다)", async () => {
  const h = harness();
  await h.controller.init();
  h.controller.openTxtEdit("new", "", "", "", {});

  const markup = renderToStaticMarkup(
    createElement(TxtEditDialog, { controller: h.controller }),
  );
  assert.ok(!markup.includes('id="txtEditSaveAs"'), "새 생성 창에 「새 파일로 저장」이 떴다");
});

test("S10-05 판정은 tpl/txt_lint 왕복에서 오고 문안은 그대로 재진술된다", async () => {
  const h = harness({
    call: async (_screen, action) => (action === "txt_lint" ? LINT_REPLY : {}),
  });
  await h.controller.init();
  const initialPulls = h.counts.initial;
  h.controller.openTxtEdit("edit", "C:/t/기안.txt", "기안", LINT_CONTENT, {});

  assert.ok(await awaitLint(h.controller), "디바운스 뒤에도 판정이 도착하지 않았다");
  const sent = h.trace.filter((row) => row[0] === "dispatch" && row[2] === "txt_lint");
  assert.equal(sent.length, 1, "린트 왕복은 디바운스로 한 번만 나간다");
  assert.deepEqual(sent[0][3], { content: LINT_CONTENT }, "본문만 싣는다(경로 없음)");
  /* 읽기 전용 동사라 editor 재당김을 태우지 않는다 — 글자마다 화면 전체가 돌면 안 된다. */
  assert.equal(h.counts.initial, initialPulls, "읽기 전용 왕복이 재당김을 태웠다");

  const markup = renderToStaticMarkup(
    createElement(TxtEditDialog, { controller: h.controller }),
  );
  assert.ok(markup.includes("닫는 마커가 없습니다"),
    "Python 이 낸 message 가 그대로 서지 않는다(kind 로 문안을 다시 지으면 갈린다)");
});

test("S10-05 낡은 응답은 새 본문을 덮지 않는다", async () => {
  const replies = [];
  const h = harness({
    call: async (_screen, action, payload) => {
      if (action !== "txt_lint") return {};
      /* 첫 요청만 늦게 답한다 — 그 사이 사용자가 더 쳤다. */
      const late = payload.content === LINT_CONTENT;
      await new Promise((resolve) => { setTimeout(resolve, late ? 120 : 0); });
      const reply = { ...LINT_REPLY, summary: { ...LINT_REPLY.summary, markers: late ? 99 : 1 } };
      replies.push(payload.content);
      return reply;
    },
  });
  await h.controller.init();
  h.controller.openTxtEdit("edit", "C:/t/기안.txt", "기안", LINT_CONTENT, {});
  await new Promise((resolve) => { setTimeout(resolve, 200); });
  h.controller.typeTxtEdit("{{공고명}}");
  assert.ok(await awaitLint(h.controller), "둘째 판정이 도착하지 않았다");
  await new Promise((resolve) => { setTimeout(resolve, 200); });

  const lint = h.controller.viewModel.getSnapshot().txtEdit.lint;
  assert.equal(lint.content, "{{공고명}}", "판정이 본 본문이 화면의 것과 다르다");
  assert.equal(lint.summary.markers, 1, "늦게 온 옛 응답이 새 판정을 덮었다");
});

test("S10-05 「새 파일로 저장」은 기존 txt_new 를 재사용한다(새 동사 없음)", async () => {
  const h = harness({ prompt: () => "회의결과" });
  await h.controller.init();
  h.controller.openTxtEdit("edit", "C:/t/기안.txt", "기안", LINT_CONTENT, {});

  await h.controller.saveTxtEditAsNew({});

  const verbs = h.trace.filter((row) => row[0] === "dispatch" && row[1] === "tpl" && row[2] !== "refresh")
    .map((row) => row[2]);
  assert.ok(verbs.includes("txt_new"), "새 파일 저장이 txt_new 를 부르지 않았다");
  assert.ok(!verbs.includes("txt_edit"), "새 파일 저장이 원본까지 덮었다");
  const call = h.trace.find((row) => row[0] === "dispatch" && row[2] === "txt_new");
  assert.deepEqual(call[3], { name: "회의결과", content: LINT_CONTENT });
});

test("S10-05 「새 파일로 저장」 취소는 아무것도 발신하지 않는다", async () => {
  const h = harness({ prompt: () => null });
  await h.controller.init();
  h.controller.openTxtEdit("edit", "C:/t/기안.txt", "기안", LINT_CONTENT, {});

  await h.controller.saveTxtEditAsNew({});

  assert.equal(
    h.trace.filter((row) => row[0] === "dispatch" && row[2] === "txt_new").length, 0,
    "취소했는데 파일이 만들어졌다");
  assert.notEqual(h.controller.viewModel.getSnapshot().txtEdit, null, "취소가 창을 닫았다");
});

test("S10-05 저장 성공은 「변경사항 확인/적용」이 남았음을 인라인으로 말한다", async () => {
  const h = harness();
  await h.controller.init();
  h.controller.openTxtEdit("edit", "C:/t/기안.txt", "기안", LINT_CONTENT, {});

  await h.controller.submitTxtEdit();

  const message = h.controller.viewModel.getSnapshot().saveMessage;
  assert.equal(message.level, "ok");
  assert.ok(message.text.includes("변경사항 확인") && message.text.includes("변경사항 적용"),
    `저장이 반영까지 한 것처럼 읽힌다: ${message.text}`);
  const markup = renderToStaticMarkup(
    createElement(EditorScreen, { controller: h.controller }),
  );
  assert.ok(markup.includes('id="save-msg"') && markup.includes("변경사항 확인"),
    "안내가 갈 인라인 자리에 실제로 실리지 않았다");
});

test("S10-05 스팬→데코 투영은 문서 밖·겹침·미지 kind 를 버린다", () => {
  assert.deepEqual(
    usableSpans([{ kind: "field", start: 4, end: 11 }, { kind: "marker", start: 12, end: 22 }], 22),
    [
      { from: 4, to: 11, className: "cm-txtField" },
      { from: 12, to: 22, className: "cm-txtMarker" },
    ],
  );
  // 문서가 줄어든 뒤 도착한 좌표 — 자르고, 빈 것은 버린다.
  assert.deepEqual(usableSpans([{ kind: "field", start: 4, end: 11 }], 6),
    [{ from: 4, to: 6, className: "cm-txtField" }]);
  assert.deepEqual(usableSpans([{ kind: "field", start: 8, end: 11 }], 6), []);
  // 겹침은 RangeSet 이 던진다 — 뒤 조각을 버려 화면이 살아 있게 한다.
  assert.deepEqual(
    usableSpans([{ kind: "field", start: 0, end: 10 }, { kind: "marker", start: 5, end: 8 }], 20),
    [{ from: 0, to: 10, className: "cm-txtField" }],
  );
  // 모르는 어휘는 칠하지 않는다(조용히 틀린 색보다 무색이 낫다).
  assert.deepEqual(usableSpans([{ kind: "미래어휘", start: 0, end: 3 }], 20), []);
});

/* ⑧ 동봉 예제 상시 진입점(#891·#892)의 렌더·확인 왕복 계약은 여기 있었다 — 튜토리얼
   진입 표면과 함께 배포본에서 걷혔다(#941). `tpl` 채널의 `install_examples`·
   `remove_examples` 액션과 스냅샷 축 `library.examples` 는 동결로 남는다. */

/* ---------------- ⑦ 부팅 당김의 호스트 준비 게이트(U6-A 리뷰) ---------------- */

test("loadInitial 은 호스트 준비 뒤에만 initial 을 부른다 — 순서는 구조가 진다", async () => {
  let release;
  const ready = new Promise((resolve) => { release = resolve; });
  const h = harness({ whenReady: () => ready });

  const pending = h.controller.init();
  await Promise.resolve();
  await Promise.resolve();
  /* 준비 전에는 **한 번도** 부르지 않는다. 종전에는 「initSequence 에 넣어라」는 관례가
     유일한 방어였고, 그것을 모르는 호출자 하나가 실 WebView2 창을 못 뜨게 했다. */
  assert.equal(h.counts.initial, 0, "호스트 준비 전에 initial 이 나갔습니다.");

  release();
  await pending;
  assert.equal(h.counts.initial, 1, "준비 뒤에는 정확히 한 번 나간다.");
});

/* ───────────────────────── U6-C 연결 확인 표(#977) ─────────────────────────
   판정은 전부 링1·링2 에 있다(`gui/mapping_state.py`·`webapp/screen_editor.py`). 여기서
   재는 것은 **표면이 그 값을 그대로 쓰는가**와 **어느 액션으로 갈리는가** 둘뿐이다. */

const BIND_OPTIONS = [
  { value: "", label: "열을 고르세요", kind: "none", field: "" },
  { value: "col:업체명", label: "업체명", kind: "column", field: "업체명" },
  { value: "col:금액", label: "금액", kind: "column", field: "금액" },
  { value: "sp:const", label: "고정값…", kind: "const", field: "" },
  { value: "sp:today", label: "오늘 날짜", kind: "today", field: "" },
  { value: "sp:blank", label: "비워 둠", kind: "blank", field: "" },
];

const BIND_DISPLAY_GROUPS = [
  { label: "텍스트", options: [
    { value: "text:", label: "원문", type: "text", fmt: "" },
    { value: "text:phone", label: "전화", type: "text", fmt: "phone" }] },
  { label: "날짜", options: [
    { value: "date:", label: "표준", type: "date", fmt: "" },
    { value: "date:kor", label: "한글", type: "date", fmt: "kor" }] },
  { label: "금액", options: [
    { value: "amount:", label: "원", type: "amount", fmt: "" }] },
];

function bindRow(index, field, state, over) {
  /* `confirmable`·`revertable` 은 실 생산자와 **같은 규칙**으로 짓는다(리뷰 4·9). */
  const confirmed = state === "confirmed";
  const touched = state === "edited";
  const hasContent = state !== "needs_source";
  return Object.assign({
    index, template_field: field, inferred_type: "text", context: "",
    source: "", type: "text", const: "", fmt: "",
    display_options: BIND_DISPLAY_GROUPS, display_value: "text:",
    confirmed, touched,
    has_content: hasContent,
    confirmable: hasContent || confirmed,
    revertable: touched && !confirmed,
    suggestion_score: 0, preview: "값", preview_kind: "value",
    preview_empty: false, preview_error: false,
    row_state: state,
    state_label: {
      suggested: "제안", edited: "확인 필요", confirmed: "확인", needs_source: "확인 필요",
    }[state],
    source_kind: state === "needs_source" ? "" : "column",
    source_value: state === "needs_source" ? "" : "col:업체명",
    source_missing_label: "",
  }, over || {});
}

function bindSnap(extra) {
  return snap(Object.assign({
    section: "binding", record_count: 3, preview_index: 1, preview_count: 3,
    source_fields: ["업체명", "금액"], data_column_options: BIND_OPTIONS,
    sample_rows: [], schema_only: false, is_complete: false,
    binding_head: {
      suggested: 1, needs_confirm: 1, const: 0,
      promote_label: "제안 1건 모두 확인", promoted_label: "제안을 모두 확인했습니다",
      unused_columns: 2,
    },
    rows: [
      bindRow(0, "업체", "suggested", { source: "업체명" }),
      bindRow(1, "담당자", "needs_source", { preview: "", preview_kind: "none" }),
    ],
  }, extra || {}));
}

test("U6-C 특수 항목 선택은 열 이름 공간을 지나지 않고 자기 액션으로 갈린다", async () => {
  const h = harness({ initial: async () => bindSnap() });
  await h.controller.init();
  const sent = () => h.trace.filter((row) => row[0] === "dispatch" && row[1] === "editor")
    .map((row) => [row[2], row[3]]);

  h.controller.chooseDataColumn(1, "sp:const");
  h.controller.chooseDataColumn(1, "sp:today");
  h.controller.chooseDataColumn(1, "sp:blank");
  h.controller.chooseDataColumn(1, "col:금액");
  h.controller.chooseDataColumn(1, "");
  await h.controller.flushPendingEdits();

  assert.deepEqual(sent(), [
    ["set_display", { index: 1, type: "const", fmt: "" }],
    ["set_display", { index: 1, type: "today", fmt: "" }],
    ["set_blank", { index: 1 }],
    ["set_source", { index: 1, source: "금액" }],
    ["set_source", { index: 1, source: "" }],
  ]);
  // 센티넬이 소스 값으로 새면 동명 실열을 영영 못 겨눈다(리뷰 R5) — 그 부재를 못박는다.
  for (const [action, payload] of sent()) {
    if (action !== "set_source") continue;
    assert.equal(String(payload.source).startsWith("sp:"), false);
    assert.equal(String(payload.source).startsWith("col:"), false);
  }
});

test("U6-C 목록에 없는 항목 값은 조용히 무시되지 않는다", async () => {
  const h = harness({ initial: async () => bindSnap() });
  await h.controller.init();
  assert.throws(() => h.controller.chooseDataColumn(1, "sp:없는것"), /알 수 없는 데이터 열 항목/);
});

test("U6-C 상태 배지는 링1 라벨을 그대로 쓰고 채울 것 없는 행에서 잠긴다", async () => {
  const h = harness({ initial: async () => bindSnap() });
  await h.controller.init();
  const markup = renderToStaticMarkup(
    createElement(EditorScreen, { controller: h.controller }),
  );

  assert.ok(markup.includes('data-act="row-confirm"'), "배지 버튼이 없다");
  assert.equal(markup.includes('type="checkbox"'), false, "확정 체크박스가 남아 있다");
  assert.equal(markup.includes('data-act="row-type"'), false, "타입 열이 남아 있다");
  assert.equal(markup.includes('data-act="toggle-header"'), false, "열 선별 칩이 남아 있다");
  // 잠금은 `confirmable` 하나로 갈리고 사유를 함께 든다(말없는 무동작 금지).
  const badges = markup.match(/<button[^>]*data-act="row-confirm"[^>]*>/g) || [];
  assert.equal(badges.length, 2);
  assert.equal(badges[0].includes("disabled"), false, "내용 있는 행의 배지가 잠겼다");
  assert.ok(badges[1].includes("disabled"), "내용 없는 행의 배지가 열려 있다");
  assert.ok(markup.includes("열을 고르거나 고정값"), "잠긴 배지가 사유를 말하지 않는다");
  assert.ok(markup.includes(">제안<") && markup.includes(">확인 필요<"),
    "배지 문안이 스냅샷의 `state_label` 이 아니다");
});

test("U6-C 머리 pill·일괄 승격 문안은 스냅샷 값 그대로다", async () => {
  const h = harness({ initial: async () => bindSnap() });
  await h.controller.init();
  const markup = renderToStaticMarkup(
    createElement(EditorScreen, { controller: h.controller }),
  );

  assert.ok(markup.includes("자동 제안 1"));
  assert.ok(markup.includes("확인 필요 1"));
  assert.ok(markup.includes("고정값 0"));
  assert.ok(markup.includes("제안 1건 모두 확인"));
  assert.ok(markup.includes("사용하지 않는 데이터 열 2개"));

  // 승격할 제안이 0 이면 버튼은 잠기고 **다른 문안**을 든다(0 의 두 뜻을 Python 이 가른다).
  const done = harness({
    initial: async () => bindSnap({
      binding_head: {
        suggested: 0, needs_confirm: 0, const: 2,
        promote_label: "제안 0건 모두 확인", promoted_label: "제안을 모두 확인했습니다",
        unused_columns: 0,
      },
    }),
  });
  await done.controller.init();
  const after = renderToStaticMarkup(
    createElement(EditorScreen, { controller: done.controller }),
  );
  assert.ok(after.includes("제안을 모두 확인했습니다"));
  assert.equal(after.includes("제안 0건 모두 확인"), false);
});

test("U6-C 미리보기는 Python 이 낸 표식 문자열을 그대로 그린다", async () => {
  const h = harness({
    initial: async () => bindSnap({
      rows: [
        bindRow(0, "담당자", "suggested", {
          source: "업체명", preview: "〘미입력·담당자〙", preview_kind: "missing",
          preview_empty: true,
        }),
        bindRow(1, "비고", "confirmed", {
          preview: "", preview_kind: "blank", has_content: false, confirmable: false,
          source_kind: "blank", source_value: "sp:blank",
        }),
      ],
    }),
  });
  await h.controller.init();
  const markup = renderToStaticMarkup(
    createElement(EditorScreen, { controller: h.controller }),
  );
  // 표식은 UI 문안이 아니라 **문서에 박히는 데이터**라 웹이 짓지 않는다.
  assert.ok(markup.includes("〘미입력·담당자〙"), "빈 값이 빈칸으로 샜다");
  assert.ok(markup.includes('class="pv missing"'));
  assert.ok(markup.includes('class="pv blank"'));
});

test("U6-C 지연 flush 는 행의 열 축을 절대 다루지 않는다 — 항목 값이 set_source 로 새던 자리", async () => {
  // 데이터 열 select 가 초안을 갖던 동안 `flushPendingEdits` 의 일반 갈래가 그 초안
  // (`col:금액`)을 `set_source` 에 그대로 실어 **존재하지 않는 열**에 결속시켰다 —
  // R5 센티넬 금지의 정확한 위반이다. 초안을 두지 않는 것이 그 자리를 구조로 닫는다.
  const h = harness({ initial: async () => bindSnap() });
  await h.controller.init();

  h.controller.chooseDataColumn(1, "col:금액");
  await h.controller.flushPendingEdits();
  const sent = h.trace.filter((row) => row[0] === "dispatch" && row[1] === "editor");

  // 열 축은 **정확히 한 번**, 실 열 이름으로만 나간다(flush 가 두 번째를 더하지 않는다).
  const sources = sent.filter((row) => row[2] === "set_source");
  assert.equal(sources.length, 1);
  assert.deepEqual(sources[0][3], { index: 1, source: "금액" });
  for (const [, , action, payload] of sent) {
    for (const value of Object.values(payload || {})) {
      if (typeof value !== "string") continue;
      assert.equal(/^(col|sp):/.test(value), false,
        `${action} 이 항목 값 ${value} 를 실어 보냈다`);
    }
  }
});

test("U6-C 표시형 select 가 유형 축을 든다 — 그룹 + (유형, 표시형) 원자 발행", async () => {
  // `infer_type` 은 이름 키워드 휴리스틱이라 「계약일」이 text 로 추정되면 날짜 서식을
  // 영영 못 고른다. 유형 열이 걷힌 뒤 그 축이 사는 유일한 자리가 이 select 다.
  const h = harness({ initial: async () => bindSnap() });
  await h.controller.init();
  const markup = renderToStaticMarkup(
    createElement(EditorScreen, { controller: h.controller }),
  );
  assert.ok(markup.includes('<optgroup label="텍스트">'), "유형 그룹이 없다");
  assert.ok(markup.includes('<optgroup label="날짜">'));
  assert.ok(markup.includes('<optgroup label="금액">'));

  h.controller.chooseDisplay(0, "date:kor");
  await h.controller.flushPendingEdits();
  const sent = h.trace.filter((row) => row[0] === "dispatch" && row[1] === "editor");
  // **한 발**이다 — 유형이 바뀌면 표시형 키가 무효라 두 발 사이에는 사람이 고른 표시형이
  // 사라진 상태가 실재한다.
  assert.deepEqual(sent.map((row) => [row[2], row[3]]), [
    ["set_display", { index: 0, type: "date", fmt: "kor" }],
  ]);
  assert.throws(() => h.controller.chooseDisplay(0, "date:없는것"), /알 수 없는 표시형 항목/);
});

test("U6-C 비움 확정 행의 배지는 눌린다 — 확인을 풀 길이 있어야 한다", async () => {
  // `confirmable` 이 `has_content()` 뿐이면 「확인」 배지가 비활성으로 서서
  // 「열을 고르세요」라고 말한다 — 자기 상태와 어긋난 손잡이다.
  const h = harness({
    initial: async () => bindSnap({
      rows: [bindRow(0, "비고", "confirmed", {
        has_content: false, confirmable: true, source_kind: "blank",
        source_value: "sp:blank", preview: "", preview_kind: "blank",
      })],
    }),
  });
  await h.controller.init();
  const markup = renderToStaticMarkup(
    createElement(EditorScreen, { controller: h.controller }),
  );
  const badge = (markup.match(/<button[^>]*data-act="row-confirm"[^>]*>/g) || [])[0];
  assert.ok(badge && !badge.includes("disabled"), `비움 확정 배지가 잠겼다: ${badge}`);
});

test("U6-C ↻ 의 노출은 Python 술어 하나가 진다 — 웹이 재판정하지 않는다", async () => {
  // `_do_revert_source` 가 확정 행을 거절하는 것과 같은 술어라야 「눌렀는데 거절당하는」
  // 버튼이 남지 않는다. 웹이 `touched && !confirmed && record_count` 로 다시 조립하면
  // 그 셋 중 하나가 갈리는 날 어포던스와 거절이 어긋난다.
  const shown = harness({
    initial: async () => bindSnap({ rows: [bindRow(0, "업체", "edited")] }),
  });
  await shown.controller.init();
  assert.ok(renderToStaticMarkup(createElement(EditorScreen, { controller: shown.controller }))
    .includes('data-act="revert-source"'));

  // 스냅샷이 아니라고 하면 웹은 그리지 않는다 — touched 가 참이어도.
  const hidden = harness({
    initial: async () => bindSnap({
      rows: [bindRow(0, "업체", "edited", { revertable: false })],
    }),
  });
  await hidden.controller.init();
  assert.equal(renderToStaticMarkup(createElement(EditorScreen, { controller: hidden.controller }))
    .includes('data-act="revert-source"'), false, "웹이 술어를 재판정했다");
});

test("U6-C 「고정값…」 초점은 그 입력이 실제로 선 렌더에서 착지한다", async () => {
  // 입력은 **서버가 이 행을 const 로 인정한 뒤에야** 렌더된다 — 고른 순간의 DOM 에는
  // 없으므로 마이크로태스크로 겨누면 언제나 빈손이다.
  const h = harness({ initial: async () => bindSnap() });
  await h.controller.init();

  h.controller.chooseDataColumn(1, "sp:const");
  // 아직 서버가 인정하기 전 — 가져갈 초점이 대기 중이다.
  assert.equal(h.controller.takePendingConstFocus(0), false, "다른 행이 가져갔다");
  h.controller.chooseDataColumn(1, "sp:const");
  assert.equal(h.controller.takePendingConstFocus(1), true, "그 행이 초점을 가져간다");
  // 1회성이다 — 남기면 이후 재렌더가 사람이 옮긴 커서를 계속 빼앗는다.
  assert.equal(h.controller.takePendingConstFocus(1), false, "표지가 안 걷혔다");
});

test("U6-C 행 상태 class 넷은 두 CSS 에 **둘 다** 선언돼 있다 — 고아 검사", async () => {
  // `editor.ts` 의 닫힌 집합이 CSS 와 갈리면 그 상태는 화면에서 무표지가 된다. 특히
  // `forced-colors.css` 는 고대비에서 **틴트가 통째로 사라진 뒤** 상태를 잇는 유일한 층이라,
  // 여기서 빠진 클래스는 눈으로도 정적 검사로도 안 보인다(U6-C 리뷰 6 이 실제로 그 자리였다).
  const { readFileSync } = await import("node:fs");
  const product = readFileSync("frontend/css/editor.css", "utf8");
  const forced = readFileSync("frontend/css/forced-colors.css", "utf8");
  const classes = Object.values(ROW_STATE_CLASS);
  assert.equal(classes.length, 4);
  for (const cls of classes) {
    assert.ok(product.includes(`tr.${cls} `) || product.includes(`tr.${cls}{`),
      `editor.css 에 tr.${cls} 선언이 없다`);
    assert.ok(forced.includes(`tr.${cls} `) || forced.includes(`tr.${cls}{`),
      `forced-colors.css 에 tr.${cls} 선언이 없다 — 고대비에서 이 상태가 사라진다`);
  }
  // 반대 방향도 본다: CSS 에만 있는 유령 클래스는 퇴역을 안 따라온 잔재다.
  for (const stale of ["r-unconfirmed", "r-unmatched", "r-schemaonly"]) {
    assert.equal(product.includes(`tr.${stale}`), false, `editor.css 에 ${stale} 잔재`);
    assert.equal(forced.includes(`tr.${stale}`), false, `forced-colors.css 에 ${stale} 잔재`);
  }
});
