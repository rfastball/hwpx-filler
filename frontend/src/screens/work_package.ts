/* 작업 꾸러미(#1188 WP-05) — 「문서 작업」의 「작업 내보내기…」·「작업 불러오기…」 왕복.
 *
 * 이 파일이 소유하는 것은 **흐름**뿐이다: 호스트 파일 선택(`pick_work_package_path`) → library
 * 꾸러미 액션 → 확인 창 → 확정. 무엇이 들어오는지·이름이 어떻게 바뀌는지·템플릿을 새로 두는지·
 * 확인 조건 없이 내보내도 되는지는 Python(`webapp/work_package_panel.py`)이 판정하고 문장까지
 * 지어 보낸다. 여기서는 그 투영을 줄로 늘어놓기만 한다 — 개수·충돌·재사용·계약을 다시 세지 않는다.
 *
 * 확인 창은 공용 `Modal.confirm` 이다(기본 초점=취소·Escape=머무르기·테마는 그 계약 그대로).
 * 본문은 줄바꿈을 보존하는 문단이라 계획은 여러 줄 글로 싣는다. */
import type { BridgeClient } from "../runtime/client.ts";
import { expectHostValue } from "./runtime.ts";

type Obj = Record<string, any>;

export type WorkPackageDeps = {
  client: BridgeClient;
  modal: { confirm(spec: Obj): Promise<boolean> };
  notify(message: string): void;
  /** 불러온 뒤 목록을 다시 읽고 Python 이 고른 첫 작업을 연다. */
  refresh(select: string): Promise<unknown>;
};

/** 불러오기 확인 본문 — 작업마다 이름 줄, 그 아래 템플릿과 처리 표지, 이름이 바뀌면 그 줄.
 *  모든 글자는 `plan_view` 가 지은 값이다(템플릿 표지까지 작업 줄에 실려 온다). */
export function workPackagePlanBody(view: Obj): string {
  const lines: string[] = [];
  for (const job of (view.jobs || []) as Obj[]) {
    lines.push(String(job.name));
    lines.push(`  ${String(job.template)} · ${String(job.template_label)}`);
    if (job.note) lines.push(`  ${String(job.note)}`);
  }
  if (view.data_notice) lines.push("", String(view.data_notice));
  return lines.join("\n");
}

export function createWorkPackageActions(deps: WorkPackageDeps) {
  const send = async (action: string, payload: Obj): Promise<Obj> => {
    const call = deps.client.dispatch as unknown as (
      channel: string, name: string, body: Obj,
    ) => ReturnType<BridgeClient["dispatch"]>;
    return (expectHostValue(await call("library", action, payload), `library/${action}`) ?? {}) as Obj;
  };

  /** 파일 선택 — 취소(null·빈 값)는 아무것도 바꾸지 않았으므로 조용히 끝난다. */
  async function pick(action: "export" | "import"): Promise<string> {
    const picked = expectHostValue(
      await deps.client.invoke("pick_work_package_path", action), "pick_work_package_path",
    );
    return picked === null || picked === undefined ? "" : String(picked);
  }

  /** 이 작업 공간의 모든 작업을 한 꾸러미로 — 무엇이 빠지고 무엇이 계약 없이 실리는지는 Python 이
   *  한 확인 문장으로 돌려준다(`confirm_text`). 실을 작업이 없으면 Python 이 쓰지 않고 거절한다. */
  async function exportAll(returnFocus?: HTMLElement): Promise<void> {
    const path = await pick("export");
    if (!path) return;
    let result = await send("export_work_package", { path });
    if (result.needs_confirm) {
      const accepted = await deps.modal.confirm({
        title: "작업 내보내기", body: String(result.confirm_text || ""),
        confirmLabel: "내보내기", cancelLabel: "취소", returnFocus,
      });
      if (!accepted) return;
      result = await send("export_work_package", { path, confirm: true });
    }
    if (result.ok === false) deps.notify(String(result.error));
  }

  /** 계획을 보이고 확정한다. 지문이 낡았으면 Python 이 새 계획을 함께 돌려준다 — 그 계획을
   *  다시 보이고 다시 묻는다(사람이 본 계획과 설치한 계획이 다를 수 없다). 거절은 `null`. */
  async function confirmAndInstall(path: string, first: Obj, returnFocus?: HTMLElement): Promise<Obj | null> {
    let plan = first;
    for (;;) {
      const view = (plan.view || {}) as Obj;
      const accepted = await deps.modal.confirm({
        title: String(view.title || ""), body: workPackagePlanBody(view),
        confirmLabel: "불러오기", cancelLabel: "취소", returnFocus,
      });
      if (!accepted) return null;
      const result = await send("import_work_package", { path, basis: plan.basis });
      if (!result.stale) return result;
      plan = result;
    }
  }

  async function importPackage(returnFocus?: HTMLElement): Promise<void> {
    const path = await pick("import");
    if (!path) return;
    const plan = await send("inspect_work_package", { path });
    if (plan.ok === false) { deps.notify(String(plan.error)); return; }
    const result = await confirmAndInstall(path, plan, returnFocus);
    if (result === null) return;
    if (result.ok === false) { deps.notify(String(result.error)); return; }
    await deps.refresh(String((result.imported || [])[0] || ""));
    if (result.message) deps.notify(String(result.message));
  }

  return { exportAll, importPackage };
}

export type WorkPackageActions = ReturnType<typeof createWorkPackageActions>;
