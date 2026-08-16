/* S5-06(#702) TypeScript parity — Python `domain/canonical_execution_encoding.py` 와 byte 동일.

   `tests/fixtures/execution_canonical_v1_golden.json` 은 Python·TS 공통 오러클이다.
   여기서 TS 가, `tests/test_canonical_execution_encoding.py` 에서 Python 이 같은 파일을 재현한다.
   한쪽 encoding 이 달라지면 그쪽 스위트만 빨강이 된다.

   `.ts` 확장자 그대로 import — Node type stripping 이 제품 파일을 무변환으로 실어 Vite 빌드와
   같은 파일을 본다. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  canonicalExecutionBytes,
  canonicalExecutionDigest,
  CanonicalExecutionEncodingError,
} from "../../frontend/src/domain/canonical_execution_encoding.ts";

const GOLDEN = JSON.parse(
  readFileSync(
    new URL("../fixtures/execution_canonical_v1_golden.json", import.meta.url),
    "utf8",
  ),
);

function toHex(bytes) {
  let out = "";
  for (const byte of bytes) out += byte.toString(16).padStart(2, "0");
  return out;
}

for (const vector of GOLDEN.vectors) {
  test(`golden vector reproduced: ${vector.name}`, async () => {
    assert.equal(toHex(canonicalExecutionBytes(vector.value)), vector.canonical_hex);
    assert.equal(await canonicalExecutionDigest(vector.value), vector.digest);
  });
}

test("map key order does not change bytes", () => {
  const forward = { a: 1, b: [true, false, null], z: -5 };
  const reverse = { z: -5, b: [true, false, null], a: 1 };
  assert.equal(
    toHex(canonicalExecutionBytes(forward)),
    toHex(canonicalExecutionBytes(reverse)),
  );
});

test("float rejected — no silent identity", () => {
  assert.throws(() => canonicalExecutionBytes({ x: 1.5 }), CanonicalExecutionEncodingError);
});

test("u64 magnitude overflow rejected", () => {
  assert.throws(
    () => canonicalExecutionBytes(2n ** 64n),
    CanonicalExecutionEncodingError,
  );
});

test("lone surrogate rejected", () => {
  assert.throws(
    () => canonicalExecutionBytes("\ud800"),
    CanonicalExecutionEncodingError,
  );
});
