/* 단일 React root 의 상태기계 — `createRoot` 는 주입받는다 (R2-01 · #405).

   이 모듈은 React 를 import 하지 않는다. 마운트 수명주기(부팅·커밋·정산)를 값 주입만으로
   재는 순수 상태기계라, node 테스트가 실 React 없이 기록자 factory 를 넣어 「요청이 정확히
   한 번인가」「가드가 무는가」를 직접 잰다(ADR-04 의 주입 규율을 검증 가능성으로 재사용).

   ## 가드는 커밋-키다 — 요청-키가 아니다

   두 번째 부팅을 막는 열쇠는 「createRoot 를 불렀는가」가 아니라 **「성공적으로 커밋된
   마운트가 살아 있는가」**다. node 의 합성 루트 테스트는 한 모듈 인스턴스에서 `bootProduct()`
   를 여러 번 부르는데, 그 환경에선 실 createRoot 가 대역 DOM 을 거절해 커밋이 성립하지
   않는다 — 요청-키였다면 그 반복이 전부 throw 로 죽는다. 커밋 전의 중복 부팅 창은 이
   가드가 아니라 「제품 entry 의 호출자가 하나뿐」이라는 정적 게이트가 진다.

   ## 커밋의 관측자

   「#reactRoot 가 정적으로 존재한다」와 「React 가 실제로 커밋했다」는 다른 사실이다 —
   빈 트리 + 정적 컨테이너는 관측자 없이 구별되지 않는다. 그래서 커밋 순간 컨테이너에
   `data-react-mounted="1"` 을 심고, 실 WebView2 게이트가 그 마커를 되읽는다. */

export type ReactRootLike = {
  render(children: unknown): void;
  unmount(): void;
};

export type CreateRootFn = (container: Element) => ReactRootLike;

export type RootControllerDeps = {
  createRoot: CreateRootFn;
  /* 렌더할 요소 트리의 factory — 실물은 boundary.ts 가 대고, 기록자 테스트는 스텁을 댄다.
     `onCommit` 을 요소 계약으로 받는 이유: 커밋 신호가 요소 트리 안(effect)에서 나므로,
     상태기계는 그 신호를 닫힌 콜백으로 건네고 결과만 되받는다. */
  createAppElement: (hooks: { onCommit: () => void }) => unknown;
  alarm: (message: string) => void;
};

export const MOUNT_MARKER_ATTRIBUTE = "data-react-mounted";

/** 단일 React root 컨트롤러 하나를 만든다 — 제품에선 boot.ts 가 모듈 상태로 정확히 하나를
 *  들고, 테스트는 매번 새로 만들어 상태기계를 격리한다. */
export function createReactRootController(deps: RootControllerDeps) {
  let root: ReactRootLike | null = null;
  let container: Element | null = null;
  let committed = false;

  return {
    /** 컨테이너에 React root 를 세운다. 커밋된 마운트가 살아 있으면 시끄럽게 throw 하고,
     *  요청·렌더 실패는 경보 후 `false` 다 — 조용한 폴백 경로는 없다. */
    boot(target: Element): boolean {
      if (committed) {
        throw new Error(
          "React root 가 이미 커밋된 채 살아 있습니다 — unmount 정산 전의 재부팅은 두 번째 실행 경로입니다.",
        );
      }
      try {
        const requested = deps.createRoot(target);
        root = requested;
        container = target;
        requested.render(
          deps.createAppElement({
            onCommit: () => {
              committed = true;
              target.setAttribute(MOUNT_MARKER_ATTRIBUTE, "1");
            },
          }),
        );
        return true;
      } catch (error) {
        root = null;
        container = null;
        deps.alarm(`React root 부팅 실패 — ${String(error)}`);
        return false;
      }
    },

    /** 살아 있는 root 를 정확히 1회 정산한다. 정산할 root 가 없는 호출은 침묵으로 접지 않고
     *  throw 한다 — 이중 정산은 「이미 죽은 것을 또 죽였다」가 아니라 호출 규약 위반이다. */
    unmount(): void {
      if (root === null) {
        throw new Error("정산할 React root 가 없습니다 — unmount 는 정확히 1회여야 합니다.");
      }
      const settled = root;
      root = null;
      committed = false;
      settled.unmount();
      container?.removeAttribute(MOUNT_MARKER_ATTRIBUTE);
      container = null;
    },

    /** 커밋-키 관측면 — 테스트가 가드 무장 여부를 직접 묻는다. */
    isCommitted(): boolean {
      return committed;
    },
  };
}
