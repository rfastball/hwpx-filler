# UI 계약 — 현재 웹 UI

> **문서 상태:** 현재 정본
> **권위 범위:** HWPX Filler 웹 UI의 레이어, 라우팅, 화면 소유권과 자동 계약 게이트
> **후속 정본:** 구현 세부는 `web/`, `src/hwpxfiller/webapp/`, `src/hwpxfiller/gui/*_state.py`
> **편집 정책:** 계속 갱신

이 문서는 pywebview + WebView2로 배포되는 현재 UI의 계약 진입점이다. 실제 표면은
[`frontend/index.html`](../frontend/index.html)과 그 자산이며, Python 어댑터는
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
- **직접 브리지 경로:** 네이티브 자원이 관여하는 호출은 `frontend/js/bridge.js`가
  `WebFrontend` 공개 메서드를 **직접** 부른다 — 파일/폴더 피커(`pick_data_file`,
  `pick_output_folder`, `pick_template_path`, `pick_pool_data_file`), 실행·가져오기
  (`generate`, `import_template_file` — 단건 가져오기+채택(F8 통일, hwpx·txt·RAW 수용),
  `import_templates_folder` — 폴더 직속 .hwpx/.txt 일괄 등록(#339): 스캔 재진술 →
  확정 실행의 2왕복이며 실행은 재스캔이 아니라 **재진술된 후보 목록에 결속**된다,
  채택 없음 = 편집 세션 무변경),
  에디터 착지(`open_job_in_editor`, `editor_has_unsaved_work`,
  `new_job_from_data` — 「이 데이터로 새 작업」(U2 §2.4·§4 판정 E): 「문서 만들기」가 지금
  마운트한 데이터를 **웹이 실어 보내지 않고** 그 컨트롤러에 되물어 신규 초안을 연다
  (마운트 정체의 단일 출처 = 그 화면. 웹이 기억한 값을 실으면 도착 순서에 따라 다른
  파일로 시작한다). 데이터 부재는 조용히 빈 마법사를 열지 않고 `ERROR:` 로 거절),
  경로 추적
  (`open_path`, `reveal_path`, `copy_path`, `reveal_corrupt_job`), 클립보드·설정
  (`copy_clipboard`, `set_theme`, `set_font_scale`, `set_master_width`),
  시트 적재(`load_data_sheet`),
  네이티브 X 닫기 확인의 처분 통보(`confirm_window_close`, `cancel_window_close` — N-07에서
  앱 셸이 `window.pywebview.api`를 직접 부르던 자리를 브리지 표면
  `Bridge.confirmWindowClose()`/`cancelWindowClose()`로 옮겼다).
  전역 `pywebview`에 **닿는**(프로퍼티 접근 — 주입 별칭 `win.`·`ctx.win.` 포함) 파일의
  실측 전수는 다섯이다: legacy 단일 백엔드 통로 `frontend/js/bridge.js`, selftest 층 셋(`src/selftest/boot.js`·
  `probes/boot_routing_overlay.js`·`probes/persistence_geometry.js`), 그리고 신규 통로의
  유일한 소유자 `src/runtime/adapter.ts`(R2-02). R4-04의 ProductScreens executor도 호스트
  존재를 직접 판독하지 않고 주입된 `Bridge.hostReady()`에 묻는다. 이 전수는
  `tests/js/pywebview_allowlist.test.js`가 AST 술어 + 게이트 안 핀으로 양방향 대조한다 —
  여덟 번째 파일이 전역에 닿으면 빨갛다.
  이 경로는 action registry **밖**이므로, 새 직접 메서드를
  추가하면 이 목록과 payload 검증 책임(메서드 본문)을 함께 갱신한다.
  `pick_data_file`/`load_data_sheet` 의 성사 반환은 **마운트 descriptor**
  (`{label, path, sheet, rows}` — U2 §2.7 3행)다: 데이터 선택 면이 닫히지 않고 「현재
  데이터」를 재진술하고 「이 데이터 고정」을 세우는 근거가 이 호출의 결과여야 한다(다음
  푸시 도착에 기대면 발신 순서 의존 — [[bridge-call-ordering-contract]] 결함류).

### Python↔TypeScript 단일 계약과 typed bridge client (R2-02 · #406)

위 두 경로의 어휘(화면×액션×payload 키·직접 메서드 24·프로토콜 v1 상수·오류 어휘·거절
봉투)는 **Python 실물이 정본**이고, TypeScript 쪽은 생성물 하나로만 소비한다 — 같은 계약을
두 언어에서 손으로 중복 유지하지 않는다.

- **생성 사슬:** `scripts/gen_bridge_contract.py` 가 정본(`action_registry`·`product_api`·
  `app.py` WebFrontend·`frontend/src/product_api.js` snake 어휘)을 추출해
  `frontend/src/contract/contract.gen.ts` 를 찍는다. 생성물은 커밋되는 소스이고 손으로
  고치지 않는다 — `tests/test_bridge_contract.py` 가 재생성 바이트 비교(드리프트)에 더해
  **생성기와 코드를 공유하지 않는 독립 오러클**(Python 직접 import · `webapp.app` 런타임
  리플렉션 · 독립 JS 판독)로 지키므로, 생성기가 정본을 오독하면 바이트 비교가 초록이어도
  오러클이 빨갛다.
- **runtime adapter:** `frontend/src/runtime/adapter.ts` — `window.pywebview` ready 대기·
  호출·오류 변환의 유일한 신규 소유자. 변환 대상은 웹→Python 실패 셋뿐이다(dispatch 거절
  봉투 → typed 오류·원문 보존 / `"ERROR:"` 문자열 규약 → typed 결과 / 메서드 부재 → loud
  typed 오류). 그 밖의 실패는 감싸지 않고 그대로 던져진다.
- **typed client:** `frontend/src/runtime/client.ts` — 화면·액션·메서드 이름이 생성 유니온으로
  좁혀진 전송 표면. 합성 루트가 정확히 한 번 구성해 반환값으로 내고, 소비자는 R2-03+ 의
  feature 다(legacy 화면 25는 계속 `bridge.js` 를 쓴다 — ADR-06). `close_guard_state` 는
  웹 소비자 0 인 host-internal 로 **기록**되며 client 표면에 오르지 않는다.
- payload **값** 타입은 v1 계약에 없다(키 집합이 계약의 전부 — `unknown` 이 정직한 번역).
  selftest 계약은 제품 계약에 섞이지 않는다(오러클이 비혼합을 단언한다).

### 상태·구독·selector 경계 — 스냅샷 store (R2-03 · #407)

상태는 세 부류로 갈리고 소유가 다르다: **① Python 권위 상태**(링1 판정·게이트·문안 — 스냅샷
으로 투영), **② frontend local draft**(아직 Python 에 커밋되지 않은 입력 — `pendingFieldEdit`
류, 정산/폐기/되돌림 3출구), **③ ephemeral UI 상태**(열림·포커스·접힘 — 표시 전용). React 가
①을 소비하는 유일한 store 경계가 `frontend/src/state/store.ts` 다.

- **전송-충실이 계약이다.** store 는 도착한 스냅샷을 도착 순서로 보관할 뿐 값을 해석·병합
  하지 않는다 — 부분 스냅샷(생성 진행 델타)의 해석은 소비 화면의 도메인이고, store 가
  병합하면 두 번째 판정자가 된다. stale 3의미(사라진 세계의 요청 / 결과 강등 / 낡은 LAST
  규율)·pending 2의미(미커밋 draft / 왕복 미결)·낙관 갱신의 기존 의미는 전부 기존 소유자에
  남는다 — store 층은 어느 것도 재판정하지 않는다.
- **배선은 브리지 채널(포트 하류)이다.** 합성 루트가 `contract.gen.ts` 화면 유니온에서 유도한
  6채널 각각에 `bridge.onPush` 탭 하나를 건다 — selftest 프로브가 push 통로를 갈아끼우면
  legacy render 와 store 가 **같은 세계**를 본다. 리스너 예외는 store 안에서 격리·경보되어
  같은 채널 뒤의 legacy render 를 죽이지 않는다.
- **구독은 해제 가능하고 화면 model의 subscribe 는 안정 참조다**(`useSyncExternalStore`
  재구독 요동 방어). 이중 해제는 throw, unmount 뒤 listener 0 은 `listenerCount` 관측면과
  node 계약이 잰다. R4 이후 각 화면 component는 controller model의
  `subscribe/getSnapshot`을 React 내장 API에 직접 건넨다. R2의 범용
  `use_screen_snapshot.ts`는 제품 소비자 0이 확인돼 R5-02에서 제거됐다.
- **당김 착지는 revision 가드를 진다**: `ingestPulled` 는 당김 시작 이후 push 가 착지한
  채널에 낡은 결과를 덮지 않고 그 판정을 반환값으로 알린다(「등록 전 push 는 버려진다·
  부팅은 initial 당김이 정본」의 store 판 번역).
- **실물 증거**: React 트리의 StoreSignal 이 수신 총 revision 을 `#reactRoot` 의
  `data-react-store-rev` 로 반영하고(기입 주체는 target 을 닫은 `boot.ts` 클로저 — 신호는
  DOM 을 모른다), `tests/test_react_store_live.py` 가 실 WebView2 에서 push 수신과 reload
  재초기화 신품성을 되읽는다. 화면 selector 의 실물과 legacy 구독(`wired`/`seated`)의 후계
  지정은 R3+ 가 이 경계 위에 세운다 — 이 단계의 소비자는 StoreSignal 뿐이다.

### 검증·동일 산출물·패키징 기반 접속 (R2-04 · #408)

R2 가 세운 React 기반(root·계약·store)의 검증이 기존 행렬 — 동일 산출물·실 WebView2·오프라인
패키징 — 에 공백 없이 연결되는 경계다. 새 러너·새 번들·새 창을 만들지 않는다.

- **selftest 클러스터 R**(`frontend/src/selftest/probes/react_runtime.js`) 이 실창 문서에서
  React 마커 셋을 판독한다: 커밋 마커 `data-react-mounted` == "1" · store 마커
  `data-react-store-rev` 십진 문자열 · 마커 단 요소 정확 1(**마커 규율 census** — 마커를 심는
  경로가 root.ts 하나뿐임의 재확인이지, 마커를 안 심는 날 `createRoot` 둘째 root 의 방어가
  아니다). 위반은 프로브 throw 라 source 게이트(프로브 무오류 단언)와 packaged 판정
  (`packaging/build.ps1` — 책임 수 43 + `react_runtime` 형상 단언, 오프라인 국면 소유)이
  각자의 기존 경로로 붉는다. 값의 크기(0/양수) 단언은 4국면 live 게이트의 소유로 남는다.
- **다중 root 의 실방어는 정적 층이다**: `react-dom/*` 결속은 `react/boot.ts` 하나로 핀,
  날 `createRoot(` 호출 census 1(멤버-접근·정의는 세지 않는다), 합성 루트 factory
  (`bootReactRoot`·`createSnapshotStore`) 착좌 census 각 1 — R2-00 불변식(다중 island 금지)의
  기계 검사(`tests/test_frontend_build_graph.py`).
- **봉인 입력에 tsconfig.json 이 편입됐다**(`web_artifact.py` `_SOURCE_CONFIG_PATHS`) — Vite 의
  `.ts` 변환이 읽는 실빌드 입력이라 dirty 거부·source 레코드 양쪽에 닿는다. 봉인 외부 URL
  술어의 불활성 열거(정확 4 + 접두 1, `.js` 한정 면제)는 R2-01 경계 개정 형상 그대로
  **존치**한다 — 어느 URL 도 소비하는 로더가 산출물 안에 없다(재판정 완료, #408 패킷 §2.3).
- **Vitest/jsdom·범용 JS/TS lint 는 이 단계에서 기각됐다** — DOM 수명주기의 실증은 실
  WebView2 층이 이미 지고(마운트 커밋·reload 재초기화·store 4국면), jsdom 은 그보다 약한
  둘째 오러클이다. 요구가 증명되는 시점(R3+ 화면 이관)의 재개방 사유는 #408 패킷 §4.5.

### 공용 상호작용·overlay 수명주기 (R3-01 · #410)

overlay 판정의 단일 정본과 완전 데이터-구동 표면 4(confirm·choose·prompt·되돌리기 토스트)의
React 소유 이전. 합법 중첩(폼 모달 위 promise 다이얼로그 — pool 재등록)이 legacy DOM 모달과
React 렌더 다이얼로그를 **한 스택**에 세우므로, 판정이 두 세계로 갈리면 같은 상태의 두
판정자가 된다 — 그래서 판정은 하나이고 집행만 갈린다.

- **판정 = 트리-불가지 엔진**(`frontend/src/overlay/engine.ts`): 중첩 스택·promise 직렬화
  (`pendingDialog`)·Escape/Tab/복귀 승계·keydown 시점(`keydownWanted`)을 소유한다. DOM
  기입·판독 0 — 요소는 불투명 참조다. modal.js 의 자기 스택·자기 직렬화 불리언은 **잔존
  금지가 계약**이다(정적 게이트가 음성으로 든다).
- **집행 = 두 집행자, 한 계약**(`OverlayExecutor`): DOM-backed 9 모달은
  `frontend/src/overlay/modal.js`의 명시 구성 adapter가
  legacy 집행자가, promise 다이얼로그·토스트는 React host(`frontend/src/overlay/host.ts`)의
  컨트롤러가 집행한다. host 는 골격을 **1회 렌더**하고 동적 전이(문안·클래스·포커스·퇴장)는
  ref 노드 위 **명령형 동기 집행**이다 — 상태 재렌더가 없어 ⑴파사드 호출과 같은 동기 턴에
  DOM 이 전이하고 ⑵노드 정체성이 open↔close 를 가로질러 유지되고 ⑶불량 root 판정이 실 DOM
  classList 판독이다(`flushSync` 는 소비자가 없어 쓰지 않는다).
- **파사드는 남는다**: `Modal.open/close/confirm/prompt/choose/restoreFocus` 소비 12 모듈
  무변경. 문안·기본 라벨·danger 판정·거절 재진술은 파사드 소유이고 host 는 **해석된 spec**
  만 받는다(골격 불량 loud 거절 문안 `missingText` 포함). 다이얼로그 DOM 집행은 늦은 결속
  슬롯(`instance.ts` `setOverlayDialogHost` — 마운트 effect 가 정확히 1회 대입, 이중 대입
  throw)으로 넘어가고, host 부재(부팅 창·마운트 실패)·골격 부재/불량(`.modal` 상실·필수 자식
  결측 — 호출 시점 실 DOM 판독)은 조용한 무동작이 아니라 안전측 거절 + loud 다.
- **문서 리스너의 시점 계약**: dismissal 계열(팝오버 바깥닫기·Escape·resize)은 popover.js 가
  **부착 명세**(`Popover.documentAttachments`)로 내고 `bootProduct` 가 **구성 시** 그 순서
  그대로 부착한다(모듈 평가 부작용 0). 모달 keydown 은 엔진 배선(`instance.ts`)이 엔진 구독
  으로 **첫 open 부착·스택 빌 때 해제**한다. 구성이 언제나 첫 open 보다 앞이므로 Escape
  층화(팝오버 먼저 닫히고 최상위 모달 나중)가 부착 순서로 선다. 둘 다 React 마운트와
  독립이다 — 마운트 실패가 legacy 모달의 Escape/Tab 까지 걷는 두 번째 실행 경로를 만들지
  않는다.
- **골격 4 의 거처**: React host 가 `#reactOverlayHost`(#overlayRoot 등가의 위치 맥락 —
  `overlay.css` 호스트 규칙) 안에 같은 id·클래스·ARIA·초기 문안으로 렌더하고, 다이얼로그·
  토스트는 그 **직속** 자식이다. 정적 `index.html` 에는 **부재가 계약**이다 — 재도입은 id
  중복·두 세계 분열이고 정적 계약이 즉시 붉는다. 합법 오버레이 포털은 둘(`#overlayRoot` ·
  `#reactOverlayHost`)이고, live 소유 술어(`overlay_children_owned`)가 그 두-포털 형상을
  document 전역에서 재측정한다.
- **검증 배치**: 엔진 순수층은 `tests/js/overlay_engine.test.js`, host 렌더 요소 계약(실 서버
  렌더)·집행 계약은 `tests/js/overlay_host.test.js`, 파사드~엔진~집행자 실물 사슬은
  `tests/js/n05_overlay.test.js`(하니스가 bootProduct 구성 몫을 재현), 실창 증거는 기존
  selftest 게이트(`modal_a11y`·`modal_confirm_serial` — React 표면 위 무변경 초록, 골격은
  React 커밋 산물이라 마운트 전제조건 대기) + 신설 `tests/test_react_overlay_live.py`(host
  마커·직속 자식·닫힘 상시 렌더·id 유일의 reload 재초기화 되읽기)가 진다.
- **R4 인계**: 9 모달·메뉴 3·콜패널·이동 다이얼로그 2 의 DOM 실이관(내용 생산자=화면과 한
  몸). **R5 정산**: 구 파사드 파일은 은퇴했고 adapter와 SurfaceSheet는 factory 주입으로
  구성된다. React host 슬롯은 mount/unmount cleanup이 exact 대칭이다.

### 앱 셸·navigation 수명주기 (R3-02 · #411)

앱 셸을 셋으로 갈랐다 — **판정·수명주기·집행**. 파사드(`Nav.go`·`Nav.refresh`·
`AppCloseGuard.prompt`)와 그 거동은 무변경이다.

- **판정 = 셸 상태기계**(`frontend/src/shell/nav.ts`): 현재 화면·기본 랜딩(`DEFAULT_SCREEN`)·
  몰입 이탈 위임(`IMMERSIVE_SURFACES` — id·cls 한 행, 새 몰입 표면은 여기 한 줄)·ready
  게이트(`routingReady`)·전환 자동 재당김 규약(`REFRESH_ON_NAV` — 단일 정의)·닫기 직렬화
  (`closePromptPending` 승계)를 소유한다. DOM 기입·판독 0·전역 접촉 0 — 집행자 포트가 주입
  이고, 결속은 정확히 1회(이중 결속 throw). `go` 는 synchronous 다: 파사드 호출 → 판정 →
  집행이 한 동기 턴이고 React 재렌더를 경유하지 않는다.
- **수명주기 = React ShellHost**(`frontend/src/shell/host.ts`): 셸 리스너(백스톱
  `unhandledrejection`·탭 클릭·도구 클릭·라벨 동기)의 부착/해제와 부팅 시퀀스(호스트 ready
  사건 훅 → `markReady` → init 5 재생: library→editor→job→workbench→DataPicker)를 트리
  자식으로 소유한다. 부착 실물(`attachShell`)은 effect 와 node 하니스가 같은 하나를 쓴다.
  부착이 비동기라 ready 사건은 **선판정 + 이벤트**(adapter `whenReady` 규약)로, 부착 전에
  지나간 `hwpx:*` 라벨 동기 사건은 **부착 직후 따라잡기**(`catchUp` — 현재 상태 재판독)로
  놓침 창을 닫는다(#74 라벨 어긋남 결함류의 구조 폐쇄). 리스너는 once 가 아니다(재발화 시
  init 재주행 — 각 controller의 `loadInitial` 멱등 계약이 중복 당김을 막는다).
- **집행 = ProductScreenExecutor + shell/app.ts adapter**: `src/screens/product_screen_executor.ts`가
  `flushSync` 안에서 visibility store와 aria-current·몰입 body 클래스를 함께 바꾸고,
  `main.stage` 및 명명된 내부 스크롤·안정 focus를 화면별로 보존한다. 화면 전환 전
  `SurfaceSheet.closeAllAndRestore()` 회수와 refresh 발신(`Bridge.call` + notice/실패 재진술)도
  같은 executor 포트가 진다. `src/shell/app.ts`에는 스플리터 제스처와 전역 리스너
  **서술**만 남는다.
  **닫기 확인의 호출·문안(`앱 종료 확인`·`confirmLabel: "종료"`·`계속
  작업`)·`danger: true`·`Bridge.confirmWindowClose/cancelWindowClose` 발신도 TS adapter
  계약이다** — 직렬화 판정은 상태기계를 지나고 modal은 명시 포트로 주입된다. adapter 가 판정을
  재조립하면 그것이 경계 위반이다(음성 게이트가 든다).
- **마운트 실패의 반경**: R3-01(확인 창)에 더해 탭·도구 응답·화면 init 이 React 마운트에
  선다 — 실패는 경보(alert)로 착지하고 Vanilla fallback 은 없다(#405 불변식).
- **검증 배치**: 상태기계 순수층은 `tests/js/shell_nav.test.js`, adapter 결합·부착 실물은
  `tests/js/n06_app_shell.test.js`(attachShell 로 종전 거동 계측), 실창 증거는 기존 selftest
  부팅·라우팅 프로브(무변경 초록) + 신설 `tests/test_react_shell_live.py`(랜딩·실클릭 동기
  전환·닫기 취소/확정 왕복·reload 재초기화)가 진다.
- **R4-04 착지**: `reactScreenStage` 하나에 `ProductScreens`가 네 화면을 mounted-hidden으로
  유지한다. visibility store 하나가 `.on`·`hidden`·`inert`·`aria-hidden`을 함께 내리고,
  editor/workbench 이탈·rerender 수명주기는 registry의 단일 owner가 fail-closed한다.
  **R5 인계**: 테마·개인화 배선의 정리와 adapter 잔존 0.

### React 패리티 검증 매트릭스 (R3-03 · #412)

이 표는 검증 종류를 “테스트가 많다”는 산문으로 뭉개지 않는다. 각 동등성 축마다 정적·브라우저·
실창 증거를 따로 들고, 아직 증거가 없는 칸은 공란 대신 **왜 비어 있는지**를 적는다. 아래 마커와
표 형식은 `tests/test_parity_matrix.py`가 파싱하므로 이름을 바꾸거나 행을 줄이는 것도 계약 변경이다.

<!-- R3-03-PARITY-MATRIX:START -->
| 축 | 정적 | 브라우저 | 실창 |
|---|---|---|---|
| css-cascade | `tests/test_web_css_manifest.py::test_app_css_manifest_matches_product_entry_import_order` | 비어 있음 — 링크 순서와 파일 전수는 실렌더 상태가 아니라 빌드 그래프 계약이다. | 비어 있음 — R4 화면 이관 전에는 CSS 순서를 다시 재는 별도 WebView2 부팅을 늘리지 않는다. |
| dom-aria | `tests/test_web_dom_contract.py::test_custom_modals_have_dialog_semantics`, `tests/js/overlay_host.test.js` | 비어 있음 — ReactDOMServer 정적 렌더는 정적 열로 분류하고 실제 WebView2 동작은 실창 열이 소유한다. | `tests/test_react_overlay_live.py::test_overlay_host_commits_skeletons_and_survives_reinit_in_a_real_window` |
| keyboard-focus | `tests/test_web_dom_contract.py::test_card_families_keep_keyboard_focus_outline`, `tests/js/n05_overlay.test.js` | 비어 있음 — StubElement 단위 검사는 정적 열로 분류하고 실제 WebView2 초점 왕복은 실창 열이 소유한다. | `tests/test_web_selftest_gate.py::TestWebSelftestGate::test_modal_escape_closes_and_restores_focus` |
| geometry | `tests/test_scroll_topology.py::test_capped_scrollport_inventory_matches_dom_and_behavior_contract` | `tests/test_web_press_geometry.py::test_row_surface_left_edge_does_not_move_while_held` | `tests/test_web_selftest_gate.py::test_window_geometry_restores_or_falls_back_in_real_webview` |
| motion | `tests/test_interaction_responsiveness.py::test_press_feedback_covers_round_trip_surfaces_and_reduced_motion` | `tests/test_web_press_geometry.py::test_press_marker_actually_fires_on_a_box_surface` | 비어 있음 — 실제 OS 모션 설정을 변이하지 않는 정책이라 강제 대조는 Playwright가 소유한다. |
| forced-colors | `tests/test_personalization_contract.py::test_forced_colors_preserves_three_owner_signals` | `tests/test_web_press_geometry.py::test_forced_colors_ownership_markers_render_only_in_active_media` | 비어 있음 — WebView2에서 사용자 Windows 고대비 설정을 시험이 바꾸지 않으며 Playwright 양면 렌더가 후계다. |
| ts-copy | `tests/test_web_css_orphan_classes.py::test_typescript_class_name_properties_are_seen` | 비어 있음 — TS 생산자 편입 여부는 소스 폐포 술어의 책임이고 렌더 결과는 해당 DOM 축에서 본다. | 비어 있음 — R4 화면 실이관 전에는 TS 복제만 위한 별도 콜드 부팅을 만들지 않는다. |
<!-- R3-03-PARITY-MATRIX:END -->

### Python→웹 제품 경계 — `window.__hwpx` 하나 (N-07 · #372 D-06)

Python이 부르는 웹 이름은 **버전 있는 파사드 하나**다. 종전에는 다섯 내부 이름
(`window.__push`·`window.AppCloseGuard.prompt`·`window.Personalization.apply`·
`window.Theme.apply`·`window.alert`)을 Python이 직접 알고 불렀고, 그 결합은 두 방향으로
조용히 썩었다: 웹이 이름을 바꾸면 Python의 문자열이 아무 말 없이 빗나가고
(`… && ….prompt(payload)`는 부재를 **falsy 무동작**으로 삼켰다), Python이 웹 내부 배치를
알아야 하므로 링 경계가 문자열 안에 숨었다.

```js
window.__hwpx.describe()
// → { protocol: "hwpx-product", version: 1,
//     capabilities: ["snapshot", "close-request", "preferences", "notice"] }
window.__hwpx.deliver({ version: 1, event, payload })   // → 동기 · JSON 직렬화 가능한 결과
```

종전 내부 호출은 **전부 전역 이름이었고 N-10에서 그 전역들이 사라졌다** — 아래 열은
이제 승계 관계의 기록이지 현재 도달 경로가 아니다. 오늘 Python이 아는 이름은 `__hwpx`뿐이다.

| 사건 | payload | 종전 내부 호출(전역, 사망) | 의미 |
|---|---|---|---|
| `snapshot` | `{screen, snapshot}` | `window.__push` | 관측 푸시. `screen`은 **불투명한 라우팅 값** |
| `close-request` | `{state}` | `window.AppCloseGuard.prompt` | 비동기 확인 모달을 **시작**만 한다 |
| `preferences` | `{personalization, theme?}` | `window.Personalization.apply` + `window.Theme.apply` | 창이 숨은 동안 주입. `theme`는 저장값이 light/dark일 때만 실린다 |
| `notice` | `{message}` | `window.alert` | 발사 후 망각. 내구성 기록은 Python이 이미 마쳤다 |

능력 목록과 핸들러 표는 **같은 레지스트리**에서 나온다 — 광고했는데 처리기가 없는 상태를
구조적으로 불가능하게 만든다. 미지 버전·미지 사건·형태 위반·처리기 부재는 전부 안정 코드로
**시끄럽게** 실패하고, v1으로 강등되는 조용한 경로는 없다. 서술자와 실패 객체는 화면 id·
모듈 이름·DOM id를 담지 않는다(담는 순간 이름만 바뀐 결합이 된다).

`preferences`가 두 호출을 하나로 접었지만 **귀속은 잃지 않는다**: 처리기가 실제로 적용한
조각 이름 배열(`applied`)을 돌려주고 파사드가 빠진 조각을 `missing`으로 지목하므로,
"개인화가 죽었다"와 "테마가 죽었다"는 여전히 다른 경보 문장으로 나온다.

`deliver`는 **절대 await 대상이 아니다**. 호출자는 `evaluate_js` 뒤에 앉은 Python 스레드라
Promise를 돌려주면 해소를 기다리지 못한 채 형태를 모르는 값을 받는다. 비동기가 본질인
사건은 "시작했다"는 사실만 돌려준다.

Python 쪽 어댑터는 `webapp/product_api.py`이고, 표현식 조립·서술자 검증·결과 판정을 그
파일 하나가 소유한다 — `app.py`는 JS 문자열을 만들지 않는다.

임시 전역 27개는 **0개가 됐다**(N-10). N-09가 Python selftest의 71개 직접 호출을 0으로
만들었고, N-10이 마지막 소비자(`scripts/capture_101_screenshots.py`의 `window.Nav.go` 판독)를
DOM 경로로 재배선한 뒤 별칭 전부와 중앙 compat 계층 파일을 지웠다. 그 자리의 후계는
`frontend/src/bootstrap.js` — 조립만 하고 전역은 `__hwpx` 하나만 건다.

제품 코드가 만드는 전역은 이제 셋뿐이다: 플랫폼이 주입하는 `window.pywebview`, 제품 공개
API `window.__hwpx`(생산자 1 = 합성 루트), 명시적 selftest 런타임에만 서는
`window.__hwpxTest`(생산자 1 = `frontend/src/selftest/api.js`). fallback 경로는 없다.

### selftest 경계 — `window.__hwpxTest` (N-09 · #372 D-07)

Python selftest가 부르는 웹 이름도 **버전 있는 뿌리 하나**다. 종전에는 `app.py`가 JS 프로브
문자열 28개(139,206자)를 품고 `evaluate_js`를 71곳에서 불러 DOM·전역을 직접 겨눴다.

```js
window.__hwpxTest                                  // Object.freeze({ version: 1, run })
window.__hwpxTest.run({version: 1, action: "start", mode, input, flags})
// → {ok: true, action: "start", runId, state: "running", mode, deadlineMs}
window.__hwpxTest.run({version: 1, action: "poll", runId})
// → {ok: true,  state: "running",   elapsedMs, deadlineMs}
// → {ok: true,  state: "succeeded", evidence, order, timings, …}   ← 종결, **한 번만**
// → {ok: false, code: "run_failed", evidence, errors, skipped, …}  ← 종결, **한 번만**
```

**정상 실행에는 이 전역이 없다.** own 프로퍼티로 존재하지 않으며, 만들었다 지우는 경로도
두지 않는다(지우기가 한 번 실패하면 그 잔존은 아무도 못 듣는다).

활성화 조건은 **하나뿐**이다: `--selftest` 프로세스에서만 Python이 `js_api`에 시험 파사드
(`selftest_claim`·`selftest_host_op`)를 붙이고, 프런트가 프로세스 메모리 토큰을 **한 번**
클레임한 뒤에야 전역이 선다. URL 쿼리·`location.hash`·빌드 플래그·정적 산출물은 활성화
조건이 **아니다** — 전부 페이지 쪽에서 만들 수 있는 조건이라 "호스트가 이 창을 시험용으로
띄웠다"를 증명하지 못한다. 토큰은 JS 클로저와 Python 메모리에만 있고 URL·로그·결과 JSON·
증거 파일 어디에도 실리지 않는다.

`run`은 **동기**다(`deliver`와 같은 이유 — `evaluate_js` 뒤의 Python 스레드는 Promise를
기다리지 못한다). 본질이 비동기인 실행은 두 박자로 접힌다: `start`가 "시작했다"와 일회용
`runId`를 즉시 주고, `poll`이 그 뒤를 묻는다. 종결 결과는 **정확히 한 번** 회수되고 재조회·
재시작·미지 `runId`·버전 불일치·시한 초과는 전부 안정 코드로 시끄럽게 거절된다.

정상 실행과 시험 실행은 **같은 한 번의 Vite 빌드**를 쓴다. 갈리는 것은 런타임 호스트 능력
하나뿐이고 산출물은 바이트까지 같다 — 별도 test entry·chunk·번들은 없다.

Python 쪽 어댑터는 `webapp/selftest_api.py`이고, 표현식 조립·호스트 연산 allowlist·결과
판정을 그 파일 하나가 소유한다. 프로브 정의는 `frontend/src/selftest/probes/` 45개이고
러너는 `frontend/src/selftest/runner.js`다.

#### 푸시는 단일 활성 통로를 지난다

제품 `snapshot` 처리기와 selftest 프로브는 **같은 포트**(`frontend/src/push_port.js`)를
부른다. 프로브가 `ctx.push`를 갈아끼우면 뒤이어 도착하는 **호스트 푸시**도 그 통로를 지나야
`mirror_pushes`·`reject_pushes`가 실물을 잰다. 처리기가 푸시를 값으로 붙들면 제품 푸시가
가로채기를 우회하고, 프로브는 "푸시 0"을 보고 그 침묵을 **배선 부재**로 읽는다 — N-07에서
실제로 난 회귀이고(#379 §5), `tests/js/n09_push_port.test.js`가 음성 대조까지 지고 있다.

사용자 확인(파괴 전이의
`needs_confirm` 왕복)은 pywebview 네이티브 다이얼로그가 아니라 **JavaScript `Modal.confirm`**
(`frontend/src/overlay/modal.js`)이 구현한다 — 판정·수치는 Python이 내리고 문안·확인 UI는 웹이 소유한다.
창 수명 같은 나머지 네이티브 동작도 링2 브리지가 소유한다. 링0·링1이 WebView2 또는 DOM을
알게 해서는 안 된다.

## 현재 라우팅과 소유권

상단 토바 탭은 `job` 「문서 만들기」와 `library` 「문서 작업」 두 개이고, 최상위 제품 화면은
`library`, `job`, `editor`, `workbench` 네 개다. 「기안」(`draft`)은 F6 PR-B 에서
사망했다(승계처 = 편집기 TXT 밴드 + 검토·복사 작업대 — 지도 §10.15.15 점검표).
좌 레일과 그 접기는 F2 PR-B 에서 사망했다.
`frontend/src/shell/app.ts`의 앱 셸이 내는 `Nav.go`가 전환을 요청한다(주입으로 전달되는
구성 산물이다 — 전역 `window.Nav`는 N-10에서 사라졌다. R3-02 부터 판정은 셸 상태기계
`frontend/src/shell/nav.ts`, 집행은 `product_screen_executor.ts`다 — 위 「앱 셸·navigation
수명주기」). 정적 HTML에는 `#reactScreenStage` 하나만 있고 `ProductScreens`가 네 wrapper를
같은 React root의 portal로 만들며, 숨은 화면도 unmount하지 않는다.
`editor`(재작성 F7)와 `workbench`(재작성 F6)는
**탭 없는 몰입 표면**이다: 상단 2탭을 덮으므로 nav 버튼이 없고, 나가는 모든 이동이 자기
이탈 가드를 지난다(`{force:true}` 는 처분을 마친 재호출). 위임은 화면마다의 특례가 아니라
상태기계의 **몰입 표면 목록**(`IMMERSIVE_SURFACES`)이 진다 — 특례를 표면마다 늘리면 가드의
완전성이 표면 수에 비례하고, 그것이 이 두 표면을 화면으로 올린 바로 그 이유다. 새 몰입
표면은 그 목록에 한 줄이면 되고 셸 은닉(`body.<cls>-open` — 집행은 adapter)과 이탈 위임이
함께 따라온다.

| 라우트/표면 | DOM·JavaScript 소유자 | Python 컨트롤러 | 링1 ViewModel·상태 소유자 |
|---|---|---|---|
| `library` 문서 작업(전역 라이브러리) | `#scr-library`, `src/screens/library.ts` | `LibraryController` | `HomeViewModel`(모듈명은 유지 — 지도 §10.8 판정 A) |
| `job` 문서 만들기(데이터·실행) | `#scr-job`, `src/screens/product_screens.ts`(+`job_read.ts`·`job_run.ts`·`job_result.ts`) | `JobController` | `RunViewModel`, `SelectionModel`, 필터 상태, 후보 판정(`work_candidates`) |
| `editor` 문서 작업 편집기(몰입) | `#scr-editor`, `src/screens/editor.ts`(+`editor_state.ts`·`editor_entry.ts`·`group_move_dialog.ts`) | `EditorController` | `MappingModel`, `EditSession`·`EditContext`, 저장 판정, 공유 `TemplateManagerViewModel` |
| `workbench` TXT 검토·복사 작업대(몰입) | `#scr-workbench`, `src/screens/workbench.ts`(+`workbench_state.ts`·`segment_view.ts`) | `WorkbenchController` | `MappingModel`, `SelectionModel`, `TxtQueueModel`, `EditSession` |
| 데이터 선택 다이얼로그(화면 아님) | `#dataPickerModal`, `src/screens/data_picker.ts` | `PoolController` + 호스트 화면 | `DatasetPoolViewModel` |
| 시트 선택 확정 게이트(화면 아님) | `#sheetModal`, `src/screens/sheet_picker.ts` | 호스트 화면(`job`·`editor`) | — (확정 전 로드 금지는 표면 계약) |

화면을 추가·삭제·이름 변경할 때는 `PRODUCT_SCREEN_IDS`, ProductScreens wrapper, visibility
store, Python 컨트롤러 `name`, `WebFrontend.controllers`, action registry를 한 계약 변경으로
갱신한다. 나가는 길에
가드가 붙는 화면(편집기)은 `Nav.go` 위임까지 한 묶음이다 — 가드를 표면마다 따로 걸면
완전성이 표면 수에 비례한다.

#### 문서 작업 편집기 = 몰입 표면 + section patch 거래 (F7 PR-A — 지도 §10.13)

- **탭은 계약 §5.1 의 section 문자열**(`template`·`binding`·`filename`, 「시험」은 F8)이고
  **집합은 매체 파생**이다(TXT 는 파일 이름 탭 없음 — §3.2). 정수 단계 어휘는 사망했다:
  patch 의 키와 탭이 같은 문자열이라야 같은 상태를 두 표면이 다르게 부르지 않는다.
- **저장 단위는 한 section 의 patch**(§13-16). 다른 탭으로 가려면 저장·버리기·머무르기 중
  하나를 명시한다 — 판정(무엇이 dirty 인가)은 Python, 3택 문안은 웹이다. 머무르기가 기본값
  (Escape 로 편집이 사라지지 않는다). 「변경 버리기」는 **진입 시점 스냅샷**으로 되돌리고
  데이터는 유지한다(데이터 선택은 patch 가 아니라 세션 문맥이다).
- **주 행동은 하나** — 「변경 저장」. 「이번 생성에 적용」은 `runOverrides`(PR-B)의 표면이라
  라디오를 미리 늘어놓지 않는다(§6: 같은 선택지를 모든 문맥에 나열하지 않는다).
- **진입은 늘 문맥과 함께**(§5.1): 사유·증거·복귀처를 보낸 표면이 싣는다. 미배선 사유는
  fail-closed 로 거절한다 — 조용한 폴백은 곧 배너가 아무 말도 못 하는 진입이다.
- **판본은 저장 상태 옆에서 읽힌다**(`저장됨 · 템플릿 r2 · 연결 r5`). 규칙이 갈릴 때만 오르고
  실행 결과 증거·미리보기 before/after 가 같은 값을 쓴다.
- 「저장」 분류는 사망했고 그 항목은 흩어졌다: 이름=머리 인라인, 작성 출처=템플릿 탭,
  저장 버튼·차단 사유=footer. **저장 시 데이터 자동등록(#18·#26)과 기본 데이터 연결
  재진술(#53-A)은 #347(U2 §5.3 판정 D)로 폐기** — 편집 세션의 데이터는 검토용 문맥일 뿐
  작업에 저장되지 않고, 풀 등록은 데이터 선택 면의 「이 데이터 고정」 하나다.

### 데이터 선택 다이얼로그 (재작성 F1 — `pool` 화면 사망의 승계처)

데이터 선택은 「문서 만들기」 세션 표면이 여는 **한 오버레이**(`#dataPickerModal`,
`frontend/js/data_picker.js`)로 수렴한다. 구 2버튼(「등록 데이터…」·「파일 선택…」)과 `pool`
화면(`#scr-pool`·`screens/pool.js`)은 사망했고, 그 기능은 세 구획으로 흡수됐다:

| 구획 | 내용 | 백엔드 |
|---|---|---|
| 현재 데이터 | 마운트 재진술 + 「이 데이터 고정」(파일 출처에서만 — 등록 데이터는 이미 고정된 참조). 이 회차에 고정했으면 버튼 자리에 「고정됨: 이름」(U2 §2.7 6행) | 호스트 스냅샷 `data_target` / 찾아보기 뒤는 브리지 descriptor |
| 고정한 데이터 | 등록 데이터 **전 상태**(활성·보관·끊김·나라) + 사용·보관·활성화·삭제·다시 연결 + 손상 격리 | `pool` 컨트롤러 스냅샷·액션 **그대로** |
| 다른 데이터 | 파일 찾아보기(1회용) → 다중 시트면 시트 확정 게이트 | 호스트 `pick_data_file`/`load_data_sheet` |

- **화면은 죽고 컨트롤러는 산다**: `PoolController` 는 그대로 살아 이 다이얼로그가 `pool`
  관측 푸시의 구독자다(`Bridge.onPush("pool", …)`). 판정·문구는 Python 단일 출처.
- 보관·끊김 항목은 숨기지 않고 **정직하게 비활성** + 사유 병기 — 숨기면 `활성화`·`다시 연결`
  동사에 도달할 길이 사라진다.
- **닫힘 규약(U2 §2.7)**: 실패(나라 동결·죽은 참조·모호 시트·행 0건·읽기 실패)는 절대 닫지
  않고 면 안 상태줄에 재진술한다. 고정 목록 선택은 남은 결정이 없어 성사 즉시 닫히고,
  **파일 찾아보기는 성사해도 면을 유지한다** — 「현재 데이터」가 descriptor 로 재진술되고
  그 자리에 「이 데이터 고정…」이 선다(끝난 선택은 닫히고, 결정이 남은 선택은 남는다).
  마운트 진행 중에는 닫기·Escape 를 차단하고 표기한다.
- 전환 손실 가드는 **대상 확정 직후·읽기 직전**에 호스트 콜백으로 묻는다(`confirmSwap`).
- 고정·다시 연결은 `#poolRegModal` 을 이 면 **위에** 스택으로 띄운다(제목이 진입 사유).
  「＋ 직접 등록…」은 죽었다(U2 §2.7 4행 — 「읽지 않고 등록」이 유일한 고유 기능이자 곧
  결함). pin 모드에서는 path·sheet 가 읽기전용이고 폼 안 찾아보기(`#poolRegBrowse`)를
  감춘다(§2.7 5행) — 그 버튼·`pick_pool_data_file` 브리지는 「다시 연결」이 계속 쓴다.
- **데이터 축 정체성 = `normcase(abspath(path)) + sheet`, 이름 = 순수 라벨**(#347, U2 §5.3
  판정 C). 풀 항목 조작(`archive`·`activate`·`delete`·`load_pool`·`relink`)은 슬롯 `key` 를
  겨눈다. `register_excel` 의 중복 판정은 정체성이다: 같은 데이터 재등록은 2건이 아니라
  기존 등록의 라벨·메모 갱신(확인 승격) 또는 「이미 고정돼 있습니다」 재진술로 접힌다.
  `relink`(`key`+새 참조)는 같은 슬롯의 참조 교체(수명 보존)이고 확인 왕복을 거친다.
  구판(이름=키)이 남긴 **같은 정체성 등록 2+건**은 스냅샷 `duplicates` 로 loud 표면화되고
  `resolve_duplicate`(남길 `keep` 확정, 확인 왕복)로만 정리된다 — 조용한 자동 병합 금지.
- **파괴·덮어쓰기 확정은 「보여준 상태의 지문」에 결속된다** — 이 화면의 확정 왕복
  **넷 전부**(`delete` · `register_excel` 의 라벨 갱신 · `relink` · `resolve_duplicate`)가
  기제 하나를 공유한다. 1차 응답이 `basis`(`screen_pool.confirm_basis`)를 발행하고 확정이
  그대로 되싣는다. 백엔드는 쓰기 잠금 안에서 지금 상태의 지문을 다시 지어 대조하고,
  다르거나 미동봉이면 **삭제·덮어쓰기 0건 + loud 재진술 후 재확인**(fail-closed).
- 지문 재료는 **표시 요약이 아니라 정체를 정하는 전체 값**이다(`screen_pool.bound_state` —
  슬롯 키·이름·종류·정규화 정체성·`opts` 원본·비고·수명). `reference_summary` 는 사람이
  읽으라고 경로를 basename 으로 줄이는 함수라 결속에 쓰면 `/a/x.xlsx`→`/b/x.xlsx` 교체가
  지문을 통과한다. 문안은 요약(`display_reference`)을, 결속은 전체 값을 쓰되 **소재는 그
  시점의 디스크 항목 하나** — 보여준 것과 대조하는 것이 갈리면 그 틈이 곧 고지 없는
  파괴다(에디터 `confirmed_overwrite_text` 동형).

### `job` 세션 표면의 형상 (v6 `screen-data` 2열 — 재작성 R1)

세션 패널(`#jobZones`)은 구 4존(헤더·데이터·본문·완료)이 아니라 **v6 `screen-data` 2열**이다
(`.data-grid` — 정본 `docs/archive/DATA_FIRST_INTEGRATION_MAP.md` §10.5 R1).

| 열 | 구획 | 소유 |
|---|---|---|
| 좌 `.dg-main` | 현재 데이터(겨눔·검색·필터·표·필터 밖 스트립) → 본문 확인(표 없는 한 줄 — U2 §2.13) → 생성 결과 | 데이터-우선 흐름의 입력과 되읽기 |
| 우 `.dg-side` | 이 데이터에 사용할 문서(후보·추천·탐색 출구 — 활성 카드가 정체·템플릿·연결 상태를 겸한다) → 생성 준비(저장 폴더·재진술) | 문서 선택과 실행 준비 |

- 두 열은 존 구분선을 공유하는 **한 카드 안의 구획**이고, 컨테이너 900px 이하에서 1열로
  퇴화한다(`@container session-panel`). 구 `.job-duo`(표\|거울 가로 병치, #272)는 이 형상으로
  대체됐다.
- **본문 확인 존은 표 없는 한 줄이다**(U2 §2.13 · #346): 빈 값 표지(필드 이름 지목 —
  정보이지 클릭 표적이 아니다) + 이름 건수 + 확인 면 출구(「생성 값 미리보기 ⤢」). 구 거울
  테이블(필드 채움 표·클릭형 ack 행·420px 캡·펼침 면 `#jobConfirmSheet`)은 필드축 ack
  폐기와 함께 사망했다 — **값·이름을 말하는 표면은 확인 면(`#previewSheet`) 하나다**(C3
  폐색). danger 차단 배너(드리프트·미해소 토큰)는 같은 자리·같은 형상으로 남는다. 인라인
  재진술(`#jobRestate`)은 선택 유래·산출 수치·경로만 말하고, 파일 이름 목록은 확인 면의
  「이름 계획」 한 줄로 이주했다.
- **znum 4존 서수는 이 화면에서 은퇴**했다(v6 는 순서 있는 4단계가 아니라 마주 보는 두 열).
  「다음에 어디로」의 정보는 게이트 문안 앞머리의 **구획 이름 지목**(`gateStep`)이 승계하며,
  지목 문자열은 실재하는 `zone-cap` 캡션과 일치해야 한다(죽은 번호는 지목을 거짓말로 만든다).
  **지목의 근거는 링1 이 낸 축 이름**(`gate.reason` — `no_data`·`no_rows`·`no_candidates`·
  `no_job`·`drift`·`name_tokens`·`template_missing`…)이고 표면은 이름을 자리로 옮기기만
  한다(#342 리뷰 P2). 표면이 상태를 다시 읽어 지목을 만들면 게이트 **서열**이 두 곳에 살고,
  실제로 그렇게 샜다 — 템플릿 부재를 직접 보고 접두를 붙이는 바람에 `workbench_entry_gate`
  가 「행 선택이 먼저」라고 판정한 상태에서도 문서 선택기를 가리켰다. 템플릿 축은 지목이
  **빈 문자열**이다: 그 축을 소유하던 존은 죽었고 복구는 같은 줄의 액션바 재연결이 진다.
  구 「기안」의 znum 문법은 화면과 함께 사망했다(F6 PR-B) — 작업대는 서수 없는 몰입 셸이다.
- 좌 master 작업 목록은 **존치**한다 — 사망은 F2 PR-B 다(지도 §10.8). 그 관리 동사 중 열린
  세션의 정체와 결속된 것(`rename_job`·`set_group`·`rename_group`·`disband_group`)은 이 화면
  컨트롤러가 계속 **소유**하고, 라이브러리 표면이 교차 화면 dispatch 로 부른다(§10.8 판정 F) —
  여기서 재구현하면 같은 상태를 두 판정이 내게 된다. `toggle_group`(그룹 접힘)의 소유는
  라이브러리로 넘어갔고 두 화면이 같은 영속 키(`job_collapsed_groups`)를 공유한다.
- 생성 버튼은 계속 하단 sticky 액션바(`#jobActionBar`)다(#179 슬라이스 5b — 스크롤 무관 상시
  도달). v6 시안의 side-card `run-actions` 배치와 다른 지점이다.
- **「선택한 작업」 존은 사망했다**(U2 §4 판정 A, #342 — 실측상 어포던스의 세 번째 사본).
  승계: 작업명 = 활성 카드 하이라이트 + **액션바 이름**(`#jobActionName` — 활성 카드는
  스크롤 위로 사라지므로 상수 높이 층이 정체를 겸한다, §4-A 상속 의무) · 템플릿 파일명 =
  활성 카드 확장 부제(`cand-tpl`) · 열기/폴더에서 보기 = **활성 카드 ⋮**(부유 `#jobCandMenu`,
  그룹 ⋮ 동형 — React ContextMenu 재사용) + 라이브러리 상세 신설(§2.20) · `template_missing`
  경보 = 카드 **「연결 상태」**(`conn_label` — 텍스트가 정본, 경고색은 강조, 판정 C) ·
  「템플릿 다시 연결…」 = **경고 카드 기본 클릭 대체**(판정 D — 클릭이 선택 대신 안내
  다이얼로그 + 재연결 리다이렉트, 활성+경고면 경고가 이기고, 재연결 커밋이 성사된 **뒤에야**
  이어서 선택이 한 체인으로 나간다; 실패·취소면 선택하지 않는다). 편집기 「템플릿」 탭의
  같은 어포던스는 그대로 산다(사본 셋→둘, §2.20 ⑷).
- **재연결 도달은 세션 축의 불변식이다**(#342 리뷰 3라운드 근본 조치): *활성 작업이 있고
  템플릿이 부재면 재연결 경로가 화면에 있다.* 그 보장은 후보 카드가 아니라 **액션바**
  (`#jobActionConn`·`#jobActionRelink`)가 진다 — 후보 구획은 데이터 마운트·호환성·순위
  슬라이스 셋에 걸린 투영이라 보장을 얹으면 조건마다 구멍이 난다(리뷰가 같은 결함류를 세
  조건에서 3번 냈다). 액션바는 조건이 없고 세션 스냅샷 두 값(`template_missing`·
  `conn_label` — 술어·문안 모두 Python `_template_conn` 단일 출처, 매체 3가지 전부에서
  같은 술어)만 읽는다. 두 입구(경고 카드 클릭·액션바 버튼)는 **한 몸통**(`relinkTemplateFor`)
  을 써 확인 문안·T1 무장 가드·발신 순서가 갈리지 않는다. 상태 순회 단언은
  `tests/test_webapp_job.py` 의 불변식 테스트, 실렌더는 selftest `job_active_card` 프로브.

#### 전체 표시순서 축 (F3 — 지도 §10.11)

좌 열 표 위 `#jobOrderBar` 가 계약 §18.10 의 `viewOrder` 를 사용자 축으로 연다
(`sourceDesc`=최신 행 먼저 / `sourceAsc`=원본 순서, 2값 고정).

- **소비처는 하나의 훅**(`_display_indices`)이다: 표·필터 밖 선택 스트립·실행 입력·파일 이름
  계획이 전부 이 투영을 통과한다. 어느 하나가 원본 순서로 남으면 「보이는 것 = 만들어지는
  것」이 거기서만 깨진다.
- 축은 **데이터 귀속**이다 — 새 데이터·시트 교체는 `sourceDesc` 로 되돌리고(불변식
  §18.11-13), 개인화 설정으로 승격하지 않는다. 작업 선택은 축을 건드리지 않는다(§18.11-23).
- 순서 변경은 **선택 집합을 바꾸지 않는다**(투영 대 집합). 바뀌는 것은 생성 순서와 그 함수인
  파일 이름 순번이며, 옆 문안(`#jobOrderNote`)이 이를 상시 재진술한다 — 순번 절은 규칙이
  실제로 `{{seq}}` 를 쓸 때만 붙는다(안 쓰는 작업에 말하면 문안이 거짓이 된다). 확인 왕복은
  두지 않는다: 표 「문서」 열이 새 이름을 즉시 보여준다.
- ⤢ 펼침 면에는 **같은 요소가 이동**한다(복제 금지 — 상태가 둘로 갈린다). 왕복 중에는 방금
  고른 값이 이기고(`pendingOrder`), 실행 거동은 selftest `view_order` 프로브가 지킨다.

#### 전문 범위 편집기 = ⤢ 펼침 면 + 초안 거래 (F3 — 지도 §10.11)

「펼쳐서 행 고르기 ⤢」는 계속 실 DOM 을 옮기는 `SurfaceSheet` 면이고(별도 화면 신설 없음),
**의미론만** 새것이다 — 면 안의 편집은 초안(`RecordRangeDraft`)으로 격리된다.

- 초안은 **Python 소유**다. 존 13액션은 이름 그대로 초안을 향하고(같은 동사, 다른 대상),
  경계는 믹스인의 훅 4개(`_zone_sel`·`_zone_flt`·`_zone_set_flt`·`_zone_visible`)에 한 번만
  적힌다. 기본 구현이 커밋 상태를 돌려준다(존 소비 화면은 이제 이 화면 하나다 — F6 PR-B).
- 스냅샷 이중 소스 경계: **초안** = 표·필터·칩·필터 밖 스트립·재진술·footer 수치·표의 실
  파일 이름 / **커밋** = 실행 입력·게이트·본문 확인 한 줄·후보·세션 가드·직전 필터 슬롯. 적용 전 메인
  범위는 불변이다(불변식 §18.11-21).
- footer(`#jobRangeFoot`)는 **화면 DOM 소유**이고 면 슬롯 안에서만 보인다(CSS — 면 공유자
  「기안」은 사망했지만 슬롯 격리 규율은 그대로 산다). 구성 = 상태 문안 · 「선택된 항목만
  보기」(초안 전용 보기 상태로 적용 대상 아님) · 「취소」 · 「선택 적용: N건」.
- 출구는 **한 관문**을 지난다: 취소·닫기·Escape 전부 `beforeClose` 가드를 통과하고, 변경이
  있을 때만 확인을 묻는다(「버리고 닫기」 / 「계속 편집」). 3택을 두지 않는 근거는 「적용」이
  면 안의 상시 버튼이라는 것 — 가드가 세 번째 선택지를 새 기제로 만들 필요가 없다.
- 열기는 **성사 뒤**다: 초안 생성이 거절되면(데이터 없음·생성 중) 면을 띄우지 않는다. 적용
  실패(스냅샷 세대 불일치)에서도 면을 닫지 않는다 — 문맥을 남긴다.
- 초안이 열린 동안 생성은 잠긴다(버튼 비활성 + Python 거절). 잠금은 DOM 이 아니라 상태가
  진다 — 모달에 가려 못 누르는 것과 잠긴 것은 다른 사실이다.

#### 확인 면 = 생성 값 미리보기 시트 + 검토 요구 (F5 — 지도 §10.12 · U2 §2.13 승격)

레코드 1건이 실제로 받을 값과 파일 이름을 보여주고, 확인이 필요한 변경이 있으면
그 자리에서 **명시 승인**을 받는다. 골격은 index.html 정적 DOM(`#previewSheet` — 구
680px 모달 `#previewModal` 의 시트 승격: 값을 말하는 유일 표면이 됐고 렌더러가 올
자리다), 호스트는 공용 `modal.js` 스택이다(신설 0).

- **열림과 자리는 Python 소유**다(`preview` 스냅샷 구획). 자리는 **표시순 서수**이지 원본
  index 가 아니고, 웹은 이동 **방향**(`preview_move {delta}`)만 보낸다 — 좌표를 되돌려주면
  그 사이의 데이터 교체·표시순서 변경이 남의 행을 고른다.
- **값과 이름은 파생**이다: 값은 실행 입력과 같은 `mapped_records`, 이름은 표 「문서」 열이
  쓰는 그 문자열(`RunStatus.audit`)이다. 한 건만 따로 계산하면 `{{seq}}` 가 1 로 고정되고
  꼬리표가 사라져 미리보기가 실행과 다른 이름을 말한다.
- **드로어는 커밋 세계를 그린다**: 범위 초안이 열려 있으면 열지 않는다(적용도 안 한 편집을
  승인하는 것은 불변식 §18.11-21 위반). 생성 중에도 열지 않고, 열려 있으면 잠근다.
- **요구가 없어도 열린다**(§13-2 정상 반복 실행에서 미리보기는 선택). 승인 버튼은 요구가
  남아 있을 때만 서고, **면을 연 것은 승인이 아니다**(§13-4). 승인은 면이 열려 있을 때만
  받는다 — 증거를 띄우지 않은 경로의 승인은 무엇에 근거했는지 말할 수 없다.
- 검토 요구(`ReviewRequirement`)는 규칙의 **대상별 지문**과 마지막 완주가 남긴 기준선
  (`Job.reviewed_rules`)의 차이다. 위험은 파일명 집합 > 의미 연결 > 표시형이고 위험마다
  다른 증거를 싣는다. 템플릿 변경은 승인 축이 아니라 드리프트 게이트가 진다.
- **빈 값도 요구다**(`blank_set` — U2 §2.13, 필드축 ack 폐기의 보정): 규칙이 기준선과
  같아도 이번 실행 입력에 빈 값이 있으면 요구가 선다 — 표식(`MISSING_MARKER`)이 박히는
  실행이라 승인 없이 조용히 생성되지 않는다(침묵 금지). 표식 조건은 「빈 값이 있으면」
  하나로 단순하고(`_run_marker` — 생성·미리보기·승인의 단일 술어), 승인 지문의 표식
  성분은 **빈 값 필드 집합의 해시**다(집합이 갈리면 승인 자동 무효). 구 필드축
  ack(`ack_field`·`unack_field`·거울 클릭=확인·UD-19 재클릭 토글·가드의 `ack_count`)는
  전부 사망 — 표면 어휘는 「승인」 하나다(§2.10 방향 유지).
- 승인 유효 범위는 위험별로 다르다: 표시형은 규칙 지문에만(단 빈 값이 있으면 선택 결속으로
  승격), 의미·파일명·빈 값은 **선택 지문까지** 결속된다(선택·순서가 바뀌면 그 증거 자체가
  무효다).
- **「빈 값 있는 건만 보기」**(`preview_blank_only` — §2.13): ‹ › 이동을 빈 값 있는 건으로
  한정한다(선례: 결과 존 「실패한 건만 선택」). 상태·경계(`blank_only`·`blank_count`·
  `can_prev`·`can_next`)는 Python 소유이고 표면은 스냅샷을 되읽는다(낙관 토글 없음).
  빈 값 건 0이면 비활성 + 켜기 거절. 면이 닫히면 열림·자리와 함께 놓는다.
- **「이름 계획」 한 줄**: 인라인 재진술의 파일 이름 목록이 이주한 자리 — 건수·저장 폴더를
  집합으로 말하고, 개별 이름은 ‹ › 훑기(파일 이름 칸)가 말한다.
- **적용 범위 축은 없다**(U2 §2.3) — `runOverrides`(F7 **PR-B**)가 기각·사망하면서 이 축의
  존재 이유가 사라졌다. 값이 하나뿐인 축은 정보가 아니라 고를 수 없는 선택지의 암시다.
  override 가 실제로 서면 그때 축이 함께 돌아온다. 행별 「수정」 deep-link 도 PR-B 소관이라
  지금은 드로어 하나의 「이 작업 편집」 출구이고, 그 출구는 진입 문맥(`preview_result` + 보고
  있던 행)을 실어 편집기 배너가 왜 왔는지를 말한다(F7 PR-A).
- 게이트 서열에서 검토 요구는 **전제조건 다음·열림 직전**(warn, `reason="review_required"`)
  이다. 선택 0건·저장 폴더 미지정 상태에서 "검토하세요"는 이행 불가능한 지시다.

#### TXT 검토·복사 작업대 = 고정 사본 세션 (F6 PR-A — 지도 §10.15)

TXT 작업은 「문서 만들기」에 **합류**한다(대조표 17·18행): 후보·문서 탐색·데이터 존을 HWPX
와 똑같이 쓰고, 갈리는 것은 실행 행동뿐이다 — 「N개 생성」 대신 **「검토·복사 시작 · N건」**
이 작업대(`#scr-workbench`)를 연다.

- **작업 방식은 3값이고 연결 상태는 다른 축이다**(§19.1). 값·파생은 링0
  (`work_mode`), 표시 문구는 링1(`gui/work_mode.py`) 단일 출처 — 후보 카드·문서 탐색·
  라이브러리 셋이 같은 문자열을 쓴다. 라이브러리 필터의 「미연결 → hwpx」 귀속은 *필터
  규칙*이지 방식 파생이 아니다(두 함수를 합치지 않는다).
- **후보 자격은 `unsupported` 만 가른다**: hwpx·txt 는 같은 술어(필요한 열이 현재 데이터에
  있는가)로 판정된다. 미상 확장자·미연결은 그대로 fail-closed 제외다.
- **세션은 진입 시 고정 사본**(§13-13·§18.11-25): 표시순 투영을 통과한 OrderedSelection 의
  복사본을 받고, 이후 「문서 만들기」의 검색·필터·정렬·선택 변화가 작업점 순서를 바꾸지
  않는다. 그래서 작업대에는 데이터 존이 **없다** — 데이터를 바꾸려면 나갔다 다시 들어온다.
- **진입은 성사 뒤다**: 생성 중·범위 초안 열림·선택 0건이면 화면을 세우지 않고 사유를
  돌려준다(작업대는 **커밋된** 실행 입력의 사본을 뜬다 — F5 드로어와 같은 경계).
- **좌 pane 은 미저장 변경이지 override 가 아니다**. 착지점은 「기본 규칙으로 저장…」
  하나이고, 확인 문안이 dirty 필드를 **전부** 나열한다(§11). 저장은 Binding 판본을 올리고
  같은 작업점으로 돌아오며, 이미 복사한 레코드는 「다시 확인 필요」가 된다. 거래 모델은
  편집기와 같은 `EditSession`(section=`binding`)이다.
- **저장은 잠금 안에서 디스크를 다시 읽는다**: 작업대 세션은 오래 열려 있어 진입 시 읽은
  Job 이 특히 낡기 쉽다. 그룹·태그·완주 스탬프는 최신값을 승계하고, 규칙이 외부에서
  갈렸으면 조용히 덮지 않고 확인을 다시 받는다.
- **승계 4종은 거처만 옮긴다**: 큐 퇴화(1건이면 큐 장치 3종 은닉) · T3 가드(복사 진행 중
  이탈) · 정렬 린트(카드와 클립보드가 같은 값) · 확정-비움(게이트에서 제외). 판정 소유자는
  각각 `TxtQueueModel`·가드 술어·`gui/txt_card.py`·`MappingModel` 그대로다.
- **검토 요구·미리보기 드로어는 배제 선언**: TXT 엔 파일 이름 축이 없고(§3.2) 작업대가 이미
  레코드 전수를 채운 모습으로 보여 주는 검토 표면이라, 같은 확인을 두 표면이 겸하지 않는다.

#### 생성 결과 = 3태 구획 + 실행 기록 (F4 — 지도 §10.10)

결과는 좌 열 하단 `생성 결과` 존에 선다(v6 는 화면 상단 전폭 `result-panel` — 어긋남과
되깎기 조건은 §10.10 판정 H). 한 구획(`#jobResult`)이 다섯 상태를 진다.

| `[data-state]` | 언제 | 판정 |
|---|---|---|
| `completed` · `partiallyCompleted` · `failed` | 실행이 끝났을 때 | **Python 단일 산출**(`status`) — 계약 §10, 불변식 §13-10 |
| `running` | 생성 진행 중 | 진행 델타(태를 덮지 않고 자리를 빌린다) |
| `rejected` | 실행 **전** 거절(게이트 방어 재확인) | 결과가 아니라 "생성하지 않았다" |

- **태와 색은 다른 축**이다: 구조는 `data-state`, 색 채널은 `data-level`(ok·warn·danger)이
  지고 JS 는 둘 다 재계산하지 않는다. 취소 런은 네 번째 태가 아니라 `partiallyCompleted` +
  `cancelled` + warn 이다(#278 이 세운 채널 보존).
- 실패 행은 **원본 index 앵커**(`#jobResultFail-<index>`) + 식별 요약 + 실파일명 + 사유다.
  식별 요약은 표 「문서」 열과 같은 링1 판정(`identity_summary`)이라 결과에서 본 이름으로
  표에서 그 행을 찾는다. 아는 원인이 없는 실패에만 **「원인 진단 미연결」**(계약 §10.3)이
  붙는다 — 원문은 언제나 보존된다.
- 「실패한 N건만 선택」은 **선택만** 바꾸고 생성하지 않는다(2클릭 분리). 재시도·레코드
  filename override 는 `runOverrides`(F7) 선행이라 아직 없다. 노출·라벨은 실패 행 목록이
  아니라 Python 수치(`failed_selectable`)가 정한다 — 배치 진입 전 실패는 레코드별 시도가
  없어 행이 0개인데 다시 만들 대상은 전량이다.
- 중단(`cancelled`)은 성공 수와 무관하게 `partiallyCompleted` 다 — 첫 레코드 전에 멈춘 런은
  실패한 시도가 없으므로 실패 태를 달지 않는다(없던 실패를 지어내지 않는다).
- 결과 처분은 지문 **성분별 2분기**다(U2 §2.18 · #340): **작업 전환·데이터 교체 = 초기화**
  (링1 이 이미 실행 증거를 죽인 축 — §19.10 "잃는 것은 실행 증거뿐") · **선택·규칙·저장
  폴더 = 강등 유지**(「직전 실행」 표기 — 「실패한 N건만 선택」이 자기 결과를 없애면 안
  된다는 판정 G 의 논거가 사는 축). 이름 변경은 전환이 아니다(주체 `last_run_job` 이 이름을
  추종한다). 자동 초기화는 실행 기록에 **퇴장 한 줄**(주체·건수·경로 — 세션 스코프)을
  남기고, 강등과 명시 파기(`결과 닫기`)는 남기지 않는다(치우라는 행동이 흔적을 남기면 반만
  듣는 것이 된다).
- 결과 행동의 **주체 판정은 스냅샷이 낸다**: 직전 런의 주체는 세션 상태(`last_run_job`)가
  들고 이름 변경을 같은 전이에서 추종하며, 표면은 `last_run_job === job_name` 두 Python
  값만 비교한다(정체를 표면이 보관하지 않는다). 주체가 아니면 증거는 남기고 행동 2종
  (파일 이름 규칙 수정·실패한 N건만 선택)만 걷는다 — 강등된 결과의 행동이 지금 열린 작업을
  겨누면 남의 작업을 편집하거나 확실한 무동작이 된다.
- `generate` 는 dispatch 밖이라 자동 push 가 없다 — 런이 끝나면 컨트롤러가 스냅샷을 한 번
  흘린다(주체·완주 스탬프). 덮어쓰기 확인 왕복에는 밀지 않는다.
- `#jobGenLog` 는 **실행 기록**으로 남는다: 결과 사건은 3태 구획이 가져갔고, 여기 남는 것은
  비-결과 사건(데이터 불러옴·검색/열기 실패·중단 요청·고지)이다 — 이 화면의 유일한 비모달
  사건 채널이라 함께 죽이지 않았다. **기본은 접힘**(`<details#jobRunLog>`)이되 **마지막 기록
  한 줄은 접힌 채로도 보인다**(`#jobRunLogLast`) — 접힘은 노이즈 억제이지 소음 제거가 아니다.

### `job` 화면의 데이터-우선 세션 계약 (data-first 봉합)

`JobController` 는 마운트된 데이터(`datasource`·`records`)·선택(`SelectionModel`)·필터를
**세션(컨트롤러) 소유**로 보유한다 — 정본: `docs/archive/DATA_FIRST_INTEGRATION_MAP.md`.

- 데이터 마운트(`pick_data_file`→`load_data_path`, `load_data_sheet`, `load_pool`)는 **작업
  미선택에도 허용**되고, 마운트 직후 선택은 **0건**이다. `load_pool` 의 겨눔은 풀 **슬롯
  키**(`key`)다(#347, U2 §5.3 — 이름은 중복 허용 라벨이라 겨눔의 정체가 못 된다).
- `select_job` 은 vm 만 재생성하고 세션 데이터를 주입한다(`RunViewModel.set_acquired`) —
  데이터·선택·필터는 **전환·해제에서 생존**하고, 잃는 것은 실행 증거(완주 담보·승인)뿐이다.
  구 T1 스위치 가드(`needs_confirm`/`switch_job`)는 파괴가 사라져 함께 죽었다.
  **작업 선택은 데이터를 세우지 않는다**(#347 — 구 `default_dataset_ref` 자동 조준 폐기,
  데이터↔작업 결속은 어느 방향으로도 다시 들이지 않는다).
- 스냅샷은 데이터 준비 시 `candidates`(현재 데이터 호환 작업 후보 — 링1
  `gui/work_candidates.py` §18.4 단일 판정)를 싣고, 작업 미선택 게이트는 링1
  `prework_gate` 산출을 그대로 렌더한다(링2 문안 재조립 금지).
- `candidates` 는 4구획이다(슬라이스 2): `top`(상위 `MAIN_TOP_N` available, 링1
  `rank_available` 순위 — 즐겨찾기→최근 사용→미사용)·`more`(순위 밖 available 수,
  0이 아니면 표면이 정직하게 고지)·`needs`(확인 필요, 이름순)·`suggested`(추천 이름).
  `top` 의 각 카드는 템플릿 정체(`template_name`·`template_path`·`template_missing`)와
  「연결 상태」 문안(`conn_label` — 정상은 빈 문자열로 조용히)을 함께 싣는다(U2 §4, #342):
  available 판정 자체는 §18.4 대로 Binding 호환성만 보되, 부재는 파일 존재 검사 하나라
  후보 축에서 미리 말한다(판정 F — 눌러본 뒤 차단은 뒤늦은 경보). 단 `candidates` 는
  데이터 마운트·호환성·순위 슬라이스에 걸린 **투영**이므로 **재연결 도달 보장을 여기 얹지
  않는다**(#342 리뷰 3라운드 근본 조치 — 조건마다 구멍이 하나씩 나 같은 결함류가 3번
  반복됐다). 카드의 「연결 상태」·경고 클릭은 *렌더된 카드에 대한* 계약이고, 보장은 아래
  세션 축이 진다.
  **추천은 표지일 뿐 전이가 아니다** — `job_name` 은 사용자 클릭(`select_job`)으로만 바뀐다
  (§18.3 개정, v6 상태전이 리뷰 F-02). 순위·추천 계산은 전부 링1이 하고 JS 는 그리기만 한다.
- 스냅샷은 `browse`(문서 탐색 §18.6·§19.5 — 탭·검색어·행·탭 건수·검색으로 걸러낸 수)도
  싣는다. 탭·검색어는 **세션 소유**(`JobController`)라 탭을 옮겨도 검색어가 살고 시트를
  닫았다 열어도 찾던 자리로 돌아온다. 검색 대상은 작업 표시 이름만이고 일치 규칙은 앱 전역
  자모 부분일치(`core.jamo`)다. 탭 건수는 **검색 전** 값 — 탭 라벨은 데이터에 대한 사실이다.
  액션 `browse_tab`(`tab`)·`browse_query`(`text`).
- **탐색 면의 클릭 목적지는 사유가 가른다**(U2 §4 판정 E, #349 — §18.7 6분기 중 이 둘만
  짓는다). 「확인 필요」 행(= 데이터 구조 불일치, master `needs_action` 의 유일 원인)은
  없는 열을 열거한 채 **새 작업 마법사**(`new_job_from_data`)로 가고, 템플릿 부재는 후보
  카드의 「연결 상태」 축에서 **재연결**로 간다(#342 의 자리 그대로). 나머지 넷은 짓지
  않는다: 1은 실행 게이트가, 2·3은 데이터 축이 이미 풀고, 5는 후보 목록의 정체를 바꾸는
  별개 결정, 6은 계약이 리다이렉트를 금지한다. 같은 마법사의 다른 입구가 후보 줄의
  「＋ 이 데이터로 새 작업」(`#jobCandNewWork`, §2.4)이고 **흐름 몸통은 하나**다.
- 그 입구의 **가부·참조는 한 판정**이 낸다 — `DataZoneMixin.new_work_handoff()` 가
  `({path, sheet, header_row}, "")` 또는 `({}, 사유)` 를 돌려주고, 스냅샷 `new_work`
  (`{can, reason}`)와 브리지 `new_job_from_data` 가 **같은 값**을 읽는다. 표면이
  `data_target.path` 유무로 유추하면 「누를 수 있다」고 그려 놓고 백엔드가 거절한다
  (#349 리뷰 1R: `_do_load_pool` 은 엑셀 참조에만 `data_path` 를 채운다 — 그 값은
  로케이트·고정 프리필의 것이다). 참조를 경로로 줄이지도 않는다: 등록 데이터의
  `header_row` 를 떨어뜨리면 마법사가 **다른 헤더**에 앵커를 건다. 파일로 다시 열 수 없는
  마운트(조립 파이프라인)는 버튼을 숨기지 않고 **비활성 + 사유 병기**로 거절한다.
- 그 참조는 **마운트 성사 시점에 포획**된다(`data_path`·`data_sheet`·`data_header_row` —
  세 값이 같은 시점의 한 벌). 승계가 풀 슬롯을 다시 읽지 않는 이유는 슬롯이 가변이기
  때문이다(#349 리뷰 2R): 「다시 연결」은 참조만 갈아 끼우고 수명을 보존하는 정상 수명
  사건(#347)이라, 재마운트 전까지 화면은 **옛 참조로 읽은 레코드**를 보여 준다 — 그때
  슬롯을 재해석하면 「표시는 A · 시작은 B」가 된다. 같은 규율이 마운트 descriptor
  (§2.7)·소스 일치 키(`_data_key`)에도 걸린다: **나중에 다시 읽어 판정하지 않는다.**
- **마법사로 가는 입구는 전부 그 한 게이트를 지난다**(#349 리뷰 3R). 현재 입구는 둘
  (후보 줄 `#jobCandNewWork` · 탐색 면 「확인 필요」 행)이고, 링2 는 판정을 한 자리에서만
  읽고(`newWorkGate`) 행동 훅은 한 표(`NEW_WORK_HOOKS`)를 게이트가 감싼 헬퍼
  (`newWorkAttrs`)만 발행한다 — 막혔으면 훅 대신 `disabled` + 사유가 나가므로 입구가 늘어도
  게이트를 건너뛸 수 없다. 그 불변식은 정적 계약이 **훅 발행처 census** 로 잡는다(표 밖의
  발행 = 실패). 막힘은 숨기지 않고 두 입구 모두 제자리에서 사유를 말하며, 비활성 입구에는
  `data-busy-lock` 을 달지 않는다(생성 종료의 일괄 복원이 되살린다).
- 탐색 면을 떠나며 **다른 모달을 여는 흐름은 닫힘이 끝난 뒤에 시작한다**(#349 리뷰 4R —
  `browseAfterClose` 1슬롯, 소비는 착지 결정과 같은 `onClose` 한 지점). 이 면의 `onClose` 는
  닫힘 경로 전부에서 무조건 배경으로 초점을 옮기므로(착지 1지점 규율), 닫는 중에 확인
  모달이 서면 그 착지가 모달 **뒤**로 초점을 옮겨 트랩을 벗어난다. `Modal` 은 자기
  `returnFocus` 만 `wasTop` 으로 지킬 수 있다 — 앱 콜백이 무엇을 겨눌지는 그 화면만 안다.
- **데이터를 들고 시작한 초안은 템플릿을 골라도 앵커를 잃지 않는다**(#349 리뷰 3R):
  `EditorController.new_job_session` 은 진입 사유가 `document_browser_new_work` 인 초안에
  한해 데이터 문맥과 진입 문맥을 초기화 너머로 승계한다. 그 예외가 없으면 1단계에서
  「이 템플릿으로」를 누른 **모든 사용자**가 보통의 빈 초안으로 떨어진다. 이름·매핑·단계는
  종전대로 끊긴다(혼합 세션 금지 불변).
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

`LibraryController`와 React producer(`frontend/src/screens/library.ts`)가 홈 화면을
대체한다(재작성 F2 PR-A). 링1
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
- 상세 `<dt>템플릿</dt>` 행은 이름 곁에 **「열기」·「폴더에서 보기」**(PathActions 아이콘,
  `detail.template_path` 겨눔)를 신설로 싣는다(U2 §2.20, #342) — 경보(템플릿 미연결 N건)는
  이 화면이 내는데 조작이 여기 없었다(계기판의 짝). 어휘·아이콘은 PathActions가 소유하고,
  자리는 템플릿 행 안이다(자리가 대상을 말한다). 경로 검증은 백엔드 화이트리스트, 클릭은
  React 핸들러 — 신설 배선은 payload 한 칸(`template_path`)뿐이다.
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
  `scripts/gen_design_tokens.py`가 커밋되는 `frontend/css/tokens.css`와 동결 목업의 생성 구간을 만든다.
  `tests/test_design_tokens.py`가 생성물 드리프트를 막는다.
- 실제 레이아웃·컴포넌트 스타일의 단일 출처는 `frontend/css/` 아래 **9개 스타일시트**다
  (`base`·`draftcard`·`editor`·`job`·`overlay`·`library`·`forced-colors`·`jobdata`·`tail`).
  구 `app.css`를 **순서 보존 컷**으로 자른 것이라 링크 순서대로 이어붙이면 옛 파일과 바이트
  동일하고, 그래서 **`<link>` 순서가 캐스케이드 계약**이다 — 목록·순서의 단일 출처는
  `tests/_web_css.py`의 `APP_CSS_FILES`이고 `tests/test_web_css_manifest.py`가 셸 링크 순서와
  `frontend/css/*.css` 전수 등재를 게이트한다. 현재 앱을 판단할 때 동결 목업의 인라인 CSS를
  사용하지 않는다.
- 한 번만 쓰이는 정적 문구는 `frontend/index.html` 또는 해당 화면 JavaScript/Python 산출자가
  소유한다. 둘 이상에서 공유하는 사용자 문구만 `frontend/js/copy.js` 등 명시적 공용 상수로 올린다.
  문구 규율과 금지어는 [카피 스타일 가이드](COPY_STYLE_GUIDE.md)와 관련 테스트가 맡는다.

## 변경 규율

- 링1 공개 API를 바꾸면 이를 소비하는 컨트롤러와 관련 헤드리스 테스트를 함께 갱신한다.
- DOM `id`, `data-*`, script 순서 또는 화면 루트를 바꾸면 정적 DOM 계약을 먼저 갱신하고,
  실제 동작이 관여하면 WebView2 selftest 시나리오도 갱신한다.
- 목업은 [동결 시안](UI_PROTOTYPE_APPB.html)이다. 현재 기능을 설계하거나 검증하기 위해 목업을
  먼저 고치지 않는다. 보존된 `data-vm` seam이 더는 유효하지 않을 때에만 역사 계약과 함께
  명시적으로 정리한다.
