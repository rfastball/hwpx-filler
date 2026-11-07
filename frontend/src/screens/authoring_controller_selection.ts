/* 대상 고르기(select/adopt/back)·캐럿 보고(caretSelection)·범위 고르기(두 번 누름). 공유
 * 가변 상태(뷰·viewId·명시 선택 홀드)는 get/set 또는 Map 참조로 deps 를 받는다. `activate`
 * (수명주기 클러스터) 방향으로만 의존한다 — 반대 방향 의존은 없다. */
import type { AuthoringEditor, PickPoint, RangePick } from "./authoring_controller.ts";

type Obj = Record<string, any>;

export type SelectionDeps = {
  editors: Map<string, AuthoringEditor>;
  selectionRequests: Map<string, number>;
  navigationHistory: { id: string; revision: number; target: Obj }[];
  snapshot(): Obj;
  getView(): Obj;
  getViewId(): string;
  update(patch: Obj): void;
  guarded(work: () => unknown | Promise<unknown>, kind?: string): Promise<void>;
  dispatch(action: string, payload?: Obj, verdict?: boolean): Promise<Obj>;
  flush(id: string): Promise<void>;
  revision(id: string): number;
  fenced(id: string, payload?: Obj): Obj;
  problemHere(id: string, here: unknown): void;
  announce(text: string): void;
  scheduleRemember(id: string): void;
  /** 「데이터로 필드 찾기」·클릭 끌어오기 등 다른 문서의 대상을 고르면 그 문서를 먼저
   *  활성화한다(수명주기 클러스터 소유). */
  activate(id: string): Promise<void>;
  bumpPreviewRequest(): number;
  getExplicit(): { id: string; place: Obj; focusing: boolean } | null;
  setExplicit(value: { id: string; place: Obj; focusing: boolean } | null): void;
  /** 선택 대상의 정체(§3.3·§6.2) — authoring_controller.ts 소유 순수 함수. */
  semanticTarget(target: Obj): Obj | undefined;
  /** 명시 선택이 편집기를 옮긴 자리의 되울림인가 — authoring_controller.ts 소유 순수 함수. */
  echoes(place: Obj, selection: Obj): boolean;
  /** 범위 고르기의 한 걸음(순수) — authoring_controller.ts 소유. */
  rangePickStep(pick: RangePick | null, point: PickPoint): { pick: RangePick | null; commit?: Obj };
  copy: { rangePickStart: string; rangePickEnd: string; rangePickCancel: string };
};

