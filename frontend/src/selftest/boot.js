/* N-09 중앙 selftest 부트 — 프로토콜(`api.js`)·엔진(`runner.js`+`probes/`)·호스트(`bridge.js` 의
   `testHost`)를 **한 자리에서** 잇는다.

   ## 이 파일이 있는 이유

   세 조각은 서로를 몰라야 한다. `api.js` 는 프로토콜만 알고 러너를 주입으로 받는다. 러너는
   프로브만 알고 능력을 주입으로 받는다. 프로브는 문서 안만 안다. 그 셋을 실제로 묶는 배선은
   어딘가에 **한 번** 있어야 하고, 그 자리를 제품 파일(합성 루트)에 흩으면 시험 배선이
   제품 조립과 섞인다. 그래서 배선은 여기 모이고 합성 루트는 이 함수를 **한 번 부르기만**
   한다.

   ## 활성화 조건은 하나뿐이다

   `testHost.available()` — 즉 **호스트 프로세스가 시험 메서드를 대는가**. 정상 실행의
   `WebFrontend` 에는 그 메서드가 아예 없으므로 거짓이고, 이 함수는 아무것도 설치하지 않은 채
   돌아간다. URL 쿼리·해시·빌드 플래그·정적 산출물은 **읽지 않는다** — 페이지 쪽에서 만들 수
   있는 조건은 "호스트가 이 창을 시험용으로 띄웠다"를 증명하지 못하기 때문이다(`api.js` 머리말).

   그래서 정상 실행과 시험 실행은 **완전히 같은 번들**을 쓴다. 갈리는 것은 런타임의 호스트
   능력 하나뿐이고, 빌드 산출물은 바이트까지 같다(D-07).

   ## 서비스는 **객체째** 넘긴다

   프로브가 `services.Bridge.call = stub` 처럼 프로퍼티를 갈아끼워 통로를 관측한다. 여기서
   메서드를 값으로 뽑아 넘기면 스텁이 우회돼 "요청은 프로브에 걸렸는데 발신은 실물로 새는"
   자리가 생긴다 — `bridge.js`·`bootstrap.js` 머리말이 두 번 적은 그 결함류다. R4 React
   화면은 같은 이유로 살아 있는 `services.Client` 객체를 받는다. 프로브는 이 둘을 한
   스텁 수명으로 함께 갈아끼워 legacy remainder와 React owner가 같은 합성 세계를 보게 한다.

   ## 푸시는 **포트**로 넘긴다

   `push_port.js` 참조. 프로브가 `ctx.push` 를 갈아끼우면 제품 스냅샷 처리기가 보내는
   호스트 푸시도 같은 통로를 지나야 `mirror_pushes`·`reject_pushes` 가 실물을 잰다. */

import { createSelftestRunner, HOST_OPS } from "./runner.js";
import { registerAllProbes } from "./probes/index.js";
import { installSelftestApi, SELFTEST_VERSION } from "./api.js";
import { Preserve } from "./preserve.js";

/** 부트 판정 — 던지지 않는다. 정상 실행에서 능력이 없는 것은 결함이 아니라 기대되는 상태이고,
 *  그때 부팅을 깨뜨리면 시험 훅이 제품 가용성을 쥐게 된다. */
function outcome(installed, reason, extra) {
  return Object.assign({ installed, reason }, extra || {});
}

/** 호스트 클레임 응답 판독.
 *
 *  계약: `{ok: true, version: 1, token, provides: [...]}`. 형태 위반은 **조용히 넘기지 않고**
 *  설치 거절로 확정한다 — 여기서 관대하면 "능력이 반쯤 선" 상태가 만들어지고, 그 상태의
 *  실패는 프로브 실패로 위장된다. */
function readClaim(raw) {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    return { ok: false, reason: "claim-malformed" };
  }
  if (raw.ok !== true) {
    return { ok: false, reason: "claim-refused", code: typeof raw.code === "string" ? raw.code : null };
  }
  if (raw.version !== SELFTEST_VERSION) {
    return { ok: false, reason: "claim-version", version: raw.version };
  }
  if (typeof raw.token !== "string" || raw.token === "") {
    return { ok: false, reason: "claim-token" };
  }
  if (!Array.isArray(raw.provides) || raw.provides.some((op) => typeof op !== "string")) {
    return { ok: false, reason: "claim-provides" };
  }
  /* 호스트가 대는 op 가 러너의 어휘 밖이면 그것은 두 층이 갈라졌다는 뜻이다. 모르는 이름을
     조용히 버리면 프로브의 `requiresHost` 판정이 엉뚱하게 통과한다. */
  const unknown = raw.provides.filter((op) => !HOST_OPS.includes(op));
  if (unknown.length > 0) {
    return { ok: false, reason: "claim-unknown-ops", unknown };
  }
  return { ok: true, token: raw.token, provides: raw.provides.slice() };
}

/** 시험 능력을 세운다(호스트가 대는 경우에만). **비동기** — pywebview 왕복이 그렇다.
 *
 *  @param {object} deps
 *    - `win` / `doc`   : 측정 표면.
 *    - `testHost`      : `bridge.js` 의 시험 전용 통로(공개 브리지 표면이 아니다).
 *    - `pushPort`      : `push_port.js` 의 단일 활성 통로.
 *    - `services`      : 프로브가 쓰는 구성 산물 열(객체째).
 *    - `alarm`         : 설치 실패를 알리는 통로(선택). 조용한 실패를 만들지 않는다.
 */
