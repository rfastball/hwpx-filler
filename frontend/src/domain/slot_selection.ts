/* S4 선택 언어의 TypeScript 미러 — Python `domain/slot_selection.py` 와 byte 동일
 * (S4-01 · #671). canonical byte framing 과 digest 는 두 언어가 같은 golden vector 를
 * 재현해야 한다: `tests/fixtures/slot_selection_v1_golden.json` 이 단일 오러클이다.
 *
 * 이 모듈은 DOM·React·저장소를 모른다. 순수 값·의미 계약만 소유한다. */

export const SELECTION_SET_SCHEMA_VERSION = "slot-selection-set/v1";
export const CANONICAL_ENCODING_VERSION = "slot-selection-canonical/v1";
export const EXACTLY_ONE = "EXACTLY_ONE";

const MAGIC = new Uint8Array([0x48, 0x46, 0x50, 0x53, 0x45, 0x4c, 0x31, 0x00]); // "HFPSEL1\0"
const U32_MAX = 0xffffffff;
const ENCODER = new TextEncoder();

export class SlotSelectionError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "SlotSelectionError";
    this.code = code;
  }
}

/** JS TextEncoder 는 lone surrogate 를 U+FFFD 로 조용히 치환한다 — Python 은 던진다.
 * parity 를 위해 encode 전에 명시로 거절한다. */
function requireScalarText(value: unknown, what: string): string {
  if (typeof value !== "string" || value === "") {
    throw new SlotSelectionError(
      "INVALID_SELECTION_SET",
      `${what} 는 비어 있지 않은 문자열이어야 한다`,
    );
  }
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        throw new SlotSelectionError(
          "INVALID_SELECTION_SET",
          `${what} 에 유효하지 않은 Unicode scalar`,
        );
      }
      i += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      throw new SlotSelectionError(
        "INVALID_SELECTION_SET",
        `${what} 에 유효하지 않은 Unicode scalar`,
      );
    }
  }
  return value;
}

export interface SlotSelection {
  slotId: string;
  selectedOptionIds: readonly string[];
}

export interface SlotSelectionSet {
  selections: readonly SlotSelection[];
}

/** 구문 불변식을 강제한다 — 값 모델 생성지에서 부른다. */
export function validateSelectionSet(set: SlotSelectionSet): SlotSelectionSet {
  if (!Array.isArray(set.selections)) {
    throw new SlotSelectionError(
      "INVALID_SELECTION_SET",
      "selections 는 배열이어야 한다",
    );
  }
  const seenSlots = new Set<string>();
  for (const selection of set.selections) {
    requireScalarText(selection.slotId, "slot_id");
    if (seenSlots.has(selection.slotId)) {
      throw new SlotSelectionError(
        "INVALID_SELECTION_SET",
        `같은 slot_id entry 중복: ${selection.slotId}`,
      );
    }
    seenSlots.add(selection.slotId);
    // 역직렬화·bridge 입력이 문자열이면 length·iteration 이 문자를 option 으로
    // 오인한다 — Python 의 tuple 검사와 parity 를 위해 배열을 먼저 강제한다.
    if (!Array.isArray(selection.selectedOptionIds)) {
      throw new SlotSelectionError(
        "INVALID_SELECTION_SET",
        "selected_option_ids 는 배열이어야 한다",
      );
    }
    if (selection.selectedOptionIds.length === 0) {
      throw new SlotSelectionError(
        "INVALID_SELECTION_SET",
        "selected_option_ids 는 비어 있을 수 없다",
      );
    }
    const seenOptions = new Set<string>();
    for (const optionId of selection.selectedOptionIds) {
      requireScalarText(optionId, "option_id");
      if (seenOptions.has(optionId)) {
        throw new SlotSelectionError(
          "INVALID_SELECTION_SET",
          `한 entry 안에서 option ID 중복: ${optionId}`,
        );
      }
      seenOptions.add(optionId);
    }
  }
  return set;
}

