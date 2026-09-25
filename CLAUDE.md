# Claude 작업 진입점

공통 절차는 [CONTRIBUTING.md](CONTRIBUTING.md), 읽기·작성 목적지는 [문서 지도](docs/README.md)가
소유한다. 새 문서는 먼저 `scripts/docs_contract.py --route`로 라우팅한다.

## 도구별 위임

규모 있는 구현은 정확한 델타·범위·산출물·정지 조건·제외를 명시하고 executor 서브에이전트
(`model: opus`)에 위임한 뒤 결과를 검증한다. 팬아웃 판단·감사·스윕은 Sonnet, 경계가 정해진
기계적 읽기·변환은 Haiku를 사용한다. 반환은 핵심 수치·경로로 받고 원문을 덤프하지 않는다.
모델별 자세는 claude-model-postures 플러그인 훅이 주입한다.

병렬 작업은 직교성이 확인된 경우만 허용한다. `viewmodel/run_state.py`는 단일 소유자다.
domain 변경은 관련 viewmodel과 한 작업에 묶고 `hwpxcore` 변경은 단일 작업으로 직렬 처리한다.
불확실하면 직렬로 수행한다. 코드 교차 계약·문안 예산·완료 보고는 공통 기여 절차를 따른다.
