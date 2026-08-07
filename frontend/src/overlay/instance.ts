/* overlay 엔진·다이얼로그 host 의 제품 배선 (R3-01 · #410) — 단일 인스턴스와 늦은 결속 슬롯.
 *
 * `boot.ts` 선례 그대로다: 판정 기계는 팩토리(`engine.ts` — node 테스트가 직접 구성해
 * 격리)이고, 제품은 이 모듈이 정확히 하나를 든다. reload 는 모듈 그래프 재평가 = 신품이라
 * legacy renderers·snapshot store 와 같은 수명이다.
 *
 * ## 두 소비자, 한 인스턴스
 *
 * - 명시 구성되는 overlay adapter(`modal.js`)가 같은 디렉터리에서 스택·직렬화 판정을 위임한다.
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

/* ## 문서 keydown 의 수명주기 — 첫 open 부착 · 스택 빌 때 해제 (패킷 §4.1·개정 4)
 *
 * 시점 판정(`keydownWanted`)은 엔진이, 부착·해제 집행은 엔진과 한 몸인 이 배선 모듈이
 * 진다 — React host 가 아니다. 이유는 둘이다: ① legacy 모달의 Escape/Tab 은 오늘도 React
 * 마운트와 독립이어야 한다(마운트 실패·부팅 창에서 keydown 만 조용히 죽는 두 번째 실행
 * 경로 금지). ② 소비자 쪽 캡처 선점(data_picker 가 자기 Escape 가드를 modal 보다 먼저
 * 세우는 계약)은 「모달 keydown 은 open 호출 사슬 안에서 부착된다」에 기대고 있다.
 *
 * dismissal 계열(popover)은 bootProduct 구성 시 상시 부착(개정 10)이라 언제나 이 리스너보다
 * 앞 순서다 — Escape 한 번에 팝오버가 먼저 닫히고 최상위 모달이 나중인 층화가 부착 순서로
 * 선다. 부착 대상 document 는 부착 시점에 읽는다(모듈 평가의 문서 부작용 0). */
type KeydownDocument = {
  addEventListener(type: string, listener: (event: KeyboardEvent) => void, capture: boolean): void;
  removeEventListener(type: string, listener: (event: KeyboardEvent) => void, capture: boolean): void;
};

let keydownDocument: KeydownDocument | null = null;

function onKeydown(event: KeyboardEvent): void {
  const decision = overlayEngine.handleKeydown(event);
  if (decision.kind === "none") return;
  if (decision.kind === "consume") {
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
  }
  if (decision.kind === "escape") {
    event.preventDefault();
    event.stopImmediatePropagation(); // 같은 document 의 전역 Escape 가 아래 층까지 걷지 않게 한 겹 소비.
    overlayEngine.requestClose(decision.host);
    return;
  }
  if (overlayEngine.trapTab(decision.host, decision.backward)) event.preventDefault();
}

overlayEngine.subscribe(() => {
  const wanted = overlayEngine.keydownWanted();
  if (wanted && keydownDocument === null) {
    const doc = (globalThis as { document?: KeydownDocument }).document;
    if (doc === undefined) return;
    keydownDocument = doc;
    keydownDocument.addEventListener("keydown", onKeydown, true);
  } else if (!wanted && keydownDocument !== null) {
    keydownDocument.removeEventListener("keydown", onKeydown, true);
    keydownDocument = null;
  }
});

/** promise 다이얼로그·토스트의 DOM 집행 표면 — React host 가 마운트 시 공급한다.
 *  문안·기본 라벨·danger 판정은 modal adapter가 소유하고, 여기는 **해석된 spec** 만 받는다 —
 *  골격 부재/불량의 loud 거절 문안(`missingText`)도 그 소유의 일부라 spec 으로 실린다. */
export type DialogHost = {
  confirm(spec: {
    title: string;
    body: string;
    confirmLabel: string;
    cancelLabel: string;
    danger: boolean;
    missingText: string;
    returnFocus?: unknown;
  }): Promise<boolean>;
  prompt(spec: {
    title: string;
    body: string;
    value: string;
    missingText: string;
    validate?: (value: string) => unknown;
    returnFocus?: unknown;
  }): Promise<string | null>;
  choose(spec: {
    title: string;
    body: string;
    primary: { value: string; label: string };
    alt: { value: string; label: string };
    refusal: { value: string; label: string };
    missingText: string;
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

/** adapter의 호출 시점 판독 — 부재는 null 로 알리고, 거절 문안·alert 은 adapter가 진다. */
export function overlayDialogHost(): DialogHost | null {
  return dialogHost;
}
