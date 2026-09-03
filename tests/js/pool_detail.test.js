/* 등록 데이터 상세 시트 + 공용 시트 골격(고르기 열 공용 ④).
 *
 * 두 층을 잰다:
 *
 * 1. `DetailSheetFrame` — **좌표 계약**이다. 두 접두어(`tplDetail`·`poolDetail`)가 같은
 *    여덟 자리를 내는지 본다. 골격이 하나인 것의 관측 가능한 얼굴이 이것이라, 한쪽만
 *    좌표를 잃으면 그 시트를 든 게이트(selftest 프로브)가 그때야 빨강이 된다.
 * 2. `PoolDetailSheet` — 스냅샷의 `detail` 존 하나를 그대로 그리는가. **문안은 재지 않고
 *    옮겨졌는지만 잰다**: 정체 줄 성분도 열 표 머리도 링1(`DatasetDetail`)이 짓는다.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { DetailSheetFrame } from "../../frontend/src/screens/detail_sheet.ts";
import { PoolDetailSheet } from "../../frontend/src/screens/pool_detail.ts";

const NOOP_CLIENT = { async invoke() { return { ok: true, value: null }; } };

function detailFixture(overrides) {
  return Object.assign({
    key: "k1", name: "7월 공고목록", kind: "excel", kind_label: "엑셀/CSV", status: "active",
    badge_label: "활성", badge_level: "ok", path: "C:/d/7월.xlsx", sheet: "물품",
    sheet_title: "물품", header_row: 2, note: "분기 집계",
    facts: ["종류 엑셀/CSV", "시트: 물품", "헤더 2행", "메모: 분기 집계"],
    column_count: 3, column_summary: "열 3개", columns: ["공고명", "금액", "기관"],
    actions: [{ key: "relink", label: "다시 연결…" }, { key: "archive", label: "보관" }],
    error: "",
  }, overrides || {});
}

/** `pool` 채널 모델과 컨트롤러 상태를 든 최소 컨트롤러 대역. */
function controllerFor(pool, view) {
  const calls = [];
  const still = () => () => {};
  return {
    calls,
    controller: {
      poolModel: { getSnapshot: () => pool, subscribe: still },
      model: { getSnapshot: () => Object.assign({ detailMessage: "" }, view || {}), subscribe: still },
      client: NOOP_CLIENT,
      notify: (message) => calls.push(["notify", message]),
      closeDetail: () => calls.push(["close"]),
      handleDetailVerb: (action) => { calls.push(["verb", action]); },
    },
  };
}

function renderSheet(pool, view) {
  const { controller } = controllerFor(pool, view);
  return renderToStaticMarkup(createElement(PoolDetailSheet, { controller }));
}

/* ---------------- ① 공용 골격의 좌표 계약 ---------------- */

test("DetailSheetFrame — 두 접두어가 같은 여덟 자리를 낸다(골격이 하나인 것의 얼굴)", () => {
  for (const prefix of ["tplDetail", "poolDetail"]) {
    const markup = renderToStaticMarkup(createElement(DetailSheetFrame, {
      idPrefix: prefix, title: "이름", pill: { label: "활성", level: "ok" },
      path: "C:/d/a.xlsx", client: NOOP_CLIENT, notify: () => {},
      error: "못 읽었습니다", diagnostics: ["진단 하나"],
      message: "동사가 실패했습니다", result: { text: "성과", level: "ok" },
      body: createElement("p", { id: `${prefix}Body` }, "몸통"),
      verbs: [{ action: "act:archive", label: "보관" }],
      onVerb: () => {}, onClose: () => {},
    }));
    for (const slot of ["Title", "Path", "Error", "Msg", "Result", "Verbs", "Close"]) {
      assert.ok(markup.includes(`id="${prefix}${slot}"`), `${prefix}${slot} 좌표가 없습니다`);
    }
    assert.ok(markup.includes("modal-card detail-sheet"), "골격 클래스가 서지 않았습니다");
    assert.ok(markup.includes("진단 하나") && markup.includes("몸통"));
    /* 동사 버튼의 `data-act` 는 「detail-」 접두 그대로다(게이트가 이 좌표를 든다). */
    assert.ok(markup.includes('data-act="detail-act:archive"'), markup);
  }
});

