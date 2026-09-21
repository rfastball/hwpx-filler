/* R4-02 문서 작업 편집기의 React 표면(legacy `frontend/js/screens/editor.js`). */
import { createElement, Fragment, useEffect, useRef, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import { disposeLintpad, mountLintpad, updateLintpad } from "../editorview/txt_lintpad.ts";
import type { LintpadHandle, LintpadSpan } from "../editorview/txt_lintpad.ts";
import { ContextMenu } from "./context_menu.ts";
import { DETAIL_SHEET_EMPTY, DetailSheetFrame } from "./detail_sheet.ts";
import { NoticeBox } from "./notice_box.ts";
import { invokePathAction } from "./path_actions.ts";
import { PreviewCell } from "./preview_cell.ts";
import {
  PCLM_UNAVAILABLE, ROW_DETAIL_LABEL, mergeSessionRow, poolHeadSub,
} from "./pool_verbs.ts";
import { PoolColumn, SESSION_DATA_KEY } from "./pool_column.ts";
import type { PoolColumnHost } from "./pool_column.ts";
import { NAME_FIELD, PATTERN_FIELD, hasPendingEdits, rowField, valueOf } from "./editor_state.ts";
import type { DraftState } from "./editor_state.ts";
import { libRowMenuItems } from "./editor_controller.ts";
import type { EditorController, Obj, TxtLintState, ViewState } from "./editor_controller.ts";

export { createEditorController, libRowMenuItems } from "./editor_controller.ts";
export type { EditorController, EditorControllerDeps } from "./editor_controller.ts";

const INFERRED_LABEL: Record<string, string> = {
  text: "텍스트", date: "날짜", amount: "금액", number: "숫자", phone: "전화번호",
};
/** 매핑 행 상태 → class. Python 이 내는 닫힌 집합 넷과 1:1. */
export const ROW_STATE_CLASS: Record<string, string> = {
  suggested: "r-suggested", edited: "r-edited",
  confirmed: "r-confirmed", needs_source: "r-needs-source",
};
const ROW_BADGE_CLASS: Record<string, string> = {
  suggested: "sugg", edited: "warn", confirmed: "ok", needs_source: "warn",
};
const NOT_CONFIRMABLE_HINT = "열을 고르거나 고정값·오늘 날짜를 고르세요";
const SECTION_TITLES: Record<string, string> = {
  template: "고르기", binding: "연결 확인", filename: "이름·저장",
};
const isEditing = (snapshot: Obj): boolean => !!snapshot.editing_origin;
/* ---- 표현 ---- */

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

function stageTitle(snapshot: Obj, section: string): string {
  const title = SECTION_TITLES[section] || section;
  if (isEditing(snapshot)) return title;
  const index = (snapshot.sections || []).indexOf(section);
  return index < 0 ? title : `${index + 1}단계: ${title}`;
}

function gateHint(snapshot: Obj): string {
  /* 1단계의 사유는 **Python 이 낸다**(`pairing.advance_block_reason`) — 좌·우 어느 쪽이
     비었는지에 따라 고칠 자리가 갈리는데, 그 판정을 여기서 다시 하면 게이트와 문안이
     서로 다른 상태를 말하게 된다(U6-B #976). */
  if (snapshot.section === "template") {
    return String((snapshot.pairing || {}).advance_block_reason || "");
  }
  if (snapshot.section === "binding") return "전 행을 확정해야 진행할 수 있습니다";
  return "";
}

/** 머리 부제 — 「{템플릿} ⟷ {데이터}」 한 줄(동결 시안 장면 2·3 머리와 같다).
 *
 *  1단계에서는 연결 카드가 같은 말을 하지만 2·3단계에는 그 카드가 없다. 단계마다 다른
 *  문형을 세우면 같은 사실이 두 어휘를 갖는다 — 한 줄로 통일한다. **짝이 다 서기 전에는
 *  침묵한다**(2026-09-03 재판정): 「템플릿을 아직 고르지 않았습니다 ⟷ gg」 는 1단계 연결
 *  카드가 이미 하는 말의 되풀이였다. */
function pairLine(snapshot: Obj): string {
  const pairing = (snapshot.pairing || {}) as Obj;
  const template = String(pairing.template_name || "");
  const data = String(pairing.data_name || "");
  return template && data ? `${template} ⟷ ${data}` : "";
}

/** 머리 — 이 세션이 **무엇을 편집 중인가**와 그 저장 상태.
 *
 *  작업 이름 입력은 U6-D(#978)에서 3단계 「이름·저장」 폼으로 옮겼다. 라벨 없이 제목 자리에
 *  사는 입력이라 저장 게이트가 「작업 이름을 입력하세요」라고 말해도 사람이 찾지 못하던
 *  자리다(`SaveVerdict.blocked_field` 의 주석이 그 사실을 적고 있었다). 머리에 남은 것은
 *  제목(부제와 같은 짝 한 줄)과 상태 pill 이고, **소유는 여전히 세션**이다 — 이름은 어느
 *  section patch 에도 속하지 않아 탭 이동의 자동 버리기가 건드리지 않는다(판정 L). */
function EditorHead(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot } = props;
  const dirty = !!snapshot.dirty;
  const level = snapshot.is_draft ? "idle" : (dirty ? "warn" : "idle");
  /* 머리는 **상태만** 말한다(#945 F5). 저장 세대 카운터(`revisions`)는 규칙이 갈릴 때 오르는
     내부 어휘라 여기서 읽는 사람에게 아무 행동도 주지 않는다 — 스냅샷 키와 도메인 축은
     그대로 살고, 판본을 실제로 대조하는 자리(실행 결과 증거·작업 목록)가 계속 든다. */
  const stateText = snapshot.is_draft
    ? "아직 저장하지 않은 새 작업"
    : (dirty ? "저장하지 않은 변경" : "저장됨");
  return h("header", { className: "scr-head editor-head" },
    h("div", null,
      h("p", { className: "eyebrow" }, "문서 작업 편집기"),
      /* 제목은 **읽기 전용 정체**다. 초안은 아직 이름이 없을 수 있어(고르기 전) 그때는
         이름 없는 새 작업이라고 말한다 — 빈 제목은 화면이 무엇을 편집 중인지 말하지 않는다. */
      h("h1", { id: "editorTitle" }, String(snapshot.name || "새 작업")),
      pairLine(snapshot) ? h("p", { className: "sub", id: "editorSubtitle" }, pairLine(snapshot)) : null),
    h("div", { className: "status", id: "editorSaveState", "data-level": level }, stateText));
}

/** 진입 문맥 배너 — **증거가 있을 때만** 선다(2026-09-03 재판정). 사유 문장(「…에서
 *  열었습니다」)과 복귀 버튼은 걷혔다: 방금 거기서 온 사람에게 출처는 새 정보가 아니고, 복귀는
 *  왼쪽 위 「← 원래 업무로 돌아가기」 가 같은 곳으로 간다. 남는 것은 진입이 실어 온 **사실**
 *  (실패한 행 · 입력이 필요한 항목 · 고칠 것)뿐이고, 값이 빈 증거는 줄을 세우지 않는다. */
function ContextBanner(props: { snapshot: Obj }): ReactNode {
  const context = props.snapshot.context || {};
  const evidence = (context.evidence || {}) as Obj;
  const rows = Object.keys(evidence).filter((key) => String(evidence[key] ?? "") !== "")
    .map((key) => h("span", { key }, h("b", null, key), " ", String(evidence[key])));
  if (!rows.length) {
    return h("section", { className: "note ctxbanner", id: "editorContext", style: { display: "none" } });
  }
  return h("section", { className: "note ctxbanner", id: "editorContext" },
    h("div", { className: "ctx-ev" }, ...rows));
}

function StepHeader(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  const sections = (snapshot.sections || []) as string[];
  const here = sections.indexOf(snapshot.section);
  const children = isEditing(snapshot)
    ? sections.map((section) => h("button", {
      className: `wstep-tab as-tab${(snapshot.dirty_sections || []).includes(section) ? " dirty" : ""}`,
      "data-act": "goto-tab", "data-section": section, key: section,
      "aria-current": section === snapshot.section ? "true" : undefined,
      onClick: () => controller.guarded(() => controller.gotoSection(section)),
    }, SECTION_TITLES[section] || section))
    : sections.map((section, index) => h("div", {
      className: `wstep-tab${index < here ? " done" : ""}`, key: section,
      "aria-current": section === snapshot.section ? "true" : undefined,
    }, h("span", { className: "k" }, String(index + 1)), SECTION_TITLES[section] || section));
  return h("div", { className: "wsteps", id: "editor-steps", "aria-label": "문서 작업 편집 영역" },
    ...children);
}

