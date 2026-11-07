/* 템플릿·데이터 채택(고르기 열 선택·끌어 놓기)과 등록 데이터(pool) 관리 동사, 매핑 재판정
 * 관문(자동 제안 다시 받기 등) — `editor_controller.ts` 책임 분리(복잡도 예산).
 * 공유 상태(스냅샷·발신·알림)는 deps로 받는다. */
import type { BridgeClient } from "../runtime/client.ts";
import type { ServiceHandoffPorts } from "../ports/service_handoff.ts";
import { pickDataFile } from "./data_file_pick.ts";
import { invokePathAction } from "./path_actions.ts";
import {
  createPoolVerbs, pclmSheetEditOptions, POOL_DATA_GONE, POOL_GONE_FROM_LIST, poolRefusalText,
} from "./pool_verbs.ts";
import type { PoolRegistrationPort } from "./pool_verbs.ts";
import { createLatestIntentQueue } from "./latest_intent.ts";
import { SESSION_DATA_KEY } from "./pool_column.ts";
import { libItems, findDataItem } from "./editor_controller_slots.ts";
import type { ModalPort, Obj } from "./editor_controller.ts";

/** 고르기 거절의 착지 — 끌어 놓기는 모아서(`refusals`) 한 번 말하고, 클릭은 바로 알린다.
 *  좌·우 열 선택이 같은 규칙을 쓴다(종전에는 두 함수가 같은 클로저를 각자 지었다). */
function refuseInto(refusals: string[] | undefined, text: string, notice: (text: string) => void): boolean {
  if (refusals) refusals.push(text); else notice(text);
  return false;
}

export type SelectionDeps = {
  modal: ModalPort;
  client: BridgeClient;
  services: ServiceHandoffPorts;
  poolRegistration: PoolRegistrationPort;
  tplModel: { getSnapshot(): Obj | null };
  poolModel: { getSnapshot(): Obj | null };
  snapshot(): Obj;
  notify(message: string): void;
  noticeSave(message: string): void;
  /** 편집 변이 — 전부 한 체인에 선다(순서에 기대는 질의도 포함). */
  sendEdit(action: string, payload?: Obj): Promise<Obj>;
  /** 관리 동사도 **편집 체인**에 선다(리뷰 6) — 이 화면의 다른 발신과 순서를 나눠 갖지
   *  않으면 보관·삭제가 마운트·저장 왕복 사이로 끼어든다. */
  dispatchChained(screen: string, action: string, payload?: Obj): Promise<Obj>;
  invoke(method: Parameters<BridgeClient["invoke"]>[0], ...args: unknown[]): Promise<unknown>;
  refreshScreen(): Promise<unknown>;
};

