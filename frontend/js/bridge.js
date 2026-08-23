/* 브리지 클라이언트 — pywebview.api(=Python WebFrontend)와 왕복. 화면-불가지.
   웹→Python 은 dispatch/네이티브 호스트 메서드 **24개**(데이터·네이티브 22 + 창 닫기 확인 2),
   Python→웹은 factory 가 돌려주는 `push(screen, snapshot)` 관측 푸시다.
   화면 모듈은 `bridge.onPush(screen, fn)` 로 렌더러를 등록한다 — 브리지는 화면 로직을 모른다.

   ## 이 파일이 유일한 백엔드 통로다(N-07)

   `pywebview.api` 판독은 여기 말고 어디에도 없다. 종전엔 앱 셸이 창 닫기 확인 두 호출을,
   테마·개인화가 준비 여부 판정을 각자 직접 만졌다 — 같은 호스트를 세 파일이 따로 아는 모양은
   ①프로브가 브리지만 갈아끼워도 그 경로들이 실물로 새고 ②백엔드 계약 변경이 세 자리에서
   따로 낡는다. 그래서 두 닫기 호출은 `confirmWindowClose`·`cancelWindowClose` 로, 준비 판정은
   `hostReady()` 로 이 표면에 올라왔다.

   ## factory 는 객체를 **살아 있는 채로** 돌려준다

   Python selftest 가 프로퍼티를 교체해(`…​.call = stub`) 통로를 갈아끼우므로 소비자는 객체
   참조를 들고 호출 시점에 메서드를 찾아야 한다. 여기서도, 소비자 쪽에서도 메서드를 값으로
   뽑지 않는다 — 뽑는 순간 요청은 프로브에 걸렸는데 발신은 실물로 새는 자리가 생긴다. */
const DISPATCH_REJECTION_KEY = "__hwpx_dispatch_rejection_v1__";

function unwrapDispatchResult(value) {
  if (!value || typeof value !== "object" || !Object.hasOwn(value, DISPATCH_REJECTION_KEY)) {
    return value;
  }
  const rejection = value[DISPATCH_REJECTION_KEY];
  if (!rejection || typeof rejection !== "object" || typeof rejection.message !== "string") {
    throw new Error("Python dispatch 거절 봉투가 손상되었습니다.");
  }
  const error = new Error(rejection.message);
  if (typeof rejection.name === "string" && rejection.name) error.name = rejection.name;
  throw error;
}

function unwrapDispatch(value) {
  return value && typeof value.then === "function"
    ? value.then(unwrapDispatchResult)
    : unwrapDispatchResult(value);
}

