/* Library controller behavior: lifecycle, late binding, and serialized intents. */
import test from "node:test";
import assert from "node:assert/strict";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { LibraryScreen, createLibraryController } from "../../frontend/src/screens/library.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

const tick = () => new Promise((resolve) => setImmediate(resolve));

/* 그룹·태그 동사(moveModel·setMove·closeMove·confirmMove·openMove·editTags·
   showGroupMenu·closeGroupMenu·handleGroupMenu·groupContextMenu)는 U4 §2-30 에서
   표면과 함께 사라졌다 — 판정·영속은 링1·모델에 동결로 남는다.
   `installExamples`(#891 빈 상태의 두 번째 출구)도 같은 처분이다 — 튜토리얼 진입 표면과
   함께 배포본에서 걷혔고(#941) `tpl` 채널의 액션·스냅샷 축은 동결로 남는다. */
const SURFACE = [
  "init", "model", "axis",
  "toggleFavorite", "runPrimary", "newWork", "editWork", "renameJob",
  "cloneJob", "removeJob", "relink", "revealCorrupt", "deleteCorrupt",
  "doc", "client", "popover", "notify",
];

function build(options = {}) {
  let snapshot = options.snapshot ?? { detail: null, sections: [] };
  const runtimeCalls = [];
  const dispatchCalls = [];
  const invokes = [];
  const notifications = [];
  const navigation = [];
  const browse = [];
  const editor = [];
  const modalCalls = [];
  const menuCalls = [];
  const ports = createScreenPorts();
  const jobReadImpl = {
    refreshList() {},
    async openBrowseNeedsAction(name) { browse.push(name); },
  };
  ports.jobRead.bind(jobReadImpl);
  ports.editorEntry.bind({
    openGuarded(...args) { editor.push(["openGuarded", ...args]); return true; },
    newDraft(...args) { editor.push(["newDraft", ...args]); return true; },
    newDraftFromData(...args) { editor.push(["newDraftFromData", ...args]); return true; },
    land(...args) { editor.push(["land", ...args]); },
    restoreEntryFocus(...args) { editor.push(["restoreEntryFocus", ...args]); },
  });
  const services = createServiceHandoffPorts();
  services.relink.bind({ relinkTemplate: async (...args) => { menuCalls.push(["relink", ...args]); return true; } });
  const runtime = {
    model: () => ({ getSnapshot: () => snapshot, subscribe: () => () => {} }),
    loadInitial: async (screen) => {
      runtimeCalls.push(screen);
      if (options.initialError) throw options.initialError;
      return snapshot;
    },
  };
  const client = {
    dispatch: async (screen, action, payload) => {
      dispatchCalls.push([screen, action, payload]);
      const value = options.dispatch ? await options.dispatch(screen, action, payload) : {};
      return { ok: true, value };
    },
    invoke: async (method, ...args) => {
      invokes.push([method, ...args]);
      return { ok: true, value: options.invoke ? await options.invoke(method, ...args) : null };
    },
  };
  const modal = {
    confirm: async (spec) => { modalCalls.push(["confirm", spec]); return options.confirm ?? false; },
    prompt: async (spec) => { modalCalls.push(["prompt", spec]); return options.prompt ?? null; },
    open: (id, spec) => modalCalls.push(["open", id, spec]),
    close: (id) => modalCalls.push(["close", id]),
  };
  const controller = createLibraryController({
    doc: { activeElement: null, getElementById: () => null }, runtime, client, ports, services, modal,
    undo: { show: (...args) => menuCalls.push(["undo", ...args]) },
    popover: { place() {}, wireDismiss: () => () => {} },
    groupMenu: { show: (...args) => menuCalls.push(["show", ...args]), hide: () => menuCalls.push(["hide"]) },
    navigation: { go: (screen) => navigation.push(screen) },
    notify: (message) => notifications.push(String(message)),
  });
  return {
    controller, client, ports, jobReadImpl, runtimeCalls, dispatchCalls, invokes,
    notifications, navigation, browse, editor, modalCalls, menuCalls,
    setSnapshot(value) { snapshot = value; },
  };
}

