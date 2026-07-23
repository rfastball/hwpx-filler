# UI 계약 — 현재 웹 UI

> **문서 상태:** 현재 정본
> **권위 범위:** HWPX Filler 웹 UI의 레이어, 라우팅, 화면 소유권과 자동 계약 게이트
> **후속 정본:** 구현 세부는 `web/`, `src/hwpxfiller/webapp/`, `src/hwpxfiller/gui/*_state.py`
> **편집 정책:** 계속 갱신

이 문서는 pywebview + WebView2로 배포되는 현재 UI의 계약 진입점이다. 실제 표면은
[`web/index.html`](../web/index.html)과 그 자산이며, Python 어댑터는
`src/hwpxfiller/webapp/`에 있다. Qt 셸 시대의 목업 계약은
[역사 보존본](archive/UI_CONTRACT_QT.md)에서만 확인한다.

관련 결정: [UI/백엔드 분리](ARCH_UI_SEPARATION.md) ·
[UI 디자인 결정](UI_DESIGN_DECISIONS.md) ·
[렌더 보존 계약](WEB_RENDER_PRESERVATION.md)

## 의존 방향과 경계

의존은 바깥쪽에서 안쪽으로만 흐른다.

1. **링0 — 도메인/데이터:** `src/hwpxfiller/core/`, `src/hwpxfiller/data/`. 문서 생성,
   저장 모델, 데이터 소스를 소유하며 UI 런타임을 모른다.
2. **링1 — ViewModel/상태:** `src/hwpxfiller/gui/*_state.py`의 Qt-free 모델. 링0을 호출하고
   상태·게이트·직렬화 가능한 값을 제공한다. DOM이나 pywebview를 임포트하지 않는다.
3. **링2 — 웹 프레젠테이션:** `src/hwpxfiller/webapp/`의 컨트롤러·브리지와 `web/`의
   HTML/CSS/JavaScript. 링1을 호출해 JSON-safe snapshot으로 바꾸고 DOM에 렌더한다.

