/* `job.js` 클러스터 C 의 `job_mirror` 조각 — 책임 분리(복잡도 예산) 전용 사이드카.
 *
 * `runJobMirror` 자체는 `job.js` 에 그대로 산다(계약 파일의 함수 식별자를 보존한다). 이
 * 모듈은 그 몸체가 쪼개진 단계 함수들만 들고, `job.js` 가 가져다 쓴다. 공유 헬퍼
 * (`enterSyntheticJob`·`stubDispatch`·`isShown`·`displayOf`·`deepCopy`·`pushAndSettle`)는
 * 다른 job 프로브도 쓰므로 `job.js` 에 남아 export 되고, 여기로는 **역수입하지 않는다**
 * (production import 그래프의 순환 금지 — `job.js` → `job_mirror.js` → `job.js` 는 닫힌
 * 비순환 그래프 계약을 깬다). 대신 `runJobMirror` 가 한 번 묶은 `lib` 객체로 주입한다. */

/** app.py:1283-1314 그대로 — 필터가 선 세션(가시 1행 + 필터 밖 선택 1행). */
function mirrorSnapshot() {
  return {
    job_name: "공고서", has_job: true,
    out_dir: "C:\\Results", data_label: "d.csv", data_source_label: "d.csv (파일)", data_notice: null,
    template_name: "t.hwpx", template_path: "C:\\t.hwpx", template_missing: false,
    filename_pattern: "doc-{{seq}}", has_data: true, record_count: 2, selected_count: 2,
    records: [{ index: 0, selected: true, name: "doc-001.hwpx", summary: "전산장비" },
      { index: 1, selected: true, name: "doc-002.hwpx", summary: "사무비품" }],
    filter: {
      active: true, reapply_available: true, reapply_hint: "(공고명) 포함 「전산」",
      search: "전산",
      chips: [{ column: "금액", text: "금액 ≥ '1,000,000'" }, { column: "", text: "(공고명) 포함 「전산」" }],
      definition: "필터 '소기업' · 필터 '전산' · 금액 ≥ '1,000,000' · (공고명) 포함 「전산」",
      branches: ["공고명"],
      columns: [
        { name: "공고명", kind: "text", active: false, filtered: true, constraints: ["필터 '전산'"] },
        { name: "금액", kind: "amount", active: true, filtered: true, constraints: ["금액 ≥ '1,000,000'"] },
      ],
      adhoc_active: true,
      presets: [
        {
          name: "소기업", active: true, usable: true, reason: "",
          dimension: "추정가격", dimension_label: "추정가격",
          description: "추정가격 < '100,000,000'",
          state: { search: "", pruned: [], columns: { 추정가격: { text: "", values: null, range: {
            first: { op: "lt", operand: "100,000,000" }, second: null, joiner: "and" } } } },
        },
        {
          name: "중소기업", active: false, usable: false,
          reason: "이 필터의 열이 지금 데이터에 없습니다: 추정가격",
          dimension: "추정가격", dimension_label: "추정가격", description: "",
          state: { search: "", pruned: [], columns: { 추정가격: { text: "", values: null, range: {
            first: { op: "ge", operand: "100,000,000" }, second: null, joiner: "and" } } } },
        },
        {
          name: "전산", active: true, usable: true, reason: "",
          dimension: "공고명", dimension_label: "공고명", description: "공고명 포함 '전산'",
          state: { search: "", pruned: [], columns: { 공고명: { text: "전산", values: null, range: null } } },
        },
      ],
      preset_groups: [
        { key: "추정가격", label: "추정가격", names: ["소기업", "중소기업"] },
        { key: "공고명", label: "공고명", names: ["전산"] },
      ],
      builder: {
        total: 2, can_create: true, reason: "",
        adhoc: { search: "전산", pruned: [], columns: {
          금액: { text: "", values: null, range: {
            first: { op: "ge", operand: "1,000,000" }, second: null, joiner: "and" } },
        } },
        columns: [
          { name: "공고명", kind: "text", label: "텍스트", hidden: false, values: ["전산장비", "사무비품"], more: 0 },
          { name: "금액", kind: "amount", label: "금액", hidden: false, values: [], more: 0 },
        ],
      },
    },
    table: {
      columns: [{ name: "공고명", kind: "text" }, { name: "금액", kind: "amount" }],
      rows: [{
        index: 0, selected: true, name: "doc-001.hwpx", summary: "전산장비",
        cells: [[["전산", true], ["장비", false]], [["1,000,000원", false]]],
      }],
      visible_count: 1,
      hidden_selected: [{ index: 1, selected: true, name: "doc-002.hwpx", summary: "사무비품" }],
    },
    preflight: { level: "ok", text: "ok" },
    blank_fields: ["낙찰율"],
    drift: [], gate: { enabled: true, level: "", text: "생성 준비" },
  };
}

