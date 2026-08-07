/* R4-03 확인 면(생성 값 미리보기) — legacy `job.js` 의 `renderPreview`·`renderPreviewEvidence`
   후계.

   **이 표면은 모듈 상태를 하나도 늘리지 않는다**: 열림·자리·값·이름·증거가 전부 스냅샷
   (`s.preview`)에서 온다(판정 A·M). 여는 것은 사용자 클릭이 아니라 Python 이 "열렸다"고
   말한 사실이고, DOM 개폐만 그 상태를 따라간다.

   가용성(이전·다음·빈 값 한정)도 Python 이 낸다 — 표면이 `pos`/`total` 로 재유도하면
   「빈 값 있는 건만 보기」가 켜졌을 때 경계가 그 건들의 처음·끝으로 바뀌는 것을 놓쳐
   판정이 갈린다. */

import { Fragment, createElement } from "react";
import type { ReactNode } from "react";

import type { JobRunController } from "./job_run.ts";
import { useRun, useRunSnapshot } from "./job_run.ts";

type Obj = Record<string, any>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

function shownValue(value: unknown): ReactNode {
  return value ? String(value) : h("em", { className: "muted" }, "(빈 값)");
}

function ValueRow(props: { row: Obj; controller: JobRunController }): ReactNode {
  const row = props.row;
  const name = String(row.name || "");
  return h("div", { className: "mir-row", "data-field": name },
    h("span", { className: "mir-name" }, name),
    h("span", { className: "mir-val" }, shownValue(row.value)),
    // 행별 「수정」(F6 PR-B deep-link, §10.14.3) — 이상한 값을 본 그 자리에서 그 필드의
    // 탭으로 간다. target 조립·발신은 `previewFix` 하나(파일 이름 「수정」과 단일 경로).
    h("button", {
      className: "btn sm", "data-act": "preview-fix", "data-field": name,
      "aria-label": `'${name}' 연결 수정`,
      onClick: () => { void props.controller.previewFixField(name); },
    }, "수정"));
}

/** before 는 **있을 때만** 그린다(F7 판정 H): 직전 판본이 없는 작업에 빈 값을 세우면
 *  "이전엔 비어 있었다"는 거짓 증거가 된다. */
function EvidenceRow(props: { row: Obj }): ReactNode {
  const row = props.row;
  const hasBefore = Object.prototype.hasOwnProperty.call(row, "before");
  return h("div", { className: "mir-row", "data-field": String(row.name || "") },
    h("span", { className: "mir-name" }, String(row.name || "")),
    h("span", { className: "mir-val" },
      hasBefore ? createElement(Fragment, null,
        h("span", { className: "ev-before" }, shownValue(row.before)), " → ") : null,
      shownValue(row.value),
      row.note ? h("span", { className: "doc-sum" }, String(row.note)) : null));
}