/** 좌 열 — 「템플릿」 풀. 정본은 `tpl` 채널 스냅샷의 **공용 열 존**(`column`)이고 선택
 *  표지만 편집기 스냅샷이 준다(`pairing.template_key`).
 *
 *  hwpx·txt 를 **한 목록으로** 그리고 매체는 pill 로 가른다(동결 시안 장면 1): 루트가
 *  하나가 된 뒤(U6-A) 두 밴드는 같은 폴더의 두 확장자일 뿐이라, 구획으로 가르면 「어디에
 *  무엇이 있나」를 사람이 두 번 훑게 된다. 그 목록을 **한 목록으로 접는 일도 이제 Python
 *  이 한다** — 이 자리는 호스트만 세운다(고르기 열 공용 ②).
 *
 *  바닥에는 「파일 가져오기…」·「서식 폴더 열기」만 둔다. */
function TemplatePool(props: {
  tpl: Obj | null; snapshot: Obj; controller: EditorController;
}): ReactNode {
  const { tpl, snapshot, controller } = props;
  const root = (tpl || {}).templates_root || {};
  const pairing = (snapshot.pairing || {}) as Obj;
  const host: PoolColumnHost = {
    side: "tpl",
    rootId: "editorTplPool",
    listId: "editorTplList",
    title: "템플릿",
    headSub: "서식 폴더",
    headSubTitle: String(root.directory || ""),
    /* 선택 표지의 정본은 **편집기 스냅샷의 키**다(고르기 열 공용 ①) — 종전에는 경로
       문자열을 좌 열이 직접 대조했고, 그러면 같은 사실을 Python 과 표면이 각자 잰다. */
    selectedKey: String(pairing.template_key || ""),
    choose: (key: string) => controller.guarded(() => controller.chooseTemplate(key)),
    drop: (sourceSide: string, sourceKey: string, targetKey: string) =>
      controller.guarded(() => controller.dropPair(sourceSide, sourceKey, targetKey)),
    /* ⋮ 가 겨누는 매체는 행이 든 표지 그대로다(`icon` = `hwpx`/`txt`) — 표면이 밴드로
       매체를 유도하지 않는다. */
    onMore: (row: Obj, trigger: HTMLElement) =>
      controller.toggleLibMenu("tpl", String(row.icon || ""), String(row.key), trigger),
    reload: () => controller.refreshLibrary(),
    notify: controller.notify,
    acts: createElement(Fragment, null,
      h("button", {
        className: "btn sm", "data-act": "import-template", key: "import",
        onClick: () => controller.guarded(() => controller.importTemplate()),
      }, "파일 가져오기…"),
      h("button", {
        className: "btn sm", "data-act": "open-template-folder", key: "open-folder",
        disabled: !root.directory, title: String(root.directory || ""),
        onClick: () => { void invokePathAction({
          client: controller.client, path: String(root.directory || ""),
          action: "open", notify: controller.notify,
        }); },
      }, "서식 폴더 열기")),
    emptyFallback: "서식 폴더를 아직 읽지 못했습니다.",
  };
  return h(PoolColumn as any, { host, column: ((tpl || {}).column || null) as Obj | null });
}

/** 중앙 — 연결 카드. **수치도 그 출처(`basis`)도 Python 이 낸다**(U6-B #976).
 *
 *  `basis="model"` 이면 이미 세운 매핑 모델의 실제 수치라 라벨이 「확인」이고,
 *  `"preview"` 면 아직 모델이 없어 순수 함수로 미리 세어 본 값이라 「자동 연결」이다.
 *  두 어휘를 하나로 뭉치면 카드가 「이미 확인했다」와 「확인하면 이렇게 될 것이다」를
 *  같은 말로 하게 된다. */
function LinkCard(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  const pairing = (snapshot.pairing || {}) as Obj;
  const ready = !!pairing.ready;
  const blockReason = String(pairing.advance_block_reason || "");
  const can = !!(snapshot.reachable || {}).template;
  const autoLabel = pairing.basis === "model" ? "확인" : "자동 연결";
  return h("div", { className: "linkzone" },
    h("div", { className: `wire${ready ? " live" : ""}`, id: "editorWire" },
      h("b", null), h("i", null), h("b", null)),
    h("div", {
      className: "linkcard", id: "editorLinkCard", role: "status", "aria-live": "polite",
    },
    ready
      ? createElement(Fragment, null,
        h("span", { className: "pairname" },
          `${pairing.template_name} ⟷ ${pairing.data_name}`),
        h("span", { className: "size" },
          `필드 ${pairing.field_count}개 · 열 ${pairing.column_count}개`),
        h("span", null, `${autoLabel} `),
        h("span", { className: "n" }, String(pairing.auto_count)),
        h("span", null, " · "),
        Number(pairing.confirm_count)
          ? h("span", { className: "warnline" }, "확인 필요 ",
            h("span", { className: "n" }, String(pairing.confirm_count)))
          : createElement(Fragment, null, "확인 필요 ",
            h("span", { className: "n" }, "0")))
      : h("span", { className: "linkcard-placeholder" }, "왼쪽과 오른쪽에서 하나씩 고르세요.")),
    h("button", {
      className: "btn primary cta", id: "editorLinkCta", "data-act": "goto-binding",
      disabled: !can, title: can ? "" : blockReason,
      onClick: () => controller.guarded(() => controller.gotoSection("binding")),
    }, "연결 확인으로"),
    !can && blockReason
      ? h("p", { className: "note quiet", id: "editorLinkBlock", style: { textAlign: "center" } },
        blockReason)
      : null);
}

/** 우 열 — 「데이터」 풀. 좌 열과 **같은 컴포넌트의 다른 인스턴스**다(고르기 열 공용 ③a).
 *
 *  종전에는 이 자리가 「데이터 선택」 다이얼로그의 세 구획(`PoolSections`)을 그렸다. 같은
 *  컴포넌트를 나눠 쓰는 것 자체는 옳았지만 **나눌 상대가 틀렸다**: 우 열의 이웃은 다이얼로그가
 *  아니라 **좌 열**이고, 그래서 「고를 수 있는가」의 시각적 얼굴·⋯ 메뉴·새로 읽기가 한쪽에만
 *  있었다. 이제 두 열이 같은 것을 그린다 — 갈리는 것은 바닥 동사 줄 하나다.
 *
 *  「현재 데이터」 카드는 **행 하나로 접혔다**: 파일로 연 데이터는 Python 이 같은 행 계약으로
 *  내려주고(`pairing.data_row` · 키 `session`) 그것이 목록 맨 위에 선다. 풀에 등록된 결속은
 *  그 행이 없다(`data_row === null`) — 풀 행이 이미 그것을 들고 있어 두 번 세우지 않는다. */
function DataPool(props: {
  pool: Obj | null; snapshot: Obj; controller: EditorController;
}): ReactNode {
  const { pool, snapshot, controller } = props;
  const column = ((pool || {}).column || null) as Obj | null;
  const pairing = (snapshot.pairing || {}) as Obj;
  const sessionRow = (pairing.data_row || null) as Obj | null;
  /* 이어붙이기는 **공용 순수 함수 하나**다(공용 ⑤ 리뷰) — 데이터 선택 다이얼로그와 같은
     목록이라 같은 순서·같은 최소 열을 써야 한다. */
  const merged = mergeSessionRow(column, sessionRow);
  const host: PoolColumnHost = {
    side: "dat",
    rootId: "editorDataPool",
    listId: "editorDataList",
    title: "데이터",
    headSub: poolHeadSub(column),
    /* 고름 표지의 정본은 편집기 스냅샷이다: 풀 결속이면 그 슬롯 키, 파일 결속이면 세션
       행이다. 두 축이 배타라 한 줄로 접힌다(둘 다 서는 상태는 Python 이 만들지 않는다). */
    selectedKey: String(pairing.data_key || (sessionRow ? SESSION_DATA_KEY : "")),
    choose: (key: string) => controller.guarded(() => controller.chooseData(key)),
    drop: (sourceSide: string, sourceKey: string, targetKey: string) =>
      controller.guarded(() => controller.dropPair(sourceSide, sourceKey, targetKey)),
    onMore: (row: Obj, trigger: HTMLElement) =>
      controller.toggleLibMenu("dat", String(row.icon || ""), String(row.key), trigger),
    reload: () => controller.refreshPool(),
    notify: controller.notify,
    onNoticeAction: (key: string, payload: Obj) => controller.poolNoticeAction(key, payload),
    acts: createElement(Fragment, null,
      h("button", {
        className: "btn sm", id: "editorPoolBrowse", "data-busy-lock": true, key: "browse",
        onClick: () => controller.guarded(() => controller.pickData()),
      }, "파일 찾아보기…"),
      /* 계약 목록은 파일 피커가 아니라 **DB 자리 + 시트**로 겨눈다(#937). 스냅샷이 그
         둘을 아직 안 실었으면 숨기지 않고 비활성 + 사유 병기 — 죽은 버튼을 조용히 두면
         「눌러도 아무 일 없음」이 결함으로 읽힌다. */
      h("button", {
        className: "btn sm", id: "editorPoolPclm", "data-busy-lock": true, key: "pclm",
        disabled: !(pool || {}).pclm, title: (pool || {}).pclm ? "" : PCLM_UNAVAILABLE,
        onClick: () => controller.openPclm(),
      }, "계약 목록(.db) 등록…"),
      /* 「이 데이터 고정…」은 **고정할 것이 있을 때만** 선다 — 풀에서 고른 데이터는 이미
         고정돼 있고, 아무것도 안 골랐으면 겨눌 것이 없다. 그 사실을 드는 값이 곧 세션 행이다. */
      sessionRow ? h("button", {
        className: "btn sm", id: "editorPoolPin", "data-busy-lock": true, key: "pin",
        onClick: () => controller.openPin(),
      }, "이 데이터 고정…") : null),
    emptyFallback: "고정한 데이터를 아직 읽지 못했습니다.",
  };
  return h(PoolColumn as any, { host, column: merged });
}

