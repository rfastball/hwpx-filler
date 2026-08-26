/* 온보딩 튜토리얼 — 체크리스트 셸 패널 + 순간 카드 (슬라이스 E · #894).
 *
 * 정본은 `docs/ONBOARDING_TUTORIAL.md` §1 D3(체크리스트 + 순간 카드)·§4.3(렌더·통신)이다.
 *
 * ## 이 파일이 판정하지 않는 것 — 전부다
 *
 * 단계·티어·달성·다음 걸음·졸업·제안·순간 카드 문안은 **링1**(`gui/tutorial_state.py`)이
 * 소유하고 스냅샷으로 내려온다. 여기는 그것을 그리기만 한다. 문안을 조립하거나 「어느
 * 단계가 끝났는가」를 다시 세면 그 순간 같은 상태의 두 번째 판정자가 된다(제품 규칙).
 * 이 파일에 사용자 대면 문장으로 남는 것은 패널 자체의 조작 라벨뿐이다(제목·접기·닫기·
 * 다시 열기) — 그것들은 링1 커리큘럼이 아니라 이 표면의 가구다.
 *
 * ## 왜 `.topbar` 가 아니라 셸 레벨인가
 *
 * editor·workbench 는 몰입 표면이라 body 클래스가 상단 토바를 덮는다(`IMMERSIVE_SURFACES`).
 * 토바 안에 패널을 두면 네 화면 중 둘에서 사라진다. 그래서 패널은 React 트리의 셸 레벨
 * 형제(`react/boundary.ts` 의 `createAppElement`)로 서고 `#reactRoot` 안에 그려진다 —
 * 화면 stage 밖이라 화면 전환이 이 서브트리를 unmount 하지 않는다.
 *
 * 화면 전환은 `shellNav.subscribe()` 로 **관측**한다. `go()` 성공을 낙관 가정하지 않는
 * 이유는 편집기 이탈 가드가 전환을 취소할 수 있어서다 — 취소된 전환으로 패널이 남의 화면
 * 이름을 달면 CSS 좌표가 실제와 어긋난다.
 *
 * ## 순간 카드 — 요소를 짚지 않는다
 *
 * 코치마크는 기각이다(§1 D3): 앵커 좌표가 DOM 계약의 소비자가 되면 화면 개편마다
 * 드리프트한다. 그래서 카드는 어떤 요소도 겨누지 않는 고정 자리에 뜨고, `pointer-events`
 * 를 받지 않아 클릭을 **가로채지 않는다**(CSS 소유). 확인 모달이 떠 있는 동안은 억제하고,
 * 동시 1장이며, 자동 소멸한다.
 *
 * 큐 소비는 백엔드 왕복이다(`consume_moment`). 프런트가 자기 안에서 지우면 다음 스냅샷이
 * 같은 카드를 다시 싣는다 — 소비 사실의 정본은 링1 의 큐 하나다.
 *
 * ## 세 국면 — 진행 · 완주 · 초점 (#918 A·C)
 *
 * 렌더 분기는 `started`·`dismissed` 둘이 아니라 본문의 세 국면을 함께 가른다.
 *
 * - **진행**: 다음 걸음 한 줄 + 전 과정 체크리스트 + 다시 보기 자리.
 * - **완주**(`standard_complete` ∧ 초점 없음): 체크리스트 대신 완주 문안 + 다시 보기 자리.
 *   18/18 인 채 「다음 걸음」을 계속 가리키던 것이 #918 A 다.
 * - **초점**(`focus_tier` ≠ ""): 그 과정 하나만 + 되돌아가지 않는 것의 문안 + 해제 동선.
 *
 * 국면 판정의 재료(`standard_complete`·`focus_tier`·`guided_tier`·문안)는 전부 링1 이 실어
 * 보낸다. 여기서 하는 것은 그 값들로 어느 가지를 그릴지 고르는 일뿐이다.
 */
