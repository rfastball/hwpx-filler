/* N-08 클러스터 C — 「문서 만들기」(job) 프로브. 저장소에서 **가장 큰** 프로브 다섯의 이식본.
 *
 * 무엇을 옮겼나: `src/hwpxfiller/webapp/app.py` 의 상수 다섯과 그 열두 호출 자리.
 *   · `_JOB_DATA_FIRST_PROBE_JS`(944)          → job_data_first  (3877 + 지연 회수 3882·3888)
 *   · `_JOB_INHERITED_AFFORDANCE_PROBE_JS`(1572) → job_inherited (3895)
 *   · `_JOB_ACTIVE_CARD_PROBE_JS`(1636)        → job_active_card (3899 + 지연 회수 3900)
 *   · `_JOB_MIRROR_PROBE_JS`(1278)             → job_mirror      (3904 + stash 읽기 3907·3911·
 *                                                 3913·3915·3917·3919)
 *   · `_JOB_RESULT_PROBE_JS`(1755)             → job_result      (3922 + 지연 회수 3923)
 *   · (상수 없는 인라인 읽기)                   → job_density_narrow (3939, 앞뒤 호스트 resize
 *                                                 3937·3943)
 *
 * 무엇을 **안** 바꿨나: 프로브가 하는 일·순서·방출 필드·타이밍 의도. 값 모양은 기준 실행과
 * 같다 — `tests/test_web_selftest_gate.py` 의 열두 개 소비 테스트가 그 모양을 단언한다.
 *
 * 무엇을 바꿨나: **상태 인계 방식 하나뿐**. 레거시는 비동기 단계의 결과를 창 객체 위 `__*`
 * 자리에 쌓고 파이썬이 문자열 보간으로 만든 표현식으로 폴링해 회수했다(`_probe_late`,
 * app.py:3494). 이 클러스터의 스태시는 열둘이다 — 즐겨찾기 넷(`favSent`·`favChain`·`favDiag`·
 * `favDone`), 탐색 넷(`browsePickFocus`·`browseSheetClosed`·`browseCloseFocus`·`browseDone`),
 * 거울 여섯(`jobToggleValues`·`mirrorPreviewDispatch`·`mirrorPreviewFocus`·`mirrorClickSeen`·
 * `mirrorFocusTargetState`·`mirrorPushes`), 후보 둘(`candSent`·`candProbeDone`), 결과 여덟
 * (`jobResultSnap`·`rejectState`·`rejectText`·`rejectGen`·`rejectLog`·`rejectHidden`·
 * `rejectPushes`·`runlogLast`). 전부 지역 변수와 반환값이 됐다. 전역 쓰기 금지가 첫 이유고,
 * 두 번째가 더 무겁다 — 번들러가 모듈 스코프 이름을 바꾸면 문자열로 만든 전역 조회가
 * **조용히** 빗나가고, 선언은 살고 결과만 죽는다.
 *
 * 렌더 구동은 **주입된 `ctx.push`** 로만 한다. 이 클러스터에서 특히 중요한 이유: 거울·결과
 * 프로브는 비동기 창 동안 job 푸시를 **가로채 삼키고 무엇을 삼켰는지 증언한다**(조용한 격리
 * 금지). 가로채기는 `ctx.push` 자리를 갈아 끼워 구현하므로, 어딘가에서 값으로 잡아 둔 사본을
 * 쓰면 그 사본은 갈아 끼운 것을 못 본다 — 발신 0·푸시 0 이 조용히 보고된다. 그래서 규약은
 * **호출 시점에 주입 능력에서 다시 읽는 늦은 결속**이다. 이 파일 어디에도 주입 push 를 지역
 * 이름으로 미리 잡아 두고 구동에 쓰는 자리는 없다 — 원본 보관·복원용 두 자리만 예외이고,
 * 그 둘은 주석으로 표시해 두었다.
 *
 * 보존한 양성/음성 대조(하나도 잃지 않는다):
 *   · job_data_first : actionbar_plane ↔ actionbar_plane_empty_note(빈 문안 자리) ·
 *                      fav_pressed=["true","false"] · fav_order=[F,T,T,F,T,F] ·
 *                      gen_disabled · restate_hidden · folder_pick_disabled ·
 *                      cand_disabled_chips==0 · browse_query_kept↔browse_query_settled.
 *   · job_inherited  : no_data_exit_with_data(false) ↔ no_data_exit_shown(true).
 *   · job_active_card: conn_quiet_when_ok ↔ conn_text_no_data/relink_visible_no_data ·
 *                      warn_click_sends=="[]"(막힘) ↔ warn_redirect_modal(안내 다이얼로그) ·
 *                      cands_hidden_when_no_data. relink 는 `offsetParent` 로 **실제 가시성**을
 *                      본다 — hidden 을 지운 것과 그려진 것은 다른 사실이다.
 *   · job_mirror     : mirror_trigger_disabled(false) ↔ mirror_trigger_locked(true) ·
 *                      reapply_shown ↔ reapply_hidden · panel_hidden(hidden 이 flex 를 이긴다) ·
 *                      guard_body(재적용 있음) ↔ guard_body_minimal(없음) ·
 *                      exit_rejected/exit_running(빈 문자열) ↔ 채워진 퇴장 다섯 줄 ·
 *                      mirror_trigger_disabled_at_click(false) + mirror_click_seen(true)
 *                      — 비활성 요소의 `click()` 은 이벤트를 만들지 않으므로 「발신 0」을
 *                      배선 부재로 읽지 않기 위한 **부재판별력** 계기다 ·
 *                      mirror_focus_target_state=="ready" · job_grid_wide(2열).
 *   · job_result     : renamed_keeps_result ↔ switch_resets_result ↔ data_swap_resets_result ↔
 *                      selection_change_keeps_result(+demotes) · foreign_*_hidden ↔
 *                      renamed_*_shown · folder_hidden_while_running ↔ folder_shown_on_result ·
 *                      reject_state=="rejected" · close_focus ∈ {jobGenBtn, jobResultZone} ·
 *                      close_runlog_last 는 퇴장 한 줄의 **부재**를 단언한다.
 *                      하위 `artifact`(S7-03 · #825): 문서 목록 행이 그려지고(offsetParent) ·
 *                      「내용 보기」가 `job/artifact_open` 을 쏘고 `.artifact-sheet` 가
 *                      **보이며** · 관찰이 선 판은 문단·병합 표·빈 값 표식·「표시하지 못한
 *                      구간」을 함께 세우고 · 관찰이 서지 않은 두 상태(세션 밖 ↔ digest
 *                      불일치)가 **다른 문안**을 받으며 · 닫으면 초점이 그 행의 버튼으로
 *                      돌아온다. 새 프로브 키·새 창 0 — 이 창의 증거에 붙는다.
 *   · job_density_narrow : 1열 ↔ job_mirror.job_grid_wide 의 2열.
 *
 * 알고 옮긴 취약점(가리지 않는다): `_JOB_DATA_FIRST` 의 `.click()` 열 자리와 `_JOB_MIRROR` 의
 * 다섯 자리에는 `offsetParent` 가시성 단언이 없다 — `display:none` 요소를 눌러도 "성공"한다.
 * 감도를 바꾸지 않으려고 그대로 옮겼고, 자리 전수는 이 이식의 보고서에 열거돼 있다.
 *
 * 이 모듈은 **비활성(inert)** 이다. 제품 그래프가 import 하지 않고 전역을 하나도 쓰지 않으며,
 * import 만으로는 DOM 을 만지지도 리스너를 걸지도 않는다 — 전부 호출 시점에 일어난다.
 */

import { ERROR_CODES } from "../runner.js";

export const C_CLUSTER = "C";

/** 이 클러스터가 내는 키 전수. `keysForCluster("C")` 와 정확히 같아야 한다(테스트가 센다). */
export const C_KEYS = Object.freeze([
  "job_active_card", "job_data_first", "job_density_narrow",
  "job_inherited", "job_mirror", "job_result",
]);

/* ────────────────────────── 공용 조각 ────────────────────────── */

/** 레거시는 전역에서 `Nav`·`Bridge`·`Modal`·`Popover`·`JobScreen` 을 주웠다. 여기선 주입만
 *  쓰고, 없으면 **조용히 넘어가지 않는다** — 없는 서비스로 잰 값은 측정이 아니라 침묵이다. */
function requireServices(ctx, names) {
  const services = ctx.services || {};
  const missing = names.filter((name) => !services[name]);
  if (missing.length > 0) {
    ctx.fail(ERROR_CODES.CONTRACT, `주입되지 않은 서비스: ${missing.join(", ")}`);
  }
  return services;
}

/** 합성 snapshot으로 재는 프로브는 화면 전환이 자동으로 쏘는 실 refresh를 이미 대체한다.
 *  이를 명시하지 않으면 늦게 도착한 실 스냅샷이 React portal을 비운 뒤 합성 ID를 읽게 된다. */
function enterSyntheticJob(services, options = {}) {
  services.Nav.go("job", { ...options, refreshed: true });
}

/** 한 합성 snapshot 위에서 legacy remainder와 R4 React owner가 서로 다른 백엔드 세계를
 *  보지 않게 `Bridge.call`과 typed `Client.dispatch`를 한 수명으로 교체한다. make는 기존
 *  raw Bridge 계약을 유지하고 typed 쪽만 HostResult로 감싼다. */
function stubDispatch(services, make) {
  const Bridge = services.Bridge;
  const real = Bridge.call;
  const mine = make(real);
  Bridge.call = mine;
  const Client = services.Client;
  const realDispatch = Client && Client.dispatch;
  const typedMine = typeof realDispatch === "function"
    ? async function (screen, action, payload) {
      return { ok: true, value: await mine(screen, action, payload) };
    }
    : null;
  if (typedMine) Client.dispatch = typedMine;
  return {
    restore() {
      if (Bridge.call === mine) Bridge.call = real;
      if (typedMine && Client.dispatch === typedMine) Client.dispatch = realDispatch;
    },
  };
}

/** 실행 발신의 통로는 R4-03 에서 **옮겨 앉았다** — legacy remainder 의 raw `Bridge.generate`
 *  가 아니라 React owner 의 typed `Client.invoke("generate", …)` 다. 옛 자리를 갈아끼우면
 *  스텁이 **죽은 seam** 에 붙어 실 generate 가 그대로 돈다: 프로브는 거절 결과를 기다리는데
 *  호스트는 진짜 생성을 시도하고, 스텁 호출 수는 0 인 채 프로브가 null 을 읽는다.
 *  `stubDispatch` 와 같은 이유·같은 수명 규약으로 **산 자리**를 잡는다.
 *
 *  make 는 호스트 **payload** 를 낸다 — 봉투(`{ok, value}`)의 것이 아니다. 두 `ok` 는 다른
 *  층이라 겹쳐 읽으면 「Python 이 거절했다」와 「호출이 아예 성립하지 않았다」가 한 값으로
 *  접힌다: 봉투는 통로의 성패, payload 는 판정이다. */
function stubGenerate(services, make) {
  const Client = services.Client;
  const real = Client.invoke;
  const mine = async function (method, ...args) {
    if (method !== "generate") return real.call(Client, method, ...args);
    return { ok: true, value: make(args) };
  };
  Client.invoke = mine;
  return {
    restore() {
      if (Client.invoke === mine) Client.invoke = real;
    },
  };
}

/** id 로 글을 읽되 자리가 **없으면 이름을 말하고 죽는다**. 종전 이 자리들은
 *  `getElementById(id).textContent` 라서 실패가 "Cannot read properties of null" 한 줄이었다 —
 *  어느 자리가 아직 안 섰는지 말하지 못한다. React 이관처럼 「무엇이 사라졌나」가 곧 진단인
 *  국면에서 그 한 줄은 진단 비용을 전부 사람에게 떠넘긴다. */
function textOf(doc, id) {
  const el = doc.getElementById(id);
  if (el === null) throw new Error(`프로브가 읽을 자리가 DOM 에 없습니다: #${id}`);
  return el.textContent;
}

function displayOf(ctx, el) {
  return ctx.win.getComputedStyle(el).display;
}

function isShown(ctx, el) {
  return displayOf(ctx, el) !== "none";
}

function mapAll(nodes, fn) {
  return Array.prototype.map.call(nodes, fn);
}

/** 레거시가 `JSON.parse(JSON.stringify(snap))` 로 쓰던 깊은 사본 — 원판을 만지지 않는다. */
function deepCopy(value) {
  return JSON.parse(JSON.stringify(value));
}

/** React external-store 구독은 push와 같은 호출 스택에서 값을 받지만 concurrent root의 DOM
 *  커밋은 다음 turn에 끝날 수 있다. 고정 지연 없이 한 turn만 넘겨 현재 안정 ID를 읽는다. */
async function pushAndSettle(ctx, screen, snapshot) {
  ctx.push(screen, snapshot);
  await ctx.sleep(0);
}

/** concurrent root가 첫 portal 묶음을 나눠 커밋하고 앞선 실 push가 합성판을 덮을 수 있으므로,
 *  존재 계약이 설 때까지 합성판을 다시 밀며 0ms turn만 양보한다. 조건 충족 즉시 끝난다. */
