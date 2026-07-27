/* 「문서 작업」 전역 라이브러리(§19.6·§19.7) — browser + detail. 재작성 F2 PR-A.
   홈(카드 나열 + group-by 렌즈)의 승계자다. 안정 DOM(index.html) + Python 이
   window.__push('library', snapshot) 로 값만 채운다. 표현 계층(탭·칩·행·상세)만 여기서
   만든다 — 보기·필터·검색·건강 판정은 전부 링1 소유(링2 대체 금지).

   §9.3 4계약면(지도 §10.8.2)의 이행분이 이 파일에 있다:
   - 정체: 행 id = 작업 이름(안정 키), 탭·칩·헤더·상세 버튼 id 고정, 재렌더는 Preserve.around.
   - 잠금: 축 컨트롤·행 버튼에 data-busy-lock(생성 중 전역 잠금 대상).
   - 의도: 즐겨찾기 직렬화는 공용 몸통 js/intent.js(「작업」 화면과 한 기제, 리뷰 3R).
   - 순서: 이동은 대상 화면 dispatch 로 **먼저 겨눈 뒤** window.Nav — 실패하면 화면 불변.
   - 실패: 실패는 이 화면 안에서 재진술하고 보기·필터·선택을 유지한다.

   좌 목록 관리 동사 중 열린 세션의 정체와 결속된 것(이름 변경·그룹 지정/이름 변경/해산)은
   「작업」 컨트롤러가 계속 소유한다 — 여기서는 교차 화면 dispatch 로 부르고 뒤이어
   library/refresh 로 이 화면 스냅샷을 맞춘다(지도 §10.8 판정 F). */
