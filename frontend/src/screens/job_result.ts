/* R4-03 결과 3태 구획 + 증거 + 실행 기록 — legacy `job.js` 의 `renderResultPanel`·
   `renderEvidence`·`failRow`·`log` 후계.

   **판정을 재조립하지 않는다**: 태·색·문안·실패 수치·판본은 전부 Python 이 낸 값 그대로다.
   여기서 다시 계산하면 판정이 두 벌이 되고, 그 둘은 따로 늙는다(판정 A).

   결과는 웹 소유 세션 상태다 — Python push 가 덮지 않는다. 결과는 **그 실행의 것**이고
   스냅샷은 **지금 상태의 것**이라 서로 후계가 아니다. 그 분리를 reducer 가 들고
   (`job_run_state.ts`), 이 파일은 그 상태를 그리기만 한다. */

import { Fragment, createElement } from "react";
import type { ReactNode } from "react";

import { PathActions } from "./path_actions.ts";
import type { JobRunController } from "./job_run.ts";
import { DELIVERY_DISPOSITION_COPY, useRun, useRunSnapshot } from "./job_run.ts";
import type { DeliveredArtifactRow } from "./job_run_state.ts";

type Obj = Record<string, any>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 실패 행 = 식별 요약 + 실파일명 + 사유. 「어느 행인가」는 표 「문서」 열과 같은 판정
 *  (Python `identity_summary`)이라 사용자가 결과에서 본 이름으로 표에서 그 행을 찾는다. */
function FailRow(props: { fail: Obj }): ReactNode {
  const f = props.fail;
  return h("div", { className: "result3-fail", id: `jobResultFail-${String(f.index)}` },
    h("div", { className: "result3-fail-name" }, `${String(f.filename || "")} 저장 실패`),
    f.identity ? h("div", { className: "result3-fail-why" }, String(f.identity)) : null,
    h("div", { className: "result3-fail-why" }, String(f.reason || "")),
    f.known ? null : h("div", { className: "result3-undiagnosed" },
      "원인 진단 미연결 — 확인된 원인이 없어 받은 메시지를 그대로 보여줍니다."));
}

/** 만들어진 문서 한 줄(S7-03 · #825) — 파일명 · 안착 처분 · 경로 어포던스 · 내용 보기.
 *
 *  값은 Python 이 낸 `delivered` 행 그대로다. 처분 라벨만 공용 어휘 지도를 지나는데, 그
 *  지도는 이 화면이 이미 다른 자리에서 쓰던 것과 **같은 하나**다(라벨을 여기서 다시 지으면
 *  같은 처분이 두 이름으로 불린다). 「내용 보기」는 실물을 다시 읽는 관찰이라 미리보기와
 *  다른 표면으로 간다(#820 D4). */
function DeliveredRow(props: {
  row: DeliveredArtifactRow;
  controller: JobRunController;
}): ReactNode {
  const row = props.row;
  const ordinal = Number(row.ordinal);
  return h("div", {
    className: "result3-doc", id: `jobResultDoc-${String(ordinal)}`,
    "data-ordinal": String(ordinal),
  },
    h("span", { className: "result3-doc-name" }, String(row.filename || "")),
    h("span", { className: "result3-doc-disp" },
      DELIVERY_DISPOSITION_COPY[String(row.disposition || "")] || "확인할 수 없음"),
    h("span", { className: "result3-doc-acts" },
      createElement(PathActions as any, {
        client: props.controller.client,
        path: String(row.path || ""),
        only: ["reveal", "copy"],
        notify: props.controller.notify,
      }),
      h("button", {
        className: "btn sm", type: "button", "data-busy-lock": true,
        "data-act": "artifact-open",
        "aria-label": `'${String(row.filename || "")}' 내용 보기`,
        onClick: (event: any) => {
          props.controller.openArtifactFrom(ordinal, event?.currentTarget ?? null);
        },
      }, "내용 보기")));
}

/** 접힘 증거 — 로그 상자가 나르던 것(FillNote 사실·받은 메시지 원문)의 거처(§10.10.3).
 *  열림 상태는 `<details>` 가 소유해 재렌더를 건넌다. */