/* `#jobMirror`(legacy HWPX 의 드리프트·파일명 토큰 차단 배너 host)와 그 위에 섰던 캡션·
   요약 한 줄(`#jobMirrorLine`/`#jobMirrorSummary`)은 전부 걷혔다 — 문서 생성이 managed
   하나가 되며(#1081 PR2) 그 사유는 작업대 관찰·배달 계획이 말한다. 여기서 재는 것은
   **부재**다: 선언된 철거는 조용한 무시와 다르고, 되살아나면 이 줄들이 빨강이다. 저장 폴더
   한 줄(`#jobOutDirLine`)도 같은 갈래의 표면이라 함께 잰다. */
export async function runJobMirrorBannersGone(ctx, services, doc, out, lib) {
  lib.enterSyntheticJob(services);
  const snap = mirrorSnapshot();
  await lib.pushAndSettle(ctx, "job", snap);
  out.full_cell_title = doc.getElementById("jobCell-0-0")?.parentElement?.title || "";

  out.mirror_host_gone = !doc.getElementById("jobMirror");
  out.mirror_line_gone = !doc.getElementById("jobMirrorLine")
    && !doc.getElementById("jobMirrorSummary")
    && !doc.querySelector(".mirline, .mir-blank-flag, .mirempty, .mir-drift");
  out.out_dir_line_gone = !doc.getElementById("jobOutDirLine");
  /* 종전 이 자리에 섰던 확인 면 출구(`#jobMirrorPreviewOpen`)와 그 잠금 대조는 #957 에서
     사망했다. 파괴 확인의 계측은 아래 `ow_body` 다. */
  out.mirror_preview_exit_gone = !doc.getElementById("jobMirrorPreviewOpen");
  out.mirror_review_flag_gone = !doc.getElementById("jobReviewFlag");
  /* 재진술 블록(`#jobRestate`)도 존 재편에서 죽었다 — 선택 수치의 세 번째 발화였다. */
  out.restate_gone = !doc.getElementById("jobRestate");
  return snap;
}

function jobMirrorTableMark(doc) {
  const m = doc.querySelector("#jobTableBody mark");
  return m ? m.textContent : "";
}

