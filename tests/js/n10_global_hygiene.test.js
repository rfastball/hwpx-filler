/* 제품 전역의 최종 경계. 실제 source와 sealed artifact를 파싱해 공개 전역 쓰기를 확인한다. */
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
  const writes = [];

  function record(name) {
    if (typeof name === "string") writes.push(name);
  }

  function walk(node, parent = null) {
    if (node.type === "MemberExpression" && globalRoot(node.object)) {
      const name = staticKey(node.property, node.computed);
      const isWrite = (parent?.type === "AssignmentExpression" && parent.left === node)
        || (parent?.type === "UpdateExpression" && parent.argument === node);
      if (isWrite) record(name);
    }

    if (node.type === "CallExpression" && node.callee?.type === "MemberExpression"
        && node.callee.object?.type === "Identifier" && node.callee.object.name === "Object") {
      const method = staticKey(node.callee.property, node.callee.computed);
      if (method === "defineProperty" && globalRoot(node.arguments[0])) {
        const name = staticKey(node.arguments[1], true);
        record(name);
      }
      if (method === "assign" && globalRoot(node.arguments[0])) {
        for (const arg of node.arguments.slice(1)) {
          if (arg?.type !== "ObjectExpression") continue;
          for (const property of arg.properties) {
            const name = staticKey(property.key, property.computed);
            record(name);
          }
        }
      }
    }

    for (const child of childNodes(node)) walk(child, node);
  }

  walk(program);
  return writes;
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

test("source 공개 전역 쓰기는 __hwpx 하나뿐이고 selftest 이름은 __hwpxTest다", () => {
  const scans = ["src/", "js/"].flatMap((dir) => listCode(new URL(dir, FRONTEND), dir));
  const reservedWrites = new Set();
  for (const { rel, url } of scans) {
    const writes = inspectSource(readFileSync(url, "utf8"), rel);
    for (const name of writes) if (name.startsWith("__hwpx")) reservedWrites.add(name);
  }
  assert.deepEqual([...reservedWrites], ["__hwpx"]);
  assert.equal(SELFTEST_GLOBAL, "__hwpxTest");
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

test("sealed HTML·bundle도 module entry와 공개 전역 쓰기 경계를 지킨다", () => {
  const { bytes } = loadArtifact();
  const tags = scriptTags(bytes.get("index.html").toString("utf8"));
  assert.equal(tags.length, 1);
  assert.match(tags[0], /\btype=["']module["']/i);

  const reservedWrites = new Set();
  for (const [rel, raw] of bytes) {
    if (!rel.endsWith(".js") || rel.startsWith(".vite/")) continue;
    const writes = inspectSource(raw.toString("utf8"), rel);
    for (const name of writes) if (name.startsWith("__hwpx")) reservedWrites.add(name);
  }
  assert.deepEqual([...reservedWrites], ["__hwpx"]);
});
