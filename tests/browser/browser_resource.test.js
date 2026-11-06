/* Real Chrome checks for sealed CSS geometry and the vendored rhwp serializer.
 * HWPX_WEB_ARTIFACT_ROOT is verified by the caller before this resource lane runs. */
import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { resolve, basename } from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { chromium } from "playwright-core";
import { browserServer, corpusDocuments, probePage, rendered, repo, corpus } from "./browser_probe.js";

const { layout, press, probe } = JSON.parse(readFileSync(new URL("./render_fixtures.json", import.meta.url)));
let browser;
let server;
let generated;

before(async () => {
  generated = await mkdtemp(resolve(tmpdir(), "hwpx-browser-"));
  server = await browserServer(generated);
  browser = await chromium.launch({ channel: "chrome", timeout: 10000 });
});
after(async () => { await browser?.close(); await server?.close(); if (generated) await rm(generated, { recursive: true, force: true }); });

const close = (actual, expected, tolerance = 0.5) => assert.ok(Math.abs(actual - expected) <= tolerance,
  `expected ${actual} ≈ ${expected}`);
const boxOrder = (boxes) => boxes.every((box, i) => !i || boxes[i - 1].right <= box.left + 0.5);
const rootCss = () => server.css;

function assertCommonAuthoring(m, where) {
  assert.deepEqual(m.brokenWords, [], where);
  if (m.outlineShown) {
    assert.deepEqual([...new Set(m.rowHeights)], [28], where);
    assert.ok(m.outlineOverflowX <= 0 && m.rowsInside, where);
    assert.deepEqual(m.guides, { slot: "solid", option: "dashed" }, where);
  }
  assert.ok(m.iconSizes.every(([w, h]) => w === 32 && h === 32), where);
  assert.ok(m.toolbarRows === 1 && m.toolbarOverflowY <= 1, where);
  assert.ok(m.headRows === 1 && m.headSaveInside && m.headOverflowX <= 0, where);
  assert.ok(m.noteInside && m.noteEllipsis && m.selectionOverflowY <= 0, where);
  assert.ok(m.statusLinks.length && m.statusLinks.every((link) =>
    link.decoration === "none" && link.border === "none" && link.background === "rgba(0, 0, 0, 0)"), where);
}

function assertWideAuthoring(m, where) {
  assert.ok(m.outlineShown && m.splitterShown && !m.railShown && !m.scrimShown, where);
  assert.equal(m.propertiesPosition, "static", where);
  assert.ok(boxOrder([m.outline, m.splitterOutline, m.center, m.splitterProperties, m.properties]), where);
  assert.ok(m.documentEdgeFree, `${where}: ${m.documentEdgeHit}`);
  close(m.outline.width, Math.min(16 * m.root, 0.30 * m.body.width));
  close(m.properties.width, Math.min(20 * m.root, 0.35 * m.body.width));
}

function assertNarrowAuthoring(m, where) {
  const rail = m.container <= 52 * m.root + 0.5;
  assert.ok(!m.splitterShown && m.railShown === rail && m.outlineShown !== rail, where);
  if (!rail) assert.ok(m.outline.right <= m.center.left + 0.5, where);
  assert.ok(m.propertiesPosition === "absolute" && m.scrimShown, where);
  close(m.properties.top, m.body.top, 1);
  close(m.properties.bottom, m.body.bottom, 1);
  close(m.properties.right, m.body.right, 1);
  close(m.scrim.width, m.body.width, 1);
  assert.ok(m.documentEdgeHit.includes("authoring-properties") ||
    ["LABEL", "INPUT", "H2", "DIV", "BUTTON", "FORM"].includes(m.documentEdgeHit), where);
}

