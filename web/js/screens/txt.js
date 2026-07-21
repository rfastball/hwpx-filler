/* 기안문 채우기(txt) 화면 — 세션 표면은 공용 팩토리(draftsession.js)가 소유한다.

   첫 실화면(스파이크 승격)이라 오래 이 파일이 세션 렌더 전부를 들고 있었다. #148 슬라이스 3a
   에서 「기안」 화면이 같은 세션을 열게 되며 팩토리로 끌어올렸다 — 두 표면이 갈라질 자리를
   없앤다(백엔드 draft_session.py 와 짝). 이 파일에 남는 것은 **화면 고유 id 맵**과 부팅뿐이다.

   수명: 슬라이스 6(구 화면 사망)에서 이 화면과 함께 사라진다. */
(function () {
  const SCREEN = "txt";

  const sess = window.DraftSession.create({
    screen: SCREEN,
    rowIdPrefix: "txtRow-",  // preserve.js 가 id 로 포커스 복원 — 화면 간 전역 유일
    ids: {
      status: "txtStatus", tplSel: "tplSel", dataLabel: "txtDataLabel",
      pickBtn: "btnPick", poolBtn: "btnTxtPoolData", pasteBtn: "btnPaste",
      zoneNote: "txtZoneNote", note: "txtNote", tokPanel: "tokPanel",
      // 데이터 존(datazone.js 인스턴스)
      selCount: "txtSelCount", search: "txtFilterSearch", reapply: "txtFilterReapply",
      chips: "txtFilterChips", strip: "txtSelStrip",
      tableHost: "txtTableHost", tableWrap: "txtTableWrap", tableEmpty: "txtTableEmpty",
      tableHead: "txtTableHead", tableBody: "txtTableBody", colPanel: "txtColPanel",
      selAll: "txtSelAll", selNone: "txtSelNone",
      // 작업점 카드
      card: "txtCard", cardReadout: "txtCardReadout", cardDots: "txtCardDots",
      cardTitle: "txtCardTitle", cardRender: "txtCardRender", cardLint: "txtCardLint",
      lintAction: "txtLintAction", cardPrev: "txtCardPrev", cardNext: "txtCardNext",
      cardCopy: "txtCardCopy", cardDefer: "txtCardDefer", advance: "txtAdvance",
      targetFont: "txtTargetFont",
    },
  });

  /* 화면 부팅 — 라우터(app.js)가 pywebviewready 후 호출. */
  async function init() {
    Bridge.onPush(SCREEN, sess.render);
    sess.wire();
    const initState = await Bridge.initial(SCREEN);
    sess.fillTemplateSelect(initState);
    sess.render(initState);
  }

  // guardBody·copyGateBody 는 순수 합성기 — 실앱 게이트가 합성 결과(수치·문안 배치)를
  // 되읽는다(job 관례). confirmNewDraftIfArmed 는 홈의 「＋ 새 기안」이 소비(#126).
  window.TxtScreen = {
    init,
    refreshOnEnter: sess.refreshOnEnter,
    guardBody: sess.guardBody,
    copyGateBody: sess.copyGateBody,
    confirmNewDraftIfArmed: sess.confirmNewDraftIfArmed,
  };
})();
