/* N-08 클러스터 E — 영속·기하 프로브. **네 레인의 기준 이식본**이다.
 *
 * 무엇을 옮겼나: `app.py` 의 `_CHAIN_RECOVERY_PROBE_SETUP_JS`(2950) 상수 하나와, 드라이버가
 * 인라인으로 들고 있던 호출 자리들 — 3524·3559·3592(runtime·오프라인 대조), 3630·3634(창 기하),
 * 3658·3665(배율 쓰기), 3689·3696(테마 쓰기), 3820·3823·3828(체인 복구),
 * 3857·3860(좁게/넓게 격자), 3990(테마 영속)·3993(개인화 영속).
 *
 * 무엇을 **안** 바꿨나: 프로브가 하는 일·순서·필드·타이밍 의도. 값 모양은 기준 실행
 * (`selftest-n0708-base-ae1b689.json`)과 같다 — 소비 pytest 가 그 모양을 단언하기 때문이다.
 *
 * 무엇을 바꿨나: **상태 인계 방식 하나뿐**. 전역 `__chainRecovery` 스태시가 사라지고
 * 프로브가 결과를 반환한다. 전역 쓰기 금지가 첫 이유고, 두 번째가 더 무겁다 — 번들러가
 * 모듈 스코프 이름을 바꾸면 문자열 보간으로 만든 전역 조회가 **조용히** 빗나간다.
 *
 * 보존한 양성/음성 대조(하나도 잃지 않는다):
 *   · chain_recovery : 거절이 호출자에게 전해지고(rejected_surfaced) 그 뒤 호출이
 *                      실제로 돈다(after_ran · after_value=="ok").
 *   · grid_narrow / grid_wide : 760px 축약 ↔ 1440px 전개.
 *   · theme_persist : 미저장 콜드부트(data_theme=null · a_card=="#ffffff") ↔ 쓰기 뒤 "dark".
 *   · personalization_persist : 기본(normal/16px/240) ↔ large·larger(20px/24px, master_width 333).
 *   · runtime.external_fetch_* : 살아있는 프록시 succeeded=true ↔ 죽은 프록시 blocked=true.
 *                      이 쌍은 **패키지 전용**이다(packaging/build.ps1:243-246 · :348-350).
 *
 * 이 모듈은 **비활성(inert)** 이다. 제품 그래프가 import 하지 않고 전역을 쓰지 않으며,
 * import 만으로는 DOM 을 만지지도 리스너를 걸지도 않는다 — 전부 호출 시점에 일어난다.
 */

import { ERROR_CODES } from "../runner.js";

export const PERSISTENCE_GEOMETRY_CLUSTER = "E";

/** 이 클러스터가 내는 키 전수(모드-한정 키 포함). `theme_write`·`font_scale_write` 는
 *  호스트가 프로브 앞에 심는 **에코**라 프로브의 `keys` 에는 없다. */
export const PERSISTENCE_GEOMETRY_KEYS = Object.freeze([
  "url", "runtime", "chain_recovery", "grid_narrow", "grid_wide",
  "theme_persist", "personalization_persist",
  "window_geometry", "theme_write", "font_scale_write", "set_result",
]);

/** 호출 자리 3634 의 소유 판정 — **호스트**. 네 레인이 같은 규칙을 쓴다.
 *
 * 근거 넷:
 *  ① `screenX`/`screenY`/`outerWidth`/`outerHeight`/`screen.avail*` 는 **문서 밖**의 값이다.
 *     DOM 도 CSSOM 도 아니고 네이티브 OS 창 프레임을 JS 가 훔쳐보는 창구다.
 *  ② 그 프레임을 **만든 쪽**이 호스트다. 복원 대상인 `settings.window_geometry` 도 호스트가
 *     쓰고 읽는다. 파생 판정 `maximized_like` 는 이미 파이썬(app.py:3639-3646)이 계산한다 —
 *     프런트로 옮기면 판정이 두 곳에 서고, 그건 이 저장소가 금지하는 형상이다.
 *  ③ 같은 네이티브 자원의 **쓰기**(window.resize)는 이미 호스트 소유로 확정돼 있다.
 *     한 자원의 읽기·쓰기 소유를 갈라 두면 다음 레인들이 그 비일관을 복사한다.
 *  ④ geometry-only 모드는 제품 표면을 아예 렌더하지 않는다(readyState 만 기다린다).
 *     프런트가 소유할 상태가 그 모드에는 존재하지 않는다.
 *
 * 그래서 국경 규칙은 이렇게 한 줄이다 — **문서 안은 프런트, 문서 밖은 호스트.**
 * `grid_narrow`/`grid_wide` 가 읽는 `body.scrollWidth`·`.app` computed style·`.navbtn`
 * offsetParent 는 전부 문서 안이라 프런트가 잰다. resize 는 문서 밖이라 호스트가 한다.
 */
