/* 온보딩 튜토리얼 셸 표면의 렌더 계약과 순간 카드 큐 (슬라이스 E · #894).
 *
 * 두 축을 잰다 — overlay_host 테스트와 같은 갈래다.
 *
 * 1. **렌더 요소 계약** — 실 서버 렌더(`react-dom/server`)로 요소 트리를 실제 산출해,
 *    컴포넌트 소스의 문자열이 아니라 **렌더 결과**를 본다. 패널이 네 화면 어디서나 같은
 *    형상으로 서는지(셸 레벨이라 화면 이름은 `data-screen` 표식일 뿐), 접힘·닫힘·재개가
 *    무엇을 걷고 무엇을 남기는지, 문안이 전부 스냅샷에서 오는지.
 * 2. **큐 소비·억제 분기** — 화면에 선 장은 **큐에서 파생**이라(`momentToShow`) 지역
 *    상태가 아니고, 그래서 서버 렌더로도 그대로 관측된다. 소비는 그 장의 시간이 다 됐을
 *    때 일어나는 왕복이라 effect 안에 있다 — node 환경이 실 클라이언트 커밋을 받쳐 주지
 *    않으므로(`react_root.test.js` 머리말) 그 시각 배선의 실증거는 live 게이트(슬라이스 F)
 *    몫이고, 여기서는 **어느 장이 서는가**의 규칙을 남김없이 잰다.
 *
 * 억제 축이 `needs_confirm` 플래그가 아니라 overlay 엔진인 이유는 제품과 같다: 그 플래그는
 * 화면 컨트롤러마다 흩어져 있어 중앙 관측점이 못 된다.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  MOMENT_VISIBLE_MS,
  TutorialPanel,
  momentToShow,
  nextStepOf,
} from "../../frontend/src/tutorial/panel.ts";

/* ────────────────────────── 하니스 ────────────────────────── */

const KIND = "tutorial-checklist/v1";

function step(milestone, title, achieved, extra = {}) {
  return {
    milestone,
    title,
    next_step: `${title} 하세요.`,
    moment_copy: `${title} 의미.`,
    achieved,
    ...extra,
  };
}

function snapshot(overrides = {}) {
  return {
    kind: KIND,
    started: true,
    active: true,
    dismissed: false,
    achieved_count: 1,
    step_count: 3,
    standard_complete: false,
    all_complete: false,
    suggested_tier: "basic",
    tiers: [
      {
        tier: "basic",
        label: "기본",
        title: "첫 문서",
        optional: false,
        complete: false,
        graduation_copy: "기본 졸업 문안",
        invitation: "기본 초대 문안",
        achieved_count: 1,
        step_count: 2,
        steps: [step("T0", "예제 설치", true), step("T1", "템플릿 고르기", false)],
      },
      {
        tier: "deep",
        label: "심화",
        title: "구간",
        optional: true,
        complete: false,
        graduation_copy: "심화 졸업 문안",
        invitation: "심화 초대 문안",
        achieved_count: 0,
        step_count: 1,
        steps: [step("T17", "구성 바꿔 생성", false)],
      },
    ],
    moment_queue: [],
    ...overrides,
  };
}

/** 렌더 1회 — `ports` 는 안정 참조 규약을 그대로 흉내낸다(구독은 즉시 해제 클로저 반환). */
function render(snap, options = {}) {
  const sent = [];
  const ports = {
    model: {
      getSnapshot: () => snap,
      subscribe: () => () => {},
    },
    loadInitial: () => Promise.resolve(snap),
    dispatch: (action, payload) => {
      sent.push([action, payload]);
      return Promise.resolve(null);
    },
    nav: {
      subscribe: () => () => {},
      currentScreen: () => options.screen ?? "job",
    },
    overlay: {
      subscribe: () => () => {},
      isBusy: () => options.busy === true,
    },
    alarm: () => {},
  };
  return { markup: renderToStaticMarkup(createElement(TutorialPanel, ports)), sent };
}

/* ────────────────────────── 1. 패널 렌더 계약 ────────────────────────── */

test("패널은 네 화면 전부에서 같은 형상으로 서고 화면 이름만 표식으로 남는다", () => {
  for (const screen of ["job", "library", "editor", "workbench"]) {
    const { markup } = render(snapshot(), { screen });
    assert.match(markup, /id="tutorialPanelRoot"/, `${screen}: 패널 루트 부재`);
    assert.match(markup, /id="tutorialPanel"/, `${screen}: 패널 부재`);
    assert.match(
      markup,
      new RegExp(`data-screen="${screen}"`),
      `${screen}: 셸 관측 화면 표식이 실리지 않았습니다`,
    );
  }
});

