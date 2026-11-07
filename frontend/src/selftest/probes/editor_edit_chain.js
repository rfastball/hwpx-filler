/* `editor_workbench_data.js` 클러스터 D 의 **편집 발신 프로브**(`editor_tab_autodiscard`·
 * `editor_discard_immediate`)가 함께 쓰는 편집 체인 관측·정리 조각 — 책임 분리(복잡도 예산)
 * 사이드카.
 *
 * 두 프로브는 편집기 브리지 호출을 스텁으로 갈아끼우고, 제품 컨트롤러가 그 스텁으로 쏘는
 * 발신(`set_name`·`goto_section`·`discard_patch`)을 잰다. 그 발신은 제품의 편집 체인
 * (`editor_controller.ts` 의 `EDIT_CHAIN`)에 줄을 선다. 여기서 지는 것은 둘이다.
 *
 *  ① **어느 고리가 늦었는가**(CI 실측 — `editor_discard_immediate` 가 시한 2.5초를 넘겼는데
 *     러너는 시한에서 부분 상태를 버리므로 클릭 → 정산(`set_name`) → 체인 대기 →
 *     `discard_patch` 중 어디가 늦었는지 남지 않았다). 클릭 기준 상대 시각을 단계마다 찍고,
 *     기다리는 단계와 이미 도착한 단계를 실패 문안에 싣는다.
 *  ② **시한을 넘긴 프로브의 늦은 발신이 다음 프로브로 새지 않는다**(같은 실측 — 버려진
 *     프로브의 정리가 스텁을 되돌린 뒤 늦은 `discard_patch` 가 **실** 컨트롤러에 닿았고, 실
 *     세션은 저장 전 새 작업이라 던졌다. 그 경보는 다음 프로브 `editor_txt_band` 의 이름으로
 *     섰다). 스텁을 되돌리기 **전에** 늦은 발신의 착지와 체인 정산을 유계로 기다린다.
 *
 * 공유 헬퍼(`service`)는 `editor_workbench_data.js` 에 살고 여기로 역수입하지 않는다
 * (import 그래프 순환 금지) — 부르는 쪽이 `lib` 으로 주입한다. */

import { ERROR_CODES, SelftestProbeError } from "../runner.js";

/** 제품 편집 체인 키 — `editor_controller.ts` 의 `EDIT_CHAIN` 과 **같은 문자열**이다. 제품
 *  모듈을 import 해 유도하지 않는 것은 이 프로브 모듈이 제품 그래프 밖(inert)이어야 해서다.
 *  둘이 갈라지면 정산이 빈 체인을 기다려 즉시 끝난다 — 그러면 ②의 격리가 조용히 죽으므로
 *  단위 테스트가 제품 원천의 문자열과 대조한다. */
export const EDITOR_EDIT_CHAIN = "editor:mutate";

/** 되돌린 스냅샷 push 뒤 재렌더 정착 대기(ms) — 레거시 값 그대로. */
export const DISCARD_SETTLE_MS = 300;

/** 발신 대기의 끝점과 프로브 시한 사이의 여유(ms). `ctx.waitFor` 는 판정 뒤 폴링 한 번
 *  (기본 50ms)만큼 넘칠 수 있고, 정착 뒤 DOM 읽기와 타이머 지터도 이 안에 든다. 이 여유가
 *  있어야 늦은 발신이 감시견의 이름 없는 시한 초과가 아니라 **이 프로브의 문안**으로 선다. */
export const DISCARD_WAIT_MARGIN_MS = 250;

/** 정리 국면에서 늦은 발신의 착지 + 체인 정산을 기다리는 총상한(ms). 러너는 정리에 시한을
 *  걸지 않으므로 이 상한이 유일한 끝이다 — 엔진 총예산(80초)의 호스트 여유(60초) 안에서
 *  실패 경로에만 쓰인다(정상 경로는 체인이 이미 비어 있어 폴링 한 번이면 끝난다). */
export const EDIT_QUIESCE_MS = 3000;

/** `editor_discard_immediate` 가 재는 단계 — 클릭 기준 상대 시각으로 증거와 문안에 싣는다.
 *  `pre_chain_idle` 은 타이핑 **전**에 본 편집 체인이 비는 시각이다(음수 = 클릭 전에 이미
 *  비었다). 양수로 크면 프로브 앞에서 누군가 체인을 붙들고 있었다는 뜻이다. */
export const DISCARD_STEPS = Object.freeze([
  "pre_chain_idle", "set_name_arrived", "set_name_resolved", "discard_patch_arrived",
]);

/** 클릭 뒤 차례로 기다리는 단계 — `pre_chain_idle` 은 관측만 하고 기다리지 않는다. */
const AWAITED_STEPS = Object.freeze(["set_name_arrived", "set_name_resolved", "discard_patch_arrived"]);

/** 단계 시각 기록기. 절대 시각을 적어 두고 상대 시각은 읽을 때 원점(클릭)에서 뺀다 —
 *  원점보다 먼저 찍힌 단계(`pre_chain_idle`)도 같은 축에 선다. 같은 단계는 처음 한 번만. */
export function createStepClock(now) {
  const at = {};
  let origin = null;
  function relative(step) {
    return origin === null || !(step in at) ? null : Math.round(at[step] - origin);
  }
  return {
    start() { origin = now(); },
    get started() { return origin !== null; },
    mark(step) { if (!(step in at)) at[step] = now(); },
    has(step) { return step in at; },
    /** 도착한 단계만 담은 `{단계: 클릭 기준 ms}` — 증거 필드. */
    timeline() {
      const out = {};
      for (const step of DISCARD_STEPS) if (step in at) out[step] = relative(step);
      return out;
    },
    /** 사람이 읽는 한 줄 — `set_name_arrived +4ms · discard_patch_arrived 미도착`. */
    describe() {
      return DISCARD_STEPS.map((step) => {
        const ms = relative(step);
        if (ms === null) return `${step} 미도착`;
        return `${step} ${ms >= 0 ? "+" : ""}${ms}ms`;
      }).join(" · ");
    },
  };
}

