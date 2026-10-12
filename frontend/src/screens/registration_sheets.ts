/* 등록 폼의 시트 선언·기본 시트 규칙. Excel과 계약 목록이 같은 체크박스를 쓴다. */
type Sheet = { name: string };
type State = {
  mode: "excel" | "pclm";
  targetKey: string;
  view: string;
  sheet: string;
  sheets: string[];
  availableSheets: Sheet[];
  inspectedPath: string;
  inspecting: boolean;
  submitting: boolean;
  db: string;
  path: string;
};

/* 등록면은 종류를 **명시로** 든다(#937). `mode` 가 없으면 표면이 어느 좌표를 물어야 할지를
   path 유무 같은 모양으로 되추측하게 되고, 그러면 같은 판정이 두 곳에 산다. 엑셀은
   경로+시트, 계약 목록은 DB+뷰 — 좌표가 다를 뿐 확인 왕복(needs_confirm/basis)은 한 벌이다. */
export type RegState = State & {
  title: string;
  okLabel: string;
  name: string;
  note: string;
  refreshScreen: "job" | "editor" | "";
  pinMode: boolean;
  error: string;
};

export function newRegistrationState(options: Partial<RegState>): RegState {
  const defaults: RegState = {
    title: "데이터 등록", okLabel: "등록", mode: "excel", name: "", path: "",
    sheet: "", db: "", view: "", sheets: [],
    availableSheets: [], inspectedPath: "", inspecting: false, submitting: false,
    note: "", targetKey: "", refreshScreen: "", pinMode: false, error: "",
  };
  return { ...defaults, ...options,
    sheets: options.sheets ?? initialRegistrationSheets(options) };
}

function initialRegistrationSheets(options: Partial<RegState>): string[] {
  if (options.mode === "pclm") return options.view ? [options.view] : [];
  const sheet = options.sheet?.trim();
  return sheet ? [sheet] : [];
}

const MISSING_DEFAULT = "기본 시트를 찾을 수 없습니다. 계약 목록 파일을 확인하세요.";

export function missingPclmDefault(value: State): boolean {
  return value.mode === "pclm" && !!value.targetKey
    && !value.availableSheets.some((sheet) => sheet.name === value.view);
}

function primarySheet(value: State, sheets: string[]): string {
  const initial = value.mode === "pclm" ? value.view : value.sheet.trim();
  return value.mode === "pclm" && value.targetKey ? initial
    : sheets.includes(initial) ? initial : sheets[0] || "";
}

export function inspectedRegistrationSheets(value: State, availableSheets: Sheet[], path: string) {
  const sheets = value.sheets.filter((name) => availableSheets.some((sheet) => sheet.name === name));
  const initial = value.mode === "pclm" ? value.view : value.sheet.trim();
  const primary = primarySheet(value, sheets);
  const selected = value.mode === "pclm" ? { view: primary } : { sheet: primary };
  return { availableSheets, sheets, ...selected, inspectedPath: path,
    error: value.mode === "pclm" && value.targetKey
      && !availableSheets.some((sheet) => sheet.name === initial) ? MISSING_DEFAULT : "" };
}

export function selectedRegistrationSheets(value: State, requested: string[]) {
  const sheets = [...new Set(requested)].filter((name) =>
    value.availableSheets.some((sheet) => sheet.name === name));
  if (value.mode === "pclm" && value.targetKey
      && value.availableSheets.some((sheet) => sheet.name === value.view)
      && !sheets.includes(value.view)) sheets.push(value.view);
  const primary = primarySheet(value, sheets);
  return { sheets, ...(value.mode === "pclm" ? { view: primary } : { sheet: primary }),
    error: missingPclmDefault(value) ? MISSING_DEFAULT : "" };
}

export function registrationSheetError(value: State): string {
  if ((value.mode === "pclm" || value.availableSheets.length > 0) && value.sheets.length === 0)
    return "읽을 시트를 고르세요.";
  return missingPclmDefault(value) ? MISSING_DEFAULT : "";
}

export function registrationSubmitDisabled(value: State): boolean {
  return value.submitting || value.inspecting || !value.inspectedPath
    || value.inspectedPath !== (value.mode === "pclm" ? value.db : value.path).trim()
    || !!registrationSheetError(value);
}
