/* 제품 합성 루트 — ESM 모듈을 조립해 앱 하나를 세운다.

   ## 이 파일의 내력과 N-10 이 지운 것

   이 자리에는 `compat.js` 가 있었다. 그 파일은 **두 가지**를 했다: ①모듈을 조립하는 합성
   루트, ②아직 전역 이름으로 읽는 소비자를 위한 임시 별칭 스물일곱의 단일 생산자
   (#372 D-05). ②는 전환기의 부채였고
   N-10 이 그것을 0 으로 만들면서 파일 이름도 함께 은퇴했다 — **별칭 줄만 지우고 `compat`
   이라는 이름을 남기면 "호환 계층이 아직 있다"는 거짓 표식이 남는다**. 남은 책임은 ①뿐이고,
   그 책임의 정직한 이름이 bootstrap 이다.

   최종 허용 전역은 셋뿐이다:

   - `window.pywebview` — pywebview 런타임이 주입한다(제품 코드가 만들지 않는다)
   - `window.__hwpx` — 버전 있는 제품 공개 API. 생산자는 이 파일 하나(D-06)
   - `window.__hwpxTest` — 명시적 selftest 런타임에서만. 생산자는 `selftest/api.js` 하나(D-07)

   임시 별칭 스물일곱이 지던 소비는 전부 승계처가 있다: Python 직접 호출 → `window.__hwpx`
   (N-07), Python selftest 프로브 71곳 → 프런트 프로브 + `window.__hwpxTest`(N-08·N-09),
   프런트 모듈 간 참조 → 아래의 명시적 주입. 마지막 executable 소비자였던
   `scripts/capture_101_screenshots.py` 의 `window.Nav.go` 판독은 N-10 에서 DOM 경로로
   재배선했다.

   이 파일은 **조립만** 한다. 기능·상태·DOM·리스너를 여기 두지 않는다.

   ## 평가 순서가 계약이다

   제품 entry(`main.js`)는 이 모듈의 `bootProduct` 를 **정확히 한 번** 부른다. 화면·서비스는
   전부 이 모듈의 static import 로 그래프에 들어오고, ESM 규칙상 import 가 본문보다 먼저
   평가되므로 호출 시점에 모든 factory 가 서 있다. 구성 순서는 본문이 정한다:
   서비스 → 화면 넷 → 앱 셸 → 제품 API → 시험 배선. 앱 셸 구성은
   같은 의미로 `go(DEFAULT_SCREEN)` 을 즉시 실행하므로 서비스·화면보다 반드시 뒤에 선다.

   부작용을 **모듈 평가**가 아니라 **호출**이 지는 것이 `compat.js` 와의 실질적 차이다.
   import 만으로 앱이 서던 종전에는 이 그래프에 닿는 어떤 테스트도 앱 전체를 부팅시켰고,
   조립을 관측하려면 ESM 캐시를 질의 문자열로 우회해야 했다. 이제 조립은 부르는 쪽이 정한다.

   ## 두 가지 주입 형태와 그 이유

   의존이 다른 ESM 모듈뿐인 것은 평범한 named export 라 그대로 넘기고, `Bridge` 나 구성
   산물처럼 **값이 구성에서 나오는 것**은 factory 로 내보내 여기서 딱 한 번 구성한다.
   모듈이 자기 안에서 전역을 뒤지지 않게 하는 것이 목적이다.

   ### `bridge` 는 **객체째** 넘긴다 — 메서드를 뽑으면 프로브가 무력화된다

   selftest 프로브가 `Bridge.call = stub` 처럼 **프로퍼티를 교체**해 통로를 갈아끼운다.
   그래서 소비자는 객체 참조를 들고 있어야 스텁을 본다. 여기서 `{ call: … }` 처럼 메서드를
   값으로 뽑아 넘기면 스텁이 우회돼 요청은 프로브에 걸렸는데 발신은 실물로 새는 자리가
   생긴다 — `datazone.js` 가 요청 시점에 통로를 붙드는 이유와 같은 결함류다.

   ### 교차 화면·Nav 는 **late-bound 콜백**이다 — 그래야 순환이 안 생긴다

   화면 간 간선(library→job·editor→job·job→editor)과 화면→Nav 간선을 import 로 적으면
   editor↔job 순환이 그래프에 실린다. 그래서 그 간선들은 이 함수의 콜백 테이블이 진다:
   구성 시점엔 대상이 아직 없어도 되고(선언만 있으면 된다), 호출 시점에 그때의 대상을
   찾는다. `Nav` 는 앱 셸 구성 산물이라 화면 구성 **뒤에** 대입되지만, 콜백이 지연 호출이라
   화면은 그 전에 구성돼도 안전하다 — 값으로 캡처하는 구현으로 되돌아가면 cycle 게이트와
   합성 루트 계약 테스트가 잡는다. 이 테이블에 업무 상태·화면 수명주기 상태를 두지 않는다.

   ## 반환값은 전역의 후계가 아니다

   `bootProduct` 는 구성 산물을 **반환**한다. 이것은 별칭 스물일곱의 대체재가 아니다 —
   전역이 아니고, 레지스트리도 아니고, 어디에도 설치되지 않는다. 제품 entry 는 반환값을
   **쓰지 않는다**(부팅은 호출 자체로 끝난다). 이 값이 있는 이유는 하나다: 합성 루트가
   올바른 객체를 올바른 자리에 걸었는가를 묻는 테스트가, 종전에는 `window` 를 훔쳐보는
   것 말고 물을 방법이 없었다. 전역을 없애면서 그 질문까지 잃으면 "별칭이 사라졌다"는
   사실만 남고 "조립이 여전히 옳다"는 사실이 죽는다 — 선언은 살고 결과가 죽는 그 결함류다.
   그래서 관측면을 전역에서 반환값으로 옮긴다. 넓히지 않는다. */