/** 항목 상세 시트의 **구간 항목 표** — 행 동사 3종 + 밴드 동사 1종(S8-03 · U4-E3 #939).
 *
 *  좌표(`data-act="slot-*"` · `data-slot=<id>`)와 왕복은 U6-E(#979)에서 **그대로** 시트 안으로
 *  옮겼다 — 바뀐 것은 이 표가 서는 자리 하나다. 그 이동이 메운 구멍은 도달성이다: U6-B 뒤
 *  COMPILED 행의 동사가 0 이 되면서, 완전 변환된 템플릿에서만 존재하는 이 동사들에 닿을 길이
 *  없었다.
 *
 *  진단이 있으면 목록 대신 사유가 서고 동사는 하나도 서지 않는다(못 믿는 구조 위에서 변이를
 *  권하지 않는다 — 진단 우선 규율). */
function SlotTable(props: {
  slots: Obj; diagnostics: string[]; controller: EditorController;
}): ReactNode {
  const { slots, diagnostics, controller } = props;
  const rows = (slots.rows || []) as Obj[];
  const verb = (row: Obj, act: string, label: string, danger?: boolean): ReactNode =>
    h("button", {
      className: `btn sm${danger ? " danger" : ""}`, key: act,
      "data-act": `slot-${act}`, "data-slot": String(row.id),
      onClick: (event: Obj) => controller.guarded(
        () => controller.handleSlotVerb(act, String(row.id), event.currentTarget)),
    }, label);
  const bandVerb = diagnostics.length || !rows.length ? null : h("button", {
    className: "btn sm danger", "data-act": "slot-decompile-all",
    style: { marginLeft: "auto" },
    onClick: (event: Obj) => controller.guarded(
      () => controller.handleSlotVerb("decompile-all", "", event.currentTarget)),
  }, "전부 표기로 되돌리기");
  return h("div", { className: "grp", id: "tplDetailSlots" },
    h("div", { className: "row", style: { marginBottom: "var(--sp-4)" } },
      h("span", { className: "cap" }, "구간 항목"),
      h("span", { className: "muted capnote" }, String(slots.summary || "")),
      bandVerb),
    ...(diagnostics.length ? [] : rows.map((row) => h("div", {
      className: "slotrow", key: String(row.id), "data-slot": String(row.id),
    },
    h("span", { className: "fname" }, String(row.label || row.id)),
    h("span", { className: "tbadge", title: (row.options || []).join(" · ") },
      `선택 ${row.option_count}`),
    verb(row, "rename", "이름 바꾸기"),
    verb(row, "decompile", "표기로 되돌리기"),
    verb(row, "remove", "삭제", true)))));
}

/** 항목 상세 시트의 **필드 표** — 나열식 금지(#16 판정)의 좌표 `.schema-fields` 를 잇는다.
 *
 *  값의 주인은 `tpl` 채널이다(`detail.fields` — 이름과 링0 추정 유형). 편집기가 자기 세션
 *  스키마로 그리던 종전 표와 겨누는 대상이 다르다: 이 표가 말하는 것은 **풀 항목(파일)** 이고,
 *  그래서 세션이 아직 그 템플릿을 고르지 않았어도 답할 수 있다. */
function DetailFields(props: { detail: Obj }): ReactNode {
  const fields = (props.detail.fields || []) as Obj[];
  return createElement(Fragment, null,
    h("p", { className: "fields-head", id: "tplDetailFieldSummary" },
      String(props.detail.field_summary || "")),
    fields.length
      ? h("div", { className: "tblwrap" },
        h("table", { className: "schema-fields" },
          h("thead", null, h("tr", null,
            h("th", null, "필드"), h("th", null, "추정 타입"))),
          h("tbody", null, ...fields.map((field: Obj, index: number) =>
            h("tr", { key: index },
              h("td", null, h("span", { className: "fname" }, String(field.name))),
              h("td", null, h("span", { className: "tbadge" },
                INFERRED_LABEL[String(field.type_hint)] || String(field.type_hint || ""))))))))
      : null);
}

/** 「자세히…」가 여는 **항목 상세 시트**(U6-E #979 · `#tplDetailModal`).
 *
 *  편집기 고르기 존 아래에 흩어져 있던 관리 표면(선택 chip + 경로 동사 · 작성 출처 · 스키마
 *  표 · 구간 항목 밴드 · 구간 요약)이 여기 하나로 모였다. 모을 때의 규율 둘:
 *
 *  - **재료는 `tpl` 채널 존 하나**다(`detail`). 시트가 두 스냅샷을 합성하면 그 사이에 갈린
 *    사실이 한 장에 함께 선다(상태 배지는 옛것, 항목 목록은 새것).
 *  - **겨누는 것은 세션이 아니라 파일**이다. 그래서 편집 중인 템플릿이든 아니든 같은 시트가
 *    서고, 마침 같은 파일이면 변이 통지 seam(`mutation_sinks` → `reconcile_template_mutation`)
 *    이 편집 세션을 스스로 다시 세운다 — 시트는 닫지 않는다(편집기 notice 가 말한다).
 *
 *  골격(머리·경로 문·오류 상자·성과 두 줄·동사 줄)은 이 파일이 그리지 않는다: 등록 데이터
 *  쪽 시트(`pool_detail.ts`)와 **같은 형**이라 `DetailSheetFrame` 하나가 진다(고르기 열
 *  공용 ④). 여기 남는 것은 이 매체만 아는 몸통(필드 표·구간 항목)과 좌표 접두어다. */
export function TplDetailSheet(props: { controller: EditorController }): ReactNode {
  const { controller } = props;
  /* 세 번째 인자(getServerSnapshot)는 `EditorScreen` 과 같은 이유로 선다 — 없으면 이 창이
     `react-dom/server` 로 한 번도 렌더되지 못해 노드 배치를 단위층에서 잴 수 없다. */
  const tpl = useSyncExternalStore(
    controller.tplModel.subscribe, controller.tplModel.getSnapshot,
    controller.tplModel.getSnapshot);
  /* 동사의 성과와 실패가 **이 면 안**에 선다(U6-E 리뷰 3): 시트는 스크림으로 화면을
     덮으므로 좌 열 바닥 결과 줄도 `#save-msg` 도 그 뒤에 그려진다. 값의 정본은 고르기 열
     존(`tpl.column.result`, Python)이고, 여기서 다시 짓는 문안은 없다. */
  const view = useSyncExternalStore(
    controller.viewModel.subscribe, controller.viewModel.getSnapshot,
    controller.viewModel.getSnapshot);
  const result = ((((tpl || {}) as Obj).column || {}) as Obj).result || {};
  const detail = (((tpl || {}) as Obj).detail || null) as Obj | null;
  const shared = {
    idPrefix: "tplDetail",
    client: controller.client,
    notify: controller.notify,
    message: view.detailMessage ? String(view.detailMessage) : "",
    result,
    onClose: (): void => { controller.closeDetail(); },
  };
  if (detail === null) {
    return h(DetailSheetFrame as any, Object.assign({}, shared, {
      title: "항목 상세",
      empty: DETAIL_SHEET_EMPTY,
    }));
  }
  const media = String(detail.media || "hwpx");
  const diagnostics = (detail.diagnostics || []) as string[];
  const slots = (detail.slots || null) as Obj | null;
  /* 동사 줄은 행 ⋮ 와 **같은 함수**가 짓는다(같은 상태 두 곳 판정 금지) — 지금 서 있는
     「자세히…」 자신만 걷는다. */
  const verbs = libRowMenuItems(media, detail)
    .filter((entry) => entry.action !== "detail");
  return h(DetailSheetFrame as any, Object.assign({}, shared, {
    title: String(detail.name || ""),
    /* 배지의 저자는 **링1 하나**다(공용 ⑤ 리뷰) — TXT 는 말할 상태 축이 없어 그 자리에
       매체 표지가 서지만, 그 판정도 문안도 `compile_badge` 가 낸다. 종전에는 여기서
       `media === "txt"` 를 다시 판정해 문자열을 지었다(같은 상태 두 곳 판정). */
    pill: {
      label: String(detail.badge_label || ""),
      level: String(detail.badge_level || "muted"),
    },
    path: String(detail.path || ""),
    /* 판독 실패·구간 진단은 숨기지 않는다 — 오류 행에서 「자세히…」가 서는 이유가 이것이다. */
    error: String(detail.error || ""),
    diagnostics,
    body: createElement(Fragment, null,
      h(DetailFields as any, { detail }),
      slots ? h(SlotTable as any, { slots, diagnostics, controller }) : null),
    verbs,
    onVerb: (action: string, trigger: HTMLElement): void => {
      controller.guarded(() => controller.handleDetailVerb(action, trigger));
    },
  }));
}

