import assert from 'node:assert/strict';

function trueKeys(object, keys, owner) {
  for (const key of keys.split(' ')) assert.equal(object[key], true, owner + '.' + key);
}

function verifyEditorState(receipt) {
  const state = receipt.job_editmode;
  assert.ok(state.error == null);
  trueKeys(state, 'editor_screen_on job_screen_off nav_hidden back_shown foot_shown_new ' +
    'foot_shown_edit discard_shown_clean discard_disabled_clean save_disabled_clean ' +
    'discard_shown_dirty discard_enabled_dirty save_enabled_dirty ' +
    'ctx_hidden_when_voluntary ctx_shown back_btn nav_back_after_leave',
  'job_editmode');
  assert.deepEqual([state.wizard_steps, state.edit_tabs, state.edit_dirty_tab_marked],
    [3, 3, 1]);
  assert.match(state.dirty_head, /저장하지 않은 변경/);
  assert.equal(state.head_title, '공고서');
  assert.equal(state.name_input_in_head, false);
  assert.match(state.save_state, /저장됨/);
  assert.ok(!state.save_state.includes('r'));
  assert.equal(state.ctx_return_btn, false);
  assert.match(state.ctx_text, /실패한 행/);
  assert.match(state.ctx_text, /4 \/ 12/);
  assert.ok(!state.ctx_text.includes('열었습니다'));
}

function verifyBinding(receipt) {
  const binding = receipt.editor_binding;
  assert.ok(binding.error == null);
  assert.deepEqual(binding.head_cols,
    ['템플릿 필드', '데이터 열', '가공', '표시형', '미리보기']);
  assert.deepEqual(binding.slice_buttons, [
    { label: '+ 가공', disabled: false },
    { label: '1번째 글자부터 3글자', disabled: false },
    { label: '+ 가공', disabled: false },
    { label: '+ 가공', disabled: true },
  ]);
  const pop = binding.slice_pop;
  trueKeys(pop, 'inside attached focus_in_value', 'editor_binding.slice_pop');
  assert.deepEqual([pop.radios, pop.checked, pop.expanded, pop.rows, pop.summary],
    [9, 'chars', 'true', 3, '맞음 3행']);
  assert.equal(binding.slice_rows_geom.length, 9);
  for (const row of binding.slice_rows_geom) {
    assert.equal(row.inside, true);
    assert.ok(row.scroll <= row.client + 1);
    assert.equal(row.one_line, true);
  }
  assert.ok(binding.slice_inputs_geom.length > 0);
  assert.ok(binding.slice_inputs_geom.some(item => item.tag === 'select'));
  for (const item of binding.slice_inputs_geom) {
    const bound = item.tag === 'select' ? item.font_px * 10 : item.col_width / 2;
    assert.ok(item.width <= bound);
    assert.equal(item.flex_grow, '0');
  }
  assert.equal(binding.slice_preview_call, 'preview_slice:{"index":1,"sample":null}');
  assert.equal(binding.slice_propose_call,
    'propose_slice:{"index":1,"sample":0,"start":0,"end":13}');
  assert.equal(binding.slice_apply_call,
    'set_slice:{"index":1,"slice":{"mode":"split","delimiter":"-","index":1,"on_missing":"keep"}}');
  assert.equal(binding.slice_tag, '3/3행 맞음');
  trueKeys(binding, 'slice_closed slice_focus_back empty_select preview_none ' +
    'exact_badge_inside promote_disabled_after header_chips_gone type_column_gone ' +
    'confirm_checkbox_gone auto_revert_option revert_same_line', 'editor_binding');
  assert.match(binding.foot_text, /사용하지 않는 데이터 열 1개/);
  assert.deepEqual(binding.pills, ['자동 제안 2', '확인 필요 2', '고정값 0']);
  assert.equal(binding.promote_label, '제안 2건 모두 확인');
  assert.deepEqual(binding.badges, ['제안', '제안', '확인 필요', '확인 필요']);
  assert.deepEqual(binding.badge_disabled, [false, false, false, true]);
  assert.match(binding.badge_hint, /고정값/);
  assert.equal(binding.promote_call, 'confirm_suggested:{}');
  assert.deepEqual(binding.badges_after, ['확인', '확인', '확인 필요', '확인 필요']);
  assert.deepEqual([binding.exact_badge, binding.exact_pressed],
    ['자동확정 · 이름 일치', 'true']);
  assert.ok(binding.exact_select_width >= 40);
  assert.equal(binding.exact_cell_h, binding.src_cell_h_suggested);
  assert.equal(binding.promoted_label_after, '제안을 모두 확인했습니다');
  assert.ok(binding.pick_const.startsWith('set_display:'));
  assert.match(binding.pick_const, /"const"/);
  assert.ok(binding.pick_today.startsWith('set_display:'));
  assert.ok(!binding.option_values.includes('sp:blank'));
  assert.equal(binding.pick_column, 'set_source:{"index":3,"source":"수량"}');
  assert.equal(binding.sentinel_in_set_source, false);
  assert.equal(binding.badge_call, 'set_confirmed:{"index":0,"confirmed":true}');
  assert.deepEqual(binding.display_groups, ['텍스트', '날짜', '금액']);
  assert.equal(binding.pick_display, 'set_display:{"index":0,"type":"date","fmt":""}');
  assert.deepEqual([binding.step_next, binding.step_prev],
    ['step_preview:{"delta":1}', 'step_preview:{"delta":-1}']);
  assert.equal(binding.src_cell_h_manual, binding.src_cell_h_suggested);
  assert.equal(binding.src_cell_h_unselected, binding.src_cell_h_suggested);
}

function verifySave(receipt) {
  const save = receipt.editor_save_gate;
  assert.ok(save.error == null);
  trueKeys(save, 'save_present clean_disabled typing_enabled typing_discard_enabled ' +
    'rerender_keeps_enabled reverted_disabled reverted_discard_disabled ' +
    'pattern_present pattern_typing_enabled row_const_present row_clean_disabled ' +
    'row_typing_enabled row_reverted_disabled row_value_survives_push ' +
    'row_enabled_after_push gone_control_disables name_in_body name_hint_shown ' +
    'name_hint_gone_when_edited out_dir_readonly folder_settings_opens ' +
    'settings_closed_after save_and_open_present save_and_open_enabled ' +
    'save_before_prefer landed_on_job', 'editor_save_gate');
  assert.equal(save.name_in_head, false);
  assert.equal(save.derived_name_value, '공고서 · 대장');
  assert.ok(save.seq_example.endsWith('· 002 · 003'));
  assert.equal(save.out_dir_value, 'D:/문서/Results');
  assert.equal(save.out_dir_source, '설정한 저장 폴더');
  const notice = save.notice_channel;
  assert.deepEqual(notice.present,
    { template: true, binding: true, filename: true });
  trueKeys(notice, 'save_enabled matches_block_reason visible', 'editor_save_gate.notice');
  assert.equal(notice.inside_body, false);
  assert.equal(notice.alerts, 0);
}

export function verifyEditorDetailReceipt(receipt) {
  verifyEditorState(receipt);
  verifyBinding(receipt);
  verifySave(receipt);
}
