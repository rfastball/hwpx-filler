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
  OUTPUT_FOLDER_BUSY_REASON,
  SETTINGS_MODAL_ID,
  SettingsSheetView,
  TEMPLATES_ROOT_BUSY_REASON,
  THEME_LABELS,
} from "../../frontend/src/screens/settings_sheet.ts";

const FOLDER = Object.freeze({
  directory: "C:\서고\Results",
  sourceLabel: "설정한 저장 폴더",
  notice: "",
  busy: false,
});

const ROOT = Object.freeze({
  directory: "D:\서식",
  sourceLabel: "설정한 폴더",
  notice: "",
  busy: false,
});

function ports(theme = "system", scale = "normal", folder = FOLDER, root = ROOT) {
  const calls = { theme: [], scale: [], closed: [], picked: 0, pickedRoot: 0, refreshed: 0 };
  return {
    calls,
    props: {
      theme: { current: () => theme, set: (mode) => { calls.theme.push(mode); } },
      personalization: {
        currentFontScale: () => scale,
        setFontScale: (value) => { calls.scale.push(value); },
      },
      modal: { close: (id) => { calls.closed.push(id); } },
      job: {
        subscribe: () => () => {},
        getRun: () => ({ running: folder.busy, lastFull: null }),
        pickOutputFolder: () => { calls.picked += 1; },
        client: { invoke: () => null },
        notify: () => {},
      },
      templates: {
        subscribe: () => () => {},
        getSnapshot: () => null,
        pickTemplatesRoot: () => { calls.pickedRoot += 1; return "D:\새서식"; },
        refreshCurrentScreen: () => { calls.refreshed += 1; },
        client: { invoke: () => null },
        notify: () => {},
      },
      currentTheme: theme,
      currentScale: scale,
      outputFolder: folder,
      templatesRoot: root,
    },
  };
}

function markup(theme, scale, folder, root) {
  return renderToStaticMarkup(
    createElement(SettingsSheetView, ports(theme, scale, folder, root).props),
  );
}

/** 서버 렌더 산출에서 한 세그먼트의 `[값, aria-pressed]` 쌍을 뽑는다. */
function pressedPairs(html, axis) {
  const segment = html.split(`${axis}=""`)[1].split("</div>")[0];
  return Array.from(segment.matchAll(/data-value="([^"]+)" aria-pressed="([^"]+)"/g))
    .map((m) => [m[1], m[2]]);
}

test("설정 모달은 테마·글자 크기·저장 폴더·서식 폴더 네 행을 편다", () => {
  const html = markup();
  assert.match(html, /<h3 id="settingsTitle">설정<\/h3>/);
  assert.match(html, /id="settingsClose"/);
  assert.equal(html.split('class="settings-row').length - 1, 4, "설정 행이 넷이 아닙니다.");

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
  const segments = html.split('class="settings-seg"').slice(1)
    .map((chunk) => chunk.split("</div>")[0]);
  assert.equal(segments.length, 2);
  for (const seg of segments) assert.ok(!seg.includes("disabled"), seg);
});

test("저장 폴더 행은 backend 도출을 그대로 그린다 — 경로·출처·사유", () => {
  const html = markup(undefined, undefined, {
    directory: "C:\서고\Results",
    sourceLabel: "기본값",
    notice: "설정한 저장 폴더를 찾을 수 없습니다. 기본 폴더로 되돌렸습니다.",
    busy: false,
  });
  assert.match(html, /id="settingsFolderLabel">저장 폴더</);
  assert.ok(html.includes('id="settingsOutDir"'));
  assert.ok(html.includes('value="C:\서고\Results"'));
  assert.ok(html.includes('id="settingsPickFolder"'));
  assert.ok(html.includes("기본값"), "출처 라벨이 없습니다.");
  // 조용한 하향 금지 — 사유는 경고로 선다.
  assert.ok(html.includes("설정한 저장 폴더를 찾을 수 없습니다."));
  // 경로가 있으면 경로 어포던스(폴더에서 보기·경로 복사)도 함께 선다.
  assert.ok(html.includes('data-track-act="reveal"'));
  assert.ok(html.includes('data-track-act="copy"'));
});

