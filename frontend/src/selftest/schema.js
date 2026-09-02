/* N-08 selftest 결과 계약의 **단일 출처**.
 *
 * 오늘 이 계약은 `src/hwpxfiller/webapp/app.py` 의 `_selftest_drive` 안에 **암묵으로만** 산다:
 * 어떤 키가 어느 모드에서 나오는지, 어떤 값이 어떤 게이트를 지나는지가 드라이버의 실행 순서와
 * 파이썬 리터럴에 흩어져 있다. N-08 은 그 28개 프로브 상수를 프런트 모듈로 옮기는데, 옮기는
 * 네 레인(B·C·D·E)이 각자 계약을 다시 지으면 이식은 되돌릴 수 없이 갈라진다. 이 파일이 그
 * 갈라짐을 막는 자리다 — **키·모드·소유·소비**를 데이터로 적고, 산술(합집합 수량)은
 * 하드코딩이 아니라 모드 행렬에서 **계산**한다.
 *
 * 이 모듈은 **비활성(inert)** 이다. 제품 entry(`main.js` → `bootstrap.js`/`bridge.js`) 어디에서도
 * import 하지 않으며, 전역을 하나도 쓰지 않는다. 소비자는 Node 테스트뿐이다.
 *
 * 실측 근거: base SHA `ae1b689` 에서 실 WebView2 로 5개 모드를 각각 구동해 받은 증거 파일
 * (`selftest-n0708-base-ae1b689.json`, `n0708-modes/*.json`). 아래 숫자·키·값 종류는 그
 * 캡처에서 왔다 — 설계 문서의 옛 수치(44)가 아니다.
 */

/* ────────────────────────────── 모드 ────────────────────────────── */

/** 환경변수로 고르는 모드 다섯. 전부 `--selftest` 로 들어간다.
 *
 *  `kind` 가 갈림의 핵심이다:
 *   - `"key-set"`  — 그 모드가 내는 **키 집합**이 따로 있다.
 *   - `"value-level"` — 키 집합은 기반 모드와 **똑같고**, 값만 달라진다. `offline_probe` 가
 *     그것이다: 43키 그대로 나오고 `runtime.external_fetch_*` 의 값만 바뀌며 중첩 필드
 *     `external_fetch_error` 가 하나 는다. 키-가산 모드로 오해하면 합집합이 틀린다.
 */
export const SELFTEST_MODES = Object.freeze({
  full: Object.freeze({
    name: "full",
    env: null,
    kind: "key-set",
    baseMode: null,
    /** 44키. 순서는 알파벳 — 드라이버 실행 순서가 아니다(그건 runner 의 `legacySite`). */
    keys: Object.freeze([
      "action_roundtrip", "chain_recovery", "data_picker", "data_picker_buttons",
      "data_sheet", "editor_binding", "editor_discard_immediate", "editor_lib",
      "editor_lib_manage", "editor_save_gate", "editor_tab_autodiscard", "editor_txt_band",
      "grid_narrow", "grid_wide", "home_screen_gone", "job_active_card",
      "job_data_first", "job_density_narrow", "job_editmode", "job_inherited",
      "job_mirror", "job_on", "job_result", "library_surface", "library_view_tabs",
      "milestone_h_overlay", "milestone_h_wave1", "modal_a11y", "modal_confirm_serial",
      "nav_count", "personalization_persist", "preserve", "preserve_real",
      "range_draft", "react_runtime", "runtime", "sheet_gate", "shell_settings",
      "theme_persist", "title_dom", "tpl_options", "url", "view_order", "workbench",
    ]),
    echo: null,
    valueDeltas: Object.freeze([]),
  }),

  offline_probe: Object.freeze({
    name: "offline_probe",
    env: "HWPX_SELFTEST_OFFLINE_PROBE",
    kind: "value-level",
    baseMode: "full",
    /** 값-수준 모드는 자기 키 목록을 갖지 않는다 — `keysForMode` 가 기반 모드에서 해소한다. */
    keys: null,
    echo: null,
    valueDeltas: Object.freeze([
      Object.freeze({
        key: "runtime",
        /** full 에서는 없다가 이 모드에서만 붙는 **중첩** 필드(최상위 키가 아니다). */
        addedFields: Object.freeze(["external_fetch_error"]),
        /** full 에서 `null` 이던 것이 실 boolean 으로 확정된다. */
        changedFields: Object.freeze([
          "external_fetch_completed", "external_fetch_succeeded", "external_fetch_blocked",
        ]),
      }),
    ]),
  }),

  geometry_only: Object.freeze({
    name: "geometry_only",
    env: "HWPX_SELFTEST_GEOMETRY_ONLY",
    kind: "key-set",
    baseMode: null,
    keys: Object.freeze(["window_geometry"]),
    echo: null,
    valueDeltas: Object.freeze([]),
  }),

  font_scale_write: Object.freeze({
    name: "font_scale_write",
    env: "HWPX_SELFTEST_SET_FONT_SCALE",
    kind: "key-set",
    baseMode: null,
    keys: Object.freeze(["font_scale_write", "set_result"]),
    /** 요청값을 그대로 되비추는 키 — 프로브가 아니라 **호스트가 먼저** 심는다(app.py:3653).
     *  그래서 브리지 시한 초과로 프로브가 실패해도 이 키는 증거에 남고 `error` 가 함께 선다. */
    echo: Object.freeze({ key: "font_scale_write", from: "HWPX_SELFTEST_SET_FONT_SCALE" }),
    valueDeltas: Object.freeze([]),
  }),

  theme_write: Object.freeze({
    name: "theme_write",
    env: "HWPX_SELFTEST_SET_THEME",
    kind: "key-set",
    baseMode: null,
    keys: Object.freeze(["theme_write", "set_result"]),
    echo: Object.freeze({ key: "theme_write", from: "HWPX_SELFTEST_SET_THEME" }),
    valueDeltas: Object.freeze([]),
  }),
});

