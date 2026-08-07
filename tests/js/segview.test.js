/* SegmentView 특성화 테스트 — legacy `SegView` 페인터의 React 후계(R4-02 · #415).
 *
 * 원본은 문자열 페인터(`frontend/js/segview.js`)의 특성화였다. 기대값은 전환 이전 소스를
 * 실행해 얻은 실제 출력이었고, 그것이 `innerHTML` 로 들어갔으므로 클래스 이름·속성·이스케이프
 * 넉 자가 전부 계약이었다.
 *
 * 후계는 요소 트리라 이스케이프의 소유자가 React 로 넘어갔다. 그래서 이 파일은 **같은 질문을
 * 새 산출에 다시 묻는다** — 계약(클래스·`data-token` 신원·〈빈 값〉 글리프·title 문안·구분자
 * 없는 이어붙임)은 그대로 재고, 이스케이프는 「React 가 태운다」를 산출로 확인한다.
 *
 * 잘못된 입력(text 없음 등)은 **오늘 하는 그대로** 단언한다 — 이 슬라이스는 이관이지 결함
 * 수정이 아니다. 고쳐야 한다면 그건 별도 판정이고, 그때 이 기대값이 시끄럽게 깨지는 것이 목적이다.
 *
 * `plain()` 은 후계가 없다: 제품 소비자가 0이었다(클립보드 평문은 백엔드 `copy_clipboard` 가
 * 진다). 죽은 export 를 React 로 옮기지 않는다 — 아래 마지막 테스트가 그것을 명시로 못박는다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

import * as SegmentModule from "../../frontend/src/screens/segment_view.ts";

const { SegmentView, segmentNodes } = SegmentModule;

function paint(segments, owners) {
  return renderToStaticMarkup(createElement(SegmentView, { segments, owners }));
}

test("paint: 세그먼트 목록 없음/빈 목록은 빈 산출(널 관용)", () => {
  assert.equal(paint(undefined), "");
  assert.equal(paint(null), "");
  assert.equal(paint([]), "");
  assert.equal(paint(undefined, { 이름: "auto" }), "");
});

test("paint: fill — 이름 있으면 data-token, 없으면 속성 자체가 없다", () => {
  assert.equal(
    paint([{ kind: "fill", name: "이름", text: "홍길동" }]),
    '<span class="seg-fill" data-token="이름">홍길동</span>',
  );
  assert.equal(
    paint([{ kind: "fill", text: "홍길동" }]),
    '<span class="seg-fill">홍길동</span>',
  );
});

test("paint: fill + owners — 적중이면 own-*, 불발이면 맨 seg-fill", () => {
  const seg = [{ kind: "fill", name: "이름", text: "홍길동" }];
  assert.equal(
    paint(seg, { 이름: "auto" }),
    '<span class="seg-fill own-auto" data-token="이름">홍길동</span>',
  );
  assert.equal(
    paint(seg, { 다른: "auto" }),
    '<span class="seg-fill" data-token="이름">홍길동</span>',
  );
  // owners 미전달·null 은 불발과 같은 결과 — txt 카드 하위호환면.
  assert.equal(paint(seg), '<span class="seg-fill" data-token="이름">홍길동</span>');
  assert.equal(paint(seg, null), '<span class="seg-fill" data-token="이름">홍길동</span>');
});

test("paint: owners 를 줘도 이름 없는 fill 은 소유권을 묻지 않는다", () => {
  assert.equal(
    paint([{ kind: "fill", text: "홍길동" }], { 이름: "auto" }),
    '<span class="seg-fill">홍길동</span>',
  );
});

test("paint: blank — title 문안과 〈빈 값〉 글리프", () => {
  assert.equal(
    paint([{ kind: "blank", name: "주소" }]),
    '<span class="seg-blank" data-token="주소" title="{{주소}}: 빈 값">〈빈 값〉</span>',
  );
});

test("paint: missing — seg-missing 에 원문 토큰 텍스트", () => {
  assert.equal(
    paint([{ kind: "missing", name: "금액", text: "{{금액}}" }]),
    '<span class="seg-missing" data-token="금액">{{금액}}</span>',
  );
});

test("paint: literal — kind 부재/미상은 마크업 없이 원문만", () => {
  assert.equal(paint([{ text: "안녕" }]), "안녕");
  // 이름이 있어도 literal 에는 data-token 을 붙이지 않는다(템플릿 원문엔 소유 규칙이 없다).
  assert.equal(paint([{ kind: "헛것", text: "안녕", name: "이름" }]), "안녕");
});

test("paint: 혼합 — 표시 순서대로, 구분자 없이 이어붙인다", () => {
  assert.equal(
    paint([
      { text: "계약자 " },
      { kind: "fill", name: "이름", text: "홍길동" },
      { text: " 님, " },
      { kind: "blank", name: "주소" },
      { text: " / " },
      { kind: "missing", name: "금액", text: "{{금액}}" },
    ]),
    '계약자 <span class="seg-fill" data-token="이름">홍길동</span> 님, ' +
      '<span class="seg-blank" data-token="주소" title="{{주소}}: 빈 값">〈빈 값〉</span> / ' +
      '<span class="seg-missing" data-token="금액">{{금액}}</span>',
  );
  assert.equal(
    paint(
      [
        { text: "계약자 " },
        { kind: "fill", name: "이름", text: "홍길동" },
        { kind: "fill", name: "직위", text: "대표" },
      ],
      { 이름: "auto", 직위: "manual" },
    ),
    '계약자 <span class="seg-fill own-auto" data-token="이름">홍길동</span>' +
      '<span class="seg-fill own-manual" data-token="직위">대표</span>',
  );
});

test("paint: 이스케이프 — 본문 텍스트는 React 가 태운다(마크업으로 새지 않는다)", () => {
  const html = paint([{ kind: "fill", name: "이름", text: 'a & b < c > d " e' }]);
  assert.ok(html.includes("a &amp; b &lt; c"), html);
  assert.equal(html.includes("<b>"), false);
  const literal = paint([{ text: '<b>&"</b>' }]);
  assert.equal(literal.includes("<b>"), false, literal);
  assert.ok(literal.includes("&lt;b&gt;"), literal);
});

test("paint: 이스케이프 — 이름은 속성 컨텍스트(data-token·title)에서도 태운다", () => {
  const html = paint([{ kind: "fill", name: 'n&a<m>e"x', text: "값" }]);
  assert.ok(html.includes('data-token="n&amp;a&lt;m&gt;e&quot;x"'), html);
  const blank = paint([{ kind: "blank", name: 'n&a<m>e"x' }]);
  assert.ok(blank.includes('data-token="n&amp;a&lt;m&gt;e&quot;x"'), blank);
  assert.ok(blank.includes('title="{{n&amp;a&lt;m&gt;e&quot;x}}: 빈 값"'), blank);
  const missing = paint([{ kind: "missing", name: 'n&"x', text: '{{n&"x}}' }]);
  assert.ok(missing.includes('data-token="n&amp;&quot;x"'), missing);
});

test("paint: 신원 — data-token 은 이름 있는 조각에만, literal 에는 없다", () => {
  const html = paint([
    { text: "머리 " },
    { kind: "fill", name: "이름", text: "홍길동" },
    { kind: "blank", name: "주소" },
    { kind: "missing", name: "금액", text: "{{금액}}" },
    { text: " 꼬리" },
  ]);
  assert.equal(html.match(/ data-token="/g).length, 3);
  assert.ok(html.includes(' data-token="이름"'));
  assert.ok(html.includes(' data-token="주소"'));
  assert.ok(html.includes(' data-token="금액"'));
  assert.equal(paint([{ text: "머리", name: "이름" }]).includes("data-token"), false);
});

test("paint: 오늘의 잘못된 입력 처리 — 고치지 말고 받아쓴다", () => {
  // text 없는 fill 은 String(undefined) 을 태워 문자열 "undefined" 가 그대로 보인다.
  assert.equal(
    paint([{ kind: "fill", name: "이름" }]),
    '<span class="seg-fill" data-token="이름">undefined</span>',
  );
  // 이름 없는 blank 는 data-token 을 잃고 title 에 "{{undefined}}" 가 박힌다.
  assert.equal(
    paint([{ kind: "blank" }]),
    '<span class="seg-blank" title="{{undefined}}: 빈 값">〈빈 값〉</span>',
  );
});

test("segmentNodes — 조각 배열은 소비 표면이 감쌀 수 있게 그대로 나온다", () => {
  const nodes = segmentNodes([{ text: "가" }, { kind: "fill", name: "이름", text: "홍" }]);
  assert.equal(nodes.length, 2);
  assert.equal(nodes[0], "가");
  assert.equal(nodes[1].props["data-token"], "이름");
  assert.equal(segmentNodes(null).length, 0);
});

test("공개면은 SegmentView·segmentNodes 둘뿐 — 죽은 plain 은 승계하지 않는다", () => {
  assert.deepEqual(Object.keys(SegmentModule).sort(), ["SegmentView", "segmentNodes"]);
  assert.equal(typeof SegmentModule.SegmentView, "function");
  assert.equal(typeof SegmentModule.plain, "undefined",
    "제품 소비자가 0이던 plain 은 React 후계를 만들지 않는다(#415 처분)");
});