/** 필터 표면 되읽기(블록 4) — 가시 행·하이라이트·칩·가지 ×·스트립·유래 수치·아이콘. */
export function runJobMirrorFilterSurface(doc, win, out) {
  out.tbl_rows = doc.querySelectorAll("#jobTableBody tr[data-i]").length;
  const renderedRow = doc.querySelector("#jobTableBody tr[data-i]");
  const renderedAmount = doc.querySelector("#jobTableBody td.col-amount");
  out.row_role = renderedRow && renderedRow.getAttribute("role");
  out.row_selected = renderedRow && renderedRow.getAttribute("aria-selected");
  out.row_checkbox = !!doc.querySelector('#jobTableBody td.doccol input[type="checkbox"]');
  out.row_doccell_display = win.getComputedStyle(doc.querySelector("#jobTableBody .doccell")).display;
  /* U4 8번 — 「문서」 열의 이름·요약은 걷혔다. 사라진 것은 **음성으로** 재고(되살아나면 빨강),
     그 자리에 온 선택 동사(U4 11번)는 양성으로 잰다. 옛 `lead_hint`·`repeated_placeholder` 는
     각각 죽은 노드와 vacuous 0 이 되어 이 둘로 승계됐다. */
  out.doccol_row_names = doc.querySelectorAll(
    "#jobTableBody .doc-name, #jobTableBody .doc-sum, #jobTableBody .doc-off",
  ).length;
  out.head_doccol_text = doc.querySelector("#jobTableHead th.doccol").textContent.trim();
  out.head_selall = !!doc.querySelector("#jobTableHead th.doccol input#jobSelAll");
  out.amount_align = win.getComputedStyle(renderedAmount).textAlign;
  out.amount_nums = win.getComputedStyle(renderedAmount).fontVariantNumeric;
  out.tbl_mark = jobMirrorTableMark(doc);
  out.ficos = doc.querySelectorAll("#jobTableHead .fico[data-col]").length;
  out.chips_text = doc.getElementById("jobFilterChips").textContent;
  out.branch_prune = !!doc.querySelector('#jobFilterChips [data-prune="공고명"]');
  const definitionChip = doc.querySelector("#jobFilterChips .fchip.definition");
  const branchChip = doc.querySelector("#jobFilterChips .fchip.branch");
  out.filter_role_labels = Array.from(doc.querySelectorAll(".fchip .chip-role")).map(
    (e) => e.textContent,
  );
  out.definition_bg = win.getComputedStyle(definitionChip).backgroundColor;
  out.branch_bg = win.getComputedStyle(branchChip).backgroundColor;
  out.branch_border_style = win.getComputedStyle(branchChip).borderStyle;
  return renderedRow;
}

/** 저장한 필터 칩(2026-09-30 재설계) — 같은 열 무리(알약 + 표지)·홀로 선 칩·켜짐/꺼짐 배경
 *  대조·경고 사유·조건 title·▾ 메뉴(켜진 칩만)·문맥 메뉴·토글 발신. */
