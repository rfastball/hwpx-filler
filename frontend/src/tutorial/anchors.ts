/* Tutorial anchors: one key names one real product control (#1127). The host names the key and, where a
 * control repeats, its parameter (file, field, column, job, slot or sheet); this table only locates it.
 * Every selector is a single selector: the first match is the control, never a fallback to a wider area. */

export const ANCHORS: Readonly<Record<string, string>> = Object.freeze({
  "new-job": "#libraryNewWork",
  "library-row": "#libraryList button[data-work='{arg}']",
  "library-use": "#libraryDetail [data-use]",
  "library-edit": "#libraryDetail [data-edit]",
  "template-row": "#editorTplList .pitem[data-path$='{arg}']",
  "template-more": "#editorTplList .pitem-wrap:has(.pitem[data-path$='{arg}']) button[data-act='lib-more']",
  "data-row": "#editorDataList .pitem[data-key='{arg}']",
  "data-browse": "#editorPoolBrowse",
  "editor-next": "#editor-foot button[data-act='next']",
  "editor-tab": "#editor-steps button[data-act='goto-tab'][data-section='{arg}']",
  "map-confirm": "#editor-body table.map tr[data-field='{arg}'] button[data-act='row-confirm']",
  "map-source": "#editor-body table.map tr[data-field='{arg}'] select[data-act='row-source']",
  "map-format": "#editor-body table.map tr[data-field='{arg}'] select[data-act='row-fmt']",
  "map-slice": "#editor-body table.map tr[data-field='{arg}'] [data-act='row-slice']",
  "slice-sample": ".slicepop input[data-slice-value]",
  "slice-done": ".slicepop button[data-act='slice-done']",
  "preview-next": "#editor-body button[data-act='next-rec']",
  "binding-more": "#editor-body button[data-act='binding-more']",
  "menu-item": ".ctx-menu [data-context-menu-action='{arg}']",
  "confirm-all": "#editor-body button[data-act='confirm-suggested']",
  "filename-pattern": "#editor-body input[data-act='pattern']",
  "save-and-open": "#editor-foot button[data-act='save-and-open']",
  "dialog-confirm": "#confirmModalOk",
  "sheet-check": "#sheetList input[data-sheet='{arg}']",
  "sheet-import": "#sheetImport",
  "filter-chip": "#jobFilterChips button[data-preset='{arg}']",
  "row-selection": "#jobSelAll",
  "slot-options": "#jobContentSelectionZone .cs-options[aria-label='{arg}']",
  "delivery-plan": "#jobDeliveryZone",
  generate: "#jobManagedCreate",
  "result-open": "#jobResultDocs button[data-act='artifact-open']",
  results: "#jobResult",
  "data-label": "#jobDataLabel",
  "open-workbench": "#jobGenBtn",
  "wb-copy": "#wbCopy",
  "wb-next": "#wbNext",
  "wb-blank": "#wbCard .seg-blank[data-token='{arg}']",
  "wb-declared": "#wbCard .seg-declared[data-token='{arg}']",
  "txt-review": "#wbCard",
  "authoring-range": "#authoring-canvas .cm-tutorial-range",
  "create-command": ".authoring-toolbar button[data-rove='{arg}']",
  "property-name": "[data-guide='property-name']",
  "trial-toggle": ".authoring-toolbar-end button[aria-pressed]",
  "trial-fill-names": "[data-guide='trial-fill-names']",
  "trial-slot": "[data-guide='trial-slot'][data-slot='{arg}']",
  "save-template": "[data-guide='save-template']",
  "impact-tab": "#authoring-dock-tab-impact",
  "apply-check": "[data-guide='apply-check']",
  "apply-confirm": "[data-guide='apply-confirm']",
  "nav-job": ".navbtn[data-scr='job']",
});

/** A quoted CSS attribute value: only the backslash and the quote need escaping. */
function quoted(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

/** The selector of `key` with its parameter filled in; null for an unknown key or a missing parameter. */
export function anchorSelector(key: string | null, arg = ""): string | null {
  const selector = key ? ANCHORS[key] : undefined;
  if (!selector) return null;
  if (!selector.includes("{arg}")) return selector;
  return arg ? selector.split("{arg}").join(quoted(arg)) : null;
}

/** Anchors that box a painted text range rather than one control: the range spans several elements (one per
 *  line), so the box is the union of every visible match. */
export const SPAN_ANCHORS: ReadonlySet<string> = new Set(["authoring-range"]);
