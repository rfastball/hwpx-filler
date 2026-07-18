/* 즉시 기안(txt) 화면 — 브리지로 링1 TxtDraftViewModel 과 왕복. 첫 실화면(스파이크 승격).
   렌더는 Python 이 window.__push('txt', snapshot) 로 밀어 넣는다(관측 방향). 프리뷰 재진술
   (빨강 항목없음 {{토큰}}·〈빈 값〉)은 표현 계층이라 여기서 만든다 = 링2 대체, VM 로직 아님. */
(function () {
  const SCREEN = "txt";
  const $ = (id) => document.getElementById(id);
  const STATE_LABEL = { fill: "✓ 채움", blank: "◦ 빈 값", missing: "● 항목 없음" };
  let LAST = null;

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js) — " 도 escape 해 속성 컨텍스트 안전

  /* 템플릿 토큰을 레코드로 치환하되 미충족을 명시 재진술 — txt_view._build_preview_html 의 웹 이식.
     항목없음=빨강 {{토큰}}, 빈값=〈빈 값〉 마커, 채움=값 그대로. VM 로직 아님(순수 표현). */
  function buildPreview(template, record) {
    const re = /\{\{\s*([^{}|]+?)\s*\}\}/g;
    let out = "", last = 0, m;
    while ((m = re.exec(template)) !== null) {
      out += esc(template.slice(last, m.index));
      const name = m[1].trim();
      if (!(name in record)) {
        out += `<span class="tok-missing">{{${esc(name)}}}</span>`;
      } else {
        const v = record[name] ?? "";
        out += String(v).trim() === "" ? `<span class="tok-blank">〈빈 값〉</span>` : esc(v);
      }
      last = re.lastIndex;
    }
    out += esc(template.slice(last));
    return out;
  }

  /* Python→웹 푸시 렌더. Bridge.onPush 로 등록된다. */
  function render(s) {
    Preserve.around(() => {  // 재구성 가로질러 포커스·캐럿·프리뷰/토큰 스크롤 보존(#28)
      LAST = s;
      // 템플릿 콤보를 스냅샷에 동기(F11) — 서버측 선택 변경(새 기안 초기화·홈 '기안
      // 열기' 진입)이 콤보에 보이게. 옵션에 없는 이름(붙여넣은 텍스트)은 선택 해제로 남는다.
      const sel = $("tplSel");
      if (sel.value !== s.template_name) sel.value = s.template_name;
      $("recIdx").textContent = `${s.record_index} / ${s.record_count}`;
      $("recPrev").disabled = s.record_count <= 1;
      $("recNext").disabled = s.record_count <= 1;

      const rows = s.tokens.map((t) =>
        `<div class="tok ${t.state}">` +
        `<span class="tname" title="{{${esc(t.name)}}}">{{${esc(t.name)}}}</span>` +
        `<span class="st">${STATE_LABEL[t.state]}</span></div>`
      ).join("");
      $("tokPanel").innerHTML = rows || `<p class="muted">토큰이 없는 템플릿입니다.</p>`;

      $("renderView").innerHTML = buildPreview(s.template_text, s.record);
      // 소스 종류 병기 라벨(#26 #6) — 서버가 플래그에서 합성(K8)·화면별 고유 id(#27), run/matrix 와 분리.
      $("txtDataLabel").value = s.data_source_label || "";
      setStatus(s.missing_fields, s.empty_fields);
      resetNote();
    });
  }

  function setStatus(missing, empty) {
    const pill = $("txtStatus");
    if (missing.length) { pill.dataset.level = "warn"; pill.textContent = `항목 없음 ${missing.length}`; }
    else if (empty.length) { pill.dataset.level = "warn"; pill.textContent = `빈 값 ${empty.length}`; }
    else { pill.dataset.level = "ok"; pill.textContent = "전량 채움"; }
  }

  function resetNote() {
    const n = $("txtNote");
    n.dataset.level = "idle";
    n.textContent = "복사가 commit — 실시간 view가 곧 산출물. 항목 없는 토큰은 그대로 노출됩니다.";
  }

  /* 완료 동작(복사/저장) 후 리포트를 재진술 — confirm-or-alarm: 미충족 포함 시 시끄럽게. */
  function announce(action, report) {
    const n = $("txtNote");
    const mi = report.missing_fields || [], em = report.empty_fields || [];
    if (mi.length) { n.dataset.level = "warn"; n.textContent = `⚠ 항목 없음 ${mi.length}건(${mi.join(", ")}) 포함 ${action}됨 — 빨간 토큰 확인 후 사용하세요.`; }
    else if (em.length) { n.dataset.level = "warn"; n.textContent = `⚠ 빈 값 ${em.length}건(${em.join(", ")}) 포함 ${action}됨 — 확인 후 사용하세요.`; }
    else { n.dataset.level = "ok"; n.textContent = `✓ 전량 채움 ${action} 완료.`; }
  }

  function warnNote(msg) {
    const n = $("txtNote"); n.dataset.level = "warn"; n.textContent = "⚠ " + msg;
  }

  /* 웹→Python 이벤트 배선. */
  function wire() {
    $("tplSel").addEventListener("change", (e) =>
      Bridge.call(SCREEN, "select_template", { name: e.target.value }));
    $("recPrev").addEventListener("click", () => Bridge.call(SCREEN, "step", { delta: -1 }));
    $("recNext").addEventListener("click", () => Bridge.call(SCREEN, "step", { delta: 1 }));

    $("btnPick").addEventListener("click", async () => {
      let r = await Bridge.pickDataFile(SCREEN);
      if (r && typeof r === "object" && r.needs_sheet) {   // 다중 시트 → 확정 게이트(#33)
        r = await SheetPicker.choose(SCREEN, r);
        if (r === null) return;                            // 취소 = 중단(첫 시트 강등 없음)
      }
      if (r === null) return;                      // 취소
      if (typeof r === "string" && r.startsWith("ERROR:")) { warnNote(r.slice(6).trim()); return; }
      // 파일명은 load_data_path 가 스냅샷(data_label)으로 밀어 render 가 채운다(P4 서버 소유).
    });
    // 등록 데이터(풀) 겨눔(#26 #6) — 취소=중단, 실패는 모달 안에서 재진술(PoolPicker).
    $("btnTxtPoolData").addEventListener("click", async () => {
      await PoolPicker.choose(SCREEN);             // 라벨은 스냅샷(data_source_label)이 채운다
    });

    $("btnCopy").addEventListener("click", async () =>
      announce("복사", await Bridge.copyClipboard(SCREEN)));
    $("btnSave").addEventListener("click", async () => {
      const r = await Bridge.saveFile(SCREEN);
      if (r) announce("저장", r);
    });

    // 붙여넣기 모달(세션 템플릿) — 개폐·초기포커스·복귀·Escape 는 Modal 헬퍼가 소유(#27/#28).
    $("btnPaste").addEventListener("click", () => {
      $("pasteText").value = LAST ? LAST.template_text : "";
      window.Modal.open("pasteModal", { initialFocus: $("pasteText") });
    });
    $("pasteCancel").addEventListener("click", () => window.Modal.close("pasteModal"));
    $("pasteOk").addEventListener("click", () => {
      // 템플릿만 바꾼다 — 겨눈 데이터는 유지(VM datasource 불변). 라벨은 스냅샷이 실상태 반영(P4).
      Bridge.call(SCREEN, "set_template_text", { text: $("pasteText").value });
      window.Modal.close("pasteModal");
    });
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    wire();
    const initState = await Bridge.initial(SCREEN);
    const sel = $("tplSel");
    sel.innerHTML = initState.templates
      .map((n) => `<option value="${esc(n)}">${esc(n)}.txt</option>`).join("");
    if (initState.templates.length) sel.value = initState.template_name;
    render(initState);
  }

  window.TxtScreen = { init };
})();
