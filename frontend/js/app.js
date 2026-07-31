/* 라우터 + 부팅 — 상단 토바 탭으로 화면 전환, pywebview 준비 시 실화면 초기화.
   화면별 로직은 js/screens/*.js 가 소유(JobScreen.init 등). 여기선 배선만.
   셸은 좌 레일 5화면 라우팅에서 상단 2탭(+과도기 임시 2)으로 교체됐다(F2 PR-B, 지도 §10.9).

   `screens` 는 compat 이 먼저 구성해 넘기는 화면 객체 넷(`{ library, editor, job, workbench }`)
   — 셸은 마지막에 구성되므로 late-binding 이 필요 없다. `Theme`·`Personalization`·`DataPicker`
   는 factory 산물 주입, `Modal`·`SurfaceSheet` 는 평범한 named export 라 직접 import 다. */

import { Modal } from "./modal.js";
import { SurfaceSheet } from "./surface_sheet.js";

export function createAppShell({ Bridge, Theme, Personalization, DataPicker, screens }) {
  /* 네이티브 X 닫기 확인 착지(#218 G1). Python closing 이벤트가 현재 세션 술어를 판정해
     호출하며, 취소/Escape는 창을 유지하고 다음 X에서 새 상태를 다시 판정한다. */
  let closePromptPending = false;
  const AppCloseGuard = {
    async prompt(state) {
      if (closePromptPending) return;
      closePromptPending = true;
      const reasons = (state && state.reasons) || [];
      try {
        const ok = await Modal.confirm({
          title: "앱 종료 확인",
          body: "앱을 닫으면 다음 진행 상태가 사라집니다:\n\n• " + reasons.join("\n• ") +
            "\n\n그래도 종료할까요?",
          confirmLabel: "종료",
          cancelLabel: "계속 작업",
          danger: true,
        });
        if (ok) await window.pywebview.api.confirm_window_close();
        else await window.pywebview.api.cancel_window_close();
      } catch (err) {
        await window.pywebview.api.cancel_window_close();
        window.alert("종료 확인을 처리하지 못해 창을 유지합니다: " +
          String((err && err.message) || err));
      } finally {
        closePromptPending = false;
      }
    },
  };
  /* 비동기 실패 최종 백스톱 — 지역 가드(디스패처 try/catch·.catch)를 빠뜨린 브리지
     rejection 이 조용한 무반응으로 증발하는 결함류(F8·F9·#45 profile_*·P2 onClick)가
     파일마다 반복 재발했다. 사이트별 규율 대신 셸에서 구조적으로 받는다: 여기 도달한
     rejection 은 "가드를 잊은 곳"뿐이며(지역에서 잡힌 실패는 오지 않는다) alert 로
     시끄럽게 재진술한다(confirm-or-alarm). 개별 화면의 맞춤 가드는 계속 1차 방어선. */
  window.addEventListener("unhandledrejection", (e) => {
    e.preventDefault();
    const r = e.reason;
    window.alert(String((r && r.message) || r));
  });

  const navs = document.querySelectorAll(".navbtn");
  const scrs = document.querySelectorAll(".scr");
  const DEFAULT_SCREEN = "job";  // R-info 결정 1: 작업이 중심 개체이자 콜드 부팅 랜딩(#239).
  let routingReady = false;

  /* 전환 시 자동 새로고침 대상(C6) — 다른 화면의 변경(에디터 자동등록·삭제 등)이 부팅
     스냅샷에 가려지는 고착 방지. 백엔드에 _do_refresh 가 있는 컨트롤러만 화이트리스트로
     보낸다(미지 액션은 백엔드가 loud 거절하므로 무차별 dispatch 금지). 수동 새로고침
     버튼은 유지된다(명시적 재스캔 경로). 「문서 만들기」도 레지스트리 파생 후보·문서 탐색을
     스냅샷으로 그리므로 포함한다 — 빼면 에디터에서 막 저장한 작업이 후보에 안 보인다.
     실행 화면(run)은 사망(슬라이스 3)이라 목록에서 제거. 홈은 「문서 작업」 라이브러리로
     대체됐다(재작성 F2) — 그 화면의 refresh 는 레지스트리 + 영속 그룹 접힘을 함께 다시
     읽는다(다른 화면에서 접은 상태가 stale 로 남지 않게). */
  const REFRESH_ON_NAV = ["library", "job"];

  /* 몰입 표면 — 상단 2탭을 덮고(셸 표지를 body 클래스로 내려 CSS 가 감춘다) 나가는 이동이
     자기 이탈 가드를 먼저 지나는 화면들(EditorScreen·WorkbenchScreen — compat 이 구성해
     넘긴 screens.editor/.workbench 가 그 실물이다). 탭이 없으므로 `navs` 에도 없다. */
  const IMMERSIVE = [
    { id: "editor", owner: screens.editor, cls: "editor-open" },
    { id: "workbench", owner: screens.workbench, cls: "workbench-open" },
  ];

  /* 화면 스냅샷 재당김의 **단일 정의**(8R 근본 조치) — 전환이 자동으로 쏘는 발신과, 그
     화면을 **노출하기 전에** 완료를 기다려야 하는 호출자(편집기 이탈)가 같은 절차를 쓴다.
     두 벌이 되면 한쪽만 고쳐지고 그 경로만 옛 규칙을 든 화면을 내보인다 — 실제로 F7 은
     복귀처마다 따로 봉합하다 같은 결함을 네 라운드에 걸쳐 재발시켰다.
     새로고칠 백엔드가 없으면(브라우저 단독 미리보기·부팅 직전) 무동작 이행 약속을 준다. */
  function refresh(id) {
    if (!routingReady || !REFRESH_ON_NAV.includes(id)
        || !window.pywebview || !Bridge) {
      return Promise.resolve(null);
    }
    // refresh 가 사후 고지(notice)를 돌려주면 alert 로 시끄럽게 알린다 — 열린 세션이 다른
    // 화면의 삭제로 닫힌 경우 등. notice 없는 화면엔 무해(무반응).
    return Bridge.call(id, "refresh", {}).then((r) => {
      if (r && r.notice) window.alert(r.notice);
      return r;
    });
  }

  /* 화면 전환 — 탭 클릭과 라이브러리 상세의 프로그램적 이동이 공유하는 단일 경로.

     편집기(재작성 F7)는 **몰입 표면**이라 두 가지가 다르다: ①상단 2탭을 덮는다(셸 표지를
     body 클래스로 내려 CSS 가 감춘다 — 편집 중에 화면 전환구가 살아 있으면 처분 미확정
     이탈구가 다시 생긴다) ②나가는 이동은 편집기의 이탈 가드를 **먼저** 지난다. 가드는
     비동기(3택 모달)라 여기서 위임하고 처분이 끝나면 `force` 로 되돌아온다 — go() 를
     비동기로 바꾸면 반환값을 무시하는 기존 호출부 전부가 조용히 순서를 잃는다. */
  function go(id, opts) {
    // 몰입 표면의 **단일 목록**(F6) — 편집기 하나였을 때는 특례 한 줄이었지만, 작업대가
    // 합류하면서 같은 모양이 둘이 됐다. 특례를 늘리면 가드의 완전성이 표면 수에 비례한다
    // (F7 이 편집기를 화면으로 올린 바로 그 이유) — 그래서 목록으로 만든다: 새 몰입 표면은
    // 여기 한 줄이고, 이탈 위임과 셸 은닉이 자동으로 따라온다.
    for (const im of IMMERSIVE) {
      const el = document.getElementById("scr-" + im.id);
      if (id !== im.id && el && el.classList.contains("on") && !(opts && opts.force)) {
        const owner = im.owner;
        if (owner && owner.leaveTo) { owner.leaveTo(id); return; }
      }
    }
    // 펼침 면 회수(F7) — 실 DOM 을 오버레이로 옮겨 띄우는 면이라, 열린 채 화면이 바뀌면
    // 남의 화면 위에 이 화면의 DOM 이 떠 있는다. 전환 자체가 소유하므로 화면이 늘어도
    // 같은 회수가 걸린다(종전엔 「편집 모드 진입」이 그 자리에서 닫아 줬다).
    if (SurfaceSheet && SurfaceSheet.closeAllAndRestore) {
      SurfaceSheet.closeAllAndRestore();
    }
    navs.forEach((x) => x.setAttribute("aria-current", x.dataset.scr === id ? "true" : "false"));
    scrs.forEach((s) => s.classList.toggle("on", s.id === "scr-" + id));
    IMMERSIVE.forEach((im) => document.body.classList.toggle(im.cls, id === im.id));
    if (!routingReady) return;  // pywebviewready 전에는 DOM 기본 랜딩만 정하고 브리지 호출은 미룬다.
    // 실패는 조용히 삼키지 않는다(confirm-or-alarm) — 화면은 이미 전환됐고 스냅샷만 낡음.
    // `refreshed` 는 호출자가 **전환 전에** 이미 기다린 경우다(편집기 이탈 — 8R P1): 다시
    // 쏘면 왕복이 두 벌이 되고, 늦게 도착한 두 번째가 방금 복원한 면을 흔든다.
    if (!(opts && opts.refreshed)) {
      refresh(id).catch((err) => window.alert(String((err && err.message) || err)));
    }
    // 「문서 만들기」 복귀 시 편집 호스트의 에디터도 재렌더(#138 리뷰 F12) — job refresh 는
    // 세션 스냅샷만 갱신하고 편집 모드 1단계 피커는 놔둬, 관리 화면에서 바뀐 공유 그룹
    // 접힘이 stale 로 남는다.
    if (id === "job" && screens.editor && screens.editor.rerender) {
      screens.editor.rerender();
    }
    // 「기안」 표면은 진입 시 재동기가 필요하다 — 이 화면 DOM 은 자기 화면에 푸시가 올 때만
    // 갱신되는데, 그 사이 저쪽에서 바뀔 수 있는 것이 둘 있다: ①템플릿 드롭다운은 스냅샷이
    // 아니라 initial 1회로 채워지고(#135 — 다른 화면이 더한 템플릿이 안 보인다) ②**대상 글꼴
    // 선언은 앱 전역**이라 저쪽 기안 표면에서 바꿀 수 있다(코덱스 리뷰 P2). 둘 다 refresh
    // 디스패치로는 못 고친다(하나는 스냅샷 소유가 아니고, 하나는 재렌더가 필요).
  }
  // 「작업 에디터」 과도기 항목 사망(슬라이스 5)과 함께 제거 — 편집 진입은 EditorEntry
  // 소비처(「문서 작업」 상세 등)가 담당한다.
  navs.forEach((b) => b.addEventListener("click", () => go(b.dataset.scr)));
  // 화면 간 프로그램적 이동의 단일 경로 — 라이브러리 상세의 「문서 만들기에서 사용」 등이
  // 대상 화면을 자체 dispatch 로 먼저 겨눈 뒤 여기로 전환한다(library.js 가 소비).
  const Nav = { go, refresh };
  go(DEFAULT_SCREEN);  // 브리지 준비 전에는 DOM·탭 기본 상태만 확정한다.

  // 글자 크기 라벨 — 셸 전역 개인화 표지. 레일 접기(#18/9B2AB35D-A)는 상단 토바 교체와 함께
  // 사망했다(F2 PR-B, 지도 §10.9): 토바는 64px 한 줄이라 접을 것이 없고, 좁은 창의 여유는
  // 브랜드 워드마크·도구 값 라벨 접힘(CSS 820px)이 대신 번다.
  function syncPersonalizationLabels() {
    const fontLabel = document.getElementById("fontScaleLabel");
    const fontText = { normal: "기본", large: "크게 (125%)", larger: "더 크게 (150%)" };
    if (fontLabel && Personalization) {
      fontLabel.textContent = fontText[Personalization.currentFontScale()];
    }
  }
  const fontScaleToggle = document.getElementById("fontScaleToggle");
  if (fontScaleToggle) fontScaleToggle.addEventListener("click", () =>
    Personalization.toggleFontScale());
  window.addEventListener("hwpx:personalizationchange", syncPersonalizationLabels);
  syncPersonalizationLabels();

  // 「기안」 master 폭 스플리터(S7) — 「문서 만들기」 좌 목록 사망 뒤 남는 유일 소비처지만
  // CSS 변수·설정값(`master_width`)은 그대로 공유 계약을 유지한다(F6 작업대 합류 지점).
  document.querySelectorAll(".master-splitter").forEach((splitter) => {
    splitter.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const app = document.querySelector(".app");
      const startX = event.clientX;
      const startWidth = parseFloat(getComputedStyle(app).getPropertyValue("--master-width")) || 240;
      splitter.setPointerCapture(event.pointerId);
      document.body.classList.add("resizing-master");
      const move = (e) => Personalization.setMasterWidth(startWidth + e.clientX - startX);
      const finish = (e) => {
        splitter.removeEventListener("pointermove", move);
        splitter.removeEventListener("pointerup", finish);
        splitter.removeEventListener("pointercancel", finish);
        document.body.classList.remove("resizing-master");
        if (splitter.hasPointerCapture(e.pointerId)) splitter.releasePointerCapture(e.pointerId);
        Personalization.saveMasterWidth(
          parseFloat(getComputedStyle(app).getPropertyValue("--master-width")));
      };
      splitter.addEventListener("pointermove", move);
      splitter.addEventListener("pointerup", finish);
      splitter.addEventListener("pointercancel", finish);
    });
    splitter.addEventListener("keydown", (event) => {
      const now = parseFloat(getComputedStyle(document.querySelector(".app"))
        .getPropertyValue("--master-width")) || 240;
      let next = now;
      if (event.key === "ArrowLeft") next -= 10;
      else if (event.key === "ArrowRight") next += 10;
      else if (event.key === "Home") next = Personalization.masterMin;
      else if (event.key === "End") next = Personalization.masterMax;
      else return;
      event.preventDefault();
      Personalization.saveMasterWidth(next);
    });
  });

  // 테마 전환(System→Light→Dark) — 셸 전역. Theme(theme.js)가 data-theme 를 소유하고
  // 브리지로 Python 설정에 영속(#74), 여기선 배선 + 토바 라벨을 현재 모드로 동기화만 한다.
  const themeToggle = document.getElementById("themeToggle");
  const themeLabel = document.getElementById("themeLabel");
  const THEME_TEXT = { system: "시스템", light: "라이트", dark: "다크" };
  function syncThemeLabel() {
    if (themeLabel && Theme) themeLabel.textContent = THEME_TEXT[Theme.current()];
  }
  if (themeToggle && Theme) {
    themeToggle.addEventListener("click", () => { Theme.toggle(); });
    // 라벨 동기는 themechange 단일 경로 — 토글이든 부팅 주입(app.py loaded→Theme.apply)이든
    // 같은 신호로 반영된다. 이 스크립트는 주입 **전**(body 말미)에 돌므로 직접 호출은 기본
    // system 라벨만 세우고, 저장 테마는 주입 시 이벤트로 재동기된다(#74 라벨 어긋남 방지).
    window.addEventListener("hwpx:themechange", syncThemeLabel);
    syncThemeLabel();
  }

  // pywebview.api 준비 후 실화면 초기화(브라우저 단독 미리보기에선 안 뜸 — 정상).
  window.addEventListener("pywebviewready", () => {
    routingReady = true;
    if (screens.library) screens.library.init();  // 「문서 작업」 라이브러리(F2 — 홈 승계)
    if (screens.editor) screens.editor.init();
    if (screens.job) screens.job.init();  // 「문서 만들기」(#90) — 유일 생성 표면
    if (screens.workbench) screens.workbench.init();  // TXT 검토·복사 작업대(F6)
    // (「템플릿 관리」 화면은 사망(F8 §10.17) — tpl 채널 소비는 editor.js 구독이 잇는다.)
    // 데이터 선택 다이얼로그(재작성 F1) — 화면이 아니라 오버레이라 라우팅 대상이 아니지만
    // pool 관측 푸시의 구독자라 여기서 배선한다(구 PoolScreen.init 승계).
    if (DataPicker) DataPicker.init();
  });

  return { Nav, AppCloseGuard };
}