export async function runJobMirrorPresetChips(ctx, services, doc, win, out, lib) {
  out.preset_chips = doc.querySelectorAll("#jobFilterChips .fchip.preset").length;
  out.preset_pressed = Array.from(doc.querySelectorAll(".preset-toggle")).map(
    (e) => e.getAttribute("aria-pressed"),
  );
  const cluster = doc.querySelector("#jobFilterChips .fcluster");
  out.preset_cluster = cluster ? {
    label: cluster.querySelector(".fcluster-label")?.textContent || "",
    chips: Array.from(cluster.querySelectorAll(".preset-toggle")).map((e) => e.textContent),
    border: win.getComputedStyle(cluster).borderTopStyle,
  } : null;
  out.preset_single_outside = !doc.querySelector('.fcluster [data-preset="전산"]')
    && !!doc.querySelector('#jobFilterChips [data-preset="전산"]');
  const onToggle = doc.querySelector('.preset-toggle[data-preset="소기업"]');
  const warnToggle = doc.querySelector('.preset-toggle[data-preset="중소기업"]');
  out.preset_warn_title = warnToggle.title;
  out.preset_warn_aria_disabled = warnToggle.getAttribute("aria-disabled");
  out.preset_on_title = onToggle.title;
  out.preset_on_bg = win.getComputedStyle(onToggle.closest(".fchip.preset")).backgroundColor;
  out.preset_off_bg = win.getComputedStyle(warnToggle.closest(".fchip.preset")).backgroundColor;
  /* ▾ 는 켜진 칩에만 선다 — 꺼진 칩은 이름 단추가 칩 폭 전부다(빈자리 예약 0, 테두리 2px 만). */
  out.preset_menu_buttons = Array.from(doc.querySelectorAll("#jobFilterChips [data-preset-menu]")).map(
    (e) => e.getAttribute("data-preset-menu"),
  );
  out.preset_off_reserve = Math.round(
    warnToggle.closest(".fchip.preset").getBoundingClientRect().width - warnToggle.getBoundingClientRect().width,
  );
  /* 문맥 메뉴 키(Shift+F10)는 꺼진 칩에도 같은 메뉴(고치기·삭제)를 세우고 첫 항목으로 초점을 옮긴다.
     Escape 는 메뉴만 닫고 연 칩으로 초점을 돌린다. */
  warnToggle.focus();
  warnToggle.dispatchEvent(new win.KeyboardEvent("keydown", { key: "F10", shiftKey: true, bubbles: true }));
  await ctx.sleep(50);
  const ctxPop = doc.querySelector('[data-preset-pop="중소기업"]');
  out.preset_ctx_menu = ctxPop ? {
    role: ctxPop.getAttribute("role"),
    items: Array.from(ctxPop.querySelectorAll('[role="menuitem"]')).map((e) => e.textContent),
    focus_first: doc.activeElement === ctxPop.querySelector('[role="menuitem"]'),
    shown: lib.isShown(ctx, ctxPop),
  } : null;
  if (ctxPop) {
    ctxPop.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await ctx.sleep(50);
  }
  out.preset_ctx_closed = !doc.querySelector("[data-preset-pop]") && doc.activeElement === warnToggle;
  warnToggle.blur();
  /* 저장한 필터가 조이는 열의 머리도 표지를 세우고, title 이 무엇이 조이는지 이름으로 말한다. */
  out.head_fico = Array.from(doc.querySelectorAll("#jobTableHead .fico[data-col]")).map(
    (e) => [e.getAttribute("data-col"), e.classList.contains("on"), e.title],
  );
  /* 「모두 보기」 — 필터가 선 동안 표시 수 바로 뒤의 조용한 글 링크. 「필터 지우기」는 없다. */
  const showAll = doc.getElementById("jobShowAll");
  out.show_all = showAll ? {
    text: showAll.textContent,
    after_count: showAll.previousElementSibling === doc.getElementById("jobSelCount"),
    count_text: doc.getElementById("jobSelCount").textContent,
    border: win.getComputedStyle(showAll).borderTopColor === "rgba(0, 0, 0, 0)",
    underline: win.getComputedStyle(showAll).textDecorationLine,
  } : null;
  out.filter_clear_gone = !doc.querySelector('[data-act="filter-clear"]');
  const newBtn = doc.querySelector('#jobFilterChips [data-act="filter-new"]');
  out.filter_new_shown = !!newBtn && lib.isShown(ctx, newBtn);
  out.filter_save_gone = !doc.querySelector('[data-act="filter-save"]');

  const presetSent = [];
  const countSent = [];
  const listSent = [];
  const presetStub = lib.stubDispatch(services, (realCall) => function presetStubHandler(screen, action, payload) {
    if (action === "toggle_filter_preset") {
      presetSent.push(payload.name);
      return Promise.resolve({ ok: true, active: false });
    }
    if (action === "filter_clear") {
      presetSent.push("모두 보기");
      return Promise.resolve({});
    }
    if (action === "count_filter_state") {
      countSent.push(payload.state);
      return Promise.resolve({ ok: true, count: 1, total: 2, summary: "금액 ≥ '1,000,000'" });
    }
    if (action === "list_filter_columns") {
      listSent.push(payload.query);
      return Promise.resolve({ ok: true, columns: [
        { name: "공고명", kind: "text", label: "텍스트", hidden: false, segments: [["공고", true], ["명", false]] },
        { name: "금액", kind: "amount", label: "금액", hidden: false, segments: [["금액", false]] },
      ] });
    }
    return realCall.call(services.Bridge, screen, action, payload);
  });
  onToggle.click();                                   // ※ 가시성 단언 없음(레거시 그대로)
  await ctx.sleep(0);
  if (showAll) showAll.click();
  await ctx.sleep(0);
  out.preset_toggle_sent = String(JSON.stringify(presetSent));
  return { newBtn, countSent, listSent, presetStub };
}

