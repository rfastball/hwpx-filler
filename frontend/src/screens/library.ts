/* R4-01 「문서 작업」 React 표면. Python snapshot의 판정을 다시 만들지 않고 목록·상세·
   필터·관리 동사를 createElement 트리로 투영한다. 화면 root와 이동 dialog content의 DOM,
   이벤트, pending search 수명주기는 React가 단독 소유한다. */
import {
  createElement,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";

import type { BridgeClient } from "../runtime/client.ts";
import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import type { ScreenPorts } from "./ports.ts";
import type { ScreenRuntime } from "./runtime.ts";
import { expectHostValue } from "./runtime.ts";
import type { ContextMenuPopoverPort } from "./context_menu.ts";
import { PathActions } from "./path_actions.ts";
import { BLANK_MARK, PreviewCell } from "./preview_cell.ts";

type Obj = Record<string, any>;

type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
  prompt(spec: Obj): Promise<string | null>;
  open(id: string, spec?: Obj): void;
  close(id: string): void;
};

type UndoPort = { show(message: string, action: () => unknown): void };

export type LibraryControllerDeps = {
  doc: Document;
  runtime: ScreenRuntime;
  client: BridgeClient;
  ports: ScreenPorts;
  services: ServiceHandoffPorts;
  modal: ModalPort;
  undo: UndoPort;
  popover: ContextMenuPopoverPort;
  navigation: { go(screen: string): void };
  notify(message: string): void;
};

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

function valueOf(result: Awaited<ReturnType<BridgeClient["dispatch"]>>, label: string): Obj {
  return (expectHostValue(result, label) ?? {}) as Obj;
}