웹→Python 경로는 두 갈래다(#257 리뷰 — 전 경로를 여기서 계약한다).

- **디스패치 경로:** 순수 데이터 액션은 `WebFrontend.initial(screen)`과
  `dispatch(screen, action, payload)`를 통하고, 허용 화면·액션·payload 키는
  `webapp/action_registry.py`의 `validate_dispatch`가 검증한다.
- **직접 브리지 경로:** 네이티브 자원이 관여하는 호출은 `web/js/bridge.js`가
  `WebFrontend` 공개 메서드를 **직접** 부른다 — 파일/폴더 피커(`pick_data_file`,
  `pick_output_folder`, `pick_template_path`, `pick_pool_data_file`), 실행·가져오기
  (`generate`, `import_template_file`, `import_library_template`), 에디터 착지
  (`load_template_into_editor`, `open_job_in_editor`, `editor_has_unsaved_work`), 경로 추적
  (`open_path`, `reveal_path`, `copy_path`, `reveal_corrupt_job`), 클립보드·설정
  (`copy_clipboard`, `set_theme`, `set_font_scale`, `set_rail_collapsed`, `set_master_width`),
  시트 적재(`load_data_sheet`). 이 경로는 action registry **밖**이므로, 새 직접 메서드를
  추가하면 이 목록과 payload 검증 책임(메서드 본문)을 함께 갱신한다.

Python→웹 관측 갱신은 `window.__push(screen, snapshot)`으로 흐른다. 사용자 확인(파괴 전이의
`needs_confirm` 왕복)은 pywebview 네이티브 다이얼로그가 아니라 **JavaScript `Modal.confirm`**
(`web/js/modal.js`)이 구현한다 — 판정·수치는 Python이 내리고 문안·확인 UI는 웹이 소유한다.
창 수명 같은 나머지 네이티브 동작도 링2 브리지가 소유한다. 링0·링1이 WebView2 또는 DOM을
알게 해서는 안 된다.

## 현재 라우팅과 소유권

레일과 최상위 DOM 화면의 현재 목록은 `home`, `job`, `draft`, `tpl`, `pool` 다섯 개다.
`web/js/app.js`의 `window.Nav.go`가 표시 상태를 전환한다. `editor`는 라우팅 화면이 아니라
`job` 화면 안의 편집 호스트이며 `EditorEntry`가 편집 모드로 착지시킨다.

| 라우트/표면 | DOM·JavaScript 소유자 | Python 컨트롤러 | 링1 ViewModel·상태 소유자 |
|---|---|---|---|
| `home` 대시보드 | `#scr-home`, `screens/home.js` | `HomeController` | `HomeViewModel` |
| `job` 작업 목록·실행 | `#scr-job`, `screens/job.js` | `JobController` | `RunViewModel`, `SelectionModel`, 필터 상태 |
| `job` 내부 작업 편집 | `#jobEditHost`, `screens/editor.js`, `editor_entry.js` | `EditorController` | `MappingModel`, 저장 판정, 공유 `TemplateManagerViewModel` |
| `draft` 기안 작업·세션 | `#scr-draft`, `screens/draft.js`, `draftsession.js` | `DraftController` | `TxtDraftViewModel`, `MappingModel`, `SelectionModel`, `TxtQueueModel` |
| `tpl` 템플릿 관리 | `#scr-tpl`, `screens/template.js` | `TemplateController` | `TemplateManagerViewModel`, 템플릿 그룹 상태 |
| `pool` 데이터 관리 | `#scr-pool`, `screens/pool.js` | `PoolController` | `DatasetPoolViewModel` |

화면을 추가·삭제·이름 변경할 때는 DOM 루트, 화면 JavaScript의 `SCREEN`, Python 컨트롤러
`name`, `WebFrontend.controllers`, action registry를 한 계약 변경으로 갱신한다. `job` 내부 편집
표면처럼 라우트와 컨트롤러가 1:1이 아닌 경우도 위 표에 명시한다.

## DOM과 런타임 게이트

- `tests/test_web_dom_contract.py`는 **실제 배포 자산**을 읽는 정적 계약이다. 전역 `id` 유일성,
  화면 루트, script/style 배선, 접근성 참조, 렌더 보존 래핑과 주요 JS/브리지 seam을 검사한다.
- `tests/test_web_selftest_gate.py`와 `python -m hwpxfiller.webapp --selftest`는 **실 WebView2**에서
  부팅·렌더·상호작용·브리지 왕복을 되읽는 동적 게이트다. 정적 문자열 검사만으로 증명할 수 없는
  실제 가시성, 포커스, 클릭, 상태 갱신을 맡는다.
- `tests/test_ui_contract.py`는 동결 목업의 `data-vm` 주석과 아직 살아 있는 링1 ViewModel 표면의
  정합성만 검사한다. 배포 DOM이나 현재 라우팅의 정본이 아니다.

정적 DOM 게이트와 실 WebView2 게이트는 대체 관계가 아니다. 구조적 누락은 전자가 빠르게 잡고,
브라우저 런타임에서만 드러나는 결함은 후자가 잡는다.

## 디자인 토큰, CSS와 문구의 단일 출처

- 원시 디자인 토큰의 단일 출처는 `src/hwpxfiller/gui/design_tokens.json`이다.
  `scripts/gen_design_tokens.py`가 커밋되는 `web/css/tokens.css`와 동결 목업의 생성 구간을 만든다.
  `tests/test_design_tokens.py`가 생성물 드리프트를 막는다.
- 실제 레이아웃·컴포넌트 스타일의 단일 출처는 `web/css/app.css`다. 현재 앱을 판단할 때
  동결 목업의 인라인 CSS를 사용하지 않는다.
- 한 번만 쓰이는 정적 문구는 `web/index.html` 또는 해당 화면 JavaScript/Python 산출자가
  소유한다. 둘 이상에서 공유하는 사용자 문구만 `web/js/copy.js` 등 명시적 공용 상수로 올린다.
  문구 규율과 금지어는 [카피 스타일 가이드](COPY_STYLE_GUIDE.md)와 관련 테스트가 맡는다.

## 변경 규율

- 링1 공개 API를 바꾸면 이를 소비하는 컨트롤러와 관련 헤드리스 테스트를 함께 갱신한다.
- DOM `id`, `data-*`, script 순서 또는 화면 루트를 바꾸면 정적 DOM 계약을 먼저 갱신하고,
  실제 동작이 관여하면 WebView2 selftest 시나리오도 갱신한다.
- 목업은 [동결 시안](UI_PROTOTYPE_APPB.html)이다. 현재 기능을 설계하거나 검증하기 위해 목업을
  먼저 고치지 않는다. 보존된 `data-vm` seam이 더는 유효하지 않을 때에만 역사 계약과 함께
  명시적으로 정리한다.
