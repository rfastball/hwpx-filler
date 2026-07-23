/* 작업 정의(HWPX) 렌더러 — 브리지로 링1 EditorController 와 왕복. 3분류(템플릿·매핑·저장).
   에디터 흡수(R-flow 블록 2 개정, 결정 39~41): 표면은 「작업」 패널의 편집 모드(#jobEditHost)에
   산다 — 신규 초안은 마법사 **단계**(전진 게이트·푸터 내비), 저장된 작업 편집은 **탭**(자유
   이동, editing_origin 으로 가른다). 구 2단계 '데이터 선택'은 매핑 단계의 관문으로 인라인
   (3단계 접기) — 템플릿(0) → 매핑(1, 데이터 관문 내장) → 저장(2).
   렌더는 Python 이 window.__push('editor', snapshot) 로 밀어 넣는다.
   표현 계층(단계/탭 UI·매핑표·행 색·표시형 라벨)만 여기서 만든다 — VM 로직 아님. */
(function () {
  const SCREEN = "editor";
  const $ = (id) => document.getElementById(id);
  // 표시형/타입 라벨은 표현 계층 → 여기(뷰)에 둔다(Qt mapping_table 의 웹 짝).
  const TYPE_LABEL = { text: "텍스트", date: "날짜", amount: "금액", const: "고정값" };
  const INFERRED_LABEL = { text: "텍스트", date: "날짜", amount: "금액", number: "숫자", phone: "전화번호" };
  const STEP_TITLES = ["템플릿 선택", "필드 매핑", "작업 저장"];
  let LAST = null;

  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  // 편집(탭) vs 신규(마법사 단계) — 정보 완전 동등, 공개 방식만 상이(결정 41).
  const isEditing = (s) => !!s.editing_origin;

  // <details> 의 유효 펼침 — 재렌더 관통 보존(PR-3 리뷰 F8: preserve.js 는 details open 을
  // 스냅샷하지 않아 수동으로 연 접힘이 매 push 에 도로 닫혔다). 접힘별 전용 변수(혼합 금지).
  let foldOpen = false;     // 미사용 헤더 접힘(.ign-fold)
  let tokFoldOpen = false;  // 파일명 토큰 참조 접힘(.tok-fold, F27 — PR-4 리뷰 F6)

  /* ---- Python→웹 푸시 렌더 ---- */
  function render(s) {
    Preserve.around(() => {  // 마법사 폼 포커스·캐럿·본문 스크롤 보존(#28)
      // 재구성 전 현 펼침을 읽어 이월(수동 개폐 존중) — 접힘별 전용 클래스로 분리 판독.
      const fold = document.querySelector("#jobEditHost details.ign-fold");
      if (fold) foldOpen = fold.open;
      const tokFold = document.querySelector("#jobEditHost details.tok-fold");
      if (tokFold) tokFoldOpen = tokFold.open;
      LAST = s;
      $("editor-steps").innerHTML = stepHeader(s);
      $("editor-body").innerHTML = stepBody(s);
      $("editor-foot").innerHTML = footer(s);
      // 편집(탭)에선 저장 탭에만 푸터가 있다 — 빈 푸터의 고아 경계선 방지.
      $("editor-foot").style.display = (isEditing(s) && s.step < 2) ? "none" : "";
    });
  }

  /* 헤더: 신규=단계 표지(번호·게이트), 편집=탭(자유 이동 버튼). 같은 .wstep-tab 룩 재사용. */
  function stepHeader(s) {
    if (isEditing(s)) {
      return STEP_TITLES.map((t, i) => {
        const cur = i === s.step ? ' aria-current="true"' : "";
        return `<button class="wstep-tab as-tab" data-act="goto-tab" data-step="${i}"${cur}>${esc(t)}</button>`;
      }).join("");
    }
    return STEP_TITLES.map((t, i) => {
      const cur = i === s.step ? ' aria-current="true"' : "";
      const done = i < s.step ? " done" : "";
      return `<div class="wstep-tab${done}"${cur}><span class="k">${i + 1}</span>${esc(t)}</div>`;
    }).join("");
  }

  /* 본문 표제 — 신규는 단계 서수를 말하고, 편집(탭)은 분류 이름만 말한다. */
  function stageTitle(s, i) {
    return isEditing(s) ? STEP_TITLES[i] : `${i + 1}단계: ${STEP_TITLES[i]}`;
  }

  function stepBody(s) {
    // 세션 통지(#26) — 문제(warn)만 시끄럽게, 정상(ok)은 muted 한 줄(F32).
    const notice = s.notice
      ? `<p class="note ${s.notice.level === "ok" ? "quiet" : "warnbox"}" style="white-space:pre-line">${esc(s.notice.text)}</p>`
      : "";
    if (s.step === 0) return notice + templateStage(s);
    if (s.step === 1) return notice + mappingStage(s);
    return notice + saveStage(s);  // 2 = 저장
  }

  /* ---- 분류 0: 템플릿 — 신규 1단계 = **라이브러리에서 그룹 구획으로 고르기**(#108 슬라이스 3).
     관리 화면 HWPX 구획과 **같은 그룹 모델·같은 접힘**(선택 전용). 매체는 hwpx 하나뿐(마법사=
     .hwpx 산출 → 매체 자동 필터). 바깥 파일은 「가져오기…」=라이브러리로 복사 후 그 사본으로
     시작(앱 소유 루트 — 원본 수정 불파급). ---- */
  function libRow(t) {
    // 상태 사유(detail)는 배지 title 로 — 오류 행은 선택 버튼 대신 사유를 보여준다(리뷰 F8:
    // 죽은 버튼이 생 예외 alert 로 끝나는 반쪽 노출 금지 — 원인 있는 사용 불가).
    const badge = t.badge_label
      ? `<span class="tbadge" title="${esc(t.detail || "")}">${esc(t.badge_label)}</span>` : "";
    const pick = t.is_error
      ? `<span class="muted capnote" title="${esc(t.detail || "")}">사용 불가</span>`
      : (t.current
        ? `<span class="muted capnote">선택됨</span>`
        : `<button class="btn sm" data-act="use-library" data-path="${esc(t.path)}">이 템플릿으로</button>`);
    // .fname 이 남는 폭을 먹고 말줄임(F14) — 배지·동작은 고정폭이라 스페이서 불필요.
    return `<div class="libselrow${t.current ? " cur" : ""}"><span class="fname">${esc(t.name)}</span>` +
      `${badge}${pick}</div>`;
  }

  function libGroupHead(sec, idx) {
    const label = sec.group || "그룹 없음";
    // 안정 id(#138 리뷰 F13) — 재렌더 뒤 Preserve 가 같은 헤더로 키보드 포커스를 복원한다
    // (구획 순서는 접힘 토글에 불변이라 인덱스가 안정 식별자다).
    return `<div class="job-grp"><button class="job-grp-head" id="libgrp-${idx}" data-act="toggle-lib-group"` +
      ` data-group="${esc(sec.group)}" aria-expanded="${sec.collapsed ? "false" : "true"}">` +
      `<span class="grp-name">${esc(label)}</span><span class="grp-count">${sec.count}</span>` +
      `<span class="grp-caret">${sec.collapsed ? "▸" : "▾"}</span></button></div>`;
  }

  function libraryPicker(s) {
    const lib = s.library || { sections: [], flat: true };
    const sections = lib.sections || [];
    const total = sections.reduce((n, sec) => n + (sec.items ? sec.items.length : 0), 0);
    let body;
    if (!total) {
      body = `<div class="muted" style="padding:var(--sp-8)">라이브러리에 템플릿이 없습니다.` +
        ` '가져오기…'로 추가하거나 템플릿 관리에서 확인하세요.</div>`;
    } else if (lib.flat) {
      // 퇴화 불변식(그룹 0개) — 헤더 없는 평면 나열.
      body = `<div class="tpl-grp-rows flat">` +
        sections.map((sec) => sec.items.map(libRow).join("")).join("") + `</div>`;
    } else {
      body = sections.map((sec, i) =>
        libGroupHead(sec, i) +
        (sec.collapsed ? "" : `<div class="tpl-grp-rows">${sec.items.map(libRow).join("")}</div>`)
      ).join("");
    }
    return `<div class="grp">
      <div class="row" style="margin-bottom:var(--sp-4)"><span class="cap">템플릿 라이브러리</span>
        <span class="spacer"></span>
        <button class="btn sm" data-act="import-template">가져오기…</button></div>
      <p class="note quiet" style="margin-top:0">HWPX 서식만 표시됩니다.</p>
      ${body}
    </div>`;
  }

  function templateStage(s) {
    let out = `<div class="wtitle">${esc(stageTitle(s, 0))}</div>
      <p class="wsub">라이브러리에서 누름틀 템플릿을 고르거나 '가져오기…'로 추가하세요.</p>
      ${libraryPicker(s)}`;
    if (s.template_name) {
      out += `<div class="row"><span class="lbl">선택한 템플릿</span>
        <span class="filechip"><b>${esc(s.template_name)}</b></span>
        ${PathTrack.affordances(s.template_path)}</div>`;
    }
    if (s.raw_block) {
      out += `<p class="note dangerbox" style="white-space:pre-line">${esc(s.raw_block)}</p>`;
    } else if (s.gate_error) {
      out += `<p class="note dangerbox">템플릿 상태를 확인할 수 없습니다. 진행할 수 없습니다.</p>`;
    } else if (s.field_count) {
      out += schemaTable(s);
      if (s.gate) {
        out += `<div class="note warnbox" style="white-space:pre-line">${esc(s.gate.message)}</div>`;
        if (!s.gate.acked) {
          out += `<button class="btn" data-act="ack-gate">비우고 진행 확인 (${s.gate.unmet.length}개 토큰)</button>`;
        }
      }
    }
    return out;
  }

  // 1단계 필드표: 나열식 요약을 구조화(#16 98DDFE96). 필드·추정타입·위치·문맥.
  function schemaTable(s) {
    const rows = (s.fields || []).map((f) => {
      const type = INFERRED_LABEL[f.inferred_type] || f.inferred_type || "";
      const where = f.in_table ? "표 안" : "본문";  // in_table → 위치 라벨(색 아닌 텍스트)
      const ctx = f.context || "";
      const ctxCell = ctx
        ? `<span title="${esc(ctx)}">${esc(ctx)}</span>`
        : `<span class="pv emptyval">—</span>`;
      return `<tr>
        <td><span class="fname">${esc(f.name)}</span></td>
        <td><span class="tbadge">${esc(type)}</span></td>
        <td class="muted">${esc(where)}</td>
        <td class="fctx">${ctxCell}</td></tr>`;
    }).join("");
    return `<p class="fields-head">${esc(s.schema_summary)}</p>
      <div class="tblwrap"><table class="schema-fields"><thead><tr>
        <th>필드</th><th>추정 타입</th><th>위치</th><th>문맥</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
  }

  // 데이터 미리보기: 컬럼 헤더 + 샘플 행 그리드(#16). F21 열 압축(블록 2 결정 14): 미리보기
  // 열 = 활성 헤더만(미사용 열은 뷰에서 제외, 재활성 시 복귀). 매핑표 행은 반대로 안 숨긴다
  // (mapRow 의무 잔존, 조용한 빈칸 금지) — 여긴 데이터 감(感)을 주는 미리보기라 압축이 맞다.
  function dataPreview(s) {
    if (!s.record_count) return "";
    const all = s.source_fields || [];
    const active = new Set(s.active_source_fields || all);
    // sample_rows 는 전체 source_fields 순서로 투영된 배열 — 원 인덱스를 물고 활성 열만 남긴다.
    const cols = all.map((name, i) => ({ name, i })).filter((c) => active.has(c.name));
    const head = cols.map((c) => `<th title="${esc(c.name)}">${esc(c.name)}</th>`).join("");
    const sample = s.sample_rows || [];
    const body = sample.map((row) =>
      `<tr>${cols.map((c) => {
        const v = row[c.i];
        return (v === "" || v == null)
          ? `<td><span class="pv emptyval">(빈 값)</span></td>`  // ADR-B: 빈 셀 시끄럽게
          : `<td><span class="pv">${esc(v)}</span></td>`;
      }).join("")}</tr>`).join("");
    const hiddenCols = all.length - cols.length;
    const colNote = hiddenCols
      ? ` · 열 ${cols.length}/${all.length} (미사용 ${hiddenCols}열 제외)`
      : ` · 전체 ${all.length}열`;
    const more = s.record_count > sample.length
      ? `<p class="fields-head muted">샘플 ${sample.length}행 표시(외 ${s.record_count - sample.length}행)</p>`
      : "";
    return `<p class="fields-head">${s.record_count}행 불러옴${colNote}.</p>
      <div class="tblwrap"><table class="data-preview"><thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody></table></div>${more}`;
  }

  /* 데이터 관문(F18·F20) — 매핑 단계의 머리(3단계 접기). 파일 선택/바꾸기 + '데이터 없이
     진행' 옵트아웃. 선택과 결과가 같은 지면: 파일을 고르면 매핑표가 그 자리에서 차오른다
     (Python 이 load_data_path 에서 모델 재구성 → 다음 push). 작업엔 데이터가 저장되지 않는다. */
  function dataGateway(s) {
    const has = !!s.data_path;
    const picker = has
      ? `<span class="filechip"><b>${esc(s.data_name)}</b>${s.data_sheet ? ` <span class="sheet">시트: ${esc(s.data_sheet)}</span>` : ""}</span>
         <button class="btn" data-act="pick-data">바꾸기…</button>`
      : `<button class="btn primary" data-act="pick-data">파일 선택…</button>`;
    return `<div class="row gateway">
      <span class="lbl">이 작업의 데이터</span>
      ${picker}
      <button class="btn linklike" data-act="skip-data">데이터 없이 진행</button>
      ${has ? PathTrack.affordances(s.data_path) : ""}</div>`;
  }

  /* 사용할 헤더 = 칩-라이브(결정 12·13). 체크박스 스테이징 소거 — 칩 클릭이 곧 즉시 토글.
     활성 칩(클릭=미사용) + 미사용 접힘 구역(칩 클릭=다시 사용) + 전체 사용/전체 미사용 대칭쌍.
     활성 변화는 백엔드 apply_active_sources 가 처리: 미접촉 행은 라이브 재제안, 사람 소유
     행은 소스가 꺼지면 R4 시끄러운 강등(notice). '전체 미사용' 후 미사용 구역 자동 펼침. */
  function headerSelect(s) {
    // 헤더 선택은 데이터가 로드됐을 때만(관문 겨눔 후) 성립한다 — 편집 모드처럼 데이터 없이
    // source_fields 가 저장 매핑 어휘에서 채워진 경우엔 '사용할 헤더'가 없다(복원 행을 헤더
    // 토글로 언매핑하는 유령 표면 방지, 리뷰 F4). mockup 상태 1(파일 겨눔 후)=칩벽 등장.
    const all = s.source_fields || [];  // 전체 헤더(스냅샷 계약 키) — 활성/미사용은 파생
    if (!all.length || !s.record_count) return "";
    const active = new Set(s.active_source_fields || []);
    const ignored = s.ignored_source_fields || [];
    const activeChips = all.filter((f) => active.has(f)).map((f) =>
      `<button class="hchip on" data-act="toggle-header" data-field="${esc(f)}" title="클릭 = 미사용으로">${esc(f)}</button>`
    ).join("") || '<span class="muted">사용 중인 데이터 열이 없습니다. 아래 미사용 목록에서 골라 켜세요.</span>';
    // 미사용 = 벽 이탈 + 접힘 구역(결정 13). '전체 미사용'이 ignored_expanded 로 자동 펼침.
    const ignoredBlock = ignored.length
      ? `<details class="hidden-hdrs ign-fold"${(s.ignored_expanded || foldOpen) ? " open" : ""}><summary>미사용 ${ignored.length}개 (펼쳐 다시 사용)</summary>
           <div class="hchips">${ignored.map((f) =>
              `<button class="hchip ign" data-act="toggle-header" data-field="${esc(f)}" title="클릭 = 다시 사용">${esc(f)}</button>`).join("")}</div>
           <p class="hint" style="margin-top:var(--sp-4)">미사용 데이터 열은 자동 매핑 제안·소스 후보에서 빠집니다.</p>
         </details>`
      : "";
    return `<div class="grp">
      <div class="row" style="margin-bottom:var(--sp-4)"><span class="cap">사용할 데이터 열</span>
        <span class="muted" style="margin-left:var(--sp-8)">${all.length}개 중 ${s.active_count}개 사용</span>
        <span class="spacer"></span>
        ${s.ignored_count ? `<button class="btn sm" data-act="use-all-headers">전체 사용</button>` : ""}
        <button class="btn sm" data-act="use-none">전체 미사용</button>
      </div>
      <div class="hchips">${activeChips}</div>
      ${ignoredBlock}
    </div>`;
  }

  /* ---- 분류 1: 필드 매핑 (데이터 관문 내장, 3단계 접기) ---- */
  function mappingStage(s) {
    const rows = (s.rows || []).map((r) => mapRow(r, s)).join("");
    const stepper = s.preview_count
      ? `<button class="btn sm" data-act="prev-rec">◀ 이전 행</button>
         <span class="mono">행 ${s.preview_index}/${s.preview_count}</span>
         <button class="btn sm" data-act="next-rec">다음 행 ▶</button>`
      : `<span class="muted">행 0/0 · 데이터 없음(템플릿 필드만)</span>`;
    const counts = s.counts
      ? `<span class="muted">채움 ${s.counts.filled} · 빈 값 ${s.counts.empty} · 미매핑 ${s.counts.unmapped}` +
        `${s.preview_empties && s.preview_empties.length ? " (" + esc(s.preview_empties.join(", ")) + ")" : ""}</span>`
      : "";
    const banner = s.schema_only
      ? `<p class="note warnbox">데이터 없이 매핑 중입니다. 고정값을 넣거나 비움으로 확정하세요.</p>`
      : "";
    return `<div class="wtitle">${esc(stageTitle(s, 1))}</div>
      <p class="wsub">필드마다 데이터 열을 지정하고 전 행을 확정하세요.</p>
      ${dataGateway(s)}
      ${headerSelect(s)}
      ${banner}
      <div class="tblwrap"><table class="map"><thead><tr>
        <th>확정</th><th>템플릿 필드 · 추정</th><th>데이터 열</th>
        <th>타입 / 고정값</th><th>표시형</th><th>미리보기</th><th>상태</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <div class="stepper">${stepper}<span class="spacer"></span>${counts}</div>
      <div class="gate">
        <span class="gatecount ${s.is_complete ? "ok" : "pend"}">확정 ${(s.rows || []).filter((r) => r.confirmed).length}/${(s.rows || []).length}</span>
        <span class="spacer"></span>
        <button class="btn" data-act="confirm-all">모두 확정</button>
        <button class="btn" data-act="unconfirm-all">모두 해제</button>
        ${s.unconfirm_undo_count ? `<button class="btn" data-act="restore-confirmed">직전 확정 ${s.unconfirm_undo_count}개 복원</button>` : ""}
      </div>
      ${dataPreview(s)}`;
  }

  // 소유권 태그(칩-라이브 결정 12) — 확정/수동(touched)/제안(시스템)/후보 없음.
  function ownerTag(r, s) {
    if (r.confirmed) return `<span class="tag conf">확정</span>`;
    if (r.touched) return `<span class="tag man">수동</span>`;
    if (r.source) return `<span class="tag sugg">제안</span>`;  // 시스템 소유(활성 따라 유동)
    // 미접촉·소스 없음: 데이터 있으면 '후보 없음', 스키마온리면 중립(오경보 방지).
    return s.record_count ? `<span class="tag none">후보 없음</span>` : `<span class="tag none">—</span>`;
  }

  function mapRow(r, s) {
    // 후보는 활성 헤더만(#49) — 미사용 헤더는 소스 드롭다운에서 빠진다.
    const candidates = s.active_source_fields || s.source_fields || [];
    const known = candidates.includes(r.source);
    const srcOpts = [`<option value=""${r.source ? "" : " selected"}>(비움)</option>`]
      .concat(candidates.map((f) =>
        `<option value="${esc(f)}"${f === r.source ? " selected" : ""} title="${esc(f)}">${esc(f)}</option>`))
      // 복원·데이터 교체로 현재 소스 목록에 없는 소스를 참조하는 행 — (비움)으로
      // 오표시하지 않고 명시 옵션으로 시끄럽게 드러낸다(#26 조용한 소실 금지).
      .concat(r.source && !known
        ? [`<option value="${esc(r.source)}" selected title="현재 데이터에 없는 소스">${esc(r.source)} (데이터에 없음)</option>`]
        : [])
      .join("");
    // 수동(touched·미확정) 행만 전용 '↩' 버튼으로 자동 제안 복귀(리뷰 R5: 센티넬 옵션은 동명
    // 실열과 충돌 — 별도 액션 revert-source). 확정 행은 제외(PR-3 리뷰 F2: 확정도 touched 라
    // 무가드면 오클릭 한 번에 확정이 풀리고 다른 열로 치환 — 확정 해제가 의식적 1단계).
    // 데이터 있을 때만(재제안할 활성 소스가 있어야).
    const revertBtn = r.touched && !r.confirmed && s.record_count
      ? ` <button class="btn sm" data-act="revert-source" data-index="${r.index}" title="자동 제안으로 되돌리기">↩</button>`
      : "";
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
    else if (r.preview_empty) preview = `<span class="pv emptyval">(이 행에서 빈 값)</span>`;
    else preview = `<span class="pv">${esc(r.preview)}</span>`;
    return `<tr class="r-${r.row_state}">
      <td><input type="checkbox" class="cbx" data-act="row-confirm" data-index="${r.index}"${r.confirmed ? " checked" : ""}></td>
      <td><span class="fname" title="${esc(r.context || r.template_field)}">${esc(r.template_field)}</span>
        <span class="tbadge">[추정: ${esc(inferred)}]</span></td>
      <td><select class="sel" data-act="row-source" data-index="${r.index}">${srcOpts}</select>${revertBtn}</td>
      <td><select class="sel" data-act="row-type" data-index="${r.index}">${typeOpts}</select> ${constInput}</td>
      <td><select class="sel" data-act="row-fmt" data-index="${r.index}"${fmtList.length ? "" : " disabled"}>${fmtOpts}</select></td>
      <td>${preview}</td>
      <td>${ownerTag(r, s)}</td></tr>`;
  }

  /* ---- 분류 2: 저장 ---- */
  function saveStage(s) {
    return `<div class="wtitle">${esc(stageTitle(s, 2))}${s.editing_origin ? ` <span class="pill">편집: ${esc(s.editing_origin)}</span>` : ""}</div>
      <p class="wsub">이 작업(템플릿·매핑·파일명)을 저장합니다. 데이터는 실행할 때 고릅니다.</p>
      <div class="row"><span class="lbl lbl-fixed">작업 이름</span>
        <input class="field" data-act="name" value="${esc(s.name)}" placeholder="예: 공고서 자동생성"></div>
      <div class="row"><span class="lbl lbl-fixed">파일명 패턴</span>
        <input class="field mono" data-act="pattern" value="${esc(s.pattern)}"></div>
      ${s.pattern_preview ? `<p class="hint mono" style="margin-top:0">예: ${esc(s.pattern_preview)}${s.record_count ? " (표본 1행 기준)" : ""}</p>` : ""}
      ${provenanceBlock(s)}
      ${datasetBlock(s)}
      ${defaultDatasetBlock(s)}
      ${filenameTokenHelp(s)}
      <div id="save-msg" class="note" style="display:none"></div>`;
  }

  /* 작성 출처 provenance(#53-C) — 이 매핑이 어느 템플릿·데이터 스키마에서 작성됐는지
     되짚는 설명 메타(실행 게이트 아님). 편집 모드에서 복원된 경우만 표시. */
  function provenanceBlock(s) {
    const p = s.provenance;
    if (!p) return "";
    const when = p.updated_at
      ? (p.authored_at && p.authored_at !== p.updated_at
          ? `작성 ${esc(p.authored_at)} · 갱신 ${esc(p.updated_at)}`
          : `작성 ${esc(p.updated_at)}`)
      : "";
    const line = (label, val) =>
      val ? `<div class="hint" style="margin-top:0"><b>${label}</b> ${esc(val)}</div>` : "";
    const drift = (p.template_fields && s.fields && s.fields.length
        && p.template_fields !== s.fields.map((f) => f.name).join(" · "))
      ? `<div class="hint danger" style="margin-top:var(--sp-4)">⚠ 작성 당시와 템플릿 필드 구성이 다릅니다. 매핑 재검토가 필요할 수 있습니다.</div>`
      : "";
    return `<div class="grp">
      <span class="cap">작성 출처</span>
      ${line("템플릿", p.template)}
      ${line("데이터", p.dataset)}
      ${line("템플릿 필드", p.template_fields)}
      ${line("데이터 열", p.source_keys)}
      ${when ? `<div class="hint muted" style="margin-top:0">${when}</div>` : ""}
      ${drift}
    </div>`;
  }

  /* 선언 데이터 자동등록(#26/#18 31A5A484-C) — 검토용으로 고른 데이터를 등록 데이터로
     자동등록한다. 참조(경로·시트)만 저장 — 행·내용은 저장하지 않는다. */
  function datasetBlock(s) {
    if (!s.data_path) return "";
    return `<div class="grp">
      <span class="cap">데이터 함께 등록</span>
      <p class="hint" style="margin-top:0">저장하면 데이터(${esc(s.data_name)})를 등록 데이터에
        올리고 <b>이 작업의 기본 데이터로 연결</b>합니다. 파일 위치만 기억하고, 실행할 때
        원본을 읽습니다.</p>
      <div class="row"><span class="lbl lbl-fixed">등록 이름</span>
        <input class="field" data-act="dataset-name" value="${esc(s.dataset_name)}"></div>
    </div>`;
  }

  /* 기본 데이터 연결 상태(#67) — 편집 모드에서 복원한 참조의 현재 상태 재진술 + 로케이트.
     이 세션이 데이터를 새로 골랐으면 서버가 null 을 줘 자동등록 블록이 서사를 맡는다. */
  function defaultDatasetBlock(s) {
    const d = s.default_dataset;
    if (!d) return "";
    let line;
    if (d.status === "linked") {
      line = `<p class="hint" style="margin-top:0">기본 데이터: <b>${esc(d.name)}</b> (연결됨)
        ${PathTrack.affordances(d.path)}</p>`;
    } else if (d.status === "dead") {
      line = `<p class="hint danger" style="margin-top:0">⚠ 기본 데이터: <b>${esc(d.name)}</b>.
        참조 파일이 없습니다(${esc(d.path)}). 데이터 관리에서 [다시 연결…]하세요.</p>`;
    } else if (d.status === "corrupt") {  // 항목 JSON 손상 — 삭제와 다른 조치(데이터 관리 격리 표시와 정합)
      line = `<p class="hint danger" style="margin-top:0">⚠ 기본 데이터: <b>${esc(d.name)}</b>.
        등록 데이터를 읽을 수 없습니다(손상). 데이터 관리에서 확인하세요.</p>`;
    } else {  // missing — 풀 항목 자체가 사라짐
      line = `<p class="hint danger" style="margin-top:0">⚠ 기본 데이터: <b>${esc(d.name)}</b>.
        등록 데이터에 없습니다(삭제됨). 데이터 관리에서 등록하거나 데이터를 다시 선택하세요.</p>`;
    }
    return `<div class="grp">
      <span class="cap">기본 데이터 연결</span>${line}
    </div>`;
  }

  /* 파일명 패턴 토큰 도우미(#17) — Qt SaveJobPage._refresh_filename_help 웹 포트.
     s.rows 는 스텝2 매핑 확정 시점에 이미 계산돼 스냅샷에 실려온다 — 신규 브리지 호출 없음. */
  /* 토큰 참조 = 접힘(F27, 결정 14) — 라이브 예시(F26)가 상시 답을 주므로 참조표는 부피만
     차지한다. 펼침은 사용자 선택(기본 접힘). */
  function filenameTokenHelp(s) {
    const rows = (s.rows || []).filter((r) => r.has_content);
    const fieldsHtml = rows.length
      ? rows.map((r) => `<code>{{${esc(r.template_field)}}}</code> → ${fnPreviewText(r, s)}`).join(" &nbsp;·&nbsp; ")
      : `<span class="muted">매핑을 완료하면 파일명에 쓸 수 있는 필드가 여기 표시됩니다.</span>`;
    return `<details class="hidden-hdrs tok-fold"${tokFoldOpen ? " open" : ""}><summary>파일명에 넣을 수 있는 값 (펼쳐 보기)</summary>
      <p class="hint" style="margin-top:var(--sp-4)">${fieldsHtml}</p>
      <p class="hint">
        날짜: <code>{{date}}</code> → 생성 날짜(YYYYMMDD) · <code>{{date:YYYY-MM-DD}}</code> → 하이픈 포함 날짜<br>
        순번: <code>{{seq}}</code> → 1부터 증가 · <code>{{seq:001}}</code> → 001부터 세 자리로 증가
      </p>
    </details>`;
  }

  function fnPreviewText(r, s) {
    if (r.preview_error) return `<span class="pv emptyval">(미리보기 오류)</span>`;
    if (r.preview_empty) return `<span class="pv emptyval">${s.record_count ? "(빈 값)" : "(샘플 데이터 없음)"}</span>`;
    let display = String(r.preview).replace(/[\r\n]+/g, " ");
    if (display.length > 40) display = display.slice(0, 39) + "…";
    return `<span class="pv">${esc(display)}</span>`;
  }

  /* ---- 푸터 내비 — 신규=마법사(취소/뒤로/다음/저장), 편집=탭이라 내비 없음(저장 탭에 저장만).
     복귀 어포던스 불설치(결정 40): "저장하고 실행으로" 류 포커스 튕김 버튼은 두지 않는다 —
     실행 복귀는 좌 목록 행 클릭이 담당하고, 저장은 제자리에서 완결된다. ---- */
  function footer(s) {
    if (isEditing(s)) {
      return s.step === 2
        ? `<span class="spacer"></span><button class="btn primary" data-act="save">저장</button>`
        : "";
    }
    const back = s.step > 0
      ? `<button class="btn" data-act="back">◀ 뒤로</button>` : `<button class="btn" disabled>◀ 뒤로</button>`;
    let next;
    if (s.step < 2) {
      const can = s.reachable[s.step];
      next = `<button class="btn primary" data-act="next"${can ? "" : " disabled"}>다음 ▶</button>`;
    } else {
      next = `<button class="btn primary" data-act="save">작업 저장</button>`;
    }
    const hint = (s.step < 2 && !s.reachable[s.step])
      ? `<span class="muted capnote">${gateHint(s)}</span>` : "";
    return `<button class="btn" data-act="cancel-new">취소</button>${back}` +
      `<span class="spacer"></span>${hint}${next}`;
  }

  function gateHint(s) {
    if (s.step === 0) return "템플릿을 선택하고 미해결 토큰을 확인해야 진행할 수 있습니다";
    if (s.step === 1) return "전 행을 확정해야 진행할 수 있습니다";
    return "";
  }

  /* 확정·수동 매핑 보호(PR#105 리뷰 F1) — 관문의 데이터 교체/비우기는 _ensure_model 재초안으로
     사람 소유 행을 미확정으로 되돌린다(값은 carry_profile 로 이월). 편집 복원 확정을 '검토만'
     하려던 1클릭이 매핑 표 바로 위 관문에서 조용히 리셋하지 않게 파괴 전 확인한다(confirm-or-
     alarm). 수치는 **Python 이 지금** 판정한다(PR-2 리뷰 F7 — LAST 는 push 지연 창에서 stale 이라
     방금 확정한 행이 안 보여 확인이 조용히 생략됐다). 0이면 조용히 진행(새 작업 첫 겨눔 등). */
  /* 새 템플릿 진입 = 새 작업 세션 확인 — 폐기 판정은 EditorEntry.confirmDiscard 단일 출처
     (PR-4 리뷰 F9). 편집(탭) 맥락에선 미저장이 없어도(클린 복원) 확인한다(리뷰 F1: 「이
     템플릿으로」가 열려 있는 작업의 편집 맥락을 조용히 닫고 새 초안으로 갈아타면 안 된다 —
     저장본은 남지만 '이 작업을 고치는 중'이라는 맥락의 전환은 의식적이어야 한다). */
  async function confirmNewSessionIfUnsaved() {
    const editing = LAST && LAST.editing_origin;
    if (editing) {
      const busy = await Bridge.editorHasUnsavedWork();
      if (!busy) return true;
      return Modal.confirm({ body:
        `'${editing}' 편집을 닫고 새 작업 초안을 시작합니다.` +
        "\n저장하지 않은 변경은 사라집니다." +
        "\n\n계속할까요?", confirmLabel: "새 작업 시작", cancelLabel: "취소" });
    }
    return EditorEntry.confirmDiscard(
      "새 템플릿으로 시작하면 저장하지 않은 작업 세션이 사라집니다.\n" +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?");
  }

  async function confirmMappingResetIfConfirmed(verbPhrase) {
    const st = await Bridge.call(SCREEN, "mapping_reset_stakes", {});
    const n = (st && st.human) || 0;
    if (!n) return true;
    return Modal.confirm({ body:
      `${verbPhrase} 확정했거나 직접 편집한 매핑 ${n}개가 전부 미확정으로 돌아갑니다` +
      `(값은 이월).\n\n계속할까요?`, confirmLabel: "미확정으로 되돌리기", cancelLabel: "취소" });
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
        case "use-library": {
          if (!(await confirmNewSessionIfUnsaved())) break;
          await Bridge.call(SCREEN, "use_library_template", { path: el.dataset.path });
          break;
        }
        case "toggle-lib-group":
          // 1단계 피커 그룹 접힘 — 관리 화면과 같은 모델 토글(뷰 상태, 세션 불변).
          await Bridge.call(SCREEN, "toggle_library_group", { group: el.dataset.group });
          break;
        case "import-template": {
          if (!(await confirmNewSessionIfUnsaved())) break;
          const r = await Bridge.importTemplateFile(SCREEN);
          if (typeof r === "string" && r.startsWith("ERROR:")) alertMsg(r.slice(6).trim());
          break;
        }
        case "ack-gate": await Bridge.call(SCREEN, "ack_gate", {}); break;
        case "pick-data": {
          if (!(await confirmMappingResetIfConfirmed("데이터를 바꾸면"))) break;  // 확정 보호(F1)
          let r = await Bridge.pickDataFile(SCREEN);
          if (r && typeof r === "object" && r.needs_sheet) {   // 다중 시트 → 확정 게이트(#33)
            r = await SheetPicker.choose(SCREEN, r);
            if (r === null) break;                              // 취소 = 중단(첫 시트 강등 없음)
          }
          if (typeof r === "string" && r.startsWith("ERROR:")) alertMsg(r.slice(6).trim());
          break;
        }
        case "skip-data": {
          if (!(await confirmMappingResetIfConfirmed("데이터 없이 진행하면"))) break;  // 확정 보호(F1)
          await Bridge.call(SCREEN, "skip_data", {});
          break;
        }
        case "goto-tab":  // 편집(탭) 자유 이동(결정 41) — 게이트는 백엔드가 editing 기준으로 판정.
          await Bridge.call(SCREEN, "goto_step", { step: Number(el.dataset.step) });
          break;
        // 칩-라이브(결정 13): 칩 클릭 = 즉시 토글(활성↔미사용). 전체 사용/전체 미사용 대칭쌍.
        case "toggle-header":
          await Bridge.call(SCREEN, "toggle_source_active", { field: el.dataset.field }); break;
        case "use-all-headers": await Bridge.call(SCREEN, "use_all_headers", {}); break;
        case "use-none": {
          // 수치는 Python 이 지금 판정(stale LAST 우회 차단 — F7 동형). 확정 존재는 확인
          // 모달 **전에** 선차단(PR-3 리뷰 F5: 파괴를 승인시킨 뒤 오류로 거부하는 확인-후-
          // 오류 순서 금지) — 백엔드 loud 차단은 백스톱으로 존속. 소스 겨눈 수동 미확정만
          // 실제 강등 집합이라 그 수치로 확인한다(리뷰 F4 — 문안=파괴 집합).
          const st = await Bridge.call(SCREEN, "mapping_reset_stakes", {});
          if (st && st.confirmed) {
            window.alert(`확정한 매핑 ${st.confirmed}개가 있어 전체 미사용을 할 수 없습니다. 확정을 먼저 해제하거나 칩을 하나씩 끄세요.`);
            break;
          }
          const man = (st && st.manual_unconfirmed) || 0;
          if (man && !(await Modal.confirm({ body:
            `전체 미사용하면 직접 소스를 고른 매핑 ${man}개의 수동 지정이 해제됩니다` +
            `(자동 제안으로만 복원).\n\n계속할까요?`,
            confirmLabel: "전체 미사용", cancelLabel: "취소" }))) break;
          await Bridge.call(SCREEN, "use_none", {});
          break;
        }
        case "revert-source":
          await Bridge.call(SCREEN, "revert_source", { index: idx }); break;
        case "prev-rec": await Bridge.call(SCREEN, "step_preview", { delta: -1 }); break;
        case "next-rec": await Bridge.call(SCREEN, "step_preview", { delta: 1 }); break;
        case "unconfirm-all": await Bridge.call(SCREEN, "unconfirm_all", {}); break;
        case "restore-confirmed": await Bridge.call(SCREEN, "restore_confirmed", {}); break;
        case "confirm-all": await confirmAll(); break;
        case "row-confirm": await Bridge.call(SCREEN, "set_confirmed", { index: idx, confirmed: el.checked }); break;
        case "cancel-new": {
          if (!(await EditorEntry.confirmDiscard(
            "새 작업 만들기를 취소하면 입력한 이름 · 데이터 · 매핑이 사라집니다.\n\n계속할까요?",
            el))) break;
          await Bridge.call(SCREEN, "discard_session", {});
          if (window.JobScreen && window.JobScreen.showRunMode) window.JobScreen.showRunMode();
          else window.alert("실행 모드로 돌아갈 수 없습니다. 화면 구성 요소(JobScreen)가 로드되지 않았습니다.");
          break;
        }
        case "back": await Bridge.call(SCREEN, "goto_step", { step: LAST.step - 1 }); break;
        case "next": await Bridge.call(SCREEN, "goto_step", { step: LAST.step + 1 }); break;
        case "save": await doSave({}); break;
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

  /* 모두 확정 — 내용 행 즉시 확정 + 비움 승격 이름게이트(ADR-E 반사적 dismiss 봉쇄). */
  async function confirmAll() {
    const res = await Bridge.call(SCREEN, "confirm_all", {});
    const blanks = (res && res.blanks) || [];
    if (!blanks.length) return;
    const ok = await Modal.confirm({ body:
      `아래 ${blanks.length}개 필드는 채우지 않고 '비움'으로 확정합니다:\n\n${blanks.join(", ")}\n\n계속할까요?`,
      confirmLabel: "비움으로 확정", cancelLabel: "취소",
    });
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
      window.alert("저장 처리 중 오류가 발생했습니다. 작업이 저장됐는지 홈에서 확인하세요.\n" + err);
      return;
    }
    if (!res || typeof res !== "object") {
      alertMsg("저장 결과를 확인할 수 없습니다. 작업이 저장됐는지 홈에서 확인하세요.");
      return;
    }
    if (res.ok) {
      // 저장은 제자리(결정 40 — 포커스 튕김 없음). 좌 목록만 갱신해 새/개명 작업이 바로 보이게
      // 한다(에디터 흡수로 목록과 같은 화면에 산다 — REFRESH_ON_NAV 를 기다릴 이유가 없다).
      if (window.JobScreen && window.JobScreen.refreshList) window.JobScreen.refreshList();
      // 성공 재진술은 Python notice(ok) 채널 — 저장 착지가 저장본 편집 세션 재로드 push 라
      // #save-msg 는 그 재렌더에 증발한다(PR-2 리뷰 F2: push/반환 경합에 안 걸리는 채널만).
      // 반저장(작업 저장 성공 + 데이터 등록 실패)만 여기서 loud — 성공으로 뭉개지 않는다.
      if (res.dataset_register_error) {
        window.alert(`작업 '${res.saved_name}' 은 저장됐지만 데이터 등록이 실패했습니다.\n`
          + res.dataset_register_error);
      }
      return;
    }
    if (res.needs_overwrite) {
      // 본 문안을 그대로 되돌려 준다(#149) — 모달을 읽는 사이 디스크가 바뀌면 확인은 다른
      // 상태에 대한 것이 된다. 판정은 Python 이 쓰기 잠금 안에서 다시 하고(문안 대조),
      // 달라졌으면 새 문안으로 다시 묻는다. 여기는 무엇을 보여 줬는지만 실어 보낸다.
      if (await Modal.confirm({
        body: res.overwrite_text + "\n\n계속할까요?",
        confirmLabel: "덮어쓰기", cancelLabel: "취소", danger: true,
      })) {
        doSave(Object.assign({}, flags, {
          confirm_overwrite: true,
          confirmed_overwrite_text: res.overwrite_text,
        }));
      }
      return;
    }
    if (res.needs_dataset_confirm) {
      if (await Modal.confirm({
        body: res.dataset_text, confirmLabel: "덮어쓰기", cancelLabel: "취소", danger: true,
      })) {
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
    // 에디터 흡수(결정 39) — 표면 거처는 「작업」 패널의 편집 호스트. 위임 루트도 함께 이사.
    const root = $("jobEditHost");
    root.addEventListener("click", onClick);
    root.addEventListener("change", onChange);
    Bridge.initial(SCREEN).then(render);
  }

  /* 현 에디터 스냅샷 재당김·재렌더(#138 리뷰 F12) — 편집 모드로 복귀할 때 1단계 피커가
     관리 화면에서 바뀐 공유 그룹 접힘을 반영하게 한다(returning-to-job 이 job 만 refresh 해
     피커가 stale 접힘으로 남던 문제). 순수 재렌더라 세션 상태 불변(Preserve 가 포커스 보존). */
  function rerender() {
    if (window.pywebview && window.Bridge) Bridge.initial(SCREEN).then(render);
  }

  window.EditorScreen = { init, rerender };
})();