export function createLibraryController(deps: LibraryControllerDeps) {
  const model = deps.runtime.model<Obj | null>("library");
  let axisTail = Promise.resolve();
  const favoriteTail = new Map<string, Promise<void>>();
  const favoriteIntent = new Map<string, boolean>();
  const favoriteRevision = new Map<string, number>();

  const dispatch = async (screen: string, action: string, payload: Obj = {}): Promise<Obj> => {
    const call = deps.client.dispatch as unknown as (
      channel: string, name: string, body: Obj,
    ) => ReturnType<BridgeClient["dispatch"]>;
    return valueOf(await call(screen, action, payload), `${screen}/${action}`);
  };

  const invoke = async (method: Parameters<BridgeClient["invoke"]>[0], ...args: unknown[]) =>
    expectHostValue(await deps.client.invoke(method, ...args), method);

  function axis(action: string, payload: Obj = {}): Promise<void> {
    const send = async (): Promise<void> => { await dispatch("library", action, payload); };
    const next = axisTail.then(send, send);
    axisTail = next.catch(() => undefined);
    return next;
  }

  function snapshot(): Obj | null {
    return model.getSnapshot();
  }

  function selected(name: string): Obj | null {
    const detail = snapshot()?.detail;
    if (detail && detail.name === name) return detail;
    deps.notify(`'${name}' 작업의 현재 상태를 읽지 못해 중단했습니다.\n목록을 새로 고친 뒤 다시 시도하세요.`);
    return null;
  }

  async function jobDispatch(action: string, payload: Obj, selectIfOk = ""): Promise<Obj> {
    const result = await dispatch("job", action, payload);
    await dispatch("library", "refresh", result.ok === false || selectIfOk === ""
      ? {} : { select: selectIfOk });
    return result;
  }

  async function renameJob(name: string, returnFocus: HTMLElement): Promise<void> {
    await deps.modal.prompt({
      body: `'${name}' 의 새 이름을 입력하세요.`, value: name, returnFocus,
      validate: async (raw: unknown) => {
        const next = String(raw || "").trim();
        const result = await jobDispatch("rename_job", { name, new: raw }, next);
        return result.ok === false ? (result.error || "이름을 바꾸지 못했습니다.") : "";
      },
    });
  }

  async function removeJob(name: string, returnFocus: HTMLElement): Promise<void> {
    let result = await dispatch("library", "delete_job", { name });
    if (result.needs_confirm) {
      const accepted = await deps.modal.confirm({
        title: "작업 삭제 확인",
        body: `작업 '${name}' 이(가) 문서 만들기 화면에 진행 중인 세션으로 열려 있습니다.\n삭제하면 그 세션의 선택·데이터·진행이 함께 사라집니다.`,
        confirmLabel: "삭제", cancelLabel: "취소", returnFocus,
      });
      if (!accepted) return;
      result = await dispatch("library", "delete_job", { name, confirm: true });
    }
    if (result.undo) {
      deps.undo.show(`작업 '${name}' 을(를) 삭제했습니다.`, async () => {
        const restored = await dispatch("library", "undo_delete_job", {});
        if (restored.ok === false) throw new Error(String(restored.error));
      });
    }
  }

  async function runPrimary(name: string): Promise<void> {
    const work = selected(name);
    if (work === null) return;
    const target = work.primary?.target || "job";
    if (target === "editor") {
      deps.ports.editorEntry.current().openGuarded(name, {
        entry_reason: "library",
        evidence: { "여기서 고칠 것": "이 작업은 아직 「문서 만들기」가 받을 수 없습니다" },
        return_context: { surface: "library" },
      });
      return;
    }
    const result = await dispatch("job", "prefer_work", { name });
    deps.navigation.go("job");
    if (result.reason === "incompatible") {
      await deps.ports.jobRead.current().openBrowseNeedsAction(name);
    }
  }

  async function toggleFavorite(name: string, shown: boolean): Promise<void> {
    const intended = !(favoriteIntent.get(name) ?? shown);
    favoriteIntent.set(name, intended);
    const revision = (favoriteRevision.get(name) ?? 0) + 1;
    favoriteRevision.set(name, revision);
    const previous = favoriteTail.get(name) ?? Promise.resolve();
    const next = previous.then(async () => {
      const value = intended;
      const result = await dispatch("library", "toggle_favorite", { name, value });
      if (result.ok === false) deps.notify(result.error || "즐겨찾기를 바꾸지 못했습니다.");
      if (favoriteRevision.get(name) === revision) {
        favoriteIntent.delete(name);
        favoriteRevision.delete(name);
      }
    });
    favoriteTail.set(name, next.catch((error) => deps.notify(String(error))));
    await next;
  }

  async function deleteCorrupt(path: string): Promise<void> {
    let result = await dispatch("library", "delete_corrupt", { path });
    if (result.needs_confirm && await deps.modal.confirm({
      body: result.confirm_text, confirmLabel: "삭제", cancelLabel: "취소", danger: true,
    })) {
      result = await dispatch("library", "delete_corrupt", { path, confirm: true });
    }
  }

  return {
    init(): Promise<unknown> { return deps.runtime.loadInitial("library"); },
    model,
    axis,
    toggleFavorite,
    runPrimary,
    newWork: () => deps.ports.editorEntry.current().newDraft(),
    /* `extra` 는 편집기 deep-link 의 거친 형태(`section`)를 실어 보내는 자리다 — 재선택
       바로가기가 「어느 탭에 착지하는가」를 여기서 정한다. 배관은 이미 서 있다:
       `app.py` 의 `open_editor` 가 `ctx.section` 을 `load_job(landing_section=…)` 으로
       넘긴다(신설 없음). 이탈 가드는 `openGuarded` 가 그대로 진다. */
    editWork(name: string, evidence: Obj = {}, extra: Obj = {}): unknown {
      return deps.ports.editorEntry.current().openGuarded(name, {
        entry_reason: "library", evidence, return_context: { surface: "library" }, ...extra,
      });
    },
    renameJob,
    cloneJob: (name: string) => dispatch("library", "clone_job", { name }),
    removeJob,
    relink(name: string): Promise<boolean> {
      return deps.services.relink.current().relinkTemplate("library", name, (message, kind) => {
        if (kind === "ok") deps.notify(message);
      });
    },
    revealCorrupt: (path: string) => invoke("reveal_corrupt_job", path),
    deleteCorrupt,
    doc: deps.doc,
    client: deps.client,
    popover: deps.popover,
    notify: deps.notify,
  };
}

