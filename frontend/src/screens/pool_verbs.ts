/* 등록 데이터 풀의 **관리 동사 한 벌** — 두 호스트(고르기 우 열 · 데이터 선택 다이얼로그)가
 * 같은 몸통을 쓴다(U6-B #976).
 *
 * 종전에는 이 함수들이 목록 컴포넌트(`pool_list.ts`)와 한 파일에 살았다. 그 컴포넌트는
 * 고르기 열 공용 ③b 에서 `PoolColumn` 에 흡수돼 사라졌고, **그리는 일과 발신하는 일**은
 * 애초에 다른 관심사라 남은 쪽이 여기로 왔다: 두 호스트가 공유하는 것은 DOM 이 아니라
 * 「같은 `pool` 채널·같은 확인 왕복·같은 연타 차단」이다.
 *
 * **판정·문안·`basis` 는 전부 Python 이 낸다**(`screen_pool.py`). 여기 있는 것은 확인 UI 와
 * 발신뿐이고, 그래서 종류가 늘어도 이 파일은 늘지 않는다.
 */
import type { ContextMenuItem } from "./context_menu.ts";
import { SESSION_DATA_KEY } from "./pool_column.ts";

type Obj = Record<string, any>;

/** 항목 상세 시트를 여는 메뉴 항목의 라벨 — 좌·우 두 열과 시트 안내가 같은 글자를 쓴다. */
export const ROW_DETAIL_LABEL = "자세히…";

/** 우 열 행 ⋯ 가 열 동사 목록 — 링1 동사 + 「폴더에서 보기」 + 「자세히…」.
 *
 *  **두 호스트가 같은 함수를 부른다**(고르기 열 공용 ④): 편집기 우 열과 데이터 선택
 *  다이얼로그는 같은 열을 그리므로 그 행의 ⋯ 목록도 한 벌이어야 한다. 종전에는 두 파일이
 *  같은 규칙을 각자 적었고(다이얼로그의 지역 `rowMenuItems`), 그러면 항목이 하나 늘 때
 *  한쪽에만 서는 날이 온다 — 지금 늘어난 「자세히…」가 바로 그 항목이다.
 *
 *  **상태 동사는 링1 소유다**(`row.actions` — 다시 연결·보관/활성화·삭제). 종전 카드가
 *  하던 「엑셀이면 다시 연결을 하나 더 붙인다」는 표면 판정은 함께 사라졌다(같은 상태를 두
 *  곳이 판정하지 않는다): 그 목록은 이제 `screen_pool` 이 전수로 낸다.
 *
 *  「폴더에서 보기」는 경로가 있을 때만, 「자세히…」는 **등록 항목**에만 선다: 세션 행(파일로
 *  연 데이터)은 풀에 없어 검토할 항목 자체가 없고, 서게 두면 눌러도 답할 것이 없다.
 *  순서는 좌 열과 같다 — 링1 동사 · 경로 문 · 「자세히…」가 마지막이다. */
export function dataRowMenuItems(row: Obj | null): ContextMenuItem[] {
  if (row === null || row === undefined) return [];
  const items: ContextMenuItem[] = ((row.actions || []) as Obj[]).map((action: Obj) =>
    ({ action: `act:${String(action.key)}`, label: String(action.label) }));
  if (row.path) items.push({ action: "reveal", label: "폴더에서 보기" });
  if (String(row.key || "") !== SESSION_DATA_KEY) {
    items.push({ action: "detail", label: ROW_DETAIL_LABEL });
  }
  return items;
}

/** 계약 목록 블록이 아직 없을 때의 사유 — 죽은 버튼 대신 비활성 + `title`. */
export const PCLM_UNAVAILABLE =
  "계약 목록 정보를 아직 읽지 못했습니다 — 잠시 뒤 다시 열어 보세요.";

/** 목록에서 사라진 키의 사유 — **조용한 반환 금지**.
 *
 *  드롭·⋯ 도중 `tpl`·`pool` push 가 끼면 손에 든 키가 지금 목록에 없을 수 있다. 그때
 *  말없이 반환하면 누른 사람에게 화면이 아무 말도 남기지 않는다 — 이 저장소가 금지하는
 *  무반응이다. */
export const POOL_GONE_FROM_LIST = "목록이 바뀌었습니다. 다시 고르세요.";

/** 고를 수 없는 항목의 클릭·드롭 문안 — **조용히 무시하지 않는다**(U6-B).
 *
 *  사유는 Python 이 행에 실어 보낸 것을 그대로 재진술한다: 여기서 문장을 다시 지으면 같은
 *  상태가 부제와 알림에서 두 어휘를 갖는다. 두 호스트가 같은 열을 그리므로 그 거절의
 *  **문형도 한 벌**이다. */
export function poolRefusalText(name: string, reason: string): string {
  return `'${name}' 은(는) 고를 수 없습니다. ${reason}`;
}

/** `#poolRegModal` 을 여는 자리 — 등록 폼의 수명은 데이터 선택 컨트롤러가 계속 소유한다.
 *
 *  고르기 화면은 그 폼을 **다시 만들지 않고** 이 포트로 연다: 확인 왕복(needs_confirm/
 *  basis)·pin 모드 잠금·pclm 좌표가 한 벌이라, 두 번째 구현을 세우면 그 한 벌이 갈린다. */