/** 드라이버가 모드를 고르는 **순서**(app.py:3627·3650~3651·3677). 앞이 이긴다.
 *  `offline_probe` 는 이 목록에 없다 — 배타 모드가 아니라 `full` 위의 값-수준 변조기다. */
export const MODE_PRECEDENCE = Object.freeze([
  "geometry_only", "font_scale_write", "theme_write", "full",
]);

/** 값-수준 변조기 — 배타 모드와 같은 축에 두지 않는다. */
export const MODE_MODIFIERS = Object.freeze(["offline_probe"]);

/* ────────────────────────────── 클러스터 ────────────────────────────── */

/** 이식 레인 넷 + 신설 축 하나. E 만 이 레인(N08-S)이 실측으로 확정했고 B·C·D 는 각
 *  레인이 자기 키를 `SELFTEST_KEYS[key].cluster` 에 적어 채운다. R 는 레거시 이관이 아니라
 *  R2-04(#408)가 세운 React 실런타임 마커 축이다. 미할당은 **숨기지 않는다** —
 *  `unassignedClusterKeys()` 가 소리 내어 남은 것을 센다(confirm-or-alarm). */
export const CLUSTERS = Object.freeze({
  B: Object.freeze({
    id: "B",
    assigned: true,
    module: "frontend/src/selftest/probes/boot_routing_overlay.js",
  }),
  C: Object.freeze({
    id: "C",
    assigned: true,
    module: "frontend/src/selftest/probes/job.js",
  }),
  D: Object.freeze({
    id: "D",
    assigned: true,
    module: "frontend/src/selftest/probes/editor_workbench_data.js",
  }),
  E: Object.freeze({
    id: "E",
    assigned: true,
    module: "frontend/src/selftest/probes/persistence_geometry.js",
  }),
  R: Object.freeze({
    id: "R",
    assigned: true,
    module: "frontend/src/selftest/probes/react_runtime.js",
  }),
});

/* ────────────────────────────── 키 ────────────────────────────── */

/** 값 종류 — 캡처된 실 증거의 JSON 타입. */
export const VALUE_KINDS = Object.freeze([
  "boolean", "integer", "string", "array", "object",
]);

