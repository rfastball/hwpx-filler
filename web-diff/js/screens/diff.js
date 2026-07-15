/* diff 화면 — 브리지로 hwpxdiff.diff 엔진과 왕복(무변경 재사용). Qt DiffReviewWindow 의 웹판.
   렌더는 Python 이 window.__push('diff', snapshot) 로 민다(관측 방향). 신구대비표·변경리스트는
   snapshot 의 구조화 데이터(rows·groups·ops)에서 DOM 을 짓는다 = Qt _render_doc_html/_side_html
   의 순수 표현 포팅(VM 로직 아님). 색/라벨은 snapshot(core KIND_*)에서만 — 하드코딩 금지. */
(function () {
  const SCREEN = "diff";
  const $ = (id) => document.getElementById(id);
  let LAST = null;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }
  function nl2br(s) { return esc(s).replace(/\n/g, "<br>") || "&nbsp;"; }

  /* 낱말 op → 한쪽 판본 관점 인라인 강조(Qt _side_html 포팅).
     구판(old): equal + delete/replace 의 <del>; 신판(new): equal + insert/replace 의 <ins>. */
  function sideHtml(ops, side) {
    const out = [];
    for (const w of ops) {
      if (w.op === "equal") out.push(esc(w.old));
      else if (side === "old" && (w.op === "delete" || w.op === "replace"))
        out.push(`<del>${esc(w.old)}</del>`);
      else if (side === "new" && (w.op === "insert" || w.op === "replace"))
        out.push(`<ins>${esc(w.new)}</ins>`);
    }
    return out.join("") || "&nbsp;";
  }

  /* 전문 신구대비표 <table>(Qt _render_doc_html 포팅). 그룹 헤더는 group_key 변화 지점,
     변경 행엔 id="chg-{seq}" 앵커(리스트 클릭 점프 표적). 색/틴트는 snapshot 에서. */
  function renderDoc(s) {
    const colors = s.kind_colors || {}, tints = s.kind_tints || {}, labels = s.kind_labels || {};
    const rows = ["<table class='doctable'><thead><tr><th class='c-tag'></th>",
      "<th>구판</th><th>신판</th></tr></thead><tbody>"];
    let prevKey = null;
    for (const r of s.rows) {
      if (r.group_key !== prevKey) {
        rows.push(`<tr class='grouprow'><td colspan='3'>${esc(r.group_key)}</td></tr>`);
        prevKey = r.group_key;
      }
      const anchor = r.seq != null ? ` id='chg-${r.seq}'` : "";
      if (r.kind === "equal") {
        const body = nl2br(r.new_text);
        rows.push(`<tr class='r-equal'><td></td><td>${body}</td><td>${body}</td></tr>`);
        continue;
      }
      const color = colors[r.kind] || "#555";
      const tag = `<span class='ktag' style='color:${color}'>${esc(labels[r.kind] || r.kind)}</span>`;
      if (r.kind === "added") {
        rows.push(`<tr class='r-added'${anchor}><td>${tag}</td><td></td>` +
          `<td style='background:${tints.added || ""}'>${nl2br(r.new_text)}</td></tr>`);
      } else if (r.kind === "removed") {
        rows.push(`<tr class='r-removed'${anchor}><td>${tag}</td>` +
          `<td style='background:${tints.removed || ""}'>${nl2br(r.old_text)}</td><td></td></tr>`);
      } else { // changed / renumber
        const ops = r.ops || [];
        let oldH = sideHtml(ops, "old"), newH = sideHtml(ops, "new");
        if (r.kind === "renumber") {
          const rc = colors.renumber || "#7a7f87";
          oldH = `<span style='color:${rc}'>${oldH}</span>`;
          newH = `<span style='color:${rc}'>${newH}</span>`;
        }
        rows.push(`<tr class='r-changed'${anchor}><td>${tag}</td>` +
          `<td>${oldH}</td><td>${newH}</td></tr>`);
      }
    }
    rows.push("</tbody></table>");
    $("docView").innerHTML = rows.join("");
  }

  /* 변경 리스트(Qt 좌측 QTableWidget 포팅). 행마다 종류 배지+라벨+상세, data-seq/data-kind. */
  function renderList(s) {
    const colors = s.kind_colors || {}, labels = s.kind_labels || {};
    const html = s.groups.map((g) =>
      `<div class='chg' data-seq='${g.seq}' data-kind='${g.kind}'>` +
      `<span class='cbadge' style='background:${colors[g.kind] || "#555"}'>` +
      `${esc(labels[g.kind] || g.kind)}</span>` +
      `<span class='clabel'>${esc(g.label)}</span>` +
      `<span class='cdetail'>${esc(g.detail)}</span></div>`
    ).join("");
    $("changeList").innerHTML = html || "<p class='muted'>변경이 없습니다.</p>";
  }

  /* KPI 4타일 — 색은 snapshot(core KIND_COLORS). */
  function renderKpis(s) {
    const labels = s.kind_labels || {}, colors = s.kind_colors || {};
    const order = ["added", "removed", "changed", "renumber"];
    $("diffKpis").innerHTML = order.map((k) =>
      `<div class='kpi'><div class='v' style='color:${colors[k] || ""}'>${s.summary[k] || 0}</div>` +
      `<div class='l'>${esc(labels[k] || k)}</div></div>`
    ).join("");
  }

  function setStatus(level, text) {
    const p = $("diffStatus"); p.dataset.level = level; p.textContent = text;
  }

  /* 클라이언트측 종류 필터(Qt _visible/setRowHidden 포팅) — 변경 리스트만 걸러낸다.
     renumber 는 종류 체크가 아니라 전용 토글을 따른다. 전부 숨으면 시끄럽게 알린다(RC-32). */
  function applyFilter() {
    const enabled = new Set();
    if ($("fAdded").checked) enabled.add("added");
    if ($("fRemoved").checked) enabled.add("removed");
    if ($("fChanged").checked) enabled.add("changed");
    const showRenumber = $("fRenumber").checked;
    const rows = $("changeList").querySelectorAll(".chg");
    let visible = 0;
    rows.forEach((el) => {
      const kind = el.dataset.kind;
      const show = kind === "renumber" ? showRenumber : enabled.has(kind);
      el.style.display = show ? "" : "none";
      if (show) visible++;
    });
    const notice = $("filterNotice");
    if (rows.length && visible === 0) {
      notice.style.display = ""; notice.textContent =
        "필터에 걸려 표시된 변경이 없습니다 — 종류 필터·번호변경 토글을 확인하세요.";
    } else notice.style.display = "none";
  }

  function showResultUI(on) {
    const disp = on ? "" : "none";
    $("diffKpis").style.display = on ? "grid" : "none";
    $("diffSplit").style.display = on ? "grid" : "none";
    $("stageNote").style.display = on ? "none" : "";
  }

  /* Python→웹 푸시 렌더. Bridge.onPush 로 등록된다. */
  function render(s) {
    LAST = s;
    $("oldLabel").value = s.old_label || "";
    $("newLabel").value = s.new_label || "";
    $("compareBtn").disabled = !s.can_compare || s.status === "running";
    renderRecent(s.recent || []);

    if (s.status === "running") {
      showResultUI(false);
      $("diffFilters").style.display = "none";
      $("diffSummary").style.display = "none";
      $("stageNote").innerHTML = "<span class='spinner'></span> 비교 중… (대형 문서는 시간이 걸릴 수 있습니다)";
      setStatus("warn", "비교 중");
      return;
    }
    if (s.status === "error") {
      showResultUI(false);
      $("diffFilters").style.display = "none";
      $("diffSummary").style.display = "none";
      $("stageNote").innerHTML = `<span class='danger'>비교 실패</span> — ${esc(s.error)}`;
      setStatus("warn", "오류");
      return;
    }
    if (!s.has_result) {
      showResultUI(false);
      $("diffFilters").style.display = "none";
      $("diffSummary").style.display = "none";
      $("stageNote").innerHTML = s.can_compare
        ? "<b>비교</b>를 눌러 두 판본을 대조하세요."
        : "구판·신판을 선택한 뒤 <b>비교</b>를 누르세요.";
      setStatus("idle", "판본 선택");
      return;
    }
    // done + 결과 있음
    renderKpis(s);
    renderList(s);
    renderDoc(s);
    showResultUI(true);
    if (s.change_count === 0) {
      $("diffSummary").style.display = ""; $("diffSummary").textContent = s.no_changes_message;
      $("diffFilters").style.display = "none";
      setStatus("ok", "변경 없음");
    } else {
      $("diffSummary").style.display = "none";
      $("diffFilters").style.display = "flex";
      applyFilter();
      setStatus("warn", `변경 ${s.change_count}건`);
    }
  }

  function renderRecent(recent) {
    $("recentBtn").disabled = recent.length === 0;
    $("recentMenu").innerHTML = recent.map((p, i) =>
      `<button class='recent-item' data-i='${i}'>` +
      `<span class='ri-old'>${esc(p.old_label)}</span> → <span class='ri-new'>${esc(p.new_label)}</span>` +
      `</button>`).join("");
  }

  /* 웹→Python 이벤트 배선. */
  function wire() {
    $("pickOld").addEventListener("click", async () => {
      const r = await Bridge.pickOld(SCREEN);
      if (typeof r === "string" && r.startsWith("ERROR:"))
        setStatus("warn", "구판 오류: " + r.slice(6).trim());
      // 파일명은 load_old_path 가 스냅샷(old_label)으로 밀어 render 가 채운다.
    });
    $("pickNew").addEventListener("click", async () => {
      const r = await Bridge.pickNew(SCREEN);
      if (typeof r === "string" && r.startsWith("ERROR:"))
        setStatus("warn", "신판 오류: " + r.slice(6).trim());
    });
    $("compareBtn").addEventListener("click", async () => {
      const r = await Bridge.compare(SCREEN);
      if (r && r.ok === false) setStatus("warn", r.error);
      // running/done 은 push 가 render 로 반영한다.
    });

    // 필터(클라이언트측)
    ["fAdded", "fRemoved", "fChanged", "fRenumber"].forEach((id) =>
      $(id).addEventListener("change", applyFilter));

    // 변경 리스트 행 클릭 → 전문 뷰 앵커로 스크롤 + 하이라이트
    $("changeList").addEventListener("click", (e) => {
      const row = e.target.closest(".chg");
      if (!row) return;
      $("changeList").querySelectorAll(".chg.sel").forEach((x) => x.classList.remove("sel"));
      row.classList.add("sel");
      const anchor = document.getElementById("chg-" + row.dataset.seq);
      if (anchor) {
        anchor.scrollIntoView({ block: "center", behavior: "smooth" });
        anchor.classList.add("flash");
        setTimeout(() => anchor.classList.remove("flash"), 900);
      }
    });

    // 최근 메뉴 토글 + 선택
    $("recentBtn").addEventListener("click", () =>
      $("recentMenu").classList.toggle("hidden"));
    $("recentMenu").addEventListener("click", (e) => {
      const item = e.target.closest(".recent-item");
      if (!item) return;
      const pair = LAST.recent[+item.dataset.i];
      $("recentMenu").classList.add("hidden");
      Bridge.call(SCREEN, "select_recent", { old: pair.old, new: pair.new });
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".recent-wrap")) $("recentMenu").classList.add("hidden");
    });
  }

  /* 화면 부팅 — app.js 가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    render(await Bridge.initial(SCREEN));
  }

  window.DiffScreen = { init };
})();
