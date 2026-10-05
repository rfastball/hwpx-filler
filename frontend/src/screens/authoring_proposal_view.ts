/* 「데이터로 필드 찾기」(#1156)의 React 표면 — 띠(도구 막대 아래), 구조 패널의 제안·보류 묶음, 제안 팝오버, 빈 필드
 * 목록의 입구 링크. 모양은 `authoring_proposal.ts` 의 순수 투영이 정하고 여기서는 그리기·초점·자리만 맡는다. */
import { Fragment, createElement as h, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { clampMenu, roveFocus } from "./authoring_a11y.ts";
import { selectionBarPlace } from "./authoring_commands.ts";
import { button, iconButton, primary, quiet } from "./authoring_primitives.ts";
import type { Obj, Props } from "./authoring_primitives.ts";
import { PROPOSAL_COPY, bandView, missingLines, outlineGroups, popoverView, proposalCounts, proposalOf } from "./authoring_proposal.ts";
import type { ProposalFocus, ProposalOpen } from "./authoring_proposal.ts";
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

/** 맞춰 보는 동안 띠의 조작 — `disabled` 가 아니라 `aria-disabled` 로 흐리고 입력을 무시한다. 초점을 쥔 조작이 disabled 가
 *  되면 브라우저가 초점을 문서 몸통으로 떨어뜨리고 되살리지 않는다(행을 ↓ 로 넘기다 초점을 잃는다). */
const dimmed = (off: boolean) => (off ? { "aria-disabled": true } : {});
const unless = (off: boolean, work: () => void) => () => { if (!off) work(); };

/** 데이터·행 고르기 — 데이터는 Python 이 준 등록 데이터 목록(지금 데이터가 골라진 채로만 선다), 행은 Python 이 고른 행과 상위 행이며
 *  고른 행의 힌트와 행이 잘렸을 때의 Python 안내가 곁에 선다. 데이터가 없으면(needs_data) 데이터 선택 창을 여는 단추가 선다. */
function bandPickers(controller: Props["controller"], band: ReturnType<typeof bandView>): ReactNode[] {
  const busy = band.state === "working";
  return [
    band.dataKey && band.datasets.length > 0 && h(Fragment, { key: "data" },
      h("label", { htmlFor: "authoring-proposal-data" }, PROPOSAL_COPY.data),
      h("select", { id: "authoring-proposal-data", className: "field authoring-proposal-select", value: band.dataKey, ...dimmed(busy),
        onChange: (event: any) => { if (!busy) run(controller, () => controller.proposal.chooseData(String(event.target.value)))(); } },
        ...band.datasets.map((entry) => h("option", { key: String(entry.key), value: String(entry.key) }, String(entry.name ?? entry.key))))),
    band.pickData && controller.proposal.canPickData() && h(Fragment, { key: "pick" },
      button(PROPOSAL_COPY.pickData, unless(busy, run(controller, () => controller.proposal.pickData())), { className: "btn", ...dimmed(busy) })),
    band.rows.length > 0 && h(Fragment, { key: "row" },
      h("label", { htmlFor: "authoring-proposal-row" }, PROPOSAL_COPY.row),
      h("select", { id: "authoring-proposal-row", className: "field authoring-proposal-select", value: band.row, ...dimmed(busy),
        onChange: (event: any) => { if (!busy) run(controller, () => controller.proposal.chooseRow(Number(event.target.value)))(); } },
        ...band.rows.map((row) => h("option", { key: String(row.index), value: String(row.index) }, String(row.label ?? row.index)))),
      band.hint && h("span", { className: "authoring-proposal-hint" }, band.hint),
      band.rowsNote && h("span", { className: "authoring-proposal-rows-note" }, band.rowsNote)),
  ];
}

/** 행동 뒤 초점 요청(`ProposalFocus`)을 푼다 — Python 의 다음 투영이 닿은 뒤(revision 이 바뀌었거나 그 묶음이 사라졌다) 같은
 *  차례의 구조 패널 줄로, 줄이 없거나 접혀 있으면 띠 제목으로. 남은 제안이 없을 때만 띠 제목으로 가는 요청(모두 필드로)도 있다. */
function useFocusRequest(controller: Props["controller"], root: { current: HTMLElement | null }, proposal: Obj | null, request: ProposalFocus | null) {
  const groups: string[] = Array.isArray(proposal?.groups) ? proposal!.groups.map((group: Obj) => String(group.id)) : [];
  useEffect(() => {
    const shell = root.current?.closest<HTMLElement>(".authoring-shell");
    if (!request || !proposal || !shell || waiting(request, proposal, groups)) return;
    controller.proposal.focusDone();
    focusTarget(shell, request, proposal);
  }, [request?.seq, `${proposal?.revision}:${groups.join(",")}`]);
}
/** 요청이 아직 Python 의 다음 투영을 기다리는가 — revision 이 그대로이고 행동한 묶음이 아직 있다. */
const waiting = (request: ProposalFocus, proposal: Obj, groups: string[]) =>
  request.revision !== undefined && proposal.revision === request.revision && (!request.group || groups.includes(request.group));
/** 요청의 자리로 초점을 옮긴다 — 줄 차례(없으면 띠 제목), 띠 제목, 또는 남은 제안이 없을 때만 띠 제목. */
function focusTarget(shell: HTMLElement, request: ProposalFocus, proposal: Obj) {
  const title = shell.querySelector<HTMLElement>("#authoring-proposal-title");
  if (request.target === "emptyTitle") { if (!proposalCounts(proposal).proposal) title?.focus(); return; }
  const rows = request.target === "row" ? [...shell.querySelectorAll<HTMLElement>("button[data-proposal-row]")] : [];
  (rows[Math.min(Math.max(request.index, 0), rows.length - 1)] || title)?.focus();
}

/** 띠(도구 막대 아래, 이름 붙은 구획): 데이터·행 고르기, 수, 「제안 N개 모두 필드로」, 끄기. 수가 바뀌면 단일 live region 이 한 번 읽는다. */
export function ProposalBand({ controller, item, view }: Surface): ReactNode {
  const proposal = proposalOf(item);
  const band = proposal ? bandView(proposal, !!view.proposalBusy) : null;
  const root = useRef<HTMLElement>(null);
  const spoken = useRef("");
  const say = spokenOf(band);
  useEffect(() => { if (say && say !== spoken.current) controller.announce(say); spoken.current = say; }, [say]);
  useFocusRequest(controller, root, proposal, view.proposalFocus || null);
  if (!band || !proposal) return null;
  // 끄면 띠가 사라진다 — 초점은 도구 막대의 대기 항목으로 간다.
  const off = run(controller, async () => {
    const toolbar = root.current?.closest(".authoring-shell")?.querySelector<HTMLElement>('.authoring-toolbar [data-rove][tabindex="0"]');
    await controller.proposal.off();
    toolbar?.focus();
  });
  return h("section", { ref: root, className: "authoring-proposal-band", role: "region", "aria-labelledby": "authoring-proposal-title", "aria-busy": band.state === "working" || undefined },
    h("span", { className: "authoring-proposal-title", id: "authoring-proposal-title", tabIndex: -1 }, icon("find"), PROPOSAL_COPY.title),
    ...bandPickers(controller, band),
    bandStatus(band, proposal),
    band.primary && primary(band.primary.label, unless(band.primary.disabled, run(controller, () => controller.proposal.makeAll())), dimmed(band.primary.disabled)),
    h("span", { className: "authoring-proposal-sep", "aria-hidden": true }),
    iconButton("close", PROPOSAL_COPY.off, off));
}

/** 구조 패널의 제안·보류 묶음(띠가 켜진 동안 필드 목록 위). 줄은 한 번의 Tab 으로 들어와 ↑↓ 로 옮기고(roving),
 *  누르면 그 자리로 편집면을 옮기며 팝오버를 연다(대화상자를 여는 단추: aria-haspopup·aria-expanded). 행동 뒤 초점은 띠가 돌린다. */
export function ProposalOutline({ controller, item, view }: Surface): ReactNode {
  const proposal = proposalOf(item);
  const [active, setActive] = useState("");
  if (proposal?.state !== "ready") return null;
  const groups = outlineGroups(proposal);
  const all = [...groups.proposals, ...groups.held];
  const open: ProposalOpen | null = view.proposalOpen || null;
  const current = all.some((entry) => entry.id === active) ? active : all[0]?.id;
  const row = (entry: Obj) => h("button", { key: entry.id, type: "button", className: "authoring-proposal-row", "data-proposal-row": entry.id,
    tabIndex: entry.id === current ? 0 : -1, "aria-label": entry.label,
    "aria-haspopup": "dialog", "aria-expanded": open?.group === entry.id, onFocus: () => setActive(entry.id),
    onClick: (event: any) => run(controller, () => controller.proposal.openRow(entry.id, event.currentTarget))() },
    h("span", { className: `authoring-proposal-swatch${entry.held ? " held" : ""}`, "aria-hidden": true }),
    h("span", { className: "authoring-proposal-name", title: entry.name }, entry.name),
    entry.count ? h("span", { className: "authoring-proposal-count" }, entry.count) : null);
  const head = (id: string, label: string, count: number) => h("div", { className: "authoring-proposal-group", id }, h("span", null, label), h("span", null, String(count)));
  return h("div", { className: "authoring-proposal-list", onKeyDown: (event: any) => { roveFocus(event, event.currentTarget, "button[data-proposal-row]", "vertical"); } },
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
      // 링크는 띠가 서며 걷힌다 — 초점을 쥐고 있었으면 띠 제목으로 옮긴다.
      h("button", { type: "button", className: "authoring-proposal-link",
        onClick: (event: any) => { const focused = event.currentTarget === event.currentTarget.ownerDocument?.activeElement; run(controller, () => controller.proposal.start(focused))(); } },
        PROPOSAL_COPY.link)));
}

