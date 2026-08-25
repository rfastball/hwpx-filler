/* React root 의 제품 배선 — 실 `createRoot` 와 컨트롤러 단일 인스턴스가 여기 산다 (R2-01 · #405).

   `react-dom/client` 의 bare import 는 `.ts` 서브트리에만 허용된다 — `.js` 도달 그래프는
   bare 0 을 유지해 비 React JS가 React를 직접 싣는 경로를 원천 차단한다(정적 게이트가 잰다).
   그래서 합성 루트(`bootstrap.js`)는 이 모듈의 함수만 부르고 React 를 모른다.

   컨트롤러는 모듈 상태로 정확히 하나다: 같은 모듈 그래프에서 `bootProduct()` 가 다시 불려도
   커밋-키 가드가 한 인스턴스에 쌓인다. 상태기계 자체의 검증은 factory 를 직접 만드는
   node 테스트가 지고, 이 배선의 실물 증거는 실 WebView2 의 마운트 마커 되읽기가 진다. */
import { createRoot } from "react-dom/client";
import { createAppElement } from "./boundary.ts";
import { createReactRootController } from "./root.ts";
import type { SnapshotStore } from "../state/store.ts";
import type { OverlayHostPorts } from "../overlay/host.ts";
import type { ShellHostPorts } from "../shell/host.ts";
import type { ProductScreensPorts } from "../screens/product_screens.ts";
import type { TutorialPorts } from "../tutorial/panel.ts";

export const REACT_ROOT_ID = "reactRoot";

/** store 사건 수신의 실물 마커 — 실 WebView2 게이트가 되읽는다(`data-react-mounted` 의
 *  상태판). 기입 주체는 신호 컴포넌트가 아니라 target 을 닫은 아래 클로저다(root.ts 의
 *  onCommit 이 마운트 마커를 소유하는 것과 같은 규율 — StoreSignal 은 DOM 을 모른다). */
export const STORE_REVISION_ATTRIBUTE = "data-react-store-rev";

type BootHost = {
  doc: Document;
  alarm: (message: string) => void;
  store: SnapshotStore;
  overlay: OverlayHostPorts;
  shell: ShellHostPorts;
  screens: ProductScreensPorts;
  tutorial: TutorialPorts;
};

let controller: ReturnType<typeof createReactRootController> | null = null;

/* 늦은 결속 슬롯 (R2-03 · #407) — 컨트롤러는 모듈 싱글턴이라 첫 호출의 요소 factory
   클로저를 캡처한다. store·target 을 **값으로 캡처하면** node 의 반복 부팅에서 신품과
   어긋난다(`bridge` 를 객체째 넘기는 규율과 같은 결함류). 그래서 클로저는 슬롯을 읽고,
   슬롯은 매 `bootReactRoot` 호출이 `controller.boot()` **전에** 갱신한다 — 요소 factory
   호출은 boot 본문 안이라 같은 동기 사슬에서 슬롯이 낡을 창이 없다. */
let currentStore: SnapshotStore | null = null;
let currentTarget: Element | null = null;
let currentOverlay: OverlayHostPorts | null = null;
let currentShell: ShellHostPorts | null = null;
let currentScreens: ProductScreensPorts | null = null;
let currentTutorial: TutorialPorts | null = null;

/** 제품 React root 를 세운다 — 합성 루트가 기존 조립 **뒤에** 정확히 한 번 부른다.
 *  실패는 경보 후 `false` 다: 부팅을 React 마운트에 매달지 않되, 침묵으로 접지도 않는다. */
export function bootReactRoot(host: BootHost): boolean {
  if (controller === null) {
    controller = createReactRootController({
      createRoot: (container) => createRoot(container),
      createAppElement: ({ onCommit }) => {
        if (currentStore === null || currentTarget === null || currentOverlay === null
          || currentShell === null || currentScreens === null || currentTutorial === null) {
          /* boot() 밖에서 불릴 길은 없다 — 이 throw 는 그 계약이 깨졌을 때의 시끄러운
             착지이고, root.ts 의 boot catch 가 경보 후 false 로 접는다. */
          throw new Error("React 요소 factory 가 늦은 결속 슬롯 밖에서 불렸습니다.");
        }
        const target = currentTarget;
        return createAppElement({
          onCommit,
          alarm: host.alarm,
          store: currentStore,
          reflectStoreRevision: (revision) => {
            target.setAttribute(STORE_REVISION_ATTRIBUTE, String(revision));
          },
          overlay: currentOverlay,
          shell: currentShell,
          screens: currentScreens,
          tutorial: currentTutorial,
        });
      },
      alarm: host.alarm,
    });
  }
  const target = host.doc.getElementById(REACT_ROOT_ID);
  if (target === null) {
    host.alarm(`React root 컨테이너(#${REACT_ROOT_ID})가 문서에 없습니다 — 마운트를 건너뛰지 않고 실패로 보고합니다.`);
    return false;
  }
  currentStore = host.store;
  currentTarget = target;
  currentOverlay = host.overlay;
  currentShell = host.shell;
  currentScreens = host.screens;
  currentTutorial = host.tutorial;
  return controller.boot(target);
}
