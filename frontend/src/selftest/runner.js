/* N-08 selftest 프로브 하니스 — 프로토콜 중립. **이식의 급소는 여기다.**
 *
 * 오늘의 기제(app.py:3502~3506, 호출 자리 10곳)는 이렇게 산다:
 *   ① SETUP 프로브가 돌면서 결과를 전역 `__<이름>`(창 객체 위) 에 **비동기로 쌓는다**,
 *   ② 파이썬이 `evaluate_js("!!window." + flag)` 를 **50회 × 50ms = 2.5초** 폴링한다,
 *   ③ 한 번에 `json.loads(evaluate_js(expr))` 로 회수한다.
 *
 * 그대로 옮기면 안 되는 결함 둘:
 *
 *   **(가) 폴링 만료에 `else` 가 없다.** 시한이 지나도 경보 없이 흘러가 `window` 에 놓인
 *   **모양은 맞지만 낡은** 객체를 그대로 회수한다. 74개 테스트 중 `pending is False` 를
 *   단언하는 것은 둘뿐이고, 비동기 키 12개는 조용히 만료될 수 있는 시한 뒤에 읽힌다.
 *   계측 층의 confirm-or-alarm 위반이다 — 이 러너는 **시한 초과를 시끄럽게 실패**시키고
 *   부분 결과를 절대 내보내지 않는다. "완주했는가"는 선택이 아니라 **구조**다.
 *
 *   **(나) 넓은 catch 가 실패를 정상값으로 바꾼다.** 상수 24개에 걸친 catch 40곳이
 *   `catch (e) { out.error = String(e) }` 를 하고, 그중 몇몇 키는 `error is None` 단언조차
 *   없다. 그래서 "프로브가 실패했다" 와 "프로브가 false 를 쟀다" 가 구별되지 않는다.
 *   이 러너의 오류는 `{probe, phase, code, message}` 구조체이고, 실패한 프로브의 키는
 *   결과에 **실리지 않는다**.
 *
 * 그리고 상태 인계 방식만 바꾼다: 프로브는 결과를 **반환**하고, 러너가 들고 있는다.
 * 창 객체 위의 `__*` 스태시는 (i) 전역 쓰기 금지에 정면으로 걸리고 (ii) 번들러 이름 변경 뒤
 * 문자열 보간으로 만든 전역 조회가 조용히 빗나간다 — 선언은 살고 결과는 죽는 그 결함류다.
 *
 * 이 모듈은 **비활성(inert)** 이다. 제품 그래프 어디에서도 import 하지 않고 전역을 쓰지 않는다.
 */

/* ────────────────────────── 오류 어휘 ────────────────────────── */

/** 오류가 난 **국면**. 넓은 catch 대신 이 축으로 실패를 갈라 본다. */
export const PROBE_PHASES = Object.freeze([
  "registration", // 등록·계획 시점(계약 위반)
  "precondition", // 측정 전 전제 대기
  "setup",        // 프로브 준비
  "run",          // 측정
  "host",         // 호스트에 요청한 연산
  "teardown",     // 정리
  "emit",         // 반환값 모양 확정
]);

export const ERROR_CODES = Object.freeze({
  DEADLINE_EXCEEDED: "deadline_exceeded",
  PREDICATE_THREW: "predicate_threw",
  PROBE_THREW: "probe_threw",
  TEARDOWN_FAILED: "teardown_failed",
  HOST_REFUSED: "host_refused",
  SHAPE_MISMATCH: "shape_mismatch",
  INCOMPLETE: "probe_incomplete",
  CONTRACT: "contract_violation",
  SKIPPED_AFTER_TEARDOWN: "skipped_after_teardown_failure",
});

/** 구조화 오류. `message` 는 사람이 읽는 재진술이고 `code` 는 기계가 가른다. */
export class SelftestProbeError extends Error {
  constructor({ probe, phase, code, message }) {
    super(`[${probe}/${phase}/${code}] ${message}`);
    this.name = "SelftestProbeError";
    this.probe = probe;
    this.phase = phase;
    this.code = code;
    this.detail = message;
  }

