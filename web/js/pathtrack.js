/* 추적성 로케이트 공용 컴포넌트(#53-B) — 열기·폴더에서 보기·경로 복사.
   화면-불가지: PathTrack.affordances(path) 로 버튼 HTML 을 만들고, 문서 레벨 위임
   핸들러가 data-track-act 를 Bridge 로 라우팅한다(각 화면이 재렌더해도 위임이라 안전).
   경로 검증은 백엔드 화이트리스트(app.py _validate_owned)가 소유 — 프론트는 표현만. */
(function () {
  const esc = window.escHtml;
  const ACTS = {
    open:   { label: "열기",        fn: (p) => Bridge.openPath(p) },
    reveal: { label: "폴더에서 보기", fn: (p) => Bridge.revealPath(p) },
    copy:   { label: "경로 복사",     fn: (p) => Bridge.copyPath(p) },
  };

  /* path 를 로케이트 버튼 묶음 HTML 로. 전체경로는 title 툴팁. path 없으면 "".
     opts.only = 표시할 액션 배열. 기본은 열기·폴더보기 2개(F29) — 「경로 복사」는
     「폴더에서 보기」와 중복 어포던스라 기본에서 빼고, 경로 텍스트가 실제로 필요한
     곳(예: 실행 화면 저장 폴더)만 only 로 명시해 살린다. */
  function affordances(path, opts) {
    if (!path) return "";
    const which = (opts && opts.only) || ["open", "reveal"];
    const btns = which.map((k) =>
      `<button type="button" class="btn sm track-btn" data-track-act="${k}"` +
      ` data-path="${esc(path)}" title="${esc(path)}">${ACTS[k].label}</button>`
    ).join("");
    return `<span class="track-affords" title="${esc(path)}">${btns}</span>`;
  }

  async function onClick(e) {
    const el = e.target.closest("[data-track-act]");
    if (!el) return;
    const spec = ACTS[el.dataset.trackAct];
    const path = el.dataset.path;
    if (!spec || !path) return;
    try {
      const r = await spec.fn(path);
      if (typeof r === "string" && r.startsWith("ERROR:")) {
        window.alert(r.slice(6).trim());   // 소유 밖·죽은 참조 등 시끄럽게
      } else if (el.dataset.trackAct === "copy") {
        const old = el.textContent;        // 복사 성공 잠깐 표시(비파괴)
        el.textContent = "복사됨 ✓";
        setTimeout(() => { el.textContent = old; }, 1200);
      }
    } catch (err) {
      window.alert(String((err && err.message) || err));
    }
  }

  document.addEventListener("click", onClick);  // 위임 1회 부착(화면 재렌더 무관)
  window.PathTrack = { affordances };
})();
