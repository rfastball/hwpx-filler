/* 앱 셸 상태기계 (R3-02 · #411) — 라우팅·ready 게이트·재당김 규약·닫기 직렬화 **판정**의 단일 정본.
 *
 * 구 앱 셸이 혼자 들던 셸 판정(현재 화면·몰입 이탈 위임·기본 랜딩·전환 자동 재당김·종료 확인
 * 단일 실행)을 여기로 올린다. 판정이 legacy 팩토리와 React 층으로 갈리면 같은 상태의 두
 * 판정자가 된다(제품 규칙 위반) — 그래서 판정은 이 기계 하나이고, DOM **집행**(클래스·속성
 * 토글·브리지 발신·재진술)은 집행자 포트(shell/app.ts adapter)가 진다. overlay 엔진
 * (`overlay/engine.ts`)과 같은 절취선이다.
 *
 * ## 정본 이동 — DEFAULT_SCREEN·REFRESH_ON_NAV·IMMERSIVE_SURFACES
 *
 * 세 목록의 정본이 구 앱 셸에서 이 파일로 옮겨 왔다(패킷 §4.3). 몰입 표면의 body 클래스는
 * 판정 데이터가 아니라 집행 좌표지만, 목록을 둘로 쪼개면 「새 몰입 표면은 한 줄」(F6)이
 * 죽는다 — 그래서 id·cls 를 한 행에 두고 판정은 id 만, 집행은 두 값을 읽는다.
 *
 * ## 현재 화면은 상태다 — DOM 판독의 승계
 *
 * 구 go() 는 「몰입 표면이 켜져 있는가」를 `classList.contains("on")` 실 DOM 판독으로
 * 판정했다. 이 기계는 현재 화면을 자기 상태로 들고 DOM 은 그 투영이다 — 판정·수치는
 * 상태기계, 표시는 집행자(같은 상태를 두 곳이 판정하지 않는다).
 *
 * ## go 는 synchronous 다 — 그 계약이 여기의 형태를 정한다
 *
 * 파사드 `Nav.go` 호출 → 이 기계의 판정 → 집행자의 DOM 기입이 **한 동기 턴**이다(반환값
 * 없음 — 비동기로 바꾸면 반환값을 무시하는 기존 호출부 전부가 조용히 순서를 잃는다).
 * React 재렌더를 경유하지 않으므로 flushSync 류 장치가 필요 없다(R3-01 host 와 같은 구조).
 *
 * ## 이 파일에 없는 것
 *
 * DOM 기입 0 · DOM 판독 0 · 전역 접촉 0 · React 접촉 0. 호스트 주입(브리지) 가용성 판독도
 * 집행자 몫이다 — 이 기계는 「ready 인가·화이트리스트인가」만 판정하고, 호스트 부재의
 * 무동작 이행 약속은 집행자가 돌려준다(#490 예약 전역 그물이 구 앱 셸 접촉을 기등재한
 * 이유이기도 하다 — 판독을 옮기면 그물이 넓어진다). 음성 게이트(shell_nav.test.js)의
 * **전역 이름** needle 은 주석까지 읽는다 — 전역 이름을 여기 표기하지 않는 것 자체가
 * 계약이다(n06 규율). React 언급은 산문이라 허용이고, React 모듈의 실행 import 만 막는다.
 *
 * ## 수명·구성
 *
 * 인스턴스는 합성 루트(`bootstrap.js`)가 정확히 하나 구성한다 — reload 는 모듈 그래프
 * 재평가 = 신품이라 store·overlay 엔진과 같은 수명이다. 구성은 부작용이 없다. 집행자
 * 결속은 adapter 구성이 정확히 1회 지고, 두 번째 결속은 throw 다(두 번째 집행자는 두 번째
 * 실행 경로 — instance.ts 다이얼로그 host 슬롯과 같은 엄격도). */

/** 콜드 부팅 랜딩 — R-info 결정 1: 작업이 중심 개체(#239). 정본은 이 상수 하나다. */
export const DEFAULT_SCREEN = "job";

/* 전환 시 자동 새로고침 대상(C6) — 다른 화면의 변경(에디터 자동등록·삭제 등)이 부팅
   스냅샷에 가려지는 고착 방지. 백엔드에 _do_refresh 가 있는 컨트롤러만 화이트리스트로
   보낸다(미지 액션은 백엔드가 loud 거절하므로 무차별 dispatch 금지). 「문서 만들기」도
   레지스트리 파생 후보·문서 탐색을 스냅샷으로 그리므로 포함한다 — 빼면 에디터에서 막
   저장한 작업이 후보에 안 보인다. */
