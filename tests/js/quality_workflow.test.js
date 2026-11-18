import assert from 'node:assert/strict';
import { globSync, readFileSync } from 'node:fs';
import test from 'node:test';
import { parse } from 'yaml';
import { OUTER_MS } from '../../scripts/live101_native/run_budget.mjs';

const read = name => readFileSync(new URL(`../../${name}`, import.meta.url), 'utf8').replace(/^\uFEFF/u, '');
const qualityText = read('.github/workflows/quality.yml');
const quality = parse(qualityText, { schema: 'failsafe' });
const jobs = quality.jobs;
const releaseText = read('.github/workflows/release.yml');
const release = parse(releaseText, { schema: 'failsafe' }).jobs['build-release'].steps;
const commands = job => (job.steps ?? []).filter(step => step.run).map(step => step.run);
const needs = job => new Set(typeof job.needs === 'string' ? [job.needs] : job.needs ?? []);
const uses = (job, action) => (job.steps ?? []).filter(step => step.uses?.startsWith(action));
const text = job => JSON.stringify(job);
const downloads = job => uses(job, 'actions/download-artifact').some(step => step.with.name === 'sealed-web');
const buildTokens = ['npm run build', 'npm.cmd run build', '-Mode Build'];
const axes = { native: 'HWPX_SKIP_NATIVE_TESTS', browser: 'HWPX_SKIP_MOTION_TESTS', live: 'HWPX_SKIP_GUI_TESTS' };
const axisCommand = { native: '-- --ignored --exact', browser: 'node --test --test-concurrency=1 "tests/browser/*.test.js"',
  live: 'run_native_live101.ps1' };
