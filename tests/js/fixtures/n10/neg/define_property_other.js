/* 음성 대조 ⑤ — `Object.defineProperty` 의 수신자가 창이 아니다. 프로브가 합성 이벤트에
   읽기 전용 필드를 붙일 때 쓰는 실제 형태이고(`probes/*.js` 다섯 곳), 이름이 계산값인
   변형까지 있다. 예약 대역(`__hwpx*`) 밖의 이름이므로 이름 축에서도 조용해야 한다. */
const ev = {};

Object.defineProperty(ev, "propertyName", { value: "opacity" });

export function tag(obj, name) {
  Object.defineProperty(obj, name, { value: true });
  return obj;
}