export type LibraryController = ReturnType<typeof createLibraryController>;

function HealthPill({ health }: { health?: Obj }): ReactNode {
  if (!health?.severity) return null;
  return h("span", { className: `pill ${health.severity >= 3 ? "danger" : "warn"}` }, health.text);
}

function LibraryRow(props: { row: Obj; selected: string; controller: LibraryController }): ReactNode {
  const { row, selected, controller } = props;
  const active = row.name === selected;
  return h("div", { className: `lib-row${active ? " on" : ""}`, key: row.name },
    h("button", {
      className: "lib-row-main", "data-work": row.name,
      "aria-current": active ? "true" : "false", "data-busy-lock": true,
      onClick: () => { void controller.axis("select_work", { name: row.name }); },
    },
    h("span", { className: "lib-row-name" }, row.name, h(HealthPill as any, { health: row.health }), row.data_bound === false ? h("span", { className: "pill warn", title: "데이터를 연결해야 문서를 만들 수 있습니다." }, "연결 필요") : null),
    h("span", { className: "lib-row-meta" }, row.mode_label)),
    h("button", {
      className: "lib-fav", "data-fav": row.name,
      "aria-pressed": row.favorited ? "true" : "false",
      "aria-label": `${row.name} 즐겨찾기`, title: "즐겨찾기", "data-busy-lock": true,
      onClick: () => { void controller.toggleFavorite(row.name, !!row.favorited); },
    }, row.favorited ? "★" : "☆"));
}

function LibraryList(props: { snapshot: Obj; controller: LibraryController }): ReactNode {
  const { snapshot, controller } = props;
  const sections = snapshot.sections || [];
  const shown = sections.reduce((sum: number, section: Obj) => sum + Number(section.count || 0), 0);
  let content: ReactNode;
  if (snapshot.is_empty) {
    /* 빈 상태의 출구는 하나다 — 직접 만들기. 동봉 예제로 시작하는 두 번째 출구(#891)는
       튜토리얼 진입 표면과 함께 배포본에서 걷혔다(#941). 스냅샷의 `examples` 축은 그대로
       서 있으므로 되살릴 때 이 자리에서 다시 소비하면 된다. */
    content = h("div", { className: "empty" }, h("div", { className: "heading" }, "저장된 작업이 없습니다"),
      h("p", null, "템플릿과 매핑을 묶어 첫 작업을 만드세요.\n데이터·행은 문서를 만들 때 고릅니다."),
      h("button", { className: "btn primary", "data-new-work": true, onClick: controller.newWork }, "＋ 첫 작업 만들기"));
  } else if (!shown) {
    content = h("div", { className: "empty" }, h("div", { className: "heading" }, "조건에 맞는 작업이 없습니다"),
      h("p", null, "보기·작업 방식·검색 중 하나가 목록을 비웠습니다."),
      h("button", { className: "btn", "data-clear-filters": true, onClick: () => { void controller.axis("clear_filters"); } },
        "필터 지우고 전체 보기"));
  } else {
    /* 구획 헤더는 없다(U4 §2-30) — 그룹 표면이 걷혀 백엔드가 언제나 헤더 없는 평면
       1구획을 낸다. 구획 구조 자체는 스냅샷 계약이라 그대로 훑는다. */
    content = sections.flatMap((section: Obj) =>
      (section.rows || []).map((row: Obj) =>
        h(LibraryRow as any, { key: row.name, row, selected: snapshot.selected, controller })));
  }
  return h("section", {
    className: "library-list-pane", id: "libraryPanel", role: "tabpanel",
    "aria-labelledby": `library-view-${snapshot.view || "all"}`,
  },
  h("p", { className: "library-count", id: "libraryCount", tabIndex: -1, role: "status", "aria-live": "polite" },
    snapshot.is_empty ? "저장된 작업이 없습니다." : `${shown}건`),
  h("div", { className: "library-list", id: "libraryList", "data-preserve-scroll": true }, content));
}

