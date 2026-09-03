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

1. **링0 — kernel/도메인/데이터:** `src/hwpxcore/`, `src/hwpxfiller/domain/`,
   `src/hwpxfiller/data/`. 문서 형식, 제품 모델, 데이터 소스를 소유하며 UI 런타임을 모른다.
2. **링1 — ViewModel/상태:** `src/hwpxfiller/gui/*_state.py`의 Qt-free 모델. 링0을 호출하고
   상태·게이트·직렬화 가능한 값을 제공한다. DOM이나 pywebview를 임포트하지 않는다.
3. **링2 — 웹 프레젠테이션:** `src/hwpxfiller/webapp/`의 컨트롤러·브리지와 `web/`의
   HTML/CSS/JavaScript. 링1을 호출해 JSON-safe snapshot으로 바꾸고 DOM에 렌더한다.

### 외부 mechanism 착지 규율 (P3-06 · #588)

외부 package가 제품 의미를 모른다는 사실은 그 package를 전역 core에 둘 근거가 아니다.
import는 **그 기능을 실제로 조립하는 integration 경계**에 두고, Product Domain과 Product
Contract에는 vendor type·instance·상태를 노출하지 않는다. integration은 vendor 입력과
callback을 제품 command로, vendor 결과를 제품 result 또는 직렬화 가능한 값으로 번역한다.
따라서 `frontend/src/contract/contract.gen.ts`와 Python domain/application 계약은 React 같은
표현 계층 type을 알 수 없다.

runtime dependency를 추가하는 변경은
`tests/architecture_contract.toml`의 `[vendor_integration.*]`에 package, 허용 배치 경계,
`mount_owner`·`update_owner`·`dispose_owner`를 함께 등록한다. 기존 P3 repo-contract 게이트는
등록되지 않은 dependency, 경계 밖 import(type-only 포함), 사라진 lifecycle owner를 거절한다.
owner는 구독·listener·worker·WASM instance 등 자신이 세운 자원을 dispose까지 정산하며,
제품 상태를 vendor 내부 상태에만 보관하지 않는다.

현재 React integration의 허용 착지는 `frontend/src/react/`, `frontend/src/screens/`,
`frontend/src/overlay/host.ts`, `frontend/src/shell/host.ts`다. 단일 root의 mount는
`react/root.ts`의 `boot`, store update 연결은 `react/boundary.ts`의 `StoreSignal`, dispose는
`react/root.ts`의 `unmount`가 소유한다. 여러 기능이 같은 vendor를 서로 다르게 해석하기
시작할 때만 project-owned seam을 둔다. 작은 단일 소비자는 그 기능 경계에서 직접 통합하며,
미래 교체 가능성만을 위한 범용 wrapper는 만들지 않는다.