/** 소유 — 프런트가 잴 수 있는 것과 호스트만 아는 것의 국경.
 *
 *  **규칙(네 레인 공통, 이 레인이 정한다)**: 문서 안(DOM·CSSOM·computed style·레이아웃
 *  박스·viewport 상대 측정)은 `frontend`, 문서 밖(네이티브 OS 창 프레임, 프로세스, 디스크,
 *  아티팩트 정체성)은 `host`. 한 키가 둘을 섞으면 `mixed` 이고 어느 필드가 어느 쪽인지
 *  `hostFields` 에 적는다.
 */
export const OWNERS = Object.freeze(["frontend", "host", "mixed"]);

function key(descriptor) {
  return Object.freeze({
    consumedBy: Object.freeze([]),
    unconsumedReason: null,
    cluster: null,
    hostFields: Object.freeze([]),
    note: null,
    ...descriptor,
  });
}

/** 성공 경로 48키의 전수 서술. `error` 는 여기 **없다** — 부재 계약이라 따로 산다. */
export const SELFTEST_KEYS = Object.freeze({
  // ── 클러스터 E(이 레인) ──────────────────────────────────────────
  url: key({
    kind: "string", modes: ["full"], cluster: "E", owner: "host",
    consumedBy: ["tests/test_web_selftest_gate.py", "packaging/build.ps1"],
    note: "pywebview window.get_current_url() — JS 가 아니라 호스트 창 API(app.py:3714).",
  }),
  runtime: key({
    kind: "object", modes: ["full"], cluster: "E", owner: "mixed",
    hostFields: ["artifact_id", "tree_sha256"],
    consumedBy: ["tests/test_web_selftest_gate.py", "packaging/build.ps1"],
    note:
      "build.ps1:434 가 책임 수를 셀 때 **유일하게 제외**하는 키. 값-수준 모드"
      + "(offline_probe)의 유일한 무대이기도 하다.",
  }),
  chain_recovery: key({
    kind: "object", modes: ["full"], cluster: "E", owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    note: "Intent.chained 의 실패-복구 실행 성질(리뷰 5R). 정적 계약이 못 보는 축.",
  }),
  grid_narrow: key({
    kind: "object", modes: ["full"], cluster: "E", owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    note: "네이티브 window.resize(760,600) 의 **읽는 쪽**. resize 자체는 호스트 소유.",
  }),
  grid_wide: key({
    kind: "object", modes: ["full"], cluster: "E", owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    note: "네이티브 window.resize(1440,900) 의 읽는 쪽. narrow 의 음성 대조.",
  }),
  theme_persist: key({
    kind: "object", modes: ["full"], cluster: "E", owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    note: "콜드부트 되읽기(#74) — 미저장이면 data_theme=null·a_card='#ffffff'.",
  }),
  personalization_persist: key({
    kind: "object", modes: ["full"], cluster: "E", owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    note: "기본(normal/16px/240) ↔ 콜드부트 large·larger(20px/24px, master_width 333) 대조.",
  }),
  window_geometry: key({
    kind: "object", modes: ["geometry_only"], cluster: "E", owner: "host",
    consumedBy: [
      "tests/test_web_selftest_gate.py", "tests/test_personalization_contract.py",
    ],
    note:
      "screenX/screenY/outerWidth/outerHeight/screen.avail* = 네이티브 OS 창 프레임."
      + " 문서 밖이라 호스트 소유(파생 maximized_like 도 app.py:3639 에서 파이썬이 계산).",
  }),
  theme_write: key({
    kind: "string", modes: ["theme_write"], cluster: "E", owner: "host",
    unconsumedReason: "모드 에코 — 증거에 실리지만 어느 테스트도 단언하지 않는다.",
    note: "호스트가 프로브 앞에 먼저 심는 값(app.py:3678). 실패해도 남는다.",
  }),
  font_scale_write: key({
    kind: "string", modes: ["font_scale_write"], cluster: "E", owner: "host",
    consumedBy: ["tests/test_personalization_contract.py"],
    note: "app.py:3653. test_personalization_contract 가 dict 전체 동일성으로 소비한다.",
  }),
  set_result: key({
    kind: "string", modes: ["theme_write", "font_scale_write"], cluster: "E", owner: "host",
    consumedBy: [
      "tests/test_web_selftest_gate.py", "tests/test_personalization_contract.py",
    ],
    note:
      "settings.load_theme()/load_font_scale() 의 **디스크 되읽기** — 호스트 소유."
      + " 요청값과 다를 수 있다(무효 값이면 이전 값이 그대로 나온다).",
  }),

  // ── 클러스터 R(React 실런타임 — R2-04 신설 축) ──────────────────
  react_runtime: key({
    kind: "object", modes: ["full"], cluster: "R", owner: "frontend",
    consumedBy: ["packaging/build.ps1"],
    note:
      "React 마운트 커밋 마커·store 사건 마커의 존재 증명(문서 안 3판독). 위반은 프로브"
      + " throw 라 source 게이트는 error 부재 단언이 문다. 값의 크기 단언은"
      + " tests/test_web_selftest_gate.py의 module selftest result 소유.",
  }),

  // ── 아직 레인 미할당(B·C·D 가 각자 cluster 를 채운다) ─────────────
  action_roundtrip: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  data_picker: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  data_picker_buttons: key({
    kind: "boolean", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  data_sheet: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  editor_binding: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  editor_discard_immediate: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  editor_lib: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  editor_lib_manage: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  editor_save_gate: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  editor_tab_autodiscard: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  editor_txt_band: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    note:
      "teardown 실패가 out.teardown_error 로만 남고 **아무도 읽지 않는다**"
      + " — runner 의 teardown 계약이 겨누는 표본.",
    cluster: "D",
  }),
  home_screen_gone: key({
    kind: "boolean", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  job_active_card: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "C",
  }),
  job_data_first: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    note: "job_mirror 보다 **먼저** 돌아야 한다(빈 경로 스냅샷을 남긴다, app.py:3872~3876).",
    cluster: "C",
  }),
  job_density_narrow: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "C",
  }),
  job_editmode: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  job_inherited: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "C",
  }),
  job_mirror: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "C",
  }),
  job_on: key({
    kind: "boolean", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  job_result: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "C",
  }),
  library_surface: key({
    kind: "boolean", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  library_view_tabs: key({
    kind: "array", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  milestone_h_overlay: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    note: "앞뒤로 호스트 resize(720,500)·(1440,900) 가 붙는다(app.py:3974·3982).",
    cluster: "B",
  }),
  milestone_h_wave1: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  modal_a11y: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  modal_confirm_serial: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  nav_count: key({
    kind: "integer", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  preserve: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  preserve_real: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  range_draft: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  sheet_gate: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  shell_settings: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    note:
      "레거시 이관이 아니라 셸 설정 모달(토바 ⚙)의 신설 축이다 — legacySite 9991 은 실재"
      + " 줄이 아니라 순서 표식이고, theme_persist(3990) **뒤**를 강제한다(이 프로브가"
      + " 테마를 잠시 바꿨다 되돌린다).",
    cluster: "B",
  }),
  title_dom: key({
    kind: "string", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "B",
  }),
  tpl_options: key({
    kind: "array", modes: ["full"], owner: "frontend",
    unconsumedReason:
      "소비 테스트 0건. app.py:3718 이 #tplSel option 값을 읽지만 #tplSel 은 편집기 안으로"
      + " 옮겨 사망했고, 기준 실행의 값은 `[]` 다. **감도 공백을 아는 채로** 남긴다 —"
      + " 조용히 지우지도, 없던 단언을 지어내지도 않는다(그 판정은 N-09 이후의 별건).",
    note: "감도 공백: 이 키가 어떤 값이 되든 지금은 아무 게이트도 붉어지지 않는다.",
    cluster: "B",
  }),
  view_order: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
  workbench: key({
    kind: "object", modes: ["full"], owner: "frontend",
    consumedBy: ["tests/test_web_selftest_gate.py"],
    cluster: "D",
  }),
});

