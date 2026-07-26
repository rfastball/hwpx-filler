(function () {
  const DEMO_ROWS = [
    { id: 1, name: "김나르미", department: "정책기획팀", position: "주무관", date: "2026-08-01" },
    { id: 2, name: "박문서", department: "복지행정팀", position: "팀장", date: "2026-08-01" },
    { id: 3, name: "이도움", department: "민원여권팀", position: "주무관", date: "2026-08-04" },
    { id: 4, name: "최가람", department: "문화관광팀", position: "주무관", date: "2026-08-04" },
  ];

  const FIELD_LABELS = {
    name: "성명",
    department: "부서",
    position: "직위",
    date: "임용일",
  };

  const state = {
    selected: new Set(),
    recipeSelected: false,
    currentStep: "data",
    running: false,
  };

  const startView = document.getElementById("startView");
  const runView = document.getElementById("runView");
  const dataStep = document.getElementById("dataStep");
  const recipeStep = document.getElementById("recipeStep");
  const overviewStep = document.getElementById("overviewStep");
  const dataTableBody = document.getElementById("dataTableBody");
  const recipeChoice = document.getElementById("recipeChoice");
  const runButton = document.getElementById("runButton");
  const tabs = {
    data: document.getElementById("dataTab"),
    recipe: document.getElementById("recipeTab"),
    test: document.getElementById("testTab"),
    overview: document.getElementById("overviewTab"),
  };

  function selectedRows() {
    return DEMO_ROWS.filter((row) => state.selected.has(row.id));
  }

  function showRoot(view) {
    startView.hidden = view !== "start";
    runView.hidden = view !== "run";
    window.scrollTo({ top: 0, behavior: "auto" });
  }

  function setStep(step) {
    state.currentStep = step;
    dataStep.hidden = step !== "data";
    recipeStep.hidden = step !== "recipe" && step !== "test";
    overviewStep.hidden = step !== "overview";
    Object.entries(tabs).forEach(([key, tab]) => {
      const active = key === step || (step === "overview" && key === "overview");
      tab.classList.toggle("is-active", active);
      if (active) tab.setAttribute("aria-current", "step");
      else tab.removeAttribute("aria-current");
    });
    window.scrollTo({ top: 0, behavior: "auto" });
  }

  function resetRun() {
    state.selected.clear();
    state.recipeSelected = false;
    state.running = false;
    recipeChoice.setAttribute("aria-pressed", "false");
    tabs.recipe.disabled = true;
    tabs.test.disabled = true;
    tabs.overview.disabled = true;
    runButton.textContent = "Test merge";
    renderRows();
    renderRecipe();
    updateDataStep();
    setStep("data");
  }

  function openDemo() {
    resetRun();
    showRoot("run");
  }

  function renderRows() {
    dataTableBody.replaceChildren();
    DEMO_ROWS.forEach((row) => {
      const tr = document.createElement("tr");
      const checked = state.selected.has(row.id);
      tr.classList.toggle("is-selected", checked);

      const checkCell = document.createElement("td");
      checkCell.className = "check-col";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = checked;
      checkbox.setAttribute("aria-label", `${row.name} 선택`);
      checkbox.addEventListener("change", () => setSelected(row.id, checkbox.checked));
      checkCell.appendChild(checkbox);

      const values = [row.name, row.department, row.position, row.date];
      tr.appendChild(checkCell);
      values.forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });

      const statusCell = document.createElement("td");
      const status = document.createElement("span");
      status.className = "row-status";
      status.textContent = "실행 전";
      statusCell.appendChild(status);
      tr.appendChild(statusCell);

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
    updateDataStep();
    renderRecipe();
  }

  function updateDataStep() {
    const count = state.selected.size;
    document.getElementById("selectionCount").textContent = `선택 ${count}/${DEMO_ROWS.length}`;
    document.getElementById("dataStepMessage").textContent = count
      ? `${count}건을 Recipe 단계로 보냅니다.`
      : "계속하려면 한 행 이상 선택하세요.";
    document.getElementById("continueButton").disabled = count === 0;
    tabs.recipe.disabled = count === 0;
  }

  function displayValue(key, value) {
    if (key !== "date") return value;
    const [year, month, day] = value.split("-");
    return `${year}. ${month}. ${day}`;
  }

  function renderRecipe() {
    const rows = selectedRows();
    const first = rows[0];
    document.getElementById("builderSelectionCount").textContent = `선택 ${rows.length}건`;
    const list = document.getElementById("mergeFieldList");
    const status = document.getElementById("fieldStatus");
    list.replaceChildren();

    document.querySelectorAll(".merge-pill").forEach((pill) => {
      const key = pill.dataset.field;
      pill.classList.toggle("is-filled", Boolean(first && state.recipeSelected));
      pill.textContent = first && state.recipeSelected
        ? displayValue(key, first[key])
        : FIELD_LABELS[key];
    });

    if (!first || !state.recipeSelected) {
      const p = document.createElement("p");
      p.textContent = "레시피를 선택하면 첫 행의 값을 연결합니다.";
      list.appendChild(p);
      status.textContent = "대기";
      document.getElementById("recipeStepMessage").textContent = "레시피를 선택하세요.";
      runButton.disabled = true;
      tabs.test.disabled = true;
      return;
    }

    Object.entries(FIELD_LABELS).forEach(([key, label]) => {
      const row = document.createElement("div");
      row.className = "field-map-row";
      const field = document.createElement("span");
      field.className = "field-name-pill";
      field.textContent = label;
      const value = document.createElement("strong");
      value.textContent = displayValue(key, first[key]);
      row.append(field, value);
      list.appendChild(row);
    });
    status.textContent = "4/4 준비";
    document.getElementById("recipeStepMessage").textContent =
      `${rows.length}건 · 확인할 문제 없음`;
    runButton.disabled = false;
  }

  function renderOverview(rows) {
    document.getElementById("overviewSummary").textContent =
      `${rows.length}건의 결과와 필드 값을 Recent Runs에 모았습니다.`;
    document.getElementById("documentCount").textContent = `${rows.length}건`;
    document.getElementById("verifiedCount").textContent = `${rows.length * 4}/${rows.length * 4}`;

    const resultBody = document.getElementById("resultTableBody");
    resultBody.replaceChildren();
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        `${row.name}_신규 임용 통지서.hwpx`,
        "신규 임용 통지서",
      ];
      values.forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });
      const status = document.createElement("td");
      status.className = "status-success";
      status.textContent = "완료";
      const verified = document.createElement("td");
      verified.className = "status-success";
      verified.textContent = "4/4 준비";
      tr.append(status, verified);
      resultBody.appendChild(tr);
    });
  }

  document.getElementById("openDemoBtn").addEventListener("click", openDemo);
  document.getElementById("recentDemoBtn").addEventListener("click", openDemo);

  document.getElementById("brandHome").addEventListener("click", (event) => {
    event.preventDefault();
    resetRun();
    showRoot("start");
  });

  document.getElementById("changeDataBtn").addEventListener("click", () => {
    resetRun();
    showRoot("start");
  });

  document.getElementById("continueButton").addEventListener("click", () => {
    if (state.selected.size === 0) return;
    setStep("recipe");
  });

  tabs.data.addEventListener("click", () => setStep("data"));
  tabs.recipe.addEventListener("click", () => {
    if (!tabs.recipe.disabled) setStep("recipe");
  });

  document.getElementById("backToDataButton").addEventListener("click", () => setStep("data"));

  recipeChoice.addEventListener("click", () => {
    state.recipeSelected = !state.recipeSelected;
    recipeChoice.setAttribute("aria-pressed", String(state.recipeSelected));
    renderRecipe();
  });

  runButton.addEventListener("click", () => {
    if (runButton.disabled) return;
    state.running = true;
    runButton.disabled = true;
    runButton.textContent = "Testing…";
    tabs.test.disabled = false;
    setStep("test");
    const rows = selectedRows();
    window.setTimeout(() => {
      renderOverview(rows);
      tabs.overview.disabled = false;
      setStep("overview");
      state.running = false;
    }, 420);
  });

  document.getElementById("newRunButton").addEventListener("click", () => {
    resetRun();
    showRoot("start");
  });

  renderRows();
  updateDataStep();
  renderRecipe();
})();