import { createElement, useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

/** 순간 카드가 화면에 머무는 시간(ms). 억제 중에는 이 시계가 돌지 않는다 — 모달에 가려
 *  있던 시간이 표시 시간으로 소진되면 사용자는 그 카드를 영영 못 본다. */
export const MOMENT_VISIBLE_MS = 6000;

export type TutorialStepSnapshot = {
  milestone: string;
  title: string;
  next_step: string;
  moment_copy: string;
  achieved: boolean;
};

export type TutorialTierSnapshot = {
  tier: string;
  label: string;
  title: string;
  optional: boolean;
  complete: boolean;
  graduation_copy: string;
  invitation: string;
  /** 이 과정을 다시 겨눴을 때 **되돌아가지 않는 것**의 문안(없으면 ""). */
  replay_caveat: string;
  achieved_count: number;
  step_count: number;
  steps: readonly TutorialStepSnapshot[];
};

export type TutorialMomentSnapshot = {
  milestone: string;
  title: string;
  moment_copy: string;
};

export type TutorialSnapshot = {
  kind: string;
  started: boolean;
  active: boolean;
  dismissed: boolean;
  achieved_count: number;
  step_count: number;
  standard_complete: boolean;
  all_complete: boolean;
  /** 파생 제안(첫 미졸업 과정). 그릴 때 보는 것은 `guided_tier` 다. */
  suggested_tier: string;
  /** 사용자가 명시로 겨눈 과정(없으면 ""). 국면을 가르는 축. */
  focus_tier: string;
  /** 안내가 실제로 겨누는 과정 = 초점 ?? 제안. 둘을 표면이 다시 합치지 않는다. */
  guided_tier: string;
  focus_caveat: string;
  completion_title: string;
  completion_copy: string;
  revisit_prompt: string;
  tiers: readonly TutorialTierSnapshot[];
  moment_queue: readonly TutorialMomentSnapshot[];
};

export type TutorialPorts = {
  /** `runtime.model("tutorial")` — 안정 참조 subscribe/getSnapshot 쌍. */
  model: {
    getSnapshot(): unknown;
    subscribe(listener: () => void): () => void;
  };
  /** 부팅 1회 당김(`runtime.loadInitial("tutorial")`). 실패는 경보로 착지한다. */
  loadInitial(): Promise<unknown>;
  /** `client.dispatch("tutorial", …)` 의 좁은 투영. */
  dispatch(action: string, payload?: Record<string, unknown>): Promise<unknown>;
  /** 셸 상태기계 관측 — 전환·ready 전이. 판정은 저쪽 소유이고 여기는 읽기만 한다. */
  nav: {
    subscribe(listener: () => void): () => void;
    currentScreen(): string | null;
  };
  /** overlay 엔진 관측 — 확인 모달이 떠 있는가(순간 카드 억제 축). */
  overlay: {
    subscribe(listener: () => void): () => void;
    isBusy(): boolean;
  };
  alarm(message: string): void;
};

/** 스냅샷 형상의 이름표 — 링1 `_SNAPSHOT_KIND` 와 같은 값. 형상을 되묻지 않고 분기한다. */
const SNAPSHOT_KIND = "tutorial-checklist/v1";

/** 도착 전(null)·형상 불일치는 **그리지 않는다**. 추측해 반쪽 패널을 세우지 않는다. */
function asSnapshot(value: unknown): TutorialSnapshot | null {
  if (value === null || typeof value !== "object") return null;
  const candidate = value as { kind?: unknown };
  if (candidate.kind !== SNAPSHOT_KIND) return null;
  return value as TutorialSnapshot;
}

/** 지금 안내할 걸음 — 겨눈 과정(링1 판정)의 첫 미달성 단계. 없으면 `null`.
 *
 *  「어느 과정인가」는 링1 이 정한다(`guided_tier` = 명시 초점 ?? 파생 제안). 여기서 하는
 *  것은 그 과정 안에서 표 순서상 첫 미달성을 고르는 일뿐이고, 그 순서 역시 링1 이 실어 보낸
 *  배열 순서다. 다 걸은 과정을 겨누면 남은 걸음이 없어 `null` 이고, 그때 안내 자리에 서는
 *  것은 「다음 걸음」이 아니라 완주 문안이다(#918 A). */
export function nextStepOf(snapshot: TutorialSnapshot): TutorialStepSnapshot | null {
  const tier = snapshot.tiers.find((entry) => entry.tier === snapshot.guided_tier);
  if (tier === undefined) return null;
  return tier.steps.find((step) => !step.achieved) ?? null;
}

/** 지금 겨눈 과정의 스냅샷 — 명시 초점이 없으면 `null`(국면 판정의 축).
 *
 *  파생 제안으로는 이 값이 서지 않는다: 제안은 「다음에 갈 곳」이고 초점은 「지금 이것만
 *  본다」라서, 둘을 한 값으로 합치면 아직 안 걸은 과정이 혼자 서고 나머지가 사라진다. */
export function focusedTierOf(snapshot: TutorialSnapshot): TutorialTierSnapshot | null {
  if (snapshot.focus_tier === "") return null;
  return snapshot.tiers.find((entry) => entry.tier === snapshot.focus_tier) ?? null;
}

function stepNode(step: TutorialStepSnapshot): ReactNode {
  /* 완료 단계는 순간 카드 문안을 **펼침에 남긴다**(§1 D3) — 카드를 놓쳐도 같은 말이
     여기 있어야 「지나갔는데 왜 그랬는지 모른다」가 생기지 않는다. */
  return createElement(
    "li",
    {
      key: step.milestone,
      className: step.achieved ? "tut-step is-done" : "tut-step",
      "data-milestone": step.milestone,
      "data-achieved": step.achieved ? "1" : "0",
    },
    createElement("span", { className: "tut-step-mark", "aria-hidden": "true" }, step.achieved ? "✓" : "○"),
    createElement(
      "span",
      { className: "tut-step-body" },
      createElement("span", { className: "tut-step-title" }, step.title),
      step.achieved
        ? createElement("span", { className: "tut-step-note" }, step.moment_copy)
        : null,
    ),
  );
}

function tierNode(tier: TutorialTierSnapshot, guided: string): ReactNode {
  return createElement(
    "section",
    {
      key: tier.tier,
      className: tier.complete ? "tut-tier is-complete" : "tut-tier",
      "data-tier": tier.tier,
      "data-complete": tier.complete ? "1" : "0",
    },
    createElement(
      "h4",
      { className: "tut-tier-head" },
      createElement("span", { className: "tut-tier-label" }, tier.label),
      createElement("span", { className: "tut-tier-title" }, tier.title),
      createElement(
        "span",
        { className: "tut-tier-count" },
        `${tier.achieved_count}/${tier.step_count}`,
      ),
    ),
    /* 졸업 문안은 졸업했을 때, 초대 문안은 **지금 제안 중인 티어**일 때만 선다. 둘을 늘
       같이 그리면 아직 시작도 안 한 티어가 "할 수 있습니다"라고 말한다. */
    tier.complete
      ? createElement("p", { className: "tut-tier-grad" }, tier.graduation_copy)
      : tier.tier === guided
        ? createElement("p", { className: "tut-tier-invite" }, tier.invitation)
        : null,
    createElement("ul", { className: "tut-steps" }, tier.steps.map(stepNode)),
  );
}

/** 다시 볼 과정을 고르는 자리 — 안내 한 줄(링1 문안) + 과정 버튼들.
 *
 *  이 줄이 #918 C 의 답이다: 지나간 과정을 겨눌 길이 없어서 안내는 늘 「첫 미졸업」만
 *  가리켰고, 다 걸으면 그마저 사라졌다. 버튼이 보내는 것은 초점뿐이고 **달성 기록은 손대지
 *  않는다** — 한 일을 안 했다고 말하지 않는다(링1 머리말 「두 축」). */
function revisitNode(
  snapshot: TutorialSnapshot,
  send: (action: string, payload?: Record<string, unknown>) => void,
): ReactNode {
  return createElement(
    "div",
    { key: "revisit", className: "tut-revisit" },
    createElement("p", { id: "tutorialRevisit", className: "tut-revisit-lead" }, snapshot.revisit_prompt),
    createElement(
      "div",
      { id: "tutorialTierPicker", className: "tut-picker", role: "group", "aria-labelledby": "tutorialRevisit" },
      ...snapshot.tiers.map((tier) => createElement(
        "button",
        {
          key: tier.tier,
          type: "button",
          className: "btn sm tut-pick",
          "data-tier": tier.tier,
          onClick: () => { send("focus_tier", { tier: tier.tier }); },
        },
        createElement("span", { className: "tut-pick-label" }, tier.label),
        createElement(
          "span",
          { className: "tut-pick-count" },
          `${tier.achieved_count}/${tier.step_count}`,
        ),
      )),
    ),
  );
}

/** 완주 자리 — 체크리스트가 서던 곳에 완주 문안이 선다.
 *
 *  표준 완주와 전체 완주가 다른 말을 하지만 그 갈림은 링1 이 이미 했다: 여기 오는 것은
 *  문자열 둘뿐이라 표면이 「어디까지 했는가」를 다시 세지 않는다. */
function completionNode(snapshot: TutorialSnapshot): ReactNode {
  return createElement(
    "div",
    { key: "complete", id: "tutorialComplete", className: "tut-done" },
    createElement("strong", { className: "tut-done-title" }, snapshot.completion_title),
    createElement("p", { className: "tut-done-copy" }, snapshot.completion_copy),
  );
}

/** 지금 띄울 카드 한 장 — 없으면 `null`. **큐에서 파생**이지 지역 상태가 아니다.
 *
 *  지역 상태로 들고 있다가 「띄우자마자 소비」하면, 소비가 큐를 줄이는 순간 화면의 카드와
 *  큐가 갈려 두 곳이 같은 것을 다르게 안다. 그래서 화면은 늘 **큐의 맨 앞**이고, 소비는
 *  그 장의 시간이 다 됐을 때 일어난다 — 소비가 곧 다음 장으로 넘어가는 사건이다.
 *
 *  억제(확인 모달)와 미시작·닫힘에서는 아무 장도 서지 않는다. 큐는 그대로 남으므로
 *  모달이 닫히면 같은 장이 처음부터 다시 선다. */
export function momentToShow(input: {
  active: boolean;
  suppressed: boolean;
  queue: readonly TutorialMomentSnapshot[] | undefined;
}): TutorialMomentSnapshot | null {
  if (!input.active || input.suppressed) return null;
  const queue = input.queue;
  if (queue === undefined || queue.length === 0) return null;
  return queue[0] ?? null;
}

/** 순간 카드 하나 — 요소를 겨누지 않는 고정 자리(머리말). */
function momentNode(moment: TutorialMomentSnapshot): ReactNode {
  return createElement(
    "div",
    {
      id: "tutorialMoment",
      className: "tut-moment",
      role: "status",
      "aria-live": "polite",
      "data-milestone": moment.milestone,
    },
    createElement("strong", { className: "tut-moment-title" }, moment.title),
    createElement("span", { className: "tut-moment-copy" }, moment.moment_copy),
  );
}

/** 셸 레벨 튜토리얼 표면 — 체크리스트 패널 + 순간 카드. 트리에 정확히 하나. */
export function TutorialPanel(ports: TutorialPorts): ReactNode {
  const raw = useSyncExternalStore(ports.model.subscribe, ports.model.getSnapshot, ports.model.getSnapshot);
  const screen = useSyncExternalStore(ports.nav.subscribe, ports.nav.currentScreen, ports.nav.currentScreen);
  const suppressed = useSyncExternalStore(ports.overlay.subscribe, ports.overlay.isBusy, ports.overlay.isBusy);

  const [collapsed, setCollapsed] = useState(false);

  const snapshot = useMemo(() => asSnapshot(raw), [raw]);

  const { alarm } = ports;
  const send = useCallback(
    (action: string, payload?: Record<string, unknown>): void => {
      ports.dispatch(action, payload).catch((error: unknown) => {
        alarm(`튜토리얼 ${action} 실패 — ${String(error)}`);
      });
    },
    [ports, alarm],
  );

  /* 부팅 당김 — 화면 init 시퀀스에 얹지 않는다. 이 표면은 화면이 아니라 셸 레벨이고,
     자기 채널의 첫 스냅샷을 자기가 당기는 것이 소유 경계와 맞는다(`loadInitial` 은 채널당
     한 번을 기억하므로 재마운트가 왕복을 늘리지 않는다). */
  useEffect(() => {
    ports.loadInitial().catch((error: unknown) => {
      alarm(`튜토리얼 초기 상태를 불러오지 못했습니다 — ${String(error)}`);
    });
  }, [ports, alarm]);

  const card = momentToShow({
    active: snapshot !== null && snapshot.active,
    suppressed,
    queue: snapshot?.moment_queue,
  });
  const shown = card === null ? "" : card.milestone;

  /* 자동 소멸 = **소비**다. 시간이 다 되면 되알리고, 큐가 줄면서 다음 장이 그 자리에 선다.
     억제 중에는 시계가 아예 서지 않는다(`card` 가 null 이라 이 effect 가 걸리지 않는다) —
     모달에 가려 있던 시간이 표시 시간으로 소진되면 그 카드는 영영 안 보인 채 사라진다. */
  useEffect(() => {
    if (shown === "") return undefined;
    const timer = setTimeout(() => { send("consume_moment", { milestone: shown }); }, MOMENT_VISIBLE_MS);
    return () => { clearTimeout(timer); };
  }, [shown, send]);

  if (snapshot === null || !snapshot.started) return null;

  /* 명시 종료 뒤에도 **되돌아올 문**은 남긴다 — 닫기가 곧 영구 소멸이면 그것은 종료가
     아니라 파괴다(진행 기록은 그대로 살아 있다). */
  if (snapshot.dismissed) {
    return createElement(
      "div",
      { id: "tutorialPanelRoot", className: "tut-root is-dismissed", "data-screen": screen ?? "" },
      createElement(
        "button",
        {
          type: "button",
          id: "tutorialResume",
          className: "btn sm tut-resume",
          onClick: () => { send("resume"); },
        },
        "튜토리얼 다시 열기",
      ),
    );
  }

  const next = nextStepOf(snapshot);
  const focused = focusedTierOf(snapshot);
  /* 국면 셋(머리말): 초점이 서면 초점, 아니면 완주 여부. 「완주」의 기준은 링1 의 표준 완주
     (고급까지)다 — 선택 진입인 심화를 안 걸었다고 계속 걸음을 재촉하지 않는다(§3.6). */
  const phase = focused !== null ? "focus" : snapshot.standard_complete ? "complete" : "progress";
  const body: ReactNode[] = [];
  if (phase === "focus" && focused !== null) {
    if (next !== null) {
      body.push(createElement("p", { key: "next", id: "tutorialNextStep", className: "tut-next" }, next.next_step));
    }
    /* 되돌아가지 않는 것을 먼저 말하고 목록을 준다 — 「다시 보기」를 「되돌리기」로 읽고
       걷기 시작한 뒤에 알리면 이미 두 번째 작업이 생긴 뒤다(#918 C 한계 문안). */
    if (snapshot.focus_caveat !== "") {
      body.push(createElement("p", { key: "caveat", id: "tutorialFocusCaveat", className: "tut-caveat" }, snapshot.focus_caveat));
    }
    body.push(tierNode(focused, snapshot.guided_tier));
    body.push(createElement(
      "button",
      {
        key: "clear",
        type: "button",
        id: "tutorialFocusClear",
        className: "btn sm tut-focus-clear",
        onClick: () => { send("clear_focus"); },
      },
      "전체 보기",
    ));
  } else if (phase === "complete") {
    body.push(completionNode(snapshot));
    body.push(revisitNode(snapshot, send));
  } else {
    if (next !== null) {
      body.push(createElement("p", { key: "next", id: "tutorialNextStep", className: "tut-next" }, next.next_step));
    }
    body.push(...snapshot.tiers.map((tier) => tierNode(tier, snapshot.guided_tier)));
    body.push(revisitNode(snapshot, send));
  }

  return createElement(
    "div",
    { id: "tutorialPanelRoot", className: "tut-root", "data-screen": screen ?? "" },
    createElement(
      "aside",
      {
        id: "tutorialPanel",
        className: collapsed ? "tut-panel is-collapsed" : "tut-panel",
        "aria-labelledby": "tutorialPanelTitle",
        "data-collapsed": collapsed ? "1" : "0",
        "data-phase": phase,
      },
      createElement(
        "header",
        { className: "tut-head" },
        createElement("h3", { id: "tutorialPanelTitle", className: "tut-title" }, "튜토리얼"),
        createElement(
          "span",
          { id: "tutorialProgress", className: "tut-progress" },
          `${snapshot.achieved_count}/${snapshot.step_count}`,
        ),
        createElement(
          "button",
          {
            type: "button",
            id: "tutorialCollapse",
            className: "btn sm tut-collapse",
            "aria-expanded": collapsed ? "false" : "true",
            "aria-controls": "tutorialBody",
            onClick: () => { setCollapsed((value) => !value); },
          },
          collapsed ? "펼치기" : "접기",
        ),
        createElement(
          "button",
          {
            type: "button",
            id: "tutorialDismiss",
            className: "btn sm tut-dismiss",
            onClick: () => { send("dismiss"); },
          },
          "튜토리얼 닫기",
        ),
      ),
      /* 접힘은 렌더를 걷는다(hidden 이 아니라 부재) — 접힌 목록이 초점 순서에 남아 Tab 이
         보이지 않는 곳으로 가지 않게. 머리 줄은 남아 진행 수치를 계속 말한다. */
      collapsed ? null : createElement("div", { id: "tutorialBody", className: "tut-body" }, ...body),
    ),
    /* 억제 중에는 `momentToShow` 가 null 을 낸다 — 큐는 그대로라 모달이 닫히면 다시 선다. */
    card === null ? null : momentNode(card),
  );
}