async function pushUntil(ctx, screen, snapshot, ready, turns = 12) {
  for (let turn = 0; turn < turns; turn += 1) {
    ctx.push(screen, snapshot);
    await ctx.sleep(0);
    if (ready()) return true;
  }
  return !!ready();
}

function activeId(doc) {
  return doc.activeElement && doc.activeElement.id;
}

/** 컨트롤러 명령(renderResult·markResultStale 등) 뒤의 커밋 turn. push 와 같은 이유이고
 *  같은 비용이다 — 이 층은 명령을 동기로 받고 DOM 은 다음 turn 에 세운다. */
async function settle(ctx) {
  await ctx.sleep(0);
}

/* ────────────────────────── 합성 스냅샷 ────────────────────────── */

/* 스냅샷은 매 실행마다 새로 짓는다. 프로브가 자기 판을 **제자리에서 변조**하며 진행하기
   때문이다(거울의 `preview.can_open`·`drift`·`name_tokens`·`filter.reapply_available`).
   모듈 상수로 얼려 두면 두 번째 실행이 첫 실행의 마지막 상태에서 시작한다. */

/** app.py:951-997 그대로 — 작업 미선택 + 데이터 마운트(데이터-우선 §18.2). */
function dataFirstSnapshot() {
  return {
    job_name: "", has_job: false,
    out_dir: "", data_label: "d.csv", data_source_label: "파일: d.csv", data_notice: null,
    template_name: "", template_path: "", filename_pattern: "", template_missing: false,
    has_data: true, record_count: 2, selected_count: 1,
    records: [{ index: 1, selected: true, name: "", summary: "사무비품" },
      { index: 0, selected: false, name: "", summary: "전산장비" }],
    candidates: {
      top: [{
        name: "공고서", tier: "favorite", favorited: true,
        last_run_at: "2026-07-20T09:00:00", suggested: false,
        mode: "hwpx_generate", mode_label: "HWPX 생성",
        template_name: "공고서.hwpx", template_path: "C:\\t\\공고서.hwpx",
        template_missing: false, conn_label: "",
      }, {
        name: "계약서", tier: "unused", favorited: false,
        last_run_at: "", suggested: true,
        mode: "text_review_copy", mode_label: "온나라 기안",
        template_name: "계약서.txt", template_path: "C:\\t\\계약서.txt",
        template_missing: false, conn_label: "",
      }],
      sections: [{ mode: "hwpx_generate", mode_label: "HWPX 문서 생성", names: ["공고서"] },
        { mode: "text_review_copy", mode_label: "온나라 기안 검토·복사", names: ["계약서"] }],
      more: 2, needs_count: 1,
      suggested: "계약서",
    },
    browse: {
      tab: "needs_action", query: "견적",
      rows: [{ name: "견적서", missing: ["담당자"], mode: "hwpx_generate", mode_label: "HWPX 생성" }],
      sections: [{ mode: "hwpx_generate", mode_label: "HWPX 문서 생성", names: ["견적서"] }],
      available_count: 7, needs_count: 1, filtered_out: 2,
    },
    filter: {
      active: false, reapply_available: false, reapply_hint: "", search: "", chips: [],
      definition: "", branches: [],
      columns: [{ name: "공고명", kind: "text", active: false }],
    },
    table: {
      columns: [{ name: "공고명", kind: "text" }],
      rows: [{ index: 1, selected: true, name: "", summary: "사무비품", cells: [[["사무비품", false]]] },
        { index: 0, selected: false, name: "", summary: "전산장비", cells: [[["전산장비", false]]] }],
      visible_count: 2, hidden_selected: [],
    },
    restate: { origin: "manual", filter_active: false, in_def: 0, extra: 0, sample: [1] },
    preflight: { level: "", text: "" }, blank_fields: [], drift: [], name_tokens: [],
    gate: { enabled: false, level: "warn", text: "문서 작업을 선택하세요." },
  };
}

/** app.py:1283-1314 그대로 — 필터가 선 세션(가시 1행 + 필터 밖 선택 1행). */
function mirrorSnapshot() {
  return {
    job_name: "공고서", has_job: true,
    out_dir: "C:\\Results", data_label: "d.csv", data_source_label: "d.csv (파일)", data_notice: null,
    template_name: "t.hwpx", template_path: "C:\\t.hwpx", template_missing: false,
    filename_pattern: "doc-{{seq}}", has_data: true, record_count: 2, selected_count: 2,
    records: [{ index: 0, selected: true, name: "doc-001.hwpx", summary: "전산장비" },
      { index: 1, selected: true, name: "doc-002.hwpx", summary: "사무비품" }],
    filter: {
      active: true, reapply_available: true, reapply_hint: "(공고명) 포함 「전산」",
      search: "전산",
      chips: ["(공고명) 포함 「전산」"],
      definition: "(공고명) 포함 「전산」", branches: ["공고명"],
      columns: [{ name: "공고명", kind: "text", active: false },
        { name: "금액", kind: "amount", active: false }],
    },
    table: {
      columns: [{ name: "공고명", kind: "text" }, { name: "금액", kind: "amount" }],
      rows: [{
        index: 0, selected: true, name: "doc-001.hwpx", summary: "전산장비",
        cells: [[["전산", true], ["장비", false]], [["1,000,000원", false]]],
      }],
      visible_count: 1,
      hidden_selected: [{ index: 1, selected: true, name: "doc-002.hwpx", summary: "사무비품" }],
    },
    restate: { origin: "manual", filter_active: true, in_def: 1, extra: 1, sample: [0] },
    preflight: { level: "ok", text: "ok" },
    blank_fields: ["낙찰율"],
    preview: {
      open: false, pos: 0, total: 2, can_open: true,
      blank_only: false, blank_count: 1, can_prev: false, can_next: true,
    },
    drift: [], gate: { enabled: true, level: "", text: "생성 준비" },
  };
}

/** app.py:1577-1594 그대로 — 좌 목록 사망이 넘긴 두 의무의 승계 판. */
function inheritedSnapshot() {
  return {
    job_name: "", has_job: false, out_dir: "", data_label: "d.csv",
    data_source_label: "파일: d.csv", data_notice: null,
    template_name: "", template_path: "", filename_pattern: "", template_missing: false,
    has_data: true, record_count: 1, selected_count: 1,
    records: [{ index: 0, selected: true, name: "", summary: "사무비품" }],
    candidates: {
      top: [{ name: "공고서", favorited: false, suggested: false, last_run_at: "" }],
      more: 0, needs_count: 0, suggested: "",
    },
    browse: { tab: "available", query: "", rows: [], available_count: 1, needs_count: 0, filtered_out: 0 },
    guard: { armed: false, sel_count: 1, in_def: 0, extra: 0, filter_active: false, filter_parts: 0 },
    table: {
      columns: [{ name: "공고명", kind: "text" }],
      rows: [{ index: 0, selected: true, name: "", summary: "사무비품", cells: [[["사무비품", false]]] }],
      visible_count: 1, hidden_selected: [],
    },
    restate: { origin: "manual", filter_active: false, in_def: 0, extra: 0, sample: [0] },
    preflight: { level: "", text: "" }, blank_fields: [], drift: [], name_tokens: [],
    gate: { enabled: false, level: "warn", text: "문서 작업을 선택하세요." },
  };
}

/** app.py:1641-1673 그대로 — 활성 카드 하나 + 템플릿 부재 경고 카드 하나. */
function activeCardSnapshot() {
  return {
    job_name: "공고서", has_job: true, out_dir: "C:\\Results", data_label: "d.csv",
    data_source_label: "파일: d.csv", data_notice: null,
    template_name: "공고서.hwpx", template_path: "C:\\t\\공고서.hwpx",
    template_missing: false, filename_pattern: "doc-{{seq:001}}",
    has_data: true, record_count: 1, selected_count: 1,
    records: [{ index: 0, selected: true, name: "doc-001.hwpx", summary: "사무비품" }],
    candidates: {
      top: [{
        name: "공고서", tier: "recent", favorited: false,
        last_run_at: "2026-07-20T09:00:00", suggested: false,
        mode: "hwpx_generate", mode_label: "HWPX 생성",
        template_name: "공고서.hwpx", template_path: "C:\\t\\공고서.hwpx",
        template_missing: false, conn_label: "",
      }, {
        name: "계약서", tier: "unused", favorited: false,
        last_run_at: "", suggested: false,
        mode: "hwpx_generate", mode_label: "HWPX 생성",
        template_name: "계약서.hwpx", template_path: "C:\\t\\계약서.hwpx",
        template_missing: true, conn_label: "템플릿 없음",
      }],
      sections: [], more: 0, needs_count: 0, suggested: "", txt_note: "",
    },
    browse: { tab: "available", query: "", rows: [], available_count: 2, needs_count: 0, filtered_out: 0 },
    filter: {
      active: false, reapply_available: false, reapply_hint: "", search: "", chips: [],
      definition: "", branches: [], columns: [{ name: "공고명", kind: "text", active: false }],
    },
    table: {
      columns: [{ name: "공고명", kind: "text" }],
      rows: [{ index: 0, selected: true, name: "doc-001.hwpx", summary: "사무비품", cells: [[["사무비품", false]]] }],
      visible_count: 1, hidden_selected: [],
    },
    restate: { origin: "manual", filter_active: false, in_def: 0, extra: 0, sample: [0] },
    preflight: { level: "ok", text: "ok" }, mirror: [], drift: [], name_tokens: [],
    gate: { enabled: true, level: "", text: "생성 준비" },
  };
}

/** app.py:1761-1776 그대로 — 결과의 주체와 같은 작업('공고서')에서 출발한다(2R P2 비교군). */
function resultSnapshot() {
  return {
    job_name: "공고서", last_run_job: "공고서", has_job: true, out_dir: "D:\\out", data_label: "d.csv",
    data_mount: 1,
    data_source_label: "파일: d.csv", data_notice: null,
    template_name: "t.hwpx", template_path: "D:\\t.hwpx", filename_pattern: "doc-{{seq:001}}",
    template_missing: false, has_data: true, record_count: 1, selected_count: 1,
    records: [{ index: 0, selected: true, name: "", summary: "사무비품" }],
    candidates: { top: [], more: 0, needs_count: 0, suggested: "" },
    browse: { tab: "available", query: "", rows: [], available_count: 0, needs_count: 0, filtered_out: 0 },
    guard: { armed: false, sel_count: 1, in_def: 0, extra: 0, filter_active: false, filter_parts: 0 },
    table: { columns: [], rows: [], visible_count: 0, hidden_selected: [] },
    restate: { origin: "manual", filter_active: false, in_def: 0, extra: 0, sample: [0] },
    preflight: { level: "", text: "" }, blank_fields: [], drift: [], name_tokens: [],
    gate: { enabled: false, level: "warn", text: "확인이 필요합니다." },
  };
}

/** app.py:1778-1789 — 부분 실패 결과 payload. 여러 자리에서 같은 값으로 재렌더된다. */
function partialResult() {
  return {
    ok: true, status: "partiallyCompleted", title: "2개 성공 · 1개 실패",
    exit_summary: "2개 성공 · 1개 실패",
    summary: "완료. 성공 2/3, 실패 1.", level: "danger", stage: "", message: "", known: true,
    out_dir: "D:\\out", succeeded: 2, failed: 1, failed_selectable: 1, total: 3,
    failures: [{ index: 7, identity: "사무비품", filename: "doc-003.hwpx", reason: "설명 없는 오류", known: false }],
    fill_notes: ["누름틀 값 자리를 새로 만들어 채웠습니다."],
    cancelled: false, attempted: 3, unstarted: 0,
  };
}

/* ────────────────────── job_data_first — 측정 조각 ────────────────────── */

/** app.py:1005-1015. 액션바에서 **눈에 보이는 마지막 것**과 좌 열 오른쪽 끝(구분선)의 차. */
function measureActionbarPlane(ctx) {
  const doc = ctx.doc;
  const side = doc.querySelector("#jobZones .data-grid > .dg-side");
  const row = doc.querySelector("#jobActionBar .actionbar-row");
  if (!side || !row) return null;
  const visible = Array.prototype.filter.call(
    row.children, (c) => c.getBoundingClientRect().width > 0,
  );
  if (!visible.length) return null;
  return Math.round(
    visible[visible.length - 1].getBoundingClientRect().right - side.getBoundingClientRect().left,
  );
}

/** app.py:1018-1034. 같은 측정을 **문안이 빈** 상태에서 한 번 더 — 폭 0 인 flex 항목이
 *  앞의 gap 을 살려 마지막 버튼만 물러서는 자리를 잰다. 문안은 재고 되돌린다. */
