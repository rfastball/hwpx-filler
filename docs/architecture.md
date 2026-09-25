# 아키텍처

<a id="architecture-boundaries"></a>
## 계층과 실행 자산

의존은 바깥에서 안으로 흐른다. `hwpxfiller`가 `hwpxcore`를 사용하며 역방향은 금지다.

| 계층 | 소유 | 금지 |
|---|---|---|
| `hwpxcore/` 형식 커널 | HWPX bytes 파싱·관찰·직렬화 | 제품 규칙, 파일 시스템·창·시계 등 환경 효과 |
| domain·application | 작업·구성·선택·준비·실행 판정 | DOM·pywebview |
| `viewmodel/` | 상태·문안·게이트 투영 | 실제 창·DOM 조작 |
| `webapp/` | 컨트롤러·브리지·네이티브 자원 조정 | 도메인 판정 재구현 |
| `frontend/` | React 렌더·포커스·모달·표시 상태 | 의미·권한·최신성·실행 가능 여부의 독립 판정 |

모듈 좌표는 [module-rings.toml](../tests/contracts/module-rings.toml), 공개 경계·vendor 배치는
[architecture_contract.toml](../tests/architecture_contract.toml)이 소유한다. 예외 목록을 복제하지 않는다.
제품은 Windows pywebview/WebView2에서 실행하며 유일한 웹 소스는 `frontend/`다.
소스 실행은 현재 소스에 대해 봉인된 `build/web/`, 배포 실행은 번들의 `web/`를 검증한다.
자산 경로 override나 검증 실패 fallback은 없다. [빌드 절차](../CONTRIBUTING.md#development)를 따른다.

<a id="architecture-runtime"></a>
## 통신과 화면 수명

`WebFrontend.initial(screen)`과 `dispatch(screen, action, payload)`의 화면·액션·키는
[action_registry.py](../src/hwpxfiller/webapp/action_registry.py)가 검증한다. 알 수 없는 키를
조용히 버리지 않는다. 직접 네이티브 호출은 registry 밖이므로 메서드 본문이 입력을 검증한다.
정확한 목록은 [런타임 참조](reference/runtime.md), 웹 호출은 [bridge.js](../frontend/js/bridge.js),
TypeScript 계약은 [gen_bridge_contract.py](../scripts/gen_bridge_contract.py)가 소유한다.

Python→웹 제품 경계는 `window.__hwpx`의 snapshot 사건이다. 테스트용 `window.__hwpxTest`와
섞지 않는다. 컨트롤러 push sink는 주입되므로 실제 창 없이 dispatch·snapshot을 검사한다.
`pool`·`tpl`처럼 일부 표면이 구독하는 채널을 최상위 화면으로 설명하지 않는다.

제품 화면은 단일 React 트리다. snapshot store는 도착 순서를 관리하고 `useSyncExternalStore`에
안정된 참조를 제공한다. 늦은 pull이 새 push를 덮지 않도록 revision을 비교한다.
웹이 의미 상태를 병합·재판정하지 않는다. 숨김과 파괴는 다르며 실행자가 `hidden`·`inert`·
`aria-hidden`을 함께 적용한다. 구독·listener·worker·vendor 객체는 설치한 소유자가 해제한다.
제품의 렌더 계약은 전체 `innerHTML` 재구성 후 범용 복원이 아니다. 연속성은 행동으로 검증한다.

상단 탭은 `job`(문서 만들기)·`library`(문서 작업), `editor`·`workbench`는 몰입 화면이다.
이탈 판정은 [shell/nav.ts](../frontend/src/shell/nav.ts), 화면 적용·listener 수명은 셸이 소유한다.
[overlay/engine.ts](../frontend/src/overlay/engine.ts)는 DOM 없는 스택 상태기계로 확인 promise,
Escape, 초기 포커스와 복귀를 조정한다. Python이 손실 집합을 판정하고 웹이 확인을 표시한다.
실패한 확인을 성공·무응답으로 바꾸거나 화면별 지름길로 이탈 가드를 우회하지 않는다.

<a id="architecture-authority"></a>
## 의미 권위와 제어면

제품은 문서 생성에 필요한 동사만 노출한다. backend 개체마다 관리 화면·선택기·등록·승인
수명주기를 만들지 않는다. 지원 매체별 하나의 불변 출하 Profile(HWPX·TXT)을 사용한다.
제품 전체에 Profile이 하나라는 뜻은 아니다. 사용자 선택·생성·게시·admission·history·fence
관리는 없다. Profile은 형식 처리의 qualification identity이지 범용 운영 제어면이 아니다.

선택 해석·digest·적용 판본·최신성·준비·실행 가능 여부·blocker·복구 동사는 application이
판정한다. 웹은 불투명 token과 projection을 전달·표시하며 token을 파싱해 별도 권위를 만들지
않는다. 구성·프리셋 mutation은 새 token과 view를 반환하며 실패를 성공 변경처럼 표시하지 않는다.
엔진 내부 능력을 UI 제공 기능으로 간주하지 않는다. [지원 경계](product.md#product-scope)를 따른다.

HMAC은 발급 컨텍스트의 무결성과 용도·작업 결속을 확인한다. 사용자 권한 체계나 현재 revision·
Work·실행 가능성의 증명이 아니다. 서명과 현재 상태 대조, 잠금, 재전송·소비 검사는 각각 필요하다.
유효 서명만으로 다른 작업이나 오래된 선택에 명령을 적용하지 않는다.

외부 효과의 안전에 필요한 영속만 둔다. 새 first-seen·등록·승인 원장은 실제 소비 경계와
음성 테스트로 재전송·중복·복구 필요성을 증명해야 한다. 이름 유일성·CAS·token version으로
풀리는 문제에 durable 원장을 중복 도입하지 않는다. 미지원·손상·최신성 불명을 성공 fallback으로
낮추지 않는다. 보수적인 선택 자동 유지 조건은 [작업 흐름](workflow.md#workflow-template)이 소유한다.

[아키텍처](../tests/repo_contract/test_architecture.py), [금지 경계](../tests/repo_contract/test_p3_forbidden_edges.py),
[브리지](../tests/repo_contract/test_bridge_contract.py), [제어면 축소](../tests/repo_contract/test_control_surface_reduction.py),
[구성 제품](../tests/test_slot_configuration_product.py), [제어면 증거](../tests/test_control_plane_evidence.py)가
형상과 의미 경계를 검사한다. 실제 DOM·WebView2의 결과를 정적 검사만으로 보증하지 않는다.
