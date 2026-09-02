/* 셸 설정 모달 — 토바 ⚙ 하나가 여는 전역 설정 면.
 *
 * ## 왜 순환 토글이 아니라 세그먼트인가
 *
 * 종전의 `#themeToggle`(◐)·`#fontScaleToggle`(A)은 **누르기 전에는** 지금 값도 고를 수 있는
 * 값도 말하지 않는 순환 버튼이었다. 값이 셋인 축을 순환으로 돌리면 원하는 값에 닿기까지
 * 화면 전체가 두 번 다시 그려지고, 되돌리려면 한 바퀴를 더 돈다. 세 값을 한 줄에 펴고
 * 지금 값을 `aria-pressed` 로 말하는 세그먼트가 같은 상태를 **보이게** 만든다.
 *
 * ## 판정·영속은 여기 없다
 *
 * 이 면이 지는 것은 「고르는 자리」 하나다. 현재값 판독·적용·영속은 전부 셸 서비스
 * (`shell/preferences.ts` 의 `createTheme`·`createPersonalization`)가 그대로 지고, 그쪽이
 * `bridge.setTheme`/`setFontScale` 로 Python settings 에 쓴다 — 이 컴포넌트가 추가한 왕복은
 * 하나도 없다. 그래서 현재값도 지역 상태로 복제하지 않고 서비스 판독 + 서비스가 내는
 * 사건(`hwpx:themechange`·`hwpx:personalizationchange`) 구독으로 **파생**한다: 부팅 주입
 * (`preferences` 처리기)·selftest 의 직접 `Theme.set` 같은 이 면 **밖의** 변경도 같은 사건을
 * 내므로, 표시가 어긋날 창이 구조적으로 없다.
 *
 * ## 행 목록은 자란다
 *
 * 마크업은 `.settings-row` 반복이다 — 라벨 한 칸 + 조작 한 칸. 축이 늘면 행이 하나 는다.
 *
 * ## 폴더 두 행만 제품 스냅샷을 읽는다
 *
 * 테마·글자 크기는 셸 서비스의 값이지만 **저장 폴더는 Python 이 도출한 값**이다(작업 화면
 * 스냅샷의 `output_folder` 존 — 설정한 폴더가 사라졌는지, 지금 쓰이는 경로가 무엇인지, 그
 * 출처가 무엇인지를 전부 backend 가 판정해 싣는다). 그래서 이 행은 job 컨트롤러를 **포트로**
 * 받아 그 스냅샷을 구독하고, 지역 상태를 만들지 않는다. 고르는 왕복(`pick_output_folder`)도
 * 그 컨트롤러의 것을 그대로 부른다 — 오류 재진술 규율이 거기 있고, 여기서 다시 조립하면
 * 같은 판정이 두 곳에 산다.
 *
 * **서식 폴더 행도 같다**(U6-A #975): 값의 주인이 tpl 채널이라 그 스냅샷의 `templates_root`
 * 존을 구독한다. 다른 점은 두 가지뿐이다 — 채널이 편집기 동사에서만 밀리므로 첫 스냅샷은
 * 이 면이 직접 당기고(`init`), 재지정 성사 뒤에는 지금 화면을 한 번 다시 당긴다(목록의
 * 정본은 각 화면 스냅샷이다).
 */

