/* typed bridge client (R2-02 · #406) — feature 가 소비할 **전송 표면**. 여기까지가 이 층이다.

   화면·액션·메서드 이름이 생성 계약(`contract.gen.ts`)의 리터럴 유니온으로 좁혀진다 —
   오타·낡은 이름은 tsc 가 컴파일에서 잡고, 타입을 우회한 런타임 호출은 아래 가드가
   시끄럽게 거절한다. payload **값** 검증은 여기서 하지 않는다: 키 집합 거절의 정본은
   Python `validate_dispatch` 하나이고, 웹이 재판정하면 같은 상태를 두 곳이 판정한다.

   직접 메서드 23 을 개별 typed 메서드로 다시 적지 않는다 — 그 표가 곧 다섯 번째 손
   재진술이 된다(n07 의 손 표는 드리프트 게이트 자신이라 예외였던 자리다). 이름 유니온을
   받는 `invoke` 하나로 좁히고, 자주 쓰는 왕복 둘(initial·dispatch)만 형태를 앞에 세운다.

   구독(snapshot) 소비 형태는 이 단계가 답하지 않는다 — R2-03 인계(패킷 §9).

   소비자는 아직 없다(R2-01 의 빈 root 와 같은 기반 착지). 합성 루트가 정확히 한 번
   구성해 반환값으로 내고, R2-03+ 의 feature 가 그 주입을 이어받는다 — component 가
   전역을 직접 뒤지는 형태는 여기서부터 구조적으로 막힌다. */
import { HOST_INTERNAL_METHODS, HOST_METHODS } from "../contract/contract.gen.ts";
import type {
  ActionName,
  HostInternalMethodName,
  HostMethodName,
  ScreenName,
} from "../contract/contract.gen.ts";
import type { HostResult } from "./adapter.ts";

/** client 가 내보내는 메서드 이름 — host-internal(웹 소비자 0 의 기록)은 표면이 아니다. */
export type ClientMethodName = Exclude<HostMethodName, HostInternalMethodName>;

/** 어댑터 주입 형태 — 구조 타입이라 실물(`createRuntimeAdapter` 산물)과 테스트 대역이 같다. */
type RuntimeAdapter = {
  hostReady(): boolean;
  whenReady(): Promise<void>;
  call(method: HostMethodName, args: readonly unknown[]): Promise<HostResult>;
};

export function createBridgeClient({ adapter }: { adapter: RuntimeAdapter }) {
  const known: readonly string[] = HOST_METHODS;
  const internal: readonly string[] = HOST_INTERNAL_METHODS;

  /* 타입이 이미 막는 두 경우를 런타임에서도 막는 이유: 이 표면은 `.js` 소비자도 받는다 —
     타입 검사 밖에서 온 오타·내부 표면 호출이 호스트까지 가서야 죽으면 원인이 흐려진다. */
  function invoke(method: ClientMethodName, ...args: unknown[]): Promise<HostResult> {
    if (!known.includes(method)) {
      throw new Error(`계약(HOST_METHODS)에 없는 메서드입니다: ${method}`);
    }
    if (internal.includes(method)) {
      throw new Error(`host-internal 메서드는 client 표면이 아닙니다: ${method}`);
    }
    return adapter.call(method, args);
  }

  return {
    hostReady: (): boolean => adapter.hostReady(),
    whenReady: (): Promise<void> => adapter.whenReady(),
    invoke,

    /** 화면 부팅 1회 당김 — 화면 이름이 생성 유니온으로 좁혀진다. */
    initial(screen: ScreenName): Promise<HostResult> {
      return invoke("initial", screen);
    },

    /** 순수 데이터 액션 — 화면×액션 짝이 생성 유니온으로 좁혀진다. payload 기본은 빈
     *  객체(bridge.js `|| {}` 와 같은 강제 — 미지정과 빈 payload 는 같은 발신이다). */
    dispatch<S extends ScreenName>(
      screen: S,
      action: ActionName<S>,
      payload?: Record<string, unknown>,
    ): Promise<HostResult> {
      return invoke("dispatch", screen, action, payload === undefined ? {} : payload);
    },
  };
}
