/* R1-02 소유권 인벤토리 — 공통 범위·경로·정규식 상수와 소스 수집기.
 *
 * `extract_js_ast_axes.mjs`의 축들이 공유하는 것(파일 오프셋→줄 번호 변환, AST 범용 walk,
 * 저장소 상대 소스 수집, 정적 폐포 계약 상수, markup/id 정규식)을 모은다. 값은 분리 전과
 * 완전히 같고, `sources()`의 포함 판정만 이름이 선 보조함수로 추출했다(함수 복잡도 예산).
 */
import { readFileSync, globSync, statSync } from "node:fs";
import { join, sep } from "node:path";

/** 파일 오프셋 → 1-기반 줄 번호. 좌표가 원장 증거의 단위라 반올림하지 않는다. */
export function lineIndex(source) {
  const starts = [0];
  for (let i = 0; i < source.length; i += 1) {
    if (source[i] === "\n") starts.push(i + 1);
  }
  return (offset) => {
    let low = 0;
    let high = starts.length - 1;
    while (low < high) {
      const mid = (low + high + 1) >> 1;
      if (starts[mid] <= offset) low = mid;
      else high = mid - 1;
    }
    return low + 1;
  };
}

export const SKIP_KEYS = new Set(["type", "start", "end", "range", "loc", "parent"]);

export function walk(node, visit) {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node)) {
    for (const child of node) walk(child, visit);
    return;
  }
  if (typeof node.type === "string") visit(node);
  for (const key of Object.keys(node)) {
    if (!SKIP_KEYS.has(key)) walk(node[key], visit);
  }
}

/* ── 범위 ──────────────────────────────────────────────────────────
 *
 * 확장자를 열거하지 않는다. 정적 폐포 계약(#490)이 코드가 **아닌** 접미사만 들고, 제품
 * 프런트 전수에서 그것을 감산한다. 새 `.tsx`·다음 코드 형식은 자동 편입되며, 파서가 못
 * 읽는 형식이면 조용히 누락되지 않고 실패한다.
 */
const STATIC_CLOSURE = JSON.parse(readFileSync(
  new URL("../../tests/static_closure_contract.json", import.meta.url),
  "utf8",
));
export const NON_CODE_SUFFIXES = STATIC_CLOSURE.non_code_suffixes;
export const PRODUCT_SCOPE = ["frontend/**/*"];
export const OXC_SUFFIXES = new Set([".js", ".mjs"]);
export const SELFTEST_SCOPE = ["frontend/src/selftest/**/*.js", "frontend/src/selftest/**/*.mjs"];
export const SELFTEST_PREFIX = "frontend/src/selftest/";
/* R5-99 B1·S1 뒤 이 목록이 가리는 것은 **리스너 대칭 잔차 하나**다 — DOM 생성 술어는
   제품 폐포 전체를 보고, 여기는 React effect cleanup 계약의 정의역(overlay·shell·screens)만
   남는다. 선언 scope(원장·게이트)와 이 목록은 같은 셋이어야 한다 — 어긋나면 S1 재발. */
export const REACT_HOST_PREFIXES = [
  "frontend/src/overlay/",
  "frontend/src/shell/",
  "frontend/src/screens/",
];

/* ── 축 1·3 공용 정규식 ───────────────────────────────────────────── */
export const ID_ATTR = /(?<![\w-])id="([^"]*)$|(?<![\w-])id="([^"]*)"/g;
export const MARKUP_DATA_ATTR = /[\s<](data-[a-z][a-z0-9-]*)(?=\s|=|\/?>|$)/g;
export const BARE_MARKUP_DATA_ATTR = /^(data-[a-z][a-z0-9-]*)(?=\s|=|$)/g;
export const DYNAMIC_MARKUP_DATA_ATTR = /(?:^|[\s<])data-$/;

function isExcludedSelftest(rel, excludeSelftest) {
  return excludeSelftest && rel.startsWith(SELFTEST_PREFIX);
}

function isExcludedNonCode(rel, excludeNonCode) {
  return excludeNonCode && NON_CODE_SUFFIXES.some((suffix) => rel.endsWith(suffix));
}

function isIncludedSource(rel, { excludeSelftest, excludeNonCode }) {
  if (isExcludedSelftest(rel, excludeSelftest)) return false;
  if (isExcludedNonCode(rel, excludeNonCode)) return false;
  return true;
}

/** 멤버 키는 **저장소 상대 POSIX 경로**다 — OS 마다 달라지면 원장이 못 산다. */
export function sources(root, patterns, { excludeSelftest = false, excludeNonCode = false } = {}) {
  const seen = new Map();
  for (const pattern of [].concat(patterns)) {
    for (const raw of globSync(pattern, { cwd: root })) {
      const rel = raw.split(sep).join("/");
      if (!statSync(join(root, rel)).isFile()) continue;
      if (!isIncludedSource(rel, { excludeSelftest, excludeNonCode })) continue;
      if (!seen.has(rel)) seen.set(rel, { rel, text: readFileSync(join(root, rel), "utf8") });
    }
  }
  return [...seen.values()].sort((a, b) => (a.rel < b.rel ? -1 : a.rel > b.rel ? 1 : 0));
}
