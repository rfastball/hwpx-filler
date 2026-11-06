// SX-05 follows the thirteen-shutter journey in the same native window.
// Every assertion observes either the actual page or the product API used by it.
import path from 'node:path';
import { Staging, verifyFixtures } from './fixtures.mjs';

const requireValue = (condition, reason) => { if (!condition) throw new Error(reason); };
const view = snapshot => {
  const current = snapshot.slot_configuration?.current_view;
  requireValue(current && typeof current === 'object', 'SX-05 current Slot view is absent');
  return current;
};
const bench = (snapshot, where) => {
  const value = snapshot.workbench_observation;
  requireValue(value?.supported === true,
    `SX-05 workbench observation absent at ${where}: ${JSON.stringify(snapshot)}`);
  return value;
};
const snapshot = s => s.snapshot('job');

async function selectWork(s, name) {
  const selector = `#jobCandidates button[data-cand=${JSON.stringify(name)}]`;
  await s.wait(`!!document.querySelector(${JSON.stringify(selector)}) &&
    !document.querySelector(${JSON.stringify(selector)}).disabled`, `${name} candidate`,
  { requires: ['#jobCandidates'] });
  await s.click(selector, `${name} explicit selection`);
  await s.wait(`document.getElementById('jobActionName').textContent.trim() === ${JSON.stringify(name)}`,
    `${name} active Work`, { requires: ['#jobActionName'] });
}