function compareBytes(a: Uint8Array, b: Uint8Array): number {
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i += 1) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return a.length - b.length;
}

class ByteSink {
  private chunks: Uint8Array[] = [];
  private total = 0;

  push(bytes: Uint8Array): void {
    this.chunks.push(bytes);
    this.total += bytes.length;
  }

  u32(value: number): void {
    if (!Number.isInteger(value) || value < 0 || value > U32_MAX) {
      throw new SlotSelectionError(
        "CANONICAL_SELECTION_ENCODING_ERROR",
        "count 가 u32 범위 초과",
      );
    }
    const buf = new Uint8Array(4);
    buf[0] = (value >>> 24) & 0xff;
    buf[1] = (value >>> 16) & 0xff;
    buf[2] = (value >>> 8) & 0xff;
    buf[3] = value & 0xff;
    this.push(buf);
  }

  text(value: string): Uint8Array {
    const raw = ENCODER.encode(value);
    if (raw.length > U32_MAX) {
      throw new SlotSelectionError(
        "CANONICAL_SELECTION_ENCODING_ERROR",
        "UTF-8 byte length 가 u32 범위 초과",
      );
    }
    this.u32(raw.length);
    this.push(raw);
    return raw;
  }

  concat(): Uint8Array {
    const out = new Uint8Array(this.total);
    let offset = 0;
    for (const chunk of this.chunks) {
      out.set(chunk, offset);
      offset += chunk.length;
    }
    return out;
  }
}

/** slot-selection-canonical/v1 정본 bytes — 저장 순서 무관, 같은 의미는 같은 bytes. */
export function canonicalizeSelectionSet(
  contractId: string,
  set: SlotSelectionSet,
): Uint8Array {
  requireScalarText(contractId, "contract_id");
  validateSelectionSet(set); // Python 은 생성지에서 검증한다 — TS 도 canonicalize 전에 강제.
  const sink = new ByteSink();
  sink.push(MAGIC);
  sink.text(SELECTION_SET_SCHEMA_VERSION);
  sink.text(contractId);
  sink.u32(set.selections.length);

  const bySlot = set.selections
    .map((selection) => ({ selection, key: ENCODER.encode(selection.slotId) }))
    .sort((a, b) => compareBytes(a.key, b.key));

  for (const { selection } of bySlot) {
    sink.text(selection.slotId);
    sink.u32(selection.selectedOptionIds.length);
    const byOption = selection.selectedOptionIds
      .map((optionId) => ({ optionId, key: ENCODER.encode(optionId) }))
      .sort((a, b) => compareBytes(a.key, b.key));
    for (const { optionId } of byOption) {
      sink.text(optionId);
    }
  }
  return sink.concat();
}

function toHex(bytes: Uint8Array): string {
  let out = "";
  for (const byte of bytes) {
    out += byte.toString(16).padStart(2, "0");
  }
  return out;
}

/** canonical bytes 의 sha256 content-address. Web Crypto 라 async 다. */
export async function digestSelectionSet(
  contractId: string,
  set: SlotSelectionSet,
): Promise<string> {
  const canonical = canonicalizeSelectionSet(contractId, set);
  const buffer = new ArrayBuffer(canonical.length);
  new Uint8Array(buffer).set(canonical);
  const hash = await globalThis.crypto.subtle.digest("SHA-256", buffer);
  return "sha256:" + toHex(new Uint8Array(hash));
}

/** 저장 순서 무관 semantic equality — 같은 canonical bytes 면 같다. */
export function semanticSelectionEqual(
  a: SlotSelectionSet,
  b: SlotSelectionSet,
): boolean {
  const schema = SELECTION_SET_SCHEMA_VERSION;
  return (
    compareBytes(
      canonicalizeSelectionSet(schema, a),
      canonicalizeSelectionSet(schema, b),
    ) === 0
  );
}