  /** 보고서에 싣는 평평한 모양 — `{probe, phase, code, message}` 딱 그것. */
  toRecord() {
    return { probe: this.probe, phase: this.phase, code: this.code, message: this.detail };
  }
}

function probeError(probe, phase, code, message) {
  return new SelftestProbeError({ probe, phase, code, message });
}

function describeThrown(value) {
  if (value instanceof Error) return String(value.message || value);
  return String(value);
}

/* ────────────────────────── 호스트 소유 연산 ────────────────────────── */

/** 프런트가 **할 수 없는** 것들. 러너는 이것들을 호스트에 **요청**할 뿐 스스로 하지 않는다.
 *  국경 규칙: 문서 안(DOM·CSSOM·computed style·레이아웃)은 프런트, 문서 밖(네이티브 창
 *  프레임·프로세스·디스크·아티팩트 정체성)은 호스트. */
export const HOST_OPS = Object.freeze([
  "mode_select",       // 환경변수 → 모드 선택
  "input_select",      // 모드 입력값(테마 이름·배율 이름)
  "global_deadline",   // 프로세스 전체 시한(90초)
  "window_resize",     // 네이티브 창 크기 변경 6회
  "window_geometry",   // 네이티브 OS 창 프레임 측정(screenX/outerWidth/screen.avail*)
  "current_url",       // pywebview window.get_current_url()
  "artifact_identity", // artifact_id · tree_sha256
  "settings_readback", // settings.json 디스크 되읽기(load_theme/load_font_scale)
  "output_write",      // 증거 파일 쓰기
  "window_destroy",    // 정식 종료
  "packaged_process",  // 동결 exe 프로세스 조율(build.ps1)
]);

/* ────────────────────────── 시간 예산 ────────────────────────── */

/** 오늘의 프로브별 시한(ms). **늘리지 않는다** — 데이터로 적었으니 기계가 센다. */
export const LEGACY_DEADLINES_MS = Object.freeze({
  /** `_probe_late` 공용 폴링(50 × 50ms). 호출 자리 10곳이 이 예산을 쓴다. */
  __probe_late__: 2500,
  action_roundtrip: 10000,
  view_order: 6000,
  data_sheet: 6000,
  range_draft: 6000,
  chain_recovery: 5000,
  /** 오프라인 프로브 정착(app.py:3590). `runtime` 키 안에서만 쓰인다. */
  runtime: 8000,
  window_geometry: 10000,
  /** 브리지 준비 폴링(app.py:3656·3687) + 디스크 반영 폴링(app.py:3668·3700). */
  theme_write: 25000,
  font_scale_write: 25000,
});

/** 조건 없는 고정 sleep — 실측으로 확인한 자리들(ms). */
export const LEGACY_FIXED_SLEEPS_MS = Object.freeze({
  "app.py:3709 드라이버 진입": 4500,
  "app.py:3633 네이티브 최대화/복원 반영": 400,
  "app.py:3856 resize(760,600) 재배치": 600,
  "app.py:3859 resize(1440,900) 재배치": 600,
  "app.py:3864 SheetPicker.choose 2회차 마이크로태스크": 800,
  "app.py:3870 initial() 해소 + 렌더 안정": 1200,
  "app.py:3975 resize(720,500) 재배치": 300,
  "app.py:3977 overlay setup 정착": 100,
  "app.py:3983 resize(1440,900) 복귀": 300,
});

/** 오케스트레이터 실측 총량. 개별 합이 아니라 **측정된 기준선**이다 — 재유도하지 않는다. */
export const LEGACY_BUDGET = Object.freeze({
  fixedSleepTotalMs: 9800,
  worstCaseMs: 68000,
  processTimeoutMs: 90000, // tests/test_web_selftest_gate.py:31
  headroomMs: 22000,
});