function LibraryDetailRoot({ children }: { children: ReactNode }): ReactNode {
  return h("aside", {
    className: "library-detail", id: "libraryDetail", "aria-label": "선택한 작업 상세",
  }, children);
}

/** 연결 카드의 한 축(템플릿 / 데이터) — 항목 + 경로 동사 + 재선택 바로가기.
 *
 *  재선택은 **정체를 보는 자리에서 그 정체를 바꾸러 가는 길**이다. 착지 탭은 Python 이
 *  아는 편집기 섹션 어휘(`gui/edit_session.py`: template / binding)를 그대로 싣고, 진입
 *  가드·데이터 인계는 `editWork` → `openGuarded` 가 종전대로 진다(#966 deep-link 불변). */
function PairSide(props: {
  name: string; sub: ReactNode; path: string; warn?: boolean;
  controller: LibraryController; action: ReactNode;
}): ReactNode {
  const { name, sub, path, warn, controller, action } = props;
  return h("div", { className: "side" },
    h("div", { className: `lib-pitem${warn ? " warn" : ""}` },
      h("span", { className: "ic" }),
      h("span", { className: "lib-pitem-text" },
        h("span", { className: "nm" }, name || BLANK_MARK),
        h("span", { className: "sb" }, sub)),
      path ? h(PathActions as any, {
        client: controller.client, path, notify: controller.notify,
      }) : null),
    action);
}

/** 연결 카드 — 「무엇과 무엇이 붙었나」. 좁은 상세 패널이라 편집기의 가로 3열을 **눕힌다**:
 *  같은 링1 투영, 다른 배치다(동결 시안 장면 4). 수치는 Python 이 세고 여기서는 그리기만
 *  한다 — 세지 못한 갈래(`counted` 거짓)에는 수치 줄을 세우지 않는다(0 을 사실처럼 말하지
 *  않는다). 표가 서지 않는 갈래에서도 이 카드는 남는다: 고치러 갈 동사가 여기 있다. */
function PairCard(props: {
  detail: Obj; card: Obj; staleFields: string[]; controller: LibraryController;
}): ReactNode {
  const { detail, card, staleFields, controller } = props;
  const dataBound = detail.data_bound;
  return h("div", { className: "lib-paircard", id: "libraryPairCard" },
    h(PairSide as any, {
      name: String(card.template_name || ""),
      sub: card.counted ? `필드 ${card.template_field_count}개` : "",
      path: String(detail.template_path || ""),
      warn: !!card.template_missing || !card.template_bound,
      controller,
      action: h("button", { className: "btn sm", id: "libraryRepickTemplate", "data-repick": "template",
        onClick: () => controller.editWork(detail.name, {
          "여기서 할 것": "「템플릿」 탭에서 다른 템플릿을 고르고 저장하세요",
        }, { section: "template" }) }, "템플릿 재선택…"),
    }),
    h("div", { className: "mid" },
      h("span", { className: "vwire", "aria-hidden": "true" }),
      card.counted ? h("span", { className: "nums" },
        h("b", null, `연결 ${card.mapped_count} / ${card.template_field_count}`),
        ` · 확인 필요 ${card.unbound_count}`,
        /* 템플릿에서 사라진 연결은 숨기지 않는다 — 실행 게이트가 막는 상태이고,
           목록이 침묵하면 사용자는 눌러 보고서야 안다. */
        card.stale_count ? h("span", { className: "stale" },
          `템플릿에 없는 연결 ${card.stale_count}건: ${staleFields.join(" · ")}`) : null) : null),
    /* 데이터 축은 템플릿 바로 옆이다(#932 U4-C) — 「무엇으로 만드는가」의 두 축이라
       한쪽만 보이면 상세가 절반만 말한다. 미결속은 빈칸이 아니라 **사유와 동선**이다. */
    h(PairSide as any, {
      name: dataBound ? String(card.data_name || "") : "",
      sub: dataBound
        ? String(detail.data_label || "")
        : h("span", { className: "why" }, "데이터를 연결해야 문서를 만들 수 있습니다."),
      path: dataBound ? String(detail.data_path || "") : "",
      warn: !dataBound,
      controller,
      action: dataBound
        ? h("button", { className: "btn sm", id: "libraryRepickData", "data-repick": "data",
          onClick: () => controller.editWork(detail.name, {
            "여기서 할 것": "「필드 연결」 탭에서 다른 데이터를 고르고 저장하세요",
          }, { section: "binding" }) }, "데이터 재선택…")
        : h("button", { className: "btn sm", "data-connect-data": detail.name,
          onClick: () => controller.editWork(detail.name, {
            "여기서 할 것": "「필드 연결」 탭에서 데이터를 고르고 저장하세요",
          }) }, "데이터 연결하기…"),
    }));
}

