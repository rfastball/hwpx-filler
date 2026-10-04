import { createElement as h } from "react";
import type { ReactNode } from "react";
import type { AuthoringController } from "./authoring_controller.ts";
import { TPL_STATUS_COPY } from "./job_run.ts";
import { copyText, StructureDelta, DOCK_PANELS, focusRequest, dockTabs } from "./authoring_commands.ts";
import { KIND_LABEL, SEVERITY_LABEL, CATEGORY_LABEL, IDENTIFIER_IMPACT, kindTag, problemFix, problemAction } from "./authoring_outline_model.ts";
import { joined } from "./authoring_outline.ts";
import { Trial } from "./authoring_trial.ts";
import { ExternalDocument } from "./authoring_editor.ts";
import { button, quiet, primary, rowButton, rowList } from "./authoring_primitives.ts";
import type { Obj } from "./authoring_primitives.ts";

export type DockContext = { controller: AuthoringController; item: Obj | undefined; view: Obj;
  act: (work: () => unknown, kind?: string) => () => void;
  selectInDock: (entry: Obj) => () => void;
  externalVerbs: (saveFailed: boolean) => ReactNode[];
  closePanel: (patch: Obj) => void };

type DockControlContext = { controller: AuthoringController; view: Obj; dock: ReturnType<typeof dockTabs>;
  act: (work: () => unknown, kind?: string) => () => void; openPanel: (panel: string) => void;
  returnFocus: (slot: "dock") => void };

export function dockControls({ controller, view, dock, act, openPanel, returnFocus }: DockControlContext) {
  const openDock = (key: string) => {
    const request = () => controller.update(focusRequest(controller.viewModel.getSnapshot(), "dock"));
    if (key === dock.active) return request();
    if (key === "raw") return act(async () => { await controller.raw(); request(); })();
    if (key === "impact") return act(async () => { await controller.impact(); request(); })();
    if (DOCK_PANELS.includes(key)) return openPanel(key);
    controller.update({ dock: key, dockClosed: false, contextMenu: null, ...(key === "trial" ? { trial: true } : {}), ...(DOCK_PANELS.includes(view.panel) ? { panel: "" } : {}), ...focusRequest(view, "dock") });
  };
  const closeDock = () => {
    controller.update({ ...(DOCK_PANELS.includes(view.panel) ? { panel: "" } : {}), trial: false, dock: "", dockClosed: true, dockMax: false });
    returnFocus("dock");
  };
  const closePanel = (patch: Obj) => { controller.update(patch); returnFocus("dock"); };
  return { openDock, closeDock, closePanel };
}

