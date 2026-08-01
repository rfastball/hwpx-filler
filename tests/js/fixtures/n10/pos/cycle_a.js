/* 양성 대조 ⑧-가 — a ↔ b 순환의 한쪽. */
import { b } from "./cycle_b.js";

export function a() {
  return b();
}
