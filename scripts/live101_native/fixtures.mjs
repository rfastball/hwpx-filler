import { createHash, randomBytes } from 'node:crypto';
import { mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const MANIFEST = path.join(ROOT, 'fixtures/manifest.json');
const SECTION_SOURCE = 'data/발주목록.csv';

export function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function contained(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative !== '' && relative !== '..'
    && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

async function atomicBytes(target, bytes) {
  const temporary = `${target}.live101-${randomBytes(8).toString('hex')}`;
  try {
    await writeFile(temporary, bytes, { flag: 'wx' });
    await rename(temporary, target);
  } catch (error) {
    // A failed staging action remains an explicit failed test, never a partial success.
    throw new Error(`native live101 fixture staging failed at ${target}: ${error.message}`);
  }
}

export async function verifyFixtures(home) {
  const manifest = JSON.parse(await readFile(MANIFEST, 'utf8'));
  for (const name of ['base', 'initial', 'successor']) {
    const entry = manifest[name];
    const file = name === 'base'
      ? path.join(home, 'templates/발주요청서.hwpx')
      : path.join(ROOT, 'fixtures', entry.path);
    const bytes = await readFile(file);
    if (bytes.length !== entry.size || sha256(bytes) !== entry.sha256) {
      throw new Error(`SX-05 ${name} fixture differs from its checked source`);
    }
  }
  return manifest;
}

export async function workTemplate(home, name) {
  const job = JSON.parse(await readFile(path.join(home, 'jobs', `${name}.job.json`), 'utf8'));
  const template = path.resolve(job.template_path);
  const applied = path.resolve(home, 'template_authority/applied');
  if (!contained(applied, template)) {
    throw new Error(`SX-05 Work template is outside its isolated applied store: ${template}`);
  }
  return template;
}

export class Staging {
  constructor(home, manifest) {
    this.home = home;
    this.fixtureManifest = manifest;
    this.secret = null;
    this.sourceBackup = null;
  }

  async template(kind) {
    if (!['initial', 'successor'].includes(kind)) throw new Error(`unknown SX-05 template ${kind}`);
    const file = path.join(ROOT, 'fixtures', this.fixtureManifest[kind].path);
    const bytes = await readFile(file);
    if (sha256(bytes) !== this.fixtureManifest[kind].sha256) throw new Error(`SX-05 ${kind} fixture changed`);
    const target = await workTemplate(this.home, '발주요청서');
    await atomicBytes(target, bytes);
    return target;
  }

  async data(kind) {
    const source = path.join(this.home, SECTION_SOURCE);
    if (kind === 'clean') {
      if (this.sourceBackup) {
        await atomicBytes(source, this.sourceBackup);
        this.sourceBackup = null;
      }
      return source;
    }
    if (kind === 'missing') return path.join(this.home, 'data/sx05-does-not-exist.csv');
    const target = path.join(this.home, `data/sx05-${kind}.csv`);
    if (kind === 'incompatible') {
      await writeFile(target, '\ufeff다른항목\n값\n', 'utf8');
      return target;
    }
    if (!['blank', 'release'].includes(kind)) throw new Error(`unknown SX-05 data stage ${kind}`);
    const current = await readFile(source);
    const text = current.toString('utf8').replace(/^\ufeff/, '').replace(/\r\n/g, '\n');
    const lines = text.trimEnd().split('\n').map(line => line.split(','));
    const index = lines[0].indexOf('공고명');
    if (lines.length < 2 || index < 0) throw new Error('SX-05 CSV field is missing');
    if (kind === 'blank') lines[1][index] = '';
    else for (const row of lines) row.splice(index, 1);
    const output = `\ufeff${lines.map(row => row.join(',')).join('\n')}\n`;
    if (kind === 'blank') {
      this.sourceBackup ??= current;
      await atomicBytes(source, Buffer.from(output, 'utf8'));
      return source;
    }
    await writeFile(target, output, 'utf8');
    return target;
  }

  async context(kind) {
    const target = path.join(this.home, 'template_authority/slot_token_secret.json');
    if (kind === 'corrupt') {
      this.secret = await readFile(target);
      await atomicBytes(target, Buffer.from('{corrupt'));
    } else if (kind === 'restore' && this.secret) {
      await atomicBytes(target, this.secret);
      this.secret = null;
    } else {
      throw new Error(`unknown SX-05 context stage ${kind}`);
    }
  }

  async output() {
    const output = path.join(this.home, 'sx-output');
    await mkdir(output, { recursive: true });
    return output;
  }

  async collision(relative) {
    const output = path.resolve(this.home, 'sx-output');
    const target = path.resolve(output, relative);
    if (!contained(output, target)) throw new Error('SX-05 collision leaves isolated output');
    await mkdir(path.dirname(target), { recursive: true });
    await atomicBytes(target, Buffer.from('sx05-existing-output\n'));
  }

  async manifest() {
    const output = path.join(this.home, 'sx-output');
    const result = {};
    async function descend(directory, prefix = '') {
      for (const item of await readdir(directory, { withFileTypes: true })) {
        const relative = path.posix.join(prefix, item.name);
        if (item.isDirectory()) await descend(path.join(directory, item.name), relative);
        else if (item.isFile()) result[relative] = sha256(await readFile(path.join(directory, item.name)));
      }
    }
    await descend(output);
    return result;
  }
}
