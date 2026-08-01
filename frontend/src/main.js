import "../css/tokens.css";
import "../css/base.css";
import "../css/draftcard.css";
import "../css/editor.css";
import "../css/job.css";
import "../css/overlay.css";
import "../css/library.css";
import "../css/forced-colors.css";
import "../css/jobdata.css";
import "../css/tail.css";

/* 제품 entry 의 JS 는 합성 루트 하나다. N-07 까지는 그 자리가 `compat.js` 였고 entry 는 그것을
   **부작용 import** 로 실었다 — 모듈 평가가 곧 부팅이었다. N-10 이 임시 전역 스물일곱을 지우며
   그 파일을 은퇴시키고, 부팅을 평가가 아니라 **호출**이 지게 했다.

   그래서 아래 한 줄이 제품의 유일한 부팅 지점이다. 두 번 부르면 서비스 리스너가 한 벌 더
   서므로 호출자는 여기 하나뿐이어야 하고, 그 유일성은 정적 게이트가 센다. */
import { bootProduct } from "./bootstrap.js";

bootProduct();
