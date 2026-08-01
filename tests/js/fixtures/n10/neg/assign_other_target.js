/* 음성 대조 ④ — `Object.assign` 의 수신자가 창이 아니다. 제품 코드에 스무 곳 넘게 있는
   평범한 얕은 복사라, 여기서 발화하면 게이트를 아무도 못 켠다. */
const registry = {};

Object.assign(registry, { Leak: 1 });

export function seed(target, extras) {
  return Object.assign({}, target, extras);
}

export function mutate(target) {
  Object.assign(target, { Leak: 2 });
  return target;
}