/* ─────────────────────── `error` — 부재 계약 ─────────────────────── */

/** `error` 는 성공 키가 **아니다**. 실패했을 때만 서고, 그때 `test_no_probe_error` 와
 *  `build.ps1:430-432` 가 각각 붉어진다. 성공 합집합에 접어 넣으면 "48 vs 49" 가 흐려지고
 *  더 나쁘게는 "있어도 되는 키"로 읽힌다 — 그래서 별도 상수다. */
export const ERROR_CONTRACT = Object.freeze({
  key: "error",
  kind: "absence",
  meaning: "프로브가 예외·시한 초과로 끝났다는 **시끄러운 표식**. 성공 경로에는 없어야 한다.",
  assertedAbsentBy: Object.freeze([
    "tests/test_web_selftest_gate.py::TestWebSelftestGate::test_no_probe_error",
    "packaging/build.ps1:430-432",
  ]),
  assertedPresentBy: Object.freeze([
    "tests/test_personalization_contract.py::test_font_scale_selftest_reports_bridge_timeout",
    "tests/test_personalization_contract.py::test_font_scale_selftest_reports_evaluation_error",
  ]),
  /** 성공 키 48 + 이 키 = 49. "44" 는 폐기된 설계 수치다(#957 에서 `preview_drawer` 퇴역으로
   *  48→47, 셸 설정 모달의 `shell_settings` 신설로 47→48). */
  unionWithError: 49,
});

