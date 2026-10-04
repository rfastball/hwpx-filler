# 코드에서 생성한 런타임 참조

> 생성물: `uv run python scripts/docs_contract.py --write`. 직접 편집하지 않는다.
> 선언·등록 목록이다. 채널이나 메서드가 있다는 사실은 사용자 기능의 노출을 뜻하지 않는다.

## 환경 선언

| 항목 | 선언 | 원천 |
|---|---|---|
| 제품 버전 | `0.11.0` | [pyproject.toml](../../pyproject.toml) |
| Python 요구 범위 | `>=3.13,<3.14` | [pyproject.toml](../../pyproject.toml) |
| Python pin | `3.13` | [.python-version](../../.python-version) |
| Node pin | `24.18.1` | [.node-version](../../.node-version) |
| Node engine | `24.18.1` | [package.json](../../package.json) |
| npm engine | `11.16.0` | [package.json](../../package.json) |
| package manager | `npm@11.16.0` | [package.json](../../package.json) |

## 진입점

| 종류 | 명령 | Python 대상 |
|---|---|---|
| scripts | `hwpxfiller` | `hwpxfiller.cli:main` |
| gui-scripts | `hwpx-filler-web` | `hwpxfiller.webapp.app:main` |

## 품질 CI

원천: [quality.yml](../../.github/workflows/quality.yml). 실제 설정의 등록 목록이다.

- Jobs: `sealed-web`, `static`, `pytest-contract`, `windows-native`, `browser-render`, `live-webview2`, `distribution-webview2`, `quality-gate`
- `quality-gate.needs`: `sealed-web`, `static`, `pytest-contract`, `windows-native`, `browser-render`, `live-webview2`, `distribution-webview2`

## WebFrontend 공개 메서드

원천: [app.py](../../src/hwpxfiller/webapp/app.py)의 클래스 AST.
host 내부 소비용 메서드도 포함한다. 실제 웹 호출은 [bridge.js](../../frontend/js/bridge.js)와
독립 브리지 계약 테스트로 대조한다.

| 메서드 | 인자 |
|---|---|
| `authoring_cases_file` | `session_id: str, action: str` |
| `cancel_window_close` | `` |
| `close_guard_state` | `` |
| `confirm_window_close` | `` |
| `copy_clipboard` | `screen: str, token: 'str &#124; None'=None` |
| `copy_path` | `path: str` |
| `dispatch` | `screen: str, action: str, payload: 'dict &#124; None'=None` |
| `export_authoring_result` | `session_id: str, revision: int` |
| `generate` | `screen: str, confirm_overwrite: bool=False, run_token: str=''` |
| `import_template_file` | `screen: str` |
| `initial` | `screen: str` |
| `load_data_sheet` | `screen: str, path: str, sheet: str &#124; list[str], confirmation: dict &#124; None=None` |
| `new_job_from_data` | `context: 'dict &#124; None'=None` |
| `open_authoring_document` | `path: str='', as_template: bool=False` |
| `open_job_in_editor` | `name: str, context: 'dict &#124; None'=None` |
| `open_path` | `path: str` |
| `pick_data_file` | `screen: str` |
| `pick_output_folder` | `screen: str` |
| `pick_pool_data_file` | `` |
| `pick_template_path` | `` |
| `pick_templates_root` | `screen: str` |
| `reveal_corrupt_job` | `path: str` |
| `reveal_path` | `path: str` |
| `save_artifact_as` | `ordinal: object` |
| `save_authoring_document` | `session_id: str, revision: int` |
| `set_authoring_width` | `panel: str, width: int` |
| `set_font_scale` | `scale: str` |
| `set_master_width` | `width: int` |
| `set_theme` | `mode: str` |

## Selftest 전용 공개 메서드

원천: [selftest_api.py](../../src/hwpxfiller/webapp/selftest_api.py)의 SelftestHostFacade.
제품 WebFrontend의 메서드가 아니다. selftest 권한·수명 검사를 거치는 별도 경계다.

| 메서드 | 인자 |
|---|---|
| `claim_state` | `` |
| `selftest_claim` | `version: object=None, token: object=None` |
| `selftest_host_op` | `op: object=None, payload: object=None, token: object=None` |

## Dispatch registry

원천: [action_registry.py](../../src/hwpxfiller/webapp/action_registry.py).
공유 dictionary expansion을 포함한다. 직접 host 호출의 payload 검증은 이 표 밖이다.

### authoring

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `activate` | `session_id` | — |
| `apply_job` | `session_id`, `revision`, `job_name`, `change_token` | — |
| `case_remove` | `session_id`, `revision`, `name` | — |
| `case_upsert` | `session_id`, `revision`, `name`, `values`, `selected` | — |
| `check_external` | `session_id` | — |
| `close` | `session_id` | `force` |
| `commands` | `session_id`, `revision`, `selection` | `context` |
| `content` | `session_id` | — |
| `copy` | `session_id`, `revision`, `selector` | — |
| `external_content` | `session_id` | — |
| `impact` | `session_id`, `revision` | — |
| `locate` | `session_id`, `revision`, `selection` | `target` |
| `new` | `media` | `content` |
| `prepare_apply` | `session_id`, `revision`, `job_name` | — |
| `preview` | `session_id`, `revision`, `command` | — |
| `preview_paste` | `session_id`, `revision`, `clipboard_token`, `destination`, `with_meaning` | — |
| `reload` | `session_id`, `revision` | `force` |
| `remember_view` | `session_id`, `revision`, `selection`, `mode` | — |
| `rhwp_roundtrip_preflight` | `session_id`, `revision`, `content` | — |
| `rhwp_unverified` | `session_id`, `revision`, `detail` | — |
| `same_text` | `session_id`, `revision`, `selection` | — |
| `save` | `session_id`, `revision` | — |
| `save_cases` | `session_id` | — |
| `search` | `session_id`, `revision`, `query`, `kind` | — |
| `syntax` | `session_id` | — |
| `trial` | `session_id`, `revision` | — |
| `trial_fill_names` | `session_id`, `revision` | — |
| `trial_input` | `session_id`, `revision`, `values`, `selected` | — |
| `update` | `session_id`, `revision`, `content` | — |

