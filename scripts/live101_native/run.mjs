import { createHash } from 'node:crypto';
import { cp, mkdir, mkdtemp, readFile, readdir, stat, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { connectNativePage } from './cdp.mjs';
import { runLegacy } from './legacy.mjs';
import { NativeSurface } from './surface.mjs';
import { runJourney } from './journey.mjs';
import { runRestart } from './restart.mjs';
import { judgePhase } from './verdict.mjs';
import { BOOT_MS, HARD_STOP_MS, SURFACE_MS, hardStopReport } from './run_budget.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '../..');
const EXAMPLE = path.join(REPO, 'examples/quickstart-101');
const PRACTICE = new Set([
  'jobs', 'datasets', 'mapping_bases', 'out', 'Results', 'template_authority',
  'sx-output', 'ui_settings.ini', 'settings.json', 'webapp-alerts.log',
]);
const refuseState = [...PRACTICE, 'templates/Results'];

function options(argv) {
  const [mode, ...rest] = argv;
  if (!['check', 'capture'].includes(mode)) throw new Error('usage: run.mjs check|capture --exe PATH [--home PATH] [--evidence DIR]');
  const parsed = { mode, phase: 'legacy' };
  for (let i = 0; i < rest.length;) {
    if (rest[i] === '--dev-assets') {
      if (parsed.devAssets || !rest[i + 1] || !rest[i + 2]) {
        throw new Error('live101 --dev-assets requires one WEB directory and one TUTORIAL directory');
      }
      parsed.devAssets = [path.resolve(rest[i + 1]), path.resolve(rest[i + 2])];
      i += 3;
      continue;
    }
    if (!['--exe', '--home', '--evidence', '--phase'].includes(rest[i]) || !rest[i + 1]) {
      throw new Error(`unknown or incomplete live101 argument: ${rest[i]}`);
    }
    parsed[rest[i].slice(2)] = rest[i + 1];
    i += 2;
  }
  if (!parsed.exe) throw new Error('native GUI executable is required');
  if (!['legacy', 'journey', 'restart'].includes(parsed.phase)) {
    throw new Error(`unknown live101 phase: ${parsed.phase}`);
  }
  if (mode === 'capture' && parsed.phase !== 'legacy') {
    throw new Error('only the legacy phase captures the thirteen tutorial screens');
  }
  return parsed;
}

async function exists(file) {
  try { await stat(file); return true; } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

async function seed(home) {
  const dirt = [];
  for (const relative of refuseState) if (await exists(path.join(home, relative))) dirt.push(relative);
  if (dirt.length) throw new Error(`live101 home contains practice state: ${dirt.join(', ')}`);
  if (await exists(path.join(home, 'data')) || await exists(path.join(home, 'templates'))) {
    throw new Error('live101 seed home already contains data or templates; refusing to overwrite assets');
  }
  await mkdir(home, { recursive: true });
  for (const name of ['data', 'templates']) {
    const source = path.join(EXAMPLE, name);
    if (!await exists(source)) throw new Error(`missing committed live101 asset: ${source}`);
    await cp(source, path.join(home, name), {
      recursive: true,
      filter: item => !PRACTICE.has(path.basename(item)),
    });
  }
  if (!await exists(path.join(home, 'data/발주목록.csv'))) {
    throw new Error('missing live101 CSV fixture');
  }
}

async function hashTree(root) {
  const result = {};
  async function descend(directory, prefix = '') {
    for (const item of (await readdir(directory, { withFileTypes: true }))
      .sort((left, right) => left.name.localeCompare(right.name))) {
      const relative = path.posix.join(prefix, item.name);
      if (item.isDirectory()) await descend(path.join(directory, item.name), relative);
      else if (item.isFile()) {
        const bytes = await readFile(path.join(directory, item.name));
        result[relative] = createHash('sha256').update(bytes).digest('hex');
      }
    }
  }
  await descend(root);
  return result;
}

async function generatedDocuments(home) {
  const work = JSON.parse(await readFile(path.join(home, 'jobs/발주요청서.job.json'), 'utf8'));
  const template = path.resolve(work.template_path);
  const applied = path.resolve(home, 'template_authority/applied') + path.sep;
  if (!template.toLowerCase().startsWith(applied.toLowerCase())) {
    throw new Error(`generated Work template is outside app-owned applied assets: ${template}`);
  }
  const results = path.join(path.dirname(template), 'Results');
  return (await readdir(results)).filter(name => name.toLowerCase().endsWith('.hwpx')).sort();
}

async function verifyPageIdentity(page, exe, devAssets) {
  const web = devAssets?.[0] ?? path.join(path.dirname(exe), 'web');
  const seal = JSON.parse(await readFile(path.join(web, 'web-artifact-seal.json'), 'utf8'));
  const loaded = await page.evaluate(`(async()=>{
    const descriptor=window.__hwpx?.describe();
    const script=document.querySelector('script[type="module"]')?.src;
    if(!script)return {descriptor,script:null};
    const bytes=await (await fetch(script)).arrayBuffer();
    const digest=await crypto.subtle.digest('SHA-256',bytes);
    return {descriptor,script:new URL(script).pathname.slice(1),
      sha256:[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('')};
  })()`);
  if (loaded.descriptor?.protocol !== 'hwpx-product' || loaded.descriptor?.version !== 1) {
    throw new Error('native page product protocol/version differs');
  }
  const file = seal.output?.files?.find(entry => entry.path === loaded.script);
  if (!file || file.sha256 !== loaded.sha256) {
    throw new Error(`native page script differs from sealed artifact: ${JSON.stringify(loaded)}`);
  }
  return { artifact_id: seal.artifact_id, tree_sha256: seal.output.tree_sha256,
    script: loaded.script, script_sha256: loaded.sha256 };
}

function armWatchdog(state, evidence) {
  return setTimeout(() => {
    void (async () => {
      state.timedOut = true;
      state.report = hardStopReport({ phase: state.args.phase, mode: state.args.mode, home: state.home,
        previous: state.report, shots: state.surface?.shots ?? [], elapsedMs: Date.now() - state.started });
      try {
        state.report.teardown = state.page ? await state.page.abort()
          : { graceful: false, forced: false, reason: 'native page not connected' };
      } catch (error) {
        state.report.teardown = { graceful: false, forced: true, error: String(error) };
      }
      try {
        await writeFile(path.join(evidence, 'check-report.json'), JSON.stringify(state.report, null, 2), 'utf8');
      } catch (error) {
        process.stderr.write(`native live101 deadline report failed: ${error}\n`);
      }
      process.stderr.write(`${state.report.error}\n`);
      process.exit(1);
    })();
  }, HARD_STOP_MS);
}

async function captureDiagnostic(page) {
  try {
    return await page.evaluate(`(async()=>({
      screen:document.querySelector('.scr.on')?.id || null,
      editor:document.querySelector('#scr-editor')?.textContent.slice(0,1500) || null,
      gate:document.querySelector('#editorTplGate')?.textContent || null,
      link:document.querySelector('#editorLinkCard')?.textContent || null,
      authoring_tabs:[...document.querySelectorAll('#scr-authoring .authoring-tab')]
        .map(e=>({text:e.textContent,html:e.outerHTML.slice(0,500)})),
      modals:[...document.querySelectorAll('.modal:not(.hidden)')]
        .map(e=>({id:e.id,text:e.textContent.slice(0,500)})),
      overlays:[...document.querySelectorAll('[role="dialog"]')]
        .map(e=>({class:e.className,text:e.textContent.slice(0,500)})),
      authoring:await window.pywebview.api.initial('authoring'),
      dispatchTrace:(window.__cap?.dispatchTrace || []).map(x=>({
        screen:x.screen,action:x.action,error:x.error || null,
        response_ok:x.response?.ok ?? null
      })),
      dispatchInstalled:window.__cap?.dispatchInstalled || false,
      alerts:window.__cap?.alerts || [],
    }))()`, 3000);
  } catch (diagnosticError) {
    return { error: String(diagnosticError) };
  }
}

async function teardownAndSave(state, evidence) {
  if (!state.timedOut && state.page) {
    try {
      state.report.teardown = await state.page.close();
    } catch (closeError) {
      state.report.teardown = { graceful: false, error: String(closeError) };
    }
    if (!state.report.teardown.graceful && state.report.verdict.ok) {
      state.report.verdict = { ok: false, failures: ['native window did not close cleanly'] };
    }
  }
  if (!state.timedOut) {
    try {
      await writeFile(path.join(evidence, 'check-report.json'),
        JSON.stringify(state.report ?? { error: 'native run ended without a report' }, null, 2), 'utf8');
    } finally {
      clearTimeout(state.watchdog);
    }
  }
}

async function executeRun(state, evidence, exampleBefore) {
  const { args, home } = state;
  if (args.phase !== 'restart') await seed(home);
  else if (!await exists(home)) throw new Error('restart requires the completed isolated home');
  const exe = path.resolve(args.exe);
  state.page = await connectNativePage(exe, home, BOOT_MS, args.devAssets);
  state.surface = new NativeSurface(state.page, SURFACE_MS,
    args.mode === 'capture' ? path.join(evidence, 'pixels') : null);
  await state.surface.install();
  const source = await verifyPageIdentity(state.page, exe, args.devAssets);
  const observations = args.phase === 'restart' ? await runRestart(state.surface, home)
    : await runLegacy(state.surface, {
      page: state.page, csvPath: path.join(home, 'data/발주목록.csv'),
    });
  if (args.phase === 'journey') {
    observations.sx05 = (await runJourney(state.surface, home, evidence)).seen;
  }
  const documents = args.phase === 'restart' ? [] : await generatedDocuments(home);
  state.report = {
    phase: args.phase, mode: args.mode, home, observations, documents,
    hwpx_generated: documents.length, shots: state.surface.shots,
    elapsed_s: Math.round((Date.now() - state.started) / 100) / 10,
    source,
  };
  state.report.verdict = judgePhase(state.report);
  if (!state.report.verdict.ok) throw new Error(state.report.verdict.failures.join('; '));
  const exampleAfter = await hashTree(EXAMPLE);
  if (JSON.stringify(exampleBefore) !== JSON.stringify(exampleAfter)) {
    throw new Error('committed live101 source assets changed during native run');
  }
}

async function handleRunError(state, error) {
  if (state.timedOut) return;
  const { args, home } = state;
  state.report ??= { phase: args.phase, mode: args.mode, home, observations: {},
    documents: [], hwpx_generated: 0, shots: state.surface?.shots ?? [] };
  state.report.verdict = { ok: false, failures: [error.message] };
  state.report.error = error.stack ?? String(error);
  if (state.page) state.report.diagnostic = await captureDiagnostic(state.page);
}

async function main() {
  const args = options(process.argv.slice(2));
  const home = args.home ? path.resolve(args.home)
    : path.join(await mkdtemp(path.join(os.tmpdir(), 'hwpx-101-native-')), 'home');
  const evidence = path.resolve(args.evidence ?? path.join(os.tmpdir(), `hwpx-101-evidence-${Date.now()}`));
  await mkdir(evidence, { recursive: true });
  const exampleBefore = await hashTree(EXAMPLE);
  const state = { args, home, page: undefined, surface: undefined, report: undefined,
    started: Date.now(), timedOut: false };
  state.watchdog = armWatchdog(state, evidence);
  try {
    await executeRun(state, evidence, exampleBefore);
  } catch (error) {
    await handleRunError(state, error);
  } finally {
    await teardownAndSave(state, evidence);
  }
  if (state.timedOut) return;
  process.stdout.write(`${evidence}\n`);
  if (!state.report.verdict.ok) {
    process.stderr.write(`${state.report.error ?? state.report.verdict.failures.join('; ')}\n`);
    process.exitCode = 1;
  }
}

await main();