function authoringHtml(scale, appStyle = "", { trial = null, max = false, trialOpen = true } = {}) {
  let scaffold = layout._SCAFFOLD;
  if (trial) {
    const dock = layout._TRIAL_DOCK.replace("{result}", layout._TRIAL_RESULTS[trial]);
    scaffold = scaffold.replace('  <footer class="authoring-status">', `${dock}  <footer class="authoring-status">`);
    scaffold = scaffold.replace('<div class="authoring-shell">',
      `<div class="authoring-shell${max ? " dock-max" : ""}${trialOpen ? " trial-open" : ""}">`);
  }
  return rendered(scaffold, { css_path: rootCss(), scale, rows: layout._OUTLINE_ROWS,
    app_style: appStyle, icon: layout._ICON });
}

async function measure(html, width, height, script, options = {}) {
  const { page, context } = await probePage(browser, server, html, { width, height, ...options });
  try {
    await page.waitForTimeout(120);
    return await page.evaluate(`(${script})()`);
  } finally { await context.close(); }
}

test("authoring columns, rail and sheet stay usable across window widths and font scales", async () => {
  for (const [width, height] of [[1440, 900], [1028, 740], [1000, 700], [744, 560]]) {
    for (const scale of ["normal", "large", "larger"]) {
      const m = await measure(authoringHtml(scale), width, height, layout._MEASURE);
      const where = `${width}x${height}@${scale}`;
      const narrow = m.container <= 64 * m.root + 0.5;
      assertCommonAuthoring(m, where);
      if (narrow) assertNarrowAuthoring(m, where);
      else assertWideAuthoring(m, where);
    }
  }
  const normal = await measure(authoringHtml("normal", "--authoring-outline-w:16rem;--authoring-properties-w:20rem"),
    1440, 900, layout._MEASURE);
  const large = await measure(authoringHtml("large", "--authoring-outline-w:16rem;--authoring-properties-w:20rem"),
    1440, 900, layout._MEASURE);
  close(normal.outline.width, 256);
  close(large.outline.width, 320);
  close(normal.properties.width, 320);
  close(large.properties.width, 400);
});

test("forced colors keep authoring lint and ownership markers distinct", async () => {
  const html = rendered(layout._FORCED, { css_path: rootCss() });
  const active = await measure(html, 800, 400, layout._MEASURE_FORCED, { forcedColors: "active" });
  const plain = await measure(html, 800, 400, layout._MEASURE_FORCED, { forcedColors: "none" });
  assert.equal(active.field.shadow, "none");
  assert.equal(active.marker.shadow, "none");
  assert.equal(active.field.bottom, "2px solid");
  assert.equal(active.marker.bottom, "1px dashed");
  assert.equal(active.marker.left, "1px dashed");
  assert.ok(plain.field.bottom.startsWith("0px") && plain.field.shadow !== "none");
  assert.equal(active.link, active.ref);
  for (const mode of [active, plain]) {
    assert.deepEqual([mode.error.line, mode.error.style], ["underline", "wavy"]);
    assert.deepEqual([mode.warning.line, mode.warning.style], ["underline", "dotted"]);
  }
  assert.notEqual(plain.error.color, plain.warning.color);
  assert.equal(active.error.color, active.warning.color);
  assert.equal(active.error.color, active.ink);
  assert.equal(active.pair, "dashed");
  assert.equal(plain.pair, "none");

  const ownership = rendered(probe._DOC, { css_path: rootCss(), width: "800",
    scaffold: probe._FORCED_COLORS_SCAFFOLD });
  const yes = await measure(ownership, 1000, 600, probe._MEASURE_FORCED_COLORS, { forcedColors: "active" });
  const no = await measure(ownership, 1000, 600, probe._MEASURE_FORCED_COLORS, { forcedColors: "none" });
  assert.equal(yes.matches, true);
  assert.equal(no.matches, false);
  for (const name of ["auto", "hand", "man"]) {
    assert.equal(yes.markers[name].boxShadow, "none");
    assert.deepEqual([yes.markers[name].borderBottomWidth, yes.markers[name].borderBottomStyle], ["3px", "solid"]);
    assert.notEqual(no.markers[name].boxShadow, "none");
    assert.equal(no.markers[name].borderBottomWidth, "0px");
  }
});

