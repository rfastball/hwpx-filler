import assert from 'node:assert/strict';

function trueKeys(object, keys, owner) {
  for (const key of keys.split(' ')) assert.equal(object[key], true, `${owner}.${key}`);
}

function verifyTabAndDiscard(receipt) {
  const tab = receipt.editor_tab_autodiscard;
  assert.ok(tab.error == null);
  assert.equal(tab.why, '완료');
  assert.deepEqual(tab.calls, ['goto_section']);
  assert.deepEqual(tab.payload_keys, ['section']);
  assert.equal(tab.target_sent, 'filename');
  assert.equal(tab.choose_modal_open, false);
  assert.equal(tab.confirm_modal_open, false);

  const discard = receipt.editor_discard_immediate;
  assert.ok(discard.error == null);
  assert.equal(discard.why, '완료');
  trueKeys(discard, 'discard_enabled_on_typing name_node_stable name_node_connected ' +
    'name_focus_stable flushed_before_discard discard_disabled_after ' +
    'save_disabled_after discarded', 'editor_discard_immediate');
  assert.equal(discard.confirm_modal_open, false);
  assert.equal(discard.call_order, 'set_name,discard_patch');
  assert.equal(discard.name_value_after_discard, '공고서');
}

function verifyTxtBand(receipt) {
  const band = receipt.editor_txt_band;
  assert.ok(band.error == null);
  assert.equal(band.why, '완료');
  assert.deepEqual(band.bands, []);
  assert.equal(band.txt_pick, true);
  assert.equal(band.txt_media_pill, 'TXT');
  assert.equal(band.txt_tabs, 3);
  assert.ok(band.txt_step3_label.endsWith('이름·저장'));
  assert.equal(band.txt_name_input, true);
  assert.equal(band.txt_out_dir_row, false);
  assert.equal(band.txt_pattern_input, false);
  trueKeys(band, 'lintpad_trigger lintpad_mounted authoring_screen_on ' +
    'lintpad_content_editable lintpad_focusable lintpad_lint_arrived ' +
    'authoring_escape_retains authoring_document_mode authoring_template_mode ' +
    'authoring_close_asks lintpad_source_hidden lintpad_tag_caret_outside ' +
    'authoring_cancel_retains lintpad_disposed', 'editor_txt_band');
  assert.deepEqual([band.lintpad_marks_before, band.lintpad_field_marks,
    band.lintpad_marker_marks], [0, 1, 1]);
  assert.match(band.lintpad_diag_text, /닫는 마커가 없습니다/);

  assert.ok(band.kbd_error == null);
  trueKeys(band, 'kbd_outline_reached kbd_fields_view kbd_field_focused ' +
    'kbd_properties_focus kbd_rename_preview kbd_escape_reverts ' +
    'kbd_escape_keeps_panel kbd_escape_closes kbd_escape_focus_editor ' +
    'kbd_f2_focus kbd_dock_reached kbd_problems_tab kbd_problem_focus ' +
    'kbd_problems_selected kbd_problem_moved kbd_problem_dock_kept ' +
    'kbd_problem_no_properties kbd_toolbar_again kbd_dimmed_reached ' +
    'kbd_dimmed_aria kbd_dimmed_note kbd_dimmed_no_panel kbd_dimmed_focus_kept ' +
    'kbd_more_button kbd_more_menu kbd_back_button kbd_more_menu_closed ' +
    'kbd_back_restored kbd_back_focus_editor kbd_back_properties',
  'editor_txt_band.keyboard');
  assert.ok(band.kbd_problems_expected >= 1);
  assert.equal(band.kbd_problems_tab_label, `문제 ${band.kbd_problems_expected}`);
  assert.equal(band.kbd_dock_panels, 1);
  assert.equal(band.kbd_field_label, '필드 · 공고명 · 사용 위치 1곳');
  assert.equal(band.kbd_properties_target, band.kbd_field_label);
  assert.equal(band.kbd_name_described_by, 'authoring-properties-target');
  assert.equal(band.kbd_properties_context, '');
  assert.deepEqual([band.kbd_properties_command, band.kbd_f2_command],
    ['rename_field', 'rename_field']);
  assert.match(band.kbd_rename_preview_text, /‘공고제목’으로 변경됩니다/);
  assert.deepEqual([band.kbd_problem_severity, band.kbd_problem_category],
    ['오류', '구조']);
  assert.ok(band.kbd_problem_action.startsWith('원문으로 이동 · 오류 · 구조'));
  assert.equal(band.kbd_problem_expected_line, 1);
  assert.equal(band.kbd_problem_caret_line, 1);
  assert.equal(band.kbd_dimmed_note_text,
    '구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요.');
  assert.equal(band.kbd_dimmed_note_text, band.kbd_dimmed_title);
  assert.equal(band.kbd_back_expected_line, 0);
  assert.ok(band.kbd_back_expected.endsWith('행'));
  assert.ok(band.kbd_back_context.includes(band.kbd_back_expected));
  assert.equal(band.kbd_error_band, '');
  trueKeys(band, 'ime_no_preview ime_value_kept ime_focus_kept ime_caret_kept ' +
    'ime_panel_kept', 'editor_txt_band.ime');
  assert.equal(band.ime_error_band, '');
  assert.equal(band.ime_value_after_end, '공고명수');
}

function verifyA11y(receipt) {
  const band = receipt.editor_txt_band;
  assert.ok(band.a11y_error == null);
  trueKeys(band, 'a11y_new_tab a11y_tabs_reached a11y_tabs_entry a11y_tabs_left ' +
    'a11y_tabs_right a11y_tabs_home a11y_tabs_enter a11y_tabs_end ' +
    'a11y_tabs_delete_closed a11y_tabs_delete_focus a11y_toolbar_reached ' +
    'a11y_toolbar_single_stop a11y_toolbar_right a11y_toolbar_end ' +
    'a11y_toolbar_wrap a11y_toolbar_dimmed_in_order a11y_dock_reached ' +
    'a11y_dock_entry a11y_dock_search a11y_dock_enter_focus ' +
    'a11y_dock_escape_closed a11y_dock_escape_return a11y_tree_reached ' +
    'a11y_tree_entry a11y_tree_field a11y_tree_current a11y_menu_open ' +
    'a11y_menu_down a11y_menu_end a11y_menu_home a11y_menu_in_window ' +
    'a11y_menu_escape_closed a11y_menu_escape_return a11y_menu_no_disabled ' +
    'a11y_palette_open a11y_palette_dock_kept a11y_palette_arrow ' +
    'a11y_palette_escape_closed a11y_palette_escape_return ' +
    'a11y_bottom_menu_open a11y_bottom_menu_in_window',
  'editor_txt_band.a11y');
  assert.ok(band.a11y_steps.length >= 15);
  for (const item of band.a11y_toolbar_dimmed) {
    assert.ok(['create_field', 'create_slot', 'create_option'].includes(item));
  }
  assert.equal(band.a11y_toolbar_visits.at(-1), 'trial');
  assert.equal(band.a11y_error_band, '');
}

export function verifyEditorReceipt(receipt) {
  verifyTabAndDiscard(receipt);
  verifyTxtBand(receipt);
  verifyA11y(receipt);
}
