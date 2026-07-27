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

레일과 최상위 DOM 화면의 현재 목록은 `library`, `job`, `draft`, `tpl` 네 개다.
`web/js/app.js`의 `window.Nav.go`가 표시 상태를 전환한다. `editor`는 라우팅 화면이 아니라
`job` 화면 안의 편집 호스트이며 `EditorEntry`가 편집 모드로 착지시킨다.

| 라우트/표면 | DOM·JavaScript 소유자 | Python 컨트롤러 | 링1 ViewModel·상태 소유자 |
|---|---|---|---|
| `library` 문서 작업(전역 라이브러리) | `#scr-library`, `screens/library.js` | `LibraryController` | `HomeViewModel`(모듈명은 유지 — 지도 §10.8 판정 A) |
| `job` 작업 목록·실행 | `#scr-job`, `screens/job.js` | `JobController` | `RunViewModel`, `SelectionModel`, 필터 상태, 후보 판정(`work_candidates`) |
| `job` 내부 작업 편집 | `#jobEditHost`, `screens/editor.js`, `editor_entry.js` | `EditorController` | `MappingModel`, 저장 판정, 공유 `TemplateManagerViewModel` |
| `draft` 기안 작업·세션 | `#scr-draft`, `screens/draft.js`, `draftsession.js` | `DraftController` | `TxtDraftViewModel`, `MappingModel`, `SelectionModel`, `TxtQueueModel` |
| `tpl` 템플릿 관리 | `#scr-tpl`, `screens/template.js` | `TemplateController` | `TemplateManagerViewModel`, 템플릿 그룹 상태 |
| 데이터 선택 다이얼로그(화면 아님) | `#dataPickerModal`, `data_picker.js` | `PoolController` + 호스트 화면 | `DatasetPoolViewModel` |

화면을 추가·삭제·이름 변경할 때는 DOM 루트, 화면 JavaScript의 `SCREEN`, Python 컨트롤러
`name`, `WebFrontend.controllers`, action registry를 한 계약 변경으로 갱신한다. `job` 내부 편집
표면처럼 라우트와 컨트롤러가 1:1이 아닌 경우도 위 표에 명시한다.

### 데이터 선택 다이얼로그 (재작성 F1 — `pool` 화면 사망의 승계처)

데이터 선택은 「작업」·「기안」 두 세션 표면이 공유하는 **한 오버레이**(`#dataPickerModal`,
`web/js/data_picker.js`)로 수렴한다. 구 2버튼(「등록 데이터…」·「파일 선택…」)과 `pool`
화면(`#scr-pool`·`screens/pool.js`)은 사망했고, 그 기능은 세 구획으로 흡수됐다:

| 구획 | 내용 | 백엔드 |
|---|---|---|
| 현재 데이터 | 마운트 재진술 + 「이 데이터 고정」(파일 출처에서만 — 등록 데이터는 이미 고정된 참조) | 호스트 스냅샷 `data_target` |
| 고정한 데이터 | 등록 데이터 **전 상태**(활성·보관·끊김·나라) + 사용·보관·활성화·삭제·다시 연결 + 손상 격리 | `pool` 컨트롤러 스냅샷·액션 **그대로** |
| 다른 데이터 | 파일 찾아보기(1회용) → 다중 시트면 시트 확정 게이트 | 호스트 `pick_data_file`/`load_data_sheet` |

- **화면은 죽고 컨트롤러는 산다**: `PoolController` 는 그대로 살아 이 다이얼로그가 `pool`
  관측 푸시의 구독자다(`Bridge.onPush("pool", …)`). 판정·문구는 Python 단일 출처.
- 보관·끊김 항목은 숨기지 않고 **정직하게 비활성** + 사유 병기 — 숨기면 `활성화`·`다시 연결`
  동사에 도달할 길이 사라진다.
