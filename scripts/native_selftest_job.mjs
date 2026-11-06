import assert from 'node:assert/strict';

function trueKeys(object, keys, owner) {
  for (const key of keys.split(' ')) assert.equal(object[key], true, `${owner}.${key}`);
}

function verifyLegacyMirror(receipt) {
  const mirror = receipt.job_mirror;
  assert.ok(mirror.error == null);
  assert.equal(mirror.full_cell_title, '전산장비');
  trueKeys(mirror, 'mirror_host_gone out_dir_line_gone mirror_line_gone restate_gone ' +
    'mirror_preview_exit_gone mirror_review_flag_gone', 'job_mirror');

}

function verifyJobResult(receipt) {
  const result = receipt.job_result;
  assert.ok(result.error == null);
  trueKeys(result, 'run_caption_visible_without_folder shown fail_row fail_identity ' +
    'undiagnosed failed_sel_shown rowless_recovery_shown rowless_no_fake_rows ' +
    'evidence_shown evidence_open_survives_rerender stale_shown alive_after_stale ' +
    'renamed_keeps_result renamed_rename_shown renamed_failedsel_shown ' +
    'switch_resets_result selection_change_keeps_result selection_change_demotes ' +
    'data_swap_label_unchanged data_swap_resets_result foreign_rename_hidden ' +
    'foreign_failedsel_hidden foreign_evidence_alive foreign_stale_names_owner ' +
    'busy_lock_declared folder_hidden_while_running folder_shown_on_result ' +
    'closed idle_zone_hidden runlog_absent', 'job_result');
  assert.equal(result.state, 'partiallyCompleted');
  assert.equal(result.level, 'danger');
  assert.match(result.title, /2개 성공/);
  assert.match(result.failed_sel_label, /1건만 선택/);
  assert.match(result.rowless_recovery_label, /3건만 선택/);
  assert.ok(['jobGenBtn', 'scr-job'].includes(result.close_focus));
  assert.equal(result.reject_btn_disabled, false);
  assert.equal(result.reject_state, 'rejected');
  assert.match(result.reject_text, /최소 1건/);
  assert.equal(result.reject_alerts, 0);
  assert.equal(result.refusal_alerts.length, 1);
  assert.match(result.refusal_alerts[0], /다시 만들 실패 건이 남아 있지 않습니다/);

}

function verifyArtifact(receipt) {
  const artifact = receipt.job_result.artifact;
  trueKeys(artifact, 'docs_shown doc_visible open_btn_visible sheet_shown ' +
    'absent_save_disabled mismatch_differs_from_absent content_requested ' +
    'observed_doc_hidden text_projection_absent observed_save_enabled ' +
    'sheet_closed sheet_host_hidden', 'job_result.artifact');
  assert.equal(artifact.docs_rows, 2);
  assert.match(artifact.doc_text, /공고서-001\.hwpx/);
  assert.match(artifact.doc_text, /새 파일/);
  assert.deepEqual(artifact.doc_track_acts, ['reveal']);
  assert.ok(artifact.open_dispatches.includes('job/artifact_open'));
  assert.equal(artifact.absent_status, 'ARTIFACT_NOT_IN_SESSION');
  assert.ok(artifact.absent_title && artifact.absent_title !== '(자리 없음)');
  assert.match(artifact.mismatch_detail, /안착 기록과 다르다/);
  assert.equal(artifact.observed_doc_state, 'failed');
  assert.equal(artifact.render_failed_status, 'ARTIFACT_FILE_MISSING');
  assert.ok(artifact.render_failed_title && artifact.render_failed_title !== '(자리 없음)');
  assert.ok(artifact.render_failed_detail);
  assert.ok(artifact.close_dispatches.includes('job/artifact_close'));
  assert.equal(artifact.close_focus_target_state, 'ready');

}

