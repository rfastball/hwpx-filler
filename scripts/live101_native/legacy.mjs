// The shipped Quickstart 101 path, exercised through the actual Tauri WebView.
// Keep the same thirteen shutters for check and capture. A shutter is recorded
// only after its visible state and the preceding native operation have landed.
export const CAPTURE_POINTS = Object.freeze([
  'job-landing', 'library-empty', 'template-pick', 'mapping-confirm',
  'save-job', 'library-detail', 'session-panel', 'range-editor',
  'preflight-check', 'generated', 'workbench-review', 'workbench-copied',
  'workbench-empty-value',
]);

async function allSelected(s, label) {
  await s.value(`(()=>{const b=document.getElementById('jobSelAll');
    if(b && !b.checked && !b.disabled)b.click();return true})()`);
  await s.wait(`(()=>{const c=document.getElementById('jobSelCount');
    if(!c)return false;const m=/선택\\s+(\\d+)/.exec(c.textContent||'');
    return !!m && Number(m[1])>0})()`, `${label}: selection landed`,
    { timeoutMs: 30000, requires: ['#jobSelCount'] });
}

async function chooseTemplateAndData(s, ctx, selector, label, onPaired = null,
  incomplete = false) {
  await s.click('#libraryNewWork', `${label}: new work`);
  await s.wait(`document.querySelector('#scr-editor.on') &&
    document.querySelector(${JSON.stringify(selector)})`, `${label}: template picker`,
    { requires: ['#scr-editor', '#editorPairZone'] });
  await s.click(selector, `${label}: choose template`);
  await s.wait(`!!document.querySelector('#editorTplGate') &&
    /필드 [1-9]/.test(document.querySelector('#editorTplGate').textContent)`,
    `${label}: field schema`, { requires: ['#editorTplGate'] });
  await ctx.page.queueDialog('file', ctx.csvPath);
  await s.click('#editorPoolBrowse', `${label}: choose CSV`);
  await s.wait(`document.querySelector('#scr-editor .wfoot [data-act="next"]')?.disabled === false`,
    `${label}: data paired`, { requires: ['#editorDataList'] });
  if (onPaired) await onPaired();
  await s.clickText('#scr-editor', '다음 ▶');
  await s.wait(`!!document.querySelector('#scr-editor [data-act="confirm-suggested"]')`,
    `${label}: mapping`, { requires: ['#scr-editor'] });
  if (!await s.value(`document.querySelector('#scr-editor [data-act="confirm-suggested"]').disabled`)) {
    await s.click('#scr-editor [data-act="confirm-suggested"]', `${label}: confirm suggestions`);
  }
  await s.wait(`document.querySelector('#scr-editor').textContent.includes(${JSON.stringify(incomplete ? '자동 제안 0' : '확인 필요 0')}) &&
    [...document.querySelectorAll('#scr-editor [data-act="row-confirm"]')]
      .every(b=>b.disabled || b.getAttribute('aria-pressed')==='true')`,
    `${label}: suggestions landed`, { requires: ['#scr-editor'] });
}

