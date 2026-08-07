/* N-08 레인 C — 클러스터 C(`frontend/src/selftest/probes/job.js`) 계약.
 *
 * 이 클러스터는 저장소에서 **가장 큰** 프로브 다섯을 진다. 이 파일이 보는 것 셋:
 *  ⓐ 이식이 **충실**한가 — 방출 필드와 그 값 모양이 레거시와 같고, 양성/음성 대조가 하나도
 *     사라지지 않았는가.
 *  ⓑ **순서가 데이터로 남았는가** — 이 클러스터는 순서를 잃으면 조용히 틀린다(빈 경로
 *     스냅샷 · 자기 스냅샷 밀기 · 같은 문맥 · resize 괄호). 네 제약이 `plan("full")` 에서
 *     실제로 성립하는지 실행 결과로 센다(`after` 를 적어 놓고 안 지키는 길을 막는다).
 *  ⓒ 규약이 지켜졌는가 — 시한이 늘지 않았고, 모듈이 전역을 쓰지 않으며, import 만으로는
 *     아무 일도 하지 않는가.
 *
 * DOM 은 손으로 세운 최소 대역이다. 제품 전역은 하나도 세우지 않는다 — 프로브가 전역을
 * 읽지 않는다는 것이 이 이식의 요점이기 때문이다(읽으면 대역이 없어 즉시 터진다).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createSelftestRunner, HOST_OPS } from "../../frontend/src/selftest/runner.js";
import { keysForCluster } from "../../frontend/src/selftest/schema.js";
import {
  C_CLUSTER,
  C_KEYS,
  createJobProbes,
  registerJobProbes,
} from "../../frontend/src/selftest/probes/job.js";

const SRC = readFileSync(
  new URL("../../frontend/src/selftest/probes/job.js", import.meta.url),
  "utf8",
);

const NOTICE = encodeURIComponent("공고서");
const CONTRACT = encodeURIComponent("계약서");

/* ────────────────────────── 가상 시계 ────────────────────────── */
/* 기준 이식본(n08_persistence_geometry.test.js)의 시계를 그대로 쓴다 — 두 레인이 다른 시계를
   쓰면 "예산이 늘었다"의 뜻이 레인마다 갈린다. */

function createClock() {
  let clock = 0;
  let seq = 0;
  const timers = [];
  return {
    now: () => clock,
    sleep(ms) {
      return new Promise((resolve) => {
        timers.push({ at: clock + ms, seq: (seq += 1), resolve });
      });
    },
    fireNext() {
      if (timers.length === 0) return false;
      timers.sort((a, b) => (a.at - b.at) || (a.seq - b.seq));
      const timer = timers.shift();
      clock = Math.max(clock, timer.at);
      timer.resolve();
      return true;
    },
  };
}

async function settle(clock, promise) {
  let done = false;
  const tracked = promise.then(
    (value) => { done = true; return value; },
    (error) => { done = true; throw error; },
  );
  tracked.catch(() => {});
  for (let step = 0; step < 20000; step += 1) {
    for (let flush = 0; flush < 40; flush += 1) await Promise.resolve();
    if (done) break;
    if (!clock.fireNext()) break;
  }
  return tracked;
}

/* ────────────────────────── DOM 대역 ────────────────────────── */

class FakeEl {
  constructor(tag, id) {
    this.tagName = String(tag || "div").toUpperCase();
    this.id = id || "";
    this.textContent = "";
    this.innerHTML = "";
    this.value = "";
    this.title = "";
    this.checked = false;
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.isConnected = true;
    this.offsetParent = {};
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.css = {};
    /** `true` 면 이 요소에서는 CSS display 가 UA `[hidden]` 을 이긴다 — overlay/hidden
     *  결함류의 **음성 극**을 세우는 손잡이다(규칙이 살아도 결과가 죽는 자리). */
    this.hiddenLoses = false;
    this.rect = { left: 0, right: 0, top: 0, bottom: 0, width: 10, height: 10 };
    this.rectFn = null;
    this.listeners = {};
    this.behavior = null;
    this.sub = new Map();
    this.subAll = new Map();
    this.doc = null;
    const classes = new Set();
    this.classList = {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
    };
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name)
      ? this.attributes[name] : null;
  }

  setAttribute(name, value) { this.attributes[name] = String(value); }

  hasAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name);
  }

  getBoundingClientRect() { return this.rectFn ? this.rectFn() : this.rect; }

  querySelector(sel) { return this.sub.has(sel) ? this.sub.get(sel) : null; }

  querySelectorAll(sel) { return this.subAll.has(sel) ? this.subAll.get(sel) : []; }

  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }

  dispatchEvent(event) {
    for (const fn of this.listeners[event.type] || []) fn(event);
    return true;
  }

  /** 비활성 요소의 `click()` 은 **이벤트를 만들지 않는다** — 「발신 0」이 배선 부재인지
   *  잠금인지 못 가르는 그 계측 공백이 여기서 재현된다(부재판별력 계기의 전제). */
  click() {
    if (this.disabled) return;
    this.dispatchEvent({ type: "click", target: this });
    if (this.behavior) this.behavior();
  }

  focus() { if (this.doc) this.doc.activeElement = this; }

  blur() { if (this.doc && this.doc.activeElement === this) this.doc.activeElement = this.doc.body; }
}

class FakeEvent {
  constructor(type, opts) {
    this.type = type;
    this.bubbles = !!(opts && opts.bubbles);
  }
}

/* ────────────────────── 「문서 만들기」 대역 조립 ────────────────────── */

/** 다섯 프로브가 함께 쓰는 한 벌의 대역. 레거시 드라이버가 한 창에서 순서대로 돌리는 것과
 *  같은 형상이라, 교차오염(자기 스냅샷 밀기·경로 스냅샷)도 여기서 실제로 일어난다. */
