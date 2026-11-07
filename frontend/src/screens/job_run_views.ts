/* R4-03 실행 표면의 순수 렌더 조각 — 사전검증 배너·작업대 관찰 구획·상태 pill·준비 캡션.
   행동 막대·배달·템플릿 변경(`JobActionBar`·`JobDelivery`·`JobTemplateChange`)은 job_run.ts가
   진다. `JobWorkbenchStatus`의 「데이터 확인」·「입력이 필요한 항목」 구획은 React 컴포넌트가
   아니라 `render<X>(props)` 일반 함수로 같은 자리에 그린다(구획의 재마운트 동작이 그대로다). */
import { Fragment, createElement } from "react";
import type { ReactNode } from "react";

import type { JobRunController, Obj } from "./job_run.ts";
import { h, isManagedHwpx, useRunSnapshot } from "./job_run.ts";

export function JobPreflight(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  const p = (s?.preflight || {}) as Obj;
  if (!s?.has_data || !p.text) return null;
  const cls = p.level === "ok" ? "quiet" : p.level === "danger" ? "dangerbox" : "warnbox";
  return h("div", { className: `preflight note ${cls}`, style: { whiteSpace: "pre-line" } },
    String(p.text));
}

/** record validation issue 목록 — 문제마다 위치 보기 단추를 낸다. 중첩된 `<li>` 목록이라
 *  소유 함수 안에 그대로 두면 그 중첩만큼 함수가 커지므로 별도 렌더 함수로 둔다. */
function renderRecordIssuesList(props: { controller: JobRunController; issues: Obj[] }): ReactNode {
  const { controller, issues } = props;
  return h('ul', { className: 'plain-list', id: 'jobRecordValidationIssues' },
    ...issues.map((issue) => h('li', {
      key: `${String(issue.record_identity)}:${String(issue.field_id)}`,
    },
    h('span', null,
      `${String(issue.record_display_locator)} · ${String(issue.field_display_label)} · `,
      String(issue.message || '')),
    h('button', {
      className: 'btn sm', type: 'button',
      onClick: () => { void controller.recoverRecordIssue(issue.recovery_target as Obj); },
    }, '문제 위치 보기'))));
}

/** record validation의 본문 — 문제 목록이 있으면 그것, 없으면 확인 건수, 둘 다 없으면
 *  빈 자리(비차단 고지는 `renderRecordSection`이 그 옆에 따로 그린다). */
function renderRecordBody(
  props: { controller: JobRunController; issues: Obj[]; validatedCount: number },
): ReactNode {
  const { controller, issues, validatedCount } = props;
  if (issues.length) return renderRecordIssuesList({ controller, issues });
  if (validatedCount > 0) {
    return h('p', { className: 'muted capnote' }, `${validatedCount}건의 데이터를 확인했습니다.`);
  }
  return null;
}

/** record validation이 선 「데이터 확인」 구획 — context error 가 아닌 나머지 경우. */
function renderRecordStatus(props: { controller: JobRunController; wb: Obj }): ReactNode {
  const { controller, wb } = props;
  const recordValidation = (wb.record_validation || {}) as Obj;
  const issues = (recordValidation.issues || []) as Obj[];
  const recordAdvisory = String(recordValidation.advisory_notice || '');
  const validatedCount = Number(recordValidation.validated_count || 0);
  if (!(issues.length > 0 || validatedCount > 0 || !!recordAdvisory)) return null;
  return createElement(Fragment, null,
    h('div', { className: 'zone-cap' }, '데이터 확인'),
    renderRecordBody({ controller, issues, validatedCount }),
    // 비차단 고지(#957) — blocker 목록과 **다른 줄·다른 색**이다. 문안은 backend 가
    // 낸 것을 그대로 그린다(수치·판정을 여기서 다시 조립하지 않는다).
    recordAdvisory
      ? h('p', { className: 'warn capnote', id: 'jobRecordValidationAdvisory' },
        recordAdvisory)
      : null);
}

/** 「데이터 확인」 구획 — record validation 결과·context error 안내를 짓는다.
 *  `JobWorkbenchStatus`가 쥐던 지역 상수 하나를 모듈 함수로 승격했을 뿐 로직은 그대로다. */
function renderRecordSection(props: { controller: JobRunController; wb: Obj }): ReactNode {
  const { controller, wb } = props;
  if (wb.kind === 'context_error') {
    return createElement(Fragment, null,
      h('div', { className: 'zone-cap' }, '데이터 확인'),
      h('p', { className: 'danger capnote' },
        String(wb.detail || '현재 데이터를 확인할 수 없습니다.')));
  }
  return renderRecordStatus({ controller, wb });
}

