# 코드에서 생성한 런타임 참조

> 생성물: `node scripts/docs_contract.mjs --write`. 직접 편집하지 않는다.
> 선언·등록 목록이다. 채널이나 메서드가 있다는 사실은 사용자 기능의 노출을 뜻하지 않는다.

## 환경 선언

| 항목 | 선언 | 원천 |
|---|---|---|
| 제품 버전 | `0.15.0` | [crates/hwpx-desktop/Cargo.toml](../../crates/hwpx-desktop/Cargo.toml) |
| Node pin | `24.18.1` | [.node-version](../../.node-version) |
| Node engine | `24.18.1` | [package.json](../../package.json) |
| npm engine | `11.16.0` | [package.json](../../package.json) |
| package manager | `npm@11.16.0` | [package.json](../../package.json) |
| Rust pin | `1.93.1` | [rust-toolchain.toml](../../rust-toolchain.toml) |
| Rust components | `clippy, rustfmt, llvm-tools` | [rust-toolchain.toml](../../rust-toolchain.toml) |
| Cargo workspace | `crates/hwpx-core, crates/hwpx-filler, crates/hwpx-artifact, crates/hwpx-desktop` | [Cargo.toml](../../Cargo.toml) |

## 진입점

| 종류 | 명령 | 대상 |
|---|---|---|
| Cargo binary | `hwpxfiller` | [src/bin/hwpxfiller.rs](../../crates/hwpx-desktop/src/bin/hwpxfiller.rs) |
| Cargo binary | `documentnarmi` | [src/bin/documentnarmi.rs](../../crates/hwpx-desktop/src/bin/documentnarmi.rs) |

Rust CLI:

```powershell
.\run-filler.ps1 -Cli --template T.hwpx --data data.csv --out out --ledger
cargo run --locked -p hwpx-desktop --bin hwpxfiller --no-default-features -- --template T.hwpx --fields
cargo run --locked -p hwpx-desktop --bin hwpxfiller --no-default-features -- schema T.hwpx --out schema.json
cargo run --locked -p hwpx-desktop --bin hwpxfiller --no-default-features -- drift OLD.hwpx NEW.hwpx
```

## 품질 CI

원천: [quality.yml](../../.github/workflows/quality.yml). 실제 설정의 등록 목록이다.

- Jobs: `sealed-web`, `static`, `rust-coverage`, `windows-native`, `browser-render`, `live-webview2`, `distribution-webview2`, `rust-kernel`, `quality-gate`
- `quality-gate.needs`: `sealed-web`, `static`, `rust-coverage`, `windows-native`, `browser-render`, `live-webview2`, `distribution-webview2`, `rust-kernel`

## Native host 공개 메서드

원천: [host_contract.json](../../crates/hwpx-desktop/src/host_contract.json).
직접 호출의 인자·선택 여부를 Rust 라우터도 같은 표에서 검증한다.

| 메서드 | 인자 |
|---|---|
| `initial` | `screen` |
| `dispatch` | `screen, action, payload = None` |
| `pick_data_file` | `screen` |
| `open_authoring_document` | `path = None, as_template = None` |
| `save_authoring_document` | `session_id, revision` |
| `authoring_cases_file` | `session_id, action` |
| `export_authoring_result` | `session_id, revision` |
| `load_data_sheet` | `screen, path, sheet, confirmation = None` |
| `import_template_file` | `screen` |
| `copy_clipboard` | `screen, token = None` |
| `pick_output_folder` | `screen` |
| `pick_templates_root` | `screen` |
| `generate` | `screen, confirm_overwrite = None, run_token = None` |
| `open_job_in_editor` | `name, context = None` |
| `new_job_from_data` | `context = None` |
| `reveal_corrupt_job` | `path` |
| `pick_pool_data_file` | `` |
| `pick_template_path` | `` |
| `pick_work_package_path` | `action` |
| `open_path` | `path` |
| `reveal_path` | `path` |
| `copy_path` | `path` |
| `save_artifact_as` | `ordinal` |
| `set_theme` | `mode` |
| `set_font_scale` | `scale` |
| `set_master_width` | `width` |
| `set_authoring_width` | `panel, width` |
| `close_guard_state` | `` |
| `close_flush_required` | `` |
| `confirm_window_close` | `` |
| `cancel_window_close` | `` |

## 시험 전용 호스트 채널

[Tauri 호스트](../../crates/hwpx-desktop/src/tauri_host.rs)는 시험 능력이 있는 실행에서만
`selftest_claim`(version)과 `selftest_host_op`(op, payload)를 받는다.
이 채널은 공개 host 메서드 목록과 분리되며 일반 실행에서는 거절한다.

## Dispatch registry