test("공개 표면 — React library controller 키가 정확하다", () => {
  assert.deepEqual(Object.keys(build().controller), SURFACE);
});

test("init — initial pull은 screen runtime 한 곳에 위임한다", async () => {
  const h = build();
  await h.controller.init();
  assert.deepEqual(h.runtimeCalls, ["library"]);
});

test("첫 initial 실패 — controller가 조용히 삼키지 않는다", async () => {
  const h = build({ initialError: new Error("initial down") });
  await assert.rejects(h.controller.init(), /initial down/);
});

test("축 액션 — 호출 순서를 한 체인으로 직렬화한다", async () => {
  let active = 0;
  let peak = 0;
  const h = build({ dispatch: async () => {
    active += 1; peak = Math.max(peak, active); await tick(); active -= 1; return {};
  } });
  await Promise.all([
    h.controller.axis("set_view", { view: "recent" }),
    h.controller.axis("set_mode", { mode: "txt" }),
  ]);
  assert.equal(peak, 1);
  assert.deepEqual(h.dispatchCalls.map((row) => row[1]), ["set_view", "set_mode"]);
});

test("문서 만들기에서 사용 — incompatible이면 job 착지 뒤 확인 필요 탐색", async () => {
  const h = build({
    snapshot: { detail: { name: "작업A", primary: { target: "job" } } },
    dispatch: async (_screen, action) => action === "prefer_work" ? { reason: "incompatible" } : {},
  });
  await h.controller.runPrimary("작업A");
  assert.deepEqual(h.dispatchCalls[0], ["job", "prefer_work", { name: "작업A" }]);
  assert.deepEqual(h.navigation, ["job"]);
  assert.deepEqual(h.browse, ["작업A"]);
});

test("문서 만들기에서 사용 — compatible이면 명시 선택 뒤 job 착지", async () => {
  const h = build({
    snapshot: { detail: { name: "작업A", primary: { target: "job" } } },
    dispatch: async (_screen, action) => action === "prefer_work" ? { promoted: true } : {},
  });
  await h.controller.runPrimary("작업A");
  assert.deepEqual(h.dispatchCalls[0], ["job", "prefer_work", { name: "작업A" }]);
  assert.deepEqual(h.navigation, ["job"]);
  assert.deepEqual(h.browse, []);
});

test("편집 대상 primary — EditorEntry 6-key port로 위임한다", async () => {
  const h = build({ snapshot: { detail: { name: "작업A", primary: { target: "editor" } } } });
  await h.controller.runPrimary("작업A");
  assert.equal(h.editor[0][0], "openGuarded");
  assert.equal(h.editor[0][1], "작업A");
  assert.equal(h.editor[0][2].entry_reason, "library");
  assert.deepEqual(h.navigation, []);
});

test("JobReadPort late binding — 구성 뒤 교체한 메서드가 다음 호출에 잡힌다", async () => {
  const h = build({
    snapshot: { detail: { name: "작업A", primary: { target: "job" } } },
    dispatch: async () => ({ reason: "incompatible" }),
  });
  const late = [];
  h.jobReadImpl.openBrowseNeedsAction = async (name) => late.push(name);
  await h.controller.runPrimary("작업A");
  assert.deepEqual(late, ["작업A"]);
  assert.deepEqual(h.browse, []);
});

test("BridgeClient late binding — 교체한 dispatch가 다음 발신을 받는다", async () => {
  const h = build();
  const swapped = [];
  h.client.dispatch = async (...args) => { swapped.push(args); return { ok: true, value: {} }; };
  await h.controller.cloneJob("작업A");
  assert.deepEqual(swapped, [["library", "clone_job", { name: "작업A" }]]);
});