function Evidence(props: { result: Obj }): ReactNode {
  const r = props.result;
  const notes = (r.fill_notes || []) as string[];
  const rev = (r.revisions || {}) as Obj;
  const parts: ReactNode[] = [];

  if (notes.length) {
    parts.push(h("div", { key: "notes" },
      h("b", null, `채움 주의 ${notes.length}건`),
      h("ul", null, ...notes.map((n, i) => h("li", { key: i }, String(n))))));
  }
  if (r.stage || r.message) {
    parts.push(h("div", { key: "stage" },
      h("b", null, "실패 단계"), ` ${String(r.stage || "")}`,
      h("pre", null, String(r.message || ""))));
    if (r.known === false) {
      parts.push(h("div", { key: "undiag", className: "result3-undiagnosed" }, "원인 진단 미연결"));
    }
  }
  if (r.cancelled) {
    parts.push(h("div", { key: "cancel" },
      `미착수 ${r.unstarted || 0}건 — 중단 요청 시점에 아직 시작하지 않았습니다.`));
  }
  // 사용한 판본(§13-7) — 값은 **런이 시작될 때 고정된 것**이라 그 뒤 편집 저장이 판본을
  // 올려도 여기 숫자는 그 실행이 실제로 쓴 세대를 가리킨다. 없으면 줄 자체를 만들지
  // 않는다 — 모르는 세대를 r1 로 채우지 않는다.
  if (rev.template || rev.binding) {
    parts.push(h("div", { key: "rev" },
      h("b", null, "사용한 판본"),
      ` 템플릿 r${String(rev.template || "?")} · 연결 r${String(rev.binding || "?")}`));
  }

  return h("details", { className: "result3-evidence", id: "jobResultEvidence", hidden: !parts.length },
    h("summary", { id: "jobResultEvidenceCap" },
      notes.length ? `자세히 · 채움 주의 ${notes.length}건` : "자세히"),
    h("div", { id: "jobResultEvidenceBody" }, ...parts));
}

