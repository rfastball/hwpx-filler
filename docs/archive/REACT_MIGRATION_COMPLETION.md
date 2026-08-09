# React/TypeScript 전환 완료 기록

> **문서 상태:** 역사 기록
> **완료 범위:** R-00(#394)부터 legacy 제거·음성 게이트(#419·#420)까지
> **현재 정본:** 코드, `docs/UI_CONTRACT.md`, 장기 소유 테스트
> **편집 정책:** 동결

React/TypeScript 전환은 완료됐다. 제품 화면은 단일 React 트리가 만들고, Python은
도메인·애플리케이션 사실을, React/TypeScript는 DOM·표현·UI 수명주기를, host는 창·OS 효과를
소유한다. 제품 경계는 `window.__hwpx`, selftest 경계는 `window.__hwpxTest`이며, 실행·selftest·
패키징은 같은 sealed web artifact를 소비한다. legacy 화면 렌더러나 fallback 런타임은 없다.

전환 중 사용한 소유권 인벤토리, 검증 자산 원장, 단계별 successor 지도와 R3/R4 이름의 테스트는
착지 여부를 판단하기 위한 임시 장치였다. 완료 뒤에도 유지하면 현재 구조보다 migration 역사를
검사하고, 파일·심볼 수 변화마다 테스트를 증식시키므로 제거했다. 상세 계측값·단계별 좌표·판정
이력은 Git 이력과 #394~#420에 남아 있다.

장기 계약은 다음 소유자에 남는다.

- 공개 브리지·dispatch 경계: `tests/repo_contract/test_bridge_contract.py`,
  `tests/repo_contract/test_dispatch_payload_contract.py`
- DOM·portal 순수 행동: 해당 TypeScript 모듈의 Node 단위 테스트
- 실 WebView2 렌더·React 커밋·store 마커: `tests/test_web_selftest_gate.py`의 모듈 단위 부팅
- 화면·store·overlay·shell의 순수 행동: 해당 TypeScript 모듈의 Node 단위 테스트
- Python 결정·payload·저장·동시성: 각 core/data/controller 장기 소유 테스트
- sealed artifact 동일성: 빌드·패키징 계약

새 기능은 완료 원장이나 R단계 census를 되살리지 않는다. 현재 공개 경계나 행동이 바뀌면 위
장기 소유자를 갱신하고, 새로운 일회성 이관이 필요하다면 완료 조건과 삭제 시점을 먼저 둔다.
