/* N-04·N-05 중앙 합성 루트 — ESM 모듈을 조립하고, 아직 전역으로 읽는 소비자에게 되건다.

   #372 D-05 의 자리다: 임시 제품 전역은 **한 곳에서만** 만들고 각 항목은 생성 단계와 제거
   책임 이슈를 진다. N-04 의 잎 넷(copy·esc·guard·segview)에 이어 N-05 에서 공용 UI 서비스
   열다섯이 named export/factory 로 바뀌었지만, 소비자(화면 넷과 앱 셸 = N-06, 그리고 Python
   selftest 프로브)는 아직 `window.Modal` 처럼 읽는다. 그 간극을 파일마다 `window.X = …` 로
   메우면 전역 생산자가 다시 열아홉 곳에 흩어지고 "compat 수량이 단조 감소한다"는 D-05 의
   계측점이 사라진다 — 그래서 별칭은 여기 열아홉뿐이다.

   이 파일은 **조립만** 한다. 기능·상태·DOM·리스너를 여기 두지 않는다. 소비자가 ESM import
   로 옮겨가면(N-06) 해당 줄이 지워지고, 파일 자체의 제거 책임은 N-10 이다.

   ## 평가 순서가 계약이다

   제품 entry(`main.js`)가 이 모듈을 **모든 소비 IIFE 보다 먼저** import 하므로, static import
   가 main 본문보다 먼저 평가되는 ESM 규칙에 따라 열아홉 별칭은 소비자가 실행될 때 이미 서
   있다. entry 본문에서 나중에 대입하는 방식은 금지다 — 그 순간 소비 IIFE 는 이미 `undefined`
   를 읽은 뒤다.

   ## 두 가지 주입 형태와 그 이유

   서비스는 둘로 갈린다. 의존이 다른 ESM 모듈뿐인 것은 평범한 named export 라 여기서 그대로
   되걸고, `Bridge` 나 `Nav` 처럼 **아직 전역인 것**을 쓰는 것은 factory 로 내보내 여기서 딱
   한 번 구성한다. 서비스가 자기 안에서 전역을 뒤지지 않게 하는 것이 목적이다.

   ### `bridge` 는 **객체째** 넘긴다 — 메서드를 뽑으면 프로브가 무력화된다

   Python selftest 가 `window.Bridge.call = stub` 처럼 **프로퍼티를 교체**해 통로를 갈아끼운다
   (app.py 열 곳). 그래서 서비스는 객체 참조를 들고 있어야 스텁을 본다. 여기서 `{ call: … }`
   처럼 메서드를 값으로 뽑아 넘기면 스텁이 우회돼 요청은 프로브에 걸렸는데 발신은 실물로
   새는 자리가 생긴다 — `datazone.js` 가 요청 시점에 통로를 붙드는 이유와 같은 결함류다.

   ### `navigate` 는 **지연 호출**이다 — 그래야 순환이 안 생긴다

   `window.Nav` 는 `app.js`(N-06 소유, 아직 classic IIFE)가 만들고 이 모듈보다 **나중에**
   평가된다. 값으로 캡처하면 `undefined` 를 붙들고, `editor_entry` 가 `app.js` 를 import 하게
   만들면 `app.js → …services… → editor_entry → app.js` 순환이 선다(그 파일은 IIFE 본문에서
   `go(DEFAULT_SCREEN)` 을 즉시 실행하므로 평가 순서 함정이 실재한다). 호출 시점에 찾는 좁은
   콜백 하나가 그 간선을 모듈 그래프 밖으로 뺀다. `window.Nav` 판독이 서비스가 아니라 여기
   한 줄에만 남는 것이 요점이다. */
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

/* 아직 전역인 두 소비 대상. `bridge` 는 객체째(위 주석), `navigate` 는 지연 호출(위 주석). */
const bridge = window.Bridge;
const navigate = (...args) => window.Nav.go(...args);

/* 상태를 가진 서비스는 여기서 **정확히 한 번** 구성된다. 순서는 종전 entry 의 서비스 순서를
   따르되 `PathTrack` 만 한 칸 앞으로 온다 — `DataPicker` 가 그것을 주입받기 때문이다. 그
   서비스들은 부작용(위임 리스너 부착 등)을 구성 시점에 한 번 치르므로 두 번 부르면 리스너가
   겹친다. 재호출 방지는 서비스가 아니라 이 파일의 단일 호출이 진다. */
const Theme = createTheme({ bridge });
const Personalization = createPersonalization({ bridge });
const SheetPicker = createSheetPicker({ bridge });
const PathTrack = createPathTrack({ bridge });
const DataPicker = createDataPicker({ bridge, sheetPicker: SheetPicker, pathTrack: PathTrack });
const Relink = createRelink({ bridge });
const DataZone = createDataZone({ bridge });
const EditorEntry = createEditorEntry({ bridge, navigate });

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
