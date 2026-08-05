/* React overlay host (R3-01 · #410) — 완전 데이터-구동 표면 4(confirm·choose·prompt·토스트)의
 * React 소유 DOM 과 명령형 집행.
 *
 * ## 동기 계약은 구조로 선다 — flushSync 가 아니라
 *
 * live 프로브(modal_a11y)는 파사드 호출 **직후 같은 동기 턴**에 DOM 을 읽고, 같은 요소
 * 참조를 open↔close 를 가로질러 재사용하며, 첫 open 전에 닫힘 display 를 판독한다(패킷
 * rev3 개정 3 의 3중 전제). 그 셋의 직접 구현이 이 파일의 형태다: React 는 골격을 **1회
 * 렌더**하고(mount/dispose·리스너 수명주기 소유), 동적 전이(문안·클래스·포커스·퇴장)는
 * 이 모듈의 명령형 컨트롤러가 ref 노드 위에서 **동기 집행**한다. 상태 재렌더가 없으므로
 * 노드 정체성이 유지되고, 파사드 호출과 같은 턴에 DOM 이 전이한다 — modal.js 가 증명해
 * 온 거동을 React 소유 DOM 위로 옮기는 최소 재유도 경로다.
 *
 * ## 소유 경계
 *
 * 문안·기본 라벨·danger 판정·거절 재진술은 파사드(legacy modal.js)가 계속 소유한다 —
 * 이 파일은 **해석된 spec** 을 받아 그린다(파괴 확정 감사·문안 그물이 legacy 층 원문
 * 위에서 완전하다는 형제 패킷 판정과 정합). 스택·직렬화·Escape/Tab 판정은 엔진
 * (`engine.ts`) 소유이고 여기는 집행자다. 문서 리스너도 이 파일 소유가 아니다 —
 * dismissal 계열은 bootProduct 구성 시 상시(bootstrap.js·개정 10), 모달 keydown 은
 * 첫 open 부착·스택 빌 때 해제(instance.ts·개정 4)라, React 마운트가 실패해도 legacy
 * 모달의 Escape/Tab 이 조용히 죽는 두 번째 실행 경로가 없다. */
import { createElement, useEffect, useRef } from "react";
import type { ReactNode, RefObject } from "react";

import { overlayEngine, setOverlayDialogHost } from "./instance.ts";
import type { DialogHost } from "./instance.ts";
import type { OverlayExecutor } from "./engine.ts";

/** CSS 160ms 전이가 없거나 transitionend 가 누락될 때만 쓰는 안전망(modal.js 계약 승계). */
const CLOSE_FALLBACK_MS = 220;

export type OverlayHostPorts = {
  doc: Document;
  /** 실패 재진술(토스트 되돌리기 실패·골격 불량 거절) — window.alert 은 주입으로 받는다. */
  notify: (message: string) => void;
};

/* ── 집행 헬퍼 — modal.js 의 검증된 거동을 그대로 옮긴다 ── */

function focusables(root: HTMLElement): HTMLElement[] {
  const list = root.querySelectorAll<HTMLElement>(
    "button, input, textarea, select, [href], [tabindex]",
  );
  return Array.prototype.filter.call(list, (node: HTMLElement) => {
    const disabled = (node as { disabled?: boolean }).disabled === true;
    return !disabled && node.tabIndex !== -1 && node.offsetParent !== null;
  });
}

/** 경계(첫↔끝)와 바깥 이탈에서만 개입한다 — 반환은 개입 여부(preventDefault 조건). */
function trapWithin(root: HTMLElement, backward: boolean, doc: Document): boolean {
  const list = focusables(root);
  if (!list.length) return true;
  const first = list[0];
  const last = list[list.length - 1];
  const current = doc.activeElement;
  const inside = current !== null && root.contains(current);
  if (backward) {
    if (!inside || current === first) {
      last.focus();
      return true;
    }
    return false;
  }
  if (!inside || current === last) {
    first.focus();
    return true;
  }
  return false;
}

/** 옮겨 보고 확인 — 판정을 흉내내지 않고 결과를 읽는다(modal.js restoreFocus 규율).
 *  실패 시 지금 서 있는 화면 루트(.scr.on)에 착지한다. */