test("trial dock fills the remaining height for HWPX and TXT", async () => {
  for (const [width, height] of [[1440, 900], [1366, 768], [1028, 740]]) {
    for (const scale of ["normal", "large"]) {
      for (const media of ["hwpx", "txt"]) {
        const m = await measure(authoringHtml(scale, "", { trial: media }), width, height, layout._MEASURE_TRIAL);
        const where = `${media} ${width}x${height}@${scale}`;
        const floor = height <= 820 ? 0.32 : 0.4;
        assert.ok(m.body.height >= floor * m.viewport - 0.5, where);
        assert.ok(m.result.height >= 0.5 * m.panel.height, where);
        assert.ok(m.state.bottom <= m.result.top && m.result.top <= m.reason.top, where);
        assert.ok(m.output.top <= m.result.top && m.result.top < m.output.bottom, where);
        assert.deepEqual(m.folded, [false, false], where);
        assert.ok(m.summaryShown && m.caseGap >= 0, where);
        if (m.result.height > 12 * m.root + 0.5) close(Math.min(m.result.bottom, m.output.bottom), m.output.bottom, 12.5);
        if (width === 1440 && height === 900 && scale === "normal") assert.ok(m.result.height >= 215, where);
        if (media === "hwpx") close(m.frame.height, m.result.height, 1);
        else assert.ok(m.resultScrolls, where);
        assert.ok(Math.min(m.result.bottom, m.output.bottom) - m.result.top >= 0.5 * m.panel.height, where);
      }
    }
  }
  for (const media of ["hwpx", "txt"]) {
    const m = await measure(authoringHtml("normal", "", { trial: media, max: true }), 1440, 900, layout._MEASURE_TRIAL);
    assert.ok(m.result.height > 20 * m.root, media);
    close(m.result.bottom, m.output.bottom, 12.5);
    assert.ok(m.outputOverflow > 0 && m.outputOverflow <= 8 * m.root, media);
    assert.ok(m.state.bottom <= m.result.top && m.result.top <= m.reason.top, media);
  }
  for (const [width, height, trialOpen, floor] of [[1028, 740, true, 0.32], [1366, 768, true, 0.32],
    [1028, 740, false, 0.4], [1440, 900, true, 0.4]]) {
    const m = await measure(authoringHtml("normal", "", { trial: "hwpx", trialOpen }), width, height, layout._MEASURE_TRIAL);
    close(m.body.height, floor * m.viewport, 1);
  }
});

async function pressMeasure(scaffold, width, motion) {
  const html = rendered(probe._DOC, { css_path: rootCss(), width: String(width), scaffold });
  const { page, context } = await probePage(browser, server, html,
    { width: Math.max(width + 200, 800), motion });
  try {
    await page.waitForTimeout(120);
    const before = await page.evaluate(`(${probe._MEASURE})()`);
    const box = await page.locator("#probe").boundingBox();
    assert.ok(box, "press probe element exists");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(320);
    const held = await page.evaluate(`(${probe._MEASURE})()`);
    await page.mouse.up();
    return { dLeft: held.left - before.left, dWidth: held.width - before.width,
      transform: held.transform, active: held.active };
  } finally { await context.close(); }
}

test("row press preserves left edge with live motion and reduced-motion control", async () => {
  for (const [selector, width] of Object.entries(press.ROW_SURFACES)) {
    const scaffold = press.SCAFFOLDS[selector];
    const live = await pressMeasure(scaffold, width, "no-preference");
    const control = await pressMeasure(scaffold, width, "reduce");
    assert.ok(Math.abs(control.dLeft) <= 0.05, `${selector}: reduced-motion control ${control.dLeft}`);
    assert.equal(live.active, true, selector);
    assert.ok(Math.abs(live.dLeft) <= 1, `${selector}: ${live.dLeft}px, width delta ${live.dWidth}px`);
  }
  const box = '<button class="btn" id="probe" style="width:200px">미리보기</button>';
  const live = await pressMeasure(box, 400, "no-preference");
  const control = await pressMeasure(box, 400, "reduce");
  assert.notEqual(live.transform, "none");
  assert.equal(control.transform, "none");
  assert.ok(Math.abs(live.dLeft) > 0.5);
});

