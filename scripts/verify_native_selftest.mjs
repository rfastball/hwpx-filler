#!/usr/bin/env node
// Judge the native WebView receipt against the existing full-probe contract.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyJobReceipt } from './native_selftest_job.mjs';
import { verifyEditorReceipt } from './native_selftest_editor.mjs';
import { verifyWorkbenchReceipt } from './native_selftest_workbench.mjs';
import { verifyEditorDetailReceipt } from './native_selftest_editor_detail.mjs';
import { verifySurfaceReceipt } from './native_selftest_surfaces.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = file => JSON.parse(readFileSync(file, 'utf8'));
const hex64 = /^[a-f0-9]{64}$/;

function verifyReceiptIdentity(receipt, identity, graph) {
  if (Object.hasOwn(receipt, 'error')) {
    const detail = String(receipt.error);
    const start = detail.indexOf('{');
    let failed;
    if (start >= 0) {
      try {
        const result = JSON.parse(detail.slice(start));
        failed = result.errors?.[0] ?? result.evidence?.error;
      } catch { /* The original message remains the failure evidence. */ }
    }
    throw new Error(`WebView probe failed: ${failed ? JSON.stringify(failed) :
      detail.slice(0, 800)}`);
  }
  const expected = [...new Set(graph.probes.filter(probe => probe.modes.includes('full'))
    .flatMap(probe => probe.keys))].sort();
  assert.deepEqual(Object.keys(receipt).sort(), expected, 'full probe closure differs');
  for (const [name, value] of Object.entries(receipt)) {
    if (typeof value === 'boolean') assert.equal(value, true, `${name} is false`);
  }
  const runtime = receipt.runtime;
  assert.equal(receipt.url, 'http://tauri.localhost/');
  assert.equal(runtime.page_url, receipt.url);
  assert.equal(runtime.origin, 'http://tauri.localhost');
  assert.match(runtime.artifact_id, hex64);
  assert.match(runtime.tree_sha256, hex64);
  assert.equal(runtime.artifact_id, identity.artifact_id);
  assert.equal(runtime.tree_sha256, identity.tree_sha256);
  assert.ok(Array.isArray(runtime.resource_urls) && runtime.resource_urls.length > 0);
  assert.ok(runtime.resource_urls.every(url => url.startsWith(`${runtime.origin}/`)));
  assert.equal(runtime.resources_same_origin, true);
  assert.deepEqual(runtime.forbidden_resources, []);
  assert.equal(runtime.external_fetch_completed, true);
  assert.equal(runtime.external_fetch_succeeded, false);
  assert.equal(runtime.external_fetch_blocked, true);
  assert.equal(typeof runtime.external_fetch_error, 'string');
  assert.ok(runtime.external_fetch_error.length > 0);
  assert.notEqual(runtime.external_fetch_error, 'external fetch succeeded');
  assert.notEqual(runtime.external_fetch_error, 'offline probe timed out');
  return expected.length;
}