function restoreFocusTo(target: unknown, doc: Document): void {
  const candidate = target as { focus?: () => void; isConnected?: boolean } | null;
  if (candidate && typeof candidate.focus === "function" && candidate.isConnected !== false) {
    candidate.focus();
    if (doc.activeElement === candidate) return;
  }
  const screen = doc.querySelector<HTMLElement>(".scr.on");
  if (screen === null) return;
  if (!screen.hasAttribute("tabindex")) screen.setAttribute("tabindex", "-1");
  screen.focus();
}

type SettleMachinery = {
  timer: ReturnType<typeof setTimeout> | null;
  onTransitionEnd: ((event: TransitionEvent) => void) | null;
};

/** React 다이얼로그 하나의 집행자 — 전이 시작·정착 안전망·트랩·복귀 전부 이 안이다. */
function makeExecutor(args: {
  root: HTMLElement;
  doc: Document;
  initialFocus: () => HTMLElement | null;
  returnFocus: unknown;
}): OverlayExecutor {
  const { root, doc } = args;
  const card = root.querySelector<HTMLElement>(".modal-card");
  const machinery: SettleMachinery = { timer: null, onTransitionEnd: null };

  return {
    show(depth: number): void {
      root.style.setProperty("--modal-depth", String(depth));
      root.classList.remove("is-closing");
      root.classList.remove("hidden");
    },
    focusInitial(): void {
      const target = args.initialFocus();
      if (target !== null) target.focus();
    },
    beginClose(): void {
      root.classList.add("is-closing");
      if (card !== null) {
        machinery.onTransitionEnd = (event: TransitionEvent) => {
          if (event.target === card
            && (event.propertyName === "opacity" || event.propertyName === "transform")) {
            overlayEngine.settleClose(root);
          }
        };
        card.addEventListener("transitionend", machinery.onTransitionEnd);
      }
      machinery.timer = setTimeout(() => {
        overlayEngine.settleClose(root);
      }, CLOSE_FALLBACK_MS);
    },
    finishClose(): void {
      if (machinery.timer !== null) clearTimeout(machinery.timer);
      machinery.timer = null;
      if (card !== null && machinery.onTransitionEnd !== null) {
        card.removeEventListener("transitionend", machinery.onTransitionEnd);
      }
      machinery.onTransitionEnd = null;
      root.classList.add("hidden");
      root.classList.remove("is-closing");
      root.style.removeProperty("--modal-depth");
    },
    trapTab(backward: boolean): boolean {
      return trapWithin(root, backward, doc);
    },
    restoreFocus(): void {
      restoreFocusTo(args.returnFocus, doc);
    },
  };
}

function setText(node: HTMLElement | null, text: string): void {
  if (node !== null) node.textContent = text;
}

/* ── 다이얼로그 세션 — _promiseModal 의 정착 단일화·리스너 부착/해제·안전측 거절 이식 ── */

type DialogRefs = {
  root: HTMLElement;
  ok: HTMLButtonElement;
  cancel: HTMLButtonElement;
  alt: HTMLButtonElement | null;
  input: HTMLInputElement | null;
  error: HTMLElement | null;
};