function measureActionbarPlaneWithEmptyNote(ctx) {
  const doc = ctx.doc;
  const note = doc.getElementById("jobGate");
  const side = doc.querySelector("#jobZones .data-grid > .dg-side");
  const row = doc.querySelector("#jobActionBar .actionbar-row");
  if (!note || !side || !row) return null;
  const saved = note.textContent;
  note.textContent = "";
  const visible = Array.prototype.filter.call(
    row.children, (c) => c.getBoundingClientRect().width > 0,
  );
  const gap = visible.length
    ? Math.round(
      visible[visible.length - 1].getBoundingClientRect().right - side.getBoundingClientRect().left,
    )
    : null;
  note.textContent = saved;
  return gap;
}

/** app.py:1038-1045. 레거시는 이 블록을 1046-1056 에 **한 번 더 복사해 두었다**(같은 코드가
 *  같은 필드를 덮어쓴다). 산출이 동일하므로 여기서는 한 번만 잰다 — 필드 순서도 그대로다. */
function measureCapActions(ctx) {
  const doc = ctx.doc;
  const cap = doc.querySelector("#jobZones .zone-cap.zone-cap-actions");
  const btn = cap && cap.querySelector("button");
  if (!cap || !btn) return null;
  return {
    display: ctx.win.getComputedStyle(cap).display,
    far_edge: Math.round(cap.getBoundingClientRect().right - btn.getBoundingClientRect().right),
  };
}

/** 레거시가 `_probe_late`(app.py:3888)로 회수하던 탐색 3필드의 모양. `String`·`!!` 변환까지
 *  같게 둔다 — 파이썬 회수 표현식이 그 변환을 하고 있었고, 소비 테스트가 그 문자열을 본다. */
function browseLateFields(pickFocus, sheetClosed, closeFocus) {
  return {
    browse_pick_focus: String(pickFocus),
    browse_sheet_closed: !!sheetClosed,
    browse_close_focus: String(closeFocus),
  };
}

/** app.py:1069-1146 — 문서 탐색 면을 실클릭으로 열고 탭·행·사유·검색 고지를 되읽은 뒤,
 *  ① 고르고 닫음 ② 그냥 닫음(취소) 두 사유의 포커스 착지를 차례로 잰다.
 *
 *  착지는 **닫힘 전이 종료 뒤**에 확정된다 — 즉시 읽으면 늘 직전 포커스가 보여 프로브가
 *  거짓 통과한다(관측자 오염). 그래서 450·60·450ms 대기를 그대로 유지한다.
 *
 *  동기 구간(면 열기·검색어 경합·탭 포커스)은 첫 await 앞에 있으므로 레거시와 같은 turn 에
 *  끝난다. 반환 promise 는 호출부가 나중에 await 한다(레거시는 파이썬이 flag 를 폴링했다). */
async function driveBrowseSheet(ctx, out, snap, setupReady = () => {}) {
  const doc = ctx.doc;
  const services = ctx.services;

  const exit = doc.querySelector("#jobCandidates [data-browse-open]");
  if (!exit) {
    out.browse_open = "no-exit";
    setupReady();
    /* 레거시는 여기서 IIFE 를 빠져나가 완료 flag 를 세우지 않는다 — 파이썬 폴링이 2.5초를
       채우고 **정의되지 않은 스태시**를 읽어 간다. 그 산출을 그대로 낸다. */
    return browseLateFields(undefined, undefined, undefined);
  }
  exit.click();                                     // ※ 가시성 단언 없음(레거시 그대로)
  const sheet = doc.getElementById("jobBrowseSheet");
  out.browse_open = !sheet.classList.contains("hidden");
  out.browse_tabs = mapAll(
    sheet.querySelectorAll("[data-browse-tab]"),
    (b) => b.textContent + "/" + b.getAttribute("aria-selected"),
  );
  out.browse_rows = mapAll(
    sheet.querySelectorAll(".browse-row"),
    (r) => r.textContent.replace(/\s+/g, " ").trim(),
  );
  out.browse_note = doc.getElementById("jobBrowseNote").textContent;
  out.browse_focus_is_query = doc.activeElement === doc.getElementById("jobBrowseQuery");

  /* 왕복 중 이어 친 검색어가 옛 스냅샷에 덮이지 않는가(리뷰 4R P2): 포커스를 둔 채 새 글자를
     넣고 **옛 검색어를 담은** 스냅샷을 밀어도 입력값이 살아야 하고, 포커스가 떠난 뒤엔 서버
     값으로 확정돼야 한다. 두 극을 한 쌍으로 잰다. */
  const qi = doc.getElementById("jobBrowseQuery");
  qi.focus();
  qi.value = "견적요청";
  await pushAndSettle(ctx, "job", snap);
  out.browse_query_kept = qi.value;
  out.browse_query_node_stable = qi === doc.getElementById("jobBrowseQuery");
  out.browse_query_node_connected = qi.isConnected;
  out.browse_query_focus_stable = doc.activeElement === qi;
  /* 모달 focus trap은 body로 빠진 `.blur()`를 첫 입력으로 되돌린다. "포커스가 떠남"을
     실제로 만들기 위해 같은 모달의 탭으로 옮긴다 — trap을 깨는 것이 이 대조의 목적이 아니다. */
  doc.getElementById("jobBrowseTab-available").focus();
  out.browse_query_focus_left = doc.activeElement !== qi;
  await pushAndSettle(ctx, "job", snap);
  out.browse_query_settled = qi.value;

  /* 탭 전환 재렌더에서 키보드 포커스가 살아남는가(리뷰 1R P2 — 안정 id + preserve). */
  const tabA = doc.getElementById("jobBrowseTab-available");
  if (tabA) {
    tabA.focus();
    await pushAndSettle(ctx, "job", snap);
    out.browse_tab_focus = activeId(doc);
  }
  /* 여기까지가 레거시의 동기 구간이다. R4 DOM 커밋을 기다리는 0ms turn 동안 뒤 즐겨찾기
     프로브가 포커스를 뺏지 않도록 부모에게 이 구간의 확정을 알린다. */
  setupReady();

  /* 사용 가능 행을 고르면 **성사 뒤에** 면이 닫히고 포커스가 그 시점의 실 DOM 에 선다.
     스텁은 select_job 만 가로채고 스냅샷을 밀지 않는다 — 프로덕션에선 push·render 가
     resolve 보다 먼저 끝나므로, 여기서 스냅샷을 밀면 그 순서를 가려 버린다(3R P2). */
  const avail = deepCopy(snap);
  avail.browse = {
    tab: "available", query: "", rows: [{ name: "공고서", missing: [] }],
    available_count: 7, needs_count: 1, filtered_out: 0,
  };
  await pushAndSettle(ctx, "job", avail);
  const row = doc.getElementById("jobBrowseRow-" + encodeURIComponent("공고서"));
  if (!row) return browseLateFields("no-row", undefined, undefined);

  const dispatchStub = stubDispatch(services, (real) => function (screen, action) {
    if (action !== "select_job") return real.apply(null, arguments);
    return Promise.resolve({});
  });
  row.click();                                      // ※ 가시성 단언 없음(레거시 그대로)

  await ctx.sleep(450);
  dispatchStub.restore();
  const cls = doc.getElementById("jobBrowseSheet").classList;
  const sheetClosed = cls.contains("is-closing") || cls.contains("hidden");
  const pickFocus = activeId(doc);
  await pushAndSettle(ctx, "job", snap);            // 원판 복구(뒤 프로브 방해 금지)
  doc.querySelector("#jobCandidates [data-browse-open]").click();   // ※ 가시성 단언 없음
  await ctx.sleep(60);
  doc.getElementById("jobBrowseClose").click();      // ※ 가시성 단언 없음(그냥 닫기)
  await ctx.sleep(450);
  return browseLateFields(pickFocus, sheetClosed, activeId(doc));
}

/** app.py:1183-1246 — 즐겨찾기 쓰기 계약 2건(직렬화·정리 식별)을 실 DOM·실 핸들러로 잰다.
 *
 *  브리지를 **한 건씩 우리가 풀어 주는** 스텁으로 갈아 큐 상태를 관측한다. 단계 전이는
 *  `sleep(0)` — 각 단계 사이에 이벤트 루프가 돌아 체인이 실제로 진행된다(레거시의
 *  `setTimeout(…, 0)` 사슬과 같은 의도). 노드 참조를 들고 있지 않는다: 뒤따르는 재푸시가
 *  DOM 을 교체하므로 매 단계에서 **이름으로 다시 찾는다**(떼어진 노드 클릭은 조용한 무동작). */
async function driveFavoriteIntents(ctx, out, snap) {
  const doc = ctx.doc;
  const services = ctx.services;
  const starOf = (name) => doc.getElementById("jobFav-" + encodeURIComponent(name));

  if (!starOf("공고서") || !starOf("계약서")) {
    out.fav_intents = "no-stars";
    /* 레거시는 여기서 IIFE 를 빠져나가고 세 스태시가 모두 미정의로 남는다. 파이썬 회수
       표현식의 `String(undefined)` · `JSON.stringify(undefined || null)` 산출 그대로. */
    return {
      fav_chain: String(undefined),
      fav_order: JSON.stringify(null),
      fav_diag: JSON.stringify(null),
    };
  }

  const sent = [];
  const release = [];
  const dispatchStub = stubDispatch(services, (real) => function (screen, action, payload) {
    if (action !== "toggle_favorite") return real.apply(null, arguments);
    sent.push(payload.value);
    return new Promise((res) => { release.push(res); });
  });
  let favChain = null;
  const drain = (res) => { const r = release.shift(); if (r) r(res); };
  /* 레일 진입이 유발한 **실 refresh** 스냅샷이 뒤늦게 도착해 합성 화면을 덮는다(실 홈엔
     데이터가 없어 후보 줄이 비워진다). 클릭 단계마다 합성 스냅샷을 다시 밀어 카드를
     되살린다 — 표시는 여전히 낡은 상태이므로 DOM-대-미결 의도 시나리오는 그대로 성립한다. */
  const repush = () => pushAndSettle(ctx, "job", snap);

  starOf("공고서").click();                          // ※ 가시성 단언 없음(레거시 그대로)
  starOf("공고서").click();                          // ※ 가시성 단언 없음(레거시 그대로)
  out.fav_sync_sends = sent.length;   // 0 — 클릭은 체인 진입이고 즉시 발신하지 않는다
  out.fav_intents = JSON.stringify(sent);

  const steps = [
    // ① 직렬화: 앞 왕복이 끝나기 전엔 둘째를 보내지 않는다(발신 1건).
    () => { favChain = JSON.stringify({ inflight: sent.length }); drain({ ok: true }); },
    () => { drain({ ok: true }); },                  // 첫 카드 큐 소진
    // ② 정리 식별: 같은 값이 다시 큐에 드는 3연속(true→false→true) 뒤,
    //    **첫 왕복만** 실패로 완료시키고 4번째 클릭의 의도를 관측한다.
    async () => {
      await repush();
      starOf("계약서").click(); starOf("계약서").click(); starOf("계약서").click();
    },
    () => { drain({ ok: false, error: "실패 시늉" }); },
    async () => { await repush(); starOf("계약서").click(); },
    // 남은 큐를 전부 흘려 보내 최종 발신열을 확정한다(각 단계 = 이벤트 루프 1회전).
    () => { drain({ ok: false, error: "실패 시늉" }); },
    () => { drain({ ok: false, error: "실패 시늉" }); },
    () => { drain({ ok: false, error: "실패 시늉" }); },
    () => { dispatchStub.restore(); },
  ];

  const diag = [];
  for (let i = 0; i < steps.length; i += 1) {
    await ctx.sleep(0);
    try {
      await steps[i]();
      diag.push("ok" + i);
    } catch (thrown) {
      diag.push("err" + i + ":" + (thrown && thrown.message) + " ids="
        + mapAll(doc.querySelectorAll("#jobCandidates [data-fav]"), (b) => b.id).join("|")
        + " html=" + doc.getElementById("jobCandidates").innerHTML.slice(0, 80));
    }
  }
  return {
    fav_chain: String(favChain),
    fav_order: JSON.stringify(sent),
    fav_diag: JSON.stringify(diag),
  };
}

/* ────────────────────────── 프로브 본체 ────────────────────────── */

