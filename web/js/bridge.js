/* 브리지 클라이언트 — pywebview.api(=Python WebFrontend)와 왕복. 화면-불가지.
   웹→Python 은 dispatch/네이티브 메서드, Python→웹은 window.__push(screen, snapshot) 관측 푸시.
   화면 모듈은 Bridge.onPush(screen, fn) 로 렌더러를 등록한다 — 브리지는 화면 로직을 모른다. */
(function () {
  const renderers = {};   // screen id → fn(snapshot)

  const Bridge = {
    /** 화면 렌더러 등록 — Python 이 그 화면을 푸시하면 fn(snapshot) 이 불린다. */
    onPush(screen, fn) { renderers[screen] = fn; },

    /** 화면 초기 상태 당김(부팅 1회). */
    initial(screen) { return window.pywebview.api.initial(screen); },

    /** 순수 데이터 액션(창 불필요) — Python 이 처리 후 관측 푸시로 되민다. */
    call(screen, action, payload) {
      return window.pywebview.api.dispatch(screen, action, payload || {});
    },

    /** 네이티브 파일 다이얼로그 → 링1 VM 로드. 파일명·"ERROR:…"·null(취소), 또는
     *  다중 시트면 {needs_sheet, path, name, sheets:[…]} 로 시트 확정을 요구(#33). */
    pickDataFile(screen) { return window.pywebview.api.pick_data_file(screen); },

    /** 확정한 시트로 다중 시트 워크북 로드(#33). 파일명·"ERROR:…"·null. */
    loadDataSheet(screen, path, sheet) {
      return window.pywebview.api.load_data_sheet(screen, path, sheet);
    },

    /** 네이티브 열기 다이얼로그(HWPX 템플릿) → 스키마/게이트 로드. 파일명·"ERROR:…"·null. */
    pickTemplateFile(screen) { return window.pywebview.api.pick_template_file(screen); },

    /** 현재 렌더를 OS 클립보드로(완료=commit). 리포트(missing/empty) 반환. */
    copyClipboard(screen) { return window.pywebview.api.copy_clipboard(screen); },

    /** 네이티브 저장 다이얼로그 → 원자 쓰기. 결과 dict 또는 null(취소). */
    saveFile(screen) { return window.pywebview.api.save_file(screen); },

    /** 네이티브 폴더 피커(SHBrowseForFolder) → 저장 폴더 지정. 경로·"ERROR:…"·null(취소). */
    pickOutputFolder(screen) { return window.pywebview.api.pick_output_folder(screen); },

    /** 실행 화면 동기 생성 — 게이트/덮어쓰기 재진술·결과 요약 dict 반환. */
    generate(screen, confirmOverwrite) {
      return window.pywebview.api.generate(screen, !!confirmOverwrite);
    },

    /** 네이티브 폴더 피커 → 템플릿 관리 HWPX 라이브러리 폴더 재지정. 경로·"ERROR:…"·null. */
    pickLibraryFolder() { return window.pywebview.api.pick_library_folder(); },

    /** 템플릿 관리 '작업 만들기' → 그 템플릿을 에디터에 로드(크로스스크린). 파일명·"ERROR:…". */
    loadTemplateIntoEditor(path) { return window.pywebview.api.load_template_into_editor(path); },

    /** 에디터에 미저장 작업 세션이 있는가 — 크로스스크린 진입 전 폐기 확인 판단(#25). */
    editorHasUnsavedWork() { return window.pywebview.api.editor_has_unsaved_work(); },

    /** 홈 '편집' → 저장된 작업을 에디터 편집 세션으로 복원(#26). 이름·"ERROR:…". */
    openJobInEditor(name) { return window.pywebview.api.open_job_in_editor(name); },

    /** 홈 손상 카드 '폴더 열기' → 탐색기에서 파일 표시(#26 #8). null·"ERROR:…". */
    revealCorruptJob(path) { return window.pywebview.api.reveal_corrupt_job(path); },

    /** 데이터 관리 등록 모달 '찾아보기' → 경로만 반환(로드 없음, #26 #4). null=취소. */
    pickPoolDataFile() { return window.pywebview.api.pick_pool_data_file(); },

    /** 템플릿 다시 연결(#67) '찾아보기' → 경로만 반환(로드 없음). null=취소. */
    pickTemplatePath() { return window.pywebview.api.pick_template_path(); },

    /** 추적성 로케이트(#53-B) — 소유 경로 검증 후 열기/폴더보기/복사. null·"ERROR:…". */
    openPath(path) { return window.pywebview.api.open_path(path); },
    revealPath(path) { return window.pywebview.api.reveal_path(path); },
    copyPath(path) { return window.pywebview.api.copy_path(path); },

    /** 테마 선택 영속(오리진 비의존 Python 설정, #74). 확정값(문자열) 반환.
     *  당김(get)은 없다 — 부팅 주입(app.py loaded→Theme.apply)이 유일한 읽기 경로. */
    setTheme(mode) { return window.pywebview.api.set_theme(mode); },
  };

  // Python→웹 푸시 진입점(app.py 의 evaluate_js 가 호출). 전역 노출.
  window.__push = function (screen, snapshot) {
    const fn = renderers[screen];
    if (fn) fn(snapshot);
  };

  window.Bridge = Bridge;
})();
