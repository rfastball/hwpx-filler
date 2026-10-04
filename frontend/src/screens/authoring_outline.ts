import { createElement as h, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AUTHORING_COPY } from "./authoring_controller.ts";
import { sectionLabel } from "./authoring_primitives.ts";
import type { Obj, Props } from "./authoring_primitives.ts";
import { KIND_LABEL, SEVERITY_LABEL, COVERAGE_LABEL, sameFieldMeta, outlineSpine, groupedPath, fieldsInFirstUse,
  outlineKey, outlineCurrent, filterMatch, outlineLabel } from "./authoring_outline_model.ts";
import type { SpineNode } from "./authoring_outline_model.ts";
import { icon, coverageDot, kindGlyph } from "./icons.ts";
import { treeKey, roveFocus } from "./authoring_a11y.ts";
import type { TreeRow } from "./authoring_a11y.ts";
import { shellShortcut } from "./authoring_editor.ts";

type TreeNode = { key: string; label: string; content: ReactNode[]; entry: Obj; kind?: string; highlight?: Obj; open?: boolean; children?: () => TreeNode[] };
type TreeHandlers = { onSelect(entry: Obj, element: HTMLElement): void; onMenu(entry: Obj, element: HTMLElement, anchor: { x: number; y: number; top?: number }): void };

/** 구조 목록(§3.3·§10)은 APG treeview 다: 한 번의 Tab 으로 들어오고(roving tabindex), ↑↓ 이동·→ 펼침/첫 자식·
 *  ← 접힘/부모·Home·End, Enter·Space 로 고른다. 지금 위치(current — 바깥에서 안쪽으로의 열쇠 경로)는 **보이는 가장 안쪽**
 *  줄 하나에 aria-current 와 색이 아닌 표지(왼쪽 막대·굵기)로 서고, 바뀌면 그 줄이 보이도록 목록을 옮긴다.
 *  이름은 outlineLabel 그대로다. 펼침 상태는 이 목록의 수명(문서 탭 하나)만큼 남는다. */
