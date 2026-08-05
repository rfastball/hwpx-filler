/* 트리-불가지 overlay 엔진 (R3-01 · #410) — 스택·직렬화·Escape/Tab/복귀 **판정**의 단일 정본.
 *
 * modal.js 가 혼자 들던 판정(중첩 스택·promise 직렬화·트랩 경계·복귀 승계)을 여기로 올린다.
 * 합법 중첩(폼 모달 위 promise 다이얼로그 — pool 재등록)이 legacy DOM 모달과 React 렌더
 * 다이얼로그를 **한 스택**에 세우므로, 판정이 두 세계로 갈리면 같은 상태의 두 판정자가 된다
 * (제품 규칙 위반). 그래서 판정은 트리-불가지 엔진 하나이고, DOM **집행**만 집행자
 * (executor — legacy modal.js / React host)로 갈린다.
 *
 * ## 이 파일에 없는 것
 *
 * DOM 기입 0 · DOM 판독 0 · 전역 접촉 0 · React 접촉 0. 요소는 불투명 참조로만 보관한다
 * (`host` — Element 든 무엇이든 엔진은 안을 보지 않는다). 트랩의 포커스 이동·복귀의
 * 옮겨-보고-확인·퇴장 전이의 정착은 전부 집행자 포트가 진다 — 판정(언제·무엇을)과
 * 집행(어떻게)의 절취선이 이 파일의 존재 이유다.
 *
 * ## 수명·구성
 *
 * 인스턴스는 팩토리 + 제품 배선 모듈의 싱글턴이다(`root.ts`/`boot.ts` 선례 — node 테스트는
 * 팩토리를 직접 구성해 격리하고, 제품은 `instance.ts` 가 정확히 하나를 든다). reload 는
 * 모듈 그래프 재평가 = 신품이라 store 와 같은 수명이다.
 *
 * ## 문서 리스너의 시점 계약 (패킷 §4.1·n05_data_picker 0→2→0→2 핀의 승계)
 *
 * dismissal 계열(팝오버 바깥닫기·Escape)은 구성 시 상시, 모달 keydown 은 **첫 open 부착·
 * 스택 빌 때 해제**다. 엔진은 부착하지 않는다 — 시점 판정(`keydownWanted`)과 핸들러
 * (`handleKeydown`)만 소유하고, 실제 부착/해제는 리스너 수명주기 소유자(React host effect
 * — R3-01 이 세우는 해제-소유 선례)가 `subscribe` 로 시점 변화를 구독해 집행한다. */

/** 집행자 — 스택 항목 하나의 DOM 효과 전부. 판정은 엔진이, 집행은 이쪽이 진다. */
export type OverlayExecutor = {
  /** 개방 집행(hidden 해제·depth 반영). `depth` 는 스택 등록 직후의 0-기반 층위 —
   *  `--modal-depth` 집행의 축이다(판정은 엔진, 기입은 집행자). */
  show(depth: number): void;
  /** 퇴장 시작(is-closing 진입). 정착은 집행자가 전이 종료/안전망으로 판정해
   *  `settleClose(host)` 를 부른다 — 220ms 안전망도 집행자 소유다(전이는 DOM 사건). */
  beginClose(): void;
  /** 퇴장 정착 후 정리(hidden 확정·클래스 정리). 엔진이 settleClose 안에서 정확히 1회 부른다. */
  finishClose(): void;
  /** 초기 포커스 집행(호출부 지정 요소 우선 규율은 집행자 소유). */
  focusInitial(): void;
  /** 트랩 경계 집행 — 방향에 따라 첫/끝 포커스 가능 요소로 이동. 포커스 가능 목록·경계
   *  판정(첫↔끝·바깥 이탈)까지 집행자가 진다: 그 판정은 DOM 판독(offsetParent·tabIndex)
   *  없이는 성립하지 않고, 엔진은 「최상위가 트랩을 소유한다」는 사실만 판정한다. */
  trapTab(backward: boolean): void;
  /** 복귀 집행 — 옮겨 보고 확인 + 화면 루트 착지 폴백(modal.js:136-148 규율 그대로). */
  restoreFocus(): void;
};

export type OverlayEntry = {
  /** 불투명 요소 참조 — 동일성 판정(이중 open·close 대상)에만 쓴다. */
  host: unknown;
  executor: OverlayExecutor;
  /** 폼 dirty 가드 — false 반환은 닫기 요청 소비(surface_sheet 이탈 가드 규율). */
  beforeClose?: () => boolean;
  /** 어떤 경로로 닫혀도 정착 후 1회 통지. */
  onClose?: () => void;
};

type StackRecord = {
  entry: OverlayEntry;
  closing: boolean;
  /** 정착 티켓 — 같은 닫힘의 정착이 두 경로(전이 종료·안전망)로 겹쳐도 1회만 정산. */
  ticket: number;
};

export type KeydownDecision =
  | { kind: "none" }
  | { kind: "consume" }
  | { kind: "escape"; host: unknown }
  | { kind: "trap"; host: unknown; backward: boolean };

export type EngineListener = () => void;