/** app.py:944-1276 + 3877·3882·3888. */
async function runJobDataFirst(ctx) {
  const services = requireServices(ctx, ["Nav", "Bridge"]);
  const doc = ctx.doc;
  const out = {};

  enterSyntheticJob(services);
  const snap = dataFirstSnapshot();
  await pushUntil(ctx, "job", snap, () => (
    doc.querySelectorAll("#jobCandidates [data-cand]").length === snap.candidates.top.length
  ));

  out.zones_shown = isShown(ctx, doc.getElementById("jobZones"));
  out.actionbar_plane = measureActionbarPlane(ctx);
  out.actionbar_plane_empty_note = measureActionbarPlaneWithEmptyNote(ctx);
  out.cap_actions = measureCapActions(ctx);
  out.actionbar_shown = isShown(ctx, doc.getElementById("jobActionBar"));
  out.cands_row_shown = isShown(ctx, doc.getElementById("jobCandsRow"));
  out.cand_buttons = doc.querySelectorAll("#jobCandidates [data-cand]").length;
  out.cand_exit = !!doc.querySelector("#jobCandidates [data-browse-open]");
  out.cand_more_text = (() => {
    const m = doc.querySelector("#jobCandidates .cand-more");
    return m ? m.textContent.replace(/\s+/g, " ").trim() : "";
  })();
  out.cand_disabled_chips = doc.querySelectorAll("#jobCandidates button[disabled]").length;

  /* 탐색 면 — 동기 구간은 지금 끝나고, 착지 사슬은 뒤에서 await 한다. */
  let browseSetupReady;
  const browseSetup = new Promise((resolve) => { browseSetupReady = resolve; });
  const browseChain = driveBrowseSheet(ctx, out, snap, browseSetupReady);
  browseChain.catch(() => {});   // 둘이 함께 거절해도 미처리 거절로 프로세스를 죽이지 않는다
  await browseSetup;

  out.cand_order = mapAll(
    doc.querySelectorAll("#jobCandidates [data-cand]"), (b) => b.getAttribute("data-cand"),
  );
  out.fav_pressed = mapAll(
    doc.querySelectorAll("#jobCandidates [data-fav]"), (b) => b.getAttribute("aria-pressed"),
  );
  out.suggested_marks = doc.querySelectorAll("#jobCandidates .cand-sug").length;
  out.cand_sec_caps = mapAll(
    doc.querySelectorAll("#jobCandidates .cand-sec-cap"), (h) => h.textContent,
  );
  out.cand_mode_texts = mapAll(
    doc.querySelectorAll("#jobCandidates .cand-mode"), (m) => m.textContent,
  );
  out.suggested_dashed = (() => {
    const card = doc.querySelector("#jobCandidates .job-cand-card.suggested");
    return card ? ctx.win.getComputedStyle(card).borderStyle : "";
  })();
  out.more_text = (() => {
    const m = doc.querySelector("#jobCandidates .cand-more");
    return m ? m.textContent : "";
  })();
  const favChain = driveFavoriteIntents(ctx, out, snap);
  favChain.catch(() => {});      // 위와 같은 이유 — 실패는 아래 Promise.all 이 그대로 올린다

  out.gate_text = doc.getElementById("jobGate").textContent;
  out.gen_disabled = doc.getElementById("jobGenBtn").disabled;
  out.action_name_empty = doc.getElementById("jobActionName").textContent === "";
  out.tbl_rows_order = mapAll(
    doc.querySelectorAll("#jobTableBody tr[data-i]"), (r) => r.getAttribute("data-i"),
  );
  out.restate_hidden = displayOf(ctx, doc.getElementById("jobRestate")) === "none";
  out.folder_pick_disabled = doc.getElementById("jobBtnPickFolder").disabled;

  /* 회수 순서는 레거시 드라이버 그대로다 — 즐겨찾기(3882) 먼저, 탐색(3888) 다음. */
  const [favLate, browseLate] = await Promise.all([favChain, browseChain]);
  Object.assign(out, favLate);
  Object.assign(out, browseLate);

  /* 별 포커스가 재렌더(별을 누르면 카드가 1순위로 이동)를 가로질러 살아남는가 —
     이름 유래 안정 id 가 실제로 붙었는지 실물로 본다. 탐색과 즐겨찾기 사슬도 초점을
     의도적으로 움직이므로 둘을 회수한 뒤 재렌더만 단독으로 재야 서로의 착지를 오염시키지 않는다. */
  out.fav_focus_restored = await (async () => {
    const star = doc.getElementById("jobFav-" + encodeURIComponent("계약서"));
    if (!star) return "no-id";
    star.focus();
    const moved = deepCopy(snap);                  // 깊은 사본만 만진다(원판 불변)
    moved.candidates.top.reverse();
    moved.candidates.top[0].favorited = true;      // 즐겨찾기 지정 후 1순위로 이동한 판
    await pushAndSettle(ctx, "job", moved);
    const kept = doc.activeElement
      && doc.activeElement.id === "jobFav-" + encodeURIComponent("계약서");
    const restored = kept ? "kept" : String(activeId(doc));
    await pushAndSettle(ctx, "job", snap);         // 뒤 프로브를 위해 원판 복구
    return restored;
  })();

  ctx.state.favOrder = out.fav_order;
  ctx.state.browsePickFocus = out.browse_pick_focus;

  return { job_data_first: out };
}

/** app.py:1572-1626 + 3895. 고정 대기·폴링은 없다. R4 selectJob은 편집 정산을 먼저 await
 *  하므로 클릭 프레임 측정 뒤 마이크로태스크만 흘려 typed 발신이 스텁에 들어온 것을 확인한다. */
async function runJobInherited(ctx) {
  const services = requireServices(ctx, ["Nav", "Bridge"]);
  const doc = ctx.doc;
  const out = {};

  enterSyntheticJob(services);
  const snap = inheritedSnapshot();
  await pushAndSettle(ctx, "job", snap);

  /* ① 「여는 중」 지연 표지(#217 R1) — 좌 목록 행에 있던 계약을 후보 카드가 진다. 왕복을
     **우리가 풀 수 있는** 미결로 세워 클릭 프레임의 표지를 읽고 곧바로 풀어 준다. */
  const card = doc.getElementById("jobCand-" + encodeURIComponent("공고서"));
  if (!card) {
    out.opening_marker_immediate = "no-card";
  } else {
    let release;
    let entered = false;
    const dispatchStub = stubDispatch(services, () => function () {
      entered = true;
      return new Promise((res) => { release = res; });
    });
    card.click();
    /* 레거시는 클릭 안에서 곧바로 Bridge를 불렀다. R4는 flushPendingEdits()의 await 하나를
       지나 typed Client를 읽으므로 여기서 즉시 복원하면 합성 이름이 실 backend로 샌다.
       타이머를 늘리지 않고 마이크로태스크 두 번만 흘려 발신 진입을 확인한다. */
    for (let turn = 0; !entered && turn < 4; turn += 1) await Promise.resolve();
    await ctx.sleep(0);
    const liveCard = doc.getElementById("jobCand-" + encodeURIComponent("공고서"));
    out.opening_marker_immediate = !!liveCard
      && liveCard.textContent.indexOf("여는 중") >= 0;
    if (release) release({});
    await ctx.sleep(0);
    dispatchStub.restore();
    if (!entered) {
      ctx.fail(ERROR_CODES.CONTRACT, "job_inherited: 카드 선택 발신이 typed 스텁에 들어오지 않았습니다.");
    }
  }

  /* ② 흡수처 출구(판정 C) — 데이터가 있으면 숨고(소음 금지), 데이터·작업이 둘 다 없으면
     상주해 막다른 화면을 막는다. 두 극을 한 쌍으로 잰다. */
  out.no_data_exit_with_data = isShown(ctx, doc.getElementById("jobNoDataExit"));
  const empty = deepCopy(snap);
  empty.has_data = false; empty.record_count = 0; empty.records = [];
  empty.table = { columns: [], rows: [], visible_count: 0, hidden_selected: [] };
  empty.candidates = { top: [], more: 0, needs_count: 0, suggested: "" };
  await pushAndSettle(ctx, "job", empty);
  out.no_data_exit_shown = isShown(ctx, doc.getElementById("jobNoDataExit"));
  out.no_data_exit_target = !!doc.getElementById("jobPickInLibrary");

  return { job_inherited: out };
}

/** app.py:1636-1743 + 3899·3900. */
async function runJobActiveCard(ctx) {
  const services = requireServices(ctx, ["Nav", "Bridge"]);
  const doc = ctx.doc;
  const out = {};

  enterSyntheticJob(services);
  const snap = activeCardSnapshot();
  await pushAndSettle(ctx, "job", snap);

  // ① 액션바가 활성 작업 이름을 말한다(§4-A 상속 의무 — 상수 높이 층의 정체 표시).
  out.action_name = doc.getElementById("jobActionName").textContent;
  // ② 활성 카드 — 확장 부제(템플릿 파일명)와 ⋮ 는 활성 카드에만 선다(판정 B).
  const activeCard = doc.querySelector("#jobCandidates .job-cand-card.active");
  out.active_tpl = (() => {
    const t = activeCard && activeCard.querySelector(".cand-tpl");
    return t ? t.textContent : "";
  })();
  out.menu_btn_in_active = !!(activeCard && activeCard.querySelector("[data-cand-menu]"));
  out.menu_btn_count = doc.querySelectorAll("#jobCandidates [data-cand-menu]").length;
  // ⋮ 클릭 → React 카드 안의 두 항목이 그 템플릿 경로를 겨눈다(PathActions 위임).
  doc.getElementById("jobCandMenuBtn").click();
  await ctx.sleep(0);
  const menuSelector = "#jobCandidates .cand-inline-menu";
  const menu = doc.querySelector(menuSelector);
  out.menu_open = !!menu;
  out.menu_items = mapAll(
    menu ? menu.querySelectorAll("[data-track-act]") : [],
    (b) => b.getAttribute("data-track-act") + ":" + b.getAttribute("data-path") + ":" + b.textContent,
  );
  doc.getElementById("jobCandMenuBtn").click();    // 같은 소유자 토글로 닫아 뒤 프로브 오염 방지
  await ctx.sleep(0);
  out.menu_closed = !doc.querySelector(menuSelector);
  // ③ 경고 카드 — 「연결 상태」는 텍스트가 정본이다(색만으로 말하지 않는다).
  const warnCard = doc.querySelector("#jobCandidates .job-cand-card.warn");
  out.warn_conn = (() => {
    const c = warnCard && warnCard.querySelector(".cand-conn");
    return c ? c.textContent : "";
  })();
  /* ③-b **도달 보장 축**(3R 근본 조치) — 활성 작업의 템플릿이 부재면 후보 구획이 어떤
     상태든(여기선 데이터 미마운트라 구획이 통째로 숨는다) 액션바가 연결 상태와 재연결을
     세운다. 정상 상태에선 조용하다(거짓 경보 금지) — 그 침묵이 음성 극이다. */
  out.conn_quiet_when_ok = doc.getElementById("jobActionConn").hidden === true
    && doc.getElementById("jobActionRelink").hidden === true;
  {
    const gone = deepCopy(snap);
    gone.has_data = false; gone.record_count = 0; gone.records = [];
    gone.table = { columns: [], rows: [], visible_count: 0, hidden_selected: [] };
    gone.candidates = { top: [], sections: [], more: 0, needs_count: 0, suggested: "", txt_note: "" };
    gone.template_missing = true; gone.conn_label = "템플릿 없음";
    await pushAndSettle(ctx, "job", gone);
    out.cands_hidden_when_no_data = displayOf(ctx, doc.getElementById("jobCandsRow")) === "none";
    out.cand_cards_when_no_data = doc.querySelectorAll("#jobCandidates [data-cand]").length;
    const conn = doc.getElementById("jobActionConn");
    const relink = doc.getElementById("jobActionRelink");
    out.conn_text_no_data = conn.hidden ? "" : conn.textContent;
    /* 실제로 **눈에 보이는가** — hidden 을 지운 것과 렌더된 것은 다른 사실이다(프로브
       click 이 hidden 을 통과한다는 교훈의 같은 계열). */
    out.relink_visible_no_data = !relink.hidden && relink.offsetParent !== null;
    await pushAndSettle(ctx, "job", snap);          // 원판 복구(뒤 단계 오염 금지)
  }
  /* ④ 경고 카드 클릭 = 선택이 아니다(판정 D) — 안내 다이얼로그가 서고, 취소하면 아무
     발신도 없다. 발신열은 취소 정착(160ms) 뒤에 확정되므로 400ms 뒤에 회수한다. */
  const sent = [];
  const dispatchStub = stubDispatch(services, () => function (screen, action) {
    sent.push(action);
    return Promise.resolve({});
  });
  doc.getElementById("jobCand-" + encodeURIComponent("계약서")).click();
  await ctx.sleep(0);
  const cm = doc.getElementById("confirmModal");
  out.warn_redirect_modal = !!cm && !cm.classList.contains("hidden");
  out.warn_modal_body = doc.getElementById("confirmModalBody").textContent;
  doc.getElementById("confirmModalCancel").click();

  await ctx.sleep(400);
  dispatchStub.restore();
  /* 레거시는 `JSON.stringify(sent)` 를 스태시에 담고 파이썬이 `String(...)` 로 회수했다 —
     소비 테스트가 `json.loads` 로 다시 푼다. 문자열인 채로 낸다. */
  out.warn_click_sends = String(JSON.stringify(sent));
  ctx.state.warnClickSends = out.warn_click_sends;

  return { job_active_card: out };
}

