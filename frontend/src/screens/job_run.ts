/* R4-03 실행 표면 — 사전검증·위험 배너·게이트·저장 폴더·배달 계획·액션바·진행/결과
   수명주기의 단일 owner. legacy `js/screens/job.js` 의 실행 remainder 전체가 여기로 온다.

   ## 존 재편(#957 후속) — 같은 사실을 두 번 말하지 않는다

   구 「본문 확인」 존의 요약 한 줄(빈 값 필드·이름 건수)과 우 열 「현재 실행 상태」 문안은
   각각 사전검증 `[경고] 빈 값 필드` 와 우상단 상태 pill 이 이미 말하던 것의 두 번째 발화라
   걷혔다. 남는 것은 **행동을 든 것**뿐이다: 「생성 예정 문서」는 좌 열(표와 생성 결과 사이)로
   옮겨 만들 것과 만들어진 것이 한 줄기로 읽힌다. legacy HWPX 의 위험 배너(`#jobMirror`)는
   문서 생성이 managed 하나가 되며(#1081 PR2) 걷혔다.
   구 재진술 블록(`#jobRestate`)은 선택 수치를 세 번째로 말하던 자리라 함께 죽었다 —
   그 수치를 정말 다시 물어야 하는 자리는 파괴 전이 가드 모달 하나이고, 거기는 공유
   합성기 `selectionLine` 이 계속 진다.

   ## 이 파일이 legacy 에서 바꾼 것 하나

   상태다. legacy 는 모듈 지역 `LAST`·`RESULT`·`generating`·`lastSessionKey` 넷을 들고
   도착한 것을 무엇이든 지금 것이라고 가정했다. 여기서는 그 넷이 `job_run_state.ts` 의 한
   reducer 로 합쳐지고, **귀속 판정**(화면 세대·세션 지문·실행 토큰)이 반영 여부를 정한다.
   나머지는 전부 그대로다 — 판정·수치·문안의 출처는 여전히 Python 이고, 이 층은 그것을
   자리에 놓기만 한다.

   ## 순수 합성기 셋은 표면이 아니라 계약이다

   `overwriteBody`·`guardBody`·`selectionLine` 은 인자만 읽는 순수 함수다. 실앱 게이트가
   산출을 되읽어 파괴적 확인 문안의 조용한 드리프트를 막는다 — 그래서 컨트롤러 표면에
   이름째 남는다(삭제 회귀를 핀이 잡는다). */

