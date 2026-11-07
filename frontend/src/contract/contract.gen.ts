/* 자동 생성 — 손으로 고치지 않는다 (scripts/gen_bridge_contract.mjs).
 * 정본: Rust bridge_descriptor, action_registry.json, host_contract.json, frontend/src/product_api.js.
 * payload 값 타입의 정본은 제품 컨트롤러이며 이 표는 허용 키 집합을 투영한다. */

export const PRODUCT_PROTOCOL = "hwpx-product";

export const PRODUCT_VERSION = 1;

export const PRODUCT_CAPABILITIES = [
  "snapshot",
  "close-request",
  "preferences",
  "notice",
] as const;

export type ProductCapability = (typeof PRODUCT_CAPABILITIES)[number];

export const HOST_ERROR_CODES = [
  "facade-absent",
  "evaluate-failed",
  "descriptor-malformed",
  "protocol-mismatch",
  "version-unsupported",
  "capability-missing",
  "result-not-object",
  "result-missing-ok",
  "result-ok-not-bool",
  "rejected",
  "payload-unserializable",
  "adapter-internal",
] as const;

export type HostErrorCode = (typeof HOST_ERROR_CODES)[number];

export const JS_PRODUCT_ERROR_CODES = [
  "malformed_request",
  "unsupported_version",
  "unknown_event",
  "malformed_payload",
  "handler_unavailable",
  "handler_failed",
] as const;

export type JsProductErrorCode = (typeof JS_PRODUCT_ERROR_CODES)[number];

export const TEMPLATE_PREPARATION_STATUSES = [
  "checking",
  "ready",
  "no_change",
  "invalid",
  "error",
  "interrupted",
  "source_changed",
  "changed_while_checking",
  "superseded",
  "applied",
  "conflict",
  "rejected",
] as const;

export type TemplatePreparationStatus = (typeof TEMPLATE_PREPARATION_STATUSES)[number];

export const TEMPLATE_APPLY_STATUSES = [
  "applied",
  "already_applied",
  "applied_then_advanced",
  "conflict",
  "superseded",
  "rejected",
] as const;

export type TemplateApplyStatus = (typeof TEMPLATE_APPLY_STATUSES)[number];

export const DISPATCH_REJECTION_KEY = "__hwpx_dispatch_rejection_v1__";

export const DISPATCH_REJECTION_FIELDS = ["name", "message"] as const;