function OutlineTree({ labelledBy, nodes, current, inactive, onSelect, onMenu, onHighlight }: TreeHandlers & { labelledBy: string; nodes: TreeNode[]; current: string[]; inactive?: boolean; onHighlight(target: Obj | null): void }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [focusKey, setFocusKey] = useState("");
  const elements = useRef(new Map<string, HTMLElement>());
  // 보이는 줄의 평탄한 차례 — 키보드 이동의 기준. 펼친 줄의 자식만 여기서 짓는다.
  const rows: (TreeRow & { node: TreeNode })[] = [];
  const kids = new Map<string, TreeNode[]>();
  const walk = (list: TreeNode[], parent: string | null) => {
    for (const node of list) {
      const expandable = !!node.children;
      const open = expandable && (expanded[node.key] ?? !!node.open);
      rows.push({ key: node.key, parent, expandable, expanded: open, node });
      if (open) { const children = node.children!(); kids.set(node.key, children); walk(children, node.key); }
    }
  };
  walk(nodes, null);
  const byKey = new Map(rows.map((row) => [row.key, row]));
  const currentKey = [...current].reverse().find((key) => byKey.has(key));
  const active = byKey.has(focusKey) ? focusKey : currentKey ?? rows[0]?.key;
  // 지금 위치가 연속 묶음 안이면 그 묶음을 펼친다(접어 둔 묶음도 — 가리킨 줄이 보여야 한다). 항목·선택의 접힘은 그대로 둔다.
  const path = current.join("\u0000");
  useEffect(() => {
    const groups = current.slice(0, -1).filter((key) => key.startsWith("group:") && !expanded[key]);
    if (groups.length) setExpanded((state) => ({ ...state, ...Object.fromEntries(groups.map((key) => [key, true])) }));
  }, [path]);
  // 현재 위치 따라가기(F15): 캐럿이 옮긴 줄이 목록 밖이면 가장 가까운 쪽으로 스크롤한다(초점은 옮기지 않는다).
  useEffect(() => { if (currentKey) elements.current.get(currentKey)?.scrollIntoView?.({ block: "nearest" }); }, [currentKey]);
  const toggle = (key: string, open: boolean) => setExpanded((state) => ({ ...state, [key]: open }));
  const own = (event: any) => event.target?.closest?.('[role="treeitem"]') === event.currentTarget;
  const render = (node: TreeNode): ReactNode => {
    const row = byKey.get(node.key)!;
    // 숨은 보기(다른 탭)의 tree 는 Tab·F6 의 입구를 두지 않는다(inactive).
    return h("li", { key: node.key, role: "treeitem", "data-tree-key": node.key, "data-kind": node.kind, tabIndex: !inactive && node.key === active ? 0 : -1, "aria-label": node.label,
      "aria-expanded": row.expandable ? row.expanded : undefined, "aria-current": node.key === currentKey ? "true" : undefined,
      ref: (element: HTMLElement | null) => { if (element) elements.current.set(node.key, element); else elements.current.delete(node.key); },
      onClick: (event: any) => { if (own(event)) onSelect(node.entry, event.currentTarget); },
      onContextMenu: (event: any) => { if (!own(event)) return; event.preventDefault(); event.stopPropagation(); onMenu(node.entry, event.currentTarget, { x: event.clientX, y: event.clientY }); } },
      h("span", { className: "authoring-tree-row", onMouseEnter: () => onHighlight(node.highlight || null) },
        // 펼침 표지는 마우스용이다(키보드는 →·←). 글자가 아니라 CSS 가 그린다.
        h("span", { className: "authoring-tree-toggle", "aria-hidden": true, "data-leaf": row.expandable ? undefined : "",
          onClick: row.expandable ? (event: any) => { event.stopPropagation(); toggle(node.key, !row.expanded); } : undefined }),
        ...node.content),
      row.expanded && h("ul", { role: "group" }, ...(kids.get(node.key) || []).map(render)));
  };
  return h("ul", { className: "authoring-tree", role: "tree", "aria-labelledby": labelledBy,
    onMouseLeave: () => onHighlight(null),
    onBlur: (event: any) => { if (!event.currentTarget?.contains?.(event.relatedTarget)) onHighlight(null); },
    onFocus: (event: any) => {
      const key = event.target?.getAttribute?.("data-tree-key");
      if (!key) return;
      if (key !== focusKey) setFocusKey(key);
      // 키보드로 옮긴 줄도 편집면에서 강조한다 — 마우스와 같은 길(§10).
      onHighlight(byKey.get(key)?.node.highlight || null);
    },
    onKeyDown: (event: any) => {
      const element = event.target?.closest?.('[role="treeitem"]') as HTMLElement | null;
      const key = element?.getAttribute("data-tree-key");
      const row = key ? byKey.get(key) : undefined;
      if (!element || !row || event.nativeEvent?.isComposing) return;
      // Shift+F10·메뉴 키는 이 줄을 고른 뒤 그 줄 아래에 문맥 메뉴를 연다(§6.1) — 셸의 일반 경로로 가지 않는다.
      if (shellShortcut(event) === "context-menu") {
        event.preventDefault(); event.stopPropagation();
        const rect = (element.querySelector(".authoring-tree-row") || element).getBoundingClientRect();
        onMenu(row.node.entry, element, { x: rect.left, y: rect.bottom, top: rect.top });
        return;
      }
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const action = treeKey(event.key, rows, row.key);
      if (!action) return;
      event.preventDefault();
      if (action.expand) toggle(action.expand, true);
      if (action.collapse) toggle(action.collapse, false);
      if (action.focus) { setFocusKey(action.focus); elements.current.get(action.focus)?.focus(); }
      if (action.select) onSelect(row.node.entry, element);
    } }, ...nodes.map(render));
}

