/* 제품 전역의 최종 경계. 분석기 자체나 마이그레이션 수량은 테스트하지 않는다.
 * 실제 source와 sealed artifact만 파싱해 공개 전역 둘과 은퇴 별칭 부재를 확인한다. */
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { pathToFileURL } from "node:url";

import viteConfig from "../../vite.config.mjs";
import { SELFTEST_GLOBAL } from "../../frontend/src/selftest/api.js";

const { parseAst } = await import("vite");

const FRONTEND = new URL("../../frontend/", import.meta.url);
const SOURCE_HTML = new URL("index.html", FRONTEND);
const ARTIFACT = new URL(`${pathToFileURL(viteConfig.build.outDir).href}/`);
const SEAL_NAME = "web-artifact-seal.json";
const DEAD_ALIASES = new Set([
  "Copy", "escHtml", "Guard", "SegView", "Popover", "Preserve", "Intent", "UndoToast",
  "Modal", "SurfaceSheet", "GroupList", "Theme", "Personalization", "SheetPicker",
  "PathTrack", "Relink", "DataZone", "DataPicker", "EditorEntry", "LibraryScreen",
  "EditorScreen", "JobScreen", "WorkbenchScreen", "Nav", "AppCloseGuard", "Bridge", "__push",
]);
const CODE_SUFFIXES = [".js", ".mjs", ".ts", ".tsx"];

function childNodes(node) {
  const children = [];
  for (const [key, value] of Object.entries(node)) {
    if (["type", "start", "end", "loc"].includes(key)) continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item && typeof item === "object" && typeof item.type === "string") children.push(item);
      }
    } else if (value && typeof value === "object" && typeof value.type === "string") {
      children.push(value);
    }
  }
  return children;
}

function staticKey(node, computed = false) {
  if (!node) return null;
  if (!computed && node.type === "Identifier") return node.name;
  if (node.type === "Literal" && typeof node.value === "string") return node.value;
  if (node.type === "TemplateLiteral" && node.expressions.length === 0) {
    return node.quasis[0].value.cooked;
  }
  return null;
}

function globalRoot(node) {
  return node?.type === "Identifier" && ["window", "globalThis"].includes(node.name);
}

function inspectSource(source, filename) {
  const lang = filename.endsWith(".tsx") ? "tsx" : filename.endsWith(".ts") ? "ts" : "js";
  const program = parseAst(source, { lang });
  const references = [];
  const writes = [];

  function record(name, target, into) {
    if (typeof name === "string") into.push({ name, target });
  }

  function walk(node, parent = null) {
    if (node.type === "MemberExpression" && globalRoot(node.object)) {
      const name = staticKey(node.property, node.computed);
      record(name, node.object.name, references);
      const isWrite = (parent?.type === "AssignmentExpression" && parent.left === node)
        || (parent?.type === "UpdateExpression" && parent.argument === node);
      if (isWrite) record(name, node.object.name, writes);
    }

    if (node.type === "CallExpression" && node.callee?.type === "MemberExpression"
        && node.callee.object?.type === "Identifier" && node.callee.object.name === "Object") {
      const method = staticKey(node.callee.property, node.callee.computed);
      if (method === "defineProperty" && globalRoot(node.arguments[0])) {
        const name = staticKey(node.arguments[1], true);
        record(name, node.arguments[0].name, references);
        record(name, node.arguments[0].name, writes);
      }
      if (method === "assign" && globalRoot(node.arguments[0])) {
        for (const arg of node.arguments.slice(1)) {
          if (arg?.type !== "ObjectExpression") continue;
          for (const property of arg.properties) {
            const name = staticKey(property.key, property.computed);
            record(name, node.arguments[0].name, references);
            record(name, node.arguments[0].name, writes);
          }
        }
      }
    }

    for (const child of childNodes(node)) walk(child, node);
  }

  walk(program);
  return { references, writes };
}

function listCode(dir, prefix = "") {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const rel = `${prefix}${entry.name}`;
    if (entry.isDirectory()) files.push(...listCode(new URL(`${entry.name}/`, dir), `${rel}/`));
    else if (CODE_SUFFIXES.some((suffix) => entry.name.endsWith(suffix))) {
      files.push({ rel, url: new URL(entry.name, dir) });
    }
  }
  return files;
}