export const SCREEN_ACTIONS = {
  authoring: {
    activate: { required: ["session_id"], optional: [] },
    apply_job: { required: ["change_token", "job_name", "revision", "session_id"], optional: [] },
    case_remove: { required: ["name", "revision", "session_id"], optional: [] },
    case_upsert: { required: ["name", "revision", "selected", "session_id", "values"], optional: [] },
    check_external: { required: ["session_id"], optional: [] },
    close: { required: ["session_id"], optional: ["force"] },
    commands: { required: ["revision", "selection", "session_id"], optional: ["context"] },
    content: { required: ["session_id"], optional: [] },
    copy: { required: ["revision", "selector", "session_id"], optional: [] },
    external_content: { required: ["session_id"], optional: [] },
    impact: { required: ["revision", "session_id"], optional: [] },
    locate: { required: ["revision", "selection", "session_id"], optional: ["target"] },
    new: { required: ["media"], optional: ["content"] },
    prepare_apply: { required: ["job_name", "revision", "session_id"], optional: [] },
    preview: { required: ["command", "revision", "session_id"], optional: [] },
    preview_paste: { required: ["clipboard_token", "destination", "revision", "session_id", "with_meaning"], optional: [] },
    propose_dismiss: { required: ["group_id", "revision", "session_id"], optional: [] },
    propose_fields: { required: ["revision", "session_id"], optional: ["pool_key", "row", "sheet"] },
    propose_make: { required: ["group_id", "revision", "session_id"], optional: ["spot_id"] },
    propose_make_all: { required: ["revision", "session_id"], optional: [] },
    propose_off: { required: ["session_id"], optional: [] },
    propose_pick_column: { required: ["column", "group_id", "revision", "session_id"], optional: [] },
    reload: { required: ["revision", "session_id"], optional: ["force"] },
    remember_view: { required: ["mode", "revision", "selection", "session_id"], optional: [] },
    rhwp_roundtrip_preflight: { required: ["content", "revision", "session_id"], optional: [] },
    rhwp_unverified: { required: ["detail", "revision", "session_id"], optional: [] },
    same_text: { required: ["revision", "selection", "session_id"], optional: [] },
    save: { required: ["revision", "session_id"], optional: [] },
    save_cases: { required: ["session_id"], optional: [] },
    search: { required: ["kind", "query", "revision", "session_id"], optional: [] },
    syntax: { required: ["session_id"], optional: [] },
    trial: { required: ["revision", "session_id"], optional: [] },
    trial_fill_names: { required: ["revision", "session_id"], optional: [] },
    trial_input: { required: ["revision", "selected", "session_id", "values"], optional: [] },
    update: { required: ["content", "revision", "session_id"], optional: [] },
  },
  editor: {
    ack_gate: { required: [], optional: [] },
    confirm_suggested: { required: [], optional: [] },
    discard_patch: { required: [], optional: ["section"] },
    discard_session: { required: [], optional: [] },
    dismiss_notice: { required: [], optional: [] },
    goto_section: { required: ["section"], optional: [] },
    mapping_reset_stakes: { required: [], optional: ["cause"] },
    new_session: { required: [], optional: [] },
    preview_slice: { required: ["index"], optional: ["sample"] },
    propose_slice: { required: ["end", "index", "sample", "start"], optional: [] },
    restore_confirmed: { required: [], optional: [] },
    resuggest_all: { required: [], optional: [] },
    revert_source: { required: ["index"], optional: [] },
    save: { required: [], optional: ["confirm_overwrite", "confirmed_overwrite_text"] },
    set_confirmed: { required: ["confirmed", "index"], optional: [] },
    set_const: { required: ["const", "index"], optional: [] },
    set_display: { required: ["index", "type"], optional: ["fmt"] },
    set_name: { required: ["name"], optional: [] },
    set_pattern: { required: ["pattern"], optional: [] },
    set_slice: { required: ["index"], optional: ["slice"] },
    set_source: { required: ["index", "source"], optional: [] },
    step_preview: { required: ["delta"], optional: [] },
    unconfirm_all: { required: [], optional: [] },
    use_library_template: { required: ["path"], optional: [] },
    use_pool_data: { required: ["key"], optional: ["sheet"] },
  },
  job: {
    apply_selection_preset: { required: ["configuration_token", "preset_key"], optional: [] },
    artifact_close: { required: [], optional: [] },
    artifact_content: { required: [], optional: [] },
    artifact_open: { required: ["ordinal"], optional: [] },
    browse_query: { required: [], optional: ["text"] },
    browse_tab: { required: [], optional: ["tab"] },
    cancel_generation: { required: [], optional: [] },
    count_filter_state: { required: ["state"], optional: [] },
    create_filter_preset: { required: ["name", "state"], optional: ["epoch", "from_adhoc"] },
    delete_filter_preset: { required: ["name"], optional: ["epoch"] },
    dismiss_data_notice: { required: [], optional: [] },
    filter_clear: { required: [], optional: ["epoch"] },
    filter_clear_col: { required: ["column"], optional: ["epoch"] },
    filter_col_range: { required: ["column"], optional: ["epoch", "first", "joiner", "second"] },
    filter_col_text: { required: ["column"], optional: ["epoch", "text"] },
    filter_col_values: { required: ["column"], optional: ["epoch", "values"] },
    filter_panel: { required: ["column"], optional: [] },
    filter_prune: { required: ["column"], optional: ["epoch"] },
    filter_reapply: { required: [], optional: ["epoch"] },
    filter_search: { required: [], optional: ["epoch", "text"] },
    guard_state: { required: [], optional: [] },
    hide_column: { required: ["column"], optional: ["epoch"] },
    list_filter_columns: { required: [], optional: ["query"] },
    load_pool: { required: ["key"], optional: ["sheet"] },
    open_slot_configuration: { required: [], optional: [] },
    open_workbench: { required: [], optional: [] },
    prefer_work: { required: ["name"], optional: [] },
    range_draft_apply: { required: [], optional: [] },
    range_draft_cancel: { required: [], optional: [] },
    range_draft_open: { required: [], optional: [] },
    recover_record_issue: { required: ["target"], optional: [] },
    refresh: { required: [], optional: [] },
    refresh_observation: { required: [], optional: [] },
    refresh_slot_configuration: { required: [], optional: ["configuration_token"] },
    relink_template: { required: ["name"], optional: ["confirm", "path"] },
    remount_data: { required: [], optional: ["confirm"] },
    rename_job: { required: ["name"], optional: ["new"] },
    resolve_execution: { required: [], optional: [] },
    save_selection_preset: { required: ["configuration_token", "name"], optional: ["confirmed_overwrite_key"] },
    select_failed: { required: [], optional: [] },
    select_job: { required: ["name"], optional: ["confirm"] },
    select_range: { required: ["indices", "value"], optional: ["epoch"] },
    select_slot_option: { required: ["configuration_token", "option_id", "request_id", "slot_id"], optional: [] },
    set_all: { required: [], optional: ["epoch"] },
    set_none: { required: [], optional: ["epoch"] },
    set_selected_only: { required: ["value"], optional: [] },
    set_view_order: { required: ["value"], optional: ["epoch"] },
    template_apply: { required: ["change_token"], optional: [] },
    template_check: { required: ["request_id"], optional: [] },
    toggle_favorite: { required: ["name", "value"], optional: [] },
    toggle_filter_preset: { required: ["name"], optional: ["epoch"] },
    toggle_record: { required: ["index", "value"], optional: ["epoch"] },
    unhide_columns: { required: [], optional: ["epoch"] },
    update_filter_preset: { required: ["name", "new_name", "state"], optional: ["epoch"] },
  },
  library: {
    clear_filters: { required: [], optional: [] },
    clone_job: { required: ["name"], optional: [] },
    delete_corrupt: { required: ["path"], optional: ["confirm"] },
    delete_job: { required: ["name"], optional: ["confirm"] },
    export_work_package: { required: ["path"], optional: ["confirm", "names"] },
    import_work_package: { required: ["basis", "path"], optional: [] },
    inspect_work_package: { required: ["path"], optional: [] },
    refresh: { required: [], optional: ["select"] },
    relink_template: { required: ["name"], optional: ["confirm", "path"] },
    select_work: { required: [], optional: ["name"] },
    set_mode: { required: [], optional: ["mode"] },
    set_query: { required: [], optional: ["text"] },
    set_view: { required: [], optional: ["view"] },
    toggle_favorite: { required: ["name", "value"], optional: [] },
    undo_delete_job: { required: [], optional: [] },
  },
  pool: {
    activate: { required: ["key"], optional: [] },
    archive: { required: ["key"], optional: [] },
    delete: { required: ["key"], optional: ["basis", "confirm"] },
    inspect_sheets: { required: ["path"], optional: ["kind"] },
    refresh: { required: [], optional: [] },
    register_excel: { required: ["name", "path"], optional: ["basis", "confirm", "note", "sheet", "sheets"] },
    register_pclm: { required: ["db", "name", "view"], optional: ["basis", "confirm", "key", "note", "views"] },
    relink: { required: ["key", "path"], optional: ["basis", "confirm", "name", "note", "sheet", "sheets"] },
    reorder_sheets: { required: ["key", "sheets"], optional: [] },
    resolve_duplicate: { required: ["keep"], optional: ["basis", "confirm"] },
    review: { required: ["key"], optional: [] },
  },
  tpl: {
    compile: { required: ["path"], optional: ["confirm"] },
    install_examples: { required: [], optional: ["confirm"] },
    refresh: { required: [], optional: [] },
    remove_examples: { required: [], optional: ["confirm"] },
    review: { required: ["path"], optional: [] },
    slot_decompile: { required: ["path", "slot_id"], optional: ["confirm"] },
    slot_decompile_all: { required: ["path"], optional: ["confirm"] },
    slot_remove: { required: ["path", "slot_id"], optional: ["confirm"] },
    slot_rename: { required: ["path", "slot_id"], optional: ["label"] },
  },
  tutorial: {
    cleanup: { required: ["token"], optional: [] },
    cleanup_preview: { required: [], optional: [] },
    exit: { required: [], optional: ["transition_token"] },
    later: { required: [], optional: [] },
    next: { required: [], optional: [] },
    observe_ui: { required: ["anchor", "checkpoint", "scenario_id"], optional: [] },
    observe_ui_closed: { required: ["anchor", "checkpoint", "scenario_id"], optional: [] },
    pause: { required: [], optional: [] },
    preflight: { required: ["action", "screen"], optional: ["destination_screen", "scenario_id"] },
    reset_progress: { required: ["confirm"], optional: [] },
    restart: { required: ["scenario_id"], optional: ["transition_token"] },
    resume: { required: [], optional: ["transition_token"] },
    select: { required: ["scenario_id"], optional: ["transition_token"] },
    set_entry_visible: { required: ["visible"], optional: [] },
    skip: { required: [], optional: [] },
    start: { required: ["scenario_id"], optional: ["transition_token"] },
  },
  workbench: {
    close: { required: [], optional: [] },
    copy_precheck: { required: [], optional: [] },
    leave_guard: { required: [], optional: [] },
    revert_card: { required: ["index"], optional: [] },
    set_card_text: { required: ["index", "text"], optional: [] },
    set_current: { required: ["index"], optional: [] },
    set_fullwidth: { required: ["value"], optional: [] },
    set_target_font: { required: [], optional: ["font"] },
    set_view: { required: [], optional: ["view"] },
    step: { required: ["delta"], optional: [] },
    toggle_advance: { required: ["value"], optional: [] },
  },
} as const;

