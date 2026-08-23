/* R4-03 실행 표면 — 사전검증·거울·재진술·게이트·저장 폴더·액션바·진행/결과 수명주기의
   단일 owner. legacy `js/screens/job.js` 의 실행 remainder 전체가 여기로 온다.

   ## 이 파일이 legacy 에서 바꾼 것 하나

   상태다. legacy 는 모듈 지역 `LAST`·`RESULT`·`generating`·`lastSessionKey` 넷을 들고
   도착한 것을 무엇이든 지금 것이라고 가정했다. 여기서는 그 넷이 `job_run_state.ts` 의 한
   reducer 로 합쳐지고, **귀속 판정**(화면 세대·세션 지문·실행 토큰)이 반영 여부를 정한다.
   나머지는 전부 그대로다 — 판정·수치·문안의 출처는 여전히 Python 이고, 이 층은 그것을
   자리에 놓기만 한다.

   ## 순수 합성기 넷은 표면이 아니라 계약이다

   `overwriteBody`·`guardBody`·`resultExitLine`·`selectionLine` 은 인자만 읽는 순수 함수다.
   실앱 게이트가 산출을 되읽어 파괴적 확인·퇴장 한 줄의 조용한 문안 드리프트를 막는다 —
   그래서 컨트롤러 표면에 이름째 남는다(삭제 회귀를 핀이 잡는다). */

