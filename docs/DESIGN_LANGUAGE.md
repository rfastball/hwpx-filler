# 시각 디자인 언어

문서나르미는 한국어 데스크톱 생산성 앱이다. 데이터 표와 필드 연결을 읽고 확인하는 일을
우선하며, 웹 콘텐츠 사이트의 내비게이션이나 장식적 대시보드 문법을 그대로 가져오지 않는다.

## 시각 원칙

무채색 표면과 얇은 경계선으로 구획을 나누고, 액센트는 동작·활성·포커스에 절제해 쓴다.
값의 미확인·누락·선택 상태는 별도의 의미색으로 구분한다. 색만으로 상태를 전달하지 않고
라벨·형태·접근 가능한 이름을 함께 제공한다.

일관된 밀도와 시작선을 유지한다. 폼은 라벨·필드 열을 정렬하고 동급 구획을 같은 방식으로
묶는다. 제목·조작부가 이미 설명하는 부제와 정상 완료 낭독은 추가하지 않는다.
상시 힌트보다 빈 상태의 다음 행동과 실패의 복구 수단을 우선한다.

## 단일 출처

| 대상 | 정본 | 검사/소비 |
|---|---|---|
| 색·상태·여백·모서리·타이포·모션·층 | [design_tokens.json](../src/hwpxfiller/viewmodel/design_tokens.json) | [생성기](../scripts/gen_design_tokens.py) → [tokens.css](../frontend/css/tokens.css) |
| 컴포넌트와 배치 | [제품 CSS](../frontend/css)와 React 컴포넌트 | [UI 갤러리](UI_GALLERY.html), 실제 화면 검사 |
| vendor 배치와 수명 | [architecture_contract.toml](../tests/architecture_contract.toml) | [금지 경계 검사](../tests/repo_contract/test_p3_forbidden_edges.py) |
| 한국어 명칭·문형 | [용어](UI_VOCABULARY.md) · [문안](COPY_STYLE_GUIDE.md) | 문안 census·행동 테스트 |

수치·색상값을 이 문서에 다시 쓰지 않는다. 토큰을 수정하고 생성물을 갱신한다.
과거 비교 목업을 현재 제품 CSS의 소비자로 유지하지 않는다.

## 상호작용과 접근성

버튼의 눌림 효과가 표 행·열의 정렬을 깨뜨리면 안 된다. 정적 CSS 존재 검사만으로 눌림
기하를 보증하지 않는다. 실제 브라우저에서 `prefers-reduced-motion`의 두 경우를 검증한다.

키보드 포커스·캐럿·스크롤 연속성, 모달의 포커스 포획과 복귀, 비활성 상태의 이유를 지킨다.
라이트·다크 모두 토큰 대비 검사와 실제 렌더 검사를 통과해야 한다. 현재 대비 하한과
대상 쌍은 [test_contrast_wcag.py](../tests/repo_contract/test_contrast_wcag.py)가 소유한다.
테스트 통과를 접근성 인증이나 모든 사용자 환경의 보증으로 서술하지 않는다.

[실렌더 검사](../tests/test_web_press_geometry.py)와
[실앱 검사](../tests/test_web_selftest_gate.py)가 실제 상호작용을 검증한다.