export const REFRESH_ON_NAV: readonly string[] = Object.freeze(["library", "job"]);

export type ImmersiveSurface = { readonly id: string; readonly cls: string };

/* 몰입 표면의 **단일 목록**(F6) — 상단 2탭을 덮고(셸 표지 body 클래스는 집행자가 내린다)
   나가는 이동이 자기 이탈 가드를 먼저 지나는 화면들. 특례를 늘리면 가드의 완전성이 표면
   수에 비례한다 — 새 몰입 표면은 여기 한 줄이고, 이탈 위임 판정과 셸 은닉 집행이 자동으로
   따라온다. */
export const IMMERSIVE_SURFACES: readonly ImmersiveSurface[] = Object.freeze([
  Object.freeze({ id: "editor", cls: "editor-open" }),
  Object.freeze({ id: "workbench", cls: "workbench-open" }),
]);

/** 집행자 — 셸 판정 하나의 DOM·브리지 효과 전부. 판정은 기계가, 집행은 이쪽(shell/app.ts
 *  집행 adapter)이 진다. 어느 메서드도 판정을 재조립하지 않는다 — 재조립이 보이면 그것이
 *  경계 위반이다(패킷 §6). */
export type ShellExecutor = {
  /** 몰입 이탈 위임 집행 — 소유 화면의 `leaveTo(to)` 호출. 반환은 **위임 성립 여부**:
   *  소유 화면이 이탈 가드를 안 들면(leaveTo 부재) 위임 없이 전환을 계속한다(구 go() 의
   *  fallthrough 보존 — 가드 없는 몰입 표면이 항행을 막는 새 상태를 만들지 않는다). */
  delegateLeave(from: string, to: string): boolean;
  /** 펼침 면 일괄 회수(F7) — 전환 자체가 소유하므로 화면이 늘어도 같은 회수가 걸린다. */
  reclaimSurfaces(): void;
  /** 클래스·속성 집행 — aria-current·`.scr.on`·몰입 body 클래스. 좌표는
   *  `IMMERSIVE_SURFACES` 를 같은 정본에서 읽는다. */
  applyScreen(id: string): void;
  /** 재당김 발신 — 호스트 주입·Bridge 가용성 판독과 notice 재진술을 지고, 호스트 부재면
   *  무동작 이행 약속을 돌려준다. 규약 판정(ready·화이트리스트)은 이 기계의 `refresh` 가
   *  이미 끝냈다. */
  dispatchRefresh(id: string): Promise<unknown>;
  /** 전환 자동 재당김의 실패 재진술 — 문안·alert 은 집행 층 소유라 원 error 를 그대로
   *  넘긴다(실패는 조용히 삼키지 않는다 — 화면은 이미 전환됐고 스냅샷만 낡음). */
  notifyRefreshFailure(error: unknown): void;
  /** 「문서 만들기」 착지 시 편집 호스트 재렌더(#138 리뷰 F12) — 관리 화면에서 바뀐 공유
   *  그룹 접힘이 편집 모드 1단계 피커에 stale 로 남지 않게. */
  rerenderEditor(): void;
};

export type GoOptions = { force?: boolean; refreshed?: boolean };

export type ShellNavListener = () => void;

/* 편집 호스트 재렌더가 결속된 화면 — 값은 DEFAULT_SCREEN 과 우연히 같지만 판정이 다르다:
   랜딩 기본값이 바뀌어도 재렌더는 「문서 만들기」 착지를 계속 따라가야 한다. */
const EDITOR_HOST_SCREEN = "job";

