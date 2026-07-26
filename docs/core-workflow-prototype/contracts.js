(function () {
  "use strict";

  const freezeEntries = (value) => Object.freeze(
    Object.fromEntries(Object.entries(value).map(([key, item]) => [key, Object.freeze(item)]))
  );

  /*
   * 제품 구현에 전달할 워크플로 계약.
   * 화면 ID와 실제 작업 상태는 별개다. UI는 이 정의에서 단계 이름·주 행동·복귀 규칙을 읽고,
   * 런타임 상태(validation/run/save/preview)는 app의 state에서 독립적으로 보관한다.
   */
  const workflow = freezeEntries({
    data: {
      label: "문서 만들기",
      entryCondition: "데이터가 분석되었거나 시안 데이터가 선택되어 있음",
      completionCondition: "항목과 문서를 선택하고 자동 검증을 통과함",
      primaryAction: "문서 생성 또는 검토·복사 시작",
      next: "result",
      back: null,
      failure: "data",
      actions: ["selectRecords", "selectDocument", "validateRun", "openSettings", "editConnection"],
      restrictions: ["필수 연결 누락 중 생성 불가", "대기·실패 중 중복 실행 불가"]
    },
    settings: {
      label: "문서 설정",
      entryCondition: "설정할 문서가 선택되어 있음",
      completionCondition: "템플릿 상태와 연결 상태를 확인함",
      primaryAction: "이 문서로 만들기",
      next: "data",
      back: "data",
      failure: "settings",
      actions: ["inspectStructure", "editConnection", "openExternalEditor", "showDeferredTxtEditor"],
      restrictions: ["설정 화면 조회만으로 실행 문서가 확정되지 않음"]
    },
    connection: {
      label: "연결 편집",
      entryCondition: "문서와 데이터 형식이 고정되어 있음",
      completionCondition: "필수 연결과 표시 규칙 검증 후 저장됨",
      primaryAction: "연결 저장",
      next: "returnView",
      back: "returnView",
      failure: "connection",
      actions: ["changeMapping", "suggestEmptyMappings", "saveConnection"],
      restrictions: ["저장 실패 시 편집값 보존", "필수 연결 누락 중 저장 불가"]
    },
    preview: {
      label: "생성 값 확인",
      entryCondition: "실행 컨텍스트 검증을 통과함",
      completionCondition: "필수 게이트이면 사용자가 결과 확인을 명시적으로 완료함",
      primaryAction: "결과 확인 완료 또는 문서 생성",
      next: "result",
      back: "data",
      failure: "preview",
      actions: ["createValuePreview", "approvePreview", "generateDocuments"],
      restrictions: ["HWPX 최종 모양을 재현하지 않음", "열기만으로 확인 완료 처리하지 않음"]
    },
    workbench: {
      label: "검토·복사",
      entryCondition: "텍스트 템플릿과 하나 이상의 항목이 선택됨",
      completionCondition: "선택한 모든 항목을 복사 완료함",
      primaryAction: "현재 항목 복사",
      next: "result",
      back: "data",
      failure: "workbench",
      actions: ["adjustSessionMapping", "copyDraft", "saveDraft", "saveDraftAsTemplate"],
      restrictions: ["복사 후에도 원래 항목 순서 보존", "표시 규칙 변경 시 완료 항목 재확인"]
    },
    result: {
      label: "처리 결과",
      entryCondition: "생성 또는 복사 요청이 끝남",
      completionCondition: "성공 결과를 확인하거나 실패 원인과 영향을 받은 입력을 확인함",
      primaryAction: "실패 원인 확인 및 입력 교정",
      next: "data",
      back: "data",
      failure: "result",
      actions: ["inspectFailure", "correctFailureInput", "retryFailedDocuments", "returnToData"],
      restrictions: ["부분 성공을 전체 성공으로 표시하지 않음", "원인 확인 전 재실행을 주 행동으로 두지 않음"]
    }
  });

  /*
   * v3 편집 워크플로. v2의 화면 계약은 회귀 확인을 위해 위에 보존하고, v3는
   * "증거가 생긴 표면 → 한 편집기 → 같은 위치 복귀"를 별도 정본으로 사용한다.
   */
  const workflowV3 = freezeEntries({
    data: {
      label: "문서 만들기",
      entryCondition: "데이터가 분석되었거나 시안 데이터가 선택되어 있음",
      completionCondition: "항목과 문서를 선택하고 자동 검증을 통과함",
      primaryAction: "문서 생성 또는 검토·복사 시작",
      next: "result",
      back: null,
      failure: "data",
      actions: ["selectRecords", "selectDocument", "validateRun", "openWorkEditor"],
      restrictions: ["필수 연결 누락 중 생성 불가", "단순 문서 작업 조회는 실행 문서 선택 사건이 아님"]
    },
    library: {
      label: "문서 작업",
      entryCondition: "저장된 문서 작업 목록을 조회함",
      completionCondition: "문서 작업을 조회하거나 편집을 마치고 목록으로 돌아옴",
      primaryAction: "문서 작업 열기",
      next: "editor",
      back: "data",
      failure: "library",
      actions: ["searchDocumentWork", "openWorkEditor", "showDeferredNewWork"],
      restrictions: ["목록 조회로 실행 문서·검증·미리보기 승인을 바꾸지 않음"]
    },
    editor: {
      label: "문서 작업 편집기",
      entryCondition: "문서와 편집 section이 EditContext로 고정되어 있음",
      completionCondition: "변경 범위를 선택해 적용하거나 draft를 버리고 ReturnContext로 복귀함",
      primaryAction: "선택한 범위로 변경 적용",
      next: "returnContext",
      back: "returnContext",
      failure: "editor",
      actions: ["editTemplate", "editBinding", "editExecutionProfile", "testChange", "applyScope"],
      restrictions: ["Run-only 변경은 기본 revision을 바꾸지 않음", "저장·검증·미리보기 승인을 서로 다른 사건으로 유지"]
    },
    preview: {
      label: "생성 값 확인",
      entryCondition: "실행 컨텍스트 검증을 통과함",
      completionCondition: "필수 게이트이면 사용자가 결과 확인을 명시적으로 완료함",
      primaryAction: "결과 확인 완료 또는 문서 생성",
      next: "result",
      back: "data",
      failure: "preview",
      actions: ["createValuePreview", "approvePreview", "openWorkEditor", "generateDocuments"],
      restrictions: ["결과 요소는 소유 규칙으로 deep-link", "미리보기 생성만으로 승인하지 않음"]
    },
    workbench: {
      label: "검토·복사",
      entryCondition: "텍스트 템플릿과 하나 이상의 항목이 선택됨",
      completionCondition: "선택한 모든 항목을 복사 완료함",
      primaryAction: "현재 항목 복사",
      next: "result",
      back: "data",
      failure: "workbench",
      actions: ["adjustSessionRule", "openWorkEditor", "copyDraft", "saveDraft"],
      restrictions: ["레코드 순서 고정", "세션 조정과 영구 규칙 저장을 구분"]
    },
    result: {
      label: "처리 결과",
      entryCondition: "생성 또는 복사 요청이 끝남",
      completionCondition: "결과를 확인하거나 증거에서 정확한 교정 위치로 이동함",
      primaryAction: "원인과 영향 범위 확인",
      next: "data",
      back: "data",
      failure: "result",
      actions: ["inspectFailure", "openWorkEditor", "returnToData"],
      restrictions: ["확정 원인과 미확정 원인을 구분", "부분 성공을 전체 성공으로 표시하지 않음"]
    }
  });

  const editContract = Object.freeze({
    sections: Object.freeze(["template", "binding", "execution", "test"]),
    entryReasons: Object.freeze([
      "voluntary",
      "library",
      "schema_new_field",
      "schema_missing_field",
      "preview_result",
      "run_failure",
      "output_result",
      "workbench_result"
    ]),
    ownerRoutes: Object.freeze({
      template: "문구·표·토큰·서명란·문서 구조",
      binding: "데이터 항목·값 유형·표시형·빈 값·계산",
      execution: "파일명·출력 위치·충돌 정책·실행 모드",
      run: "특정 레코드 또는 이번 실행 예외"
    }),
    returnRules: Object.freeze({
      preview: "drawer와 previewIndex를 복원하고 같은 결과 요소를 강조",
      data: "파일·선택·검색·실행 문서를 유지하고 원래 경고를 강조",
      result: "같은 실행 결과와 실패 또는 출력 항목을 강조",
      workbench: "workIndex·미리보기 종류·탭과 결과 토큰을 복원",
      library: "검색어·스크롤 위치와 문서 카드를 복원"
    }),
    scopePolicies: Object.freeze({
      run: "Run draft override만 변경하고 기본 revision은 유지",
      default: "새 기본 revision 저장 후 현재 실행 컨텍스트를 별도 재검증",
      fork: "현재 작업을 유지한 별도 변형이며 v3에서는 지원 범위 안내"
    })
  });

  /*
   * v4 교정 계약. workflowV3/editContract는 v3 회귀 확인을 위해 보존한다.
   * 현재 제품 경계는 template_path의 확장자, mapping, filename_pattern이며
   * 편집 저장 단위는 한 EditContext에서 만든 한 section patch다.
   */
  const workflowV4 = freezeEntries({
    data: {
      label: "문서 만들기",
      entryCondition: "데이터 분석과 레코드 선택이 존재함",
      completionCondition: "활성 문서 작업의 자동 검증과 필요한 결과 확인을 통과함",
      primaryAction: "문서 생성 또는 텍스트 검토·복사 시작",
      next: "result",
      back: null,
      failure: "data",
      actions: ["selectRecords", "selectWork", "validateRun", "openWorkEditor", "createCustomerWork"],
      restrictions: ["template_path가 매체를 결정", "문서 작업 조회는 활성 실행 작업을 바꾸지 않음"]
    },
    library: {
      label: "문서 작업",
      entryCondition: "저장된 문서 작업을 조회함",
      completionCondition: "한 작업을 조회·편집하고 목록 위치로 복귀함",
      primaryAction: "문서 작업 열기",
      next: "editor",
      back: "data",
      failure: "library",
      actions: ["searchWork", "openWorkEditor"],
      restrictions: ["활성 작업과 같은 작업을 바꾸면 기존 검증·승인을 폐기"]
    },
    editor: {
      label: "문서 작업 편집기",
      entryCondition: "EditContext가 workId·section·target·evidence·ReturnContext를 고정함",
      completionCondition: "현재 section patch 하나를 적용하거나 버림",
      primaryAction: "문맥별 주 범위로 현재 patch 적용",
      next: "returnContext",
      back: "returnContext",
      failure: "editor",
      actions: ["editTemplate", "editBinding", "editFilename", "testPatch", "applyPatch"],
      restrictions: ["한 진입에서 한 section patch", "상속된 실행 override를 기본 규칙 저장에 포함하지 않음"]
    },
    preview: {
      label: "생성 값 미리보기",
      entryCondition: "실행 검증을 통과함",
      completionCondition: "필요한 경우 사용자가 결과 확인을 명시적으로 승인함",
      primaryAction: "결과 확인 완료 또는 실행",
      next: "result",
      back: "data",
      failure: "preview",
      actions: ["createValuePreview", "approvePreview", "openWorkEditor"],
      restrictions: ["모든 결과 수정은 한 편집기로 deep-link", "생성은 승인 사건이 아님"]
    },
    workbench: {
      label: "텍스트 검토·복사",
      entryCondition: "TXT 문서 작업과 하나 이상의 레코드가 선택됨",
      completionCondition: "선택 레코드를 복사 완료함",
      primaryAction: "현재 항목 복사",
      next: "result",
      back: "data",
      failure: "workbench",
      actions: ["adjustSessionPatch", "persistBindingPatch", "copyRecord"],
      restrictions: ["최초 레코드 순서 고정", "영구 저장은 표시된 dirty 필드만 포함"]
    },
    result: {
      label: "처리 결과",
      entryCondition: "실행 요청이 끝남",
      completionCondition: "결과를 닫거나 실패 레코드만 교정·재시도함",
      primaryAction: "원인과 영향 범위 확인",
      next: "data",
      back: "data",
      failure: "result",
      actions: ["inspectFailure", "retryFailedRecord", "editRecordFilename"],
      restrictions: ["성공 결과 보존", "런타임 충돌을 영구 편집기 속성으로 만들지 않음"]
    }
  });

  const editContractV4 = Object.freeze({
    sectionsByMedia: Object.freeze({
      hwpx: Object.freeze(["template", "binding", "filename", "test"]),
      txt: Object.freeze(["template", "binding", "test"])
    }),
    persistentCore: Object.freeze(["template_path", "mapping", "filename_pattern"]),
    transaction: Object.freeze({
      inputs: Object.freeze(["baseSnapshot", "inheritedRunOverrides", "patch"]),
      saveUnit: "patch",
      restriction: "effective draft 전체를 저장하지 않음"
    }),
    scopePolicy: Object.freeze({
      activeRunPrimary: "run",
      activeRunSecondary: "default",
      libraryPrimary: "default",
      templatePrimary: "default",
      templateSecondary: "fork",
      source: "현재 patch와 활성 Run 존재 여부에서 매번 산출"
    }),
    invalidation: Object.freeze({
      sameActiveWorkDefaultSave: "validation과 필요한 preview approval 폐기",
      runPatch: "현재 preview approval 폐기, 기본 revision 유지"
    }),
    returnRules: editContract.returnRules
  });

  /*
   * 처음 보는 데이터 형식에는 근거 없는 문서 작업을 추천하지 않는다. 정확한 LogicalDataset
   * 식별과 저장 Binding이 없으면 사용자가 대상 문서를 먼저 고른 뒤 연결 draft를 만든다.
   */
  const newConnection = freezeEntries({
    unselected: {
      label: "대상 문서 미선택",
      entryCondition: "정확히 일치하는 저장 연결이 없는 새 데이터 형식",
      primaryAction: "문서 작업 직접 고르기",
      next: "choosing"
    },
    choosing: {
      label: "문서 목록에서 선택 중",
      entryCondition: "사용자가 자동 추천이 아닌 전체 문서 목록을 열었음",
      primaryAction: "연결할 문서 선택",
      next: "targetSelected"
    },
    targetSelected: {
      label: "대상 문서 선택됨",
      entryCondition: "사용자가 연결할 문서를 명시적으로 선택함",
      primaryAction: "새 연결 만들기",
      next: "editing"
    },
    editing: {
      label: "연결 작성 중",
      entryCondition: "문서와 데이터 형식이 고정되고 Binding draft가 생성됨",
      primaryAction: "새 연결 저장",
      next: "savedPendingPreview"
    },
    savedPendingPreview: {
      label: "저장됨 · 결과 확인 필요",
      entryCondition: "Binding revision 저장과 실행 재검증이 완료됨",
      primaryAction: "생성 값 확인",
      next: "ready"
    },
    ready: {
      label: "실행 준비 완료",
      entryCondition: "사용자가 새 연결의 생성 값을 확인함",
      primaryAction: "문서 생성 또는 검토·복사 시작",
      next: "result"
    }
  });

  /*
   * 코드·정본 문서에서 확인한 기능 상태. UI는 status가 deferred/unsupported/removed인 기능을
   * 성공 가능한 현재 행동으로 노출하지 않는다.
   */
  const capabilities = freezeEntries({
    selectRecords: {
      status: "supported",
      operations: ["SelectionModel"]
    },
    validateRun: {
      status: "composed",
      operations: ["validate mapping", "check empty values", "check output collisions"]
    },
    saveConnection: {
      status: "composed",
      operations: ["save mapping", "save job revision", "revalidate run context"]
    },
    createValuePreview: {
      status: "composed",
      operations: ["mapping value_for", "preview counts", "filename preview"],
      reason: "HWPX 화면 렌더가 아니라 실제로 주입될 값과 파일명을 확인합니다."
    },
    pixelPerfectHwpxPreview: {
      status: "removed",
      reason: "한글 렌더러와 다른 화면을 최종 문서 모양처럼 약속하지 않습니다."
    },
    generateDocuments: {
      status: "supported",
      operations: ["generate_batch", "GenerateResult"]
    },
    cancelBatch: {
      status: "supported",
      operations: ["generate_batch cancelled callback"],
      reason: "현재 문서를 마친 뒤 레코드 경계에서 취소됩니다."
    },
    retryFailedDocuments: {
      status: "composed",
      operations: ["failed record selection", "corrected run context validation", "generate_batch"],
      reason: "실패 원인과 입력을 확인하고 필요한 교정을 마친 뒤에만 후속 행동으로 제공합니다."
    },
    inspectFailure: {
      status: "deferred",
      reason: "시안에는 실제 백엔드 실패 원인과 항목별 진단 데이터가 연결되어 있지 않습니다."
    },
    correctFailureInput: {
      status: "composed",
      operations: ["preserve failed record selection", "openWorkEditor with evidence", "revalidate run context", "ReturnContext"]
    },
    inferValueType: {
      status: "supported",
      operations: ["existing value sniffing", "user type override"],
      reason: "추론된 유형임을 표시하고 사용자가 텍스트·날짜·금액 중 다시 고를 수 있습니다."
    },
    directValue: {
      status: "supported",
      operations: ["const mapping", "literal value"],
      reason: "데이터 항목 대신 직접 입력한 고정값을 모든 선택 레코드에 사용합니다."
    },
    recommendDocumentWork: {
      status: "deferred",
      reason: "유사 스키마의 자동 추천 기준과 신뢰도 계약이 없어, 새 데이터 형식에서는 목록을 비우고 사용자가 문서를 직접 고릅니다."
    },
    copyDraft: {
      status: "supported",
      operations: ["copy_clipboard", "TxtQueueModel"]
    },
    saveDraft: {
      status: "supported",
      operations: ["draft session save"]
    },
    saveDraftAsTemplate: {
      status: "supported",
      operations: ["draft session save_template"]
    },
    editTxtTemplate: {
      status: "deferred",
      reason: "전용 편집 화면의 범위와 저장 계약이 아직 확정되지 않았습니다."
    },
    openExternalEditor: {
      status: "composed",
      operations: ["open_path", "template refresh", "compile status"],
      reason: "외부 편집 뒤 사용자가 돌아와 변경 확인을 요청하는 흐름입니다."
    },
    inspectStructure: {
      status: "supported",
      operations: ["template schema", "token scan"]
    },
    evidenceDeepLink: {
      status: "composed",
      operations: ["EditContext", "owner route", "target focus", "ReturnContext"],
      reason: "시안 상태로 정확한 탭·항목 진입과 원래 표면 복귀를 검증합니다."
    },
    runOverridePrototype: {
      status: "composed",
      operations: ["prototype Run draft override", "preview invalidation", "value preview refresh"],
      reason: "Run 영속 API가 아니라 v3 시안의 명시적 mock 상태입니다."
    },
    patchOnlyEditorV4: {
      status: "composed",
      operations: ["base snapshot", "inherited run overrides", "single-section patch"],
      reason: "v4는 유효 초안 전체가 아니라 현재 EditContext의 patch만 저장합니다."
    },
    mediaDerivedFlowV4: {
      status: "composed",
      operations: ["template_path suffix", "media-specific tabs", "media-specific actions"],
      reason: "매체 전환 설정 없이 템플릿 경로의 확장자로 HWPX와 TXT 흐름을 나눕니다."
    },
    createCustomerWorkV4: {
      status: "composed",
      operations: ["new work identity", "mapping patch", "validation", "preview gate"],
      reason: "고객 데이터 수용 시나리오를 위한 최소 생성 흐름이며 완전한 마법사는 아닙니다."
    },
    browseCurrentDataDocumentsV5: {
      status: "composed",
      operations: ["runtime DataTarget fields", "saved Binding compatibility", "favorite and last_run_at ordering", "ReturnContext"],
      reason: "전역 라이브러리와 분리된 현재 DataTarget 하위 탐색면입니다."
    },
    favoriteDocumentWorkV5: {
      status: "composed",
      operations: ["prototype localStorage metadata", "stable main ordering"],
      reason: "시안에서는 localStorage mock이며 Job의 영구 메타데이터 mutation은 아직 연결하지 않습니다."
    },
    repairBindingFromDocumentsV5: {
      status: "composed",
      operations: ["compatibilityFor evidence", "EditContext binding deep-link", "default Binding revision save", "ReturnContext"],
      reason: "Run-only override로 끝내지 않고 기존 patch-only 편집기의 기본 저장 거래를 재사용합니다."
    },
    switchToDefaultDatasetV5: {
      status: "composed",
      operations: ["Dataset Pool reference check", "explicit user confirmation", "atomic mount", "preferredWorkId", "validateRun"],
      reason: "default_dataset_ref는 사용자 확인 없는 자동 전환 명령이 아닙니다."
    },
    createTemplateBasedWorkV5: {
      status: "composed",
      operations: ["new work identity", "safe binding draft", "patch-only save", "validateRun", "preview gate"],
      reason: "수용 흐름을 위한 최소 생성 경로이며 완전한 신규 작업 마법사는 아닙니다."
    },
    quickRecordRangeV5: {
      status: "composed",
      operations: ["LoadedDataSnapshot", "RecordRangeState", "shared filter derivation", "additive visible selection"],
      reason: "메인의 단순 의도 선택과 전문 편집기가 같은 스냅샷·범위 상태를 소비합니다."
    },
    columnFilterV5: {
      status: "composed",
      operations: ["global search", "column text", "value OR", "cross-column AND", "date/amount comparison"],
      reason: "백엔드 FilterModel의 값·텍스트·범위 의미를 시안 상태에 재현하되 중첩 식 빌더는 만들지 않습니다."
    },
    recordRangeEditorV5: {
      status: "composed",
      operations: ["draft clone", "dirty guard", "explicit apply", "ReturnContext"],
      reason: "문서 작업 EditContext와 분리된 현재 runtimeData 범위 편집 거래입니다."
    },
    snapshotWysiwygV5: {
      status: "composed",
      operations: ["snapshot-local identity", "OrderedSelection", "preview", "HWPX", "TXT session copy"],
      reason: "제품 계약 정본이며 실제 백엔드에는 ordered indices 배선이 더 필요합니다."
    },
    savedRecordView: {
      status: "deferred",
      reason: "현재 작업은 세션 범위 선택이며 이름 붙인 보기 저장은 별도 제품 결정입니다."
    },
    persistentRecordRange: {
      status: "removed",
      reason: "레코드 스냅샷과 선택 범위는 현재 실행 세션 밖으로 영속하지 않습니다."
    },
    virtualRecordRows: {
      status: "deferred",
      reason: "320건 벤치마크 뒤 병목이 확인될 때만 윈도잉 또는 가상화를 결정합니다."
    },
    runtimeCollisionRecoveryV4: {
      status: "composed",
      operations: ["preserve successes", "record filename override", "retry one failed record"],
      reason: "이름 충돌을 영구 문서 작업 속성으로 저장하지 않고 실패 레코드의 Run context에서 복구합니다."
    },
    executionProfilePrototype: {
      status: "composed",
      operations: ["prototype ExecutionProfile state", "revision fingerprint", "run revalidation"],
      reason: "현재 백엔드 저장 구조와 같다고 추정하지 않는 시안 전용 모델입니다."
    },
    templateDiff: {
      status: "deferred",
      reason: "실제 HWPX diff 엔진은 연결되지 않았으며 v3는 샘플 후보 요약임을 명시합니다."
    },
    unknownFailureDiagnosis: {
      status: "deferred",
      reason: "실제 진단 API가 없어 확인 가능한 단계·레코드·메시지·revision만 표시합니다."
    },
    liveCollaboration: {
      status: "unsupported",
      reason: "동시 편집과 충돌 해결을 지원하지 않습니다."
    }
  });

  const prototypeOutcomes = freezeEntries({
    success: {
      label: "정상 처리",
      description: "검증·저장·미리보기·실행이 완료됩니다."
    },
    previewFailure: {
      label: "미리보기 실패",
      description: "입력과 선택을 보존하고 원인 확인·입력 교정으로 돌아가는 흐름을 보여줍니다."
    },
    saveFailure: {
      label: "저장 실패",
      description: "실제 원인 진단은 만들지 않고, 편집값을 유지한 채 원인과 입력을 확인하는 흐름을 보여줍니다."
    },
    partialResult: {
      label: "문서 일부 실패",
      description: "성공 결과와 실패 항목을 보존하고 실패 원인 확인·입력 교정을 먼저 안내합니다."
    },
    processingFailure: {
      label: "문서 생성 실패",
      description: "이전 성공 결과와 입력을 보존하고 원인 확인·입력 교정으로 돌아갑니다."
    }
  });

  /*
   * v5 데이터 선택 확장. v4 편집 거래는 그대로 두고 실행 입력의 검사·시트 확정·원자 교체를
   * 앞단에 추가한다. Dataset Pool은 별도 데이터 제품이 아니라 고정 참조의 백엔드 실체다.
   */
  const workflowV5 = freezeEntries({
    dataEmpty: {
      label: "데이터 선택",
      entryCondition: "복원 가능한 마지막 물림이 없음",
      completionCondition: "파일 검사와 필요한 시트 확정 뒤 레코드 읽기 성공",
      primaryAction: "데이터 선택",
      next: "records",
      back: null,
      failure: "dataEmpty",
      actions: ["inspectDataFile", "chooseSheet", "mountDataTarget"],
      restrictions: ["다중 시트 자동 선택 금지", "실패한 후보를 현재 데이터로 저장하지 않음"]
    },
    dataChoosing: {
      label: "데이터 바꾸기",
      entryCondition: "현재 실행면에서 보조 선택 표면을 엶",
      completionCondition: "새 후보 로드와 필요한 전환 확인 완료",
      primaryAction: "새 데이터 후보 선택",
      next: "records",
      back: "records",
      failure: "records",
      actions: ["inspectDataFile", "choosePinnedReference", "relinkDatasetReference"],
      restrictions: ["성공 전 runtimeData 보존", "월별 직접 파일 자동 고정 금지"]
    },
    records: {
      label: "레코드 범위와 문서 작업 선택",
      entryCondition: "runtimeData가 ready이며 선택 0건·검색/필터 없음·최신 행 먼저로 시작함",
      completionCondition: "OrderedSelection이 1건 이상이고 현재 DataTarget 호환 작업을 명시적으로 선택해 권위 있는 실행 검증을 통과함",
      primaryAction: "문서 생성 또는 검토·복사",
      next: "result",
      back: "dataChoosing",
      failure: "records",
      actions: ["searchRecords", "filterColumns", "selectVisibleRecords", "editRecordRange", "selectCompatibleWork", "browseCurrentDataDocuments", "validateRun", "openWorkEditor"],
      restrictions: ["행 수만으로 전문 편집기를 강제하지 않음", "호환성 판정은 실행 검증을 대체하지 않음", "우선 노출은 activeWorkId 선택 사건이 아님", "라이브러리 조회는 현재 데이터와 activeWorkId를 바꾸지 않음"]
    },
    documents: {
      label: "현재 데이터에 사용할 문서 탐색",
      entryCondition: "runtimeData.loadState가 ready이고 사용자가 전체 탐색을 명시적으로 엶",
      completionCondition: "사용 가능한 작업을 선택하거나 원인에 맞는 연결·전환·새 identity 경로로 진입함",
      primaryAction: "이 문서 선택 또는 원인별 해결",
      next: "records",
      back: "records",
      failure: "documents",
      actions: ["toggleDocumentFavorite", "repairBinding", "confirmDefaultDatasetSwitch", "createDocumentIdentity"],
      restrictions: ["전역 문서 작업 라이브러리가 아님", "다른 데이터 구조에 기존 Binding 자동 덮어쓰기 금지", "검색은 문서 표시 이름만 사용"]
    }
  });

  const documentSelectionV5 = Object.freeze({
    candidateGate: "runtimeData.loadState === ready",
    compatibility: Object.freeze({
      available: "저장 identity + 모든 필수 source 선언 + 직접 입력 필수값 존재 + runtime field 존재",
      executionValidation: "작업 선택 뒤 validateRun으로 별도 수행",
      singleSource: "compatibilityFor"
    }),
    main: Object.freeze({
      limit: 5,
      order: Object.freeze(["favorite timestamp desc", "last_run_at desc", "display name"]),
      sections: Object.freeze(["즐겨찾기", "최근 사용", "다른 문서"]),
      selection: "노출과 분리된 명시적 사용자 사건"
    }),
    browser: Object.freeze({
      surface: "documents",
      tabs: Object.freeze(["available", "needsAction"]),
      queryTargets: Object.freeze(["saved work display name", "template-only display name"]),
      returnContext: Object.freeze(["documentTab", "documentQuery", "scrollY", "focusTarget"])
    }),
    needsAction: Object.freeze({
      bindingDrift: "binding/<firstMissingFieldId>",
      defaultDataset: "명시적 확인 뒤 원자 데이터 전환과 preferredWorkId 선택",
      differentData: "새 work identity; 기존 Binding 불변",
      templateOnly: "새 work identity",
      damaged: "지원 경계와 실제 손상 이유 표시"
    }),
    favorite: Object.freeze({
      label: "즐겨찾기",
      prototypePersistence: "localStorage mock",
      effect: "정렬 메타데이터만 변경; revision/validation/preview approval 불변"
    })
  });

  const recordRangeV5 = Object.freeze({
    dataAuthority: "dataState.runtimeData LoadedDataSnapshot",
    owner: "runtimeData.snapshotId",
    initial: Object.freeze({
      selectedCount: 0,
      search: "",
      columnFilters: Object.freeze({}),
      viewOrder: "sourceDesc",
      shiftAnchorId: null
    }),
    identity: Object.freeze({
      recordRef: "snapshotId + snapshotRecordId",
      order: "snapshotOrdinal",
      diagnostic: "sourceRowNumber"
    }),
    derivation: Object.freeze([
      "orderedSnapshotRecords",
      "filteredRecordIds",
      "visibleOrderedRecords",
      "orderedSelectedRecords",
      "hiddenSelectedRecords",
      "headerSelectionState",
      "selectionFingerprint"
    ]),
    selection: Object.freeze({
      headerCheck: "현재 가시 결과를 기존 선택에 가산",
      headerUncheck: "현재 가시 결과만 해제",
      clearAll: "검색·필터와 무관하게 전역 해제",
      shiftRange: "현재 visibleOrderedRecords 순서"
    }),
    execution: "OrderedSelection 하나를 preview, HWPX record IDs, 파일 이름, TXT session이 공유",
    editor: Object.freeze({
      surface: "record-range",
      transaction: "draft clone -> explicit apply or discard",
      dirtyGuard: Object.freeze(["apply", "discard", "stay"]),
      selectedOnly: "검색과 열 필터를 일시 무시하는 보기 상태"
    })
  });

  const dataExtensionV5 = Object.freeze({
    identity: Object.freeze({
      excel: "path + sheet + optional headerRow",
      csv: "path + optional headerRow",
      referenceKey: "datasetRefName"
    }),
    stateAxes: Object.freeze(["documentWorkState", "editState", "runState", "workbenchState", "dataState"]),
    transition: Object.freeze({
      order: Object.freeze(["inspect", "chooseSheetIfNeeded", "loadRecords", "restateLossesIfNeeded", "atomicCommit"]),
      failure: "기존 runtimeData와 수작업 실행 상태 보존",
      reset: Object.freeze(["RecordRangeState(selected none, search none, filters none, sourceDesc)", "validation", "preview", "approval", "result", "runOverrides", "dismissedSuggestions", "workbenchSession"]),
      preserve: Object.freeze(["works", "bindings", "templateRevisions", "bindingRevisions", "librarySearch", "pinnedDataRefs"])
    }),
    capabilities: Object.freeze({
      inspectDataFilePrototype: Object.freeze({status:"composed",operations:["mock file metadata", "sheet overview", "header sample"]}),
      mountDataTargetPrototype: Object.freeze({status:"composed",operations:["fail-closed sheet check", "record load", "atomic UI commit"]}),
      datasetPoolProjection: Object.freeze({status:"supported",operations:["DatasetPoolItem", "DatasetPoolRegistry", "active projection"]}),
      mountedDataPersistencePrototype: Object.freeze({status:"composed",operations:["localStorage reference only", "runtime reread"]}),
      backendMountedDataPersistence: Object.freeze({status:"deferred",reason:"전역 마지막 물림 저장소는 현재 백엔드에 없음"}),
      automaticDatasetCatalog: Object.freeze({status:"removed",reason:"직접 선택 월별 파일은 자동 등록하지 않음"})
    })
  });

  window.WorkflowContract = Object.freeze({
    workflow,
    workflowV3,
    workflowV4,
    workflowV5,
    editContract,
    editContractV4,
    newConnection,
    dataExtensionV5,
    documentSelectionV5,
    recordRangeV5,
    capabilities,
    prototypeOutcomes
  });
})();
