/** Recovery from content choices that the current template cannot offer. */
import { createElement } from "react";
import type { ReactNode } from "react";
import type { EditorEntryPort } from "./ports.ts";

export function openJobInEditor(entry: EditorEntryPort, name: string | undefined, context: Record<string, unknown>): Promise<boolean> {
  if (!name) return Promise.resolve(false);
  return Promise.resolve(entry.openGuarded(name, context) as boolean);
}

export function openTemplateRepairInEditor(entry: EditorEntryPort, name?: string): Promise<boolean> {
  return openJobInEditor(entry, name, {
    entry_reason: "document_browser_repair", section: "template", return_context: { surface: "job" },
  });
}

export function TemplateRepairButton(props: {
  blockers: unknown; busy: boolean; onOpen: () => void;
}): ReactNode {
  if (!Array.isArray(props.blockers) || !props.blockers.includes("REPAIR_TEMPLATE")) return null;
  return createElement("button", {
    className: "btn", id: "jobRepairTemplate", type: "button", disabled: props.busy,
    onClick: props.onOpen,
  }, "수정…");
}