test("즐겨찾기 연타 — 같은 작업의 최신 intent를 직렬화한다", async () => {
  const h = build();
  await Promise.all([h.controller.toggleFavorite("작업A", false), h.controller.toggleFavorite("작업A", false)]);
  assert.deepEqual(h.dispatchCalls.map((row) => row[2].value), [true, false]);
});

/* ---------------------------------------------- 상세 재선택 바로가기 + 걷힌 표면 */
function detailSnapshot(detail) {
  return {
    view: "all", mode: "all", query: "", counts: {}, selected: detail.name,
    alerts: {}, corrupt_rows: [], detail,
    sections: [{ value: "", label: "", count: 1, headed: false, is_untagged: false,
      collapsed: false, rows: [{ name: detail.name, mode_label: detail.mode_label,
        health: {}, data_bound: detail.data_bound, favorited: false }] }],
  };
}

/* `pairing_detail` 은 U6-F(#980)의 상세 하단 존이다 — 카드(정체·수치) · 읽기 전용 4열 표 ·
   계획 한 줄. 행은 편집기 2단계와 같은 링1 투영이라 여기서는 **키를 그대로 그리는지**만
   본다(수치·라벨을 웹이 짓지 않는다는 것이 이 존의 요점이다). */
function pairingDetail(over = {}) {
  return {
    card: {
      template_name: "공고서", template_bound: true, template_missing: false,
      data_name: "월별", counted: true, template_field_count: 3, mapped_count: 2,
      unbound_count: 1, stale_count: 0,
    },
    rows: [
      { template_field: "공고명", source_label: "사업명", display_label: "원문",
        preview: "청사 냉난방 교체", preview_kind: "value" },
      { template_field: "계약금액", source_label: "금액", display_label: "1,234,567원",
        preview: "48,500,000원", preview_kind: "value" },
    ],
    more_fields: [], stale_fields: [], rows_basis: "template",
    first_row: { state: "ready", reason: "", record_count: 120 },
    plan: { state: "ready", pattern: "공고-{{ID}}", first_name: "공고-1-001.hwpx", count: 120 },
    output_folder: { directory: "D:\\문서\\Results", source: "default",
      source_label: "기본값", notice: "" },
    ...over,
  };
}

const BOUND_DETAIL = {
  name: "작업A", mode_label: "HWPX 문서 생성", primary: { label: "문서 만들기에서 사용", hint: "" },
  template_path: "C:/t.hwpx",
  data_bound: true, data_label: "월별.xlsx · 낙찰현황", data_path: "C:/월별.xlsx",
  health_causes: [], pairing_detail: pairingDetail(),
};

test("상세 재선택 — 템플릿·데이터 두 축이 각자 바로가기를 든다", () => {
  const h = build({ snapshot: detailSnapshot(BOUND_DETAIL) });
  const markup = renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
  assert.ok(markup.includes('id="libraryRepickTemplate"'));
  assert.ok(markup.includes("템플릿 재선택…"));
  assert.ok(markup.includes('id="libraryRepickData"'));
  assert.ok(markup.includes("데이터 재선택…"));
});

test("상세 재선택 — 미결속 데이터는 「연결하기」 하나뿐이다(재선택 버튼 없음)", () => {
  const h = build({ snapshot: detailSnapshot({
    ...BOUND_DETAIL, data_bound: false, data_label: "", data_path: "",
    pairing_detail: pairingDetail({ card: { ...pairingDetail().card, data_name: "" } }),
  }) });
  const markup = renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
  assert.ok(markup.includes("데이터 연결하기…"));
  assert.ok(!markup.includes('id="libraryRepickData"'));
  assert.ok(markup.includes('id="libraryRepickTemplate"'));   // 템플릿 축은 그대로 선다
});