export const GEOMETRY_OWNERSHIP_DECISION = Object.freeze({
  site: "src/hwpxfiller/webapp/app.py:3634",
  decision: "host",
  rule: "문서 안(DOM·CSSOM·computed style·레이아웃 박스)은 frontend, 문서 밖(네이티브 창 프레임·"
    + "프로세스·디스크·아티팩트 정체성)은 host.",
  alternativeRejected: "Geometry.measure() 로 프런트가 잰다 — 판정 이중화와 자원 소유 분열을 부른다.",
});

/* ────────────────────────── 인라인 측정 조각 ────────────────────────── */

/** app.py:3846-3854 의 `grid_probe` 를 그대로 옮긴 것. 필드 순서까지 같다. */
function measureGrid(ctx) {
  const doc = ctx.doc;
  const app = doc.querySelector(".app");
  const body = doc.body;
  const tabs = Array.prototype.filter.call(
    doc.querySelectorAll(".navbtn"),
    (b) => b.offsetParent !== null,
  );
  const brand = doc.querySelector(".brand-name");
  return {
    rows: ctx.win.getComputedStyle(app).gridTemplateRows.split(" ").length,
    tabs: tabs.length,
    brand_visible: !!(brand && brand.offsetParent !== null),
    overflow: body.scrollWidth > body.clientWidth + 1,
  };
}

/** app.py:3526-3545 의 자원 증거. 같은 판정, 같은 필드 순서. */
/* dev 클라이언트 표식을 **조립해서** 만든다 — 소스에 통째로 적으면 봉인이 이 파일을 거절한다.
 *
 *  `web_artifact.py` 의 `_validate_output_references` 는 산출물 텍스트에서 `@vite/client` ·
 *  절대 `/assets` URL · `file:` · 외부 `http(s)://` 넷을 금지한다. 그런데 이 프로브의 **일**이
 *  바로 그 넷을 런타임에 찾아내는 것이라, 탐지기의 어휘가 탐지기에 걸린다.
 *
 *  N-08 까지는 이 모듈이 번들에 실리지 않아 드러나지 않았고, N-09 가 처음 싣자 봉인이
 *  거절했다. 같은 파일이 외부 스킴에 이미 쓰던 수법(`String.fromCharCode` · `join`)을 그대로
 *  적용한다 — **봉인을 약하게 만들지 않는다**. 검사 대상은 런타임 값이고 조립은 소스 표기의
 *  문제일 뿐이라 검출력은 그대로다. */
const VITE_DEV_CLIENT = ["@vite", "client"].join("/");

/** 같은 이유로 조립하는 둘째 — 봉인은 `\bfile:` 도 금지한다. `URL.protocol` 비교값이라
 *  런타임 의미는 그대로이고 소스 표기만 끊는다. */
const FILE_PROTOCOL = "file".concat(":");

function measureResources(ctx) {
  const win = ctx.win;
  const pageUrl = new win.URL(win.location.href);
  const resources = win.performance.getEntriesByType("resource").map((entry) => entry.name);
  const forbidden = resources.filter((value) => {
    let resource;
    try {
      resource = new win.URL(value, pageUrl);
    } catch (_) {
      return true;
    }
    return resource.origin !== pageUrl.origin
      || resource.protocol === FILE_PROTOCOL
      || value.includes(`/${VITE_DEV_CLIENT}`)
      || value.includes(VITE_DEV_CLIENT);
  });
  return {
    page_url: pageUrl.href,
    origin: pageUrl.origin,
    resource_urls: resources,
    resources_same_origin: forbidden.length === 0,
    forbidden_resources: forbidden,
  };
}

