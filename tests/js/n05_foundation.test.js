/* N-05 Packet A — 기반 서비스 넷(popover·preserve·intent·undo_toast)의 ESM 계약과
   **오늘의 동작** 특성화.

   정적 소스 대조는 export 의 존재만 보고 산출을 못 본다(N-04 선례). 여기서 세는 것은 셋이다:
   ① 공개 표면이 계약 표와 정확히 같은가, ② 모듈 스코프 상태가 **import 당 한 번**만 서는가
   (싱글턴 — 사본이 갈리면 즐겨찾기 미결 의도·팝오버 레지스트리가 조용히 두 벌이 된다),
   ③ 전환 전 IIFE 가 내던 결과를 그대로 내는가.

   ②는 반드시 **음성 대조**와 함께 센다: 캐시 우회 쿼리로 같은 파일을 한 번 더 평가하면
   상태가 갈리는 것을 보여야, "공유된다"는 단언이 판별력을 가진다.

   DOM 은 Node 에 없다. 여기서 심는 window/document/Node/Element stub 은 제품 전역이 아니므로
   **매 테스트 뒤 반드시 걷는다** — 남기면 다음 테스트의 관측이 오염된다. */
import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const MODULES = {
  Popover: new URL("../../frontend/js/popover.js", import.meta.url),
  Preserve: new URL("../../frontend/js/preserve.js", import.meta.url),
  Intent: new URL("../../frontend/js/intent.js", import.meta.url),
  UndoToast: new URL("../../frontend/js/undo_toast.js", import.meta.url),
};

/* 계약 §1-A 표 — 키 순서까지 그대로다. R3-01(#410)이 Popover 에 `documentAttachments`
   (문서 부착 **명세** — 부착 집행은 bootProduct 구성 몫)를 더했다. 함수가 아닌 유일한
   키라 아래 표면 테스트가 형상을 따로 잰다. */
const SURFACE = {
  Popover: ["register", "wireDismiss", "closeAll", "place", "documentAttachments"],
  Preserve: ["around"],
  Intent: ["chained", "settle", "createFavorite"],
  UndoToast: ["show", "hide"],
};

// ---------------------------------------------------------------- DOM stub --

class StubNode {
  constructor(id = "") {
    this.id = id;
    this.parentNode = null;
    this.childNodes = [];
    this.listeners = new Map();
  }

  add(child) {
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }

  contains(other) {
    for (let node = other; node; node = node.parentNode) if (node === this) return true;
    return false;
  }

  /* host 컨트롤러의 골격 판독(`#id` 하위 조회)에 필요한 최소 표면 — 그 이상은 안 준다. */
  querySelector(selector) {
    const id = String(selector).replace(/^#/, "");
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (child.id === id) return child;
        const found = walk(child);
        if (found !== null) return found;
      }
      return null;
    };
    return walk(this);
  }

  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }

  async dispatch(type, event) {
    for (const handler of this.listeners.get(type) || []) await handler.call(this, event);
  }
}

