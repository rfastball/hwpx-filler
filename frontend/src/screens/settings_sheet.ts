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
 */

import { createElement, useCallback, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

type Obj = Record<string, any>;

/** 셸 서비스의 최소 포트 — 구현은 `shell/preferences.ts` 가, 테스트는 대역이 댄다. */
export type SettingsThemePort = { current(): string; set(mode: string): unknown };
export type SettingsPersonalizationPort = {
  currentFontScale(): string;
  setFontScale(scale: string): unknown;
};
export type SettingsModalPort = { close(id: string): void };

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

export function SettingsSheet(props: {
  theme: SettingsThemePort;
  personalization: SettingsPersonalizationPort;
  modal: SettingsModalPort;
}): ReactNode {
  const { theme, personalization } = props;
  const currentTheme = useShellValue("hwpx:themechange", () => theme.current());
  const currentScale = useShellValue(
    "hwpx:personalizationchange", () => personalization.currentFontScale(),
  );
  return createElement(SettingsSheetView as any, { ...props, currentTheme, currentScale });
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
  currentTheme: string;
  currentScale: string;
}): ReactNode {
  const { theme, personalization, modal, currentTheme, currentScale } = props;

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
        }))));
}
