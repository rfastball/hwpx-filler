/* React overlay host 의 요소 계약·집행 계약 (R3-01 · #410).
 *
 * 두 축을 잰다:
 *
 * 1. **렌더 요소 계약** — index.html 에서 이전한 골격 4(confirm·choose·prompt·토스트)가
 *    같은 id·클래스·ARIA·초기 문안으로 React 렌더에 실려 있는가. 정적 index.html 의
 *    **부재**는 pytest 정적 계약이 재고, 여기는 **렌더 존재** 쪽 절반이다 — 실 서버 렌더
 *    (`react-dom/server`)로 요소 트리를 실제 산출해 재므로, 컴포넌트 소스의 문자열이
 *    아니라 렌더 결과를 본다(선언이 아니라 결과).
 *
 * 2. **집행 계약** — 컨트롤러 실물(createOverlayDialogController)의 초기 초점 지정
 *    (confirm/choose=취소·prompt=입력칸), danger **양방향** 토글(안정 버튼 재사용의 상태
 *    누수 차단), choose 3답 값, 그리고 합성 루트 계약(host 가 구동하는 엔진 =
 *    instance.ts 의 단일 인스턴스, 슬롯 이중 대입 throw·해제 후 재대입 가능).
 *
 * 직렬화·Escape·스택·복귀의 전 사슬은 n05_overlay(파사드 경유 실물 사슬)와
 * overlay_engine(엔진 순수층)이 지고, 실 WebView2 증거는 live 게이트가 진다. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  OverlayHost,
  createOverlayDialogController,
} from "../../frontend/src/overlay/host.ts";
import { overlayEngine, setOverlayDialogHost } from "../../frontend/src/overlay/instance.ts";

/* ────────────────────────── 1. 렌더 요소 계약 ────────────────────────── */

const MARKUP = renderToStaticMarkup(
  createElement(OverlayHost, { doc: {}, notify: () => {} }),
);

test("host 는 #reactOverlayHost 하나에 골격 4 를 렌더한다", () => {
  assert.match(MARKUP, /^<div id="reactOverlayHost">/);
  for (const id of ["confirmModal", "chooseModal", "promptModal", "undoToast"]) {
    const count = MARKUP.split(`id="${id}"`).length - 1;
    assert.equal(count, 1, `#${id} 가 정확히 1회 렌더되어야 합니다`);
  }
});

test("다이얼로그 3종 — 같은 클래스·role·aria-modal·aria-labelledby·닫힘 초기 상태", () => {
  for (const id of ["confirmModal", "chooseModal", "promptModal"]) {
    const at = MARKUP.indexOf(`id="${id}"`);
    assert.ok(at !== -1, `#${id} 부재`);
    const opening = MARKUP.slice(MARKUP.lastIndexOf("<div", at), MARKUP.indexOf(">", at) + 1);
    assert.match(opening, /class="modal hidden"/, `#${id}: 닫힘 상태 상시 렌더(.modal.hidden)가 아닙니다`);
    assert.match(opening, /role="dialog"/, `#${id}: role 소실`);
    assert.match(opening, /aria-modal="true"/, `#${id}: aria-modal 소실`);
    assert.match(opening, new RegExp(`aria-labelledby="${id}Title"`), `#${id}: 제목 연결 소실`);
  }
  // 카드·제목·본문 — index.html 골격과 같은 구조(.modal-card > h3 + p.modal-body).
  for (const id of ["confirmModal", "chooseModal", "promptModal"]) {
    assert.match(MARKUP, new RegExp(`<h3 id="${id}Title">`), `#${id}Title 부재`);
    assert.match(MARKUP, new RegExp(`<p class="modal-body" id="${id}Body">`), `#${id}Body 부재`);
  }
  assert.equal(MARKUP.split('class="modal-card"').length - 1, 3, "modal-card 는 다이얼로그마다 하나다");
});

test("초기 문안·버튼 골격 — 파사드가 채우기 전의 정적 문안이 index.html 시절과 같다", () => {
  assert.match(MARKUP, /<h3 id="confirmModalTitle">확인<\/h3>/);
  assert.match(MARKUP, /<button class="btn" id="confirmModalCancel">취소<\/button>/);
  assert.match(MARKUP, /<button class="btn primary" id="confirmModalOk">확인<\/button>/);
  assert.match(MARKUP, /<h3 id="chooseModalTitle">선택<\/h3>/);
  assert.match(MARKUP, /<button class="btn" id="chooseModalCancel">머무르기<\/button>/);
  assert.match(MARKUP, /<button class="btn" id="chooseModalAlt"><\/button>/);
  assert.match(MARKUP, /<button class="btn primary" id="chooseModalOk"><\/button>/);
  assert.match(MARKUP, /<h3 id="promptModalTitle">입력<\/h3>/);
  assert.match(MARKUP, /<input class="field" id="promptModalInput" type="text"\/>/);
  assert.match(MARKUP, /<button class="btn" id="promptModalCancel">취소<\/button>/);
  assert.match(MARKUP, /<button class="btn primary" id="promptModalOk">확인<\/button>/);
});