export function renderDockContent(key: string, { controller, item, view, act, selectInDock, externalVerbs, closePanel }: DockContext): ReactNode {
    if (key === "trial" && item) return h(Trial, { controller, item, view });
    if (!item) return null;
    if (key === "paste") return h("section", { className: "authoring-bottom", "aria-label": "의미 붙여넣기" }, h("h2", null, "의미 붙여넣기"),
      h("p", null, "문서에서 붙여넣을 위치를 고르세요. 같은 이름의 필드 연결과 새 식별자를 확인한 뒤 적용합니다."),
      h("form", { onSubmit: (event: any) => { event.preventDefault(); const data = new FormData(event.currentTarget); act(() => controller.paste(data.has("meaning"), String(data.get("new_id") || ""), data.has("link_existing")))(); } },
        h("label", null, h("input", { type: "checkbox", name: "meaning", defaultChecked: true }), "의미 포함"),
        h("label", null, h("input", { type: "checkbox", name: "link_existing" }), "같은 이름의 기존 필드에 연결"),
        h("label", null, "새 연결 식별자 ", h("input", { name: "new_id", className: "field" })),
        h("button", { className: "btn", disabled: !controller.clipboard() }, "붙여넣기 미리보기")),
      view.command?.type === "paste" && view.preview && h("div", { className: "authoring-preview" },
        h("pre", { role: "group", "aria-label": "변경 전" }, view.preview.before), h("pre", { role: "group", "aria-label": "변경 후" }, view.preview.after),
        h("div", { className: "authoring-actions" }, quiet("취소", () => controller.update({ preview: null })), primary("붙여넣기 적용", act(controller.applyPreview)))));
    if (key === "search") return h("section", { className: "authoring-bottom", "aria-label": "검색" }, h("h2", null, "검색"),
      h("form", { onSubmit: (event: any) => { event.preventDefault(); const values = new FormData(event.currentTarget); act(() => controller.search(String(values.get("query")), String(values.get("kind")), values.has("all")))(); } },
        h("input", { className: "field", name: "query", "aria-label": "검색어", defaultValue: view.query }),
        h("select", { className: "field", name: "kind", "aria-label": "검색 대상" }, h("option", { value: "body" }, "본문"), h("option", { value: "field" }, "필드"), h("option", { value: "structure" }, "항목·선택"), h("option", { value: "all" }, "전체")),
        h("label", null, h("input", { type: "checkbox", name: "all" }), "열린 모든 문서"), h("button", { className: "btn" }, "찾기")),
      // 요약과 종류는 Python 이 센 것·준 것 그대로다(§6.3). 여러 문서를 찾으면 문서마다 한 줄씩 선다. 읽기는 셸의 live region 이 한다.
      ...(view.searchSummaries || []).map((entry: Obj, index: number) => h("p", { key: `summary-${index}`, className: "authoring-search-summary" },
        view.searchSummaries.length > 1 ? `${entry.document} · ${entry.summary}` : entry.summary)),
      // 적중은 원문으로 옮겨 가는 행이다(UX-09): 종류 칩 · 문맥 · 흐린 문서 이름 · 이동 화살표.
      rowList("검색 결과", view.hits.map((hit: Obj) => rowButton({ chip: KIND_LABEL[hit.kind] ? kindTag(hit.kind) : null, text: hit.context || hit.name || hit.label, context: hit.document }, selectInDock(hit)))));
    // 원문 표기(F26·UI09): Python 이 지은 문법 표현을 본문 항목별로 읽기 전용으로 보인다.
    if (key === "raw") return h("section", { className: "authoring-bottom", "aria-label": "원문 표기" }, h("h2", null, "원문 표기"),
      view.syntax?.note && h("p", null, view.syntax.note),
      ...(view.syntax?.sections || []).map((section: Obj, index: number) => h("div", { key: index, className: "authoring-syntax" },
        h("h3", null, section.entry), h("pre", { tabIndex: 0, role: "group", "aria-label": `${section.entry} 원문 표기` }, section.text))),
      quiet("복사", act(() => copyText((view.syntax?.sections || []).map((section: Obj) => section.text).join("\n\n"))), { disabled: !view.syntax?.sections?.length }));
    if (key === "impact") return h("section", { className: "authoring-bottom", "aria-label": "변경 영향·작업 적용" }, h("h2", null, "변경 영향·작업 적용"),
      view.impact?.save_required && h("p", null, "템플릿을 저장한 뒤 적용할 작업을 확인하세요."),
      view.impact?.structure_delta && h(StructureDelta, { delta: view.impact.structure_delta }),
      !!view.impact?.identifier_changes?.length && h("ul", { "aria-label": "식별자 변경" }, ...view.impact.identifier_changes.map((entry: Obj | string, index: number) =>
        h("li", { key: index }, typeof entry === "string" ? entry : `${KIND_LABEL[entry.kind] || entry.kind || ""} · ${entry.from ?? entry.id ?? ""}${entry.to != null ? ` → ${entry.to}` : ""}`))),
      (!!view.impact?.structure_delta?.renamed?.length || !!view.impact?.identifier_changes?.length) && h("p", null, IDENTIFIER_IMPACT),
      view.impact?.content_changed_since_save && h("p", null, "저장 이후 본문 변경 있음"),
      (!view.impact?.available || !!view.impact.unverified_jobs?.length) && h("p", null, "연결된 작업의 영향은 확인하지 않았습니다."),
      !!view.impact?.unverified_jobs?.length && h("p", null, `확인하지 않은 작업 ${view.impact.unverified_jobs.length}개`),
      view.impact?.available && !view.impact.jobs?.length && h("p", null, "연결된 작업 없음"),
      ...(view.impact?.jobs || []).map((job: Obj) => { const blocked = view.impact.save_required || view.impact.usable === false; return h("div", { key: job.name }, h("strong", null, job.name),
        job.change_status && h("p", null, TPL_STATUS_COPY[job.change_status] || job.change_status),
        h("p", null, `추가 필드: ${(job.added_fields || []).join(", ") || "없음"} · 없어진 필드: ${(job.removed_fields || job.unmapped_fields || []).join(", ") || "없음"}`),
        button("적용 영향 확인", act(() => controller.applyJob(job.name)), { "data-guide": "apply-check", disabled: blocked, "aria-disabled": blocked || undefined, title: (blocked && job.blocked_reason) || undefined }),
        blocked && job.blocked_reason && h("p", { className: "authoring-reason" }, job.blocked_reason)); }),
      view.jobApply && h("div", null, h("p", null, TPL_STATUS_COPY[view.jobApply.preparation?.status] || view.jobApply.message),
        ...(view.jobApply.preparation?.diagnostics || []).map((entry: Obj, index: number) => h("p", { key: index }, entry.message)),
        h("div", { className: "authoring-actions" }, quiet("취소", () => controller.update({ jobApply: null })), primary("기존 작업에 적용", act(controller.confirmJob), { "data-guide": "apply-confirm", disabled: !view.jobApply.change_token }))));
    const fix = key === "problems" && view.preview ? problemFix(item.problems, view.command) : null;
    // 문제 한 건(§7.2·F24): 심각도·종류는 색이 아닌 글자로(P14), 대상·설명·다음 행동을 Python 의 problems 그대로 보인다.
    // 문제 한 건은 행이다(UX-09): 심각도 글자 칩 · 종류 · 설명 · 흐린 대상. 이동하는 다음 행동(「원문으로 이동」)은 그 행 자체이고
    // 그 동사가 행 이름의 첫머리·툴팁으로 남는다. 명령형 다음 행동(구조 표기 수정 등)은 행 곁의 보조 단추다.
    if (key === "problems") return h("section", { className: "authoring-bottom", "aria-label": "문제" }, h("h2", null, "문제"),
      !item.problems?.length && h("p", { className: "authoring-reason" }, "문제 없음"),
      rowList("문제", (item.problems || []).map((problem: Obj, index: number) => {
        const actions: Obj[] = problem.actions || [];
        const navigate = actions.find((action) => action.kind !== "command");
        const chip = h("span", { className: "authoring-badge", "data-severity": problem.severity }, SEVERITY_LABEL[problem.severity] || problem.severity);
        const body = [h("span", { key: "category", className: "authoring-problem-category" }, CATEGORY_LABEL[problem.category] || problem.category), " ", problem.message];
        return h("div", { key: index, className: "authoring-problem" },
          // 이름은 다음 행동(동사)이 먼저, 이어서 심각도·종류·대상·설명 — 보이는 행과 같은 글이다.
          navigate ? rowButton({ chip, text: body, context: problem.target || null }, act(() => problemAction(controller, item, problem, navigate)), { title: navigate.label,
            "aria-label": joined(navigate.label, SEVERITY_LABEL[problem.severity] || problem.severity, CATEGORY_LABEL[problem.category] || problem.category, problem.target, problem.message) })
            : h("div", { className: "authoring-row static" }, chip, h("span", { className: "authoring-row-text" }, ...body), problem.target ? h("span", { className: "authoring-row-context" }, problem.target) : null),
          ...actions.filter((action) => action !== navigate).map((action: Obj, actionIndex: number) => button(action.label, act(() => problemAction(controller, item, problem, action)), { key: actionIndex })));
      })),
      // 문제 행의 명령 행동이 낸 미리보기는 이 탭에서 확인·확정한다 — 확정 단추는 그 행동의 이름이다(구조 표기 자동 수정만 기존 이름).
      fix && h("div", { className: "authoring-preview" },
        h("h3", null, "수정 제안"), h("pre", { role: "group", "aria-label": "변경 전" }, view.preview.before), h("pre", { role: "group", "aria-label": "변경 후" }, view.preview.after),
        h("div", { className: "authoring-actions" }, quiet("취소", () => controller.update({ preview: null })), primary(view.command.type === "repair_marker" ? "구조 표기 수정" : fix.label, act(controller.applyPreview)))));
    if (key === "external_changed") return h("section", { className: "authoring-bottom", role: "alert", "aria-label": "외부 파일 변경" }, h("h2", null, "외부 파일 변경"),
      h("div", { className: "authoring-actions start" },
        button("양쪽 내용 확인", act(controller.compareExternal)), ...externalVerbs(false)));
    // 저장 실패(AC24·§9.2): 변경은 그대로 남고, 같은 세 복구 동사에 「다시 저장」이 더해진다 — 이 구획의 주 행동이다.
    if (key === "external") return h("section", { className: "authoring-bottom", role: "alert", "aria-label": "저장 실패" }, h("h2", null, "저장 실패"),
      h("div", { className: "authoring-actions start" },
        button("양쪽 내용 확인", act(controller.compareExternal)), ...externalVerbs(true)));
    // 비교 안에서 결정한다(IDE-01): 경보 구획과 같은 동사·같은 실행 경로가 비교 아래에도 선다. 「비교 닫기」는 물러선 행동이다.
    if (key === "comparison" && view.comparison) return h("section", { className: "authoring-bottom", "aria-label": "외부 파일 내용" }, h("h2", null, "외부 파일 내용"),
      h("div", { className: "authoring-compare" }, ...[["현재 작업", view.comparison.current_content, view.comparison.current_section_entries], ["외부 파일 내용", view.comparison.content, view.comparison.section_entries]].map(([label, content, sectionEntries]) =>
        h("div", { key: label }, h("h3", null, label), item.media === "txt" ? h("pre", null, content) : h(ExternalDocument, { controller, item, content, sectionEntries, title: label })))),
      h("div", { className: "authoring-actions" }, quiet("비교 닫기", () => closePanel({ panel: "" })),
        ...(view.saveFailed ? externalVerbs(true) : item.external_changed ? externalVerbs(false) : [])));
    return null;
  }
