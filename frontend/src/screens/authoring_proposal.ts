/* 「데이터로 필드 찾기」(#1156) — 저작 작업대의 제안 띠·문서 표식·팝오버·구조 패널 묶음의 표면 몫.
 *
 * 판정(제안·보류 등급, 이유·주석 문장, 필드 이름, 연결 열, 표시 형식, 자리 좌표, 행 힌트)은 전부 Python 의 탭 투영
 * `proposal` 이다. 여기서는 (1) 그 투영을 띠·팝오버·표식 모양으로 옮기는 **순수** 함수(단위로 잰다)와 (2) 다섯 액션
 * (`propose_fields`·`propose_make`·`propose_make_all`·`propose_dismiss`·`propose_off`)을 보내고 만든 결과를 편집기의
 * 기존 실행 취소 한 단위(편집기 `apply`)로 얹는 동작만 든다. 등급을 다시 매기거나 이유를 조립하지 않는다. */
import type { LintpadMark } from "../editorview/txt_card_marks.ts";

type Obj = Record<string, any>;
/** 이 기능이 쓰는 편집기 표면 — 저작 컨트롤러의 편집기 형 일부(컨트롤러를 가져오면 모듈 고리가 생긴다). */
type ProposalEditor = {
  content(): Promise<string>;
  focus(target: Obj): Promise<void>;
  command(command: "undo"): Promise<void>;
  scrollTo?(target: Obj): Promise<boolean>;
};

/** 이 기능의 고정 문구(단추·표지) — 이름·수가 든 문장(출처 줄·같은 이름 필드 주석·「이 자리만」 단추 이름·만든 뒤 알림)은
 *  Python 이 묶음·결과에 실어 준다(#1156 문구 목록). */
export const PROPOSAL_COPY = {
  title: "데이터로 필드 찾기",
  menu: "데이터로 필드 찾기…",
  link: "데이터로 필드 찾기",
  data: "데이터",
  row: "행",
  noneLeft: "남은 제안 없음",
  off: "데이터로 필드 찾기 끄기",
  working: "문서와 데이터를 맞춰 보는 중…",
  needsData: "먼저 데이터를 고르세요.",
  proposals: "제안",
  held: "보류",
  emptyProposals: "남은 제안이 없습니다.",
  missing: "찾지 못한 열",
  format: "표시형",
  raw: "데이터 값",
  make: "필드로 만들기",
  only: "이 자리만",
  keep: "그대로 두기",
  close: "제안 닫기",
  undo: "실행 취소",
  columnPick: "필드 이름과 연결 열",
} as const;
export const countsText = (proposals: number, held: number) => `제안 ${proposals} · 보류 ${held}`;
export const makeAllText = (count: number) => `제안 ${count}개 모두 필드로`;
export const sameText = (count: number) => `같은 값 ${count}곳`;
export const spotName = (group: Obj) => `${group.kind === "held" ? "보류된 제안" : "필드 제안"} ${group.name}: ${group.value}`;

/** 팝오버가 선 자리 — 연 묶음·자리, 연 길(문서 캐럿 `spot`·구조 패널 줄 `row`), 문서에서 열었으면 캐럿 줄(호스트 좌표),
 *  초점을 팝오버로 옮길 차례 번호(패널 줄에서 연 때만 — 문서에서 연 팝오버는 타자 중의 초점을 가져가지 않는다). */
export type ProposalOpen = { group: string; spot: string; origin: "spot" | "row"; rect: Obj | null; focus: number };

/** 탭의 제안 투영 — 띠가 꺼져 있으면 null. */
export function proposalOf(item: Obj | null | undefined): Obj | null {
  const proposal = item?.proposal;
  return proposal && typeof proposal === "object" ? proposal : null;
}
const groupsOf = (proposal: Obj | null): Obj[] => Array.isArray(proposal?.groups) ? proposal!.groups : [];
const spotsOf = (group: Obj | null | undefined): Obj[] => Array.isArray(group?.spots) ? group!.spots : [];
export const findGroup = (proposal: Obj | null, id: string | undefined): Obj | null => groupsOf(proposal).find((group) => group.id === id) || null;
/** 묶음을 고를 때 먼저 서는 자리 — 보류 묶음이 고를 수 있는 한 자리(`only`)를 가졌으면 그 자리, 아니면 첫 자리. */
export function firstSpot(group: Obj | null): Obj | null {
  const spots = spotsOf(group);
  return spots.find((spot) => spot.id === group?.only) || spots[0] || null;
}
/** 제안 수·보류 수 — Python 의 `counts`. */
export function proposalCounts(proposal: Obj | null): { proposal: number; held: number } {
  return { proposal: Number(proposal?.counts?.proposal) || 0, held: Number(proposal?.counts?.held) || 0 };
}