async function pickOption(s, selector) {
  const opened = await s.value(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});
    if(!e)return false;const d=e.closest('details');if(d&&!d.open)d.open=true;return true})()`);
  requireValue(opened, `SX-05 Option is absent: ${selector}`);
  await s.click(selector, `choose ${selector}`);
}

async function selectAll(s, label) {
  await s.value(`(()=>{const b=document.getElementById('jobSelAll');
    if(b&&!b.checked&&!b.disabled)b.click();return true})()`);
  await s.wait(`(()=>{const c=document.getElementById('jobSelCount');
    const m=/선택\\s+(\\d+)/.exec(c?.textContent||'');return !!m&&Number(m[1])>0})()`,
    label, { timeoutMs: 30000, requires: ['#jobSelCount'] });
}

async function applyStagedTemplate(s, staging, kind, confirm) {
  await staging.template(kind);
  await s.click('.navbtn[data-scr="library"]', `${kind} library`);
  await s.wait(`!!document.querySelector('#libraryList [data-work="발주요청서"]')`,
    `${kind} Work row`, { timeoutMs: 30000, requires: ['#libraryList'] });
  await s.click('#libraryList [data-work="발주요청서"]', `${kind} detail`);
  await s.wait(`!!document.querySelector('#libraryDetail [data-use="발주요청서"]') &&
    !!document.getElementById('libraryTemplateEdit')`, `${kind} editable asset`,
  { timeoutMs: 30000, requires: ['#libraryDetail'] });
  await s.click('#libraryTemplateEdit', `${kind} authoring`);
  await s.wait(`!!document.getElementById('authoring-dock-tab-impact')`,
    `${kind} impact tab`, { timeoutMs: 30000, requires: ['#scr-authoring'] });
  await s.click('#authoring-dock-tab-impact', `${kind} impact`);
  await s.wait(`!!document.querySelector('[data-guide="apply-check"]')`, `${kind} check impact`);
  await s.click('[data-guide="apply-check"]', `${kind} check`);
  await s.wait(`!!document.querySelector('[data-guide="apply-confirm"]:not(:disabled)')`,
    `${kind} prepared`, { timeoutMs: 30000 });
  if (confirm) {
    await s.click('[data-guide="apply-confirm"]', `${kind} apply`);
    await s.wait(`!document.querySelector('[data-guide="apply-confirm"]')`,
      `${kind} applied`, { timeoutMs: 30000 });
  }
  await s.click('#scr-authoring .authoring-tab [aria-label$="닫기"]', `${kind} close tab`);
  await s.wait(`!document.querySelector('#scr-authoring .authoring-tab')`,
    `${kind} tab closed`, { requires: ['#scr-authoring'] });
  await s.click('#scr-authoring [aria-label="돌아가기"]', `${kind} leave authoring`);
  await s.wait(`!!document.querySelector('#scr-library.on')`, `${kind} library return`);
  await s.click('.navbtn[data-scr="job"]', `${kind} job return`);
  await s.wait(`!!document.querySelector('#scr-job.on')`, `${kind} job return`);
  if (!await s.value(`document.getElementById('jobActionName').textContent.trim()==='발주요청서'`)) {
    await selectWork(s, '발주요청서');
  }
}

async function setFolder(s, folder, picker, field, sourceLabel = null) {
  await s.click('#settingsOpen', `settings for ${field}`);
  await s.wait(`!document.getElementById('settingsModal').classList.contains('hidden')`,
    `settings opened for ${field}`, { requires: ['#settingsModal'] });
  await s.page.queueDialog('folder', folder);
  await s.click(picker, `choose ${field}`);
  await s.wait(`document.querySelector(${JSON.stringify(field)})?.value===${JSON.stringify(folder)}`,
    `${field} persisted`, { requires: [field] });
  if (sourceLabel) await s.wait(`document.getElementById('settingsTplDirSource')?.textContent===${JSON.stringify(sourceLabel)}`,
    `${field} origin`, { requires: ['#settingsTplDirSource'] });
  await s.click('#settingsClose', `close settings for ${field}`);
  await s.wait(`document.getElementById('settingsModal').classList.contains('hidden')`,
    `settings closed for ${field}`);
}

async function mountData(s, source, failure = false) {
  await s.page.queueDialog('file', source);
  await s.click('#jobBtnPickData', 'choose data');
  await s.wait(`!document.getElementById('dataPickerModal').classList.contains('hidden')`,
    'data picker opened', { requires: ['#dataPickerModal', '#dataPickerBrowse'] });
  await s.click('#dataPickerBrowse', 'browse data');
  if (failure) {
    await s.wait(`document.getElementById('dataPickerNote').textContent.trim().startsWith('⚠')`,
      'failed data transition notice', { timeoutMs: 25000 });
  } else {
    await s.wait(`!document.getElementById('dataPickerModal').classList.contains('hidden') &&
      document.getElementById('dataPickerNote').textContent.includes('불러왔습니다') &&
      !!document.querySelector('#dataPickerPinned .pitem[data-key="session"] .nm') &&
      getComputedStyle(document.getElementById('dataPickerPin')).display !== 'none'`,
    'data transition landed', { timeoutMs: 25000 });
  }
  await s.click('#dataPickerClose', 'close data picker');
  await s.wait(`document.getElementById('dataPickerModal').classList.contains('hidden')`,
    'data picker closed', { requires: ['#dataPickerModal'] });
}

async function presetRoundtrip(s) {
  const token = view(await snapshot(s)).new_configuration_token;
  const saved = await s.dispatch('job', 'save_selection_preset',
    { configuration_token: token, name: 'sx-preset' });
  requireValue(saved?.status === 'SAVED' && saved.saved_key,
    `S9: preset was not saved: ${JSON.stringify(saved)}`);
  requireValue((await snapshot(s)).content_presets?.items?.some(item => item.name === 'sx-preset'),
    'S9: saved preset absent from snapshot');
  requireValue(await s.value(`(()=>{const z=document.getElementById('jobContentSelectionZone');
    const list=z?.querySelector('.cs-presets');const slot=z?.querySelector('.cs-slot');
    return !!(list&&slot&&(list.compareDocumentPosition(slot)&Node.DOCUMENT_POSITION_FOLLOWING))})()`),
  'S9: preset list does not precede Slots');
  await s.wait(`[...document.querySelectorAll('#jobContentSelectionZone .cs-preset-name')]
    .some(e=>e.offsetParent!==null&&e.textContent.trim()==='sx-preset')`,
  'S9: preset visibly listed');
  await pickOption(s, '#cs-opt-0-1');
  await s.wait(`document.getElementById('cs-opt-0-1').checked`, 'different selection landed');
  await s.gateDispatch('apply_selection_preset', 'after');
  await s.click('#jobContentSelectionZone .cs-preset-apply', 'apply saved preset');
  await s.waitDispatchGate('preset response held');
  await s.releaseDispatch();
  await s.wait(`document.getElementById('cs-opt-0-0').checked &&
    !document.getElementById('cs-opt-0-1').checked &&
    !!document.querySelector('#jobContentSelectionZone .cs-preset-notice-applied')`,
  'S9: saved selection restored', { timeoutMs: 30000 });
  const notice = await s.value(`document.querySelector('#jobContentSelectionZone .cs-preset-notice').textContent`);
  requireValue(notice.includes('적용했습니다'), 'S9: applied result is not restated');
  const trace = await s.takeDispatchTrace();
  requireValue(trace.some(item => item.action === 'apply_selection_preset'),
    'S9: preset command trace absent');
  return { saved_key: saved.saved_key, notice, trace };
}

async function successorAndBinding(s, staging) {
  await applyStagedTemplate(s, staging, 'successor', false);
  await s.wait(`!!document.getElementById('jobTplApply')`,
    'successor is ready to apply', { timeoutMs: 30000 });
  await s.gateDispatch('select_slot_option', 'before');
  await pickOption(s, '#cs-opt-1-1');
  await s.waitDispatchGate('old-token command held');
  await s.wait(`document.querySelector('.content-selection')?.getAttribute('aria-busy')==='true'`,
    'content command pending');
  await s.click('#jobTplApply', 'apply successor');
  await s.wait(`document.getElementById('jobTplNotice')?.textContent.includes('적용')`,
    'successor applied', { timeoutMs: 30000 });
  await s.releaseDispatch();
  await s.wait(`!!document.querySelector('.cs-status-stale') &&
    document.querySelectorAll('#jobContentSelectionZone .cs-slot').length===2 &&
    !!document.querySelector('#jobContentSelectionZone .cs-retained-note[data-fate="RESOLVED"]') &&
    !!document.querySelector('#jobContentSelectionZone .cs-retained-note[data-fate="SELECTED_OPTION_REMOVED"]') &&
    !!document.querySelector('#jobContentSelectionZone .cs-retained-gone')`,
  'H4: stale command and three retained fates', { timeoutMs: 30000 });
  const projection = view(await snapshot(s)).projection;
  const fates = Object.fromEntries(projection.retained_selections.map(item => [item.slot_id, item.fate]));
  requireValue(['RESOLVED', 'SELECTED_OPTION_REMOVED', 'SLOT_REMOVED']
    .every(fate => Object.values(fates).includes(fate)) &&
    new Set(Object.values(fates)).size === 3,
  `H4: retained fates merged: ${JSON.stringify(fates)}`);
  const currentIds = projection.slots.map(slot => slot.slot_id);
  requireValue(Object.entries(fates).every(([id, fate]) =>
    fate !== 'SLOT_REMOVED' || !currentIds.includes(id)),
  'H4: removed Slot was resurrected');
  const visible = await s.value(`document.getElementById('jobContentSelectionZone').innerText`);
  requireValue(Object.keys(fates).every(id => !visible.includes(id)),
    'H4: retained copy exposed internal Slot ID');
  const trace = await s.takeDispatchTrace();
  const staleCommands = trace.filter(item => item.action === 'select_slot_option');
  requireValue(staleCommands.length > 0, 'H4: stale command trace absent');
  await pickOption(s, '#cs-opt-1-0');
  await s.wait(`document.getElementById('cs-opt-1-0').checked`, 'broken Option repaired');
  await pickOption(s, '#cs-opt-0-0');
  await s.wait(`document.getElementById('cs-opt-0-0').checked`, 'retained Option confirmed');
  await s.wait(`!document.querySelector('#jobContentSelectionZone .cs-retained-note[data-fate="RESOLVED"]') &&
    !document.querySelector('#jobContentSelectionZone .cs-retained-note[data-fate="SELECTED_OPTION_REMOVED"]') &&
    !!document.querySelector('#jobContentSelectionZone .cs-retained-gone')`,
  'H4: repaired notes closed, removed Slot remains');
  const remaining = view(await snapshot(s)).projection.retained_selections.map(item => item.fate);
  requireValue(remaining.length === 1 && remaining[0] === 'SLOT_REMOVED',
    'H4: repaired fate remained or removed Slot disappeared');
  const exactTarget = 'binding/추가확인';
  const button = `#jobInputRequirements button[data-exact-target="${exactTarget}"]`;
  await s.wait(`!!document.querySelector(${JSON.stringify(button)})`,
    'exact Binding action', { requires: ['#jobInputRequirements'] });
  await s.click(button, 'repair exact Binding');
  const row = '#editor-body table.map tr[data-field="추가확인"]';
  const source = `${row} select[data-act="row-source"]`;
  await s.wait(`!!document.querySelector('#scr-editor.on') &&
    !!document.querySelector(${JSON.stringify(source)}) &&
    document.activeElement===document.querySelector(${JSON.stringify(source)})`,
  'exact Binding row focused', { requires: ['#scr-editor', row] });
  await s.setValue(source, 'col:공고명');
  const badge = `${row} button[data-act="row-confirm"]`;
  await s.wait(`!!document.querySelector(${JSON.stringify(`${badge}:not([disabled])`)})`,
    'Binding confirmation armed');
  await s.click(badge, 'confirm Binding source');
  await s.wait(`document.querySelector(${JSON.stringify(badge)})?.getAttribute('aria-pressed')==='true'`,
    'Binding source confirmed');
  await s.clickText('#scr-editor', '변경 저장');
  await s.wait(`document.querySelector('#scr-editor').textContent.includes('저장했습니다')`,
    'Binding saved', { timeoutMs: 30000 });
  await s.click('#editorBack', 'return from editor');
  await s.wait(`!!document.querySelector('#scr-job.on')`, 'Binding ReturnContext',
    { timeoutMs: 30000 });
  const binding = bench(await snapshot(s), 'binding repair');
  const repaired = { field_id: '추가확인',
    active_field: binding.active_field_requirement_ids.includes('추가확인'),
    pending_action: binding.input_requirements.some(item => item.field_id === '추가확인') };
  requireValue(repaired.active_field && !repaired.pending_action,
    'H4: saved Binding did not recompute current requirements');
  return { retained_fates: fates, binding_target: exactTarget,
    binding_repaired: repaired, stale_trace: staleCommands };
}

