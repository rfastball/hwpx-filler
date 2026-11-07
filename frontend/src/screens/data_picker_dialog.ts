/* 데이터 선택 다이얼로그(`#dataPickerModal`)의 렌더. 컨트롤러(상태·발신)는 `data_picker.ts`
   가 계속 소유하고, 여기는 그 스냅샷을 공용 `PoolColumn`·`ContextMenu` 로 그리는 순수
   조립만 진다. */
import { Fragment, createElement, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { ContextMenu } from "./context_menu.ts";

import { PoolColumn, SESSION_DATA_KEY } from "./pool_column.ts";
import type { PoolColumnHost } from "./pool_column.ts";
import { mergeSessionRow, poolHeadSub } from "./pool_verbs.ts";
import type { DataPickerController, PickerSessionRead } from "./data_picker.ts";

type Obj = Record<string, any>;

/** 여는 쪽이 세션 값을 주지 않았을 때 — **비어 있음을 명시**한다(추측 금지). */
const NO_SESSION_DATA: PickerSessionRead = () => (
  { data_row: null, data_pool_key: "", sheet: "" }
);

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 이 다이얼로그가 공용 열에 넘기는 호스트 — 고르기 화면의 두 열과 **한 컴포넌트**다(③b).
 *
 *  종전에는 이 자리가 세 구획(현재 데이터 / 고정한 데이터 / 다른 데이터)을 그리는 별도
 *  컴포넌트(`pool_list.ts`)였다. 같은 등록 목록을 두 문법으로 그리던 자리라, 「고를 수
 *  있는가」의 시각적 얼굴과 행 동사가 화면마다 갈렸다 — 다이얼로그는 행 안 버튼 다섯,
 *  고르기 열은 ⋯ 하나. 이제 그림은 한 벌이고 갈리는 것은 넷이다: 좌표(`dataPicker*`),
 *  바닥 동사 줄, 짝 지을 상대 열이 없다는 것(`drop` 없음), 1차 동사가 발행하는 액션
 *  (`job/load_pool` — 고르기 화면은 `editor/use_pool_data`).
 *
 *  좌표는 살아 있는 것만 **불변**이다: `#dataPickerPinned` 는 목록 그대로이고,
 *  카드 시절의 `#dataPickerCurrent`·`#dataPickerDupes`·`#dataPickerCorrupt` 는 그 카드와
 *  함께 사라졌다(현재 데이터 = 목록 첫 행, 통지 = 목록 안 `[data-notice]`). */
function dialogHost(
  controller: DataPickerController, seen: ReturnType<PickerSessionRead>, column: Obj | null,
): PoolColumnHost {
  const sessionRow = seen.data_row;
  return {
    side: "dat",
    rootId: "dataPickerPool",
    listId: "dataPickerPinned",
    title: "데이터",
    headSub: poolHeadSub(column),
    /* 고름 표지의 정본은 **작업 스냅샷**이다: 풀 겨눔이면 그 슬롯 키, 아니면 세션 행이다.
       세션이 슬롯 키를 지어내지 않는다(추측 금지) — Python 이 이미 아는 사실이다. */
    selectedKey: seen.data_pool_key || (sessionRow ? SESSION_DATA_KEY : ""),
    choose: controller.choose,
    /* `drop` 없음 = 끌기 props 0. 이 면에는 짝 지을 상대 열이 없다. */
    onMore: (row: Obj, trigger: HTMLElement) => { controller.toggleRowMenu(row, trigger); },
    onNoticeAction: controller.noticeAction,
    reload: () => controller.refresh(),
    notify: controller.notify,
    acts: createElement(Fragment, null,
      h("button", {
        className: "btn sm", id: "dataPickerBrowse", "data-busy-lock": true, key: "browse",
        onClick: () => { void controller.browseFile(); },
      }, "파일 찾아보기…"),
      /* 「이 데이터 등록…」은 **고정할 것이 있고 아직 고정되지 않았을 때만** 선다: 풀에서
         고른 데이터는 이미 등록된 참조라 다시 고정하면 같은 파일의 참조가 둘로 갈린다. */
      sessionRow && !seen.data_pool_key ? h("button", {
        className: "btn sm", id: "dataPickerPin", "data-busy-lock": true, key: "pin",
        onClick: controller.openPin,
      }, "이 데이터 등록…") : null),
    emptyFallback: "등록한 데이터를 읽는 중…",
  };
}

export function DataPickerDialog(props: { controller: DataPickerController }): ReactNode {
  const { controller } = props;
  /* 세 번째 인자(getServerSnapshot)를 같은 getter 로 넘긴다(`EditorScreen` 선례): 제품
     런타임은 쓰지 않지만, 없으면 이 면이 `react-dom/server` 로 한 번도 렌더되지 못해
     노드 배치 계약을 단위층에서 잴 수 없다. */
  const state = useSyncExternalStore(
    controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot);
  const pool = useSyncExternalStore(
    controller.poolModel.subscribe, controller.poolModel.getSnapshot,
    controller.poolModel.getSnapshot);
  const seen = state.session ? state.session.read() : NO_SESSION_DATA();
  const column = ((pool || {}).column || null) as Obj | null;
  /* 이어붙이기는 **공용 순수 함수 하나**다(공용 ⑤ 리뷰) — 고르기 우 열과 같은 목록이라
     같은 순서·같은 최소 열을 써야 한다. */
  const merged = mergeSessionRow(column, seen.data_row);
  return h("div", { className: "modal-card data-picker" },
    h("h3", { id: "dataPickerTitle" }, "데이터 선택"),
    h("p", { id: "dataPickerNote", className: `note ${state.level === "danger" ? "dangerbox" : state.level === "ok" ? "okbox" : ""}`,
      role: "status", "aria-live": "polite", style: { display: state.status ? "" : "none", whiteSpace: "pre-line" } }, state.status),
    h(PoolColumn as any, { host: dialogHost(controller, seen, column), column: merged }),
    h("div", { className: "modal-actions" },
      h("button", { className: "btn", id: "dataPickerClose", onClick: controller.close }, "닫기")),
    /* 행 ⋯ — 고르기 화면과 같은 컴포넌트를 이 면의 좌표로 세운다. 트리거 selector 가
       갈리는 것이 두 팝오버의 dismissal 을 나눈다(`#scr-editor .job-more` ↔ 이 면). */
    h(ContextMenu as any, {
      id: "dataPickerRowMenu",
      controller: controller.rowContextMenu,
      popover: controller.popover,
      triggerSelector: "#dataPickerModal .job-more",
      onDismiss: controller.closeRowMenu,
      onSelect: (action: string) => { void controller.handleRowMenu(action); },
    }));
}
