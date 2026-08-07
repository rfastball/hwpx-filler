/* R5-02 — 제품 모듈 폐포·dead export·React runtime cardinality 게이트.
 *
 * 기존 센서의 소유를 빼앗지 않는다:
 *   - 전역 생산·우회·source/bundle: n10_global_hygiene.test.js
 *   - pywebview/__hwpx* 직접 접촉: pywebview_allowlist.test.js
 *   - createRoot 1·실창 mount marker 1: frontend build graph + live gate
 *
 * 이 파일은 그 사이의 실제 공백만 잇는다. 제품 entry에서 닿지 않는 파일, 소비자도 내부
 * 참조도 없는 export, 미사용 runtime dependency, lock/bundle의 중복 React를 각각 독립된
 * 결과로 센다. 파서는 이미 핀된 Vite(oxc)를 쓰며 새 lint 의존을 만들지 않는다. */
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, extname, relative, resolve } from "node:path";
import { dirname as posixDirname, join as posixJoin, normalize as posixNormalize }
  from "node:path/posix";
import { fileURLToPath } from "node:url";

let parseAst;
try {
  ({ parseAst } = await import("vite"));
} catch (thrown) {
  throw new Error(
    "프런트 툴체인(`vite`)을 못 불렀습니다 — R5 경계 게이트는 스킵하지 않습니다: "
    + thrown.message,
  );
}

const REPO = fileURLToPath(new URL("../..", import.meta.url));
const FRONTEND = resolve(REPO, "frontend");
const TEST_JS = resolve(REPO, "tests/js");
const CONTRACT = JSON.parse(
  readFileSync(resolve(REPO, "tests/static_closure_contract.json"), "utf8"),
);
const CLOSURE = CONTRACT.module_closure;

function walkFiles(root) {
  const out = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = resolve(root, entry.name);
    if (entry.isDirectory()) out.push(...walkFiles(path));
    else out.push(path);
  }
  return out;
}

function sourceLanguage(name) {
  if (name.endsWith(".tsx")) return "tsx";
  if (name.endsWith(".ts")) return "ts";
  return "js";
}

function parse(source, name) {
  try {
    return parseAst(source, { lang: sourceLanguage(name) });
  } catch (thrown) {
    throw new Error(`${name}: AST 파싱 실패 — 게이트가 볼 수 없는 코드는 허용하지 않습니다: ${thrown.message}`);
  }
}

function childNodes(node) {
  const out = [];
  for (const [key, value] of Object.entries(node)) {
    if (["type", "start", "end", "loc"].includes(key)) continue;
    if (Array.isArray(value)) {
      for (const item of value) if (item?.type) out.push(item);
    } else if (value?.type) out.push(value);
  }
  return out;
}

function bindingNames(pattern, into) {
  if (!pattern) return;
  if (pattern.type === "Identifier") into.push(pattern.name);
  else if (pattern.type === "ObjectPattern") {
    for (const property of pattern.properties) {
      bindingNames(property.type === "RestElement" ? property.argument : property.value, into);
    }
  } else if (pattern.type === "ArrayPattern") {
    for (const element of pattern.elements) bindingNames(element, into);
  } else if (pattern.type === "AssignmentPattern") bindingNames(pattern.left, into);
  else if (pattern.type === "RestElement") bindingNames(pattern.argument, into);
}

function declarationNames(declaration) {
  const out = [];
  if (declaration.id) bindingNames(declaration.id, out);
  for (const item of declaration.declarations ?? []) bindingNames(item.id, out);
  return out;
}

function countIdentifiers(node, name) {
  let count = 0;
  const visit = (current) => {
    if (current.type === "Identifier" && current.name === name) count += 1;
    for (const child of childNodes(current)) visit(child);
  };
  visit(node);
  return count;
}

