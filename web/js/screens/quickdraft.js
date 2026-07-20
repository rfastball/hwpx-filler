/* 빠른 기안 화면 — 작업의 휘발 쌍둥이(R-flow 블록 5, #90 슬라이스 7). 브리지로 링1
   QuickDraftViewModel 과 왕복. 렌더는 Python 이 window.__push('quickdraft', snapshot) 로
   밀어 넣는다(txt/job 관측 방향). 미리보기 채움 표지는 공유 SegView.paint(segview.js)로
   그린다 = 링1 render_segments 세그먼트 페인트, 웹은 토큰 정규식을 재구현하지 않는다.

   포커스 입력 보호(리뷰 확정, 슬라이스 4 stale 경합 클래스): 타이핑 액션(값 입력·원문 편집)은
   서버가 **푸시하지 않고 스냅샷을 반환**하고(_NO_PUSH), JS 가 그 스냅샷으로 **겨냥 패치**한다
   — 값 입력은 미리보기만, 원문 편집은 폼 패인만 재구성하고 포커스된 textarea 는 손대지 않는다.
   전면 재렌더(render)는 구조 액션(템플릿 선택·붙여넣기·탭 전환)에서만 돈다.

   PR-2: 템플릿 소스·파이프라인 토큰 폼·미리보기 2판. 데이터 이원·제스처 결속(PR-3), 복사·
   휘발도 가드(PR-4)는 이 render 를 확장한다 — 없는 걸 있는 척하지 않는다. */
