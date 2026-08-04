/* React root 의 제품 배선 — 실 `createRoot` 와 컨트롤러 단일 인스턴스가 여기 산다 (R2-01 · #405).

   `react-dom/client` 의 bare import 는 `.ts` 서브트리에만 허용된다 — `.js` 도달 그래프는
   bare 0 을 유지해 legacy 25 가 React 를 직접 싣는 경로를 원천 차단한다(정적 게이트가 잰다).
   그래서 합성 루트(`bootstrap.js`)는 이 모듈의 함수만 부르고 React 를 모른다.

   컨트롤러는 모듈 상태로 정확히 하나다: 같은 모듈 그래프에서 `bootProduct()` 가 다시 불려도
   커밋-키 가드가 한 인스턴스에 쌓인다. 상태기계 자체의 검증은 factory 를 직접 만드는
   node 테스트가 지고, 이 배선의 실물 증거는 실 WebView2 의 마운트 마커 되읽기가 진다. */
import { createRoot } from "react-dom/client";
import { createAppElement } from "./boundary.ts";
import { createReactRootController } from "./root.ts";

export const REACT_ROOT_ID = "reactRoot";

type BootHost = {
  doc: Document;
  alarm: (message: string) => void;
};

let controller: ReturnType<typeof createReactRootController> | null = null;

/** 제품 React root 를 세운다 — 합성 루트가 기존 조립 **뒤에** 정확히 한 번 부른다.
 *  실패는 경보 후 `false` 다: 부팅을 React 마운트에 매달지 않되, 침묵으로 접지도 않는다. */
export function bootReactRoot(host: BootHost): boolean {
  if (controller === null) {
    controller = createReactRootController({
      createRoot: (container) => createRoot(container),
      createAppElement: ({ onCommit }) => createAppElement({ onCommit, alarm: host.alarm }),
      alarm: host.alarm,
    });
  }
  const target = host.doc.getElementById(REACT_ROOT_ID);
  if (target === null) {
    host.alarm(`React root 컨테이너(#${REACT_ROOT_ID})가 문서에 없습니다 — 마운트를 건너뛰지 않고 실패로 보고합니다.`);
    return false;
  }
  return controller.boot(target);
}
