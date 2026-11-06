import test from 'node:test';
import assert from 'node:assert/strict';
import { CAPTURE_POINTS } from '../../scripts/live101_native/legacy.mjs';
import { judgePhase } from '../../scripts/live101_native/verdict.mjs';

function report() {
  return {
    phase: 'journey', mode: 'check', hwpx_generated: 3, shots: [...CAPTURE_POINTS],
    observations: {
      hwpx_result_state: 'completed', preview_surface_retired: true,
      txt_copied: '1 / 3', empty_value_gate_asked: true,
      empty_value_surfaced: true, save_and_open_seated: true,
      seq_example_positive: '예: 001 · 002 · 003', seq_example_negative: '예: 001',
      sx05: {
        H1: { pixel: { sha256: 'pixel', unstable: false } },
        H2: {}, H3: {}, H4: {}, H5: {},
        H6: { filesystem_before: {}, filesystem_after: { output: 'digest' } },
        H7: { work_race: 'B_WON' },
      },
    },
  };
}

test('native live report accepts complete evidence and rejects omitted journey facts', () => {
  const healthy = report();
  assert.equal(judgePhase(healthy).ok, true);
  for (const mutate of [
    value => { value.observations.sx05.H1.pixel.unstable = undefined; },
    value => { value.observations.sx05.H7.work_race = undefined; },
    value => { value.observations.sx05.H6.filesystem_after = {}; },
    value => { value.hwpx_generated = 0; },
  ]) {
    const broken = structuredClone(healthy);
    mutate(broken);
    assert.equal(judgePhase(broken).ok, false);
  }
});

test('native restart report requires current S4 intent, Binding and absent session state', () => {
  const healthy = {
    phase: 'restart', shots: [], observations: { sx05_restart: {
      data_restored: { has_data: true, selected_count: 0, notice: null },
      durable: { job: '발주요청서', selections: { slot: ['option'] },
        binding: { active_field: true, pending_action: false } },
      session_absent: { active_work_before_reselect: true },
      filesystem_before: { output: 'digest' }, filesystem_after: { output: 'digest' },
    } },
  };
  assert.equal(judgePhase(healthy).ok, true);
  for (const mutate of [
    value => { value.observations.sx05_restart.durable.selections = {}; },
    value => { delete value.observations.sx05_restart.durable.binding.pending_action; },
    value => { delete value.observations.sx05_restart.session_absent; },
    value => { delete value.observations.sx05_restart.data_restored.notice; },
  ]) {
    const broken = structuredClone(healthy);
    mutate(broken);
    assert.equal(judgePhase(broken).ok, false);
  }
});