/* ────────────────────────── 등록 계약 ────────────────────────── */

/** 프로브 정의의 필수 필드. B·C·D 레인이 그대로 따른다. */
const REQUIRED_FIELDS = Object.freeze([
  "name", "keys", "cluster", "owner", "modes", "legacySite", "deadlineMs",
]);

const OWNERS = Object.freeze(["frontend", "host"]);

function assertContract(condition, name, message) {
  if (!condition) throw probeError(name, "registration", ERROR_CODES.CONTRACT, message);
}

function normalizeDefinition(def, index, taken) {
  const name = def && typeof def.name === "string" ? def.name : `#${index}`;
  assertContract(def && typeof def === "object", name, "프로브 정의가 객체가 아닙니다.");
  for (const field of REQUIRED_FIELDS) {
    assertContract(
      Object.prototype.hasOwnProperty.call(def, field),
      name,
      `필수 필드 누락: ${field}`,
    );
  }
  assertContract(typeof def.name === "string" && def.name.length > 0, name, "name 이 비었습니다.");
  assertContract(!taken.names.has(def.name), name, "같은 이름의 프로브가 이미 있습니다.");
  assertContract(
    Array.isArray(def.keys) && def.keys.length > 0
      && def.keys.every((k) => typeof k === "string" && k.length > 0),
    name,
    "keys 는 비어 있지 않은 문자열 배열이어야 합니다.",
  );
  /* 키 충돌은 여기서 세지 않는다 — 모드가 다르면 같은 키를 다른 프로브가 낼 수 있다
     (`set_result` 을 theme_write·font_scale_write 두 프로브가 각자 낸다). 한 모드 안에서의
     충돌만 결함이고, 그 판정은 `plan(mode)` 이 진다. */
  assertContract(typeof def.cluster === "string" && def.cluster.length > 0, name, "cluster 가 비었습니다.");
  assertContract(OWNERS.includes(def.owner), name, `owner 는 ${OWNERS.join("|")} 중 하나입니다.`);
  assertContract(
    Array.isArray(def.modes) && def.modes.length > 0
      && def.modes.every((m) => typeof m === "string" && m.length > 0),
    name,
    "modes 는 비어 있지 않은 문자열 배열이어야 합니다.",
  );
  assertContract(
    Number.isInteger(def.legacySite) && def.legacySite > 0,
    name,
    "legacySite 는 app.py 의 호출 자리 줄 번호(양의 정수)여야 합니다 — 클러스터를 넘는"
    + " 실행 순서를 이 숫자가 잇습니다.",
  );
  assertContract(
    Number.isInteger(def.deadlineMs) && def.deadlineMs >= 0,
    name,
    "deadlineMs 는 0 이상의 정수여야 합니다.",
  );

  const legacy = LEGACY_DEADLINES_MS[def.name];
  if (legacy === undefined) {
    assertContract(
      typeof def.deadlineRationale === "string" && def.deadlineRationale.length > 0,
      name,
      "레거시 시한 표에 없는 프로브는 deadlineRationale 을 적어야 합니다 —"
      + " 예산은 조용히 늘지 않습니다.",
    );
  } else {
    assertContract(
      def.deadlineMs <= legacy,
      name,
      `deadlineMs ${def.deadlineMs} 가 레거시 예산 ${legacy} 를 넘습니다 — 예산은 늘리지 않습니다.`,
    );
  }

  const after = def.after === undefined ? [] : def.after;
  assertContract(
    Array.isArray(after) && after.every((a) => typeof a === "string"),
    name,
    "after 는 프로브 이름 문자열 배열이어야 합니다.",
  );

  const requiresHost = def.requiresHost === undefined ? [] : def.requiresHost;
  assertContract(
    Array.isArray(requiresHost) && requiresHost.every((op) => HOST_OPS.includes(op)),
    name,
    `requiresHost 는 HOST_OPS(${HOST_OPS.join(", ")}) 안에서만 고릅니다.`,
  );

  const hostSetup = def.hostSetup === undefined ? null : def.hostSetup;
  if (hostSetup !== null) {
    assertContract(
      hostSetup && typeof hostSetup === "object" && HOST_OPS.includes(hostSetup.op),
      name,
      "hostSetup 은 `{op, payload}` 이고 op 는 HOST_OPS 안에 있어야 합니다.",
    );
    assertContract(
      requiresHost.includes(hostSetup.op),
      name,
      `hostSetup.op(${hostSetup.op}) 를 requiresHost 에도 적어야 합니다 — 선언과 요청은 같이 삽니다.`,
    );
  }

  const settleBeforeMs = def.settleBeforeMs === undefined ? 0 : def.settleBeforeMs;
  const cooldownAfterMs = def.cooldownAfterMs === undefined ? 0 : def.cooldownAfterMs;
  for (const [label, value, reasonField] of [
    ["settleBeforeMs", settleBeforeMs, "settleReason"],
    ["cooldownAfterMs", cooldownAfterMs, "cooldownReason"],
  ]) {
    assertContract(Number.isInteger(value) && value >= 0, name, `${label} 은 0 이상의 정수입니다.`);
    if (value > 0) {
      assertContract(
        typeof def[reasonField] === "string" && def[reasonField].length > 0,
        name,
        `${label} > 0 이면 ${reasonField} 로 **왜 기다리는지**를 적습니다 —`
        + " 이유 없는 sleep 은 다음 이식에서 조용히 사라지거나 조용히 늘어납니다.",
      );
    }
  }

  if (def.owner === "host") {
    assertContract(
      typeof def.hostOp === "string" && HOST_OPS.includes(def.hostOp),
      name,
      "host 소유 프로브는 HOST_OPS 안의 hostOp 를 지정해야 합니다.",
    );
    assertContract(def.run === undefined, name, "host 소유 프로브는 run 을 가질 수 없습니다.");
    assertContract(
      def.keys.length === 1,
      name,
      "host 소유 프로브는 키를 정확히 하나 냅니다(요청 하나 = 값 하나).",
    );
  } else {
    assertContract(typeof def.run === "function", name, "frontend 소유 프로브는 run 이 필요합니다.");
    assertContract(def.hostOp === undefined, name, "frontend 소유 프로브에 hostOp 를 둘 수 없습니다.");
  }

  for (const hook of ["precondition", "setup", "teardown"]) {
    assertContract(
      def[hook] === undefined || typeof def[hook] === "function",
      name,
      `${hook} 은 함수여야 합니다.`,
    );
  }
  assertContract(
    def.completionField === undefined || typeof def.completionField === "string",
    name,
    "completionField 는 문자열입니다.",
  );

  /* 러너의 감시견은 **마지막 안전망**이다. 시한 초과를 스스로 값으로 확정하는 프로브
     (오프라인 대조가 그렇다 — build.ps1:348-350 이 그 표식 문자열을 읽는다)가 있으면
     감시견이 그 분기를 가로채 대조가 사라진다. 그런 프로브는 명시로 빠지되, **어떻게
     경보하는지**를 적어야 한다. 조용히 빠지는 길은 없다. */
  const handlesOwnDeadline = def.handlesOwnDeadline === true;
  if (handlesOwnDeadline) {
    assertContract(
      typeof def.deadlineHandling === "string" && def.deadlineHandling.length > 0,
      name,
      "handlesOwnDeadline 프로브는 deadlineHandling 으로 자기 경보 방식을 적어야 합니다.",
    );
  }

  taken.names.add(def.name);

  return Object.freeze({
    name: def.name,
    keys: Object.freeze(def.keys.slice()),
    cluster: def.cluster,
    owner: def.owner,
    modes: Object.freeze(def.modes.slice()),
    legacySite: def.legacySite,
    deadlineMs: def.deadlineMs,
    deadlineRationale: def.deadlineRationale || null,
    handlesOwnDeadline,
    deadlineHandling: def.deadlineHandling || null,
    after: Object.freeze(after.slice()),
    afterReason: def.afterReason || null,
    requiresHost: Object.freeze(requiresHost.slice()),
    hostSetup: hostSetup === null ? null : Object.freeze({ ...hostSetup }),
    settleBeforeMs,
    settleReason: def.settleReason || null,
    cooldownAfterMs,
    cooldownReason: def.cooldownReason || null,
    hostOp: def.hostOp || null,
    hostPayload: def.hostPayload === undefined ? null : def.hostPayload,
    completionField: def.completionField || null,
    precondition: def.precondition || null,
    preconditionWhat: def.preconditionWhat || "전제",
    setup: def.setup || null,
    run: def.run || null,
    teardown: def.teardown || null,
    note: def.note || null,
    index,
  });
}