async function contextAndRecords(s, staging) {
  await staging.context('corrupt');
  await s.click('.navbtn[data-scr="library"]', 'context error transition');
  await s.wait(`!!document.querySelector('#scr-library.on')`, 'library after context corruption');
  await s.click('.navbtn[data-scr="job"]', 'context error job return');
  await s.wait(`document.getElementById('jobContentSelectionZone').textContent
    .includes('포함할 내용을 불러오지 못했습니다') &&
    !!window.__cap.btn('#jobContentSelectionZone','다시 불러오기')`,
  'H5: backend context recovery action', { requires: ['#jobContentSelectionZone'] });
  const contextText = await s.value(`document.getElementById('jobContentSelectionZone').innerText`);
  requireValue(!contextText.includes('INVALID_CONFIGURATION_TOKEN'),
    'H5: raw context error code is visible');
  await staging.context('restore');
  await s.clickText('#jobContentSelectionZone', '다시 불러오기');
  await s.wait(`document.querySelectorAll('#jobContentSelectionZone .cs-slot').length===2`,
    'H5: context recovered', { timeoutMs: 30000 });

  await mountData(s, await staging.data('blank'));
  await selectAll(s, 'blank record selected');
  await s.wait(`!!document.getElementById('jobRecordValidationAdvisory') &&
    !document.getElementById('jobRecordValidationIssues')`,
  'H5: blank record is advisory, not blocker', { timeoutMs: 30000 });
  const record = bench(await snapshot(s), 'blank record');
  const advisory = await s.value(`document.getElementById('jobRecordValidationAdvisory').textContent`);
  requireValue(record.record_validation.issues.length === 0 &&
    record.record_validation.advisory_count >= 1,
  `H5: blank record blocked: ${advisory}`);
  await mountData(s, await staging.data('clean'));
  const stale = await s.dispatch('job', 'recover_record_issue', { target: {
    target_kind: 'cell', snapshot_generation: -1,
    record_identity: 'current-record/-1/0', model_index: 0, field_id: '공고명',
  } });
  const message = stale?.__hwpx_dispatch_rejection_v1__?.message ?? stale?.error ?? '';
  requireValue(String(message).includes('다시 확인해'),
    `H7: stale record recovery target was accepted: ${JSON.stringify(stale)}`);
  return { context_text: contextText, record_advisory: advisory,
    old_record_rejected: true };
}