function runDialog<T>(args: {
  refs: DialogRefs;
  doc: Document;
  notify: (message: string) => void;
  refusal: T;
  prepare: () => void;
  initialFocus: () => HTMLElement | null;
  okValue: () => T;
  altValue?: T;
  validate?: (value: T) => unknown;
  returnFocus: unknown;
}): Promise<T> {
  const { refs, doc } = args;
  return new Promise<T>((resolve) => {
    /* 재진입 거절·문안은 파사드가 이미 판정했다 — 여기서의 실패는 호출 규약 위반이라
       조용히 접지 않고 안전측 거절 + 재진술한다(도달 불가 방어). */
    if (!overlayEngine.acquireDialog()) {
      args.notify("확인 창 직렬화가 어긋났습니다 — 요청을 실행하지 않았습니다.");
      resolve(args.refusal);
      return;
    }
    args.prepare();
    let settled = false;
    let closing = false;
    let closeValue: T = args.refusal;
    let validating = false;

    const cleanup = (): void => {
      refs.ok.removeEventListener("click", onOk);
      if (refs.alt !== null) refs.alt.removeEventListener("click", onAlt);
      refs.cancel.removeEventListener("click", onCancel);
      if (refs.input !== null) refs.input.removeEventListener("keydown", onInputKey);
    };
    const settle = (value: T): void => {
      if (settled) return;
      settled = true;
      overlayEngine.releaseDialog();
      resolve(value);
    };
    const finish = (value: T): void => {
      if (settled || closing) return;
      closing = true;
      closeValue = value;
      cleanup();
      overlayEngine.requestClose(refs.root);
    };
    async function onOk(): Promise<void> {
      if (validating) return;
      const value = args.okValue();
      if (args.validate) {
        validating = true;
        refs.ok.disabled = true;
        try {
          const error = await args.validate(value);
          if (error) {
            if (refs.error !== null) {
              refs.error.textContent = String(error);
              refs.error.style.display = "block";
            }
            return;
          }
        } finally {
          validating = false;
          refs.ok.disabled = false;
        }
      }
      finish(value);
    }
    function onAlt(): void {
      finish(args.altValue as T);
    }
    function onCancel(): void {
      finish(args.refusal);
    }
    function onInputKey(event: KeyboardEvent): void {
      if (event.isComposing || event.keyCode === 229) return;
      if (event.key === "Enter") {
        event.preventDefault();
        void onOk();
      }
    }
    refs.ok.addEventListener("click", onOk);
    if (refs.alt !== null) refs.alt.addEventListener("click", onAlt);
    refs.cancel.addEventListener("click", onCancel);
    if (refs.input !== null) refs.input.addEventListener("keydown", onInputKey);

    overlayEngine.open({
      host: refs.root,
      executor: makeExecutor({
        root: refs.root,
        doc,
        initialFocus: args.initialFocus,
        returnFocus: args.returnFocus ?? doc.activeElement,
      }),
      onClose: () => {
        if (!closing) {
          closing = true;
          closeValue = args.refusal;
          cleanup();
        }
        settle(closeValue);
      },
    });
  });
}

/* ── 골격 — index.html 에서 이전한 4 표면과 동일한 id·클래스·ARIA·초기 문안 ── */

function el(
  tag: string,
  props: Record<string, unknown> | null,
  ...children: ReactNode[]
): ReactNode {
  return createElement(tag, props, ...children);
}

function dialogSkeletons(refs: {
  confirm: RefObject<HTMLDivElement | null>;
  choose: RefObject<HTMLDivElement | null>;
  prompt: RefObject<HTMLDivElement | null>;
  toast: RefObject<HTMLDivElement | null>;
}): ReactNode[] {
  return [
    el("div", {
      key: "confirmModal", id: "confirmModal", ref: refs.confirm,
      className: "modal hidden", role: "dialog",
      "aria-modal": "true", "aria-labelledby": "confirmModalTitle",
    },
    el("div", { className: "modal-card" },
      el("h3", { id: "confirmModalTitle" }, "확인"),
      el("p", { className: "modal-body", id: "confirmModalBody" }),
      el("div", { className: "modal-actions" },
        el("button", { className: "btn", id: "confirmModalCancel" }, "취소"),
        el("button", { className: "btn primary", id: "confirmModalOk" }, "확인")))),
    el("div", {
      key: "chooseModal", id: "chooseModal", ref: refs.choose,
      className: "modal hidden", role: "dialog",
      "aria-modal": "true", "aria-labelledby": "chooseModalTitle",
    },
    el("div", { className: "modal-card" },
      el("h3", { id: "chooseModalTitle" }, "선택"),
      el("p", { className: "modal-body", id: "chooseModalBody" }),
      el("div", { className: "modal-actions" },
        el("button", { className: "btn", id: "chooseModalCancel" }, "머무르기"),
        el("button", { className: "btn", id: "chooseModalAlt" }),
        el("button", { className: "btn primary", id: "chooseModalOk" })))),
    el("div", {
      key: "promptModal", id: "promptModal", ref: refs.prompt,
      className: "modal hidden", role: "dialog",
      "aria-modal": "true", "aria-labelledby": "promptModalTitle",
    },
    el("div", { className: "modal-card" },
      el("h3", { id: "promptModalTitle" }, "입력"),
      el("p", { className: "modal-body", id: "promptModalBody" }),
      el("input", { className: "field", id: "promptModalInput", type: "text" }),
      el("p", {
        id: "promptModalError", className: "note dangerbox", role: "alert",
        style: { display: "none" },
      }),
      el("div", { className: "modal-actions" },
        el("button", { className: "btn", id: "promptModalCancel" }, "취소"),
        el("button", { className: "btn primary", id: "promptModalOk" }, "확인")))),
    el("div", {
      key: "undoToast", id: "undoToast", ref: refs.toast,
      className: "undo-toast", role: "status", "aria-live": "polite", hidden: true,
    },
    el("span", { id: "undoToastText" }),
    el("button", { className: "btn sm", id: "undoToastBtn" }, "되돌리기")),
  ];
}