- 마운트 성사 시에만 닫는다. 실패(나라 동결·죽은 참조·모호 시트·행 0건·읽기 실패)는 면 안
  상태줄에 재진술하고 면을 유지한다. 마운트 진행 중에는 닫기·Escape 를 차단하고 표기한다.
- 전환 손실 가드는 **대상 확정 직후·읽기 직전**에 호스트 콜백으로 묻는다(`confirmSwap`).
- 고정·등록·다시 연결은 `#poolRegModal` 을 이 면 **위에** 스택으로 띄운다(제목이 진입 사유).

### `job` 세션 표면의 형상 (v6 `screen-data` 2열 — 재작성 R1)

세션 패널(`#jobZones`)은 구 4존(헤더·데이터·본문·완료)이 아니라 **v6 `screen-data` 2열**이다
(`.data-grid` — 정본 `docs/DATA_FIRST_INTEGRATION_MAP.md` §10.5 R1).

| 열 | 구획 | 소유 |
|---|---|---|
| 좌 `.dg-main` | 현재 데이터(겨눔·검색·필터·표·필터 밖 스트립) → 본문 확인(거울) → 생성 결과 | 데이터-우선 흐름의 입력과 되읽기 |
| 우 `.dg-side` | 이 데이터에 사용할 문서(후보·추천·탐색 출구) → 선택한 작업(정체·템플릿·재연결) → 생성 준비(저장 폴더·재진술) | 문서 선택과 실행 준비 |