### editor

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `ack_gate` | — | — |
| `confirm_suggested` | — | — |
| `discard_patch` | — | `section` |
| `discard_session` | — | — |
| `dismiss_notice` | — | — |
| `goto_section` | `section` | — |
| `mapping_reset_stakes` | — | — |
| `new_session` | — | — |
| `preview_slice` | `index` | `sample` |
| `propose_slice` | `index`, `sample`, `start`, `end` | — |
| `restore_confirmed` | — | — |
| `resuggest_all` | — | — |
| `revert_source` | `index` | — |
| `save` | — | `confirm_overwrite`, `confirmed_overwrite_text` |
| `set_confirmed` | `index`, `confirmed` | — |
| `set_const` | `index`, `const` | — |
| `set_display` | `index`, `type` | `fmt` |
| `set_name` | `name` | — |
| `set_pattern` | `pattern` | — |
| `set_slice` | `index` | `slice` |
| `set_source` | `index`, `source` | — |
| `step_preview` | `delta` | — |
| `unconfirm_all` | — | — |
| `use_library_template` | `path` | — |
| `use_pool_data` | `key` | — |

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
| `create_filter_preset` | `name`, `state` | `from_adhoc`, `epoch` |
| `delete_filter_preset` | `name` | `epoch` |
| `dismiss_data_notice` | — | — |
| `filter_clear` | — | `epoch` |
| `filter_clear_col` | `column` | `epoch` |
| `filter_col_range` | `column` | `first`, `second`, `joiner`, `epoch` |
| `filter_col_text` | `column` | `text`, `epoch` |
| `filter_col_values` | `column` | `values`, `epoch` |
| `filter_panel` | `column` | — |
| `filter_prune` | `column` | `epoch` |
| `filter_reapply` | — | `epoch` |
| `filter_search` | — | `text`, `epoch` |
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
| `relink_template` | `name` | `path`, `confirm` |
| `remount_data` | — | `confirm` |
| `rename_job` | `name` | `new` |
| `resolve_execution` | — | — |
| `save_selection_preset` | `configuration_token`, `name` | `confirmed_overwrite_key` |
| `select_failed` | — | — |
| `select_job` | `name` | `confirm` |
| `select_range` | `indices`, `value` | `epoch` |
| `select_slot_option` | `configuration_token`, `slot_id`, `option_id`, `request_id` | — |
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
| `refresh` | — | `select` |
| `relink_template` | `name` | `path`, `confirm` |
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
| `delete` | `key` | `confirm`, `basis` |
| `inspect_sheets` | `path` | `kind` |
| `refresh` | — | — |
| `register_excel` | `name`, `path` | `sheet`, `sheets`, `note`, `confirm`, `basis` |
| `register_pclm` | `name`, `view` | `db`, `views`, `note`, `confirm`, `basis` |
| `relink` | `key`, `path` | `sheet`, `sheets`, `note`, `name`, `confirm`, `basis` |
| `resolve_duplicate` | `keep` | `confirm`, `basis` |
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
| `observe_ui` | `scenario_id`, `checkpoint`, `anchor` | — |
| `pause` | — | — |
| `preflight` | `screen`, `action` | `scenario_id`, `destination_screen` |
| `reset_progress` | `confirm` | — |
| `restart` | `scenario_id` | `transition_token` |
| `resume` | — | `transition_token` |
| `select` | `scenario_id` | `transition_token` |
| `skip` | — | — |
| `start` | `scenario_id` | `transition_token` |

### workbench

| 액션 | 필수 키 | 선택 키 |
|---|---|---|
| `close` | — | — |
| `copy_precheck` | — | — |
| `leave_guard` | — | — |
| `preview_map_slice` | `name` | `sample` |
| `propose_map_slice` | `name`, `sample`, `start`, `end` | — |
| `revert_map` | `name` | — |
| `save_rules` | — | `confirm`, `confirmed_text` |
| `set_confirmed` | `name`, `value` | — |
| `set_current` | `index` | — |
| `set_fullwidth` | `value` | — |
| `set_map_fmt` | `name` | `code` |
| `set_map_slice` | `name` | `slice` |
| `set_map_type` | `name`, `type` | — |
| `set_map_value` | `name` | `text` |
| `set_source` | `name` | `col`, `confirm` |
| `set_target_font` | — | `font` |
| `set_view` | — | `view` |
| `step` | `delta` | — |
| `toggle_advance` | `value` | — |
