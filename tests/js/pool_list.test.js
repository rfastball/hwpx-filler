/* 등록 데이터 풀의 **공유 몸통**(U6-B #976) — 두 호스트가 같은 DOM 을 내는가.
 *
 * 이 파일이 재는 것은 셋이다: ①두 포트가 같은 노드를 내고 갈리는 것은 라벨·발행·id 접두
 * 셋뿐인가 ②판정이 하나도 여기 없는가(`selectable`·`select_block_reason` 을 그대로 든다)
 * ③끌어 놓기가 형식·상대 열 규칙·비활성 거절을 지키는가.
 *
 * 종전에는 같은 상태를 두 표면이 다르게 그렸다(다이얼로그의 웹 `usableReason` ↔ 편집기
 * 축약판의 Python `pool_option_block`). 그 축약판이 사슬째 퇴역한 자리라, 여기서 갈라짐이
 * 다시 생기면 그때 빨강이어야 한다. */
import test from "node:test";
import assert from "node:assert/strict";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { PoolSections, dragProps } from "../../frontend/src/screens/pool_list.ts";

const ROW = {
  key: "k1", name: "7월 공고목록", kind: "excel", kind_label: "엑셀/CSV", status: "active",
  badge_label: "활성", badge_level: "ok", reference: "C:/d/7월.xlsx (물품)",
  locate_path: "C:/d/7월.xlsx", sheet: "물품", missing: false, note: "",
  actions: [{ key: "archive", label: "보관" }],
  selectable: true, select_block_reason: "",
};

const BROKEN = Object.assign({}, ROW, {
  key: "k2", name: "지난목록", missing: true,
  selectable: false, select_block_reason: "참조가 끊겼습니다. '다시 연결' 뒤에 쓸 수 있습니다.",
});

const POOL = {
  rows: [ROW, BROKEN], duplicates: [], corrupted: [],
  pclm: { default_db: "C:/d/pclm.db", views: [], titles: {} },
};

function host(overrides) {
  return Object.assign({
    idPrefix: "dataPicker",
    chooseLabel: "이 데이터 사용",
    onChoose() {},
    current: {},
    currentKey: "",
    openPin() {},
    browse() {},
    openPclm() {},
    poolAction() {},
    resolveDuplicate() {},
    client: {},
    notify() {},
  }, overrides || {});
}

const render = (h, pool = POOL) => renderToStaticMarkup(
  createElement(PoolSections, { host: h, pool }));

test("두 호스트가 같은 몸통을 낸다 — 갈리는 것은 라벨·id 접두 둘뿐", () => {
  const dialog = render(host());
  const editor = render(host({ idPrefix: "editorPool", chooseLabel: "이 데이터로" }));

  /* 접두를 되돌리고 라벨을 맞추면 **한 글자도 다르지 않아야** 한다 — 다르면 두 표면이
     같은 상태를 다르게 그리기 시작한 것이다. */
  const normalized = editor
    .replaceAll("editorPool", "dataPicker")
    .replaceAll("이 데이터로", "이 데이터 사용");
  assert.equal(normalized, dialog);

  /* 다이얼로그의 좌표는 **불변**이다 — 이 id 를 겨눈 게이트가 이미 있다. */
  for (const id of ["dataPickerCurrent", "dataPickerPinned", "dataPickerDupes",
    "dataPickerCorrupt", "dataPickerBrowse", "dataPickerPclm"]) {
    assert.ok(dialog.includes(`id="${id}"`), `${id} 좌표가 사라졌습니다`);
  }
});

test("1차 동사는 호스트가 준 라벨을 쓰고 그 행을 그대로 되돌린다", () => {
  const chosen = [];
  const h = host({ chooseLabel: "이 데이터로", onChoose: (row) => chosen.push(row.key) });
  const markup = render(h);
  assert.ok(markup.includes("이 데이터로"), "호스트 라벨이 서지 않았습니다");
  assert.equal(markup.includes("이 데이터 사용"), false, "다른 호스트의 라벨이 새 나왔습니다");
  /* 발행 자체는 호스트의 일이라 여기서는 콜백 시그니처만 못박는다(행 전체를 준다 —
     키만 주면 호스트가 목록을 다시 뒤져야 하고, 그 조회가 두 번째 판정이 된다). */
  h.onChoose(ROW);
  assert.deepEqual(chosen, ["k1"]);
});

test("「쓸 수 있는가」는 스냅샷이 든다 — 표면은 status·missing 으로 다시 판정하지 않는다", () => {
  const markup = render(host());
  /* 끊긴 행은 **숨기지 않고** 비활성 + 사유다. 사유 문안은 Python 이 낸 것 그대로. */
  assert.ok(markup.includes("지난목록"), "끊긴 행이 목록에서 사라졌습니다");
  assert.ok(markup.includes("뒤에 쓸 수 있습니다"), "사유가 병기되지 않았습니다");
  assert.ok(markup.includes('aria-disabled="true"'), "끊긴 행이 비활성으로 서지 않았습니다");

  /* 양성 대조 — 같은 `status`·`missing` 인데 스냅샷이 「쓸 수 있다」고 하면 열린다.
     표면이 다시 판정하고 있으면 이 대조가 빨강이 된다. */
  const lenient = Object.assign({}, BROKEN, {
    selectable: true, select_block_reason: "",
  });
  const open = render(host(), Object.assign({}, POOL, { rows: [lenient] }));
  assert.equal(open.includes('aria-disabled="true"'), false,
    "스냅샷이 허용했는데 표면이 스스로 잠갔습니다(두 곳 판정).");
});

