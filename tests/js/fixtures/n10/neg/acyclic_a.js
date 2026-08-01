/* 음성 대조 ⑧-가 — 다이아몬드. 같은 노드(`acyclic_c.js`)를 두 경로가 방문하지만 순환은
   아니다. 방문 표시를 "봤다/도는 중" 두 상태로 나누지 않는 순회는 여기서 거짓 순환을 낸다. */
import { b } from "./acyclic_b.js";
import { c } from "./acyclic_c.js";

export function boot() {
  return b() + c();
}
