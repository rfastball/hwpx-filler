/* 시험 입력·케이스 저장/복원·같은 문구 찾기·검색. 공유 가변 상태(뷰·viewId·타이머·검색
 * 요청 번호)는 get/set 으로 deps 를 받는다. `save`(수명주기 클러스터) 방향으로만 의존한다. */
type Obj = Record<string, any>;

export type TrialDeps = {
  views: Map<string, Obj>;
  inputPumps: Map<string, Promise<void>>;
  modal: { choose(spec: Obj): Promise<string | null>; prompt(spec: Obj): Promise<string | null> };
  snapshot(): Obj;
  tab(id?: string): Obj;
  getView(): Obj;
  getViewId(): string;
  update(patch: Obj): void;
  guarded(work: () => unknown | Promise<unknown>, kind?: string): Promise<void>;
  dispatch(action: string, payload?: Obj, verdict?: boolean): Promise<Obj>;
  flush(id: string): Promise<void>;
  revision(id: string): number;
  fenced(id: string, payload?: Obj): Obj;
  getTrialTimer(): ReturnType<typeof setTimeout> | undefined;
  setTrialTimer(timer: ReturnType<typeof setTimeout> | undefined): void;
  bumpSearchRequest(): number;
  getSearchRequest(): number;
  /** 편집기 선택 좌표만 남긴다 — authoring_controller.ts 소유 순수 함수(§6.2 공용). */
  coordinates(selection: Obj | null | undefined): Obj;
  /** 「문서 작업」에 저장 왕복을 넘긴다 — 수명주기 클러스터 소유(「저장 필요」 재시도 한 길뿐). */
  save(id: string): Promise<boolean>;
};

