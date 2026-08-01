/* N-09 시험 능력 프로토콜 — `window.__hwpxTest` 의 **JS 절반**.

   N-08 이 프로브 엔진(`runner.js` + `probes/`)을 세웠고, 그것을 실제로 돌리는 통로가 여기다.
   이 파일은 **프로토콜만** 소유한다: 누가 켤 수 있는가(핸드셰이크), 어떤 봉투가 오가는가,
   실행 하나의 수명이 어떤 상태를 지나는가. 프로브가 무엇을 재는지는 러너의 몫이고 이 모듈은
   러너를 **주입**으로만 받는다 — import 로 붙들면 프로토콜이 제품 배선을 알게 되고, 그때부터
   이 파일은 러너가 바뀔 때마다 같이 낡는다.

   ## 왜 조건부 설치인가 — 있으면 그건 제품 표면이다

   시험 훅이 제품 런타임에 서 있으면 그것은 시험 훅이 아니라 **제품 API** 다. 실사용자의
   창에서 임의의 페이지 스크립트가 그 이름으로 앱 전체를 몰 수 있고, 그 순간 "시험용이라
   문서화하지 않았다"는 말은 아무것도 막지 못한다. 그래서 규칙은 **부재**다: 정상 런타임에서
   `__hwpxTest` 는 `win` 의 own 프로퍼티로 **존재하지 않는다**. 만들었다 지우는 길은 두지
   않는다 — 지우기가 한 번 실패하면 그 잔존은 아무도 못 듣는다(선언은 살고 결과는 죽는다).

   ## 왜 핸드셰이크인가 — 페이지가 스스로 켤 수 있는 스위치는 스위치가 아니다

   쿼리스트링·`location.hash`·빌드 플래그·정적 산출물은 전부 **페이지 쪽에서 만들 수 있는**
   조건이다. 그중 하나라도 설치 조건이 되면 "호스트가 이 창을 시험용으로 띄웠다"는 사실을
   증명하지 못한다. 이 모듈이 읽는 조건은 하나뿐이다: 호스트 프로세스 메모리에만 있는 토큰을
   **한 번** 클레임했는가. 그래서 이 파일에는 `location`·`document`·`import.meta.env` 판독이
   한 글자도 없고, 그 부재를 단위 테스트가 소스 전수로 센다.

   토큰은 클로저에 남되 **아무 데도 실리지 않는다** — 봉투에도, 창에도, 로그에도. 유일한
   용도는 나가는 종결 봉투를 그 문자열로 훑어 유출을 **시끄럽게 거절**하는 것이다(주입된
   러너가 실수로 토큰을 증거에 담아도 그 실행은 통과하지 못한다).

   ## 왜 `run` 이 동기인가 — 호출자는 `evaluate_js` 뒤의 파이썬 스레드다

   `product_api.js` 머리말과 같은 이유다: Promise 를 돌려주면 그 스레드는 해소를 기다리지
   못한 채 형태를 모르는 값을 받는다. 그래서 `run` 은 **동기**이고 JSON 직렬화 가능한 봉투를
   돌려준다. 본질이 비동기인 실행은 두 박자로 접힌다 — `start` 가 "시작했다"와 `runId` 를
   즉시 주고, `poll` 이 그 뒤를 묻는다.

   ## 왜 시한을 JS 가 지는가 — 레거시 결함 (가) 를 여기서 닫는다

   `app.py` 의 `_probe_late` 는 폴링 만료에 `else` 가 없어, 시한이 지나도 경보 없이 흘러가
   **모양은 맞지만 낡은** 값을 회수했다(runner.js 머리말). 이 프로토콜에서 시한 초과는
   종결 **실패**이고, 그때 부분 결과·중간 보고서는 봉투에 실리지 않는다. 늦게 도착한 러너
   보고서도 마찬가지로 버려진다 — "완주했는가"는 선택이 아니라 구조다.

   ## 계약 v1

       window.__hwpxTest                       // Object.freeze({ version: 1, run })
       run({version: 1, action: "start", mode, input, flags})
       // -> {ok: true, action: "start", runId, state: "running", mode, deadlineMs}
       run({version: 1, action: "poll", runId})
       // -> {ok: true,  action: "poll", state: "running",   runId, elapsedMs, deadlineMs}
       // -> {ok: true,  action: "poll", state: "succeeded", runId, evidence, order, timings, …}
       // -> {ok: false, action: "poll", state: "failed",    runId, code, …}

   상태: `ABSENT`(정상 런타임) → `UNCLAIMED` → `READY` → `RUNNING` → `SUCCEEDED`|`FAILED`
   → `CONSUMED`. 종결 결과는 **정확히 한 번** 회수되고 그 뒤의 재조회는 거절이다. 실행 슬롯은
   능력 하나당 하나이고 재시작은 없다 — 한 창에서 두 번 돌아야 할 이유가 생기면 그것은 새
   프로세스가 질 일이다(조용한 재시작은 "무엇을 잰 결과인가"를 잃는다).

   검증 순서가 계약이다: 요청 형태 → **버전** → 액션 이름 → 액션 존재 → 인자 → 상태.
   버전이 액션보다 앞이다 — 미지 버전의 요청은 **해석 자체를 하지 않는다**. */