export function JobResultZone(props: { controller: JobRunController }): ReactNode {
  const run = useRun(props.controller);
  const snapshot = useRunSnapshot(props.controller);
  const r = run.result;
  const progress = run.progress;

  // 진행바 — 취소된 배치는 **시도한 만큼**이다(#278). 무조건 100% 로 채우면 정확한 요약
  // 문안 옆에서 시각이 "완주했고 오류"라고 거짓말한다.
  let pct = 0;
  if (r !== null && !r.running && !r.rejected) {
    pct = r.cancelled && r.total ? Math.round(((r.attempted || 0) / r.total) * 100) : 100;
  } else if (progress !== null) {
    pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  }

  // 진행 중은 결과 3태를 덮지 않는다 — 같은 구획에 `running` 태로 서고, 끝나면 Python 이
  // 낸 태가 그 자리를 받는다.
  const shown: Obj | null = run.running && progress !== null
    ? { running: true, title: `생성 중… ${progress.done}/${progress.total}`, summary: "" }
    : r;

  const owner = String(snapshot?.last_run_job ?? "");
  const foreign = !(owner && snapshot?.job_name && owner === String(snapshot.job_name));
  const state = shown === null ? ""
    : shown.running ? "running" : shown.rejected ? "rejected" : String(shown.status || "failed");
  const fails = (shown?.failures || []) as Obj[];
  const hasDir = !!(shown && shown.out_dir && !shown.running && !shown.rejected);
  const selectable = Number(shown?.failed_selectable || 0);
  // 만들어진 문서 목록(S7-03) — **결과 dict 가 실은 것만** 그린다. 폴더를 훑어 목록을
  // 유추하지 않는다: 이 존이 말하는 것은 「이 실행이 앉힌 문서」이고, 그 사실의 출처는
  // 그 실행의 결과 하나다(#820 D5 — 원장·폴더 되읽기는 이 슬라이스 밖).
  const delivered = ((shown?.delivered || []) as DeliveredArtifactRow[]);

  return createElement(Fragment, null,
    h("div", { className: "zone-cap" }, "생성 결과"),
    h("div", { className: "bar" }, h("i", { id: "jobGenBar", style: { width: `${pct}%` } })),
    h("section", {
      id: "jobResult", className: "result3", "data-state": state,
      "data-level": shown?.level || "", "aria-live": "polite", hidden: shown === null,
    },
      shown === null ? null : createElement(Fragment, null,
        h("div", { className: "result3-head" },
          h("strong", { id: "jobResultTitle" }, String(shown.title || "")),
          h("div", { className: "acts" },
            // 복구 행동의 노출·라벨은 행 목록이 아니라 **Python 수치**가 정한다(1R P2):
            // 배치 진입 전 실패는 레코드별 시도가 없어 행이 0개인데 다시 만들 대상은 전량이다.
            h("button", {
              className: "btn sm", id: "jobResultFailedSel", type: "button", "data-busy-lock": true,
              hidden: !selectable || foreign, onClick: props.controller.selectFailed,
            }, `실패한 ${selectable}건만 선택`),
            h("button", {
              className: "btn sm", id: "jobResultRename", type: "button", "data-busy-lock": true,
              hidden: !!(shown.running || shown.rejected) || foreign,
              onClick: props.controller.openRenameRules,
            }, "파일 이름 규칙 수정"),
            h("button", {
              className: "btn sm", id: "jobResultClose", type: "button", "data-busy-lock": true,
              hidden: !!shown.running, onClick: props.controller.closeResult,
            }, "결과 닫기"))),
        h("p", { className: "result3-summary", id: "jobResultSummary" }, String(shown.summary || "")),
        // 강등 표기 — 무엇이 달라졌는지까지는 말하지 않는다(추측 금지). 다만 다른 작업이
        // 열려 있으면 어느 작업의 결과인지를 밝힌다: 행동이 걷힌 이유가 거기 있다.
        h("p", { className: "result3-stale", id: "jobResultStale", hidden: !shown.stale },
          !shown.stale ? ""
            : foreign && owner
              ? `이 결과는 '${owner}' 실행입니다. 지금은 그 작업이 열려 있지 않아 여기서 이어서 손볼 수 없습니다.`
              : "이 결과는 직전 실행입니다. 그 뒤 작업·데이터·선택이 바뀌었습니다."),
        h("div", { className: "result3-folder", hidden: !hasDir },
          h("span", { className: "lbl" }, "저장 폴더"),
          h("span", { className: "result3-dir", id: "jobResultDir" }, String(shown.out_dir || "")),
          // 저장 폴더 어포던스는 **실패 태에서도** 남는다 — 실패 진단의 첫 걸음이 그 폴더 열기다.
          h("span", { id: "jobResultTrack" },
            hasDir ? createElement(PathActions as any, {
              client: props.controller.client,
              path: String(shown.out_dir),
              only: ["reveal", "copy"],
              notify: props.controller.notify,
            }) : null)),
        h("section", {
          className: "result3-docs", id: "jobResultDocs",
          hidden: !delivered.length, "aria-labelledby": "jobResultDocsCap",
        },
          h("div", { className: "zone-cap zone-cap-sub", id: "jobResultDocsCap" },
            `만든 문서 ${delivered.length}건`),
          ...delivered.map((row) => createElement(DeliveredRow as any, {
            key: String(row.ordinal), row, controller: props.controller,
          }))),
        h("div", { className: "result3-fails", id: "jobResultFails" },
          ...fails.map((f, i) => createElement(FailRow as any, { key: i, fail: f }))),
        createElement(Evidence as any, { result: shown }))),
    createElement(JobRunLog as any, { controller: props.controller }));
}

/** 실행 기록 — 이 화면의 유일한 비모달 사건 채널. 접힘은 노이즈 억제지 소음 제거가
 *  아니라 **마지막 한 줄은 접힌 채로도 보인다**. */
export function JobRunLog(props: { controller: JobRunController }): ReactNode {
  const run = useRun(props.controller);
  const lines = run.log;
  return h("details", { className: "runlog", id: "jobRunLog", open: run.logOpen },
    h("summary", { onClick: props.controller.toggleLog },
      h("span", { className: "zone-cap zone-cap-sub" }, "실행 기록"),
      h("span", { className: "runlog-last", id: "jobRunLogLast" },
        lines.length ? lines[lines.length - 1] : "아직 기록이 없습니다.")),
    h("div", { className: "logbox", id: "jobGenLog" },
      lines.length ? lines.join("\n") : "이 세션에서 일어난 일이 여기에 남습니다."));
}
