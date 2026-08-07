/* 화면 전환 수명주기 registry — 판정은 shell/nav.ts, 실제 owner 호출만 이 표가 잇는다.

   몰입 이탈 owner는 editor/workbench 정확히 둘이다. 등록되지 않은 일반 화면은 false로
   fallthrough하지만, owner를 해제한 뒤 다시 호출하는 것은 죽은 owner 사용이므로 loud하다. */

export const SCREEN_LIFECYCLE_OWNER_IDS = Object.freeze(["editor", "workbench"] as const);

export type ScreenLifecycleOwnerId = typeof SCREEN_LIFECYCLE_OWNER_IDS[number];

export type ScreenLifecycleOwner = {
  leaveTo(to: string): unknown;
  rerender?(): unknown;
};

export function createScreenLifecycleRegistry() {
  const allowed = new Set<string>(SCREEN_LIFECYCLE_OWNER_IDS);
  const owners = new Map<ScreenLifecycleOwnerId, ScreenLifecycleOwner>();
  const released = new Set<ScreenLifecycleOwnerId>();

  function assertAlive(id: ScreenLifecycleOwnerId): void {
    if (released.has(id)) {
      throw new Error(`화면 수명주기 owner가 해제된 뒤 호출됐습니다: ${id}`);
    }
  }

  return {
    register(id: ScreenLifecycleOwnerId, owner: ScreenLifecycleOwner): () => void {
      if (!allowed.has(id)) throw new Error(`화면 수명주기 owner 집합 밖 등록입니다: ${id}`);
      if (owners.has(id) || released.has(id)) {
        throw new Error(`화면 수명주기 owner가 중복 등록됐습니다: ${id}`);
      }
      owners.set(id, owner);
      let active = true;
      return () => {
        if (!active) throw new Error(`화면 수명주기 owner를 두 번 해제했습니다: ${id}`);
        active = false;
        owners.delete(id);
        released.add(id);
      };
    },

    delegateLeave(from: string, to: string): boolean {
      if (!allowed.has(from)) return false;
      const id = from as ScreenLifecycleOwnerId;
      assertAlive(id);
      const owner = owners.get(id);
      if (owner === undefined) {
        throw new Error(`화면 수명주기 owner가 결속되지 않았습니다: ${id}`);
      }
      owner.leaveTo(to);
      return true;
    },

    rerender(id: string): boolean {
      if (!allowed.has(id)) return false;
      const ownerId = id as ScreenLifecycleOwnerId;
      assertAlive(ownerId);
      const owner = owners.get(ownerId);
      if (owner === undefined) {
        throw new Error(`화면 수명주기 owner가 결속되지 않았습니다: ${ownerId}`);
      }
      if (owner.rerender === undefined) return false;
      owner.rerender();
      return true;
    },

    ownerIds(): readonly ScreenLifecycleOwnerId[] {
      return SCREEN_LIFECYCLE_OWNER_IDS.filter((id) => owners.has(id));
    },
  };
}

export type ScreenLifecycleRegistry = ReturnType<typeof createScreenLifecycleRegistry>;