async function deliveryAndOverwrite(s, staging, home) {
  await selectAll(s, 'records reselected after data transition');
  const templates = path.join(home, 'templates');
  await setFolder(s, templates, '#settingsPickTplFolder', '#settingsTplDir', '설정한 폴더');
  const output = await staging.output();
  await setFolder(s, output, '#settingsPickFolder', '#settingsOutDir');
  try {
    await s.wait(`document.querySelectorAll('#jobPlannedDocuments li').length>0`,
      'H5: exact delivery plan', { timeoutMs: 30000 });
  } catch (error) {
    const blockers = await s.value(`document.getElementById('jobDeliveryBlockers')?.innerText.trim()`);
    throw new Error(`H5: delivery plan absent: blockers=${JSON.stringify(blockers)}: ${error.message}`);
  }
  const before = bench(await snapshot(s), 'before collision').delivery.planned_documents;
  const dispositions = before.map(item => item.collision_disposition);
  requireValue(dispositions.length > 0 && !dispositions.includes('WRITE_OVERWRITE'),
    `H5: destructive disposition before collision: ${dispositions}`);
  const relative = before[0].relative_path;
  await staging.collision(relative);
  const baseline = await staging.manifest();
  await setFolder(s, output, '#settingsPickFolder', '#settingsOutDir');
  await s.wait(`!!document.querySelector('#jobPlannedDocuments li[data-collision-disposition="WRITE_OVERWRITE"]')`,
  'H5: destructive overwrite disposition', { timeoutMs: 30000 });
  const current = bench(await snapshot(s), 'after collision');
  requireValue(current.delivery.planned_documents.some(item =>
    item.collision_disposition === 'WRITE_OVERWRITE'),
  'H5: collision did not yield WRITE_OVERWRITE');
  requireValue(!await s.value(`!!document.getElementById('jobManagedPreviewOpen')`),
    'H5: retired managed preview is visible');
  await s.wait(`!document.getElementById('jobManagedCreate').disabled`,
    'H6: managed create enabled', { requires: ['#jobManagedCreate'] });
  const planned = current.delivery.planned_documents.map(item => item.relative_path);
  await s.click('#jobManagedCreate', 'managed create');
  await s.wait(`!document.getElementById('confirmModal').classList.contains('hidden') &&
    document.getElementById('confirmModalTitle').textContent.includes('덮어쓰기')`,
  'H5: overwrite confirmation', { timeoutMs: 30000 });
  const body = await s.value(`document.getElementById('confirmModalBody').textContent`);
  requireValue(body.includes('덮어씁니다') && body.includes(relative),
    'H5: overwrite confirmation does not name destructive action and path');
  await s.click('#confirmModalOk', 'confirm overwrite');
  await s.wait(`document.getElementById('jobResult')?.dataset.state==='completed'`,
    'H6: managed generation completed', { timeoutMs: 60000 });
  const after = await staging.manifest();
  requireValue(JSON.stringify(after) !== JSON.stringify(baseline),
    'H6: managed create did not alter output files');
  requireValue(planned.every(name => Object.hasOwn(after, name)),
    'H6: a planned output file is absent');
  await s.click('#jobResultClose', 'close managed result');
  return { templates_root_roundtrip: templates, output,
    dispositions_before: dispositions, overwrite_confirm_body: body,
    runtime_reason: current.create_action?.disabled_reason,
    filesystem_before: baseline, filesystem_after: after };
}