/** 「+ 필터」 열림 — 지금 조건(금액 ≥ · 검색)으로 채워진 카드가 트리거 아래에 서고, 살아 있는
 *  수를 묻는다(배치는 연 직후에 잰다 — 트리거 아래에 붙고, 아래가 모자라면 위로 뒤집힌다). */
export async function runJobMirrorFilterBuilderOpen(ctx, doc, win, out, newBtn, countSent, lib) {
  newBtn.click();
  await ctx.sleep(400);                                // 150ms 지연 + 응답 + 그리기
  const builderRoot = doc.getElementById("jobFilterBuilder");
  out.builder_open = !!builderRoot && lib.isShown(ctx, builderRoot);
  out.builder_title = builderRoot?.querySelector("#jobFilterBuilderTitle")?.textContent || "";
  out.builder_note = builderRoot?.querySelector("[data-fb-from-adhoc]")?.textContent || "";
  out.builder_cards = builderRoot
    ? Array.from(builderRoot.querySelectorAll(".fb-card[data-fb-row] .fb-card-name")).map((e) => e.textContent)
    : [];
  out.builder_and = builderRoot
    ? Array.from(builderRoot.querySelectorAll(".fb-and")).map((e) => e.textContent) : [];
  out.builder_count = builderRoot?.querySelector("[data-fb-count] .fb-status-text")?.textContent || "";
  out.builder_meter = builderRoot?.querySelector(".fb-meter-fill")?.style.transform || "";
  out.builder_name_placeholder = builderRoot?.querySelector("[data-fb-name]")?.placeholder || "";
  out.builder_count_sent = countSent.length > 0
    && JSON.stringify(countSent[countSent.length - 1]?.columns?.금액?.range?.first || null);
  const operandAlignOf = (root) => {
    const input = root?.querySelector(".fb-operand.num");
    return input ? win.getComputedStyle(input).textAlign : "";
  };
  out.builder_operand_align = operandAlignOf(builderRoot);
  const openRect = builderRoot?.getBoundingClientRect();
  const anchor = newBtn.getBoundingClientRect();
  out.builder_anchored = !!openRect
    && (openRect.top >= anchor.bottom - 1 || openRect.bottom <= anchor.top + 1);
  out.builder_geometry = openRect ? {
    viewport: [win.innerWidth, win.innerHeight], trigger: [Math.round(anchor.top), Math.round(anchor.bottom)],
    top: Math.round(openRect.top), bottom: Math.round(openRect.bottom),
    placement: builderRoot.dataset.placement || "",
  } : null;
  out.builder_width = openRect ? Math.round(openRect.width) : 0;
  out.builder_fits_viewport = !!openRect && openRect.top >= 0 && openRect.bottom <= win.innerHeight + 1;
  const picker = doc.getElementById("jobFilterColumnPicker");
  out.builder_focus_picker = doc.activeElement === picker;
  return { builderRoot, picker };
}

/** 맨 아래 열 콤보박스가 Python 거르기로 목록을 세워 ↓/Enter 로 카드를 더하며, Escape 로
 *  닫히고 초점이 트리거로 돌아온다. */
