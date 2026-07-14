/* 작업 에디터(HWPX) 화면 — 브리지로 링1 EditorController 와 왕복. 4단계 마법사.
   목업 scr-editor 이관(#15·#16). 렌더는 Python 이 window.__push('editor', snapshot) 로 밀어 넣는다.
   표현 계층(단계 UI·매핑표·행 색·표시형 라벨)만 여기서 만든다 — VM 로직 아님. */
(function () {
  const SCREEN = "editor";
  const $ = (id) => document.getElementById(id);
  // 표시형/타입 라벨은 표현 계층 → 여기(뷰)에 둔다(Qt mapping_table 의 웹 짝).
  const TYPE_LABEL = { text: "텍스트", date: "날짜", amount: "금액", const: "고정값" };
  const INFERRED_LABEL = { text: "텍스트", date: "날짜", amount: "금액", number: "숫자", phone: "전화번호" };
  const STEP_TITLES = ["템플릿 선택", "데이터 선택", "필드 매핑 확정", "작업 저장"];
  let LAST = null;

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    LAST = s;
    $("editor-steps").innerHTML = stepHeader(s);
    $("editor-body").innerHTML = stepBody(s);
    $("editor-foot").innerHTML = footer(s);
  }

  function stepHeader(s) {
    return STEP_TITLES.map((t, i) => {
      const cur = i === s.step ? ' aria-current="true"' : "";
      const done = i < s.step ? " done" : "";
      return `<div class="wstep-tab${done}"${cur}><span class="k">${i + 1}</span>${esc(t)}</div>`;
    }).join("");
  }

  function stepBody(s) {
    if (s.step === 0) return step0(s);
    if (s.step === 1) return step1(s);
    if (s.step === 2) return step2(s);
    return step3(s);
  }

  /* ---- 1단계: 템플릿 ---- */
  function step0(s) {
    let out = `<div class="wtitle">1단계 — 템플릿 선택</div>
      <p class="wsub">누름틀이 들어 있는 HWPX 템플릿을 선택하세요.</p>
      <div class="row"><span class="lbl">템플릿(.hwpx)</span>
        <input class="field ro" readonly value="${esc(s.template_name || "")}"
          placeholder="템플릿을 선택하세요">
        <button class="btn" data-act="pick-template">찾아보기…</button></div>`;
    if (s.raw_block) {
      out += `<p class="note dangerbox" style="white-space:pre-line">${esc(s.raw_block)}</p>`;
    } else if (s.gate_error) {
      out += `<p class="note dangerbox">템플릿 상태를 확인할 수 없습니다 — 진행할 수 없습니다.</p>`;
    } else if (s.field_count) {
      out += `<p class="fields-line">${esc(s.schema_summary)}</p>`;
      if (s.gate) {
        out += `<div class="note warnbox" style="white-space:pre-line">${esc(s.gate.message)}</div>`;
        if (!s.gate.acked) {
          out += `<button class="btn" data-act="ack-gate">비우고 진행 확인 (${s.gate.unmet.length}개 토큰)</button>`;
        }
      }
    }
    return out;
  }

  /* ---- 2단계: 데이터(선택적) ---- */
  function step1(s) {
    return `<div class="wtitle">2단계 — 데이터 선택 <span class="muted" style="font-weight:400;font-size:12px">(선택)</span></div>
      <p class="wsub">레코드(행)마다 문서 1건을 생성할 데이터 파일. 작업엔 데이터가 저장되지 않습니다 —
        매핑 검토용 샘플입니다. 데이터 없이 진행하면 스키마만으로 매핑합니다.</p>
      <div class="row"><span class="lbl">데이터(.xlsx/.csv)</span>
        <input class="field ro" readonly value="${esc(s.data_name || "")}"
          placeholder="데이터를 선택하거나 건너뛰세요">
        <button class="btn" data-act="pick-data">찾아보기…</button>
        <button class="btn" data-act="skip-data">데이터 없이 진행 →</button></div>
      ${s.record_count ? `<p class="note okbox">컬럼 ${s.source_fields.length}개, 레코드 ${s.record_count}건 로드.</p>` : ""}`;
  }

  /* ---- 3단계: 매핑 표 ---- */
  function step2(s) {
    const rows = (s.rows || []).map((r) => mapRow(r, s)).join("");
    const stepper = s.preview_count
      ? `<button class="btn sm" data-act="prev-rec">◀ 이전 행</button>
         <span class="mono">행 ${s.preview_index}/${s.preview_count}</span>
         <button class="btn sm" data-act="next-rec">다음 행 ▶</button>`
      : `<span class="muted">행 0/0 — 데이터 미연결(스키마만)</span>`;
    const counts = s.counts
      ? `<span class="muted">채움 ${s.counts.filled} · 빈 값 ${s.counts.empty} · 미매핑 ${s.counts.unmapped}` +
        `${s.preview_empties && s.preview_empties.length ? " — " + esc(s.preview_empties.join(", ")) : ""}</span>`
      : "";
    const banner = s.schema_only
      ? `<p class="note warnbox">데이터 미연결(스키마온리) — 내용 없는 행은 '미매칭'이 아니라 '데이터 없음'입니다. 고정값을 넣거나 비움으로 확정하세요.</p>`
      : "";
    return `<div class="wtitle">3단계 — 필드 매핑 확정</div>
      <p class="wsub">자동 제안은 초안입니다. 모든 행을 검토·확정해야 다음으로 진행합니다.
        채우지 않을 필드는 소스를 (비움)으로 두고 확정하세요.</p>
      ${banner}
      <div class="tblwrap"><table class="map"><thead><tr>
        <th>확정</th><th>템플릿 필드 · 추정</th><th>데이터 항목</th>
        <th>타입 / 고정값</th><th>표시형</th><th>미리보기</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <div class="stepper">${stepper}<span style="flex:1"></span>${counts}</div>
      <div class="gate">
        <span class="gatecount ${s.is_complete ? "ok" : "pend"}">확정 ${(s.rows || []).filter((r) => r.confirmed).length}/${(s.rows || []).length}</span>
        <span style="flex:1"></span>
        <button class="btn" data-act="confirm-all">모두 확정</button>
        <button class="btn" data-act="unconfirm-all">모두 해제</button>
      </div>`;
  }

  function mapRow(r, s) {
    const srcOpts = [`<option value=""${r.source ? "" : " selected"}>(비움)</option>`]
      .concat((s.source_fields || []).map((f) =>
        `<option value="${esc(f)}"${f === r.source ? " selected" : ""} title="${esc(f)}">${esc(f)}</option>`))
      .join("");
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
    else if (r.preview_empty) preview = `<span class="pv emptyval">(이 레코드에서 빈 값)</span>`;
    else preview = `<span class="pv">${esc(r.preview)}</span>`;
    return `<tr class="r-${r.row_state}">
      <td><input type="checkbox" class="cbx" data-act="row-confirm" data-index="${r.index}"${r.confirmed ? " checked" : ""}></td>
      <td><span class="fname" title="${esc(r.context || r.template_field)}">${esc(r.template_field)}</span>
        <span class="tbadge">[추정: ${esc(inferred)}]</span></td>
      <td><select class="sel" data-act="row-source" data-index="${r.index}">${srcOpts}</select></td>
      <td><select class="sel" data-act="row-type" data-index="${r.index}">${typeOpts}</select> ${constInput}</td>
      <td><select class="sel" data-act="row-fmt" data-index="${r.index}"${fmtList.length ? "" : " disabled"}>${fmtOpts}</select></td>
      <td>${preview}</td></tr>`;
  }

  /* ---- 4단계: 저장 ---- */
  function step3(s) {
    return `<div class="wtitle">4단계 — 작업 저장</div>
      <p class="wsub">이 작업(템플릿·매핑·파일명)을 저장합니다. 데이터·행은 저장하지 않습니다 —
        실행할 때 고릅니다.</p>
      <div class="row" style="margin-bottom:9px"><span class="lbl" style="width:76px">작업 이름</span>
        <input class="field" data-act="name" value="${esc(s.name)}" placeholder="예: 공고서 자동생성"></div>
      <div class="row"><span class="lbl" style="width:76px">파일명 패턴</span>
        <input class="field mono" data-act="pattern" value="${esc(s.pattern)}"></div>
      <p class="muted" style="font-size:11.5px;margin:8px 0 0 84px">토큰: {{필드}}, {{date:YYYYMMDD}}, {{seq:001}}</p>
      <div id="save-msg" class="note" style="display:none"></div>`;
  }

  /* ---- 푸터 내비 ---- */
  function footer(s) {
    const back = s.step > 0
      ? `<button class="btn" data-act="back">◀ 뒤로</button>` : `<button class="btn" disabled>◀ 뒤로</button>`;
    let next;
    if (s.step < 3) {
      const can = s.reachable[s.step];
      next = `<button class="btn primary" data-act="next"${can ? "" : " disabled"}>다음 ▶</button>`;
    } else {
      next = `<button class="btn primary" data-act="save">작업 저장</button>`;
    }
    const hint = (s.step < 3 && !s.reachable[s.step])
      ? `<span class="muted" style="font-size:12px">${gateHint(s)}</span>` : "";
    return `${back}<span style="flex:1"></span>${hint}${next}`;
  }

  function gateHint(s) {
    if (s.step === 0) return "템플릿을 선택하고 게이트를 통과해야 진행할 수 있습니다";
    if (s.step === 2) return "전 행을 확정해야 진행할 수 있습니다";
    return "";
  }

  /* ---- 이벤트 위임(innerHTML 재구성이라 위임이 안전) ---- */
  async function onClick(e) {
    const el = e.target.closest("[data-act]");
    if (!el) return;
    const act = el.dataset.act;
    const idx = el.dataset.index !== undefined ? Number(el.dataset.index) : null;
    switch (act) {
      case "pick-template": {
        const r = await Bridge.pickTemplateFile(SCREEN);
        if (typeof r === "string" && r.startsWith("ERROR:")) alertMsg(r.slice(6).trim());
        break;
      }
      case "ack-gate": Bridge.call(SCREEN, "ack_gate", {}); break;
      case "pick-data": {
        const r = await Bridge.pickDataFile(SCREEN);
        if (typeof r === "string" && r.startsWith("ERROR:")) alertMsg(r.slice(6).trim());
        break;
      }
      case "skip-data": Bridge.call(SCREEN, "skip_data", {}); break;
      case "prev-rec": Bridge.call(SCREEN, "step_preview", { delta: -1 }); break;
      case "next-rec": Bridge.call(SCREEN, "step_preview", { delta: 1 }); break;
      case "unconfirm-all": Bridge.call(SCREEN, "unconfirm_all", {}); break;
      case "confirm-all": await confirmAll(); break;
      case "row-confirm": Bridge.call(SCREEN, "set_confirmed", { index: idx, confirmed: el.checked }); break;
      case "back": Bridge.call(SCREEN, "goto_step", { step: LAST.step - 1 }); break;
      case "next": Bridge.call(SCREEN, "goto_step", { step: LAST.step + 1 }); break;
      case "save": await doSave(false); break;
      default: break;
    }
  }

  function onChange(e) {
    const el = e.target.closest("[data-act]");
    if (!el) return;
    const idx = el.dataset.index !== undefined ? Number(el.dataset.index) : null;
    switch (el.dataset.act) {
      case "row-source": Bridge.call(SCREEN, "set_source", { index: idx, source: el.value }); break;
      case "row-type": Bridge.call(SCREEN, "set_type", { index: idx, type: el.value }); break;
      case "row-fmt": Bridge.call(SCREEN, "set_fmt", { index: idx, fmt: el.value }); break;
      case "row-const": Bridge.call(SCREEN, "set_const", { index: idx, const: el.value }); break;
      case "name": Bridge.call(SCREEN, "set_name", { name: el.value }); break;
      case "pattern": Bridge.call(SCREEN, "set_pattern", { pattern: el.value }); break;
      default: break;
    }
  }

  /* 모두 확정 — 내용 행 즉시 확정 + 비움 승격 이름게이트(ADR-E 반사적 dismiss 봉쇄). */
  async function confirmAll() {
    const res = await Bridge.call(SCREEN, "confirm_all", {});
    const blanks = (res && res.blanks) || [];
    if (!blanks.length) return;
    const ok = window.confirm(
      `아래 ${blanks.length}개 필드는 채우지 않고 '비움'으로 확정합니다:\n\n${blanks.join(", ")}\n\n계속할까요?`
    );
    if (ok) Bridge.call(SCREEN, "confirm_blanks", { fields: blanks });
  }

  /* 저장 — 차단 사유·덮어쓰기 확인 재진술(조용한 덮어쓰기 금지). */
  async function doSave(confirmOverwrite) {
    const res = await Bridge.call(SCREEN, "save", { confirm_overwrite: confirmOverwrite });
    if (res.ok) { alertMsg(`✓ 작업 '${res.saved_name}' 저장됨.`, "ok"); return; }
    if (res.needs_overwrite) {
      if (window.confirm(res.overwrite_text + "\n\n계속할까요?")) doSave(true);
      return;
    }
    alertMsg(res.block_reason || "저장할 수 없습니다.");
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
    const root = $("scr-editor");
    root.addEventListener("click", onClick);
    root.addEventListener("change", onChange);
    Bridge.initial(SCREEN).then(render);
  }

  window.EditorScreen = { init };
})();
