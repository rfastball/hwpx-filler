/* 등록 데이터 풀의 **몸통** — 두 호스트가 같은 컴포넌트를 세운다(U6-B #976).
 *
 * 종전에는 같은 상태를 두 표면이 다르게 그렸다: 「문서 만들기」의 데이터 선택 다이얼로그
 * (`data_picker.ts`)는 전 상태 + 관리 동사 다섯을, 편집기 2단계 머리의 축약판
 * (`PoolPickList`)은 이름·참조·「이 데이터 연결」만 그렸고, 「쓸 수 있는가」의 사유 문안도
 * 서로 달랐다(웹 `usableReason` ↔ Python `pool_option_block`). 그 축약판이 사슬째 퇴역하고
 * 두 자리가 이 파일 하나를 쓴다 — U6 §2.4 의 「데이터 풀은 고르기 화면의 오른쪽 열
 * 그 자체다」가 구조로 서는 자리다.
 *
 * **판정은 하나도 여기 없다.** 배지·사유·동사 목록·고를 수 있는가는 전부 `pool` 채널
 * 스냅샷이 실어 온 값이고(`screen_pool.py`), 이 파일은 그것을 그리고 호스트 콜백으로
 * 되쏜다. 갈리는 것은 셋뿐이다 — 1차 동사의 **라벨**, 그 동사가 **무엇을 발행하는가**,
 * 그리고 DOM `id` 접두(두 호스트가 동시에 살아 있어도 id 가 겹치지 않게).
 */
import { createElement, Fragment } from "react";
import type { ReactNode } from "react";

import type { BridgeClient } from "../runtime/client.ts";
import { PathActions } from "./path_actions.ts";

type Obj = Record<string, any>;

/** 드래그 결속(U6-B) — 고르기 화면에서만 선다. 다이얼로그 호스트는 넘기지 않는다. */
export type PoolDragBinding = {
  /** 이 열의 side 표지(`"dat"`). 상대 열은 `"tpl"` 이다. */
  side: string;
  /** 드롭 성사 — 발행은 **클릭과 같은 액션 두 번**이다(새 액션 없음). */
  onDrop(sourceSide: string, sourceKey: string, targetKey: string): void;
  /** 고를 수 없는 항목 위 드롭 — 조용히 삼키지 않고 사유를 재진술한다.
   *  `key` 를 함께 주는 이유는 호스트가 **이름까지** 말할 수 있어야 하기 때문이다
   *  (「'X' 은(는) 고를 수 없습니다. …」 — 클릭 거절과 같은 문형). */
  onRefuse(reason: string, key: string): void;
};

export type PoolListHost = {
  /** DOM id 접두 — 다이얼로그는 `"dataPicker"`(좌표 불변), 고르기 화면은 자기 것. */
  idPrefix: string;
  /** 1차 동사의 라벨(다이얼로그 「이 데이터 사용」 / 고르기 「이 데이터로」). */
  chooseLabel: string;
  /** 1차 동사의 발행 — 호스트가 자기 채널로 보낸다(`load_pool` ↔ `use_pool_data`). */
  onChoose(row: Obj): void;
  /** 지금 마운트된 데이터의 재진술 `{label, detail, sheet, path, origin, kind}`. */
  current: Obj;
  /** 겨눈 풀 슬롯 키(없으면 `""`) — 어느 항목이 선택 상태인가. */
  currentKey: string;
  /** 「이 데이터 고정…」(`#poolRegModal` pin 모드). */
  openPin(): void;
  /** 「파일 찾아보기…」 — 다중 시트 확정 게이트는 호스트가 이미 지난다. */
  browse(): void;
  /** 「계약 목록(.db) 등록…」. */
  openPclm(): void;
  /** 관리 동사(보관·활성화·삭제·다시 연결) — 두 호스트가 **같은 `pool` 채널**로 보낸다. */
  poolAction(action: string, row: Obj): void;
  /** 중복 등록 정리 확정. */
  resolveDuplicate(keep: string): void;
  drag?: PoolDragBinding;
  client: BridgeClient;
  notify(message: string): void;
};

/** 계약 목록 블록이 아직 없을 때의 사유 — 죽은 버튼 대신 비활성 + `title`. */
export const PCLM_UNAVAILABLE =
  "계약 목록 정보를 아직 읽지 못했습니다 — 잠시 뒤 다시 열어 보세요.";

