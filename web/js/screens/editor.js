/* 문서 작업 편집기 렌더러 — 브리지로 링1 EditorController 와 왕복. **몰입 표면**(#scr-editor,
   재작성 F7 PR-A · 지도 §10.13): 상단 2탭을 덮고 출구는 back 하나다 — 그래야 patch 처분
   (저장·버리기·머무르기)이 한 곳에서 끝난다. 구 「작업」 화면 편집 모드(#jobEditHost)는 사망.
   탭은 계약 §5.1 의 section 문자열(템플릿·필드 연결·표시·파일 이름 — 「시험」은 기각, §10.17.1)이고
   **집합은 Python 이 매체에서 파생**해 내려준다. 신규 초안은 전진 게이트(순서 의존이 실재),
   저장된 작업 편집은 자유 이동 + 처분 가드.
   렌더는 Python 이 window.__push('editor', snapshot) 로 밀어 넣는다.
   표현 계층(탭 UI·매핑표·행 색·표시형 라벨·문맥 배너)만 여기서 만든다 — VM 로직 아님. */
(function () {
  const SCREEN = "editor";
  const $ = (id) => document.getElementById(id);
  // 표시형/타입 라벨은 표현 계층 → 여기(뷰)에 둔다(Qt mapping_table 의 웹 짝).
  const TYPE_LABEL = { text: "텍스트", date: "날짜", amount: "금액", const: "고정값" };
  const INFERRED_LABEL = { text: "텍스트", date: "날짜", amount: "금액", number: "숫자", phone: "전화번호" };
  /* 탭 어휘 = 계약 §5.1 의 section 문자열(재작성 F7 판정 B) — 정수 단계는 사망했다.
     탭 **집합**은 Python 이 매체에서 파생해 내려준다(s.sections): TXT 는 파일 이름 탭이
     없다(§3.2). 계약의 넷째 탭 「시험」은 기각(§10.17.1) — 여기서 목록을 발명하지 않는다. */
  const SECTION_TITLES = {
    template: "템플릿", binding: "필드 연결·표시", filename: "파일 이름",
  };
  let LAST = null;

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  /* 편집기의 브리지 왕복은 **한 줄에 선다**(4R P2 → 5R P2 확장, 공용 `intent.js` 체인).
     blur 로 발화하는 `change` 는 아무도 기다리지 않는 발신이고, 클릭 변이는 **자기 핸들러
     안에서만** 기다린다 — 어느 쪽이든 사용자가 곧바로 back·다른 탭을 누르면 그 발신보다
     먼저 판정이 나서, 방금 한 편집이 아무 확인 없이 좌초한다. 그래서 `change` 만이 아니라
     **상태를 바꾸거나 그 순서에 기대는 왕복 전부**가 이 체인을 지난다(질의도 포함 — 대기 중
     변이 뒤의 답이라야 참이다). `flushPendingEdits` 는 그 줄이 비었음을 뜻한다.

     체인 밖에 남는 것 둘: `Bridge.initial`(첫 스냅샷 당김)과 `Bridge.editorHasUnsavedWork`
     (정산 **뒤** 컨트롤러에게 직접 묻는 질의 — 체인에 넣으면 자기가 기다리는 줄에 선다). */
  const EDIT_CHAIN = "editor:mutate";
  function sendEdit(action, payload) {
    return window.Intent.chained(EDIT_CHAIN, () => Bridge.call(SCREEN, action, payload));
  }
  function flushPendingEdits() {
    return window.Intent.chained(EDIT_CHAIN, () => Promise.resolve());
  }

  // 편집(탭) vs 신규(마법사 단계) — 정보 완전 동등, 공개 방식만 상이(결정 41).
  const isEditing = (s) => !!s.editing_origin;

  // <details> 의 유효 펼침 — 재렌더 관통 보존(PR-3 리뷰 F8: preserve.js 는 details open 을
  // 스냅샷하지 않아 수동으로 연 접힘이 매 push 에 도로 닫혔다). 접힘별 전용 변수(혼합 금지).
  let foldOpen = false;     // 미사용 헤더 접힘(.ign-fold)
  let tokFoldOpen = false;  // 파일명 토큰 참조 접힘(.tok-fold, F27 — PR-4 리뷰 F6)

  /* deep-link 조준 대기 1슬롯(F6 PR-B, §10.14.3) — 보낸 표면(드로어)이 진입 성사 뒤
     `aimAt(target)` 로 건다. 조준 문맥의 push 가 아직이면 여기 걸어 두고 render 가 소비한다
     (브리지 반환과 push 는 독립 채널이라 어느 쪽이 먼저인지 기대지 않는다). */
  let pendingAim = null;

  /* 열린 라이브러리 ⋮ 메뉴의 정체(F8 — tpl 화면 사망의 관리 동사 승계, §10.17.2 판정 D).
     파생 불가: 스냅샷은 「어느 메뉴가 열려 있는가」를 모른다(뷰 상태 — template.js menuFor
     의 이주분, 한 객체로 묶어 1변수). {media, kind:"row"|"group", key?|group?, item?, trigger} */
  let libMenuFor = null;

  /* 관리 기제 = 공용 팩토리·기존 DOM(#tplRowMenu·#tplMoveModal) **재사용, 이식 아님**(F2
     교훈 ④). 관리 동사는 tpl 채널을 그대로 부른다(F1 data_picker→pool 동형 — 컨트롤러·
     잠금·경로 검증 규율 생존, §10.17.2 판정 B). 목록의 정본은 editor 스냅샷 하나다. */
  const libRowMenu = window.GroupList.createMenu({ menuId: "tplRowMenu" });
  const libMoveDialog = window.GroupList.createMoveDialog({
    modalId: "tplMoveModal", listId: "tplMoveList", errId: "tplMoveErr",
    nameId: "tplMoveName", radioName: "tplMove",
    newRadioId: "tplMoveNewRadio", newNameId: "tplMoveNewName",
  });

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    Preserve.around(() => {  // 폼 포커스·캐럿·본문 스크롤 보존(#28)
      // 재구성 전 현 펼침을 읽어 이월(수동 개폐 존중) — 접힘별 전용 클래스로 분리 판독.
      const fold = document.querySelector("#scr-editor details.ign-fold");
      if (fold) foldOpen = fold.open;
      const tokFold = document.querySelector("#scr-editor details.tok-fold");
      if (tokFold) tokFoldOpen = tokFold.open;
      LAST = s;
      renderHead(s);
      renderContext(s);
      $("editor-steps").innerHTML = stepHeader(s);
      $("editor-body").innerHTML = stepBody(s);
      $("editor-foot").innerHTML = footer(s);
      $("editor-foot").style.display = footer(s) ? "" : "none";
    });
    // 조준은 Preserve **밖**에서 — 안에서 겨누면 되돌림이 새 초점을 이전 초점으로 덮는다.
    if (pendingAim && s.context && s.context.target === pendingAim) {
      const target = pendingAim;
      pendingAim = null;
      aimAtTarget(s, target);
    }
  }

  /* 조준 실행 — 행이 없으면 fail-open(스키마 드리프트: 탭 착지·배너 증거는 그대로 참이고,
     없는 행에 가짜 초점을 세우지 않는다). 초점 대상은 사람이 고치러 온 그 컨트롤이다. */
  function aimAtTarget(s, target) {
    if (target === "filename/filenamePattern") {
      const el = document.querySelector('#editor-body input[data-act="pattern"]');
      if (el) el.focus();
      return;
    }
    const field = target.slice("binding/".length);
    const row = document.querySelector(
      `#editor-body table.map tr[data-field="${CSS.escape(field)}"]`);
    if (!row) return;
    row.scrollIntoView({ block: "center" });
    const sel = row.querySelector('select[data-act="row-source"]');
    if (sel) sel.focus();
  }

  /* 드로어가 진입 성사 뒤 부르는 조준 seam(F6 PR-B). 조준 문맥이 이미 도착했으면 즉시,
     아니면 다음 render 가 소비한다 — 두 순서 모두에서 정확히 한 번 겨눈다. */
  function aimAt(target) {
    const ctx = (LAST && LAST.context) || {};
    if (ctx.target === target) {
      aimAtTarget(LAST, target);
      return;
    }
    pendingAim = target;
  }

  /* 머리 — 이름(안정 입력)·부제·저장 상태 + 판본. 「저장」 분류 사망의 승계처(§10.13.3).
     이름 입력은 innerHTML 로 다시 짓지 않는다: 매 push 마다 다시 지으면 아직 change 로
     확정되지 않은 타이핑이 스냅샷 값으로 조용히 덮인다. 포커스 중엔 값도 건드리지 않는다. */
  function renderHead(s) {
    const nameEl = $("editorName");
    if (nameEl && document.activeElement !== nameEl && nameEl.value !== s.name) {
      nameEl.value = s.name || "";
    }
    $("editorSubtitle").textContent = s.template_name
      ? `템플릿 ${s.template_name}` : "템플릿을 아직 고르지 않았습니다.";
    // 판본(§10.13 판정 O 표시 자리 ①) — 저장된 작업만 세대가 있다. 초안에 r1 을 붙이면
    // 저장되지도 않은 규칙에 있지도 않은 세대를 말하게 된다.
    const st = $("editorSaveState");
    const rev = s.revisions || {};
    // 세션 수준 dirty 는 **Python 이 낸 값 하나**를 읽는다(3R 근본 조치) — 여기서
    // `dirty_sections` 로 다시 조립하면 이름처럼 section 밖의 편집을 「저장됨」이라 말한다.
    const dirty = !!s.dirty;
    if (s.is_draft) {
      st.dataset.level = "idle";
      st.textContent = "아직 저장하지 않은 새 작업";
    } else {
      st.dataset.level = dirty ? "warn" : "idle";
      st.textContent = (dirty ? "저장하지 않은 변경 · " : "저장됨 · ")
        + `템플릿 r${rev.template || "?"} · 연결 r${rev.binding || "?"}`;
    }
  }

  /* 진입 문맥 배너(계약 §5.1) — 왜 왔는지·무엇을 보고 왔는지·어디로 돌아가는지.
     증거는 **보낸 표면이 본 것**을 그대로 싣는다(편집기가 다시 계산하면 배너와 화면이
     갈린다). 사유가 자발적 진입이면 배너 자체를 세우지 않는다 — 할 말이 없으면 침묵. */
  const ENTRY_LEAD = {
    library: "「문서 작업」에서 열었습니다.",
    preview_result: "미리보기에서 열었습니다.",
    run_failure: "생성 실패 결과에서 열었습니다.",
    output_result: "생성 결과에서 열었습니다.",
    document_browser_repair: "실행을 막는 문제를 고치러 열었습니다.",
  };
  const RETURN_LABEL = {
    data: "문서 만들기로 돌아가기", preview: "미리보기로 돌아가기",
    result: "결과로 돌아가기", library: "「문서 작업」으로 돌아가기",
    documents: "문서 탐색으로 돌아가기",
  };
  function renderContext(s) {
    const box = $("editorContext");
    const ctx = s.context || {};
    const lead = ENTRY_LEAD[ctx.entry_reason];
    if (!lead) { box.style.display = "none"; box.innerHTML = ""; return; }
    const ev = ctx.evidence || {};
    const rows = Object.keys(ev).map((k) =>
      `<span><b>${esc(k)}</b> ${esc(ev[k])}</span>`).join("");
    const surface = (ctx.return_context || {}).surface;
    const back = RETURN_LABEL[surface]
      ? `<button class="btn sm" data-act="context-return">${esc(RETURN_LABEL[surface])}</button>` : "";
    box.style.display = "";
    box.innerHTML = `<div class="row"><b>${esc(lead)}</b><span class="spacer"></span>${back}</div>` +
      (rows ? `<div class="ctx-ev">${rows}</div>` : "");
  }

  /* 헤더: 신규=단계 표지(번호·게이트), 편집=탭(자유 이동 버튼). 같은 .wstep-tab 룩 재사용. */
  function stepHeader(s) {
    const sections = s.sections || [];
    const here = sections.indexOf(s.section);
    if (isEditing(s)) {
      return sections.map((sec) => {
        const cur = sec === s.section ? ' aria-current="true"' : "";
        const dirty = (s.dirty_sections || []).includes(sec) ? " dirty" : "";
        return `<button class="wstep-tab as-tab${dirty}" data-act="goto-tab" data-section="${esc(sec)}"${cur}>` +
          `${esc(SECTION_TITLES[sec] || sec)}</button>`;
      }).join("");
    }
    return sections.map((sec, i) => {
      const cur = sec === s.section ? ' aria-current="true"' : "";
      const done = i < here ? " done" : "";
      return `<div class="wstep-tab${done}"${cur}><span class="k">${i + 1}</span>${esc(SECTION_TITLES[sec] || sec)}</div>`;
    }).join("");
  }

  /* 본문 표제 — 신규는 단계 서수를 말하고(순서 의존이 실재), 편집은 탭 이름만 말한다. */
  function stageTitle(s, section) {
    const title = SECTION_TITLES[section] || section;
    if (isEditing(s)) return title;
    const i = (s.sections || []).indexOf(section);
    return i < 0 ? title : `${i + 1}단계: ${title}`;
  }

  function stepBody(s) {
    // 세션 통지(#26) — 문제(warn)만 시끄럽게, 정상(ok)은 muted 한 줄(F32).
    const notice = s.notice
      ? `<p class="note ${s.notice.level === "ok" ? "quiet" : "warnbox"}" style="white-space:pre-line">${esc(s.notice.text)}</p>`
      : "";
    if (s.section === "template") return notice + templateStage(s);
    if (s.section === "binding") return notice + mappingStage(s);
    return notice + saveStage(s);
  }

  /* ---- 분류 0: 템플릿 — 신규 1단계 = **라이브러리에서 그룹 구획으로 고르기**(#108 슬라이스 3).
     관리 화면과 **같은 그룹 모델·같은 접힘**(선택 전용). **매체 2밴드**(F6 PR-B — 구 「기안」
     화면 사망의 생성 경로 승계처): HWPX 서식·TXT 기안을 한 피커가 보이고, 고른 확장자가 세션
     매체(탭 구성·저장 게이트)를 정한다. 행 클릭은 두 밴드 모두 기존 use_library_template
     하나다(신규 액션 0). 바깥 파일은 「가져오기…」=라이브러리로 복사 후 그 사본으로
     시작(앱 소유 루트 — 원본 수정 불파급). ---- */
  // 행 꼬리 관리 어포던스(F8 — tpl 화면 사망의 승계): 「그룹 없음」 행만 ＋그룹지정 칩,
  // 모든 행에 ⋮(오류·손상 행 포함 — 삭제 도달성, F1 ⓒ와 같은 뿌리).
  function libRowTail(media, t) {
    const chip = t.group ? "" :
      `<button class="tpl-assign" data-act="lib-assign" data-media="${media}" data-key="${esc(t.key)}">＋ 그룹 지정</button>`;
    return `${chip}<button class="job-more" data-act="lib-more" data-media="${media}"` +
      ` data-key="${esc(t.key)}" aria-haspopup="true" aria-label="템플릿 관리">⋮</button>`;
  }

  function libRow(t) {
    // 상태 사유(detail)는 배지 title 로 — 오류 행은 선택 버튼 대신 사유를 보여준다(리뷰 F8:
    // 죽은 버튼이 생 예외 alert 로 끝나는 반쪽 노출 금지 — 원인 있는 사용 불가).
    const badge = t.badge_label
      ? `<span class="tbadge" title="${esc(t.detail || "")}">${esc(t.badge_label)}</span>` : "";
    const pick = t.is_error
      ? `<span class="muted capnote" title="${esc(t.detail || "")}">사용 불가</span>`
      : (t.current
        ? `<span class="muted capnote">선택됨</span>`
        : `<button class="btn sm" data-act="use-library" data-path="${esc(t.path)}">이 템플릿으로</button>`);
    // 채움 완화 사전 고지(#154) — tpl 카드 warn 줄의 승계. 문안은 링1 확정.
    const warns = (t.fill_warns || []).map(
      (w) => `<div class="hint warn">${esc(w)}</div>`
    ).join("");
    // .fname 이 남는 폭을 먹고 말줄임(F14) — 배지·동작은 고정폭이라 스페이서 불필요.
    return `<div class="libselrow${t.current ? " cur" : ""}"><span class="fname">${esc(t.name)}</span>` +
      `${badge}${pick}${libRowTail("hwpx", t)}</div>${warns}`;
  }

  // TXT 밴드 행(F6 PR-B) — 상태 축이 다르다: 필드 수(토큰 유무의 사전 신호)·읽기 오류.
  function txtLibRow(t) {
    const badge = t.error
      ? `<span class="tbadge" title="${esc(t.error)}">읽기 오류</span>`
      : `<span class="tbadge">필드 ${t.field_count}</span>`;
    const pick = t.error
      ? `<span class="muted capnote" title="${esc(t.error)}">사용 불가</span>`
      : (t.current
        ? `<span class="muted capnote">선택됨</span>`
        : `<button class="btn sm" data-act="use-library" data-path="${esc(t.path)}">이 템플릿으로</button>`);
    return `<div class="libselrow${t.current ? " cur" : ""}"><span class="fname">${esc(t.name)}</span>` +
      `${badge}${pick}${libRowTail("txt", t)}</div>`;
  }

  function libGroupHead(sec, idx, media) {
    const label = sec.group || "그룹 없음";
    // 안정 id(#138 리뷰 F13) — 재렌더 뒤 Preserve 가 같은 헤더로 키보드 포커스를 복원한다
    // (구획 순서는 접힘 토글에 불변이라 밴드+인덱스가 안정 식별자다).
    // 명명 그룹만 ⋮(이름 변경·해산 — F8, tpl 그룹 헤더 승계). 「그룹 없음」은 관리 대상 아님.
    const more = sec.group
      ? `<button class="job-more grp-more" data-act="lib-grp-more" data-media="${media}"` +
        ` data-group="${esc(sec.group)}" aria-haspopup="true" aria-label="그룹 관리">⋮</button>`
      : "";
    return `<div class="job-grp"><button class="job-grp-head" id="libgrp-${media}-${idx}" data-act="toggle-lib-group"` +
      ` data-group="${esc(sec.group)}" data-media="${media}" aria-expanded="${sec.collapsed ? "false" : "true"}">` +
      `<span class="grp-name">${esc(label)}</span><span class="grp-count">${sec.count}</span>` +
      `<span class="grp-caret">${sec.collapsed ? "▸" : "▾"}</span></button>${more}</div>`;
  }

  // 한 매체 밴드의 본문 — 그룹 구획(퇴화 시 평면), 빈 밴드는 조치 안내 한 줄.
  function libraryBand(band, media, rowFn, emptyText) {
    const sections = (band && band.sections) || [];
    const total = sections.reduce((n, sec) => n + (sec.items ? sec.items.length : 0), 0);
    if (!total) {
      return `<div class="muted" style="padding:var(--sp-8)">${emptyText}</div>`;
    }
    if (band.flat) {
      // 퇴화 불변식(그룹 0개) — 헤더 없는 평면 나열.
      return `<div class="tpl-grp-rows flat">` +
        sections.map((sec) => sec.items.map(rowFn).join("")).join("") + `</div>`;
    }
    return sections.map((sec, i) =>
      libGroupHead(sec, i, media) +
      (sec.collapsed ? "" : `<div class="tpl-grp-rows">${sec.items.map(rowFn).join("")}</div>`)
    ).join("");
  }

  function libraryPicker(s) {
    const lib = s.library || {};
    const hw = lib.hwpx || {}, tx = lib.txt || {};
    // 라이브러리 결과 재진술 줄(F8 — `#tplResult` 승계): 성형·수명은 tpl 컨트롤러 소유,
    // 여기는 스냅샷의 완성 문안을 그리기만 한다. 빈 결과는 자리도 차지하지 않는다.
    const res = lib.result || {};
    const resultLine = res.text
      ? `<div class="run-result${res.level && res.level !== "muted" ? " " + esc(res.level) : ""}">${esc(res.text)}</div>`
      : "";
    // 밴드 캡션: 개수 + 라이브러리 루트 경로(tpl `#tplHwpxCount`·`#tplLibDir` 승계 —
    // 점검표 10행). 경로는 말줄임 대신 title 로 전문 노출.
    const bandCap = (label, band) =>
      `<span class="cap">${label}</span>` +
      (band.count ? `<span class="muted capnote">${band.count}개</span>` : "") +
      (band.dir ? `<span class="muted capnote mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:22em" title="${esc(band.dir)}">${esc(band.dir)}</span>` : "");
    return `<div class="grp">
      <div class="row" style="margin-bottom:var(--sp-4)">${bandCap("HWPX 서식", hw)}
        <span class="spacer"></span>
        <button class="btn sm" data-act="import-template">가져오기…</button></div>
      <p class="note quiet" style="margin-top:0">누름틀에 채운 .hwpx 문서 파일을 만드는 작업입니다.</p>
      ${libraryBand(lib.hwpx, "hwpx", libRow,
        "라이브러리에 템플릿이 없습니다. '가져오기…'로 추가하세요.")}
    </div>
    <div class="grp">
      <div class="row" style="margin-bottom:var(--sp-4)">${bandCap("TXT 기안", tx)}</div>
      <p class="note quiet" style="margin-top:0">채운 본문을 검토하고 복사해 쓰는 작업입니다. 파일은 만들지 않습니다.</p>
      ${libraryBand(lib.txt, "txt", txtLibRow,
        "TXT 기안 템플릿이 없습니다. '가져오기…'로 추가하거나 새로 만드세요.")}
    </div>${resultLine}`;
  }

  /* ---- 라이브러리 관리 동사(F8 — tpl 화면 사망의 승계, §10.17.2 판정 B·D) ----
     디스패치는 tpl 채널 그대로(잠금·경로 검증·휴지통 규율 생존) — 몸통은 template.js 에서
     이식했고, tpl push 를 init 의 구독이 받아 editor 스냅샷을 재당김해 되그린다. */
  function findLibItem(media, key) {
    const band = ((LAST && LAST.library) || {})[media] || {};
    for (const sec of band.sections || []) {
      for (const it of sec.items || []) if (it.key === key) return it;
    }
    return null;
  }

  function closeLibMenu() {
    libMenuFor = null;
    libRowMenu.hide();
  }

  function openLibMenu(media, kind, id, btn) {
    let html;
    if (kind === "group") {
      html =
        `<button data-menu="grp-rename">그룹 이름 변경</button>` +
        `<button data-menu="grp-disband">그룹 해산</button>`;
      libMenuFor = { media, kind, group: id, trigger: btn };
    } else {
      const it = findLibItem(media, id);
      // 소비 동사(「이 템플릿으로」)는 행 버튼이 이미 소유 — 메뉴는 관리 동사만(2벌 금지,
      // §10.17.2 판정 D). 무그룹 행의 그룹 지정은 ＋그룹지정 칩이 담당.
      html =
        (it && it.group ? `<button data-menu="move">그룹으로 이동…</button>` : "") +
        `<button data-menu="delete" class="danger">삭제</button>`;
      libMenuFor = { media, kind, key: id, item: it, trigger: btn };
    }
    libRowMenu.show(html, btn);  // 위치잡기·표시는 팩토리 소유(job.js·template.js 와 단일 출처)
  }

  function toggleLibMenu(media, kind, id, btn) {
    const same = libMenuFor && libMenuFor.kind === kind && libMenuFor.media === media &&
      (kind === "group" ? libMenuFor.group === id : libMenuFor.key === id);
    if (same) { closeLibMenu(); return; }
    openLibMenu(media, kind, id, btn);
  }

  async function onLibMenuClick(e) {
    const btn = e.target.closest("button[data-menu]");
    if (!btn || !libMenuFor) return;
    const m = libMenuFor, act = btn.dataset.menu;
    closeLibMenu();
    try {
      if (act === "move") openLibMoveDialog(m.media, m.item, m.trigger);
      else if (act === "delete") await deleteLibTemplate(m.media, m.item);
      else if (act === "grp-rename") await renameLibGroup(m.media, m.group, m.trigger);
      else if (act === "grp-disband") await disbandLibGroup(m.media, m.group, m.trigger);
    } catch (err) {
      window.alert(String((err && err.message) || err));
    }
  }

  function openLibMoveDialog(media, item, returnFocus) {
    if (!item) return;
    const band = ((LAST && LAST.library) || {})[media] || {};
    libMoveDialog.open({
      nameText: item.name,
      groups: band.group_names || [],
      current: item.group || "",
      returnFocus,
      onConfirm: (group) =>
        Bridge.call("tpl", "set_group", { media, key: item.key, group })
          .catch((err) => window.alert(String((err && err.message) || err))),
    });
  }

  async function renameLibGroup(media, old, returnFocus) {
    const val = await Modal.prompt({
      title: "그룹 이름 변경", body: `'${old}' 의 새 이름`, value: old, returnFocus,
    });
    if (val === null) return;
    const r = await Bridge.call("tpl", "rename_group", { media, group: old, new: val });
    if (r && r.needs_confirm) {
      if (await Modal.confirm({
        body: `'${r.new}' 그룹이 이미 있습니다. '${old}' 의 ${r.count}개를 '${r.new}'(${r.target}개)에 합칠까요?`,
        confirmLabel: "합치기", cancelLabel: "취소", returnFocus,
      })) {
        await Bridge.call("tpl", "rename_group", { media, group: old, new: val, confirm: true });
      }
    } else if (r && r.error) {
      window.alert(r.error);
    }
  }

  async function disbandLibGroup(media, name, returnFocus) {
    const r = await Bridge.call("tpl", "disband_group", { media, group: name });
    if (r && r.needs_confirm && (await Modal.confirm({
      body: `'${name}' 그룹을 해산하면 ${r.count}개가 '그룹 없음'으로 이동합니다. 해산할까요?`, returnFocus,
      confirmLabel: "해산", cancelLabel: "취소",
    }))) {
      await Bridge.call("tpl", "disband_group", { media, group: name, confirm: true });
    }
  }

  async function deleteLibTemplate(media, item) {
    if (!item) return;
    const r = await Bridge.call("tpl", "delete", { media, path: item.path });
    if (r && r.undo) window.UndoToast.show(`템플릿 '${item.name}' 을(를) 휴지통으로 옮겼습니다.`, async () => {
      const restored = await Bridge.call("tpl", "undo_delete", {});
      if (restored && restored.ok === false) throw new Error(restored.error);
    });
  }

  function templateStage(s) {
    let out = `<div class="wtitle">${esc(stageTitle(s, "template"))}</div>
      <p class="wsub">만들 작업의 템플릿을 고르세요.</p>
      ${libraryPicker(s)}`;
    if (s.template_name) {
      out += `<div class="row"><span class="lbl">선택한 템플릿</span>
        <span class="filechip"><b>${esc(s.template_name)}</b></span>
        ${PathTrack.affordances(s.template_path)}</div>`;
      out += provenanceBlock(s);   // 「저장」 분류 사망의 승계(§10.13.3) — 템플릿·필드 어휘의 지문
    }
    if (s.raw_block) {
      out += `<p class="note dangerbox" style="white-space:pre-line">${esc(s.raw_block)}</p>`;
    } else if (s.gate_error) {
      out += `<p class="note dangerbox">템플릿 상태를 확인할 수 없습니다. 진행할 수 없습니다.</p>`;
    } else if (s.field_count) {
      out += schemaTable(s);
      if (s.gate) {
        out += `<div class="note warnbox" style="white-space:pre-line">${esc(s.gate.message)}</div>`;
        if (!s.gate.acked) {
          out += `<button class="btn" data-act="ack-gate">비우고 진행 확인 (${s.gate.unmet.length}개 토큰)</button>`;
        }
      }
    }
    return out;
  }

  // 1단계 필드표: 나열식 요약을 구조화(#16 98DDFE96). 필드·추정타입·위치·문맥.
  function schemaTable(s) {
    const rows = (s.fields || []).map((f) => {
      const type = INFERRED_LABEL[f.inferred_type] || f.inferred_type || "";
      const where = f.in_table ? "표 안" : "본문";  // in_table → 위치 라벨(색 아닌 텍스트)
      const ctx = f.context || "";
      const ctxCell = ctx
        ? `<span title="${esc(ctx)}">${esc(ctx)}</span>`
        : `<span class="pv emptyval">—</span>`;
      return `<tr>
        <td><span class="fname">${esc(f.name)}</span></td>
        <td><span class="tbadge">${esc(type)}</span></td>
        <td class="muted">${esc(where)}</td>
        <td class="fctx">${ctxCell}</td></tr>`;
    }).join("");
    return `<p class="fields-head">${esc(s.schema_summary)}</p>
      <div class="tblwrap"><table class="schema-fields"><thead><tr>
        <th>필드</th><th>추정 타입</th><th>위치</th><th>문맥</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
  }

  // 데이터 미리보기: 컬럼 헤더 + 샘플 행 그리드(#16). F21 열 압축(블록 2 결정 14): 미리보기
  // 열 = 활성 헤더만(미사용 열은 뷰에서 제외, 재활성 시 복귀). 매핑표 행은 반대로 안 숨긴다
  // (mapRow 의무 잔존, 조용한 빈칸 금지) — 여긴 데이터 감(感)을 주는 미리보기라 압축이 맞다.
  function dataPreview(s) {
    if (!s.record_count) return "";
    const all = s.source_fields || [];
    const active = new Set(s.active_source_fields || all);
    // sample_rows 는 전체 source_fields 순서로 투영된 배열 — 원 인덱스를 물고 활성 열만 남긴다.
    const cols = all.map((name, i) => ({ name, i })).filter((c) => active.has(c.name));
    const head = cols.map((c) => `<th title="${esc(c.name)}">${esc(c.name)}</th>`).join("");
    const sample = s.sample_rows || [];
    const body = sample.map((row) =>
      `<tr>${cols.map((c) => {
        const v = row[c.i];
        return (v === "" || v == null)
          ? `<td><span class="pv emptyval">(빈 값)</span></td>`  // ADR-B: 빈 셀 시끄럽게
          : `<td><span class="pv">${esc(v)}</span></td>`;
      }).join("")}</tr>`).join("");
    const hiddenCols = all.length - cols.length;
    const colNote = hiddenCols
      ? ` · 열 ${cols.length}/${all.length} (미사용 ${hiddenCols}열 제외)`
      : ` · 전체 ${all.length}열`;
    const more = s.record_count > sample.length
      ? `<p class="fields-head muted">샘플 ${sample.length}행 표시(외 ${s.record_count - sample.length}행)</p>`
      : "";
    return `<p class="fields-head">${s.record_count}행 불러옴${colNote}.</p>
      <div class="tblwrap"><table class="data-preview"><thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody></table></div>${more}`;
  }

  /* 데이터 관문(F18·F20) — 매핑 단계의 머리(3단계 접기). 파일 선택/바꾸기 + '데이터 없이
     진행' 옵트아웃. 선택과 결과가 같은 지면: 파일을 고르면 매핑표가 그 자리에서 차오른다
     (Python 이 load_data_path 에서 모델 재구성 → 다음 push). 작업엔 데이터가 저장되지 않는다. */
  function dataGateway(s) {
    const has = !!s.data_path;
    const picker = has
      ? `<span class="filechip"><b>${esc(s.data_name)}</b>${s.data_sheet ? ` <span class="sheet">시트: ${esc(s.data_sheet)}</span>` : ""}</span>
         <button class="btn" data-act="pick-data">바꾸기…</button>`
      : `<button class="btn primary" data-act="pick-data">파일 선택…</button>`;
    return `<div class="row gateway">
      <span class="lbl">이 작업의 데이터</span>
      ${picker}
      <button class="btn linklike" data-act="skip-data">데이터 없이 진행</button>
      ${has ? PathTrack.affordances(s.data_path) : ""}</div>`;
  }

  /* 사용할 헤더 = 칩-라이브(결정 12·13). 체크박스 스테이징 소거 — 칩 클릭이 곧 즉시 토글.
     활성 칩(클릭=미사용) + 미사용 접힘 구역(칩 클릭=다시 사용) + 전체 사용/전체 미사용 대칭쌍.
     활성 변화는 백엔드 apply_active_sources 가 처리: 미접촉 행은 라이브 재제안, 사람 소유
     행은 소스가 꺼지면 R4 시끄러운 강등(notice). '전체 미사용' 후 미사용 구역 자동 펼침. */
  function headerSelect(s) {
    // 헤더 선택은 데이터가 로드됐을 때만(관문 겨눔 후) 성립한다 — 편집 모드처럼 데이터 없이
    // source_fields 가 저장 매핑 어휘에서 채워진 경우엔 '사용할 헤더'가 없다(복원 행을 헤더
    // 토글로 언매핑하는 유령 표면 방지, 리뷰 F4). mockup 상태 1(파일 겨눔 후)=칩벽 등장.
    const all = s.source_fields || [];  // 전체 헤더(스냅샷 계약 키) — 활성/미사용은 파생
    if (!all.length || !s.record_count) return "";
    const active = new Set(s.active_source_fields || []);
    const ignored = s.ignored_source_fields || [];
    const activeChips = all.filter((f) => active.has(f)).map((f) =>
      `<button class="hchip on" data-act="toggle-header" data-field="${esc(f)}" title="클릭 = 미사용으로">${esc(f)}</button>`
    ).join("") || '<span class="muted">사용 중인 데이터 열이 없습니다. 아래 미사용 목록에서 골라 켜세요.</span>';
    // 미사용 = 벽 이탈 + 접힘 구역(결정 13). '전체 미사용'이 ignored_expanded 로 자동 펼침.
    const ignoredBlock = ignored.length
      ? `<details class="hidden-hdrs ign-fold"${(s.ignored_expanded || foldOpen) ? " open" : ""}><summary>미사용 ${ignored.length}개 (펼쳐 다시 사용)</summary>
           <div class="hchips">${ignored.map((f) =>
              `<button class="hchip ign" data-act="toggle-header" data-field="${esc(f)}" title="클릭 = 다시 사용">${esc(f)}</button>`).join("")}</div>
           <p class="hint" style="margin-top:var(--sp-4)">미사용 데이터 열은 자동 매핑 제안·소스 후보에서 빠집니다.</p>
         </details>`
      : "";
    return `<div class="grp">
      <div class="row" style="margin-bottom:var(--sp-4)"><span class="cap">사용할 데이터 열</span>
        <span class="muted" style="margin-left:var(--sp-8)">${all.length}개 중 ${s.active_count}개 사용</span>
        <span class="spacer"></span>
        ${s.ignored_count ? `<button class="btn sm" data-act="use-all-headers">전체 사용</button>` : ""}
        <button class="btn sm" data-act="use-none">전체 미사용</button>
      </div>
      <div class="hchips">${activeChips}</div>
      ${ignoredBlock}
    </div>`;
  }

  /* ---- 분류 1: 필드 매핑 (데이터 관문 내장, 3단계 접기) ---- */
  function mappingStage(s) {
    const rows = (s.rows || []).map((r) => mapRow(r, s)).join("");
    const stepper = s.preview_count
      ? `<button class="btn sm" data-act="prev-rec">◀ 이전 행</button>
         <span class="mono">행 ${s.preview_index}/${s.preview_count}</span>
         <button class="btn sm" data-act="next-rec">다음 행 ▶</button>`
      : `<span class="muted">행 0/0 · 데이터 없음(템플릿 필드만)</span>`;
    const counts = s.counts
      ? `<span class="muted">채움 ${s.counts.filled} · 빈 값 ${s.counts.empty} · 미매핑 ${s.counts.unmapped}` +
        `${s.preview_empties && s.preview_empties.length ? " (" + esc(s.preview_empties.join(", ")) + ")" : ""}</span>`
      : "";
    const banner = s.schema_only
      ? `<p class="note warnbox">데이터 없이 매핑 중입니다. 고정값을 넣거나 비움으로 확정하세요.</p>`
      : "";
    return `<div class="wtitle">${esc(stageTitle(s, "binding"))}</div>
      <p class="wsub">필드마다 데이터 열을 지정하고 전 행을 확정하세요.</p>
      ${dataGateway(s)}
      ${datasetBlock(s)}
      ${defaultDatasetBlock(s)}
      ${headerSelect(s)}
      ${banner}
      <div class="tblwrap"><table class="map"><thead><tr>
        <th>확정</th><th>템플릿 필드 · 추정</th><th>데이터 열</th>
        <th>타입 / 고정값</th><th>표시형</th><th>미리보기</th><th>상태</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <div class="stepper">${stepper}<span class="spacer"></span>${counts}</div>
      <div class="gate">
        <span class="gatecount ${s.is_complete ? "ok" : "pend"}">확정 ${(s.rows || []).filter((r) => r.confirmed).length}/${(s.rows || []).length}</span>
        <span class="spacer"></span>
        <button class="btn" data-act="confirm-all">모두 확정</button>
        <button class="btn" data-act="unconfirm-all">모두 해제</button>
        ${s.unconfirm_undo_count ? `<button class="btn" data-act="restore-confirmed">직전 확정 ${s.unconfirm_undo_count}개 복원</button>` : ""}
      </div>
      ${dataPreview(s)}`;
  }

  // 소유권 태그(칩-라이브 결정 12) — 확정/수동(touched)/제안(시스템)/후보 없음.
  function ownerTag(r, s) {
    if (r.confirmed) return `<span class="tag conf">확정</span>`;
    if (r.touched) return `<span class="tag man">수동</span>`;
    if (r.source) return `<span class="tag sugg">제안</span>`;  // 시스템 소유(활성 따라 유동)
    // 미접촉·소스 없음: 데이터 있으면 '후보 없음', 스키마온리면 중립(오경보 방지).
    return s.record_count ? `<span class="tag none">후보 없음</span>` : `<span class="tag none">—</span>`;
  }

  function mapRow(r, s) {
    // 후보는 활성 헤더만(#49) — 미사용 헤더는 소스 드롭다운에서 빠진다.
    const candidates = s.active_source_fields || s.source_fields || [];
    const known = candidates.includes(r.source);
    const srcOpts = [`<option value=""${r.source ? "" : " selected"}>(비움)</option>`]
      .concat(candidates.map((f) =>
        `<option value="${esc(f)}"${f === r.source ? " selected" : ""} title="${esc(f)}">${esc(f)}</option>`))
      // 복원·데이터 교체로 현재 소스 목록에 없는 소스를 참조하는 행 — (비움)으로
      // 오표시하지 않고 명시 옵션으로 시끄럽게 드러낸다(#26 조용한 소실 금지).
      .concat(r.source && !known
        ? [`<option value="${esc(r.source)}" selected title="현재 데이터에 없는 소스">${esc(r.source)} (데이터에 없음)</option>`]
        : [])
      .join("");
    // 수동(touched·미확정) 행만 전용 '↩' 버튼으로 자동 제안 복귀(리뷰 R5: 센티넬 옵션은 동명
    // 실열과 충돌 — 별도 액션 revert-source). 확정 행은 제외(PR-3 리뷰 F2: 확정도 touched 라
    // 무가드면 오클릭 한 번에 확정이 풀리고 다른 열로 치환 — 확정 해제가 의식적 1단계).
    // 데이터 있을 때만(재제안할 활성 소스가 있어야).
    const revertBtn = r.touched && !r.confirmed && s.record_count
      ? ` <button class="btn sm" data-act="revert-source" data-index="${r.index}" title="자동 제안으로 되돌리기">↩</button>`
      : "";
    const typeOpts = (s.type_options || []).map((t) =>
      `<option value="${esc(t)}"${t === r.type ? " selected" : ""}>${esc(TYPE_LABEL[t] || t)}</option>`).join("");
    const fmtList = (s.fmt_options && s.fmt_options[r.type]) || [];
    const fmtOpts = fmtList.length
      ? fmtList.map((o) => `<option value="${esc(o.code)}"${o.code === r.fmt ? " selected" : ""}>${esc(o.label)}</option>`).join("")
      : `<option value="">—</option>`;
    const constInput = r.type === "const"
      ? `<input class="sel" data-act="row-const" data-index="${r.index}" value="${esc(r.const)}" placeholder="고정값">`
      : "";
    const inferred = INFERRED_LABEL[r.inferred_type] || r.inferred_type || "";
    let preview;
    if (r.preview_error) preview = `<span class="pv emptyval">(미리보기 오류)</span>`;
    else if (r.preview_empty) preview = `<span class="pv emptyval">(이 행에서 빈 값)</span>`;
    else preview = `<span class="pv">${esc(r.preview)}</span>`;
    return `<tr class="r-${r.row_state}" data-field="${esc(r.template_field)}">
      <td><input type="checkbox" class="cbx" data-act="row-confirm" data-index="${r.index}"${r.confirmed ? " checked" : ""}></td>
      <td><span class="fname" title="${esc(r.context || r.template_field)}">${esc(r.template_field)}</span>
        <span class="tbadge">[추정: ${esc(inferred)}]</span></td>
      <td><select class="sel" data-act="row-source" data-index="${r.index}">${srcOpts}</select>${revertBtn}</td>
      <td><select class="sel" data-act="row-type" data-index="${r.index}">${typeOpts}</select> ${constInput}</td>
      <td><select class="sel" data-act="row-fmt" data-index="${r.index}"${fmtList.length ? "" : " disabled"}>${fmtOpts}</select></td>
      <td>${preview}</td>
      <td>${ownerTag(r, s)}</td></tr>`;
  }

  /* ---- 탭: 파일 이름 — 대조표 20행의 승격(저장 단계 인라인 → 전용 탭).
     이름·자동등록·기본 데이터·작성 출처는 각자의 거처로 흩어졌다(§10.13.3 승계 정산):
     이름=머리, 자동등록·기본 데이터=연결 탭의 데이터 관문, 작성 출처=템플릿 탭. ---- */
  function saveStage(s) {
    return `<div class="wtitle">${esc(stageTitle(s, "filename"))}</div>
      <p class="wsub">이 작업이 만드는 파일의 이름 규칙입니다. HWPX 작업의 영구 규칙이고,
        이번 생성에서만 쓸 값은 여기 두지 않습니다.</p>
      <div class="row"><span class="lbl lbl-fixed">파일명 패턴</span>
        <input class="field mono" data-act="pattern" value="${esc(s.pattern)}"></div>
      ${s.pattern_preview ? `<p class="hint mono" style="margin-top:0">예: ${esc(s.pattern_preview)}${s.record_count ? " (표본 1행 기준)" : ""}</p>` : ""}
      ${filenameTokenHelp(s)}
      <div id="save-msg" class="note" style="display:none"></div>`;
  }

  /* 작성 출처 provenance(#53-C) — 이 매핑이 어느 템플릿·데이터 스키마에서 작성됐는지
     되짚는 설명 메타(실행 게이트 아님). 편집 모드에서 복원된 경우만 표시. */
  function provenanceBlock(s) {
    const p = s.provenance;
    if (!p) return "";
    const when = p.updated_at
      ? (p.authored_at && p.authored_at !== p.updated_at
          ? `작성 ${esc(p.authored_at)} · 갱신 ${esc(p.updated_at)}`
          : `작성 ${esc(p.updated_at)}`)
      : "";
    const line = (label, val) =>
      val ? `<div class="hint" style="margin-top:0"><b>${label}</b> ${esc(val)}</div>` : "";
    const drift = (p.template_fields && s.fields && s.fields.length
        && p.template_fields !== s.fields.map((f) => f.name).join(" · "))
      ? `<div class="hint danger" style="margin-top:var(--sp-4)">⚠ 작성 당시와 템플릿 필드 구성이 다릅니다. 매핑 재검토가 필요할 수 있습니다.</div>`
      : "";
    return `<div class="grp">
      <span class="cap">작성 출처</span>
      ${line("템플릿", p.template)}
      ${line("데이터", p.dataset)}
      ${line("템플릿 필드", p.template_fields)}
      ${line("데이터 열", p.source_keys)}
      ${when ? `<div class="hint muted" style="margin-top:0">${when}</div>` : ""}
      ${drift}
    </div>`;
  }

  /* 선언 데이터 자동등록(#26/#18 31A5A484-C) — 검토용으로 고른 데이터를 등록 데이터로
     자동등록한다. 참조(경로·시트)만 저장 — 행·내용은 저장하지 않는다. */
  function datasetBlock(s) {
    if (!s.data_path) return "";
    return `<div class="grp">
      <span class="cap">데이터 함께 등록</span>
      <p class="hint" style="margin-top:0">저장하면 데이터(${esc(s.data_name)})를 등록 데이터에
        올리고 <b>이 작업의 기본 데이터로 연결</b>합니다. 파일 위치만 기억하고, 실행할 때
        원본을 읽습니다.</p>
      <div class="row"><span class="lbl lbl-fixed">등록 이름</span>
        <input class="field" data-act="dataset-name" value="${esc(s.dataset_name)}"></div>
    </div>`;
  }

  /* 기본 데이터 연결 상태(#67) — 편집 모드에서 복원한 참조의 현재 상태 재진술 + 로케이트.
     이 세션이 데이터를 새로 골랐으면 서버가 null 을 줘 자동등록 블록이 서사를 맡는다. */
  function defaultDatasetBlock(s) {
    const d = s.default_dataset;
    if (!d) return "";
    let line;
    if (d.status === "linked") {
      line = `<p class="hint" style="margin-top:0">기본 데이터: <b>${esc(d.name)}</b> (연결됨)
        ${PathTrack.affordances(d.path)}</p>`;
    // 조치 안내는 **실재하는 거처**를 가리켜야 한다(F1: 「데이터 관리」 화면 사망) — 등록
    // 데이터의 수명 관리는 이제 「작업」의 [데이터 선택…] 안 「고정한 데이터」 구획이다.
    } else if (d.status === "dead") {
      line = `<p class="hint danger" style="margin-top:0">⚠ 기본 데이터: <b>${esc(d.name)}</b>.
        참조 파일이 없습니다(${esc(d.path)}). 「문서 만들기」의 [데이터 선택…] → 「고정한 데이터」에서
        [다시 연결…]하세요.</p>`;
    } else if (d.status === "corrupt") {  // 항목 JSON 손상 — 삭제와 다른 조치(손상 격리 표시와 정합)
      line = `<p class="hint danger" style="margin-top:0">⚠ 기본 데이터: <b>${esc(d.name)}</b>.
        등록 데이터를 읽을 수 없습니다(손상). 「문서 만들기」의 [데이터 선택…]에서 확인하세요.</p>`;
    } else {  // missing — 풀 항목 자체가 사라짐
      line = `<p class="hint danger" style="margin-top:0">⚠ 기본 데이터: <b>${esc(d.name)}</b>.
        등록 데이터에 없습니다(삭제됨). 「문서 만들기」의 [데이터 선택…]에서 같은 이름으로 고정하거나,
        데이터를 다시 선택하세요.</p>`;
    }
    return `<div class="grp">
      <span class="cap">기본 데이터 연결</span>${line}
    </div>`;
  }

  /* 파일명 패턴 토큰 도우미(#17) — Qt SaveJobPage._refresh_filename_help 웹 포트.
     s.rows 는 스텝2 매핑 확정 시점에 이미 계산돼 스냅샷에 실려온다 — 신규 브리지 호출 없음. */
  /* 토큰 참조 = 접힘(F27, 결정 14) — 라이브 예시(F26)가 상시 답을 주므로 참조표는 부피만
     차지한다. 펼침은 사용자 선택(기본 접힘). */
  function filenameTokenHelp(s) {
    const rows = (s.rows || []).filter((r) => r.has_content);
    const fieldsHtml = rows.length
      ? rows.map((r) => `<code>{{${esc(r.template_field)}}}</code> → ${fnPreviewText(r, s)}`).join(" &nbsp;·&nbsp; ")
      : `<span class="muted">매핑을 완료하면 파일명에 쓸 수 있는 필드가 여기 표시됩니다.</span>`;
    return `<details class="hidden-hdrs tok-fold"${tokFoldOpen ? " open" : ""}><summary>파일명에 넣을 수 있는 값 (펼쳐 보기)</summary>
      <p class="hint" style="margin-top:var(--sp-4)">${fieldsHtml}</p>
      <p class="hint">
        날짜: <code>{{date}}</code> → 생성 날짜(YYYYMMDD) · <code>{{date:YYYY-MM-DD}}</code> → 하이픈 포함 날짜<br>
        순번: <code>{{seq}}</code> → 1부터 증가 · <code>{{seq:001}}</code> → 001부터 세 자리로 증가
      </p>
    </details>`;
  }

  function fnPreviewText(r, s) {
    if (r.preview_error) return `<span class="pv emptyval">(미리보기 오류)</span>`;
    if (r.preview_empty) return `<span class="pv emptyval">${s.record_count ? "(빈 값)" : "(샘플 데이터 없음)"}</span>`;
    let display = String(r.preview).replace(/[\r\n]+/g, " ");
    if (display.length > 40) display = display.slice(0, 39) + "…";
    return `<span class="pv">${esc(display)}</span>`;
  }

  /* ---- 푸터 내비 — 신규=마법사(취소/뒤로/다음/저장), 편집=탭이라 내비 없음(저장 탭에 저장만).
     복귀 어포던스 불설치(결정 40): "저장하고 실행으로" 류 포커스 튕김 버튼은 두지 않는다 —
     실행 복귀는 화면 머리 「실행으로 돌아가기」가 담당하고(F2 PR-B — 좌 목록 행 클릭의
     승계처), 저장은 제자리에서 완결된다. ---- */
  function footer(s) {
    const sections = s.sections || [];
    const here = sections.indexOf(s.section);
    if (isEditing(s)) {
      // 편집의 주 행동은 **하나**다(§10.13 판정 E): 「변경 저장」. 「이번 생성에 적용」은
      // runOverrides 가 서는 PR-B 자리라 여기 라디오를 미리 늘어놓지 않는다(§6: 같은
      // 선택지를 모든 문맥에 나열하지 않는다). 손댄 것이 없으면 버릴 것도 없다.
      const discard = s.dirty
        ? `<button class="btn" data-act="discard-patch">변경 버리기</button>` : "";
      return `${discard}<span class="spacer"></span>` +
        `<button class="btn primary" data-act="save">변경 저장</button>`;
    }
    const back = here > 0
      ? `<button class="btn" data-act="back">◀ 뒤로</button>` : `<button class="btn" disabled>◀ 뒤로</button>`;
    const last = here >= sections.length - 1;
    const can = !!(s.reachable || {})[s.section];
    const next = last
      ? `<button class="btn primary" data-act="save">작업 저장</button>`
      : `<button class="btn primary" data-act="next"${can ? "" : " disabled"}>다음 ▶</button>`;
    const hint = (!last && !can) ? `<span class="muted capnote">${gateHint(s)}</span>` : "";
    return `<button class="btn" data-act="cancel-new">취소</button>${back}` +
      `<span class="spacer"></span>${hint}${next}`;
  }

  function gateHint(s) {
    if (s.section === "template") return "템플릿을 선택하고 미해결 토큰을 확인해야 진행할 수 있습니다";
    if (s.section === "binding") return "전 행을 확정해야 진행할 수 있습니다";
    return "";
  }

  /* 탭 이웃 — 초안 마법사의 ◀뒤로/다음▶ 이 쓰는 자리. 목록은 Python 이 준다(발명 금지). */
  function neighbour(delta) {
    const sections = (LAST && LAST.sections) || [];
    const here = sections.indexOf(LAST && LAST.section);
    return sections[Math.min(sections.length - 1, Math.max(0, here + delta))];
  }

  /* 탭 이동 — 처분 미확정 patch 가 있으면 Python 이 `needs_section_guard` 로 되돌리고,
     여기서 **3택**(저장하고 이동 · 버리고 이동 · 머무르기)을 받는다(계약 §5.2).
     판정이 Python 인 이유: "무엇이 dirty 인가"는 규칙 비교라 표면이 재유도하면 두 답이
     생긴다. 문안만 여기 있고, 통과 표지(`disposition`)를 실어 같은 액션을 다시 부른다.
     머무르기는 **기본값**이다 — 모달을 Escape 로 닫아도 편집이 사라지지 않는다. */
  async function gotoSection(target) {
    if (!target) return;
    // 대기 중 입력이 판정을 추월하지 않게 먼저 정산한다(4R P2) — 방금 친 패턴이 아직
    // 도착하지 않은 채 판정하면 처분할 것이 없다고 읽고 그 편집을 다른 탭으로 끌고 간다.
    await flushPendingEdits();
    const r = await sendEdit("goto_section", { section: target });
    if (!(r && r.needs_section_guard)) return;
    const choice = await Modal.choose({
      title: `「${r.section_label}」 에서 바꾼 내용이 있습니다`,
      body: "다른 탭으로 가기 전에 이 변경을 어떻게 할지 정하세요.\n" +
        "한 번에 한 곳만 고칩니다 — 저장하면 새 판본이 되고, 버리면 열었을 때 상태로 돌아갑니다.",
      choices: [
        { value: "save", label: "저장하고 이동" },
        { value: "discard", label: "버리고 이동" },
        { value: "stay", label: "머무르기" },
      ],
    });
    if (choice === "save") {
      const saved = await doSave({});
      if (!saved) return;                       // 저장이 막혔으면 이동하지 않는다(문맥 보존)
    } else if (choice === "discard") {
      // **그 자리만** 되돌린다(2R P2) — 모달이 말한 범위가 곧 파기 범위다. 이름처럼 어느
      // section 에도 없는 편집은 이 처분의 대상이 아니다.
      await sendEdit("discard_patch", { section: r.section });
    } else {
      return;                                   // 머무르기(Escape 포함)
    }
    await sendEdit("goto_section", { section: target, disposition: choice });
  }

  /* 확정·수동 매핑 보호(PR#105 리뷰 F1) — 관문의 데이터 교체/비우기는 _ensure_model 재초안으로
     사람 소유 행을 미확정으로 되돌린다(값은 carry_profile 로 이월). 편집 복원 확정을 '검토만'
     하려던 1클릭이 매핑 표 바로 위 관문에서 조용히 리셋하지 않게 파괴 전 확인한다(confirm-or-
     alarm). 수치는 **Python 이 지금** 판정한다(PR-2 리뷰 F7 — LAST 는 push 지연 창에서 stale 이라
     방금 확정한 행이 안 보여 확인이 조용히 생략됐다). 0이면 조용히 진행(새 작업 첫 겨눔 등). */
  /* 새 템플릿 진입 = 새 작업 세션 확인 — 폐기 판정은 EditorEntry.confirmDiscard 단일 출처
     (PR-4 리뷰 F9). 편집(탭) 맥락에선 미저장이 없어도(클린 복원) 확인한다(리뷰 F1: 「이
     템플릿으로」가 열려 있는 작업의 편집 맥락을 조용히 닫고 새 초안으로 갈아타면 안 된다 —
     저장본은 남지만 '이 작업을 고치는 중'이라는 맥락의 전환은 의식적이어야 한다). */
  async function confirmNewSessionIfUnsaved() {
    const editing = LAST && LAST.editing_origin;
    if (editing) {
      const busy = await Bridge.editorHasUnsavedWork();
      if (!busy) return true;
      return Modal.confirm({ body:
        `'${editing}' 편집을 닫고 새 작업 초안을 시작합니다.` +
        "\n저장하지 않은 변경은 사라집니다." +
        "\n\n계속할까요?", confirmLabel: "새 작업 시작", cancelLabel: "취소" });
    }
    return EditorEntry.confirmDiscard(
      "새 템플릿으로 시작하면 저장하지 않은 작업 세션이 사라집니다.\n" +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?");
  }

  async function confirmMappingResetIfConfirmed(verbPhrase) {
    const st = await sendEdit("mapping_reset_stakes", {});
    const n = (st && st.human) || 0;
    if (!n) return true;
    return Modal.confirm({ body:
      `${verbPhrase} 확정했거나 직접 편집한 매핑 ${n}개가 전부 미확정으로 돌아갑니다` +
      `(값은 이월).\n\n계속할까요?`, confirmLabel: "미확정으로 되돌리기", cancelLabel: "취소" });
  }

  /* ---- 이벤트 위임(innerHTML 재구성이라 위임이 안전) ---- */
  async function onClick(e) {
    const el = e.target.closest("[data-act]");
    if (!el) return;
    const act = el.dataset.act;
    const idx = el.dataset.index !== undefined ? Number(el.dataset.index) : null;
    // 브리지 rejection 이 unhandled 로 삼켜지면 버튼이 조용히 무반응이 된다 — 개별 핸들러가
    // 아니라 디스패처에서 한 번에 loud 재진술한다(pool.js onListClick 미러, #45). 새 case 가
    // 늘어도 가드를 자동 상속한다(profile_* 만 봉합하고 confirmAll 을 빠뜨렸던 재발 방지).
    try {
      switch (act) {
        case "use-library": {
          if (!(await confirmNewSessionIfUnsaved())) break;
          await sendEdit("use_library_template", { path: el.dataset.path });
          break;
        }
        case "toggle-lib-group":
          // 1단계 피커 그룹 접힘 — 관리 화면과 같은 모델 토글(뷰 상태, 세션 불변).
          // media 가 밴드(hwpx/txt)를 고른다(F6 PR-B 2밴드).
          await sendEdit("toggle_library_group", { group: el.dataset.group, media: el.dataset.media });
          break;
        // 라이브러리 관리 어포던스(F8 — tpl 화면 사망의 승계, §10.17.2 판정 D).
        case "lib-more":
          toggleLibMenu(el.dataset.media, "row", el.dataset.key, el);
          break;
        case "lib-grp-more":
          toggleLibMenu(el.dataset.media, "group", el.dataset.group, el);
          break;
        case "lib-assign":
          openLibMoveDialog(el.dataset.media, findLibItem(el.dataset.media, el.dataset.key), el);
          break;
        case "import-template": {
          if (!(await confirmNewSessionIfUnsaved())) break;
          const r = await Bridge.importTemplateFile(SCREEN);
          if (typeof r === "string" && r.startsWith("ERROR:")) alertMsg(r.slice(6).trim());
          break;
        }
        case "ack-gate": await sendEdit("ack_gate", {}); break;
        case "pick-data": {
          if (!(await confirmMappingResetIfConfirmed("데이터를 바꾸면"))) break;  // 확정 보호(F1)
          let r = await Bridge.pickDataFile(SCREEN);
          if (r && typeof r === "object" && r.needs_sheet) {   // 다중 시트 → 확정 게이트(#33)
            r = await SheetPicker.choose(SCREEN, r);
            if (r === null) break;                              // 취소 = 중단(첫 시트 강등 없음)
          }
          if (typeof r === "string" && r.startsWith("ERROR:")) alertMsg(r.slice(6).trim());
          break;
        }
        case "skip-data": {
          if (!(await confirmMappingResetIfConfirmed("데이터 없이 진행하면"))) break;  // 확정 보호(F1)
          await sendEdit("skip_data", {});
          break;
        }
        case "goto-tab":  // 탭 이동 — 처분 미확정이면 백엔드가 3택을 요구한다(§5.2).
          await gotoSection(el.dataset.section);
          break;
        case "context-return":
          await leaveTo(returnScreen());
          break;
        case "discard-patch": {
          if (!(await Modal.confirm({
            body: "이 편집에서 바꾼 내용을 버리고 저장된 상태로 되돌립니다.\n\n계속할까요?",
            returnFocus: el, confirmLabel: "변경 버리기", cancelLabel: "취소",
          }))) break;
          await sendEdit("discard_patch", {});
          break;
        }
        // 칩-라이브(결정 13): 칩 클릭 = 즉시 토글(활성↔미사용). 전체 사용/전체 미사용 대칭쌍.
        case "toggle-header":
          await sendEdit("toggle_source_active", { field: el.dataset.field }); break;
        case "use-all-headers": await sendEdit("use_all_headers", {}); break;
        case "use-none": {
          // 수치는 Python 이 지금 판정(stale LAST 우회 차단 — F7 동형). 확정 존재는 확인
          // 모달 **전에** 선차단(PR-3 리뷰 F5: 파괴를 승인시킨 뒤 오류로 거부하는 확인-후-
          // 오류 순서 금지) — 백엔드 loud 차단은 백스톱으로 존속. 소스 겨눈 수동 미확정만
          // 실제 강등 집합이라 그 수치로 확인한다(리뷰 F4 — 문안=파괴 집합).
          const st = await sendEdit("mapping_reset_stakes", {});
          if (st && st.confirmed) {
            window.alert(`확정한 매핑 ${st.confirmed}개가 있어 전체 미사용을 할 수 없습니다. 확정을 먼저 해제하거나 칩을 하나씩 끄세요.`);
            break;
          }
          const man = (st && st.manual_unconfirmed) || 0;
          if (man && !(await Modal.confirm({ body:
            `전체 미사용하면 직접 소스를 고른 매핑 ${man}개의 수동 지정이 해제됩니다` +
            `(자동 제안으로만 복원).\n\n계속할까요?`,
            confirmLabel: "전체 미사용", cancelLabel: "취소" }))) break;
          await sendEdit("use_none", {});
          break;
        }
        case "revert-source":
          await sendEdit("revert_source", { index: idx }); break;
        case "prev-rec": await sendEdit("step_preview", { delta: -1 }); break;
        case "next-rec": await sendEdit("step_preview", { delta: 1 }); break;
        case "unconfirm-all": await sendEdit("unconfirm_all", {}); break;
        case "restore-confirmed": await sendEdit("restore_confirmed", {}); break;
        case "confirm-all": await confirmAll(); break;
        case "row-confirm": await sendEdit("set_confirmed", { index: idx, confirmed: el.checked }); break;
        case "cancel-new": {
          if (!(await EditorEntry.confirmDiscard(
            "새 작업 만들기를 취소하면 입력한 이름 · 데이터 · 매핑이 사라집니다.\n\n계속할까요?",
            el))) break;
          await sendEdit("discard_session", {});
          // 확인·폐기를 마쳤으니 이탈 가드를 다시 태우지 않는다(force — `landOn` 이 건다) —
          // 같은 폐기를 두 번 묻는 것은 소음이고, 두 번째 확인에서 취소하면 이미 비운
          // 세션에 남게 된다. 착지는 이탈과 **같은 절차**를 쓴다: 편집기를 나가는 길이
          // 둘이면 그중 하나만 재적재를 기다리는 비대칭이 다시 생긴다.
          await landOn(returnScreen());
          break;
        }
        case "back": await gotoSection(neighbour(-1)); break;
        case "next": await gotoSection(neighbour(1)); break;
        case "save": await doSave({}); break;
        default: break;
      }
    } catch (err) {
      window.alert(String((err && err.message) || err));
    }
  }

  function onChange(e) {
    const el = e.target.closest("[data-act]");
    if (!el) return;
    const idx = el.dataset.index !== undefined ? Number(el.dataset.index) : null;
    switch (el.dataset.act) {
      case "row-source": sendEdit("set_source", { index: idx, source: el.value }); break;
      case "row-type": sendEdit("set_type", { index: idx, type: el.value }); break;
      case "row-fmt": sendEdit("set_fmt", { index: idx, fmt: el.value }); break;
      case "row-const": sendEdit("set_const", { index: idx, const: el.value }); break;
      case "name": sendEdit("set_name", { name: el.value }); break;
      case "pattern": sendEdit("set_pattern", { pattern: el.value }); break;
      case "dataset-name": sendEdit("set_dataset_name", { name: el.value }); break;
      default: break;
    }
  }

  /* 모두 확정 — 내용 행 즉시 확정 + 비움 승격 이름게이트(ADR-E 반사적 dismiss 봉쇄). */
  async function confirmAll() {
    const res = await sendEdit("confirm_all", {});
    const blanks = (res && res.blanks) || [];
    if (!blanks.length) return;
    const ok = await Modal.confirm({ body:
      `아래 ${blanks.length}개 필드는 채우지 않고 '비움'으로 확정합니다:\n\n${blanks.join(", ")}\n\n계속할까요?`,
      confirmLabel: "비움으로 확정", cancelLabel: "취소",
    });
    // await 로 던진다 — fire-and-forget 이면 rejection 이 디스패처 가드 밖으로 샌다(#45).
    if (ok) await sendEdit("confirm_blanks", { fields: blanks });
  }

  /* 저장 — 차단 사유·덮어쓰기·자동등록 확인 재진술(조용한 덮어쓰기 금지).
     flags 는 확인 라운드트립을 누적한다({confirm_overwrite, confirm_dataset}).
     브리지 예외도 잡아 표시한다 — 백엔드가 반저장(작업 저장 후 실패) 상태로 던지면
     화면이 무반응이 되는 함정 봉쇄(실패는 언제나 시끄럽게). */
  async function doSave(flags) {
    let res;
    try {
      res = await sendEdit("save", flags || {});
    } catch (err) {
      window.alert("저장 처리 중 오류가 발생했습니다. 작업이 저장됐는지 「문서 작업」에서 확인하세요.\n" + err);
      return;
    }
    if (!res || typeof res !== "object") {
      alertMsg("저장 결과를 확인할 수 없습니다. 작업이 저장됐는지 「문서 작업」에서 확인하세요.");
      return false;
    }
    if (res.ok) {
      // 저장은 제자리(결정 40 — 포커스 튕김 없음). 후보·문서 탐색 스냅샷만 갱신해 새/개명
      // 작업이 바로 보이게 한다 — REFRESH_ON_NAV 를 기다릴 이유가 없다(좌 목록 사망 뒤
      // 갱신 대상이 목록에서 이 두 표면으로 옮겨졌다, F2 PR-B).
      if (window.JobScreen && window.JobScreen.refreshList) window.JobScreen.refreshList();
      // 성공 재진술은 Python notice(ok) 채널 — 저장 착지가 저장본 편집 세션 재로드 push 라
      // #save-msg 는 그 재렌더에 증발한다(PR-2 리뷰 F2: push/반환 경합에 안 걸리는 채널만).
      // 반저장(작업 저장 성공 + 데이터 등록 실패)만 여기서 loud — 성공으로 뭉개지 않는다.
      if (res.dataset_register_error) {
        window.alert(`작업 '${res.saved_name}' 은 저장됐지만 데이터 등록이 실패했습니다.\n`
          + res.dataset_register_error);
      }
      // **성공을 값으로 돌려준다**(1R P1): 「저장하고 이동」·「저장하고 나가기」는 이 값으로
      // 계속할지를 정한다 — undefined 를 돌려주면 성공한 저장이 이동을 막아, 사용자가 고른
      // 처분이 절반만 일어난다(저장은 됐는데 가려던 곳에 못 간다).
      return true;
    }
    if (res.needs_overwrite) {
      // 본 문안을 그대로 되돌려 준다(#149) — 모달을 읽는 사이 디스크가 바뀌면 확인은 다른
      // 상태에 대한 것이 된다. 판정은 Python 이 쓰기 잠금 안에서 다시 하고(문안 대조),
      // 달라졌으면 새 문안으로 다시 묻는다. 여기는 무엇을 보여 줬는지만 실어 보낸다.
      if (await Modal.confirm({
        body: res.overwrite_text + "\n\n계속할까요?",
        confirmLabel: "덮어쓰기", cancelLabel: "취소", danger: true,
      })) {
        return doSave(Object.assign({}, flags, {
          confirm_overwrite: true,
          confirmed_overwrite_text: res.overwrite_text,
        }));
      }
      return false;
    }
    if (res.needs_dataset_confirm) {
      if (await Modal.confirm({
        body: res.dataset_text, confirmLabel: "덮어쓰기", cancelLabel: "취소", danger: true,
      })) {
        return doSave(Object.assign({}, flags, { confirm_dataset: true }));
      }
      return false;
    }
    alertMsg(res.dataset_error || res.block_reason || "저장할 수 없습니다.");
    return false;
  }

  function alertMsg(msg, level) {
    const box = $("save-msg");
    if (box) {
      box.style.display = "block";
      box.className = "note " + (level === "ok" ? "okbox" : "warnbox");
      box.textContent = (level === "ok" ? "" : "⚠ ") + msg;
    } else {
      window.alert(msg);
    }
  }

  function init() {
    Bridge.onPush(SCREEN, render);
    // tpl 채널 구독(F8 — F1 의 data_picker→pool 동형): 관리 동사(그룹·삭제·가져오기)의
    // 결과·목록 변화를 editor 스냅샷 **재당김**으로 되그린다 — 목록·결과 렌더의 정본은
    // editor 스냅샷 하나다(tpl 스냅샷을 여기서 직접 그리면 성형이 두 벌이 된다). 병존
    // 기간 template.js 의 자기 구독과 공존한다(bridge.js 복수 구독).
    Bridge.onPush("tpl", () => { Bridge.initial(SCREEN).then(render); });
    // 몰입 표면(재작성 F7) — 위임 루트가 화면 전체다. back 은 재렌더가 만지지 않는 안정
    // 요소라 여기서 직접 문다(문맥 배너의 복귀 버튼은 재구성되므로 위임으로 받는다).
    const root = $("scr-editor");
    root.addEventListener("click", onClick);
    root.addEventListener("change", onChange);
    $("editorBack").addEventListener("click", () => leaveTo(returnScreen()));
    // 라이브러리 ⋮ 메뉴·이동 다이얼로그 배선(F8) — DOM(#tplRowMenu·#tplMoveModal)은 셸
    // 레벨 공용이라 병존 기간 template.js 와 이중 배선되지만, 각 인스턴스가 자기 열림
    // 상태(libMenuFor / onConfirm)로만 반응해 서로 간섭하지 않는다.
    $("tplRowMenu").addEventListener("click", onLibMenuClick);
    libMoveDialog.wire("tplMoveOk", "tplMoveCancel");
    window.Popover.wireDismiss({
      isOpen: () => libMenuFor !== null,
      contains: (t) => !!(t.closest("#tplRowMenu") || t.closest("#scr-editor .job-more")),
      close: closeLibMenu,
    });
    Bridge.initial(SCREEN).then(render);
  }

  /* 복귀처 — 진입 문맥이 말한 표면(계약 §8). 없으면 「문서 만들기」다: 편집기는 늘 업무
     표면에서 열리고, 모르는 자리로 보내느니 흐름의 본진으로 보낸다. */
  const RETURN_SCREEN = {
    data: "job", preview: "job", result: "job", documents: "job", library: "library",
  };
  function returnScreen() {
    const ctx = (LAST && LAST.context) || {};
    return RETURN_SCREEN[(ctx.return_context || {}).surface] || "job";
  }

  /* 복귀 **상태**까지 되돌린다(1R P2) — 화면 키만 맞추면 「미리보기로 돌아가기」가 보통의
     「문서 만들기」로 데려다 놓는다. 라벨이 약속한 자리와 실제 착지가 다른 것은 문안 부정직의
     한 형태다. 면을 여는 절차(Python 왕복·성사 뒤 열기·포커스)는 그 화면이 소유한 seam 을
     그대로 쓴다 — 여기서 다시 조립하면 열기 규율이 두 벌이 된다. */
  async function restoreReturnState() {
    const ctx = (LAST && LAST.context) || {};
    const ret = ctx.return_context || {};
    if (ret.surface === "preview" && ret.reopen_drawer
        && window.JobScreen && window.JobScreen.openPreview) {
      // 규칙 재적재는 `landOn` 이 **전환 전에** 이미 끝냈다(8R 근본 조치) — 여기서 다시
      // 기다리면 순서 규율이 미리보기 복귀에만 사는 두 벌째가 되고, 그것이 5R→8R 사이에
      // 데이터·결과 복귀를 무방비로 남긴 자리다.
      // 같은 previewIndex·같은 행(§10.14.3): 자리는 진입 때 실은 값의 왕복이고, 행
      // 정체성은 `context.target` 에서 파생한다 — 둘째 축을 만들지 않는다(판정 B).
      await window.JobScreen.openPreview(null, {
        at: ret.preview_index || 0,
        focusTarget: ctx.target || "",
      });
    }
  }

  /* 편집기에서 나가는 **착지 절차**(8R P1) — 목적 화면을 노출하기 **전에** 그 화면이
     디스크를 다시 읽게 한다. `Nav.go` 의 자동 refresh 는 기다려지지 않는 발신이라, 전환만
     하면 사용자는 **편집 전 규칙**을 든 화면을 손에 쥔다: 그 창에서 「만들기」를 누르면
     방금 고친 매핑이 반영되지 않은 문서가 나오고, 실행 증거는 그것을 최신이라 말한다.
     복귀처별로 봉합하지 않고 이 한 자리에 두는 이유가 곧 F7 리뷰가 반복된 원인이다.
     재적재가 실패하면 **나가지 않는다** — 옛 규칙을 든 화면에 실행구를 열어 주는 것이
     조용한 거짓이고, 편집기에 머무르는 쪽은 시끄럽고 되돌릴 수 있다. */
  async function landOn(target) {
    try {
      await window.Nav.refresh(target);
    } catch (err) {
      window.alert("돌아갈 화면을 다시 읽지 못해 편집기에 머무릅니다: "
        + String((err && err.message) || err));
      return false;
    }
    window.Nav.go(target, { force: true, refreshed: true });
    // **초점도 되돌린다**(9R P2) — 화면만 바꾸면 초점은 방금 숨겨진 편집기의 back 버튼에
    // 남는다. 키보드 사용자는 보이는 초점 없이 착지해 남의(숨은) 요소부터 tab 을 시작한다.
    // 되돌릴 자리는 편집기를 **띄운 자리**이고, 그것을 아는 곳은 진입 seam 하나다.
    window.EditorEntry.restoreEntryFocus();
    return true;
  }

  /* 편집기를 나가는 **단일 출구**(§10.13 판정 N) — back·문맥 복귀·다른 화면의 프로그램적
     이동이 전부 여기로 모인다. 처분 미확정 patch 가 있으면 3택을 먼저 받고, 초안이면
     세션 폐기 확인을 받는다(초안은 patch 가 아니라 세션 전체가 미저장이다 — 판정 P).
     Nav.go 는 `force` 로 되돌아온다(가드 재진입 방지). */
  async function leaveTo(target) {
    await flushPendingEdits();
    const s = LAST || {};
    // **section 밖의 편집도 잃을 것이다**(2R P1): 이름·자동등록 이름은 어느 section 에도
    // 속하지 않아 탭 표지엔 안 뜬다 — 그것만 보면 머리에서 이름을 고치고 나가는 사람에게
    // 아무것도 묻지 않고 그 편집을 버린다. 몰입 표면엔 그 세션으로 되돌아올 길이 없으므로
    // (구 「편집 계속」은 사망) 조용한 파기가 된다. 판정은 Python 의 `dirty` 하나다.
    // 정산 뒤에도 **스냅샷이 아니라 컨트롤러에게 묻는다**(4R P2): push 도착과 이 판정의
    // 순서까지 기대고 싶지 않다 — 잃을 것이 있는지는 Python 이 지금 답할 수 있다.
    // `s.dirty` 를 먼저 보는 것은 세션 손댐 표지가 아직 안 선 첫 왕복의 방어다.
    let dirty = !!s.dirty;
    if (!dirty && !s.is_draft) {
      try {
        dirty = await Bridge.editorHasUnsavedWork();
      } catch (err) {
        dirty = true;   // 모르면 묻는다(확인-또는-경보의 안전 방향)
      }
    }
    if (dirty && !s.is_draft) {
      const choice = await Modal.choose({
        title: "저장하지 않은 변경이 있습니다",
        body: "편집기를 나가기 전에 이 변경을 어떻게 할지 정하세요."
          + "\n저장하면 새 판본이 되고, 버리면 열었을 때 상태로 돌아갑니다.",
        choices: [
          { value: "save", label: "저장하고 나가기" },
          { value: "discard", label: "버리고 나가기" },
          { value: "stay", label: "머무르기" },
        ],
      });
      if (choice === "save") {
        if (!(await doSave({}))) return;      // 저장이 막혔으면 나가지 않는다(문맥 보존)
      } else if (choice === "discard") {
        await sendEdit("discard_patch", {});
      } else {
        return;
      }
    } else if (s.is_draft && !(await EditorEntry.confirmDiscard(
      "편집기를 나가면 저장하지 않은 새 작업이 사라집니다."
      + "\n사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?"))) {
      return;
    } else if (s.is_draft) {
      await sendEdit("new_session", {});   // 확인을 마쳤으면 실제로 폐기한다
    }
    if (!(await landOn(target))) return;
    if (target === returnScreen()) await restoreReturnState();
  }

  /* 현 에디터 스냅샷 재당김·재렌더(#138 리뷰 F12) — 편집 모드로 복귀할 때 1단계 피커가
     관리 화면에서 바뀐 공유 그룹 접힘을 반영하게 한다(returning-to-job 이 job 만 refresh 해
     피커가 stale 접힘으로 남던 문제). 순수 재렌더라 세션 상태 불변(Preserve 가 포커스 보존). */
  function rerender() {
    if (window.pywebview && window.Bridge) Bridge.initial(SCREEN).then(render);
  }

  window.EditorScreen = { init, rerender, leaveTo, aimAt };
})();