/** 읽기 전용 4열 표 — 필드 · 데이터 열 · 표시형 · 첫 행.
 *
 *  행은 편집기 2단계와 **같은 링1 투영**이고 두 라벨도 Python 이 해소해 보낸다. 행을 누르면
 *  같은 배관으로 편집기 2단계의 그 행에 착지한다(`target: binding/<필드>` — 배선은 이미 서
 *  있다: `app.py` `ctx.target` → `load_job(target=…)` → `aimAtTarget`). */
function PairTable(props: { detail: Obj; zone: Obj; controller: LibraryController }): ReactNode {
  const { detail, zone, controller } = props;
  const firstRow = (zone.first_row || {}) as Obj;
  const rows = (zone.rows || []) as Obj[];
  const more = (zone.more_fields || []) as string[];
  const open = (field: string) => controller.editWork(detail.name, {
    "여기서 할 것": "「연결 확인」에서 이 행의 데이터 열을 확인하세요",
  }, { target: `binding/${field}` });
  return h("table", { className: "ro", id: "libraryPairRows", "data-first-row": String(firstRow.state || "") },
    h("thead", null, h("tr", null,
      h("th", null, "템플릿 필드"), h("th", null, "데이터 열"),
      h("th", null, "표시형"), h("th", null, "첫 행"))),
    h("tbody", null,
      /* 행 자체가 손잡이다. `role="button"` 은 **얹지 않는다** — `tr` 의 암묵 role 을 덮으면
         표의 구조가 보조기술에서 무너진다. 초점 가능 + Enter/Space + 제목으로 어포던스를
         세우고, 무엇이 일어나는지는 계획 줄이 한 번 더 말한다. */
      ...rows.map((row) => h("tr", {
        key: String(row.template_field), "data-field": row.template_field,
        tabIndex: 0, title: `'${row.template_field}' 연결을 편집기에서 확인합니다`,
        onClick: () => open(String(row.template_field)),
        onKeyDown: (event: Obj) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault(); open(String(row.template_field));
        },
      },
      h("td", { className: "f" }, String(row.template_field)),
      h("td", null, String(row.source_label || "")),
      h("td", null, String(row.display_label || "")),
      /* 첫 행 칸은 편집기 「미리보기」 열과 **같은 렌더러**다 — 닫힌 집합을 두 곳에서
         스위치하면 그 집합이 갈린다. 갈리는 것은 오류의 문장 하나이고, 그것은 행마다 같은
         문장이라 존 수준에서 받는다. */
      h("td", null, h(PreviewCell as any, {
        row, errorText: firstRow.state === "error" ? String(firstRow.reason || "") : "",
      })))),
      /* 프레임 밖 행은 스크롤로 조용히 감추지 않고 **이름으로** 말한다(시안 944). */
      more.length ? h("tr", { className: "more-row" },
        h("td", { colSpan: 4 }, `그 밖에 ${more.length}행: ${more.join(" · ")}`)) : null));
}

/** 계획 한 줄 — 「이 작업이 만들 파일」. 이름은 실제 생성기와 같은 함수가 만든 것이고,
 *  아직 못 읽었으면 이름 대신 **규칙**을 말한다(아는 것만 말한다). */