export function createBridge() {
  // screen id → [fn, ...] — 한 채널 복수 구독이 앞의 소비자를 조용히 밀어내지 않도록 배열로 둔다.
  const renderers = {};

  const bridge = {
    /** 화면 렌더러 등록 — Python 이 그 화면을 푸시하면 등록 순서대로 fn(snapshot) 이 불린다. */
    onPush(screen, fn) { (renderers[screen] = renderers[screen] || []).push(fn); },

    /** 호스트(백엔드) 준비 여부 — 브라우저 단독 프리뷰면 거짓. 재시도·캐시 없는 순간 판정이다:
     *  준비를 기다리는 일은 `pywebviewready` 이벤트가 지고, 여기선 "지금 호스트가 있는가"만
     *  답한다. 이 술어가 없으면 소비자가 호스트 내부 형태를 직접 알아야 한다. */
    hostReady() { return !!(window.pywebview && window.pywebview.api); },

    /** 화면 초기 상태 당김(부팅 1회). */
    initial(screen) { return window.pywebview.api.initial(screen); },

    /** 순수 데이터 액션(창 불필요) — Python 이 처리 후 관측 푸시로 되민다. */
    call(screen, action, payload) {
      return unwrapDispatch(window.pywebview.api.dispatch(screen, action, payload || {}));
    },

    /** 네이티브 파일 다이얼로그 → 링1 VM 로드. 파일명·"ERROR:…"·null(취소), 또는
     *  다중 시트면 {needs_sheet, path, name, sheets:[…]} 로 시트 확정을 요구(#33). */
    pickDataFile(screen) { return window.pywebview.api.pick_data_file(screen); },

    /** 확정한 시트로 다중 시트 워크북 로드(#33). 파일명·"ERROR:…"·null. */
    loadDataSheet(screen, path, sheet) {
      return window.pywebview.api.load_data_sheet(screen, path, sheet);
    },

    /** 템플릿 가져오기=복사(R-info 2부, 생 파일 직접 로드 pickTemplateFile 의 후계 — 신규
        1단계는 라이브러리가 정본) — 다이얼로그 → 라이브러리 복사 → 사본으로 새 세션.
        파일명·"ERROR:…"·null. */
    importTemplateFile(screen) { return window.pywebview.api.import_template_file(screen); },

    /** 「폴더에서 가져오기…」(#339 U2 §2.16) — ①무인자: 폴더 피커 → 읽기 전용 스캔 →
        재진술 dict(needs_confirm + 후보 files). ②(folder, true, files): 확정 실행 —
        재스캔이 아니라 **확정 시점 후보 목록**을 그대로 실행한다(재진술이 참이 되게,
        채택 없음 = 세션 무변경). null = 피커 취소, 실패 = {ok:false, error}. */
    importTemplatesFolder(folder, confirm, files) {
      return window.pywebview.api.import_templates_folder(folder || null, !!confirm, files || null);
    },

    /** 작업점 카드 렌더를 OS 클립보드로(복사=완료, 결정 16). 리포트(missing/empty) 반환.
        건별 파일 저장(saveFile)은 사망(결정 18) — 기록 원본이 내부 시스템, 산출물 무소유. */
    /** 클립보드 쓰기 — `token` 은 사전확인이 돌려준 **그 카드의 정체**다(F6 3R): 백엔드가
        대조해 어긋나면 쓰지 않는다("확인 대상 = 복사 대상"). 토큰 개념이 없는 화면은 생략. */
    copyClipboard(screen, token) { return window.pywebview.api.copy_clipboard(screen, token); },

    /** 네이티브 폴더 피커(SHBrowseForFolder) → 저장 폴더 지정. 경로·"ERROR:…"·null(취소). */
    pickOutputFolder(screen) { return window.pywebview.api.pick_output_folder(screen); },

    /** 실행 화면 동기 생성 — 게이트/덮어쓰기 재진술·결과 요약 dict 반환. */
    generate(screen, confirmOverwrite) {
      return window.pywebview.api.generate(screen, !!confirmOverwrite);
    },

    /* (importLibraryTemplate·loadTemplateIntoEditor 는 tpl 화면과 함께 사망(F8) — 가져오기는
       importTemplateFile 하나로 통일(§10.17.2 판정 C), 라이브러리 선택은 편집기 dispatch
       use_library_template 이 소유. 소비자 0 통로는 남기지 않는다.) */

    /** 에디터에 미저장 작업 세션이 있는가 — 크로스스크린 진입 전 폐기 확인 판단(#25). */
    editorHasUnsavedWork() { return window.pywebview.api.editor_has_unsaved_work(); },

    /** 「문서 작업」 상세 '작업 편집' → 저장된 작업을 에디터 편집 세션으로 복원(#26). 이름·"ERROR:…". */
    // context = {entry_reason, evidence, return_context}(계약 §5.1) — 진입 문맥은 **보낸
    // 표면**이 안다. 편집기가 되계산하면 배너가 사용자가 방금 본 것과 다른 말을 한다.
    openJobInEditor(name, context) {
      return window.pywebview.api.open_job_in_editor(name, context || {});
    },

    /** 「이 데이터로 새 작업」(U2 §2.4·§4 판정 E) — 「문서 만들기」의 마운트 데이터를 든
     *  신규 초안. 데이터의 정체는 **보내지 않는다**: 지금 무엇이 올라와 있는지의 단일
     *  출처는 그 화면의 컨트롤러이고, 웹이 기억한 값을 실으면 도착 순서에 따라 다른
     *  파일로 시작할 수 있다. 반환은 시작한 데이터 경로·"ERROR:…". */
    newJobFromData(context) {
      return window.pywebview.api.new_job_from_data(context || {});
    },

    /** 「문서 작업」 손상 카드 '폴더 열기' → 탐색기에서 파일 표시(#26 #8). null·"ERROR:…". */
    revealCorruptJob(path) { return window.pywebview.api.reveal_corrupt_job(path); },

    /** 데이터 고정·등록 모달 '찾아보기' → 경로만 반환(로드 없음, #26 #4). null=취소. */
    pickPoolDataFile() { return window.pywebview.api.pick_pool_data_file(); },

    /** 템플릿 다시 연결(#67) '찾아보기' → 경로만 반환(로드 없음). null=취소. */
    pickTemplatePath() { return window.pywebview.api.pick_template_path(); },

    /** 추적성 로케이트(#53-B) — 소유 경로 검증 후 열기/폴더보기/복사. null·"ERROR:…". */
    openPath(path) { return window.pywebview.api.open_path(path); },
    revealPath(path) { return window.pywebview.api.reveal_path(path); },
    copyPath(path) { return window.pywebview.api.copy_path(path); },

    /** 산출물 관찰의 「다른 이름으로 저장」(S7-03 · #825) — 파일 피커가 관여하므로 직접
     *  브리지다. 겨눔은 배달 문서의 `ordinal` 하나이고 bytes 는 웹이 만지지 않는다:
     *  백엔드가 그 자리에서 안착 파일을 다시 관찰해 검증된 bytes 를 그대로 옮긴다(D2).
     *  반환 {ok, status, detail, path} — 저장·취소·관찰 거절·SAVE_COPY_FAILED 가 서로
     *  다른 status 로 오므로 호출자가 넷을 구분해 말한다(fallback 금지). */
    saveArtifactAs(ordinal) { return window.pywebview.api.save_artifact_as(ordinal); },

    /** 테마 선택 영속(오리진 비의존 Python 설정, #74). 확정값(문자열) 반환.
     *  당김(get)은 없다 — 부팅 주입(app.py loaded→Theme.apply)이 유일한 읽기 경로. */
    setTheme(mode) { return window.pywebview.api.set_theme(mode); },

    /** 앱 글자 배율·셸 레이아웃 영속 — 모두 오리진 비의존 settings.json. */
    setFontScale(scale) { return window.pywebview.api.set_font_scale(scale); },
    setMasterWidth(width) { return window.pywebview.api.set_master_width(Math.round(width)); },

    /** 네이티브 X 닫기 확인의 처분 통보(#218 G1) — 확인 모달의 3택 결과를 호스트에 되돌린다.
     *  종전엔 앱 셸이 `pywebview.api` 를 직접 만졌다. 반환은 **그대로** 넘긴다(호출자가 await):
     *  여기서 삼키면 닫기 실패가 조용해지고, 그것이 곧 "닫힌 줄 알았는데 안 닫힘"이다. */
    confirmWindowClose() { return window.pywebview.api.confirm_window_close(); },
    cancelWindowClose() { return window.pywebview.api.cancel_window_close(); },
  };

  // Python→웹 푸시 진입점(app.py 의 evaluate_js 가 부르는 전역이 여기로 걸린다). 미구독 화면은
  // 조용히 무시(등록 전 push 는 버려진다 — 부팅은 initial 당김이 정본).
  function push(screen, snapshot) {
    for (const fn of renderers[screen] || []) fn(snapshot);
  }

  /* 시험 전용 호스트 통로(N-09) — **공개 브리지 표면이 아니다**.
     `bridge` 에 얹지 않는 것이 요점이다: 얹는 순간 화면·서비스가 이 통로를 부를 수 있게 되고,
     그러면 "시험 훅은 제품에서 도달 불가" 라는 계약이 표면 하나 차이로 무너진다. 그래서
     factory 의 **별도 반환값**으로 나가고, 받는 쪽은 중앙 selftest 부트 하나뿐이다.

     여기 두는 이유는 `pywebview.api` 판독을 이 파일 하나에 가두는 규율을 지키기 위해서다
     (파일 머리말). 정상 실행에서는 아래 두 메서드가 **호스트에 존재하지 않으므로**
     `available()` 이 거짓이고 부트는 아무것도 설치하지 않는다 — 활성화 조건은 오직
     "호스트가 이 프로세스를 시험용으로 띄웠는가" 다. */
  const testHost = {
    /** 호스트가 시험 능력을 대는가 — 정상 실행에선 거짓이다(메서드 자체가 없다). */
    available() {
      return !!(window.pywebview && window.pywebview.api
        && typeof window.pywebview.api.selftest_claim === "function");
    },
    /** 일회용 토큰 클레임. 두 번째 호출은 호스트가 거절한다. */
    claim(version) { return window.pywebview.api.selftest_claim(version); },
    /** 문서 밖 연산 요청(HOST_OPS). op·payload 검증은 **호스트가** 진다. */
    request(op, payload) {
      return window.pywebview.api.selftest_host_op(op, payload === undefined ? null : payload);
    },
  };

  return { bridge, push, testHost };
}