/** 1단계 게이트 존 — **세션 판정**이라 고르기 단계에 남되 한 줄이다(U6-E #979).
 *
 *  이 존이 답하는 것은 「지금 고른 템플릿으로 진행할 수 있는가」 하나다. 「그 템플릿에 무엇이
 *  들어 있는가」(스키마 표·구간 요약·작성 출처)는 그 답 뒤에 묻는 별개의 질문이고, 그 자리는
 *  「자세히…」가 여는 시트다 — 그래서 여기 남는 수치는 `field_count` 하나다.
 *
 *  RAW 차단·판독 실패 사유는 Python 문안 그대로이고, 「비우고 진행 확인」의 조건도 종전과
 *  같다(`gate` 가 서고 아직 확인 전). */
function TemplateGate(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  if (!snapshot.template_path) return null;
  const detail = (snapshot.session_detail || {}) as Obj;
  const available = !!detail.available;
  const reason = String(detail.reason || "");
  const gate = snapshot.gate;
  const drift = String(snapshot.schema_drift || "");
  /* 머리는 상태와 무관하게 선택한 템플릿을 식별한다. 폴더 열기는 좌 열의 루트 버튼이 맡는다. */
  const head = h("div", { className: "row" },
    h("span", { className: "cap" }, "선택한 템플릿"),
    h("span", { className: "muted capnote" }, String(snapshot.template_name || "")),
    snapshot.field_count
      ? h("span", { className: "muted capnote" }, `필드 ${snapshot.field_count}개`)
      : null,
    h("span", { className: "spacer" }),
    /* 시트는 `tpl` 이 아는 항목만 연다 — 가부·사유는 Python 판정이고 여기는 잠금과 병기만
       한다(리뷰 5). 조용히 열리지 않는 문을 두지 않는다. */
    h("button", {
      className: "btn sm", "data-act": "session-detail",
      disabled: !available, title: available ? undefined : reason,
      onClick: (event: Obj) => controller.guarded(
        () => controller.openDetail(String(snapshot.template_path || ""), event.currentTarget)),
    }, ROW_DETAIL_LABEL));
  let body: ReactNode = null;
  if (snapshot.raw_block) {
    body = h("p", { className: "note dangerbox", style: { whiteSpace: "pre-line" } },
      String(snapshot.raw_block));
  } else if (snapshot.gate_error) {
    body = h("p", { className: "note dangerbox" },
      "템플릿 상태를 확인할 수 없습니다. 진행할 수 없습니다.");
  }
  return h("div", { className: "grp", id: "editorTplGate" },
    head,
    !available && reason
      ? h("p", { className: "muted capnote", id: "editorTplDetailBlock" }, reason)
      : null,
    body,
    /* 작성 출처 드리프트(#53-C 승계 · 리뷰 6) — **세션 판정**이라 이 자리다. 판정도 문안도
       Python 이 낸다(웹이 필드 목록을 다시 대조하지 않는다). */
    drift
      ? h("p", { className: "note warnbox", id: "editorSchemaDrift" }, drift)
      : null,
    gate
      ? h("div", { className: "note warnbox", style: { whiteSpace: "pre-line" } }, gate.message)
      : null,
    gate && !gate.acked
      ? h("button", {
        className: "btn", "data-act": "ack-gate",
        onClick: () => controller.guarded(() => controller.sendEdit("ack_gate", {})),
      }, `비우고 진행 확인 (${gate.unmet.length}개 토큰)`)
      : null);
}

/** 1단계 「고르기」 — 좌 템플릿 풀 · 중앙 연결 카드 · 우 데이터 풀(U6 §2.2 · #976).
 *
 *  **이 단계가 묻는 질문은 하나**다: 「어느 템플릿을 어느 데이터에?」. U6-E(#979)가 그 아래에
 *  남아 있던 것들을 걷었다 — 선택 chip + 경로 동사 · 작성 출처 · 스키마 표 · 구간 항목 밴드 ·
 *  구간 요약은 전부 항목 상세 시트로 갔고, 결과 줄은 관리 동사가 나가는 좌 열 바닥으로 갔다.
 *  존 아래에 남은 것은 세션 판정 한 줄(`TemplateGate`)뿐이다.
 *
 *  구 `DataGateway`(2단계 머리의 데이터 관문)와 축약 목록 `PoolPickList` 는 U6-B 에서 사슬째
 *  퇴역했다: 데이터를 고르는 자리가 우 열 하나가 됐고, 그 열은 「데이터 선택」 다이얼로그와
 *  같은 컴포넌트라 같은 상태를 두 표면이 다르게 그릴 길이 없다. */
function PairingStage(props: {
  snapshot: Obj; tpl: Obj | null; pool: Obj | null; controller: EditorController;
}): ReactNode {
  const { snapshot, tpl, pool, controller } = props;
  return h("div", null,
    h("div", { className: "wtitle" }, stageTitle(snapshot, "template")),
    h("p", { className: "wsub" }, "템플릿과 데이터를 하나씩 고르세요."),
    h("div", { className: "pairzone", id: "editorPairZone" },
      h(TemplatePool as any, { tpl, snapshot, controller }),
      h(LinkCard as any, { snapshot, controller }),
      h(DataPool as any, { pool, snapshot, controller })),
    h(TemplateGate as any, { snapshot, controller }));
}


/** 데이터 열 칸 — select(실 열 + 특수 항목) · 고정값 인라인 입력 · 상태 배지 버튼.
 *
 *  이 칸 하나가 종전 세 열(데이터 열 · 타입/고정값 · 확정 체크)을 흡수한다(U6 §2.2 · 동결
 *  시안 장면 2). 흡수의 조건은 **판정이 늘지 않는 것**이었다: 항목의 `kind` 도, 배지의
 *  문안·가부도, 「데이터에 없음」 표기도 전부 Python 이 낸 값이고 여기서는 그리기만 한다. */
function DataColumnCell(props: {
  row: Obj; snapshot: Obj; draft: DraftState; controller: EditorController;
}): ReactNode {
  const { row, snapshot, draft, controller } = props;
  const index = Number(row.index);
  const options = (snapshot.data_column_options || []) as Obj[];
  /* select 값의 정본은 **스냅샷**이다(리뷰 2) — 초안을 두지 않으므로 여기서 읽을 draft
     가 없고, 실패한 선택은 다음 렌더가 이 값으로 되돌린다. */
  const value = String(row.source_value || "");
  const missingLabel = String(row.source_missing_label || "");
  const nodes: ReactNode[] = options.map((option) => h("option", {
    value: String(option.value), key: String(option.value),
    title: String(option.label), "data-kind": String(option.kind),
  }, String(option.label)));
  /* 현재 데이터에 없는 결속은 목록에 없다 — 「(비움)」으로 오표시하지 않고 명시 항목으로
     드러낸다(문안은 Python). 이 항목을 다시 고르는 것은 무동작이다. */
  if (missingLabel) {
    nodes.push(h("option", {
      value: String(row.source_value), key: "missing", title: missingLabel,
      "data-kind": "column",
    }, missingLabel));
  }
  const confirmable = !!row.confirmable;
  const constRef = useRef<HTMLInputElement | null>(null);
  /* 「고정값…」을 고른 뒤 값을 적을 자리로 커서를 옮긴다(리뷰 8). 그 입력은 **서버가 이
     행을 const 로 인정한 뒤에야** 렌더되므로 고른 순간에는 DOM 에 없다 — 초점은 그 입력이
     실제로 선 이 렌더에서 선다. 표지는 가져가는 쪽이 걷어 재렌더마다 커서를 빼앗지 않는다. */
  useEffect(() => {
    if (constRef.current === null) return;
    if (controller.takePendingConstFocus(index)) constRef.current.focus();
  });
  return h("div", { className: "srccell" },
    h("select", {
      className: `sel${row.row_state === "needs_source" ? " empty" : ""}`,
      "data-act": "row-source", "data-index": index, value,
      onChange: (event: Obj) => controller.guarded(
        () => controller.chooseDataColumn(index, String(event.currentTarget.value))),
    }, ...nodes),
    row.source_kind === "const" ? h("input", {
      className: "sel", "data-act": "row-const", "data-index": index, placeholder: "고정값",
      ref: constRef,
      value: valueOf(draft, rowField(index, "const")),
      onChange: (event: Obj) => controller.type(rowField(index, "const"), String(event.currentTarget.value)),
      onFocus: () => controller.focus(rowField(index, "const"), true),
      onBlur: () => {
        controller.focus(rowField(index, "const"), false);
        controller.commitRowOnBlur(index, "const");
      },
      onCompositionStart: () => controller.compose(rowField(index, "const"), true),
      onCompositionEnd: () => controller.compose(rowField(index, "const"), false),
    }) : null,
    h("button", {
      className: `badge ${ROW_BADGE_CLASS[String(row.row_state)]}`,
      type: "button", "data-act": "row-confirm", "data-index": index,
      disabled: !confirmable,
      title: confirmable ? "" : NOT_CONFIRMABLE_HINT,
      "aria-pressed": !!row.confirmed,
      onClick: () => controller.guarded(() => controller.sendEdit(
        "set_confirmed", { index, confirmed: !row.confirmed })),
    }, String(row.state_label)),
    /* ↻ 의 노출 술어는 **Python 이 낸다**(`revertable` — 리뷰 9). `_do_revert_source` 가
       확정 행을 거절하는 것과 같은 술어라야 「눌렀는데 거절당하는」 버튼이 남지 않는다. */
    row.revertable ? h("button", {
      className: "btn icon", "data-act": "revert-source", "data-index": index,
      title: "자동 제안으로 되돌리기", "aria-label": "이 행 자동 제안 다시 받기",
      onClick: () => controller.guarded(() => controller.sendEdit("revert_source", { index })),
    }, "↻") : null);
}

