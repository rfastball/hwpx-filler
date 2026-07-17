/* 템플릿 다시 연결 공용 흐름(#67, PR #70 리뷰) — pick → 1차 재진술 confirm → 확정 커밋.
   Python 단일 출처(screens.relink_job_template)의 JS 짝. run/home 에 흐름이 복붙돼
   오류 표면이 갈렸던 것(홈이 restated 를 버림)을 여기로 수렴하고, 결과 통지만
   화면별 콜백(notify)으로 주입한다 — PathTrack/Modal 공용 헬퍼 선례. */
(function () {
  /* notify(msg, kind) — kind: "ok"(커밋 재진술) | "cancel"(사용자 취소) | "error"(실패).
     실패는 공통 window.alert 로도 loud(콜백은 화면 채널 병기용). 미지정이면 no-op. */
  async function relinkTemplate(screen, name, notify) {
    const say = notify || function () {};
    try {
      const path = await Bridge.pickTemplatePath();
      if (!path) return;                            // 피커 취소 — 아무것도 안 바뀜
      let res = await Bridge.call(screen, "relink_template", { name, path });
      if (res && res.needs_confirm) {
        if (!window.confirm(res.confirm_text + "\n\n계속할까요?")) {
          say("다시 연결 취소 — 템플릿 연결을 바꾸지 않았습니다.", "cancel");
          return;
        }
        res = await Bridge.call(screen, "relink_template", { name, path, confirm: true });
      }
      if (res && res.ok === false) {
        window.alert(res.error);
        say("다시 연결 실패: " + res.error, "error");
        return;
      }
      if (res && res.restated) say(res.restated, "ok");
    } catch (err) {
      window.alert(String((err && err.message) || err));
    }
  }

  window.Relink = { relinkTemplate };
})();