export type PoolRegistrationPort = {
  openRegDialog(options: Obj): void;
  openPclm(): void;
  /** 등록 데이터 「자세히…」 — 시트의 주인도 데이터 선택 컨트롤러다(등록 폼과 같은 근거).
   *
   *  `#poolDetailModal` 은 셸 레벨 overlay 하나이고, 그것을 여는 문이 두 곳(고르기 우 열·
   *  다이얼로그)이다. 두 번째 구현을 세우면 시트의 동사 착지·메시지 채널이 갈린다. */
  openDetail(key: string, trigger: HTMLElement | null): Promise<void>;
};

export type PoolVerbDeps = {
  dispatch(screen: string, action: string, payload?: Obj): Promise<Obj>;
  modal: { confirm(spec: Obj): Promise<boolean> };
  /** 실패 재진술 — 호스트의 채널로 간다(다이얼로그 상태줄 / 편집기 인라인 알림).
   *  삼키면 「눌렀는데 아무 일도 없다」가 되므로 두 호스트 다 자기 자리를 준다. */
  onError(message: string): void;
  /** 「사용」의 몸통 — 관리 동사와 달리 채널이 호스트마다 갈린다(`load_pool` ↔
   *  `use_pool_data`). 나머지 넷은 종류와 무관하게 **같은 `pool` 채널**이다. */
  onUse(row: Obj): Promise<unknown> | void;
  /** 「다시 연결」 폼 프리필. */
  openRelink(row: Obj): void;
  /** 다른 왕복이 진행 중이면 사유(없으면 `""`). */
  busyReason?(): string;
};

/** 앞선 왕복이 아직 끝나지 않았을 때의 거절 — 연타가 두 번 발신되지 않게 한다. */
export const POOL_VERB_IN_FLIGHT =
  "앞선 요청이 아직 끝나지 않았습니다. 잠시 뒤 다시 누르세요.";

/** 관리 동사 한 벌 — 확인 왕복(`delete`)과 지문 되싣기까지 **두 호스트가 공유**한다.
 *
 *  **연타 차단도 여기 하나가 진다**(U6-B #976 리뷰 6): 다이얼로그는 마운트 중임을
 *  `busyReason` 으로 말하지만 그 술어는 「사용」 하나만 덮었다 — 삭제·보관·중복 정리의
 *  두 번째 클릭은 그대로 나가 확인 모달을 두 벌 세우거나 같은 지문으로 두 번 확정한다.
 *  in-flight 표지를 몸통이 들면 두 호스트가 같은 보호를 받는다(호스트별 재구현 0). */
export function createPoolVerbs(deps: PoolVerbDeps) {
  let inFlight = false;

  /** 지금 받을 수 없으면 사유, 받을 수 있으면 ``""``. 호스트 사유가 더 구체적이라 먼저다. */
  function refusal(): string {
    const hosted = deps.busyReason ? deps.busyReason() : "";
    if (hosted) return hosted;
    return inFlight ? POOL_VERB_IN_FLIGHT : "";
  }

  async function poolAction(action: string, row: Obj): Promise<void> {
    const busy = refusal();
    if (busy) { deps.onError(busy); return; }
    /* 표지는 **첫 await 앞에서** 선다 — 같은 틱의 두 번째 클릭이 그 사이로 새지 않게. */
    inFlight = true;
    try {
      if (action === "use") { await deps.onUse(row); return; }
      if (action === "relink") { deps.openRelink(row); return; }
      if (action === "delete") {
        const first = await deps.dispatch("pool", "delete", { key: row.key });
        if (first.needs_confirm && await deps.modal.confirm({
          body: `${first.confirm_text}\n\n삭제할까요?`,
          confirmLabel: "삭제", cancelLabel: "취소", danger: true,
        })) {
          await deps.dispatch("pool", "delete", {
            key: row.key, confirm: true, basis: first.basis,
          });
        }
        return;
      }
      await deps.dispatch("pool", action, { key: row.key });
    } catch (error) {
      deps.onError(`고정한 데이터를 바꾸지 못했습니다:\n${String(error)}`);
    } finally {
      inFlight = false;
    }
  }

  async function resolveDuplicate(keep: string): Promise<void> {
    const busy = refusal();
    if (busy) { deps.onError(busy); return; }
    inFlight = true;
    try {
      const first = await deps.dispatch("pool", "resolve_duplicate", { keep });
      if (first.needs_confirm && await deps.modal.confirm({
        body: `${first.confirm_text}\n\n정리할까요?`,
        confirmLabel: "정리", cancelLabel: "취소", danger: true,
      })) {
        await deps.dispatch("pool", "resolve_duplicate", {
          keep, confirm: true, basis: first.basis,
        });
      }
    } catch (error) {
      deps.onError(`중복 등록을 정리하지 못했습니다:\n${String(error)}`);
    } finally {
      inFlight = false;
    }
  }

  return { poolAction, resolveDuplicate };
}
