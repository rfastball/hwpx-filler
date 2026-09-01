/* 창 포커스 복귀가 현재 화면을 **다시 묻는다**(#932 B5).
 *
 * 「템플릿 조치 필요」 존이 조치가 있을 때만 서게 된 뒤로, 앱 밖에서 일어난 변화 —
 * 한글에서 템플릿을 고치는 것이 정확히 그것이다 — 는 push 를 내지 않으므로 다음 상호작용
 * 까지 화면이 옛 판을 든다. 주기 검사가 아니라 **사용자가 돌아온 순간** 한 번이라 유휴
 * 비용이 0 이고, 그 갱신을 놓쳐도 실행 게이트가 드리프트를 blocker 로 잡는다(두 층).
 *
 * 리스너는 여기서 **부착되지 않는다** — adapter 는 서술만 캡처하고 수명은 ShellHost 가
 * 진다(R3-02). 그래서 이 테스트도 서술 목록을 읽고 핸들러를 직접 부른다.
 */
import test from "node:test";
import assert from "node:assert/strict";

async function withShellGlobals(run) {
  const priorDocument = globalThis.document;
  const priorWindow = globalThis.window;
  globalThis.document = {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    body: { classList: { add() {}, remove() {} } },
  };
  globalThis.window = { addEventListener() {}, removeEventListener() {}, alert() {} };
  try {
    return await run();
  } finally {
    globalThis.document = priorDocument;
    globalThis.window = priorWindow;
  }
}

function buildShell(refreshScreen, currentScreen = "job") {
  return withShellGlobals(async () => {
    const { createAppShell } = await import("../../frontend/src/shell/app.ts");
    return createAppShell({
      Bridge: {
        hostReady: () => false,
        confirmWindowClose: () => Promise.resolve(null),
        cancelWindowClose: () => Promise.resolve(null),
      },
      /* 셸이 아는 modal 포트는 둘이다 — 종료 확인(confirm)과 설정 모달 개폐(open).
         테마·개인화 값 선택은 셸 인자가 아니라 설정 모달 컴포넌트의 주입으로 옮겨갔다. */
      modal: { confirm: () => Promise.resolve(true), open() {} },
      Personalization: {
        currentFontScale: () => "normal",
        setMasterWidth() {},
        saveMasterWidth() {},
        masterMin: 200,
        masterMax: 480,
      },
      shellNav: {
        go() {},
        refresh() {},
        currentScreen: () => currentScreen,
        beginClosePrompt: () => true,
        endClosePrompt() {},
      },
      initSequence: [],
      refreshScreen,
    });
  });
}

function focusHandlers(shell) {
  return shell.shellHost.attachments
    .filter((a) => a.type === "focus")
    .map((a) => a.handler);
}

test("창으로 돌아오면 현재 화면을 다시 묻는다", async () => {
  const asked = [];
  const shell = await buildShell((screen) => {
    asked.push(screen);
    return Promise.resolve(null);
  });

  const handlers = focusHandlers(shell);
  assert.equal(handlers.length, 1, "포커스 복귀 갱신 서술이 없습니다(또는 중복입니다).");
  handlers[0](new Event("focus"));
  assert.deepEqual(asked, ["job"], "현재 화면이 아니라 다른 화면을 물었습니다.");
});

test("갱신 실패는 셸을 무너뜨리지 않는다 — 편의이지 계약이 아니다", async () => {
  const shell = await buildShell(() => Promise.reject(new Error("bridge down")));
  const handlers = focusHandlers(shell);
  // 던지면 unhandledrejection 백스톱이 alert 를 띄운다 — 돌아왔다는 이유로 경보가 뜨면
  // 그것이 곧 과경고다. 삼키는 자리가 여기 하나뿐이라 여기서 못박는다.
  assert.doesNotThrow(() => handlers[0](new Event("focus")));
  await new Promise((resolve) => setImmediate(resolve));
});

test("아직 아무 화면도 안 섰으면 묻지 않는다", async () => {
  const asked = [];
  const shell = await buildShell((screen) => {
    asked.push(screen);
    return Promise.resolve(null);
  }, null);
  focusHandlers(shell)[0](new Event("focus"));
  assert.deepEqual(asked, [], "물을 대상이 없는데 물었습니다.");
});

test("포커스 갱신은 지금 선 화면을 따라간다", async () => {
  const asked = [];
  const shell = await buildShell((screen) => {
    asked.push(screen);
    return Promise.resolve(null);
  }, "library");
  focusHandlers(shell)[0](new Event("focus"));
  assert.deepEqual(asked, ["library"]);
});