function verifyReactAndPicker(receipt) {
  const react = receipt.react_runtime;
  assert.equal(react.mounted, '1');
  assert.equal(react.roots, 1);
  assert.match(react.store_rev, /^[0-9]+$/);
  const tutorial = [
    'target_hit', 'off_target_free', 'hud_hit', 'panel_hit',
    'coach_in_view', 'spot_covers_target', 'coach_150_in_view', 'hud_150_hit',
    'dialog_guide_in_focus_boundary', 'dialog_exit_reachable', 'dialog_target_hit',
    'dialog_escape_keeps_guide',
  ];
  assert.deepEqual(Object.keys(react.tutorial_surface).sort(), tutorial.sort());
  for (const key of tutorial) assert.equal(react.tutorial_surface[key], true, `tutorial.${key}`);

  assert.ok(receipt.title_dom);
  assert.equal(receipt.nav_count, 2);
  assert.equal(receipt.job_on, true);
  assert.equal(receipt.data_picker_buttons, true);
  const picker = receipt.data_picker;
  assert.equal(picker.error, null);
  assert.equal(picker.rows, 4);
  assert.match(picker.session_row, /대장\.xlsx/);
  for (const key of [
    'opened', 'use_active_enabled', 'use_archived_disabled', 'activate_reachable',
    'relink_reachable', 'reveal_reachable', 'corrupt_shown', 'pin_offered',
    'register_gone', 'pin_path_readonly', 'pin_sheet_selectable', 'pin_browse_hidden',
    'browse_kept_open', 'browse_restated', 'browse_pin_visible', 'use_targets_key',
    'dupes_shown', 'pclm_row_usable', 'pclm_no_relink', 'pclm_sheet_edit_reachable',
    'pclm_edit_db_locked', 'pclm_edit_custom_visible', 'pclm_edit_default_locked',
    'pclm_entry_gone', 'pclm_reg_initial_empty', 'pclm_reg_multiple_selected',
  ]) assert.equal(picker[key], true, `data_picker.${key}`);
  assert.equal(picker.pin_title, '이 데이터 등록');
  assert.equal(picker.pin_ok, '등록');
  assert.equal(picker.pin_path, 'C:/d/대장.xlsx');
  assert.equal(picker.pin_sheet, '물품');
  assert.equal(picker.pclm_reg_view_options, 3);
  assert.equal(picker.pclm_reg_db_prefill, 'C:/d/pclm.db');
  assert.equal(picker.pclm_reg_view_text, 'v_통합_v2|v_접수_v1|계약');
  assert.equal(picker.pclm_reg_view_label, '사용할 시트');
}

function verifyActionsAndPairing(receipt) {
  const actions = receipt.action_roundtrip;
  assert.equal(actions.pending, false);
  for (const [family, screen, action] of [
    ['editor', 'editor', 'new_session'], ['job', 'job', 'refresh'],
    ['pool', 'pool', 'refresh'], ['template', 'tpl', 'refresh'],
  ]) {
    const observed = actions.families[family];
    assert.equal(Object.hasOwn(observed, 'error'), false, `${family} dispatch`);
    assert.equal(observed.screen, screen);
    assert.equal(observed.action, action);
    assert.equal(observed.snapshot, true);
    assert.ok(observed.snapshot_keys.length > 0);
  }
  assert.deepEqual(Object.keys(actions.families).sort(),
    ['editor', 'job', 'pool', 'template']);
  assert.equal(receipt.home_screen_gone, true);
  assert.equal(receipt.library_surface, true);
  assert.deepEqual(receipt.library_view_tabs, ['all', 'recent', 'favorites', 'needsAction']);
  const pair = receipt.library_pairing_edit;
  assert.equal(pair.bound_present, true);
  assert.equal(pair.bound_title, '고르기에서 조합을 바꿉니다');
  assert.equal(pair.bound_nums, '연결 3 / 4');
  assert.equal(pair.entry_calls, 1);
  assert.deepEqual([pair.entry_name, pair.entry_section, pair.entry_reason],
    ['연결손잡이검증', 'template', 'library']);
  assert.equal(pair.uncounted_present, true);
  assert.equal(pair.uncounted_title, pair.bound_title);
  assert.equal(pair.uncounted_label, '조합 보기');
  assert.equal(pair.connect_data, '연결손잡이검증');
}

