/* 브리지 클라이언트 — pywebview.api(=Python WebFrontend)와 왕복. 화면-불가지.
   웹→Python 은 dispatch/네이티브 메서드, Python→웹은 window.__push(screen, snapshot) 관측 푸시.
   화면 모듈은 Bridge.onPush(screen, fn) 로 렌더러를 등록한다 — 브리지는 화면 로직을 모른다. */
(function () {
  // screen id → [fn, ...] — 한 채널 복수 구독(F8): 병존 기간 편집기가 tpl push 를 함께
  // 듣는다. 교체 의미의 재등록 소비자는 없다(전 화면이 자기 채널 1회 등록) — 덮어쓰기
  // 단일 슬롯이면 나중 등록이 먼저 등록을 조용히 밀어내 화면 하나가 렌더를 잃는다.
  const renderers = {};

  const Bridge = {
    /** 화면 렌더러 등록 — Python 이 그 화면을 푸시하면 등록 순서대로 fn(snapshot) 이 불린다. */
    onPush(screen, fn) { (renderers[screen] = renderers[screen] || []).push(fn); },

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

    /** 테마 선택 영속(오리진 비의존 Python 설정, #74). 확정값(문자열) 반환.
     *  당김(get)은 없다 — 부팅 주입(app.py loaded→Theme.apply)이 유일한 읽기 경로. */
    setTheme(mode) { return window.pywebview.api.set_theme(mode); },

    /** 앱 글자 배율·셸 레이아웃 영속 — 모두 오리진 비의존 settings.json. */
    setFontScale(scale) { return window.pywebview.api.set_font_scale(scale); },
    setMasterWidth(width) { return window.pywebview.api.set_master_width(Math.round(width)); },
  };

  // Python→웹 푸시 진입점(app.py 의 evaluate_js 가 호출). 전역 노출. 미구독 화면은 조용히
  // 무시(등록 전 push 는 버려진다 — 부팅은 initial 당김이 정본).
  window.__push = function (screen, snapshot) {
    for (const fn of renderers[screen] || []) fn(snapshot);
  };

  window.Bridge = Bridge;
})();