export function createSelectionController(deps: SelectionDeps) {
  /** 현재 선택의 명령 가용성 — locate 결과가 실어 오면 그것, 아니면 독립 액션 `commands` 로 묻는다. */
  async function commandsFor(id: string, located: Obj | null, selection: Obj): Promise<Obj[]> {
    if (located?.commands) return located.commands;
    const result = await deps.dispatch("commands", deps.fenced(id, { selection, context: located?.context || deps.getView().context || {} }));
    return result.commands || [];
  }

  /** 명시 선택 → 편집기 좌표. 값을 파싱하지 않는다 — 투영이 준 자리를 그대로 좁힌다. */
  function selectPlace(target: Obj): { location: Obj; place: Obj } {
    const location = target.location || target.occurrences?.[0] || target.source || target;
    const place = { ...location, start: location.source_start ?? location.start, end: location.source_end ?? location.end };
    return { location, place };
  }

  /** 명시 선택의 명령 유형 표지 — 속성 패널의 기본 입력칸을 가른다. */
  function commandTypeForTarget(target: Obj): string | undefined {
    return target.kind === "field" ? "rename_field" : target.kind === "option" ? "rename_option" : target.kind === "slot" ? "rename_slot" : undefined;
  }

  /** 식별자 있는 locate 발신 — identity 스프레드를 한 자리로(`select`·`adopt` 공용). */
  function locateWithIdentity(id: string, target: Obj, location: Obj): Promise<Obj> {
    const identity = deps.semanticTarget(target);
    return deps.dispatch("locate", { session_id: id, revision: target.source_revision, selection: location, ...(identity ? { target: identity } : {}) });
  }

  /** 좁힐 좌표가 있는가 — 초점을 줄 자리가 실재하는지. */
  function hasFocusableLocation(location: Obj): boolean {
    return location.start != null || location.source_start != null || location.paragraph != null || location.start_paragraph != null;
  }

  /** 명시 선택 결과의 patch — 속성 카드·위치 줄·명령 판정을 한 자리에 모은다. */
  function selectUpdatePayload(
    location: Obj, located: Obj | null, target: Obj, options: { keepDock?: boolean }, prior: Obj | null,
    commands: Obj[], viewContext: Obj,
  ): Obj {
    return {
      selected: { ...location, ...(located?.selected || target) }, selection: location, matches: located?.matches || [],
      ...(options.keepDock ? {} : { panel: "properties", formEntry: "" }),
      refusal: null, preview: null, command: null, selectionNote: prior,
      context: located?.context || viewContext || {}, commands, commandType: commandTypeForTarget(target),
    };
  }

  /** 대상 하나를 고른다 — 편집면 강조·위치 줄·명령 판정이 그 대상으로 옮긴다. 기본은 속성 패널을 그 대상으로 연다.
   *  `keepDock`(NG-06)은 독에서 시작한 선택(문제·검색·결과 시험 행)의 길이다: `view.panel` 을 건드리지 않아 펼친 독 탭이
   *  그대로 남고 속성 패널은 열리지 않는다. 속성은 F2·문맥 메뉴·구조 목록 줄·만들기 명령으로 연다. */
  async function select(target: Obj, options: { keepDock?: boolean } = {}): Promise<void> {
    // A preview belongs to the target it was computed for. Choosing another target retires both
    // the shown preview and any in-flight one — otherwise a late create_field preview for the old
    // range lands under the new target's "필드 이름 변경" label and its apply runs the old command.
    deps.bumpPreviewRequest();
    const previous = { id: deps.snapshot().active_id, revision: deps.revision(deps.snapshot().active_id), target: deps.getView().selection };
    if (target.session_id && target.session_id !== deps.snapshot().active_id) await deps.activate(target.session_id);
    const id = deps.snapshot().active_id;
    const { location, place } = selectPlace(target);
    const hold = { id, place, focusing: true };
    // 이 선택보다 먼저 떠난 캐럿 locate 는 늦게 와도 이 선택을 바꾸지 못한다.
    deps.setExplicit(hold);
    deps.selectionRequests.set(id, (deps.selectionRequests.get(id) || 0) + 1);
    try {
      await deps.flush(id);
      const located = target.source_revision != null ? await locateWithIdentity(id, target, location) : null;
      deps.navigationHistory.push(previous);
      const view = deps.getView();
      const prior = view.selectionNote?.source === "problem" ? view.selectionNote : null;
      const commands = await commandsFor(id, located, location);
      deps.update(selectUpdatePayload(location, located, target, options, prior, commands, view.context));
      deps.problemHere(id, located?.problems_here);
      if (hasFocusableLocation(location)) await deps.editors.get(id)?.focus(place);
    } catch (error) {
      if (deps.getExplicit() === hold) deps.setExplicit(null);
      throw error;
    } finally { hold.focusing = false; }
  }

  /** 적용 결과의 patch — 속성 카드·명령 판정만 바꾼다. */
  function adoptUpdatePayload(location: Obj, located: Obj, target: Obj, commands: Obj[], viewContext: Obj): Obj {
    return {
      selected: { ...location, ...(located.selected || target) }, matches: located.matches || [],
      context: located.context || viewContext || {}, commands,
    };
  }

  /** 적용한 이름 변경이 가리키는 새 대상(#1069)을 지금 대상으로 받는다 — 패널·초점·편집기 선택은 그대로 두고, 속성 카드·
   *  위치 줄·폼 초기값·명령 판정만 Python 이 되짚은 대상으로 바꾼다(표면은 받은 대상을 쓸 뿐이다). */
  async function adopt(target: Obj): Promise<void> {
    const id = deps.snapshot().active_id;
    if (target.session_id && target.session_id !== id) return;
    const location = target.location || target.occurrences?.[0] || target;
    const located = await locateWithIdentity(id, target, location);
    if (id !== deps.getViewId()) return;
    const commands = await commandsFor(id, located, location);
    if (id !== deps.getViewId()) return;
    deps.update(adoptUpdatePayload(location, located, target, commands, deps.getView().context));
  }

  async function back(): Promise<void> {
    const previous = deps.navigationHistory.pop();
    if (!previous) return;
    await deps.activate(previous.id);
    const located = await deps.dispatch("locate", { session_id: previous.id, revision: previous.revision, selection: previous.target });
    deps.update({ selection: previous.target, selected: null, context: located.context || {}, commands: await commandsFor(previous.id, located, previous.target) });
    await deps.editors.get(previous.id)?.focus(previous.target);
  }

  /** 이 보고가 명시 선택의 되울림인가. */
  function isEchoReport(hold: { focusing: boolean; place: Obj }, selection: Obj): boolean {
    return hold.focusing || !Object.keys(selection).length || deps.echoes(hold.place, selection);
  }

  /** 같은 축(좌표)인가 — 선택이 지금 뷰 선택과 같은 자리인가. */
  const SELECTION_SAME_KEYS = ["entry", "start", "end", "paragraph", "start_paragraph", "end_paragraph"];
  function sameSelection(selection: Obj, viewSelection: Obj): boolean {
    return SELECTION_SAME_KEYS.every((key) => selection[key] === viewSelection[key]);
  }

  /** 캐럿 이동 때 위치 줄 메모를 남길지 — 같은 자리의 재보고·고르기 중·문제 메모 유지 조건. */
  function keepsSelectionNote(same: boolean, selectionNote: Obj | null | undefined, hasSelection: boolean): boolean {
    if (same || selectionNote?.source === "rangePick") return true;
    return selectionNote?.source === "problem" && hasSelection;
  }

  /** 되울림 정산 — 편집기 좌표만 받아 두고(위치 기억) 명시 대상·명령 판정은 그대로 둔다. */
  function settleEchoReport(id: string, hold: { focusing: boolean }, selection: Obj): void {
    if (!hold.focusing) deps.setExplicit(null);
    deps.selectionRequests.set(id, (deps.selectionRequests.get(id) || 0) + 1);
    deps.update({ selection });
    deps.scheduleRemember(id);
  }

  /** 캐럿 이동 정산(첫 단계) — 위치 줄 메모·선택 patch·원격 기억을 건다. 빈 선택이면 `null`. */
  function settleCaretMove(id: string, selection: Obj): { same: boolean; request: number } | null {
    const view = deps.getView();
    const same = sameSelection(selection, view.selection);
    const request = (deps.selectionRequests.get(id) || 0) + 1;
    deps.selectionRequests.set(id, request);
    // 캐럿이 옮겨 가면 위치 줄 메모(F2 불가 사유 등)는 걷힌다(IDE-01) — 같은 자리의 재보고는 이동이 아니다.
    // 문제 메모(IDE-05)는 다음 판정이 올 때까지 남는다 — 같은 문제 안의 이동에서 깜박이지 않고, 판정이 걷거나 바꾼다.
    const keepNote = keepsSelectionNote(same, view.selectionNote, Object.keys(selection).length > 0);
    deps.update({ selection, matches: [], context: {}, ...(keepNote ? {} : { selectionNote: null }) });
    deps.scheduleRemember(id);
    return Object.keys(selection).length ? { same, request } : null;
  }

  /** locate 응답이 늦었거나 그사이 자리를 떠났는가(같은 세 겹 검사가 두 번 반복된다). */
  function isStaleLocateResponse(id: string, request: number, atRevision: number): boolean {
    return id !== deps.getViewId() || deps.selectionRequests.get(id) !== request || deps.revision(id) !== atRevision;
  }

  /** 단일 적중만 있으면 그 대상을 고른다 — 그 밖(0·다건·근사)은 고르지 않는다. */
  function soleMatchSelection(matches: Obj[]): Obj | null {
    return matches.length === 1 && !matches[0].approximate ? { ...matches[0].location, ...matches[0] } : null;
  }

  /** locate 응답의 patch — 선택 옆 막대·속성 카드가 읽는 자리. `retain` 이면(이동·복제·범위
   *  조정의 목적지) 고른 대상을 바꾸지 않는다. */
  function locateUpdatePayload(result: Obj, commands: Obj[], selection: Obj, retain: boolean): Obj {
    const matches = result.matches || [];
    // commandsSelection: 이 판정이 선 편집기 선택(같은 객체) — 선택 옆 막대(IDE-08)는 지금 선택의 판정이 도착했을 때만 선다.
    return {
      matches, commands, commandsSelection: selection, context: result.context || {},
      ...(!retain ? { selected: soleMatchSelection(matches) } : {}),
    };
  }

  /** 지금 자리가 든 명시 선택 홀드(없으면 `null`). */
  function currentHold(id: string): { id: string; place: Obj; focusing: boolean } | null {
    const explicit = deps.getExplicit();
    return explicit?.id === id ? explicit : null;
  }

  async function caretSelection(id: string, selection: Obj): Promise<void> {
    if (id !== deps.getViewId()) return;
    const hold = currentHold(id);
    if (hold && isEchoReport(hold, selection)) {
      // 진행 중인 캐럿 locate 도 물린다 — 빈 선택(이동 중 보고)은 아무것도 하지 않는다.
      if (Object.keys(selection).length) settleEchoReport(id, hold, selection);
      return;
    }
    if (hold) deps.setExplicit(null);
    const move = settleCaretMove(id, selection);
    if (!move) return;
    await deps.flush(id);
    const atRevision = deps.revision(id);
    const result = await deps.dispatch("locate", deps.fenced(id, { selection }));
    if (isStaleLocateResponse(id, move.request, atRevision)) return;
    const commands = await commandsFor(id, result, selection);
    if (isStaleLocateResponse(id, move.request, atRevision)) return;
    // Moving or resizing uses the new caret as a destination; retain its source.
    const retain = move.same || ["move", "duplicate", "adjust_range"].includes(deps.getView().commandType);
    deps.update(locateUpdatePayload(result, commands, selection, retain));
    deps.problemHere(id, result.problems_here);
  }

  async function selection(id: string, nextSelection: Obj): Promise<void> {
    if (id !== deps.getViewId()) return;
    const view = deps.getView();
    // 고르기 중 키로 범위를 골랐으면(Shift+화살표) 그 범위가 선다 — 고르기는 접힌다. 캐럿 이동은 점이 아니다.
    if (view.rangePick && Object.keys(nextSelection).length && (nextSelection.start !== nextSelection.end
        || (nextSelection.start_paragraph ?? nextSelection.paragraph) !== (nextSelection.end_paragraph ?? nextSelection.start_paragraph ?? nextSelection.paragraph))) endRangePick(id);
    await caretSelection(id, nextSelection);
  }

  /** 범위 고르기(두 번 누름)를 켜고 끈다. 켜면 시작 자리를 기다린다. 끄는 길은 이 단추·Escape·편집·다른 문서다. */
  function toggleRangePick(): void {
    const view = deps.getView();
    if (view.rangePick) { cancelRangePick(); return; }
    const editor = deps.editors.get(deps.getViewId());
    if (!editor?.rangePick) return;
    deps.update({ rangePick: { phase: "start" } });
    void deps.guarded(() => editor.rangePick!(null), "editor");
    pickNote(deps.copy.rangePickStart);
  }
  /** 고르기의 안내 메모 — 여느 위치 줄 메모와 달리 캐럿 이동·문제 메모에 걷히지 않고 고르기가 끝날 때 걷힌다. */
  function pickNote(message: string): void {
    deps.update({ selectionNote: { message, severity: "info", source: "rangePick" } });
    deps.announce(message);
  }
  /** 고르기를 조용히 접는다 — 편집기의 누름 가로채기·고무줄 범위를 끄고 메모를 걷는다(취소 알림은 부른 쪽이 정한다). */
  function endRangePick(id = deps.getViewId()): void {
    const view = deps.getView();
    deps.update({ rangePick: null, ...(view.selectionNote?.source === "rangePick" ? { selectionNote: null } : {}) });
    void deps.guarded(async () => { await deps.editors.get(id)?.rangePick?.(false); }, "editor");
  }
  function cancelRangePick(): void {
    if (!deps.getView().rangePick) return;
    endRangePick();
    deps.announce(deps.copy.rangePickCancel);
  }
  /** 편집기가 알린 누름 한 번(범위 고르기 중에만 온다). 시작이면 고무줄 범위를 켜고, 끝이면 두 자리 사이를 편집기 선택으로
   *  세운다 — 그 선택의 보고가 여느 선택처럼 명령 판정·선택 옆 막대로 간다. */
  async function pickClick(id: string, point: PickPoint): Promise<void> {
    const view = deps.getView();
    if (id !== deps.getViewId() || !view.rangePick) return;
    const step = deps.rangePickStep(view.rangePick, point);
    const editor = deps.editors.get(id);
    if (step.commit) {
      endRangePick(id);
      await editor?.focus(step.commit);
      return;
    }
    if (step.pick?.phase === "end") {
      deps.update({ rangePick: step.pick });
      await editor?.rangePick?.(step.pick.start);
      pickNote(deps.copy.rangePickEnd);
    }
  }

  return {
    select, adopt, back, caretSelection, selection, toggleRangePick, cancelRangePick, pickClick,
    endRangePick,
  };
}

export type SelectionController = ReturnType<typeof createSelectionController>;