function verifyShellState(receipt) {
  const order = receipt.view_order;
  assert.equal(order.error, undefined);
  assert.equal(order.present, true);
  assert.deepEqual(order.options, ['sourceDesc', 'sourceAsc']);
  assert.equal(order.control_before, true);
  assert.deepEqual([order.after_roundtrip, order.restored], ['sourceAsc', 'sourceDesc']);
  assert.deepEqual([order.label_before, order.label_after_roundtrip, order.label_restored],
    ['아래 행부터', '위 행부터', '아래 행부터']);
  const draft = receipt.range_draft;
  assert.equal(draft.error, undefined);
  assert.equal(draft.present, true);
  assert.equal(draft.foot_hidden_in_screen, true);
  assert.equal(draft.opened_without_data, false);
  assert.equal(draft.draft_state.open, false);
  const chain = receipt.chain_recovery;
  assert.equal(chain.error, undefined);
  assert.equal(chain.rejected_surfaced, true);
  assert.equal(chain.after_ran, true);
  assert.equal(chain.after_value, 'ok');
  const settings = receipt.shell_settings;
  assert.equal(settings.opened, true);
  assert.equal(typeof settings.display, 'string');
  assert.notEqual(settings.display, 'none');
  assert.equal(settings.option_visible, true);
  assert.equal(settings.applied_theme, settings.requested_theme);
  assert.equal(settings.option_pressed, 'true');
  assert.equal(settings.theme_restored, settings.theme_before);
  assert.equal(settings.closed, true);
  assert.equal(settings.focus_back, 'settingsOpen');
}

function verifyModalAndGeometry(receipt) {
  const modal = receipt.modal_a11y;
  for (const key of [
    'opened', 'escape_entered_closing', 'closed_by_escape', 'confirm_opened',
    'confirm_entered_closing', 'confirm_closed', 'choose_opened',
    'choose_all_visible', 'non_modal_open_rejected_loud', 'danger_class',
    'danger_resets_to_neutral', 'non_modal_close_rejected_loud',
    'malformed_confirm_root_refused_loud', 'confirm_after_malformed_opens',
  ]) assert.equal(modal[key], true, `modal.${key}`);
  assert.equal(modal.focus_in, 'promptModalInput');
  assert.equal(modal.focus_restored, modal.focus_before);
  assert.deepEqual([modal.confirm_display_closed_before, modal.confirm_display_open,
    modal.confirm_display_closed], ['none', 'flex', 'none']);
  assert.equal(modal.confirm_focus, 'confirmModalCancel');
  assert.equal(modal.choose_display, 'flex');
  assert.equal(modal.choose_focus, 'chooseModalCancel');
  assert.equal(modal.choose_labels, '저장하고 이동|버리고 이동|머무르기');
  assert.equal(typeof modal.danger_background, 'string');
  assert.notEqual(modal.danger_background, 'transparent');
  assert.notEqual(modal.danger_background, 'rgba(0, 0, 0, 0)');
  assert.equal(modal.confirm_reentry_alerts, 1);
  assert.equal(modal.confirm_body_after_reentry, '첫 확인 본문');
  assert.equal(modal.confirm_trap_wrapped, 'confirmModalCancel');
  assert.deepEqual(receipt.modal_confirm_serial, { first: true, second: false });
  assert.deepEqual(receipt.sheet_gate, {
    status: 'done', opened: true, btn_count: 2, focus_first: true,
    picked: '확정됨:낙찰현황', cancelled: null, closed_after: true,
  });
  assert.equal(receipt.grid_narrow.tabs, 2);
  assert.equal(receipt.grid_narrow.tool_labels_visible, false);
  assert.equal(receipt.grid_narrow.overflow, false);
  assert.equal(receipt.grid_wide.rows, 2);
  assert.equal(receipt.grid_wide.tabs, 2);
  assert.equal(receipt.grid_wide.tool_labels_visible, true);
  assert.equal(receipt.grid_wide.overflow, false);
  assert.deepEqual(receipt.preserve, {
    focus_id: 'preserveProbeInput', sel_start: 2, sel_end: 4, scroll_top: 120,
  });
  for (const screen of ['editor', 'job']) {
    assert.equal(receipt.preserve_real[screen], 'ok');
  }
  assert.ok(Number.isFinite(receipt.preserve_real.editor_scroll_before) &&
    receipt.preserve_real.editor_scroll_before > 0);
  assert.ok(Math.abs(receipt.preserve_real.editor_scroll_top -
    receipt.preserve_real.editor_scroll_before) < 2);
}