function MapRow(props: {
  row: Obj; snapshot: Obj; draft: DraftState; controller: EditorController;
}): ReactNode {
  const { row, snapshot, draft, controller } = props;
  const index = Number(row.index);
  const displayGroups = (row.display_options || []) as Obj[];
  /* 행 상태 class 는 **닫힌 집합**이다(Python `screen_editor.py` 가 넷 중 하나를 낸다).
     보간으로 지으면 이름이 코드에 안 남아 CSS 고아 검사가 이 자리를 통째로 건너뛴다 —
     넷을 리터럴로 적어 그 검사에 들게 하고, 계약 밖 값은 조용히 무-class 로 접지 않는다. */
  const rowClass = ROW_STATE_CLASS[String(row.row_state)];
  if (rowClass === undefined) throw new Error(`알 수 없는 행 상태: ${row.row_state}`);
  return h("tr", { className: rowClass, "data-field": row.template_field, key: index },
    h("td", null,
      h("span", { className: "fname", title: row.context || row.template_field }, row.template_field),
      h("span", { className: "tbadge" },
        `[추정: ${INFERRED_LABEL[row.inferred_type] || row.inferred_type || ""}]`)),
    h("td", null, h(DataColumnCell as any, { row, snapshot, draft, controller })),
    /* 표시형 select 가 **유형 축까지 든다**(리뷰 1). `infer_type` 은 이름 키워드
       휴리스틱이라 「계약일」이 text 로 추정되면 날짜 서식을 영영 못 고르는 자리가 생겼다 —
       옵션을 유형별 그룹으로 묶어 한 번의 선택이 (유형, 표시형) 한 쌍을 원자적으로 세운다.
       그룹·라벨·값은 전부 Python 이 낸다. */
    h("td", null, h("select", {
      className: "sel", "data-act": "row-fmt", "data-index": index,
      value: String(row.display_value || ""), disabled: !displayGroups.length,
      onChange: (event: Obj) => controller.guarded(
        () => controller.chooseDisplay(index, String(event.currentTarget.value))),
    }, ...(displayGroups.length
      ? displayGroups.map((group) => h("optgroup", {
        label: String(group.label), key: String(group.label),
      }, ...((group.options || []) as Obj[]).map((option) =>
        h("option", { value: String(option.value), key: String(option.value) },
          String(option.label)))))
      : [h("option", { value: "", key: "" }, "—")]))),
    h("td", null, h(PreviewCell as any, { row })));
}

/** 표 머리 — pill 3개 · 일괄 승격 · 드문 동사 ⋯. 수치도 문안도 Python 이 낸다. */
function BindingHead(props: { snapshot: Obj; controller: EditorController }): ReactNode {
  const { snapshot, controller } = props;
  const head = (snapshot.binding_head || {}) as Obj;
  const suggested = Number(head.suggested || 0);
  return h("div", { className: "bindbar" },
    h("span", { className: "pill acc", "data-pill": "suggested" }, `자동 제안 ${suggested}`),
    h("span", { className: "pill warn", "data-pill": "needs-confirm" },
      `확인 필요 ${Number(head.needs_confirm || 0)}`),
    h("span", { className: "pill muted", "data-pill": "const" },
      `고정값 ${Number(head.const || 0)}`),
    h("span", { className: "spacer" }),
    h("button", {
      className: "btn sm", "data-act": "confirm-suggested", type: "button",
      disabled: !suggested,
      onClick: () => controller.guarded(() => controller.confirmSuggested()),
    }, String(suggested ? head.promote_label : head.promoted_label)),
    h("button", {
      className: "btn sm icon binding-more", "data-act": "binding-more", type: "button",
      "aria-label": "연결 확인 그 밖의 동작", "aria-haspopup": "menu",
      "aria-expanded": controller.isBindingMenuOpen(),
      onClick: (event: Obj) => controller.guarded(
        () => controller.toggleBindingMenu(event.currentTarget as HTMLElement)),
    }, "⋯"));
}

function MappingStage(props: {
  snapshot: Obj; draft: DraftState; view: ViewState; controller: EditorController;
}): ReactNode {
  const { snapshot, draft, controller } = props;
  const rows = (snapshot.rows || []) as Obj[];
  const head = (snapshot.binding_head || {}) as Obj;
  return h("div", null,
    h("div", { className: "wtitle" }, stageTitle(snapshot, "binding")),
    /* 부제는 걷혔다 — 제목·표 머리·배지가 이미 「필드마다 데이터 열을 정한다」를 보여준다
       (`docs/COPY_STYLE_GUIDE.md` §1·§2: 상시 부제 기본 0). */
    /* 처방은 **저장 게이트와 같은 말**이어야 한다(#945 F8). U4-C 이후 데이터 연결은 저장의
       하드 게이트라(`gui/job_editor_state.validate_save`), 종전의 "고정값을 넣거나 비움으로
       확정하세요"는 그대로 따라도 저장이 막히는 거짓 처방이었다. 같은 상태를 두 어휘로
       판정하지 않는다 — 여기서 말하는 것은 그 게이트의 사실과 고칠 자리(1단계)다. */
    snapshot.schema_only ? h("p", { className: "note warnbox" },
      "데이터를 연결하지 않아 지금은 저장할 수 없습니다. '고르기' 단계에서 데이터를 고르세요.") : null,
    h(BindingHead as any, { snapshot, controller }),
    h("div", { className: "tblwrap" }, h("table", { className: "map" },
      h("thead", null, h("tr", null,
        h("th", null, "템플릿 필드"),
        h("th", null, "데이터 열"),
        h("th", null, "표시형"),
        h("th", null, "미리보기",
          h("span", { className: "stepper" }, ...(snapshot.preview_count
            ? [
              h("button", {
                className: "btn sm", "data-act": "prev-rec", type: "button",
                "aria-label": "이전 행", key: "prev",
                onClick: () => controller.guarded(() => controller.sendEdit("step_preview", { delta: -1 })),
              }, "◀"),
              h("span", { className: "mono", key: "at" },
                `행 ${snapshot.preview_index} / ${snapshot.preview_count}`),
              h("button", {
                className: "btn sm", "data-act": "next-rec", type: "button",
                "aria-label": "다음 행", key: "next",
                onClick: () => controller.guarded(() => controller.sendEdit("step_preview", { delta: 1 })),
              }, "▶"),
            ]
            : [h("span", { className: "muted", key: "none" }, "행 0 / 0 · 데이터 없음")]))))),
      h("tbody", null, ...rows.map((row) =>
        h(MapRow as any, { key: row.index, row, snapshot, draft, controller }))),
      /* 바닥은 **수치 하나**다(§8 낭독 패턴 3): 「미리보기는 실제 행입니다」는 시스템 원칙
         낭독이라 걷혔고, 안 쓰는 열이 0 이면 말할 것이 없어 줄 자체가 서지 않는다. */
      Number(head.unused_columns || 0) > 0
        ? h("tfoot", null, h("tr", null, h("td", { colSpan: 4 },
          `사용하지 않는 데이터 열 ${Number(head.unused_columns)}개`)))
        : null)),
    h(DataPreview as any, { snapshot }));
}