test("머리 줄 — 제목·진행 수치·접기·닫기가 각자 안정 id 로 선다", () => {
  const { markup } = render(snapshot());
  assert.match(markup, /<h3 id="tutorialPanelTitle" class="tut-title">튜토리얼<\/h3>/);
  assert.match(markup, /id="tutorialProgress"[^>]*>1\/3</);
  assert.match(markup, /id="tutorialCollapse"[^>]*aria-expanded="true"/);
  assert.match(markup, /id="tutorialDismiss"[^>]*>튜토리얼 닫기</);
});

test("문안은 전부 스냅샷에서 온다 — 티어·단계·다음 걸음·초대", () => {
  const { markup } = render(snapshot());
  assert.match(markup, /id="tutorialNextStep"[^>]*>템플릿 고르기 하세요\.</,
    "다음 걸음은 제안 티어의 첫 미달성 단계 문안이어야 합니다");
  assert.match(markup, /기본<\/span><span class="tut-tier-title">첫 문서/);
  assert.match(markup, /data-milestone="T0"[^>]*data-achieved="1"/);
  assert.match(markup, /data-milestone="T1"[^>]*data-achieved="0"/);
  // 제안 티어만 초대 문안을 세운다 — 아직 안 온 티어가 권유하지 않는다.
  assert.match(markup, /기본 초대 문안/);
  assert.ok(!markup.includes("심화 초대 문안"), "제안 티어가 아닌 곳에 초대 문안이 섰습니다");
});

test("완료 단계는 순간 카드 문안을 펼침에 남긴다(§1 D3 — 놓쳐도 사라지지 않는다)", () => {
  const { markup } = render(snapshot());
  assert.match(markup, /예제 설치 의미\./);
  // 미달성 단계는 그 문안을 미리 흘리지 않는다(행동 후 의미 부여라서).
  assert.ok(!markup.includes("템플릿 고르기 의미."), "미달성 단계의 순간 문안이 새어 나왔습니다");
});

test("졸업한 티어는 졸업 문안을 세우고 초대 문안을 걷는다", () => {
  const snap = snapshot();
  snap.tiers[0].complete = true;
  const { markup } = render(snap);
  assert.match(markup, /기본 졸업 문안/);
  assert.ok(!markup.includes("기본 초대 문안"));
  assert.match(markup, /data-complete="1"/);
});

test("접으면 본문이 렌더에서 걷힌다 — hidden 이 아니라 부재(초점 순서 보호)", () => {
  // 접힘은 지역 상태라 서버 렌더의 기본값은 펼침이다. 펼침에서 본문이 있다는 것과,
  // 접힘 클래스·aria 가 같은 노드에 산다는 것을 함께 잰다.
  const { markup } = render(snapshot());
  assert.match(markup, /id="tutorialBody"/);
  assert.match(markup, /id="tutorialCollapse"[^>]*aria-controls="tutorialBody"/);
  assert.match(markup, /class="tut-panel"[^>]*data-collapsed="0"/);
});

test("시작 전에는 아무것도 그리지 않는다 — 평소 사용이 패널을 불러내지 않는다", () => {
  const { markup } = render(snapshot({ started: false, active: false }));
  assert.equal(markup, "");
});

test("형상 이름표가 다르면 그리지 않는다 — 추측해 반쪽 패널을 세우지 않는다", () => {
  assert.equal(renderToStaticMarkup(createElement(TutorialPanel, {
    model: { getSnapshot: () => null, subscribe: () => () => {} },
    loadInitial: () => Promise.resolve(null),
    dispatch: () => Promise.resolve(null),
    nav: { subscribe: () => () => {}, currentScreen: () => "job" },
    overlay: { subscribe: () => () => {}, isBusy: () => false },
    alarm: () => {},
  })), "");
});

test("닫으면 체크리스트는 걷히고 재개 문 하나만 남는다", () => {
  const { markup } = render(snapshot({ active: false, dismissed: true }));
  assert.match(markup, /class="tut-root is-dismissed"/);
  assert.match(markup, /id="tutorialResume"[^>]*>튜토리얼 다시 열기</);
  assert.ok(!markup.includes('id="tutorialPanel"'), "닫힌 뒤에도 패널 본체가 남았습니다");
  assert.ok(!markup.includes('id="tutorialBody"'));
});

/* ────────────────────────── 2. 순간 카드 큐 ────────────────────────── */

test("큐가 비면 카드가 서지 않는다", () => {
  const { markup } = render(snapshot());
  assert.ok(!markup.includes('id="tutorialMoment"'));
});