/** 타이핑 전 편집 체인이 비는 시각을 찍는다 — 기다리지 않고 관측만 한다. */
export function observePreChain(ctx, lib, steps) {
  const Intent = lib.service(ctx, "Intent");
  Promise.resolve(Intent.settle(EDITOR_EDIT_CHAIN)).then(() => steps.mark("pre_chain_idle"));
}

/** 클릭 뒤 단계를 차례로 기다린다 — `discard_patch` 가 도착하면 즉시 끝난다.
 *
 *  단계마다 `ctx.waitFor` 를 새로 부른다: 러너의 `waitState.what` 은 호출 시점에 고정되는
 *  문자열이라 한 번 부르고 갱신할 길이 없다. 단계로 나누면 감시견이 먼저 깨더라도
 *  「(대기 중: …)」 이 **그 단계 진입 시점까지** 도착한 단계를 정직하게 싣는다.
 *
 *  상한은 단계마다가 아니라 **끝점 하나**(프로브 시한 − 정착 − 여유)를 나눠 쓴다. 그래서
 *  내부 대기 + 정착이 시한 안에 엄격히 들고, 늦으면 이 프로브의 문안이 감시견보다 먼저 선다.
 *  만료 문안은 **만료 시점**의 단계 시각으로 다시 쓴다 — 진입 시점 문자열은 그 사이 도착한
 *  `pre_chain_idle` 을 「미도착」이라 말할 수 있다. */
export async function awaitDiscardSteps(ctx, steps) {
  const end = ctx.now() + ctx.remainingMs() - DISCARD_SETTLE_MS - DISCARD_WAIT_MARGIN_MS;
  for (const step of AWAITED_STEPS) {
    if (steps.has("discard_patch_arrived")) return;
    const timeoutMs = Math.max(0, end - ctx.now());
    try {
      await ctx.waitFor(() => steps.has(step) || steps.has("discard_patch_arrived"), {
        what: `${step} (단계 진입 시점 클릭 기준: ${steps.describe()})`,
        timeoutMs,
      });
    } catch (thrown) {
      if (!(thrown instanceof SelftestProbeError) || thrown.code !== ERROR_CODES.DEADLINE_EXCEEDED) {
        throw thrown;
      }
      ctx.fail(
        ERROR_CODES.DEADLINE_EXCEEDED,
        `${step} 대기 ${timeoutMs}ms 초과 — 클릭 기준: ${steps.describe()}`,
      );
    }
  }
}

/** 늦은 제품 발신이 **스텁에** 착지하고 편집 체인이 빌 때까지 유계로 기다린다(정리 국면).
 *
 *  프로브의 promise 가 끝났다고 제품 체인이 빈 것은 아니다 — 프로브는 자기 대기를 끝내고
 *  돌아왔어도 컨트롤러의 정산·발신은 아직 줄에 있을 수 있다. 그래서 「발신 착지」는 프로브가
 *  아는 사실(`inFlight`)로, 「체인 정산」은 제품이 쓰는 같은 체인의 `settle` 로 잰다.
 *  상한 안에 안 서면 던진다 — 러너가 이 프로브의 `teardown_failed` 로 세우고 뒤 국면을
 *  멈춘다. 스텁을 되돌린 채 늦은 발신을 실 컨트롤러로 흘려보내는 것보다 그 편이 정직하다. */
export async function quiesceEditorEdits(ctx, lib, inFlight, what) {
  const Intent = lib.service(ctx, "Intent");
  if (typeof Intent.settle !== "function") {
    throw new Error("Intent.settle 이 주입되지 않았습니다 — 편집 체인 정산을 잴 수 없습니다.");
  }
  const end = ctx.now() + EDIT_QUIESCE_MS;
  const left = () => Math.max(0, end - ctx.now());
  await ctx.waitFor(() => !inFlight(), {
    what: `${what} 착지(늦은 제품 발신이 스텁에 닿기 전에는 스텁을 되돌리지 않는다)`,
    timeoutMs: left(),
    phase: "teardown",
  });
  let settled = false;
  Promise.resolve(Intent.settle(EDITOR_EDIT_CHAIN)).then(() => { settled = true; });
  await ctx.waitFor(() => settled, {
    what: `편집 체인(${EDITOR_EDIT_CHAIN}) 정산`,
    timeoutMs: left(),
    phase: "teardown",
  });
}

/** 스텁을 쓴 편집기 프로브의 정리 — 정산 → 스텁 복원 → 셸 복귀 순서를 지킨다.
 *  정산이 실패해도 스텁과 셸은 되돌리고 **정산 실패를 그대로** 던진다(뒤 국면은 러너가
 *  멈춘다). `lib` = `{ service, restoreShell }`. */
export async function teardownStubbedEditor(ctx, lib, inFlight, what) {
  let quiesceError = null;
  try {
    await quiesceEditorEdits(ctx, lib, inFlight, what);
  } catch (thrown) {
    quiesceError = thrown;
  }
  if (ctx.state.stub) ctx.state.stub.restore();
  lib.restoreShell(ctx, ctx.state.out || {});
  if (quiesceError) throw quiesceError;
}