function DataPreview(props: { snapshot: Obj }): ReactNode {
  const { snapshot } = props;
  if (!snapshot.record_count) return null;
  const columns = (snapshot.source_fields || []) as string[];
  const sample = (snapshot.sample_rows || []) as any[][];
  return h("div", null,
    h("p", { className: "fields-head" },
      `${snapshot.record_count}행 불러옴 · 전체 ${columns.length}열.`),
    h("div", { className: "tblwrap" }, h("table", { className: "data-preview" },
      h("thead", null, h("tr", null, ...columns.map((name) =>
        h("th", { title: name, key: name }, name)))),
      h("tbody", null, ...sample.map((row, rowIndex) =>
        h("tr", { key: rowIndex }, ...columns.map((name, columnIndex) => {
          const value = row[columnIndex];
          return h("td", { key: name }, (value === "" || value === null || value === undefined)
            ? h("span", { className: "pv emptyval" }, "(빈 값)")
            : h("span", { className: "pv" }, value));
        })))))),
    snapshot.record_count > sample.length ? h("p", { className: "fields-head muted" },
      `샘플 ${sample.length}행 표시(외 ${snapshot.record_count - sample.length}행)`) : null);
}

function fnPreviewText(row: Obj, snapshot: Obj): ReactNode {
  if (row.preview_error) return h("span", { className: "pv emptyval" }, "(미리보기 오류)");
  if (row.preview_empty) {
    return h("span", { className: "pv emptyval" },
      snapshot.record_count ? "(빈 값)" : "(샘플 데이터 없음)");
  }
  let display = String(row.preview).replace(/[\r\n]+/g, " ");
  if (display.length > 40) display = `${display.slice(0, 39)}…`;
  return h("span", { className: "pv" }, display);
}

/** 3단계 「이름·저장」 — 「뭐라고 부르고 뭐라고 저장하나?」(U6 §2.2 · 동결 시안 장면 3).
 *
 *  행 셋이고 그 셋이 이 단계가 묻는 전부다: **작업 이름**(두 매체 공통) · **문서 파일
 *  이름**(hwpx 만 — TXT 는 파일을 만들지 않는다) · **저장 폴더**(읽기 전용 재진술).
 *
 *  이름은 여기 그려지지만 **`filename` section patch 에 속하지 않는다**(§10.13 판정 L):
 *  탭 이동의 자동 버리기와 `discard_patch {section}` 은 패턴만 되돌리고 이름은 그대로 둔다.
 *  같은 화면에 그린다고 같은 거래에 드는 것이 아니다.
 *
 *  저장 폴더는 **여기서 바꾸지 않는다** — 전역 설정이라 고르는 자리가 하나여야 한다(#968).
 *  값·출처·하향 사유는 Python 이 작업 화면과 같은 함수로 낸다(웹 재조립 0). */
function NameSaveStage(props: {
  snapshot: Obj; draft: DraftState; view: ViewState; controller: EditorController;
}): ReactNode {
  const { snapshot, draft, view, controller } = props;
  /* 문서 파일 이름 행은 **매체 파생**이다(§3.2) — TXT 작업은 파일을 만들지 않는다.
     단계 자체는 두 매체가 함께 갖는다(U6-D): 이름은 매체와 무관한 저장 게이트 술어다. */
  const hasPattern = snapshot.template_media !== "txt";
  /* 저장 폴더 행은 **Python 이 존을 낼 때만** 선다(U6-D #978 리뷰 4). TXT 는 파일을 만들지
     않아 폴더가 축이 아니고(`UI_CONTRACT` 「폴더가 축이 아니다」), 그때 존은 `null` 이다 —
     웹이 매체로 다시 판정하면 같은 사실을 두 곳이 답한다. */
  const folder = (snapshot.output_folder || null) as Obj | null;
  const rows = ((snapshot.rows || []) as Obj[]).filter((row) => row.has_content);
  const tokens: ReactNode[] = [];
  rows.forEach((row, index) => {
    if (index > 0) tokens.push(h("span", { key: `sep-${index}` }, "  ·  "));
    tokens.push(h("code", { key: `tok-${index}` }, `{{${row.template_field}}}`));
    tokens.push(h("span", { key: `arrow-${index}` }, " → "));
    tokens.push(h("span", { key: `pv-${index}` }, fnPreviewText(row, snapshot)));
  });
  return h("div", null,
    h("div", { className: "wtitle" }, stageTitle(snapshot, "filename")),
    h("div", { className: "row" },
      h("span", { className: "lbl lbl-fixed" }, "작업 이름"),
      h("input", {
        className: "field", id: "editorName", type: "text", "data-act": "name",
        placeholder: "작업 이름을 입력하세요", "aria-label": "작업 이름",
        value: valueOf(draft, NAME_FIELD),
        "aria-invalid": view.invalidField === NAME_FIELD ? "true" : undefined,
        onChange: (event: Obj) => controller.type(NAME_FIELD, String(event.currentTarget.value)),
        onFocus: () => controller.focus(NAME_FIELD, true),
        onBlur: () => { controller.focus(NAME_FIELD, false); controller.commitField(NAME_FIELD); },
        onCompositionStart: () => controller.compose(NAME_FIELD, true),
        onCompositionEnd: () => controller.compose(NAME_FIELD, false),
      })),
    /* 힌트는 **Python 표지 하나**가 세운다(`job_name_is_derived`). 웹이 「이름이 도출값과
       같은가」로 되유추하면 사람이 우연히 같은 이름을 지은 순간 힌트가 되살아난다. */
    snapshot.name_hint
      ? h("p", { className: "hint", id: "editorNameHint", style: { marginTop: 0 } },
        String(snapshot.name_hint))
      : null,
    hasPattern ? h("div", { className: "row" },
      h("span", { className: "lbl lbl-fixed" }, "문서 파일 이름"),
      h("input", {
        className: "field mono", "data-act": "pattern", value: valueOf(draft, PATTERN_FIELD),
        "aria-label": "문서 파일 이름",
        "aria-invalid": view.invalidField === PATTERN_FIELD ? "true" : undefined,
        onChange: (event: Obj) => controller.type(PATTERN_FIELD, String(event.currentTarget.value)),
        onFocus: () => controller.focus(PATTERN_FIELD, true),
        onBlur: () => { controller.focus(PATTERN_FIELD, false); controller.commitField(PATTERN_FIELD); },
        onCompositionStart: () => controller.compose(PATTERN_FIELD, true),
        onCompositionEnd: () => controller.compose(PATTERN_FIELD, false),
      })) : null,
    /* 예시는 **연번째로** Python 이 만든다(`pattern_preview`) — 여기서 「· 002 · 003」을
       조립하면 seq 토큰이 없는 패턴에서도 연번이 있는 것처럼 그려진다. */
    (hasPattern && snapshot.pattern_preview)
      ? h("p", { className: "hint mono", id: "editorPatternPreview", style: { marginTop: 0 } },
        `예: ${snapshot.pattern_preview}${snapshot.record_count ? " (표본 1행 기준)" : ""}`)
      : null,
    hasPattern ? h("details", {
      className: "hidden-hdrs tok-fold", open: view.tokFoldOpen,
      onToggle: (event: Obj) => controller.setTokFold(!!event.currentTarget.open),
    },
    h("summary", null, "파일명에 넣을 수 있는 값 (펼쳐 보기)"),
    h("p", { className: "hint", style: { marginTop: "var(--sp-4)" } },
      ...(tokens.length ? tokens
        : [h("span", { className: "muted", key: "none" },
          "매핑을 완료하면 파일명에 쓸 수 있는 필드가 여기 표시됩니다.")])),
    h("p", { className: "hint" },
      "날짜: ", h("code", null, "{{date}}"), " → 생성 날짜(YYYYMMDD) · ",
      h("code", null, "{{date:YYYY-MM-DD}}"), " → 하이픈 포함 날짜", h("br", null),
      "순번: ", h("code", null, "{{seq}}"), " → 1부터 증가 · ",
      h("code", null, "{{seq:001}}"), " → 001부터 세 자리로 증가")) : null,
    folder ? h("div", { className: "row", id: "editorOutFolderRow" },
      h("span", { className: "lbl lbl-fixed" }, "저장 폴더"),
      h("input", {
        className: "field ro mono", id: "editorOutDir", type: "text", readOnly: true,
        "aria-label": "저장 폴더", tabIndex: -1,
        value: String(folder.directory || "아직 정해지지 않았습니다"),
      }),
      folder.source_label
        ? h("span", { className: "muted capnote", id: "editorOutDirSource" },
          String(folder.source_label))
        : null,
      h("button", {
        className: "btn linklike", type: "button", "data-act": "open-settings",
        id: "editorOpenFolderSettings",
        onClick: () => controller.openSettings(),
      }, "설정에서 바꾸기")) : null,
    /* 설정한 폴더가 사라져 기본값으로 내려간 사유 — 조용한 하향 금지(문안은 링0 소유). */
    (folder && folder.notice)
      ? h("p", { className: "hint", id: "editorOutDirNotice", style: { marginTop: 0 } },
        String(folder.notice))
      : null);
}