(function () {
  const SCREEN = "quickdraft";
  const $ = (id) => document.getElementById(id);
  const esc = window.escHtml;
  // 토큰 폼 칩 상태어 — Python(_token_state)이 판정한 상태에 한글 문안만 입힌다(파생 판정 금지).
  const CHIP_LABEL = { auto: "자동", hand: "직접 수정", man: "직접 입력", blank: "비어 있음" };
  let LAST = null;
  let TEMPLATES = [];   // 슬롯 드롭다운용 라이브러리 이름 — initial 에서 채움
  let tab = "preview";  // 우측 판 탭(미리보기/원문 편집) = 순수 뷰 상태(클라이언트 소유)

  // 내용 크기 칩(결정 34) — field-sizing 지원(Chromium 123+/WebView2)이면 CSS 가 폭·높이를
  // 다 맡고, 미지원 폴백에서만 JS 로 높이를 보정한다(값이 여러 줄이어도 잘리지 않게).
  const FIELD_SIZING = typeof CSS !== "undefined" && CSS.supports && CSS.supports("field-sizing", "content");
  function autoGrow(el) {
    if (FIELD_SIZING || !el) return;
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
  }
  function growAll() {
    if (FIELD_SIZING) return;
    const vs = document.querySelectorAll("#qdFormPane .qd-val");
    for (let i = 0; i < vs.length; i++) autoGrow(vs[i]);
  }

  /* 텍스트 입력 디바운스 dispatch — 타건마다 서버 왕복은 낭비라 멈춤(≈180ms) 후 전체 값을
     보낸다(증분 아님 = 멱등). 값 유실 경합은 _NO_PUSH+겨냥 패치가 막고(포커스 입력 미재구성),
     디바운스는 왕복 빈도만 줄인다. */
  let debTimer = null, debFn = null;
  function debounce(fn) {
    debFn = fn;
    if (debTimer) clearTimeout(debTimer);
    debTimer = setTimeout(() => { debTimer = null; const f = debFn; debFn = null; if (f) f(); }, 180);
  }
  function flushDebounce() {
    if (debTimer) { clearTimeout(debTimer); debTimer = null; }
    const f = debFn; debFn = null; if (f) f();
  }

  function tokenRowHtml(t, i) {
    const empty = (t.value || "").trim() === "";
    return `<div class="qd-trow" data-i="${i}">` +
      `<div class="qd-trow-head">` +
      `<span class="qd-tname" title="{{${esc(t.name)}}}">{{${esc(t.name)}}}</span>` +
      `<span class="qd-chip ${t.state}" id="qdChip-${i}">${CHIP_LABEL[t.state] || ""}</span></div>` +
      `<div class="qd-vline"><span class="qd-elbow" aria-hidden="true">↳</span>` +
      `<textarea class="qd-val${empty ? " empty" : ""}" rows="1" id="qdVal-${i}" data-i="${i}"` +
      ` placeholder="입력" aria-label="${esc(t.name)} 값">${esc(t.value || "")}</textarea></div></div>`;
  }

  function formPaneHtml(s) {
    const rows = (s.tokens || []).map(tokenRowHtml).join("") ||
      `<p class="qd-formhint">토큰이 없는 템플릿입니다.</p>`;
    return `<h4>값 채우기</h4>${rows}` +
      `<p class="qd-formhint">값을 직접 입력하면 사람 소유가 됩니다. 데이터 결속은 준비 중입니다.</p>`;
  }

  function rightPaneHtml(s) {
    const right = tab === "source"
      ? `<textarea class="qd-srcedit" id="qdSrc" aria-label="템플릿 원문">${esc(s.template_text)}</textarea>` +
        `<p class="qd-prevnote">여기서 고친 템플릿은 이 세션의 사본입니다. 라이브러리는 바뀌지 않습니다.</p>`
      : `<pre class="wc-render f-malgun" id="qdRender">${window.SegView.paint(s.segments)}</pre>` +
        `<p class="qd-prevnote">이대로 복사됩니다. 파란 음영은 채운 자리 표지로, 화면에만 보이고 복사되지 않습니다.</p>`;
    return `<div class="qd-prevhead"><div class="qd-tabs">` +
      `<button class="btn sm" id="qdTabPrev" aria-pressed="${tab !== "source"}">미리보기</button>` +
      `<button class="btn sm" id="qdTabSrc" aria-pressed="${tab === "source"}">원문 편집</button>` +
      `</div></div>${right}`;
  }

  function bodyHtml(s) {
    if (!s.template_text) {
      return `<div class="qd-emptywrap">` +
        `<div class="qd-dircard"><h4>라이브러리에서 시작</h4>` +
        `<p>저장된 템플릿을 골라 값만 채웁니다. 템플릿은 바뀌지 않습니다.</p>` +
        `<button class="btn" id="qdEmA">템플릿 고르기</button></div>` +
        `<div class="qd-dircard"><h4>붙여넣기로 시작</h4>` +
        `<p>메신저나 문서에서 받은 서식을 붙여 넣습니다. 라이브러리에 저장되지 않습니다.</p>` +
        `<button class="btn" id="qdEmB">붙여넣기…</button></div></div>`;
    }
    return `<div class="qd-2pane">` +
      `<div class="qd-formpane" id="qdFormPane">${formPaneHtml(s)}</div>` +
      `<div class="qd-prevpane" id="qdRightPane">${rightPaneHtml(s)}</div></div>`;
  }

  function syncSlot(s) {
    const sel = $("qdTplSel");
    const pseudo = s.origin === "paste";
    let opts = `<option value="">(템플릿 선택)</option>`;
    TEMPLATES.forEach((n) => {
      const isCur = !pseudo && !s.modified && s.template_name === n;
      opts += `<option value="${esc(n)}"${isCur ? " selected" : ""}>${esc(n)}</option>`;
    });
    if (pseudo) opts += `<option value="__pasted" selected>(붙여넣은 텍스트)</option>`;
    else if (s.modified) opts += `<option value="__mod" selected>${esc(s.template_name || "")} (수정됨)</option>`;
    sel.innerHTML = opts;
  }

  function setPill(s) {
    const pill = $("qdStatus");
    if (!s.template_text) { pill.dataset.level = "idle"; pill.textContent = "세션 휘발 · 저장 없음"; return; }
    const un = s.unfilled_count || 0;
    if (un) { pill.dataset.level = "warn"; pill.textContent = `미채움 ${un}`; }
    else { pill.dataset.level = "ok"; pill.textContent = "전량 채움"; }
  }

  /* 재렌더 전에 포커스 textarea 의 현재 DOM 값을 LAST 로 흡수 — 디바운스가 아직 서버에 안
     보낸 마지막 글자가 전면 재렌더(탭 전환 등)에서 옛 스냅샷 값으로 되돌아가지 않게. */
  function syncEditsIntoLast() {
    if (!LAST || !LAST.tokens) return;
    LAST.tokens.forEach((t, i) => { const v = $("qdVal-" + i); if (v) t.value = v.value; });
    const src = $("qdSrc");
    if (src) LAST.template_text = src.value;
  }

  /* 전면 재렌더 — 구조 액션(템플릿 선택·붙여넣기·탭 전환·부팅)에서만. 포커스·캐럿·스크롤
     보존(#28)으로 감싼다. 타이핑 액션은 이 경로를 타지 않는다(겨냥 패치 = patchForm/patchRight). */
  function render(s) {
    Preserve.around(() => {
      LAST = s;
      syncSlot(s);
      $("qdBody").innerHTML = bodyHtml(s);
      wireBody(s);
      setPill(s);
      growAll();
    });
  }

  /* 겨냥 패치 — 원문 편집(edit_source): 폼 패인만 재구성(토큰 셋 변화 반영)하고 포커스된
     원문 textarea(우 패인)는 손대지 않는다. */
  function patchForm(s) {
    LAST = s;
    syncSlot(s);
    const pane = $("qdFormPane");
    if (pane) { pane.innerHTML = formPaneHtml(s); wireFormRows(s); growAll(); }
    setPill(s);
  }

  /* 겨냥 패치 — 값 입력(set_token): 미리보기만 갱신하고 포커스된 값 textarea(폼)는 손대지 않는다. */
  function patchRight(s) {
    LAST = s;
    const pre = $("qdRender");  // 미리보기 모드에서만 존재(원문 편집 탭이면 없음 → no-op)
    if (pre) pre.innerHTML = window.SegView.paint(s.segments);
    setPill(s);
  }

  function wireFormRows(s) {
    (s.tokens || []).forEach((t, i) => {
      const val = $("qdVal-" + i);
      if (!val) return;
      val.addEventListener("input", () => {
        // 낙관적 표지(값 공백 여부만 — 치환 재구현 아님): 칩·빈칸·알약을 즉시 갱신하고,
        // 미리보기 갱신은 반환 스냅샷 patchRight 가 맡는다(판정은 Python, JS는 문안만).
        const emptyNow = val.value.trim() === "";
        val.classList.toggle("empty", emptyNow);
        autoGrow(val);
        const chip = $("qdChip-" + i);
        if (chip) {
          const st = emptyNow ? "blank" : "man";
          chip.className = "qd-chip " + st;
          chip.textContent = CHIP_LABEL[st];
        }
        const un = document.querySelectorAll("#qdFormPane .qd-val.empty").length;
        const pill = $("qdStatus");
        if (un) { pill.dataset.level = "warn"; pill.textContent = `미채움 ${un}`; }
        else { pill.dataset.level = "ok"; pill.textContent = "전량 채움"; }
        debounce(() => Bridge.call(SCREEN, "set_token", { name: t.name, text: val.value })
          .then(patchRight));
      });
      val.addEventListener("blur", flushDebounce);  // 포커스 이탈 시 대기 편집 즉시 반영
    });
  }

  function wireBody(s) {
    if (!s.template_text) {
      const a = $("qdEmA"), b = $("qdEmB");
      if (a) a.addEventListener("click", () => $("qdTplSel").focus());  // 정직: 드롭다운으로 고르게
      if (b) b.addEventListener("click", openPaste);
      return;
    }
    wireFormRows(s);
    const src = $("qdSrc");
    if (src) {
      src.addEventListener("input", () =>
        debounce(() => Bridge.call(SCREEN, "edit_source", { text: src.value }).then(patchForm)));
      src.addEventListener("blur", flushDebounce);
    }
    const tp = $("qdTabPrev"), ts = $("qdTabSrc");
    // 탭 전환은 전면 재렌더 — 편집 중이었다면 DOM 값을 LAST 로 흡수한 뒤 바꿔 마지막 글자 보존.
    if (tp) tp.addEventListener("click", () => { syncEditsIntoLast(); tab = "preview"; render(LAST); });
    if (ts) ts.addEventListener("click", () => { syncEditsIntoLast(); tab = "source"; render(LAST); });
  }

  function openPaste() {
    $("qdPasteText").value = (LAST && LAST.origin === "paste") ? LAST.template_text : "";
    window.Modal.open("qdPasteModal", { initialFocus: $("qdPasteText") });
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. 슬롯·붙여넣기 모달은 여기서 1회 배선. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    $("qdTplSel").addEventListener("change", (e) => {
      const v = e.target.value;
      if (v === "" || v === "__pasted" || v === "__mod") return;  // 안내·의사 옵션은 무동작
      Bridge.call(SCREEN, "select_template", { name: v });
    });
    $("qdBtnPaste").addEventListener("click", openPaste);
    $("qdPasteCancel").addEventListener("click", () => window.Modal.close("qdPasteModal"));
    $("qdPasteOk").addEventListener("click", () => {
      Bridge.call(SCREEN, "paste_template", { text: $("qdPasteText").value });
      window.Modal.close("qdPasteModal");
    });
    const initState = await Bridge.initial(SCREEN);
    TEMPLATES = initState.templates || [];
    render(initState);
  }

  window.QuickDraftScreen = { init };
})();
