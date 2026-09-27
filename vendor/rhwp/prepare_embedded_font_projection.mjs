import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const studio = process.argv[2];
if (!studio) throw new Error('Studio source directory required');
const dir = join(studio, 'src/core/generated/font-rule-projections');
const source = readFileSync(join(dir, 'canvaskit-sfnt.ts'), 'utf8');
const urls = source.match(/https?:\/\/[^"'\s]+/g) ?? [];
if (urls.length !== 128 || urls.some(url => !url.startsWith('https://cdn.jsdelivr.net/')))
  throw new Error(`Unexpected CanvasKit external font catalog: ${urls.length} URLs`);
// RHWP_DISABLE_EXTERNAL_WEBFONTS selects each rule's offline snapshot. Keep the
// generated rule IDs and local font data while removing unreachable CDN strings.
const embedded = source.replace(/https?:\/\/[^"'\s]+/g, 'unavailable-external-font');
writeFileSync(join(dir, 'canvaskit-sfnt-embedded.ts'), embedded);
