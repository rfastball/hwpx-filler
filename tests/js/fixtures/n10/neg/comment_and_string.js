/* 음성 대조 — 주석과 문자열 속의 전역 쓰기. 이 저장소의 주석은 **죽은 이름을 일부러
   보존한다**(`bootstrap.js` 머리말이 사라진 별칭 스물일곱을 이름으로 적는다). 산문을 코드로
   세면 "적으면 안 되는 이름이 있다" 는 거짓 실패가 나고, 그러면 결정 배경을 못 적게 된다.

   예: window.Leak = 1 / Object.assign(window, { Leak: 1 }) — 둘 다 여기선 산문이다. */

// globalThis.Leak = 1;

const sample = "window.Leak = 1";
const template = `Object.defineProperty(window, "Leak", { value: 1 })`;

export function describe() {
  return `${sample} / ${template}`;
}
