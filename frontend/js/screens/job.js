/* 「문서 만들기」 화면 — 세션 패널 하나(R-flow #90 · 재작성 R1·F7).
   세션 패널 = v6 `screen-data` 2열(좌 `.dg-main` 현재 데이터·거울·결과 / 우 `.dg-side`
   문서 선택기·생성 준비 — 구 「선택한 작업」 존은 U2 §4 판정 A 로 사망, 활성 카드와
   액션바 이름이 승계. 구 4존 znum 은 이 형상으로 대체),
   정의 편집은 자기 화면(#scr-editor, 재작성 F7)으로 나갔다 — 이 화면은 실행 세션 하나다.
   좌 master 작업 목록은 F2 PR-B 에서 사망했다(지도 §10.9): 작업 선택은 데이터가 준비된 뒤
   후보 side-card·문서 탐색 면이 지고, 목록 관리 6동사와 데이터 없는 상태의 작업 찾기는
   「문서 작업」 라이브러리가 승계했다.
   안정 DOM(index.html) + Python 이 __push('job', snapshot) 로 값만 채운다(run/txt 패턴).
   표현 계층(거울 테이블·재진술 블록·게이트·진행/로그)만 여기서 만든다 — VM 로직 아님(링2 대체, #87).
   덮어쓰기 확인은 공용 Modal.confirm의 수치 합성 본문으로 — 네이티브 다이얼로그 무사용이라 #86
   재유입 가드에 처음부터 부합한다. 존 배치(헤더·데이터·본문·완료)는 여기서 안정 DOM 에 값을 채운다. */
import { escHtml } from "../esc.js";
import { Modal } from "../modal.js";
import { Preserve } from "../preserve.js";
import { Guard } from "../guard.js";

