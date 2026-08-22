/* 화면 전환 집행자의 **초점 복원** 경계(#795).

   이 파일이 지는 것 하나: 들어오는 화면이 이미 자기 안에 초점을 세웠으면 전환이 그것을
   빼앗지 않는다. 나머지(가시성·스크롤 기억·셸 marker)는 이 슬라이스가 소유하지 않는다. */
import test from "node:test";
import assert from "node:assert/strict";

import { createProductScreenExecutor } from "../../frontend/src/screens/product_screen_executor.ts";

const SCREEN_IDS = ["job", "library", "editor", "workbench"];

function element(id, { focusable = true } = {}) {
  const node = {
    id,
    isConnected: true,
    children: [],
    dataset: {},
    scrollTop: 0,
    scrollLeft: 0,
    classList: { toggle() {}, add() {}, remove() {} },
    setAttribute() {},
    closest: () => null,
    querySelectorAll: () => ({ forEach() {} }),
    focus() { if (focusable) node.doc.activeElement = node; },
  };
  node.contains = (other) => other === node || node.children.includes(other);
  return node;
}

function harness({ activeIn = null, claimDuringCommit = null } = {}) {
  const stage = element("stage");
  const roots = new Map(SCREEN_IDS.map((id) => [id, element(`scr-${id}`)]));
  const doc = {
    activeElement: null,
    body: { classList: { toggle() {} } },
    querySelector: (selector) => (selector === "main.stage" ? stage : null),
    querySelectorAll: () => ({ forEach() {} }),
    getElementById: (id) => {
      for (const [screen, root] of roots) if (`scr-${screen}` === id) return root;
      return null;
    },
  };
  for (const root of roots.values()) root.doc = doc;
  if (activeIn !== null) {
    const holder = element("focus-holder");
    holder.doc = doc;
    roots.get(activeIn).children.push(holder);
    doc.activeElement = holder;
  }
  let current = "job";
  const claimed = element("claimed-by-incoming");
  claimed.doc = doc;
  const executor = createProductScreenExecutor({
    doc,
    bridge: { hostReady: () => false, call: async () => null },
    visibility: {
      getSnapshot: () => current,
      activate: (id) => {
        current = id;
        // 목적 화면이 commit 중에 자기 자리를 겨눈다(deep-link 조준의 실제 시점).
        if (claimDuringCommit === id) {
          roots.get(id).children.push(claimed);
          doc.activeElement = claimed;
        }
      },
    },
    lifecycle: { delegateLeave: () => false },
    reclaimSurfaces() {},
    notify() {},
  });
  return { executor, doc, roots, claimed };
}

test("#795 들어오는 화면이 이미 자기 안에 초점을 세웠으면 전환이 빼앗지 않는다", () => {
  // deep-link 진입이 그 형상이다: 목적 화면이 지목된 자리를 겨눈 **뒤** 전환이 마무리된다.
  // 여기서 덮으면 사용자가 방금 지목한 자리를 화면 루트가 가져간다.
  const h = harness({ activeIn: "job", claimDuringCommit: "editor" });

  h.executor.applyScreen("editor");

  assert.equal(h.doc.activeElement, h.claimed, "전환이 목적 화면의 조준을 빼앗았습니다");
});

test("#795 나가는 화면이 초점을 들고 있었으면 들어오는 화면 루트가 받는다", () => {
  // 음성 대조 — 기존 계약을 약화시키지 않는다. 초점이 고아가 되면 시작점을 준다.
  const h = harness({ activeIn: "job" });

  h.executor.applyScreen("editor");

  assert.equal(h.doc.activeElement, h.roots.get("editor"), "초점이 고아가 된 채 남았습니다");
});