test("겨눈 항목은 aria-current 로 서고, 겨눔이 없으면 아무 행도 서지 않는다", () => {
  assert.equal(render(host()).includes('aria-current="true"'), false);
  const marked = render(host({ currentKey: "k1" }));
  assert.ok(marked.includes('aria-current="true"'));
  assert.equal(marked.split('aria-current="true"').length - 1, 1, "겨눔은 하나다");
});

/* ---------------- 끌어 놓기 — 클릭이 발행하는 같은 액션 두 번 ---------------- */

function fakeEvent(payload) {
  const classes = new Set();
  const transfer = {
    data: {}, types: payload === undefined ? [] : ["text/plain"],
    effectAllowed: "", dropEffect: "",
    setData(kind, value) { this.data[kind] = value; this.types = ["text/plain"]; },
    getData(kind) { return this.data[kind] ?? (payload || ""); },
  };
  return {
    prevented: false,
    preventDefault() { this.prevented = true; },
    dataTransfer: transfer,
    currentTarget: { classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      has: (name) => classes.has(name),
    } },
    classes,
  };
}

test("dragstart 는 `<side>:<key>` 한 형식만 싣는다", () => {
  const props = dragProps({ side: "dat", onDrop() {}, onRefuse() {} }, "k1", true, "");
  assert.equal(props["data-side"], "dat");
  assert.equal(props["data-key"], "k1");
  assert.equal(props.draggable, true);
  const event = fakeEvent();
  props.onDragStart(event);
  assert.equal(event.dataTransfer.getData("text/plain"), "dat:k1");
  assert.equal(event.dataTransfer.effectAllowed, "link");
});

test("고를 수 없는 항목은 끌 수도 놓을 수도 없고, 거절은 사유를 남긴다", () => {
  const refused = [];
  const dropped = [];
  const props = dragProps(
    { side: "dat", onDrop: (...args) => dropped.push(args), onRefuse: (...args) => refused.push(args) },
    "k2", false, "참조가 끊겼습니다.",
  );
  assert.equal(props.draggable, false, "끌 수 있으면 놓을 수 있다고 읽힙니다");

  /* **받되 거절한다**: 안 받으면 `drop` 이 안 와서 손을 놓은 사람에게 아무 말도 못 한다.
     강조는 성사할 자리에만 서므로 「놓을 수 있다」는 약속이 서지 않는다. */
  const over = fakeEvent("tpl:t1");
  props.onDragOver(over);
  assert.equal(over.prevented, true, "놓아도 아무 말이 없는 자리를 만들었습니다");
  /* "none" 이면 브라우저가 드롭을 취소해 `drop` 이 오지 않는다 — 사유를 낼 자리가
     사라지므로 "link" 를 둔다(강조 부재가 「성사하지 않는다」를 말한다). */
  assert.equal(over.dataTransfer.dropEffect, "link");
  assert.equal(over.classes.has("drop-target"), false, "성사하지 못할 자리를 강조했습니다");

  const drop = fakeEvent("tpl:t1");
  props.onDrop(drop);
  assert.deepEqual(dropped, [], "고를 수 없는 항목이 발신을 냈습니다");
  assert.deepEqual(refused, [["참조가 끊겼습니다.", "k2"]], "조용히 삼켰습니다");
});

test("같은 열끼리는 짝이 아니고, 상대 열의 드롭만 액션을 낸다", () => {
  const dropped = [];
  const refused = [];
  const props = dragProps(
    { side: "dat", onDrop: (...args) => dropped.push(args), onRefuse: (why) => refused.push(why) },
    "k1", true, "",
  );

  const same = fakeEvent("dat:k9");
  props.onDrop(same);
  assert.deepEqual(dropped, [], "같은 열 안에서 액션이 나갔습니다");
  assert.deepEqual(refused, [], "같은 열 드롭은 거절 문안이 아니라 무동작이다");

  const other = fakeEvent("tpl:t1");
  props.onDragOver(other);
  assert.equal(other.prevented, true);
  assert.equal(other.dataTransfer.dropEffect, "link");
  assert.equal(other.classes.has("drop-target"), true, "드롭 대상 강조가 서지 않았습니다");
  props.onDrop(other);
  assert.deepEqual(dropped, [["tpl", "t1", "k1"]]);
  assert.equal(other.classes.has("drop-target"), false, "드롭 뒤 강조가 남았습니다");
});

test("드래그 결속이 없는 호스트는 끌기 props 를 하나도 얹지 않는다", () => {
  assert.deepEqual(dragProps(undefined, "k1", true, ""), {});
  const markup = render(host());
  assert.equal(markup.includes('data-side="dat"'), false,
    "다이얼로그 호스트에 끌기 좌표가 새 나왔습니다");
});
