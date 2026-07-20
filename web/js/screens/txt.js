/* 기안문 채우기(txt) 화면 — 브리지로 링1 TxtDraftViewModel 과 왕복. 첫 실화면(스파이크 승격).
   렌더는 Python 이 window.__push('txt', snapshot) 로 밀어 넣는다(관측 방향). 프리뷰 재진술
   (빨강 항목없음 {{토큰}}·〈빈 값〉)은 표현 계층이라 여기서 만든다 = 링2 대체, VM 로직 아님. */
(function () {
  const SCREEN = "txt";
  const $ = (id) => document.getElementById(id);
  const STATE_LABEL = { fill: "✓ 채움", blank: "◦ 빈 값", missing: "● 항목 없음" };
  // 상태 색인 점 상태어(한글) — aria-label/title 이 영문 토큰(current/copied/uncopied)을 누출하지 않게.
  const DOT_STATE_LABEL = { current: "작업점", copied: "복사됨", uncopied: "대기" };
  let LAST = null;
  let lastDotsSig = null;  // 상태 색인 점 재구축 스킵 서명(리뷰 F7) — 점 지형 불변 push 에 reflow 회피

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js) — " 도 escape 해 속성 컨텍스트 안전

  /* ---- 데이터 존 고지(재적용 결과·전멸 필터 무동작) — 렌더 불가침 JS 소유 요소 ----
     완료 존 로그가 없는 화면이라 log 채널을 이 고지 한 줄로 받는다. 푸시 재렌더에
     증발하지 않고(렌더 함수 무접촉), 데이터 소스가 바뀌면 걷힌다(render 가 판정). */
  let zoneNoteKey = null;
  function zoneLog(msg) {
    const el = $("txtZoneNote");
    el.textContent = msg;
    el.style.display = "";
  }

  /* ---- 데이터 존(전-선언 큐 선택, 블록 3) = 공용 팩토리(datazone.js) 두 번째 인스턴스 ----
     표면 계약·리뷰 결정 주석은 팩토리가 소유한다. 여기는 화면 고유값만 주입한다: 선두
     「큐」 열 = 큐 표지(대기 순번·작업점 ▶·복사됨 — 링1 TxtQueueModel 상태의 사영,
     복사 동사·카드는 다음 PR) · 세션 지문 = 데이터 라벨만(작업 화면과 달리 작업 축이
     없다) · 문안 = 기안 어휘. */
  const dz = window.DataZone.create({
    screen: SCREEN,
    ids: {
      selCount: "txtSelCount", search: "txtFilterSearch", reapply: "txtFilterReapply",
      chips: "txtFilterChips", strip: "txtSelStrip",
      tableHost: "txtTableHost", tableWrap: "txtTableWrap", tableEmpty: "txtTableEmpty",
      tableHead: "txtTableHead", tableBody: "txtTableBody", colPanel: "txtColPanel",
      selAll: "txtSelAll", selNone: "txtSelNone",
    },
    rowIdPrefix: "txtRow-",  // preserve.js 가 id 로 포커스 복원 — job 행과 전역 유일
    lead: {
      header: "큐",
      /* 큐 표지 — **순번(qpos)은 여기 렌더하지 않는다**(리뷰): 이 표는 레코드 순서인데
         순번은 큐-꼬리 순서라, 해제 후 재선택한 행이 꼬리로 가면 위→아래로 1,2,5,3,4 처럼
         비단조로 읽힌다(의도된 큐 의미론이지만 화면에선 렌더 버그로 보인다). 순번의 거처는
         **큐 순서로 그리는 상태 색인·작업점 카드**(PR-3)다 — 거기선 단조롭다. 여기선
         상태(작업점·대기·복사됨)만 정직하게 말한다. */
      bodyHtml(r) {
        if (!r.selected) return `<span class="doc-off">선택하면 큐에 담깁니다</span>`;
        if (r.copied) return `<span class="doc-sum">복사됨</span>`;  // 정직 라벨(결정 16)
        if (r.current) return `<span class="doc-name">▶ 작업점</span>`;
        return `<span class="doc-name">대기</span>`;
      },
    },
    copy: {
      emptyNoData: "데이터를 선택하면 기안 대상 행이 여기에 표시됩니다.",
      emptyFiltered: "필터와 일치하는 행이 없습니다. 위 칩의 정의를 확인하세요.",
      emptyNoRows: "데이터에 행이 없습니다.",
      stripLead: (n) => `필터 밖 선택 <b>${n}행</b> — 화면엔 안 보이지만 큐에 포함됩니다: `,
    },
    /* 세션 지문 = 소스 **정체**(data_key: 정규화 경로+시트 / 풀 참조) — 표시 라벨이 아니다
       (리뷰): 라벨은 basename 이라 `folder1/명단.xlsx`↔`folder2/명단.xlsx` 가 같은 문자열이 돼
       세션 리셋이 발화하지 않고, 이전 파일의 Shift 앵커가 살아남아 새 파일에서 엉뚱한 범위가
       조용히 선택된다. 작업 화면이 `작업명|라벨` 복합 키로 우연히 피한 함정을 여기선 정체
       키로 정면 차단한다(Python `_data_key` 와 같은 판정 = 재적용 게이트와도 일치). */
    tableKey: (s) => s.data_key || "",
    log: zoneLog,
  });

  /* 작업점 카드 렌더 = 링1 render_segments(채움 표지 삼분)의 페인트. **웹은 토큰 정규식을
     재구현하지 않는다**(PR-1 이 예고한 파생경계 번역오류 상류 차단 — 종전 buildPreview 는
     Python 렌더와 두 벌로 걷다 어긋날 위험). 세그먼트 텍스트는 클립보드 평문 그대로라
     이어붙이면 render_record 와 같다(불변식). literal=원문, fill=값(음영), blank=〈빈 값〉
     표지, missing={{토큰}} 원문(빨강). */
  const paintCard = window.SegView.paint;  // 공유 세그먼트 페인터(segview.js) — 빠른 기안과 한 계약

  /* 작업점 카드(결정 16) — 상태 색인(위치·처리·빈칸 지도) + 코드블록 렌더 + 동사 게이트.
     커서가 목록을 걷지 않고 큐가 이 한 장을 지나간다: 작업점=첫 미처리, 복사분은 후미로. */
  function renderCard(s) {
    const c = s.card || {};
    const complete = !!c.is_complete;
    $("txtCard").classList.toggle("complete", complete);
    // 상태 색인 재진술 — 위치·처리 진척·빈칸 수.
    const readout = $("txtCardReadout");
    if (!c.has_current) {
      readout.textContent = s.has_data
        ? "선택된 카드가 없습니다 — 위 표에서 행을 선택하면 큐에 담깁니다."
        : "데이터를 선택하면 기안 대상 행이 카드로 들어옵니다.";
    } else if (complete) {
      readout.textContent = `완주 — ${c.selected_count}건 전부 복사했습니다.`;
    } else {
      const posTxt = c.position
        ? `작업점 ${c.position}/${c.uncopied_count} 미처리`
        : "복사됨 카드";
      const gaps = (c.missing_fields || []).length + (c.empty_fields || []).length;
      readout.textContent =
        `${posTxt} · 복사 ${c.copied_count}/${c.selected_count}` + (gaps ? ` · 빈칸 ${gaps}건` : "");
    }
    // 상태 색인 점 — 큐 표시 순서(단조). 클릭 = 작업점 지정. 빈칸 카드엔 빨강 표지(빈칸 지도).
    // 상태어는 한글로 번역해 aria-label 에 싣는다(리뷰: 영문 토큰 current/copied 누출 차단).
    // **변할 때만 재구축**(리뷰 F7): 필터 타건 등 점 지형 불변인 push 에서 O(n) DOM write+
    // reflow 를 피한다(서명 비교). 수백 건 큐의 점 색인 압축 문법은 후속(결정 21 유보).
    const order = c.index_map || [];
    const dotsSig = order.map((d) => `${d.index}${d.state[0]}${d.has_gap ? "g" : ""}`).join(",");
    if (dotsSig !== lastDotsSig) {
      lastDotsSig = dotsSig;
      $("txtCardDots").innerHTML = order.map((d) => {
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
    const fontSel = $("txtTargetFont");
    if (fontSel.value !== font) fontSel.value = font;
    // 클래스 **전체 대입**(리뷰 F5): 벗겨낼 글꼴 목록을 여기 다시 적으면 열거형의 네 번째
    // 사본이 되고, 글꼴을 추가하면서 이 목록을 놓치면 낡은 f-* 가 남아 stale 글꼴로 렌더된다.
    $("txtCardRender").className = "wc-render f-" + font;
    renderLint(c.lint || {});
    $("txtCardTitle").textContent = !c.has_current
      ? "이대로 복사됩니다 (미리보기 — 데이터 미선택)"
      : c.is_copied ? "복사됨 — 다시 복사하면 클립보드가 갱신됩니다" : "이대로 복사됩니다";
    $("txtCardRender").innerHTML = paintCard(c.segments);
    // 동사 게이트 — 작업점 없으면 복사·미루기 불가, 복사분은 못 미룬다(모델 계약의 표면 반영).
    $("txtCardCopy").disabled = !c.has_current;
    $("txtCardDefer").disabled = !c.has_current || c.is_copied;
    // 이전/다음 = **경계 비활성**(리뷰 F2): queue.step 은 순환 없이 클램프라, 첫/끝 카드에서
    // 버튼을 살려 두면 클릭이 조용한 no-op 가 된다(고장난 듯). 작업점 위치로 양끝을 잠근다.
    const ci = c.has_current ? order.findIndex((d) => d.index === c.index) : -1;
    $("txtCardPrev").disabled = ci <= 0;
    $("txtCardNext").disabled = ci < 0 || ci >= order.length - 1;
    $("txtAdvance").checked = !!c.advance_after;
  }

  /* 선언-조건부 정렬 린트(결정 17) — 술어는 Python(card.lint)이 판정하고 여기는 문안만 입힌다.
     비례폭을 선언했을 때만 선다: 고정폭(굴림체·돋움체)에서 연속 공백 정렬은 정당한 저작이라
     경보하면 소음이다. 치환은 세션 렌더 옵션이라 템플릿 원본을 건드리지 않고, 바뀐 결과가
     카드에 그대로 보이며 클립보드도 같은 텍스트다(되읽기 = 검증). 되돌리기는 항상 열려 있다. */
  function renderLint(lint) {
    const box = $("txtCardLint");
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
      `<button class="btn sm" id="txtLintAction" data-act="${applied ? "undo" : "fix"}">` +
      `${applied ? "되돌리기" : "전각 공백으로 치환"}</button>`;
  }

  /* Python→웹 푸시 렌더. Bridge.onPush 로 등록된다. */
  function render(s) {
    Preserve.around(() => {  // 재구성 가로질러 포커스·캐럿·카드/토큰 스크롤 보존(#28)
      LAST = s;
      // 템플릿 콤보를 스냅샷에 동기(F11) — 서버측 선택 변경(새 기안 초기화·홈 '기안
      // 열기' 진입)이 콤보에 보이게. 옵션에 없는 이름(붙여넣은 텍스트)은 선택 해제로 남는다.
      const sel = $("tplSel");
      if (sel.value !== s.template_name) sel.value = s.template_name;

      const rows = s.tokens.map((t) =>
        `<div class="tok ${t.state}">` +
        `<span class="tname" title="{{${esc(t.name)}}}">{{${esc(t.name)}}}</span>` +
        `<span class="st">${STATE_LABEL[t.state]}</span></div>`
      ).join("");
      $("tokPanel").innerHTML = rows || `<p class="muted">토큰이 없는 템플릿입니다.</p>`;

      renderCard(s);  // 작업점 카드(상태 색인·코드블록 렌더·동사 게이트) — 큐 판(결정 16)
      // 소스 종류 병기 라벨(#26 #6) — 서버가 플래그에서 합성(K8)·화면별 고유 id(#27), run 과 분리.
      $("txtDataLabel").value = s.data_source_label || "";
      dz.render(s);  // 데이터 존(테이블·칩·스트립) — 팩토리 소유(datazone.js). 게이트 없는
                     // 전량 렌더라 별도 dz.sync 불요(LAST 는 매 push 최신).
      // 존 고지는 데이터 소스가 바뀌면 걷는다(다른 세션으로의 누수 방지 — 읽힐 때까지 유지).
      // 키는 표시 라벨이 아니라 정체(data_key) — 동명 다른 폴더 전환에서 이전 소스의 고지가
      // 남는 같은 함정을 tableKey 와 함께 닫는다(리뷰).
      const zkey = s.data_key || "";
      if (zkey !== zoneNoteKey) {
        zoneNoteKey = zkey;
        $("txtZoneNote").style.display = "none";
        $("txtZoneNote").textContent = "";
      }
      const card = s.card || {};
      setStatus(card.missing_fields || [], card.empty_fields || []);  // card 단일 출처(리뷰 F9)
      renderNote(card);  // 완료 노트 = 스냅샷 구동(card.last_copy) — announce 순서 경합 없음
    });
  }

  function setStatus(missing, empty) {
    const pill = $("txtStatus");
    if (missing.length) { pill.dataset.level = "warn"; pill.textContent = `항목 없음 ${missing.length}`; }
    else if (empty.length) { pill.dataset.level = "warn"; pill.textContent = `빈 값 ${empty.length}`; }
    else { pill.dataset.level = "ok"; pill.textContent = "전량 채움"; }
  }

  function resetNote() {
    const n = $("txtNote");
    n.dataset.level = "idle";
    n.textContent = window.Copy.TXT_NOTE;  // 단일 출처(copy.js) — index.html 정적 중복 제거(F15)
  }

  /* 완료 노트(복사 확정) = **스냅샷 구동**. Python 이 복사한 행 번호와 리포트를 card.last_copy 로
     싣고(어떤 변이 동작이든 무효화), 여기선 그 스냅샷을 그대로 진술한다 — JS announce 후 재푸시가
     지우는 순서 경합도, 전진 시 카드가 바뀌어 노트가 딴 카드를 가리키는 desync 도 구조적으로
     없다(리뷰 F1·F2). 없으면 기본 안내(resetNote). 미충족 포함 복사는 시끄럽게(빈칸 게이트). */
  function renderNote(c) {
    const lc = c.last_copy;
    if (!lc) { resetNote(); return; }
    const n = $("txtNote"), mi = lc.missing_fields || [], em = lc.empty_fields || [], row = lc.row + 1;
    if (mi.length) {
      n.dataset.level = "warn";
      n.textContent = `⚠ ${row}행 복사됨 — 항목 없음 ${mi.length}건(${mi.join(", ")}) 포함. 빨간 토큰 확인 후 사용하세요.`;
    } else if (em.length) {
      n.dataset.level = "warn";
      n.textContent = `⚠ ${row}행 복사됨 — 빈 값 ${em.length}건(${em.join(", ")}) 포함. 확인 후 사용하세요.`;
    } else {
      n.dataset.level = "ok";
      n.textContent = `✓ ${row}행 전량 채움 복사 완료.`;
    }
  }

  function warnNote(msg) {
    const n = $("txtNote"); n.dataset.level = "warn"; n.textContent = "⚠ " + msg;
  }

  /* 카드 결속 복사(결정 16) — 작업점 카드 렌더를 클립보드로(복사=완료). Python(copy_clipboard→
     note_copied)이 복사분을 후미로 옮기고 전진 opt-in 후 재푸시하며, 완료 노트는 그 스냅샷
     (card.last_copy)이 실어 온다(renderNote) — JS 가 별도로 announce 하지 않으므로 순서 경합이
     없다. 빈칸 게이트 = 카드 결속(결정 16): 미충족 포함 복사는 전면 가시 렌더(빨강 세그먼트)
     + 완료 노트로 시끄럽게 알린다(완화 조항 — 전면 가시성 표면의 "틀리면 보이는" 경보). */
  async function copyCard() {
    if ($("txtCardCopy").disabled) return;  // 작업점 없음 = 무동작(모델 계약의 표면 반영)
    await Bridge.copyClipboard(SCREEN);  // 완료 노트는 note_copied 재푸시가 스냅샷 구동으로 렌더
  }

  /* ---- 세션 가드(T3 — 블록 4 결정 26·27) : 데이터 교체가 큐 진행을 조용히 버리지 않게 ----
     술어·수치는 Python(_guard_state)이 판정하고 여기는 문안만 입힌다(작업 화면과 같은 규율).
     T3 성분(큐 부분 진행)이 이 화면 고유다: 어디까지 붙여넣었는지는 앱 밖 기억이라, 처리
     표지가 증발하면 복구할 방법이 없다. 잃는 것을 종류별로 명시한다(결정 27 수치 재진술). */
  function guardBody(g) {
    const lost = [];
    if (g.queue_partial) lost.push(`복사 진행 ${g.copied_count}/${g.sel_count}행(처리 표지)`);
    // 선택 재진술 조각은 「작업」 가드와 **공유**(guard.js, 리뷰 F6) — 같은 가드 상태를 두
    // 화면이 다른 문장으로 말하지 않게. 종류별 열거(무엇이 사라지는가)만 이 화면 몫.
    if (g.sel_count) {
      lost.push(window.Guard.selectionLine(g.sel_count, g.filter_active, g.in_def, g.extra));
    }
    if (g.filter_parts > 0) lost.push(`필터 정의 ${g.filter_parts}개 조건`);
    return `다른 데이터를 겨누면 이 큐는 새로 만들어집니다.\n` +
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
      body: guardBody(g),
      confirmLabel: "데이터 바꾸고 버리기",
      cancelLabel: "머무르기",
    });
  }

  /* 웹→Python 이벤트 배선. */
  function wire() {
    // 데이터 존(테이블·열 패널·칩·스트립·전체 선택/해제·문서 레벨 닫기)은 팩토리 몫 배선.
    dz.wire();
    $("tplSel").addEventListener("change", (e) =>
      Bridge.call(SCREEN, "select_template", { name: e.target.value }));

    // 작업점 카드 동사(결정 16) — 큐 네비게이션(↓/↑ 경계 멈춤·점 클릭)·복사(카드 결속·Enter)·
    // 미루기·복사 후 전진 토글. 자유 레코드 스테퍼는 사망(커서가 아니라 큐가 카드를 지나간다).
    $("txtCardPrev").addEventListener("click", () => Bridge.call(SCREEN, "step", { delta: -1 }));
    $("txtCardNext").addEventListener("click", () => Bridge.call(SCREEN, "step", { delta: 1 }));
    $("txtCardDots").addEventListener("click", (e) => {
      const dot = e.target.closest(".wc-dot");
      if (dot) Bridge.call(SCREEN, "set_current", { index: Number(dot.dataset.i) });
    });
    $("txtCardCopy").addEventListener("click", copyCard);
    // Enter=복사(결정 16 Enter 경로) — 코드블록에 포커스가 있을 때. pre 는 비편집이라 안전.
    $("txtCardRender").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); copyCard(); }
    });
    $("txtCardDefer").addEventListener("click", () => {
      if (!$("txtCardDefer").disabled) Bridge.call(SCREEN, "defer", {});  // index 생략=작업점
    });
    $("txtAdvance").addEventListener("change", (e) =>
      Bridge.call(SCREEN, "toggle_advance", { value: e.target.checked }));

    // 대상 글꼴 선언(결정 17) — 값은 Python 이 전역 설정에 영속한다(웹 저장소 아님, #74 전례).
    $("txtTargetFont").addEventListener("change", (e) =>
      Bridge.call(SCREEN, "set_target_font", { font: e.target.value }));
    // 린트 처방(치환·되돌리기) — 버튼은 매 렌더 재생성이라 위임으로 받는다.
    $("txtCardLint").addEventListener("click", (e) => {
      const act = e.target.closest("#txtLintAction");
      if (act) Bridge.call(SCREEN, "set_fullwidth", { value: act.dataset.act === "fix" });
    });

    $("btnPick").addEventListener("click", async () => {
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
    $("btnTxtPoolData").addEventListener("click", async () => {
      await dz.flushPendingSearch();  // 재겨눔 전 검색 정산(위 btnPick 과 같은 규율)
      if (!(await confirmDataSwapIfArmed())) return;  // T3 가드 — 파일 경로와 같은 규율
      await PoolPicker.choose(SCREEN);             // 라벨은 스냅샷(data_source_label)이 채운다
    });

    // 붙여넣기 모달(세션 템플릿) — 개폐·초기포커스·복귀·Escape 는 Modal 헬퍼가 소유(#27/#28).
    $("btnPaste").addEventListener("click", () => {
      $("pasteText").value = LAST ? LAST.template_text : "";
      window.Modal.open("pasteModal", { initialFocus: $("pasteText") });
    });
    $("pasteCancel").addEventListener("click", () => window.Modal.close("pasteModal"));
    $("pasteOk").addEventListener("click", () => {
      // 템플릿만 바꾼다 — 겨눈 데이터는 유지(VM datasource 불변). 라벨은 스냅샷이 실상태 반영(P4).
      Bridge.call(SCREEN, "set_template_text", { text: $("pasteText").value });
      window.Modal.close("pasteModal");
    });
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    const initState = await Bridge.initial(SCREEN);
    const sel = $("tplSel");
    sel.innerHTML = initState.templates
      .map((n) => `<option value="${esc(n)}">${esc(n)}.txt</option>`).join("");
    if (initState.templates.length) sel.value = initState.template_name;
    render(initState);
  }

  // guardBody 는 순수 합성기 — 실앱 게이트가 합성 결과(수치·문안 배치)를 되읽는다(job 관례).
  window.TxtScreen = { init, guardBody };
})();
