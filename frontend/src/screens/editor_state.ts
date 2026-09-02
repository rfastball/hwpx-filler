/* R4-02 편집 표면의 **local draft reducer** — 전송 스냅샷과 입력 중인 값의 소유자를 가른다.

   legacy 편집기는 이 문제를 두 기제로 풀었다: 공용 보존 헬퍼가 재구성을 가로질러 포커스·
   캐럿을 되찾고, `pendingFieldEdit` 1슬롯이 「아직 커밋되지 않은 타이핑」의 존재와 값을 들었다.
   React 는 재구성이 아니라 **소유**로 푼다 — 입력값의 소유자가 이 reducer 하나이고, push 는
   `serverValue` 만 갈아 끼운다. 그래서 보존할 캐럿이 애초에 생기지 않는다(같은 노드가 산다).

   불변식(패킷 rev2 §2.2):

   1. full push 는 새 `serverValue`/`baseRevision` 를 저장한다.
   2. `dirty || focused || composing` 인 field 의 `draftValue` 는 **덮지 않는다**.
   3. 손대지 않은 field 만 새 server 값을 흡수한다.
   4. 변이는 단조 증가 `pendingToken` 을 발급하고, 응답은 **session 과 token 이 모두** 맞을
      때만 반영한다.
   5. 늦은 성공·실패는 현재 draft 를 지우지 않고 stale 관측으로 남는다.
   6. Python 이 새 값을 확인한 뒤에만 draft 가 clean 으로 승격한다.

   session 이 바뀌거나(다른 작업을 열었다) 서버가 더 이상 그 field 를 들지 않으면(탭 이동으로
   행이 사라졌다) 그 draft 는 **버린다** — legacy 가 「되돌릴 자리가 없으면 대기도 버린다」로
   쓴 규칙과 같다. 되돌릴 자리가 없는 대기는 열린 저장 버튼의 거짓 근거가 된다. */

export type FieldState = {
  /** 이 값을 낸 스냅샷 판본. 늦은 응답이 어느 세대의 답인지 가른다. */
  baseRevision: number;
  /** Python 이 아는 값. */
  serverValue: string;
  /** 사용자가 보고 있는 값. clean 이면 serverValue 와 같다. */
  draftValue: string;
  dirty: boolean;
  focused: boolean;
  composing: boolean;
  /** 0 = 대기 중 변이 없음. */
  pendingToken: number;
  /** 이 field 에 대한 마지막 실패 사유(조용히 삼키지 않는다). */
  error: string;
};

export type DraftState = {
  /** 편집 세션의 정체 — 바뀌면 모든 draft 를 버린다. */
  session: string;
  revision: number;
  fields: Readonly<Record<string, FieldState>>;
  /** 마지막으로 발급한 token. 화면 전체에서 단조 증가한다. */
  lastToken: number;
  /** 늦게 도착해 버려진 응답의 수 — 음성 대조가 「무시했다」를 관측할 자리. */
  staleResponses: number;
};

export type FieldPatch = { focused?: boolean; composing?: boolean };

export const NAME_FIELD = "name";
export const PATTERN_FIELD = "pattern";

/** 행 축의 **초안 대상**은 고정값 입력 하나다(U6-C 리뷰 2). 두 select(데이터 열·표시형)는
 *  고르는 순간이 곧 커밋이라 초안을 두지 않는다 — 두면 그 항목 값(`col:…`/`sp:…`)이 지연
 *  flush 의 일반 갈래로 새어 액션 payload 를 오염시킨다. */
export type RowAxis = "const";

/** 행 field 키 — 표시 순서가 아니라 **행 index** 로 짓는다(Python 이 든 정체). */
export function rowField(index: number, axis: RowAxis): string {
  return `row:${index}:${axis}`;
}

function cleanField(value: string, revision: number): FieldState {
  return {
    baseRevision: revision,
    serverValue: value,
    draftValue: value,
    dirty: false,
    focused: false,
    composing: false,
    pendingToken: 0,
    error: "",
  };
}

export function emptyDraft(): DraftState {
  return { session: "", revision: 0, fields: {}, lastToken: 0, staleResponses: 0 };
}

/** 스냅샷이 든 편집 가능 값 전수. 여기 없는 키는 그 스냅샷에서 편집 대상이 아니다. */
export type ServerValues = Readonly<Record<string, string>>;

/** 전송 스냅샷 흡수 — 규칙 1~3. 세션이 바뀌면 전부 새로 세운다. */
export function ingestSnapshot(
  state: DraftState,
  args: { session: string; revision: number; values: ServerValues },
): DraftState {
  const fresh = args.session !== state.session;
  const fields: Record<string, FieldState> = {};
  for (const [key, value] of Object.entries(args.values)) {
    const previous = fresh ? undefined : state.fields[key];
    if (previous === undefined) {
      fields[key] = cleanField(value, args.revision);
      continue;
    }
    const held = previous.dirty || previous.focused || previous.composing;
    /* 든 값은 그대로 두되 `dirty` 는 **다시 센다**(규칙 6 의 승격 자리). 커밋 응답만으로는
       올리지 않기 때문에, Python 이 새 값을 확인해 준 이 push 가 그 유일한 승격 경로다.
       여기서 옛 `dirty` 를 그대로 이월하면 저장이 성사된 뒤에도 화면이 영영 미저장이라고
       말하고 이탈 가드가 계속 묻는다 — 규칙 6 이 「승격하지 않는다」가 아니라 「확인 뒤에만
       승격한다」인 이유다. */
    fields[key] = held
      ? {
        ...previous,
        serverValue: value,
        baseRevision: args.revision,
        dirty: previous.draftValue !== value,
      }
      : { ...cleanField(value, args.revision), focused: previous.focused, error: previous.error };
  }
  return {
    session: args.session,
    revision: args.revision,
    fields,
    lastToken: state.lastToken,
    staleResponses: fresh ? 0 : state.staleResponses,
  };
}