test("editWork — section extra가 EditorEntry 문맥에 합류한다(착지 탭 deep-link)", async () => {
  /* 두 재선택 버튼의 onClick 이 부르는 그 경로다. 섹션 어휘는 Python 이 아는 값
     (`gui/edit_session.py`: template / binding)이고 배관은 `app.py` 가 이미 진다. */
  const h = build();
  await h.controller.editWork("작업A", { "여기서 할 것": "고르세요" }, { section: "template" });
  await h.controller.editWork("작업A", {}, { section: "binding" });
  assert.deepEqual(h.editor, [
    ["openGuarded", "작업A", {
      entry_reason: "library", evidence: { "여기서 할 것": "고르세요" },
      return_context: { surface: "library" }, section: "template",
    }],
    ["openGuarded", "작업A", {
      entry_reason: "library", evidence: {},
      return_context: { surface: "library" }, section: "binding",
    }],
  ]);
});

test("걷힌 상세 표면 — 실행 이력·실행 방식·옛 `bindings` 사슬은 렌더되지 않는다", () => {
  /* **U6-F(#980)에서 뒤집은 단언**: 종전 이 시험은 「필드 연결 표는 렌더되지 않는다」였다.
     #966 이 걷은 것은 정보가 아니라 **별도 라벨 사전을 든 payload 사슬**(`detail.bindings`)
     이었고, U6-F 의 표는 편집기 2단계와 **같은 링1 투영**·같은 라벨 상수를 두 번째 호스트가
     소비한다 — 웹이 라벨을 짓지 않으므로 「같은 상태를 두 곳이 판정」이 아니다. 그래서 남는
     금지는 옛 키 하나다: `bindings` 는 되살아나도 그려지지 않는다. */
  const h = build({
    snapshot: detailSnapshot({
      ...BOUND_DETAIL,
      // 낡은 페이로드가 되살아나도 표면은 그리지 않는다(소비처가 없어야 진짜 걷힌 것이다).
      last_run_display: "마지막 성공 실행 2026-07-09", run_note: "채운 원문을 검토해 복사합니다",
      bindings: [{ template_field: "계약명", source_label: "bidNtceNm", format_label: "텍스트", blank: false }],
    }),
  });
  const markup = renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
  assert.ok(!markup.includes("마지막 성공 실행"));
  assert.ok(!markup.includes("실행 방식"));
  assert.ok(!markup.includes("bidNtceNm"));
  assert.ok(markup.includes("HWPX 문서 생성"));               // 방식 부제는 남는다
  assert.ok(markup.includes("작업 이름"));                     // 검색 안내는 실제 축만 말한다
  assert.ok(!markup.includes("작업 이름, 그룹, 태그"));
});

test("상세 연결 존 — 카드 수치·4열 표·계획 줄을 스냅샷 그대로 그린다", () => {
  const h = build({ snapshot: detailSnapshot(BOUND_DETAIL) });
  const markup = renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
  assert.ok(markup.includes('id="libraryPairCard"'));
  assert.ok(markup.includes("공고서") && markup.includes("월별"));
  assert.ok(markup.includes("연결 2 / 3"));                    // 수치는 Python 이 센다
  assert.ok(markup.includes("확인 필요 1"));
  assert.ok(markup.includes("필드 3개"));
  assert.ok(markup.includes("템플릿 필드") && markup.includes("데이터 열")
    && markup.includes("표시형") && markup.includes("첫 행"));
  assert.ok(markup.includes('data-field="공고명"'));
  assert.ok(markup.includes("1,234,567원"));                   // 표시형 라벨도 Python 이 낸다
  assert.ok(markup.includes("48,500,000원"));
  /* 계획은 라벨 2행이다(2026-09-03) — 첫 이름 + 나머지 건수, 그리고 저장 폴더. 경로는
     표시용으로만 줄고 온전한 값은 `title` 에 선다. */
  assert.ok(markup.includes('id="libraryPlanLine"'));
  assert.ok(markup.includes("공고-1-001.hwpx") && markup.includes("외 119건"));
  assert.ok(markup.includes('title="D:\\문서\\Results"'));
  assert.ok(markup.includes("D:\\문서\\Results"));
});

