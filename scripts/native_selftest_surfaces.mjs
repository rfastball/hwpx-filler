import assert from 'node:assert/strict';

function trueKeys(object, keys, owner) {
  for (const key of keys.split(' ')) assert.equal(object[key], true, owner + '.' + key);
}

function verifyLibrary(receipt) {
  const library = receipt.editor_lib_manage;
  assert.ok(library.error == null);
  assert.deepEqual(library.toolbar, [true, false, false, true]);
  trueKeys(library, 'retired_folder_import refresh_compact refresh_locked ' +
    'refresh_reenabled refresh_motion refresh_completed refresh_restored ' +
    'detail_always_available raw_more_visible partial_more_visible fill_warn ' +
    'result_line result_in_left_column band_caption gate_zone ' +
    'template_folder_single template_folder_visible menu_shown menu_closed ' +
    'detail_item_visible sheet_open sheet_fields_table slot_rename_visible ' +
    'slot_band_verb_visible slot_band_verb_targets_file slot_prompt_shown ' +
    'slot_notice_inline slot_notice_not_behind_scrim sheet_result_inside ' +
    'sheet_closed', 'editor_lib_manage');
  assert.deepEqual([library.grp_heads, library.rows_visible, library.grp_more,
    library.row_more, library.assign_chips, library.slot_rows,
    library.flat_heads, library.flat_rows], [0, 7, 0, 7, 0, 1, 0, 1]);
  assert.deepEqual(library.retired_zones,
    { slots_band: true, session_slot_summary: true, file_chip: true,
      schema_table: true });
  assert.deepEqual(library.template_folder_calls, [['open', 'C:/lib']]);
  assert.deepEqual(library.hwpx_menu_items, ['edit', 'act:compile', 'detail']);
  assert.deepEqual(library.partial_menu_items, library.hwpx_menu_items);
  assert.deepEqual(library.compiled_menu_items, ['edit', 'detail']);
  assert.deepEqual(library.txt_menu_items, ['edit', 'detail']);
  assert.deepEqual(library.txt_error_menu_items, ['detail']);
  assert.deepEqual(library.detail_dispatch, [['tpl', 'review', 'C:/lib/구간.hwpx']]);
  assert.deepEqual(library.sheet_field_names, ['계약명', '계약일']);
  assert.deepEqual(library.sheet_verbs, ['detail-edit']);
  assert.deepEqual(library.slot_verbs, [true, true, true]);
  assert.equal(library.slot_prompt_value, '특약 사항');
  assert.deepEqual(library.slot_dispatch,
    [['tpl', 'slot_rename', 'C:/lib/구간.hwpx', '특약', '특약 사항']]);
}

function verifyMilestone(receipt) {
  const h = receipt.milestone_h_wave1;
  for (const [role, fontSize] of [
    ['screen', '19px'], ['section', '15px'], ['zone', '13px'],
  ]) {
    assert.equal(h.headings[role].font_size, fontSize);
    assert.equal(h.headings[role].font_weight, '700');
  }
  assert.equal(h.job_step_badges, 0);
  assert.deepEqual(h.job_steps, [
    '현재 데이터', '생성 결과', '시작하기', '이 데이터에 사용할 문서', '생성 준비',
  ]);
  assert.ok(h.selected_card && Object.keys(h.selected_card).length > 0);
  for (const color of [h.selected_card.border_left, h.selected_card.background,
    h.card_base.background, h.disabled_primary.background,
    h.enabled_primary.background]) {
    assert.equal(typeof color, 'string');
    assert.ok(color.length > 0);
  }
  assert.notEqual(h.selected_card.border_left, 'rgba(0, 0, 0, 0)');
  assert.notEqual(h.selected_card.background, h.card_base.background);
  assert.notEqual(h.disabled_primary.background, h.enabled_primary.background);
  assert.equal(h.disabled_primary.opacity, '1');
  assert.ok(h.pathtrack.count >= 2);
  trueKeys(h.pathtrack, 'titled svg', 'milestone_h_wave1.pathtrack');
  for (const name of h.pathtrack.names) {
    assert.ok(['열기', '폴더에서 보기', '경로 복사'].includes(name));
  }
  assert.equal(h.scroll.overflow_y, 'auto');
  assert.match(h.scroll.gutter, /stable/);
  assert.match(h.scroll.overscroll, /contain/);
  assert.equal(h.scroll.sticky_position, 'sticky');
  assert.ok(h.scroll.scroll_top > 0);
  assert.equal(h.scroll.sticky_holds, true);

}