/* ───────────────────── build.ps1 — 비-pytest 소유자 ───────────────────── */

/** 패키지 릴리스 빌드가 **키 집합 자체**를 소유하는 두 자리. pytest 만 보면 안 보인다. */
export const BUILD_INVARIANTS = Object.freeze({
  responsibilityCount: Object.freeze({
    source: "packaging/build.ps1:436-437",
    expected: 43,
    excludes: Object.freeze(["runtime"]),
    rule: "최상위 키에서 `runtime` 하나를 뺀 수가 정확히 43. 키를 더하거나 빼면 릴리스가 죽는다.",
  }),
  noTopLevelBooleanFalse: Object.freeze({
    source: "packaging/build.ps1:439-450",
    rule: "최상위 값이 boolean `false` 인 키가 하나라도 있으면 패키지 빌드가 throw 한다.",
    booleanKeys: Object.freeze([
      "data_picker_buttons", "home_screen_gone", "job_on", "library_surface",
    ]),
  }),
  externalFetchControlPair: Object.freeze({
    source: Object.freeze(["packaging/build.ps1:243-246", "packaging/build.ps1:348-350"]),
    packagedOnly: true,
    positive: Object.freeze({ external_fetch_succeeded: true, external_fetch_blocked: false }),
    negative: Object.freeze({ external_fetch_succeeded: false, external_fetch_blocked: true }),
    rule: "살아있는 프록시=성공 / 죽은 프록시=차단. 양성 대조가 없으면 격리 증거가 무의미하다.",
  }),
});

/** pytest 밖에서 이 계약을 붙들고 있는 자리 전수 — 설계 패킷이 놓쳤던 넷. */
export const NON_PYTEST_OWNERS = Object.freeze([
  Object.freeze({
    site: "packaging/build.ps1:436-437",
    owns: "최상위 책임 키 수 == 43(runtime 제외)",
    breaksIf: "키를 더하거나 뺀다",
  }),
  Object.freeze({
    site: "packaging/build.ps1:439-450",
    owns: "최상위 boolean false 금지",
    breaksIf: "어떤 책임이 false 로 떨어진다",
  }),
  Object.freeze({
    site: "packaging/build.ps1:451-472",
    owns: "react_runtime 형상(mounted '1' · store_rev 십진 문자열 · roots 1)",
    breaksIf: "React 마커 계약이 바뀌거나 증거에서 빠진다",
  }),
  Object.freeze({
    site: "tests/test_web_runtime_artifact.py:55",
    owns:
      "`_runtime_selftest_evidence` ~ `_selftest_drive` 사이 **소스 텍스트 구간**"
      + " — 코드 배치 자체를 단언한다(N-09 소관, 이 레인이 아니다).",
    breaksIf: "두 함수 사이에 코드가 들어가거나 함수가 옮겨진다",
  }),
]);

/* 셋째 build.ps1 항목(react_runtime 형상)은 R2-04(#408)의 신설이다 — 아래 이력의
   「사라진 넷째」와 다른 자리이니 혼동하지 않는다.

   N-11A(#423): 넷째 항목이 사라졌다. `scripts/capture_101_screenshots.py` 가 소유하던
   「`_selftest_drive` 가 교체 가능한 모듈 수준 이름일 것」은 **적힌 줄 번호부터 이미 틀렸고**
   (`:72` → 실제 `:749`), 그 사이 실제 호출 계약은 조용히 깨져 있었다. 그 책임은 이제 pytest
   가 진다 — `tests/test_live_run_contract.py` 가 봉투 하나·0-arity 진입점·등록 시점 거절을
   양성·음성으로 세운다. 원장에서 지운 것이 아니라 **소유자가 pytest 로 옮겨간** 것이다. */