export async function runLegacy(surface, ctx) {
  const s = surface;
  const seen = {};
  const shot = name => s.shoot(name);
  await s.wait(`!!document.querySelector('#jobPickInLibrary')`, 'empty landing',
    { requires: ['#jobPickInLibrary'] });
  await s.wait(`getComputedStyle(document.getElementById('jobNoDataExit')).display !== 'none'`,
    'data exit visible', { requires: ['#jobNoDataExit'] });
  await shot('job-landing');

  await s.click('#jobPickInLibrary', 'library exit');
  await s.wait(`!!document.querySelector('#scr-library.on')`, 'library screen',
    { requires: ['#scr-library'] });
  await shot('library-empty');
  await chooseTemplateAndData(s, ctx,
    '#editorTplList .pitem[data-path*="발주요청서"]', 'HWPX', async () => {
      await s.wait(`document.querySelector('#editorLinkCard').textContent.includes('⟷') &&
        !!document.querySelector('#editorDataList .pitem[data-key="session"]')`,
        'HWPX visible data pair', { requires: ['#editorLinkCard', '#editorDataList'] });
      await s.scrollTo('#editorPairZone');
      await shot('template-pick');
    });
  await s.wait(`document.querySelector('#scr-editor').textContent.includes('해양수산부') &&
    [...document.querySelectorAll('#scr-editor [data-act="row-confirm"]')]
      .every(b=>b.getAttribute('aria-pressed')==='true')`,
    'HWPX all rows confirmed', { requires: ['#scr-editor'] });
  await s.value(`document.querySelector('#scr-editor .wbody').scrollTop=0`);
  await shot('mapping-confirm');

  await s.clickText('#scr-editor', '다음 ▶');
  await s.wait(`!!document.getElementById('editorName') &&
    !!document.querySelector('#scr-editor input[data-act="pattern"]')`,
    'HWPX name and save', { requires: ['#editorName'] });
  await s.wait(`document.getElementById('editorName').value.length>0 &&
    !!document.getElementById('editorNameHint')`, 'derived name and hint');
  await s.setValue('#editorName', '발주요청서');
  await s.setValue('#scr-editor input[data-act="pattern"]',
    '발주요청서-{{공고번호}}-{{seq:001}}');
  await s.wait(`document.getElementById('editorPatternPreview').textContent
    .includes('발주요청서-2026-001-001.hwpx · 002 · 003')`, 'sequence example present');
  seen.seq_example_positive = await s.value(
    `document.getElementById('editorPatternPreview').textContent.trim()`);
  await s.setValue('#scr-editor input[data-act="pattern"]', '발주요청서-{{공고번호}}');
  await s.wait(`document.getElementById('editorPatternPreview').textContent
    .includes('발주요청서-2026-001') &&
    !document.getElementById('editorPatternPreview').textContent.includes('· 002')`,
  'sequence example absent');
  seen.seq_example_negative = await s.value(
    `document.getElementById('editorPatternPreview').textContent.trim()`);
  await s.wait(`document.getElementById('editorOutDir').value.length>0 &&
    !!document.getElementById('editorOpenFolderSettings')`, 'output folder restated');
  await shot('save-job');
  await s.clickText('#scr-editor', '작업 저장');
  await s.wait(`document.querySelector('#scr-editor').textContent.includes('저장했습니다')`,
    'HWPX work saved', { timeoutMs: 30000 });
  await s.wait(`document.getElementById('editorSaveState').textContent.includes('저장됨')`,
    'HWPX saved state');
  seen.hwpx_job_saved = true;
  await s.click('#editorBack', 'leave Editor');
  await s.wait(`!!document.querySelector('#scr-job.on')`, 'return to Job');

  await s.click('.navbtn[data-scr="library"]', 'library');
  await s.wait(`!!document.querySelector('#libraryList [data-work="발주요청서"]')`,
    'saved HWPX row');
  await s.click('#libraryList [data-work="발주요청서"]');
  await s.wait(`!!document.querySelector('#libraryDetail [data-use]')`, 'work detail');
  await s.wait(`!!document.querySelector('#libraryPairRows:not([data-first-row="pending"])')`,
    'detail first row');
  await shot('library-detail');
  await s.click('#libraryDetail [data-use="발주요청서"]', 'use HWPX work');
  await s.wait(`!!document.querySelector('#scr-job.on') &&
    document.getElementById('jobDataLabel')?.textContent.trim()==='발주목록.csv' &&
    document.getElementById('jobActionName')?.textContent.trim()==='발주요청서'`,
    'durable work and data paired', { timeoutMs: 25000 });
  seen.bound_work_arrives_with_its_data = await s.value(
    `document.getElementById('jobDataLabel').textContent.trim()`);
  await s.wait(`document.querySelector('#jobCandidates button[data-cand="발주요청서"]')
    ?.getAttribute('aria-pressed')==='true'`, 'HWPX work selected');
  seen.work_candidate_actionable = '발주요청서';
  seen.explicit_work_selected = '발주요청서';
  await allSelected(s, 'HWPX all rows');
  await s.wait(`!document.getElementById('jobManagedCreate').disabled &&
    document.getElementById('jobGenBtn').hidden &&
    !document.getElementById('jobPreflight').textContent.includes('첫 실행')`,
    'first run is open and quiet', { timeoutMs: 30000 });
  seen.first_run_not_announced = true;
  if (await s.value(`!!document.getElementById('jobMirrorPreviewOpen') ||
      !!document.getElementById('jobReviewFlag')`)) {
    throw new Error('retired preview or approval action is visible');
  }
  seen.preview_surface_retired = true;
  await shot('session-panel');

  await s.click('#jobDataExpand', 'open range editor');
  await s.wait(`!document.getElementById('dataSheet').classList.contains('hidden') &&
    document.getElementById('dataSheetSlot').contains(document.getElementById('jobRangeFoot'))`,
    'range editor and footer');
  await s.click('#jobOrderToggle', 'reverse display order');
  await s.wait(`document.querySelector('#jobTableBody tr')?.dataset.i==='0'`,
    'display order changed');
  await shot('range-editor');
  await s.click('#jobTableBody tr[data-i="0"] input[type="checkbox"]', 'toggle row off');
  await s.wait(`document.getElementById('jobRangeApply').textContent.includes('2건') &&
    document.getElementById('jobOrderToggle').getAttribute('aria-pressed')==='true'`,
    'range draft keeps order');
  await s.click('#jobTableBody tr[data-i="0"] input[type="checkbox"]', 'toggle row on');
  await s.wait(`document.getElementById('jobRangeApply').textContent.includes('3건')`,
    'range draft restored');
  await s.click('#jobRangeCancel', 'cancel range draft');
  await s.wait(`!!window.__cap.btn(null,'버리고 닫기')`, 'discard guard');
  await s.clickText(null, '버리고 닫기');
  await s.wait(`document.getElementById('dataSheet').classList.contains('hidden') &&
    document.getElementById('jobOrderToggle').getAttribute('aria-pressed')==='false' &&
    !document.getElementById('jobManagedCreate').disabled`,
    'main range preserved', { timeoutMs: 30000 });
  await s.wait(`!document.getElementById('jobMirrorLine') &&
    !document.getElementById('jobMirrorSummary') &&
    !document.getElementById('jobRestate') && !document.getElementById('jobMirror')`,
    'retired summary surfaces absent');
  await s.wait(`!!document.querySelector('#jobPreflight .preflight')`, 'preflight');
  await s.scrollTo('#jobPreflight .preflight');
  await shot('preflight-check');

  await s.click('#jobManagedCreate', 'create HWPX documents');
  await s.wait(`document.getElementById('jobResult')?.dataset.state==='completed'`,
    'generation completed', { timeoutMs: 60000, requires: ['#jobResult'] });
  seen.hwpx_result_state = await s.value(`document.getElementById('jobResult').dataset.state`);
  await s.scrollTo('#jobResult');
  await shot('generated');

  await s.click('.navbtn[data-scr="library"]', 'library for TXT');
  await s.wait(`!!document.querySelector('#scr-library.on')`, 'library for TXT');
  await chooseTemplateAndData(s, ctx,
    '#editorTplList .pitem[data-path*="발주요청_기안"]', 'TXT');
  await s.wait(`document.querySelectorAll('#editor-steps .wstep-tab').length===3 &&
    document.querySelector('#scr-editor').textContent.includes('확인 필요 0') &&
    [...document.querySelectorAll('#scr-editor [data-act="row-confirm"]')]
      .every(b=>b.getAttribute('aria-pressed')==='true')`, 'TXT three steps and mappings');
  await s.clickText('#scr-editor', '다음 ▶');
  await s.wait(`!!document.getElementById('editorName') &&
    !document.querySelector('#scr-editor input[data-act="pattern"]')`, 'TXT name step');
  await s.setValue('#editorName', '발주요청 기안');
  await s.clickText('#scr-editor', '작업 저장');
  await s.wait(`document.querySelector('#scr-editor').textContent.includes('저장했습니다')`,
    'TXT saved', { timeoutMs: 30000 });
  await s.click('#editorBack', 'leave TXT Editor');
  await s.wait(`!!document.querySelector('#scr-job.on')`, 'TXT Editor exit');

  await s.click('.navbtn[data-scr="library"]', 'library for TXT workbench');
  await s.wait(`!!document.querySelector('#libraryList [data-work="발주요청 기안"]')`,
    'TXT library row');
  await s.click('#libraryList [data-work="발주요청 기안"]');
  await s.wait(`!!document.querySelector('#libraryDetail [data-use="발주요청 기안"]')`,
    'TXT detail');
  await s.click('#libraryDetail [data-use="발주요청 기안"]', 'use TXT work');
  await s.wait(`document.getElementById('jobActionName')?.textContent.trim()==='발주요청 기안' &&
    !document.getElementById('jobSelAll').disabled`, 'TXT work and data survived',
    { timeoutMs: 25000 });
  seen.data_survived_job_switch = true;
  await allSelected(s, 'TXT all rows');
  await s.wait(`document.getElementById('jobGenBtn').textContent.includes('검토·복사 시작') &&
    !document.getElementById('jobGenBtn').disabled`, 'TXT workbench entry');
  await s.click('#jobGenBtn', 'open workbench');
  await s.wait(`!!document.querySelector('#scr-workbench.on') &&
    document.getElementById('wbCard')?.textContent.includes('[발주 요청]') &&
    document.getElementById('wbCard')?.textContent.includes('구매')`,
    'TXT filled card');
  await shot('workbench-review');
  await s.click('#wbCopy', 'copy TXT');
  await s.wait(`document.getElementById('wbCopied')?.textContent.trim().startsWith('1 /')`,
    'TXT copy counter');
  seen.txt_copied = await s.value(`document.getElementById('wbCopied').textContent.trim()`);
  await shot('workbench-copied');
  await s.click('#wbBack', 'leave workbench');
  await s.wait(`!!document.querySelector('#scr-job.on') || !!window.__cap.btn(null,'나가기')`,
    'workbench exit guard');
  await s.value(`window.__cap.clickBtn(null,'나가기');true`);
  await s.wait(`!!document.querySelector('#scr-job.on')`, 'workbench exit');

  await s.click('.navbtn[data-scr="library"]', 'library for empty value');
  await s.wait(`!!document.querySelector('#scr-library.on')`, 'library for empty value');
  await chooseTemplateAndData(s, ctx,
    '#editorTplList .pitem[data-path*="오류연습_미치환"]', 'empty value', null, true);
  await s.wait(`document.querySelector('#scr-editor').textContent.includes('자동 제안 0') &&
    [...document.querySelectorAll('#scr-editor [data-act="row-confirm"]')]
      .every(b=>b.disabled || b.getAttribute('aria-pressed')==='true')`,
    'empty-value suggestions landed');
  const emptyRow = '#scr-editor table.map tr[data-field="담당연락처"]';
  await s.wait(`document.querySelector(${JSON.stringify(emptyRow)})
    ?.querySelector('[data-act="row-confirm"]')?.disabled===true`,
    'empty row requires explicit value');
  seen.empty_value_gate_asked = true;
  await s.setValue(`${emptyRow} select[data-act="row-source"]`, 'sp:const');
  await s.wait(`document.querySelector(${JSON.stringify(emptyRow)})
    ?.querySelector('[data-act="row-confirm"]')?.disabled===false`,
    'empty constant declared');
  await s.click(`${emptyRow} [data-act="row-confirm"]`, 'confirm empty constant');
  await s.wait(`document.querySelector('#scr-editor').textContent.includes('확인 필요 0') &&
    [...document.querySelectorAll('#scr-editor [data-act="row-confirm"]')]
      .every(b=>b.getAttribute('aria-pressed')==='true')`,
    'empty-value mappings confirmed');
  await s.clickText('#scr-editor', '다음 ▶');
  await s.wait(`!!document.getElementById('editorName')`, 'empty-value name step');
  await s.setValue('#editorName', '오류연습');
  await s.clickText('#scr-editor', '저장하고 문서 만들기로');
  await s.wait(`!!document.querySelector('#scr-job.on') &&
    document.getElementById('jobActionName')?.textContent.trim()==='오류연습'`,
    'save and open empty-value work', { timeoutMs: 30000 });
  seen.save_and_open_seated = true;
  await s.click('.navbtn[data-scr="library"]', 'library for saved empty-value work');
  await s.wait(`!!document.querySelector('#libraryList [data-work="오류연습"]')`,
    'saved empty-value work');
  await s.click('#libraryList [data-work="오류연습"]');
  await s.wait(`!!document.querySelector('#libraryDetail [data-use="오류연습"]')`,
    'saved empty-value work detail');
  await s.click('#libraryDetail [data-use="오류연습"]', 'use saved empty-value work');
  await s.wait(`document.getElementById('jobActionName')?.textContent.trim()==='오류연습' &&
    !document.getElementById('jobSelAll').disabled`, 'empty-value work loaded',
    { timeoutMs: 25000 });
  await allSelected(s, 'empty-value rows');
  await s.wait(`!document.getElementById('jobGenBtn').disabled`, 'empty-value workbench ready');
  await s.click('#jobGenBtn', 'review empty-value work');
  await s.wait(`!!document.querySelector('#scr-workbench.on') &&
    !!document.querySelector('#wbCard .seg-declared[data-token="담당연락처"]')`,
    'empty value visible');
  seen.empty_value_surfaced = true;
  await shot('workbench-empty-value');
  if (s.shots.join('|') !== CAPTURE_POINTS.join('|')) {
    throw new Error(`shutter order differs: ${JSON.stringify(s.shots)}`);
  }
  return seen;
}
