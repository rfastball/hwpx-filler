/* 등록 데이터(pool) 등록 폼(`#poolRegModal`) 상태 — `data_picker.ts` 책임 분리(복잡도
   예산 — module_statements 상한). 이 폼은 「지금 마운트된 데이터」(`data_picker.ts` 의
   `state`)와 독립적인 가변 상태(`reg`·`regRevision`·`inspectionRevision`)라 깨끗이
   나뉜다 — 여는 쪽(openPin·openPclm·행 ⋯ 동사)이 프리필 값을 다 채워 넘기므로 이 모듈은
   마운트 세션을 몰라도 된다. */
import {
  inspectedRegistrationSheets, newRegistrationState, registrationSheetError,
  selectedRegistrationSheets,
} from "./registration_sheets.ts";
import type { RegState } from "./registration_sheets.ts";

type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
  open(id: string, spec?: Obj): void;
  close(id: string): void;
};

/** 등록 폼 상태 → 발행할 액션과 payload. pclm/excel 두 갈래의 조립을 한 곳에 모은다
 *  (복잡도 예산 — `submitReg` 분리). 순수 함수라 `reg` 스냅샷만 받는다. */
function buildRegistrationPayload(reg: RegState): { action: string; payload: Obj } {
  const pclm = reg.mode === "pclm";
  const action = pclm ? "register_pclm" : reg.targetKey ? "relink" : "register_excel";
  const payload: Obj = pclm
    ? { name: reg.name.trim(), db: reg.db.trim(), view: reg.view, views: [...reg.sheets], note: reg.note.trim() }
    : {
      name: reg.name.trim(), path: reg.path.trim(), sheet: reg.sheet.trim(), sheets: [...reg.sheets], note: reg.note.trim(),
    };
  if (reg.targetKey) payload.key = reg.targetKey;
  return { action, payload };
}

type RegistrationCheck = { ok: true } | { ok: false; error: string | null };

/** 제출 전 유효성 검사 3종(이름·경로 필수, 조사 재검증, 시트 선택)을 하나의 판정으로
 *  모은다(복잡도 예산 — `submitReg` 분리). `error: null` 은 「아직 준비되지 않았다」로
 *  조용히 멈추는 자리(지문 재조사 대기 등)고, 문자열은 사용자에게 보일 사유다. */
function validateRegistration(reg: RegState, payload: Obj): RegistrationCheck {
  const pclm = reg.mode === "pclm";
  if (pclm ? !payload.name : !payload.name || !payload.path) {
    return { ok: false, error: pclm ? "이름을 입력하세요." : "이름과 파일 경로를 입력하세요." };
  }
  if (reg.inspecting || !reg.inspectedPath || reg.inspectedPath !== (pclm ? payload.db : payload.path)) {
    return { ok: false, error: null };
  }
  const sheetError = registrationSheetError(reg);
  if (sheetError) return { ok: false, error: sheetError };
  return { ok: true };
}

export type RegistrationFormDeps = {
  doc: Document;
  modal: ModalPort;
  dispatch(screen: string, action: string, payload?: Obj): Promise<Obj>;
  pickPoolDataFile(): Promise<unknown>;
  notify(message: string): void;
  refreshScreen(screen: "job" | "editor"): Promise<unknown>;
};

