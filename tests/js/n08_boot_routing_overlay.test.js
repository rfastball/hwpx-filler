/* N-08 레인 B — 클러스터 B(`frontend/src/selftest/probes/boot_routing_overlay.js`) 계약.
 *
 * 두 가지를 동시에 본다:
 *  ⓐ 이식이 **충실**한가 — app.py 의 상수 일곱과 호출 자리 열아홉이 값 모양·필드 순서·타이밍
 *     의도를 그대로 들고 왔는가, 그리고 **양성/음성 대조가 하나도 사라지지 않았는가**.
 *  ⓑ 규약이 **지켜졌는가** — 등록 메타데이터(시한·순서·호스트 요청·정리)가 러너 계약을
 *     통과하고, 모듈이 import 만으로는 아무 일도 하지 않는가.
 *
 * DOM 은 손으로 세운 최소 대역이다. 제품 전역은 하나도 세우지 않는다 — 프로브가 전역을
 * 읽지 않는다는 것이 이 이식의 요점이기 때문이다(읽으면 대역이 없어 즉시 터진다).
 *
 * 대역의 원칙: **계산 스타일을 클래스에서 유도한다**. `display` 는 `.modal.hidden → none`,
 * `.modal → flex` 로 풀리므로, 부록 B-9 결함(`.modal{display:flex}` 가 `.hidden` 을 이기는 것)을
 * 대역에서 실제로 재현할 수 있고 음성 대조가 그림이 아니라 실행이 된다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createSelftestRunner, HOST_OPS } from "../../frontend/src/selftest/runner.js";
import { keysForCluster } from "../../frontend/src/selftest/schema.js";
import {
  B_CLUSTER,
  B_KEYS,
  createBootRoutingOverlayProbes,
  registerBootRoutingOverlayProbes,
} from "../../frontend/src/selftest/probes/boot_routing_overlay.js";

const MODULE_URL = new URL(
  "../../frontend/src/selftest/probes/boot_routing_overlay.js", import.meta.url,
);
const SRC = readFileSync(MODULE_URL, "utf8");

/* ────────────────────────── 가상 시계 ────────────────────────── */

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

const DEFAULT_STYLE = Object.freeze({
  display: "block",
  fontSize: "13px", fontWeight: "400",
  backgroundColor: "rgb(255, 255, 255)", color: "rgb(0, 0, 0)",
  borderLeftColor: "rgba(0, 0, 0, 0)", opacity: "1",
  overflowY: "visible", overflow: "visible",
  scrollbarGutter: "auto", overscrollBehavior: "auto",
  position: "static", backdropFilter: "none",
  maxHeight: "none", fontFamily: "Pretendard", flexGrow: "0",
  width: "auto", height: "auto",
  borderRadius: "0px", boxShadow: "none",
  zIndex: "auto", pointerEvents: "auto",
  transformOrigin: "left top",
});

class FakeEl {
  constructor(tag, doc) {
    this.tagName = String(tag || "div").toUpperCase();
    this.doc = doc;
    this.id = "";
    this.textContent = "";
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.dataset = {};
    this.style = { cssText: "", display: "", height: "", transformOrigin: "" };
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.clientHeight = 0;
    this.disabled = false;
    this.hidden = false;
    this.type = "";
    this.selectionStart = null;
    this.selectionEnd = null;
    this.value = "";
    this.removed = 0;
    this.rect = { top: 0, left: 0, right: 0, bottom: 0, height: 0 };
    this._classes = new Set();
    this._style = {};
    this._pseudo = {};
    this._q = {};
    this._qa = {};
    this._html = "";
    this._listeners = new Map();
  }

  get className() { return Array.from(this._classes).join(" "); }

  set className(value) {
    this._classes = new Set(String(value || "").split(/\s+/).filter(Boolean));
  }

  get classList() {
    const set = this._classes;
    return {
      contains: (c) => set.has(c),
      add: (c) => set.add(c),
      remove: (c) => set.delete(c),
    };
  }

  get parentElement() { return this.parentNode; }

  get innerHTML() { return this._html; }

  set innerHTML(html) {
    this._html = String(html);
    if (this.doc) this.doc.absorb(this, this._html);
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    if (child.id && this.doc) this.doc.ids.set(child.id, child);
    return child;
  }

  removeChild(child) {
    this.children = this.children.filter((c) => c !== child);
    child.parentNode = null;
    if (child.id && this.doc) this.doc.ids.delete(child.id);
    return child;
  }

  remove() {
    this.removed += 1;
    if (this.parentNode) this.parentNode.removeChild(this);
    else if (this.id && this.doc) this.doc.ids.delete(this.id);
  }

  contains(node) {
    if (node === this) return true;
    return this.children.some((c) => c.contains(node));
  }

  focus() { if (this.doc) this.doc.activeElement = this; }

  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }

  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }

  setAttribute(name, value) { this.attributes[name] = value; }

  getBoundingClientRect() { return { ...this.rect }; }

  querySelector(sel) { return sel in this._q ? this._q[sel] : null; }

  querySelectorAll(sel) { return sel in this._qa ? this._qa[sel].slice() : []; }

  cloneNode() {
    const clone = new FakeEl(this.tagName, this.doc);
    clone.textContent = this.textContent;
    clone._qa = { button: (this._qa.button || []).map((b) => {
      const c = new FakeEl("button", this.doc);
      c.textContent = b.textContent;
      return c;
    }) };
    return clone;
  }

  addEventListener(type, fn, opts) {
    const list = this._listeners.get(type) || [];
    list.push({ fn, once: !!(opts && opts.once), capture: !!(opts && opts.capture) });
    this._listeners.set(type, list);
  }

  dispatchEvent(ev) {
    ev.target = ev.target || this;
    this.fire(ev);
    if (ev.bubbles) {
      let node = this.parentNode;
      while (node) { node.fire(ev); node = node.parentNode; }
    }
    if (this.doc) this.doc.fire(ev, !ev.bubbles);
    return true;
  }

  fire(ev) {
    const list = this._listeners.get(ev.type) || [];
    this._listeners.set(ev.type, list.filter((l) => !l.once));
    for (const l of list) l.fn(ev);
  }

  click() { this.dispatchEvent({ type: "click", bubbles: true }); }
}

function fakeEvent(type, init) {
  return { type, bubbles: !!(init && init.bubbles), ...(init || {}) };
}

