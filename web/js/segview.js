/* 공유 채움 표지 세그먼트 페인터 — 링1 render_segments(결정 22·33) 삼분 사영의 단일 표면.
   txt 작업점 카드와 빠른 기안 미리보기가 **같은 계약**(fill 음영·blank 〈빈 값〉·missing
   {{토큰}} 빨강)을 그리므로 페인터를 한 곳에 둔다 — 두 벌 손복사가 어긋나면(seg 어휘·마크업
   변경 시 한쪽만 낡음) 두 화면 미리보기가 조용히 발산한다(파생경계 번역오류의 화면 판).
   웹은 토큰 정규식을 재구현하지 않는다: 서버가 보낸 세그먼트를 그리기만 한다. */
(function () {
  const esc = window.escHtml;
  /* owners(선택) = {토큰이름: 소유 상태} 맵. 넘기면 fill 세그먼트에 own-* 클래스를 얹어
     **누가 채웠는지**를 색으로 가른다(빠른 기안 소유권 색, 결정 33 — 자동 결속 vs 직접
     수정 vs 무결속 수기). 안 넘기면(txt 카드) 종전 그대로 — 하위호환이라 txt 는 무변경.
     소유권 판정은 서버(토큰 state)라 여긴 클래스만 입힌다(파생 판정 금지). */
  function paint(segments, owners) {
    return (segments || []).map((s) => {
      if (s.kind === "fill") {
        const own = owners && s.name ? owners[s.name] : "";
        const cls = own ? `seg-fill own-${own}` : "seg-fill";
        return `<span class="${cls}">${esc(s.text)}</span>`;
      }
      if (s.kind === "blank")
        return `<span class="seg-blank" title="{{${esc(s.name)}}} — 빈 값">〈빈 값〉</span>`;
      if (s.kind === "missing") return `<span class="seg-missing">${esc(s.text)}</span>`;
      return esc(s.text);  // literal — 원문 그대로
    }).join("");
  }
  /* 클립보드 평문(표지 없는 원본) — 세그먼트 텍스트 이어붙임 = 서버 render_record 불변식.
     표지 토글 OFF 미리보기가 "복사되는 그대로"를 보여줄 때 쓴다(음영 없는 순수 텍스트). */
  function plain(segments) {
    return (segments || []).map((s) => s.text).join("");
  }
  window.SegView = { paint, plain };
})();
