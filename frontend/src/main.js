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

/* 제품 entry 의 JS 는 이제 중앙 compat 하나다(N-07). `bridge.js` 는 IIFE 를 벗고 ESM factory 가
   되면서 compat 의 static import 로 그래프에 들어온다 — 부작용 import 로 "먼저 평가돼야 한다"는
   순서 계약을 걸던 마지막 자리가 사라졌다. */
import "./compat.js";
