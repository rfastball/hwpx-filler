/* 실행(run) 화면 — 브리지로 링1 RunViewModel·SelectionModel 과 왕복. 목업 scr-run 이관(#18).
   안정 DOM(index.html) + Python 이 window.__push('run', snapshot) 로 값만 채운다(txt 패턴).
   표현 계층(3상태 배지·게이트 재진술·진행/로그)만 여기서 만든다 — VM 로직 아님(링2 대체). */
(function () {
  const SCREEN = "run";
  const $ = (id) => document.getElementById(id);
  let LAST = null;
  let generating = false;

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    if (s && s.progress) { renderProgress(s.progress); return; }  // 진행 델타(경량) — 로그 바닥고정, 보존 밖
    Preserve.around(() => {  // 매핑/레코드 포커스·스크롤 보존(#28)
      LAST = s;
      setJobOptions(s.jobs, s.job_name);
      renderJobMeta(s);
      renderData(s);
      renderPreflight(s);
      renderBadges(s);
      renderRecords(s);
      renderGate(s);
      renderStatus(s);
      $("runBody").style.display = s.has_job ? "" : "none";
      // 작업·데이터·선택이 바뀐 새 스냅샷 → 이전 생성 결과 무효화(#28, UD-10). txt.resetNote 패턴.
      if (!generating) resetGenResult();
    });
  }

  /* 이전 생성 결과(요약·진행바·로그)를 기본 상태로 되돌린다 — 오래된 성공 잔존 방지(#28).
     생성 중(generating)엔 부르지 않아 진행 표시를 보존한다. 완료 결과는 renderResult 가
     push 아닌 직접 호출로 그리므로 다음 사용자 변경(스냅샷) 전까지 유지된다. */
  function resetGenResult() {
    $("genBar").style.width = "0%";
    const r = $("genResult");
    r.textContent = "";
    r.className = "run-result";
    $("genLog").textContent = "";
    logStarted = false;
  }

  /* 작업 목록 옵션은 변경 시에만 재구성(선택 중 리셋 방지). 값은 항상 스냅샷에 맞춘다. */
  function setJobOptions(jobs, current) {
    const sel = $("jobSel");
    const key = (jobs || []).join("");
    if (sel.dataset.key !== key) {
      sel.dataset.key = key;
      sel.innerHTML =
        `<option value="">— 작업 선택 —</option>` +
        (jobs || []).map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
    }
    sel.value = current || "";
  }

  function renderJobMeta(s) {
    const box = $("jobMeta");
    if (!s.has_job) { box.textContent = ""; box.style.display = "none"; return; }
    box.style.display = "";
    box.innerHTML =
      `<span class="mono">${esc(s.template_name || "(템플릿 없음)")}</span>` +
      ` · 파일명 <span class="mono">${esc(s.filename_pattern)}</span>` +
      // 템플릿 로케이트(#53-B) — 열기·폴더보기·경로복사(소유 화이트리스트 검증).
      ` ${PathTrack.affordances(s.template_path)}`;
    $("targetLine").innerHTML = s.template_name
      ? `새 문서 생성 — 작업 템플릿(<span class="mono">${esc(s.template_name)}</span>)으로 한 번에 완성합니다.`
      : `작업 템플릿 경로가 비어 있습니다 — 에디터에서 템플릿을 지정하세요.`;
  }

  function renderData(s) {
    // 소스 종류 병기 라벨("파일: x" / "등록 데이터: 이름", #26 #6) — 서버가 플래그에서 합성(K8).
    $("runDataLabel").value = s.data_source_label || "";
    $("outDir").value = s.out_dir || "";
    // 저장 폴더 로케이트(#53-B) — 폴더 열기·경로복사(폴더라 '열기'는 탐색기로 동일).
    const ot = $("outTrack");
    if (ot) ot.innerHTML = PathTrack.affordances(s.out_dir, { only: ["reveal", "copy"] });
    // 기본 데이터셋 자동 조준 재진술(#53-A) — 성공(ok)/실패(warn) 시끄럽게 표시.
    const note = $("runDataNotice");
    if (note) {
      const n = s.data_notice;
      if (n && n.text) {
        note.style.display = "block";
        note.className = "note " + (n.level === "ok" ? "okbox" : "warnbox");
        note.textContent = (n.level === "ok" ? "✓ " : "⚠ ") + n.text;
      } else {
        note.style.display = "none";
        note.textContent = "";
      }
    }
  }

  function renderPreflight(s) {
    const box = $("preflight");
    const p = s.preflight || { level: "", text: "" };
    if (!s.has_data || !p.text) { box.style.display = "none"; return; }
    box.style.display = "block";
    const cls = p.level === "ok" ? "okbox" : p.level === "danger" ? "dangerbox" : "warnbox";
    box.className = "preflight note " + cls;
    box.style.whiteSpace = "pre-line";
    box.textContent = p.text;
  }

  /* 3상태 배지(ADR-B/E) — 미입력만 클릭형(확인/철회 토글), 나머지는 정적. */
  function renderBadges(s) {
    const host = $("fieldBadges");
    const states = s.field_states || [];
    if (!states.length) {
      host.innerHTML = s.has_job
        ? `<span class="muted" style="font-size:12px">데이터를 선택하면 필드별 채움 상태가 여기에 표시됩니다.</span>`
        : "";
      return;
    }
    host.innerHTML = states.map(badge).join("");
  }

  function badge(st) {
    const nm = esc(st.name);
    if (st.state === "filled") return `<span class="fb fill">✓ ${nm}</span>`;
    if (st.state === "blank") return `<span class="fb blank">◦ ${nm} (비움)</span>`;
    if (st.state === "drift") return `<span class="fb drift">⚠ ${nm} — 매핑 재확정 필요</span>`;
    // missing(값 빔) — 클릭해 확인/철회.
    if (st.acknowledged) {
      return `<span class="fb missing ack" data-f="${nm}" role="button" tabindex="0"
        title="다시 눌러 확인을 취소합니다(게이트가 다시 닫힙니다).">✓ ${nm} — 미입력 표시 예정</span>`;
    }
    return `<span class="fb missing" data-f="${nm}" role="button" tabindex="0">● ${nm} — 미입력 확인</span>`;
  }

  function renderRecords(s) {
    const host = $("recList");
    const recs = s.records || [];
    $("selCount").textContent = `선택 ${s.selected_count}/${s.record_count}`;
    if (!recs.length) {
      host.innerHTML = s.has_job
        ? `<div class="rec muted">데이터를 선택하면 생성 대상 문서가 여기에 표시됩니다.</div>`
        : "";
      return;
    }
    host.innerHTML = recs.map((r) =>
      `<label class="rec"><input type="checkbox" data-i="${r.index}"${r.selected ? " checked" : ""}>` +
      `<span class="rf">${esc(r.label)}</span></label>`).join("");
  }

  function renderGate(s) {
    const g = s.gate || { enabled: false, level: "", text: "" };
    $("genBtn").disabled = !g.enabled || generating;
    const gate = $("genGate");
    gate.textContent = generating ? "" : g.text;
    gate.className = "muted";
    gate.style.color = g.level === "danger" ? "var(--a-danger)"
      : g.level === "warn" ? "var(--a-warn)" : "";
  }

  function renderStatus(s) {
    const pill = $("runStatus");
    if (!s.has_job) { pill.dataset.level = "idle"; pill.textContent = "작업 선택"; return; }
    if (!s.has_data) { pill.dataset.level = "idle"; pill.textContent = "데이터 선택"; return; }
    if (s.gate && s.gate.enabled) { pill.dataset.level = "ok"; pill.textContent = "생성 준비"; }
    else { pill.dataset.level = "warn"; pill.textContent = "확인 필요"; }
  }

  /* 진행 델타 — 진행바만 갱신(전체 재렌더 없음). */
  function renderProgress(p) {
    const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
    $("genBar").style.width = pct + "%";
    const r = $("genResult");
    r.className = "run-result";
    r.textContent = `생성 중… ${p.done}/${p.total}`;
  }

  /* ---- 로그 ---- */
  let logStarted = false;
  function log(msg) {
    const box = $("genLog");
    const ts = new Date().toLocaleTimeString("ko-KR", { hour12: false });
    if (!logStarted) { box.textContent = ""; logStarted = true; }
    box.textContent += (box.textContent ? "\n" : "") + `[${ts}] ${msg}`;
    box.scrollTop = box.scrollHeight;
  }

  /* ---- 웹→Python 이벤트 ---- */
  /* busy 잠금 대상은 하드코딩 id 배열이 아니라 [data-busy-lock] 속성으로 선언한다 — 새
     컨트롤을 추가할 때 이 함수를 잊고 지나쳐도(#26 setBusy 누락 회귀) 속성만 붙이면
     자동으로 잠긴다(구조적 재발 방지). */
  function setBusy(busy) {
    $("scr-run").querySelectorAll("[data-busy-lock]").forEach((el) => { el.disabled = busy; });
    $("genBtn").disabled = busy || !(LAST && LAST.gate && LAST.gate.enabled);
    $("genBtn").textContent = busy ? "생성 중…" : "이 작업으로 문서 생성";
  }

  async function doGenerate(confirmOverwrite) {
    generating = true; setBusy(true);
    if (!confirmOverwrite) { $("genBar").style.width = "0%"; log("생성 요청"); }
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
    $("genBar").style.width = "100%";
    const r = $("genResult");
    r.textContent = res.summary;
    r.className = "run-result " + (res.level === "ok" ? "ok" : "danger");
    log(res.summary);
    (res.failures || []).forEach((f) => log("  [실패] " + f));
    log(`저장 폴더: ${res.out_dir}`);
  }

  function warnResult(msg, level) {
    const r = $("genResult");
    r.textContent = "⚠ " + msg;
    r.className = "run-result " + (level === "danger" ? "danger" : "warn");
    log(msg);
  }

  function onClick(e) {
    const badgeEl = e.target.closest(".fb.missing");
    if (badgeEl && $("scr-run").contains(badgeEl)) {
      const field = badgeEl.dataset.f;
      const act = badgeEl.classList.contains("ack") ? "unack_field" : "ack_field";
      Bridge.call(SCREEN, act, { field });
    }
  }

  function onBadgeKey(e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    const badgeEl = e.target.closest(".fb.missing");
    if (!badgeEl) return;
    e.preventDefault();
    const act = badgeEl.classList.contains("ack") ? "unack_field" : "ack_field";
    Bridge.call(SCREEN, act, { field: badgeEl.dataset.f });
  }

  function onRecChange(e) {
    const cb = e.target.closest('input[type="checkbox"][data-i]');
    if (!cb) return;
    Bridge.call(SCREEN, "toggle_record", { index: Number(cb.dataset.i), value: cb.checked });
  }

  function wire() {
    $("jobSel").addEventListener("change", (e) =>
      Bridge.call(SCREEN, "select_job", { name: e.target.value }));
    $("selAll").addEventListener("click", () => Bridge.call(SCREEN, "set_all", {}));
    $("selNone").addEventListener("click", () => Bridge.call(SCREEN, "set_none", {}));
    $("recList").addEventListener("change", onRecChange);
    $("fieldBadges").addEventListener("click", onClick);
    $("fieldBadges").addEventListener("keydown", onBadgeKey);
    $("genBtn").addEventListener("click", () => doGenerate(false));

    $("btnPickData").addEventListener("click", async () => {
      let r = await Bridge.pickDataFile(SCREEN);
      if (r && typeof r === "object" && r.needs_sheet) {   // 다중 시트 → 확정 게이트(#33)
        r = await SheetPicker.choose(SCREEN, r);
        if (r === null) { log("데이터 선택 취소 — 시트를 확정하지 않았습니다."); return; }
      }
      if (r === null) return;                       // 취소
      if (typeof r === "string" && r.startsWith("ERROR:")) { log("데이터 오류: " + r.slice(6).trim()); return; }
      log(`데이터 불러옴: ${r}`);
    });
    // 등록 데이터(풀) 겨눔(#26 #6) — 취소=중단, 실패는 모달 안에서 재진술(PoolPicker).
    $("btnPoolData").addEventListener("click", async () => {
      const label = await PoolPicker.choose(SCREEN);
      if (label === null) return;                   // 취소 = 겨눔 중단
      log(`등록 데이터 불러옴: ${label}`);
    });
    $("btnPickFolder").addEventListener("click", async () => {
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

  window.RunScreen = { init };
})();
