/* 편집기 draft(이름·패턴·행 값) 발신·커밋과 데이터 열/표시형 select 발행(「저장/더티 처리」).
 * `draft` 그 자체는 흡수(`absorb`)도 써야 하는 공유 가변 상태라 main 파일이 계속 소유하고,
 * 여기는 get/set 으로만 건드린다. */
import {
  NAME_FIELD, PATTERN_FIELD, issueToken, markField, rowField, settle, typeInto,
} from "./editor_state.ts";
import type { DraftState, RowAxis } from "./editor_state.ts";
import type { Obj } from "./editor_controller.ts";

export type DraftOpsDeps = {
  getDraft(): DraftState;
  setDraft(next: DraftState): void;
  emitDraft(): void;
  /** 편집 변이 — 전부 한 체인에 선다(순서에 기대는 질의도 포함). */
  sendEdit(action: string, payload?: Obj): Promise<Obj>;
  /** 대기 중 편집을 전부 올린 뒤 그 체인이 비는 지점을 기다리는 sentinel. */
  settleChain(): Promise<unknown>;
  notify(message: string): void;
  noticeSave(message: string): void;
  getView(): { invalidField: string };
  patchView(next: Obj): void;
  snapshot(): Obj;
};

export function createDraftOps(deps: DraftOpsDeps) {
  /* ---- draft 커밋: 컨트롤에서 온 값의 발신 자리 ---- */

  function type(field: string, value: string): void {
    deps.setDraft(typeInto(deps.getDraft(), field, value));
    /* 겨눈 칸을 사용자가 고치는 순간 그 차단 알림은 현 상태를 서술하지 않는다 — 겨눔과
       사유를 같은 전이에서 함께 걷는다(#874). */
    if (deps.getView().invalidField !== "" && field === deps.getView().invalidField) {
      deps.patchView({ invalidField: "", saveMessage: null });
    }
    deps.emitDraft();
  }

  function focus(field: string, focused: boolean): void {
    deps.setDraft(markField(deps.getDraft(), field, { focused }));
    deps.emitDraft();
  }

  function compose(field: string, composing: boolean): void {
    deps.setDraft(markField(deps.getDraft(), field, { composing }));
    deps.emitDraft();
  }

  /** 값 커밋 — session·token 이 맞는 응답만 draft 를 clean 으로 올린다. */
  async function commit(field: string, action: string, payload: Obj): Promise<void> {
    const session = deps.getDraft().session;
    const issued = issueToken(deps.getDraft(), field);
    deps.setDraft(issued.state);
    deps.emitDraft();
    try {
      await deps.sendEdit(action, payload);
      deps.setDraft(settle(deps.getDraft(), { ok: true, session, token: issued.token, key: field }));
    } catch (error) {
      deps.setDraft(settle(deps.getDraft(), {
        ok: false, session, token: issued.token, key: field,
        error: String((error as Obj)?.message || error),
      }));
      deps.notify(String((error as Obj)?.message || error));
    }
    deps.emitDraft();
  }

  /* 발신은 **호출 자리마다 리터럴**이다 — 액션 이름과 페이로드 키를 표로 감추면 정적
     계약(dispatch 배선·페이로드 스키마)이 이 화면을 못 보고 공허하게 통과한다. */
  function commitField(field: string): void {
    const state = deps.getDraft().fields[field];
    if (state === undefined || !state.dirty) return;
    if (field === NAME_FIELD) void commit(field, "set_name", { name: state.draftValue });
    if (field === PATTERN_FIELD) void commit(field, "set_pattern", { pattern: state.draftValue });
  }

  /** 표 안의 두 select 가 쓰는 **초안 없는** 발신(U6-C 리뷰 2).
   *
   *  select 는 값을 들고 있을 이유가 없다 — 고르는 순간이 곧 커밋이고, 타이핑처럼 지켜야 할
   *  중간 상태가 없다. 초안을 두면 그 값(항목 값)이 지연 flush 의 일반 갈래로 새어 액션
   *  payload 를 오염시킨다. 실패하면 화면을 서버 값으로 되돌린다: 재렌더가 제어 select 의
   *  DOM 값을 스냅샷 값으로 되맞추므로 「고른 것처럼 보이는데 안 고른」 자리가 남지 않는다. */
  function sendRowChoice(action: string, payload: Obj): void {
    void deps.sendEdit(action, payload)
      .catch((error) => { deps.noticeSave(String((error as Obj)?.message || error)); })
      /* 성공이든 실패든 한 번 더 그린다 — 실패는 되돌리기고, 성공은 push 가 오기 전까지
         화면이 옛 값을 들고 있지 않게 하는 정산이다. */
      .finally(() => { deps.patchView({}); });
  }

  /** 데이터 열 항목 값 → 발행할 액션(U6-C #977).
   *
   *  **값을 파싱하지 않는다** — Python 이 낸 항목 목록에서 그 값을 찾아 `kind` 를 읽는다.
   *  접두 규칙(`col:`/`sp:`)을 여기서 다시 해석하면 그 규칙을 두 곳이 소유하게 되고,
   *  Python 이 이름 공간을 바꾸는 날 웹만 옛 규칙으로 남는다. 목록에 없는 값은 조용히
   *  무시하지 않고 시끄럽게 던진다(선택지에 없는 것이 선택됐다 = 배선 결함). */
  function chooseDataColumn(index: number, value: string): void {
    const options = (deps.snapshot().data_column_options || []) as Obj[];
    const row = ((deps.snapshot().rows || []) as Obj[]).find((r) => Number(r.index) === index);
    /* 「데이터에 없음」 항목은 그 행에만 서는 자리라 공용 목록에 없다 — 지금 값 그대로
       되보내는 무동작이므로 발신하지 않는다(같은 열을 다시 고른 것과 같다). */
    if (row && row.source_missing_label && value === String(row.source_value)) return;
    const picked = options.find((option) => String(option.value) === value);
    if (picked === undefined) throw new Error(`알 수 없는 데이터 열 항목입니다: ${value}`);
    const kind = String(picked.kind);
    if (kind === "column") {
      sendRowChoice("set_source", { index, source: String(picked.field) });
    } else if (kind === "none") {
      sendRowChoice("set_source", { index, source: "" });
    } else {
      /* 「고정값…」을 고르면 값을 적을 자리가 새로 생긴다. 그 입력은 **서버가 이 행을
         const 로 인정한 뒤에야** 렌더되므로 지금 DOM 에는 없다 — 마이크로태스크로 겨누면
         언제나 빈손이다. 표지를 남기고 그 입력이 실제로 선 렌더에서 초점을 준다(리뷰 8). */
      if (kind === "const") deps.patchView({ pendingConstFocus: index });
      sendRowChoice("set_display", { index, type: kind, fmt: "" });
    }
  }

  /** 표시형 항목 값 → (유형, 표시형) 한 쌍(U6-C 리뷰 1). 값 문자열은 파싱하지 않는다 —
   *  항목이 `type`·`fmt` 를 따로 들고 오므로 접두 규칙을 웹이 소유하지 않는다. */
  function chooseDisplay(index: number, value: string): void {
    const row = ((deps.snapshot().rows || []) as Obj[]).find((r) => Number(r.index) === index);
    const groups = ((row || {}).display_options || []) as Obj[];
    for (const group of groups) {
      const picked = ((group.options || []) as Obj[])
        .find((option) => String(option.value) === value);
      if (picked !== undefined) {
        sendRowChoice("set_display", {
          index, type: String(picked.type), fmt: String(picked.fmt),
        });
        return;
      }
    }
    throw new Error(`알 수 없는 표시형 항목입니다: ${value}`);
  }

  function commitRowValue(index: number, axis: RowAxis, value: string): void {
    void commit(rowField(index, axis), "set_const", { index, const: value });
  }

  function commitRow(index: number, axis: RowAxis, value: string): void {
    type(rowField(index, axis), value);
    commitRowValue(index, axis, value);
  }

  function commitRowOnBlur(index: number, axis: RowAxis): void {
    const state = deps.getDraft().fields[rowField(index, axis)];
    if (state === undefined || !state.dirty) return;
    commitRowValue(index, axis, state.draftValue);
  }

  /** dirty draft를 발신열에 올리고 그 줄을 비운다 — 커밋(이동·저장·이탈) 전 관문이다.
   *  버튼 행동이 먼저 온 경우에도 blur 이벤트의 발생 여부에 기대지 않는다. 이미 blur가 올린
   *  field(`pendingToken > 0`)는 다시 보내지 않고 아래 sentinel이 그 발신만 기다린다. */
  async function flushPendingEdits(): Promise<unknown> {
    const commits: Promise<void>[] = [];
    for (const [field, state] of Object.entries(deps.getDraft().fields)) {
      if (!state.dirty || state.pendingToken > 0 || state.composing) continue;
      if (field === NAME_FIELD) {
        commits.push(commit(field, "set_name", { name: state.draftValue }));
        continue;
      }
      if (field === PATTERN_FIELD) {
        commits.push(commit(field, "set_pattern", { pattern: state.draftValue }));
        continue;
      }
      /* 행 축의 초안은 **고정값 입력 하나**다(U6-C 리뷰 2). 종전에는 데이터 열 select 도
         초안을 가졌는데 그 값은 열 이름이 아니라 **항목 값**(`col:…`/`sp:…`)이라, 지연
         flush 의 일반 갈래가 그것을 `set_source` 에 그대로 실어 존재하지 않는 열
         「col:품명」에 결속시켰다 — R5 센티넬 금지의 정확한 위반이다. 두 select 는 이제
         초안을 두지 않고 고른 그 자리에서 kind 로 갈라 발행한다. 「가공」 팝오버의 입력은
         행 축 초안이 아니다(팝오버가 blur·Enter 에서 완성된 명세로 보낸다). */
      const match = /^row:(\d+):(const)$/.exec(field);
      if (match === null) throw new Error(`알 수 없는 편집 draft field입니다: ${field}`);
      const index = Number(match[1]);
      commits.push(commit(field, "set_const", { index, const: state.draftValue }));
    }
    await Promise.all(commits);
    return deps.settleChain();
  }

  return {
    type, focus, compose, commitField, commitRow, commitRowOnBlur,
    chooseDataColumn, chooseDisplay, flushPendingEdits,
  };
}
