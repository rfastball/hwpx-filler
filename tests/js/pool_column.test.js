/* 고르기 열 공용 컴포넌트(`PoolColumn`) — 좌·우 두 열이 **한 행 계약·한 상태기계**인가.
 *
 * 이 파일이 재는 것은 넷이다: ①같은 존을 두 side 로 세우면 갈리는 것이 좌표뿐인가
 * ②선택·차단의 세 상태(고를 수 있음 / 고름 / 못 고름)가 표지 하나씩으로만 서는가
 * ③못 고르는 행이 **눌리는가**(조용한 무시 금지 — `disabled` 가 아니라 `aria-disabled`)
 * ④사전 고지·통지·빈 상태·결과 줄이 스냅샷 값 그대로 서는가.
 *
 * 판정은 하나도 이 컴포넌트에 없다 — 여기서 새로 나는 문장이나 가부가 있으면 그때가
 * 「같은 상태를 두 곳이 판정한다」의 첫날이다. */
import test from "node:test";
import assert from "node:assert/strict";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { PoolColumn, dragProps } from "../../frontend/src/screens/pool_column.ts";

const ROW = {
  key: "a.hwpx", name: "공고서", sub: "필드 3개", reason: "", warns: [],
  badge_label: "변환 완료", badge_level: "ok", icon: "hwpx",
  selectable: true, path: "C:/lib/a.hwpx", actions: [],
};

const BLOCKED = Object.assign({}, ROW, {
  key: "b.hwpx", name: "원본", path: "C:/lib/b.hwpx", icon: "hwpx",
  badge_label: "누름틀만", badge_level: "warn",
  reason: "누름틀·구간 변환을 해야 고를 수 있습니다.", selectable: false,
});

const COLUMN = {
  rows: [ROW, BLOCKED], notices: [], empty_hint: "",
  count_label: "2개", result: { text: "", level: "muted" },
};

function host(overrides) {
  return Object.assign({
    side: "tpl", rootId: "editorTplPool", listId: "editorTplList",
    title: "템플릿", headSub: "서식 폴더", headSubTitle: "C:/lib",
    selectedKey: "", choose() {}, drop() {},
    emptyFallback: "서식 폴더를 아직 읽지 못했습니다.",
  }, overrides || {});
}

const render = (h, column = COLUMN) => renderToStaticMarkup(
  createElement(PoolColumn, { host: h, column }));

/** 요소 트리를 평평하게 편다(함수 컴포넌트는 호출해 펼친다) — 클릭 핸들러를 잡으려면
 *  마크업이 아니라 노드가 필요하다(`renderToStaticMarkup` 은 핸들러를 지운다). */
function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (tree === null || tree === undefined || typeof tree !== "object") return [];
  if (typeof tree.type === "function") return nodes(tree.type(tree.props));
  const children = tree.props ? tree.props.children : undefined;
  return [tree, ...nodes(children === undefined ? [] : [].concat(children))];
}

test("두 side 가 같은 행 DOM 을 낸다 — 갈리는 것은 좌표·표지·글리프뿐", () => {
  const left = render(host());
  const right = render(host({
    side: "dat", rootId: "editorDataPool", listId: "editorDataList",
    title: "데이터", headSub: "2건", headSubTitle: undefined,
  }));

  /* 행만 떼어내 좌표를 되돌리면 **한 글자도 다르지 않아야** 한다(글리프는 종류 축이라
     행 값에서 나오고, 여기서는 두 열이 같은 행을 받았으므로 그것도 같다). */
  const rowsOf = (markup) => markup.slice(markup.indexOf("pitem-wrap"));
  assert.equal(rowsOf(right).replaceAll('data-side="dat"', 'data-side="tpl"'), rowsOf(left));

  /* 좌표는 호스트가 정하고 컴포넌트가 지어내지 않는다. */
  assert.ok(left.includes('id="editorTplPool"') && left.includes('id="editorTplList"'));
  assert.ok(right.includes('id="editorDataPool"') && right.includes('id="editorDataList"'));
  assert.ok(left.includes('aria-label="템플릿"') && right.includes('aria-label="데이터"'));
});

