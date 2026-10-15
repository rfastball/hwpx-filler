/* 작업 꾸러미 흐름(#1188 WP-05) — 파일 선택 → library 꾸러미 액션 → 확인 → 확정.
   판정(개수·충돌·재사용·계약)과 문장은 전부 Python 투영이다. 여기서는 흐름이 그 투영을
   그대로 나르는지, 취소·거절·낡은 지문·실패가 각자의 착지를 갖는지만 본다. */
import test from "node:test";
import assert from "node:assert/strict";

import { createWorkPackageActions, workPackagePlanBody } from "../../frontend/src/screens/work_package.ts";

const VIEW = {
  title: "작업 2개를 불러옵니다",
  jobs: [
    { name: "계약A", final_name: "계약A", note: "", template: "안내.hwpx",
      template_label: "새로 추가", has_contract: true },
    { name: "계약B", final_name: "계약B (2)", note: "‘계약B (2)’ 이름으로 불러옵니다",
      template: "안내.hwpx", template_label: "새로 추가", has_contract: true },
  ],
  templates: [{ display_name: "안내.hwpx", action: "new", label: "새로 추가", target: "안내.hwpx" }],
  presets: [],
  data_notice: "데이터는 들어 있지 않습니다. 불러온 뒤 작업마다 데이터를 연결하세요.",
};

function build({ picked = "C:/pkg/보낸작업.narumi", replies = {}, confirms = [] } = {}) {
  const invokes = [];
  const calls = [];
  const confirmsSeen = [];
  const notes = [];
  const refreshed = [];
  const queues = Object.fromEntries(Object.entries(replies).map(([key, list]) => [key, [...list]]));
  const answers = [...confirms];
  const actions = createWorkPackageActions({
    client: {
      invoke: async (method, ...args) => { invokes.push([method, ...args]); return { ok: true, value: picked }; },
      dispatch: async (screen, action, payload) => {
        calls.push([screen, action, payload]);
        return { ok: true, value: (queues[action] || []).shift() ?? {} };
      },
    },
    modal: { confirm: async (spec) => { confirmsSeen.push(spec); return answers.shift() ?? false; } },
    notify: (message) => notes.push(message),
    refresh: async (select) => { refreshed.push(select); },
  });
  return { actions, invokes, calls, confirmsSeen, notes, refreshed };
}

test("확인 본문 — 작업 줄 아래 템플릿 표지, 이름이 바뀐 작업만 그 줄, 끝에 데이터 안내", () => {
  assert.equal(workPackagePlanBody(VIEW), [
    "계약A",
    "  안내.hwpx · 새로 추가",
    "계약B",
    "  안내.hwpx · 새로 추가",
    "  ‘계약B (2)’ 이름으로 불러옵니다",
    "",
    "데이터는 들어 있지 않습니다. 불러온 뒤 작업마다 데이터를 연결하세요.",
  ].join("\n"));
});

test("내보내기 — 저장 창 취소는 아무 액션도 보내지 않는다", async () => {
  const h = build({ picked: null });
  await h.actions.exportAll();
  assert.deepEqual(h.invokes, [["pick_work_package_path", "export"]]);
  assert.deepEqual(h.calls, []);
});

test("내보내기 — 빠질 작업·계약 없이 실릴 작업은 Python 이 지은 한 확인 문장으로 묻고 확정만 다시 보낸다", async () => {
  const text = "템플릿을 읽을 수 없는 작업은 빠집니다: 계약C, 기안\n\n"
    +"데이터를 읽을 수 없어 확인 조건 없이 내보냅니다. 받는 쪽에서 연결을 직접 확정해야 합니다.";
  const h = build({
    replies: { export_work_package: [{ ok: true, needs_confirm: true, confirm_text: text }, { ok: true }] },
    confirms: [true],
  });
  await h.actions.exportAll();
  assert.equal(h.confirmsSeen[0].body, text);
  assert.equal(h.confirmsSeen[0].confirmLabel, "내보내기");
  assert.deepEqual(h.calls.map((row) => row[2]), [
    { path: "C:/pkg/보낸작업.narumi" },
    { path: "C:/pkg/보낸작업.narumi", confirm: true },
  ]);
  assert.deepEqual(h.notes, []);                      // 정상 경로는 무음
});