function createJobBand(conf) {
  const options = conf || {};
  const byId = new Map();
  const sel = new Map();
  const selAll = new Map();
  const band = {
    panelWidth: 1000,
    hostPushes: [],
    navLog: [],
    resizes: [],
    services: null,
    lastResult: null,
    resultOwner: null,
    mount: 1,
    selectionKey: null,
    currentSnap: null,
  };

  const doc = {
    readyState: "complete",
    activeElement: null,
    body: null,
    getElementById: (id) => (byId.has(id) ? byId.get(id) : null),
    querySelector: (s) => (sel.has(s) ? sel.get(s) : null),
    querySelectorAll: (s) => (selAll.has(s) ? selAll.get(s) : []),
  };

  function make(tag, id) {
    const el = new FakeEl(tag, id);
    el.doc = doc;
    if (id) byId.set(id, el);
    return el;
  }

  doc.body = make("body");
  doc.activeElement = doc.body;

  /* ── 세션 존·액션바 ─────────────────────────────────────────── */
  const jobZones = make("div", "jobZones");
  const jobActionBar = make("div", "jobActionBar");
  const dgSide = make("div");
  dgSide.rect = { left: 100, right: 400, width: 300, height: 40 };
  const actionRow = make("div");
  const jobGate = make("span", "jobGate");
  jobGate.textContent = "문서 작업을 선택하세요.";
  jobGate.rectFn = () => ({ left: 0, right: 0, width: jobGate.textContent ? 60 : 0, height: 20 });
  const jobGenBtn = make("button", "jobGenBtn");
  jobGenBtn.disabled = true;
  /* 빈 문안이 자리를 비우면 앞의 gap 이 남아 마지막 버튼만 물러선다 — 그 결함을 켜는 손잡이. */
  jobGenBtn.rectFn = () => ({
    left: 20, width: 80, height: 28,
    right: 100 - (options.emptyNoteShift && !jobGate.textContent ? options.emptyNoteShift : 0),
  });
  actionRow.children = [jobGate, jobGenBtn];
  sel.set("#jobZones .data-grid > .dg-side", dgSide);
  sel.set("#jobActionBar .actionbar-row", actionRow);

  const capActions = make("h3");
  capActions.css.display = options.capDisplay || "flex";
  const capBtn = make("button");
  capActions.sub.set("button", capBtn);
  capActions.rect = { left: 0, right: 300, width: 300, height: 20 };
  capBtn.rect = { left: 280, right: options.capFarEdge === undefined ? 300 : 300 - options.capFarEdge, width: 20, height: 20 };
  sel.set("#jobZones .zone-cap.zone-cap-actions", capActions);

  const jobActionName = make("span", "jobActionName");
  const jobActionConn = make("span", "jobActionConn");
  jobActionConn.hidden = true;
  const jobActionRelink = make("button", "jobActionRelink");
  jobActionRelink.hidden = true;
  const jobBtnPickFolder = make("button", "jobBtnPickFolder");
  jobBtnPickFolder.disabled = true;
  const jobRestate = make("div", "jobRestate");
  jobRestate.textContent = "직접 선택 2행 · 정의 매치 1 · 정의 밖 1";
  const jobNoDataExit = make("div", "jobNoDataExit");
  jobNoDataExit.css.display = "none";
  make("button", "jobPickInLibrary");

  /* ── 후보 줄 ─────────────────────────────────────────────── */
  const jobCandsRow = make("div", "jobCandsRow");
  const jobCandidates = make("div", "jobCandidates");
  jobCandidates.innerHTML = "<div class='job-cand-card'>…</div>";
  const browseOpen = make("button", "jobBrowseOpen");
  browseOpen.attributes["data-browse-open"] = "";
  const candMore = make("span");
  candMore.textContent = "  확인 필요 1건 · 외 2건  ";
  const candRun = make("span");
  candRun.textContent = "마지막 성공 실행 2026-07-20";

  const cards = new Map();
  const stars = new Map();
  function candCard(name, opts) {
    const card = make("button", "jobCand-" + encodeURIComponent(name));
    card.attributes["data-cand"] = name;
    Object.assign(card, opts && opts.el ? opts.el : {});
    cards.set(name, card);
    const star = make("button", "jobFav-" + encodeURIComponent(name));
    star.attributes["data-fav"] = name;
    star.attributes["aria-pressed"] = (opts && opts.favorited) ? "true" : "false";
    stars.set(name, star);
    return card;
  }
  const cardNotice = candCard("공고서", { favorited: true });
  const cardContract = candCard("계약서", { favorited: false });

  selAll.set("#jobCandidates [data-cand]", [cardNotice, cardContract]);
  selAll.set("#jobCandidates [data-fav]", [stars.get("공고서"), stars.get("계약서")]);
  selAll.set("#jobCandidates button[disabled]", options.disabledChips || []);
  sel.set("#jobCandidates [data-browse-open]", browseOpen);
  sel.set("#jobCandidates .cand-more", candMore);
  sel.set("#jobCandidates .cand-run", candRun);
  const sug = make("span");
  selAll.set("#jobCandidates .cand-sug", [sug]);
  const secCapA = make("h4"); secCapA.textContent = "HWPX 문서 생성";
  const secCapB = make("h4"); secCapB.textContent = "온나라 기안 검토·복사";
  selAll.set("#jobCandidates .cand-sec-cap", [secCapA, secCapB]);
  const modeA = make("span"); modeA.textContent = "HWPX 생성";
  const modeB = make("span"); modeB.textContent = "온나라 기안";
  selAll.set("#jobCandidates .cand-mode", [modeA, modeB]);
  const suggestedCard = make("div");
  suggestedCard.css.borderStyle = "dashed";
  sel.set("#jobCandidates .job-cand-card.suggested", suggestedCard);

  /* 활성 카드·경고 카드(job_active_card) */
  const activeCard = make("div");
  const candTpl = make("span"); candTpl.textContent = "공고서.hwpx";
  const candMenuBtn = make("button", "jobCandMenuBtn");
  candMenuBtn.attributes["data-cand-menu"] = "";
  activeCard.sub.set(".cand-tpl", candTpl);
  activeCard.sub.set("[data-cand-menu]", candMenuBtn);
  sel.set("#jobCandidates .job-cand-card.active", activeCard);
  selAll.set("#jobCandidates [data-cand-menu]", [candMenuBtn]);
  const warnCard = make("div");
  const candConn = make("span"); candConn.textContent = "템플릿 없음";
  warnCard.sub.set(".cand-conn", candConn);
  sel.set("#jobCandidates .job-cand-card.warn", warnCard);
  const itemOpen = make("button");
  itemOpen.attributes["data-track-act"] = "open";
  itemOpen.attributes["data-path"] = "C:\\t\\공고서.hwpx";
  itemOpen.textContent = "열기";
  const itemReveal = make("button");
  itemReveal.attributes["data-track-act"] = "reveal";
  itemReveal.attributes["data-path"] = "C:\\t\\공고서.hwpx";
  itemReveal.textContent = "폴더에서 보기";
  candMenuBtn.behavior = () => {
    const selector = "#jobCandidates .cand-inline-menu";
    if (sel.has(selector)) {
      sel.delete(selector);
      return;
    }
    const inlineMenu = make("span");
    inlineMenu.subAll.set("[data-track-act]", [itemOpen, itemReveal]);
    sel.set(selector, inlineMenu);
  };

  const confirmModal = make("div", "confirmModal");
  confirmModal.classList.add("hidden");
  const confirmBody = make("p", "confirmModalBody");
  const confirmCancel = make("button", "confirmModalCancel");
  confirmCancel.behavior = () => { confirmModal.classList.add("hidden"); };

  /* ── 문서 탐색 면 ─────────────────────────────────────────── */
  const sheet = make("div", "jobBrowseSheet");
  sheet.classList.add("hidden");
  const browseNote = make("p", "jobBrowseNote");
  browseNote.textContent = "검색으로 2건을 걸렀습니다.";
  const browseQuery = make("input", "jobBrowseQuery");
  browseQuery.value = "견적";
  const tabAvail = make("button", "jobBrowseTab-available");
  tabAvail.textContent = "사용 가능 7";
  tabAvail.attributes["data-browse-tab"] = "available";
  tabAvail.attributes["aria-selected"] = "false";
  const tabNeeds = make("button");
  tabNeeds.textContent = "확인 필요 1";
  tabNeeds.attributes["data-browse-tab"] = "needs_action";
  tabNeeds.attributes["aria-selected"] = "true";
  sheet.subAll.set("[data-browse-tab]", [tabAvail, tabNeeds]);
  const browseRow = make("div");
  browseRow.textContent = "견적서  없는 열: 담당자";
  sheet.subAll.set(".browse-row", [browseRow]);
  const browseClose = make("button", "jobBrowseClose");

  browseOpen.behavior = () => {
    sheet.classList.remove("hidden");
    sheet.classList.remove("is-closing");
    browseQuery.focus();
  };
  browseClose.behavior = () => {
    sheet.classList.add("hidden");
    browseOpen.focus();               // 그냥 닫기 = **다시 열 출구**로 돌려보낸다
  };

  /* ── 표·필터 표면(job_mirror) ─────────────────────────────── */
  const tableRow = make("tr");
  tableRow.attributes["data-i"] = "0";
  tableRow.attributes["aria-selected"] = "true";
  tableRow.classList.add("on");
  const rowInput = make("input");
  rowInput.checked = true;
  tableRow.sub.set("input", rowInput);
  const rowTwo = make("tr");
  rowTwo.attributes["data-i"] = "1";
  selAll.set("#jobTableBody tr[data-i]", options.tableRows === "two" ? [rowTwo, tableRow] : [tableRow]);
  sel.set("#jobTableBody tr[data-i]", options.tableRows === "two" ? rowTwo : tableRow);
  const amountCell = make("td");
  amountCell.css.textAlign = "right";
  amountCell.css.fontVariantNumeric = "tabular-nums";
  sel.set("#jobTableBody td.col-amount", amountCell);
  sel.set('#jobTableBody td.doccol input[type="checkbox"]', rowInput);
  const docCell = make("div");
  docCell.css.display = "flex";
  sel.set("#jobTableBody .doccell", docCell);
  const colHint = make("span");
  colHint.textContent = "선택하면 파일명이 정해집니다";
  sel.set("#jobTableHead .col-hint", colHint);
  selAll.set('#jobTableBody .doc-off:not([aria-hidden="true"])', []);
  const mark = make("mark"); mark.textContent = "전산";
  sel.set("#jobTableBody mark", mark);
  const ficoA = make("button"); ficoA.attributes["data-col"] = "공고명";
  const ficoB = make("button"); ficoB.attributes["data-col"] = "금액";
  selAll.set("#jobTableHead .fico[data-col]", [ficoA, ficoB]);
  sel.set("#jobTableHead .fico", ficoA);

  const chips = make("div", "jobFilterChips");
  chips.textContent = "(공고명) 포함 「전산」";
  const prune = make("button");
  sel.set('#jobFilterChips [data-prune="공고명"]', prune);
  const defChip = make("span");
  defChip.css.backgroundColor = "rgb(230, 240, 255)";
  const branchChip = make("span");
  branchChip.css.backgroundColor = "rgb(245, 245, 245)";
  branchChip.css.borderStyle = "solid";
  sel.set("#jobFilterChips .fchip.definition", defChip);
  sel.set("#jobFilterChips .fchip.branch", branchChip);
  const roleA = make("span"); roleA.textContent = "필터";
  const roleB = make("span"); roleB.textContent = "가지";
  const roleC = make("span"); roleC.textContent = "선택";
  selAll.set(".fchip .chip-role", [roleA, roleB, roleC]);
  const strip = make("div", "jobSelStrip");
  strip.textContent = "필터 밖 선택 1행 · doc-002.hwpx";
  strip.css.backgroundColor = "rgb(245, 245, 245)";
  sel.set('#jobSelStrip [data-unsel="1"]', make("button"));

  const jobMirrorLine = make("div", "jobMirrorLine");
  jobMirrorLine.textContent = "빈 값 1필드(낙찰율) · 이름 2건";
  const jobMirror = make("div", "jobMirror");
  const blankFlag = make("span");
  sel.set("#jobMirrorLine .mir-blank-flag", blankFlag);
  const previewOpen = make("button", "jobMirrorPreviewOpen");
  const filterReapply = make("button", "jobFilterReapply");
  filterReapply.title = "(공고명) 포함 「전산」";
  const jobPanel = make("div", "jobPanel");
  const jobDataGrid = make("div", "jobDataGrid");
  const scrJob = make("section", "scr-job");
  scrJob.classList.add("on");
  const scrEditor = make("section", "scr-editor");
  const previewCard = make("div");
  sel.set("#previewSheet .modal-card", previewCard);
  previewCard.addEventListener("transitionend", () => {
    /* 닫힘 전이가 끝나면 초점은 **그 트리거**로 돌아온다 — 잠긴 트리거는 건너뛰는 것이
       모달의 정상 경로다(그 갈림을 mirror_focus_target_state 가 증언한다). */
    if (!previewOpen.disabled) previewOpen.focus();
    else doc.body.focus();
  });
  previewOpen.behavior = () => {
    Promise.resolve().then(() => band.services.Bridge.call("job", "preview_open", {}));
  };

  const effectivePanelWidth = () => parseFloat(jobPanel.style.width) || band.panelWidth;
  jobPanel.rectFn = () => ({ left: 0, right: effectivePanelWidth(), width: effectivePanelWidth(), height: 600 });

  /* ── 결과 3태 구획(job_result) ────────────────────────────── */
  const jobResult = make("div", "jobResult");
  jobResult.hidden = true;
  const jobResultTitle = make("h3", "jobResultTitle");
  const jobResultFails = make("ul", "jobResultFails");
  const jobResultFailedSel = make("button", "jobResultFailedSel");
  jobResultFailedSel.attributes["data-busy-lock"] = "";
  const jobResultEvidence = make("details", "jobResultEvidence");
  const jobResultStale = make("div", "jobResultStale");
  jobResultStale.hidden = true;
  const jobResultRename = make("button", "jobResultRename");
  jobResultRename.attributes["data-busy-lock"] = "";
  const jobResultClose = make("button", "jobResultClose");
  jobResultClose.attributes["data-busy-lock"] = "";
  const jobResultSummary = make("p", "jobResultSummary");
  const jobResultZone = make("section", "jobResultZone");
  const jobRunLog = make("details", "jobRunLog");
  const jobRunLogLast = make("div", "jobRunLogLast");
  jobRunLogLast.textContent = "아직 기록이 없습니다.";
  const jobGenLog = make("div", "jobGenLog");
  const folderLine = make("div");
  folderLine.css.display = "flex";
  folderLine.hiddenLoses = !!options.folderHiddenLoses;
  sel.set("#jobResult .result3-folder", folderLine);
  let failRow = null;

  function resetResultZone() {
    jobResult.hidden = true;
    jobResultStale.hidden = true;
    if (failRow) { byId.delete("jobResultFail-7"); failRow = null; }
  }

  function renderResult(payload) {
    if (payload && payload.running) {
      jobResult.hidden = false;
      jobResult.dataset.state = "running";
      jobResultTitle.textContent = payload.title;
      folderLine.hidden = true;
      return;
    }
    band.lastResult = payload;
    band.resultOwner = band.currentSnap ? band.currentSnap.last_run_job : null;
    jobResult.hidden = false;
    jobResultStale.hidden = true;
    folderLine.hidden = false;
    jobResult.dataset.state = payload.status;
    jobResult.dataset.level = payload.level;
    jobResultTitle.textContent = payload.title;
    jobResultSummary.textContent = payload.summary;
    jobResultEvidence.hidden = false;
    const failures = payload.failures || [];
    jobResultFails.children = failures.map(() => make("li"));
    jobResultFails.textContent = failures
      .map((f) => `${f.identity} ${f.known ? f.reason : "원인 진단 미연결"}`).join(" ");
    if (failures.length > 0) {
      failRow = make("li", "jobResultFail-" + failures[0].index);
    } else if (failRow) {
      byId.delete("jobResultFail-7");
      failRow = null;
    }
    jobResultFailedSel.hidden = !(payload.failed_selectable > 0);
    jobResultFailedSel.textContent = `실패한 ${payload.failed_selectable}건만 선택`;
    jobResultRename.hidden = false;
  }

  function markResultStale() {
    if (jobResult.hidden) return;
    jobResultStale.hidden = false;
    /* 주체는 **`last_run_job` 을 따라온다** — 이름 변경은 전환이 아니다. */
    const owner = (band.currentSnap && band.currentSnap.last_run_job) || "";
    jobResultStale.textContent = `직전 실행 · ${owner}`;
    /* 남의 작업을 겨누는 버튼은 서지 않는다(주체 방어). */
    const mine = !!band.currentSnap && band.currentSnap.job_name === owner;
    jobResultRename.hidden = !mine;
    jobResultFailedSel.hidden = !mine;
  }

  jobResultClose.behavior = () => {
    resetResultZone();
    jobRunLogLast.textContent = "아직 기록이 없습니다.";
    /* 게이트가 닫혀 생성 버튼이 비활성이면 구획 자신이 초점을 받는다(방금 있던 문맥 유지). */
    if (jobGenBtn.disabled) jobResultZone.focus(); else jobGenBtn.focus();
  };
  jobGenBtn.behavior = () => {
    /* 발신 통로는 R4-03 에서 typed `Client.invoke` 로 옮겼다. 대역이 옛 `Bridge.generate` 를
       계속 모델링하면 프로브가 **죽은 seam** 을 스텁해도 이 층은 초록이라, 값싼 층의 초록이
       제품에 대해 거짓이 된다(실 WebView2 만 빨강 = 진단이 가장 비싼 곳으로 밀린다).
       상관 토큰 반향까지 흉내 내는 이유도 같다 — 토큰을 안 돌려주는 스텁은 여기서 잡힌다. */
    band.genCalls = (band.genCalls || 0) + 1;
    const token = `band-run-${band.genCalls}`;
    band.services.Client.invoke("generate", "job", false, token).then((env) => {
      const res = (env && env.ok === true ? env.value : null) || {};
      // 귀속이 깨진 응답은 그리지 않는다 — 남의 실행 결과를 자기 자리에 세우는 경로다.
      if (res.run_token !== token) return;
      if (res.ok === false) {
        jobResult.hidden = false;
        jobResult.dataset.state = "rejected";
        jobResultSummary.textContent = res.error;
        jobGenLog.textContent = res.error;
        jobRunLogLast.textContent = res.error;
      }
    });
  };

  /* ── 렌더(푸시 수신) ──────────────────────────────────────── */
  function render(screen, snap) {
    if (screen !== "job" || !snap) return;
    const previous = band.currentSnap;
    band.currentSnap = snap;
    // 게이트·prework
    jobGate.textContent = snap.gate ? snap.gate.text : "";
    jobGenBtn.disabled = !(snap.gate && snap.gate.enabled);
    jobActionName.textContent = snap.job_name || "";
    jobBtnPickFolder.disabled = !snap.has_job;
    jobZones.css.display = "grid";
    jobActionBar.css.display = "flex";
    jobCandsRow.css.display = (snap.candidates && snap.candidates.top.length > 0) ? "flex" : "none";
    selAll.set(
      "#jobCandidates [data-cand]",
      (snap.candidates ? snap.candidates.top : []).map((c) => cards.get(c.name)).filter(Boolean),
    );
    for (const cand of (snap.candidates ? snap.candidates.top : [])) {
      const star = stars.get(cand.name);
      if (star) star.attributes["aria-pressed"] = cand.favorited ? "true" : "false";
    }
    // 데이터 없음 출구·연결 상태
    jobNoDataExit.css.display = (!snap.has_data && !snap.has_job) ? "flex" : "none";
    const missing = !!snap.template_missing;
    jobActionConn.hidden = !missing;
    jobActionConn.textContent = missing ? "템플릿 없음" : "";
    jobActionRelink.hidden = !missing;
    if (options.relinkInvisible) jobActionRelink.offsetParent = null;
    // 본문 존·재진술 — prework(작업 미선택)과 danger 차단에서 재진술은 서지 않는다
    const danger = !!(snap.gate && snap.gate.level === "danger");
    jobRestate.css.display = (danger || !snap.has_job) ? "none" : "block";
    const drift = snap.drift || [];
    const tokens = snap.name_tokens || [];
    if (drift.length > 0 || tokens.length > 0) {
      const banner = make("div");
      banner.attributes.role = "alert";
      banner.textContent = (drift.length ? drift : tokens).join(", ");
      jobMirror.children = [banner];
      sel.set('#jobMirror .mir-drift[role="alert"]', banner);
      sel.set("#jobMirror .mir-drift", banner);
      sel.set("#jobMirror .mirline", null);
      sel.set('#jobMirror [data-act="fix-mapping"]', drift.length ? make("a") : null);
      sel.set('#jobMirror [data-act="fix-filename"]', tokens.length ? make("a") : null);
    } else {
      jobMirror.children = [];
      sel.set('#jobMirror .mir-drift[role="alert"]', null);
      sel.set("#jobMirror .mir-drift", null);
      sel.set("#jobMirror .mirline", null);
      sel.set('#jobMirror [data-act="fix-mapping"]', null);
      sel.set('#jobMirror [data-act="fix-filename"]', null);
    }
    // 확인 면 출구 가용성은 `can_open` 에 결속된다
    if (snap.preview) previewOpen.disabled = !snap.preview.can_open;
    // 직전 필터 재적용
    if (snap.filter) {
      filterReapply.css.display = snap.filter.reapply_available ? "inline-flex" : "none";
    }
    // 탐색 면: 포커스가 입력에 있으면 서버 값이 덮지 않는다
    if (snap.browse && doc.activeElement !== browseQuery) browseQuery.value = snap.browse.query;
    if (snap.browse && snap.browse.rows.some((r) => r.name === "공고서")) {
      if (!byId.has("jobBrowseRow-" + NOTICE)) {
        const row = make("div", "jobBrowseRow-" + NOTICE);
        row.behavior = () => {
          band.services.Client.dispatch("job", "select_job", { name: "공고서" }).then(() => {
            sheet.classList.add("is-closing");
            cards.get("공고서").focus();
          });
        };
      }
    }
    // 결과 구획의 §2.18 처분
    if (previous && !jobResult.hidden) {
      const switched = previous.last_run_job === snap.last_run_job
        && previous.job_name !== snap.job_name;
      const swapped = previous.data_mount !== snap.data_mount;
      const selectionChanged = previous.selection_key !== snap.selection_key;
      if (switched || swapped) {
        const prior = band.lastResult;
        resetResultZone();
        if (prior) {
          jobRunLogLast.textContent =
            `${prior.exit_summary} · ${snap.last_run_job} · ${prior.out_dir}`;
        }
      } else if (selectionChanged) {
        markResultStale();
      }
    }
  }

  /* ── 주입 능력 ────────────────────────────────────────────── */
  const win = {
    Event: FakeEvent,
    getComputedStyle(el) {
      const hiddenWins = el.hidden && !el.hiddenLoses;
      return {
        ...el.css,
        display: hiddenWins ? "none" : (el.css.display || "block"),
        gridTemplateColumns: el === jobDataGrid
          ? (effectivePanelWidth() >= 900 ? "1fr 320px" : "1fr")
          : (el.css.gridTemplateColumns || "none"),
      };
    },
  };

  /* 즐겨찾기 의도는 화면 표시가 아니라 **누적 의도**를 따른다(왕복 중 재클릭이 의도를
     뒤집는다). 스냅샷이 다시 와도 낡은 표시로 되돌아가는 실제 형상 그대로. */
  const favIntent = new Map([["공고서", true], ["계약서", false]]);
  let favChain = Promise.resolve();
  for (const [name, star] of stars) {
    star.behavior = () => {
      const next = !favIntent.get(name);
      favIntent.set(name, next);
      const dispatch = band.services.Client.dispatch; // R4 typed 통로를 요청 시점에 고정
      favChain = favChain
        .then(() => dispatch.call(band.services.Client, "job", "toggle_favorite", { name, value: next }))
        .catch(() => {});
    };
  }

  cardNotice.behavior = () => {
    cardNotice.setAttribute("aria-busy", "true");
    cardNotice.textContent = "공고서 여는 중…";
    /* R4 selectJob은 flushPendingEdits() 뒤 다음 마이크로태스크에서 typed 발신한다. 프로브가
       클릭 직후 스텁을 거두는 회귀를 잡으려면 대역도 이 실제 순서를 따라야 한다. */
    Promise.resolve().then(() => band.services.Client.dispatch(
      "job", "select_job", { name: "공고서" },
    ));
  };
  cardContract.behavior = () => {
    /* 경고 카드 클릭은 **선택이 아니다** — 안내 다이얼로그가 서고 발신은 없다. */
    if (options.warnCardSelects) {
      band.services.Client.dispatch("job", "select_job", { name: "계약서" });
      return;
    }
    confirmModal.classList.remove("hidden");
    confirmBody.textContent = "이 작업은 선택할 수 없습니다. 템플릿을 다시 연결하세요.";
  };

  let rowChain = Promise.resolve();
  tableRow.behavior = () => {
    const on = tableRow.classList.contains("on");
    const next = !on;
    tableRow.classList.toggle("on", next);
    tableRow.attributes["aria-selected"] = next ? "true" : "false";
    rowInput.checked = next;
    /* R4 owner의 typed 통로는 **요청 시점**에 붙든다 — 큐에서 풀릴 때 다시 찾으면 그 사이
       바뀐 통로로 나간다. 프로브 스텁이 바로 그 대표 사례이고, 거울 프로브가 두 번째 토글
       값을 지연 회수로 확인할 수 있는 근거가 이 한 줄이다. */
    const dispatch = band.services.Client.dispatch;
    rowChain = rowChain
      .then(() => dispatch.call(band.services.Client, "job", "toggle_record", { index: 0, value: next }))
      .catch(() => {});
  };
  ficoA.behavior = () => {
    band.services.Client.dispatch("job", "filter_panel", { col: "공고명" });
    const reactPanel = make("div");
    reactPanel.setAttribute("aria-busy", "true");
    reactPanel.textContent = "공고명 · 불러오는 중…";
    const panelClose = make("button");
    panelClose.behavior = () => {
      if (!options.panelCloseSticks) sel.delete("#jobTableHost .react-colpanel");
    };
    reactPanel.sub.set('[data-act="panel-close"]', panelClose);
    sel.set("#jobTableHost .react-colpanel", reactPanel);
  };

  const services = {
    Nav: {
      go(screen, opts) {
        band.navLog.push({ screen, opts: opts || null });
        scrJob.classList.toggle("on", screen === "job");
        scrEditor.classList.toggle("on", screen === "editor");
      },
    },
    Bridge: {
      call: (screen, action, payload) => {
        band.navLog.push({ bridge: action, payload });
        return Promise.resolve({});
      },
    },
    Client: {
      dispatch: (screen, action, payload) => {
        band.navLog.push({ client: action, payload });
        return Promise.resolve({ ok: true, value: {} });
      },
      /* 기본은 성사 — 봉투는 통로의 성패(`ok:true`), payload 는 판정이다. 토큰을 그대로
         돌려주는 것이 실물의 계약이라 대역도 그렇게 한다. */
      invoke: (method, ...args) => Promise.resolve(
        { ok: true, value: { ok: true, run_token: args[2] } },
      ),
    },
    Modal: { close: () => { previewCard.classList.add("is-closing"); } },
    Popover: { closeAll: () => {} },
    JobScreen: {
      overwriteBody: (info) => `총 ${info.total}건 · 덮어쓰기 ${info.overwrite_count}`
        + ` · 새로 만들기 ${info.new_count} · ${info.conflict_names.join(", ")} 외 ${info.conflict_more}`,
      resultExitLine: (payload, owner) => {
        if (payload.rejected || payload.running) return "";
        if (!payload.exit_summary) return `${owner} · 수치를 알 수 없습니다`;
        return `${owner} · ${payload.exit_summary} · ${payload.out_dir}`;
      },
      guardBody: (counts, verb) => {
        const parts = [`직접 선택 ${counts.sel_count}행`, verb];
        if (counts.in_def || counts.extra) {
          parts.push(`정의 매치 ${counts.in_def} · 정의 밖 ${counts.extra}`);
        }
        if (counts.filter_active) parts.push(`필터 정의(${counts.filter_parts}개 조건) · 직전 필터 재적용`);
        return parts.join(" · ");
      },
      confirmDestructiveIfArmed: () => Promise.resolve(true),
      renderResult,
      markResultStale,
    },
  };
  band.services = services;

  band.doc = doc;
  band.win = win;
  band.el = {
    jobGate, jobGenBtn, previewOpen, filterReapply, jobPanel, jobDataGrid,
    jobResult, jobResultStale, jobActionRelink, jobNoDataExit, sheet, browseQuery,
    jobRunLogLast, folderLine, cards, stars, browseOpen, jobRestate,
  };
  band.render = render;
  return band;
}