/** 셸 대역. 실 index.html 의 **id 격자**만 세우고 나머지는 세우지 않는다. */
function createDom(options) {
  const conf = options || {};
  const doc = {
    title: conf.title === undefined ? "문서나르미" : conf.title,
    activeElement: null,
    ids: new Map(),
    _listeners: new Map(),
    _q: {},
    _qa: {},
  };

  const make = (tag, id, classes) => {
    const el = new FakeEl(tag, doc);
    if (id) { el.id = id; doc.ids.set(id, el); }
    if (classes) el.className = classes;
    return el;
  };

  const body = make("body");
  body.parentNode = null;
  doc.body = body;
  doc.documentElement = make("html");

  doc.createElement = (tag) => new FakeEl(tag, doc);
  doc.getElementById = (id) => (doc.ids.has(id) ? doc.ids.get(id) : null);
  doc.querySelector = (sel) => {
    if (sel in doc._q) return doc._q[sel];
    if (/^#[\w-]+$/.test(sel)) return doc.getElementById(sel.slice(1));
    return null;
  };
  doc.querySelectorAll = (sel) => (sel in doc._qa ? doc._qa[sel].slice() : []);
  doc.addEventListener = (type, fn, opts) => {
    const list = doc._listeners.get(type) || [];
    list.push({ fn, capture: !!(opts && opts.capture) });
    doc._listeners.set(type, list);
  };
  doc.dispatchEvent = (ev) => { doc.fire(ev, false); return true; };
  doc.fire = (ev, captureOnly) => {
    for (const l of doc._listeners.get(ev.type) || []) {
      if (captureOnly && !l.capture) continue;
      l.fn(ev);
    }
  };

  /* innerHTML 대역 — 프로브가 실제로 쓰는 마크업만 흡수한다(범용 파서가 아니다). */
  doc.absorb = (el, html) => {
    el.children.forEach((c) => { if (c.id) doc.ids.delete(c.id); });
    el.children = [];
    el._q = {};
    el._qa = {};
    el.scrollTop = 0;                        // 재구성은 스크롤을 0 으로 되돌린다(브라우저 그대로)
    const ids = html.match(/id="([^"]+)"/g) || [];
    for (const raw of ids) {
      const id = raw.slice(4, -1);
      const child = make(html.includes(`<input id="${id}"`) ? "input" : "button", id);
      el.appendChild(child);
      if (id === "preserveProbeInput") child.value = "abcdef";
      if (id === "__hOverlayInside") child.textContent = "inside";
    }
    if (html.includes("<th>")) {
      const th = make("th");
      th._style = { position: "sticky" };
      th.rect = { top: 12, left: 0, right: 100, bottom: 24, height: 12 };
      el._q.th = th;
      el.appendChild(th);
    }
    if (html.includes("track-btn")) {
      const buttons = ["폴더에서 보기", "경로 복사"].map((name) => {
        const b = make("button", "", "track-btn");
        b.setAttribute("aria-label", name);
        b.setAttribute("title", name);
        b._q.svg = new FakeEl("svg", doc);
        return b;
      });
      doc._qa[".track-btn"] = buttons;
      buttons.forEach((b) => el.appendChild(b));
    }
  };

  /* ── 셸 격자 ── */
  const navbtns = ["job", "library"].map((scr) => {
    const b = make("button", "", "navbtn");
    b.setAttribute("data-scr", scr);
    return b;
  });
  doc._qa[".navbtn"] = navbtns;
  doc._q[".navbtn"] = navbtns[0];

  const scrJob = make("div", "scr-job");
  if (conf.jobOn !== false) scrJob.classList.add("on");
  body.appendChild(scrJob);
  if (conf.homeAlive) {
    body.appendChild(make("div", "scr-home"));
    body.appendChild(make("div", "homeBrowser"));
  }

  const librarySurfaceIds = [
    "scr-library", "libraryViewTabs", "libraryModeFilters", "libraryFacets",
    "librarySearch", "libraryList", "libraryDetail", "libraryCount",
  ];
  const skipped = conf.missingLibraryId || null;
  for (const id of librarySurfaceIds) {
    if (id === skipped) continue;
    body.appendChild(make("div", id));
  }
  doc._qa["#libraryViewTabs [data-library-view]"] =
    (conf.viewTabs || ["all", "recent", "favorites", "needsAction"]).map((view) => {
      const b = make("button");
      b.dataset.libraryView = view;
      return b;
    });

  if (conf.dataPickerButton !== false) body.appendChild(make("button", "jobBtnPickData"));
  doc._qa["#tplSel option"] = (conf.tplOptions || []).map((value) => {
    const o = make("option");
    o.value = value;
    return o;
  });

  /* 존 캡션 표본(작업 화면 렌더의 소비) */
  doc._qa["#scr-job .zone-cap"] = (conf.zoneCaps || ["현재 데이터", "본문 확인"]).map((text) => {
    const el = make("div", "", "zone-cap");
    el.textContent = ` ${text} `;
    el._qa.button = [];
    el._style = { fontSize: "13px", fontWeight: "700" };
    return el;
  });
  doc._qa["#scr-job .zone-cap .znum"] = [];
  doc._q["#scr-job .zone-cap"] = doc._qa["#scr-job .zone-cap"][0] || null;
  doc._q[".scr-head h1"] = make("h1");
  doc._q[".scr-head h1"]._style = { fontSize: "22px", fontWeight: "700" };

  const genBtn = make("button", "jobGenBtn");
  genBtn._style = { backgroundColor: "rgb(37, 110, 244)" };
  body.appendChild(genBtn);
  body.appendChild(make("div", "jobOutTrack"));
  body.appendChild(make("div", "editor-body"));

  /* ── 오버레이 포털 둘 + 모달 셋 (R3-01 · #410 개정 8) ──
     legacy 모달(txtEditModal)은 #overlayRoot, promise 다이얼로그(confirm·choose)는 React
     호스트 컨테이너 #reactOverlayHost 의 **직속** 자식이다 — 제품의 두-포털 형상 그대로를
     모델링해야 `overlay_children_owned` 의 양성이 새 가지(React 호스트 부모)를 실제로 밟는다. */
  const overlayRoot = make("div", "overlayRoot");
  body.appendChild(overlayRoot);
  const reactOverlayHost = make("div", "reactOverlayHost");
  body.appendChild(reactOverlayHost);

  const buildModal = (id, extras, host) => {
    const modal = make("div", id, "modal hidden");
    modal._style = { zIndex: "80" };
    const card = make("div", "", "modal-card");
    card.rect = { top: 40, left: 0, right: 400, bottom: 440, height: 400 };
    card.scrollHeight = 900;
    card.clientHeight = 400;
    modal._q[".modal-card"] = card;
    modal.appendChild(card);
    doc._q[`#${id} .modal-card`] = card;
    const actions = make("div", "", "modal-actions");
    actions.rect = { top: 300, left: 0, right: 400, bottom: 400, height: 40 };
    modal._q[".modal-actions"] = actions;
    card.appendChild(actions);
    (extras || []).forEach((childId) => {
      const child = make("button", childId);
      actions.appendChild(child);
    });
    (host || overlayRoot).appendChild(modal);
    return modal;
  };

  buildModal("txtEditModal", ["txtEditName"]);
  /* R4-02 — 프로브의 폼 모달 표적이 `promptModal` 로 옮겼다(txtEditModal 은 내용의 생산자가
     편집기 React 표면이라 열어 두는 것만으로는 안이 빈다). 이 창은 R3-01 이 React host 렌더로
     옮긴 뒤 골격이 **상주**라 그 자리를 이어받을 수 있다. */
  buildModal("promptModal", ["promptModalInput", "promptModalCancel", "promptModalOk"],
    reactOverlayHost);
  const confirmModal = buildModal(
    "confirmModal", ["confirmModalCancel", "confirmModalOk"], reactOverlayHost,
  );
  const confirmBody = make("div", "confirmModalBody");
  confirmModal._q[".modal-card"].appendChild(confirmBody);
  buildModal("chooseModal", ["chooseModalCancel", "chooseModalAlt", "chooseModalOk"], reactOverlayHost);
  doc.getElementById("chooseModalOk").className = "primary";
  doc.getElementById("confirmModalOk").className = "primary";
  /* 15px 구획 역할의 정적 생존 표본(app.py:3086) — 모달 DOM 은 셸 레벨 상주라 여기 산다. */
  const sectionHead = make("h3");
  sectionHead._style = { fontSize: "15px", fontWeight: "700" };
  doc._q[".modal-card h3"] = sectionHead;

  doc._qa[".modal,.ctx-menu,.colpanel"] = [
    doc.getElementById("txtEditModal"),
    doc.getElementById("promptModal"),
    doc.getElementById("confirmModal"),
    doc.getElementById("chooseModal"),
  ];
  if (conf.strayOverlayChild) {
    const stray = make("div", "", "ctx-menu");
    body.appendChild(stray);
    doc._qa[".modal,.ctx-menu,.colpanel"].push(stray);
  }

  /* ── 작업대 카드(클러스터 D 의 DOM — 여기선 재질 표본으로만 빌린다) ── */
  const wbCard = make("div", "wbCard", "wb-preview");
  wbCard._style = {
    maxHeight: "320px", overflowY: "auto", fontFamily: "GulimChe, 굴림체", flexGrow: "0",
  };
  body.appendChild(wbCard);
  const wbDots = make("div", "wbDots");
  wbDots._style = { overflow: "visible" };
  body.appendChild(wbDots);
  doc._q["#wbDots .wc-dot"] = null;

  /* ── 창 대역 ── */
  const win = {
    innerWidth: conf.innerWidth === undefined ? 1440 : conf.innerWidth,
    innerHeight: conf.innerHeight === undefined ? 900 : conf.innerHeight,
    console: { error() {} },
    alert() {},
    Event: class { constructor(type, init) { Object.assign(this, fakeEvent(type, init)); } },
    KeyboardEvent: class { constructor(type, init) { Object.assign(this, fakeEvent(type, init)); } },
    PointerEvent: class { constructor(type, init) { Object.assign(this, fakeEvent(type, init)); } },
    FocusEvent: class { constructor(type, init) { Object.assign(this, fakeEvent(type, init)); } },
    getComputedStyle(el, pseudo) {
      if (pseudo) {
        const table = {
          "::-webkit-scrollbar": { width: "8px" },
          "::-webkit-scrollbar-button": { display: "none", width: "0px", height: "0px" },
          "::before": { width: "14px", height: "14px" },
        };
        return { ...DEFAULT_STYLE, ...(table[pseudo] || {}), ...((el && el._pseudo[pseudo]) || {}) };
      }
      const base = { ...DEFAULT_STYLE, ...(el ? el._style : {}) };
      /* CSS 규칙 유도: `.modal.hidden{display:none}` 가 `.modal{display:flex}` 를 이긴다. */
      if (el && el.classList.contains("hidden")) base.display = conf.hiddenLosesToFlex ? "flex" : "none";
      else if (el && el.classList.contains("modal")) base.display = "flex";
      if (el && el.classList.contains("jcard")) {
        base.backgroundColor = "rgb(250, 250, 250)";
        if (el.getAttribute("aria-current") === "true") {
          base.backgroundColor = "rgb(235, 242, 255)";
          base.borderLeftColor = "rgb(37, 110, 244)";
        }
      }
      if (el && el.classList.contains("tblwrap")) {
        base.overflowY = "auto";
        base.scrollbarGutter = "stable both-edges";
        base.overscrollBehavior = "contain";
      }
      if (el && el.classList.contains("jobtbwrap")) base.overflowY = "auto";
      if (el && el.tagName === "TH") {
        base.position = "sticky";
        base.backdropFilter = "blur(14px)";
        base.backgroundColor = "rgba(255, 255, 255, 0.8)";
      }
      if (el && el.classList.contains("wc-render")) {
        base.maxHeight = "320px";
        base.overflowY = "auto";
        base.fontFamily = "GulimChe, 굴림체";
        base.flexGrow = "0";
      }
      if (el && el.classList.contains("wc-dot")) { base.width = "24px"; base.height = "24px"; }
      if (el && el.classList.contains("ctx-menu")) {
        base.zIndex = "60";
        base.borderRadius = "12px";
        base.boxShadow = "0 12px 32px rgba(0,0,0,.18)";
      }
      if (el && el.id === "jobGenBtn") {
        base.backgroundColor = el.disabled ? "rgb(230, 233, 238)" : "rgb(37, 110, 244)";
        base.opacity = "1";
      }
      return base;
    },
    visualViewport: { height: conf.innerHeight === undefined ? 900 : conf.innerHeight },
    pywebview: { api: { initial: () => Promise.resolve({}) } },
  };

  return { doc, win, body, overlayRoot, navbtns };
}