export function createRegistrationForm(deps: RegistrationFormDeps) {
  let reg: RegState | null = null;
  let regRevision = 0;
  let inspectionRevision = 0;
  const regListeners = new Set<Listener>();

  function emitReg(): void { for (const listener of [...regListeners]) listener(); }

  function patchReg(next: Partial<RegState>): void {
    if (reg === null) return;
    if ((next.path !== undefined && next.path !== reg.path) || (next.db !== undefined && next.db !== reg.db)) {
      inspectionRevision++;
      next = { ...next, sheet: "", view: "", sheets: [], availableSheets: [], inspectedPath: "", inspecting: false, error: "" };
    }
    reg = { ...reg, ...next };
    emitReg();
  }

  function openRegDialog(options: Partial<RegState>): void {
    regRevision++;
    reg = newRegistrationState(options);
    emitReg();
    /* 첫 빈 좌표에 선다 — 엑셀은 파일 경로, 고정(pin)과 계약 목록은 이름(계약 목록의 DB 자리는
       파일 고르기가 이미 채웠다). */
    const focusId = options.pinMode || reg.mode === "pclm" ? "poolRegName" : "poolRegPath";
    deps.modal.open("poolRegModal", { initialFocus: deps.doc.getElementById(focusId) });
    void inspectRegSheets();
  }

  /** 조사 응답 판정 — 성공이면 지문을 되싣고, 아니면 사유를 남긴다(복잡도 예산 —
   *  `inspectRegSheets` 분리의 추출 대상). */
  function settleInspection(result: Obj, path: string): void {
    if (result.ok !== true || !Array.isArray(result.sheets)) {
      patchReg({ error: result.error || "등록하지 못했습니다." });
      return;
    }
    const availableSheets = result.sheets as RegState["availableSheets"];
    patchReg(inspectedRegistrationSheets(reg!, availableSheets, path));
  }

  /** 조사를 건너뛸 자리인가 — 가드 3종을 한 판정으로 모은다(복잡도 예산 —
   *  `inspectRegSheets` 분리의 추출 대상). */
  function inspectionBlocked(path: string): boolean {
    if (reg === null) return true;
    return reg.submitting || !path || reg.inspectedPath === path || reg.inspecting;
  }

  async function inspectRegSheets(): Promise<void> {
    if (reg === null) return;
    const pclm = reg.mode === "pclm";
    const path = (pclm ? reg.db : reg.path).trim();
    if (inspectionBlocked(path)) return;
    const revision = regRevision;
    const request = ++inspectionRevision;
    const current = () => reg !== null && regRevision === revision && inspectionRevision === request;
    patchReg({ inspecting: true, error: "" });
    try {
      const result = await deps.dispatch("pool", "inspect_sheets", pclm ? { path, kind: "pclm" } : { path });
      if (current()) settleInspection(result, path);
    } catch (error) {
      if (current()) patchReg({ error: String((error as Obj)?.message || error) });
    } finally {
      if (current()) patchReg({ inspecting: false });
    }
  }

  function selectRegSheets(sheets: string[]): void {
    if (reg === null || reg.inspecting || reg.submitting) return;
    patchReg(selectedRegistrationSheets(reg, sheets));
  }

  async function confirmedRegistration(
    action: string, payload: Obj, okLabel: string, revision: number, result: Obj,
  ): Promise<Obj | null> {
    if (!result.needs_confirm) return result;
    const accepted = await deps.modal.confirm({
      body: result.confirm_text, confirmLabel: okLabel, cancelLabel: "취소", danger: true,
    });
    if (!accepted || reg === null || regRevision !== revision) return null;
    return deps.dispatch("pool", action, { ...payload, confirm: true, basis: result.basis });
  }

  async function refreshRegisteredTabs(screen: RegState["refreshScreen"]): Promise<void> {
    if (!screen) return;
    try { await deps.refreshScreen(screen); }
    catch (error) { deps.notify(String((error as Obj)?.message || error)); }
  }

  /** 제출 응답 후속 처리 — 지연 확인 왕복·판정·시트 닫기까지(복잡도 예산 — `submitReg`
   *  분리의 추출 대상). 도중에 폼이 바뀌었거나(revision 불일치) 거절됐으면 조용히 멈춘다. */
  async function settleRegistrationSubmit(
    action: string, payload: Obj, initial: Obj, revision: number, pclm: boolean,
  ): Promise<void> {
    if (reg === null || regRevision !== revision) return;
    const result = await confirmedRegistration(action, payload, reg.okLabel, revision, initial);
    if (result === null || reg === null || regRevision !== revision) return;
    if (result.ok === false) { patchReg({ error: result.error || "등록하지 못했습니다." }); return; }
    const refreshScreen = pclm && reg.targetKey ? reg.refreshScreen : "";
    deps.modal.close("poolRegModal");
    reg = null;
    emitReg();
    await refreshRegisteredTabs(refreshScreen);
  }

  async function submitReg(): Promise<void> {
    if (reg === null || reg.submitting) return;
    const pclm = reg.mode === "pclm";
    const { action, payload } = buildRegistrationPayload(reg);
    const check = validateRegistration(reg, payload);
    if (!check.ok) {
      if (check.error !== null) patchReg({ error: check.error });
      return;
    }
    const revision = regRevision;
    patchReg({ submitting: true });
    try {
      const initial = await deps.dispatch("pool", action, payload);
      await settleRegistrationSubmit(action, payload, initial, revision, pclm);
    } catch (error) {
      if (regRevision === revision) patchReg({ error: String((error as Obj)?.message || error) });
    } finally {
      if (regRevision === revision) patchReg({ submitting: false });
    }
  }

  return {
    regModel: {
      getSnapshot: (): RegState | null => reg,
      subscribe(listener: Listener): () => void {
        regListeners.add(listener);
        return () => { regListeners.delete(listener); };
      },
    },
    openRegDialog, patchReg, inspectRegSheets, selectRegSheets, submitReg,
    closeReg(): void { deps.modal.close("poolRegModal"); regRevision++; reg = null; emitReg(); },
    browseRegPath: async (): Promise<void> => {
      if (reg === null || reg.submitting) return;
      const revision = regRevision;
      const previousPath = reg.path;
      const path = await deps.pickPoolDataFile();
      if (path && reg !== null && regRevision === revision && reg.path === previousPath) {
        patchReg({ path: String(path) });
        await inspectRegSheets();
      }
    },
  };
}

export type RegistrationForm = ReturnType<typeof createRegistrationForm>;