function moduleFacts(source, name) {
  const tree = parse(source, name);
  const imports = [];
  const importedNames = [];
  const exports = [];
  const reexports = [];
  const identifierCounts = new Map();
  const selfIdentifierCounts = new Map();
  const unknownDynamicImports = [];

  const addSelfIdentifierCount = (name, count) => {
    selfIdentifierCounts.set(name, (selfIdentifierCounts.get(name) ?? 0) + count);
  };
  const recordDeclarationSelf = (declaration) => {
    if (declaration.type === "VariableDeclaration") {
      for (const declarator of declaration.declarations) {
        const declared = [];
        bindingNames(declarator.id, declared);
        for (const declaredName of declared) {
          addSelfIdentifierCount(declaredName, countIdentifiers(declarator, declaredName));
        }
      }
    } else {
      for (const declaredName of declarationNames(declaration)) {
        addSelfIdentifierCount(
          declaredName, countIdentifiers(declaration, declaredName),
        );
      }
    }
  };

  const visit = (node) => {
    if (node.type === "Identifier") {
      identifierCounts.set(node.name, (identifierCounts.get(node.name) ?? 0) + 1);
    }
    if (node.type === "ImportExpression") {
      if (node.source?.type === "Literal" && typeof node.source.value === "string") {
        imports.push(node.source.value);
      } else {
        unknownDynamicImports.push(source.slice(node.start, node.end));
      }
    }
    for (const child of childNodes(node)) visit(child);
  };
  visit(tree);

  for (const node of tree.body) {
    if (["VariableDeclaration", "FunctionDeclaration", "ClassDeclaration"].includes(node.type)) {
      recordDeclarationSelf(node);
    }
  }

  for (const node of tree.body) {
    if ((node.type === "ImportDeclaration" || node.type === "ExportNamedDeclaration"
      || node.type === "ExportAllDeclaration") && node.source) {
      imports.push(node.source.value);
    }
    if (node.type === "ImportDeclaration") {
      for (const specifier of node.specifiers) {
        if (specifier.type === "ImportSpecifier") {
          importedNames.push({
            source: node.source.value,
            name: specifier.imported.name ?? specifier.imported.value,
          });
        } else if (specifier.type === "ImportDefaultSpecifier") {
          importedNames.push({ source: node.source.value, name: "default" });
        } else {
          importedNames.push({ source: node.source.value, name: "*" });
        }
      }
    }
    if (node.type === "ExportDefaultDeclaration") exports.push("default");
    if (node.type === "ExportNamedDeclaration") {
      if (node.declaration) {
        const names = declarationNames(node.declaration);
        exports.push(...names);
        recordDeclarationSelf(node.declaration);
      }
      else {
        for (const specifier of node.specifiers) {
          const exported = specifier.exported.name ?? specifier.exported.value;
          exports.push(exported);
          addSelfIdentifierCount(exported, countIdentifiers(specifier, exported));
          if (node.source) {
            reexports.push({
              source: node.source.value,
              imported: specifier.local.name ?? specifier.local.value,
              exported,
            });
          }
        }
      }
    }
    if (node.type === "ExportAllDeclaration") {
      reexports.push({ source: node.source.value, imported: "*", exported: "*" });
    }
  }
  return {
    imports,
    importedNames,
    exports,
    reexports,
    identifierCounts,
    selfIdentifierCounts,
    unknownDynamicImports,
  };
}

function relativeModule(from, specifier) {
  return posixNormalize(posixJoin(posixDirname(from), specifier));
}

function packageRoot(specifier) {
  if (specifier.startsWith("@")) return specifier.split("/").slice(0, 2).join("/");
  return specifier.split("/")[0];
}