function byId<T extends HTMLElement>(root: HTMLElement, id: string): T {
  const found = root.querySelector<T>(`#${id}`);
  if (found === null) {
    throw new Error(`overlay host 골격에 #${id} 가 없습니다 — 렌더 계약이 깨졌습니다.`);
  }
  return found;
}

/** 다이얼로그 골격의 호출 시점 판독 — 부재를 throw 가 아니라 null 로 알린다. 판정은
 *  호출자(컨트롤러)가 안전측 거절로 잇는다: 렌더 계약상 도달 불가여도, 외부 변이(노드
 *  제거·클래스 훼손)에 조용한 교착 대신 loud 거절이 서야 한다(개정 3-3·#92 리뷰 #4). */
function find<T extends HTMLElement>(root: HTMLElement, id: string): T | null {
  return root.querySelector<T>(`#${id}`);
}

/** 다이얼로그·토스트의 DOM 집행 컨트롤러 — React host effect 와 node 하니스가 **같은
 *  실물**을 세운다(React 는 골격 렌더와 수명주기만 얹는다). 골격 검증은 매 호출 실 DOM
 *  판독이다: root 의 `.modal` 상실·필수 자식 부재는 acquire 전에 안전측 거절 + loud 라
 *  pendingDialog 가 갇히지 않는다(base modal.js `_promiseModal` 가드의 승계). */
export function createOverlayDialogController(args: {
  doc: Document;
  notify: (message: string) => void;
  roots: { confirm: HTMLElement; choose: HTMLElement; prompt: HTMLElement; toast: HTMLElement };
}): { controller: DialogHost; dispose: () => void } {
  const { doc, notify, roots } = args;

  /* ── 토스트 — 1슬롯·10초·실패 재진술(undo_toast.js 거동 이식) ── */
  const toastText = byId<HTMLElement>(roots.toast, "undoToastText");
  const toastButton = byId<HTMLButtonElement>(roots.toast, "undoToastBtn");
  let undoAction: (() => unknown) | null = null;
  let toastTimer: ReturnType<typeof setTimeout> | null = null;
  const toastHide = (): void => {
    roots.toast.hidden = true;
    undoAction = null;
    if (toastTimer !== null) clearTimeout(toastTimer);
    toastTimer = null;
  };
  const onToastClick = async (): Promise<void> => {
    const action = undoAction;
    if (action === null) return;
    toastButton.disabled = true;
    try {
      await action();
      toastHide();
    } catch (thrown) {
      const failure = thrown as { message?: unknown } | null;
      notify(String((failure && failure.message) || thrown));
    } finally {
      toastButton.disabled = false;
    }
  };
  toastButton.addEventListener("click", onToastClick);

  function refuse<T>(id: string, missingText: string, refusal: T): Promise<T> {
    console.error("Modal: 다이얼로그 골격 부재/불량 — " + id);
    notify(missingText);
    return Promise.resolve(refusal);
  }

  const controller: DialogHost = {
    confirm(spec) {
      const ok = find<HTMLButtonElement>(roots.confirm, "confirmModalOk");
      const cancel = find<HTMLButtonElement>(roots.confirm, "confirmModalCancel");
      if (!roots.confirm.classList.contains("modal") || ok === null || cancel === null) {
        return refuse("confirmModal", spec.missingText, false);
      }
      const refs: DialogRefs = { root: roots.confirm, ok, cancel, alt: null, input: null, error: null };
      return runDialog<boolean>({
        refs, doc, notify,
        refusal: false,
        prepare: () => {
          setText(find(roots.confirm, "confirmModalTitle"), spec.title);
          setText(find(roots.confirm, "confirmModalBody"), spec.body);
          ok.textContent = spec.confirmLabel;
          cancel.textContent = spec.cancelLabel;
          ok.classList.toggle("danger", spec.danger);
          ok.classList.toggle("primary", !spec.danger);
        },
        initialFocus: () => cancel,
        okValue: () => true,
        returnFocus: spec.returnFocus,
      });
    },
    prompt(spec) {
      const ok = find<HTMLButtonElement>(roots.prompt, "promptModalOk");
      const cancel = find<HTMLButtonElement>(roots.prompt, "promptModalCancel");
      const input = find<HTMLInputElement>(roots.prompt, "promptModalInput");
      if (!roots.prompt.classList.contains("modal") || ok === null || cancel === null || input === null) {
        return refuse("promptModal", spec.missingText, null);
      }
      const refs: DialogRefs = {
        root: roots.prompt, ok, cancel, alt: null, input,
        error: find<HTMLElement>(roots.prompt, "promptModalError"),
      };
      return runDialog<string | null>({
        refs, doc, notify,
        refusal: null,
        prepare: () => {
          setText(find(roots.prompt, "promptModalTitle"), spec.title);
          setText(find(roots.prompt, "promptModalBody"), spec.body);
          input.value = spec.value;
          if (refs.error !== null) {
            refs.error.textContent = "";
            refs.error.style.display = "none";
          }
        },
        initialFocus: () => input,
        okValue: () => input.value,
        validate: spec.validate as ((value: string | null) => unknown) | undefined,
        returnFocus: spec.returnFocus,
      });
    },
    choose(spec) {
      const ok = find<HTMLButtonElement>(roots.choose, "chooseModalOk");
      const cancel = find<HTMLButtonElement>(roots.choose, "chooseModalCancel");
      const alt = find<HTMLButtonElement>(roots.choose, "chooseModalAlt");
      if (!roots.choose.classList.contains("modal") || ok === null || cancel === null || alt === null) {
        return refuse("chooseModal", spec.missingText, spec.refusal.value);
      }
      const refs: DialogRefs = { root: roots.choose, ok, cancel, alt, input: null, error: null };
      return runDialog<string>({
        refs, doc, notify,
        refusal: spec.refusal.value,
        altValue: spec.alt.value,
        prepare: () => {
          setText(find(roots.choose, "chooseModalTitle"), spec.title);
          setText(find(roots.choose, "chooseModalBody"), spec.body);
          ok.textContent = spec.primary.label;
          alt.textContent = spec.alt.label;
          cancel.textContent = spec.refusal.label;
        },
        initialFocus: () => cancel,
        okValue: () => spec.primary.value,
        returnFocus: spec.returnFocus,
      });
    },
    toastShow(message, undo) {
      setText(toastText, message);
      undoAction = undo;
      roots.toast.hidden = false;
      if (toastTimer !== null) clearTimeout(toastTimer);
      toastTimer = setTimeout(toastHide, 10000);
    },
    toastHide,
  };

  return {
    controller,
    dispose: () => {
      toastButton.removeEventListener("click", onToastClick);
      toastHide();
    },
  };
}