/** 띠 한 줄의 모양 — 상태(맞춰 보는 중·데이터 없음·실패·준비), 데이터·행 고르기, 수, 주 행동. */
export function bandView(proposal: Obj, busy: boolean) {
  const state = busy ? "working" : String(proposal.state || "");
  return { state, ...bandData(proposal, state), message: bandMessage(proposal, state), failed: state === "failed", primary: bandPrimary(proposal, state) };
}
/** 데이터·행 고르기 — 고른 데이터 키, 행 목록(데이터가 없으면 비움), 고른 행과 그 Python 힌트. */
function bandData(proposal: Obj, state: string) {
  const data: Obj = proposal.data && typeof proposal.data === "object" ? proposal.data : {};
  const rows: Obj[] = Array.isArray(data.rows) && state !== "needs_data" ? data.rows : [];
  return {
    datasets: (Array.isArray(proposal.datasets) ? proposal.datasets : []) as Obj[],
    dataKey: String(data.pool_key ?? ""),
    rows,
    row: data.row == null ? "" : String(data.row),
    hint: String(rows.find((row) => row.index === data.row)?.hint ?? ""),
  };
}
/** 상태 자리: 준비면 수, 맞춰 보는 중이면 그 문구, 데이터가 없으면 다음 행동, 실패면 Python 문장(오류로 읽힌다). */
function bandMessage(proposal: Obj, state: string): string {
  const counts = proposalCounts(proposal);
  if (state === "ready") return countsText(counts.proposal, counts.held);
  if (state === "working") return PROPOSAL_COPY.working;
  return state === "needs_data" ? PROPOSAL_COPY.needsData : String(proposal.error || "");
}
/** 주 행동 「제안 N개 모두 필드로」 — 남은 제안이 없거나 맞춰 보는 중이면 흐리다. 데이터 없음·실패에는 서지 않는다. */
function bandPrimary(proposal: Obj, state: string): { label: string; disabled: boolean } | null {
  if (state !== "ready" && state !== "working") return null;
  const count = proposalCounts(proposal).proposal;
  return { label: count ? makeAllText(count) : PROPOSAL_COPY.noneLeft, disabled: state !== "ready" || count === 0 };
}

/** 구조 패널의 두 묶음 줄 — 제안·보류 각각, 줄마다 열쇠·이름·자리 수 표기(Python `count_text`)·접근 이름. */
export function outlineGroups(proposal: Obj | null): { proposals: Obj[]; held: Obj[] } {
  const row = (group: Obj) => ({ id: String(group.id), name: String(group.name ?? ""), count: String(group.count_text ?? ""),
    held: group.kind === "held", label: spotName(group) });
  const groups = groupsOf(proposal);
  return { proposals: groups.filter((group) => group.kind === "proposal").map(row), held: groups.filter((group) => group.kind === "held").map(row) };
}

/** 찾지 못한 열 — 같은 이유끼리 한 줄(열 이름을 「, 」로 잇는다)이고 이유는 Python 문장이다. */
export function missingLines(proposal: Obj | null): { columns: string; reason: string }[] {
  const lines = new Map<string, string[]>();
  for (const entry of Array.isArray(proposal?.missing) ? proposal!.missing : []) {
    const reason = String(entry?.reason ?? "");
    lines.set(reason, [...(lines.get(reason) || []), String(entry?.column ?? "")]);
  }
  return [...lines].map(([reason, columns]) => ({ columns: `${PROPOSAL_COPY.missing} · ${columns.join(", ")}`, reason }));
}

/** 보류 묶음의 「이 자리만」 — 단추 이름은 Python `only_label`(없으면 단추가 없다)이고, 고를 수 있는 한 자리(`only`)가 있으면
 *  그 자리, 아니면 연 자리 하나다. 제안 묶음은 자리가 둘 이상일 때만 연 자리 하나를 따로 만들 수 있다. */
