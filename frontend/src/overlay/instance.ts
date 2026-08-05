/* overlay 엔진·다이얼로그 host 의 제품 배선 (R3-01 · #410) — 단일 인스턴스와 늦은 결속 슬롯.
 *
 * `boot.ts` 선례 그대로다: 판정 기계는 팩토리(`engine.ts` — node 테스트가 직접 구성해
 * 격리)이고, 제품은 이 모듈이 정확히 하나를 든다. reload 는 모듈 그래프 재평가 = 신품이라
 * legacy renderers·snapshot store 와 같은 수명이다.
 *
 * ## 두 소비자, 한 인스턴스
 *
 * - legacy 파사드(`frontend/js/modal.js`)가 js→ts 상대 import 로 이 모듈을 읽어 스택·직렬화
 *   판정을 위임한다(`bootstrap.js` 가 `.ts` 를 import 하는 선례 — 역방향 `.ts`→legacy 간선은
 *   게이트가 0 으로 막는다).
 * - React host(`host.ts`)가 트리 안에서 같은 인스턴스를 구독·집행한다.
 *
 * ## 다이얼로그 host 슬롯 — 늦은 결속
 *
 * promise 다이얼로그(confirm/choose/prompt)와 토스트의 **DOM 집행**은 React host 가 마운트한
 * 뒤에만 존재한다. 파사드는 호출 시점에 슬롯을 읽고, 부재면 안전측 거절 + loud 를 집행한다
 * (골격 부재 거절과 같은 형태 — 부팅 창·마운트 실패에서 조용한 무동작이 생기지 않게).
 * 슬롯 대입은 host 마운트 effect 가 정확히 1회, 해제는 unmount cleanup 이 진다. */
import { createOverlayEngine } from "./engine.ts";
import type { OverlayEngine } from "./engine.ts";

export const overlayEngine: OverlayEngine = createOverlayEngine();

/** promise 다이얼로그·토스트의 DOM 집행 표면 — React host 가 마운트 시 공급한다.
 *  문안·기본 라벨·danger 판정은 파사드(legacy)가 소유하고, 여기는 **해석된 spec** 만 받는다. */
export type DialogHost = {
  confirm(spec: {
    title: string;
    body: string;
    confirmLabel: string;
    cancelLabel: string;
    danger: boolean;
    returnFocus?: unknown;
  }): Promise<boolean>;
  prompt(spec: {
    title: string;
    body: string;
    value: string;
    validate?: (value: string) => unknown;
    returnFocus?: unknown;
  }): Promise<string | null>;
  choose(spec: {
    title: string;
    body: string;
    primary: { value: string; label: string };
    alt: { value: string; label: string };
    refusal: { value: string; label: string };
    returnFocus?: unknown;
  }): Promise<string>;
  toastShow(message: string, undo: () => unknown): void;
  toastHide(): void;
};

let dialogHost: DialogHost | null = null;

/** host 마운트가 정확히 1회 대입한다 — 이미 서 있으면 throw(두 번째 host 는 두 번째 실행 경로). */
export function setOverlayDialogHost(host: DialogHost): () => void {
  if (dialogHost !== null) {
    throw new Error("overlay 다이얼로그 host 가 이미 서 있습니다 — 두 번째 마운트는 두 번째 실행 경로입니다.");
  }
  dialogHost = host;
  return () => {
    dialogHost = null;
  };
}

/** 파사드의 호출 시점 판독 — 부재는 null 로 알리고, 거절 문안·alert 은 파사드가 진다. */
export function overlayDialogHost(): DialogHost | null {
  return dialogHost;
}