/** app.py:1278-1565 + 3904·3907·3911·3913·3915·3917·3919. 이 클러스터에서 가장 큰 프로브. */
async function runJobMirror(ctx) {
  const services = requireServices(ctx, ["Nav", "Bridge", "Modal", "JobRun"]);
  const doc = ctx.doc;
  const win = ctx.win;
  const out = {};

  enterSyntheticJob(services);
  let snap = mirrorSnapshot();
  await pushAndSettle(ctx, "job", snap);

  /* 본문 존 = 표 없는 한 줄(U2 §2.13). 한 줄은 안정 DOM(#jobMirrorLine)이고 #jobMirror 는
     danger 배너 전용이다(#364) — 자리를 가르는 것이 트리거를 재렌더에서 지키는 기제다. */
  out.mirror_no_table = !doc.querySelector("#jobMirrorZone table");
  out.mirror_banner_empty = doc.getElementById("jobMirror").children.length === 0;
  out.mirror_line = (() => {
    const l = doc.getElementById("jobMirrorLine");
    return l && !l.hidden ? l.textContent : "";
  })();
  out.mirror_line_has_blank_flag = !!doc.querySelector("#jobMirrorLine .mir-blank-flag");
  out.mirror_preview_exit = !!doc.getElementById("jobMirrorPreviewOpen");
  /* 판별 계기(#364 재게이트) — 「트리거가 있는가 / 잠겨 있지 않은가」를 클릭 **전에** 따로
     센다: `click()` 은 비활성 요소에서 이벤트를 만들지 않아 조용한 무동작이 되고, 그러면
     발신열만 보고는 「배선이 없다」와 구별할 수 없다(계측의 부재판별력). */
  out.mirror_trigger_disabled = doc.getElementById("jobMirrorPreviewOpen").disabled;
  /* 음성 대조(두 값) — 가용성이 실제로 `can_open` 에 결속돼 있는가. 한 값만 재면
     「늘 열려 있는 버튼」도 초록이라 잠금 계약이 검사되지 않는다. */
  snap = deepCopy(snap);
  snap.preview.can_open = false;
  await pushAndSettle(ctx, "job", snap);
  out.mirror_trigger_locked = doc.getElementById("jobMirrorPreviewOpen").disabled;
  snap = deepCopy(snap);
  snap.preview.can_open = true;
  await pushAndSettle(ctx, "job", snap);

  out.restate_shown = isShown(ctx, doc.getElementById("jobRestate"));
  out.restate_no_namelist = !doc.querySelector("#jobRestate .namelist");

  /* 필터 표면 되읽기(블록 4) — 가시 행·하이라이트·칩·가지 ×·스트립·유래 수치·아이콘. */
  out.tbl_rows = doc.querySelectorAll("#jobTableBody tr[data-i]").length;
  const renderedRow = doc.querySelector("#jobTableBody tr[data-i]");
  const renderedAmount = doc.querySelector("#jobTableBody td.col-amount");
  out.row_role = renderedRow && renderedRow.getAttribute("role");
  out.row_selected = renderedRow && renderedRow.getAttribute("aria-selected");
  out.row_checkbox = !!doc.querySelector('#jobTableBody td.doccol input[type="checkbox"]');
  out.row_doccell_display = win.getComputedStyle(doc.querySelector("#jobTableBody .doccell")).display;
  out.lead_hint = doc.querySelector("#jobTableHead .col-hint").textContent;
  out.repeated_placeholder = doc.querySelectorAll('#jobTableBody .doc-off:not([aria-hidden="true"])').length;
  out.amount_align = win.getComputedStyle(renderedAmount).textAlign;
  out.amount_nums = win.getComputedStyle(renderedAmount).fontVariantNumeric;
  out.tbl_mark = (() => {
    const m = doc.querySelector("#jobTableBody mark");
    return m ? m.textContent : "";
  })();
  out.ficos = doc.querySelectorAll("#jobTableHead .fico[data-col]").length;
  out.chips_text = doc.getElementById("jobFilterChips").textContent;
  out.branch_prune = !!doc.querySelector('#jobFilterChips [data-prune="공고명"]');
  const definitionChip = doc.querySelector("#jobFilterChips .fchip.definition");
  const branchChip = doc.querySelector("#jobFilterChips .fchip.branch");
  out.filter_role_labels = Array.from(doc.querySelectorAll(".fchip .chip-role")).map(
    (e) => e.textContent,
  );
  out.definition_bg = win.getComputedStyle(definitionChip).backgroundColor;
  out.branch_bg = win.getComputedStyle(branchChip).backgroundColor;
  out.branch_border_style = win.getComputedStyle(branchChip).borderStyle;
  out.strip_shown = isShown(ctx, doc.getElementById("jobSelStrip"));
  out.strip_text = doc.getElementById("jobSelStrip").textContent;
  out.strip_bg = win.getComputedStyle(doc.getElementById("jobSelStrip")).backgroundColor;
  out.strip_unsel = !!doc.querySelector('#jobSelStrip [data-unsel="1"]');
  out.sel_line = doc.getElementById("jobRestate").textContent;

  /* 왕복을 일부러 미결로 둔 채 두 번 누른다. 둘째 값이 첫 낙관 표지를 기준으로 계산돼야
     true→false→true 가 되고, checkbox·aria-selected·행 tint 가 같은 프레임에 맞는다(#217 R2). */
  const toggleValues = [];
  const zoneStub = stubDispatch(services, (realCall) => function (screen, action, payload) {
    if (action === "toggle_record") {
      /* **해소되는** 스텁이다(리뷰 2R): 존 변이는 한 체인에 직렬화되므로 영원히 미결인 첫
         발신은 둘째를 영영 막는다. 재는 것은 "push 가 오기 전 재클릭이 화면의 현재 상태를
         쓰는가"이지 promise 가 매달리는가가 아니다. 둘째 값은 마이크로태스크 뒤에 실린다. */
      toggleValues.push(payload.value);
      return Promise.resolve({});
    }
    if (action === "filter_panel") return new Promise(function () {});
    return realCall.call(services.Bridge, screen, action, payload);
  });
  renderedRow.click();                              // ※ 가시성 단언 없음(레거시 그대로)
  await ctx.sleep(0);                              // React 낙관 상태 DOM 커밋
  out.row_optimistic_off = !renderedRow.classList.contains("on")
    && renderedRow.getAttribute("aria-selected") === "false"
    && !renderedRow.querySelector("input").checked;
  renderedRow.click();                              // ※ 가시성 단언 없음(레거시 그대로)
  await ctx.sleep(0);                              // 둘째 실시간 의도 DOM 커밋
  out.row_optimistic_on = renderedRow.classList.contains("on")
    && renderedRow.getAttribute("aria-selected") === "true"
    && renderedRow.querySelector("input").checked;
  out.row_toggle_values = toggleValues.slice();     // 즉시분(첫 발신) — 최종 확인은 아래 되읽기
  /* filter_panel 응답이 영원히 미결이어도 클릭 프레임에 제목 + 로딩 껍데기가 먼저 선다(#217 R4). */
  doc.querySelector("#jobTableHead .fico").click(); // ※ 가시성 단언 없음(레거시 그대로)
  await ctx.sleep(0);
  /* R4는 정적 #jobColPanel을 채우지 않고 현재 portal 안에 React 패널을 마운트한다. 같은
     노드 identity/hidden 속성이 아니라 현재 React 소유 표면의 존재와 제거를 잰다. */
  const panelSelector = "#jobTableHost .react-colpanel";
  const loadingPanel = doc.querySelector(panelSelector);
  out.panel_shell_immediate = !!loadingPanel
    && loadingPanel.getAttribute("aria-busy") === "true"
    && loadingPanel.textContent.indexOf("불러오는 중") >= 0
    && loadingPanel.textContent.indexOf("공고명") >= 0;
  const panelClose = loadingPanel && loadingPanel.querySelector('[data-act="panel-close"]');
  if (panelClose) panelClose.click();                 // ※ 가시성 단언 없음(레거시 그대로)
  await ctx.sleep(0);
  zoneStub.restore();
  /* 열 패널 기본 닫힘 — React owner에서는 hidden 토글이 아니라 조건부 언마운트가 계약이다. */
  out.panel_hidden = !doc.querySelector(panelSelector);

  /* 드리프트 스냅샷 → 본문 존 한 줄이 차단 배너 + 행동 링크로 교체되는지(overlay 가 아닌
     실제 교체). 실앱에서 드리프트는 게이트 danger 를 합성하므로 게이트도 danger 로 세운다. */
  snap = deepCopy(snap);
  snap.drift = ["유령", "계약조건"]; snap.blank_fields = [];
  snap.gate = { enabled: false, level: "danger", text: "템플릿 구조가 확정 매핑과 달라졌습니다." };
  await pushAndSettle(ctx, "job", snap);
  out.drift_banner = !!doc.querySelector('#jobMirror .mir-drift[role="alert"]');
  out.drift_fix_link = !!doc.querySelector('#jobMirror [data-act="fix-mapping"]');
  out.drift_no_line = !doc.querySelector("#jobMirror .mirline");
  out.restate_hidden_on_drift = displayOf(ctx, doc.getElementById("jobRestate")) === "none";

  /* 파일명 토큰 danger(#128) — 드리프트와 **같은 자리·같은 형상**으로 서는지. */
  snap = deepCopy(snap);
  snap.drift = []; snap.name_tokens = ["납품기한"];
  snap.blank_fields = [];
  snap.gate = { enabled: false, level: "danger", text: "파일명 패턴의 토큰이…" };
  await pushAndSettle(ctx, "job", snap);
  out.token_banner = !!doc.querySelector('#jobMirror .mir-drift[role="alert"]');
  out.token_fix_link = !!doc.querySelector('#jobMirror [data-act="fix-filename"]');
  out.token_no_line = !doc.querySelector("#jobMirror .mirline");
  out.token_banner_text = (() => {
    const b = doc.querySelector("#jobMirror .mir-drift");
    return b ? b.textContent : "";
  })();
  out.token_restate_hidden = displayOf(ctx, doc.getElementById("jobRestate")) === "none";
  /* 덮어쓰기 확인 본문 합성 되읽기 — overwrite_count/new_count 스왑·이름 목록 누락의 핀. */
  out.ow_body = services.JobRun.overwriteBody({
    total: 10, overwrite_count: 3, new_count: 7, conflict_names: ["a.hwpx", "b.hwpx"], conflict_more: 5,
  });
  /* 퇴장 한 줄(§2.18)의 네 태 산출 — 결과 구획이 초기화된 뒤 **유일하게 남는 흔적**이라
     거짓 진술이 여기서 조용히 배포되면 되돌아볼 자리가 없다(#363 리뷰 P2). */
  out.exit_cancelled_untouched = services.JobRun.resultExitLine(
    { exit_summary: "중단 · 0개 성공 · 미착수 12건", out_dir: "D:\\out" }, "발주요청서",
  );
  out.exit_cancelled_mixed = services.JobRun.resultExitLine(
    { exit_summary: "중단 · 5개 성공 · 1개 실패 · 미착수 6건", out_dir: "D:\\out" }, "발주요청서",
  );
  out.exit_prebatch_failed = services.JobRun.resultExitLine(
    { exit_summary: "생성 시작 전 실패 · 대상 12건", out_dir: "D:\\out" }, "발주요청서",
  );
  out.exit_completed = services.JobRun.resultExitLine(
    { exit_summary: "12개 성공", out_dir: "D:\\out" }, "발주요청서",
  );
  out.exit_partial_failure = services.JobRun.resultExitLine(
    { exit_summary: "10개 성공 · 2개 실패", out_dir: "D:\\out" }, "발주요청서",
  );
  /* 생성이 아닌 태는 적을 것이 없다 — 거절·진행에 퇴장 한 줄을 지어내지 않는다(음성 극). */
  out.exit_rejected = services.JobRun.resultExitLine(
    { rejected: true, title: "생성하지 않았습니다", summary: "빈 값" }, "발주요청서",
  );
  out.exit_running = services.JobRun.resultExitLine(
    { running: true, title: "생성 중… 1/3" }, "발주요청서",
  );
  /* 요약 없는 **실행 결과**는 조용히 넘기지 않는다 — 수치를 지어내지 않고 모른다고 적는가. */
  out.exit_missing_summary = services.JobRun.resultExitLine(
    { ok: true, status: "completed", title: "문서 생성 완료 · 3개", out_dir: "D:\\out" }, "발주요청서",
  );
  /* 세션 가드 재진술 본문 — 있는 손실만 열거한다(과경고는 경보의 인플레). 두 극을 함께 낸다. */
  out.guard_body = services.JobRun.guardBody(
    { sel_count: 3, in_def: 2, extra: 1, filter_active: true, filter_parts: 2 }, "데이터를 바꾸면",
  );
  out.guard_body_minimal = services.JobRun.guardBody(
    { sel_count: 1, in_def: 0, extra: 0, filter_active: false, filter_parts: 0 }, "데이터를 바꾸면",
  );
  out.data_guard_wired = typeof services.JobRun.confirmDestructiveIfArmed === "function";

  /* 직전 필터 재적용(결정 28) — 양 분기 모두 핀한다: 켜짐만 고정하면 "항상 떠 있는 죽은
     버튼" 회귀가 초록으로 샌다. */
  out.reapply_shown = isShown(ctx, doc.getElementById("jobFilterReapply"));
  out.reapply_title = doc.getElementById("jobFilterReapply").title;
  snap = deepCopy(snap);
  snap.filter.reapply_available = false;
  await pushAndSettle(ctx, "job", snap);
  out.reapply_hidden = displayOf(ctx, doc.getElementById("jobFilterReapply")) === "none";

  snap = deepCopy(snap);
  snap.filter.reapply_available = true;
  snap.drift = []; snap.name_tokens = [];
  snap.gate = { enabled: true, level: "", text: "생성 준비" };
  snap.blank_fields = ["필드0"];
  await pushAndSettle(ctx, "job", snap);

  /* CI 가상 데스크톱은 창 크기를 실제 화면 상한에서 클램프한다. 운영 CSS 를 바꾸지 않고
     컨테이너 자체를 900px 경계 너머로 고정해 wide 분기를 검증한 뒤 즉시 복원한다
     (실 협폭 분기는 job_density_narrow 가 실제 창으로 맡는다 — 두 극이 한 쌍이다). */
  const jobPanel = doc.getElementById("jobPanel");
  const jobPanelFlex = jobPanel.style.flex;
  const jobPanelWidth = jobPanel.style.width;
  jobPanel.style.flex = "0 0 1100px"; jobPanel.style.width = "1100px";
  out.job_grid_wide = win.getComputedStyle(doc.getElementById("jobDataGrid")).gridTemplateColumns;
  jobPanel.style.flex = jobPanelFlex; jobPanel.style.width = jobPanelWidth;

  /* 확인 면 출구는 비동기(정산 뒤 발신)라 발신은 이 turn 뒤에 확정된다. 레거시는 발신열을
     창 객체에 남기고 파이썬이 새 JS 턴으로 되읽었다 — 여기서는 그냥 await 한다. */
  const dispatched = [];
  const sheetStub = stubDispatch(services, () => function (screen, action) {
    dispatched.push({ screen, action });
    return Promise.resolve({});
  });
  /* 이 창도 실 push 에서 격리한다: 프로브 첫머리 `Nav.go('job')` 이 쏜 실 refresh 의 푸시
     (세션 없는 실 스냅샷)가 호스트 스레드에서 늦게 착지해 정확히 이 비동기 창에 들어온다.
     그러면 트리거가 `can_open:false` 로 잠기고, 닫힘 시점의 초점 복귀는 **비활성 트리거를
     건너뛰는 것이 계약**이라 초점이 화면 루트로 내려간다 — 실앱에선 옳은 처분이고 여기서는
     합성 세션 위에 실 빈 스냅샷이 끼어드는 프로브 산물이다. 삼킨 것은 기록해 증언한다
     (조용한 격리 금지).
     아래 한 줄이 이 파일의 유일한 push 선-포획이다 — **복원·전달 대상**을 잡는 자리이고,
     측정 구동은 전부 `ctx.push(...)` 호출 시점 조회로 남는다(늦은 결속). */
  const mirrorRealPush = ctx.push;
  const mirrorPushes = [];
  ctx.push = function (screen, pushed) {
    if (screen === "job") {
      mirrorPushes.push({ job: pushed && pushed.job_name, has_job: !!(pushed && pushed.has_job) });
      return undefined;
    }
    return mirrorRealPush(screen, pushed);
  };
  ctx.state.mirrorPushes = mirrorPushes;

  const mirrorTrigger = doc.getElementById("jobMirrorPreviewOpen");
  /* 클릭이 **이벤트까지 갔는가**를 따로 센다(부재판별력): 비활성 요소의 `click()` 은
     이벤트를 만들지 않으므로, 이것 없이는 「발신 0」이 배선 부재인지 잠금인지 모른다. */
  let clickSeen = false;
  mirrorTrigger.addEventListener("click", () => { clickSeen = true; });
  out.mirror_trigger_disabled_at_click = mirrorTrigger.disabled;
  mirrorTrigger.focus();
  mirrorTrigger.click();

  /* 정리는 **스텁이 산 채로** 한다(관측자 오염 리트머스): 닫힘이 발화하는 preview_close 가
     실 백엔드에 닿으면 세션 없는 실 스냅샷 푸시가 뒤 프로브(job_result)의 비동기 창에
     착지하고, §2.18 처분이 그 푸시를 「작업 없음 전환」으로 읽어 방금 세운 rejected 결과를
     초기화한다 — 프로브가 프로브를 오염시키는 자리다. 복원은 닫힘 정착 **뒤에** 한다. */
  const closing = (async () => {
    await ctx.sleep(30);
    services.Modal.close("previewSheet");
    const card = doc.querySelector("#previewSheet .modal-card");
    if (card) {
      const transitionEnd = new win.Event("transitionend", { bubbles: true });
      Object.defineProperty(transitionEnd, "propertyName", { value: "opacity" });
      card.dispatchEvent(transitionEnd);
    }
    // 닫은 뒤 초점이 **그 트리거**로 돌아오는가(#364 리뷰 P2).
    const previewFocus = activeId(doc);
    /* 측정 시점의 트리거 상태 — 초점이 안 돌아왔을 때 「복귀점이 틀렸다」와 「트리거가
       그사이 잠겼다(정상 경로)」를 가른다. */
    const focusTargetState = (() => {
      const b = doc.getElementById("jobMirrorPreviewOpen");
      if (!b) return "missing";
      return b.disabled ? "disabled" : (b.isConnected ? "ready" : "detached");
    })();
    ctx.push = mirrorRealPush;
    sheetStub.restore();
    return { previewFocus, focusTargetState };
  })();

  /* 편집기가 자기 화면으로 나가며(재작성 F7) 「편집 모드가 화면을 덮는다」는 계약 — 열린
     펼침 면의 일괄 회수는 화면 전환이 진다. 레거시와 같이 닫힘 대기 **앞에서** 동기로 돈다. */
  services.Nav.go("editor", { force: true });
  out.edit_closes_sheets = !doc.getElementById("scr-job").classList.contains("on")
    && doc.getElementById("scr-editor").classList.contains("on");
  enterSyntheticJob(services, { force: true });

  const closed = await closing;

  /* 지연 회수 여섯(app.py:3907·3911·3913·3915·3917·3919). `row_toggle_values` 는 **덮어쓰기**라
     필드 자리는 그대로 두고 값만 최종 의도열로 바뀐다. */
  out.row_toggle_values = toggleValues.slice();
  out.mirror_preview_dispatch = dispatched;
  out.mirror_preview_focus = String(closed.previewFocus);
  out.mirror_click_seen = !!clickSeen;
  out.mirror_focus_target_state = String(closed.focusTargetState);
  out.mirror_pushes = mirrorPushes;

  return { job_mirror: out };
}

