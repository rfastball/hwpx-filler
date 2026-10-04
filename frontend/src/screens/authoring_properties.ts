import { createElement as h, useEffect, useRef, useState } from "react";
import { COMMANDS, coordinates } from "./authoring_controller.ts";
import type { AuthoringController } from "./authoring_controller.ts";
import { CREATE_TYPES, StructureDelta } from "./authoring_commands.ts";
import { IDENTIFIER_IMPACT, KIND_LABEL, commandAvailability, problemCount } from "./authoring_outline_model.ts";
import { button, quiet, primary, danger, iconButton, sectionLabel } from "./authoring_primitives.ts";
import type { Obj, Props } from "./authoring_primitives.ts";
import { kindGlyph } from "./icons.ts";

export function appliedProperties(selected: Obj | null | undefined, proposal = "") {
  return { name: selected?.name || selected?.label || proposal, identifier: selected?.option_id || selected?.slot_id || selected?.id || "",
    parent: selected?.slot_id || "", text: String(selected?.raw?.value ?? selected?.name ?? "") };
}
/** Escape 의 단계: 작성 중인 값이 적용값과 다르면 입력만 되돌리고(revert), 같으면 패널을 닫는다(close). */
export function escapeStage(selected: Obj | null | undefined, draft: ReturnType<typeof appliedProperties>, proposal = ""): "revert" | "close" {
  const applied = appliedProperties(selected, proposal);
  return (Object.keys(applied) as (keyof typeof applied)[]).some((key) => applied[key] !== draft[key]) ? "revert" : "close";
}
/** 편집기 마운트의 보존 판정 보고(U01·§7.1). 판정·안내는 Python 투영(tab.compatibility) 하나에서 선다 —
 *  Python 판정이 돌아오기 전에 편집기가 스스로 막았거나(내보내기·검사 호출 실패) 마운트가 무너지면
 *  그 사실만 Python 에 알린다. 이미 판정을 받은 뒤의 차단은 Python 이 안다(다시 알리지 않는다). */
export const sameCommand = (a: Obj | null | undefined, b: Obj | null | undefined): boolean => !!a && !!b && JSON.stringify(a) === JSON.stringify(b);
/** 속성 제출(P-01 확인 등급) — 한글 조합 중 Enter 는 어느 등급에서도 확정이 아니다(§6.2·§10). 보냈으면 true.
 *  보인 미리보기가 `enter` 등급이고 입력이 그때와 같으면 이 제출이 적용이다. 아니면 미리보기를 받고, Python 이 준 등급이
 *  `none` 이면 그 값으로 곧바로 적용한다(미리보기 구획은 서지 않는다). `button` 등급은 제출로 적용되지 않는다 — 위험 단추뿐이다.
 *  `finish` 가 없으면(등급 밖의 제출) 미리보기만 세운다. */
export function submitProperties(controller: Pick<AuthoringController, "guarded" | "preview" | "viewModel">, composing: boolean, command: () => Obj,
  finish?: (prepared: Obj) => Promise<void>): boolean {
  if (composing) return false;
  const sent = command();
  const shown = controller.viewModel.getSnapshot();
  void controller.guarded(async () => {
    if (finish && shown.preview?.confirm === "enter" && sameCommand(sent, shown.command)) { await finish(shown.preview); return; }
    const prepared = await controller.preview(sent);
    if (finish && prepared && !prepared.refusal && prepared.confirm === "none") await finish(prepared);
  });
  return true;
}

const RENAME_TYPES = ["rename_field", "rename_slot", "rename_option"];
const FIELD_TYPES = ["create_field", "rename_field", "relink_field", "unset_field"];

