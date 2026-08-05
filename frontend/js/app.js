/* 셸 집행 adapter — 판정은 상태기계(src/shell/nav.ts), 여기는 legacy DOM 위 **집행**만 진다.
   화면별 로직은 js/screens/*.js 가 소유(JobScreen.init 등). R3-02(#411)가 셸을 셋으로 갈랐다:

   - **판정** — 현재 화면·몰입 이탈 위임·ready 게이트·재당김 규약·닫기 직렬화는 상태기계
     하나가 소유한다. 이 파일이 판정을 재조립하면 그것이 경계 위반이다(같은 상태를 두 곳이
     판정하지 않는다).
   - **수명주기** — 셸 리스너 부착/해제와 부팅 시퀀스(ready 사건 → init 5)는 React
     ShellHost 가 소유한다. 이 파일은 대상·핸들러를 구성 시 캡처해 **서술**(`shellHost`)로
     넘긴다 — 그래서 재초기화가 리스너를 복제하지 않는 계약이 effect 대칭 해제로 선다.
   - **집행** — 클래스·속성 토글, 브리지 발신, 문안·재진술, 스플리터 제스처는 여기 남는다.
     집행 대상이 legacy 소유 DOM(화면 루트의 클래스·속성)이라서다 — R4 가 화면을 옮기면
     이 adapter 의 집행 대상이 줄고, R5 가 0 으로 만든다.

   `screens` 는 합성 루트가 먼저 구성해 넘기는 화면 객체 넷(`{ library, editor, job,
   workbench }`), `shellNav` 는 같은 루트가 구성한 상태기계다. `Theme`·`Personalization`·
   `DataPicker` 는 factory 산물 주입, `Modal`·`SurfaceSheet` 는 평범한 named export 라 직접
   import, 정본 상수(DEFAULT_SCREEN·IMMERSIVE_SURFACES)는 상태기계 모듈에서 읽는다. */

import { Modal } from "./modal.js";
import { SurfaceSheet } from "./surface_sheet.js";
import { DEFAULT_SCREEN, IMMERSIVE_SURFACES } from "../src/shell/nav.ts";