/** app.py:1755-1947 + 3922·3923. */
async function runJobResult(ctx) {
  const services = requireServices(ctx, ["Nav", "Bridge", "JobRun", "Modal"]);
  const doc = ctx.doc;
  const out = {};

  enterSyntheticJob(services);
  const baseSnap = resultSnapshot();
  await pushAndSettle(ctx, "job", baseSnap);

  const partial = partialResult();
  services.JobRun.renderResult(partial);
  await settle(ctx);
  const box = doc.getElementById("jobResult");
  out.state = box.dataset.state;
  out.level = box.dataset.level;
  out.shown = !box.hidden;
  out.title = textOf(doc, "jobResultTitle");
  out.fail_row = !!doc.getElementById("jobResultFail-7");
  out.fail_identity = textOf(doc, "jobResultFails").indexOf("사무비품") >= 0;
  out.undiagnosed = textOf(doc, "jobResultFails").indexOf("원인 진단 미연결") >= 0;
  out.failed_sel_shown = !doc.getElementById("jobResultFailedSel").hidden;
  out.failed_sel_label = textOf(doc, "jobResultFailedSel");

  /* 증거는 접혀서 서고, 사용자가 연 뒤에는 재렌더(스냅샷 푸시)를 건너 열린 채 남는다. */
  const evidence = doc.getElementById("jobResultEvidence");
  out.evidence_shown = !evidence.hidden;
  evidence.open = true;
  services.JobRun.renderResult(partial);
  await settle(ctx);
  out.evidence_open_survives_rerender = doc.getElementById("jobResultEvidence").open;

  /* 배치 진입 전 실패(행 0개·전량 실패) — 복구 행동이 행 목록에서 파생되면 여기서 통째로
     사라진다(1R P2). 노출·라벨은 호스트 수치(failed_selectable)가 정한다.
     `out_dir` 리터럴은 레거시(app.py:1814)가 이스케이프 하나를 빠뜨려 실제 값이 `D:out` 인
     자리다. 아무 소비자도 읽지 않으므로 감도를 바꾸지 않게 **그대로** 옮긴다. */
  services.JobRun.renderResult({
    ok: true, status: "failed", title: "문서 생성 실패",
    summary: "문서를 만들지 못했습니다. 대상 3건이 모두 생성되지 않았습니다.",
    level: "danger", stage: "생성 시작 전", message: "[WinError 5] 액세스가 거부되었습니다",
    known: true, out_dir: "D:\out", succeeded: 0, failed: 3, failed_selectable: 3, total: 3,
    failures: [], fill_notes: [], cancelled: false, attempted: 0, unstarted: 3,
  });
  await settle(ctx);
  out.rowless_recovery_shown = !doc.getElementById("jobResultFailedSel").hidden;
  out.rowless_recovery_label = textOf(doc, "jobResultFailedSel");
  out.rowless_no_fake_rows = doc.getElementById("jobResultFails").children.length === 0;
  services.JobRun.renderResult(partial);
  await settle(ctx);

  /* 지문 변화 = 강등이지 파기가 아니다(판정 G) — 결과가 남고 「직전 실행」이 붙는다. */
  services.JobRun.markResultStale();
  await settle(ctx);
  out.stale_shown = !doc.getElementById("jobResultStale").hidden;
  out.alive_after_stale = !doc.getElementById("jobResult").hidden;

  /* ① 이름 변경(3R P2) — 같은 작업인데 정체 표기만 바뀐 경우. 주체가 그 전이를 따라오므로
     결과가 살고 행동이 그대로 남아야 한다. */
  const snapR = deepCopy(baseSnap);
  snapR.job_name = "공고서(수정)"; snapR.last_run_job = "공고서(수정)";
  await pushAndSettle(ctx, "job", snapR);
  services.JobRun.markResultStale();
  await settle(ctx);
  out.renamed_rename_shown = !doc.getElementById("jobResultRename").hidden;
  out.renamed_failedsel_shown = !doc.getElementById("jobResultFailedSel").hidden;
  out.renamed_keeps_result = !doc.getElementById("jobResult").hidden;

  /* ② 다른 작업으로 전환(§2.18) — 존이 닫히고 실행 기록에 퇴장 한 줄이 남는다. */
  const snapB = deepCopy(snapR);
  snapB.job_name = "둘째";
  await pushAndSettle(ctx, "job", snapB);
  out.switch_resets_result = doc.getElementById("jobResult").hidden;
  out.switch_exit_line = textOf(doc, "jobRunLogLast");

  /* 강등 렌더러의 주체 방어(3R P2) — 푸시를 거치지 않고 결과가 재수립되는 경로에서
     남의 작업을 겨누는 버튼이 서지 않는지 몸통을 직접 찌른다. 증거는 남는다. */
  services.JobRun.renderResult(partial);
  services.JobRun.markResultStale();
  await settle(ctx);
  out.foreign_rename_hidden = doc.getElementById("jobResultRename").hidden;
  out.foreign_failedsel_hidden = doc.getElementById("jobResultFailedSel").hidden;
  out.foreign_evidence_alive = !!doc.getElementById("jobResultFail-7");
  out.foreign_stale_names_owner = textOf(doc, "jobResultStale").indexOf("공고서") >= 0;

  /* ③ 선택 변경 = 강등 유지(§2.18) — 「실패한 N건만 선택」이 자기 결과를 없애면 안 된다. */
  await pushAndSettle(ctx, "job", baseSnap);        // 비교군 복귀(원 작업 문맥)
  services.JobRun.renderResult(partial);
  await settle(ctx);
  const snapSel = deepCopy(baseSnap);
  snapSel.selection_key = "0,1";
  await pushAndSettle(ctx, "job", snapSel);
  out.selection_change_keeps_result = !doc.getElementById("jobResult").hidden;
  out.selection_change_demotes = !doc.getElementById("jobResultStale").hidden;

  /* ④ 데이터 교체 = 초기화 + 퇴장 한 줄(경로 포함). 교체의 표지는 **마운트 세대**이지 표시
     라벨이 아니다(#363 리뷰 P2) — 라벨을 그대로 두고 세대만 올린다. */
  const snapData = deepCopy(snapSel);
  snapData.data_mount = 2;
  await pushAndSettle(ctx, "job", snapData);
  out.data_swap_resets_result = doc.getElementById("jobResult").hidden;
  out.data_swap_exit_line = textOf(doc, "jobRunLogLast");
  out.data_swap_label_unchanged = snapData.data_source_label === "파일: d.csv";
  await pushAndSettle(ctx, "job", baseSnap);        // 비교군 복귀(다음 단계는 같은 작업 문맥)
  services.JobRun.renderResult(partial);
  await settle(ctx);

  /* 구획 행동은 생성 중 잠긴다(계약면 2) — 선언 표식이 실제로 붙는가. */
  out.busy_lock_declared = ["jobResultClose", "jobResultFailedSel", "jobResultRename"].every(
    (id) => doc.getElementById(id).hasAttribute("data-busy-lock"),
  );
  /* 진행 태에서는 저장 폴더 줄이 숨는다 — display:flex 가 UA [hidden] 을 이기는 결함
     클래스라 계산 스타일로 확인한다(속성만 보면 통과해 버린다). 두 극을 한 쌍으로 잰다. */
  services.JobRun.renderResult({ running: true, title: "생성 중… 1/3", summary: "" });
  await settle(ctx);
  out.folder_hidden_while_running = displayOf(
    ctx, doc.querySelector("#jobResult .result3-folder"),
  ) === "none";
  services.JobRun.renderResult(partial);
  await settle(ctx);
  out.folder_shown_on_result = displayOf(
    ctx, doc.querySelector("#jobResult .result3-folder"),
  ) !== "none";

  /* ── 산출물 관찰(S7-03 · #825) — 결과 존 문서 목록 + 읽기 전용 시트 ─────────────
     새 프로브 키·새 클러스터·새 콜드 부팅을 늘리지 않는다: 이미 서 있는 이 창의
     `job_result` 증거에 하위 필드로 붙는다. 클릭 자리마다 `offsetParent` 를 함께 재는
     이유는 머리말이 못박은 함정 때문이다 — `click()` 은 hidden 요소도 통과하므로
     가시성을 따로 묻지 않으면 「눈으로 본 것」과 다른 결론이 나온다. */
  const artifact = {};
  const deliveredResult = {
    ...partial,
    delivered: [
      { ordinal: 0, filename: "공고서-001.hwpx", disposition: "WRITE_NEW",
        path: "D:\out\공고서-001.hwpx" },
      { ordinal: 1, filename: "공고서-002.hwpx", disposition: "WRITE_ADD_SUFFIX",
        path: "D:\out\공고서-002.hwpx" },
    ],
  };
  services.JobRun.renderResult(deliveredResult);
  await settle(ctx);
  const docsBox = doc.getElementById("jobResultDocs");
  artifact.docs_shown = !!docsBox && !docsBox.hidden && isShown(ctx, docsBox);
  artifact.docs_rows = docsBox === null ? -1 : docsBox.querySelectorAll(".result3-doc").length;
  const docRow = doc.getElementById("jobResultDoc-0");
  /* 행 하나가 **그려졌는가**(offsetParent) + 파일명·처분 라벨·경로 어포던스가 그 안에 있는가.
     처분 라벨은 확인 면과 같은 어휘 지도를 지난다 — 코드 원문이 새면 그 자리가 재조립이다. */
  artifact.doc_visible = !!docRow && docRow.offsetParent !== null;
  artifact.doc_text = docRow === null ? "(자리 없음)" : String(docRow.textContent || "");
  artifact.doc_track_acts = docRow === null ? [] : mapAll(
    docRow.querySelectorAll("[data-track-act]"), (button) => button.dataset.trackAct,
  );

  /* 열기 왕복은 스텁 안에서 돈다 — 실 백엔드에 닿으면 세션 없는 실 스냅샷이 이 창에
     착지해 §2.18 처분이 방금 세운 결과를 초기화한다(runJobMirror 가 같은 자리에서 배운 것). */
  const artifactDispatches = [];
  const artifactStub = stubDispatch(services, () => async (screen, action) => {
    artifactDispatches.push(`${screen}/${action}`);
    return {};
  });
  const openButton = docRow === null
    ? null : docRow.querySelector('[data-act="artifact-open"]');
  artifact.open_btn_visible = !!openButton && openButton.offsetParent !== null;
  if (openButton) openButton.focus();
  if (openButton) openButton.click();
  await ctx.sleep(30);
  artifact.open_dispatches = artifactDispatches.slice();
  const sheetCard = doc.querySelector("#artifactSheet .artifact-sheet");
  /* 면이 **그려졌는가** — 계산 스타일과 offsetParent 를 함께 본다(hidden 이 flex 를 이기는
     결함 클래스와 「눌렸지만 안 보인다」 결함 클래스가 각각 다른 계기에 걸린다). */
  artifact.sheet_shown = !!sheetCard && isShown(ctx, sheetCard) && sheetCard.offsetParent !== null;
  /* ④ 백엔드에 그 문서가 없는 상태 — 조용한 빈 화면이 아니라 **구분된 거절 문안**이다. */
  artifact.absent_status = String(
    (doc.getElementById("artifactRefused") || {}).dataset?.status ?? "(자리 없음)",
  );
  artifact.absent_title = String(
    (doc.getElementById("artifactRefusedTitle") || {}).textContent ?? "(자리 없음)",
  );
  artifact.absent_save_disabled = !!(doc.getElementById("artifactSaveAs") || {}).disabled;

  /* 관찰이 선 상태의 상 — 구조·빈 값 표식·「표시하지 못한 구간」이 한 판에 선다.
     값은 전부 Python 이 낸 스냅샷 형상 그대로다(표면이 재조립하지 않는다). */
  const observedSnap = deepCopy(baseSnap);
  observedSnap.artifact_view = {
    open: true, ordinal: 0, filename: "공고서-001.hwpx", status: "observed", detail: "",
    structure: {
      kind: "artifact-observation/v1",
      sections: [{ blocks: [
        { type: "paragraph", text: "계약 상대자 귀하", fields: [] },
        { type: "table", rows: [[
          { blocks: [{ type: "paragraph", text: "항목", fields: [] }],
            span: { colSpan: 2, rowSpan: 1 }, addr: { colAddr: 0, rowAddr: 0 } },
        ]] },
      ] }],
      headers: [], footers: [],
      unrendered_regions: { counts: { mystery: 2 }, examples: { mystery: "sec/mystery" } },
      partial_coverage: true,
      coverage_code: "ARTIFACT_PARTIAL_COVERAGE",
      missing_value_markers: [{ field: "추정가격", count: 1 }],
    },
  };
  await pushAndSettle(ctx, "job", observedSnap);
  artifact.observed_paragraph = mapAll(
    doc.querySelectorAll("#artifactSheet .artifact-para"), (node) => node.textContent,
  );
  const mergedCell = doc.querySelector("#artifactSheet .artifact-table td");
  artifact.observed_colspan = mergedCell === null ? -1 : Number(mergedCell.colSpan);
  artifact.observed_markers = String(
    (doc.getElementById("artifactMarkerList") || {}).textContent ?? "(자리 없음)",
  );
  const unrendered = doc.getElementById("artifactUnrendered");
  artifact.unrendered_partial = String(unrendered?.dataset?.partial ?? "(자리 없음)");
  artifact.unrendered_shown = !!unrendered && unrendered.offsetParent !== null;
  artifact.unrendered_text = String(
    (doc.getElementById("artifactUnrenderedList") || {}).textContent ?? "(자리 없음)",
  );
  artifact.observed_save_enabled = !(doc.getElementById("artifactSaveAs") || {}).disabled;

  /* 무결성 실패는 「준비 안 됨」과 다른 문장을 받는다(#820 §3, fallback 0). */
  const mismatchSnap = deepCopy(observedSnap);
  mismatchSnap.artifact_view = {
    open: true, ordinal: 0, filename: "공고서-001.hwpx",
    status: "ARTIFACT_DIGEST_MISMATCH", detail: "내용이 안착 기록과 다르다", structure: null,
  };
  await pushAndSettle(ctx, "job", mismatchSnap);
  artifact.mismatch_title = String(
    (doc.getElementById("artifactRefusedTitle") || {}).textContent ?? "(자리 없음)",
  );
  artifact.mismatch_detail = String(
    (doc.getElementById("artifactRefusedDetail") || {}).textContent ?? "(자리 없음)",
  );
  artifact.mismatch_differs_from_absent = artifact.mismatch_title !== artifact.absent_title;

  /* 닫기 — runJobMirror 관용구 그대로(transitionend 수동 발화 + 복귀 초점 판별). */
  services.Modal.close("artifactSheet");
  const closingCard = doc.querySelector("#artifactSheet .modal-card");
  if (closingCard) {
    const transitionEnd = new ctx.win.Event("transitionend", { bubbles: true });
    Object.defineProperty(transitionEnd, "propertyName", { value: "opacity" });
    closingCard.dispatchEvent(transitionEnd);
  }
  await ctx.sleep(30);
  artifact.close_dispatches = artifactDispatches.slice();
  artifact.close_focus = String(activeId(doc));
  artifact.close_focus_target_state = (() => {
    const row = doc.getElementById("jobResultDoc-0");
    const button = row && row.querySelector('[data-act="artifact-open"]');
    if (!button) return "missing";
    return button.disabled ? "disabled" : (button.isConnected ? "ready" : "detached");
  })();
  /* 「닫혔다」 = **안 보인다** 이지 DOM 에서 사라졌다가 아니다 — portal 내용은 그대로
     마운트돼 있고 골격이 `hidden` 을 받는다. 둘을 함께 재 어느 층이 안 닫혔는지 가른다. */
  const closedSheet = doc.querySelector("#artifactSheet .artifact-sheet");
  artifact.sheet_closed = !closedSheet || closedSheet.offsetParent === null;
  artifact.sheet_host_hidden = !!doc.getElementById("artifactSheet")
    ?.classList.contains("hidden");
  artifactStub.restore();
  out.artifact = artifact;

  /* 비교군 복귀 — 뒤 단계(닫기·거절 창)는 delivered 없는 결과 위에서 돈다. */
  await pushAndSettle(ctx, "job", baseSnap);
  services.JobRun.renderResult(partial);
  await settle(ctx);

  /* 닫기 = 유일한 명시 파기 + 포커스는 다음 행동으로 착지(계약면 3). */
  doc.getElementById("jobResultClose").click();
  await settle(ctx);
  out.closed = doc.getElementById("jobResult").hidden;
  out.close_focus = activeId(doc);
  /* 명시 파기는 퇴장 한 줄을 남기지 않는다(§2.18 파기 대칭) — 실행 기록이 기본 문안으로
     돌아왔는지 되읽는다. 이 필드는 **부재**를 단언하는 자리다(자동 초기화만 흔적을 남긴다). */
  out.close_runlog_last = textOf(doc, "jobRunLogLast");
  out.runlog_collapsed = !doc.getElementById("jobRunLog").open;
  out.runlog_last_visible = isShown(ctx, doc.getElementById("jobRunLogLast"));

  /* 실행 전 거절은 3태가 아니라 rejected 태로 선다 — 결과 자리를 비워 두지 않는다.
     누를 수 있는 상태는 **스냅샷으로** 만든다(세션 성분은 그대로라 강등·초기화가 아니다).
     종전 이 자리는 DOM 프로퍼티를 직접 뒤집었다 — legacy 는 노드에 리스너를 달았으니 그것으로
     충분했지만 React 는 `onClick` 을 부르기 전 **자기 props 의 `disabled`** 를 본다
     (`shouldPreventMouseEvent`). 프로퍼티만 뒤집으면 핸들러가 영영 안 불리고, 그 침묵은
     「거절이 안 그려졌다」와 똑같이 생겼다. 계측이 모델을 우회하면 그 계측은 아무것도 안 잰다. */
  const genSnap = deepCopy(baseSnap);
  genSnap.gate = { enabled: true, level: "", text: "" };
  await pushAndSettle(ctx, "job", genSnap);

  let rejectGenCalls = 0;
  const genStub = stubGenerate(services, (args) => {
    rejectGenCalls += 1;
    /* 문안은 살아 있는 blank_set 게이트 문형(U2 §2.13) — 죽은 ack 문형을 프로브가
       정본처럼 실으면 다음 사람이 그 메시지가 산다고 읽는다. */
    return {
      ok: false, error: "빈 값 필드가 표식으로 문서에 박힙니다: 추정가격.", level: "warn",
      /* 상관 토큰은 **반향**이다(R4-03) — 컨트롤러는 이것이 없으면 거절을 그리기 전에
         계약 위반으로 멈춘다. 대역이 자기 토큰을 지어내면 그 관문을 우회해, 귀속이 깨진
         응답도 통과하는 세계에서 재게 된다. 받은 것을 그대로 돌려준다. */
      run_token: args[2],
    };
  });
  /* 거절 창 격리(관측자 오염 리트머스) — 첫머리 `Nav.go('job')` 이 쏜 실 refresh 의 푸시가
     늦게 착지해 정확히 이 비동기 창에 들어오고, §2.18 처분이 그것을 「작업 없음 전환 =
     초기화」로 정확히 읽어 방금 세운 rejected 를 지운다. 창이 열린 동안 job 푸시는 기록만
     하고 흘려보내지 않는다 — 무엇을 삼켰는지는 reject_pushes 가 증언한다. */
  const realPush = ctx.push;                        // 복원·전달 대상(이 파일 두 번째이자 마지막)
  const rejectPushes = [];
  ctx.push = function (screen, pushed) {
    if (screen === "job") {
      rejectPushes.push({
        job: pushed && pushed.job_name, has_job: !!(pushed && pushed.has_job),
        data: pushed && pushed.data_source_label, progress: !!(pushed && pushed.progress),
      });
      return undefined;
    }
    return realPush(screen, pushed);
  };
  ctx.state.rejectPushes = rejectPushes;
  /* 「발신 전 정지」는 갈래가 하나가 아니다 — 핸들러가 안 걸린 것 / 걸렸는데 첫 await 에서
     던진 것이 같은 침묵을 낸다. 클릭 자리가 `void controller.startGenerate()` 라 후자의
     거절은 아무 데도 안 남으므로, 이 창에서만 그 소음을 받아 증거로 싣는다. */
  const rejectUnhandled = [];
  const onUnhandled = (event) => {
    const reason = event && event.reason;
    rejectUnhandled.push(String((reason && reason.message) || reason));
  };
  ctx.win.addEventListener("unhandledrejection", onUnhandled);
  /* 발신 앞에는 **커밋 관문**이 하나 더 있다(`flushPendingEdits`). 그 관문이 호스트를
     부르면 이 합성 창에서 영영 안 돌아올 수 있고, 그때 침묵은 「핸들러 미배선」과
     구별되지 않는다. 창을 닫아 두고 무엇을 요청했는지 이름으로 남긴다. */
  const rejectDispatches = [];
  const dispatchStub = stubDispatch(services, () => async (screen, action) => {
    rejectDispatches.push(`${screen}/${action}`);
    return {};
  });
  const genBtn = doc.getElementById("jobGenBtn");
  // React 가 **스스로** 연 상태여야 한다 — 여기가 참이면 이후 단언 전체가 공허하다.
  const rejectBtnDisabled = genBtn.disabled;
  genBtn.click();

  await ctx.sleep(60);
  ctx.win.removeEventListener("unhandledrejection", onUnhandled);
  dispatchStub.restore();
  out.reject_btn_disabled = !!rejectBtnDisabled;
  out.reject_unhandled = rejectUnhandled;
  out.reject_dispatches = rejectDispatches;
  // 잠금 전이가 섰는가 = `beginRun` 까지 갔는가. 라벨은 그 전이의 가시면이다.
  out.reject_btn_label = String(genBtn.textContent || "");
  out.reject_run_action = String((baseSnap.run_action && baseSnap.run_action.key) || "");
  const resultBox = doc.getElementById("jobResult");
  /* 판별 증거 — 스텁 호출 수·로그 원문·구획 은닉이 「발신 전 정지 / 발신 후 렌더 /
     렌더 후 소거」 세 갈래를 가른다. 그래서 **이 자리의 읽기만은 던지지 않는다**: 자리가
     없다는 사실 자체가 세 갈래 중 하나를 가리키는 증거인데, 던지면 그 증거가 통째로
     사라지고 "null 을 읽었다" 한 줄만 남는다 — 그 한 줄은 세 갈래를 구별하지 못한다.
     대신 표식을 실어 게이트가 시끄럽게 떨어지게 한다(조용한 통과가 아니다). */
  const ABSENT = "(자리 없음)";
  const textOrAbsent = (id) => {
    const el = doc.getElementById(id);
    return el === null ? ABSENT : el.textContent;
  };
  const rejectState = resultBox === null ? ABSENT : resultBox.dataset.state;
  const rejectText = textOrAbsent("jobResultSummary");
  const rejectLog = textOrAbsent("jobGenLog");
  const rejectHidden = resultBox === null ? true : resultBox.hidden;
  // 거절 사유는 로그도 탄다 — 접힌 요약 줄이 그 사실을 실제로 나르는가.
  const runlogLast = textOrAbsent("jobRunLogLast");
  ctx.push = realPush;
  genStub.restore();

  out.reject_state = String(rejectState);
  out.reject_text = String(rejectText);
  out.reject_gen = Number(rejectGenCalls);
  out.reject_log = String(rejectLog);
  out.reject_hidden = !!rejectHidden;
  out.reject_pushes = rejectPushes;
  out.runlog_last = String(runlogLast);

  return { job_result: out };
}

