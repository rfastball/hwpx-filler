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

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    Preserve.around(() => {  // 마법사 폼 포커스·캐럿·본문 스크롤 보존(#28)
      LAST = s;
      $("editor-steps").innerHTML = stepHeader(s);
      $("editor-body").innerHTML = stepBody(s);
      $("editor-foot").innerHTML = footer(s);
    });
  }

  function stepHeader(s) {
    return STEP_TITLES.map((t, i) => {
      const cur = i === s.step ? ' aria-current="true"' : "";
      const done = i < s.step ? " done" : "";
      return `<div class="wstep-tab${done}"${cur}><span class="k">${i + 1}</span>${esc(t)}</div>`;
    }).join("");
  }

  function stepBody(s) {
    // 세션 통지(#26) — 편집 복원·프로파일 반영·데이터 교체 보존을 시끄럽게 재진술.
    const notice = s.notice
      ? `<p class="note ${s.notice.level === "ok" ? "okbox" : "warnbox"}" style="white-space:pre-line">${esc(s.notice.text)}</p>`
      : "";
    if (s.step === 0) return notice + step0(s);
    if (s.step === 1) return notice + step1(s);
    if (s.step === 2) return notice + step2(s);
    return notice + step3(s);
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
        ${s.base_name ? `<span class="muted" style="font-size:12px">프로파일: ${esc(s.base_name)}</span>` : ""}
        <span style="flex:1"></span>
        <button class="btn" data-act="profile-apply">프로파일 적용…</button>
        <button class="btn" data-act="profile-save">프로파일로 저장…</button>
        <button class="btn" data-act="profile-delete">프로파일 삭제…</button>
        <button class="btn" data-act="confirm-all">모두 확정</button>
        <button class="btn" data-act="unconfirm-all">모두 해제</button>
      </div>`;
  }

  function mapRow(r, s) {
    const known = (s.source_fields || []).includes(r.source);
    const srcOpts = [`<option value=""${r.source ? "" : " selected"}>(비움)</option>`]
      .concat((s.source_fields || []).map((f) =>
        `<option value="${esc(f)}"${f === r.source ? " selected" : ""} title="${esc(f)}">${esc(f)}</option>`))
      // 복원·데이터 교체로 현재 소스 목록에 없는 소스를 참조하는 행 — (비움)으로
      // 오표시하지 않고 명시 옵션으로 시끄럽게 드러낸다(#26 조용한 소실 금지).
      .concat(r.source && !known
        ? [`<option value="${esc(r.source)}" selected title="현재 데이터에 없는 소스">${esc(r.source)} (데이터에 없음)</option>`]
        : [])
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
    return `<div class="wtitle">4단계 — 작업 저장${s.editing_origin ? ` <span class="pill">편집: ${esc(s.editing_origin)}</span>` : ""}</div>
      <p class="wsub">이 작업(템플릿·매핑·파일명)을 저장합니다. 데이터·행은 저장하지 않습니다 —
        실행할 때 고릅니다.</p>
      <div class="row" style="margin-bottom:9px"><span class="lbl" style="width:76px">작업 이름</span>
        <input class="field" data-act="name" value="${esc(s.name)}" placeholder="예: 공고서 자동생성"></div>
      <div class="row"><span class="lbl" style="width:76px">파일명 패턴</span>
        <input class="field mono" data-act="pattern" value="${esc(s.pattern)}"></div>
      ${datasetBlock(s)}
      ${filenameTokenHelp(s)}
      <div id="save-msg" class="note" style="display:none"></div>`;
  }

  /* 선언 데이터 자동등록(#26/#18 31A5A484-C) — 검토용으로 고른 데이터를 등록 데이터로
     자동등록한다. 참조(경로·시트)만 저장 — 행·내용은 저장하지 않는다. */
  function datasetBlock(s) {
    if (!s.data_path) return "";
    return `<div class="grp" style="margin-top:10px">
      <span class="cap">선언 데이터 자동등록</span>
      <p class="hint" style="margin-top:0">저장하면 이 작업이 쓴 데이터(${esc(s.data_name)})를
        등록 데이터로 함께 등록합니다 — 경로 참조만 저장(행·내용 없음), 실행 때 다시 읽습니다.</p>
      <div class="row"><span class="lbl" style="width:76px">등록 이름</span>
        <input class="field" data-act="dataset-name" value="${esc(s.dataset_name)}"></div>
    </div>`;
  }

  /* 파일명 패턴 토큰 도우미(#17) — Qt SaveJobPage._refresh_filename_help 웹 포트.
     s.rows 는 스텝2 매핑 확정 시점에 이미 계산돼 스냅샷에 실려온다 — 신규 브리지 호출 없음. */
  function filenameTokenHelp(s) {
    const rows = (s.rows || []).filter((r) => r.has_content);
    const fieldsHtml = rows.length
      ? rows.map((r) => `<code>{{${esc(r.template_field)}}}</code> → ${fnPreviewText(r, s)}`).join(" &nbsp;·&nbsp; ")
      : `<span class="muted">매핑을 완료하면 파일명에 쓸 수 있는 필드가 여기 표시됩니다.</span>`;
    return `<div class="grp" style="margin-top:10px">
      <span class="cap">파일명에 넣을 수 있는 값</span>
      <p class="hint" style="margin-top:0">${fieldsHtml}</p>
      <p class="hint">
        날짜: <code>{{date}}</code> → 생성 날짜(YYYYMMDD) · <code>{{date:YYYY-MM-DD}}</code> → 하이픈 포함 날짜<br>
        순번: <code>{{seq}}</code> → 1부터 증가 · <code>{{seq:001}}</code> → 001부터 세 자리로 증가
      </p>
    </div>`;
  }

  function fnPreviewText(r, s) {
    if (r.preview_error) return `<span class="pv emptyval">(미리보기 오류)</span>`;
    if (r.preview_empty) return `<span class="pv emptyval">${s.record_count ? "(빈 값)" : "(샘플 데이터 없음)"}</span>`;
    let display = String(r.preview).replace(/[\r\n]+/g, " ");
    if (display.length > 40) display = display.slice(0, 39) + "…";
    return `<span class="pv">${esc(display)}</span>`;
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
    // 브리지 rejection 이 unhandled 로 삼켜지면 버튼이 조용히 무반응이 된다 — 개별 핸들러가
    // 아니라 디스패처에서 한 번에 loud 재진술한다(pool.js onListClick 미러, #45). 새 case 가
    // 늘어도 가드를 자동 상속한다(profile_* 만 봉합하고 confirmAll 을 빠뜨렸던 재발 방지).
    try {
      switch (act) {
        case "pick-template": {
          // 새 템플릿 선택 = 새 작업 세션 → 미저장 세션은 조용히 버리지 않고 확인(#25).
          if (LAST && LAST.has_unsaved_work && !window.confirm(
            "저장하지 않은 작업 세션이 있습니다.\n" +
            "새 템플릿으로 시작하면 이전의 이름·데이터·매핑이 사라집니다.\n\n계속할까요?")) break;
          const r = await Bridge.pickTemplateFile(SCREEN);
          if (typeof r === "string" && r.startsWith("ERROR:")) alertMsg(r.slice(6).trim());
          break;
        }
        case "ack-gate": Bridge.call(SCREEN, "ack_gate", {}); break;
        case "pick-data": {
          let r = await Bridge.pickDataFile(SCREEN);
          if (r && typeof r === "object" && r.needs_sheet) {   // 다중 시트 → 확정 게이트(#33)
            r = await SheetPicker.choose(SCREEN, r);
            if (r === null) break;                              // 취소 = 중단(첫 시트 강등 없음)
          }
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
        case "save": await doSave({}); break;
        case "profile-apply": await profileApply(); break;
        case "profile-save": await profileSave(); break;
        case "profile-delete": await profileDelete(); break;
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
      case "row-source": Bridge.call(SCREEN, "set_source", { index: idx, source: el.value }); break;
      case "row-type": Bridge.call(SCREEN, "set_type", { index: idx, type: el.value }); break;
      case "row-fmt": Bridge.call(SCREEN, "set_fmt", { index: idx, fmt: el.value }); break;
      case "row-const": Bridge.call(SCREEN, "set_const", { index: idx, const: el.value }); break;
      case "name": Bridge.call(SCREEN, "set_name", { name: el.value }); break;
      case "pattern": Bridge.call(SCREEN, "set_pattern", { pattern: el.value }); break;
      case "dataset-name": Bridge.call(SCREEN, "set_dataset_name", { name: el.value }); break;
      default: break;
    }
  }

  /* ---- 매핑 프로파일(#26 #5) — 목록 재진술 → 이름 확정 → 반영/저장(확인 라운드트립).
     브리지 rejection(디스크·권한 등) 가드는 onClick 디스패처가 소유한다(#45) —
     여기 함수들은 await 로 던지기만 하면 조용한 무반응 없이 loud 재진술된다. ---- */
  async function profileApply() {
    const res = await Bridge.call(SCREEN, "profile_list", {});
    const bases = (res && res.bases) || [];
    const corrupt = ((res && res.corrupted) || [])
      .map((c) => `! ${c.file} — 손상: ${c.error}`).join("\n");
    if (!bases.length) {
      window.alert("저장된 매핑 프로파일이 없습니다." + (corrupt ? "\n\n" + corrupt : ""));
      return;
    }
    const listing = bases
      .map((b) => `· ${b.name} (필드 ${b.field_count} · 참조 작업 ${b.job_refs})`).join("\n");
    const name = window.prompt(
      `적용할 프로파일 이름을 입력하세요:\n\n${listing}${corrupt ? "\n" + corrupt : ""}`,
      bases[0].name);
    if (name === null || !name.trim()) return;
    const r = await Bridge.call(SCREEN, "profile_apply", { name: name.trim() });
    if (r && r.ok === false) window.alert(r.error || "프로파일을 적용할 수 없습니다.");
  }

  async function profileSave() {
    const name = window.prompt("저장할 프로파일 이름:", (LAST && LAST.base_name) || "");
    if (name === null || !name.trim()) return;
    let r = await Bridge.call(SCREEN, "profile_save", { name: name.trim() });
    if (r && r.needs_confirm) {
      if (!window.confirm(r.confirm_text)) return;
      r = await Bridge.call(SCREEN, "profile_save", { name: name.trim(), confirm: true });
    }
    if (r && r.ok === false) window.alert(r.error || "프로파일을 저장할 수 없습니다.");
  }

  async function profileDelete() {
    const res = await Bridge.call(SCREEN, "profile_list", {});
    const bases = (res && res.bases) || [];
    if (!bases.length) {
      window.alert("저장된 매핑 프로파일이 없습니다.");
      return;
    }
    const listing = bases
      .map((b) => `· ${b.name} (필드 ${b.field_count} · 참조 작업 ${b.job_refs})`).join("\n");
    const name = window.prompt(`삭제할 프로파일 이름을 입력하세요:\n\n${listing}`, "");
    if (name === null || !name.trim()) return;
    let r = await Bridge.call(SCREEN, "profile_delete", { name: name.trim() });
    if (r && r.needs_confirm) {
      // 파괴 확정 — 참조 작업 수를 재진술한 뒤에만 삭제(confirm-or-alarm).
      if (!window.confirm(r.confirm_text)) return;
      r = await Bridge.call(SCREEN, "profile_delete", { name: name.trim(), confirm: true });
    }
    if (r && r.ok === false) window.alert(r.error || "프로파일을 삭제할 수 없습니다.");
  }

  /* 모두 확정 — 내용 행 즉시 확정 + 비움 승격 이름게이트(ADR-E 반사적 dismiss 봉쇄). */
  async function confirmAll() {
    const res = await Bridge.call(SCREEN, "confirm_all", {});
    const blanks = (res && res.blanks) || [];
    if (!blanks.length) return;
    const ok = window.confirm(
      `아래 ${blanks.length}개 필드는 채우지 않고 '비움'으로 확정합니다:\n\n${blanks.join(", ")}\n\n계속할까요?`
    );
    // await 로 던진다 — fire-and-forget 이면 rejection 이 디스패처 가드 밖으로 샌다(#45).
    if (ok) await Bridge.call(SCREEN, "confirm_blanks", { fields: blanks });
  }

  /* 저장 — 차단 사유·덮어쓰기·자동등록 확인 재진술(조용한 덮어쓰기 금지).
     flags 는 확인 라운드트립을 누적한다({confirm_overwrite, confirm_dataset}).
     브리지 예외도 잡아 표시한다 — 백엔드가 반저장(작업 저장 후 실패) 상태로 던지면
     화면이 무반응이 되는 함정 봉쇄(실패는 언제나 시끄럽게). */
  async function doSave(flags) {
    let res;
    try {
      res = await Bridge.call(SCREEN, "save", flags || {});
    } catch (err) {
      window.alert("저장 처리 중 오류가 발생했습니다 — 작업이 저장됐는지 홈에서 확인하세요.\n" + err);
      return;
    }
    if (!res || typeof res !== "object") {
      alertMsg("저장 결과를 확인할 수 없습니다 — 작업이 저장됐는지 홈에서 확인하세요.");
      return;
    }
    if (res.ok) {
      let msg = `✓ 작업 '${res.saved_name}' 저장됨.`;
      if (res.dataset_registered) msg += ` 데이터 '${res.dataset_registered}' 등록됨.`;
      if (res.dataset_register_error) {
        // 반저장(작업 저장 성공 + 데이터 등록 실패) — 성공으로 뭉개지 않고 경고로 재진술.
        alertMsg(msg + " " + res.dataset_register_error);
      } else {
        alertMsg(msg, "ok");
      }
      return;
    }
    if (res.needs_overwrite) {
      if (window.confirm(res.overwrite_text + "\n\n계속할까요?")) {
        doSave(Object.assign({}, flags, { confirm_overwrite: true }));
      }
      return;
    }
    if (res.needs_dataset_confirm) {
      if (window.confirm(res.dataset_text)) {
        doSave(Object.assign({}, flags, { confirm_dataset: true }));
      }
      return;
    }
    alertMsg(res.dataset_error || res.block_reason || "저장할 수 없습니다.");
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
