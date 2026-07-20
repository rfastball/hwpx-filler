/* 빠른 기안 화면 — 작업의 휘발 쌍둥이(R-flow 블록 5, #90 슬라이스 7). 브리지로 링1
   QuickDraftViewModel 과 왕복. 렌더는 Python 이 window.__push('quickdraft', snapshot) 로
   밀어 넣는다(txt/job 관측 방향). 미리보기 재진술·토큰 폼은 표현 계층이라 여기서 만든다
   = 링2 대체, VM 로직 재구현 아님.

   PR-1(골격): 도달 가능한 빈손 화면만 세운다. 템플릿 소스·파이프라인 토큰 폼·미리보기(PR-2),
   데이터 이원·제스처 결속·표현형 3층(PR-3), 휘발도 가드·복사·표지(PR-4)는 뒤 PR 이 이
   render 와 #qdBody 를 확장한다. 없는 기능을 있는 척하지 않는다(confirm-or-alarm). */
(function () {
  const SCREEN = "quickdraft";
  const $ = (id) => document.getElementById(id);
  let LAST = null;
  let TEMPLATES = [];  // 슬롯 드롭다운용 라이브러리 이름(PR-2 가 소비) — initial 에서 채움

  /* Python→웹 푸시 렌더. Bridge.onPush 로 등록된다. 전체 스냅샷 재렌더가 포커스·캐럿·스크롤을
     뭉개지 않게 Preserve.around 로 감싼다(#28) — PR-2 이후 폼·미리보기가 이 안에서 재구성된다. */
  function render(s) {
    Preserve.around(() => {
      LAST = s;
      // 휘발 표지(상태 배지) — 빈 세션은 idle. 미채움/전량 채움 3상은 PR-2 이후 토큰 상태로 산다.
      const pill = $("qdStatus");
      if (pill && !s.template_text) {
        pill.dataset.level = "idle";
        pill.textContent = "세션 휘발 · 저장 없음";
      }
    });
  }

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, render);
    const initState = await Bridge.initial(SCREEN);
    TEMPLATES = initState.templates || [];
    render(initState);
  }

  window.QuickDraftScreen = { init };
})();