export async function runJobMirrorFilterBuilderPicker(ctx, doc, win, out, newBtn, builderRoot, picker, listSent) {
  out.picker_role = picker?.getAttribute("role") || "";
  if (picker) {
    const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, "value").set;
    setter.call(picker, "공고");
    picker.dispatchEvent(new win.Event("input", { bubbles: true }));
    await ctx.sleep(250);                              // 80ms 지연 + 응답 + 그리기
    out.picker_expanded = picker.getAttribute("aria-expanded");
    out.picker_query_sent = listSent[listSent.length - 1] || "";
    out.picker_options = Array.from(doc.querySelectorAll("#jobFilterColumnList [role=option]")).map(
      (e) => e.querySelector(".fb-option-name")?.textContent || "",
    );
    out.picker_mark = doc.querySelector("#jobFilterColumnList mark")?.textContent || "";
    /* 목록이 펼쳐져 빌더가 자라도 화면 안에 다시 선다(이름·footer 가 밀려 나가지 않는다). */
    await ctx.sleep(80);
    const grownRect = builderRoot.getBoundingClientRect();
    const footRect = builderRoot.querySelector(".fb-foot")?.getBoundingClientRect();
    const trig = newBtn.getBoundingClientRect();
    out.picker_fits_viewport = grownRect.top >= 0 && grownRect.bottom <= win.innerHeight + 1
      && !!footRect && footRect.bottom <= win.innerHeight + 1;
    /* 자라도 트리거에 붙은 채다(아래면 트리거 아래에서 시작, 위면 트리거 위에서 끝) — 가리지 않는다. */
    out.picker_anchored = grownRect.top >= trig.bottom - 1 || grownRect.bottom <= trig.top + 1;
    out.picker_geometry = {
      viewport: [win.innerWidth, win.innerHeight], trigger: [Math.round(trig.top), Math.round(trig.bottom)],
      top: Math.round(grownRect.top), bottom: Math.round(grownRect.bottom),
      placement: builderRoot.dataset.placement || "",
    };
    picker.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    await ctx.sleep(0);
    picker.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await ctx.sleep(80);
    out.picker_added = Array.from(builderRoot.querySelectorAll(".fb-card[data-fb-row] .fb-card-name")).map(
      (e) => e.textContent,
    );
    out.picker_focus_in_new_card = !!doc.activeElement?.closest?.('.fb-card[data-fb-column="공고명"]');
  }
  doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await ctx.sleep(50);
  out.builder_closed_on_escape = !doc.getElementById("jobFilterBuilder");
  out.builder_focus_returned = doc.activeElement === newBtn;
}

/** ▾ → 「고치기」 — 제목·이름 프리필·삭제 단추, 바깥 누름으로 닫힌다. */
export async function runJobMirrorPresetEdit(ctx, doc, win, out, presetStub) {
  const menuBtn = doc.querySelector('[data-preset-menu="소기업"]');
  menuBtn.click();
  await ctx.sleep(50);
  out.preset_menu_expanded = menuBtn.getAttribute("aria-expanded");
  doc.querySelector('[data-preset-pop="소기업"] [data-preset-act="edit"]')?.click();
  await ctx.sleep(50);
  const editRoot = doc.getElementById("jobFilterBuilder");
  out.edit_title = editRoot?.querySelector("#jobFilterBuilderTitle")?.textContent || "";
  out.edit_name = editRoot?.querySelector("[data-fb-name]")?.value || "";
  out.edit_delete = !!editRoot?.querySelector('[data-act="fb-delete"]');
  doc.body.dispatchEvent(new win.MouseEvent("mousedown", { bubbles: true }));
  await ctx.sleep(50);
  out.edit_closed_outside = !doc.getElementById("jobFilterBuilder");
  presetStub.restore();
}

/** 왕복을 일부러 미결로 둔 채 두 번 누른다. 둘째 값이 첫 낙관 표지를 기준으로 계산돼야
 *  true→false→true 가 되고, checkbox·aria-selected·행 tint 가 같은 프레임에 맞는다(#217 R2). */
