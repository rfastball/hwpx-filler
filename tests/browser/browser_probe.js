import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, readdir } from "node:fs/promises";
import { resolve, relative, extname, basename } from "node:path";
import { fileURLToPath } from "node:url";

export const repo = resolve(fileURLToPath(new URL("../../", import.meta.url)));
export const corpus = resolve(repo, "tests/corpus");
const sdk = resolve(repo, "frontend/vendor/rhwp/editor");
const types = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".wasm": "application/wasm", ".css": "text/css", ".hwpx": "application/octet-stream" };

function inside(root, part) {
  const target = resolve(root, part);
  const path = relative(root, target);
  return path === "" || (!path.startsWith("..") && !path.startsWith("/") && !path.includes(":"));
}

export async function browserServer(generated = null) {
  const artifact = process.env.HWPX_WEB_ARTIFACT_ROOT;
  assert.ok(artifact, "HWPX_WEB_ARTIFACT_ROOT must name the verified sealed web artifact");
  const web = resolve(artifact);
  const manifest = JSON.parse(await readFile(resolve(web, ".vite/manifest.json"), "utf8"));
  const entries = Object.values(manifest).filter((entry) => entry?.isEntry === true);
  const css = Object.values(manifest).filter((entry) => entry?.file?.endsWith(".css"));
  assert.equal(entries.length, 1, "single sealed product entry");
  assert.equal(css.length, 1, "single sealed CSS chunk");
  await readFile(resolve(web, css[0].file));
  await readFile(resolve(web, "rhwp/studio/index.html"));
  let probe = "";
  const mounts = [["/__sdk__/", sdk], ["/__corpus__/", corpus],
    ...(generated ? [["/__generated__/", resolve(generated)]] : [])];
  const server = createServer(async (request, response) => {
    try {
      const route = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
      if (route === "/__probe__.html") {
        response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        response.end(probe);
        return;
      }
      const mount = mounts.find(([prefix]) => route.startsWith(prefix));
      const root = mount?.[1] ?? web;
      const path = mount ? route.slice(mount[0].length) : route.slice(1);
      if (!inside(root, path)) { response.writeHead(403); response.end(); return; }
      const target = resolve(root, path);
      const data = await readFile(target);
      response.writeHead(200, { "Content-Type": types[extname(target)] ?? "application/octet-stream" });
      response.end(data);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  const base = `http://127.0.0.1:${server.address().port}`;
  return { base, css: css[0].file, setProbe: (html) => { probe = html; },
    close: () => new Promise((done) => server.close(done)) };
}

export function rendered(template, values) {
  return template.replace(/\{([a-z_]+)\}/g, (found, key) => key in values ? values[key] : found)
    .replaceAll("{{", "{").replaceAll("}}", "}");
}

export async function probePage(browser, server, html, options = {}) {
  server.setProbe(html);
  const context = await browser.newContext({ viewport: { width: options.width ?? 800, height: options.height ?? 600 },
    reducedMotion: options.motion ?? "no-preference", ...(options.forcedColors ? { forcedColors: options.forcedColors } : {}) });
  const page = await context.newPage();
  await page.goto(`${server.base}/__probe__.html`, { waitUntil: "networkidle" });
  const resources = await page.evaluate(() => performance.getEntriesByType("resource").map((item) => item.name));
  assert.ok(resources.some((url) => url.endsWith(".css")), "sealed CSS was not loaded");
  assert.ok(resources.every((url) => url.startsWith(`${server.base}/`) && !url.includes("@vite/client")), resources.join("\n"));
  return { page, context };
}

export async function corpusDocuments(root = corpus, prefix = "") {
  const out = [];
  for (const item of await readdir(root, { withFileTypes: true })) {
    if (item.isDirectory()) out.push(...await corpusDocuments(resolve(root, item.name), `${prefix}${item.name}/`));
    else if (item.isFile() && item.name.toLowerCase().endsWith(".hwpx")) out.push(`${prefix}${item.name}`);
  }
  return out.sort();
}

export const leafName = (path) => basename(path);
