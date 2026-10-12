/* 등록 폼은 공용 상태 계약을 렌더한다. 처리와 파일 검사는 data_picker controller가 소유한다. */
import { createElement, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import type { DataPickerController } from "./data_picker.ts";
import { newRegistrationState, registrationSubmitDisabled } from "./registration_sheets.ts";
import type { RegState } from "./registration_sheets.ts";

type Obj = Record<string, any>;
function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

function sheetChoice(value: RegState, controller: DataPickerController, sheet: { name: string }): ReactNode {
  return h("label", { className: "pool-reg-sheet", key: sheet.name },
    h("input", { type: "checkbox", checked: value.sheets.includes(sheet.name),
      disabled: value.mode === "pclm" && !!value.targetKey && sheet.name === value.view,
      onChange: (event: Obj) => controller.selectRegSheets(event.currentTarget.checked
        ? [...value.sheets, sheet.name] : value.sheets.filter((name) => name !== sheet.name)) }),
    h("span", null, sheet.name));
}

function sheetSelector(value: RegState, controller: DataPickerController): ReactNode {
  const pclm = value.mode === "pclm";
  if (!pclm && value.inspectedPath && value.availableSheets.length === 0) return null;
  return h("fieldset", {
    className: "pool-reg-sheets", id: pclm ? "poolRegView" : "poolRegSheet",
    disabled: value.inspecting || value.submitting,
  }, h("legend", { className: "lbl" }, "사용할 시트"),
  value.availableSheets.length > 0 ? h("div", { className: "pool-reg-sheet-head" },
    h("label", { className: "pool-reg-sheet pool-reg-sheet-all" },
    h("input", { type: "checkbox", checked: value.sheets.length === value.availableSheets.length,
      ref: (input: HTMLInputElement | null) => {
        if (input) input.indeterminate = value.sheets.length > 0 && value.sheets.length < value.availableSheets.length;
      },
      onChange: (event: Obj) => controller.selectRegSheets(event.currentTarget.checked
        ? value.availableSheets.map((sheet) => sheet.name) : []) }),
    h("span", null, "전체 선택")),
    h("span", { className: "pool-reg-sheet-count" }, `${value.sheets.length}개 시트 선택`)) : null,
  h("div", { className: "pool-reg-sheet-list" }, ...value.availableSheets.map((sheet) => sheetChoice(value, controller, sheet))),
  value.inspecting ? h("p", { className: "capnote", role: "status" }, "읽는 중…") : null,
  value.sheets.length === 0 && !value.inspecting ? h("p", { className: "capnote" }, "읽을 시트를 고르세요.") : null);
}

export function PoolRegistrationDialog(props: { controller: DataPickerController }): ReactNode {
  const { controller } = props;
  const state = useSyncExternalStore(
    controller.regModel.subscribe, controller.regModel.getSnapshot,
    controller.regModel.getSnapshot);
  const value = state || newRegistrationState({});
  const pclm = value.mode === "pclm";
  return h("div", { className: "modal-card pool-registration", "aria-busy": value.inspecting || value.submitting },
    h("h3", { id: "poolRegTitle" }, value.title),
    h("div", { className: "pool-registration-body" },
    pclm ? null : h("label", { className: "ctl" }, h("span", { className: "lbl" }, "파일 경로(.xlsx/.csv)"),
      h("span", { className: "row" }, h("input", { className: "field mono spacer", id: "poolRegPath", type: "text",
        value: value.path, readOnly: value.pinMode, disabled: value.submitting,
        onBlur: () => { void controller.inspectRegSheets(); },
        onChange: (event: Obj) => controller.patchReg({ path: event.currentTarget.value }) }),
      h("button", { className: "btn", id: "poolRegBrowse", type: "button", hidden: value.pinMode,
        disabled: value.submitting,
        onClick: () => { void controller.browseRegPath(); } }, "찾아보기…"))),
    pclm ? h("label", { className: "ctl" }, h("span", { className: "lbl" }, "DB 자리"),
      h("input", { className: "field mono", id: "poolRegDb", type: "text", value: value.db,
        readOnly: !!value.targetKey, disabled: value.submitting,
        onBlur: () => { void controller.inspectRegSheets(); },
        onChange: (event: Obj) => controller.patchReg({ db: event.currentTarget.value }) })) : null,
    h("label", { className: "ctl" }, h("span", { className: "lbl" }, "이름"),
      h("input", { className: "field", id: "poolRegName", type: "text", value: value.name, disabled: value.submitting,
        placeholder: "예: 7월 공고목록", onChange: (event: Obj) => controller.patchReg({ name: event.currentTarget.value }) })),
    sheetSelector(value, controller),
    h("label", { className: "ctl" }, h("span", { className: "lbl" }, "메모(선택)"),
      h("input", { className: "field", id: "poolRegNote", type: "text", value: value.note, disabled: value.submitting,
        onChange: (event: Obj) => controller.patchReg({ note: event.currentTarget.value }) })),
    h("p", { className: "note dangerbox", role: "alert", style: { display: value.error ? "" : "none" } }, value.error)),
    h("div", { className: "modal-actions" },
      h("button", { className: "btn", id: "poolRegCancel", onClick: controller.closeReg }, "취소"),
      h("button", { className: "btn primary", id: "poolRegOk",
        disabled: registrationSubmitDisabled(value),
        onClick: () => { void controller.submitReg(); } }, value.okLabel)));
}