function verifyHWPXPreflight(receipt) {
  // The HWPX authoring owner must execute against the two seeded corpus copies.
  // A 45-key receipt can otherwise be green while the keyboard branch is skipped.
  const authoring = receipt.editor_txt_band;
  assert.ok(authoring.hwpx_authoring_error == null);
  assert.ok(authoring.hwpx_authoring_restore_error == null);
  assert.ok(authoring.hwpx_kbd_skipped == null,
    'HWPX keyboard owner was skipped');
  assert.equal(authoring.hwpx_authoring_library_rows, 2);
  assert.equal(authoring.hwpx_authoring_entry_affordance, true);
  assert.ok(Array.isArray(authoring.hwpx_authoring_preflight) &&
    authoring.hwpx_authoring_preflight.length > 0);
  assert.ok(authoring.hwpx_authoring_candidate);
  assert.ok(authoring.hwpx_authoring_aborted == null);
  assert.equal(authoring.hwpx_authoring_mounted, true);
  assert.equal(authoring.hwpx_authoring_rhwp_editable, true);
  const judged = authoring.hwpx_authoring_preflight.filter(
    candidate => candidate.editable != null);
  assert.ok(judged.length > 0, 'HWPX preflight has no judged corpus copy');
  for (const entry of judged) {
    assert.equal(entry.saw_checking, true);
    assert.deepEqual([entry.compat_state, entry.chip_after, entry.banner],
      entry.editable ? ['editable', '', false] :
        ['limited', '읽기 전용 · 보존 확인 필요', true]);
  }
  assert.equal(authoring.hwpx_authoring_readiness, 'ready');
  assert.equal(authoring.hwpx_authoring_alerts, 0);
  assert.ok(authoring.hwpx_authoring_library_rows > 0);
  const base = authoring.hwpx_authoring_base_field_count;
  assert.ok(Number.isInteger(base) && base > 0);
  return base;
}

function verifyHWPXEdit(receipt, base) {
  const authoring = receipt.editor_txt_band;
  assert.equal(authoring.hwpx_authoring_target_field_count, 2);
  assert.equal(authoring.hwpx_authoring_target_formatted, true);
  assert.equal(authoring.hwpx_authoring_save_as_required, true);
  assert.equal(authoring.hwpx_authoring_save_asked_for_path, true);
  assert.equal(authoring.hwpx_authoring_save_needs_path, true);
  assert.equal(authoring.hwpx_authoring_save_path_after, '');
  assert.ok(authoring.hwpx_authoring_search_hit);
  for (const key of [
    'hwpx_authoring_hit_dock_kept', 'hwpx_authoring_hit_no_properties',
    'hwpx_authoring_create_enabled', 'hwpx_authoring_create_changed_content',
    'hwpx_authoring_create_panel_closed', 'hwpx_authoring_undo_changed_content',
    'hwpx_authoring_undo_label_cleared', 'hwpx_authoring_undone_matches_source',
    'hwpx_authoring_redo_content_equals_create',
    'hwpx_authoring_undo2_content_equals_undo',
    'hwpx_authoring_rename_enter_armed', 'hwpx_authoring_mode_content_stable',
    'hwpx_authoring_min_window_ok', 'hwpx_authoring_font_scale_ok',
    'hwpx_authoring_font_scale_restored', 'hwpx_authoring_master_width_stable',
    'hwpx_authoring_close_asks', 'hwpx_authoring_closed',
    'hwpx_authoring_disposed',
  ]) assert.equal(authoring[key], true, key);
  for (const key of [
    'hwpx_authoring_impact_tab', 'hwpx_authoring_create_form_select',
    'hwpx_authoring_create_preview_flashed', 'hwpx_authoring_screen_on_after_close',
  ]) assert.equal(authoring[key], false, key);
  assert.equal(authoring.hwpx_authoring_create_submit_label, '필드로 만들기');
  assert.equal(authoring.hwpx_authoring_create_field_count, base + 1);
  assert.ok(authoring.hwpx_authoring_create_label.endsWith('필드로 만들기'));
  assert.equal(authoring.hwpx_authoring_create_crumb,
    `필드 · ${authoring.hwpx_authoring_create_new_field}`);
  assert.equal(authoring.hwpx_authoring_undo_field_count, base);
  assert.equal(authoring.hwpx_authoring_redo_field_count, base + 1);
  assert.ok(authoring.hwpx_authoring_rename_target);
  assert.equal(authoring.hwpx_authoring_rename_affected, 2);
  assert.equal(authoring.hwpx_authoring_rename_new_count, 2);
  assert.equal(authoring.hwpx_authoring_rename_old_count, 0);
  assert.equal(authoring.hwpx_authoring_rename_field_total, base);
  assert.equal(authoring.hwpx_authoring_rename_undo_old_count, 2);
  assert.equal(authoring.hwpx_authoring_rename_undo_new_count, 0);
}

