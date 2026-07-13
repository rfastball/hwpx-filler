export const meta = {
  name: 'feature',
  description: 'filler 기능 워크플로 — 영향도→계획(확정 게이트)→직렬/직교 병렬 구현→결정적+적대적 리뷰→머지 준비 보고',
  whenToUse: 'hwpx-filler에 기능을 추가·변경할 때. mode:"plan"으로 먼저 호출해 계획을 확정받고, mode:"implement"로 재호출한다.',
  phases: [
    { title: 'Impact', detail: '읽기 전용 영향도 조사 — unknowns는 억지로 채우지 않는다' },
    { title: 'Plan', detail: 'task 분할 + 직교성 인증 (style.py 단일 소유자 규칙)' },
    { title: 'Implement', detail: '직렬 기본; 인증+결정적 가드 통과 시만 worktree 병렬 → 스쿼시 회수' },
    { title: 'Review', detail: '결정적 게이트(test.ps1) + 적대적 diff 리뷰 + 드리프트 판정' },
  ],
}

// ── 실측 영역 지도 (2026-07-13 기준; tests/는 파일명 관례 매핑) ──────────────
const AREAS = {
  core:     { paths: ['src/hwpxcore/'] },
  fillcore: { paths: ['src/hwpxfiller/core/'] },
  data:     { paths: ['src/hwpxfiller/data/'] },
  gui:      { paths: ['src/hwpxfiller/gui/'] },
  cli:      { paths: ['src/hwpxfiller/cli.py', 'src/hwpxfiller/batch.py', 'src/hwpxfiller/naming.py'] },
  tests:    { paths: ['tests/', 'conftest.py'] },
  docs:     { paths: ['docs/', 'README.md'] },
  packaging:{ paths: ['packaging/', 'build.ps1', 'test.ps1', 'scripts/', 'pyproject.toml', 'uv.lock'] },
}
// 동결 영역: 작업 초점은 filler — diff 제품 변경은 무엇이든 즉시 알람.
const FROZEN = { diff: { paths: ['src/hwpxdiff/'] } }

// 직교성 규칙 — planner가 병렬 인증할 때 반드시 지킬 제약.
const ORTHOGONALITY_RULES = `
- src/hwpxfiller/gui/style.py 는 단일 소유자다. 이 파일을 건드리는 task는 절대 둘 이상 병렬 금지 — 직렬화하거나 한 task로 묶어라.
- fillcore(engine/schema/mapping) 변경은 gui/*_state.py 로 파문된다. 같은 기능이면 한 워커에 묶어라.
- src/hwpxcore/ 변경은 filler·diff 양쪽에 파문된다. core를 건드리면 병렬 인증 불가 — 단일 워커 직렬.
- 확신이 없으면 병렬로 인증하지 마라. 직렬이 기본값이다.`

const GATE_CMD = String.raw`.\test.ps1`  // ruff→pyright→pytest(757), basetemp·UTF-8·offscreen 이미 처리됨

// ── 스키마 = 계약 ────────────────────────────────────────────────────────────
const IMPACT = { type: 'object', required: ['areas', 'components', 'unknowns', 'risks'], properties: {
  areas: { type: 'array', items: { enum: Object.keys(AREAS) } },
  components: { type: 'array', items: { type: 'object', required: ['area', 'paths', 'reason'], properties: {
    area: { type: 'string' }, paths: { type: 'array', items: { type: 'string' } }, reason: { type: 'string' } } } },
  unknowns: { type: 'array', items: { type: 'string' } },
  risks: { type: 'array', items: { type: 'string' } },
} }

const PLAN = { type: 'object', required: ['areas', 'tasks', 'parallel_certified', 'certification_reason'], properties: {
  areas: { type: 'array', items: { enum: Object.keys(AREAS) } },
  tasks: { type: 'array', items: { type: 'object', required: ['id', 'areas', 'objective', 'acceptance', 'test_files'], properties: {
    id: { type: 'string' }, areas: { type: 'array', items: { type: 'string' } },
    objective: { type: 'string' },
    acceptance: { type: 'array', items: { type: 'string' } },
    test_files: { type: 'array', items: { type: 'string' } },   // 내부 루프용 pytest 대상
    depends_on: { type: 'array', items: { type: 'string' } } } } },
  parallel_certified: { type: 'boolean' },        // 직교성 인증 — false면 전부 직렬
  certification_reason: { type: 'string' },
} }

