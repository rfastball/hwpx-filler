/* React 오류 경계와 마운트 신호 — 요소는 전부 `createElement` 로 만든다 (R2-01 · #405).

   `.tsx` 는 이 단계에서 닫혀 있다: Node 24 의 type stripping 은 `.ts` 만 싣고 `.tsx` 는
   `ERR_UNKNOWN_FILE_EXTENSION` 으로 죽는다 — node 게이트와 제품이 같은 파일을 보려면
   JSX 없이 서야 한다. JSX 도입 여부는 화면을 실제로 이관하는 단계(R3+)가 자기 패킷에서
   결정한다.

   ## 렌더 실패는 명시 실패 표면 + 경보다 — Vanilla fallback 은 없다

   경계가 잡은 실패는 `role="alert"` 실패 표면으로 그 자리에서 보이고, 경보 콜백으로
   시끄럽게 재진술된다. legacy 트리로 되돌아가 실패를 숨기는 경로는 만들지 않는다(#405
   불변식). R3-01 이 overlay 표면 4 를, R3-02 가 셸 리스너·부팅 시퀀스를 이 트리에 실은
   뒤로 렌더 실패는 실제 제품 반경(확인 창·탭 응답)을 가진다 — 착지 형태가 계약인 이유다. */
import { Component, createElement, useEffect, useMemo, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import type { SnapshotStore } from "../state/store.ts";
import { OverlayHost } from "../overlay/host.ts";
import type { OverlayHostPorts } from "../overlay/host.ts";
import { ShellHost } from "../shell/host.ts";
import type { ShellHostPorts } from "../shell/host.ts";

type BoundaryProps = {
  alarm: (message: string) => void;
  /* 상태기계의 커밋 신호 — 경계 자신은 쓰지 않지만 최외곽 요소의 props 로 실어, 렌더
     실물 없이 요소만 받는 기록자도 커밋 경로에 닿을 수 있게 한다(root.ts 의 요소 계약). */
  onCommit?: () => void;
  children?: ReactNode;
};

type BoundaryState = { failed: boolean };

export class ReactErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false };

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: unknown): void {
    this.props.alarm(`React 화면 렌더 실패 — ${String(error)}`);
  }

  render(): ReactNode {
    if (this.state.failed) {
      return createElement(
        "div",
        { role: "alert" },
        "화면 일부를 그리지 못했습니다 — 앱을 다시 시작해 주세요.",
      );
    }
    return this.props.children ?? null;
  }
}

/** 커밋 순간을 알리는 화면 없는 신호 — effect 는 React 가 트리를 DOM 에 반영한 뒤에 돈다. */
function MountSignal(props: { onCommit: () => void }): null {
  const { onCommit } = props;
  useEffect(() => {
    onCommit();
  }, [onCommit]);
  return null;
}

/** store 사건 수신의 화면 없는 신호 (R2-03 · #407) — snapshot→store→구독→React 인과
 *  경로의 실물이다. 6채널 구독을 합성해 총 revision 을 콜백으로 알릴 뿐, DOM 을 직접
 *  판독·기입하지 않는다(마커 기입은 target 을 닫은 boot.ts 클로저 몫 — 침묵 전역 판독
 *  경로를 구조로 봉쇄한다). 화면·문안·판정도 지지 않는다 — 그것이 자라면 R3 선점이다. */
function StoreSignal(props: {
  store: SnapshotStore;
  reflectStoreRevision: (revision: number) => void;
}): null {
  const { store, reflectStoreRevision } = props;
  /* 합성 subscribe 는 store 에 결속된 안정 참조여야 한다 — 렌더마다 새 클로저면
     useSyncExternalStore 가 매 렌더 전 채널을 해제→재구독한다(hook 파일 머리말). */
  const subscribeAll = useMemo(
    () => (listener: () => void) => {
      const unsubscribes = store.channels.map((screen) => store.subscriber(screen)(listener));
      return () => {
        unsubscribes.forEach((unsubscribe) => unsubscribe());
      };
    },
    [store],
  );
  const total = useSyncExternalStore(subscribeAll, () =>
    store.channels.reduce((sum, screen) => sum + store.revision(screen), 0));
  useEffect(() => {
    reflectStoreRevision(total);
  }, [total, reflectStoreRevision]);
  return null;
}

/** 제품 React 트리의 요소 factory — root 상태기계의 `createAppElement` 실물이다.
 *  자식 넷: 마운트 신호 · store 신호 · overlay host(R3-01 — 완전 데이터-구동 표면 4 의
 *  React 소유 DOM) · shell host(R3-02 — 셸 리스너·부팅 시퀀스의 수명주기). */
export function createAppElement(hooks: {
  onCommit: () => void;
  alarm: (message: string) => void;
  store: SnapshotStore;
  reflectStoreRevision: (revision: number) => void;
  overlay: OverlayHostPorts;
  shell: ShellHostPorts;
}): ReactNode {
  return createElement(
    ReactErrorBoundary,
    { alarm: hooks.alarm, onCommit: hooks.onCommit },
    createElement(MountSignal, { onCommit: hooks.onCommit }),
    createElement(StoreSignal, {
      store: hooks.store,
      reflectStoreRevision: hooks.reflectStoreRevision,
    }),
    createElement(OverlayHost, hooks.overlay),
    createElement(ShellHost, hooks.shell),
  );
}
