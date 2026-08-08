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
import {
  existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, extname, join, relative, resolve } from "node:path";
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

function patternHasName(pattern, name) {
  const names = [];
  bindingNames(pattern, names);
  return names.includes(name);
}

function declarationOwner(tree, name) {
  for (const statement of tree.body) {
    const declaration = statement.type === "ExportNamedDeclaration"
      ? statement.declaration : statement;
    if (!declaration) continue;
    if (declaration.type === "VariableDeclaration") {
      for (const declarator of declaration.declarations) {
        if (patternHasName(declarator.id, name)) return declarator;
      }
    } else if (declarationNames(declaration).includes(name)) return declaration;
  }
  return null;
}

function blockDirectlyBinds(block, name) {
  return block.body.some((statement) => {
    if (statement.type === "VariableDeclaration" && statement.kind !== "var") {
      return statement.declarations.some((item) => patternHasName(item.id, name));
    }
    return ["FunctionDeclaration", "ClassDeclaration"].includes(statement.type)
      && statement.id?.name === name;
  });
}

function functionVarBinds(node, name) {
  let found = false;
  const visit = (current) => {
    if (found || !current) return;
    if (current !== node && [
      "FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression",
    ].includes(current.type)) return;
    if (current.type === "VariableDeclaration" && current.kind === "var"
      && current.declarations.some((item) => patternHasName(item.id, name))) {
      found = true;
      return;
    }
    for (const child of childNodes(current)) visit(child);
  };
  visit(node.body);
  return found;
}

/**
 * top-level 선언 하나로 실제 resolve되는 참조만 센다. 같은 철자의 nested binding은
 * 별개 symbol이다 — 이름 출현 수로 세면 review P2의 거짓 초록이 돌아온다.
 */
function topLevelBindingReferences(tree, name, owner) {
  let count = 0;
  const walkBindingExtras = (pattern, includeDefaults = true) => {
    if (!pattern) return;
    walk(pattern.typeAnnotation);
    if (pattern.type === "AssignmentPattern") {
      walkBindingExtras(pattern.left, includeDefaults);
      if (includeDefaults) walk(pattern.right);
    } else if (pattern.type === "RestElement") {
      walkBindingExtras(pattern.argument, includeDefaults);
    } else if (pattern.type === "ObjectPattern") {
      for (const property of pattern.properties) {
        walkBindingExtras(
          property.type === "RestElement" ? property.argument : property.value,
          includeDefaults,
        );
      }
    } else if (pattern.type === "ArrayPattern") {
      for (const element of pattern.elements) walkBindingExtras(element, includeDefaults);
    }
  };
  const walk = (node) => {
    if (!node || node === owner) return;
    if (node.type === "Identifier") {
      if (node.name === name) count += 1;
      return;
    }
    if (node.type === "Program") {
      for (const statement of node.body) walk(statement);
      return;
    }
    if (node.type === "VariableDeclaration") {
      for (const declarator of node.declarations) {
        walkBindingExtras(declarator.id);
        walk(declarator.init);
      }
      return;
    }
    if (node.type === "VariableDeclarator") {
      walkBindingExtras(node.id);
      walk(node.init);
      return;
    }
    if (["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"].includes(node.type)) {
      const parameterShadows = node.params.some((param) => patternHasName(param, name));
      /* default 식은 함수 바깥이 아니라 parameter environment에서 resolve된다. 같은 이름의
         parameter가 하나라도 있으면 그 default들의 같은 철자는 top-level binding이 아니다. */
      for (const param of node.params) walkBindingExtras(param, !parameterShadows);
      walk(node.typeParameters);
      walk(node.returnType);
      const shadowed = node.id?.name === name
        || parameterShadows
        || functionVarBinds(node, name);
      if (!shadowed) walk(node.body);
      return;
    }
    if (node.type === "BlockStatement") {
      if (!blockDirectlyBinds(node, name)) for (const statement of node.body) walk(statement);
      return;
    }
    if (node.type === "CatchClause") {
      if (!patternHasName(node.param, name)) walk(node.body);
      return;
    }
    if (["ForInStatement", "ForOfStatement"].includes(node.type)) {
      if (node.left?.type === "VariableDeclaration"
        && node.left.kind !== "var"
        && node.left.declarations.some((item) => patternHasName(item.id, name))) return;
      walk(node.left);
      walk(node.right);
      walk(node.body);
      return;
    }
    if (node.type === "ForStatement") {
      if (node.init?.type === "VariableDeclaration"
        && node.init.kind !== "var"
        && node.init.declarations.some((item) => patternHasName(item.id, name))) return;
      walk(node.init);
      walk(node.test);
      walk(node.update);
      walk(node.body);
      return;
    }
    if (["ClassDeclaration", "ClassExpression"].includes(node.type)) {
      walk(node.superClass);
      walk(node.typeParameters);
      walk(node.superTypeArguments);
      for (const item of node.implements ?? []) walk(item);
      if (node.id?.name !== name) walk(node.body);
      return;
    }
    if (node.type === "ImportDeclaration" || node.type === "ExportAllDeclaration") return;
    if (node.type === "ExportNamedDeclaration") {
      walk(node.declaration);
      return;
    }
    if (node.type === "ExportDefaultDeclaration") {
      walk(node.declaration);
      return;
    }
    if (["MemberExpression", "OptionalMemberExpression"].includes(node.type)) {
      walk(node.object);
      if (node.computed) walk(node.property);
      return;
    }
    if (["Property", "PropertyDefinition", "MethodDefinition"].includes(node.type)) {
      if (node.computed) walk(node.key);
      walk(node.typeAnnotation);
      walk(node.value);
      return;
    }
    if (node.type === "LabeledStatement") {
      walk(node.body);
      return;
    }
    if (["BreakStatement", "ContinueStatement", "MetaProperty"].includes(node.type)) return;
    for (const child of childNodes(node)) walk(child);
  };
  walk(tree);
  return count;
}