test("prompt 오류줄·토스트 — role/aria-live/hidden 초기 상태가 이전과 동일하다", () => {
  const errorAt = MARKUP.indexOf('id="promptModalError"');
  assert.ok(errorAt !== -1);
  const errorTag = MARKUP.slice(MARKUP.lastIndexOf("<p", errorAt), MARKUP.indexOf(">", errorAt) + 1);
  assert.match(errorTag, /class="note dangerbox"/);
  assert.match(errorTag, /role="alert"/);
  assert.match(errorTag, /display:none/, "오류줄은 닫힘(display:none)으로 시작한다");

  const toastAt = MARKUP.indexOf('id="undoToast"');
  assert.ok(toastAt !== -1);
  const toastTag = MARKUP.slice(MARKUP.lastIndexOf("<div", toastAt), MARKUP.indexOf(">", toastAt) + 1);
  assert.match(toastTag, /class="undo-toast"/);
  assert.match(toastTag, /role="status"/);
  assert.match(toastTag, /aria-live="polite"/);
  assert.match(toastTag, /hidden/, "토스트는 hidden 으로 시작한다");
  assert.match(MARKUP, /<span id="undoToastText"><\/span>/);
  assert.match(MARKUP, /<button class="btn sm" id="undoToastBtn">되돌리기<\/button>/);
});

/* ────────────────────────── 2. 집행 계약 — 최소 DOM 스텁 ────────────────────────── */

class El {
  constructor(tag, id = "", classes = []) {
    this.tagName = String(tag).toUpperCase();
    this.id = id;
    this.childNodes = [];
    this.parentNode = null;
    this.classSet = new Set(classes);
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.listeners = new Map();
    this.styleProps = {};
    this.attrs = {};
    const self = this;
    this.classList = {
      add: (...n) => n.forEach((x) => self.classSet.add(x)),
      remove: (...n) => n.forEach((x) => self.classSet.delete(x)),
      contains: (n) => self.classSet.has(n),
      toggle: (n, force) => {
        const want = force === undefined ? !self.classSet.has(n) : !!force;
        if (want) self.classSet.add(n); else self.classSet.delete(n);
        return want;
      },
    };
    this.style = {
      setProperty: (k, v) => { self.styleProps[k] = String(v); },
      removeProperty: (k) => { delete self.styleProps[k]; },
      get display() { return self.styleProps.display || ""; },
      set display(v) { self.styleProps.display = String(v); },
    };
  }

  setAttribute(name, value) { this.attrs[name] = String(value); }

  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); }

  add(child) { child.parentNode = this; this.childNodes.push(child); return child; }

  contains(node) { for (let n = node; n; n = n.parentNode) if (n === this) return true; return false; }

  querySelector(selector) {
    const sel = String(selector);
    const hit = (el) => (sel.startsWith("#") ? el.id === sel.slice(1)
      : sel.startsWith(".") ? el.classSet.has(sel.slice(1)) : false);
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (hit(child)) return child;
        const found = walk(child);
        if (found !== null) return found;
      }
      return null;
    };
    return walk(this);
  }

  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(fn);
  }

  removeEventListener(type, fn) {
    const list = this.listeners.get(type);
    if (!list) return;
    const at = list.indexOf(fn);
    if (at !== -1) list.splice(at, 1);
  }

  focus() { DOC.activeElement = this; }
}

const DOC = {
  activeElement: null,
  querySelector: () => null, // 화면 루트 폴백은 이 파일 범위 밖(n05_overlay 가 잰다).
};

function dialogFixture(id, kids) {
  const root = new El("div", id, ["modal", "hidden"]);
  const card = root.add(new El("div", "", ["modal-card"]));
  for (const kid of kids) card.add(kid);
  return root;
}

