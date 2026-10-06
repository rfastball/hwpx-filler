/* 「파일 찾아보기…」 한 입구의 응답 해석 — 데이터 선택 면과 편집기가 한 벌로 쓴다.

   Python `pick_data_file` 의 응답은 넷 중 하나다: 취소(`null`), 실패(`ERROR:` 문자열), 다중 시트
   확정 요구(`needs_sheet`), 계약 목록 파일의 등록 갈래(`contract_list` — `.db`·`.pclm` 은 시트를
   사람이 골라 등록해야 쓴다). 어느 갈래인지는 Python 이 판정하고 여기는 그 표지를 옮길 뿐
   확장자를 보지 않는다. 두 입구가 각자 풀면 한쪽만 새 갈래를 모르는 채 늙는다. */
import type { SheetPickerPort } from "../ports/service_handoff.ts";

type Obj = Record<string, any>;

export type DataFilePick =
  | { kind: "mounted"; value: Obj }
  | { kind: "error"; message: string }
  | { kind: "sheet_cancelled" }
  /** 대화상자 취소이거나 등록 폼으로 넘겼다 — 지금 데이터는 그대로다. */
  | { kind: "none" };

/** 응답 객체가 그 갈래 표지를 들었는가(문자열·`null` 응답은 표지가 없다). */
function marked(result: unknown, key: "contract_list" | "needs_sheet"): result is Obj {
  return typeof result === "object" && result !== null && Boolean((result as Obj)[key]);
}

export async function pickDataFile(
  invoke: (method: "pick_data_file", screen: string) => Promise<unknown>,
  screen: string,
  ports: { sheetPicker: SheetPickerPort; openContractList(db: string): void },
): Promise<DataFilePick> {
  let result = (await invoke("pick_data_file", screen)) as any;
  if (marked(result, "contract_list")) {
    ports.openContractList(String(result.path ?? ""));
    return { kind: "none" };
  }
  if (marked(result, "needs_sheet")) {
    result = await ports.sheetPicker.choose(screen, result);
    if (result === null) return { kind: "sheet_cancelled" };
  }
  if (!result) return { kind: "none" };
  if (typeof result === "string" && result.startsWith("ERROR:")) {
    return { kind: "error", message: result.slice(6).trim() };
  }
  return { kind: "mounted", value: result };
}
