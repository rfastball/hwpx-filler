/* 저작 화면의 Python 왕복 두 길(dispatch·invoke)과, Python 이 스스로 세운 활성 문서를 화면의 뷰로 따라가기(#1146).
 *
 * 튜토리얼이 연 연습 문서·작업 공간 전환·연습 종료 뒤 복원은 Python 이 활성 문서를 바꾸고 화면은 push 만 받는다. 편집기는
 * 스냅샷의 활성 탭을 그리는데 화면의 뷰가 그 탭이 아니면 편집기의 선택 보고가 버려진다 — 골라도 판정(locate)이 없다.
 * 이 화면이 보낸 요청이 돌아오기 전에 온 push 는 그 요청의 결과이므로 그 요청을 보낸 동작(열기·닫기·옮기기)이 활성 문서를
 * 맞춘다. 요청이 모두 돌아온 뒤에도 뷰가 활성 문서와 다르면 그때 따라간다. 따라가기에 실패한 문서는 그 문서가 활성인
 * 동안 다시 시도하지 않는다(요청마다 되풀이되는 오류 고리를 만들지 않는다). 활성 문서가 바뀌면 그 표식은 지워진다 — 나중에
 * Python 이 그 문서를 다시 세우면 새 활성화다. 무엇이 활성인지는 판정하지 않는다 — 스냅샷 값을 따를 뿐이다. */

import type { BridgeClient } from "../runtime/client.ts";
import { expectHostValue } from "./runtime.ts";

type Obj = Record<string, any>;
type Call = (screen: string, name: string, body: Obj) => ReturnType<BridgeClient["dispatch"]>;

export type AuthoringHostView = {
  /** 스냅샷의 활성 문서 id(없으면 빈 문자열). */
  activeId(): string;
  /** 이 화면의 뷰가 서 있는 문서 id. */
  viewId(): string;
  activate(id: string): Promise<void>;
  fail(error: unknown): void;
  subscribe(listener: () => void): unknown;
};

export function authoringHost(client: BridgeClient, view: AuthoringHostView) {
  let inFlight = 0;
  let unfollowed = "";

  function follow() {
    const active = view.activeId();
    // 실패 표식은 그 활성화 한 번에만 선다 — Python 이 다른 문서를 세웠다면 다음에 다시 그 문서로 와도 따라간다.
    if (active !== unfollowed) unfollowed = "";
    if (!active || active === view.viewId() || active === unfollowed || inFlight > 0) return;
    void view.activate(active).catch((error) => { unfollowed = active; view.fail(error); });
  }

  /** 요청은 세기 시작한 뒤에 보낸다 — 보내는 순간 동기로 도착하는 push 도 그 요청의 결과로 센다. */
  async function awaited<T>(request: () => Promise<T>): Promise<T> {
    inFlight += 1;
    try { return await request(); } finally {
      inFlight -= 1;
      if (inFlight === 0) setTimeout(follow, 0);
    }
  }

  view.subscribe(follow);
  return {
    /** verdict: Python 이 판정을 세션 상태로 이미 투영한 호출(시험 입력 검증 등) — ok:false 는 오류 띠가 아니라 그 표면이 보인다. */
    async dispatch(action: string, payload: Obj = {}, verdict = false): Promise<Obj> {
      const call = client.dispatch as unknown as Call;
      const result = expectHostValue(await awaited(() => call("authoring", action, payload)), `authoring/${action}`) as Obj;
      // 거절(refusal)은 오류가 아니라 판정이다 — 호출자가 사유와 대안을 그린다(U07·AC08·AC10).
      if (result?.ok === false && !result.refusal && !verdict) throw new Error(result.message || result.detail || result.reason);
      return result || {};
    },
    async invoke(method: Parameters<BridgeClient["invoke"]>[0], ...args: unknown[]): Promise<Obj | null> {
      return expectHostValue(await awaited(() => client.invoke(method, ...args)), method) as Obj | null;
    },
  };
}
