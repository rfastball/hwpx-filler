import { createElement as h } from "react";
import type { ReactNode } from "react";
import type { AuthoringController } from "./authoring_controller.ts";
import type { LiveState } from "./authoring_a11y.ts";
import type { Obj } from "./authoring_primitives.ts";
import type { zoomChoice } from "./authoring_editor.ts";

export function renderAuthoringFooter({ item, controller, liveNow, openDock, zoom }: {
  item: Obj | undefined; controller: AuthoringController; liveNow: LiveState;
  openDock: (key: string) => void; zoom: ReturnType<typeof zoomChoice>
}): ReactNode {
  return     item && h("footer", { className: "authoring-status", role: "group" },
      // 왼쪽: 저장·준비와 구조 검사. 오른쪽: 보존·복원·시험. 구분선은 CSS 가 그린다(글자가 아니다).
      h("div", { className: "authoring-status-group" },
        // 저장·검사·시험은 서로 다른 상태다(P09·§9.1): 저장됨 뒤에 Python 의 readiness(초안/사용 준비)를 붙인다.
        h("span", null, liveNow.save),
        // 구조 오류가 있으면 Python 의 준비 문장(readiness.message)을, 없으면 개수를 보인다. 수는 문제 탭 배지와 같은
        // problems 에서 센다 — 문제가 있으면 그 표현이 문제 탭으로 가는 글 링크 모양 단추다(IDE-01).
        item.problems?.length ? h("button", { type: "button", className: "authoring-status-link", onClick: () => openDock("problems") }, liveNow.readinessText)
          : h("span", null, liveNow.readinessText)),
      h("div", { className: "authoring-status-group authoring-status-end" },
        // 준비 상태 옆의 보존 판정 칩 — Python 의 compatibility.state 를 이름으로 옮길 뿐이다(마운트 전에도 선다).
        item.compatibility?.state === "checking" && h("span", { "data-compat": "checking" }, "보존 확인 중"),
        item.compatibility?.state === "limited" && h("span", { "data-compat": "limited" }, "읽기 전용 · 보존 확인 필요"),
        item.restore?.message && h("span", { "data-restore": item.restore.state }, item.restore.message),
        // 결과 시험 상태는 상태마다 한 표현이다 — Python 의 trial_state_label 그대로(P09·§9.1). 시험을 한 뒤에만 서고,
        // 누르면 결과 시험 탭을 연다(IDE-01). 시험 자료 표지는 보관한 케이스나 저장하지 않은 입력이 있을 때만 선다.
        item.trial_state !== "untried" && item.trial_state_label && h("button", { type: "button", className: "authoring-status-link", "data-trial": item.trial_state, onClick: () => openDock("trial") }, item.trial_state_label),
        (item.cases_dirty || !!item.cases?.length) && h("span", null, item.cases_dirty ? "시험 자료: 저장하지 않은 변경" : "시험 자료: 로컬 보관"),
        // 확대는 상태 막대 끝의 작은 선택이다(편집기 관례) — 도구 막대의 roving 묶음 밖, 보통 Tab 순서다.
        h("select", { className: "field authoring-zoom", "aria-label": "확대", value: zoom.value, onChange: (event: any) => controller.setZoom(event.target.value === "fit" ? "fit" : Number(event.target.value)) },
          ...zoom.options.map(([value, label]) => h("option", { key: value, value }, label)))));
}
