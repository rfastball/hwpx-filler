/* UX-08(#1027) — 저작 작업대의 열 폭·분할선·좁은 폭 시트, TXT 편집기 테마, 강제 색상 표지.
 *
 * 실제 배치(열 폭·시트가 편집면을 덮는가)는 실렌더 게이트(tests/test_web_authoring_layout.py)가
 * 잰다. 여기서는 그 배치를 움직이는 순수 번역(키·끌기 → 폭), 개인화 서비스의 싣기·영속,
 * 표면이 내는 접근성 표지, 그리고 CSS 가 그 표지를 실제로 겨누는지를 잰다. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { keyedWidth, draggedWidth, WIDTH_STEP, cyclePanels, PANEL_CYCLE } from "../../frontend/src/screens/authoring_layout.ts";
import { AuthoringScreen } from "../../frontend/src/screens/authoring.ts";
import { createAuthoringController } from "../../frontend/src/screens/authoring_controller.ts";
import { AUTHORING_WIDTH_BOUNDS, clampAuthoringWidth, createPersonalization } from "../../frontend/src/shell/preferences.ts";
import { lintpadIsDark, lintpadDarkFacet } from "../../frontend/src/editorview/txt_lintpad.ts";

const css = (name) => readFileSync(new URL(`../../frontend/css/${name}`, import.meta.url), "utf8");

test("분할선 키보드: 구조는 → 가 넓히고, 속성은 ← 가 넓힌다 — 한 번에 1rem, Home/End 는 범위 끝", () => {
  assert.equal(WIDTH_STEP, 16);
  assert.equal(keyedWidth("outline", 240, "ArrowRight"), 256);
  assert.equal(keyedWidth("outline", 240, "ArrowLeft"), 224);
  assert.equal(keyedWidth("properties", 300, "ArrowLeft"), 316);
  assert.equal(keyedWidth("properties", 300, "ArrowRight"), 284);
  assert.equal(keyedWidth("outline", 240, "Home"), AUTHORING_WIDTH_BOUNDS.outline.min);
  assert.equal(keyedWidth("properties", 240, "End"), AUTHORING_WIDTH_BOUNDS.properties.max);
  // 범위 밖으로 밀리지 않는다.
  assert.equal(keyedWidth("outline", AUTHORING_WIDTH_BOUNDS.outline.max, "ArrowRight"), AUTHORING_WIDTH_BOUNDS.outline.max);
  // 폭과 무관한 키는 기본 동작을 막지 않는다(null).
  assert.equal(keyedWidth("outline", 240, "Tab"), null);
  assert.equal(keyedWidth("outline", 240, "ArrowUp"), null);
});

test("분할선 끌기: 화면 px 이동을 뿌리 글자 크기로 나눠 기준 px 로 바꾼다(150% 배율에서 24px = 1rem)", () => {
  assert.equal(draggedWidth("outline", 240, 24, 24), 256);
  assert.equal(draggedWidth("outline", 240, 16, 16), 256);
  assert.equal(draggedWidth("properties", 300, -24, 24), 316);
  assert.equal(draggedWidth("outline", 240, -1000, 16), AUTHORING_WIDTH_BOUNDS.outline.min);
  assert.equal(draggedWidth("properties", 240, -1000, 16), AUTHORING_WIDTH_BOUNDS.properties.max);
});

test("개인화 경계값은 Python settings.AUTHORING_WIDTH_BOUNDS 와 같고, 비유효 입력은 저장값 없음(null)이다", () => {
  const settings = readFileSync(new URL("../../src/hwpxfiller/external/settings.py", import.meta.url), "utf8");
  for (const [panel, { min, max }] of Object.entries(AUTHORING_WIDTH_BOUNDS)) {
    assert.match(settings, new RegExp(`"${panel}": \\(${min}, ${max}\\)`), panel);
  }
  assert.equal(clampAuthoringWidth("outline", null), null);
  assert.equal(clampAuthoringWidth("outline", "헛것"), null);
  assert.equal(clampAuthoringWidth("outline", 250.4), 250);
  assert.equal(clampAuthoringWidth("outline", 10), AUTHORING_WIDTH_BOUNDS.outline.min);
});

function personalizationDom(t) {
  const props = new Map();
  const app = {
    style: {
      setProperty: (key, value) => props.set(key, value),
      removeProperty: (key) => props.delete(key),
      getPropertyValue: (key) => props.get(key) || "",
    },
  };
  const attrs = new Map();
  const alerts = [];
  const saved = { window: globalThis.window, document: globalThis.document, getComputedStyle: globalThis.getComputedStyle };
  globalThis.window = { alert: (message) => alerts.push(String(message)), dispatchEvent: () => true };
  globalThis.document = {
    documentElement: { setAttribute: (k, v) => attrs.set(k, v), getAttribute: (k) => attrs.get(k) ?? null },
    querySelector: (selector) => (selector === ".app" ? app : null),
    querySelectorAll: () => [],
  };
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => "240px" });
  t.after(() => Object.assign(globalThis, saved));
  return { props, alerts };
}

test("개인화: 부팅 주입이 저장 폭을 rem 으로 싣고, null 은 기본값(변수 제거)으로 둔다", (t) => {
  const dom = personalizationDom(t);
  const pers = createPersonalization({ bridge: { hostReady: () => false } });
  pers.apply({ font_scale: "normal", master_width: 240, authoring_widths: { outline: 256, properties: null } });
  assert.equal(dom.props.get("--authoring-outline-w"), "16rem");
  assert.equal(dom.props.has("--authoring-properties-w"), false);
  assert.equal(pers.authoringWidth("outline"), 256);
  assert.equal(pers.authoringWidth("properties"), null);
  // 배율 동사는 authoring_widths 없이 apply 를 부른다 — 사용자가 맞춘 폭이 사라지면 안 된다.
  pers.setFontScale("larger");
  assert.equal(dom.props.get("--authoring-outline-w"), "16rem");
  assert.equal(pers.authoringWidth("outline"), 256);
});

test("개인화: 끌기 중(set)은 영속하지 않고, 놓기(save)만 클램프된 기준 px 로 Python 에 남긴다", async (t) => {
  const dom = personalizationDom(t);
  const calls = [];
  const pers = createPersonalization({
    bridge: { hostReady: () => true, setAuthoringWidth: (panel, width) => { calls.push([panel, width]); return Promise.resolve(width); } },
  });
  assert.equal(pers.setAuthoringWidth("outline", 300), 300);
  assert.deepEqual(calls, []);
  assert.equal(pers.saveAuthoringWidth("properties", 9999), AUTHORING_WIDTH_BOUNDS.properties.max);
  assert.deepEqual(calls, [["properties", AUTHORING_WIDTH_BOUNDS.properties.max]]);
  assert.equal(dom.props.get("--authoring-properties-w"), `${AUTHORING_WIDTH_BOUNDS.properties.max / 16}rem`);
  // 저장 거절(Promise reject)은 삼키지 않고 경보로 올린다.
  const failing = createPersonalization({
    bridge: { hostReady: () => true, setAuthoringWidth: () => Promise.reject(new Error("범위 밖")) },
  });
  failing.saveAuthoringWidth("outline", 200);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(dom.alerts, ["범위 밖"]);
});

test("TXT 편집기 테마: data-theme 명시값이 이기고, 「시스템」은 OS 선호를 따른다 — 그 판정이 vendor darkTheme facet 으로 선다", () => {
  assert.equal(lintpadIsDark("dark", false), true);
  assert.equal(lintpadIsDark("light", true), false);
  assert.equal(lintpadIsDark(null, true), true);
  assert.equal(lintpadIsDark(null, false), false);
  assert.equal(lintpadDarkFacet(true), true);
  assert.equal(lintpadDarkFacet(false), false);
});

test("TXT 편집기 검색 패널: vendor 가 그리는 패널 클래스 전부에 제품 토큰 색이 선다", () => {
  const authoring = css("authoring.css");
  for (const selector of [".cm-panels", ".cm-panel input.cm-textfield", ".cm-panel button.cm-button", ".cm-panel label", ".cm-searchMatch", ".cm-searchMatch-selected"]) {
    const rule = authoring.match(new RegExp(`\\.authoring-document \\.cm-editor ${selector.replace(/[.[\]]/g, "\\$&")}\\{([^}]*)\\}`));
    assert.ok(rule, `${selector} 규칙이 없습니다`);
    assert.match(rule[1], /var\(--/, `${selector} 가 토큰을 쓰지 않습니다`);
    assert.doesNotMatch(rule[1], /#[0-9a-f]{3,8}\b/i, `${selector} 에 색 리터럴`);
  }
  // vendor 버튼의 밝은 그라디언트를 걷는다.
  assert.match(authoring, /\.cm-panel button\.cm-button\{[^}]*background-image:none/);
});

test("강제 색상: 린트 강조 두 종은 그림자 대신 실보더로 모양이 갈린다", () => {
  const forced = css("forced-colors.css");
  assert.match(forced, /\.cm-txtField\{border-bottom:2px solid Highlight\}/);
  assert.match(forced, /\.cm-txtMarker\{border:1px dashed CanvasText\}/);
});

test("입력 테두리는 대비 검사를 받는 조작 경계 토큰을 쓴다", () => {
  assert.match(css("base.css"), /\.field\{background:var\(--a-card\);border:1px solid var\(--n-border-control\)/);
});

test("고정폭 글꼴은 토큰 하나 — 제품 CSS 에 글꼴 스택 리터럴이 남지 않는다", () => {
  for (const name of ["base.css", "authoring.css", "editor.css", "draftcard.css", "job.css", "library.css"]) {
    assert.doesNotMatch(css(name), /Consolas|Cascadia/, name);
  }
  assert.match(css("tokens.css"), /--font-mono:"Cascadia Code","Consolas","D2Coding",ui-monospace,monospace;/);
});

// ---- 표면(authoring.ts) — 분할선·레일·가림막의 접근성 표지 ----
function harness() {
  const snapshot = { active_id: "a", tabs: [{ id: "a", name: "a.txt", path: "a.txt", revision: 0, values: {}, selected: {} }] };
  const client = {
    async dispatch(_screen, action, payload) { if (action === "activate") snapshot.active_id = payload.session_id; return { ok: true, value: {} }; },
    async invoke() { return { ok: true, value: null }; },
  };
  const controller = createAuthoringController({ client,
    runtime: { model: () => ({ getSnapshot: () => snapshot, subscribe: () => () => {} }), loadInitial: async () => {} },
    modal: { choose: async () => "save", prompt: async () => null, confirm: async () => true },
    navigation: { go() {}, refresh: async () => {} },
  });
  return controller;
}

const layout = { authoringWidth: (panel) => (panel === "outline" ? 256 : null), setAuthoringWidth: (_p, w) => w, saveAuthoringWidth: (_p, w) => w };
const render = (controller) => renderToStaticMarkup(createElement(AuthoringScreen, { controller, layout }));

test("구조 분할선은 늘 서고, 속성 분할선·가림막은 속성 패널이 열렸을 때만 선다", async () => {
  const controller = harness();
  await controller.activate("a");
  const closed = render(controller);
  assert.ok(closed.includes(`<div role="separator" tabindex="0" class="authoring-splitter authoring-splitter-outline" aria-orientation="vertical" aria-label="구조 패널 너비" aria-valuemin="${AUTHORING_WIDTH_BOUNDS.outline.min}" aria-valuemax="${AUTHORING_WIDTH_BOUNDS.outline.max}" aria-valuenow="256"></div>`), closed);
  assert.ok(!closed.includes("속성 패널 너비"));
  assert.ok(!closed.includes("authoring-scrim"));
  assert.ok(closed.includes('<button type="button" class="authoring-rail-toggle" aria-expanded="false">구조 패널 보기</button>'));
  controller.update({ panel: "properties", commandType: "create_field", selected: null, selection: { start: 0, end: 2 } });
  const open = render(controller);
  const splitter = open.indexOf('aria-label="속성 패널 너비"');
  assert.ok(splitter > 0 && splitter < open.indexOf('<form class="authoring-properties"'), "속성 분할선은 속성 패널 바로 앞(왼쪽)에 선다");
  assert.ok(open.includes('<div class="authoring-scrim" aria-hidden="true"></div>'));
  // UX-01 의 보이는 「닫기」는 그대로 남는다.
  assert.ok(open.includes('<h2 id="authoring-properties-title">속성</h2><button type="button" class="btn sm">닫기</button>'));
});

test("좁은 폭 규칙은 창이 아니라 작업대 폭의 rem 컨테이너 질의이고, 편집면을 겹치는 것은 가림막을 둔 시트뿐이다", () => {
  const authoring = css("authoring.css");
  assert.match(authoring, /#scr-authoring\.on\{[^}]*container:authoring\/inline-size/);
  assert.doesNotMatch(authoring, /@media\s*\(max-width:\s*\d+px\)/, "px 미디어 질의가 남았습니다");
  const narrow = authoring.slice(authoring.indexOf("@container authoring (max-width:64rem)"));
  assert.ok(narrow.length > 0);
  assert.match(narrow, /\.authoring-scrim\{display:block;position:absolute;inset:0/);
  assert.match(narrow, /\.authoring-body:not\(\.outline-open\)>\.authoring-outline\{display:none\}/);
  // 구조는 핵심 패널이라 레일 문턱(52rem)이 속성 시트 문턱(64rem)보다 좁다 — 1024px 에서도 구조가 선다.
  const rail = authoring.slice(authoring.indexOf("@container authoring (max-width:52rem)"));
  assert.match(rail, /\.authoring-body:not\(\.outline-open\)>\.authoring-outline\{display:none\}/);
  const sheet = authoring.slice(authoring.indexOf("@container authoring (max-width:64rem)"), authoring.indexOf("@container authoring (max-width:52rem)"));
  assert.doesNotMatch(sheet, /authoring-outline\{display:none/, "64rem 문턱에서 구조를 접으면 안 됩니다");
  // 고정 px 열 폭이 남지 않는다.
  assert.doesNotMatch(authoring, /grid-template-columns:\s*\d+px/);
});

test("F6 순환: 그려진 패널만 돌고, 접힌 구조는 레일 버튼이 대신 서서 키보드로 닿는다", () => {
  assert.ok(PANEL_CYCLE.split(",").includes(".authoring-rail-toggle"));
  const focused = [];
  const panel = (name, { shown = true, control = false } = {}) => ({
    name,
    contains: (node) => node === name,
    matches: () => control,
    getClientRects: () => ({ length: shown ? 1 : 0 }),
    querySelector: () => ({ focus: () => focused.push(`${name}:first`) }),
    focus: () => focused.push(name),
  });
  // 좁은 폭: 구조는 숨고 레일 버튼이 보인다.
  const narrow = [panel("toolbar"), panel("rail", { control: true }), panel("outline", { shown: false }), panel("canvas"), panel("dock")];
  assert.equal(cyclePanels(narrow, "toolbar", false).name, "rail");
  assert.deepEqual(focused, ["rail"]);
  assert.equal(cyclePanels(narrow, "rail", false).name, "canvas");
  assert.equal(cyclePanels(narrow, "toolbar", true).name, "dock");
  // 넓은 폭: 레일이 숨고 구조가 선다 — 구조 안 첫 조작으로 간다.
  focused.length = 0;
  const wide = [panel("toolbar"), panel("rail", { shown: false, control: true }), panel("outline"), panel("canvas")];
  assert.equal(cyclePanels(wide, "toolbar", false).name, "outline");
  assert.deepEqual(focused, ["outline:first"]);
  assert.equal(cyclePanels([], null, false), null);
});
