/* 그룹 목록 공용 팩토리 — 부유 ⋮ 메뉴 위치잡기.

   원래 이 파일은 기제 셋(메뉴 위치잡기 · 접힘 즉답 토글 · 그룹 이동 다이얼로그)을 들었다.
   손수 2벌이던 것을 한 곳으로 걷은 자리였고, 소비 표면이 여럿이라 id 를 cfg 로 받았다.

   R4-01(#414)이 라이브러리를, R4-02(#415)가 편집기를 React 로 옮기면서 그중 둘의 마지막
   소비자가 사라졌다:

   - `toggleGroup`/`setGroupExpanded`(접힘 즉답) → 라이브러리 React 표면이 같은 규율
     (낙관 반영 → 실패 시 되돌림 + loud)을 자기 안에 진다.
   - `createMoveDialog`(그룹 이동) → `src/screens/group_move_dialog.ts` 가 후계다. 라이브러리
     쪽 짝은 #414 의 `LibraryMoveDialog` 다.

   남은 것은 `createMenu` 하나다 — React 라이브러리·편집기 **둘 다** 이 위치잡기를 계속
   소비한다(내용·정체는 화면이 만들고, 위치·표시/숨김만 여기가 소유). 그 마지막 소비자까지
   걷는 것은 #417 의 몫이고, 그때 이 파일이 사라진다.

   바깥닫기(Popover.wireDismiss)는 화면이 자기 술어로 직접 배선한다 — menuFor 정체가 화면
   소유라 여기서 대신 들지 않는다(표면별 suppress 인스턴스 원칙 유지). */

import { Popover } from "./popover.js";

const $ = (id) => document.getElementById(id);

/* 부유 ⋮ 메뉴(.ctx-menu) — 내용·정체는 화면이 만들고, 위치·표시/숨김만 팩토리가 소유. */
function createMenu(cfg) {
  function show(html, btn) {
    const m = $(cfg.menuId);
    m.innerHTML = html;
    // .ctx-menu 는 display 미지정 div — block 로 노출(job 은 "", tpl 은 "block" 를 쓰던 걸
    // 통일; 둘 다 CSS 기본이 block 라 결과 동형). 측정 전에 보여야 offsetHeight 가 잡힌다.
    m.style.display = "block";
    // 표시 뒤 getBoundingClientRect 실폭·실높이로 clamp/flip한다. width 상수나 렌더 전
    // offset 추정은 긴 지역화 문안에서 우측 돌출을 만들므로 공용 팝오버 배치기에 맡긴다.
    Popover.place(m, btn);
    const first = m.querySelector("button");
    if (first) first.focus();
  }
  function hide() {
    const m = $(cfg.menuId);
    m.style.display = "none";
    m.innerHTML = "";
  }
  return { show, hide };
}

export const GroupList = { createMenu };