test("생성 중에는 찾아보기가 비활성이고 **사유를 병기한다** — 조용히 막지 않는다", () => {
  const open = markup(undefined, undefined, { ...FOLDER, busy: false });
  assert.equal(open.includes(OUTPUT_FOLDER_BUSY_REASON), false, "쉬는 중에 잠금 사유가 섰습니다.");

  const busy = markup(undefined, undefined, { ...FOLDER, busy: true });
  const button = busy.split('id="settingsPickFolder"')[1].split("</button>")[0];
  assert.ok(button.includes("disabled"), "생성 중인데 찾아보기가 열려 있습니다.");
  assert.ok(busy.includes(OUTPUT_FOLDER_BUSY_REASON), "비활성 사유가 병기되지 않았습니다.");
  assert.ok(busy.includes('id="settingsPickFolderReason"'));
});

test("찾아보기는 job 컨트롤러의 동사를 그대로 부른다 — 이 면이 왕복을 재조립하지 않는다", () => {
  const { calls, props } = ports();
  const tree = SettingsSheetView(props);
  const buttons = [];
  /* 훅을 쓰는 잎(PathActions 의 `useState`)은 렌더러 없이 부를 수 없다 — 이 걷기가 재는 것은
     **이 면이 붙인** onClick 의 목적지라 그런 잎은 건너뛴다(삼키는 것이 아니라 범위 밖이다). */
  const walk = (node) => {
    if (node === null || node === undefined || typeof node !== "object") return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node.type === "function") {
      let rendered;
      try { rendered = node.type(node.props); } catch { return; }
      walk(rendered);
      return;
    }
    if (node.props) {
      if (node.props.onClick) buttons.push(node.props);
      walk(node.props.children);
    }
  };
  walk(tree);
  const pick = buttons.find((p) => p.id === "settingsPickFolder");
  assert.ok(pick, "찾아보기 버튼이 없습니다.");
  pick.onClick();
  assert.equal(calls.picked, 1);
});

