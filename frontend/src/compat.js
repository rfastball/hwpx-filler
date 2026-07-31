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

/* 아직 전역인 유일한 소비 대상(N-07 소유). 객체째 — 위 주석. */
const bridge = window.Bridge;

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