export function SemanticForm({ controller, selected, selection, preview, onClose }: Props & { selected: Obj; selection: Obj; preview: Obj | null; onClose: () => void }) {
  const view = controller.viewModel.getSnapshot();
  const [type, setType] = useState(view.commandType || "create_field");
  // 이름 칸의 제안(P-06)은 Python 이 선택 앞 라벨에서 지은 값이다 — 폼이 이 대상으로 설 때 한 번 받아 둔다(캐럿 재보고가
  // 문맥을 잠시 비워도 쓰던 이름을 덮지 않는다). 표면은 라벨을 추론하지 않는다.
  const suggestion = String(view.context?.name_suggestion || "");
  const [proposal, setProposal] = useState(suggestion);
  const proposed = type === "create_field" ? proposal : "";
  const [name, setName] = useState(() => appliedProperties(selected, proposed).name);
  const [identifier, setIdentifier] = useState(() => appliedProperties(selected).identifier);
  const [parent, setParent] = useState(() => appliedProperties(selected).parent);
  const [text, setText] = useState(() => appliedProperties(selected).text);
  const [cascade, setCascade] = useState(false);
  const [keepValue, setKeepValue] = useState(true);
  // 같은 문구 N곳(P-07): Python 이 준 원시 자리 목록(찾은 revision·고른 자리 열쇠와 함께)과 체크한 자리. 모두 해제로 시작한다(U03).
  const [same, setSame] = useState<Obj | null>(null);
  const [checked, setChecked] = useState<number[]>([]);
  // 「연결 식별자」 접기(P-11a): 만들기에서는 접혀 있고(비우면 이름을 쓴다), 이름 거절이 그 칸을 가리키면 편다.
  const [identifierOpen, setIdentifierOpen] = useState(false);
  const composing = useRef(false);
  const nameInput = useRef<HTMLInputElement>(null);
  const readOnly = controller.tab().media === "hwpx" && controller.tab().rhwp_editable !== true;
  const available = commandAvailability(view.commands, type);
  const refusal: Obj | null = view.refusal;
  // 이름 문법 거절(invalid_name)은 그 입력 칸 곁에 선다 — 거절 구획·오류 띠가 아니다(P-06). 입력은 그대로 남는다.
  const invalid: Obj | null = refusal?.code === "invalid_name" ? refusal : null;
  const invalidField = invalid ? (invalid.field === "identifier" ? "identifier" : "name") : "";
  // 고른 자리(편집기 좌표)와 체크한 같은 문구 자리들 — 목록은 찾은 문서·고른 자리 그대로일 때만 선다(옛 좌표를 보이지도 싣지도 않는다).
  const site = coordinates(selection);
  const siteKey = JSON.stringify(site);
  const sameHits: Obj[] | null = type === "create_field" && same && same.key === siteKey && same.revision === controller.revisionOf() ? same.hits : null;
  const ranges = sameHits && checked.length ? [site, ...checked.map((index) => sameHits[index].location)] : null;
  const switchType = (next: string) => { setType(next); controller.update({ preview: null, refusal: null, commandType: next }); };
  const cancel = () => controller.update({ preview: null, refusal: null });
  // 기존 필드에 연결(U07)은 개별 사용 위치 한 곳이 선택됐을 때만 뜻이 있다 — 필드 전체 선택은 사용 위치 묶음(occurrences)을 가진다.
  const singleOccurrence = selected?.kind === "field" && !selected?.occurrences;
  const candidates: Obj[] = preview?.candidates || controller.tab().analysis?.fields || [];
  const affected = preview?.affected ?? preview?.edits?.length ?? 0;
  const revert = (offer = proposed) => { const applied = appliedProperties(selected, offer); setName(applied.name); setIdentifier(applied.identifier); setParent(applied.parent); setText(applied.text); };
  useEffect(() => { setProposal(suggestion); revert(type === "create_field" ? suggestion : ""); setSame(null); setChecked([]); if (selected?.occurrences) setType("rename_field"); }, [selected]);
  useEffect(() => { if (view.commandType) setType(view.commandType); }, [view.commandType]);
  useEffect(() => { if (invalidField === "identifier") setIdentifierOpen(true); }, [refusal]);
  const command = (): Obj => ({ ...selected, ...(["create_field", "create_slot", "create_option", "adjust_range"].includes(type) ? selection : {}), type, name, old_name: selected?.name || name,
    id: identifier || name, label: name, slot_id: type === "create_option" ? view.context?.slot_id : parent || selected?.slot_id || selected?.id,
    option_id: selected?.option_id, kind: selected?.kind || "slot", text, cascade,
    destination: selection.start, destination_entry: selection.entry, destination_paragraph: selection.start_paragraph ?? selection.paragraph, new_id: identifier || name,
    // 여러 자리 명령(IDE-07)은 한 명령이다 — 체크한 자리가 있을 때만 `ranges`(고른 자리 포함).
    ...(type === "create_field" && ranges ? { ranges } : {}) });
  // 문맥 줄(UX-10 R2): Python 의 location_label(담긴 항목/선택 · 문단·행 범위)만 보인다 — 원시 좌표는 싣지 않는다.
  const locationLabel = String(view.context?.location_label || "");
  // 대상 카드(UX-09)는 의미 요소(필드·항목·선택)일 때만 선다 — 검색 적중처럼 종류가 없는 대상은 글자 범위다.
  const kind: "field" | "slot" | "option" | null = selected?.kind === "field" || selected?.kind === "slot" || selected?.kind === "option" ? selected.kind : null;
  // 고른 문구 카드(UX-10 R2): 의미가 아직 없는 글자 범위를 고른 채 속성을 열면(필드로 만들기) 무엇을 만드는지 보인다.
  // 카드는 보일 글자가 있을 때만 선다 — Python 이 문구를 확정하지 못하면(selected_text 없음) 빈 카드 대신 문맥 줄만 남는다.
  const rangeText = String(view.context?.selected_text || "");
  const textRange = !kind && !!rangeText && selection.start != null && selection.end != null && (selection.start !== selection.end
    || (selection.start_paragraph ?? selection.paragraph) !== (selection.end_paragraph ?? selection.start_paragraph ?? selection.paragraph));
  // 화면 읽기(§10): 이름 칸은 대상(종류·사용 위치)과 소속(상위 항목/선택·범위)을 설명으로 함께 읽힌다. 거절이 서면 그 문장도.
  const describedBy = (key: string) => [key === "name" && (kind || textRange) && "authoring-properties-target", key === "name" && locationLabel && "authoring-properties-context",
    invalidField === key && `authoring-properties-${key}-reason`].filter(Boolean).join(" ") || undefined;
  const control = (key: string, value: string, onChange: (value: string) => void, props: Obj = {}) => h("input", { className: "field", value,
    ref: key === "name" ? nameInput : undefined, ...props, "aria-describedby": describedBy(key), "aria-invalid": invalidField === key || undefined,
    onChange: (event: any) => onChange(event.target.value) });
  const reason = (key: string) => invalidField === key && h("p", { key: `${key}-reason`, className: "authoring-reason", id: `authoring-properties-${key}-reason`, role: "alert" }, invalid!.message);
  const field = (label: string, key: string, value: string, onChange: (value: string) => void, props: Obj = {}) => [
    h("label", { key: `${key}-field`, className: "authoring-field" }, label, control(key, value, onChange, props)), reason(key)];
  const close = () => { controller.update({ panel: "", preview: null, refusal: null }); onClose(); };
  // 대상 카드(UX-09): 종류 표지 · 굵은 이름 · 메타 한 줄. 이름 칸의 설명(aria-describedby)은 카드 전체의 접근 이름이다.
  const whole = selected?.kind === "field" && Array.isArray(selected?.occurrences);
  const problems = problemCount(controller.tab().problems, selected?.kind === "field" ? selected?.name : selected?.option_id || selected?.slot_id || selected?.name);
  const targetMeta = selected?.kind === "field"
    ? [selected.occurrences ? `사용 위치 ${selected.count ?? selected.occurrences.length}곳` : "", selected.occurrences ? "" : String(selected.context || ""), problems ? `문제 ${problems}` : ""]
    : [String(selected?.location_label || ""), problems ? `문제 ${problems}` : ""];
  // 제출 단추는 처음부터 명령 이름이다(NG-04) — 「필드로 만들기」를 눌러 연 폼의 확정도 「필드로 만들기」다.
  const applyLabel = COMMANDS.find(([value]) => value === type)?.[1] || "적용";
  // 명시 만들기 진입(도구 막대·문맥 메뉴·팔레트)은 「명령」 선택을 그리지 않는다(NG-05). 구조 목록 줄·F2 는 둔다.
  const explicitCreate = view.formEntry === "create" && CREATE_TYPES.includes(type);
  // 이름 변경 폼은 입력이 적용값과 같은 동안 보낼 것이 없다(NG-05 c) — 표면이 제 입력을 비교할 뿐이다.
  const unchanged = RENAME_TYPES.includes(type) && escapeStage(selected, { name, identifier, parent, text }) === "close";
  const blocked = readOnly || !available.enabled;
  const tier = preview?.confirm;
  // enter 등급 미리보기가 섰고 입력이 그때와 같으면 다음 Enter(또는 같은 주 단추)가 적용이다 — 단추에 Enter 키 표기가 선다.
  const armed = !!preview && tier === "enter" && sameCommand(command(), view.command);
  /** 준비된 미리보기를 적용한다. `none` 등급의 만들기는 적용 뒤 패널을 닫고 새 요소를 고른다(결정 2·NG-14) — 선택·캐럿이
   *  새 필드에 서서 이름표와 위치 줄(「필드 · 이름」)이 무엇이 됐는지 보인다. 다른 등급은 영향을 본 자리에 패널이 남는다. */
  const finish = async (prepared: Obj) => {
    const sent = prepared.command || command();
    const captured = prepared.original;
    const applied = await controller.applyPreview(prepared);
    if (!applied) return;
    if (sent.type === "create_field" && keepValue && sent.name && captured) await controller.keepTrialValue(String(sent.name), String(captured));
    // 패널이 남는 이름 변경(#1069): 카드·위치 줄·이름 칸이 Python 이 되짚은 새 대상으로 선다 — 이름이 같아지니 제출은 다시 꺼진다.
    if (prepared.confirm !== "none" && applied.renamed) { await controller.adopt(applied.renamed); return; }
    if (prepared.confirm !== "none" || !CREATE_TYPES.includes(sent.type)) return;
    controller.update({ panel: "", preview: null, refusal: null, formEntry: "" });
    if (applied.created) await controller.select(applied.created, { keepDock: true });
    onClose();
  };
  const submit = () => submitProperties(controller, composing.current, command, finish);
  // 위험 단추(button 등급): 누름만이 적용이다 — Enter 제출은 미리보기를 다시 세울 뿐이다.
  const apply = () => { void controller.guarded(async () => { if (!composing.current && preview) await finish(preview); }); };
  const nameLabel = type.includes("field") ? "필드 이름" : "표시 이름";
  const findSame = () => { void controller.guarded(async () => { const found = await controller.sameText(selection); if (found) { setSame({ ...found, key: siteKey }); setChecked([]); } }); };
  /** 같은 문구 자리 한 줄: 체크 상자 · Python 문맥(찾은 글자는 강조 — 같은 줄의 두 자리가 갈린다) · 흐린 위치 줄. 만들 수 없는 자리는
   *  흐린 채 Python 사유가 그 상자의 설명이다. */
  const sameRow = (hit: Obj, index: number) => {
    const reasonId = hit.reason ? `authoring-same-${index}-reason` : undefined;
    const text = String(hit.context || "");
    const focus = hit.focus;
    return h("label", { key: index, className: `authoring-same-row${hit.enabled ? "" : " disabled"}` },
      h("input", { type: "checkbox", checked: checked.includes(index), disabled: !hit.enabled || undefined, "aria-describedby": reasonId,
        onChange: (event: any) => setChecked(event.target.checked ? [...checked, index].sort((a, b) => a - b) : checked.filter((at) => at !== index)) }),
      h("span", { className: "authoring-same-text" }, ...(focus ? [text.slice(0, focus.start), h("mark", { key: "focus" }, text.slice(focus.start, focus.end)), text.slice(focus.end)] : [text])),
      hit.location_label ? h("span", { className: "authoring-row-context" }, hit.location_label) : null,
      hit.reason ? h("span", { className: "authoring-reason", id: reasonId }, hit.reason) : null);
  };
  return h("form", { className: "authoring-properties", "aria-labelledby": "authoring-properties-title", onCompositionStart: () => { composing.current = true; }, onCompositionEnd: () => { composing.current = false; },
    onSubmit: (event: any) => { event.preventDefault(); submit(); },
    // Escape 1단계: 입력창의 작성 중인 값만 적용값으로 되돌린다. 2단계(되돌릴 것이 없을 때)는 셸이 패널을 닫고 선택으로 돌아간다.
    onKeyDown: (event: any) => {
      if (event.key !== "Escape" || event.nativeEvent?.isComposing) return;
      if (escapeStage(selected, { name, identifier, parent, text }, proposed) === "revert") { event.stopPropagation(); revert(); }
    } },
    // 닫기(§3.1): 모든 폭에서 머리 오른쪽에 선다 — Escape 의 닫기 단계와 같은 일(패널을 닫고 선택으로 돌아간다).
    h("div", { className: "authoring-properties-head" }, sectionLabel("속성", { id: "authoring-properties-title" }),
      iconButton("close", "닫기", close)),
    kind && h("div", { className: "authoring-target" },
      h("span", { className: "authoring-target-kind" }, kindGlyph(kind), h("span", { className: "authoring-kind" }, KIND_LABEL[kind])),
      // 필드 전체는 이름 칸의 설명이 outlineLabel 전체(종류·이름·사용 위치 수·문제)다 — 보이는 것은 굵은 이름과 메타 줄이고,
      // 종류·수는 화면 읽기용 글로만 이름에 붙는다(보이는 표지·메타와 같은 글이라 두 번 읽히지 않게 메타는 숨긴다).
      whole ? h("p", { id: "authoring-properties-target", className: "authoring-target-name" },
          h("span", { className: "authoring-sr" }, `${KIND_LABEL.field} · `), selected.name,
          h("span", { className: "authoring-sr" }, ` · ${[`사용 위치 ${selected.count ?? selected.occurrences.length}곳`, ...(problems ? [`문제 ${problems}`] : [])].join(" · ")}`))
        : h("p", { id: "authoring-properties-target", className: "authoring-target-name" }, selected.name || selected.label || selected.id),
      targetMeta.some(Boolean) && h("p", { className: "authoring-target-meta", "aria-hidden": whole || undefined }, targetMeta.filter(Boolean).join(" · "))),
    // 카드 전체가 이름 칸의 설명이다(종류 「고른 문구」 + 글자).
    textRange && h("div", { className: "authoring-target", id: "authoring-properties-target" },
      h("span", { className: "authoring-target-kind" }, h("span", { className: "authoring-kind" }, "고른 문구")),
      h("p", { className: "authoring-target-name quote", title: rangeText }, rangeText)),
    // 명령을 바꿔도 초점은 이 select 에 남는다(WCAG 3.2.2) — 닫힌 select 의 ↑↓ 는 값마다 change 를 쏜다.
    !explicitCreate && h("label", { className: "authoring-field" }, "명령", h("select", { className: "field", value: type, "aria-disabled": !available.enabled || undefined, title: available.reason || undefined,
      "aria-describedby": !available.enabled && available.reason ? "authoring-properties-reason" : undefined, onChange: (event: any) => switchType(event.target.value) },
      ...COMMANDS.map(([value, label]) => { const entry = commandAvailability(view.commands, value); return h("option", { key: value, value, disabled: !entry.enabled, title: entry.reason || undefined }, label); }))),
    // 비활성 사유와 대안은 Python 의 판정을 그대로 보인다(P07) — 툴팁만이 유일한 경로가 되지 않도록 본문에도 선다(§10).
    !available.enabled && available.reason && h("p", { className: "authoring-reason", id: "authoring-properties-reason" }, available.reason),
    !available.enabled && available.alternative && h("div", null, button(available.alternative.label, () => switchType(available.alternative!.command_type))),
    locationLabel && h("p", { className: "authoring-context", id: "authoring-properties-context" }, locationLabel),
    ...field(nameLabel, "name", name, setName, nameLabel === "필드 이름" ? { list: "authoring-existing-fields" } : {}),
    type === "create_field" && h("datalist", { id: "authoring-existing-fields" }, ...candidates.map((candidate: Obj) => h("option", { key: candidate.name, value: candidate.name, label: `${candidate.name} · 사용 위치 ${candidate.count ?? 0}곳` }))),
    // 연결 식별자(P-11a): 만들기에서는 접는다(요약이 칸의 이름이다). 이름 변경은 기존 작업 연결에 닿으므로 펼친 칸이다.
    !FIELD_TYPES.includes(type) && (["create_slot", "create_option"].includes(type)
      ? h("details", { className: "authoring-disclosure", open: identifierOpen || invalidField === "identifier", onToggle: (event: any) => setIdentifierOpen(!!event.currentTarget?.open) },
        h("summary", null, "연결 식별자"), control("identifier", identifier, setIdentifier, { "aria-label": "연결 식별자" }), reason("identifier"))
      : field("연결 식별자", "identifier", identifier, setIdentifier)),
    type === "create_option" ? h("p", null, `상위 항목: ${view.context?.slot_id || "없음"}`) :
      ["rename_option", "adjust_range", "unwrap", "delete", "duplicate", "move"].includes(type) && field("상위 항목", "parent", parent, setParent),
    type === "unset_field" && field("남길 본문", "text", text, setText),
    type === "unset_field" && h("div", { className: "authoring-actions start" },
      quiet("필드 이름 사용", () => setText(selected?.name || "")),
      quiet("시험값 사용", () => setText(String(view.values[selected?.name] ?? "")), { disabled: !(selected?.name in view.values) })),
    type === "create_field" && h("label", null, h("input", { type: "checkbox", checked: keepValue, onChange: (event: any) => setKeepValue(event.target.checked) }), " 고른 문구를 시험값으로 보관"),
    type === "unwrap" && h("label", null, h("input", { type: "checkbox", checked: cascade, onChange: (event: any) => setCascade(event.target.checked) }), " 하위 의미 함께 해제"),
    // 같은 문구 N곳(P-07): 적용 전 폼 안에서 같은 문구 자리를 체크 목록으로 고른다. 기본 범위는 고른 한 곳이다(U03) — 행은 모두
    // 해제로 시작하고, 체크한 자리만 한 명령(`ranges`)에 실린다. 요약은 검색과 같은 Python 문장이다.
    type === "create_field" && textRange && h("div", { className: "authoring-actions start" }, quiet("다른 같은 문구 찾기", findSame)),
    sameHits && same?.summary && h("p", { className: "authoring-search-summary" }, same.summary),
    sameHits && !!sameHits.length && h("div", { className: "authoring-same", role: "group", "aria-label": "검색 결과" }, ...sameHits.map(sameRow)),
    // 거절(U07·AC08·AC10): Python 의 판정 문장을 그대로 보이고, 다음 행동만 버튼으로 세운다. 이름 문법 거절은 칸 곁이다.
    refusal && !invalid && h("section", { className: "authoring-preview authoring-refusal", role: "alert", "aria-label": "변경 불가" },
      h("p", null, refusal.message),
      refusal.code === "cascade_required" && h("ul", { "aria-label": "함께 해제될 하위 의미" }, ...(refusal.children || []).map((child: Obj, index: number) =>
        h("li", { key: index }, `${KIND_LABEL[child.kind] || child.kind} · ${child.label || child.id}${child.count != null ? ` · ${child.count}` : ""}`))),
      h("div", { className: "authoring-actions" },
        button("취소", cancel, { className: "btn quiet" }),
        refusal.code === "name_conflict" && quiet("다른 이름 입력", () => { nameInput.current?.focus(); nameInput.current?.select(); }),
        refusal.code === "name_conflict" && singleOccurrence && button("기존 필드에 연결", () => { setName(String(refusal.name || "")); switchType("relink_field"); }),
        refusal.code === "cascade_required" && primary("하위 의미 함께 해제", () => { setCascade(true); submitProperties(controller, composing.current, () => ({ ...command(), cascade: true }), finish); }))),
    preview && h("section", { className: "authoring-preview", "aria-label": "변경 영향" },
      h("h3", { className: "authoring-section-label" }, "변경 영향"),
      preview.expanded && h("p", null, "고른 범위를 문단 전체로 넓힙니다. 포함될 내용을 확인하세요."),
      // 전체 이름 변경의 문장(§13)은 조사까지 Python 이 짓는다(preview.message) — 표면은 그대로 보인다.
      h("p", null, preview.message || `사용 위치 ${affected}곳`),
      preview.counts && h("p", null, `문단 ${preview.counts.paragraphs ?? 0} · 필드 ${preview.counts.fields ?? 0} · 선택 ${preview.counts.options ?? 0} · 표 ${preview.counts.tables ?? 0}`),
      preview.included != null && (Array.isArray(preview.included)
        ? h("ul", { "aria-label": "포함될 내용" }, ...preview.included.map((entry: Obj | string, index: number) => h("li", { key: index }, typeof entry === "string" ? entry : entry.label || entry.text || entry.id)))
        : h("pre", { role: "group", "aria-label": "포함될 내용" }, String(preview.included))),
      !!preview.children?.length && h("ul", { "aria-label": "하위 의미" }, ...preview.children.map((child: Obj, index: number) =>
        h("li", { key: index }, `${KIND_LABEL[child.kind] || child.kind} · ${child.label || child.id}${child.count != null ? ` · ${child.count}` : ""}`))),
      preview.links_existing && h("p", null, `기존 필드에 연결 · 사용 위치 ${preview.existing_count ?? 0}곳`),
      (preview.before || preview.original) && h("pre", { role: "group", "aria-label": "변경 전" }, preview.before || preview.original),
      preview.after && h("pre", { role: "group", "aria-label": "변경 후" }, preview.after),
      preview.structure_delta && h(StructureDelta, { delta: preview.structure_delta }),
      !!preview.structure_delta?.renamed?.length && h("p", null, IDENTIFIER_IMPACT),
      preview.body_changed && h("p", null, "본문 변경 있음"),
      !!preview.linked_jobs?.length && h("p", null, `연결된 작업: ${preview.linked_jobs.join(", ")}`),
      !!preview.impact_unverified && h("p", null, "연결된 작업의 영향은 확인하지 않았습니다."),
      preview.field_delta && h("p", null, `추가 필드: ${(preview.field_delta.added_fields || []).join(", ") || "없음"} · 없어진 필드: ${(preview.field_delta.removed_fields || []).join(", ") || "없음"}`),
      ...(preview.edits || []).map((edit: Obj, index: number) => h("pre", { key: index }, edit.text))),
    // 바닥 행동 줄(UX-09): 오른쪽 정렬. 주 행동은 명령 이름의 제출 단추 하나다(NG-04) — Enter 도 이 단추가 받는다.
    // none 등급은 그 한 번에 적용되고, enter 등급은 영향이 선 뒤 같은 단추(Enter 표기)가 적용이며, button 등급은 제출이
    // 미리보기를 다시 세우는 「변경 미리보기」가 되고 적용은 위험 단추(명령 이름)뿐이다.
    h("div", { className: "authoring-actions authoring-properties-actions" },
      quiet("취소", preview ? cancel : close),
      tier === "button" && preview
        ? h("button", { key: "recheck", className: "btn", type: "submit", disabled: blocked, "aria-disabled": blocked || undefined, title: available.reason || undefined }, "변경 미리보기")
        : h("button", { key: "submit", className: "btn primary", type: "submit", disabled: blocked || unchanged, "aria-disabled": (blocked || unchanged) || undefined, title: available.reason || undefined,
          "aria-keyshortcuts": armed ? "Enter" : undefined },
        applyLabel, armed ? h("kbd", { className: "authoring-key", "aria-hidden": true }, "Enter") : null),
      tier === "button" && preview && danger(applyLabel, apply, { key: "apply" })),
  );
}

/** 시험 결과의 닻 필드(IDE-04 · P-02) — 마지막으로 값을 바꾼 시험 입력의 필드, 없으면 편집면에서 고른 필드다.
 *  둘 다 없으면 null 이고 결과는 옮기지 않는다(쪽 머리). 이름은 표면이 짓지 않는다 — 입력칸·선택 대상의 이름 그대로다. */