import { Guard } from "../js/guard.js";

import { createTheme, createPersonalization } from "./shell/preferences.ts";
import { createModal } from "./overlay/modal.js";
import { createSurfaceSheet } from "../js/surface_sheet.js";
import { UndoToast } from "../js/undo_toast.js";
import { Popover } from "../js/popover.js";
import { Intent } from "../js/intent.js";

import { createAppShell } from "./shell/app.ts";
import { createBridge } from "../js/bridge.js";
import { createProductApi } from "./product_api.js";
import { createPushPort } from "./push_port.js";
import { bootReactRoot } from "./react/boot.ts";
import { createRuntimeAdapter } from "./runtime/adapter.ts";
import { createBridgeClient } from "./runtime/client.ts";
import { createShellNav } from "./shell/nav.ts";
import { createSnapshotStore } from "./state/store.ts";
import { createScreenRuntime } from "./screens/runtime.ts";
import { createScreenPorts } from "./screens/ports.ts";
import { createServiceHandoffPorts } from "./ports/service_handoff.ts";
import {
  PRODUCT_OVERLAY_COMPONENTS, createProductScreenVisibility, productOverlayComponent,
} from "./screens/product_screens.ts";
import { createProductScreenExecutor } from "./screens/product_screen_executor.ts";
import { createScreenLifecycleRegistry } from "./screens/screen_lifecycle_registry.ts";
import { createLibraryController } from "./screens/library.ts";
import { createDataPickerController } from "./screens/data_picker.ts";
import { createJobReadController } from "./screens/job_read.ts";
import { createJobRunController } from "./screens/job_run.ts";
import { createSlotConfigService } from "./screens/job_slot_config.ts";
import { createJobContentSelectionController } from "./screens/job_content_selection.ts";
import { createJobRelink } from "./screens/job_relink.ts";
import { createEditorController } from "./screens/editor.ts";
import { createEditorEntry } from "./screens/editor_entry.ts";
import { createWorkbenchController } from "./screens/workbench.ts";
import { createSheetPickerController } from "./screens/sheet_picker.ts";
import { bootSelftest } from "./selftest/boot.js";

/** 제품 하나를 조립해 세운다 — 제품 entry 가 **정확히 한 번** 부른다.
 *
 *  이 함수는 멱등이 아니다. 두 번 부르면 서비스 셋(`popover`·`undo_toast`·`pathtrack`)이
 *  위임 리스너를 한 벌 더 붙이고 앱 셸이 랜딩을 다시 찍는다. 재호출 방지는 서비스가 아니라
 *  **호출자가 하나뿐이라는 사실**이 진다(`main.js` 한 줄, 정적 게이트가 그 유일성을 센다).
 *
 *  @returns {{bridge: object, pushPort: object, productApi: object, services: object,
 *    client: object, store: object}}
 *    구성 산물. entry 는 쓰지 않는다 — 합성 계약을 묻는 테스트의 관측면이다(머리말 참조).
 */