function createCaps(conf) {
  const options = conf || {};
  const clock = createClock();
  const band = createJobBand(options);
  const requests = [];
  const caps = {
    doc: band.doc,
    win: band.win,
    push(screen, snapshot) {
      band.hostPushes.push({ screen, job: snapshot && snapshot.job_name });
      band.render(screen, snapshot);
    },
    services: options.services === undefined ? band.services : options.services,
    host: {
      provides: HOST_OPS.slice(),
      request(op, payload) {
        requests.push({ op, payload });
        if (op === "window_resize") {
          band.resizes.push(payload);
          band.panelWidth = payload.width - 40;
        }
        if (options.host) return options.host(op, payload);
        return null;
      },
    },
    now: clock.now,
    sleep: clock.sleep,
  };
  return { caps, clock, band, requests };
}

async function runFull(conf) {
  const built = createCaps(conf);
  const runner = createSelftestRunner(built.caps);
  registerJobProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  return { ...built, runner, report };
}

/* ────────────────────────── 표면 ────────────────────────── */

test("공개 표면 — 정확히 넷이고 export default 는 없다", () => {
  assert.equal(C_CLUSTER, "C");
  assert.ok(Array.isArray(C_KEYS));
  assert.equal(typeof createJobProbes, "function");
  assert.equal(typeof registerJobProbes, "function");
  assert.equal(/export\s+default/.test(SRC), false);
  const exported = (SRC.match(/^export\s+(?:const|function|async function)\s+([A-Za-z_$][\w$]*)/gm) || [])
    .map((line) => line.replace(/^export\s+(?:const|function|async function)\s+/, ""));
  assert.deepEqual(exported.sort(), ["C_CLUSTER", "C_KEYS", "createJobProbes", "registerJobProbes"]);
});