export type ScreenName = keyof typeof SCREEN_ACTIONS;

export type ActionName<S extends ScreenName> = keyof (typeof SCREEN_ACTIONS)[S] & string;

export const HOST_METHODS = [
  "initial",
  "dispatch",
  "pick_data_file",
  "open_authoring_document",
  "save_authoring_document",
  "authoring_cases_file",
  "export_authoring_result",
  "load_data_sheet",
  "import_template_file",
  "copy_clipboard",
  "pick_output_folder",
  "pick_templates_root",
  "generate",
  "open_job_in_editor",
  "new_job_from_data",
  "reveal_corrupt_job",
  "pick_pool_data_file",
  "pick_template_path",
  "pick_work_package_path",
  "open_path",
  "reveal_path",
  "copy_path",
  "save_artifact_as",
  "set_theme",
  "set_font_scale",
  "set_master_width",
  "set_authoring_width",
  "close_guard_state",
  "close_flush_required",
  "confirm_window_close",
  "cancel_window_close",
] as const;

export type HostMethodName = (typeof HOST_METHODS)[number];

export const HOST_INTERNAL_METHODS = [
  "close_flush_required",
] as const;

export type HostInternalMethodName = (typeof HOST_INTERNAL_METHODS)[number];

export interface HostApi {
  initial(screen: unknown): unknown;
  dispatch(screen: unknown, action: unknown, payload?: unknown): unknown;
  pick_data_file(screen: unknown): unknown;
  open_authoring_document(path?: unknown, as_template?: unknown): unknown;
  save_authoring_document(session_id: unknown, revision: unknown): unknown;
  authoring_cases_file(session_id: unknown, action: unknown): unknown;
  export_authoring_result(session_id: unknown, revision: unknown): unknown;
  load_data_sheet(screen: unknown, path: unknown, sheet: unknown, confirmation?: unknown): unknown;
  import_template_file(screen: unknown): unknown;
  copy_clipboard(screen: unknown, token?: unknown): unknown;
  pick_output_folder(screen: unknown): unknown;
  pick_templates_root(screen: unknown): unknown;
  generate(screen: unknown, confirm_overwrite?: unknown, run_token?: unknown): unknown;
  open_job_in_editor(name: unknown, context?: unknown): unknown;
  new_job_from_data(context?: unknown): unknown;
  reveal_corrupt_job(path: unknown): unknown;
  pick_pool_data_file(): unknown;
  pick_template_path(): unknown;
  pick_work_package_path(action: unknown): unknown;
  open_path(path: unknown): unknown;
  reveal_path(path: unknown): unknown;
  copy_path(path: unknown): unknown;
  save_artifact_as(ordinal: unknown): unknown;
  set_theme(mode: unknown): unknown;
  set_font_scale(scale: unknown): unknown;
  set_master_width(width: unknown): unknown;
  set_authoring_width(panel: unknown, width: unknown): unknown;
  close_guard_state(): unknown;
  close_flush_required(): unknown;
  confirm_window_close(): unknown;
  cancel_window_close(): unknown;
}

