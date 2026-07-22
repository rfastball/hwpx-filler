# 아키텍처 결정 — UI 디자인 / 백엔드 분리 (앱 B)

> **문서 상태:** 부분 대체
> **권위 범위:** 링0·링1의 UI-runtime 비의존성과 바깥쪽→안쪽 의존 방향
> **후속 정본:** [현재 웹 UI 계약](UI_CONTRACT.md)
> **편집 정책:** 결정 변경 시만 갱신

이 결정이 도입한 3링 경계 중 **링0·링1과 의존 방향은 계속 유효**하다. 최초 결정의
Qt 위젯 링2는 제거되었고, 현재 링2는 pywebview + WebView2 셸이다. 당시 목업↔Qt 계약은
[Qt 시대 보존본](archive/UI_CONTRACT_QT.md)에 남긴다.

## 문제

UI를 바꿀 때 문서 생성·데이터 처리 정책까지 흔들리고, 색·상태 성형·I/O가 위젯에 중복되면
표현 변경이 백엔드 회귀로 번진다. 디자인 토큰과 화면 상태의 소유자를 분리하면서도 UI가
사용하는 공개 seam은 자동 검증할 필요가 있었다.

## 결정 — 3링 레이어링

의존은 바깥쪽에서 안쪽으로만 흐르며 안쪽 링은 UI runtime을 포함하지 않는다.

- **링0 — 도메인/코어** (`core/*`, `data/*`): `Job`, `RunRequest`, `MappingProfile`,
  `HwpxEngine`, 데이터 소스와 영속 규칙을 소유한다. UI 이유로 정책을 바꾸지 않는다.
- **링1 — 앱/ViewModel** (`gui/*_state.py`): `HomeViewModel`, `RunViewModel`,
  `MappingModel`, `SelectionModel`, `TxtDraftViewModel`, `TemplateManagerViewModel`,
  `DatasetPoolViewModel` 등 UI-runtime 비의존 상태·명령·게이트를 소유한다. 상태는 가능한 한
  JSON-safe 값 또는 직렬화 가능한 dataclass로 낸다.
- **링2 — 웹 프레젠테이션/브리지** (`webapp/*`, `web/*`): Python 컨트롤러가 링1을 호출해
  snapshot으로 만들고 JavaScript가 DOM에 렌더한다. pywebview는 파일 선택, 확인, 클립보드,
  창 수명과 WebView2 호스팅을 맡는다.

Qt 위젯을 링2로 두었던 최초 구현은 **대체됨**이다. 현재 화면, 라우팅, DOM/JavaScript/Python
소유권은 [현재 웹 UI 계약](UI_CONTRACT.md)이 정본이다.

## 계약 seam과 자동 게이트

- 링1 공개 API와 상태 모델은 Python 헤드리스 테스트가 검증한다.
- 웹 화면/action/payload는 `webapp/action_registry.py`와 컨트롤러 테스트가 검증한다.
- 실제 배포 DOM의 구조·배선은 `tests/test_web_dom_contract.py`가 정적으로 검증한다.
- 브라우저 런타임 동작은 `tests/test_web_selftest_gate.py`가 실 WebView2에서 검증한다.
- `tests/test_ui_contract.py`는 동결 목업의 `data-vm`과 생존 링1 API 사이의 역사적 seam만
  지킨다. 현재 배포 화면의 계약 게이트가 아니다.

## 토큰 파이프라인

색 토큰의 단일 출처는 `src/hwpxfiller/gui/design_tokens.json`이다.
`scripts/gen_design_tokens.py`가 `web/css/tokens.css`와 동결 목업의 `<gen:tokens>` 영역을
생성하며 `tests/test_design_tokens.py`가 드리프트를 차단한다. 생성물은 패키징 입력이므로
저장소에 커밋한다. 실제 웹 레이아웃과 컴포넌트 CSS는 `web/css/app.css`가 소유한다.

## 불변식

- 링0과 링1은 pywebview, WebView2, DOM 또는 다른 GUI runtime을 임포트하지 않는다.
- 링2는 링1의 정책을 복제하지 않고, 확정된 입력을 전달하고 결과를 표현한다.
- 기존 ViewModel과 상태 모델을 웹 컨트롤러나 JavaScript에서 재구현하지 않는다.
- 명시성 게이트, 누락값의 시끄러운 표식, 실행 직전 재검증 같은 정책은 링1/링0 소유로 둔다.
- 화면 구조 변경은 정적 DOM 계약과 필요한 실 WebView2 시나리오를 함께 갱신한다.

## 결과

디자인·배선 변경은 원칙적으로 링2와 토큰에 국한되고, 도메인 정책은 헤드리스로 검증할 수 있다.
새 데이터 소스와 저장 규칙은 안쪽 링에서 정의하며, 링2는 그 결과를 같은 브리지 계약으로
소비한다. UI runtime 교체가 다시 일어나더라도 링0·링1의 계약은 유지한다.