function verifyDataFirst(receipt) {
  const first = receipt.job_data_first;
  assert.ok(first.error == null);
  trueKeys(first, 'zones_shown actionbar_shown show_all_absent cands_row_shown ' +
    'cand_exit gen_disabled action_name_empty', 'job_data_first');
  assert.ok(Math.abs(first.actionbar_plane) <= 1);
  assert.ok(Math.abs(first.actionbar_plane_empty_note) <= 1);
  assert.ok(first.cap_actions);
  assert.equal(first.cap_actions.display, 'flex');
  assert.ok(Math.abs(first.cap_actions.far_edge) <= 1);
  assert.doesNotMatch(first.sel_count_plain, /표시/);
  assert.equal(first.cand_buttons, 2);
  assert.equal(first.cand_disabled_chips, 0);
  assert.match(first.cand_more_text, /2건/);
  assert.match(first.cand_more_text, /1건/);
  assert.match(first.gate_text, /문서 작업을 선택하세요/);
  assert.deepEqual(first.tbl_rows_order, ['1', '0']);
  assert.deepEqual(first.cand_order, ['공고서', '계약서']);
  assert.deepEqual(first.fav_pressed, ['true', 'false']);
  assert.equal(first.suggested_marks, 1);
  assert.equal(first.suggested_dashed, 'dashed');
  assert.match(first.more_text, /2건/);
  assert.equal(Object.hasOwn(first, 'last_run_text'), false);
  assert.deepEqual(first.cand_sec_caps, ['HWPX 문서 생성', '온나라 기안 검토·복사']);
  assert.deepEqual(first.cand_mode_texts, ['HWPX 생성', '온나라 기안']);
  assert.equal(first.fav_focus_restored, 'kept');
  assert.equal(first.fav_sync_sends, 0);
  assert.equal(first.fav_intents, '[]');
  assert.equal(JSON.parse(first.fav_chain).inflight, 1);
  assert.deepEqual(JSON.parse(first.fav_order),
    [false, true, true, false, true, false]);
  const refusals = JSON.parse(first.fav_refusal_alerts);
  assert.ok(refusals.length && refusals.every(line => line.includes('실패 시늉')));

  assert.equal(first.browse_open, true);
  assert.deepEqual(first.browse_tabs, ['사용 가능 7/false', '확인 필요 1/true']);
  assert.equal(first.browse_rows.length, 1);
  assert.ok(first.browse_rows[0].startsWith('견적서'));
  assert.match(first.browse_rows[0], /없는 열: 담당자/);
  assert.match(first.browse_note, /2건/);
  trueKeys(first, 'browse_focus_is_query browse_query_node_stable ' +
    'browse_query_node_connected browse_query_focus_stable browse_query_focus_left ' +
    'browse_sheet_closed', 'job_data_first');
  assert.equal(first.browse_query_kept, '견적요청');
  assert.equal(first.browse_query_settled, '견적');
  assert.equal(first.browse_tab_focus, 'jobBrowseTab-available');
  assert.equal(first.browse_close_focus, 'jobBrowseOpen');
  assert.equal(first.browse_pick_focus, `jobCand-${encodeURIComponent('공고서')}`);

}

function verifyLayoutAndStrip(receipt) {
  const mirror = receipt.job_mirror;
  const sheet = receipt.data_sheet;
  assert.ok(sheet.error == null);
  trueKeys(sheet, 'moved first_sticky restored foot_shown_in_sheet', 'data_sheet');
  assert.equal(mirror.edit_takes_over_screen, true);
  assert.equal(mirror.job_grid_wide.split(/\s+/).length, 2);
  assert.ok(receipt.job_density_narrow.panel <= 900);
  assert.equal(receipt.job_density_narrow.columns.split(/\s+/).length, 1);

  assert.equal(mirror.tbl_rows, 1);
  assert.equal(mirror.tbl_mark, '전산');
  assert.equal(mirror.ficos, 2);
  assert.match(mirror.chips_text, /「전산」/);
  trueKeys(mirror, 'branch_prune strip_shown strip_unsel', 'job_mirror');
  for (const label of ['열 조건', '가지', '선택']) {
    assert.ok(mirror.filter_role_labels.includes(label));
  }
  assert.equal(typeof mirror.definition_bg, 'string');
  assert.equal(typeof mirror.branch_bg, 'string');
  assert.notEqual(mirror.definition_bg, mirror.branch_bg);
  assert.equal(mirror.branch_border_style, 'solid');
  assert.equal(mirror.strip_bg, mirror.branch_bg);
  assert.match(mirror.strip_text, /1행/);
  assert.match(mirror.strip_text, /doc-002\.hwpx/);

}

