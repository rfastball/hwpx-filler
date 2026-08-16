/* S4-01(#671) TypeScript parity — Python `domain/slot_selection.py` 와 byte 동일.

   `tests/fixtures/slot_selection_v1_golden.json` 은 Python·TS 공통 오러클이다.
   여기서 TS 가, `tests/test_slot_selection.py` 에서 Python 이 같은 파일을 재현한다.
   한쪽 encoding 이 달라지면 그쪽 스위트만 빨강이 된다.

   `.ts` 확장자 그대로 import 하는 것 자체가 계약이다 — Node type stripping 이 제품
   파일을 무변환으로 실어 Vite 빌드와 같은 파일을 본다. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  canonicalizeSelectionSet,
  digestSelectionSet,
  semanticSelectionEqual,
  validateSelectionSet,
  SlotSelectionError,
} from "../../frontend/src/domain/slot_selection.ts";

const GOLDEN = JSON.parse(
  readFileSync(
    new URL("../fixtures/slot_selection_v1_golden.json", import.meta.url),
    "utf8",
  ),
);

function toSet(selections) {
  return {
    selections: selections.map(([slotId, optionIds]) => ({
      slotId,
      selectedOptionIds: optionIds,
    })),
  };
}

function toHex(bytes) {
  let out = "";
  for (const byte of bytes) out += byte.toString(16).padStart(2, "0");
  return out;
}

for (const vector of GOLDEN.vectors) {
  test(`golden vector reproduced: ${vector.name}`, async () => {
    const set = toSet(vector.selections);
    assert.equal(
      toHex(canonicalizeSelectionSet(GOLDEN.contract_id, set)),
      vector.canonical_hex,
    );
    assert.equal(
      await digestSelectionSet(GOLDEN.contract_id, set),
      vector.digest,
    );
  });
}

test("storage order does not change bytes", () => {
  const cid = GOLDEN.contract_id;
  const forward = toSet([
    ["s1", ["o1a", "o1b"]],
    ["s2", ["o2"]],
  ]);
  const reversed = toSet([
    ["s2", ["o2"]],
    ["s1", ["o1b", "o1a"]],
  ]);
  assert.ok(semanticSelectionEqual(forward, reversed));
});

test("lone surrogate rejected", () => {
  assert.throws(
    () => validateSelectionSet(toSet([["\ud800", ["o"]]])),
    (err) => err instanceof SlotSelectionError && err.code === "INVALID_SELECTION_SET",
  );
});

test("duplicate slot entry rejected", () => {
  assert.throws(
    () =>
      validateSelectionSet(
        toSet([
          ["s", ["a"]],
          ["s", ["b"]],
        ]),
      ),
    (err) => err instanceof SlotSelectionError,
  );
});
