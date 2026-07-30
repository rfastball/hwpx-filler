/* 데이터 선택 다이얼로그 — v6 `dataPickerDialog` 통합 표면(재작성 F1, 지도 §10.7).

   한 면에서 세 구획을 고른다: **현재 데이터**(재진술 + 「이 데이터 고정」) · **고정한 데이터**
   (Dataset Pool 참조 목록 + 수명 관리) · **다른 데이터**(파일 찾아보기 — 1회용). 종전의 두
   버튼(`등록 데이터…`·`파일 선택…`)과 `pool` 화면이 하던 일이 전부 여기로 모인다.

   ## 소유 경계 (지도 §10.7.2 판정 A·B)

   - 목록·수명 관리는 **`PoolController` 를 그대로** 소비한다(`refresh`·`archive`·`activate`·
     `delete`·`register_excel` + `pool` 관측 푸시). 백엔드 신설 0 — 죽은 것은 화면뿐이고 이
     모듈이 `pool` 푸시의 새 구독자다.
   - 마운트는 **호스트 화면**(`job`)의 액션이다(`load_pool` / `pick_data_file`) —
     데이터는 세션 소유라 어느 화면의 세션에 물리는지가 의미를 가진다.
   - 「고정한 데이터」는 **보관 항목도 싣는다**: 활성만 실으면 `활성화` 동사에 도달할 길이
     사라진다(§10.7.2 C — 표시 상한과 무관한 도달성). 보관·끊김·나라 항목은 숨기지 않고
     **정직하게 비활성**으로 두고 사유를 병기한다.

   ## 4계약면 (지도 §10.7.1 — 새 오버레이의 생명주기)

   1. **재렌더 정체**: 목록은 열린 채 재렌더된다(보관·삭제가 같은 면에서 일어난다). 행 키는
      풀 항목 이름(`data-name`), 재렌더는 `Preserve.around` 로 감싸 포커스가 면 밖으로
      떨어지지 않게 한다.
   2. **잠금 범위**: 생성 중 잠금은 호스트 `setBusy` 가 이 루트도 훑는다(오버레이 루트는 화면
      루트 질의 밖 — 슬3 2R P2 선례). 마운트 진행 중에는 닫기·Escape·추가 클릭을 막고 **그
      사실을 표기**한다(`pool_picker.js` C8 승계 — '취소했다'면서 데이터가 바뀌는 거짓말 금지).
   3. **전이·왕복 순서**: 실패·취소는 절대 면을 닫지 않는다(허가지 의무가 아니다 — U2
      §2.7 1행). 고정 목록 선택은 남은 결정이 없어 성사 즉시 닫히고, 파일 찾아보기는
      성사해도 「이 데이터 고정」 결정이 남아 면을 유지한다 — 「끝난 선택은 닫히고, 결정이
      남은 선택은 남는다」. 닫힘 뒤 포커스는 여는 트리거로 복귀(modal.js 소유). 고정·확인·
      시트 선택은 이 면 **위에** 스택으로 뜬다.
   4. **실패 경로 문맥**: 나라 동결·죽은 참조·모호 시트·행 0건·읽기 실패는 면을 닫지 않고
      상태줄에 재진술한다 — 다른 항목 재선택도 취소도 여기서 계속 가능하다.

   모달 골격(`#dataPickerModal`·`#poolRegModal`)은 index.html 정적 DOM 이 소유한다 — 동적
   생성은 정적 파싱 가드(test_web_dom_contract 의 role/aria 계약)의 사각을 만든다(구
   `pool_picker.js` K12 의 교훈). 이 파일은 거동만 소유하고 배선은 1회(`wired`)다.

   가드 순서(§10.7.2 D): 전환 손실 확인은 **대상이 정해진 직후·읽기 직전**에 호스트 콜백
   (`confirmSwap`)으로 묻는다. 파기는 오직 성공한 읽기 뒤에만 일어난다(§18.2 원자 계약은
   `load_data_path` 가 이미 만족). */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = window.escHtml;  // 공유 이스케이퍼(esc.js)

  let LAST = null;      // 마지막 pool 스냅샷 — 열려 있지 않아도 푸시를 받아 둔다.
  let session = null;   // 열린 회차 {screen, current, confirmSwap, onLoaded, resolve}
  let loading = false;  // 마운트 진행 중 — 닫기·Escape·추가 클릭 차단(C8)
  let wired = false;

  const errText = (err) => String((err && err.message) || err);

  /* ---- 상태줄(실패 경로 문맥 보존 — 면을 닫지 않고 여기서 말한다) ---- */
  function setStatus(text, level) {
    const el = $("dataPickerNote");
    if (!el) return;
    el.textContent = text || "";
    el.className = "note " + (level === "danger" ? "dangerbox" : level === "ok" ? "okbox" : "");
    el.style.display = text ? "" : "none";
  }

  function noteLoadingBlock() {
    setStatus("⚠ 불러오는 중입니다. 끝날 때까지 닫을 수 없습니다.", "danger");
  }

  /* ---- 렌더 ---- */
  function renderCurrent() {
    const host = $("dataPickerCurrent");
    const cur = (session && session.current) || null;
    if (!cur || !cur.label) {
      host.innerHTML = `<p class="muted capnote">아직 데이터가 없습니다. 아래에서 고르세요.</p>`;
      return;
    }
    const sheet = cur.sheet ? ` <span class="muted">시트: ${esc(cur.sheet)}</span>` : "";
    // 「이 데이터 고정」은 **파일 출처에서만** 뜬다 — 등록 데이터 출처는 이미 고정된 참조다
    // (v6 pinCurrentData hidden 동형). 없는 대상에 버튼을 띄우면 문안이 거짓이 된다.
    // (§2.7 6행의 「고정됨」 회차 기억은 §5.3 재편으로 되깎았다 — 중복 판정이 경로 기준이
    //  돼 같은 파일 재고정은 2건이 아니라 기존 등록의 갱신·「이미 고정됨」 재진술로 접힌다.)
    const pin = cur.origin === "file" && cur.path
      ? `<button class="btn sm" id="dataPickerPin" data-busy-lock>이 데이터 고정…</button>`
      : "";
    host.innerHTML =
      `<div class="tplcard"><div class="tplcard-top">` +
      `<span class="tplcard-name">${esc(cur.label)}</span>${sheet}` +
      `<span class="pill ok">사용 중</span></div>` +
      (cur.detail ? `<div class="tplcard-meta muted">${esc(cur.detail)}</div>` : "") +
      (pin ? `<div class="tplcard-acts">${pin}</div>` : "") +
      `</div>`;
  }

  /* 고정 목록 — 풀 스냅샷 행 그대로(전 상태·배지·참조 요약·메모·로케이트). 사용 가능 여부는
     상태에서 파생하고, 불가하면 **버튼을 지우지 않고** 비활성 + 사유를 병기한다. */
  function usableReason(r) {
    if (r.status !== "active") return "보관 항목입니다 — [활성화] 뒤에 쓸 수 있습니다";
    if (r.missing) return "참조가 끊겼습니다 — [다시 연결] 뒤에 쓸 수 있습니다";
    return "";
  }

  function renderPinned() {
    const host = $("dataPickerPinned");
    const rows = (LAST && LAST.rows) || [];
    if (!LAST) {
      host.innerHTML = `<p class="muted capnote">고정한 데이터를 읽는 중…</p>`;
      return;
    }
    if (!rows.length) {
      host.innerHTML =
        `<p class="muted capnote">고정한 데이터가 없습니다. 자주 쓰는 파일은 ` +
        `「이 데이터 고정」으로 여기 남겨 두면 다음부터 한 번에 고를 수 있습니다.</p>`;
      return;
    }
    // 행동의 겨눔은 **슬롯 키**다(§5.3 — 이름은 중복 허용 라벨이라 동명 2건을 못 가른다).
    // 이름은 상태줄 문구용으로만 함께 싣는다.
    host.innerHTML = rows.map((r) => {
      const reason = usableReason(r);
      const idattrs = `data-key="${esc(r.key)}" data-name="${esc(r.name)}"`;
      const use = `<button class="btn sm primary" data-act="use" ${idattrs}` +
        `${reason ? ` disabled title="${esc(reason)}"` : ""} data-busy-lock>이 데이터 사용</button>`;
      let acts = (r.actions || []).map((a) =>
        `<button class="btn sm" data-act="${esc(a.key)}" ${idattrs} data-busy-lock>` +
        `${esc(a.label)}</button>`).join("");
      // 다시 연결(#67) — 엑셀 참조만. 확정은 pool `relink` 액션의 confirm 왕복이 담당한다.
      if (r.kind === "excel") {
        acts += `<button class="btn sm" data-act="relink" ${idattrs}` +
          ` data-busy-lock>다시 연결…</button>`;
      }
      const broken = r.missing ? `<span class="pill danger">참조 끊김</span>` : "";
      const note = r.note ? `<span class="pk-note">${esc(r.note)}</span>` : "";
      const why = reason ? `<span class="pk-note">${esc(reason)}</span>` : "";
      const track = r.locate_path ? PathTrack.affordances(r.locate_path) : "";
      // 행은 **정보 열 + 행동 열** 2열이다(세로 밀도 — 마일스톤 L). 참조·메모·사유·로케이트를
      // 각자 한 줄씩 쌓으면 3항목만으로 다이얼로그가 넘친다.
      return `<div class="tplcard pk-row" data-row="${esc(r.key)}">
        <div class="pk-info">
          <div class="tplcard-top"><span class="tplcard-name" title="${esc(r.reference)}">${esc(r.name)}</span>
            <span class="pill muted">${esc(r.kind_label)}</span>
            <span class="pill ${esc(r.badge_level)}">${esc(r.badge_label)}</span>${broken}</div>
          <div class="tplcard-meta muted pk-ref"><span>${esc(r.reference)}</span>${track}</div>
          ${note || why ? `<div class="tplcard-meta muted">${note}${why}</div>` : ""}
        </div>
        <div class="tplcard-acts">${use}${acts}</div></div>`;
    }).join("");
  }

  /* 같은 데이터(경로+시트)를 가리키는 등록 2+건 — 구판(이름=키) 마이그레이션의 병합 대상
     (§5.3). 조용히 하나 버리지 않는다: loud 재진술하고 남길 1건을 사용자가 확정한다. */
  function renderDuplicates() {
    const box = $("dataPickerDupes");
    const groups = (LAST && LAST.duplicates) || [];
    if (!groups.length) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    box.innerHTML = groups.map((g) =>
      `<div class="note warnbox">⚠ 같은 데이터(${esc(g.reference)})를 가리키는 등록이 ` +
      `${g.entries.length}건입니다. 남길 등록을 골라 정리하세요:<br>` +
      g.entries.map((e) =>
        `<button class="btn sm" data-dup-keep="${esc(e.key)}" data-busy-lock>` +
        `'${esc(e.name)}' 남기기</button>`).join(" ") +
      `</div>`).join("");
  }

  /* 손상 격리(RC-05) — 숨기지 않고 목록 아래 상주 위험 카드로. 상태줄과 따로 두어야
     로드 오류 문구에 덮이지 않는다(pool_picker C5 승계). */
  function renderCorrupt() {
    const box = $("dataPickerCorrupt");
    const rows = (LAST && LAST.corrupted) || [];
    if (!rows.length) { box.style.display = "none"; box.innerHTML = ""; return; }
    box.style.display = "";
    box.innerHTML = rows.map((c) =>
      `<div class="note dangerbox">⚠ 손상된 등록 데이터: ${esc(c.file)} — ${esc(c.error)}</div>`
    ).join("");
  }

  function renderAll() {
    renderCurrent();
    renderPinned();
    renderDuplicates();
    renderCorrupt();
  }

  /** Python→웹 pool 푸시(보관·활성화·삭제·등록 결과) — 열려 있으면 그 자리에서 다시 그린다. */
  function render(s) {
    LAST = s;
    if (!isOpen()) { return; }        // 닫혀 있으면 값만 보관(다음 열기에 반영)
    // 재렌더 정체(계약면 1) — 방금 누른 버튼이 사라지므로 포커스를 복원한다.
    Preserve.around(renderAll);
    // 등록·전이·삭제 결과 문구는 컨트롤러가 성과별 심각도로 낸다 — 그대로 재진술(신설 금지).
    const res = s.result || {};
    if (res.text) setStatus(res.text, res.level === "muted" ? "" : res.level);
  }

  // 열림 판정은 **회차 상태**로 한다(DOM 클래스 조회 아님) — 회차는 open 에서 세워지고
  // 닫힘(onClose)에서 비워지므로 모달 전이 애니메이션과 무관하게 정확하다.
  function isOpen() { return session !== null; }

  /* ---- 마운트(성사 시에만 닫는다 — 계약면 3) ---- */
  function finish(label) {
    const s = session;
    session = null;
    loading = false;
    document.removeEventListener("keydown", onEscCapture, true);
    Modal.close("dataPickerModal");
    if (s) {
      if (label && s.onLoaded) s.onLoaded(label);
      s.resolve(label || null);
    }
  }

  async function mountPinned(key, name) {
    if (loading) return;
    if (!(await session.confirmSwap())) return;   // 손실 가드 — 읽기 직전(§10.7.2 D)
    loading = true;
    setStatus(`${name} 읽는 중…`, "");
    try {
      const r = await Bridge.call(session.screen, "load_pool", { key });
      if (r && r.ok) { finish(r.label || name); return; }
      // 나라 동결·죽은 참조·모호 시트·행 0건 — 면을 닫지 않고 재진술(계약면 4).
      setStatus("⚠ " + ((r && r.error) || "등록 데이터를 불러올 수 없습니다."), "danger");
    } catch (err) {
      setStatus("⚠ 등록 데이터를 불러올 수 없습니다:\n" + errText(err), "danger");
    } finally {
      loading = false;
    }
  }

  /* 찾아보기 = 성사해도 **면을 닫지 않는다**(U2 §2.7 1행). 안내문("고른 뒤 「이 데이터
     고정」으로 남길 수 있습니다")이 약속한 그 기능이 서려면, 마운트 직후 「현재 데이터」가
     방금 고른 파일로 재진술되고 그 자리에 고정 버튼이 서야 한다. 반면 고정 목록 선택
     (mountPinned)은 남은 결정이 없어 지금처럼 닫는다 — 「끝난 선택은 닫히고, 결정이 남은
     선택은 남는다」. 성사 판정은 브리지 descriptor(label·path·sheet·rows — §2.7 3행)로
     한다: 다음 푸시 도착을 기다리면 발신 순서에 기대는 것이다. */
  async function browseFile() {
    if (loading) return;
    if (!(await session.confirmSwap())) return;   // 손실 가드 — 피커 열기 직전
    loading = true;
    setStatus("파일 선택 창에서 파일을 고르세요…", "");
    try {
      let r = await Bridge.pickDataFile(session.screen);
      if (r && typeof r === "object" && r.needs_sheet) {  // 다중 시트 확정 게이트(#33)
        r = await SheetPicker.choose(session.screen, r);
        if (r === null) { setStatus("시트 선택을 취소했습니다 — 데이터는 그대로입니다.", ""); return; }
      }
      if (r === null) { setStatus("", ""); return; }      // 취소 = 중단(면 유지)
      if (typeof r === "string" && r.startsWith("ERROR:")) {
        setStatus("⚠ 파일을 읽을 수 없습니다: " + r.slice(6).trim(), "danger");
        return;
      }
      // 성사 — 회차의 「현재 데이터」를 descriptor 로 재진술하고 면을 유지한다.
      session.current = {
        label: r.label, detail: `${r.rows}건`,
        path: r.path, sheet: r.sheet || "", origin: "file",
      };
      session.mounted = r.label;  // 이후 닫힘의 해소값 — 닫아도 마운트는 성사됐다
      renderCurrent();
      if (session.onLoaded) session.onLoaded(r.label);
      setStatus(
        `${r.label} — ${r.rows}건을 불러왔습니다. 이대로 쓰려면 [닫기], ` +
        "자주 쓰는 파일이면 「이 데이터 고정…」으로 남겨 두세요.", "ok");
    } catch (err) {
      setStatus("⚠ 파일을 읽을 수 없습니다:\n" + errText(err), "danger");
    } finally {
      loading = false;
    }
  }

  /* ---- 고정 목록 수명 관리(pool 액션 그대로 — 판정 A). 겨눔은 슬롯 키(§5.3). ---- */
  async function onPinnedClick(e) {
    const btn = e.target.closest("button[data-act]");
    if (!btn || btn.disabled) return;
    const act = btn.dataset.act;
    const key = btn.dataset.key;
    const name = btn.dataset.name;
    if (act === "use") { await mountPinned(key, name); return; }
    if (act === "relink") {
      const row = ((LAST && LAST.rows) || []).find((r) => r.key === key);
      // 다시 연결 = 같은 슬롯의 참조 교체(수명 보존) — pool `relink` confirm 왕복으로 확정.
      if (row) openRegDialog({
        title: "데이터 다시 연결", okLabel: "다시 연결", relinkKey: key,
        name: row.name, path: row.locate_path, sheet: row.sheet, note: row.note,
        focus: "path",
      });
      return;
    }
    if (loading) { noteLoadingBlock(); return; }
    try {
      if (act === "delete") {
        // 파괴 확정 — 1차=재진술(needs_confirm), 확인 시에만 2차 삭제(조용한 소실 금지).
        const res = await Bridge.call("pool", "delete", { key });
        if (res && res.needs_confirm && (await Modal.confirm({
          body: res.confirm_text + "\n\n삭제할까요?",
          confirmLabel: "삭제", cancelLabel: "취소", danger: true,
        }))) {
          await Bridge.call("pool", "delete", { key, confirm: true });
        }
        return;
      }
      await Bridge.call("pool", act, { key });   // archive/activate — 비파괴 즉시
    } catch (err) {
      setStatus("⚠ " + errText(err), "danger");
    }
  }

  /* 중복 등록 병합(§5.3 마이그레이션) — 남길 1건 클릭 → 재진술 확인 → 확정 삭제. */
  async function onDupesClick(e) {
    const btn = e.target.closest("button[data-dup-keep]");
    if (!btn) return;
    if (loading) { noteLoadingBlock(); return; }
    const keep = btn.dataset.dupKeep;
    try {
      const res = await Bridge.call("pool", "resolve_duplicate", { keep });
      if (res && res.needs_confirm && (await Modal.confirm({
        body: res.confirm_text + "\n\n정리할까요?",
        confirmLabel: "정리", cancelLabel: "취소", danger: true,
      }))) {
        await Bridge.call("pool", "resolve_duplicate", { keep, confirm: true });
      }
    } catch (err) {
      setStatus("⚠ " + errText(err), "danger");
    }
  }

  /* ---- 고정 다이얼로그(= v6 pinDataDialog) — 등록 모달을 이 면 위에 스택으로 띄운다 ----
     「＋ 직접 등록」은 죽었다(U2 §2.7 4행) — 유일한 고유 기능(마운트하지 않고 등록)이
     가능한 이유가 곧 결함(경로만 반환하고 읽지 않음)이었다. 남은 진입은 둘뿐이다:
     pin(방금 읽은 현재 데이터 고정 — path·sheet 읽기전용, 찾아보기 감춤: §2.7 5행)과
     relink(고정 목록의 끊긴 참조를 새 경로로 — path 편집·찾아보기 유지, 의무 상속분). */
  function openRegDialog(opts) {
    const p = opts || {};
    // 제목과 확정 버튼은 **같은 동사**를 쓴다 — 「이 데이터 고정」을 열고 「등록」을 누르게
    // 하면 같은 행동을 두 이름으로 부르는 셈이다(COPY_STYLE_GUIDE 동사 일치).
    $("poolRegTitle").textContent = p.title || "데이터 등록";
    $("poolRegOk").textContent = p.okLabel || "등록";
    $("poolRegName").value = p.name || "";
    $("poolRegPath").value = p.path || "";
    $("poolRegSheet").value = p.sheet || "";
    $("poolRegNote").value = p.note || "";
    // pin 모드 = 「이 데이터」가 방금 확인한 그 데이터라는 말이 참이 되게 참조를 잠근다.
    $("poolRegPath").readOnly = !!p.pin;
    $("poolRegSheet").readOnly = !!p.pin;
    $("poolRegBrowse").style.display = p.pin ? "none" : "";
    // relink 대상 슬롯(§5.3) — 확정이 register(신규/갱신)가 아니라 relink(같은 슬롯의
    // 참조 교체)로 가야 하는 회차. pin/직접 등록은 "".
    if (session) session.regTarget = p.relinkKey || "";
    window.Modal.open("poolRegModal", {
      initialFocus: p.focus === "path" ? $("poolRegPath") : $("poolRegName"),
    });
  }

  /** 「이 데이터 고정」 — 지금 물린 파일·시트를 프리필하고 이름만 받는다(v6 pinData). */
  function openPinDialog() {
    const cur = (session && session.current) || {};
    openRegDialog({
      title: "이 데이터 고정", okLabel: "고정", pin: true,
      name: "", path: cur.path || "", sheet: cur.sheet || "", note: "",
      focus: "name",
    });
  }

  async function submitRegDialog() {
    // relink 회차는 같은 슬롯의 참조 교체(pool `relink`), 아니면 등록(pool `register_excel`
    // — 같은 데이터면 백엔드가 라벨 갱신·「이미 고정됨」으로 접는다, §5.3 정체성 판정).
    const relinkKey = (session && session.regTarget) || "";
    const action = relinkKey ? "relink" : "register_excel";
    const payload = {
      name: $("poolRegName").value,
      path: $("poolRegPath").value,
      sheet: $("poolRegSheet").value,
      note: $("poolRegNote").value,
    };
    if (relinkKey) payload.key = relinkKey;
    // 브리지 rejection 이 unhandled 로 삼켜지면 버튼이 무반응이 된다 — loud 재진술하고
    // 모달은 열어 둔다(입력 보존, 고쳐 재시도 가능).
    try {
      let res = await Bridge.call("pool", action, payload);
      if (res && res.needs_confirm) {
        // 참조 교체·같은 데이터 라벨 갱신 — 조용히 덮지 않고 확인 승격.
        if (!(await Modal.confirm({
          body: res.confirm_text + "\n\n계속할까요?",
          confirmLabel: "덮어쓰기", cancelLabel: "취소", danger: true,
        }))) return;
        res = await Bridge.call("pool", action, { ...payload, confirm: true });
      }
      if (res && res.ok === false) { window.alert(res.error); return; }
      window.Modal.close("poolRegModal");
    } catch (err) {
      window.alert(errText(err));
    }
  }

  /* ---- 개폐 ---- */
  // 마운트 중 Escape 차단(계약면 2) — Modal 의 캡처 keydown 보다 **먼저** 등록해(같은 대상의
  // 캡처 리스너는 등록 순) 선행 수신하고, 로드 중이면 닫힘 전파를 끊고 그 사실을 표기한다.
  function onEscCapture(e) {
    if (e.key === "Escape" && loading) {
      e.preventDefault();
      e.stopImmediatePropagation();
      noteLoadingBlock();
    }
  }

  /** 데이터 선택 면을 열고 마운트 결과를 해소한다(라벨=성사 · null=마운트 없이 닫힘).
   *  찾아보기 성사는 면을 닫지 않으므로(U2 §2.7 1행) 해소는 닫힘 시점이다 — 그 회차에
   *  마운트가 성사됐으면 닫힘도 그 라벨로 해소된다(닫기 = 중단이 아니라 「이대로 쓰기」).
   *  opts: {screen, current:{label,detail,path,sheet,origin}, confirmSwap, onLoaded, trigger} */
  function open(opts) {
    build();
    const o = opts || {};
    return new Promise((resolve) => {
      session = {
        screen: o.screen,
        current: o.current || {},
        confirmSwap: o.confirmSwap || (() => Promise.resolve(true)),
        onLoaded: o.onLoaded || null,
        mounted: "",    // 이 회차에 성사된 마운트 라벨(찾아보기 — 면 유지 경로)
        regTarget: "",  // 열린 등록 모달의 relink 대상 슬롯 키(""=pin/등록 — §5.3)
        resolve,
      };
      loading = false;
      setStatus("", "");
      renderAll();
      document.addEventListener("keydown", onEscCapture, true);  // Modal.open 보다 먼저
      Modal.open("dataPickerModal", {
        onClose: () => {                 // 마운트 없는 닫힘 = 중단(조용한 강등 없음)
          const s = session;
          session = null;
          document.removeEventListener("keydown", onEscCapture, true);
          if (s) s.resolve(s.mounted || null);
        },
        initialFocus: $("dataPickerClose"),
      });
      // 외부 변경(다른 표면·CLI 등록) 재스캔 — 푸시가 목록을 채운다. 실패는 상태줄로.
      // **이것이 유일한 재스캔 지점이다**(U2 §2.3 에서 수동 「새로고침」 제거). 손상 격리
      // 판정(`corrupted`)도 이 호출로만 다시 계산되므로, 열 때마다 부르는 이 자리가 조용히
      // 사라지면 면이 낡은 손상 목록을 보이게 된다.
      Bridge.call("pool", "refresh", {}).catch((err) => {
        setStatus("⚠ 고정한 데이터를 읽을 수 없습니다: " + errText(err), "danger");
      });
    });
  }

  function build() {
    if (wired) return;
    wired = true;
    $("dataPickerClose").addEventListener("click", () => {
      if (loading) { noteLoadingBlock(); return; }
      Modal.close("dataPickerModal");
    });
    $("dataPickerBrowse").addEventListener("click", browseFile);
    // (「＋ 직접 등록…」 배선은 U2 §2.7 4행에서 버튼과 함께 죽었다 — 등록은 「이 데이터
    //  고정」(pin)과 「다시 연결」(relink) 두 진입만 남는다. 대체 경로 신설 없음.)
    // 재렌더에도 살아남게 안정 컨테이너에 위임(행은 푸시마다 다시 그려진다).
    $("dataPickerPinned").addEventListener("click", onPinnedClick);
    $("dataPickerDupes").addEventListener("click", onDupesClick);
    $("dataPickerCurrent").addEventListener("click", (e) => {
      if (e.target.closest("#dataPickerPin")) openPinDialog();
    });
    // 고정 다이얼로그(스택 상위) — 이 모듈이 유일 소유자다(pool 화면 사망분 승계).
    $("poolRegCancel").addEventListener("click", () => window.Modal.close("poolRegModal"));
    $("poolRegOk").addEventListener("click", submitRegDialog);
    $("poolRegBrowse").addEventListener("click", async () => {
      const p = await Bridge.pickPoolDataFile();   // 경로만 — 로드 없음
      if (p) $("poolRegPath").value = p;
    });
  }

  /* 부팅 — 라우터(app.js)가 pywebviewready 후 호출. 여기서는 푸시 구독과 배선만 하고
     목록은 **열 때** 당긴다(부팅 예산: 안 여는 세션에서 풀 I/O 를 지불하지 않는다). */
  function init() {
    Bridge.onPush("pool", render);
    build();
  }

  window.DataPicker = { init, open };
})();
