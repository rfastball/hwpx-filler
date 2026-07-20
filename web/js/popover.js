/* 팝오버 바깥-닫기 공용 헬퍼 — 바깥 pointerdown=닫기+그 클릭 1회 소비, Escape=닫기.
   PR-2a 리뷰: 행/그룹 ⋮ 메뉴(job.js)와 열 필터 패널(datazone.js)이 같은 기제를 손수
   2벌 들고 있었다 — modal.js 가 다이얼로그 개폐를 중앙화하듯 기제를 단일 출처로 걷고,
   표면별로 is-open 술어·inside 판정·close 만 주입받는다.

   호출마다 자기 suppress 플래그·리스너를 갖는 인스턴스가 선다 — 표면끼리 상태를 공유하지
   않는다(교차 소거 금지). 같은 document 노드의 capture 리스너끼리는 stopPropagation 에
   서로 막히지 않고 preventDefault 는 멱등이라, 두 표면이 같은 클릭을 각자 소비해도
   겹침이 무해하다. Escape 닫기는 소비하지 않는다(클릭이 아니므로 샐 동사가 없다). */
(function () {
  /** cfg: { isOpen(), contains(target), close() } — 열려 있고 바깥이면 close+소비. */
  function wireDismiss(cfg) {
    let suppressNextClick = false;
    // 닫기 제스처의 click 을 캡처 단계에서 1회 소비 — 닫기와 그 클릭의 원래 동사(행
    // 토글·버튼 실행)가 한 클릭에 겹치지 않게(작업 화면 리뷰 #3에서 실증된 결함 클래스).
    document.addEventListener("click", (e) => {
      if (suppressNextClick) {
        suppressNextClick = false;
        e.stopPropagation();
        e.preventDefault();
      }
    }, true);
    document.addEventListener("pointerdown", (e) => {
      if (!cfg.isOpen()) return;
      if (cfg.contains(e.target)) return;
      cfg.close();
      suppressNextClick = true;
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && cfg.isOpen()) cfg.close();
    });
  }

  window.Popover = { wireDismiss };
})();
