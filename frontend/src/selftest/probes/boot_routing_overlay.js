/* N-08 클러스터 B — 부팅·라우팅·오버레이·보존 프로브.
 *
 * 무엇을 옮겼나: `src/hwpxfiller/webapp/app.py` 의 상수 일곱과 그것을 부르는 호출 자리 열아홉.
 *   · `_MODAL_A11Y_PROBE_JS`(629)                  → modal_a11y · modal_confirm_serial (3833·3837)
 *   · `_PRESERVE_PROBE_JS`(856)                    → preserve                          (3867)
 *   · `_PRESERVE_REAL_SETUP_JS`(887)               → preserve_real 의 setup            (3869)
 *   · `_PRESERVE_REAL_PROBE_JS`(897)               → preserve_real 의 run              (3871)
 *   · `_ACTION_ROUNDTRIP_PROBE_SETUP_JS`(2973)     → action_roundtrip                  (3743·3746·3751)
 *   · `_MILESTONE_H_WAVE1_PROBE_JS`(3014)          → milestone_h_wave1                 (3969)
 *   · `_MILESTONE_H_OVERLAY_PROBE_SETUP_JS`(3116)  → milestone_h_overlay               (3976·3978)
 * 그리고 드라이버가 인라인 문자열로 들고 있던 한 줄짜리 되읽기 여덟 —
 * 3716(title_dom) · 3717(nav_count) · 3718(tpl_options) · 3721(job_on) · 3725(home_screen_gone) ·
 * 3728(library_surface) · 3733(library_view_tabs) · 3738(data_picker_buttons).
 *
 * 공용 폴링 하니스 `_probe_late`(3494~3506, 호출 자리 3503·3506)는 **이식하지 않는다** —
 * 러너의 `ctx.waitFor` 와 감시견이 그 자리를 이미 승계했고(그것도 만료에 `else` 가 있는 판으로),
 * 같은 기제를 두 벌 두면 다음 레인이 어느 쪽을 고칠지 갈린다.
 *
 * 무엇을 **안** 바꿨나: 프로브가 하는 일·순서·필드 이름과 **필드 순서**·타이밍 의도. 소비
 * pytest(`tests/test_web_selftest_gate.py`)가 값 모양을 그대로 단언하기 때문이다.
 *
 * 무엇을 바꿨나 — 둘뿐이다.
 *  ① **상태 인계**. 창 객체 위의 `__cf1`/`__cf2`(모달 프로브가 `.then` 으로 쌓고 한 턴 뒤
 *     app.py:3837 이 읽던 것)와 `__snaps`(preserve_real 의 setup→probe 인계), `__actionRoundtrip`,
 *     `__milestoneHOverlay` 스태시가 전부 사라지고 **러너가 `ctx.state` 로 든다**. 전역 쓰기
 *     금지가 첫 이유고, 두 번째가 더 무겁다 — 번들러가 이름을 바꾸면 문자열 보간으로 만든
 *     전역 조회가 조용히 빗나간다(선언은 살고 결과는 죽는 결함류).
 *  ② **넓은 catch 의 폐기**. `_MILESTONE_H_OVERLAY_PROBE_SETUP_JS` 의 바깥 try/catch 는
 *     실패를 `out.error` 라는 **정상 모양 값**으로 바꿔 돌려줬다. 러너의 오류는 구조체이고
 *     실패한 프로브의 키는 결과에 실리지 않으므로, 여기서는 던지게 둔다. 화면별 측정값인
 *     `preserve_real` 의 `'throw:…'`/`'no-snap'` 은 **catch 가 아니라 측정 결과**라 그대로 둔다.
 *
 * 보존한 양성/음성 대조(하나도 잃지 않는다):
 *   · modal_a11y : Escape 닫힘 ↔ 포커스 복귀(before==restored) / confirm display none→flex→none /
 *                  danger 적용 ↔ `danger_resets_to_neutral` / 비-모달 open **과** close 양쪽 거절 /
 *                  불량 confirm root 거절 ↔ 그 뒤 정상 confirm 개방(교착 부재) /
 *                  `choose_all_visible` 는 존재가 아니라 **가시성**을 잰다.
 *   · modal_confirm_serial : first=true(확인 클릭) ↔ second=false(재진입 즉시 거절).
 *   · home_screen_gone ↔ library_surface : 죽은 표면 ↔ 승계 표면. 한 부팅에서 같이 읽어야
 *                  "둘 다 있는" 반쪽 이주가 승계 쪽 단언만으로 초록이 되지 않는다.
 *   · action_roundtrip : `pending is False` + 네 화면군 각각 screen/action/snapshot_keys 와
 *                  `"error" not in got`.
 *   · milestone_h_wave1 : disabled ↔ enabled primary, card_base ↔ selected_card.
 *   · milestone_h_overlay : drag 로 닫힘 ↔ 그 뒤 click 이 살아 있음(click_after_drag),
 *                  우클릭 뒤 click 생존, IME Escape 는 열어 두고 ↔ 맨 Escape 는 닫는다.
 *
 * 알려진 감도 공백(가리지 않고 적는다): 이 클러스터의 `.click()` 자리 가운데 가시성을
 * 단언하는 것은 `choose_all_visible`(app.py:763) **하나뿐**이다. `display:none` 요소를 눌러도
 * 프로브는 "성공"한다 — 이 저장소가 이미 기록한 교훈이다. 없던 단언을 여기서 지어내면
 * 감도가 조용히 달라지므로 원문대로 옮기고, 자리마다 주석으로 표시해 둔다.
 *
 * 이 모듈은 **비활성(inert)** 이다. 제품 그래프 어디에서도 import 하지 않고, 전역을 쓰지 않고,
 * import 만으로는 DOM 을 만지지도 리스너를 걸지도 않는다 — 전부 호출 시점에 일어난다.
 */

import { ERROR_CODES } from "../runner.js";

export const B_CLUSTER = "B";

/** 이 클러스터가 내는 키 전수. 순서는 **레거시 드라이버의 실행 순서**다(알파벳이 아니다) —
 *  스키마의 `keysForCluster("B")` 와는 정렬 뒤 같아야 하고, 그 동일성은 테스트가 센다. */
export const B_KEYS = Object.freeze([
  "title_dom", "nav_count", "tpl_options", "job_on",
  "home_screen_gone", "library_surface", "library_view_tabs", "data_picker_buttons",
  "action_roundtrip", "modal_a11y", "modal_confirm_serial",
  "preserve", "preserve_real", "milestone_h_wave1", "milestone_h_overlay",
]);

/* ────────────────────────── 인라인 조각 ────────────────────────── */

/** 라이브러리 표면 실재(app.py:3729-3731) — 축 4종과 2-pane 골격의 id 전수. */
const LIBRARY_SURFACE_IDS = Object.freeze([
  "scr-library", "libraryViewTabs", "libraryModeFilters", "libraryFacets",
  "librarySearch", "libraryList", "libraryDetail", "libraryCount",
]);

/** 데이터 선택 단일 출구(app.py:3739). 구 2버튼·pool 화면 사망의 승계 지점. */
const DATA_PICKER_BUTTON_IDS = Object.freeze(["jobBtnPickData"]);

/** 액션 왕복 네 군(app.py:2978-2982) — `[family, screen, action]`. 순서까지 원문 그대로. */
const ACTION_ROUNDTRIP_SPECS = Object.freeze([
  Object.freeze(["editor", "editor", "new_session"]),
  Object.freeze(["job", "job", "refresh"]),
  Object.freeze(["pool", "pool", "refresh"]),
  Object.freeze(["template", "tpl", "refresh"]),
]);

