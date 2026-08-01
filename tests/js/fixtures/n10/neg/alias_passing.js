/* 음성 대조 ⑩ — 창을 **인자로 넘기는** 것은 별칭이 아니다. `bootstrap.js` 가 실제로
   `bootSelftest({ win: window, doc: document })` 로 넘기고, 그 주입이야말로 N-09 설계의 요지다.
   금지되는 것은 창을 지역 이름에 **담아 두고** 그 이름으로 쓰는 우회뿐이다. */
import { boot } from "./acyclic_a.js";

export function run(deps) {
  const win = deps.win;
  boot({ win: window, doc: document });
  return win;
}
