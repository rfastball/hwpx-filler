/* 여러 작업 실행(matrix) 화면 — 브리지로 링1 MatrixRunViewModel·SelectionModel 과 왕복.
   목업 scr-matrix 이관(#14). 안정 DOM(index.html) + Python 이 window.__push('matrix', snapshot)
   로 값만 채운다(run 패턴). 표현 계층(작업별 3상태 배지·게이트 재진술·진행/로그)만 여기서
   만든다 — VM 로직 아님(링2 대체). 미입력 확인은 (작업, 필드) 단위. */
(function () {
  const SCREEN = "matrix";
  const $ = (id) => document.getElementById(id);
  let LAST = null;
  let generating = false;

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    if (s && s.progress) { renderProgress(s.progress); return; }  // 진행 델타(경량) — 로그 바닥고정, 보존 밖
    Preserve.around(() => {  // 작업/레코드 포커스·스크롤 보존(#28)
      LAST = s;
      renderJobs(s);
      renderData(s);
      renderBadges(s);
      renderRecords(s);
      renderGate(s);
      renderStatus(s);
      // 작업·데이터·선택이 바뀐 새 스냅샷 → 이전 일괄 생성 결과 무효화(#28, UD-10). run/txt 패턴.
      if (!generating) resetMxGenResult();
    });
  }

  /* 이전 일괄 생성 결과(요약·진행바·로그)를 기본 상태로 되돌린다 — 오래된 성공 잔존 방지(#28).
     생성 중(generating)엔 부르지 않는다. 완료 결과는 renderResult 가 직접 호출로 그리므로
     다음 사용자 변경(스냅샷) 전까지 유지된다. */
  function resetMxGenResult() {
    $("mxGenBar").style.width = "0%";
    const r = $("mxGenResult");
    r.textContent = "";
    r.className = "run-result";
    $("mxGenLog").textContent = "";
    logStarted = false;
  }

  /* 작업 다중선택 — 매 스냅샷마다 목록·선택을 그대로 반영(선택은 VM 이 이름으로 보유). */
  function renderJobs(s) {
    const host = $("mxJobList");
    const jobs = s.jobs || [];
    $("mxJobCount").textContent = `선택 ${s.selection_count}개`;
    if (!jobs.length) {
      host.innerHTML =
        `<div class="rec muted">저장된 작업이 없습니다 — 작업 에디터에서 작업을 먼저 만드세요.</div>`;
      return;
    }
    // 로케이트 버튼은 <label> 밖(#67) — 라벨 클릭 전달로 체크박스가 오토글되지 않게.
    host.innerHTML = jobs.map((j) =>
      `<div class="rec"><label style="display:flex;gap:var(--sp-8);align-items:center;flex:1">` +
      `<input type="checkbox" data-job="${esc(j.name)}"${j.selected ? " checked" : ""}>` +
      `<span class="rf">${esc(j.name)}</span></label>` +
      `${PathTrack.affordances(j.template_path, { only: ["reveal", "copy"] })}</div>`).join("");
  }

  function renderData(s) {
    // 소스 종류 병기 라벨("파일: x" / "등록 데이터: 이름", #26 #6) — 서버가 플래그에서 합성(K8).
    $("mxDataLabel").value = s.data_source_label || "";
    $("mxOutDir").value = s.out_dir || "";
    // 공통 데이터·저장 폴더 로케이트(#67) — run 화면(#outTrack) 미러, 위임은 pathtrack 전역.
    $("mxDataTrack").innerHTML = PathTrack.affordances(s.data_track_path);
    $("mxOutTrack").innerHTML =
      PathTrack.affordances(s.out_dir, { only: ["reveal", "copy"] });
  }

  /* 작업별 3상태 배지(ADR-B/E) — 작업 헤더로 묶고, 미입력만 클릭형(확인/철회 토글). */
  function renderBadges(s) {
    const host = $("mxFieldBadges");
    const sums = s.field_summaries || [];
    if (!sums.length) {
      host.innerHTML =
        `<span class="muted" style="font-size:12px">작업과 데이터를 선택하면 작업별 필드 채움 상태가 여기에 표시됩니다.</span>`;
      return;
    }
    host.innerHTML = sums.map((js) =>
      `<span class="mx-jobhead">[${esc(js.job_name)}]</span>` +
      (js.states || []).map((st) => badge(js.job_name, st)).join("")).join("");
  }

  function badge(job, st) {
    const nm = esc(st.name);
    const j = esc(job);
    if (st.state === "filled") return `<span class="fb fill">✓ ${nm}</span>`;
    if (st.state === "blank") return `<span class="fb blank">◦ ${nm} (비움)</span>`;
    if (st.state === "drift") return `<span class="fb drift">⚠ ${nm} — 매핑 재확정 필요</span>`;
    // missing(값 빔) — 클릭해 확인/철회. (작업, 필드) 단위로 겨눈다.
    if (st.acknowledged) {
      return `<span class="fb missing ack" data-job="${j}" data-f="${nm}" role="button" tabindex="0"
        title="다시 눌러 확인을 취소합니다(게이트가 다시 닫힙니다).">✓ ${nm} — 미입력 표시 예정</span>`;
    }
    return `<span class="fb missing" data-job="${j}" data-f="${nm}" role="button" tabindex="0">● ${nm} — 미입력 확인</span>`;
  }

  function renderRecords(s) {
    const host = $("mxRecList");
    const recs = s.records || [];
    $("mxSelCount").textContent = `선택 ${s.selected_count}/${s.record_count}`;
    if (!recs.length) {
      host.innerHTML =
        `<div class="rec muted">공통 데이터를 선택하면 사용할 행이 여기에 표시됩니다.</div>`;
      return;
    }
    host.innerHTML = recs.map((r) =>
      `<label class="rec"><input type="checkbox" data-i="${r.index}"${r.selected ? " checked" : ""}>` +
      `<span class="rf">${esc(r.label)}</span></label>`).join("");
  }

  function renderGate(s) {
    const g = s.gate || { enabled: false, level: "", text: "" };
    $("mxGenBtn").disabled = !g.enabled || generating;
    const gate = $("mxGenGate");
    gate.textContent = generating ? "" : g.text;
    gate.className = "muted";
    gate.style.color = g.level === "danger" ? "var(--a-danger)"
      : g.level === "warn" ? "var(--a-warn)" : "";
  }

  function renderStatus(s) {
    const pill = $("mxStatus");
    if (!s.selection_count) { pill.dataset.level = "idle"; pill.textContent = "작업 선택"; return; }
    if (!s.has_data) { pill.dataset.level = "idle"; pill.textContent = "데이터 선택"; return; }
    if (s.gate && s.gate.enabled) { pill.dataset.level = "ok"; pill.textContent = "생성 준비"; }
    else { pill.dataset.level = "warn"; pill.textContent = "확인 필요"; }
  }

  /* 진행 델타 — 진행바만 갱신(전체 재렌더 없음). */
  function renderProgress(p) {
    const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
    $("mxGenBar").style.width = pct + "%";
    const r = $("mxGenResult");
    r.className = "run-result";
    r.textContent = `생성 중… ${p.done}/${p.total}`;
  }

  /* ---- 로그 ---- */
  let logStarted = false;
  function log(msg) {
    const box = $("mxGenLog");
    const ts = new Date().toLocaleTimeString("ko-KR", { hour12: false });
    if (!logStarted) { box.textContent = ""; logStarted = true; }
    box.textContent += (box.textContent ? "\n" : "") + `[${ts}] ${msg}`;
    box.scrollTop = box.scrollHeight;
  }

  /* ---- 웹→Python 이벤트 ---- */
  /* busy 잠금 대상은 하드코딩 id 배열이 아니라 [data-busy-lock] 속성으로 선언한다 — 새
     컨트롤을 추가할 때 이 함수를 잊고 지나쳐도(#26 setBusy 누락 회귀) 속성만 붙이면
     자동으로 잠긴다(구조적 재발 방지, run.js 미러). */
  function setBusy(busy) {
    $("scr-matrix").querySelectorAll("[data-busy-lock]").forEach((el) => { el.disabled = busy; });
    $("mxGenBtn").disabled = busy || !(LAST && LAST.gate && LAST.gate.enabled);
    $("mxGenBtn").textContent = busy ? "생성 중…" : "여러 작업 문서 생성";
  }

  async function doGenerate(confirmOverwrite) {
    generating = true; setBusy(true);
    if (!confirmOverwrite) { $("mxGenBar").style.width = "0%"; log("일괄 생성 요청"); }
    let res;
    try {
      res = await Bridge.generate(SCREEN, confirmOverwrite);
    } finally {
      generating = false; setBusy(false);
    }
    if (res.ok) { renderResult(res); return; }
    if (res.needs_overwrite) {
      // 조용한 덮어쓰기 금지 — 재진술 후 확인 시에만 재호출(RC-02).
      if (window.confirm(res.overwrite_text + "\n\n계속할까요?")) { doGenerate(true); }
      else { log("생성 취소 — 기존 파일 덮어쓰기를 확정하지 않았습니다."); }
      return;
    }
    warnResult(res.error || "생성할 수 없습니다.", res.level);
  }

  function renderResult(res) {
    $("mxGenBar").style.width = "100%";
    const r = $("mxGenResult");
    r.textContent = res.summary;
    r.className = "run-result " + (res.level === "ok" ? "ok" : "danger");
    log(res.summary);
    (res.per_job || []).forEach((jr) =>
      log(`  [${jr.job_name}] ${jr.succeeded}/${jr.total} → ${jr.out_dir}/`));
    (res.failures || []).forEach((f) => log("  [실패] " + f));
    log(`저장 폴더: ${res.out_dir}`);
  }

  function warnResult(msg, level) {
    const r = $("mxGenResult");
    r.textContent = "⚠ " + msg;
    r.className = "run-result " + (level === "danger" ? "danger" : "warn");
    log(msg);
  }

  function ackAction(badgeEl) {
    const act = badgeEl.classList.contains("ack") ? "unack_field" : "ack_field";
    Bridge.call(SCREEN, act, { job: badgeEl.dataset.job, field: badgeEl.dataset.f });
  }

  function onBadgeClick(e) {
    const badgeEl = e.target.closest(".fb.missing");
    if (badgeEl && $("scr-matrix").contains(badgeEl)) ackAction(badgeEl);
  }

  function onBadgeKey(e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    const badgeEl = e.target.closest(".fb.missing");
    if (!badgeEl) return;
    e.preventDefault();
    ackAction(badgeEl);
  }

  function onJobChange(e) {
    const cb = e.target.closest('input[type="checkbox"][data-job]');
    if (!cb) return;
    Bridge.call(SCREEN, "toggle_job", { name: cb.dataset.job, value: cb.checked });
  }

  function onRecChange(e) {
    const cb = e.target.closest('input[type="checkbox"][data-i]');
    if (!cb) return;
    Bridge.call(SCREEN, "toggle_record", { index: Number(cb.dataset.i), value: cb.checked });
  }

  function wire() {
    $("mxJobList").addEventListener("change", onJobChange);
    $("mxJobAll").addEventListener("click", () => Bridge.call(SCREEN, "set_all_jobs", {}));
    $("mxJobNone").addEventListener("click", () => Bridge.call(SCREEN, "set_none_jobs", {}));
    $("mxSelAll").addEventListener("click", () => Bridge.call(SCREEN, "set_all", {}));
    $("mxSelNone").addEventListener("click", () => Bridge.call(SCREEN, "set_none", {}));
    $("mxRecList").addEventListener("change", onRecChange);
    $("mxFieldBadges").addEventListener("click", onBadgeClick);
    $("mxFieldBadges").addEventListener("keydown", onBadgeKey);
    $("mxGenBtn").addEventListener("click", () => doGenerate(false));

    $("btnMxPickData").addEventListener("click", async () => {
      let r = await Bridge.pickDataFile(SCREEN);
      if (r && typeof r === "object" && r.needs_sheet) {   // 다중 시트 → 확정 게이트(#33)
        r = await SheetPicker.choose(SCREEN, r);
        if (r === null) { log("공통 데이터 선택 취소 — 시트를 확정하지 않았습니다."); return; }
      }
      if (r === null) return;                       // 취소
      if (typeof r === "string" && r.startsWith("ERROR:")) { log("데이터 오류: " + r.slice(6).trim()); return; }
      log(`공통 데이터 불러옴: ${r}`);
    });
    // 등록 데이터(풀) 겨눔(#26 #6) — 취소=중단, 실패는 모달 안에서 재진술(PoolPicker).
    $("btnMxPoolData").addEventListener("click", async () => {
      const label = await PoolPicker.choose(SCREEN);
      if (label === null) return;                   // 취소 = 겨눔 중단
      log(`등록 데이터 불러옴: ${label}`);
    });
    $("btnMxPickFolder").addEventListener("click", async () => {
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

  window.MatrixScreen = { init };
})();