test("클릭은 셸 서비스로 그대로 나간다 — 이 면은 판정을 소유하지 않는다", () => {
  const { calls, props } = ports("system", "normal");
  const tree = SettingsSheetView(props);
  const buttons = [];
  /* 훅을 쓰는 잎(PathActions 의 `useState`)은 렌더러 없이 부를 수 없다 — 이 걷기가 재는 것은
     **이 면이 붙인** onClick 의 목적지라 그런 잎은 건너뛴다(삼키는 것이 아니라 범위 밖이다). */
  const walk = (node) => {
    if (node === null || node === undefined || typeof node !== "object") return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node.type === "function") {
      let rendered;
      try { rendered = node.type(node.props); } catch { return; }
      walk(rendered);
      return;
    }
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

test("서식 폴더 행은 backend 도출을 그대로 그린다 — 경로·출처·사유", () => {
  const html = markup(undefined, undefined, undefined, {
    directory: "D:\없는서식",
    sourceLabel: "설정한 폴더",
    notice: "설정한 서식 폴더를 찾을 수 없습니다: D:\없는서식",
    busy: false,
  });
  assert.match(html, /id="settingsTplDirLabel">서식 폴더</);
  assert.ok(html.includes('id="settingsTplDir"'));
  assert.ok(html.includes('id="settingsPickTplFolder"'));
  assert.ok(html.includes("설정한 폴더"), "출처 라벨이 없습니다.");
  /* 기본값으로 **내려가지 않는다** — 사라진 폴더도 그대로 서고 사유만 병기된다. */
  assert.ok(html.includes('value="D:\없는서식"'));
  assert.ok(html.includes('id="settingsTplDirNotice"'));
  assert.ok(html.includes("설정한 서식 폴더를 찾을 수 없습니다"));
});

test("생성 중에는 서식 폴더 찾아보기도 비활성 + 사유 병기 — 저장 폴더와 같은 술어", () => {
  const open = markup(undefined, undefined, undefined, { ...ROOT, busy: false });
  assert.equal(open.includes(TEMPLATES_ROOT_BUSY_REASON), false);

  const busy = markup(undefined, undefined, undefined, { ...ROOT, busy: true });
  const button = busy.split('id="settingsPickTplFolder"')[1].split("</button>")[0];
  assert.ok(button.includes("disabled"), "생성 중인데 서식 폴더 찾아보기가 열려 있습니다.");
  assert.ok(busy.includes(TEMPLATES_ROOT_BUSY_REASON));
  assert.ok(busy.includes('id="settingsPickTplFolderReason"'));
});

test("서식 폴더 찾아보기는 브리지 왕복 뒤 지금 화면을 다시 당긴다", async () => {
  const { calls, props } = ports();
  const tree = SettingsSheetView(props);
  const buttons = [];
  const walk = (node) => {
    if (node === null || node === undefined || typeof node !== "object") return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node.type === "function") {
      let rendered;
      try { rendered = node.type(node.props); } catch { return; }
      walk(rendered);
      return;
    }
    if (node.props) {
      if (node.props.onClick) buttons.push(node.props);
      walk(node.props.children);
    }
  };
  walk(tree);
  const pick = buttons.find((p) => p.id === "settingsPickTplFolder");
  assert.ok(pick, "서식 폴더 찾아보기 버튼이 없습니다.");
  pick.onClick();
  await new Promise((resolve) => { setTimeout(resolve, 0); });
  assert.equal(calls.pickedRoot, 1);
  assert.equal(calls.refreshed, 1, "재지정 성사 뒤 화면 재당김이 없습니다.");
});

test("두 폴더 행은 **같은 팩토리**가 그린다 — 좌표만 다르고 형상은 같다", () => {
  const html = markup();
  /* 사본이면 한쪽에만 붙는 어포던스·잠금 사유가 생긴다. 형상 동형을 구조로 잰다:
     같은 클래스·같은 자식 구성이 두 번 나오고 id 만 갈린다. */
  assert.equal(html.split('class="settings-row settings-row-folder"').length - 1, 2);
  assert.equal(html.split('class="settings-folder-row"').length - 1, 2);
  for (const id of ["settingsOutDir", "settingsTplDir",
    "settingsPickFolder", "settingsPickTplFolder",
    "settingsOutDirSource", "settingsTplDirSource"]) {
    assert.ok(html.includes(`id="${id}"`), `좌표 소실: ${id}`);
  }
  // 경로 어포던스도 두 행 모두에 선다(빌려 쓰지 않고 각자 포트의 client 를 쓴다).
  assert.equal(html.split('data-track-act="reveal"').length - 1, 2);
});

test("서식 폴더 행의 경로 어포던스는 **자기 포트**의 client·notify 를 쓴다", () => {
  const { props } = ports();
  const seen = [];
  props.templates.client = { invoke: (...args) => { seen.push(args); return null; } };
  const tree = SettingsSheetView(props);
  const rows = [];
  const walk = (node) => {
    if (node === null || node === undefined || typeof node !== "object") return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node.type === "function") {
      if (node.props && node.props.pathId === "settingsTplDir") rows.push(node.props);
      let rendered;
      try { rendered = node.type(node.props); } catch { return; }
      walk(rendered);
      return;
    }
    if (node.props) walk(node.props.children);
  };
  walk(tree);
  assert.equal(rows.length, 1, "서식 폴더 행이 팩토리로 서지 않았습니다.");
  assert.equal(rows[0].client, props.templates.client, "남의 컨트롤러 client 를 빌렸습니다.");
  assert.equal(rows[0].notify, props.templates.notify);
});