/** 인라인 알림 노드(#323) — **셸 레벨**이라 세 탭이 공유하고 본문 재렌더에 증발하지 않는다.
 *  종전 거처는 파일 이름 탭 본문이었고, 그래서 나머지 두 탭의 통지가 갈 곳이 없었다.
 *
 *  상자·닫기는 `NoticeBox` 가 소유한다(U4 §2.12 · #945) — 문안 조립(`⚠ ` 표지)은 여기
 *  그대로다. 통지가 없어도 **노드는 남는다**: 세 탭 어디서든 통지가 갈 자리가 있다는
 *  것이 #323 의 계약이라 프로브가 그 존재를 통지 이전에 먼저 잰다. */
function SaveMessage(props: { view: ViewState; controller: EditorController }): ReactNode {
  const { saveMessage } = props.view;
  if (!saveMessage) return h("div", { id: "save-msg", className: "note", style: { display: "none" } });
  return createElement(NoticeBox, {
    id: "save-msg",
    closeId: "saveMsgClose",
    level: saveMessage.level === "ok" ? "ok" : "warn",
    text: `${saveMessage.level === "ok" ? "" : "⚠ "}${saveMessage.text}`,
    onClose: props.controller.clearSaveMessage,
  });
}

function EditorFooter(props: {
  snapshot: Obj; draft: DraftState; controller: EditorController;
}): ReactNode {
  const { snapshot, draft, controller } = props;
  const sections = (snapshot.sections || []) as string[];
  const here = sections.indexOf(snapshot.section);
  if (isEditing(snapshot)) {
    /* 저장·버리기는 **같은 합성 술어**로 상시 표시 + 상태 비활성이다(U2 §2.4·§2.17). */
    const armed = !!snapshot.dirty || hasPendingEdits(draft);
    /* 연결 확정 대기(#911)는 무장 사유를 **더한다**. 판정·라벨은 Python 이 실어 보낸
       것을 그대로 읽는다 — 「저장 안 됨」 같은 인접 사실로 확정 필요를 여기서 추론하지 않는다.
       바꿀 것이 없는데 관리 검토가 확정을 기다리면 dirty 는 영영 거짓이고, 그 상태에서
       두 동사가 모두 잠겨 사슬을 닫을 길이 없었다. 버리기는 그대로 dirty 술어다(확정
       대기는 버릴 것을 만들지 않는다). 라벨이 갈리는 자리는 **무변경 확정 하나**다:
       손댄 것이 있으면 그 저장이 확정도 겸하므로 「변경 저장」이 여전히 참말이다.
       설명 줄은 걷혔다(§8 낭독 패턴 1) — 전제 조건은 라벨이 말하고 사유는 blocker 가 든다. */
    const confirm = (snapshot.binding_confirm || {}) as Obj;
    const confirmPending = !!confirm.pending;
    const confirmOnly = confirmPending && !armed;
    return h("footer", { className: "wfoot", id: "editor-foot" },
      h("button", {
        className: "btn", "data-act": "discard-patch", disabled: !armed,
        onClick: () => controller.guarded(() => controller.discardPatch()),
      }, "변경 버리기"),
      h("span", { className: "spacer" }),
      h("button", {
        className: "btn", "data-act": "save",
        "data-confirm-binding": confirmOnly ? "1" : null,
        disabled: !(armed || confirmPending),
        onClick: () => controller.guarded(() => controller.doSave({})),
      }, confirmOnly ? String(confirm.label || "") : "변경 저장"),
      saveAndOpenButton(armed || confirmPending, controller));
  }
  const last = here >= sections.length - 1;
  const can = !!(snapshot.reachable || {})[snapshot.section];
  return h("footer", { className: "wfoot", id: "editor-foot" },
    h("button", {
      className: "btn", "data-act": "cancel-new",
      onClick: () => controller.guarded(() => controller.cancelNewDraft()),
    }, "취소"),
    here > 0
      ? h("button", {
        className: "btn", "data-act": "back",
        onClick: () => controller.guarded(() => controller.gotoSection(controller.neighbour(-1))),
      }, "◀ 뒤로")
      : h("button", { className: "btn", disabled: true }, "◀ 뒤로"),
    h("span", { className: "spacer" }),
    (!last && !can) ? h("span", { className: "muted capnote" }, gateHint(snapshot)) : null,
    last
      ? h("button", {
        className: "btn", "data-act": "save",
        onClick: () => controller.guarded(() => controller.doSave({})),
      }, "작업 저장")
      : null,
    last
      ? saveAndOpenButton(true, controller)
      : h("button", {
        className: "btn primary", "data-act": "next", disabled: !can,
        onClick: () => controller.guarded(() => controller.gotoSection(controller.neighbour(1))),
      }, "다음 ▶"));
}

/** 「저장하고 문서 만들기로」 — 마지막 단계의 **주 행동**(U6 §2.2 · 동결 시안 장면 3).
 *
 *  저장 자체는 두 동사 모두 같은 `doSave` 를 지난다(게이트·덮어쓰기 확인·차단 조준 공유).
 *  갈리는 것은 **성사 뒤에 어디에 서는가** 하나다: 「작업 저장」은 제자리(결정 40 불변),
 *  이 동사는 문서 만들기에 그 작업이 선 상태로 착석한다. 무장 술어는 옆 동사와 **같은
 *  값**을 받는다 — 두 술어를 두면 한쪽만 눌리는 상태가 실재한다. */
function saveAndOpenButton(armed: boolean, controller: EditorController): ReactNode {
  return h("button", {
    className: "btn primary", "data-act": "save-and-open", disabled: !armed,
    onClick: () => controller.guarded(() => controller.saveAndOpen()),
  }, "저장하고 문서 만들기로");
}

export function EditorScreen(props: { controller: EditorController }): ReactNode {
  const { controller } = props;
  /* 세 store 모두 세 번째 인자(getServerSnapshot)를 같은 getter 로 넘긴다
     (`JobContentSelection` 선례): 제품 런타임은 이 인자를 쓰지 않지만, 없으면 이 셸이
     `react-dom/server` 로 **한 번도** 렌더되지 못해 노드 배치 계약을 단위층에서 잴 수 없다. */
  const snapshot = useSyncExternalStore(
    controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot);
  const draft = useSyncExternalStore(
    controller.draftModel.subscribe, controller.draftModel.getSnapshot,
    controller.draftModel.getSnapshot);
  const view = useSyncExternalStore(
    controller.viewModel.subscribe, controller.viewModel.getSnapshot,
    controller.viewModel.getSnapshot);
  /* 고르기 단계의 두 열은 **자기 채널을 직접 구독**한다(U6-B #976) — 편집기 스냅샷이
     같은 목록을 한 번 더 실어 나르면 tpl·pool 의 변이가 두 경로로 도착한다. */
  const tpl = useSyncExternalStore(
    controller.tplModel.subscribe, controller.tplModel.getSnapshot,
    controller.tplModel.getSnapshot);
  const pool = useSyncExternalStore(
    controller.poolModel.subscribe, controller.poolModel.getSnapshot,
    controller.poolModel.getSnapshot);

  /* 조준은 렌더 **뒤**에 — 커밋 전에는 겨눌 노드가 아직 없다. */
  useEffect(() => { controller.consumeAim(); });

  if (snapshot === null) {
    return h("div", { className: "editor-shell" },
      h("p", { className: "note", role: "status" }, "편집기를 읽는 중…"));
  }
  let body: ReactNode;
  if (snapshot.section === "template") {
    body = h(PairingStage as any, { snapshot, tpl, pool, controller });
  }
  else if (snapshot.section === "binding") body = h(MappingStage as any, { snapshot, draft, view, controller });
  else body = h(NameSaveStage as any, { snapshot, draft, view, controller });
  return h("div", { className: "editor-shell" },
    h("button", {
      className: "btn sm back", id: "editorBack", type: "button",
      onClick: () => controller.guarded(() => controller.leaveTo(controller.returnScreen())),
    }, "← 원래 업무로 돌아가기"),
    h(EditorHead as any, { snapshot, controller }),
    h(ContextBanner as any, { snapshot }),
    h(StepHeader as any, { snapshot, controller }),
    h("div", { className: "wbody", id: "editor-body", "data-preserve-scroll": true },
      /* 세션 통지(#26) — 문제(warn)만 시끄럽게, 정상(ok)은 muted 한 줄.
         닫기는 **사용자 몫**이다(U4 계열1-20): 세우는 트리거는 그대로라 사유가 다시 서면
         통지도 다시 서고, 해소를 자동 감지하려 들면 통지마다 해소 술어를 새로 지어야 한다. */
      snapshot.notice ? createElement(NoticeBox, {
        tag: "p",
        closeId: "editorNoticeClose",     // 좌표는 불변 — 이 id 를 든 게이트가 이미 있다.
        level: snapshot.notice.level === "ok" ? "quiet" : "warn",
        text: String(snapshot.notice.text),
        onClose: () => { void controller.sendEdit("dismiss_notice", {}); },
      }) : null,
      body),
    h(SaveMessage as any, { view, controller }),
    h(EditorFooter as any, { snapshot, draft, controller }),
    h(ContextMenu as any, {
      id: "tplRowMenu",
      controller: controller.libContextMenu,
      popover: controller.popover,
      triggerSelector: "#scr-editor .job-more",
      onDismiss: controller.closeLibMenu,
      onSelect: (action: string) => { void controller.handleLibMenu(action); },
    }),
    /* 2단계 머리의 드문 동사 — 「제안 n건 모두 확인」 옆에 늘어놓지 않는다(§6: 같은
       선택지를 모든 문맥에 나열하지 않는다). 되돌리는 동사는 필요할 때 찾을 수 있으면
       된다. 트리거 selector 가 lib 쪽과 갈리는 것이 두 메뉴의 dismissal 을 나눈다. */
    h(ContextMenu as any, {
      id: "bindingMoreMenu",
      controller: controller.bindingContextMenu,
      popover: controller.popover,
      triggerSelector: "#scr-editor .binding-more",
      onDismiss: controller.closeBindingMenu,
      onSelect: (action: string) => { controller.guarded(() => controller.handleBindingMenu(action)); },
    }));
}

