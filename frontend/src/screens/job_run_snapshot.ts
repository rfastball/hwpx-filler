/* R4-03 실행 표면이 읽는 스냅샷 — 컨트롤러 run 저장소의 마지막 full 스냅샷 구독과 managed HWPX
   판독. 실행 컨트롤러(job_run.ts)와 그 렌더 조각(job_run_views.ts)이 함께 읽는다. */
import { useSyncExternalStore } from "react";

import type { JobRunController, Obj } from "./job_run.ts";

/** HWPX 문서 생성 작업인가 — 판정은 Python 이 낸 `managed_hwpx` 하나를 읽는다. 문서 생성
 *  경로는 managed 하나라(#1081 PR2) 이 값은 「권위가 선 HWPX 작업」이다. 거짓이면 TXT(복사)·
 *  미선택 표면이거나, 초기 등록이 거절돼 권위가 서지 않은 HWPX 작업이다(그 작업의 생성은
 *  backend 가 초기 등록 거절 문장으로 닫고, 사유는 템플릿 존이 진단과 함께 말한다). */
export function isManagedHwpx(s: Obj | null): boolean {
  return s?.managed_hwpx === true;
}

export function useRunSnapshot(controller: JobRunController): Obj | null {
  return useSyncExternalStore(controller.subscribe, controller.getRun, controller.getRun).lastFull;
}