/* ────────────────────────── 러너 ────────────────────────── */

/** 호스트가 주입하는 능력. **전역에서 주워 오지 않는다** — `push` 도 인자다.
 *
 *  `{ doc, win, push, services, host: { request, provides }, now, sleep }`
 *   - `doc` / `win`  : 측정 표면(문서 안). 쓰기용이 아니라 재는 용도다.
 *   - `push`         : 배포된 푸시 진입점(전역 `__push` 와 같은 것). 13개 상수가 이걸로
 *                      실렌더를 몬다. 전역 조회가 아니라 주입이라, 테스트에서 그대로 갈린다.
 *   - `services`     : ESM 서비스 참조(Intent·Modal·Theme·Personalization …).
 *   - `host.request(op, payload)` : HOST_OPS 요청 창구.
 *   - `host.provides`: 이 호스트가 실제로 대는 op 목록. 없는 op 를 요구하면 계획이 붉어진다.
 *   - `now()` / `sleep(ms)` : 시계 주입. 테스트에서 가상 시계로 갈아 끼운다.
 */
export function createSelftestRunner(capabilities) {
  const caps = capabilities || {};
  const missing = ["doc", "win", "push", "host", "now", "sleep"].filter((f) => !caps[f]);
  if (missing.length > 0) {
    throw probeError(
      "<runner>", "registration", ERROR_CODES.CONTRACT,
      `주입 누락: ${missing.join(", ")} — 러너는 전역에서 능력을 줍지 않습니다.`,
    );
  }
  if (typeof caps.host.request !== "function") {
    throw probeError(
      "<runner>", "registration", ERROR_CODES.CONTRACT,
      "host.request(op, payload) 가 없습니다.",
    );
  }
  const provides = Array.isArray(caps.host.provides) ? caps.host.provides.slice() : HOST_OPS.slice();
  const services = caps.services || {};
  const now = caps.now;
  const sleep = caps.sleep;
  const pollIntervalMs = Number.isInteger(caps.pollIntervalMs) ? caps.pollIntervalMs : 50;

  const registered = [];
  const taken = { names: new Set() };

  function register(def) {
    const normalized = normalizeDefinition(def, registered.length, taken);
    registered.push(normalized);
    return normalized;
  }

  function registerAll(defs) {
    return (defs || []).map(register);
  }

  function probes() {
    return registered.slice();
  }

  /** 모드에 참여하는 프로브를 **실행 순서**로 세운다.
   *  1차 = `after` 위상 정렬(잃으면 조용히 틀리는 축), 동률은 `legacySite` 오름차순.
   *  클러스터가 서로를 몰라도 `legacySite` 가 네 레인을 한 순서로 잇는다. */
  function plan(mode) {
    const planned = registered.filter((p) => p.modes.includes(mode));
    const byName = new Map(planned.map((p) => [p.name, p]));

    const owner = new Map();
    for (const p of planned) {
      for (const k of p.keys) {
        if (owner.has(k)) {
          throw probeError(
            p.name, "registration", ERROR_CODES.CONTRACT,
            `모드 ${mode} 에서 키 ${k} 를 ${owner.get(k)} 와 함께 냅니다 — 한 키의 생산자는 하나입니다.`,
          );
        }
        owner.set(k, p.name);
      }
    }

    for (const p of planned) {
      for (const dep of p.after) {
        if (!byName.has(dep)) {
          throw probeError(
            p.name, "registration", ERROR_CODES.CONTRACT,
            `after 가 가리키는 ${dep} 가 모드 ${mode} 의 계획에 없습니다 —`
            + " 순서 제약을 잃은 채로 돌지 않습니다.",
          );
        }
      }
      for (const op of p.requiresHost) {
        if (!provides.includes(op)) {
          throw probeError(
            p.name, "registration", ERROR_CODES.HOST_REFUSED,
            `호스트가 ${op} 를 대지 않습니다.`,
          );
        }
      }
      if (p.owner === "host" && !provides.includes(p.hostOp)) {
        throw probeError(
          p.name, "registration", ERROR_CODES.HOST_REFUSED,
          `호스트가 ${p.hostOp} 를 대지 않습니다.`,
        );
      }
    }

    const indegree = new Map(planned.map((p) => [p.name, 0]));
    const dependents = new Map(planned.map((p) => [p.name, []]));
    for (const p of planned) {
      for (const dep of p.after) {
        indegree.set(p.name, indegree.get(p.name) + 1);
        dependents.get(dep).push(p.name);
      }
    }

    const ready = planned.filter((p) => indegree.get(p.name) === 0);
    const order = [];
    const rank = (a, b) => (a.legacySite - b.legacySite) || (a.index - b.index);
    while (ready.length > 0) {
      ready.sort(rank);
      const next = ready.shift();
      order.push(next);
      for (const depName of dependents.get(next.name)) {
        indegree.set(depName, indegree.get(depName) - 1);
        if (indegree.get(depName) === 0) ready.push(byName.get(depName));
      }
    }

    if (order.length !== planned.length) {
      const stuck = planned.filter((p) => !order.includes(p)).map((p) => p.name).sort();
      throw probeError(
        stuck[0] || "<plan>", "registration", ERROR_CODES.CONTRACT,
        `after 에 순환이 있습니다: ${stuck.join(", ")}`,
      );
    }
    return order;
  }

  /** 모드의 최악 시간 예산 — 시한 + 대기의 합. 레거시 기준선과 비교하려고 데이터로 낸다. */
  function budgetMs(mode) {
    return plan(mode).reduce(
      (total, p) => total + p.deadlineMs + p.settleBeforeMs + p.cooldownAfterMs,
      0,
    );
  }

  function makeContext(probe, mode, options, waitState) {
    const start = now();
    const ctx = {
      probe: probe.name,
      mode,
      deadlineMs: probe.deadlineMs,
      keys: probe.keys,
      doc: caps.doc,
      win: caps.win,
      push: caps.push,
      services,
      input: options.input === undefined ? null : options.input,
      flags: options.flags || {},
      state: {},
      now,
      sleep,
      elapsedMs() { return now() - start; },
      remainingMs() { return probe.deadlineMs - (now() - start); },
      host(op, payload) {
        if (!probe.requiresHost.includes(op) && probe.hostOp !== op) {
          return Promise.reject(probeError(
            probe.name, "host", ERROR_CODES.CONTRACT,
            `선언하지 않은 호스트 연산 ${op} 를 요청했습니다 — requiresHost 에 적으십시오.`,
          ));
        }
        return Promise.resolve(caps.host.request(op, payload));
      },
      fail(code, message) {
        throw probeError(probe.name, "run", code, message);
      },
      async waitFor(predicate, opts) {
        const conf = opts || {};
        const timeoutMs = conf.timeoutMs === undefined ? probe.deadlineMs : conf.timeoutMs;
        const what = conf.what || "조건";
        const phase = conf.phase || "run";
        const began = now();
        /* 바깥 감시견이 같은 시각에 깨더라도 **무엇을 기다리다 죽었는지**는 남는다.
           레거시의 진단 공백(어느 폴링이 만료됐는지 알 수 없다)을 여기서 닫는다. */
        waitState.what = what;
        for (;;) {
          let ok;
          try {
            ok = await predicate();
          } catch (thrown) {
            waitState.what = null;
            throw probeError(
              probe.name, phase, ERROR_CODES.PREDICATE_THREW,
              `${what} 판정이 던졌습니다: ${describeThrown(thrown)}`,
            );
          }
          if (ok) {
            waitState.what = null;
            return true;
          }
          if (now() - began >= timeoutMs) {
            waitState.what = null;
            throw probeError(
              probe.name, phase, ERROR_CODES.DEADLINE_EXCEEDED,
              `${what} 시한 ${timeoutMs}ms 초과 — 낡은 부분 결과를 내보내지 않고 실패로 확정합니다.`,
            );
          }
          await sleep(pollIntervalMs);
        }
      },
    };
    return ctx;
  }

  /** 시한 감시. 프로브가 스스로 끝나지 않아도 러너는 반드시 끝난다. */
  function withDeadline(probe, phase, work, waitState) {
    if (probe.deadlineMs <= 0 || probe.handlesOwnDeadline) return work();
    let done = false;
    const guarded = Promise.resolve()
      .then(work)
      .then((value) => { done = true; return value; });
    const watchdog = sleep(probe.deadlineMs).then(() => {
      if (done) return new Promise(() => {}); // 이미 끝났으면 경주에서 빠진다.
      const waiting = waitState && waitState.what ? ` (대기 중: ${waitState.what})` : "";
      throw probeError(
        probe.name, phase, ERROR_CODES.DEADLINE_EXCEEDED,
        `시한 ${probe.deadlineMs}ms 초과${waiting} — 부분 상태를 결과로 내지 않습니다.`,
      );
    });
    guarded.catch(() => {});
    watchdog.catch(() => {});
    return Promise.race([guarded, watchdog]);
  }

  function validateShape(probe, value) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      throw probeError(
        probe.name, "emit", ERROR_CODES.SHAPE_MISMATCH,
        "프로브는 선언한 키를 담은 평평한 객체를 반환해야 합니다.",
      );
    }
    const produced = Object.keys(value).sort();
    const declared = probe.keys.slice().sort();
    if (produced.length !== declared.length
      || produced.some((k, i) => k !== declared[i])) {
      throw probeError(
        probe.name, "emit", ERROR_CODES.SHAPE_MISMATCH,
        `반환 키 [${produced.join(", ")}] 가 선언 [${declared.join(", ")}] 과 다릅니다.`,
      );
    }
    if (probe.completionField) {
      for (const k of declared) {
        const emitted = value[k];
        if (emitted && typeof emitted === "object"
          && emitted[probe.completionField] !== false) {
          throw probeError(
            probe.name, "emit", ERROR_CODES.INCOMPLETE,
            `${k}.${probe.completionField} 가 false 가 아닙니다 — 완주하지 않은 결과입니다.`,
          );
        }
      }
    }
    return value;
  }

  /** 모드 하나를 처음부터 끝까지 몬다. 보고서는 **항상** 돌아오고, 실패는 보고서 안에서 시끄럽다. */
  async function run(mode, options) {
    const opts = options || {};
    const order = plan(mode);
    const report = {
      ok: true,
      mode,
      order: order.map((p) => p.name),
      results: {},
      errors: [],
      skipped: [],
      timings: {},
    };
    let poisonedBy = null;

    for (const probe of order) {
      if (poisonedBy) {
        report.skipped.push({
          probe: probe.name,
          code: ERROR_CODES.SKIPPED_AFTER_TEARDOWN,
          message: `${poisonedBy} 의 정리가 실패해 뒤따르는 국면을 오염시킵니다 — 건너뜁니다.`,
        });
        continue;
      }

      const waitState = { what: null };
      const ctx = makeContext(probe, mode, opts, waitState);
      const began = now();
      let value = null;
      let failed = false;
      let started = false;

      try {
        if (probe.precondition) {
          await ctx.waitFor(() => probe.precondition(ctx), {
            what: probe.preconditionWhat,
            phase: "precondition",
            timeoutMs: probe.deadlineMs,
          });
        }
        if (probe.hostSetup) {
          started = true;
          await ctx.host(probe.hostSetup.op, probe.hostSetup.payload);
        }
        if (probe.settleBeforeMs > 0) await sleep(probe.settleBeforeMs);

        started = true;
        value = await withDeadline(probe, probe.owner === "host" ? "host" : "run", async () => {
          if (probe.setup) await probe.setup(ctx);
          if (probe.owner === "host") {
            const measured = await ctx.host(probe.hostOp, probe.hostPayload);
            return { [probe.keys[0]]: measured };
          }
          return probe.run(ctx);
        }, waitState);
        validateShape(probe, value);
      } catch (thrown) {
        failed = true;
        report.ok = false;
        report.errors.push(
          thrown instanceof SelftestProbeError
            ? thrown.toRecord()
            : {
              probe: probe.name,
              phase: "run",
              code: ERROR_CODES.PROBE_THREW,
              message: describeThrown(thrown),
            },
        );
      }

      if (started && probe.teardown) {
        try {
          await probe.teardown(ctx);
        } catch (thrown) {
          report.ok = false;
          report.errors.push({
            probe: probe.name,
            phase: "teardown",
            code: ERROR_CODES.TEARDOWN_FAILED,
            message: `정리 실패: ${describeThrown(thrown)}`,
          });
          poisonedBy = probe.name;
        }
      }

      if (!failed) {
        for (const k of probe.keys) report.results[k] = value[k];
      }
      report.timings[probe.name] = now() - began;

      if (probe.cooldownAfterMs > 0) await sleep(probe.cooldownAfterMs);
    }

    return report;
  }

  /** 보고서 → 디스크에 쓰는 증거. 실패가 있으면 `error` 가 서고, 실패한 키는 **없다**.
   *  모양만 맞고 낡은 값이 성공인 척 실리는 오늘의 경로를 여기서 끊는다. */
  function toEvidence(report, extra) {
    const evidence = { ...(extra || {}), ...report.results };
    if (report.errors.length > 0 || report.skipped.length > 0) {
      const lines = report.errors.map(
        (e) => `[${e.probe}/${e.phase}/${e.code}] ${e.message}`,
      ).concat(report.skipped.map((s) => `[${s.probe}/skipped/${s.code}] ${s.message}`));
      evidence.error = lines.join(" | ");
    }
    return evidence;
  }

  /** 계약 메타데이터만 뽑아 본다(테스트·문서용). 실행하지 않는다. */
  function describe() {
    return registered.map((p) => ({
      name: p.name,
      keys: p.keys.slice(),
      cluster: p.cluster,
      owner: p.owner,
      modes: p.modes.slice(),
      legacySite: p.legacySite,
      deadlineMs: p.deadlineMs,
      handlesOwnDeadline: p.handlesOwnDeadline,
      deadlineHandling: p.deadlineHandling,
      after: p.after.slice(),
      afterReason: p.afterReason,
      requiresHost: p.requiresHost.slice(),
      hostSetup: p.hostSetup,
      settleBeforeMs: p.settleBeforeMs,
      settleReason: p.settleReason,
      cooldownAfterMs: p.cooldownAfterMs,
      cooldownReason: p.cooldownReason,
      hostOp: p.hostOp,
      completionField: p.completionField,
      note: p.note,
    }));
  }

  return { register, registerAll, probes, plan, budgetMs, run, toEvidence, describe };
}