/** 다이얼로그·토스트 host — 트리에 정확히 하나. 골격을 1회 렌더하고 mount effect 가
 *  컨트롤러 슬롯·문서 리스너·토스트 배선을 세우며 cleanup 이 대칭으로 걷는다. */
export function OverlayHost(ports: OverlayHostPorts): ReactNode {
  const confirmRef = useRef<HTMLDivElement | null>(null);
  const chooseRef = useRef<HTMLDivElement | null>(null);
  const promptRef = useRef<HTMLDivElement | null>(null);
  const toastRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const confirmRoot = confirmRef.current;
    const chooseRoot = chooseRef.current;
    const promptRoot = promptRef.current;
    const toastRoot = toastRef.current;
    if (confirmRoot === null || chooseRoot === null || promptRoot === null || toastRoot === null) {
      throw new Error("overlay host 골격이 마운트되지 않았습니다 — 렌더 계약이 깨졌습니다.");
    }

    /* 컨트롤러(파사드가 호출 시점 슬롯으로 닿는 DOM 집행 표면)는 팩토리가 세운다 —
       React 의 몫은 골격 렌더와 이 수명주기(슬롯 대입·cleanup 대칭 회수)뿐이다. */
    const { controller, dispose } = createOverlayDialogController({
      doc: ports.doc,
      notify: ports.notify,
      roots: { confirm: confirmRoot, choose: chooseRoot, prompt: promptRoot, toast: toastRoot },
    });
    const releaseHost = setOverlayDialogHost(controller);

    return () => {
      releaseHost();
      dispose();
    };
    /* ports 는 boot 늦은 결속 슬롯이 대는 안정 참조 — 재구성은 reload(신품 그래프)뿐이다. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return el(
    "div",
    { id: "reactOverlayHost" },
    ...dialogSkeletons({ confirm: confirmRef, choose: chooseRef, prompt: promptRef, toast: toastRef }),
  );
}
