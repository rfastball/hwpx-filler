/* 「작업」 화면 — 좌 master 목록 + 우 상세 패널 **두 모드**(R-flow #90 · 블록 2 개정 39~41).
   실행 모드(기본)=세션 패널 4존, 편집 모드=정의 호스트(#jobEditHost — editor.js 가 렌더).
   안정 DOM(index.html) + Python 이 window.__push('job', snapshot) 로 값만 채운다(run/txt 패턴).
   표현 계층(거울 테이블·재진술 블록·게이트·진행/로그)만 여기서 만든다 — VM 로직 아님(링2 대체, #87).
   덮어쓰기 확인은 공용 Modal.confirm의 수치 합성 본문으로 — 네이티브 다이얼로그 무사용이라 #86
   재유입 가드에 처음부터 부합한다. 존 배치(헤더·데이터·본문·완료)는 여기서 안정 DOM 에 값을 채운다. */
(function () {
  const SCREEN = "job";
  const $ = (id) => document.getElementById(id);
  let LAST = null;
  let generating = false;
  let lastSessionKey = null;  // 완료 존 세션 스코프 판정(결정 7) — 세션 변경 시에만 리셋
  let restateExpanded = false;  // 재진술 블록 이름 목록 펼침(대량 표본+「외 N건」, 결정 36)
  let lastRestateKey = null;    // 펼침 리셋 판정 — 작업/데이터 전환 시 펼침을 끈다(세션 누수 방지)
  let mirrorRowCount = 0;       // 420px 실측 캡의 현재 필드 수(#272)
  let mirrorResizeObserver = null;
  /* 패널 모드(결정 39·40) — "run"(행 클릭=실행 세션, 기본) | "edit"(정의 편집·신규 마법사).
     모드는 표시 상태일 뿐: 실행 세션은 JobController, 정의 세션은 EditorController 가 각자
     소유해 전환이 어느 쪽도 파괴하지 않는다. 파괴 가능 지점은 진입 가드가 지킨다 —
     T1(세션 전환)=selectJobGuarded, 미저장 정의 덮어쓰기=EditorEntry.openGuarded. */
  let MODE = "run";

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  /* ---- 데이터 존(필터 테이블·열 패널·칩·스트립) = 공용 팩토리(datazone.js, PR-2a 추출) ----
     표면 계약·리뷰 결정 주석은 팩토리가 소유한다 — 여기는 화면 고유값만 주입한다:
     id 묶음 · 선두 「문서」 열(F33 승계: 실파일명 + 식별 요약) · 빈 상태/스트립 문안 ·
     세션 지문(renderTable 리셋 판정 — 완료 존 sessionKey 와 다른 축: 선택 제외) · log 채널.
     log 는 함수 선언이라 호이스팅으로 이 시점 참조가 안전하다. */
  const dz = window.DataZone.create({
    screen: SCREEN,
    ids: {
      selCount: "jobSelCount", search: "jobFilterSearch", reapply: "jobFilterReapply",
      chips: "jobFilterChips", strip: "jobSelStrip",
      tableHost: "jobTableHost", tableWrap: "jobTableWrap", tableEmpty: "jobTableEmpty",
      tableHead: "jobTableHead", tableBody: "jobTableBody", colPanel: "jobColPanel",
      selAll: "jobSelAll", selNone: "jobSelNone",
    },
    rowIdPrefix: "jobRow-",  // preserve.js 가 id 로 포커스 복원 — 접두 변경은 보존 계약 파손
    lead: {
      header: "문서",
      hint: "선택하면 파일명이 정해집니다",
      bodyHtml(r) {
        const doc = r.name
          ? `<span class="doc-name">${esc(r.name)}</span>`
          : `<span class="doc-off" aria-hidden="true">—</span>`;
        const sum = r.summary ? `<span class="doc-sum">${esc(r.summary)}</span>` : "";
        return doc + sum;
      },
    },
    copy: {
      emptyNoData: "데이터를 선택하면 생성 대상 문서가 여기에 표시됩니다.",
      emptyFiltered: "필터와 일치하는 행이 없습니다. 위 칩의 정의를 확인하세요.",
      emptyNoRows: "데이터에 행이 없습니다.",
      stripLead: (n) => `필터 밖 선택 <b>${n}행</b>도 생성에 포함됩니다: `,
    },
    tableKey: (s) => (s.job_name || "") + "|" + (s.data_source_label || ""),
    log,
  });

  /* ---- 그룹 목록 기제(부유 ⋮ 메뉴·이동 다이얼로그) = 공용 팩토리(grouplist.js) ----
     위치잡기·다이얼로그 조립은 팩토리 소유(template.js 와 단일 출처). 여기는 화면 고유값만:
     메뉴 내용·menuFor 정체는 open/close 가 만들고, 이동 확정은 onConfirm 으로 디스패치한다. */
  const rowMenu = window.GroupList.createMenu({ menuId: "jobRowMenu" });
  const moveDialog = window.GroupList.createMoveDialog({
    modalId: "groupMoveModal", listId: "groupMoveList", errId: "groupMoveErr",
    nameId: "groupMoveJob", radioName: "grpMove",
    newRadioId: "grpMoveNewRadio", newNameId: "grpMoveNewName",
  });

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    if (s && s.progress) { renderProgress(s.progress); return; }  // 진행 델타(경량)
    Preserve.around(() => {  // 매핑/레코드 포커스·스크롤 보존(#28)
      LAST = s;
      dz.sync(s);  // 존 렌더는 아래 hasJob 게이트를 타지만 스냅샷 관측은 무조건 — 팩토리
                   // flushPendingSearch 의 stale LAST 오발 차단(리뷰: master 계약 복원)
      renderMaster(s);
      const hasJob = !!s.has_job;
      syncModeDisplay(hasJob);
      if (hasJob) {
        renderHeader(s);
        renderData(s);
        renderPreflight(s);
        renderMirror(s);
        dz.render(s);  // 데이터 존(테이블·칩·스트립) — 팩토리 소유(datazone.js)
        renderRestate(s);
        renderGateAndFolder(s);
      }
      renderStatus(s);
      if (MODE === "edit") setEditStatus();  // 편집 모드 표지는 세션 상태 pill 을 덮는다
      // 완료 존(생성 결과·로그)은 세션 스코프로 보존한다(결정 7) — 매 push 가 아니라 세션이
      // 실제로 바뀔 때만 무효화한다. 레일 이탈 후 복귀(REFRESH_ON_NAV 재push)는 세션 불변이라
      // 결과가 살아남고(리뷰 #3: 결정 7 위배 봉합), 작업·데이터·선택 변경(#28 UD-10)에서만
      // 이전 결과를 지운다. nav 는 CSS 토글이라 DOM 은 어차피 살아있다.
      const key = sessionKey(s);
      if (!generating && key !== lastSessionKey) resetGenResult();
      lastSessionKey = key;
      setBusy(generating);
    });
  }

  /* 이전 생성 결과(요약·진행바·로그)를 기본 상태로 되돌린다(오래된 성공 잔존 방지, #28). */
  function resetGenResult() {
    $("jobGenBar").style.width = "0%";
    const r = $("jobGenResult");
    r.textContent = "";
    r.className = "run-result";
    $("jobGenLog").textContent = "";
    logStarted = false;
  }

  /* 세션 지문 — 완료 존 보존 판정(결정 7). 작업·데이터·저장 폴더·선택 집합이 그대로면 같은
     세션이라 이전 생성 결과가 유효하다. 선택은 정확한 인덱스 집합으로(개수만으론 행 교체를
     놓친다). 작업 미선택이면 빈 문자열 = 세션 없음. */
  function sessionKey(s) {
    if (!s.has_job) return "";
    const sel = (s.records || []).filter((r) => r.selected).map((r) => r.index).join(",");
    return [s.job_name, s.data_source_label, s.out_dir, sel].join("|");
  }

  /* ---- 패널 두 모드(결정 39·40) ---- */
  function syncModeDisplay(hasJob) {
    const edit = MODE === "edit";
    if (edit || !hasJob) {
      // 펼침 면의 실 DOM이 overlay 슬롯에 남은 채 편집 호스트를 여는 교차 모드 상태를 막는다.
      window.SurfaceSheet.closeAndRestore("jobConfirmSheet");
      window.SurfaceSheet.closeAndRestore("dataSheet");
    }
    $("jobZones").style.display = (!edit && hasJob) ? "" : "none";
    // 하단 sticky 생성 액션바(#179 슬라이스 5b) — 세션 4존과 같이 실행 모드·작업 선택 시에만.
    // 편집 모드(정의 호스트)·미선택에선 숨어 고아 버튼이 되지 않는다.
    $("jobActionBar").style.display = (!edit && hasJob) ? "" : "none";
    $("jobEmptyPanel").style.display = (edit || hasJob) ? "none" : "";
    $("jobEditHost").style.display = edit ? "" : "none";
  }

  function setEditStatus() {
    const st = $("jobStatus");
    st.dataset.level = "idle";
    st.textContent = "편집 모드";
  }

  /* 편집 모드 진입 — 미저장 정의 확인은 호출측 단일 출처가 이미 지킨다(기존 작업=
     EditorEntry.openGuarded, 신규=home.newJob 대칭 확인). 여기는 표시 전환만. */
  function showEditMode() {
    MODE = "edit";
    syncModeDisplay(!!(LAST && LAST.has_job));
    setEditStatus();
    $("jobEditExitNote").style.display = "none";  // 편집 재진입 = 복귀 고지 소임 종료
    $("jobEditResume").style.display = "none";
  }

  /* 실행 복귀(T2 재정의, 블록 2 개정 결정 45) — 가드 대상이 화면 인계에서 "편집 중 행 클릭"
     으로 이동했다. 전환은 **비파괴**다: 정의 세션은 EditorController 에 그대로 살고, 미저장
     정의를 덮을 수 있는 유일한 경로(다른 작업 편집·새 작업)는 openGuarded/newJob 확인이
     지킨다. 그래서 묻지 않고 **고지**만 한다(T2 종결 해석과 동형 — 물을 파괴가 없으면 확인
     모달은 소음이다). 반환 = 미저장 편집 존재 여부(호출측이 고지 표면을 켠다). */
  async function exitEditToRun() {
    if (MODE === "run") return false;
    let busy = false;
    try {
      busy = await Bridge.editorHasUnsavedWork();
    } catch (err) {
      log("편집 상태 확인 실패: " + String((err && err.message) || err));
    }
    MODE = "run";
    syncModeDisplay(!!(LAST && LAST.has_job));
    if (LAST) renderStatus(LAST);
    return busy;
  }

  /* 신규 마법사 취소 착지 — 백엔드 discard_session 뒤 실행/미선택 패널로 돌아간다. */
  function showRunMode() {
    MODE = "run";
    syncModeDisplay(!!(LAST && LAST.has_job));
    if (LAST) renderStatus(LAST);
    $("jobEditExitNote").style.display = "none";
    $("jobEditResume").style.display = "none";
  }

  /* T2 고지 표면(PR-2 리뷰 F4) — 완료 존 log() 는 세션 전환 리셋(resetGenResult)·존 은닉에
     증발했다. 이 요소는 어떤 렌더 함수도 쓰지 않는 JS 소유라 push·세션 리셋을 관통해
     살아남고, 사용자가 확인 버튼으로 걷거나 편집 재진입 때 걷힌다(고지=읽힐 때까지). */
  function showExitNote() {
    const el = $("jobEditExitNote");
    el.innerHTML =
      `저장하지 않은 편집이 있습니다. 저장 전에는 실행에 반영되지 않습니다. ` +
      // 복귀 버튼(PR-5 리뷰 F1) — 레일 심 사망 후 이 고지가 유일한 **비파괴** 복귀 경로다
      // (다른 진입은 전부 세션 초기화/재로드). 고지가 약속한 「돌아가면 그대로」의 실행 수단.
      `<button class="btn sm" data-act="return-to-edit">편집으로 돌아가기</button> ` +
      `<button class="btn sm" data-act="dismiss-exit-note">확인</button>`;
    el.style.display = "";
    // 고지를 확인해 걷어도 미저장 편집 세션의 비파괴 복귀 경로는 헤더에 남는다(#218 G4).
    $("jobEditResume").style.display = "";
  }

  /* 좌 목록 갱신 — 편집 저장 직후 새/개명 작업이 바로 보이게(editor.js doSave 가 호출).
     실패 재진술은 모드를 따른다(PR-2 리뷰 F10): 편집 모드에선 완료 존 log 가 숨어 있어
     조용한 실패가 된다 — 그때는 alert 로 loud. */
  function refreshList() {
    Bridge.call(SCREEN, "refresh", {}).catch((err) => {
      const msg = "목록 갱신 실패: " + String((err && err.message) || err);
      if (MODE === "edit") window.alert(msg);
      else log(msg);
    });
  }

  /* ---- 좌 master 목록(HWPX 구획 + 사용자 그룹, 결정 43) ----
     구획/그룹/접힘의 판정은 Python(_job_sections)이 내리고 여기는 받은 구획을 그리기만 한다.
     행 면 = 이름 단독(결정 7) + 호버·포커스 노출 ⋮(관리 메뉴). 그룹 0개면 job_flat 로
     헤더·들여쓰기 없는 평면(퇴화 불변식 — 현행 모습 그대로). */
  let RENAMING = null;  // {name, value} 인라인 이름 변경 중(재렌더 생존용 지역 상태)

  function rowHtml(r) {
    if (RENAMING && RENAMING.name === r.name) {
      return `<div class="job-row"><input class="field job-rename" id="jobRenameInput"` +
        ` data-orig="${esc(r.name)}" value="${esc(RENAMING.value)}" aria-label="새 이름">` +
        (RENAMING.error ? `<span class="note dangerbox" role="alert">${esc(RENAMING.error)}</span>` : "") +
        `</div>`;
    }
    return `<div class="job-row">` +
      `<button class="job-item" data-job="${esc(r.name)}" aria-current="${r.selected ? "true" : "false"}">${esc(r.name)}</button>` +
      `<button class="job-more" data-more="${esc(r.name)}" aria-haspopup="true" aria-label="작업 관리">⋮</button></div>`;
  }

  function renderMaster(s) {
    const host = $("jobListHwpx");
    const empty = $("jobListHwpxEmpty");
    const sections = s.job_sections || [];
    const total = sections.reduce((n, sec) => n + sec.rows.length, 0);
    empty.style.display = total ? "none" : "";
    if (s.job_flat) {
      host.innerHTML = sections.map((sec) => sec.rows.map(rowHtml).join("")).join("");
      return;
    }
    host.innerHTML = sections.map((sec) => {
      const label = sec.group || "그룹 없음";
      // 접힘 화살표는 이름 오른쪽·호버 노출, 접힌 그룹은 상시 노출(결정 5 — CSS 가 담당).
      const head =
        `<div class="job-grp">` +
        `<button class="job-grp-head" data-grp-toggle="${esc(sec.group)}" aria-expanded="${sec.collapsed ? "false" : "true"}">` +
        `<span class="grp-name">${esc(label)}</span>` +
        `<span class="grp-count">${sec.count}</span>` +
        `<span class="grp-caret">${sec.collapsed ? "▸" : "▾"}</span></button>` +
        (sec.group
          ? `<button class="job-more grp-more" data-grp-more="${esc(sec.group)}" aria-haspopup="true" aria-label="그룹 관리">⋮</button>`
          : "") +
        `</div>` +
        `<div class="job-grp-rows"${sec.collapsed ? " hidden" : ""}>${sec.rows.map(rowHtml).join("")}</div>`;
      return head;
    }).join("");
  }

  /* ---- 헤더 존 — 작업 정체(이름·템플릿·재연결 동선) ---- */
  function renderHeader(s) {
    $("jobHeadTitle").textContent = s.job_name || "";
    const tpl = $("jobHeadTpl");
    tpl.innerHTML = s.template_name
      ? `템플릿 <span class="mono">${esc(s.template_name)}</span> ${PathTrack.affordances(s.template_path)}`
      : `템플릿 경로가 비어 있습니다. 편집 모드의 템플릿 탭에서 지정하세요.`;
    // 템플릿 다시 연결(#67)은 복구 동선 — 파일이 실제로 없을 때만 노출(F30, "정상은 조용히").
    const relink = $("jobRelink");
    if (s.template_missing) {
      relink.style.display = "block";
      relink.className = "note warnbox";
      relink.innerHTML =
        `템플릿 파일을 찾을 수 없습니다. ` +
        `<button class="btn sm" data-act="relink-template" data-busy-lock>템플릿 다시 연결…</button>`;
    } else {
      relink.style.display = "none";
      relink.innerHTML = "";
    }
  }

  /* ---- 데이터 존 — 겨눔 라벨·자동 조준 재진술 ---- */
  function renderData(s) {
    $("jobDataLabel").value = s.data_source_label || "";
    const note = $("jobDataNotice");
    const n = s.data_notice;
    if (n && n.text) {
      note.style.display = "block";
      // 실패(warn)만 시끄럽게, 성공(ok)은 muted 한 줄(F32: 정상 초록 배너는 노이즈).
      note.className = "note " + (n.level === "ok" ? "quiet" : "warnbox");
      note.textContent = (n.level === "ok" ? "" : "확인 필요: ") + n.text;
    } else {
      note.style.display = "none";
      note.textContent = "";
    }
  }

  function renderPreflight(s) {
    const box = $("jobPreflight");
    const p = s.preflight || { level: "", text: "" };
    if (!s.has_data || !p.text) { box.style.display = "none"; return; }
    box.style.display = "block";
    const cls = p.level === "ok" ? "quiet" : p.level === "danger" ? "dangerbox" : "warnbox";
    box.className = "preflight note " + cls;
    box.style.whiteSpace = "pre-line";
    box.textContent = p.text;
  }

  /* ---- 본문 존 거울 = 필드 채움 테이블(결정 36 ⓑ) ----
     hwpx 본문은 앱에서 렌더 못 하므로 거울이 비추는 것은 "생성될 문서의 채움 상태"다. ADR-E
     배지는 별도 UI가 아니라 거울의 행: 미입력 행 클릭=확인, 재클릭=철회(UD-19). danger(드리프트)는
     ack 로 안 풀리므로 같은 표에 섞지 않고 거울 자리 차단 배너 + 행동 링크로 분리한다(결정 36·S9). */
  function renderMirror(s) {
    const host = $("jobMirror");
    const drift = s.drift || [];
    if (drift.length) {
      // danger = 차단 배너 + 상시 행동 링크(막다른 경보 금지 — 경보 어포던스는 숨지 않는다).
      host.innerHTML =
        `<div class="mir-drift" role="alert">` +
        `<p>템플릿 구조가 확정 매핑과 달라져 문서를 생성할 수 없습니다. ` +
        `어긋난 필드: <b>${esc(drift.join(", "))}</b>.</p>` +
        `<button class="btn sm" data-act="fix-mapping" data-busy-lock>편집에서 매핑 확정…</button>` +
        `</div>`;
      syncMirrorCap(0);
      return;
    }
    // 미해소 파일명 토큰(#128) — **드리프트와 같은 danger 자격**이라 같은 자리에서 같은 형상으로
    // 발화한다(주석 9: 배너 소관은 드리프트·토큰 둘 다). 종전엔 이 자리가 전 행 「채움」 표를
    // 그려 문서가 건강해 보이고, 재진술 블록은 danger 라 말없이 사라지고, 남는 신호는 하단 회색
    // 캡션 한 줄뿐이었다 — 차단은 걸렸는데 무엇을 하라는 출구가 없는 막다른 경보.
    const nameTokens = s.name_tokens || [];
    if (nameTokens.length) {
      const toks = nameTokens.map((t) => `{{${t}}}`).join(", ");
      host.innerHTML =
        `<div class="mir-drift" role="alert">` +
        `<p>파일명 패턴의 토큰을 채우지 못해 문서를 생성할 수 없습니다. ` +
        `남는 토큰: <b>${esc(toks)}</b>.</p>` +
        `<button class="btn sm" data-act="fix-filename" data-busy-lock>편집에서 파일명 패턴 고치기…</button>` +
        `</div>`;
      syncMirrorCap(0);
      return;
    }
    const rows = s.mirror || [];
    if (!rows.length) {  // 선택 0(또는 데이터 미겨눔) = 생성될 문서 없음
      host.innerHTML = `<p class="mirempty muted capnote">행을 선택하면 이 문서에 들어갈 값이 여기 표시됩니다.</p>`;
      syncMirrorCap(0);
      return;
    }
    host.innerHTML =
      `<div class="tbwrap"><table class="tb mir"><tbody>` +
      rows.map(mirrorRow).join("") + `</tbody></table></div>`;
    syncMirrorCap(rows.length);
  }

  /* 420px 캡은 필드 수가 아니라 실 오버플로로 판정한다. 배율·문안 줄바꿈에서도 거짓 표지를
     내지 않고, 펼침 면에선 max-height 해제 뒤 ResizeObserver가 표지를 즉시 걷는다. */
  function measureMirrorCap() {
    const host = $("jobMirror"), strip = $("jobMirrorCapstrip");
    const clipped = mirrorRowCount > 0 && host.clientHeight > 0
      && host.scrollHeight > host.clientHeight + 1;
    strip.hidden = !clipped;
    strip.innerHTML = clipped
      ? `전체 <b>${mirrorRowCount}필드</b> — ` +
        `<button class="btn sm" type="button" data-mirror-expand>펼쳐서 확인 ⤢</button>`
      : "";
  }

  function syncMirrorCap(count) {
    mirrorRowCount = count;
    measureMirrorCap();
    if (window.requestAnimationFrame) window.requestAnimationFrame(measureMirrorCap);
  }

  function openJobConfirmSheet(e) {
    // capstrip 클릭은 위임되어 currentTarget이 비포커스 strip이다. 실제 버튼을
    // 우선 보존하고, 프로그램 호출이면 영구 헤더 버튼을 복귀점으로 쓴다.
    const trigger = e && e.target && e.target.closest
      ? e.target.closest("button") : null;
    window.SurfaceSheet.open({
      modalId: "jobConfirmSheet",
      returnFocus: trigger || $("jobMirrorExpand") || document.activeElement,
      initialFocus: $("jobConfirmSheetClose"),
      moves: [
        { id: "jobMirror", slotId: "jobConfirmSheetMirrorSlot" },
        { id: "jobRestate", slotId: "jobConfirmSheetRestateSlot" },
      ],
      afterRestore: measureMirrorCap,
    });
  }

  function openJobDataSheet(e) {
    $("dataSheetTitle").textContent = "작업 데이터 행 고르기";
    window.SurfaceSheet.open({
      modalId: "dataSheet",
      returnFocus: e && e.currentTarget ? e.currentTarget : document.activeElement,
      initialFocus: $("dataSheetClose"),
      moves: [
        { id: "jobRecsHead", slotId: "dataSheetSlot" },
        { id: "jobFilterChips", slotId: "dataSheetSlot" },
        { id: "jobTableHost", slotId: "dataSheetSlot" },
        { id: "jobSelStrip", slotId: "dataSheetSlot" },
        { id: "jobColPanel", slotId: "dataSheetSlot" },
      ],
    });
  }

  function mirrorRow(r, i) {
    const nm = esc(r.name);
    const val = esc(r.value);
    // 안정 id — 클릭형 미입력 행이 ack 재렌더를 가로질러 포커스를 잃지 않게(preserve.js 는 id 로
    // 복원). 행 index 는 필드 집합이 안정인 세션 내에서 안정하다(이름 특수문자 회피).
    const id = `jobMirF-${i}`;
    if (r.state === "filled") {
      return `<tr class="mir-row" id="${id}"><td class="mir-f">${nm}</td><td class="mir-v">${val}</td>` +
        `<td class="mir-s"><span class="st filled">채움${r.formatted ? " · 표시형" : ""}</span></td></tr>`;
    }
    if (r.state === "blank") {
      return `<tr class="mir-row blankd" id="${id}"><td class="mir-f">${nm}</td><td class="mir-v">${val}</td>` +
        `<td class="mir-s"><span class="st blankd">비움 확정</span></td></tr>`;
    }
    // missing — 클릭형 행(확인/철회 토글). ack 여부로 색·칩 전환.
    const ack = r.acknowledged;
    const chip = ack ? `<span class="st ackd">확인됨 · 클릭=철회</span>`
                     : `<span class="st miss">빈 값 · 클릭=확인</span>`;
    return `<tr class="mir-row miss${ack ? " ackd" : ""}" id="${id}" role="button" tabindex="0" ` +
      `data-f="${nm}" aria-pressed="${ack ? "true" : "false"}">` +
      `<td class="mir-f">${nm}</td><td class="mir-v">${val}</td><td class="mir-s">${chip}</td></tr>`;
  }

  /* (열 필터 패널·필터 테이블·칩 줄·스트립·검색 정산은 datazone.js 팩토리로 이동 — PR-2a
     추출. 표면 계약·리뷰 결정 주석은 팩토리가 소유한다. 화면 고유 popover 인 행/그룹 ⋮
     메뉴의 바깥-닫기는 공용 Popover.wireDismiss 주입(wire) — 기제 단일 출처, 상태는
     표면별 인스턴스라 패널 몫과 교차하지 않는다.) */

  /* ---- 게이트 · 재진술 블록(상시, 결정 36 D1-B) — 선택 유래 + 산출 요약 + 이름 목록.
     이미 보이는 것을 재검증하지 않으므로 모달이 아니라 상시 블록이다. 이름 = 실파일명(정준) ·
     식별 요약(보조, PR-1 identity_summary). 소량(≤3)=전부, 대량=층화 표본(결정 5 —
     Python restate.sample, 광의 OR 의 소수 가지가 반드시 등장) + 「외 N건 펼치기」.
     선택 유래(결정 4) = 집합 비교 무상태 판정(restate.origin): 정의-유래면 정의줄을
     재진술하고, 이탈이면 매치/밖 수치를 병기한다(S4 델타). */
  function renderRestate(s) {
    const box = $("jobRestate");
    // 펼침 상태는 작업/데이터 전환에 리셋한다(모듈 전역이 다른 세션으로 새지 않게). 선택 토글은
    // 유지 — 같은 세션 내 편집이므로. 세션 지문(선택 제외)으로 판정.
    const rkey = (s.job_name || "") + "|" + (s.data_source_label || "");
    if (rkey !== lastRestateKey) { restateExpanded = false; lastRestateKey = rkey; }
    const sel = (s.records || []).filter((r) => r.selected);
    // danger 차단(드리프트·미해소 파일명 토큰) 중엔 재진술을 숨긴다 — "생성 불가"인데 "N건 생성"을
    // 동시에 진술하면 모순(confirm-or-alarm, 리뷰). '차단' 판정은 게이트 단일 출처를 소비한다
    // (drift 를 독립 재유도하지 않는다 — 백엔드 RC-23 서열이 danger 를 이미 합성; 토큰 danger 도 포섭).
    const blocked = !!(s.gate && s.gate.level === "danger");
    if (!s.has_data || !sel.length || blocked) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    const rs = s.restate || { origin: null, filter_active: false, sample: [] };
    const byIndex = {};
    sel.forEach((r) => { byIndex[r.index] = r; });
    // 표본 = 층화(Python) — 펼침·소량은 전부.
    const sampleIdx = (sel.length <= 3 || restateExpanded)
      ? sel.map((r) => r.index)
      : (rs.sample || []).filter((i) => byIndex[i]);
    const shown = sampleIdx.map((i) => byIndex[i]).filter(Boolean);
    const list = shown.map((r) =>
      `<span class="nm"><b>${esc(r.name || "(파일명 미정)")}</b>` +
      (r.summary ? ` · ${esc(r.summary)}` : "") + `</span>`).join("");
    const more = (sel.length > 3)
      ? `<button class="btn sm" id="jobRestateMore" data-act="restate-more" data-busy-lock>` +
        (restateExpanded ? "접기" : `⋯ 외 ${sel.length - shown.length}건 펼치기`) + `</button>`
      : "";
    // 선택 유래 문안(결정 4·S4) — 정의-유래 = 정의줄 재진술이 「전체 선택」의 담보.
    // 직접 선택 문안은 가드 모달과 공유 합성기(selectionLine, 리뷰 #9)로 단일 출처.
    const selLine = (rs.origin === "definition")
      ? `정의 매치 전체 ${sel.length}행: ${esc((s.filter && s.filter.definition) || "")}`
      : esc(selectionLine(sel.length, rs.filter_active, rs.in_def, rs.extra));
    box.innerHTML =
      `<span class="dl">선택</span><span>${selLine}</span>` +
      `<span class="dl">생성</span><span>문서 ${sel.length}건 · 저장 폴더: ${esc(s.out_dir || "미지정")}` +
      `<div class="namelist">${list}${more}</div></span>`;
  }

  /* ---- 본문 존: 게이트·저장 폴더·생성 버튼 ---- */
  function gateStep(s, g) {
    // 게이트의 판정(level/enabled/text)은 Python 단일 출처 그대로 두고, 현재 막힌 존의
    // 서수만 표시층에서 결합한다(H-03). danger는 템플릿·매핑 정의, 선택 0은 데이터 존,
    // 나머지 미입력·저장 폴더 사유는 본문 확인 존에서 해소한다.
    if (!g || g.enabled || !g.text) return "";
    if (!s.has_job || s.template_missing || g.level === "danger") return "① ";
    if (!s.has_data || !(s.selected_count > 0)) return "② ";
    return "③ ";
  }

  function renderGateAndFolder(s) {
    $("jobOutDir").value = s.out_dir || "";
    // 저장 폴더 열기/경로 복사 어포던스(#53-B) — 실행 화면에서 승계(리뷰 F3). 생성 후 앱에서
    // 바로 폴더를 열거나 경로를 복사한다(빈 out_dir 이면 PathTrack 이 알아서 아무것도 안 그림).
    const ot = $("jobOutTrack");
    if (ot) ot.innerHTML = PathTrack.affordances(s.out_dir, { only: ["reveal", "copy"] });
    const g = s.gate || { enabled: false, level: "", text: "" };
    $("jobGenBtn").disabled = !g.enabled || generating;
    const gate = $("jobGate");
    gate.textContent = generating ? "" : gateStep(s, g) + g.text;
    gate.className = "muted";
    gate.style.color = g.level === "danger" ? "var(--a-danger)"
      : g.level === "warn" ? "var(--a-warn)" : "";
  }

  function renderStatus(s) {
    const pill = $("jobStatus");
    if (!s.has_job) { pill.dataset.level = "idle"; pill.textContent = "작업 선택"; return; }
    if (!s.has_data) { pill.dataset.level = "idle"; pill.textContent = "데이터 선택"; return; }
    if (s.gate && s.gate.enabled) { pill.dataset.level = "ok"; pill.textContent = "생성 준비"; }
    else { pill.dataset.level = "warn"; pill.textContent = "확인 필요"; }
  }

  /* 진행 델타 — 진행바만 갱신(전체 재렌더 없음). */
  function renderProgress(p) {
    const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
    $("jobGenBar").style.width = pct + "%";
    const r = $("jobGenResult");
    r.className = "run-result";
    r.textContent = `생성 중… ${p.done}/${p.total}`;
  }

  /* ---- 로그(완료 존, 세션 스코프) ---- */
  let logStarted = false;
  function log(msg) {
    const box = $("jobGenLog");
    const ts = new Date().toLocaleTimeString("ko-KR", { hour12: false });
    if (!logStarted) { box.textContent = ""; logStarted = true; }
    box.textContent += (box.textContent ? "\n" : "") + `[${ts}] ${msg}`;
    box.scrollTop = box.scrollHeight;
  }

  /* ---- busy 잠금 — [data-busy-lock] 속성 선언(setBusy 누락 회귀 방지, #26) ---- */
  function setBusy(busy) {
    $("scr-job").querySelectorAll("[data-busy-lock]").forEach((el) => { el.disabled = busy; });
    $("jobGenBtn").disabled = busy || !(LAST && LAST.gate && LAST.gate.enabled);
    $("jobGenBtn").textContent = busy ? "생성 중…" : "이 작업으로 문서 생성";
    $("jobGenCancel").style.display = busy ? "" : "none";
    if (!busy) { $("jobGenCancel").disabled = false; $("jobGenCancel").textContent = "다음 건부터 중단"; }
  }

  /* ---- 덮어쓰기 확인 본문 = 수치 합성(A-2-22, 결정 36) — 총량·파괴분·신규분을 종류별로
     재진술한다(블록 4 가드 형식 승계). 별도 재진술 모달을 만들지 않고, 어차피 떠야 하는 RC-02
     덮어쓰기 모달이 수치를 나른다. 공용 modal.js Modal.confirm의 기본 포커스=머무르기·Escape=
     머무르기)이 담당한다 — 새 표면은 처음부터 #86 재유입 가드에 부합(window.confirm 무사용). */
  function overwriteBody(res) {
    const names = res.conflict_names || [];
    const more = res.conflict_more ? `\n외 ${res.conflict_more}개` : "";
    return `${res.total}건을 생성합니다. 이 중 ${res.overwrite_count}건이 기존 파일을 덮어씁니다:\n` +
      `${names.join("\n")}${more}\n\n나머지 ${res.new_count}건은 새 파일입니다.`;
  }

  async function doGenerate(confirmOverwriteFlag) {
    generating = true; setBusy(true);
    if (!confirmOverwriteFlag) { $("jobGenBar").style.width = "0%"; log("생성 요청"); }
    // busy-lock 은 덮어쓰기 모달 종료까지 유지한다 — finally 를 needs_overwrite 흐름 뒤에 두어,
    // 모달이 열린 동안 생성 버튼이 재활성돼 두 번째 생성이 첫 확인 미결인 채 시작되는 재진입
    // 경합을 막는다(리뷰 #1: modal.js 는 blocking window.confirm 과 달리 포커스 트랩이 없어
    // 백드롭 뒤 살아있는 버튼에 Tab+Enter 가 닿는다 — run.js 엔 없던 창).
    try {
      const res = await Bridge.generate(SCREEN, confirmOverwriteFlag);
      if (res.ok) { renderResult(res); return; }
      if (res.needs_overwrite) {
        // 조용한 덮어쓰기 금지 — 수치 재진술 후 확인 시에만 재호출(RC-02). 모달 대기 동안 busy 유지.
        const ok = await window.Modal.confirm({
          title: "덮어쓰기 확인", body: overwriteBody(res),
          confirmLabel: "덮어쓰고 생성", cancelLabel: "취소", danger: true,
        });
        if (ok) { await doGenerate(true); }
        else { log("생성을 취소했습니다."); }
        return;
      }
      warnResult(res.error || "생성할 수 없습니다.", res.level);
    } finally {
      generating = false; setBusy(false);
    }
  }

  function renderResult(res) {
    const total = Number(res.total) || 0;
    const attempted = Number(res.attempted) || 0;
    const percent = res.cancelled && total > 0
      ? Math.max(0, Math.min(100, Math.round(attempted / total * 100)))
      : 100;
    $("jobGenBar").style.width = percent + "%";
    const r = $("jobGenResult");
    r.textContent = res.summary;
    r.className = "run-result " +
      (res.level === "ok" ? "ok" : (res.level === "warn" ? "warn" : "danger"));
    log(res.summary);
    (res.failures || []).forEach((f) => log("  [실패] " + f));
    // 채움 완화 사실(#154) — 문안은 Python(describe_fill_note)이 확정, JS 는 표기만.
    (res.fill_notes || []).forEach((n) => log("  [주의] " + n));
    log(`저장 폴더: ${res.out_dir}`);
  }

  function warnResult(msg, level) {
    const r = $("jobGenResult");
    r.textContent = "확인 필요: " + msg;
    r.className = "run-result " + (level === "danger" ? "danger" : "warn");
    log(msg);
  }

  /* ---- 웹→Python 이벤트 ---- */
  /* ---- 세션 가드(블록 4, 결정 26·27) — 파괴 전이의 수치 재진술 본문 합성 ----
     술어·수치는 Python(_guard_state)이 판정하고, 여기는 문안만 입힌다. verbPhrase 로
     전이 종류(T1 작업 전환 / 데이터 재겨눔 / 템플릿 재연결)를 구분 — 무엇이 사라지는지 명시. */

  /* 선택 재진술 한 줄 — 재진술 블록(renderRestate)과 가드 모달(guardBody)의 **공유
     합성기**(리뷰 #9): 같은 수치를 두 곳이 따로 조립하면 문안이 갈라져 모달이 화면
     재진술과 모순되는 드리프트 클래스가 생긴다. 이제 그 공유 범위가 화면 밖으로도
     넓어졌다 — txt T3 가드와 같은 조각을 쓴다(guard.js, PR-4 리뷰 F6). */
  const selectionLine = window.Guard.selectionLine;

  function guardBody(g, verbPhrase) {
    const lost = [selectionLine(g.sel_count, g.filter_active, g.in_def, g.extra)];
    if (g.filter_parts > 0) lost.push(`필터 정의(${g.filter_parts}개 조건)`);
    return `${verbPhrase} 이 세션의 선택이 사라집니다.\n` +
      `사라지는 것: ${lost.join(" · ")}.`;
  }

  /* 파괴 전이 사전 확인(데이터 재겨눔·템플릿 재연결 — T1 동류 세션 재구성). 피커/흐름을
     열기 **전에** 묻는다(파일까지 고른 뒤 "머무르기"는 고른 노동을 또 버리게 한다).
     무장 판정은 guard_state **실시간 질의**(리뷰 #4: 스냅샷 캐시는 generate 무푸시
     경로·왕복 지연에서 stale — 완주 직후 거짓 모달·무장 직후 무확인 통과 양방향 오판).
     true=진행, false=머무르기. */
  async function confirmDestructiveIfArmed(title, verbPhrase, confirmLabel) {
    const g = await Bridge.call(SCREEN, "guard_state", {});
    if (!g || !g.armed) return true;
    return window.Modal.confirm({
      title, body: guardBody(g, verbPhrase),
      confirmLabel, cancelLabel: "취소",
    });
  }

  function confirmDataSwapIfArmed() {
    return confirmDestructiveIfArmed(
      "데이터 변경 확인", "데이터를 바꾸면", "데이터 바꾸고 버리기");
  }

  /* T1 가드 왕복(RC-02 동형): 무변이 needs_confirm → modal.js 이진 확인(기본 포커스=
     머무르기·Escape=머무르기) → 확인 시에만 confirm=true 재호출. 단일 실행(switching)
     — 더블클릭이 두 왕복·두 모달을 만들면 modal.js 재진입 가드가 loud 거절을 띄운다
     (리뷰 #5: 정상 제스처에 오류성 경보). */
  let switching = false;
  async function selectJobGuarded(name) {
    /* 반환 = 전환 성사 여부(false=머무르기/재진입 거절) — 편집 모드 이탈이 이 판정을
       기다린다(가드 선행·전환 후행, PR-2 리뷰 F5: 취소는 무변화여야 한다). */
    if (switching) return false;
    switching = true;
    try {
      const res = await Bridge.call(SCREEN, "select_job", { name });
      if (res && res.needs_confirm) {
        const ok = await window.Modal.confirm({
          title: "작업 전환 확인",
          body: guardBody(res, "작업을 전환하면"),
          confirmLabel: "전환하고 버리기", cancelLabel: "취소",
        });
        if (!ok) return false;
        await Bridge.call(SCREEN, "select_job", { name, confirm: true });
      }
      return true;
    } finally {
      switching = false;
    }
  }

  function setJobOpening(item, opening) {
    if (!item) return;
    if (opening) {
      if (!item.dataset.idleLabel) item.dataset.idleLabel = item.textContent;
      item.setAttribute("aria-busy", "true");
      item.textContent = `${item.dataset.idleLabel} · 여는 중…`;
      return;
    }
    item.removeAttribute("aria-busy");
    if (item.dataset.idleLabel) {
      item.textContent = item.dataset.idleLabel;
      delete item.dataset.idleLabel;
    }
  }

  async function selectJobFromItem(item) {
    // 검색 디바운스 정산·Python 로드보다 먼저 표지를 세운다. 정본 판정은 select_job push가 덮는다.
    setJobOpening(item, true);
    try {
      await dz.flushPendingSearch();
      return await selectJobGuarded(item.dataset.job);
    } finally {
      if (item.isConnected) setJobOpening(item, false);
    }
  }

  function onMasterClick(e) {
    // 관리 어포던스(⋮·그룹 헤더)가 행 진입 동사보다 먼저 — 행 클릭=실행(주동사)과 분리.
    const more = e.target.closest(".job-more[data-more]");
    if (more) { toggleRowMenu("job", more.dataset.more, more); return; }
    const gmore = e.target.closest(".grp-more[data-grp-more]");
    if (gmore) { toggleRowMenu("group", gmore.dataset.grpMore, gmore); return; }
    const grp = e.target.closest(".job-grp-head[data-grp-toggle]");
    if (grp) {
      // 접힘 토글은 보기만 바꾼다 — 선택·세션 무영향(결정 6-⑤). ""=「그룹 없음」.
      GroupList.toggleGroup(
        grp,
        () => Bridge.call(SCREEN, "toggle_group", { group: grp.getAttribute("data-grp-toggle") }),
        "작업 그룹 접힘 상태를 저장하지 못했습니다."
      );
      return;
    }
    const item = e.target.closest(".job-item[data-job]");
    if (!item) return;
    const already = item.getAttribute("aria-current") === "true";
    // 편집 중 행 클릭 = 실행 복귀(결정 40 — 복귀 어포던스는 좌 목록이 담당). **가드 선행·
    // 전환 후행**(PR-2 리뷰 F5): T1 확인이 끝나기 전엔 편집 표면을 걷지 않는다 —
    // 「머무르기」=무변화(취소가 편집 화면을 잃게 하면 안 된다). 선택을 먼저 성사시키는
    // 구조라 지연 선택이 뒤늦게 클릭을 추월하는 창도 없다(리뷰 F8). 같은 작업 재클릭이면
    // 진행 중 세션을 그대로 다시 노출한다(재구성 없음 — 아래 무동작 가드와 동근).
    if (MODE === "edit") {
      (async () => {
        if (!already) {
          if ((await selectJobFromItem(item)) === false) return;  // 머무르기
        }
        if (await exitEditToRun()) showExitNote();  // T2 고지(미저장 편집 있을 때만)
      })().catch((err) => {
        log("작업 열기 실패: " + String((err && err.message) || err));
      });
      return;
    }
    // 이미 선택된 작업 재클릭 = 무동작(세션 재구성으로 데이터 겨눔이 날아가지 않게).
    if (already) return;
    // 미적용 검색어는 전환 시도 전에 정산(적용) — 취소만 하면 「머무르기」 세션에서
    // 마지막 타이핑이 증발한다(리뷰 #2). 새 세션 오발도 함께 차단(PR-2b 리뷰 #1).
    selectJobFromItem(item).catch((err) => {
      log("작업 열기 실패: " + String((err && err.message) || err));
    });
  }

  /* ---- 좌 목록 관리(결정 43) — ⋮ 메뉴·인라인 이름 변경·그룹 이동/관리 ----
     파괴·병합 판정과 수치는 Python(_do_delete_job 등 needs_confirm 왕복)이 내리고,
     여기는 문안을 입혀 modal.js 로 재진술한다(네이티브 다이얼로그 금지 #86). */
  let menuFor = null;  // {kind:"job"|"group", name, trigger} — 열린 ⋮ 메뉴의 대상과 복귀점

  function closeRowMenu() {
    menuFor = null;
    rowMenu.hide();
  }

  function toggleRowMenu(kind, name, btn) {
    if (menuFor && menuFor.kind === kind && menuFor.name === name) { closeRowMenu(); return; }
    openRowMenu(kind, name, btn);
  }

  function openRowMenu(kind, name, btn) {
    menuFor = { kind, name, trigger: btn };
    // 메뉴 내용은 화면 소유(작업=편집/복제/이름/이동/삭제, 그룹=이름변경/해산), 위치·표시는 팩토리.
    const html = kind === "job"
      ? `<button data-menu="edit">편집</button>` +
        `<button data-menu="clone">복제</button>` +
        `<button data-menu="rename">이름 변경</button>` +
        `<div class="sep"></div>` +
        `<button data-menu="move">그룹으로 이동…</button>` +
        `<div class="sep"></div>` +
        `<button data-menu="delete" class="danger">삭제</button>`
      : `<button data-menu="grp-rename">그룹 이름 변경</button>` +
        `<button data-menu="grp-disband">그룹 해산</button>`;
    rowMenu.show(html, btn);
  }

  async function onRowMenuClick(e) {
    const b = e.target.closest("button[data-menu]");
    if (!b || !menuFor) return;
    const act = b.dataset.menu;
    const { kind, name, trigger } = menuFor;
    closeRowMenu();
    if (kind === "job") {
      if (act === "edit") { EditorEntry.openGuarded(name); return; }  // PR-5 에서 패널 편집 모드로 repoint
      if (act === "clone") {
        const r = await Bridge.call(SCREEN, "clone_job", { name });
        if (r && r.name) log(`복제: '${name}' → '${r.name}'`);
        return;
      }
      if (act === "rename") { startRename(name); return; }
      if (act === "move") { openGroupMove(name, trigger); return; }
      if (act === "delete") { deleteJob(name, trigger); return; }
    }
    if (act === "grp-rename") { renameGroup(name, trigger); return; }
    if (act === "grp-disband") { disbandGroup(name, trigger); }
  }

  /* 인라인 이름 변경 — 행이 입력칸으로 바뀐다(결정 43). Enter=확정·Escape=취소·포커스
     이탈=확정 시도. 확정 실패(선점·빈 이름)는 loud 재진술 후 Enter 경로만 편집을 복원한다
     (이탈 경로 복원은 사용자가 이미 다른 곳을 겨눈 포커스를 빼앗는다). */
  function startRename(name) {
    RENAMING = { name, value: name };
    if (LAST) renderMaster(LAST);
    const inp = $("jobRenameInput");
    if (inp) { inp.focus(); inp.select(); }
  }

  async function commitRename(restoreOnError) {
    const inp = $("jobRenameInput");
    if (!inp || !RENAMING) return;
    const orig = RENAMING.name;
    const typed = inp.value;
    RENAMING = null;  // 디스패치의 push 재렌더가 입력칸을 되살리지 않게 먼저 걷는다
    if (typed.trim() === orig) { if (LAST) renderMaster(LAST); return; }  // 무변경 = 조용히 복귀
    const r = await Bridge.call(SCREEN, "rename_job", { name: orig, new: typed });
    if (r && r.ok) { log(`이름 변경: '${orig}' → '${typed.trim()}'`); return; }
    const error = (r && r.error) || "알 수 없는 오류";
    log("이름 변경 실패: " + error);
    RENAMING = { name: orig, value: typed, error };
    if (LAST) renderMaster(LAST);
    if (restoreOnError) {
      const again = $("jobRenameInput");
      if (again) { again.focus(); again.select(); }
    }
  }

  function cancelRename() {
    RENAMING = null;
    if (LAST) renderMaster(LAST);
  }

  function onMasterKeydown(e) {
    if (e.target.id !== "jobRenameInput") return;
    // 한글 IME 조합 확정 Enter 는 제출이 아니다(modal.js 관례 승계).
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter") { e.preventDefault(); commitRename(true); }
    if (e.key === "Escape") { e.preventDefault(); cancelRename(); }
  }

  function onMasterFocusOut(e) {
    if (e.target.id === "jobRenameInput" && RENAMING) commitRename(false);
  }

  /* 그룹 이동 다이얼로그(결정 43) — 조립·확정은 공용 moveDialog 팩토리, 여기는 현 그룹 조회와
     확정 디스패치(set_group)·로그만 주입한다. 새 그룹 data-new·빈 이름 재진술은 팩토리 소유. */
  function currentGroupOf(name) {
    const sections = (LAST && LAST.job_sections) || [];
    for (const sec of sections) {
      if (sec.rows.some((r) => r.name === name)) return sec.group;
    }
    return "";
  }

  function openGroupMove(name, returnFocus) {
    moveDialog.open({
      nameText: `작업 '${name}' 을(를) 옮길 그룹을 고르세요.`,
      groups: (LAST && LAST.job_group_names) || [],
      current: currentGroupOf(name),
      returnFocus,
      onConfirm: async (group) => {
        await Bridge.call(SCREEN, "set_group", { name, group });
        log(group ? `그룹 이동: '${name}' → '${group}'` : `그룹 해제: '${name}'`);
      },
    });
  }

  async function deleteJob(name, returnFocus) {
    const res = await Bridge.call(SCREEN, "delete_job", { name });
    if (res && res.undo) {
      showDeleteUndo(name, res);
      return;
    }
    if (!(res && res.needs_confirm)) return;
    let body = `작업 '${name}' 을(를) 삭제합니다. 템플릿 연결과 매핑 정의가 함께 사라집니다.`;
    if (res.open_session) {
      body += `\n지금 열려 있는 세션도 닫힙니다.`;
      if (res.armed) {
        body += ` 사라지는 것: ` +
          `${selectionLine(res.sel_count, res.filter_active, res.in_def, res.extra)}.`;
      }
    }
    const ok = await window.Modal.confirm({
      title: "작업 삭제 확인", body,
      confirmLabel: "휴지통으로 이동", cancelLabel: "취소",
      returnFocus,
    });
    if (!ok) return;
    const deleted = await Bridge.call(SCREEN, "delete_job", { name, confirm: true });
    log(`작업을 휴지통으로 이동: '${name}'`);
    showDeleteUndo(name, deleted);
  }

  function showDeleteUndo(name, deleted) {
    if (deleted && deleted.undo) window.UndoToast.show(`작업 '${name}' 을(를) 휴지통으로 옮겼습니다.`, async () => {
      const restored = await Bridge.call(SCREEN, "undo_delete_job", {});
      if (restored && restored.ok === false) throw new Error(restored.error);
    });
  }

  async function renameGroup(old, returnFocus) {
    const val = await window.Modal.prompt({
      title: "그룹 이름 변경", body: `그룹 '${old}' 의 새 이름을 넣으세요.`, value: old,
      returnFocus,
    });
    if (val === null) return;
    const r = await Bridge.call(SCREEN, "rename_group", { name: old, new: val });
    if (r && r.needs_confirm) {
      // 기존 그룹으로의 개명 = 병합 — 수치 재진술 후 확정(조용한 병합 금지). 수치는 '지금
      // 기준' 관측으로 적는다(#149): 확인 왕복 사이 다른 표면이 소속을 옮길 수 있어 약속으로
      // 읽히면 안 되고, 옮겨지는 집합의 규칙('전부')이 실제로 참인 진술이다.
      const ok = await window.Modal.confirm({
        title: "그룹 병합 확인",
        body: `'${r.new}' 그룹이 이미 있습니다. '${old}' 의 작업 전부(지금 기준 ${r.count}개)를 ` +
          `'${r.new}'(현재 ${r.target_count}개)에 합칩니다.`,
        confirmLabel: "합치기", cancelLabel: "취소",
        returnFocus,
      });
      if (!ok) return;
      const r2 = await Bridge.call(SCREEN, "rename_group",
        { name: old, new: val, confirm: true, seen: r.count });
      if (r2 && r2.ok) {
        log(`그룹 병합: '${old}' → '${val.trim()}' (작업 ${r2.count}개 이동)${r2.drift_note || ""}`);
      }
      return;
    }
    if (r && r.ok) {
      if (r.count) log(`그룹 이름 변경: '${old}' → '${val.trim()}'`);
    } else if (r) {
      log("그룹 이름 변경 실패: " + r.error);
    }
  }

  async function disbandGroup(name, returnFocus) {
    const res = await Bridge.call(SCREEN, "disband_group", { name });
    if (!(res && res.needs_confirm)) return;
    // 이동 집합은 '해산 시점의 소속 전부' 라는 규칙으로 적고, 수치는 지금 기준 관측으로
    // 덧붙인다(#149) — 확인 왕복 사이 소속이 바뀌어도 규칙 쪽은 언제나 참이다.
    const ok = await window.Modal.confirm({
      title: "그룹 해산 확인",
      body: `그룹 '${name}' 을(를) 해산합니다. 해산 시점의 소속 작업 전부(지금 기준 ${res.count}개)가 ` +
        `'그룹 없음'으로 이동합니다.`,
      confirmLabel: "해산", cancelLabel: "취소",
      returnFocus,
    });
    if (!ok) return;
    const r = await Bridge.call(SCREEN, "disband_group", { name, confirm: true, seen: res.count });
    if (r && r.ok) log(`그룹 해산: '${name}' (작업 ${r.count}개 이동)${r.drift_note || ""}`);
  }

  /* 허브(홈)에서 이 작업을 열기 — 좌 목록 재클릭 무동작 가드(onMasterClick)와 동형.
     이미 이 작업 세션이면 재구성하지 않고(진행 중 데이터 겨눔·행 선택·확인이 조용히 소실되지
     않게 — 리뷰 F1) 그대로 두고 화면만 전환한다. 아니면 겨눠 진입한다. */
  function openJob(name) {
    // 허브발 실행 진입도 행 클릭과 동형 — 가드 선행·전환 후행(리뷰 F5), 미저장 편집은 고지.
    if (MODE === "edit") {
      (async () => {
        if (!(LAST && LAST.job_name === name)) {
          await dz.flushPendingSearch();
          if ((await selectJobGuarded(name)) === false) {
            window.Nav.go(SCREEN);  // 머무르기 — 편집 표면 유지한 채 화면만 노출
            return;
          }
        }
        if (await exitEditToRun()) showExitNote();
        window.Nav.go(SCREEN);
      })();
      return;
    }
    if (!(LAST && LAST.job_name === name)) {
      // 미적용 검색 정산 후 T1 가드 승계 — 허브 진입도 같은 파괴 전이(결정 26).
      dz.flushPendingSearch().then(() => selectJobGuarded(name));
    }
    window.Nav.go(SCREEN);
  }

  /* 거울 미입력 행 = ADR-E 배지 — 클릭=확인·재클릭=철회(UD-19). ackd 클래스로 토글 방향 판정. */
  function mirrorAck(rowEl) {
    const act = rowEl.classList.contains("ackd") ? "unack_field" : "ack_field";
    Bridge.call(SCREEN, act, { field: rowEl.dataset.f });
  }

  function onMirrorClick(e) {
    // 두 danger 배너의 행동 링크(#128) — 목적지는 같은 편집 모드다(매핑도 파일명 패턴도 거기
    // 산다). 진입 흐름을 공유하되 라벨은 각자 고칠 것을 말한다.
    if (e.target.closest('[data-act="fix-mapping"],[data-act="fix-filename"]')) {
      openEditForRepair();
      return;
    }
    const row = e.target.closest(".mir-row.miss");
    if (row) mirrorAck(row);
  }

  function onMirrorKey(e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    const row = e.target.closest(".mir-row.miss");
    if (!row) return;
    e.preventDefault();
    mirrorAck(row);
  }

  /* danger(구조 드리프트) 수리 동선 — 이 작업을 **패널 편집 모드**에 열어 매핑을 재확정한다
     (공용 EditorEntry.openGuarded: 미저장 정의 확인 후 모드 전환 — 에디터 흡수로 화면 이동이
     아니라 제자리 모드 전환이 됐다). 확정·저장 후 좌 목록 행 클릭으로 세션 재개. */
  function openEditForRepair() {
    // #99-6 동형 방어(PR-5 리뷰 F4) — 셔틀 미로드의 동기 ReferenceError 는 조용한 무반응.
    if (!window.EditorEntry) { window.alert("편집 진입 구성 요소(EditorEntry)가 로드되지 않았습니다."); return; }
    if (LAST && LAST.job_name) EditorEntry.openGuarded(LAST.job_name);
  }

  /* 템플릿 다시 연결(#67) — 공용 흐름(relink.js)에 위임, 결과 재진술 채널만 log 주입.
     재연결 확정은 기선택 작업을 재적재해 세션(선택·필터·겨눔)을 재구성한다 — T1 동류
     파괴 전이이므로 무장 시 먼저 확인한다(리뷰 #0: 재연결 확인문은 템플릿 경로만
     재진술해 선택 소실이 조용히 지나갔다). */
  async function doRelinkTemplate() {
    if (!(LAST && LAST.job_name)) return;
    const ok = await confirmDestructiveIfArmed(
      "템플릿 다시 연결 확인", "템플릿을 다시 연결하면", "다시 연결하고 버리기");
    if (!ok) return;
    Relink.relinkTemplate(SCREEN, LAST.job_name, (msg) => log(msg));
  }

  function startNewJob() {
    if (!window.EditorEntry) {
      window.alert("편집 진입 구성 요소(EditorEntry)가 로드되지 않았습니다.");
      return;
    }
    EditorEntry.newDraft();
  }

  function wire() {
    $("jobListHwpx").addEventListener("click", onMasterClick);
    $("jobListHwpx").addEventListener("keydown", onMasterKeydown);
    $("jobListHwpx").addEventListener("focusout", onMasterFocusOut);
    $("jobRowMenu").addEventListener("click", onRowMenuClick);
    // ⋮ 메뉴 바깥 클릭 닫기+클릭 1회 소비·Escape — 기제는 공용 Popover.wireDismiss(단일
    // 출처), 여기는 메뉴 술어만 주입한다(패널 몫은 팩토리가 자기 인스턴스로 주입).
    Popover.wireDismiss({
      isOpen: () => menuFor !== null,
      contains: (t) => !!(t.closest("#jobRowMenu") || t.closest(".job-more")),
      close: closeRowMenu,
    });
    moveDialog.wire("grpMoveOk", "grpMoveCancel");
    // 데이터 존(테이블·열 패널·칩·스트립·전체 선택/해제·문서 레벨 닫기)은 팩토리 몫 배선.
    dz.wire();
    if (window.ResizeObserver && !mirrorResizeObserver) {
      mirrorResizeObserver = new ResizeObserver(measureMirrorCap);
      mirrorResizeObserver.observe($("jobMirror"));
    }
    $("jobDataExpand").addEventListener("click", openJobDataSheet);
    $("jobMirrorExpand").addEventListener("click", openJobConfirmSheet);
    $("jobMirrorCapstrip").addEventListener("click", (e) => {
      if (e.target.closest("[data-mirror-expand]")) openJobConfirmSheet(e);
    });
    $("jobConfirmSheetClose").addEventListener("click", () =>
      window.SurfaceSheet.close("jobConfirmSheet"));
    $("dataSheetClose").addEventListener("click", () => window.SurfaceSheet.close("dataSheet"));
    // T2 복귀 고지 — 확인=걷기, 돌아가기=비파괴 편집 재진입(세션 무접촉 — 리뷰 F1/F4).
    $("jobEditExitNote").addEventListener("click", (e) => {
      if (e.target.closest('[data-act="return-to-edit"]')) { showEditMode(); return; }
      if (e.target.closest('[data-act="dismiss-exit-note"]')) {
        $("jobEditExitNote").style.display = "none";
      }
    });
    $("jobEditResume").addEventListener("click", showEditMode);
    // 구획 ＋ 새 작업(1부 결정 10 — 레일 항목 사망의 생성 진입 승계, 리뷰 F2). 흐름은
    // EditorEntry.newDraft 단일 출처(홈 ＋ 와 공유 — 폐기 확인·착지 드리프트 금지).
    $("jobNewBtn").addEventListener("click", startNewJob);
    $("jobEmptyNewBtn").addEventListener("click", startNewJob);
    // 재렌더에도 살아남게 안정 컨테이너에 위임(#67).
    $("jobRelink").addEventListener("click", (e) => {
      if (e.target.closest('[data-act="relink-template"]')) doRelinkTemplate();
    });
    // 거울(재렌더에도 살아남게 안정 컨테이너에 위임) — 미입력 행 ack + 드리프트 수리 링크.
    $("jobMirror").addEventListener("click", onMirrorClick);
    $("jobMirror").addEventListener("keydown", onMirrorKey);
    // 재진술 블록 이름 목록 펼침/접기(대량 표본).
    $("jobRestate").addEventListener("click", (e) => {
      if (e.target.closest('[data-act="restate-more"]')) {
        restateExpanded = !restateExpanded;
        // Preserve.around 로 감싼다 — 토글 버튼(id=jobRestateMore)이 innerHTML 재구성을
        // 가로질러 포커스를 유지하게(거울-행 ack 경로와 같은 규율, 리뷰). 밖에서 부르면 body 낙하.
        if (LAST) Preserve.around(() => renderRestate(LAST));
      }
    });
    $("jobGenBtn").addEventListener("click", () => doGenerate(false));
    $("jobGenCancel").addEventListener("click", async () => {
      const btn = $("jobGenCancel");
      btn.disabled = true;
      btn.textContent = "중단 요청됨…";
      await Bridge.call(SCREEN, "cancel_generation", {});
      log("중단 요청: 진행 중인 문서를 마친 뒤 미착수 건을 중단합니다.");
    });

    $("jobBtnPickData").addEventListener("click", async () => {
      if (!(await confirmDataSwapIfArmed())) return;  // 데이터 재겨눔 = T1 동류 파괴 전이
      let r = await Bridge.pickDataFile(SCREEN);
      if (r && typeof r === "object" && r.needs_sheet) {   // 다중 시트 → 확정 게이트(#33)
        r = await SheetPicker.choose(SCREEN, r);
        if (r === null) { log("데이터 선택을 취소했습니다."); return; }
      }
      if (r === null) return;                       // 취소
      if (typeof r === "string" && r.startsWith("ERROR:")) { log("데이터 오류: " + r.slice(6).trim()); return; }
      log(`데이터 불러옴: ${r}`);
    });
    // 등록 데이터(풀) 겨눔(#26 #6) — 취소=중단, 실패는 모달 안에서 재진술(PoolPicker).
    $("jobBtnPoolData").addEventListener("click", async () => {
      if (!(await confirmDataSwapIfArmed())) return;  // 데이터 재겨눔 = T1 동류 파괴 전이
      const label = await PoolPicker.choose(SCREEN);
      if (label === null) return;                   // 취소 = 겨눔 중단
      log(`등록 데이터 불러옴: ${label}`);
    });
    $("jobBtnPickFolder").addEventListener("click", async () => {
      const r = await Bridge.pickOutputFolder(SCREEN);
      if (r === null) return;                       // 취소
      if (typeof r === "string" && r.startsWith("ERROR:")) { log("폴더 오류: " + r.slice(6).trim()); return; }
      log(`저장 폴더: ${r}`);
    });
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    render(await Bridge.initial(SCREEN));
  }

  // overwriteBody·guardBody 는 순수 합성기 — 실앱 게이트가 합성 결과(수치·문안 배치)를
  // 되읽어 회귀를 막는다(파괴적 확인의 조용한 드리프트 금지 — RC-02 판과 가드 판 동형).
  // confirmDataSwapIfArmed 는 배선 존재 핀(리뷰 #6 — JS 전용 가드 지점이라 삭제 회귀를
  // 실앱 게이트가 잡을 표식이 없었다).
  // showEditMode/refreshList 는 편집 모드 seam(EditorEntry·editor.js doSave 가 소비).
  window.JobScreen = {
    init, overwriteBody, guardBody, confirmDataSwapIfArmed, openJob,
    showEditMode, showRunMode, refreshList, openJobConfirmSheet, openJobDataSheet,
  };
})();
