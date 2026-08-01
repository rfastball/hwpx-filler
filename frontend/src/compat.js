/* N-04·N-05·N-06 중앙 합성 루트 — ESM 모듈을 조립하고, 아직 전역으로 읽는 소비자에게 되건다.

   #372 D-05 의 자리다: 임시 제품 전역은 **한 곳에서만** 만들고 각 항목은 생성 단계와 제거
   책임 이슈를 진다. N-04 의 잎 넷, N-05 의 공용 UI 서비스 열다섯에 이어 N-06 에서 화면 넷과
   앱 셸이 named factory 로 바뀌었다. 남은 전역 소비자는 Python selftest 프로브와 Python 의
   직접 호출(`window.Nav.go`·`window.JobScreen.renderResult`·`window.AppCloseGuard.prompt` 등,
   app.py)뿐이며, 그 간극을 파일마다 `window.X = …` 로 메우면 생산자가 다시 흩어지고 "compat
   수량이 단조 감소한다"는 D-05 의 계측점이 사라진다 — 그래서 별칭은 여기 스물다섯뿐이다.

   이 파일은 **조립만** 한다. 기능·상태·DOM·리스너를 여기 두지 않는다. Python 소비가 versioned
   `window.__hwpx` 로 옮겨가면(N-07~N-09) 해당 별칭이 지워지고, 파일 자체의 제거 책임은
   N-10 이다.

   ## 평가 순서가 계약이다

   제품 entry(`main.js`)는 이제 `bridge.js` 와 이 모듈 둘만 싣는다. `bridge.js` 가 앞이어야
   아래의 `window.Bridge` 캡처가 실물을 붙든다. 화면·서비스는 전부 이 모듈의 static import
   로 그래프에 들어오고, ESM 규칙상 import 가 본문보다 먼저 평가되므로 구성 시점에 모든
   factory 가 서 있다. 구성 순서는 본문이 정한다: 서비스 → 화면 넷 → 앱 셸 → 별칭. 앱 셸
   구성은 구 `app.js` IIFE 평가와 같은 의미로 `go(DEFAULT_SCREEN)` 을 즉시 실행하므로
   서비스·화면보다 반드시 뒤에 선다.

   ## 두 가지 주입 형태와 그 이유

   의존이 다른 ESM 모듈뿐인 것은 평범한 named export 라 여기서 그대로 되걸고, `Bridge` 나
   구성 산물처럼 **값이 구성에서 나오는 것**은 factory 로 내보내 여기서 딱 한 번 구성한다.
   모듈이 자기 안에서 전역을 뒤지지 않게 하는 것이 목적이다.

   ### `bridge` 는 **객체째** 넘긴다 — 메서드를 뽑으면 프로브가 무력화된다

   Python selftest 가 `window.Bridge.call = stub` 처럼 **프로퍼티를 교체**해 통로를 갈아끼운다
   (app.py 열 곳). 그래서 소비자는 객체 참조를 들고 있어야 스텁을 본다. 여기서 `{ call: … }`
   처럼 메서드를 값으로 뽑아 넘기면 스텁이 우회돼 요청은 프로브에 걸렸는데 발신은 실물로
   새는 자리가 생긴다 — `datazone.js` 가 요청 시점에 통로를 붙드는 이유와 같은 결함류다.

   ### 교차 화면·Nav 는 **late-bound 콜백**이다 — 그래야 순환이 안 생긴다

   화면 간 간선(library→job·editor→job·job→editor)과 화면→Nav 간선을 import 로 적으면
   editor↔job 순환이 그래프에 실린다. 그래서 그 간선들은 이 파일의 콜백 테이블이 진다:
   구성 시점엔 대상이 아직 없어도 되고(선언만 있으면 된다), 호출 시점에 그때의 대상을
   찾는다. `Nav` 는 앱 셸 구성 산물이라 화면 구성 **뒤에** 대입되지만, 콜백이 지연 호출이라
   화면은 그 전에 구성돼도 안전하다 — 값으로 캡처하는 구현으로 되돌아가면 cycle 게이트와
   compat 계약 테스트가 잡는다. 이 테이블에 업무 상태·화면 수명주기 상태를 두지 않는다. */
import { Copy } from "../js/copy.js";
import { escHtml } from "../js/esc.js";
import { Guard } from "../js/guard.js";
import { SegView } from "../js/segview.js";

import { createTheme } from "../js/theme.js";
import { createPersonalization } from "../js/personalization.js";
import { Preserve } from "../js/preserve.js";
import { Modal } from "../js/modal.js";
import { SurfaceSheet } from "../js/surface_sheet.js";
import { UndoToast } from "../js/undo_toast.js";
import { createSheetPicker } from "../js/sheet_picker.js";
import { createDataPicker } from "../js/data_picker.js";
import { createPathTrack } from "../js/pathtrack.js";
import { createRelink } from "../js/relink.js";
import { Popover } from "../js/popover.js";
import { createDataZone } from "../js/datazone.js";
import { Intent } from "../js/intent.js";
import { GroupList } from "../js/grouplist.js";
import { createEditorEntry } from "../js/editor_entry.js";