test("키 전수가 스키마의 클러스터 C 와 정확히 같다", () => {
  assert.deepEqual(C_KEYS.slice().sort(), keysForCluster("C"));
  assert.equal(C_KEYS.length, 6);
  for (const k of [
    "job_data_first", "job_inherited", "job_active_card",
    "job_mirror", "job_result", "job_density_narrow",
  ]) {
    assert.ok(C_KEYS.includes(k), k);
  }
});

test("등록 — 러너 계약을 전수 통과하고 full 계획이 선다", () => {
  const { caps } = createCaps();
  const runner = createSelftestRunner(caps);
  const registered = registerJobProbes(runner);
  assert.equal(registered.length, 6);
  assert.equal(runner.probes().length, 6);
  assert.deepEqual(runner.plan("full").map((p) => p.name), [
    "job_data_first", "job_inherited", "job_active_card",
    "job_mirror", "job_result", "job_density_narrow",
  ]);
  for (const probe of runner.describe()) {
    assert.equal(probe.cluster, "C");
    assert.equal(probe.owner, "frontend");
    assert.deepEqual(probe.modes, ["full"]);
  }
});

test("createJobProbes 는 순수하다 — 부를 때 DOM·리스너·전역이 생기지 않는다", () => {
  const before = Object.keys(globalThis).length;
  const first = createJobProbes();
  const second = createJobProbes();
  assert.equal(first.length, 6);
  assert.notEqual(first[0], second[0], "정의는 매번 새로 지어야 합니다(공유 변조 금지).");
  assert.equal(Object.keys(globalThis).length, before);
  assert.equal(typeof globalThis.document, "undefined");
});