/* ────────────────────────── 서비스 대역 ────────────────────────── */

/** 실 Modal 헬퍼의 계약을 재현한다: `.modal` 가드(loud 거절) · 스택 · Escape/Tab · 단일 실행 직렬화. */
function createServices(dom, options) {
  const conf = options || {};
  const doc = dom.doc;
  const win = dom.win;
  const stack = [];
  let pendingDialog = null;
  const popovers = [];

  const focusablesOf = (id) => ({
    confirmModal: ["confirmModalCancel", "confirmModalOk"],
    chooseModal: ["chooseModalCancel", "chooseModalAlt", "chooseModalOk"],
    promptModal: ["promptModalInput", "promptModalCancel", "promptModalOk"],
    txtEditModal: ["txtEditName"],
  }[id] || []);

  const closeAllPopovers = () => {
    for (const p of popovers.slice()) if (p.isOpen()) p.close();
  };

  const finishClose = (el) => {
    el.classList.remove("is-closing");
    el.classList.add("hidden");
    const entry = stack.find((s) => s.el === el);
    if (entry) {
      stack.splice(stack.indexOf(entry), 1);
      if (entry.returnFocus) entry.returnFocus.focus();
    }
  };

  const Modal = {
    open(id, opts) {
      const el = doc.getElementById(id);
      if (!el || !el.classList.contains("modal")) {
        win.console.error(`Modal.open: '${id}' 는 .modal 이 아닙니다 — 열지 않습니다.`);
        return false;
      }
      closeAllPopovers();
      const returnFocus = (opts && opts.returnFocus) || doc.activeElement;
      stack.push({ el, returnFocus });
      el.classList.remove("hidden");
      el.classList.remove("is-closing");
      if (opts && opts.initialFocus) opts.initialFocus.focus();
      return true;
    },
    close(id) {
      const el = doc.getElementById(id);
      if (!el || !el.classList.contains("modal")) {
        win.console.error(`Modal.close: '${id}' 는 .modal 이 아닙니다 — 닫지 않습니다.`);
        return false;
      }
      el.classList.add("is-closing");
      return true;
    },
    confirm(spec) {
      const el = doc.getElementById("confirmModal");
      /* 골격 검증이 pendingDialog 를 세우기 **전** 이라 교착이 생기지 않는다(Codex P2). */
      if (!el.classList.contains("modal")) {
        win.console.error("Modal.confirm: confirm root 가 불량입니다.");
        return Promise.resolve(false);
      }
      if (pendingDialog) {
        win.alert("이미 확인 창이 열려 있습니다.");
        return Promise.resolve(conf.leakyReentry ? true : false);
      }
      doc.getElementById("confirmModalBody").textContent = spec.body;
      const ok = doc.getElementById("confirmModalOk");
      ok.textContent = spec.confirmLabel || "확인";
      if (spec.danger) { ok.classList.add("danger"); ok.classList.remove("primary"); }
      else if (!conf.dangerLeaks) { ok.classList.remove("danger"); ok.classList.add("primary"); }
      Modal.open("confirmModal");
      doc.getElementById("confirmModalCancel").focus();
      return new Promise((resolve) => {
        pendingDialog = resolve;
        const settleWith = (value) => {
          pendingDialog = null;
          Modal.close("confirmModal");
          resolve(value);
        };
        ok.addEventListener("click", () => settleWith(true), { once: true });
        doc.getElementById("confirmModalCancel")
          .addEventListener("click", () => settleWith(false), { once: true });
      });
    },
    choose(spec) {
      const ids = ["chooseModalOk", "chooseModalAlt", "chooseModalCancel"];
      ids.forEach((id, i) => { doc.getElementById(id).textContent = spec.choices[i].label; });
      if (conf.hiddenChooseButton) {
        doc.getElementById("chooseModalAlt")._style = { display: "none" };
      }
      Modal.open("chooseModal");
      doc.getElementById("chooseModalCancel").focus();
      return new Promise((resolve) => {
        ids.forEach((id, i) => {
          doc.getElementById(id).addEventListener("click", () => {
            Modal.close("chooseModal");
            resolve(spec.choices[i].value);
          }, { once: true });
        });
      });
    },
  };

  doc.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      if (ev.isComposing) return;                        // IME 조합 중 Escape 는 삼킨다
      const top = stack[stack.length - 1];
      if (top) Modal.close(top.el.id);
      return;
    }
    if (ev.key === "Tab") {
      const top = stack[stack.length - 1];
      if (!top) return;
      const order = focusablesOf(top.el.id);
      const at = order.indexOf(doc.activeElement && doc.activeElement.id);
      if (at === order.length - 1 && !conf.brokenTrap) doc.getElementById(order[0]).focus();
    }
  });

  /* transitionend(opacity) 로 퇴장을 완료시키는 실 Modal 의 리스너와 동형. */
  for (const id of ["txtEditModal", "promptModal", "confirmModal", "chooseModal"]) {
    const el = doc.getElementById(id);
    el._q[".modal-card"].addEventListener("transitionend", (ev) => {
      if (ev.propertyName !== "opacity") return;
      if (!conf.brokenFinish) finishClose(el);
    });
  }

  const Popover = {
    register(spec) {
      popovers.push(spec);
      return () => {
        const at = popovers.indexOf(spec);
        if (at >= 0) popovers.splice(at, 1);
      };
    },
    place(pop, trigger) {
      pop.style.transformOrigin = "left bottom";
      pop.rect = { top: 40, left: 20, right: 280, bottom: 200, height: 160 };
      return { placement: "top", trigger };
    },
    closeAll: closeAllPopovers,
  };

  let downTarget = null;
  doc.addEventListener("pointerdown", (ev) => {
    downTarget = ev.button === 0 ? ev.target : null;
  });
  doc.addEventListener("pointerup", (ev) => {
    if (!downTarget) return;
    for (const p of popovers.slice()) {
      if (p.isOpen() && !p.contains(ev.target) && !p.contains(downTarget)) p.close();
    }
    downTarget = null;
  });
  doc.addEventListener("focusout", (ev) => {
    for (const p of popovers.slice()) if (p.isOpen() && !p.contains(ev.relatedTarget)) p.close();
  });
  doc.addEventListener("scroll", () => { closeAllPopovers(); }, { capture: true });

  const Preserve = {
    around(fn) {
      const active = doc.activeElement;
      const keep = active
        ? { id: active.id, start: active.selectionStart, end: active.selectionEnd }
        : null;
      const scrolls = [];
      for (const el of dom.body.children) {
        if (el.getAttribute("data-preserve-scroll") !== null) scrolls.push([el.id, el.scrollTop]);
      }
      fn();
      if (conf.brokenPreserve) return;
      for (const [id, top] of scrolls) {
        const el = doc.getElementById(id);
        if (el) el.scrollTop = top;
      }
      if (keep && keep.id) {
        const el = doc.getElementById(keep.id);
        if (el) { el.focus(); el.setSelectionRange(keep.start, keep.end); }
      }
    },
  };

  const navigations = [];
  const Nav = { go(screen, opts) { navigations.push([screen, opts]); } };

  const bridgeCalls = [];
  const Bridge = {
    call(screen, action) {
      bridgeCalls.push([screen, action]);
      if (conf.bridgeCallFails === screen) return Promise.reject(new Error("registry 거절"));
      return Promise.resolve(true);
    },
    initial(screen) {
      if (conf.emptySnapshotFor === screen) return Promise.resolve({});
      return Promise.resolve({ screen, ok: true });
    },
  };

  const PathTrack = {
    affordances(path, opts) {
      return `<span class="track-btn" data-path="${path}" data-only="${opts.only.join(",")}"></span>`;
    },
  };

  return {
    services: { Modal, Popover, Preserve, Nav, Bridge, PathTrack },
    navigations, bridgeCalls, popovers, stack,
  };
}