test("DetailSheetFrame — 빈 면은 안내 하나이고 동사 줄이 서지 않는다", () => {
  const markup = renderToStaticMarkup(createElement(DetailSheetFrame, {
    idPrefix: "poolDetail", title: "데이터 상세", client: NOOP_CLIENT, notify: () => {},
    empty: "볼 항목이 없습니다.", onClose: () => {},
    verbs: [{ action: "act:archive", label: "보관" }],
  }));
  assert.ok(markup.includes('id="poolDetailEmpty"'), markup);
  assert.ok(markup.includes('id="poolDetailClose"'), "빈 면에도 닫기는 선다");
  assert.equal(markup.includes('id="poolDetailVerbs"'), false,
    "겨눌 항목이 없는데 동사 줄이 섰습니다");
});

/* ---------------- ② 등록 데이터 상세 ---------------- */

test("PoolDetailSheet — 열 표·정체 줄·표 머리는 스냅샷 값 그대로다", () => {
  const markup = renderSheet({ detail: detailFixture(), result: { text: "", level: "muted" } });

  assert.ok(markup.includes('id="poolDetailColumns"'), "열 표 좌표가 없습니다");
  /* 행 수는 열 수와 같다 — 표면이 열을 접거나 늘리지 않는다. */
  assert.equal((markup.match(/<tr><td><span class="fname">/g) || []).length, 3, markup);
  for (const name of ["공고명", "금액", "기관"]) assert.ok(markup.includes(name), name);
  /* 정체 줄 성분은 링1 이 짓고 웹은 잇기만 한다(어휘·순서를 여기서 재조립하지 않는다). */
  assert.ok(markup.includes("종류 엑셀/CSV · 시트: 물품 · 헤더 2행 · 메모: 분기 집계"), markup);
  assert.ok(markup.includes('id="poolDetailColumnSummary"') && markup.includes("열 3개"));
  assert.ok(markup.includes("7월 공고목록") && markup.includes("활성"));
  assert.ok(markup.includes("C:/d/7월.xlsx"), "경로 줄이 없습니다");
});

test("PoolDetailSheet — 동사 줄은 링1 동사 + 경로 문이고 「자세히…」 자신은 걷힌다", () => {
  const markup = renderSheet({ detail: detailFixture(), result: {} });
  for (const act of ["detail-act:relink", "detail-act:archive", "detail-reveal"]) {
    assert.ok(markup.includes(`data-act="${act}"`), `${act} 가 없습니다`);
  }
  assert.equal(markup.includes('data-act="detail-detail"'), false,
    "지금 서 있는 「자세히…」가 그 시트 안에 또 섰습니다");
});

test("PoolDetailSheet — 읽기 실패는 숨기지 않고 사유 상자로 선다(열 표는 서지 않는다)", () => {
  const markup = renderSheet({
    detail: detailFixture({
      columns: [], column_count: 0, column_summary: "열 목록을 읽지 못했습니다",
      error: "파일을 찾을 수 없습니다: C:/d/7월.xlsx",
    }),
    result: {},
  });
  assert.ok(markup.includes('id="poolDetailError"'), markup);
  assert.ok(markup.includes("파일을 찾을 수 없습니다"), markup);
  assert.ok(markup.includes("열 목록을 읽지 못했습니다"), "표 머리가 사유를 재진술하지 않습니다");
  assert.equal(markup.includes('id="poolDetailColumns"'), false, "빈 열 표가 섰습니다");
  /* 못 읽은 항목에서도 「다시 연결」에 닿는 문은 서 있어야 한다(막다른 경보 금지). */
  assert.ok(markup.includes('data-act="detail-act:relink"'), markup);
});

test("PoolDetailSheet — 상세가 없으면 빈 면 안내가 선다", () => {
  const markup = renderSheet({ detail: null, result: {} });
  assert.ok(markup.includes('id="poolDetailEmpty"'), markup);
  assert.ok(markup.includes("자세히…"), "빈 면 안내가 여는 길을 말하지 않습니다");
});

test("PoolDetailSheet — 성과·실패 두 줄은 각자 채널로 선다", () => {
  const markup = renderSheet(
    { detail: detailFixture(), result: { text: "데이터셋을 보관했습니다", level: "ok" } },
    { detailMessage: "VERB_REFUSAL" });
  assert.ok(markup.includes('id="poolDetailResult"') && markup.includes("데이터셋을 보관했습니다"));
  assert.ok(markup.includes('id="poolDetailMsg"') && markup.includes("VERB_REFUSAL"));
});
