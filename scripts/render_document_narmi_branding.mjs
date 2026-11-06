// Rasterize the canonical SVGs with installed Chrome; no Python or image library.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const icoSizes = [16, 24, 32, 48, 64, 128, 256];
const prefix = 'document-narmi-mark-';
export const tierFor = size => prefix + (size <= 24 ? 'micro' : size <= 32 ? 'small' : 'full');
const stems = ['micro', 'micro-reversed', 'small', 'small-reversed', 'full', 'full-reversed']
  .map(name => prefix + name).concat('document-narmi-lockup');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const readText = file => readFileSync(file, 'utf8').replace(/\r\n?/gu, '\n');

export function encodeIco(frames) {
  if (frames.length !== icoSizes.length) throw new Error('all seven native-size ICO frames required');
  const header = Buffer.alloc(6 + frames.length * 16);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(frames.length, 4);
  let offset = header.length;
  frames.forEach((png, at) => {
    const size = icoSizes[at];
    if (!Buffer.isBuffer(png) || png.length < 33
        || !png.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'))
        || png.readUInt32BE(16) !== size || png.readUInt32BE(20) !== size) {
      throw new Error(`invalid ${size}px ICO PNG frame`);
    }
    const entry = 6 + at * 16;
    header[entry] = header[entry + 1] = size === 256 ? 0 : size;
    header.writeUInt16LE(1, entry + 4);
    header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(png.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += png.length;
  });
  return Buffer.concat([header, ...frames]);
}

// Runs in Chrome. Images are rasterized at their final pixel dimensions, never downsampled.
async function renderInBrowser(sources, sizes) {
  const tier = size => 'document-narmi-mark-' + (size <= 24 ? 'micro' : size <= 32 ? 'small' : 'full');
  const canvas = (width, height) => Object.assign(document.createElement('canvas'), { width, height });
  const boxes = new Map();
  function svg(stem) { return new DOMParser().parseFromString(sources[stem], 'image/svg+xml').documentElement; }
  async function raster(stem, width, height, viewBox) {
    const source = svg(stem);
    source.setAttribute('width', width);
    source.setAttribute('height', height);
    if (viewBox) source.setAttribute('viewBox', viewBox.map(value => value.toFixed(4)).join(' '));
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error(`failed to rasterize ${stem}`));
      image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(source));
    });
    const result = canvas(width, height);
    result.getContext('2d').drawImage(image, 0, 0, width, height);
    return result;
  }
  function alphaBounds(image) {
    const { width, height } = image;
    const pixels = image.getContext('2d').getImageData(0, 0, width, height).data;
    let left = width, top = height, right = 0, bottom = 0;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        if (!pixels[(y * width + x) * 4 + 3]) continue;
        left = Math.min(left, x); top = Math.min(top, y);
        right = Math.max(right, x + 1); bottom = Math.max(bottom, y + 1);
      }
    }
    if (left >= right || top >= bottom) throw new Error('empty SVG raster');
    return [left, top, right - left, bottom - top];
  }
  async function tightBox(stem) {
    if (boxes.has(stem)) return boxes.get(stem);
    const [vx, vy, vw, vh] = svg(stem).getAttribute('viewBox').trim().split(/[\s,]+/u).map(Number);
    const bounds = alphaBounds(await raster(stem, 512, Math.round(512 * vh / vw)));
    const scale = vw / 512;
    const box = [vx + bounds[0] * scale, vy + bounds[1] * scale, bounds[2] * scale, bounds[3] * scale];
    boxes.set(stem, box);
    return box;
  }
  async function square(stem, size, fill = 0.94) {
    const [x, y, w, h] = await tightBox(stem);
    const side = Math.max(w, h) / fill;
    return raster(stem, size, size, [x + w / 2 - side / 2, y + h / 2 - side / 2, side, side]);
  }
  async function wide(stem, height) {
    const box = await tightBox(stem);
    return raster(stem, Math.round(height * box[2] / box[3]), height, box);
  }
  async function board(frames) {
    const result = canvas(1440, 1020), ctx = result.getContext('2d');
    ctx.fillStyle = '#F4F6F9'; ctx.fillRect(0, 0, 1440, 1020);
    function text(x, y, value, size, color, bold = false) {
      ctx.font = `${bold ? 'bold ' : ''}${size}px "Malgun Gothic"`;
      ctx.textBaseline = 'top'; ctx.fillStyle = color; ctx.fillText(value, x, y);
    }
    function panel(x, y, width, height, color = '#FFFFFF') {
      ctx.fillStyle = color; ctx.beginPath(); ctx.roundRect(x, y, width, height, 28); ctx.fill();
    }
    text(96, 76, '문서나르미', 24, '#111827', true);
    text(96, 121, '세 문서 면이 오른쪽 위로 흐르며 원본에서 결과물까지 이어집니다.', 17, '#667085');
    panel(96, 194, 1248, 326);
    ctx.drawImage(await wide('document-narmi-lockup', 132), 180, 285);
    text(184, 452, 'HWPX 문서 자동화', 18, '#667085');
    panel(96, 552, 608, 370);
    text(144, 590, 'SIZE TIERS', 20, '#111827', true);
    text(144, 630, '프레임마다 다른 정본을 싣는다 — 한 그림은 16px 을 못 버틴다.', 15, '#667085');
    for (const [size, x] of [[16, 150], [24, 250], [32, 370], [48, 500]]) {
      ctx.drawImage(frames[sizes.indexOf(size)], x, 780 - size);
      text(x, 800, `${size} px`, 14, '#98A2B3');
      text(x, 826, tier(size).split('-').at(-1), 13, '#B4BCC8');
    }
    panel(736, 552, 608, 370, '#0E3FAE');
    text(784, 590, 'TONAL REVERSED', 20, 'white', true);
    text(784, 630, '어두운 면에서는 겹침을 살리는 밝은 세 톤으로 반전합니다.', 15, '#DCEBFA');
    for (const [size, x] of [[24, 800], [32, 900], [64, 1010]]) {
      ctx.drawImage(await square(tier(size) + '-reversed', size), x, 790 - size);
      text(x, 810, `${size} px`, 14, '#9FC0F5');
    }
    text(1130, 742, '문서나르미', 36, 'white', true);
    for (const [x, color, label] of [[102, '#0E3FAE', 'Deep Blue  #0E3FAE'],
      [336, '#1857D8', 'Flow Blue  #1857D8'], [582, '#43C9A8', 'Result Mint  #43C9A8']]) {
      ctx.fillStyle = color; ctx.beginPath(); ctx.ellipse(x + 11, 969, 11, 11, 0, 0, Math.PI * 2); ctx.fill();
      text(x + 35, 954, label, 16, '#475467');
    }
    return result;
  }
  await document.fonts.load('24px "Malgun Gothic"');
  const frames = await Promise.all(sizes.map(size => square(tier(size), size)));
  const png = image => image.toDataURL('image/png').split(',')[1];
  return { frames: frames.map(png), mark: png(await square(tier(256), 256, 0.92)), board: png(await board(frames)) };
}

