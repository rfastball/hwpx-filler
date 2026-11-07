/* HWPX 편집면 마운트의 호스트 쪽 판독 — `rhwp_editor.ts` 의 `mountRhwp` 가 쓴다.
 *
 * 앱의 테마·글자 배율, Studio 페이지 주소, 호스트가 그려져 있는지, Studio 와 주고받는 HWPX 바이트의 base64 변환. */

export type Appearance = { theme: 'light' | 'dark' | 'system'; fontScale: 1 | 1.25 | 1.5 };

/** The app's theme and font scale (`html[data-theme]`, `html[data-font-scale]`) as the Studio takes them. */
export function hostAppearance(root: { getAttribute(name: string): string | null } | null | undefined): Appearance {
  const theme = root?.getAttribute("data-theme");
  const scale = root?.getAttribute("data-font-scale");
  return { theme: theme === "light" || theme === "dark" ? theme : "system",
    fontScale: scale === "larger" ? 1.5 : scale === "large" ? 1.25 : 1 };
}

/** The Studio page URL. The Studio applies the host theme before its first paint (theme-init.js); later changes go
 *  by message. */
export function studioUrlFor(appearance: Appearance): string {
  const studioUrl = new URL("/rhwp/studio/index.html", document.baseURI);
  studioUrl.searchParams.set("hostTheme", appearance.theme);
  studioUrl.searchParams.set("hostFontScale", String(appearance.fontScale));
  // The product keeps no recovery drafts (#1068): every mount (editor, trial result, comparison) turns the Studio's
  // own autosave off — no interval or idle draft is written and no 「문서 복구」 dialog offers another document's body.
  studioUrl.searchParams.set("autosave", "off");
  return studioUrl.href;
}

/** The host is rendered: no `hidden`/`inert` ancestor (inactive document tabs) and laid out. */
export function hostRendered(host: HTMLElement): boolean {
  if (typeof host.closest === "function" && host.closest("[hidden],[inert]")) return false;
  return !("offsetParent" in host) || host.offsetParent !== null;
}

export function decodeBase64(value: string): Uint8Array {
  return Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
}
export function encodeBase64(bytes: Uint8Array): string {
  let result = "";
  for (let offset = 0; offset < bytes.length; offset += 32768)
    result += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  return btoa(result);
}