/** 값 기반 graph 분석기 — 실파일과 합성 음성 fixture가 같은 술어를 쓴다. */
export function analyzeModules(sources, entries, testOnlyEntries = []) {
  const facts = new Map([...sources].map(([name, source]) => [name, moduleFacts(source, name)]));
  const edges = new Map();
  const bare = new Set();
  for (const [name, item] of facts) {
    const local = [];
    for (const specifier of item.imports) {
      if (specifier.startsWith(".")) {
        const target = relativeModule(name, specifier);
        if (!sources.has(target)) {
          if (!target.endsWith(".css")) local.push(target); // 아래 missing에서 시끄럽게 신고
        } else local.push(target);
      } else if (!specifier.endsWith(".css")) bare.add(packageRoot(specifier));
    }
    edges.set(name, local);
  }

  const reachedFrom = (roots) => {
    const reached = new Set();
    const visit = (name) => {
      if (reached.has(name)) return;
      reached.add(name);
      for (const target of edges.get(name) ?? []) if (sources.has(target)) visit(target);
    };
    for (const root of roots) visit(root);
    return reached;
  };

  const cycles = [];
  const state = new Map();
  const visitCycle = (name, trail) => {
    if (state.get(name) === 1) {
      const start = trail.indexOf(name);
      cycles.push([...trail.slice(start), name]);
      return;
    }
    if (state.get(name) === 2) return;
    state.set(name, 1);
    for (const target of edges.get(name) ?? []) if (sources.has(target)) visitCycle(target, [...trail, name]);
    state.set(name, 2);
  };
  for (const name of sources.keys()) visitCycle(name, []);

  const productReached = reachedFrom(entries);
  const testReached = reachedFrom(testOnlyEntries);
  const orphanFiles = [...sources.keys()].filter(
    (name) => !productReached.has(name) && !testReached.has(name),
  ).sort();
  const missingImports = [...edges].flatMap(([name, targets]) => targets
    .filter((target) => !sources.has(target))
    .map((target) => `${name} -> ${target}`));
  const unknownDynamicImports = [...facts].flatMap(([name, item]) =>
    item.unknownDynamicImports.map((expression) => `${name}: ${expression}`));

  return {
    facts,
    bare,
    cycles,
    productReached,
    testReached,
    orphanFiles,
    missingImports,
    unknownDynamicImports,
  };
}

function productSources() {
  const excluded = new Set(CONTRACT.non_code_suffixes);
  return new Map(
    walkFiles(FRONTEND)
      .filter((path) => !excluded.has(extname(path)))
      .map((path) => [relative(FRONTEND, path).replaceAll("\\", "/"), readFileSync(path, "utf8")]),
  );
}

function testImportsIntoProduct(product) {
  const imported = new Map();
  for (const path of walkFiles(TEST_JS).filter((item) => item.endsWith(".test.js"))) {
    const source = readFileSync(path, "utf8");
    const facts = moduleFacts(source, relative(REPO, path).replaceAll("\\", "/"));
    for (const item of facts.importedNames) {
      if (!item.source.startsWith(".")) continue;
      const target = relative(FRONTEND, resolve(dirname(path), item.source)).replaceAll("\\", "/");
      if (!product.has(target)) continue;
      if (!imported.has(target)) imported.set(target, new Set());
      imported.get(target).add(item.name);
    }
  }
  return imported;
}

function importedProductNames(analysis, product) {
  const imported = testImportsIntoProduct(product);
  for (const [from, facts] of analysis.facts) {
    for (const item of facts.importedNames) {
      if (!item.source.startsWith(".")) continue;
      const target = relativeModule(from, item.source);
      if (!product.has(target)) continue;
      if (!imported.has(target)) imported.set(target, new Set());
      imported.get(target).add(item.name);
    }
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const [from, facts] of analysis.facts) {
      const consumers = imported.get(from);
      if (!consumers) continue;
      for (const item of facts.reexports) {
        if (!item.source.startsWith(".")) continue;
        const target = relativeModule(from, item.source);
        if (!product.has(target)) continue;
        const names = item.exported === "*"
          ? [...consumers].filter((name) => name !== "default")
          : (consumers.has("*") || consumers.has(item.exported) ? [item.imported] : []);
        if (names.length === 0) continue;
        if (!imported.has(target)) imported.set(target, new Set());
        const targetConsumers = imported.get(target);
        for (const name of names) {
          if (!targetConsumers.has(name)) {
            targetConsumers.add(name);
            changed = true;
          }
        }
      }
    }
  }
  return imported;
}

