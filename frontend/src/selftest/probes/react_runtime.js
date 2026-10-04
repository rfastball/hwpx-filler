/* 클러스터 R — React 실런타임 마커 프로브 (R2-04 · #408).
 *
 * 레거시 후계가 **아니다**. B·C·D·E 는 `app.py` 상수의 이관이라 출처 줄 번호를 적지만,
 * 이 클러스터는 R2 가 세운 React 기반(마운트 커밋 마커 `data-react-mounted` · store 사건
 * 마커 `data-react-store-rev`)의 신설 검증 축이다 — 그래서 `legacySite` 는 실재 줄이 아니라
 * 레거시 전 구간(최대 3993)을 넘는 단일 관례값이고, 출처 주석 의무(레거시 28 상수 1:1)의
 * 정의역 밖이다.
 *
 * 무엇을 재나 — **기반 마커의 존재 증명** 셋, 전부 문서 안(국경 규칙: 문서 안은 frontend):
 *   · mounted   : `#reactRoot` 의 `data-react-mounted` == "1" (커밋 마커 — root.ts 가 커밋
 *                 시점에 심는다).
 *   · store_rev : `data-react-store-rev` 가 십진 문자열(`/^[0-9]+$/`). 값의 크기(0/양수)는
 *                 묻지 않는다 — 값보다 마커 형상을 보는 module selftest result의 소유이고,
 *                 여기서 겸하면 프로브가 클러스터 실행 순서에 결합된다.
 *   · roots     : `[data-react-mounted]` 전수 == 1. **마커 규율 census** 다 — 마커의 생산자는
 *                 root.ts 컨트롤러 경로 하나이므로, 이 판독은 「마커를 심는 경로가 하나뿐」을
 *                 실창에서 재확인할 뿐 날 `createRoot` 둘째 root(마커를 안 심는다)는 잡지
 *                 못한다. 다중 island 의 실방어는 정적 census(tests/artifact_contract/test_frontend_build_graph.py)가
 *                 진다.
 *
 * 위반은 **throw** 다(ctx.fail) — 러너가 `report.errors` 로 재진술하고 실패한 키는 증거에서
 * 빠지므로, source 게이트(test_no_probe_error)와 packaged 판정(build.ps1 의 error 선행 검사 +
 * 책임 수 43)이 각자의 기존 경로로 붉는다. 화면 판정·문안·dispatch 는 0 — 화면 동작 검증의
 * 이식이 아니라 기반 마커의 존재 증명이다(자라면 R3 선점 = 상향 대상).
 *
 * 마커는 렌더가 아니라 **커밋 후 effect** 산물이라(root.ts:59-64 · boundary.ts:80-85) 즉시
 * 판독은 이론적 경합 창이 있다 — `precondition` 이 러너 공용 대기(ctx.waitFor)로 마커 존재를
 * 시한 안에 기다린 뒤 본판독한다.
 *
 * 소유권 인벤토리 alias 계약: 이 파일은 재실측기의 selftest-scope alias 가 세는 토큰
 * (HTML 직렬화 대입·리스너 등록·호스트 다리 접촉의 이름들)을 **주석 포함 0** 으로
 * 유지한다 — 판독은 getElementById/querySelectorAll/getAttribute 로만 한다.
 *
 * 이 모듈은 **비활성(inert)** 이다. 제품 그래프를 import 하지 않고 전역을 쓰지 않으며,
 * import 만으로는 DOM 을 만지지 않는다 — 전부 호출 시점에 일어난다. */

import { ERROR_CODES } from "../runner.js";

export const REACT_RUNTIME_CLUSTER = "R";

/** 이 클러스터가 내는 키 전수 — 하나다. */
export const REACT_RUNTIME_KEYS = Object.freeze(["react_runtime"]);

/* 마커 이름은 정본 상수(react/boot.ts `STORE_REVISION_ATTRIBUTE` · react/root.ts
 * `MOUNT_MARKER_ATTRIBUTE` · boot.ts `REACT_ROOT_ID`)의 리터럴 사본이다 — 프로브 트리는
 * 제품 그래프를 import 하지 않는다(비활성 계약)는 것이 이 중복의 이유이고, 드리프트는
 * 실창 판독 자체가 잡는다(이름이 어긋나면 마커가 영영 안 보여 이 프로브가 붉는다). */
const ROOT_ID = "reactRoot";
const MOUNT_MARKER = "data-react-mounted";
const STORE_REV = "data-react-store-rev";
const DECIMAL = /^[0-9]+$/;

