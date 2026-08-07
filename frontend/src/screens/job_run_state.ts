/* R4-03 실행 상태 reducer — 「이 응답이 지금 내가 기다리는 그 실행의 것인가」 하나를 든다.

   legacy `job.js` 는 이 질문을 묻지 않았다. 모듈 지역 `generating` 불리언과 `RESULT` 변수가
   있었고, 도착한 것은 무엇이든 지금 것이라고 가정했다. 실제로 그 가정이 깨지는 창이 셋 있다:

   1. `generate` 는 **성공일 때만** 반환 전에 full push 를 낸다. 덮어쓰기 필요·거절에는 그
      push 가 없다 — 그래서 "push 가 오면 끝난 것"으로 읽으면 그 두 갈래가 영영 진행 중이다.
   2. 덮어쓰기 확인 왕복은 호출을 **둘**로 만든다. 그 둘을 다른 실행으로 세면 첫 호출의 늦은
      응답이 둘째 응답을 덮는다.
   3. 진행 델타는 direct 반환과 다른 채널이라 순서 보장이 없다. 완료 뒤 도착한 앞선 델타가
      완료 결과를 진행 중으로 되돌린다(#415 가 실 게이트에서만 잡은 부류의 창이다).

   그래서 실행 정체를 **세 성분**으로 든다: 화면 세대(`screenEpoch`) · 세션 지문(`sessionKey`)
   · 실행 토큰(`runToken`). 셋이 전부 현재와 같을 때만 응답을 반영한다. 토큰은 Python 이
   되돌려 주는 불투명 문자열이고(`screen_job.py._run_token`), 우리는 그것을 만들기만 하지
   해석하지 않는다.

   **판정을 여기서 다시 하지 않는다**: status·level·title·summary·failures·evidence 수치는
   전부 Python 이 낸 값 그대로 통과한다. 이 파일이 정하는 것은 「반영하는가 버리는가」뿐이다. */

export type SessionKey = {
  job: string;
  data: string;
  out: string;
  sel: string;
  rules: string;
  /** 직전 런의 주체 — 지문 성분이 **아니라** 작업 축의 판독 보조다(개명 ≠ 파기). */
  own: string;
};

export type RunIdentity = {
  screenEpoch: number;
  sessionKey: SessionKey | null;
  runToken: string;
};

export type RunResult = Record<string, any>;
export type RunProgress = { done: number; total: number; run_token?: string };

export type JobRunState = {
  lastFull: Record<string, any> | null;
  progress: RunProgress | null;
  result: RunResult | null;
  /** 결과를 만든 그 실행의 세션 지문 — 강등·초기화 판정의 비교군. */
  resultFingerprint: SessionKey | null;
  running: boolean;
  active: RunIdentity | null;
  /** 방금 종료된 op 의 토큰 — terminal barrier 가 **자기 이름을 댈 수 있게** 남긴다.
   *  없으면 완료 뒤 늦은 델타가 「활성 실행 없음」으로 읽혀, 양성 경합(정상)과 미배선
   *  (결함)이 같은 문장을 낸다. 두 사건을 한 문장으로 접으면 진단이 죽는다. */
  finishedToken: string;
  screenEpoch: number;
  /** 버려진 응답의 진단 흔적. 조용히 버리면 「아무 일도 안 일어남」과 구분되지 않는다. */
  discarded: ReadonlyArray<{ kind: "direct" | "progress"; reason: string; token: string }>;
};

export function initialRunState(): JobRunState {
  return {
    lastFull: null, progress: null, result: null, resultFingerprint: null,
    running: false, active: null, finishedToken: "", screenEpoch: 0, discarded: [],
  };
}

/* 세션 지문 — legacy `sessionKey(s)` 의 성분·값을 그대로 옮긴다(U2 §2.18). 값의 출처가
   전부 Python 이라는 것이 요점이다: 표면이 경로·시트로 정체를 재조립하면 같은 판정이 두
   곳에 살고, 실제로 그렇게 샌 적이 있다(`data_source_label` 은 서로 다른 파일이 같은
   문자열이 된다 — 그래서 마운트 세대 `data_mount` 하나를 쓴다). */