test("고름 표지는 `selectedKey` 하나가 정한다 — 없으면 고른 행도 없다", () => {
  const none = render(host());
  assert.equal((none.match(/aria-pressed="true"/g) || []).length, 0,
    "고른 키가 없는데 고른 행이 섰습니다");
  assert.ok(none.includes('aria-pressed="false"'), "고를 수 있는 행은 축 자체는 든다");

  const one = render(host({ selectedKey: "a.hwpx" }));
  assert.equal((one.match(/aria-pressed="true"/g) || []).length, 1,
    "고른 행은 정확히 하나여야 합니다");
  const pressed = one.slice(one.indexOf('aria-pressed="true"'));
  assert.ok(pressed.includes("공고서"), "키가 가리키는 행이 고름 표지를 들어야 합니다");
});

test("못 고르는 행은 숨기지 않고 서되 **눌린다** — 사유는 그 자리에", () => {
  const chosen = [];
  const h = host({ choose: (key) => chosen.push(key) });
  const markup = render(h);

  const row = markup.slice(markup.indexOf('data-path="C:/lib/b.hwpx"'));
  const button = row.slice(0, row.indexOf("</button>"));
  assert.ok(button.includes('aria-disabled="true"'), "비활성 표시가 서야 합니다");
  assert.equal(button.includes("disabled=\"\""), false,
    "`disabled` 면 클릭이 오지 않아 사유를 말할 자리가 없습니다");
  assert.equal(button.includes('aria-pressed'), false,
    "못 고르는 행에 고름 축을 세우지 않습니다");
  assert.ok(markup.includes('class="sb why">누름틀·구간 변환을 해야 고를 수 있습니다.'),
    "사유는 부제 자리에 그대로 섭니다");

  /* 그리고 실제로 눌리면 **한 자리로 간다** — 이름·사유의 재진술은 그 자리
     (`chooseTemplate`)가 하고, 여기서 문장을 짓지 않는다. */
  const blocked = nodes(createElement(PoolColumn, { host: h, column: COLUMN }))
    .find((node) => node.props && node.props["data-path"] === "C:/lib/b.hwpx");
  assert.ok(blocked, "차단 행 노드를 찾지 못했습니다");
  blocked.props.onClick();
  assert.deepEqual(chosen, ["b.hwpx"]);
});

test("사전 고지는 사유와 **다른 줄**로 선다(#154 — 접으면 조용히 사라진다)", () => {
  const markup = render(host(), {
    rows: [Object.assign({}, ROW, { warns: ["빈 값 2건", "표식으로 남습니다"] })],
    notices: [], empty_hint: "", count_label: "1개", result: { text: "", level: "muted" },
  });
  assert.equal((markup.match(/class="sb warn"/g) || []).length, 2,
    "고지 줄 수가 스냅샷과 같아야 합니다");
  assert.ok(markup.includes("빈 값 2건") && markup.includes("표식으로 남습니다"));
});

test("존 통지는 문안과 그 처분을 **같은 자리**에 세운다", () => {
  const fired = [];
  const markup = render(
    host({ onNoticeAction: (key, payload) => fired.push([key, payload]) }),
    Object.assign({}, COLUMN, {
      notices: [
        { level: "danger", text: "⚠ 손상된 등록 데이터: a.json — bad", actions: [] },
        {
          level: "warn", text: "같은 데이터를 가리키는 등록이 2건입니다.",
          actions: [
            { key: "resolve_duplicate", label: "'A' 남기기", payload: { keep: "k1" } },
            { key: "resolve_duplicate", label: "'B' 남기기", payload: { keep: "k2" } },
          ],
        },
      ],
    }));

  assert.ok(markup.includes('data-notice="danger"') && markup.includes("note dangerbox"));
  assert.ok(markup.includes('data-notice="warn"') && markup.includes("note warnbox"));
  assert.equal((markup.match(/data-notice-act="resolve_duplicate"/g) || []).length, 2,
    "동사는 통지가 든 수만큼 섭니다");
  /* 통지는 목록의 **맨 앞**이다 — 행 아래로 밀리면 스크롤 뒤에 숨는다. */
  assert.ok(markup.indexOf("data-notice") < markup.indexOf("pitem-wrap"));

  const h = host({ onNoticeAction: (key, payload) => fired.push([key, payload]) });
  h.onNoticeAction("resolve_duplicate", { keep: "k2" });
  assert.deepEqual(fired, [["resolve_duplicate", { keep: "k2" }]]);
});