/* R4-01 뒤 이 파일은 #416으로 넘길 실행·결과·미리보기 remainder만 소유한다. */
export function createJobScreen({
  Bridge, Nav, EditorScreen, PathTrack, EditorEntry, JobDataCoordinator, JobRelinkFlow,
}) {
  const SCREEN = "job";
  const $ = (id) => document.getElementById(id);
  let LAST = null;
  let generating = false;
  let lastSessionKey = null;  // 완료 존 세션 스코프 판정(결정 7) — 성분별 지문(U2 §2.18)
  /* (구 거울 테이블의 펼침·캡 상태 4종 — 이름 목록 펼침·캡 실측 — 은 표 없는 한 줄 재편(U2 §2.13)과 함께 사망했다.) */
  /* 패널 모드(결정 39·40)는 편집기가 몰입 표면이 되며 사망했다(재작성 F7 판정 N):
     정의 편집은 자기 화면(#scr-editor)에 살고, 이 화면은 실행 세션 하나만 그린다.
     「이 화면이 안 보인다」는 판정은 이제 `.scr.on` 하나로 충분하다. */

  const esc = escHtml;  // 공유 이스케이퍼(esc.js)
  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    if (s && s.progress) { renderProgress(s.progress); return; }  // 진행 델타(경량)
    Preserve.around(() => {  // 매핑/레코드 포커스·스크롤 보존(#28)
      LAST = s;
      const hasJob = !!s.has_job;
      syncModeDisplay(hasJob);
      // 데이터-우선(§18.2): 세션 4존은 작업 미선택에도 산다 — 스냅샷이 vm-None 상태를
      // 전 키 유효값으로 방출하므로(prework 게이트·빈 거울·후보) 렌더러는 무조건 돈다.
      renderActiveIdentity(s);
      renderPreflight(s);
      renderMirror(s);
      renderPreview(s);
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
      // 데이터 성분은 **정체**이지 표시 라벨이 아니다(#363 리뷰 P2): `data_source_label`
      // 은 「파일: <basename>」이라 같은 이름의 다른 파일·같은 통합문서의 다른 시트·같은
      // 경로의 바뀐 내용이 전부 같은 문자열이고, 그러면 §2.18 의 「데이터 교체 = 초기화」가
      // 그 경우들에서 서지 않아 결과가 **남의 데이터에 붙은 채** 강등도 아닌 상태로 남는다.
      // 값은 Python 이 낸 마운트 세대(`data_mount`) 하나 — 표면이 경로·시트로 정체를 다시
      // 조립하지 않는다(같은 상태를 두 층이 판정하지 않게, 그리고 경로 정체성 축은 §5.3 이
      // 재편 중이다).
      data: s.data_mount,
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
      const exit = resultExitLine(RESULT, (LAST && LAST.last_run_job) || "");
      resetGenResult();
      if (exit) log(exit);
      return;
    }
    if (prev.job !== next.job || prev.out !== next.out ||
        prev.sel !== next.sel || prev.rules !== next.rules) {
      markResultStale();
    }
  }

  /* 퇴장 한 줄 합성 — 「'발주요청서' 10개 성공 · 2개 실패 — C:\…\Results」.

     **수치를 여기서 다시 조립하지 않는다**(#363 리뷰 P2). 종전엔 `total` 을 「N건 생성」
     으로 적었는데 그 값은 **대상 수**이지 만들어진 수가 아니다: 12건 배치를 첫 건 전에
     취소하면 실제 생성 0건인데 「12건 생성」이라고 말했다. 결과 구획은 그 직후 초기화되므로
     **그 거짓 진술이 유일하게 남는 흔적**이 된다(confirm-or-alarm 정면).

     그래서 수치 몸통은 Python 이 낸 **퇴장 요약**(`exit_summary`)을 그대로 쓴다.
     구획 제목(`title`)이 아닌 이유(#363 2차 리뷰): 제목은 구획 **머리**라 일부러 짧아
     취소 갈래가 실패 수를 접고 `failed` 태가 수치를 통째로 생략한다 — 화면에서는 옆의
     요약·실패 행이 그것을 말하므로 손실이 아니지만, 결과가 초기화된 **뒤**에는 그 옆이
     없다. 손실 함수를 표면에서 되메우면 수치를 두 층이 조립하게 되므로, 목적이 다른
     합성기를 Python 에 하나 더 두고 여기서는 고르기만 한다.

     거절(rejected)·진행(running) 태는 생성 자체가 없어 적을 것이 없다(빈 문자열 —
     그 결과들은 `exit_summary` 를 애초에 싣지 않는다).
     「결과 닫기」(명시 파기)는 이 경로를 타지 않는다 — 치우라는 행동이 흔적을 남기면
     반만 듣는 것이 된다(§2.18 파기 대칭).

     **순수 합성기**다(인자만 읽는다): 실앱 게이트가 태별 산출을 되읽어 문안 드리프트를
     막는다(overwriteBody·guardBody 와 같은 자리). */
  function resultExitLine(r, owner) {
    // 생성이 아닌 태(진행·거절)만 조용하다 — 적을 실행이 애초에 없다.
    if (!r || r.running || r.rejected) return "";
    const who = owner ? `'${owner}' ` : "";
    const dir = r.out_dir ? ` — ${r.out_dir}` : "";
    // 요약 없는 **실행 결과**는 조용히 넘기지 않는다: 이 줄이 유일한 흔적이라 침묵하면
    // 소멸 자체가 흔적 없이 사라진다(§2.18 이 이 줄을 세운 이유가 그것이다). 수치를
    // 지어내지 않고 **모른다고 적는다** — 「원인 진단 미연결」과 같은 정직 강등이다.
    const body = r.exit_summary || "생성 결과가 세션에서 물러났습니다(수치 요약 없음)";
    return `${who}${body}${dir}`;
  }

  /* ---- 세션 표면 동기화 ---- */
  function syncModeDisplay(hasJob) {
    // (구 거울 펼침 면(2 pane 확인 면)의 강제 닫기는 면 사망과 함께 걷혔다 — U2 §2.13.
    //  확인 면(#previewSheet)의 개폐는 Python 소유 `preview.open` 이 지고, 작업 전환은
    //  백엔드 `_do_select_job` 이 preview_close 로 닫는다. 데이터 면(dataSheet)은 데이터-
    //  우선(§18.2)이라 작업 미선택에도 산다 — 렌더마다 닫지 않는다(리뷰 5R).)
    void hasJob;
    // 데이터-우선: 세션 4존·액션바는 상시 — 작업 미선택에도 데이터 존이 진입점이다(§18.2).
    // 구 편집 모드 은닉(결정 39)은 편집기가 자기 화면으로 나가며 사라졌다(F7 판정 N).
    $("jobZones").style.display = "";
    $("jobActionBar").style.display = "";
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

  /* ---- 본문 존 = 표 없는 한 줄(U2 §2.13) ----
     구 거울 테이블(필드 채움 표 + 미입력 행 클릭 토글)은 필드축 ack 폐기와 함께 죽었다 —
     값을 말하는 표면은 확인 면(#previewSheet) 하나다. 여기 남는 것은 빈 값 표지·이름
     건수·확인 면 출구 한 줄과, danger 차단 배너(드리프트·미해소 토큰 — 같은 자리, 같은
     형상, 결정 36·S9)뿐이다. */
  /* 한 줄과 배너는 **다른 자리**다: 배너만 innerHTML 로 교체되고 한 줄은 안정 DOM 에 값만
     채운다(확인 면 트리거가 재렌더로 교체되면 복귀 초점이 끊긴다 — #364 리뷰 P2). */
  function showMirrorBanner(host, html) {
    host.innerHTML = html;
    $("jobMirrorLine").hidden = true;
  }

  function showMirrorLine(host, html) {
    host.innerHTML = "";
    $("jobMirrorSummary").innerHTML = html;
    $("jobMirrorLine").hidden = false;
  }

  function renderMirror(s) {
    const host = $("jobMirror");
    // TXT 는 이 존이 **없는 축**이다 — 존을 통째로 걷는다. 남겨 두면 빈 상태 문안이 행을
    // 다 고른 뒤에도 그대로 서서, 따라 해도 아무 일이 없는 막다른 지시가 된다(리뷰 6R).
    const zone = $("jobMirrorZone");
    if (zone) zone.style.display = isCopyWork(s) ? "none" : "";
    const drift = s.drift || [];
    if (drift.length) {
      // danger = 차단 배너 + 상시 행동 링크(막다른 경보 금지 — 경보 어포던스는 숨지 않는다).
      showMirrorBanner(host,
        `<div class="mir-drift" role="alert">` +
        `<p>템플릿 구조가 확정 매핑과 달라져 문서를 생성할 수 없습니다. ` +
        `어긋난 필드: <b>${esc(drift.join(", "))}</b>.</p>` +
        `<button class="btn sm" data-act="fix-mapping" data-busy-lock>편집에서 매핑 확정…</button>` +
        `</div>`);
      return;
    }
    // 미해소 파일명 토큰(#128) — **드리프트와 같은 danger 자격**이라 같은 자리에서 같은
    // 형상으로 발화한다(배너 소관은 드리프트·토큰 둘 다).
    const nameTokens = s.name_tokens || [];
    if (nameTokens.length) {
      const toks = nameTokens.map((t) => `{{${t}}}`).join(", ");
      showMirrorBanner(host,
        `<div class="mir-drift" role="alert">` +
        `<p>파일명 패턴의 토큰을 채우지 못해 문서를 생성할 수 없습니다. ` +
        `남는 토큰: <b>${esc(toks)}</b>.</p>` +
        `<button class="btn sm" data-act="fix-filename" data-busy-lock>편집에서 파일명 패턴 고치기…</button>` +
        `</div>`);
      return;
    }
    const n = s.selected_count || 0;
    if (!s.has_job || !s.has_data || !n) {  // 선택 0(또는 미겨눔) = 생성될 문서 없음
      // 트리거는 그대로 두고 문안만 바꾼다 — 가용성은 `setBusy` 단일 지점이 정한다
      // (`can_open` 이 false 라 비활성). 자리를 없애면 안정 복귀점도 함께 사라진다.
      showMirrorLine(host, `<span class="mirempty muted capnote">행을 선택하면 생성 내용을 확인할 수 있습니다.</span>`);
      return;
    }
    // 한 줄: 빈 값 표지(정보 — 클릭 표적 아님) + 이름 건수 + 확인 면 출구(⤢).
    // 어느 필드가 비는지는 이름으로 지목하되 **값은 말하지 않는다**(C3 폐색의 요점).
    const blanks = s.blank_fields || [];
    const blankBit = blanks.length
      ? `<span class="mir-blank-flag">빈 값 <b>${blanks.length}필드</b>(${blanks.map(esc).join("·")})</span>`
      : `빈 값 없음`;
    showMirrorLine(host, `${blankBit} · 이름 <b>${n}건</b>`);
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
    // 「빈 값 있는 건만 보기」(U2 §2.13) — 상태는 Python 소유라 스냅샷을 되읽는다
    // (낙관 토글 없음, #215 동류). 가용성(0건 비활성)은 setBusy 단일 지점이 정한다.
    $("previewBlankOnly").setAttribute("aria-pressed", p.blank_only ? "true" : "false");
    // 이름 계획 한 줄(U2 §2.13) — 구 인라인 재진술의 파일 이름 목록이 접힌 자리. 개별
    // 이름은 ‹ › 훑기(파일 이름 칸)가 말하고, 여기는 집합(건수·착지 폴더)만 말한다.
    $("previewNamePlan").textContent =
      `${p.total || 0}건 · 저장 폴더: ${s.out_dir || "미지정"}`;
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
    Modal.close("previewSheet");
  }

  async function openPreview(e, opts) {
    const o = opts || {};
    // 복귀 트리거는 **실제 클릭된 버튼**으로 푼다(#364 리뷰 P2): 본문 존 한 줄의
    // 「생성 값 미리보기 ⤢」는 위임 핸들러(`#jobMirror` 컨테이너)를 타므로 `currentTarget`
    // 이 포커스 불가능한 div 다 — 그대로 넘기면 시트를 닫은 키보드 사용자의 초점이
    // 위임 클릭이면 실제 버튼을, 복귀 호출이면 안정 액션바 버튼을 포커스 좌표로 쓴다.
    const trigger = e?.target?.closest?.("button") || $("jobPreviewOpen");
    // 성사 뒤에만 연다(§9.3 4행 상속): 거절되면(생성 중·초안 열림·선택 0건) 면을 띄우지
    // 않는다 — 열어 놓고 실패를 말하면 무엇을 미리보는 중인지가 거짓이 된다.
    // `at` = deep-link 복귀의 같은 자리(§10.15.15 판정 C) — 값은 Python 이 push 한
    // preview.pos 의 왕복이고 Python 이 클램프한다. 리터럴 payload(정적 가드 판독 대상).
    try {
      await JobDataCoordinator.current().flushPendingEdits();   // 예약된 편집이 뒤늦게 착지해 자리를 흔들지 않게
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
    Modal.open("previewSheet", {
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
    Modal.close("previewSheet");   // 편집 호스트 위에 남의 모달 금지(F2 PR-B 교훈)
    const opened = await openEditForRepair({
      entry_reason: "preview_result",
      target,
      evidence,
      return_context: { surface: "preview", reopen_drawer: true, preview_index: at },
    });
    // 착지 조준은 편집기 소유(스크롤·포커스) — 진입 성사 뒤에만 겨눈다.
    if (opened && EditorScreen && EditorScreen.aimAt) {
      EditorScreen.aimAt(target);
    }
  }

  /* (구 거울 행 합성·클릭형 확인 토글(UD-19)은 필드축 ack 폐기와
     함께 사망 — U2 §2.13. 빈 값 표지는 정보로 남고 클릭 표적만 사라졌다.) */

  /* (열 필터 패널·필터 테이블·칩 줄·스트립·검색 정산은 datazone.js 팩토리로 이동 — PR-2a
     추출. 표면 계약·리뷰 결정 주석은 팩토리가 소유한다. 화면 고유 popover 인 행/그룹 ⋮
     메뉴의 바깥-닫기는 공용 Popover.wireDismiss 주입(wire) — 기제 단일 출처, 상태는
     표면별 인스턴스라 패널 몫과 교차하지 않는다.) */

  /* ---- 게이트 · 재진술 블록(상시, 결정 36 D1-B) — 선택 유래 + 산출 요약.
     이미 보이는 것을 재검증하지 않으므로 모달이 아니라 상시 블록이다.
     구 파일 이름 목록(표본+「외 N건 펼치기」)은 확인 면의 「이름 계획」 한 줄로 이주했다
     (U2 §2.13) — 값·이름을 말하는 표면은 확인 면 하나다. 여기 남는 것은 수치·경로뿐이다.
     선택 유래(결정 4) = 집합 비교 무상태 판정(restate.origin): 정의-유래면 정의줄을
     재진술하고, 이탈이면 매치/밖 수치를 병기한다(S4 델타). */
  function renderRestate(s) {
    const box = $("jobRestate");
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
    // 선택 유래 문안(결정 4·S4) — 정의-유래 = 정의줄 재진술이 「전체 선택」의 담보.
    // 직접 선택 문안은 가드 모달과 공유 합성기(selectionLine, 리뷰 #9)로 단일 출처.
    const selLine = (rs.origin === "definition")
      ? `정의 매치 전체 ${sel.length}행: ${esc((s.filter && s.filter.definition) || "")}`
      : esc(selectionLine(sel.length, rs.filter_active, rs.in_def, rs.extra));
    // 산출 재진술은 **매체마다 다른 사실**이다(리뷰 6R). TXT 는 파일을 만들지 않으므로
    // 「문서 N건 · 저장 폴더」는 거짓이다 — 이 버튼이 실제로 하는 일(작업대에서
    // 레코드마다 검토·복사)을 그대로 말한다.
    box.innerHTML = isCopyWork(s)
      ? `<span class="dl">선택</span><span>${selLine}</span>` +
        `<span class="dl">복사</span><span>작업대에서 ${sel.length}건을 한 건씩 검토하고 ` +
        `복사합니다. 파일은 만들지 않습니다.</span>`
      : `<span class="dl">선택</span><span>${selLine}</span>` +
        `<span class="dl">생성</span><span>문서 ${sel.length}건 · 저장 폴더: ${esc(s.out_dir || "미지정")}</span>`;
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
    // 이름 없는 게이트(저장 폴더·이어채우기 등 hwpx warn 갈래)만 자리로 유추한다.
    // 데이터·행이 안 갖춰졌으면 그게 먼저다(prework_gate 서열과 같은 걸음).
    const noRows = !s.has_data || !(s.selected_count > 0);
    if (!s.has_job) return noRows ? GATE_ZONE.no_data : GATE_ZONE.no_job;
    if (noRows) return GATE_ZONE.no_data;
    // 이름 없는 warn 의 **마지막 소비자였던 필드축 ack 게이트가 폐기됐다**(U2 §2.13) —
    // 남는 것(저장 폴더·이어채우기)은 본문 축이 아니라 그 자리를 가리키면 거짓 지목이
    // 된다. `drift`·`name_tokens` 는 위 named 조회가 계속 「본문 확인」으로 보낸다:
    // 그 danger 배너는 재편 뒤에도 그 존에 산다(사망한 것은 값 표·클릭형 행이다).
    return "";
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
    [$("scr-job"), $("previewSheet")].forEach((root) => {
      root.querySelectorAll("[data-busy-lock]").forEach((el) => { el.disabled = busy; });
    });
    // 초안이 열려 있으면 생성은 닫혀 있다(§10.11.2 계약면 2 — 잠금은 DOM 이 아니라 상태가
    // 진다). Python 도 같은 이유로 거절하지만, 버튼이 눌리는 척하면 거절 문구가 사후 통보가
    // 된다. 모달에 가려 물리적으로 못 누르는 것과 잠긴 것은 다른 사실이다.
    $("jobGenBtn").disabled = busy || !(LAST && LAST.gate && LAST.gate.enabled);
    // 저장 폴더는 작업 속성(기본 = 템플릿/Results) — 작업 미선택에서 고르게 두면 작업
    // 선택이 기본값으로 조용히 덮어써 선택이 증발한다(#302 리뷰 P2). busy-lock 일괄 복원이
    // 되살리지 않도록 여기(렌더 말미 단일 지점)서 판정한다.
    // TXT 는 저장 폴더 축이 없으므로 피커도 없다(행 자체가 숨지만 잠금은 DOM 이 아니라
    // 상태가 진다 — 일괄 복원이 되살리지 않게 여기서 못박는다).
    $("jobBtnPickFolder").disabled =
      busy || !(LAST && LAST.has_job) || isCopyWork(LAST);
    // 미리보기 버튼들도 여기서 정한다(F5) — 위 일괄 복원이 renderPreview 의 판정을 되살린다.
    // 열기는 선택이 있을 때, 이동은 경계에서 멈춘다(순환하지 않으므로 끝에서 비활성).
    // 경계는 Python 이 낸다(can_prev·can_next — §2.13): 「빈 값 있는 건만 보기」가 켜지면
    // 경계가 그 건들의 처음·끝으로 바뀌는데, 표면이 pos/total 로 재유도하면 판정이 갈린다.
    const pv = (LAST && LAST.preview) || {};
    // 확인 면 출구는 둘(액션바·본문 존 한 줄)이고 **가용성 판정은 하나**다 — 두 자리가
    // 각자 정하면 한쪽만 열린 채 남는다. 한 줄의 버튼은 안정 DOM 이라 여기서 잠근다.
    $("jobPreviewOpen").disabled = busy || !pv.can_open;
    $("jobMirrorPreviewOpen").disabled = busy || !pv.can_open;
    $("previewPrev").disabled = busy || !pv.total || !pv.can_prev;
    $("previewNext").disabled = busy || !pv.total || !pv.can_next;
    // 「빈 값 있는 건만 보기」 — 빈 값 건이 0이면 한정할 대상이 없어 비활성(무동작 토글 금지).
    $("previewBlankOnly").disabled = busy || !pv.blank_count;
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
    await JobDataCoordinator.current().flushPendingEdits();
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
        const ok = await Modal.confirm({
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
  const selectionLine = Guard.selectionLine;

  /* 손실 열거는 **실제로 파기되는 집합**과 일치해야 한다(지도 §10.7.3 감사) — 과경고도
     누락도 거짓말이다. 데이터 전환이 파기하는 것: ①선택(0건 재생성) ②필터 정의(재생성).
     구 ③「빈 값 확인」 성분은 필드축 ack 폐기(U2 §2.13)로 걷었다 — 확인이라는 상태가
     없어졌으므로 남겨 두면 가드가 존재하지 않는 것을 잃는다고 말한다. 자동 조준 재진술은
     사라지는 게 아니라 새 데이터가 스스로를 재진술하며 **대체**되고, 생성 결과·로그는
     처분 계약(§2.18)이 따로 지므로 열거하지 않는다. 필터 정의는 직전 슬롯에 스태시되지만
     재적용은 **소스 일치**를 요구하므로(`_reapply_available` 3연언) 다른 데이터로 가면
     지금 자리에선 되살릴 수 없다 — 그 조건까지 말해야 "사라진다"가 정확해진다. */
  function guardBody(g, verbPhrase) {
    const lost = [selectionLine(g.sel_count, g.filter_active, g.in_def, g.extra)];
    if (g.filter_parts > 0) lost.push(`필터 정의(${g.filter_parts}개 조건)`);
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
    return Modal.confirm({
      title, body: guardBody(g, verbPhrase),
      confirmLabel, cancelLabel: "취소",
    });
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
  }

  /* danger(구조 드리프트) 수리 동선 — 이 작업을 **패널 편집 모드**에 열어 매핑을 재확정한다
     (공용 EditorEntry.openGuarded: 미저장 정의 확인 후 모드 전환 — 에디터 흡수로 화면 이동이
     아니라 제자리 모드 전환이 됐다). 확정·저장 후 「실행으로 돌아가기」로 세션 재개. */
  function openEditForRepair(context) {
    // #99-6 동형 방어(PR-5 리뷰 F4) — 셔틀 미로드의 동기 ReferenceError 는 조용한 무반응.
    // 성사 여부를 되돌려 준다(F6 PR-B) — deep-link 조준은 진입이 실제로 열렸을 때만 건다.
    if (!EditorEntry) {
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

  /* R4-01 임시 실행 remainder 배선. 읽기·탐색 이벤트는 React가 소유하므로 이 목록에
     들어오지 않는다. #416이 실행 표면을 React로 옮기면 이 함수와 파일을 함께 제거한다. */
  function wireRun() {
    $("jobPreviewOpen").addEventListener("click", openPreview);
    $("previewClose").addEventListener("click", () => Modal.close("previewSheet"));
    $("previewPrev").addEventListener("click", () =>
      Bridge.call(SCREEN, "preview_move", { delta: -1 }));
    $("previewNext").addEventListener("click", () =>
      Bridge.call(SCREEN, "preview_move", { delta: 1 }));
    $("previewApprove").addEventListener("click", () => {
      Bridge.call(SCREEN, "preview_approve", {}).catch((err) =>
        log("확인을 저장하지 못했습니다: " + String((err && err.message) || err)));
    });
    $("previewEdit").addEventListener("click", () => {
      Modal.close("previewSheet");
      openEditForRepair({
        entry_reason: "preview_result",
        evidence: { "보고 있던 행": ($("previewPos").textContent || "").trim() },
        return_context: { surface: "preview", reopen_drawer: true },
      });
    });
    $("previewRows").addEventListener("click", (event) => {
      const button = event.target.closest('[data-act="preview-fix"]');
      if (!button) return;
      const field = button.dataset.field;
      const row = (((LAST && LAST.preview) || {}).rows || [])
        .find((entry) => entry.name === field) || {};
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
    $("previewBlankOnly").addEventListener("click", () => {
      const on = $("previewBlankOnly").getAttribute("aria-pressed") === "true";
      Bridge.call(SCREEN, "preview_blank_only", { value: !on }).catch((err) =>
        log("빈 값 건만 보기를 바꾸지 못했습니다: " + String((err && err.message) || err)));
    });
    $("jobMirror").addEventListener("click", onMirrorClick);
    $("jobMirrorPreviewOpen").addEventListener("click", openPreview);
    $("jobActionRelink").addEventListener("click", () => {
      if (LAST && LAST.job_name) JobRelinkFlow.current().relinkTemplateFor(LAST.job_name);
    });
    $("jobGenBtn").addEventListener("click", async () => {
      await JobDataCoordinator.current().flushPendingEdits();
      const key = (LAST && LAST.run_action && LAST.run_action.key) || "generate";
      if (key !== "workbench") { doGenerate(false); return; }
      Bridge.call(SCREEN, "open_workbench", {}).then((res) => {
        if (res && res.ok) { Nav.go("workbench"); return; }
        log((res && res.error) || "작업대를 열지 못했습니다.");
      });
    });
    $("jobGenCancel").addEventListener("click", async () => {
      const button = $("jobGenCancel");
      button.disabled = true;
      button.textContent = "중단 요청됨…";
      await Bridge.call(SCREEN, "cancel_generation", {});
      log("중단 요청: 진행 중인 문서를 마친 뒤 미착수 건을 중단합니다.");
    });
    $("jobResultClose").addEventListener("click", () => {
      resetGenResult();
      const button = $("jobGenBtn");
      if (!button.disabled) button.focus(); else $("jobResultZone").focus();
    });
    $("jobResultFailedSel").addEventListener("click", async () => {
      const res = await Bridge.call(SCREEN, "select_failed", {});
      const count = (res && res.selected) || 0;
      log(count
        ? "실패한 " + count + "건만 선택했습니다. 그대로 다시 생성하면 이 건만 만듭니다."
        : "다시 만들 실패 건이 남아 있지 않습니다(데이터나 작업이 그사이 바뀌었습니다).");
    });
    $("jobResultRename").addEventListener("click", () => {
      if (!(LAST && LAST.job_name)) { log("작업이 선택돼 있지 않습니다."); return; }
      const owner = LAST.last_run_job || LAST.job_name;
      if (owner !== LAST.job_name) {
        log("이 결과는 '" + owner + "' 실행입니다. 지금 열린 작업이 달라 파일 이름 규칙을 열지 않았습니다.");
        return;
      }
      const result = RESULT || {};
      EditorEntry.openGuarded(owner, {
        entry_reason: result.status === "failed" ? "run_failure" : "output_result",
        section: "filename",
        evidence: {
          "이 실행": (result.title || "").trim(),
          "사용한 판본": result.revisions
            ? "템플릿 r" + result.revisions.template + " · 연결 r" + result.revisions.binding : "",
        },
        return_context: { surface: "result" },
      });
    });
    $("jobBtnPickFolder").addEventListener("click", async () => {
      const result = await Bridge.pickOutputFolder(SCREEN);
      if (result === null) return;
      if (typeof result === "string" && result.startsWith("ERROR:")) {
        log("폴더 오류: " + result.slice(6).trim());
        return;
      }
      log("저장 폴더: " + result);
    });
  }
  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출.
     멱등·재시도 계약(N-06 §7): 성공 후 재호출은 추가 등록 0, 동시 호출은 같은 초기화를
     공유하고, 첫 initial 이 거절되면 다음 명시적 init 이 initial 만 다시 당긴다(이미 선
     listener·onPush 는 중복 설치하지 않는다). rejection 은 종전대로 호출자에게 전파. */
  let wired = false;
  async function init() {
    if (!wired) {
      wireRun();
      wired = true;
    }
    return undefined;
  }

  // overwriteBody·guardBody 는 순수 합성기 — 실앱 게이트가 합성 결과(수치·문안 배치)를
  // 되읽어 회귀를 막는다(파괴적 확인의 조용한 드리프트 금지 — RC-02 판과 가드 판 동형).
  // confirmDestructiveIfArmed 는 R4 job read의 데이터 재겨눔도 소비하는 단일 파괴 가드다.
  // 실앱 게이트가 이 승계 이름의 존재를 핀해 삭제 회귀를 잡는다.
  // refreshList 는 편집 저장 seam(editor.js doSave 가 소비). 구 두 모드 seam 3종은
  // 편집기가 자기 화면으로 나가며 사망했다(F7 판정 N) — 되돌릴 모드가 없다.
  // renderResult 는 결과 3태 구획의 유일한 입구다(F4) — 실앱 게이트가 Python 이 내는
  // 결과 dict 를 그대로 흘려 태·강등·증거 접힘이 실 WebView2 에서 서는지 되읽는다.
  const JobScreen = {
    init, overwriteBody, guardBody, resultExitLine, confirmDestructiveIfArmed, log,
    openPreview, renderResult, markResultStale,
    acceptFull: render,
    acceptProgress: renderProgress,
  };
  return JobScreen;
}