/* ───────────────────── 순서 — 잃으면 조용히 틀린다 ───────────────────── */

test("네 순서 제약이 데이터로 남고 plan(full) 에서 **실제로** 성립한다", () => {
  const { caps } = createCaps();
  const runner = createSelftestRunner(caps);
  registerJobProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));
  const order = runner.plan("full").map((p) => p.name);
  const at = (name) => order.indexOf(name);

  // ① app.py:3872-3876 — 빈 경로 스냅샷(#137 교차오염)
  assert.deepEqual(byName.get("job_mirror").after, ["job_data_first"]);
  assert.match(byName.get("job_mirror").afterReason, /빈 경로/);
  assert.match(byName.get("job_mirror").afterReason, /#137/);
  assert.ok(at("job_data_first") < at("job_mirror"));

  // ② app.py:3897-3898 — 자기 스냅샷을 미는 프로브는 앞 사슬이 끝난 뒤에
  assert.deepEqual(byName.get("job_active_card").after, ["job_data_first"]);
  assert.match(byName.get("job_active_card").afterReason, /자기 합성 스냅샷/);
  assert.ok(at("job_data_first") < at("job_active_card"));

  // ③ app.py:3921 — 거울 바로 뒤, 같은 화면·같은 스냅샷 문맥
  assert.deepEqual(byName.get("job_result").after, ["job_mirror"]);
  assert.match(byName.get("job_result").afterReason, /같은 화면·같은 스냅샷 문맥/);
  assert.equal(at("job_result"), at("job_mirror") + 1, "거울과 결과 사이에 아무도 끼지 않는다.");

  // ④ app.py:3937-3944 — 밀도 읽기는 호스트 resize 괄호 안에 있다(프로브가 직접 하지 않는다)
  const density = byName.get("job_density_narrow");
  assert.deepEqual(density.hostSetup, { op: "window_resize", payload: { width: 900, height: 820 } });
  assert.deepEqual(density.requiresHost, ["window_resize"]);
  assert.equal(density.settleBeforeMs, 400);
  assert.equal(density.cooldownAfterMs, 400);
  assert.match(density.settleReason, /relayout/);
  assert.match(density.cooldownReason, /1440/);
  assert.deepEqual(density.after, ["job_result"]);
  assert.ok(at("job_result") < at("job_density_narrow"));
  /* 프로브가 스스로 창을 만지지 않는다 — 소스에 resize 호출이 없다. */
  assert.equal(/resizeTo|\.resize\(/.test(SRC), false);

  // 순서 제약이 있는 프로브는 **전부** 사유를 적었다(이유 없는 순서는 다음 이식에서 사라진다)
  for (const probe of runner.describe()) {
    if (probe.after.length > 0) {
      assert.equal(typeof probe.afterReason, "string", probe.name);
      assert.ok(probe.afterReason.length > 20, probe.name);
    }
  }
});

test("legacySite 열두 자리가 app.py 의 실제 호출 순서를 잇는다", () => {
  const { caps } = createCaps();
  const runner = createSelftestRunner(caps);
  registerJobProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));
  assert.equal(byName.get("job_data_first").legacySite, 3877);
  assert.equal(byName.get("job_inherited").legacySite, 3895);
  assert.equal(byName.get("job_active_card").legacySite, 3899);
  assert.equal(byName.get("job_mirror").legacySite, 3904);
  assert.equal(byName.get("job_result").legacySite, 3922);
  assert.equal(byName.get("job_density_narrow").legacySite, 3939);
});

test("시간 예산은 늘지 않았다 — 레거시 표와 자리별 대조", () => {
  const { caps } = createCaps();
  const runner = createSelftestRunner(caps);
  registerJobProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));
  /* `deadlineRationale` 은 describe() 가 싣지 않는 필드라 정의 데이터에서 직접 본다. */
  const rationale = new Map(createJobProbes().map((p) => [p.name, p.deadlineRationale]));
  /* 레거시 → 이식. `_probe_late` 는 50×50ms = 2500ms 공용 예산이다. */
  const table = [
    ["job_data_first", 2500 + 2500, 5000],   // app.py:3882 + 3888
    ["job_inherited", 0, 0],                 // 폴링 없음
    ["job_active_card", 2500, 2500],         // app.py:3900
    /* job_mirror — 레거시 비교 대상이 **성립하지 않는다**(#429). app.py:3910 의 0.2초
       sleep 은 비동기 확정만 덮었고, 이 프로브가 함께 하는 277줄 동기 구간(getComputedStyle
       다수 = 강제 레이아웃 반복)에는 레거시에 시한이 **아예 없었다**. 이식 예산이 그 둘을 한
       값으로 덮으므로 0.2초와 견주는 것은 사과와 배다.

       종전 이 줄은 `[200, 200]` 이었다. 그래서 값·근거문·이 가드 셋이 모두 "200 이 맞다"를
       인코딩했다 — 정작 근거문은 "시한이 아예 없던 동기 구간까지 이제 이 예산 안에 든다"고
       스스로 적고 있었는데도. 느린 러너에서 CI 가 두 번 무너지고서야 드러났다. */
    ["job_mirror", Infinity, 2500],
    ["job_result", 2500, 2500],              // app.py:3923
    ["job_density_narrow", 0, 0],            // 폴링 없음
  ];
  for (const [name, legacy, ported] of table) {
    assert.equal(byName.get(name).deadlineMs, ported, name);
    assert.ok(byName.get(name).deadlineMs <= legacy, `${name} 예산이 늘었습니다`);
    assert.equal(typeof rationale.get(name), "string", name);
    assert.ok(rationale.get(name).length > 20, name);
  }
  /* 고정 대기 합도 레거시(app.py:3938 + 3944 = 0.8초) 그대로. */
  const totalWait = runner.describe().reduce(
    (sum, p) => sum + p.settleBeforeMs + p.cooldownAfterMs, 0,
  );
  assert.equal(totalWait, 800);
  assert.equal(runner.budgetMs("full"), 5000 + 0 + 2500 + 2500 + 2500 + 0 + 800);
  /* 아무 프로브도 자기 시한을 스스로 처리하지 않는다 — 감시견이 마지막 안전망이다. */
  for (const p of runner.describe()) assert.equal(p.handlesOwnDeadline, false, p.name);
});

/* ────────────────────── 한 바퀴(full) 통과 ────────────────────── */

test("full 한 바퀴 — 여섯 키가 전부 서고 오류가 없다", async () => {
  const { report, band } = await runFull();
  assert.deepEqual(report.errors, []);
  assert.equal(report.ok, true);
  assert.deepEqual(Object.keys(report.results).sort(), keysForCluster("C"));
  assert.deepEqual(report.skipped, []);
  /* 레거시 드라이버와 같은 실행 순서. */
  assert.deepEqual(report.order, [
    "job_data_first", "job_inherited", "job_active_card",
    "job_mirror", "job_result", "job_density_narrow",
  ]);
  const syntheticEntries = band.navLog.filter((entry) => entry.screen === "job");
  assert.ok(syntheticEntries.length >= 6);
  assert.ok(syntheticEntries.every((entry) => entry.opts && entry.opts.refreshed === true),
    "합성 job 스냅샷 앞에서는 자동 실 refresh를 중복 발신하지 않습니다.");
  assert.ok(band.hostPushes.length > 20, "실 render 구동이 주입 push 로 실제로 일어났습니다.");
});

/* ────────────────── job_data_first — 대조 보존 ────────────────── */

test("job_data_first — prework 표면과 기준면 두 측정", async () => {
  const { report } = await runFull();
  const j = report.results.job_data_first;
  assert.equal(j.zones_shown, true);
  assert.equal(j.actionbar_shown, true);
  /* 기준면은 좌 열 오른쪽 끝(구분선)이다 — 두 측정 모두 어긋남 0. */
  assert.equal(j.actionbar_plane, 0);
  assert.equal(j.actionbar_plane_empty_note, 0);
  assert.deepEqual(j.cap_actions, { display: "flex", far_edge: 0 });
  assert.equal(j.cands_row_shown, true);
  assert.equal(j.cand_buttons, 2);
  assert.equal(j.cand_exit, true);
  assert.equal(j.cand_more_text, "확인 필요 1건 · 외 2건");
  assert.equal(j.cand_disabled_chips, 0);
  assert.equal(j.gate_text, "문서 작업을 선택하세요.");
  assert.equal(j.gen_disabled, true);
  assert.equal(j.action_name_empty, true);
  assert.equal(j.restate_hidden, true);
  assert.equal(j.folder_pick_disabled, true);
  assert.deepEqual(j.cand_order, ["공고서", "계약서"]);
  assert.deepEqual(j.fav_pressed, ["true", "false"]);
  assert.deepEqual(j.cand_sec_caps, ["HWPX 문서 생성", "온나라 기안 검토·복사"]);
  assert.deepEqual(j.cand_mode_texts, ["HWPX 생성", "온나라 기안"]);
  assert.equal(j.suggested_marks, 1);
  assert.equal(j.suggested_dashed, "dashed");
  assert.equal(j.last_run_text, "마지막 성공 실행 2026-07-20");
  assert.equal(j.fav_focus_restored, "kept");
});

test("job_data_first — 빈 문안이 자리를 차지하면 두 번째 측정만 어긋난다(음성 극)", async () => {
  const { report } = await runFull({ emptyNoteShift: 12 });
  const j = report.results.job_data_first;
  assert.equal(j.actionbar_plane, 0, "문안이 있는 상태는 여전히 정렬돼 보인다");
  assert.equal(j.actionbar_plane_empty_note, -12, "빈 문안 자리가 남아 마지막 버튼만 물러섰다");
});

