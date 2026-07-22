/* 작업을 편집 모드에 여는 공용 흐름(#26/#67, PR #97 리뷰) — 미저장 정의 세션은 조용히 버리지
   않고 확인 후 연다(#25 미러). home.editJob 과 job.openEditForRepair(드리프트·파일명 토큰 수리)이 축자
   동일했던 것을 여기로 수렴한다(relink.js 공용 헬퍼 선례). newJob/makeJob 은 진입 후 동작이
   달라(new_session vs openJobInEditor) 별개다 — 이 헬퍼는 '기존 작업 열기' 한 형상만 담는다.
   에디터 흡수(결정 39~41): 목적지가 별도 화면에서 「작업」 패널의 편집 모드로 바뀌었다 —
   가드·로드 계약은 그대로, 마지막 착지만 Nav("job")+showEditMode 다. */
(function () {
  /* land() — 편집 모드 착지의 단일 정의(PR-2 리뷰: 축자 복붙은 착지 변경 시 드리프트 표면 —
     한 곳이 밀리면 실행 모드에 조용히 오착지한다). 소비처 = 신규 초안(newDraft — 홈 ＋·작업
     구획 ＋·template.makeJob 후속 착지)·기존 작업 열기(openGuarded)·미저장 초안 복귀(작업
     화면 T2 고지). JobScreen 미로드는 **loud**(PR-5 리뷰 F3: 백엔드 세션은 이미 초기화됐는데
     실행 모드에 조용히 떨어지면 사용자에게 설명 없는 무반응이 된다 — 조용한 오착지 금지). */
  function land() {
    window.Nav.go("job");
    if (window.JobScreen && window.JobScreen.showEditMode) window.JobScreen.showEditMode();
    else window.alert("편집 모드를 열 수 없습니다. 화면 구성 요소(JobScreen)가 로드되지 않았습니다.");
  }

  /* newDraft() — 「＋ 새 작업」의 단일 정의(PR-5 리뷰 F2: 홈·작업 구획 ＋ 가 같은 흐름을
     복붙하면 폐기 확인·착지가 드리프트한다): 폐기 확인 → 세션 초기화 → 편집 모드 착지. */
  async function newDraft() {
    if (!(await confirmDiscard(
      "새 작업을 시작하면 저장하지 않은 편집 세션이 사라집니다.\n" +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?"))) return false;
    await Bridge.call("editor", "new_session", {});
    land();
    return true;
  }

  /* 미저장 정의 세션 폐기 확인의 **단일 출처**(PR-4 리뷰 F9 — 3중 복붙 수렴): 판정은 브리지
     즉시 질의(stale LAST 금지), 문구만 호출측이 준다. 미저장 없으면 조용히 통과. */
  async function confirmDiscard(body) {
    if (!(await Bridge.editorHasUnsavedWork())) return true;
    return window.Modal.confirm({ body });
  }

  /* openGuarded(name) — 미저장 정의 확인 → 작업 로드 → 「작업」 편집 모드. 취소·손상 시 무이동.
     반환: 열었으면 true, 확인 취소·오류로 중단했으면 false(호출부 후속 판단용). */
  async function openGuarded(name) {
    if (!(await confirmDiscard(
      `'${name}' 편집을 열면 저장하지 않은 편집 세션이 사라집니다.\n` +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?"))) {
      return false;
    }
    const r = await Bridge.openJobInEditor(name);
    if (typeof r === "string" && r.startsWith("ERROR:")) {
      window.alert(r.slice(6).trim());   // 손상·템플릿 부재 → loud(조용한 무시 금지)
      return false;
    }
    land();
    return true;
  }

  window.EditorEntry = { openGuarded, land, confirmDiscard, newDraft };
})();