function deadExports(analysis, imported, publicModules = new Set()) {
  const dead = [];
  for (const [name, facts] of analysis.facts) {
    if (publicModules.has(name)) continue;
    const consumers = imported.get(name) ?? new Set();
    for (const exported of facts.exports) {
      if (consumers.has("*") || consumers.has(exported)) continue;
      /* 자기 선언 안의 참조(재귀 포함)는 소비자가 아니다. 선언 바깥에서 참조되는 helper는
         살리되, 자기 자신만 부르는 고립 export는 dead public surface로 남긴다. */
      const outsideDeclaration = (facts.identifierCounts.get(exported) ?? 0)
        - (facts.selfIdentifierCounts.get(exported) ?? 0);
      if (outsideDeclaration <= 0) dead.push(`${name}:${exported}`);
    }
  }
  return dead.sort();
}

function reactRegions(bundle) {
  return [...bundle.matchAll(
    /^\/\/#region (node_modules\/(?:react|react-dom)\/[^\r\n]+)$/gm,
  )].map((match) => match[1]);
}

function dependencyFindings(bare, pkg, lock, devOwners) {
  const declared = new Set(Object.keys(pkg.dependencies));
  const devDeclared = new Set(Object.keys(pkg.devDependencies));
  const ownedDev = new Set(Object.keys(devOwners));
  const locations = Object.keys(lock.packages);
  const installationLocations = (dependency) => locations.filter(
    (name) => name === `node_modules/${dependency}` || name.endsWith(`/node_modules/${dependency}`),
  );
  return {
    undeclaredRuntime: [...bare].filter((name) => !declared.has(name)).sort(),
    unusedRuntime: [...declared].filter((name) => !bare.has(name)).sort(),
    unownedDev: [...devDeclared].filter((name) => !ownedDev.has(name)).sort(),
    staleDevOwners: [...ownedDev].filter((name) => !devDeclared.has(name)).sort(),
    reactLocations: installationLocations("react"),
    reactDomLocations: installationLocations("react-dom"),
  };
}

test("검출력 — orphan·cycle을 문고 acyclic diamond와 exact test entry는 통과한다", () => {
  const cycle = new Map([
    ["main.js", 'import "./a.js";'],
    ["a.js", 'import "./b.js";'],
    ["b.js", 'import "./a.js";'],
    ["orphan.js", "export const orphan = 1;"],
    ["schema.js", "export const schema = 1;"],
  ]);
  const hit = analyzeModules(cycle, ["main.js"], ["schema.js"]);
  assert.deepEqual(hit.orphanFiles, ["orphan.js"]);
  assert.equal(hit.cycles.length, 1);

  const diamond = new Map([
    ["main.js", 'import "./a.js"; import "./b.js";'],
    ["a.js", 'import "./leaf.js";'],
    ["b.js", 'import "./leaf.js";'],
    ["leaf.js", "export const leaf = 1;"],
  ]);
  const miss = analyzeModules(diamond, ["main.js"]);
  assert.deepEqual(miss.orphanFiles, []);
  assert.deepEqual(miss.cycles, []);
});

test("검출력 — 동적 import도 모듈·runtime dependency 폐포에 들어가고 비리터럴은 거절한다", () => {
  const sources = new Map([
    ["main.js", 'import("./lazy.js"); import("ghost-runtime");'],
    ["lazy.js", "export const lazy = 1;"],
  ]);
  const analysis = analyzeModules(sources, ["main.js"]);
  assert.deepEqual(analysis.orphanFiles, []);
  assert.deepEqual([...analysis.bare], ["ghost-runtime"]);
  assert.deepEqual(analysis.unknownDynamicImports, []);

  const unknown = analyzeModules(new Map([
    ["main.js", "const path = './lazy.js'; import(path);"],
  ]), ["main.js"]);
  assert.deepEqual(unknown.unknownDynamicImports, ["main.js: import(path)"]);
});