/* ────────────────────────── 계약 상수 ────────────────────────── */

/** 이 프로토콜이 말할 줄 아는 유일한 버전. 다른 값은 협상이 아니라 거절이다. */
export const SELFTEST_VERSION = 1;

/** 창에 서는 이름. 정상 런타임에는 own 프로퍼티로 **없다**. */
export const SELFTEST_GLOBAL = "__hwpxTest";

/** 액션 전수 — 순서가 곧 두 박자다. */
export const SELFTEST_ACTIONS = Object.freeze(["start", "poll"]);

/** 실행 하나의 수명. `ABSENT` 는 능력이 설치되지 않은 정상 런타임의 이름이라 슬롯 상태가
 *  아니지만, 파이썬이 같은 어휘로 읽도록 여기 함께 적는다. */
export const SELFTEST_STATES = Object.freeze({
  ABSENT: "absent",
  UNCLAIMED: "unclaimed",
  READY: "ready",
  RUNNING: "running",
  SUCCEEDED: "succeeded",
  FAILED: "failed",
  CONSUMED: "consumed",
});

/** 안정 실패 코드 — **값이 계약이다**(파이썬 어댑터가 이 문자열로 분기한다).
 *
 *  `RUN_FAILED` 는 제안 목록에 없던 하나를 더한 것이다. 프로브가 실패한 실행을 `INTERNAL`
 *  로 접으면 "우리 프로토콜이 깨졌다" 와 "재려던 것이 틀렸다" 가 같은 코드가 되고, 그 둘은
 *  원인도 조치도 다르다 — 진단 축을 잃지 않으려고 이름을 하나 더 세운다. */
export const SELFTEST_ERROR_CODES = Object.freeze({
  /** 요청이 객체가 아니거나 필수 인자의 형태가 계약 밖이다(`field` 가 어느 것인지 지목). */
  MALFORMED_REQUEST: "malformed_request",
  /** `version` 이 지원 버전이 아니다(부재·0·2·비수치 포함). 이 경우 액션은 읽지 않는다. */
  UNSUPPORTED_VERSION: "unsupported_version",
  /** 계약에 없는 액션 이름이다. */
  UNKNOWN_ACTION: "unknown_action",
  /** 클레임이 없거나 토큰이 토큰의 자격을 못 갖췄다 — 능력은 **설치되지 않는다**. */
  UNAUTHORIZED: "unauthorized",
  /** 이 창에 이미 능력이 서 있다(또는 그 이름이 이미 점유돼 있다). 클레임은 일회용이다. */
  ALREADY_CLAIMED: "already_claimed",
  /** 실행이 도는 중에 다시 `start` 했다. 조용히 재시작하지 않는다. */
  ALREADY_RUNNING: "already_running",
  /** 슬롯이 없거나 `runId` 가 그 슬롯의 것이 아니다. */
  UNKNOWN_RUN: "unknown_run",
  /** 일회용 슬롯이 이미 소진됐다 — 종결 회수 뒤의 재조회, 또는 종결 뒤의 재시작. */
  ALREADY_CONSUMED: "already_consumed",
  /** JS 쪽 시한을 넘겼다. 부분 결과는 **실리지 않는다**. */
  DEADLINE_EXCEEDED: "deadline_exceeded",
  /** 프로브가 실패한 채로 실행이 끝났다 — 프로토콜은 멀쩡하고 잰 것이 틀렸다. */
  RUN_FAILED: "run_failed",
  /** 프로토콜·주입 자체가 깨졌다(러너 구성 실패·직렬화 불가·토큰 유출 등). */
  INTERNAL: "internal",
});