원천: [action_registry.json](../../crates/hwpx-desktop/src/action_registry.json).
직접 host 호출의 payload 검증은 이 표 밖이다.

### authoring

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `activate` | `session_id` | — |
| `apply_job` | `change_token`, `job_name`, `revision`, `session_id` | — |
| `case_remove` | `name`, `revision`, `session_id` | — |
| `case_upsert` | `name`, `revision`, `selected`, `session_id`, `values` | — |
| `check_external` | `session_id` | — |
| `close` | `session_id` | `force` |
| `commands` | `revision`, `selection`, `session_id` | `context` |
| `content` | `session_id` | — |
| `copy` | `revision`, `selector`, `session_id` | — |
| `external_content` | `session_id` | — |
| `impact` | `revision`, `session_id` | — |
| `locate` | `revision`, `selection`, `session_id` | `target` |
| `new` | `media` | `content` |
| `prepare_apply` | `job_name`, `revision`, `session_id` | — |
| `preview` | `command`, `revision`, `session_id` | — |
| `preview_paste` | `clipboard_token`, `destination`, `revision`, `session_id`, `with_meaning` | — |
| `propose_dismiss` | `group_id`, `revision`, `session_id` | — |
| `propose_fields` | `revision`, `session_id` | `pool_key`, `row`, `sheet` |
| `propose_make` | `group_id`, `revision`, `session_id` | `spot_id` |
| `propose_make_all` | `revision`, `session_id` | — |
| `propose_off` | `session_id` | — |
| `propose_pick_column` | `column`, `group_id`, `revision`, `session_id` | — |
| `reload` | `revision`, `session_id` | `force` |
| `remember_view` | `mode`, `revision`, `selection`, `session_id` | — |
| `rhwp_roundtrip_preflight` | `content`, `revision`, `session_id` | — |
| `rhwp_unverified` | `detail`, `revision`, `session_id` | — |
| `same_text` | `revision`, `selection`, `session_id` | — |
| `save` | `revision`, `session_id` | — |
| `save_cases` | `session_id` | — |
| `search` | `kind`, `query`, `revision`, `session_id` | — |
| `syntax` | `session_id` | — |
| `trial` | `revision`, `session_id` | — |
| `trial_fill_names` | `revision`, `session_id` | — |
| `trial_input` | `revision`, `selected`, `session_id`, `values` | — |
| `update` | `content`, `revision`, `session_id` | — |

### editor

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `ack_gate` | — | — |
| `confirm_suggested` | — | — |
| `discard_patch` | — | `section` |
| `discard_session` | — | — |
| `dismiss_notice` | — | — |
| `goto_section` | `section` | — |
| `mapping_reset_stakes` | — | `cause` |
| `new_session` | — | — |
| `preview_slice` | `index` | `sample` |
| `propose_slice` | `end`, `index`, `sample`, `start` | — |
| `restore_confirmed` | — | — |
| `resuggest_all` | — | — |
| `revert_source` | `index` | — |
| `save` | — | `confirm_overwrite`, `confirmed_overwrite_text` |
| `set_confirmed` | `confirmed`, `index` | — |
| `set_const` | `const`, `index` | — |
| `set_display` | `index`, `type` | `fmt` |
| `set_name` | `name` | — |
| `set_pattern` | `pattern` | — |
| `set_slice` | `index` | `slice` |
| `set_source` | `index`, `source` | — |
| `step_preview` | `delta` | — |
| `unconfirm_all` | — | — |
| `use_library_template` | `path` | — |
| `use_pool_data` | `key` | `sheet` |

