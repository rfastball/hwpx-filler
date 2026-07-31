/* 버전 있는 제품 파사드(N-07) — Python→웹 호출의 **유일한 공개 경계**.

   종전 Python 은 웹의 내부 이름을 하나씩 알고 불렀다(화면 객체·서비스 객체·푸시 전역).
   그 결합은 두 방향으로 조용히 썩는다: ①웹이 이름을 바꾸면 Python 의 문자열이 아무 말 없이
   빗나가고(`… && ….prompt(payload)` 는 부재를 **falsy 무동작**으로 삼켰다) ②Python 이 웹 내부
   구조를 알아야 하므로 링 경계가 문자열 안에 숨는다. 이 파일은 그 통로를 하나로 좁히고
   **모든 실패를 구조화**한다 — 조용한 대체 경로는 하나도 없다.

   ## 표면은 둘뿐이다

   - `describe()` — 프로토콜·버전·능력 목록. 호출자가 "이 창이 무엇을 받는가"를 **묻고** 시작한다.
   - `deliver({ version, event, payload })` — 한 사건을 해당 능력으로 라우팅한다.

   ## 능력 목록과 핸들러 표는 **같은 레지스트리**에서 나온다

   광고한 능력에 핸들러가 없는 상태를 구조적으로 불가능하게 만드는 것이 목적이다. 두 벌을
   손으로 적으면 한쪽만 자라고, 그 어긋남은 "능력은 있다는데 아무 일도 안 일어난다"는 가장
   진단하기 어려운 침묵이 된다.

   ## `deliver` 는 절대 await 대상이 아니다

   호출자는 `evaluate_js` 뒤에 앉은 Python 스레드다. Promise 를 돌려주면 그 스레드는 해소를
   기다리지 못한 채 형태를 모르는 값을 받는다. 그래서 반환은 **동기 · JSON 직렬화 가능**한
   평범한 객체다. 비동기가 본질인 사건(확인 모달·알림)은 "시작했다"는 사실만 돌려준다.

   ## 내부 이름을 밖으로 내지 않는다

   서술자에도 실패 객체에도 화면 id·모듈 이름·DOM id·서비스 이름을 담지 않는다. 담는 순간
   경계는 이름만 바뀐 결합이 되고, 다음 개명이 다시 Python 을 깨뜨린다. 그래서 핸들러가 던진
   예외의 **메시지도 싣지 않는다**: 그 문자열은 대개 내부 식별자를 그대로 물고 온다. 진단은
   안정 코드(`handler_failed`)로 하고, 서사는 웹 콘솔·셸 백스톱이 진다. */

/** 프로토콜 이름 — 서술자에만 나온다. 요청은 버전만 싣는다(형태를 늘리지 않는다). */
const PRODUCT_PROTOCOL = "hwpx-product";

/** 지원 버전. 미지 버전은 v1 로 강등되지 않는다 — 강등이 곧 조용한 추측이다. */
const PRODUCT_VERSION = 1;

/** 안정 실패 코드 — 값이 계약이다(Python 어댑터가 이 문자열로 분기한다).
 *  이름이 아니라 **값**을 비교하도록 내보낸다. */
export const PRODUCT_ERROR_CODES = Object.freeze({
  /** 요청 자체가 객체가 아니거나 `event` 가 문자열이 아니다. */
  MALFORMED_REQUEST: "malformed_request",
  /** `version` 이 지원 버전이 아니다(누락·0·2·비수치 포함). */
  UNSUPPORTED_VERSION: "unsupported_version",
  /** 광고하지 않은 사건이다. */
  UNKNOWN_EVENT: "unknown_event",
  /** 사건은 알지만 payload 형태가 계약과 다르다. */
  MALFORMED_PAYLOAD: "malformed_payload",
  /** 그 능력을 실제로 수행할 내부 처리기가 없다(주입 누락·부분 부재). */
  HANDLER_UNAVAILABLE: "handler_unavailable",
  /** 처리기가 있었지만 동기 실행 중 던졌다. */
  HANDLER_FAILED: "handler_failed",
});

const CODES = PRODUCT_ERROR_CODES;

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** 이번 요청이 요구한 설정 조각 — 순서 고정. `theme` 는 저장값이 light/dark 일 때만 실린다. */
function requestedPreferences(payload) {
  const pieces = ["personalization"];
  if (payload.theme === "light" || payload.theme === "dark") pieces.push("theme");
  return pieces;
}

/* 단일 레지스트리 — 서술자의 능력 목록도, 핸들러 조회 키도 여기서만 나온다.
   각 항목은 payload 검증(어긋난 **필드 이름**을 돌려준다)과 호출 규약을 소유한다.
   `invoke` 는 { ok:true, extras } 또는 { ok:false, code, extras } 를 돌려주고,
   그 조각을 `deliver` 가 공통 결과 형태로 감싼다. */