/** 브레드크럼 차례(UX-09): 바깥에서 안쪽으로 — 항목 › 선택 › 필드. Python 이 준 일치 후보를 종류 차례로만 세운다. */
export function crumbs(matches: Obj[] | undefined): Obj[] {
  const rank: Obj = { slot: 0, option: 1, field: 2 };
  return [...(matches || [])].map((match, at) => ({ match, at })).sort((a, b) => (rank[a.match.kind] ?? 3) - (rank[b.match.kind] ?? 3) || a.at - b.at).map((entry) => entry.match);
}
/** 문자 몇 개를 「 · 」 로 잇는다 — 빈 것은 뺀다. */
export const joined = (...parts: unknown[]) => parts.filter((part) => part !== null && part !== undefined && part !== false && part !== "" && part !== 0).join(" · ");
/** 대상별 가장 무거운 심각도(오류 > 경고) — 문제 줄의 글리프 자리에 글자 칩으로 선다(§10: 색이 아니라 글자). */
export function problemSeverities(problems: Obj[] | undefined): Map<string, string> {
  const severities = new Map<string, string>();
  for (const problem of problems || []) if (problem.target != null && severities.get(problem.target) !== "error") severities.set(problem.target, problem.severity);
  return severities;
}
type RowParts = { severity?: string; tag?: boolean; dot?: ReactNode; meta?: string };
/** 트리 한 줄의 보이는 내용: [글리프 또는 심각도 칩] [종류 표지] [시험 점] [이름 — 한 줄 말줄임, 전체는 title] … [흐린 메타]. */
function rowContent(kind: "slot" | "option" | "field", name: string, parts: RowParts): ReactNode[] {
  return [
    h("span", { key: "glyph", className: "authoring-tree-glyph" }, parts.severity
      ? h("span", { className: "authoring-badge", "data-severity": parts.severity }, SEVERITY_LABEL[parts.severity] || parts.severity) : kindGlyph(kind)),
    parts.tag === false ? null : h("span", { key: "kind", className: "authoring-kind" }, KIND_LABEL[kind]),
    parts.dot || null,
    h("span", { key: "name", className: "authoring-tree-name", title: name }, name),
    parts.meta ? h("span", { key: "meta", className: "authoring-tree-meta" }, parts.meta) : null,
  ];
}
const EMPTY_FIELDS = "필드가 없습니다. 문구를 고르고 「필드로 만들기」를 누르세요.";

/** 왼쪽 템플릿 구조(§3.1 UI03·UI04·§3.3 · UX-09): 한 패널의 두 보기.
 *  - 구조: 문서 순서의 척추 — 항목(실선 안내선) 아래 선택(점선 안내선), 필드 사용 위치는 그것을 담은 자리에 잎으로 선다.
 *    선택 앞의 점은 시험 상태(채움 모양), 여러 자리에 선 필드는 「같은 필드, i/n」.
 *  - 필드: 이름별 묶음(처음 쓰인 순서) — 펼치면 사용 위치(문맥과 소속). 사용 위치 줄은 펼친 뒤에만 짓는다(UX-05).
 *  필터는 두 보기 모두에서 일치하는 줄과 그 조상을 남긴다. 줄에 마우스·초점이 머물면 편집면이 그 범위를 강조한다. */