function verifyPresets(receipt) {
  const mirror = receipt.job_mirror;
  assert.equal(mirror.preset_chips, 3);
  assert.deepEqual(mirror.preset_pressed, ['true', 'false', 'true']);
  assert.deepEqual(mirror.preset_cluster, {
    label: '추정가격', chips: ['소기업', '중소기업'], border: 'solid',
  });
  trueKeys(mirror, 'preset_single_outside preset_ctx_closed filter_new_shown ' +
    'filter_save_gone', 'job_mirror');
  assert.equal(mirror.preset_warn_aria_disabled, 'true');
  assert.equal(mirror.preset_warn_title, '이 필터의 열이 지금 데이터에 없습니다: 추정가격');
  assert.equal(mirror.preset_on_title, "소기업: 추정가격 < '100,000,000'");
  assert.equal(typeof mirror.preset_on_bg, 'string');
  assert.equal(typeof mirror.preset_off_bg, 'string');
  assert.notEqual(mirror.preset_on_bg, mirror.preset_off_bg);
  assert.deepEqual(mirror.preset_menu_buttons, ['소기업', '전산']);
  assert.ok(mirror.preset_off_reserve >= 0 && mirror.preset_off_reserve <= 2);
  assert.deepEqual(mirror.preset_ctx_menu,
    { role: 'menu', items: ['고치기', '삭제'], focus_first: true, shown: true });
  assert.equal(mirror.preset_menu_expanded, 'true');
  assert.equal(mirror.preset_toggle_sent, '["소기업","모두 보기"]');

}

function verifyFilterGeometry(receipt) {
  const mirror = receipt.job_mirror;
  assert.deepEqual(mirror.head_fico, [
    ['공고명', true, "필터 '전산'"], ['금액', true, "금액 ≥ '1,000,000'"],
  ]);
  const show = mirror.show_all;
  assert.ok(show);
  assert.equal(show.text, '모두 보기');
  assert.equal(show.after_count, true);
  assert.equal(show.count_text, '선택 2/2 · 표시 1/2');
  assert.equal(show.border, true);
  assert.equal(show.underline, 'underline');
  assert.equal(mirror.filter_clear_gone, true);
  for (const key of ['chip_row', 'chip_row_narrow']) {
    const row = mirror[key];
    assert.equal(row.display, 'grid');
    assert.ok(row.lines >= 2);
    trueKeys(row, 'hanging after_caption plus_outside_area long_name_clipped long_title',
      `job_mirror.${key}`);
    assert.ok(Math.abs(row.plus_top) <= 1);
    assert.ok(row.plus_right >= 0 && row.plus_right <= 1);
    assert.deepEqual(row.heights, [28]);
  }
  const corner = mirror.table_expand;
  assert.equal(corner.in_host, true);
  assert.deepEqual([corner.label, corner.title, corner.text],
    ['표 크게 열기', '표 크게 열기', '']);
  trueKeys(corner, 'scroll_width scrolled', 'job_mirror.table_expand');
  assert.deepEqual(corner.before, corner.after);
  assert.equal(corner.after.on_top, true);
  assert.ok(corner.after.right >= 0 && corner.after.right <= 12);
  assert.ok(corner.after.top >= 0 && corner.after.top <= 4);

}

function verifyFilterBuilder(receipt) {
  const mirror = receipt.job_mirror;
  assert.equal(mirror.builder_open, true);
  assert.equal(mirror.builder_title, '필터 만들기');
  assert.equal(mirror.builder_note, '열 머리 조건에서 채움');
  assert.deepEqual(mirror.builder_cards, ['금액', '전체 열 검색']);
  assert.deepEqual(mirror.builder_and, ['그리고', '그리고']);
  assert.equal(mirror.builder_count, '1행 / 2행');
  assert.equal(mirror.builder_meter, 'scaleX(0.5)');
  assert.equal(mirror.builder_name_placeholder, "금액 ≥ '1,000,000'");
  assert.equal(mirror.builder_count_sent, '{"op":"ge","operand":"1,000,000"}');
  assert.equal(mirror.builder_operand_align, 'right');
  assert.equal(mirror.builder_focus_picker, true);
  assert.equal(mirror.picker_role, 'combobox');
  assert.deepEqual([mirror.picker_expanded, mirror.picker_query_sent], ['true', '공고']);
  assert.deepEqual(mirror.picker_options, ['공고명']);
  assert.equal(mirror.picker_mark, '공고');
  assert.deepEqual(mirror.picker_added, ['금액', '전체 열 검색', '공고명']);
  trueKeys(mirror, 'picker_focus_in_new_card picker_fits_viewport picker_anchored ' +
    'builder_anchored builder_fits_viewport builder_closed_on_escape ' +
    'builder_focus_returned edit_delete edit_closed_outside', 'job_mirror');
  assert.ok(mirror.builder_width >= 440 && mirror.builder_width <= 470);
  assert.deepEqual([mirror.edit_title, mirror.edit_name], ['필터 고치기', '소기업']);

}

