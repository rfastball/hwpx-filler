(function () {
  const DEMO_ROWS = [
    { id: 1, name: "김나르미", department: "정책기획팀", position: "주무관", date: "2026-08-01" },
    { id: 2, name: "박문서", department: "복지행정팀", position: "팀장", date: "2026-08-01" },
    { id: 3, name: "이도움", department: "민원여권팀", position: "주무관", date: "2026-08-04" },
    { id: 4, name: "최가람", department: "문화관광팀", position: "주무관", date: "2026-08-04" },
  ];

  const state = {
    selected: new Set(),
    recipeSelected: false,
    running: false,
  };

  const startView = document.getElementById("startView");
  const workspaceView = document.getElementById("workspaceView");
  const receiptView = document.getElementById("receiptView");
  const dataTableBody = document.getElementById("dataTableBody");
  const selectionCount = document.getElementById("selectionCount");
  const recipeChoice = document.getElementById("recipeChoice");
  const previewEmpty = document.getElementById("previewEmpty");
  const fieldPreview = document.getElementById("fieldPreview");
  const readyCount = document.getElementById("readyCount");
  const actionSummary = document.getElementById("actionSummary");
  const actionDetail = document.getElementById("actionDetail");
  const runButton = document.getElementById("runButton");

  function show(view) {
    [startView, workspaceView, receiptView].forEach((item) => {
      item.hidden = item !== view;
    });
    window.scrollTo({ top: 0, behavior: "auto" });
  }

  function selectedRows() {
    return DEMO_ROWS.filter((row) => state.selected.has(row.id));
  }

  function resetRun() {
    state.selected.clear();
    state.recipeSelected = false;
    state.running = false;
    recipeChoice.setAttribute("aria-pressed", "false");
    runButton.textContent = "문서 만들기";
    renderRows();
    update();
  }

  function renderRows() {
    dataTableBody.replaceChildren();
    DEMO_ROWS.forEach((row) => {
      const tr = document.createElement("tr");
      const checked = state.selected.has(row.id);
      tr.classList.toggle("is-selected", checked);

      const checkCell = document.createElement("td");
      checkCell.className = "check-column";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = checked;
      checkbox.setAttribute("aria-label", `${row.name} 선택`);
      checkbox.addEventListener("change", () => setSelected(row.id, checkbox.checked));
      checkCell.appendChild(checkbox);

      [checkCell, row.name, row.department, row.position, row.date].forEach((value) => {
        if (value instanceof HTMLElement) {
          tr.appendChild(value);
          return;
        }
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });

      tr.addEventListener("click", (event) => {
        if (event.target instanceof HTMLInputElement) return;
        setSelected(row.id, !state.selected.has(row.id));
      });
      dataTableBody.appendChild(tr);
    });
  }

  function setSelected(id, selected) {
    if (selected) state.selected.add(id);
    else state.selected.delete(id);
    renderRows();
    update();
  }

  function renderPreview() {
    const first = selectedRows()[0];
    const ready = first && state.recipeSelected;
    previewEmpty.hidden = Boolean(ready);
    fieldPreview.hidden = !ready;
    fieldPreview.replaceChildren();

    if (!ready) {
      readyCount.textContent = "대기";
      readyCount.classList.remove("is-ready");
      return;
    }

    readyCount.textContent = "필드 4개 준비";
    readyCount.classList.add("is-ready");
    [
      ["성명", first.name],
      ["부서", first.department],
      ["직위", first.position],
      ["임용일", first.date.replaceAll("-", ". ")],
    ].forEach(([label, value]) => {
      const row = document.createElement("div");
      row.className = "field-row";
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = label;
      dd.textContent = value;
      row.append(dt, dd);
      fieldPreview.appendChild(row);
    });
  }

  function update() {
    const count = state.selected.size;
    selectionCount.textContent = `선택 ${count}/${DEMO_ROWS.length}`;
    renderPreview();

    if (count === 0) {
      actionSummary.textContent = "행을 선택하세요.";
      actionDetail.textContent = "데이터 전체가 자동으로 선택되지 않습니다.";
    } else if (!state.recipeSelected) {
      actionSummary.textContent = `${count}건 선택`;
      actionDetail.textContent = "적용할 레시피를 선택하세요.";
    } else {
      actionSummary.textContent = `${count}건 · 준비됨`;
      actionDetail.textContent = "신규 임용 통지서 · 확인할 문제 없음";
    }

    runButton.disabled = count === 0 || !state.recipeSelected || state.running;
    runButton.textContent = count > 0 ? `문서 ${count}건 만들기` : "문서 만들기";
  }

  function renderReceipt(rows) {
    document.getElementById("receiptSummary").textContent =
      `선택한 ${rows.length}건의 결과와 필드 확인 상태를 한곳에 모았습니다.`;
    document.getElementById("verifiedSummary").textContent =
      `필드 ${rows.length * 4}/${rows.length * 4} 준비`;

    const outputList = document.getElementById("outputList");
    outputList.replaceChildren();
    rows.forEach((row) => {
      const li = document.createElement("li");
      const name = document.createElement("span");
      const status = document.createElement("span");
      name.textContent = `${row.name}_신규 임용 통지서.hwpx`;
      status.textContent = "필드 4개 준비";
      li.append(name, status);
      outputList.appendChild(li);
    });
  }

  document.getElementById("openDemoBtn").addEventListener("click", () => {
    resetRun();
    show(workspaceView);
  });

  document.getElementById("changeDataBtn").addEventListener("click", () => {
    resetRun();
    show(startView);
  });

  document.getElementById("brandHome").addEventListener("click", (event) => {
    event.preventDefault();
    resetRun();
    show(startView);
  });

  recipeChoice.addEventListener("click", () => {
    state.recipeSelected = !state.recipeSelected;
    recipeChoice.setAttribute("aria-pressed", String(state.recipeSelected));
    update();
  });

  runButton.addEventListener("click", () => {
    if (runButton.disabled) return;
    state.running = true;
    runButton.disabled = true;
    runButton.textContent = "결과 정리 중…";
    const rows = selectedRows();
    window.setTimeout(() => {
      renderReceipt(rows);
      show(receiptView);
      state.running = false;
    }, 420);
  });

  document.getElementById("restartBtn").addEventListener("click", () => {
    resetRun();
    show(startView);
  });

  renderRows();
  update();
})();