const roundtripHarness = `<!doctype html><meta charset="utf-8"><div id="editor" style="width:1200px;height:900px"></div>
<script type="module">
import { createStudio } from "/__sdk__/index.js";
const b64 = (bytes) => {
  let text = "";
  for (let i = 0; i < bytes.length; i += 32768) text += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return btoa(text);
};
let editor = null;
window.roundtrip = async (url, name) => {
  if (editor) editor.destroy();
  document.querySelector("#editor").innerHTML = "";
  editor = await createStudio(document.querySelector("#editor"), {
    studioUrl: new URL("/rhwp/studio/index.html", location.href).href,
    plugins: ["hwpctrl"], chrome: { menu: false, toolbar: true, statusbar: false } });
  const bytes = new Uint8Array(await (await fetch(url)).arrayBuffer());
  try { await editor.loadFile(bytes, name, { skipUnsavedGuard: true }); }
  catch (error) { return { error: String(error?.message || error) }; }
  return { exported: b64(await editor.exportHwpx()) };
};
window.harnessReady = true;
</script>`;

const fixtureBinary = () => {
  const path = resolve(process.env.HWPX_BROWSER_FIXTURE_BIN ?? resolve(repo, "target/debug/examples/browser_fixture.exe"));
  assert.ok(existsSync(path), `native browser fixture helper is missing: ${path}`);
  return path;
};

async function roundtripVerdict(page, bin, route, original, name, output) {
  const result = await page.evaluate(([url, label]) => window.roundtrip(url, label), [server.base + route, name]);
  if (result.error) return ["load_failed"];
  await writeFile(output, Buffer.from(result.exported, "base64"));
  const verdict = JSON.parse(execFileSync(bin, ["compare", original, output], { encoding: "utf8", timeout: 15000 }));
  assert.equal(verdict.editable, verdict.diagnostics.length === 0, name);
  return verdict.diagnostics.map((item) => item.kind).sort();
}

test("real rhwp Studio preserves the entire corpus and current authoring outputs", async () => {
  const bin = fixtureBinary();
  const docs = await corpusDocuments();
  assert.ok(docs.length > 0, "corpus cannot be empty");
  server.setProbe(roundtripHarness);
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage();
  try {
    await page.goto(`${server.base}/__probe__.html`, { waitUntil: "load" });
    await page.waitForFunction(() => window.harnessReady === true);
    const blocked = {};
    for (const [index, name] of docs.entries()) {
      const output = resolve(generated, `export-corpus-${index}.hwpx`);
      const verdict = await roundtripVerdict(page, bin, `/__corpus__/${name}`, resolve(corpus, name), basename(name), output);
      if (verdict.length) blocked[name] = verdict;
    }
    assert.deepEqual(blocked, {
      "metatag_s1/G3-package-carriers.hwpx": ["entry_set_changed", "entry_set_changed", "xml_changed"],
      "real/filled_notice_marine.hwpx": ["load_failed"],
    });
    execFileSync(bin, ["generate", generated], { encoding: "utf8", timeout: 30000 });
    for (const [index, name] of ["batch-fields.hwpx", "slot-20-35-table-end.hwpx",
      "slot-20-36-table-end.hwpx", "slot-36-36-table-end.hwpx", "trailing-empty-field.hwpx",
      "slot-20-34-trailing-empty-field.hwpx"].entries()) {
      const original = resolve(generated, name);
      const output = resolve(generated, `export-generated-${index}.hwpx`);
      const verdict = await roundtripVerdict(page, bin, `/__generated__/${name}`, original, name, output);
      assert.deepEqual(verdict, [], `${name}: ${verdict.join(", ")}`);
    }
  } finally { await context.close(); }
});
