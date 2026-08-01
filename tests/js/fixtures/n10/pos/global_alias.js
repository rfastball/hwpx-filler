/* 양성 대조 ⑩ — 전역을 지역 이름에 담아 두고 그 이름으로 쓴다. 이 한 줄을 허용하면 위
   아홉 형태를 전부 우회할 수 있으므로, **별칭을 만드는 것 자체**를 금지 구문으로 센다. */
export const marker = "pos/global_alias";

const w = window;
w.Leak = 1;