/** 본판독 — 문서 안 3판독, 부작용 0. */
function measureReactRuntime(ctx) {
  const doc = ctx.doc;
  const root = doc.getElementById(ROOT_ID);
  return {
    mounted: root === null ? null : root.getAttribute(MOUNT_MARKER),
    store_rev: root === null ? null : root.getAttribute(STORE_REV),
    roots: doc.querySelectorAll(`[${MOUNT_MARKER}]`).length,
  };
}

async function measureTutorialSurface(ctx) {
  const doc = ctx.doc;
  const bridge = ctx.services.Bridge;
  if (!bridge || typeof bridge.initial !== "function") ctx.fail(ERROR_CODES.CONTRACT, "tutorial initial 통로가 없습니다.");
  const real = await bridge.initial("tutorial");
  if (!real || real.kind !== "tutorial-lessons/v1") ctx.fail(ERROR_CODES.CONTRACT, "tutorial-lessons/v1 실 스냅샷이 없습니다.");
  const nav = ctx.services.Nav;
  if (!nav || typeof nav.go !== "function" || typeof nav.currentScreen !== "function") ctx.fail(ERROR_CODES.CONTRACT, "튜토리얼 화면 이동 관측점이 없습니다.");
  const oldScreen = nav.currentScreen();
  const oldScale = doc.documentElement.getAttribute("data-font-scale");
  const hit = (element) => {
    const box = element.getBoundingClientRect();
    return doc.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  };
  let pending = null;
  const bounds = (element) => {
    const box = element.getBoundingClientRect();
    return box.left >= 0 && box.top >= 0 && box.right <= ctx.win.innerWidth && box.bottom <= ctx.win.innerHeight;
  };
  try {
    nav.go("job", { force: true });
    const synthetic = {
      ...real,
      invitation: { ...real.invitation, visible: false },
      active: true, paused: false, scenario_id: "first_hwpx", checkpoint: 0,
      practice: { active: true, return_screen: oldScreen },
      stages: [{ id: "a", title: "고르기", status: "current" }],
      beat: { id: "selftest-target", title: "대상 확인", body: "실제 데이터 이름을 가리키는 안내입니다.",
        mode: "action", screen: "job", target: "data-label", placement: "right", can_next: false },
      show_result: false, result: null,
    };
    ctx.push("tutorial", synthetic);
    await ctx.waitFor(() => !!doc.getElementById("tutorialCoach") && !!doc.getElementById("jobDataLabel"),
      { what: "튜토리얼 코치와 실제 데이터 이름", timeoutMs: 2000 });
    const entry = doc.getElementById("tutorialOpen");
    const target = doc.getElementById("jobDataLabel");
    const spot = doc.querySelector(".tutorial-spot");
    const coach = doc.getElementById("tutorialCoach");
    if (!entry || !target || !spot || !coach) ctx.fail(ERROR_CODES.CONTRACT, "튜토리얼 필수 DOM 요소가 없습니다.");
    await ctx.waitFor(() => spot.getBoundingClientRect().width > 0, { what: "튜토리얼 spotlight 기하", timeoutMs: 1000 });
    const targetHit = hit(target);
    const outsideHit = doc.elementFromPoint(8, ctx.win.innerHeight - 8);
    const entryHit = hit(entry);
    entry.click();
    await ctx.waitFor(() => !!doc.getElementById("tutorialPanel"), { what: "HUD 펼침", timeoutMs: 1000 });
    const panel = doc.getElementById("tutorialPanel");
    const panelHit = hit(panel);
    const normal = {
      target_hit: targetHit === target || target.contains(targetHit),
      off_target_free: !!outsideHit && !outsideHit.closest(".tutorial-guide, .tutorial-shield"),
      hud_hit: entryHit === entry || entry.contains(entryHit),
      panel_hit: panelHit === panel || panel.contains(panelHit),
      coach_in_view: bounds(coach),
      spot_covers_target: (() => { const a = spot.getBoundingClientRect(); const b = target.getBoundingClientRect();
        return a.left <= b.left && a.top <= b.top && a.right >= b.right && a.bottom >= b.bottom; })(),
    };
    doc.documentElement.setAttribute("data-font-scale", "larger");
    await new Promise((resolve) => ctx.win.requestAnimationFrame(() => ctx.win.requestAnimationFrame(resolve)));
    await ctx.waitFor(() => bounds(coach), { what: "150% 코치 기하", timeoutMs: 1000 });
    const large = { coach_150_in_view: bounds(coach), hud_150_hit: (() => {
      const now = hit(entry); return now === entry || entry.contains(now);
    })() };
    entry.click();
    // #1127: a dialog hosts the guide exactly when the beat's boxed control is inside it.
    pending = ctx.services.Modal.confirm({ title: "대상 확인", body: "대화상자 안의 대상", confirmLabel: "확인", cancelLabel: "취소" });
    ctx.push("tutorial", { ...synthetic, beat: { ...synthetic.beat, id: "selftest-dialog", target: "dialog-confirm" } });
    await ctx.waitFor(() => !!doc.querySelector("#confirmModal #tutorialCoach"),
      { what: "확인 대화상자 안의 연습 안내", timeoutMs: 2000 });
    const modal = doc.getElementById("confirmModal");
    const inline = modal.querySelector("#tutorialCoach");
    const exit = modal.querySelector("#tutorialDialogExit");
    const boxed = doc.getElementById("confirmModalOk");
    exit.focus();
    const dialog = {
      dialog_guide_in_focus_boundary: modal.contains(inline) && inline.getAttribute("role") === "region",
      dialog_exit_reachable: doc.activeElement === exit,
      dialog_target_hit: (() => { const current = hit(boxed); return current === boxed || boxed.contains(current); })(),
    };
    exit.dispatchEvent(new ctx.win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await ctx.waitFor(() => !doc.querySelector("#confirmModal #tutorialCoach") && !!doc.querySelector("#tutorialPanelRoot #tutorialCoach"),
      { what: "Escape 뒤 현재 단계 안내 복귀", timeoutMs: 2000 });
    await pending;
    return { ...normal, ...large, ...dialog, dialog_escape_keeps_guide: !!doc.getElementById("tutorialCoach") };
  } finally {
    ctx.services.Modal?.close("confirmModal");
    if (oldScale === null) doc.documentElement.removeAttribute("data-font-scale");
    else doc.documentElement.setAttribute("data-font-scale", oldScale);
    ctx.push("tutorial", real);
    const entry = doc.getElementById("tutorialOpen");
    if (entry?.getAttribute("aria-expanded") === "true") entry.click();
    if (oldScreen && oldScreen !== nav.currentScreen()) nav.go(oldScreen, { force: true });
  }
}

/** 판정 술어 — 위반이면 사유 문자열, 정상이면 null. 프로브와 단위 테스트가 **같은 하나**를
 *  쓴다(두 곳이 따로 판정하면 「루프는 통과, 게이트는 빨강」 갈림이 생긴다 — live 게이트 선례). */
export function judgeReactRuntime(value) {
  if (value.mounted !== "1") {
    return `data-react-mounted 가 "1" 이 아닙니다: ${JSON.stringify(value.mounted)}`;
  }
  if (typeof value.store_rev !== "string" || !DECIMAL.test(value.store_rev)) {
    return `data-react-store-rev 가 십진 문자열이 아닙니다: ${JSON.stringify(value.store_rev)}`;
  }
  if (value.roots !== 1) {
    return `마운트 마커를 단 요소가 정확히 1이 아닙니다: ${value.roots}`;
  }
  return null;
}

/** 클러스터 R 의 프로브 정의 전체 — 정의만 만들고 DOM 은 호출 시점에만 만진다(순수). */
export function createReactRuntimeProbes() {
  return [
    {
      name: "react_runtime",
      keys: [...REACT_RUNTIME_KEYS],
      cluster: REACT_RUNTIME_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      /* 레거시 부재 신설 축 — 전 레거시 자리(최대 3993)를 넘는 단일 관례값. 실행 순서
         tiebreak 에만 닿고 이 프로브의 판독은 순서 독립이다(값 단언 없음). */
      legacySite: 9990,
      deadlineMs: 7000,
      deadlineRationale:
        "React 마커 판독과 같은 창의 tutorial HUD·spotlight hit test. tutorial 스냅샷과"
        + " 글자 150%를 임시 적용해 측정한 뒤 원복하며 별도 부팅은 없다.",
      precondition: (ctx) => {
        const root = ctx.doc.getElementById(ROOT_ID);
        return root !== null
          && root.getAttribute(MOUNT_MARKER) !== null
          && root.getAttribute(STORE_REV) !== null;
      },
      preconditionWhat: "React 마운트·store 마커 존재",
      run: async (ctx) => {
        const value = measureReactRuntime(ctx);
        const violation = judgeReactRuntime(value);
        if (violation !== null) ctx.fail(ERROR_CODES.CONTRACT, violation);
        value.tutorial_surface = await measureTutorialSurface(ctx);
        return { react_runtime: value };
      },
    },
  ];
}