const CODES = SELFTEST_ERROR_CODES;
const STATES = SELFTEST_STATES;

/** 실행 하나의 JS 쪽 시한(ms) 기본값.
 *
 *  러너가 데이터로 적은 레거시 기준선은 최악 68000ms, 파이썬 게이트의 프로세스 시한은
 *  90000ms 다(`runner.js` 의 `LEGACY_BUDGET`). 그 사이에 서야 하는 이유는 하나다 —
 *  프로세스가 죽어 아무 말도 못 남기기 **전에** 구조화된 실패를 돌려주려면 JS 시한이 먼저
 *  깨어나야 한다. 같거나 크면 이 시한은 영영 발화하지 않는 죽은 선언이 된다. 저 두 수를
 *  import 로 끌어오지 않는 것은 프로토콜이 러너 상수에 묶이지 않게 하려는 것이고, 대신
 *  통합자가 `deadlineMs` 로 실제 예산을 명시할 수 있다. */
export const DEFAULT_DEADLINE_MS = 75000;

/** 토큰 최소 길이. 하한을 세지 않으면 "빈 문자열만 아니면 통과"가 되고, 그건 자격 검사가
 *  아니라 존재 검사다. 호스트는 `secrets.token_urlsafe(32)`(43자) 급을 낸다. */
export const MIN_TOKEN_LENGTH = 32;

/** `runId` 바이트 수 — 16바이트 = 32자리 16진수. */
const RUN_ID_BYTES = 16;

/* ────────────────────────── 봉투 ────────────────────────── */

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function ok(action, extras) {
  return Object.assign({ ok: true, action }, extras);
}

function fail(code, action, extras) {
  return Object.assign({ ok: false, code, action }, extras);
}

/** 던져진 것을 **평평한 기록**으로. 러너의 `SelftestProbeError` 는 자기 모양을 스스로
 *  아므로(`toRecord()`) 그것을 그대로 쓴다 — 클래스를 import 하면 프로토콜이 러너에 묶인다.
 *  스택은 싣지 않는다(내부 경로·번들 이름이 그대로 딸려 나온다). */
function describeThrown(thrown) {
  if (thrown && typeof thrown.toRecord === "function") {
    try {
      const record = thrown.toRecord();
      if (isPlainObject(record)) return record;
    } catch { /* 기록조차 실패하면 아래 일반 경로로 내려간다 */ }
  }
  const message = thrown instanceof Error ? String(thrown.message || thrown) : String(thrown);
  return { probe: null, phase: "run", code: CODES.INTERNAL, message };
}

/* ────────────────────────── 설치 ────────────────────────── */