/** `#poolRegModal` 을 여는 자리 — 등록 폼의 수명은 데이터 선택 컨트롤러가 계속 소유한다.
 *
 *  고르기 화면은 그 폼을 **다시 만들지 않고** 이 포트로 연다: 확인 왕복(needs_confirm/
 *  basis)·pin 모드 잠금·pclm 좌표가 한 벌이라, 두 번째 구현을 세우면 그 한 벌이 갈린다. */
export type PoolRegistrationPort = {
  openRegDialog(options: Obj): void;
  openPclm(): void;
};

export type PoolVerbDeps = {
  dispatch(screen: string, action: string, payload?: Obj): Promise<Obj>;
  modal: { confirm(spec: Obj): Promise<boolean> };
  /** 실패 재진술 — 호스트의 채널로 간다(다이얼로그 상태줄 / 편집기 인라인 알림).
   *  삼키면 「눌렀는데 아무 일도 없다」가 되므로 두 호스트 다 자기 자리를 준다. */
  onError(message: string): void;
  /** 「사용」의 몸통 — 관리 동사와 달리 채널이 호스트마다 갈린다(`load_pool` ↔
   *  `use_pool_data`). 나머지 넷은 종류와 무관하게 **같은 `pool` 채널**이다. */
  onUse(row: Obj): Promise<void> | void;
  /** 「다시 연결」 폼 프리필. */
  openRelink(row: Obj): void;
  /** 다른 왕복이 진행 중이면 사유(없으면 `""`). */
  busyReason?(): string;
};

/** 관리 동사 한 벌 — 확인 왕복(`delete`)과 지문 되싣기까지 **두 호스트가 공유**한다.
 *
 *  판정·문안·`basis` 는 전부 Python 이 낸다(`screen_pool.py`). 여기 있는 것은 확인 UI 와
 *  발신뿐이고, 그래서 종류가 늘어도 이 함수는 늘지 않는다. */
export function createPoolVerbs(deps: PoolVerbDeps) {
  async function poolAction(action: string, row: Obj): Promise<void> {
    try {
      const busy = deps.busyReason ? deps.busyReason() : "";
      if (busy) { deps.onError(busy); return; }
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
    }
  }

  async function resolveDuplicate(keep: string): Promise<void> {
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
    }
  }

  return { poolAction, resolveDuplicate };
}

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 끌어 놓기 props — 좌·우 두 열이 **같은 규칙**을 쓴다(`editor.ts` 의 템플릿 열도 이것).
 *
 *  성사하는 드롭은 **상대 열의 고를 수 있는 항목** 위에서만이다: 같은 열끼리는 짝이 아니라
 *  무동작이고, 비활성 항목은 받되 **사유와 함께 거절**한다(조용한 무시 금지 — 아래
 *  `onDragOver` 주석이 그 순서의 근거를 진다). 강조는 클래스 하나(`.drop-target`)이고
 *  애니메이션이 없다 — 정적이라 `prefers-reduced-motion` 과 무관하다. */
export function dragProps(
  binding: PoolDragBinding | undefined,
  key: string,
  selectable: boolean,
  blockReason: string,
): Obj {
  if (binding === undefined) return {};
  const clear = (event: Obj): void => {
    event.currentTarget.classList.remove("drop-target");
  };
  return {
    "data-side": binding.side,
    "data-key": key,
    draggable: selectable,
    onDragStart: (event: Obj) => {
      if (!selectable || !event.dataTransfer) return;
      event.dataTransfer.effectAllowed = "link";
      event.dataTransfer.setData("text/plain", `${binding.side}:${key}`);
    },
    onDragOver: (event: Obj) => {
      const transfer = event.dataTransfer;
      if (!transfer) return;
      /* 어느 열에서 왔는지는 `dragover` 에서 값을 읽을 수 없다(브라우저가 막는다) —
         읽을 수 있는 것은 **형식**뿐이라 side 대조는 `drop` 이 진다.

         **비활성 항목 위에서도 놓을 수는 있게 한다**: 안 받으면 `drop` 이 아예 안 와서
         손을 놓은 사람에게 화면이 아무 말도 못 한다(이 저장소가 금지하는 조용한 무시).
         받되 거절하고 사유를 남긴다 — 강조(`.drop-target`)는 **성사할 자리에만** 서므로
         「놓을 수 있다」는 약속과 「받는다」는 사실이 갈리지 않는다. */
      if (!Array.prototype.includes.call(transfer.types, "text/plain")) return;
      event.preventDefault();
      /* `dropEffect` 는 "link" 로 둔다 — "none" 이면 브라우저가 드롭을 **취소**해
         `drop` 이 아예 오지 않고, 그러면 위의 이유가 그대로 되살아난다(HTML 드래그
         모델). 「받을 수 없다」는 강조 부재와 항목 자체의 비활성 표시가 말한다. */
      transfer.dropEffect = "link";
      if (selectable) event.currentTarget.classList.add("drop-target");
    },
    onDragLeave: clear,
    onDrop: (event: Obj) => {
      event.preventDefault();
      clear(event);
      const payload = String(event.dataTransfer?.getData("text/plain") || "");
      const at = payload.indexOf(":");
      if (at < 0) return;
      const sourceSide = payload.slice(0, at);
      const sourceKey = payload.slice(at + 1);
      if (sourceSide === binding.side) return;      // 같은 열끼리는 짝이 아니다
      if (!selectable) { binding.onRefuse(blockReason, key); return; }
      binding.onDrop(sourceSide, sourceKey, key);
    },
  };
}

