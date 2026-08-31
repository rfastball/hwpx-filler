/* [변경사항 확인]의 **거절 재진술** 계약(#804).
 *
 * `template_check` 는 실패해도 예외로 오지 않는다 — 종결된 판정을 `{"ok": false, ...}` 로
 * 돌려준다. 그 응답을 읽지 않으면 화면은 「눌렀는데 아무 일도 안 일어난다」가 되고, 그것이
 * #804 가 실 WebView2 에서 관측한 막다른 길의 직접 원인이었다(이 경로는 커버 0 건이었다).
 *
 * 재는 것 셋: ① 거절이 구획 재진술 + 알림 채널에 **둘 다** 착지한다(#957 — 실행 기록
 * 상자가 퇴역하면서 두 번째 착지가 `deps.notify` 로 옮겨졌다) ② 백엔드가 실어 보낸
 * `error` 문장이 정본이다(문안 재조립 금지) ③ 초기 등록 실패 문안은 존이 그리는 것과 **같은
 * 문장**이다(단일 출처). 판정·수치는 Python, 문안·집행만 웹이라는 링 계약의 표면이다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  JobTemplateChange,
  createJobRunController,
  tplCheckRefusalNotice,
} from "../../frontend/src/screens/job_run.ts";

function harness(options = {}) {
  const calls = [];
  const notified = [];
  let snapshot = options.snapshot ?? null;
  const subscribers = new Set();
  const model = {
    getSnapshot: () => ({ full: snapshot, progress: null }),
    subscribe(listener) {
      subscribers.add(listener);
      return () => subscribers.delete(listener);
    },
  };
  const runtime = { model: () => model, loadInitial: () => Promise.resolve({}) };
  const client = {
    invoke: () => Promise.resolve({ ok: true, value: null }),
    dispatch: (screen, action, payload) => {
      calls.push({ screen, action, payload });
      return Promise.resolve({ ok: true, value: options.dispatchValue ?? { ok: true } });
    },
  };
  const port = (impl) => {
    let bound = impl ?? null;
    return { bind(value) { bound = value; }, current: () => bound };
  };
  const controller = createJobRunController({
    runtime,
    client,
    ports: {
      jobRun: port(), jobRunCoordination: port(),
      jobData: port({ flushPendingEdits: () => Promise.resolve() }),
      jobRelinkFlow: port({ relinkTemplateFor: () => Promise.resolve() }),
      editorEntry: port({ openGuarded: () => true }),
    },
    services: { relink: port({ relinkTemplate: () => Promise.resolve(true) }) },
    modal: { confirm: () => Promise.resolve(true), open() {}, close() {} },
    navigation: { go() {}, currentScreen: () => "job" },
    doc: { getElementById: () => null, querySelector: () => null },
    selectionLine: (n) => `${n}행 선택`,
    notify(message) { notified.push(String(message)); },
  });
  const push = (value) => {
    snapshot = value;
    for (const listener of [...subscribers]) listener();
  };
  return { controller, calls, push, notified };
}

/** 스냅샷이 컨트롤러에 **실제로 도달한** 대역 — `init` 이 model 을 붙여야 세션 정체가 산다. */
async function seated(snap, options = {}) {
  const h = harness({ ...options, snapshot: snap });
  await h.controller.init();
  h.push(snap);
  return h;
}

/* 초기 등록에 실패한 작업 — 존은 확인을 비활성 + 사유 병기로 세운다(#659 S3-08). */
const NEEDS_INIT_SNAP = {
  has_job: true,
  job_name: "발주요청서 (복사본)",
  preview: { pos: 0, rows: [] },
  template_change: {
    supported: true,
    reason: "initialization_required",
    checkable: false,
    // 노출 술어는 Python 이 낸다(#932 B5) — 초기 등록 실패는 비활성 + 사유 병기로 **선다**.
    actionable: true,
    source_drift: null,
    source_drift_note: null,
    diagnostics: [{ kind: "not_a_package", message: "HWPX 꾸러미를 열지 못했습니다" }],
    epoch: null,
    preparation: null,
  },
};

/* 확인이 열려 있는 평범한 작업 — 거절이 여기로 오면 구획이 그것을 말해야 한다. */
const CHECKABLE_SNAP = {
  ...NEEDS_INIT_SNAP,
  template_change: {
    supported: true, reason: "", checkable: true, diagnostics: [],
    // 원본이 갈렸으니 확인이 열려 있고 존도 선다(#932 B5).
    actionable: true, source_drift: "changed",
    source_drift_note: "원본 파일이 캡처 이후 편집되었습니다.",
    epoch: null, preparation: null,
  },
};

