/* 위치 줄의 문제 메모(IDE-05) — 저작 컨트롤러와 구조 패널 모델이 함께 쓰는 순수 함수. 컨트롤러가 구조 패널 모델을 가져오면
 * 그 모델이 컨트롤러 형을 가져와 모듈 고리가 생긴다 — 그래서 따로 둔다. */
type Obj = Record<string, any>;

/** 위치 줄 메시지(IDE-05)의 내용 — locate 가 판정한 `problems_here`(문제 목록 순번) 가운데 첫 문제의 심각도와 Python 문장.
 *  겹침은 Python 이 판정했다. 여기서는 순번으로 문제를 찾을 뿐이다. `source: "problem"` 은 캐럿이 옮길 때 이 메모를
 *  다음 판정까지 남겨 둘지(깜박임 없이) 가르는 표지다. */
export function problemNote(problems: Obj[] | undefined, here: unknown): { message: string; severity?: "error" | "warning"; source: "problem" } | null {
  if (!Array.isArray(here)) return null;
  for (const index of here) {
    const problem = typeof index === "number" ? problems?.[index] : undefined;
    if (!problem?.message) continue;
    const severity = problem.severity === "error" || problem.severity === "warning" ? problem.severity : undefined;
    return { message: String(problem.message), ...(severity ? { severity } : {}), source: "problem" };
  }
  return null;
}
