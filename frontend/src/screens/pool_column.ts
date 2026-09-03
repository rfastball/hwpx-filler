/* 고르기의 **열 하나** — 세 자리가 이 컴포넌트의 세 인스턴스다: 1단계의 좌(템플릿)·
 * 우(데이터) 열과 「데이터 선택」 다이얼로그(`data_picker.ts` — ③b 에서 합류).
 *
 * 동결 시안 `docs/u6-mockups/pairing-flow.html` 장면 1 의 문법(`.pool` · `.pool-head` ·
 * `.pool-list` · `.pitem` · `.pool-acts`)이 여기 한 벌로 선다. 종전에는 같은 그림을 두
 * 파일이 각자 그렸다 — 좌 열은 `editor.ts` 의 지역 `PoolItem`, 우 열은 `pool_list.ts` 의
 * 세 구획 — 그래서 「고를 수 있는가」의 시각적 얼굴(비활성 표시·사유 자리·선택 표지)이
 * 두 벌이었고, 한쪽만 고쳐지는 날이 오게 돼 있었다.
 *
 * **판정은 하나도 여기 없다.** 행이 드는 값은 전부 Python 이 낸 공용 존
 * (:mod:`hwpxfiller.webapp.pool_column`)이고 이 파일은 그것을 그린 뒤 호스트 콜백으로
 * 되쏜다. 갈리는 것은 넷뿐이다 — 이 열이 어느 쪽인가(`side`), DOM 좌표(`rootId`·`listId`),
 * 바닥에 서는 동사 줄(`acts`), 그리고 짝 지을 상대 열이 있는가(`drop`).
 *
 * 못 고르는 행은 **숨기지 않고 서되 눌리면 사유를 말한다**: `aria-disabled` 이지 `disabled`
 * 가 아니고, 클릭도 끌어놓기 거절도 호스트의 같은 한 자리(`choose`)를 지난다 — 이름과
 * 사유의 재진술은 그 자리가 하고, 표면은 문장을 짓지 않는다.
 */
import { createElement } from "react";
import type { ReactNode } from "react";

type Obj = Record<string, any>;

/** 지금 쓰고 있는 데이터가 목록 맨 위에 서는 행의 키 — Python 이 짓는 값과 **같은 글자**여야
 *  한다(`webapp/pool_column.SESSION_DATA_KEY`). 이 키를 든 행은 풀 항목이 아니라 상태 동사가
 *  없고 다시 고를 수도 없다(이미 그것을 쓰고 있다). 소비자가 셋(편집기 우 열·데이터 선택
 *  다이얼로그·행 계약 자신)이라 행 계약이 사는 이 파일이 든다. */
export const SESSION_DATA_KEY = "session";

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

/** 한 열의 호스트 — 열이 **모르는 것**만 받는다(판정·문안은 스냅샷이 든다). */
export type PoolColumnHost = {
  /** 이 열의 표지 — 끌어놓기의 상대 판정과 좌표 선택자(`[data-side]`)가 이 값을 본다. */
  side: "tpl" | "dat";
  /** 열 뿌리의 DOM `id`(게이트 좌표). */
  rootId: string;
  /** 항목 목록의 DOM `id`(게이트 좌표). */
  listId: string;
  /** 머리의 이름 — `aria-label` 도 같은 글자다. */
  title: string;
  /** 머리의 부제(무엇을 읽고 있는 목록인가). */
  headSub: ReactNode;
  /** 그 부제의 `title` — 폴더 전체 경로처럼 줄에 다 못 쓰는 사실이 선다. */
  headSubTitle?: string;
  /** 지금 고른 행의 키(없으면 `""`) — 정본은 편집기 스냅샷이다. */
  selectedKey: string;
  /** 고름·거절이 지나는 **한 자리**. 클릭도 드롭 거절도 여기로 온다. */
  choose(key: string): void;
  /** 끌어놓기 성사 — 두 열의 키를 그대로 넘긴다.
   *
   *  **없으면 끌기 props 를 하나도 얹지 않는다**: 데이터 선택 다이얼로그에는 상대 열이
   *  없어서 짝 지을 것이 없다. 결속 없이 `draggable` 만 서면 「끌 수 있다」는 약속이 서고
   *  놓을 자리는 어디에도 없다(빈 약속 금지 — 좌표 `data-side` 도 그때만 선다). */
  drop?(sourceSide: string, sourceKey: string, targetKey: string): void;
  /** 행 ⋮ — 없으면 그 버튼 자체가 서지 않는다(죽은 어포던스를 만들지 않는다). */
  onMore?(row: Obj, trigger: HTMLElement): void;
  /** 존 통지가 든 동사(중복 정리 등)의 발행 — payload 는 그 채널 스키마 그대로다. */
  onNoticeAction?(key: string, payload: Obj): void;
  /** 「새로 읽기」 — 없으면 머리에 그 버튼이 서지 않는다. */
  reload?(): void;
  /** 바닥 동사 줄 — 열마다 다른 유일한 덩어리다. */
  acts?: ReactNode;
  /** 스냅샷이 **아직 없을 때**의 문안. 빈 목록의 사유는 Python 이 낸다(`empty_hint`). */
  emptyFallback: string;
};

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 행 앞머리 표지 — 어휘 전수는 Python 이 소유한다(`webapp/pool_column.POOL_ICONS`).
 *
 *  선 글리프 하나로 통일한 이유: 상세 패널의 연결 카드(`library.ts`)와 이 열이 **같은
 *  것을 가리키면 같은 그림**이어야 한다. 종전에는 좌 열이 테두리 상자, 상세 패널이 SVG 라
 *  같은 템플릿이 두 자리에서 다른 모양이었다. 미지 값(`other`)은 숨기지 않고 민 종이로
 *  선다 — 그 행 자체는 사유와 함께 서 있어야 한다. */