export function sessionKeyOf(snapshot: Record<string, any> | null): SessionKey | null {
  if (snapshot === null || !snapshot.has_job) return null;
  return {
    job: String(snapshot.job_name ?? ""),
    data: String(snapshot.data_mount ?? ""),
    out: String(snapshot.out_dir ?? ""),
    sel: String(snapshot.selection_key ?? ""),
    rules: String(snapshot.rules_key ?? ""),
    own: String(snapshot.last_run_job ?? ""),
  };
}

function sameIdentity(a: SessionKey | null, b: SessionKey | null): boolean {
  if (a === null || b === null) return a === b;
  return a.job === b.job && a.data === b.data && a.out === b.out
    && a.sel === b.sel && a.rules === b.rules;
}

/** 새 사용자 의도마다 충돌 없는 불투명 토큰. 값에 의미를 싣지 않는다 — 대조만 한다. */
export function createTokenFactory(prefix = "run"): () => string {
  let serial = 0;
  return () => {
    serial += 1;
    return `${prefix}-${serial}-${Math.random().toString(36).slice(2, 10)}`;
  };
}

/* ------------------------------------------------------------------ 결과 수명 */

/** 결과 처분 — 성분별 2분기(U2 §2.18). legacy `disposeResultBySession` 의 후계다.
 *
 *  `exit` 는 초기화 갈래에서만 non-null 이고, 호출자가 그 한 줄을 로그에 잇는다. 합성 자체는
 *  여기서 하지 않는다 — 문안은 표현 계층이 소유하고 이 파일은 **무엇이 일어났는가**만 낸다. */
export type Disposal =
  | { kind: "keep" }
  | { kind: "stale" }
  | { kind: "reset"; exitOwner: string };

export function disposeBySession(
  state: JobRunState, prev: SessionKey | null, next: SessionKey | null,
): Disposal {
  if (state.result === null || prev === null) return { kind: "keep" };
  // 개명은 전환이 아니다 — 주체(`own`)가 이름을 추종하므로 job 성분이 갈려도 주체=열린
  // 작업이면 같은 작업이다. 이 한 줄이 없으면 이름만 바꿔도 결과가 통째로 사라진다.
  const jobSwitched = next === null || (prev.job !== next.job && next.own !== next.job);
  if (jobSwitched || (next !== null && prev.data !== next.data)) {
    return { kind: "reset", exitOwner: String(state.lastFull?.last_run_job ?? "") };
  }
  if (prev.job !== next.job || prev.out !== next.out
      || prev.sel !== next.sel || prev.rules !== next.rules) {
    return { kind: "stale" };
  }
  return { kind: "keep" };
}

/* ------------------------------------------------------------------ 전이 */

/** 사용자의 새 generate 의도. 여기서만 토큰이 새로 난다 — 덮어쓰기 확인 재호출은 아니다. */
export function beginRun(state: JobRunState, runToken: string): JobRunState {
  return {
    ...state,
    running: true,
    progress: null,
    finishedToken: "",
    active: {
      screenEpoch: state.screenEpoch,
      sessionKey: sessionKeyOf(state.lastFull),
      runToken,
    },
  };
}

/** 확인 취소 — op 를 끝내되 **직전 결과를 임의로 지우지 않는다**(사용자가 치우라고 한 적 없다). */
export function endRun(state: JobRunState): JobRunState {
  const token = state.active === null ? state.finishedToken : state.active.runToken;
  return { ...state, running: false, active: null, finishedToken: token, progress: null };
}

function stale(state: JobRunState, kind: "direct" | "progress", reason: string, token: string): JobRunState {
  return { ...state, discarded: [...state.discarded, { kind, reason, token }] };
}

