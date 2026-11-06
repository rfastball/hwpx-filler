// Generated docs views. Inputs are the checked manifest and declared runtime authorities.
import path from 'node:path';
import { CORE, INDEX, PRODUCT, REFERENCE, inventory, topicBodies } from './docs_contract_core.mjs';
import { environmentDeclarations } from './docs_runtime.mjs';
import { readFileSync } from 'node:fs';

const read = (root, name) => readFileSync(path.join(root, name), 'utf8')
  .replace(/^\uFEFF/, '').replaceAll('\r\n', '\n');
const fromDocs = name => name.startsWith('docs/') ? name.slice(5) : `../${name}`;

export function renderIndex(root, data = inventory(root)) {
  const records = data.document;
  const lines = ['# 문서 지도', '', '> manifest.toml에서 생성한다. 직접 편집하지 않는다.', '',
    '현재 동작은 코드·테스트·빌드 설정이 최종 권위다. 같은 목적의 새 파일 대신 소유 절을 갱신한다.',
    '절차·이름·예산·검토 명령은 [기여 규칙](../CONTRIBUTING.md)을 따른다.',
    '', '## 읽기와 쓰기의 다섯 목적지', '', '| 목적 | 정본 |', '|---|---|'];
  for (const [role, name] of Object.entries(CORE)) {
    const doc = records.find(item => item.role === role);
    lines.push(`| \`${role}\` | [${doc.title}](${fromDocs(name)}) |`);
  }
  lines.push('', '## 주제별 작성 라우팅', '', '| 주제 | 갱신할 절 |', '|---|---|');
  for (const doc of records.filter(item => item.kind === 'canonical')) {
    const bodies = topicBodies(root, doc);
    for (const topic of data.topic.filter(item => item.document === doc.path)) {
      const title = bodies[topic.id].match(/^## (.+)$/m)?.[1];
      if (!title) throw new Error(`missing topic heading: ${topic.id}`);
      lines.push(`| \`${topic.id}\` | [${title}](${fromDocs(doc.path)}#${topic.id}) |`);
    }
  }
  for (const [kinds, label] of [
    [new Set(['generated', 'current']), '진입점·생성 참조'],
    [new Set(['machine']), '실행 가능한 원장'],
    [new Set(['evidence', 'research']), '관측과 연구'],
  ]) {
    lines.push('', `## ${label}`, '');
    for (const doc of records) {
      if (kinds.has(doc.kind) && doc.path !== INDEX) {
        lines.push(`- [${doc.title}](${fromDocs(doc.path)})`);
      }
    }
  }
  lines.push('', '기능 계획·진행·담당·완료·리뷰는 GitHub 이슈·PR, 재현 입력은 테스트 fixture에 둔다.',
    '작은 제안은 이슈로, 독립 장문 모델만 연구로 분리한다. 증거·연구는 현재 계약을 대신하지 않는다.',
    '예제 설명·코퍼스·테스트/제품 HTML도 manifest에 용도별 정확한 경로로 등록한다.');
  return `${lines.join('\n')}\n`;
}

export function renderProduct(root) {
  let text = read(root, CORE.product).split('\n').slice(1).join('\n').replace(/^\n+/, '');
  if (!/^### Platform\n\n(?:web|ios|android|adaptive)\s*$/m.test(text)) {
    throw new Error('missing/invalid Platform in product source');
  }
  text = text.replace(/^<a id="[a-z][a-z0-9-]*"><\/a>\s*$/gm, '').replace(/^### /gm, '## ');
  text = text.replace(/\]\(([^)]+)\)/g, (whole, target) => {
    if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith('//')) return whole;
    const [pathname, fragment = ''] = target.split('#');
    if (!pathname) return whole;
    const resolved = path.posix.normalize(`docs/${pathname}`);
    return `](${resolved}${fragment ? `#${fragment}` : ''})`;
  });
  return '# Product\n\n<!-- impeccable:product-schema 1 -->\n\n' +
    '> Generated from [docs/product.md](docs/product.md). Edit that source, then run ' +
    '`node scripts/docs_contract.mjs --write`.\n\n' + text.replace(/^\n+/, '');
}