export function Outline({ controller, item, view, counts, onSelect, onMenu, onContext }: Props & TreeHandlers & { item: Obj; view: Obj; counts: Map<string, number>; onContext(event: any): void }) {
  const [tab, setTab] = useState<"structure" | "fields">("structure");
  const [query, setQuery] = useState("");
  const analysis: Obj = item.analysis || {};
  const version = analysis.revision ?? analysis;
  const spine = useMemo(() => outlineSpine(analysis), [version]);
  const fields = useMemo(() => fieldsInFirstUse(analysis), [version]);
  const severities = useMemo(() => problemSeverities(item.problems), [item.problems]);
  const located = outlineCurrent(analysis, view.selected, view.matches);
  // 묶음 안 사용 위치가 지금 위치면 묶음이 그 경로의 조상이다 — 트리가 그 묶음을 펼쳐 줄을 보인다.
  const current = { ...located, structure: groupedPath(spine, located.structure) };
  const coverage = new Map<string, string>((item.trial_coverage || []).map((entry: Obj) => [`${entry.slot_id}\u0000${entry.option_id}`, entry.state]));
  // 강조 요청은 줄을 훑는 동안 마지막 것만 보낸다 — 문서 장식을 줄마다 다시 그리지 않는다.
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const highlight = (target: Obj | null) => {
    if (pending.current) clearTimeout(pending.current);
    pending.current = setTimeout(() => { pending.current = null; controller.highlight(target); }, 60);
  };
  useEffect(() => () => { if (pending.current) clearTimeout(pending.current); }, [item.id]);
  const filtering = !!query.trim();
  const problemsOf = (target: string) => counts.get(target) || 0;

  const spineNodes = (list: SpineNode[], matched: boolean): TreeNode[] => list.flatMap((node): TreeNode[] => {
    if (node.kind === "group") {
      // 연속 묶음: 기본은 접혀 있고 사용 위치 수와 그 필드들의 문제 수를 모아 보인다. 필터 중에는 일치한 줄만 펼쳐 둔다.
      const found = filtering ? spineNodes(node.children, matched) : null;
      if (found && !found.length) return [];
      const names = [...new Set(node.children.map((use) => String(use.field.name)))];
      const problems = names.reduce((sum, name) => sum + problemsOf(name), 0);
      const severity = names.map((name) => severities.get(name)).find((level) => level === "error")
        ?? names.map((name) => severities.get(name)).find(Boolean);
      const meta = joined(`사용 위치 ${node.children.length}곳`, problems && `문제 ${problems}`);
      const first = node.children[0];
      return [{ key: node.key, kind: "group", label: joined(AUTHORING_COPY.looseUses, meta),
        content: rowContent("field", AUTHORING_COPY.looseUses, { severity, tag: false, meta }),
        // 한 필드만 든 묶음에 머물면 그 필드의 사용 위치를 모두 칠한다 — 여러 필드면 칠할 한 대상이 없다.
        entry: { ...first.occurrence, name: first.field.name, kind: "field" }, open: !!found,
        ...(names.length === 1 ? { highlight: { kind: "field", id: names[0] } } : {}),
        children: () => found ?? spineNodes(node.children, true) }];
    }
    if (node.kind === "use") {
      const { field, occurrence, index, total } = node;
      if (!matched && !filterMatch(query, field.name, occurrence.context)) return [];
      const problems = problemsOf(field.name);
      return [{ key: outlineKey.use(field.name, index), kind: "use", label: joined(KIND_LABEL.field, field.name, sameFieldMeta(index, total), problems && `문제 ${problems}`),
        content: rowContent("field", field.name, { severity: severities.get(field.name), meta: joined(sameFieldMeta(index, total), problems && `문제 ${problems}`) }),
        entry: { ...occurrence, name: field.name, kind: "field" }, highlight: { kind: "field", id: field.name, index } }];
    }
    const own = node.kind === "slot" ? node.slot : node.option;
    const name = String(own.label || own.id);
    const self = matched || filterMatch(query, own.label, own.id);
    const children = filtering ? spineNodes(node.children, self) : null;
    if (filtering && !self && !children!.length) return [];
    const problems = problemsOf(own.id);
    const build = () => children ?? spineNodes(node.children, true);
    const expandable = filtering ? !!children!.length : node.children.length > 0;
    if (node.kind === "slot") {
      const slot = node.slot;
      return [{ key: outlineKey.slot(slot.id), kind: "slot", label: joined(outlineLabel("slot", slot), slot.location_label, problems && `문제 ${problems}`),
        content: rowContent("slot", name, { severity: severities.get(slot.id), meta: joined(slot.location_label, problems && `문제 ${problems}`) }),
        entry: { ...slot, ...slot.location, kind: "slot", slot_id: slot.id }, highlight: { kind: "slot", id: slot.id }, open: true,
        children: expandable ? build : undefined }];
    }
    const { slot, option } = node;
    const state = coverage.get(`${slot.id}\u0000${option.id}`);
    const dot = state ? h("span", { key: "dot", className: "authoring-coverage-dot", "data-state": state, title: COVERAGE_LABEL[state] }, coverageDot(state)) : null;
    return [{ key: outlineKey.option(slot.id, option.id), kind: "option",
      label: joined(outlineLabel("option", option, 0, slot.label || slot.id), option.location_label, state && COVERAGE_LABEL[state], problems && `문제 ${problems}`),
      content: rowContent("option", name, { severity: severities.get(option.id), dot, meta: joined(option.location_label, problems && `문제 ${problems}`) }),
      entry: { ...option, ...option.location, kind: "option", slot_id: slot.id, option_id: option.id }, highlight: { kind: "option", id: option.id, slot_id: slot.id }, open: true,
      children: expandable ? build : undefined }];
  });

  const slotName = (id: string) => { const slot = (analysis.slots || []).find((entry: Obj) => entry.id === id); return slot ? String(slot.label || slot.id) : ""; };
  const optionName = (slotId: string, id: string) => { const option = (analysis.slots || []).find((entry: Obj) => entry.id === slotId)?.options?.find((entry: Obj) => entry.id === id); return option ? String(option.label || option.id) : ""; };
  const occurrenceNode = (field: Obj, occurrence: Obj, at: number, total: number): TreeNode => {
    const slot = occurrence.slot_id ? slotName(occurrence.slot_id) : "";
    const option = occurrence.slot_id && occurrence.option_id ? optionName(occurrence.slot_id, occurrence.option_id) : "";
    const place = [slot, option].filter(Boolean).join(" / ");
    return { key: outlineKey.occurrence(field.name, at + 1), kind: "occurrence",
      label: joined(outlineLabel("occurrence", { name: field.name, index: at + 1, total, context: occurrence.context }), slot && `${KIND_LABEL.slot} ${slot}`, option && `${KIND_LABEL.option} ${option}`),
      content: [h("span", { key: "name", className: "authoring-tree-name", title: occurrence.context || field.name }, `${at + 1}. ${occurrence.context || field.name}`),
        place ? h("span", { key: "meta", className: "authoring-tree-meta", title: place }, place) : null],
      entry: { ...occurrence, name: field.name, kind: "field" }, highlight: { kind: "field", id: field.name, index: at + 1 } };
  };
  const fieldNodes = fields.flatMap((field: Obj): TreeNode[] => {
    const occurrences: Obj[] = field.occurrences || [];
    const byName = filterMatch(query, field.name);
    const hits = filtering && !byName ? occurrences.map((occurrence, at) => ({ occurrence, at })).filter(({ occurrence }) => filterMatch(query, occurrence.context)) : null;
    if (hits && !hits.length) return [];
    const problems = problemsOf(field.name);
    return [{ key: outlineKey.field(field.name), kind: "field", label: outlineLabel("field", field, problems),
      // 수는 글로 선다(§10): 「사용 위치 n곳」 — 이름(outlineLabel)과 같은 표현이다.
      content: rowContent("field", field.name, { severity: severities.get(field.name), tag: false, meta: joined(`사용 위치 ${field.count ?? 0}곳`, problems && `문제 ${problems}`) }),
      entry: { ...field, kind: "field" }, highlight: { kind: "field", id: field.name }, open: !!hits,
      children: occurrences.length ? () => (hits || occurrences.map((occurrence, at) => ({ occurrence, at }))).map(({ occurrence, at }) => occurrenceNode(field, occurrence, at, occurrences.length)) : undefined }];
  });
  const structureNodes = spineNodes(spine, !filtering);

  const tabButton = (key: "structure" | "fields", id: string, label: ReactNode[]) => h("button", { key, type: "button", role: "tab", id, className: "authoring-outline-tab",
    tabIndex: tab === key ? 0 : -1, "aria-selected": tab === key, "aria-controls": `${id}-panel`, "data-outline-view": key,
    onClick: () => setTab(key), onFocus: () => setTab(key) }, ...label);
  const tree = (key: "structure" | "fields", labelledBy: string, nodes: TreeNode[], path: string[]) => nodes.length > 0 && h(OutlineTree, { key: `${item.id}:${key}:${filtering ? "filter" : "all"}`,
    labelledBy, nodes, current: path, inactive: tab !== key, onSelect, onMenu, onHighlight: highlight });
  return h("aside", { className: "authoring-outline", "aria-label": "템플릿 구조", onContextMenu: onContext },
    h("div", { className: "authoring-outline-head" },
      sectionLabel("템플릿 구조", { id: "authoring-outline-title" }),
      // 두 보기는 한 쌍의 APG tabs 다(자동 활성화 — ←→ 로 옮기면 그 보기가 선다). 화살표가 옮긴 탭은 키 처리 안에서 고른다 —
      // focus 사건은 창이 OS 초점을 쥘 때만 오므로(배경 창이면 activeElement 만 옮는다) 활성화를 그 사건에 맡기지 않는다.
      h("div", { className: "authoring-outline-tabs", role: "tablist", "aria-labelledby": "authoring-outline-title",
        onKeyDown: (event: any) => {
          if (!roveFocus(event, event.currentTarget, '[role="tab"]', "horizontal")) return;
          const moved = event.currentTarget.ownerDocument?.activeElement?.getAttribute?.("data-outline-view");
          if (moved === "structure" || moved === "fields") setTab(moved);
        } },
        tabButton("structure", "authoring-outline-structure", ["구조"]),
        tabButton("fields", "authoring-outline-fields", ["필드", " ", h("span", { key: "count", className: "authoring-tab-count" }, String(fields.length))])),
      h("label", { className: "authoring-filter" }, icon("search"),
        h("input", { className: "field", type: "search", "aria-label": "구조 필터", value: query, onChange: (event: any) => setQuery(event.target.value),
          onKeyDown: (event: any) => { if (event.key === "Escape" && query && !event.nativeEvent?.isComposing) { event.preventDefault(); event.stopPropagation(); setQuery(""); } } }))),
    h("div", { className: "authoring-outline-panel", role: "tabpanel", id: "authoring-outline-structure-panel", "aria-labelledby": "authoring-outline-structure", hidden: tab !== "structure" },
      tree("structure", "authoring-outline-structure", structureNodes, current.structure),
      // 빈 상태 안내(NG-01)는 첫 행동인 필드 만들기 하나다: 필드도 항목도 없을 때만 선다. 필드가 있고 항목이 없으면 문장을 두지 않는다
      // (선택 기능이 없다는 사실은 알릴 일이 아니다 — 상시 힌트 기본 0). 필드·항목 유무는 Python 투영(analysis)을 읽기만 한다.
      !filtering && !(analysis.slots || []).length && !fields.length && h("p", { className: "authoring-outline-empty" }, EMPTY_FIELDS)),
    h("div", { className: "authoring-outline-panel", role: "tabpanel", id: "authoring-outline-fields-panel", "aria-labelledby": "authoring-outline-fields", hidden: tab !== "fields" },
      tree("fields", "authoring-outline-fields", fieldNodes, current.fields),
      !filtering && !fields.length && h("p", { className: "authoring-outline-empty" }, EMPTY_FIELDS)));
}