function moduleFacts(source, name) {
  const tree = parse(source, name);
  const imports = [];
  const importedNames = [];
  const importBindings = new Map();
  const exports = [];
  const exportLocals = new Map();
  const reexports = [];
  const unknownDynamicImports = [];

  const visit = (node) => {
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
    if ((node.type === "ImportDeclaration" || node.type === "ExportNamedDeclaration"
      || node.type === "ExportAllDeclaration") && node.source) {
      imports.push(node.source.value);
    }
    if (node.type === "ImportDeclaration") {
      for (const specifier of node.specifiers) {
        if (specifier.type === "ImportSpecifier") {
          const imported = specifier.imported.name ?? specifier.imported.value;
          importedNames.push({
            source: node.source.value,
            name: imported,
          });
          importBindings.set(specifier.local.name, { source: node.source.value, imported });
        } else if (specifier.type === "ImportDefaultSpecifier") {
          importedNames.push({ source: node.source.value, name: "default" });
          importBindings.set(specifier.local.name, { source: node.source.value, imported: "default" });
        } else {
          importedNames.push({ source: node.source.value, name: "*" });
          importBindings.set(specifier.local.name, { source: node.source.value, imported: "*" });
        }
      }
    }
  }

  for (const node of tree.body) {
    if (node.type === "ExportDefaultDeclaration") {
      exports.push("default");
      exportLocals.set("default", null);
    }
    if (node.type === "ExportNamedDeclaration") {
      if (node.declaration) {
        const names = declarationNames(node.declaration);
        exports.push(...names);
        for (const declaredName of names) exportLocals.set(declaredName, declaredName);
      }
      else {
        for (const specifier of node.specifiers) {
          const exported = specifier.exported.name ?? specifier.exported.value;
          const local = specifier.local.name ?? specifier.local.value;
          exports.push(exported);
          if (node.source) {
            reexports.push({
              source: node.source.value,
              imported: local,
              exported,
            });
            exportLocals.set(exported, null);
          } else if (importBindings.has(local)) {
            const binding = importBindings.get(local);
            reexports.push({ ...binding, exported });
            exportLocals.set(exported, null);
          } else {
            exportLocals.set(exported, local);
          }
        }
      }
    }
    if (node.type === "ExportAllDeclaration") {
      const exported = node.exported?.name ?? node.exported?.value;
      if (exported) {
        exports.push(exported);
        exportLocals.set(exported, null);
        reexports.push({ source: node.source.value, imported: "*", exported });
      } else {
        reexports.push({ source: node.source.value, imported: "*", exported: "*" });
      }
    }
  }
  const internalReferences = new Map();
  for (const [exported, local] of exportLocals) {
    const owner = local ? declarationOwner(tree, local) : null;
    internalReferences.set(
      exported, owner ? topLevelBindingReferences(tree, local, owner) : 0,
    );
  }
  return {
    imports,
    importedNames,
    exports,
    reexports,
    internalReferences,
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
      if ((facts.internalReferences.get(exported) ?? 0) === 0) {
        dead.push(`${name}:${exported}`);
      }
    }
  }
  return dead.sort();
}

function productReachedTestOnly(analysis, testOnlyEntries) {
  return testOnlyEntries.filter((name) => analysis.productReached.has(name)).sort();
}