import { createElement, useCallback, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { BridgeClient } from "../runtime/client.ts";
import { PathActions } from "./path_actions.ts";

type Obj = Record<string, any>;

/** 셸 서비스의 최소 포트 — 구현은 `shell/preferences.ts` 가, 테스트는 대역이 댄다. */
export type SettingsThemePort = { current(): string; set(mode: string): unknown };
export type SettingsPersonalizationPort = {
  currentFontScale(): string;
  setFontScale(scale: string): unknown;
};
export type SettingsModalPort = { close(id: string): void };

/** 저장 폴더 행이 쓰는 **구조적** 포트 — `JobRunController` 가 그대로 만족한다.
 *
 *  타입을 import 하지 않고 형태로만 적는 이유는 순환이다: `job_run.ts` 가 이 파일의
 *  `SETTINGS_MODAL_ID` 를 값으로 가져간다(배달 blocker 의 착지가 이 모달을 연다). 필요한 것은
 *  구독 하나·판독 하나·동사 하나뿐이라 형태로 충분하다. */
export type SettingsOutputFolderPort = {
  subscribe(listener: () => void): () => void;
  /** 컨트롤러의 실행 상태 저장소. `lastFull` 이 마지막 전체 스냅샷, `running` 이 생성 진행. */
  getRun(): { running?: boolean; lastFull?: Obj | null };
  pickOutputFolder(): unknown;
  client: BridgeClient;
  notify(message: string): void;
};

/** 생성이 도는 동안 폴더를 못 바꾸는 **사유** — 조용히 비활성으로 두지 않는다. */
export const OUTPUT_FOLDER_BUSY_REASON = "문서를 만드는 중에는 저장 폴더를 바꿀 수 없습니다.";
/** 도출 자체가 불가능할 때의 자리 문안(경로 칸이 빈 채로 서는 것을 막는다). */
export const OUTPUT_FOLDER_EMPTY_TEXT = "아직 정해지지 않았습니다 — 폴더를 선택하세요.";

/** 서식 폴더 행이 쓰는 **구조적** 포트(U6-A #975) — tpl 채널 스냅샷 하나를 구독한다.
 *
 *  저장 폴더 포트와 형상이 같되 실행 상태를 따로 묻지 않는다: 잠금 판정은 저장 폴더 행과
 *  **같은 사실**(생성 진행)이라 그 행이 이미 읽는 값을 재사용하고, 여기서 두 번째 판정을
 *  세우지 않는다.
 *
 *  **첫 스냅샷을 이 면이 당기지 않는다**: 이 오버레이는 부팅에 상주 마운트라, 마운트 effect
 *  에서 호스트를 부르면 그 호출이 `pywebviewready` **앞**에 선다 — 실측에서 그 순서가
 *  WebView2 창을 아예 못 뜨게 했다(`loaded` 미발화 · `Main window failed to start`).
 *  그래서 `tpl` 첫 당김은 셸의 부팅 시퀀스(`initSequence`, 호스트 준비 뒤 발화)가 진다. */
export type SettingsTemplatesRootPort = {
  subscribe(listener: () => void): () => void;
  /** tpl 채널 모델 판독 — 안정 참조를 돌려줘야 한다(파생 객체 금지). */
  getSnapshot(): Obj | null;
  pickTemplatesRoot(): unknown;
  /** 재지정 성사 뒤 지금 화면을 다시 당긴다 — 목록의 정본은 각 화면 스냅샷이다. */
  refreshCurrentScreen(): unknown;
  /** 경로 어포던스(폴더에서 보기·경로 복사)가 쓰는 전송 표면. **이 포트가 직접 든다** —
   *  저장 폴더 포트의 것을 빌려 쓰면 두 행이 남의 컨트롤러에 묶인다. */
  client: BridgeClient;
  notify(message: string): void;
};

/** 생성 중에 서식 폴더를 못 바꾸는 사유 — 저장 폴더와 같은 규율(조용히 막지 않는다). */
export const TEMPLATES_ROOT_BUSY_REASON =
  "문서를 만드는 중에는 서식 폴더를 바꿀 수 없습니다.";
/** 루트가 아직 도출되지 않은 자리 문안(경로 칸이 빈 채로 서는 것을 막는다). */
export const TEMPLATES_ROOT_EMPTY_TEXT = "아직 읽지 못했습니다 — 폴더를 선택하세요.";

/** 모달 DOM id — 여는 쪽(shell/app.ts)과 닫는 쪽(이 파일)이 같은 상수를 쓴다. */
export const SETTINGS_MODAL_ID = "settingsModal";

/** 값 → 사용자 문안. `shell/app.ts` 의 라벨 사전을 그대로 이주한 것이다(문자열 무변경) —
 *  종전에는 토바 라벨 하나를 채우는 데 쓰였고 지금은 세그먼트 셋의 이름이 된다. */
export const THEME_LABELS = Object.freeze({
  system: "시스템", light: "라이트", dark: "다크",
} as Record<string, string>);
export const FONT_SCALE_LABELS = Object.freeze({
  normal: "기본", large: "크게 (125%)", larger: "더 크게 (150%)",
} as Record<string, string>);

/** 세그먼트 순서 = 서비스의 순환 순서 그대로(preferences.ts 의 `order`·`fontOrder`). */
export const THEME_MODES = Object.freeze(["system", "light", "dark"] as const);
export const FONT_SCALES = Object.freeze(["normal", "large", "larger"] as const);

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 셸 사건 하나를 구독해 현재값을 **파생**한다. 지역 상태가 아니라 판독이라 이 면 밖의
 *  변경(부팅 주입·프로브 직접 호출)도 같은 값에 도착한다. */
function useShellValue(eventName: string, read: () => string): string {
  const subscribe = useCallback((listener: () => void) => {
    /* 서비스가 `window` 에 사건을 내므로 창이 없는 환경(서버 렌더)에서는 구독할 것도 없다 —
       그 경우 getServerSnapshot 만 도므로 이 경로는 애초에 불리지 않는다. */
    window.addEventListener(eventName, listener);
    return () => { window.removeEventListener(eventName, listener); };
  }, [eventName]);
  return useSyncExternalStore(subscribe, read, read);
}

type SegmentProps = {
  /** 프로브·게이트가 무는 안정 좌표. 값 자체는 비어 있고 존재가 의미다. */
  axis: string;
  labelId: string;
  values: readonly string[];
  labels: Record<string, string>;
  current: string;
  onPick(value: string): void;
};

/** 3값 세그먼트 — 지금 값은 `aria-pressed` 하나로 말한다.
 *
 *  `data-busy-lock` 을 걸지 않는다: 이건 전역 개인화라 생성 진행 상태와 아무 관계가 없고,
 *  잠그면 「생성 중에는 글자 크기를 못 키운다」는 없는 규칙이 생긴다. */
function Segment(props: SegmentProps): ReactNode {
  const attrs: Obj = { className: "settings-seg", role: "group", "aria-labelledby": props.labelId };
  attrs[props.axis] = "";
  return h("div", attrs,
    ...props.values.map((value) => h("button", {
      key: value,
      type: "button",
      className: "btn settings-seg-opt",
      "data-value": value,
      "aria-pressed": props.current === value ? "true" : "false",
      onClick: () => { props.onPick(value); },
    }, props.labels[value] || value)));
}

/** 폴더 행 하나 — 라벨 + 읽기 전용 경로 + 「찾아보기…」 + 출처·사유 + 경로 어포던스.
 *
 *  **저장 폴더와 서식 폴더가 이 하나를 부른다.** 둘은 값의 채널과 도출 규칙만 다르고 형상은
 *  같다 — 사본으로 두면 한쪽에만 붙는 어포던스·잠금 사유가 생기고, 그 어긋남은 눈으로만
 *  잡힌다. DOM `id` 는 계약 좌표라 **호출자가 명시로 싣는다**(파생 조립 금지 — 프로브·
 *  게이트·live 대본이 그 문자열을 그대로 문다).
 *
 *  판정은 하나도 여기 없다: 경로·출처·사유는 Python 도출의 투영이고, `busy` 는 호출자가
 *  이미 읽은 실행 상태다. 이 면은 그리기와 클릭 전달만 한다. */
function FolderRow(props: {
  label: string;
  labelId: string;
  pathId: string;
  pickId: string;
  sourceId: string;
  noticeId: string;
  reasonId: string;
  view: OutputFolderView;
  emptyText: string;
  busyReason: string;
  onPick(): void;
  client: BridgeClient;
  notify(message: string): void;
}): ReactNode {
  const { view } = props;
  return h("div", { className: "settings-row settings-row-folder" },
    h("span", { className: "settings-label", id: props.labelId }, props.label),
    h("div", { className: "settings-folder" },
      h("div", { className: "settings-folder-row" },
        h("input", {
          className: "field ro", id: props.pathId, type: "text", readOnly: true,
          "aria-labelledby": props.labelId,
          value: view.directory,
          placeholder: props.emptyText,
        }),
        h("button", {
          className: "btn sm", id: props.pickId, type: "button",
          /* 생성 중에는 잠근다 — 이번 실행이 겨눈 폴더가 도중에 갈리면 결과가 어디서 왔고
             어디로 갔는지 말할 수 없다. 잠그되 **사유를 병기**한다(조용히 막지 않는다). */
          disabled: view.busy,
          title: view.busy ? props.busyReason : undefined,
          onClick: () => { props.onPick(); },
        }, "찾아보기…"),
        view.directory
          ? createElement(PathActions as any, {
            client: props.client,
            path: view.directory,
            only: ["reveal", "copy"],
            notify: props.notify,
          })
          : null),
      view.sourceLabel
        ? h("span", { className: "muted capnote", id: props.sourceId }, view.sourceLabel)
        : null,
      view.notice
        ? h("p", { className: "warn capnote", id: props.noticeId }, view.notice)
        : null,
      view.busy
        ? h("p", { className: "muted capnote", id: props.reasonId }, props.busyReason)
        : null));
}

/** 저장 폴더 행이 그리는 값 — 전부 Python 도출의 투영이다(여기서 판정하지 않는다). */
export type OutputFolderView = {
  directory: string;
  sourceLabel: string;
  notice: string;
  /** 생성 진행 — 참이면 「찾아보기…」가 비활성 + 사유 병기. */
  busy: boolean;
};

/** 서식 폴더 행이 그리는 값 — 저장 폴더와 같은 성분(둘 다 링0 도출의 투영이다). */
export type TemplatesRootView = OutputFolderView;

export function SettingsSheet(props: {
  theme: SettingsThemePort;
  personalization: SettingsPersonalizationPort;
  modal: SettingsModalPort;
  job: SettingsOutputFolderPort;
  templates: SettingsTemplatesRootPort;
}): ReactNode {
  const { theme, personalization, job, templates } = props;
  const currentTheme = useShellValue("hwpx:themechange", () => theme.current());
  const currentScale = useShellValue(
    "hwpx:personalizationchange", () => personalization.currentFontScale(),
  );
  /* 스냅샷 판독은 **파생**이다 — 컨트롤러 저장소를 그대로 구독하므로 이 면 밖의 변경(폴더를
     고른 뒤의 push, 생성 시작·종료)도 같은 값에 도착한다. `getRun` 은 안정 참조를 돌려주는
     저장소 판독이라 그것을 그대로 스냅샷 함수로 쓴다(파생 객체를 만들면 매 호출이 새 참조가
     돼 useSyncExternalStore 가 무한 재렌더에 든다). */
  const runState = useSyncExternalStore(job.subscribe, job.getRun, job.getRun);
  const folder = ((runState.lastFull || {}).output_folder || {}) as Obj;
  const outputFolder: OutputFolderView = {
    directory: String(folder.directory || ""),
    sourceLabel: String(folder.source_label || ""),
    notice: String(folder.notice || ""),
    busy: runState.running === true,
  };
  /* 서식 폴더도 같은 규율이다 — tpl 채널의 `templates_root` 존을 그대로 판독한다. */
  const tplState = useSyncExternalStore(
    templates.subscribe, templates.getSnapshot, templates.getSnapshot,
  );
  const root = ((tplState || {}).templates_root || {}) as Obj;
  const templatesRoot: TemplatesRootView = {
    directory: String(root.directory || ""),
    sourceLabel: String(root.source_label || ""),
    notice: String(root.notice || ""),
    busy: runState.running === true,
  };
  return createElement(SettingsSheetView as any, {
    ...props, currentTheme, currentScale, outputFolder, templatesRoot,
  });
}

/** 현재값을 **받아서** 그리는 순수 면 — 훅이 없다.
 *
 *  갈라 놓는 이유는 하나다: 이 면이 그리는 것과 클릭이 어디로 나가는지는 렌더러 없이도
 *  물을 수 있어야 하는데, 구독 훅이 몸통에 있으면 그 질문마다 실 렌더러가 필요해진다.
 *  파생(구독)은 위가, 형상·발신은 여기가 진다. */
export function SettingsSheetView(props: {
  theme: SettingsThemePort;
  personalization: SettingsPersonalizationPort;
  modal: SettingsModalPort;
  job: SettingsOutputFolderPort;
  templates: SettingsTemplatesRootPort;
  currentTheme: string;
  currentScale: string;
  outputFolder: OutputFolderView;
  templatesRoot: TemplatesRootView;
}): ReactNode {
  const { theme, personalization, modal, job, templates, currentTheme, currentScale } = props;
  const folder = props.outputFolder;
  const root = props.templatesRoot;

  /** 서식 폴더 재지정 — 성사(경로 문자열)면 지금 화면을 다시 당긴다. 취소는 `null`,
   *  실패는 `"ERROR: …"` 라 어느 쪽도 재당김을 걸지 않는다(브리지 규약 그대로). */
  const pickRoot = async (): Promise<void> => {
    const picked = await templates.pickTemplatesRoot();
    if (typeof picked === "string" && picked !== "" && !picked.startsWith("ERROR:")) {
      await templates.refreshCurrentScreen();
    }
  };

  return h("div", { className: "modal-card settings-card" },
    h("div", { className: "settings-head" },
      h("h3", { id: "settingsTitle" }, "설정"),
      h("button", {
        className: "btn", id: "settingsClose", type: "button",
        onClick: () => { modal.close(SETTINGS_MODAL_ID); },
      }, "닫기")),
    h("div", { className: "settings-body" },
      h("div", { className: "settings-row" },
        h("span", { className: "settings-label", id: "settingsThemeLabel" }, "테마"),
        createElement(Segment as any, {
          axis: "data-set-theme",
          labelId: "settingsThemeLabel",
          values: THEME_MODES,
          labels: THEME_LABELS,
          current: currentTheme,
          onPick: (value: string) => { theme.set(value); },
        })),
      h("div", { className: "settings-row" },
        h("span", { className: "settings-label", id: "settingsFontLabel" }, "글자 크기"),
        createElement(Segment as any, {
          axis: "data-set-font",
          labelId: "settingsFontLabel",
          values: FONT_SCALES,
          labels: FONT_SCALE_LABELS,
          current: currentScale,
          onPick: (value: string) => { personalization.setFontScale(value); },
        })),
      createElement(FolderRow as any, {
        label: "저장 폴더", labelId: "settingsFolderLabel",
        pathId: "settingsOutDir", pickId: "settingsPickFolder",
        sourceId: "settingsOutDirSource", noticeId: "settingsOutDirNotice",
        reasonId: "settingsPickFolderReason",
        view: folder, emptyText: OUTPUT_FOLDER_EMPTY_TEXT,
        busyReason: OUTPUT_FOLDER_BUSY_REASON,
        onPick: () => { void job.pickOutputFolder(); },
        client: job.client, notify: job.notify,
      }),
      createElement(FolderRow as any, {
        label: "서식 폴더", labelId: "settingsTplDirLabel",
        pathId: "settingsTplDir", pickId: "settingsPickTplFolder",
        sourceId: "settingsTplDirSource", noticeId: "settingsTplDirNotice",
        reasonId: "settingsPickTplFolderReason",
        view: root, emptyText: TEMPLATES_ROOT_EMPTY_TEXT,
        busyReason: TEMPLATES_ROOT_BUSY_REASON,
        onPick: () => { void pickRoot(); },
        client: templates.client, notify: templates.notify,
      })));
}