export function createShellNav() {
  let executor: ShellExecutor | null = null;
  let current: string | null = null;
  let routingReady = false;
  let closePromptPending = false;
  const registrations = new Set<{ listener: ShellNavListener; alive: boolean }>();

  function must(): ShellExecutor {
    if (executor === null) {
      /* 결속 전 판정 요청은 배선 결함이다 — 조용한 무동작으로 접으면 「랜딩이 안 찍혔다」가
         침묵이 된다(confirm-or-alarm). */
      throw new Error("셸 집행자가 결속되지 않았습니다 — bindExecutor 가 판정보다 먼저여야 합니다.");
    }
    return executor;
  }

  function notify(): void {
    for (const registration of [...registrations]) {
      if (registration.alive) registration.listener();
    }
  }

  /* 화면 스냅샷 재당김의 **단일 정의**(8R 근본 조치) — 전환이 자동으로 쏘는 발신과, 그
     화면을 **노출하기 전에** 완료를 기다려야 하는 호출자(편집기 이탈)가 같은 절차를 쓴다.
     두 벌이 되면 한쪽만 고쳐지고 그 경로만 옛 규칙을 든 화면을 내보인다(F7 이 네 라운드에
     걸쳐 재발시킨 결함류). 규약 밖이면 무동작 이행 약속이다. */
  function refresh(id: string): Promise<unknown> {
    if (!routingReady || !REFRESH_ON_NAV.includes(id)) return Promise.resolve(null);
    return must().dispatchRefresh(id);
  }

  /* 화면 전환 — 탭 클릭과 라이브러리 상세의 프로그램적 이동이 공유하는 단일 경로.
     몰입 표면에서 나가는 이동은 그 화면의 이탈 가드를 **먼저** 지난다: 가드는 비동기
     (3택 모달)라 위임 후 전환을 중단하고, 처분이 끝나면 호출부가 `force` 로 되돌아온다. */
  function go(id: string, opts?: GoOptions): void {
    const exec = must();
    if (
      current !== null && current !== id && !(opts && opts.force)
      && IMMERSIVE_SURFACES.some((im) => im.id === current)
      && exec.delegateLeave(current, id)
    ) {
      return; // 전환 중단 — 처분 뒤 force 재진입이 되돌아온다.
    }
    exec.reclaimSurfaces();
    current = id;
    exec.applyScreen(id);
    notify();
    if (!routingReady) return; // ready 전에는 DOM 기본 랜딩만 정하고 브리지 발신은 미룬다.
    /* `refreshed` 는 호출자가 **전환 전에** 이미 기다린 경우다(편집기 이탈 — 8R P1): 다시
       쏘면 왕복이 두 벌이 되고, 늦게 도착한 두 번째가 방금 복원한 면을 흔든다. */
    if (!(opts && opts.refreshed)) {
      refresh(id).catch((error) => exec.notifyRefreshFailure(error));
    }
    if (id === EDITOR_HOST_SCREEN) exec.rerenderEditor();
  }

  return {
    /** 집행자 결속 — adapter 구성이 정확히 1회. 두 번째는 throw(머리말). */
    bindExecutor(next: ShellExecutor): void {
      if (executor !== null) {
        throw new Error("셸 집행자가 이미 결속돼 있습니다 — 두 번째 구성은 두 번째 실행 경로입니다.");
      }
      executor = next;
    },

    /** 관측면 — 현재 화면(랜딩 전 null). 집행자·테스트가 판정 결과를 되묻는 축이다. */
    currentScreen(): string | null {
      return current;
    },

    /** 관측면 — ready 게이트(구 `routingReady` 의 승계). */
    isRoutingReady(): boolean {
      return routingReady;
    },

    go,
    refresh,

    /** ready 전이 — 부팅 시퀀서(호스트 ready 사건 훅)가 부른다. 재발화는 상태 무변화라
     *  통지하지 않는다 — init 재주행 여부는 시퀀서 소유다(현 동작 보존, 패킷 §1 ②). */
    markReady(): void {
      if (routingReady) return;
      routingReady = true;
      notify();
    },

    /** 종료 확인 직렬화 진입 — 미결이 있으면 거절(구 `closePromptPending` 의 승계).
     *  거절의 무동작은 호출부(AppCloseGuard) 계약 그대로다 — 다음 X 가 새 상태를 다시
     *  판정한다. */
    beginClosePrompt(): boolean {
      if (closePromptPending) return false;
      closePromptPending = true;
      return true;
    },

    /** 직렬화 해제 — 미보유 해제는 호출 규약 위반이라 throw(overlay 엔진 releaseDialog
     *  와 같은 엄격도). 성공·실패·거절 어느 경로든 finally 가 정확히 1회 부른다. */
    endClosePrompt(): void {
      if (!closePromptPending) {
        throw new Error("보유하지 않은 종료 확인 직렬화를 해제했습니다 — begin/end 는 짝이어야 합니다.");
      }
      closePromptPending = false;
    },

    /** 관측면 — 종료 확인 미결 여부. */
    isClosePromptPending(): boolean {
      return closePromptPending;
    },

    /** 상태 변화 구독(전환·ready 전이) — 해제 클로저 반환. 이중 해제는 throw(store.ts 규율). */
    subscribe(listener: ShellNavListener): () => void {
      const registration = { listener, alive: true };
      registrations.add(registration);
      return () => {
        if (!registration.alive) {
          throw new Error("이미 해제된 셸 구독입니다 — 해제는 등록마다 정확히 1회여야 합니다.");
        }
        registration.alive = false;
        registrations.delete(registration);
      };
    },
  };
}

export type ShellNav = ReturnType<typeof createShellNav>;
