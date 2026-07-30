/* 「문서 만들기」 화면 — 세션 패널 하나(R-flow #90 · 재작성 R1·F7).
   세션 패널 = v6 `screen-data` 2열(좌 `.dg-main` 현재 데이터·거울·결과 / 우 `.dg-side`
   문서 선택기·생성 준비 — 구 「선택한 작업」 존은 U2 §4 판정 A 로 사망, 활성 카드와
   액션바 이름이 승계. 구 4존 znum 은 이 형상으로 대체),
   정의 편집은 자기 화면(#scr-editor, 재작성 F7)으로 나갔다 — 이 화면은 실행 세션 하나다.
   좌 master 작업 목록은 F2 PR-B 에서 사망했다(지도 §10.9): 작업 선택은 데이터가 준비된 뒤
   후보 side-card·문서 탐색 면이 지고, 목록 관리 6동사와 데이터 없는 상태의 작업 찾기는
   「문서 작업」 라이브러리가 승계했다.
   안정 DOM(index.html) + Python 이 window.__push('job', snapshot) 로 값만 채운다(run/txt 패턴).
   표현 계층(거울 테이블·재진술 블록·게이트·진행/로그)만 여기서 만든다 — VM 로직 아님(링2 대체, #87).
   덮어쓰기 확인은 공용 Modal.confirm의 수치 합성 본문으로 — 네이티브 다이얼로그 무사용이라 #86
   재유입 가드에 처음부터 부합한다. 존 배치(헤더·데이터·본문·완료)는 여기서 안정 DOM 에 값을 채운다. */
