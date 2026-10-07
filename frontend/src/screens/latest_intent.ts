/* 연속 의도의 **마지막 하나**만 착지시키는 직렬 큐 — 작업 화면의 데이터 전환과 편집기의
   등록 데이터·시트 탭 전환이 같은 규율을 쓴다.

   누를 때마다 의도 번호가 오르고, 일은 앞 일이 끝난 뒤에 차례로 선다. 차례가 왔을 때 더 새
   의도가 있으면 그 일은 시작하지 않는다(`superseded` 를 돌려준다). 이미 시작한 일은 확인
   모달처럼 기다리는 자리 뒤에서 `isCurrent()` 로 다시 물어 낡았으면 변이를 보내지 않는다 —
   그래서 확인을 두 번 겹쳐 띄우지 않고, 먼저 누른 대상이 나중 선택을 덮지도 않는다. */

export type LatestIntentQueue = {
  run<T>(task: (isCurrent: () => boolean) => Promise<T>, superseded: T): Promise<T>;
};

export function createLatestIntentQueue(): LatestIntentQueue {
  let latest = 0;
  let tail: Promise<unknown> = Promise.resolve();
  return {
    run<T>(task: (isCurrent: () => boolean) => Promise<T>, superseded: T): Promise<T> {
      const intent = ++latest;
      const isCurrent = (): boolean => intent === latest;
      const next = tail.then(() => (isCurrent() ? task(isCurrent) : superseded));
      /* 앞 일의 실패가 뒤 차례를 끊지 않는다 — 실패의 재진술은 그 일을 부른 쪽이 진다. */
      tail = next.catch(() => undefined);
      return next;
    },
  };
}
