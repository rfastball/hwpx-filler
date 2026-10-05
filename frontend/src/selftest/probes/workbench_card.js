/* 작업대 본문 편집면 되읽기(#1148 PR B) — `editor_workbench_data.js` 의 workbench 프로브가 부른다.
 *
 * 그 클러스터 모듈은 프로브 정의만 들고, 편집면 하나를 재는 잔 단계는 여기 둔다(응집 단위 분리).
 * 이 모듈은 **비활성**이다: import 만으로는 DOM 을 만지지 않는다 — 전부 호출 시점에 일어난다. */

function textOf(el) {
  return el ? String(el.textContent) : "";
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
    const line = hole && hole.closest(".cm-line");
    const text = line && Array.prototype.find.call(line.childNodes, (node) => node.nodeType === 3);
    content.focus();
    const range = doc.createRange();
    range.setStart(text, text.length);
    range.collapse(true);
    const picked = doc.getSelection();
    picked.removeAllRanges();
    picked.addRange(range);
    await ctx.sleep(30);
    doc.execCommand("insertText", false, "없음");
    await ctx.sleep(30);
    res.hole_gone = !doc.querySelector('#wbCard .seg-blank[data-token="비고"]');
    res.filled_marks = doc.querySelectorAll("#wbCard .seg-fill").length;
    res.sent_before_pause = sent.length;
    await ctx.sleep(400);
    res.sent_after_pause = sent.map((row) => row[0] + ":" + JSON.stringify(row[1]));
    const compose = (type, data) => content.dispatchEvent(
      new ctx.win.CompositionEvent(type, { bubbles: true, data }));
    compose("compositionstart", "");
    doc.execCommand("insertText", false, "함");
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
