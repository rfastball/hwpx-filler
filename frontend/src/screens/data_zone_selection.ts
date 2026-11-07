/* R4-01 DataZone 의 행 선택 — 낙관적 선택 상태와 머리 체크박스 3상태 판독. 선택 수·필터 판정은
   backend 스냅샷 값이고, 여기는 보인 값과 확정 대기만 쥔다. */
import { useEffect, useRef, useState } from "react";

import type { JobReadController } from "./data_zone.ts";

type Obj = Record<string, any>;

/** 선택 — **화면이 먼저 보이고**(낙관), backend 가 그 뒤를 확정하거나 되돌린다. 실패는
 *  보인 값을 되돌리고 알린다(`anchor`는 Shift 범위 선택의 시작점, `optimisticSelection`은
 *  아직 backend 확정을 못 받은 보인 값). */
export function useOptimisticSelection(
  controller: JobReadController, rawRows: Obj[] | undefined,
): { selectedFor(row: Obj): boolean; toggleRow(row: Obj, shift: boolean): void } {
  const rows = rawRows || [];
  const anchor = useRef<{ index: number; value: boolean } | null>(null);
  const optimisticSelection = useRef(new Map<number, boolean>());
  const [, setSelectionRevision] = useState(0);

  useEffect(() => {
    let changed = false;
    const live = new Map<number, boolean>(rows.map((row) => [row.index, !!row.selected]));
    for (const [index, intended] of optimisticSelection.current) {
      if (!live.has(index) || live.get(index) === intended) {
        optimisticSelection.current.delete(index);
        changed = true;
      }
    }
    if (changed) setSelectionRevision((revision) => revision + 1);
  }, [rawRows]); // eslint-disable-line react-hooks/exhaustive-deps

  function selectedFor(row: Obj): boolean {
    return optimisticSelection.current.get(row.index) ?? !!row.selected;
  }
  function showSelection(index: number, value: boolean): void {
    optimisticSelection.current.set(index, value);
    setSelectionRevision((revision) => revision + 1);
  }
  function sendSelection(action: string, payload: Obj, intended: Array<[number, boolean]>): void {
    void controller.zone(action, payload).catch((error) => {
      let changed = false;
      for (const [index, value] of intended) {
        if (optimisticSelection.current.get(index) === value) {
          optimisticSelection.current.delete(index);
          changed = true;
        }
      }
      if (changed) setSelectionRevision((revision) => revision + 1);
      controller.notify(`선택을 바꾸지 못했습니다: ${String(error)}`);
    });
  }
  function toggleRow(row: Obj, shift: boolean): void {
    if (shift && anchor.current !== null) {
      const visible = rows.map((item) => item.index);
      const left = visible.indexOf(anchor.current.index);
      const right = visible.indexOf(row.index);
      if (left >= 0 && right >= 0) {
        const indices = visible.slice(Math.min(left, right), Math.max(left, right) + 1);
        const intended = indices.map((index: number) => [index, anchor.current!.value] as [number, boolean]);
        for (const [index, value] of intended) showSelection(index, value);
        sendSelection("select_range", { indices, value: anchor.current.value }, intended);
        return;
      }
    }
    const value = !selectedFor(row);
    anchor.current = { index: row.index, value };
    showSelection(row.index, value);
    sendSelection("toggle_record", { index: row.index, value }, [[row.index, value]]);
  }

  return { selectedFor, toggleRow };
}

/** 머리 체크박스의 3상태 — **보이는 행** 기준이다(U4 11번). 백엔드가 필터 활성 시 매치만
 *  가산하므로(`data_zone.py` `_do_set_all`), 전건 판정을 전체 레코드로 재면 필터를 켠 채
 *  다 골라도 영영 「일부」로 남는다 — 술어가 동사의 실제 결과를 따라가야 한다. 해제는
 *  **필터 밖 선택까지** 지운다(`set_none` 은 집합 전체를 비운다) — 그 범위를 이름이 말한다. */
export function resolveHeadSelection(
  visibleRows: Obj[], hidden: Obj[], filter: Obj, selectedFor: (row: Obj) => boolean,
): { headChecked: boolean; headPartial: boolean; headSelectLabel: string } {
  const visibleSelected = visibleRows.filter((row) => selectedFor(row)).length;
  const headChecked = visibleRows.length > 0 && visibleSelected === visibleRows.length;
  const headPartial = visibleSelected > 0 && !headChecked;
  const headSelectLabel = headChecked
    ? (hidden.length ? `전체 해제 (필터 밖 선택 ${hidden.length}행도 함께)` : "전체 해제")
    : (filter.active ? "보이는 행 모두 선택" : "전체 선택");
  return { headChecked, headPartial, headSelectLabel };
}