/* vendor region 수집은 **이름을 열거하지 않는다**. 종전 술어는 `react|react-dom` 정규식이라
 * 같은 출하 바이트 안의 `scheduler` 2 region 을 아무도 안 봤다(react-dom 의 전이 런타임 —
 * 우리 source 가 import 하지 않으므로 dependency 축도 못 본다). 「집합 하나를 넓히고 형제를
 * 안 넓힌다」(#490)의 표본이라, 겨눔을 `node_modules/` 전부로 바꾼다. 계약 목록에 없는
 * 패키지가 출하에 들어오면 그 자체가 빨강이다. */
function vendorRegions(bundle) {
  return [...bundle.matchAll(
    /^\/\/#region (node_modules\/[^\r\n]+)$/gm,
  )].map((match) => match[1]).sort();
}

/* region 경로에서 패키지 이름을 뽑는다. scope 는 두 성분이 한 이름이라 `@` 를 따로 본다 —
 * 안 그러면 `@scope` 가 이름이 되어 lock 조회가 영영 빈손이고, 그 침묵이 "설치가 하나다"와
 * 똑같이 생긴다. */
function vendorPackageName(region) {
  // 중첩 설치는 **마지막** `node_modules/` 뒤가 진짜 패키지다 —
  // `react-dom/node_modules/scheduler/index.js` 를 앞에서 읽으면 `react-dom` 으로 보고돼
  // 중복 사본이 정상 이름표를 달고 지나간다(L16 반증).
  const parts = region.split("node_modules/").pop().split("/");
  return parts[0].startsWith("@") ? `${parts[0]}/${parts[1]}` : parts[0];
}

/* 수집 대상도 넓힌다. 종전은 manifest 의 `isEntry` 청크 **하나**만 읽었다 — entry 수가 1 임은
 * 단언돼 있지만, 비-entry JS 청크(동적 import 가 만드는 것)는 그 단언을 깨지 않은 채 vendor
 * 코드를 실어 나를 수 있다. sealed 트리의 `.js` 전부를 모집단으로 삼으면 그 자리가 닫힌다. */
function sealedVendorRegions(root) {
  return walkFiles(root)
    .filter((path) => path.endsWith(".js"))
    .sort()
    .flatMap((path) => vendorRegions(readFileSync(path, "utf8")))
    .sort();
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

  const leakedTestOnly = analyzeModules(new Map([
    ["main.js", 'import "./schema.js";'],
    ["schema.js", "export const schema = 1;"],
  ]), ["main.js"], ["schema.js"]);
  assert.deepEqual(productReachedTestOnly(leakedTestOnly, ["schema.js"]), ["schema.js"]);
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

  const shadowed = new Map([
    ["main.js", 'import "./lib.js";'],
    ["lib.js", [
      "export const value = 1;",
      "function consumeLocal() { const value = 2; return value; }",
      "consumeLocal();",
    ].join("\n")],
  ]);
  const shadowedAnalysis = analyzeModules(shadowed, ["main.js"]);
  assert.deepEqual(
    deadExports(shadowedAnalysis, importedProductNames(shadowedAnalysis, shadowed)),
    ["lib.js:value"],
    "nested scope의 같은 철자를 top-level export 소비로 오인했습니다.",
  );

  const parameterDefault = new Map([
    ["main.js", 'import "./lib.js";'],
    ["lib.js", [
      "export const value = 1;",
      "function consume(value = 2, copy = value) { return copy; }",
      "consume();",
    ].join("\n")],
  ]);
  const parameterAnalysis = analyzeModules(parameterDefault, ["main.js"]);
  assert.deepEqual(
    deadExports(parameterAnalysis, importedProductNames(parameterAnalysis, parameterDefault)),
    ["lib.js:value"],
    "parameter default의 같은 철자를 top-level export 소비로 오인했습니다.",
  );
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

  const namespace = new Map([
    ["main.js", 'import { lib } from "./barrel.js"; void lib.foo;'],
    ["barrel.js", 'export * as lib from "./lib.js";'],
    ["lib.js", "export const foo = 1; export const bar = 2;"],
  ]);
  const namespaceAnalysis = analyzeModules(namespace, ["main.js"]);
  assert.deepEqual(namespaceAnalysis.orphanFiles, []);
  assert.deepEqual(
    deadExports(namespaceAnalysis, importedProductNames(namespaceAnalysis, namespace)),
    [],
    "namespace re-export 소비는 원본 모듈의 export 전부를 소비합니다.",
  );
});