import { Fragment, createElement, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { BridgeClient } from "../runtime/client.ts";
import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import type { ScreenPorts } from "./ports.ts";
/* 모달 id 는 여는 쪽과 그리는 쪽이 **같은 상수**를 쓴다 — 문자열을 두 벌 들면 한쪽만 늙는다. */
import { SETTINGS_MODAL_ID } from "./settings_sheet.ts";
import type { JobScreenModel, ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import {
  acceptDirect, acceptFull, acceptProgress, beginRun, bumpEpoch, closeResult,
  createTokenFactory, disposeBySession, endRun, initialRunState, sessionKeyOf,
} from "./job_run_state.ts";
import type { JobRunState } from "./job_run_state.ts";
import { isManagedHwpx, useRunSnapshot } from "./job_run_snapshot.ts";
import { openJobInEditor, openTemplateRepairInEditor, TemplateRepairButton } from "./job_template_repair.ts";
import {
  applyNotice, composeGuardBody, DELIVERY_DISPOSITION_COPY, gateStep, newTplRequestId,
  overwriteBody, saveArtifactMessage,
  TPL_INITIALIZATION_REQUIRED_COPY, TPL_RECHECK_LABEL, TPL_STANDING_FALLBACK_COPY,
  TPL_STATUS_COPY, TPL_ZONE_CAP_ACTION, TPL_ZONE_CAP_SETTLED, tplCheckRefusalNotice,
} from "./job_run_copy.ts";

export type Obj = Record<string, any>;
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

export {
  ARTIFACT_REFUSAL_TITLE, saveArtifactMessage, DELIVERY_DISPOSITION_COPY,
  overwriteBody, composeGuardBody,
} from "./job_run_copy.ts";


export function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/* ------------------------------------------------------------------ 컨트롤러 */

type UiState = {
  /** 산출물 「다른 이름으로 저장」의 마지막 결과 한 줄(S7-03 · #825). 저장·취소·저장 실패·
   *  관찰 거절이 서로 다른 문장으로 여기 앉는다. 판정은 백엔드 `status` 가 하고 이 값은
   *  그 코드를 문안으로 옮긴 결과다(시트 밖에서 조립해 시트가 상태를 갖지 않게 한다). */
  artifactSave: string;
};

type TemplateChangeUi = { inFlight: boolean; requestId: string | null; notice: string };

export function createJobRunController(deps: JobRunControllerDeps) {
  const model = deps.runtime.model<JobScreenModel>("job");
  const nextToken = createTokenFactory();

  let run: JobRunState = initialRunState();
  let ui: UiState = { artifactSave: "" };
  /* 템플릿 변경 확인·적용(S3-09)의 화면 local 상태 — 진행 여부·요청 키·적용 재진술.
     요청 키는 prepare intent 의 재전송 단위다: 진행 중 중복 클릭은 무시(한 요청으로 수렴),
     전송 실패로 남은 키는 다음 클릭이 **같은 키로 재전송**, 성공 뒤 클릭만 새 키(=새 intent). */
  let tpl: TemplateChangeUi = { inFlight: false, requestId: null, notice: "" };
  const listeners = new Set<Listener>();
  let releaseModel: (() => void) | null = null;
  let lastFullSeen: unknown = null;
  let lastProgressSeen: unknown = null;

  function emit(): void { for (const listener of [...listeners]) listener(); }
  function setRun(next: JobRunState): void { run = next; emit(); }
  function setTpl(next: TemplateChangeUi): void { tpl = next; emit(); }

  function snapshot(): Obj | null {
    return run.lastFull;
  }

  /** 응답이 오는 사이 작업이 갈리지 않았는가 — 템플릿 변경 확인·적용 재진술이 같은
   *  「현재도 같은 작업인가」 질의를 두 번 거듭 짓던 것을 하나로 합친다. */
  function stillOwner(owner: string): boolean {
    return String(snapshot()?.job_name || "") === owner;
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
    /* 초기화 갈래는 그 실행에 딸린 웹 소유 한 줄(산출물 저장 결과)도 함께 치운다 — 결과가
       물러난 뒤 남으면 다음 세션 밑에 앉은 남의 문장이 된다. `ui` 를 `setRun` 앞에 두어
       emit 한 번에 함께 실린다. */
    if (!before.running && disposal.kind === "reset") ui = { artifactSave: "" };
    setRun(next);
    syncArtifactOpen(next.lastFull);
  }

  /** 산출물 관찰 시트의 개폐를 상태에 맞춘다(S7-03 · #825). Python 이 닫았다고 말했는데
   *  면이 떠 있으면 그 면은 **남의 문서**를 그리고 있다 — 백엔드가 배달 좌표를 놓는
   *  데이터 교체·작업 전환이 그 경로다. 개폐 주인은 Python 소유 `artifact_view.open` 이고
   *  이 층은 집행만 한다.
   *
   *  열려 있지 않은 대상의 `close` 는 스택에 없어 아무 일도 하지 않으므로 DOM 에 열림
   *  여부를 되묻지 않는다 — 상태의 진실은 스냅샷이지 클래스가 아니다. */
  function syncArtifactOpen(full: Obj | null): void {
    if (!(full && full.artifact_view && full.artifact_view.open)) {
      deps.modal.close("artifactSheet");
    }
  }

  function pump(): void {
    const next = model.getSnapshot();
    if (next.full !== null && next.full !== lastFullSeen) {
      lastFullSeen = next.full;
      lastProgressSeen = null;
      ingestFull(next.full);
    }
    if (next.progress !== null && next.progress !== lastProgressSeen) {
      lastProgressSeen = next.progress;
      setRun(acceptProgress(run, next.progress as any));
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
      deps.notify("실행 응답에 상관 토큰이 없습니다(계약 위반) — 결과를 신뢰할 수 없습니다.");
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
      // 능동 취소는 착지가 없다 — 방금 「취소」를 고른 사람에게 취소를 다시 알리지 않는다.
      setRun(endRun(run));
      return;
    }

    if (res.ok === false && res.error) {
      // 실행 전 거절 — 결과 자리를 비워 두면 눌렀는데 아무 일도 없는 것으로 읽힌다.
      // 사유는 이 구획 하나가 진다(재진술 두 벌 금지).
      setRun(acceptDirect(run, {
        rejected: true, level: res.level === "danger" ? "danger" : "warn",
        title: "생성하지 않았습니다", summary: String(res.error), run_token: res.run_token,
      }));
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
      deps.notify(String(res.error || "작업대를 열지 못했습니다."));
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
    try {
      await doGenerate(token, false);
    } catch (error) {
      setRun(endRun(run));
      deps.notify(`생성하지 못했습니다: ${String((error as Obj)?.message ?? error)}`);
    }
  }

  /* ---- 산출물 관찰 시트(S7-03 · #825) ---- */
  /** 어느 행이 열었는가 — 닫을 때 초점이 그 자리로 돌아가야 한다(면은 문서마다 열린다). */
  let artifactTrigger: HTMLElement | null = null;

  /** 배달 문서 하나를 관찰해 시트를 연다.
   *
   *  커밋 관문(`flushPendingEdits`)은 지나지 않는다: 관찰의 대상은 **이미 만들어진
   *  파일**이라 지금 표의 편집과 아무 관계가 없다.
   *
   *  관찰이 서지 않은 갈래에서도 **면은 연다**. 백엔드가 사유를 스냅샷에 실어 주므로 시트가
   *  그것을 말한다 — 여기서 실패로 접으면 사용자는 눌렀는데 아무 일도 없는 화면을 본다. */
  async function openArtifact(ordinal: number): Promise<void> {
    try {
      await dispatch("artifact_open", { ordinal });
    } catch (error) {
      deps.notify(`문서 내용을 열지 못했습니다: ${String((error as Obj)?.message ?? error)}`);
      return;
    }
    if (deps.navigation.currentScreen() !== "job") {
      void dispatch("artifact_close", {});
      return;
    }
    deps.modal.open("artifactSheet", {
      returnFocus: artifactTrigger,
      initialFocus: deps.doc.getElementById("artifactClose"),
      onClose: () => { void dispatch("artifact_close", {}); },
    });
  }

  /** exact target 을 지목한 진입은 그 문맥을 editor 에 넘긴다 — **조준은 editor 가** 한다(#789).
   *
   *  종전에는 여기서 port 너머로 `aimAt` 을 부르려 했는데 그 메서드는 `EditorEntryPort` 표면에
   *  없었고, `typeof` 로 물어보고 없으면 조용히 지나가는 형상이라 초점이 한 번도 선 적이 없었다.
   *  진입 문맥은 이미 목표를 담아 editor 에 도착하므로 물어볼 곳은 바깥이 아니라 그쪽이다. */
  function openBindingRequirement(exactTarget: string, displayLabel: string): Promise<boolean> {
    return openJobInEditor(deps.ports.editorEntry.current(), snapshot()?.job_name, {
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
    overwriteBody, guardBody,
    selectionLine: deps.selectionLine,
    async resolveExecution(): Promise<void> {
      try {
        await dispatch("resolve_execution", {});
      } catch (error) {
        deps.notify(`\ud604\uc7ac \uc124\uc815\uc744 \ud655\uc778\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4: ${String(error)}`);
      }
    },
    /** context error 의 복구 동사(#912 D4) — 마지막 Plan 을 **지금 이 순간으로** 다시 관찰한다.
     *
     *  이 액션은 registry 와 핸들러에 있었는데 프런트 호출자가 0 이라 단방향 배선이었다:
     *  「현재 실행 맥락을 복원하지 못했습니다」가 danger 문안으로만 서고 그것을 지울 동사가
     *  화면에 없었다. 판정·문안은 backend 가 낸 `recover_action` 을 그대로 소비한다(재조립 0). */
    async recoverContext(): Promise<void> {
      try {
        await dispatch("refresh_observation", {});
      } catch (error) {
        deps.notify(`현재 상태를 다시 확인하지 못했습니다: ${String(error)}`);
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
        // 겨눔은 하나다 — 이전 표지를 걷지 않으면 지난 겨눔이 같이 남아 어디를 봤는지 잃는다.
        deps.doc.querySelectorAll('.jb-aimed').forEach((stale) => stale.classList.remove('jb-aimed'));
        try { element.focus({ preventScroll: true }); } catch { element.focus(); }
        /* 표지는 별 상태가 아니라 **성공한 focus 수명**에만 붙는 class 다(workbench `aimAt` 승계):
           WebView2 는 focus 된 tr 을 activeElement 로 되읽으면서도 `tr:focus` 의 셀 shadow 를
           계산하지 않는 경우가 있다. blur 와 함께 사라지고 앱 상태로는 들지 않는다. */
        if (deps.doc.activeElement === element) element.classList.add('jb-aimed');
        // `center` 는 중첩 스크롤러(.jobtbwrap) 밖 페이지째를 끌어올린다 — 겨눔이 시야를 옮긴다.
        element.scrollIntoView?.({ block: 'nearest' });
      } catch (error) {
        // 실패 사유는 가시 채널로 올린다 — 「눌렀는데 아무 일도 없다」로 읽히지 않게.
        deps.notify(`문제 위치로 이동하지 못했습니다: ${String(error)}`);
      }
    },
    confirmDestructiveIfArmed,

    /** 결과 3태 구획의 **프로브 입구**(F4) — legacy 파사드가 지던 이름 그대로다.
     *  실앱 게이트가 Python 이 내는 결과 dict 를 그대로 흘려 태·강등·증거 접힘이 실
     *  WebView2 에서 서는지 되읽는다. 귀속 판정(`acceptDirect`)을 지나지 **않는다**:
     *  이 입구는 실행이 아니라 렌더를 겨누고, 토큰 없는 dict 를 넣는 것이 그 시험의 요지다. */
    renderResult(res: Obj): void {
      setRun({ ...run, result: res, running: false });
    },
    markResultStale(): void {
      if (run.result === null) return;
      setRun({ ...run, result: { ...run.result, stale: true } });
    },
    startGenerate,
    openBindingRequirement,
    openTemplateRepair: () => openTemplateRepairInEditor(
      deps.ports.editorEntry.current(), snapshot()?.job_name,
    ),
    async cancelGeneration(): Promise<void> {
      /* 중단 요청의 착지는 결과 구획이다 — 진행 중인 문서를 마친 뒤 Python 이 「생성을
         중단했습니다 · N개 완료」와 미착수 건수를 그 자리에 낸다. 접수 시점에 따로 알리지
         않는 이유는 그것이 성공한 요청이라서다(실패·거절만 알림 채널로 간다). */
      await dispatch("cancel_generation", {});
    },
    closeResult(): void {
      /* legacy `resetGenResult` 동등 — 명시 파기는 결과와 함께 그 실행에 딸린 웹 소유 한 줄
         (산출물 저장 결과)까지 치운다. 남으면 치우라는 행동을 반만 들은 것이 된다.
         `artifactSave` 는 JobRunState 가 아니라 UiState 라 reducer 밖이다. */
      ui = { artifactSave: "" };
      setRun(closeResult(run));
      // S6-05: managed 화면에선 #jobGenBtn 이 숨어 있다 — 눌렀던 create 로 초점을 되돌린다.
      const managedButton = deps.doc.getElementById(
        "jobManagedCreate",
      ) as HTMLButtonElement | null;
      const button = deps.doc.getElementById("jobGenBtn") as HTMLButtonElement | null;
      if (managedButton && !managedButton.disabled) managedButton.focus();
      else if (button && !button.disabled) button.focus();
      else deps.doc.getElementById("scr-job")?.focus();
    },
    async selectFailed(): Promise<void> {
      const res = await dispatch("select_failed", {});
      // 성사한 선택은 표의 선택 수·재진술이 그대로 보인다(무착지). 0 건은 **거절**이라
      // 조용히 넘기지 않는다 — 눌렀는데 표가 그대로인 이유가 여기 말고 없다.
      if (!Number(res.selected || 0)) {
        deps.notify("다시 만들 실패 건이 남아 있지 않습니다(데이터나 작업이 그사이 바뀌었습니다).");
      }
    },
    openRenameRules(): void {
      const s = snapshot();
      if (!s || !s.job_name) { deps.notify("작업이 선택돼 있지 않습니다."); return; }
      const owner = String(s.last_run_job || s.job_name);
      if (owner !== String(s.job_name)) {
        deps.notify(
          `이 결과는 '${owner}' 실행입니다. 지금 열린 작업이 달라 파일 이름 규칙을 열지 않았습니다.`,
        );
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
    /** 전역 저장 폴더 지정 — 이 화면에는 트리거가 없고 **설정 모달의 저장 폴더 행**이 부른다.
     *
     *  화면이 아니라 여기 남는 이유는 왕복의 소유다: `pick_output_folder` 는 직접 브리지
     *  경로이고 그 응답의 오류 재진술 규율(조용한 무시 금지)이 이 컨트롤러의 것이다. 설정 면은
     *  그 동사를 호출만 한다 — 판정·문안을 그쪽에서 다시 조립하지 않는다. */
    async pickOutputFolder(): Promise<void> {
      const result = expectHostValue(
        await deps.client.invoke("pick_output_folder", "job"), "pick_output_folder");
      if (result === null || result === undefined) return;
      const text = String(result);
      // 고른 폴더는 저장 폴더 표시가 그대로 보인다(무착지) — 오류만 알림 채널로 간다.
      if (text.startsWith("ERROR:")) { deps.notify(`폴더 오류: ${text.slice(6).trim()}`); return; }
      /* 저장 폴더를 **재진술하는 표면이 둘**이 됐다(U6-D #978): 이 화면과 편집기 3단계다.
         이 왕복은 `job` 컨트롤러만 밀므로 편집기는 자기 다음 푸시까지 옛 경로를 그린다 —
         설정에서 방금 바꾼 값을 읽기 전용 칸이 부정하는 자리다. 그래서 편집기도 재당긴다
         (재당김은 스냅샷 조회 하나라 세션 상태를 건드리지 않는다). */
      void deps.runtime.refresh("editor");
    },
    /** 배달 blocker 의 착지 — 저장 폴더를 바꾸러 갈 문을 연다(막다른 경보 금지).
     *  여는 것만 안다: 모달의 내용·현재값·잠금은 전부 설정 면이 진다. */
    openOutputFolderSettings(): void {
      deps.modal.open(SETTINGS_MODAL_ID, {
        returnFocus: deps.doc.getElementById("jobOpenFolderSettings"),
      });
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
        const res = await dispatch("template_check", { request_id: requestId });
        // **거절도 응답이다**(#804): `ok:false` 는 전송 실패가 아니라 종결된 판정이라 예외로
        // 오지 않는다 — 여기서 읽지 않으면 「시키는 대로 눌렀는데 아무 일도 안 일어난다」가
        // 된다. 판정·사유는 Python 이 싣고 여기는 그것을 재진술할 뿐이다.
        const notice = res.ok === true ? "" : tplCheckRefusalNotice(res);
        // 응답이 오는 사이 작업이 갈렸으면 구획에는 싣지 않는다(남의 재진술 차단, 리뷰 P2).
        // 그래도 **알림 채널에는 낸다** — 좌석이 풀리는 거절(work_context_changed)은 존
        // 자체가 사라져 구획이 아무 말도 할 수 없는 자리이기 때문이다.
        setTpl({ inFlight: false, requestId: null, notice: stillOwner(owner) ? notice : "" });
        if (notice) deps.notify(notice);
      } catch (error) {
        // 전송 실패 — 키를 남겨 다음 클릭이 같은 키로 재전송. 단 그사이 작업이 갈렸으면
        // 키는 남의 intent 라 버린다(리뷰 P2 동류 — 상태는 세션 정체를 따른다).
        setTpl({ inFlight: false, requestId: stillOwner(owner) ? requestId : null, notice: "" });
        deps.notify(`변경사항 확인에 실패했습니다: ${String(error)}`);
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
        setTpl({ inFlight: false, requestId: null, notice: stillOwner(owner) ? applyNotice(res) : "" });
      } catch (error) {
        setTpl({ ...tpl, inFlight: false });
        deps.notify(`변경사항 적용에 실패했습니다: ${String(error)}`);
      }
    },
    /* ---- 산출물 관찰(S7-03 · #825) — 열림·값은 Python 소유, 여기는 집행과 문안이다. */
    openArtifactFrom(ordinal: number, trigger: HTMLElement | null): void {
      artifactTrigger = trigger;
      ui = { ...ui, artifactSave: "" };  // 새 문서를 열면 앞 문서의 저장 한 줄은 남의 것이다
      void openArtifact(ordinal);
    },
    closeArtifact(): void { deps.modal.close("artifactSheet"); },
    /** 「다른 이름으로 저장」 — 직접 브리지다(파일 피커가 관여). 겨눔은 **지금 열린 면의
     *  ordinal** 이고 그 값은 스냅샷에서 읽는다: 표면이 따로 기억하면 그 사이 도착한 푸시가
     *  면을 다른 문서로 바꿨을 때 보고 있는 것과 저장하는 것이 갈린다. */
    async saveArtifactAs(): Promise<void> {
      const view = (snapshot()?.artifact_view || {}) as Obj;
      const ordinal = Number(view.ordinal);
      if (!Number.isInteger(ordinal) || ordinal < 0) {
        ui = { ...ui, artifactSave: "저장할 문서를 확인할 수 없습니다." };
        emit();
        return;
      }
      try {
        const result = (await deps.client.invoke("save_artifact_as", ordinal)) as Obj;
        ui = { ...ui, artifactSave: saveArtifactMessage(result || {}) };
        emit();
      } catch (error) {
        ui = {
          ...ui,
          artifactSave: `저장하지 못했습니다. ${String((error as Obj)?.message ?? error)}`,
        };
        emit();
      }
    },
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

  deps.ports.jobRunCoordination.bind({ confirmDestructiveIfArmed });

  return controller;
}

export type JobRunController = ReturnType<typeof createJobRunController>;

export function useRun(controller: JobRunController): JobRunState & UiState {
  const state = useSyncExternalStore(controller.subscribe, controller.getRun, controller.getRun);
  const ui = useSyncExternalStore(controller.subscribe, controller.getUi, controller.getUi);
  return { ...state, ...ui };
}


/* ------------------------------------------------------------------ 표면 */

export { JobPreflight, JobWorkbenchStatus, JobStatusPill, JobRunCap } from "./job_run_views.ts";
export { isManagedHwpx, useRunSnapshot } from "./job_run_snapshot.ts";

/* 구 위험 배너(`JobDangerBanner` · `#jobMirror`)와 저장 폴더 한 줄(`JobOutFolderLine` ·
   `#jobOutDirLine`)은 legacy HWPX 생성 갈래의 표면이었다 — 문서 생성이 managed 하나가 되며
   (#1081 PR2) 구조·파일 이름 사유는 작업대 관찰·배달 계획이, 저장 폴더는 「생성 예정 문서」 머리가
   말한다. 그 배너의 복구 동사(`openRepair`)도 함께 걷혔다.

   구 재진술 블록(`JobRestate` · `#jobRestate`)은 존 재편에서 죽었다 — 「선택 N행」은 표
   머리와 필터 밖 스트립이, 「생성 N건 · 저장 폴더」는 배달 계획(`JobDelivery`)이 이미
   말하던 것이라 세 번째 발화였다. 그 수치를 정말 다시 물어야 하는 자리는
   선택을 파기하는 전이의 확인 모달 하나이고, 거기는 `composeGuardBody` 가 공유 합성기
   `selectionLine` 으로 계속 짓는다(그래서 그 합성기는 표면에 이름째 남는다). */

/** 「생성 예정 문서」 — 만들 문서의 이름·저장 자리·충돌 처분과, 계획이 서지 않은 사유.
 *
 *  존 재편에서 **좌 열**로 내려왔다(데이터 표와 `#jobResultZone` 사이): 만들 것과 만들어진
 *  것이 같은 열에서 위아래로 읽히고, 우 열은 「고르고 준비하는」 축만 든다. 렌더 조건은
 *  작업대 존과 같다(managed hwpx + 관찰 지원) — 조건이 같아도 자리가 다르므로 컴포넌트를
 *  가른다. 저장 폴더를 말하는 자리는 이제 여기 하나다(legacy hwpx 의 `JobOutFolderLine` 은
 *  #1081 PR2 에서 걷혔다). TXT(복사) 갈래는 파일을 만들지 않아 렌더 0 이다. */
export function JobDelivery(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  const wb = (s?.workbench_observation || {}) as Obj;
  if (!isManagedHwpx(s) || wb.supported !== true) return null;
  const intent = (wb.run_delivery_intent || null) as Obj | null;
  const delivery = (wb.delivery || {}) as Obj;
  const planned = (delivery.planned_documents || []) as Obj[];
  const deliveryBlockers = (delivery.blockers || []) as Obj[];
  // 저장 폴더는 backend 가 도출해 **스냅샷 최상위**로 싣는다(전역화) — 작업 유무·관찰 성패와
  // 무관한 사실이라 작업대 존이 아니라 거기가 그 자리다. 표면은 값을 그리기만 하고 경로·
  // 라벨을 여기서 다시 만들지 않는다. **고르는 동사는 여기 없다**: 저장 폴더는 작업 속성이
  // 아니라 앱 설정이 됐고, 그 자리는 설정 모달의 저장 폴더 행 하나다(아래 출구가 그 문이다).
  const outputFolder = (s?.output_folder || {}) as Obj;
  const outputFolderPath = String(
    outputFolder.directory || intent?.output_directory || '',
  );
  const outputFolderSource = String(outputFolder.source_label || '');
  const outputFolderNotice = String(outputFolder.notice || '');
  return createElement(Fragment, null,
    // 「충돌 처리」 선택기는 없다(U4 계열2-27) — 같은 이름이 있으면 덮어쓰는 것이 기본이고
    // (`DEFAULT_COLLISION_POLICY`), 그 사실은 정책 라벨이 아니라 **파일마다** 아래 목록의
    // `DELIVERY_DISPOSITION_COPY` 가 말한다. 무엇을 덮어쓰는지 묻는 확인 면은 그 다음이다.
    h('div', { className: 'zone-cap' }, '생성 예정 문서'),
    // 계획은 이름만 말하면 절반이다 — 어디에 떨어지는지, 그 경로가 **어디서 왔는지**를 같은
    // 자리에서 진술한다(#879). 출처 라벨을 빼면 「자동으로 잡힌 자리」와 「사용자가 정한
    // 자리」가 한 줄로 똑같이 보인다. 라벨 문안은 backend 가 낸 것을 그대로 싣는다.
    outputFolderPath
      ? h('p', { className: 'muted capnote', id: 'jobPlannedOutDir' },
        outputFolderSource
          ? `저장 폴더: ${outputFolderPath} (${outputFolderSource})`
          : `저장 폴더: ${outputFolderPath}`)
      : null,
    // 도출이 한 단계 내려간 사유는 경고로 선다 — 경고 침묵 금지.
    outputFolderNotice
      ? h('p', { className: 'warn capnote', id: 'jobPlannedOutDirNotice' },
        outputFolderNotice)
      : null,
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
    // 배달 blocker 의 등록된 복구 동사는 「저장 폴더 바꾸기」이고(`blocker_affordance.py`
    // REVIEW_DELIVERY), 그 동사는 설정 모달로 이사했다. 그래서 이 자리는 **문**을 세운다 —
    // 사유만 적고 갈 곳을 안 주면 막다른 경보가 된다. 열기만 하므로 생성 잠금을 타지 않는다
    // (모달 안의 「찾아보기…」가 실행 중 비활성 + 사유 병기를 진다).
    deliveryBlockers.length
      ? h('button', {
        className: 'btn sm', id: 'jobOpenFolderSettings', type: 'button',
        onClick: () => { props.controller.openOutputFolderSettings(); },
      }, '저장 폴더 설정 열기…')
      : null,
    // 「목록 새로 확인」도 없다(U4 계열2-28) — 계획은 그것을 바꾸는 전이에서 Python 이
    // 무효화하고 다시 세운다. 사람이 눌러 새로고침해야 하는 목록이면 그 자체가 결함이다.
  );
}


export function JobActionBar(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  const run = useRun(props.controller);
  const busy = run.running;
  const on = !!s?.has_job;
  const missing = on && !!s?.template_missing;
  const gate = (s?.gate || { enabled: false, level: "", text: "" }) as Obj;
  const managed = isManagedHwpx(s);
  const workbench = (s?.workbench_observation || {}) as Obj;
  const createAction = (workbench.create_action || {}) as Obj;
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
    // 확인 면 출구(A 갈래 `#jobMirrorPreviewOpen`·B 갈래 `#jobManagedPreviewOpen`)와
    // 「승인 필요」 표지(`#jobReviewFlag`)는 #957 에서 함께 사망했다. 검토 요구는 사전검증
    // `[알림]` 한 자리가 지고(같은 상태를 두 곳이 판정하지 않는다), 파괴 확인은 생성 호출의
    // `needs_overwrite` 왕복이 진다.
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
    h(TemplateRepairButton as any, { blockers: workbench.blockers, busy,
      onOpen: () => { void props.controller.openTemplateRepair(); } }),
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

/* ------------------------------------------------------------------ 템플릿 변경(S3-09) */

export {
  TPL_STATUS_COPY, tplCheckRefusalNotice, TPL_ZONE_CAP_ACTION, TPL_ZONE_CAP_SETTLED,
  TPL_STANDING_FALLBACK_COPY, TPL_RECHECK_LABEL, applyNotice,
} from "./job_run_copy.ts";

export function useTemplateChangeUi(controller: JobRunController): TemplateChangeUi {
  // 세 번째 인자(server snapshot)는 형제 훅과 같은 값이다 — 없으면 SSR 렌더가 이 구획만
  // 클라이언트 렌더로 강등돼 계약 테스트가 존 문안을 볼 수 없다.
  return useSyncExternalStore(
    controller.subscribe, controller.getTemplateChange, controller.getTemplateChange,
  );
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
  // **노출 술어는 Python 이 낸다**(#932 B5). 존이 「확인할 수 있다」는 capability 존이라
  // 웹은 그 판정을 다시 조립하지 않는다.
  //
  // `tpl.notice` 클로즈만 웹 몫이다: 적용 뒤 결과 재진술 수명은 웹이 소유한다(#659).
  if (!z.actionable && !tpl.notice) return null;
  const diagnostics = ((needsInit ? z.diagnostics : prep?.diagnostics) || []) as Obj[];
  const statusText = needsInit
    ? TPL_INITIALIZATION_REQUIRED_COPY
    : status
      ? (TPL_STATUS_COPY[status] ?? `확인 상태: ${status}`)
      : TPL_STANDING_FALLBACK_COPY;
  return h("div", { id: "jobTplChange" },
    h("div", { className: "zone-cap" }, z.actionable ? TPL_ZONE_CAP_ACTION : TPL_ZONE_CAP_SETTLED),
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
