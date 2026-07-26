(function () {
  "use strict";

  const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
  let activeRun = null;
  let sequence = 0;
  const failedOnce = new Set();

  const failure = (code, message, correctionScope) => {
    const error = new Error(message);
    error.code = code;
    error.cause = {
      status: "notConnected",
      summary: "이 시안에는 실제 실패 원인 진단이 연결되어 있지 않습니다."
    };
    error.correctionScope = correctionScope;
    error.recovery = `${error.cause.summary} ${correctionScope}을 확인하고 필요한 값을 고친 뒤 다시 진행하세요.`;
    return error;
  };
  const shouldFailOnce = (key, enabled) => {
    if (!enabled || failedOnce.has(key)) return false;
    failedOnce.add(key);
    return true;
  };

  const mockDocumentWorkflow = {
    async inspectDataFile({ path, file }) {
      await wait(260);
      if (!file || file.error) {
        throw failure(
          "DATA_INSPECTION_FAILED",
          file?.error || `${path} 파일을 찾을 수 없습니다.`,
          "새 데이터 후보"
        );
      }
      return {
        kind: file.kind,
        path,
        sheets: file.sheets.map((sheet) => ({
          name: sheet.name,
          rows: sheet.rows,
          columns: sheet.columns,
          headerSample: [...sheet.headerSample]
        }))
      };
    },

    async mountDataTarget({ path, fileName, kind, sheet, headerRow, file }) {
      await wait(320);
      if (!file || file.error) {
        throw failure(
          "DATA_LOAD_FAILED",
          file?.error || `${path} 파일을 찾을 수 없습니다.`,
          "새 데이터 후보"
        );
      }
      if (file.sheets.length > 1 && !sheet) {
        throw failure(
          "SHEET_REQUIRED",
          "시트가 여러 개인 파일은 사용할 시트를 명시해야 합니다.",
          "데이터 로드 경계"
        );
      }
      const selected = file.sheets.find((candidate) => candidate.name === (sheet || null));
      if (!selected) {
        throw failure(
          "SHEET_NOT_FOUND",
          "선택한 시트를 파일에서 찾을 수 없습니다.",
          "데이터 로드 경계"
        );
      }
      return {
        target: { path, fileName, kind, sheet: selected.name, headerRow: headerRow ?? null },
        fields: selected.fields.map((field) => ({ ...field })),
        records: selected.records.map((record) => ({ ...record })),
        displayMeta: { recordCount: selected.records.length, fieldCount: selected.fields.length }
      };
    },

    async validateRun(context) {
      await wait(320);
      if (!context.selectedCount) {
        throw failure("EMPTY_SELECTION", "실행 조건을 확인하지 못했습니다.", "선택한 항목");
      }
      return {
        validationId: `validation-${++sequence}`,
        status: "completed",
        checkedRevision: context.bindingRevision || 1
      };
    },

    async saveConnection(payload) {
      await wait(480);
      if (shouldFailOnce(`connection:${payload.documentId}`, payload.outcome === "saveFailure")) {
        throw failure(
          "SAVE_FAILED",
          "연결 저장 단계가 완료되지 않았습니다.",
          "보존된 연결 입력"
        );
      }
      return {
        bindingRevision: (payload.bindingRevision || 1) + 1,
        status: "saved"
      };
    },

    async saveEditorChange(payload) {
      await wait(460);
      if (shouldFailOnce(
        `editor:${payload.documentId}:${payload.section}`,
        payload.outcome === "saveFailure"
      )) {
        throw failure(
          "EDITOR_SAVE_FAILED",
          "기본 규칙 revision 저장 단계가 완료되지 않았습니다.",
          "보존된 편집기 draft"
        );
      }
      return {
        status: "saved",
        section: payload.section,
        bindingRevision: payload.section === "binding"
          ? (payload.bindingRevision || 1) + 1
          : payload.bindingRevision,
        templateRevision: payload.section === "template"
          ? (payload.templateRevision || 1) + 1
          : payload.templateRevision,
        executionRevision: payload.section === "execution"
          ? (payload.executionRevision || 1) + 1
          : payload.executionRevision
      };
    },

    async saveRunOverride(payload) {
      await wait(260);
      return {
        status: "saved",
        scope: "run",
        documentId: payload.documentId,
        changedTarget: payload.changedTarget
      };
    },

    async analyzeTemplateCandidate(payload) {
      await wait(420);
      return {
        status: "candidate",
        documentId: payload.documentId,
        isSample: true,
        addedTokens: ["{{지급일_설명}}"],
        removedTokens: [],
        affectedFields: ["지급일"],
        requiresTest: true
      };
    },

    async createValuePreview(payload) {
      await wait(420);
      if (shouldFailOnce("preview", payload.outcome === "previewFailure")) {
        throw failure(
          "PREVIEW_FAILED",
          "생성 값 준비 단계가 완료되지 않았습니다.",
          "보존된 데이터 선택과 연결"
        );
      }
      return {
        previewId: `preview-${++sequence}`,
        status: "completed",
        recordCount: payload.recordCount
      };
    },

    async runDocuments(payload, onProgress) {
      const run = { id: `run-${++sequence}`, cancelled: false };
      activeRun = run;
      const total = payload.recordCount;
      let completed = 0;
      for (let index = 0; index < total; index += 1) {
        await wait(220);
        if (run.cancelled) {
          activeRun = null;
          return {
            runId: run.id,
            status: completed ? "partiallyCompleted" : "cancelled",
            total,
            succeeded: completed,
            failed: 0,
            cancelled: total - completed,
            failedRecordIds: []
          };
        }
        completed += 1;
        if (onProgress) onProgress({ completed, total });
      }
      activeRun = null;

      if (payload.outcome === "processingFailure") {
        throw failure(
          "RUN_FAILED",
          "문서 생성 단계가 완료되지 않았습니다.",
          "확인 가능한 실패 증거와 사용 revision"
        );
      }
      if (payload.outcome === "partialResult" && total > 1) {
        return {
          runId: run.id,
          status: "partiallyCompleted",
          total,
          succeeded: total - 1,
          failed: 1,
          cancelled: 0,
          failedRecordIds: [payload.recordIds[total - 1]],
          failureDetails: [{
            recordId: payload.recordIds[total - 1],
            causeStatus: "confirmed",
            code: "OUTPUT_COLLISION",
            stage: "output_save",
            summary: "같은 이름의 파일이 있으며 현재 충돌 정책은 ‘중단’입니다."
          }]
        };
      }
      return {
        runId: run.id,
        status: "completed",
        total,
        succeeded: total,
        failed: 0,
        cancelled: 0,
        failedRecordIds: []
      };
    },

    cancelRun() {
      if (activeRun) activeRun.cancelled = true;
    },

    async retryFailedDocuments(payload, onProgress) {
      return this.runDocuments({ ...payload, outcome: "success" }, onProgress);
    },

    async saveDraft(payload) {
      await wait(420);
      if (shouldFailOnce(`draft:${payload.kind}`, payload.outcome === "saveFailure")) {
        throw failure(
          "DRAFT_SAVE_FAILED",
          `${payload.kind === "template" ? "템플릿" : "기안"} 저장 단계가 완료되지 않았습니다.`,
          "보존된 조정과 복사 상태"
        );
      }
      return { status: "saved", savedAt: new Date().toISOString() };
    }
  };

  /*
   * 실제 연결 시 이 한 줄의 구현체만 realDocumentWorkflow로 교체한다.
   * UI 이벤트는 mock 함수나 타이머를 직접 호출하지 않는다.
   */
  window.documentActions = mockDocumentWorkflow;
})();
