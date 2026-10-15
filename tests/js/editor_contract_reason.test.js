/* 데이터 계약 미통과 사유(#1188 WP-02) — 판정·문장은 Python 이 내고 웹은 그대로 그리기만 한다. */
import test from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";

import { contractReason } from "../../frontend/src/screens/editor.ts";

test("계약 사유는 Python 문장 그대로 그 행 index 로 선다", () => {
  const markup = renderToStaticMarkup(
    contractReason({ contract_reason: "날짜로 읽히지 않는 값 2행" }, 3),
  );
  assert.ok(markup.includes('data-act="row-contract-reason"'));
  assert.ok(markup.includes('data-index="3"'));
  assert.ok(markup.includes(">날짜로 읽히지 않는 값 2행<"));
});

test("사유가 빈 행(일반 작업·통과 행)에는 아무것도 서지 않는다", () => {
  assert.equal(contractReason({ contract_reason: "" }, 0), null);
  assert.equal(contractReason({}, 0), null);
});