/** `querySelectorAll` 결과를 배열로. NodeList 든 배열이든 같은 몸통을 쓴다. */
function all(doc, selector) {
  return Array.prototype.slice.call(doc.querySelectorAll(selector));
}

/** app.py 의 `finishModal` — 카드에 `transitionend(opacity)` 를 손으로 흘려 퇴장을 완료시킨다. */
function finishModal(ctx, id) {
  const card = ctx.doc.querySelector("#" + id + " .modal-card");
  if (!card) return;
  const ev = new ctx.win.Event("transitionend", { bubbles: true });
  Object.defineProperty(ev, "propertyName", { value: "opacity" });
  card.dispatchEvent(ev);
}

/** 문서로 키다운 하나. `defineProperty` 로 붙이는 필드(예: `isComposing`)까지 원문과 같게. */
function keydown(ctx, key, defined) {
  const ev = new ctx.win.KeyboardEvent("keydown", { key, bubbles: true });
  if (defined) {
    for (const name of Object.keys(defined)) {
      Object.defineProperty(ev, name, { value: defined[name] });
    }
  }
  ctx.doc.dispatchEvent(ev);
  return ev;
}

/** app.py:3016-3024 의 `styleOf` — 필드 순서까지 같다. */
function styleOf(ctx, el) {
  if (!el) return null;
  const s = ctx.win.getComputedStyle(el);
  return {
    font_size: s.fontSize, font_weight: s.fontWeight,
    background: s.backgroundColor, color: s.color,
    border_left: s.borderLeftColor, opacity: s.opacity,
  };
}

/** 주입 확인 — 없는 서비스를 조용히 지나치지 않는다(레거시는 전역이라 `undefined.open` 으로
 *  터졌고 그 예외가 드라이버 전체를 죽였다. 여기선 어느 프로브가 무엇을 못 받았는지 남는다). */
function requireService(ctx, name, methods) {
  const service = ctx.services[name];
  const missing = (methods || []).filter((m) => !service || typeof service[m] !== "function");
  if (!service || missing.length > 0) {
    ctx.fail(
      ERROR_CODES.CONTRACT,
      `${name} 이 주입되지 않았거나 ${missing.join("·")} 를 대지 않습니다 —`
      + " 프로브는 전역에서 서비스를 줍지 않습니다.",
    );
  }
  return service;
}

/** 마이크로태스크 경계. 레거시는 `evaluate_js` 스택이 풀리며 큐가 flush 되고 파이썬이 **다음
 *  호출**(app.py:3837)로 값을 읽었다 — 여기서는 그 "한 턴 뒤"를 명시 await 로 만든다.
 *  고정 sleep 이 아니라 마이크로태스크만 흘리므로 시간 예산은 늘지 않는다. */
async function flushMicrotasks(turns) {
  for (let i = 0; i < turns; i += 1) await Promise.resolve();
}

/* ────────────────────────── 프로브 정의 ────────────────────────── */

/** 클러스터 B 의 프로브 전수를 **정의 데이터**로 낸다. 부작용 없음 — 이 함수를 부르는 것만으로는
 *  DOM 을 만지지도, 리스너를 걸지도, 전역을 쓰지도 않는다. */
