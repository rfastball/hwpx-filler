/* 작업을 편집 모드에 여는 공용 흐름(#26/#67, PR #97 리뷰) — 미저장 정의 세션은 조용히 버리지
   않고 확인 후 연다(#25 미러). home.editJob 과 job.openEditForRepair(드리프트·파일명 토큰 수리)이 축자
   동일했던 것을 여기로 수렴한다(relink.js 공용 헬퍼 선례). newJob/makeJob 은 진입 후 동작이
   달라(new_session vs openJobInEditor) 별개다 — 이 헬퍼는 '기존 작업 열기' 한 형상만 담는다.
   재작성 F7: 목적지가 다시 **자기 화면**(#scr-editor 몰입 표면)이 됐다 — 가드·로드 계약은
   그대로이고 마지막 착지만 Nav("editor") 다. 진입 문맥(사유·증거·복귀처)은 여기서 백엔드로
   함께 넘어간다: 편집기는 스스로 열리지 않으므로(늘 다른 표면의 문제가 사람을 보낸다)
   문맥 없는 진입은 왜 왔는지도 어디로 돌아갈지도 없는 표면이 된다(계약 §5.1). */
(function () {
  /* land() — 편집기 착지의 단일 정의(PR-2 리뷰: 축자 복붙은 착지 변경 시 드리프트 표면 —
     한 곳이 밀리면 엉뚱한 화면에 조용히 오착지한다). 소비처 = 신규 초안(newDraft — 「문서
     작업」 ＋·template.makeJob 후속 착지)·기존 작업 열기(openGuarded).
     `force` 인 이유: 진입은 **이미 확인을 마친 뒤**라 편집기 이탈 가드를 다시 태울 것이
     없다(그 가드는 나가는 길의 것이다). */
  /* 편집기를 **띄운 자리** 1슬롯(9R P2) — 이탈이 초점을 여기로 되돌린다.

     왜 진입 seam 이 기억하는가: 복귀처마다 `focus_target` 을 실어 보내면 표면이 넷이라 넷
     모두 고쳐야 하고, 새 진입처가 생기면 조용히 빠진다(F7 이 복귀 봉합에서 겪은 그 형태 —
     지도 §10.13.14). 편집기로 들어오는 문은 이 파일 하나이므로, 여기서 한 번 기억하면
     모든 이탈이 공짜로 따라온다. 요소 참조로 두는 이유는 재렌더로 사라졌을 때의 대안이
     이미 `Modal.restoreFocus` 에 있기 때문이다(판정을 흉내내지 않고 결과를 읽는다). */
  let entryFocus = null;

  function rememberEntryFocus() {
    entryFocus = document.activeElement;
  }

  /* 이탈이 부르는 초점 되돌림 — 모달의 되돌림과 **같은 규칙**을 쓴다(재발명 금지). */
  function restoreEntryFocus() {
    const target = entryFocus;
    entryFocus = null;      // 1슬롯 — 다음 진입이 다시 채운다(옛 자리로 두 번 되돌리지 않는다)
    window.Modal.restoreFocus(target);
  }

  function land() {
    window.Nav.go("editor", { force: true });
  }

  /* newDraft() — 「＋ 새 작업」의 단일 정의(PR-5 리뷰 F2: 「문서 작업」·작업 구획 ＋ 가 같은 흐름을
     복붙하면 폐기 확인·착지가 드리프트한다): 폐기 확인 → 세션 초기화 → 편집 모드 착지. */
  async function newDraft() {
    rememberEntryFocus();   // 확인 모달 앞에서 — 모달은 자기 되돌림으로 이 자리를 복원한다
    if (!(await confirmDiscard(
      "새 작업을 시작하면 저장하지 않은 편집 세션이 사라집니다.\n" +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?"))) return false;
    await Bridge.call("editor", "new_session", {});
    land();
    return true;
  }

  /* newDraftFromData(context) — 「이 데이터로 새 작업」의 단일 정의(U2 §2.4·§4 판정 E, #349).
     `newDraft` 와 갈라 두는 이유는 이 파일 머리가 적은 그대로다: **진입 후 동작이 다르면**
     별개 흐름이다(여기는 마운트 데이터 앵커 + 진입 문맥을 든다). 같은 것 — 폐기 확인 문안과
     착지 — 은 계속 공용을 부른다.

     확인은 **하나뿐이고 조건부**다: 편집기에 미저장 세션이 있을 때만 뜬다(`confirmDiscard`).
     이 동선이 예전에 열리지 않았던 이유였던 「저장 시 데이터 자동등록 확인」은 #347 이
     없앴으므로, 여기서 새로 물을 것을 만들지 않는다. */
  async function newDraftFromData(context) {
    rememberEntryFocus();
    if (!(await confirmDiscard(
      "이 데이터로 새 작업을 시작하면 저장하지 않은 편집 세션이 사라집니다.\n" +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?"))) return false;
    const r = await Bridge.newJobFromData(context || {});
    if (typeof r === "string" && r.startsWith("ERROR:")) {
      window.alert(r.slice(6).trim());   // 데이터 부재·재적재 실패 → loud(조용한 무이동 금지)
      return false;
    }
    land();
    return true;
  }

  /* 미저장 정의 세션 폐기 확인의 **단일 출처**(PR-4 리뷰 F9 — 3중 복붙 수렴): 판정은 브리지
     즉시 질의(stale LAST 금지), 문구만 호출측이 준다. 미저장 없으면 조용히 통과. */
  async function confirmDiscard(body, returnFocus) {
    if (!(await Bridge.editorHasUnsavedWork())) return true;
    return window.Modal.confirm({
      body, returnFocus, confirmLabel: "버리고 계속", cancelLabel: "취소",
    });
  }

  /* openGuarded(name, context) — 미저장 정의 확인 → 작업 로드 → 편집기 화면. 취소·손상 시 무이동.
     반환: 열었으면 true, 확인 취소·오류로 중단했으면 false(호출부 후속 판단용).

     `context` = {entry_reason, evidence, return_context, section}(계약 §5.1) — **보낸 표면**이
     자기가 본 것을 싣는다. 이 seam 이 인자를 흘리면 모든 진입이 기본 자발적 진입으로 떨어져
     배너·복귀처가 통째로 사라진다(1R P1: 실제로 그렇게 빠뜨렸다 — 단일 정의는 인자까지
     단일이어야 한다). */
  async function openGuarded(name, context) {
    rememberEntryFocus();
    if (!(await confirmDiscard(
      `'${name}' 편집을 열면 저장하지 않은 편집 세션이 사라집니다.\n` +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?"))) {
      return false;
    }
    const r = await Bridge.openJobInEditor(name, context || {});
    if (typeof r === "string" && r.startsWith("ERROR:")) {
      window.alert(r.slice(6).trim());   // 손상·템플릿 부재 → loud(조용한 무시 금지)
      return false;
    }
    land();
    return true;
  }

  window.EditorEntry = {
    openGuarded, land, confirmDiscard, newDraft, newDraftFromData, restoreEntryFocus,
  };
})();
