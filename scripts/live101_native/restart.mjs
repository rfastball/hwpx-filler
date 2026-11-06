import { Staging, verifyFixtures } from './fixtures.mjs';
import { stat } from 'node:fs/promises';
import path from 'node:path';

const requireValue = (condition, reason) => { if (!condition) throw new Error(reason); };

export async function runRestart(surface, home) {
  const s = surface;
  const staging = new Staging(home, await verifyFixtures(home));
  const before = await staging.manifest();
  const initial = await s.snapshot('job');
  const data = { has_data: initial.has_data, selected_count: initial.selected_count,
    notice: initial.data_notice ?? null };
  requireValue(data.has_data === true && data.selected_count === 0 && data.notice === null,
    `H7: remembered data was not restored without selection: ${JSON.stringify(data)}`);
  requireValue(initial.has_job === false, 'H7: session active Work survived restart');
  requireValue(initial.workbench_observation?.run_delivery_intent == null,
    'H7: delivery intent exists before selecting Work');
  const output = path.join(home, 'sx-output');
  requireValue((await stat(output)).isDirectory(), 'H7: the prior output directory is absent');
  requireValue(initial.output_folder?.directory === output &&
    initial.output_folder?.source === 'remembered',
  `H7: global output folder was not restored: ${JSON.stringify(initial.output_folder)}`);
  await s.wait(`document.getElementById('jobActionName').textContent.trim()===''`,
    'restart active Work absent');
  const selector = '#jobCandidates button[data-cand="발주요청서"]';
  await s.wait(`!!document.querySelector(${JSON.stringify(selector)}) &&
    !document.querySelector(${JSON.stringify(selector)}).disabled`,
  'restart Work selectable');
  await s.click(selector, 'reselect Work after restart');
  await s.wait(`document.getElementById('jobActionName').textContent.trim()==='발주요청서'`,
    'restart Work selected');
  const current = await s.snapshot('job');
  const view = current.slot_configuration?.current_view;
  requireValue(Array.isArray(view?.projection?.slots) && view.projection.slots.length > 0,
    'H7: durable selection projection absent');
  const selections = Object.fromEntries(view.projection.slots.map(slot =>
    [slot.slot_id, slot.options.filter(option => option.effective).map(option => option.option_id)]));
  requireValue(Object.values(selections).some(options => options.length > 0),
    'H7: durable selections are empty');
  const bench = current.workbench_observation;
  requireValue(bench?.supported === true, 'H7: workbench absent after reselecting Work');
  requireValue(Array.isArray(bench.input_requirements),
    'H7: Binding requirements are absent');
  const binding = { field_id: '추가확인',
    active_field: bench.active_field_requirement_ids?.includes('추가확인') === true,
    pending_action: bench.input_requirements?.some(item => item.field_id === '추가확인') === true };
  requireValue(binding.active_field && !binding.pending_action,
    `H7: saved Binding was not restored: ${JSON.stringify(binding)}`);
  const intent = bench.run_delivery_intent;
  const delivery = { directory: intent?.output_directory,
    source: current.output_folder?.source, collision_policy: intent?.collision_policy };
  requireValue(delivery.directory === output && delivery.source === 'remembered' &&
    delivery.collision_policy === 'OVERWRITE_EXPLICIT',
  `H7: delivery default after restart differs: ${JSON.stringify(delivery)}`);
  const after = await staging.manifest();
  requireValue(JSON.stringify(before) === JSON.stringify(after),
    'H7: restart observation changed generated files');
  return { sx05_restart: {
    durable: { job: current.job_name, selections, binding },
    delivery_default: delivery, data_restored: data,
    session_absent: { active_work_before_reselect: true },
    filesystem_before: before, filesystem_after: after,
  } };
}