export function createOverlayEngine() {
  const stack: StackRecord[] = [];
  let pendingDialog = false;
  let nextTicket = 1;
  const registrations = new Set<{ listener: EngineListener; alive: boolean }>();

  function top(): StackRecord | null {
    return stack.length ? stack[stack.length - 1] : null;
  }

  function recordOf(host: unknown): StackRecord | null {
    for (let i = stack.length - 1; i >= 0; i -= 1) {
      if (stack[i].entry.host === host) return stack[i];
    }
    return null;
  }

  function notify(): void {
    for (const registration of [...registrations]) {
      if (registration.alive) registration.listener();
    }
  }

  return {
    /** 관측면 — 스택 깊이(--modal-depth 집행·keydown 시점 판정의 축). */
    depth(): number {
      return stack.length;
    },

    /** 관측면 — host 가 스택에 있는가(이중 open 판정을 소비자도 물을 수 있게). */
    isOpen(host: unknown): boolean {
      return recordOf(host) !== null;
    },

    /** 모달 keydown 리스너가 서 있어야 하는 구간인가 — 첫 open ~ 스택 빌 때(현 의미 보존). */
    keydownWanted(): boolean {
      return stack.length > 0;
    },

    /** promise 다이얼로그 직렬화 관측면. */
    isDialogPending(): boolean {
      return pendingDialog;
    },

    /** 스택 변화 구독 — 해제 클로저 반환. 이중 해제는 throw(store.ts 규율). */
    subscribe(listener: EngineListener): () => void {
      const registration = { listener, alive: true };
      registrations.add(registration);
      return () => {
        if (!registration.alive) {
          throw new Error("이미 해제된 overlay 엔진 구독입니다 — 해제는 등록마다 정확히 1회여야 합니다.");
        }
        registration.alive = false;
        registrations.delete(registration);
      };
    },

    /** 열기 — 같은 host 의 이중 open 은 무시(멱등 — 스택 중복으로 닫힘 의미가 꼬이는 것 방지).
     *  개방 순서 집행(복귀점 포착·경량층 닫기)은 호출부(파사드)가 이 앞에서 진다(H-16). */
    open(entry: OverlayEntry): boolean {
      if (recordOf(entry.host) !== null) return false;
      stack.push({ entry, closing: false, ticket: 0 });
      entry.executor.show(stack.length - 1);
      entry.executor.focusInitial();
      notify();
      return true;
    },

    /** 닫기 요청 — 판정만 한다: 미등록 무시 / 퇴장 중 재입력 소비 / beforeClose 소비 /
     *  아니면 beginClose 집행 지시. 정착은 settleClose 가 잇는다. */
    requestClose(host: unknown): "ignored" | "consumed" | "closing" {
      const record = recordOf(host);
      if (record === null) return "ignored";
      if (record.closing) return "consumed";
      if (record.entry.beforeClose && record.entry.beforeClose() === false) return "consumed";
      record.closing = true;
      record.ticket = nextTicket;
      nextTicket += 1;
      record.entry.executor.beginClose();
      notify();
      return "closing";
    },

    /** 퇴장 정착 — 집행자(전이 종료 또는 안전망)가 부른다. 같은 닫힘의 겹침 호출은 1회만
     *  정산하고, 정리 순서는 modal.js finishClose 그대로: 집행 정리 → 스택 제거 →
     *  (최상위였을 때만) 복귀 → onClose 통지. */
    settleClose(host: unknown): boolean {
      const record = recordOf(host);
      if (record === null || !record.closing) return false;
      const wasTop = top() === record;
      record.closing = false;
      record.entry.executor.finishClose();
      const index = stack.indexOf(record);
      if (index !== -1) stack.splice(index, 1);
      if (wasTop) record.entry.executor.restoreFocus();
      if (record.entry.onClose) record.entry.onClose();
      notify();
      return true;
    },

    /** promise 다이얼로그 직렬화 — 진입 시도. 미결이 있으면 거절(loud 재진술은 파사드 몫 —
     *  문안·alert 은 집행 층이 소유한다). */
    acquireDialog(): boolean {
      if (pendingDialog) return false;
      pendingDialog = true;
      return true;
    },

    /** 직렬화 해제 — settle-once 는 파사드의 정착 단일화가 지고, 여기는 상태만 되돌린다.
     *  미보유 해제는 호출 규약 위반이라 throw(이중 정산 규율). */
    releaseDialog(): void {
      if (!pendingDialog) {
        throw new Error("보유하지 않은 promise 다이얼로그 직렬화를 해제했습니다 — acquire/release 는 짝이어야 합니다.");
      }
      pendingDialog = false;
    },

    /** 문서 keydown 판정 — 모달 계열의 몫만. 팝오버 dismissal 이 **먼저** 같은 사건을
     *  처리하는 상대 순서는 리스너 수명주기 소유자가 부착 순서로 지킨다(§2.4 의미 보존).
     *  IME 조합(229 포함)은 소비하지 않고 통과(조합 취소가 먼저다). */
    handleKeydown(event: {
      key: string;
      shiftKey?: boolean;
      isComposing?: boolean;
      keyCode?: number;
    }): KeydownDecision {
      const record = top();
      if (record === null) return { kind: "none" };
      if (event.isComposing || event.keyCode === 229) return { kind: "none" };
      if (record.closing && (event.key === "Escape" || event.key === "Tab")) {
        return { kind: "consume" };
      }
      if (event.key === "Escape") {
        return { kind: "escape", host: record.entry.host };
      }
      if (event.key === "Tab") {
        return { kind: "trap", host: record.entry.host, backward: event.shiftKey === true };
      }
      return { kind: "none" };
    },

    /** Tab 트랩 집행 위임 — 판정(최상위 소유)과 방향만 정하고 경계 이동은 집행자가 진다. */
    trapTab(host: unknown, backward: boolean): void {
      const record = recordOf(host);
      if (record !== null) record.entry.executor.trapTab(backward);
    },
  };
}

export type OverlayEngine = ReturnType<typeof createOverlayEngine>;
