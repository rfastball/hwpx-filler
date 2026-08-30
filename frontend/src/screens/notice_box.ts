/* U4-G3(#945 F4) — 화면 중립 알림 상자.

   같은 결함류가 세 번 잡혔다(#874 `saveMessage` · #933 편집기 `notice` · 지금 job
   `data_notice`): **세우는 전이는 있는데 끄는 전이가 없는 채널**이다. 화면마다 수제로
   ✕ 를 붙이는 수리를 반복하는 대신, 수동 소멸 알림의 닫기를 **컴포넌트 문법**으로
   강제한다 — `onClose` 는 선택 항목이 아니라 필수라 「닫을 수 없는 NoticeBox」는 타입
   수준에서 만들 수 없다. 매 변이에 자동 소멸하는 알림(workbench·job_run·job_slot_config)
   은 끄는 동사가 이미 있으므로 이 컴포넌트를 **쓰지 않으면 된다**.

   이 경계가 소유하는 것은 **상자와 닫기뿐**이다. 문안 조립(「확인 필요: 」 접두, `⚠ `
   표지)·레벨 판정·언제 서는가는 종전 소유자가 그대로 진다 — 같은 상태를 두 곳이
   판정하게 만들지 않는다. */
import { createElement } from "react";
import type { ReactNode } from "react";

/** 상자 문법의 시각 레벨 — `.note` 뒤에 붙는 기존 변형 클래스로 그대로 번역된다. */
export type NoticeLevel = "warn" | "danger" | "ok" | "quiet";

const BOX_CLASS: Readonly<Record<NoticeLevel, string>> = {
  warn: "warnbox",
  danger: "dangerbox",
  ok: "okbox",
  /* 「정상은 조용히」(F32) — 박스 없이 muted 한 줄. 배치만 상자 문법을 공유한다. */
  quiet: "quiet",
};

export function NoticeBox(props: {
  /** 이미 조립된 최종 문안. 접두·표지는 부르는 쪽이 붙인다. */
  text: string;
  /** **필수** — 닫기 없는 알림을 만들 수 없게 하는 것이 이 컴포넌트의 요지다. */
  onClose: () => void;
  level?: NoticeLevel;
  /** 상자 노드의 id — 기존 좌표(`save-msg`·`jobDataNotice`)를 든 게이트가 소비한다. */
  id?: string;
  /** 닫기 단추의 id — 프로브·대본이 겨눌 좌표. */
  closeId?: string;
  /** 상자 태그. 기존 알림의 여백(문단 기본 margin)을 보존해야 하는 자리만 `p`. */
  tag?: "p" | "div";
}): ReactNode {
  const { closeId, id, onClose, tag, text } = props;
  const level: NoticeLevel = props.level ?? "warn";
  return createElement(tag ?? "div", {
    className: `note ${BOX_CLASS[level]} note-dismissable`,
    id,
    /* 여러 줄 통지의 줄바꿈을 살린다 — 문안이 한 줄로 뭉치면 사유가 안 읽힌다. */
    style: { whiteSpace: "pre-line" },
  },
  createElement("span", { className: "note-text" }, text),
  createElement("button", {
    className: "note-close", id: closeId, type: "button",
    "aria-label": "알림 닫기",
    onClick: onClose,
  }, "✕"));
}
