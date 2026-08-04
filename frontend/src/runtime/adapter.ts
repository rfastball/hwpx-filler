/* pywebview 런타임 어댑터 (R2-02 · #406) — ready 대기·호출·오류 변환의 **유일한 신규 소유자**.

   `window.pywebview` 에 닿는 제품 신규 통로는 이 파일 하나다(allowlist 게이트
   `tests/js/pywebview_allowlist.test.js` 가 파일 전수를 핀으로 지킨다). legacy 통로
   `js/bridge.js` 는 그대로 산다(ADR-06 — 신규 소비자만 이 통로를 쓴다). 이 파일은
   `../js/` 를 import 하지 않는다 — `.ts` → legacy 간선 0 은 정적 게이트가 잰다.

   ## 변환 대상은 웹→Python 경로의 실패 셋뿐이다 (패킷 rev2 §4.2-1)

   ① dispatch 거절 봉투(`{name, message}` — app.py 의 예상 가능한 도메인/스키마 거절)
   ② `"ERROR:"` 문자열 규약(직접 메서드의 실패 신고)
   ③ 호스트 메서드 부재(종전엔 런타임 TypeError 로 터지던 자리)

   셋을 typed 결과(`HostResult`)로 바꾼다. **그 밖의 실패는 변환하지 않는다** — 예상 밖
   예외·transport 거절은 그대로 위로 던져진다(Promise rejection 통과). 감싸면 실제 결함이
   정상 거절로 위장한다(app.py dispatch 독스트링과 같은 근거). 제품 JS snake 6종은
   Python→웹(deliver) 경로의 어휘라 이 어댑터의 변환 대상이 아니다.

   ## 미지를 재라벨하지 않는다

   거절 봉투의 `name`·`message` 는 **원문 보존**이다(selftest `JS_CODE_MAP` 의 「표에 없으면
   원문 보존」 선례). 손상된 봉투는 성공으로도 거절로도 접지 않고 제 이름의 실패로 신고한다. */
import { DISPATCH_REJECTION_KEY } from "../contract/contract.gen.ts";
import type { HostMethodName } from "../contract/contract.gen.ts";

/** 호스트 창의 최소 형태 — pywebview 는 런타임 주입이라 존재가 선택적이다. */
type HostWindow = {
  pywebview?: { api?: Record<string, unknown> };
  addEventListener(type: string, listener: () => void, options?: { once?: boolean }): void;
};

/** 어댑터가 typed 로 바꾸는 실패 전수 — 이 밖의 실패는 변환 없이 던져진다(머리말). */
export type HostFailure =
  | { kind: "host-absent"; message: string }
  | { kind: "method-missing"; method: string; message: string }
  | { kind: "dispatch-rejected"; name: string; message: string }
  | { kind: "rejection-envelope-malformed"; message: string }
  | { kind: "host-error-string"; message: string };

export type HostResult =
  | { ok: true; value: unknown }
  | { ok: false; failure: HostFailure };

function failure(shape: HostFailure): HostResult {
  return { ok: false, failure: shape };
}

/** 호스트 반환값 하나를 typed 결과로 판정한다 — 성공·봉투·문자열 규약 세 갈래뿐이다. */
function classify(value: unknown): HostResult {
  if (value !== null && typeof value === "object"
    && Object.hasOwn(value, DISPATCH_REJECTION_KEY)) {
    const rejection = (value as Record<string, unknown>)[DISPATCH_REJECTION_KEY];
    if (rejection === null || typeof rejection !== "object"
      || typeof (rejection as { message?: unknown }).message !== "string") {
      /* 손상 봉투를 dispatch-rejected 로 접으면 「손상」이라는 사실이 사라진다 —
         bridge.js 의 같은 자리(봉투 손상 throw)와 같은 엄격도, 형태만 typed 다. */
      return failure({
        kind: "rejection-envelope-malformed",
        message: "Python dispatch 거절 봉투가 손상되었습니다.",
      });
    }
    const body = rejection as { name?: unknown; message: string };
    return failure({
      kind: "dispatch-rejected",
      /* bridge.js 와 같은 규약: name 이 비면 JS Error 기본 이름이다. message 는 원문 보존. */
      name: typeof body.name === "string" && body.name !== "" ? body.name : "Error",
      message: body.message,
    });
  }
  if (typeof value === "string" && value.startsWith("ERROR:")) {
    return failure({ kind: "host-error-string", message: value });
  }
  return { ok: true, value };
}

/** 창 하나에 묶인 어댑터를 구성한다 — 구성은 부작용이 없다(리스너 부착은 whenReady 호출 시). */
export function createRuntimeAdapter({ win }: { win: HostWindow }) {
  function hostApi(): Record<string, unknown> | null {
    const host = win.pywebview;
    return host !== undefined && host.api !== undefined ? host.api : null;
  }

  return {
    /** 지금 호스트가 있는가 — 재시도·캐시 없는 순간 판정(bridge.js hostReady 와 같은 술어). */
    hostReady(): boolean {
      return hostApi() !== null;
    },

    /** 호스트 주입을 기다린다 — `pywebviewready` 는 주입 **뒤에** 발화하므로 선판정과
     *  이벤트 대기 사이에 놓치는 창이 없다(selftest boot.js 와 같은 규약). */
    whenReady(): Promise<void> {
      if (hostApi() !== null) return Promise.resolve();
      return new Promise((resolve) => {
        win.addEventListener("pywebviewready", () => { resolve(); }, { once: true });
      });
    },

    /** 호스트 메서드 하나를 부른다. 반환은 typed 결과, 예상 밖 예외는 변환 없이 던져진다. */
    async call(method: HostMethodName, args: readonly unknown[]): Promise<HostResult> {
      const api = hostApi();
      if (api === null) {
        return failure({
          kind: "host-absent",
          message: `호스트(pywebview)가 없어 ${method} 를 부를 수 없습니다.`,
        });
      }
      const target = api[method];
      if (typeof target !== "function") {
        /* 종전 이 실패는 소비자 자리의 TypeError 였다 — 이름을 잃지 않고 시끄럽게 신고한다. */
        return failure({
          kind: "method-missing",
          method,
          message: `호스트에 ${method} 가 없습니다 — 계약(HOST_METHODS)과 호스트가 어긋났습니다.`,
        });
      }
      const value = await (target as (...call: unknown[]) => unknown).apply(api, [...args]);
      return classify(value);
    },
  };
}