test("검출력 — 소비·내부참조 없는 export만 dead이고 내부 helper·import 소비는 살린다", () => {
  const sources = new Map([
    ["main.js", 'import { entry } from "./lib.js"; void entry;'],
    ["lib.js", [
      "export function internalHelper() { return 1; }",
      "export function entry() { return internalHelper(); }",
      "export function abandoned() { return 0; }",
    ].join("\n")],
  ]);
  const analysis = analyzeModules(sources, ["main.js"]);
  const imported = importedProductNames(analysis, sources);
  assert.deepEqual(deadExports(analysis, imported), ["lib.js:abandoned"]);
});

test("검출력 — 재귀·export-list 고립 표면은 dead이고 barrel 소비는 원본까지 전파된다", () => {
  const recursive = new Map([
    ["main.js", 'import "./lib.js";'],
    ["lib.js", "export function abandoned() { return abandoned(); }"],
  ]);
  const recursiveAnalysis = analyzeModules(recursive, ["main.js"]);
  assert.deepEqual(
    deadExports(recursiveAnalysis, importedProductNames(recursiveAnalysis, recursive)),
    ["lib.js:abandoned"],
  );

  const localList = new Map([
    ["main.js", 'import "./lib.js";'],
    ["lib.js", "const abandoned = () => 0; export { abandoned };"],
  ]);
  const localListAnalysis = analyzeModules(localList, ["main.js"]);
  assert.deepEqual(
    deadExports(localListAnalysis, importedProductNames(localListAnalysis, localList)),
    ["lib.js:abandoned"],
  );

  const barrel = new Map([
    ["main.js", 'import { foo } from "./barrel.js"; void foo;'],
    ["barrel.js", 'export { foo } from "./lib.js";'],
    ["lib.js", "export const foo = 1;"],
  ]);
  const barrelAnalysis = analyzeModules(barrel, ["main.js"]);
  assert.deepEqual(barrelAnalysis.orphanFiles, []);
  assert.deepEqual(
    deadExports(barrelAnalysis, importedProductNames(barrelAnalysis, barrel)),
    [],
  );

  const exportAll = new Map([
    ["main.js", 'import { foo } from "./outer.js"; void foo;'],
    /* 소비 흐름의 역순으로 넣어 단일 순회로는 lib까지 못 닿게 한다 — fixpoint가 계약이다. */
    ["inner.js", 'export * from "./lib.js";'],
    ["outer.js", 'export * from "./inner.js";'],
    ["lib.js", "export const foo = 1;"],
  ]);
  const exportAllAnalysis = analyzeModules(exportAll, ["main.js"]);
  assert.deepEqual(exportAllAnalysis.orphanFiles, []);
  assert.deepEqual(
    deadExports(exportAllAnalysis, importedProductNames(exportAllAnalysis, exportAll)),
    [],
  );
});

test("검출력 — React bundle region의 중복·누락이 exact cardinality를 깨뜨린다", () => {
  const expected = CLOSURE.react_bundle_regions;
  const clean = expected.map((name) => `//#region ${name}`).join("\n");
  assert.deepEqual(reactRegions(clean), expected);
  assert.notDeepEqual(reactRegions(`${clean}\n//#region ${expected[0]}`), expected);
  assert.notDeepEqual(reactRegions(expected.slice(1).map((name) => `//#region ${name}`).join("\n")), expected);
});

test("검출력 — 미사용 runtime dependency와 중첩 React 설치를 함께 신고한다", () => {
  const findings = dependencyFindings(
    new Set(["react"]),
    { dependencies: { react: "1", unused: "1" }, devDependencies: { vite: "1" } },
    { packages: {
      "": {},
      "node_modules/react": {},
      "node_modules/a/node_modules/react": {},
      "node_modules/react-dom": {},
    } },
    { vite: "build owner" },
  );
  assert.deepEqual(findings.unusedRuntime, ["unused"]);
  assert.deepEqual(findings.reactLocations,
    ["node_modules/react", "node_modules/a/node_modules/react"]);
  assert.deepEqual(findings.unownedDev, []);
  assert.deepEqual(findings.staleDevOwners, []);
});