function PlanLine(props: { zone: Obj }): ReactNode {
  const plan = (props.zone.plan || {}) as Obj;
  const folder = (props.zone.output_folder || {}) as Obj;
  const ready = plan.state === "ready";
  return h("p", { className: "plan-line", id: "libraryPlanLine" },
    "문서 파일 이름 ",
    ready ? h("b", null, String(plan.first_name || "")) : h("span", { className: "muted" }, `규칙 ${plan.pattern || ""}`),
    ready ? ` · ${plan.count}건` : "",
    folder.directory ? h("span", null, " · 저장 폴더 ", h("b", null, String(folder.directory))) : null,
    " · 행을 누르면 편집기 '연결 확인' 으로 갑니다.");
}

function LibraryDetail(props: { detail: Obj | null; controller: LibraryController }): ReactNode {
  const { detail, controller } = props;
  if (!detail) return h(LibraryDetailRoot as any, null,
    h("p", { className: "lib-detail-blank muted" }, "왼쪽에서 작업을 고르면 상세가 열립니다."));
  const primary = detail.primary || { label: "문서 만들기에서 사용", hint: "" };
  const health = detail.health_causes?.length ? h("div", { className: "note warnbox" },
    h("div", { className: "cap" }, "확인할 것"),
    h("ul", { className: "lib-causes" },
      ...detail.health_causes.map((cause: Obj, index: number) => h("li", { key: index }, cause.text))),
    detail.template_missing ? h("button", {
      className: "btn sm", "data-relink": detail.name,
      onClick: () => { void controller.relink(detail.name); },
    }, "템플릿 다시 연결…") : null) : null;
  /* 상세 하단은 U6-F(#980)에서 연결 그림이 됐다 — 종전의 사실 3행(dl)이 답하던 정체는
     카드가 지고, 「이 작업은 무엇을 무엇으로 채워 어떤 파일을 만드나」를 표와 계획 줄이
     잇는다. 표가 서지 않는 갈래(템플릿을 읽을 수 없음)에서도 카드는 남는다. */
  const zone = (detail.pairing_detail || {}) as Obj;
  const card = (zone.card || {}) as Obj;
  const rows = (zone.rows || []) as Obj[];
  const scroll = h("div", { className: "lib-detail-scroll", "data-preserve-scroll": true },
    h("h2", { className: "lib-detail-name" }, detail.name),
    h("p", { className: "lib-detail-sub" }, detail.mode_label),
    health,
    h(PairCard as any, {
      detail, card, controller,
      staleFields: (zone.stale_fields || []) as string[],
    }),
    /* 행의 출처가 저장본이면 **그렇다고 말한다** — 표가 템플릿의 현재 모습인 척하면
       사라진 필드·새 필드를 조용히 감춘다(문안은 Python 이 아니라 여기 하나뿐이라 상수로
       올리지 않는다 — `docs/UI_CONTRACT.md` 단일 출처 규칙). */
    zone.rows_basis === "profile" ? h("p", { className: "rows-basis note warnbox" },
      "템플릿을 읽지 못해 저장된 연결만 보여 줍니다.") : null,
    rows.length ? h(PairTable as any, { detail, zone, controller }) : null,
    rows.length && zone.plan ? h(PlanLine as any, { zone }) : null);
  const actions = h("div", { className: "lib-detail-acts" },
    h("button", { className: "btn primary sm", "data-use": detail.name, title: primary.hint,
      onClick: () => { void controller.runPrimary(detail.name); } }, primary.label),
    h("button", { className: "btn sm", "data-edit": detail.name,
      onClick: () => controller.editWork(detail.name) }, "작업 편집"),
    h("span", { className: "lib-detail-manage" },
      h("button", { className: "btn sm", "data-rename": detail.name,
        onClick: (event: Obj) => { void controller.renameJob(detail.name, event.currentTarget); } }, "이름 변경"),
      h("button", { className: "btn sm", "data-clone": detail.name,
        onClick: () => { void controller.cloneJob(detail.name); } }, "복제"),
      h("button", { className: "btn sm lib-del", "data-delete": detail.name,
        onClick: (event: Obj) => { void controller.removeJob(detail.name, event.currentTarget); } }, "삭제")));
  return h(LibraryDetailRoot as any, null, scroll, actions);
}