/* ────────────────────────── 능력 조립 ────────────────────────── */

function createCaps(overrides) {
  const conf = overrides || {};
  const clock = createClock();
  const dom = createDom(conf.dom);
  const wired = createServices(dom, conf.services);
  const requests = [];
  const pushes = [];

  const push = (screen, snapshot) => {
    pushes.push([screen, snapshot]);
    if (conf.pushThrows) throw new Error("render 붕괴");
    /* 실 render() 는 innerHTML 을 다시 짓고 Preserve.around 가 스크롤을 되돌린다. */
    const box = dom.doc.getElementById("editor-body");
    if (box) {
      const keep = box.scrollTop;
      box.scrollTop = 0;
      if (!(conf.services && conf.services.brokenPreserve)) box.scrollTop = keep;
    }
  };

  const caps = {
    doc: dom.doc,
    win: dom.win,
    push,
    services: conf.services === null ? {} : wired.services,
    host: {
      provides: HOST_OPS.slice(),
      request(op, payload) {
        requests.push({ op, payload });
        if (op === "window_resize") {
          dom.win.innerWidth = payload.width;
          dom.win.innerHeight = payload.height;
          dom.win.visualViewport = { height: payload.height };
        }
        if (conf.host) return conf.host(op, payload);
        return null;
      },
    },
    now: clock.now,
    sleep: clock.sleep,
  };
  if (conf.noServices) caps.services = {};
  return { caps, clock, dom, wired, requests, pushes };
}

async function runFull(overrides) {
  const built = createCaps(overrides);
  const runner = createSelftestRunner(built.caps);
  registerBootRoutingOverlayProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  return { ...built, runner, report };
}

/* ────────────────────────── 표면 ────────────────────────── */

test("공개 표면 — 정확히 넷이고 export default 는 없다", async () => {
  const mod = await import(MODULE_URL);
  assert.deepEqual(Object.keys(mod).sort(), [
    "B_CLUSTER", "B_KEYS", "createBootRoutingOverlayProbes", "registerBootRoutingOverlayProbes",
  ]);
  assert.equal(B_CLUSTER, "B");
  assert.ok(Array.isArray(B_KEYS));
  assert.equal(typeof createBootRoutingOverlayProbes, "function");
  assert.equal(typeof registerBootRoutingOverlayProbes, "function");
  assert.equal(/export\s+default/.test(SRC), false);
  assert.equal(Object.isFrozen(B_KEYS), true);
});

test("키 전수가 스키마의 클러스터 B 와 정확히 같다", () => {
  assert.deepEqual(B_KEYS.slice().sort(), keysForCluster("B"));
  assert.equal(B_KEYS.length, 15);
  for (const k of [
    "title_dom", "nav_count", "tpl_options", "job_on", "home_screen_gone", "library_surface",
    "library_view_tabs", "data_picker_buttons", "action_roundtrip", "modal_a11y",
    "modal_confirm_serial", "preserve", "preserve_real", "milestone_h_wave1",
    "milestone_h_overlay",
  ]) {
    assert.ok(B_KEYS.includes(k), k);
  }
  /* 프로브가 실제로 내는 키의 합집합도 같아야 한다 — 선언만 맞고 방출이 빠지는 길을 막는다. */
  const emitted = createBootRoutingOverlayProbes().flatMap((p) => p.keys);
  assert.deepEqual(emitted.slice().sort(), keysForCluster("B"));
});

test("등록 — 러너 계약을 전수 통과하고 full 계획이 레거시 실행 순서로 선다", () => {
  const { caps } = createCaps();
  const runner = createSelftestRunner(caps);
  registerBootRoutingOverlayProbes(runner);
  assert.equal(runner.probes().length, 14, "modal_a11y 하나가 두 키를 내므로 15키 = 14프로브");

  assert.deepEqual(runner.plan("full").map((p) => p.name), [
    "title_dom", "nav_count", "tpl_options", "job_on",
    "home_screen_gone", "library_surface", "library_view_tabs", "data_picker_buttons",
    "action_roundtrip", "modal_a11y", "preserve", "preserve_real",
    "milestone_h_wave1", "milestone_h_overlay",
  ]);
  /* 이 클러스터는 full 전용이다 — 다른 모드의 계획에 새어 들지 않는다. */
  for (const mode of ["geometry_only", "theme_write", "font_scale_write"]) {
    assert.deepEqual(runner.plan(mode).map((p) => p.name), []);
  }
});

test("legacySite 가 app.py 호출 자리를 그대로 가리킨다 — 클러스터를 넘는 순서의 유일한 실", () => {
  const { caps } = createCaps();
  const runner = createSelftestRunner(caps);
  registerBootRoutingOverlayProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));

  assert.deepEqual(
    Object.fromEntries([...byName].map(([n, p]) => [n, p.legacySite])),
    {
      title_dom: 3716, nav_count: 3717, tpl_options: 3718, job_on: 3721,
      home_screen_gone: 3725, library_surface: 3728, library_view_tabs: 3733,
      data_picker_buttons: 3738, action_roundtrip: 3743, modal_a11y: 3833,
      preserve: 3867, preserve_real: 3869, milestone_h_wave1: 3969,
      milestone_h_overlay: 3976,
    },
  );
  /* 전부 클러스터 B 이고 전부 프런트 소유(호스트 소유 프로브가 없다 — resize 는 요청뿐). */
  for (const p of byName.values()) {
    assert.equal(p.cluster, "B");
    assert.equal(p.owner, "frontend");
    assert.deepEqual(p.modes, ["full"]);
  }
});

test("순서 제약은 전부 사유를 달고 있다 — 잃으면 조용히 틀리는 축", () => {
  const { caps } = createCaps();
  const runner = createSelftestRunner(caps);
  registerBootRoutingOverlayProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));

  const edges = {
    library_surface: ["home_screen_gone"],
    library_view_tabs: ["library_surface"],
    preserve_real: ["preserve"],
    milestone_h_wave1: ["preserve_real"],
    milestone_h_overlay: ["milestone_h_wave1"],
  };
  for (const [name, after] of Object.entries(edges)) {
    assert.deepEqual(byName.get(name).after, after, name);
  }
  /* `after` 를 선언한 프로브는 **반드시** 이유를 적는다. 이유 없는 순서는 다음 이식에서 사라진다. */
  for (const p of byName.values()) {
    if (p.after.length === 0) {
      assert.equal(p.afterReason, null, `${p.name}: 제약이 없는데 사유만 남았습니다.`);
      continue;
    }
    assert.equal(typeof p.afterReason, "string", p.name);
    assert.ok(p.afterReason.length > 0, p.name);
  }
  assert.match(byName.get("library_surface").afterReason, /반쪽 이주/);
  assert.match(byName.get("milestone_h_overlay").afterReason, /720x500/);
});