/** 팝오버의 기준 자리(호스트 창 좌표) — 패널 줄이면 그 줄(오른쪽에 선다), TXT 면 그 자리 표식, HWPX 면 캐럿 줄.
 *  문서 자리가 보이지 않으면(TXT 표식이 편집면 스크롤 밖이거나 가상화로 걷혔다, HWPX 캐럿 줄이 틀 밖이다) `"hidden"` 이다. */
function anchorOf(controller: Props["controller"], open: ProposalOpen, box: HTMLElement): { rect: Rect; side: "below" | "right" } | "hidden" | null {
  const element = open.origin === "row" ? controller.proposal.opener() as HTMLElement | null
    : box.ownerDocument.querySelector<HTMLElement>(`.authoring-document:not([hidden]) [data-token=${JSON.stringify(`proposal:${open.spot}`)}]`);
  const rect = element?.isConnected && typeof element.getBoundingClientRect === "function" ? element.getBoundingClientRect() : null;
  if (rect && open.origin === "row") return { rect: { left: rect.right, top: rect.top, bottom: rect.bottom }, side: "right" };
  if (rect) return outside(rect, element!.closest<HTMLElement>(".cm-scroller")) ? "hidden" : { rect: { left: rect.left, top: rect.top, bottom: rect.bottom }, side: "below" };
  if (open.rect) return { rect: open.rect as Rect, side: "below" };
  return open.origin === "spot" ? "hidden" : null;
}
/** 자리 표식이 편집면 스크롤 창 밖인가. */
function outside(rect: { top: number; bottom: number }, scroller: HTMLElement | null): boolean {
  const view = scroller?.getBoundingClientRect();
  return !!view && view.bottom > view.top && (rect.bottom <= view.top || rect.top >= view.bottom);
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
  const anchor = placeAnchor(controller, open, box, shell);
  if (!anchor) return;
  const size = box.getBoundingClientRect();
  const place = proposalPlace(anchor, { width: size.width, height: size.height }, { width: win.innerWidth, height: win.innerHeight });
  const base = shell.getBoundingClientRect();
  box.style.left = `${place.left - base.left - (shell.clientLeft || 0) + (shell.scrollLeft || 0)}px`;
  box.style.top = `${place.top - base.top - (shell.clientTop || 0) + (shell.scrollTop || 0)}px`;
}