function LibraryToolbar(props: { snapshot: Obj; controller: LibraryController }): ReactNode {
  const { snapshot, controller } = props;
  const [search, setSearch] = useState(String(snapshot.query || ""));
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (controller.doc.activeElement?.id !== "librarySearch") setSearch(String(snapshot.query || ""));
  }, [snapshot.query]);
  useEffect(() => () => { if (timer.current !== null) clearTimeout(timer.current); }, []);
  const views = ["all", "recent", "favorites", "needsAction"];
  const modes = [["all", "전체"], ["hwpx", "HWPX 문서 생성"], ["txt", "온나라 기안 검토·복사"]];
  return h("div", { className: "library-toolbar" },
    h("label", { className: "library-search-field" }, h("span", { className: "lbl" }, "작업 검색"),
      h("input", { className: "field", id: "librarySearch", type: "search", autoComplete: "off",
        /* 링1(`HomeViewModel._library_pool`)은 이름·사용자 group·태그 값을 훑지만, 뒤의 두
           축은 U4 §2-30 에서 표면이 걷혀 **사용자가 만들 자리가 없다** — 그것을 안내로
           내걸면 있지도 않은 축으로 찾으라는 말이 된다. 문안은 실제로 쓸 수 있는 축만
           말한다(판정·매칭 범위는 링1 그대로, 동결 축은 그대로 동결). */
        placeholder: "작업 이름", "data-busy-lock": true, value: search,
        onChange: (event: Obj) => {
          const text = String(event.currentTarget.value);
          setSearch(text);
          if (timer.current !== null) clearTimeout(timer.current);
          timer.current = setTimeout(() => { timer.current = null; void controller.axis("set_query", { text }); }, 180);
        } })),
    h("div", { className: "library-filter-group" }, h("span", { className: "library-filter-label", id: "libraryViewLabel" }, "보기"),
      h("div", { className: "library-tabs", role: "tablist", "aria-labelledby": "libraryViewLabel", id: "libraryViewTabs",
        onKeyDown: (event: Obj) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          const index = views.findIndex((view) => view === snapshot.view);
          const next = views[(index + (event.key === "ArrowRight" ? 1 : views.length - 1)) % views.length];
          event.preventDefault(); void controller.axis("set_view", { view: next });
        } },
        h("button", { type: "button", role: "tab", id: "library-view-all", "data-library-view": "all", "data-label": "모든 작업",
          "aria-controls": "libraryPanel", "aria-selected": snapshot.view === "all" ? "true" : "false",
          tabIndex: snapshot.view === "all" ? 0 : -1, "data-busy-lock": true,
          onClick: () => { void controller.axis("set_view", { view: "all" }); } },
        `모든 작업${typeof snapshot.counts?.all === "number" ? ` · ${snapshot.counts.all}` : ""}`),
        h("button", { type: "button", role: "tab", id: "library-view-recent", "data-library-view": "recent", "data-label": "최근 사용",
          "aria-controls": "libraryPanel", "aria-selected": snapshot.view === "recent" ? "true" : "false",
          tabIndex: snapshot.view === "recent" ? 0 : -1, "data-busy-lock": true,
          onClick: () => { void controller.axis("set_view", { view: "recent" }); } },
        `최근 사용${typeof snapshot.counts?.recent === "number" ? ` · ${snapshot.counts.recent}` : ""}`),
        h("button", { type: "button", role: "tab", id: "library-view-favorites", "data-library-view": "favorites", "data-label": "즐겨찾기",
          "aria-controls": "libraryPanel", "aria-selected": snapshot.view === "favorites" ? "true" : "false",
          tabIndex: snapshot.view === "favorites" ? 0 : -1, "data-busy-lock": true,
          onClick: () => { void controller.axis("set_view", { view: "favorites" }); } },
        `즐겨찾기${typeof snapshot.counts?.favorites === "number" ? ` · ${snapshot.counts.favorites}` : ""}`),
        h("button", { type: "button", role: "tab", id: "library-view-needsAction", "data-library-view": "needsAction", "data-label": "확인 필요",
          "aria-controls": "libraryPanel", "aria-selected": snapshot.view === "needsAction" ? "true" : "false",
          tabIndex: snapshot.view === "needsAction" ? 0 : -1, "data-busy-lock": true,
          onClick: () => { void controller.axis("set_view", { view: "needsAction" }); } },
        `확인 필요${typeof snapshot.counts?.needsAction === "number" ? ` · ${snapshot.counts.needsAction}` : ""}`)),
    ),
    h("div", { className: "library-filter-group" }, h("span", { className: "library-filter-label", id: "libraryModeLabel" }, "작업 방식"),
      h("div", { className: "library-modes", role: "group", "aria-labelledby": "libraryModeLabel", id: "libraryModeFilters" },
        ...modes.map(([mode, label]) => h("button", { className: "pill", type: "button",
          "data-library-mode": mode, "aria-pressed": snapshot.mode === mode ? "true" : "false",
          "data-busy-lock": true, key: mode, onClick: () => { void controller.axis("set_mode", { mode }); } }, label)))),
    );
}