import { Fragment, createElement, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { BridgeClient } from "../runtime/client.ts";
import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import { PathActions } from "./path_actions.ts";
import type { PreviewRequest, ScreenPorts } from "./ports.ts";
import type { JobScreenModel, ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import {
  acceptDirect, acceptFull, acceptProgress, beginRun, bumpEpoch, closeResult,
  createTokenFactory, disposeBySession, endRun, initialRunState, sessionKeyOf,
} from "./job_run_state.ts";
import type { JobRunState } from "./job_run_state.ts";

type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
  open(id: string, spec?: Obj): void;
  close(id: string): void;
};

export type JobRunControllerDeps = {
  runtime: ScreenRuntime;
  client: BridgeClient;
  ports: ScreenPorts;
  services: ServiceHandoffPorts;
  modal: ModalPort;
  /** 항행과 **관측**. `currentScreen` 은 셸 상태기계의 관측면을 그대로 통과한 값이라
   *  「지금 어느 화면인가」의 판정이 여기서 다시 조립되지 않는다(랜딩 전에는 `null`). */
  navigation: { go(screen: string): void; currentScreen(): string | null };
  doc: Document;
  notify(message: string): void;
  /** 선택 재진술 한 줄의 **공유 합성기**(`js/guard.js`) — 재진술 블록과 가드 모달이 같은
   *  수치를 따로 조립하면 문안이 갈려 모달이 화면 재진술과 모순된다. 주입으로 받는 이유는
   *  이 층이 legacy `.js` 그래프를 직접 import 하지 않기 위해서다(합성 루트가 건넨다). */
  selectionLine(count: number, filterActive: unknown, inDef: unknown, extra: unknown): string;
};

/** 게이트 지목의 **어휘 지도** — 링1 이 낸 사유 축 이름 → 그 축을 소유한 구획 캡션.
 *  판정(무엇이 막는가·무엇이 먼저인가)은 게이트가 하고 여기는 이름을 자리로 옮기기만 한다.
 *  표면이 상태를 다시 읽어 지목을 만들면 서열이 두 곳에 살고, 실제로 그렇게 샜다. */
const GATE_ZONE: Record<string, string> = {
  no_data: "현재 데이터 · ",
  no_rows: "현재 데이터 · ",
  no_candidates: "이 데이터에 사용할 문서 · ",
  no_job: "이 데이터에 사용할 문서 · ",
  drift: "본문 확인 · ",
  name_tokens: "본문 확인 · ",
  // 템플릿 축은 **빈 문자열**이다 — 그 축을 소유하던 「선택한 작업」 존은 죽었고 복구는
  // 같은 액션바 줄의 연결 상태·재연결이 곁에서 진다. 없는 구획을 가리키느니 안 가리킨다.
  template_missing: "",
  template_unreadable: "",
};

const DELIVERY_POLICIES = [
  ["ADD_SUFFIX", "같은 이름이 있으면 번호 붙이기"],
  ["FAIL", "같은 이름이 있으면 만들지 않기"],
  ["OVERWRITE_EXPLICIT", "기존 파일 덮어쓰기"],
] as const;

export const DELIVERY_DISPOSITION_COPY: Record<string, string> = {
  WRITE_NEW: "새 파일",
  WRITE_ADD_SUFFIX: "번호를 붙인 새 파일",
  WRITE_OVERWRITE: "기존 파일 덮어쓰기",
};

/* ------------------------------------------------------------------ 순수 합성기 */

/** 덮어쓰기 확인 본문 — 총량·파괴분·신규분을 종류별로 재진술한다(결정 36). */
export function overwriteBody(res: Obj): string {
  const names = (res.conflict_names || []) as string[];
  const more = res.conflict_more ? `\n외 ${res.conflict_more}개` : "";
  return `${res.total}건을 생성합니다. 이 중 ${res.overwrite_count}건이 기존 파일을 덮어씁니다:\n`
    + `${names.join("\n")}${more}\n\n나머지 ${res.new_count}건은 새 파일입니다.`;
}

/** 파괴 전이 가드 본문 — 손실 열거는 **실제로 파기되는 집합**과 일치해야 한다
 *  (과경고도 누락도 거짓말이다). 선택 한 줄은 주입받은 공유 합성기가 낸다. */
export function composeGuardBody(
  selectionLine: JobRunControllerDeps["selectionLine"],
): (g: Obj, verbPhrase: string) => string {
  return (g, verbPhrase) => {
    const lost = [selectionLine(g.sel_count, g.filter_active, g.in_def, g.extra)];
    if (g.filter_parts > 0) lost.push(`필터 정의(${g.filter_parts}개 조건)`);
    const stash = g.filter_parts > 0
      ? "\n필터 정의는 이 데이터로 돌아오면 「직전 필터 재적용」으로 되살릴 수 있습니다." : "";
    return `${verbPhrase} 이 세션의 선택이 사라집니다.\n`
      + `사라지는 것: ${lost.join(" · ")}.${stash}`;
  };
}

/** 퇴장 한 줄 — **수치를 여기서 다시 조립하지 않는다**(#363 리뷰 P2). `total` 은 대상 수이지
 *  만들어진 수가 아니라, 취소된 배치에서 「N건 생성」이 유일하게 남는 거짓 진술이 된다.
 *  수치 몸통은 Python 이 낸 `exit_summary` 를 그대로 쓴다. */
export function resultExitLine(r: Obj | null, owner: string): string {
  if (!r || r.running || r.rejected) return "";
  const who = owner ? `'${owner}' ` : "";
  const dir = r.out_dir ? ` — ${r.out_dir}` : "";
  // 요약 없는 실행 결과는 조용히 넘기지 않는다 — 이 줄이 유일한 흔적이라 침묵하면 소멸
  // 자체가 흔적 없이 사라진다. 수치를 지어내지 않고 **모른다고 적는다**.
  const body = r.exit_summary || "생성 결과가 세션에서 물러났습니다(수치 요약 없음)";
  return `${who}${body}${dir}`;
}

/** 실행 표면이 작업대인가 — 판정은 Python 이 낸 `run_action.key` 하나를 읽는다. 표면이
 *  확장자·매체를 다시 읽어 분기하면 같은 판정이 두 곳에 산다(F6 판정 D). */
function isCopyWork(s: Obj | null): boolean {
  return !!(s && s.run_action && s.run_action.key === "workbench");
}

function isManagedHwpx(s: Obj | null): boolean {
  return s?.managed_hwpx === true;
}

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/* ------------------------------------------------------------------ 컨트롤러 */

type UiState = { log: readonly string[]; logOpen: boolean };

type TemplateChangeUi = { inFlight: boolean; requestId: string | null; notice: string };

export function createJobRunController(deps: JobRunControllerDeps) {
  const model = deps.runtime.model<JobScreenModel>("job");
  const nextToken = createTokenFactory();

  let run: JobRunState = initialRunState();
  let ui: UiState = { log: [], logOpen: false };
  /* 템플릿 변경 확인·적용(S3-09)의 화면 local 상태 — 진행 여부·요청 키·적용 재진술.
     요청 키는 prepare intent 의 재전송 단위다: 진행 중 중복 클릭은 무시(한 요청으로 수렴),
     전송 실패로 남은 키는 다음 클릭이 **같은 키로 재전송**, 성공 뒤 클릭만 새 키(=새 intent). */
  let tpl: TemplateChangeUi = { inFlight: false, requestId: null, notice: "" };
  const listeners = new Set<Listener>();
  let attached: { onFull(s: unknown): void; onProgress(p: unknown): void } | null = null;
  let releaseModel: (() => void) | null = null;
  let lastFullSeen: unknown = null;
  let lastProgressSeen: unknown = null;

  function emit(): void { for (const listener of [...listeners]) listener(); }
  function setRun(next: JobRunState): void { run = next; emit(); }
  function setTpl(next: TemplateChangeUi): void { tpl = next; emit(); }

  /** 실행 기록 — 이 화면의 유일한 비모달 사건 채널이라 실패가 여기로 착지한다. */
  function log(message: string): void {
    const ts = new Date().toLocaleTimeString("ko-KR", { hour12: false });
    ui = { ...ui, log: [...ui.log, `[${ts}] ${message}`] };
    emit();
  }

  function snapshot(): Obj | null {
    return run.lastFull;
  }

  const guardBody = composeGuardBody(deps.selectionLine);

  async function dispatch(action: any, payload: Obj = {}): Promise<Obj> {
    return (expectHostValue(
      await deps.client.dispatch("job", action, payload as any), `job/${String(action)}`,
    ) ?? {}) as Obj;
  }

  /* ---- 스냅샷 유입: full 은 세션 사실, progress 는 현재 op 만 ---- */
  function ingestFull(value: unknown): void {
    const before = run;
    const next = acceptFull(before, value as Obj);
    const prevKey = sessionKeyOf(before.lastFull);
    const nextKey = sessionKeyOf(value as Obj);
    const disposal = disposeBySession(before, prevKey, nextKey);
    /* 템플릿 변경 UI 상태(재전송 키·적용 재진술)는 세션 정체를 따른다(리뷰 P2) — 작업이
       갈리면 A 의 「적용했습니다」가 B 밑에 남는 남의 재진술이 된다. 개명은 전환이 아니다
       (`disposeBySession` 과 같은 술어). emit 은 아래 setRun 이 겸한다. */
    const tplSwitched = prevKey !== null
      && (nextKey === null || (prevKey.job !== nextKey.job && nextKey.own !== nextKey.job));
    if (tplSwitched && (tpl.requestId !== null || tpl.notice)) {
      tpl = { ...tpl, requestId: null, notice: "" };
    }
    /* 퇴장 한 줄은 **초기화 갈래에서만** 선다. 그 갈래는 legacy `resetGenResult` 와 같이
       실행 기록을 **먼저 비운다** — 안 비우면 죽은 세션의 줄이 다음 세션 밑에 그대로 쌓여
       「이어지는 한 실행」으로 읽힌다(마지막 줄만 보는 계약은 이 누적을 통과시킨다).
       문안은 리셋 **전** 상태에서 조립하고, 로그는 리셋 **뒤에** 적는다(순서를 바꾸면 방금
       적은 줄이 곧바로 지워진다). `ui` 를 `setRun` 앞에 두어 emit 한 번에 함께 실린다. */
    const resetting = !before.running && disposal.kind === "reset";
    const line = resetting ? resultExitLine(before.result, disposal.exitOwner) : "";
    if (resetting) ui = { log: [], logOpen: false };
    setRun(next);
    if (line) log(line);
    syncPreviewOpen(next.lastFull);
  }

  /** 확인 면의 개폐를 상태에 맞춘다(legacy `closePreviewIfOpen` 동등). Python 이 닫았다고
   *  말했는데 면이 떠 있으면 그 면은 **남의 값**을 그리고 있다 — 작업 전환·데이터 교체가
   *  백엔드에서 닫는 원격 닫힘이 그 경로다. 개폐 주인은 Python 소유 `preview.open` 이고
   *  이 층은 집행만 한다.
   *
   *  열려 있지 않은 대상의 `close` 는 스택에 없어 아무 일도 하지 않으므로 DOM 에 열림
   *  여부를 되묻지 않는다 — 상태의 진실은 스냅샷이지 클래스가 아니다. */
  function syncPreviewOpen(full: Obj | null): void {
    if (!(full && full.preview && full.preview.open)) deps.modal.close("previewSheet");
  }

  function pump(): void {
    const next = model.getSnapshot();
    if (next.full !== null && next.full !== lastFullSeen) {
      lastFullSeen = next.full;
      lastProgressSeen = null;
      ingestFull(next.full);
      attached?.onFull(next.full);
    }
    if (next.progress !== null && next.progress !== lastProgressSeen) {
      lastProgressSeen = next.progress;
      setRun(acceptProgress(run, next.progress as any));
      attached?.onProgress(next.progress);
    }
  }

  /* ---- 생성 ---- */
  async function doGenerate(token: string, confirmOverwrite: boolean): Promise<void> {
    // 커밋은 대기 중인 존 변이 뒤에 선다(8R P1). 덮어쓰기 확인 뒤 재호출도 같은 관문을
    // 지나되 그 시점엔 체인이 비어 있어 즉시 통과한다.
    await deps.ports.jobData.current().flushPendingEdits();
    const res = (expectHostValue(
      await deps.client.invoke("generate", "job", confirmOverwrite, token), "generate",
    ) ?? {}) as Obj;

    // 토큰 반향이 없거나 빈 문자열이면 계약 위반이다 — 조용히 넘기면 귀속 판정 전체가
    // 무의미해지므로 시끄럽게 세운다(그 상태로 결과를 그리면 남의 응답도 그린다).
    if (typeof res.run_token !== "string" || res.run_token === "") {
      setRun(endRun(run));
      const message = "실행 응답에 상관 토큰이 없습니다(계약 위반) — 결과를 신뢰할 수 없습니다.";
      deps.notify(message);
      log(message);
      return;
    }

    if (res.needs_overwrite === true) {
      setRun(acceptDirect(run, res));
      // 조용한 덮어쓰기 금지 — 수치 재진술 후 확인 시에만 **같은 토큰으로** 재호출한다.
      const ok = await deps.modal.confirm({
        title: "덮어쓰기 확인", body: overwriteBody(res),
        confirmLabel: "덮어쓰고 생성", cancelLabel: "취소", danger: true,
      });
      if (ok) { await doGenerate(token, true); return; }
      setRun(endRun(run));
      log("생성을 취소했습니다.");
      return;
    }

    if (res.ok === false && res.error) {
      // 실행 전 거절 — 결과 자리를 비워 두면 눌렀는데 아무 일도 없는 것으로 읽힌다.
      setRun(acceptDirect(run, {
        rejected: true, level: res.level === "danger" ? "danger" : "warn",
        title: "생성하지 않았습니다", summary: String(res.error), run_token: res.run_token,
      }));
      log(String(res.error));
      return;
    }
    setRun(acceptDirect(run, res));
  }

  async function startGenerate(): Promise<void> {
    const s = snapshot();
    // 방식 판정은 **첫 await 앞**에서 끝난다 — 이미 읽은 스냅샷만 쓰므로 미룰 이유가 없고,
    // 미루면 아래 진입 잠금이 작업대 갈래까지 잠그게 된다(그쪽은 실행이 아니다).
    const key = (s && s.run_action && s.run_action.key) || "generate";
    if (key === "workbench") {
      await deps.ports.jobData.current().flushPendingEdits();
      const res = await dispatch("open_workbench", {});
      if (res.ok) { deps.navigation.go("workbench"); return; }
      log(String(res.error || "작업대를 열지 못했습니다."));
      return;
    }
    /* S6-05(#812): managed 조기 return(조용한 로그, #729 잔여위험 2)은 철거됐다 — managed
       create 도 legacy 와 같은 generate 왕복을 탄다. 판정은 전부 백엔드가 진다: 준비 미달·
       stale·admission 거절은 결과 dict 의 rejected 구획으로 시끄럽게 돌아온다(재조립 0). */

    /* 진입 직렬화는 **첫 await 앞**에 선다. legacy 는 커밋 관문(`flushPendingEdits`) 뒤에
       `generating` 을 세웠고 그 창에 둘째 클릭이 들어올 수 있었다 — 토큰이 없던 때는 둘째가
       백엔드 자물쇠에 거절당하고 첫 런의 결과가 그대로 그려져 무해했다. **귀속이 생기면서
       그 창의 대가가 바뀐다**: 둘째의 `beginRun` 이 첫 런의 정체를 덮어써, 실제로 만들어진
       문서의 결과가 남의 것으로 폐기되고 화면엔 「이미 생성 중」만 남는다. 문서는 생겼는데
       사용자는 그 사실을 못 듣는 경로다.
       커밋 관문은 사라지지 않고 `doGenerate` 첫 줄이 그대로 진다 — 발신 앞에 서는 것이
       계약이지 잠금 앞에 서는 것이 계약은 아니다. */
    if (run.running) return;
    const token = nextToken();
    setRun(beginRun(run, token));
    log("생성 요청");
    try {
      await doGenerate(token, false);
    } catch (error) {
      setRun(endRun(run));
      log(`생성하지 못했습니다: ${String((error as Obj)?.message ?? error)}`);
    }
  }

  /* ---- 확인 면 ---- */
  async function openPreview(request?: PreviewRequest): Promise<void> {
    const o = request || {};
    try {
      await deps.ports.jobData.current().flushPendingEdits();
      await dispatch("preview_open", { at: o.at || 0 });
    } catch (error) {
      log(`미리보기를 열지 못했습니다: ${String((error as Obj)?.message ?? error)}`);
      return;
    }
    // 왕복 중 화면을 떠났으면 열지 않고 상태를 되돌린다 — 남는 「열림」 상태가 다음
    // 복귀에서 아무 트리거 없이 면을 띄운다. 「지금 어느 화면인가」는 셸 상태기계가 답한다:
    // `#scr-job` 의 `.on` 을 직접 읽으면 같은 판정이 두 곳에 살고, React 서브트리가
    // legacy 화면 루트를 붙드는 간선이 된다(정적 폐포가 그 자리를 문다).
    if (deps.navigation.currentScreen() !== "job") {
      void dispatch("preview_close", {});
      return;
    }
    deps.modal.open("previewSheet", {
      returnFocus: previewTrigger ?? deps.doc.getElementById("jobPreviewOpen"),
      initialFocus: deps.doc.getElementById("previewClose"),
      onClose: () => { void dispatch("preview_close", {}); },
    });
    if (o.focusTarget) focusPreviewTarget(o.focusTarget);
  }

  let previewTrigger: HTMLElement | null = null;

  /** 복귀 초점 = 떠났던 그 행의 「수정」. 행 DOM 은 push 재렌더가 만드므로(브리지 반환과
   *  독립 채널) 유한 재시도 후 폴백은 initialFocus 다. */
  function focusPreviewTarget(target: string): void {
    let tries = 0;
    const find = (): HTMLElement | null => (target === "filename/filenamePattern"
      ? deps.doc.getElementById("previewFixFilename")
      : deps.doc.querySelector(
        `#previewRows [data-act="preview-fix"][data-field="${CSS.escape(target.slice("binding/".length))}"]`));
    const step = (): void => {
      const el = find();
      if (el && el.offsetParent !== null) { el.focus(); return; }
      if (++tries > 3) return;
      requestAnimationFrame(step);
    };
    step();
  }

  /** 행별·파일 이름 「수정」의 단일 경로 — `at` 은 `Modal.close` 가 `preview_close` 를
   *  발화하기 **전에** 읽는다: pos 는 닫힘에 0 으로 리셋되므로 순서를 바꾸면 복귀가 늘
   *  첫 행으로 선다(발신 순서 규약). */
  async function previewFix(target: string, evidence: Obj): Promise<void> {
    const at = ((snapshot()?.preview) || {}).pos || 0;
    deps.modal.close("previewSheet");
    // 조준은 editor 가 **자기 진입 문맥으로** 한다(#789). 여기서 port 너머로 부르지 않는다 —
    // 종전에는 port 표면에 없는 메서드를 `typeof` 로 물어보고 없으면 조용히 지나가서,
    // deep-link 초점이 한 번도 선 적이 없었다.
    await openEditForRepair({
      entry_reason: "preview_result", target, evidence,
      return_context: { surface: "preview", reopen_drawer: true, preview_index: at },
    });
  }

  function openEditForRepair(context: Obj): Promise<boolean> {
    const s = snapshot();
    if (!s || !s.job_name) return Promise.resolve(false);
    return Promise.resolve(
      deps.ports.editorEntry.current().openGuarded(s.job_name, context) as boolean,
    );
  }

  /** exact target 을 지목한 진입은 그 문맥을 editor 에 넘긴다 — **조준은 editor 가** 한다(#789).
   *
   *  종전에는 여기서 port 너머로 `aimAt` 을 부르려 했는데 그 메서드는 `EditorEntryPort` 표면에
   *  없었고, `typeof` 로 물어보고 없으면 조용히 지나가는 형상이라 초점이 한 번도 선 적이 없었다.
   *  진입 문맥은 이미 목표를 담아 editor 에 도착하므로 물어볼 곳은 바깥이 아니라 그쪽이다. */
  function openBindingRequirement(exactTarget: string, displayLabel: string): Promise<boolean> {
    return openEditForRepair({
      entry_reason: "document_browser_repair",
      target: exactTarget,
      evidence: { "입력이 필요한 항목": displayLabel },
      return_context: { surface: "data" },
    });
  }

  /* ---- 파괴 전이 가드 — 무장 판정은 guard_state **실시간 질의**다(스냅샷 캐시는
     generate 무푸시 경로·왕복 지연에서 stale — 양방향 오판). true=진행, false=머무르기. */
  async function confirmDestructiveIfArmed(
    title: string, verbPhrase: string, confirmLabel: string,
  ): Promise<boolean> {
    const g = await dispatch("guard_state", {});
    if (!g || !g.armed) return true;
    return deps.modal.confirm({
      title, body: guardBody(g, verbPhrase), confirmLabel, cancelLabel: "취소",
    });
  }

  const controller = {
    model,
    client: deps.client,
    notify: deps.notify,
    subscribe(listener: Listener): () => void {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    getRun: (): JobRunState => run,
    getUi: (): UiState => ui,
    getTemplateChange: (): TemplateChangeUi => tpl,

    /* 순수 합성기 — 실앱 게이트가 산출을 되읽는다(이름째 표면에 남는 이유). */
    overwriteBody, guardBody, resultExitLine,
    selectionLine: deps.selectionLine,
    async resolveExecution(): Promise<void> {
      try {
        await dispatch("resolve_execution", {});
      } catch (error) {
        log(`\ud604\uc7ac \uc124\uc815\uc744 \ud655\uc778\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4: ${String(error)}`);
      }
    },
    async recoverRecordIssue(target: Obj): Promise<void> {
      try {
        const result = await dispatch('recover_record_issue', { target });
        const element = (
          deps.doc.getElementById(String(result.element_id || ''))
          || deps.doc.getElementById(String(result.fallback_element_id || ''))
        );
        if (!element) throw new Error('문제 위치가 현재 표에 없습니다.');
        element.scrollIntoView?.({ block: 'center' });
        element.focus();
      } catch (error) {
        log(`문제 위치로 이동하지 못했습니다: ${String(error)}`);
      }
    },
    confirmDestructiveIfArmed, log,

    /** 결과 3태 구획의 **프로브 입구**(F4) — legacy 파사드가 지던 이름 그대로다.
     *  실앱 게이트가 Python 이 내는 결과 dict 를 그대로 흘려 태·강등·증거 접힘이 실
     *  WebView2 에서 서는지 되읽는다. 귀속 판정(`acceptDirect`)을 지나지 **않는다**:
     *  이 입구는 실행이 아니라 렌더를 겨누고, 토큰 없는 dict 를 넣는 것이 그 시험의 요지다. */
    renderResult(res: Obj): void {
      setRun({ ...run, result: res, resultFingerprint: sessionKeyOf(run.lastFull), running: false });
    },
    markResultStale(): void {
      if (run.result === null) return;
      setRun({ ...run, result: { ...run.result, stale: true } });
    },
    startGenerate,
    openBindingRequirement,
    async cancelGeneration(): Promise<void> {
      await dispatch("cancel_generation", {});
      log("중단 요청: 진행 중인 문서를 마친 뒤 미착수 건을 중단합니다.");
    },
    closeResult(): void {
      /* legacy `resetGenResult` 동등 — 명시 파기는 결과만이 아니라 **그 실행의 기록까지**
         치운다. 로그가 남으면 치우라는 행동을 반만 들은 것이 되고, 다음 실행의 첫 줄이 남의
         실행 끝줄 밑에 붙어 「이어지는 한 세션」으로 읽힌다. 펼침은 그 세션의 의사표시라
         함께 접는다. `log`·`logOpen` 은 JobRunState 가 아니라 UiState 라 reducer 밖이다. */
      ui = { log: [], logOpen: false };
      setRun(closeResult(run));
      // S6-05: managed 화면에선 #jobGenBtn 이 숨어 있다 — 눌렀던 create 로 초점을 되돌린다.
      const managedButton = deps.doc.getElementById(
        "jobManagedCreate",
      ) as HTMLButtonElement | null;
      const button = deps.doc.getElementById("jobGenBtn") as HTMLButtonElement | null;
      if (managedButton && !managedButton.disabled) managedButton.focus();
      else if (button && !button.disabled) button.focus();
      else deps.doc.getElementById("jobResultZone")?.focus();
    },
    async selectFailed(): Promise<void> {
      const res = await dispatch("select_failed", {});
      const count = Number(res.selected || 0);
      log(count
        ? `실패한 ${count}건만 선택했습니다. 그대로 다시 생성하면 이 건만 만듭니다.`
        : "다시 만들 실패 건이 남아 있지 않습니다(데이터나 작업이 그사이 바뀌었습니다).");
    },
    openRenameRules(): void {
      const s = snapshot();
      if (!s || !s.job_name) { log("작업이 선택돼 있지 않습니다."); return; }
      const owner = String(s.last_run_job || s.job_name);
      if (owner !== String(s.job_name)) {
        log(`이 결과는 '${owner}' 실행입니다. 지금 열린 작업이 달라 파일 이름 규칙을 열지 않았습니다.`);
        return;
      }
      const result = (run.result || {}) as Obj;
      deps.ports.editorEntry.current().openGuarded(owner, {
        entry_reason: result.status === "failed" ? "run_failure" : "output_result",
        section: "filename",
        evidence: {
          "이 실행": String(result.title || "").trim(),
          "사용한 판본": result.revisions
            ? `템플릿 r${result.revisions.template} · 연결 r${result.revisions.binding}` : "",
        },
        return_context: { surface: "result" },
      });
    },
    async pickOutputFolder(): Promise<void> {
      const result = expectHostValue(
        await deps.client.invoke("pick_output_folder", "job"), "pick_output_folder");
      if (result === null || result === undefined) return;
      const text = String(result);
      if (text.startsWith("ERROR:")) { log(`폴더 오류: ${text.slice(6).trim()}`); return; }
      log(`저장 폴더: ${text}`);
    },
    async setDeliveryCollision(policy: string): Promise<void> {
      if (policy === "OVERWRITE_EXPLICIT") {
        const confirmed = await deps.modal.confirm({
          title: "기존 파일 덮어쓰기",
          body: "같은 이름의 파일이 있으면 기존 파일을 덮어씁니다.",
          confirmLabel: "덮어쓰기 사용", cancelLabel: "취소", danger: true,
        });
        if (!confirmed) return;
      }
      try {
        await dispatch("set_delivery_collision", { collision_policy: policy });
      } catch (error) {
        log(`충돌 처리를 바꾸지 못했습니다: ${String(error)}`);
      }
    },
    async refreshDelivery(): Promise<void> {
      try {
        await dispatch("refresh_delivery", {});
      } catch (error) {
        log(`생성 예정 문서를 다시 확인하지 못했습니다: ${String(error)}`);
      }
    },
    relinkActive(): void {
      const s = snapshot();
      if (s && s.job_name) void deps.ports.jobRelinkFlow.current().relinkTemplateFor(String(s.job_name));
    },
    /* ---- 템플릿 변경 확인·적용(S3-09) — 판정·token 발급은 Python, 여기는 재전송 규율만 ---- */
    async templateCheck(): Promise<void> {
      if (tpl.inFlight) return; // 중복 클릭 = 진행 중인 같은 요청으로 수렴(새 intent 아님)
      const owner = String(snapshot()?.job_name || "");
      const requestId = tpl.requestId ?? newTplRequestId();
      setTpl({ inFlight: true, requestId, notice: "" });
      try {
        await dispatch("template_check", { request_id: requestId });
        setTpl({ inFlight: false, requestId: null, notice: "" }); // 성공 — 다음 클릭은 새 intent
      } catch (error) {
        // 전송 실패 — 키를 남겨 다음 클릭이 같은 키로 재전송. 단 그사이 작업이 갈렸으면
        // 키는 남의 intent 라 버린다(리뷰 P2 동류 — 상태는 세션 정체를 따른다).
        const still = String(snapshot()?.job_name || "") === owner;
        setTpl({ inFlight: false, requestId: still ? requestId : null, notice: "" });
        log(`변경사항 확인에 실패했습니다: ${String(error)}`);
      }
    },
    async templateApply(token: string): Promise<void> {
      if (tpl.inFlight) return;
      const owner = String(snapshot()?.job_name || "");
      setTpl({ ...tpl, inFlight: true });
      try {
        const res = await dispatch("template_apply", { change_token: token });
        // 응답이 오는 사이 작업이 갈렸으면 재진술을 싣지 않는다 — A 의 적용 결과가 B 의
        // 구획에 앉는 경로 차단(리뷰 P2).
        const still = String(snapshot()?.job_name || "") === owner;
        setTpl({ inFlight: false, requestId: null, notice: still ? applyNotice(res) : "" });
      } catch (error) {
        setTpl({ ...tpl, inFlight: false });
        log(`변경사항 적용에 실패했습니다: ${String(error)}`);
      }
    },
    openPreviewFrom(trigger: HTMLElement | null): void {
      previewTrigger = trigger;
      void openPreview({});
    },
    closePreview(): void { deps.modal.close("previewSheet"); },
    previewMove(delta: number): void { void dispatch("preview_move", { delta }); },
    previewBlankOnly(value: boolean): void {
      void dispatch("preview_blank_only", { value }).catch((error) =>
        log(`빈 값 건만 보기를 바꾸지 못했습니다: ${String(error)}`));
    },
    previewApprove(previewToken?: string): void {
      void dispatch("preview_approve", previewToken ? { preview_token: previewToken } : {}).catch((error) =>
        log(`확인을 저장하지 못했습니다: ${String(error)}`));
    },
    previewEdit(): void {
      deps.modal.close("previewSheet");
      void openEditForRepair({
        entry_reason: "preview_result",
        evidence: { "보고 있던 행": String(deps.doc.getElementById("previewPos")?.textContent || "").trim() },
        return_context: { surface: "preview", reopen_drawer: true },
      });
    },
    previewFixField(field: string): Promise<void> {
      const row = ((snapshot()?.preview || {}).rows || []).find((r: Obj) => r.name === field) || {};
      return previewFix(`binding/${field}`, {
        "보고 있던 행": String(deps.doc.getElementById("previewPos")?.textContent || "").trim(),
        "필드": field,
        "본 값": row.value || "(빈 값)",
      }).catch((error) => log(`수정으로 이동하지 못했습니다: ${String(error)}`));
    },
    previewFixFilename(): Promise<void> {
      return previewFix("filename/filenamePattern", {
        "보고 있던 행": String(deps.doc.getElementById("previewPos")?.textContent || "").trim(),
        "파일 이름": String(deps.doc.getElementById("previewFilename")?.textContent || "").trim(),
      }).catch((error) => log(`수정으로 이동하지 못했습니다: ${String(error)}`));
    },
    openRepair(kind: "fix-mapping" | "fix-filename"): void {
      void openEditForRepair({
        entry_reason: "document_browser_repair",
        evidence: {
          "고칠 것": kind === "fix-filename" ? "파일 이름 규칙" : "필드 연결",
          "막힌 이유": String(deps.doc.getElementById("jobGate")?.textContent || "").trim(),
        },
        return_context: { surface: "data" },
      });
    },
    toggleLog(): void { ui = { ...ui, logOpen: !ui.logOpen }; emit(); },

    init(): Promise<unknown> {
      if (releaseModel === null) {
        releaseModel = model.subscribe(pump);
        pump();
      }
      return deps.runtime.loadInitial("job");
    },
    dispose(): void {
      if (releaseModel !== null) { releaseModel(); releaseModel = null; }
      setRun(bumpEpoch(run));
    },
  };

  /* JobRunPort·JobRunCoordinationPort — legacy 구현을 **파일째** 지우므로 handoff 상대가
     없다(#415 D10 과 같은 형태). 빈 port 에 한 번 결속하고 둘째 결속은 throw 한다:
     중간 dual-dispatch 창이 애초에 생기지 않으므로 불변식은 handoff 보다 강하다. */
  deps.ports.jobRun.bind({
    attach(callbacks) {
      if (attached !== null) throw new Error("JobRunPort: run callback은 정확히 한 번 attach합니다.");
      attached = callbacks;
      return () => { attached = null; };
    },
    acceptFull(value: unknown) { ingestFull(value); },
    acceptProgress(value: unknown) { setRun(acceptProgress(run, value as any)); },
    openPreview,
    dispose() { controller.dispose(); },
  });
  deps.ports.jobRunCoordination.bind({ confirmDestructiveIfArmed, log });

  return controller;
}

export type JobRunController = ReturnType<typeof createJobRunController>;

export function useRun(controller: JobRunController): JobRunState & UiState {
  const state = useSyncExternalStore(controller.subscribe, controller.getRun, controller.getRun);
  const ui = useSyncExternalStore(controller.subscribe, controller.getUi, controller.getUi);
  return { ...state, ...ui };
}

export function useRunSnapshot(controller: JobRunController): Obj | null {
  return useSyncExternalStore(controller.subscribe, controller.getRun, controller.getRun).lastFull;
}

/* ------------------------------------------------------------------ 표면 */

export function JobPreflight(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  const p = (s?.preflight || {}) as Obj;
  if (!s?.has_data || !p.text) return null;
  const cls = p.level === "ok" ? "quiet" : p.level === "danger" ? "dangerbox" : "warnbox";
  return h("div", { className: `preflight note ${cls}`, style: { whiteSpace: "pre-line" } },
    String(p.text));
}

export function JobMirrorZone(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  const run = useRun(props.controller);
  // TXT 는 이 존이 **없는 축**이다 — 통째로 걷는다. 남겨 두면 빈 상태 문안이 행을 다 고른
  // 뒤에도 그대로 서서, 따라 해도 아무 일이 없는 막다른 지시가 된다(리뷰 6R).
  // 자리를 비우면 `#jobMirrorZone:empty` 가 존을 접는다(legacy 의 `style.display` 후계 —
  // portal target 의 속성은 React 가 만지지 않는다).
  if (isCopyWork(s) || isManagedHwpx(s)) return null;
  const drift = (s?.drift || []) as string[];
  const nameTokens = (s?.name_tokens || []) as string[];
  const n = Number(s?.selected_count || 0);
  const blanks = (s?.blank_fields || []) as string[];

  // danger = 차단 배너 + 상시 행동 링크(막다른 경보 금지 — 경보 어포던스는 숨지 않는다).
  let banner: ReactNode = null;
  if (drift.length) {
    banner = h("div", { className: "mir-drift", role: "alert" },
      h("p", null, "템플릿 구조가 확정 매핑과 달라져 문서를 생성할 수 없습니다. 어긋난 필드: ",
        h("b", null, drift.join(", ")), "."),
      h("button", {
        className: "btn sm", "data-act": "fix-mapping", "data-busy-lock": true,
        onClick: () => props.controller.openRepair("fix-mapping"),
      }, "편집에서 매핑 확정…"));
  } else if (nameTokens.length) {
    banner = h("div", { className: "mir-drift", role: "alert" },
      h("p", null, "파일명 패턴의 토큰을 채우지 못해 문서를 생성할 수 없습니다. 남는 토큰: ",
        h("b", null, nameTokens.map((t) => `{{${t}}}`).join(", ")), "."),
      h("button", {
        className: "btn sm", "data-act": "fix-filename", "data-busy-lock": true,
        onClick: () => props.controller.openRepair("fix-filename"),
      }, "편집에서 파일명 패턴 고치기…"));
  }

  const summary: ReactNode = (!s?.has_job || !s?.has_data || !n)
    // 선택 0 = 생성될 문서 없음. 트리거는 그대로 두고 문안만 바꾼다 — 자리를 없애면
    // 안정 복귀점도 함께 사라진다.
    ? h("span", { className: "mirempty muted capnote" }, "행을 선택하면 생성 내용을 확인할 수 있습니다.")
    : createElement(Fragment, null,
      blanks.length
        ? h("span", { className: "mir-blank-flag" }, "빈 값 ", h("b", null, `${blanks.length}필드`), `(${blanks.join("·")})`)
        : "빈 값 없음",
      " · 이름 ", h("b", null, `${n}건`));

  const pv = (s?.preview || {}) as Obj;
  return createElement(Fragment, null,
    h("div", { className: "zone-cap" }, "본문 확인"),
    h("div", { id: "jobMirror" }, banner),
    // 한 줄은 안정 DOM 이다 — 확인 면 트리거가 재렌더로 교체되면 시트를 닫은 키보드
    // 사용자의 초점이 그 버튼으로 못 돌아간다(#280 캡스트립과 같은 결함).
    h("p", { className: "mirline", id: "jobMirrorLine", hidden: banner !== null },
      h("span", { id: "jobMirrorSummary" }, summary),
      h("button", {
        className: "btn sm", id: "jobMirrorPreviewOpen", type: "button",
        disabled: run.running || !pv.can_open,
        onClick: (event: Obj) => props.controller.openPreviewFrom(event.currentTarget),
      }, "생성 값 미리보기 ⤢")));
}

export function JobOutRow(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  const run = useRun(props.controller);
  // 저장 폴더는 hwpx 생성의 축이다 — TXT 에선 그 자리를 그리지 않는다(빈 값으로 두면
  // "아직 안 정했다"로 읽혀 사용자가 고르러 간다).
  if (isCopyWork(s) || isManagedHwpx(s)) return null;
  const out = String(s?.out_dir || "");
  return createElement(Fragment, null,
    h("span", { className: "lbl" }, "저장 폴더"),
    h("input", {
      className: "field ro", id: "jobOutDir", type: "text", readOnly: true,
      value: out, placeholder: "이 폴더에 문서를 저장합니다",
    }),
    h("button", {
      className: "btn", id: "jobBtnPickFolder", "data-busy-lock": true,
      // 저장 폴더는 작업 속성이다 — 작업 미선택에서 고르게 두면 작업 선택이 기본값으로
      // 조용히 덮어써 선택이 증발한다(#302 리뷰 P2).
      disabled: run.running || !s?.has_job || isCopyWork(s),
      onClick: () => { void props.controller.pickOutputFolder(); },
    }, "찾아보기…"),
    h("span", { id: "jobOutTrack" },
      out ? createElement(PathActions as any, {
        client: props.controller.client,
        path: out,
        only: ["reveal", "copy"],
        notify: props.controller.notify,
      }) : null));
}

/** 재진술 블록 — 이미 보이는 것을 재검증하지 않으므로 모달이 아니라 상시 블록이다. */
export function JobRestate(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  if (isManagedHwpx(s)) return null;
  const sel = ((s?.records || []) as Obj[]).filter((r) => r.selected);
  const gate = (s?.gate || {}) as Obj;
  // danger 차단 중엔 재진술을 숨긴다 — "생성 불가"인데 "N건 생성"을 동시에 진술하면 모순.
  const blocked = gate.level === "danger";
  if (!s?.has_job || !s?.has_data || !sel.length || blocked) return null;
  const rs = (s.restate || {}) as Obj;
  const selLine = rs.origin === "definition"
    ? `정의 매치 전체 ${sel.length}행: ${String((s.filter && s.filter.definition) || "")}`
    : String(props.controller.selectionLine(sel.length, rs.filter_active, rs.in_def, rs.extra));
  // 산출 재진술은 **매체마다 다른 사실**이다(리뷰 6R) — TXT 는 파일을 만들지 않는다.
  return createElement(Fragment, null,
    h("span", { className: "dl" }, "선택"), h("span", null, selLine),
    isCopyWork(s)
      ? createElement(Fragment, null,
        h("span", { className: "dl" }, "복사"),
        h("span", null, `작업대에서 ${sel.length}건을 한 건씩 검토하고 복사합니다. 파일은 만들지 않습니다.`))
      : createElement(Fragment, null,
        h("span", { className: "dl" }, "생성"),
        h("span", null, `문서 ${sel.length}건 · 저장 폴더: ${String(s.out_dir || "미지정")}`)));
}

function gateStep(s: Obj, g: Obj): string {
  if (!g || g.enabled || !g.text) return "";
  const named = GATE_ZONE[String(g.reason || "")];
  if (named !== undefined) return named;
  // 이름 없는 게이트만 자리로 유추한다 — 데이터·행이 안 갖춰졌으면 그게 먼저다.
  const noRows = !s.has_data || !(Number(s.selected_count) > 0);
  if (!s.has_job) return noRows ? GATE_ZONE.no_data : GATE_ZONE.no_job;
  if (noRows) return GATE_ZONE.no_data;
  return "";
}

export function JobWorkbenchStatus(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  const running = useRun(props.controller).running;
  const wb = (s?.workbench_observation || {}) as Obj;
  if (!isManagedHwpx(s) || wb.supported !== true) return null;
  const items = (wb.input_requirements || []) as Obj[];
  const executionAction = (wb.execution_action || null) as Obj | null;
  const recordValidation = (wb.record_validation || {}) as Obj;
  const recordIssues = (recordValidation.issues || []) as Obj[];
  const recordSection = wb.kind === 'context_error'
    ? createElement(Fragment, null,
        h('div', { className: 'zone-cap' }, '데이터 확인'),
        h('p', { className: 'danger capnote' },
          String(wb.detail || '현재 데이터를 확인할 수 없습니다.')))
    : createElement(Fragment, null,
    h('div', { className: 'zone-cap' }, '데이터 확인'),
    recordIssues.length
      ? h('ul', { className: 'plain-list', id: 'jobRecordValidationIssues' },
          ...recordIssues.map((issue) => h('li', {
            key: `${String(issue.record_identity)}:${String(issue.field_id)}`,
          },
          h('span', null,
            `${String(issue.record_display_locator)} · ${String(issue.field_display_label)} · `,
            String(issue.message || '')),
          h('button', {
            className: 'btn sm', type: 'button',
            onClick: () => { void props.controller.recoverRecordIssue(
              issue.recovery_target as Obj,
            ); },
          }, '문제 위치 보기'))))
      : h('p', { className: 'muted capnote' },
          Number(recordValidation.validated_count || 0) > 0
            ? `${Number(recordValidation.validated_count)}건의 데이터를 확인했습니다.`
            : '확인할 데이터가 없습니다.'));
  const intent = (wb.run_delivery_intent || null) as Obj | null;
  const delivery = (wb.delivery || {}) as Obj;
  const planned = (delivery.planned_documents || []) as Obj[];
  const deliveryBlockers = (delivery.blockers || []) as Obj[];
  const collisionPolicy = String(intent?.collision_policy || '');
  const deliverySection = createElement(Fragment, null,
    h('div', { className: 'zone-cap' }, '저장 폴더'),
    h('div', { className: 'run-row' },
      h('input', {
        className: 'field ro', id: 'jobManagedOutDir', type: 'text', readOnly: true,
        value: String(intent?.output_directory || ''),
        placeholder: '이 폴더에 문서를 저장합니다',
      }),
      h('button', {
        className: 'btn sm', id: 'jobManagedPickFolder', type: 'button',
        disabled: running || !s?.has_job,
        onClick: () => { void props.controller.pickOutputFolder(); },
      }, '찾아보기…')),
    h('div', { className: 'zone-cap' }, '충돌 처리'),
    h('select', {
      className: 'field', id: 'jobDeliveryCollision', value: collisionPolicy,
      disabled: running || intent === null,
      onChange: (event: Obj) => {
        const policy = String(event.currentTarget.value);
        event.currentTarget.value = collisionPolicy;
        void props.controller.setDeliveryCollision(policy);
      },
    },
    intent === null
      ? h('option', { value: '' }, '저장 폴더를 먼저 선택하세요')
      : null,
    ...DELIVERY_POLICIES.map(([value, label]) =>
      h('option', { key: value, value }, label))),
    h('div', { className: 'zone-cap' }, '생성 예정 문서'),
    planned.length
      ? h('ul', { className: 'plain-list', id: 'jobPlannedDocuments' },
          ...planned.map((item) => h('li', {
            key: `${String(item.record_identity)}:${String(item.item_ordinal)}`,
            'data-collision-disposition': String(item.collision_disposition || ''),
          },
          h('span', null, String(item.relative_path || '')),
          h('span', { className: 'muted capnote' },
            DELIVERY_DISPOSITION_COPY[String(item.collision_disposition || '')] || ''))))
      : deliveryBlockers.length
        ? h('ul', { className: 'plain-list danger capnote', id: 'jobDeliveryBlockers' },
            ...deliveryBlockers.map((blocker, index) =>
              h('li', { key: index },
                String(blocker.message || ''),
                blocker.conflicting_relative_path
                  ? h('span', null,
                    h('br', null), String(blocker.conflicting_relative_path))
                  : null)))
        : h('p', { className: 'muted capnote' }, '생성 예정 문서가 없습니다.'),
    h('div', { className: 'run-row' },
      h('button', {
        className: 'btn sm', id: 'jobRefreshDelivery', type: 'button',
        disabled: running || intent === null,
        onClick: () => { void props.controller.refreshDelivery(); },
      }, '목록 새로 확인'),
      h('span', { className: 'muted capnote' },
        '현재 상태에서 만들 예정인 이름입니다. 실제 파일 생성을 예약한 것은 아닙니다.')));
  return createElement(Fragment, null,
    h("div", { className: "zone-cap" }, String(wb.input_requirements_label || "")),
    items.length
      ? h("ul", { className: "plain-list", id: "jobInputRequirements" },
          ...items.map((item) => h("li", {
            key: String(item.field_id),
            "data-binding-state": String(item.binding_state || ""),
          },
          h("span", null, String(item.display_label || "")),
          item.action_required === true
            ? h("button", {
                className: "btn sm", type: "button",
                "data-exact-target": String(item.exact_target || ""),
                onClick: () => { void props.controller.openBindingRequirement(
                  String(item.exact_target || ""), String(item.display_label || "")); },
              }, "\uc218\uc815\u2026")
            : null)))
      : null,
    h("div", { className: "zone-cap" }, "\ud604\uc7ac \uc2e4\ud589 \uc0c1\ud0dc"),
    h("p", { className: "muted capnote", "data-status-code": String(wb.execution_status_code || "") },
      String(wb.execution_status_phrase || "")),
    executionAction
      ? h("div", { className: "run-row" },
          h("button", {
            className: "btn sm", type: "button", id: "jobResolveExecution",
            disabled: executionAction.enabled !== true,
            onClick: () => { void props.controller.resolveExecution(); },
          }, String(executionAction.label || "")),
          h("span", { className: "muted capnote" },
            String(executionAction.disabled_reason || "")))
      : null,
    recordSection,
    deliverySection);
}

export function JobActionBar(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  const run = useRun(props.controller);
  const busy = run.running;
  const on = !!s?.has_job;
  const missing = on && !!s?.template_missing;
  const gate = (s?.gate || { enabled: false, level: "", text: "" }) as Obj;
  const review = (s?.review || {}) as Obj;
  const pv = (s?.preview || {}) as Obj;
  const managed = isManagedHwpx(s);
  const workbench = (s?.workbench_observation || {}) as Obj;
  const createAction = (workbench.create_action || {}) as Obj;
  const previewRequirement = (workbench.preview_requirement || {}) as Obj;
  const previewAvailable = previewRequirement.kind === "OPTIONAL"
    || previewRequirement.kind === "REQUIRED";
  const ra = (s?.run_action || { key: "generate", label: "이 작업으로 문서 생성" }) as Obj;

  return h("div", { className: "actionbar-row" },
    h("span", { className: "actionbar-identity" },
      h("span", { className: "actionbar-job", id: "jobActionName" }, on ? String(s?.job_name || "") : ""),
      h("span", { className: "actionbar-conn", id: "jobActionConn", hidden: !missing },
        missing ? String(s?.conn_label || "") : ""),
      h("button", {
        className: "btn sm", id: "jobActionRelink", type: "button", "data-busy-lock": true,
        hidden: !missing, disabled: busy, onClick: props.controller.relinkActive,
      }, "템플릿 다시 연결…")),
    h("button", {
      className: "btn", id: "jobPreviewOpen", "data-busy-lock": true,
      hidden: managed, disabled: busy || managed || !pv.can_open,
      onClick: (event: Obj) => props.controller.openPreviewFrom(event.currentTarget),
    }, "생성 값 미리보기"),
    // 「승인 필요」 표지는 요구가 **아직 안 풀렸을 때만** — 승인한 뒤에도 붙어 있으면
    // 확인이 무의미해진다.
    h("span", {
      className: "pill warn", id: "jobReviewFlag",
      hidden: managed,
      style: { display: review.required && !review.approved ? "" : "none" },
    }, "승인 필요"),
    managed && previewAvailable ? h("button", {
      className: workbench.primary_action === "REVIEW_PREVIEW" ? "btn primary" : "btn",
      id: "jobManagedPreviewOpen", type: "button", disabled: busy,
      onClick: (event: Obj) => props.controller.openPreviewFrom(event.currentTarget),
    }, "생성 내용 확인") : null,
    h("button", {
      className: "btn primary", id: "jobGenBtn",
      hidden: managed,
      disabled: busy || !gate.enabled,
      onClick: () => { void props.controller.startGenerate(); },
    }, busy ? "생성 중…" : String(ra.label)),
    managed ? h("button", {
      className: "btn primary", id: "jobManagedCreate", type: "button",
      disabled: busy || createAction.enabled !== true,
      onClick: () => { void props.controller.startGenerate(); },
    }, String(createAction.label || "")) : null,
    h("button", {
      className: "btn", id: "jobGenCancel", style: { display: busy ? "" : "none" },
      onClick: () => { void props.controller.cancelGeneration(); },
    }, "다음 건부터 중단"),
    // 정적 선언(`muted capnote`)을 덮어쓰지 않는다(리뷰 R5) — 빈 문안이 자리를 비우게
    // 하는 규칙(`.actionbar-row>.capnote:empty`)이 붙을 곳을 잃는다.
    managed ? h("span", { className: "muted capnote", id: "jobManagedCreateReason" },
      String(createAction.disabled_reason || "")) : null,

    h("span", {
      className: "muted capnote", id: "jobGate",
      hidden: managed,
      style: {
        color: gate.level === "danger" ? "var(--a-danger)"
          : gate.level === "warn" ? "var(--a-warn)" : "",
      },
    }, busy || s === null ? "" : `${gateStep(s, gate)}${String(gate.text || "")}`));
}

export function JobStatusPill(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  if (isManagedHwpx(s)) {
    const wb = (s?.workbench_observation || {}) as Obj;
    return h("div", {
      id: "jobStatus", className: "status", "data-level": "idle",
      "data-status-code": String(wb.execution_status_code || ""),
    }, String(wb.execution_status_phrase || ""));
  }
  let level = "idle";
  let text = "작업 선택";
  if (s?.has_job) {
    if (!s.has_data) { text = "데이터 선택"; }
    else if (s.gate && s.gate.enabled) { level = "ok"; text = isCopyWork(s) ? "복사 준비" : "생성 준비"; }
    else {
      // 막힌 이유가 규칙축이면 표지도 「승인」이다(U2 §2.10) — 어휘를 갈라 놓고 이 자리만
      // 「확인 필요」로 두면 같은 행동을 두 이름으로 부른다.
      level = "warn";
      text = (s.gate && s.gate.reason) === "review_required" ? "승인 필요" : "확인 필요";
    }
  }
  /* 클래스는 `status` 다 — `pill` 이 아니다. 색은 `data-level` **혼자** 내지 않는다:
     `.status[data-level="ok"|"warn"]`(base.css)이 그 결속이고, `.pill` 계열은 `.pill.ok`
     처럼 **클래스**로 태를 받는다. `pill` + `data-level` 조합은 어느 쪽에도 안 붙어 속성만
     살고 색이 죽는다(배경 `--n-track` 과 본문 크기도 함께 잃는다). legacy 의 `div.status`
     를 그대로 옮긴다 — 이 자리에서 바꿀 것은 생산자뿐이고 표현이 아니다. */
  return h("div", { id: "jobStatus", className: "status", "data-level": level }, text);
}

/** 생성 준비 캡션 — 하는 일을 따라간다(TXT 는 파일을 만들지 않는다). */
export function JobRunCap(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  if (isManagedHwpx(s)) {
    return String(s?.workbench_observation?.create_action?.label || "");
  }
  return isCopyWork(s) ? "복사 준비" : "생성 준비";
}

/* ------------------------------------------------------------------ 템플릿 변경(S3-09) */

/** prepare intent 재전송 키 — Python 이 `[A-Za-z0-9._-]{1,64}` 로 fail-closed 검증한다. */
function newTplRequestId(): string {
  return `r${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 제품 status → 상태 문안. 정본 어휘는 contract.gen.ts 의 TEMPLATE_PREPARATION_STATUSES —
 *  표에 없는 status 는 조용히 비우지 않고 원문을 그대로 보인다(조용한 폴백 금지). */
const TPL_STATUS_COPY: Record<string, string> = {
  checking: "변경사항을 확인하는 중입니다…",
  ready: "적용할 수 있는 변경사항이 있습니다.",
  no_change: "변경사항이 없습니다 — 지금 템플릿이 이미 적용된 상태입니다.",
  invalid: "변경된 템플릿이 검사를 통과하지 못했습니다. 기존 템플릿이 계속 사용됩니다.",
  error: "확인 중 오류가 났습니다. 다시 확인해 주세요.",
  interrupted: "확인이 끝나기 전에 중단되었습니다. 다시 확인해 주세요.",
  source_changed: "확인하는 동안 템플릿 연결이 바뀌었습니다.",
  changed_while_checking: "확인하는 동안 작업의 템플릿 상태가 바뀌었습니다.",
  superseded: "새 확인이 시작되어 이 결과는 대체되었습니다.",
  applied: "확인한 변경사항이 현재 작업에 적용되어 있습니다.",
  conflict: "확인 이후 작업 상태가 바뀌어 이 변경사항은 적용할 수 없습니다.",
  rejected: "이 변경사항은 더 이상 적용할 수 없습니다.",
};

/** FAIL(invalid)과 오류·중단·대체를 다른 행동 문구로 가른다 — 재확인 라벨이 그 분리다. */
const TPL_RECHECK_LABEL: Record<string, string> = {
  error: "다시 확인",
  interrupted: "다시 확인",
  conflict: "현재 상태로 다시 확인",
  superseded: "현재 상태로 다시 확인",
  source_changed: "현재 상태로 다시 확인",
  changed_while_checking: "현재 상태로 다시 확인",
};

/** 적용 결과 한 줄 재진술 — TemplateApplyStatus 전집. rollback 경로는 없다(#659). */
export function applyNotice(res: Obj): string {
  switch (String(res.status || "")) {
    case "applied": return "변경사항을 적용했습니다.";
    case "already_applied": return "이미 적용되어 있는 변경사항입니다.";
    case "applied_then_advanced":
      return "이 변경사항은 적용된 뒤 다른 적용이 이어졌습니다. 현재 상태로 다시 확인하세요.";
    case "conflict": return "확인 이후 작업 상태가 바뀌어 적용하지 못했습니다. 현재 상태로 다시 확인하세요.";
    case "superseded": return "새 확인이 시작되어 이 변경사항은 대체되었습니다.";
    case "rejected": return "이 변경사항은 더 이상 적용할 수 없습니다.";
    default: return `적용 결과: ${String(res.status || "미상")}`;
  }
}

export function useTemplateChangeUi(controller: JobRunController): TemplateChangeUi {
  return useSyncExternalStore(controller.subscribe, controller.getTemplateChange);
}

/** 템플릿 변경사항 구획 — revision 번호·목록·선택기는 없다(#659 계약). token 은 스냅샷의
 *  opaque 문자열을 버튼에 관통시킬 뿐 화면이 해석하지 않는다. */
export function JobTemplateChange(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  const running = useRun(props.controller).running;
  const tpl = useTemplateChangeUi(props.controller);
  const z = (s?.template_change || null) as Obj | null;
  if (!s?.has_job || !z || !z.supported) return null; // HWPX 아닌 작업 — capability 비노출
  const prep = (z.preparation || null) as Obj | null;
  const status = prep ? String(prep.status || "") : "";
  const needsInit = z.reason === "initialization_required";
  const busy = tpl.inFlight || running;
  const diagnostics = ((needsInit ? z.diagnostics : prep?.diagnostics) || []) as Obj[];
  const statusText = needsInit
    ? "템플릿 초기 등록에 실패해 변경사항을 확인할 수 없습니다. 템플릿을 수정하거나 다시 연결한 뒤 확인하세요."
    : status
      ? (TPL_STATUS_COPY[status] ?? `확인 상태: ${status}`)
      : "템플릿 원본을 고쳤다면 변경사항을 확인한 뒤 이 작업에 적용할 수 있습니다.";
  return h("div", { id: "jobTplChange" },
    h("div", { className: "zone-cap" }, "템플릿 변경사항"),
    h("div", {
      className: needsInit || status === "invalid" ? "note warnbox" : "muted capnote",
      id: "jobTplStatus",
      style: { whiteSpace: "pre-line" },
    }, statusText),
    diagnostics.length
      ? h("ul", { id: "jobTplDiag", className: "muted capnote" },
          diagnostics.map((d, index) =>
            h("li", { key: index }, String(d.message || d.kind || ""))))
      : null,
    h("div", { className: "run-row" },
      h("button", {
        className: "btn sm", id: "jobTplCheck", type: "button",
        disabled: busy || !z.checkable,
        onClick: () => { void props.controller.templateCheck(); },
      }, TPL_RECHECK_LABEL[status] || "변경사항 확인"),
      status === "ready" && prep?.change_token
        ? h("button", {
            className: "btn sm primary", id: "jobTplApply", type: "button",
            disabled: busy,
            onClick: () => { void props.controller.templateApply(String(prep.change_token)); },
          }, "변경사항 적용")
        : null),
    tpl.notice
      ? h("div", { className: "muted capnote", id: "jobTplNotice" }, tpl.notice)
      : null);
}