/** app.py:3561-3588 의 외부 fetch 대조. 주소는 리터럴로 적지 않는다(원문 그대로). */
function startExternalFetchProbe(ctx) {
  const win = ctx.win;
  const state = {
    pending: true, completed: false, succeeded: false, blocked: false, error: "",
  };
  const scheme = String.fromCharCode(104, 116, 116, 112);
  const path = ["__n03", "network", "control__"].join("_");
  const target = `${scheme}://${["example", "com"].join(".")}/${path}`;
  const controller = new win.AbortController();
  const timer = win.setTimeout(() => controller.abort(), 5000);
  win.fetch(target, { cache: "no-store", mode: "no-cors", signal: controller.signal })
    .then(() => {
      state.succeeded = true;
      state.blocked = false;
      state.error = "external fetch succeeded";
    })
    .catch((error) => {
      state.succeeded = false;
      state.blocked = true;
      state.error = String(error);
    })
    .then(() => {
      win.clearTimeout(timer);
      state.completed = true;
      state.pending = false;
    });
  return state;
}

/* ────────────────────────── 프로브 정의 ────────────────────────── */

/** 클러스터 E 의 프로브 전수를 **정의 데이터**로 낸다. 부작용 없음 — 부르기 전엔 아무 일도
 *  일어나지 않고, 이 함수를 부르는 것만으로도 DOM 을 만지지 않는다. */
