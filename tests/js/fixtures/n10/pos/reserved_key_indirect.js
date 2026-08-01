/* 양성 대조 ⑪ — 주입받은 창(`win`)에 예약 이름을 심는다. 수신자가 지역 식별자라 "전역
   쓰기" 로는 보이지 않지만, **이름이 `__hwpx*` 예약 대역**이면 그것은 제품 전역의 생산이다.
   `frontend/src/selftest/api.js` 가 실제로 이 형태다 — 그래서 이름 축으로 따로 센다. */
export function install(win) {
  Object.defineProperty(win, "__hwpxTest", { value: {}, writable: false });
}