/** 고정한 데이터 1행 — 카드 좌표(`.tplcard.pk-row` · `data-row` · `data-act`)는 불변이다.
 *
 *  「쓸 수 있는가」와 그 사유는 **스냅샷이 든다**(`selectable`·`select_block_reason`).
 *  종전에는 이 파일의 지역 함수가 `status`·`missing` 으로 문장을 다시 지었고, 그래서 같은
 *  상태가 두 표면에서 두 어휘를 가졌다(U6-B). */
export function PinnedRow(props: { row: Obj; host: PoolListHost }): ReactNode {
  const { row, host } = props;
  const reason = String(row.select_block_reason || "");
  const selectable = !!row.selectable;
  const actions = (row.actions || []).map((action: Obj) => h("button", {
    className: "btn sm", "data-act": action.key, "data-key": row.key, "data-name": row.name,
    "data-busy-lock": true, key: action.key,
    onClick: () => { host.poolAction(action.key, row); },
  }, action.label));
  if (row.kind === "excel") actions.push(h("button", {
    className: "btn sm", "data-act": "relink", "data-key": row.key, "data-name": row.name,
    "data-busy-lock": true, key: "relink", onClick: () => { host.poolAction("relink", row); },
  }, "다시 연결…"));
  const current = !!host.currentKey && host.currentKey === row.key;
  return h("div", {
    className: `tplcard pk-row${current ? " cur" : ""}`, "data-row": row.key,
    /* 목록 안의 「지금 이것」 표지 — 행은 버튼이 아니라 카드라 `aria-current` 가 맞는
       역할이다(좌 열의 항목은 버튼이라 `aria-pressed` 를 쓴다). */
    "aria-current": current ? "true" : undefined,
    "aria-disabled": selectable ? undefined : "true",
    ...dragProps(host.drag, String(row.key), selectable, reason),
  },
  h("div", { className: "pk-info" },
    h("div", { className: "tplcard-top" },
      h("span", { className: "tplcard-name", title: row.reference }, row.name),
      h("span", { className: "pill muted" }, row.kind_label),
      h("span", { className: `pill ${row.badge_level}` }, row.badge_label),
      row.missing ? h("span", { className: "pill danger" }, "참조 끊김") : null),
    h("div", { className: "tplcard-meta muted pk-ref" }, h("span", null, row.reference),
      h(PathActions as any, {
        client: host.client, path: row.locate_path, notify: host.notify,
      })),
    row.note || reason ? h("div", { className: "tplcard-meta muted" },
      row.note ? h("span", { className: "pk-note" }, row.note) : null,
      reason ? h("span", { className: "pk-note" }, reason) : null) : null),
  h("div", { className: "tplcard-acts" },
    h("button", {
      className: "btn sm primary", "data-act": "use", "data-key": row.key,
      "data-name": row.name, disabled: !selectable, title: reason, "data-busy-lock": true,
      onClick: () => { host.onChoose(row); },
    }, host.chooseLabel), ...actions));
}

/** 세 구획(현재 데이터 · 고정한 데이터 · 다른 데이터) — 모달 껍데기를 뺀 몸통.
 *
 *  다이얼로그는 이것을 `.modal-card` 안에, 고르기 화면은 우 열 카드 안에 세운다. 두 자리가
 *  같은 노드를 내므로 「같은 상태를 두 표면이 다르게 그린다」가 구조적으로 불가능해진다. */
