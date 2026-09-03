/* 「자세히…」가 여는 **등록 데이터 상세 시트**(고르기 열 공용 ④ · `#poolDetailModal`).
 *
 * 좌 열 항목의 시트(`TplDetailSheet`)와 **같은 골격**(`DetailSheetFrame`)을 쓰고, 갈리는
 * 것은 몸통 하나다: 저쪽이 필드 표와 구간 항목을 그리는 자리에 이쪽은 정체 한 줄과 열 표를
 * 그린다. 두 열이 한 컴포넌트인 이상 그 열의 항목이 답하는 면도 한 형이어야 한다.
 *
 * **재료는 `pool` 채널 존 하나**다(`detail`). 시트가 두 스냅샷을 합성하면 그 사이에 갈린
 * 사실이 한 장에 함께 선다(배지는 옛것, 열 목록은 새것). 문안·수치도 전부 Python 이
 * 낸다 — 정체 줄의 성분은 링1 `DatasetDetail.facts()`, 열 표 머리는 `column_summary()` 다.
 *
 * **겨누는 것은 세션이 아니라 등록 항목**이다: 지금 그 데이터를 쓰고 있든 아니든 같은 시트가
 * 서고, 파일로 연 세션 행에는 애초에 이 문이 없다(풀에 없는 것은 검토할 항목이 아니다).
 */
import { createElement, Fragment, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { createDataPickerController } from "./data_picker.ts";
import { DetailSheetFrame } from "./detail_sheet.ts";
import { dataRowMenuItems } from "./pool_verbs.ts";

type Obj = Record<string, any>;
type PoolDetailController = ReturnType<typeof createDataPickerController>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 몸통 — 정체 한 줄 · 열 표 머리 · 열 표.
 *
 *  표는 좌 열 시트의 필드 표와 **같은 좌표**(`.schema-fields`)를 쓴다: 같은 형의 두 표라
 *  문법이 갈리면 한 시트에서 다른 시트로 넘어갈 때 같은 것이 다르게 보인다. 열은 값이
 *  하나뿐이라(이름) 유형 칸이 없다 — 데이터 열에는 링0 추정을 얹는 축이 없고, 없는 축을
 *  지어 세우지 않는다. */
function DetailColumns(props: { detail: Obj }): ReactNode {
  const { detail } = props;
  const columns = (detail.columns || []) as string[];
  const facts = (detail.facts || []) as string[];
  return createElement(Fragment, null,
    facts.length
      ? h("p", { className: "muted capnote", id: "poolDetailFacts" }, facts.join(" · "))
      : null,
    h("p", { className: "fields-head", id: "poolDetailColumnSummary" },
      String(detail.column_summary || "")),
    columns.length
      ? h("div", { className: "tblwrap" },
        h("table", { className: "schema-fields", id: "poolDetailColumns" },
          h("thead", null, h("tr", null, h("th", null, "열"))),
          h("tbody", null, ...columns.map((name: string, index: number) =>
            h("tr", { key: index },
              h("td", null, h("span", { className: "fname" }, String(name))))))))
      : null);
}

export function PoolDetailSheet(props: { controller: PoolDetailController }): ReactNode {
  const { controller } = props;
  /* 세 번째 인자(getServerSnapshot)는 `react-dom/server` 로 이 면을 한 번은 렌더할 수 있게
     한다 — 없으면 노드 배치를 단위층에서 잴 수 없다(다른 overlay 와 같은 이유). */
  const pool = useSyncExternalStore(
    controller.poolModel.subscribe, controller.poolModel.getSnapshot,
    controller.poolModel.getSnapshot) as Obj | null;
  const view = useSyncExternalStore(
    controller.model.subscribe, controller.model.getSnapshot,
    controller.model.getSnapshot) as Obj;
  const detail = (((pool || {}) as Obj).detail || null) as Obj | null;
  const result = (((pool || {}) as Obj).result || {}) as Obj;
  const shared = {
    idPrefix: "poolDetail",
    client: controller.client,
    notify: controller.notify,
    message: String(view.detailMessage || ""),
    /* 성과 줄의 정본은 그대로 `pool.result`(Python) 다 — 여기서 다시 짓는 문안은 없다. */
    result,
    onClose: (): void => { controller.closeDetail(); },
  };
  if (detail === null) {
    return h(DetailSheetFrame as any, Object.assign({}, shared, {
      title: "데이터 상세",
      empty: "볼 항목이 없습니다. 목록에서 항목의 ⋮ → 「자세히…」를 누르세요.",
    }));
  }
  /* 동사 줄은 행 ⋮ 와 **같은 함수**가 짓는다(같은 상태 두 곳 판정 금지) — 지금 서 있는
     「자세히…」 자신만 걷는다. */
  const verbs = dataRowMenuItems(detail).filter((entry) => entry.action !== "detail");
  return h(DetailSheetFrame as any, Object.assign({}, shared, {
    title: String(detail.name || ""),
    pill: {
      label: String(detail.badge_label || ""),
      level: String(detail.badge_level || "muted"),
    },
    path: String(detail.path || ""),
    /* 읽기 실패(끊긴 참조·오타난 시트·손상 파일)는 숨기지 않는다 — 그 사유를 보이는 것이
       이 시트가 오류 항목에서도 서는 이유이고, 「다시 연결」 동사에 닿는 문이기도 하다. */
    error: String(detail.error || ""),
    body: h(DetailColumns as any, { detail }),
    verbs,
    onVerb: (action: string, trigger: HTMLElement): void => {
      void controller.handleDetailVerb(action, trigger);
    },
  }));
}