export const DOCUMENT_CREATION_BLOCKERS = [
  "SELECT_DATA",
  "SELECT_RECORDS",
  "SELECT_WORK",
  "CONNECT_DATA",
  "REVIEW_TEMPLATE_CHANGE",
  "REPAIR_TEMPLATE",
  "CHOOSE_CONTENT",
  "REVIEW_BINDING",
  "REVIEW_RECORD_DATA",
  "REVIEW_DELIVERY",
  "EXECUTION_NO_EVIDENCE",
  "EXECUTION_CHECKING",
  "EXECUTION_STALE",
  "POLICY_BLOCKED",
  "RUNTIME_NOT_ADMITTED",
  "CONTEXT_ERROR",
] as const;

export type DocumentCreationBlocker = (typeof DOCUMENT_CREATION_BLOCKERS)[number];

export const PRIMARY_ACTIONS = [
  "RECOVER_CONTEXT",
  "SELECT_DATA",
  "SELECT_RECORDS",
  "SELECT_WORK",
  "CONNECT_DATA",
  "REVIEW_TEMPLATE_CHANGE",
  "REPAIR_TEMPLATE",
  "CHOOSE_CONTENT",
  "REVIEW_BINDING",
  "RESOLVE_EXECUTION",
  "REVIEW_RECORD_DATA",
  "REVIEW_DELIVERY",
  "RESOLVE_RUNTIME_POLICY",
  "CREATE_DOCUMENTS",
] as const;

export type PrimaryAction = (typeof PRIMARY_ACTIONS)[number];

export const WORKBENCH_EXECUTION_STATUSES = [
  "NO_EVIDENCE",
  "CHECKING",
  "CURRENT",
  "STALE",
  "DOMAIN_BLOCKED",
  "POLICY_BLOCKED",
  "CONTEXT_ERROR",
] as const;

export type WorkbenchExecutionStatus = (typeof WORKBENCH_EXECUTION_STATUSES)[number];

export const COLLISION_POLICIES = [
  "ADD_SUFFIX",
  "FAIL",
  "OVERWRITE_EXPLICIT",
] as const;

export type CollisionPolicy = (typeof COLLISION_POLICIES)[number];

export const SESSION_DATA_KEY = "session" as const;