test("상세 연결 존 — 프레임 밖 행은 건수로 명시한다(스크롤로 감추지 않는다)", () => {
  /* 2026-09-03 재판정: 이름 나열은 좁은 상세에서 표만큼 길어져 표를 밀어냈다. 표 밖 한 줄이
     「몇 개 중 몇 개」를 말하고 이름은 페이로드에만 남는다(숨기는 것이 아니라 세는 것이다). */
  const h = build({
    snapshot: detailSnapshot({
      ...BOUND_DETAIL,
      pairing_detail: pairingDetail({ more_fields: ["담당자", "연락처"] }),
    }),
  });
  const markup = renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
  assert.ok(markup.includes('id="libraryRowsTail"'));
  assert.ok(markup.includes("필드 4개 중 2개"));            // 행 2 + 프레임 밖 2
  assert.ok(!markup.includes("담당자"));                    // 이름은 더 그리지 않는다
});

test("상세 연결 존 — 프레임 밖 행이 없으면 꼬리 줄도 없다", () => {
  const h = build({ snapshot: detailSnapshot(BOUND_DETAIL) });   // more_fields: []
  const markup = renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
  assert.ok(!markup.includes('id="libraryRowsTail"'));
});

test("상세 연결 존 — 아직 못 읽은 첫 행은 빈 칸 마커, 읽기 실패는 사유다", () => {
  const pending = build({
    snapshot: detailSnapshot({
      ...BOUND_DETAIL,
      pairing_detail: pairingDetail({
        rows: [{ template_field: "공고명", source_label: "사업명", display_label: "원문",
          preview: "—", preview_kind: "pending" }],
        first_row: { state: "pending", reason: "", record_count: 0 },
        plan: { state: "pending", pattern: "공고-{{ID}}", first_name: "", count: 0 },
      }),
    }),
  });
  const pendingMarkup = renderToStaticMarkup(
    createElement(LibraryScreen, { controller: pending.controller }));
  assert.ok(pendingMarkup.includes('data-first-row="pending"'));
  assert.ok(pendingMarkup.includes('class="pv pending"'));
  assert.ok(pendingMarkup.includes("규칙 공고-{{ID}}"));       // 이름 대신 아는 것을 말한다
  assert.ok(!pendingMarkup.includes("120건"));

  const failed = build({
    snapshot: detailSnapshot({
      ...BOUND_DETAIL,
      pairing_detail: pairingDetail({
        rows: [{ template_field: "공고명", source_label: "사업명", display_label: "원문",
          preview: "", preview_kind: "error" }],
        first_row: { state: "error", reason: "경로를 찾을 수 없음: C:/월별.xlsx",
          record_count: 0 },
      }),
    }),
  });
  const failedMarkup = renderToStaticMarkup(
    createElement(LibraryScreen, { controller: failed.controller }));
  // 조용한 빈칸 금지 — 사유가 그 칸에 선다.
  assert.ok(failedMarkup.includes("경로를 찾을 수 없음: C:/월별.xlsx"));
});

test("상세 연결 존 — 표가 없는 갈래에서도 카드와 재선택 동사는 남는다", () => {
  /* 템플릿을 읽을 수 없으면 구조(표)는 못 그리지만 정체(카드)는 답할 수 있고, 무엇보다
     **고치러 가는 동사**가 카드에 있다 — 접으면 그 길이 함께 접힌다. */
  const h = build({
    snapshot: detailSnapshot({
      ...BOUND_DETAIL, template_missing: true,
      pairing_detail: {
        card: { template_name: "공고서", template_bound: true, template_missing: true,
          data_name: "월별", counted: false, template_field_count: 0, mapped_count: 0,
          unbound_count: 0, stale_count: 0 },
        rows: [], more_fields: [], stale_fields: [], rows_basis: "",
        first_row: null, plan: null, output_folder: null,
      },
    }),
  });
  const markup = renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
  assert.ok(markup.includes('id="libraryRepickTemplate"'));
  assert.ok(!markup.includes('id="libraryPairRows"'));
  assert.ok(!markup.includes("연결 0 / 0"));                   // 세지 않은 수치를 말하지 않는다
});