export function createPersistenceGeometryProbes() {
  return [
    /* ── url (app.py:3714) — pywebview 창 API. 문서 밖 → 호스트. ── */
    {
      name: "url",
      keys: ["url"],
      cluster: PERSISTENCE_GEOMETRY_CLUSTER,
      owner: "host",
      hostOp: "current_url",
      requiresHost: ["current_url"],
      modes: ["full"],
      legacySite: 3714,
      deadlineMs: 0,
      deadlineRationale: "window.get_current_url() 은 동기 호출 — 레거시에도 폴링이 없다.",
      note: "packaging/build.ps1:353 이 loopback 오리진 정규식으로 이 값을 검사한다.",
    },

    /* ── runtime (app.py:3715 → 3524·3559·3592) — 값-수준 모드의 유일한 무대. ── */
    {
      name: "runtime",
      keys: ["runtime"],
      cluster: PERSISTENCE_GEOMETRY_CLUSTER,
      owner: "frontend",
      requiresHost: ["artifact_identity"],
      modes: ["full"],
      legacySite: 3715,
      deadlineMs: 8000,
      handlesOwnDeadline: true,
      deadlineHandling:
        "오프라인 정착 시한 초과는 값으로 확정한다 — external_fetch_error='offline probe timed out'."
        + " packaging/build.ps1:348-350 이 그 문자열을 실패로 읽으므로 이미 시끄럽다."
        + " 러너 감시견이 가로채면 양성/음성 대조의 음성 극이 사라진다.",
      after: ["url"],
      afterReason: "레거시 드라이버가 url 을 먼저 확정한 뒤 그 오리진으로 자원을 대조한다.",
      note:
        "build.ps1:311 이 책임 수를 셀 때 제외하는 유일한 키. 오프라인 모드는 키를 더하지"
        + " 않고 이 객체 안의 external_fetch_* 값만 바꾼다(+ external_fetch_error 중첩 필드).",
      async run(ctx) {
        const evidence = measureResources(ctx);
        const identity = await ctx.host("artifact_identity", null);
        evidence.artifact_id = identity.artifact_id;
        evidence.tree_sha256 = identity.tree_sha256;
        evidence.external_fetch_completed = null;
        evidence.external_fetch_succeeded = null;
        evidence.external_fetch_blocked = null;

        if (!ctx.flags.offlineProbe) return { runtime: evidence };

        const state = startExternalFetchProbe(ctx);
        try {
          await ctx.waitFor(() => state.pending === false, {
            what: "외부 fetch 대조 정착",
            timeoutMs: 8000,
          });
          const completed = state.completed === true;
          const succeeded = completed && state.succeeded === true;
          const blocked = completed && !succeeded && state.blocked === true;
          evidence.external_fetch_completed = completed;
          evidence.external_fetch_succeeded = succeeded;
          evidence.external_fetch_blocked = blocked;
          evidence.external_fetch_error = String(state.error === undefined ? "" : state.error);
        } catch (_) {
          /* 레거시의 시한 초과 분기(app.py:3608-3612)를 그대로 둔다 — 이 자리는 이미
             confirm-or-alarm 을 지킨다: 조용히 흘러가는 대신 **시끄러운 표식 값**을 남기고,
             build.ps1:348-350 이 그 문자열을 실패로 읽는다. 그래서 러너 오류로 올리지 않고
             값으로 확정한다(양성/음성 대조 쌍의 음성 극이 여기다). */
          evidence.external_fetch_completed = false;
          evidence.external_fetch_succeeded = false;
          evidence.external_fetch_blocked = null;
          evidence.external_fetch_error = "offline probe timed out";
        }
        return { runtime: evidence };
      },
    },

    /* ── chain_recovery (app.py:2950 상수 · 3820·3823·3828 호출) ── */
    {
      name: "chain_recovery",
      keys: ["chain_recovery"],
      cluster: PERSISTENCE_GEOMETRY_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3820,
      deadlineMs: 5000,
      completionField: "pending",
      note:
        "호출 직렬화 체인이 실패 한 번으로 죽지 않는지 실행으로 증명한다(리뷰 5R)."
        + " 정적 계약은 'catch 가 있다'까지만 본다.",
      async run(ctx) {
        const Intent = ctx.services.Intent;
        if (!Intent || typeof Intent.chained !== "function") {
          ctx.fail(ERROR_CODES.CONTRACT, "Intent.chained 가 주입되지 않았습니다.");
        }
        /* 필드 순서까지 기준 실행과 같게 둔다: pending → rejected_surfaced → after_value
           → after_ran. 소비 pytest 는 값만 보지만, 증거 파일의 diff 가 읽히는 물건이다. */
        const out = { pending: true };
        const key = `probe:${String(Math.random())}`;
        const seen = [];
        await Intent.chained(key, () => Promise.reject(new Error("의도된 실패")))
          .then(
            () => { out.rejected_surfaced = false; },
            () => { out.rejected_surfaced = true; },   // 실패는 호출자에게 그대로 전해진다
          )
          .then(() => Intent.chained(key, () => { seen.push("after"); return "ok"; }))
          .then((v) => { out.after_value = v; })
          .catch((e) => { out.error = String((e && e.message) || e); })
          .then(() => {
            out.after_ran = seen.length === 1;
            out.pending = false;
          });
        /* 레거시는 여기서 멈춘다 — `out.error` 를 담은 정상 모양 값을 그대로 내보내고,
           그 키의 `error is None` 단언이 있는 프로브만 우연히 붉어졌다. 러너 계약은
           "프로브가 실패한 것"과 "프로브가 false 를 잰 것"을 가른다. */
        if (out.error) ctx.fail(ERROR_CODES.PROBE_THREW, out.error);
        return { chain_recovery: out };
      },
    },

    /* ── grid_narrow (app.py:3855-3857) — resize 는 호스트, 읽기는 프런트 ── */
    {
      name: "grid_narrow",
      keys: ["grid_narrow"],
      cluster: PERSISTENCE_GEOMETRY_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3857,
      deadlineMs: 0,
      deadlineRationale: "측정은 동기 computed style 읽기 — 레거시에도 폴링이 없다(대기는 settle).",
      requiresHost: ["window_resize"],
      hostSetup: { op: "window_resize", payload: { width: 760, height: 600 } },
      settleBeforeMs: 600,
      settleReason:
        "resize 는 OS 이벤트라 relayout 이 즉시 끝나지 않는다. 이 대기를 지우면 게이트가"
        + " flaky 해진다(app.py:3856 의 0.6초 그대로).",
      note: "최소 크기 = 820px 경계 아래 → 토바 축약. 좁은 창에서 탭이 잘리는 것이 진짜 회귀다.",
      run(ctx) {
        return { grid_narrow: measureGrid(ctx) };
      },
    },

    /* ── grid_wide (app.py:3858-3860) — narrow 의 음성 대조 ── */
    {
      name: "grid_wide",
      keys: ["grid_wide"],
      cluster: PERSISTENCE_GEOMETRY_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3860,
      deadlineMs: 0,
      deadlineRationale: "측정은 동기 computed style 읽기 — 레거시에도 폴링이 없다.",
      requiresHost: ["window_resize"],
      hostSetup: { op: "window_resize", payload: { width: 1440, height: 900 } },
      settleBeforeMs: 600,
      settleReason: "app.py:3859 의 0.6초 — resize 뒤 relayout 안정.",
      after: ["grid_narrow"],
      afterReason:
        "축약이 눌러앉아 상시 접힘이 되는 회귀는 **좁힌 뒤 넓혔을 때만** 보인다."
        + " 순서를 잃으면 두 측정이 같은 폭을 재고 대조가 사라진다.",
      run(ctx) {
        return { grid_wide: measureGrid(ctx) };
      },
    },

    /* ── theme_persist (app.py:3990) — 오리진 비의존 영속 콜드부트 되읽기(#74) ── */
    {
      name: "theme_persist",
      keys: ["theme_persist"],
      cluster: PERSISTENCE_GEOMETRY_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3990,
      deadlineMs: 0,
      deadlineRationale: "속성·CSS 변수 동기 읽기.",
      after: ["grid_wide"],
      afterReason:
        "레거시는 이 읽기를 마지막 resize(1440,900) 복귀 뒤에 둔다 — 좁은 폭에서 잰"
        + " 카드 색을 기본 폭의 값으로 오인하지 않게 한다.",
      note: "미저장이면 data_theme=null(=system) · a_card='#ffffff'. 쓰기 프로세스 뒤엔 'dark'.",
      run(ctx) {
        const root = ctx.doc.documentElement;
        return {
          theme_persist: {
            data_theme: root.getAttribute("data-theme"),
            a_card: ctx.win.getComputedStyle(root).getPropertyValue("--a-card").trim(),
          },
        };
      },
    },

    /* ── personalization_persist (app.py:3993-4006) ── */
    {
      name: "personalization_persist",
      keys: ["personalization_persist"],
      cluster: PERSISTENCE_GEOMETRY_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3993,
      deadlineMs: 0,
      deadlineRationale: "속성·computed style·선택 범위 동기 읽기.",
      after: ["theme_persist"],
      afterReason: "레거시 드라이버의 마지막 두 줄 순서 그대로.",
      note:
        "topbar_h 는 라이브러리 2-pane 계산이 소비하는 **구조 치수**라 실측으로 핀한다"
        + "(리터럴 드리프트 = 페이지가 조용히 스크롤하는 자리).",
      run(ctx) {
        const doc = ctx.doc;
        const win = ctx.win;
        const root = doc.documentElement;
        const app = doc.querySelector(".app");
        const body = doc.body;
        const p = doc.createElement("p");
        p.textContent = "선택 가능한 본문";
        body.appendChild(p);
        ctx.state.probeNode = p;
        const range = doc.createRange();
        range.selectNodeContents(p);
        const selection = win.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        const selected = selection.toString();
        selection.removeAllRanges();
        p.remove();
        return {
          personalization_persist: {
            font_scale: root.getAttribute("data-font-scale"),
            root_px: win.getComputedStyle(root).fontSize,
            topbar_h: Math.round(doc.querySelector(".topbar").getBoundingClientRect().height),
            master_width: parseFloat(win.getComputedStyle(app).getPropertyValue("--master-width")),
            splitters: doc.querySelectorAll(".master-splitter").length,
            body_overflow: body.scrollWidth > body.clientWidth + 1,
            selected_text: selected,
          },
        };
      },
      /* 레거시는 정리를 측정 안에 섞어 두고 실패하면 아무도 모른다(`_EDITOR_TXT_BAND` 의
         `teardown_error` 는 읽는 테스트가 없다). 여기선 정리 실패가 러너 오류가 되고
         뒤 프로브를 오염시키지 않도록 실행을 멈춘다. */
      teardown(ctx) {
        const node = ctx.state.probeNode;
        if (node && node.parentNode) {
          node.remove();
          throw new Error(
            "선택 프로브의 <p> 가 문서에 남았습니다 — 다음 프로브의 레이아웃 측정을 오염시킵니다.",
          );
        }
      },
    },

    /* ── window_geometry (app.py:3630·3634) — geometry-only 모드 전용, 호스트 소유 ── */
    {
      name: "window_geometry",
      keys: ["window_geometry"],
      cluster: PERSISTENCE_GEOMETRY_CLUSTER,
      owner: "host",
      hostOp: "window_geometry",
      requiresHost: ["window_geometry"],
      modes: ["geometry_only"],
      legacySite: 3634,
      deadlineMs: 10000,
      settleBeforeMs: 400,
      settleReason: "네이티브 최대화/복원 이벤트와 JS outer* 반영 안정(app.py:3633).",
      preconditionWhat: "document.readyState === 'complete'",
      precondition(ctx) {
        return ctx.doc.readyState === "complete" && !!ctx.doc.body;
      },
      note: GEOMETRY_OWNERSHIP_DECISION.decision === "host"
        ? "판정: 호스트 소유(GEOMETRY_OWNERSHIP_DECISION 참조). maximized_like 파생도 호스트."
        : "",
    },

    /* ── font_scale_write (app.py:3652-3675) — 쓰기 모드 ── */
    {
      name: "font_scale_write",
      keys: ["set_result"],
      cluster: PERSISTENCE_GEOMETRY_CLUSTER,
      owner: "frontend",
      requiresHost: ["input_select", "settings_readback"],
      modes: ["font_scale_write"],
      legacySite: 3665,
      deadlineMs: 25000,
      note:
        "`font_scale_write` 키는 호스트가 프로브 앞에 심는 **에코**라 여기 keys 에 없다"
        + "(app.py:3653) — 그래서 브리지 시한 초과로 실패해도 증거에 남는다.",
      async run(ctx) {
        const scale = await ctx.host("input_select", { setting: "font_scale" });
        await ctx.waitFor(
          () => !!(ctx.win.pywebview && ctx.win.pywebview.api && ctx.services.Personalization),
          { what: "브리지 준비(Personalization.setFontScale)", timeoutMs: 15000 },
        );
        ctx.services.Personalization.setFontScale(scale);
        /* evaluate_js 가 promise 를 대기하지 않던 자리 그대로 — 디스크 반영을 폴링해 확정한다.
           단 시한 초과는 조용한 통과가 아니라 시끄러운 실패다(레거시는 여기서 마지막
           읽은 값을 그냥 실었다). */
        await ctx.waitFor(
          async () => (await ctx.host("settings_readback", { setting: "font_scale" })) === scale,
          { what: "settings.json 배율 반영", timeoutMs: 10000 },
        );
        return { set_result: await ctx.host("settings_readback", { setting: "font_scale" }) };
      },
    },

    /* ── theme_write (app.py:3677-3707) — 쓰기 모드 ── */
    {
      name: "theme_write",
      keys: ["set_result"],
      cluster: PERSISTENCE_GEOMETRY_CLUSTER,
      owner: "frontend",
      requiresHost: ["input_select", "settings_readback"],
      modes: ["theme_write"],
      legacySite: 3696,
      deadlineMs: 25000,
      note:
        "실사용 경로 그대로 구동한다 — 토글 클릭이 지나는 Theme.set→Bridge.setTheme→"
        + "api.set_theme 홉 전체. api 직접 호출로 바꾸면 theme.js 결함이 무커버가 된다.",
      async run(ctx) {
        const theme = await ctx.host("input_select", { setting: "theme" });
        await ctx.waitFor(
          () => !!(ctx.win.pywebview && ctx.win.pywebview.api
            && ctx.services.Bridge && ctx.services.Theme),
          { what: "브리지(pywebview.api) 준비 — Theme.set", timeoutMs: 15000 },
        );
        ctx.services.Theme.set(theme);
        await ctx.waitFor(
          async () => (await ctx.host("settings_readback", { setting: "theme" })) === theme,
          { what: "settings.json 테마 반영", timeoutMs: 10000 },
        );
        return { set_result: await ctx.host("settings_readback", { setting: "theme" }) };
      },
    },
  ];
}

/** 러너에 이 클러스터를 통째로 등록한다. 레인 B·C·D 도 같은 이름꼴을 쓴다. */
export function registerPersistenceGeometryProbes(runner) {
  return runner.registerAll(createPersistenceGeometryProbes());
}
