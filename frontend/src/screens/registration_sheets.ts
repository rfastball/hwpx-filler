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

const MISSING_DEFAULT = "기본 시트를 찾을 수 없습니다. 계약 목록 파일을 확인하세요.";

export function missingPclmDefault(value: State): boolean {
  return value.mode === "pclm" && !!value.targetKey
    && !value.availableSheets.some((sheet) => sheet.name === value.view);
}

function primarySheet(value: State, sheets: string[]): string {
  const initial = (value.mode === "pclm" ? value.view : value.sheet).trim();
  return value.mode === "pclm" && value.targetKey ? initial
    : sheets.includes(initial) ? initial : sheets[0] || "";
}

export function inspectedRegistrationSheets(value: State, availableSheets: Sheet[], path: string) {
  const sheets = value.sheets.filter((name) => availableSheets.some((sheet) => sheet.name === name));
  const initial = (value.mode === "pclm" ? value.view : value.sheet).trim();
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
  return { sheets, ...(value.mode === "pclm" ? { view: primary } : { sheet: primary }), error: "" };
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
