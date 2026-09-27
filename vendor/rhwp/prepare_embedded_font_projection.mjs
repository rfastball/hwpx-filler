import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const studio = process.argv[2];
if (!studio) throw new Error('Studio source directory required');
const dir = join(studio, 'src/core/generated/font-rule-projections');
const URL_PATTERN = /https?:\/\/[^"'\s]+/g;
const expectExternalCatalog = (name, source) => {
  const urls = source.match(URL_PATTERN) ?? [];
  if (urls.length !== 128 || urls.some(url => !url.startsWith('https://cdn.jsdelivr.net/')))
    throw new Error(`Unexpected ${name} external font catalog: ${urls.length} URLs`);
};

const source = readFileSync(join(dir, 'canvaskit-sfnt.ts'), 'utf8');
expectExternalCatalog('CanvasKit', source);
// RHWP_DISABLE_EXTERNAL_WEBFONTS selects each rule's offline snapshot. Keep the
// generated rule IDs and local font data while removing unreachable CDN strings.
const embedded = source.replace(URL_PATTERN, 'unavailable-external-font');
writeFileSync(join(dir, 'canvaskit-sfnt-embedded.ts'), embedded);

// Canvas2D webfont supply: the embedded runtime cannot reach the CDN, so keep only
// the rules that carry no external URL and re-seal the projection metadata. The
// generated source is parsed as text (JSON literals inside Object.freeze) so the
// build does not depend on Node's TypeScript stripping.
const webfont = readFileSync(join(dir, 'webfont-supply.ts'), 'utf8');
expectExternalCatalog('Canvas2D webfont', webfont);
const META_HEAD = 'export const FONT_RULE_CANVAS2D_WEBFONT_META = Object.freeze(';
const RULES_HEAD =
  'export const FONT_RULE_CANVAS2D_WEBFONT_RULES: readonly GeneratedFontRuleProjection[] = Object.freeze(';
const metaAt = webfont.indexOf(META_HEAD);
const metaEnd = webfont.indexOf('});', metaAt);
const rulesAt = webfont.indexOf(RULES_HEAD, metaEnd);
// Tolerate CRLF checkouts (older caches); the generated file is LF throughout.
const body = webfont.trimEnd();
if (metaAt < 0 || metaEnd < 0 || rulesAt < 0 || !body.endsWith(']);'))
  throw new Error('Unexpected Canvas2D webfont projection layout');
const meta = JSON.parse(webfont.slice(metaAt + META_HEAD.length, metaEnd + 1));
const allRules = JSON.parse(body.slice(rulesAt + RULES_HEAD.length, -2));
if (meta.projectionId !== 'canvas2d-webfont' || meta.ruleCount !== allRules.length || allRules.length !== 153)
  throw new Error(`Unexpected Canvas2D webfont projection: ${meta.projectionId} ${meta.ruleCount}/${allRules.length}`);
const rules = allRules.filter(rule => !/https?:\/\//.test(JSON.stringify(rule)));
if (rules.length !== 62 || rules.some(rule => rule.supply?.external !== false))
  throw new Error(`Unexpected Canvas2D local webfont rules: ${rules.length}`);
const embeddedMeta = {
  ...meta,
  projectionId: 'canvas2d-webfont-embedded',
  ruleCount: rules.length,
  projectionSha256: createHash('sha256').update(JSON.stringify(rules)).digest('hex'),
};
writeFileSync(join(dir, 'webfont-supply-embedded.ts'), webfont.slice(0, metaAt).replace(/\r\n/g, '\n') +
  `${META_HEAD}${JSON.stringify(embeddedMeta, null, 2)});\n` +
  `${RULES_HEAD}${JSON.stringify(rules, null, 2)});\n`);
