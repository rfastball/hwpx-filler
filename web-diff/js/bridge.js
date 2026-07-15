/* 브리지 클라이언트 — pywebview.api(=Python WebFrontend)와 왕복. 화면-불가지.
   filler web/js/bridge.js 의 diff 판. 웹→Python 은 dispatch/네이티브 메서드, Python→웹은
   window.__push(screen, snapshot) 관측 푸시. 화면 모듈은 Bridge.onPush(screen, fn) 로 등록. */
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

    /** 네이티브 열기 다이얼로그(구판 HWPX) → 경로 로드. 파일명·"ERROR:…"·null(취소). */
    pickOld(screen) { return window.pywebview.api.pick_old_file(screen); },

    /** 네이티브 열기 다이얼로그(신판 HWPX) → 경로 로드. 파일명·"ERROR:…"·null(취소). */
    pickNew(screen) { return window.pywebview.api.pick_new_file(screen); },

    /** 비동기 비교 시작 — 워커 스레드 + push(완료 시 결과). 즉시 {ok,status} 반환. */
    compare(screen) { return window.pywebview.api.compare(screen); },
  };

  // Python→웹 푸시 진입점(app.py 의 evaluate_js 가 호출). 전역 노출.
  window.__push = function (screen, snapshot) {
    const fn = renderers[screen];
    if (fn) fn(snapshot);
  };

  window.Bridge = Bridge;
})();