function verifyHWPXGeometryAndKeyboard(receipt) {
  const authoring = receipt.editor_txt_band;
  assert.equal(authoring.hwpx_authoring_font_scale_skipped ?? null, null);
  assert.equal(authoring.hwpx_authoring_font_scale, 'larger');
  assert.equal(authoring.hwpx_authoring_font_scale_px, '24px');
  assert.deepEqual(authoring.hwpx_authoring_modes,
    ['document', 'structure', 'template']);
  assert.equal(authoring.hwpx_authoring_mode_dirty_after,
    authoring.hwpx_authoring_mode_dirty_before);
  assert.ok(authoring.hwpx_authoring_min_window_scroll_w <=
    authoring.hwpx_authoring_min_window_client_w);
  assert.ok(authoring.hwpx_authoring_font_scale_scroll_w <=
    authoring.hwpx_authoring_font_scale_client_w);
  for (const key of [
    'hwpx_kbd_outline', 'hwpx_kbd_field', 'hwpx_kbd_f2_focus',
    'hwpx_kbd_escape_closes', 'hwpx_kbd_iframe_input',
    'hwpx_kbd_iframe_panel_open', 'hwpx_kbd_iframe_escape_closes',
    'hwpx_kbd_iframe_f6_left',
  ]) assert.equal(authoring[key], true, key);
  assert.ok(authoring.hwpx_kbd_field_label.startsWith('필드 · 수요기관 · 사용 위치 2곳'));
  assert.ok(authoring.hwpx_kbd_escape_presses <= 2);
}

export function verifyNativeSelftest(receipt, identity, graph) {
  const probes = verifyReceiptIdentity(receipt, identity, graph);
  verifyReactAndPicker(receipt);
  verifyActionsAndPairing(receipt);
  verifyShellState(receipt);
  verifyModalAndGeometry(receipt);
  const base = verifyHWPXPreflight(receipt);
  verifyHWPXEdit(receipt, base);
  verifyHWPXGeometryAndKeyboard(receipt);
  verifyJobReceipt(receipt);
  verifyEditorReceipt(receipt);
  verifyWorkbenchReceipt(receipt);
  verifyEditorDetailReceipt(receipt);
  verifySurfaceReceipt(receipt);
  return { probes, artifact_id: identity.artifact_id };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length !== 4) {
      throw new Error('usage: verify_native_selftest.mjs RECEIPT IDENTITY');
    }
    const result = verifyNativeSelftest(read(process.argv[2]), read(process.argv[3]),
      read(path.join(root, 'tests/contracts/selftest-probe-graph.json')));
    process.stdout.write(`native WebView receipt verified: ${result.probes} probes\n`);
  } catch (error) { process.stderr.write(`${error.stack ?? error}\n`); process.exitCode = 1; }
}