test("시간 예산은 늘지 않았다 — 레거시 old→new 대조", () => {
  const { caps } = createCaps();
  const runner = createSelftestRunner(caps);
  registerBootRoutingOverlayProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));

  /** app.py 의 실측 예산(ms). 0 = 폴링도 시한도 없던 동기 되읽기. */
  const legacy = {
    title_dom: 0, nav_count: 0, tpl_options: 0, job_on: 0,
    home_screen_gone: 0, library_surface: 0, library_view_tabs: 0, data_picker_buttons: 0,
    action_roundtrip: 10000,   // app.py:3744
    /* modal_a11y 만 레거시 0 에서 벗어난다 — R3-01(#410)에서 confirm·choose 골격이 React
       host 커밋 산물이 되며 마운트 전제 시한이 붙었다(react_runtime 5000ms 와 동형의 신설
       축). 본문 측정은 여전히 마이크로태스크뿐이라 실측 시간은 늘지 않는다. */
    modal_a11y: 5000,
    preserve: 0, preserve_real: 0,
    milestone_h_wave1: 0, milestone_h_overlay: 0,
  };
  for (const [name, budget] of Object.entries(legacy)) {
    assert.ok(
      byName.get(name).deadlineMs <= budget || budget === 0,
      `${name}: 시한이 레거시를 넘습니다.`,
    );
    assert.equal(byName.get(name).deadlineMs, budget, name);
  }
  /* 레거시 시한표에 없는 프로브는 전부 사유를 적었다(예산은 조용히 늘지 않는다).
     `describe()` 는 rationale 을 싣지 않으므로 정의 데이터에서 직접 센다. */
  for (const def of createBootRoutingOverlayProbes()) {
    if (def.name === "action_roundtrip") continue;
    assert.equal(typeof def.deadlineRationale, "string", def.name);
    assert.ok(def.deadlineRationale.length > 0, def.name);
  }
  /* 고정 대기도 레거시 그대로 — 0.3초(app.py:3975) / 0.3초(app.py:3983). */
  const overlay = byName.get("milestone_h_overlay");
  assert.equal(overlay.settleBeforeMs, 300);
  assert.equal(overlay.cooldownAfterMs, 300);
  assert.match(overlay.settleReason, /3975/);
  assert.match(overlay.cooldownReason, /3983/);
  for (const p of byName.values()) {
    if (p.name === "milestone_h_overlay") continue;
    assert.equal(p.settleBeforeMs, 0, p.name);
    assert.equal(p.cooldownAfterMs, 0, p.name);
  }
  /* 이 클러스터의 최악 예산 = 10초(action_roundtrip) + 5초(modal_a11y 마운트 전제 시한,
     R3-01) + 0.6초(overlay 앞뒤 대기). 실측 경로에서 전제는 즉시 참이라 벽시계는 안 는다. */
  assert.equal(runner.budgetMs("full"), 15600);
});

test("호스트 요청은 창 크기 변경 하나뿐이고 선언과 요청이 같이 산다", () => {
  const { caps } = createCaps();
  const runner = createSelftestRunner(caps);
  registerBootRoutingOverlayProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));
  for (const p of byName.values()) {
    if (p.name === "milestone_h_overlay") {
      assert.deepEqual(p.requiresHost, ["window_resize"]);
      assert.deepEqual(p.hostSetup, { op: "window_resize", payload: { width: 720, height: 500 } });
      continue;
    }
    assert.deepEqual(p.requiresHost, [], p.name);
    assert.equal(p.hostSetup, null, p.name);
  }
});

/* ────────────────────── 한 줄 되읽기 여덟 ────────────────────── */

test("부팅 되읽기 여덟 — 기준 실행과 같은 값 모양", async () => {
  const { report } = await runFull();
  assert.equal(report.results.title_dom, "문서나르미");
  assert.equal(report.results.nav_count, 2);
  assert.deepEqual(report.results.tpl_options, []);
  assert.equal(report.results.job_on, true);
  assert.equal(report.results.home_screen_gone, true);
  assert.equal(report.results.library_surface, true);
  assert.deepEqual(report.results.library_view_tabs, ["all", "recent", "favorites", "needsAction"]);
  assert.equal(report.results.data_picker_buttons, true);
});

test("home_screen_gone ↔ library_surface — 죽은 표면과 승계 표면의 쌍", async () => {
  /* 음성 극: 홈이 살아 있으면 승계 쪽이 초록이어도 사망 판정이 false 로 떨어진다. */
  const revived = await runFull({ dom: { homeAlive: true } });
  assert.equal(revived.report.results.home_screen_gone, false);
  assert.equal(revived.report.results.library_surface, true);

  /* 반대 극: 승계 표면의 축 하나가 빠지면 사망 판정이 초록이어도 승계가 false 다. */
  const halfBuilt = await runFull({ dom: { missingLibraryId: "libraryFacets" } });
  assert.equal(halfBuilt.report.results.home_screen_gone, true);
  assert.equal(halfBuilt.report.results.library_surface, false);
});

test("job_on / data_picker_buttons — build.ps1 이 금지하는 boolean false 극도 잰다", async () => {
  const off = await runFull({ dom: { jobOn: false, dataPickerButton: false } });
  assert.equal(off.report.results.job_on, false);
  assert.equal(off.report.results.data_picker_buttons, false);
});

test("tpl_options — 죽은 키지만 값은 그대로 흐른다(단언을 지어내지 않는다)", async () => {
  const { report } = await runFull({ dom: { tplOptions: ["a", "b"] } });
  assert.deepEqual(report.results.tpl_options, ["a", "b"]);
  /* 기준 실행의 값은 `[]` — 그리고 어떤 값이든 지금은 아무 게이트도 붉어지지 않는다. */
  const base = await runFull();
  assert.deepEqual(base.report.results.tpl_options, []);
});

/* ────────────────────── action_roundtrip ────────────────────── */

test("action_roundtrip — 네 화면군이 click→bridge→snapshot 을 한 실행에서 완주한다", async () => {
  const { report, wired } = await runFull();
  const probe = report.results.action_roundtrip;
  assert.equal(probe.pending, false, "완주 표지가 false 여야 합니다.");
  assert.deepEqual(Object.keys(probe.families).sort(), ["editor", "job", "pool", "template"]);
  const expected = {
    editor: ["editor", "new_session"],
    job: ["job", "refresh"],
    pool: ["pool", "refresh"],
    template: ["tpl", "refresh"],
  };
  for (const [family, [screen, action]] of Object.entries(expected)) {
    const got = probe.families[family];
    assert.equal(Object.prototype.hasOwnProperty.call(got, "error"), false, family);
    assert.deepEqual([got.screen, got.action], [screen, action], family);
    assert.equal(got.snapshot, true, family);
    assert.ok(got.snapshot_keys.length > 0, `${family}: 빈 snapshot`);
  }
  assert.deepEqual(wired.bridgeCalls.map((c) => c[0]).sort(), ["editor", "job", "pool", "tpl"]);
});

test("action_roundtrip — 한 군이 거절당하면 error 가 그 군에 남는다(음성 극)", async () => {
  const { report } = await runFull({ services: { bridgeCallFails: "pool" } });
  const probe = report.results.action_roundtrip;
  assert.equal(probe.pending, false);
  assert.equal(probe.families.pool.error, "registry 거절");
  assert.equal(Object.prototype.hasOwnProperty.call(probe.families.pool, "snapshot"), false);
  assert.equal(probe.families.job.snapshot, true);
});

test("action_roundtrip — 빈 snapshot 은 snapshot_keys 가 비어 정직하게 드러난다", async () => {
  const { report } = await runFull({ services: { emptySnapshotFor: "job" } });
  const got = report.results.action_roundtrip.families.job;
  assert.equal(got.snapshot, true);
  assert.deepEqual(got.snapshot_keys, []);
});

test("action_roundtrip — 완주하지 않으면 시끄럽게 실패하고 키가 실리지 않는다", async () => {
  /* 레거시는 만료에 else 가 없어 pending 인 객체를 그대로 실었다. 그 조용한 경로를 막는다. */
  const positive = await runFull();
  assert.equal(positive.report.ok, true, "기준 판은 완주한다(이 테스트의 양성 대조).");

  const built = createCaps();
  const runner = createSelftestRunner(built.caps);
  built.wired.services.Bridge.call = () => new Promise(() => {});   // 영영 해소되지 않는 판
  registerBootRoutingOverlayProbes(runner);
  const stuck = await settle(built.clock, runner.run("full", {}));
  const failure = stuck.errors.find((e) => e.probe === "action_roundtrip");
  assert.equal(failure.code, "deadline_exceeded");
  assert.match(failure.message, /action_roundtrip\.pending/);
  assert.equal(Object.prototype.hasOwnProperty.call(stuck.results, "action_roundtrip"), false);
  assert.equal(stuck.ok, false);
});

test("action_roundtrip — Bridge 주입이 없으면 조용히 넘어가지 않는다", async () => {
  const built = createCaps();
  const runner = createSelftestRunner(built.caps);
  delete built.wired.services.Bridge;
  registerBootRoutingOverlayProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  const failure = report.errors.find((e) => e.probe === "action_roundtrip");
  assert.match(failure.message, /Bridge 이 주입되지 않았거나/);
});

/* ────────────────────── modal_a11y / modal_confirm_serial ────────────────────── */