test("검출력 — vendor bundle region의 중복·누락·미열거·development 유입을 exact multiset이 문다", () => {
  const expected = [...CLOSURE.vendor_bundle_regions].sort();
  const clean = expected.map((name) => `//#region ${name}`).join("\n");
  assert.deepEqual(vendorRegions(clean), expected);
  assert.notDeepEqual(vendorRegions(`${clean}\n//#region ${expected[0]}`), expected);
  assert.notDeepEqual(
    vendorRegions(expected.slice(1).map((name) => `//#region ${name}`).join("\n")),
    expected,
  );
  // 이름 열거였다면 통과했을 둘. development 빌드 유입은 production region 을 그대로 둔 채
  // **더해지는** 형태라 "누락" 술어로는 안 잡힌다.
  assert.notDeepEqual(
    vendorRegions(`${clean}\n//#region node_modules/react-dom/cjs/react-dom.development.js`),
    expected,
  );
  assert.notDeepEqual(
    vendorRegions(`${clean}\n//#region node_modules/some-other-lib/index.js`),
    expected,
  );
});

test("검출력 — vendor 패키지 이름은 scope 두 성분을 한 이름으로 읽는다", () => {
  assert.equal(vendorPackageName("node_modules/react/index.js"), "react");
  assert.equal(vendorPackageName("node_modules/react-dom/cjs/react-dom.production.js"), "react-dom");
  assert.equal(vendorPackageName("node_modules/@scope/pkg/index.js"), "@scope/pkg");
  assert.equal(
    vendorPackageName("node_modules/react-dom/node_modules/scheduler/index.js"),
    "scheduler",
    "중첩 설치를 앞의 node_modules 로 읽으면 중복 사본이 정상 이름표를 답니다.",
  );
});

test("검출력 — vendor region은 entry가 아닌 청크에 숨어도 수집된다", () => {
  // 합성 트리를 **실제로 걸어** 수집한다. 「entry 하나만 읽는다」는 결함은 문자열 술어가
  // 아니라 수집 범위의 문제라, 범위를 바꾼 함수를 그대로 돌려야 반증이 성립한다.
  const root = mkdtempSync(join(tmpdir(), "r5-vendor-"));
  try {
    mkdirSync(resolve(root, "assets"), { recursive: true });
    writeFileSync(
      resolve(root, "assets/entry.js"),
      "//#region node_modules/react/index.js\n",
      "utf8",
    );
    writeFileSync(
      resolve(root, "assets/lazy-chunk.js"),
      "//#region node_modules/scheduler/index.js\n",
      "utf8",
    );
    // 코드가 아닌 형식은 모집단 밖이다 — 넣어 두고 안 잡히는지 함께 본다.
    writeFileSync(
      resolve(root, "assets/style.css"),
      "/*#region node_modules/not-code/index.js*/\n",
      "utf8",
    );
    assert.deepEqual(sealedVendorRegions(root), [
      "node_modules/react/index.js",
      "node_modules/scheduler/index.js",
    ], "entry 하나만 읽으면 lazy 청크의 vendor 코드가 무증상으로 출하됩니다.");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
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
  assert.deepEqual(
    productReachedTestOnly(analysis, testOnly),
    [],
    "test-only entry가 제품 entry에서도 도달됩니다 — 출하 그래프 격리가 깨졌습니다.",
  );
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

test("실 sealed bundle — 출하 vendor module region 전수가 계약과 exact multiset이다", () => {
  const root = resolve(REPO, "build/web");
  const manifestPath = resolve(root, ".vite/manifest.json");
  assert.ok(existsSync(manifestPath), "sealed bundle manifest가 없습니다 — 먼저 canonical web build를 실행하세요.");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const entries = Object.values(manifest).filter((item) => item.isEntry === true);
  assert.equal(entries.length, 1, "출하 bundle entry가 정확히 하나가 아닙니다.");

  const expected = [...CLOSURE.vendor_bundle_regions].sort();
  assert.ok(expected.length > 0, "vendor 계약이 비면 대조가 공허합니다.");
  assert.deepEqual(
    sealedVendorRegions(root),
    expected,
    "sealed bundle의 vendor runtime module cardinality가 계약과 어긋났습니다.",
  );
});

test("실 sealed bundle — vendor 계약의 패키지 이름이 lock의 설치 위치와 1:1이다", () => {
  // 계약 목록(무엇이 실렸는가)과 lock(무엇이 설치됐는가)을 **한자리에서** 잇는다. 이름이
  // 계약에만 있으면 유령이고, 설치가 둘 이상이면 중첩 사본이 출하에 들어올 길이 열린다.
  const lock = JSON.parse(readFileSync(resolve(REPO, "package-lock.json"), "utf8"));
  const names = [...new Set(
    CLOSURE.vendor_bundle_regions.map((region) => vendorPackageName(region)),
  )].sort();
  assert.ok(names.length > 0);
  for (const name of names) {
    const locations = Object.keys(lock.packages).filter(
      (path) => path === `node_modules/${name}` || path.endsWith(`/node_modules/${name}`),
    );
    assert.deepEqual(locations, [`node_modules/${name}`],
      `${name}: 출하 vendor의 설치 위치가 정확히 하나가 아닙니다 — ${locations}`);
  }
});
