/* 스냅샷 store (R2-03 · #407) — Python 권위 스냅샷의 **전송-충실** 보관소.

   Python→웹 관측 푸시(`snapshot` 사건)가 React 에 닿는 유일한 store 경계다. 이 파일이
   지는 것은 「도착한 것을 도착한 순서로 보관하고, 해제 가능한 구독으로 알린다」까지이고,
   그 밖의 모든 것은 하지 않는다:

   - **값 해석 0.** 스냅샷은 불투명하다 — 부분/전체 판별·병합·화면 해석을 하지 않는다.
     생성 진행 델타(`{"progress": …}`) 같은 부분 스냅샷의 해석은 소비 화면의 도메인이다
     (legacy `job.js` 가 오늘 그렇듯이). 여기서 병합하면 store 가 두 번째 판정자가 된다.
   - **판정 재조립 0.** stale/pending/게이트 판정은 Python(링1)이 소유하고 스냅샷으로
     투영된다 — store 는 그 투영을 나르기만 한다.

   ## 채널은 생성 계약에서 유도된다

   구독 정의역은 `contract.gen.ts` 의 화면 유니온이다 — 손 목록을 두면 그것이 계약의
   다섯 번째 재진술이 된다(R2-02 §2.4 결함류). 화면 채널 6종은 브리지 `renderers` 테이블의
   실측 키와 정확히 일치한다(패킷 §2.2).

   ## 순서 규약 — 도착 순, 당김만 revision 가드

   push 는 도착 순 last-delivery 다(세대 없는 fire-and-forget 의 정직한 번역 — Python 은
   push 반환을 소비하지 않고 스냅샷에 버전 필드도 없다). 단 하나의 신규 계약이
   `ingestPulled` 다: initial 류 당김의 착지는 당김 시작 시점 revision 을 함께 받아, 그 뒤
   push 가 이미 착지했으면 **적용하지 않고 그 사실을 반환값으로 알린다** — 「등록 전 push 는
   버려진다·부팅은 initial 당김이 정본」(bridge.js) 계약의 store 판 번역이다: 빈 채널의
   당김은 정본이고, 이미 push 가 착지한 채널에 낡은 당김이 덮어쓰는 것은 정본 역전이다.

   ## 리스너 예외는 격리하되 침묵하지 않는다

   이 store 의 ingest 는 브리지 renderers 체인(각 채널의 legacy render 앞자리)에서 불린다.
   리스너 예외가 위로 던져지면 React 층이 legacy render 를 죽이는 새 간섭 채널이 된다 —
   그래서 통지는 등록 사본을 순회하며 예외를 주입된 경보로 재진술하고 나머지 통지를
   계속한다(`bootstrap.js` preferences 처리기의 조각별 감싸기와 같은 형태 — 실패가 이름을
   갖고 남는 것이 침묵의 반대다).

   ## 이 파일에 없는 것

   DOM·전역·pywebview 접촉 0(신규 전송 통로는 `runtime/adapter.ts` 하나 — allowlist 게이트).
   React 도 모른다 — 화면 controller model의 안정된 subscribe/getSnapshot을 component가
   `useSyncExternalStore`에 직접 건네는 결합 경계가 진다. */
import { SCREEN_ACTIONS } from "../contract/contract.gen.ts";
import type { ScreenName } from "../contract/contract.gen.ts";

/** 구독 정의역 — 생성 계약의 화면 유니온에서 유도한다(손 목록 금지). */
export const SNAPSHOT_CHANNELS = Object.freeze(
  Object.keys(SCREEN_ACTIONS) as ScreenName[],
);

export type SnapshotListener = () => void;

/** 당김 착지의 판정 결과 — 조용한 무시 대신 「적용됐는가」를 값으로 돌려준다. */
export type PullOutcome = { applied: boolean; revision: number };

type Registration = { listener: SnapshotListener; alive: boolean };

type Channel = {
  value: unknown;
  revision: number;
  registrations: Set<Registration>;
  /** 채널별 **안정 참조** subscribe — `useSyncExternalStore` 는 subscribe 함수 참조가
   *  렌더마다 바뀌면 매 렌더 해제→재구독한다. 같은 채널 = 같은 함수 참조가 계약이다. */
  subscribeBound: (listener: SnapshotListener) => () => void;
};

export type SnapshotStore = ReturnType<typeof createSnapshotStore>;

/** 스냅샷 store 하나를 만든다 — 합성 루트가 정확히 한 번 구성한다(reload 시 재구성 =
 *  legacy renderers 와 같은 수명). 구성은 부작용이 없다. */
