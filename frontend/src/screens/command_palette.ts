/* IDE-02 명령 표면 — 문맥 메뉴와 명령 팔레트가 Python 의 같은 명령 판정(F40·P07)을 표면마다 어떻게 싣는가.
   판정(가능·사유·대안)은 Python 몫이다. 여기서는 그 판정을 **거르고 놓기만** 한다: 자동 표면(문맥 메뉴)은 되는 명령과
   대안만, 명시 표면(팔레트)은 되는 것 먼저 · 안 되는 것은 흐림 + Python 사유 문장 그대로(같은 사유끼리 한 번). */
import { createElement as h, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { listKey } from "./authoring_a11y.ts";

type Obj = Record<string, any>;

/** 명령 무리의 첫 명령 — 무리가 바뀌는 보이는 항목 위에만 구분선이 선다. */
export const COMMAND_GROUP_START = new Set(["rename_field", "rename_slot", "unwrap", "duplicate"]);
/** 파괴 명령 — 위험 모양으로 선다. 「원본 템플릿으로 되돌리기」(#1078)는 채운 값을 모두 지운다. */
export const DESTRUCTIVE = new Set(["delete", "revert_template"]);
export const KEY_HINTS: Obj = { rename_field: "F2", rename_slot: "F2", rename_option: "F2" };
/** 단축키 표기 → aria-keyshortcuts 값. Ctrl 만 Control 로 바꾸고 나머지(F2·Shift+F6…)는 표기 그대로다. */
const ARIA_KEYS: Obj = { "Ctrl+S": "Control+S", "Ctrl+F": "Control+F", "Ctrl+Shift+P": "Control+Shift+P" };
export const ariaKeys = (keys?: string): string | undefined => keys ? ARIA_KEYS[keys] || keys : undefined;

/** 명령 한 건의 판정 — 화면이 Python 의 commands 와 읽기 전용 여부로 짓는다(pending: 판정 전, 사유 없음). */
export type CommandEntry = { type: string; label: string; enabled: boolean; pending: boolean; reason: string | null; alternative: { label: string; command_type: string } | null };

/** 문맥 메뉴(자동 표면)의 한 줄. command 는 pick 에 넘길 명령 종류다. reason 은 편집면 메뉴에 늘 서는 「필드로 만들기」가
 *  불가일 때만 싣는 Python 사유다(결정 C). */
export type MenuLine = { key: string; label: string; command: string; disabled: boolean; groupStart: boolean; danger: boolean; alternative: boolean; reason?: string | null };
/** 편집면(글 자리)에서 연 문맥 메뉴에 판정과 무관하게 늘 서는 명령 — 자동 표면 규칙(불가 숨김)의 유일한 예외다(결정 C).
 *  문서에서 가장 먼저 찾는 명령이 사라졌다 나타나지 않게, 불가이면 흐리게 두고 Python 사유를 설명 줄로 싣는다. */
export const EDITOR_PINNED = "create_field";
/** 문맥 메뉴에 실을 것(P-04). 판정 전(pending)이면 지금처럼 모든 명령을 사유 없이 흐리게 싣는다(workflow: 판정 전 명령은
 *  사유 없이 비활성). 판정이 서면 되는 명령과 불가 명령의 대안만 싣는다. 읽기 전용이거나 실을 것이 없으면 null —
 *  화면은 팔레트를 여는 「명령」 한 줄을 세운다. 구분선은 보이는 항목 사이에서 무리가 바뀔 때만 선다. */
export function menuLines(entries: CommandEntry[], readOnly: boolean, editor = false): MenuLine[] | null {
  if (readOnly) return null;
  let group = 0;
  const groupOf = entries.map((entry) => (COMMAND_GROUP_START.has(entry.type) ? ++group : group));
  const pending = entries.every((entry) => entry.pending);
  const lines: (MenuLine & { group: number })[] = entries.flatMap((entry, index) => {
    const base = { groupStart: false, danger: DESTRUCTIVE.has(entry.type), alternative: false, group: groupOf[index] };
    if (pending || entry.enabled) return [{ ...base, key: entry.type, label: entry.label, command: entry.type, disabled: !entry.enabled }];
    if (editor && entry.type === EDITOR_PINNED) return [{ ...base, key: entry.type, label: entry.label, command: entry.type, disabled: true, reason: entry.reason }];
    if (entry.alternative) return [{ ...base, danger: false, alternative: true, key: `${entry.type}-alternative`, label: entry.alternative.label, command: entry.alternative.command_type, disabled: false }];
    return [];
  });
  if (!lines.length) return null;
  return lines.map(({ group: at, ...line }, index) => ({ ...line, groupStart: index > 0 && lines[index - 1].group !== at }));
}

/** 팔레트 한 항목. run 이 있으면 셸 동작, command 가 있으면 의미 명령(pick)이다. */
export type PaletteOption = { id: string; label: string; enabled: boolean; keys?: string; command?: string; run?: () => void; danger?: boolean; alternative?: boolean };
/** 셸 동작 한 줄(저장·찾기·영역 이동 …) — 이름 · 실행 · 불가 · 단축키 표기. */
export type PaletteAction = { label: string; run: () => void; disabled?: boolean; keys?: string };
/** 팔레트의 세 부분(P-10): 되는 것(의미 명령 → 셸 동작), 사유별 무리(흐린 명령과 곁의 대안), 사유 없는 불가(판정 전·읽기 전용). */
export type PaletteModel = { runnable: PaletteOption[]; blocked: { reason: string; options: PaletteOption[] }[]; silent: PaletteOption[] };

/** 입력이 이름에 들어 있는가 — 대소문자 무시, 앞뒤 공백 무시(초성 검색은 없다). */
const matches = (query: string, label: string) => { const wanted = query.trim().toLocaleLowerCase(); return !wanted || label.toLocaleLowerCase().includes(wanted); };

/** 팔레트에 실을 것. 사유 무리는 이웃이 아니라 **사유 값**으로 묶는다 — 한 사유는 한 번만 선다. 무리 차례는 그 사유를 처음 가진
 *  명령의 차례(Python 차례)다. 되지 않는 셸 동작은 싣지 않는다(사유가 없는 불가는 되는 목록의 소음이다). */
export function paletteModel(entries: CommandEntry[], actions: PaletteAction[], query: string): PaletteModel {
  const runnable: PaletteOption[] = [];
  const groups = new Map<string, PaletteOption[]>();
  const silent: PaletteOption[] = [];
  for (const entry of entries) {
    const own = { label: entry.label, keys: KEY_HINTS[entry.type], command: entry.type, danger: DESTRUCTIVE.has(entry.type) };
    if (entry.enabled) { if (matches(query, entry.label)) runnable.push({ ...own, id: `cmd-${entry.type}`, enabled: true }); continue; }
    const members: PaletteOption[] = [];
    if (matches(query, entry.label)) members.push({ ...own, id: `cmd-${entry.type}`, enabled: false });
    if (entry.alternative && matches(query, entry.alternative.label)) {
      members.push({ id: `alt-${entry.type}`, label: entry.alternative.label, enabled: true, command: entry.alternative.command_type, alternative: true });
    }
    if (!members.length) continue;
    if (!entry.reason) { silent.push(...members); continue; }
    const reason = String(entry.reason);
    groups.set(reason, [...(groups.get(reason) || []), ...members]);
  }
  actions.forEach((action, index) => {
    if (!action.disabled && matches(query, action.label)) runnable.push({ id: `act-${index}`, label: action.label, enabled: true, keys: action.keys, run: action.run });
  });
  return { runnable, blocked: [...groups].map(([reason, options]) => ({ reason, options })), silent };
}
/** 화살표가 도는 차례 — 보이는 차례 그대로다. */
export const paletteOrder = (model: PaletteModel): PaletteOption[] => [...model.runnable, ...model.blocked.flatMap((group) => group.options), ...model.silent];

const NO_MATCH = "일치하는 명령이 없습니다.";
const optionId = (option: PaletteOption) => `authoring-palette-${option.id}`;

/** 명령 팔레트(P-10) — 머리 띠 아래 가운데에 뜨는 비모달 오버레이다. APG combobox(입력) + listbox(aria-activedescendant).
 *  ↑↓ 로 활성 항목을 옮긴다(흐린 항목도 활성이 되어 사유 무리 이름이 읽힌다). Enter 는 되는 활성 항목만 실행하고 닫는다.
 *  Escape 는 닫고 연 자리로 초점을 돌린다 — 셸 Escape(속성 패널 닫기)로 새지 않게 전파를 막는다. 조합 중 키는 무시한다.
 *  초점이 팔레트 밖으로 나가면 닫는다(닿은 곳이 없으면 연 자리로). */
export function CommandPalette({ entries, actions, onPick, onClose }: {
  entries: CommandEntry[]; actions: PaletteAction[];
  onPick: (commandType: string) => void; onClose: (restore: boolean) => void;
}): ReactNode {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const model = paletteModel(entries, actions, query);
  const order = paletteOrder(model);
  const current = order.length ? order[Math.min(active, order.length - 1)] : null;
  useEffect(() => { input.current?.focus(); }, []);
  // 머리 띠 바로 아래에 선다 — 띠 높이는 글자 배율·탭 줄에 따라 달라지므로 그린 뒤 잰다.
  useLayoutEffect(() => {
    const el = box.current;
    const head = el?.parentElement?.querySelector?.(".authoring-head") as HTMLElement | null | undefined;
    if (el && head && typeof head.offsetTop === "number" && typeof head.offsetHeight === "number") el.style.top = `${head.offsetTop + head.offsetHeight + 4}px`;
  }, []);
  useEffect(() => {
    const el = current ? box.current?.querySelector?.(`#${optionId(current)}`) as HTMLElement | null | undefined : null;
    el?.scrollIntoView?.({ block: "nearest" });
  }, [current?.id]);
  const run = (option: PaletteOption | null) => {
    if (!option?.enabled) return;
    onClose(true);
    if (option.run) option.run(); else if (option.command) onPick(option.command);
  };
  const row = (option: PaletteOption) => {
    const selected = option === current;
    return h("div", { key: option.id, id: optionId(option), role: "option", "aria-selected": selected, "aria-disabled": option.enabled ? undefined : true,
      "aria-keyshortcuts": ariaKeys(option.keys),
      className: `authoring-palette-option${selected ? " active" : ""}${option.alternative ? " alternative" : ""}${option.danger ? " danger" : ""}`,
      // 누름이 입력칸의 초점을 빼앗지 않는다 — 활성 항목은 늘 입력칸이 가리킨다.
      onMouseDown: (event: any) => event.preventDefault(),
      onClick: () => run(option) },
      h("span", { className: "authoring-palette-label" }, option.label),
      option.keys ? h("kbd", { className: "authoring-key", "aria-hidden": true }, option.keys) : null);
  };
  return h("div", { ref: box, className: "authoring-command-palette", role: "dialog", "aria-label": "명령 팔레트",
    onKeyDown: (event: any) => {
      if (event.nativeEvent?.isComposing || event.keyCode === 229) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(true); return; }
      const next = listKey(event.key, order.indexOf(current as PaletteOption), order.length);
      if (next !== null) { event.preventDefault(); setActive(next); return; }
      if (event.key === "Enter") { event.preventDefault(); run(current); }
    },
    onBlur: () => {
      // 초점이 실제로 옮겨 간 뒤에 판정한다 — 편집면 iframe 으로 간 초점도 문서의 activeElement 로 보인다.
      setTimeout(() => {
        const el = box.current;
        const doc = el?.ownerDocument;
        if (!el?.isConnected || !doc) return;
        const now = doc.activeElement;
        if (now && el.contains(now)) return;
        onClose(!now || now === doc.body);
      }, 0);
    } },
    h("input", { ref: input, className: "field", type: "text", role: "combobox", "aria-label": "명령", autoComplete: "off", spellCheck: false,
      "aria-autocomplete": "list", "aria-expanded": order.length > 0, "aria-controls": order.length ? "authoring-palette-list" : undefined,
      "aria-activedescendant": current ? optionId(current) : undefined, value: query,
      onChange: (event: any) => { setQuery(event.target.value); setActive(0); } }),
    order.length
      ? h("div", { id: "authoring-palette-list", className: "authoring-palette-list", role: "listbox", "aria-label": "명령" },
        ...model.runnable.map(row),
        // 사유는 무리의 이름이다(role=group · aria-label) — 보이는 머리 줄은 읽기 도구에 되풀이하지 않는다.
        ...model.blocked.map((group) => h("div", { key: group.reason, role: "group", "aria-label": group.reason, className: "authoring-palette-group" },
          h("div", { className: "authoring-palette-reason", "aria-hidden": true }, group.reason), ...group.options.map(row))),
        ...model.silent.map(row))
      : h("p", { className: "authoring-reason authoring-palette-empty" }, NO_MATCH));
}