test("큐의 맨 앞 한 장만 선다 — 동시 1장", () => {
  const snap = snapshot({
    moment_queue: [
      { milestone: "T0", title: "예제 설치", moment_copy: "예제가 들어왔습니다." },
      { milestone: "T1", title: "템플릿 고르기", moment_copy: "필드가 올라왔습니다." },
    ],
  });
  const { markup } = render(snap);
  assert.match(markup, /id="tutorialMoment"[^>]*data-milestone="T0"/);
  assert.match(markup, /예제가 들어왔습니다\./);
  assert.equal(markup.split('id="tutorialMoment"').length - 1, 1, "카드가 두 장 섰습니다");
  assert.ok(!markup.includes("필드가 올라왔습니다."), "두 번째 장이 함께 섰습니다");
});

test("순간 카드는 상태 영역이고 클릭 대상이 아니다", () => {
  const snap = snapshot({
    moment_queue: [{ milestone: "T0", title: "예제 설치", moment_copy: "예제가 들어왔습니다." }],
  });
  const { markup } = render(snap);
  const at = markup.indexOf('id="tutorialMoment"');
  const opening = markup.slice(markup.lastIndexOf("<div", at), markup.indexOf(">", at) + 1);
  assert.match(opening, /role="status"/);
  assert.match(opening, /aria-live="polite"/);
  // 요소 앵커 금지(§1 D3) — 카드는 어떤 요소도 겨누지 않는다.
  assert.ok(!/data-anchor|aria-describedby|data-target/.test(opening),
    "순간 카드가 요소를 겨눴습니다 — 코치마크는 기각입니다");
  const cardMarkup = markup.slice(markup.lastIndexOf("<div", at));
  assert.ok(!cardMarkup.includes("<button"), "순간 카드에 조작 상자가 들어갔습니다");
});

test("확인 모달이 떠 있으면 카드가 억제된다 — 체크리스트는 그대로 산다", () => {
  const snap = snapshot({
    moment_queue: [{ milestone: "T0", title: "예제 설치", moment_copy: "예제가 들어왔습니다." }],
  });
  const { markup } = render(snap, { busy: true });
  assert.ok(!markup.includes('id="tutorialMoment"'), "억제 중에 카드가 섰습니다");
  assert.match(markup, /id="tutorialPanel"/, "억제 대상은 카드뿐인데 패널까지 걷혔습니다");
});

test("닫힌 동안에는 큐가 실려 와도 카드를 세우지 않는다", () => {
  const snap = snapshot({
    active: false,
    dismissed: true,
    moment_queue: [{ milestone: "T0", title: "예제 설치", moment_copy: "예제가 들어왔습니다." }],
  });
  const { markup } = render(snap);
  assert.ok(!markup.includes('id="tutorialMoment"'));
});

test("momentToShow — 큐에서 파생이고, 억제·미활성은 큐를 남긴 채 아무 장도 내지 않는다", () => {
  const a = { milestone: "T0", title: "예제 설치", moment_copy: "하나" };
  const b = { milestone: "T1", title: "템플릿", moment_copy: "둘" };
  const queue = [a, b];
  assert.equal(momentToShow({ active: true, suppressed: false, queue }), a,
    "선 장은 늘 큐의 맨 앞이다");
  assert.equal(momentToShow({ active: true, suppressed: true, queue }), null,
    "억제 중에는 아무 장도 서지 않는다");
  assert.equal(momentToShow({ active: false, suppressed: false, queue }), null,
    "닫혔거나 시작 전이면 아무 장도 서지 않는다");
  assert.equal(momentToShow({ active: true, suppressed: false, queue: [] }), null);
  assert.equal(momentToShow({ active: true, suppressed: false, queue: undefined }), null,
    "스냅샷 도착 전에도 시끄럽게 죽지 않는다");
  // 억제가 풀리면 **같은 장**이 처음부터 다시 선다(큐를 건드리지 않았으므로).
  assert.equal(momentToShow({ active: true, suppressed: false, queue }), a);
});

/* ────────────────────────── 3. 다음 걸음 선택 ────────────────────────── */

test("nextStepOf 는 제안 티어의 첫 미달성 단계다 — 순서도 링1 배열 그대로", () => {
  const snap = snapshot();
  assert.equal(nextStepOf(snap).milestone, "T1");
  snap.tiers[0].steps[1].achieved = true;
  assert.equal(nextStepOf(snap), null, "그 티어에 남은 단계가 없으면 안내할 걸음도 없다");
  snap.suggested_tier = "deep";
  assert.equal(nextStepOf(snap).milestone, "T17");
  snap.suggested_tier = "";
  assert.equal(nextStepOf(snap), null, "제안 티어가 없으면(전부 졸업) 걸음도 없다");
});

test("자동 소멸 시간은 공용 상수 하나다", () => {
  assert.equal(typeof MOMENT_VISIBLE_MS, "number");
  assert.ok(MOMENT_VISIBLE_MS > 0);
});