import { createLibraryScreen } from "../js/screens/library.js";
import { createEditorScreen } from "../js/screens/editor.js";
import { createJobScreen } from "../js/screens/job.js";
import { createWorkbenchScreen } from "../js/screens/workbench.js";
import { createAppShell } from "../js/app.js";
import { createBridge } from "../js/bridge.js";
import { createProductApi } from "./product_api.js";
import { createPushPort } from "./push_port.js";
import { bootSelftest } from "./selftest/boot.js";

/* 브리지는 이제 여기서 **정확히 한 번** 구성된다(N-07). 종전에는 `bridge.js` 가 IIFE 로
   `window.Bridge`·`window.__push` 를 스스로 만들고 이 파일이 그걸 되읽었다 — 생산자가 둘로
   갈린 마지막 자리였다. 구성 산물을 아래에서 별칭으로 되걸므로 소비자 표면은 그대로다.

   `bridge` 는 **객체째** 아래로 넘어간다. selftest 프로브가 `Bridge.call = stub` 처럼
   프로퍼티를 교체해 통로를 갈아끼우므로, 메서드를 값으로 뽑으면 스텁이 우회된다. */
const { bridge, push, testHost } = createBridge();

/* 관측 푸시의 단일 활성 통로(N-09) — 제품 스냅샷 처리기와 selftest 프로브가 **같은** 통로를
   부르게 한다. 값으로 붙들면 프로브의 가로채기를 우회하고, 그 침묵이 배선 부재로 읽힌다
   (`push_port.js` 머리말 · N-07 #379 §5 에서 실제로 한 번 났다). */
const pushPort = createPushPort(push);

/* late-bound 좌표 — 아래에서 구성되면 채워진다. 콜백이 지연 호출이라 선언만 먼저 선다. */
let LibraryScreen;
let EditorScreen;
let JobScreen;
let WorkbenchScreen;
let Nav;

/* 화면→Nav 간선. `Nav` 는 앱 셸 구성 산물이라 마지막에 대입된다. */
const navigation = {
  go: (...args) => Nav.go(...args),
  refresh: (...args) => Nav.refresh(...args),
};

/* editor·library→job 간선 — 소비 메서드만 좁게 싣는다(전 표면을 실으면 절단이 무의미). */
const jobCallbacks = {
  refreshList: (...args) => JobScreen.refreshList(...args),
  openPreview: (...args) => JobScreen.openPreview(...args),
  openBrowseNeedsAction: (...args) => JobScreen.openBrowseNeedsAction(...args),
};

/* job→editor 간선. */
const editorCallbacks = {
  aimAt: (...args) => EditorScreen.aimAt(...args),
};

/* EditorEntry 의 착지 콜백 — N-05 에선 `window.Nav` 판독이었지만 Nav 생산이 이 파일로
   들어오면서 지역 late-bound 로 좁혀졌다. `window.Nav` 판독은 이제 어디에도 없다. */
const navigate = (...args) => Nav.go(...args);

/* 상태를 가진 서비스는 여기서 **정확히 한 번** 구성된다. 순서는 종전 그대로 — 그 서비스들은
   부작용(위임 리스너 부착 등)을 구성 시점에 한 번 치르므로 두 번 부르면 리스너가 겹친다.
   재호출 방지는 서비스가 아니라 이 파일의 단일 호출이 진다. */
const Theme = createTheme({ bridge });
const Personalization = createPersonalization({ bridge });
const SheetPicker = createSheetPicker({ bridge });
const PathTrack = createPathTrack({ bridge });
const DataPicker = createDataPicker({ bridge, sheetPicker: SheetPicker, pathTrack: PathTrack });
const Relink = createRelink({ bridge });
const DataZone = createDataZone({ bridge });
const EditorEntry = createEditorEntry({ bridge, navigate });

/* 화면 넷 — 구성 순서는 구 entry 의 IIFE 평가 순서 그대로다. 교차 간선은 위 콜백 테이블로
   받으므로 구성 시점의 상호 참조가 없다. */
LibraryScreen = createLibraryScreen({
  Bridge: bridge, Nav: navigation, JobScreen: jobCallbacks, EditorEntry, PathTrack, Relink,
});
EditorScreen = createEditorScreen({
  Bridge: bridge, Nav: navigation, JobScreen: jobCallbacks, EditorEntry, PathTrack, SheetPicker,
});
JobScreen = createJobScreen({
  Bridge: bridge, Nav: navigation, EditorScreen: editorCallbacks,
  DataZone, PathTrack, Relink, EditorEntry, DataPicker,
});
WorkbenchScreen = createWorkbenchScreen({ Bridge: bridge, Nav: navigation });

