import { CAPTURE_POINTS } from './legacy.mjs';

function judgeLegacy(report) {
  const failures = [];
  const o = report.observations ?? {};
  if (report.hwpx_generated !== 3) failures.push(`HWPX documents ${report.hwpx_generated}, expected 3`);
  if (o.hwpx_result_state !== 'completed') failures.push('HWPX completion state absent');
  if (o.preview_surface_retired !== true) failures.push('retired preview is visible');
  if (!String(o.txt_copied ?? '').startsWith('1 /')) failures.push('TXT copy counter absent');
  if (o.empty_value_gate_asked !== true) failures.push('empty value confirmation gate absent');
  if (o.empty_value_surfaced !== true) failures.push('empty value surface absent');
  if (o.save_and_open_seated !== true) failures.push('save-and-open did not seat Work');
  if (!String(o.seq_example_positive ?? '').includes('· 002 · 003')) failures.push('sequence positive example absent');
  if (!o.seq_example_negative || String(o.seq_example_negative).includes('· 002')) failures.push('sequence negative example wrong');
  if (report.shots?.join('|') !== CAPTURE_POINTS.join('|')) failures.push('capture points differ');
  if (report.mode === 'capture' && report.unstable_shots?.length) failures.push('capture contains an unstable frame');
  return { ok: failures.length === 0, failures };
}

export function judgePhase(report) {
  if (report.phase === 'restart') {
    const o = report.observations?.sx05_restart;
    const failures = [];
    if (o?.data_restored?.has_data !== true || o.data_restored.selected_count !== 0 ||
        o.data_restored.notice !== null) {
      failures.push('remembered data did not restore without session selection');
    }
    const durable = o?.durable;
    if (durable?.job !== '발주요청서' ||
        !durable.selections || Object.keys(durable.selections).length === 0 ||
        durable.binding?.active_field !== true || durable.binding.pending_action !== false) {
      failures.push('durable Work S4/Binding absent');
    }
    if (!o?.session_absent || !Object.values(o.session_absent).length ||
        !Object.values(o.session_absent).every(value => value === true)) {
      failures.push('session-only state survived restart');
    }
    if (!o || JSON.stringify(o.filesystem_before) !== JSON.stringify(o.filesystem_after)) {
      failures.push('restart changed generated files');
    }
    if (report.shots?.length) failures.push('restart repeated legacy shutters');
    return { ok: failures.length === 0, failures };
  }
  const legacy = judgeLegacy(report);
  if (report.phase === 'legacy') return legacy;
  const sx = report.observations?.sx05;
  const failures = [...legacy.failures];
  if (report.phase !== 'journey' ||
      !sx || !['H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'H7'].every(key => sx[key])) {
    failures.push('SX-05 evidence is incomplete');
  }
  if (!sx?.H1?.pixel?.sha256 || sx.H1.pixel.unstable !== false) {
    failures.push('SX-05 actual pixel evidence absent or unstable');
  }
  if (sx?.H6 && JSON.stringify(sx.H6.filesystem_before) ===
      JSON.stringify(sx.H6.filesystem_after)) failures.push('SX-05 generation left output unchanged');
  if (sx?.H7?.work_race !== 'B_WON') failures.push('SX-05 latest Work did not win');
  return { ok: failures.length === 0, failures };
}