export function bootProduct() {
  const dataSheetClose = document.getElementById("dataSheetClose");
  if (dataSheetClose === null) {
    throw new Error("R4 React close button host가 없습니다: #dataSheetClose");
  }
  /* 브리지는 여기서 **정확히 한 번** 구성된다(N-07). 종전에는 `bridge.js` 가 IIFE 로
     `window.Bridge`·`window.__push` 를 스스로 만들고 합성 루트가 그걸 되읽었다 — 생산자가
     둘로 갈린 마지막 자리였다.

     `bridge` 는 **객체째** 아래로 넘어간다. selftest 프로브가 `Bridge.call = stub` 처럼
     프로퍼티를 교체해 통로를 갈아끼우므로, 메서드를 값으로 뽑으면 스텁이 우회된다. */
  const { bridge, push, testHost } = createBridge();

  /* 관측 푸시의 단일 활성 통로(N-09) — 제품 스냅샷 처리기와 selftest 프로브가 **같은** 통로를
     부르게 한다. 값으로 붙들면 프로브의 가로채기를 우회하고, 그 침묵이 배선 부재로 읽힌다
     (`push_port.js` 머리말 · N-07 #379 §5 에서 실제로 한 번 났다). */
  const pushPort = createPushPort(push);

  /* 스냅샷 store (R2-03 · #407) — Python 권위 스냅샷의 전송-충실 보관소. React 소비의
     유일한 store 경계이고, 여기서 **정확히 한 번** 구성된다(reload 시 재구성 = renderers
     와 같은 수명). 탭은 **브리지 채널**(포트 하류)에 선다: selftest 프로브가 pushPort 를
     `override` 로 갈아끼우면(mirror·reject) legacy render 와 store 가 **같은 세계**를
     본다 — 파사드 처리기 옆에 탭을 두면 reject 중에도 store 만 갱신돼 두 소비자가 갈린다
     (관측자 오염, N-07 #379 §5 결함류). 채널 목록은 생성 계약 유도라 손 목록이 없고,
     `ingest` 는 안정 함수라 값으로 넘겨도 늦은 결속이 깨지지 않는다(리스너 예외는 store
     안에서 격리·경보되므로 이 탭이 같은 채널 뒤 legacy render 를 죽이지 않는다).
     `services` 에 싣지 않는 이유는 store가 시험에서 교체할 전송 표면이 아니기 때문이다.
     반대로 client는 R4 React 화면이 실제로 부르는 살아 있는 객체라 아래 selftest 주입 표에
     싣는다. 그래야 기존 probe가 합성 snapshot 위에서 dispatch를 갈아끼울 때 typed 경로만
     실 백엔드로 새지 않는다. */
  const store = createSnapshotStore({
    alarm: (message) => console.error("[hwpx] snapshot store 리스너 실패", message),
  });
  for (const screen of store.channels) {
    bridge.onPush(screen, (snapshot) => store.ingest(screen, snapshot));
  }

  /* R4 화면 런타임은 React boot보다 먼저 선다. raw push의 제품 구독자는 위 store tap 하나고,
     화면 model과 임시 job-run adapter는 그 하류에서 같은 사건 순서를 본다. */
  const client = createBridgeClient({ adapter: createRuntimeAdapter({ win: window }) });
  const runtime = createScreenRuntime({ client, store });
  const screenPorts = createScreenPorts();
  const servicePorts = createServiceHandoffPorts();

  /* late-bound 좌표 — 아래에서 구성되면 채워진다. 콜백이 지연 호출이라 선언만 먼저 선다. */
  let Nav;

  /* 화면→Nav 간선. `Nav` 는 앱 셸 구성 산물이라 마지막에 대입된다. */
  const navigation = {
    go: (...args) => Nav.go(...args),
    refresh: (...args) => Nav.refresh(...args),
    /* 「지금 어느 화면인가」의 관측면. 화면이 이것을 **DOM 으로** 물으면(`#scr-job` 의
       `.on` 판독) React 서브트리가 legacy 화면 루트를 붙들게 되고, 같은 판정이 상태기계와
       DOM 두 곳에 산다 — R3-02 가 세운 「판정은 상태기계」의 직접 소비 자리다. */
    currentScreen: () => Nav.currentScreen(),
  };

  /* editor·library→job 간선 — 소비 메서드만 좁게 싣는다(전 표면을 실으면 절단이 무의미). */
  const jobCallbacks = {
    refreshList: (...args) => screenPorts.jobRead.current().refreshList(...args),
    openBrowseNeedsAction: (...args) => screenPorts.jobRead.current().openBrowseNeedsAction(...args),
  };

  /* job→editor 간선. */
  const editorCallbacks = {
    aimAt: (...args) => EditorController.aimAt(...args),
  };

  /* EditorEntry 의 착지 콜백 — N-05 에선 `window.Nav` 판독이었지만 Nav 생산이 합성 루트로
     들어오면서 지역 late-bound 로 좁혀졌다. `window.Nav` 판독은 이제 어디에도 없다. */
  const navigate = (...args) => Nav.go(...args);

  /* 상태를 가진 서비스는 여기서 **정확히 한 번** 구성된다. 순서는 종전 그대로 — 그 서비스들은
     부작용(위임 리스너 부착 등)을 구성 시점에 한 번 치르므로 두 번 부르면 리스너가 겹친다. */
  const Theme = createTheme({ bridge });
  const Personalization = createPersonalization({ bridge });
  const Modal = createModal({ popover: Popover });
  const SurfaceSheet = createSurfaceSheet({ modal: Modal });
  /* R4-02 — 시트 선택·편집기 진입 seam 은 React 구현이 **유일한 owner** 다. legacy 구현이
     남지 않으므로 handoff 할 상대가 없다: 빈 port 에 한 번 결속하고, 둘째 결속은 throw 한다
     (중간 dual-dispatch 창이 애초에 생기지 않는다). */
  const SheetPickerController = createSheetPickerController({
    doc: document, client, modal: Modal,
  });
  const SheetPicker = SheetPickerController.port;
  const EditorEntry = createEditorEntry({
    doc: document, client, modal: Modal, navigate,
    notify: (message) => window.alert(message),
  });

  servicePorts.sheetPicker.bind(SheetPicker);
  servicePorts.relink.bind(createJobRelink({
    client, modal: Modal, alarm: (message) => window.alert(message),
  }));
  screenPorts.editorEntry.bind(EditorEntry);

  /* 화면 넷 — 구성 순서는 구 entry 의 IIFE 평가 순서 그대로다. 교차 간선은 위 콜백 테이블로
     받으므로 구성 시점의 상호 참조가 없다. */
  const LibraryController = createLibraryController({
    doc: document,
    runtime, client, ports: screenPorts, services: servicePorts,
    modal: Modal, undo: UndoToast, popover: Popover,
    navigation,
    notify: (message) => window.alert(message),
  });
  const DataPicker = createDataPickerController({
    doc: document,
    runtime, client, services: servicePorts, modal: Modal,
    notify: (message) => window.alert(message),
  });
  const JobRead = createJobReadController({
    runtime, client, ports: screenPorts, services: servicePorts,
    modal: Modal, popover: Popover, surfaceSheet: SurfaceSheet, dataPicker: DataPicker,
    navigation, doc: document,
    notify: (message) => window.alert(message),
  });
  const EditorController = createEditorController({
    doc: document,
    runtime, client, ports: screenPorts, services: servicePorts,
    modal: Modal, popover: Popover, chain: Intent,
    navigation,
    /* 고르기 단계 우 열의 「고정」·「계약 목록 등록」은 **데이터 선택 컨트롤러가 가진
       `#poolRegModal` 을 그대로 연다**(U6-B #976) — 확인 왕복·pin 잠금·pclm 좌표가 한
       벌이라 두 번째 구현을 세우면 그 한 벌이 갈린다. 그래서 간선은 값이 아니라 포트다. */
    poolRegistration: {
      openRegDialog: (options) => DataPicker.openRegDialog(options),
      openPclm: () => DataPicker.openPclm(),
    },
    notify: (message) => window.alert(message),
  });
  const WorkbenchController = createWorkbenchController({
    doc: document, runtime, client, modal: Modal, chain: Intent, navigation,
    notify: (message) => window.alert(message),
  });
  /* R4-03 — 실행·결과 표면의 단일 owner. legacy `screens/job.js` 는 이 커밋에서 사라지므로
     `createJobRunAdapter` 를 거치는 임시 fan-out 도 함께 은퇴한다(port 를 직접 결속한다). */
  const JobRunController = createJobRunController({
    runtime, client, ports: screenPorts, services: servicePorts,
    modal: Modal, navigation, doc: document,
    selectionLine: Guard.selectionLine,
    notify: (message) => window.alert(message),
  });
  /* SX-02(#725) — 「문서 만들기」 "포함할 내용" zone. 순수 slot config 서비스(4 dispatch 왕복,
     local optimistic authority 0)를 job 화면 composition 에 잇는다. 컨트롤러가 job 스냅샷의
     read-only slot_configuration view 로 passive hydrate 하므로 mount 는 open()(write-on-read)을
     부르지 않는다(#744). loud 실패는 alert 로 착지시킨다(조용한 삼킴 0). */
  const SlotConfigService = createSlotConfigService({
    client,
    alarm: (message) => window.alert(message),
  });
  /* S9-03(#829) — 보관된 선택(Preset)의 이름 입력·덮어쓰기 확인은 공유 모달 파사드가 진다
     (판정·수치는 Python, 문안·확인 UI 는 웹). */
  const JobContentSelectionController = createJobContentSelectionController({
    runtime, service: SlotConfigService, modal: Modal,
  });
  const DataPickerService = {
    init: () => DataPicker.init(),
    open: (...args) => DataPicker.open(...args),
  };

  /* 셸 상태기계 (R3-02 · #411) — 라우팅·ready·닫기 직렬화 **판정**의 단일 정본. 여기서
     **정확히 한 번** 구성된다(reload 시 재구성 = store·renderers 와 같은 수명). 집행자
     결속은 아래 adapter 구성이 정확히 1회 지고, 두 번째 결속은 상태기계가 throw 한다 —
     `bootProduct` 재호출 방지가 「호출자 유일성」에 더해 구조 한 겹을 얻었다. */
  const shellNav = createShellNav();
  const visibility = createProductScreenVisibility();
  const lifecycle = createScreenLifecycleRegistry();
  lifecycle.register("editor", {
    leaveTo: (...args) => EditorController.leaveTo(...args),
    rerender: () => EditorController.rerender(),
  });
  lifecycle.register("workbench", {
    leaveTo: (...args) => WorkbenchController.leaveTo(...args),
  });
  shellNav.bindExecutor(createProductScreenExecutor({
    doc: document,
    bridge,
    visibility,
    lifecycle,
    reclaimSurfaces: () => SurfaceSheet.closeAllAndRestore(),
    notify: (message) => window.alert(message),
  }));

  const initSequence = [
    /* 서식 폴더 행(U6-A #975)이 읽는 `tpl` 첫 스냅샷 — 다른 화면 init 과 같은 줄에 세운다.
       (호스트 준비 대기 자체는 `runtime.loadInitial` 이 구조로 진다 — 이 자리에 있는 것은
       순서 안전이 아니라 「부팅에 당기는 채널 전수」를 한 표로 읽히게 하려는 것이다.) */
    () => runtime.loadInitial("tpl"),
    () => LibraryController.init(),
    () => EditorController.init(),
    () => JobRunController.init(),
    () => WorkbenchController.init(),
    () => DataPicker.init(),
  ];

  /* 앱 셸 집행 adapter — 마지막. 구성이 곧 부팅 랜딩(`go("job")`)이라 화면·서비스 뒤에
     선다. 셸 리스너·부팅 시퀀스는 여기서 **서술**(`shellHost`)로만 캡처되고, 부착/해제
     수명주기는 아래 React root 의 ShellHost effect 가 진다(R3-02). */
  const appShell = createAppShell({
    Bridge: bridge, modal: Modal, Personalization, shellNav, initSequence,
    refreshScreen: (screen) => runtime.refresh(screen),
  });
  Nav = appShell.Nav;
  const AppCloseGuard = appShell.AppCloseGuard;

  /* 구성 산물 전수 — 시험 배선과 반환값이 같은 표를 쓴다. 골라 넘기지 않는 이유는
     `bootSelftest` 호출부 주석에 있다. */
  const services = {
    Bridge: bridge, Client: client, Nav, AppCloseGuard,
    Guard, Popover, Intent, UndoToast,
    Modal, SurfaceSheet, Theme, Personalization, SheetPicker,
    DataPicker: DataPickerService, EditorEntry,
    JobRun: JobRunController,
  };

  /* 제품 공개 경계(N-07 · D-06) — Python 이 부르는 유일한 이름이다. 종전에는 Python 이
     `window.__push`·`window.AppCloseGuard.prompt`·`window.Personalization.apply`·`window.Theme.apply`·
     `window.alert` 다섯 내부 이름을 직접 알고 불렀다. N-10 뒤 그 이름들은 전역에 없다.

     처리기 표의 키는 파사드가 광고하는 능력 이름과 같은 레지스트리에서 나온다 — 광고했는데
     처리기가 없는 상태를 구조적으로 막는 것이 그 파일의 요지다. */
  const productApi = createProductApi({
    handlers: {
      /* 관측 푸시 — 화면은 불투명한 라우팅 값이라 여기서도 해석하지 않는다.

         **포트로 보낸다**(구성 산물 `push` 를 값으로 붙들지 않는다). selftest 프로브가 열세
         곳에서 `ctx.push` 자리에 기록용 래퍼를 **대입해** 도착한 푸시를 관측하는데, 여기서
         지역 `push` 를 캡처하면 제품 푸시가 그 래퍼를 **우회해** 프로브가 "푸시 0" 을 보고,
         그 침묵이 배선 부재처럼 읽힌다 — `bridge` 를 객체째 넘기는 이유와 정확히 같은
         결함류이고, 실제로 이 자리에서 한 번 재발했다(job_mirror·job_result 두 게이트가 잡았다).

         N-07 은 이것을 `window.__push` **전역 지연 판독**으로 고쳤다. N-09 는 같은 늦은 결속을
         유지하되 전역이 아니라 포트로 옮겼고, N-10 이 그 전역을 지웠다. 이 경로는 처음부터
         전역에 의존하지 않았으므로 별칭 삭제가 여기를 건드리지 않는다. */
      snapshot: (payload) => pushPort.dispatch(payload.screen, payload.snapshot),

      /* 네이티브 X 닫기 확인 — **시작만** 한다. 처분은 모달이 브리지로 되돌린다. */
      "close-request": (payload) => AppCloseGuard.prompt(payload.state),

      /* 부팅 설정 주입 — 돌려주는 것은 **실제로 적용한 조각 이름**이다.
         조각별로 따로 감싸는 이유: 테마가 죽어도 개인화가 살았다는 사실을 잃지 않기 위해서다.
         여기서 예외를 삼키는 것은 침묵이 아니다 — 빠진 이름이 곧 실패 신고이고, Python 이
         그 이름을 받아 내구성 경보로 지목한다(조용한 성공 접기의 반대). */
      preferences: (payload) => {
        const applied = [];
        try {
          Personalization.apply(payload.personalization);
          applied.push("personalization");
        } catch { /* 보고에서 빠지는 것이 실패 신고다 */ }
        if (payload.theme === "light" || payload.theme === "dark") {
          try {
            Theme.apply(payload.theme);
            applied.push("theme");
          } catch { /* 위와 같다 */ }
        }
        return applied;
      },

      /* 사후 고지 — 내구성 기록은 Python 이 이미 마쳤다. 이쪽은 창 계층 best effort. */
      notice: (payload) => window.alert(payload.message),
    },
  });

  /* 제품 공개 API — 제품 코드가 만드는 전역은 정상 실행에서 **이 하나뿐**이다(D-06).
     임시 별칭 스물일곱은 N-10 에서 사라졌고 이 줄만 남았다. */
  window.__hwpx = productApi;

  /* 시험 능력(N-09, D-07) — **호스트가 대는 경우에만** 선다.
     정상 실행에서는 `testHost.available()` 이 거짓이라 아무것도 설치되지 않고, 이 호출은
     전역도 부작용도 남기지 않는다. 활성화 조건은 URL·빌드 플래그가 아니라 호스트 프로세스의
     시험 메서드 존재 하나뿐이다 — 그래서 정상 실행과 시험 실행이 **같은 번들**을 쓴다.

     `window.__hwpxTest` 는 제품 API `__hwpx` 와 **다른 계정**이다: 제품 표면이 아니므로 정상
     실행에 존재해서는 안 된다. 생산자는 `selftest/api.js` 의 `defineProperty` 하나뿐이라 이
     파일에는 그 이름이 등장하지 않는다.

     반환 Promise 를 기다리지 않는다 — 부팅을 시험 배선에 매달지 않는다. 파이썬은 능력이 설
     때까지 준비 표현식을 폴링한다(그쪽이 시한과 경보를 진다). */
  bootSelftest({
    win: window,
    doc: document,
    testHost,
    pushPort,
    /* 구성 산물 **전수** — 객체째 넘긴다(프로퍼티 교체 관측이 성립해야 한다).
       골라 넘기지 않는 이유: 프로브 일부가 `ctx.services[name]` 으로 **동적 조회**를 해서
       정적 검색으로는 필요 목록을 셀 수 없다. 실제로 골라 넘겼다가 `SheetPicker`·`Preserve`·
       `DataPicker` 셋이 빠져 실엔진에서 세 프로브가 죽었다(러너가 이름을 대며 시끄럽게
       실패해 한 번에 보였다). 전수를 넘기면 그 결함류가 구조적으로 사라지고, 러너는 프로브가
       선언한 것만 쓰므로 더 넘겨서 생기는 손해는 없다. */
    services,
    alarm: (result) => {
      /* 호스트가 시험용으로 띄웠는데 능력이 서지 못한 경우 — 조용하면 안 된다. 파이썬은
         뒤이어 "파사드 부재" 로 죽는데, 그때 **왜** 못 섰는지는 이 줄에만 남는다. */
      window.console.error("[hwpx] selftest 능력 설치 실패", result);
    },
  });

  /* overlay dismissal 계열 문서 리스너 (R3-01 · #410 개정 10) — **bootProduct 구성 시**
     상시 부착이다. 모듈 평가가 아니라 이 호출이 부작용을 진다(머리말의 합성 루트 계약).
     React host effect 도 아니다 — effect 는 커밋 뒤 비동기라 「구성 시」가 아니고, 마운트
     실패가 팝오버 바깥닫기까지 조용히 걷는 두 번째 실행 경로가 된다. 모달 keydown 은
     첫 open 부착(instance.ts·개정 4)이라 언제나 이 목록 **뒤** 순서 — Escape 층화(팝오버
     먼저 닫히고 최상위 모달 나중)가 부착 순서로 선다. 해제는 없다: reload = 신품 그래프. */
  for (const attachment of Popover.documentAttachments) {
    const target = attachment.target === "window" ? window : document;
    target.addEventListener(attachment.type, attachment.handler, attachment.capture === true);
  }

  /* React root (R2-01 · #405) — 기존 조립 **뒤에** 선다. legacy 두 트리와 겹치지 않는
     `#reactRoot` 하나가 React 소유 경계의 전부이고, React 를 아는 것은 `./react/boot.ts`
     쪽이다(`.js` 그래프는 bare import 0 을 유지한다 — 정적 게이트가 잰다).

     실패는 시끄럽고 부팅은 계속된다 — 그러나 R3-01(overlay 표면 4)·R3-02(셸 리스너·부팅
     시퀀스)부터 이 트리는 제품 경로다: 마운트 실패 = 확인 창·탭 응답·화면 init 이 서지
     않는다. 그 실패를 조용히 접지 않고 경보(alert)로 착지시키는 것이 이 배선의 계약이고,
     Vanilla fallback 은 만들지 않는다(#405 불변식). node 의 합성 루트 테스트 환경에선 대역
     DOM 이 실 createRoot 를 통과하지 못해 이 경보가 매번 도는 것이 허용 상태다 — 실물
     커밋 증거는 live 게이트의 마운트 마커 되읽기가 진다. */
  bootReactRoot({
    doc: document,
    alarm: (message) => {
      console.error("[hwpx] React root 부팅 실패", message);
      window.alert(message);
    },
    /* R2-03 — 트리의 StoreSignal 이 이 store 를 구독한다. boot.ts 가 늦은 결속 슬롯으로
       요소 factory 에 넘기므로 여기서는 객체째 한 번 건네면 된다. */
    store,
    /* R3-01 — 트리의 OverlayHost 가 완전 데이터-구동 표면 4(confirm·choose·prompt·토스트)를
       렌더·집행한다. 문서 리스너는 여기 몫이 아니다(dismissal=위 구성 시 부착, keydown=
       instance.ts 첫 open 부착). */
    overlay: {
      doc: document,
      notify: (message) => window.alert(message),
    },
    /* R3-02 — 트리의 ShellHost 가 셸 리스너 부착/해제와 부팅 시퀀스(ready 사건 훅 →
       상태기계 markReady → init 5)를 소유한다. 서술은 adapter 구성 시 캡처된 것을 그대로
       넘긴다 — 여기서 풀어 헤치면 합성 루트가 두 번째 셸 조립자가 된다. */
    shell: appShell.shellHost,
    /* R4-04 — static stage 하나에 제품 화면 넷을 한 portal로, overlay는 같은 subtree의
       기존 target으로 보낸다. ProductScreens가 target 중복·static child를 fail-closed한다. */
    screens: {
      doc: document,
      visibility,
      library: LibraryController,
      editor: EditorController,
      workbench: WorkbenchController,
      jobRead: JobRead,
      jobRun: JobRunController,
      slotContent: JobContentSelectionController,
      dataPicker: DataPicker,
        sheetPicker: SheetPickerController,
      dataSheetClose,
      overlays: [
        productOverlayComponent("poolRegModal", PRODUCT_OVERLAY_COMPONENTS.PoolRegistrationDialog,
          { controller: DataPicker }),
        productOverlayComponent("dataPickerModal", PRODUCT_OVERLAY_COMPONENTS.DataPickerDialog,
          { controller: DataPicker }),
        productOverlayComponent("dataSheetSlot", PRODUCT_OVERLAY_COMPONENTS.JobDataBody,
          { controller: JobRead, location: "sheet" }),
        productOverlayComponent("jobBrowseSheet", PRODUCT_OVERLAY_COMPONENTS.JobBrowseDialog,
          { controller: JobRead }),
        productOverlayComponent("txtEditModal", PRODUCT_OVERLAY_COMPONENTS.TxtEditDialog,
          { controller: EditorController }),
        /* 항목 상세 시트(U6-E #979) — 행 ⋮ 의 「자세히…」가 여는 면. 편집기 컨트롤러를
           받지만 그리는 값은 `tpl` 채널 스냅샷 한 존(`detail`)이다. */
        productOverlayComponent("tplDetailModal", PRODUCT_OVERLAY_COMPONENTS.TplDetailSheet,
          { controller: EditorController }),
        productOverlayComponent("sheetModal", PRODUCT_OVERLAY_COMPONENTS.SheetPickerDialog,
          { controller: SheetPickerController }),
        productOverlayComponent("artifactSheet", PRODUCT_OVERLAY_COMPONENTS.JobArtifactSheet,
          { controller: JobRunController }),
        /* 셸 설정 모달 — 셸 서비스 셋(테마·개인화·모달)과 job 컨트롤러 하나를 받는다.
           앞 셋의 판정·영속은 서비스가 그대로 지고, 저장 폴더는 Python 도출이라 그 값을
           싣는 스냅샷의 주인(JobRunController)을 포트로 받는다 — 전역 값이라 화면이 job 에
           있든 없든 같은 면이 같은 값을 그린다. */
        productOverlayComponent("settingsModal", PRODUCT_OVERLAY_COMPONENTS.SettingsSheet,
          {
            theme: Theme, personalization: Personalization, modal: Modal,
            job: JobRunController,
            /* 서식 폴더 행(U6-A #975) — 값의 주인은 tpl 채널이라 그 모델을 그대로 구독한다.
               화면 컨트롤러를 하나 더 세우지 않는 이유는 이 면이 tpl 의 **한 존**만 읽기
               때문이다(같은 상태를 두 곳이 판정하지 않는다). */
            templates: {
              subscribe: (listener) => runtime.model("tpl").subscribe(listener),
              getSnapshot: () => runtime.model("tpl").getSnapshot(),
              pickTemplatesRoot: () => bridge.pickTemplatesRoot("tpl"),
              refreshCurrentScreen: () => runtime.refresh(Nav.currentScreen()),
              /* 경로 어포던스의 전송 표면은 이 포트가 직접 든다 — 저장 폴더 포트의 것을
                 빌리면 서식 폴더 행이 남의 컨트롤러에 묶인다. */
              client,
              notify: (message) => window.alert(message),
            },
          }),
      ],
    },
  });

  return { bridge, pushPort, productApi, services, client, store };
}