export function createSnapshotStore({ alarm }: { alarm: (message: string) => void }) {
  const channels = new Map<ScreenName, Channel>();

  function subscribeTo(channel: Channel, listener: SnapshotListener): () => void {
    if (typeof listener !== "function") {
      throw new TypeError("snapshot store 구독자가 함수가 아닙니다.");
    }
    /* 등록은 등록 수만큼이다 — 같은 함수를 두 번 구독하면 두 등록이고, 각 등록이 자기
       해제 클로저를 소유한다(React 의 effect 인스턴스마다 자기 cleanup 이 서는 형상). */
    const registration: Registration = { listener, alive: true };
    channel.registrations.add(registration);
    return () => {
      if (!registration.alive) {
        /* 이중 해제는 호출 규약 위반이다 — 침묵 무동작으로 접으면 「해제했는데 리스너가
           남아 있다」와 「이미 해제된 것을 또 해제했다」가 같은 침묵이 된다(root.ts 의
           unmount 이중 정산 throw 와 같은 엄격도). */
        throw new Error("이미 해제된 구독입니다 — 해제는 등록마다 정확히 1회여야 합니다.");
      }
      registration.alive = false;
      channel.registrations.delete(registration);
    };
  }

  for (const screen of SNAPSHOT_CHANNELS) {
    const channel: Channel = {
      value: null,
      revision: 0,
      registrations: new Set(),
      subscribeBound: (listener) => subscribeTo(channel, listener),
    };
    channels.set(screen, channel);
  }

  /** 미지 채널은 시끄럽게 거절한다 — 계약 밖 이름이 조용히 빈 채널로 접히면
   *  구독자는 영영 오지 않는 push 를 기다린다. */
  function channelOf(screen: ScreenName): Channel {
    const channel = channels.get(screen);
    if (channel === undefined) {
      throw new Error(`계약(SCREEN_ACTIONS)에 없는 채널입니다: ${String(screen)}`);
    }
    return channel;
  }

  function notify(channel: Channel, screen: ScreenName): void {
    /* 사본 순회 — 통지 중의 구독/해제가 이번 순회를 흔들지 않는다. */
    for (const registration of [...channel.registrations]) {
      if (!registration.alive) continue;
      try {
        registration.listener();
      } catch (error) {
        /* 격리 + 재진술(머리말) — 다음 리스너와 이 체인 뒤의 legacy render 를 지킨다. */
        alarm(`snapshot store 리스너 실패(${screen}) — ${String(error)}`);
      }
    }
  }

  function ingest(screen: ScreenName, snapshot: unknown): void {
    const channel = channelOf(screen);
    channel.value = snapshot;
    channel.revision += 1;
    notify(channel, screen);
  }

  return {
    /** 구독 정의역 — 배선(합성 루트)과 소비자가 같은 목록을 쓴다. */
    channels: SNAPSHOT_CHANNELS,

    /** push 착지 — 도착 순 last-delivery. 값은 해석하지 않는다(머리말). */
    ingest,

    /** 당김(initial 류) 착지 — `sinceRevision`(당김 시작 시점의 revision) 이후 push 가
     *  착지했으면 적용하지 않는다. 판정은 반환값이 알린다(조용한 무시 금지). */
    ingestPulled(screen: ScreenName, snapshot: unknown, sinceRevision: number): PullOutcome {
      const channel = channelOf(screen);
      if (channel.revision !== sinceRevision) {
        return { applied: false, revision: channel.revision };
      }
      ingest(screen, snapshot);
      return { applied: true, revision: channel.revision };
    },

    /** 마지막 도착 스냅샷 — **참조 그대로**(getSnapshot 캐시 안정성 계약). 도착 전엔
     *  `null`(파사드 부재 `null` 관용과 같은 형). */
    get(screen: ScreenName): unknown {
      return channelOf(screen).value;
    },

    /** 채널별 단조 revision — 당김 가드와 관측의 축. */
    revision(screen: ScreenName): number {
      return channelOf(screen).revision;
    },

    /** 구독 — 해제 클로저를 돌려준다. 등록은 등록 수만큼, 이중 해제는 throw. */
    subscribe(screen: ScreenName, listener: SnapshotListener): () => void {
      return channelOf(screen).subscribeBound(listener);
    },

    /** 채널별 안정 참조 subscribe — 같은 채널이면 언제나 같은 함수다(위 Channel 주석). */
    subscriber(screen: ScreenName): (listener: SnapshotListener) => () => void {
      return channelOf(screen).subscribeBound;
    },

    /** 관측면 — 「unmount 뒤 listener 0」 불변식을 테스트가 직접 묻는다
     *  (`push_port.js` 의 `overridden` 관측면 선례). */
    listenerCount(screen: ScreenName): number {
      return channelOf(screen).registrations.size;
    },
  };
}
