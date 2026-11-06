// Design tokens are the single source for the generated region of frontend/css/tokens.css.
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const TOKENS = join(ROOT, 'frontend', 'design-tokens.json');
const CSS = join(ROOT, 'frontend', 'css', 'tokens.css');
const OPEN = '/* <gen:tokens> */';
const CLOSE = '/* </gen:tokens> */';

const WEB = [
  ['--a-primary', 'color.primary'], ['--a-primary-h', 'color.primary_hover'],
  ['--a-brand', 'color.brand'], ['--a-warn', 'color.warn'], ['--a-danger', 'color.danger'],
  ['--a-ok', 'color.ok'], ['--a-muted', 'color.muted'], ['--a-border', 'color.border'],
  ['--a-card', 'color.card_bg'], ['--a-window', 'color.window_bg'], ['--a-ink', 'color.ink'],
  ['--a-on-accent', 'color.on_accent'], ['--a-shadow', 'color.shadow'],
  ['--a-scrim', 'color.scrim'], ['--a-scrim-reduced', 'color.scrim_reduced'],
  ['--a-unconf', 'state.unconfirmed_bg'], ['--a-unmatch', 'state.unmatched_bg'],
  ['--a-empty', 'state.data_empty_fg'], ['--a-sel', 'state.select_bg'],
  ['--fb-fill-bg', 'badge.fill_bg'], ['--fb-fill-bd', 'badge.fill_border'],
  ['--fb-blank-bg', 'badge.blank_bg'], ['--fb-blank-bd', 'badge.blank_border'],
  ['--fb-missing-bg', 'badge.missing_bg'], ['--fb-missing-bd', 'badge.missing_border'],
  ['--fb-ack-bg', 'badge.ack_bg'], ['--fb-ack-fg', 'badge.ack_fg'],
  ['--fb-ack-bd', 'badge.ack_border'], ['--fb-missing-press', 'badge.missing_press'],
  ['--n-surface-alt', 'neutral.surface_alt'], ['--n-hover', 'neutral.hover'],
  ['--n-pressed', 'neutral.pressed'], ['--n-track', 'neutral.track'],
  ['--n-header-bg', 'neutral.header_bg'], ['--n-border-strong', 'neutral.border_strong'],
  ['--n-border-control', 'neutral.border_control'], ['--n-ink-soft', 'neutral.ink_soft'],
  ['--n-header-ink', 'neutral.header_ink'], ['--n-ink-control', 'neutral.ink_control'],
  ['--log-surface', 'log.surface'], ['--log-ink', 'log.ink'],
  ['--a-sem-field', 'semantic.field'], ['--a-sem-slot', 'semantic.slot'],
  ['--a-sem-option', 'semantic.option'], ['--a-sem-slot-ink', 'semantic.slot_ink'],
  ['--a-sem-option-ink', 'semantic.option_ink'],
];
const SCALE = [
  ['--sp-2', 'space.2'], ['--sp-4', 'space.4'], ['--sp-6', 'space.6'],
  ['--sp-8', 'space.8'], ['--sp-10', 'space.10'], ['--sp-12', 'space.12'],
  ['--sp-16', 'space.16'], ['--sp-24', 'space.24'], ['--sp-40', 'space.40'],
  ['--rad-control', 'radius.control'], ['--rad-surface', 'radius.surface'],
  ['--rad-overlay', 'radius.overlay'], ['--rad-pill', 'radius.pill'],
  ['--fs-caption', 'type.caption'], ['--fs-body', 'type.body'],
  ['--fs-dense', 'type.dense'], ['--fs-strong', 'type.strong'],
  ['--fs-section', 'type.section'], ['--fs-kpi', 'type.kpi'],
];
const MOTION = [
  ['--dur-press', 'motion.dur_press', 'ms'], ['--dur-pop', 'motion.dur_pop', 'ms'],
  ['--dur-modal', 'motion.dur_modal', 'ms'], ['--ease-out', 'motion.ease_out', ''],
  ['--ease-in-out', 'motion.ease_in_out', ''],
];
const LAYER = [
  ['--z-overlay-root', 'layer.overlay_root'], ['--z-popover', 'layer.popover'],
  ['--z-modal', 'layer.modal'],
];
const FONT = [['--font-ui', 'font.ui'], ['--font-mono', 'font.mono']];

const valueAt = (source, path) => path.split('.').reduce((value, part) => {
  if (value === null || typeof value !== 'object' || !Object.hasOwn(value, part)) {
    throw new Error(`필수 디자인 토큰이 없습니다: ${path}`);
  }
  return value[part];
}, source);
const declarations = (source, rows, indent, render = value => value) =>
  rows.map(([name, path, unit = '']) => `${indent}${name}:${render(valueAt(source, path), path)}${unit};`);

export function renderWebRegion(tokens) {
  const scale = declarations(tokens, SCALE, '  ', (value, path) =>
    path.startsWith('type.') ? `${value / 16}rem` : `${value}px`);
  const lines = [OPEN, ':root{',
    ...declarations(tokens, WEB, '  '), ...scale,
    ...declarations(tokens, MOTION, '  '), ...declarations(tokens, LAYER, '  '),
    ...declarations(tokens, FONT, '  '),
    '  color-scheme:light;', '}',
    'html{font-size:100%;}',
    'html[data-font-scale="large"]{font-size:125%;}',
    'html[data-font-scale="larger"]{font-size:150%;}',
    '@media (prefers-color-scheme:dark){',
    '  :root:not([data-theme="light"]){',
    ...declarations(tokens.dark, WEB, '    '),
    '    color-scheme:dark;', '  }', '}',
    ':root[data-theme="dark"]{',
    ...declarations(tokens.dark, WEB, '  '),
    '  color-scheme:dark;', '}', CLOSE];
  return lines.join('\n');
}

const REGION = /[ \t]*\/\* <gen:tokens> \*\/[\s\S]*?\/\* <\/gen:tokens> \*\//;
const normalized = text => text.replace(/\r\n?/g, '\n');

export function run({ root = ROOT, check = false, log = console.log, error = console.error } = {}) {
  const tokensPath = root === ROOT ? TOKENS : join(root, 'frontend', 'design-tokens.json');
  const cssPath = root === ROOT ? CSS : join(root, 'frontend', 'css', 'tokens.css');
  const tokens = JSON.parse(readFileSync(tokensPath, 'utf8'));
  const css = normalized(readFileSync(cssPath, 'utf8'));
  const match = REGION.exec(css);
  if (check) {
    const problem = !match ? 'tokens.css: <gen:tokens> 마커 없음' :
      match[0].trim() !== renderWebRegion(tokens).trim() ?
        'tokens.css: 토큰 드리프트(design-tokens.json 과 불일치)' : '';
    if (problem) { error(`토큰 드리프트:\n  ${problem}`); return 1; }
    log('토큰 동기화 OK (frontend/css/tokens.css)');
    return 0;
  }
  if (!match) { error(`마커(${OPEN} … ${CLOSE})를 파일에서 찾을 수 없습니다.`); return 1; }
  writeFileSync(cssPath, css.replace(REGION, renderWebRegion(tokens)), 'utf8');
  log('재생성 완료: frontend/css/tokens.css');
  return 0;
}

export function main(args = process.argv.slice(2), options = {}) {
  if (args.some(arg => arg !== '--check')) {
    (options.error ?? console.error)('usage: node scripts/gen_design_tokens.mjs [--check]');
    return 1;
  }
  try { return run({ ...options, check: args.includes('--check') }); }
  catch (cause) { (options.error ?? console.error)(String(cause)); return 1; }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  process.exitCode = main();
}