function workflowJobs(root) {
  const text = read(root, '.github/workflows/quality.yml');
  const jobsText = text.split('\njobs:\n')[1];
  if (!jobsText) throw new Error('missing explicit workflow jobs mapping');
  const jobs = [...jobsText.matchAll(/^  ([^\s:\n]+):[^\n]*$/gm)].map(match => match[1]);
  if (!jobs.length || jobs.some(job => !/^[A-Za-z_][\w-]*$/.test(job)) || !jobs.includes('quality-gate')) {
    throw new Error('unsupported workflow job key syntax');
  }
  const gate = jobsText.split('  quality-gate:\n')[1]?.split(/\n  [A-Za-z_][\w-]*:/, 1)[0];
  const needsBlock = gate?.match(/^    needs:\s*\n((?:      - [\w-]+\n)+)/m)?.[1];
  if (!needsBlock) throw new Error('quality-gate needs must explicitly enumerate jobs');
  return [jobs, [...needsBlock.matchAll(/- ([\w-]+)/g)].map(match => match[1])];
}

export function renderReference(root) {
  const [desktop, rows] = environmentDeclarations(root);
  const host = JSON.parse(read(root, 'crates/hwpx-desktop/src/host_contract.json'));
  const registry = JSON.parse(read(root, 'crates/hwpx-desktop/src/action_registry.json'));
  const lines = ['# 코드에서 생성한 런타임 참조', '',
    '> 생성물: `node scripts/docs_contract.mjs --write`. 직접 편집하지 않는다.',
    '> 선언·등록 목록이다. 채널이나 메서드가 있다는 사실은 사용자 기능의 노출을 뜻하지 않는다.',
    '', '## 환경 선언', '', '| 항목 | 선언 | 원천 |', '|---|---|---|'];
  for (const [label, value, source] of rows) {
    lines.push(`| ${label} | \`${value}\` | [${source}](../../${source}) |`);
  }
  lines.push('', '## 진입점', '', '| 종류 | 명령 | 대상 |', '|---|---|---|');
  for (const binary of desktop.bin) {
    lines.push(`| Cargo binary | \`${binary.name}\` | [${binary.path}](../../crates/hwpx-desktop/${binary.path}) |`);
  }
  const [jobs, needs] = workflowJobs(root);
  lines.push('', 'Rust CLI:', '', '```powershell',
    '.\\run-filler.ps1 -Cli --template T.hwpx --data data.csv --out out --ledger',
    'cargo run --locked -p hwpx-desktop --bin hwpxfiller --no-default-features -- --template T.hwpx --fields',
    'cargo run --locked -p hwpx-desktop --bin hwpxfiller --no-default-features -- schema T.hwpx --out schema.json',
    'cargo run --locked -p hwpx-desktop --bin hwpxfiller --no-default-features -- drift OLD.hwpx NEW.hwpx',
    '```', '', '## 품질 CI', '',
    '원천: [quality.yml](../../.github/workflows/quality.yml). 실제 설정의 등록 목록이다.',
    '', `- Jobs: ${jobs.map(job => `\`${job}\``).join(', ')}`,
    `- \`quality-gate.needs\`: ${needs.map(job => `\`${job}\``).join(', ')}`,
    '', '## Native host 공개 메서드', '',
    '원천: [host_contract.json](../../crates/hwpx-desktop/src/host_contract.json).',
    '직접 호출의 인자·선택 여부를 Rust 라우터도 같은 표에서 검증한다.',
    '', '| 메서드 | 인자 |', '|---|---|');
  for (const method of host.host_methods) {
    const args = method.params.map(param => `${param.name}${param.optional ? ' = None' : ''}`).join(', ');
    lines.push(`| \`${method.name}\` | \`${args}\` |`);
  }
  lines.push('', '## 시험 전용 호스트 채널', '',
    '[Tauri 호스트](../../crates/hwpx-desktop/src/tauri_host.rs)는 시험 능력이 있는 실행에서만',
    '`selftest_claim`(version)과 `selftest_host_op`(op, payload)를 받는다.',
    '이 채널은 공개 host 메서드 목록과 분리되며 일반 실행에서는 거절한다.',
    '', '## Dispatch registry', '',
    '원천: [action_registry.json](../../crates/hwpx-desktop/src/action_registry.json).',
    '직접 host 호출의 payload 검증은 이 표 밖이다.');
  for (const [screen, actions] of Object.entries(registry).sort(([a], [b]) => a.localeCompare(b))) {
    lines.push('', `### ${screen}`, '', '| 액션 | 필수 키 | 선택 키 |', '|---|---|---|');
    for (const [action, schema] of Object.entries(actions).sort(([a], [b]) => a.localeCompare(b))) {
      const format = list => list.length ? list.map(key => `\`${key}\``).join(', ') : '—';
      lines.push(`| \`${action}\` | ${format(schema.required)} | ${format(schema.optional)} |`);
    }
  }
  return `${lines.join('\n')}\n`;
}

export function generatedOutputs(root, data = inventory(root)) {
  return { [INDEX]: renderIndex(root, data), [REFERENCE]: renderReference(root),
    [PRODUCT]: renderProduct(root) };
}