test("실 source — 모든 모듈은 product 또는 exact test-only 폐포이고 cycle/dead export가 0이다", () => {
  const sources = productSources();
  const entries = CLOSURE.product_entries;
  const testOnly = Object.keys(CLOSURE.test_only_entries);
  const publicModules = new Set(Object.keys(CLOSURE.generated_public_modules));
  const analysis = analyzeModules(sources, entries, testOnly);

  assert.ok(sources.size >= 60, `제품 코드를 ${sources.size}개만 읽었습니다 — 0건이 공허합니다.`);
  for (const entry of [...entries, ...testOnly, ...publicModules]) {
    assert.ok(sources.has(entry), `${entry}: 폐포 분류가 실파일을 앞질렀습니다.`);
  }
  assert.deepEqual(analysis.missingImports, [], "상대 import가 없는 파일을 가리킵니다.");
  assert.deepEqual(analysis.unknownDynamicImports, [], "정적으로 판독할 수 없는 dynamic import가 있습니다.");
  assert.deepEqual(analysis.cycles, [], `모듈 cycle: ${JSON.stringify(analysis.cycles)}`);
  assert.deepEqual(analysis.orphanFiles, [], `분류되지 않은 dead 파일: ${analysis.orphanFiles}`);

  const imported = importedProductNames(analysis, sources);
  assert.deepEqual(
    deadExports(analysis, imported, publicModules),
    [],
    "소비자도 파일 내부 참조도 없는 export가 있습니다.",
  );
});

test("실 dependency/lock — runtime 선언은 전부 사용되고 React 설치 위치는 각 하나다", () => {
  const sources = productSources();
  const analysis = analyzeModules(
    sources,
    CLOSURE.product_entries,
    Object.keys(CLOSURE.test_only_entries),
  );
  const pkg = JSON.parse(readFileSync(resolve(REPO, "package.json"), "utf8"));
  const lock = JSON.parse(readFileSync(resolve(REPO, "package-lock.json"), "utf8"));
  const findings = dependencyFindings(
    analysis.bare, pkg, lock, CONTRACT.dev_dependency_owners,
  );

  assert.deepEqual(findings.undeclaredRuntime, [], "선언되지 않은 runtime bare import가 있습니다.");
  assert.deepEqual(findings.unusedRuntime, [], "사용하지 않는 runtime dependency가 있습니다.");
  assert.deepEqual(findings.unownedDev, [], "책임이 분류되지 않은 devDependency가 있습니다.");
  assert.deepEqual(findings.staleDevOwners, [], "실제 선언을 앞질러 남은 devDependency 책임이 있습니다.");
  assert.ok(Object.values(CONTRACT.dev_dependency_owners).every((reason) => reason.length > 0));
  assert.deepEqual(findings.reactLocations, ["node_modules/react"],
    `React 설치 위치가 하나가 아닙니다: ${findings.reactLocations}`);
  assert.deepEqual(findings.reactDomLocations, ["node_modules/react-dom"],
    `ReactDOM 설치 위치가 하나가 아닙니다: ${findings.reactDomLocations}`);
});

test("실 sealed bundle — React/ReactDOM runtime module region이 각각 exact-once다", () => {
  const manifestPath = resolve(REPO, "build/web/.vite/manifest.json");
  assert.ok(existsSync(manifestPath), "sealed bundle manifest가 없습니다 — 먼저 canonical web build를 실행하세요.");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const entries = Object.values(manifest).filter((item) => item.isEntry === true);
  assert.equal(entries.length, 1, "출하 bundle entry가 정확히 하나가 아닙니다.");
  const bundle = readFileSync(resolve(REPO, "build/web", entries[0].file), "utf8");
  assert.deepEqual(
    reactRegions(bundle),
    CLOSURE.react_bundle_regions,
    "sealed bundle의 React runtime module cardinality가 어긋났습니다.",
  );
});