export function PoolSections(props: { host: PoolListHost; pool: Obj | null }): ReactNode {
  const { host, pool } = props;
  const id = (suffix: string): string => `${host.idPrefix}${suffix}`;
  const current = host.current || {};
  const rows = (pool?.rows || []) as Obj[];
  return createElement(Fragment, null,
    h("section", { className: "picker-sec", "aria-labelledby": id("CurCap") },
      h("div", { className: "cap", id: id("CurCap") }, "현재 데이터"),
      h("div", { id: id("Current") }, current.label ? h("div", { className: "tplcard" },
        h("div", { className: "tplcard-top" },
          h("span", { className: "tplcard-name" }, current.label),
          /* 자리 이름은 종류를 가리지 않고 「시트」 하나다 — 계약면도 사용자에겐 표 한 장이라
             내부 어휘(뷰)를 표면에 세울 이유가 없다. 종류가 가르는 것은 **값의 표기**뿐이다
             (#937): 계약 목록의 면 이름은 내부 이름이라 스냅샷 제목표로 옮겨 그린다. 그
             표에 없는 이름(손편집·구판)은 감추지 않고 원문 그대로 남긴다. */
          current.sheet ? h("span", { className: "muted" },
            `시트: ${current.kind === "pclm"
              ? (pool?.pclm?.titles || {})[current.sheet] || current.sheet
              : current.sheet}`) : null,
          h("span", { className: "pill ok" }, "사용 중")),
        current.detail ? h("div", { className: "tplcard-meta muted" }, current.detail) : null,
        current.origin === "file" && current.path ? h("div", { className: "tplcard-acts" },
          h("button", {
            className: "btn sm", id: id("Pin"), "data-busy-lock": true,
            onClick: host.openPin,
          }, "이 데이터 고정…")) : null)
        : h("p", { className: "muted capnote" }, "아직 데이터가 없습니다. 아래에서 고르세요."))),
    h("section", { className: "picker-sec", "aria-labelledby": id("PinCap") },
      h("div", { className: "cap", id: id("PinCap") }, "고정한 데이터"),
      h("div", { id: id("Pinned"), className: "tpllist" },
        pool === null ? h("p", { className: "muted capnote" }, "고정한 데이터를 읽는 중…")
          : rows.length
            ? rows.map((row: Obj) => h(PinnedRow as any, { key: row.key, row, host }))
            : h("p", { className: "muted capnote" }, "고정한 데이터가 없습니다.")),
      h("div", { id: id("Dupes") }, ...(pool?.duplicates || []).map((group: Obj) =>
        h("div", { className: "note warnbox", key: group.reference },
          `⚠ 같은 데이터(${group.reference})를 가리키는 등록이 ${group.entries.length}건입니다. 남길 등록을 골라 정리하세요: `,
          ...group.entries.map((entry: Obj) => h("button", {
            className: "btn sm", "data-dup-keep": entry.key, "data-busy-lock": true,
            key: entry.key, onClick: () => { host.resolveDuplicate(entry.key); },
          }, `'${entry.name}' 남기기`))))),
      h("div", { id: id("Corrupt") }, ...(pool?.corrupted || []).map((entry: Obj) =>
        h("div", { className: "note dangerbox", key: entry.file },
          `⚠ 손상된 등록 데이터: ${entry.file} — ${entry.error}`)))),
    h("section", { className: "picker-sec", "aria-labelledby": id("OtherCap") },
      h("div", { className: "cap", id: id("OtherCap") }, "다른 데이터"),
      h("button", {
        className: "btn", id: id("Browse"), "data-busy-lock": true,
        onClick: () => { host.browse(); },
      }, "파일 찾아보기…"),
      /* 계약 목록은 파일 피커가 아니라 **DB 자리 + 시트**로 겨눈다(#937). 스냅샷이 그
         둘을 아직 안 실었으면 숨기지 않고 비활성 + 사유 병기 — 죽은 버튼을 조용히 두면
         「눌러도 아무 일 없음」이 결함으로 읽힌다. 라벨의 괄호는 **확장자**다: 저쪽
         프로그램 이름(pclm)은 이 제품의 표면 어휘가 아니라 표면에 세우지 않는다. */
      h("button", {
        className: "btn", id: id("Pclm"), "data-busy-lock": true,
        disabled: !pool?.pclm, title: pool?.pclm ? "" : PCLM_UNAVAILABLE,
        onClick: host.openPclm,
      }, "계약 목록(.db) 등록…")));
}