function makeRoots() {
  const confirm = dialogFixture("confirmModal", [
    new El("h3", "confirmModalTitle"), new El("p", "confirmModalBody"),
    new El("button", "confirmModalCancel"), new El("button", "confirmModalOk"),
  ]);
  const choose = dialogFixture("chooseModal", [
    new El("h3", "chooseModalTitle"), new El("p", "chooseModalBody"),
    new El("button", "chooseModalCancel"), new El("button", "chooseModalAlt"),
    new El("button", "chooseModalOk"),
  ]);
  const prompt = dialogFixture("promptModal", [
    new El("h3", "promptModalTitle"), new El("p", "promptModalBody"),
    new El("input", "promptModalInput"), new El("p", "promptModalError"),
    new El("button", "promptModalCancel"), new El("button", "promptModalOk"),
  ]);
  const toast = new El("div", "undoToast", ["undo-toast"]);
  toast.add(new El("span", "undoToastText"));
  toast.add(new El("button", "undoToastBtn"));
  return { confirm, choose, prompt, toast };
}

function click(el) {
  for (const fn of [...(el.listeners.get("click") || [])]) fn({ target: el });
}

function flushClose(root) {
  const card = root.querySelector(".modal-card");
  for (const fn of [...(card.listeners.get("transitionend") || [])]) {
    fn({ target: card, propertyName: "opacity" });
  }
}

function session(roots = makeRoots()) {
  const alerts = [];
  const made = createOverlayDialogController({
    doc: DOC,
    notify: (message) => alerts.push(String(message)),
    roots,
  });
  return { roots, alerts, controller: made.controller, dispose: made.dispose };
}

test("초기 초점 — confirm·choose 는 취소(머무르기), prompt 는 입력칸이다(F7·결정 27/36/38)", async () => {
  const s = session();

  const c = s.controller.confirm({
    title: "확인", body: "b", confirmLabel: "확인", cancelLabel: "취소",
    danger: false, missingText: "m",
  });
  assert.equal(DOC.activeElement.id, "confirmModalCancel");
  click(s.roots.confirm.querySelector("#confirmModalCancel"));
  flushClose(s.roots.confirm);
  assert.equal(await c, false);

  const p = s.controller.prompt({ title: "입력", body: "b", value: "가", missingText: "m" });
  assert.equal(DOC.activeElement.id, "promptModalInput");
  assert.equal(s.roots.prompt.querySelector("#promptModalInput").value, "가");
  click(s.roots.prompt.querySelector("#promptModalCancel"));
  flushClose(s.roots.prompt);
  assert.equal(await p, null);

  const h = s.controller.choose({
    title: "선택", body: "b",
    primary: { value: "go", label: "이동" }, alt: { value: "patch", label: "덧대기" },
    refusal: { value: "stay", label: "머무르기" }, missingText: "m",
  });
  assert.equal(DOC.activeElement.id, "chooseModalCancel");
  click(s.roots.choose.querySelector("#chooseModalCancel"));
  flushClose(s.roots.choose);
  assert.equal(await h, "stay");
  s.dispose();
});

test("danger 는 양방향 토글이다 — danger 뒤 중립이 빨갛게 남지 않는다(#219 상태 누수 차단)", async () => {
  const s = session();
  const ok = s.roots.confirm.querySelector("#confirmModalOk");

  const first = s.controller.confirm({
    title: "확인", body: "지웁니다", confirmLabel: "지웁니다", cancelLabel: "취소",
    danger: true, missingText: "m",
  });
  assert.equal(ok.classSet.has("danger"), true);
  assert.equal(ok.classSet.has("primary"), false);
  assert.equal(ok.textContent, "지웁니다");
  click(ok);
  flushClose(s.roots.confirm);
  assert.equal(await first, true);

  const second = s.controller.confirm({
    title: "확인", body: "중립", confirmLabel: "확인", cancelLabel: "취소",
    danger: false, missingText: "m",
  });
  assert.equal(ok.classSet.has("danger"), false, "이전 danger 가 남았습니다");
  assert.equal(ok.classSet.has("primary"), true);
  click(s.roots.confirm.querySelector("#confirmModalCancel"));
  flushClose(s.roots.confirm);
  assert.equal(await second, false);
  s.dispose();
});

test("choose 의 보조 버튼은 alt 값으로 해소된다(3답 형상)", async () => {
  const s = session();
  const h = s.controller.choose({
    title: "선택", body: "b",
    primary: { value: "go", label: "이동" }, alt: { value: "patch", label: "덧대기" },
    refusal: { value: "stay", label: "머무르기" }, missingText: "m",
  });
  const alt = s.roots.choose.querySelector("#chooseModalAlt");
  assert.equal(alt.textContent, "덧대기");
  click(alt);
  flushClose(s.roots.choose);
  assert.equal(await h, "patch");
  s.dispose();
});

