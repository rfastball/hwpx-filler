/* R4-01 job 읽기 표면의 스냅샷 판독 — job 모델 full 스냅샷의 형태 검사(`has_data`·`has_job` 판정이
   없으면 던진다)와 화면 UI 상태 구독. 컨트롤러(job_read.ts)와 렌더 조각(job_read_views.ts)이 함께 읽는다. */
import { useSyncExternalStore } from "react";

import type { JobReadController, Obj, UiState } from "./job_read.ts";
import type { JobScreenModel } from "./runtime.ts";

function asObject(value: unknown, label: string): Obj {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}: snapshot 객체가 아닙니다.`);
  }
  return value as Obj;
}

export function fullSnapshot(model: JobScreenModel): Obj | null {
  if (model.full === null) return null;
  const snapshot = asObject(model.full, "job");
  if (typeof snapshot.has_data !== "boolean" || typeof snapshot.has_job !== "boolean") {
    throw new Error("job snapshot: has_data/has_job 판정이 없습니다.");
  }
  return snapshot;
}

export function useJob(controller: JobReadController): Obj | null {
  /* 세 번째 인자는 정적 렌더의 스냅샷이다 — 같은 출처를 준다(다른 화면의 관례와 동일).
     없으면 `renderToStaticMarkup` 이 이 화면에서만 던져 정적 렌더 계약을 못 세운다. */
  const model = useSyncExternalStore(
    controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot);
  return fullSnapshot(model);
}

export function useUi(controller: JobReadController): UiState {
  return useSyncExternalStore(controller.uiModel.subscribe, controller.uiModel.getSnapshot, controller.uiModel.getSnapshot);
}
