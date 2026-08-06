/* R4-03 저수준 `RelinkPort` 의 React/typed-client 구현 — legacy `js/relink.js` 의 후계.
 *
 * 이 port 가 소유하는 것은 **한 왕복**이다: 피커 → 백엔드 needs-confirm → 재진술 확인 →
 * confirm=true 커밋, 그리고 그 결과의 boolean. 그 위의 흐름(활성 작업 무장 가드·성공 뒤
 * 이어서 선택)은 #414 가 영구 소유하는 `JobRelinkFlowPort` 몫이라 여기 오지 않는다 —
 * rev5 가 그 경계를 그었고 rev6 이 소비자 allowlist 를 확정했다:
 *
 *   - job candidate/actionbar → `JobRelinkFlowPort` 만 (저수준 직접 호출 0)
 *   - `JobRelinkFlowPort` 구현 → 이 port: exact 1 (`job_read.ts`)
 *   - library React flow → 이 port: exact 1 (`library.ts`)
 *
 * 반환은 **커밋 성사 여부 하나**다(rev7 §2). descriptor·`ERROR:`·null 3형 반환은 SheetPicker
 * 계약이고 여기 적용하지 않는다 — 두 port 의 결과 모양이 섞이면 호출자가 어느 계약으로
 * 읽어야 할지 모른다. 취소·거절·예외는 전부 false 이고, 커밋 성사만 true 다.
 *
 * `notify` 는 **호출자의 채널**이라 선택 인자다(없어도 동작한다). 실패의 loud alert 는 이
 * 서비스 자신의 채널(`deps.alarm`)이라 별개다 — 호출자가 콜백을 안 줬다고 실패가 조용해지면
 * 그게 곧 조용한 거절이다. */

import type { BridgeClient } from "../runtime/client.ts";
import type { RelinkNotify, RelinkPort } from "../ports/service_handoff.ts";
import { expectHostValue } from "./runtime.ts";

type Obj = Record<string, any>;

type ModalPort = { confirm(spec: Obj): Promise<boolean> };

export type JobRelinkDeps = {
  client: BridgeClient;
  modal: ModalPort;
  /** 서비스 자신의 loud 채널 — 호출자 `notify` 유무와 무관하게 실패를 시끄럽게 만든다. */
  alarm(message: string): void;
};

/** 화면 이름은 계약 유니온이지만 이 port 는 호출자가 준 문자열을 그대로 나른다 —
 *  legacy 소비자 둘(`"job"`·`"library"`)의 identity 를 보존하는 것이 handoff 의 조건이다. */
type RelinkScreen = "job" | "library";

function relinkScreen(screen: string): RelinkScreen {
  if (screen !== "job" && screen !== "library") {
    throw new Error(`RelinkPort: 등재되지 않은 소비자 화면입니다: ${screen}`);
  }
  return screen;
}

export function createJobRelink(deps: JobRelinkDeps): RelinkPort {
  async function relinkTemplate(
    screen: string, name: string, notify?: RelinkNotify,
  ): Promise<boolean> {
    const say: RelinkNotify = notify ?? (() => {});
    try {
      // 소비자 폐색은 **try 안**이다: 이 port 의 결과 계약은 `Promise<boolean>` 하나라
      // 여기서 throw 하면 `if (await relink(...))` 로 쓰는 호출자에게 처리되지 않은
      // rejection 이 된다. 시끄럽게 알리되 결과 모양은 하나로 유지한다.
      const target = relinkScreen(screen);
      const picked = expectHostValue(
        await deps.client.invoke("pick_template_path"), "pick_template_path",
      );
      // 피커 취소 — 아무것도 바뀌지 않았으므로 조용히 false 다(사용자가 방금 취소했다).
      if (picked === null || picked === undefined || picked === "") return false;
      const path = String(picked);

      let res = (expectHostValue(
        await deps.client.dispatch(target, "relink_template", { name, path }),
        "relink_template",
      ) ?? {}) as Obj;

      if (res.needs_confirm === true) {
        // 조용한 재연결 금지 — 백엔드가 낸 재진술을 그대로 보이고 확정을 받는다.
        const ok = await deps.modal.confirm({
          body: `${String(res.confirm_text ?? "")}\n\n계속할까요?`,
          confirmLabel: "다시 연결", cancelLabel: "취소",
        });
        if (!ok) {
          say("다시 연결을 취소했습니다.", "cancel");
          return false;
        }
        res = (expectHostValue(
          await deps.client.dispatch(target, "relink_template", { name, path, confirm: true }),
          "relink_template",
        ) ?? {}) as Obj;
      }

      if (res.ok === false) {
        const error = String(res.error ?? "다시 연결하지 못했습니다.");
        deps.alarm(error);
        say(`다시 연결 실패: ${error}`, "error");
        return false;
      }
      if (res.restated) say(String(res.restated), "ok");
      return true;
    } catch (error) {
      // 예외도 false 다 — 성사 여부를 모르는 채 true 를 내면 호출자가 후속 선택을 태운다.
      deps.alarm(String((error as Obj)?.message ?? error));
      return false;
    }
  }

  return { relinkTemplate };
}
