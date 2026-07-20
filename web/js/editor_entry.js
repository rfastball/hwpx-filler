/* 작업을 편집 모드에 여는 공용 흐름(#26/#67, PR #97 리뷰) — 미저장 정의 세션은 조용히 버리지
   않고 확인 후 연다(#25 미러). home.editJob 과 job.fixMapping(드리프트 수리)이 축자
   동일했던 것을 여기로 수렴한다(relink.js 공용 헬퍼 선례). newJob/makeJob 은 진입 후 동작이
   달라(new_session vs openJobInEditor) 별개다 — 이 헬퍼는 '기존 작업 열기' 한 형상만 담는다.
   에디터 흡수(결정 39~41): 목적지가 별도 화면에서 「작업」 패널의 편집 모드로 바뀌었다 —
   가드·로드 계약은 그대로, 마지막 착지만 Nav("job")+showEditMode 다. */
(function () {
  /* openGuarded(name) — 미저장 정의 확인 → 작업 로드 → 「작업」 편집 모드. 취소·손상 시 무이동.
     반환: 열었으면 true, 확인 취소·오류로 중단했으면 false(호출부 후속 판단용). */
  async function openGuarded(name) {
    const busy = await Bridge.editorHasUnsavedWork();
    if (busy && !(await window.Modal.confirm({ body:
      "저장하지 않은 편집(정의) 세션이 있습니다.\n" +
      `'${name}' 편집을 열면 그 세션의 이름·데이터·매핑이 사라집니다.\n\n계속할까요?` }))) {
      return false;
    }
    const r = await Bridge.openJobInEditor(name);
    if (typeof r === "string" && r.startsWith("ERROR:")) {
      window.alert(r.slice(6).trim());   // 손상·템플릿 부재 → loud(조용한 무시 금지)
      return false;
    }
    window.Nav.go("job");
    if (window.JobScreen && window.JobScreen.showEditMode) window.JobScreen.showEditMode();
    return true;
  }

  window.EditorEntry = { openGuarded };
})();
