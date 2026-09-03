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

import { PoolColumn } from "../../frontend/src/screens/pool_column.ts";

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
