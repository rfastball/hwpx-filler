/* R4-02 채움 표지 세그먼트의 React 후계(legacy `frontend/js/segview.js`).

   계약은 그대로다 — fill 음영 · blank 〈빈 값〉 · missing {{토큰}} 빨강, 그리고 이름 있는
   조각만 `data-token` 신원을 진다(literal 에는 붙이지 않는다: 템플릿 원문에는 소유 규칙이
   없다). 작업대의 「결과 → 규칙 겨눔」이 그 한 축으로 산다.

   달라진 것은 **생산 방식**뿐이다: 문자열 조립 + `innerHTML` 이 아니라 요소 트리라
   이스케이프가 React 소유가 된다(로컬 이스케이퍼 재정의 금지 계약의 자연 이행).

   `text`·`name` 이 없는 잘못된 입력의 산출은 legacy 를 **그대로 받아쓴다**(`String(...)`).
   이 슬라이스는 이관이지 결함 수정이 아니다 — 고칠 값이면 그것은 별도 판정이고, 그때
   `tests/js/r4_segment_view.test.js` 가 시끄럽게 깨지는 것이 목적이다. */
import { createElement, Fragment } from "react";
import type { ReactNode } from "react";

export type Segment = {
  kind?: string;
  name?: string;
  text?: string;
};

export type SegmentOwners = Readonly<Record<string, string>> | null | undefined;

/** 세그먼트 하나의 요소 — literal 은 요소가 아니라 문자열이다(legacy 와 같은 산출). */
function segmentNode(segment: Segment, owners: SegmentOwners, key: number): ReactNode {
  const name = segment.name;
  /* 이름 없는 조각에는 속성을 **안 붙인다**. 조건부 객체를 펼치는 편이 짧지만, 전개는
     소유권 추출기가 못 보는 자리라 `data-token` 이 분모에서 조용히 사라진다(같은 이유로
     `sheet_picker.ts` 의 `data-first` 도 리터럴이다). `undefined` 는 React 가 속성을
     생략하므로 산출은 legacy 와 같다. */
  const token = name ? String(name) : undefined;
  if (segment.kind === "fill") {
    const own = owners && name ? owners[name] : "";
    return createElement("span", {
      key, className: own ? `seg-fill own-${own}` : "seg-fill", "data-token": token,
    }, String(segment.text));
  }
  if (segment.kind === "blank") {
    return createElement("span", {
      key, className: "seg-blank", "data-token": token, title: `{{${String(name)}}}: 빈 값`,
    }, "〈빈 값〉");
  }
  if (segment.kind === "missing") {
    return createElement("span", {
      key, className: "seg-missing", "data-token": token,
    }, String(segment.text));
  }
  return String(segment.text);
}

/** 세그먼트 목록의 요소 배열 — 널 관용(목록 없음·빈 목록은 빈 배열)은 legacy 그대로. */
export function segmentNodes(
  segments: readonly Segment[] | null | undefined,
  owners?: SegmentOwners,
): ReactNode[] {
  return (segments || []).map((segment, index) => segmentNode(segment, owners, index));
}

/** 소비 표면이 감싸는 요소를 소유하고, 이 component 는 조각만 낸다. */
export function SegmentView(props: {
  segments: readonly Segment[] | null | undefined;
  owners?: SegmentOwners;
}): ReactNode {
  return createElement(Fragment, null, ...segmentNodes(props.segments, props.owners));
}
