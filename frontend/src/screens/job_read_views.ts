/* R4-01 job 읽기 표면의 순수 렌더 조각 — 데이터 머리·표 본문·탭·빈 데이터 안내·시트 닫기
   결속. 컨트롤러·브리지 디스패치와 후보·탐색 렌더(BrowseRow/CandidateCard/JobBrowseDialog/
   JobCandidates)는 job_read.ts가 진다. */
import { Fragment, createElement, useEffect } from "react";
import type { ReactNode } from "react";

import { JobDataZone } from "./data_zone.ts";
import { NoticeBox } from "./notice_box.ts";
import { RefreshButton } from "./refresh_button.ts";
import { SheetTabs } from "./sheet_tabs.ts";
import type { JobReadController, Obj } from "./job_read.ts";
import { h, useJob, useUi } from "./job_read.ts";

export function JobDataHeader(props: { controller: JobReadController }): ReactNode {
  const snapshot = useJob(props.controller);
  if (snapshot === null) return h("p", { className: "muted", role: "status" }, "데이터 상태를 읽는 중…");
  const notice = snapshot.data_notice;
  return createElement(Fragment, null,
    h("div", { className: "zone-cap job-data-heading", "data-loaded": snapshot.has_data },
      h("span", { className: "job-data-name", id: "jobDataLabel",
        title: snapshot.data_label || "현재 데이터" },
        snapshot.has_data ? snapshot.data_label : "현재 데이터"),
      h("div", { className: "job-data-actions" },
        h("button", { className: snapshot.has_data ? "btn quiet sm" : "btn primary",
          id: "jobBtnPickData", type: "button", "data-busy-lock": true,
          onClick: props.controller.openDataPicker }, snapshot.has_data ? "변경…" : "데이터 선택…"),
        createElement(RefreshButton, {
          id: "jobBtnRemountData", label: "데이터 새로고침", disabled: !snapshot.has_data,
          onRefresh: props.controller.remountData, notify: props.controller.notify,
        }))),
    /* 결속 복구는 Python 판정을 그대로 따르며 조용한 교체 동작과 별도로 강조한다. */
    snapshot.job_data_unbound
      ? h("div", { className: "run-row" }, h("button", { className: "btn primary sm", id: "jobConnectData", type: "button",
          "data-busy-lock": true,
          title: "이 작업에 데이터를 연결해야 문서를 만들 수 있습니다.",
          onClick: () => { void props.controller.connectJobData(); } }, "데이터 연결하기…"))
      : null,
    /* 데이터 통지(U4 §2.12 · #945) — 상자·닫기는 `NoticeBox` 가, 문안 조립(「확인 필요: 」
       접두)과 레벨 판정은 여기가 그대로 진다. 이 채널은 매 변이 자동 소멸이 아니라
       **사유가 해소될 때까지 남는** 수동 소멸이라 닫기 동사를 가진다. */
    notice?.text
      ? createElement(NoticeBox, {
        id: "jobDataNotice",
        closeId: "jobDataNoticeClose",
        level: notice.level === "ok" ? "quiet" : "warn",
        text: `${notice.level === "ok" ? "" : "확인 필요: "}${notice.text}`,
        onClose: () => { void props.controller.dismissDataNotice(); },
      })
      : h("div", { id: "jobDataNotice", className: "note", hidden: true }));
}

/* R5-02: 미착좌 JobDataHeaderPortal은 생산·소비가 모두 0이라 제거했다.
   JobDataHeader는 ProductScreens의 job 화면이 직접 소유하고,
   JobReadEffects는 같은 화면의 effect 슬롯이 별도로 착좌한다.
   둘을 다시 묶는 compatibility component는 두 번째 수명주기 경로가 된다.
   아래 표 body와 browse surface의 현재 좌표를 보존해 ownership 증거가
   unrelated line churn으로 흐려지지 않도록 이 제거 기록을 같은 8행에 둔다.
   실행 코드·export·fallback은 남기지 않는다.
*/

function JobTableScroll(props: { wrapRef: Obj; hidden?: boolean; children?: ReactNode }): ReactNode {
  return h("div", {
    className: "tbwrap jobtbwrap",
    id: "jobTableWrap",
    hidden: props.hidden,
    "data-preserve-scroll": true,
    ref: props.wrapRef,
  }, props.children);
}

export function JobDataBody(props: { controller: JobReadController; location: "inline" | "sheet" }): ReactNode {
  const snapshot = useJob(props.controller);
  const ui = useUi(props.controller);
  if (snapshot === null) return null;
  if ((props.location === "sheet") !== ui.sheetOpen) return null;
  return h(JobDataZone as any, { snapshot, controller: props.controller, scroll: JobTableScroll,
    tabs: props.location === "inline" ? h(JobDataTabs as any, { controller: props.controller }) : null });
}

export function JobDataTabs(props: { controller: JobReadController }): ReactNode {
  const { controller } = props;
  const snapshot = useJob(controller);
  const ui = useUi(controller);
  return h(SheetTabs as any, {
    rows: snapshot?.data_sheet_tabs || [], busy: !!ui.switchingData, locked: !!ui.openingName,
    onPick: (row: Obj) => { void controller.switchData(row.key, row.sheet); },
    onReorder: (key: string, sheets: string[]) => controller.reorderSheets(key, sheets),
  });
}

export function NewWorkButton(props: { snapshot: Obj; controller: JobReadController }): ReactNode {
  const ui = useUi(props.controller);
  const gate = props.snapshot.new_work || { can: true, reason: "" };
  return createElement(Fragment, null,
    h("button", { className: "btn sm", type: "button", id: "jobCandNewWork", "data-new-work": gate.can === false ? undefined : true,
      "data-busy-lock": gate.can === false ? undefined : true, disabled: gate.can === false || !!ui.switchingData, title: gate.reason || "",
      onClick: () => { void props.controller.newWorkFromData(); } }, "＋ 이 데이터로 새 작업"),
    gate.can === false ? h("span", { className: "cand-newwork-why muted" }, gate.reason) : null);
}

export function JobNoDataExit(props: { controller: JobReadController }): ReactNode {
  const snapshot = useJob(props.controller);
  if (snapshot === null || snapshot.has_data || snapshot.has_job) return null;
  return h("div", { className: "job-read-side-content" }, h("div", { className: "zone-cap" }, "시작하기"),
    h("p", { className: "muted capnote" }, "데이터를 먼저 고르면 그 데이터로 쓸 수 있는 문서 작업이 여기에 표시됩니다."),
    h("p", { className: "muted capnote" }, "쓸 작업을 이미 알고 있다면 「문서 작업」에서 고른 뒤 문서 만들기에서 사용을 누르세요."),
    h("button", { className: "btn sm", id: "jobPickInLibrary", type: "button",
      onClick: () => props.controller.navigation.go("library") }, "「문서 작업」에서 고르기"));
}

/** static data-sheet shell의 닫기 버튼을 React 수명주기에 결속한다. */
export function JobReadEffects(props: { controller: JobReadController; closeButton: HTMLElement }): null {
  useEffect(() => {
    const close = () => props.controller.closeDataSheet();
    props.closeButton.addEventListener("click", close);
    return () => props.closeButton.removeEventListener("click", close);
  }, [props.controller, props.closeButton]);
  return null;
}