/** 타이핑 — 발신하지 않는다. dirty 는 **서버 값과 다른가**로만 정한다. */
export function typeInto(state: DraftState, key: string, value: string): DraftState {
  const field = state.fields[key];
  if (field === undefined) return state;
  return {
    ...state,
    fields: {
      ...state.fields,
      [key]: { ...field, draftValue: value, dirty: value !== field.serverValue, error: "" },
    },
  };
}

/** 포커스·조합 표지 — 규칙 2 의 입력. */
export function markField(state: DraftState, key: string, patch: FieldPatch): DraftState {
  const field = state.fields[key];
  if (field === undefined) return state;
  return { ...state, fields: { ...state.fields, [key]: { ...field, ...patch } } };
}

/** 변이 발급 — 규칙 4. 반환 token 을 응답 정산에 그대로 싣는다. */
export function issueToken(state: DraftState, key: string): { state: DraftState; token: number } {
  const field = state.fields[key];
  const token = state.lastToken + 1;
  if (field === undefined) return { state: { ...state, lastToken: token }, token };
  return {
    state: {
      ...state,
      lastToken: token,
      fields: { ...state.fields, [key]: { ...field, pendingToken: token } },
    },
    token,
  };
}

export type Settlement =
  | { ok: true; session: string; token: number; key: string; serverValue?: string }
  | { ok: false; session: string; token: number; key: string; error: string };

/** 응답 정산 — 규칙 4·5·6. session·token 이 어긋나면 **아무것도 바꾸지 않고** stale 로 센다. */
export function settle(state: DraftState, result: Settlement): DraftState {
  const field = state.fields[result.key];
  if (field === undefined || result.session !== state.session || field.pendingToken !== result.token) {
    return { ...state, staleResponses: state.staleResponses + 1 };
  }
  if (!result.ok) {
    return {
      ...state,
      fields: { ...state.fields, [result.key]: { ...field, pendingToken: 0, error: result.error } },
    };
  }
  /* 성공이라도 Python 이 새 값을 확인해 준 경우에만 clean 으로 올린다 — 확인 없는 승격은
     「보낸 것이 곧 저장된 것」이라는 두 번째 판정자를 만든다. */
  if (result.serverValue === undefined) {
    return {
      ...state,
      fields: { ...state.fields, [result.key]: { ...field, pendingToken: 0, error: "" } },
    };
  }
  return {
    ...state,
    fields: {
      ...state.fields,
      [result.key]: {
        ...field,
        serverValue: result.serverValue,
        draftValue: result.serverValue,
        dirty: false,
        pendingToken: 0,
        error: "",
      },
    },
  };
}

/** 이 화면에 커밋되지 않은 편집이 있는가 — legacy `pendingFieldEdit` 의 후계. */
export function hasPendingEdits(state: DraftState): boolean {
  return Object.values(state.fields).some((field) => field.dirty);
}

/** 대기 중인 변이가 있는가(발신했으나 아직 정산 전). */
export function hasInFlight(state: DraftState): boolean {
  return Object.values(state.fields).some((field) => field.pendingToken !== 0);
}

/** 표시값 — 없는 키는 빈 문자열이 아니라 **loud** 다(계약 밖 키를 조용히 그리지 않는다). */
export function valueOf(state: DraftState, key: string): string {
  const field = state.fields[key];
  if (field === undefined) throw new Error(`편집 field '${key}' 가 스냅샷에 없습니다.`);
  return field.draftValue;
}

export function fieldError(state: DraftState, key: string): string {
  return state.fields[key]?.error ?? "";
}

/** 스냅샷이 실제로 든 값만 모은다 — 없는 키를 발명하지 않는다. */
export function editorServerValues(snapshot: Record<string, any>): ServerValues {
  const values: Record<string, string> = {
    [NAME_FIELD]: String(snapshot.name ?? ""),
    [PATTERN_FIELD]: String(snapshot.pattern ?? ""),
  };
  for (const row of (snapshot.rows || []) as Array<Record<string, any>>) {
    const index = Number(row.index);
    /* 두 select 는 초안을 두지 않으므로 여기 실리지 않는다(U6-C 리뷰 2) — 서버 값이 곧
       화면 값이고, 실패하면 재렌더가 그 값으로 되돌린다. 초안은 고정값 입력 하나다. */
    values[rowField(index, "const")] = String(row.const ?? "");
  }
  return values;
}

/** 세션 정체 — 편집 대상이 바뀌면 draft 를 들고 가지 않는다. */
export function editorSession(snapshot: Record<string, any>): string {
  return snapshot.is_draft ? "draft" : `job:${String(snapshot.editing_origin ?? "")}`;
}

export function editorRevision(snapshot: Record<string, any>): number {
  const revisions = snapshot.revisions || {};
  return Number(revisions.binding ?? 0) * 1000 + Number(revisions.template ?? 0);
}