test("job_data_first — 즐겨찾기 의도열이 클릭 순서 그대로 여섯 건", async () => {
  const { report } = await runFull();
  const j = report.results.job_data_first;
  assert.equal(j.fav_sync_sends, 0, "클릭은 체인 진입이고 즉시 발신하지 않는다");
  assert.equal(j.fav_intents, "[]");
  assert.equal(JSON.parse(j.fav_chain).inflight, 1, "앞 왕복이 끝나기 전엔 둘째를 보내지 않는다");
  assert.deepEqual(JSON.parse(j.fav_order), [false, true, true, false, true, false]);
  assert.deepEqual(
    JSON.parse(j.fav_diag),
    ["ok0", "ok1", "ok2", "ok3", "ok4", "ok5", "ok6", "ok7", "ok8"],
    "아홉 단계가 전부 예외 없이 돌았다 — 하나라도 던지면 진단 문자열이 남는다",
  );
});

test("job_data_first — 별이 없으면 조용히 넘어가지 않고 'no-stars' 로 말한다", async () => {
  const built = createCaps();
  built.band.doc.getElementById = ((real) => (id) => (
    id.indexOf("jobFav-") === 0 ? null : real(id)
  ))(built.band.doc.getElementById);
  const runner = createSelftestRunner(built.caps);
  registerJobProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  const j = report.results.job_data_first;
  assert.equal(j.fav_intents, "no-stars");
  assert.equal(j.fav_chain, "undefined");
  assert.equal(j.fav_order, "null");
  assert.equal(j.fav_diag, "null");
  assert.equal(j.fav_focus_restored, "no-id");
});

test("job_data_first — 탐색 면: 검색어 경합·탭 포커스·두 사유의 착지", async () => {
  const { report } = await runFull();
  const j = report.results.job_data_first;
  assert.equal(j.browse_open, true);
  assert.deepEqual(j.browse_tabs, ["사용 가능 7/false", "확인 필요 1/true"]);
  assert.deepEqual(j.browse_rows, ["견적서 없는 열: 담당자"]);
  assert.equal(j.browse_note, "검색으로 2건을 걸렀습니다.");
  assert.equal(j.browse_focus_is_query, true);
  /* 왕복 중 이어 친 검색어는 옛 스냅샷에 덮이지 않고, 포커스가 떠난 뒤 서버 값으로 확정된다. */
  assert.equal(j.browse_query_kept, "견적요청");
  assert.equal(j.browse_query_settled, "견적");
  assert.equal(j.browse_tab_focus, "jobBrowseTab-available");
  /* ① 고르고 닫음 = 그 작업 카드 ② 그냥 닫음 = 다시 열 출구. 두 사유가 다른 자리에 선다. */
  assert.equal(j.browse_sheet_closed, true);
  assert.equal(j.browse_pick_focus, "jobCand-" + NOTICE);
  assert.equal(j.browse_close_focus, "jobBrowseOpen");
});

test("job_data_first — 탐색 출구가 없으면 'no-exit' 이고 착지 3필드는 미정의 산출 그대로", async () => {
  const built = createCaps();
  const realQuery = built.band.doc.querySelector;
  built.band.doc.querySelector = (s) => (
    s === "#jobCandidates [data-browse-open]" ? null : realQuery(s)
  );
  const runner = createSelftestRunner(built.caps);
  registerJobProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  const j = report.results.job_data_first;
  assert.equal(j.browse_open, "no-exit");
  assert.equal(j.cand_exit, false);
  assert.equal(j.browse_pick_focus, "undefined");
  assert.equal(j.browse_sheet_closed, false);
  assert.equal(j.browse_close_focus, "undefined");
});

/* ────────────────── job_inherited — 두 극 ────────────────── */

test("job_inherited — 「여는 중」 표지와 흡수처 출구 두 극", async () => {
  const { report, band } = await runFull();
  const j = report.results.job_inherited;
  assert.equal(j.opening_marker_immediate, true, "후보 카드 클릭 프레임에 지연 표지가 선다");
  assert.equal(
    band.navLog.some((entry) => entry.client === "select_job"), false,
    "합성 작업 선택이 typed 스텁을 벗어나 실 Client로 샜습니다.",
  );
  /* 데이터가 있으면 숨고(소음 금지), 둘 다 없으면 상주한다(막다른 화면 금지). */
  assert.equal(j.no_data_exit_with_data, false);
  assert.equal(j.no_data_exit_shown, true);
  assert.equal(j.no_data_exit_target, true);
  assert.deepEqual(Object.keys(j), [
    "opening_marker_immediate", "no_data_exit_with_data", "no_data_exit_shown", "no_data_exit_target",
  ]);
});

test("job_inherited — 후보 카드가 없으면 'no-card' 로 말한다", async () => {
  const built = createCaps();
  built.band.doc.getElementById = ((real) => (id) => (
    id === "jobCand-" + NOTICE ? null : real(id)
  ))(built.band.doc.getElementById);
  const runner = createSelftestRunner(built.caps);
  registerJobProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  assert.equal(report.results.job_inherited.opening_marker_immediate, "no-card");
});

/* ────────────────── job_active_card — 대조 보존 ────────────────── */

test("job_active_card — 정체·메뉴·연결 상태와 「선택이 아니다」", async () => {
  const { report } = await runFull();
  const j = report.results.job_active_card;
  assert.equal(j.action_name, "공고서");
  assert.equal(j.active_tpl, "공고서.hwpx");
  assert.equal(j.menu_btn_in_active, true);
  assert.equal(j.menu_btn_count, 1);
  assert.equal(j.menu_open, true);
  assert.equal(j.menu_closed, true);
  assert.deepEqual(j.menu_items, [
    "open:C:\\t\\공고서.hwpx:열기",
    "reveal:C:\\t\\공고서.hwpx:폴더에서 보기",
  ]);
  assert.equal(j.warn_conn, "템플릿 없음");
  /* 도달 보장 축 — 정상 상태에선 조용하고(음성 극), 구획이 통째로 숨어도 액션바가 세운다. */
  assert.equal(j.conn_quiet_when_ok, true);
  assert.equal(j.cands_hidden_when_no_data, true);
  assert.equal(j.cand_cards_when_no_data, 0);
  assert.equal(j.conn_text_no_data, "템플릿 없음");
  assert.equal(j.relink_visible_no_data, true);
  /* 경고 카드 클릭 = 안내 다이얼로그, 취소하면 **발신 0건**. */
  assert.equal(j.warn_redirect_modal, true);
  assert.ok(j.warn_modal_body.includes("선택") && j.warn_modal_body.includes("다시 연결"));
  assert.deepEqual(JSON.parse(j.warn_click_sends), []);
});

test("job_active_card — relink 가 hidden 만 지워지고 안 그려지면 거짓 통과하지 않는다", async () => {
  const { report } = await runFull({ relinkInvisible: true });
  const j = report.results.job_active_card;
  assert.equal(j.conn_text_no_data, "템플릿 없음", "hidden 은 지워졌다(속성만 보는 검사는 통과)");
  assert.equal(j.relink_visible_no_data, false, "offsetParent 로 보면 화면에 없다 — 도달 보장 소멸");
});

test("job_active_card — 경고 카드가 선택을 보내면 발신열이 그것을 증언한다(음성 극)", async () => {
  const { report } = await runFull({ warnCardSelects: true });
  const j = report.results.job_active_card;
  assert.equal(j.warn_redirect_modal, false);
  assert.deepEqual(JSON.parse(j.warn_click_sends), ["select_job"]);
});

/* ────────────────── job_mirror — 가장 촘촘한 대조 ────────────────── */

test("job_mirror — 본문 존 한 줄과 잠금 결속 두 값", async () => {
  const { report } = await runFull();
  const j = report.results.job_mirror;
  assert.equal(j.mirror_no_table, true);
  assert.equal(j.mirror_banner_empty, true);
  assert.ok(j.mirror_line.includes("빈 값") && j.mirror_line.includes("낙찰율"));
  assert.equal(j.mirror_line_has_blank_flag, true);
  assert.equal(j.mirror_preview_exit, true);
  /* 두 값 대조 — 한 값만 재면 「늘 열려 있는 버튼」도 초록이다. */
  assert.equal(j.mirror_trigger_disabled, false);
  assert.equal(j.mirror_trigger_locked, true);
  assert.equal(j.restate_shown, true);
  assert.equal(j.restate_no_namelist, true);
});

test("job_mirror — 필터 표면·표 의미·낙관 토글", async () => {
  const { report } = await runFull();
  const j = report.results.job_mirror;
  assert.equal(j.tbl_rows, 1);
  assert.equal(j.row_role, null, "tr 에 checkbox role 이 남으면 native row 의미를 덮는다");
  assert.equal(j.row_selected, "true");
  assert.equal(j.row_checkbox, true);
  assert.equal(j.row_doccell_display, "flex");
  assert.equal(j.lead_hint, "선택하면 파일명이 정해집니다");
  assert.equal(j.repeated_placeholder, 0);
  assert.equal(j.amount_align, "right");
  assert.ok(j.amount_nums.includes("tabular-nums"));
  assert.equal(j.tbl_mark, "전산");
  assert.equal(j.ficos, 2);
  assert.ok(j.chips_text.includes("「전산」"));
  assert.equal(j.branch_prune, true);
  assert.deepEqual(j.filter_role_labels, ["필터", "가지", "선택"]);
  assert.notEqual(j.definition_bg, j.branch_bg);
  assert.equal(j.branch_border_style, "solid");
  assert.equal(j.strip_shown, true);
  assert.ok(j.strip_text.includes("doc-002.hwpx"));
  assert.equal(j.strip_bg, j.branch_bg);
  assert.equal(j.strip_unsel, true);
  assert.ok(j.sel_line.includes("정의 밖 1"));
  /* 낙관 표지는 즉시 뒤집히고 재클릭은 **화면의 현재 상태**를 쓴다. */
  assert.equal(j.row_optimistic_off, true);
  assert.equal(j.row_optimistic_on, true);
  assert.deepEqual(j.row_toggle_values, [false, true], "지연 회수가 최종 의도열을 확정한다");
  assert.equal(j.panel_shell_immediate, true);
});

