/* TXT 검토·복사 작업대(v6 S7 · 계약 §11) — 재작성 F6 PR-A.

   「문서 만들기」에서 TXT 작업을 실행하면 오는 **몰입 화면**이다. 데이터·범위 선택은 저쪽이
   끝냈고 여기는 진입 시점의 **고정 사본**을 받아 레코드 하나씩 검토·복사한다.

   판정은 전부 Python(workbench 스냅샷)이고 여기는 그리기와 발신만 한다 — 작업점·복사 이력·
   미저장 변경·린트 술어를 웹이 다시 계산하지 않는다. 카드 세그먼트는 공용 SegView 로 그려
   「기안」 카드와 같은 채움 표지 계약(fill 음영·〈빈 값〉·{{토큰}} 빨강)을 쓴다. */
(function () {
  const SCREEN = "workbench";
  const $ = (id) => document.getElementById(id);
  const esc = window.escHtml;
  let LAST = null;

  const OWN_LABEL = { auto: "데이터 열에서", man: "직접 입력한 값" };

  /* ---- 좌 pane: 필드 연결 표 — 「기안」 맞추기 표와 같은 열·같은 동사.
     같은 판정(MappingModel)을 부르므로 어휘를 갈라 두면 그 자체가 드리프트다. */
  function mapRowHtml(s, t, i) {
    const srcSel = t.own === "auto" ? t.source : "";
    const colList = (s.source_fields || []).slice();
    if (srcSel && colList.indexOf(srcSel) < 0) colList.unshift(srcSel);
    const cols = colList.map((c) =>
      `<option value="${esc(c)}"${c === srcSel ? " selected" : ""}>${esc(c)}</option>`).join("");
    const dot = t.own ? `<span class="own ${t.own}" title="${OWN_LABEL[t.own] || ""}"></span>` : "";
    const src =
      `<div class="mapsrc">${dot}` +
      `<select class="field sm mapsrc-sel" id="wbMap-src-${i}" data-i="${i}"` +
      ` aria-label="${esc(t.name)} 데이터 열">` +
      `<option value=""${srcSel === "" ? " selected" : ""}>(직접 입력)</option>${cols}</select>` +
      (t.suggest && t.own !== "auto"
        ? `<button class="btn sm mapsug" id="wbMap-sug-${i}" data-i="${i}"` +
          ` title="이름이 비슷한 열입니다">` +
          `'${esc(t.suggest)}' 적용</button>` : "") +
      (t.can_revert
        ? `<button class="btn sm maprev" id="wbMap-rev-${i}" data-i="${i}">자동으로 되돌리기</button>` : "") +
      `</div>`;
    const typeOpts = ((s.type_options) || []).map((o) =>
      `<option value="${esc(o.code)}"${o.code === t.fmt_kind ? " selected" : ""}>${esc(o.label)}</option>`).join("");
    const typeCell = t.own === "auto"
      ? `<select class="field sm maptype" id="wbMap-type-${i}" data-i="${i}"` +
        ` aria-label="${esc(t.name)} 유형">${typeOpts}</select>`
      : `<span class="muted">—</span>`;
    const fmts = ((s.fmt_options && s.fmt_options[t.fmt_kind]) || []).map((o) =>
      `<option value="${esc(o.code)}"${o.code === t.fmt_code ? " selected" : ""}>${esc(o.label)}</option>`).join("");
    const fmtCell = (t.own === "auto" && fmts)
      ? `<select class="field sm mapfmt" id="wbMap-fmt-${i}" data-i="${i}"` +
        ` aria-label="${esc(t.name)} 표시형">${fmts}</select>`
      : `<span class="muted">—</span>`;
    // 확정-비움(결정 12)은 「아직 안 씀」이 아니라 「비워둠(선언)」이다 — 판정은 서버.
    const declared = !!t.blank_declared;
    const valCell = declared
      ? `<span class="mapval-declared muted" title="비우기로 확정한 값입니다. 복사 전 확인에서 제외됩니다.">비움 확정</span>`
      : `<textarea class="mapval-in${(t.value || "").trim() === "" ? " empty" : ""}" rows="1"` +
        ` id="wbMap-val-${i}" data-i="${i}" placeholder="직접 입력"` +
        ` aria-label="${esc(t.name)} 값">${esc(t.value || "")}</textarea>`;
    const ckCell =
      `<input class="ck mapck" type="checkbox" id="wbMap-ck-${i}" data-i="${i}"` +
      `${t.confirmed ? " checked" : ""}` +
      ` aria-label="${esc(t.name)} 확정">`;
    return `<tr data-i="${i}"${declared ? ' class="row-blank-declared"' : ""}>` +
      `<td class="maptok" title="{{${esc(t.name)}}}">${esc(t.name)}</td>` +
      `<td>${src}</td><td class="maptype-cell">${typeCell}</td>` +
      `<td class="mapfmt-cell">${fmtCell}</td><td class="mapval-cell">${valCell}</td>` +
      `<td class="mapck-cell">${ckCell}</td></tr>`;
  }

  function renderMap(s) {
    const rows = (s.rows || []).map((t, i) => mapRowHtml(s, t, i)).join("");
    $("wbMapPanel").innerHTML =
      `<table class="maptable"><thead><tr>` +
      `<th>항목</th><th>데이터 열</th><th>유형</th><th>표시형</th><th>값</th><th>확정</th>` +
      `</tr></thead><tbody>${rows}</tbody></table>`;
  }

  /* ---- 우 pane: 카드 + 검토 상태 + 린트 */
  const REVIEW_TEXT = {
    todo: ["복사 전", "idle"],
    copied: ["복사 완료", "ok"],
    recheck: ["규칙 변경 뒤 다시 확인 필요", "warn"],
  };

  function renderCard(s) {
    const c = s.card || {};
    $("wbCard").innerHTML = window.SegView.paint(c.segments || []);
    const rv = REVIEW_TEXT[c.review_state] || REVIEW_TEXT.todo;
    $("wbReview").textContent = rv[0];
    $("wbReview").setAttribute("data-level", rv[1]);
    // 정렬 린트(결정 17) — 판정은 서버다(글꼴 이름으로 비례폭을 재판별하지 않는다).
    const lint = c.lint || {};
    const el = $("wbLint");
    el.style.display = lint.active ? "" : "none";
    el.textContent = lint.applied
      ? "연속 공백을 전각으로 바꿔 복사합니다."
      : "이 글꼴에서는 연속 공백이 밀릴 수 있습니다.";
  }

  function renderFoot(s) {
    const c = s.card || {};
    const total = s.total || 0;
    const pos = c.position === null || c.position === undefined ? 0 : c.position + 1;
    $("wbPosition").textContent = `${pos} / ${total}`;
    $("wbCopied").textContent = `${s.copied_count || 0} / ${total}`;
    // 큐 퇴화(승계) — 1건이면 순회할 곳이 없어 큐 장치가 숨는다. 정보가 없어서지 장식이라서가 아니다.
    const degen = !!c.queue_degenerate;
    $("wbPrev").style.display = degen ? "none" : "";
    $("wbNext").style.display = degen ? "none" : "";
    document.querySelector(".wb-adv").style.display = degen ? "none" : "";
    $("wbPrev").disabled = degen || pos <= 1;
    $("wbNext").disabled = degen || pos >= total;
    $("wbAdvance").checked = !!c.advance_after;
    $("wbCopy").disabled = !c.has_current;
    const lc = c.last_copy;
    $("wbNote").textContent = lc
      ? `${lc.row}행을 복사했습니다.`
        + (lc.empty_fields && lc.empty_fields.length
          ? ` (빈 값: ${lc.empty_fields.join(", ")})` : "")
      : (c.source_row ? `원본 ${c.source_row}행` : "");
  }

  function render(s) {
    LAST = s;
    if (!s || !s.open) return;   // 세션 없음 — 화면은 라우팅 가드가 막는다
    $("wbTitle").textContent = s.job_name || "검토·복사";
    $("wbMode").textContent = s.mode_label || "";
    const rev = s.revision || {};
    $("wbRevision").textContent = `템플릿 r${rev.template || 0} · 연결 r${rev.binding || 0}`;
    const d = s.dirty || { count: 0 };
    $("wbDirtyNote").textContent = d.count
      ? `저장하지 않은 변경 ${d.count}건`
      : (d.pending ? "확정하지 않은 편집이 있습니다" : "저장하지 않은 변경 없음");
    $("wbSaveRules").disabled = !s.can_save;
    $("wbSaveRules").title = s.save_block || "";
    document.querySelectorAll("[data-wb-view]").forEach((b) => {
      b.setAttribute("aria-pressed", b.dataset.wbView === s.view ? "true" : "false");
    });
    const n = $("wbNotice");
    n.style.display = (s.notice && s.notice.text) ? "" : "none";
    if (s.notice && s.notice.text) {
      n.textContent = s.notice.text;
      n.className = "note " + (s.notice.level || "muted");
    }
    // Preserve 는 **id 로** 포커스·캐럿을 되찾는다 — 그래서 아래 행 컨트롤에 안정 id 가
    // 붙어 있다. id 없이 재구성하면 push 한 번에 타이핑하던 자리가 body 로 떨어진다.
    window.Preserve.around(() => renderMap(s));
    renderCard(s);
    renderFoot(s);
  }

  /* ---- 발신 */
  function call(action, payload) {
    return window.Bridge.call(SCREEN, action, payload || {});
  }

  async function copyCard() {
    const pre = await call("copy_precheck", {});
    const blockers = [];
    if (pre.missing_fields && pre.missing_fields.length) {
      blockers.push(`채우지 못한 항목: ${pre.missing_fields.join(", ")}`);
    }
    if (pre.empty_fields && pre.empty_fields.length) {
      blockers.push(`값이 빈 항목: ${pre.empty_fields.join(", ")}`);
    }
    if (blockers.length) {
      const ok = await window.Modal.confirm({
        title: "이대로 복사할까요?",
        body: blockers.join("\n") + "\n\n확정-비움으로 선언한 항목은 여기 세지 않습니다.",
        confirmLabel: "그래도 복사",
        cancelLabel: "돌아가기",
      });
      if (!ok) return;
    }
    // 실제 클립보드 쓰기는 브리지가 한다 — 성사 뒤에만 큐·완료 노트가 움직인다.
    await window.Bridge.copyClipboard(SCREEN);
  }

  async function saveRules() {
    const first = await call("save_rules", {});
    if (!first || first.ok === false) {
      if (first && first.error) window.alert(first.error);
      return;
    }
    if (first.needs_confirm) {
      // §11: 영구 저장 확인에는 **모든 dirty 필드를 나열**한다. 이 저장은 다음 실행부터의
      // 기본 규칙을 바꾸므로(override 없음) 무엇이 영구히 달라지는지 세지 않고 누르게 하지 않는다.
      const lead = first.drift
        ? "열어 둔 사이 이 작업이 다른 곳에서 바뀌었습니다. 지금 저장하면 그 변경 위에 아래 연결을 덮어씁니다.\n\n"
        : "";
      const ok = await window.Modal.confirm({
        title: "기본 규칙으로 저장할까요?",
        body: lead + `다음 항목의 연결·표시가 이 작업의 기본 규칙이 됩니다:\n`
          + (first.fields || []).join(", ")
          + "\n\n이미 복사한 항목은 다시 확인이 필요해집니다.",
        confirmLabel: "기본 규칙으로 저장",
        cancelLabel: "취소",
      });
      if (!ok) return;
      const res = await call("save_rules", { confirm: true, confirm_drift: true });
      if (res && res.ok === false && res.error) window.alert(res.error);
    }
  }

  /* ---- 이탈: 단일 관문. 나가는 모든 이동이 여기를 지난다(가드 완전성이 표면 수에
     비례하지 않게 — F7 편집기와 같은 규율). Nav.go 가 위임한다. */
  async function leaveTo(target) {
    const g = await call("leave_guard", {});
    if (g && g.armed) {
      const hasChanges = !!(LAST && LAST.dirty && LAST.dirty.count);
      if (hasChanges) {
        const choice = await window.Modal.choose({
          title: "작업대를 나갈까요?",
          body: g.lines.join("\n"),
          choices: [
            { value: "save", label: "저장하고 나가기" },
            { value: "discard", label: "버리고 나가기" },
            { value: "stay", label: "계속 검토" },
          ],
        });
        if (choice === "stay" || !choice) return;
        if (choice === "save") {
          await saveRules();
          // 저장이 확인 창에서 취소됐으면 여전히 dirty 다 — 그때는 나가지 않는다.
          const after = await call("leave_guard", {});
          if (after && after.armed && LAST && LAST.dirty && LAST.dirty.count) return;
        }
      } else {
        const ok = await window.Modal.confirm({
          title: "작업대를 나갈까요?",
          body: g.lines.join("\n"),
          confirmLabel: "나가기",
          cancelLabel: "계속 검토",
        });
        if (!ok) return;
      }
    }
    await call("close", {});
    window.Nav.go(target, { force: true });
  }

  function wire() {
    $("wbBack").addEventListener("click", () => leaveTo("job"));
    $("wbPrev").addEventListener("click", () => call("step", { delta: -1 }));
    $("wbNext").addEventListener("click", () => call("step", { delta: 1 }));
    $("wbCopy").addEventListener("click", copyCard);
    $("wbSaveRules").addEventListener("click", saveRules);
    $("wbAdvance").addEventListener("change", (e) =>
      call("toggle_advance", { value: e.target.checked }));
    document.querySelectorAll("[data-wb-view]").forEach((b) => {
      b.addEventListener("click", () => call("set_view", { view: b.dataset.wbView }));
    });
    const panel = $("wbMapPanel");
    panel.addEventListener("change", (e) => {
      const el = e.target, i = Number(el.dataset.i);
      if (el.classList.contains("mapsrc-sel")) call("set_source", { index: i, source: el.value });
      else if (el.classList.contains("maptype")) call("set_map_type", { index: i, code: el.value });
      else if (el.classList.contains("mapfmt")) call("set_map_fmt", { index: i, code: el.value });
      else if (el.classList.contains("mapck")) call("set_confirmed", { index: i, value: el.checked });
      else if (el.classList.contains("mapval-in")) call("set_map_value", { index: i, value: el.value });
    });
    panel.addEventListener("click", (e) => {
      const sug = e.target.closest(".mapsug"), rev = e.target.closest(".maprev");
      if (sug) {
        const row = (LAST && LAST.rows) ? LAST.rows[Number(sug.dataset.i)] : null;
        if (row) call("set_source", { index: Number(sug.dataset.i), source: row.suggest });
      } else if (rev) {
        call("revert_map", { index: Number(rev.dataset.i) });
      }
    });
  }

  function init() {
    wire();
    window.Bridge.onPush(SCREEN, render);
  }

  window.WorkbenchScreen = { init, render, leaveTo };
})();
