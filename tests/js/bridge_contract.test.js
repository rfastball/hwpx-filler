import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { parseAst } from 'vite';
import { SESSION_DATA_KEY } from '../../frontend/src/contract/contract.gen.ts';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = relative => readFileSync(path.join(root, relative), 'utf8');
const contract = () => read('frontend/src/contract/contract.gen.ts');
const quoted = values => values.map(value => JSON.stringify(value));
const exportedArray = (source, name) => {
  const body = source.match(new RegExp(`export const ${name} = \\[([\\s\\S]*?)\\] as const;`))?.[1];
  assert.notEqual(body, undefined, `${name} export is missing`);
  return [...body.matchAll(/"([^"\n]+)"/g)].map(match => match[1]);
};
const sourceFiles = (directory, result = []) => {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) sourceFiles(file, result);
    else if (/\.(?:[cm]?js|tsx?)$/.test(entry.name)) result.push(file);
  }
  return result;
};

// Local dispatch helpers hide the screen argument; all other callers declare it.
const callOwners = {
  'src/screens/library.ts': { SCREEN: 'library', axis: 'library', jobDispatch: 'job' },
  'src/screens/work_package.ts': { send: 'library' },
  'src/screens/editor.ts': { SCREEN: 'editor', sendEdit: 'editor', commit: 'editor' },
  'src/screens/workbench.ts': { SCREEN: 'workbench', sendWb: 'workbench', commit: 'workbench' },
  'src/screens/data_picker.ts': { SCREEN: 'pool' },
  'src/screens/job_read.ts': { zone: 'job' },
  'src/screens/data_zone.ts': { zone: 'job' },
  'src/screens/job_column_panel.ts': { zone: 'job' },
  'src/tutorial/panel.ts': { send: 'tutorial' },
};
const literal = node => node?.type === 'Literal' && typeof node.value === 'string' ? node.value : null;
const member = node => node?.type === 'MemberExpression' && !node.computed
  ? [node.object?.name, node.property?.name] : [];
const staticKeys = node => {
  if (node === undefined) return [];
  if (node?.type !== 'ObjectExpression') return null;
  const keys = [];
  for (const property of node.properties) {
    if (property.type !== 'Property' || property.computed) return null;
    const key = property.key.name ?? literal(property.key);
    if (key === null) return null;
    keys.push(key);
  }
  return keys;
};
function decodedDispatch(node, owners, screenConstant) {
  const [object, property] = member(node.callee);
  const method = node.callee.name ?? (object === 'controller' ? property : null);
  if (method === 'dispatch' || object === 'Bridge' && property === 'call'
    || object === 'controller' && property === 'call') {
    const screen = literal(node.arguments[0])
      ?? (node.arguments[0]?.name === 'SCREEN' ? screenConstant : null);
    const action = literal(node.arguments[1]);
    return screen && action ? { screen, action, payload: node.arguments[2] } : null;
  }
  if (!owners[method]) return null;
  const actionIndex = method === 'commit' ? 1 : 0;
  const action = literal(node.arguments[actionIndex]);
  return action ? { screen: owners[method], action, payload: node.arguments[actionIndex + 1] } : null;
}
function dispatchProblem(call, file, registry) {
  const { screen, action, payload } = call;
  const schema = registry[screen]?.[action];
  if (!schema) return { checked: 0, problem: `${file}: ${screen}/${action} is unregistered` };
  const keys = staticKeys(payload);
  if (!keys) return { checked: 0, problem: null };
  const missing = schema.required.filter(key => !keys.includes(key));
  const extra = keys.filter(key => ![...schema.required, ...schema.optional].includes(key));
  return { checked: 1, problem: missing.length || extra.length
    ? `${file}: ${screen}/${action} missing=${missing} extra=${extra}` : null };
}
function literalDispatchProblems(source, file, registry) {
  const owners = callOwners[file] ?? {};
  const ast = parseAst(source, { lang: file.endsWith('.tsx') ? 'tsx' : file.endsWith('.ts') ? 'ts' : 'js' });
  const screenConstant = literal(ast.body.flatMap(item => item.declarations ?? [])
    .find(item => item.id?.name === 'SCREEN')?.init) ?? owners.SCREEN;
  const problems = [];
  let checked = 0;
  const visit = node => {
    if (node.type === 'CallExpression') {
      const call = decodedDispatch(node, owners, screenConstant);
      if (call) {
        const result = dispatchProblem(call, file, registry);
        checked += result.checked;
        if (result.problem) problems.push(result.problem);
      }
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(child => child?.type && visit(child));
      else if (value?.type) visit(value);
    }
  };
  visit(ast);
  return { checked, problems };
}

