import { createElement, useState } from "react";
import type { ReactNode } from "react";

import type { BridgeClient } from "../runtime/client.ts";
import { expectHostValue } from "./runtime.ts";

type Action = "open" | "reveal" | "copy";

const LABEL: Record<Action, string> = {
  open: "열기",
  reveal: "폴더에서 보기",
  copy: "경로 복사",
};

function icon(action: Action | "done"): ReactNode {
  const common = { viewBox: "0 0 20 20", "aria-hidden": "true", focusable: "false" };
  if (action === "open") {
    return createElement("svg", common,
      createElement("path", { d: "M11 3h6v6M17 3l-8 8" }),
      createElement("path", { d: "M15 11v5H4V5h5" }));
  }
  if (action === "reveal") {
    return createElement("svg", common,
      createElement("path", { d: "M2.5 6.5h6l1.5 2h7.5v7.5h-15z" }),
      createElement("path", { d: "M2.5 6.5v-2h5l1.5 2" }));
  }
  if (action === "copy") {
    return createElement("svg", common,
      createElement("rect", { x: "7", y: "7", width: "9", height: "9", rx: "1" }),
      createElement("path", { d: "M5 13H4V4h9v1" }));
  }
  return createElement("svg", common, createElement("path", { d: "M4 10l4 4 8-9" }));
}

export function PathActions(props: {
  client: BridgeClient;
  path?: string | null;
  only?: readonly Action[];
  labels?: boolean;
  notify: (message: string) => void;
}): ReactNode {
  const { client, notify } = props;
  const path = props.path ?? "";
  const [copied, setCopied] = useState(false);
  if (path === "") return null;
  const actions = props.only ?? ["open", "reveal"];

  async function run(action: Action): Promise<void> {
    try {
      const method = action === "open" ? "open_path" : action === "reveal" ? "reveal_path" : "copy_path";
      expectHostValue(await client.invoke(method, path), `${LABEL[action]} 실패`);
      if (action === "copy") {
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }
    } catch (error) {
      notify(String((error as { message?: unknown } | null)?.message ?? error));
    }
  }

  return createElement(
    "span",
    { className: "track-affords", title: path },
    ...actions.map((action) => {
      const done = action === "copy" && copied;
      const label = done ? "복사됨" : LABEL[action];
      return createElement(
        "button",
        {
          key: action,
          type: "button",
          className: "btn sm icon track-btn",
          "data-track-act": action,
          "data-path": path,
          title: done ? label : `${label} — ${path}`,
          "aria-label": label,
          onClick: () => { void run(action); },
        },
        icon(done ? "done" : action),
        props.labels ? label : null,
      );
    }),
  );
}