export async function runJobMirrorZoneToggleAndPanel(ctx, services, doc, win, out, renderedRow, lib) {
  const toggleValues = [];
  const zoneStub = lib.stubDispatch(services, (realCall) => function zoneStubHandler(screen, action, payload) {
    if (action === "toggle_record") {
      /* **해소되는** 스텁이다(리뷰 2R): 존 변이는 한 체인에 직렬화되므로 영원히 미결인 첫
         발신은 둘째를 영영 막는다. 재는 것은 "push 가 오기 전 재클릭이 화면의 현재 상태를
         쓰는가"이지 promise 가 매달리는가가 아니다. 둘째 값은 마이크로태스크 뒤에 실린다. */
      toggleValues.push(payload.value);
      return Promise.resolve({});
    }
    if (action === "filter_panel") return new Promise(function () {});
    return realCall.call(services.Bridge, screen, action, payload);
  });
  renderedRow.click();                              // ※ 가시성 단언 없음(레거시 그대로)
  await ctx.sleep(0);                              // React 낙관 상태 DOM 커밋
  out.row_optimistic_off = !renderedRow.classList.contains("on")
    && renderedRow.getAttribute("aria-selected") === "false"
    && !renderedRow.querySelector("input").checked;
  renderedRow.click();                              // ※ 가시성 단언 없음(레거시 그대로)
  await ctx.sleep(0);                              // 둘째 실시간 의도 DOM 커밋
  out.row_optimistic_on = renderedRow.classList.contains("on")
    && renderedRow.getAttribute("aria-selected") === "true"
    && renderedRow.querySelector("input").checked;
  out.row_toggle_values = toggleValues.slice();     // 즉시분(첫 발신) — 최종 확인은 아래 되읽기
  /* filter_panel 응답이 영원히 미결이어도 클릭 프레임에 제목 + 로딩 껍데기가 먼저 선다(#217 R4). */
  doc.querySelector("#jobTableHead .fico").click(); // ※ 가시성 단언 없음(레거시 그대로)
  await ctx.sleep(0);
  /* R4는 정적 #jobColPanel을 채우지 않고 현재 portal 안에 React 패널을 마운트한다. 같은
     노드 identity/hidden 속성이 아니라 현재 React 소유 표면의 존재와 제거를 잰다. */
  const panelSelector = "#jobTableHost .react-colpanel";
  const loadingPanel = doc.querySelector(panelSelector);
  out.panel_shell_immediate = !!loadingPanel
    && loadingPanel.getAttribute("aria-busy") === "true"
    && loadingPanel.textContent.indexOf("불러오는 중") >= 0
    && loadingPanel.textContent.indexOf("공고명") >= 0;
  const panelClose = loadingPanel && loadingPanel.querySelector('[data-act="panel-close"]');
  if (panelClose) panelClose.click();                 // ※ 가시성 단언 없음(레거시 그대로)
  await ctx.sleep(0);
  zoneStub.restore();
  /* 열 패널 기본 닫힘 — React owner에서는 hidden 토글이 아니라 조건부 언마운트가 계약이다. */
  out.panel_hidden = !doc.querySelector(panelSelector);
  return toggleValues;
}

/** 드리프트·파일명 토큰 스냅샷이 와도 차단 배너는 서지 않는다(host 가 없다) — 그 사유를
 *  말하는 자리는 managed 작업대 관찰·배달 계획이다. 음성 한 번으로 잰다. 이어서 덮어쓰기/가드
 *  본문과 직전 필터 재적용(결정 28) 양 분기를 잰다. */
