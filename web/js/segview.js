/* 공유 채움 표지 세그먼트 페인터 — 링1 render_segments(결정 22·33) 삼분 사영의 단일 표면.
   txt 작업점 카드와 빠른 기안 미리보기가 **같은 계약**(fill 음영·blank 〈빈 값〉·missing
   {{토큰}} 빨강)을 그리므로 페인터를 한 곳에 둔다 — 두 벌 손복사가 어긋나면(seg 어휘·마크업
   변경 시 한쪽만 낡음) 두 화면 미리보기가 조용히 발산한다(파생경계 번역오류의 화면 판).
   웹은 토큰 정규식을 재구현하지 않는다: 서버가 보낸 세그먼트를 그리기만 한다. */
(function () {
  const esc = window.escHtml;
  function paint(segments) {
    return (segments || []).map((s) => {
      if (s.kind === "fill") return `<span class="seg-fill">${esc(s.text)}</span>`;
      if (s.kind === "blank")
        return `<span class="seg-blank" title="{{${esc(s.name)}}} — 빈 값">〈빈 값〉</span>`;
      if (s.kind === "missing") return `<span class="seg-missing">${esc(s.text)}</span>`;
      return esc(s.text);  // literal — 원문 그대로
    }).join("");
  }
  window.SegView = { paint };
})();
