/* SegView 특성화 테스트(characterization) — ESM 전환의 안전망.
 *
 * 기대값은 전부 **전환 이전** 소스(base 8c522fd 의 IIFE segview.js + window.escHtml)를
 * 실행해 얻은 실제 출력이다. 새 코드를 보고 쓴 게 아니라 옛 동작을 받아쓴 것이라,
 * 이 파일이 초록이면 "ESM 으로 옮기면서 마크업이 한 바이트도 안 변했다"가 참이다.
 *
 * 이 페인터의 산출물은 innerHTML 로 들어간다 — 클래스 이름·속성 순서·앞 공백·이스케이프
 * 넉 자(& < > ")·구분자 없는 join 이 전부 계약이다. 그래서 "대충 같은 뜻"이 아니라
 * 문자열 동일성으로 못박는다.
 *
 * 잘못된 입력(text 없음 등)은 **오늘 하는 그대로** 단언한다 — 여기서 고치지 않는다.
 * 고쳐야 한다면 그건 별도 판정이고, 그때 이 기대값이 시끄럽게 깨지는 것이 목적이다.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { SegView } from "../../frontend/js/segview.js";

const { paint, plain } = SegView;

test("paint: 세그먼트 목록 없음/빈 목록은 빈 문자열(널 관용)", () => {
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

test("paint: literal — kind 부재/미상은 마크업 없이 이스케이프된 원문만", () => {
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

test("paint: 이스케이프 — 본문 텍스트의 & < > \" 넉 자", () => {
  assert.equal(
    paint([{ kind: "fill", name: "이름", text: 'a & b < c > d " e' }]),
    '<span class="seg-fill" data-token="이름">a &amp; b &lt; c &gt; d &quot; e</span>',
  );
  assert.equal(paint([{ text: '<b>&"</b>' }]), "&lt;b&gt;&amp;&quot;&lt;/b&gt;");
});

test("paint: 이스케이프 — 이름은 속성 컨텍스트(data-token·title)에서도 태운다", () => {
  assert.equal(
    paint([{ kind: "fill", name: 'n&a<m>e"x', text: "값" }]),
    '<span class="seg-fill" data-token="n&amp;a&lt;m&gt;e&quot;x">값</span>',
  );
  assert.equal(
    paint([{ kind: "blank", name: 'n&a<m>e"x' }]),
    '<span class="seg-blank" data-token="n&amp;a&lt;m&gt;e&quot;x"' +
      ' title="{{n&amp;a&lt;m&gt;e&quot;x}}: 빈 값">〈빈 값〉</span>',
  );
  assert.equal(
    paint([{ kind: "missing", name: 'n&"x', text: '{{n&"x}}' }]),
    '<span class="seg-missing" data-token="n&amp;&quot;x">{{n&amp;&quot;x}}</span>',
  );
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
  // text 없는 fill 은 String(undefined) 을 태워 문자열 "undefined" 가 새어나온다.
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

test("plain: 세그먼트 목록 없음/빈 목록은 빈 문자열", () => {
  assert.equal(plain(undefined), "");
  assert.equal(plain(null), "");
  assert.equal(plain([]), "");
});

test("plain: 혼합 — text 만 이어붙이고 마크업도 이스케이프도 없다", () => {
  assert.equal(
    plain([
      { text: "계약자 " },
      { kind: "fill", name: "이름", text: "홍길동" },
      { kind: "blank", name: "주소" },
      { kind: "missing", name: "금액", text: "{{금액}}" },
    ]),
    "계약자 홍길동{{금액}}",
  );
  assert.equal(plain([{ kind: "fill", name: 'n&"', text: '<b>&"</b>' }]), '<b>&"</b>');
});

test("plain: 오늘의 잘못된 입력 처리 — text 부재는 join 이 빈칸으로 삼킨다", () => {
  // paint 와 달리 "undefined" 가 아니라 빈 문자열로 사라진다(Array#join 의 널 처리).
  assert.equal(plain([{ kind: "fill", name: "이름" }, { text: "뒤" }]), "뒤");
  assert.equal(plain([{ kind: "blank", name: "주소" }]), "");
  assert.equal(plain([{ text: null }, { text: "뒤" }]), "뒤");
});

test("공개면은 paint·plain 둘뿐 — 넓히지 않는다", () => {
  assert.deepEqual(Object.keys(SegView).sort(), ["paint", "plain"]);
  assert.equal(typeof SegView.paint, "function");
  assert.equal(typeof SegView.plain, "function");
});

test("import 만으로 전역을 건드리지 않는다(전역 설치는 합성 루트의 __hwpx 하나뿐)", async (t) => {
  const had = Object.hasOwn(globalThis, "window");
  const prev = globalThis.window;
  globalThis.window = {};
  t.after(() => {
    if (had) globalThis.window = prev;
    else delete globalThis.window;
  });

  await import("../../frontend/js/segview.js?probe=global");
  assert.equal(Object.keys(globalThis.window).length, 0);
});
