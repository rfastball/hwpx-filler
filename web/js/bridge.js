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

    /** 네이티브 파일 다이얼로그 → 링1 VM 로드. 파일명 또는 "ERROR:…" 또는 null(취소). */
    pickDataFile(screen) { return window.pywebview.api.pick_data_file(screen); },

    /** 현재 렌더를 OS 클립보드로(완료=commit). 리포트(missing/empty) 반환. */
    copyClipboard(screen) { return window.pywebview.api.copy_clipboard(screen); },

    /** 네이티브 저장 다이얼로그 → 원자 쓰기. 결과 dict 또는 null(취소). */
    saveFile(screen) { return window.pywebview.api.save_file(screen); },
  };

  // Python→웹 푸시 진입점(app.py 의 evaluate_js 가 호출). 전역 노출.
  window.__push = function (screen, snapshot) {
    const fn = renderers[screen];
    if (fn) fn(snapshot);
  };

  window.Bridge = Bridge;
})();