### job

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `apply_selection_preset` | `configuration_token`, `preset_key` | — |
| `artifact_close` | — | — |
| `artifact_content` | — | — |
| `artifact_open` | `ordinal` | — |
| `browse_query` | — | `text` |
| `browse_tab` | — | `tab` |
| `cancel_generation` | — | — |
| `count_filter_state` | `state` | — |
| `create_filter_preset` | `name`, `state` | `epoch`, `from_adhoc` |
| `delete_filter_preset` | `name` | `epoch` |
| `dismiss_data_notice` | — | — |
| `filter_clear` | — | `epoch` |
| `filter_clear_col` | `column` | `epoch` |
| `filter_col_range` | `column` | `epoch`, `first`, `joiner`, `second` |
| `filter_col_text` | `column` | `epoch`, `text` |
| `filter_col_values` | `column` | `epoch`, `values` |
| `filter_panel` | `column` | — |
| `filter_prune` | `column` | `epoch` |
| `filter_reapply` | — | `epoch` |
| `filter_search` | — | `epoch`, `text` |
| `guard_state` | — | — |
| `hide_column` | `column` | `epoch` |
| `list_filter_columns` | — | `query` |
| `load_pool` | `key` | `sheet` |
| `open_slot_configuration` | — | — |
| `open_workbench` | — | — |
| `prefer_work` | `name` | — |
| `range_draft_apply` | — | — |
| `range_draft_cancel` | — | — |
| `range_draft_open` | — | — |
| `recover_record_issue` | `target` | — |
| `refresh` | — | — |
| `refresh_observation` | — | — |
| `refresh_slot_configuration` | — | `configuration_token` |
| `relink_template` | `name` | `confirm`, `path` |
| `remount_data` | — | `confirm` |
| `rename_job` | `name` | `new` |
| `resolve_execution` | — | — |
| `save_selection_preset` | `configuration_token`, `name` | `confirmed_overwrite_key` |
| `select_failed` | — | — |
| `select_job` | `name` | `confirm` |
| `select_range` | `indices`, `value` | `epoch` |
| `select_slot_option` | `configuration_token`, `option_id`, `request_id`, `slot_id` | — |
| `set_all` | — | `epoch` |
| `set_none` | — | `epoch` |
| `set_selected_only` | `value` | — |
| `set_view_order` | `value` | `epoch` |
| `template_apply` | `change_token` | — |
| `template_check` | `request_id` | — |
| `toggle_favorite` | `name`, `value` | — |
| `toggle_filter_preset` | `name` | `epoch` |
| `toggle_record` | `index`, `value` | `epoch` |
| `unhide_columns` | — | `epoch` |
| `update_filter_preset` | `name`, `new_name`, `state` | `epoch` |

### library

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `clear_filters` | — | — |
| `clone_job` | `name` | — |
| `delete_corrupt` | `path` | `confirm` |
| `delete_job` | `name` | `confirm` |
| `export_work_package` | `path` | `confirm`, `names` |
| `import_work_package` | `basis`, `path` | — |
| `inspect_work_package` | `path` | — |
| `refresh` | — | `select` |
| `relink_template` | `name` | `confirm`, `path` |
| `select_work` | — | `name` |
| `set_mode` | — | `mode` |
| `set_query` | — | `text` |
| `set_view` | — | `view` |
| `toggle_favorite` | `name`, `value` | — |
| `undo_delete_job` | — | — |

### pool

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `activate` | `key` | — |
| `archive` | `key` | — |
| `delete` | `key` | `basis`, `confirm` |
| `inspect_sheets` | `path` | `kind` |
| `refresh` | — | — |
| `register_excel` | `name`, `path` | `basis`, `confirm`, `note`, `sheet`, `sheets` |
| `register_pclm` | `db`, `name`, `view` | `basis`, `confirm`, `key`, `note`, `views` |
| `relink` | `key`, `path` | `basis`, `confirm`, `name`, `note`, `sheet`, `sheets` |
| `reorder_sheets` | `key`, `sheets` | — |
| `resolve_duplicate` | `keep` | `basis`, `confirm` |
| `review` | `key` | — |

### tpl

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `compile` | `path` | `confirm` |
| `install_examples` | — | `confirm` |
| `refresh` | — | — |
| `remove_examples` | — | `confirm` |
| `review` | `path` | — |
| `slot_decompile` | `path`, `slot_id` | `confirm` |
| `slot_decompile_all` | `path` | `confirm` |
| `slot_remove` | `path`, `slot_id` | `confirm` |
| `slot_rename` | `path`, `slot_id` | `label` |

### tutorial

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `cleanup` | `token` | — |
| `cleanup_preview` | — | — |
| `exit` | — | `transition_token` |
| `later` | — | — |
| `next` | — | — |
| `observe_ui` | `anchor`, `checkpoint`, `scenario_id` | — |
| `observe_ui_closed` | `anchor`, `checkpoint`, `scenario_id` | — |
| `pause` | — | — |
| `preflight` | `action`, `screen` | `destination_screen`, `scenario_id` |
| `reset_progress` | `confirm` | — |
| `restart` | `scenario_id` | `transition_token` |
| `resume` | — | `transition_token` |
| `select` | `scenario_id` | `transition_token` |
| `set_entry_visible` | `visible` | — |
| `skip` | — | — |
| `start` | `scenario_id` | `transition_token` |

### workbench

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `close` | — | — |
| `copy_precheck` | — | — |
| `leave_guard` | — | — |
| `revert_card` | `index` | — |
| `set_card_text` | `index`, `text` | — |
| `set_current` | `index` | — |
| `set_fullwidth` | `value` | — |
| `set_target_font` | — | `font` |
| `set_view` | — | `view` |
| `step` | `delta` | — |
| `toggle_advance` | `value` | — |