const IMPL = { type: 'object', required: ['task_id', 'done', 'summary', 'discovered_impacts'], properties: {
  task_id: { type: 'string' }, done: { type: 'boolean' }, summary: { type: 'string' },
  discovered_impacts: { type: 'array', items: { type: 'string' } },  // 안전밸브: 스코프 확장 금지, 보고만
  branch: { type: 'string' },                                        // worktree 워커만: 커밋한 브랜치명
} }
// worktree 병렬 워커용 — 브랜치 보고가 없으면 회수 불가이므로 필수로 승격
const IMPL_WT = { ...IMPL, required: [...IMPL.required, 'branch'] }

// 구현 전 사전 실측 — 드리프트 판정의 기준점
const PRE = { type: 'object', required: ['base', 'dirty'], properties: {
  base: { type: 'string' },                                   // git rev-parse HEAD (SHA 전체)
  dirty: { type: 'array', items: { type: 'string' } } } }     // 워크플로 이전부터 더티였던 파일

// 병렬 브랜치 회수 결과
const MERGE = { type: 'object', required: ['merged', 'conflicts'], properties: {
  merged: { type: 'array', items: { type: 'string' } },
  conflicts: { type: 'array', items: { type: 'object', required: ['branch', 'detail'], properties: {
    branch: { type: 'string' }, detail: { type: 'string' } } } } } }

const GATE = { type: 'object', required: ['passed', 'tail'], properties: {
  passed: { type: 'boolean' }, tail: { type: 'string' } } }

const REVIEW = { type: 'object', required: ['refuted', 'findings'], properties: {
  refuted: { type: 'boolean' },
  findings: { type: 'array', items: { type: 'object', required: ['severity', 'claim'], properties: {
    severity: { enum: ['blocker', 'warn'] }, claim: { type: 'string' }, file: { type: 'string' } } } },
} }

const CHANGED = { type: 'object', required: ['files'], properties: {
  files: { type: 'array', items: { type: 'string' } } } }

// 발견 임팩트(discovered_impacts) 정산 결과 — 보고만 되고 소비 안 되던 안전밸브를 닫는다.
const RECONCILE = { type: 'object', required: ['fixed', 'deferred'], properties: {
  fixed: { type: 'array', items: { type: 'string' } },       // 실제 수리한 임팩트 요약
  deferred: { type: 'array', items: { type: 'object', required: ['impact', 'reason', 'is_defect'], properties: {
    impact: { type: 'string' }, reason: { type: 'string' },
    is_defect: { type: 'boolean' } } } },                    // is_defect=true면 미해소 결함 → 알람
} }

// ── 공통: 변경 파일 → 영역 매핑 (결정적, 스크립트 내 순수 JS) ─────────────────
function mapAreas(files) {
  const hit = new Set(), frozenHit = [], unmapped = []
  for (const f of files) {
    const p = f.replace(/\\/g, '/')
    let found = false
    for (const [name, a] of Object.entries(FROZEN))
      if (a.paths.some(x => p.startsWith(x))) { frozenHit.push(f); found = true }
    for (const [name, a] of Object.entries(AREAS))
      if (a.paths.some(x => p.startsWith(x))) { hit.add(name); found = true }
    if (!found) unmapped.push(f)
  }
  return { areas: [...hit], frozenHit, unmapped }
}

// args 정규화 — 하네스가 Workflow args 를 JSON 문자열로 전달하는 경우가 있어(그러면
// 스크립트의 args.mode/args.request 접근이 undefined → 조용한 오류), 문자열이면 객체로
// 파싱한다. 이미 객체면 그대로. 이후 코드는 전부 정규화된 A 를 쓴다.
const A = (typeof args === 'string') ? JSON.parse(args) : (args || {})