test("초기 등록 실패 거절은 구획과 알림 채널에 함께 재진술된다", async () => {
  const h = await seated(CHECKABLE_SNAP, {
    dispatchValue: { ok: false, reason: "initialization_required" },
  });
  await h.controller.templateCheck();

  const notice = h.controller.getTemplateChange().notice;
  assert.ok(notice.includes("템플릿 초기 등록에 실패해"), `조용한 성공: ${notice}`);
  assert.equal(h.notified.length, 1);
  assert.ok(h.notified[0].includes("템플릿 초기 등록에 실패해"));
});

test("초기 등록 실패 문안은 존이 그리는 문장과 **같다**(단일 출처)", async () => {
  const h = await seated(NEEDS_INIT_SNAP);
  const zone = renderToStaticMarkup(createElement(JobTemplateChange, { controller: h.controller }));
  const restated = tplCheckRefusalNotice({ ok: false, reason: "initialization_required" });
  // 존 문안은 HTML 에 그대로 들어간다 — 두 자리가 갈리면 여기서 부러진다.
  assert.ok(zone.includes(restated), `존 문안과 재진술이 갈렸다: ${restated}`);
});

/* 준비를 마쳤고 원본도 그대로다 — 조치가 없는 종결 상태(#932 B5). */
const SETTLED_SNAP = {
  ...NEEDS_INIT_SNAP,
  template_change: {
    supported: true, reason: "", checkable: true, diagnostics: [],
    actionable: false, source_drift: "unchanged", source_drift_note: null,
    epoch: 1, preparation: null,
  },
};

test("조치가 없으면 존은 서지 않는다 — U4 12번", async () => {
  const h = await seated(SETTLED_SNAP);
  const zone = renderToStaticMarkup(createElement(JobTemplateChange, { controller: h.controller }));
  assert.equal(zone, "", `조치 없는 상태에서 존이 섰다: ${zone}`);
});

test("결과 재진술이 서 있는 동안에는 숨기지 않는다 — 재진술 수명은 웹 소유", async () => {
  const h = await seated(SETTLED_SNAP, {
    dispatchValue: { ok: false, reason: "initialization_required" },
  });
  await h.controller.templateCheck();  // 거절 한 줄이 구획에 앉는다

  const zone = renderToStaticMarkup(createElement(JobTemplateChange, { controller: h.controller }));
  assert.ok(zone.includes("jobTplNotice"), "재진술이 존과 함께 증발했다");
  // 조치는 없는데 재진술만 남은 자리라 「조치 필요」로 부르지 않는다(24번).
  assert.ok(zone.includes("템플릿 변경사항"), zone);
  assert.ok(!zone.includes("템플릿 조치 필요"), zone);
});

test("조치가 있을 때만 「조치 필요」로 부른다 — 12·24 는 한 판정", async () => {
  const h = await seated(CHECKABLE_SNAP);
  const zone = renderToStaticMarkup(createElement(JobTemplateChange, { controller: h.controller }));
  assert.ok(zone.includes("템플릿 조치 필요"), zone);
  // status 가 없는 자리는 드리프트 재진술이 문장을 진다(빈 칸으로 새지 않는다).
  assert.ok(zone.includes("원본 파일이 캡처 이후 편집되었습니다."), zone);
});

test("백엔드가 실은 error 문장이 정본이다 — 프런트가 다시 짓지 않는다", async () => {
  const backend = "문서 작업이 변경되어 선택을 해제했습니다. 문서 작업을 다시 선택하세요.";
  const h = await seated(CHECKABLE_SNAP, {
    dispatchValue: { ok: false, reason: "work_context_changed", error: backend },
  });
  await h.controller.templateCheck();
  assert.equal(h.controller.getTemplateChange().notice, backend);
  assert.deepEqual(h.notified, [backend]);
});

test("좌석이 갈린 뒤 도착한 거절은 남의 구획에 안 앉되 알림 채널에는 남는다", async () => {
  const h = await seated(CHECKABLE_SNAP, {
    dispatchValue: { ok: false, reason: "work_context_changed", error: "다시 선택하세요." },
  });
  const pending = h.controller.templateCheck();
  h.push({ ...CHECKABLE_SNAP, job_name: "다른 작업" });  // 응답이 오는 사이 작업이 갈린다
  await pending;
  assert.equal(h.controller.getTemplateChange().notice, "");  // 남의 재진술 차단
  assert.equal(h.notified.length, 1);  // 그래도 사라지지는 않는다
});

test("표에 없는 사유도 조용히 비우지 않는다", () => {
  assert.ok(tplCheckRefusalNotice({ ok: false, reason: "알 수 없는 사유" }).includes("알 수 없는 사유"));
  assert.ok(tplCheckRefusalNotice({ ok: false }).length > 0);
});

test("성공(ok:true)은 아무 재진술도 남기지 않는다", async () => {
  const h = await seated(CHECKABLE_SNAP, {
    dispatchValue: { ok: true, preparation: { status: "no_change" } },
  });
  await h.controller.templateCheck();
  assert.equal(h.controller.getTemplateChange().notice, "");
  assert.deepEqual(h.notified, []);
});
