import assert from 'node:assert/strict';

function verifyPreferences(receipt) {
  const theme = receipt.theme_persist;
  assert.equal(theme.data_theme, null);
  assert.equal(theme.a_card, '#ffffff');
  const personalization = receipt.personalization_persist;
  assert.deepEqual([personalization.font_scale, personalization.root_px,
    personalization.master_width, personalization.splitters],
  ['normal', '16px', 240, 0]);
  const immersive = ['scr-editor', 'scr-workbench'].includes(personalization.active_screen);
  assert.equal(personalization.immersive_body, immersive);
  assert.equal(personalization.topbar_h, immersive ? 44 : 64);
  assert.equal(personalization.body_overflow, false);
  assert.equal(personalization.selected_text, '선택 가능한 본문');
}

function verifyWorkbench(receipt) {
  const workbench = receipt.workbench;
  assert.ok(workbench.error == null);
  assert.equal(workbench.screen_on, true);
  assert.equal(workbench.nav_hidden, true);
  assert.equal(workbench.title, '발주요청_기안');
  assert.deepEqual([workbench.position, workbench.copied], ['1 / 3', '1 / 3']);
  assert.match(workbench.revision, /연결 r4/);
  assert.match(workbench.review, /다시 확인/);
  assert.equal(workbench.map_panel, false);
  assert.deepEqual([workbench.binding_link, workbench.template_link],
    ['연결 편집', '템플릿 편집']);
  assert.equal(workbench.template_link_absent, true);
  assert.ok(workbench.card_width_ratio >= 0.95);
  assert.deepEqual([
    workbench.card_fill, workbench.card_blank, workbench.card_blank_label,
    workbench.card_declared, workbench.card_editable, workbench.copy_with_holes,
  ], [
    1, 1, '〈빈 값〉', '〈비워 둠〉', 'true', {
      calls: [['copy_precheck', {}], ['copy_clipboard', 'workbench', 'copy-probe']],
      confirmation_open: false, blank_marker: 1,
    },
  ]);
  assert.equal(workbench.lint_shown, true);
  assert.equal(workbench.lint_action, 'on:전각으로 바꾸기');
  assert.equal(workbench.font_value, 'malgun');
  assert.ok(workbench.font_width < 180);
  assert.deepEqual(workbench.dots, ['7행 · 작업 중 · 다시 확인 필요', '4행 · 대기']);
  assert.equal(workbench.dots_role, 'group');
  assert.equal(workbench.dot_button_role, null);
  assert.equal(workbench.dot_tabstops, 1);
  assert.equal(workbench.dot_arrow_focus, '1');
  assert.deepEqual(workbench.view_pressed, ['true', 'false']);
  assert.equal(workbench.view_colors_differ, true);
  assert.equal(workbench.large_queue.count, 500);
  assert.equal(workbench.large_queue.scrolls, true);
  assert.ok(workbench.large_queue.height <= 97);
  assert.equal(workbench.large_queue.current_visible, true);
  assert.equal(workbench.large_queue.preview_clear, true);
  assert.equal(workbench.large_queue.tabstops, 1);
  assert.deepEqual([workbench.prev_disabled, workbench.next_disabled], [false, true]);
  assert.equal(workbench.card_tokens, 3);
  assert.equal(workbench.token_role, null);
  assert.deepEqual(workbench.edit, {
    hole_gone: true, filled_marks: 2, sent_before_pause: 0,
    sent_after_pause: ['set_card_text:{"index":0,"text":"수신: 회계과\\n비고: 없음\\n단위: "}'],
    sent_while_composing: 1,
    sent_after_compose: '{"index":0,"text":"수신: 회계과\\n비고: 없음함\\n단위: "}',
    focus_kept: true,
  });
  assert.ok(workbench.narrow_larger.width <= 760);
  assert.ok(workbench.narrow_larger.body_height > 100);
  assert.equal(workbench.narrow_larger.scrolls, true);
  assert.equal(workbench.narrow_larger.card_reachable, true);
  assert.deepEqual([workbench.degen_prev, workbench.degen_adv], ['none', 'none']);
  assert.deepEqual(workbench.leave_calls, ['leave_guard', 'close']);
  assert.equal(workbench.landed, true);
}

export function verifyWorkbenchReceipt(receipt) {
  verifyPreferences(receipt);
  verifyWorkbench(receipt);
}