test("job_mirror — React 열 패널은 닫으면 언마운트된다(양성/음성)", async () => {
  const positive = await runFull();
  assert.equal(positive.report.results.job_mirror.panel_hidden, true);
  const negative = await runFull({ panelCloseSticks: true });
  assert.equal(
    negative.report.results.job_mirror.panel_hidden, false,
    "React colpanel이 닫힌 뒤에도 남는 회귀를 잡습니다.",
  );
});

test("job_mirror — 드리프트·파일명 토큰 danger 가 같은 자리에 서고 재진술이 숨는다", async () => {
  const { report } = await runFull();
  const j = report.results.job_mirror;
  assert.equal(j.drift_banner, true);
  assert.equal(j.drift_fix_link, true);
  assert.equal(j.drift_no_line, true);
  assert.equal(j.restate_hidden_on_drift, true);
  assert.equal(j.token_banner, true);
  assert.equal(j.token_fix_link, true);
  assert.equal(j.token_no_line, true);
  assert.ok(j.token_banner_text.includes("납품기한"));
  assert.equal(j.token_restate_hidden, true);
});

test("job_mirror — 퇴장 한 줄: 생성 태 다섯은 말하고 거절·진행 둘은 침묵한다", async () => {
  const { report } = await runFull();
  const j = report.results.job_mirror;
  for (const key of [
    "exit_cancelled_untouched", "exit_cancelled_mixed", "exit_prebatch_failed",
    "exit_completed", "exit_partial_failure",
  ]) {
    assert.ok(j[key].includes("발주요청서"), key);
    assert.ok(j[key].length > 0, key);
  }
  assert.ok(j.exit_cancelled_untouched.includes("미착수 12건"));
  assert.ok(j.exit_partial_failure.includes("2개 실패"));
  /* 생성이 아닌 태에는 적을 것이 없다 — 지어내지 않는다(음성 극 둘). */
  assert.equal(j.exit_rejected, "");
  assert.equal(j.exit_running, "");
  /* 요약 없는 실행 결과는 수치를 지어내지 않고 모른다고 적는다. */
  assert.ok(j.exit_missing_summary.includes("알 수 없습니다"));
});

test("job_mirror — 가드 본문은 있는 손실만 열거한다(과경고 금지)", async () => {
  const { report } = await runFull();
  const j = report.results.job_mirror;
  assert.ok(j.guard_body.includes("직접 선택 3행"));
  assert.ok(j.guard_body.includes("정의 매치 2") && j.guard_body.includes("정의 밖 1"));
  assert.ok(j.guard_body.includes("데이터를 바꾸면"));
  assert.ok(j.guard_body.includes("직전 필터 재적용"));
  assert.equal(j.guard_body.includes("빈 값 확인"), false);
  /* 음성 극 — 없는 손실을 열거하면 가드가 거짓말을 한다. */
  assert.equal(j.guard_body_minimal.includes("직전 필터 재적용"), false);
  assert.equal(j.guard_body_minimal.includes("정의 밖"), false);
  assert.equal(j.data_guard_wired, true);
  assert.ok(j.ow_body.includes("덮어쓰기 3") && j.ow_body.includes("새로 만들기 7"));
  assert.ok(j.ow_body.includes("a.hwpx"));
});

test("job_mirror — 직전 필터 재적용은 양 분기를 다 핀한다", async () => {
  const { report } = await runFull();
  const j = report.results.job_mirror;
  assert.equal(j.reapply_shown, true);
  assert.equal(j.reapply_hidden, true, "reapply_available=false 면 버튼이 사라진다");
  assert.ok(j.reapply_title.includes("(공고명) 포함 「전산」"), "설치할 정의를 업고 있다");
});

test("job_mirror — 클릭 부재판별력·초점 복귀·발신·삼킨 푸시", async () => {
  const { report, band } = await runFull();
  const j = report.results.job_mirror;
  /* 「발신 0」을 배선 부재로 읽기 전에 클릭이 이벤트까지 갔는지 먼저 가른다. */
  assert.equal(j.mirror_trigger_disabled_at_click, false);
  assert.equal(j.mirror_click_seen, true);
  assert.deepEqual(j.mirror_preview_dispatch.map((d) => d.action), ["preview_open"]);
  assert.equal(
    j.mirror_preview_dispatch.some((d) => d.action === "ack_field" || d.action === "unack_field"),
    false, "죽은 액션은 발신되지 않는다",
  );
  assert.equal(j.mirror_focus_target_state, "ready");
  assert.equal(j.mirror_preview_focus, "jobMirrorPreviewOpen");
  assert.equal(j.edit_closes_sheets, true);
  assert.equal(j.job_grid_wide.split(" ").length, 2, "패널을 900px 너머로 고정하면 2열이다");
  /* 삼킨 푸시는 배열로 증언한다(조용한 격리 금지). 이식 모델에서 이 창이 볼 수 있는 것은
     **주입 능력을 통과한 푸시뿐**이므로, 호스트가 늦게 쏘는 refresh 푸시를 같은 능력으로
     흘리지 않으면 이 증거는 영영 빈다 — N-09 중앙 seam 요청으로 보고서에 적혀 있다. */
  assert.ok(Array.isArray(j.mirror_pushes));
  assert.deepEqual(j.mirror_pushes, []);
  /* 창이 닫힌 뒤 주입 push 가 복원됐다 — 뒤 프로브(job_result)의 구동이 대역에 닿는다. */
  assert.ok(band.hostPushes.some((p) => p.job === "둘째"));
});

test("job_mirror — 트리거가 잠긴 채 눌리면 이벤트가 없고 그 사실이 남는다(음성 극)", async () => {
  const built = createCaps();
  const trigger = built.band.el.previewOpen;
  /* 렌더가 무엇을 하든 트리거는 잠긴 채로 둔다 = can_open 결속이 끊긴 회귀. */
  Object.defineProperty(trigger, "disabled", { get: () => true, set: () => {} });
  const runner = createSelftestRunner(built.caps);
  registerJobProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  const j = report.results.job_mirror;
  assert.equal(j.mirror_trigger_disabled, true, "미리볼 문서가 있는데 출구가 잠겼다");
  assert.equal(j.mirror_trigger_disabled_at_click, true);
  assert.equal(j.mirror_click_seen, false, "비활성 요소의 click() 은 이벤트를 만들지 않는다");
  assert.deepEqual(j.mirror_preview_dispatch, [], "그래서 발신 0 은 배선 부재가 아니다");
  assert.equal(j.mirror_focus_target_state, "disabled", "복귀 불가 사유가 남는다");
  assert.notEqual(j.mirror_preview_focus, "jobMirrorPreviewOpen");
});

/* ────────────────── job_result — 처분 4분기 ────────────────── */

test("job_result — 3태·증거·강등과 §2.18 처분 네 갈래", async () => {
  const { report } = await runFull();
  const j = report.results.job_result;
  assert.equal(j.shown, true);
  assert.equal(j.state, "partiallyCompleted");
  assert.equal(j.level, "danger");
  assert.ok(j.title.includes("2개 성공"));
  assert.equal(j.fail_row, true);
  assert.equal(j.fail_identity, true);
  assert.equal(j.undiagnosed, true);
  assert.equal(j.failed_sel_shown, true);
  assert.ok(j.failed_sel_label.includes("1건만 선택"));
  assert.equal(j.evidence_shown, true);
  assert.equal(j.evidence_open_survives_rerender, true);
  /* 행 0개·전량 실패에서도 복구 행동은 남고, 없는 행을 지어내지 않는다. */
  assert.equal(j.rowless_recovery_shown, true);
  assert.ok(j.rowless_recovery_label.includes("3건만 선택"));
  assert.equal(j.rowless_no_fake_rows, true);
  assert.equal(j.stale_shown, true);
  assert.equal(j.alive_after_stale, true);
  /* ① 개명 = 전환이 아니다(결과 유지·행동 유지) */
  assert.equal(j.renamed_keeps_result, true);
  assert.equal(j.renamed_rename_shown, true);
  assert.equal(j.renamed_failedsel_shown, true);
  /* ② 작업 전환 = 초기화 + 퇴장 한 줄(주체·수치·경로) */
  assert.equal(j.switch_resets_result, true);
  assert.ok(j.switch_exit_line.includes("2개 성공") && j.switch_exit_line.includes("1개 실패"));
  assert.equal(j.switch_exit_line.includes("3건 생성"), false, "대상 수는 만들어진 수가 아니다");
  assert.ok(j.switch_exit_line.includes("공고서(수정)") && j.switch_exit_line.includes("D:\\out"));
  /* ③ 선택 변경 = 강등 유지 */
  assert.equal(j.selection_change_keeps_result, true);
  assert.equal(j.selection_change_demotes, true);
  /* ④ 데이터 교체 = 초기화 + 퇴장 한 줄. 판정은 마운트 세대이지 표시 라벨이 아니다. */
  assert.equal(j.data_swap_label_unchanged, true);
  assert.equal(j.data_swap_resets_result, true);
  assert.ok(j.data_swap_exit_line.includes("D:\\out"));
  /* 주체 방어 — 남의 작업을 겨누는 버튼은 서지 않고 증거는 남는다. */
  assert.equal(j.foreign_rename_hidden, true);
  assert.equal(j.foreign_failedsel_hidden, true);
  assert.equal(j.foreign_evidence_alive, true);
  assert.equal(j.foreign_stale_names_owner, true);
});