function assertBlockerControls(text, host, actions) {
  // Independent UI expectations: runtime refusal has no recovery verb; checking
  // keeps its control disabled. The native observation tests own enabled/reason state.
  const active = [
    ['SELECT_DATA', '#jobBtnPickData', 'pick_data_file'],
    ['SELECT_RECORDS', '#jobSelAll', 'job.set_all'],
    ['SELECT_WORK', '#jobCandidates .cand-pick', 'job.select_job'],
    ['CONNECT_DATA', '#jobConnectData', 'open_job_in_editor'],
    ['REVIEW_TEMPLATE_CHANGE', '#jobTplCheck', 'job.template_check'],
    ['REPAIR_TEMPLATE', '#jobRepairTemplate', 'open_job_in_editor'],
    ['CHOOSE_CONTENT', '.cs-option-input', 'job.select_slot_option'],
    ['REVIEW_BINDING', '#jobInputRequirements button', 'open_job_in_editor'],
    ['REVIEW_RECORD_DATA', '#jobRecordValidationIssues button', 'job.recover_record_issue'],
    ['REVIEW_DELIVERY', '#settingsPickFolder', 'pick_output_folder'],
    ['EXECUTION_NO_EVIDENCE', '#jobResolveExecution', 'job.resolve_execution'],
    ['EXECUTION_STALE', '#jobResolveExecution', 'job.resolve_execution'],
    ['CONTEXT_ERROR', '#jobRecoverContext', 'job.refresh_observation'],
  ];
  const automatic = [['EXECUTION_CHECKING', '#jobResolveExecution']];
  const noVerb = ['POLICY_BLOCKED', 'RUNTIME_NOT_ADMITTED'];
  assert.deepEqual([...active, ...automatic].map(([code]) => code).concat(noVerb).sort(),
    exportedArray(text, 'DOCUMENT_CREATION_BLOCKERS').sort());
  const frontend = sourceFiles(path.join(root, 'frontend/src'))
    .filter(file => !file.endsWith('contract.gen.ts'))
    .map(file => readFileSync(file, 'utf8')).join('\n');
  const methods = new Set(host.host_methods.filter(method => !method.internal).map(method => method.name));
  for (const [code, selector, target] of [...active, ...automatic]) {
    const tokens = [...selector.matchAll(/[#.]([A-Za-z][\w-]*)/g)].map(match => match[1]);
    assert.ok(tokens.length && tokens.every(token => frontend.includes(token)), `${code}: ${selector}`);
    if (!target) continue;
    const [screen, action] = target.split('.');
    assert.ok(action ? Object.hasOwn(actions[screen] ?? {}, action) : methods.has(target), `${code}: ${target}`);
  }
  const literals = new Set([...`${frontend}\n${read('frontend/js/bridge.js')}`
    .matchAll(/['"]([a-z][a-z0-9_]*)['"]/g)].map(match => match[1]));
  // The frozen example installer remains callable by its native tests, without a UI entry.
  const frozen = new Set(['tpl.install_examples', 'tpl.remove_examples']);
  for (const target of frozen) {
    const [screen, action] = target.split('.');
    assert.ok(Object.hasOwn(actions[screen] ?? {}, action), `stale exclusion: ${target}`);
  }
  const unconsumed = registry => Object.entries(registry).flatMap(([screen, entries]) =>
    Object.keys(entries).filter(action => !literals.has(action) && !frozen.has(`${screen}.${action}`))
      .map(action => `${screen}.${action}`)).sort();
  assert.deepEqual(unconsumed(actions), [], 'registered actions need frontend callers');
  assert.deepEqual(unconsumed({ job: { missing_frontend_action: {} } }), ['job.missing_frontend_action']);
}

function profileManagementSurfaces(host, actions) {
  const names = [
    ...host.host_methods.map(method => `host:${method.name}`),
    ...Object.entries(actions).flatMap(([screen, entries]) => [
      `screen:${screen}`, ...Object.keys(entries).map(action => `action:${screen}.${action}`),
    ]),
  ];
  return names.filter(name => /profile|qualification/i.test(name)).sort();
}

test('generated bridge contract matches native, host, action, and frontend authorities', () => {
  const result = spawnSync(process.execPath, ['scripts/gen_bridge_contract.mjs', '--check'], {
    cwd: root, encoding: 'utf8', timeout: 60_000,
  });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  const text = contract();
  const host = JSON.parse(read('crates/hwpx-desktop/src/host_contract.json'));
  const actions = JSON.parse(read('crates/hwpx-desktop/src/action_registry.json'));
  assert.deepEqual(profileManagementSurfaces(host, actions), [], 'shipping profile management is not a product surface');
  assert.deepEqual(profileManagementSurfaces(
    { host_methods: [{ name: 'publish_qualification_profile' }] },
    { job: { manage_profile: {} }, qualification: {} },
  ), ['action:job.manage_profile', 'host:publish_qualification_profile', 'screen:qualification']);
  assert.deepEqual(exportedArray(text, 'HOST_METHODS'),
    host.host_methods.map(method => method.name));
  assert.deepEqual(exportedArray(text, 'HOST_INTERNAL_METHODS'),
    host.host_methods.filter(method => method.internal).map(method => method.name));
  assert.match(text, new RegExp(`export const DISPATCH_REJECTION_KEY = ${JSON.stringify(host.dispatch_rejection.key)};`));
  assert.deepEqual(
    [...text.matchAll(/^    (\w+): \{ required: \[(.*?)\], optional: \[(.*?)\] \},$/gm)]
      .map(match => [match[1], match[2], match[3]]).length,
    Object.values(actions).reduce((count, screen) => count + Object.keys(screen).length, 0),
  );
  for (const [screen, entries] of Object.entries(actions)) {
    const body = text.match(new RegExp(`^  ${screen}: \\{([\\s\\S]*?)^  \\},`, 'm'))?.[1];
    assert.ok(body, `missing screen ${screen}`);
    for (const [action, schema] of Object.entries(entries)) {
      const required = quoted([...schema.required].sort()).join(', ');
      const optional = quoted([...schema.optional].sort()).join(', ');
      assert.ok(body.includes(`    ${action}: { required: [${required}], optional: [${optional}] },`),
        `${screen}.${action}`);
    }
  }
  const productSource = read('frontend/src/product_api.js');
  const jsCodes = [...productSource.match(/PRODUCT_ERROR_CODES\s*=\s*Object\.freeze\(\{([\s\S]*?)\}\)/)[1]
    .matchAll(/:\s*"([a-z_]+)"/g)].map(match => match[1]);
  assert.deepEqual(exportedArray(text, 'JS_PRODUCT_ERROR_CODES'), jsCodes);
  assertBlockerControls(text, host, actions);
  const documented = read('docs/reference/runtime.md');
  const directCalls = [...read('frontend/js/bridge.js').matchAll(/\bapi\.(\w+)/g)].map(match => match[1]);
  assert.ok(directCalls.length);
  for (const method of new Set(directCalls)) {
    assert.ok(documented.includes(`\`${method}\``), `undocumented host call: ${method}`);
  }
});

test('frontend consumes generated contract values and type-only imports cannot satisfy the gate', () => {
  const expected = ['SCREEN_ACTIONS', 'HOST_METHODS', 'HOST_INTERNAL_METHODS', 'DISPATCH_REJECTION_KEY', 'SESSION_DATA_KEY'];
  const files = sourceFiles(path.join(root, 'frontend/src')).filter(file => !file.endsWith('contract.gen.ts'));
  const sources = files.map(file => readFileSync(file, 'utf8'));
  for (let index = 0; index < files.length; index++) {
    if (!files[index].endsWith('.ts')) continue;
    assert.ok(!sources[index].includes(JSON.stringify(SESSION_DATA_KEY))
      && !sources[index].includes(`'${SESSION_DATA_KEY}'`), `duplicate session row key: ${files[index]}`);
  }
  const consumes = (source, name) => {
    const imports = [...source.matchAll(/import\s+(type\s+)?\{([^}]*)\}\s*from\s*["']([^"']*contract\.gen\.ts)["']/g)];
    return imports.some(match => !match[1] && match[2].split(',').some(specifier => {
      const item = specifier.trim();
      if (item.startsWith('type ')) return false;
      const parts = item.split(/\s+as\s+/);
      if (parts[0].trim() !== name) return false;
      const binding = (parts[1] ?? name).trim();
      return (source.match(new RegExp(`\\b${binding}\\b`, 'g')) ?? []).length >= 2;
    }));
  };
  for (const name of expected) {
    assert.ok(sources.some(source => consumes(source, name)), `${name} is not consumed as a value`);
  }
  assert.equal(consumes('import type { SCREEN_ACTIONS } from "../contract/contract.gen.ts";\n',
    'SCREEN_ACTIONS'), false);
});

test('literal frontend dispatch payloads fit native action schemas', () => {
  const registry = JSON.parse(read('crates/hwpx-desktop/src/action_registry.json'));
  const reports = sourceFiles(path.join(root, 'frontend/src')).map(file => {
    const relative = path.relative(path.join(root, 'frontend'), file).replaceAll('\\', '/');
    return literalDispatchProblems(readFileSync(file, 'utf8'), relative, registry);
  });
  assert.ok(reports.reduce((total, report) => total + report.checked, 0) > 0);
  assert.deepEqual(reports.flatMap(report => report.problems), []);
  const probe = source => literalDispatchProblems(source, 'src/screens/workbench.ts', registry).problems;
  assert.deepEqual(probe('dispatch("job", "select_slot_option", {slot_id:"s"})'),
    ['src/screens/workbench.ts: job/select_slot_option missing=configuration_token,option_id,request_id extra=']);
  assert.deepEqual(probe('dispatch("job", "select_slot_option")'),
    ['src/screens/workbench.ts: job/select_slot_option missing=configuration_token,option_id,request_id,slot_id extra=']);
  assert.deepEqual(probe('sendWb("set_view", {view:"card", typo:true})'),
    ['src/screens/workbench.ts: workbench/set_view missing= extra=typo']);
  assert.deepEqual(probe('sendWb("removed_action", {})'),
    ['src/screens/workbench.ts: workbench/removed_action is unregistered']);
  assert.deepEqual(probe('sendWb("set_view", {...draft})'), []);
});