/** 현재 active op 의 것인가 — 세 성분 전부가 같아야 한다. */
function belongsToActive(state: JobRunState, token: string): string {
  const active = state.active;
  // terminal barrier 를 **먼저** 본다: 완료 직후의 늦은 델타는 정상 경합이고, 그것을
  // 「활성 실행 없음」으로 접으면 배선이 아예 안 된 결함과 같은 문장이 된다.
  if (token !== "" && token === state.finishedToken) return "이미 종료된 실행입니다";
  if (active === null) return "활성 실행이 없습니다";
  if (active.screenEpoch !== state.screenEpoch) return "화면 세대가 바뀌었습니다";
  if (active.runToken !== token) return "다른 실행의 토큰입니다";
  if (!sameIdentity(active.sessionKey, sessionKeyOf(state.lastFull))) return "세션이 바뀌었습니다";
  return "";
}

/** full push — 세션 사실만 갱신한다. **결과를 만들지도 덮지도 않는다**. */
export function acceptFull(state: JobRunState, snapshot: Record<string, any>): JobRunState {
  const prev = sessionKeyOf(state.lastFull);
  const next = sessionKeyOf(snapshot);
  // 실행 중에는 처분하지 않는다 — 런이 스스로 만든 세션 변화(`last_run_job` 스탬프)로
  // 자기 결과를 강등시키는 자기모순을 막는다(legacy `if (!generating)` 의 후계).
  if (state.running) return { ...state, lastFull: snapshot };
  const disposal = disposeBySession(state, prev, next);
  const base = { ...state, lastFull: snapshot };
  if (disposal.kind === "reset") {
    return { ...base, result: null, resultFingerprint: null, progress: null };
  }
  if (disposal.kind === "stale" && state.result !== null) {
    return { ...base, result: { ...state.result, stale: true } };
  }
  return base;
}

/** 진행 델타 — 현재 op 의 `progress` 만 갱신한다. `lastFull` 을 절대 덮지 않는다. */
export function acceptProgress(state: JobRunState, progress: RunProgress): JobRunState {
  const token = String(progress.run_token ?? "");
  const mismatch = belongsToActive(state, token);
  if (mismatch !== "") return stale(state, "progress", mismatch, token);
  if (!state.running) return stale(state, "progress", "이미 종료된 실행입니다", token);
  return { ...state, progress: { ...progress } };
}

/** direct 응답 — 현재 op 의 outcome 을 싣는다. 늦은 것은 진단 가능하게 버린다.
 *
 *  `needs_overwrite` 는 **op 를 끝내지 않는다**: 같은 토큰으로 확인 재호출이 이어진다. */
export function acceptDirect(state: JobRunState, result: RunResult): JobRunState {
  const token = String(result.run_token ?? "");
  const mismatch = belongsToActive(state, token);
  if (mismatch !== "") return stale(state, "direct", mismatch, token);
  if (result.needs_overwrite === true) return state;
  return {
    ...state,
    running: false,
    active: null,
    finishedToken: token,
    progress: null,
    result,
    resultFingerprint: sessionKeyOf(state.lastFull),
  };
}

/** 사용자의 명시 파기 — 로그에 흔적을 남기지 않는다(치우라는 행동을 반만 들으면 안 된다). */
export function closeResult(state: JobRunState): JobRunState {
  return { ...state, result: null, resultFingerprint: null, progress: null };
}

/** 화면 폐기·재진입 — 세대를 올려 앞선 실행의 모든 응답을 한 번에 남으로 만든다. */
export function bumpEpoch(state: JobRunState): JobRunState {
  return {
    ...state, screenEpoch: state.screenEpoch + 1,
    running: false, active: null, finishedToken: "", progress: null,
  };
}

/** 이 결과가 지금 열린 작업의 것인가 — 판정에 드는 두 값 다 Python 이 낸 스냅샷 값이다. */
export function isForeignResult(state: JobRunState): boolean {
  const full = state.lastFull;
  if (full === null || state.result === null) return false;
  const owner = String(full.last_run_job ?? "");
  return !(owner && full.job_name && owner === String(full.job_name));
}
