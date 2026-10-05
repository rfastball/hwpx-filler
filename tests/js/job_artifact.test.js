/* 만든 문서 「내용 보기」(#1138) — 보기 전용 렌더링·행 아이콘·실패 표시의 계약.
 *
 * 1. **보기 전용** — 마운트 인자는 `readOnly` 이고 편집으로 이어지는 훅(보존 검사·선택 추적·문맥 메뉴·
 *    범위 고르기·선택 사각형)을 싣지 않는다. Studio 가 넘기는 셸 키는 Escape(닫기)만 듣고 저장 키는 버린다.
 *    내보내기(onChanged)는 아무것도 하지 않는다.
 * 2. **원료 → 마운트** — 원료는 Python 응답의 bytes 그대로 렌더러에 간다. 원료 거절·요청 실패·마운트
 *    실패는 모두 거절 면 값이 되고 렌더러는 서지 않는다(성공처럼 보이는 대체 없음).
 * 3. **면·행 렌더** — 관찰이 선 면은 렌더러 자리만 세우고 옛 텍스트 투영을 그리지 않는다. 문서 행은
 *    폴더에서 보기·내용 보기 두 아이콘 단추이고 경로 복사가 없다.
 * WASM iframe 은 Node 에서 띄울 수 없다 — 실 Studio 의 거동은 selftest(`job_result.artifact`)와 실렌더 몫이다. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  ARTIFACT_RENDER_FAILED,
  JobArtifactSheet,
  artifactViewerSpec,
  renderFailure,
  showArtifact,
} from "../../frontend/src/screens/job_artifact.ts";
import { JobResultZone } from "../../frontend/src/screens/job_result.ts";
import { initialRunState } from "../../frontend/src/screens/job_run_state.ts";

const HOST = { id: "host" };

function fakeController(lastFull, result = null) {
  const run = { ...initialRunState(), lastFull, result };
  const ui = { artifactSave: "" };
  const closed = [];
  return {
    closed,
    client: { dispatch: async () => ({ ok: true, value: {} }), invoke: async () => ({ ok: true, value: null }) },
    notify() {},
    subscribe: () => () => {},
    getRun: () => run,
    getUi: () => ui,
    closeArtifact() { closed.push("close"); },
    openArtifactFrom() {},
    saveArtifactAs: async () => {},
    selectFailed() {}, openRenameRules() {}, closeResult() {},
  };
}

test("보기 전용 마운트 인자 — readOnly 이고 편집 훅이 하나도 없다", () => {
  const closed = [];
  const errors = [];
  const spec = artifactViewerSpec(HOST, "QUJD", "공고서-001.hwpx",
    { onClose: () => closed.push(1), onError: (error) => errors.push(error) });
  assert.equal(spec.readOnly, true);
  assert.equal(spec.trackSelection, "never");
  assert.equal(spec.zoom, "fit");
  assert.equal(spec.host, HOST);
  assert.equal(spec.content, "QUJD");
  assert.equal(spec.fileName, "공고서-001.hwpx");
  assert.equal(spec.title, "공고서-001.hwpx");
  for (const hook of ["preflight", "onCompatibility", "onContextMenu", "onRangePick", "onSelectionRect"]) {
    assert.equal(spec[hook], undefined, `${hook} 가 실렸다`);
  }
  // 내보내기·선택 보고는 받아도 아무 일이 없다(저작 상태를 바꿀 길이 없다).
  assert.equal(spec.onChanged("ZZZ"), undefined);
  assert.equal(spec.onSelectionChanged({ entry: "x" }), undefined);
  // 셸 키는 Escape 만 닫기로 잇는다 — 저장·명령 팔레트·찾기·이름 바꾸기는 버린다.
  for (const key of ["CtrlS", "CtrlShiftP", "CtrlF", "F2", "F6", "ShiftF6"]) spec.onShortcut(key);
  assert.deepEqual(closed, []);
  spec.onShortcut("Escape");
  assert.deepEqual(closed, [1]);
  const failure = new Error("boom");
  spec.onError(failure);
  assert.deepEqual(errors, [failure]);
});

test("원료가 서면 그 bytes 그대로 보기 전용으로 마운트한다", async () => {
  const mounted = [];
  const handle = { dispose() {} };
  const { shown, handle: got } = await showArtifact({
    fetch: async () => ({ ok: true, ordinal: 0, filename: "공고서-001.hwpx", content: "UEsDBA==" }),
    mount: async (spec) => { mounted.push(spec); return handle; },
    host: HOST, filename: "공고서-001.hwpx", onClose() {}, onError() {},
  });
  assert.deepEqual(shown, { state: "rendered" });
  assert.equal(got, handle);
  assert.equal(mounted.length, 1);
  assert.equal(mounted[0].content, "UEsDBA==");
  assert.equal(mounted[0].readOnly, true);
});

test("원료 거절은 그 사유 그대로 거절 면이 되고 렌더러는 서지 않는다", async () => {
  let mounts = 0;
  const { shown, handle } = await showArtifact({
    fetch: async () => ({ ok: false, ordinal: 0, status: "ARTIFACT_DIGEST_MISMATCH", detail: "내용이 다르다" }),
    mount: async () => { mounts += 1; return { dispose() {} }; },
    host: HOST, filename: "a.hwpx", onClose() {}, onError() {},
  });
  assert.deepEqual(shown, { state: "failed", status: "ARTIFACT_DIGEST_MISMATCH", detail: "내용이 다르다" });
  assert.equal(handle, null);
  assert.equal(mounts, 0);
});

test("요청 실패·렌더러 실패도 거절 면이다 — 오류 문장이 사유가 된다", async () => {
  const broken = await showArtifact({
    fetch: async () => { throw new Error("job/artifact_content: 연결 끊김"); },
    mount: async () => { throw new Error("unreachable"); },
    host: HOST, filename: "a.hwpx", onClose() {}, onError() {},
  });
  assert.deepEqual(broken.shown, { state: "failed", status: ARTIFACT_RENDER_FAILED, detail: "job/artifact_content: 연결 끊김" });
  const unreadable = await showArtifact({
    fetch: async () => ({ ok: true, ordinal: 0, content: "bm90" }),
    mount: async () => { throw new Error("HWPX 파일을 열 수 없습니다"); },
    host: HOST, filename: "a.hwpx", onClose() {}, onError() {},
  });
  assert.equal(unreadable.shown.state, "failed");
  assert.equal(unreadable.shown.status, ARTIFACT_RENDER_FAILED);
  assert.match(unreadable.shown.detail, /열 수 없습니다/);
  assert.equal(unreadable.handle, null);
  assert.deepEqual(renderFailure("plain"), { state: "failed", status: ARTIFACT_RENDER_FAILED, detail: "plain" });
});

test("관찰이 선 면은 렌더러 자리만 세우고 텍스트 투영을 그리지 않는다", () => {
  const controller = fakeController({
    artifact_view: { open: true, ordinal: 0, filename: "공고서-001.hwpx", status: "observed", detail: "" },
  });
  const html = renderToStaticMarkup(createElement(JobArtifactSheet, { controller }));
  assert.match(html, /id="artifactDoc"/);
  assert.match(html, /data-state="loading"/);
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /산출물 관찰: 공고서-001\.hwpx/);
  assert.doesNotMatch(html, /artifact-para|artifact-table|artifactRefused|글꼴과 쪽 모양은 그리지 않습니다/);
  // 저장의 원료는 관찰한 bytes 다 — 관찰이 서 있으면 저장 단추가 산다.
  assert.doesNotMatch(html, /id="artifactSaveAs"[^>]*disabled/);
});

test("관찰이 서지 않은 면은 렌더러 없이 거절을 말하고 저장을 닫는다", () => {
  const controller = fakeController({
    artifact_view: {
      open: true, ordinal: 0, filename: "공고서-001.hwpx",
      status: "ARTIFACT_FILE_MISSING", detail: "경로에 파일이 없다",
    },
  });
  const html = renderToStaticMarkup(createElement(JobArtifactSheet, { controller }));
  assert.doesNotMatch(html, /id="artifactDoc"/);
  assert.match(html, /data-status="ARTIFACT_FILE_MISSING"/);
  assert.match(html, /문서 파일을 찾을 수 없습니다/);
  assert.match(html, /경로에 파일이 없다/);
  assert.match(html, /id="artifactSaveAs"[^>]*disabled/);
});

test("만든 문서 행 — 폴더에서 보기·내용 보기 두 아이콘이고 경로 복사가 없다", () => {
  const delivered = [{ ordinal: 3, filename: "공고서-003.hwpx", disposition: "WRITE_NEW", path: "D:\\out\\공고서-003.hwpx" }];
  const result = { status: "success", title: "완료", summary: "", out_dir: "D:\\out", delivered, failures: [] };
  const controller = fakeController({ job_name: "작업", last_run_job: "작업" }, result);
  const html = renderToStaticMarkup(createElement(JobResultZone, { controller }));
  const row = html.slice(html.indexOf('id="jobResultDoc-3"'));
  const rowEnd = row.indexOf('id="jobResultFails"');
  const rowHtml = row.slice(0, rowEnd < 0 ? undefined : rowEnd);
  assert.match(rowHtml, /data-track-act="reveal"/);
  assert.doesNotMatch(rowHtml, /data-track-act="copy"/);
  const open = rowHtml.match(/<button[^>]*data-act="artifact-open"[^>]*>([\s\S]*?)<\/button>/);
  assert.ok(open, "내용 보기 단추가 없다");
  assert.match(open[0], /class="btn sm icon track-btn"/);
  assert.match(open[0], /title="내용 보기"/);
  assert.match(open[0], /aria-label="&#x27;공고서-003\.hwpx&#x27; 내용 보기"/);
  // 보이는 글자 없이 아이콘만 선다(이름은 aria-label·title 이 싣는다).
  assert.match(open[1], /^<svg[^>]*aria-hidden="true"/);
  assert.equal(open[1].replace(/<[^>]+>/g, ""), "");
});