export function JobPreviewSheet(props: { controller: JobRunController }): ReactNode {
  const snapshot = useRunSnapshot(props.controller);
  const run = useRun(props.controller);
  const p = (snapshot?.preview || {}) as Obj;
  const ev = (p.evidence || {}) as Obj;
  const evRows = (ev.rows || []) as Obj[];
  const rows = (p.rows || []) as Obj[];
  const busy = run.running;
  const hasEvidence = !!(evRows.length || ev.note || ev.reason);

  return h("div", { className: "modal-card sheet-card preview-drawer" },
    h("div", { className: "sheet-head" },
      h("h3", { id: "previewTitle" }, "생성 값 미리보기"),
      h("button", {
        className: "btn", id: "previewClose", type: "button",
        onClick: props.controller.closePreview,
      }, "닫기")),
    h("div", { className: "sheet-body preview-sheet-body" },
      h("p", { className: "modal-sub" },
        "이 이름으로 이 값이 나갑니다. 미리보기를 여는 것과 승인은 다른 일입니다."),

      h("div", { className: "preview-nav" },
        h("button", {
          className: "btn sm", id: "previewPrev", "data-busy-lock": true, "aria-label": "이전 문서",
          disabled: busy || !p.total || !p.can_prev,
          onClick: () => props.controller.previewMove(-1),
        }, "‹"),
        h("strong", { id: "previewPos" }, `${(p.pos || 0) + 1} / ${p.total || 0}`),
        h("button", {
          className: "btn sm", id: "previewNext", "data-busy-lock": true, "aria-label": "다음 문서",
          disabled: busy || !p.total || !p.can_next,
          onClick: () => props.controller.previewMove(1),
        }, "›"),
        // 「빈 값 있는 건만 보기」 — 상태는 Python 소유라 스냅샷을 되읽는다(낙관 토글 없음,
        // #215 동류). 빈 값 건이 0이면 한정할 대상이 없어 비활성(무동작 토글 금지).
        h("button", {
          className: "btn sm", id: "previewBlankOnly", type: "button", "data-busy-lock": true,
          "aria-pressed": p.blank_only ? "true" : "false",
          disabled: busy || !p.blank_count,
          onClick: () => props.controller.previewBlankOnly(!p.blank_only),
        }, "빈 값 있는 건만 보기")),

      h("p", {
        id: "previewEmpty", className: "note", role: "status", "aria-live": "polite",
        style: { display: p.empty_note ? "" : "none" },
      }, String(p.empty_note || "")),

      h("section", {
        className: "picker-sec", id: "previewEvidence",
        style: { display: hasEvidence ? "" : "none" }, "aria-labelledby": "previewEvidenceCap",
      },
        h("div", { className: "cap", id: "previewEvidenceCap" }, "확인할 변경"),
        h("p", {
          className: "muted capnote", id: "previewEvidenceReason",
          style: { display: ev.reason ? "" : "none" },
        }, String(ev.reason || "")),
        h("div", { id: "previewEvidenceRows" },
          ...evRows.map((row, i) => createElement(EvidenceRow as any, { key: i, row }))),
        h("p", {
          className: "muted capnote", id: "previewEvidenceNote",
          style: { display: ev.note ? "" : "none" },
        }, String(ev.note || ""))),

      h("section", { className: "picker-sec", "aria-labelledby": "previewValuesCap" },
        h("div", { className: "cap", id: "previewValuesCap" }, "채울 값"),
        h("div", { id: "previewRows" },
          ...rows.map((row, i) => createElement(ValueRow as any, {
            key: String(row.name || i), row, controller: props.controller,
          })))),

      h("div", { className: "preview-foot" },
        h("div", null,
          h("span", { className: "muted capnote" }, "파일 이름"),
          h("strong", { id: "previewFilename" }, String(p.filename || "")),
          h("button", {
            className: "btn sm", id: "previewFixFilename", "aria-label": "파일 이름 규칙 수정",
            onClick: () => { void props.controller.previewFixFilename(); },
          }, "수정")),
        // 이름 계획 한 줄(U2 §2.13) — 개별 이름은 ‹ › 훑기가 말하고 여기는 집합만 말한다.
        h("div", null,
          h("span", { className: "muted capnote" }, "이름 계획"),
          h("span", { className: "muted", id: "previewNamePlan" },
            `${p.total || 0}건 · 저장 폴더: ${snapshot?.out_dir || "미지정"}`))),

      h("div", { className: "modal-actions" },
        h("button", {
          className: "btn", id: "previewEdit", onClick: props.controller.previewEdit,
        }, "이 작업 편집"),
        // 승인 버튼은 **요구가 남아 있을 때만** 선다. 없는 사건의 버튼을 회색으로 두면
        // "여기서 뭔가 해야 하나" 하는 미끼가 된다.
        h("button", {
          className: "btn primary", id: "previewApprove",
          style: { display: p.can_approve ? "" : "none" },
          onClick: props.controller.previewApprove,
        }, "이 이름과 값으로 승인"))));
}