/** 시험 능력을 **핸드셰이크에 성공했을 때만** 창에 세운다.
 *
 *  던지지 않는다 — 정상 런타임에서 클레임이 없는 것은 결함이 아니라 **기대되는 상태**이고,
 *  그때 부팅을 깨뜨리면 시험 훅이 제품 가용성을 쥐게 된다. 대신 판정을 구조화해 돌려주므로
 *  통합자는 "설치하려 했는데 못 했다" 를 경보할 수 있다.
 *
 *  주입(`ports`):
 *   - `win`         (필수) 능력을 세울 창 객체.
 *   - `claimToken`  (필수) **동기** 콜백. 호스트 왕복(pywebview 는 비동기다)은 통합자가
 *                   먼저 마치고, 여기엔 이미 받아 둔 토큰을 돌려주는 클로저를 넘긴다.
 *                   정확히 **한 번** 불린다. 문자열이 아니거나 짧으면 아무것도 설치되지 않는다.
 *   - `createRunner`(필수) `({mode, input, flags}) => runner`. **`start` 때 처음** 불린다
 *                   (설치는 러너를 만들지 않는다). 러너는 `run(mode, options)` 와
 *                   `toEvidence(report, extra)` 를 가져야 한다.
 *   - `now`         (선택) `() => number`. 기본 `Date.now`. 시한 계산에만 쓴다.
 *   - `deadlineMs`  (선택) 양의 정수. 기본 `DEFAULT_DEADLINE_MS`.
 *   - `randomBytes` (선택) `(n) => Uint8Array`. 기본은 `win.crypto.getRandomValues`.
 *                   둘 다 없으면 **설치하지 않는다** — 약한 난수로 조용히 내려가지 않는다.
 *
 *  반환: `{ok: true, installed: true, state: "ready"}` 또는 `{ok: false, code, …}`. */
export function installSelftestApi(ports) {
  const config = isPlainObject(ports) ? ports : {};
  const win = config.win;

  /* 창부터. 뒤의 판정은 전부 이 객체 위에서 뜻을 갖는다. */
  if (!win || (typeof win !== "object" && typeof win !== "function")) {
    return fail(CODES.INTERNAL, null, { field: "win" });
  }

  /* 재설치·이름 점유는 **여기서** 끊는다. 남이 먼저 그 이름에 무언가를 올려 뒀다면 그것을
     덮어쓰는 것이 아니라 거절한다 — 덮어쓰면 "누가 이 표면의 생산자인가"가 흐려진다. */
  if (Object.hasOwn(win, SELFTEST_GLOBAL)) {
    return fail(CODES.ALREADY_CLAIMED, null, { state: STATES.READY });
  }

  /* 주입 검증이 클레임보다 **먼저**다. 배선이 어긋난 채로 호스트의 일회용 클레임을 태우면
     고치고 다시 시도할 길이 사라진다 — 일회용은 마지막에 만진다. */
  const claimToken = config.claimToken;
  if (typeof claimToken !== "function") {
    return fail(CODES.INTERNAL, null, { field: "claimToken" });
  }
  const createRunner = config.createRunner;
  if (typeof createRunner !== "function") {
    return fail(CODES.INTERNAL, null, { field: "createRunner" });
  }
  const now = config.now === undefined ? Date.now : config.now;
  if (typeof now !== "function") {
    return fail(CODES.INTERNAL, null, { field: "now" });
  }
  const deadlineMs = config.deadlineMs === undefined ? DEFAULT_DEADLINE_MS : config.deadlineMs;
  if (!Number.isInteger(deadlineMs) || deadlineMs <= 0) {
    return fail(CODES.INTERNAL, null, { field: "deadlineMs" });
  }
  const randomBytes = resolveRandomBytes(config.randomBytes, win);
  if (randomBytes === null) {
    return fail(CODES.INTERNAL, null, { field: "randomBytes" });
  }

  /* 클레임 — 이 프로토콜이 읽는 **유일한** 설치 조건이다. */
  let token;
  try {
    token = claimToken();
  } catch {
    /* 클레임이 던진 이유는 싣지 않는다(호스트 내부 문안이 그대로 딸려 나온다).
       "권한 없음" 하나로 충분하고, 서사는 호스트 쪽 로그가 진다. */
    return fail(CODES.UNAUTHORIZED, null, { field: "claimToken", state: STATES.UNCLAIMED });
  }
  if (token !== null && typeof token === "object" && typeof token.then === "function") {
    /* 비동기 클레임은 인증 실패가 아니라 **배선 실패**다. 두 사건을 같은 코드로 접으면
       통합자는 토큰이 틀린 줄 알고 엉뚱한 곳을 판다. */
    return fail(CODES.INTERNAL, null, { field: "claimToken", reason: "async" });
  }
  if (typeof token !== "string" || token.length < MIN_TOKEN_LENGTH) {
    return fail(CODES.UNAUTHORIZED, null, { field: "token", state: STATES.UNCLAIMED });
  }

  const api = Object.freeze({
    version: SELFTEST_VERSION,
    run: createRun({ token, createRunner, now, deadlineMs, randomBytes }),
  });

  /* 쓰기 불가·재정의 불가·열거 불가. 대입도 재정의도 **둘 다** 실패해야 이 표면의 생산자가
     하나로 남는다(ESM 은 strict 이므로 대입은 조용한 무시가 아니라 TypeError 다). */
  Object.defineProperty(win, SELFTEST_GLOBAL, {
    value: api,
    writable: false,
    configurable: false,
    enumerable: false,
  });

  return ok(null, { installed: true, state: STATES.READY });
}