export function poolGlyph(icon: string): ReactNode {
  const common = { viewBox: "0 0 20 20", "aria-hidden": "true", focusable: "false" };
  if (icon === "hwpx") {
    return h("svg", common,
      h("path", { d: "M5 2.5h7l4 4v11H5z" }),
      h("path", { d: "M12 2.5v4h4" }));
  }
  if (icon === "txt") {
    return h("svg", common,
      h("path", { d: "M4.5 2.5h11v15h-11z" }),
      h("path", { d: "M7.5 7h5M7.5 10h5M7.5 13h3" }));
  }
  if (icon === "excel") {
    return h("svg", common,
      h("rect", { x: "3", y: "4", width: "14", height: "12", rx: "1" }),
      h("path", { d: "M3 9h14M8 4v12" }));
  }
  if (icon === "pclm") {
    return h("svg", common,
      h("ellipse", { cx: "10", cy: "5.5", rx: "6", ry: "2.5" }),
      h("path", { d: "M4 5.5v9c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-9" }),
      h("path", { d: "M4 10c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" }));
  }
  return h("svg", common, h("path", { d: "M4.5 2.5h11v15h-11z" }));
}

/** 끌어 놓기 props — 좌·우 두 열이 **같은 규칙**을 쓴다.
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

/** 항목 하나 — 동결 시안 장면 1 의 `.pitem` 형(글리프 · 이름 · 부제 · pill)과 형제 ⋮.
 *
 *  ⋮ 를 버튼 **안**에 넣지 않는 이유는 하나다: 버튼 안의 버튼은 만들지 않는다. */
function PoolRow(props: { row: Obj; host: PoolColumnHost }): ReactNode {
  const { row, host } = props;
  const key = String(row.key);
  const selectable = !!row.selectable;
  const reason = String(row.reason || "");
  const current = host.selectedKey !== "" && host.selectedKey === key;
  const warns = (row.warns || []) as string[];
  return h("div", { className: "pitem-wrap" },
    h("button", {
      type: "button", className: "pitem", "data-act": "pick", "data-path": row.path,
      /* 행의 **정체 좌표** — 끌기 결속과 무관하게 선다. 종전에는 이 값을 `dragProps` 가
         얹어서, 끌기가 없는 호스트(다이얼로그)의 행은 자기 키를 말하지 못했다(같은 행을
         겨눈 게이트가 좌표를 잃는 자리). 끌기 쪽이 드는 것은 `data-side` 하나다. */
      "data-key": key,
      /* 못 고르는 행도 **눌린다** — `disabled` 면 클릭이 오지 않아 사유를 말할 자리가
         없다. 「고름」 축은 고를 수 있는 행에서만 의미가 있어 그때만 선다. */
      "aria-pressed": selectable ? (current ? "true" : "false") : undefined,
      "aria-disabled": selectable ? undefined : "true",
      onClick: () => { host.choose(key); },
      ...dragProps(
        host.drop === undefined ? undefined : {
          side: host.side,
          onDrop: host.drop,
          /* 거절도 **클릭과 같은 한 자리**를 지난다: 호스트가 행을 다시 찾아 이름과
             Python 사유로 재진술한다(문형 두 벌 금지). */
          onRefuse: (_why: string, refusedKey: string) => { host.choose(refusedKey); },
        },
        key, selectable, reason,
      ),
    },
    h("span", { className: "ic", "aria-hidden": "true" }, poolGlyph(String(row.icon || ""))),
    h("span", { className: "pitem-text" },
      h("span", { className: "nm" }, String(row.name || "")),
      h("span", { className: "sb" }, String(row.sub || "")),
      reason ? h("span", { className: "sb why" }, reason) : null,
      /* 사전 고지는 사유와 **다른 축**이다(#154) — 고를 수 있는 행도 미리 알릴 것이 있고,
         목록에서 걷으면 그 사실이 조용히 사라진다. */
      ...warns.map((warn: string, index: number) =>
        h("span", { className: "sb warn", key: index }, String(warn)))),
    h("span", { className: `pill ${row.badge_level || "muted"}` },
      String(row.badge_label || ""))),
    host.onMore ? h("button", {
      className: "job-more", "data-act": "lib-more", "data-side": host.side,
      "data-media": String(row.icon || ""), "data-key": key,
      "aria-haspopup": "true", "aria-label": "항목 관리",
      onClick: (event: Obj) => { host.onMore?.(row, event.currentTarget); },
    }, "⋮") : null);
}

