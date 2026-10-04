import { createElement as h } from "react";
import type { ReactNode } from "react";
import type { AuthoringController } from "./authoring_controller.ts";
import { icon } from "./icons.ts";

export type Obj = Record<string, any>;
export type Props = { controller: AuthoringController };
/* 단추 어휘(UX-09 · #1039) — 역할이 곧 모양이다. 보조 행동 `.btn`(테두리)이 기본이고, 구획마다 하나뿐인 주 행동은
   `.btn.primary`(채움·굵게), 물러서는 행동(취소·닫기·복사…)은 `.btn.quiet`(테두리 없음), 되돌릴 수 없는 행동은
   `.btn.danger`(채움 + 동사), 그림만 선 단추는 `.btn.icon`(이름은 aria-label·title). 이동하는 줄은 단추 모양이 아니다
   — `rowButton`(목록 행)·트리 행·브레드크럼 조각·메뉴 항목이 따로 선다. 편집기 틀(머리 띠·도구 막대)은 명령을
   `.btn.quiet` 로 두고 띠마다 실행 행동 하나(저장·결과 시험)만 테두리·채움으로 세운다. */
export const button = (label: ReactNode | ReactNode[], click: (event: any) => void, props: Obj = {}) =>
  h("button", { type: "button", className: "btn", onClick: click, ...props }, ...(Array.isArray(label) ? label : [label]));
export const quiet = (label: ReactNode | ReactNode[], click: (event: any) => void, props: Obj = {}) => button(label, click, { className: "btn quiet", ...props });
export const primary = (label: ReactNode | ReactNode[], click: () => void, props: Obj = {}) => button(label, click, { className: "btn primary", ...props });
export const danger = (label: ReactNode | ReactNode[], click: () => void, props: Obj = {}) => button(label, click, { className: "btn danger", ...props });
/** 아이콘 단추 — 보이는 글자 대신 그림이 서고, 기존 이름은 접근 가능한 이름과 툴팁으로 남는다(새 문구 없음). */
export const iconButton = (name: string, label: string, click: (event: any) => void, props: Obj = {}) =>
  h("button", { type: "button", className: "btn icon", "aria-label": label, title: label, onClick: click, ...props }, icon(name));
/** 목록 행(UX-09): 종류/심각도 칩 · 본문 · 흐린 문맥 · 오른쪽 이동 화살표. 단추가 아니라 원문으로 옮겨 가는 줄이다. */
export const rowButton = (parts: { chip?: ReactNode; text: ReactNode; value?: ReactNode; context?: ReactNode }, click: () => void, props: Obj = {}) =>
  h("button", { type: "button", className: "authoring-row", onClick: click, ...props },
    parts.chip || null, h("span", { className: "authoring-row-text" }, parts.text),
    parts.value != null ? h("span", { className: "authoring-row-value" }, parts.value) : null,
    parts.context ? h("span", { className: "authoring-row-context" }, parts.context) : null,
    h("span", { className: "authoring-row-go" }, icon("chevron-right")));
/** 행 목록 — role=list 로 목록임을 밝힌다(목록 스타일을 걷어도 읽기 도구가 목록으로 센다). */
export const rowList = (label: string, rows: ReactNode[], className = "") => rows.length
  ? h("ul", { className: `authoring-rows${className ? ` ${className}` : ""}`, role: "list", "aria-label": label }, ...rows.map((row, index) => h("li", { key: index }, row))) : null;
/** 구획 이름(UX-09): 내용과 겨루지 않는 caption 크기의 이름표다 — 제목 이동을 위해 h2 의미는 그대로 둔다. */
export const sectionLabel = (text: string, props: Obj = {}) => h("h2", { className: "authoring-section-label", ...props }, text);