/** 난수 공급자 결정 — 주입이 우선, 없으면 창의 CSPRNG. 둘 다 없으면 `null` 이고 그 뜻은
 *  "설치하지 않는다" 다. `Math.random` 으로 내려가는 길은 두지 않는다. */
function resolveRandomBytes(injected, win) {
  if (typeof injected === "function") return injected;
  const crypto = win.crypto;
  if (crypto && typeof crypto.getRandomValues === "function") {
    return (count) => crypto.getRandomValues(new Uint8Array(count));
  }
  return null;
}

/* ────────────────────────── 상태 기계 ────────────────────────── */

/** 봉투 하나를 받는 **동기** 진입점을 만든다. 슬롯은 이 클로저가 소유하고 창에 새지 않는다. */
function createRun({ token, createRunner, now, deadlineMs, randomBytes }) {
  /* 실행 슬롯 — 능력 하나당 하나. `null` 이면 아직 `start` 가 없었다는 뜻이다. */
  let slot = null;

  function expired() {
    return now() - slot.startedAt >= deadlineMs;
  }

  /** 시한을 **관측 시점에** 확정한다. 타이머를 걸지 않는 이유: 타이머는 창이 얼어 있으면
   *  같이 얼고, 그때의 침묵은 "아직 도는 중" 과 구별되지 않는다. 폴링이 곧 관측이므로
   *  관측할 때마다 세면 시한은 반드시 발화한다. */
  function settleDeadlineIfExpired() {
    if (slot === null || slot.state !== STATES.RUNNING) return;
    if (!expired()) return;
    slot.state = STATES.FAILED;
    slot.settledAt = now();
    slot.failure = { code: CODES.DEADLINE_EXCEEDED };
  }

  /** 러너가 보고서를 냈다. 늦게 왔으면 **버린다** — 시한 뒤에 도착한 완주는 완주가 아니다. */
  function onReport(report) {
    if (slot === null || slot.state !== STATES.RUNNING) return;
    if (expired()) {
      settleDeadlineIfExpired();
      return;
    }
    slot.settledAt = now();
    if (!isPlainObject(report)) {
      slot.state = STATES.FAILED;
      slot.failure = { code: CODES.INTERNAL, field: "report" };
      return;
    }
    slot.report = report;
    slot.state = report.ok === true ? STATES.SUCCEEDED : STATES.FAILED;
  }

  /** 러너가 던졌다(계획 위반·주입 누락 등). 보고서 자체가 없으므로 증거도 없다. */
  function onThrown(thrown) {
    if (slot === null || slot.state !== STATES.RUNNING) return;
    if (expired()) {
      settleDeadlineIfExpired();
      return;
    }
    slot.settledAt = now();
    slot.state = STATES.FAILED;
    slot.failure = { code: CODES.INTERNAL, errors: [describeThrown(thrown)] };
  }

  function start(request) {
    const mode = request.mode;
    if (typeof mode !== "string" || mode === "") {
      return fail(CODES.MALFORMED_REQUEST, "start", { field: "mode" });
    }
    const flags = request.flags === undefined || request.flags === null ? {} : request.flags;
    if (!isPlainObject(flags)) {
      return fail(CODES.MALFORMED_REQUEST, "start", { field: "flags" });
    }
    const input = request.input === undefined ? null : request.input;

    if (slot !== null) {
      settleDeadlineIfExpired();
      /* 도는 중이면 "도는 중" 이고, 끝났으면 슬롯이 **소진** 된 것이다. 어느 쪽도 조용한
         재시작으로 접지 않는다 — 재시작은 무엇을 잰 결과인지를 잃는 가장 조용한 길이다. */
      const code = slot.state === STATES.RUNNING ? CODES.ALREADY_RUNNING : CODES.ALREADY_CONSUMED;
      return fail(code, "start", { state: slot.state });
    }

    const runId = makeRunId(randomBytes);
    slot = {
      runId,
      mode,
      startedAt: now(),
      settledAt: null,
      state: STATES.RUNNING,
      report: null,
      failure: null,
      runner: null,
    };

    /* 발사 후 망각. `await` 하지 않으므로 호출 스레드는 여기서 곧장 돌아간다. 러너 구성도
       이 체인 안에서 하므로 구성 실패가 `start` 를 깨뜨리지 않고 **폴링에서 보이는 실패**가
       된다 — 시작 자체가 던지면 파이썬은 runId 없이 아무것도 물을 수 없다. */
    Promise.resolve()
      .then(() => {
        const runner = createRunner({ mode, input, flags });
        if (!runner || typeof runner.run !== "function"
          || typeof runner.toEvidence !== "function") {
          throw new Error("주입된 러너에 run/toEvidence 가 없습니다.");
        }
        slot.runner = runner;
        return runner.run(mode, { input, flags });
      })
      .then(onReport, onThrown);

    return ok("start", {
      runId,
      state: STATES.RUNNING,
      mode,
      deadlineMs,
    });
  }

  function poll(request) {
    const runId = request.runId;
    if (typeof runId !== "string" || runId === "") {
      return fail(CODES.MALFORMED_REQUEST, "poll", { field: "runId" });
    }
    if (slot === null) {
      return fail(CODES.UNKNOWN_RUN, "poll", { state: STATES.READY });
    }
    if (slot.runId !== runId) {
      /* 어느 id 를 기대했는지는 **말하지 않는다** — 되물어 맞히는 길을 열지 않는다. */
      return fail(CODES.UNKNOWN_RUN, "poll", { state: slot.state });
    }

    settleDeadlineIfExpired();

    if (slot.state === STATES.CONSUMED) {
      return fail(CODES.ALREADY_CONSUMED, "poll", { runId, state: STATES.CONSUMED });
    }
    if (slot.state === STATES.RUNNING) {
      return ok("poll", {
        runId,
        state: STATES.RUNNING,
        elapsedMs: now() - slot.startedAt,
        deadlineMs,
      });
    }
    return consume(runId);
  }

  /** 종결 결과 회수 — **정확히 한 번**. 봉투를 다 세운 뒤에 상태를 옮기므로, 봉투를 세다
   *  실패해도 그 실패가 곧 소진이고 재조회로 다시 시도되지 않는다(같은 실패를 두 번 세는
   *  것보다 한 번 시끄럽게 죽는 편이 진단이 쉽다). */
  function consume(runId) {
    const base = {
      runId,
      state: slot.state,
      elapsedMs: (slot.settledAt === null ? now() : slot.settledAt) - slot.startedAt,
      deadlineMs,
    };
    let envelope;
    if (slot.state === STATES.SUCCEEDED) {
      envelope = successEnvelope(base);
    } else if (slot.failure !== null) {
      envelope = fail(slot.failure.code, "poll", Object.assign({}, base, {
        state: STATES.FAILED,
        errors: slot.failure.errors || [],
        field: slot.failure.field,
      }));
      if (envelope.field === undefined) delete envelope.field;
    } else {
      envelope = failedReportEnvelope(base);
    }
    slot.state = STATES.CONSUMED;
    slot.report = null;
    slot.runner = null;

    const leak = auditEnvelope(envelope, token);
    if (leak !== null) {
      /* 직렬화 불가이거나 토큰이 실려 있다. 어느 쪽이든 이 봉투는 나가지 않는다 —
         `field` 하나만 남기고 내용은 통째로 버린다. */
      return fail(CODES.INTERNAL, "poll", {
        runId, state: STATES.CONSUMED, field: leak,
      });
    }
    return envelope;
  }

  function successEnvelope(base) {
    const report = slot.report;
    let evidence;
    try {
      evidence = slot.runner.toEvidence(report, null);
    } catch (thrown) {
      return fail(CODES.INTERNAL, "poll", Object.assign({}, base, {
        state: STATES.FAILED,
        errors: [describeThrown(thrown)],
      }));
    }
    return ok("poll", Object.assign({}, base, {
      state: STATES.SUCCEEDED,
      mode: slot.mode,
      evidence,
      order: report.order || [],
      timings: report.timings || {},
    }));
  }

  /** 프로브가 실패한 채 끝난 실행. 증거는 러너의 `toEvidence` 가 세운 그대로 싣는다 —
   *  실패한 프로브의 키는 거기서 이미 빠져 있고 `error` 가 서 있다. 그 규칙을 여기서 다시
   *  구현하지 않는다(같은 판정을 두 곳이 지면 둘은 반드시 갈라진다). 구조화된
   *  `errors`·`skipped` 는 문자열로 접히기 전의 원형이라 함께 싣는다. */
  function failedReportEnvelope(base) {
    const report = slot.report;
    let evidence;
    try {
      evidence = slot.runner.toEvidence(report, null);
    } catch (thrown) {
      return fail(CODES.INTERNAL, "poll", Object.assign({}, base, {
        state: STATES.FAILED,
        errors: [describeThrown(thrown)],
      }));
    }
    return fail(CODES.RUN_FAILED, "poll", Object.assign({}, base, {
      state: STATES.FAILED,
      mode: slot.mode,
      evidence,
      errors: report.errors || [],
      skipped: report.skipped || [],
      order: report.order || [],
      timings: report.timings || {},
    }));
  }

  /** 봉투 하나를 받는 유일한 표면. 순서: 형태 → 버전 → 액션 → 액션별 인자. */
  return function run(request) {
    if (!isPlainObject(request)) {
      return fail(CODES.MALFORMED_REQUEST, null, { field: "request" });
    }
    /* 버전이 액션보다 앞이다 — 미지 버전의 `action` 은 읽지도 않는다. */
    if (request.version !== SELFTEST_VERSION) {
      return fail(CODES.UNSUPPORTED_VERSION, null, { supported: [SELFTEST_VERSION] });
    }
    const action = typeof request.action === "string" ? request.action : null;
    if (action === null || action === "") {
      return fail(CODES.MALFORMED_REQUEST, null, { field: "action" });
    }
    if (!SELFTEST_ACTIONS.includes(action)) {
      return fail(CODES.UNKNOWN_ACTION, action, { actions: SELFTEST_ACTIONS.slice() });
    }
    return action === "start" ? start(request) : poll(request);
  };
}

/** 추측 불가능한 일회용 실행 id. 16바이트 16진수. */
function makeRunId(randomBytes) {
  const bytes = randomBytes(RUN_ID_BYTES);
  let hex = "";
  for (let i = 0; i < bytes.length; i += 1) {
    hex += bytes[i].toString(16).padStart(2, "0");
  }
  return hex;
}

/** 나가는 종결 봉투 감사 — ①JSON 으로 실을 수 있는가 ②토큰이 섞여 있지 않은가.
 *
 *  ②는 이 파일이 토큰을 어디에도 싣지 않으므로 원칙적으로 발화하지 않는다. 그럼에도 세는
 *  이유는 증거의 출처가 **주입된 러너**이기 때문이다 — 러너나 프로브가 실수로 호스트 비밀을
 *  결과에 담으면 그것은 파이썬을 지나 디스크의 증거 파일까지 간다. 그 경로는 조용하다.
 *
 *  통과면 `null`, 아니면 거절 사유 필드 이름. */
function auditEnvelope(envelope, token) {
  let serialized;
  try {
    serialized = JSON.stringify(envelope);
  } catch {
    return "serialization";
  }
  if (serialized === undefined) return "serialization";
  if (serialized.includes(token)) return "token_leak";
  return null;
}
