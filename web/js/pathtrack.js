/* 추적성 로케이트 공용 컴포넌트(#53-B) — 열기·폴더에서 보기·경로 복사.
   화면-불가지: PathTrack.affordances(path) 로 버튼 HTML 을 만들고, 문서 레벨 위임
   핸들러가 data-track-act 를 Bridge 로 라우팅한다(각 화면이 재렌더해도 위임이라 안전).
   경로 검증은 백엔드 화이트리스트(app.py _validate_owned)가 소유 — 프론트는 표현만. */
(function () {
  const esc = window.escHtml;
  const ICONS = {
    open: '<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="M11 3h6v6M17 3l-8 8"/><path d="M15 11v5H4V5h5"/></svg>',
    reveal: '<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="M2.5 6.5h6l1.5 2h7.5v7.5h-15z"/><path d="M2.5 6.5v-2h5l1.5 2"/></svg>',
    copy: '<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false"><rect x="7" y="7" width="9" height="9" rx="1"/><path d="M5 13H4V4h9v1"/></svg>',
    done: '<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="M4 10l4 4 8-9"/></svg>',
  };
  const ACTS = {
    open:   { label: "열기", icon: ICONS.open, fn: (p) => Bridge.openPath(p) },
    reveal: { label: "폴더에서 보기", icon: ICONS.reveal, fn: (p) => Bridge.revealPath(p) },
    copy:   { label: "경로 복사", icon: ICONS.copy, fn: (p) => Bridge.copyPath(p) },
  };

  /* path 를 로케이트 버튼 묶음 HTML 로. 전체경로는 title 툴팁. path 없으면 "".
     opts.only = 표시할 액션 배열. 기본은 열기·폴더보기 2개(F29) — 「경로 복사」는
     「폴더에서 보기」와 중복 어포던스라 기본에서 빼고, 경로 텍스트가 실제로 필요한
     곳(예: 실행 화면 저장 폴더)만 only 로 명시해 살린다. */
  function affordances(path, opts) {
    if (!path) return "";
    const which = (opts && opts.only) || ["open", "reveal"];
    // 버튼 title 에도 전체 경로를 병기한다(#264 리뷰) — 아이콘 버튼 위에선 버튼 자신의
    // title 이 부모 .track-affords 의 경로 title 을 가려, 경로 텍스트를 안 그리는 호출부
    // (풀 카드 등)에서 전체 경로가 발견 불가능해진다(full-path-tooltip 계약 위반).
    const btns = which.map((k) => {
      const spec = ACTS[k];
      return `<button type="button" class="btn sm icon track-btn" data-track-act="${k}"` +
        ` data-path="${esc(path)}" title="${spec.label} — ${esc(path)}"` +
        ` aria-label="${spec.label}">${spec.icon}</button>`;
    }).join("");
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
        const old = el.innerHTML;          // 아이콘 급을 유지한 채 복사 성공을 잠깐 재진술
        el.innerHTML = ICONS.done;
        el.setAttribute("aria-label", "복사됨");
        el.setAttribute("title", "복사됨");
        setTimeout(() => {
          el.innerHTML = old;
          el.setAttribute("aria-label", spec.label);
          // 라벨만으로 되돌리면 첫 복사 이후 경로 툴팁이 재렌더까지 사라진다(#280 리뷰)
          // — 생성 시와 같은 「라벨 — 경로」 형태로 복원한다.
          el.setAttribute("title", `${spec.label} — ${path}`);
        }, 1200);
      }
    } catch (err) {
      window.alert(String((err && err.message) || err));
    }
  }

  document.addEventListener("click", onClick);  // 위임 1회 부착(화면 재렌더 무관)
  window.PathTrack = { affordances };
})();