function onlyAction(group: Obj, spot: Obj): { label: string; spot: string } | null {
  if (group.kind === "held") {
    const only = spotsOf(group).find((entry) => entry.id === group.only);
    return group.only_label ? { label: String(group.only_label), spot: String((only || spot).id) } : null;
  }
  return spotsOf(group).length > 1 ? { label: PROPOSAL_COPY.only, spot: String(spot.id) } : null;
}

/** 팝오버 한 장의 모양 — 연 묶음이 투영에 없으면(다시 계산되어 사라졌으면) null. 문장은 Python 것이고, 여기서 잇는 것은
 *  같은 값 수 표지뿐이다. 같은 값의 열이 여럿이면 머리가 열 고르기(`choices`)다. */
export function popoverView(proposal: Obj | null, open: ProposalOpen | null | undefined) {
  const group = open ? findGroup(proposal, open.group) : null;
  const spot = spotsOf(group).find((entry) => entry.id === open?.spot) || firstSpot(group);
  if (!proposal || !group || !spot) return null;
  const held = group.kind === "held";
  return {
    group: String(group.id), spot: String(spot.id), held, name: String(group.name ?? ""), dialogLabel: `${group.name} ${PROPOSAL_COPY.proposals}`,
    source: String(group.source_text ?? ""),
    column: columnOf(group),
    choices: columnChoices(group),
    ...popoverDetails(group),
    reason: held ? String(group.reason || "") : "",
    make: !held,
    only: onlyAction(group, spot),
  };
}
/** 연결 열 이름 — Python `column`(없으면 필드 이름). */
const columnOf = (group: Obj) => String(group.column ?? group.name ?? "");
/** 팝오버 머리의 열 고르기 — 지금 열과 「열도 같은 값」 열(Python `columns`). 다른 열이 없으면 빈 목록(이름만 선다). */
function columnChoices(group: Obj): string[] {
  const others = (Array.isArray(group.columns) ? group.columns : []).map((column: Obj) => String(column.name ?? "")).filter(Boolean);
  return others.length ? [columnOf(group), ...others] : [];
}
/** 표시 형식 줄 — 표시 이름이 「원문」이 아닐 때만, 데이터의 원시 값과 함께 선다. */
function formatOf(group: Obj): { label: string; raw: string } | null {
  const label = group.binding?.label;
  return label && label !== "원문" ? { label: String(label), raw: String(group.raw ?? "") } : null;
}
/** 팝오버 본문 — 다른 열 주석, 값, 표시 형식(원문이 아닐 때만, 데이터 값과 함께), 같은 값 수·위치, Python 주석. */
function popoverDetails(group: Obj) {
  const spots = spotsOf(group);
  const where = [...new Set(spots.map((entry) => String(entry.where || "")).filter(Boolean))].join(", ");
  return {
    columns: (Array.isArray(group.columns) ? group.columns : []).map((column: Obj) => String(column.note || "")).filter(Boolean) as string[],
    value: String(group.value ?? ""),
    format: formatOf(group),
    same: spots.length > 1 ? { text: sameText(spots.length), where } : null,
    note: String(group.note || ""),
    links: String(group.links_note || ""),
  };
}

/** 같은 표 칸 경로인가(둘 다 없으면 본문). */
function sameCell(a: unknown, b: unknown): boolean {
  const key = (path: unknown) => JSON.stringify(Array.isArray(path) && path.length ? path.map((step: Obj) => [step?.parent_paragraph, step?.control, step?.cell, step?.paragraph]) : null);
  return key(a) === key(b);
}
/** 캐럿(빈 선택)이 이 자리 안(양 끝 포함)에 섰는가. TXT 는 글자 위치만, HWPX 는 구역·문단·표 칸까지 같아야 한다. */
function holds(spot: Obj, selection: Obj, text: boolean): boolean {
  const at = selection.start;
  if (typeof at !== "number" || selection.end !== at || at < spot.start || at > spot.end) return false;
  return text || sameParagraph(spot, selection);
}
/** HWPX 캐럿과 자리가 같은 구역·문단·표 칸인가. */
function sameParagraph(spot: Obj, selection: Obj): boolean {
  const paragraph = selection.start_paragraph ?? selection.paragraph;
  return selection.entry === spot.entry && paragraph === spot.paragraph && (selection.end_paragraph ?? paragraph) === paragraph
    && sameCell(selection.cell_path, spot.cell_path);
}
/** 편집기 캐럿이 선 제안 자리 — 문서에서 자리를 누르면 그 묶음의 팝오버가 선다. 띠가 준비 상태가 아니면 없다. */
export function spotAt(proposal: Obj | null, selection: Obj, media: string): { group: string; spot: string } | null {
  if (proposal?.state !== "ready") return null;
  for (const group of groupsOf(proposal)) {
    const spot = spotsOf(group).find((entry) => holds(entry, selection, media === "txt"));
    if (spot) return { group: String(group.id), spot: String(spot.id) };
  }
  return null;
}

