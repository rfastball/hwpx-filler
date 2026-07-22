/* 기안 세션 표면 공용 팩토리 — 「기안문 채우기」와 「기안」이 한 벌을 쓴다. #148 슬라이스 3a.

   백엔드의 draft_session.py(DraftSessionMixin)와 **짝**이다: 세션 기계가 하나면 표면도
   하나여야 두 화면이 갈라지지 않는다(#94 교훈 — 한시적 중복은 한시적이지 않다). 슬라이스 6
   에서 구 화면이 죽으면 소비자만 하나 줄고 이 파일은 그대로 남는다.

   화면 고유값은 **id 맵**으로만 주입한다(grouplist.js·datazone.js 팩토리 관례). 판정은 여전히
   전부 Python 이고 여기는 문안·표현뿐이다(파생경계 번역오류 상류 차단).

   반환 표면: render(s) · wire() · refreshOnEnter() · guardBody/copyGateBody(순수 합성기 —
   실앱 게이트가 되읽는다) · confirmNewDraftIfArmed/confirmDataSwapIfArmed(파괴 경로 사전 확인). */
(function () {
  const $ = (id) => document.getElementById(id);
  // 상태 색인 점 상태어(한글) — aria-label/title 이 영문 토큰(current/copied/uncopied)을 누출하지 않게.
  const DOT_STATE_LABEL = { current: "작업점", copied: "복사됨", uncopied: "대기" };
  // 소유권 색 범례(결정 33) — 판정은 서버(토큰 own)라 여긴 문안·색만(파생 판정 금지).
  const OWN_LABEL = { auto: "데이터에서 자동", man: "직접 입력" };
  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js) — " 도 escape 해 속성 컨텍스트 안전

  /* 데이터 존 문안 — 두 화면 공통 기본값(화면별로 갈라야 할 실증이 나오면 cfg 로 연다). */
  const ZONE_COPY = {
    emptyNoData: "데이터를 선택하면 기안 대상 행이 여기에 표시됩니다.",
    emptyFiltered: "필터와 일치하는 행이 없습니다. 위 칩의 정의를 확인하세요.",
    emptyNoRows: "데이터에 행이 없습니다.",
    stripLead: (n) => `필터 밖 선택 <b>${n}행</b> — 화면엔 안 보이지만 큐에 포함됩니다: `,
  };

  /* 붙여넣기 모달은 두 화면이 **한 벌 DOM** 을 공유한다 — 확정 버튼 배선은 모듈 1회,
     소유권(어느 화면이 열었나)만 슬롯으로 넘긴다. */
  let pasteOwner = null;
  let pasteWired = false;
  function wirePasteModal() {
    if (pasteWired) return;
    pasteWired = true;
    $("pasteCancel").addEventListener("click", () => window.Modal.close("pasteModal"));
    $("pasteOk").addEventListener("click", () => {
      if (pasteOwner) pasteOwner();
      window.Modal.close("pasteModal");
    });
  }

  function create(cfg) {
    const SCREEN = cfg.screen;
    const id = cfg.ids;
    let LAST = null;
    let lastDotsSig = null;  // 상태 색인 점 재구축 스킵 서명(리뷰 F7) — 점 지형 불변 push 에 reflow 회피
    let zoneNoteKey = null;
    // 카드 보기 = 채운 모습/원문(순수 뷰 상태, 클라이언트 소유 — 서버 왕복 없음). 「기안문
    // 채우기」는 뷰 전환 손잡이가 없어(id 미부여) 항상 채운 모습이다.
    let view = "filled";

    /* 타이핑 구동(값 입력·원문 라이브 편집)은 서버 왕복을 디바운스한다(빠른 기안 선례) — 타건
       마다 왕복은 낭비고, 값 유실 경합은 _NO_PUSH+겨냥 패치가 막는다(포커스 입력 미재구성). */
    let debTimer = null, debFn = null;
    // 편집 왕복을 **직렬 체인**으로 잇는다(리뷰 A) — 타이핑 편집이 dispatch 순서대로 착지하고,
    // flush 가 최신뿐 아니라 **미착지 편집 전부**를 기다리게 한다. 종전(단일 debPending)은 최신
    // promise 만 추적해, 왕복이 180ms 를 넘어 겹치면 flush 가 이전 편집을 안 기다리고 그 편집이
    // 뒤늦게/역순으로 착지해 컨트롤러에 stale 원문을 복원할 수 있었다(승격이 화면과 다른 원문 저장).
    // 체인이면 다음 편집이 직전 착지 후에 발사돼 순서가 보장되고, flush 는 체인 tail 을 기다린다.
    let editChain = Promise.resolve();
    function runDeb(f) {
      const next = editChain.then(() => f());
      // 한 편집 실패가 체인을 끊지 않게 파생(editChain)에서 흡수하되, 반환 next 는 실패를 그대로
      // 전파해 awaiter(flush)·셸 백스톱이 시끄럽게 받는다(조용한 삼킴 아님 — confirm-or-alarm).
      editChain = next.catch(() => {});
      return next;
    }
    function debounce(fn) {
      debFn = fn;
      if (debTimer) clearTimeout(debTimer);
      debTimer = setTimeout(() => { debTimer = null; const f = debFn; debFn = null; if (f) runDeb(f); }, 180);
    }
    function flushDeb() {
      if (debTimer) { clearTimeout(debTimer); debTimer = null; }
      const f = debFn; debFn = null;
      if (f) return runDeb(f);   // 방금 스케줄분 + 체인 전체를 기다림(runDeb 가 tail 반환)
      return editChain;          // 대기분 없어도 미착지 체인 전체를 기다린다
    }
    /* 렌더 세대 — 구조 변화(전면 render)가 나면 올라가, 늦게 착지한 타이핑 응답이 옛 세대의
       스냅샷으로 미리보기를 되돌리는 경합을 막는다(빠른 기안 EPOCH 선례). */
    let EPOCH = 0;
    function inEpoch(fn) { const e = EPOCH; return (s) => { if (e === EPOCH) fn(s); }; }

    /* ---- 데이터 존 고지(재적용 결과·전멸 필터 무동작) — 렌더 불가침 JS 소유 요소 ----
       완료 존 로그가 없는 화면이라 log 채널을 이 고지 한 줄로 받는다. 푸시 재렌더에
       증발하지 않고(렌더 함수 무접촉), 데이터 소스가 바뀌면 걷힌다(render 가 판정). */
    function zoneLog(msg) {
      const el = $(id.zoneNote);
      el.textContent = msg;
      el.style.display = "";
    }

    /* ---- 데이터 존(전-선언 큐 선택, 블록 3) = 공용 팩토리(datazone.js) 인스턴스 ----
       표면 계약·리뷰 결정 주석은 팩토리가 소유한다. 여기는 화면 고유값만 주입한다: 선두
       「큐」 열 = 큐 표지(대기·작업점 ▶·복사됨 — 링1 TxtQueueModel 상태의 사영) · 세션
       지문 = 소스 정체(data_key) · 문안 = 기안 어휘. */
    const dz = window.DataZone.create({
      screen: SCREEN,
      ids: {
        selCount: id.selCount, search: id.search, reapply: id.reapply,
        chips: id.chips, strip: id.strip,
        tableHost: id.tableHost, tableWrap: id.tableWrap, tableEmpty: id.tableEmpty,
        tableHead: id.tableHead, tableBody: id.tableBody, colPanel: id.colPanel,
        selAll: id.selAll, selNone: id.selNone,
      },
      rowIdPrefix: cfg.rowIdPrefix,  // preserve.js 가 id 로 포커스 복원 — 화면 간 전역 유일
      lead: {
        header: "큐",
        /* 큐 표지 — **순번(qpos)은 여기 렌더하지 않는다**(리뷰): 이 표는 레코드 순서인데
           순번은 큐-꼬리 순서라, 해제 후 재선택한 행이 꼬리로 가면 위→아래로 1,2,5,3,4 처럼
           비단조로 읽힌다(의도된 큐 의미론이지만 화면에선 렌더 버그로 보인다). 순번의 거처는
           **큐 순서로 그리는 상태 색인·작업점 카드**다 — 거기선 단조롭다. 여기선
           상태(작업점·대기·복사됨)만 정직하게 말한다. */
        bodyHtml(r) {
          if (!r.selected) return `<span class="doc-off">선택하면 큐에 담깁니다</span>`;
          if (r.copied) return `<span class="doc-sum">복사됨</span>`;  // 정직 라벨(결정 16)
          if (r.current) return `<span class="doc-name">▶ 작업점</span>`;
          return `<span class="doc-name">대기</span>`;
        },
      },
      copy: ZONE_COPY,
      /* 세션 지문 = 소스 **정체**(data_key: 정규화 경로+시트 / 풀 참조) — 표시 라벨이 아니다
         (리뷰): 라벨은 basename 이라 `folder1/명단.xlsx`↔`folder2/명단.xlsx` 가 같은 문자열이 돼
         세션 리셋이 발화하지 않고, 이전 파일의 Shift 앵커가 살아남아 새 파일에서 엉뚱한 범위가
         조용히 선택된다(Python `_data_key` 와 같은 판정 = 재적용 게이트와도 일치). */
      tableKey: (s) => s.data_key || "",
      log: zoneLog,
    });

    /* 작업점 카드 렌더 = 링1 render_segments(채움 표지 삼분)의 페인트. **웹은 토큰 정규식을
       재구현하지 않는다**. 세그먼트 텍스트는 클립보드 평문 그대로라 이어붙이면 render_record 와
       같다(불변식). literal=원문, fill=값(음영), blank=〈빈 값〉 표지, missing={{토큰}}(빨강). */
    const paintCard = window.SegView.paint;  // 공유 세그먼트 페인터(segview.js)

    /* ---- ② 맞추기 표(#148 슬라이스 3b·4) — 토큰별 결속·근사 제안·유형·표시형·확정·소유권 색·값.
       판정은 전부 Python(mapping_state)이고 여기는 문안·표현뿐이다(파생경계 번역오류 상류 차단):
       열 후보·소유권(auto/man)·제안·유형·값·확정·상태는 서버 토큰 그대로 소비하고 재판정하지 않는다.
       유형·확정 열은 `.persist` 로 표시한다 — 슬라이스 4 는 그릇을 늘 보이게 세우고, 저장 세션
       유래로 켜고 끄는 지속성 스위치(결정 7)는 슬라이스 5 가 이 클래스에 숨김 규칙을 얹는다. */
    function mapRowHtml(s, t, i) {
      // 드롭다운 선택 = 결속 열(auto)일 때만 그 열, 아니면 「(직접 입력)」(man·무결속). man 의
      // 기억된 소스(t.source)는 드롭다운이 아니라 「되돌리기」로 되살린다 — 옵션 selected 는
      // **유효 선택(srcSel)** 로만 판정한다(Codex F1): t.source 로 판정하면 man 이 「(직접 입력)」과
      // 옛 열을 동시에 selected 해 나중 것(열)이 이겨, 상수가 그 열에 결속된 듯 거짓 표시된다.
      const srcSel = t.own === "auto" ? t.source : "";
      // 복원된 결속(데이터 미연결) 정직 표시(리뷰 5a P2) — 데이터가 없어 s.columns 가 비어도
      // 결속된 열(srcSel)을 선택지에 넣어 「(직접 입력)」으로 오표시되지 않게(저장 매핑 거짓 표시
      // 차단). 실제 데이터 연결 시 열 존재는 백엔드 _rebuild_mapping 이 재검증한다(죽은 결속 강등).
      const colList = (s.columns || []).slice();
      if (srcSel && colList.indexOf(srcSel) < 0) colList.unshift(srcSel);
      const cols = colList.map((c) =>
        `<option value="${esc(c)}"${c === srcSel ? " selected" : ""}>${esc(c)}</option>`).join("");
      const dot = t.own ? `<span class="own ${t.own}" title="${OWN_LABEL[t.own] || ""}"></span>` : "";
      const src =
        `<div class="mapsrc">${dot}` +
        `<select class="field sm mapsrc-sel" id="${id.tokPanel}-src-${i}" data-i="${i}"` +
        ` aria-label="${esc(t.name)} 데이터 열">` +
        `<option value=""${srcSel === "" ? " selected" : ""}>(직접 입력)</option>${cols}</select>` +
        // 근사 제안(결정 30) — 무결속·비auto 에서만, 자동 적용 없이 원클릭.
        (t.suggest && t.own !== "auto"
          ? `<button class="btn sm mapsug" id="${id.tokPanel}-sug-${i}" data-i="${i}"` +
            ` title="이름이 비슷한 열입니다">「${esc(t.suggest)}」 적용</button>` : "") +
        // 「자동으로 되돌리기」 — 결속 값을 고쳐 상수로 강등된 자리를 원 열로(막다른 강등 금지).
        (t.can_revert
          ? `<button class="btn sm maprev" id="${id.tokPanel}-rev-${i}" data-i="${i}">자동으로 되돌리기</button>` : "") +
        `</div>`;
      // 유형(#148 슬라이스 4, 결정 12) — 값-운반 유형(텍스트/날짜/금액)을 사람이 이긴다. 결속
      // (auto) 값에만 뜻이 있어(운반할 값이 있는 자리) 표시형과 같은 게이트로 auto 행에만 띄운다:
      // const(man)·무결속엔 운반 유형이 없어 dead control 이 된다. 유형이 바뀌면 표시형은
      // 기본으로 떨어지고(모델 계약) 표시형 드롭다운 후보가 다시 뜬다.
      const typeOpts = ((s.type_options) || []).map((o) =>
        `<option value="${esc(o.code)}"${o.code === t.fmt_kind ? " selected" : ""}>${esc(o.label)}</option>`).join("");
      const typeCell = t.own === "auto"
        ? `<select class="field sm maptype persist" id="${id.tokPanel}-type-${i}" data-i="${i}"` +
          ` aria-label="${esc(t.name)} 유형">${typeOpts}</select>`
        : `<span class="muted">—</span>`;
      // 표시형(결정 34 2층) — 데이터에서 오는 값(auto)에만 뜻이 있다(man/무결속엔 dead control 금지).
      const fmts = ((s.fmt_options && s.fmt_options[t.fmt_kind]) || []).map((o) =>
        `<option value="${esc(o.code)}"${o.code === t.fmt_code ? " selected" : ""}>${esc(o.label)}</option>`).join("");
      const fmtCell = (t.own === "auto" && fmts)
        ? `<select class="field sm mapfmt" id="${id.tokPanel}-fmt-${i}" data-i="${i}"` +
          ` aria-label="${esc(t.name)} 표시형">${fmts}</select>`
        : `<span class="muted">—</span>`;
      // 「지금 행의 값」 — **항상 편집 가능**(사용자 결정). 결속(auto)이면 현재 행의 데이터 값이
      // 미리 차 있고, 여기 타이핑하면 상수(man)로 강등된다(전 행 공통) — 되돌리기(maprev)가
      // 원 결속 열을 되살린다. 무결속·상수는 빈 칸에서 직접 입력한다(빠른 기안 qd-val 동형).
      // 확정-비움(결정 12)이면 「아직 안 씀」이 아니라 「비워둠(선언)」이라 정직하게 말한다(판정은
      // 서버 blank_declared) — 타이핑하면 값이 생겨 상수로 강등되며 선언이 풀린다.
      const declared = !!t.blank_declared;
      const valCell = declared
        ? `<span class="mapval-declared muted" title="확정-비움 — 복사 확인에서 제외">비워둠(선언)</span>`
        : `<textarea class="mapval-in${(t.value || "").trim() === "" ? " empty" : ""}"` +
          ` rows="1" id="${id.tokPanel}-val-${i}" data-i="${i}" placeholder="직접 입력"` +
          ` aria-label="${esc(t.name)} 값">${esc(t.value || "")}</textarea>`;
      // 확정 열(#148 슬라이스 4, 결정 12) — 행별 확정. 확정+무내용 = 확정-비움. 판정은 서버
      // (t.confirmed), 여긴 체크 상태만 되읽는다. .persist 는 슬라이스 5 유래 스위치의 훅.
      const ckCell =
        `<input class="ck mapck persist" type="checkbox" id="${id.tokPanel}-ck-${i}" data-i="${i}"` +
        `${t.confirmed ? " checked" : ""} aria-label="${esc(t.name)} 확정">`;
      return `<tr data-i="${i}"${declared ? ' class="row-blank-declared"' : ""}>` +
        `<td class="maptok" title="{{${esc(t.name)}}}">${esc(t.name)}</td>` +
        `<td>${src}</td><td class="maptype-cell persist">${typeCell}</td>` +
        `<td class="mapfmt-cell">${fmtCell}</td><td class="mapval-cell">${valCell}</td>` +
        `<td class="mapck-cell persist">${ckCell}</td></tr>`;
    }

    function renderMap(s) {
      const tokens = s.tokens || [];
      const host = $(id.tokPanel);
      // 유래별 그릇 게이팅(#148 슬라이스 5a, 결정 7) — 저장 모드에서만 유형·확정(`.persist`) 열이
      // 뜬다. 판정은 Python(s.mode), 여기는 data-mode 표지만(CSS 가 display 를 가른다). 미지정은
      // 휘발로 낙착(구 화면은 mode 를 안 보내 유형·확정이 숨는 게 옳다).
      host.dataset.mode = s.mode || "volatile";
      if (!tokens.length) {
        host.innerHTML = `<p class="muted hint" style="padding:10px">토큰이 없는 템플릿입니다.</p>`;
      } else {
        // 무데이터(가상 1건, 결정 14) — 「데이터 열」은 「직접 입력」만 가능하고 값 열은 행이
        // 하나뿐이라 「지금 행의 값」이 아니라 그냥 「값」이다(가리키는 여러 행이 없다).
        const valHead = s.has_data ? "지금 행의 값" : "값";
        host.innerHTML =
          `<table class="dmap"><thead><tr>` +
          `<th style="width:15%">토큰</th><th style="width:29%">데이터 열</th>` +
          `<th class="persist" style="width:13%">유형</th><th style="width:15%">표시형</th>` +
          `<th>${valHead}</th><th class="persist" style="width:52px">확정</th>` +
          `</tr></thead><tbody>` +
          tokens.map((t, i) => mapRowHtml(s, t, i)).join("") +
          `</tbody></table>`;
      }
      if (id.mapLegend) {
        // 휘발 note(#148 슬라이스 5a, 결정 7) — 휘발 모드에선 유형·확정을 묻지 않는 이유를
        // 정직하게 말한다(열이 왜 없는지). 저장 모드에선 열이 그 자리를 대신 설명한다.
        const volNote = (s.mode || "volatile") === "volatile"
          ? `<span class="muted volatile-note">이 세션은 저장하지 않으므로 <b>유형·확정</b>은 ` +
            `묻지 않습니다 — 남기려면 「기안으로 저장」.</span>`
          : "";
        $(id.mapLegend).innerHTML =
          `<span><i class="own auto"></i>데이터에서 자동</span>` +
          `<span><i class="own man"></i>직접 입력</span>` +
          `<span class="muted">항목 없음은 <span class="mono">{{토큰}}</span> 그대로 복사됩니다.</span>` +
          volNote;
      }
    }

    /* 소유권 맵(결정 33) — {토큰이름: own}. 카드 fill 세그먼트에 own-* 클래스를 입혀 값이
       데이터에서 왔는지(auto) 직접 입력인지(man) 색으로 가른다. 판정은 서버 토큰 그대로. */
    function ownersOf(s) {
      const o = {};
      (s.tokens || []).forEach((t) => { if (t.own === "auto" || t.own === "man") o[t.name] = t.own; });
      return o;
    }

    /* ---- ③ 원문 뷰 전환(결정 34) — 채운 모습 ↔ 원문(같은 칸의 두 모습). 뷰 전환 손잡이가
       있는 화면(「기안」)만 원문 textarea 를 보이고, 타이핑이 ② 표를 실시간 재구성한다. */
    function applyView() {
      if (!id.viewFilled) return;  // 뷰 전환 없는 화면(「기안문 채우기」) — 항상 채운 모습
      const src = view === "source";
      $(id.viewFilled).setAttribute("aria-pressed", String(!src));
      $(id.viewSource).setAttribute("aria-pressed", String(src));
      $(id.srcView).hidden = !src;
      $(id.cardRender).hidden = src;  // 두 모습은 배타 — 원문 볼 땐 채운 모습을 숨긴다
    }

    /* 원문바 메타(#148 슬라이스 5b) — 이름 + 수정됨 표지 + 「사본으로 편집」(저장 모드에서만).
       **textarea 는 손대지 않는다** — 라이브 편집(_NO_PUSH) 응답 patchMap 도 이 메타를 갱신해야
       하기 때문이다(리뷰 5b P2): 깨끗한 원문을 고치면 source_dirty=true·template_name 소거인데
       full render 만 이걸 그리면 무관한 재렌더 전까지 옛 이름·수정됨 부재로 남는다. */
    function renderSourceBar(s) {
      const saved = (s.mode || "volatile") === "saved";
      if (id.srcName) $(id.srcName).textContent = s.template_name || "(붙여넣은 텍스트)";
      if (id.modBadge) $(id.modBadge).hidden = !s.source_dirty;  // 판정은 Python(source_dirty)
      // srcFork = 저장 원문을 사본으로 가르는 유일 출구(읽기 전용의 탈출구) — 휘발에선 이미 편집
      // 가능이라 숨는다(dead control 금지, 시안 `[data-mode]` 게이트 이식).
      if (id.srcFork) $(id.srcFork).hidden = !saved;
    }

    function renderSource(s) {
      if (!id.srcBox) return;
      const box = $(id.srcBox);
      // 저장 원문은 읽기 전용(#148 슬라이스 5a, 결정 7 스위치 ④) — 정의가 조용히 갈라지지 않게.
      // readonly 면 input 이 안 나 _do_edit_source 도 안 돈다(표면 방어). 손보려면 「사본으로
      // 편집」이 휘발로 가른다(슬라이스 5b — 원문바 srcFork). 판정은 Python(s.source_readonly).
      box.readOnly = !!s.source_readonly;
      if (box.value !== s.template_text) box.value = s.template_text || "";
      renderSourceBar(s);
    }

    /* 작업점 카드(결정 16) — 상태 색인(위치·처리·빈칸 지도) + 코드블록 렌더 + 동사 게이트.
       커서가 목록을 걷지 않고 큐가 이 한 장을 지나간다: 작업점=첫 미처리, 복사분은 후미로. */
    function renderCard(s) {
      const c = s.card || {};
      const complete = !!c.is_complete;
      // 큐 퇴화(결정 8·14) — 유효 큐 ≤ 1건(단건·무데이터 가상 1건). 판정은 Python(queue_degenerate)이
      // 하고 여기는 큐 장치 3종(진행 색인·다음 카드·자동 전진)을 숨기는 표현만 한다: 순회할 곳도
      // 전진할 곳도 없어 정보가 없다(장식이라 지우는 게 아니라 뜻이 없어 숨는다).
      const degen = !!c.queue_degenerate;
      $(id.card).classList.toggle("complete", complete);
      // 상태 색인 재진술 — 위치·처리 진척·빈칸 수. 퇴화 시 진행/복사 색인은 무의미하니 뺀다.
      const readout = $(id.cardReadout);
      const gaps = (c.missing_fields || []).length + (c.empty_fields || []).length;
      if (!c.has_current) {
        readout.textContent = s.has_data
          ? "선택된 카드가 없습니다 — 위 표에서 행을 선택하면 큐에 담깁니다."
          : "템플릿을 고르거나 붙여넣으면 이대로 채워 복사할 수 있습니다.";
      } else if (degen) {
        // 단건·무데이터 — 큐 진척이 없다. 복사 전 확인이 필요한 빈칸만 재진술한다.
        readout.textContent = gaps ? `빈칸 ${gaps}건 — 복사 전 확인합니다.` : "";
      } else if (complete) {
        readout.textContent = `완주 — ${c.selected_count}건 전부 복사했습니다.`;
      } else {
        const posTxt = c.position
          ? `작업점 ${c.position}/${c.uncopied_count} 미처리`
          : "복사됨 카드";
        readout.textContent =
          `${posTxt} · 복사 ${c.copied_count}/${c.selected_count}` + (gaps ? ` · 빈칸 ${gaps}건` : "");
      }
      // 상태 색인 점 — 큐 표시 순서(단조). 클릭 = 작업점 지정. 빈칸 카드엔 빨강 표지(빈칸 지도).
      // 상태어는 한글로 번역해 aria-label 에 싣는다(영문 토큰 current/copied 누출 차단).
      // **변할 때만 재구축**(리뷰 F7): 필터 타건 등 점 지형 불변인 push 에서 O(n) DOM write+
      // reflow 를 피한다(서명 비교).
      // 큐 장치 3종을 퇴화 시 숨긴다(결정 8·14) — 진행 색인 점·◀▶ 다음 카드·자동 전진. hidden
      // 은 disabled 와 독립이라(아래 경계 잠금은 다중 카드에서만 뜻이 있음) 표시 여부만 가른다.
      $(id.cardDots).hidden = degen;
      $(id.cardPrev).hidden = degen;
      $(id.cardNext).hidden = degen;
      const advWrap = $(id.advance).closest(".wc-advance");
      if (advWrap) advWrap.hidden = degen;
      const order = c.index_map || [];
      const dotsSig = order.map((d) => `${d.index}${d.state[0]}${d.has_gap ? "g" : ""}`).join(",");
      if (dotsSig !== lastDotsSig) {
        lastDotsSig = dotsSig;
        $(id.cardDots).innerHTML = order.map((d) => {
          const label = DOT_STATE_LABEL[d.state] || d.state;
          return `<button class="wc-dot ${d.state}${d.has_gap ? " gap" : ""}" role="listitem"` +
            ` data-i="${d.index}" aria-label="${d.index + 1}행 ${label}${d.has_gap ? " 빈칸있음" : ""}"` +
            ` title="${d.index + 1}행 · ${label}${d.has_gap ? " · 빈칸 있음" : ""}"></button>`;
        }).join("");
      }
      // 카드 정체 + 렌더.
      // 대상 글꼴 선언(결정 17) — 콤보 동기 + 원문 렌더가 선언을 추종한다("넘어가는 감각").
      // 폭 성질(비례폭 여부) 판정은 Python 이 한다 — 여기선 클래스만 갈아 끼운다.
      const font = s.target_font || "gulimche";
      const fontSel = $(id.targetFont);
      if (fontSel.value !== font) fontSel.value = font;
      // 클래스 **전체 대입**(리뷰 F5): 벗겨낼 글꼴 목록을 여기 다시 적으면 열거형의 사본이
      // 되고, 글꼴을 추가하면서 이 목록을 놓치면 낡은 f-* 가 남아 stale 글꼴로 렌더된다.
      $(id.cardRender).className = "wc-render f-" + font;
      renderLint(c.lint || {});
      $(id.cardTitle).textContent = !c.has_current
        ? "이대로 복사됩니다 (미리보기 — 데이터 미선택)"
        : c.is_copied ? "복사됨 — 다시 복사하면 클립보드가 갱신됩니다" : "이대로 복사됩니다";
      // 소유권 색(결정 33) — fill 세그먼트가 데이터(auto)인지 직접 입력(man)인지 색으로 가른다.
      $(id.cardRender).innerHTML = paintCard(c.segments, ownersOf(s));
      // 동사 게이트 — 작업점(또는 가상 카드)이 없으면 복사 불가(모델 계약의 표면 반영).
      $(id.cardCopy).disabled = !c.has_current;
      // 이전/다음 = **경계 비활성**(리뷰 F2): queue.step 은 순환 없이 클램프라, 첫/끝 카드에서
      // 버튼을 살려 두면 클릭이 조용한 no-op 가 된다(고장난 듯). 작업점 위치로 양끝을 잠근다.
      const ci = c.has_current ? order.findIndex((d) => d.index === c.index) : -1;
      $(id.cardPrev).disabled = ci <= 0;
      $(id.cardNext).disabled = ci < 0 || ci >= order.length - 1;
      $(id.advance).checked = !!c.advance_after;
    }

    /* 선언-조건부 정렬 린트(결정 17) — 술어는 Python(card.lint)이 판정하고 여기는 문안만 입힌다.
       비례폭을 선언했을 때만 선다: 고정폭(굴림체·돋움체)에서 연속 공백 정렬은 정당한 저작이라
       경보하면 소음이다. 치환은 세션 렌더 옵션이라 템플릿 원본을 건드리지 않고, 바뀐 결과가
       카드에 그대로 보이며 클립보드도 같은 텍스트다(되읽기 = 검증). 되돌리기는 항상 열려 있다. */
    function renderLint(lint) {
      const box = $(id.cardLint);
      if (!lint.active) { box.hidden = true; box.innerHTML = ""; return; }
      box.hidden = false;
      const applied = !!lint.applied;
      box.dataset.level = applied ? "ok" : "warn";
      const msg = applied
        ? "전각 공백으로 치환했습니다. 어느 글꼴에서도 정렬이 유지되며, 복사되는 텍스트도 " +
          "지금 보이는 그대로입니다."
        : "정렬 취약: 연속 공백으로 맞춘 정렬은 선언된 비례폭 글꼴에서 흐트러질 수 있습니다. " +
          "한글과 전각 공백은 모든 글꼴에서 폭이 같아 견고합니다.";
      // 처방 버튼의 **id 는 두 상태에서 같다**: 누르면 곧바로 재렌더되는데 id 가 바뀌면
      // preserve.js 가 포커스를 복원할 대상을 잃는다(키보드 사용자가 자리를 놓친다).
      box.innerHTML = `<span class="txt">${msg}</span>` +
        `<button class="btn sm" id="${id.lintAction}" data-act="${applied ? "undo" : "fix"}">` +
        `${applied ? "되돌리기" : "전각 공백으로 치환"}</button>`;
    }

    /* Python→웹 푸시 렌더. Bridge.onPush 로 등록된다(소비자가 등록). 전면 재렌더는 구조
       변화(선택·템플릿·결속·데이터)에서 돈다 — 타이핑 액션(값 입력·원문 라이브 편집)은
       _NO_PUSH 라 이 경로를 타지 않고 겨냥 패치(patchMap/patchPreview)로 온다. */
    function render(s) {
      EPOCH++;  // 새 세대 — 이전 세대의 타이핑 응답은 이제 무효(늦은 착지 되감기 차단)
      Preserve.around(() => {  // 재구성 가로질러 포커스·캐럿·카드/토큰 스크롤 보존(#28)
        LAST = s;
        // 템플릿 콤보를 스냅샷에 동기(F11) — 서버측 선택 변경(새 기안 초기화·홈 '기안
        // 열기' 진입)이 콤보에 보이게. 옵션에 없는 이름(붙여넣은 텍스트)은 선택 해제로 남는다.
        const sel = $(id.tplSel);
        if (sel.value !== s.template_name) sel.value = s.template_name;
        // 저장 모드(원문 읽기 전용)는 **원문 정의 자체를 잠근다** — textarea 뿐 아니라 템플릿 교체
        // 진입점(콤보·붙여넣기)도(리뷰 5a P1). 안 잠그면 저장 레시피가 조용히 다른 원문으로 바뀌어
        // 「사본으로 편집」 전이 없이 수정된 정의를 저장분처럼 보여준다(계약 거짓말). 데이터 컨트롤은
        // 잠그지 않는다(저장 세션도 데이터는 매번 바꾼다). 손보려면 「사본으로 편집」(5b).
        const roLock = !!s.source_readonly;
        sel.disabled = roLock;
        $(id.pasteBtn).disabled = roLock;

        renderMap(s);       // ② 맞추기 표(결속·제안·표시형·소유권 색·「지금 행의 값」)
        renderSource(s);    // ③ 원문 뷰 textarea 동기(뷰 전환 화면만)
        applyView();        // ③ 채운 모습/원문 배타 표시
        renderCard(s);  // 작업점 카드(상태 색인·코드블록 렌더·동사 게이트) — 큐 판(결정 16)
        // 소스 종류 병기 라벨(#26 #6) — 서버가 플래그에서 합성(K8)·화면별 고유 id(#27).
        $(id.dataLabel).value = s.data_source_label || "";
        dz.render(s);  // 데이터 존(테이블·칩·스트립) — 팩토리 소유(datazone.js)
        // 존 고지는 데이터 소스가 바뀌면 걷는다(다른 세션으로의 누수 방지 — 읽힐 때까지 유지).
        // 키는 표시 라벨이 아니라 정체(data_key) — 동명 다른 폴더 전환에서 이전 소스의 고지가
        // 남는 같은 함정을 tableKey 와 함께 닫는다(리뷰).
        const zkey = s.data_key || "";
        if (zkey !== zoneNoteKey) {
          zoneNoteKey = zkey;
          $(id.zoneNote).style.display = "none";
          $(id.zoneNote).textContent = "";
        }
        const card = s.card || {};
        setStatus(card.missing_fields || [], card.empty_fields || []);  // card 단일 출처(리뷰 F9)
        renderNote(card);  // 완료 노트 = 스냅샷 구동(card.last_copy) — announce 순서 경합 없음
      });
    }

    function setStatus(missing, empty) {
      const pill = $(id.status);
      if (missing.length) { pill.dataset.level = "warn"; pill.textContent = `항목 없음 ${missing.length}`; }
      else if (empty.length) { pill.dataset.level = "warn"; pill.textContent = `빈 값 ${empty.length}`; }
      else { pill.dataset.level = "ok"; pill.textContent = "전량 채움"; }
    }

    /* 겨냥 패치 — 값 입력(set_map_value, _NO_PUSH): 미리보기·상태만 갱신하고 **맞추기 표는
       재구성하지 않는다**(포커스된 값 입력이 살아 있게). 판정은 Python 반환 스냅샷. */
    function patchPreview(s) {
      LAST = s;
      renderCard(s);  // 값이 바뀌면 카드 렌더·상태 색인·소유권 색이 바뀐다
      const card = s.card || {};
      setStatus(card.missing_fields || [], card.empty_fields || []);
    }

    /* 겨냥 패치 — 원문 라이브 편집(edit_source, _NO_PUSH): 토큰 셋이 바뀌므로 맞추기 표를
       재구성하고 미리보기도 갱신하되 **포커스된 원문 textarea 는 손대지 않는다**(zone ③).
       맞추기 표 이벤트는 위임 배선이라(wire) 재구성 후 재배선이 불필요하다. */
    function patchMap(s) {
      LAST = s;
      renderMap(s);
      renderSourceBar(s);  // 원문 라이브 편집 → 이름·수정됨 표지 갱신(리뷰 5b P2 — textarea 불건드림)
      renderCard(s);  // 원문 변화 → 미리보기(채운 모습 복귀 대비, 원문 뷰에선 숨겨져 있어도 최신)
      const card = s.card || {};
      setStatus(card.missing_fields || [], card.empty_fields || []);
    }

    /* 열 결속 — 직접 입력한 값을 덮는 경우엔 Python 이 확인 문안을 돌려주고(변이 없음), 사람이
       확인하면 같은 액션을 confirm 으로 다시 부른다(빠른 기안·relink 게이트 재진술 문법). */
    async function setSource(name, col) {
      const r = await Bridge.call(SCREEN, "set_source", { name, col });
      if (!r || !r.confirm) return;  // 결속됨(변이는 push→render 가 드롭다운을 실상태로 맞춘다)
      if (!(await window.Modal.confirm({
        title: "값 덮어쓰기 확인",
        body: r.confirm,
        confirmLabel: "데이터 값으로 바꾸기",
        cancelLabel: "머무르기",
      }))) {
        // 머무르기 = 백엔드 불변(상수 유지)인데 native select 는 이미 새 열을 보인다 — 확인
        // 왕복은 push 를 안 하므로 아무도 되돌려 주지 않는다(Codex F2). LAST 로 재렌더해
        // 드롭다운을 실상태(「(직접 입력)」)로 복원한다(표시 ≠ 실제 상태 봉합).
        if (LAST) render(LAST);
        return;
      }
      Bridge.call(SCREEN, "set_source", { name, col, confirm: true });
    }

    function resetNote() {
      const n = $(id.note);
      n.dataset.level = "idle";
      n.textContent = window.Copy.TXT_NOTE;  // 단일 출처(copy.js)
    }

    /* 완료 노트(복사 확정) = **스냅샷 구동**. Python 이 복사한 행 번호와 리포트를 card.last_copy 로
       싣고(어떤 변이 동작이든 무효화), 여기선 그 스냅샷을 그대로 진술한다 — JS announce 후 재푸시가
       지우는 순서 경합도, 전진 시 카드가 바뀌어 노트가 딴 카드를 가리키는 desync 도 구조적으로
       없다(리뷰 F1·F2). 없으면 기본 안내(resetNote). 미충족 포함 복사는 시끄럽게(빈칸 게이트). */
    function renderNote(c) {
      const lc = c.last_copy;
      if (!lc) { resetNote(); return; }
      const n = $(id.note), mi = lc.missing_fields || [], em = lc.empty_fields || [];
      // 행 접두 — 가상 카드(무데이터 직접 입력, 결정 14)는 행 번호가 없다(row=null). 그때는
      // "N행" 대신 카드를 가리키지 않고 진술한다("복사됨").
      const pfx = lc.row == null ? "" : `${lc.row + 1}행 `;
      if (mi.length) {
        n.dataset.level = "warn";
        n.textContent = `⚠ ${pfx}복사됨 — 항목 없음 ${mi.length}건(${mi.join(", ")}) 포함. 빨간 토큰 확인 후 사용하세요.`;
      } else if (em.length) {
        n.dataset.level = "warn";
        n.textContent = `⚠ ${pfx}복사됨 — 빈 값 ${em.length}건(${em.join(", ")}) 포함. 확인 후 사용하세요.`;
      } else {
        n.dataset.level = "ok";
        n.textContent = `✓ ${pfx}전량 채움 복사 완료.`;
      }
    }

    function warnNote(msg) {
      const n = $(id.note); n.dataset.level = "warn"; n.textContent = "⚠ " + msg;
    }

    /* 빈칸 게이트 본문(결정 16 · 부록 A-3-28) — 무엇이 채워지지 않은 채 나가는지 열거한다.
       집합은 Python 이 복사와 같은 render 통로로 확정해 주므로(copy_precheck) 여기서 세는 것과
       실제 나가는 텍스트가 갈라지지 않는다 = 열거해도 되는 경우다. 긴 목록은 앞 6개만 적고
       나머지는 수치로 접는다(모달이 스크롤로 번지면 정작 결론 버튼이 안 보인다). */
    function copyGateBody(pre) {
      const lines = [];
      const list = (names) => {
        const head = names.slice(0, 6).join(", ");
        return names.length > 6 ? `${head} 외 ${names.length - 6}개` : head;
      };
      const mi = pre.missing_fields || [], em = pre.empty_fields || [];
      if (mi.length) lines.push(`항목 없음 ${mi.length}건: ${list(mi)}`);
      if (em.length) lines.push(`빈 값 ${em.length}건: ${list(em)}`);
      // 꼬리 문장은 해당 종류가 실제로 있을 때만 — 빈 값만 있는 카드에 "{{토큰}} 원문이
      // 실린다"고 말하면 일어나지 않는 일을 경고하는 것이 된다(over-warn 도 거짓이다).
      const tail = mi.length ? "\n항목 없음은 {{토큰}} 원문 그대로 클립보드에 실립니다." : "";
      // 행 접두 — 가상 카드(무데이터, 결정 14)는 행 번호가 없다(row=null).
      const pfx = pre.row == null ? "이대로 복사하면" : `${pre.row + 1}행을 이대로 복사하면`;
      return `${pfx} 아래 항목이 채워지지 않은 채 나갑니다.\n` +
        lines.join("\n") + tail;
    }

    /* 카드 결속 복사(결정 16) — 작업점 카드 렌더를 클립보드로(복사=완료). Python(copy_clipboard→
       note_copied)이 복사분을 후미로 옮기고 전진 opt-in 후 재푸시하며, 완료 노트는 그 스냅샷
       (card.last_copy)이 실어 온다(renderNote) — JS 가 별도로 announce 하지 않으므로 순서 경합이
       없다.

       빈칸 게이트 = 카드 결속(결정 16, #125): 결손이 있으면 **복사 전에** 확인을 받는다. 완화
       조항(결정 31)의 범위는 "틀리면 보이는 추측(표현형)"이고 미해소 토큰은 같은 결정이 **엄격
       유지**로 분류한 '그럴싸한 오류'다 — 붙여넣기 전까지 아무도 그것이 오류인 줄 모른다. */
    async function copyCard() {
      if ($(id.cardCopy).disabled) return;  // 작업점 없음 = 무동작(모델 계약의 표면 반영)
      // 판정은 Python 이 지금(스냅샷 캐시는 왕복 지연에서 stale — 작업 화면 가드와 같은 규율).
      const pre = await Bridge.call(SCREEN, "copy_precheck", {});
      if (!pre || !pre.can_copy) return;  // 작업점 소실(레이스) — 브리지도 같은 술어로 막는다
      if ((pre.missing_fields || []).length || (pre.empty_fields || []).length) {
        const go = await window.Modal.confirm({
          title: "빈칸이 있습니다",
          body: copyGateBody(pre),
          confirmLabel: "그대로 복사",
          cancelLabel: "취소",
        });
        if (!go) return;  // 머무르기 = 클립보드 불변(직전 복사분도 건드리지 않는다)
      }
      await Bridge.copyClipboard(SCREEN);  // 완료 노트는 note_copied 재푸시가 스냅샷 구동으로 렌더
    }

    /* ---- 세션 가드(T3 — 블록 4 결정 26·27) : 데이터 교체가 큐 진행을 조용히 버리지 않게 ----
       술어·수치는 Python(_guard_state)이 판정하고 여기는 문안만 입힌다(작업 화면과 같은 규율).
       T3 성분(큐 부분 진행)이 기안 고유다: 어디까지 붙여넣었는지는 앱 밖 기억이라, 처리
       표지가 증발하면 복구할 방법이 없다. 잃는 것을 종류별로 명시한다(결정 27 수치 재진술). */
    function guardBody(g, lead) {
      const lost = [];
      if (g.queue_partial) lost.push(`복사 진행 ${g.copied_count}/${g.sel_count}행(처리 표지)`);
      // 선택 재진술 조각은 「작업」 가드와 **공유**(guard.js, 리뷰 F6) — 같은 가드 상태를 두
      // 화면이 다른 문장으로 말하지 않게. 종류별 열거(무엇이 사라지는가)만 이 표면 몫.
      if (g.sel_count) {
        lost.push(window.Guard.selectionLine(g.sel_count, g.filter_active, g.in_def, g.extra));
      }
      if (g.filter_parts > 0) lost.push(`필터 정의 ${g.filter_parts}개 조건`);
      // 앞머리만 제스처별로 갈린다(데이터 교체 / 새 기안) — 잃는 것의 열거는 같은 술어를 공유한다.
      return `${lead || "다른 데이터를 겨누면"} 이 큐는 새로 만들어집니다.\n` +
        `사라지는 것: ${lost.join(" · ")}.`;
    }

    /* 데이터 교체 사전 확인 — 피커를 열기 **전에** 묻는다(파일까지 고른 뒤 "머무르기"는 고른
       노동을 또 버리게 한다). 무장 판정은 실시간 질의(스냅샷 캐시는 왕복 지연에서 stale).
       true=진행, false=머무르기. */
    async function confirmDataSwapIfArmed() {
      const g = await Bridge.call(SCREEN, "guard_state", {});
      if (!g || !g.armed) return true;
      return window.Modal.confirm({
        title: "데이터 변경 확인",
        body: guardBody(g, "다른 데이터를 겨누면"),
        confirmLabel: "데이터 바꾸고 버리기",
        cancelLabel: "머무르기",
      });
    }

    /* 「＋ 새 기안」 사전 확인(#126 — T3 면제 철회). 원장 F11 의 면제 근거("txt 출력은 일회성이라
       버릴 durable 상태가 없다")는 블록 3 전-선언 큐 신설로 거짓이 됐다: 20건 중 12건까지 붙여넣은
       큐가 클릭 한 번에 사라지고, 어디까지 처리했는지는 앱 밖 기억이라 복원 수단이 없다. 술어·수치는
       데이터 교체 가드와 **같은 _guard_state** 를 쓴다(두 파괴 경로가 한 술어를 공유). true=진행. */
    async function confirmNewDraftIfArmed() {
      const g = await Bridge.call(SCREEN, "guard_state", {});
      if (!g || !g.armed) return true;
      return window.Modal.confirm({
        title: "새 기안 확인",
        body: guardBody(g, "새 기안을 시작하면"),
        confirmLabel: "새로 시작하고 버리기",
        cancelLabel: "머무르기",
      });
    }

    /* 웹→Python 이벤트 배선. */
    function wire() {
      // 데이터 존(테이블·열 패널·칩·스트립·전체 선택/해제·문서 레벨 닫기)은 팩토리 몫 배선.
      dz.wire();
      $(id.tplSel).addEventListener("change", (e) =>
        Bridge.call(SCREEN, "select_template", { name: e.target.value }));

      // 작업점 카드 동사(결정 16) — 큐 네비게이션(◀▶ 경계 멈춤·점 클릭)·복사(카드 결속·Enter)·
      // 복사 후 전진 토글. ◀▶·점 클릭이 **자유 이동**이라 미루기(결정 10 사망)를 대체한다.
      $(id.cardPrev).addEventListener("click", () => Bridge.call(SCREEN, "step", { delta: -1 }));
      $(id.cardNext).addEventListener("click", () => Bridge.call(SCREEN, "step", { delta: 1 }));
      $(id.cardDots).addEventListener("click", (e) => {
        const dot = e.target.closest(".wc-dot");
        if (dot) Bridge.call(SCREEN, "set_current", { index: Number(dot.dataset.i) });
      });
      $(id.cardCopy).addEventListener("click", copyCard);
      // Enter=복사(결정 16 Enter 경로) — 코드블록에 포커스가 있을 때. pre 는 비편집이라 안전.
      $(id.cardRender).addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); copyCard(); }
      });
      // 미루기(결정 19)는 슬라이스 3c 에서 **사망**했다 — 두 표면 모두 자유 이동(◀▶·점 클릭)이
      // 막힌 카드의 탈출구다(작업점 고정 전제가 깨져 큐 뒤로 보내는 동사가 불필요해졌다).
      $(id.advance).addEventListener("change", (e) =>
        Bridge.call(SCREEN, "toggle_advance", { value: e.target.checked }));

      // 대상 글꼴 선언(결정 17) — 값은 Python 이 전역 설정에 영속한다(웹 저장소 아님, #74 전례).
      $(id.targetFont).addEventListener("change", (e) =>
        Bridge.call(SCREEN, "set_target_font", { font: e.target.value }));
      // 린트 처방(치환·되돌리기) — 버튼은 매 렌더 재생성이라 위임으로 받는다.
      $(id.cardLint).addEventListener("click", (e) => {
        const act = e.target.closest("#" + id.lintAction);
        if (act) Bridge.call(SCREEN, "set_fullwidth", { value: act.dataset.act === "fix" });
      });

      // ---- ② 맞추기 표 — 표는 매 렌더 재생성이라 **위임 배선**(호스트 1회)한다. 행의 토큰은
      //      data-i 로 LAST.tokens 를 찾는다. 결속·표시형·제안·되돌리기는 구조 액션(전면 push),
      //      값 입력은 타이핑(_NO_PUSH → patchPreview)이다.
      const mapTokenOf = (el) => {
        const row = el.closest("tr[data-i]");
        return row && LAST && LAST.tokens ? LAST.tokens[Number(row.dataset.i)] : null;
      };
      $(id.tokPanel).addEventListener("change", (e) => {
        const t = mapTokenOf(e.target);
        if (!t) return;
        const cl = e.target.classList;
        if (cl.contains("mapsrc-sel")) setSource(t.name, e.target.value);
        else if (cl.contains("maptype"))  // 유형 정정(결정 12) — 사람이 값 스니핑을 이긴다
          Bridge.call(SCREEN, "set_map_type", { name: t.name, type: e.target.value });
        else if (cl.contains("mapfmt"))
          Bridge.call(SCREEN, "set_map_fmt", { name: t.name, code: e.target.value });
        else if (cl.contains("mapck"))  // 행별 확정(결정 12) — 확정+무내용 = 확정-비움
          Bridge.call(SCREEN, "set_confirmed", { name: t.name, value: e.target.checked });
      });
      $(id.tokPanel).addEventListener("click", (e) => {
        const sug = e.target.closest(".mapsug"), rev = e.target.closest(".maprev");
        if (!sug && !rev) return;
        const t = mapTokenOf(e.target);
        if (!t) return;
        if (sug) setSource(t.name, t.suggest);        // 근사 제안 원클릭 결속(결정 30)
        else Bridge.call(SCREEN, "revert_map", { name: t.name });  // man→auto 되돌리기
      });
      $(id.tokPanel).addEventListener("input", (e) => {
        if (!e.target.classList.contains("mapval-in")) return;
        const t = mapTokenOf(e.target);
        if (!t) return;
        // 낙관적 표지 — 판정은 Python, 미리보기는 반환 스냅샷 patchPreview 가 갱신한다:
        // ①빈칸(값 공백 여부) ②소유권 색. 결속 값을 고치면 즉시 man(상수)로 강등되는데, 이
        // 타이핑 경로는 표를 재구성하지 않으므로(포커스 보호) 점을 안 바꾸면 색이 "데이터"라고
        // 거짓말한다(값은 이미 사람 소유인데) — 지배 결함류(문안/표지 ≠ 실제 집합)라 즉시 뒤집는다.
        e.target.classList.toggle("empty", e.target.value.trim() === "");
        const dot = e.target.closest("tr").querySelector(".own");
        if (dot) dot.className = "own man";
        debounce(() => Bridge.call(SCREEN, "set_map_value", { name: t.name, text: e.target.value })
          .then(inEpoch(patchPreview)));
      });
      // 포커스 이탈 시 대기 편집 즉시 반영(blur 는 버블 안 해 캡처로 받는다).
      $(id.tokPanel).addEventListener("blur", flushDeb, true);

      // ---- ③ 원문 뷰 전환(결정 34) — 뷰 전환 손잡이가 있는 화면만. 순수 뷰 상태라 서버 왕복
      //      없이 배타 표시만 바꾼다. 원문 라이브 편집은 타이핑(_NO_PUSH → patchMap)이다.
      if (id.viewFilled) {
        $(id.viewFilled).addEventListener("click", () => { view = "filled"; applyView(); });
        $(id.viewSource).addEventListener("click", () => { view = "source"; applyView(); });
      }
      if (id.srcBox) {
        $(id.srcBox).addEventListener("input", (e) =>
          debounce(() => Bridge.call(SCREEN, "edit_source", { text: e.target.value })
            .then(inEpoch(patchMap))));
        $(id.srcBox).addEventListener("blur", flushDeb);
      }
      // 「사본으로 편집」(#148 슬라이스 5b) — 저장 원문을 휘발 사본으로 가른다(값·데이터·큐 진행
      // 승계, 원문만 편집 가능). 진행이 있으면(복사한 카드) 1회 사실 진술: 이미 복사한 건은 이전
      // 문안으로 남는다(결정 11 — 되돌릴 수 없어 「진행 초기화」는 거짓말). 저장 기안은 불변.
      if (id.srcFork) {
        $(id.srcFork).addEventListener("click", async () => {
          // 복사 이력·건수 판정은 copied_total(내구 단조)로 — 무데이터 가상 복사는 copied_count
          // 에 안 잡히고(큐 미기록, 682), copied_count 는 선택 해제·데이터 교체로 줄어(reconcile)
          // 이미 붙여넣은 문서 수를 못 센다(685). 이 카운터는 복사 조작마다 +1 되어 유지된다.
          const card = (LAST && LAST.card) || {};
          const nCopied = card.copied_total || 0;
          if (nCopied > 0 && !(await window.Modal.confirm({
            title: "사본으로 편집",
            body: `이미 복사한 ${nCopied}건은 이전 문안으로 남습니다 — 되돌릴 수 없습니다. 앞으로 ` +
              `복사할 카드부터 새 문안이 적용됩니다. 저장된 기안은 그대로 두고 이 세션만 사본으로 가릅니다.`,
            confirmLabel: "사본으로 편집", cancelLabel: "머무르기",
          }))) return;
          // 사본이 유일 휘발("이번 세션")이 되어 직전에 붙여넣던 세션을 밀어낸다(단일 슬롯). 그
          // 세션에 복구 불가 진행이 있으면 백엔드가 needs_confirm 으로 되묻는다(리뷰 5b 2R P1).
          let r = await Bridge.call(SCREEN, "fork_to_volatile", {});  // 푸시가 원문을 편집 가능으로 재렌더
          if (r && r.needs_confirm) {
            const prev = r.copied_count || 0;
            if (!(await window.Modal.confirm({
              title: "붙여넣던 세션이 사라집니다",
              body: (prev > 0 ? `직전에 붙여넣던 세션에서 이미 ${prev}건을 복사했습니다 — 되돌릴 수 없습니다. ` : "") +
                `이 사본이 「이번 세션」 자리를 대신합니다. 붙여넣던 세션의 원문 편집·데이터·선택·복사 ` +
                `진행은 저장된 기안에 보관되지 않아, 사본으로 가르면 함께 사라집니다.`,
              confirmLabel: "사본으로 편집", cancelLabel: "머무르기",
            }))) return;
            await Bridge.call(SCREEN, "fork_to_volatile", { confirm: true });
          }
        });
      }

      $(id.pickBtn).addEventListener("click", async () => {
        // 데이터 재선택 = 필터 세션의 죽음 — 대기 중 검색 디바운스를 먼저 정산해 직전 필터
        // 슬롯(결정 28)에 마지막 타이핑까지 실린다(작업 화면 flush 규율 승계).
        await dz.flushPendingSearch();
        if (!(await confirmDataSwapIfArmed())) return;  // T3 가드(결정 26·27) — 피커 열기 전에
        let r = await Bridge.pickDataFile(SCREEN);
        if (r && typeof r === "object" && r.needs_sheet) {   // 다중 시트 → 확정 게이트(#33)
          r = await SheetPicker.choose(SCREEN, r);
          if (r === null) return;                            // 취소 = 중단(첫 시트 강등 없음)
        }
        if (r === null) return;                      // 취소
        if (typeof r === "string" && r.startsWith("ERROR:")) { warnNote(r.slice(6).trim()); return; }
        // 파일명은 load_data_path 가 스냅샷(data_label)으로 밀어 render 가 채운다(P4 서버 소유).
      });
      // 등록 데이터(풀) 겨눔(#26 #6) — 취소=중단, 실패는 모달 안에서 재진술(PoolPicker).
      $(id.poolBtn).addEventListener("click", async () => {
        await dz.flushPendingSearch();  // 재겨눔 전 검색 정산(위 pickBtn 과 같은 규율)
        if (!(await confirmDataSwapIfArmed())) return;  // T3 가드 — 파일 경로와 같은 규율
        await PoolPicker.choose(SCREEN);             // 라벨은 스냅샷(data_source_label)이 채운다
      });

      // 붙여넣기 모달(세션 템플릿) — 개폐·초기포커스·복귀·Escape 는 Modal 헬퍼가 소유(#27/#28).
      // 모달 DOM 은 **두 화면 공유 한 벌**이라 확정 버튼도 한 번만 배선하고, 어느 화면이
      // 열었는지는 소유권 슬롯이 기억한다(두 인스턴스가 각자 리스너를 달면 한 번 누를 때
      // 두 화면이 다 바뀐다 — 조용한 교차 오염).
      wirePasteModal();
      $(id.pasteBtn).addEventListener("click", () => {
        pasteOwner = pasteOk;
        $("pasteText").value = LAST ? LAST.template_text : "";
        window.Modal.open("pasteModal", { initialFocus: $("pasteText") });
      });
    }

    /* 붙여넣기 확정 — 템플릿만 바꾼다(겨눈 데이터는 유지, VM datasource 불변). */
    function pasteOk() {
      Bridge.call(SCREEN, "set_template_text", { text: $("pasteText").value });
    }

    /* 템플릿 목록 채우기 — 선택은 **세션의 실제 템플릿**(스냅샷)이 정한다(드롭다운은 표시일 뿐). */
    function fillTemplateSelect(state) {
      const sel = $(id.tplSel);
      const names = state.templates || [];
      sel.innerHTML = names.map((n) => `<option value="${esc(n)}">${esc(n)}.txt</option>`).join("");
      if (names.length) sel.value = state.template_name;
    }

    /* 화면 진입 재동기(#135 리뷰 P2 + 코덱스 P2) — 이 표면의 DOM 은 **자기 화면에 푸시가
       올 때만** 갱신되므로, 다른 화면에 있는 동안 바뀐 것이 여기 남아 있지 않다. 둘을 함께
       고친다:
       ① 템플릿 드롭다운은 부팅 시 1회만 채워져서 다른 화면이 라이브러리에 더한 템플릿
          (빠른 기안 승격·관리 화면 「새 TXT」·가져오기)이 앱 재시작 전엔 안 보였다.
       ② **대상 글꼴 선언은 앱 전역**이라 다른 기안 표면에서 바꿀 수 있다 — 백엔드는 이제
          한 실체를 공유하지만(TargetFontSetting), 이 화면 DOM 은 재렌더 없이는 옛 값을
          그대로 보여 준다(콤보·미리보기 글꼴·정렬 린트 문안).
       initial 은 무변이 질의라 세션을 건드리지 않는다 — 지금 진실을 그대로 다시 그린다. */
    async function refreshOnEnter() {
      if (!(window.pywebview && window.Bridge)) return;
      const state = await Bridge.initial(SCREEN);
      fillTemplateSelect(state);
      render(state);
    }

    return {
      render, wire, fillTemplateSelect, refreshOnEnter, pasteOk,
      guardBody, copyGateBody, confirmNewDraftIfArmed, confirmDataSwapIfArmed,
      warnNote, dz,
      // 대기·미착지 타이핑 편집 정산(승격이 화면에 보이는 원문/값을 저장하게) — 「템플릿으로
      // 저장」이 promote_info/save_template 전에 await 한다(빠른 기안 flushDebounce 선례).
      flush: flushDeb,
    };
  }

  window.DraftSession = { create };
})();
