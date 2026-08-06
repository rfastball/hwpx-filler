/* 한 React root 안의 화면 portal registry. target identity·중복 owner·static child 잔존을
   mount 전에 fail-closed로 검사하고, 별 createRoot 없이 createPortal만 사용한다. */
import { createElement, useMemo } from "react";
import type { ReactNode } from "react";
import type { ComponentType } from "react";
import { createPortal } from "react-dom";

export type ScreenPortal = { targetId: string; content: ReactNode };

/** 합성 루트가 React bare import 없이 portal 서술을 만들게 하는 경계 factory. */
export function screenPortal<P extends object>(
  targetId: string,
  component: ComponentType<P>,
  props: P,
): ScreenPortal {
  return { targetId, content: createElement(component, props) };
}

export type ScreenMigrationHostPorts = {
  doc: Document;
  portals: readonly ScreenPortal[];
};

export function resolvePortalTargets(
  doc: Document,
  portals: readonly ScreenPortal[],
): ReadonlyArray<{ target: Element; content: ReactNode }> {
  const ids = new Set<string>();
  return portals.map((portal) => {
    if (ids.has(portal.targetId)) {
      throw new Error(`React 화면 portal target이 중복됐습니다: #${portal.targetId}`);
    }
    ids.add(portal.targetId);
    const target = doc.getElementById(portal.targetId);
    if (target === null) {
      throw new Error(`React 화면 portal target이 없습니다: #${portal.targetId}`);
    }
    if (target.childNodes.length !== 0) {
      throw new Error(`React 화면 portal target에 static child가 남았습니다: #${portal.targetId}`);
    }
    return { target, content: portal.content };
  });
}

export function ScreenMigrationHost(ports: ScreenMigrationHostPorts): ReactNode {
  const targets = useMemo(
    () => resolvePortalTargets(ports.doc, ports.portals),
    [ports.doc, ports.portals],
  );
  return createElement(
    "div",
    { id: "reactScreenStage", hidden: true, "aria-hidden": "true" },
    ...targets.map((entry, index) => createPortal(entry.content, entry.target, `screen-${index}`)),
  );
}
