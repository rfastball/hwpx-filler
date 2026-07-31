/* N-04 중앙 호환 계층 — 이미 ESM 인 잎 모듈을, 아직 전역으로 읽는 소비자에게 되건다.

   #372 D-05 의 자리다: 임시 제품 전역은 **한 곳에서만** 만들고 각 항목은 생성 단계와 제거
   책임 이슈를 진다. copy·esc·guard·segview 는 N-04 에서 named export 로 바뀌었지만 소비자
   (공용 서비스 N-05, 화면·앱 셸 N-06)는 아직 classic IIFE 라 `window.escHtml` 처럼 읽는다.
   그 간극을 파일마다 `window.X = …` 를 되살려 메우면 전역 생산자가 다시 25곳에 흩어지고,
   "compat 수량이 단조 감소한다"는 D-05 의 계측점이 사라진다 — 그래서 별칭은 여기 넷뿐이다.

   여기에 기능·상태·리스너를 두지 않는다. 이 파일이 하는 일은 이름 되걸기 하나이고, 소비자가
   ESM import 로 옮겨가면(N-05·N-06) 해당 줄이 지워지며, 파일 자체의 제거 책임은 N-10 이다.

   평가 순서가 계약이다: 제품 entry(`main.js`)가 이 모듈을 **모든 소비 IIFE 보다 먼저**
   import 하므로, static import 가 main 본문보다 먼저 평가되는 ESM 규칙에 따라 네 별칭은
   소비자가 실행될 때 이미 서 있다. entry 본문에서 나중에 대입하는 방식은 금지다 — 그 순간
   소비 IIFE 는 이미 `undefined` 를 읽은 뒤다. */
import { Copy } from "../js/copy.js";
import { escHtml } from "../js/esc.js";
import { Guard } from "../js/guard.js";
import { SegView } from "../js/segview.js";

window.Copy = Copy;
window.escHtml = escHtml;
window.Guard = Guard;
window.SegView = SegView;