(function () {
  const SCREEN = "job";
  const $ = (id) => document.getElementById(id);
  let LAST = null;
  let generating = false;
  let lastSessionKey = null;  // 완료 존 세션 스코프 판정(결정 7) — 성분별 지문(U2 §2.18)
  let restateExpanded = false;  // 재진술 블록 이름 목록 펼침(대량 표본+「외 N건」, 결정 36)
  let lastRestateKey = null;    // 펼침 리셋 판정 — 작업/데이터 전환 시 펼침을 끈다(세션 누수 방지)
  let mirrorRowCount = 0;       // 420px 실측 캡의 현재 필드 수(#272)
  let mirrorResizeObserver = null;
  /* 패널 모드(결정 39·40)는 편집기가 몰입 표면이 되며 사망했다(재작성 F7 판정 N):
     정의 편집은 자기 화면(#scr-editor)에 살고, 이 화면은 실행 세션 하나만 그린다.
     「이 화면이 안 보인다」는 판정은 이제 `.scr.on` 하나로 충분하다. */

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)
  const ZONE_CHAIN = "job:zone";  // 데이터 존 + 범위 초안 출구의 공통 발신 체인
  let pendingZoneMutations = 0;   // 발신했지만 아직 결과가 안 온 존 변이 수(이탈 가드 소재)

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
    // 존 발신 직렬화 키(리뷰 2R) — 이 존의 13액션과 범위 초안의 적용·취소가 **한 체인**을
    // 쓴다. 같은 범위 상태 하나를 바꾸는 발신들이라 도착 순서가 뒤바뀌면 취소한 편집이
    // 커밋된 범위에 착지한다.
    chainKey: ZONE_CHAIN,
    // 대상 세계 세대(리뷰 4R) — 웹은 판정하지 않고 **보고 있던 세계**를 나른다.
    epoch: () => (LAST ? LAST.zone_epoch : undefined),
    // 아직 푸시가 안 온 편집 수 — 이탈 가드가 `dirty` 만 보면 방금 친 편집을 못 본다.
    onMutation: (delta) => { pendingZoneMutations += delta; },
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

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    if (s && s.progress) { renderProgress(s.progress); return; }  // 진행 델타(경량)
    Preserve.around(() => {  // 매핑/레코드 포커스·스크롤 보존(#28)
      LAST = s;
      dz.sync(s);  // 존 렌더는 아래 hasJob 게이트를 타지만 스냅샷 관측은 무조건 — 팩토리
                   // flushPendingSearch 의 stale LAST 오발 차단(리뷰: master 계약 복원)
      const hasJob = !!s.has_job;
      syncModeDisplay(hasJob);
      // 데이터-우선(§18.2): 세션 4존은 작업 미선택에도 산다 — 스냅샷이 vm-None 상태를
      // 전 키 유효값으로 방출하므로(prework 게이트·빈 거울·후보) 렌더러는 무조건 돈다.
      renderActiveIdentity(s);
      renderData(s);
      renderPreflight(s);
      renderMirror(s);
      dz.render(s);  // 데이터 존(테이블·칩·스트립) — 팩토리 소유(datazone.js)
      renderRangeFoot(s);
      renderPreview(s);
      renderCandidates(s);
      renderBrowse(s);   // 탐색 면은 열려 있지 않아도 그린다(열 때 이미 최신)
      renderRestate(s);
      renderGateAndFolder(s);
      renderStatus(s);
      // 완료 존(생성 결과·로그)은 세션 스코프로 보존한다(결정 7) — 매 push 가 아니라 세션이
      // 실제로 바뀔 때만 무효화한다. 탭 이탈 후 복귀(REFRESH_ON_NAV 재push)는 세션 불변이라
      // 결과가 살아남고(리뷰 #3: 결정 7 위배 봉합), 작업·데이터·선택 변경(#28 UD-10)에서만
      // 이전 결과를 지운다. nav 는 CSS 토글이라 DOM 은 어차피 살아있다.
      // 처분은 성분별 2분기다(U2 §2.18) — 판정 G(강등)는 선택 축의 자기모순을 막는
      // 논거였는데 5성분 전부를 덮은 과적용이었다. 작업 전환·데이터 교체는 링1 이 이미
      // 증거를 죽였으므로(§19.10 — 남는 것은 웹 RESULT 강등 사본뿐) **초기화**하고,
      // 선택·규칙·저장 폴더는 판정 G 의 논거가 사는 축이라 **강등 유지**한다.
      const key = sessionKey(s);
      if (!generating) disposeResultBySession(lastSessionKey, key);
      lastSessionKey = key;
      setBusy(generating);
    });
  }

  /* 결과 파기 — 진행바·구획·실행 기록을 기본 상태로 되돌린다. 호출자는 둘이다:
     「결과 닫기」(명시 파기 — 로그 무흔적) · 작업 전환/데이터 교체의 자동 초기화
     (U2 §2.18 — 호출측이 퇴장 한 줄을 이어 적는다). */
  function resetGenResult() {
    $("jobGenBar").style.width = "0%";
    RESULT = null;
    const box = $("jobResult");
    box.hidden = true;
    box.dataset.state = "";
    box.dataset.level = "";
    $("jobGenLog").textContent = "";
    $("jobRunLogLast").textContent = "아직 기록이 없습니다.";
    $("jobRunLog").open = false;   // 세션이 죽으면 다시 접는다(펼침은 그 세션의 의사표시)
    logStarted = false;
  }

  /* 강등 = 결과는 남고 "직전 실행"이라고 말한다(판정 G — §2.18 뒤로는 선택·규칙·저장
     폴더 축의 처분). 이미 강등돼 있어도 **다시 그린다**(2R P2): 두 번째 변화가 행동
     가용성을 바꿀 수 있다 — 한 번 강등했다고 건너뛰면 옛 판정의 버튼이 그대로 남는다. */
  function markResultStale() {
    if (!RESULT) return;
    RESULT.stale = true;
    renderResultPanel();
  }

  /* 세션 지문 — 완료 존 처분 판정(결정 7 · U2 §2.18). 성분 5개와 값은 종전 그대로이고
     **모양만 구조**다: `join("|")` 단일 문자열로는 무엇이 갈렸는지 몰라 성분별 처분(작업
     전환·데이터 교체=초기화 / 선택·규칙·저장 폴더=강등)을 지을 수 없다. 선택은 정확한
     인덱스 집합으로(개수만으론 행 교체를 놓친다). 작업 미선택이면 null = 세션 없음. */
  function sessionKey(s) {
    if (!s.has_job) return null;
    // 선택 성분은 **Python 이 낸 커밋 지문**(`selection_key`)이다 — 표에서 세지 않는다.
    // 표의 `selected` 는 범위 편집기가 열려 있으면 **초안** 표지라(F3 판정 D), 그걸로 지문을
    // 만들면 적용도 안 한 편집이 직전 실행 결과를 「직전 실행」으로 강등시키고 취소해도
    // 되돌아오지 않는다(리뷰 1R). 정합에 드는 값은 판정 주체가 낸다(F4 3R 근본 조치와 같은 형태).
    // 규칙 지문도 성분이다(6R P2) — 결과가 「지금 결과」로 남으려면 그것을 만든 규칙이 아직
    // 그 규칙이어야 한다. 편집기에서 고치고 돌아오면 재적재가 규칙을 갈아 끼우는데, 이
    // 성분이 없으면 다른 규칙으로 만든 결과가 후속 행동까지 열어 둔 채 「지금」으로 남는다.
    // `own`(직전 런의 주체)은 지문 성분이 아니라 **작업 축의 판독 보조**다: 이름 변경은
    // 주체가 추종하므로(3R P2) 전환과 갈라 읽을 수 있다 — 개명은 파기가 아니다.
    return {
      job: s.job_name,
      data: s.data_source_label,
      out: s.out_dir,
      sel: s.selection_key || "",
      rules: s.rules_key || "",
      own: s.last_run_job || "",
    };
  }

  /* 결과 처분 — 지문 성분별 2분기(U2 §2.18).
     작업 전환·데이터 교체 = **초기화**: 링1 은 이미 지웠고(`_last_generated`·`_last_failed`
     — §19.10 "잃는 것은 실행 증거뿐") 웹 RESULT 만 강등 사본으로 남는 형상이었다.
     선택·규칙·저장 폴더 = **강등 유지**: 「실패한 N건만 선택」이 자기 결과를 없애면
     무엇을 다시 만드는지 볼 수 없다(선택 변경이 곧 지문 변경 — 판정 G 의 논거가 사는 축).
     이름 변경은 전환이 아니다 — 주체(`own`)가 이름을 추종하므로 job 성분이 갈려도
     주체=열린 작업이면 강등 축으로 내린다. */
  function disposeResultBySession(prev, next) {
    if (!RESULT || prev === null) return;   // 결과 없음 · 직전 비교군 없음(첫 렌더)
    const jobSwitched = next === null ||
      (prev.job !== next.job && next.own !== next.job);
    if (jobSwitched || (next !== null && prev.data !== next.data)) {
      // 초기화 시 퇴장 한 줄(§2.18) — 사용자가 요청하지 않은 소멸이라 흔적을 남긴다.
      // 받는 것은 결과의 사본이 아니라 「결과가 세션에서 물러났다」는 사건과 그때의
      // 경로다(저장 폴더를 손으로 골랐던 런은 그 경로의 유일한 보관처가 결과 존이었다).
      // 리셋 전에 조립한다(RESULT 를 읽는다). 리셋이 실행 기록도 비우므로 로그는 리셋
      // **뒤에** 적는다 — 이 한 줄도 세션 스코프다(영구 증거는 fill-ledger sidecar 몫).
      const exit = resultExitLine();
      resetGenResult();
      if (exit) log(exit);
      return;
    }
    if (prev.job !== next.job || prev.out !== next.out ||
        prev.sel !== next.sel || prev.rules !== next.rules) {
      markResultStale();
    }
  }

  /* 퇴장 한 줄 합성 — 「'발주요청서' 12건 생성(2건 실패) — C:\…\Results」.
     거절(rejected)·진행(running) 태는 생성물이 없어 적을 것이 없다(빈 문자열).
     「결과 닫기」(명시 파기)는 이 경로를 타지 않는다 — 치우라는 행동이 흔적을 남기면
     반만 듣는 것이 된다(§2.18 파기 대칭). */
  function resultExitLine() {
    const r = RESULT;
    if (!r || r.running || r.rejected || typeof r.total !== "number") return "";
    const owner = (LAST && LAST.last_run_job) ? `'${LAST.last_run_job}' ` : "";
    const fail = r.failed ? `(${r.failed}건 실패)` : "";
    const dir = r.out_dir ? ` — ${r.out_dir}` : "";
    return `${owner}${r.total}건 생성${fail}${dir}`;
  }

  /* ---- 세션 표면 동기화 ---- */
  function syncModeDisplay(hasJob) {
    // 거울 면은 **작업의 것**이라 작업이 없으면 설 자리가 없다. 데이터 면은 다르다:
    // 데이터-우선(§18.2)에서 데이터 존은 작업 없이도 살고, 범위 편집기도 데이터만 있으면
    // 연다 — `!hasJob` 으로 함께 닫으면 작업을 고르기 전엔 편집이 첫 왕복마다 취소돼
    // 편집기 자체가 못 쓰는 것이 된다(리뷰 5R). 강제 닫기의 사유를 면별로 가른다.
    if (!hasJob) window.SurfaceSheet.closeAndRestore("jobConfirmSheet");
    // 데이터-우선: 세션 4존·액션바는 상시 — 작업 미선택에도 데이터 존이 진입점이다(§18.2).
    // 구 편집 모드 은닉(결정 39)은 편집기가 자기 화면으로 나가며 사라졌다(F7 판정 N).
    $("jobZones").style.display = "";
    $("jobActionBar").style.display = "";
  }

  /* 스냅샷 갱신 — 편집 저장 직후 새/개명 작업이 후보·문서 탐색에 바로 뜨게(editor.js doSave
     가 호출). 좌 목록 사망(F2 PR-B) 뒤 갱신 대상이 목록에서 이 두 표면으로 옮겨졌다.
     **실패는 늘 loud**(F7): 호출자가 편집기 화면에 있으면 이 화면의 완료 존 log 는 아예
     보이지 않아 조용한 실패가 된다 — 화면이 갈린 뒤로는 모드 분기가 아니라 alert 가 정직하다. */
  function refreshList() {
    Bridge.call(SCREEN, "refresh", {}).catch((err) => {
      window.alert("작업 목록 갱신 실패: " + String((err && err.message) || err));
    });
  }

  /* ---- 활성 작업의 정체·연결 상태(액션바) — 죽은 「선택한 작업」 존의 승계(U2 §4-A) ----
     존이 죽은 뒤 「지금 어느 작업으로 생성하는가」를 말하는 것이 활성 카드 하이라이트
     하나인데, 그 카드는 표를 훑으면 스크롤 위로 사라진다. sticky 사이드바는 기각됐으므로
     (§5.2) 상수 높이 층인 액션바가 작업 이름을 겸한다 — 「이 작업으로 문서 생성」의
     「이 작업」을 같은 줄이 말한다.

     **재연결 도달 보장도 여기가 진다**(#342 리뷰 3라운드 근본 조치). 종전엔 그 의무를 경고
     후보 카드가 졌는데, 후보 구획은 데이터 마운트·호환성·순위 슬라이스 셋에 걸린 **투영**
     이라 조건마다 구멍이 하나씩 났다(같은 결함류 3건: 슬라이스 밖 → ranked 밖 → 데이터
     미마운트). 조건을 하나씩 때우는 대신 **조건이 없는 축**으로 옮긴다: 이 층은 작업이
     선택돼 있으면 언제나 서고, 판정(`template_missing`)·문안(`conn_label`)은 세션 스냅샷이
     그대로 흐른다(표면 재조립 없음). 카드의 「연결 상태」·경고 클릭은 그대로 살지만 그건
     *렌더된 카드에 대한* 계약이지 도달 보장이 아니다. */
  function renderActiveIdentity(s) {
    const on = !!s.has_job;
    $("jobActionName").textContent = on ? (s.job_name || "") : "";
    const missing = on && !!s.template_missing;
    const conn = $("jobActionConn");
    conn.hidden = !missing;
    conn.textContent = missing ? (s.conn_label || "") : "";
    // 버튼 가용성은 setBusy 가 렌더 말미에 [data-busy-lock] 을 일괄 복원하므로 여기서는
    // **존재 여부**(hidden)만 정한다 — disabled 로 숨기면 그 복원이 되살린다.
    $("jobActionRelink").hidden = !missing;
  }

  /* ---- 데이터 존 — 겨눔 라벨·자동 조준 재진술 ---- */
  /* 표시순서 축(F3) — 값의 정본은 Python(`view_order`)이지만, **왕복 중에는 방금 고른 값이
     이긴다**: 확정 전에 도착한 push 가 select 를 옛 값으로 되돌리면 사용자는 자기 조작이
     씹힌 것으로 읽는다(#217 R2 의 선택 토글과 같은 계열). 값이 하나뿐이라 즐겨찾기 같은
     의도 큐는 필요 없고 **마지막 값이 이긴다** — 중간 값은 버리는 것이지 취소가 아니다. */
  let pendingOrder = null;

  function renderOrderBar(s) {
    const sel = $("jobOrderSel");
    // 축의 값은 **존 대상**을 따른다(F3 판정 D): 초안이 열려 있으면 초안의 축이다. 커밋 값만
    // 그리면 편집기에서 순서를 바꾼 뒤 아무 재렌더(행 토글 등)에나 선택기가 옛 값으로
    // 되돌아가 표(초안 순서)와 선택기가 서로 다른 말을 한다.
    const d = s.range_draft;
    const committed = (d && d.open ? d.view_order : s.view_order) || "sourceDesc";
    const want = pendingOrder !== null ? pendingOrder : committed;
    if (sel.value !== want) sel.value = want;
    $("jobOrderNote").textContent = s.order_note || "";
  }

  async function onOrderChange(e) {
    const value = e.target.value;
    pendingOrder = value;
    try {
      // **직렬화**(리뷰 1R): 동시 발신은 도착 순서를 보장하지 않는다 — pywebview 는 호출마다
      // 별도 스레드라, 빠르게 두 번 고르면 **먼저 고른 값이 나중에 커밋**돼 생성 순서와
      // 순번 파일 이름이 마지막 선택과 반대로 정해질 수 있다. 표시만 지키는 `pendingOrder`
      // 로는 못 막는다(그건 화면의 값, 이건 쓰기의 순서). 기제는 intent.js 가 이미 소유한다.
      //
      // 체인 키는 **상태 단위**이지 위젯 단위가 아니다(리뷰 3R): 축을 따로 세웠더니 취소가
      // 먼저 초안을 지우고 늦은 축 변경이 **커밋된 범위**에 착지했다 — 같은 `recordRange`
      // 를 바꾸는 발신은 전부 한 줄에 선다.
      pendingZoneMutations += 1;
      try {
        await window.Intent.chained(ZONE_CHAIN, () =>
          Bridge.call(SCREEN, "set_view_order", { value, epoch: LAST && LAST.zone_epoch }));
      } finally {
        pendingZoneMutations -= 1;
      }
    } catch (err) {
      // 실패하면 **스냅샷이 안 온다** — 의도만 놓으면 선택기는 거절된 값을 계속 보이고
      // 표·생성 순서는 옛 값이라 화면이 거짓말한다(리뷰 4R). 값을 되돌리고 시끄럽게 알린다.
      log("표시순서를 바꾸지 못했습니다: " + String((err && err.message) || err));
      if (pendingOrder === value) pendingOrder = null;
      if (LAST) renderOrderBar(LAST);
      return;
    } finally {
      // 내 왕복이 마지막일 때만 의도를 놓는다 — 뒤에 더 고른 값이 있으면 그 값이 소유자다.
      if (pendingOrder === value) pendingOrder = null;
    }
  }

  function renderData(s) {
    renderOrderBar(s);
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

  /* ---- 문서 작업 후보(§18.4·§18.5·§19.3, data-first) — 판정·순위는 Python 단일 출처 ----
     top=상위 5 순위 카드(클릭 선택·별 토글·추천 표지), more=잘린 수 정직 고지, needs=확인
     필요(막힌 이유 병기). 데이터 미준비면 줄 자체가 없다(§18.1 — 후보 미계산).
     한 가지 작업 방식(HWPX)뿐이라 §19.3 의 방식 구획은 평면으로 퇴화한다 — 「기안」(TXT)이
     이 구획에 합류하는 슬라이스에서 헤더가 선다. */
  // 최근 사용 문안은 **Python 이 낸다**(F6): 두 매체가 다른 술어를 쓰기 때문이다(§19.4 —
  // HWPX 는 완주, TXT 는 복사 1건). 표면이 한 문구로 뭉치면 하필 구별이 중요한 자리에서
  // 이력을 거짓으로 말한다. 구 `lastRunLabel(iso)` 는 그래서 사망했다.

  function candCard(c, s) {
    const active = c.name === s.job_name;
    const fav = c.favorited === true;
    const warn = c.template_missing === true;
    const verb = fav ? "즐겨찾기에서 제거" : "즐겨찾기에 추가";
    // 카드 부제의 **작업 방식 텍스트는 늘 유지된다**(§19.3 마지막 문장) — 한 방식만 있어
    // 머리글이 퇴화해도 여기는 남는다. 색만으로 방식을 구별하지 않는다는 계약의 이행이기도
    // 하다(텍스트가 늘 함께 선다).
    // 「연결 상태」(U2 §4 판정 C, #342)도 같은 계약이다: 텍스트가 정본이고 색은 강조 —
    // 문안은 Python(conn_label)이 내고 여기는 그린다. 정상은 조용히(빈 문자열 = 무표시).
    const meta = (c.suggested ? `<span class="cand-sug">추천</span>` : "") +
      `<span class="cand-mode">${esc(c.mode_label || "")}</span>` +
      `<span class="cand-run">${esc(c.last_run_label || "")}</span>` +
      (c.conn_label ? `<span class="cand-conn">${esc(c.conn_label)}</span>` : "");
    // 활성 카드 확장 부제(판정 B) — 죽은 「선택한 작업」 존의 템플릿 파일명 승계. 전 카드에
    // 주면 side-card 가 같은 파일명 다섯 줄로 늘어나므로 **선택된 하나의 정체**만 확장한다.
    const tpl = active && c.template_name
      ? `<span class="cand-tpl mono">${esc(c.template_name)}</span>` : "";
    // 안정 id는 **이름 유래**다(#138 F13 관례의 변형): 별을 누르면 카드가 1순위로 이동하므로
    // 인덱스는 안정 식별자가 아니고, 그러면 preserve.js 가 방금 누른 별로 포커스를 못 돌려
    // 키보드 사용자가 재렌더마다 문서 처음으로 떨어진다. encodeURIComponent 로 특수문자를
    // 회피한다(따옴표·공백이 속성 경계를 깨지 않게).
    const key = encodeURIComponent(c.name);
    // 활성 카드 ⋮(판정 B) — 열기·폴더에서 보기. 전 카드에 주면 ⋮ 다섯이 서고 hover 노출이라
    // 발견성이 더 나쁘다 — 활성 카드에만, 상시 가시로 선다. 내용은 toggleCandMenu 가 만든다.
    const menu = active && c.template_path
      ? `<button class="cand-menu" type="button" id="jobCandMenuBtn" data-cand-menu` +
        ` data-path="${esc(c.template_path)}" data-busy-lock aria-haspopup="menu"` +
        ` aria-label="'${esc(c.name)}' 템플릿 열기·폴더에서 보기" title="템플릿 열기·폴더에서 보기">⋮</button>`
      : "";
    // 경고 카드(판정 D) — 기본 클릭이 선택 대신 재연결 리다이렉트다. 활성+경고면 경고가
    // 이기므로(차단 사유는 여기서만 말한다) 표식은 활성 여부와 무관하게 싣는다.
    return `<div class="job-cand-card${active ? " active" : ""}${c.suggested ? " suggested" : ""}` +
      `${warn ? " warn" : ""}">` +
      `<button class="cand-fav" type="button" id="jobFav-${key}" data-fav="${esc(c.name)}"` +
      ` aria-pressed="${fav}" aria-label="${esc(c.name)} ${verb}" title="${verb}">` +
      `${fav ? "★" : "☆"}</button>` +
      // data-busy-lock: 생성 중 setBusy 가 비활성 — 진행 중 전환은 Python 도 거부(P1).
      `<button class="cand-pick" type="button" id="jobCand-${key}" data-busy-lock` +
      ` data-cand="${esc(c.name)}"${warn ? ` data-missing="1"` : ""}` +
      ` aria-pressed="${active}"><span class="cand-nm">${esc(c.name)}</span>` +
      `<span class="cand-meta">${meta}</span>${tpl}</button>${menu}</div>`;
  }

  /* ---- 활성 카드 ⋮ 메뉴 — 부유 .ctx-menu(그룹 ⋮ 동형: GroupList.createMenu 소유) ----
     행동 자체는 PathTrack 의 문서 레벨 위임이 받는다(data-track-act·data-path) — 경로 검증
     화이트리스트·오류 재진술을 그대로 상속하고, 여기는 열고 닫기만 진다. 열림 판정은 모듈
     상태가 아니라 메뉴 DOM 에서 파생한다(가변 상태 예산 — 메뉴는 하나뿐이고 내용이 고정이라
     정체를 따로 들 것이 없다; 그룹 ⋮ 의 menuFor 는 「어느 그룹인가」가 있어 상태가 필요했다). */
  const candMenu = window.GroupList.createMenu({ menuId: "jobCandMenu" });

  function candMenuOpen() {
    const m = document.getElementById("jobCandMenu");
    return !!m && m.style.display !== "none";
  }

  function closeCandMenu() {
    candMenu.hide();
  }

  function toggleCandMenu(btn) {
    if (candMenuOpen()) { closeCandMenu(); return; }
    const p = btn.getAttribute("data-path") || "";
    // 라벨은 PathTrack 기존 어휘 그대로다(U2 §2.20 ⑸ — 어휘는 바꾸지 않는다).
    candMenu.show(
      `<button type="button" data-track-act="open" data-path="${esc(p)}">열기</button>` +
      `<button type="button" data-track-act="reveal" data-path="${esc(p)}">폴더에서 보기</button>`,
      btn);
  }

  /* 재연결 흐름의 **단일 몸통** — 입구는 둘이다(U2 §4 판정 D, #342): ①경고 후보 카드의
     기본 클릭(선택의 대체) ②액션바 「템플릿 다시 연결…」(도달 보장 축, 3R). 두 입구가
     각자 흐름을 들면 확인 문안·가드·발신 순서가 갈린다.
     클릭 의도(선택)와 실제 동작(재연결)이 다르므로 **왜 다른지 먼저 재진술**하고(다이얼로그가
     겸한다), 활성 작업이면 세션 재구성(T1 동류)이라 무장 시 손실 확인을 이어 받는다.
     재연결 커밋이 **성사된 뒤에야** 선택이 나간다(브리지 발신 순서 규약) — 실패·취소면
     선택하지 않고 카드는 경고로 남는다. */
  async function relinkTemplateFor(name) {
    const active = !!(LAST && LAST.job_name === name);
    const ok = await window.Modal.confirm({
      title: "템플릿 다시 연결",
      body: active
        ? `'${name}' 작업의 템플릿 파일을 찾을 수 없어 문서를 만들 수 없습니다.\n` +
          `템플릿을 다시 연결하면 작업을 다시 불러옵니다.`
        : `'${name}' 작업은 템플릿 파일을 찾을 수 없어 바로 선택할 수 없습니다.\n` +
          `템플릿을 다시 연결하면 이어서 이 작업을 선택합니다. 실패하면 선택하지 않습니다.`,
      confirmLabel: "템플릿 다시 연결…", cancelLabel: "취소",
    });
    if (!ok) return;
    if (active) {
      // 재연결 확정은 기선택 작업을 재적재해 세션(선택·필터·겨눔)을 재구성한다 — T1 동류
      // 파괴 전이이므로 무장 시 먼저 확인한다(구 존 재연결 버튼의 가드 승계, 리뷰 #0).
      const armed = await confirmDestructiveIfArmed(
        "템플릿 다시 연결 확인", "템플릿을 다시 연결하면", "다시 연결하고 버리기");
      if (!armed) return;
    }
    const committed = await Relink.relinkTemplate(SCREEN, name, (msg) => log(msg));
    // 활성 작업은 백엔드가 커밋과 함께 재적재까지 끝낸다(_do_relink_template) — 여기서
    // select 를 겹쳐 보내면 같은 재구성이 두 번 돈다.
    if (!committed || active) return;
    // 성공 뒤 이어서 선택(판정 D) — 카드는 push 재렌더로 교체됐으므로 id 로 다시 찾는다.
    const card = document.getElementById("jobCand-" + encodeURIComponent(name));
    try {
      await selectJobWithMarker(card, name);
    } catch (err) {
      log("작업 열기 실패: " + String((err && err.message) || err));
    }
  }

  /* 즐겨찾기 전이 단일 몸통 — 후보 카드의 별과 라이브러리 행의 별이 같은 경로를 쓴다(두 표면이
     서로 다른 왕복을 갖지 않게). 기제(미결 의도 계산·전역 쓰기 직렬화·꼬리 식별 정리)는
     리뷰 3R·4R·5R·6R 가 세운 그대로이되 **공용 몸통**(js/intent.js)으로 걷었다 — 재작성 F2 의
     라이브러리가 같은 별을 새로 그리며 기제 없이 DOM 값만 보내 같은 결함류를 재발시켰다
     (리뷰 3R 근본 조치). 여기 남는 것은 이 화면의 브리지 키와 오류 표면뿐이다.

     낙관 표지는 없다: Python 왕복 결과(push)로만 표시가 바뀐다 — 별이 먼저 켜졌다가 저장
     실패로 되돌아가면 영속된 척하는 거짓 표지다(#215 동류). */
  const favorite = window.Intent.createFavorite({
    send: (name, value) => Bridge.call(SCREEN, "toggle_favorite", { name, value })
      .then((res) => { if (res && res.ok === false) log(res.error); }),
    onError: (msg) => log(msg),
  });

  function toggleFavorite(name, domPressed) {
    favorite.toggle(name, domPressed);
  }

  /* ---- 문서 탐색 면(§18.6·§19.5) — 「문서 만들기」 하위 면(별 라우트 아님) ----
     탭 라벨의 수치·행·검색 판정은 Python 이 내고 여기는 그린다. 사용 가능 행 클릭 = 작업
     선택(세션 데이터·선택·필터는 생존, §18.2). 확인 필요 행은 정직한 비활성 + 막힌 열 병기. */
  function renderBrowse(s) {
    const b = s.browse || {
      tab: "available", query: "", rows: [], available_count: 0,
      needs_count: 0, filtered_out: 0,
    };
    const tabs = [
      { key: "available", label: `사용 가능 ${b.available_count}` },
      { key: "needs_action", label: `확인 필요 ${b.needs_count}` },
    ];
    // 안정 id(리뷰 1R P2): 탭 전환은 재렌더라 id 없으면 preserve.js 가 방금 누른 탭으로
    // 포커스를 못 돌리고, 활성 요소가 열린 모달 밖으로 떨어진다(키보드 사용자 좌초).
    $("jobBrowseTabs").innerHTML = tabs.map((t) =>
      `<button class="browse-tab" type="button" role="tab" id="jobBrowseTab-${t.key}"` +
      ` data-busy-lock data-browse-tab="${t.key}" aria-selected="${b.tab === t.key}">` +
      `${esc(t.label)}</button>`
    ).join("");
    // 타이핑 중엔 스냅샷이 입력값을 덮지 않는다(리뷰 4R P2 — 데이터 존 검색과 같은 규칙):
    // 왕복 중 이어 친 글자가 옛 검색어로 되돌아가면 사용자의 의도가 조용히 잘린다. 확정은
    // 포커스가 떠난 뒤(또는 재진입) 렌더가 맡는다.
    const q = $("jobBrowseQuery");
    if (document.activeElement !== q && q.value !== (b.query || "")) {
      q.value = b.query || "";
    }
    const rows = b.rows || [];
    const needsTab = b.tab === "needs_action";
    const browseRow = (r) => {
      if (needsTab) {
        return `<div class="browse-row off"><span class="browse-nm">${esc(r.name)}</span>` +
          `<span class="browse-why muted">현재 데이터에 없는 열: ` +
          `${esc((r.missing || []).join(", "))}</span></div>`;
      }
      const active = r.name === s.job_name;
      return `<button class="browse-row" type="button" id="jobBrowseRow-${encodeURIComponent(r.name)}"` +
        ` data-busy-lock data-browse-pick="${esc(r.name)}"` +
        ` aria-pressed="${active}"><span class="browse-nm">${esc(r.name)}</span>` +
        `<span class="browse-why muted">${esc(r.mode_label || "")}` +
        (active ? " · 지금 선택된 작업" : "") + `</span></button>`;
    };
    // 탭 **안**에서만 방식으로 구획한다(§19.5) — 탭(사용 가능/확인 필요)이 primary
    // classification 이라 방식을 탭으로 올리지 않는다. 퇴화 규칙은 후보 줄과 같다.
    const bsecs = b.sections || [];
    const byBrowseName = {};
    rows.forEach((r) => { byBrowseName[r.name] = r; });
    $("jobBrowseRows").innerHTML = rows.length
      ? (bsecs.length > 1
        ? bsecs.map((sec) =>
          `<div class="browse-sec" data-browse-mode="${esc(sec.mode)}">` +
          `<h3 class="browse-sec-cap">${esc(sec.mode_label)}</h3>` +
          sec.names.map((n) => byBrowseName[n] ? browseRow(byBrowseName[n]) : "").join("") +
          `</div>`).join("")
        : rows.map(browseRow).join(""))
      : `<p class="muted capnote">${b.query
        ? "이름이 일치하는 작업이 없습니다."
        : (needsTab ? "확인이 필요한 작업이 없습니다."
                    : "현재 데이터로 쓸 수 있는 작업이 없습니다.")}</p>`;
    // 검색이 감춘 건수는 조용히 두지 않는다 — 탭 수치와 화면 행 수의 차이를 설명한다.
    $("jobBrowseNote").textContent = b.filtered_out > 0
      ? `검색으로 ${b.filtered_out}건이 목록에서 빠졌습니다.` : "";
  }

  function renderCandidates(s) {
    const row = $("jobCandsRow");
    const host = $("jobCandidates");
    // 데이터·작업이 **둘 다** 없을 때만 흡수처 출구를 세운다(지도 §10.9 판정 C). 작업이
    // 이미 열려 있으면 화면은 할 말이 있으므로(액션바의 활성 작업 이름) 출구는 소음이다.
    $("jobNoDataExit").style.display = (!s.has_data && !s.has_job) ? "" : "none";
    if (!s.has_data) { row.style.display = "none"; host.innerHTML = ""; return; }
    row.style.display = "";
    const c = s.candidates || { top: [], more: 0, needs_count: 0, suggested: "" };
    const top = c.top || [], needs = c.needs_count ? [1] : [];
    // 고지 ①(F6 PR-B — 휘발 「기안」 폐지의 대체 경로 재진술): 술어(txt 템플릿 有 ∧ txt
    // 작업 0건)는 Python 이 낸다. 빈 「온나라 기안」 구획 머리 + 경로 안내 한 줄.
    const txtNote = c.txt_note
      ? `<div class="cand-sec" data-cand-mode="text">` +
        `<h3 class="cand-sec-cap">온나라 기안</h3>` +
        `<span class="muted">${esc(c.txt_note)}</span></div>`
      : "";
    if (!top.length && !needs.length) {
      // 막다른 자리를 만들지 않는다(U2 §2.4). 흡수처 출구(`#jobNoDataExit`)는 데이터·작업이
      // **둘 다** 없을 때만 서는데, 정작 출구가 필요한 상태는 여기다 — 데이터는 골랐고 그
      // 데이터로 쓸 작업이 하나도 없어 이 화면에서 더 갈 데가 없다. 「흡수했다고 적어 놓고
      // 가는 길을 안 보여 주면 그게 조용한 소실」이라는 §10.9 판정 C 가 이 자리에도 걸린다.
      host.innerHTML =
        `<span class="muted">현재 데이터에 사용할 수 있는 문서 작업이 없습니다.</span>` +
        `<button class="btn sm" type="button" data-cands-exit>「문서 작업」에서 고르기</button>` +
        txtNote;
      return;
    }
    // 작업 방식 구획(§19.3) — **구획 여부·순서 판정은 Python**(candidates.sections)이고
    // 여기는 머리글을 그릴지만 정한다. 한 방식뿐이면 머리글 없는 평면으로 퇴화한다:
    // 중복 정보를 줄이려는 계약의 규칙이지 정보를 버리는 것이 아니다(부제는 남는다).
    const byName = {};
    top.forEach((t) => { byName[t.name] = t; });
    const sections = c.sections || [];
    let html;
    if (sections.length > 1) {
      html = sections.map((sec) =>
        `<div class="cand-sec" data-cand-mode="${esc(sec.mode)}">` +
        `<h3 class="cand-sec-cap">${esc(sec.mode_label)}</h3>` +
        sec.names.map((n) => byName[n] ? candCard(byName[n], s) : "").join("") +
        `</div>`).join("");
    } else {
      html = top.map((t) => candCard(t, s)).join("");
    }
    // 잘린 나머지·확인 필요는 **수치 + 문서 탐색 출구**로만 말한다(슬라이스 3): 목록의
    // 소유자는 이제 탐색 면이고, 후보 줄은 "지금 고를 것"만 보여 준다(조용한 절단 금지).
    const bits = [];
    if (c.more > 0) bits.push(`쓸 수 있는 작업 <b>${c.more}건</b> 더`);
    if (c.needs_count > 0) bits.push(`확인 필요 <b>${c.needs_count}건</b>`);
    if (bits.length) {
      html += `<span class="cand-more muted">${bits.join(" · ")} — ` +
        `<button class="btn sm" type="button" id="jobBrowseOpen" data-busy-lock data-browse-open>` +
        `문서 작업 찾기…</button></span>`;
    }
    host.innerHTML = html + txtNote;
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

  /* 실행 표면이 작업대인가(매체 파생) — 판정은 Python 이 낸 `run_action.key` 하나를 읽는다.
     표면이 확장자·매체를 다시 읽어 분기하면 같은 판정이 두 곳에 산다(F6 판정 D). 산출을
     말하는 자리(거울·재진술·저장 폴더·상태 태)가 전부 이 술어 하나를 쓴다. */
  function isCopyWork(s) {
    return !!(s && s.run_action && s.run_action.key === "workbench");
  }

  /* ---- 본문 존 거울 = 필드 채움 테이블(결정 36 ⓑ) ----
     hwpx 본문은 앱에서 렌더 못 하므로 거울이 비추는 것은 "생성될 문서의 채움 상태"다. ADR-E
     배지는 별도 UI가 아니라 거울의 행: 미입력 행 클릭=확인, 재클릭=철회(UD-19). danger(드리프트)는
     ack 로 안 풀리므로 같은 표에 섞지 않고 거울 자리 차단 배너 + 행동 링크로 분리한다(결정 36·S9). */
  function renderMirror(s) {
    const host = $("jobMirror");
    // TXT 는 거울이 **없는 축**이다(스냅샷이 무조건 빈 mirror 를 싣는다) — 존을 통째로
    // 걷는다. 남겨 두면 빈 상태 문안("행을 선택하면 …")이 행을 다 고른 뒤에도 그대로 서서,
    // 따라 해도 아무 일이 없는 막다른 지시가 된다(리뷰 6R).
    const zone = $("jobMirrorZone");
    if (zone) zone.style.display = isCopyWork(s) ? "none" : "";
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
    window.SurfaceSheet.open({
      modalId: "jobConfirmSheet",
      // 클릭된 버튼(캡스트립 위임 포함) → 상시 ⤢ 버튼 순(#279 리뷰, SurfaceSheet.trigger).
      returnFocus: window.SurfaceSheet.trigger(e, $("jobMirrorExpand")),
      initialFocus: $("jobConfirmSheetClose"),
      moves: [
        { id: "jobMirror", slotId: "jobConfirmSheetMirrorSlot" },
        { id: "jobRestate", slotId: "jobConfirmSheetRestateSlot" },
      ],
      afterRestore: measureMirrorCap,
    });
  }

  /* 문서 탐색 면 열기 — 실 DOM 이동(SurfaceSheet)이 아니라 자체 내용을 가진 면이라
     Modal 로 직접 연다. 포커스는 검색 입력으로: 이 표면에 온 이유가 "찾기"다. */
  /* 탐색 면을 닫은 **직후** 포커스를 연결된 컨트롤에 세운다(리뷰 3R P2).

     렌더 훅에 예약하는 방식은 왕복 순서에 의존했다: `select_job` 은 Python 이 이미 push·
     render 를 끝낸 뒤 resolve 하므로 예약이 렌더보다 늦고, 그 예약은 무관한 다음 렌더를
     흔드는 유령으로 남았다. 그래서 **예약을 없애고** 그 시점의 실 DOM 을 id 로 찾아 바로
     세운다 — 착지 우선순위는 방금 고른 작업 카드 → 다시 탐색을 열 출구 → 생성 버튼
     (순위 밖 작업을 골라 카드가 없을 수도 있다). */
  let browsePickedName = "";  // 이번 닫힘이 "고르고 닫음"이면 그 작업 이름(아니면 "")
  // 면의 개폐 세대(리뷰 P2) — 큐에 선 선택이 **그 사이 닫힌** 면의 잔여 명령으로 실행되면
  // 사용자가 취소한 전환이 뒤늦게 일어나고, 표식까지 남아 다음 닫기의 착지를 오염시킨다.
  // 열림·닫힘마다 올려서, 큐가 자기 세대가 아니면 조용히 접는다(전이 없음 = 파괴 없음).
  let browseOpenGen = 0;

  function focusAfterPick(name) {
    // 이름이 비면(단순 닫기) 카드 후보를 건너뛰고 출구 → 생성 버튼 순으로 내려간다.
    const ids = (name ? ["jobCand-" + encodeURIComponent(name)] : [])
      .concat(["jobBrowseOpen", "jobGenBtn"]);
    for (let i = 0; i < ids.length; i++) {
      const el = document.getElementById(ids[i]);
      if (el && el.focus && !el.disabled) {
        try { el.focus({ preventScroll: true }); } catch (err) { el.focus(); }
        return ids[i];
      }
    }
    return "";
  }

  function openBrowseSheet(e) {
    browseOpenGen += 1;
    window.Modal.open("jobBrowseSheet", {
      initialFocus: $("jobBrowseQuery"),
      // 노드를 붙잡아 두지 않는다(리뷰 6R P2): 면 안에서 탭·검색을 한 번이라도 하면 그 사이
      // 재렌더가 후보 줄을 통째로 갈아 끼워 붙잡아 둔 출구 노드가 끊긴다 — Modal 은 끊긴
      // 복귀점을 건너뛰므로 포커스가 방금 숨은 면에 남는다. **닫히는 시점에 다시 찾는다.**
      returnFocus: null,
      // 착지 결정은 **닫힘 1지점**에서만 한다(리뷰 P2): 고르고 닫았으면 그 작업 카드,
      // 그냥 닫았으면(취소) 다시 열 출구다. 선택 경로가 따로 focus 하면 전이 종료 뒤 이
      // 콜백이 덮어써 두 착지가 경합한다 — 사유를 플래그로 넘겨 한 번만 결정한다.
      onClose: () => {
        browseOpenGen += 1;                       // 닫힘도 세대 전환(큐에 선 선택 무효화)
        const n = browsePickedName;
        browsePickedName = "";
        focusAfterPick(n);
      },
    });
  }

  /* 「문서 작업」에서 온 비호환 착지(§19.8 2분기) — 조용히 아무 일도 안 일어나는 대신
     막힌 사유가 있는 자리로 데려간다. 탭·검색어는 세션 소유라 Python 에 먼저 세우고
     (판정·건수는 그쪽이 낸다) 면을 연다. */
  async function openBrowseNeedsAction(name) {
    await Bridge.call(SCREEN, "browse_tab", { tab: "needs_action" });
    await Bridge.call(SCREEN, "browse_query", { text: name });
    openBrowseSheet();
  }

  /* ---- 전문 범위 편집기(F3, 계약 §18.10) — ⤢ 펼침 면 + 초안 거래 ----
     면은 실 DOM 을 옮기고(SurfaceSheet), **의미론만** 새것이다: 여기서의 편집은 초안으로
     격리돼 적용 전 메인 범위·게이트·거울·결과를 바꾸지 않는다(불변식 §18.11-21). 초안의
     소유·판정은 전부 Python(지도 §10.11 판정 A) — 여기는 출구 3개와 가드 1개만 진다. */
  let rangeApplied = false;    // 적용 경로로 닫히는 중(onClose 의 취소 발신 억제)
  let rangeForceClose = false; // 가드 확인을 받은 닫기(다음 요청 1회 통과)

  function draftState() {
    return (LAST && LAST.range_draft) || null;
  }

  function renderRangeFoot(s) {
    const d = s.range_draft || {};
    const on = !!d.selected_only;
    $("jobRangeApply").textContent = `선택 적용: ${d.sel_count || 0}건`;
    const only = $("jobRangeSelectedOnly");
    only.setAttribute("aria-pressed", on ? "true" : "false");
    // 두 사실을 한 줄이 진다: ①지금 무엇을 보고 있는가 ②적용 전에는 반영되지 않는다.
    $("jobRangeNote").textContent = on
      ? "선택된 항목만 보는 중 — 검색과 열 필터는 잠시 적용하지 않습니다. 변경은 적용해야 반영됩니다."
      : "변경은 적용하기 전까지 문서 만들기 화면에 반영되지 않습니다.";
  }

  /* ---- 미리보기 드로어(재작성 F5, 지도 §10.12) --------------------------------
     이 렌더러는 **모듈 상태를 하나도 늘리지 않는다**: 열림·자리·값·이름·증거가 전부
     스냅샷(`s.preview`)에서 온다(판정 A·M). DOM 개폐만 상태를 따라간다 — 여는 것은
     사용자 클릭이 아니라 Python 이 "열렸다"고 말한 사실이다. */
  function renderPreview(s) {
    const p = s.preview || { open: false, can_open: false };
    const r = s.review || {};
    // 「확인 필요」 표지는 요구가 **아직 안 풀렸을 때만**: 승인한 뒤에도 붙어 있으면 확인이
    // 무의미해진다. 버튼 가용성(열기·이동)은 여기서 정하지 않는다 — `setBusy` 가 렌더 말미에
    // `[data-busy-lock]` 을 일괄 복원하므로 여기서 끈 것을 되살린다(`jobBtnPickFolder` 가 같은
    // 이유로 거기 있다). 실 창 프로브가 잡은 자리다.
    $("jobReviewFlag").style.display = r.required && !r.approved ? "" : "none";
    if (!p.open) { closePreviewIfOpen(); return; }
    $("previewPos").textContent = `${(p.pos || 0) + 1} / ${p.total || 0}`;
    const empty = $("previewEmpty");
    empty.textContent = p.empty_note || "";
    empty.style.display = p.empty_note ? "" : "none";
    $("previewRows").innerHTML = (p.rows || []).map((row) =>
      `<div class="mir-row" data-field="${esc(row.name)}">` +
      `<span class="mir-name">${esc(row.name)}</span>` +
      `<span class="mir-val">${row.value ? esc(row.value) : "<em class='muted'>(빈 값)</em>"}</span>` +
      // 행별 「수정」(F6 PR-B deep-link, §10.14.3) — 이상한 값을 본 그 자리에서 그 필드의
      // 탭으로 간다. target 조립·발신은 previewFix 하나(파일 이름 「수정」과 단일 경로).
      `<button class="btn sm" data-act="preview-fix" data-field="${esc(row.name)}"` +
      ` aria-label="'${esc(row.name)}' 연결 수정">수정</button>` +
      `</div>`).join("");
    renderPreviewEvidence(p.evidence || { rows: [], note: "" });
    $("previewFilename").textContent = p.filename || "";
    // 승인 버튼은 **요구가 남아 있을 때만** 선다(v6 `approvePreview.hidden` 승계). 없는
    // 사건의 버튼을 회색으로 두면 "여기서 뭔가 해야 하나" 하는 미끼가 된다.
    $("previewApprove").style.display = p.can_approve ? "" : "none";
  }

  function renderPreviewEvidence(ev) {
    const sec = $("previewEvidence");
    const rows = ev.rows || [];
    if (!rows.length && !ev.note && !ev.reason) { sec.style.display = "none"; return; }
    sec.style.display = "";
    $("previewEvidenceReason").textContent = ev.reason || "";
    $("previewEvidenceReason").style.display = ev.reason ? "" : "none";
    // before 는 **있을 때만** 그린다(F7 판정 H): 직전 판본이 없는 작업(첫 저장·구 버전)에
    // 빈 값을 세우면 "이전엔 비어 있었다"는 거짓 증거가 된다. 값은 저장해 둔 문자열이 아니라
    // **이전 규칙으로 같은 행을 다시 렌더**한 것이라, 두 값이 같은 행의 두 규칙이다.
    const shown = (v) => (v ? esc(v) : "<em class='muted'>(빈 값)</em>");
    $("previewEvidenceRows").innerHTML = rows.map((row) =>
      `<div class="mir-row" data-field="${esc(row.name)}">` +
      `<span class="mir-name">${esc(row.name)}</span>` +
      `<span class="mir-val">` +
      (Object.prototype.hasOwnProperty.call(row, "before")
        ? `<span class="ev-before">${shown(row.before)}</span> → ` : "") +
      shown(row.value) +
      (row.note ? `<span class="doc-sum">${esc(row.note)}</span>` : "") +
      `</span></div>`).join("");
    $("previewEvidenceNote").textContent = ev.note || "";
    $("previewEvidenceNote").style.display = ev.note ? "" : "none";
  }

  /* DOM 개폐를 상태에 맞춘다. Python 이 닫았다고 말했는데 면이 떠 있으면(작업 전환·데이터
     교체 같은 원격 닫힘) 그 면은 남의 값을 그리고 있는 것이다.
     열려 있지 않은 대상의 `Modal.close` 는 스택에 없어 아무 일도 하지 않는다 — 그래서
     열림 여부를 DOM 에 되묻지 않는다(상태의 진실은 스냅샷이지 클래스가 아니다). */
  function closePreviewIfOpen() {
    window.Modal.close("previewModal");
  }

  async function openPreview(e, opts) {
    const o = opts || {};
    const trigger = (e && e.currentTarget) || $("jobPreviewOpen");
    // 성사 뒤에만 연다(§9.3 4행 상속): 거절되면(생성 중·초안 열림·선택 0건) 면을 띄우지
    // 않는다 — 열어 놓고 실패를 말하면 무엇을 미리보는 중인지가 거짓이 된다.
    // `at` = deep-link 복귀의 같은 자리(§10.15.15 판정 C) — 값은 Python 이 push 한
    // preview.pos 의 왕복이고 Python 이 클램프한다. 리터럴 payload(정적 가드 판독 대상).
    try {
      await dz.flushPendingEdits();   // 예약된 편집이 뒤늦게 착지해 자리를 흔들지 않게
      await Bridge.call(SCREEN, "preview_open", { at: o.at || 0 });
    } catch (err) {
      log("미리보기를 열지 못했습니다: " + String((err && err.message) || err));
      return;
    }
    // 왕복 중 화면을 떠났으면(다른 탭·편집기) 열지 않고 상태를 되돌린다 — 남는 「열림」
    // 상태가 다음 복귀에서 아무 트리거 없이 면을 띄운다.
    if (!$("scr-job").classList.contains("on")) {
      Bridge.call(SCREEN, "preview_close", {});
      return;
    }
    window.Modal.open("previewModal", {
      returnFocus: trigger,
      initialFocus: $("previewClose"),
      onClose: () => { Bridge.call(SCREEN, "preview_close", {}); },
    });
    // 복귀 초점 = 떠났던 그 행의 「수정」(§10.14.3 "같은 행"). 행 DOM 은 push 재렌더가
    // 만들므로(브리지 반환과 독립 채널) 유한 재시도 후 폴백은 initialFocus(previewClose).
    if (o.focusTarget) focusPreviewTarget(o.focusTarget);
  }

  function focusPreviewTarget(target) {
    const find = () => (target === "filename/filenamePattern"
      ? $("previewFixFilename")
      : document.querySelector(
          `#previewRows [data-act="preview-fix"][data-field="${CSS.escape(target.slice("binding/".length))}"]`));
    let tries = 0;
    const step = () => {
      const el = find();
      if (el && el.offsetParent !== null) { el.focus(); return; }
      if (++tries > 3) return;             // 폴백 — 이미 선 previewClose 초점을 유지
      requestAnimationFrame(step);
    };
    step();
  }

  /* 행별·파일 이름 「수정」의 단일 경로(F6 PR-B, §10.14.3) — EditContext.target 한 축.
     `at` 은 Modal.close 가 onClose 로 preview_close 를 발화하기 **전에** 읽는다: pos 는
     닫힘에 0 으로 리셋되므로, 순서를 바꾸면 복귀가 늘 첫 행으로 선다(발신 순서 규약). */
  async function previewFix(target, evidence) {
    const at = ((LAST && LAST.preview) || {}).pos || 0;
    window.Modal.close("previewModal");   // 편집 호스트 위에 남의 모달 금지(F2 PR-B 교훈)
    const opened = await openEditForRepair({
      entry_reason: "preview_result",
      target,
      evidence,
      return_context: { surface: "preview", reopen_drawer: true, preview_index: at },
    });
    // 착지 조준은 편집기 소유(스크롤·포커스) — 진입 성사 뒤에만 겨눈다.
    if (opened && window.EditorScreen && window.EditorScreen.aimAt) {
      window.EditorScreen.aimAt(target);
    }
  }

  /* 이탈 가드(판정 F) — 변경이 있을 때만 묻는다. 3택 대신 2택인 근거는 「적용」이 이미 면
     안의 상시 버튼이라는 것: 가드가 세 번째 선택지를 새 기제로 만들 필요가 없다(계속 편집 →
     적용 = 한 클릭). 파괴 방향만 명시 확인을 받는다. */
  function guardRangeClose() {
    if (rangeForceClose) { rangeForceClose = false; return true; }
    const d = draftState();
    if (!d || !d.open) return true;          // 초안 없는 면 = 평범한 닫기
    // `dirty` 는 **푸시가 온 사실**이다(리뷰 4R): 방금 친 편집이 아직 왕복 중이면 false 라,
    // 그것만 보면 약속한 확인 없이 조용히 버린다. 내가 보낸 편집의 수를 함께 센다.
    if (!d.dirty && pendingZoneMutations === 0) { discardAndClose(); return false; }
    window.Modal.confirm({
      title: "편집한 범위를 버릴까요?",
      body: "적용하지 않은 변경이 있습니다. 버리면 문서 만들기 화면의 범위는 그대로 남습니다.",
      confirmLabel: "버리고 닫기",
      cancelLabel: "계속 편집",
      danger: true,
      returnFocus: $("jobRangeCancel"),
    }).then((ok) => {
      if (ok) discardAndClose();             // 아니면 면 유지(아무 일도 안 일어난다)
    });
    return false;                            // 이 닫기 요청은 소비 — 폐기 성사 뒤 다시 닫는다
  }

  /* 취소도 **성사 뒤에 닫는다**(적용과 같은 순서, 리뷰 1R): 먼저 닫으면 느린 브리지에서
     메인 화면이 잠시 초안 기준 행을 그리고 생성이 잠긴 채로 남으며, 발신이 거절되면 면은
     닫혔는데 Python 초안만 살아남는다(고아). 실패하면 면을 유지하고 사유를 남긴다. */
  async function discardAndClose() {
    try {
      // 대기 중 편집은 **보내지 않는다**(리뷰 2R P1) — 초안이 사라진 뒤 도착하면 사용자가
      // 버린 검색어가 커밋된 필터에 착지한다. 이미 나간 발신은 같은 체인이 순서를 지킨다.
      dz.dropPendingEdits();
      await window.Intent.chained(ZONE_CHAIN, () =>
        Bridge.call(SCREEN, "range_draft_cancel", {}));
    } catch (err) {
      log("범위 편집을 취소하지 못했습니다: " + String((err && err.message) || err));
      return;
    }
    rangeForceClose = true;
    window.SurfaceSheet.close("dataSheet");
  }

  async function applyRangeDraft() {
    try {
      // 디바운스 창 안에서 눌러도 방금 친 조건이 사라지지 않게 먼저 정산한다.
      await dz.flushPendingEdits();
      await window.Intent.chained(ZONE_CHAIN, () =>
        Bridge.call(SCREEN, "range_draft_apply", {}));
    } catch (err) {
      // 실패(세대 불일치 등)에서는 **닫지 않는다**(§10.11.2 실패 경로 면) — 문맥을 남긴다.
      log("범위를 적용하지 못했습니다: " + String((err && err.message) || err));
      return;
    }
    rangeApplied = true;
    rangeForceClose = true;
    window.SurfaceSheet.close("dataSheet");
  }

  function openJobDataSheet(e) {
    const trigger = window.SurfaceSheet.trigger(e, $("jobDataExpand"));
    // 성사 뒤에만 연다(§9.3 4행): 초안 생성이 거절되면(생성 중·데이터 없음) 면을 띄우지
    // 않는다 — 열어 놓고 나서 실패를 말하면 편집기가 무엇을 편집 중인지 거짓이 된다.
    //
    // **열기도 존 체인에 선다**(리뷰 5R): 방금 친 편집이 큐에 있는데 열기가 먼저 도착하면,
    // 그 편집은 옛 세대를 업고 와 stale 로 거절된다 — 사용자가 화면에서 본 변경이 커밋에도
    // 초안에도 없이 사라진다(세대 기제가 스스로 연 창). 디바운스 예약분도 먼저 정산해
    // **복제되는 범위가 사용자가 보고 있던 그것**이 되게 한다.
    (async () => {
      try {
        await dz.flushPendingEdits();
        await window.Intent.chained(ZONE_CHAIN, () =>
          Bridge.call(SCREEN, "range_draft_open", {}));
      } catch (err) {
        log("범위 편집기를 열지 못했습니다: " + String((err && err.message) || err));
        return;
      }
      // 왕복 중 다른 탭으로 떠났거나 편집 모드로 넘어갔으면 **열지 않는다**(리뷰 2R P2):
      // 전역 면이라 새 화면 위에 남의 화면 DOM 을 얹고 뜬다. 초안은 여기서 거둔다 —
      // 안 그러면 아무 표면도 없는 초안이 남아 생성이 조용히 잠긴 채로 있는다.
      if (!$("scr-job").classList.contains("on")) {
        Bridge.call(SCREEN, "range_draft_cancel", {});
        return;
      }
      rangeApplied = false;
      rangeForceClose = false;
      $("dataSheetTitle").textContent = "처리할 행 범위";
      window.SurfaceSheet.open({
        modalId: "dataSheet",
        returnFocus: trigger,
        initialFocus: $("dataSheetClose"),
        beforeClose: guardRangeClose,
        onClose: () => {
          // 백스톱: 정상 경로(적용·폐기)는 닫기 **전에** 이미 정리했다. 가드를 우회해 닫히는
          // 경로(모드 전환의 강제 닫기 등)만 여기서 잡아 고아 초안을 남기지 않는다.
          const d = draftState();
          if (!rangeApplied && d && d.open) Bridge.call(SCREEN, "range_draft_cancel", {});
        },
        moves: [
          { id: "jobRecsHead", slotId: "dataSheetSlot" },
          // 표시순서 축도 따라간다(F3 판정 C): 축이 메인에만 남으면 펼친 면에서 순서를 못
          // 바꾸고, 두 벌로 복제하면 상태가 둘로 갈린다 — 같은 요소가 이동하므로 둘 다 아니다.
          { id: "jobOrderBar", slotId: "dataSheetSlot" },
          { id: "jobFilterChips", slotId: "dataSheetSlot" },
          { id: "jobTableHost", slotId: "dataSheetSlot" },
          { id: "jobSelStrip", slotId: "dataSheetSlot" },
          { id: "jobColPanel", slotId: "dataSheetSlot" },
          { id: "jobRangeFoot", slotId: "dataSheetSlot" },
        ],
      });
    })();
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
    // 작업 미선택(prework)이면 재진술 자체가 성립하지 않는다 — 파일명·폴더가 정의 불가한데
    // "문서 N건 생성"을 말하면 과진술(거짓)이다(#302 리뷰 P2). 게이트가 다음 할 일을 말한다.
    if (!s.has_job || !s.has_data || !sel.length || blocked) { box.style.display = "none"; box.innerHTML = ""; return; }
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
    // 산출 재진술은 **매체마다 다른 사실**이다(리뷰 6R). TXT 는 파일을 만들지 않으므로
    // 「문서 N건 · 저장 폴더」도, 파일 이름 목록(전부 "(파일명 미정)")도 거짓이다 —
    // 이 버튼이 실제로 하는 일(작업대에서 레코드마다 검토·복사)을 그대로 말한다.
    box.innerHTML = isCopyWork(s)
      ? `<span class="dl">선택</span><span>${selLine}</span>` +
        `<span class="dl">복사</span><span>작업대에서 ${sel.length}건을 한 건씩 검토하고 ` +
        `복사합니다. 파일은 만들지 않습니다.</span>`
      : `<span class="dl">선택</span><span>${selLine}</span>` +
        `<span class="dl">생성</span><span>문서 ${sel.length}건 · 저장 폴더: ${esc(s.out_dir || "미지정")}` +
        `<div class="namelist">${list}${more}</div></span>`;
  }

  /* ---- 본문 존: 게이트·저장 폴더·생성 버튼 ---- */
  /* 게이트 지목의 **어휘 지도**(#342 리뷰 P2) — 링1 이 낸 사유 축 이름 → 그 축을 소유한
     구획 캡션. 판정(무엇이 막는가·무엇이 먼저인가)은 게이트가 하고 여기는 이름을 자리로
     옮기기만 한다. 표면이 상태를 다시 읽어 지목을 만들면 서열이 두 곳에 살고, 실제로 그렇게
     샜다: `template_missing` 을 직접 보고 접두를 붙이는 바람에 **행 선택이 먼저인** TXT
     상태(`workbench_entry_gate` 서열 = 데이터 → 행 → 템플릿)에서도 문서 선택기를 가리켰다.

     템플릿 축(`template_missing`·`template_unreadable`)은 **빈 문자열**이다 — 그 축을
     소유하던 「선택한 작업」 존은 죽었고(U2 §4), 복구는 같은 액션바 줄의 연결 상태·재연결이
     곁에서 진다(3R). 없는 구획을 가리키느니 아무 데도 가리키지 않는다. */
  const GATE_ZONE = {
    no_data: "현재 데이터 · ",
    no_rows: "현재 데이터 · ",
    no_candidates: "이 데이터에 사용할 문서 · ",
    no_job: "이 데이터에 사용할 문서 · ",
    drift: "본문 확인 · ",
    name_tokens: "본문 확인 · ",
    template_missing: "",
    template_unreadable: "",
  };

  function gateStep(s, g) {
    // 게이트의 판정(level/enabled/text)은 Python 단일 출처 그대로 두고, 현재 막힌 **구획의
    // 이름**만 표시층에서 결합한다(H-03 승계). R1 재작성으로 4존 znum 이 사라져 구 서수
    // ①②③ 은 가리킬 대상을 잃었다 — 정보(어디로 가야 하는가)는 살리고 표기를 실재하는
    // 구획 캡션으로 바꾼다(죽은 번호를 남기면 지목이 거짓말이 된다).
    if (!g || g.enabled || !g.text) return "";
    // 링1 이 축 이름을 냈으면 그 이름만 읽는다 — 상태 재유도 금지(서열은 게이트의 것).
    const named = GATE_ZONE[g.reason || ""];
    if (named !== undefined) return named;
    // 이름 없는 게이트(빈 값 확인·저장 폴더·이어채우기 등 hwpx warn 갈래)만 자리로 유추한다.
    // 이 갈래들은 선택된 작업의 본문 축이라 지목이 하나뿐이고, 데이터·행이 안 갖춰졌으면
    // 그게 먼저다(prework_gate 서열과 같은 걸음).
    const noRows = !s.has_data || !(s.selected_count > 0);
    if (!s.has_job) return noRows ? GATE_ZONE.no_data : GATE_ZONE.no_job;
    if (noRows) return GATE_ZONE.no_data;
    return GATE_ZONE.drift;
  }

  function renderGateAndFolder(s) {
    // 저장 폴더는 hwpx 생성의 축이다 — TXT 에선 그 자리를 그리지 않는다(빈 값으로 두면
    // "아직 안 정했다"로 읽혀 사용자가 고르러 간다). 캡션도 하는 일을 따라간다.
    const copyWork = isCopyWork(s);
    $("jobOutRow").style.display = copyWork ? "none" : "";
    $("jobRunCap").textContent = copyWork ? "복사 준비" : "생성 준비";
    $("jobOutDir").value = s.out_dir || "";
    // 저장 폴더 열기/경로 복사 어포던스(#53-B) — 실행 화면에서 승계(리뷰 F3). 생성 후 앱에서
    // 바로 폴더를 열거나 경로를 복사한다(빈 out_dir 이면 PathTrack 이 알아서 아무것도 안 그림).
    const ot = $("jobOutTrack");
    if (ot) ot.innerHTML = PathTrack.affordances(s.out_dir, { only: ["reveal", "copy"] });
    const g = s.gate || { enabled: false, level: "", text: "" };
    $("jobGenBtn").disabled = !g.enabled || generating;
    const gate = $("jobGate");
    gate.textContent = generating ? "" : gateStep(s, g) + g.text;
    // 정적 선언(`class="muted capnote"`)을 **덮어쓰지 않는다**(리뷰 R5) — 여기서 "muted" 만
    // 세우면 `capnote`(캡션급 크기)가 매 렌더에 조용히 벗겨지고, 빈 문안이 자리를 비우게 하는
    // 규칙(`.actionbar-row>.capnote:empty`)도 붙을 곳을 잃는다. 마크업이 선언한 것을 지운 뒤
    // 그 선언을 근거로 쓰는 규칙을 짜면 둘 다 거짓이 된다.
    gate.className = "muted capnote";
    gate.style.color = g.level === "danger" ? "var(--a-danger)"
      : g.level === "warn" ? "var(--a-warn)" : "";
  }

  function renderStatus(s) {
    const pill = $("jobStatus");
    if (!s.has_job) { pill.dataset.level = "idle"; pill.textContent = "작업 선택"; return; }
    if (!s.has_data) { pill.dataset.level = "idle"; pill.textContent = "데이터 선택"; return; }
    if (s.gate && s.gate.enabled) {
      pill.dataset.level = "ok";
      pill.textContent = isCopyWork(s) ? "복사 준비" : "생성 준비";
      return;
    }
    // 막힌 이유가 규칙축이면 표지도 「승인」이다(U2 §2.10 · 리뷰 R1). 어휘를 갈라 놓고 이
    // 자리만 「확인 필요」로 두면, 첫 실행 화면에서 상단 표지와 옆 표지가 **같은 행동을 두
    // 이름으로** 부른다 — 어휘 분리가 하려던 일이 그 자리에서 무효가 된다. 서열을 다시
    // 유도하지 않고 게이트가 낸 `reason` 하나만 읽는다(그러라고 있는 필드다).
    pill.dataset.level = "warn";
    pill.textContent = (s.gate && s.gate.reason) === "review_required" ? "승인 필요" : "확인 필요";
  }

  /* 진행 델타 — 진행바 + 진행 태만 갱신(전체 재렌더 없음). 진행은 3태를 덮지 않는다:
     같은 구획에 `running` 태로 서고, 끝나면 Python 이 낸 태가 그 자리를 받는다. */
  function renderProgress(p) {
    const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
    $("jobGenBar").style.width = pct + "%";
    RESULT = { running: true, title: `생성 중… ${p.done}/${p.total}`, summary: "" };
    renderResultPanel();
  }

  /* ---- 실행 기록(비-결과 사건 채널, 세션 스코프) ---- */
  let logStarted = false;
  function log(msg) {
    const box = $("jobGenLog");
    const ts = new Date().toLocaleTimeString("ko-KR", { hour12: false });
    if (!logStarted) { box.textContent = ""; logStarted = true; }
    box.textContent += (box.textContent ? "\n" : "") + `[${ts}] ${msg}`;
    box.scrollTop = box.scrollHeight;
    // 접힌 채로도 **마지막 한 줄**은 보인다 — 상자를 통째로 숨기면 이 화면의 유일한 비모달
    // 사건 채널(작업 열기 실패·폴더 오류 등)이 조용해진다. 접힘은 노이즈 억제지 소음 제거다.
    $("jobRunLogLast").textContent = msg;
  }

  /* ---- busy 잠금 — [data-busy-lock] 속성 선언(setBusy 누락 회귀 방지, #26) ---- */
  function setBusy(busy) {
    // 탐색 면·데이터 선택 면은 **오버레이 루트**에 살아 `#scr-job` 질의에 안 걸린다(리뷰 2R
    // P2) — 생성 중 열려 있으면 클릭이 Python 거절로 끝나고 사용자는 문맥만 잃는다. 같은
    // 잠금에 넣는다(지도 §10.7.1 계약면 2).
    // ⤢ 펼침 면 2종도 같은 이유로 루트다: 실 DOM 이동이라 잠글 요소가 **면 안으로 옮겨가**
    // `#scr-job` 질의에서 빠진다(표시순서 축·전체 선택·검색이 그렇게 새 있었다, F3).
    [$("scr-job"), $("jobBrowseSheet"), $("dataPickerModal"),
     $("dataSheet"), $("jobConfirmSheet"), $("previewModal")].forEach((root) => {
      root.querySelectorAll("[data-busy-lock]").forEach((el) => { el.disabled = busy; });
    });
    // 초안이 열려 있으면 생성은 닫혀 있다(§10.11.2 계약면 2 — 잠금은 DOM 이 아니라 상태가
    // 진다). Python 도 같은 이유로 거절하지만, 버튼이 눌리는 척하면 거절 문구가 사후 통보가
    // 된다. 모달에 가려 물리적으로 못 누르는 것과 잠긴 것은 다른 사실이다.
    const draftOpen = !!(LAST && LAST.range_draft && LAST.range_draft.open);
    $("jobGenBtn").disabled =
      busy || draftOpen || !(LAST && LAST.gate && LAST.gate.enabled);
    // 저장 폴더는 작업 속성(기본 = 템플릿/Results) — 작업 미선택에서 고르게 두면 작업
    // 선택이 기본값으로 조용히 덮어써 선택이 증발한다(#302 리뷰 P2). busy-lock 일괄 복원이
    // 되살리지 않도록 여기(렌더 말미 단일 지점)서 판정한다.
    // TXT 는 저장 폴더 축이 없으므로 피커도 없다(행 자체가 숨지만 잠금은 DOM 이 아니라
    // 상태가 진다 — 일괄 복원이 되살리지 않게 여기서 못박는다).
    $("jobBtnPickFolder").disabled =
      busy || !(LAST && LAST.has_job) || isCopyWork(LAST);
    // 미리보기 버튼들도 여기서 정한다(F5) — 위 일괄 복원이 renderPreview 의 판정을 되살린다.
    // 열기는 선택이 있을 때, 이동은 경계에서 멈춘다(순환하지 않으므로 끝에서 비활성).
    const pv = (LAST && LAST.preview) || {};
    $("jobPreviewOpen").disabled = busy || !pv.can_open;
    $("previewPrev").disabled = busy || !pv.total || pv.pos <= 0;
    $("previewNext").disabled = busy || !pv.total || pv.pos >= pv.total - 1;
    // 실행 행동은 **매체 파생 2분기**(F6 판정 D) — 라벨도 행동 키도 Python 이 낸다.
    // 표면이 매체를 다시 읽어 분기하면 같은 판정이 두 곳에 산다.
    const ra = (LAST && LAST.run_action) || { key: "generate", label: "이 작업으로 문서 생성" };
    $("jobGenBtn").textContent = busy ? "생성 중…" : ra.label;
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
    // 커밋은 대기 중인 존 변이 뒤에 선다(8R P1). 덮어쓰기 확인 뒤의 재귀 호출도 같은 관문을
    // 지나되, 그 시점엔 체인이 이미 비어 있어 즉시 통과한다.
    await window.Intent.settle(ZONE_CHAIN);
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
    // 취소된 배치는 부분 결과로 그린다(#278 리뷰) — 진행바를 무조건 100% 로 채우고
    // warn 을 danger 로 접으면, 정확한 요약 문안 옆에서 시각이 "완주했고 오류"라고
    // 거짓말한다. 진행 = 시도한 만큼, 색 = Python 판정 level 그대로(warn 채널 보존).
    const pct = res.cancelled && res.total
      ? Math.round(((res.attempted || 0) / res.total) * 100) : 100;
    $("jobGenBar").style.width = pct + "%";
    RESULT = res;
    renderResultPanel();
  }

  /* 실행 전 거절(게이트 방어 재확인) — 3태가 아니다. 같은 구획에 `rejected` 태로 서서
     "생성하지 않았다"를 말한다: 결과 자리를 비워 두면 눌렀는데 아무 일도 없는 것으로 읽힌다. */
  function warnResult(msg, level) {
    RESULT = {
      rejected: true, level: level === "danger" ? "danger" : "warn",
      title: "생성하지 않았습니다", summary: msg,
    };
    renderResultPanel();
    log(msg);
  }

  /* ---- 결과 3태 구획(F4, 지도 §10.10) ----
     RESULT 은 웹 소유 세션 상태다(Python 푸시가 덮지 않는다 — 결과는 그 실행의 것이고
     스냅샷은 지금 상태의 것이다). 태·색·문안·실패 판정은 전부 Python 이 낸 값을 그대로
     쓴다: 여기서 재계산하면 판정이 두 벌이 된다(판정 A). */
  let RESULT = null;

  function renderResultPanel() {
    const box = $("jobResult");
    if (!RESULT) { box.hidden = true; box.dataset.state = ""; return; }
    const r = RESULT;
    const state = r.running ? "running" : r.rejected ? "rejected" : (r.status || "failed");
    box.hidden = false;
    box.dataset.state = state;
    box.dataset.level = r.level || "";
    $("jobResultTitle").textContent = r.title || "";
    $("jobResultSummary").textContent = r.summary || "";
    // 이 결과가 **지금 열린 작업의 것인가** — 판정에 드는 두 값(직전 런의 주체·열린 작업)은
    // 둘 다 Python 이 낸 스냅샷 값이다(3R P2 근본 조치). 표면이 정체를 들고 비교하면 그
    // 정체가 변할 때(이름 변경) 같은 작업이 남처럼 보인다. 주체가 아니면 결과의 행동 2종은
    // 남의 작업을 겨누거나 확실한 무동작이 되므로 **행동만 걷고 증거는 남긴다**.
    const owner = (LAST && LAST.last_run_job) || "";
    const mine = !!(owner && LAST.job_name && owner === LAST.job_name);
    const foreign = !mine;
    // 강등 표기 — 무엇이 달라졌는지까지는 말하지 않는다(추측 금지). 다만 다른 작업이 열려
    // 있으면 **어느 작업의 결과인지**를 밝힌다: 행동이 걷힌 이유가 거기 있다.
    const stale = $("jobResultStale");
    stale.hidden = !r.stale;
    stale.textContent = !r.stale ? ""
      : foreign && owner
        ? `이 결과는 '${owner}' 실행입니다. 지금은 그 작업이 열려 있지 않아 여기서 이어서 손볼 수 없습니다.`
        : "이 결과는 직전 실행입니다. 그 뒤 작업·데이터·선택이 바뀌었습니다.";

    const dir = $("jobResultDir");
    const hasDir = !!(r.out_dir && !r.running && !r.rejected);
    dir.parentElement.hidden = !hasDir;
    dir.textContent = r.out_dir || "";
    // 저장 폴더 어포던스는 **실패 태에서도** 남는다 — 실패 진단의 첫 걸음이 그 폴더 열기다.
    $("jobResultTrack").innerHTML = hasDir
      ? PathTrack.affordances(r.out_dir, { only: ["reveal", "copy"] }) : "";

    const fails = r.failures || [];
    $("jobResultFails").innerHTML = fails.map(failRow).join("");
    // 복구 행동의 노출·라벨은 **행 목록이 아니라 Python 수치**(failed_selectable)가 정한다
    // (1R P2): 배치 진입 전 실패는 레코드별 시도가 없어 행이 0개인데, 다시 만들 대상은
    // 전량이다 — 행에서 파생하면 그 런에서만 복구 행동이 통째로 사라진다.
    const sel = $("jobResultFailedSel");
    const selectable = r.failed_selectable || 0;
    // 작업이 바뀌었으면 실패 목록은 Python 에서 이미 죽었다 — 남겨 두면 0건을 돌려주는
    // 유령 버튼이다. `hidden` 을 쓰는 이유: setBusy 가 [data-busy-lock] 의 disabled 를
    // 매 렌더 되돌리므로 disabled 로는 이 판정이 유지되지 않는다.
    sel.hidden = !selectable || foreign;
    sel.textContent = `실패한 ${selectable}건만 선택`;
    $("jobResultRename").hidden = !!(r.running || r.rejected) || foreign;
    $("jobResultClose").hidden = !!r.running;
    renderEvidence(r, fails);
  }

  /* 실패 행 = 식별 요약 + 실파일명 + 사유. 「어느 행인가」는 표 「문서」 열과 같은 판정
     (Python identity_summary)이라 사용자가 결과에서 본 이름으로 표에서 그 행을 찾는다. */
  function failRow(f) {
    const undiag = f.known ? ""
      : `<div class="result3-undiagnosed">원인 진단 미연결 — 확인된 원인이 없어 받은 메시지를 그대로 보여줍니다.</div>`;
    const who = f.identity ? `<div class="result3-fail-why">${esc(f.identity)}</div>` : "";
    return `<div class="result3-fail" id="jobResultFail-${esc(String(f.index))}">
      <div class="result3-fail-name">${esc(f.filename || "")} 저장 실패</div>
      ${who}<div class="result3-fail-why">${esc(f.reason || "")}</div>${undiag}</div>`;
  }

  /* 접힘 증거 — 로그 상자가 나르던 것(FillNote 사실·받은 메시지 원문)의 새 거처(§10.10.3).
     열림 상태는 <details> 가 소유해 재렌더를 건넌다. */
  function renderEvidence(r, fails) {
    const notes = r.fill_notes || [];
    const parts = [];
    if (notes.length) {
      parts.push(`<div><b>채움 주의 ${notes.length}건</b><ul>` +
        notes.map((n) => `<li>${esc(n)}</li>`).join("") + "</ul></div>");
    }
    if (r.stage || r.message) {
      parts.push(`<div><b>실패 단계</b> ${esc(r.stage || "")}` +
        `<pre>${esc(r.message || "")}</pre></div>`);
      if (r.known === false) {
        parts.push(`<div class="result3-undiagnosed">원인 진단 미연결</div>`);
      }
    }
    if (r.cancelled) {
      parts.push(`<div>미착수 ${r.unstarted || 0}건 — 중단 요청 시점에 아직 시작하지 않았습니다.</div>`);
    }
    // 사용한 판본(§13-7 · 재작성 F7 판정 I) — 계약 §10.3 이 원인 미확정 화면에 명시적으로
    // 요구하는 증거다. 값은 **런이 시작될 때 고정된 것**이라 그 뒤 편집 저장이 판본을
    // 올려도 여기 숫자는 그 실행이 실제로 쓴 세대를 가리킨다. 없으면(구 결과·정체 소실)
    // 줄 자체를 만들지 않는다 — 모르는 세대를 r1 로 채우지 않는다.
    const rev = r.revisions || {};
    if (rev.template || rev.binding) {
      parts.push(`<div><b>사용한 판본</b> 템플릿 r${esc(String(rev.template || "?"))} · ` +
        `연결 r${esc(String(rev.binding || "?"))}</div>`);
    }
    const box = $("jobResultEvidence");
    box.hidden = !parts.length;
    $("jobResultEvidenceCap").textContent =
      notes.length ? `자세히 · 채움 주의 ${notes.length}건` : "자세히";
    $("jobResultEvidenceBody").innerHTML = parts.join("");
    if (!parts.length) box.open = false;
    // 실패 원문은 각 실패 행이 이미 상시 가시로 진다(접어 두면 증거가 한 겹 뒤로 간다).
    void fails;
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

  /* 손실 열거는 **실제로 파기되는 집합**과 일치해야 한다(지도 §10.7.3 감사) — 과경고도
     누락도 거짓말이다. 데이터 전환이 파기하는 것: ①선택(0건 재생성) ②필터 정의(재생성)
     ③빈 값 확인(`set_acquired` 의 ack 재평가). 자동 조준 재진술은 사라지는 게 아니라 새
     데이터가 스스로를 재진술하며 **대체**되고, 생성 결과·로그는 그대로 남으므로 열거하지
     않는다. 필터 정의는 직전 슬롯에 스태시되지만 재적용은 **소스 일치**를 요구하므로
     (`_reapply_available` 3연언) 다른 데이터로 가면 지금 자리에선 되살릴 수 없다 — 그 조건
     까지 말해야 "사라진다"가 정확해진다. */
  function guardBody(g, verbPhrase) {
    const lost = [selectionLine(g.sel_count, g.filter_active, g.in_def, g.extra)];
    if (g.filter_parts > 0) lost.push(`필터 정의(${g.filter_parts}개 조건)`);
    if (g.ack_count > 0) lost.push(`빈 값 확인 ${g.ack_count}개`);
    const stash = g.filter_parts > 0
      ? "\n필터 정의는 이 데이터로 돌아오면 「직전 필터 재적용」으로 되살릴 수 있습니다." : "";
    return `${verbPhrase} 이 세션의 선택이 사라집니다.\n` +
      `사라지는 것: ${lost.join(" · ")}.${stash}`;
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

  /* 데이터 선택 다이얼로그 「현재 데이터」 구획 소재 — 스냅샷이 이미 낸 값만 옮긴다(재판정
     금지). `path`·`sheet` 는 「이 데이터 고정」이 프리필로 쓰는 참조 정체(Python 소유
     data_target)이고, 출처가 `pool` 이면 이미 고정된 참조라 고정 버튼이 뜨지 않는다. */
  function currentDataDescriptor() {
    const t = (LAST && LAST.data_target) || {};
    return {
      label: (LAST && LAST.data_source_label) || "",
      detail: LAST && LAST.has_data ? `${LAST.record_count}건` : "",
      path: t.path || "", sheet: t.sheet || "", origin: t.origin || "",
    };
  }

  /* 작업 전환 — **가드 없음**이 계약이다(데이터-우선 §18.2): 전환은 vm 만 재생성하고
     데이터·선택·필터는 세션 소유라 생존한다. 구 T1 스위치 가드는 파기 자체가 사라져 함께
     죽었고(백엔드 `_do_select_job` 은 더 이상 needs_confirm 을 내지 않는다), 여기 남아 있던
     확인 왕복 분기도 함께 걷는다 — 죽은 가드 코드는 "이 전이는 파괴적"이라는 거짓 신호이자,
     되살아난 백엔드 분기를 소리 없이 받아 주는 통로다. 남는 것은 단일 실행(switching)뿐:
     더블클릭이 두 왕복을 만들면 modal.js 재진입 가드가 정상 제스처에 오류성 경보를 띄운다
     (리뷰 #5). */
  let switching = false;
  async function selectJobGuarded(name) {
    /* 반환 = 전환 성사 여부(false=재진입 거절) — 편집 모드 이탈이 이 판정을 기다린다
       (PR-2 리뷰 F5: 취소는 무변화여야 한다). */
    if (switching) return false;
    switching = true;
    try {
      await Bridge.call(SCREEN, "select_job", { name });
      return true;
    } finally {
      switching = false;
    }
  }

  /* 「여는 중」 지연 표지(#217 R1) — 클릭 프레임에 즉시 서고 왕복이 끝나면 걷힌다. 좌 목록
     행에 있던 것을 **후보 카드·탐색 행이 승계**했다(F2 PR-B, 지도 §10.9 판정 E): 표면이
     죽어도 그 표면이 지던 경보는 승계처가 진다 — 아니면 큰 레지스트리에서 클릭이 아무 일도
     안 한 것처럼 보이는 시간이 되돌아온다. 라벨 통째 치환(구 몸통) 대신 표식 노드를 덧붙인다
     — 후보 카드는 이름·메타 두 span 구조라 textContent 를 갈면 카드가 무너진다. */
  function setJobOpening(btn, opening) {
    if (!btn) return;
    const MARK = "openingMark";
    if (opening) {
      if (btn.querySelector("." + MARK)) return;
      btn.setAttribute("aria-busy", "true");
      const mark = document.createElement("span");
      mark.className = MARK;
      mark.textContent = " · 여는 중…";
      btn.appendChild(mark);
      return;
    }
    btn.removeAttribute("aria-busy");
    const mark = btn.querySelector("." + MARK);
    if (mark) mark.remove();
  }

  /* 표지를 세운 채 전환한다 — 검색 디바운스 정산·Python 로드보다 먼저 표지가 서고, 정본
     판정은 select_job push 가 덮는다. 성사 여부를 그대로 돌려준다(호출측이 판정 소비). */
  async function selectJobWithMarker(btn, name) {
    setJobOpening(btn, true);
    try {
      await dz.flushPendingSearch();
      return await selectJobGuarded(name);
    } finally {
      if (btn && btn.isConnected) setJobOpening(btn, false);
    }
  }

  /* 이 작업을 세션에 열기 — 후보 카드 재클릭 무동작 가드와 동형.
     라이브러리에서 오는 경로는 `prefer_work`(§19.8 3분기 판정)를 타므로 여기로 오지 않는다.
     남는 소비처는 화면 안 진입과 외부 스크립트(캡처 하니스)다.
     이미 이 작업 세션이면 재구성하지 않고(진행 중 데이터 겨눔·행 선택·확인이 조용히 소실되지
     않게 — 리뷰 F1) 그대로 두고 화면만 전환한다. 아니면 겨눠 진입한다. */
  function openJob(name) {
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
    const fix = e.target.closest('[data-act="fix-mapping"],[data-act="fix-filename"]');
    if (fix) {
      openEditForRepair({
        entry_reason: "document_browser_repair",
        evidence: {
          "고칠 것": fix.dataset.act === "fix-filename" ? "파일 이름 규칙" : "필드 연결",
          "막힌 이유": ($("jobGate").textContent || "").trim(),
        },
        return_context: { surface: "data" },
      });
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
     아니라 제자리 모드 전환이 됐다). 확정·저장 후 「실행으로 돌아가기」로 세션 재개. */
  function openEditForRepair(context) {
    // #99-6 동형 방어(PR-5 리뷰 F4) — 셔틀 미로드의 동기 ReferenceError 는 조용한 무반응.
    // 성사 여부를 되돌려 준다(F6 PR-B) — deep-link 조준은 진입이 실제로 열렸을 때만 건다.
    if (!window.EditorEntry) {
      window.alert("편집 진입 구성 요소(EditorEntry)가 로드되지 않았습니다.");
      return Promise.resolve(false);
    }
    if (LAST && LAST.job_name) return EditorEntry.openGuarded(LAST.job_name, context);
    return Promise.resolve(false);
  }

  /* (구 doRelinkTemplate — 「선택한 작업」 존의 「템플릿 다시 연결…」 버튼 — 은 존과 함께
     사망했다(U2 §4 판정 A, #342). 흐름 자체는 relinkTemplateFor 가 승계한다: 같은 공용
     Relink.relinkTemplate + 같은 T1 무장 가드에, 입구만 경고 카드 클릭과 액션바 버튼으로
     바뀌었다.) */

  function wire() {
    // 데이터 존(테이블·열 패널·칩·스트립·전체 선택/해제·문서 레벨 닫기)은 팩토리 몫 배선.
    dz.wire();
    if (window.ResizeObserver && !mirrorResizeObserver) {
      mirrorResizeObserver = new ResizeObserver(measureMirrorCap);
      mirrorResizeObserver.observe($("jobMirror"));
    }
    // 문서 작업 후보 카드 클릭 = 작업 선택(§18.2 보존 전환 — 데이터·선택은 세션 소유라 생존).
    // 활성 후보 재활성화는 무시한다(#302 리뷰 P2): CSS pointer-events:none 은 키보드
    // (Enter/Space) 합성 클릭을 막지 못하고, 재선택은 vm 재생성 = ack·완주 담보·폴더의
    // 조용한 소실이라 무해하지 않다(탐색 면 재선택 no-op 과 대칭).
    $("jobCandidates").addEventListener("click", (e) => {
      // 별 = 정렬 메타만(§18.5) — 작업 선택이 아니다. 카드 안 중첩 버튼이라 먼저 가른다.
      const fav = e.target.closest("[data-fav]");
      if (fav) {
        toggleFavorite(fav.getAttribute("data-fav"),
                       fav.getAttribute("aria-pressed") === "true");
        return;
      }
      if (e.target.closest("[data-browse-open]")) { openBrowseSheet(e); return; }
      // 활성 카드 ⋮(판정 B) — 카드 안 중첩 버튼이라 선택 판정보다 먼저 가른다(별과 동형).
      const mbtn = e.target.closest("[data-cand-menu]");
      if (mbtn) { toggleCandMenu(mbtn); return; }
      const btn = e.target.closest("[data-cand]");
      if (!btn) return;
      // 경고 카드(판정 D) — 기본 클릭이 선택의 **대체**다. 활성+경고면 경고가 이기므로
      // 재클릭 무동작 가드(aria-pressed)보다 먼저 판정한다.
      if (btn.dataset.missing === "1") {
        relinkTemplateFor(btn.getAttribute("data-cand"));
        return;
      }
      if (btn.getAttribute("aria-pressed") !== "true") {
        // 지연 표지 승계(판정 E) — 큰 레지스트리에서 왕복이 길면 클릭이 아무 일도 안 한
        // 것처럼 보인다. 실패는 완료 존 log 로 재진술(조용한 무반응 금지).
        selectJobWithMarker(btn, btn.getAttribute("data-cand")).catch((err) =>
          log("작업 열기 실패: " + String((err && err.message) || err)));
      }
    });
    // 활성 카드 ⋮ 메뉴 — 행동은 PathTrack 문서 위임이 받으므로 여기는 닫기만 진다.
    $("jobCandMenu").addEventListener("click", (e) => {
      if (e.target.closest("[data-track-act]")) closeCandMenu();
    });
    // ⋮ 바깥 닫기(그룹 ⋮ 동형) — 캡처 클릭 억제 + 바깥 pointerdown + Escape.
    window.Popover.wireDismiss({
      isOpen: candMenuOpen,
      contains: (t) => !!(t.closest && (t.closest("#jobCandMenu") || t.closest("[data-cand-menu]"))),
      close: closeCandMenu,
    });
    // 문서 탐색 면(§18.6) — 탭·검색은 Python 판정 왕복, 행 클릭은 명시 작업 선택.
    $("jobBrowseClose").addEventListener("click", () => window.Modal.close("jobBrowseSheet"));
    $("jobBrowseTabs").addEventListener("click", (e) => {
      const t = e.target.closest("[data-browse-tab]");
      if (!t || t.getAttribute("aria-selected") === "true") return;
      const tab = t.getAttribute("data-browse-tab");
      Intent.chained("browse", () =>
        Bridge.call(SCREEN, "browse_tab", { tab })
          .catch((err) => log("탭 전환 실패: " + String((err && err.message) || err))));
    });
    // 검색은 타이핑마다 왕복하지 않고 짧게 모은다(데이터 존 검색 관례) — 판정은 여전히
    // Python 이 지금 내린다(JS 가 목록을 자체 필터하면 이중 진실).
    let browseTimer = null;
    $("jobBrowseQuery").addEventListener("input", (e) => {
      const text = e.target.value;
      if (browseTimer) window.clearTimeout(browseTimer);
      browseTimer = window.setTimeout(() => {
        browseTimer = null;
        // 같은 체인에 태워 **도착 순서**를 고정한다(리뷰 5R P2): 큰 레지스트리에서 한 응답이
        // 디바운스보다 느리면 두 요청이 겹치고, 늦게 온 옛 응답이 새 검색 결과를 되돌린다
        // (입력값만 지키는 포커스 가드로는 결과-문안 불일치가 남는다). 탭 전환도 같은 체인:
        // 탭과 검색은 한 목록의 두 축이라 서로 앞질러도 같은 어긋남이 난다.
        Intent.chained("browse", () =>
          Bridge.call(SCREEN, "browse_query", { text })
            .catch((err) => log("검색 실패: " + String((err && err.message) || err))));
      }, 180);
    });
    $("jobBrowseRows").addEventListener("click", (e) => {
      const pick = e.target.closest("[data-browse-pick]");
      if (!pick || pick.getAttribute("aria-pressed") === "true") return;
      // 선택은 명시 사건이다(§18.6) — 면을 닫고 세션 패널로 돌려보낸다(데이터는 생존).
      const name = pick.getAttribute("data-browse-pick");
      // 포커스 착지를 **명시로** 예약한다(리뷰 1R P2): 면을 닫는 전이와 선택 재렌더가 겹쳐
      // 모달이 기억한 복귀 트리거(출구 버튼)가 교체·해제되므로, Modal 의 복귀는 건너뛰어지고
      // 포커스가 숨은 검색 입력이나 body 로 떨어진다. 착지점은 방금 고른 작업의 카드 —
      // 사용자의 다음 관심이 거기 있고, 없으면 다시 탐색을 열 출구로 내린다.
      // **성사 뒤에만 닫는다**(리뷰 2R P2): 가드 취소·Python 거절(생성 중 등)에서 면을 먼저
      // 닫으면 사용자는 오류만 받고 찾던 문맥을 잃는다. 성사 시점엔 Python 의 push·render 가
      // 이미 끝나 있으므로(3R P2) 닫은 **직후** 실 DOM 을 찾아 포커스를 세운다 — 예약을
      // 남기지 않으니 무관한 뒤 렌더를 흔들 유령도 없다.
      // 선택도 **같은 체인**에 태운다(리뷰 P1): 느린 browse_query·browse_tab 이 아직 돌고
      // 있으면 그 응답이 선택 뒤에 도착해 패널·후보 스냅샷을 옛 상태로 되돌린다. 탐색 표면의
      // 모든 왕복이 한 줄에 서야 화면이 마지막 사용자 행동을 반영한다.
      const gen = browseOpenGen;                  // 이 클릭이 속한 개폐 세대
      Intent.chained("browse", () =>
        gen !== browseOpenGen ? null :            // 그 사이 닫혔다 = 취소된 의도(조용히 접는다)
        selectJobWithMarker(pick, name).then((ok) => {
          if (!ok) return;                      // 가드 취소·거절 = 면 유지(문맥 보존)
          browsePickedName = name;              // 착지 사유 표식 — 결정은 onClose 단일 지점
          window.Modal.close("jobBrowseSheet");
        }).catch((err) => {
          log("작업 열기 실패: " + String((err && err.message) || err));
        }));
    });
    $("jobOrderSel").addEventListener("change", onOrderChange);
    $("jobDataExpand").addEventListener("click", openJobDataSheet);
    $("jobRangeApply").addEventListener("click", applyRangeDraft);
    // 취소도 닫기와 같은 관문을 지난다(가드 → onClose 가 초안을 버린다) — 출구마다 다른
    // 경로를 만들면 그중 하나는 가드를 안 탄다.
    $("jobRangeCancel").addEventListener("click", () => window.SurfaceSheet.close("dataSheet"));
    $("jobRangeSelectedOnly").addEventListener("click", () => {
      const d = draftState();
      Bridge.call(SCREEN, "set_selected_only", { value: !(d && d.selected_only) });
    });
    // 미리보기 드로어(F5) — 열기·이동·승인·편집 진입. 자리는 Python 이 서수로 소유하므로
    // 웹은 **방향만** 보낸다(레코드 index 를 되돌려주지 않는다, 판정 M).
    $("jobPreviewOpen").addEventListener("click", openPreview);
    $("previewClose").addEventListener("click", () => window.Modal.close("previewModal"));
    $("previewPrev").addEventListener("click", () =>
      Bridge.call(SCREEN, "preview_move", { delta: -1 }));
    $("previewNext").addEventListener("click", () =>
      Bridge.call(SCREEN, "preview_move", { delta: 1 }));
    $("previewApprove").addEventListener("click", () => {
      Bridge.call(SCREEN, "preview_approve", {}).catch((err) =>
        log("확인을 저장하지 못했습니다: " + String((err && err.message) || err)));
    });
    // 거친 진입(「이 작업 편집」 — target 없음)은 존치하고, 행별·파일 이름 「수정」이
    // deep-link(§10.14.3)를 더한다. 면을 먼저 닫아 편집 호스트 위에 남의 모달이 떠 있지
    // 않게 한다(F2 PR-B 교훈).
    $("previewEdit").addEventListener("click", () => {
      window.Modal.close("previewModal");
      openEditForRepair({
        entry_reason: "preview_result",
        evidence: { "보고 있던 행": ($("previewPos").textContent || "").trim() },
        return_context: { surface: "preview", reopen_drawer: true },
      });
    });
    // 행별 「수정」 — 위임(행 DOM 은 push 재렌더가 다시 짓는다). 증거는 이 표면이 **본
    // 것**(Python 이 push 한 스냅샷 값)을 그대로 싣는다 — 편집기가 재계산하지 않는다.
    $("previewRows").addEventListener("click", (e) => {
      const btn = e.target.closest('[data-act="preview-fix"]');
      if (!btn) return;
      const field = btn.dataset.field;
      const row = (((LAST && LAST.preview) || {}).rows || [])
        .find((r) => r.name === field) || {};
      previewFix("binding/" + field, {
        "보고 있던 행": ($("previewPos").textContent || "").trim(),
        "필드": field,
        "본 값": row.value || "(빈 값)",
      }).catch((err) => log("수정으로 이동하지 못했습니다: " + String((err && err.message) || err)));
    });
    $("previewFixFilename").addEventListener("click", () => {
      previewFix("filename/filenamePattern", {
        "보고 있던 행": ($("previewPos").textContent || "").trim(),
        "파일 이름": ($("previewFilename").textContent || "").trim(),
      }).catch((err) => log("수정으로 이동하지 못했습니다: " + String((err && err.message) || err)));
    });
    $("jobMirrorExpand").addEventListener("click", openJobConfirmSheet);
    $("jobMirrorCapstrip").addEventListener("click", (e) => {
      if (e.target.closest("[data-mirror-expand]")) openJobConfirmSheet(e);
    });
    $("jobConfirmSheetClose").addEventListener("click", () =>
      window.SurfaceSheet.close("jobConfirmSheet"));
    $("dataSheetClose").addEventListener("click", () => window.SurfaceSheet.close("dataSheet"));
    // 데이터·작업이 둘 다 없는 상태의 유일 출구(지도 §10.9 판정 C) — 데이터 없이 작업을
    // 보는 경로는 「문서 작업」이 흡수했고, 여기서는 그 흡수처를 가리키기만 한다(겨눔 없음:
    // 명시 선택은 저쪽 「문서 만들기에서 사용」이 `prefer_work` 로 낸다).
    $("jobPickInLibrary").addEventListener("click", () => window.Nav.go("library"));
    // 같은 출구가 「데이터는 있는데 쓸 작업이 0건」에도 선다(U2 §2.4). 후보 구획은 매 푸시
    // 다시 그려지므로 안정 컨테이너에 위임한다 — 버튼에 직접 걸면 첫 렌더에만 붙는다.
    $("jobCandidates").addEventListener("click", (e) => {
      if (e.target.closest("[data-cands-exit]")) window.Nav.go("library");
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
    // 액션바 재연결(#342 3R) — 도달 보장 축의 입구. 흐름은 경고 카드와 **한 몸통**이다.
    $("jobActionRelink").addEventListener("click", () => {
      if (!(LAST && LAST.job_name)) return;
      relinkTemplateFor(LAST.job_name);
    });
    $("jobGenBtn").addEventListener("click", async () => {
      // 두 실행 행동 다 **커밋**이다 — 무엇을 대상으로 도는지가 방금 누른 존 변이에 달렸다.
      // 존 발신은 ZONE_CHAIN 으로 서로의 순서를 지키지만 커밋은 그 체인 밖이라, 정산하지
      // 않으면 행 토글이 착지하기 전에 생성이 **옛 선택**으로 돌 수 있다(F6 8R P1).
      await window.Intent.settle(ZONE_CHAIN);
      // TXT 는 생성이 아니라 작업대 진입이다. 진입 자격 판정도 Python 이 하고(선택 0건·
      // 초안 열림·생성 중) 여기는 거절 사유를 재진술만 한다 — 조용한 무동작 금지.
      const key = (LAST && LAST.run_action && LAST.run_action.key) || "generate";
      if (key !== "workbench") { doGenerate(false); return; }
      Bridge.call(SCREEN, "open_workbench", {}).then((res) => {
        if (res && res.ok) { window.Nav.go("workbench"); return; }
        log((res && res.error) || "작업대를 열지 못했습니다.");
      });
    });
    $("jobGenCancel").addEventListener("click", async () => {
      const btn = $("jobGenCancel");
      btn.disabled = true;
      btn.textContent = "중단 요청됨…";
      await Bridge.call(SCREEN, "cancel_generation", {});
      log("중단 요청: 진행 중인 문서를 마친 뒤 미착수 건을 중단합니다.");
    });

    // ---- 결과 3태 구획의 행동 3종(F4) ----
    $("jobResultClose").addEventListener("click", () => {
      // 명시 파기 — 퇴장 한 줄을 남기지 않는다(§2.18 파기 대칭): 치우라는 행동이
      // 흔적을 남기면 반만 듣는 것이 된다. 자동 초기화(작업 전환·데이터 교체)만 적는다.
      resetGenResult();
      // 닫은 뒤 포커스는 **실 DOM 에 착지**한다(계약면 3). 다음 행동은 생성이지만 게이트가
      // 닫혀 있으면 그 버튼은 disabled 라 focus() 가 조용히 실패하고 body 로 떨어진다 —
      // 그때는 구획 자신(존 컨테이너)이 받는다: 사용자를 방금 있던 문맥에 남긴다.
      const btn = $("jobGenBtn");
      if (!btn.disabled) btn.focus(); else $("jobResultZone").focus();
    });
    // 「실패한 N건만 선택」 — 선택만 바꾸고 생성하지 않는다(판정 F). 실패 index 는 Python
    // 소유라 여기서 인덱스를 실어 보내지 않는다. 무동작(0건)은 사유를 말한다.
    $("jobResultFailedSel").addEventListener("click", async () => {
      const res = await Bridge.call(SCREEN, "select_failed", {});
      const n = (res && res.selected) || 0;
      log(n
        ? `실패한 ${n}건만 선택했습니다. 그대로 다시 생성하면 이 건만 만듭니다.`
        : "다시 만들 실패 건이 남아 있지 않습니다(데이터나 작업이 그사이 바뀌었습니다).");
    });
    // 파일 이름 규칙 수정 — 편집 진입은 공용 EditorEntry 단일 출처. F7 이 파일 이름을
    // **전용 탭**으로 승격했으므로 이제 그 탭으로 곧장 착지한다(F4 가 남긴 빚의 회수).
    $("jobResultRename").addEventListener("click", () => {
      if (!(LAST && LAST.job_name)) { log("작업이 선택돼 있지 않습니다."); return; }
      // 방어적 재확인(2R P2) — 이 버튼은 결과의 작업이 곧 열린 작업일 때만 뜨지만,
      // 렌더 사이의 전환 경합이 있으면 열린 작업을 겨눠 **남의 작업을 편집**하게 된다.
      // 겨눔 대상은 언제나 그 결과를 만든 작업이고, 어긋나면 열지 않고 사실을 말한다.
      const owner = LAST.last_run_job || LAST.job_name;
      if (owner !== LAST.job_name) {
        log(`이 결과는 '${owner}' 실행입니다. 지금 열린 작업이 달라 파일 이름 규칙을 열지 않았습니다.`);
        return;
      }
      if (!window.EditorEntry) { window.alert("편집 진입 구성 요소(EditorEntry)가 로드되지 않았습니다."); return; }
      const r = RESULT || {};   // 결과는 웹 소유 세션 상태다(Python 푸시가 덮지 않는다)
      EditorEntry.openGuarded(owner, {
        entry_reason: r.status === "failed" ? "run_failure" : "output_result",
        section: "filename",
        evidence: {
          "이 실행": (r.title || "").trim(),
          "사용한 판본": r.revisions
            ? `템플릿 r${r.revisions.template} · 연결 r${r.revisions.binding}` : "",
        },
        return_context: { surface: "result" },
      });
    });

    // 데이터 선택 = 단일 출구(재작성 F1) — 현재/고정한/다른 세 갈래가 한 면 안에서 갈리고,
    // 손실 가드는 대상이 정해진 직후 다이얼로그가 이 콜백으로 묻는다(지도 §10.7.2 D).
    $("jobBtnPickData").addEventListener("click", () => {
      DataPicker.open({
        screen: SCREEN,
        current: currentDataDescriptor(),
        confirmSwap: confirmDataSwapIfArmed,   // 데이터 재겨눔 = T1 동류 파괴 전이
        onLoaded: (label) => log(`데이터 불러옴: ${label}`),
      });
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
  // refreshList 는 편집 저장 seam(editor.js doSave 가 소비). 구 두 모드 seam 3종은
  // 편집기가 자기 화면으로 나가며 사망했다(F7 판정 N) — 되돌릴 모드가 없다.
  // renderResult 는 결과 3태 구획의 유일한 입구다(F4) — 실앱 게이트가 Python 이 내는
  // 결과 dict 를 그대로 흘려 태·강등·증거 접힘이 실 WebView2 에서 서는지 되읽는다.
  window.JobScreen = {
    init, overwriteBody, guardBody, confirmDataSwapIfArmed, openJob,
    refreshList,
    openJobConfirmSheet, openJobDataSheet, openBrowseNeedsAction,
    // 미리보기 복귀 seam(1R P2) — 편집기가 「미리보기로 돌아가기」라고 적은 이상 실제로
    // 그 면으로 돌려보내야 한다. 열기 절차(왕복·성사 뒤 열기·포커스)는 여기 하나가 소유한다.
    openPreview,
    renderResult, markResultStale,
  };
})();