const ROUTES = {
  /** 관측 푸시 — 화면은 **불투명한 라우팅 값**이다. 여기서 해석하지 않는다(해석하는 순간
   *  경계가 화면 목록을 알게 되고, 화면이 늘 때마다 이 파일이 낡는다). */
  snapshot: {
    validate(payload) {
      if (typeof payload.screen !== "string" || payload.screen === "") return "screen";
      if (!Object.hasOwn(payload, "snapshot")) return "snapshot";
      return null;
    },
    invoke(handler, payload) {
      handler(payload);
      return { ok: true, extras: {} };
    },
  },

  /** 네이티브 X 닫기 확인 — 비동기 3택 모달을 **시작**한다. 여기서 기다리면 호출 스레드가
   *  모달 해소까지 매달린다. 처분 통보는 모달 소유자가 브리지로 되돌린다. */
  "close-request": {
    validate(payload) {
      return isPlainObject(payload.state) ? null : "state";
    },
    invoke(handler, payload) {
      handler(payload);
      return { ok: true, extras: { started: true } };
    },
  },

  /** 부팅 설정 주입 — 개인화는 항상, 테마는 저장값이 light/dark 일 때만 온다.
   *  처리기는 **실제로 적용한 조각 이름 배열**을 돌려준다. 그 보고를 요구 조각과 대조해
   *  빠진 조각을 이름으로 지목한다 — "설정 주입 실패" 한 줄로 뭉치면 개인화가 죽은 것과
   *  테마가 죽은 것이 같은 말이 되고, 그 둘은 원인도 조치도 다르다. */
  preferences: {
    validate(payload) {
      if (!isPlainObject(payload.personalization)) return "personalization";
      const theme = payload.theme;
      if (theme !== undefined && theme !== null && theme !== "light" && theme !== "dark") {
        return "theme";
      }
      return null;
    },
    invoke(handler, payload) {
      const requested = requestedPreferences(payload);
      const reported = handler(payload);
      const seen = Array.isArray(reported) ? reported : [];
      const applied = requested.filter((piece) => seen.includes(piece));
      const missing = requested.filter((piece) => !applied.includes(piece));
      if (missing.length > 0) {
        return { ok: false, code: CODES.HANDLER_UNAVAILABLE, extras: { applied, missing } };
      }
      return { ok: true, extras: { applied } };
    },
  },

  /** 사후 고지 — 발사 후 망각. 처리기 호출 자체를 다음 태스크로 미뤄, 블로킹 알림창이
   *  호출 스레드를 잡아도 `deliver` 는 이미 돌아와 있게 한다. 처리기 부재는 미루기 **전에**
   *  동기로 판정한다(미룬 뒤에 알면 그 실패는 아무도 못 듣는다). */
  notice: {
    validate(payload) {
      return typeof payload.message === "string" && payload.message !== "" ? null : "message";
    },
    invoke(handler, payload) {
      setTimeout(() => { handler(payload); }, 0);
      return { ok: true, extras: { scheduled: true } };
    },
  },
};

/** 능력 목록 — 매 호출 새 배열(호출자가 내부 상태를 흔들 수 없게). */
function capabilityNames() {
  return Object.keys(ROUTES);
}

function success(event, extras) {
  return Object.assign({ ok: true, event }, extras);
}

function failure(code, event, extras) {
  return Object.assign({ ok: false, code, event }, extras);
}

/** 제품 파사드 구성 — `handlers` 는 능력 이름을 키로 하는 표다.
 *  이 모듈은 전역을 만들지 않는다(설치는 중앙 compat 한 곳의 몫, D-05). */
export function createProductApi(ports) {
  const handlers = (ports && ports.handlers) || {};

  function describe() {
    return {
      protocol: PRODUCT_PROTOCOL,
      version: PRODUCT_VERSION,
      capabilities: capabilityNames(),
    };
  }

  /* 검증 순서가 계약이다: 요청 형태 → 버전 → 사건 이름 → 사건 존재 → payload → 처리기.
     버전이 사건보다 앞이다 — 미지 버전의 요청은 **해석 자체를 하지 않는다**. */
  function deliver(request) {
    if (!isPlainObject(request)) {
      return failure(CODES.MALFORMED_REQUEST, null, { field: "request" });
    }
    const event = typeof request.event === "string" ? request.event : null;
    if (request.version !== PRODUCT_VERSION) {
      return failure(CODES.UNSUPPORTED_VERSION, event, { supported: [PRODUCT_VERSION] });
    }
    if (event === null || event === "") {
      return failure(CODES.MALFORMED_REQUEST, null, { field: "event" });
    }
    if (!Object.hasOwn(ROUTES, event)) {
      return failure(CODES.UNKNOWN_EVENT, event, { capabilities: capabilityNames() });
    }
    const route = ROUTES[event];
    const payload = request.payload;
    if (!isPlainObject(payload)) {
      return failure(CODES.MALFORMED_PAYLOAD, event, { field: "payload" });
    }
    const badField = route.validate(payload);
    if (badField !== null) {
      return failure(CODES.MALFORMED_PAYLOAD, event, { field: badField });
    }
    const handler = Object.hasOwn(handlers, event) ? handlers[event] : undefined;
    if (typeof handler !== "function") {
      return failure(CODES.HANDLER_UNAVAILABLE, event, {});
    }
    let outcome;
    try {
      outcome = route.invoke(handler, payload);
    } catch {
      // 예외 메시지는 싣지 않는다 — 대개 내부 식별자를 그대로 물고 온다(위 머리말).
      return failure(CODES.HANDLER_FAILED, event, {});
    }
    if (outcome.ok === true) return success(event, outcome.extras);
    return failure(outcome.code, event, outcome.extras);
  }

  return { describe, deliver };
}