/** 린트메모장 호스트 — vendor 수명주기를 **React 효과 하나**가 진다.
 *
 *  마운트/해제는 이 창이 살아 있는 동안만이다(`state === null` 이면 부모가 아예 렌더하지
 *  않는다). CodeMirror 타입은 `txt_lintpad.ts` 밖으로 나오지 않으므로 여기 있는 것은
 *  불투명 손잡이뿐이다(#588 봉쇄).
 *
 *  본문의 주인은 CodeMirror 문서이고 상태는 그 거울이다 — 매 렌더마다 값을 되밀어 넣지
 *  않는다(`updateLintpad` 가 같은 문자열이면 아무것도 하지 않는다). 그래서 캐럿이 튀지
 *  않으면서도 밖에서 갈아 끼운 본문은 따라 들어온다. */
function TxtLintpad(props: {
  controller: EditorController; content: string; spans: readonly LintpadSpan[] | null;
}): ReactNode {
  const { controller } = props;
  const hostRef = useRef<HTMLDivElement | null>(null);
  const handleRef = useRef<LintpadHandle | null>(null);
  /* 마지막으로 **얹은** 판정. 렌더마다 같은 좌표를 다시 dispatch 하면 타이핑 한 글자에
     트랜잭션이 둘씩 붙는다(강조는 그대로인 채 비용만 는다). */
  const appliedSpans = useRef<readonly LintpadSpan[] | null>(null);
  /* 마운트 시점의 본문만 심는다 — 이후 갱신은 아래 효과가 진다(deps 를 비워 재마운트 금지). */
  const initial = useRef<string>(props.content);
  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return undefined;
    const handle = mountLintpad({
      host,
      doc: initial.current,
      contentId: "txtEditContent",
      ariaLabel: "템플릿 내용",
      onDocChanged: (text: string) => { controller.typeTxtEdit(text); },
    });
    handleRef.current = handle;
    return () => { disposeLintpad(handle); handleRef.current = null; };
  }, []);
  useEffect(() => {
    const handle = handleRef.current;
    if (handle === null) return;
    const fresh = props.spans !== null && props.spans !== appliedSpans.current;
    if (fresh) appliedSpans.current = props.spans;
    updateLintpad(handle, {
      doc: props.content, spans: fresh ? props.spans ?? undefined : undefined,
    });
  });
  return h("div", { className: "lintpad", id: "txtLintpad", ref: hostRef });
}

/** 진단 재진술 — Python 이 낸 `message` 를 **그대로** 줄로 편다(문안 재조립 금지). */
function TxtLintReport(props: { lint: TxtLintState | null }): ReactNode {
  const { lint } = props;
  const diagnostics = lint?.diagnostics || [];
  if (lint === null) {
    return h("p", { id: "txtLintReport", className: "hint" }, "표기를 확인하는 중…");
  }
  if (diagnostics.length === 0) {
    const summary = lint.summary || {};
    return h("p", { id: "txtLintReport", className: "hint" },
      `표기 이상 없음 · 항목 ${Number(summary.slots || 0)} · 선택 ${Number(summary.options || 0)}`
      + ` · 누름틀 ${Number(summary.fields || 0)}`);
  }
  return h("div", { id: "txtLintReport", className: "note warnbox", role: "status" },
    h("p", { style: { margin: 0 } }, `구간 표기 이상 ${diagnostics.length}건`),
    h("ul", { id: "txtLintDiag", className: "muted capnote" },
      diagnostics.map((diagnostic, index) => h("li", { key: index },
        String(diagnostic.message || ""),
        diagnostic.context ? h("span", { className: "muted" }, ` — ${String(diagnostic.context)}`) : null))));
}

export function TxtEditDialog(props: { controller: EditorController }): ReactNode {
  const { controller } = props;
  /* 세 번째 인자(getServerSnapshot)는 `EditorScreen` 과 같은 이유로 선다: 없으면 이 창이
     `react-dom/server` 로 **한 번도** 렌더되지 못해 노드 배치를 단위층에서 잴 수 없다. */
  const view = useSyncExternalStore(
    controller.viewModel.subscribe, controller.viewModel.getSnapshot,
    controller.viewModel.getSnapshot);
  const state = view.txtEdit;
  /* 초기 포커스는 **커밋 뒤** 이 자리가 겨눈다. 모달 executor 의 `initialFocus` 는 열림
     **시점**의 DOM 을 보는데 이 창의 내용은 그 뒤 커밋에서 생기므로, 열림 시점에 넘기면
     대상이 없어 되돌림 트리거로 떨어진다(시트 선택이 같은 이유로 같은 형태를 쓴다). */
  useEffect(() => {
    if (state === null) return;
    /* 초기 포커스의 주인은 **여기 하나**다. 메모장이 마운트에서 스스로 겨누면 새 생성
       창에서 이름 칸과 두 번 다투고, 마지막에 이긴 쪽이 순서에 따라 갈린다. 메모장의
       컨텐츠 DOM 은 종전 id 를 그대로 이어받으므로 겨눔 방식은 바뀌지 않았다. */
    const target = controller.doc.getElementById(
      state.mode === "new" ? "txtEditName" : "txtEditContent");
    target?.focus();
  }, [state === null, state?.mode]);
  return h("div", { className: "modal-card" },
    h("h3", { id: "txtEditTitle" }, state?.title || "새 TXT 템플릿"),
    h("label", {
      className: "ctl", id: "txtNameRow",
      style: { display: state?.mode === "new" ? "" : "none" },
    },
    h("span", { className: "lbl" }, "이름(확장자 제외)"),
    h("input", {
      className: "field", id: "txtEditName", type: "text", placeholder: "예: 회의결과보고",
      value: state?.name || "",
      onChange: (event: Obj) => controller.patchTxtEdit({ name: String(event.currentTarget.value) }),
    })),
    h("p", { className: "modal-sub" },
      "{{필드}} 토큰과 {{#항목 …}} 구간 표기를 포함한 템플릿 내용"),
    state === null ? null : h(TxtLintpad as any, {
      /* 판정이 아직 없으면 `null` 이다 — 빈 배열을 주면 「강조 없음」을 매번 새로 얹는
         것과 구분되지 않는다(렌더마다 같은 좌표를 다시 dispatch 하는 자리). */
      controller, content: state.content, spans: state.lint?.spans ?? null,
    }),
    h(TxtLintReport as any, { lint: state?.lint || null }),
    h("p", {
      id: "txtEditError", className: "note dangerbox", role: "alert",
      style: { display: state?.error ? "block" : "none" },
    }, state?.error || ""),
    h("div", { className: "modal-actions" },
      h("button", {
        className: "btn", id: "txtEditCancel",
        onClick: () => controller.guarded(() => controller.confirmDiscardTxtEdit()),
      }, "취소"),
      state?.mode === "edit"
        ? h("button", {
          className: "btn", id: "txtEditSaveAs",
          onClick: (event: Obj) => controller.guarded(
            () => controller.saveTxtEditAsNew(event.currentTarget)),
        }, "새 파일로 저장…")
        : null,
      h("button", {
        className: "btn primary", id: "txtEditOk",
        onClick: () => controller.guarded(() => controller.submitTxtEdit()),
      }, "저장")));
}