test("빈 목록의 사유는 Python 이 내고, 스냅샷이 없을 때만 이 자리 문안이 선다", () => {
  const empty = render(host(), Object.assign({}, COLUMN, {
    rows: [], empty_hint: "서식 폴더가 비어 있습니다.",
  }));
  assert.ok(empty.includes("서식 폴더가 비어 있습니다."));
  assert.equal(empty.includes("아직 읽지 못했습니다"), false,
    "Python 사유를 두고 표면 문안이 섰습니다");

  const unloaded = render(host(), null);
  assert.ok(unloaded.includes("서식 폴더를 아직 읽지 못했습니다."));
  assert.equal(unloaded.includes("pitem-wrap"), false);
});

test("결과 줄은 스냅샷의 레벨을 그대로 입고 `muted` 는 클래스를 늘리지 않는다", () => {
  const ok = render(host(), Object.assign({}, COLUMN, {
    result: { text: "검토: 문제 없음", level: "ok" },
  }));
  assert.ok(ok.includes('class="run-result ok"') && ok.includes("검토: 문제 없음"));

  const muted = render(host(), Object.assign({}, COLUMN, {
    result: { text: "읽었습니다", level: "muted" },
  }));
  assert.ok(muted.includes('class="run-result"'));

  assert.equal(render(host()).includes("run-result"), false,
    "말할 결과가 없으면 줄도 서지 않습니다");
});

test("세 번째 인스턴스(다이얼로그)도 같은 행 DOM 을 낸다 — 갈리는 것은 좌표·끌기뿐", () => {
  /* 「데이터 선택」 다이얼로그가 합류한 자리(③b). 종전에는 같은 등록 목록을 두 컴포넌트가
     각자 그렸고(카드 vs 행), 그래서 「고를 수 있는가」의 얼굴과 행 동사가 화면마다 갈렸다.
     좌표와 끌기 props 를 걷어 내면 **한 글자도 다르지 않아야** 한다. */
  const editor = render(host({
    side: "dat", rootId: "editorDataPool", listId: "editorDataList", title: "데이터",
    headSub: "2개", headSubTitle: undefined, onMore() {}, reload() {},
  }));
  const dialog = render(host({
    side: "dat", rootId: "dataPickerPool", listId: "dataPickerPinned", title: "데이터",
    headSub: "2개", headSubTitle: undefined, onMore() {}, reload() {}, drop: undefined,
  }));

  const rowsOf = (markup) => markup.slice(markup.indexOf("pitem-wrap"));
  const stripped = rowsOf(editor)
    .replace(/ draggable="[^"]*"/g, "")
    .replaceAll(' data-side="dat"', "");
  assert.equal(
    rowsOf(dialog).replaceAll(' data-side="dat"', ""), stripped,
    "같은 존을 받은 두 인스턴스가 다른 행을 그렸습니다",
  );
  /* 끌기 결속이 없는 호스트는 끌기 좌표·핸들을 **하나도** 얹지 않는다: 놓을 자리가 없는데
     끌 수 있으면 화면이 지키지 못할 약속을 한다. 행의 정체 좌표(`data-key`)는 그와 무관하게
     선다 — 그 키를 겨눈 게이트가 두 자리에 다 있다. */
  assert.equal(dialog.includes("draggable"), false, "다이얼로그 행이 끌 수 있게 섰습니다");
  assert.ok(dialog.includes('data-key="a.hwpx"'), "행이 자기 키를 말하지 않았습니다");
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
  const markup = render(host({ drop: undefined }));
  assert.equal(markup.includes('data-side="tpl"'), false,
    "다이얼로그 호스트에 끌기 좌표가 새 나왔습니다");
});

test("⋮ 와 「새로 읽기」는 호스트가 줄 때만 선다 — 죽은 어포던스를 만들지 않는다", () => {
  const bare = render(host());
  assert.equal(bare.includes('data-act="lib-more"'), false);
  assert.equal(bare.includes('data-act="refresh"'), false);

  const full = render(host({ onMore() {}, reload() {} }));
  assert.equal((full.match(/data-act="lib-more"/g) || []).length, 2,
    "⋮ 는 모든 행에 섭니다(동사 0 인 행이 없다)");
  assert.ok(full.includes('data-media="hwpx"') && full.includes('data-key="a.hwpx"'));
  assert.ok(full.includes('data-act="refresh"') && full.includes("새로 읽기"));
});
