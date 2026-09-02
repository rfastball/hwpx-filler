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

   ## 두 번째 결함류 — 늦은 호스트 푸시가 프로브의 값을 덮는다

   U6-B(#976)가 편집기 진입마다 실 `tpl/refresh`·`pool/refresh` 를 내면서 드러났다: 그
   응답은 **호스트 푸시**로 돌아오고 도착 시점이 불특정이라, 앞 프로브가 낸 왕복의 답이
   **다음 프로브**가 심은 합성 목록을 덮는다(CI 실측 — `data_picker` 의 `rows` 가 3 → 0,
   기다리던 프로브는 조건이 영영 안 서 run_hung). 러너가 느릴수록 창이 넓어져 **CI 에서만**
   보이는 결함류다.

   출처는 구조적으로 갈린다: **호스트 푸시는 `dispatch` 로 들어오고**(제품 파사드의
   `snapshot` 처리기), **프로브 푸시는 `active` 를 직접 부른다**(러너의 `ctx.push`). 그래서
   프로브가 든 채널(`claim`)에는 `dispatch` 만 막는다 — 프로브마다 stub 을 덧대는 것은 같은
   결함이 다음 파일에서 또 나는 길이다(그 스텁은 파일 넷에 흩어졌고 두 파일을 빠뜨렸다).

   **교체가 서 있으면 막지 않는다**: 통로를 갈아끼운 프로브(`job_mirror`·`job_result`)는
   도착하는 호스트 푸시를 **세는 것**이 목적이라, 그것까지 삼키면 위의 첫 결함류가 그대로
   되살아난다(측정기가 조용히 0 을 읽는다).

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
  /** 프로브가 「내가 든다」고 선언한 채널 — 그 프로브가 끝날 때까지 정본은 프로브 값이다. */
  const claimed = new Set();

  /* 안정된 단일 함수 — 소비자가 이것을 값으로 붙들어도 늦은 결속이 유지된다.
     N-10 이전에는 임시 전역 별칭도 이 함수를 가리켰다(두 입구가 갈리지 않게). 그 별칭이
     사라진 지금 입구는 제품 파사드 하나이고, 계약은 그대로다. */
  function dispatch(screen, snapshot) {
    /* 프로브가 든 채널의 **늦은 호스트 푸시**는 버린다(위 두 번째 결함류). 교체가 서 있으면
       막지 않는다 — 그 프로브는 도착을 세는 것이 목적이고, 막으면 첫 결함류가 되살아난다. */
    if (override === null && claimed.has(screen)) return undefined;
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

    /** 이 채널의 정본을 프로브가 든다 — 러너의 `ctx.push` 가 미는 순간 선다. */
    claim(screen) {
      claimed.add(screen);
    },

    /** 클레임 전부 해제. 러너가 프로브마다 부른다 — `restore` 와 **다른 축**이라 따로 둔다:
     *  통로 교체는 「누가 그리는가」이고 클레임은 「누구의 값이 정본인가」다. 하나로 묶으면
     *  통로를 되돌리는 관용(`ctx.push = 원본`)이 클레임까지 조용히 푼다. */
    releaseClaims() {
      claimed.clear();
    },

    /** 지금 이 채널을 프로브가 들고 있는가 — 테스트가 누수를 단언하는 축. */
    isClaimed(screen) {
      return claimed.has(screen);
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