/** HWPX 편집면에 넘길 제안 자리 — 띠가 준비 상태일 때만. 연 자리에는 필드 이름을 실어 이름표 표지가 하나 더 선다. */
export function proposalSpots(proposal: Obj | null, open: ProposalOpen | null | undefined): { place: Obj; label: string; held: boolean; open?: string }[] {
  if (proposal?.state !== "ready") return [];
  return groupsOf(proposal).flatMap((group) => spotsOf(group).map((spot) => ({ place: spot, label: spotName(group), held: group.kind === "held",
    ...(open?.spot === spot.id ? { open: String(group.name ?? "") } : {}) })));
}

/** TXT 편집면의 제안 표식(본문 표식 층) — 제안은 초록·보류는 회색 점선 밑줄이고, 연 자리는 면이 깔리며 그 앞에 흐린 이름표가
 *  선다. `data-token` 은 팝오버가 그 자리 옆에 서려고 겨누는 신원이다(`proposal:<자리>`). */
export function proposalMarks(proposal: Obj | null, open: ProposalOpen | null | undefined): LintpadMark[] {
  if (proposal?.state !== "ready") return [];
  return groupsOf(proposal).flatMap((group) => groupMarks(group, open?.spot)).sort((a, b) => a.start - b.start || a.end - b.end);
}
/** 한 묶음의 표식 — 자리마다 점선 밑줄, 연 자리는 면을 더하고 그 머리에 흐린 이름표(길이 0 표식)가 선다. */
function groupMarks(group: Obj, lit: string | undefined): LintpadMark[] {
  const kind = group.kind === "held" ? " cm-authoring-proposal-held" : "";
  return spotsOf(group).filter((spot) => typeof spot.start === "number" && typeof spot.end === "number" && spot.end > spot.start).flatMap((spot): LintpadMark[] => {
    const mark = { start: spot.start, end: spot.end, className: `cm-authoring-proposal${kind}`, token: `proposal:${spot.id}` };
    if (spot.id !== lit) return [mark];
    return [{ ...mark, className: `${mark.className} cm-authoring-proposal-open` },
      { start: spot.start, end: spot.start, className: `cm-authoring-proposal-tag${kind}`, label: String(group.name ?? "") }];
  });
}

/** 편집기 장식을 다시 보낼 열쇠 — 같은 투영의 재전송(push)에는 다시 그리지 않는다. */
export function proposalKey(item: Obj | null | undefined): string {
  const proposal = proposalOf(item);
  return proposal ? JSON.stringify([proposal.state, proposal.revision, groupsOf(proposal).map((group) => [group.id, group.kind, spotsOf(group).map((spot) => spot.id)])]) : "";
}

export type ProposalHost = {
  dispatch(action: string, payload: Obj): Promise<Obj>;
  fenced(id: string, payload?: Obj): Obj;
  flush(id: string): Promise<void>;
  editor(id: string): ProposalEditor | undefined;
  /** 이 화면의 미리보기 적용 사슬(`applyPreview`) — 확정 직전 revision 재검사·편집기 한 단위·내용 갱신·실행 취소 표지. */
  applyPreview(prepared: Obj): Promise<unknown>;
  viewId(): string;
  tab(id?: string): Obj;
  view(): Obj;
  update(patch: Obj): void;
  changed(id: string, content: string): void;
  revision(id: string): number;
  pending(id: string): boolean;
  redecorate(): void;
  scheduleTrial(id: string): void;
  /** 「문서 작업」 데이터 고르기(기존 데이터 선택 창) — 데이터가 없을 때 이끈다. */
  dataPicker?: { open(options: Obj): Promise<string | null> };
  /** 되돌리기 알림(1슬롯) — `frontend/js/undo_toast.js`. */
  toast?: { show(message: string, undo: () => unknown, label?: string): void };
};