// ═════════════════════════════ MODE: plan ═════════════════════════════
if (!A.mode || A.mode === 'plan') {
  if (!A.request) return { error: 'args.request(기능 요청 설명)가 필요하다.' }

  phase('Impact')
  const impact = await agent(
    `hwpx-filler 저장소의 변경 영향도 조사 담당이다. 코드를 절대 수정하지 마라(읽기 전용).
기능 요청: ${A.request}

영역 정의: ${JSON.stringify(AREAS)}
동결 영역(건드리면 안 됨): src/hwpxdiff/

조사할 것: 관련 기존 기능·유사 패턴, 수정 대상 모듈(실제 파일 경로 근거 필수),
gui의 view/*_state 쌍 구조, 링 계약(tests/test_architecture.py·test_ui_contract.py가 코드로 강제하는 규칙),
관련 테스트 파일, docs/ 관련 문서.
모르는 것·요청이 불명확한 것은 절대 추측으로 메우지 말고 unknowns 배열에 남겨라.`,
    { schema: IMPACT, effort: 'medium' })

  phase('Plan')
  const plan = await agent(
    `hwpx-filler 기능 계획 담당이다. 코드를 수정하지 마라.
기능 요청: ${A.request}
영향도 보고: ${JSON.stringify(impact)}

task로 분할하라. 각 task에 objective·acceptance(검증 가능한 완료 조건)·test_files(관련 pytest 파일)를 채워라.
영역(areas) 정직성: task.areas 는 objective 가 생성·수정할 **모든** 파일의 영역을 포함해야 한다
(예: objective 가 scripts/ 에 파일을 쓰면 areas 에 packaging 을, cli.py 를 만지면 cli 를 포함).
영역 정의: ${JSON.stringify(AREAS)}
임팩트 커버리지: 영향도 보고의 components 가 짚은 모든 영역·파일은 최소 한 task 의 areas·objective 가
담당해야 한다 — 어떤 파일도 담당 task 없이 방치하지 마라(방치는 곧 조용한 미수정으로 샌다).
직교성 인증: 아래 규칙을 적용해 task들이 병렬 실행 가능한지 판정하고 이유를 적어라.
${ORTHOGONALITY_RULES}
동결 영역(src/hwpxdiff/)을 필요로 하는 계획은 세우지 마라 — 필요하면 unknowns로 남겨야 했던 사안이다.`,
    { schema: PLAN, effort: 'high' })

  // 임팩트 커버리지 정산(결정적) — 영향도가 짚은 영역 중 어떤 task.areas 도 담당하지
  // 않는 것을 골라낸다. 담당 없는 영역은 곧 조용한 미수정으로 새므로 확정 전에 고지한다.
  const taskAreas = new Set((plan.tasks || []).flatMap(t => t.areas || []))
  const impactAreas = new Set((impact.components || []).map(c => c.area).filter(Boolean))
  const coverage_gaps = [...impactAreas].filter(a => !taskAreas.has(a))

  // 여기서 반환 → 메인 에이전트가 unknowns·coverage_gaps·계획을 사용자에게 확정받는다(게이트 A/B).
  return { mode: 'plan', impact, plan, coverage_gaps,
    next: coverage_gaps.length
      ? `⚠ 임팩트 영역 [${coverage_gaps.join(', ')}] 을 담당하는 task 가 없다 — 계획을 보강하거나 사용자와 확정한 뒤 implement 로 재호출하라.`
      : 'unknowns를 사용자와 확정한 뒤 Workflow({scriptPath, args:{mode:"implement", request, plan}})로 재호출' }
}

