/* 열 머리 필터 패널의 상태와 「값 선택」 목록(#1137).

   무엇이 목록에 서고 무엇이 체크됐는지는 Python `filter_panel` 이 정한다 — 같은 열의 부분일치·범위
   조건이 배제한 값은 목록에 서지 않는다(엑셀 검색 상자 동형, `FilterView.column_values`). 여기는 그
   답을 그리고, **패널이 열린 채 필터가 바뀌면 다시 물어** 칸을 그 답에 맞출 뿐이다 — 판정하지 않는다.

   다시 묻기는 존 변이와 같은 직렬 체인으로 보낸다(앞서 보낸 변이가 모두 반영된 답). 그 사이 사용자가
   값 칸을 또 누르면 그 답은 버린다 — 늦은 답이 방금 누른 칸을 되돌리면 다음 누름이 되돌려진 칸으로
   목록을 계산한다. 누름마다 push 가 오고 그 push 가 다시 묻게 하므로 마지막 답은 늘 버려지지 않는다. */
import { createElement, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

type Obj = Record<string, any>;

type PanelController = {
  doc: Document;
  notify(message: string): void;
  uiModel: { subscribe(listener: () => void): () => void; getSnapshot(): Obj };
  zone(action: string, payload?: Obj, returnValue?: boolean): Promise<Obj>;
};

/** 열린 패널 — `data === null` 은 첫 답을 기다리는 중(로딩 껍데기). */
export type PanelState = { column: string; data: Obj | null } | null;

type Box = { checked: boolean; dataset: { val?: string } };
type PanelRoot = {
  querySelectorAll(selector: string): ArrayLike<any>;
  querySelector(selector: string): any;
};

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 값 칸의 체크 — Python 이 준 그대로(`checked === null` 은 「(전체)」 = 목록의 값 전부). */
export function valueChecked(data: Obj, value: string): boolean {
  return data.checked === null || !!data.checked?.includes(value);
}

/** 값 칸 → 보낼 체크 목록 — 칸이 모두 켜지면 `null`(「(전체)」). */
export function valuesFromBoxes(boxes: Box[]): string[] | null {
  const on = boxes.filter((box) => box.checked).map((box) => box.dataset.val || "");
  return on.length === boxes.length ? null : on;
}

/** 「(전체)」 누름 — 값 칸(비제어)을 그 상태로 세우고 보낼 목록을 준다. 켜진 채 남으면 다음 누름이
 *  고른 값을 끄는 쪽으로 뒤집힌다(#1131). */
export function setAllBoxes(boxes: Box[], on: boolean): string[] | null {
  for (const box of boxes) box.checked = on;
  return on ? null : [];
}

/** 열린 패널의 칸을 새 답에 맞춘다 — 값 칸·「(전체)」, 그리고 초점 밖·대기 입력 없는 부분일치 칸의 글자
 *  (「이 열 조건 지우기」·칩 × 가 지운 글자가 패널에 남지 않게). 입력 중인 칸은 건드리지 않는다. */
export function syncColumnPanel(root: PanelRoot | null, data: Obj, typing: boolean): void {
  if (!root) return;
  for (const box of Array.from(root.querySelectorAll("input[data-val]")) as Box[]) {
    box.checked = valueChecked(data, box.dataset.val || "");
  }
  const all = root.querySelector("input[data-val-all]");
  if (all) all.checked = data.checked === null;
  const text = root.querySelector("input[data-ctext]");
  if (text && !typing && text !== text.ownerDocument?.activeElement) text.value = String(data.text || "");
}

/** 늦게 도착한 실패가 지금 열린 패널과 같은 열일 때만 참 — 다른 열을 연 뒤(또는 패널을 닫은 뒤) 도착한
 *  옛 실패는 통보·패널 닫기 어느 쪽도 하지 않는다(#1139, 성공 답의 `current?.column === column` 과 같은 결). */
export function shouldReportPanelFailure(panel: PanelState, column: string): boolean {
  return panel?.column === column;
}

/** 다시 묻기의 순서 규칙 — `edited()` 뒤에 도착한, 그 전에 보낸 물음의 답은 버린다. */
export function createPanelRefresher(deps: {
  fetch(column: string): Promise<Obj>;
  apply(column: string, data: Obj): void;
  fail(column: string, error: unknown): void;
}) {
  let edits = 0;
  return {
    edited(): void { edits += 1; },
    refresh(column: string): void {
      const mine = edits;
      deps.fetch(column).then(
        (data) => { if (mine === edits) deps.apply(column, data); },
        (error) => deps.fail(column, error),
      );
    },
  };
}

function boxesOf(input: HTMLElement): Box[] {
  return [...(input.closest(".cp-vals") as HTMLElement).querySelectorAll<HTMLInputElement>("input[data-val]")];
}

/** 「값 선택」 칸 — 목록·체크는 Python 답 그대로, 누름은 존 변이 하나. */
export function ColumnValues(props: {
  controller: PanelController;
  column: string;
  data: Obj;
  onEdit(): void;
}): ReactNode {
  const { controller, column, data, onEdit } = props;
  const ref = useRef<HTMLDivElement | null>(null);
  const ui = useSyncExternalStore(controller.uiModel.subscribe, controller.uiModel.getSnapshot, controller.uiModel.getSnapshot);
  const typing = !!ui.pendingColumn;
  useLayoutEffect(() => syncColumnPanel(ref.current?.closest(".colpanel") ?? null, data, typing), [data]);
  const send = (values: string[] | null) => {
    onEdit();
    void controller.zone("filter_col_values", { column, values });
  };
  return h("div", { className: "cp-sec", ref }, h("span", { className: "cp-cap" }, "값 선택(같은 열 안은 OR)"),
    h("div", { className: "cp-vals" },
      h("label", null, h("input", { type: "checkbox", "data-val-all": true, defaultChecked: data.checked === null,
        onChange: (event: Obj) => send(setAllBoxes(boxesOf(event.currentTarget), event.currentTarget.checked)) }),
      h("b", null, "(전체)")),
      ...(data.options || []).map((value: string) => h("label", { key: value },
        h("input", { type: "checkbox", "data-val": value, "data-busy-lock": true,
          defaultChecked: valueChecked(data, value),
          onChange: (event: Obj) => send(valuesFromBoxes(boxesOf(event.currentTarget))) }),
        value === "" ? "(빈값)" : value))));
}

/** 열 머리 패널의 상태 — 열기(같은 열이면 닫기)·필터가 바뀌면 다시 묻기·값 누름 표지.
 *
 *  여는 순간 누른 자리를 `trigger` 에 들고(배치 기준) `onOpen()`(부르는 쪽의 일 — 빌더 닫기)을 부른다. 다시 묻는 계기는 존
 *  epoch(데이터 마운트)와 정의줄이다 — 열 조건·검색·저장한 필터 어느 것이 바뀌어도 정의줄이 바뀐다. */
export function useColumnPanel(
  controller: PanelController, snapshot: Obj, trigger: { current: HTMLElement | null }, onOpen: () => void,
) {
  const [panel, setPanel] = useState<PanelState>(null);
  const panelRef = useRef<PanelState>(panel);
  const setPanelTracked = (next: PanelState | ((current: PanelState) => PanelState)) => {
    setPanel((current) => {
      const value = typeof next === "function" ? (next as (current: PanelState) => PanelState)(current) : next;
      panelRef.current = value;
      return value;
    });
  };
  const refresher = useRef<ReturnType<typeof createPanelRefresher> | null>(null);
  /** 늦게 도착한 실패는 그 자리의 패널이 여전히 그 열일 때만 통보하고 닫는다(#1139 — 다른 열을
   *  연 뒤 도착한 실패가 그 패널을 닫지 않도록). */
  const fail = (column: string, error: unknown) => {
    if (!shouldReportPanelFailure(panelRef.current, column)) return;
    controller.notify(`필터를 불러오지 못했습니다: ${String(error)}`);
    setPanelTracked(null);
  };
  refresher.current ??= createPanelRefresher({
    fetch: (column) => controller.zone("filter_panel", { column }),
    apply: (column, data) => setPanelTracked((current) => current?.column === column && current.data !== null ? { column, data } : current),
    fail,
  });
  const revision = `${snapshot.zone_epoch}|${snapshot.filter?.definition}`;
  const seen = useRef(revision);
  const loaded = panel !== null && panel.data !== null ? panel.column : null;
  useEffect(() => {
    if (loaded === null || seen.current === revision) return;
    seen.current = revision;
    refresher.current?.refresh(loaded);
  }, [revision, loaded]);

  async function open(column: string, from: HTMLElement | null): Promise<void> {
    if (panel?.column === column) { setPanelTracked(null); return; }
    onOpen();
    trigger.current = from;
    seen.current = revision;  // 여는 물음이 답할 정의 — 기다리는 사이 바뀌면 도착 뒤 다시 묻는다
    setPanelTracked({ column, data: null });
    try {
      const data = await controller.zone("filter_panel", { column }, true);
      setPanelTracked((current) => current?.column === column ? { column, data } : current);
    } catch (error) {
      fail(column, error);
    }
  }

  return { panel, setPanel: setPanelTracked, open, edited: refresher.current.edited };
}