/** 「입력이 필요한 항목」 구획 — U3-03(#876): backend 가 조치 필요만 실어 준다. */
function renderInputRequirementSection(
  props: { controller: JobRunController; wb: Obj; items: Obj[] },
): ReactNode {
  const { controller, wb, items } = props;
  // 0건이면 라벨까지 포함해 구획을 안 세운다 — 손댈 것이 없는데 「입력이 필요한 항목」이
  // 상시로 서 있으면 그 자체가 잘못된 진술이다.
  if (!items.length) return null;
  return createElement(Fragment, null,
    h("div", { className: "zone-cap" }, String(wb.input_requirements_label || "")),
    h("ul", { className: "plain-list", id: "jobInputRequirements" },
      ...items.map((item) => h("li", {
        key: String(item.field_id),
        "data-binding-state": String(item.binding_state || ""),
      },
      h("span", null, String(item.display_label || "")),
      item.action_required === true
        ? h("button", {
            className: "btn sm", type: "button",
            "data-exact-target": String(item.exact_target || ""),
            onClick: () => { void controller.openBindingRequirement(
              String(item.exact_target || ""), String(item.display_label || "")); },
          }, "수정…")
        : null))));
}

/** `JobWorkbenchStatus`가 그릴지·무엇을 그릴지 판정하는 입력 — managed hwpx + 관찰 지원이
 *  아니면 `null`(렌더 0). 게이트·기본값 분기를 여기 모아 렌더 함수 자신은 그 결과만 쓴다. */
function resolveWorkbenchView(
  s: Obj | null,
): { wb: Obj; items: Obj[]; executionAction: Obj | null; recoverAction: Obj | null } | null {
  const wb = (s?.workbench_observation || {}) as Obj;
  if (!isManagedHwpx(s) || wb.supported !== true) return null;
  return {
    wb,
    items: (wb.input_requirements || []) as Obj[],
    executionAction: (wb.execution_action || null) as Obj | null,
    // context error 의 복구 동사(#912 D4). execution_action 과 배타다 — 관찰이 무너진
    // 자리에는 「현재 설정 확인」이 아니라 복구가 서고, 어느 쪽이든 **backend 가 실은 것만**
    // 그린다.
    recoverAction: (wb.recover_action || null) as Obj | null,
  };
}

export function JobWorkbenchStatus(props: { controller: JobRunController }): ReactNode {
  const s = useRunSnapshot(props.controller);
  const view = resolveWorkbenchView(s);
  if (!view) return null;
  const { wb, items, executionAction, recoverAction } = view;
  /* 「현재 실행 상태」 캡션 + 상태 문안은 걷혔다: `execution_status_phrase` 는 우상단 상태
     pill(`JobStatusPill`)이 managed 갈래에서 **그대로** 그리는 바로 그 문자열이라, 이 자리에
     한 벌 더 두면 같은 사실이 한 화면에서 두 번 발화한다. 남는 것은 그 상태를 **바꾸는 동사**
     둘(`#jobResolveExecution`·`#jobRecoverContext`)이고, 그 좌표는 blocker 어포던스 표가 든다. */
  return createElement(Fragment, null,
    renderInputRequirementSection({ controller: props.controller, wb, items }),
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
    recoverAction
      ? h("div", { className: "run-row" },
          h("button", {
            className: "btn sm", type: "button", id: "jobRecoverContext",
            disabled: recoverAction.enabled !== true,
            onClick: () => { void props.controller.recoverContext(); },
          }, String(recoverAction.label || "")),
          h("span", { className: "muted capnote" },
            String(recoverAction.disabled_reason || "")))
      : null,
    renderRecordSection({ controller: props.controller, wb }));
}

/** 실행 표면이 작업대인가 — 판정은 Python 이 낸 `run_action.key` 하나를 읽는다. 표면이
 *  확장자·매체를 다시 읽어 분기하면 같은 판정이 두 곳에 산다(F6 판정 D). */
function isCopyWork(s: Obj | null): boolean {
  return !!(s && s.run_action && s.run_action.key === "workbench");
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
      // 「승인 필요」 갈래는 #957 에서 사망했다 — 검토는 더 이상 생성을 막지 않으므로
      // 이 자리에 규칙축 차단이 서지 않는다. 남는 것은 전부 「확인 필요」다.
      level = "warn";
      text = "확인 필요";
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