const runsAxis = (job, axis) => commands(job).some(command => command.includes(axisCommand[axis]));
const retiredTooling = /\b(?:python|pytest|uv|ruff|pyright|pyinstaller|pyproject)\b|setup-uv|uv\.lock/iu;
// 실 Win32 자원이 있어야 도는 Rust 테스트 — 소스의 `#[ignore]` 전체가 곧 native 축이다.
const ignoredRustTests = () => globSync('crates/*/{src,tests}/**/*.rs', { cwd: new URL('../../', import.meta.url) })
  .flatMap(file => [...read(file.replaceAll('\\', '/')).matchAll(/#\[ignore[^\]]*\]\s*fn\s+([A-Za-z0-9_]+)/gu)]
    .map(match => match[1])).sort();
const nativeNames = command => [...command.matchAll(/((?:[a-z_]+::)+(windows_[a-z0-9_]+))/gu)].map(match => match[1]);
const releaseStep = fragment => {
  const matches = release.filter(step => step.name?.includes(fragment));
  assert.equal(matches.length, 1, fragment);
  return matches[0];
};
const contains = (source, parts) => parts.forEach(part => assert.ok(source.includes(part), part));

test('aggregate covers every job and accepts only success while preserving non-PR history', () => {
  assert.deepEqual(needs(jobs['quality-gate']), new Set(Object.keys(jobs).filter(name => name !== 'quality-gate')));
  contains(text(jobs['quality-gate']), ['always()', 'exit 1']);
  assert.ok(commands(jobs['quality-gate']).some(command => command.includes('.value.result != "success"')));
  contains(quality.concurrency.group, ['pull_request.number', 'github.sha']);
  assert.ok(quality.concurrency['cancel-in-progress'].includes("github.event_name == 'pull_request'"));
  assert.ok('merge_group' in quality.on);
  const actions = [...qualityText.matchAll(/uses: (\S+)([^\n]*)/gu)];
  assert.ok(actions.length);
  for (const [, reference, trailer] of actions) {
    assert.match(reference.split('@')[1], /^[0-9a-f]{40}$/u);
    assert.match(trailer, /#\s*v\d/u);
  }
  for (const token of ['nick-fields/retry', 'continue-on-error: true', '--reruns']) {
    assert.ok(!qualityText.includes(token), token);
  }
});

test('no workflow or local runner installs Python tooling and artifact downloads reject corruption', () => {
  for (const [name, source] of [['quality.yml', qualityText], ['release.yml', releaseText],
    ['test.ps1', read('test.ps1')], ['test-rust.ps1', read('test-rust.ps1')]]) {
    assert.doesNotMatch(source, retiredTooling, name);
  }
  for (const probe of ['uv sync --locked', 'uv run --no-sync pytest', 'astral-sh/setup-uv@v6', 'python -c 1', 'ruff check']) {
    assert.match(probe, retiredTooling, probe);
  }
  const transfers = Object.values(jobs).flatMap(job => uses(job, 'actions/download-artifact'));
  assert.ok(transfers.length);
  for (const step of transfers) assert.equal(step.with['digest-mismatch'], 'error');
});

test('one sealed frontend producer supplies verified bytes to every consumer before Node setup', () => {
  assert.deepEqual(Object.entries(jobs).filter(([, job]) => buildTokens.some(token => text(job).includes(token)))
    .map(([name]) => name), ['sealed-web']);
  const uploads = uses(jobs['sealed-web'], 'actions/upload-artifact');
  assert.equal(uploads.length, 1);
  assert.equal(uploads[0].with.name, 'sealed-web');
  contains(uploads[0].with.path, ['build/web', 'web-artifact-identity.json']);
  assert.equal(uploads[0].with['include-hidden-files'], 'true');
  assert.equal(uploads[0].with['if-no-files-found'], 'error');
  const consumers = Object.entries(jobs).filter(([, job]) => downloads(job));
  assert.ok(consumers.length);
  for (const [name, job] of Object.entries(jobs)) {
    if (needs(job).has('sealed-web') && name !== 'quality-gate') assert.ok(downloads(job), name);
    if (downloads(job)) {
      assert.ok(needs(job).has('sealed-web'), name);
      contains(text(job), ['VerifyExisting', 'web-artifact-identity.json']);
      assert.ok(!buildTokens.some(token => text(job).includes(token)), name);
    }
    const verify = job.steps.findIndex(step => step.run?.includes('VerifyExisting'));
    if (verify < 0) continue;
    const rust = job.steps.findIndex(step => step.name === 'Prepare pinned Rust web verifier' && step.run === 'cargo --version');
    assert.ok(rust >= 0 && rust < verify, name);
    job.steps.forEach((step, index) => {
      if (step.uses?.startsWith('actions/setup-node')) assert.ok(verify < index, name);
    });
  }
  contains(read('build-web.ps1'), ["run_web_artifact.ps1') -Verify"]);
  contains(read('scripts/run_web_artifact.ps1'), ['cargo run --quiet --locked -p hwpx-artifact', '$cargoCommand.Source -ieq $cachedCargo']);
});

test('Rust build caches save from one owner per family on master push and only restore elsewhere', () => {
  const families = { debug: 'rust-kernel', coverage: 'rust-coverage', release: 'distribution-webview2' };
  const restoreOnly = ['sealed-web', 'static', 'windows-native', 'browser-render'];
  for (const [name, job] of Object.entries(jobs)) {
    const caches = uses(job, 'Swatinem/rust-cache');
    if (name === 'quality-gate' || name === 'live-webview2') {
      assert.equal(caches.length, 0, name);
      continue;
    }
    assert.equal(caches.length, 1, name);
    const [cache] = caches;
    // 첫 cargo 호출보다 앞서야 복원이 의미가 있고, 모든 job 이 같은 시점에 키를 계산한다.
    const at = job.steps.indexOf(cache);
    assert.ok(at === 1 && job.steps[0].uses.startsWith('actions/checkout'), name);
    assert.equal(cache.with['cache-bin'], 'false', name);
    const owner = Object.entries(families).find(([, saver]) => saver === name);
    if (owner) {
      assert.equal(cache.with['shared-key'], owner[0], name);
      assert.equal(cache.with['save-if'], "${{ github.event_name == 'push' }}", name);
    } else {
      assert.ok(restoreOnly.includes(name), name);
      assert.equal(cache.with['shared-key'], 'debug', name);
      assert.equal(cache.with['save-if'], 'false', name);
    }
  }
});

test('rhwp Studio is reused only for an exact input match and still meets the seal', () => {
  const producer = jobs['sealed-web'];
  assert.ok('schedule' in quality.on);
  const restore = uses(producer, 'actions/cache/restore');
  const save = uses(producer, 'actions/cache/save');
  assert.equal(restore.length, 1);
  assert.equal(save.length, 1);
  assert.equal(Object.values(jobs).flatMap(job => uses(job, 'actions/cache')).length, 2);
  const [restoreStep] = restore;
  const [saveStep] = save;
  // schedule 은 복원하지 않아 콜드 빌드가 돈다. 부분 일치 fallback 은 없다.
  assert.equal(restoreStep.if, "github.event_name != 'schedule'");
  assert.equal(restoreStep.with['restore-keys'], undefined);
  contains(restoreStep.with.key, ["hashFiles('scripts/build_rhwp.ps1', 'vendor/rhwp/**', '.node-version')"]);
  assert.equal(saveStep.with.key, `\${{ steps.${restoreStep.id}.outputs.cache-primary-key }}`);
  assert.equal(saveStep.with.path, restoreStep.with.path);
  contains(restoreStep.with.path, ['build/rhwp/studio\n', 'build/rhwp/studio.inputs.sha256']);
  contains(saveStep.if, [`steps.${restoreStep.id}.outputs.cache-hit != 'true'`]);
  assert.ok(!saveStep.if.includes('merge_group') && !saveStep.if.includes('schedule'));
  const build = producer.steps.findIndex(step => step.run?.includes('-Mode Build'));
  assert.ok(producer.steps.indexOf(restoreStep) < build && build < producer.steps.indexOf(saveStep));
  assert.equal(producer.steps[build].env.RHWP_REUSE_STAMPED_STUDIO, '1');
  // 재사용 판단은 스크립트 한 곳이 같은 입력의 다이제스트 stamp 로 하고, 봉인이 파일별로 다시 대조한다.
  const script = read('scripts/build_rhwp.ps1');
  contains(script, ["$env:RHWP_REUSE_STAMPED_STUDIO -eq '1'", "'scripts/build_rhwp.ps1'", "'.node-version'",
    "'vendor/rhwp'", "'build/rhwp/studio.inputs.sha256'", 'Remove-Item -LiteralPath $stamp']);
  assert.ok(script.indexOf('Remove-Item -LiteralPath $stamp') < script.indexOf('git clone'));
  assert.ok(script.lastIndexOf('Set-Content -LiteralPath $stamp') > script.indexOf("Copy-Item -Path (Join-Path $source 'assets/fonts')"));
  contains(read('crates/hwpx-artifact/src/lib.rs'), ['let studio = studio_output_closure(&root, &output_files)?;']);
  contains(read('crates/hwpx-artifact/src/studio.rs'), ['"rhwp Studio output differs from pinned runtime manifest"']);
  contains(read('vite.config.mjs'), ['cpSync(studioRoot, join(webOutDir, "rhwp", "studio")']);
});

test('Rust and product copy gates run locally and CI resource responsibilities do not overlap', () => {
  const local = read('test.ps1');
  const runner = read('test-rust.ps1');
  assert.equal(jobs['rust-kernel']['runs-on'], 'windows-latest');
  assert.deepEqual(commands(jobs['rust-kernel']), ['.\\test-rust.ps1']);
  contains(local, ["'test-rust.ps1'", 'node scripts/complexity_budget.mjs --check', 'node scripts/ui_copy_census.mjs --check']);
  contains(runner, ['cargo fmt --all --check', 'cargo clippy --workspace --all-targets --locked -- -D warnings',
    'cargo test --workspace --all-targets --locked', 'cargo check -p hwpx-desktop --bin hwpxfiller --no-default-features --locked']);
  for (const command of ['node scripts/complexity_budget.mjs --check', 'node scripts/ui_copy_census.mjs --check']) {
    assert.ok(commands(jobs.static).includes(command));
  }
  for (const axis of Object.keys(axes)) assert.equal(Object.values(jobs).filter(job => runsAxis(job, axis)).length, 1, axis);
  for (const command of [...commands(jobs.static), ...commands(jobs['rust-kernel'])]) {
    assert.ok(!command.includes('--ignored') && !command.includes('tests/browser'), command);
  }
  const producer = text(jobs['sealed-web']);
  assert.ok(producer.indexOf('-Mode Build') < producer.indexOf('npm.cmd test'));

  // 커버리지 하한은 한 job 이 계측 빌드로 혼자 소유한다 — 산출물도 Node 도 쓰지 않는다.
  const coverage = jobs['rust-coverage'];
  assert.deepEqual(Object.entries(jobs).filter(([, job]) => /coverage/iu.test(commands(job).join('\n')))
    .map(([name]) => name), ['rust-coverage']);
  assert.ok(commands(coverage).some(command => command.includes('scripts\\rust_coverage.ps1')));
  assert.ok(coverage.steps.some(step => step.name === 'Rust LLVM coverage floors'));
  assert.ok(uses(coverage, 'actions/upload-artifact').some(step => step.if === 'always()'
    && step.with.path.includes('package-coverage.md')));
  assert.equal(needs(coverage).size, 0);
  assert.equal(downloads(coverage), false);
  assert.equal(uses(coverage, 'actions/setup-node').length, 0);
});

test('real Win32 axis runs exactly the ignored Rust tests in CI and locally, and counts them', () => {
  const ignored = ignoredRustTests();
  assert.ok(ignored.length >= 3, ignored.join(', '));
  const native = Object.entries(jobs).filter(([, job]) => runsAxis(job, 'native'));
  assert.deepEqual(native.map(([name]) => name), ['windows-native']);
  const [command] = commands(native[0][1]).filter(item => item.includes('--ignored'));
  contains(command, ['cargo test -p hwpx-desktop --lib', '--locked', '-- --ignored --exact',
    `test result: ok\\. ${ignored.length} passed;`]);
  const names = nativeNames(command);
  assert.deepEqual(names.map(name => name.split('::').at(-1)).sort(), ignored);
  assert.equal(downloads(native[0][1]), false);
  assert.equal(uses(native[0][1], 'actions/setup-node').length, 0);
  const local = read('test.ps1');
  contains(local, ['test -p hwpx-desktop --lib --locked -- --ignored --exact', ...names,
    `test result: ok\\. ${ignored.length} passed;`, 'HWPX_SKIP_NATIVE_TESTS']);
});

test('Chrome and native WebView2 keep distinct evidence, full scope and failure uploads', () => {
  const chrome = Object.values(jobs).find(job => runsAxis(job, 'browser'));
  const live = jobs['live-webview2'];
  assert.ok(chrome.name.includes('Chrome') && !text(chrome).includes('WebView2'));
  assert.ok(live.name.includes('WebView2') && !text(live).toLowerCase().includes('chrome'));
  assert.deepEqual(needs(live), new Set(['distribution-webview2']));
  assert.ok(uses(live, 'actions/download-artifact').some(step => step.with.name === 'native-gui'));
  assert.equal(commands(live).filter(command => command.includes('run_native_live101.ps1')).length, 1);
  for (const token of ['--live-scope', '-LiveScope', 'HWPX_SELFTEST_PROBES']) {
    assert.ok(!text(live).includes(token) && !text(release).includes(token), token);
  }
  for (const name of ['live-webview2', 'distribution-webview2']) {
    const evidence = uses(jobs[name], 'actions/upload-artifact').filter(step => step.with.name.endsWith('-evidence'));
    assert.ok(evidence.length);
    evidence.forEach(step => assert.equal(step.if, 'always()'));
  }
  contains(text(chrome), ['Press-geometry browser precondition', 'HWPX_SKIP_MOTION_TESTS', "channel: 'chrome'"]);
  // Node 드라이버와 rhwp 왕복 fixture 를 갖춘 뒤, 방금 검증한 봉인 트리로 Chrome suite 를 돈다.
  const step = fragment => chrome.steps.findIndex(item => (item.run ?? '').includes(fragment));
  const order = [step('VerifyExisting'), step('npm.cmd ci'), step('--example browser_fixture'),
    step("channel: 'chrome'"), step('tests/browser/*.test.js')];
  assert.ok(order.every((at, index) => at >= 0 && (index === 0 || order[index - 1] < at)), order.join(','));
  const suite = chrome.steps[order.at(-1)];
  assert.equal(suite.env.HWPX_WEB_ARTIFACT_ROOT, 'build/web');
  assert.equal(suite.env.HWPX_BROWSER_FIXTURE_BIN, 'target/debug/examples/browser_fixture.exe');
  contains(read('test.ps1'), ["'tests/browser/*.test.js'", '--example browser_fixture', 'HWPX_WEB_ARTIFACT_ROOT',
    'HWPX_BROWSER_FIXTURE_BIN', 'HWPX_SKIP_MOTION_TESTS']);
  assert.ok(globSync('tests/browser/*.test.js', { cwd: new URL('../../', import.meta.url) }).length > 0);
  for (const variable of Object.values(axes)) {
    for (const token of [`${variable}:`, `${variable}=1`, `${variable} = "1"`]) assert.ok(!qualityText.includes(token));
  }
  assert.match(read('scripts/run_native_live101.ps1'), /foreach \(\$phase in @\('journey', 'restart'\)\)/u);
  assert.equal(Number(live['timeout-minutes']), 60);
  assert.ok(2 * OUTER_MS <= Number(live['timeout-minutes']) * 60_000 * 0.9);
});

test('distribution and release consume the verified tree before native journey and recovery evidence', () => {
  const distribution = commands(jobs['distribution-webview2']);
  const packaging = distribution.filter(command => command.includes('packaging'));
  assert.equal(packaging.length, 1);
  contains(packaging[0], ['-Target all', '-WebMode VerifyExisting']);
  for (const script of ['verify_native_restart.ps1', 'verify_native_capability.ps1']) {
    const checks = distribution.filter(command => command.includes(script));
    assert.equal(checks.length, 1);
    assert.ok(checks[0].includes('dist/hwpx-filler-web/hwpx-filler-web.exe'));
  }
  const tests = releaseStep('Quality and tests');
  const packageStep = releaseStep('Build portable applications');
  const native = releaseStep('Native Quickstart 101 journey and restart');
  const upload = releaseStep('Upload live evidence');
  assert.equal(releaseStep('Validate release version').run, 'node scripts/check_release_version.mjs $env:RELEASE_TAG');
  assert.equal(releaseStep('Prepare pinned Rust web verifier').run, 'cargo --version');
  const setup = release.find(step => step.uses?.startsWith('actions/setup-node@'));
  assert.equal(setup.with['node-version-file'], '.node-version');
  assert.equal(tests.run, '.\\test.ps1 -SkipLive');
  contains(read('test.ps1'), ["& (Join-Path $PSScriptRoot 'build-web.ps1')", "$word -ieq '-SkipLive'"]);
  assert.ok(read('build-web.ps1').includes("[string]$Mode = 'Build'"));
  contains(packageStep.run, ['.\\packaging\\build_native.ps1 -Target all -SkipCheck -WebMode VerifyExisting', 'release-evidence']);
  assert.ok(!releaseText.includes('npm.cmd ci') && !releaseText.includes('npm.cmd run build'));
  contains(native.run, ['run_native_live101.ps1', 'dist/hwpx-filler-web/hwpx-filler-web.exe']);
  assert.equal(upload.if, 'always()');
  contains(upload.with.path, ['live-evidence/journey/**', 'live-evidence/restart/**', '!live-evidence/home/**']);
  const order = [setup, tests, packageStep, native, upload].map(step => release.indexOf(step));
  assert.ok(order.every((at, index) => index === 0 || order[index - 1] < at));
});

test('packaged bundle checks call the artifact CLI in bundle mode, which rejects --verify', () => {
  const callers = ['.github/workflows/release.yml', 'packaging/build_native.ps1', 'packaging/assemble_native.ps1'];
  const calls = callers.flatMap(name => read(name).replace(/`\r?\n\s*/gu, ' ').split(/\r?\n/u)
    .filter(line => /run_web_artifact\.ps1|\$artifact |\$checker /u.test(line) && line.includes('--bundle-root')));
  assert.ok(calls.length >= 5, calls.join('\n'));
  for (const call of calls) assert.ok(!/\s-Verify\b|\s--verify\b/u.test(call), call);
});

test('release reconciles installed and portable identities before cleanup and publishes complete evidence', () => {
  const reconcile = releaseStep('Reconcile web artifact identity').run;
  contains(reconcile, ['run_web_artifact.ps1 --reconcile', "--expect 'source,dist,installed,portable'",
    '--build-metadata build\\version\\build-metadata.json', 'throw', 'release-evidence.json']);
  for (const name of ['dist', 'installed', 'portable']) assert.ok(reconcile.includes(`--copy ('${name}=`));
  assert.ok(!reconcile.includes('Sort-Object -Unique'));
  const smoke = releaseStep('Smoke test install and uninstall').run;
  assert.ok(smoke.indexOf('run_web_artifact.ps1') >= 0 && smoke.indexOf('run_web_artifact.ps1') < smoke.indexOf('Uninstall-Product $fillerDir'));
  assert.ok(smoke.includes('installed.json'));
  const portable = releaseStep('Package portable bundles').run;
  assert.ok(portable.indexOf('Compress-Archive') >= 0 && portable.indexOf('Compress-Archive') < portable.indexOf('Expand-Archive'));
  assert.ok(portable.indexOf('Expand-Archive') < portable.indexOf('run_web_artifact.ps1'));
  assert.ok(portable.includes('portable.json'));
  for (const glob of ['*.exe', '*.zip', '*.json']) assert.ok(releaseStep('Create checksums').run.includes(`installer-dist\\${glob}`));
  contains(releaseText, ['installer-dist/release-evidence.json', 'installer-dist/build-metadata.json', 'runtime_packages',
    '-Target all', 'dist\\hwpx-cli\\hwpx-cli.exe', 'HWPX-CLI-$version-portable.zip', 'verify_cli_bundle.mjs']);
  assert.ok(qualityText.includes('-Target all'));
  assert.ok(read('packaging/installers/hwpx-filler.iss').includes('Source: "..\\..\\dist\\hwpx-filler-web\\*"'));
  assert.ok(read('package-installer.ps1').includes("[ValidateSet('all', 'filler')]"));
  assert.ok(read('packaging/build_native.ps1').includes("[ValidateSet('all', 'filler', 'cli')]"));
  for (const token of ['package-installer.ps1', 'WINDOWS_CERTIFICATE_BASE64', 'Install Inno Setup']) {
    assert.ok(!qualityText.includes(token) && releaseText.includes(token));
  }
});
