/* React 셸 host (R3-02 · #411) — 셸 리스너·부팅 시퀀스의 **수명주기**를 React 트리가 소유한다.
 *
 * ## 무엇을 소유하고 무엇을 소유하지 않는가
 *
 * 이 컴포넌트는 화면이 없다(`null` 렌더). 소유하는 것은 수명주기 둘뿐이다:
 *
 * - **셸 리스너 부착/해제** — 탭 클릭·도구 클릭·개인화/테마 라벨 동기·비동기 백스톱.
 *   대상·핸들러는 집행 adapter(app.js)가 구성 시 캡처해 서술로 넘긴다(`attachments`) —
 *   판정·문안·DOM 기입은 전부 그쪽 소유이고, 여기는 부착과 **대칭 해제**만 진다(재초기화가
 *   리스너를 복제하지 않는다는 불변식의 구조적 거처 — Popover.documentAttachments 를
 *   bootProduct 가 순회하는 형태의 React 판).
 * - **부팅 시퀀스** — 호스트 ready 사건 훅 → 상태기계 `markReady` → init 시퀀스 재생.
 *   init 본문은 legacy 화면 콜백 주입이라 여기는 순서만 소유한다(순서 = 배열 순서, 정본은
 *   adapter 가 세운 목록).
 *
 * ## 선판정 + 이벤트 — 부착이 비동기라 생기는 놓침 창을 닫는다
 *
 * 구 셸은 리스너를 합성 루트 호출(동기)에 부착해 ready 사건을 놓칠 수 없었다. effect 는
 * 커밋 뒤라 사건이 먼저 발화할 수 있다 — 그래서 부착 전에 「지금 이미 준비인가」를 한 번
 * 묻고, 준비면 즉시 ready 경로를 진다(`runtime/adapter.ts whenReady`·`selftest/boot.js` 와
 * 같은 규약). 리스너는 once 가 아니다 — 재발화 시 init 재주행이 현 동작 핀이고(n06 계측),
 * 멱등은 각 화면 init 의 wired 가드가 진다(패킷 §1 ②).
 *
 * ## 마운트 실패는 시끄럽다
 *
 * R3-01 이 overlay 표면을 트리에 실은 뒤로 React 마운트는 이미 제품 경로다 — 셸 리스너가
 * 그 위에 얹히면서 마운트 실패의 반경이 「탭·도구 응답 없음」까지 넓어진다. 그 실패는
 * boot.ts 경보(alert)로 착지하지, 조용한 폴백 경로를 만들지 않는다(#405 불변식 — Vanilla
 * fallback 금지). */
import { useEffect } from "react";
import type { ReactNode } from "react";

/** 리스너 서술 하나 — 대상·유형·핸들러. 캡처 옵션은 셸 리스너에 소비자가 없어 싣지 않는다
 *  (필요해지는 순간 그 소비자가 이 형을 넓힌다 — 미리 넓히면 죽은 표면이다). */
export type ShellAttachment = {
  target: {
    addEventListener(type: string, handler: (event: never) => void): void;
    removeEventListener(type: string, handler: (event: never) => void): void;
  };
  type: string;
  handler: (event: never) => void;
};

export type ShellHostPorts = {
  /** 상태기계의 ready 전이 — 판정은 기계 소유, 여기는 호출 시점만 소유한다. */
  nav: { markReady(): void };
  /** 셸 리스너 전수 — adapter 구성 시 캡처(NodeList 캡처 시점 보존, 패킷 §1 ③). */
  attachments: readonly ShellAttachment[];
  /** 부착 직후의 따라잡기 — 부착이 비동기라 **부착 전에 지나간 사건**(부팅 preferences
   *  주입의 라벨 동기 등)을 현재 상태 재판독으로 만회한다. 선판정+이벤트와 같은 규약의
   *  사건판이다: 사건이 먼저면 여기가, 나중이면 리스너가 잇는다 — 어느 쪽이든 창이 없다
   *  (#74 라벨 어긋남 결함류의 구조 폐쇄). */
  catchUp: ReadonlyArray<() => void>;
  boot: {
    /** ready 사건의 대상 — 제품은 window, 테스트는 대역. */
    win: ShellAttachment["target"];
    /** 선판정 — 「지금 호스트가 있는가」(Bridge.hostReady 주입). */
    hostReady(): boolean;
    /** init 본문 — legacy 화면 콜백 주입. 순서가 계약이다(library→editor→job→workbench→DataPicker). */
    initSequence: ReadonlyArray<() => void>;
  };
};

/** 부착 실물 — React host effect 와 node 하니스가 **같은 실물**을 세운다(overlay host
 *  컨트롤러 분리와 같은 규율). 반환은 대칭 해제 클로저다. */
export function attachShell(ports: ShellHostPorts): () => void {
  for (const attachment of ports.attachments) {
    attachment.target.addEventListener(attachment.type, attachment.handler);
  }
  for (const step of ports.catchUp) step();
  const onHostReady = (): void => {
    ports.nav.markReady();
    for (const step of ports.boot.initSequence) step();
  };
  /* 선판정(머리말) — 이미 준비면 즉시, 아니면 사건이 잇는다. once 없음(재발화 재주행 보존). */
  if (ports.boot.hostReady()) onHostReady();
  ports.boot.win.addEventListener("pywebviewready", onHostReady);

  return () => {
    ports.boot.win.removeEventListener("pywebviewready", onHostReady);
    for (const attachment of ports.attachments) {
      attachment.target.removeEventListener(attachment.type, attachment.handler);
    }
  };
}

/** 셸 수명주기 host — 트리에 정확히 하나. 마운트가 부착·시퀀서를 세우고 cleanup 이
 *  대칭으로 걷는다. */
export function ShellHost(ports: ShellHostPorts): ReactNode {
  useEffect(() => {
    return attachShell(ports);
    /* ports 는 boot 늦은 결속 슬롯이 대는 안정 참조 — 재구성은 reload(신품 그래프)뿐이다. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* 화면 없는 수명주기 컴포넌트 — MountSignal·StoreSignal 과 같은 형. DOM 을 만들면
     그 순간부터 셸 DOM 의 두 번째 생산자다(정적 id 계약·소유 경계 양쪽의 이유로 null). */
  return null;
}