/** app.py:3939 — 협폭 적층 분기는 **창폭이 아니라 세션 패널 폭**(container query 900px)이
 *  판정한다. 앞뒤 resize 는 호스트 소유라 여기서 직접 하지 않는다. */
function runJobDensityNarrow(ctx) {
  const doc = ctx.doc;
  return {
    job_density_narrow: {
      columns: ctx.win.getComputedStyle(doc.getElementById("jobDataGrid")).gridTemplateColumns,
      panel: Math.round(doc.getElementById("jobPanel").getBoundingClientRect().width),
    },
  };
}

/* ────────────────────────── 프로브 정의 ────────────────────────── */

/** 클러스터 C 의 프로브 전수를 **정의 데이터**로 낸다. 부작용 없음 — 이 함수를 부르는 것만
 *  으로는 DOM 을 만지지도, 리스너를 걸지도, 전역을 쓰지도 않는다. */
export function createJobProbes() {
  return [
    /* ── job_data_first (app.py:3877 · 지연 회수 3882·3888) ── */
    {
      name: "job_data_first",
      keys: ["job_data_first"],
      cluster: C_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3877,
      deadlineMs: 5000,
      deadlineRationale:
        "레거시 예산 = `_probe_late` 두 번(app.py:3882 즐겨찾기 · 3888 탐색 착지), 각 50×50ms"
        + " = 2500ms 를 **차례로** 쓴다. 5000 은 그 합 그대로이고 늘어난 것이 없다."
        + " 동기 측정에는 레거시에도 시한이 없었다.",
      note:
        "이 프로브의 `.click()` 열 자리에는 offsetParent 가시성 단언이 없다 —"
        + " display:none 요소를 눌러도 '성공'한다. 감도를 바꾸지 않으려고 그대로 옮겼다.",
      run: runJobDataFirst,
    },

    /* ── job_inherited (app.py:3895) ── */
    {
      name: "job_inherited",
      keys: ["job_inherited"],
      cluster: C_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3895,
      deadlineMs: 0,
      deadlineRationale:
        "동기 측정뿐 — 레거시에도 폴링도 sleep 도 없다(app.py:3895 는 단발 evaluate).",
      after: ["job_data_first"],
      afterReason:
        "후보 카드 클릭은 전환 재진입 가드를 잡으므로, job_data_first 의 탐색 착지"
        + "(setTimeout 연속)가 아직 풀리는 중이면 그 선택이 조용히 거절된다 — 프로브가"
        + " 프로브를 오염시키는 자리라 레거시도 착지 완료를 확인한 뒤에 돌린다(app.py:1567-1571).",
      run: runJobInherited,
    },

    /* ── job_active_card (app.py:3899 · 지연 회수 3900) ── */
    {
      name: "job_active_card",
      keys: ["job_active_card"],
      cluster: C_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3899,
      deadlineMs: 2500,
      deadlineRationale:
        "레거시 예산 = `_probe_late` 한 번(app.py:3900) = 50×50ms = 2500ms."
        + " 안쪽 확인 취소 정착 400ms 가 그 안에 든다.",
      after: ["job_data_first"],
      afterReason:
        "이 프로브는 **자기 합성 스냅샷을 민다**. job_data_first 의 비동기 사슬(즐겨찾기"
        + " 큐·탐색 착지)이 아직 돌고 있으면 그 사슬이 원판을 되밀어 이 프로브의 판을 덮는다"
        + " — app.py:3897-3898 이 명시한 교차오염 차단 순서 그대로다.",
      run: runJobActiveCard,
    },

    /* ── job_mirror (app.py:3904 + stash 읽기 여섯) ── */
    {
      name: "job_mirror",
      keys: ["job_mirror"],
      cluster: C_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3904,
      deadlineMs: 2500,
      deadlineRationale:
        "이 프로브는 `_probe_late` 를 쓰지 않는다 — 여섯 stash 는 폴링 없는 단발 evaluate 고,"
        + " 레거시가 비동기 확정에 준 예산은 app.py:3910 의 0.2초 sleep 하나뿐이다."
        + " 그런데 200ms 를 그대로 쓰던 종전 값은 **레거시보다 넓은 일**을 덮고 있었다:"
        + " 시한이 아예 없던 동기 구간(277줄, `getComputedStyle` 다수로 강제 레이아웃을"
        + " 여러 번 유발한다)까지 그 안에 들어왔기 때문이다. 종전 근거문이 그 사실을 스스로"
        + " 적어 두고도(\"예산은 줄었지 늘지 않았다\") 값은 그대로였고, 느린 러너에서 실제로"
        + " 터졌다(#429 — CI 2회, 그때마다 이 프로브의 키를 읽는 10여 테스트가 함께 무너졌다)."
        + " 2500ms 는 같은 클러스터에서 비슷한 동기 읽기를 하는 job_result·job_grid_wide 와"
        + " 같은 값이다 — 이 프로브만 두 자릿수 작을 이유가 없다.",
      after: ["job_data_first"],
      afterReason:
        "job_data_first 가 **먼저** 돌아야 한다(app.py:3872-3876): 그 프로브는 빈 경로"
        + " 스냅샷을 남기므로, 순서가 뒤집히면 경로 어포던스를 읽는 뒤 프로브들이 거울의"
        + " 경로 있는 스냅샷을 복원받는다 — #137 프로브 교차오염 교훈이 온 자리다.",
      note:
        "이 프로브의 `.click()` 다섯 자리에도 offsetParent 가시성 단언이 없다."
        + " job_grid_wide(2열)는 job_density_narrow(1열)의 양성 극이다.",
      run: runJobMirror,
    },

    /* ── job_result (app.py:3922 · 지연 회수 3923) ── */
    {
      name: "job_result",
      keys: ["job_result"],
      cluster: C_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3922,
      deadlineMs: 2500,
      deadlineRationale:
        "레거시 예산 = `_probe_late` 한 번(app.py:3923) = 50×50ms = 2500ms."
        + " 안쪽 거절 창 60ms 가 그 안에 든다.",
      after: ["job_mirror"],
      afterReason:
        "app.py:3921 — 결과 3태는 **거울 프로브 바로 뒤**, 같은 화면·같은 스냅샷 문맥에서"
        + " 돈다. 사이에 다른 프로브가 들어와 화면을 옮기거나 스냅샷을 갈면 결과 구획이"
        + " 서는 전제 자체가 달라진다.",
      run: runJobResult,
    },

    /* ── job_density_narrow (app.py:3937-3944) — 앞뒤 호스트 resize 로 감싸인 읽기 ── */
    {
      name: "job_density_narrow",
      keys: ["job_density_narrow"],
      cluster: C_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3939,
      deadlineMs: 0,
      deadlineRationale:
        "측정은 동기 computed style·레이아웃 박스 읽기 — 레거시에도 폴링이 없다"
        + "(대기는 앞뒤 settle 이 진다).",
      requiresHost: ["window_resize"],
      hostSetup: { op: "window_resize", payload: { width: 900, height: 820 } },
      settleBeforeMs: 400,
      settleReason:
        "app.py:3938 의 0.4초 — resize 는 OS 이벤트라 relayout 이 즉시 끝나지 않는다."
        + " 이 대기를 지우면 container query 분기를 밟기 전에 재게 된다.",
      cooldownAfterMs: 400,
      cooldownReason:
        "app.py:3944 의 0.4초 — teardown 이 요청한 복귀 resize(1440,900)의 relayout 안정."
        + " 이 대기 없이 다음 프로브가 재면 좁은 폭에서 잰 값이 기본 폭 값으로 읽힌다.",
      after: ["job_result"],
      afterReason:
        "레거시는 이 읽기를 job_result 의 지연 회수(app.py:3923-3932)가 **끝난 뒤**에 둔다"
        + " — 호스트 resize(900,820)가 그 회수 창에 끼면 앞 프로브가 측정 도중 relayout 을"
        + " 맞는다. 또 이 1열 값은 job_mirror.job_grid_wide 의 2열과 짝인 음성 극이라,"
        + " 넓은 판정이 먼저 서야 대조가 성립한다.",
      note:
        "협폭 분기는 창폭이 아니라 **세션 패널 폭**(container query 900px)이 판정한다"
        + "(app.py:3933-3936) — 그래서 panel 실측을 함께 낸다.",
      run: runJobDensityNarrow,
      /* 복귀 resize 는 호스트 소유다 — 프로브가 직접 창을 만지지 않는다. 측정이 실패해도
         돌아가야 하므로 teardown 에 둔다(창을 좁힌 채로 두면 뒤 클러스터가 전부 오염된다). */
      teardown(ctx) {
        return ctx.host("window_resize", { width: 1440, height: 900 });
      },
    },
  ];
}

/** 러너에 이 클러스터를 통째로 등록한다. 레인 B·D·E 도 같은 이름꼴을 쓴다. */
export function registerJobProbes(runner) {
  return runner.registerAll(createJobProbes());
}