/* ────────────────────────────── 산술 ────────────────────────────── */

/** 모드가 실제로 내는 키 목록. 값-수준 모드는 기반 모드에서 해소한다. */
export function keysForMode(modeName) {
  const mode = SELFTEST_MODES[modeName];
  if (!mode) throw new Error(`알 수 없는 selftest 모드: ${String(modeName)}`);
  if (mode.kind === "value-level") {
    if (!mode.baseMode) throw new Error(`값-수준 모드에 baseMode 가 없습니다: ${modeName}`);
    return keysForMode(mode.baseMode);
  }
  return mode.keys.slice();
}

/** 성공 경로 합집합 — **모드 행렬에서 계산한다**(손으로 적은 47 을 쓰지 않는다). */
export function successUnion() {
  const seen = new Set();
  for (const name of Object.keys(SELFTEST_MODES)) {
    for (const k of keysForMode(name)) seen.add(k);
  }
  return Array.from(seen).sort();
}

/** 그 키를 내는 모드 이름들(값-수준 모드 포함). */
export function modesForKey(keyName) {
  return Object.keys(SELFTEST_MODES)
    .filter((name) => keysForMode(name).includes(keyName))
    .sort();
}

export function keysForCluster(clusterId) {
  return Object.keys(SELFTEST_KEYS)
    .filter((k) => SELFTEST_KEYS[k].cluster === clusterId)
    .sort();
}

/** 아직 어느 레인도 자기 것이라 적지 않은 키 — 조용히 사라지지 않게 세어 둔다. */
export function unassignedClusterKeys() {
  return Object.keys(SELFTEST_KEYS)
    .filter((k) => SELFTEST_KEYS[k].cluster === null)
    .sort();
}

/** 소비 테스트가 0건인 키와 그 사유. `tpl_options` 가 여기 산다. */
export function unconsumedKeys() {
  return Object.keys(SELFTEST_KEYS)
    .filter((k) => SELFTEST_KEYS[k].consumedBy.length === 0)
    .sort()
    .map((k) => Object.freeze({ key: k, reason: SELFTEST_KEYS[k].unconsumedReason }));
}

/** build.ps1 이 세는 "책임" 키 — 최상위에서 `runtime` 을 뺀 것. */
export function responsibilityKeys(evidence) {
  return Object.keys(evidence)
    .filter((k) => !BUILD_INVARIANTS.responsibilityCount.excludes.includes(k))
    .sort();
}

/** 두 build.ps1 불변식을 **기계로** 확인한다. 위반은 사유를 재진술하는 배열로 돌려준다. */
export function checkBuildInvariants(evidence) {
  const violations = [];
  const responsibilities = responsibilityKeys(evidence);
  const expected = BUILD_INVARIANTS.responsibilityCount.expected;
  if (responsibilities.length !== expected) {
    violations.push({
      invariant: "responsibilityCount",
      source: BUILD_INVARIANTS.responsibilityCount.source,
      message: `책임 키 수 ${responsibilities.length} != ${expected}`,
    });
  }
  for (const name of responsibilities) {
    if (evidence[name] === false) {
      violations.push({
        invariant: "noTopLevelBooleanFalse",
        source: BUILD_INVARIANTS.noTopLevelBooleanFalse.source,
        message: `최상위 boolean false 책임: ${name}`,
      });
    }
  }
  return violations;
}

/** `error` 부재 계약. 있으면 사유를 그대로 재진술한다(숨기지 않는다). */
export function checkErrorAbsence(evidence) {
  if (!Object.prototype.hasOwnProperty.call(evidence, ERROR_CONTRACT.key)) return null;
  return {
    invariant: "errorAbsence",
    source: ERROR_CONTRACT.assertedAbsentBy.slice(),
    message: String(evidence[ERROR_CONTRACT.key]),
  };
}
