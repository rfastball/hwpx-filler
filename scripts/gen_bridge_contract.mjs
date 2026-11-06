#!/usr/bin/env node
// Generate the frontend bridge contract from native Rust and checked JSON authorities.
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(root, "frontend/src/contract/contract.gen.ts");
const readJson = (name) => JSON.parse(readFileSync(path.join(root, name), "utf8"));
const quote = (value) => JSON.stringify(value);
const array = (name, values) => [
  `export const ${name} = [`,
  ...values.map((value) => `  ${quote(value)},`),
  "] as const;",
];
const keys = (values) => `[${[...values].sort().map(quote).join(", ")}]`;

function nativeVocabulary() {
  const env = { ...process.env };
  const localCargo = path.join(root, ".cache/rhwp-cargo/bin/cargo.exe");
  if (existsSync(localCargo) && !env.CARGO_HOME) {
    env.CARGO_HOME = path.join(root, ".cache/rhwp-cargo");
    env.RUSTUP_HOME ??= path.join(root, ".cache/rhwp-rustup");
    env.PATH = `${path.dirname(localCargo)}${path.delimiter}${env.PATH ?? ""}`;
  }
  const result = spawnSync("cargo", [
    "run", "--quiet", "--offline", "--locked", "--no-default-features",
    "-p", "hwpx-desktop", "--example", "bridge_descriptor",
  ], { cwd: root, env, encoding: "utf8", maxBuffer: 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Rust bridge descriptor failed (${result.status}): ${result.stderr}`);
  }
  return JSON.parse(result.stdout);
}

function jsErrorCodes(source) {
  const body = source.match(/PRODUCT_ERROR_CODES\s*=\s*Object\.freeze\(\{(?<body>[\s\S]*?)\}\)/)?.groups?.body;
  if (!body) throw new Error("PRODUCT_ERROR_CODES is missing");
  const codes = [...body.matchAll(/:\s*"([a-z_]+)"/g)].map((entry) => entry[1]);
  if (!codes.length || new Set(codes).size !== codes.length) {
    throw new Error("PRODUCT_ERROR_CODES is empty or duplicated");
  }
  return codes;
}

function assertVocabulary(vocabulary) {
  if (typeof vocabulary.protocol !== "string" || !Number.isInteger(vocabulary.version)
      || typeof vocabulary.session_data_key !== "string" || !vocabulary.session_data_key) {
    throw new Error("Native product descriptor is malformed");
  }
  for (const name of ["capabilities", "error_codes", "preparation_statuses", "apply_statuses",
    "blocker_codes", "primary_actions", "execution_statuses", "collision_policies"]) {
    if (!Array.isArray(vocabulary[name]) || !vocabulary[name].length ||
        vocabulary[name].some((value) => typeof value !== "string")) {
      throw new Error(`Native descriptor ${name} is malformed`);
    }
  }
}

function assertHost(host) {
  if (!host.dispatch_rejection || typeof host.dispatch_rejection.key !== "string" ||
      !Array.isArray(host.dispatch_rejection.fields) || !Array.isArray(host.host_methods) ||
      host.host_methods.length === 0) {
    throw new Error("Native host contract is malformed");
  }
  for (const method of host.host_methods) assertHostMethod(method);
}

function assertHostMethod(method) {
  if (!/^\w+$/.test(method.name) || !Array.isArray(method.params) ||
      (method.internal !== undefined && method.internal !== true) ||
      method.params.some((param) => !/^\w+$/.test(param.name) || typeof param.type !== "string")) {
    throw new Error("Native host method is malformed");
  }
}

function renderScreenActions(screen, actions) {
  if (!/^\w+$/.test(screen) || !actions || typeof actions !== "object") {
    throw new Error("Action registry screen is malformed");
  }
  const lines = [`  ${screen}: {`];
  for (const [action, schema] of Object.entries(actions)) {
    if (!/^\w+$/.test(action) || !Array.isArray(schema.required) || !Array.isArray(schema.optional)) {
      throw new Error("Action registry entry is malformed");
    }
    lines.push(`    ${action}: { required: ${keys(schema.required)}, optional: ${keys(schema.optional)} },`);
  }
  lines.push("  },");
  return lines;
}

function renderRegistry(registry) {
  if (!registry || typeof registry !== "object" || !Object.keys(registry).length) {
    throw new Error("Action registry is empty");
  }
  const lines = [];
  for (const [screen, actions] of Object.entries(registry)) {
    lines.push(...renderScreenActions(screen, actions));
  }
  return lines;
}

export function renderContract(vocabulary, host, registry, frontendProductSource) {
  assertVocabulary(vocabulary);
  assertHost(host);
  const methods = host.host_methods;
  const lines = [
    "/* 자동 생성 — 손으로 고치지 않는다 (scripts/gen_bridge_contract.mjs).",
    " * 정본: Rust bridge_descriptor, action_registry.json, host_contract.json, frontend/src/product_api.js.",
    " * payload 값 타입의 정본은 제품 컨트롤러이며 이 표는 허용 키 집합을 투영한다. */",
    "",
    `export const PRODUCT_PROTOCOL = ${quote(vocabulary.protocol)};`,
    "",
    `export const PRODUCT_VERSION = ${vocabulary.version};`,
    "",
    ...array("PRODUCT_CAPABILITIES", vocabulary.capabilities),
    "",
    "export type ProductCapability = (typeof PRODUCT_CAPABILITIES)[number];",
    "",
    ...array("HOST_ERROR_CODES", vocabulary.error_codes),
    "",
    "export type HostErrorCode = (typeof HOST_ERROR_CODES)[number];",
    "",
    ...array("JS_PRODUCT_ERROR_CODES", jsErrorCodes(frontendProductSource)),
    "",
    "export type JsProductErrorCode = (typeof JS_PRODUCT_ERROR_CODES)[number];",
    "",
    ...array("TEMPLATE_PREPARATION_STATUSES", vocabulary.preparation_statuses),
    "",
    "export type TemplatePreparationStatus = (typeof TEMPLATE_PREPARATION_STATUSES)[number];",
    "",
    ...array("TEMPLATE_APPLY_STATUSES", vocabulary.apply_statuses),
    "",
    "export type TemplateApplyStatus = (typeof TEMPLATE_APPLY_STATUSES)[number];",
    "",
    `export const DISPATCH_REJECTION_KEY = ${quote(host.dispatch_rejection.key)};`,
    "",
    `export const DISPATCH_REJECTION_FIELDS = [${host.dispatch_rejection.fields.map(quote).join(", ")}] as const;`,
    "",
    "export const SCREEN_ACTIONS = {",
  ];
  lines.push(...renderRegistry(registry));
  lines.push(
    "} as const;", "",
    "export type ScreenName = keyof typeof SCREEN_ACTIONS;", "",
    "export type ActionName<S extends ScreenName> = keyof (typeof SCREEN_ACTIONS)[S] & string;", "",
    ...array("HOST_METHODS", methods.map((method) => method.name)), "",
    "export type HostMethodName = (typeof HOST_METHODS)[number];", "",
    ...array("HOST_INTERNAL_METHODS", methods.filter((method) => method.internal)
      .map((method) => method.name)), "",
    "export type HostInternalMethodName = (typeof HOST_INTERNAL_METHODS)[number];", "",
    "export interface HostApi {",
  );
  for (const method of methods) {
    const params = method.params.map((param) => `${param.name}${param.optional ? "?" : ""}: unknown`);
    lines.push(`  ${method.name}(${params.join(", ")}): unknown;`);
  }
  lines.push(
    "}", "",
    ...array("DOCUMENT_CREATION_BLOCKERS", vocabulary.blocker_codes), "",
    "export type DocumentCreationBlocker = (typeof DOCUMENT_CREATION_BLOCKERS)[number];", "",
    ...array("PRIMARY_ACTIONS", vocabulary.primary_actions), "",
    "export type PrimaryAction = (typeof PRIMARY_ACTIONS)[number];", "",
    ...array("WORKBENCH_EXECUTION_STATUSES", vocabulary.execution_statuses), "",
    "export type WorkbenchExecutionStatus = (typeof WORKBENCH_EXECUTION_STATUSES)[number];", "",
    ...array("COLLISION_POLICIES", vocabulary.collision_policies), "",
    "export type CollisionPolicy = (typeof COLLISION_POLICIES)[number];", "",
    `export const SESSION_DATA_KEY = ${quote(vocabulary.session_data_key)} as const;`, "",
  );
  return lines.join("\n");
}

function main() {
  if (process.argv.length > 3 || (process.argv[2] && process.argv[2] !== "--check")) {
    throw new Error("Usage: node scripts/gen_bridge_contract.mjs [--check]");
  }
  const source = renderContract(
    nativeVocabulary(),
    readJson("crates/hwpx-desktop/src/host_contract.json"),
    readJson("crates/hwpx-desktop/src/action_registry.json"),
    readFileSync(path.join(root, "frontend/src/product_api.js"), "utf8"),
  );
  if (process.argv[2] === "--check") {
    if (!existsSync(output) || readFileSync(output, "utf8") !== source) {
      throw new Error("contract.gen.ts drift: run node scripts/gen_bridge_contract.mjs");
    }
    process.stdout.write("계약 동기화 OK (frontend/src/contract/contract.gen.ts)\n");
  } else {
    writeFileSync(output, source, "utf8");
    process.stdout.write("재생성 완료: frontend/src/contract/contract.gen.ts\n");
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