(function () {
  const SCREEN = "library";
  const JOB = "job";  // 세션 결속 관리 동사의 소유 화면(교차 화면 dispatch 대상)
  const $ = (id) => document.getElementById(id);

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  let LAST = null;      // 마지막 스냅샷 — 태그 프리필·그룹 목록 등 핸들러가 참조
  let menuFor = null;   // 열린 그룹 ⋮ 메뉴의 {group, trigger} — null=닫힘
  let searchTimer = null;

  /* 그룹 헤더 ⋮ 메뉴·그룹 이동 다이얼로그 = 공용 팩토리(grouplist.js, job/tpl 과 단일 출처).
     새 생명주기를 들이지 않는다(F1 판정 E 와 같은 규율) — 위치잡기·조립만 팩토리 소유. */
  const groupMenu = window.GroupList.createMenu({ menuId: "libraryGroupMenu" });
  const moveDialog = window.GroupList.createMoveDialog({
    modalId: "libraryMoveModal", listId: "libraryMoveList", errId: "libraryMoveErr",
    nameId: "libraryMoveName", radioName: "libMove",
    newRadioId: "libMoveNewRadio", newNameId: "libMoveNewName",
  });

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    // 재렌더가 포커스·스크롤을 삼키지 않게(§9.3 정체 면) — 목록·상세가 매 액션마다 다시 그려진다.
    Preserve.around(() => {
      LAST = s;
      renderAlerts(s.alerts);
      renderCorrupt(s.corrupt_rows);
      renderTabs(s.view, s.counts);
      renderModes(s.mode);
      renderFacets(s.facets);
      syncSearch(s.query);
      renderList(s);
      renderDetail(s.detail);
    });
  }

  /* 정보 위생(#239 결정 8 승계): 개수 타일은 렌더하지 않고 조치가 필요한 조건만 경보로. */
  function renderAlerts(a) {
    a = a || { missing_template_count: 0, pool_corrupted: 0 };
    const alerts = [];
    if (a.missing_template_count > 0) {
      alerts.push(`<div class="note warnbox">템플릿이 연결되지 않은 작업 ${a.missing_template_count}건이 있습니다. 「확인 필요」 보기에서 조치하세요.</div>`);
    }
    if (a.pool_corrupted > 0) {
      // 조치처는 실재해야 한다(F1: 「데이터 관리」 화면 사망) — 손상 격리의 새 거처는
      // 「작업」의 [데이터 선택…] 안 「고정한 데이터」 구획이다.
      alerts.push(`<div class="note dangerbox">손상된 등록 데이터 ${a.pool_corrupted}건이 있습니다. 「문서 만들기」의 [데이터 선택…]에서 확인하세요.</div>`);
    }
    $("libraryAlerts").innerHTML = alerts.join("");
  }

  /* 손상 작업 — 숨기지 않고 시끄러운 위험 카드로(RC-05) + 해소 동선(#26 #8·UD-44):
     폴더 열기(탐색기 표시)·삭제(백엔드 재진술 확인 라운드트립). */
  function renderCorrupt(rows) {
    const box = $("libraryCorrupt");
    rows = rows || [];
    if (!rows.length) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    box.innerHTML =
      `<div class="grp"><span class="cap">손상된 작업 파일</span>` +
      rows.map((c) =>
        `<div class="jcard corrupt"><div class="jn">${esc(c.file_name)} <span class="pill danger">손상됨</span></div>` +
        `<div class="jm">${esc(c.detail_line)}</div>` +
        `<div class="jfoot"><span></span><span class="acts">` +
        `<button class="btn sm" data-reveal="${esc(c.path)}">폴더 열기</button>` +
        `<button class="btn sm" data-del-corrupt="${esc(c.path)}">삭제</button>` +
        `</span></div></div>`
      ).join("") + `</div>`;
  }

  async function onCorruptClick(e) {
    const rv = e.target.closest("[data-reveal]");
    if (rv) {
      const r = await Bridge.revealCorruptJob(rv.dataset.reveal);
      if (typeof r === "string" && r.startsWith("ERROR:")) window.alert(r.slice(6).trim());
      return;
    }
    const dc = e.target.closest("[data-del-corrupt]");
    if (dc) {
      const path = dc.dataset.delCorrupt;
      // 백엔드가 거절할 수 있다(목록에 없는 stale 경로 → ValueError, 잠긴 파일 → PermissionError).
      // try/catch 없이는 rejection 이 삼켜져 클릭이 무반응이 된다 — 시끄럽게 재진술한다.
      try {
        const res = await Bridge.call(SCREEN, "delete_corrupt", { path });
        if (res && res.needs_confirm && (await Modal.confirm({
          body: res.confirm_text, confirmLabel: "삭제", cancelLabel: "취소", danger: true,
        }))) {
          await Bridge.call(SCREEN, "delete_corrupt", { path, confirm: true });
        }
      } catch (err) {
        window.alert(String((err && err.message) || err));
      }
    }
  }

  /* 축 변이는 **한 체인**으로 직렬화한다(리뷰 4R — 「작업」 화면 탐색의 `Intent.chained`
     선례). pywebview 는 호출마다 별도 스레드라 동시 발신의 도착 순서가 보장되지 않는다:
     디바운스된 검색이 도는 중에 다른 축을 만지면 **늦게 도착한 옛 응답이 새 결과를
     되돌려** 목록은 옛 검색어로 걸러진 채 입력창만 새 글자를 유지한다. 체인 하나면 클릭·
     타이핑 순서가 곧 반영 순서다.

     타이머를 **취소하지 않고** 그대로 두는 것이 의도적이다: 사용자가 친 글자는 그의 의사라
     다른 축을 눌렀다고 버리지 않는다 — 체인이 순서를 지키므로 나중에 도착해도 옳다.
     예외는 「필터 지우고 전체 보기」뿐이다(아래) — 그건 대기 중인 검색까지 걷겠다는 의사다. */
  function axis(action, payload) {
    return Intent.chained(SCREEN, () => Bridge.call(SCREEN, action, payload || {}));
  }

  function cancelPendingSearch() {
    if (searchTimer) { clearTimeout(searchTimer); searchTimer = null; }
  }

  /* ---- 축: 보기 탭 · 작업 방식 칩 · 태그 facet · 검색 ---- */
  /* 탭 건수는 **검색 전** 사실이다(링1 계약) — 검색어에 따라 흔들리면 "여기 몇 건인가"를 잃는다.
     라벨은 DOM 정본에서 읽고 건수만 덧댄다(재렌더마다 라벨이 누적되지 않게 접미를 걷는다). */
  function renderTabs(view, counts) {
    counts = counts || {};
    $("libraryViewTabs").querySelectorAll("[data-library-view]").forEach((b) => {
      const v = b.dataset.libraryView;
      const on = v === view;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      const label = b.dataset.label || (b.dataset.label = b.textContent.trim());
      const n = counts[v];
      b.textContent = typeof n === "number" ? `${label} · ${n}` : label;
    });
    $("libraryPanel").setAttribute("aria-labelledby", "library-view-" + view);
  }

  function renderModes(mode) {
    $("libraryModeFilters").querySelectorAll("[data-library-mode]").forEach((b) => {
      b.setAttribute("aria-pressed", b.dataset.libraryMode === mode ? "true" : "false");
    });
  }

  /* facet 칩 — 축이 하나도 없으면 UI 전체를 숨긴다(§19.6 · 퇴화-코퍼스 불변식). 0건 값은
     비활성이되 **켜진 고아 칩은 남긴다**(링1이 count=0·active=true 로 실어 보낸다) — 범인
     필터가 보이지 않는 채 실재 작업을 숨기면 confirm-or-alarm 위반이다. */
  function renderFacets(facets) {
    const box = $("libraryFacets");
    facets = facets || [];
    const chips = facets.flatMap((fa) =>
      fa.values.map((v) =>
        `<button class="pill${v.active ? "" : " muted"}" data-axis="${esc(fa.axis)}" data-val="${esc(v.value)}"` +
        `${v.count === 0 && !v.active ? " disabled" : ""} aria-pressed="${v.active ? "true" : "false"}" data-busy-lock>` +
        `${esc(fa.axis)}: ${esc(v.value)} · ${v.count}</button>`
      )
    );
    if (!chips.length) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    box.innerHTML = `<span class="library-filter-label">태그</span>` + chips.join("") +
      `<button class="btn sm" id="libraryClearFacets" data-busy-lock>태그 필터 해제</button>`;
  }

  /* 검색 입력은 사용자가 치는 중이면 덮어쓰지 않는다 — 왕복 중 도착한 푸시가 캐럿을 되감는
     것이 §8.4 「지연 왕복 중의 의도」 면의 이 표면 판본이다. */
  function syncSearch(query) {
    const el = $("librarySearch");
    if (document.activeElement !== el && el.value !== (query || "")) el.value = query || "";
  }

  /* ---- 목록(browser) ---- */
  function healthPill(h) {
    if (!h || !h.severity) return "";
    const level = h.severity >= 3 ? "danger" : "warn";
    return ` <span class="pill ${level}">${esc(h.text)}</span>`;
  }

  /* 행: 이름·작업 방식·사용자 group·최근 사용·건강·즐겨찾기(§19.6).
     즐겨찾기와 상세 열기는 **형제** 버튼이다 — 선택 버튼 안에 중첩하지 않는다(§19.6 명문).
     이 배치가 「표시 상한과 무관한 도달성」(§8.4 2행)의 새 거처다: 순위 밖 작업도 여기서 별을
     켜 메인 Top 5 로 승격할 수 있다. */
  function rowHtml(r, selected) {
    const nm = esc(r.name);
    const on = r.name === selected;
    return `<div class="lib-row${on ? " on" : ""}">` +
      `<button class="lib-row-main" data-work="${nm}" aria-current="${on ? "true" : "false"}" data-busy-lock>` +
      `<span class="lib-row-name">${nm}${healthPill(r.health)}</span>` +
      `<span class="lib-row-meta">${esc(r.mode_label)}` +
      (r.group ? ` · ${esc(r.group)}` : "") +
      ` · ${esc(r.last_run_display)}</span></button>` +
      // 다음 값을 DOM 속성으로 심지 않는다 — 왕복 중 두 번째 클릭이 그 낡은 값을 읽으면
      // 같은 의도를 두 번 보내 "껐다"가 삼켜진다(리뷰 3R). 현재 표시 상태만 두고 다음 값은
      // 공용 몸통의 **미결 의도**가 계산한다.
      `<button class="lib-fav" data-fav="${nm}"` +
      ` aria-pressed="${r.favorited ? "true" : "false"}"` +
      ` aria-label="${nm} 즐겨찾기" title="즐겨찾기" data-busy-lock>${r.favorited ? "★" : "☆"}</button></div>`;
  }

  function sectionHtml(sec, selected) {
    const rows = sec.rows.map((r) => rowHtml(r, selected)).join("");
    if (!sec.headed) return rows;  // 저장된 group 0개 = 헤더 없는 평면(퇴화 불변식)
    const g = esc(sec.value);
    return `<div class="lib-grp job-grp">` +
      `<button class="lib-grp-head" data-group="${g}" aria-expanded="${sec.collapsed ? "false" : "true"}" data-busy-lock>` +
      `<span class="grp-caret">${sec.collapsed ? "▸" : "▾"}</span> ${esc(sec.label)} · ${sec.count}</button>` +
      `<button class="job-more" data-group-more="${g}" aria-haspopup="true" aria-label="${esc(sec.label)} 그룹 관리">⋮</button>` +
      `</div><div class="lib-grp-rows"${sec.collapsed ? " hidden" : ""}>${rows}</div>`;
  }

  function isFiltered(s) {
    return !!(s.query || s.mode !== "all" ||
      (s.facets || []).some((fa) => fa.values.some((v) => v.active)));
  }

  function renderList(s) {
    const host = $("libraryList");
    const sections = s.sections || [];
    const shown = sections.reduce((n, sec) => n + sec.count, 0);
    if (s.is_empty) {
      // 코퍼스 자체가 비었다 — 필터 탓이 아니므로 출구가 아니라 온보딩을 낸다.
      $("libraryCount").textContent = "저장된 작업이 없습니다.";
      host.innerHTML =
        `<div class="empty"><div class="heading">저장된 작업이 없습니다</div>` +
        `<p>템플릿과 매핑을 묶어 첫 작업을 만드세요.\n데이터·행은 문서를 만들 때 고릅니다.</p>` +
        `<button class="btn primary" data-new-work>＋ 첫 작업 만들기</button></div>`;
      return;
    }
    $("libraryCount").textContent = `${shown}건`;
    if (!shown) {
      // 0건의 범인은 네 절단자(보기·방식·검색·태그) 중 하나다. 어느 것인지 되짚게 두지 않고
      // 한 번에 걷는 출구를 상주시킨다(§8.4 「절단과 무관한 도달성」).
      host.innerHTML =
        `<div class="empty"><div class="heading">조건에 맞는 작업이 없습니다</div>` +
        `<p>${isFiltered(s) || s.view !== "all"
          ? "보기·작업 방식·검색·태그 중 하나가 목록을 비웠습니다."
          : "이 보기에 해당하는 작업이 없습니다."}</p>` +
        `<button class="btn" data-clear-filters>필터 지우고 전체 보기</button></div>`;
      return;
    }
    host.innerHTML = sections.map((sec) => sectionHtml(sec, s.selected)).join("");
  }

  /* ---- 상세(detail) ---- */
  function bindingTable(rows) {
    if (!rows || !rows.length) return `<p class="muted">확정한 필드 연결이 없습니다.</p>`;
    return `<table class="tb lib-bindings"><thead><tr>` +
      `<th>문서 필드</th><th>데이터 항목</th><th>표시형</th></tr></thead><tbody>` +
      rows.map((b) =>
        `<tr${b.blank ? ' class="muted"' : ""}><td>${esc(b.template_field)}</td>` +
        `<td>${esc(b.source_label)}</td><td>${esc(b.format_label)}</td></tr>`).join("") +
      `</tbody></table>`;
  }

  function renderDetail(d) {
    const box = $("libraryDetail");
    if (!d) {
      // pane 자체가 이미 카드 테두리를 갖고 있어 .empty 의 점선 상자를 겹치지 않는다
      // (상자 안 상자 = 이 화면에만 있는 이질 문법). 안내 한 줄로 족하다.
      box.innerHTML = `<p class="lib-detail-blank muted">왼쪽에서 작업을 고르면 상세가 열립니다.</p>`;
      return;
    }
    const nm = esc(d.name);
    const causes = (d.health_causes || []).map((c) =>
      `<li>${esc(c.text)}</li>`).join("");
    const relink = d.template_missing
      ? `<button class="btn sm" data-relink="${nm}">템플릿 다시 연결…</button>` : "";
    const primary = d.primary || { target: "job", label: "문서 만들기에서 사용", hint: "" };
    const tags = Object.keys(d.tags || {}).length
      ? Object.entries(d.tags).map(([k, v]) =>
        `<span class="pill muted">${esc(k)}: ${esc(v)}</span>`).join(" ")
      : '<span class="muted">태그 없음</span>';
    box.innerHTML =
      `<div class="lib-detail-scroll" data-preserve-scroll>` +
      `<h2 class="lib-detail-name">${nm}</h2>` +
      `<p class="lib-detail-sub">${esc(d.mode_label)}` +
      (d.group ? ` · ${esc(d.group)}` : " · 그룹 없음") +
      ` · ${esc(d.last_run_display)}</p>` +
      // §19.7: 상세는 **모든 실제 원인**을 보인다(목록 배지는 최고 심각도 1건).
      (causes
        ? `<div class="note warnbox"><div class="cap">확인할 것</div>` +
          `<ul class="lib-causes">${causes}</ul>${relink}</div>`
        : "") +
      `<dl class="lib-detail-facts">` +
      `<dt>템플릿</dt><dd>${esc(d.template_name)}</dd>` +
      (d.filename_pattern ? `<dt>파일 이름 규칙</dt><dd>${esc(d.filename_pattern)}</dd>` : "") +
      (d.run_note ? `<dt>실행 방식</dt><dd>${esc(d.run_note)}</dd>` : "") +
      `</dl>` +
      // 저장된 항목 키를 그대로 보인다(지도 §10.8 판정 C) — 그 사실을 문안이 말한다.
      `<div class="cap">필드 연결</div>` +
      `<p class="muted lib-detail-note">작업에 저장된 데이터 항목 키입니다(현재 데이터의 열 이름이 아닙니다).</p>` +
      bindingTable(d.bindings) +
      `<div class="cap">태그</div><p class="lib-tags">${tags}</p>` +
      `</div>` +
      // 상시 행동은 상세 스크롤과 **분리해** pane 아래 고정한다(§19.6 마지막 문단).
      `<div class="lib-detail-acts">` +
      // 라벨-행동 일치: 라벨도 목적지와 함께 Python 이 낸다(표면이 짝을 다시 맞추지 않는다).
      `<button class="btn primary sm" data-use="${nm}" title="${esc(primary.hint)}">` +
      `${esc(primary.label)}</button>` +
      `<button class="btn sm" data-edit="${nm}">작업 편집</button>` +
      `<span class="lib-detail-manage">` +
      `<button class="btn sm" data-rename="${nm}">이름 변경</button>` +
      `<button class="btn sm" data-move="${nm}">그룹 이동</button>` +
      `<button class="btn sm" data-tags="${nm}">태그…</button>` +
      `<button class="btn sm" data-clone="${nm}">복제</button>` +
      // 솔리드 danger 는 확인 다이얼로그의 확정 버튼 몫이다(#184 행동 계층) — 상시 노출되는
      // 관리 줄에서 그 무게를 쓰면 경보가 싸구려가 된다. 여기선 글자색만 위험을 말한다.
      `<button class="btn sm lib-del" data-delete="${nm}">삭제</button>` +
      `</span></div>`;
  }

  /* ---- 이동: 대상 화면을 먼저 겨눈 뒤 셸 라우터로 전환(§9.3 순서 면) ---- */
  /* 「문서 만들기에서 사용」 — 명시적 버튼만 실행 문맥을 바꾼다(§19.8).

     3분기 **판정은 Python 이 낸다**(`job/prefer_work`): 데이터 준비·호환 여부는 링1 술어가
     이미 소유하므로 여기서 다시 계산하면 같은 상태를 두 곳이 판정한다(판정 단일 출처).
     이 함수가 하는 일은 반환 사유에 따른 라우팅뿐이다.

       promoted     → 활성으로 섰다. 화면만 전환한다(RecordRangeState 는 세션 소유라 생존).
       no_data      → 보관됐다. 게이트가 「데이터를 고르세요」를 말하고, 마운트 시 승격된다.
       incompatible → 활성 불변. 막힌 사유가 있는 「확인 필요」 탭으로 데려간다.

     겨눔이 실패하면(작업 소실·생성 중 등) await 가 throw 해 **화면을 바꾸지 않는다**. */
  /* 주 행동 — **목적지는 Python 이 낸다**(`detail.primary.target`, 리뷰 3R 근본 조치).
     표면이 매체를 보고 목적지를 조립하면 표시용 정규화(미연결→hwpx)와 실행 판정(원시 매체)의
     어휘가 갈려 「후보에서 배제 → 확인 필요에서도 배제 → 빈 화면」으로 끝난다. TXT(2R)와
     미연결(3R)이 그 한 클래스의 두 표본이었다. 여기서는 라우팅만 한다. */
  async function runPrimary(name) {
    const work = selectedWork(name);
    if (!work) return;
    const target = (work.primary && work.primary.target) || "job";
    if (target === "draft") {
      // 가드 문안·stale 재진술은 「기안」이 소유한 단일 경로에 위임한다. 취소 = 화면 불변.
      if (!window.DraftScreen) {
        window.alert("기안 화면 구성 요소(DraftScreen)가 로드되지 않았습니다.");
        return;
      }
      if (!(await window.DraftScreen.openWork(name))) return;
      window.Nav.go("draft");
      return;
    }
    if (target === "editor") {
      // 아직 「문서 만들기」가 받을 수 없는 작업(미연결·미상 방식) — 실제로 고칠 수 있는
      // 곳으로 보낸다. 빈 「확인 필요」에 착지시키는 것보다 정직하고 쓸모 있다.
      editJob(name, { "여기서 고칠 것": "이 작업은 아직 「문서 만들기」가 받을 수 없습니다" });
      return;
    }
    const r = await Bridge.call(JOB, "prefer_work", { name });
    // 편집기는 자기 화면으로 나갔으므로(재작성 F7) 「문서 만들기」로 가는 길에 모드 되돌림이
    // 필요 없다 — 이 화면이 보이는 동안 편집기는 열려 있지 않다(몰입 표면은 셸을 덮는다).
    window.Nav.go(JOB);
    if (r && r.reason === "incompatible" && window.JobScreen) {
      await window.JobScreen.openBrowseNeedsAction(name);
    }
  }

  /* 편집 진입 — 미저장 에디터 세션은 조용히 버리지 않고 확인(#25 미러) 후 복원.
     공용 흐름 EditorEntry.openGuarded 에 위임(job.openEditForRepair 와 단일 출처). */
  function editJob(name, evidence) {
    if (!window.EditorEntry) { window.alert("편집 진입 구성 요소(EditorEntry)가 로드되지 않았습니다."); return; }
    // 진입 문맥(계약 §5.1) — 돌아갈 자리는 이 화면이고, 보기·필터·선택은 이 화면이 자기
    // 상태로 들고 있으므로(§19.8) 복귀는 화면 키 하나면 족하다.
    EditorEntry.openGuarded(name, {
      entry_reason: "library",
      evidence: evidence || {},
      return_context: { surface: "library" },
    });
  }

  /* '＋ 새 작업' — 라벨-행동 일치: 이전 에디터 세션을 초기화한 뒤 이동한다(EditorEntry 단일 출처). */
  async function newWork() {
    if (window.EditorEntry) { await EditorEntry.newDraft(); return; }
    window.alert("편집 진입 구성 요소(EditorEntry)가 로드되지 않았습니다.");
  }

  /* ---- 관리 동사 ---- */
  /* 세션 정체와 결속된 동사는 「작업」 컨트롤러가 소유한다(§10.8 판정 F) — 여기서 부르고
     이 화면 스냅샷은 뒤이은 refresh 로 맞춘다. 판정을 두 곳에 두지 않는다. */
  async function jobDispatch(action, payload, selectIfOk) {
    const r = await Bridge.call(JOB, action, payload);
    // `selectIfOk` = 정체가 바뀐 뒤의 새 이름(이름 변경). 안 실으면 선택이 옛 이름에 남아
    // 상세가 닫히고 사용자가 보던 문맥이 사라진다 — 이름만 바뀌었을 뿐 그 작업은 그대로
    // 있는데(리뷰 2R). 한 왕복으로 끝내 중간 프레임에 상세가 깜빡이지도 않는다.
    // **실패하면 옮기지 않는다**(리뷰 3R): 이미 있는 이름으로 개명을 시도하면 거절되는데도
    // 선택이 그 **남의 작업**으로 옮겨가 오류 모달이 엉뚱한 상세 위에 뜬다.
    const ok = !(r && r.ok === false);
    await Bridge.call(SCREEN, "refresh", ok && selectIfOk ? { select: selectIfOk } : {});
    return r;
  }

  /* 관리 동사가 읽는 정체 = **상세 스냅샷**(`LAST.detail`)이다(리뷰 1R P1).
     목록 구획은 보기·검색·facet 이 걸러 낸 **투영**이라 선택한 행이 거기 없을 수 있다 —
     검색으로 가려진 뒤 「태그…」를 누르면 프리필이 `{}` 가 되고, 그대로 확정하면 실제
     태그가 통째로 지워진다(그룹 이동도 소속 그룹을 「그룹 없음」으로 조작한다). 상세는
     걸러지지 않은 `rows()` 에서 성형되므로 선택이 살아 있는 한 언제나 있다.
     그래도 없으면 **꾸며내지 않고 시끄럽게 멈춘다**(조용한 파괴 금지). */
  function selectedWork(name) {
    const d = LAST && LAST.detail;
    if (d && d.name === name) return d;
    window.alert(
      `'${name}' 작업의 현재 상태를 읽지 못해 중단했습니다.\n` +
      "목록을 새로 고친 뒤 다시 시도하세요.");
    return null;
  }

  /* 이동 다이얼로그의 도착지 후보는 **레지스트리 전역**(Python `group_names`)이다.
     화면 구획에서 파생하면 평면 보기나 켜진 필터가 목록에서 뺀 그룹이 도착지에서도
     사라져 있는 그룹으로 옮길 수 없다(리뷰 1R P2 — job·draft 화면과 같은 규약). */
  function allGroups() {
    return (LAST && LAST.group_names) || [];
  }

  async function renameJob(name, returnFocus) {
    await Modal.prompt({
      body: `'${name}' 의 새 이름을 입력하세요.`,
      value: name,
      returnFocus,
      validate: async (v) => {
        const next = String(v || "").trim();
        const r = await jobDispatch("rename_job", { name, new: v }, next);
        return r && r.ok === false ? (r.error || "이름을 바꾸지 못했습니다.") : "";
      },
    });
  }

  function moveJob(name, returnFocus) {
    const row = selectedWork(name);
    if (!row) return;
    moveDialog.open({
      groups: allGroups(),
      current: row.group || "",
      nameText: `'${name}' 을(를) 옮길 그룹`,
      returnFocus,
      onConfirm: (group) => {
        jobDispatch("set_group", { name, group })
          .catch((err) => window.alert(String((err && err.message) || err)));
      },
    });
  }

  /* 즐겨찾기 — 기제는 공용 몸통(js/intent.js)이 소유한다(리뷰 3R 근본 조치).
     이 파일 머리말은 처음부터 「의도 직렬화 기제를 그대로 옮긴다」고 적어 뒀는데
     실제로는 DOM 속성에 심어 둔 다음 값을 그대로 보냈다 — 계약이 거짓말한 자리다. 왕복 중 두 번째
     클릭이 낡은 값을 읽어 같은 의도를 두 번 보내면 `set_favorite` 이 멱등이라 껐다 켠 것이
     아니라 **켜진 채로 남고**, 동시 왕복은 마지막 클릭과 반대 상태를 영속시킬 수 있다.
     이제 「작업」 화면과 **같은 몸통**을 쓴다(두 표면이 한 기제). */
  const favorite = window.Intent.createFavorite({
    send: (name, value) => Bridge.call(SCREEN, "toggle_favorite", { name, value })
      .then((res) => {
        if (res && res.ok === false) window.alert(res.error || "즐겨찾기를 바꾸지 못했습니다.");
      }),
    onError: (msg) => window.alert(msg),
  });

  async function cloneJob(name) {
    try {
      const r = await Bridge.call(SCREEN, "clone_job", { name });
      if (r && r.ok === false) window.alert(r.error || "작업을 복제할 수 없습니다.");
    } catch (err) {
      window.alert(String((err && err.message) || err));
    }
  }

  /* '축=값, 축=값' 텍스트 → 태그 dict. 형식 오류면 {err: 문제 조각} — 호출부가 loud 처리. */
  function parseTags(text) {
    const tags = {};
    for (const part of text.split(",")) {
      const t = part.trim();
      if (!t) continue;
      const i = t.indexOf("=");
      if (i <= 0 || !t.slice(i + 1).trim()) return { err: t };
      tags[t.slice(0, i).trim()] = t.slice(i + 1).trim();
    }
    return { tags };
  }
  function sameTags(a, b) {
    const ka = Object.keys(a);
    return ka.length === Object.keys(b).length && ka.every((k) => b[k] === a[k]);
  }

  /* 태그 편집(#26 #2·D14) — 현재 태그를 '축=값' 쌍으로 재진술·프리필하고 통째 교체 저장.
     비우면 전체 해제(사용자가 명시적으로 지운 것 — 추측 아님). 형식 오류는 loud. */
  async function editTags(name, returnFocus) {
    const row = selectedWork(name);
    if (!row) return;
    const cur = row.tags || {};
    const ser = Object.entries(cur).map(([k, v]) => `${k}=${v}`).join(", ");
    // 왕복 가드(C9): 직렬화 직후 재파싱해 원본과 대조 — 값에 쉼표, 축에 쉼표/등호가 있으면
    // 이 인라인 프롬프트는 태그를 조용히 쪼개 재작성하거나 형식 오류로 막는다. 왕복 불가면
    // 조용히 진행하지 않고 시끄럽게 중단한다(confirm-or-alarm).
    const rt = parseTags(ser);
    if (rt.err !== undefined || !sameTags(rt.tags, cur)) {
      window.alert(
        `'${name}' 의 태그에 쉼표나 등호가 들어 있어 여기서 수정할 수 없습니다.\n` +
        `현재 태그: ${ser}\n\n작업 파일(.job.json)의 tags 를 직접 수정하세요.`);
      return;
    }
    await Modal.prompt({
      body:
        `'${name}' 의 태그를 '축=값' 쌍, 쉼표 구분으로 입력하세요. ` +
        `(예: 물품=의약품, 금액구간=소액)\n비우면 전부 해제합니다.`,
      value: ser,
      returnFocus,
      validate: async (raw) => {
        const parsed = parseTags(raw);
        if (parsed.err !== undefined) {
          return `태그 형식 오류: '${parsed.err}'. '축=값' 으로 입력하세요.`;
        }
        try {
          await Bridge.call(SCREEN, "set_tags", { name, tags: parsed.tags });
          return "";
        } catch (err) {
          return String((err && err.message) || err);
        }
      },
    });
  }

  /* 템플릿 다시 연결(#67) — 공용 흐름(relink.js)에 위임. 커밋 재진술을 alert 로 병기한다
     (행만 조용히 바뀌는 것 방지) — 사용자 취소는 본인 행위라 재알림 생략, 실패는 공용 흐름이 alert. */
  function relinkTemplate(name) {
    Relink.relinkTemplate(SCREEN, name, (msg, kind) => {
      if (kind === "ok") window.alert(msg);
    });
  }

  /* 작업 삭제 — 30일 휴지통 + 최근 1건 복원. 사후 관용이 있으므로 사전 확인을 없앤다.
     단 작업·기안 화면에 무장 세션이 열려 있으면 백엔드가 needs_confirm 을 돌려준다(#268
     리뷰) — 세션의 선택·진행은 파일 복원으로도 못 돌아오는 소실이라 확인 왕복만 남긴다. */
  async function deleteJob(name, returnFocus) {
    let r = await Bridge.call(SCREEN, "delete_job", { name });
    if (r && r.needs_confirm) {
      const where = r.screen === "draft" ? "기안" : "작업";
      const ok = await window.Modal.confirm({
        title: "작업 삭제 확인",
        body: `작업 '${name}' 이(가) ${where} 화면에 진행 중인 세션으로 열려 있습니다.\n` +
          `삭제하면 그 세션의 선택·데이터·진행이 함께 사라지며, 파일을 복원해도 세션은 돌아오지 않습니다.`,
        confirmLabel: "휴지통으로 이동", cancelLabel: "취소",
        returnFocus,
      });
      if (!ok) return;
      r = await Bridge.call(SCREEN, "delete_job", { name, confirm: true });
    }
    if (r && r.undo) window.UndoToast.show(`작업 '${name}' 을(를) 휴지통으로 옮겼습니다.`, async () => {
      const restored = await Bridge.call(SCREEN, "undo_delete_job", {});
      if (restored && restored.ok === false) throw new Error(restored.error);
    });
  }

  /* ---- 그룹 헤더 ⋮(그룹 이름 변경·해산) ---- */
  function closeGroupMenu() { menuFor = null; groupMenu.hide(); }
  function toggleGroupMenu(group, btn) {
    if (menuFor && menuFor.group === group) { closeGroupMenu(); return; }
    menuFor = { group, trigger: btn };
    groupMenu.show(
      `<button data-gmenu="rename">그룹 이름 변경…</button>` +
      `<div class="sep"></div>` +
      `<button data-gmenu="disband" class="danger">그룹 해산</button>`, btn);
  }
  async function onGroupMenuClick(e) {
    const btn = e.target.closest("button[data-gmenu]");
    if (!btn || menuFor === null) return;
    const { group, trigger } = menuFor, act = btn.dataset.gmenu;
    closeGroupMenu();
    // 「그룹 없음」은 저장된 group 이 아니라 그 부재의 이름이라 개명·해산 대상이 아니다.
    if (!group) { window.alert("「그룹 없음」은 이름을 바꾸거나 해산할 수 없습니다."); return; }
    if (act === "rename") await renameGroup(group, trigger);
    else if (act === "disband") await disbandGroup(group, trigger);
  }

  function groupCount(group) {
    const sec = ((LAST && LAST.sections) || []).find((s) => s.value === group);
    return sec ? sec.count : 0;
  }

  async function renameGroup(group, returnFocus) {
    const seen = groupCount(group);
    // 병합 확인은 **prompt 가 닫힌 뒤**에 한다(리뷰 3R): modal.js 는 진행 중인 promise
    // 다이얼로그가 있으면 두 번째를 거절하므로(pendingDialog 직렬화), validate 안에서 연
    // confirm 은 언제나 false 로 풀려 병합이 조용히 사라지고 재진입 alert 만 뜬다.
    // 「작업」 화면과 같은 순서 — 값을 먼저 받고, 확정 왕복은 그다음이다.
    const val = await Modal.prompt({
      title: "그룹 이름 변경",
      // 수치는 약속이 아니라 관측이다(#149) — 옮겨지는 집합의 규칙('전부')이 언제나 참이다.
      body: `그룹 '${group}' 의 새 이름을 입력하세요. 소속 작업 전부(지금 기준 ${seen}건)가 함께 옮겨집니다.`,
      value: group,
      returnFocus,
    });
    if (val === null) return;
    let r = await jobDispatch("rename_group", { name: group, new: val, seen });
    if (r && r.needs_confirm) {
      // 기존 그룹으로의 개명 = 병합이라 건수를 재진술하고 확정을 받는다. 수치는 약속이 아니라
      // **그 시점의 관측**이다(#149) — 이동 집합의 규칙('전부')이 실제로 참인 진술이다.
      const ok = await Modal.confirm({
        title: "그룹 병합 확인",
        body: `'${r.new}' 그룹이 이미 있습니다(현재 ${r.target_count}건).\n` +
          `'${r.name}' 의 작업 전부(지금 기준 ${r.count}건)를 그 그룹으로 합칩니다.`,
        confirmLabel: "합치기", cancelLabel: "취소",
        returnFocus,
      });
      if (!ok) return;
      r = await jobDispatch("rename_group",
        { name: group, new: val, seen: r.count, confirm: true });
    }
    if (r && r.ok === false) { window.alert(r.error || "그룹 이름을 바꾸지 못했습니다."); return; }
    if (r && r.drift_note) window.alert(r.drift_note);
  }

  async function disbandGroup(group, returnFocus) {
    const r = await jobDispatch("disband_group", { name: group });
    if (!r || !r.needs_confirm) return;
    const ok = await window.Modal.confirm({
      title: "그룹 해산 확인",
      // 이동 집합은 '해산 시점의 소속 전부'라는 **규칙**으로 적고 수치는 지금 기준 관측으로
      // 덧붙인다(#149) — 확인 왕복 사이 소속이 바뀌어도 규칙 쪽은 언제나 참이다. 좌 목록이
      // 죽으며 넘어온 문안 계약이다(F2 PR-B: 삭제는 의무를 상속한다).
      body: `그룹 '${group}' 을(를) 해산합니다. 해산 시점의 소속 작업 전부(지금 기준 ${r.count}건)가 ` +
        `「그룹 없음」으로 옮겨지고 작업 자체는 그대로입니다.`,
      confirmLabel: "해산", cancelLabel: "취소",
      returnFocus,
    });
    if (!ok) return;
    const done = await jobDispatch("disband_group", { name: group, confirm: true, seen: r.count });
    if (done && done.drift_note) window.alert(done.drift_note);
  }

  /* ---- 이벤트(위임) ---- */
  function onListClick(e) {
    const fav = e.target.closest("[data-fav]");
    // 다음 값은 DOM 이 아니라 **미결 의도**에서 계산된다(공용 몸통) — 여기선 현재 표시 상태만
    // 넘긴다. 빠른 2연타가 서로의 의도를 삼키지 않게 하는 §8.4 4행의 이행분이다.
    if (fav) {
      favorite.toggle(fav.dataset.fav, fav.getAttribute("aria-pressed") === "true");
      return;
    }
    const gm = e.target.closest("[data-group-more]");
    if (gm) { toggleGroupMenu(gm.dataset.groupMore, gm); return; }
    const gh = e.target.closest("[data-group]");
    if (gh) {
      // 접힘은 보기 상태라 클릭한 프레임에 먼저 반영하고 영속 요청은 뒤에서 보낸다(공용 규율).
      GroupList.toggleGroup(gh, () => axis("toggle_group", { group: gh.dataset.group }));
      return;
    }
    const row = e.target.closest("[data-work]");
    if (row) { axis("select_work", { name: row.dataset.work }); return; }
    const nw = e.target.closest("[data-new-work]");
    if (nw) { newWork(); return; }
    const cf = e.target.closest("[data-clear-filters]");
    // 「지우고 전체 보기」는 **대기 중인 검색까지** 걷겠다는 의사다 — 안 취소하면 방금 지운
    // 필터 위로 타이머가 옛 검색어를 다시 얹는다(리뷰 4R).
    if (cf) { cancelPendingSearch(); axis("clear_filters", {}); }
  }

  function onDetailClick(e) {
    const pick = (a) => e.target.closest("[data-" + a + "]");
    const use = pick("use"); if (use) { runPrimary(use.dataset.use); return; }
    const ed = pick("edit"); if (ed) { editJob(ed.dataset.edit); return; }
    const rn = pick("rename"); if (rn) { renameJob(rn.dataset.rename, rn); return; }
    const mv = pick("move"); if (mv) { moveJob(mv.dataset.move, mv); return; }
    const tg = pick("tags"); if (tg) { editTags(tg.dataset.tags, tg); return; }
    const cl = pick("clone"); if (cl) { cloneJob(cl.dataset.clone); return; }
    const rl = pick("relink"); if (rl) { relinkTemplate(rl.dataset.relink); return; }
    const dl = pick("delete"); if (dl) { deleteJob(dl.dataset.delete, dl); }
  }

  function onToolbarClick(e) {
    const view = e.target.closest("[data-library-view]");
    if (view) { axis("set_view", { view: view.dataset.libraryView }); return; }
    const mode = e.target.closest("[data-library-mode]");
    if (mode) { axis("set_mode", { mode: mode.dataset.libraryMode }); return; }
    const chip = e.target.closest("[data-axis]");
    if (chip && !chip.disabled) {
      axis("toggle_facet", { axis: chip.dataset.axis, value: chip.dataset.val });
      return;
    }
    if (e.target.id === "libraryClearFacets") axis("clear_facets", {});
  }

  /* 보기 탭 좌우 이동(role=tablist 키보드 계약) — 탭은 primary classification 이라 화살표로
     훑을 수 있어야 한다(§19.6 · 문서 탐색 탭과 같은 규약). */
  function onTabsKeydown(e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const tabs = Array.from($("libraryViewTabs").querySelectorAll("[data-library-view]"));
    const i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    next.focus();
    axis("set_view", { view: next.dataset.libraryView });
  }

  function wire() {
    $("libraryNewWork").addEventListener("click", newWork);
    $("libraryList").addEventListener("click", onListClick);
    $("libraryDetail").addEventListener("click", onDetailClick);
    $("libraryCorrupt").addEventListener("click", onCorruptClick);
    $("libraryViewTabs").addEventListener("click", onToolbarClick);
    $("libraryViewTabs").addEventListener("keydown", onTabsKeydown);
    $("libraryModeFilters").addEventListener("click", onToolbarClick);
    $("libraryFacets").addEventListener("click", onToolbarClick);
    $("libraryGroupMenu").addEventListener("click", onGroupMenuClick);
    // ⋮ 메뉴 바깥 닫기(job/tpl 동형) — 캡처 클릭 억제 + 바깥 pointerdown + Escape.
    window.Popover.wireDismiss({
      isOpen: () => menuFor !== null,
      contains: (t) => !!(t.closest("#libraryGroupMenu") || t.closest(".job-more")),
      close: closeGroupMenu,
    });
    moveDialog.wire("libMoveOk", "libMoveCancel");
    $("librarySearch").addEventListener("input", (e) => {
      // 디바운스: 타이핑 중 매 글자마다 왕복하면 캐럿·포커스가 재렌더에 시달린다.
      if (searchTimer) clearTimeout(searchTimer);
      const text = e.target.value;
      searchTimer = setTimeout(() => {
        searchTimer = null;
        axis("set_query", { text });
      }, 180);
    });
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    render(await Bridge.initial(SCREEN));
  }

  window.LibraryScreen = { init };
})();