test("상세 연결 존 — 템플릿에서 사라진 연결은 이름까지 말한다", () => {
  /* 표에 섞으면 템플릿 필드인 척하므로 표 밖에서 말한다 — 건수만 말하면 무엇을 고쳐야
     하는지가 다시 숨는다(실행 게이트가 막는 상태다). */
  const h = build({
    snapshot: detailSnapshot({
      ...BOUND_DETAIL, pairing_detail: pairingDetail({
        card: { ...pairingDetail().card, stale_count: 2 },
        stale_fields: ["옛필드", "지운필드"],
      }),
    }),
  });
  const markup = renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
  assert.ok(markup.includes("템플릿에 없는 연결 2건: 옛필드 · 지운필드"));
});

test("상세 연결 존 — 저장본으로 그린 표는 그 사실을 말한다", () => {
  /* 템플릿을 읽지 못한 갈래. 표가 「템플릿의 현재 모습」인 척하면 사라진 필드·새 필드가
     조용히 감춰진다. */
  const h = build({
    snapshot: detailSnapshot({
      ...BOUND_DETAIL,
      pairing_detail: pairingDetail({
        rows_basis: "profile",
        card: { ...pairingDetail().card, counted: false, template_field_count: 0 },
      }),
    }),
  });
  const markup = renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
  assert.ok(markup.includes("템플릿을 읽지 못해 저장된 연결만 보여 줍니다."));
  assert.ok(!markup.includes("연결 2 / 3"));                   // 세지 않은 수치는 말하지 않는다
});

test("첫 행 칸 — 편집기 「미리보기」와 **같은 렌더러**라 닫힌 집합이 갈리지 않는다", () => {
  /* 두 벌의 스위치는 실제로 갈렸다(한쪽이 `blank` 와 `none` 을 한 문자로 접었다).
     비움 확정(`blank`)은 빈 칸이고, 결속이 없는 행(`none`)만 마커를 쓴다 — 「채우지
     않기로 했다」와 「아직 안 골랐다」는 다른 상태다. */
  const h = build({
    snapshot: detailSnapshot({
      ...BOUND_DETAIL,
      pairing_detail: pairingDetail({
        rows: [
          { template_field: "여백", source_label: "비워 둠", display_label: "—",
            preview: "", preview_kind: "blank" },
          { template_field: "담당자", source_label: "열을 고르세요", display_label: "원문",
            preview: "", preview_kind: "none" },
          { template_field: "금액", source_label: "금액", display_label: "원문",
            preview: "〘미입력·금액〙", preview_kind: "missing" },
        ],
      }),
    }),
  });
  const markup = renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
  assert.ok(markup.includes('<span class="pv blank"></span>'));
  assert.ok(markup.includes('<span class="pv none">—</span>'));
  assert.ok(markup.includes('<span class="pv missing">〘미입력·금액〙</span>'));
});

test("표의 행 클릭 — 편집기 2단계의 그 행을 겨눈 `target` 이 문맥에 실린다", async () => {
  /* 프런트의 **첫 `target` 소비자**다. 배관은 이미 서 있다: `app.py` 의 `open_editor` 가
     `ctx.target` 을 `load_job(target=…)` 으로 넘기고 뷰가 그 행을 겨눈다(신설 0). */
  const h = build();
  await h.controller.editWork("작업A", { "여기서 할 것": "확인" }, { target: "binding/공고명" });
  assert.deepEqual(h.editor, [
    ["openGuarded", "작업A", {
      entry_reason: "library", evidence: { "여기서 할 것": "확인" },
      return_context: { surface: "library" }, target: "binding/공고명",
    }],
  ]);
});
