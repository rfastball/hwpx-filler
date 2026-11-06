import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { main, renderWebRegion, run } from '../../scripts/gen_design_tokens.mjs';

const ROOT = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const tokens = JSON.parse(readFileSync(join(ROOT, 'frontend/design-tokens.json'), 'utf8'));

test('token generator preserves hand CSS, rejects drift, and emits the checked product region', () => {
  assert.equal(run({ check: true, log: () => {}, error: () => {} }), 0);
  const root = mkdtempSync(join(tmpdir(), 'design-tokens-'));
  try {
    mkdirSync(join(root, 'frontend'), { recursive: true });
    mkdirSync(join(root, 'frontend/css'), { recursive: true });
    writeFileSync(join(root, 'frontend/design-tokens.json'), JSON.stringify(tokens));
    const target = join(root, 'frontend/css/tokens.css');
    const region = renderWebRegion(tokens);
    const quiet = { root, log: () => {}, error: () => {} };
    writeFileSync(target, `/* owned */\r\n  ${region.replaceAll('\n', '\r\n')}\r\n/* hand */`);
    assert.equal(run({ ...quiet, check: true }), 0);
    writeFileSync(target, readFileSync(target, 'utf8').replace('--a-primary:', '--a-primary:#wrong;/*')); 
    assert.equal(run({ ...quiet, check: true }), 1);
    assert.equal(run(quiet), 0);
    assert.equal(readFileSync(target, 'utf8'), `/* owned */\n${region}\n/* hand */`);
    assert.equal(main(['--typo'], quiet), 1);
    assert.equal(main(['--check', '--check'], quiet), 0);
    assert.equal(readFileSync(target, 'utf8'), `/* owned */\n${region}\n/* hand */`);
    const broken = structuredClone(tokens);
    delete broken.dark.color.primary;
    writeFileSync(join(root, 'frontend/design-tokens.json'), JSON.stringify(broken));
    assert.equal(main([], quiet), 1);
    assert.equal(readFileSync(target, 'utf8'), `/* owned */\n${region}\n/* hand */`);
    writeFileSync(target, '/* no marker */');
    assert.equal(run(quiet), 1);
    assert.equal(readFileSync(target, 'utf8'), '/* no marker */');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

const linear = channel => {
  const value = channel / 255;
  return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
};
const luminance = color => {
  assert.match(color, /^#[0-9a-fA-F]{6}$/);
  const [red, green, blue] = [1, 3, 5].map(at => linear(Number.parseInt(color.slice(at, at + 2), 16)));
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
};
const contrast = (a, b) => {
  const [low, high] = [luminance(a), luminance(b)].sort((x, y) => x - y);
  return (high + 0.05) / (low + 0.05);
};
const mix = (color, percent, base) => `#${[1, 3, 5].map(at => {
  const channel = Math.round(Number.parseInt(color.slice(at, at + 2), 16) * percent / 100 +
    Number.parseInt(base.slice(at, at + 2), 16) * (1 - percent / 100));
  return channel.toString(16).padStart(2, '0');
}).join('')}`;
const declaration = (css, selector, prop) => {
  const rule = css.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\{([^}]*)\\}`));
  assert.ok(rule, selector);
  const values = Object.fromEntries(rule[1].split(';').filter(part => part.includes(':'))
    .map(part => part.split(/:(.*)/s).slice(0, 2)));
  assert.ok(prop in values, `${selector} ${prop}`);
  return values[prop].trim();
};

test('text, controls, semantic marks, and derived proposal colors retain WCAG floors', () => {
  assert.throws(() => contrast('#broken', '#ffffff'));
  const checks = [];
  for (const [theme, palette] of [['light', tokens], ['dark', tokens.dark]]) {
    const { color, neutral, state, semantic } = palette;
    for (const [name, background] of [['card', color.card_bg], ['window', color.window_bg], ['track', neutral.track]])
      checks.push([`${theme} muted/${name}`, color.muted, background, 4.5]);
    for (const [name, background] of [['card', color.card_bg], ['window', color.window_bg], ['surface alt', neutral.surface_alt]])
      checks.push([`${theme} control border/${name}`, neutral.border_control, background, 3]);
    for (const [name, background] of [['window', color.window_bg], ['card', color.card_bg]])
      checks.push([`${theme} control ink/${name}`, neutral.ink_control, background, 4.5]);
    checks.push([`${theme} ink/select`, color.ink, state.select_bg, 4.5]);
    for (const name of ['danger', 'warn'])
      checks.push([`${theme} problem underline ${name}/card`, color[name], color.card_bg, 3]);
    for (const name of ['field', 'slot', 'option'])
      checks.push([`${theme} semantic ${name}/card`, semantic[name], color.card_bg, 3]);
    for (const name of ['slot', 'option'])
      checks.push([`${theme} semantic ${name} ink`, semantic[`${name}_ink`], semantic[name], 4.5]);
  }
  const dark = tokens.dark;
  for (const name of ['primary', 'warn', 'danger', 'ok'])
    checks.push([`dark ${name}/card`, dark.color[name], dark.color.card_bg, 4.5]);
  checks.push(['dark empty/card', dark.state.data_empty_fg, dark.color.card_bg, 4.5]);
  for (const [name, foreground, background] of [
    ['ok/fill', dark.color.ok, dark.badge.fill_bg],
    ['warn/blank', dark.color.warn, dark.badge.blank_bg],
    ['danger/missing', dark.color.danger, dark.badge.missing_bg],
    ['ack', dark.badge.ack_fg, dark.badge.ack_bg],
    ['accent/primary', dark.color.on_accent, dark.color.primary],
    ['accent/ok', dark.color.on_accent, dark.color.ok],
  ]) checks.push([`dark ${name}`, foreground, background, 4.5]);

  const css = readFileSync(join(ROOT, 'frontend/css/authoring.css'), 'utf8');
  const shell = css.match(/\.authoring-shell\{(--proposal-ink:[^}]*)\}/);
  assert.ok(shell, 'proposal colors');
  const face = Number(shell[1].match(/--proposal-face:color-mix\(in srgb,var\(--a-sem-field\) (\d+)%,var\(--a-card\)\)/)[1]);
  const held = Number(shell[1].match(/--proposal-held:color-mix\(in srgb,var\(--a-muted\) (\d+)%,var\(--a-card\)\)/)[1]);
  for (const [theme, palette] of [['light', tokens], ['dark', tokens.dark]]) {
    const card = palette.color.card_bg;
    const proposalFace = mix(palette.semantic.field, face, card);
    const ink = { 'var(--a-ink)': palette.color.ink, 'var(--proposal-ink)': palette.semantic.field,
      'var(--n-ink-soft)': palette.neutral.ink_soft };
    for (const [name, selector] of [['tag', '.authoring-document .cm-authoring-proposal-tag'],
      ['format pill', '.authoring-proposal-fmt']])
      checks.push([`${theme} proposal ${name} text/face`, ink[declaration(css, selector, 'color')], proposalFace, 4.5]);
    checks.push([`${theme} held tag text/card`,
      ink[declaration(css, '.authoring-document .cm-authoring-proposal-tag.cm-authoring-proposal-held', 'color')], card, 4.5]);
    checks.push([`${theme} proposal underline/card`, palette.semantic.field, card, 3]);
    checks.push([`${theme} held underline/card`, mix(palette.color.muted, held, card), card, 3]);
  }
  const failures = checks.filter(([, foreground, background, floor]) => contrast(foreground, background) < floor)
    .map(([name, foreground, background, floor]) => `${name}: ${contrast(foreground, background).toFixed(2)}:1 < ${floor}:1`);
  assert.deepEqual(failures, []);
});
