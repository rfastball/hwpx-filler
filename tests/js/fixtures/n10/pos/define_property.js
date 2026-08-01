/* 양성 대조 ⑤ — `Object.defineProperty` 로 세우는 전역. 열거 불가로 심으면 런타임 순회로도
   안 보이므로, 정적으로 못 세면 아무도 못 센다. */
export const marker = "pos/define_property";

Object.defineProperty(window, "Leak", { value: 1 });
