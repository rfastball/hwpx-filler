/* 계약 목록 등록 진입 되읽기(#937) — `editor_workbench_data.js` 의 데이터 선택 프로브가 부른다.
 *
 * 그 클러스터 모듈은 프로브 정의만 들고, 등록 폼 하나를 재는 잔 단계는 여기 둔다(응집 단위 분리).
 * DOM 헬퍼는 호출자가 넘긴다 — 같은 헬퍼를 두 벌 두지 않는다. 이 모듈은 **비활성**이다: import
 * 만으로는 DOM 을 만지지 않는다 — 전부 호출 시점에 일어난다. */

/** 파일 피커가 없는 종류라 전용 동사가 「다른 데이터」에 선다. 가시성까지 단언한다(click 은
 *  hidden 도 통과). 열린 폼은 pclm 모드로 DB 자리를 **비운 채** 열리고(다른 프로그램의 설치
 *  자리를 추측하지 않는다), 사용자가 적은 자리를 백엔드가 나열하면 **미선택 시트 목록** 을
 *  세운다(시트는 사용자 확정). 라벨에 저쪽 프로그램 이름이 서지 않는 것도 같이 되읽는다. */
export async function probePclmRegistration(ctx, { byId, isHidden, textOf, typeValue }) {
  const out = {};
  const pclmEntry = byId(ctx, "dataPickerPclm");
  out.pclm_entry = !!pclmEntry && !isHidden(ctx, pclmEntry)
    && pclmEntry.offsetParent !== null && !pclmEntry.disabled;
  out.pclm_entry_text = textOf(pclmEntry);
  pclmEntry.click();
  await ctx.sleep(0);                      // regModel → 등록 portal DOM 커밋
  const dbInput = byId(ctx, "poolRegDb");
  const sheetList = () => Array.from(
    byId(ctx, "poolRegView").querySelectorAll(".pool-reg-sheet-list input"));
  out.pclm_reg_db_prefill = dbInput.value;
  out.pclm_reg_no_sheets_before_db = sheetList().length === 0;
  /* 사용자가 DB 자리를 적고 칸을 떠나면 그 자리에서 시트를 나열한다(호출자의 inspect 대역). */
  dbInput.focus();
  typeValue(ctx, dbInput, "C:/d/pclm.db");
  dbInput.blur();
  for (let i = 0; i < 50 && sheetList().length === 0; i += 1) await ctx.sleep(10);
  const viewSelect = byId(ctx, "poolRegView");
  const sheetInputs = sheetList();
  out.pclm_reg_view_options = sheetInputs.length;
  out.pclm_reg_view_text = sheetInputs.map((input) => textOf(input.nextElementSibling)).join("|");
  out.pclm_reg_view_label = textOf(viewSelect.querySelector("legend"));
  out.pclm_reg_initial_empty = sheetInputs.every((input) => !input.checked)
    && byId(ctx, "poolRegOk").disabled;
  sheetInputs[0].click();
  await ctx.sleep(0);
  sheetInputs[1].click();
  await ctx.sleep(0);
  out.pclm_reg_multiple_selected = viewSelect.querySelectorAll(".pool-reg-sheet-list input:checked").length === 2
    && !byId(ctx, "poolRegOk").disabled;
  return out;
}