export function createTrialController(deps: TrialDeps) {
  function scheduleTrial(id: string): void {
    clearTimeout(deps.getTrialTimer());
    const state = deps.views.get(id);
    if (id === deps.getViewId() && state?.autoTrial && state?.trial) {
      deps.setTrialTimer(setTimeout(() => { void deps.guarded(() => runTrial(id), "trial"); }, 350));
    }
  }

  /** 시험 입력 전이. anchor 는 값을 바꾼 필드 이름이다 — 다음 결과가 그 필드의 출력 자리로 옮겨 간다(IDE-04 닻).
   *  케이스 불러오기·항목 선택처럼 한 필드를 고치지 않는 전이는 닻을 그대로 둔다. */
  async function trialInput(values: Obj, selectedOptions: Obj, anchor?: string): Promise<void> {
    const id = deps.snapshot().active_id;
    deps.update({ values, selectedOptions, ...(anchor ? { trialAnchor: anchor } : {}) });
    const previous = deps.inputPumps.get(id) || Promise.resolve();
    const pump = previous.catch(() => {}).then(async () => {
      await deps.flush(id);
      await deps.dispatch("trial_input", deps.fenced(id, { values, selected: selectedOptions }));
    });
    deps.inputPumps.set(id, pump);
    try { await pump; scheduleTrial(id); }
    finally { if (deps.inputPumps.get(id) === pump) deps.inputPumps.delete(id); }
  }

  /** U03: 고른 문구를 시험값으로 보관한다 — 이미 값이 있으면 덮어쓰지 않고 유지/교체를 묻는다. */
  async function keepTrialValue(name: string, captured: string): Promise<boolean> {
    const view = deps.getView();
    const values: Obj = { ...(view.values || {}) };
    if (name in values) {
      if (values[name] === captured) return false;
      const answer = await deps.modal.choose({ title: "시험값 보관", body: `‘${name}’ 필드에 시험값이 이미 있습니다.`,
        choices: [{ value: "keep", label: "기존 값 유지" }, { value: "replace", label: "고른 문구로 교체" }] });
      if (answer !== "replace") return false;
    }
    await trialInput({ ...values, [name]: captured }, view.selectedOptions || {}, name);
    return true;
  }

  /** 「필드 이름 사용」(IDE-01) — 손대지 않은 필드만 그 이름으로 채운다. 채울 대상은 Python 이 정하고(trial_fill_names),
   *  앞선 입력 전이 뒤에 차례로 선다. 돌아온 값이 곧 시험 입력이고 자동 갱신이 켜져 있으면 다시 시험한다. */
  async function fillTrialNames(): Promise<void> {
    const id = deps.snapshot().active_id;
    const previous = deps.inputPumps.get(id) || Promise.resolve();
    const pump = previous.catch(() => {}).then(async () => {
      await deps.flush(id);
      const result = await deps.dispatch("trial_fill_names", deps.fenced(id));
      if (id === deps.getViewId()) deps.update({ values: { ...(result.values || {}) }, selectedOptions: { ...(result.selected || {}) } });
    });
    deps.inputPumps.set(id, pump);
    try { await pump; scheduleTrial(id); }
    finally { if (deps.inputPumps.get(id) === pump) deps.inputPumps.delete(id); }
  }

  async function runTrial(id = deps.snapshot().active_id): Promise<void> {
    clearTimeout(deps.getTrialTimer());
    await deps.inputPumps.get(id);
    await deps.flush(id);
    if (id === deps.getViewId()) deps.update({ trialBusy: true, trial: true });
    // 시험 입력 검증 실패(예: 시험 선택 미지정)는 시험 패널의 상태 칩·문장(trial_state_message)으로만 선다(UX-10 R3).
    // 오류 띠는 호출 자체의 실패만 — 그래서 성공한 이 호출이 이전의 시험 오류 띠도 걷는다.
    try { await deps.dispatch("trial", deps.fenced(id), true); }
    finally { if (id === deps.getViewId()) deps.update({ trialBusy: false }); }
  }

  async function saveCase(id = deps.snapshot().active_id): Promise<boolean> {
    const name = await deps.modal.prompt({ title: "시험 케이스 저장", body: "이름", value: "" });
    if (!name) return false;
    await deps.flush(id);
    await deps.inputPumps.get(id);
    const state = deps.views.get(id) || deps.tab(id);
    await deps.dispatch("case_upsert", deps.fenced(id, { name, values: state.values || {}, selected: state.selectedOptions || state.selected || {} }));
    return persistCases(id);
  }

  async function persistCases(id: string): Promise<boolean> {
    const result = await deps.dispatch("save_cases", { session_id: id });
    if (result.needs_document_save) return await deps.save(id) && persistCases(id);
    if (result.needs_case_name) return saveCase(id);
    if (result.needs_case_repair) throw new Error(result.message);
    return true;
  }

  /** 고른 문구와 같은 다른 평문 자리(IDE-07 P-07) — 원시 자리·문맥·판정·위치 줄은 Python 이 짓는다. 돌려주는 값은
   *  찾은 revision 과 자리 목록이다. 탭·revision 이 그사이 바뀌었으면(늦은 응답) null — 표면은 옛 좌표를 보이지 않는다. */
  async function sameText(selection: Obj): Promise<{ revision: number; hits: Obj[]; summary: string | null } | null> {
    const id = deps.getViewId();
    await deps.flush(id);
    const atRevision = deps.revision(id);
    const result = await deps.dispatch("same_text", deps.fenced(id, { selection: deps.coordinates(selection) }));
    if (id !== deps.getViewId() || atRevision !== deps.revision(id)) return null;
    return { revision: atRevision, hits: result.hits || [], summary: result.summary ?? null };
  }

  async function search(query: string, kind: string, all = false): Promise<void> {
    const request = deps.bumpSearchRequest();
    const id = deps.getViewId();
    const hits: Obj[] = [];
    const searchSummaries: Obj[] = [];
    for (const item of all ? deps.snapshot().tabs : [deps.tab()]) {
      await deps.flush(item.id);
      const requestRevision = deps.revision(item.id);
      const result = await deps.dispatch("search", { session_id: item.id, revision: requestRevision, query, kind });
      hits.push(...(result.hits || result.results || []).map((hit: Obj) => ({ ...hit, session_id: item.id, source_revision: requestRevision, document: item.name })));
      if (result.summary) searchSummaries.push({ document: item.name, summary: result.summary });
    }
    if (id === deps.getViewId() && request === deps.getSearchRequest()) deps.update({ query, hits, searchSummaries, panel: "search" });
  }

  return { scheduleTrial, keepTrialValue, trialInput, fillTrialNames, runTrial, saveCase, persistCases, sameText, search };
}

export type TrialController = ReturnType<typeof createTrialController>;
