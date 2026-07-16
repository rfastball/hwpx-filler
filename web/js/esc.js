/* 공유 HTML 이스케이퍼 — modal.js·preserve.js 와 같은 결의 window 스코프 헬퍼.

   각 화면·피커가 복붙해 쓰던 동일 3줄 이스케이퍼 9사본(home·txt·editor·run·matrix·
   template·pool·sheet_picker·pool_picker)을 한 곳으로 모은다. innerHTML 로 조립되는
   문자열에 사용자·파일 유래 값을 끼울 때 반드시 이걸 태운다.

   escape 대상은 & < > " 네 글자 — 텍스트 노드와 큰따옴표 속성값 양쪽에서 안전한
   초집합이다(txt.js 만 " 를 빼고 있었는데 title="…"·value="…" 속성에도 쓰이고
   있어 따옴표 포함 값이 속성을 깨는 잠복 결함이었다 — 통일하며 봉합). */
(function () {
  function escHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  window.escHtml = escHtml;
})();
