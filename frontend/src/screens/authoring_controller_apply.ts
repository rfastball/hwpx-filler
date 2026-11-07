/* 명령 미리보기·적용·문서 명령 — `authoring_controller.ts` 책임 분리(복잡도 예산 —
 * module_statements/function_statements 상한). 공유 가변 상태(뷰·viewId·적용 중 표지·
 * 미리보기 요청 번호)는 get/set 으로 deps 를 받는다. 이 모듈은 선택(select/adopt) 쪽
 * 상태를 몰라도 된다 — 받는 명령·미리보기는 호출자가 다 채워 넘긴다. */
type Obj = Record<string, any>;

export type ApplyDeps = {
  editors: Map<string, { content(): Promise<string>; apply(content: string, edits: Obj[], label: string, expectedContent?: string): Promise<void> }>;
  snapshot(): Obj;
  getView(): Obj;
  getViewId(): string;
  update(patch: Obj): void;
  dispatch(action: string, payload?: Obj, verdict?: boolean): Promise<Obj>;
  flush(id: string): Promise<void>;
  revision(id: string): number;
  modal: { confirm(spec: Obj): Promise<boolean> };
  getApplying(): boolean;
  setApplying(value: boolean): void;
  getPreviewRequest(): number;
  bumpPreviewRequest(): number;
  /** 다음에 되돌릴 행동의 이름 — `COMMANDS`·`DOCUMENT_COMMANDS` 양쪽에서 찾는다. */
  commandLabel(type: string): string | undefined;
  /** 문서 명령(#1078)만의 표시 이름 — `documentCommand` 의 확인 창 제목이 이것을 쓴다. */
  documentCommandLabel(type: string): string | undefined;
  changed(id: string, content: string): void;
  scheduleTrial(id: string): void;
};