export function LibraryScreen(props: { controller: LibraryController }): ReactNode {
  const { controller } = props;
  /* 세 번째 인자(server snapshot)는 `EditorScreen` 선례를 따른다: 제품 런타임은 쓰지 않지만,
     없으면 이 셸이 `react-dom/server` 로 **한 번도** 렌더되지 못해 빈 상태의 노드 배치 계약을
     단위층에서 잴 수 없다(#891 — 두 출구가 어느 갈래에 서는가가 결과인 계약이다). */
  const snapshot = useSyncExternalStore(
    controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot);
  if (snapshot === null) return h("p", { className: "note", role: "status" }, "문서 작업을 읽는 중…");
  const alerts = snapshot.alerts || {};
  return h("div", { className: "library-react-surface" },
    h("header", { className: "scr-head" }, h("div", null, h("h1", null, "문서 작업"),
      h("p", { className: "sub" }, "저장된 문서 작업을 찾고 상태를 확인합니다.")),
    h("div", { className: "scr-head-actions" }, h("button", { className: "btn primary sm", id: "libraryNewWork",
      onClick: controller.newWork }, "＋ 새 작업"))),
    h("div", { id: "libraryAlerts" },
      alerts.missing_template_count > 0 ? h("div", { className: "note warnbox" }, `템플릿이 연결되지 않은 작업 ${alerts.missing_template_count}건이 있습니다. 「확인 필요」 보기에서 조치하세요.`) : null,
      alerts.pool_corrupted > 0 ? h("div", { className: "note dangerbox" }, `손상된 등록 데이터 ${alerts.pool_corrupted}건이 있습니다. 「문서 만들기」의 [데이터 선택…]에서 확인하세요.`) : null),
    h("div", { id: "libraryCorrupt", style: { display: snapshot.corrupt_rows?.length ? "" : "none" } },
      ...(snapshot.corrupt_rows || []).map((row: Obj) => h("div", { className: "jcard corrupt", key: row.path },
        h("div", { className: "jn" }, row.file_name, " ", h("span", { className: "pill danger" }, "손상됨")),
        h("div", { className: "jm" }, row.detail_line),
        h("div", { className: "jfoot" }, h("span", null), h("span", { className: "acts" },
          h("button", { className: "btn sm", "data-reveal": row.path, onClick: () => { void controller.revealCorrupt(row.path); } }, "폴더 열기"),
          h("button", { className: "btn sm", "data-del-corrupt": row.path, onClick: () => { void controller.deleteCorrupt(row.path); } }, "삭제")))))) ,
    h(LibraryToolbar as any, { snapshot, controller }),
    h("div", { className: "library-browser" },
      h(LibraryList as any, { snapshot, controller }),
      h(LibraryDetail as any, { detail: snapshot.detail, controller })));
}