test("modal_a11y — 기준 실행의 필드 순서와 값이 그대로 나온다", async () => {
  const { report } = await runFull();
  const m = report.results.modal_a11y;
  assert.deepEqual(Object.keys(m), [
    "choose_opened", "choose_display", "choose_focus", "choose_labels", "choose_all_visible",
    "opened", "focus_in", "closed_by_escape", "focus_before", "focus_restored",
    "escape_entered_closing", "confirm_display_closed_before", "confirm_opened",
    "confirm_display_open", "confirm_focus", "confirm_reentry_alerts",
    "confirm_body_after_reentry", "confirm_trap_wrapped", "confirm_closed",
    "confirm_entered_closing", "confirm_display_closed", "danger_class", "danger_background",
    "danger_resets_to_neutral", "non_modal_open_rejected_loud", "non_modal_close_rejected_loud",
    "malformed_confirm_root_refused_loud", "confirm_after_malformed_opens",
  ]);
  assert.equal(m.opened, true);
  assert.equal(m.focus_in, "promptModalInput");
  assert.equal(m.escape_entered_closing, true);
  assert.equal(m.closed_by_escape, true);
  assert.equal(m.focus_restored, m.focus_before, "닫은 뒤 포커스가 트리거로 복귀해야 합니다.");
  assert.equal(m.focus_before, "job");
  assert.equal(m.confirm_focus, "confirmModalCancel");
  assert.equal(m.confirm_trap_wrapped, "confirmModalCancel");
  assert.equal(m.confirm_reentry_alerts, 1);
  assert.equal(m.confirm_body_after_reentry, "첫 확인 본문");
  assert.equal(m.choose_labels, "저장하고 이동|버리고 이동|머무르기");
  assert.equal(m.choose_focus, "chooseModalCancel");
});

test("modal_a11y — confirm display 세 점(none→flex→none)이 살아 있다", async () => {
  const { report } = await runFull();
  const m = report.results.modal_a11y;
  assert.equal(m.confirm_display_closed_before, "none");
  assert.equal(m.confirm_opened, true);
  assert.equal(m.confirm_display_open, "flex");
  assert.equal(m.confirm_entered_closing, true);
  assert.equal(m.confirm_closed, true);
  assert.equal(m.confirm_display_closed, "none");
});

test("modal_a11y — `.modal{display:flex}` 가 `.hidden` 을 이기면 음성 극이 잡는다(B-9)", async () => {
  const { report } = await runFull({ dom: { hiddenLosesToFlex: true } });
  const m = report.results.modal_a11y;
  assert.equal(m.confirm_display_closed_before, "flex", "열기 전부터 보이는 결함이 드러나야 합니다.");
  assert.equal(m.confirm_display_closed, "flex", "닫아도 계속 보이는 결함이 드러나야 합니다.");
});

test("modal_a11y — Escape 로 안 닫히면 두 필드가 함께 무너진다(음성 극)", async () => {
  const { report } = await runFull({ services: { brokenFinish: true } });
  const m = report.results.modal_a11y;
  assert.equal(m.escape_entered_closing, true, "퇴장 상태에는 들어간다");
  assert.equal(m.closed_by_escape, false, "그런데 display:none 까지 가지 못한다");
});

test("modal_a11y — Tab 트랩이 새면 포커스가 모달 밖 값으로 남는다(음성 극)", async () => {
  const { report } = await runFull({ services: { brokenTrap: true } });
  assert.equal(report.results.modal_a11y.confirm_trap_wrapped, "confirmModalOk");
});

test("modal_a11y — danger 적용 ↔ 중립 복귀 두 극", async () => {
  const positive = await runFull();
  const m = positive.report.results.modal_a11y;
  assert.equal(m.danger_class, true);
  assert.notEqual(m.danger_background, "transparent");
  assert.notEqual(m.danger_background, "rgba(0, 0, 0, 0)");
  assert.equal(m.danger_resets_to_neutral, true);

  /* 음성 극: danger 가 다음 중립 confirm 에 누수되면 복귀 판정이 false. */
  const leaking = await runFull({ services: { dangerLeaks: true } });
  assert.equal(leaking.report.results.modal_a11y.danger_class, true);
  assert.equal(leaking.report.results.modal_a11y.danger_resets_to_neutral, false);
});

test("modal_a11y — 비-모달 open **과** close 를 양쪽 다 loud 거절한다", async () => {
  const positive = await runFull();
  assert.equal(positive.report.results.modal_a11y.non_modal_open_rejected_loud, true);
  assert.equal(positive.report.results.modal_a11y.non_modal_close_rejected_loud, true);

  /* 음성 극 둘 — 한쪽만 조용해져도 각각 잡힌다(대칭 결함이 반쪽만 보이면 감도가 절반이다). */
  const silentOpen = createCaps();
  silentOpen.wired.services.Modal.open = ((real) => (id, opts) => {
    if (id === "__nonModalProbe") return false;             // 조용한 no-op
    return real(id, opts);
  })(silentOpen.wired.services.Modal.open);
  const runnerA = createSelftestRunner(silentOpen.caps);
  registerBootRoutingOverlayProbes(runnerA);
  const reportA = await settle(silentOpen.clock, runnerA.run("full", {}));
  assert.equal(reportA.results.modal_a11y.non_modal_open_rejected_loud, false);
  assert.equal(reportA.results.modal_a11y.non_modal_close_rejected_loud, true);

  const silentClose = createCaps();
  silentClose.wired.services.Modal.close = ((real) => (id) => {
    if (id === "__nonModalProbe") return false;
    return real(id);
  })(silentClose.wired.services.Modal.close);
  const runnerB = createSelftestRunner(silentClose.caps);
  registerBootRoutingOverlayProbes(runnerB);
  const reportB = await settle(silentClose.clock, runnerB.run("full", {}));
  assert.equal(reportB.results.modal_a11y.non_modal_open_rejected_loud, true);
  assert.equal(reportB.results.modal_a11y.non_modal_close_rejected_loud, false);
});

test("modal_a11y — 불량 confirm root 는 loud 거절되고 그 뒤 정상 confirm 이 열린다", async () => {
  const { report, dom } = await runFull();
  const m = report.results.modal_a11y;
  assert.equal(m.malformed_confirm_root_refused_loud, true, "불량 root 거절이 loud 여야 합니다.");
  assert.equal(m.confirm_after_malformed_opens, true, "교착 없이 후속 confirm 이 열려야 합니다.");
  /* 어떤 경로로 끝나든 `.modal` 은 원복된다 — 안 그러면 뒤 프로브가 통째로 무너진다. */
  assert.equal(dom.doc.getElementById("confirmModal").classList.contains("modal"), true);
});

test("modal_a11y — `choose_all_visible` 만이 **가시성**을 단언한다(감도 공백의 유일한 예외)", async () => {
  const positive = await runFull();
  assert.equal(positive.report.results.modal_a11y.choose_opened, true);
  assert.equal(positive.report.results.modal_a11y.choose_display, "flex");
  assert.equal(positive.report.results.modal_a11y.choose_all_visible, true);

  /* 음성 극: 배선은 됐지만 한 버튼이 display:none 이면 사용자는 나갈 길이 없다. */
  const hidden = await runFull({ services: { hiddenChooseButton: true } });
  assert.equal(hidden.report.results.modal_a11y.choose_opened, true);
  assert.equal(hidden.report.results.modal_a11y.choose_all_visible, false);
  /* 그런데도 클릭은 "성공"한다 — 이 클러스터가 안고 가는 감도 공백을 실행으로 못 박는다. */
  assert.equal(hidden.report.ok, true);
});

test("modal_confirm_serial — first=true ↔ second=false(재진입 거절) 두 극", async () => {
  const { report } = await runFull();
  assert.deepEqual(report.results.modal_confirm_serial, { first: true, second: false });

  /* 음성 극: 이중 바인딩이면 첫 확정이 둘째에도 새어 두 파괴 동작이 함께 실행된다. */
  const leaky = await runFull({ services: { leakyReentry: true } });
  assert.deepEqual(leaky.report.results.modal_confirm_serial, { first: true, second: true });
});

test("modal_confirm_serial — 창 객체 스태시 없이 한 프로브가 두 키를 낸다", () => {
  const probe = createBootRoutingOverlayProbes().find((p) => p.name === "modal_a11y");
  assert.deepEqual(probe.keys, ["modal_a11y", "modal_confirm_serial"]);
});

/* ────────────────────── preserve / preserve_real ────────────────────── */

test("preserve — 포커스·캐럿·옵트인 스크롤이 재구성을 가로질러 살아남는다", async () => {
  const { report } = await runFull();
  assert.deepEqual(report.results.preserve, {
    focus_id: "preserveProbeInput", sel_start: 2, sel_end: 4, scroll_top: 120,
  });
  assert.deepEqual(Object.keys(report.results.preserve), [
    "focus_id", "sel_start", "sel_end", "scroll_top",
  ]);
});

test("preserve — Preserve 가 복원하지 않으면 세 축이 함께 무너진다(음성 극)", async () => {
  const { report } = await runFull({ services: { brokenPreserve: true } });
  const p = report.results.preserve;
  assert.equal(p.focus_id, "preserveProbeInput", "포커스는 옛 노드에 남아 id 만 같다");
  assert.equal(p.sel_start, 2);
  assert.equal(p.scroll_top, 0, "옵트인 스크롤은 재구성이 0 으로 리셋한 그대로다");
});