// ═════════════════════════════ MODE: implement ═════════════════════════════
if (A.mode === 'implement') {
  if (!A.plan || !Array.isArray(A.plan.tasks) || !A.plan.tasks.length)
    return { error: 'args.plan(확정된 계획)이 필요하다.' }
  const plan = A.plan
  // 계획 재검증 — 사용자 확정을 거쳐 왕복한 값이므로 형식을 다시 확인한다(늦은 TypeError 방지).
  const malformed = []
  if (!Array.isArray(plan.areas)) malformed.push('plan.areas 누락')
  for (const t of plan.tasks)
    if (!t.id || !Array.isArray(t.areas) || !Array.isArray(t.acceptance) || !Array.isArray(t.test_files))
      malformed.push(`task ${t.id || '(id 없음)'}: id/areas/acceptance/test_files 불량`)
  if (malformed.length) return { error: `계획 형식 불량: ${malformed.join(' · ')}` }

  const report = { tasks: [], merge: null, reconcile: null, gate: null, review: null, drift: null, status: 'unknown' }

  phase('Implement')
  // 사전 실측: 기준 SHA + 기존 더티 파일. 이후 모든 드리프트·리뷰는 base 기준으로 잰다
  // (병렬 경로는 회수 커밋이 생기므로 HEAD 기준 diff가 무의미해진다).
  const pre = await agent(
    `저장소 루트에서 실측만 하라(코드 수정 금지):
1. git rev-parse HEAD 결과 SHA 전체를 base 필드에.
2. git status --porcelain 에 잡히는 파일 경로만(상태 문자 제외) dirty 배열에.`,
    { schema: PRE, phase: 'Implement', label: 'preflight', effort: 'low' })
  if (!pre || !pre.base) return { error: '사전 실측(base SHA) 실패 — 중단' }
  const preDirty = new Set(pre.dirty || [])
  report.pre = pre

  // 직교성 인증의 결정적 가드 — 프롬프트 신뢰만으로 병렬을 열지 않는다.
  // task는 파일이 아니라 영역만 선언하므로, 같은 영역이 두 task에 걸치면 파일 단위
  // 직교성(style.py 단일 소유자 등)을 결정적으로 판별할 수 없다 → 직렬 강등.
  let serialReason = null
  if (plan.parallel_certified && plan.tasks.length > 1) {
    const seen = new Set(), dup = new Set()
    for (const t of plan.tasks) for (const a of t.areas) (seen.has(a) ? dup.add(a) : seen.add(a))
    if (plan.tasks.some(t => t.depends_on && t.depends_on.length)) serialReason = 'depends_on 있는 task 존재'
    else if (plan.tasks.some(t => t.areas.includes('core'))) serialReason = 'core 영역 포함(규칙: core는 직렬)'
    else if (dup.size) serialReason = `영역이 task 간 중복(${[...dup].join(', ')}) — 파일 단위 직교성 판별 불가`
    else if (preDirty.size) serialReason = '작업 트리가 이미 더티 — 회수 브랜치 생성 불가'
  }
  const usePar = plan.parallel_certified && plan.tasks.length > 1 && !serialReason
  if (serialReason) log(`병렬 인증 강등 → 직렬: ${serialReason}`)

  // 워커 실종(스킵·종단 오류)은 조용한 성공이 아니라 미완으로 계상한다.
  const missing = (id) => ({ task_id: id, done: false, summary: '워커 실종(스킵 또는 종단 오류)', discovered_impacts: [] })
  const taskPrompt = (task, wt) => `hwpx-filler 구현 담당${wt ? ' (격리 worktree)' : ''}. 아래 task만 구현하라 — 스코프 확장 절대 금지.
${JSON.stringify(task)}

규칙:
- task.areas 밖의 파일을 수정하지 마라. 필요해 보이면 discovered_impacts에 보고만 하라.
- src/hwpxdiff/ 는 동결 — 절대 건드리지 마라.
- 기존 코드의 관례(한국어 주석 톤, view/*_state 분리, style.py 셀렉터)를 따르라.
- 구현 후 관련 테스트만 빠르게 확인: .\\test.ps1 ${task.test_files.join(' ')} -x -q${wt ? '\n  (worktree에 .venv 없으면 먼저: uv sync --all-extras --group dev)' : ''}
- acceptance를 모두 충족했는지 스스로 점검하고 done을 정직하게 보고하라(실패면 done:false).${wt ? `
- 완료 후 모든 변경을 반드시 커밋하라(git add -A 후 git commit). 커밋 안 된 변경은 본 트리로 회수되지 못한다.
- git rev-parse --abbrev-ref HEAD 결과를 branch 필드에 정확히 보고하라.` : ''}`

  const mergeBranch = `wf/merge-${pre.base.slice(0, 7)}`
  if (usePar) {
    // 인증 + 결정적 가드 통과: worktree 병렬 → 통합 브랜치로 스쿼시 회수
    const results = await parallel(plan.tasks.map(t => () =>
      agent(taskPrompt(t, true), { schema: IMPL_WT, isolation: 'worktree', phase: 'Implement', label: `impl:${t.id}` })))
    report.tasks = results.map((r, i) => r || missing(plan.tasks[i].id))

    const branches = report.tasks.filter(t => t.done && t.branch).map(t => ({ id: t.task_id, branch: t.branch }))
    if (branches.length) {
      report.merge_branch = mergeBranch
      report.merge = await agent(
        `메인 저장소 루트(worktree 아님)에서 병렬 작업 브랜치를 회수하라. 기준 커밋: ${pre.base}
1. git checkout -B ${mergeBranch} ${pre.base}
2. 아래 각 브랜치를 순서대로: git merge --squash <branch> 후 git commit -m "wf: task <id>"
   충돌 시 git reset --merge 로 되돌리고(직전 스쿼시들은 이미 커밋돼 안전) conflicts에 {branch, detail} 기록, 다음 브랜치 계속.
3. merged에는 커밋까지 끝난 브랜치명, conflicts에는 실패를 보고하라. worktree·워커 브랜치는 삭제하지 마라.
대상: ${JSON.stringify(branches)}`,
        { schema: MERGE, phase: 'Implement', label: 'merge-back' })
    } else {
      report.merge = { merged: [], conflicts: [] }
    }
  } else {
    // 기본값: 메인 트리 직렬 (depends_on 순서 존중은 planner가 tasks 배열 순서로 보장)
    for (const t of plan.tasks) {
      const r = await agent(taskPrompt(t, false), { schema: IMPL, phase: 'Implement', label: `impl:${t.id}` })
      report.tasks.push(r || missing(t.id))
      if (!r || !r.done) { log(`task ${t.id} ${r ? '미완' : '실종'} — 직렬 체인 중단`); break }
    }
  }

  phase('Review')
  // (0) 발견 임팩트 정산 — 구현자들이 '스코프 밖'이라 보고만 한 discovered_impacts 를
  //     소비한다(보고만 되고 소비 안 되던 안전밸브를 닫는다). 테스트가 안 덮어 게이트도
  //     통과시킬 수 있는 잠재버그(예: 콜러의 잘못된 인자)를 계획 영역 안에서 수리하고,
  //     못 고칠 건 결함 여부로 분류해 최종 판정에 넘긴다. 게이트 루프 앞에 둬 재검증되게 한다.
  const allImpacts = report.tasks.flatMap(t => (t && t.discovered_impacts) || [])
  if (allImpacts.length) {
    report.reconcile = await agent(
      `발견 임팩트 정산 담당이다. 구현 중 각 task 가 '스코프 밖'이라 보고만 한 아래
discovered_impacts 를 처리하라(코드 수정 허용). 각 항목에 대해:
- 비동결 영역의 구체적 코드 결함이면(잘못된 인자·깨진 콜러·미개편 잔재 등) 근본 원인을 수리하라.
- 계획 task 영역: ${JSON.stringify(plan.tasks.map(t => ({ id: t.id, areas: t.areas })))}
- src/hwpxdiff/ 는 동결. 테스트를 약화(assert 삭제·skip)하지 마라.
- 수리한 항목은 fixed 에 요약. 안 고친 항목은 deferred 에 {impact, reason, is_defect} 로 —
  is_defect 는 '지금 방치하면 잘못 동작하는 실제 결함인가'(단순 후속 제안·문서 메모·마이그레이션 안내는 false).
discovered_impacts:
${JSON.stringify(allImpacts)}${usePar ? `
수리 후 반드시 커밋하라(git add -A && git commit -m "wf: reconcile impacts") — 회수 브랜치(${mergeBranch})에 커밋 안 된 수리는 빠진다.` : ''}`,
      { schema: RECONCILE, phase: 'Review', label: 'reconcile' })
  }

  // (1) 결정적 게이트 — 전체 test.ps1 (링 계약 테스트 포함). 최대 2회 재작업.
  let gate = null
  for (let attempt = 1; attempt <= 3; attempt++) {
    gate = await agent(
      `저장소 루트에서 ${GATE_CMD} 를 실행하고 결과를 보고하라. 코드를 수정하지 마라.
passed는 최종 exit code 0 여부, tail은 실패 시 마지막 출력 ~2000자.`,
      { schema: GATE, phase: 'Review', label: `gate#${attempt}`, effort: 'low' })
    if (gate && gate.passed) break
    if (attempt === 3) break
    log(`게이트 실패(${attempt}/2 재작업) — 수리 시도`)
    await agent(
      `게이트(${GATE_CMD}) 실패를 수리하라. 실패 출력:\n${gate ? gate.tail : '(없음)'}\n
계획된 task 스코프 안에서만 고쳐라. 계획: ${JSON.stringify(plan.tasks.map(t => ({ id: t.id, areas: t.areas })))}
src/hwpxdiff/ 동결. 근본 원인만 고치고 테스트를 약화시키지 마라(assert 삭제·skip 금지).${usePar ? `
수정 후 반드시 커밋하라(git add -A 후 git commit -m "wf: gate repair") — 현재 회수 브랜치(${mergeBranch})에 커밋 안 된 수리는 머지에서 빠진다.` : ''}`,
      { schema: IMPL, phase: 'Review', label: `repair#${attempt}` })
  }
  report.gate = gate

  // (2) 변경 파일 실측(기준: base SHA) → 결정적 드리프트 판정 (순수 JS)
  const changed = await agent(
    `저장소 루트에서 git status --porcelain 과 git diff --name-only ${pre.base} 를 실행해
기준 커밋 ${pre.base} 이후 변경·추가된 파일 경로 전체(중복 제거, 리네임은 새 경로)를 files 배열로 정확히 보고하라. 코드 수정 금지.`,
    { schema: CHANGED, phase: 'Review', label: 'diff-scan', effort: 'low' })
  // 워크플로 이전부터 더티였던 파일은 드리프트 판정에서 제외(pre_dirty로 보고는 남긴다).
  // porcelain은 미추적 디렉터리를 '.claude/'처럼 디렉터리 단위로 보고하므로 prefix 매칭이 필요하다.
  const preDirtyNorm = [...preDirty].map(d => d.replace(/\\/g, '/'))
  const isPreDirty = (f) => {
    const p = f.replace(/\\/g, '/')
    return preDirtyNorm.some(d => p === d || (d.endsWith('/') && p.startsWith(d)))
  }
  const changedFiles = changed ? changed.files.filter(f => !isPreDirty(f)) : []
  const drift = mapAreas(changedFiles)
  // 판정 기준은 plan.areas 단독이 아니라 task 영역과의 합집합 — planner의 누락이 오탐 blocker가 되지 않게.
  const plannedAreas = new Set([...plan.areas, ...plan.tasks.flatMap(t => t.areas)])
  const unexpected = drift.areas.filter(a => !plannedAreas.has(a))
  report.drift = { ...drift, unexpected, pre_dirty: [...preDirty] }

  // (3) 적대적 리뷰 — 구현자가 아닌 별도 스켑틱이 diff를 반증 시도
  report.review = await agent(
    `적대적 리뷰어다. 너는 구현자가 아니다 — 아래 주장을 반증하는 것이 임무다.
주장: "이 diff는 다음 계획을 정확히, 계획된 범위 안에서만 구현했다."
계획: ${JSON.stringify(plan)}
변경 파일: ${JSON.stringify(changedFiles)}

git diff ${pre.base} 로 실제 변경을 읽고 검사하라:
- acceptance 미충족 항목이 있는가?
- 계획에 없는 동작 변경이 숨어 있는가?
- 테스트가 약화되었는가(assert 완화·skip·삭제)?
- 조용한 추측으로 메워진 결정이 있는가(불확실한데 확인 없이 확정한 코드)?
blocker = 머지 불가 사유, warn = 사용자 판단 사항. 반증 실패면 refuted:false.`,
    { schema: REVIEW, phase: 'Review', label: 'adversary', effort: 'high' })

  // ── 최종 판정 (결정적) — 실측 실패·에이전트 실종은 통과가 아니라 알람이다 ──
  const blockers = []
  if (!report.gate || !report.gate.passed) blockers.push('결정적 게이트(test.ps1) 실패')
  if (!changed) blockers.push('변경 파일 실측 실패 — 드리프트 판정 불능')
  if (report.drift.frozenHit.length) blockers.push(`동결 영역(src/hwpxdiff/) 변경: ${report.drift.frozenHit.join(', ')}`)
  if (unexpected.length) blockers.push(`계획 밖 영역 변경: ${unexpected.join(', ')}`)
  if (report.drift.unmapped.length) blockers.push(`영역 지도 밖 파일 변경: ${report.drift.unmapped.join(', ')}`)
  if (!report.review) blockers.push('적대적 리뷰 결과 없음')
  else if (report.review.findings.some(f => f.severity === 'blocker')) blockers.push('적대적 리뷰 blocker')
  // 완결성은 보고 목록이 아니라 계획 기준으로 — 실종·미실행 task도 잡힌다.
  const doneIds = new Set(report.tasks.filter(t => t && t.done).map(t => t.task_id))
  const notDone = plan.tasks.map(t => t.id).filter(id => !doneIds.has(id))
  if (notDone.length) blockers.push(`미완·미실행 task: ${notDone.join(', ')}`)
  // 정산에서 결함으로 분류됐으나 못 고친 임팩트는 조용한 누수가 아니라 blocker다.
  if (report.reconcile) {
    const undoneDefects = report.reconcile.deferred.filter(d => d.is_defect)
    if (undoneDefects.length)
      blockers.push(`미해소 결함(discovered_impacts): ${undoneDefects.map(d => d.impact).join(' · ').slice(0, 300)}`)
  }
  if (usePar) {
    if (!report.merge) blockers.push('병렬 회수 결과 없음')
    else {
      if (report.merge.conflicts.length) blockers.push(`회수 병합 충돌: ${report.merge.conflicts.map(c => c.branch).join(', ')}`)
      const lost = report.tasks.filter(t => t.done && t.branch && !report.merge.merged.includes(t.branch)
        && !report.merge.conflicts.some(c => c.branch === t.branch)).map(t => t.task_id)
      if (lost.length) blockers.push(`회수 누락 task: ${lost.join(', ')}`)
    }
  }

  report.status = blockers.length ? 'blocked' : 'ready_to_merge'
  report.blockers = blockers
  // 머지는 여기서 절대 하지 않는다 — 사용자 확정(게이트 C)이 마지막 관문이다.
  // P5: 판정 요약을 반환 객체 맨 앞에 얹는다 — 하네스가 tasks 를 먼저 펼쳐 blocked 를
  // 놓치는 일이 없게(status·blockers·게이트·정산을 한눈에).
  const headline = `${report.status.toUpperCase()} — gate ${report.gate && report.gate.passed ? 'PASS' : 'FAIL'}`
    + (blockers.length ? ` · blockers(${blockers.length}): ${blockers.join(' | ')}` : '')
    + (report.reconcile ? ` · reconcile fixed ${report.reconcile.fixed.length}, deferred ${report.reconcile.deferred.length}` : '')
  return { headline, status: report.status, blockers, gate_passed: !!(report.gate && report.gate.passed), ...report }
}

return { error: `알 수 없는 mode: ${A.mode}` }
