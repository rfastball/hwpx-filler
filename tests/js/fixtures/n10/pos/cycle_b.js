/* 양성 대조 ⑧-나 — a ↔ b 순환의 반대쪽. */
import { a } from "./cycle_a.js";

export function b() {
  return a();
}