function chromePath() {
  const candidates = ['ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA']
    .filter(key => process.env[key]).map(key => path.join(process.env[key], 'Google/Chrome/Application/chrome.exe'));
  const chrome = candidates.find(existsSync);
  if (!chrome) throw new Error('installed Google Chrome is required to render branding');
  return chrome;
}

function requireBrandingFonts() {
  if (process.platform !== 'win32') throw new Error('branding uses the Windows Malgun Gothic font');
  for (const name of ['malgun.ttf', 'malgunbd.ttf']) {
    if (!existsSync(path.join(process.env.WINDIR ?? 'C:/Windows', 'Fonts', name))) {
      throw new Error(`branding font is missing: ${name}`);
    }
  }
}

function rasterResult(run) {
  if (run.error) throw run.error;
  if (run.status !== 0) throw new Error(`Chrome exited ${run.status}: ${run.stderr}`);
  const serialized = run.stdout.match(/<pre id="result">([^<]*)<\/pre>/u)?.[1];
  if (!serialized) throw new Error('Chrome did not finish the branding raster');
  const result = JSON.parse(serialized);
  if (result.error) throw new Error(result.error);
  return result;
}

export function renderBranding(outputRoot = root) {
  requireBrandingFonts();
  const sources = Object.fromEntries(stems.map(stem => [stem, readText(path.join(root, 'assets/branding', stem + '.svg'))]));
  mkdirSync(path.join(root, '.cache'), { recursive: true });
  const work = mkdtempSync(path.join(root, '.cache/branding-'));
  const html = path.join(work, 'render.html');
  writeFileSync(html, '<!doctype html><meta charset="utf-8"><pre id="result"></pre><script>\n'
    + `(${renderInBrowser.toString()})(${JSON.stringify(sources).replaceAll('<', '\\u003c')},${JSON.stringify(icoSizes)})`
    + '.then(result=>document.getElementById("result").textContent=JSON.stringify(result))'
    + '.catch(error=>document.getElementById("result").textContent=JSON.stringify({error:String(error)}));</script>');
  // https://developer.chrome.com/docs/automation-and-testing/headless-cli
  const run = spawnSync(chromePath(), ['--headless', '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-extensions', '--disable-sync',
    '--user-data-dir=' + path.join(work, 'profile'), '--dump-dom', '--virtual-time-budget=10000', pathToFileURL(html).href],
  { windowsHide: true, encoding: 'utf8', timeout: 45000, maxBuffer: 16 * 1024 * 1024 });
  const profile = path.resolve(work, 'profile');
  if (path.dirname(work) !== path.resolve(root, '.cache') || path.dirname(profile) !== work) {
    throw new Error('temporary Chrome profile escaped the rendering workspace');
  }
  rmSync(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
  const result = rasterResult(run);
  const frames = result.frames.map(frame => Buffer.from(frame, 'base64'));
  const files = {
    'assets/branding/document-narmi-mark-full.png': Buffer.from(result.mark, 'base64'),
    'assets/branding/document-narmi-board.png': Buffer.from(result.board, 'base64'),
    'packaging/hwpx-filler.ico': encodeIco(frames),
  };
  for (const [name, bytes] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(outputRoot, name)), { recursive: true });
    writeFileSync(path.join(outputRoot, name), bytes);
  }
  const manifest = {
    generator_sha256: sha(readText(fileURLToPath(import.meta.url))),
    inputs: Object.fromEntries(stems.map(stem => [`assets/branding/${stem}.svg`, sha(sources[stem])])),
    files: Object.fromEntries(Object.entries(files).map(([name, bytes]) => [name, sha(bytes)])),
  };
  writeFileSync(path.join(outputRoot, 'assets/branding/branding-manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  return { output: path.resolve(outputRoot), evidence: work };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length > 3) throw new Error('usage: node scripts/render_document_narmi_branding.mjs [output-root]');
    console.log(JSON.stringify(renderBranding(process.argv[2] ? path.resolve(process.argv[2]) : root)));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