async function transitionsAndRace(s, staging) {
  const beforeCancel = await snapshot(s);
  await s.click('#jobBtnPickData', 'cancel DataTarget');
  await s.wait(`!document.getElementById('dataPickerModal').classList.contains('hidden')`,
    'DataTarget cancel surface');
  await s.click('#dataPickerClose', 'cancel data picker');
  await s.wait(`document.getElementById('dataPickerModal').classList.contains('hidden')`,
    'data picker cancel settled');
  requireValue((await snapshot(s)).job_name === beforeCancel.job_name,
    'H7: cancel changed active Work');
  await mountData(s, await staging.data('missing'), true);
  requireValue((await snapshot(s)).job_name === '발주요청서',
    'H7: failed data transition changed committed Work');
  await mountData(s, await staging.data('release'));
  await s.wait(`document.getElementById('jobActionName').textContent.trim()===''`,
    'H7: incompatible data RELEASE', { timeoutMs: 30000 });
  await mountData(s, await staging.data('clean'));
  await selectWork(s, '발주요청서');
  await mountData(s, await staging.data('clean'));
  await s.wait(`document.getElementById('jobActionName').textContent.trim()==='발주요청서'`,
    'H7: compatible data KEEP', { timeoutMs: 30000 });
  await s.gateDispatch('select_slot_option', 'after');
  await pickOption(s, '#cs-opt-0-1');
  await s.waitDispatchGate('Work A response held');
  await selectWork(s, '발주요청 기안');
  await s.releaseDispatch();
  await s.wait(`document.getElementById('jobActionName').textContent.trim()==='발주요청 기안' &&
    !document.getElementById('cs-opt-0-1') &&
    document.querySelectorAll('#jobContentSelectionZone .cs-slot').length===0 &&
    document.getElementById('jobContentSelectionZone').children.length===0 &&
    !document.querySelector('#jobContentSelectionZone .cs-presets')`,
  'H7: Work B latest snapshot wins', { timeoutMs: 30000 });
  requireValue(await s.value(`getComputedStyle(document.getElementById('jobContentSelectionZone')).display`) === 'none',
    'H7: empty selection zone remained visible');
  await selectWork(s, '발주요청서');
  return { data_transition: 'KEEP/RELEASE/FAILURE_ATOMIC', work_race: 'B_WON' };
}