/** 만들기 명령의 표시 이름(실행 취소 표지) — 기존 「필드로 만들기」. */
const MAKE_LABEL = PROPOSAL_COPY.make;

export function createProposal(host: ProposalHost) {
  // 패널 줄에서 연 팝오버의 줄(닫으면 초점이 돌아갈 자리), 패널 줄 이동 중 캐럿 보고를 물리는 표지, 차례 번호.
  let opener: { focus?(): void; isConnected?: boolean } | null = null;
  let moving = false;
  let seq = 0;

  const proposal = () => proposalOf(host.tab(host.viewId()));
  function setOpen(next: ProposalOpen | null) {
    host.update({ proposalOpen: next });
    host.redecorate();
  }

  /** 띠 켜기·데이터·행 바꾸기·다시 계산. 데이터가 없으면(needs_data) 기존 데이터 선택 창으로 이끌고, 골랐으면 다시 묻는다
   *  (그때 Python 은 「문서 작업」이 지금 쓰는 데이터를 쓴다). */
  async function find(options: Obj = {}) {
    const state = await propose(options);
    if (state !== "needs_data" || options.pool_key || !host.dataPicker) return;
    if (await host.dataPicker.open({ screen: "job" })) await propose({});
  }
  async function propose(options: Obj): Promise<string> {
    const id = host.viewId();
    if (!id) return "";
    host.update({ proposalBusy: true });
    try {
      await host.flush(id);
      const result = await host.dispatch("propose_fields", host.fenced(id, options));
      return String(result.state ?? result.proposal?.state ?? proposalOf(host.tab(id))?.state ?? "");
    } finally {
      host.update({ proposalBusy: false });
      host.redecorate();
    }
  }

  /** 편집기 캐럿 보고(문서 쪽 입구) — 캐럿이 제안 자리에 서면 그 팝오버가 서고, 떠나면 걷힌다. 초점은 옮기지 않는다. */
  function caret(id: string, selection: Obj, rect?: Obj | null) {
    if (id !== host.viewId() || moving) return;
    const hit = spotAt(proposal(), selection || {}, String(host.tab(id).media || ""));
    const open: ProposalOpen | null = host.view().proposalOpen || null;
    if (!hit) { if (open) setOpen(null); return; }
    if (open?.spot === hit.spot) return;
    opener = null;
    setOpen({ ...hit, origin: "spot", rect: rect || null, focus: 0 });
  }

  /** 구조 패널 줄(키보드 입구) — 그 자리로 편집면을 옮기고 팝오버를 연다. 연 줄을 다시 누르면 닫는다. */
  async function openRow(groupId: string, element: { focus?(): void; isConnected?: boolean } | null) {
    const open: ProposalOpen | null = host.view().proposalOpen || null;
    if (open?.group === groupId) { close(false); return; }
    const id = host.viewId();
    const spot = firstSpot(findGroup(proposal(), groupId));
    if (!spot) return;
    moving = true;
    try { await host.editor(id)?.scrollTo?.(spot); } finally { moving = false; }
    opener = element;
    setOpen({ group: groupId, spot: String(spot.id), origin: "row", rect: null, focus: ++seq });
  }

  /** 팝오버를 닫는다. `restore` 면 초점을 연 자리로 — 패널 줄이면 그 줄, 문서면 편집기의 지금 선택. */
  function close(restore: boolean) {
    const open: ProposalOpen | null = host.view().proposalOpen || null;
    if (!open) return;
    setOpen(null);
    if (restore) void returnFocus(open.origin);
  }
  async function returnFocus(origin: string) {
    if (origin === "row" && opener?.isConnected !== false && opener?.focus) { opener.focus(); return; }
    const selection = host.view().selection || {};
    if (Object.keys(selection).length) await host.editor(host.viewId())?.focus(selection);
  }

  /** 만들기 — Python 이 그 revision 에서 지은 미리보기(와 그 명령)를 이 화면의 미리보기 적용 사슬에 넘긴다. 사슬이 확정 직전에
   *  같은 명령을 다시 미리 보아 revision 을 재검사하고, 편집기에 한 단위로 얹은 뒤 내용을 갱신한다(그 갱신이 Python 의 연결 초안을
   *  기록한다). 그사이 문서·탭이 바뀌었으면 얹지 않는다. */
  async function commit(id: string, action: string, payload: Obj): Promise<Obj | null> {
    const editor = host.editor(id);
    if (!editor) return null;
    await host.flush(id);
    const editorContent = await editor.content();
    const atRevision = host.revision(id);
    const result = await host.dispatch(action, host.fenced(id, payload));
    if (result.refusal) throw new Error(String(result.refusal.message || ""));
    if (!result.command || typeof result.command !== "object") throw new Error(`authoring/${action}: command`);
    if (host.viewId() !== id || host.revision(id) !== atRevision) return null;
    const applied = await host.applyPreview({ ...result, session_id: id, revision: atRevision, editorContent, command: result.command });
    return applied ? result : null;
  }

  /** 행동 뒤 — 팝오버를 걷고, 패널 줄에서 열었으면 초점은 줄 목록(같은 차례의 줄)으로 간다. */
  function settle(open: ProposalOpen | null) {
    setOpen(null);
    if (open?.origin === "row") host.update({ proposalFocus: (host.view().proposalFocus || 0) + 1 });
  }

  /** 되돌리기 알림 — Python 문장(`toast`)과 「실행 취소」. 그 뒤 문서가 바뀌었으면 누름은 아무것도 되돌리지 않는다. */
  function announce(id: string, result: Obj) {
    const at = host.revision(id);
    const message = String(result.toast || "");
    if (!message) return;
    host.toast?.show(message, async () => {
      if (host.viewId() !== id || host.pending(id) || host.revision(id) !== at) return;
      await host.editor(id)?.command("undo");
      host.update({ lastCommandLabel: "", commandNote: { seq: (host.view().commandNote?.seq || 0) + 1, kind: "undo", label: MAKE_LABEL } });
    }, PROPOSAL_COPY.undo);
  }

  return {
    find,
    chooseData: (key: string) => find({ pool_key: key }),
    chooseRow(index: number) {
      const data: Obj = proposal()?.data || {};
      return find({ pool_key: data.pool_key, ...(data.sheet != null ? { sheet: data.sheet } : {}), row: index });
    },
    caret, openRow, close,
    async make(groupId: string, spotId?: string) {
      const id = host.viewId();
      const group = findGroup(proposal(), groupId);
      const open: ProposalOpen | null = host.view().proposalOpen || null;
      const result = group && await commit(id, "propose_make", { group_id: groupId, ...(spotId ? { spot_id: spotId } : {}) });
      if (!result) return;
      settle(open);
      announce(id, result);
    },
    async makeAll() {
      const id = host.viewId();
      const count = proposalCounts(proposal()).proposal;
      const result = count ? await commit(id, "propose_make_all", {}) : null;
      if (!result) return;
      settle(host.view().proposalOpen || null);
      announce(id, result);
    },
    async dismiss(groupId: string) {
      const id = host.viewId();
      const open: ProposalOpen | null = host.view().proposalOpen || null;
      await host.flush(id);
      await host.dispatch("propose_dismiss", host.fenced(id, { group_id: groupId }));
      settle(open);
    },
    /** 팝오버 머리의 열 고르기 — 같은 값의 열 가운데 하나(판정·거절은 Python). 팝오버는 같은 묶음 열쇠로 그대로 선다. */
    async pickColumn(groupId: string, column: string) {
      const id = host.viewId();
      await host.flush(id);
      await host.dispatch("propose_pick_column", host.fenced(id, { group_id: groupId, column }));
      host.redecorate();
    },
    async off() {
      const id = host.viewId();
      setOpen(null);
      await host.dispatch("propose_off", { session_id: id });
      host.redecorate();
    },
    /** 패널 줄에서 연 팝오버의 줄 — 팝오버가 그 옆에 선다. */
    opener: () => opener,
    /** HWPX 편집면 장식에 실을 제안 자리(`rhwp_marks.ts` `proposalMarkers`). */
    spots: (id: string) => proposalSpots(proposalOf(host.tab(id)), id === host.viewId() ? host.view().proposalOpen : null),
    /** TXT 편집면 장식에 실을 본문 표식. */
    marks: (id: string) => proposalMarks(proposalOf(host.tab(id)), id === host.viewId() ? host.view().proposalOpen : null),
    key: proposalKey,
  };
}

export type ProposalController = ReturnType<typeof createProposal>;
