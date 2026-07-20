/* 빠른 기안 화면 — 작업의 휘발 쌍둥이(R-flow 블록 5, #90 슬라이스 7). 브리지로 링1
   QuickDraftViewModel 과 왕복. 렌더는 Python 이 window.__push('quickdraft', snapshot) 로
   밀어 넣는다(txt/job 관측 방향). 미리보기 채움 표지는 공유 SegView.paint(segview.js)로
   그린다 = 링1 render_segments 세그먼트 페인트, 웹은 토큰 정규식을 재구현하지 않는다.

   포커스 입력 보호(리뷰 확정, 슬라이스 4 stale 경합 클래스): 타이핑 액션(값 입력·원문 편집)은
   서버가 **푸시하지 않고 스냅샷을 반환**하고(_NO_PUSH), JS 가 그 스냅샷으로 **겨냥 패치**한다
   — 값 입력은 미리보기만, 원문 편집은 폼 패인만 재구성하고 포커스된 textarea 는 손대지 않는다.
   전면 재렌더(render)는 구조 액션(템플릿 선택·붙여넣기·탭 전환)에서만 돈다.

   PR-3: 데이터 이원(등록 데이터·임의 파일)·제스처 결속·표현형 3층. 데이터 표면은 **경량
   슬롯 + 행 스테퍼**다 — 필터·다중 선택 존(datazone.js)은 N 행 표면(txt 큐·작업)의 문법이라
   단건 표면에 들이지 않는다(결정 34 형상). 복사·휘발도 가드(PR-4)가 이 render 를 확장한다. */
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

  /* 파이프라인 2열(결정 34) — 소스(결속 열) → 표시형(프리셋). 데이터를 안 겨눴으면 소스
     칸 자체가 없다(고를 게 없는 드롭다운을 띄우지 않는다). */
  function pipeHtml(s, t, i) {
    if (!s.has_data) return "";
    const cols = (s.columns || []).map((c) =>
      `<option value="${esc(c)}"${c === t.col ? " selected" : ""}>${esc(c)}</option>`).join("");
    const fmts = ((s.fmt_options && s.fmt_options[t.fmt_kind]) || []).map((o) =>
      `<option value="${esc(o.code)}"${o.code === t.fmt_code ? " selected" : ""}>${esc(o.label)}</option>`).join("");
    // 표시형은 결속된 값에만 뜻이 있다 — 무결속 수기 값에 서식 드롭다운을 띄우면 아무 일도
    // 안 하는 손잡이가 된다(dead control 금지).
    const fmtSel = t.col
      ? `<select class="field sm qd-fmt" id="qdFmt-${i}" data-i="${i}" aria-label="${esc(t.name)} 표시형">${fmts}</select>`
      : "";
    const revert = t.state === "hand"
      ? `<button class="btn sm qd-revert" id="qdRevert-${i}" data-i="${i}">자동으로 되돌리기</button>`
      : "";
    return `<div class="qd-pipe"><span class="qd-elbow" aria-hidden="true">↳</span>` +
      `<select class="field sm qd-src" id="qdSrc-${i}" data-i="${i}" aria-label="${esc(t.name)} 데이터 열">` +
      `<option value="">(직접 입력)</option>${cols}</select>` +
      `${fmtSel}${revert}</div>`;
  }

  /* 근사 제안(결정 30) — 자동으로 붙지 않는다. 보이는 제안 + 원클릭이 규칙이다. */
  function suggestHtml(t, i) {
    if (!t.suggest || t.col) return "";
    return `<div class="qd-suggest"><span class="qd-elbow" aria-hidden="true">↳</span>` +
      `<span>「${esc(t.suggest)}」 열이 비슷합니다.</span>` +
      `<button class="btn sm" id="qdTake-${i}" data-i="${i}">이 열로 채우기</button></div>`;
  }

  function tokenRowHtml(s, t, i) {
    const empty = (t.value || "").trim() === "";
    return `<div class="qd-trow" data-i="${i}">` +
      `<div class="qd-trow-head">` +
      `<span class="qd-tname" title="{{${esc(t.name)}}}">{{${esc(t.name)}}}</span>` +
      `<span class="qd-chip ${t.state}" id="qdChip-${i}">${CHIP_LABEL[t.state] || ""}</span></div>` +
      pipeHtml(s, t, i) + suggestHtml(t, i) +
      `<div class="qd-vline"><span class="qd-elbow" aria-hidden="true">↳</span>` +
      `<textarea class="qd-val${empty ? " empty" : ""}" rows="1" id="qdVal-${i}" data-i="${i}"` +
      ` placeholder="입력" aria-label="${esc(t.name)} 값">${esc(t.value || "")}</textarea></div></div>`;
  }

  function formPaneHtml(s) {
    const rows = (s.tokens || []).map((t, i) => tokenRowHtml(s, t, i)).join("") ||
      `<p class="qd-formhint">토큰이 없는 템플릿입니다.</p>`;
    const hint = s.has_data
      ? `이름이 똑같은 열은 자동으로 붙습니다. 비슷하기만 한 열은 제안으로만 뜨니 확인하고 누르세요. 값을 직접 고치면 사람 소유가 되고 데이터가 바뀌어도 그대로 남습니다.`
      : `값을 직접 입력하면 사람 소유가 됩니다. 데이터를 겨누면 이름이 같은 자리가 자동으로 채워집니다.`;
    return `<h4>값 채우기</h4>${rows}<p class="qd-formhint">${hint}</p>`;
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

  /* 데이터 슬롯 — 겨눔 라벨 + 행 스테퍼(단건 표면의 행 재겨눔, 결정 32). 겨눔이 없으면
     라인은 비고 두 겨눔 버튼만 산다(dead 컨트롤 없음). */
  function syncData(s) {
    const line = $("qdDataLine");
    if (s.has_data) {
      const pos = `${(s.row_idx || 0) + 1} / ${s.record_count}행`;
      const label = s.row_label ? `<span class="qd-rowlabel">${esc(s.row_label)}</span>` : "";
      line.innerHTML = `<span class="qd-datalabel">${esc(s.data_source_label)}</span>` +
        `<button class="btn sm" id="qdRowPrev" aria-label="이전 행"${s.row_idx <= 0 ? " disabled" : ""}>◀</button>` +
        `<span class="qd-rowpos">${esc(pos)}</span>` +
        `<button class="btn sm" id="qdRowNext" aria-label="다음 행"${s.row_idx >= s.record_count - 1 ? " disabled" : ""}>▶</button>` +
        label;
    } else {
      line.innerHTML = `<span class="muted">선택한 데이터 없음</span>`;  // 사용자 어휘 = 「선택」(F15)
    }
    $("qdBtnClearData").classList.toggle("hidden", !s.has_data);
  }

  function warnNote(msg) {
    const el = $("qdNote");
    el.textContent = msg || "";
    el.classList.toggle("hidden", !msg);
  }

  /* 데이터 교체·해제·행 이동 전 고지(결정 32의 3분류) — 판정·문안은 Python 이 지금 만든다.
     결속·무수정 값은 조용히 재생성되므로 아무 말도 하지 않는다(무의미한 확인 금지). */
  async function carryOk(title, confirmLabel) {
    const g = await Bridge.call(SCREEN, "carry_notice", {});
    if (!g || !g.armed) return true;
    return window.Modal.confirm({
      title: title,
      body: g.message,
      confirmLabel: confirmLabel,
      cancelLabel: "머무르기",
    });
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
      syncData(s);
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
    syncRevert(s);
    setPill(s);
  }

  /* 강등의 출구를 제때 띄운다 — 결속 값을 손으로 고치는 순간 사람 소유로 강등되는데, 그
     타이핑 경로는 폼을 재구성하지 않으므로(포커스 보호) 「자동으로 되돌리기」가 다음 전면
     재렌더까지 안 보이면 되돌릴 길이 없는 강등이 된다(막다른 강등 금지, 결정 31). */
  function syncRevert(s) {
    (s.tokens || []).forEach((t, i) => {
      const pipe = document.querySelector('.qd-trow[data-i="' + i + '"] .qd-pipe');
      if (!pipe) return;
      const cur = $("qdRevert-" + i);
      if (t.state === "hand" && !cur) {
        const b = document.createElement("button");
        b.className = "btn sm qd-revert";
        b.id = "qdRevert-" + i;
        b.textContent = "자동으로 되돌리기";
        b.addEventListener("click", () => Bridge.call(SCREEN, "revert_token", { name: t.name }));
        pipe.appendChild(b);
      } else if (t.state !== "hand" && cur) {
        cur.remove();
      }
    });
  }

  function wireFormRows(s) {
    (s.tokens || []).forEach((t, i) => {
      // 결속·표현형 손잡이(구조 액션) — 서버가 푸시해 전면 재렌더한다(값 입력과 달리
      // 포커스 중인 입력이 없다).
      const src = $("qdSrc-" + i);
      if (src) src.addEventListener("change", () =>
        Bridge.call(SCREEN, "set_source", { name: t.name, col: src.value }));
      const fmt = $("qdFmt-" + i);
      if (fmt) fmt.addEventListener("change", () =>
        Bridge.call(SCREEN, "set_fmt", { name: t.name, code: fmt.value }));
      const take = $("qdTake-" + i);
      if (take) take.addEventListener("click", () =>
        Bridge.call(SCREEN, "set_source", { name: t.name, col: t.suggest }));
      const rev = $("qdRevert-" + i);
      if (rev) rev.addEventListener("click", () =>
        Bridge.call(SCREEN, "revert_token", { name: t.name }));
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
          // 결속 토큰을 손으로 고치면 사람 소유 강등(hand) — 무결속은 man/blank.
          const st = t.col ? "hand" : (emptyNow ? "blank" : "man");
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

    // ---- 데이터 겨눔(결정 34의 데이터 소스 이원) — 두 유래가 같은 고지 가드를 지난다.
    $("qdBtnPickFile").addEventListener("click", async () => {
      warnNote("");
      if (!(await carryOk("데이터 바꾸기 확인", "데이터 바꾸기"))) return;
      let r = await Bridge.pickDataFile(SCREEN);
      if (r && typeof r === "object" && r.needs_sheet) {   // 다중 시트 → 확정 게이트(#33)
        r = await SheetPicker.choose(SCREEN, r);
        if (r === null) return;                            // 취소 = 중단(첫 시트 강등 없음)
      }
      if (r === null) return;
      if (typeof r === "string" && r.startsWith("ERROR:")) { warnNote(r.slice(6).trim()); return; }
      // 라벨·행 수는 load_data_path 가 민 스냅샷이 채운다(P4 서버 소유).
    });
    $("qdBtnPoolData").addEventListener("click", async () => {
      warnNote("");
      if (!(await carryOk("데이터 바꾸기 확인", "데이터 바꾸기"))) return;
      await PoolPicker.choose(SCREEN);  // 실패 재진술은 피커 모달 안에서(공용 관문 문구)
    });
    $("qdBtnClearData").addEventListener("click", async () => {
      warnNote("");
      if (!(await carryOk("데이터 해제 확인", "데이터 해제"))) return;
      Bridge.call(SCREEN, "clear_data", {});
    });
    // 행 스테퍼는 매 렌더 새로 그려지므로 슬롯에 위임 배선한다(리스너 누수·유실 방지).
    $("qdDataLine").addEventListener("click", async (e) => {
      const prev = e.target.closest && e.target.closest("#qdRowPrev");
      const next = e.target.closest && e.target.closest("#qdRowNext");
      if (!prev && !next) return;
      if (!LAST || !LAST.has_data) return;
      const idx = (LAST.row_idx || 0) + (next ? 1 : -1);
      if (idx < 0 || idx >= LAST.record_count) return;
      if (!(await carryOk("행 바꾸기 확인", "행 바꾸기"))) return;
      Bridge.call(SCREEN, "set_row", { index: idx });
    });
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
