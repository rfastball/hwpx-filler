/* 양성 대조 ④ — `Object.assign` 으로 한 번에 여러 전역. 대입 연산자가 한 글자도 없다. */
export const marker = "pos/object_assign";

Object.assign(window, { Leak: 1, LeakTwo: 2 });