function verifyOverlay(receipt) {
  const overlay = receipt.milestone_h_overlay;
  assert.ok(overlay.error == null);
  assert.equal(overlay.pending, false);
  trueKeys(overlay, 'overlay_root_direct overlay_children_owned drag_closed ' +
    'click_after_drag click_after_right focusout_closed scroll_closed ' +
    'close_all_closed modal_closed_popover z_order ime_escape_kept_open ' +
    'exit_blocks_pointer menu_trigger_restored escape_one_layer',
  'milestone_h_overlay');
  assert.deepEqual(overlay.scrollbar, {
    width: '8px', button_display: 'none', button_width: '0px', button_height: '0px',
  });
  assert.equal(overlay.sticky_material.position, 'sticky');
  assert.match(overlay.sticky_material.backdrop, /blur\(14px\)/);
  const card = overlay.workcard;
  assert.equal(card.overflow_y, 'auto');
  assert.deepEqual([card.max_height, card.flex_grow], ['none', '1']);
  assert.match(card.font_family, /GulimChe|굴림체/);
  assert.deepEqual(card.dot_hit, ['24px', '24px']);
  assert.deepEqual(card.dot_mark, ['14px', '14px']);
  assert.equal(card.dots_overflow, 'auto');
  const popover = overlay.popover_place;
  assert.equal(popover.placement, 'top');
  assert.equal(popover.in_viewport, true);
  assert.ok(popover.origin.endsWith(' bottom'));
  assert.equal(popover.radius, '12px');
  assert.equal(typeof popover.shadow, 'string');
  assert.ok(popover.shadow.length > 0);
  assert.notEqual(popover.shadow, 'none');
  assert.equal(overlay.modal_focus_in, 'promptModalInput');
  const short = overlay.short_viewport;
  assert.ok(short.viewport <= 600);
  assert.ok(short.height <= short.viewport - 32);
  trueKeys(short, 'scrollable actions_reachable', 'milestone_h_overlay.short_viewport');
}

function verifyPicker(receipt) {
  const picker = receipt.editor_lib;
  assert.ok(picker.error == null);
  assert.deepEqual([picker.grp_heads, picker.tpl_items, picker.dat_items], [0, 3, 2]);
  trueKeys(picker, 'import_btn browse_btn blocked_shown blocked_reason ' +
    'blocked_not_draggable drag_over_accepted drag_target_marked ' +
    'drag_target_cleared drop_matches_click blocked_notice wire_live ' +
    'cta_enabled center_cta_absent pin_btn manage_verb_present ' +
    'dat_detail_item_visible pool_sheet_open pool_sheet_closed ' +
    'half_cta_disabled', 'editor_lib');
  assert.equal(picker.filter_notice, false);
  assert.equal(picker.fname_ellipsis, 'ellipsis');
  assert.deepEqual(picker.click_calls, [
    ['editor', 'use_library_template'],
    ['editor', 'mapping_reset_stakes'],
    ['editor', 'use_pool_data'],
  ]);
  assert.equal(picker.drag_payload, 'tpl:c.hwpx');
  assert.deepEqual(picker.sheet_reorder, {
    calls: [
      ['pool', 'reorder_sheets', { key: 'sheet-book', sheets: ['B', 'C', 'A'] }],
      ['pool', 'reorder_sheets', { key: 'sheet-book', sheets: ['B', 'A', 'C'] }],
    ],
    dragAccepted: true, keyAccepted: true, focusWhileSaving: true,
    focusAfterSaving: true, markerCleared: true,
  });
  assert.deepEqual([picker.same_side_drop_calls, picker.blocked_click_calls], [0, 0]);
  for (const phrase of ['a.hwpx ⟷ 7월목록.xlsx', '필드 12개 · 열 18개',
    '자동 연결 10', '확인 필요 2']) assert.ok(picker.card_text.includes(phrase));
  for (const phrase of ['시트: 물품', '헤더 1행', '12행', '사용 중']) {
    assert.ok(picker.current_restated.includes(phrase));
  }
  assert.deepEqual([picker.pool_current_marked, picker.reselect_calls,
    picker.reselect_keeps_mark, picker.manage_verb_calls], [1, 0, 1, 1]);
  assert.deepEqual(picker.dat_menu_items, ['act:archive', 'reveal', 'detail']);
  assert.deepEqual(picker.dat_detail_dispatch, [['pool', 'review', 'd1']]);
  assert.equal(picker.pool_sheet_columns, 3);
  assert.deepEqual(picker.pool_sheet_column_names, ['공고명', '금액', '기관']);
  assert.match(picker.pool_sheet_summary, /열 3개/);
  assert.match(picker.pool_sheet_facts, /시트: 물품/);
  assert.match(picker.pool_sheet_facts, /헤더 2행/);
  assert.deepEqual(picker.pool_sheet_verbs, ['detail-act:archive', 'detail-reveal']);
  assert.match(picker.half_block_reason, /오른쪽에서 데이터를 고르세요/);
}

export function verifySurfaceReceipt(receipt) {
  verifyLibrary(receipt);
  verifyMilestone(receipt);
  verifyOverlay(receipt);
  verifyPicker(receipt);
}