function scriptTags(html) {
  const withoutComments = html.replace(/<!--[\s\S]*?-->/g, "");
  return [...withoutComments.matchAll(/<script\b([^>]*)>/gi)].map((match) => match[1]);
}

function listArtifactFiles(dir = ARTIFACT, prefix = "") {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const rel = `${prefix}${entry.name}`;
    if (entry.isDirectory()) files.push(...listArtifactFiles(new URL(`${entry.name}/`, dir), `${rel}/`));
    else if (rel !== SEAL_NAME) files.push(rel);
  }
  return files.sort();
}

function loadArtifact() {
  const sealUrl = new URL(SEAL_NAME, ARTIFACT);
  if (!existsSync(sealUrl)) throw new Error("sealed web artifact가 없습니다 — `npm run build`가 먼저입니다.");
  const seal = JSON.parse(readFileSync(sealUrl, "utf8"));
  const bytes = new Map();
  for (const entry of seal.output.files) {
    const raw = readFileSync(new URL(entry.path, ARTIFACT));
    assert.equal(raw.length, entry.size, entry.path);
    assert.equal(createHash("sha256").update(raw).digest("hex"), entry.sha256, entry.path);
    bytes.set(entry.path, raw);
  }
  assert.deepEqual(listArtifactFiles(), seal.output.files.map((entry) => entry.path).sort());
  return { seal, bytes };
}

test("source 공개 전역은 __hwpx·__hwpxTest뿐이고 은퇴 별칭 참조가 없다", () => {
  const scans = ["src/", "js/"].flatMap((dir) => listCode(new URL(dir, FRONTEND), dir));
  const dead = [];
  const reservedWrites = new Set();
  for (const { rel, url } of scans) {
    const scan = inspectSource(readFileSync(url, "utf8"), rel);
    for (const ref of scan.references) if (DEAD_ALIASES.has(ref.name)) dead.push(`${rel}:${ref.name}`);
    for (const write of scan.writes) if (write.name?.startsWith("__hwpx")) reservedWrites.add(write.name);
  }
  assert.deepEqual(dead, []);
  assert.deepEqual([...reservedWrites], ["__hwpx"]);
  assert.equal(SELFTEST_GLOBAL, "__hwpxTest");
  assert.equal(existsSync(new URL("js/compat.js", FRONTEND)), false);
});

test("source HTML은 외부 module entry 하나만 실행한다", () => {
  const tags = scriptTags(readFileSync(SOURCE_HTML, "utf8"));
  assert.equal(tags.length, 1);
  assert.match(tags[0], /\btype=["']module["']/i);
  assert.match(tags[0], /\bsrc=["'][^"']+["']/i);
  assert.doesNotMatch(readFileSync(SOURCE_HTML, "utf8"), /\son[a-z]+\s*=/i);
});

test("sealed artifact 목록은 디스크 바이트와 크기·해시까지 일치한다", () => {
  const { seal, bytes } = loadArtifact();
  assert.ok(seal.output.files.length >= 4);
  assert.ok(bytes.has("index.html"));
});

test("sealed HTML·bundle도 module entry와 legacy 전역 부재를 지킨다", () => {
  const { bytes } = loadArtifact();
  const tags = scriptTags(bytes.get("index.html").toString("utf8"));
  assert.equal(tags.length, 1);
  assert.match(tags[0], /\btype=["']module["']/i);

  const dead = [];
  const reservedWrites = new Set();
  for (const [rel, raw] of bytes) {
    if (!rel.endsWith(".js") || rel.startsWith(".vite/")) continue;
    const scan = inspectSource(raw.toString("utf8"), rel);
    for (const ref of scan.references) if (DEAD_ALIASES.has(ref.name)) dead.push(`${rel}:${ref.name}`);
    for (const write of scan.writes) if (write.name?.startsWith("__hwpx")) reservedWrites.add(write.name);
  }
  assert.deepEqual(dead, []);
  assert.deepEqual([...reservedWrites], ["__hwpx"]);
});