export function createSelectionController(deps: SelectionDeps) {
  /* 등록 데이터·시트 탭 전환은 연속으로 눌러도 마지막 대상 하나로 착지한다. */
  const poolSwitches = createLatestIntentQueue();

  /** 확정·수동 매핑 보호 — 수치는 Python 이 **지금** 판정한다(stale 우회 차단).
   *  `cause` 는 무엇을 바꾸려는지만 싣는다 — 데이터 계약을 든 작업에서 계약이 다시 판정할 행을
   *  셈에서 빼는 것은 Python 이다(#1193). */
  async function confirmMappingResetIfConfirmed(
    verbPhrase: string, cause: "data" | "template",
  ): Promise<boolean> {
    const stakes = await deps.sendEdit("mapping_reset_stakes", { cause });
    const human = Number(stakes.human || 0);
    if (!human) return true;
    return deps.modal.confirm({
      body: `${verbPhrase} 확정했거나 직접 편집한 매핑 ${human}개가 전부 미확정으로 돌아갑니다` +
        `(값은 이월).\n\n계속할까요?`,
      confirmLabel: "미확정으로 되돌리기", cancelLabel: "취소",
    });
  }

  /** 템플릿 채택 — **같은 템플릿이면 아무 일도 하지 않고**, 교체면 먼저 묻는다.
   *
   *  둘 다 고르기 화면이 연 자리다(U6-B #976 리뷰 1·2). 종전 표면에서는 현재 항목이 클릭
   *  핸들러 없는 span 이라 재선택이 구조적으로 불가능했고, 교체 확인은 데이터 쪽에만 있었다
   *  — 이제 같은 제스처(클릭·끌어 놓기)가 좌·우에 다 서므로 규칙도 하나여야 한다.
   *  수치는 Python 이 **지금** 판정한다(`mapping_reset_stakes` — 웹 지역 스냅샷 금지),
   *  확인 UI 만 여기서 짓는다. 백엔드도 같은 no-op 을 진다(표면만 막으면 뚫린다). */
  async function useLibraryTemplate(path: string): Promise<boolean> {
    if (path === String(deps.snapshot().template_path || "")) return true;
    if (deps.snapshot().template_path
      && !(await confirmMappingResetIfConfirmed("템플릿을 바꾸면", "template"))) return false;
    await deps.sendEdit("use_library_template", { path });
    return true;
  }

  async function importTemplate(): Promise<void> {
    const result = await deps.invoke("import_template_file", "editor");
    if (typeof result === "string" && result.startsWith("ERROR:")) {
      deps.noticeSave(result.slice(6).trim());
      return;
    }
    if (typeof result === "string" && result !== "") await deps.refreshScreen();
  }

  async function pickData(): Promise<void> {
    if (!(await confirmMappingResetIfConfirmed("데이터를 바꾸면", "data"))) return;
    /* 응답 해석은 데이터 선택 면과 한 벌이다. 시트 확정 취소는 중단(첫 시트 강등 없음),
       계약 목록 파일(.db·.pclm)은 데이터 선택 컨트롤러의 등록 폼으로 넘긴다(포트 위임). */
    const picked = await pickDataFile(deps.invoke, "editor", {
      sheetPicker: deps.services.sheetPicker.current(),
      openContractList: (db) => deps.poolRegistration.openPclm(db),
    });
    if (picked.kind === "error") deps.noticeSave(picked.message);
  }

  /** 고정한 데이터 하나를 이 작업의 데이터로 — 파일 피커와 **같은 선행 규율**을 지킨다:
   *  확정 매핑이 걸린 교체는 고르기 **전에** 한 번 묻는다(고른 뒤 되묻는 순서 금지).
   *  `sheet` 은 「연결 확인」의 시트 탭이 싣는다 — 같은 등록의 다른 시트도 데이터 교체다.
   *  연속으로 누르면 **마지막 대상**만 착지한다(작업 화면 `switchData` 와 같은 큐): 확인을
   *  기다리는 사이 더 새 선택이 오면 앞 선택은 변이를 보내지 않고 `false` 로 끝난다. */
  async function usePoolData(key: string, sheet?: string): Promise<boolean> {
    return poolSwitches.run(async (isCurrent) => {
      if (!(await confirmMappingResetIfConfirmed("데이터를 바꾸면", "data")) || !isCurrent()) return false;
      const result = await deps.sendEdit("use_pool_data", sheet === undefined ? { key } : { key, sheet });
      if (result.ok === false) deps.noticeSave(String(result.error || "등록 데이터를 불러올 수 없습니다."));
      return result.ok !== false;
    }, false);
  }

  /* 고를 수 없는 항목의 거절 문안과 「목록에서 사라졌다」는 **데이터 선택 다이얼로그와
     공용**이다(③b — 두 자리가 같은 열을 그리므로 거절의 문형도 한 벌이다). 사유 자체는
     Python 이 행에 실어 보낸 것을 그대로 재진술한다. */
  function refuseSelection(name: string, reason: string): void {
    deps.noticeSave(poolRefusalText(name, reason));
  }

  /** 좌 열 선택 — 클릭도 드롭도 **이 한 자리**를 지난다(같은 액션, 같은 거절).
   *
   *  ``refusals`` 를 받으면 거절을 그 배열에 담고 알림은 **호출자가** 낸다(끌어 놓기는 두
   *  반의 결과를 한 문장으로 말해야 하고, 알림 채널이 1슬롯이라 각자 쓰면 앞 문장이 사라진다).
   *  반환값은 「이 반쪽이 적용됐는가」다. */
  async function chooseTemplate(key: string, refusals?: string[]): Promise<boolean> {
    const item = libItems(deps.tplModel).find((row) => String(row.key) === key);
    const refuse = (text: string): boolean => refuseInto(refusals, text, deps.noticeSave);
    if (item === undefined) return refuse(`템플릿을 찾을 수 없습니다. ${POOL_GONE_FROM_LIST}`);
    if (!item.selectable) {
      return refuse(poolRefusalText(String(item.name), String(item.reason || "")));
    }
    return useLibraryTemplate(String(item.path));
  }

  /** 우 열 선택 — 좌 열과 대칭.
   *
   *  세션 행(파일로 연 데이터)은 **무동작**이다(③a): 이미 이 작업의 데이터라 다시 마운트할
   *  것이 없고, 풀에 없으니 「목록에서 사라졌다」도 아니다. 거절 문장을 세우면 지금 쓰고
   *  있는 것을 못 고른다고 말하는 꼴이 된다 — 좌 열의 「이미 고른 항목 재선택 = 무동작」과
   *  같은 자리다. */
  async function chooseData(key: string, refusals?: string[]): Promise<boolean> {
    if (key === SESSION_DATA_KEY) return false;
    /* 재료는 **그리고 있는 그 열**이다(고르기 열 공용 ④) — 다른 존을 곁눈질하면 화면에
       선 사유와 거절이 재진술하는 사유가 서로 다른 출처에서 온다. */
    const row = findDataItem(deps.poolModel, deps.snapshot, key);
    const refuse = (text: string): boolean => refuseInto(refusals, text, deps.noticeSave);
    if (row === null) return refuse(POOL_DATA_GONE);
    if (!row.selectable) {
      return refuse(poolRefusalText(String(row.name), String(row.reason || "")));
    }
    return usePoolData(key);
  }

  /** 끌어 놓기 성사 — **클릭이 발행하는 액션 두 번**이다(새 액션 0).
   *
   *  순서는 템플릿 먼저다: 템플릿이 필드를 정하고 그 위에 데이터가 온다(U4 §2.4). 뒤집으면
   *  데이터 마운트가 모델 재조립을 태운 뒤 템플릿 교체가 그것을 또 무너뜨린다.
   *
   *  우 열의 세션 행(`session`)이 상대가 되면 **데이터 쪽은 그대로 둔다**(③a) — 「지금 쓰는
   *  데이터에 이 템플릿을 붙인다」는 뜻이고, 그 무동작은 `chooseData` 하나가 진다(거절 0). */
  async function dropPair(sourceSide: string, sourceKey: string, targetKey: string): Promise<void> {
    const [templateKey, dataKey] = sourceSide === "tpl"
      ? [sourceKey, targetKey] : [targetKey, sourceKey];
    /* 거절은 **모아서 한 번** 말한다(리뷰 5): 알림 채널이 1슬롯이라 두 반쪽이 각자 쓰면
       먼저 쓴 문장이 조용히 사라지고, 사람은 무엇이 반만 바뀌었는지 알 수 없다. */
    const refusals: string[] = [];
    const gotTemplate = await chooseTemplate(templateKey, refusals);
    const gotData = await chooseData(dataKey, refusals);
    if (refusals.length === 0) return;
    const applied = [gotTemplate ? "템플릿" : "", gotData ? "데이터" : ""].filter(Boolean);
    deps.noticeSave(applied.length
      ? `${applied.join("·")}만 바뀌었습니다. ${refusals.join(" ")}`
      : refusals.join(" "));
  }

  /* 동사 한 벌은 데이터 선택 다이얼로그와 **같은 몸통**이다(U6-B · 공용 ⑤ 리뷰) — 같은
     `pool` 채널·같은 확인 왕복·같은 분기표·같은 검토 왕복·같은 통지 동사. 갈리는 것은
     「사용」의 발행과 실패가 착지하는 자리, 그리고 네 포트뿐이다. */
  const poolVerbs = createPoolVerbs({
    dispatch: (screen: string, action: string, payload: Obj = {}) =>
      deps.dispatchChained(screen, action, payload),
    modal: deps.modal,
    onError: deps.noticeSave,
    onUse: (row: Obj) => usePoolData(String(row.key)),
    /* 프리필 재료는 **검토 왕복이 낸 상세 투영**이다(고르기 열 공용 ④) — 키 이름도
       그 투영 그대로(`path`·`sheet`·`note`)다. */
    openRelink: (row: Obj) => deps.poolRegistration.openRegDialog({
      title: "데이터 다시 연결", okLabel: "다시 연결", targetKey: row.key,
      name: row.name, path: row.path, sheet: row.sheet, note: row.note,
    }),
    openPclmSheets: (row: Obj) => deps.poolRegistration.openRegDialog({
      ...pclmSheetEditOptions(row), refreshScreen: "editor",
    }),
    poolSnapshot: () => deps.poolModel.getSnapshot() as Obj | null,
    reveal: (path: string) => invokePathAction({
      client: deps.client, path, action: "reveal", notify: deps.notify,
    }),
    /* 시트의 주인은 데이터 선택 컨트롤러다 — 이 화면은 문만 연다(두 번째 구현 금지). */
    openDetail: (key: string, trigger: HTMLElement | null) =>
      deps.poolRegistration.openDetail(key, trigger),
  });

  /** 저장 폴더 변경은 기존 설정 모달을 연다. */
  function openSettings(settingsModalId: string): void {
    deps.modal.open(settingsModalId, {});
  }

  /** 「이 데이터 고정…」 — 파일로 연 데이터를 풀에 남긴다(`#poolRegModal` pin 모드). */
  function openPin(): void {
    const state = deps.snapshot();
    if (!state.data_path) return;
    deps.poolRegistration.openRegDialog({
      title: "이 데이터 고정", okLabel: "고정", name: state.data_name,
      path: state.data_path, sheet: state.data_sheet || "", pinMode: true,
    });
  }

  async function resuggestAll(): Promise<void> {
    /* 수치는 **이 관문의 것**을 읽는다 — 관문마다 자기 수치를 읽는다. */
    const stakes = await deps.sendEdit("mapping_reset_stakes", {});
    const manual = Number(stakes.resuggest_manual || 0);
    const kept = Number(stakes.confirmed || 0);
    if (manual && !(await deps.modal.confirm({
      body: `직접 편집한 매핑 ${manual}개가 자동 제안으로 돌아갑니다.` +
        `\n직접 입력한 상수·유형·표시형도 함께 지워집니다.` +
        (kept ? `\n확정한 ${kept}개는 그대로 둡니다.` : "") +
        `\n\n계속할까요?`,
      confirmLabel: "다시 받기", cancelLabel: "취소",
    }))) return;
    const result = await deps.sendEdit("resuggest_all", {});
    /* 아무것도 안 바뀐 경우를 조용히 넘기지 않는다 — 무동작으로 보이면 그게 조용한 소실이다. */
    if (!result.resuggested) {
      deps.noticeSave(`자동 제안을 다시 받을 행이 없습니다. 확정한 ${result.kept_confirmed}개는 그대로 둡니다.`);
    }
  }

  /** 「제안 n건 모두 확인」 — 자동 제안 행만 승격한다(U6-C #977).
   *
   *  확인 왕복이 없는 이유: 이 동사는 **잃을 것을 만들지 않는다**(미확정 → 확정 한 방향
   *  이고, 되돌리는 동사가 ⋯ 메뉴에 그대로 있다). 종전 「모두 확정」이 이름 재진술 모달을
   *  세운 것은 채울 것이 없는 행까지 한 번에 비움 확정으로 밀어 넣었기 때문이고, 그 승격은
   *  이제 행별 「비워 둠」 선언이 진다. 승격한 수치는 배지·pill 이 그 자리에서 말한다. */
  async function confirmSuggested(): Promise<void> {
    await deps.sendEdit("confirm_suggested", {});
  }

  return {
    poolVerbs,
    useLibraryTemplate, importTemplate, pickData,
    usePoolData, chooseTemplate, chooseData, dropPair, refuseSelection,
    openPin, openSettings,
    confirmSuggested, resuggestAll,
    confirmMappingResetIfConfirmed,
  };
}