export async function runJourney(s, home, evidence) {
  const manifest = await verifyFixtures(home);
  const staging = new Staging(home, manifest);
  const seen = {};
  await s.click('#wbBack', 'leave workbench for SX-05');
  await s.wait(`!!document.querySelector('#scr-job.on') || !!window.__cap.btn(null,'나가기')`,
    'workbench exit');
  await s.value(`window.__cap.clickBtn(null,'나가기')`);
  await s.wait(`!!document.querySelector('#scr-job.on')`, 'SX-05 job return');
  await selectWork(s, '발주요청서');
  await s.installDispatchProbe();
  await applyStagedTemplate(s, staging, 'initial', true);
  await s.installDispatchProbe();
  await s.wait(`document.querySelectorAll('#jobContentSelectionZone .cs-slot').length===3`,
    'three canonical Slots', { requires: ['#jobContentSelectionZone'] });
  const first = view(await snapshot(s));
  const rawIds = first.projection.slots.flatMap(slot =>
    [slot.slot_id, ...slot.options.map(option => option.option_id)]);
  const visible = await s.value(`document.getElementById('jobContentSelectionZone').innerText`);
  requireValue(rawIds.every(id => !visible.includes(id)), 'H1: raw Slot/Option ID is visible');
  const labels = await s.value(`[...document.querySelectorAll('#jobContentSelectionZone .cs-slot-legend,#jobContentSelectionZone .cs-option-text')].map(e=>e.textContent.trim())`);
  requireValue(labels.length === 9, 'H1: canonical labels are incomplete');
  const pixel = await s.auditShot('sx05-content-selection', path.join(evidence, 'pixels'));
  requireValue(pixel.size > 0 && !pixel.unstable, 'H1: pixel evidence is unstable');
  await s.takeDispatchTrace();
  const beforeToken = first.new_configuration_token;
  await pickOption(s, '#cs-opt-0-0');
  await s.wait(`document.getElementById('cs-opt-0-0').checked`, 'first Option current');
  requireValue(await s.value(`document.getElementById('cs-opt-0-0').closest('details').open`),
    'H1: touched Slot collapsed');
  const changed = view(await snapshot(s));
  requireValue(changed.new_configuration_token !== beforeToken,
    'H2: configuration token did not advance');
  requireValue(changed.projection.slots[0].options[0].selected &&
    changed.projection.slots[0].options[0].effective,
  'H2: declared/effective Option differ');
  const h2Trace = await s.takeDispatchTrace();
  requireValue(h2Trace.some(item => item.action === 'select_slot_option'),
    `H2: native command trace absent: ${JSON.stringify(h2Trace)}`);
  for (const selector of ['#cs-opt-1-0', '#cs-opt-2-0']) {
    await pickOption(s, selector);
    await s.wait(`document.querySelector(${JSON.stringify(selector)}).checked`, `${selector} selected`);
  }
  const beforeFields = bench(await snapshot(s), 'H3 A').active_field_requirement_ids;
  await pickOption(s, '#cs-opt-0-1');
  await s.wait(`document.getElementById('cs-opt-0-1').checked`, 'H3 B');
  const afterFields = bench(await snapshot(s), 'H3 B').active_field_requirement_ids;
  requireValue(JSON.stringify(beforeFields) !== JSON.stringify(afterFields),
    'H3: Active Fields did not change with Option');
  await pickOption(s, '#cs-opt-0-0');
  await s.wait(`document.getElementById('cs-opt-0-0').checked`, 'H3 A restored');
  seen.H1 = { labels, raw_ids: rawIds, pixel };
  seen.H2 = { before_token: beforeToken, after_token: changed.new_configuration_token,
    trace: h2Trace };
  seen.H3 = { option_a_fields: beforeFields, option_b_fields: afterFields };
  seen.preset = await presetRoundtrip(s);
  const h4 = await successorAndBinding(s, staging);
  seen.H4 = { retained_fates: h4.retained_fates,
    binding_target: h4.binding_target, binding_repaired: h4.binding_repaired };
  seen.H7 = { stale_trace: h4.stale_trace };
  const record = await contextAndRecords(s, staging);
  const delivery = await deliveryAndOverwrite(s, staging, home);
  const transitions = await transitionsAndRace(s, staging);
  seen.H5 = { context_copy: record.context_text, record_advisory: record.record_advisory,
    dispositions_before: delivery.dispositions_before,
    overwrite_confirm_body: delivery.overwrite_confirm_body,
    runtime_reason: delivery.runtime_reason };
  seen.H6 = { filesystem_before: delivery.filesystem_before,
    filesystem_after: delivery.filesystem_after };
  seen.H7 = { ...seen.H7, old_record_rejected: record.old_record_rejected,
    ...transitions };
  seen.templates_root_roundtrip = delivery.templates_root_roundtrip;
  return { seen, output: delivery.output };
}