function verifyTableAndGuard(receipt) {
  const mirror = receipt.job_mirror;
  assert.equal(mirror.row_role, null);
  assert.equal(mirror.row_selected, 'true');
  assert.equal(mirror.row_checkbox, true);
  assert.equal(mirror.row_doccell_display, 'flex');
  assert.equal(mirror.doccol_row_names, 0);
  assert.equal(mirror.head_doccol_text, '');
  assert.equal(mirror.head_selall, true);
  assert.equal(mirror.amount_align, 'right');
  assert.match(mirror.amount_nums, /tabular-nums/);
  trueKeys(mirror, 'row_optimistic_off row_optimistic_on panel_shell_immediate ' +
    'panel_hidden data_guard_wired reapply_shown reapply_hidden', 'job_mirror');
  assert.deepEqual(mirror.row_toggle_values, [false, true]);
  for (const phrase of ['직접 선택 3행', '정의 매치 2', '정의 밖 1', '데이터를 바꾸면',
    '필터 정의(2개 조건)', '직전 필터 재적용']) assert.ok(mirror.guard_body.includes(phrase));
  assert.ok(!mirror.guard_body.includes('빈 값 확인'));
  assert.ok(!mirror.guard_body_minimal.includes('빈 값 확인'));
  assert.ok(!mirror.guard_body_minimal.includes('직전 필터 재적용'));
  assert.match(mirror.reapply_title, /\(공고명\) 포함 「전산」/);

}

function verifyJobExit(receipt) {
  const mirror = receipt.job_mirror;
  const inherited = receipt.job_inherited;
  assert.ok(inherited.error == null);
  assert.equal(inherited.no_data_exit_with_data, false);
  trueKeys(inherited, 'opening_marker_immediate no_data_exit_shown no_data_exit_target ' +
    'no_data_controls_hidden no_data_instruction_shown', 'job_inherited');

  const active = receipt.job_active_card;
  assert.ok(active.error == null);
  assert.deepEqual([active.action_name, active.active_tpl, active.menu_btn_count],
    ['공고서', '공고서.hwpx', 1]);
  trueKeys(active, 'menu_btn_in_active menu_open menu_closed conn_quiet_when_ok ' +
    'cands_hidden_when_no_data relink_visible_no_data warn_redirect_modal',
  'job_active_card');
  assert.deepEqual(active.menu_items, [
    'open:C:\\t\\공고서.hwpx:열기', 'reveal:C:\\t\\공고서.hwpx:폴더에서 보기',
  ]);
  assert.equal(active.warn_conn, '템플릿 없음');
  assert.equal(active.cand_cards_when_no_data, 0);
  assert.equal(active.conn_text_no_data, '템플릿 없음');
  assert.match(active.warn_modal_body, /선택/);
  assert.match(active.warn_modal_body, /다시 연결/);
  assert.deepEqual(JSON.parse(active.warn_click_sends), []);
  assert.equal(mirror.legacy_banner_gone, true);
  for (const phrase of ['10건을 생성합니다', '3건이 기존 파일을 덮어씁니다',
    '나머지 7건은 새 파일', 'a.hwpx', 'b.hwpx', '외 5개']) {
    assert.ok(mirror.ow_body.includes(phrase));
  }
}

export function verifyJobReceipt(receipt) {
  verifyLegacyMirror(receipt);
  verifyJobResult(receipt);
  verifyArtifact(receipt);
  verifyDataFirst(receipt);
  verifyLayoutAndStrip(receipt);
  verifyPresets(receipt);
  verifyFilterGeometry(receipt);
  verifyFilterBuilder(receipt);
  verifyTableAndGuard(receipt);
  verifyJobExit(receipt);
}
