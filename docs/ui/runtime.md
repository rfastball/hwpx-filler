# 런타임과 경계

## 의존 방향

의존은 바깥에서 안으로만 흐른다. `hwpxfiller`는 `hwpxcore`를 사용하지만 역방향은 금지다.

| 계층 | 소유 범위 | 소유하지 않는 것 |
|---|---|---|
| 형식 커널 `src/hwpxcore/` | HWPX bytes 파싱·구조 관찰·직렬화 | 제품 규칙, 파일 시스템·창·시계 등 환경 효과 |
| 제품 도메인·application | 작업·구성·선택·준비·실행 판정 | DOM과 pywebview |
| `viewmodel/` | UI에 필요한 상태·문안·게이트 투영 | 실제 창·DOM 조작 |
| `webapp/` | 컨트롤러·브리지·네이티브 자원 조정 | 도메인 판정의 재구현 |
| `frontend/` | React 렌더·포커스·모달·표시 상태 | digest·권한·최신성·실행 가능 여부의 독립 판정 |

실제 모듈 좌표는 [module_rings.toml](../module_rings.toml), 공개 경계와 vendor 배치는
[architecture_contract.toml](../../tests/architecture_contract.toml)이 소유한다.
설명 문서에서 별도 예외 목록을 만들지 않는다.

## 실행 자산

제품은 Windows pywebview와 WebView2로 동작한다. 유일한 웹 소스는 `frontend/`다.
소스 실행은 현재 소스에 대해 봉인된 `build/web/`, 배포 실행은 번들 안의 봉인된 `web/`를
검증해 사용한다. 웹 자산 경로 override나 검증 실패 시 임의 fallback을 만들지 않는다.
빌드·봉인·출하 절차는 [개발 환경](../DEVELOPMENT_ENVIRONMENT.md)이 소유한다.

## Python과 웹의 통신

`WebFrontend.initial(screen)`과 `dispatch(screen, action, payload)`는 화면 채널 경계다.
[action_registry.py](../../src/hwpxfiller/webapp/action_registry.py)가 허용 화면·액션과
필수/선택 payload 키를 검증한다. 알 수 없는 키를 `dict.get`으로 조용히 버리지 않는다.

파일 피커·생성·클립보드·설정 등 직접 호출은
[bridge.js](../../frontend/js/bridge.js)에서 `WebFrontend` 메서드로 간다.
정확한 목록은 [생성 참조](../reference/runtime.md)에 있다. TypeScript 계약은
[gen_bridge_contract.py](../../scripts/gen_bridge_contract.py)로 생성하고 직접 편집하지 않는다.

Python→웹의 제품 공개 경계는 `window.__hwpx`의 snapshot 사건이다. 테스트 전용
`window.__hwpxTest`와 섞지 않는다. 판정·수치·불투명 token은 Python이 소유하며, 웹은
주어진 값의 표시와 확인 왕복만 담당한다. token 내용을 파싱해 별도 권위를 만들지 않는다.
컨트롤러의 push sink는 주입되므로 실제 창 없이 dispatch와 snapshot을 테스트할 수 있다.

## React 상태와 수명주기

제품 화면은 단일 React 트리에 속한다. snapshot store는 도착 순서를 관리하고
`useSyncExternalStore` 구독에 안정된 참조를 제공한다. 늦게 끝난 pull이 그사이 도착한
push를 덮지 않도록 revision을 대조한다. 의미 상태를 웹에서 병합·재판정하지 않는다.

화면을 숨기는 것은 화면을 파괴하는 것과 다르다. 화면 실행자가 가시성, `hidden`,
`inert`, `aria-hidden`을 함께 적용하고, 구독·listener·worker 등은 설치한 소유자가 해제한다.
전체 `innerHTML` 재구성 후 범용 복원 헬퍼를 두는 방식은 현재 제품 렌더 계약이 아니다.
포커스·캐럿·스크롤·IME 연속성은 실제 화면의 행동 계약으로 검증한다.

## 내비게이션과 오버레이

상단 탭은 문서 만들기(`job`)와 문서 작업(`library`)다. 편집기(`editor`)와
검토·복사 작업대(`workbench`)는 몰입 화면이다. 이탈 판정은
[shell/nav.ts](../../frontend/src/shell/nav.ts), 실제 화면 적용과 listener 수명은 셸이 소유한다.
임의 화면별 예외 분기로 이탈 가드를 우회하지 않는다.

[overlay/engine.ts](../../frontend/src/overlay/engine.ts)는 DOM 없는 스택 상태기계다.
모달·시트의 확인 promise, Escape 처리, 기본 포커스와 원래 포커스 복귀를 일관되게 처리한다.
Python이 파괴 전이의 이유와 손실 집합을 결정하고 웹 확인 UI가 그 결과를 보여준다.
실패한 확인 경로를 성공이나 무응답으로 바꾸지 않는다.

## 검증

[아키텍처 검사](../../tests/repo_contract/test_architecture.py),
[브리지 검사](../../tests/repo_contract/test_bridge_contract.py),
[프런트 행동 테스트](../../tests/js), [실앱 검사](../../tests/test_web_selftest_gate.py)를 함께 쓴다.
정적 검사는 경계의 형상을, 실제 DOM·WebView2 검사는 사용자가 겪는 결과를 검증한다.