export function createAppShell({ Bridge, Theme, Personalization, DataPicker, screens, shellNav }) {
  /* 네이티브 X 닫기 확인 착지(#218 G1). Python closing 이벤트가 현재 세션 술어를 판정해
     호출하며, 취소/Escape는 창을 유지하고 다음 X에서 새 상태를 다시 판정한다.
     직렬화 **판정**(단일 실행)은 상태기계가 지고, 호출·문안·danger·브리지 발신은 여기
     잔존한다 — 파괴 확정 감사망(danger 감사·dom-contract)이 legacy 층 원문 위에서 완전하기
     때문이다(패킷 rev3 개정 5: 잔존이 설계 위반이 아니라 계약이다). */
  const AppCloseGuard = {
    async prompt(state) {
      if (!shellNav.beginClosePrompt()) return;
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
        if (ok) await Bridge.confirmWindowClose();
        else await Bridge.cancelWindowClose();
      } catch (err) {
        await Bridge.cancelWindowClose();
        window.alert("종료 확인을 처리하지 못해 창을 유지합니다: " +
          String((err && err.message) || err));
      } finally {
        shellNav.endClosePrompt();
      }
    },
  };

  const navs = document.querySelectorAll(".navbtn");
  const scrs = document.querySelectorAll(".scr");

  /* ── 집행자 — 상태기계 판정 하나의 DOM·브리지 효과 전부. 판정 재조립 금지. ── */
  shellNav.bindExecutor({
    /* 몰입 이탈 위임(F7·F6) — 소유 화면(주입 객체)의 가드에 맡긴다. 가드가 비동기(3택
       모달)라 상태기계가 전환을 중단하고, 처분이 끝나면 화면 쪽이 `force` 로 되돌아온다.
       leaveTo 부재면 위임 불성립을 알려 전환이 계속된다(가드 없는 표면이 항행을 막는 새
       상태 금지). */
    delegateLeave(from, to) {
      const owner = screens[from];
      if (owner && owner.leaveTo) { owner.leaveTo(to); return true; }
      return false;
    },
    /* 펼침 면 회수(F7) — 실 DOM 을 오버레이로 옮겨 띄우는 면이라, 열린 채 화면이 바뀌면
       남의 화면 위에 이 화면의 DOM 이 떠 있는다. 전환 판정이 상태기계로 가도 이 호출은
       집행 포트에 남는다 — 가드 완전성이 표면 수에 비례하지 않게(원 결정 보존, 패킷 §6). */
    reclaimSurfaces() {
      if (SurfaceSheet && SurfaceSheet.closeAllAndRestore) {
        SurfaceSheet.closeAllAndRestore();
      }
    },
    /* 클래스·속성 집행 — 셸이 만지는 것은 legacy 화면 루트의 클래스·속성뿐이다. 몰입
       표면은 셸 표지를 body 클래스로 내려 CSS 가 감춘다(편집 중에 화면 전환구가 살아
       있으면 처분 미확정 이탈구가 다시 생긴다). 좌표는 상태기계와 같은 정본을 읽는다. */
    applyScreen(id) {
      navs.forEach((x) => x.setAttribute("aria-current", x.dataset.scr === id ? "true" : "false"));
      scrs.forEach((s) => s.classList.toggle("on", s.id === "scr-" + id));
      IMMERSIVE_SURFACES.forEach((im) => document.body.classList.toggle(im.cls, id === im.id));
    },
    /* 재당김 발신 — 규약 판정(ready·화이트리스트)은 상태기계가 이미 끝냈다. 여기는 호스트
       가용성 판독과 발신·notice 재진술만: 새로고칠 백엔드가 없으면(브라우저 단독 미리보기·
       부팅 직전) 무동작 이행 약속을 준다. refresh 가 사후 고지(notice)를 돌려주면 alert 로
       시끄럽게 알린다 — 열린 세션이 다른 화면의 삭제로 닫힌 경우 등. */
    dispatchRefresh(id) {
      if (!window.pywebview || !Bridge) return Promise.resolve(null);
      return Bridge.call(id, "refresh", {}).then((r) => {
        if (r && r.notice) window.alert(r.notice);
        return r;
      });
    },
    /* 전환 자동 재당김의 실패 재진술 — 실패는 조용히 삼키지 않는다(confirm-or-alarm).
       화면은 이미 전환됐고 스냅샷만 낡음. */
    notifyRefreshFailure(err) {
      window.alert(String((err && err.message) || err));
    },
    /* 「문서 만들기」 복귀 시 편집 호스트의 에디터도 재렌더(#138 리뷰 F12) — job refresh 는
       세션 스냅샷만 갱신하고 편집 모드 1단계 피커는 놔둬, 관리 화면에서 바뀐 공유 그룹
       접힘이 stale 로 남는다. */
    rerenderEditor() {
      if (screens.editor && screens.editor.rerender) {
        screens.editor.rerender();
      }
    },
  });

  /* 파사드 — 표면 무변경(`Nav.go`·`Nav.refresh`). go 는 synchronous 다: 비동기로 바꾸면
     반환값을 무시하는 기존 호출부 전부가 조용히 순서를 잃는다. 판정은 전부 상태기계 안이라
     이 두 함수에는 분기가 없다. */
  function go(id, opts) {
    shellNav.go(id, opts);
  }
  function refresh(id) {
    return shellNav.refresh(id);
  }
  // 화면 간 프로그램적 이동의 단일 경로 — 라이브러리 상세의 「문서 만들기에서 사용」 등이
  // 대상 화면을 자체 dispatch 로 먼저 겨눈 뒤 여기로 전환한다(library.js 가 소비).
  const Nav = { go, refresh };
  go(DEFAULT_SCREEN);  // 브리지 준비 전에는 DOM·탭 기본 상태만 확정한다(구성=랜딩 의미 보존).

  // 글자 크기 라벨 — 셸 전역 개인화 표지. 라벨 동기는 hwpx:* 이벤트 단일 경로이고, 구성 시
  // 직접 호출은 기본 라벨만 세운다(저장값은 부팅 주입 시 이벤트로 재동기 — #74).
  function syncPersonalizationLabels() {
    const fontLabel = document.getElementById("fontScaleLabel");
    const fontText = { normal: "기본", large: "크게 (125%)", larger: "더 크게 (150%)" };
    if (fontLabel && Personalization) {
      fontLabel.textContent = fontText[Personalization.currentFontScale()];
    }
  }
  const fontScaleToggle = document.getElementById("fontScaleToggle");
  syncPersonalizationLabels();

  // 테마 라벨 — Theme(theme.js)가 data-theme 를 소유하고 브리지로 Python 설정에 영속(#74),
  // 여기선 토바 라벨을 현재 모드로 동기화만 한다.
  const themeToggle = document.getElementById("themeToggle");
  const themeLabel = document.getElementById("themeLabel");
  const THEME_TEXT = { system: "시스템", light: "라이트", dark: "다크" };
  function syncThemeLabel() {
    if (themeLabel && Theme) themeLabel.textContent = THEME_TEXT[Theme.current()];
  }
  if (themeToggle && Theme) syncThemeLabel();

  /* ── 셸 리스너 서술 — 부착/해제 수명주기는 React ShellHost 소유(R3-02). 대상은 구성
     시점 캡처다(정적 2탭·화면 루트 4 라 이후 DOM 이 불변 — 종전 NodeList 캡처와 같은
     시점). 핸들러 본문(판정 위임·라벨 집행·재진술)은 전부 이 파일 소유다. ── */
  const attachments = [];

  /* 비동기 실패 최종 백스톱 — 지역 가드(디스패처 try/catch·.catch)를 빠뜨린 브리지
     rejection 이 조용한 무반응으로 증발하는 결함류(F8·F9·#45 profile_*·P2 onClick)가
     파일마다 반복 재발했다. 사이트별 규율 대신 셸에서 구조적으로 받는다: 여기 도달한
     rejection 은 "가드를 잊은 곳"뿐이며(지역에서 잡힌 실패는 오지 않는다) alert 로
     시끄럽게 재진술한다(confirm-or-alarm). 개별 화면의 맞춤 가드는 계속 1차 방어선. */
  attachments.push({
    target: window,
    type: "unhandledrejection",
    handler: (e) => {
      e.preventDefault();
      const r = e.reason;
      window.alert(String((r && r.message) || r));
    },
  });
  // 탭 클릭 — 「작업 에디터」 과도기 항목 사망(슬라이스 5)과 함께 tpl 탭은 제거됐다.
  navs.forEach((b) => attachments.push({
    target: b, type: "click", handler: () => go(b.dataset.scr),
  }));
  if (fontScaleToggle) {
    attachments.push({
      target: fontScaleToggle, type: "click", handler: () => Personalization.toggleFontScale(),
    });
  }
  attachments.push({
    target: window, type: "hwpx:personalizationchange", handler: syncPersonalizationLabels,
  });
  if (themeToggle && Theme) {
    attachments.push({ target: themeToggle, type: "click", handler: () => { Theme.toggle(); } });
    attachments.push({ target: window, type: "hwpx:themechange", handler: syncThemeLabel });
  }

  // 「기안」 master 폭 스플리터(S7) — 「문서 만들기」 좌 목록 사망 뒤 남는 유일 소비처지만
  // CSS 변수·설정값(`master_width`)은 그대로 공유 계약을 유지한다(F6 작업대 합류 지점).
  // 제스처 단위 add/remove 대칭이 이 리스너들의 수명주기라 React effect 로 옮기지 않는다 —
  // legacy DOM(.app) 위 집행이고 판정이 없다(패킷 §4.2 adapter 잔존).
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

  /* ── 부팅 시퀀스 서술 — 재생 시점(ready 사건 훅·선판정)은 ShellHost 소유, 목록·순서는
     여기가 세운다. pywebview.api 준비 후 실화면 초기화(브라우저 단독 미리보기에선 안 뜸 —
     정상). 재발화 시 재주행이 현 동작이고 멱등은 각 화면 init 의 wired 가드가 진다. ── */
  const initSequence = [
    () => { if (screens.library) screens.library.init(); },  // 「문서 작업」 라이브러리(F2 — 홈 승계)
    () => { if (screens.editor) screens.editor.init(); },
    () => { if (screens.job) screens.job.init(); },  // 「문서 만들기」(#90) — 유일 생성 표면
    () => { if (screens.workbench) screens.workbench.init(); },  // TXT 검토·복사 작업대(F6)
    // (「템플릿 관리」 화면은 사망(F8 §10.17) — tpl 채널 소비는 editor.js 구독이 잇는다.)
    // 데이터 선택 다이얼로그(재작성 F1) — 화면이 아니라 오버레이라 라우팅 대상이 아니지만
    // pool 관측 푸시의 구독자라 여기서 배선한다(구 PoolScreen.init 승계).
    () => { if (DataPicker) DataPicker.init(); },
  ];

  return {
    Nav,
    AppCloseGuard,
    /* React ShellHost 주입 서술 — 합성 루트가 그대로 bootReactRoot 로 넘긴다. catchUp 은
       부착 전에 지나간 사건의 만회다: 부팅 preferences 주입(hwpx:* 발화)이 effect 부착보다
       빠르면 라벨이 낡는다(#74 결함류) — 부착 직후 현재 상태를 한 번 재판독한다. */
    shellHost: {
      nav: shellNav,
      attachments,
      catchUp: [syncPersonalizationLabels, syncThemeLabel],
      boot: { win: window, hostReady: () => Bridge.hostReady(), initSequence },
    },
  };
}
