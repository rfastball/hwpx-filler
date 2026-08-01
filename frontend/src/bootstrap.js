/* 제품 합성 루트 — ESM 모듈을 조립해 앱 하나를 세운다.

   ## 이 파일의 내력과 N-10 이 지운 것

   이 자리에는 `compat.js` 가 있었다. 그 파일은 **두 가지**를 했다: ①모듈을 조립하는 합성
   루트, ②아직 전역 이름으로 읽는 소비자를 위한 임시 별칭 스물일곱(`window.Modal`·
   `window.Nav`·`window.JobScreen` …)의 단일 생산자(#372 D-05). ②는 전환기의 부채였고
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
   서비스 → 화면 넷 → 앱 셸 → 제품 API → 시험 배선. 앱 셸 구성은 구 `app.js` IIFE 평가와
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

/** 제품 하나를 조립해 세운다 — 제품 entry 가 **정확히 한 번** 부른다.
 *
 *  이 함수는 멱등이 아니다. 두 번 부르면 서비스 셋(`popover`·`undo_toast`·`pathtrack`)이
 *  위임 리스너를 한 벌 더 붙이고 앱 셸이 랜딩을 다시 찍는다. 재호출 방지는 서비스가 아니라
 *  **호출자가 하나뿐이라는 사실**이 진다(`main.js` 한 줄, 정적 게이트가 그 유일성을 센다).
 *
 *  @returns {{bridge: object, pushPort: object, productApi: object, services: object}}
 *    구성 산물. entry 는 쓰지 않는다 — 합성 계약을 묻는 테스트의 관측면이다(머리말 참조).
 */
export function bootProduct() {
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

  /* EditorEntry 의 착지 콜백 — N-05 에선 `window.Nav` 판독이었지만 Nav 생산이 합성 루트로
     들어오면서 지역 late-bound 로 좁혀졌다. `window.Nav` 판독은 이제 어디에도 없다. */
  const navigate = (...args) => Nav.go(...args);

  /* 상태를 가진 서비스는 여기서 **정확히 한 번** 구성된다. 순서는 종전 그대로 — 그 서비스들은
     부작용(위임 리스너 부착 등)을 구성 시점에 한 번 치르므로 두 번 부르면 리스너가 겹친다. */
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

  /* 구성 산물 전수 — 시험 배선과 반환값이 같은 표를 쓴다. 골라 넘기지 않는 이유는
     `bootSelftest` 호출부 주석에 있다. */
  const services = {
    Bridge: bridge, Nav, AppCloseGuard,
    Copy, escHtml, Guard, SegView, Popover, Preserve, Intent, UndoToast,
    Modal, SurfaceSheet, GroupList, Theme, Personalization, SheetPicker,
    PathTrack, Relink, DataZone, DataPicker, EditorEntry,
    LibraryScreen, EditorScreen, JobScreen, WorkbenchScreen,
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

  return { bridge, pushPort, productApi, services };
}
