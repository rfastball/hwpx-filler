/* 셸 설정 모달(SettingsSheet)의 렌더 계약 — 슬라이스 D.
 *
 * 두 축을 잰다.
 *
 * 1. **렌더 요소 계약** — 실 서버 렌더(`react-dom/server`)로 요소 트리를 산출해, 소스의
 *    문자열이 아니라 **렌더 결과**를 본다: 세그먼트 둘이 서는가, 지금 값이 `aria-pressed`
 *    로 말해지는가, 프로브·게이트가 무는 안정 좌표(`data-set-theme`·`data-set-font`·
 *    `#settingsTitle`·`#settingsClose`)가 실제로 나오는가.
 * 2. **클릭 → 서비스 발신** — 이 면은 판정을 소유하지 않는다. 세그먼트를 누르면 셸 서비스
 *    (`Theme.set`·`Personalization.setFontScale`)가 **그 값 그대로** 불려야 하고, 이 면이
 *    지역 상태를 따로 들어 표시가 갈리는 일이 없어야 한다. 요소 트리의 `onClick` 을 직접
 *    불러 잰다 — node 환경이 실 클라이언트 커밋을 받쳐 주지 않으므로(react_root.test.js
 *    머리말) 실 클릭의 증거는 live 프로브(`shell_settings`) 몫이다.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  FONT_SCALE_LABELS,
  SETTINGS_MODAL_ID,
  SettingsSheetView,
  THEME_LABELS,
} from "../../frontend/src/screens/settings_sheet.ts";

function ports(theme = "system", scale = "normal") {
  const calls = { theme: [], scale: [], closed: [] };
  return {
    calls,
    props: {
      theme: { current: () => theme, set: (mode) => { calls.theme.push(mode); } },
      personalization: {
        currentFontScale: () => scale,
        setFontScale: (value) => { calls.scale.push(value); },
      },
      modal: { close: (id) => { calls.closed.push(id); } },
      currentTheme: theme,
      currentScale: scale,
    },
  };
}

function markup(theme, scale) {
  return renderToStaticMarkup(createElement(SettingsSheetView, ports(theme, scale).props));
}

/** 서버 렌더 산출에서 한 세그먼트의 `[값, aria-pressed]` 쌍을 뽑는다. */
function pressedPairs(html, axis) {
  const segment = html.split(`${axis}=""`)[1].split("</div>")[0];
  return Array.from(segment.matchAll(/data-value="([^"]+)" aria-pressed="([^"]+)"/g))
    .map((m) => [m[1], m[2]]);
}

test("설정 모달은 테마·글자 크기 두 행을 세그먼트로 편다", () => {
  const html = markup();
  assert.match(html, /<h3 id="settingsTitle">설정<\/h3>/);
  assert.match(html, /id="settingsClose"/);
  assert.equal(html.split('class="settings-row"').length - 1, 2, "설정 행이 둘이 아닙니다.");

  assert.deepEqual(pressedPairs(html, "data-set-theme").map((p) => p[0]),
    ["system", "light", "dark"]);
  assert.deepEqual(pressedPairs(html, "data-set-font").map((p) => p[0]),
    ["normal", "large", "larger"]);
  // 라벨 사전은 셸에서 이주한 문자열 그대로다 — 값이 아니라 문안이 소유의 증거다.
  for (const label of Object.values(THEME_LABELS)) assert.ok(html.includes(label), label);
  for (const label of Object.values(FONT_SCALE_LABELS)) assert.ok(html.includes(label), label);
});

test("지금 값만 aria-pressed 로 말한다 — 양극 대조", () => {
  const base = pressedPairs(markup("system", "normal"), "data-set-theme");
  assert.deepEqual(base, [["system", "true"], ["light", "false"], ["dark", "false"]]);

  const dark = pressedPairs(markup("dark", "larger"), "data-set-theme");
  assert.deepEqual(dark, [["system", "false"], ["light", "false"], ["dark", "true"]]);

  const larger = pressedPairs(markup("dark", "larger"), "data-set-font");
  assert.deepEqual(larger, [["normal", "false"], ["large", "false"], ["larger", "true"]]);
});

test("세그먼트 버튼은 생성 잠금을 타지 않는다 — 전역 설정이라 실행 상태와 무관하다", () => {
  const html = markup();
  assert.ok(!html.includes("data-busy-lock"), "설정 세그먼트에 생성 잠금이 걸렸습니다.");
  assert.ok(!html.includes("disabled"), "설정 세그먼트가 비활성으로 렌더됐습니다.");
});

test("클릭은 셸 서비스로 그대로 나간다 — 이 면은 판정을 소유하지 않는다", () => {
  const { calls, props } = ports("system", "normal");
  const tree = SettingsSheetView(props);
  const buttons = [];
  const walk = (node) => {
    if (node === null || node === undefined || typeof node !== "object") return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node.type === "function") { walk(node.type(node.props)); return; }
    if (node.props) {
      if (node.props.onClick) buttons.push(node.props);
      walk(node.props.children);
    }
  };
  walk(tree);

  const themeOpts = buttons.filter((p) => p["data-value"] && p.className.includes("settings-seg"));
  assert.equal(themeOpts.length, 6, "세그먼트 버튼이 여섯(3+3)이 아닙니다.");
  themeOpts.forEach((p) => p.onClick());
  assert.deepEqual(calls.theme, ["system", "light", "dark"]);
  assert.deepEqual(calls.scale, ["normal", "large", "larger"]);

  const close = buttons.find((p) => p.id === "settingsClose");
  close.onClick();
  assert.deepEqual(calls.closed, [SETTINGS_MODAL_ID]);
});