/* 앱 셸 — 마지막. 구성이 곧 부팅 랜딩(`go("job")`)이라 화면·서비스 뒤에 선다. */
const appShell = createAppShell({
  Bridge: bridge, Theme, Personalization, DataPicker,
  screens: {
    library: LibraryScreen, editor: EditorScreen, job: JobScreen, workbench: WorkbenchScreen,
  },
});
Nav = appShell.Nav;
const AppCloseGuard = appShell.AppCloseGuard;

/* 제품 공개 경계(N-07 · D-06) — Python 이 부르는 유일한 이름이다. 종전에는 Python 이
   `window.__push`·`window.AppCloseGuard.prompt`·`window.Personalization.apply`·`window.Theme.apply`·
   `window.alert` 다섯 내부 이름을 직접 알고 불렀다. 그 이름들은 아래에서 임시 별칭으로 계속
   살지만(selftest 가 아직 71곳에서 쓴다 — N-08·N-09 소유), **제품 호출은 여기로만 온다**.

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
       유지하되 전역이 아니라 포트로 옮긴다: 프런트 프로브는 이제 전역이 아니라 `ctx.push` 를
       갈아끼우므로, 두 소비자가 만나는 자리가 전역일 이유가 없어졌다. 전역 별칭은 N-10 계정을
       위해 아래에 남지만 **이 경로는 그것에 의존하지 않는다**. */
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

window.Copy = Copy;
window.escHtml = escHtml;
window.Guard = Guard;
window.SegView = SegView;
window.Popover = Popover;
window.Preserve = Preserve;
window.Intent = Intent;
window.UndoToast = UndoToast;
window.Modal = Modal;
window.SurfaceSheet = SurfaceSheet;
window.GroupList = GroupList;
window.Theme = Theme;
window.Personalization = Personalization;
window.SheetPicker = SheetPicker;
window.PathTrack = PathTrack;
window.Relink = Relink;
window.DataZone = DataZone;
window.DataPicker = DataPicker;
window.EditorEntry = EditorEntry;
window.LibraryScreen = LibraryScreen;
window.EditorScreen = EditorScreen;
window.JobScreen = JobScreen;
window.WorkbenchScreen = WorkbenchScreen;
window.Nav = Nav;
window.AppCloseGuard = AppCloseGuard;
/* 구 `bridge.js` IIFE 가 스스로 만들던 둘 — 이제 생산자는 이 파일 하나다(D-05).
   제거 책임은 N-10. Python selftest 71곳이던 소비자는 N-09 에서 0 이 됐고, 남은 것은
   전역 이름을 아직 쓰는 프런트 소비자뿐이다.

   `__push` 는 **포트의 dispatch** 를 가리킨다 — 전역으로 들어와도 갈아끼운 통로를 지나게
   해서, 별칭이 사는 동안 두 입구가 갈리지 않게 한다. */
window.Bridge = bridge;
window.__push = pushPort.dispatch;

/* 임시 별칭 스물일곱과 **다른 계정**이다 — 이건 제품 최종 공개 API 다(N-07, D-06).
   위 별칭들은 N-10 에서 사라지지만 이 줄은 남는다. */
window.__hwpx = productApi;

/* 시험 능력(N-09, D-07) — **호스트가 대는 경우에만** 선다.
   정상 실행에서는 `testHost.available()` 이 거짓이라 아무것도 설치되지 않고, 이 호출은
   전역도 부작용도 남기지 않는다. 활성화 조건은 URL·빌드 플래그가 아니라 호스트 프로세스의
   시험 메서드 존재 하나뿐이다 — 그래서 정상 실행과 시험 실행이 **같은 번들**을 쓴다.

   `window.__hwpxTest` 는 위 별칭 27 과도, 제품 API `__hwpx` 와도 **다른 세 번째 계정**이다:
   임시 별칭이 아니므로 N-10 의 단조 감소 계측에 들지 않고, 제품 표면이 아니므로 정상 실행에
   존재해서는 안 된다. 생산자는 `selftest/api.js` 의 `defineProperty` 하나뿐이라 이 파일에는
   그 이름이 등장하지 않는다.

   반환 Promise 를 기다리지 않는다 — 부팅을 시험 배선에 매달지 않는다. 파이썬은 능력이 설
   때까지 준비 표현식을 폴링한다(그쪽이 시한과 경보를 진다). */
bootSelftest({
  win: window,
  doc: document,
  testHost,
  pushPort,
  /* 프로브가 쓰는 구성 산물 열 — **객체째** 넘긴다(프로퍼티 교체 관측이 성립해야 한다). */
  services: {
    Bridge: bridge, Nav, Modal, Intent, Popover, SurfaceSheet,
    PathTrack, Personalization, Theme, JobScreen,
  },
  alarm: (result) => {
    /* 호스트가 시험용으로 띄웠는데 능력이 서지 못한 경우 — 조용하면 안 된다. 파이썬은
       뒤이어 "파사드 부재" 로 죽는데, 그때 **왜** 못 섰는지는 이 줄에만 남는다. */
    window.console.error("[hwpx] selftest 능력 설치 실패", result);
  },
});