/** 호스트 연산 결과 봉투를 **값으로** 푼다.
 *
 *  호스트는 성공·거절을 **같은 모양**으로 돌려준다(`{ok, op, code, detail, value}`). 프로브가
 *  보는 것은 그 안의 `value` 여야 한다 — 프로브는 `(await ctx.host(...)) === theme` 처럼
 *  **직접 비교**하고, 봉투째 주면 그 비교가 영원히 거짓이 된다. 그리고 그 거짓은 예외가
 *  아니라 **시한 초과**로만 드러나므로, 원인이 한 겹 가려진다(첫 실엔진 대면의 실제 증상).
 *
 *  거절은 여기서 **던진다**. 러너의 `ctx.host` 가 그 거부를 프로브 실패로 확정하고 사유를
 *  구조화된 오류로 올린다 — 거절을 값으로 돌려주면 프로브가 그것을 정상값으로 읽는다. */
function unwrapHostResult(op, envelope) {
  if (envelope === null || typeof envelope !== "object" || Array.isArray(envelope)) {
    throw new Error(`호스트 연산 ${op} 의 반환이 봉투가 아닙니다: ${JSON.stringify(envelope)}`);
  }
  if (envelope.ok !== true) {
    throw new Error(
      `호스트 연산 ${op} 거절 [${envelope.code}] ${envelope.detail}`,
    );
  }
  return envelope.value;
}

/** 호스트(pywebview) 가 자기 API 를 주입할 때까지 기다린다.
 *
 *  **이 대기가 없으면 능력은 영영 서지 않는다.** 제품 entry 는 모듈 평가 시점에 돌고, 그때
 *  `window.pywebview` 는 아직 없다 — pywebview 는 페이지 로드 뒤 `pywebviewready` 를 쏘며
 *  API 를 주입한다. 그래서 그 순간에 한 번 물으면 언제나 "호스트 없음"이고, 다시 묻지
 *  않으면 그걸로 끝이다. 실제로 첫 실엔진 대면이 이 모양으로 실패했고, 파이썬 쪽은
 *  `facade-absent` 로 **시끄럽게** 보고했다(조용히 통과하지 않은 것이 진단을 살렸다).
 *
 *  `shell/app.ts`·`bridge.js` 가 이미 같은 규약을 쓴다 — "준비를 기다리는 일은 `pywebviewready`
 *  이벤트가 지고, `hostReady()` 는 지금 있는가만 답한다".
 *
 *  호스트가 영영 없으면(브라우저 단독 프리뷰) 이 약속은 해소되지 않는다. 그것이 옳다:
 *  설치할 것이 없고, 기다림은 부작용이 없으며, 파이썬 쪽 시한이 따로 진다. */
function whenHostReady(win) {
  if (win.pywebview && win.pywebview.api) return Promise.resolve(true);
  return new Promise((resolve) => {
    win.addEventListener("pywebviewready", () => resolve(true), { once: true });
  });
}

export function bootSelftest(deps) {
  const { win, doc, testHost, pushPort, services, alarm } = deps || {};

  if (!testHost || typeof testHost.available !== "function") {
    return Promise.resolve(outcome(false, "host-absent"));
  }

  return whenHostReady(win).then(() => bootWithHost({
    win, doc, testHost, pushPort, services, alarm,
  }));
}

function bootWithHost(deps) {
  const { win, doc, testHost, pushPort, services, alarm } = deps;

  if (!testHost.available()) {
    /* 정상 실행의 경로다. 경보하지 않는다 — 여기서 시끄러우면 모든 사용자 부팅이 시끄럽다. */
    return Promise.resolve(outcome(false, "host-absent"));
  }

  const report = (result) => {
    if (!result.installed && typeof alarm === "function") {
      /* 호스트는 시험용으로 띄웠는데 능력이 서지 못했다 — 이건 **조용하면 안 되는** 실패다.
         그냥 두면 파이썬이 뒤이어 "파사드 부재" 로 죽고, 원인(클레임이 왜 거절됐는지)은
         아무 데도 남지 않는다. */
      alarm(result);
    }
    return result;
  };

  return Promise.resolve()
    .then(() => testHost.claim(SELFTEST_VERSION))
    .then((raw) => {
      const claim = readClaim(raw);
      if (!claim.ok) return report(outcome(false, claim.reason, claim));

      const installed = installSelftestApi({
        win,
        /* 토큰은 이미 손에 있다 — `api.js` 의 클레임 콜백은 **동기**여야 하므로 여기서
           비동기 왕복을 먼저 끝내고 클로저로 넘긴다. */
        claimToken: () => claim.token,
        createRunner: () => {
          const runner = createSelftestRunner({
            doc,
            win,
            /* 두 인자 모두 같은 포트다: `push` 는 러너의 필수 능력 검사를 만족시키고,
               `pushPort` 는 `ctx.push` 를 접근자로 만들어 **호출 시점 결속**을 준다. */
            push: pushPort.dispatch,
            pushPort,
            /* `Preserve` 는 selftest 소유 헬퍼다(R5-99 B2 — 제품 소비자 0). 제품 합성
               루트의 services 자루에는 더 이상 없고, 그것을 쓰는 유일 소비자(`preserve`
               프로브)가 있는 이쪽이 자루에 얹는다. 제품 산물은 객체째 그대로 지난다. */
            services: { ...services, Preserve },
            host: {
              provides: claim.provides,
              request: (op, payload) => testHost.request(op, payload).then(
                (envelope) => unwrapHostResult(op, envelope),
              ),
            },
            now: () => Date.now(),
            sleep: (ms) => new Promise((resolve) => { win.setTimeout(resolve, ms); }),
          });
          registerAllProbes(runner);
          return runner;
        },
      });

      return report(installed.ok
        ? outcome(true, null, { state: installed.state })
        : outcome(false, "install-refused", { code: installed.code, field: installed.field }));
    })
    .catch((thrown) => report(outcome(false, "claim-threw", {
      message: thrown instanceof Error ? String(thrown.message || thrown) : String(thrown),
    })));
}
