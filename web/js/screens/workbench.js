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
      `<select class="field sm mapsrc-sel" id="wbMap-src-${encodeURIComponent(t.name)}" data-name="${esc(t.name)}"` +
      ` aria-label="${esc(t.name)} 데이터 열">` +
      `<option value=""${srcSel === "" ? " selected" : ""}>(직접 입력)</option>${cols}</select>` +
      (t.suggest && t.own !== "auto"
        ? `<button class="btn sm mapsug" id="wbMap-sug-${encodeURIComponent(t.name)}" data-name="${esc(t.name)}"` +
          ` title="이름이 비슷한 열입니다">` +
          `'${esc(t.suggest)}' 적용</button>` : "") +
      (t.can_revert
        ? `<button class="btn sm maprev" id="wbMap-rev-${encodeURIComponent(t.name)}" data-name="${esc(t.name)}">자동으로 되돌리기</button>` : "") +
      `</div>`;
    const typeOpts = ((s.type_options) || []).map((o) =>
      `<option value="${esc(o.code)}"${o.code === t.fmt_kind ? " selected" : ""}>${esc(o.label)}</option>`).join("");
    const typeCell = t.own === "auto"
      ? `<select class="field sm maptype" id="wbMap-type-${encodeURIComponent(t.name)}" data-name="${esc(t.name)}"` +
        ` aria-label="${esc(t.name)} 유형">${typeOpts}</select>`
      : `<span class="muted">—</span>`;
    const fmts = ((s.fmt_options && s.fmt_options[t.fmt_kind]) || []).map((o) =>
      `<option value="${esc(o.code)}"${o.code === t.fmt_code ? " selected" : ""}>${esc(o.label)}</option>`).join("");
    const fmtCell = (t.own === "auto" && fmts)
      ? `<select class="field sm mapfmt" id="wbMap-fmt-${encodeURIComponent(t.name)}" data-name="${esc(t.name)}"` +
        ` aria-label="${esc(t.name)} 표시형">${fmts}</select>`
      : `<span class="muted">—</span>`;
    // 확정-비움(결정 12)은 「아직 안 씀」이 아니라 「비워둠(선언)」이다 — 판정은 서버.
    const declared = !!t.blank_declared;
    const valCell = declared
      ? `<span class="mapval-declared muted" title="비우기로 확정한 값입니다. 복사 전 확인에서 제외됩니다.">비움 확정</span>`
      : `<textarea class="mapval-in${(t.value || "").trim() === "" ? " empty" : ""}" rows="1"` +
        ` id="wbMap-val-${encodeURIComponent(t.name)}" data-name="${esc(t.name)}" placeholder="직접 입력"` +
        ` aria-label="${esc(t.name)} 값">${esc(t.value || "")}</textarea>`;
    const ckCell =
      `<input class="ck mapck" type="checkbox" id="wbMap-ck-${encodeURIComponent(t.name)}" data-name="${esc(t.name)}"` +
      `${t.confirmed ? " checked" : ""}` +
      ` aria-label="${esc(t.name)} 확정">`;
    return `<tr data-name="${esc(t.name)}"${declared ? ' class="row-blank-declared"' : ""}>` +
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
    // 린트는 **표지 + 행동**이 한 벌이다(2R P2). 「기안」에서 옮겨 온 것은 경고 문안만이
    // 아니라 그 처방(전각 치환)이다 — 판정 G 가 말한 「거처만 옮긴다」는 행동까지 포함한다.
    // 경고만 두면 사용자는 문제를 통보받고 손잡이는 없는 상태가 된다.
    const lint = c.lint || {};
    const el = $("wbLint");
    el.style.display = lint.active ? "" : "none";
    el.innerHTML = lint.applied
      ? "연속 공백을 전각으로 바꿔 복사합니다. "
        + `<button class="btn sm" type="button" id="wbLintAction" data-fullwidth="off">되돌리기</button>`
      : "이 글꼴에서는 연속 공백이 밀릴 수 있습니다. "
        + `<button class="btn sm" type="button" id="wbLintAction" data-fullwidth="on">전각으로 바꾸기</button>`;
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
    // 경계 판정은 **Python 이 낸다**(2R P1) — 표시 서수는 고정 사본의 자리이고 순회는 큐
    // 순서라 서로 다른 질문이다. 표면이 서수로 경계를 계산하면 복사 직후 그 카드에 갇힌다.
    $("wbPrev").disabled = degen || !c.can_prev;
    $("wbNext").disabled = degen || !c.can_next;
    $("wbAdvance").checked = !!c.advance_after;
    // 복사 차단은 **Python 이 낸 사유**로 닫는다(`copy_block`) — 원문 보기는 채우지 않은
    // 템플릿을 그리므로, 활성으로 두면 화면엔 `{{수신}}` 이 보이는데 클립보드엔 채운
    // 문장이 나간다(「보이는 것 = 복사되는 것」, 결정 17).
    $("wbCopy").disabled = !c.has_current || !!c.copy_block;
    $("wbCopy").title = c.copy_block || "";
    const lc = c.last_copy;
    // 복사는 성사됐는데 **최근 사용 기록이 실패**했으면 그 사실을 병기한다(4R P2) —
    // 백엔드가 일부러 남긴 사유를 표면이 안 읽으면, 무조건 성공 문안이 뜨고 이력은 조용히
    // 빠진다. HWPX 완료 요약이 스탬프 실패를 병기하는 것과 같은 규율이다.
    $("wbNote").textContent = lc
      ? `${lc.row}행을 복사했습니다.`
        + (lc.empty_fields && lc.empty_fields.length
          ? ` (빈 값: ${lc.empty_fields.join(", ")})` : "")
        + (lc.stamp_error ? ` — 최근 사용 기록은 실패했습니다: ${lc.stamp_error}` : "")
      : (c.source_row ? `원본 ${c.source_row}행` : "");
  }

  const DOT_STATE_LABEL = { current: "작업 중", copied: "복사 완료", uncopied: "대기" };

  function renderDots(s) {
    const c = s.card || {};
    const order = c.index_map || [];
    const host = $("wbDots");
    host.hidden = !!c.queue_degenerate;      // 1건이면 순회할 곳이 없다(승계 규칙)
    if (host.hidden) { host.innerHTML = ""; return; }
    host.innerHTML = order.map((d) => {
      const label = DOT_STATE_LABEL[d.state] || d.state;
      const why = label + (d.recheck ? " · 다시 확인 필요" : "");
      return `<button class="wc-dot ${d.state}${d.recheck ? " gap" : ""}" role="listitem"` +
        ` data-i="${d.index}" aria-label="${d.row}행 ${why}" title="${d.row}행 · ${why}"></button>`;
    }).join("");
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
    // 대상 글꼴은 앱 전역 선언이라 저쪽에서 바뀔 수 있다 — 스냅샷 값을 따라간다.
    const font = $("wbTargetFont");
    if (document.activeElement !== font && font.value !== (s.target_font || "")) {
      font.value = s.target_font || "";
    }
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
    renderDots(s);
    renderFoot(s);
  }

  /* ---- 발신 — `Bridge.call(SCREEN, …)` 을 **직접** 부른다. 로컬 래퍼를 두면 정적 가드
     (test_dispatch_wiring 의 리터럴 추출)가 이 화면을 못 보고 **공허하게 통과**한다: 첫 판이
     래퍼를 쓴 탓에 미등록 페이로드 키가 실 브리지에서만 드러났다(1R P1). 그래서 직렬화도
     래퍼가 아니라 **호출 자리마다** `Intent.chained` 로 감싼다 — 리터럴은 그대로 남는다.

     **이 화면의 상태는 하나라 체인도 하나다**(8R P1). 작업점·보기·전각·맞추기 표는 전부
     같은 세션을 바꾸고 같은 카드를 다시 그린다 — 축별로 체인을 가르면 「값을 고치고 곧바로
     유형을 고쳤다」가 서로를 추월할 수 있다. 커밋(복사·저장·이탈)은 이 체인을 **먼저
     정산**한다: 그것들이 읽는 것이 바로 이 발신들이 쓴 상태다. */
  const WB_CHAIN = "workbench:session";

  function sendWb(call) {
    return window.Intent.chained(WB_CHAIN, call);
  }

  async function copyCard() {
    // 방금 친 값이 아직 날아가는 중일 수 있다 — 그것이 착지한 **뒤에** 무엇을 복사할지 묻는다.
    // (blur 로 발화한 `set_map_value` 와 이 클릭은 서로 다른 스레드로 도착한다.)
    await window.Intent.settle(WB_CHAIN);
    const pre = await window.Bridge.call(SCREEN, "copy_precheck", {});
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
    // **사전확인이 본 그 카드**의 토큰을 실어 보낸다(3R P1): 그사이 작업점이 옮겨졌거나
    // 규칙이 바뀌었으면 백엔드가 쓰지 않고 stale 로 돌려주므로, 확인하지 않은 카드가
    // 클립보드로 나가지 않는다. 조용한 무동작이 아니라 다시 확인하라고 말한다.
    const res = await window.Bridge.copyClipboard(SCREEN, pre.token);
    if (res && res.stale) {
      window.alert("작업점이 그사이 바뀌어 복사하지 않았습니다. 카드를 확인하고 다시 복사하세요.");
    } else if (res && res.error) {
      window.alert(res.error);   // 차단 사유(보기 축 등)는 조용한 무동작으로 두지 않는다
    }
  }

  async function saveRules() {
    // 저장이 세는 dirty 집합도 대기 중인 편집을 포함해야 한다 — 안 그러면 확인 문안이
    // 나열하지 않은 필드가 같이 저장되거나(과소 재진술) 방금 친 값만 빠진다.
    await window.Intent.settle(WB_CHAIN);
    let r = await window.Bridge.call(SCREEN, "save_rules", {});
    // 확인 문안을 **되돌려 보낸다**(confirmed_text) — 백엔드가 잠금 안에서 지금 문안을 다시
    // 지어 대조하므로, 모달이 열린 사이 대상이 바뀌었으면(TOCTOU) 새 문안으로 다시 묻는다.
    // 「기안으로 저장」·에디터 덮어쓰기와 **같은 관용구**다: 불리언 플래그로는 「이 상황을
    // 확인했다」와 「어떤 상황을 확인했다」가 구별되지 않아, 첫 판은 클라이언트가 외부 변경을
    // 미리 승인해 버렸다(1R P2). 문안 자체가 확인의 정체라 while 로 재확인을 받는다.
    while (r && r.needs_confirm) {
      const confirmedText = r.confirm_text;
      const ok = await window.Modal.confirm({
        title: "기본 규칙으로 저장할까요?",
        body: confirmedText,
        confirmLabel: "기본 규칙으로 저장",
        cancelLabel: "취소",
      });
      if (!ok) return;
      r = await window.Bridge.call(SCREEN, "save_rules",
        { confirm: true, confirmed_text: confirmedText });
    }
    if (r && r.ok === false && r.error) window.alert(r.error);  // 게이트 실패는 시끄럽게
  }

  /* ---- 이탈: 단일 관문. 나가는 모든 이동이 여기를 지난다(가드 완전성이 표면 수에
     비례하지 않게 — F7 편집기와 같은 규율). Nav.go 가 위임한다. */
  async function leaveTo(target) {
    // 가드가 「잃을 것 없음」이라고 답하려면 **대기 중인 편집까지** 세고 답해야 한다.
    // 정산 전에 물으면 방금 친 값이 가드에 안 잡히고 세션과 함께 조용히 사라진다.
    await window.Intent.settle(WB_CHAIN);
    const g = await window.Bridge.call(SCREEN, "leave_guard", {});
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
          const after = await window.Bridge.call(SCREEN, "leave_guard", {});
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
    await window.Bridge.call(SCREEN, "close", {});
    window.Nav.go(target, { force: true });
  }

  function wire() {
    $("wbBack").addEventListener("click", () => leaveTo("job"));
    $("wbPrev").addEventListener("click", () =>
      sendWb(() => window.Bridge.call(SCREEN, "step", { delta: -1 })));
    $("wbNext").addEventListener("click", () =>
      sendWb(() => window.Bridge.call(SCREEN, "step", { delta: 1 })));
    $("wbCopy").addEventListener("click", copyCard);
    $("wbSaveRules").addEventListener("click", saveRules);
    $("wbTargetFont").addEventListener("change", (e) =>
      sendWb(() => window.Bridge.call(SCREEN, "set_target_font", { font: e.target.value })));
    // 큐 색인 직접 이동 — 아는 행으로 바로 간다(순차 이동만으로는 도달할 수 없던 자리).
    $("wbDots").addEventListener("click", (e) => {
      const dot = e.target.closest(".wc-dot");
      if (dot) sendWb(() => window.Bridge.call(SCREEN, "set_current", { index: Number(dot.dataset.i) }));
    });
    $("wbAdvance").addEventListener("change", (e) =>
      sendWb(() => window.Bridge.call(SCREEN, "toggle_advance", { value: e.target.checked })));
    document.querySelectorAll("[data-wb-view]").forEach((b) => {
      b.addEventListener("click", () =>
        sendWb(() => window.Bridge.call(SCREEN, "set_view", { view: b.dataset.wbView })));
    });
    // 린트 행동은 매 렌더마다 다시 그려지므로 위임으로 받는다(안정 id 는 포커스 보존용).
    $("wbLint").addEventListener("click", (e) => {
      const b = e.target.closest("[data-fullwidth]");
      if (b) sendWb(() => window.Bridge.call(SCREEN, "set_fullwidth", { value: b.dataset.fullwidth === "on" }));
    });
    const panel = $("wbMapPanel");
    // 행은 **토큰 이름**으로 겨눈다(F6 3R — 「기안」과 같은 규약). 결속은 직접 입력한 값을
    // 지울 수 있어 확인 왕복을 가진다: 백엔드가 `{confirm: 문안}` 을 돌려주면 물어보고
    // `confirm:true` 로 다시 보낸다(무확인 파괴 금지).
    async function bindColumn(name, col) {
      const r = await sendWb(() => window.Bridge.call(SCREEN, "set_source", { name, col }));
      if (r && r.confirm) {
        const ok = await window.Modal.confirm({
          title: "직접 입력한 값을 덮어쓸까요?", body: r.confirm,
          confirmLabel: "열 값으로 바꾸기", cancelLabel: "취소", danger: true,
        });
        if (!ok) { render(LAST); return; }   // 드롭다운을 스냅샷 상태로 되돌린다
        await sendWb(() => window.Bridge.call(SCREEN, "set_source", { name, col, confirm: true }));
      }
    }
    panel.addEventListener("change", (e) => {
      const el = e.target, name = el.dataset.name;
      if (!name) return;
      if (el.classList.contains("mapsrc-sel")) bindColumn(name, el.value);
      else if (el.classList.contains("maptype"))
        sendWb(() => window.Bridge.call(SCREEN, "set_map_type", { name, type: el.value }));
      else if (el.classList.contains("mapfmt"))
        sendWb(() => window.Bridge.call(SCREEN, "set_map_fmt", { name, code: el.value }));
      else if (el.classList.contains("mapck"))
        sendWb(() => window.Bridge.call(SCREEN, "set_confirmed", { name, value: el.checked }));
      else if (el.classList.contains("mapval-in")) {
        // 값 입력은 no-push 다(포커스된 입력을 서버 푸시가 재구성하지 않게) — 반환 스냅샷으로
        // 그린다. 재구성을 가로지르는 캐럿은 Preserve 가 안정 id 로 되찾는다.
        sendWb(() => window.Bridge.call(SCREEN, "set_map_value", { name, text: el.value }).then(render));
      }
    });
    panel.addEventListener("click", (e) => {
      const sug = e.target.closest(".mapsug"), rev = e.target.closest(".maprev");
      if (sug) {
        const hit = ((LAST && LAST.rows) || []).find((r) => r.name === sug.dataset.name);
        if (hit) bindColumn(hit.name, hit.suggest);
      } else if (rev) {
        sendWb(() => window.Bridge.call(SCREEN, "revert_map", { name: rev.dataset.name }));
      }
    });
  }

  function init() {
    wire();
    window.Bridge.onPush(SCREEN, render);
  }

  window.WorkbenchScreen = { init, render, leaveTo };
})();
