/* 세션 가드 재진술 공유 합성기(블록 4, 결정 26·27) — 「작업」 T1 과 txt T3 의 공용 문안 조각.

   술어·수치는 Python(_selection_guard)이 판정하고, 여기는 **그 수치를 문장으로 만드는 한 줄**만
   소유한다. 화면마다 따로 조립하면 같은 가드 상태에 대해 두 모달이 다른 문안을 말하는 드리프트가
   생긴다(job.js 재진술 블록이 이미 경고한 클래스 — 리뷰 F6). 전이 종류별 문안(무엇이 사라지는가)은
   화면이 이 조각 위에 얹는다. */
(function () {
  /* 선택 재진술 한 줄 — 필터가 서 있으면 정의 안팎을 나눠 말한다(정의-유래인지 수작업인지가
     사용자에게 보이도록). 화면 재진술 블록과 가드 모달이 같은 함수를 통과한다. */
  function selectionLine(count, filterActive, inDef, extra) {
    return filterActive
      ? `직접 선택 ${count}행 (정의 매치 ${inDef} · 정의 밖 ${extra})`
      : `직접 선택 ${count}행`;
  }

  window.Guard = { selectionLine };
})();
