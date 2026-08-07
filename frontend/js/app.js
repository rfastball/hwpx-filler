/* 셸 adapter — 판정은 상태기계(src/shell/nav.ts), 화면 전환 집행은 R4-04의
   ProductScreenExecutor가 진다. 이 파일은 전역 도구와 셸 리스너의 서술만 남긴다.
   R3-02(#411)가 셸을 셋으로 갈랐다:

   - **판정** — 현재 화면·몰입 이탈 위임·ready 게이트·재당김 규약·닫기 직렬화는 상태기계
     하나가 소유한다. 이 파일이 판정을 재조립하면 그것이 경계 위반이다(같은 상태를 두 곳이
     판정하지 않는다).
   - **수명주기** — 셸 리스너 부착/해제와 부팅 시퀀스(ready 사건 → init 5)는 React
     ShellHost 가 소유한다. 이 파일은 대상·핸들러를 구성 시 캡처해 **서술**(`shellHost`)로
     넘긴다 — 그래서 재초기화가 리스너를 복제하지 않는 계약이 effect 대칭 해제로 선다.
   - **집행** — 화면 visibility·focus·scroll·refresh는 ProductScreenExecutor가, 닫기 확인의
     브리지 발신·문안과 스플리터 제스처는 이 adapter가 진다.

   `shellNav` 는 합성 루트가 구성한 상태기계다. `Theme`·`Personalization`은 factory 산물
   주입이고 `Modal`은 named export를 직접 import한다. */

import { Modal } from "./modal.js";
import { DEFAULT_SCREEN } from "../src/shell/nav.ts";

export function createAppShell({ Bridge, Theme, Personalization, shellNav, initSequence }) {
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
  const Nav = { go, refresh, currentScreen: () => shellNav.currentScreen() };
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

  /* ── 셸 리스너 서술 — 부착/해제 수명주기는 React ShellHost 소유(R3-02). 정적 2탭은
     구성 시점에 캡처하고, 핸들러 본문은 판정 위임·라벨 집행·재진술만 한다. ── */
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