class StubElement extends StubNode {
  constructor(id = "", tagName = "DIV") {
    super(id);
    this.tagName = tagName;
    this.style = {};
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.scrollTop = 0;
    this.scrollLeft = 0;
    this.rect = { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
    this.calls = [];
  }

  getBoundingClientRect() {
    return this.rect;
  }

  focus(options) {
    this.calls.push(["focus", options === undefined ? null : { ...options }]);
  }

  setSelectionRange(start, end, direction) {
    this.calls.push(["setSelectionRange", start, end, direction]);
    this.selectionStart = start;
    this.selectionEnd = end;
    this.selectionDirection = direction;
  }
}

function makeInput(id, { start = null, end = null, direction = null, type = "text" } = {}) {
  const el = new StubElement(id, "INPUT");
  el.type = type;
  el.selectionStart = start;
  el.selectionEnd = end;
  el.selectionDirection = direction;
  return el;
}

function makeDom() {
  const docListeners = [];
  const winListeners = [];
  const byId = new Map();
  const scrollables = [];
  const alerts = [];
  const document = {
    activeElement: null,
    addEventListener(type, handler, capture) {
      docListeners.push({ type, handler, capture });
    },
    removeEventListener() {},
    getElementById(id) {
      return byId.get(id) || null;
    },
    querySelectorAll(selector) {
      assert.equal(selector, "[data-preserve-scroll][id]", "예상 밖 선택자");
      return scrollables.slice();
    },
  };
  const window = {
    innerWidth: 1000,
    innerHeight: 800,
    addEventListener(type, handler) {
      winListeners.push({ type, handler });
    },
    removeEventListener() {},
    alert(message) {
      alerts.push(String(message));
    },
  };
  return {
    window,
    document,
    docListeners,
    winListeners,
    scrollables,
    alerts,
    put(el) {
      byId.set(el.id, el);
      return el;
    },
    fireDoc(type, event) {
      docListeners.filter((l) => l.type === type).forEach((l) => l.handler(event));
    },
    fireWin(type, event) {
      winListeners.filter((l) => l.type === type).forEach((l) => l.handler(event));
    },
  };
}

const ABSENT = Symbol("absent");
const GLOBAL_KEYS = ["window", "document", "Node", "Element"];

function installDom(dom) {
  const saved = GLOBAL_KEYS.map((key) =>
    Object.hasOwn(globalThis, key) ? globalThis[key] : ABSENT,
  );
  globalThis.window = dom.window;
  globalThis.document = dom.document;
  globalThis.Node = StubNode;
  globalThis.Element = StubElement;
  return function restore() {
    GLOBAL_KEYS.forEach((key, index) => {
      if (saved[index] === ABSENT) delete globalThis[key];
      else globalThis[key] = saved[index];
    });
  };
}

/* 테스트 하나가 쓰는 stub — t.after 로 반드시 걷는다. */
function useDom(t, dom = makeDom()) {
  t.after(installDom(dom));
  return dom;
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

function tracked(promise) {
  const state = { settled: false, value: undefined, error: undefined };
  Promise.resolve(promise).then(
    (value) => {
      state.settled = true;
      state.value = value;
    },
    (error) => {
      state.settled = true;
      state.error = error;
    },
  );
  return state;
}

// ------------------------------------------------------------ boot import --

/* R3-01(#410) 이후 모듈 평가의 문서 부작용은 **0** 이다 — dismissal 부착은 bootProduct
   구성 시(개정 10), 토스트 DOM·배선은 React host 컨트롤러 몫이다. dynamic import 를
   유지하는 이유: 평가 시점 부작용이 0 이라는 사실 자체를 이 BOOT dom 스냅샷이 재고,
   행동 테스트는 하니스가 재현한 「구성 시 부착」 리스너를 같은 dom 으로 발화한다. */
const BOOT = makeDom();
const bootRestore = installDom(BOOT);
const popoverNs = await import(MODULES.Popover.href);
const preserveNs = await import(MODULES.Preserve.href);
const intentNs = await import(MODULES.Intent.href);
const undoNs = await import(MODULES.UndoToast.href);
const hostNs = await import("../../frontend/src/overlay/host.ts");
const instanceNs = await import("../../frontend/src/overlay/instance.ts");
bootRestore();

const { Popover } = popoverNs;
const { Preserve } = preserveNs;
const { Intent } = intentNs;
const { UndoToast } = undoNs;

/* 평가 시점 등록의 스냅샷 — 아래 구성 재현이 같은 dom 에 리스너를 붙이므로 **이 자리에서**
   떠야 한다(라이브 배열을 나중에 세면 관측이 오염된다). */
const BOOT_DOC_AT_EVAL = BOOT.docListeners.slice();
const BOOT_WIN_AT_EVAL = BOOT.winListeners.slice();

/* bootProduct 구성 몫의 재현 ① (개정 10) — dismissal 부착은 모듈 평가가 아니라 합성 루트
   호출이 진다. 행동 테스트(fireDoc/fireWin)는 이 리스너들을 발화한다. */
for (const attachment of Popover.documentAttachments) {
  if (attachment.target === "window") BOOT.window.addEventListener(attachment.type, attachment.handler);
  else BOOT.document.addEventListener(attachment.type, attachment.handler, attachment.capture);
}

/* bootProduct 구성 몫의 재현 ② — React host 가 effect 로 세우는 컨트롤러의 **실물**을
   슬롯에 앉힌다(UndoToast 파사드는 이 슬롯으로 위임한다). 다이얼로그 3 root 는 이 파일
   범위 밖이라 형상만 갖춘 자리표다 — 실물 fixture 사슬은 n05_overlay 가 진다. */
const BOOT_TOAST = BOOT.put(new StubElement("undoToast"));
const BOOT_TOAST_TEXT = BOOT.put(BOOT_TOAST.add(new StubElement("undoToastText")));
const BOOT_TOAST_BTN = BOOT.put(BOOT_TOAST.add(new StubElement("undoToastBtn", "BUTTON")));
instanceNs.setOverlayDialogHost(hostNs.createOverlayDialogController({
  doc: BOOT.document,
  notify: (message) => BOOT.window.alert(message),
  roots: {
    confirm: new StubElement("confirmModal"),
    choose: new StubElement("chooseModal"),
    prompt: new StubElement("promptModal"),
    toast: BOOT_TOAST,
  },
}).controller);

// ------------------------------------------------------------ 공개 표면 --

test("네 모듈은 계약 표와 정확히 같은 named export 하나씩만 낸다", () => {
  const namespaces = {
    Popover: popoverNs,
    Preserve: preserveNs,
    Intent: intentNs,
    UndoToast: undoNs,
  };
  for (const [name, ns] of Object.entries(namespaces)) {
    assert.deepEqual(Object.keys(ns), [name], `${name}: export 가 하나가 아닙니다`);
    assert.equal(ns.default, undefined, `${name}: default export 가 있습니다`);
    assert.deepEqual(Object.keys(ns[name]), SURFACE[name], `${name}: 공개 키가 다릅니다`);
    for (const key of SURFACE[name]) {
      if (name === "Popover" && key === "documentAttachments") {
        // 유일한 비함수 키 — 부착 명세 배열(집행은 bootProduct 구성 몫, R3-01).
        assert.equal(Array.isArray(ns[name][key]), true, "documentAttachments 가 배열이 아닙니다");
        continue;
      }
      assert.equal(typeof ns[name][key], "function", `${name}.${key} 가 함수가 아닙니다`);
    }
  }
});

test("네 파일의 음성 조건은 각각 0이다(§3)", () => {
  const forbidden = [
    [/^\(function \(\) \{/m, "top-level IIFE"],
    [/^\s*(?:window|globalThis)\.[A-Za-z_$][\w$]*\s*=/m, "자기 전역 생산"],
    [
      /\b(?:window|globalThis)\.(?:Modal|Popover|Bridge|Nav|escHtml|SheetPicker|PathTrack|Preserve|Intent|DataPicker|__push|AppCloseGuard|[A-Za-z]*Screen)\b/,
      "제품 전역 조회",
    ],
    [/export default/, "default export"],
    [/Object\.assign\(\s*(?:window|globalThis)/, "Object.assign(window, …)"],
  ];
  for (const [name, url] of Object.entries(MODULES)) {
    const source = readFileSync(url, "utf8");
    for (const [pattern, what] of forbidden) {
      assert.equal(pattern.test(source), false, `${name}: ${what} 가 남아 있습니다`);
    }
    assert.match(source, new RegExp(`^export const ${name} = `, "m"));
  }
});

// ---------------------------------------------------------- 싱글턴 identity --

test("반복 import 는 같은 네임스페이스·같은 객체를 준다(ESM 캐시)", async () => {
  for (const [name, url] of Object.entries(MODULES)) {
    const again = await import(url.href);
    const first = { Popover: popoverNs, Preserve: preserveNs, Intent: intentNs, UndoToast: undoNs }[name];
    assert.equal(again, first, `${name}: 네임스페이스가 갈렸습니다`);
    assert.equal(again[name], first[name], `${name}: 공개 객체가 갈렸습니다`);
  }
});

test("팝오버 레지스트리는 import 당 하나다 — 사본 평가는 갈린다(음성 대조)", async (t) => {
  const dom = useDom(t, BOOT);
  const closed = [];
  const panel = new StubElement("shared-panel");
  const unregister = Popover.register({
    isOpen: () => true,
    contains: (target) => panel.contains(target),
    close: () => closed.push("shared"),
  });
  t.after(unregister);

  // 같은 모듈을 다시 import 해도 같은 레지스트리다.
  const again = await import(MODULES.Popover.href);
  again.Popover.closeAll();
  assert.deepEqual(closed, ["shared"]);

  // 음성 대조 — 캐시 우회 평가는 **다른** 레지스트리이며 이 엔트리를 모른다.
  const fresh = await import(`${MODULES.Popover.href}?n05-second-instance=1`);
  assert.notEqual(fresh.Popover, Popover);
  fresh.Popover.closeAll();
  assert.deepEqual(closed, ["shared"], "사본이 원본 레지스트리를 닫았습니다");
  // 사본은 자기 부착 명세(다른 핸들러 정체성)를 내지만 문서에는 아무것도 붙이지 않는다 —
  // 부작용 이양(개정 10)의 음성 대조: keydown 은 하니스가 구성 재현으로 붙인 한 벌뿐이다.
  assert.notEqual(fresh.Popover.documentAttachments, Popover.documentAttachments);
  assert.equal(dom.docListeners.filter((l) => l.type === "keydown").length, 1,
    "사본 평가가 BOOT dom 에 리스너를 붙였습니다 — 모듈 평가의 문서 부작용은 0 이어야 한다");
});

test("Intent 의 CALL_CHAINS 는 모듈 스코프 하나다 — 사본은 자기 Map 을 갖는다", async () => {
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const running = Intent.chained("n05-shared-chain", () => gate);

  const again = await import(MODULES.Intent.href);
  const settled = tracked(again.Intent.settle("n05-shared-chain"));
  await flush();
  assert.equal(settled.settled, false, "공유 체인이면 아직 정산되지 않아야 한다");

  const fresh = await import(`${MODULES.Intent.href}?n05-second-instance=1`);
  const other = tracked(fresh.Intent.settle("n05-shared-chain"));
  await flush();
  assert.equal(other.settled, true, "사본은 빈 Map 이라 즉시 정산된다(음성 대조)");

  release("ok");
  await running;
  await flush();
  assert.equal(settled.settled, true);
});

test("모듈 평가의 문서 부작용은 0 — 8개 리스너는 부착 명세가 순서대로 낸다", () => {
  /* R3-01 이전에는 popover(7)·undo_toast(DOMContentLoaded) 가 평가 시점에 직접 붙였다.
     이관 후 평가는 부작용 0 이고, 같은 7개가 **명세**(documentAttachments)로 나와
     bootProduct 구성 시 이 순서 그대로 부착된다. DOMContentLoaded 배선은 토스트 DOM 이
     React host 소유가 되며 소멸했다 — 종류·순서·phase 가 곧 Escape 층화의 전제다. */
  assert.deepEqual(BOOT_DOC_AT_EVAL, [], "모듈 평가가 document 에 리스너를 붙였습니다");
  assert.deepEqual(BOOT_WIN_AT_EVAL, [], "모듈 평가가 window 에 리스너를 붙였습니다");
  assert.deepEqual(
    Popover.documentAttachments.map((a) => [a.target, a.type, a.capture === true]),
    [
      ["document", "click", true],
      ["document", "pointerdown", true],
      ["document", "pointerup", true],
      ["document", "pointercancel", true],
      ["document", "keydown", true],
      ["document", "focusout", true],
      ["document", "scroll", true],
      ["window", "resize", false],
    ],
    "부착 명세의 대상·종류·순서·phase 가 바뀌었습니다",
  );
  for (const attachment of Popover.documentAttachments) {
    assert.equal(typeof attachment.handler, "function", `${attachment.type}: handler 가 함수가 아닙니다`);
  }
});

// ------------------------------------------------------------- Popover --

test("register 는 cfg 셋을 요구하고, unregister 는 1회만 걷는다", (t) => {
  const dom = useDom(t, BOOT);
  const before = dom.docListeners.length;

  assert.throws(() => Popover.register(null), TypeError);
  assert.throws(() => Popover.register({ isOpen() {}, contains() {} }), TypeError);

  const closed = [];
  const cfg = { isOpen: () => true, contains: () => false, close: () => closed.push(1) };
  const unregister = Popover.register(cfg);
  // 같은 cfg 를 다시 등록해도 Set 이라 엔트리는 하나다.
  const unregister2 = Popover.register(cfg);
  Popover.closeAll();
  assert.deepEqual(closed, [1], "같은 cfg 가 두 번 닫혔습니다");

  unregister();
  unregister();                      // let registered 가 1회를 보장한다 — 재호출은 no-op
  Popover.closeAll();
  assert.deepEqual(closed, [1], "해제된 엔트리가 다시 닫혔습니다");

  // 두 번째 unregister 핸들도 이미 사라진 cfg 를 지우려 할 뿐 던지지 않는다.
  unregister2();
  assert.equal(dom.docListeners.length, before,
    "register 가 document 리스너를 늘렸습니다 — 리스너는 한 벌뿐이어야 한다");
});

test("바깥 pointerdown 이 닫고, 이어지는 같은 click 만 소비된다", (t) => {
  const dom = useDom(t, BOOT);
  const panel = new StubElement("p1");
  const inside = panel.add(new StubElement("p1-child"));
  const outside = new StubElement("outside");
  let open = true;
  const unregister = Popover.register({
    isOpen: () => open,
    contains: (target) => panel.contains(target),
    close: () => {
      open = false;
    },
  });
  t.after(unregister);

  // 안쪽 pointerdown 은 닫지 않는다.
  dom.fireDoc("pointerdown", { target: inside, button: 0, isPrimary: true, pointerId: 1 });
  assert.equal(open, true);

  dom.fireDoc("pointerdown", { target: outside, button: 0, isPrimary: true, pointerId: 2 });
  assert.equal(open, false);

  const consumed = [];
  dom.fireDoc("click", {
    target: outside,
    stopPropagation: () => consumed.push("stop"),
    preventDefault: () => consumed.push("prevent"),
  });
  assert.deepEqual(consumed, ["stop", "prevent"], "대응 click 이 소비되지 않았습니다");

  // 후보는 1회용 — 다음 click 은 그대로 통과한다.
  const next = [];
  dom.fireDoc("click", {
    target: outside,
    stopPropagation: () => next.push("stop"),
    preventDefault: () => next.push("prevent"),
  });
  assert.deepEqual(next, []);
});

test("우클릭·보조 포인터는 click 소비 후보가 아니다", (t) => {
  const dom = useDom(t, BOOT);
  const panel = new StubElement("p2");
  const outside = new StubElement("outside2");
  let open = true;
  const unregister = Popover.register({
    isOpen: () => open,
    contains: (target) => panel.contains(target),
    close: () => {
      open = false;
    },
  });
  t.after(unregister);

  dom.fireDoc("pointerdown", { target: outside, button: 2, isPrimary: true, pointerId: 3 });
  assert.equal(open, false, "우클릭도 닫기는 한다");

  const consumed = [];
  dom.fireDoc("click", {
    target: outside,
    stopPropagation: () => consumed.push("stop"),
    preventDefault: () => consumed.push("prevent"),
  });
  assert.deepEqual(consumed, [], "우클릭 뒤 click 이 잘못 소비됐습니다");
});

test("Escape·resize 는 전부 닫고, focusout·scroll 은 바깥일 때만 닫는다", (t) => {
  const dom = useDom(t, BOOT);
  const panel = new StubElement("p3");
  const inner = panel.add(new StubElement("p3-inner"));
  const other = panel.add(new StubElement("p3-other"));
  const outside = new StubElement("outside3");
  const log = [];
  let open = true;
  const unregister = Popover.register({
    isOpen: () => open,
    contains: (target) => panel.contains(target),
    close: () => {
      log.push("close");
      open = false;
    },
  });
  t.after(unregister);

  // 안쪽→안쪽 이동은 유지.
  dom.fireDoc("focusout", { target: inner, relatedTarget: other });
  assert.equal(open, true);
  // 안쪽→바깥 이동은 닫는다.
  dom.fireDoc("focusout", { target: inner, relatedTarget: outside });
  assert.equal(open, false);

  open = true;
  dom.fireDoc("scroll", { target: inner });     // 패널 내부 스크롤은 유지
  assert.equal(open, true);
  dom.fireDoc("scroll", { target: outside });   // 바깥 스크롤포트는 닫는다
  assert.equal(open, false);

  open = true;
  dom.fireDoc("keydown", { key: "a" });
  assert.equal(open, true);
  dom.fireDoc("keydown", { key: "Escape" });
  assert.equal(open, false);

  open = true;
  dom.fireWin("resize", {});
  assert.equal(open, false);
  assert.deepEqual(log, ["close", "close", "close", "close"],
    "닫힌 횟수 = 바깥 focusout·바깥 scroll·Escape·resize 넷");
});

test("place 는 실측 크기로 clamp·flip 하고 transform-origin 을 트리거에 맞춘다", (t) => {
  useDom(t, BOOT);
  const el = new StubElement("pop");
  el.rect = { left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100 };
  const anchor = new StubElement("anchor");
  anchor.rect = { left: 100, top: 200, bottom: 220, right: 150, width: 50, height: 20 };

  assert.deepEqual(Popover.place(el, anchor), { left: 100, top: 224, placement: "bottom" });
  assert.equal(el.style.left, "100px");
  assert.equal(el.style.top, "224px");
  assert.equal(el.style.transformOrigin, "25px top");
  assert.equal(el.dataset.placement, "bottom");

  // 아래 공간이 모자라면 위로 뒤집는다.
  const tall = new StubElement("pop2");
  tall.rect = { left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400 };
  const low = new StubElement("anchor2");
  low.rect = { left: 100, top: 700, bottom: 720, right: 150, width: 50, height: 20 };
  assert.deepEqual(Popover.place(tall, low), { left: 100, top: 296, placement: "top" });
  assert.equal(tall.style.transformOrigin, "25px bottom");
  assert.equal(tall.dataset.placement, "top");

  // 오른쪽 가장자리는 viewport 안으로 clamp 되고, offsetParent 는 기준면을 옮긴다.
  const edge = new StubElement("anchor3");
  edge.rect = { left: 950, top: 100, bottom: 120, right: 990, width: 40, height: 20 };
  const host = new StubElement("host");
  host.rect = { left: 40, top: 10, width: 900, height: 600, right: 940, bottom: 610 };
  const out = Popover.place(el, edge, { offsetParent: host });
  assert.deepEqual(out, { left: 796, top: 124, placement: "bottom" });
  assert.equal(el.style.left, "756px", "offsetParent 기준 absolute 좌표");
  assert.equal(el.style.top, "114px");
});

// ------------------------------------------------------------- Preserve --

test("around 는 재구성을 가로질러 포커스와 캐럿 범위를 실제로 되돌린다", (t) => {
  const dom = useDom(t);
  const before = makeInput("nameField", { start: 3, end: 7, direction: "backward" });
  dom.put(before);
  dom.document.activeElement = before;

  // 렌더가 같은 id 의 **새 요소**로 갈아치운다(innerHTML 재구성 모사).
  const after = makeInput("nameField");
  let rendered = false;
  Preserve.around(() => {
    rendered = true;
    dom.put(after);
    dom.document.activeElement = null;
  });

  assert.equal(rendered, true);
  assert.deepEqual(after.calls, [
    ["focus", { preventScroll: true }],
    ["setSelectionRange", 3, 7, "backward"],
  ]);
  assert.equal(after.selectionStart, 3);
  assert.equal(after.selectionEnd, 7);
  assert.deepEqual(before.calls, [], "옛 노드를 되살리지 않는다");
});

test("텍스트 필드가 아니면 캐럿을 건드리지 않고, id 가 사라지면 조용한 no-op 다", (t) => {
  const dom = useDom(t);
  const button = new StubElement("go", "BUTTON");
  dom.put(button);
  dom.document.activeElement = button;
  Preserve.around(() => {});
  assert.deepEqual(button.calls, [["focus", { preventScroll: true }]]);

  const number = makeInput("qty", { start: 1, end: 2, type: "number" });
  dom.put(number);
  dom.document.activeElement = number;
  Preserve.around(() => {});
  assert.deepEqual(number.calls, [["focus", { preventScroll: true }]],
    "number 입력에 setSelectionRange 를 걸면 예외가 난다");

  const gone = makeInput("vanishing", { start: 1, end: 1 });
  dom.document.activeElement = gone;
  Preserve.around(() => {});   // 같은 id 가 없다 → 보존할 것이 사라진 정상 귀결
  assert.deepEqual(gone.calls, []);
});

test("옵트인 스크롤만 복원되고, 복원은 포커스 뒤에 확정된다", (t) => {
  const dom = useDom(t);
  const marked = new StubElement("logBox");
  marked.scrollTop = 120;
  marked.scrollLeft = 30;
  dom.scrollables.push(marked);
  dom.put(marked);

  const plain = new StubElement("plainBox");
  plain.scrollTop = 40;
  dom.put(plain);

  Preserve.around(() => {
    marked.scrollTop = 0;
    marked.scrollLeft = 0;
    plain.scrollTop = 0;
  });

  assert.equal(marked.scrollTop, 120);
  assert.equal(marked.scrollLeft, 30);
  assert.equal(plain.scrollTop, 0, "표식 없는 컨테이너는 건드리지 않는다");
});

// --------------------------------------------------------------- Intent --

test("chained 는 키별로 순서를 세우고 다른 키는 서로 막지 않는다", async () => {
  const order = [];
  const gates = [];
  const send = (label) => () => {
    order.push(`start:${label}`);
    return new Promise((resolve) => {
      gates.push(() => {
        order.push(`end:${label}`);
        resolve(label);
      });
    });
  };

  const a1 = Intent.chained("n05-A", send("A1"));
  const a2 = Intent.chained("n05-A", send("A2"));
  const b1 = Intent.chained("n05-B", send("B1"));
  await flush();

  assert.deepEqual(order, ["start:A1", "start:B1"], "같은 키 두 번째가 먼저 떴습니다");
  gates.shift()();                 // A1 완료
  gates.shift()();                 // B1 완료
  await flush();
  assert.deepEqual(order, ["start:A1", "start:B1", "end:A1", "end:B1", "start:A2"]);
  gates.shift()();
  assert.deepEqual(await Promise.all([a1, a2, b1]), ["A1", "A2", "B1"]);
});

test("거부된 링은 체인을 고착시키지 않는다 — 실패를 호출자에게 그대로 전한다", async () => {
  const boom = new Error("영속 실패");
  const failed = Intent.chained("n05-R", () => Promise.reject(boom));
  await assert.rejects(failed, /영속 실패/);

  const recovered = await Intent.chained("n05-R", () => Promise.resolve("다음 호출"));
  assert.equal(recovered, "다음 호출", "거부된 링에 뒤 호출이 붙어 영영 안 돌았습니다");

  const third = tracked(Intent.chained("n05-R", () => Promise.resolve(3)));
  await flush();
  assert.equal(third.settled, true);
  assert.equal(third.value, 3);

  // 다 빠지면 settle 은 즉시 끝난다(꼬리 정리).
  const idle = tracked(Intent.settle("n05-R"));
  await flush();
  assert.equal(idle.settled, true);
});

test("settle 은 합류하지 않고 큐가 빌 때까지만 기다린다", async () => {
  let release;
  const started = [];
  const running = Intent.chained("n05-S", () => {
    started.push("write");
    return new Promise((resolve) => {
      release = resolve;
    });
  });
  const waiting = tracked(Intent.settle("n05-S"));
  await flush();
  assert.deepEqual(started, ["write"]);
  assert.equal(waiting.settled, false);

  release("done");
  await running;
  await flush();
  assert.equal(waiting.settled, true, "쓰기가 착지했는데 정산이 안 끝났습니다");
});

test("createFavorite 는 DOM 이 아니라 미결 의도로 다음 값을 계산한다(마지막 클릭이 이긴다)", async () => {
  const sent = [];
  const errors = [];
  const fav = Intent.createFavorite({
    send: (name, value) => {
      sent.push([name, value]);
      return Promise.resolve();
    },
    onError: (message) => errors.push(message),
  });

  const first = fav.toggle("n05-작업", false);
  assert.equal(fav.pending("n05-작업", false), true, "미결 의도가 서지 않았습니다");
  // 왕복 중 두 번째 클릭 — DOM 은 아직 낡은 false 지만 의도는 true 에서 출발한다.
  const second = fav.toggle("n05-작업", false);
  assert.equal(fav.pending("n05-작업", false), false);

  await Promise.all([first, second]);
  assert.deepEqual(sent, [["n05-작업", true], ["n05-작업", false]],
    "같은 의도를 두 번 보내 두 번째 토글이 사라졌습니다");
  assert.deepEqual(errors, []);
  // 마지막 링이 착지하면 미결 의도는 걷히고 판정은 DOM 으로 돌아간다.
  assert.equal(fav.pending("n05-작업", true), true);
});

test("createFavorite 의 실패는 onError 로 재진술되고 미결 의도는 걷힌다", async () => {
  const sent = [];
  const errors = [];
  let failNext = true;
  const fav = Intent.createFavorite({
    send: (name, value) => {
      sent.push([name, value]);
      if (failNext) {
        failNext = false;
        return Promise.reject(new Error("레지스트리 잠김"));
      }
      return Promise.resolve();
    },
    onError: (message) => errors.push(message),
  });

  await fav.toggle("n05-실패", false);
  assert.deepEqual(errors, ["즐겨찾기 변경 실패: 레지스트리 잠김"]);
  // 실패해도 링은 reject 하지 않으므로 꼬리 정리가 돌고 미결 의도가 걷힌다.
  assert.equal(fav.pending("n05-실패", false), false);

  // 그래서 다음 클릭은 다시 DOM 에서 출발한다 — 저장이 안 됐으니 별은 여전히 꺼져 있고
  // 같은 `true` 를 다시 보내는 것이 **오늘의 동작**이자 옳은 의미다(뒤 클릭이 막히지 않는다).
  await fav.toggle("n05-실패", false);
  assert.deepEqual(sent, [["n05-실패", true], ["n05-실패", true]],
    "한 번 실패한 뒤 클릭이 막혔습니다");
  assert.deepEqual(errors, ["즐겨찾기 변경 실패: 레지스트리 잠김"]);
});

// ------------------------------------------------------------ UndoToast --

test("show 는 문구를 싣고 10초 뒤 어포던스만 닫는다", (t) => {
  useDom(t, BOOT);
  t.mock.timers.enable({ apis: ["setTimeout"] });

  UndoToast.show("작업 1건을 삭제했습니다", () => {});
  assert.equal(BOOT_TOAST.hidden, false);
  assert.equal(BOOT_TOAST_TEXT.textContent, "작업 1건을 삭제했습니다");

  t.mock.timers.tick(9999);
  assert.equal(BOOT_TOAST.hidden, false, "10초 전에 닫혔습니다");
  t.mock.timers.tick(1);
  assert.equal(BOOT_TOAST.hidden, true);
});

test("새 show 는 이전 타이머를 갈아치우고, hide 는 타이머를 걷는다(1슬롯)", (t) => {
  useDom(t, BOOT);
  t.mock.timers.enable({ apis: ["setTimeout"] });

  UndoToast.show("첫 삭제", () => {});
  t.mock.timers.tick(9000);
  UndoToast.show("둘째 삭제", () => {});
  assert.equal(BOOT_TOAST_TEXT.textContent, "둘째 삭제");
  t.mock.timers.tick(9000);
  assert.equal(BOOT_TOAST.hidden, false, "이전 타이머가 새 토스트를 닫았습니다");
  t.mock.timers.tick(1000);
  assert.equal(BOOT_TOAST.hidden, true);

  UndoToast.show("셋째 삭제", () => {});
  UndoToast.hide();
  assert.equal(BOOT_TOAST.hidden, true);
  t.mock.timers.tick(20000);
  assert.equal(BOOT_TOAST.hidden, true, "걷힌 타이머가 되살아났습니다");
});

test("되돌리기 버튼은 콜백을 부르고 닫으며, 실패는 alert 로 시끄럽게 알린다", async (t) => {
  const dom = useDom(t, BOOT);
  dom.alerts.length = 0;
  BOOT_TOAST.hidden = true;
  BOOT_TOAST_BTN.disabled = false;

  // host 컨트롤러 기립(구성 재현)이 버튼 리스너를 정확히 1벌 심는다 — DOMContentLoaded
  // 배선은 토스트 DOM 이 React host 소유가 되며 소멸했다(R3-01).
  assert.equal(BOOT_TOAST_BTN.listeners.get("click").length, 1);

  // 콜백이 없으면 아무 일도 없다.
  UndoToast.hide();
  await BOOT_TOAST_BTN.dispatch("click", {});
  assert.equal(BOOT_TOAST_BTN.disabled, false);

  const calls = [];
  UndoToast.show("삭제했습니다", async () => {
    calls.push(BOOT_TOAST_BTN.disabled);
  });
  await BOOT_TOAST_BTN.dispatch("click", {});
  assert.deepEqual(calls, [true], "왕복 중 버튼이 잠기지 않았습니다");
  assert.equal(BOOT_TOAST.hidden, true);
  assert.equal(BOOT_TOAST_BTN.disabled, false);
  assert.deepEqual(dom.alerts, []);

  UndoToast.show("삭제했습니다", () => Promise.reject(new Error("복원 실패")));
  await BOOT_TOAST_BTN.dispatch("click", {});
  assert.deepEqual(dom.alerts, ["복원 실패"]);
  assert.equal(BOOT_TOAST.hidden, false, "실패했는데 토스트가 닫혔습니다");
  assert.equal(BOOT_TOAST_BTN.disabled, false);

  UndoToast.hide();
});