test("내보내기 — 확인을 거절하면 쓰지 않고, 실패는 Python 사유 그대로 알린다", async () => {
  const declined = build({
    replies: { export_work_package: [{ ok: true, needs_confirm: true, confirm_text: "x" }] },
  });
  await declined.actions.exportAll();
  assert.equal(declined.calls.length, 1);
  const failed = build({
    replies: { export_work_package: [{ ok: false, error: "작업 꾸러미를 만들 수 없습니다: 내보낼 수 있는 작업이 없습니다." }] },
  });
  await failed.actions.exportAll();
  assert.deepEqual(failed.notes, ["작업 꾸러미를 만들 수 없습니다: 내보낼 수 있는 작업이 없습니다."]);
});

test("불러오기 — 열기 창 취소·읽기 실패는 설치를 부르지 않는다", async () => {
  const cancelled = build({ picked: "" });
  await cancelled.actions.importPackage();
  assert.deepEqual(cancelled.invokes, [["pick_work_package_path", "import"]]);
  assert.deepEqual(cancelled.calls, []);
  const broken = build({
    replies: { inspect_work_package: [{ ok: false, error: "작업 꾸러미를 읽을 수 없습니다: digest 불일치" }] },
  });
  await broken.actions.importPackage();
  assert.deepEqual(broken.calls.map((row) => row[1]), ["inspect_work_package"]);
  assert.deepEqual(broken.notes, ["작업 꾸러미를 읽을 수 없습니다: digest 불일치"]);
  assert.equal(broken.confirmsSeen.length, 0);
});

test("불러오기 — 확인 창은 Python 제목·본문이고, 거절하면 설치하지 않는다", async () => {
  const h = build({ replies: { inspect_work_package: [{ ok: true, basis: "b1", view: VIEW }] } });
  await h.actions.importPackage();
  assert.equal(h.confirmsSeen[0].title, "작업 2개를 불러옵니다");
  assert.equal(h.confirmsSeen[0].body, workPackagePlanBody(VIEW));
  assert.equal(h.confirmsSeen[0].confirmLabel, "불러오기");
  assert.deepEqual(h.calls.map((row) => row[1]), ["inspect_work_package"]);
});

test("불러오기 — 낡은 지문은 새 계획을 다시 보이고, 다시 확인한 지문으로만 설치한다", async () => {
  const fresh = { ...VIEW, title: "작업 2개를 불러옵니다", jobs: VIEW.jobs.map((job) => ({ ...job, note: "x" })) };
  const h = build({
    replies: {
      inspect_work_package: [{ ok: true, basis: "b1", view: VIEW }],
      import_work_package: [
        { ok: false, stale: true, basis: "b2", view: fresh },
        { ok: true, imported: ["계약A", "계약B (2)"], message: "데이터 연결이 필요합니다." },
      ],
    },
    confirms: [true, true],
  });
  await h.actions.importPackage();
  assert.equal(h.confirmsSeen.length, 2);
  assert.equal(h.confirmsSeen[1].body, workPackagePlanBody(fresh));
  assert.deepEqual(h.calls.filter((row) => row[1] === "import_work_package").map((row) => row[2]), [
    { path: "C:/pkg/보낸작업.narumi", basis: "b1" },
    { path: "C:/pkg/보낸작업.narumi", basis: "b2" },
  ]);
  assert.deepEqual(h.refreshed, ["계약A"]);
  assert.deepEqual(h.notes, ["데이터 연결이 필요합니다."]);
});

test("불러오기 — 설치 실패는 목록을 다시 읽지 않고 사유를 알린다", async () => {
  const h = build({
    replies: {
      inspect_work_package: [{ ok: true, basis: "b1", view: VIEW }],
      import_work_package: [{ ok: false, error: "작업 꾸러미를 읽을 수 없습니다: 쓰기 실패" }],
    },
    confirms: [true],
  });
  await h.actions.importPackage();
  assert.deepEqual(h.refreshed, []);
  assert.deepEqual(h.notes, ["작업 꾸러미를 읽을 수 없습니다: 쓰기 실패"]);
});