export async function runJobMirrorBannersAndBodies(ctx, services, doc, win, out, snapIn, lib) {
  let snap = lib.deepCopy(snapIn);
  snap.drift = ["유령", "계약조건"]; snap.name_tokens = ["납품기한"]; snap.blank_fields = [];
  snap.gate = { enabled: false, level: "danger", text: "템플릿 구조가 확정 매핑과 달라졌습니다." };
  await lib.pushAndSettle(ctx, "job", snap);
  out.legacy_banner_gone = !doc.querySelector(".mir-drift")
    && !doc.querySelector('[data-act="fix-mapping"], [data-act="fix-filename"]');
  /* 덮어쓰기 확인 본문 합성 되읽기 — overwrite_count/new_count 스왑·이름 목록 누락의 핀. */
  out.ow_body = services.JobRun.overwriteBody({
    total: 10, overwrite_count: 3, new_count: 7, conflict_names: ["a.hwpx", "b.hwpx"], conflict_more: 5,
  });
  /* 세션 가드 재진술 본문 — 있는 손실만 열거한다(과경고는 경보의 인플레). 두 극을 함께 낸다. */
  out.guard_body = services.JobRun.guardBody(
    { sel_count: 3, in_def: 2, extra: 1, filter_active: true, filter_parts: 2 }, "데이터를 바꾸면",
  );
  out.guard_body_minimal = services.JobRun.guardBody(
    { sel_count: 1, in_def: 0, extra: 0, filter_active: false, filter_parts: 0 }, "데이터를 바꾸면",
  );
  out.data_guard_wired = typeof services.JobRun.confirmDestructiveIfArmed === "function";

  /* 직전 필터 재적용(결정 28) — 양 분기 모두 핀한다: 켜짐만 고정하면 "항상 떠 있는 죽은
     버튼" 회귀가 초록으로 샌다. */
  out.reapply_shown = lib.isShown(ctx, doc.getElementById("jobFilterReapply"));
  out.reapply_title = doc.getElementById("jobFilterReapply").title;
  snap = lib.deepCopy(snap);
  snap.filter.reapply_available = false;
  await lib.pushAndSettle(ctx, "job", snap);
  out.reapply_hidden = lib.displayOf(ctx, doc.getElementById("jobFilterReapply")) === "none";

  snap = lib.deepCopy(snap);
  snap.filter.reapply_available = true;
  snap.drift = []; snap.name_tokens = [];
  snap.gate = { enabled: true, level: "", text: "생성 준비" };
  snap.blank_fields = ["필드0"];
  await lib.pushAndSettle(ctx, "job", snap);
}

/** 화면 전환의 인계 계약 — 편집기는 자기 화면으로 **덮는다**(재작성 F7). 종전 이 자리는
 *  확인 면을 열어 두고 「전환이 펼침 면을 닫는가」를 함께 쟀는데, 그 면이 #957 에서
 *  철거돼 남는 것은 전환 자체다(펼침 면 일괄 회수는 `sheet_gate`·`modal_a11y` 가 진다).
 *
 *  푸시 격리는 그대로 둔다: 프로브 첫머리 `Nav.go('job')` 이 쏜 실 refresh 의 푸시(세션
 *  없는 실 스냅샷)가 호스트 스레드에서 늦게 착지해 뒤 프로브(job_result)의 창을 오염시킨다.
 *  삼킨 것은 기록해 증언한다(조용한 격리 금지). */
export function runJobMirrorScreenTransition(ctx, services, doc, out, toggleValues, lib) {
  const mirrorRealPush = ctx.push;
  const mirrorPushes = [];
  ctx.push = function (screen, pushed) {
    if (screen === "job") {
      mirrorPushes.push({ job: pushed && pushed.job_name, has_job: !!(pushed && pushed.has_job) });
      return undefined;
    }
    return mirrorRealPush(screen, pushed);
  };
  ctx.state.mirrorPushes = mirrorPushes;

  services.Nav.go("editor", { force: true });
  out.edit_takes_over_screen = !doc.getElementById("scr-job").classList.contains("on")
    && doc.getElementById("scr-editor").classList.contains("on");
  lib.enterSyntheticJob(services, { force: true });
  ctx.push = mirrorRealPush;

  /* 지연 회수 — `row_toggle_values` 는 **덮어쓰기**라 필드 자리는 그대로 두고 값만 최종
     의도열로 바뀐다. */
  out.row_toggle_values = toggleValues.slice();
  out.mirror_pushes = mirrorPushes;
}
