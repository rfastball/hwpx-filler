/* 관측 푸시의 **단일 활성 통로**(N-09 중앙).

   이 파일은 한 가지 결함류를 구조적으로 없애려고 존재한다: **선언은 살고 결과는 죽는다**.
   두 번 재발했고 두 번 다 실앱 게이트가 잡았다.

   ## 재발한 결함

   제품의 스냅샷 처리기와 selftest 프로브는 **같은 푸시**를 봐야 한다. 프로브는 도착하는
   호스트 푸시를 관측하려고 통로를 갈아끼우는데(`job_mirror` 의 `mirror_pushes`,
   `job_result` 의 `reject_pushes`), 제품 처리기가 그 통로를 **값으로 붙들고 있으면**
   제품 푸시는 갈아끼운 자리를 우회한다. 그러면 프로브는 「푸시 0」을 보고 그 침묵을
   **배선 부재**로 읽는다 — 측정기가 조용히 틀린다.

   - N-07 (#379 §5): 파사드의 `snapshot` 처리기가 구성 산물 `push` 를 값으로 캡처했다.
     `mirror_pushes` 1→0, `reject_pushes` 1→0. 기준 worktree 대조로 회귀 확정 후 수리.
   - 같은 이유로 `bridge` 는 **객체째** 넘긴다(`bridge.js` 헤더). 그 교훈이 `Bridge` 에만
     적혀 있었고 `__push` 에는 적혀 있지 않아서 한 번 더 났다.

   N-08 이 프로브를 프런트로 옮기면서 그 관측은 **주입된 `ctx.push`** 위에 섰다. 그런데
   주입만으로는 부족하다:

       push: (...args) => window.__push(...args)     // ← 이것으로는 못 닫는다

   프로브가 `ctx.push` 를 갈아끼워도, 제품 처리기가 자기 사본을 부르면 가로채기를 지난다.
   **두 소비자가 같은 활성 통로를 불러야** 관측이 성립한다. 그 통로가 여기다.

   ## 계약

   - `dispatch` 는 **안정된 함수 하나**다(값으로 붙들어도 안전하다). 안에서 늦게 결속한다.
   - `active` 는 **호출 시점**의 통로다 — 사전 캡처가 아니다.
   - `override(fn)` 로 갈아끼우고 `restore()` 로 원본을 되돌린다.
   - 갈아끼운 뒤 도착한 호스트 푸시도 그 통로를 지난다(늦게 도착하는 푸시가 요점이다).
   - 제품의 정상 푸시 의미는 **변하지 않는다**: override 가 없으면 `dispatch` 는 기반 푸시를
     그대로 부른다.

   이 파일에 업무 상태·화면 수명주기·DOM 을 두지 않는다. 통로 하나만 진다. */

/** 기반 푸시 하나를 감싸 **늦게 결속되는** 활성 통로를 만든다.
 *
 *  @param {(screen: string, snapshot: object) => unknown} basePush
 *    배포된 푸시 진입점(`createBridge()` 의 구성 산물).
 */
export function createPushPort(basePush) {
  if (typeof basePush !== "function") {
    throw new TypeError("createPushPort: 기반 푸시가 함수가 아닙니다.");
  }

  let override = null;

  /* 안정된 단일 함수 — 소비자가 이것을 값으로 붙들어도 늦은 결속이 유지된다.
     그래서 `window.__push` 별칭도 이 함수를 가리킨다(별칭을 통해 들어와도 같은 통로). */
  function dispatch(screen, snapshot) {
    return (override || basePush)(screen, snapshot);
  }

  return {
    dispatch,

    /** 지금 이 순간의 통로. **읽을 때마다** 판정한다(캡처 금지의 반대편). */
    get active() {
      return override || basePush;
    },

    /** 기반 통로 — 프로브가 「원본」으로 되돌릴 때 쓰는 참조. */
    get base() {
      return basePush;
    },

    /** 통로 교체. `null`/기반 함수를 주면 교체를 걷는다(둘을 같은 뜻으로 둔다 —
     *  프로브가 `ctx.push = 원본` 으로 복원하는 관용이 그대로 성립해야 한다). */
    override(fn) {
      override = (fn === null || fn === undefined || fn === basePush) ? null : fn;
    },

    /** 원본 복구. 러너가 프로브마다 반드시 부른다 — 실패한 프로브가 통로를 들고
     *  죽어도 다음 프로브와 제품 푸시가 오염되지 않는다. 레거시에는 이 보장이 없었다. */
    restore() {
      override = null;
    },

    /** 지금 교체된 상태인가 — 테스트가 누수를 단언하는 축. */
    get overridden() {
      return override !== null;
    },
  };
}