test("job_result — 잠금·폴더 두 극·닫기 착지·거절 태", async () => {
  const { report } = await runFull();
  const j = report.results.job_result;
  assert.equal(j.busy_lock_declared, true);
  /* display:flex 가 UA [hidden] 을 이기는 결함 클래스라 계산 스타일로 두 극을 잰다. */
  assert.equal(j.folder_hidden_while_running, true);
  assert.equal(j.folder_shown_on_result, true);
  assert.equal(j.closed, true);
  assert.ok(["jobGenBtn", "jobResultZone"].includes(j.close_focus), j.close_focus);
  /* 명시 파기는 퇴장 한 줄을 남기지 않는다 — **부재**를 단언하는 자리. */
  assert.equal(j.close_runlog_last, "아직 기록이 없습니다.");
  assert.equal(j.runlog_collapsed, true);
  assert.equal(j.runlog_last_visible, true);
  /* 실행 전 거절은 결과 자리를 비워 두지 않는다. */
  assert.equal(j.reject_state, "rejected");
  assert.ok(j.reject_text.includes("빈 값"));
  assert.equal(j.reject_gen, 1);
  assert.ok(j.reject_log.includes("빈 값"));
  assert.equal(j.reject_hidden, false);
  assert.ok(j.runlog_last.includes("빈 값"));
  assert.deepEqual(j.reject_pushes, []);
});

test("job_result — 저장 폴더 줄이 [hidden] 을 이기면 잡힌다(음성 극)", async () => {
  const { report } = await runFull({ folderHiddenLoses: true });
  const j = report.results.job_result;
  assert.equal(j.folder_hidden_while_running, false, "진행 태에서 저장 폴더 줄이 남아 있다");
  assert.equal(j.folder_shown_on_result, true);
});

/* ────────────────── job_density_narrow — resize 괄호 ────────────────── */

test("job_density_narrow — 호스트가 창을 좁히고 넓히며 1열을 잰다", async () => {
  const { report, band, requests } = await runFull();
  const narrow = report.results.job_density_narrow;
  assert.deepEqual(Object.keys(narrow), ["columns", "panel"]);
  assert.equal(narrow.columns.split(" ").length, 1);
  assert.ok(narrow.panel <= 900, `분기 폭(container 900px)을 안 밟았습니다: ${narrow.panel}`);
  /* 앞의 좁힘과 뒤의 복귀가 **둘 다** 호스트 요청으로 나갔다. */
  assert.deepEqual(band.resizes, [
    { width: 900, height: 820 },
    { width: 1440, height: 900 },
  ]);
  assert.deepEqual(requests.map((r) => r.op), ["window_resize", "window_resize"]);
  /* 넓은 극은 job_mirror 가 진다 — 두 값이 한 쌍이다. */
  assert.equal(report.results.job_mirror.job_grid_wide.split(" ").length, 2);
});

test("job_density_narrow — 측정이 실패해도 창은 복귀한다(정리는 건너뛰지 않는다)", async () => {
  const built = createCaps();
  const realGet = built.band.doc.getElementById;
  built.band.doc.getElementById = (id) => {
    if (id === "jobDataGrid") throw new Error("격자 소실");
    return realGet(id);
  };
  const runner = createSelftestRunner(built.caps);
  registerJobProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  const failure = report.errors.find((e) => e.probe === "job_density_narrow");
  assert.ok(failure, "측정 실패가 보고되지 않았습니다.");
  assert.equal(Object.prototype.hasOwnProperty.call(report.results, "job_density_narrow"), false);
  assert.deepEqual(built.band.resizes, [
    { width: 900, height: 820 },
    { width: 1440, height: 900 },
  ], "창을 좁힌 채로 두면 뒤 클러스터가 전부 오염된다");
});

test("정리 실패는 시끄럽다 — 호스트가 복귀 resize 를 거절하면 보고서가 붉어진다", async () => {
  const built = createCaps({
    host(op, payload) {
      if (op === "window_resize" && payload.width === 1440) throw new Error("창 복귀 거절");
      return null;
    },
  });
  const runner = createSelftestRunner(built.caps);
  registerJobProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  const teardownError = report.errors.find((e) => e.phase === "teardown");
  assert.ok(teardownError, "정리 실패가 보고되지 않았습니다.");
  assert.equal(teardownError.code, "teardown_failed");
  assert.match(teardownError.message, /창 복귀 거절/);
  assert.equal(report.ok, false);
  assert.match(runner.toEvidence(report).error, /teardown_failed/);
});

/* ────────────────── 실패는 값이 되지 않는다 ────────────────── */

test("서비스 주입이 없으면 조용히 넘어가지 않는다", async () => {
  const built = createCaps({ services: {} });
  const runner = createSelftestRunner(built.caps);
  registerJobProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  assert.equal(report.ok, false);
  assert.equal(report.results.job_data_first, undefined);
  const failure = report.errors.find((e) => e.probe === "job_data_first");
  assert.equal(failure.code, "contract_violation");
  assert.match(failure.message, /주입되지 않은 서비스/);
  assert.match(failure.message, /Nav/);
});

test("프로브가 던지면 그 키는 결과에 실리지 않는다 — 모양만 맞는 값이 성공인 척하지 않는다", async () => {
  const built = createCaps();
  const realGet = built.band.doc.getElementById;
  built.band.doc.getElementById = (id) => {
    if (id === "jobMirrorLine") throw new Error("본문 존 소실");
    return realGet(id);
  };
  const runner = createSelftestRunner(built.caps);
  registerJobProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  const failure = report.errors.find((e) => e.probe === "job_mirror");
  assert.equal(failure.code, "probe_threw");
  assert.match(failure.message, /본문 존 소실/);
  assert.equal(Object.prototype.hasOwnProperty.call(report.results, "job_mirror"), false);
  /* 레거시는 `out.error` 를 담은 정상 모양 값을 그대로 내보냈다 — 러너 계약이 그 길을 끊는다. */
  assert.match(runner.toEvidence(report).error, /probe_threw/);
});

/* ────────────────────────── 음성 ────────────────────────── */

test("음성 — 전역 쓰기·전역 조회·스태시·__hwpxTest 부재", () => {
  assert.equal(/(?:^|\s)window\.[A-Za-z_$][A-Za-z0-9_$]*\s*=/m.test(SRC), false);
  assert.equal(/globalThis\s*\.\s*[A-Za-z_$][A-Za-z0-9_$]*\s*=/.test(SRC), false);
  assert.equal(SRC.includes("__hwpxTest"), false);
  assert.equal(/window\.__/.test(SRC), false);
  assert.equal(/globalThis\.__/.test(SRC), false);
  /* 창 객체를 아예 이름으로 부르지 않는다 — 주석에도 없다(저장소 게이트가 주석을 읽는다). */
  assert.equal(/\bwindow\b/.test(SRC), false);
  /* 제품 전역을 **읽지도** 않는다 — 전부 ctx 주입이다. */
  for (const name of ["Nav", "Bridge", "Modal", "Popover", "JobScreen", "Intent", "Preserve"]) {
    assert.equal(new RegExp(`(?<![.\\w])window\\.${name}\\b`).test(SRC), false, name);
    assert.equal(new RegExp(`(?<![.\\w])globalThis\\.${name}\\b`).test(SRC), false, name);
  }
  /* 유일한 import 는 형제 러너 하나다(제품 그래프에 닿지 않는다). */
  const imports = SRC.match(/^import\s[^\n]*from\s+"[^"]+"/gm) || [];
  assert.equal(imports.length, 1);
  assert.match(imports[0], /"\.\.\/runner\.js"/);
  /* 렌더 구동은 늦은 결속으로만 — 주입 push 를 지역 이름으로 잡아 두고 쓰지 않는다.
     복원·전달 대상으로 잡는 두 자리만 예외이고 둘 다 주석으로 표시돼 있다. */
  const captures = SRC.match(/(?:const|let|var)\s+\w+\s*=\s*ctx\.push/g) || [];
  assert.equal(captures.length, 2, "push 선-포획은 복원용 두 자리뿐이어야 합니다.");
  assert.equal(/\bctx\.push\(/.test(SRC), true);
});

test("bare import 는 순수하다 — DOM·리스너·전역을 만들지 않는다", async () => {
  const before = Object.keys(globalThis).length;
  const again = await import(
    `../../frontend/src/selftest/probes/job.js?pure=${Date.now()}`
  );
  assert.equal(typeof again.createJobProbes, "function");
  assert.equal(Object.keys(globalThis).length, before);
  assert.equal(typeof globalThis.document, "undefined");
  assert.equal(typeof globalThis.window, "undefined");
  assert.deepEqual(Object.keys(again).sort(), [
    "C_CLUSTER", "C_KEYS", "createJobProbes", "registerJobProbes",
  ]);
  const defs = again.createJobProbes();
  assert.equal(defs.length, 6);
  for (const def of defs) {
    assert.equal(typeof def.name, "string");
    assert.equal(typeof def.run, "function");
  }
});