/** 놓을 기준 — 문서 자리가 보이지 않는 동안 팝오버는 숨고(엉뚱한 글 위에 떠 있지 않는다) 기준이 없다. 자리가 다시 보이면 그 곁에
 *  선다. 기준을 모르면(패널 줄이 걷혔다) 편집면 왼쪽 위다. */
function placeAnchor(controller: Props["controller"], open: ProposalOpen, box: HTMLElement, shell: HTMLElement) {
  const found = anchorOf(controller, open, box);
  box.style.visibility = found === "hidden" ? "hidden" : "";
  return found === "hidden" ? null : found ?? canvasAnchor(shell);
}
/** 기준을 모를 때(패널 줄이 걷혔다)의 자리 — 편집면 왼쪽 위. */
function canvasAnchor(shell: HTMLElement): { rect: Rect; side: "below" } | null {
  const canvas = shell.querySelector<HTMLElement>(".authoring-canvas")?.getBoundingClientRect();
  return canvas ? { rect: { left: canvas.left + PROPOSAL_GAP, top: canvas.top, bottom: canvas.top }, side: "below" } : null;
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

/** 행동 줄 — 주 행동 「필드로 만들기」(제안만), 보조 「이 자리만…」(Python `only_label`), 물러선 「그대로 두기」. 누를 때 초점이
 *  팝오버 안에 있었는지를 넘긴다 — 그러면 행동 뒤 초점이 패널 줄(없으면 띠 제목)로 간다. */
function popoverActions(controller: Props["controller"], model: PopoverModel, inside: () => boolean): ReactNode {
  return h("div", { className: "authoring-proposal-actions" },
    model.make && primary(PROPOSAL_COPY.make, () => { const focused = inside(); run(controller, () => controller.proposal.make(model.group, undefined, focused))(); }),
    model.only && button(model.only.label, () => { const focused = inside(); run(controller, () => controller.proposal.make(model.group, model.only!.spot, focused))(); }),
    quiet(PROPOSAL_COPY.keep, () => { const focused = inside(); run(controller, () => controller.proposal.dismiss(model.group, focused))(); }, { className: "btn quiet authoring-proposal-keep" }));
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
  const inside = () => !!box.current?.contains(box.current.ownerDocument.activeElement);
  const close = () => controller.proposal.close(inside());
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
    popoverActions(controller, model, inside));
}