웹→Python 경로는 두 갈래다(#257 리뷰 — 전 경로를 여기서 계약한다).

- **디스패치 경로:** 순수 데이터 액션은 `WebFrontend.initial(screen)`과
  `dispatch(screen, action, payload)`를 통하고, 허용 화면·액션·payload 키는
  `webapp/action_registry.py`의 `validate_dispatch`가 검증한다.
- **직접 브리지 경로:** 네이티브 자원이 관여하는 호출은 `frontend/js/bridge.js`가
  `WebFrontend` 공개 메서드를 **직접** 부른다 — 파일/폴더 피커(`pick_data_file`,
  `pick_output_folder`, `pick_template_path`, `pick_pool_data_file`), 실행·가져오기
  (`generate`, `import_template_file` — 단건 가져오기+채택(F8 통일, hwpx·txt·RAW 수용).
  폴더 일괄 등록(`import_templates_folder`, #339)은 U6-A(#975)에서 **퇴역**했다 — 폴더가
  곧 풀이 된 뒤로 「폴더에서 한 벌 복사해 온다」는 동사의 전제가 사라졌다),
  서식 폴더 지정(`pick_templates_root` — 폴더 피커 → tpl 권위의
  `set_templates_root`. 전역 값이라 `screen` 은 호출 표면 식별자일 뿐 라우팅에 쓰이지 않는다.
  빈 값·파일 경로 거절은 그 권위 메서드 본문이 진다 — 아래 「서식 폴더 — 단일 루트」),
  에디터 착지(`open_job_in_editor` — 진입 사유가 `DATA_ANCHORED_ENTRY_REASONS` 에 들면
  (지금은 「수정…」의 `document_browser_repair`) 「문서 만들기」의 마운트 데이터 참조를
  **같은 되묻기**(`new_work_handoff`)로 받아 편집 세션이 그 데이터를 들고 선다(#878).
  참조가 없거나 파일로 열 수 없는 마운트면 종전대로 빈 데이터 관문이고, 다시 읽지 못하면
  진입은 계속하되 사유를 통지로 재진술한다. 앞서 열려 있던 편집 세션의 미저장 변경은
  **묻지 않고 버린다** — 그 선판단을 하던 `editor_has_unsaved_work` 브리지는 소비자 0 으로
  사망했다,
  `new_job_from_data` — 「이 데이터로 새 작업」(U2 §2.4·§4 판정 E): 「문서 만들기」가 지금
  마운트한 데이터를 **웹이 실어 보내지 않고** 그 컨트롤러에 되물어 신규 초안을 연다
  (마운트 정체의 단일 출처 = 그 화면. 웹이 기억한 값을 실으면 도착 순서에 따라 다른
  파일로 시작한다). 데이터 부재는 조용히 빈 마법사를 열지 않고 `ERROR:` 로 거절),
  경로 추적
  (`open_path`, `reveal_path`, `copy_path`, `reveal_corrupt_job`),
  산출물 저장(`save_artifact_as` — S7-03 · #825: 결과 존이 나열한 배달 문서 하나를 「다른
  이름으로 저장」한다. 겨눔은 그 실행이 고정한 `ordinal` 하나이고 payload 검증은 메서드
  본문이 진다. 원료는 **그 자리에서 다시 관찰한** 검증된 bytes 그대로이며(#820 D2 — 재물질화
  경로 없음), 관찰이 서지 않으면 저장이 아니라 그 거절을 낸다. 저장 자체의 실패는
  `SAVE_COPY_FAILED` 로 관찰 상태와 **독립** 보고다. 「복사」는 별도 bytes 브리지를 만들지
  않고 행 수준 경로 복사(`copy_path`)가 진다), 클립보드·설정
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

위 두 경로의 어휘(화면×액션×payload 키·직접 메서드 25·프로토콜 v1 상수·오류 어휘·거절
봉투)는 **Python 실물이 정본**이고, TypeScript 쪽은 생성물 하나로만 소비한다 — 같은 계약을
두 언어에서 손으로 중복 유지하지 않는다.

- **생성 사슬:** `scripts/gen_bridge_contract.py` 가 정본(`action_registry`·`product_api`·
  `app.py` WebFrontend·`frontend/src/product_api.js` snake 어휘)을 추출해
  `frontend/src/contract/contract.gen.ts` 를 찍는다. 생성물은 커밋되는 소스이고 손으로
  고치지 않는다 — `tests/repo_contract/test_bridge_contract.py` 가 재생성 바이트 비교(드리프트)에 더해
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
  DOM 을 모른다), `tests/test_web_selftest_gate.py`의 단일 실 WebView2 부팅이 React 커밋·
  store marker 형상을 함께 되읽는다. push 수신의 순수 인과는 store Node 계약이, 실제 push 뒤
  화면 재렌더는 같은 selftest 결과의 화면별 행동 계약이 잇는다.

### 검증·동일 산출물·패키징 기반 접속 (R2-04 · #408)

R2 가 세운 React 기반(root·계약·store)의 검증이 기존 행렬 — 동일 산출물·실 WebView2·오프라인
패키징 — 에 공백 없이 연결되는 경계다. 새 러너·새 번들·새 창을 만들지 않는다.

- **selftest 클러스터 R**(`frontend/src/selftest/probes/react_runtime.js`) 이 실창 문서에서
  React 마커 셋을 판독한다: 커밋 마커 `data-react-mounted` == "1" · store 마커
  `data-react-store-rev` 십진 문자열 · 마커 단 요소 정확 1(**마커 규율 census** — 마커를 심는
  경로가 root.ts 하나뿐임의 재확인이지, 마커를 안 심는 날 `createRoot` 둘째 root 의 방어가
  아니다). 위반은 프로브 throw 라 source 게이트(프로브 무오류 단언)와 packaged 판정
  (`packaging/build.ps1` — 책임 수 43 + `react_runtime` 형상 단언, 오프라인 국면 소유)이
  각자의 기존 경로로 붉는다. revision 절댓값은 프로브 순서에 결합하지 않고 형상만 단언한다.
- **다중 root 의 실방어는 정적 층이다**: `react-dom/*` 결속은 `react/boot.ts` 하나로 핀,
  날 `createRoot(` 호출 census 1(멤버-접근·정의는 세지 않는다), 합성 루트 factory
  (`bootReactRoot`·`createSnapshotStore`) 착좌 census 각 1 — R2-00 불변식(다중 island 금지)의
  기계 검사(`tests/artifact_contract/test_frontend_build_graph.py`).
- **봉인 입력에 tsconfig.json 이 편입됐다**(`web_artifact.py` `_SOURCE_CONFIG_PATHS`) — Vite 의
  `.ts` 변환이 읽는 실빌드 입력이라 dirty 거부·source 레코드 양쪽에 닿는다. 봉인 외부 URL
  술어의 불활성 열거(정확 4 + 접두 1, `.js` 한정 면제)는 R2-01 경계 개정 형상 그대로
  **존치**한다 — 어느 URL 도 소비하는 로더가 산출물 안에 없다(재판정 완료, #408 패킷 §2.3).
- **Vitest/jsdom·범용 JS/TS lint 는 이 단계에서 기각됐다** — DOM 수명주기의 실증은 실
  WebView2 module selftest가 이미 지고(마운트 커밋·reload 재초기화·store marker), jsdom 은 그보다 약한
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
  렌더)·집행 계약은 `tests/js/overlay_host.test.js`, `bootProduct` 합성 경계는
  `tests/js/bootstrap.test.js`가 진다. 파사드~엔진~집행자 실물 사슬은 기존 selftest 게이트의
  `modal_a11y`·`modal_confirm_serial`·`milestone_h_overlay`가 React 표면의 개폐·포커스·직속
  portal 소유를 한 부팅에서 되읽는다.
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
  `unhandledrejection`·탭 클릭·⚙ 클릭)의 부착/해제와 부팅 시퀀스(호스트 ready
  사건 훅 → `markReady` → init 5 재생: library→editor→job→workbench→DataPicker)를 트리
  자식으로 소유한다. 부착 실물(`attachShell`)은 effect 와 node 하니스가 같은 하나를 쓴다.
  부착이 비동기라 ready 사건은 **선판정 + 이벤트**(adapter `whenReady` 규약)로 놓침 창을
  닫는다. 부착 직후 따라잡기 포트(`catchUp` — 현재 상태 재판독)는 **소비자 0** 이다: 그
  유일한 소비자였던 토바 라벨 동기 둘이 설정 모달의 파생 표시로 옮겨갔다(아래 절). 포트는
  남는다 — 결함류(#74 라벨 어긋남)는 그대로 있고 다음 셸 표시가 그 자리에서 다시 등록한다.
  리스너는 once 가 아니다(재발화 시 init 재주행 — 각 controller의 `loadInitial` 멱등 계약이
  중복 당김을 막는다).
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
- **검증 배치**: 상태기계 순수층은 `tests/js/shell_nav.test.js`, React 트리 결속과 합성 착지는
  `tests/js/react_root.test.js`·`tests/js/bootstrap.test.js`가 진다. 실창 증거는
  `tests/test_web_selftest_gate.py`의 부팅·기본 랜딩·탭 렌더·화면 action 왕복·확인창 계약이
  같은 모듈 부팅 결과를 공유한다.
- **R4-04 착지**: `reactScreenStage` 하나에 `ProductScreens`가 네 화면을 mounted-hidden으로
  유지한다. visibility store 하나가 `.on`·`hidden`·`inert`·`aria-hidden`을 함께 내리고,
  editor/workbench 이탈·rerender 수명주기는 registry의 단일 owner가 fail-closed한다.
  **R5 인계**: 테마·개인화 배선의 정리와 adapter 잔존 0.

#### 셸 설정 모달 — 테마·글자 크기·저장 폴더·서식 폴더 (⚙ 트리거)

토바 우측의 셸 전역 조작은 **⚙ 하나**다. 종전의 순환 토글 둘(`#themeToggle` ◐ ·
`#fontScaleToggle` A)은 걷혔다 — 값이 셋인 축을 순환으로 돌리면 지금 값도 고를 수 있는 값도
누르기 전에는 말해지지 않고, 원하는 값에 닿기까지 화면 전체가 두 번 다시 그려진다.

| 자리 | 좌표 | 소유 |
|---|---|---|
| 트리거 | `#settingsOpen`(`.shell-tool` + `.ti` + `.d`, `aria-haspopup="dialog"`) | `frontend/index.html` · 클릭 배선은 `src/shell/app.ts` |
| 모달 골격 | `#settingsModal`(`.modal.hidden`, `aria-labelledby="settingsTitle"`) — **비어 있어야** 한다 | `frontend/index.html` (portal target) |
| 내용 | `SettingsSheet`/`SettingsSheetView` | `src/screens/settings_sheet.ts`, `PRODUCT_OVERLAY_COMPONENTS` 경유 `bootstrap.js` 등록 |

- **행 하나 = 라벨 + 3값 세그먼트.** 테마(`[data-set-theme]` — 시스템·라이트·다크)와 글자
  크기(`[data-set-font]` — 기본·크게·더 크게)가 각각 한 행이고, 버튼은 `data-value` 로
  값을, `aria-pressed` 로 지금 값을 말한다. 세그먼트에는 `data-busy-lock` 을 걸지 않는다 —
  전역 개인화는 생성 진행과 무관하고, 잠그면 없는 규칙이 생긴다.
- **판정·영속은 이 면에 없다.** 현재값 판독·적용·디스크 쓰기는 `src/shell/preferences.ts`
  (`createTheme`·`createPersonalization` → `bridge.setTheme`/`setFontScale`)가 그대로 진다.
  Python 쪽 host method(`set_theme`·`set_font_scale`)와 부팅 주입(`preferences` 처리기 →
  `Theme.apply`)은 **무변경**이다. 표시는 서비스 사건(`hwpx:themechange`·
  `hwpx:personalizationchange`) 구독에서 **파생**하므로 이 면 밖의 변경(부팅 주입·프로브의
  직접 `Theme.set`)도 같은 값에 도착한다 — 그래서 셸의 `catchUp` 이 필요 없어졌다.
- **개폐·초점**: ⚙ 클릭 → `Modal.open("settingsModal", { returnFocus: 트리거 })`,
  `#settingsClose` → `Modal.close`. 닫으면 초점이 ⚙ 로 돌아온다(Escape·배경도 같은 경로).
- **저장 폴더 행**(세 번째 행 · `.settings-row.settings-row-folder`)은 앞 둘과 **다른 종류의
  값**이다: 테마·글자 크기는 셸 서비스의 값이지만 저장 폴더는 **Python 이 도출한 제품 값**이라
  경로·출처·사유가 스냅샷으로 온다. 그래서 이 행만 job 컨트롤러를 구조적 포트
  (`SettingsOutputFolderPort` — `subscribe`/`getRun`/`pickOutputFolder`/`client`/`notify`)로
  받아 최상위 `output_folder` 존을 구독하고, 지역 상태를 만들지 않는다.
  좌표는 경로 칸 `#settingsOutDir`(읽기 전용) · 「찾아보기…」 `#settingsPickFolder` ·
  출처 `#settingsOutDirSource` · 사유 `#settingsOutDirNotice` · 잠금 사유
  `#settingsPickFolderReason`, 그리고 경로 어포던스(`PathActions` — 폴더에서 보기·경로 복사)다.
  **생성 중에는 「찾아보기…」가 비활성이고 사유를 병기한다**(조용히 막지 않는다) — 이번 실행이
  겨눈 폴더가 도중에 갈리면 결과가 어디로 갔는지 말할 수 없기 때문이고, 그래서 이 행만
  세그먼트와 달리 실행 상태를 본다. 왕복 자체(`pick_output_folder` 직접 브리지 + 오류 재진술)는
  `JobRunController.pickOutputFolder` 가 그대로 지고 이 면은 부르기만 한다.
  기안 대상 글꼴(`#wbTargetFont`)은 작업대 소유로 남고 여기로 오지 않는다.
- **서식 폴더 행**(네 번째 행 · 같은 `.settings-row.settings-row-folder` 형상, U6-A #975)은
  저장 폴더 행의 **복제**다: 경로 칸 `#settingsTplDir`(읽기 전용) · 「찾아보기…」
  `#settingsPickTplFolder` · 출처 `#settingsTplDirSource` · 사유 `#settingsTplDirNotice` ·
  잠금 사유 `#settingsPickTplFolderReason` + 경로 어포던스(`PathActions`, reveal·copy).
  생성 중 잠금·사유 병기도 **같은 술어**(같은 실행 상태를 읽는다 — 두 번째 판정을 세우지
  않는다). 다른 것은 값의 채널과 도출 하나뿐이다: 값은 `tpl` 스냅샷 최상위 `templates_root`
  존이고(구조적 포트 `SettingsTemplatesRootPort` — `subscribe`/`getSnapshot`/
  `pickTemplatesRoot`/`refreshCurrentScreen`), 설정한 폴더가 없어도 **기본값으로 내려가지
  않는다**(아래 절). `tpl` 은 편집기 동사에서만 밀리는 채널이라 첫 스냅샷을 따로 당겨야 하는데,
  그 당김은 **셸 부팅 시퀀스**(`bootstrap.js` 의 `initSequence`)가 진다 — 이 오버레이는 부팅
  상주 마운트라 컴포넌트 effect 에서 호스트를 부르면 그 호출이 `pywebviewready` **앞**에 서고,
  실측에서 그 순서가 WebView2 창을 아예 못 뜨게 했다(`loaded` 미발화 ·
  `Main window failed to start`). 그 순서 안전은 지금 **구조가 진다**: `runtime.loadInitial`
  이 `client.whenReady()` 뒤에 당김을 줄 세우므로 어느 호출자든 안전하고, `initSequence` 의
  자리는 「부팅에 당기는 채널 전수」를 한 표로 읽히게 하는 몫만 남는다. 재지정 성사 뒤에는
  지금 화면을 한 번 다시 당긴다(목록의 정본은 각 화면 스냅샷이다).
- **두 폴더 행은 팩토리 하나**(`FolderRow`)가 그린다 — 라벨·읽기 전용 경로·「찾아보기…」·
  출처·사유·경로 어포던스의 형상이 같고 다른 것은 좌표와 값의 채널뿐이다. DOM `id` 는
  계약 좌표라 **호출자가 명시로 싣는다**(파생 조립 금지 — 프로브·게이트·live 대본이 그
  문자열을 그대로 문다). 서식 폴더 포트는 `client`·`notify` 를 **직접** 들어 경로 어포던스가
  남의 컨트롤러에 묶이지 않는다.
- **검증**: 렌더·발신 계약은 `tests/js/settings_sheet.test.js`(행 넷·두 폴더 행의 경로·출처·
  사유·잠금 사유·발신 목적지), 실 WebView2 왕복(⚙ 클릭 →
  열림 → 세그먼트 클릭 → `documentElement[data-theme]` 반영 → 원래 값 복원 → 닫힘 → 초점
  복귀)은 selftest 프로브 `shell_settings`(클러스터 B)와
  `tests/test_web_selftest_gate.py::test_shell_settings_modal_round_trips_theme_and_returns_focus`
  가 진다. 그 프로브는 테마를 잠시 바꾸므로 콜드부트 테마를 읽는 `theme_persist` **뒤**에
  서야 한다(합성 `legacySite` 9991 이 그 순서를 못박는다).

### 장기 렌더 검증 배치

R3/R4 이관 패리티 원장은 완료와 함께 퇴역했다. 장기 계약은 실제 위험 경계가 소유한다:
React 요소·ARIA는 `tests/js/overlay_host.test.js`, 셸 상태는 `tests/js/shell_nav.test.js`,
개인화·기하는 `tests/js/n08_persistence_geometry.test.js`와
`tests/test_web_press_geometry.py`, 강제 색상은 `tests/test_personalization_contract.py`, 최종
WebView2 렌더·초점·스크롤은 `tests/test_web_selftest_gate.py`가 확인한다. 테스트 경로를 다시
파싱하는 별도 메타테스트는 두지 않는다.

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

### backend-only semantic authority (SG-03 · #735)

의미 판정은 **backend/application 단일 권위**다. selection canonical bytes·execution basis
digest·Plan semantic digest·record validity·resolved delivery path·semantic currentness·runtime
admission·materialization readiness·Workbench blocker/Primary Action 은 전부 Python 이 판정한다.
frontend 는 **opaque ref/token 을 전달**하고 **projection/observation DTO 를 렌더**하며 focus/view
state 를 쥐고 Product command 를 부를 뿐, Plan/currentness/record/delivery 를 **재계산하지 않는다**.
TypeScript canonical code(`frontend/src/domain/canonical_execution_encoding.ts`·`slot_selection.ts`)는
wire codec parity test·golden vector·contract fixture 범위로만 남고 production React path 는 이를
import 하지 않는다 — 표시 어휘는 backend-파생 `frontend/src/contract/contract.gen.ts` 를 소비한다.
정본은 `docs/CONTROL_PLANE_SCOPE.md`, 게이트는 `tests/repo_contract/test_control_surface_reduction.py`
(C3·C4)와 `tests/repo_contract/test_bridge_contract.py`(C5)다.

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
실제로 난 회귀이고(#379 §5), 현재는 `tests/js/state_store.test.js`의 포트 계약과
`tests/js/bootstrap.test.js`의 합성·음성 대조가 지고 있다.

사용자 확인(파괴 전이의
`needs_confirm` 왕복)은 pywebview 네이티브 다이얼로그가 아니라 **JavaScript `Modal.confirm`**
(`frontend/src/overlay/modal.js`)이 구현한다 — 판정·수치는 Python이 내리고 문안·확인 UI는 웹이 소유한다.
창 수명 같은 나머지 네이티브 동작도 링2 브리지가 소유한다. 링0·링1이 WebView2 또는 DOM을
알게 해서는 안 된다.

## 현재 라우팅과 소유권

상단 토바 탭은 `job` 「문서 만들기」와 `library` 「문서 작업」 두 개이고, 최상위 제품 화면은
`library`, `job`, `editor`, `workbench` 네 개다. 「기안」(`draft`)은 F6 PR-B 에서
사망했다(승계처 = 편집기 좌 열의 TXT 행 + 검토·복사 작업대 — 지도 §10.15.15 점검표).
좌 레일과 그 접기는 F2 PR-B 에서 사망했다.
`frontend/src/shell/app.ts`의 앱 셸이 내는 `Nav.go`가 전환을 요청한다(주입으로 전달되는
구성 산물이다 — 전역 `window.Nav`는 N-10에서 사라졌다. R3-02 부터 판정은 셸 상태기계
`frontend/src/shell/nav.ts`, 집행은 `product_screen_executor.ts`다 — 위 「앱 셸·navigation
수명주기」). 정적 HTML에는 `#reactScreenStage` 하나만 있고 `ProductScreens`가 네 wrapper를
같은 React root의 portal로 만들며, 숨은 화면도 unmount하지 않는다.
`editor`(재작성 F7)와 `workbench`(재작성 F6)는
**탭 없는 몰입 표면**이다: 상단 2탭을 덮으므로 nav 버튼이 없고, 나가는 모든 이동이 자기
이탈 절차(`leaveTo` — 편집기는 자동 버리기 + 착지 수명주기, 작업대는 종전 가드)를
지난다(`{force:true}` 는 그 절차를 마친 재호출). 위임은 화면마다의 특례가 아니라
상태기계의 **몰입 표면 목록**(`IMMERSIVE_SURFACES`)이 진다 — 특례를 표면마다 늘리면 위임의
완전성이 표면 수에 비례하고, 그것이 이 두 표면을 화면으로 올린 바로 그 이유다. 새 몰입
표면은 그 목록에 한 줄이면 되고 셸 은닉(`body.<cls>-open` — 집행은 adapter)과 이탈 위임이
함께 따라온다.

| 라우트/표면 | DOM·JavaScript 소유자 | Python 컨트롤러 | 링1 ViewModel·상태 소유자 |
|---|---|---|---|
| `library` 문서 작업(전역 라이브러리) | `#scr-library`, `src/screens/library.ts` | `LibraryController` | `HomeViewModel`(모듈명은 유지 — 지도 §10.8 판정 A) |
| `job` 문서 만들기(데이터·실행) | `#scr-job`, `src/screens/product_screens.ts`(+`job_read.ts`·`job_run.ts`·`job_result.ts`) | `JobController` | `RunViewModel`, `SelectionModel`, 필터 상태, 후보 판정(`work_candidates`) |
| `editor` 문서 작업 편집기(몰입) | `#scr-editor`, `src/screens/editor.ts`(+`editor_state.ts`·`editor_entry.ts`·`group_move_dialog.ts`) | `EditorController` | `MappingModel`, `EditSession`·`EditContext`, 저장 판정 (템플릿 라이브러리 VM 은 U6-E 에서 `tpl` 채널 단독 소유 — 편집기는 관문 `is_live_path` 만 받는다) |
| `workbench` TXT 검토·복사 작업대(몰입) | `#scr-workbench`, `src/screens/workbench.ts`(+`workbench_state.ts`·`segment_view.ts`) | `WorkbenchController` | `MappingModel`, `SelectionModel`, `TxtQueueModel`, `EditSession` |
| 데이터 선택 다이얼로그(화면 아님) | `#dataPickerModal`, `src/screens/data_picker.ts` | `PoolController` + 호스트 화면 | `DatasetPoolViewModel` |
| 시트 선택 확정 게이트(화면 아님) | `#sheetModal`, `src/screens/sheet_picker.ts` | 호스트 화면(`job`·`editor`) | — (확정 전 로드 금지는 표면 계약) |
| 셸 설정 모달(화면 아님 · 셸 전역) | `#settingsModal`, `src/screens/settings_sheet.ts` | — (host method `set_theme`·`set_font_scale` 직접 브리지) | `src/shell/preferences.ts`(Theme·Personalization 서비스) |
| 항목 상세 시트(화면 아님 · U6-E #979) | `#tplDetailModal`, `src/screens/editor.ts`(`TplDetailSheet`) | `TemplateController`(`detail` 존) | `TemplateDetail`·`SlotView`(`gui/template_manager_state.py`) |
| 데이터 상세 시트(화면 아님 · 고르기 열 공용 계약) | `#poolDetailModal`, `src/screens/pool_detail.ts`(`PoolDetailSheet`) | `PoolController`(`detail` 존) | `DatasetDetail`(`application/dataset_pool.py`) |

두 상세 시트의 **골격은 하나다**(`src/screens/detail_sheet.ts` `DetailSheetFrame`): 머리
(이름+배지) · 경로 줄과 그 문(`PathActions`) · 오류 상자 · 진단 · 몸통 · 성과/실패 두 줄 ·
관리 동사 줄 · 닫기. 좌표는 접두어만 다르다 — `${idPrefix}` + `Title`·`Path`·`Error`·`Msg`·
`Result`·`Verbs`·`Close`·`Empty`(`tplDetail`·`poolDetail`). CSS 도 한 규칙(`.detail-sheet` —
종전 `.tpl-detail` 의 승계처)이다. 갈리는 것은 몸통 하나다: 저쪽이 필드 표·구간 항목,
이쪽이 정체 줄(`#poolDetailFacts`)·열 표 머리(`#poolDetailColumnSummary`)·열 표
(`#poolDetailColumns`)다.

화면을 추가·삭제·이름 변경할 때는 `PRODUCT_SCREEN_IDS`, ProductScreens wrapper, visibility
store, Python 컨트롤러 `name`, `WebFrontend.controllers`, action registry를 한 계약 변경으로
갱신한다. 나가는 길을 위임하는 화면(편집기)은 `Nav.go` 위임까지 한 묶음이다 — 이탈 절차를
표면마다 따로 걸면 완전성이 표면 수에 비례한다.

#### 문서 작업 편집기 = 몰입 표면 + section patch 거래 (F7 PR-A — 지도 §10.13)

- **탭은 계약 §5.1 의 section 문자열**(`template`·`binding`·`filename`, 「시험」은 F8)이고
  **집합은 매체 파생**이다(TXT 는 파일 이름 탭 없음 — §3.2). 정수 단계 어휘는 사망했다:
  patch 의 키와 탭이 같은 문자열이라야 같은 상태를 두 표면이 다르게 부르지 않는다.
  **id 는 계약이고 라벨은 문안이다**: U6-B(#976)가 라벨만 갈았다 — `template`→「고르기」,
  `binding`→「연결 확인」, `filename` 은 그대로. 그 문안은 두 자리에 산다(표면
  `editor.ts` 의 `SECTION_TITLES`, 되돌림 notice 의 `screen_editor.SECTION_LABELS`)이고
  **글자가 같아야 한다** — 갈리면 화면이 부르는 이름과 알림이 지목하는 이름이 어긋난다.

- **1단계 「고르기」는 두 풀과 한 카드다**(U6-B #976 · U6 §2.2 · 동결 시안 장면 1). 존
  `#editorPairZone` 이 좌 템플릿 풀(`#editorTplPool`) · 중앙 연결 카드(`#editorLinkCard`) ·
  우 데이터 풀(`#editorDataPool`)을 든다. 소유는 이렇게 갈린다:
  - **좌 열의 정본은 `tpl` 채널 스냅샷**이다(아래 「tpl→editor」 절). 편집기 스냅샷이 목록을
    한 번 더 성형하던 `library` 존은 **퇴역**했다(구 `_library_snapshot`) — 같은 목록을 두
    컨트롤러가 그리면 tpl 의 변환·검토가 두 경로로 도착한다. 편집기가 내는 것은 선택 키
    (`pairing.template_key`) 하나이고 항목은 그것으로 `aria-pressed` 를 그린다. 결과 줄(`.run-result`)과
    항목 상세(`detail` 존)도 같은 이유로 `tpl` 스냅샷을 직접 읽는다(중계 seam
    `library_result`·`library_slots` 폐기). **결과 줄의 자리는 좌 열 바닥**이다(U6-E #979) —
    관리 동사가 전부 그 열에서 나가므로 성과도 같은 열에서 읽힌다.
  - **우 열도 공용 `PoolColumn` 이다**(고르기 열 공용 계약). 우 열의 이웃은 다이얼로그가 아니라
    **좌 열**이라, 두 열이 같은 컴포넌트의 두 인스턴스로 서고 `pool.column` 을 그린다
    (`#editorDataPool` 뿌리 · `#editorDataList` 목록 · `.pitem[data-side="dat"]` 행).
    갈리는 것은 바닥 동사 줄 하나다 — `#editorPoolBrowse`(파일 찾아보기…) ·
    `#editorPoolPclm`(계약 목록(.db) 등록… — 스냅샷에 `pclm` 이 없으면 숨기지 않고 비활성 +
    사유) · `#editorPoolPin`(이 데이터 고정…). **우 열도 「새로 읽기」(`pool/refresh`)와 행
    ⋯ 를 가진다**: ⋯ 는 링1 이 낸 `actions`(다시 연결·보관/활성화·삭제) 다음에 「폴더에서
    보기」를 세우고, 그 동사들은 좌 열 ⋯ 와 **같은 팝오버**(`#tplRowMenu`)를 쓴다 — 열림
    상태가 `(side, media, key)` 로 갈리는 이유는 두 열의 키 공간이 다르기 때문이다.
    표면이 「엑셀이면 다시 연결을 하나 더」 같은 판정을 덧붙이던 자리는 함께 사라졌다.
    **⋯ 의 마지막은 「자세히…」다**(좌 열과 같은 순서: 링1 동사 · 경로
    문 · 상세). 목록을 짓는 함수는 두 호스트 공용 하나이고(`pool_verbs.dataRowMenuItems`),
    그 문이 여는 것이 `#poolDetailModal` 이다. **세션 행에는 그 항목이 서지 않는다** —
    풀에 없는 결속이라 검토할 항목 자체가 없다(음성 계약).
  - **파일로 연 데이터는 목록 맨 위의 행 하나다**(같은 행 계약, 키 `session`). 정본은 편집기
    스냅샷 `pairing.data_row` 이고(`screen_editor._pairing_data_row`), 부제(「시트: … · 헤더
    n행 · m행」 — 계약 목록의 뷰 이름은 `PCLM_VIEW_TITLES` 로 제목화)도 Python 이 짓는다.
    종전 「현재 데이터」 카드의 승계처이고, 한 열에 두 문법을 세우지 않으려는 것이 이유다.
    **풀 등록 결속에는 서지 않는다**(`data_key` 와 배타 — 같은 결속이 두 행으로 서지 않는다).
    그 행은 다시 눌러도 **무동작**이고(이미 이 작업의 데이터다 — 거절도 발신도 없다), 끌어
    놓기의 상대가 되면 템플릿 쪽만 바뀐다. 「이 데이터 고정…」은 **그 행이 있을 때만** 바닥
    동사 줄에 선다(풀에서 고른 데이터는 이미 고정돼 있다).
  - **다이얼로그도 같은 `PoolColumn` 이다**(인스턴스 셋). 갈리는 것은 넷이다 —
    1차 동사가 **행 클릭 하나**이고 그것이 발행하는 액션(`editor/use_pool_data` ↔
    `job/load_pool`), DOM 좌표(`editorDataPool`/`editorDataList` ↔
    `dataPickerPool`/`dataPickerPinned`), 바닥 동사 줄의 id 접두, 그리고 다이얼로그에는 짝
    지을 상대 열이 없다는 것(호스트 `drop` 없음 = 끌기 props 0). `load_pool` 을 `editor`
    채널에 넣지 않는다: 화면별 허용 목록이 곧 경계의
    정의라 같은 이름이 두 화면에 걸리면 「누가 무엇을 받는가」가 이름 하나로는 안 읽힌다.
    관리 동사(보관·활성화·삭제·다시 연결·중복 정리)는 두 호스트가 **같은 `pool` 채널**로
    보내고, 연타 차단(in-flight 표지)도 그 공용 몸통 하나가 진다 — 호스트별 재구현이 있으면
    한쪽만 두 벌 확인 모달을 세운다. 편집기 호스트는 그 위에 발신을 편집 체인(`EDIT_CHAIN`)
    으로 태워 이 화면의 다른 왕복과 순서를 나눠 갖는다.
  - **「고를 수 있는가」와 그 사유는 Python 행 필드**다(`selectable`·`select_block_reason`):
    좌는 `screen_template`(링1 `TemplateRow.select_block_reason` — 변환 전 RAW·PARTIAL 은
    비활성 + 사유), 우는 링1 `DatasetPoolRow.select_block_reason`(보관·끊김·나라). **hwpx·txt 두
    매체가 같은 링1 성형 함수를 지난다**(`TemplateRow.from_text` — `detail_line`·
    `select_block_reason` 공유): 갈리는 축은 변환 축의 유무 하나이고 그것이 `media` 다.
    링2 가 매체별로 문장을 다시 지으면 링1 문안을 고쳐도 TXT 행만 옛말을 계속 한다. 표면이 `state`·
    `status`·`missing` 으로 문장을 다시 지으면 같은 상태가 두 어휘를 갖는다 — 그래서 링2 의
    재판정(구 `pool_option_block`·웹 `usableReason`)은 사슬째 걷혔고, 못 고르는 항목의
    클릭·드롭은 조용히 삼켜지지 않고 그 사유를 인라인으로 재진술한다.
  - **두 채널이 공용 `column` 존을 함께 낸다** — 좌·우가 한 컴포넌트의 두 인스턴스가 되는
    자리다. 행·존의 키 집합은 `webapp/pool_column.py` 하나가 소유하고
    (`POOL_ROW_KEYS` · `{rows, notices, empty_hint, count_label, result}`), 판정은 그대로
    링1 이 낸다(`TemplateRow.select_block_reason` / `DatasetPoolRow.select_block_reason` —
    `selectable` 은 `reason` 의 파생이지 두 번째 판정이 아니다). 좌 열은 hwpx 다음 txt 를
    **한 목록**으로 싣고, 우 열은 손상 격리(danger)·중복 등록(warn)을 존 통지로 싣는다 —
    종전에 웹이 리터럴로 짓던 그 문장들이고, 중복 통지는 그 처분(`resolve_duplicate` +
    `payload.keep`)을 같은 자리에 함께 세운다. 개수 라벨의 분류사는 두 열 다 **항목의
    것**(`n개`)이다 — `건` 은 이 제품에서 레코드(데이터 행)의 분류사라 열 머리에서 쓰면 같은
    자리의 두 인스턴스가 다른 말을 한다. 결과 줄(`column.result`)도 이 존 안이다: 목록과
    성과가 한 열의 두 부분이라 갈릴 자리를 만들지 않는다.
    두 열의 「지금 선 행」은 `pairing.template_key`·`pairing.data_key` 가 이름한다(둘 다 열
    행의 `key` 와 같은 축 — 좌는 루트 상대경로, 우는 풀 슬롯 키이고 파일 결속이면 빈 값 +
    `pairing.data_row` 의 `session` 행).
    **좁은 열 계약에 프리필 축을 얹지 않는다**: 「다시 연결」이 요구하는 `path`·`sheet`·
    `note` 는 `pool/review` 가 세우는 상세 투영(`detail`)이 든다 — 두 호스트가 같은 왕복·
    같은 키 이름을 쓰고, 왕복이 낸 상세의 `key` 가 겨눈 키와 다르면 폼을 열지 않고 거절한다
    (그 사이 push 가 끼면 남의 등록을 덮어쓸 수 있다).
  - **퇴역 목록 — 무엇이 무엇을 승계했나**(#993). 같은 목록을 두 모양으로 들던 사슬은 전부
    걷혔다. 소비자 0 인 payload 를 남겨 두면 두 벌이 갈린 채 늙는다(U5 선례 —
    `UX_FEEDBACK_U6` §2.6):
    - `pool_list.ts` 의 `PoolSections`(카드 + 행 안 버튼 다섯) → 공용 `PoolColumn` 인스턴스
      셋. 관리 동사 한 벌은 `pool_verbs.ts` 가 계속 공유한다.
    - `.tplcard` 묶음(구 `tpl` 화면의 카드 문법) → `.pitem` 행 하나.
    - `tpl` 스냅샷의 매체 밴드 `hwpx`/`txt`(각 `sections`/`flat`/`count`/`dir`/`empty_hint`)
      → `tpl.column`(매체는 구획이 아니라 행 표지 `icon`) + 최상위 `templates_root`.
      동결된 그룹 모델(`TemplateGroupModel`)은 **영속과 유령 지정 정리만** 남고 투영은 없다.
    - `tpl`·`pool` 최상위 `result` → 각 채널의 `column.result`(상세 시트도 그것을 읽는다).
    - `pool` 스냅샷의 `rows`·`count`·`empty`·`corrupted`·`duplicates` → `pool.column` 의
      `rows`·`count_label`·`empty_hint`·`notices`(danger/warn) + 프리필은 `pool.detail`.
    - `pool.pclm.titles`(뷰 전수 제목표) → 없음. 이미 선 마운트의 제목화는 Python 이 세션 행
      부제를 지을 때 링0 `pclm_views.sheet_title` 하나로 끝난다 — 표를 웹에 내리면 같은
      제목화가 두 층에서 갈린다. `pclm` 이 남기는 것은 `default_db`·`views` 둘이다.
  - **두 열은 공용 `PoolColumn` 이 그린다**(`frontend/src/screens/pool_column.ts` — 고르기 열
    공용 계약): 열 하나의 문법(`.poolcol` 뿌리 · `.pool-head` · `.pool-list` · `.pool-acts` ·
    바닥 `.run-result`)과 행 계약(`.pitem-wrap` > `button.pitem[data-act="pick"]` + 형제
    `button.job-more[data-act="lib-more"]`)이 여기 **한 벌**이고, 그것이 읽는 것은 `tpl.column`
    (좌) 또는 `pool.column`+세션 행(우) 하나다. 행의 상태도 하나다 — 고를 수 있음
    (`aria-pressed="false"`) / 고름(`aria-pressed="true"`, `pairing.template_key`·
    `pairing.data_key`(파일 결속이면 `session`)가 이름한다) / 못 고름(`aria-disabled="true"`
    + 부제 자리의 사유). **못 고르는 행은 `disabled` 가 아니다**: 눌리지 않으면 사유를 말할
    자리가 없어 조용한 무시가 되므로, 클릭도 드롭 거절도 호스트의 같은 한 자리(`choose`)로
    가서 이름과 Python 사유로 재진술된다. 사전 고지(`warns` — #154)는 사유와 **다른 줄**로
    선다(고를 수 있는 행도 미리 알릴 것이 있고, 한 축으로 접으면 한쪽이 사라진다). 행 앞머리
    글리프는 `poolGlyph()` 한 어휘이고 상세 패널의 연결 카드(`library.ts` `pairGlyph`)가 같은
    것을 쓴다 — 같은 것을 가리키는 그림이 두 자리에서 갈리지 않는다. **못 고르는 행은 세 자리
    다 눌리되 거절을 말한다** — 그 대칭이 이 컴포넌트를 나눠 쓰는 이유이고, 거절의 문형도
    한 벌이다(`pool_verbs.poolRefusalText`·`POOL_GONE_FROM_LIST`). 「데이터 선택」
    다이얼로그도 합류해 인스턴스는 셋이다(CSS 뿌리가 `.pairzone` 이 아니라
    `.poolcol` 인 이유 — 존 배치만 `.pairzone` 이 계속 소유하고, 다이얼로그는 목록 높이만
    `.data-picker .pool-list` 로 제 사정에 맞춘다). 행의 정체 좌표(`data-key`)는 끌기 결속과
    **무관하게** 행 자신이 든다 — 끌기가 없는 호스트의 행도 자기 키를 말해야 한다.
  - **고르는 제스처는 좌·우가 한 규칙이다**(리뷰 1·2·5·10). 클릭도 끌어 놓기도 컨트롤러의
    같은 한 자리(`chooseTemplate`/`chooseData`)를 지나고, 그 자리가 셋을 함께 진다:
    ① **이미 고른 것을 다시 고르면 무동작**이다 — 통과시키면 `new_job_session` 이 이름·
    매핑·단계를 통째로 끊는다(누른 사람은 「이미 고른 것을 다시 골랐을」 뿐이다). 판정은
    표면과 `_do_use_library_template` **둘 다**에 선다(표면만 막으면 프로브·다른 호출자가
    뚫는다). ② **교체는 데이터 교체와 같은 확인 왕복**을 지난다 — 수치는 Python 이 지금
    판정하고(`mapping_reset_stakes`) 확인 UI 만 웹이 짓는다. 같은 파괴에 두 규칙을 두지
    않는다. ③ **목록에서 사라진 키도 사유를 낸다** — 드롭 도중 push 가 끼면 손에 든 키가
    지금 목록에 없을 수 있고, 그때 말없이 반환하면 끌어 놓기의 반쪽만 성사한 채 화면이
    아무 말도 하지 않는다. 끌어 놓기는 두 반쪽의 거절을 **한 문장으로** 말한다(알림 채널이
    1슬롯이라 각자 쓰면 앞 문장이 조용히 사라진다).
  - **표시명은 목록과 같은 어휘다**(U6-D #978): 편집기 스냅샷의 `template_name`·
    `pairing.template_name` 은 `domain/template_status.library_display_name`(루트 상대·확장자
    없음)이고 `data_name`·`pairing.data_name` 은 이 결속이 **풀에 등록돼 있으면 등록명**,
    아니면 확장자 없는 basename 이다. 등록명은 **세션 표지가 아니라 풀 조회**로 온다(정체성은
    등록 게이트가 쓰는 `domain.dataset_reference.reference_identity` 하나) — 「방금 풀에서
    골랐다」를 세션에 기억하면 저장하고 다시 연 세션이 같은 데이터를 다른 이름으로 부른다.
    작성 출처 기록(`provenance.dataset`)도 같은 이름을 쓴다. 종전에는 편집기가 basename+확장자를 실어 나르고 좌 열은 표시명을 그려
    같은 파일이 두 어휘로 불렸다 — 머리 부제가 목록과 다른 말을 하던 자리다. 루트는 `tpl`
    화면과 **같은 `TemplateRoot` 홀더**로 온다(주입 `template_root`).
  - **연결 카드의 수치는 출처를 명시로 든다**(`pairing.basis`). 1단계는 매핑 모델을 **만들지
    않는다**: 생성은 2단계 진입의 `_ensure_model` 하나가 지고, 카드가 미리 만들면 고르기를
    바꿔 보는 것만으로 「전원 미확정 재생성」 전이가 돌아 확정이 조용히 무너진다. 그래서
    모델이 있고 그 키가 지금 선택과 같으면 모델의 실제 수치(`basis="model"`, 라벨 「확인」),
    아니면 순수 함수 `gui.mapping_state.pairing_preview` 를 읽기 전용으로 돌린 미리보기
    (`basis="preview"`, 라벨 「자동 연결」)다. 2단계가 실제로 세울 제안과 **같은 함수**라
    수치가 갈리지 않는다. `suggest_mappings` 는 필드×열 SequenceMatcher 라 **고르기 단계
    에서만** 세고 같은 정체 키에서는 memoize 한다 — 세지 않은 자리는 `basis=""` 로 그
    사실을 말하고 표면은 그때 수치 줄을 세우지 않는다(0 을 사실처럼 말하지 않는다).
  - **`ready` 는 「짝이 실제로 섰는가」다** — 경로 둘 + **필드 1개 이상**. 경로만 보면 채울
    필드가 0 인 템플릿(hwpx RAW · 토큰 0 인 TXT)에서도 참이 되어 「필드 0개 · 자동 연결 0」
    카드가 비활성 CTA 위에 선다(화면이 「짝이 섰다」고 말하면서 다음으로 못 가는 자리).
    그 사유는 링1 문안 하나(`RAW_BLOCK_MESSAGE`/`TXT_RAW_BLOCK`)가 낸다.
  - **초안의 전진 게이트가 데이터까지 요구한다**(`can_advance("template")` = 템플릿 준비 +
    데이터 마운트). 이 단계가 묻는 질문이 하나이므로 반쪽만 고르고 지나가면 그 단계가 두
    질문을 가진 것이 되고, 데이터 관문이 2단계 머리에서 걷힌 뒤로는 고칠 표면이 없는 화면에
    착지한다. 사유는 Python 이 낸다(`pairing.advance_block_reason` — 좌·우 중 막힌 한쪽만
    지목한다). 저장본의 자유 탭 이동은 불변이고, 저장 게이트의
    `blocked_field="data"` 는 이제 **1단계 우 열**을 가리킨다.
  - **끌어 놓기는 가속기이고 클릭이 1차 경로다**(U6 §2.7). 항목을 상대 열의 고를 수 있는
    항목 위에 놓으면 **클릭이 발행하는 같은 액션 두 번**이 나간다(`use_library_template` →
    `use_pool_data`, 템플릿 먼저 — 뒤집으면 데이터 마운트가 모델 재조립을 태운 뒤 템플릿
    교체가 그것을 또 무너뜨린다). 새 액션은 0 이고, `dataTransfer` 형식은
    `text/plain` = `"<side>:<key>"` 하나다. 같은 열끼리·비활성 항목은 받지 않고, 강조는
    클래스 하나(`.drop-target`)에 애니메이션이 없어 `prefers-reduced-motion` 과 무관하다.
  - **고르기 존 아래에 남은 것은 게이트 한 줄뿐이다**(U6-E #979). 선택 chip + 경로 동사 ·
    `Provenance` · 스키마 표 · `#tplSlots` · `#editorSlotSummary` 는 전부 **항목 상세 시트**로
    갔다(아래 「항목 상세 시트」 절). 남은 게이트 존 `#editorTplGate` 는 **세션 판정**이라
    1단계에 산다 — `raw_block` · `gate_error` · `gate{message,unmet,acked}` + `ack-gate` 는
    종전 그대로이고, 스키마 표가 시트로 가면서 이 자리가 말하는 수치는 `field_count` 하나로
    좁아졌다. 존이 지는 것 넷:
    - **머리는 상태와 무관하게 선다**(#989 리뷰 8): 표시명 + `PathActions(reveal)` +
      「자세히…」. 「파일을 고치세요」라고 말하는 바로 그 상태(RAW·판독 실패)에서 고치러 갈
      길이 그 문장 옆에 없으면 안 된다. 아래 몸통만 상태로 갈린다.
    - **시트 문의 가부는 Python 이 낸다**(`session_detail{available,reason}` · 리뷰 5):
      시트는 `tpl` 이 아는 항목만 여는데(그 왕복이 경로 관문을 지난다) 저장본이 든 절대경로는
      루트 재지정·폴더 이동 뒤에도 살아 있을 수 있다. 열리지 않는 문은 **비활성 + 사유**이고
      (`#editorTplDetailBlock`) 판정은 세션 템플릿 경로 하나로 memo 된다 — 관문 질의가 서식
      폴더 스캔을 물 수 있어 스냅샷마다 지불할 것이 아니다. 관문 미배선도 「닫힘 + 사유」다.
    - **작성 출처 드리프트 경고가 여기 산다**(`schema_drift` · 리뷰 6 · #53-C 승계): 저장이
      찍은 필드 지문(`provenance.template_fields`)과 **지금 연 파일**의 필드가 갈리면 warn 한
      줄(`#editorSchemaDrift`). 풀 항목이 아니라 **세션**의 사실이라 시트가 아니라 이 자리다.
      판정·문안 모두 Python(`_provenance_drift`)이고 웹은 필드 목록을 다시 대조하지 않는다.
    - `data-act="session-detail"` 은 행 ⋮ 의 「자세히…」와 **같은 한 문**이다(`openDetail`).
- **2단계 「연결 확인」은 4열 표 하나다**(U6-C #977 · U6 §2.2 · 동결 시안 장면 2). 열은
  템플릿 필드 · 데이터 열 · 표시형 · 미리보기이고, 종전 7열의 나머지 셋은 흡수됐다:
  「확정」 체크는 데이터 열 칸의 **상태 배지 버튼**(`data-act="row-confirm"`)으로,
  「타입/고정값」은 그 칸 select 의 특수 항목군으로, 「상태」는 배지 문안으로.
  - **행 상태는 닫힌 4태이고 그 라벨은 링1 이 소유한다**: `suggested`(자동 제안) ·
    `edited`(사람이 손댐, 미확인) · `confirmed`(확인) · `needs_source`(채울 것 없음).
    판정은 `RowState.status()` 하나이고 문안은 `gui.mapping_state.ROW_STATUS_LABEL` 하나다
    — 종전에는 링2 가 4태를 짓고 웹이 그 위에서 「제안」을 한 번 더 유추했다(같은 상태를
    세 층이 판정했다). 데이터 미연결은 별도 상태가 **아니다**: 행이 요구하는 것은 같고
    (`needs_source`), 고를 열이 왜 없는지는 표 머리·1단계가 말한다.
  - **특수 항목은 열 이름 공간에 얹지 않는다.** `data_column_options` 의 항목은 실 열
    (`col:<이름>`, `kind="column"`)과 특수 셋(`sp:const`·`sp:today`·`sp:blank`)으로 갈리고,
    웹은 값을 파싱하지 않고 `kind` 로 발행 액션을 가른다 — 열은 `set_source`, 고정값·오늘
    날짜는 `set_type`, 비워 둠은 `set_blank`. `set_source` 에 센티넬이 가지 않는 것이 계약
    이다(리뷰 R5: 같은 이름의 실 열이 있으면 그 열을 영영 못 겨눈다). 링1 도 그 짝을 지킨다:
    열을 고르면 `const`/`today` 가 추정 기본형으로 풀리고, 특수 유형을 고르면 소스가 풀린다
    (표시와 출력이 갈리지 않게).
  - **유형 축은 표시형 select 가 든다**(U6-C 리뷰 1). 종전 「타입」 열이 데이터 열 칸으로
    접히며 남긴 것은 `const`/`today` 둘뿐이었는데, `infer_type` 은 이름 키워드 휴리스틱이라
    「계약일」이 text 로 추정되면 그 행은 날짜 서식으로 갈 길을 **영영** 잃는다. 그래서 표시형
    select 가 유형별 `optgroup`(텍스트·날짜·금액)으로 `format_presets` 전 유형을 나열하고,
    항목 값은 `type:fmt` 한 쌍이다. 선택은 **한 액션**(`set_display {index, type, fmt}`)이다 —
    유형이 바뀌면 표시형 키가 무효라 둘은 애초에 한 전이였고, 나눠 두면 그 사이에 사람이 고른
    표시형이 사라진 상태가 실재한다(구 `set_type`·`set_fmt` 액션은 사슬째 퇴역). 그룹 집합은
    값의 출처가 가른다: 「오늘 날짜」 행은 date 어휘 하나(U4 §2.14 판정 1), 「고정값」 행은
    프리셋이 없어 빈 목록이고 표면이 비활성 「—」로 접는다. 항목이 `type`·`fmt` 를 따로 들어
    웹은 값 문자열을 파싱하지 않는다(데이터 열 항목과 같은 규율).
  - **표 안의 두 select 는 초안을 두지 않는다**(리뷰 2). 고르는 순간이 곧 커밋이라 지켜야 할
    중간 상태가 없고, 초안을 두면 그 값(항목 값 `col:…`/`sp:…`)이 지연 flush 의 일반 갈래로
    새어 `set_source` 에 실린다 — 존재하지 않는 열 「col:품명」에 결속되는, R5 센티넬 금지의
    정확한 위반이다. 초안을 가진 행 축은 **고정값 입력 하나**이고(`RowAxis = "const"`), 발신이
    실패하면 재렌더가 제어 select 를 서버 값으로 되맞춘다.
  - **행의 어포던스 술어는 전부 Python 이 낸다**: 배지의 `confirmable`(= 내용 있음 **또는**
    확인됨 — 비움 확정 행도 확인을 풀 길이 있어야 한다) 과 ↻ 의 `revertable`(= `revert_source`
    가 거절하지 않는 조건 그대로). 웹이 `touched && !confirmed && record_count` 로 다시
    조립하면 어포던스와 거절이 갈려 「눌렀는데 거절당하는」 버튼이 남는다.
  - **일괄 승격은 자동 제안만 올린다.** 머리의 `data-act="confirm-suggested"` 는
    `MappingModel.confirm_suggested()` 를 부르고, 그 대상은 **시스템 소유 + 내용 있는 행**
    뿐이다. 사람이 손댄 행과 열 필요 행은 각자 다른 답을 요구하므로 이 버튼이 대신 답하지
    않는다. **명시성 게이트는 불변이다** — `is_complete()` 는 여전히 전 행 확인이고, 승격
    뒤에도 남은 행이 있으면 저장이 그대로 막힌다. 머리 pill 셋(자동 제안·확인 필요·고정값)과
    버튼 라벨은 전부 `binding_head` 가 실어 보낸다(웹이 수치를 따로 세면 버튼이 약속과 다른
    일을 한다). 승격할 것이 0 일 때의 문안이 두 갈래인 것도 Python 소유다 — 다 확인한 0 과
    애초에 제안이 없던 0 은 같은 문장으로 말할 수 없다.
  - **일괄 승격 뒤 저장하면 `field:*:source`/`:format` 지문 키가 한 번에 N개 등장하고
    `binding_revision` 이 1 오른다 — 의도된 결과다**(F-06 지문 2축 불변). 명시성 게이트의
    정상 산출이고, `reviewed_rules` 기준선은 완주 런만 쓴다.
  - **미리보기는 산출물이 담을 것을 그대로 말한다**(`preview_kind` 5갈래): `value` 는 실제
    값, `missing` 은 결속됐는데 이 행에서 빈 값 — 문자열이 `domain/job.MISSING_MARKER` **그
    자체**다(생성이 그 자리에 넣는 바로 그 문자열이라 UI 문안이 아니라 데이터이고, 그래서
    웹이 짓지 않는다), `blank` 는 비워 둠(빈 셀 + 배지 「확인」), `none` 은 열 필요(「—」),
    `error` 는 「(미리보기 오류)」. 스테퍼(`prev-rec`/`next-rec`)는 표 머리 `th` 안에 서고
    `step_preview` 는 종전 그대로다(표시순서 투영 없음).
  - **드문 동사는 머리 우측 `⋯` 메뉴**(`data-act="binding-more"` → `#bindingMoreMenu`)다 —
    「자동 제안 다시 받기」·「모두 해제」·「직전 확인 n개 복원」. 컨트롤러 함수도 확인 왕복도
    종전 그대로이고 바뀐 것은 **어디에 서는가**뿐이다(§6: 같은 선택지를 모든 문맥에
    나열하지 않는다).
  - **「사용할 데이터 열」 선별은 사슬째 퇴역했다**(U6 §2.5 사용자 확정): 세션 상태
    (`_ignored_sources`·펼침 힌트) · 스냅샷 키 5개(`active_source_fields`·
    `ignored_source_fields`·`active_count`·`ignored_count`·`ignored_expanded`) · 액션 3개
    (`use_all_headers`·`use_none`·`toggle_source_active`) · `HeaderSelect` 표면이 전부
    사라졌다. 매핑되지 않은 열은 자연히 쓰이지 않고, 남은 질문 하나는 표 바닥 한 줄
    (`binding_head.unused_columns`)이 잇는다. 저장 파일에 이 상태가 없었으므로 마이그레이션도
    없다. 모델 API `apply_active_sources` 는 **남는다** — 데이터 재겨눔의 어휘 재동기화가
    계속 그 관문을 쓴다.
  - 구 `confirm_all`·`confirm_blanks`(ADR-E 이름 재진술 모달)는 사슬째 사라졌다: 일괄 승격이
    앞 절반을, 행별 「비워 둠」 선언이 뒤 절반을 진다. 이름을 되읽어 주던 이유는 **일괄**이
    반사적 dismiss 로 여러 필드를 한 번에 비우기 때문이었고, 행별 선언에는 그 위험이 없다
    (고른 행이 곧 확인한 행이다).
- **저장 단위는 한 section 의 patch**(§13-16). 다른 탭으로 가는 길을 막는 patch 는 **묻지
  않고 그 자리만 되돌린다**(자동 버리기): 편집기 한 탭에서 하는 작업량은 확인을 요구할 만큼
  크지 않아, 종전 3택(저장하고 이동·버리고 이동·머무르기)은 마찰과 왕복만 남겼다. 판정도
  집행도 Python(`_do_goto_section` → `_do_discard_patch({"section": …})`)이고 웹은 정산 뒤
  `goto_section` 을 한 발 보낸다. 확인은 걷혔지만 **알림은 남는다** — 되돌린 자리를 지목하는
  notice 가 그 재진술이다(confirm-or-alarm 의 alarm 쪽). 되돌리는 범위는 종전 「버리고 이동」과
  같아 어느 section 에도 속하지 않는 편집(이름)은 살아남는다.
- **「변경 버리기」·이탈은 세션 전체를 진입 시점 스냅샷으로 되돌린다**(확인 없음). 데이터
  선택도 **함께** 되돌아간다 — 결속이 durable 이 된 뒤로 저장본의 데이터는 버릴 대상이 아니라
  되돌아갈 자리이기 때문이다(#932 U4-C). 버릴 것이 없는 세션의 되돌리기는 무동작이고 notice 도
  세우지 않는다(클린 이탈마다 디스크 재적재와 거짓 통지가 서는 것을 막는 게이트가 컨트롤러
  안에 하나 있다 — 웹이 dirty 를 재판정하면 같은 상태를 두 곳이 답한다). 초안 이탈은 되돌릴
  base 가 없어 `new_session` 으로 세션째 끊는다. 편집기는 **창 종료 가드에 참여하지 않는다**:
  묻지 않고 버리는 것이 계약인 화면에서 창 닫기만 확인을 되살리면 그 계약이 두 얼굴을 갖는다.
- **주 행동은 하나** — 「변경 저장」. 「이번 생성에 적용」은 `runOverrides`(PR-B)의 표면이라
  라디오를 미리 늘어놓지 않는다(§6: 같은 선택지를 모든 문맥에 나열하지 않는다).
- **연결 확정 대기는 무장 사유를 더한다**(#911). 스냅샷 `binding_confirm`
  (`{pending, label, hint}`)이 참이면 주 행동이 활성으로 서고, 손댄 것이 없을 때만 라벨이
  링1 의 확정 문안(`gui/job_editor_state.BINDING_CONFIRM_*`)으로 갈린다 — 무변경 확정을
  「변경 저장」이라 부르지 않는다. dirty 기반 무장과 「변경 버리기」는 무변경이다(확정 대기는
  버릴 것을 만들지 않는다). 동사 실행은 **기존 저장 경로 그대로**이고 새 백엔드 동사가 없다.
  판정은 `JobController.editor_binding_confirm_pending` 이 관리 검토의
  `REVIEW_BINDING` 과 **같은 술어**(`document_creation_workbench.binding_review_needed`)로
  내리므로, 확정 동사가 서는 순간과 그 blocker 가 서는 순간이 정의상 같다. 종전에는 매핑이
  이미 옳으면 dirty 가 영영 거짓이라 확정을 요구받고도 수행할 동사가 없었다(#895 3차 관측).
- **진입은 늘 문맥과 함께**(§5.1): 사유·증거·복귀처를 보낸 표면이 싣는다. 미배선 사유는
  fail-closed 로 거절한다 — 조용한 폴백은 곧 배너가 아무 말도 못 하는 진입이다.
- **편집기 머리는 읽기 전용이다**(U6-D #978): 제목 `#editorTitle` 이 이 세션의 정체(이름,
  없으면 「새 작업」)를 말하고 부제 `#editorSubtitle` 이 짝(`{템플릿} ⟷ {데이터}`)을 말한다.
  이름 입력은 3단계 폼으로 갔고 소유는 여전히 세션이다(어느 section patch 에도 속하지 않는다).
  머리의 상태 pill 은 **상태만** 말한다(`아직 저장하지 않은 새 작업` / `저장하지 않은 변경` /
  `저장됨`). 저장 세대 카운터(`revisions`)는 규칙이 갈릴 때만 오르는 **내부 어휘**라 머리에서
  걷혔다(#945 F5) — 스냅샷 키(`revisions`)와 도메인 축(`Job.advance_revisions`)은 그대로이고,
  판본을 실제로 대조하는 자리(실행 결과 증거·작업 목록·규칙 작업대)가 계속 같은 값을 든다.
- **3단계 「이름·저장」은 폼 셋과 동사 둘이다**(U6-D #978 · U6 §2.2 · 동결 시안 장면 3).
  section id 는 `filename` 그대로이고 라벨만 갈렸다(`SECTION_LABELS` ↔ `SECTION_TITLES` —
  글자가 같아야 한다). **두 매체가 같은 세 단계**를 갖고(`sections_for("txt")` 도 셋),
  갈리는 것은 그 단계 **안의 한 행**이다 — 작업 이름은 매체와 무관한 저장 게이트 술어라
  없는 단계에 세우면 TXT 초안이 이름을 넣을 표면 없이 차단만 받는다.
  - 행 셋: ①작업 이름 `#editorName`(두 매체) ②문서 파일 이름 `[data-act="pattern"]`
    (hwpx 만) + 연번 예시 ③저장 폴더 `#editorOutDir`(읽기 전용) + 출처 + 「설정에서 바꾸기」
    (`#editorOpenFolderSettings` → 설정 모달).
  - **이름 기본값은 링1 이 도출한다**(`gui.job_editor_state.derive_job_name`):
    `{템플릿 이름} · {데이터 표시명}`, 한쪽만 있으면 그것 하나. 템플릿 쪽은 표시명의
    **마지막 세그먼트**다 — 표시명은 루트 상대경로(`온나라/기안`)라 그 슬래시가 작업 이름에
    들어가면 레지스트리 slug 가 경로 구분자를 접어 서로 다른 두 이름이 같은 파일로 저장될 수
    있다(목록이 부르는 이름과 작업의 이름은 답하는 질문이 다르다). **구분자는 가운뎃점**이다
    (U6 §5 미결 항목의 확정) — 문장 안 em dash 전면 금지(`docs/COPY_STYLE_GUIDE.md` §3-1)에서
    라벨 문형과 이름 문형이 같은 글자를 두 뜻으로 쓰면 그 규칙이 자리마다 예외를 갖는다.
  - **파생은 표지 하나가 진다**(`job_name_is_derived`). 재도출은 템플릿 채택
    (`load_template_path`)·데이터 마운트(`_adopt_datasource`, 풀 항목은 등록명을 세운 뒤 한 번
    더) 두 몸통에서만 일어나고, `set_name` 이 표지를 끄면 그 뒤로는 어떤 고르기도 사람이 지은
    이름을 덮지 않는다. `load_job` 은 도출하지 않는다(저장본의 이름은 사람이 지어 저장한 것).
    힌트 문안도 그 표지를 따른다 — 웹이 「이름이 도출값과 같은가」로 되유추하면 우연히 같은
    이름을 지은 순간 힌트가 되살아난다.
  - **도출값은 변경이 아니다**: 표지가 참인 동안 dirty 기준선은 **재도출 시점에 기록한 그
    값**(`_derived_name_baseline`)이다. 빈 문자열을 기준으로 두면 고르는 정상 진행이 초안을
    미저장으로 만들고, 손대지 않은 세션의 이탈마다 헛확인이 뜬다(#945 F7 의 데이터 축과 같은
    결함류). 기준선을 **매번 다시 도출**해도 같은 결함의 다른 얼굴이 된다 — 도출의 입력이
    바뀌면(서식 폴더 재지정으로 표시명이 갈리면) 기준선과 현재값이 서로 다른 시점의 도출이 된다.
  - **이름은 그 화면에 그려질 뿐 `filename` patch 가 아니다**(§10.13 판정 L): 탭 이동의 자동
    버리기와 `discard_patch {section}` 은 패턴만 되돌리고 이름은 그대로 둔다. 같은 화면에
    그린다고 같은 거래에 드는 것이 아니다.
  - **파일명 예시는 연번째로 Python 이 만든다**(`pattern_preview` = `X-001.hwpx · 002 · 003`).
    첫 이름은 실제 생성기(`make_output_filename`)가 만들고, **판정도 서식도 패턴이 낸다** —
    연번 유무는 `naming.pattern_uses_seq`, 붙는 모양은 그 토큰의 폭(`naming.seq_token_pads` →
    `domain.output_name.format_seq_token`)이다. 만들어진 이름 셋에서 「달라지는 부분」을
    유추하지 않는다: 그 휴리스틱은 연번에 **붙어 있는 데이터 값**을 연번으로 오인한다
    (`A{{연도}}{{seq}}` → `A20261.hwpx · 20262 · 20263` — 값이 그대로인데 연도가 매 건
    바뀐다고 말한다). 웹이 번호를 조립하면 seq 토큰이 없는 패턴에서도 연번이 있는 것처럼
    그려져, 실제로는 이름 셋이 충돌하는 자리를 정상으로 보인다. TXT 세션에서는 계산하지 않는다.
  - **저장 폴더는 읽기 전용 재진술**이다(#968 전역 값). 값·출처·하향 사유는 작업 화면과
    **같은 함수**(`webapp/output_folder_zone.output_folder_zone`)가 내고, 편집기는 자기 세션
    `template_path` 로 부른다(기본값이 「템플릿 옆 Results」라 저장 전 초안도 답할 수 있다).
    「기억한 지정」은 **작업 컨트롤러의 메모리 값**을 콜러블(`remembered_output_directory`)로
    읽는다 — 값의 소유자가 하나여야 설정 쓰기가 실패한 순간에도 두 표면이 같은 폴더를 말한다.
    **TXT 는 존이 `null`** 이고 그 행이 서지 않는다: 파일을 만들지 않는 작업이라 폴더가 축이
    아니고, 빈 재진술은 만들지 않을 파일의 저장 위치를 말하는 것이 된다.
  - **저장 동사는 둘이고 저장 자체는 한 경로다**: `save`(제자리 착지 — 결정 40 불변)와
    `save-and-open`(「저장하고 문서 만들기로」). 후자는 `doSave` 성공 뒤 **`leaveTo` 를 타지
    않고**(그 출구는 `discard_patch`/`new_session` 을 먼저 쏴 저장 착지를 되돌린다) 라이브러리
    「문서 만들기에서 사용」과 같은 순서를 지난다: `job/prefer_work` → `refresh("job")` →
    `go("job")`, `incompatible` 이면 표면이 「확인 필요」로 라우팅한다. **3분기 판정은 Python
    `prefer_work` 가 진다** — 편집기가 `select_job` 을 직접 쏘지 않는다. 이동만 실패하면
    머무르며 `#save-msg` 가 저장 성공과 이동 실패를 함께 말한다(성공을 숨기지 않는다).
    두 동사의 무장 술어는 **같은 값**이다(둘을 따로 세면 한쪽만 눌리는 상태가 실재한다).
  - **차단 조준은 단계를 옮기지 않는다**(`aimAtBlockedField`). `name`·`pattern` 은 둘 다
    3단계에 살지만, 거절당한 저장이 사람을 그 단계로 데려가면 지나온 단계의 patch 가 탭 이동의
    **자동 버리기**에 걸린다 — 연결 확인에서 방금 선언한 「비워 둠」이 저장 거절 하나로
    사라지는 자리다. 거절은 아무것도 파괴하지 않는 전이여야 하므로 이동은 사람이 하고, 어느
    단계인지는 **링1 차단 문안**이 말한다(`'이름·저장' 단계에서 …`). 표지(`invalidField`)는
    그 칸이 보이는 단계에서만 서고 성공 저장·단계 전환·그 칸 입력에서 걷힌다(안 보이는 칸에
    남은 `aria-invalid` 는 다음에 그 단계로 갔을 때 고치지도 않은 칸을 나무란다).
    `blocked_field="data"` 는 종전대로 1단계 우 열이다.
- 「저장」 분류는 사망했고 그 항목은 흩어졌다: 이름·파일 이름·저장 폴더=3단계 「이름·저장」
  폼(U6-D #978 — 종전 「이름=머리 인라인」의 승계처), 작성 출처=템플릿 탭, 저장 버튼·차단
  사유=footer. **저장 시 데이터 자동등록(#18·#26)과 기본 데이터 연결
  재진술(#53-A)은 #347(U2 §5.3 판정 D)로 폐기** — 편집 세션의 데이터는 검토용 문맥일 뿐
  작업에 저장되지 않고, 풀 등록은 데이터 선택 면의 「이 데이터 고정」 하나다.
- **알림은 인라인 한 채널**(`#save-msg` — S8G-00 #323). 노드는 섹션 본문이 아니라 **셸
  레벨**(`.editor-shell` 직속, 본문과 footer 사이)에 서서 세 탭이 공유하고 본문 재렌더에
  증발하지 않는다. 라우팅 규칙은 하나다: **구조화된 실패·안내**(`block_reason`,
  `result.error`, `ERROR:` 접두 브리지 반환, 선차단 안내)는 `noticeSave` 로 가고,
  `window.alert`(`deps.notify`)는 **던져진 예외의 catch 백스톱 전용**이다. 종전에는 파일
  이름 탭에서만 인라인이라 나머지 두 탭의 거절이 모달 경보로 샜다 — 경보는 읽는 순간
  사라지고 그 뒤 화면은 왜 막혔는지 아무 말도 하지 않는다.
- **수동 소멸 알림은 닫기 동사를 가진다**(U4 §2.12 · #945 F4). 매 변이 자동 소멸하지 않고
  「사유가 해소될 때까지 남는」 알림은 전부 화면 중립 `NoticeBox`
  (`frontend/src/screens/notice_box.ts`)로 그린다 — `onClose` 가 필수 인자라 **닫기 없는
  인스턴스를 만들 수 없다**. 지금 이 문법을 쓰는 자리는 셋이다: 편집기 `#save-msg`
  (닫기 `#saveMsgClose` → JS 전용 `clearSaveMessage`), 편집기 세션 통지(닫기
  `#editorNoticeClose` → 액션 `dismiss_notice`), job 데이터 통지 `#jobDataNotice`(닫기
  `#jobDataNoticeClose` → 액션 `dismiss_data_notice`). 상자·닫기만 컴포넌트가 소유하고
  문안 조립·레벨 판정은 각 렌더러가 그대로 진다. 자동 소멸 알림(workbench·job_run·
  job_slot_config)은 이 문법을 **쓰지 않는다** — 닫아도 다음 변이에서 다시 서는 단추가 된다.
- **「누름틀·구간 변환」과 구간 항목 관리**(S8-03 #834): 라이브러리 행의 상태 동사
  `compile` 은 **한 동사로 두 축**을 변환한다 — 필드 토큰(`compile_document`)을 먼저,
  구간 표기(`compile_structure`)를 다음에(순서는 계약이다: 구조를 먼저 만들면 그 안의
  `{{필드}}` 가 depth>0 이 되어 필드 컴파일에서 조용히 빠진다). 라벨은 링1
  `_STATE_ACTIONS` 소유고 RAW 에서 「누름틀·구간 변환」이다. 미리보기·판정·문안은 전부 링1
  (`convert_preview`·`apply_convert`·`format_convert_*`)이고, **표기 진단이 1건이라도 있으면
  확인을 묻지 않고** 인라인 결과로 차단 사유를 재진술한다(변환 불가는 확정할 것이 아니다).
  구조 컴파일이 거절되면 필드 변환이 이미 저장됐더라도 그 거절이 같은 결과 줄에 실린다.
  - `review` 는 읽기 전용 검토이고 그 결과가 **항목 상세 한 벌**(`tpl` 스냅샷 `detail` 존)을
    세운다(U6-E #979 — 종전 `slots` 존의 확장):
    `{path, name, media, state, badge_label, badge_level, field_count, field_summary,
    fields[{name,type_hint}], actions[{key,label}], diagnostics, slots{summary,rows}, error}`.
    투영·성형은 링1(`TemplateDetail`·`SlotView`) 소유이고 **파일을 한 번만 연다** — 판독과
    lint 가 한 포트(`TemplateFileOps.inspect_and_lint`)를 지나므로 상태·배지·필드·구간 항목·
    진단·위생 점검이 같은 스냅샷에서 나온다(#989 리뷰 7: 두 번 열면 시트 한 장이 두 스냅샷을
    이고, 비용도 두 배다). **판독 예외는 링1 한 자리에서 사유로 접힌다**(`review_view` →
    `TemplateDetail.error`, 리뷰 1) — `zipfile.BadZipFile` 은 `ValueError` 가 아니라 dispatch
    의 거절 봉투를 벗어나고, 그러면 오류 행의 「자세히…」가 영영 시트를 못 연다. 못 읽은
    파일에 lint 는 없다(`None`)이고 결과 줄이 그 사유를 재진술한다.
    매체를 가른다: TXT 는 상태도 구간 축도 없어 필드 목록과 판독 실패 사유뿐이고, **조회가
    곧 소속 판정**이라 레지스트리를 한 번만 훑는다. hwpx 진입은 **경로 관문**
    (`is_live_path`)을 지나고, 겨눈 파일이 목록에서 사라지면 스냅샷이 스스로 `null` 로
    걷는다(죽은 경로를 겨눈 버튼 금지).
  - **표면은 항목 상세 시트 `#tplDetailModal` 하나다**(U6-E #979). 정적 target 은
    `frontend/index.html` 에 서고 **비어 있어야** 한다(`requireEmptyTarget` fail-closed),
    내용은 React `screens/editor.ts` 의 `TplDetailSheet` portal 이며 등록은
    `PRODUCT_OVERLAY_COMPONENTS` 경유 `bootstrap.js` 한 줄이다(`txtEditModal` 선례 — 편집기
    몰입 표면 위 모달). 여는 문은 둘이지만 함수는 하나다(`openDetail`): 행 ⋮ 의
    「자세히…」와 게이트 존의 `data-act="session-detail"`. **순서가 계약이다** — `tpl/review`
    왕복이 먼저, 그 뒤에 `Modal.open`(먼저 열면 지난 항목의 상세가 한 프레임 선다).
    구성은 위→아래로 머리(표시명 · 상태 pill · 닫기) → 경로 + `PathActions` → 판독 실패·
    구간 진단 → 필드 표(`.schema-fields` — #16 「나열식 금지」의 좌표) → 구간 항목 표
    (`#tplDetailSlots`) → 동사 줄(`#tplDetailVerbs`)이다.
  - **행 ⋮ 목록과 시트의 동사 줄은 같은 함수가 짓는다**(`libRowMenuItems`) — 시트는 자기
    자신을 여는 「자세히…」만 걷는다. 그 목록은 **닫힌 집합**이고, 처리도 분기표 하나
    (`runItemVerb`)를 지난다(#989 리뷰 9 — 두 진입이 정하는 것은 대상과 실패의 착지뿐이다).
    모르는 키는 조용히 떨어지지 않고 던진다. **`act:review` 는 없다**(리뷰 10): 검토 왕복은
    「자세히…」 하나가 지고, 링1 `_STATE_ACTIONS` 는 **수선 동사만** 든다
    (RAW→`compile` / PARTIAL→`compile` / COMPILED·FILLED→없음). 「자세히…」는 **모든 행에**
    서므로 동사 0 인 행이 없다 — U6-A 의 「동사 0 → ⋮ 비활성 + 사유」 판정은 그 근거와 함께
    걷혔고(`LIB_ROW_NO_ACTION_REASON` 삭제), 그 판정이 막던 무반응은 그대로 막힌다: 어느
    행이든 누르면 답할 것이 있고, 오류 행에서는 시트가 그 사유를 보인다.
  - 구간 항목 표의 행 동사 셋은 `data-act="slot-rename"`·`"slot-decompile"`·`"slot-remove"`
    (+`data-slot=<id>`)다. 개명은 `Modal.prompt` 하나로 끝나고(파괴 아님), 표기로 되돌리기·
    삭제는 `needs_confirm` 왕복이다 — **확인 본문은 Python 이 싣는다**(되돌리기는 「다시 변환
    전까지 문서를 만들 수 없다」는 전이 결과를, 삭제는 손실 집합을 재진술한다). 판독 진단이
    있으면 사유만 서고 동사 버튼은 아예 없다.
  - **표 머리 동사 하나가 더 선다**(U4-E3 #939 · `UX_FEEDBACK_U4` §2.16): 표 머리의
    `data-act="slot-decompile-all"`(「전부 표기로 되돌리기」)는 항목이 아니라 **파일**을
    겨눈다 — `data-slot` 이 없고 payload 에 `slot_id` 가 없다. 노출 술어는 행 동사와 **같다**
    (진단 0 · 행 1건 이상 — 개수 문턱을 따로 두지 않는다). 확인 문안은 단건 문형 승계로
    범위 한 줄만 다르고, 확정 뒤 그 템플릿은 PARTIAL 로 재진입한다.
  - 액션은 `slot_rename`(`path`·`slot_id`·`label`)·`slot_decompile`·`slot_remove`
    (각 `path`·`slot_id`·`confirm`) + `slot_decompile_all`(`path`·`confirm`)이고 넷 다 경로가
    **현재 HWPX 라이브러리 목록**에 있어야 한다(임의 파일 변이 권한 승격 차단. 관문 몸통은
    공개 술어 `TemplateController.is_live_path` 하나이고 `_slot_path` 가 그것을 지나며 행
    동사는 그 위에 id 검사를 얹는다). 그 관문의 규칙 둘(#989 리뷰 4·7): **캐시 적중 + 파일
    존재 검사로 끝내고 재스캔은 부재를 만났을 때만** 한다(무조건 재스캔하면 「자세히…」 한
    번이 폴더 전건 판독을 물어 온다 — 200개면 200 inspect), 그리고 **부재로 확정되면 거절
    전에 갱신된 목록을 민다**(`tpl` push). 거절 문구가 「목록을 새로 고쳤으니 다시 고르세요」
    라고 말하는데 좌 열에 그 행이 남아 있으면 사람은 같은 클릭을 반복한다 — 목록의 정본이
    이 채널이므로 그 push 도 여기서 나가야 한다.
    풀기 몸통은 External 이 지고(`decompile_structure` = `decompile_slot` 문서 순서 반복 +
    문서 단위 원자성), 링1 은 `decompile_all_slots`·`confirm_decompile_all_text` 를 소유한다.
  - **파일을 바꾼 tpl 동사는 전부 상세를 다시 투영한다**(`_reproject_detail` · #989 리뷰 2):
    slot 동사 넷 + 「누름틀·구간 변환」(`mutated` 갈래) + TXT 저장. 상세 **한 벌 전체**를
    다시 세우는 이유는 변환이 상태·배지·필드·항목을 한꺼번에 바꾸기 때문이다(목록만 갈아
    끼우면 새 항목 목록 위에 옛 상태 배지가 선다). **다른 파일의 변이는 시트를 건드리지
    않는다** — 대조는 이 채널의 정규화 술어 하나를 지난다. 세션이 연 파일과 같은 경로면 기존
    seam(`mutation_sinks` → `reconcile_template_mutation`)이 편집 세션 무효화 + notice 를
    세운다 — **이 사슬은 불변**이고, 시트는 그때 닫히지 않는다(편집기 notice 가 말한다).
  - **시트가 열려 있는 동안의 결과·실패는 그 면 안에 선다**(#989 리뷰 3):
    `tpl.column.result` 는 `#tplDetailResult`, 동사 실패는 `#tplDetailMsg`. 시트는 스크림으로
    화면을 덮으므로 좌 열 바닥 결과 줄도 `#save-msg` 도 그 뒤에 그려진다 — 값의 정본은 그대로
    고르기 열 존의 결과 줄이고 바뀌는 것은 **그리는 자리** 하나다(등록 데이터 시트도
    `pool.column.result` 로 같은 대칭이다). 열림 표지와 그 사유는 모달 엔진의 `beforeClose` 한
    자리가 함께 걷는다(다음 열림에 지난 사유가 남지 않는다).
  - **편집기의 구간 축 요약(구 `template_slots`·`#editorSlotSummary`)은 퇴역했다**(U6-E
    #979 · 판정 승계는 `UX_FEEDBACK_U6` §2.9). U4 §2.15 가 그 존을 읽기 전용으로 둔 근거는
    「저장 전 초안은 템플릿 파일을 변이시키지 않는다」였고 그것은 **동사 부재** 판정이었다.
    이제 동사는 편집 세션이 아니라 **풀 항목(파일)** 을 겨누는 시트에 서고, 세션과 같은
    파일일 때의 무효화는 위 seam 이 진다 — 근거가 옮겨졌으므로 존도 옮겼다. 링2 의
    `_slot_view_for`·스냅샷 키 `template_slots`·`schema_summary`·`provenance` 는 사슬째
    사라졌고, `_build_provenance` 는 **저장 경로가 쓰므로 그대로 산다**(durable 기록).
- **동봉 예제 진입점 둘은 동결이다**(#941): 편집기 「템플릿」 탭 공용 버튼 줄의
  `data-act="install-examples"`(#891 상시 설치)와 `data-act="remove-examples"`(#892 일괄 제거)는
  튜토리얼 진입 표면과 함께 배포본에서 걷혔다. `tpl` 채널의 `install_examples`·
  `remove_examples` 액션, 확인 왕복 문안, 스냅샷 축 `library.examples`
  (`removable`·`remove_label`·`remove_hint` 포함), 설치·제거 몸통
  (`external/example_pack.install`/`.remove` — manifest 기재분 밖은 건드리지 않는다)은 전부
  그대로 산다. 되살릴 때 그 자리에서 다시 소비한다(아래 「온보딩 튜토리얼」 절의 동결 표기).
- **TXT 저작 린트메모장**(S10-05 #862 · #299 회수): `#txtEditModal` 의 본문 입력은 textarea 가
  아니라 CodeMirror 6 메모장(`#txtLintpad`, 컨텐츠 DOM 은 종전 id `#txtEditContent`)이다.
  **판정은 하나도 프런트에 없다** — 타이핑 180ms 디바운스 뒤 `tpl/txt_lint`(`content` 하나,
  경로 없음 · 읽기 전용이라 editor 재당김을 태우지 않는다)가 링0
  `scan_text_structure`+`scan_text_token_spans` 의 진단·요약·**토큰 문자 오프셋**을 그대로
  싣고, 표면은 그 좌표에 `.cm-txtField`/`.cm-txtMarker` 를 얹고 `message` 를 `#txtLintDiag`
  로 재진술만 한다(웹에 `{{…}}` 정규식 0 — 있으면 sigil 선행 분류가 두 곳에서 갈린다).
  낡은 응답은 세대 + 본문 대조 두 관문이 막는다.
  - vendor 봉쇄(#588)는 `frontend/src/editorview/txt_lintpad.ts` **파일 하나**다:
    `mountLintpad`·`updateLintpad`·`disposeLintpad` 가 `tests/architecture_contract.toml`
    `[vendor_integration.codemirror]` 의 세 소유 심볼이고, CodeMirror 타입은 이 파일 밖으로
    나가지 않는다. **키맵을 세우지 않는 것이 계약**이다 — Escape/Tab 이 vendor 에 먹히면
    모달 이탈 가드(`beforeClose`)와 포커스 트랩이 조용히 우회된다.
  - 저장 동사는 셋이고 **전부 Draft 보존까지**다(#856 D5): 「저장」(신규=`txt_new` ·
    편집=`txt_edit` 드리프트 왕복)과 편집 모드의 「새 파일로 저장…」(`Modal.prompt` +
    같은 `txt_new` 재사용 — 새 백엔드 동사 없음). 성공 직후 `#save-msg` 가 「변경사항 확인」
    다음 「변경사항 적용」이 남았음을 말한다 — Candidate 출생은 그 동사이지 저장이 아니고,
    말하지 않으면 한 동작이 두 사건인 척한다.
- **고르기 단계 좌 열은 `tpl` 채널을 직접 구독한다**(U6-B #976): 목록·결과 줄·구간 항목
  목록의 정본이 그 채널 스냅샷 하나이고, 편집기 표면이 `runtime.model("tpl")` 을 읽어 그린다.
  그래서 tpl 의 변이가 목록에 닿는 길은 그 채널의 push 하나이고, 재스캔(`tpl/refresh`)은
  **editor 재당김을 태우지 않는다**(같은 진입에서 디스크를 두 번 읽지 않는다). 반대로 파일을
  변이시키는 tpl 동사는 이 세션의 스키마·게이트를 흔들 수 있어 종전대로 재당김 하나를
  태운다. 재스캔 트리거는 **1단계 진입당 한 번**이다(신규 초안·`load_job`·1단계 재진입) —
  렌더마다 훑지도, 영영 안 읽지도 않는다(U6 §2.3 「화면 진입 시 diff + 수동 새로 읽기」).
  같은 진입이 `pool/refresh` 도 한 발 보낸다(CLI·다른 창의 등록이 목록에 서지 않으면 같은
  침묵이다). **트리거는 스냅샷이 아니라 사건에 걸린다**: 셸이 편집기 화면에 들어설 때 부르는
  `rerender`(`shell/nav.ts`)와 같은 세션 안의 `gotoSection("template")` 둘이다. 마지막으로 본
  `(세션, 단계)` 를 기억해 전이를 유도하면 **초안의 세션 표지가 언제나 `"draft"`** 라
  「초안 → 취소 → 새 초안」이 같은 값으로 읽혀 두 번째 새 작업부터 재스캔이 조용히 빠진다.
- **tpl→editor 재정산 seam**(S8G-00 #320): tpl 채널이 템플릿 파일을 durable 로 바꾸면
  (`compile` 확정 · `slot_rename`·`slot_decompile`·`slot_decompile_all`·`slot_remove`
  확정 · `txt_edit`) 그 성공 **직후**
  `TemplateController.mutation_sinks` 가 `(kind, path)` 로 통지하고
  `EditorController.reconcile_template_mutation` 이 같은 파일을 든 세션만 다시 세운다
  (경로 대조는 `template_groups.norm_library_path` 단일 술어, 남의 파일이면 푸시도 없다).
  `mutated` 는 템플릿을 재로드해 스키마를 다시 파생하고 기존 이월·강등
  의미론(`_ensure_model`)을 그 위에 돌린 뒤 warn 으로 재진술한다. 채울 대상이 0 이 되면
  (RAW 강등) 낡은 모델을 걷고 danger 로 말한다 — 남겨 두면 이제는 없는 필드로 저장 게이트가
  통과한다. 삭제·복원 동사는 U6-A 에서 **퇴역**했다: `restored` 는 생산자 0 으로 종류
  열거에서 함께 걷혔고(`MUTATION_KINDS` = `mutated`·`deleted`), `deleted` 의 남은 발신자는
  동결 온보딩의 예제 일괄 제거뿐이다. `deleted` 는 danger 재진술만 하고 `template_path` 는 **지우지 않는다**; 그동안의 저장은 링2 심층 방어(`_missing_template_block`)가
  기존 `block_reason` 채널로 막는다. 이 seam 은 디스패치 액션이 아니라 **컨트롤러 간
  배선**이라 action registry 밖이고, 조립 한 줄은 `webapp/app.py` 가 소유한다.

### 데이터 선택 다이얼로그 (재작성 F1 — `pool` 화면 사망의 승계처)

데이터 선택은 「문서 만들기」 세션 표면이 여는 **한 오버레이**(`#dataPickerModal`,
`frontend/src/screens/data_picker.ts`)로 수렴한다. 구 2버튼(「등록 데이터…」·「파일 선택…」)과
`pool` 화면(`#scr-pool`·`screens/pool.js`)은 사망했고, 그 기능은 **고르기 열 하나**로
흡수됐다(고르기 열 공용 계약 — 종전의 세 구획 「현재 데이터 / 고정한 데이터 / 다른 데이터」가
목록 한 벌 + 바닥 동사 줄이 됐다):

| 자리 | 내용 | 백엔드 |
|---|---|---|
| 목록 첫 행(키 `session`) | 지금 쓰는 데이터의 재진술(이름 + 「시트: … · 헤더 n행 · m행」 — 계약 목록의 뷰 이름은 **Python 이** 제목으로 옮기고 표에 없는 이름은 원문 그대로) + 「사용 중」 배지 | 작업 스냅샷 `data_row`(`webapp/pool_column.session_data_row`) |
| 나머지 행 | 등록 데이터 **전 상태**(활성·보관·끊김·나라) — 클릭이 곧 「이 데이터 사용」이고 관리 동사(보관·활성화·삭제·다시 연결) · 「폴더에서 보기」 · 「자세히…」는 행 ⋯(`#dataPickerRowMenu`) | `pool` 컨트롤러 `column`·`detail` 존·액션 **그대로** |
| 목록 안 통지 | 손상 격리(danger)·중복 등록(warn)과 그 정리 동사 — `[data-notice]` | `pool.column.notices`(문안·수치는 Python) |
| 바닥 동사 줄 | 파일 찾아보기(1회용, `#dataPickerBrowse`) → 다중 시트면 시트 확정 게이트 · **「계약 목록(.db) 등록…」**(`#dataPickerPclm` → `#poolRegModal` pclm 모드) · 「이 데이터 고정…」(`#dataPickerPin`) | 호스트 `pick_data_file`/`load_data_sheet` · `pool/register_pclm`/`register_excel` |

- **몸통은 공용 `PoolColumn` 이다**: 모달 껍데기(제목·상태줄·닫기)만 이 파일이 지고, 목록은
  고르기 1단계의 두 열과 **같은 컴포넌트**다(위 「고르기」 절). 종전에는 이 자리가 별도
  컴포넌트(`pool_list.ts` 의 `PoolSections` — 카드 + 행 안 버튼 다섯)였고, 같은 등록 목록을
  두 문법으로 그리던 자리라 「고를 수 있는가」의 얼굴과 행 동사가 화면마다 갈렸다. 그 파일은
  **퇴역**했고 관리 동사 한 벌(`createPoolVerbs`·`PCLM_UNAVAILABLE`·`PoolRegistrationPort`·
  거절 문형)은 `frontend/src/screens/pool_verbs.ts` 로 옮겨 두 호스트가 계속 공유한다 —
  그리는 일과 발신하는 일은 애초에 다른 관심사다.
- **행 ⋯ 의 목록은 두 호스트 공용 하나다**(`pool_verbs.dataRowMenuItems`): 링1 `actions` ·
  경로가 있을 때 「폴더에서 보기」 · 마지막에 「자세히…」(세션 행 제외).
  이 파일이 같은 규칙을 다시 적던 지역 `rowMenuItems` 는 그와 함께 걷혔다.
- **등록 데이터 상세 시트(`#poolDetailModal`)의 주인도 이 컨트롤러다**(등록 폼과 같은 근거 —
  overlay 는 셸 레벨 하나이고 여는 문이 둘이다). 고르기 우 열은 `PoolRegistrationPort.
  openDetail(key, trigger)` 로 그 문을 부른다. 순서가 계약이다 — `pool/review` 가 먼저 상세를
  세우고 **그 뒤에** 시트가 열린다(먼저 열면 지난 항목의 상세가 한 프레임 선다). 시트가 열려
  있는 동안 동사의 실패는 **시트 안**(`#poolDetailMsg`)에 서고 이 면의 상태줄에는 쓰지
  않는다 — 스크림 뒤 채널에 같은 문장을 두지 않는다.
- **좌표**: 살아 있는 것은 `#dataPickerModal`·`#dataPickerTitle`·`#dataPickerNote`·
  `#dataPickerClose`·`#dataPickerPinned`(목록)·`#dataPickerBrowse`·`#dataPickerPclm`·
  `#dataPickerPin` 이다. 카드 시절의 `#dataPickerCurrent`·`#dataPickerDupes`·
  `#dataPickerCorrupt`·`#dataPickerRegister`와 구획 캡션(`*Cap`)은 그 카드와 함께 사라졌다 —
  현재 데이터는 목록 첫 행이고 통지는 목록 안 `[data-notice]` 다.
- **「지금 쓰는 데이터」는 여는 쪽이 Python 값으로 건넨다**(`job_read.currentData` →
  `open({session})`): 행 하나(`data_row`)·그 마운트의 풀 슬롯 키(`data_pool_key`)·고정
  프리필의 시트(`data_target.sheet`) 셋뿐이고 문안은 한 글자도 웹이 짓지 않는다. **값이
  아니라 함수**로 건네는 것이 계약이다 — 이 면 안에서 파일을 새로 열면 마운트가 바뀌고
  스냅샷이 다시 오는데, 여는 순간의 값을 얼리면 그 행이 이제는 쓰지 않는 데이터를
  「사용 중」이라 말한다.
- **고름 표지와 「이 데이터 고정…」은 한 값이 가른다**: `data_pool_key` 가 있으면 그 슬롯 행이
  고름 표지를 들고 고정 문은 서지 않는다(이미 고정된 참조를 다시 고정하면 같은 파일의 참조가
  둘로 갈린다). 없으면 세션 행이 표지를 들고 고정 문이 선다.
  편집기 축약판 `PoolPickList`(`#editorPoolPick`·`pick-pool-data`·`pool-pick-close`)와 그
  조회 액션 `editor/pool_options` 는 소비자 0 이 되어 **사슬째 퇴역**했다.
- **화면은 죽고 컨트롤러는 산다**: `PoolController` 는 그대로 살아 이 다이얼로그가 `pool`
  관측 푸시의 구독자다(`Bridge.onPush("pool", …)`). 판정·문구는 Python 단일 출처.
- 보관·끊김 항목은 숨기지 않고 **정직하게 비활성** + 사유 병기 — 숨기면 `활성화`·`다시 연결`
  동사에 도달할 길이 사라진다.
- **닫힘 규약(U2 §2.7)**: 실패(나라 동결·죽은 참조·모호 시트·행 0건·읽기 실패)는 절대 닫지
  않고 면 안 상태줄에 재진술한다. 고정 목록 선택은 남은 결정이 없어 성사 즉시 닫히고,
  **파일 찾아보기는 성사해도 면을 유지한다** — 목록 첫 행이 새 마운트로 다시 서고 바닥
  동사 줄에 「이 데이터 고정…」이 남는다(끝난 선택은 닫히고, 결정이 남은 선택은 남는다).
  마운트 진행 중에는 닫기·Escape 를 차단하고 표기한다.
- 전환 손실 가드는 **대상 확정 직후·읽기 직전**에 호스트 콜백으로 묻는다(`confirmSwap`).
- 고정·다시 연결은 `#poolRegModal` 을 이 면 **위에** 스택으로 띄운다(제목이 진입 사유).
  「＋ 직접 등록…」은 죽었다(U2 §2.7 4행 — 「읽지 않고 등록」이 유일한 고유 기능이자 곧
  결함). pin 모드에서는 path·sheet 가 읽기전용이고 폼 안 찾아보기(`#poolRegBrowse`)를
  감춘다(§2.7 5행) — 그 버튼·`pick_pool_data_file` 브리지는 「다시 연결」이 계속 쓴다.
- **데이터 축 정체성은 kind-스코프다**(#347 · U2 §5.3 판정 C · #937): 엑셀은
  `normcase(abspath(path)) + sheet`, 계약 목록은 `"pclm"` 접두 + `normcase(abspath(db)) + view`.
  이름은 어느 쪽에서도 **순수 라벨**이다. 접두를 나누는 이유는 종류가 정체의 성분이기
  때문이다 — 한 축으로 뭉치면 같은 파일을 가리키는 두 종류의 등록이 서로를 「같은 데이터」로
  읽는다. 풀 항목 조작(`archive`·`activate`·`delete`·`load_pool`·`relink`)은 종류와 무관하게
  슬롯 `key` 를 겨눈다. `register_excel`·`register_pclm` 의 중복 판정은 각자의 정체성이다:
  같은 데이터 재등록은 2건이 아니라 기존 등록의 라벨·메모 갱신(확인 승격) 또는 「이미
  고정돼 있습니다」 재진술로 접힌다.
  `relink`(`key`+새 참조)는 같은 슬롯의 참조 교체(수명 보존)이고 확인 왕복을 거친다.
  구판(이름=키)이 남긴 **같은 정체성 등록 2+건**은 고르기 열 존 통지(`column.notices` 의
  warn)로 loud 표면화되고 `resolve_duplicate`(남길 `keep` 확정, 확인 왕복)로만 정리된다 —
  조용한 자동 병합 금지. 그 통지가 후보마다 「'이름' 남기기」 동사를 같은 자리에 세운다.
- **계약 목록(pclm) 행의 규약**(#937): 목록에 종류 배지(`계약 목록`)와 참조 요약
  (`DB: … · 시트 …` — 면 이름은 제목으로 옮긴다)으로 서고, 행의 `path` 는 db 파일이라
  끊김 사유·열기·폴더보기가 엑셀과 같게 산다. 활성·파일 존재면 「이 데이터 사용」이 그대로 열린다. **「다시 연결」은 서지
  않는다** — 그 동사는 경로+시트 좌표(`relink_excel`)의 엑셀 전용이라 pclm 행에 세우면 누를
  수 있는 거짓 어포던스가 된다(표면 조건은 `row.kind === "excel"`).
- **`#poolRegModal` 은 모드를 명시로 든다**(`RegState.mode` — `excel`|`pclm`). pclm 모드는
  경로·시트칸·폼 안 찾아보기를 감추고 **DB 자리**(`#poolRegDb` — 스냅샷 `pclm.default_db`
  프리필, 편집 가능. 비우면 백엔드가 「기본 자리」로 해석해 `opts` 에 박는다)와 **읽을 시트**
  (`#poolRegView` select)를 묻는다. 초기 선택은 목록 첫 항목이 아니라 **빈 placeholder**
  (「시트를 고르세요」)이고 빈 채 제출은 프런트가 사유와 함께 막는다 — 계약면을 조용히 하나
  고르면 문서 건수가 어긋나므로 그 값은 사용자가 확정한다. 진입 버튼(`#dataPickerPclm`)은
  스냅샷에 `pclm` 블록이 없으면 숨기지 않고 **비활성 + `title` 사유**다(조용한 죽은 버튼
  금지). 확인 왕복(`needs_confirm`/`basis`)은 엑셀 등록과 **같은 한 벌**을 재사용한다 —
  신설 브리지 메서드는 없다(직접 브리지 목록 무변).
- **표면 어휘는 「시트」이고 내부 이름·프로젝트 이름은 서지 않는다**(U4 표면 감량). 옵션의
  `value` 는 실제 뷰 이름(백엔드 계약·SELECT 에 박히는 값) 그대로지만 **보이는 글자**는
  `${title} — ${desc}`(스냅샷 `pclm.views`)라 `v_통합_v1` 같은 이름이 표면에 새지 않고,
  진입 라벨의 괄호는 확장자다(`계약 목록(.db) 등록…` — 저쪽 프로그램 이름 `pclm` 은 표면
  어휘가 아니다). 두 다이얼로그의 설명 부제(`modal-sub`)와 「다른 데이터」의 안내 두 줄은
  **삭제**됐다 — 폼이 묻는 좌표가 이미 그것을 말한다.
- **웹 등록이 고르게 하는 면은 셋이다**(`pclm.views` ← `PCLM_DOC_VIEWS`). `v_품목_v1` 은
  한 계약이 여러 줄로 오는 유일한 뷰인데 한 문서 안에 N 줄을 반복 표로 펴는 기능이 아직
  없어서, 지금 고르게 하면 품목 1줄이 문서 1건이 된다. 좁히는 것은 **새로 고르는 자리**
  하나이고 허용목록(`PCLM_VIEWS`)·CLI·겨눔 백스톱은 넷 그대로다 — 그래서 이미 등록된 품목
  참조도 조용히 못 읽는 것이 되지 않고, 그 마운트의 제목은 **Python 이 짓는다**(링0
  `pclm_views.sheet_title` — 세션 행 부제와 상세 투영이 같은 함수를 지난다). 웹으로 내려가던
  뷰 전수 제목표(`pclm.titles`)는 그래서 소비자 0 으로 걷혔다.
- **파괴·덮어쓰기 확정은 「보여준 상태의 지문」에 결속된다** — 이 화면의 확정 왕복
  **다섯 전부**(`delete` · `register_excel` 의 라벨 갱신 · `register_pclm` 의 라벨 갱신 ·
  `relink` · `resolve_duplicate`)가 기제 하나를 공유한다. 종류가 늘어도 왕복은 늘지 않는다:
  좌표가 다른 등록은 정체성 판(`relabel_confirmed_raw`)으로 같은 몸통에 얹는다. 1차 응답이
  `basis`(`screen_pool.confirm_basis`)를 발행하고 확정이 그대로 되싣는다. 백엔드는 쓰기 잠금 안에서 지금 상태의 지문을 다시 지어 대조하고,
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
| 좌 `.dg-main` | 현재 데이터(겨눔·검색·필터·**사전검증**·위험 배너·표·필터 밖 스트립) → 생성 예정 문서(`#jobDeliveryZone`) → 생성 결과 | 데이터-우선 흐름의 입력·계획·되읽기 |
| 우 `.dg-side` | 이 데이터에 사용할 문서(후보·추천·탐색 출구 — 활성 카드가 정체·템플릿·연결 상태를 겸한다) → 생성 준비(저장 폴더 **표시** 한 줄) | 문서 선택과 실행 준비 |

- 두 열은 존 구분선을 공유하는 **한 카드 안의 구획**이고, 컨테이너 900px 이하에서 1열로
  퇴화한다(`@container session-panel`). 구 `.job-duo`(표\|거울 가로 병치, #272)는 이 형상으로
  대체됐다.
- **「본문 확인」 존은 사망했다**(존 재편 — 2중 발화 축소). 그 존의 몸통이던 요약 한 줄
  (`#jobMirrorLine`/`#jobMirrorSummary` — 빈 값 표지 + 이름 건수)은 바로 위 **사전검증**
  (`#jobPreflight`)이 이미 말하는 사실의 두 번째 발화였다. 계보는 이렇다: 구 거울 테이블
  (필드 채움 표·클릭형 ack 행·펼침 면 `#jobConfirmSheet`)이 필드축 ack 폐기와 함께 죽고
  (U2 §2.13 · #346), 값·이름을 말하던 확인 면(`#previewSheet`)과 그 출구가 #957 에서
  철거되고(**값을 말하는 표면은 만들어진 문서다**), 남은 요약 한 줄이 여기서 걷혔다.
- **남는 것은 행동을 든 위험 배너뿐이다**(`#jobMirror` — 구조 드리프트·미해소 파일명 토큰).
  그 host 는 `#jobPreflight` **바로 아래**로 내려와 「무엇이 잘못됐나(사전검증) → 어디로
  가서 고치나(배너의 복구 동사)」가 한 자리에서 이어진다. 배너에는 캡션이 없다 — 존이
  아니라 데이터 존 안의 한 조각이고, 위험이 없으면 host 는 빈 채로 자리를 차지하지 않는다.
  그래서 게이트 지목(`GATE_ZONE`)의 `drift`·`name_tokens` 는 **빈 문자열**이다(`template_missing`
  동형 — 없는 구획을 가리키느니 안 가리킨다).
- **인라인 재진술(`#jobRestate`)도 사망했다**: 「선택 N행」은 표 머리와 필터 밖 스트립이,
  「생성 N건 · 저장 폴더」는 배달 계획과 저장 폴더 표시 줄이 이미 말하던 것이라 세 번째
  발화였다. 그 수치를 정말 다시 물어야 하는 자리는 선택을 파기하는 전이의 확인 모달
  하나이고, 거기는 공유 합성기 `selectionLine`(`js/guard.js`)과 스냅샷 `guard` 축이 계속
  진다 — 그래서 스냅샷의 `restate` 축은 **퇴역**했다(산출·키·`_RESTATE_SAMPLE` 전부).
- **「생성 예정 문서」는 좌 열이다**(`#jobDeliveryZone` — 데이터 그리드와 `#jobResultZone`
  사이): 만들 것과 만들어진 것이 한 열에서 위아래로 읽힌다. 렌더 조건은 작업대 관찰과
  같고(managed hwpx + `supported`), legacy hwpx 의 저장 폴더 표시(`#jobOutDirLine`)는 우
  열 「생성 준비」가 계속 진다 — 두 갈래는 배타라 값이 두 자리에 겹치지 않는다.
- **우 열 「현재 실행 상태」 캡션도 사망했다**: `execution_status_phrase` 는 우상단 상태
  pill 이 managed 갈래에서 그리는 **바로 그 문자열**이라 2중 발화였다. 그 상태를 **바꾸는
  동사**(`#jobResolveExecution`·`#jobRecoverContext`)는 그 자리에 그대로 남는다(blocker
  어포던스 표가 그 좌표를 든다).
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

#### 생성 결과 존의 문서 목록과 산출물 관찰 시트 (S7-03 · #825)

좌 열 `#jobResult` 의 결과 3태 안에서, 이 실행이 **실제로 disk 에 앉힌** 문서를 개별 단위로
나열한다(`#jobResultDocs`). 범위는 **현재 세션 결과**뿐이다(#820 D5 — 원장 되읽기·과거
브라우징은 비범위). 목록의 원천은 결과 dict 의 `delivered` 하나이고, 폴더를 훑어 유추하지
않는다.

- **행 하나**(`#jobResultDoc-<ordinal>`) = 파일명 · 안착 처분 라벨 · 폴더에서 보기/경로 복사
  (`path_actions.ts` 재사용) · 「내용 보기」. 처분 라벨은 확인 면과 **같은 어휘 지도**
  (`DELIVERY_DISPOSITION_COPY`)를 쓴다. 경로 어포던스가 결과 파일을 겨눌 수 있는 근거는
  소유 화이트리스트의 세션 성분 확장 하나다(`JobController.delivered_artifact_paths()` →
  `WebFrontend._validate_owned`): 등록의 원천은 「앱 자신이 그 파일을 냈다」는 사실이고 exact
  대조 판정 자체는 그대로다.
- **「내용 보기」 → `artifact_open {ordinal}`** → 안착 파일 재읽기 + 기록 digest 대조 +
  재파싱(S7-01 커널) → 구조 스냅샷(S7-02) → 읽기 전용 시트 `#artifactSheet`. 열림·대상·판정·
  수치는 전부 Python 소유(`artifact_view` = `{open, ordinal, filename, status, detail,
  structure}`)이고 닫기는 `artifact_close` 무페이로드다. bytes 는 세션이 들고 있지 않으므로
  **매 관찰이 커널 재호출**이다(#820 D1 — 캐시는 관찰 권위가 못 된다).
- **생성 후 실물을 보는 유일한 표면이다**(#820 D4). 생성 **전** 값을 그리던 확인 면
  (`#previewSheet`)은 #957 에서 철거됐으므로 어휘가 갈릴 상대도 없다 — 클래스는
  `artifact-*`, 제목은 '산출물 관찰'(`docs/DOCUMENT_AUTHORITY_LAYERS.md` §1 정준어).
- **네 상태가 각각 다른 문장을 받는다**(#820 §3, fallback·빈 화면 0): `ARTIFACT_FILE_MISSING`
  / `ARTIFACT_DIGEST_MISMATCH` / `ARTIFACT_REPARSE_FAILED` / 세션 좌표 밖
  (`ARTIFACT_NOT_IN_SESSION` — 준비 안 됨과 무결성 실패를 같은 침묵으로 접지 않는다).
  `ARTIFACT_PARTIAL_COVERAGE` 는 거절이 아니라 **병기**다: 관찰은 성립하고 「표시하지 못한
  구간」 구획(`#artifactUnrendered`)이 사유와 구간을 나열한다. 그 구획은 못 본 구간이 없어도
  '없음' 으로 **항상** 선다(#820 D3 — 키째 지우면 완전한 관찰과 부분 관찰이 같아 보인다).
- 시트는 조판·서식을 재현하지 않는다(#360 rhwp 는 별도 트랙): 문단 텍스트와 표(행·열 및
  `cellSpan`/`cellAddr` 병합 메타)와 빈 값 표식 집계까지다.

#### 「포함할 내용」 존의 노출 술어 (U4 13번 · #932)

`#jobContentSelectionZone` 은 **고를 항목이 있을 때만 선다**(사용자 확정 2026-08-30 —
U3 §3(#876) 「확인할 것이 없으면 숨김이 기본」의 적용 확장). slot 없는 작업에서 이 존은
「이 문서 작업에는 선택할 내용이 없습니다.」 한 줄로 영영 서 있었고, 그 줄은 사용자가 확인할
것도 할 것도 아니었다.

- **판정은 Python 한 곳**이다: `application/slot_configuration_projection.py` 의
  `content_selection_zone_actionable` → projection 의 `zone_actionable`. 링2·웹은 읽어 나르기만
  한다 — 웹이 `slots.length` 를 다시 세면 같은 상태를 두 곳이 판정하게 된다(음성 단언이 그
  금지를 진다).
- **`CHOOSE_CONTENT` blocker 가 서는 두 상태**(`NEEDS_SELECTION`·`HAS_BROKEN_SELECTIONS`)는
  술어의 **입력**이다. 그 blocker 의 복구 동사가 이 존 안의 갈래 라디오(`.cs-option-input` —
  `blocker_affordance`)라, 존이 사라지면 「없는 자리를 가리키는 지시」가 된다(#912 결함류).
  오늘 두 상태는 항목 ≥ 1 을 함의하지만 결과가 아니라 술어로 못박는다.
- **실패·거절·직전 왕복 결과의 재진술은 술어가 숨겨도 살아남는다** — 재진술 수명은 웹 소유이고
  (#659), 술어만으로 지우면 방금 겪은 거절이 화면에서 증발한다. `CONTEXT_ERROR` 갈래(복구 동사
  「다시 불러오기」)도 그대로 선다.
- 술어가 거짓이면 React 는 children 을 비울 뿐이라 `.zone` 여백·구분선이 빈 상자로 남는다 —
  `#jobContentSelectionZone:empty`(그리고 같은 이유의 `#jobTplChangeZone:empty`)가 자리째 접는다.
- **귀결(명시 기록)**: 항목 0 건 ∧ 사라진 이전 선택 ≥ 1 이면 `cs-retained-gone` 정보는 말할
  자리를 잃는다. projection 의 detached·retained 축은 그대로 실려 나가므로 되살릴 때는 술어에
  갈래를 더하면 된다.

#### 「포함할 내용」 존의 보관된 선택(Preset) (S9-03 · #829)

`#jobContentSelectionZone` 의 slot 목록 아래 `.cs-presets` 구획이 선택 묶음을 Work **밖**에
보관하고 되불러오는 동사 둘을 연다. 직접 브리지는 늘지 않는다 — 둘 다 dispatch 경로다:
`save_selection_preset {configuration_token, name, confirmed_overwrite_key?}` ·
`apply_selection_preset {configuration_token, preset_key}`. `request_id` 가 없는 이유는 S9-02 가
재전송을 원장이 아니라 이름 유일성 + token version CAS 로 닫았기 때문이다.

- **구획은 둘이고 자리가 다르다**(U4 14~17): **목록**(적용)은 slot 목록 **위**에, **저장**은
  **아래**에 선다. 통째로 올리면 「지금 고른 것을 보관한다」가 고르는 자리보다 앞에 서서 인과가
  뒤집힌다. 술어도 각자다 — 목록은 `preset_command.preset_list_actionable`(보관·손상 → 존의
  `list_actionable`), 저장은 저장 게이트 `has_declared_selection` **그 자체**(→ `save_actionable`).
  목록 건수만으로 저장 구획을 지우지 않는 이유는 「현재 선택을 프리셋으로 저장」이 프리셋을 처음
  만드는 **유일한 입구**이기 때문이다(#932 B5 가 템플릿 존에서 거절한 스위치 트랩) — 보이는
  단추가 곧 이행되는 단추다.
- **끝난 슬롯은 접힌 채 선다**(U4 14~17): 판정은 `slot_settled` 하나(→ `ProjectedSlot.settled`)이고
  「기본 접힘」이지 「접혀 있다」가 아니다. 사용자가 편 상태는 표시 상태라 웹이 소유하고 영속하지
  않으며, **이 세션에서 만진 슬롯은 접지 않는다**(고른 직후 눈앞에서 접히면 U4-A 26번이 고친
  깜빡임이 되돌아온다 — **프리셋 적용이 채운 슬롯도 만진 것이다**, U4-G2 · #945). 접혀도
  **DOM 에서 사라지지 않는다** — `cs-opt-N-M` 은 렌더 순서 기반
  id 라 걸러내면 실주행 대본이 다른 슬롯을 누르고도 초록이 된다. `CHOOSE_CONTENT` 가 겨누는
  상태는 술어의 **입력**으로 배제된다.
- **목록은 스냅샷 존 `content_presets`** 가 낸다(`{supported, list_actionable, save_actionable,
  items[{key,name,created_at}], corrupt[{file_name,error}], corrupt_code, applied_key}`). 지원 조건은
  `slot_configuration` 존과 동형이고, `provenance` 는 내부 정보라 존에 싣지 않는다. **손상 항목은 목록에서 지우지 않는다** —
  비활성 + 사유 병기로 같은 목록에 선다(숨기면 사용자가 묻지도 못한다).
- **`items` 는 현재 템플릿 구조에 「전부 적용 가능」한 것만 싣는다**(U3 §2 · #875). 판정은
  적용 경로가 쓰는 `preset_command.fit_preset_selections` 의 `fully_applicable` 하나이고
  (선언한 slot·option 이 전부 RESOLVED — 부분 겹침은 비호환), 링2 는 어느 Work 를 대고 물을지만
  정한다. 구조를 세울 수 없으면(템플릿 확인 전·context error) 호환을 주장할 수 있는 항목이 0 이다
  — 무필터 전량 노출로 돌아가지 않는다. 걸러진 항목의 저장 파일은 그대로이고(삭제 아님),
  `corrupt` 는 호환 판정의 대상이 아니라 표시 대상이라 언제나 함께 실린다. 목록이 좁혀져도
  적용 경로의 부분 적용·깨짐 보고·거절 코드는 방어층으로 그대로 선다.
- **확인 왕복은 웹이 구현한다**: 이름 입력은 `Modal.prompt`, 이름 충돌(`NEEDS_CONFIRM` ·
  `PRESET_NAME_CONFLICT`)은 `Modal.confirm`(danger). 확정은 backend 가 낸 **그 항목의 key**
  (`existing_key`)를 되돌려 보낸다 — 이름만 다시 보내면 그 사이 그 이름을 차지한 남의 항목을
  덮는다. 근거를 못 받은 확정은 덮기가 아니라 재시도로 착지한다(조용한 덮기 경로 0).
- **수치는 Python 값 그대로다**: 적용 응답의 `applied_count`·`broken_count`·`applied_slot_ids`·
  `broken` 은 S9-02 `PresetApplyDecision` 이 낸 값이고 표면은 「적용 n · 깨짐 m」으로 문장만
  고른다(slot 목록을 다시 훑어 세지 않는다 — 같은 상태의 두 판정 금지). 깨짐 m>0 은 성공 UI
  뒤에 숨지 않고 같은 `aria-live` 줄에서 함께 선다. **적용 0 · 깨짐 0 은 갈래가 다르다**
  (U4-G2 · #945): 「0개를 적용했습니다」는 수치를 문형에 끼운 결과이지 사실의 재진술이 아니라
  「적용된 항목이 없습니다.」로 말한다(수치 판정은 그대로 링1 것이고 웹은 분기만 고른다).
  `applied_slot_ids` 는 문안 재료가 아니라 **접힘 재료**이기도 하다: 그 슬롯들은 「이 세션에서
  만진 것」으로 등재돼 적용 직후 일괄 접힘이 일어나지 않는다(26번 결함류의 프리셋 경로).
- **「지금 어떤 프리셋이 서 있는가」는 상태다**(U4-G2 · #945): 존의 `applied_key` 가 그 단일
  출처이고(`preset_command.PresetListing.applied_key`), 웹은 그 key 의 줄에 **표지만** 얹는다
  (적용 단추의 `aria-pressed`). 판정은 새로 짓지 않는다 — 구조는 목록·적용이 함께 쓰는
  `fit_preset_selections`, 같음은 `apply_selections` 가 NO_CHANGE 를 가르는
  `semantic_selection_equal` 이다. 그래서 표지가 섰다는 것은 「다시 눌러도 아무것도 바뀌지
  않는다」와 같은 말이고, 선택을 손으로 바꾸면 다음 스냅샷에서 내려간다. 같은 내용이 두 이름으로
  보관돼 있으면 목록 순서의 첫 항목이 든다(표지는 언제나 0 또는 1개다). 직전 왕복의 재진술
  (`presetNotice`)과 **다른 축**이다 — 재진술은 사건이라 다음 command 에서 지워진다.
- **적용은 durable S4 mutation** 이라 select/clear 와 같은 규율이다: 생성과 상호배제하고,
  CHANGED 면 자동 확인에 진입하며, 응답의 fresh view + **새 token** 으로 패널을 통째 교체한다.
  거절(`PRESET_NOT_FOUND`·`PRESET_ENTRY_CORRUPT`)이면 새 view·token 이 없으므로 옛 상태를 두고
  사유만 재진술한다. 진단 원문(`detail`)은 사실 서술이라 아는 코드는 웹 문안으로 말한다.
- 삭제·편집·공유·자동 적용은 비범위다(#821 §6).

#### 템플릿 조치 필요 존 (S3-09 #659 · 노출 술어 #932 B5)

side card 의 `#jobTplChange`(`#jobTplChangeZone`) 가 S3 템플릿 권위의 사용자 능력 둘을 연다:
[변경사항 확인](`#jobTplCheck` → `template_check {request_id}`) ·
[변경사항 적용](`#jobTplApply` → `template_apply {change_token}`).

- **존은 조치가 있을 때만 선다**(#932 B5 — U4 12·24 는 한 판정이다). U4 12번의 「변경 0건이면
  숨김」은 그대로는 자기모순이었다: 이 존은 결과 보고판이 아니라 **스위치**이고 건수를 알려면
  확인을 돌려야 하는데 그 확인을 여는 단추가 존 안에 있어서, 건수로 숨기면 확인을 개시할
  방법이 사라진다. 그래서 술어의 입력을 확인 결과가 아니라 **원본 드리프트**로 옮겼다 —
  캡처된 applied bytes 와 현재 원본 파일의 digest 대조라 확인을 안 눌러도 값싸게 안다.
  판정은 `application/template_change_product.template_change_zone_actionable` 한 곳이고
  링2 는 `actionable` 을 읽어 그릴지 말지만 정한다. **세우는 갈래**: `initialization_required` ·
  미종결 preparation(`ready`·`checking` + `_UNSETTLED_PREPARATION_STATUSES` 여섯) ·
  드리프트 `changed`/`unknown`. 나머지 하나(준비를 마쳤고 원본 그대로이며 확인도 종결)에서만
  숨는다. **드리프트 3상태**에서 `unknown`(값싸게 못 구함)은 「없음」으로 접지 않는다 — 접으면
  읽지 못한 파일이 「변경 없음」으로 통과해 존이 조용히 사라진다.
- **재진술 클로즈는 웹 소유**: 적용이 성사되면 드리프트가 0 이 되므로 술어만으로는 「변경사항을
  적용했습니다」가 존과 함께 증발한다. 재전송·재진술 수명은 웹이 지므로(아래) 그동안은 세운다.
  그 자리의 존 이름은 「템플릿 변경사항」이고, 조치가 실제로 남은 자리에서만 「템플릿 조치
  필요」다 — 방금 끝낸 일을 다시 시키는 이름을 쓰지 않는다.
- **숨김이 연 창은 두 층이 닫는다**(#932 B5). 앱 밖 편집(한글에서 템플릿 수정)은 push 를
  내지 않으므로, 조치가 있을 때만 서는 구획은 다음 상호작용까지 침묵한다. ⑴ 창 **포커스
  복귀**가 현재 화면을 다시 묻는다(`shell/app.ts` 의 서술 → ShellHost 가 부착; 주기 검사가
  아니라 사용자가 돌아온 순간 한 번이라 유휴 비용 0, 실패는 삼킨다 — 갱신은 편의이지
  계약이 아니다). ⑵ 그 갱신을 놓쳐도 드리프트가 **실행 게이트**로 선다
  (`workbench_template_change_verdict` 가 `changed`·`unknown` 에 `REVIEW_REQUIRED`) — 생성은
  캡처된 bytes 를 쓰므로 막지 않으면 「검토한 편집분이 반영 안 된 문서」가 조용히 나온다.
  막되 좌초시키지 않는다: 이 blocker 의 복구 동사(`#jobTplCheck`)는 **같은 판정이 세우는**
  존 안에 있어, 지시와 수단이 함께 서는 것이 구조로 보장된다.
- **최초 준비는 착석이 진다**(#932 B5): 「변경사항 확인」은 lazy bootstrap 을 겸직했고, 나중에
  선 「포함할 내용」 구획이 자기 트리거 없이 그 겸직에 얹혀 교착을 만들었다(구간 ← 준비,
  생성 ← 구간, 준비 ← 생성). 준비는 이제 `job.select_job` 이 부르는
  `TemplateChangeCoordinator.ensure_bootstrapped` 가 진다 — **명령 경로**이지 스냅샷이 아니다
  (렌더가 durable id 를 발급하는 write-on-read 금지는 그대로다). 거절은 삼키지 않는다:
  durable 실패 기록이 남고 이 존이 비활성 + 진단으로 재진술하며, 같은 실물로는 되돌지 않는다.
- **opaque Product Contract**: 스냅샷 존 `template_change` 는 capability(`supported`·`reason`·
  `checkable`)·노출 술어(`actionable`)·드리프트(`source_drift`·`source_drift_note`)·`epoch`·
  현재 Preparation view(`preparation_token`/`status`/`change_token`/
  `diagnostics`/`prepared_at`)만 싣는다. **모든 갈래가 같은 키 집합**을 낸다(키 부재 분기
  금지 — 표면이 키 유무로 갈리면 갈래 하나가 빠졌을 때 존이 조용히 사라진다). revision 번호·목록·선택기·내부 ID(경로·evidence·
  profile·base)는 DOM 에 없다. status 어휘는 생성 계약(`contract.gen.ts` 의
  `TEMPLATE_PREPARATION_STATUSES`·`TEMPLATE_APPLY_STATUSES`)이 정본이고 판정·token 발급은
  코디네이터(`webapp/template_change.py`) 소유다 — 표면은 문안과 재전송 규율만 가진다.
- **재전송 규율**(웹 소유): 진행 중 중복 클릭은 같은 요청으로 수렴, 전송 실패로 남은 키는
  같은 키로 재전송, 성공 뒤 클릭만 새 `request_id`(=새 prepare intent). `change_token` 은
  `ready` 에서만 실리고 새 확인이 시작되면 스냅샷 교체로 이전 적용 버튼이 사라진다.
- **비활성 + 사유 병기**: HWPX 아닌 작업·템플릿 미연결은 존이 명시적 unsupported, bootstrap
  실패(`initialization_required`)는 확인 버튼 비활성 + 진단 병기이고 템플릿 실물이 바뀌면
  재확인이 열린다. `invalid` 는 Candidate 유래 진단을 재진술하며 기존 템플릿이 계속 쓰임을
  말한다(조용한 fallback 금지).
- **거절 재진술**(#804): `template_check` 는 실패해도 예외가 아니라 종결된 판정
  (`{"ok": false, "reason": …}`, 필요하면 `error` 문장 동반)을 돌려준다. 표면은 그 응답을
  **반드시 읽고** 구획 재진술(`#jobTplNotice`)과 알림 채널에 함께 착지시킨다 — 좌석이 풀리는
  거절(`work_context_changed`)은 존 자체가 사라지므로 알림이 유일한 채널이다. `error` 가
  실려 오면 그것이 정본이고, `initialization_required` 문안은 존 상태 문안과 **같은 상수**를
  쓴다(웹 단일 출처 `TPL_INITIALIZATION_REQUIRED_COPY`). 표에 없는 사유도 비우지 않는다.
- **좀비 권위 금지**(#804): 초기 등록(bootstrap)에 실패한 호출은 **그 호출이 방금 발급한**
  `authority_id` 를 되돌린다(이전부터 있던 권위는 불가침). 그래서 「권위는 있는데 Work 상태
  집합은 없다」가 남지 않고, 「포함할 내용」 존은 `CONTEXT_ERROR` 막다른 길 대신 복제 직후와
  같은 미초기화로 접힌다 — 안내는 실패 기록을 든 이 존 한 곳이 진다. 규율의 적용 범위는
  **bootstrap 을 하는 경로 전부**다: 확인(`check_for_seated_context`)과 생성
  (`resolve_generation_template`)이 같은 use case(`seat_job_authority_id` 의 발급자 판정 →
  `release_job_authority_id` 의 compare-and-clear)를 공유한다. 한쪽만 닫으면 같은 막다른
  길이 다른 문으로 다시 열린다.

#### 전체 표시순서 축 (F3 — 지도 §10.11)

표 머리의 스위치 `#jobOrderToggle` 이 계약 §18.10 의 `viewOrder` 를 사용자 축으로 연다
(`sourceDesc`=최신 행 먼저 / `sourceAsc`=원본 순서, 2값 고정). **U4 7번에서 `<select>` 를 걷고
표 머리로 옮겼다** — 요구는 기본값이 아니라 컨트롤의 시각 비중이었고, 기본값 `sourceDesc` 는
그대로다(#295 결정 1 「원본 순서 보존」은 그 라운드에서 낡은 판정으로 폐기됐다).
기본값에서 벗어난 상태만 `aria-pressed` 로 서고, 2값이라는 사실은 `data-order-values` 선언이
진다(`<select>` 의 `options` 가 지던 계약의 승계 — selftest `view_order` 프로브가 되읽는다).
라벨은 「⇅ 정렬 순서」다. 종전 축 옆에 서던 상시 재진술 줄(`#jobOrderBar`/`#jobOrderNote` +
스냅샷 키 `order_note`)은 **간소화 라운드에서 걷혔다** — 표가 그리는 순서가 곧 생성 순서라는
사실은 스위치 자신의 `title` 이 진다.

- **소비처는 하나의 훅**(`_display_indices`)이다: 표·필터 밖 선택 스트립·실행 입력·파일 이름
  계획이 전부 이 투영을 통과한다. 어느 하나가 원본 순서로 남으면 「보이는 것 = 만들어지는
  것」이 거기서만 깨진다.
- 축은 **데이터 귀속**이다 — 새 데이터·시트 교체는 `sourceDesc` 로 되돌리고(불변식
  §18.11-13), 개인화 설정으로 승격하지 않는다. 작업 선택은 축을 건드리지 않는다(§18.11-23).
- 순서 변경은 **선택 집합을 바꾸지 않는다**(투영 대 집합). 바뀌는 것은 생성 순서와 그 함수인
  파일 이름 순번이다. 확인 왕복은 두지 않는다 — **근거가 U4 8번에서 갈렸다**: 종전 근거는
  「표 「문서」 열이 새 이름을 즉시 보여준다」였는데 그 열이 걷혔다. 지금 근거는 이름이 **그
  왕복에 들어갈 가치가 있는 정보가 아니라는 것**이다(사용자 확정 2026-08-30). 이름을 대조할
  자리는 「생성 예정 문서」 존(`#jobPlannedDocuments`) 하나다. 종전에는 이 사실을 축 옆
  상시 문안이 말했으나(순번 절은 규칙이 `{{seq}}` 를 쓸 때만 붙었다) 그 줄은 간소화 라운드에서
  걷혔다 — 남은 자리는 스위치의 `title` 이다.
- ⤢ 펼침 면과 인라인은 **같은 컴포넌트의 두 마운트 지점**이고 `ui.sheetOpen` 이 한쪽만
  그린다(복제 금지 — 상태가 둘로 갈린다). 종전 서술의 「같은 요소가 **이동**한다」는 R4 이전의
  실 DOM 이동 기계를 가리킨 것이고 그 기계는 걷혔다(`surface_sheet.js` 머리말) — 지금은 한쪽이
  언마운트되고 다른 쪽이 마운트된다. 왕복 중에는 방금 고른 값이 이기고(`pendingOrder`), 실행
  거동은 selftest `view_order` 프로브가 지킨다.
- **「펼쳐서 행 고르기 ⤢」의 진입점은 표 머리다**(U4 10번) — 표를 여는 동사라 표를 다스리는
  줄에 선다. 옮긴 것은 진입점뿐이고 초안 거래(§18.11-21)와 면 수명주기는 그대로다. 면 안에서는
  그 단추를 그리지 않는다(자기 자신을 여는 단추는 무동작이고, 닫는 동사는 footer 가 진다).
  트리거가 언마운트되는 표면 안으로 들어왔으므로 **닫힘 뒤 초점은 살아 있는 같은 단추로**
  되돌린다 — 저장된 노드는 그때 이미 죽어 있다.
- **선택 동사는 그 열의 머리에 있다**(U4 11번): `th.doccol` 의 체크박스(`#jobSelAll`)가 3상태로
  서고, 눌리면 전건이면 해제·아니면 선택이다. 3상태는 **보이는 행** 기준이다 — 필터가 켜지면
  `set_all` 이 매치만 가산하므로 전체 레코드로 재면 다 골라도 「일부」로 남는다. 해제가 필터 밖
  선택까지 지운다는 사실은 그 컨트롤의 이름이 진다. **행 체크박스와 동사가 다르다**: 행은
  표지 전용(`pointer-events:none`)이고 행 전체가 동사이며(넓은 표적·이중 토글 방지), 머리는
  누를 행이 없어 체크박스 자신이 동사다.

#### 전문 범위 편집기 = ⤢ 펼침 면 + 초안 거래 (F3 — 지도 §10.11)

「펼쳐서 행 고르기 ⤢」는 계속 실 DOM 을 옮기는 `SurfaceSheet` 면이고(별도 화면 신설 없음),
**의미론만** 새것이다 — 면 안의 편집은 초안(`RecordRangeDraft`)으로 격리된다.

- 초안은 **Python 소유**다. 존 13액션은 이름 그대로 초안을 향하고(같은 동사, 다른 대상),
  경계는 믹스인의 훅 4개(`_zone_sel`·`_zone_flt`·`_zone_set_flt`·`_zone_visible`)에 한 번만
  적힌다. 기본 구현이 커밋 상태를 돌려준다(존 소비 화면은 이제 이 화면 하나다 — F6 PR-B).
- 스냅샷 이중 소스 경계: **초안** = 표·필터·칩·필터 밖 스트립·footer 수치·표의 실
  파일 이름 / **커밋** = 실행 입력·게이트·사전검증·후보·세션 가드·직전 필터 슬롯. 적용 전 메인
  범위는 불변이다(불변식 §18.11-21).
- footer(`#jobRangeFoot`)는 **화면 DOM 소유**이고 면 슬롯 안에서만 보인다(CSS — 면 공유자
  「기안」은 사망했지만 슬롯 격리 규율은 그대로 산다). 구성 = 「선택된 항목만
  보기」(초안 전용 보기 상태로 적용 대상 아님) · 「취소」 · 「선택 적용: N건」. 종전 맨 앞에
  서던 상태 문안(`#jobRangeNote`)은 간소화 라운드에서 걷혔다 — 보기 범위는 「선택된 항목만
  보기」의 `aria-pressed` 가, 적용 전임은 「선택 적용」 단추 자신이 말한다.
- 출구는 **한 관문**을 지난다: 취소·닫기·Escape 전부 `beforeClose` 가드를 통과하고, 변경이
  있을 때만 확인을 묻는다(「버리고 닫기」 / 「계속 편집」). 3택을 두지 않는 근거는 「적용」이
  면 안의 상시 버튼이라는 것 — 가드가 세 번째 선택지를 새 기제로 만들 필요가 없다.
- 열기는 **성사 뒤**다: 초안 생성이 거절되면(데이터 없음·생성 중) 면을 띄우지 않는다. 적용
  실패(스냅샷 세대 불일치)에서도 면을 닫지 않는다 — 문맥을 남긴다.
- 초안이 열린 동안 생성은 잠긴다(버튼 비활성 + Python 거절). 잠금은 DOM 이 아니라 상태가
  진다 — 모달에 가려 못 누르는 것과 잠긴 것은 다른 사실이다.

#### 검토 고지와 파괴 확인 (F5 승계 — #957 정책 선회)

**생성 값 미리보기 표면은 없다.** `#previewSheet` 시트·`job_preview.ts`·5 액션
(`preview_open`/`close`/`move`/`blank_only`/`approve`)·승인 상태(`ReviewState`)·「승인 필요」
표지(`#jobReviewFlag`)·두 출구(`#jobMirrorPreviewOpen`·`#jobManagedPreviewOpen`)가 전부
철거됐다(슬라이스 ③). 되살리려는 변경은 아래 판정을 먼저 뒤집어야 한다.

- **검토는 게이트가 아니라 고지다**(#957 — 신뢰 정책 선회). `docs/UX_FEEDBACK_U4.md` §34
  「빈 값도 확인하면 생성 허용 — 게이트 유지 확정」의 **명시적 뒤집기**이고, U4 문서는 역사
  기록이라 고치지 않으므로 승계 진술은 여기다. 새 정책은 한 줄이다: **이상이 있으면 알려주되
  생성을 막지 않는다** — 사용자가 만들어진 문서를 한 번 더 본다. 그래서
  `plan_generation` 에 검토 판정기 선언이 없고(`review_check`·`PlanDecision.review_unmet`
  사망), `_compose_gate` 에 검토 단이 없으며(`reason="review_required"` 사망), 실행 백스톱도
  없다. 남은 차단은 **구조 가드**뿐이다: 드리프트·미해소 파일명 토큰(danger)과 데이터 결속·
  저장 폴더·선택 0건(warn).
- **승인이라는 사건이 없다.** `docs/core-workflow.md` §13 불변식 2·3·4
  (「정상 반복 실행에서 미리보기는 선택이다」·「새 문서 작업…은 결과 확인 전 실행을 차단한다」·
  「PreviewCreated 와 PreviewApproved 는 다른 사건이다」)와 그 상태기계의 `PreviewRequired`/
  `PreviewCreated`/`PreviewApproved` 전이는 **퇴역**했다 — 그 문서는 부분 대체 상태의 계약
  원문이라 고치지 않고 승계 진술은 여기다.
  요구를 해소하는 상태가 없으므로 스냅샷 `review` 구획은
  `approved` 키를 싣지 않는다(언제나 거짓인 필드는 표면을 거짓으로 갈라 놓는다). 남는 것은
  요구의 사실뿐이다: `required`·`risk`·`targets`·`first_run`·`unknown_baseline`·
  `structure_changed`.
- 검토 요구(`ReviewRequirement`)는 규칙의 **대상별 지문**과 마지막 완주가 남긴 기준선
  (`Job.reviewed_rules`)의 차이다. 위험은 파일명 집합 > 의미 연결 > 표시형이고, 템플릿 변경은
  드리프트 게이트가 진다. 소비처는 **사전검증 고지 하나**다: `refresh(review_notice=…)` →
  `_compose_preflight` 가 `review_notice_text` 로 「[알림] …결과 문서를 열어 확인하세요.」
  한 줄을 세운다(`long_paths` 와 같은 비차단 선례). 고지는 **등급을 올리지 않으므로**
  (`PreflightResult.level` 은 `ok` 그대로) 별도 축 `PreflightResult.notices` 로도 실린다 —
  링2 가 통과 문구로 갈아끼우는 자리에서 고지가 조용히 사라지지 않게.
  **첫 실행(`first_run`)은 고지 대상이 아니다**(사용자 판정, 간소화 라운드 — `blank_set` 과
  같은 빈 문자열): 결과 문서를 열어 확인하는 것은 첫 실행이든 아니든 상수라 「첫 실행입니다」가
  바꾸는 행동이 없다. 판정과 스냅샷 키는 그대로 산다 — 그 갈래가 없으면 첫 실행이 일반
  문안으로 새어 없는 「마지막 실행」을 말한다. 남는 고지 공급원은 `unknown_baseline` 과
  규칙 변경 둘이다.
- **빈 값은 막지 않고 표식으로 남는다**(§2.13 침묵 금지의 #957 판본): 표식
  (`MISSING_MARKER` = `〘미입력·{field}〙`)이 문서에 박히므로 조용한 통과가 아니다. 그 사실을
  말하는 자리는 셋이다 — 사전검증 「[경고] 빈 값 필드」·문서 안의 표식·완료 요약의 「빈 값 표시
  필드 N개(…)」. `blank_set` 위험은 요구로는 그대로 서지만 **고지 문안이 없다**
  (`review_notice_text` 가 빈 문자열): 같은 사실을 한 면에 두 줄로 세우지 않는다. 표식 조건은
  「빈 값이 있으면」 하나로 단순하고(`_run_marker` — 표시와 생성의 단일 술어), 구 필드축
  ack(`ack_field`·`unack_field`·거울 클릭=확인·UD-19 재클릭 토글·가드의 `ack_count`)는
  전부 사망했다.
- **관리 경로도 같은 처분이다**: `record_validation` 은 행 안의 빈 값(explicit null·빈/공백)을
  blocker 가 아니라 **미입력 표식**으로 resolve 하고, 그 사실을 비차단 `advisories` 축
  (`MISSING_VALUE_MARKED:{field_id}` — VDR provenance, identity 밖)으로 나른다. 표면은
  `#jobRecordValidationAdvisory` 한 줄(「빈 값 N칸이 있습니다. 문서에는 미입력 표식이
  들어갑니다.」)이고
  blocker 목록(`#jobRecordValidationIssues`)과 **다른 키·다른 줄**이다. 표식 문구는 두 경로가
  같은 입력에서 같아야 하므로 legacy `mark_missing_values` 와 같은 상수·같은 키
  (매핑 키 = Plan `field_id`)를 쓴다. 남는 blocker 는 **열 누락**
  (`RECORD_REQUIRED_VALUE_MISSING`)류다 — 행의 결핍이 아니라 데이터↔작업 결속의 구조 결함이라
  표식으로 덮으면 잘못된 결속이 조용히 출하된다. 구 `RECORD_EXPLICIT_NULL_NOT_ALLOWED`·
  `RECORD_BLANK_POLICY_VIOLATION` 은 **퇴역**했다.

##### 파괴 확인 = `generate` 의 `needs_overwrite` 왕복 (legacy·managed 공용)

**앱이 이미 있는 파일을 지우는 유일한 확인 왕복**이고, 두 실행 경로가 **한 자리**를 쓴다.

- 같은 이름이 있으면 덮어쓰는 것이 기본이고(`DEFAULT_COLLISION_POLICY`) 「충돌 처리」
  선택기도 「목록 새로 확인」도 화면에 없다(U4 §2-27·2-28). 확인을 세우는 것은 정책 의도가
  아니라 **이번 계획의 처분**이다 — `WRITE_OVERWRITE` 인 항목이 하나라도 있으면 첫 생성 호출이
  아무것도 쓰지 않고 되돌아온다.
- 응답 키는 한 벌이다(`_needs_overwrite_result` 단일 출처): `needs_overwrite`·`total`·
  `overwrite_count`·`new_count`·`conflict_names`(최대 10)·`conflict_more`, 그리고 모든 갈래에
  실리는 `run_token`. **문안은 웹 소유**다 — `job_run.ts` 의 `overwriteBody` 가 이 수치로
  본문을 합성하고 `Modal.confirm` 이 그 왕복을 그린다(판정·수치는 Python, 확인 UI 는 웹).
- 확인은 **그 배치에 대한 동의**이지 예약이 아니다. 재호출은 같은 시각으로 다시 계획한다:
  `needs_overwrite` 를 낸 판정이 쓴 시각을 `_overwrite_now_pin` 이 세대 키(작업·데이터·
  스냅샷 세대·존 epoch·선택·sealed basis digest)와 함께 붙들고, 확인 재호출이 **소비하며
  소거**한다. `{{date:SS}}` 류에서 이 핀이 없으면 확인창이 재진술한 파괴 집합과 실제 파괴
  집합이 초 경계에서 갈려 확인창이 거짓말이 된다.
- 왕복 사이에 세대가 갈리면(존 변이·선택 변경·데이터 교체·작업 전환) 그 확인은 **낡은
  확인**이라 거절한다 — 조용히 새 배치에 적용하지 않는다. managed 갈래는 그 위에 sealed
  basis digest·prep 캐시 검사가 함께 서서, 확인창이 말한 목록과 실행기에 넘어가는 목록이
  같은 객체에서 나온다.
- **날짜 토큰 시각은 두 축이다**(#957): 표시는 **스냅샷당 1회** 캡처(`_names_now` — 한 스냅샷의
  게이트 감사·표 「문서」 열·이름 계획이 서로 맞는다), 실행은 **런 진입 시 1회** 캡처(한 런의
  이름·본문·충돌 판정이 한 시각). 두 축이 갈리는 것은 결함이 아니다 — 확인의 자리가 만들어진
  문서로 옮겨졌기 때문이고, 갈리면 안 되는 유일한 구간이 위의 확인 왕복이다.

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
- **검토 요구는 배제 선언**: TXT 엔 파일 이름 축이 없고(§3.2) 작업대가 이미 레코드 전수를
  채운 모습으로 보여 주는 검토 표면이라, 같은 확인을 두 표면이 겸하지 않는다.
- **구간 표기가 있으면 복사는 물질화 산출이다**(S10-04 · #861). 화면의 접기는 **투영**이고
  투영은 실행 권위가 아니다 — 그대로 내보내면 고르지 않은 선택지와 마커 텍스트가 붙여넣어
  진다. 그래서 `copy_to` 는 「포함할 내용」 선택을 봉인한 Sealed Plan 으로 레코드를 물질화해
  그 bytes 를 복사한다(제거 → 마커 소거 → 치환, 단계마다 재스캔 후행조건). 봉인·검증이 서지
  않으면 **그 사유가 곧 복사 차단 사유**이고, 화면 문장과 물질화 산출이 갈리면(저장하지 않은
  연결 편집·전각 정렬) 조용히 한쪽을 내보내지 않고 거절한다. 물질화는 컨트롤러 생성자
  주입 포트다 — 작업대는 봉인·VDR·start gate 의 형체를 모른다(`content_selection` 과 같은
  규율). 마커 0(slotless)이면 이 경로를 **타지 않고** 기존 카드 렌더 그대로다.
- **세션 텍스트는 줄 끝을 원문 그대로 든다**: universal newline 으로 읽으면 CRLF 템플릿이
  화면에서 LF 로 접혀, 물질화 산출(Candidate bytes 그대로)과 갈린다. 「보이는 것 = 복사되는
  것」이 사용자가 고칠 수 없는 사유로 거짓이 되지 않게 읽기를 원문에 맞춘다.

#### 생성 결과 = 3태 구획 (F4 — 지도 §10.10)

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
  식별 요약은 필터 밖 선택 칩과 같은 링1 판정(`identity_summary`)이다. 표에서 그 행을 되찾는
  길은 U4 8번 뒤로 **요약의 성분**이다 — 표가 원본 열을 그대로 보여주므로 요약을 이루는 값으로
  찾는다(행 앵커 `#jobResultFail-<index>` 는 index 기반이라 그대로 산다). 아는 원인이 없는 실패에만 **「원인 진단 미연결」**(계약 §10.3)이
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
  추종한다). 어느 처분도 흔적 줄을 남기지 않는다 — 자동 초기화에 딸리던 **퇴장 한 줄**은
  실행 기록 상자와 함께 퇴역했다(#957).
- 결과 행동의 **주체 판정은 스냅샷이 낸다**: 직전 런의 주체는 세션 상태(`last_run_job`)가
  들고 이름 변경을 같은 전이에서 추종하며, 표면은 `last_run_job === job_name` 두 Python
  값만 비교한다(정체를 표면이 보관하지 않는다). 주체가 아니면 증거는 남기고 행동 2종
  (파일 이름 규칙 수정·실패한 N건만 선택)만 걷는다 — 강등된 결과의 행동이 지금 열린 작업을
  겨누면 남의 작업을 편집하거나 확실한 무동작이 된다.
- `generate` 는 dispatch 밖이라 자동 push 가 없다 — 런이 끝나면 컨트롤러가 스냅샷을 한 번
  흘린다(주체·완주 스탬프). 덮어쓰기 확인 왕복에는 밀지 않는다.
- **실행 기록 상자는 없다**(#957 — `#jobRunLog`·`#jobRunLogLast`·`#jobGenLog` 퇴역):
  접힌 상자 안의 한 줄은 실패를 보이게 하는 자리가 아니었다. 착지는 둘로 갈렸다 —
  **실패·거절은 알림 채널(`deps.notify`)**, **성공은 무착지**(그 사실을 이미 보이는 자리가
  결과 구획·저장 폴더 칸·데이터 라벨·표의 선택 수다). 능동 취소도 무착지다(방금 취소를
  고른 사람에게 취소를 되돌려 주지 않는다). 결과 사건은 그대로 3태 구획이 진다.

### `job` 화면의 세션·결속 계약 (U4 §2.4 재판정 — data-first 봉합 승계)

`JobController` 는 마운트된 데이터(`datasource`·`records`)·선택(`SelectionModel`)·필터를
**세션(컨트롤러) 소유**로 보유한다. 배경은 `docs/archive/DATA_FIRST_INTEGRATION_MAP.md`
이지만 **방향 판정은 이 절이 승계한다** — 그 동결 문서가 세운 「데이터-우선」 전제는
`docs/UX_FEEDBACK_U4.md` §2.4(#932 U4-C)가 뒤집었고, 동결 문서는 고치지 않는다.

- **작업은 데이터를 durable 로 든다**(`Job.data_path`·`data_sheet`·`data_header_row`·
  `data_kind` — 마운트 시점에 **한 벌**로 포획한 참조, 링0 접근자는 `data_binding_of`).
  이것이 작업↔데이터의 **유일한 관계**다: 스키마 호환을 후보 축으로 병존시키지 않는다.
  쓰는 자리는 **편집기 저장 하나**다.
  네 번째 성분이 종류인 이유는 같은 경로 문자열이 두 뜻을 가질 수 있기 때문이다(#937):
  `""` = 엑셀/CSV, `"pclm"` = 계약 목록(pclm SQLite 계약면). 계약 목록은 **같은 자리를 다른
  이름으로** 쓴다 — `data_path`=db 파일, `data_sheet`=뷰, `data_header_row`=0(계약면에는
  헤더 행 축이 없어 0 이 곧 「해당 없음」). 종류를 흘리면 결속 판정(`data_binding_matches`
  의 kind 선판정)이 db 를 가리키는 결속을 같은 경로의 엑셀 마운트에 조용히 맞춘다.
- 데이터 마운트(`pick_data_file`→`load_data_path`, `load_data_sheet`, `load_pool`)는 **작업
  미선택에도 허용**되고, 마운트 직후 선택은 **0건**이다. `load_pool` 의 겨눔은 풀 **슬롯
  키**(`key`)다(#347, U2 §5.3 — 이름은 중복 허용 라벨이라 겨눔의 정체가 못 된다). 다만
  작업의 결속이 드는 것은 슬롯 키가 아니라 그 슬롯이 **가리킨 파일 참조**다: 슬롯은
  「다시 연결」로 내용물이 갈리는 가변 개체라 작업이 그것을 들면 표시와 시작이 갈린다.
  슬롯이 가리키는 참조의 포획은 `screens.pool_reference_quad` 한 자리이고 엑셀(`path`)과
  계약 목록(`db`) 둘 다 파일을 가리키므로 `data_path` 를 채운다.
- **세션 소스 축(`data_source`)은 넷이다**: `""`(미겨눔)·`file`·`pool`·`pclm`. 병기 라벨은
  저장하지 않고 `screens.source_label` 이 매번 합성한다(미지 플래그는 loud raise). 축이
  가르는 것은 **정체**이지 종류가 아니다 — 풀 슬롯이 계약 목록을 가리키면 축은 `pool` 로
  남고 `data_kind` 만 `"pclm"` 이 된다(슬롯을 잃으면 재마운트가 무엇을 다시 읽을지 모른다).
  `pclm` 축은 슬롯 없이 서는 마운트(작업 결속·부팅 기억)의 것이다.
- 계약 목록이 서는 길은 셋이고 전부 **기존 seam 위**다: ① 풀 겨눔(`load_pool` — 위 quad
  포획) ② 작업 결속(`_mount_job_binding` → `_mount_by_kind` 가 종류로 갈래를 가르고, 이름
  없는 종류는 시끄럽게 거절한다) ③ 부팅 복원·재마운트(`_mount_remembered_data`·
  `remount_data` → `_mount_pclm`). 마운트 몸통 `_mount_pclm` 은 `load_data_path` 의 **자매**로
  같은 순서(생성 중 거절 → 읽기 → 직전 필터 스태시 → 전이 판정 → 성분 한 벌 → 소스 키 →
  범위·필터 재생성 → 기억 → 푸시)를 밟고, 소스는 링1 리졸버(`resolve_pool_source`)와 주입
  factory 를 지난다(링2 가 구체를 재선택하는 뒷문 금지). 소스 일치 키(`_data_key`)는
  `pclm:` 접두 + 정규화 db + 뷰라 같은 경로의 엑셀 마운트와 섞이지 않는다(결정 28).
  부팅 기억(`settings.last_data_source`)은 출처 축이 종류를 말하므로 종류를 따로 싣지 않고
  파일 갈래와 같은 성분(`path`=db·`sheet`=뷰)을 쓴다.
- 스냅샷 `data_target` 은 `{path, sheet, origin, kind}` 다. `kind` 는 `sheet` 자리가 **무엇을
  뜻하는지**(엑셀=시트 / 계약 목록=뷰)를 표면에 넘긴다 — 표면이 경로 모양으로 되추측하면
  같은 상태를 두 곳이 판정한다. 「이 데이터 고정」의 가부는 종전대로 `origin == 'file'`
  하나가 가른다 — 등록 데이터는 이미 고정된 참조이고, 계약 목록의 등록은 데이터 선택 면의
  전용 동사(`register_pclm`)가 진다.
- **`select_job` 은 그 작업의 결속 데이터를 세운다**(`_mount_job_binding`). 이미 그
  데이터가 서 있으면 아무 일도 하지 않는다 — 아무것도 바꾸지 않는 재읽기가 선택·필터를
  지우는 것은 그 자체로 조용한 파기다. 다른 데이터면 마운트하고, 초기화되는 것(선택·필터·
  열 선별)을 `data_notice` 로 재진술한다. 결속이 **없는** 구판 작업은 조용히 지나가고
  「데이터 연결 필요」는 게이트가 말한다(같은 상태를 두 곳이 판정하지 않는다).
  종전 계약(*"작업 선택은 데이터를 세우지 않는다"*, #347)은 이것으로 대체됐다.
- **결속 부재는 작업 사실이라 실행을 막고, 고칠 자리를 가리킨다.** 링1 게이트가
  `data_unbound` 로 세우고(단: danger 뒤·세션 전제조건 앞 — 고칠 자리가 이 화면이 아니다)
  작업대 blocker 는 `CONNECT_DATA` 다. 판정은 착석 시점 한 자리(`job_data_unbound`)이고
  복구 동사 `#jobConnectData` 가 데이터 머리에 함께 선다 — 게이트가 「현재 데이터」 구획을
  지목하므로 눈이 닿는 자리가 거기다. 라이브러리는 같은 사실을 행 배지·상세로 미리 말한다.
- 데이터·선택·필터는 여전히 **세션 소유**라 vm 재생성에서 생존하고, 잃는 것은 실행
  증거(완주 담보)뿐이다. 구 T1 스위치 가드(`needs_confirm`/`switch_job`)는 파괴가
  사라져 함께 죽었고 되살아나지 않았다.
- **데이터를 갈아 끼우면 결속이 안 맞는 작업은 놓아 준다**(`ActiveWorkContext.
  `bound_to_current_data` → KEEP/RELEASE). 판정 축이 「이 데이터로 쓸 수 있나」에서
  「이 작업이 이 데이터를 쓰나」로 갈렸다 — 호환은 우연히 맞을 수 있고, 우연한 일치로
  남의 데이터를 물린 채 실행에 들어가는 것이 이 재판정이 없애는 어긋남이다.
- 스냅샷은 데이터 준비 시 `candidates`(**이 데이터에 결속된** 작업 후보)를 싣고, 작업
  미선택 게이트는 링1 `prework_gate` 산출을 그대로 렌더한다(링2 문안 재조립 금지).
  후보 집합의 1차 관문은 링1 `bound_jobs` 이고, 그 안에서 §18.4 호환 판정
  (`compatibility_for`)이 계속 available/needs 를 가른다 — 결속된 파일의 열이 사라지는
  일은 여전히 일어나고 그때 조용히 목록에서 빠지면 사용자는 사유를 못 듣는다. 새 데이터를
  처음 마운트하면 후보 **0건**이 정상이고, 그 자리는 「＋ 이 데이터로 새 작업」이 진다.
  다른 데이터에 결속된 작업으로 가는 길은 이 존이 아니라 「문서 작업」 화면이다.
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
  자모 부분일치(`domain.jamo`)다. 탭 건수는 **검색 전** 값 — 탭 라벨은 데이터에 대한 사실이다.
  액션 `browse_tab`(`tab`)·`browse_query`(`text`). 탐색 면도 후보 줄과 **같은 결속 관문**을
  지난다 — 한 화면의 두 목록이 서로 다른 관계를 말하지 않는다(#932 U4-C).
- **탐색 면의 클릭 목적지는 사유가 가른다**(U2 §4 판정 E, #349 — §18.7 6분기 중 이 둘만
  짓는다). 「확인 필요」 행(= 데이터 구조 불일치, master `needs_action` 의 유일 원인)은
  없는 열을 열거한 채 **새 작업 마법사**(`new_job_from_data`)로 가고, 템플릿 부재는 후보
  카드의 「연결 상태」 축에서 **재연결**로 간다(#342 의 자리 그대로). 나머지 넷은 짓지
  않는다: 1은 실행 게이트가, 2·3은 데이터 축이 이미 풀고, 5는 후보 목록의 정체를 바꾸는
  별개 결정, 6은 계약이 리다이렉트를 금지한다. 같은 마법사의 다른 입구가 후보 줄의
  「＋ 이 데이터로 새 작업」(`#jobCandNewWork`, §2.4)이고 **흐름 몸통은 하나**다.
- 그 입구의 **가부·참조는 한 판정**이 낸다 — `DataZoneMixin.new_work_handoff()` 가
  `({path, sheet, header_row, kind}, "")` 또는 `({}, 사유)` 를 돌려주고, 스냅샷 `new_work`
  (`{can, reason}`)와 브리지 `new_job_from_data` 가 **같은 값**을 읽는다. 표면이
  `data_target.path` 유무로 유추하면 「누를 수 있다」고 그려 놓고 백엔드가 거절한다
  (#349 리뷰 1R: `_do_load_pool` 은 엑셀 참조에만 `data_path` 를 채운다 — 그 값은
  로케이트·고정 프리필의 것이다). 참조를 경로로 줄이지도 않는다: 등록 데이터의
  `header_row` 를 떨어뜨리면 마법사가 **다른 헤더**에 앵커를 건다. `kind` 도 같은 근거로
  함께 간다(#937) — 받는 쪽(`EditorController._load_source_ref`)이 그 값으로 해석기를
  가르고, 이름 없는 종류는 파일 갈래로 흘려보내지 않고 시끄럽게 거절한다. 파일로 다시 열
  수 없는 마운트(조립 파이프라인)는 버튼을 숨기지 않고 **비활성 + 사유 병기**로 거절한다.
- 그 참조는 **마운트 성사 시점에 포획**된다(`data_path`·`data_sheet`·`data_header_row`·
  `data_kind` — 네 값이 같은 시점의 한 벌). 승계가 풀 슬롯을 다시 읽지 않는 이유는 슬롯이 가변이기
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
- **데이터를 들고 온 진입은 템플릿을 골라도 앵커를 잃지 않는다**(#349 리뷰 3R, #878):
  `EditorController.new_job_session` 은 진입 사유가 `DATA_ANCHORED_ENTRY_REASONS`
  (`document_browser_new_work`·`document_browser_repair`)일 때 데이터 문맥과 진입 문맥을
  초기화 너머로 승계한다. 그 예외가 없으면 1단계에서 「이 템플릿으로」를 누른 **모든
  사용자**가 보통의 빈 초안으로 떨어진다. 판정은 사유 하나이고 저장본 유무는 보지 않는다 —
  수리 진입은 저장된 작업을 여는데 그 데이터도 사람이 아니라 진입이 들고 온 것이다.
  이름·매핑·단계는 종전대로 끊긴다(혼합 세션 금지 불변).
- `toggle_favorite`(`name`·`value`)은 정렬 메타(`Job.favorited_at`)만 바꾼다 — 활성 작업·
  매핑·검증·선택을 폐기하지 않는다(§18.5). 값은 표면이 보내는 의도 상태이고 시각은 Python 이
  찍는다.
- `prefer_work`(`name`)은 라이브러리 「문서 만들기에서 사용」의 착지다(§19.8). **3분기 판정은
  이 컨트롤러가 낸다** — 준비·호환은 링1 술어가 소유하므로 표면이 다시 계산하면 같은 상태를
  두 곳이 판정한다. 데이터가 이미 준비됐고 호환되면 그 버튼 사건 자체가 명시 선택이라
  `select_job` 으로 active Work가 되고, 비호환이면 active Work를 바꾸지 않은 채 표면이
  「확인 필요」로 라우팅한다.
  데이터가 없으면 `preferredWorkId` 를 **이전의 명시 의도를 나중에 재진술하기 위한 session
  hint**로 한 번만 보관한다. preferred는 active Work도 선택 권한도 아니다. 다음 DataTarget
  마운트에서 backend가 같은 링1 호환 판정으로 확인한 뒤 1회 소비하고, 호환이면 「사용할 수
  있음」을, 비호환이면 사유를 `data_notice` 로 재진술한다. 어느 경우에도 마운트가 active
  Work를 자동 선택하지 않는다. 그 `data_notice` 는 자동 소멸이 아니라 사유가 해소될 때까지
  남는 채널이라 닫기 동사(`dismiss_data_notice` — 무페이로드, 채널이 하나라 지울 대상을 웹이
  지목하지 않는다)를 가진다. 레지스트리 조회 실패 경고는 스냅샷마다 실측에서 다시 합성되는
  자동 소멸분이라 그 문의 대상이 아니다. 사용자가 현재 「문서 만들기」의 후보를 누르거나 전역
  「문서 작업」 browser에서 exact Work를 찾아 「문서 만들기에서 사용」을 다시 누른 명시
  command 뒤에만 active Work가 된다. **편집기의 「저장하고 문서 만들기로」도 같은 명시
  command 다**(U6-D #978): 저장 성공 뒤 같은 순서로 이 액션을 지나고 3분기 판정을 그대로 이
  컨트롤러에 맡긴다 — 표면이 `select_job` 을 직접 쏘면 준비·호환 판정이 한 벌 더 생긴다.
  preferred가 메인 Top-N 밖이면 순위를 바꾸거나 카드를
  끼워 넣지 않고, 전역 「문서 작업」 browser에서 직접 검색·선택한다(#764).

### 저장 폴더 — 전역 단일 값 (U3-06 #879 의 승계 판정)

**저장 폴더는 작업의 속성이 아니라 앱의 설정이다.** U3-06(#879)이 세운 3단 도출
(① 이번 세션의 명시 지정 → ② 기억한 지정 → ③ 템플릿 옆 `Results`)에서 **①이 폐지됐다** —
사용자 확정. 남은 축은 둘이다:

1. **설정한 전역 저장 폴더** — 존재 확인을 통과할 때만 선다.
2. **템플릿 옆 `Results`** — 전체 경로로 도출될 때만 선다.

둘 다 재료가 없으면 `directory=""`(도출 불가)이고, **그때만** 저장 폴더 지정이 생성의
전제조건으로 남는다(`OUTPUT_DIRECTORY_REQUIRED`).

- **판정은 링0 하나다**: `domain/output_folder_default.resolve_output_folder` — 순수 함수이고
  존재 관찰(`remembered_exists`)은 호출자가 건넨다. 출처 라벨(`설정한 저장 폴더`/`기본값`)과
  하향 사유 문안도 여기 산다 — 표면은 그리기만 한다(재조립 금지).
- **관찰과 존 성형도 한 함수다**(U6-D #978): `webapp/output_folder_zone.py` 의
  `output_folder_resolution`/`output_folder_zone` 을 작업 화면과 편집기 3단계가 **함께**
  부른다. **설정값의 소유자도 하나다** — `JobController.remembered_output_directory()` 가
  그 값을 내고 편집기는 그것을 콜러블로 주입받는다(설정 파일을 두 곳이 각자 읽으면 쓰기
  실패 한 번에 두 표면이 서로 다른 폴더를 말한다). 링0 판정이 하나여도 관찰·성형이 화면마다 손으로 쓰여 있으면 한쪽만 하향 사유를
  빠뜨리는 자리가 그대로 남는다. 갈리는 인자는 「어느 템플릿 옆을 기본값으로 보는가」 하나다
  (작업 화면은 앉은 작업의 템플릿, 편집기는 그 세션의 템플릿).
- **영속은 설정 키 `last_output_directory` 하나다**(`external/settings.py`). 키 이름은 유지하고
  **의미만 승격**했다: 「마지막 명시 지정(다음 세션의 재료)」 → 「지금 쓰이는 전역 저장 폴더」.
  값의 형태·해석이 그대로라 마이그레이션이 없다(승격 기록은 그 docstring).
- **도출의 출입구는 `JobController._output_folder_resolution()` 하나**다. managed 축의
  `RunDeliveryIntent` 와 구식 축의 `out_dir` 이 **같은 도출**을 지난다 — 부팅·작업 착석·작업
  해제·설정 변경 넷이 전부 이 함수를 거친다. 갈래별로 다른 값을 세우던 동안 생긴 결함이
  「고른 폴더가 갈래에 따라 조용히 무시된다」(#905)였다.
- **세션 상태가 없다.** `_run_delivery_intent`(session-scoped 명시 지정)와 그 갈래 술어
  `_seat_is_managed_hwpx` 는 소비자 0 으로 걷혔다. `RunDeliveryIntent` 자체는 남는다 —
  delivery 해결의 인자이고 매 도출에서 물질화된다. 세션 축으로 남는 것은 충돌 처리
  (`_run_delivery_collision`)뿐이고 저장 폴더와 독립이다.
- **작업 미선택 상태의 지정이 유효하다.** 전역값이라 앉은 작업이 없어도 설 수 있고, 작업이
  나중에 앉아도 덮이지 않는다. 종전에는 착석이 템플릿 옆 기본값으로 조용히 덮어써서 화면이
  작업 미선택에서 폴더 선택을 잠갔다 — 그 잠금과 그것을 재던 게이트 단언이 함께 죽었다.
- **스냅샷은 최상위 `output_folder` 존**(`directory`·`source`·`source_label`·`notice`)을
  **작업 유무와 무관하게 상시** 싣는다. 종전 자리였던 작업대 관찰 존
  (`workbench_observation.output_folder`)에는 더 이상 없다: 「어디에 저장되는가」는 관찰이
  무너져도, 작업이 없어도 답할 수 있는 사실이라 존이 아니라 최상위가 진다.

**표면 — 고르는 자리는 하나, 보이는 자리는 갈래마다 하나**

| 갈래 | 자리 | 좌표 |
|---|---|---|
| 고르기(전역) | 셸 설정 모달의 저장 폴더 행 | `#settingsPickFolder`(+`#settingsOutDir`·`#settingsOutDirSource`·`#settingsOutDirNotice`) |
| managed hwpx | 「생성 예정 문서」 머리 — `저장 폴더: {경로} ({출처})` + 사유 | `#jobPlannedOutDir` · `#jobPlannedOutDirNotice` |
| 구식 hwpx | 생성 준비 존의 표시 한 줄(고르는 칸·단추 없음) | `#jobOutFolderRow` → `#jobOutDirLine` · `#jobOutDirNotice` |
| TXT(복사) | 없음 — 파일을 만들지 않아 폴더가 축이 아니다 | — |
| 편집기 3단계(hwpx) | 「이름·저장」 폼의 **읽기 전용 재진술** 한 줄 + 「설정에서 바꾸기」 | `#editorOutDir` · `#editorOutDirSource` · `#editorOutDirNotice` · `#editorOpenFolderSettings` |
| 편집기 3단계(TXT) | 없음 — 존이 `null` 이라 행 자체가 서지 않는다(TXT 갈래와 같은 근거) | — |

- 작업 화면에서 걷힌 것: `#jobOutRow`(라벨+`#jobOutDir`+`#jobBtnPickFolder`+`#jobOutTrack`)와
  managed 저장 폴더 구획(`#jobManagedOutDir`·`#jobManagedPickFolder`·`…OutDirSource`·
  `…OutDirNotice`). 결과 존의 폴더 표시는 **실행 증거**라 불변이다.
- **배달 blocker 의 착지**: `#jobDeliveryBlockers` 아래 `#jobOpenFolderSettings`
  (「저장 폴더 설정 열기…」)가 설정 모달을 연다(`JobRunController.openOutputFolderSettings`).
  사유만 적고 갈 곳을 안 주면 막다른 경보가 되기 때문이다. 다만 blocker 를 **지우는** 동사는
  폴더를 실제로 바꾸는 쪽이라, `blocker_affordance.py` 의 `REVIEW_DELIVERY` 등록 좌표는
  `#settingsPickFolder`(`bridge_method="pick_output_folder"`)다 — 문은 좌표가 아니다.
- **관찰은 폴더를 만들지 않는다**(불변). 도출된 기본값은 아직 없을 수 있어 빈 점유로 관찰하고
  (`allow_missing`), 설정한 폴더는 도출이 이미 존재를 확인했으므로 그 관용을 받지 않는다 —
  거기서 읽히지 않으면 「아직 없다」가 아니라 「읽을 수 없다」(권한·잠김)다.

### 서식 폴더 — 단일 루트 (U6-A #975 · U6 §2.3)

**템플릿 목록의 루트는 하나이고 사용자가 고른다.** hwpx·txt 가 **같은** 폴더를 재귀로 읽고,
매체별 루트 축(`templates` / `text_templates`)은 사라졌다. 지정이 없으면 앱 홈 `templates` 가
루트이므로 기존 사용자의 이행 비용은 0 이다.

- **도출은 홀더 안에서 1회 memo 된다**(U6-D #978 리뷰 8): 무효화 지점은
  `TemplateRoot.set()` 하나이고, 그것이 곧 루트가 바뀌는 전부다(재지정 동사가 이 홀더에 하나
  뿐이라는 사실이 그 근거다). 편집기 스냅샷이 표시명을 짓느라 홀더를 여러 번 지나므로,
  재판독이면 푸시 한 번이 같은 답을 사러 `settings.json` 에 여러 번 간다.
- **판정은 링0 하나다**: `domain/template_root_default.resolve_templates_root` — 순수 함수이고
  존재 관찰(`configured_exists`)은 호출자가 건넨다. 출처 라벨(`설정한 폴더`/`기본 폴더`)과
  사유 문안도 여기 산다(표면 재조립 금지).
- **기본값으로 내려가지 않는다** — 저장 폴더 도출과 갈리는 유일한 지점이다. 설정한 폴더가
  사라져도 그 경로가 그대로 루트이고 `notice` 만 붙는다. 내려가면 사용자가 고른 것과 **다른
  템플릿 집합**이 목록에 서고, 그것으로 문서를 만드는 것이 곧 조용한 추측이다. 빈 목록의
  안내는 링1 `TemplateManagerViewModel.empty_hint()` 가 정본이고 고르기 열 존이 그 값을 그대로
  옮긴다(`tpl.column.empty_hint` — 루트가 하나라 원인도 하나다). 프런트의 `emptyText` 는
  스냅샷이 아직 없을 때의 자리 문안으로만 남는다.
- **영속은 설정 키 `templates_root` 하나**(`external/settings.py`, 기본 `""` = 미지정).
- **런타임 권위는 `external/template_root.TemplateRoot` 인스턴스 하나**다. 캐시하지 않는다 —
  매 판독이 설정을 다시 읽으므로 재지정 직후의 첫 스냅샷이 곧 새 루트다. 아래 **다섯 자리**가
  전부 이 홀더(또는 그 `path` 콜러블)를 지난다:
  ① `app.py` 조립의 `TemplateFileStore(root=…)` ② 같은 조립의 `TextTemplateRegistry(root=…)`
  ③ `TemplateController` 의 `TemplateManagerViewModel(root.path)` ④ `EditorController` 의
  표시명 도출(`library_display_name` — U6-E #979 에서 VM·TXT 레지스트리 지연 폴백이 함께
  퇴역해 이 화면의 루트 소비자는 하나가 됐다) ⑤ `JobRegistry(template_root=…)` 의
  `template_key` 승격·해석(`job_store.library_key_for`/`resolve_library_key` 는 루트를 **명시
  인자**로 받는다). `host/locations` 의 `default_text_templates_dir`·`library_root_for` 는
  **삭제**됐다. 루트는 **읽는 구간마다 한 번**만 평가한다(스캔 시작·저장 임계구역 진입) —
  항목마다 다시 읽으면 도중의 재지정이 한 목록·한 저장을 두 루트의 뜻으로 쪼갠다.
- **루트 재지정이 작업을 재결속하지 않는다**(#983 리뷰 차단 1). 저장된 링크는 둘이고
  (`template_path` 절대경로 + `template_key` 루트 상대키) 해석 순서는
  `job_store._resolve_template_link` 하나가 진다: **살아 있는 절대경로가 언제나 이긴다**.
  키는 「살던 자리가 통째로 사라졌을 때」만 서고(그 자리는 저장된 경로에서 키를 떼어
  되짚는다 — `_former_root_of`), 그것이 #348 이 겨눈 홈 이동·백업 복원의 정확한 모양이다.
  파일 하나가 지워진 경우는 **끊긴 링크로 남는다** — 새 루트의 동명 파일로 갈아타면 작업이
  조용히 다른 서식으로 문서를 만든다(법적 효력 문서에서 최악의 조용한 재결속). 읽기는
  여전히 디스크를 고치지 않는다(존재를 묻기만 한다).
- **재지정 동사는 하나**다: 직접 브리지 `pick_templates_root` → `TemplateController.set_templates_root`.
  빈 값·파일 경로는 loud 거절이고, 성공은 **한 번의 푸시**로 좌 열 목록과 `templates_root` 존을
  함께 옮긴다(소비자가 전부 홀더를 지나므로 갈아 끼울 두 번째 자리가 없다). 편집 세션에는
  변이 통지를 보내지 않는다 — 파일은 하나도 바뀌지 않았고, 폴더 경로를 경로 대조 seam
  (`mutation_sinks`)에 실으면 어느 세션과도 맞지 않는 조용한 무효 통지가 된다. 목록 갱신은
  이 푸시 + 호출자(설정 시트)의 화면 재당김이 진다.
- **스냅샷은 `tpl` 최상위 `templates_root` 존**(`directory`·`source`·`source_label`·`notice`)
  이고 저장 폴더의 `output_folder` 존과 동형이다. 「어느 폴더를 읽고 있는가」의 자리는 그
  존 **하나**다 — 목록이 비어도, 작업이 없어도 답할 수 있는 사실이라 열 안 사본을 두지 않는다
  (옛 밴드의 `dir` 은 그 사본이었고 함께 걷혔다).
- **표시명 규칙은 하나**다: `domain/template_status.library_display_name` — 루트 상대 경로,
  확장자 제외, POSIX(`온나라/기안`). 재귀 루트에서 basename 은 유일하지 않으므로 하위폴더가
  이름에 남아야 두 파일이 구분된다. 파일명 기반 **정체성**(`rel_key`·`template_key`)은 불변이다.
- **나열 제외는 두 매체 공통**이다: `Results`(산출물)·`.trash`(옛 삭제 보관소). 목록과 술어의
  단일 출처는 `domain/template_status` 의 `EXCLUDED_DIR_NAMES`·`is_excluded_subtree` 이고,
  hwpx walker·txt walker·레거시 이관 **셋이 그 하나를 부른다**(문자열·조건 재선언 금지).
- **레거시 TXT 는 1회 이관된다**: 설정 키가 비어 기본 루트를 쓰는 경우에만, 부팅 시
  `home/text_templates/**/*.txt` 를 같은 상대 경로로 `home/templates/` 로 **옮긴다**(복사가
  아니다 — 다음 부팅에 걷을 것이 남지 않는다). 이름이 이미 있으면 그 파일은 건드리지 않고
  사유에 남긴다. 나열이 거르는 하위트리(`Results`·`.trash`)는 **옮기지 않고** `skipped` 에
  사유로 남긴다 — 옮겨 봐야 새 루트에서도 걸러져 목록에서 사라진다. 재진술은 **두 채널**이
  받는다: 내구성 로그(`settings.alert` — stderr + 홈 `webapp-alerts.log`)와 **화면**(`tpl`
  스냅샷 `templates_root.notice` 에 이 프로세스 수명 동안 병기 — 도출 사유가 이미 있으면
  줄바꿈으로 둘 다). 로그만 두면 사용자는 자기 TXT 가 옮겨진 사실을 영영 모른다. 사용자가
  루트를 지정했으면 이관하지 않는다(고른 폴더에 앱이 파일을 넣지 않는다).
- **퇴역한 동사**(같은 슬라이스): 폴더 일괄 가져오기(`import_templates_folder` 브리지 ·
  `tpl/scan_import_folder`·`import_folder` · 링1 후보 몸통 · 「폴더에서 가져오기…」 버튼)와
  삭제·휴지통(`tpl/delete`·`undo_delete` · `TemplateFileStore.trash`/`restore` · 30일 정리 ·
  행 메뉴의 「삭제」). 삭제가 걷히면서 **동사가 0 인 행**이 생겼다(COMPILED·FILLED hwpx ·
  판독 실패 TXT) — 그 행의 ⋮ 는 **비활성 + 사유**(`LIB_ROW_NO_ACTION_REASON`)이고, 메뉴를
  여는 쪽과 트리거를 잠그는 쪽이 `libRowMenuItems` **한 술어**를 본다(누르면 아무 일도 없는
  버튼 금지). 앱은 사용자 폴더에 `.trash` 를 만들지 않는다 — 「폴더에서 보기」가
  삭제 동사를 대신한다. 단건 「가져오기…」(`import_template_file` → 루트 직속 복사 + `이름 (2)`
  접미)는 **유지**된다. 남은 `deleted` 통지 생산자는 동결 온보딩의 예제 일괄 제거뿐이다.
- **동결 그룹 정리는 허용한다**: 루트를 바꾸면 첫 스냅샷의 `TemplateGroupModel.reconcile` 이
  옛 키의 그룹 지정을 삭제·영속한다. 그룹 축은 U4 §2-30 에서 동결·비노출이고, 스캔과 어긋난
  지정이 굳는 것이 되살릴 때의 부채라 그대로 둔다.

### `library` 화면(전역 문서 작업 라이브러리) 계약 (§19.6·§19.7)

`LibraryController`와 React producer(`frontend/src/screens/library.ts`)가 홈 화면을
대체한다(재작성 F2 PR-A). 링1
투영은 `HomeViewModel` 이 그대로 소유한다 — 모듈명 유지는 지도 §10.8 판정 A 의 기록된 어휘 빚.

- 스냅샷 최상위가 곧 browser 상태다: `view`·`mode`·`query`·`counts`·`facets`·`sections`·
  `selected`·`detail`·`alerts`·`corrupt_rows`. 보기 4종(`all`/`recent`/`favorites`/
  `needsAction`)·방식 필터(`all`/`hwpx`/`txt`)·검색·태그 facet 은 **서로 다른 축**이라 하나를
  바꿔도 나머지가 살아 있고, 판정·정렬·건수는 전부 링1(`HomeViewModel.library_*`)이 낸다.
  구 group-by 렌즈는 **은퇴**했다 — 화면당 primary grouping 은 사용자 group 하나다(§19.2).
- 액션(정본 = `screen_library.py` 의 `_do_*` + `action_registry.py` 의 `library` 블록, 12건):
  `set_view`·`set_mode`·`set_query`·`clear_filters`·`select_work`·`toggle_favorite`·
  `delete_job`·`undo_delete_job`·`clone_job`·`relink_template`·`refresh`·`delete_corrupt`.
  구 `toggle_facet`·`clear_facets`·`toggle_group`·`set_tags` 는 U4 §2-30 에서 태그·그룹 표면과
  함께 걷혔다(판정·영속은 동결로 남고 액션만 없다).
- **빈 상태의 출구는 하나다** — 저장된 작업이 없는 갈래(`is_empty`)의 「＋ 첫 작업 만들기」
  (`data-new-work`). 동봉 예제로 시작하는 두 번째 출구(#891 `data-install-examples`)는
  튜토리얼 진입 표면과 함께 배포본에서 걷혔다(#941 — 아래 「온보딩 튜토리얼」 절의 동결
  표기). 스냅샷의 `examples` 축(`external/example_pack.entry_point_state()` 단일 출처)은
  그대로 서 있으므로 되살릴 때 이 자리에서 다시 소비한다. 필터가 비운 갈래(`!shown`)의 답은
  종전대로 `clear_filters` 이지 라이브러리 채우기가 아니다.
- `clear_filters` 는 0건 화면의 **상주 출구**다 — 네 절단자(보기·방식·검색·태그)를 한 번에
  걷는다. 절단 밖 작업에 도달할 길이 사라지지 않게 하는 §8.4 「도달성」 면의 이행분이다.
- `select_work` 는 상세 패널이 겨눌 행일 뿐 **활성 작업이 아니다** — 여기서 다른 작업을 열어도
  「문서 만들기」의 선택·데이터는 불변이다(§19.6 서문, 화면 머리 문안이 재진술).
- 즐겨찾기는 행 선택 버튼의 **형제** 버튼이다(§19.6: 중첩 금지). 이 배치가 「표시 상한과 무관한
  도달성」(§8.4 2행)의 새 거처다 — 메인 Top 5 밖 작업도 여기서 승격할 수 있다.
- 그룹 접힘은 **보기**만 바꾼다 — 접어도 구획 건수와 행 페이로드는 그대로다. 구획의
  `value=""` 는 두 뜻(퇴화 평면 / 「그룹 없음」)이라 `is_untagged`·`headed` 로 가른다.
- 탭 건수는 **검색 전** 값이다(라이브러리에 대한 사실 — 문서 탐색 탭과 같은 규칙).
- 검색 판정(`HomeViewModel._library_pool`)은 작업 이름·사용자 group·태그 값을 훑는다(소스
  키·데이터 경로 제외, §19.6). **안내 문구는 「작업 이름」 하나만 말한다** — 뒤의 두 축은
  U4 §2-30 에서 표면이 걷혀 사용자가 값을 만들 자리가 없고, 없는 축으로 찾으라고 안내하면
  문구가 제품을 거짓으로 말한다. 매칭 범위는 그대로 두고(동결 축은 동결) 문안만 실동작을
  말한다.
- 확인 필요 행의 `health` 는 `{severity, text}` 쌍이다 — 문구만 주면 소비자가 경고(2)와
  차단(3)을 구분하지 못해 §19.7 건강 축이 "사유 있음/없음"으로 뭉개진다. 판정·문구는
  `library_health()`(§19.7 번역)가 소유하고 표면이 다시 만들지 않는다. 현재 데이터 호환성(`work_candidates`)과는 **섞지 않는다**(§19.7 명문).
- 목록의 1건은 **파생**이고 정본은 `library_health_causes()` 의 전 원인 열거다(§19.7 "상세에서
  모든 실제 원인"). 상세 `detail.health_causes` 가 그것을 그대로 싣는다 — 같은 상태를 두 술어가
  따로 판정하면 목록과 상세가 서로 다른 말을 한다.
- **상세는 실행 이력·실행 방식 문구를 싣지 않는다.** 둘 다 표면과 payload 에서 함께 걷혔고
  (`run_note`·`last_run_display`, 목록 행의 `last_run_display` 포함), 남은 키에 빈 값을 두지도
  않는다 — 빈 값은 표면이 자리를 다시 그리는 미끼다. 근거는 각각 하나다: 실행 방식은
  부제(`mode_label`)가 이미 말하고, 실행 이력은 「무엇으로 만드는가」의 판단에 들지 않는다
  (`screen_job` 후보 카드의 `last_run_label` 이 U4 계열2-31 에서 같은 사유로 먼저 걷혔다).
  링1 `Job.last_run_at` 은 그대로 영속하고 「최근 사용」 보기의 **정렬 재료**로만 산다 —
  매체별 술어를 문구로 가르던 산출자(`gui/work_mode.last_use_label`)는 소비자 0 으로
  삭제됐다(R5-99 B2 전례). Template/Binding **판본** 열은 F7 신설분이라 오늘 만들지 않는다
  (빈 자리·「준비 중」 표기도 두지 않는다 — 판정 D).
- **매핑 사본 금지는 U6-F(#980)에서 뒤집혔다 — 다만 옛 키는 되살아나지 않는다.** #966 이
  걷은 것은 정보가 아니라 **별도 라벨 사전을 든 payload 사슬**(`detail.bindings` + 링1
  `field_binding_rows`)이었다. U6-F 의 표는 편집기 2단계와 **같은 링1 순수 함수**
  (`gui/mapping_state.row_projection`)와 **같은 라벨 상수**(`ROW_STATUS_LABEL` ·
  `SPECIAL_SOURCE_LABEL` · 표시형 프리셋)를 두 번째 호스트가 소비하는 것이라 「같은 상태를
  두 곳이 판정」이 아니다 — 웹은 라벨을 짓지 않고 읽기 전용 칸의 해소된 문안(`source_label`·
  `display_label`)도 링1 조회다. 존 이름은 **`pairing_detail`** 이고 `bindings` 는 되살리지
  않는다(옛 사슬과 구별되지 않는다). `home_state.py` 의 철거 묘비가 이 승계를 진다.
- **상세 하단은 연결 그림이다**(U6-F #980 · U6 §2.6 · 동결 시안 장면 4). 종전의 사실 3행
  (`<dl class="lib-detail-facts">`)이 답하던 정체는 **연결 카드**가 지고, 그 아래 읽기 전용
  4열 표(템플릿 필드 · 데이터 열 · 표시형 · 첫 행)가 「이 작업은 무엇을 무엇으로 채우나」를
  잇는다. 파일 이름 계획과 저장 폴더는 여기 없다(U6 §5 2026-09-03 재판정 ④·⑥ — 이름 예시는
  편집기 3단계와 생성 결과가, 저장 폴더는 설정 창이 말한다). 구획은 둘이고 서는 조건이 갈린다:
  - **카드는 언제나 선다.** 정체는 템플릿을 못 읽어도 답할 수 있고, 무엇보다 연결을 고치러
    가는 손잡이가 거기 있다 — 템플릿이 사라진 갈래에서 카드를 접으면 고치러 갈
    길이 함께 접힌다. 수치(`연결 n / m · 확인 필요 k`)는 셀 수 있을 때만 서고(`card.counted`),
    그 재료는 `domain/fill_ledger.template_path_drift` 가 **매 refresh 한 번** 계산하는
    `TemplateStructureDrift` 이고, 링1 `JobRow` 는 그 결과를 **원본째** 든다(`structure`) —
    수치를 사본으로 복사하면 「읽지 못했다」와 「읽었는데 0 이다」를 가르는 축이 옮겨 오다
    빠진다. 저장된 프로파일은 확정 행만 담아 「확인 필요」를 셀 수 없으므로 그 수치는 현재
    템플릿과의 대칭차에만 있다. **세었는가는 수치가 아니라 명시 boolean 이 답한다**
    (`TemplateStructureDrift.readable` → `JobRow.structure_readable` → `card.counted`):
    `read_error` 갈래는 대칭차가 전부 비어 있어 수치만 보면 「차이 없음」과 같은 모양이고,
    그 위에 카드를 세우면 「연결 n / n · 확인 필요 0」을 지어낸다. 필드가 0 개인 읽을 수 있는
    템플릿은 `연결 0 / 0` 을 **말한다**(그것은 사실이다). `stale_count > 0` 이면 「템플릿에 없는 연결
    n건」을 **숨기지 않고** 한 줄 더 적는다. 표시명은 목록·편집기와 같은 규칙이다
    (`library_display_name` / 풀 등록명·basename — `webapp/screens.dataset_display_name`).
  - **표의 행은 편집기와 같은 규칙으로 선다**: 템플릿을 읽었으면 **누름틀 필드**에서 행을
    세우고 저장 매핑을 얹는다(`MappingModel.from_field_names` + `apply_profile` — 편집기의
    `from_suggestions` + `apply_profile` 동형). 저장 프로파일만으로 세우면 표가 카드와 **다른
    필드 집합**을 말한다: 매핑 안 된 템플릿 필드(카드의 「확인 필요 k」)는 행이 아예 없고,
    템플릿에서 사라진 옛 연결은 템플릿 필드인 척 선다. 그래서 미결속 필드는 `needs_source`
    행으로 서고(배지 「확인 필요」·클릭 deep-link 가능), 소멸분은 표 **밖**에서 이름으로
    말한다(`stale_fields` — 카드의 「템플릿에 없는 연결 n건: …」). 행을 세울 때 소스 어휘를
    주지 않는 것도 계약이다 — 주면 이름이 같은 열에 자동 결속이 붙어(결정 30) 사람이 확정한
    적 없는 연결이 「제안」으로 선다. 템플릿을 못 읽으면 저장된 연결만 그리고 **그 사실을
    명시**한다(`rows_basis`: `template`/`profile`). 8행을 프레임 안에 두고 나머지는 스크롤로
    감추는 대신 **이름으로** 명시한다(`more_fields`) — 자르기는 투영 **전에** 한다. 행
    클릭·Enter 는 `editWork(name, evidence, {target})` 로 편집기 2단계의 그 행에 착지한다 —
    `target: binding/<필드>` 는 기존 문맥이고 배관도 이미 서 있다(`app.py.open_editor` →
    `load_job(target=…)` → `aimAtTarget`, 백엔드 신설 0).
  - **계획 줄과 저장 폴더 줄은 퇴역했다**(2026-09-03 ④·⑥). 종전 U6-F 의 `plan`·`output_folder`
    존은 페이로드에서도 사라졌다(소비자 0 사슬을 남기지 않는다). 파일 이름 규칙은 편집기
    3단계만, 실제 이름은 생성 결과만, 저장 폴더는 설정 창만 말한다.
- **「첫 행」은 지연 읽기다**(U6-F #980). 데이터 파일을 열어야 채워지므로 첫 스냅샷은
  `first_row.state="pending"` 으로 나가고, 읽기는 **워커 스레드**에서 돈 뒤 **전체 `library`
  스냅샷을 다시 민다**(런타임 `reduce` 는 job 채널만 부분 dict 델타를 허용한다). 규율은
  여섯이다:
  - ① **시작 판정은 스냅샷 산출 한 자리**다(`_detail`). 액션 핸들러마다 시작을 걸면 상태를
    바꾸는 경로가 늘 때(선택·새로고침·삭제·다시 연결·복원·복제) 그 자리를 하나씩 더 기억해야
    하고, 빠뜨린 경로에서 상세가 영영 「아직 모름」에 머문다. 스냅샷마다 「이 겨눔의 답이
    있는가」를 물으면 어느 경로로 상태가 바뀌었든 다음 스냅샷이 알아챈다.
  - ② **진행 중 키 집합**이 중복 기동을 막는다 — ①의 대가로, 없으면 검색 타이핑 한 글자마다
    같은 파일에 워커가 겹쳐 뜬다.
  - ③ 결과는 컨트롤러의 **사적 캐시**에 들어가 재렌더가 파일을 다시 읽지 않게 한다. 키는
    작업 이름 + 참조 4벌 + **파일 지문(mtime·size)** 이라, 참조가 같아도 파일이 바뀌면 자연히
    미스다(상한은 두지 않는다 — 키는 사람이 고른 작업 수만큼만 늘고, 낡음은 상한이 아니라
    지문이 막는다).
  - ④ **실패는 캐시에 남고**(그래야 ①이 무한 재시도하지 않는다) 사람의 **명시 선택**
    (`select_work`)이 그것을 걷는다 — 파일을 고쳐 두고 그 행을 다시 누르는 것이 곧 「다시
    읽어 보라」다(파일이 실제로 바뀌었으면 ③의 지문이 이미 미스를 낸다).
  - ⑤ 늦게 끝난 읽기는 **상관 키를 다시 대조**한 뒤에만 푸시한다(`_push_progress` 의
    `run_token` 선례) — 그사이 다른 행을 골랐으면 캐시에만 남는다.
  - ⑥ 상태는 명시 3태 `pending`/`ready`/`error` 이고 `record={}` 로 미읽음을 흉내 내지
    않는다(빈 레코드는 미입력 표식을 찍어 「산출물이 담을 것」과 「아직 모름」을 한 글자로
    접는다). 실패는 사유와 함께 그 칸에 서고 `library_health_causes` 에는 **섞지 않는다**
    (§19.7 — 호환성·건강과 상세 판정은 분리). 참조 끊김 판정은 `screens.reference_missing`
    단일 출처를 지난다.

  이 읽기는 「선택 ≠ 착석」 불변을 흔들지 않는다: 편집기·작업 화면의 `load_data_path` 계열을
  재사용하지 않고 자기 캐시에만 남으며 자기 채널만 민다. 존 자체는 **결속 정체·매핑 내용·
  구조 재계산·첫 행 결과·저장 폴더·분 단위 시각**을 덮는 키로 memo 한다 — 검색 한 글자마다
  전 행 투영과 폴더 stat 을 다시 지불하지 않는다.
- **미리보기 칸의 렌더러는 하나다**(`frontend/src/screens/preview_cell.ts`). 편집기 2단계의
  「미리보기」 열과 이 표의 「첫 행」 열이 같은 `preview_kind` 닫힌 집합을 받으므로 스위치를
  두 벌 두면 그 집합이 갈린다(실제로 갈렸다 — 한쪽이 `blank` 와 `none` 을 한 문자로 접었다).
  호스트마다 갈리는 것은 오류의 **문장** 하나이고 그것만 인자로 받는다.
- 카드의 두 항목은 이름 곁에 **「열기」·「폴더에서 보기」**(PathActions 아이콘,
  `detail.template_path`·`detail.data_path` 겨눔)를 싣는다(U2 §2.20, #342) — 경보(템플릿 미연결
  N건)는 이 화면이 내는데 조작이 여기 없었다(계기판의 짝). 어휘·아이콘은 PathActions가
  소유하고, 자리는 그 항목 안이다(자리가 대상을 말한다). 경로 검증은 백엔드 화이트리스트,
  클릭은 React 핸들러 — 신설 배선은 payload 한 칸(`template_path`)뿐이다.
- 편집기로 가는 손잡이는 **가운데 「연결」 줄 하나**다(`#libraryPairingEdit`, U6 §5
  2026-09-03 재판정 ⑤). 선 위의 원형 노드 + 수치(`연결 n / m · 확인 필요 k`, 세지 못한 갈래는
  「조합 보기」)가 버튼이고 편집기 1단계 **「고르기」** 에 착지한다 — 두 항목 *사이의 선*을
  누르는 것이라 그 둘을 고르는 그림으로 가고, 거기서 템플릿·데이터 교체가 둘 다 한 클릭이다.
  표 행 클릭만 2단계 「연결 확인」 으로 간다. 종전의 「템플릿 재선택…」·「데이터 재선택…」 두
  버튼은 걷혔다(데이터 재선택은 「작업 편집」 기본 착지·표 행 클릭과 같은 단계였다 — 완전
  중복). 손잡이는 `editWork(name, evidence, {section: "template"})` → `EditorEntry.openGuarded`
  를 타므로 편집기
  이탈 가드·데이터 인계는 종전대로다. `section` 어휘는 Python 단일 출처(`gui/edit_session.py`:
  `template`/`binding`)이고 배관은 이미 서 있다 — `app.py.open_editor` 가 `ctx.section` 을
  `load_job(landing_section=…)` 으로 넘긴다(백엔드 신설 0). 항목 곁에 남는 버튼은 차단 해소
  동사뿐이다 — 미결속 데이터 갈래의 「데이터 연결하기…」(연결할 결속이 아직 없다).
- 2-pane 공간 배분은 목록 길이에 끌려다니지 않는다: 넓고(≥921px) 높은(≥760px) 창에서 두 pane 이
  뷰포트를 나눠 각자 스크롤하고 **페이지는 스크롤하지 않는다**. 좌:우 비율은 U6-F(#980)에서
  `1fr : 1.25fr` 로 **뒤집혔다** — 상세가 연결 그림을 지면서 넓은 쪽이 필요해졌고, 목록은
  이름 한 줄 + 배지라 좁아도 읽힌다. 상시 행동(`작업 편집`·`문서 만들기에서 사용`)은 상세
  스크롤과 분리해 pane 아래 고정한다(§19.6 마지막 문단).
- 액션: `set_library_view`(`view`)·`set_library_mode`(`mode`)·`set_library_query`(`text`).

### 온보딩 튜토리얼 — 체크리스트 셸 패널 + 순간 카드 (#894 · `ONBOARDING_TUTORIAL.md` §1 D3·§4.3)

> **표면 동결(2026-08-30 · #941).** 아래 서술의 **웹 표면은 배포본에서 걷혔다** — React 트리의
> `TutorialPanel` 마운트(`react/boundary.ts`)·포트 배관(`react/boot.ts`·`bootstrap.js`)·
> `.tut-*` CSS(`frontend/css/tail.css`)·라이브러리 빈 상태와 편집기의 예제 설치·제거 진입점이
> 전부 제거됐고, PyInstaller spec 은 `examples/onboarding/` 자산을 **더 이상 동봉하지 않는다**
> (`packaging/verify_specs.py` 가 그 부재를 단언한다). live101 의 `onboarding` phase 도
> 함께 걷혔다(콜드 부팅 하나 감소).
>
> 태그·그룹(U4 §2-30)·나라장터와 같은 처분이다: **모델·판정·영속은 지우지 않는다.** 링1
> (`gui/tutorial_state.py`)·컨트롤러(`webapp/screen_tutorial.py`)·마일스톤 통지 seam·
> 설정 영속·`external/example_pack`·`examples/onboarding/` 자산과 그 생성 스크립트·
> 컴포넌트(`frontend/src/tutorial/panel.ts`)와 그 렌더 계약 테스트가 전부 동결로 산다. action
> registry 의 `tutorial` 화면과 `tpl` 의 `install_examples`·`remove_examples` 도 그대로다 —
> 되살릴 때 그 자리에서 다시 소비하면 된다. 재구축 정본은 #941.
>
> 아래는 **되살릴 때의 설계 정본**으로 남긴다.

**화면이 아니라 채널이다.** `tutorial` 은 `PRODUCT_SCREEN_IDS` 에 없고 DOM 루트도 탭도 없다.
그런데 action registry 의 화면 키를 갖는 이유는 이 저장소에서 **스냅샷 채널과 디스패치 어휘를
얻는 유일한 경로**가 그 표이기 때문이다(store 채널은 `SCREEN_ACTIONS` 에서 유도되고 손 목록이
없다). 같은 형상의 선례가 화면 사망 후 채널만 남은 `pool` 이다. 새 통신 경로는 만들지 않았다 —
푸시는 기존 `window.__hwpx` 의 `snapshot` 사건에 얹힌 채널 하나다.

- **판정·문안은 전부 링1**(`gui/tutorial_state.py`): 단계 T0~T17·티어 4·달성·다음 걸음·졸업·
  제안·순간 카드 문안. 링2(`webapp/screen_tutorial.py`)는 VM 하나를 **세션 소유**하고 영속
  왕복(`external/settings.load_/save_tutorial_progress`)과 스냅샷 전달만 진다. 프런트
  (`frontend/src/tutorial/panel.ts`)는 그 스냅샷을 그리기만 하고 문안을 조립하지 않는다.
- **마일스톤 통지는 디스패치가 아니라 컨트롤러 간 seam** 이다(tpl→편집기 재정산 선례): 웹이
  부르는 표면이 아니라, 원인 동사의 성공과 같은 줄에서 파이썬이 스스로 부른다. 통지 지점을
  가진 컨트롤러 넷은 `TutorialSink` 콜러블 **하나만** 생성자 주입으로 받는다(푸시 sink 와 같은
  규율 — 컨트롤러는 VM 도 `settings` 도 채널도 모른다). 조립 한 줄은 `webapp/app.py` 소유다.

| 단계 | 통지 지점(이미 성립한 전이) |
|---|---|
| T0 예제 설치 | `screen_template._do_install_examples` — `confirm` 2차 성공(1차 재진술은 통지 없음) |
| T1 템플릿 적용 | `screen_editor._do_use_library_template` — `new_job_session` 뒤 |
| T2 매핑 전확정 | `screen_editor.dispatch` 꼬리 — 링1 `is_complete()` 의 **false→true 상승 모서리** |
| T3/T10 작업 저장 | `screen_editor._do_save` — 레지스트리 쓰기 성립 뒤. HWPX/TXT 갈림은 `Job.media` |
| T14 비움 확정 | `screen_editor._do_set_blank` — 그 행이 **실제로 비움 확정으로 옮겨갔을 때**(U6-C: 구 `confirm_blanks` 모달의 후계) |
| T4/T12 마운트·교체 | `screen_job._remember_data_source` — 세 마운트 경로가 모이는 한 자리. T12 는 **이 세션 안에서의** 2번째 마운트 |
| T5 작업·행 선택 | `screen_job.dispatch` 꼬리 — `job_name` ∧ `selection.selected_count() ≥ 1` |
| T6 승인 | **발신자 없음**(#957 — 승인 사건 소멸). 링1 단계 정의는 동결 자산이라 그대로 선다 |
| T7·T8·T9·T13·T16·T17 | `screen_job._note_tutorial_generation` — 생성 완주(`succeeded ≥ 1`) 한 자리 |
| T11 복사 | `screen_workbench.note_copied` — 복사 카운터가 실제로 오른 자리 |
| T15 누름틀 변환 | `screen_template._do_compile` — 링1 `result.mutated` (무변이 거절은 통지 없음) |

- **앱이 안 들고 있는 이력은 세션이 센다**: 「같은 작업 2번째 생성」(T8)·「같은 마운트 위 작업
  전환」(T9)·「갈래 구성 변화」(T17)는 어디에도 기록이 없다(`Job` 은 `last_run_at` 한 칸,
  managed 배달 원장은 출력 폴더의 쓰기 전용 사이드카). 그래서 `GenerationLoopLedger` 가 세션
  수명으로 **세기만** 하고, 어느 T 인지는 호출자가 정한다(커리큘럼 재판정 금지). 구간 축은 S4
  read-only projection(`{항목 id: 고른 선택 id}`)의 두 실행 사이 diff이고, 조회가 서지 않는
  상태는 「구성 없음」이 아니라 **모른다**라서 T17 이 서지 않는다. 축이 갈래 하나인 이유는
  v1 제어면이 EXACTLY_ONE 이라 「구간을 뺀다」가 곧 「생략」 갈래를 고르는 것이기 때문이다
  (#284 재판정 — 두 단계로 가르면 제품에 없는 구분을 가르친다).
- **T16 전용 seam**: tpl 의 `compile_sinks` 는 `mutation_sinks` 와 **갈라** 둔다 — 변이 통지는
  「파일이 바뀌었다」 전부(개명·삭제·복원·TXT 저장)라 한 sink 로 합치면 slot 개명 한 번이
  「변환본으로 생성」을 거짓으로 켠다.
- **렌더는 셸 레벨**: `react/boundary.ts` `createAppElement` 의 **여섯 번째 형제**로 `#reactRoot`
  안에 선다. `.topbar` 는 불가하고(몰입 표면이 덮는다) 화면 stage 안도 불가하다(전환이 걷어
  간다). 화면 전환은 `shellNav.subscribe()` 로 **관측**한다 — 이탈 가드가 전환을 취소할 수
  있으므로 `go()` 성공을 낙관 가정하지 않는다.
- **순간 카드**: 요소 앵커 0(코치마크는 계속 기각 — 앵커 좌표가 DOM 계약의 소비자가 되면 화면
  개편마다 드리프트한다). 화면에 선 장은 **큐에서 파생**(`momentToShow`)이라 지역 상태가 아니고,
  자동 소멸이 곧 `consume_moment` 왕복이다(프런트가 자기 안에서 지우면 다음 스냅샷이 같은 장을
  다시 싣는다). 동시 1장·클릭 불가로채기(`pointer-events:none`)·`prefers-reduced-motion` 존중.
  억제 축은 overlay 엔진의 `isDialogPending()` 하나다 — `needs_confirm` 은 화면 컨트롤러마다
  흩어져 있어 중앙 관측점이 못 된다. 억제 중에는 시계도 서지 않는다(모달에 가려 소진되지 않게).
- **수명주기 = 두 축**(#918 · `ONBOARDING_TUTORIAL.md` §1 D5): 달성 기록은 **단조·영속**이고
  지우는 액션이 없다. 다시 걷기는 기록의 되돌리기가 아니라 **안내 초점**(`focus_tier`)의
  이동이고, 표면이 보는 실효값은 링1 이 합친 `guided_tier`(= 초점 ?? `suggested_tier`)
  하나다. 초점은 표시 이력이라 영속하지 않는다(순간 카드 소비와 같은 부류) — 닫기·재부팅은
  초점을 걷어 지금 상태로 연다. 되돌아가지 않는 것(기본 티어 T0~T3)은 감추지 않고 링1 의
  `replay_caveat` 이 초점 자리에서 말한다.
- **렌더 분기는 본문 국면 셋**: `progress`(다음 걸음 + 전 티어 목록 + 다시 보기 자리) /
  `complete`(`standard_complete` ∧ 초점 없음 → 완주 문안 + 다시 보기 자리, 체크리스트 없음) /
  `focus`(겨눈 티어 하나 + 한계 문안 + 해제 동선). 국면은 `#tutorialPanel` 의 `data-phase` 에
  실린다. 완주 자리에서 「다음 걸음」이 사라지는 것이 계약이다 — 18/18 인 채 걸음을 재촉하던
  것이 #918 A 다.
- **액션 5종**: `dismiss`·`resume`(명시 종료·재개, 영속) · `consume_moment`(`milestone`) ·
  `focus_tier`(`tier`)·`clear_focus`(안내 초점 지정·해제, 세션 값). 뒤 셋은 전부 「무엇을
  보여줄까」이고 「무엇을 달성했는가」를 바꾸는 액션은 등록되지 않는다. 달성 기록은 닫힌
  동안에도 이어지고, 그동안의 순간 카드는 큐에 넣지 않는다(재개 순간 밀린 카드가 쏟아지지
  않게). 닫은 뒤에도 `#tutorialResume` 하나가 완주·미완주 양쪽에서 남아 재개가 도달 가능하다.
- **DOM id**: `#tutorialPanelRoot`(`data-screen`) · `#tutorialPanel`(`data-collapsed`·
  `data-phase`) · `#tutorialPanelTitle` · `#tutorialProgress` · `#tutorialCollapse` ·
  `#tutorialDismiss` · `#tutorialBody` · `#tutorialNextStep` · `#tutorialComplete` ·
  `#tutorialRevisit` · `#tutorialTierPicker`(버튼마다 `data-tier`) · `#tutorialFocusCaveat` ·
  `#tutorialFocusClear` · `#tutorialMoment`(`data-milestone`) · `#tutorialResume`.
  단계·티어 행은 `data-milestone`·`data-achieved`·`data-tier`·`data-complete` 를 싣는다.
- **게이트**: 헤드리스·배선·영속은 `tests/test_webapp_tutorial.py`, 렌더 요소와 큐·억제 규칙은
  `tests/js/tutorial_panel.test.js`, 링1 판정은 `tests/test_tutorial_state.py`. 이 셋은 표면
  동결(#941) 뒤에도 그대로 선다. 실렌더 기하(`tests/test_web_tutorial_geometry.py`)와 CSS
  소비자 대조, live101 `onboarding` phase 는 그릴 것이 사라져 함께 걷혔다 — 되살리는 변경이
  `.tut-*` CSS 와 그 두 층을 한 벌로 되돌린다.

## DOM과 런타임 게이트

- source entry·import 폐포·React root 결속은
  `tests/artifact_contract/test_frontend_build_graph.py`가 정적으로 확인한다.
- 공개 브리지·payload 경계는 `tests/repo_contract/test_bridge_contract.py`와
  `tests/repo_contract/test_dispatch_payload_contract.py`, React 요소·ARIA는 각
  `tests/js/*.test.js` 장기 소유자가 확인한다. 완료 이관기의 범용 DOM 문자열 census는 퇴역했다.
- `tests/test_web_selftest_gate.py`와 `python -m hwpxfiller.webapp --selftest`는 **실 WebView2**에서
  부팅·렌더·상호작용·브리지 왕복을 되읽는다. 실제 가시성, 포커스, 클릭, 상태 갱신은 이 층의
  책임이다.
- 동결 목업의 `data-vm`은 역사적 설계 참조일 뿐 현재 배포 DOM이나 라우팅의 실행 게이트가 아니다.

구조·공개 경계·실렌더는 서로 대체하지 않는다. 다만 모든 관심사를 다시 한 파일의 문자열
목록으로 모으지 않고, 실제 위험 경계의 장기 소유자에 둔다.

## 디자인 토큰, CSS와 문구의 단일 출처

- 원시 디자인 토큰의 단일 출처는 `src/hwpxfiller/gui/design_tokens.json`이다.
  `scripts/gen_design_tokens.py`가 커밋되는 `frontend/css/tokens.css`와 동결 목업의 생성 구간을 만든다.
  생성 드리프트는 `scripts/gen_design_tokens.py --check`, 사용자 안전 대비 하한은
  `tests/repo_contract/test_contrast_wcag.py`로 나눠 확인한다.
- 실제 레이아웃·컴포넌트 스타일의 단일 출처는 `frontend/css/` 아래 **9개 스타일시트**다
  (`base`·`draftcard`·`editor`·`job`·`overlay`·`library`·`forced-colors`·`jobdata`·`tail`).
  구 `app.css`의 순서 보존 컷이며 **캐스케이드 정본은 `frontend/src/main.js`의 CSS import
  순서**다. `tests/_web_source.py`의 `ALL_CSS_FILES`는 테스트용 공유 판독자이고,
  `tests/artifact_contract/test_frontend_build_graph.py`가 entry import의 해소·폐포를 확인한다.
  완료 이관기의 별도 파일·orphan census는 퇴역했다. 현재 앱을 판단할 때 동결 목업의 인라인
  CSS를 사용하지 않는다.
- 한 번만 쓰이는 정적 문구는 `frontend/index.html` 또는 해당 화면 JavaScript/Python 산출자가
  소유한다. 둘 이상에서 공유하는 사용자 문구만 명시적 공용 상수 모듈로 올린다(승격 대상이
  없으면 모듈도 두지 않는다 — 구 `frontend/js/copy.js` 는 R5-99 B2 에서 소비자 0 으로 삭제).
  문구 규율과 금지어는 [카피 스타일 가이드](COPY_STYLE_GUIDE.md)와 관련 테스트가 맡는다.
- **blocker 어포던스**(「그 blocker 를 사용자가 무엇으로 지우는가」)의 단일 출처는
  `src/hwpxfiller/webapp/blocker_affordance.py` 다. blocker 전건이 세 형태 중 하나를 **명시로**
  선언한다: 활성 동사(셀렉터 + dispatch 액션/직접 브리지 메서드) · 자동 진행(비활성 + 사유) ·
  설계상 동사 없음(알림 설계 — 생략이 아니라 선언). 이 표는 계약이라 세 층이 함께 지킨다 —
  정적 대조와 **역방향 고아 액션 0** 은 `tests/repo_contract/test_blocker_affordance_registry.py`,
  상태별 불변식은 `tests/test_webapp_job_blocker_affordance.py`, 실창 관측은
  `scripts/live101/scenario.py` 의 관리 검토 사슬(겨눔은 이 표에서 파생)이 진다. 사설 코드→
  셀렉터 표를 따로 두지 않는다(#912 D6 이 그 드리프트의 실측이다).

## 변경 규율

- 링1 공개 API를 바꾸면 이를 소비하는 컨트롤러와 관련 헤드리스 테스트를 함께 갱신한다.
- DOM `id`, `data-*`, entry 또는 화면 루트를 바꾸면 해당 JS 장기 소유자와 artifact 폐포 계약을
  갱신하고, 실제 동작이 관여하면 WebView2 selftest 시나리오도 갱신한다.
- 목업은 [동결 시안](UI_PROTOTYPE_APPB.html)이다. 현재 기능을 설계하거나 검증하기 위해 목업을
  먼저 고치지 않는다. 보존된 `data-vm` seam이 더는 유효하지 않을 때에만 역사 계약과 함께
  명시적으로 정리한다.
