/* React 오류 경계와 마운트 신호 — 요소는 전부 `createElement` 로 만든다 (R2-01 · #405).

   `.tsx` 는 이 단계에서 닫혀 있다: Node 24 의 type stripping 은 `.ts` 만 싣고 `.tsx` 는
   `ERR_UNKNOWN_FILE_EXTENSION` 으로 죽는다 — node 게이트와 제품이 같은 파일을 보려면
   JSX 없이 서야 한다. JSX 도입 여부는 화면을 실제로 이관하는 단계(R3+)가 자기 패킷에서
   결정한다.

   ## 렌더 실패는 명시 실패 표면 + 경보다 — Vanilla fallback 은 없다

   경계가 잡은 실패는 `role="alert"` 실패 표면으로 그 자리에서 보이고, 경보 콜백으로
   시끄럽게 재진술된다. legacy 트리로 되돌아가 실패를 숨기는 경로는 만들지 않는다(#405
   불변식). 지금 이 트리의 유일한 자식은 화면 없는 마운트 신호라 이 표면이 실제로 보일
   일은 없지만, 화면이 이관되기 전에 실패의 착지 형태부터 계약으로 세운다. */
import { Component, createElement, useEffect } from "react";
import type { ReactNode } from "react";

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

/** 제품 React 트리의 요소 factory — root 상태기계의 `createAppElement` 실물이다. */
export function createAppElement(hooks: {
  onCommit: () => void;
  alarm: (message: string) => void;
}): ReactNode {
  return createElement(
    ReactErrorBoundary,
    { alarm: hooks.alarm, onCommit: hooks.onCommit },
    createElement(MountSignal, { onCommit: hooks.onCommit }),
  );
}
