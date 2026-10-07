/* 작업대 본문 편집면 되읽기(#1148 PR B) — `editor_workbench_data.js` 의 workbench 프로브가 부른다.
 *
 * 그 클러스터 모듈은 프로브 정의만 들고, 편집면 하나를 재는 잔 단계는 여기 둔다(응집 단위 분리).
 * 이 모듈은 **비활성**이다: import 만으로는 DOM 을 만지지 않는다 — 전부 호출 시점에 일어난다. */

function textOf(el) {
  return el ? String(el.textContent) : "";
}

/** 글자 넣기는 편집면의 붙여넣기 경로로 한다 — 편집면이 제 선택 자리에 트랜잭션으로 넣는다. 네이티브
 *  `insertText` 는 창이 OS 초점을 쥐지 않으면 편집면이 쓰지 않은 DOM 선택에 꽂혀 표지 글자까지 문서로 읽힌다. */
function pasteInto(ctx, el, text) {
  const transfer = new ctx.win.DataTransfer();
  transfer.setData("text/plain", text);
  el.dispatchEvent(new ctx.win.ClipboardEvent("paste", { clipboardData: transfer, bubbles: true, cancelable: true }));
}

/** 본문 표식이 Python 표식대로 갈려 섰는가 — 값 칠·〈빈 값〉·〈비워 둠〉·편집 가능·토큰 신원. */
export function readWorkbenchCard(ctx) {
  const card = (selector) => ctx.doc.querySelector(`#wbCard ${selector}`);
  return {
    card_fill: ctx.doc.querySelectorAll("#wbCard .seg-fill").length,
    card_blank: ctx.doc.querySelectorAll("#wbCard .seg-blank").length,
    card_declared: textOf(card('.seg-declared[data-token="단위"]')),
    card_blank_label: textOf(card('.seg-blank[data-token="비고"]')),
    card_editable: (card(".cm-content") || {}).contentEditable,
    card_tokens: ctx.doc.querySelectorAll("#wbCard [data-token]").length,
    token_role: card('[data-token="수신"]').getAttribute("role"),
  };
}

/** 작업대 본문 편집 되읽기 — 비고의 〈빈 값〉 자리에 캐럿을 두고 글자를 친다(합성 입력·합성 조합 사건).
 *  실 IME 의 조합 창은 흉내 내지 못한다: 재는 것은 조합 사건 사이의 발신 보류와 조합 뒤 한 번 발신이다. */
export async function probeCardEdit(ctx, stubBridgeCall) {
  const doc = ctx.doc;
  const sent = [];
  const stub = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
    if (screen === "workbench") { sent.push([action, payload]); return Promise.resolve({}); }
    return real(screen, action, payload);
  });
  const res = {};
  try {
    const content = doc.querySelector("#wbCard .cm-content");
    const hole = doc.querySelector('#wbCard .seg-blank[data-token="비고"]');
    /* 캐럿은 **편집면의 누르기 경로**로 둔다 — 표지 왼쪽 끝을 누르면 편집면이 그 자리를 선택으로
       세운다. DOM 선택을 직접 바꾸는 길은 창이 OS 초점을 쥐지 않았을 때 편집면이 읽지 않는다
       (사용자 데스크톱의 초점을 빼앗지 않고 잰다). */
    content.focus();
    const box = hole.getBoundingClientRect();
    const at = { bubbles: true, cancelable: true, button: 0, buttons: 1, detail: 1, view: ctx.win,
      clientX: box.left + 1, clientY: box.top + box.height / 2 };
    hole.dispatchEvent(new ctx.win.MouseEvent("mousedown", at));
    ctx.win.dispatchEvent(new ctx.win.MouseEvent("mouseup", { ...at, buttons: 0 }));
    await ctx.sleep(80);
    pasteInto(ctx, content, "없음");
    await ctx.sleep(30);
    res.hole_gone = !doc.querySelector('#wbCard .seg-blank[data-token="비고"]');
    res.filled_marks = doc.querySelectorAll("#wbCard .seg-fill").length;
    res.sent_before_pause = sent.length;
    await ctx.sleep(400);
    res.sent_after_pause = sent.map((row) => row[0] + ":" + JSON.stringify(row[1]));
    const compose = (type, data) => content.dispatchEvent(
      new ctx.win.CompositionEvent(type, { bubbles: true, data }));
    compose("compositionstart", "");
    pasteInto(ctx, content, "함");
    await ctx.sleep(400);
    res.sent_while_composing = sent.length;
    compose("compositionend", "함");
    await ctx.sleep(400);
    res.sent_after_compose = sent.length > 0 ? JSON.stringify(sent[sent.length - 1][1]) : "";
    res.focus_kept = content.contains(doc.activeElement) || doc.activeElement === content;
  } finally {
    stub.restore();
  }
  return res;
}

/** 빈 값·미채움 표식은 남겨 두되 복사는 확인 없이 사전검사 토큰을 클립보드 거래로 넘긴다. */
export async function probeCardCopyWithHoles(ctx, { stubBridgeCall, stubBridgeInvoke, settleUntil }) {
  const calls = [];
  const dispatch = stubBridgeCall(ctx, (real) => function (screen, action, payload) {
    if (screen === "workbench" && action === "copy_precheck") {
      calls.push([action, payload]);
      return Promise.resolve({ token: "copy-probe", missing_fields: ["수신"], empty_fields: ["비고"] });
    }
    return real(screen, action, payload);
  });
  const invoke = stubBridgeInvoke(ctx, "copyClipboard", "copy_clipboard", () => function (screen, token) {
    calls.push(["copy_clipboard", screen, token]);
    return Promise.resolve({ copied: true });
  });
  try {
    ctx.doc.getElementById("wbCopy").click();
    await settleUntil(ctx, () => calls.length === 2);
    return {
      calls,
      confirmation_open: !ctx.doc.getElementById("confirmModal").classList.contains("hidden"),
      blank_marker: ctx.doc.querySelectorAll("#wbCard .seg-blank").length,
    };
  } finally {
    invoke.restore();
    dispatch.restore();
  }
}
