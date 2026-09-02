/* 자동 생성 — 손으로 고치지 않는다 (scripts/gen_bridge_contract.py · R2-02 #406).
 *
 * 정본: webapp/action_registry.py · webapp/product_api.py · webapp/app.py(WebFrontend)
 * · frontend/src/product_api.js(PRODUCT_ERROR_CODES). 드리프트 게이트:
 * tests/repo_contract/test_bridge_contract.py (재생성 바이트 비교 + 생성기 비경유 독립 오러클).
 *
 * v1 계약의 payload 값 타입은 **키 집합**이다 — 값은 도메인 컨트롤러 소유라 unknown
 * 이 정직한 번역이고, 더 좁히면 그게 조용한 추측이다(action_registry.py:16). */

export const PRODUCT_PROTOCOL = "hwpx-product";

export const PRODUCT_VERSION = 1;

/* 순서가 계약이다 — 파사드 describe() 배열과 같은 순서로 읽힌다(product_api.py:60). */
export const PRODUCT_CAPABILITIES = [
  "snapshot",
  "close-request",
  "preferences",
  "notice",
] as const;

export type ProductCapability = (typeof PRODUCT_CAPABILITIES)[number];

/* Python 어댑터(kebab)와 제품 JS(snake)의 오류 어휘는 **경로가 다르다**: kebab 은
 * Python 이 웹→Python·Python→웹 왕복을 판정하며 내는 코드, snake 는 제품 파사드
 * deliver() 가 돌려주는 코드다. 통합·번역은 이 단계 비소유 — 여기는 사실의 등재다. */
