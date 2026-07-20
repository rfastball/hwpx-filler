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
  let markers = true;   // 채움 표지(음영·소유권 색) 켜짐 = 순수 뷰 상태(클라이언트 소유).
                        // 끄면 미리보기가 "복사되는 그대로"의 순수 평문이 된다(결정 33).
  let pendingNote = ""; // 다음 렌더에 실을 고지(유지되는 수기 값 등) — 가드가 채운다
  /* 렌더 세대 — 구조 변화(행 이동·데이터 교체·템플릿 전환)가 나면 올라간다. 타이핑 왕복이
     늦게 착지해 **옛 세대의 스냅샷**으로 미리보기·LAST 를 되돌리는 경합을 막는다(늦은 응답이
     행 1의 화면에 행 0의 본문을 그리는 결함). */
  let EPOCH = 0;

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
     디바운스는 왕복 빈도만 줄인다.

     대기 중인 편집은 **정산 가능**해야 한다: 가드(carry_notice)는 Python 이 지금 판정하는데,
     아직 안 보낸 타건이 남아 있으면 서버는 옛 상태를 보고 "고친 값 없음"이라 답해 확인이
     통째로 침묵한다(고효율 리뷰). 그래서 flush 는 진행 중 왕복의 프로미스를 돌려주고,
     제스처는 그걸 기다린 뒤에 판정을 묻는다. */
  let debTimer = null, debFn = null, debPending = null;
  function run(f) {
    const p = Promise.resolve(f());
    debPending = p;
    return p.finally(() => { if (debPending === p) debPending = null; });
  }
  function debounce(fn) {
    debFn = fn;
    if (debTimer) clearTimeout(debTimer);
    debTimer = setTimeout(() => { debTimer = null; const f = debFn; debFn = null; if (f) run(f); }, 180);
  }
  function flushDebounce() {
    if (debTimer) { clearTimeout(debTimer); debTimer = null; }
    const f = debFn; debFn = null;
    if (f) return run(f);
    return debPending || Promise.resolve();  // 이미 날아간 왕복도 착지까지 기다린다
  }

  /* 파이프라인 2열(결정 34) — 소스(결속 열) → 표시형(프리셋). 데이터를 안 겨눴으면 소스
     칸 자체가 없다(고를 게 없는 드롭다운을 띄우지 않는다). */
  function pipeHtml(s, t, i) {
    if (!s.has_data) return "";
    const cols = (s.columns || []).map((c) =>
      `<option value="${esc(c)}"${c === t.col ? " selected" : ""}>${esc(c)}</option>`).join("");
    const fmts = ((s.fmt_options && s.fmt_options[t.fmt_kind]) || []).map((o) =>
      `<option value="${esc(o.code)}"${o.code === t.fmt_code ? " selected" : ""}>${esc(o.label)}</option>`).join("");
    // 표시형은 **데이터에서 오는 값**에만 뜻이 있다 — 무결속 수기 값이나 사람이 직접 고친
    // 값(hand)에 띄우면 골라도 화면이 안 바뀌는 손잡이가 된다(dead control 금지).
    const fmtSel = t.col && t.state !== "hand"
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
      : `값을 직접 입력하면 사람 소유가 됩니다. 데이터를 고르면 이름이 같은 자리가 자동으로 채워집니다.`;
    return `<h4>값 채우기</h4>${rows}<p class="qd-formhint">${hint}</p>`;
  }

  /* 소유권 맵(결정 33 소유권 색) — {토큰이름: 상태}. fill 세그먼트에 own-* 클래스를 입혀
     **누가 채웠는지**를 색으로 가른다: auto=데이터 자동 결속 · hand=결속인데 직접 수정 ·
     man=무결속 수기. blank/missing 은 삼분 표지가 이미 색으로 말하므로 뺀다. 판정은 서버
     토큰 state 그대로(파생 판정 금지) — 폼 칩과 미리보기가 한 색 언어가 된다. */
  function ownersOf(s) {
    const o = {};
    (s.tokens || []).forEach((t) => {
      if (t.state === "auto" || t.state === "hand" || t.state === "man") o[t.name] = t.state;
    });
    return o;
  }

  /* 미리보기 본문 — 표지 ON 이면 공유 SegView(음영+소유권 색), OFF 면 순수 평문(복사되는
     그대로). plain 은 세그먼트 텍스트 이어붙임 = 서버 render_record 불변식(같은 문자열). */
  function previewInner(s) {
    if (!markers) return esc(window.SegView.plain(s.segments));
    return window.SegView.paint(s.segments, ownersOf(s));
  }

  /* 미리보기 안내문 — **표지 상태를 따라간다**(결정 33). 표지를 끄면 색 범례가 가리키는 색이
     화면에 없으므로(리뷰 F5), 범례 대신 "보이는 그대로 복사됨"을 말한다. 토글 핸들러가 이
     문안도 함께 갱신해 범례가 표지보다 오래 살지 않게 한다. */
  function previewNoteText() {
    return markers
      ? "이대로 복사됩니다. 채움 표지는 화면에만 보이고 복사되지 않습니다. 데이터 값은 파랑, 직접 고친 값은 주황, 직접 입력한 값은 초록입니다."
      : "채움 표지를 껐습니다. 지금 보이는 그대로 복사됩니다.";
  }

  function rightPaneHtml(s) {
    const right = tab === "source"
      ? `<textarea class="qd-srcedit" id="qdSrc" aria-label="템플릿 원문">${esc(s.template_text)}</textarea>` +
        `<p class="qd-prevnote">여기서 고친 템플릿은 이 세션의 사본입니다. 라이브러리는 바뀌지 않습니다.</p>`
      : `<pre class="wc-render f-malgun" id="qdRender">${previewInner(s)}</pre>` +
        `<p class="qd-prevnote" id="qdPrevNote">${previewNoteText()}</p>`;
    // 표지 토글은 미리보기 탭에서만 뜬다(원문 편집엔 표지가 없다). aria-pressed 로 상태 낭독.
    const toggle = tab === "source" ? "" :
      `<button class="btn sm" id="qdMarkerToggle" aria-pressed="${markers}" title="채움 표지를 켜고 끕니다">채움 표지</button>`;
    return `<div class="qd-prevhead"><div class="qd-tabs">` +
      `<button class="btn sm" id="qdTabPrev" aria-pressed="${tab !== "source"}">미리보기</button>` +
      `<button class="btn sm" id="qdTabSrc" aria-pressed="${tab === "source"}">원문 편집</button>` +
      `</div>${toggle}</div>${right}`;
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
    // 데이터가 없으면 「데이터 해제」는 아예 없다(dead 버튼 금지) — 속성 hidden 으로 숨긴다.
    $("qdBtnClearData").hidden = !s.has_data;
    // 양끝에서 비활성된 스테퍼에 포커스가 있으면 그대로 두면 포커스가 body 로 떨어진다
    // (preserve.js 는 id 로 되돌리는데 disabled 버튼은 focus 를 받지 않는다) — 형제로 옮긴다.
    const dead = document.querySelector("#qdDataLine .btn[disabled]");
    if (dead && document.activeElement === document.body) {
      const alive = document.querySelector("#qdDataLine .btn:not([disabled])");
      if (alive) alive.focus();
    }
  }

  /* 경보·고지 한 줄 — 빈 문자열이면 상자째 숨는다. `hidden` **속성**으로 숨긴다: 이 코드
     베이스에 일반 `.hidden` 클래스 규칙은 없고(모달 전용), 클래스로 숨긴 척하면 테두리만
     남은 빈 경고 상자가 계속 서 있는다(부록 B-9 표시 상태 결함 클래스). */
  function warnNote(msg) {
    const el = $("qdNote");
    el.textContent = msg || "";
    el.hidden = !msg;
  }

  /* 데이터 교체·해제·행 이동 전 고지(결정 32의 3분류) — 판정·문안은 Python 이 지금 만든다.
     결속·무수정 값은 조용히 재생성되므로 아무 말도 하지 않는다(무의미한 확인 금지). */
  async function carryOk(gesture, title, confirmLabel) {
    await flushDebounce();  // 대기 중인 타건 정산 후에 물어야 판정이 지금 상태를 본다
    const g = await Bridge.call(SCREEN, "carry_notice", { gesture: gesture });
    if (!g) return true;
    // 무결속 수기 값은 유지 + **고지**(막지 않는다, 결정 32) — 매 행 이동마다 모달이 서면
    // 그건 완화 조항이 경계하는 반복이다. 확인은 혼합이 생기는 직접 수정에만.
    pendingNote = g.notice || "";
    if (!g.armed) return true;
    return window.Modal.confirm({
      title: title,
      body: g.message,
      confirmLabel: confirmLabel,
      cancelLabel: "머무르기",
    });
  }

  /* 휘발도 가드(결정 32) — 세션을 비우는/바꾸는 제스처 전에 저장 안 된 노동을 재진술한다.
     판정·문안은 Python(session_guard)이 지금 만든다(carryOk 와 같은 규율, 스냅샷 캐시 아님).
     gesture: fresh=통째 폐기 · switch=템플릿 교체(같은 이름·데이터는 이어짐). armed 아니면
     조용히 통과(빈손·미노동엔 죽은 확인 금지). true=진행, false=머무르기. */
  async function sessionGuardOk(gesture, confirmLabel) {
    await flushDebounce();  // 대기 타건 정산 후 물어야 판정이 지금 상태를 본다
    const g = await Bridge.call(SCREEN, "session_guard", { gesture: gesture });
    if (!g || !g.armed) return true;
    return window.Modal.confirm({
      title: gesture === "fresh" ? "지금 세션을 버릴까요?" : "템플릿 바꾸기 확인",
      body: g.message,
      confirmLabel: confirmLabel,
      cancelLabel: "머무르기",
    });
  }

  /* 복사(결정 33) — 공유 copy_clipboard 관통(txt 카드와 같은 진입점). 미채움이 있어도
     막지 않고 복사 **후** 시끄럽게 알린다(사후 경보 승계 — 완화 조항의 "틀리면 보이는").
     대기 타건을 먼저 정산해 화면에 보이는 값 그대로가 클립보드에 담기게 한다. */
  async function copyDraft() {
    await flushDebounce();
    const note = $("qdCopyNote");
    const r = await Bridge.copyClipboard(SCREEN);
    if (!r || !r.copied) { note.dataset.level = "warn"; note.textContent = "복사할 내용이 없습니다."; return; }
    const gaps = (r.missing_fields || []).length + (r.empty_fields || []).length;
    if (gaps) {
      note.dataset.level = "warn";
      note.textContent = `복사했습니다. 아직 안 채운 자리 ${gaps}곳이 그대로 나갔습니다.`;
    } else {
      note.dataset.level = "ok";
      note.textContent = "복사했습니다.";
    }
  }

  function setPill(s) {
    const pill = $("qdStatus");
    if (!s.template_text) { pill.dataset.level = "idle"; pill.textContent = "세션 휘발 · 저장 없음"; return; }
    const un = s.unfilled_count || 0;
    if (un) { pill.dataset.level = "warn"; pill.textContent = `미채움 ${un}`; }
    else { pill.dataset.level = "ok"; pill.textContent = "전량 채움"; }
  }

  /* 화면 크롬(헤더 「새 기안」·출구 푸터) — 템플릿이 깔렸을 때만 산다(빈손엔 복사·승격·새
     기안 모두 무의미). 구조가 바뀔 때만(전면 render) 도니 복사 노트도 여기서 비운다 —
     세션이 바뀌면 직전 복사 결과 문안은 낡은 사실이다(조용한 stale 방지). */
  function syncChrome(s) {
    const loaded = !!s.template_text;
    $("qdBtnFresh").hidden = !loaded;
    $("qdFoot").hidden = !loaded;
    clearCopyNote();
  }

  /* 복사 결과 노트 비우기 — 내용이 바뀌면 직전 「복사했습니다」는 클립보드와 어긋난 거짓이
     된다(리뷰 F3). 전면 render 는 syncChrome 이 부르고, 타이핑(_NO_PUSH: 값·원문 입력)은
     겨냥 패치라 syncChrome 을 안 거치므로 입력 순간 직접 비운다("편집하면 다시 복사"가 규칙). */
  function clearCopyNote() {
    const note = $("qdCopyNote");
    if (!note) return;
    note.textContent = "";
    delete note.dataset.level;
  }

  /* 타이핑 응답 겨냥 패치를 **현 세대에만** 적용한다 — 왕복 중에 행이 바뀌거나 데이터가
     해제되면 그 응답은 옛 세계의 그림이라, 그리면 화면이 뒤로 감긴다. */
  function inEpoch(fn) {
    const e = EPOCH;
    return (s) => { if (e === EPOCH) fn(s); };
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
    EPOCH++;  // 새 세대 — 이전 세대의 타이핑 응답은 이제 무효다
    Preserve.around(() => {
      LAST = s;
      syncSlot(s);
      syncData(s);
      $("qdBody").innerHTML = bodyHtml(s);
      wireBody(s);
      setPill(s);
      syncChrome(s);
      growAll();
      // 경보(교체로 굳은 자리)가 우선이고, 없으면 직전 제스처의 고지를 한 번 싣는다.
      warnNote(s.frozen_notice || pendingNote);
      pendingNote = "";
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
    if (pre) pre.innerHTML = previewInner(s);  // 표지 ON/OFF·소유권 색 반영(전면 렌더와 한 경로)
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

  /* 열 결속 — 직접 입력한 값을 덮는 경우엔 Python 이 확인 문안을 돌려주고, 사람이 확인하면
     같은 액션을 confirm 으로 다시 부른다(relink 게이트와 같은 재진술 확인 문법). */
  async function setSource(name, col) {
    const r = await Bridge.call(SCREEN, "set_source", { name: name, col: col });
    if (!r || !r.confirm) return;
    if (!(await window.Modal.confirm({
      title: "값 덮어쓰기 확인",
      body: r.confirm,
      confirmLabel: "데이터 값으로 바꾸기",
      cancelLabel: "머무르기",
    }))) return;
    Bridge.call(SCREEN, "set_source", { name: name, col: col, confirm: true });
  }

  function wireFormRows(s) {
    (s.tokens || []).forEach((t, i) => {
      // 결속·표현형 손잡이(구조 액션) — 서버가 푸시해 전면 재렌더한다(값 입력과 달리
      // 포커스 중인 입력이 없다).
      const src = $("qdSrc-" + i);
      if (src) src.addEventListener("change", () => setSource(t.name, src.value));
      const fmt = $("qdFmt-" + i);
      if (fmt) fmt.addEventListener("change", () =>
        Bridge.call(SCREEN, "set_fmt", { name: t.name, code: fmt.value }));
      const take = $("qdTake-" + i);
      if (take) take.addEventListener("click", () => setSource(t.name, t.suggest));
      const rev = $("qdRevert-" + i);
      if (rev) rev.addEventListener("click", () =>
        Bridge.call(SCREEN, "revert_token", { name: t.name }));
      const val = $("qdVal-" + i);
      if (!val) return;
      val.addEventListener("input", () => {
        clearCopyNote();  // 값이 바뀌면 직전 복사 노트는 클립보드와 어긋난다(리뷰 F3)
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
          .then(inEpoch(patchRight)));
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
      src.addEventListener("input", () => {
        clearCopyNote();  // 원문이 바뀌면 직전 복사 노트는 클립보드와 어긋난다(리뷰 F3)
        debounce(() => Bridge.call(SCREEN, "edit_source", { text: src.value }).then(inEpoch(patchForm)));
      });
      src.addEventListener("blur", flushDebounce);
    }
    const tp = $("qdTabPrev"), ts = $("qdTabSrc");
    // 탭 전환은 전면 재렌더 — 편집 중이었다면 DOM 값을 LAST 로 흡수한 뒤 바꿔 마지막 글자 보존.
    if (tp) tp.addEventListener("click", () => { syncEditsIntoLast(); tab = "preview"; render(LAST); });
    if (ts) ts.addEventListener("click", () => { syncEditsIntoLast(); tab = "source"; render(LAST); });
    // 채움 표지 토글 — 순수 뷰 상태 전환이라 서버 왕복 없이 미리보기만 다시 그린다(편집 중이면
    // DOM 값 흡수 후). 원문 탭에선 이 버튼이 없다(표지 대상이 미리보기뿐).
    const mt = $("qdMarkerToggle");
    if (mt) mt.addEventListener("click", () => {
      syncEditsIntoLast(); markers = !markers;
      const pre = $("qdRender");
      if (pre) pre.innerHTML = previewInner(LAST);
      const note = $("qdPrevNote");  // 범례가 표지보다 오래 살지 않게 함께 갱신(리뷰 F5)
      if (note) note.textContent = previewNoteText();
      mt.setAttribute("aria-pressed", String(markers));
    });
  }

  /* 붙여넣기 열기 = 세션 교체 제스처(결정 34) — 저장 안 된 노동이 있으면 **모달을 열기
     전에** 확인한다(txt 데이터 피커 선례: 텍스트까지 붙인 뒤 "머무르기"는 노동을 또 버린다). */
  async function openPaste() {
    if (!(await sessionGuardOk("switch", "버리고 붙여넣기"))) return;
    $("qdPasteText").value = (LAST && LAST.origin === "paste") ? LAST.template_text : "";
    window.Modal.open("qdPasteModal", { initialFocus: $("qdPasteText") });
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. 슬롯·붙여넣기 모달은 여기서 1회 배선. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    $("qdTplSel").addEventListener("change", async (e) => {
      const v = e.target.value;
      if (v === "" || v === "__pasted" || v === "__mod") return;  // 안내·의사 옵션은 무동작
      // 다른 템플릿으로 전환은 세션 교체 — 저장 안 된 노동이 있으면 확인한다. 머무르기면
      // 드롭다운을 실제 정체로 되돌린다(안 그러면 고른 값이 남아 표시와 세션이 어긋난다).
      if (!(await sessionGuardOk("switch", "버리고 바꾸기"))) { if (LAST) syncSlot(LAST); return; }
      Bridge.call(SCREEN, "select_template", { name: v });
    });
    $("qdBtnPaste").addEventListener("click", openPaste);
    // 「새 기안」(결정 32) — 세션을 통째 비운다. 버릴 노동이 있으면 먼저 확인(빈손엔 통과).
    $("qdBtnFresh").addEventListener("click", async () => {
      if (!(await sessionGuardOk("fresh", "버리고 새로"))) return;
      Bridge.call(SCREEN, "fresh", {});
    });
    // 복사 = 유일한 실동작 출구(휘발 세션을 남기는 길). 승격 2동사는 표면만이라 비활성 상태다.
    $("qdBtnCopy").addEventListener("click", copyDraft);

    // ---- 데이터 겨눔(결정 34의 데이터 소스 이원) — 두 유래가 같은 고지 가드를 지난다.
    $("qdBtnPickFile").addEventListener("click", async () => {
      warnNote("");
      if (!(await carryOk("swap", "데이터 바꾸기 확인", "데이터 바꾸기"))) return;
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
      if (!(await carryOk("swap", "데이터 바꾸기 확인", "데이터 바꾸기"))) return;
      await PoolPicker.choose(SCREEN);  // 실패 재진술은 피커 모달 안에서(공용 관문 문구)
    });
    $("qdBtnClearData").addEventListener("click", async () => {
      warnNote("");
      if (!(await carryOk("clear", "데이터 해제 확인", "데이터 해제"))) return;
      Bridge.call(SCREEN, "clear_data", {});
    });
    // 행 스테퍼는 매 렌더 새로 그려지므로 슬롯에 위임 배선한다(리스너 누수·유실 방지).
    $("qdDataLine").addEventListener("click", async (e) => {
      const prev = e.target.closest && e.target.closest("#qdRowPrev");
      const next = e.target.closest && e.target.closest("#qdRowNext");
      if (!prev && !next) return;
      if (!LAST || !LAST.has_data) return;
      if (!(await carryOk("row", "행 바꾸기 확인", "행 바꾸기"))) return;
      // 다음 행 번호는 **Python 이 지금 계산**한다 — JS 캐시(LAST)로 더하면 연타 시 두 번째
      // 클릭이 아직 안 도착한 첫 클릭의 결과를 못 보고 같은 행을 다시 보낸다(클릭 삼킴).
      Bridge.call(SCREEN, "step_row", { delta: next ? 1 : -1 });
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
