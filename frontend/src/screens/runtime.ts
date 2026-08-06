/* R4 화면 런타임 — raw snapshot store와 React 제품 화면 사이의 유일한 해석 경계.

   store는 전송-충실이라 full/delta를 해석하지 않는다. 화면 런타임만 job의 progress delta를
   `{full, progress}`로 보관하고, initial pull은 시작 revision을 함께 실어 intervening push를
   덮지 않는다. 채널 init은 멱등·동시 공유이며 실패 뒤 다음 명시 호출이 재시도한다. */
import type { ScreenName } from "../contract/contract.gen.ts";
import type { BridgeClient } from "../runtime/client.ts";
import type { HostResult } from "../runtime/adapter.ts";
import type { SnapshotListener, SnapshotStore } from "../state/store.ts";

export type JobScreenModel = { full: unknown; progress: unknown };

export type ScreenModel<T = unknown> = {
  getSnapshot(): T;
  subscribe(listener: SnapshotListener): () => void;
};

export function expectHostValue(result: HostResult, label: string): unknown {
  if (result === null || typeof result !== "object" || typeof result.ok !== "boolean") {
    throw new Error(`${label}: 호스트 결과가 손상되었습니다.`);
  }
  if (!result.ok) {
    throw new Error(`${label}: ${result.failure.message}`);
  }
  return result.value;
}

type MutableModel = {
  value: unknown;
  listeners: Set<SnapshotListener>;
  subscribeBound: (listener: SnapshotListener) => () => void;
};

function isProgressDelta(value: unknown): value is { progress: unknown } {
  return value !== null && typeof value === "object"
    && Object.hasOwn(value, "progress");
}

export function createScreenRuntime(args: { client: BridgeClient; store: SnapshotStore }) {
  const { client, store } = args;
  const models = new Map<ScreenName, MutableModel>();
  const releases = new Map<ScreenName, () => void>();
  const initials = new Map<ScreenName, Promise<unknown>>();

  function notify(model: MutableModel): void {
    for (const listener of [...model.listeners]) listener();
  }

  function reduce(screen: ScreenName, previous: unknown, delivery: unknown): unknown {
    if (screen !== "job") return delivery;
    const before = previous as JobScreenModel;
    if (isProgressDelta(delivery)) {
      return { full: before.full, progress: delivery.progress } satisfies JobScreenModel;
    }
    return { full: delivery, progress: null } satisfies JobScreenModel;
  }

  function ensure(screen: ScreenName): MutableModel {
    const existing = models.get(screen);
    if (existing !== undefined) return existing;
    const model: MutableModel = {
      value: screen === "job" ? { full: null, progress: null } : null,
      listeners: new Set(),
      subscribeBound: () => { throw new Error("screen model subscribe가 초기화되지 않았습니다."); },
    };
    model.subscribeBound = (listener) => {
      if (typeof listener !== "function") throw new TypeError("screen model 구독자가 함수가 아닙니다.");
      model.listeners.add(listener);
      let alive = true;
      return () => {
        if (!alive) throw new Error("screen model 구독은 정확히 한 번 해제해야 합니다.");
        alive = false;
        model.listeners.delete(listener);
      };
    };
    const ingest = (): void => {
      model.value = reduce(screen, model.value, store.get(screen));
      notify(model);
    };
    releases.set(screen, store.subscribe(screen, ingest));
    /* runtime 구성 전에 도착한 push도 현재 store 값으로 따라잡는다. null은 미도착 표지다. */
    if (store.get(screen) !== null) ingest();
    models.set(screen, model);
    return model;
  }

  function model<T = unknown>(screen: ScreenName): ScreenModel<T> {
    const channel = ensure(screen);
    return {
      getSnapshot: () => channel.value as T,
      subscribe: channel.subscribeBound,
    };
  }

  function loadInitial(screen: ScreenName): Promise<unknown> {
    ensure(screen);
    const pending = initials.get(screen);
    if (pending !== undefined) return pending;
    const sinceRevision = store.revision(screen);
    const started = client.initial(screen)
      .then((result) => {
        const value = expectHostValue(result, `${screen} initial`);
        store.ingestPulled(screen, value, sinceRevision);
        return value;
      })
      .catch((error) => {
        initials.delete(screen);
        throw error;
      });
    initials.set(screen, started);
    return started;
  }

  /* 재당김(R4-02) — `loadInitial` 은 화면당 **한 번**을 기억하는 부팅 당김이라 두 번째
     호출이 다시 묻지 않는다. 편집기는 그것으로 부족하다: tpl 관리 동사가 목록을 바꾸면
     Python 은 `tpl` 채널을 밀고, editor 스냅샷은 **다시 물어야** 최신이 된다(legacy
     `Bridge.initial(SCREEN).then(render)` 의 후계). 같은 ingest 경로·같은 revision 가드를
     쓰므로 늦게 도착한 당김이 그사이 온 push 를 덮지 않는다. */
  function refresh(screen: ScreenName): Promise<unknown> {
    ensure(screen);
    const sinceRevision = store.revision(screen);
    return client.initial(screen).then((result) => {
      const value = expectHostValue(result, `${screen} initial`);
      store.ingestPulled(screen, value, sinceRevision);
      return value;
    });
  }

  return {
    model,
    loadInitial,
    refresh,
    listenerCount(screen: ScreenName): number {
      return ensure(screen).listeners.size;
    },
    dispose(): void {
      for (const release of releases.values()) release();
      releases.clear();
      models.clear();
      initials.clear();
    },
  };
}

export type ScreenRuntime = ReturnType<typeof createScreenRuntime>;