export const PYTHON_ERROR_CODES = [
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

export type PythonErrorCode = (typeof PYTHON_ERROR_CODES)[number];

export const JS_PRODUCT_ERROR_CODES = [
  "malformed_request",
  "unsupported_version",
  "unknown_event",
  "malformed_payload",
  "handler_unavailable",
  "handler_failed",
] as const;

export type JsProductErrorCode = (typeof JS_PRODUCT_ERROR_CODES)[number];

/* 템플릿 변경 확인·적용의 제품 status 어휘(S3-09 #659) — 내부 Preparation/Change/Apply
 * 상태의 투영이고 정본은 application/template_change_product.py 다. 내부 어휘를 웹이
 * 직접 보지 않는다(opaque Product Contract). */
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

/* 화면×액션×payload 키 — validate_dispatch 가 거절의 정본이고 이 표는 그 타입 투영이다. */
export const SCREEN_ACTIONS = {
  library: {
    set_view: { required: [], optional: ["view"] },
    set_mode: { required: [], optional: ["mode"] },
    set_query: { required: [], optional: ["text"] },
    clear_filters: { required: [], optional: [] },
    select_work: { required: [], optional: ["name"] },
    toggle_favorite: { required: ["name", "value"], optional: [] },
    delete_job: { required: ["name"], optional: ["confirm"] },
    undo_delete_job: { required: [], optional: [] },
    clone_job: { required: ["name"], optional: [] },
    relink_template: { required: ["name"], optional: ["confirm", "path"] },
    refresh: { required: [], optional: ["select"] },
    delete_corrupt: { required: ["path"], optional: ["confirm"] },
  },
  editor: {
    use_library_template: { required: ["path"], optional: [] },
    new_session: { required: [], optional: [] },
    discard_session: { required: [], optional: [] },
    goto_section: { required: ["section"], optional: [] },
    discard_patch: { required: [], optional: ["section"] },
    ack_gate: { required: [], optional: [] },
    dismiss_notice: { required: [], optional: [] },
    use_pool_data: { required: ["key"], optional: [] },
    use_all_headers: { required: [], optional: [] },
    use_none: { required: [], optional: [] },
    toggle_source_active: { required: ["field"], optional: [] },
    mapping_reset_stakes: { required: [], optional: [] },
    set_source: { required: ["index", "source"], optional: [] },
    revert_source: { required: ["index"], optional: [] },
    resuggest_all: { required: [], optional: [] },
    set_type: { required: ["index", "type"], optional: [] },
    set_fmt: { required: ["fmt", "index"], optional: [] },
    set_const: { required: ["const", "index"], optional: [] },
    set_confirmed: { required: ["confirmed", "index"], optional: [] },
    confirm_all: { required: [], optional: [] },
    confirm_blanks: { required: [], optional: ["fields"] },
    unconfirm_all: { required: [], optional: [] },
    restore_confirmed: { required: [], optional: [] },
    step_preview: { required: ["delta"], optional: [] },
    set_name: { required: ["name"], optional: [] },
    set_pattern: { required: ["pattern"], optional: [] },
    save: { required: [], optional: ["confirm_overwrite", "confirmed_overwrite_text"] },
  },
  job: {
    toggle_record: { required: ["index", "value"], optional: ["epoch"] },
    select_range: { required: ["indices", "value"], optional: ["epoch"] },
    set_all: { required: [], optional: ["epoch"] },
    set_none: { required: [], optional: ["epoch"] },
    filter_search: { required: [], optional: ["epoch", "text"] },
    filter_col_text: { required: ["column"], optional: ["epoch", "text"] },
    filter_col_values: { required: ["column"], optional: ["epoch", "values"] },
    filter_col_range: { required: ["column"], optional: ["epoch", "first", "joiner", "second"] },
    filter_prune: { required: ["column"], optional: ["epoch"] },
    filter_clear: { required: [], optional: ["epoch"] },
    filter_clear_col: { required: ["column"], optional: ["epoch"] },
    filter_reapply: { required: [], optional: ["epoch"] },
    hide_column: { required: ["column"], optional: ["epoch"] },
    unhide_columns: { required: [], optional: ["epoch"] },
    filter_panel: { required: ["column"], optional: [] },
    load_pool: { required: ["key"], optional: [] },
    guard_state: { required: [], optional: [] },
    refresh: { required: [], optional: [] },
    remount_data: { required: [], optional: ["confirm"] },
    set_view_order: { required: ["value"], optional: ["epoch"] },
    open_workbench: { required: [], optional: [] },
    range_draft_open: { required: [], optional: [] },
    range_draft_apply: { required: [], optional: [] },
    range_draft_cancel: { required: [], optional: [] },
    artifact_open: { required: ["ordinal"], optional: [] },
    artifact_close: { required: [], optional: [] },
    set_selected_only: { required: ["value"], optional: [] },
    select_job: { required: ["name"], optional: ["confirm"] },
    toggle_favorite: { required: ["name", "value"], optional: [] },
    prefer_work: { required: ["name"], optional: [] },
    browse_tab: { required: [], optional: ["tab"] },
    browse_query: { required: [], optional: ["text"] },
    dismiss_data_notice: { required: [], optional: [] },
    relink_template: { required: ["name"], optional: ["confirm", "path"] },
    template_check: { required: ["request_id"], optional: [] },
    template_apply: { required: ["change_token"], optional: [] },
    open_slot_configuration: { required: [], optional: [] },
    refresh_slot_configuration: { required: [], optional: ["configuration_token"] },
    select_slot_option: { required: ["configuration_token", "option_id", "request_id", "slot_id"], optional: [] },
    save_selection_preset: { required: ["configuration_token", "name"], optional: ["confirmed_overwrite_key"] },
    apply_selection_preset: { required: ["configuration_token", "preset_key"], optional: [] },
    recover_record_issue: { required: ["target"], optional: [] },
    resolve_execution: { required: [], optional: [] },
    refresh_observation: { required: [], optional: [] },
    rename_job: { required: ["name"], optional: ["new"] },
    cancel_generation: { required: [], optional: [] },
    select_failed: { required: [], optional: [] },
  },
  workbench: {
    step: { required: ["delta"], optional: [] },
    set_current: { required: ["index"], optional: [] },
    toggle_advance: { required: ["value"], optional: [] },
    set_view: { required: [], optional: ["view"] },
    set_target_font: { required: [], optional: ["font"] },
    set_fullwidth: { required: ["value"], optional: [] },
    set_source: { required: ["name"], optional: ["col", "confirm"] },
    set_map_value: { required: ["name"], optional: ["text"] },
    set_map_fmt: { required: ["name"], optional: ["code"] },
    set_map_type: { required: ["name", "type"], optional: [] },
    set_confirmed: { required: ["name", "value"], optional: [] },
    revert_map: { required: ["name"], optional: [] },
    copy_precheck: { required: [], optional: [] },
    save_rules: { required: [], optional: ["confirm", "confirmed_text"] },
    leave_guard: { required: [], optional: [] },
    close: { required: [], optional: [] },
  },
  pool: {
    refresh: { required: [], optional: [] },
    archive: { required: ["key"], optional: [] },
    activate: { required: ["key"], optional: [] },
    delete: { required: ["key"], optional: ["basis", "confirm"] },
    register_excel: { required: ["name", "path"], optional: ["basis", "confirm", "note", "sheet"] },
    register_pclm: { required: ["name", "view"], optional: ["basis", "confirm", "db", "note"] },
    relink: { required: ["key", "path"], optional: ["basis", "confirm", "name", "note", "sheet"] },
    resolve_duplicate: { required: ["keep"], optional: ["basis", "confirm"] },
  },
  tpl: {
    refresh: { required: [], optional: [] },
    install_examples: { required: [], optional: ["confirm"] },
    remove_examples: { required: [], optional: ["confirm"] },
    compile: { required: ["path"], optional: ["confirm"] },
    review: { required: ["path"], optional: [] },
    slot_rename: { required: ["path", "slot_id"], optional: ["label"] },
    slot_decompile: { required: ["path", "slot_id"], optional: ["confirm"] },
    slot_decompile_all: { required: ["path"], optional: ["confirm"] },
    slot_remove: { required: ["path", "slot_id"], optional: ["confirm"] },
    txt_new: { required: ["content", "name"], optional: [] },
    txt_edit: { required: ["baseline", "content", "path"], optional: ["confirm_fingerprint"] },
    txt_content: { required: ["path"], optional: [] },
    txt_lint: { required: ["content"], optional: [] },
  },
  tutorial: {
    dismiss: { required: [], optional: [] },
    resume: { required: [], optional: [] },
    consume_moment: { required: ["milestone"], optional: [] },
    focus_tier: { required: ["tier"], optional: [] },
    clear_focus: { required: [], optional: [] },
  },
} as const;

export type ScreenName = keyof typeof SCREEN_ACTIONS;

export type ActionName<S extends ScreenName> = keyof (typeof SCREEN_ACTIONS)[S] & string;

/* WebFrontend js_api 공개 표면 — 클래스 본문 정의 순서 그대로. */
export const HOST_METHODS = [
  "initial",
  "dispatch",
  "set_theme",
  "set_font_scale",
  "set_master_width",
  "import_template_file",
  "pick_templates_root",
  "pick_data_file",
  "load_data_sheet",
  "copy_clipboard",
  "pick_output_folder",
  "generate",
  "close_guard_state",
  "confirm_window_close",
  "cancel_window_close",
  "pick_pool_data_file",
  "pick_template_path",
  "reveal_corrupt_job",
  "copy_path",
  "reveal_path",
  "open_path",
  "save_artifact_as",
  "open_job_in_editor",
  "new_job_from_data",
] as const;

export type HostMethodName = (typeof HOST_METHODS)[number];

/* 웹 소비자 0 인 host-internal 표면의 기록 — 지우지도 승격하지도 않는다(패킷 §4.1). */
export const HOST_INTERNAL_METHODS = [
  "close_guard_state",
] as const;

export type HostInternalMethodName = (typeof HOST_INTERNAL_METHODS)[number];

export interface HostApi {
  initial(screen: unknown): unknown;
  dispatch(screen: unknown, action: unknown, payload?: unknown): unknown;
  set_theme(mode: unknown): unknown;
  set_font_scale(scale: unknown): unknown;
  set_master_width(width: unknown): unknown;
  import_template_file(screen: unknown): unknown;
  pick_templates_root(screen: unknown): unknown;
  pick_data_file(screen: unknown): unknown;
  load_data_sheet(screen: unknown, path: unknown, sheet: unknown): unknown;
  copy_clipboard(screen: unknown, token?: unknown): unknown;
  pick_output_folder(screen: unknown): unknown;
  generate(screen: unknown, confirm_overwrite?: unknown, run_token?: unknown): unknown;
  close_guard_state(): unknown;
  confirm_window_close(): unknown;
  cancel_window_close(): unknown;
  pick_pool_data_file(): unknown;
  pick_template_path(): unknown;
  reveal_corrupt_job(path: unknown): unknown;
  copy_path(path: unknown): unknown;
  reveal_path(path: unknown): unknown;
  open_path(path: unknown): unknown;
  save_artifact_as(ordinal: unknown): unknown;
  open_job_in_editor(name: unknown, context?: unknown): unknown;
  new_job_from_data(context?: unknown): unknown;
}

/* 문서 만들기 작업대 blocker 계열(SX-01 #724 §3) — 정의 순서가 곧 우선순위 기반이다.
 * 정본: application/document_creation_vocabulary.py. React 가 이 순서를 재구현하지 않는다
 * (blocker 합성은 backend Product 계약이 진다). */
export const DOCUMENT_CREATION_BLOCKERS = [
  "SELECT_DATA",
  "SELECT_RECORDS",
  "SELECT_WORK",
  "CONNECT_DATA",
  "REVIEW_TEMPLATE_CHANGE",
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

/* Primary Action 코드 — 우선순위 순서(#724 §3). 첫 원소가 최우선, 마지막이
 * CREATE_DOCUMENTS. 표시층은 이 순서를 재계산하지 않고 backend 가 고른 하나를 소비한다. */
export const PRIMARY_ACTIONS = [
  "RECOVER_CONTEXT",
  "SELECT_DATA",
  "SELECT_RECORDS",
  "SELECT_WORK",
  "CONNECT_DATA",
  "REVIEW_TEMPLATE_CHANGE",
  "CHOOSE_CONTENT",
  "REVIEW_BINDING",
  "RESOLVE_EXECUTION",
  "REVIEW_RECORD_DATA",
  "REVIEW_DELIVERY",
  "RESOLVE_RUNTIME_POLICY",
  "CREATE_DOCUMENTS",
] as const;

export type PrimaryAction = (typeof PRIMARY_ACTIONS)[number];

/* 작업대 execution status 7상태(SX-03 #726 §3) — orchestration+sealability+
 * admission verdict 의 재라벨. 정본: application/workbench_execution_status.py. 표시층은
 * 이 코드를 재판정하지 않고 backend 가 파생한 하나를 소비한다(문안은 STATUS_PHRASE 정본). */
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

/* RunDeliveryIntent collision policy(#724 §8) — 기본 ADD_SUFFIX, overwrite 는 명시 선택. */
export const COLLISION_POLICIES = [
  "ADD_SUFFIX",
  "FAIL",
  "OVERWRITE_EXPLICIT",
] as const;

export type CollisionPolicy = (typeof COLLISION_POLICIES)[number];