test("preserve — 픽스처가 남으면 정리 실패가 시끄럽고 뒤 프로브를 멈춘다", async () => {
  const built = createCaps();
  /* 제거가 실패하는 대역 — 400px 픽스처가 남으면 뒤 프로브의 오버플로 측정이 거짓말이 된다. */
  const realCreate = built.dom.doc.createElement;
  built.dom.doc.createElement = (tag) => {
    const el = realCreate(tag);
    if (built.dom.doc.ids.size >= 0) {
      const realRemove = el.remove.bind(el);
      el.remove = () => { if (el.id !== "preserveProbeHost") realRemove(); };
    }
    return el;
  };
  const runner = createSelftestRunner(built.caps);
  registerBootRoutingOverlayProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));

  const teardownError = report.errors.find(
    (e) => e.phase === "teardown" && e.probe === "preserve",
  );
  assert.ok(teardownError, "정리 실패가 보고되지 않았습니다.");
  assert.match(teardownError.message, /문서에 남았습니다/);
  assert.equal(report.ok, false);
  assert.match(runner.toEvidence(report).error, /teardown_failed/);
  /* 오염된 뒤 프로브는 돌지 않는다 — 부분 결과가 성공인 척하지 않는다. */
  assert.ok(report.skipped.some((s) => s.probe === "preserve_real"));
  assert.equal(Object.prototype.hasOwnProperty.call(report.results, "milestone_h_overlay"), false);
});

test("preserve_real — 두 실화면이 실 push 로 재렌더되고 편집기 스크롤이 유지된다", async () => {
  const { report, pushes, wired } = await runFull();
  assert.deepEqual(report.results.preserve_real, {
    editor: "ok", job: "ok", editor_scroll_top: 60,
  });
  /* 렌더는 배포된 push 진입점으로 몬다(전역 조회가 아니다). */
  assert.deepEqual(pushes.map((p) => p[0]), ["editor", "job", "editor", "editor"]);
  /* 스크롤은 가시 화면에서만 유효하므로 편집기를 가시화했다가 자기 판을 걷는다. */
  assert.deepEqual(wired.navigations, [
    ["editor", { force: true }], ["job", { force: true }],
  ]);
});

test("preserve_real — 스냅샷이 안 오면 'no-snap' 이 남고 이른 반환이 원문 그대로다", async () => {
  const built = createCaps();
  built.dom.win.pywebview.api.initial = () => new Promise(() => {});   // 영영 해소되지 않는다
  const runner = createSelftestRunner(built.caps);
  registerBootRoutingOverlayProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  assert.deepEqual(report.results.preserve_real, {
    editor: "no-snap", job: "no-snap", editor_scroll_top: "no-snap",
  });
  /* 원문(app.py:913)의 이른 반환 — 이 경로에서는 job 복귀 Nav 가 **일어나지 않는다**.
     고치지 않고 옮겼다는 사실을 실행으로 못 박는다(수리는 이 웨이브의 일이 아니다). */
  assert.deepEqual(built.wired.navigations, [["editor", { force: true }]]);
});

test("preserve_real — 렌더가 던지면 화면별 'throw:' 로 남는다(catch 가 아니라 측정값)", async () => {
  const { report } = await runFull({ pushThrows: true });
  const p = report.results.preserve_real;
  assert.equal(p.editor, "throw:render 붕괴");
  assert.equal(p.job, "throw:render 붕괴");
  assert.equal(p.editor_scroll_top, "throw:render 붕괴");
});

test("preserve_real — 재렌더가 스크롤을 0 으로 리셋하면 그대로 드러난다(음성 극)", async () => {
  const { report } = await runFull({ services: { brokenPreserve: true } });
  assert.equal(report.results.preserve_real.editor_scroll_top, 0);
});

test("preserve_real — 고정 대기 1.2초(app.py:3870)를 그대로 쓴다", async () => {
  const { report } = await runFull();
  assert.ok(
    report.timings.preserve_real >= 1200,
    `preserve_real 이 1.2초를 기다리지 않았습니다: ${report.timings.preserve_real}`,
  );
});

/* ────────────────────── milestone_h_wave1 ────────────────────── */

test("milestone_h_wave1 — 타이포·위계·PathTrack·스크롤포트를 한 번에 낸다", async () => {
  const { report } = await runFull();
  const h = report.results.milestone_h_wave1;
  assert.deepEqual(Object.keys(h), [
    "headings", "job_steps", "job_step_badges", "card_base", "selected_card",
    "disabled_primary", "enabled_primary", "pathtrack", "scroll",
  ]);
  assert.deepEqual(Object.keys(h.headings), ["screen", "section", "zone"]);
  assert.deepEqual(h.job_steps, ["현재 데이터", "본문 확인"]);
  assert.equal(h.job_step_badges, 0);
  assert.deepEqual(h.pathtrack.names, ["폴더에서 보기", "경로 복사"]);
  assert.equal(h.pathtrack.count, 2);
  assert.equal(h.pathtrack.titled, true);
  assert.equal(h.pathtrack.svg, true);
  assert.deepEqual(h.scroll, {
    overflow_y: "auto", gutter: "stable both-edges", overscroll: "contain",
    sticky_position: "sticky", sticky_holds: true, scroll_top: 40,
  });
});

test("milestone_h_wave1 — disabled ↔ enabled / card_base ↔ selected_card 두 쌍", async () => {
  const { report } = await runFull();
  const h = report.results.milestone_h_wave1;
  assert.notEqual(h.disabled_primary.background, h.enabled_primary.background);
  assert.equal(h.disabled_primary.opacity, "1", "물러나되 흐려지지 않는다(H-11).");
  assert.notEqual(h.selected_card.background, h.card_base.background);
  assert.notEqual(h.selected_card.border_left, "rgba(0, 0, 0, 0)");
  /* 표본은 자급이고 뒷정리도 자기가 한다 — 앞·뒤 프로브에 무임승차하지 않는다(#137). */
  assert.deepEqual(Object.keys(h.card_base), [
    "font_size", "font_weight", "background", "color", "border_left", "opacity",
  ]);
});

test("milestone_h_wave1 — 원래 disabled 상태를 원복한다(측정이 상태를 남기지 않는다)", async () => {
  const { report, dom } = await runFull();
  assert.equal(report.ok, true);
  assert.equal(dom.doc.getElementById("jobGenBtn").disabled, false);
  /* 스크롤포트 표본도 문서에 남지 않는다. */
  assert.equal(dom.body.children.some((c) => c.className === "tblwrap"), false);
});

/* ────────────────────── milestone_h_overlay ────────────────────── */

test("milestone_h_overlay — 720x500 에서 재고 호스트가 창을 되돌린다", async () => {
  const { report, requests } = await runFull();
  assert.deepEqual(requests.filter((r) => r.op === "window_resize").map((r) => r.payload), [
    { width: 720, height: 500 },
    { width: 1440, height: 900 },
  ]);
  const h = report.results.milestone_h_overlay;
  assert.equal(h.pending, false);
  /* 좁은 창 regime 을 실제로 쟀다는 증거 — 프로브가 어느 쪽을 쟀는지 함께 싣는다. */
  assert.equal(h.workcard.narrow, true);
  assert.equal(h.short_viewport.viewport, 500);
});

test("milestone_h_overlay — 오버레이 소유(두 포털)·스크롤바·sticky 재질", async () => {
  const { report, dom } = await runFull();
  const h = report.results.milestone_h_overlay;
  assert.equal(h.overlay_root_direct, true);
  /* 양성이 공허하지 않다는 대조 — fixture 가 실제로 두 포털에 갈라 심었는가(R3-01 개정 8).
     이 두 단언이 없으면 전부 overlayRoot 자식인 낡은 형상에서도 아래 true 가 나온다. */
  assert.equal(
    dom.doc.getElementById("confirmModal").parentElement,
    dom.doc.getElementById("reactOverlayHost"),
  );
  assert.equal(
    dom.doc.getElementById("txtEditModal").parentElement,
    dom.doc.getElementById("overlayRoot"),
  );
  assert.equal(h.overlay_children_owned, true);
  assert.deepEqual(h.scrollbar, {
    width: "8px", button_display: "none", button_width: "0px", button_height: "0px",
  });
  assert.equal(h.sticky_material.position, "sticky");
  assert.match(h.sticky_material.backdrop, /blur\(14px\)/);

  /* 음성 극: 오버레이 자식이 루트 밖에 서면 소유 판정이 무너진다. */
  const stray = await runFull({ dom: { strayOverlayChild: true } });
  assert.equal(stray.report.results.milestone_h_overlay.overlay_children_owned, false);
});