- 두 열은 존 구분선을 공유하는 **한 카드 안의 구획**이고, 컨테이너 900px 이하에서 1열로
  퇴화한다(`@container session-panel`). 구 `.job-duo`(표\|거울 가로 병치, #272)는 이 형상으로
  대체됐다 — 표↔거울 같은 시야 요구는 좌 열 안의 세로 인접 + 펼침 면(⤢)이 승계한다.
- **znum 4존 서수는 이 화면에서 은퇴**했다(v6 는 순서 있는 4단계가 아니라 마주 보는 두 열).
  「다음에 어디로」의 정보는 게이트 문안 앞머리의 **구획 이름 지목**(`gateStep`)이 승계하며,
  지목 문자열은 실재하는 `zone-cap` 캡션과 일치해야 한다(죽은 번호는 지목을 거짓말로 만든다).
  「기안」(`draft`)의 znum 문법은 그대로 산다 — 거기는 여전히 순서 있는 세션이다.
- 좌 master 작업 목록은 **존치**한다 — 사망은 F2 PR-B 다(지도 §10.8). 그 관리 동사 중 열린
  세션의 정체와 결속된 것(`rename_job`·`set_group`·`rename_group`·`disband_group`)은 이 화면
  컨트롤러가 계속 **소유**하고, 라이브러리 표면이 교차 화면 dispatch 로 부른다(§10.8 판정 F) —
  여기서 재구현하면 같은 상태를 두 판정이 내게 된다. `toggle_group`(그룹 접힘)의 소유는
  라이브러리로 넘어갔고 두 화면이 같은 영속 키(`job_collapsed_groups`)를 공유한다.
- 생성 버튼은 계속 하단 sticky 액션바(`#jobActionBar`)다(#179 슬라이스 5b — 스크롤 무관 상시
  도달). v6 시안의 side-card `run-actions` 배치와 다른 유일한 지점이며, 결과 3태 구획과 함께
  재검토한다(지도 F4).

### `job` 화면의 데이터-우선 세션 계약 (data-first 봉합)

`JobController` 는 마운트된 데이터(`datasource`·`records`)·선택(`SelectionModel`)·필터를
**세션(컨트롤러) 소유**로 보유한다 — 정본: `docs/DATA_FIRST_INTEGRATION_MAP.md`.

- 데이터 마운트(`pick_data_file`→`load_data_path`, `load_data_sheet`, `load_pool`)는 **작업
  미선택에도 허용**되고, 마운트 직후 선택은 **0건**이다.
- `select_job` 은 vm 만 재생성하고 세션 데이터를 주입한다(`RunViewModel.set_acquired`) —
  데이터·선택·필터는 **전환·해제에서 생존**하고, 잃는 것은 실행 증거(ack·완주 담보)뿐이다.
  구 T1 스위치 가드(`needs_confirm`/`switch_job`)는 파괴가 사라져 함께 죽었다.
- 스냅샷은 데이터 준비 시 `candidates`(현재 데이터 호환 작업 후보 — 링1
  `gui/work_candidates.py` §18.4 단일 판정)를 싣고, 작업 미선택 게이트는 링1
  `prework_gate` 산출을 그대로 렌더한다(링2 문안 재조립 금지).
- `candidates` 는 4구획이다(슬라이스 2): `top`(상위 `MAIN_TOP_N` available, 링1
  `rank_available` 순위 — 즐겨찾기→최근 사용→미사용)·`more`(순위 밖 available 수,
  0이 아니면 표면이 정직하게 고지)·`needs`(확인 필요, 이름순)·`suggested`(추천 이름).
  **추천은 표지일 뿐 전이가 아니다** — `job_name` 은 사용자 클릭(`select_job`)으로만 바뀐다
  (§18.3 개정, v6 상태전이 리뷰 F-02). 순위·추천 계산은 전부 링1이 하고 JS 는 그리기만 한다.
- 스냅샷은 `browse`(문서 탐색 §18.6·§19.5 — 탭·검색어·행·탭 건수·검색으로 걸러낸 수)도
  싣는다. 탭·검색어는 **세션 소유**(`JobController`)라 탭을 옮겨도 검색어가 살고 시트를
  닫았다 열어도 찾던 자리로 돌아온다. 검색 대상은 작업 표시 이름만이고 일치 규칙은 앱 전역
  자모 부분일치(`core.jamo`)다. 탭 건수는 **검색 전** 값 — 탭 라벨은 데이터에 대한 사실이다.
  액션 `browse_tab`(`tab`)·`browse_query`(`text`).
- `toggle_favorite`(`name`·`value`)은 정렬 메타(`Job.favorited_at`)만 바꾼다 — 활성 작업·
  매핑·검증·선택을 폐기하지 않는다(§18.5). 값은 표면이 보내는 의도 상태이고 시각은 Python 이
  찍는다.
- `prefer_work`(`name`)은 라이브러리 「문서 만들기에서 사용」의 착지다(§19.8). **3분기 판정은
  이 컨트롤러가 낸다** — 준비·호환은 링1 술어가 소유하므로 표면이 다시 계산하면 같은 상태를
  두 곳이 판정한다. 반환은 `{promoted}`(호환 → 명시 선택) / `{stored, reason:"incompatible"}`
  (활성 불변, 표면이 「확인 필요」 탭으로 라우팅) / `{stored, reason:"no_data"}`.
  보관된 `preferredWorkId` 는 마운트 시 §18.3 1행으로 판정되고 **1회 소비**된다(승격이든
  거절이든). 명시 `select_job` 도 보관분을 소비한다. 승격하지 못한 경우도 침묵하지 않고
  사유를 `data_notice` 로 재진술한다 — 방금 누른 버튼이 아무 일도 안 한 것처럼 보이면
  그게 조용한 소실이다.

### `library` 화면(전역 문서 작업 라이브러리) 계약 (§19.6·§19.7)

`LibraryController`(`web/js/screens/library.js`)가 홈 화면을 대체한다(재작성 F2 PR-A). 링1
투영은 `HomeViewModel` 이 그대로 소유한다 — 모듈명 유지는 지도 §10.8 판정 A 의 기록된 어휘 빚.

- 스냅샷 최상위가 곧 browser 상태다: `view`·`mode`·`query`·`counts`·`facets`·`sections`·
  `selected`·`detail`·`alerts`·`corrupt_rows`. 보기 4종(`all`/`recent`/`favorites`/
  `needsAction`)·방식 필터(`all`/`hwpx`/`txt`)·검색·태그 facet 은 **서로 다른 축**이라 하나를
  바꿔도 나머지가 살아 있고, 판정·정렬·건수는 전부 링1(`HomeViewModel.library_*`)이 낸다.
  구 group-by 렌즈는 **은퇴**했다 — 화면당 primary grouping 은 사용자 group 하나다(§19.2).
- 액션: `set_view`·`set_mode`·`set_query`·`toggle_facet`·`clear_facets`·`clear_filters`·
  `toggle_group`·`select_work`·`toggle_favorite`·`clone_job`·`set_tags`·`delete_job`·
  `undo_delete_job`·`relink_template`·`delete_corrupt`·`refresh`.
- `clear_filters` 는 0건 화면의 **상주 출구**다 — 네 절단자(보기·방식·검색·태그)를 한 번에
  걷는다. 절단 밖 작업에 도달할 길이 사라지지 않게 하는 §8.4 「도달성」 면의 이행분이다.
- `select_work` 는 상세 패널이 겨눌 행일 뿐 **활성 작업이 아니다** — 여기서 다른 작업을 열어도
  「문서 만들기」의 선택·데이터·승인은 불변이다(§19.6 서문, 화면 머리 문안이 재진술).
- 즐겨찾기는 행 선택 버튼의 **형제** 버튼이다(§19.6: 중첩 금지). 이 배치가 「표시 상한과 무관한
  도달성」(§8.4 2행)의 새 거처다 — 메인 Top 5 밖 작업도 여기서 승격할 수 있다.
- 그룹 접힘은 **보기**만 바꾼다 — 접어도 구획 건수와 행 페이로드는 그대로다. 구획의
  `value=""` 는 두 뜻(퇴화 평면 / 「그룹 없음」)이라 `is_untagged`·`headed` 로 가른다.
- 탭 건수는 **검색 전** 값이다(라이브러리에 대한 사실 — 문서 탐색 탭과 같은 규칙).
- 검색 대상은 작업 이름·사용자 그룹·태그 값뿐이다(소스 키·데이터 경로 제외, §19.6).
- 확인 필요 행의 `health` 는 `{severity, text}` 쌍이다 — 문구만 주면 소비자가 경고(2)와
  차단(3)을 구분하지 못해 §19.7 건강 축이 "사유 있음/없음"으로 뭉개진다. 판정·문구는
  `library_health()`(§19.7 번역)가 소유하고 표면이 다시 만들지 않는다. 현재 데이터 호환성(`work_candidates`)과는 **섞지 않는다**(§19.7 명문).
- 목록의 1건은 **파생**이고 정본은 `library_health_causes()` 의 전 원인 열거다(§19.7 "상세에서
  모든 실제 원인"). 상세 `detail.health_causes` 가 그것을 그대로 싣는다 — 같은 상태를 두 술어가
  따로 판정하면 목록과 상세가 서로 다른 말을 한다.
- 상세 「필드 연결」 표(`detail.bindings`)는 **저장된 항목 키**를 보인다. 현재 데이터는 「문서
  만들기」 세션 소유라 라이브러리가 원본 열 표시 이름을 쓰면 화면 간 결합이 생긴다(지도 §10.8
  판정 C — 되깎기 조건 기록됨). Template/Binding **판본** 열은 F7 신설분이라 오늘 만들지
  않는다(빈 자리·「준비 중」 표기도 두지 않는다 — 판정 D).
- 2-pane 공간 배분은 목록 길이에 끌려다니지 않는다: 넓고(≥921px) 높은(≥760px) 창에서 두 pane 이
  뷰포트를 나눠 각자 스크롤하고 **페이지는 스크롤하지 않는다**. 상시 행동(`작업 편집`·`문서
  만들기에서 사용`)은 상세 스크롤과 분리해 pane 아래 고정한다(§19.6 마지막 문단).
- 액션: `set_library_view`(`view`)·`set_library_mode`(`mode`)·`set_library_query`(`text`).

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