/** 존 통지 — 손상 격리(danger)·중복 등록(warn). **문안·수치는 Python 이 낸다.**
 *
 *  통지가 지시하는 처분은 그 통지와 **같은 자리**에 선다: 「골라 정리하세요」라고 말하면서
 *  고를 자리가 없으면 사람이 지시를 실행할 수 없다. */
function PoolNotice(props: { notice: Obj; host: PoolColumnHost }): ReactNode {
  const { notice, host } = props;
  const level = String(notice.level || "warn");
  return h("div", {
    className: `note ${level === "danger" ? "dangerbox" : "warnbox"}`, "data-notice": level,
  },
  String(notice.text || ""),
  ...((notice.actions || []) as Obj[]).map((action: Obj) => h("button", {
    className: "btn sm", "data-notice-act": String(action.key), "data-busy-lock": true,
    key: String(action.key) + String(JSON.stringify(action.payload || {})),
    onClick: () => { host.onNoticeAction?.(String(action.key), (action.payload || {}) as Obj); },
  }, String(action.label || ""))));
}

/** 열 하나 — 머리 · 목록(통지 + 행) · 바닥 동사 줄 · 결과 줄. */
export function PoolColumn(props: { host: PoolColumnHost; column: Obj | null }): ReactNode {
  const { host, column } = props;
  const rows = ((column || {}).rows || []) as Obj[];
  const notices = ((column || {}).notices || []) as Obj[];
  const result = ((column || {}).result || {}) as Obj;
  /* 빈 사유는 **Python 이 낸다**(`empty_hint`): 미지정·폴더 없음·빈 폴더는 서로 다른
     사유이고, 여기서 한 문장으로 접으면 사라진 폴더가 「비었다」로 읽힌다. 이 자리 문안이
     서는 것은 스냅샷이 아직 없을 때뿐이다. */
  const emptyText = String((column === null ? "" : column.empty_hint) || host.emptyFallback);
  return h("section", {
    className: "pool poolcol", id: host.rootId, "aria-label": host.title,
  },
  h("div", { className: "pool-head" },
    h("h2", null, host.title),
    h("span", { className: "sub", title: host.headSubTitle }, host.headSub),
    host.reload ? h("button", {
      className: "btn sm reload", "data-act": "refresh", "data-side": host.side,
      title: "다시 읽습니다",
      onClick: () => { host.reload?.(); },
    }, "새로 읽기") : null),
  h("div", { className: "pool-list", id: host.listId },
    ...notices.map((notice: Obj, index: number) =>
      h(PoolNotice as any, { key: `notice-${index}`, notice, host })),
    ...(rows.length
      ? rows.map((row: Obj) => h(PoolRow as any, { key: String(row.key), row, host }))
      : [h("p", {
        className: "muted capnote", key: "empty", style: { whiteSpace: "pre-line" },
      }, emptyText)])),
  host.acts ? h("div", { className: "pool-acts" }, host.acts) : null,
  /* 결과 줄 — 동사가 나가는 **그 열의 바닥**에 선다(U6-E #979). 종전에는 세 열 밑에
     떨어져 있어, 왼쪽에서 누른 변환의 성과를 다른 곳에서 찾아야 했다. */
  result.text ? h("div", {
    className: `run-result${result.level && result.level !== "muted" ? " " + result.level : ""}`,
  }, String(result.text)) : null);
}
