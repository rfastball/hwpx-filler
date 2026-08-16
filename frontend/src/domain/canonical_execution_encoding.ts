/* S5 실행 semantic 의 closed canonical byte framing — TypeScript 미러(S5-06 · #702).
 * Python `domain/canonical_execution_encoding.py` 와 byte 동일하다:
 * `tests/fixtures/execution_canonical_v1_golden.json` 이 두 언어 공통 오러클이다.
 *
 * JSON-value 의미 모델(null·boolean·정수·string·array·object)을 versioned binary 로 정본화한다.
 * map key 는 UTF-8 byte order 로 정렬해 저장/열거 순서가 identity 를 바꾸지 않는다. float 은
 * semantic identity 를 갖지 않으므로 거절한다.
 *
 * 이 모듈은 DOM·React·저장소를 모른다. 순수 encoding 계약만 소유한다. */

export const CANONICAL_ENCODING_VERSION = "execution-canonical/v1";

const MAGIC = new Uint8Array([0x48, 0x46, 0x50, 0x58, 0x45, 0x43, 0x31, 0x00]); // "HFPXEC1\0"
const U32_MAX = 0xffffffff;
const U64_MAX = 0xffffffffffffffffn;
const ENCODER = new TextEncoder();

const TAG_NULL = 0x00;
const TAG_FALSE = 0x01;
const TAG_TRUE = 0x02;
const TAG_INT = 0x03;
const TAG_STR = 0x04;
const TAG_ARRAY = 0x05;
const TAG_MAP = 0x06;

export class CanonicalExecutionEncodingError extends Error {
  code: string;
  constructor(message: string) {
    super(message);
    this.name = "CanonicalExecutionEncodingError";
    this.code = "CANONICAL_EXECUTION_ENCODING_ERROR";
  }
}

/** JS TextEncoder 는 lone surrogate 를 U+FFFD 로 조용히 치환한다 — Python 은 던진다.
 * parity 를 위해 encode 전에 명시로 거절한다. */
function encodeScalarText(value: string): Uint8Array {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        throw new CanonicalExecutionEncodingError("텍스트에 유효하지 않은 Unicode scalar");
      }
      i += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      throw new CanonicalExecutionEncodingError("텍스트에 유효하지 않은 Unicode scalar");
    }
  }
  return ENCODER.encode(value);
}

class ByteSink {
  private chunks: Uint8Array[] = [];
  private total = 0;

  byte(value: number): void {
    this.push(new Uint8Array([value]));
  }

  push(bytes: Uint8Array): void {
    this.chunks.push(bytes);
    this.total += bytes.length;
  }

  u32(value: number): void {
    if (!Number.isInteger(value) || value < 0 || value > U32_MAX) {
      throw new CanonicalExecutionEncodingError(`count/length 가 u32 범위 초과: ${value}`);
    }
    const buf = new Uint8Array(4);
    buf[0] = (value >>> 24) & 0xff;
    buf[1] = (value >>> 16) & 0xff;
    buf[2] = (value >>> 8) & 0xff;
    buf[3] = value & 0xff;
    this.push(buf);
  }

  text(value: string): void {
    const raw = encodeScalarText(value);
    if (raw.length > U32_MAX) {
      throw new CanonicalExecutionEncodingError("UTF-8 byte length 가 u32 범위 초과");
    }
    this.u32(raw.length);
    this.push(raw);
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

function compareBytes(a: Uint8Array, b: Uint8Array): number {
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i += 1) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return a.length - b.length;
}

function encodeInt(sink: ByteSink, value: bigint): void {
  const negative = value < 0n;
  const magnitude = negative ? -value : value;
  if (magnitude > U64_MAX) {
    throw new CanonicalExecutionEncodingError(`정수 magnitude 가 u64 범위 초과: ${value}`);
  }
  sink.byte(TAG_INT);
  sink.byte(negative ? 0x01 : 0x00);
  const buf = new Uint8Array(8);
  new DataView(buf.buffer).setBigUint64(0, magnitude, false);
  sink.push(buf);
}

function encodeValue(sink: ByteSink, value: unknown): void {
  if (value === null || value === undefined) {
    sink.byte(TAG_NULL);
  } else if (value === true) {
    sink.byte(TAG_TRUE);
  } else if (value === false) {
    sink.byte(TAG_FALSE);
  } else if (typeof value === "bigint") {
    encodeInt(sink, value);
  } else if (typeof value === "number") {
    if (!Number.isInteger(value)) {
      throw new CanonicalExecutionEncodingError("float 은 semantic identity 를 갖지 않는다");
    }
    encodeInt(sink, BigInt(value));
  } else if (typeof value === "string") {
    sink.byte(TAG_STR);
    sink.text(value);
  } else if (Array.isArray(value)) {
    sink.byte(TAG_ARRAY);
    sink.u32(value.length);
    for (const item of value) encodeValue(sink, item);
  } else if (typeof value === "object") {
    sink.byte(TAG_MAP);
    const entries = Object.entries(value as Record<string, unknown>).map(([key, val]) => ({
      keyBytes: ENCODER.encode(key),
      key,
      val,
    }));
    entries.sort((a, b) => compareBytes(a.keyBytes, b.keyBytes));
    sink.u32(entries.length);
    for (const { key, val } of entries) {
      sink.text(key);
      encodeValue(sink, val);
    }
  } else {
    throw new CanonicalExecutionEncodingError(`미지원 canonical 값 타입: ${typeof value}`);
  }
}

/** semantic payload 의 execution-canonical/v1 정본 bytes(저장 순서 무관). */
export function canonicalExecutionBytes(payload: unknown): Uint8Array {
  const sink = new ByteSink();
  sink.push(MAGIC);
  sink.text(CANONICAL_ENCODING_VERSION);
  encodeValue(sink, payload);
  return sink.concat();
}

function toHex(bytes: Uint8Array): string {
  let out = "";
  for (const byte of bytes) out += byte.toString(16).padStart(2, "0");
  return out;
}

/** canonical bytes 의 sha256 content-address. Web Crypto 라 async 다. */
export async function canonicalExecutionDigest(payload: unknown): Promise<string> {
  const canonical = canonicalExecutionBytes(payload);
  const buffer = new ArrayBuffer(canonical.length);
  new Uint8Array(buffer).set(canonical);
  const hash = await globalThis.crypto.subtle.digest("SHA-256", buffer);
  return "sha256:" + toHex(new Uint8Array(hash));
}