test("합성 루트 계약 — host 가 구동하는 엔진은 instance.ts 의 단일 인스턴스다", async () => {
  const s = session();
  assert.equal(overlayEngine.depth(), 0);
  const c = s.controller.confirm({
    title: "확인", body: "b", confirmLabel: "확인", cancelLabel: "취소",
    danger: false, missingText: "m",
  });
  // 같은 인스턴스라는 사실을 관측면으로 잰다 — 컨트롤러의 open 이 여기 imported 엔진의
  // 깊이·직렬화 상태로 보인다(다르면 스택이 두 세계로 갈린 것이다).
  assert.equal(overlayEngine.depth(), 1);
  assert.equal(overlayEngine.isDialogPending(), true);
  assert.equal(overlayEngine.isOpen(s.roots.confirm), true);
  click(s.roots.confirm.querySelector("#confirmModalCancel"));
  flushClose(s.roots.confirm);
  assert.equal(await c, false);
  assert.equal(overlayEngine.depth(), 0);
  assert.equal(overlayEngine.isDialogPending(), false);
  s.dispose();
});

test("슬롯 수명주기 — 이중 대입은 throw, 해제 뒤 재대입은 정상이다(두 번째 실행 경로 차단)", () => {
  const s = session();
  const release = setOverlayDialogHost(s.controller);
  assert.throws(() => setOverlayDialogHost(s.controller), /이미 서 있습니다/);
  release();
  const again = setOverlayDialogHost(s.controller);
  again();
  s.dispose();
});

/* ---------------- 닫힘 뒤 대안 착지(#787) ---------------- */

function withScreen(screen, body) {
  const previous = DOC.querySelector;
  DOC.querySelector = (selector) => (String(selector) === ".scr.on" ? screen : null);
  try {
    return body();
  } finally {
    DOC.querySelector = previous;
  }
}

test("#787 대안 착지는 목적 화면이 이미 잡은 초점을 빼앗지 않는다", async () => {
  // 대안의 근거는 「초점이 사라지는 것보다 화면 처음이 낫다」다. 초점이 사라지지 않았다면 그
  // 근거가 없다 — deep-link 진입이 그 형상이다: 누른 버튼은 화면 전환으로 사라져 트리거 복원이
  // 실패하고, 그 대안이 목적 화면의 조준 초점을 덮어쓴다.
  const screen = new El("section", "scr-editor", ["scr", "on"]);
  const aimed = screen.add(new El("select", "row-source"));
  const gone = new El("button", "vanished-trigger");
  gone.isConnected = false; // 화면이 바뀌며 사라진 트리거

  await withScreen(screen, async () => {
    const s = session();
    const c = s.controller.confirm({
      title: "확인", body: "b", confirmLabel: "확인", cancelLabel: "취소",
      danger: false, missingText: "m", returnFocus: gone,
    });
    click(s.roots.confirm.querySelector("#confirmModalCancel"));
    aimed.focus(); // 목적 화면이 자기 자리를 잡았다
    flushClose(s.roots.confirm);
    await c;
    assert.equal(DOC.activeElement, aimed, "조준한 자리를 화면 루트가 빼앗았습니다");
    s.dispose();
  });
});

test("#787 초점을 잃었으면 대안은 그대로 화면 루트로 착지한다", async () => {
  // 음성 대조 — 기존 계약(초점이 사라지는 것보다 화면 처음이 낫다)을 약화시키지 않는다.
  const screen = new El("section", "scr-job", ["scr", "on"]);
  const gone = new El("button", "vanished-trigger");
  gone.isConnected = false;

  await withScreen(screen, async () => {
    const s = session();
    const c = s.controller.confirm({
      title: "확인", body: "b", confirmLabel: "확인", cancelLabel: "취소",
      danger: false, missingText: "m", returnFocus: gone,
    });
    click(s.roots.confirm.querySelector("#confirmModalCancel"));
    DOC.activeElement = null; // 초점이 갈 곳을 잃었다
    flushClose(s.roots.confirm);
    await c;
    assert.equal(DOC.activeElement, screen, "초점을 잃었는데 아무 데도 안 세웠습니다");
    assert.equal(screen.attrs.tabindex, "-1", "프로그램 초점이라 tabindex 는 -1 이다");
    s.dispose();
  });
});