test("milestone_h_overlay — 팝오버 dismissal 다섯 경로와 click 생존 두 쌍", async () => {
  const { report } = await runFull();
  const h = report.results.milestone_h_overlay;
  assert.equal(h.drag_closed, true, "드래그(click 없는 pointer)는 팝오버를 닫는다");
  assert.equal(h.click_after_drag, true, "그런데 뒤이은 진짜 click 은 살아 있어야 한다");
  assert.equal(h.click_after_right, true, "우클릭 뒤에도 click 이 삼켜지지 않는다");
  assert.equal(h.focusout_closed, true);
  assert.equal(h.scroll_closed, true);
  assert.equal(h.close_all_closed, true);
  assert.ok(h.close_count >= 4);
  assert.equal(h.popover_place.placement, "top");
  assert.equal(h.popover_place.in_viewport, true);
  assert.match(h.popover_place.origin, / bottom$/);
});

test("milestone_h_overlay — 모달 스택·IME Escape·짧은 viewport", async () => {
  const { report } = await runFull();
  const h = report.results.milestone_h_overlay;
  assert.equal(h.modal_closed_popover, true);
  assert.equal(h.modal_focus_in, "promptModalInput");
  assert.equal(h.z_order, true);
  /* 양성/음성 한 쌍: IME 조합 중 Escape 는 **열어 두고**, 맨 Escape 는 닫는다. */
  assert.equal(h.ime_escape_kept_open, true);
  assert.equal(h.exit_blocks_pointer, true);
  assert.equal(h.menu_trigger_restored, true);
  assert.equal(h.escape_one_layer, true, "두 겹에서 Escape 한 번은 최상위만 퇴장시킨다");
  assert.equal(h.short_viewport.scrollable, true);
  assert.equal(h.short_viewport.actions_reachable, true);
  assert.ok(h.short_viewport.height <= h.short_viewport.viewport - 32);
});

test("milestone_h_overlay — 방출 모양에 `finish` 가 서지 않는다(상태는 러너가 든다)", async () => {
  const { report } = await runFull();
  const h = report.results.milestone_h_overlay;
  assert.equal(Object.prototype.hasOwnProperty.call(h, "finish"), false);
  assert.equal(Object.keys(h)[0], "pending");
  assert.deepEqual(Object.keys(h), [
    "pending", "overlay_root_direct", "overlay_children_owned", "scrollbar", "sticky_material",
    "workcard", "popover_place", "modal_closed_popover", "modal_focus_in", "z_order",
    "ime_escape_kept_open", "exit_blocks_pointer", "menu_trigger_restored", "escape_one_layer",
    "short_viewport", "drag_closed", "click_after_drag", "click_after_right", "focusout_closed",
    "scroll_closed", "close_all_closed", "close_count",
  ]);
});

test("milestone_h_overlay — 넓은 catch 를 버렸다: setup 이 던지면 키가 실리지 않는다", async () => {
  const built = createCaps();
  built.dom.doc.ids.delete("wbCard");        // 작업대 표본 소실 = setup 이 던지는 조건
  const runner = createSelftestRunner(built.caps);
  registerBootRoutingOverlayProbes(runner);
  const report = await settle(built.clock, runner.run("full", {}));
  const failure = report.errors.find((e) => e.probe === "milestone_h_overlay");
  assert.ok(failure, "실패가 보고되지 않았습니다.");
  assert.equal(
    Object.prototype.hasOwnProperty.call(report.results, "milestone_h_overlay"), false,
    "레거시는 여기서 out.error 를 담은 정상 모양 값을 실었다 — 그 경로를 끊었다.",
  );
  assert.equal(report.ok, false);
  /* 실패해도 창 복귀는 호스트가 한다(teardown). */
  assert.deepEqual(built.requests.filter((r) => r.op === "window_resize").map((r) => r.payload), [
    { width: 720, height: 500 }, { width: 1440, height: 900 },
  ]);
});

test("milestone_h_overlay — 발판이 남으면 정리가 시끄럽다", async () => {
  const built = createCaps();
  const runner = createSelftestRunner(built.caps);
  registerBootRoutingOverlayProbes(runner);
  /* Popover.closeAll 이 던지면 finish() 가 발판을 걷기 전에 멈춘다. */
  built.wired.services.Popover.closeAll = () => { throw new Error("팝오버 정리 붕괴"); };
  const report = await settle(built.clock, runner.run("full", {}));
  const teardownError = report.errors.find(
    (e) => e.phase === "teardown" && e.probe === "milestone_h_overlay",
  );
  assert.ok(teardownError, "남은 발판이 조용히 지나갔습니다.");
  assert.match(teardownError.message, /__hOverlayTrigger/);
  assert.equal(report.ok, false);
});

/* ────────────────────── 완주·증거 ────────────────────── */

test("기준 판은 15키를 전부 내고 error 가 서지 않는다", async () => {
  const { report, runner } = await runFull();
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.deepEqual(Object.keys(report.results).sort(), keysForCluster("B"));
  const evidence = runner.toEvidence(report);
  assert.equal(Object.prototype.hasOwnProperty.call(evidence, "error"), false);
  /* build.ps1:317-327 이 금지하는 최상위 boolean false 가 이 클러스터에서 나오지 않는다. */
  for (const k of ["data_picker_buttons", "home_screen_gone", "job_on", "library_surface"]) {
    assert.equal(evidence[k], true, k);
  }
});

/* ────────────────────────── 음성 ────────────────────────── */

test("음성 — 전역 쓰기·전역 스태시·__hwpxTest 부재", () => {
  assert.equal(/(?:^|\s)window\.[A-Za-z_$][A-Za-z0-9_$]*\s*=/m.test(SRC), false);
  assert.equal(/globalThis\s*\.\s*[A-Za-z_$][A-Za-z0-9_$]*\s*=/.test(SRC), false);
  assert.equal(SRC.includes("__hwpxTest"), false);
  assert.equal(/window\.__/.test(SRC), false);
  assert.equal(/globalThis\.__/.test(SRC), false);
  /* 레거시 스태시 이름이 **쓰기 대상**으로 되살아나지 않았는지도 본다. */
  for (const stash of ["__cf1", "__cf2", "__snaps", "__actionRoundtrip", "__milestoneHOverlay"]) {
    assert.equal(new RegExp(`${stash}\\s*=`).test(SRC), false, stash);
  }
});

test("음성 — 제품 전역을 읽지도 않는다(전부 ctx 주입)", () => {
  for (const global of [
    "Intent", "Modal", "Theme", "Personalization", "Bridge", "Popover",
    "Preserve", "Nav", "PathTrack", "SheetPicker",
  ]) {
    assert.equal(new RegExp(`(?<![.\\w])window\\.${global}\\b`).test(SRC), false, global);
    assert.equal(new RegExp(`(?<![.\\w])globalThis\\.${global}\\b`).test(SRC), false, global);
  }
  /* 문서·창도 주입으로만 만진다 — 맨 `document.`/`window.` 조회가 하나도 없다. */
  assert.equal(/(?<![.\w])document\s*\./.test(SRC), false);
  assert.equal(/(?<![.\w])window\s*\./.test(SRC), false);
  /* 유일한 import 는 형제 러너 하나다 — 제품 그래프(main.js·bootstrap.js·js/**)에 닿지 않는다. */
  const imports = SRC.match(/^import\s[^\n]*from\s+"[^"]+"/gm) || [];
  assert.equal(imports.length, 1);
  assert.match(imports[0], /"\.\.\/runner\.js"/);
  for (const name of ["main.js", "bootstrap.js", "bridge.js", "../js/", "../../js/"]) {
    assert.equal(SRC.includes(`from "${name}"`), false, name);
  }
});

test("bare import 는 순수하다 — DOM·리스너·전역을 만들지 않는다", async () => {
  const before = Object.keys(globalThis).length;
  const again = await import(`${MODULE_URL.href}?pure=${Date.now()}`);
  assert.equal(typeof again.createBootRoutingOverlayProbes, "function");
  assert.equal(Object.keys(globalThis).length, before);
  assert.equal(typeof globalThis.document, "undefined");
  assert.equal(typeof globalThis.window, "undefined");
  /* factory 를 불러도 DOM 은 안 만진다 — 정의 데이터만 나온다. */
  const defs = again.createBootRoutingOverlayProbes();
  assert.equal(defs.length, 14);
  for (const def of defs) {
    assert.equal(typeof def.name, "string");
    assert.equal(def.cluster, "B");
  }
  assert.deepEqual(again.B_KEYS.slice().sort(), keysForCluster("B"));
});