export function createBootRoutingOverlayProbes() {
  return [
    /* ── title_dom (app.py:3716) — 문서 부팅·셸 로드의 최소 증거 ── */
    {
      name: "title_dom",
      keys: ["title_dom"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3716,
      deadlineMs: 0,
      deadlineRationale: "문서 제목(`title`) 동기 읽기 — 레거시에도 폴링이 없다.",
      note: "비어 있지 않음만 본다(gate:93). 셸이 안 뜨면 여기서 먼저 붉어진다.",
      run(ctx) {
        return { title_dom: ctx.doc.title };
      },
    },

    /* ── nav_count (app.py:3717) — 화면 소실 회귀 가드 ── */
    {
      name: "nav_count",
      keys: ["nav_count"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3717,
      deadlineMs: 0,
      deadlineRationale: "`querySelectorAll('.navbtn').length` 동기 읽기.",
      note: "기대 수는 프로브가 아니라 소비 테스트의 NAV_SCREENS 가 소유한다(gate:96-98).",
      run(ctx) {
        return { nav_count: ctx.doc.querySelectorAll(".navbtn").length };
      },
    },

    /* ── tpl_options (app.py:3718) — **소비자 0건의 죽은 키** ── */
    {
      name: "tpl_options",
      keys: ["tpl_options"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3718,
      deadlineMs: 0,
      deadlineRationale: "option 값 map — 동기 읽기.",
      note:
        "감도 공백을 **아는 채로** 옮긴다: `#tplSel` 은 편집기 안으로 옮겨 사망했고 기준 실행의"
        + " 값은 `[]` 다. 소비 테스트가 0건이라 이 값이 무엇이 되든 지금은 아무 게이트도"
        + " 붉어지지 않는다(schema 의 unconsumedReason). 조용히 지우지도, 없던 단언을"
        + " 지어내지도 않는다 — 그 판정은 N-09 이후의 별건이다.",
      run(ctx) {
        return {
          tpl_options: all(ctx.doc, "#tplSel option").map((o) => o.value),
        };
      },
    },

    /* ── job_on (app.py:3721) — H-05 콜드 부팅 착지 ── */
    {
      name: "job_on",
      keys: ["job_on"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3721,
      deadlineMs: 0,
      deadlineRationale: "classList 동기 읽기.",
      note: "build.ps1:317-327 이 최상위 boolean false 를 금지하는 네 키 가운데 하나.",
      run(ctx) {
        return {
          job_on: ctx.doc.getElementById("scr-job").classList.contains("on"),
        };
      },
    },

    /* ── home_screen_gone (app.py:3725) — 죽은 표면. library_surface 와 한 쌍이다. ── */
    {
      name: "home_screen_gone",
      keys: ["home_screen_gone"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3725,
      deadlineMs: 0,
      deadlineRationale: "getElementById 부재 확인 — 동기 읽기.",
      note:
        "죽은 DOM 이 남아 있으면 다음 세션의 부활 경로가 된다(재작성 F2)."
        + " 승계 쪽(library_surface)만 초록인 반쪽 이주를 이 음성 극이 잡는다.",
      run(ctx) {
        const doc = ctx.doc;
        return {
          home_screen_gone: !doc.getElementById("scr-home") && !doc.getElementById("homeBrowser"),
        };
      },
    },

    /* ── library_surface (app.py:3728) — 승계 표면 ── */
    {
      name: "library_surface",
      keys: ["library_surface"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3728,
      deadlineMs: 0,
      deadlineRationale: "id 전수 존재 확인 — 동기 읽기.",
      after: ["home_screen_gone"],
      afterReason:
        "죽은 표면 ↔ 승계 표면은 **한 쌍**이다. 승계 쪽을 먼저 읽고 만족해 버리면 둘 다 서"
        + " 있는 반쪽 이주가 초록으로 지나간다 — 사망 확인을 앞에 세워 순서로 못 박는다.",
      run(ctx) {
        const doc = ctx.doc;
        return {
          library_surface: LIBRARY_SURFACE_IDS.every((id) => !!doc.getElementById(id)),
        };
      },
    },

    /* ── library_view_tabs (app.py:3733) — 보기 탭 4종(§19.6 표) ── */
    {
      name: "library_view_tabs",
      keys: ["library_view_tabs"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3733,
      deadlineMs: 0,
      deadlineRationale: "dataset map — 동기 읽기.",
      after: ["library_surface"],
      afterReason:
        "탭 목록은 표면이 실재할 때만 의미가 있다. 순서를 잃으면 `[]` 가 '탭이 없다'인지"
        + " '라이브러리가 없다'인지 구별되지 않는다.",
      run(ctx) {
        return {
          library_view_tabs: all(ctx.doc, "#libraryViewTabs [data-library-view]")
            .map((b) => b.dataset.libraryView),
        };
      },
    },

    /* ── data_picker_buttons (app.py:3738) — 데이터 선택 단일 출구 ── */
    {
      name: "data_picker_buttons",
      keys: ["data_picker_buttons"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3738,
      deadlineMs: 0,
      deadlineRationale: "id 존재 확인 — 동기 읽기.",
      note: "build.ps1 의 boolean-false 금지 네 키 가운데 하나. 「기안」 몫은 화면과 함께 사망.",
      run(ctx) {
        const doc = ctx.doc;
        return {
          data_picker_buttons: DATA_PICKER_BUTTON_IDS.every((id) => !!doc.getElementById(id)),
        };
      },
    },

    /* ── action_roundtrip (app.py:2973 상수 · 3743·3746·3751 호출) ──
       실 click → JS bridge → Python registry dispatch → snapshot 을 **한 부팅 안에서** 왕복한다. */
    {
      name: "action_roundtrip",
      keys: ["action_roundtrip"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3743,
      deadlineMs: 10000,
      completionField: "pending",
      note:
        "레거시는 `!pending` 을 10초 폴링했지만 만료에 `else` 가 없어, 시한이 지나도 **모양은"
        + " 맞고 pending 인** 객체를 그대로 실었다. 여기선 시한 초과가 러너 오류가 되고"
        + " `completionField` 가 미완주 값의 반출을 한 번 더 막는다."
        + " 가시성 공백: 숨김 호스트(`host.hidden = true`) 안 버튼을 누른다 —"
        + " 원문에도 가시성 단언이 없어 그대로 옮겼다.",
      async run(ctx) {
        const doc = ctx.doc;
        const Bridge = requireService(ctx, "Bridge", ["call", "initial"]);
        const out = { pending: true, families: {} };
        ctx.state.out = out;
        const host = doc.createElement("div");
        host.hidden = true;
        host.id = "selftestActionClicks";
        doc.body.appendChild(host);
        ctx.state.host = host;

        const clicks = ACTION_ROUNDTRIP_SPECS.map(([family, screen, action]) => new Promise(
          (resolve) => {
            const button = doc.createElement("button");
            button.type = "button";
            button.dataset.family = family;
            button.addEventListener("click", async () => {
              try {
                await Bridge.call(screen, action, {});
                const snapshot = await Bridge.initial(screen);
                out.families[family] = {
                  screen,
                  action,
                  snapshot: !!snapshot && typeof snapshot === "object",
                  snapshot_keys: snapshot && typeof snapshot === "object"
                    ? Object.keys(snapshot)
                    : [],
                };
              } catch (e) {
                out.families[family] = { screen, action, error: String((e && e.message) || e) };
              }
              resolve();
            }, { once: true });
            host.appendChild(button);
            /* 가시성 미단언 자리 ①: 숨김 호스트 안의 버튼을 누른다(app.py:3006). */
            button.click();
          },
        ));
        Promise.all(clicks).then(() => { out.pending = false; host.remove(); });

        await ctx.waitFor(() => out.pending === false, {
          what: "네 화면군 왕복 완주(action_roundtrip.pending)",
          timeoutMs: 10000,
        });
        return { action_roundtrip: out };
      },
      /* 레거시는 호스트 제거를 `.then` 안에 섞어 두고 실패하면 아무도 모른다. 남으면 뒤
         프로브의 레이아웃·포커스 측정을 오염시키므로 정리 실패를 러너 오류로 올린다. */
      teardown(ctx) {
        const host = ctx.state.host;
        if (host && host.parentNode) {
          host.remove();
          throw new Error(
            "action_roundtrip 의 숨김 클릭 호스트가 문서에 남았습니다 —"
            + " 다음 프로브의 측정을 오염시킵니다.",
          );
        }
      },
    },

    /* ── modal_a11y + modal_confirm_serial (app.py:629 상수 · 3833·3837 호출) ──
       두 키를 **한 프로브**가 낸다. 레거시는 동기 IIFE 가 `__cf1`/`__cf2` 를 창 객체에 쌓고
       파이썬이 한 턴 뒤 별도 호출로 읽었다 — 그 인계가 `ctx.state` 로 들어오면서 두 자리를
       가를 이유가 사라졌다(러너의 `state` 는 프로브 하나의 수명을 산다). */
    {
      name: "modal_a11y",
      keys: ["modal_a11y", "modal_confirm_serial"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3833,
      deadlineMs: 5000,
      deadlineRationale:
        "레거시는 동기 IIFE 한 번 + 되읽기 한 번이라 0 이었다. R3-01(#410) 뒤 confirm·"
        + "choose·prompt 골격은 정적 index.html 이 아니라 React host **커밋 산물**이라,"
        + " 마운트 완료를 전제조건으로 시한 안에 기다린다(react_runtime 과 같은 경합 창"
        + " 닫기 — 실측상 프로브 도달 전에 이미 참이다). 본문 측정은 여전히 마이크로태스크뿐이다.",
      precondition: (ctx) => ctx.doc.getElementById("confirmModal") !== null
        && ctx.doc.getElementById("chooseModal") !== null,
      preconditionWhat: "React overlay host 골격(confirm·choose) 커밋",
      note:
        "가시성 공백: `.click()` 다섯 자리 가운데 가시성을 단언하는 것은 `choose_all_visible`"
        + "(app.py:763) 뿐이다. `display:none` 버튼을 눌러도 이 프로브는 성공한다 —"
        + " 원문 그대로 옮기고 자리마다 표시했다.",
      async run(ctx) {
        const doc = ctx.doc;
        const win = ctx.win;
        const Modal = requireService(ctx, "Modal", ["open", "close", "confirm", "choose"]);

        /* (1) 커스텀 모달 개폐·초기 포커스·Escape·트리거 복귀. */
        const trigger = doc.querySelector(".navbtn");
        trigger.focus();
        const before = doc.activeElement.getAttribute("data-scr");
        /* 표적 모달 재겨눔(R4-02): `txtEditModal` 은 **폼 모달이 아니게 됐다** — 내용의
           생산자가 편집기 React 표면이라 그 창을 열어 두는 것만으로는 안에 아무 요소도
           없다(초기 포커스가 겨눌 자리 자체가 없다). 이 프로브의 주어는 「커스텀 모달의
           개폐·초기 포커스·Escape·복귀」이지 편집기가 아니므로, 골격이 **항상 서 있는**
           promise 다이얼로그(#promptModal — R3-01 이 React host 렌더로 옮긴 뒤 상주)로
           옮긴다. 앞선 재겨눔(draftSaveTplModal 사망 → txtEditModal, F6 PR-B)과 같은 처분. */
        Modal.open("promptModal", { initialFocus: doc.getElementById("promptModalInput") });
        const opened = !doc.getElementById("promptModal").classList.contains("hidden");
        const focusIn = doc.activeElement.id;
        keydown(ctx, "Escape");
        const escapeClosing = doc.getElementById("promptModal").classList.contains("is-closing");
        finishModal(ctx, "promptModal");
        const closed = doc.getElementById("promptModal").classList.contains("hidden");
        const restored = doc.activeElement.getAttribute("data-scr");

        /* (2) 네이티브 confirm 대체 모달 — `.modal{display:flex}` 가 `.hidden` 을 덮지 않는가
           (부록 B-9 결함 클래스)를 **계산 스타일 세 점**(none→flex→none)으로 본다. */
        const cm = doc.getElementById("confirmModal");
        const cDisplayClosedBefore = win.getComputedStyle(cm).display;
        const alerts = [];
        /* 재진입 거절의 loud alert 는 실행을 막는 네이티브 다이얼로그라 **기록으로 대체**한다.
           주입된 창 표면의 한시 교체이고 아래에서 반드시 원복한다(전역 별칭 생산이 아니다). */
        const origAlert = win.alert;
        win.alert = (m) => { alerts.push(String(m)); };
        /* 상태 인계: 창 객체 스태시가 아니라 프로브가 든다. */
        const serial = { first: "pending", second: "pending" };
        ctx.state.confirmSerial = serial;
        Modal.confirm({ body: "첫 확인 본문" }).then((v) => { serial.first = v; });
        const cOpened = !cm.classList.contains("hidden");
        const cDisplayOpen = win.getComputedStyle(cm).display;
        const cFocus = doc.activeElement.id;
        /* 재진입 — 즉시 거절되고 loud 여야 하며 첫 다이얼로그의 본문·리스너가 덮이면 안 된다. */
        Modal.confirm({ body: "둘째 확인 본문" }).then((v) => { serial.second = v; });
        const reentryAlerts = alerts.length;
        const bodyAfterReentry = doc.getElementById("confirmModalBody").textContent;
        /* Tab 트랩 — 마지막 포커서블에서 Tab 이 배경으로 새지 않고 첫 요소로 순환. */
        doc.getElementById("confirmModalOk").focus();
        keydown(ctx, "Tab");
        const trapWrapped = doc.activeElement.id;
        /* 가시성 미단언 자리 ②(app.py:671). */
        doc.getElementById("confirmModalOk").click();
        const confirmClosing = cm.classList.contains("is-closing");
        finishModal(ctx, "confirmModal");
        const cClosed = cm.classList.contains("hidden");
        const cDisplayClosed = win.getComputedStyle(cm).display;

        /* (3) danger 변형 ↔ 중립 복귀 — 같은 안정 버튼이 양방향으로 클래스·계산색을 바꾸는가. */
        Modal.confirm({ body: "영구 삭제", confirmLabel: "삭제", danger: true });
        const dangerOk = doc.getElementById("confirmModalOk");
        const dangerClass = dangerOk.classList.contains("danger")
          && !dangerOk.classList.contains("primary");
        const dangerBg = win.getComputedStyle(dangerOk).backgroundColor;
        /* 가시성 미단언 자리 ③(app.py:681). */
        doc.getElementById("confirmModalCancel").click();
        finishModal(ctx, "confirmModal");
        Modal.confirm({ body: "중립 전환", confirmLabel: "계속" });
        const neutralReset = !dangerOk.classList.contains("danger")
          && dangerOk.classList.contains("primary");
        /* 가시성 미단언 자리 ④(app.py:685). */
        doc.getElementById("confirmModalCancel").click();
        finishModal(ctx, "confirmModal");
        win.alert = origAlert;

        /* (4) `.modal` 없는 대상의 open/close 를 **양쪽 다** loud 거절하는가(#132.4).
           음성 반쪽(close)을 잃으면 대칭 결함이 안 보인다. */
        const mErrs = [];
        const cons = win.console;
        const origErr = cons.error;
        const np = doc.createElement("div");
        np.id = "__nonModalProbe";
        np.className = "hidden";
        doc.body.appendChild(np);
        let openRejected = false;
        let closeRejected = false;
        cons.error = function () { mErrs.push(Array.prototype.join.call(arguments, " ")); };
        try {
          const e0 = mErrs.length;
          Modal.open("__nonModalProbe");
          /* loud 는 **가드 자신의 메시지**로 판정한다 — 무관한 미래 error 로 초록 위장 차단. */
          openRejected = mErrs.slice(e0).some((m) => m.indexOf("Modal.open") >= 0)
            && np.classList.contains("hidden");
          const e1 = mErrs.length;
          Modal.close("__nonModalProbe");
          closeRejected = mErrs.slice(e1).some((m) => m.indexOf("Modal.close") >= 0);
        } finally {
          cons.error = origErr;      // 어떤 throw 에도 원복 — 아니면 실앱 console.error 가 영구 삼켜진다
          doc.body.removeChild(np);
        }

        /* (5) 불량 confirm root — loud 거절 **과** 교착 부재(후속 정상 confirm 이 열린다). */
        const cmR = doc.getElementById("confirmModal");
        let malfLoud = false;
        let afterMalfOpens = false;
        const oErr2 = cons.error;
        const oAlert2 = win.alert;
        cons.error = () => { malfLoud = true; };
        win.alert = () => {};      // 불량 경로의 실 alert 블로킹 차단
        try {
          cmR.classList.remove("modal");
          Modal.confirm({ body: "불량 root" });
          cmR.classList.add("modal");
          Modal.confirm({ body: "후속 정상" });
          afterMalfOpens = !cmR.classList.contains("hidden");
        } finally {
          if (!cmR.classList.contains("modal")) cmR.classList.add("modal");
          cons.error = oErr2;
          win.alert = oAlert2;
        }
        if (afterMalfOpens) {
          /* 가시성 미단언 자리 ⑤(app.py:729). */
          doc.getElementById("confirmModalCancel").click();
          finishModal(ctx, "confirmModal");
        }

        /* (6) 3택 모달 — 배선만 하고 안 보이면 사용자는 나갈 길이 없다.
           이 자리만 `display !== 'none'` 으로 **가시성**을 단언한다. */
        const chooseSpec = {
          title: "처분 확인",
          body: "3택 프로브",
          choices: [
            { value: "save", label: "저장하고 이동" },
            { value: "discard", label: "버리고 이동" },
            { value: "stay", label: "머무르기" },
          ],
        };
        const chPromise = Modal.choose(chooseSpec);
        const chRoot = doc.getElementById("chooseModal");
        const chOpen = !chRoot.classList.contains("hidden");
        const chDisplay = win.getComputedStyle(chRoot).display;
        const chFocus = doc.activeElement ? doc.activeElement.id : "";
        const chIds = ["chooseModalOk", "chooseModalAlt", "chooseModalCancel"];
        const chLabels = chIds.map((id) => doc.getElementById(id).textContent).join("|");
        const chVisible = chIds.every(
          (id) => win.getComputedStyle(doc.getElementById(id)).display !== "none",
        );
        /* 가시성 미단언 자리 ⑥ — 다만 바로 위 `chVisible` 이 같은 세 버튼의 가시성을 이미 쟀다. */
        doc.getElementById("chooseModalAlt").click();
        finishModal(ctx, "chooseModal");
        /* 레거시는 이 값을 창 객체(`__chooseValue`)에 쌓았지만 읽는 소비자가 0건이다 —
           전역 대신 프로브 상태로 받아 둔다(모양은 남기고 스태시만 없앤다). */
        chPromise.then((v) => { ctx.state.chooseValue = v; });

        /* 레거시의 "한 턴 뒤"(app.py:3837) — 스크립트 스택이 풀리며 flush 되던 자리. */
        await flushMicrotasks(8);

        return {
          modal_a11y: {
            choose_opened: chOpen,
            choose_display: chDisplay,
            choose_focus: chFocus,
            choose_labels: chLabels,
            choose_all_visible: chVisible,
            opened,
            focus_in: focusIn,
            closed_by_escape: closed,
            focus_before: before,
            focus_restored: restored,
            escape_entered_closing: escapeClosing,
            confirm_display_closed_before: cDisplayClosedBefore,
            confirm_opened: cOpened,
            confirm_display_open: cDisplayOpen,
            confirm_focus: cFocus,
            confirm_reentry_alerts: reentryAlerts,
            confirm_body_after_reentry: bodyAfterReentry,
            confirm_trap_wrapped: trapWrapped,
            confirm_closed: cClosed,
            confirm_entered_closing: confirmClosing,
            confirm_display_closed: cDisplayClosed,
            danger_class: dangerClass,
            danger_background: dangerBg,
            danger_resets_to_neutral: neutralReset,
            non_modal_open_rejected_loud: openRejected,
            non_modal_close_rejected_loud: closeRejected,
            malformed_confirm_root_refused_loud: malfLoud,
            confirm_after_malformed_opens: afterMalfOpens,
          },
          modal_confirm_serial: { first: serial.first, second: serial.second },
        };
      },
    },

    /* ── preserve (app.py:856 상수 · 3867 호출) — 기제(합성 픽스처) ── */
    {
      name: "preserve",
      keys: ["preserve"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3867,
      deadlineMs: 0,
      deadlineRationale: "동기 IIFE 하나 — 레거시에도 폴링이 없다.",
      note:
        "화면 네비·데이터 의존 없이 결정적으로 기제만 본다: 포커스(preserveProbeInput)·"
        + "캐럿(2,4)·옵트인 스크롤(120)이 innerHTML 재구성을 가로질러 살아남는가.",
      run(ctx) {
        const doc = ctx.doc;
        const Preserve = requireService(ctx, "Preserve", ["around"]);
        const host = doc.createElement("div");
        host.id = "preserveProbeHost";
        host.setAttribute("data-preserve-scroll", "");
        host.style.cssText = "height:40px;overflow:auto";
        const markup = '<div style="height:400px"><input id="preserveProbeInput" value="abcdef"></div>';
        host.innerHTML = markup;
        doc.body.appendChild(host);
        ctx.state.host = host;
        const input = doc.getElementById("preserveProbeInput");
        input.focus();
        input.setSelectionRange(2, 4);
        host.scrollTop = 120;
        Preserve.around(() => { host.innerHTML = markup; });   // render() 의 재구성과 동형
        const a = doc.activeElement;
        const res = {
          focus_id: a ? a.id : null,
          sel_start: a ? a.selectionStart : null,
          sel_end: a ? a.selectionEnd : null,
          scroll_top: doc.getElementById("preserveProbeHost").scrollTop,
        };
        host.remove();
        return { preserve: res };
      },
      /* 레거시는 `host.remove()` 를 측정 안에 섞어 두고 실패하면 아무도 모른다 —
         400px 픽스처가 남으면 뒤 프로브의 스크롤·오버플로 측정이 통째로 거짓말이 된다. */
      teardown(ctx) {
        const host = ctx.state.host;
        if (host && host.parentNode) {
          host.remove();
          throw new Error(
            "preserve 픽스처(#preserveProbeHost)가 문서에 남았습니다 —"
            + " 다음 프로브의 레이아웃 측정을 오염시킵니다.",
          );
        }
      },
    },

    /* ── preserve_real (app.py:887·897 상수 · 3869·3871 호출) — 실화면 회귀 ── */
    {
      name: "preserve_real",
      keys: ["preserve_real"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3869,
      deadlineMs: 0,
      deadlineRationale:
        "레거시는 시한이 아니라 **고정 1.2초 대기**(app.py:3870) 하나였다 — 폴링도 만료 판정도"
        + " 없었다. 없던 감시견을 새로 세우지 않고 그 대기만 그대로 옮긴다. 스냅샷이 안 오면"
        + " 값이 `'no-snap'` 으로 남고 소비 게이트가 `== 'ok'` 에서 붉어진다(이미 시끄럽다).",
      after: ["preserve"],
      afterReason:
        "기제(합성 픽스처) → 실화면 순서를 잃으면 실패 귀인이 갈린다. 게다가 이 프로브는"
        + " 편집기로 이동했다 작업으로 돌아오는 **몰입 셸 왕복**이라, 앞에 두면 preserve 의"
        + " 픽스처가 화면 전환 한복판에서 측정된다.",
      note:
        "상태 인계 변경: 창 객체 `__snaps` 대신 `ctx.state.snaps`. 스냅샷은 실 컨트롤러"
        + " `initial()`(비동기)로 당기고, 스크롤은 가시 화면에서만 유효하므로 편집기를 가시화한다."
        + " 렌더는 배포된 push 진입점(`ctx.push`)으로 몬다 — 전역 조회가 아니다.",
      setup(ctx) {
        const snaps = {};
        ctx.state.snaps = snaps;
        const api = ctx.win.pywebview && ctx.win.pywebview.api;
        if (!api || typeof api.initial !== "function") {
          ctx.fail(ERROR_CODES.CONTRACT, "pywebview.api.initial 이 없습니다 — 스냅샷을 당길 수 없습니다.");
        }
        const Nav = requireService(ctx, "Nav", ["go"]);
        ["editor", "job"].forEach((scr) => {
          api.initial(scr).then((s) => { snaps[scr] = s; });
        });
        Nav.go("editor", { force: true });   // 스크롤은 가시 화면에서만 유효 → 편집기 가시화
      },
      async run(ctx) {
        /* app.py:3870 — `initial()` 해소 + 렌더 안정. 조건 없는 고정 대기 그대로다. */
        await ctx.sleep(1200);

        const doc = ctx.doc;
        const Nav = requireService(ctx, "Nav", ["go"]);
        const snaps = ctx.state.snaps || {};
        const out = {};
        ["editor", "job"].forEach((scr) => {
          try {
            if (!snaps[scr]) { out[scr] = "no-snap"; return; }
            ctx.push(scr, snaps[scr]);      // 실 render() (Preserve.around 래핑)
            out[scr] = "ok";
          } catch (e) { out[scr] = "throw:" + (e && e.message); }
        });

        /* 편집기 스크롤 보존 end-to-end. 스냅샷에 필드를 주입하는 이유는 재렌더가 innerHTML 을
           다시 짓기 때문이다 — DOM 에만 spacer 를 꽂으면 재렌더가 걷어 가 측정이 성립 안 한다. */
        try {
          const snap = snaps.editor;
          if (!snap) {
            out.editor_scroll_top = "no-snap";
            /* 원문의 이른 반환(app.py:913) 그대로 — 이 경로에서는 아래 Nav 복귀가 **일어나지
               않는다**. 고치지 않는다: 거동을 바꾸면 이식이 아니라 수리가 된다. */
            return { preserve_real: out };
          }
          const fields = [];
          for (let i = 0; i < 40; i += 1) {
            fields.push({
              name: "필드" + i, inferred_type: "text", in_table: false,
              occurrences: 1, context: "",
            });
          }
          snap.section = "template";
          snap.template_path = "C:/t/스크롤검증.hwpx";
          snap.template_name = "스크롤검증.hwpx";
          snap.template_media = "hwpx";
          snap.field_count = fields.length;
          snap.fields = fields;
          snap.schema_summary = "필드 40개";
          ctx.push("editor", snap);
          /* R4-02 — 본문이 React 소유가 되면서 커밋이 다음 turn 이다. 커밋 전에 scrollTop 을
             쓰면 아직 넘칠 내용이 없어 **0 으로 클램프**되고, 그 0 이 「보존 실패」로 읽힌다.
             넘칠 만큼 자란 뒤에 쓴다 — 조건이 서면 즉시 진행하므로 고정 지연이 아니다. */
          const box = doc.getElementById("editor-body");
          for (let turn = 0; turn < 12 && box.scrollHeight <= box.clientHeight; turn += 1) {
            await ctx.sleep(0);
          }
          box.scrollTop = 60;                 // 오버플로 안 — 클램프 없이 남을 값
          ctx.push("editor", snap);           // 실 재렌더 — 스크롤이 가로질러 살아야
          await ctx.sleep(0);
          out.editor_scroll_top = doc.getElementById("editor-body").scrollTop;
        } catch (e) { out.editor_scroll_top = "throw:" + (e && e.message); }
        Nav.go("job", { force: true });       // 자기 판을 자기가 걷는다(몰입 셸 잔존 금지)
        return { preserve_real: out };
      },
    },

    /* ── milestone_h_wave1 (app.py:3014 상수 · 3969 호출) — 타이포·위계·스크롤포트 ── */
    {
      name: "milestone_h_wave1",
      keys: ["milestone_h_wave1"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3969,
      deadlineMs: 0,
      deadlineRationale: "동기 IIFE 하나 — computed style 읽기뿐이고 레거시에도 폴링이 없다.",
      after: ["preserve_real"],
      afterReason:
        "preserve_real 의 마지막 동작이 셸을 `job` 으로 되돌린다. 앞에 두면 몰입 편집기가"
        + " 셸을 덮은 채 `#scr-job .zone-cap` 을 재게 되어 다른 표면을 잰다.",
      note:
        "이 프로브가 겨누는 것은 **타이포·위계 토큰**이지 작업 화면의 의미가 아니다 —"
        + " `#scr-job .zone-cap`·`jobGenBtn`·`jobOutTrack` 은 그 계약의 표본일 뿐이다."
        + " 표본은 자급(self-seed)한다: 앞 프로브가 남긴 DOM 에 무임승차하면 #137 의 교차오염이"
        + " 되돌아온다. 다만 `#scr-job .zone-cap` 목록은 여전히 앞선 job 렌더(클러스터 C 의"
        + " job_data_first, app.py:3877)를 소비한다 — 클러스터를 넘는 그 순서는 `legacySite`"
        + " 숫자(3877 < 3969)가 잇는다.",
      async run(ctx) {
        const doc = ctx.doc;
        const win = ctx.win;
        const style = (selector) => styleOf(ctx, doc.querySelector(selector));

        const captionText = (element) => {
          if (!element) return "";
          const label = element.cloneNode(true);
          label.querySelectorAll("button").forEach((button) => { button.remove(); });
          return label.textContent.trim();
        };
        /* legacy 판에서는 조건부 존이 숨김 DOM 으로 함께 있었지만 React 포털은 비활성 존을
           unmount 한다. 전환 직전의 data-first 캡션을 보관하고 빈 세션 캡션과 합쳐 같은
           타이포 표본 집합을 증명한다. */
        const candidateCaption = all(doc, "#scr-job .zone-cap")
          .map(captionText)
          .find((text) => text === "이 데이터에 사용할 문서") || "";

        /* R4 portal 캡션도 이 프로브의 표본이다. probe별 ctx.state는 격리되므로 preserve_real의
           스태시를 빌리지 않고, 화면 계약의 최소 빈 세션을 직접 밀어 React 커밋을 기다린다. */
        const emptyJob = {
          has_job: false, has_data: false, job_name: "",
          data_source_label: "", data_target: {}, data_notice: null,
          record_count: 0, selected_count: 0, records: [],
          filter: { active: false, search: "", columns: [], chips: [], branches: [] },
          candidates: { top: [], sections: [], more: 0, needs_count: 0, suggested: "", txt_note: "" },
          browse: { tab: "available", query: "", rows: [], available_count: 0, needs_count: 0, filtered_out: 0 },
          table: { columns: [], rows: [], visible_count: 0, hidden_selected: [], hidden_columns: [] },
          new_work: { can: true, reason: "" },
        };
        if (doc.getElementById("reactScreenStage")) {
          for (let turn = 0; turn < 12; turn += 1) {
            ctx.push("job", emptyJob);
            await ctx.sleep(0);
            if (captionText(doc.querySelector("#jobNoDataExit .zone-cap")) === "시작하기") break;
          }
        }

        const gen = doc.getElementById("jobGenBtn");
        const wasDisabled = gen.disabled;
        gen.disabled = true;
        const disabledPrimary = style("#jobGenBtn");
        gen.disabled = false;
        const enabledPrimary = style("#jobGenBtn");
        gen.disabled = wasDisabled;

        /* 카드 상태 계약 표본 — 죽은 `.tplcard` 대신 같은 선택자 묶음의 생존 소비자 `.jcard`. */
        const card = doc.createElement("div");
        card.className = "jcard";
        card.setAttribute("data-selftest-probe", "card");
        doc.body.appendChild(card);
        const baseCard = styleOf(ctx, card);
        card.setAttribute("aria-current", "true");
        const selectedCard = styleOf(ctx, card);
        card.remove();

        /* 로케이트 어포던스 표본 자급 — 목적은 React PathActions 후계의 아이콘·접근 이름
           *스타일 계약*이다. 제품 handler를 복제하지 않고 같은 class/ARIA 표본만 만든다. */
        let syntheticPathButtons = [];
        if (!doc.querySelector(".track-btn")) {
          const ot = doc.getElementById("jobOutTrack");
          if (ot) {
            const specs = [["reveal", "폴더에서 보기", "⌖"], ["copy", "경로 복사", "⧉"]];
            const buttons = specs.map(([action, label, glyph]) => {
              const button = doc.createElement("button");
              button.className = "track-btn";
              button.type = "button";
              button.dataset.trackAct = action;
              button.setAttribute("aria-label", label);
              button.setAttribute("title", label + " — C:/selftest/result.hwpx");
              const svg = doc.createElement("svg");
              svg.setAttribute("aria-hidden", "true");
              button.appendChild(svg);
              button.append(glyph);
              return button;
            });
            ot.replaceChildren(...buttons);
            syntheticPathButtons = buttons;
          }
        }
        const pathButtons = syntheticPathButtons.length
          ? syntheticPathButtons : all(doc, ".track-btn");

        const scrollHost = doc.createElement("div");
        scrollHost.className = "tblwrap";
        scrollHost.style.height = "48px";
        scrollHost.innerHTML = '<table class="map"><thead><tr><th>머리</th></tr></thead><tbody>'
          + Array.from({ length: 12 }, (_, i) => "<tr><td>행 " + i + "</td></tr>").join("")
          + "</tbody></table>";
        doc.body.appendChild(scrollHost);
        ctx.state.scrollHost = scrollHost;
        const scrollStyle = win.getComputedStyle(scrollHost);
        const stickyHead = scrollHost.querySelector("th");
        const stickyStyle = win.getComputedStyle(stickyHead);
        const stickyBefore = stickyHead.getBoundingClientRect().top;
        scrollHost.scrollTop = 40;
        const stickyAfter = stickyHead.getBoundingClientRect().top;
        const scrollContract = {
          overflow_y: scrollStyle.overflowY,
          gutter: scrollStyle.scrollbarGutter,
          overscroll: scrollStyle.overscrollBehavior,
          sticky_position: stickyStyle.position,
          sticky_holds: Math.abs(stickyAfter - stickyBefore) < 1,
          scroll_top: scrollHost.scrollTop,
        };
        scrollHost.remove();

        const jobSteps = all(doc, "#scr-job .zone-cap").map(captionText);
        if (candidateCaption && !jobSteps.includes(candidateCaption)) {
          const generationIndex = jobSteps.indexOf("생성 준비");
          jobSteps.splice(generationIndex < 0 ? jobSteps.length : generationIndex, 0, candidateCaption);
        }

        return {
          milestone_h_wave1: {
            headings: {
              screen: style(".scr-head h1"),
              section: style(".modal-card h3"),
              zone: style("#scr-job .zone-cap"),
            },
            job_steps: jobSteps,
            job_step_badges: doc.querySelectorAll("#scr-job .zone-cap .znum").length,
            card_base: baseCard,
            selected_card: selectedCard,
            disabled_primary: disabledPrimary,
            enabled_primary: enabledPrimary,
            pathtrack: {
              count: pathButtons.length,
              names: pathButtons.map((e) => e.getAttribute("aria-label")),
              titled: pathButtons.every((e) => !!e.getAttribute("title")),
              svg: pathButtons.every((e) => !!e.querySelector("svg")),
            },
            scroll: scrollContract,
          },
        };
      },
      teardown(ctx) {
        const scrollHost = ctx.state.scrollHost;
        if (scrollHost && scrollHost.parentNode) {
          scrollHost.remove();
          throw new Error(
            "milestone_h_wave1 의 스크롤포트 표본(.tblwrap)이 문서에 남았습니다 —"
            + " 다음 프로브의 오버플로 측정을 오염시킵니다.",
          );
        }
      },
    },

    /* ── milestone_h_overlay (app.py:3116 상수 · 3976·3978 호출) ──
       **주제는 오버레이·z-order·스크롤바 재질**이다. `wbCard`/`wbDots`(작업대 DOM, 클러스터 D)
       에 손을 대지만 그건 워크카드 재질을 잴 **표본**일 뿐이라 이 클러스터가 진다 —
       `wb*` id 를 전부 이 레인이 소유한다는 뜻이 아니다. */
    {
      name: "milestone_h_overlay",
      keys: ["milestone_h_overlay"],
      cluster: B_CLUSTER,
      owner: "frontend",
      modes: ["full"],
      legacySite: 3976,
      deadlineMs: 0,
      deadlineRationale:
        "레거시는 시한이 아니라 고정 대기 둘(0.3초 + 0.1초)뿐이었다 — 폴링도 만료 판정도 없다."
        + " 그 둘을 그대로 옮기고 없던 감시견을 새로 세우지 않는다.",
      completionField: "pending",
      requiresHost: ["window_resize"],
      hostSetup: { op: "window_resize", payload: { width: 720, height: 500 } },
      settleBeforeMs: 300,
      settleReason:
        "네이티브 창 720x500 재배치 반영(app.py:3975). 짧은 viewport 계약을 재기 전에"
        + " relayout 이 끝나야 `short_viewport` 가 이전 크기를 잰다.",
      cooldownAfterMs: 300,
      cooldownReason: "1440x900 복귀 뒤 relayout 안정(app.py:3983) — 뒤 프로브가 720px 폭을 잰다.",
      after: ["milestone_h_wave1"],
      afterReason:
        "이 프로브만 창을 720x500 으로 줄인다. 앞에 두면 milestone_h_wave1 이 좁은 창에서"
        + " 타이포·스크롤포트를 재고, 그 수치는 기준 실행(1440 폭)과 다른 regime 이다.",
      note:
        "상태 인계 변경: 창 객체 `__milestoneHOverlay` 와 그 위의 `finish` 함수가 사라지고"
        + " 러너가 `ctx.state` 로 든다. 레거시의 바깥 try/catch(실패를 `out.error` 라는 정상 모양"
        + " 값으로 바꾸던 것)도 폐기했다 — 던지면 러너가 구조화 오류로 싣고 키는 실리지 않는다."
        + " 가시성 공백: `finish()` 의 `outside.click()` 두 자리에 가시성 단언이 없다(원문 그대로).",
      setup(ctx) {
        const doc = ctx.doc;
        const win = ctx.win;
        const Modal = requireService(ctx, "Modal", ["open", "close"]);
        const Popover = requireService(ctx, "Popover", ["register", "place", "closeAll"]);
        const out = { pending: true };
        ctx.state.out = out;

        const root = doc.getElementById("overlayRoot");
        out.overlay_root_direct = root && root.parentElement === doc.body;
        /* R3-01(#410 개정 8) — H-16 불변식(오버레이 표면은 앱 그리드 stacking context 밖
           포털에 산다)의 합법 포털은 이제 둘이다: legacy #overlayRoot 와 React 오버레이
           호스트 컨테이너(#reactOverlayHost — promise 다이얼로그·토스트는 그 **직속** 자식).
           술어를 overlayRoot 한정으로 좁히는 대안은 기각 — React 쪽 배치 드리프트(다이얼로그가
           중첩 stacking context 안으로 새는 회귀)에 눈멀게 되는 관측 축소다. */
        const reactHost = doc.getElementById("reactOverlayHost");
        out.overlay_children_owned = all(doc, ".modal,.ctx-menu,.colpanel")
          .every((el) => el.parentElement === root
            || (reactHost !== null && el.parentElement === reactHost));

        /* 전역 스크롤바 재질 + sticky 머리 재질. */
        const scrollHost = doc.createElement("div");
        scrollHost.className = "jobtbwrap";
        scrollHost.style.cssText = "height:72px;width:320px;overflow:auto";
        scrollHost.innerHTML = '<table class="jobtb"><thead><tr><th>머리</th></tr></thead><tbody>'
          + Array.from({ length: 16 }, (_, i) => "<tr><td>행 " + i + "</td></tr>").join("")
          + "</tbody></table>";
        doc.body.appendChild(scrollHost);
        const sb = win.getComputedStyle(scrollHost, "::-webkit-scrollbar");
        const sbtn = win.getComputedStyle(scrollHost, "::-webkit-scrollbar-button");
        const sh = win.getComputedStyle(scrollHost.querySelector("th"));
        out.scrollbar = {
          width: sb.width, button_display: sbtn.display,
          button_width: sbtn.width, button_height: sbtn.height,
        };
        out.sticky_material = {
          position: sh.position, backdrop: sh.backdropFilter, background: sh.backgroundColor,
        };
        scrollHost.remove();

        /* 워크카드 재질 — 표본은 작업대 카드(클러스터 D 의 DOM)를 빌리고 원복한다. */
        const cardRender = doc.getElementById("wbCard");
        const savedCardClass = cardRender.className;
        cardRender.className = "wb-preview wc-render f-gulimche";
        let dot = doc.querySelector("#wbDots .wc-dot");
        let madeDot = false;
        if (!dot) {
          dot = doc.createElement("button");
          dot.className = "wc-dot";
          doc.getElementById("wbDots").appendChild(dot);
          madeDot = true;
        }
        const cr = cardRender && win.getComputedStyle(cardRender);
        const ds = dot && win.getComputedStyle(dot);
        const dm = dot && win.getComputedStyle(dot, "::before");
        out.workcard = {
          max_height: cr && cr.maxHeight, overflow_y: cr && cr.overflowY,
          font_family: cr && cr.fontFamily,
          /* 높이 계약이 열 수에 따라 갈린다 — 어느 쪽을 쟀는지 함께 실어야 단언이 창 폭에
             따라 거짓말하지 않는다. */
          narrow: win.innerWidth <= 920, flex_grow: cr && cr.flexGrow,
          dot_hit: ds && [ds.width, ds.height], dot_mark: dm && [dm.width, dm.height],
          dots_overflow: win.getComputedStyle(doc.getElementById("wbDots")).overflow,
        };
        if (madeDot) dot.remove();
        cardRender.className = savedCardClass;

        /* 팝오버 배치 + 모달 스택 + IME Escape + 짧은 viewport. */
        const trigger = doc.createElement("button");
        trigger.id = "__hOverlayTrigger";
        trigger.textContent = "trigger";
        trigger.style.cssText = "position:fixed;right:2px;bottom:2px";
        doc.body.appendChild(trigger);
        const outside = doc.createElement("button");
        outside.id = "__hOverlayOutside";
        outside.textContent = "outside";
        doc.body.appendChild(outside);
        const pop = doc.createElement("div");
        pop.className = "ctx-menu";
        pop.style.cssText = "display:flex;width:260px;height:160px";
        pop.innerHTML = '<button id="__hOverlayInside">inside</button>';
        root.appendChild(pop);
        ctx.state.scaffold = [trigger, outside, pop];
        let popOpen = true;
        let closeCount = 0;
        const openPop = () => { popOpen = true; pop.style.display = "flex"; };
        const closePop = () => { popOpen = false; pop.style.display = "none"; closeCount += 1; };
        const unregister = Popover.register({
          isOpen: () => popOpen,
          contains: (t) => pop.contains(t),
          close: closePop,
        });
        const placed = Popover.place(pop, trigger);
        const pr = pop.getBoundingClientRect();
        const ps = win.getComputedStyle(pop);
        out.popover_place = {
          placement: placed.placement,
          in_viewport: pr.left >= 0 && pr.top >= 0
            && pr.right <= win.innerWidth && pr.bottom <= win.innerHeight,
          origin: pop.style.transformOrigin, radius: ps.borderRadius, shadow: ps.boxShadow,
        };

        trigger.focus();
        /* 같은 재겨눔(R4-02) — 위 modal_a11y 의 주석이 사유를 든다. */
        Modal.open("promptModal", {
          initialFocus: doc.getElementById("promptModalInput"), returnFocus: trigger,
        });
        const formModal = doc.getElementById("promptModal");
        out.modal_closed_popover = !popOpen;
        out.modal_focus_in = doc.activeElement.id;
        out.z_order = parseInt(win.getComputedStyle(formModal).zIndex, 10)
          > parseInt(ps.zIndex, 10);
        /* IME 조합 중 Escape 는 모달을 **열어 둔다** ↔ 맨 Escape 는 닫는다(양성/음성 한 쌍). */
        keydown(ctx, "Escape", { isComposing: true });
        out.ime_escape_kept_open = !formModal.classList.contains("hidden")
          && !formModal.classList.contains("is-closing");
        keydown(ctx, "Escape");
        out.exit_blocks_pointer = formModal.classList.contains("is-closing")
          && win.getComputedStyle(formModal).pointerEvents === "auto";
        finishModal(ctx, "promptModal");
        out.menu_trigger_restored = doc.activeElement === trigger;

        /* 두 겹에서 Escape 한 번은 최상위만 퇴장시킨다. */
        Modal.open("promptModal", { returnFocus: trigger });
        Modal.open("confirmModal", { returnFocus: trigger });
        keydown(ctx, "Escape");
        out.escape_one_layer = doc.getElementById("confirmModal").classList.contains("is-closing")
          && !doc.getElementById("promptModal").classList.contains("is-closing");
        finishModal(ctx, "confirmModal");
        Modal.close("promptModal");
        finishModal(ctx, "promptModal");

        /* 720x500 에서 200줄 본문을 끝까지 스크롤하면 액션이 viewport 안에 도달한다. */
        const longModal = doc.getElementById("confirmModal");
        const longBody = doc.getElementById("confirmModalBody");
        const savedBody = longBody.innerHTML;
        longBody.innerHTML = Array.from(
          { length: 200 }, (_, i) => "<div>본문 " + i + "</div>",
        ).join("");
        Modal.open("confirmModal", { returnFocus: trigger });
        const longCard = longModal.querySelector(".modal-card");
        longCard.scrollTop = longCard.scrollHeight;
        const actions = longModal.querySelector(".modal-actions").getBoundingClientRect();
        /* CSS 100dvh 와 같은 fractional 좌표계를 써야 고 DPI 에서 innerHeight 의 정수 절삭을
           modal-card overflow 로 오판하지 않는다. */
        out.short_viewport = {
          height: longCard.getBoundingClientRect().height,
          viewport: (win.visualViewport ? win.visualViewport.height : win.innerHeight),
          scrollable: longCard.scrollHeight > longCard.clientHeight,
          actions_reachable: actions.bottom <= win.innerHeight + 1 && actions.top >= -1,
        };
        Modal.close("confirmModal");
        finishModal(ctx, "confirmModal");
        longBody.innerHTML = savedBody;

        /* click 없는 pointer 제스처(드래그)는 팝오버를 닫는다 — 그 뒤 진짜 click 은 살아야 한다. */
        let outsideClicks = 0;
        outside.addEventListener("click", () => { outsideClicks += 1; });
        openPop();
        outside.dispatchEvent(new win.PointerEvent("pointerdown", {
          bubbles: true, button: 0, pointerId: 77, isPrimary: true,
        }));
        outside.dispatchEvent(new win.PointerEvent("pointerup", {
          bubbles: true, button: 0, pointerId: 77, isPrimary: true,
        }));
        out.drag_closed = !popOpen;

        /* 레거시는 이 마무리를 `out.finish` 로 **결과 객체 위에** 얹고 파이썬이 한 task 뒤에
           불렀다(그리고 `delete out.finish`). 러너에서는 결과가 아니라 상태로 든다 —
           그래서 방출 모양에 `finish` 가 애초에 서지 않고 지울 것도 없다. */
        ctx.state.finish = () => {
          /* 가시성 미단언 자리 ⑦(app.py:3261). */
          outside.click();
          out.click_after_drag = outsideClicks === 1;
          openPop();
          outside.dispatchEvent(new win.PointerEvent("pointerdown", {
            bubbles: true, button: 2, pointerId: 78, isPrimary: true,
          }));
          /* 가시성 미단언 자리 ⑧(app.py:3267). */
          outside.click();
          out.click_after_right = outsideClicks === 2;
          openPop();
          const inside = doc.getElementById("__hOverlayInside");
          inside.focus();
          inside.dispatchEvent(new win.FocusEvent("focusout", {
            bubbles: true, relatedTarget: outside,
          }));
          out.focusout_closed = !popOpen;
          openPop();
          doc.body.dispatchEvent(new win.Event("scroll", { bubbles: false }));
          out.scroll_closed = !popOpen;
          openPop();
          Popover.closeAll();
          out.close_all_closed = !popOpen;
          unregister();
          pop.remove();
          trigger.remove();
          outside.remove();
          ctx.state.scaffold = [];
          out.close_count = closeCount;
          out.pending = false;
          return out;
        };
      },
      async run(ctx) {
        /* app.py:3977 — click 없는 pointer 제스처의 **다음-task 만료**를 재현하려면 한 task
           이상 지나야 한다. 레거시의 0.1초 그대로. */
        await ctx.sleep(100);
        const finish = ctx.state.finish;
        if (typeof finish !== "function") {
          ctx.fail(
            ERROR_CODES.INCOMPLETE,
            "overlay setup 이 마무리 단계를 세우지 못했습니다 — 부분 상태를 결과로 내지 않습니다.",
          );
        }
        return { milestone_h_overlay: finish() };
      },
      /* 창 크기 복귀는 **호스트가 한다**(app.py:3982) — 프런트는 요청만 한다.
         남은 발판(fixed 버튼·팝오버)은 뒤 프로브의 히트 테스트를 가리므로 잔존을 시끄럽게 만든다. */
      async teardown(ctx) {
        await ctx.host("window_resize", { width: 1440, height: 900 });
        const left = (ctx.state.scaffold || []).filter((el) => el && el.parentNode);
        if (left.length > 0) {
          left.forEach((el) => el.remove());
          throw new Error(
            "milestone_h_overlay 의 발판(" + left.map((el) => el.id || el.className).join(", ")
            + ")이 문서에 남았습니다 — 고정 배치라 다음 프로브의 클릭·측정을 가립니다.",
          );
        }
      },
    },
  ];
}

/** 러너에 이 클러스터를 통째로 등록한다. 레인 E 와 같은 이름꼴이다. */
export function registerBootRoutingOverlayProbes(runner) {
  return runner.registerAll(createBootRoutingOverlayProbes());
}