export function createApplyController(deps: ApplyDeps) {
  const previewCommand = (id: string, atRevision: number, command: Obj): Promise<Obj> => command.type === "paste"
    ? deps.dispatch("preview_paste", { session_id: id, revision: atRevision, clipboard_token: command.clipboard_token,
      destination: command.destination, with_meaning: command.with_meaning })
    : deps.dispatch("preview", { session_id: id, revision: atRevision, command });

  /** 명령 하나를 미리 본다. 돌려주는 값이 준비된 미리보기다(거절이면 refusal 을 실은 결과, 늦었으면 null).
   *  확인 등급(P-01)이 `none` 이면 미리보기 구획을 그리지 않는다 — 호출자가 그 값으로 곧바로 적용한다(번쩍임 없음). */
  async function preview(command: Obj): Promise<Obj | null> {
    const id = deps.snapshot().active_id;
    const request = deps.bumpPreviewRequest();
    await deps.flush(id);
    const editorContent = await deps.editors.get(id)?.content();
    const atRevision = deps.revision(id);
    const result = await previewCommand(id, atRevision, command);
    if (id !== deps.getViewId() || request !== deps.getPreviewRequest() || atRevision !== deps.revision(id)) return null;
    if (result.refusal) { deps.update({ command, preview: null, refusal: result.refusal }); return result; }
    const prepared = { ...result, session_id: id, revision: atRevision, editorContent, command };
    deps.update({ command, preview: result.confirm === "none" ? null : prepared, refusal: null });
    return prepared;
  }

  /** 다음에 되돌릴 행동의 이름(§9.3) — backend 가 label 을 주면 그것, 아니면 명령 표시 이름
   *  (복잡도 예산 — `applyPreview` 분리의 추출 대상). */
  function resolveCommandLabel(prepared: Obj, result: Obj, command: Obj): string {
    return prepared.label || result.label || deps.commandLabel(command.type) || command.type;
  }

  /** 만든/개명한 대상을 적용 뒤 revision 에서 짚는다(복잡도 예산 — `applyPreview` 분리의
   *  추출 대상) — 호출자가 그 자리를 고를 수 있게(선택·캐럿·이름표). */
  function createdOrRenamedAt(id: string, result: Obj): { created: Obj | null; renamed: Obj | null } {
    const at = { session_id: id, source_revision: deps.revision(id) };
    return {
      created: result.created ? { ...result.created, ...at } : null,
      renamed: result.renamed ? { ...result.renamed, ...at } : null,
    };
  }

  /** 적용할 준비된 미리보기와 명령 — 인자가 없으면 보이는 미리보기다(복잡도 예산 —
   *  `applyPreview` 분리의 추출 대상). */
  function resolvePreparedCommand(given: Obj | undefined, view: Obj): { prepared: Obj | undefined; command: Obj | undefined } {
    const prepared = given || view.preview;
    return { prepared, command: prepared?.command || view.command };
  }

  /** 편집기에 적용하고 그 내용을 되읽어 draft 를 정산한다(복잡도 예산 — `applyPreview`
   *  분리의 추출 대상). */
  async function applyToEditor(
    editor: { content(): Promise<string>; apply(content: string, edits: Obj[], label: string, expectedContent?: string): Promise<void> },
    result: Obj, command: Obj, prepared: Obj, id: string,
  ): Promise<void> {
    await editor.apply(result.content ?? result.result, result.edits || [], command.type, prepared.editorContent);
    deps.changed(id, await editor.content());
  }

  /** 준비된 미리보기를 적용한다 — 인자가 없으면 보이는 미리보기다. 확정 직전 revision
   *  재검사는 등급과 무관하게 늘 돈다. */
  async function applyPreview(given?: Obj): Promise<{ label: string; created: Obj | null; renamed: Obj | null } | undefined> {
    if (deps.getApplying()) return;
    const { prepared, command } = resolvePreparedCommand(given, deps.getView());
    if (!prepared || !command) return;
    deps.setApplying(true);
    try {
      const id = prepared.session_id;
      await deps.flush(id);
      // 확정 직전에도 backend가 같은 revision을 검사한다. 늦은 미리보기는 적용하지 않는다.
      const result = await previewCommand(id, prepared.revision, command);
      if (result.refusal) throw new Error(result.refusal.message);
      await deps.flush(id);
      if (deps.revision(id) !== prepared.revision) throw new Error("문서가 변경되었습니다. 변경 미리보기를 다시 실행하세요.");
      const editor = deps.editors.get(id);
      if (!editor) throw new Error("문서 편집기를 다시 여세요.");
      await applyToEditor(editor, result, command, prepared, id);
      await deps.flush(id);
      const label = resolveCommandLabel(prepared, result, command);
      if (id === deps.getViewId()) {
        const nowView = deps.getView();
        deps.update({ command: null, preview: null, lastCommandLabel: label, commandNote: { seq: (nowView.commandNote?.seq || 0) + 1, kind: "apply", label } });
      }
      deps.scheduleTrial(id);
      return { label, ...createdOrRenamedAt(id, result) };
    } finally { deps.setApplying(false); }
  }

  /** 문서 명령 하나를 실행한다(#1078) — 속성 패널 없이 미리보기 → (확인 등급이 `none` 이 아니면) 파괴 확인 → 적용이다.
   *  확인 창은 제목·확인 단추가 명령 이름, 본문이 Python 이 지은 손실 집합(`message`)이고 기본 초점은 취소다(`button` 등급:
   *  위험 단추 누름만이 적용이다). 적용은 다른 명령과 같은 편집 사슬(applyPreview → 편집기 한 번의 실행 취소 단위)이다.
   *  돌려주는 값은 적용했는가다 — 취소했거나 그사이 문서·탭이 바뀌었으면 false. */
  async function documentCommand(type: string): Promise<boolean> {
    const id = deps.snapshot().active_id;
    await deps.flush(id);
    const editorContent = await deps.editors.get(id)?.content();
    const atRevision = deps.revision(id);
    const command = { type };
    const result = await previewCommand(id, atRevision, command);
    if (result.refusal) throw new Error(result.refusal.message);
    if (id !== deps.getViewId() || atRevision !== deps.revision(id)) return false;
    const name = deps.documentCommandLabel(type) || String(result.label || type);
    if (result.confirm !== "none" && !(await deps.modal.confirm({ title: name, body: String(result.message || ""), confirmLabel: name, danger: true })))
      return false;
    return !!(await applyPreview({ ...result, session_id: id, revision: atRevision, editorContent, command }));
  }

  return { preview, previewCommand, applyPreview, documentCommand };
}

export type ApplyController = ReturnType<typeof createApplyController>;
