/* 「데이터로 필드 찾기」(#1156)의 React 표면 — 띠(도구 막대 아래), 구조 패널의 제안·보류 묶음, 제안 팝오버, 빈 필드
 * 목록의 입구 링크. 모양은 `authoring_proposal.ts` 의 순수 투영이 정하고 여기서는 그리기·초점·자리만 맡는다. */
import { Fragment, createElement as h, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { clampMenu, roveFocus } from "./authoring_a11y.ts";
import { selectionBarPlace } from "./authoring_commands.ts";
import { button, iconButton, primary, quiet } from "./authoring_primitives.ts";
import type { Obj, Props } from "./authoring_primitives.ts";
import { PROPOSAL_COPY, bandView, missingLines, outlineGroups, popoverView, proposalCounts, proposalOf } from "./authoring_proposal.ts";
import type { ProposalOpen } from "./authoring_proposal.ts";
import { icon } from "./icons.ts";

type Surface = Props & { item: Obj | undefined; view: Obj };
type Rect = { left: number; top: number; bottom: number };
/** 패널 줄·자리와 팝오버 사이(px). */
export const PROPOSAL_GAP = 8;

const run = (controller: Props["controller"], work: () => unknown) => () => { void controller.guarded(work); };
/** HWPX 원문을 고칠 수 없는 탭(호환성 판정 전·실패) — 만들기 입구가 서지 않는다. */
export const proposalReadOnly = (item: Obj | undefined) => !item || (item.media === "hwpx" && item.rhwp_editable !== true);

/** 띠의 상태 자리 — 준비면 「제안 N · 보류 N」(수만 굵게), 아니면 Python 문장·안내 문구 그대로. */
function bandStatus(band: ReturnType<typeof bandView>, proposal: Obj): ReactNode {
  if (band.state !== "ready") return h("span", { className: "authoring-proposal-status", ...(band.failed ? { role: "alert", "data-severity": "error" } : {}) }, band.message);
  const counts = proposalCounts(proposal);
  return h("span", { className: "authoring-proposal-status" }, `${PROPOSAL_COPY.proposals} `, h("b", null, String(counts.proposal)),
    ` · ${PROPOSAL_COPY.held} `, h("b", null, String(counts.held)));
}

/** 띠가 단일 live region 으로 읽을 전이 — 준비면 수, 데이터가 없으면 다음 행동. 실패는 경보 칸(role=alert)이 읽는다. */
const spokenOf = (band: ReturnType<typeof bandView> | null) => band?.state === "ready" || band?.state === "needs_data" ? band.message : "";

/** 데이터·행 고르기 — 데이터는 Python 이 준 등록 데이터 목록, 행은 Python 이 고른 행과 상위 행이며 고른 행의 힌트가 곁에 선다. */
function bandPickers(controller: Props["controller"], band: ReturnType<typeof bandView>): ReactNode[] {
  const busy = band.state === "working";
  return [
    band.datasets.length > 0 && h(Fragment, { key: "data" },
      h("label", { htmlFor: "authoring-proposal-data" }, PROPOSAL_COPY.data),
      h("select", { id: "authoring-proposal-data", className: "field authoring-proposal-select", value: band.dataKey, disabled: busy,
        onChange: (event: any) => run(controller, () => controller.proposal.chooseData(String(event.target.value)))() },
        band.dataKey ? null : h("option", { value: "" }, ""),
        ...band.datasets.map((entry) => h("option", { key: String(entry.key), value: String(entry.key) }, String(entry.name ?? entry.key))))),
    band.rows.length > 0 && h(Fragment, { key: "row" },
      h("label", { htmlFor: "authoring-proposal-row" }, PROPOSAL_COPY.row),
      h("select", { id: "authoring-proposal-row", className: "field authoring-proposal-select", value: band.row, disabled: busy,
        onChange: (event: any) => run(controller, () => controller.proposal.chooseRow(Number(event.target.value)))() },
        ...band.rows.map((row) => h("option", { key: String(row.index), value: String(row.index) }, String(row.label ?? row.index)))),
      band.hint && h("span", { className: "authoring-proposal-hint" }, band.hint)),
  ];
}

/** 띠(도구 막대 아래, 이름 붙은 구획): 데이터·행 고르기, 수, 「제안 N개 모두 필드로」, 끄기. 수가 바뀌면 단일 live region 이 한 번 읽는다. */
export function ProposalBand({ controller, item, view }: Surface): ReactNode {
  const proposal = proposalOf(item);
  const band = proposal ? bandView(proposal, !!view.proposalBusy) : null;
  const root = useRef<HTMLElement>(null);
  const spoken = useRef("");
  const say = spokenOf(band);
  useEffect(() => { if (say && say !== spoken.current) controller.announce(say); spoken.current = say; }, [say]);
  if (!band || !proposal) return null;
  // 끄면 띠가 사라진다 — 초점은 도구 막대의 대기 항목으로 간다.
  const off = run(controller, async () => {
    const toolbar = root.current?.closest(".authoring-shell")?.querySelector<HTMLElement>('.authoring-toolbar [data-rove][tabindex="0"]');
    await controller.proposal.off();
    toolbar?.focus();
  });
  return h("section", { ref: root, className: "authoring-proposal-band", role: "region", "aria-labelledby": "authoring-proposal-title", "aria-busy": band.state === "working" || undefined },
    h("span", { className: "authoring-proposal-title", id: "authoring-proposal-title" }, icon("find"), PROPOSAL_COPY.title),
    ...bandPickers(controller, band),
    bandStatus(band, proposal),
    band.primary && primary(band.primary.label, run(controller, () => controller.proposal.makeAll()), { disabled: band.primary.disabled }),
    h("span", { className: "authoring-proposal-sep", "aria-hidden": true }),
    iconButton("close", PROPOSAL_COPY.off, off));
}

/** 구조 패널의 제안·보류 묶음(띠가 켜진 동안 필드 목록 위). 줄은 한 번의 Tab 으로 들어와 ↑↓ 로 옮기고(roving),
 *  누르면 그 자리로 편집면을 옮기며 팝오버를 연다. 팝오버가 선 줄은 눌린 상태다. */
export function ProposalOutline({ controller, item, view }: Surface): ReactNode {
  const proposal = proposalOf(item);
  const list = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState("");
  const at = useRef(0);
  // 패널 줄에서 연 팝오버의 행동 뒤 — 같은 차례의 줄(없으면 마지막 줄)로 초점이 돌아온다.
  useEffect(() => {
    const rows = [...(list.current?.querySelectorAll<HTMLElement>("button[data-proposal-row]") || [])];
    if (view.proposalFocus) rows[Math.min(at.current, rows.length - 1)]?.focus();
  }, [view.proposalFocus]);
  if (proposal?.state !== "ready") return null;
  const groups = outlineGroups(proposal);
  const all = [...groups.proposals, ...groups.held];
  const open: ProposalOpen | null = view.proposalOpen || null;
  const current = all.some((entry) => entry.id === active) ? active : all[0]?.id;
  const row = (entry: Obj) => h("button", { key: entry.id, type: "button", className: "authoring-proposal-row", "data-proposal-row": entry.id,
    tabIndex: entry.id === current ? 0 : -1, "aria-label": entry.label, "aria-pressed": open?.group === entry.id,
    "aria-haspopup": "dialog", "aria-expanded": open?.group === entry.id, onFocus: () => setActive(entry.id),
    onClick: (event: any) => { at.current = all.indexOf(entry); run(controller, () => controller.proposal.openRow(entry.id, event.currentTarget))(); } },
    h("span", { className: `authoring-proposal-swatch${entry.held ? " held" : ""}`, "aria-hidden": true }),
    h("span", { className: "authoring-proposal-name", title: entry.name }, entry.name),
    entry.count ? h("span", { className: "authoring-proposal-count" }, entry.count) : null);
  const head = (id: string, label: string, count: number) => h("div", { className: "authoring-proposal-group", id }, h("span", null, label), h("span", null, String(count)));
  return h("div", { ref: list, className: "authoring-proposal-list", onKeyDown: (event: any) => { roveFocus(event, event.currentTarget, "button[data-proposal-row]", "vertical"); } },
    head("authoring-proposal-group-proposal", PROPOSAL_COPY.proposals, groups.proposals.length),
    groups.proposals.length
      ? h("div", { role: "group", "aria-labelledby": "authoring-proposal-group-proposal" }, ...groups.proposals.map(row))
      : h("p", { className: "authoring-outline-empty" }, PROPOSAL_COPY.emptyProposals),
    groups.held.length > 0 && head("authoring-proposal-group-held", PROPOSAL_COPY.held, groups.held.length),
    groups.held.length > 0 && h("div", { role: "group", "aria-labelledby": "authoring-proposal-group-held" }, ...groups.held.map(row)),
    ...missingLines(proposal).map((line, index) => h("p", { key: `missing-${index}`, className: "authoring-proposal-missing" }, line.columns, h("br"), line.reason)));
}

/** 빈 필드 목록 안내(NG-01) — 띠가 꺼져 있고 원문을 고칠 수 있으면 그 아래에 「데이터로 한 번에 찾기」 링크가 하나 선다. */
export function EmptyFields({ controller, item, text }: Props & { item: Obj; text: string }): ReactNode {
  return h(Fragment, null, h("p", { className: "authoring-outline-empty" }, text),
    !proposalOf(item) && !proposalReadOnly(item) && h("p", { className: "authoring-outline-empty" },
      h("button", { type: "button", className: "authoring-proposal-link", onClick: run(controller, () => controller.proposal.find()) }, PROPOSAL_COPY.link)));
}

/** 팝오버의 기준 자리(호스트 창 좌표) — 패널 줄이면 그 줄(오른쪽에 선다), TXT 면 그 자리 표식, HWPX 면 캐럿 줄. */
function anchorOf(controller: Props["controller"], open: ProposalOpen, box: HTMLElement): { rect: Rect; side: "below" | "right" } | null {
  const element = open.origin === "row" ? controller.proposal.opener() as HTMLElement | null
    : box.ownerDocument.querySelector<HTMLElement>(`.authoring-document:not([hidden]) [data-token=${JSON.stringify(`proposal:${open.spot}`)}]`);
  const rect = element?.isConnected && typeof element.getBoundingClientRect === "function" ? element.getBoundingClientRect() : null;
  if (rect) return { rect: { left: open.origin === "row" ? rect.right : rect.left, top: rect.top, bottom: rect.bottom }, side: open.origin === "row" ? "right" : "below" };
  return open.rect ? { rect: open.rect as Rect, side: "below" } : null;
}

/** 팝오버의 창 좌표 — 문서 자리면 그 줄 아래(모자라면 위, 선택 옆 막대와 같은 규칙), 패널 줄이면 그 줄 오른쪽. */
export function proposalPlace(anchor: { rect: Rect; side: "below" | "right" }, size: { width: number; height: number },
  viewport: { width: number; height: number }): { left: number; top: number } {
  return anchor.side === "below" ? selectionBarPlace(anchor.rect, size, viewport)
    : clampMenu({ x: anchor.rect.left + PROPOSAL_GAP, y: anchor.rect.top }, size, viewport);
}

/** 그린 팝오버를 기준 자리 곁에 놓는다 — 셸 층(position:absolute)이라 셸 좌표로 옮긴다. 기준을 모르면 편집면 왼쪽 위다. */
function placeBox(controller: Props["controller"], open: ProposalOpen, box: HTMLElement) {
  const shell = box.closest<HTMLElement>(".authoring-shell");
  const win = box.ownerDocument.defaultView;
  if (!shell || !win?.innerWidth) return;
  const canvas = shell.querySelector<HTMLElement>(".authoring-canvas")?.getBoundingClientRect();
  const anchor = anchorOf(controller, open, box) ?? (canvas ? { rect: { left: canvas.left + PROPOSAL_GAP, top: canvas.top, bottom: canvas.top }, side: "below" as const } : null);
  if (!anchor) return;
  const size = box.getBoundingClientRect();
  const place = proposalPlace(anchor, { width: size.width, height: size.height }, { width: win.innerWidth, height: win.innerHeight });
  const base = shell.getBoundingClientRect();
  box.style.left = `${place.left - base.left - (shell.clientLeft || 0) + (shell.scrollLeft || 0)}px`;
  box.style.top = `${place.top - base.top - (shell.clientTop || 0) + (shell.scrollTop || 0)}px`;
}

type PopoverModel = NonNullable<ReturnType<typeof popoverView>>;

/** 팝오버 자리 잡기 — 그릴 때마다 기준 곁에 놓고, 스크롤(어디서든)·창 크기 변화에 다시 놓는다. */
function usePlacement(controller: Props["controller"], open: ProposalOpen | null, box: { current: HTMLDivElement | null }, key: string) {
  useLayoutEffect(() => { if (box.current && open) placeBox(controller, open, box.current); });
  useEffect(() => {
    const doc = box.current?.ownerDocument;
    if (!key || !doc) return;
    const again = () => { if (box.current && open) placeBox(controller, open, box.current); };
    doc.addEventListener("scroll", again, true);
    doc.defaultView?.addEventListener("resize", again);
    return () => { doc.removeEventListener("scroll", again, true); doc.defaultView?.removeEventListener("resize", again); };
  }, [key]);
}

/** 행동 줄 — 주 행동 「필드로 만들기」(제안만), 보조 「이 자리만…」(Python `only`·자리 수), 물러선 「그대로 두기」. */
function popoverActions(controller: Props["controller"], model: PopoverModel): ReactNode {
  return h("div", { className: "authoring-proposal-actions" },
    model.make && primary(PROPOSAL_COPY.make, run(controller, () => controller.proposal.make(model.group))),
    model.only && button(model.only.label, run(controller, () => controller.proposal.make(model.group, model.only!.spot))),
    quiet(PROPOSAL_COPY.keep, run(controller, () => controller.proposal.dismiss(model.group)), { className: "btn quiet authoring-proposal-keep" }));
}

/** 팝오버 본문 — 출처 줄, 다른 열 주석, 값 상자(표시 형식·데이터 값), 같은 값 수·위치, 주석, 보류 이유(Python 문장). */
function popoverBody(model: PopoverModel): ReactNode[] {
  return [
    h("p", { key: "source", className: "authoring-proposal-source" }, model.source),
    ...model.columns.map((note, index) => h("p", { key: `column-${index}`, className: "authoring-proposal-note" }, note)),
    h("div", { key: "value", className: "authoring-proposal-value" },
      h("div", { className: "authoring-proposal-text" }, model.value),
      model.format && h("div", { className: "authoring-proposal-format" }, h("span", null, PROPOSAL_COPY.format),
        h("span", { className: "authoring-proposal-fmt" }, model.format.label),
        h("span", { className: "authoring-proposal-raw" }, `${PROPOSAL_COPY.raw} `, h("span", { className: "mono" }, model.format.raw)))),
    model.same && !model.held && h("p", { key: "same", className: "authoring-proposal-same" }, icon("same"), h("b", null, model.same.text),
      model.same.where ? h("span", null, ` · ${model.same.where}`) : null),
    model.note && h("p", { key: "note", className: "authoring-proposal-note" }, model.note),
    model.links && h("p", { key: "links", className: "authoring-proposal-note" }, model.links),
    model.reason && h("p", { key: "why", className: "authoring-proposal-why" }, icon("info"), h("span", null, model.reason)),
  ];
}

/** 팝오버 머리의 이름 — 같은 값의 열이 여럿이면 그 가운데 고르는 칸(고르면 Python 이 그 열로 다시 판정한다), 아니면 이름. */
function popoverName(controller: Props["controller"], model: PopoverModel): ReactNode {
  if (!model.choices.length) return h("span", { className: "authoring-proposal-field" }, model.name);
  return h("select", { className: "field authoring-proposal-field authoring-proposal-column", "aria-label": PROPOSAL_COPY.columnPick,
    value: model.column, onChange: (event: any) => run(controller, () => controller.proposal.pickColumn(model.group, String(event.target.value)))() },
    ...model.choices.map((column) => h("option", { key: column, value: column }, column)));
}

/** 제안 팝오버(비모달 대화상자 「이름 제안」) — 문서 자리를 누르거나 구조 패널 줄을 고르면 선다. Escape·닫기·행동이 걷고,
 *  닫으면 초점은 연 자리(패널 줄 또는 편집면의 지금 선택)로 돌아간다. 패널 줄에서 열면 첫 행동이 초점을 받는다. */
export function ProposalPopover({ controller, item, view }: Surface): ReactNode {
  const box = useRef<HTMLDivElement>(null);
  const open: ProposalOpen | null = view.proposalOpen || null;
  const model = popoverView(proposalOf(item), open);
  usePlacement(controller, open, box, model ? `${model.group}:${model.spot}:${open?.origin}` : "");
  useEffect(() => { if (open?.focus && model) box.current?.querySelector<HTMLElement>(".authoring-proposal-actions button")?.focus(); }, [open?.focus, !!model]);
  if (!model) return null;
  const close = () => controller.proposal.close(!!box.current?.contains(box.current.ownerDocument.activeElement));
  return h("div", { ref: box, className: `authoring-proposal-popover${model.held ? " held" : ""}`, role: "dialog", "aria-label": model.dialogLabel,
    onKeyDown: (event: any) => {
      if (event.key !== "Escape" || event.nativeEvent?.isComposing) return;
      event.preventDefault(); event.stopPropagation(); close();
    } },
    h("div", { className: "authoring-proposal-head" },
      popoverName(controller, model),
      model.held && h("span", { className: "authoring-proposal-chip" }, PROPOSAL_COPY.held),
      iconButton("close", PROPOSAL_COPY.close, close)),
    ...popoverBody(model),
    popoverActions(controller, model));
}
