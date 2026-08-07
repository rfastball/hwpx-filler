"""canonical 프런트엔드 **정적 소스**의 DOM 계약.

``test_ui_contract.py`` 는 목업(``docs/UI_PROTOTYPE_APPB.html``)의 ``data-vm`` 주석이
생존 ViewModel 표면과 정합한지만 보는 역사 가드다. 이 모듈이 현재 정본인 실제
소스 역할의 index와 JavaScript/CSS 배선을 읽어 **전역 id 유일성**, 화면 구조와 정적 seam을
단언한다. 실제 렌더·클릭·브리지 왕복은 ``test_web_selftest_gate.py``의 WebView2 게이트가 맡는다.

배경(#27): ``id="dataLabel"`` 이 실행(run)·즉시기안(txt) 두 화면에 중복돼, 전역
``getElementById`` 가 항상 첫 화면 요소만 반환 → txt 갱신이 run 입력을 건드리는 크로스-스크린
오염이 있었다. 이 테스트가 그 재발을 CI 에서 직접 차단한다(접근성 계약 강화는 #27 잔여 범위).
"""
from __future__ import annotations

import re
from collections import Counter
from html.parser import HTMLParser

from _web_source import (
    ALL_CSS_FILES,
    REPO_ROOT,
    REACT_JOB_RUN_FILES,
    SOURCE_BOOTSTRAP,
    SOURCE_CSS_DIR,
    SOURCE_ENTRY,
    SOURCE_INDEX,
    SOURCE_JS_DIR,
    SOURCE_ROOT,
    app_css,
    react_job_run_source,
    reaches_product_graph,
    linked_css,
    source_text,
)

WEB_INDEX = SOURCE_INDEX
# web/ 앱 스타일시트는 분할됐다 — 여기서만 **문자열**(조각을 링크 순서대로 이어붙인 구
# app.css 등가)이다.
WEB_CSS = app_css()
# (web-diff/ 짝 가드는 hwpx-diff 저장소 분리와 함께 그쪽 test_web_dom_contract.py 로 갔다.)

# 반응형 경계(#27): 창 최소폭(760)보다 넓은 이 경계에서 2판 레이아웃이 세로 적층으로 접혀야
# 최소 크기에서도 가로 오버플로 없이 쓸 수 있다. 경계나 접힘 규칙이 사라지면 회귀.
RESPONSIVE_BREAKPOINT_PX = 820

# 전체 스냅샷 재렌더가 포커스·캐럿·스크롤을 뭉개지 않도록 render() 를 Preserve.around 로 감싸는
# 화면들(#28). 어느 화면이 래핑을 조용히 떨구면 상호작용 유실 회귀 → 정적 가드로 차단.
WEB_JS_DIR = SOURCE_JS_DIR
R4_SCREENS_DIR = SOURCE_ROOT / "src" / "screens"
R4_JOB_READ = R4_SCREENS_DIR / "job_read.ts"
R4_DATA_ZONE = R4_SCREENS_DIR / "data_zone.ts"
R4_LIBRARY = R4_SCREENS_DIR / "library.ts"
R4_DATA_PICKER = R4_SCREENS_DIR / "data_picker.ts"
R4_PORTS = R4_SCREENS_DIR / "ports.ts"
R4_EDITOR = R4_SCREENS_DIR / "editor.ts"
R4_EDITOR_ENTRY = R4_SCREENS_DIR / "editor_entry.ts"
R4_EDITOR_STATE = R4_SCREENS_DIR / "editor_state.ts"
R4_WORKBENCH = R4_SCREENS_DIR / "workbench.ts"
R4_SHEET_PICKER = R4_SCREENS_DIR / "sheet_picker.ts"
R4_GROUP_MOVE = R4_SCREENS_DIR / "group_move_dialog.ts"
# R4-03 — 실행·결과 표면 다섯. 개별 파일을 겨눠야 하는 계약(제목 생산자 단일성 등)만 이
# 상수를 쓰고, 「실행 표면이 무엇을 하는가」를 묻는 계약은 `react_job_run_source()` 로 읽는다.
R4_JOB_RUN = R4_SCREENS_DIR / "job_run.ts"
R4_JOB_RESULT = R4_SCREENS_DIR / "job_result.ts"
R4_JOB_PREVIEW = R4_SCREENS_DIR / "job_preview.ts"
R4_PRODUCT_SCREENS = R4_SCREENS_DIR / "product_screens.ts"
R4_PRODUCT_EXECUTOR = R4_SCREENS_DIR / "product_screen_executor.ts"
# 렌더 래핑·데이터 피커 계약은 **표면을 소유한 파일**을 따라간다 — 화면 파일명과 1:1 이
# 아니다. draftsession.js 는 「기안」 화면과 함께 사망(F6 PR-B) — 승계 표면인 작업대가
# 맞추기 표 렌더를 같은 래핑으로 보존한다(workbench.js renderMap).
# (R4-02: editor·workbench 는 이 목록에서 빠졌다 — React 소유에서는 재구성 자체가 없어
#  「되찾을 포커스·캐럿」이 생기지 않는다. 그 자리를 대신 지키는 것은 draft reducer 이고,
#  아래 :func:`test_preserve_helper_loaded_and_wraps_screen_renders` 가 두 축을 함께 잰다.)
#: R4-03 로 **0 이 됐다**. 남길 것은 목록이 아니라 질문이다 — 「재구성이 포커스·캐럿·
#: 스크롤을 뭉개지 않는가」. React 소유에서는 서브트리 재구성 자체가 없어 되찾을 것이
#: 생기지 않고, 그 자리를 draft reducer(값의 소유)가 지킨다. 빈 튜플로 남기는 이유는 legacy
#: 렌더 층이 되살아나면 이 목록이 다시 채워져야 함을 표식으로 두기 위해서다.
PRESERVE_WRAPPED_FILES: tuple[str, ...] = ()

#: 재구성 대신 **값의 소유**로 보존을 푸는 React 표면 — 편집 가능한 컨트롤이 전부 draft
#: reducer 에서 값을 읽어야 한다(스냅샷 push 가 입력 중인 값을 덮지 않는 구조적 거처).
DRAFT_OWNED_FILES = (R4_EDITOR, R4_WORKBENCH)

# 렌더 층 **가변 모듈 상태 예산**. Python 이 상태를 단일 소유하고 스냅샷을 미는 모델에서 JS 의
# 가변 모듈 상태는 전부 "스냅샷이 답하지 않아 표면이 답하는 것"이다 — 조용히 자라면 파생 가능한
# 값을 저장한 뒤 그것을 읽어 DOM 을 미는 **전이 함수**가 딸려 오고, 상태 조합은 곱셈으로 늘어
# 전이가 그 조합만큼 갈린다(F3·F4 리뷰의 상태-누수 P1·P2 다수가 이 계열).
#
# 상한은 **현재 실측값**이고 비교는 `<=` 다 — 즉 **줄이는 건 언제나 통과하고 늘리는 것만 시끄럽다**.
# 넘기려면 두 출구가 먼저다: ①스냅샷에서 파생해 변수를 지운다 ②Python 스냅샷으로 승격한다.
# 그래도 필요하면(순수 뷰 찌꺼기 — 펼침·실측 픽셀·옵서버 핸들) 상한을 올리되 **파생 불가 사유를
# 선언 옆 주석으로** 남긴다. 정리 자체는 메인 흐름 배선(F5~F8) 완주 후 일괄이고, 이 예산은
# 그때까지 **천장만** 지킨다(사용자 확정 2026-07-27).
#
# `const`(팩토리·헬퍼·상수)는 세지 않는다 — 병은 가변성이지 모듈 스코프가 아니다. `datazone.js`
# 가 0 인 것이 도달 가능한 목표라는 증거고, `screens/job.js` 17 은 이 앱에서 유일하게 **긴 수명의
# 절차**(데이터 선택 → 게이트 → 생성 → 결과 → 강등)를 담기 때문이다. 숙주는 파일 크기가 아니라
# 절차의 길이 — 절차를 늘리는 슬라이스(F7 재시도)가 이 천장을 먼저 만나야 한다.
# R4-03 로 legacy 화면이 0 이 되면서 이 예산의 **정의역이 통째로 옮겼다** — 렌더 층은 이제
# `frontend/src/screens/*.ts` 다. 예산을 legacy 경로에 남기면 없는 파일에 천장을 매기는 유령
# 행이 되고(그 자리는 늘 초록), 새 렌더 층은 처음부터 자유가 된다.
MUTABLE_MODULE_STATE_BUDGET = {
    # 실행 표면 — 이 앱에서 유일하게 **긴 수명의 절차**(데이터 선택 → 게이트 → 생성 → 결과
    # → 강등)를 담는다. 실측 10: 실행 정체 6(run·ui·attached·releaseModel·lastFullSeen·
    # lastProgressSeen) + 확인 면 복귀 트리거 1 + 렌더 지역 3(banner·level·text).
    # 앞의 여섯은 파생 불가다 — 스냅샷은 「이 화면이 무엇을 구독했는가」「어느 응답을 이미
    # 봤는가」를 모른다(부착·관측은 스냅샷 밖 사건이고, 그것을 Python 으로 올리면 웹 구독
    # 상태를 백엔드가 소유하는 역전이 된다). 구 legacy 판 상한은 15 였고 실측 13 이었다.
    "job_run.ts": 10,
    # (screens/template.js 는 화면 사망으로 파일째 삭제 — F8 §10.17. 관리·저작 상태는
    #  editor.js 의 libMenuFor·txtEdit 2객체로 이주했다.)
    # screens/draft.js·draftsession.js 는 화면 사망으로 파일째 삭제(F6 PR-B).
    # 작업대(F6) — 스냅샷 1개(LAST)뿐이다. 작업점·복사 이력·미저장 변경·린트를 전부
    # Python 이 소유하므로 표면이 들 것이 없다(데이터 존이 없는 화면이라 더 그렇다).
    # +1(N-06): wired — init 멱등 가드(initial 없는 화면이라 seated 는 없다).
    # (screens/workbench.js·screens/editor.js 는 R4-02 에서 React 로 이관되며 파일째
    #  사라졌다 — 그 화면들의 가변 상태는 이제 소유권 인벤토리 `state_js_module` 축이
    #  `.ts` 까지 같은 분모로 센다. 여기 남기면 없는 파일에 예산을 매기는 유령 행이 된다.)
    # 편집기 — LAST·접힘 2종 + deep-link 조준 대기 1슬롯(pendingAim, F6 PR-B §10.14.3).
    # pendingAim 은 파생 불가다: 스냅샷은 「이 조준을 이미 소비했는가」를 모른다(한 번성
    # 사건이지 상태가 아니다) — 스냅샷에 승격하면 소비 후 무효화 스킴이 따라온다.
    # +2(F8): libMenuFor(열린 라이브러리 ⋮ 메뉴의 정체)·txtEdit(TXT 저작 모달의 열림 거래)
    # — tpl 화면 사망의 관리·저작 동사 승계. 둘 다 파생 불가(뷰의 한 번성 거래 상태 —
    # template.js 5변수의 이주분을 각 1객체로 묶음).
    # +1(U2 §2.4 리뷰 R2): pendingFieldEdit — 「아직 커밋되지 않은 타이핑이 있는가」.
    # **정의상 파생 불가**다. 두 출구가 원리적으로 막혀 있다: ①스냅샷은 이 사실을 모른다
    # (모르는 것이 이 변수의 존재 이유 — 텍스트 입력은 change=blur 에서만 발신한다)
    # ②Python 승격 = 키스트로크마다 발신인데, 그건 `docs/WEB_RENDER_PRESERVATION.md` 가
    # 명시적으로 기각한 설계다(타이핑 중 재구성 없음이 Preserve 의 전제).
    # 없으면 저장 게이트가 blur 전까지 잠긴 채라 방금 고친 사람의 **첫 클릭이 삼켜진다**.
    # +1(PR #355 2R): folderImportInFlight — 폴더 일괄 가져오기 흐름(스캔→확정→실행)의
    # 진행 중 표지. 파생 불가: ①스냅샷은 「지금 이 표면이 연 왕복이 미정착인가」를 모른다
    # (배치 push 는 끝에 1회 — 진행 중은 스냅샷 밖 사건) ②DOM(버튼 disabled) 파생은 진행
    # 중 도착하는 무관 push 재렌더가 도로 풀어 버린다. 판정 정본은 Python 비차단 잠금이고
    # 이 플래그는 재클릭을 삼키는 어포던스 잠금이다.
    #
    # (위 산문 다수는 legacy 화면 파일의 것이었고, 그 파일들이 R4-01~R4-03 에서 사라지며
    #  근거도 함께 은퇴했다. 아래 넷은 오늘 실측 천장이다 — `<=` 비교라 정리는 늘 통과한다.)
    "job_read.ts": 15,           # R4-01 — 표·후보·탐색 시트의 뷰 찌꺼기(타이머·세대·꼬리)
    "editor.ts": 6,              # R4-02 — draft·wired·view·gate·display·body
    "library.ts": 4,             # R4-01 — axisTail·menuFor·moveState·content
    "group_move_dialog.ts": 3,   # R4-02 — 열림 거래 3(state·request·confirmed)
    "ports.ts": 3,               # R4-01 — 결속 슬롯의 소유·구현·인계 표지
    "data_picker.ts": 2,         # R4-01 — 다이얼로그 열림 상태 2
    "sheet_picker.ts": 2,        # R4-02 — 확정 게이트의 세션·순번
    "editor_entry.ts": 1,        # R4-02 — 복귀 초점 1슬롯
    "workbench.ts": 1,           # R4-02 — draft
    "job_result.ts": 1,          # R4-03 — 진행바 pct(렌더 지역 파생)
    "job_run_state.ts": 1,       # R4-03 — 토큰 발급 직렬 번호
    "context_menu.ts": 1,        # R4-04 — 메뉴 store의 현재 snapshot
    "product_screens.ts": 1,     # R4-04 — visibility store의 현재 화면
}

# 살아있는 컴포넌트 갤러리(개발 전용) — 실 tokens.css+app.css 를 <link> 로 물어 드리프트 0.
GALLERY = REPO_ROOT / "docs" / "UI_GALLERY.html"

# 화면 루트 — 셸 라우터가 표시/숨김으로 전환하는 최상위 컨테이너(회귀 시 화면 소실).
SCREEN_ROOTS = (
    # 홈(scr-home)은 사망(재작성 F2 PR-A) — 저장된 작업을 찾는 자리는 「문서 작업」
    # 라이브러리(§19.6 browser+detail)가 잇는다.
    "scr-library",
    # 「템플릿 관리」(scr-tpl)는 사망(F8 §10.17) — 목록·저작·변환·검토·그룹·삭제는 편집기
    # 「템플릿」 탭이 승계했다(TemplateController 는 채널로 생존, 소비자만 바뀜).
    # 「데이터 관리」(scr-pool)는 사망(재작성 F1) — 등록 데이터의 목록·수명은 데이터 선택
    # 다이얼로그가 승계했다(PoolController 는 생존, 소비자만 바뀜).
    # 「작업」(R-flow · #90) — 유일 생성 표면(실행 화면=슬라이스 3 사망) + 편집 모드(작업
    # 에디터 별도 화면=슬라이스 5 사망, 결정 39 흡수 — 정의 surface 는 scr-job 내부).
    "scr-job",
    # 「기안」(scr-draft)은 사망(F6 PR-B) — TXT 생성은 편집기 TXT 밴드·검토는 작업대가
    # 승계했다(§10.15.15).
    "scr-editor",
    "scr-workbench",
)

# 화면별 데이터 라벨은 반드시 고유 id 여야 한다(#27 dup-id 회귀 가드).
# draftDataLabel 은 화면과 함께 사망(F6 PR-B) — 데이터 존의 소비자는 job 하나다.
SCOPED_DATA_LABELS = ("jobDataLabel",)

# 상단 토바 탭(회귀 시 화면 소실·접근 이름 소실 → #27) — **계약 2탭 최종 형상**(F8 완성).
# run=슬라이스 3·editor=슬라이스 5 사망(흡수); 「기안」 F6 PR-B·「템플릿 관리」 F8 사망;
# 「데이터 관리」는 데이터 선택 다이얼로그로 흡수·사망(F1); home 은 라이브러리로 사망(F2 PR-A).
# 좌 레일은 F2 PR-B 에서 상단 탭으로 교체. 과도기 임시 탭 기제(.temp·.nav-sep·제거 예고
# title)는 F8 에 제도째 은퇴 — 아래 최종 형상 고정 테스트가 부활을 막는다.
NAV_SCREENS = ("library", "job")

# 커스텀 모달 → aria-labelledby 가 가리켜야 할 제목 id(다이얼로그 시맨틱, #27/#28).
# sheetModal 은 다중 시트 확정 게이트(#33) — 같은 Modal 헬퍼·다이얼로그 계약을 공유한다.
MODAL_LABELLEDBY = {
    "txtEditModal": "txtEditTitle",  # 템플릿 관리의 「새 TXT」·편집(template.js) — 화면 아닌 관리 모달(생존)
    # pasteModal·draftSaveTplModal 은 「기안」 화면과 함께 사망(F6 PR-B).
    "sheetModal": "sheetTitle",
    "poolRegModal": "poolRegTitle",  # 데이터 고정·등록(#26 #4 → F1 승계, 다이얼로그 위 스택)
    "dataPickerModal": "dataPickerTitle",  # 데이터 선택 통합 면(재작성 F1 — pool 화면 승계)
    # 「작업」 덮어쓰기 확인은 슬라이스 2(A-2-22)에서 공용 confirmModal(수치 합성 본문)로 이관 —
    # 전용 jobOverwriteModal DOM 폐기(아래 test_job_overwrite_uses_shared_confirm_modal 가드).
    # confirmModal·promptModal·chooseModal 3종은 R3-01(#410)에서 React host 렌더로 이전 —
    # 아래 HOST_MODAL_LABELLEDBY 가 정적 **부재** + host 렌더 소유의 양면을 진다.
    # draftMapSheet 은 「기안」과 함께 사망(F6 PR-B) — 맞추기 표는 작업대 #wbMapPanel 승계.
    "dataSheet": "dataSheetTitle",  # 작업 데이터 펼침 면(#271/#272 — 기안 몫은 F6 PR-B 사망)
    # jobConfirmSheet(작업 거울·재진술 펼침 면 #272)은 U2 §2.13 에서 사망 — 확인 면은
    # 시트로 승격한 생성 값 미리보기(#previewSheet) 하나다.
    "previewSheet": "previewTitle",
}

# R3-01(#410) — 완전 데이터-구동 다이얼로그 3종은 React host(src/overlay/host.ts)가 같은
# id·클래스·ARIA 로 렌더한다. 정적 index.html 은 **부재**가 계약이다: 재도입하면 host 렌더와
# id 가 중복되고(문서 순서상 정적 골격이 getElementById 를 선점) 두 세계 분열이 된다.
# 렌더 결과 검증은 node overlay_host.test.js(실 서버 렌더)와 live 게이트가 진다.
HOST_MODAL_LABELLEDBY = {
    "confirmModal": "confirmModalTitle",  # 네이티브 window.confirm 대체(#86) + 덮어쓰기 확인
    "promptModal": "promptModalTitle",  # 네이티브 window.prompt 대체(#86)
    # 답이 셋인 자리(재작성 F7 — patch 처분: 저장하고 이동·버리고 이동·머무르기). 확인 모달로
    # 두 번 물으면 "취소가 무엇을 취소하는지"가 갈리고 그 모호함이 곧 조용한 파기다.
    "chooseModal": "chooseModalTitle",
}

# React가 정적 골격을 인수한 렌더 표면. 정적 부재+소스 소유만 보면 실행 중 렌더가 빠진
# 회귀를 못 보고, 실행 테스트만 보면 index.html 골격이 되살아난 두 세계 분열을 못 본다.
# 그래서 표면마다 정적 계약과 브라우저/runtime 쌍을 한 행에 둔다.
REACT_RENDER_CONTRACT = {
    "src/overlay/host.ts": {
        "static_owner": HOST_MODAL_LABELLEDBY,
        "runtime_twins": (
            "tests/js/overlay_host.test.js",
            "tests/test_react_overlay_live.py",
        ),
    },
}


def _strip_js_comments(src: str) -> str:
    """JS 소스에서 주석을 걷는다 — **금지 이름 검사의 전처리**.

    이 저장소의 주석은 죽은 이름·함정을 일부러 적어 둔다(`.job-item` 산출자 0곳,
    구 표시 라벨 파생의 위험 등). 그것을 규칙으로 세면 설명이 계약을 깨는 거짓 실패가
    난다 — CSS 쪽 `_web_source.strip_comments` 와 같은 규율의 JS 판이다.
    """
    no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", no_block)


class _IdCollector(HTMLParser):
    """모든 요소의 ``id`` 속성값을 등장 순서대로 수집(중복 포함)."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: "list[str]" = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "id" and value:
                self.ids.append(value)


class _NavButtonCollector(HTMLParser):
    """``class="navbtn"`` 버튼의 속성 사전을 ``data-scr`` 키로 수집."""

    def __init__(self) -> None:
        super().__init__()
        self.buttons: "dict[str, dict[str, str]]" = {}

    def handle_starttag(self, tag, attrs):
        if tag != "button":
            return
        d = {name: (value or "") for name, value in attrs}
        classes = d.get("class", "").split()
        if "navbtn" in classes:
            self.buttons[d.get("data-scr", "")] = d


class _ModalCollector(HTMLParser):
    """``MODAL_LABELLEDBY`` 키에 해당하는 모달 컨테이너의 속성 사전을 id 키로 수집."""

    def __init__(self) -> None:
        super().__init__()
        self.modals: "dict[str, dict[str, str]]" = {}

    def handle_starttag(self, tag, attrs):
        d = {name: (value or "") for name, value in attrs}
        mid = d.get("id", "")
        if mid in MODAL_LABELLEDBY:
            self.modals[mid] = d


def _collect_ids() -> "list[str]":
    parser = _IdCollector()
    parser.feed(WEB_INDEX.read_text(encoding="utf-8"))
    return parser.ids


def _collect_modals() -> "dict[str, dict[str, str]]":
    parser = _ModalCollector()
    parser.feed(WEB_INDEX.read_text(encoding="utf-8"))
    return parser.modals


def _collect_nav_buttons() -> "dict[str, dict[str, str]]":
    parser = _NavButtonCollector()
    parser.feed(WEB_INDEX.read_text(encoding="utf-8"))
    return parser.buttons


def test_web_index_exists():
    assert WEB_INDEX.exists(), f"정적 프런트엔드 소스가 없습니다: {WEB_INDEX}"


def test_all_element_ids_are_globally_unique():
    """실제 DOM 의 전역 id 유일성 — 중복이 있으면 getElementById 가 크로스-스크린 오염(#27)."""
    counts = Counter(_collect_ids())
    dupes = {i: n for i, n in counts.items() if n > 1}
    assert not dupes, (
        "frontend/index.html 에 중복 id 가 있습니다(전역 getElementById 오염 위험): "
        + ", ".join(f"{i}×{n}" for i, n in sorted(dupes.items()))
    )


def test_screen_roots_present():
    ids = set(_collect_ids())
    product = R4_PRODUCT_SCREENS.read_text(encoding="utf-8")
    assert not set(SCREEN_ROOTS) & ids, "화면 root가 정적 셸과 ProductScreens에 이중 생산됩니다."
    for root in SCREEN_ROOTS:
        screen = root.removeprefix("scr-")
        assert product.count(f'"{screen}"') >= 1, f"ProductScreens 화면 root가 사라졌습니다: {root}"


def test_scoped_data_labels_present_and_unique():
    """React producer의 화면별 데이터 라벨은 정확히 한 곳에서 생산된다."""
    counts = Counter(_collect_ids())
    job_read = R4_JOB_READ.read_text(encoding="utf-8")
    for label in SCOPED_DATA_LABELS:
        assert counts[label] == 0, f"{label} 정적 골격이 React producer와 함께 존재합니다."
        assert job_read.count(f'id: "{label}"') == 1, (
            f"{label} React 생산자가 정확히 한 곳이어야 합니다."
        )
    # 공용 dataLabel 이 다시 들어오면 크로스-스크린 오염 재발 → 명시적으로 금지.
    assert counts["dataLabel"] == 0, "공용 id='dataLabel' 재도입 — 화면별 고유 id 로 분리하세요(#27)."


def test_nav_buttons_have_accessible_name_and_tooltip():
    """각 탭은 접근 이름(aria-label)과 호버 툴팁(title)을 버튼별로 고정해야 한다(#27).

    좁은 창에서 라벨이 줄어들어도 이름이 남아야 하고, 툴팁은 탭이 무슨 화면인지(그리고 임시
    항목이면 언제 사라지는지) 말하는 유일한 자리다.
    """
    buttons = _collect_nav_buttons()
    missing = [s for s in NAV_SCREENS if s not in buttons]
    assert not missing, f"탭이 사라졌습니다(data-scr): {missing}"
    for scr in NAV_SCREENS:
        attrs = buttons[scr]
        assert attrs.get("aria-label", "").strip(), (
            f"navbtn[data-scr={scr}] 에 비어있지 않은 aria-label 이 필요합니다 — 접근 이름 소실(#27)."
        )
        assert attrs.get("title", "").strip(), (
            f"navbtn[data-scr={scr}] 에 비어있지 않은 title 이 필요합니다 — 호버 툴팁 소실(#27)."
        )


def test_shell_is_the_final_two_tab_shape_with_no_transitional_apparatus():
    """셸 최종 형상 고정(F8 §10.17.2 판정 E) — 과도기 임시 탭 **기제 자체의 은퇴** 선언.

    「기안」(F6 PR-B)·「템플릿 관리」(F8)가 차례로 죽어 계약 2탭만 남았다. 임시 표지(.temp)·
    구분선(.nav-sep)·제거 예고 title 이 하나라도 되살아나면 과도기 기제가 부활 통로로 남았다는
    뜻이다(공회전 루프로 남겨 두면 그게 다음 임시 탭의 근거가 된다). 계약 2탭은 예고를 달지
    않는다 — 최종 형상이 조용히 흐려지지 않게.
    """
    buttons = _collect_nav_buttons()
    index = WEB_INDEX.read_text(encoding="utf-8")
    assert set(buttons) == set(NAV_SCREENS), f"셸 탭이 계약 2탭이 아닙니다: {sorted(buttons)}"
    assert index.count('class="nav-sep"') == 0, "탭 구분선(.nav-sep)은 임시 탭 제도와 함께 은퇴했습니다."
    for scr, attrs in buttons.items():
        assert "temp" not in attrs.get("class", ""), (
            f"navbtn[data-scr={scr}] 에 임시 표지(.temp) — 과도기 기제는 F8 에 은퇴했습니다."
        )
        assert "사라집니다" not in attrs.get("title", ""), (
            f"navbtn[data-scr={scr}] title 이 제거를 예고합니다 — 계약 2탭은 예고를 달지 않습니다."
        )


def test_nav_has_visual_marker_and_shell_is_topbar():
    """각 탭에 상시 보이는 아이콘 표지(.ni SVG)가 있고, 셸은 상단 토바여야 한다(#27 개정 · F2 PR-B).

    .ni 는 앱 디자인 언어 채택으로 SVG 아이콘으로 승격돼 라벨과 상시 공존한다(중복이 아니라
    스캔 보조). 셸 교체(지도 §10.9)로 좌 레일과 그 접기가 죽었으므로, 접힘 규칙이 되살아나면
    표면 없는 상태가 CSS 에 남았다는 뜻이다 — 다음 세션이 그걸 근거로 레일을 되살린다.
    """
    index = WEB_INDEX.read_text(encoding="utf-8")
    marker_count = index.count('class="ni"')
    assert marker_count == len(NAV_SCREENS), (
        f"탭 시각 표지(.ni)가 {marker_count}개 — 버튼마다 정확히 1개여야 합니다(#27)."
    )
    assert 'class="topbar"' in index and 'class="rail"' not in index, (
        "셸이 상단 토바가 아닙니다 — 좌 레일은 F2 PR-B 에서 사망했습니다(지도 §10.9)."
    )
    css = "".join(WEB_CSS.split())
    # 아이콘(.ni svg)은 상시 표지 — 크기 규칙 존재로 SVG 아이콘 착지를 확인.
    assert ".navbtn.nisvg{width:18px" in css, "탭 아이콘(.ni svg) 상시 표지 규칙이 사라졌습니다(#27)."
    assert "rail-collapsed" not in css, (
        "레일 접힘 규칙이 남아 있습니다 — 표면 없는 상태는 되살아날 통로입니다(§10.9 4계약면 4행)."
    )
    # 토바 높이는 구조 치수 단일 출처 — 라이브러리 2-pane 계산이 이 변수를 소비한다(판정 G).
    assert "--shell-topbar-h:64px" in css, "토바 높이 변수(구조 치수 · §19.12)가 사라졌습니다."
    assert "calc(100vh-var(--shell-topbar-h)-250px)" in css, (
        "라이브러리 2-pane 높이가 토바 변수를 소비하지 않습니다 — 리터럴 드리프트로 페이지가 "
        "조용히 스크롤합니다(§19.6 명문 · 지도 §10.9 판정 G)."
    )


def test_custom_modals_have_dialog_semantics():
    """커스텀 모달은 role=dialog·aria-modal·유효한 aria-labelledby 를 정적으로 가져야 한다(#27/#28).

    포커스/복귀/Escape 동적 거동은 selftest 게이트가 되읽어 단언한다 — 여기선 AT 가 다이얼로그로
    인지하고 이름을 얻는 *정적 계약*만 가드한다(네이티브 window.confirm 대체가 아닌 인페이지 모달).
    """
    ids = set(_collect_ids())
    modals = _collect_modals()
    react_labels = {
        "poolRegModal": (R4_DATA_PICKER, "PoolRegistrationDialog"),
        "dataPickerModal": (R4_DATA_PICKER, "DataPickerDialog"),
        # R4-02 — 편집 표면 셋. 제목 id 의 생산자도 함께 이동했다.
        "txtEditModal": (R4_EDITOR, "TxtEditDialog"),
        "sheetModal": (R4_SHEET_PICKER, "SheetPickerDialog"),
        "tplMoveModal": (R4_GROUP_MOVE, "GroupMoveDialog"),
        # R4-03 — 확인 면. 정적 골격은 자리(sheet 껍데기)만 남고 제목 id 도 함께 이동했다.
        "previewSheet": (R4_JOB_PREVIEW, "JobPreviewSheet"),
    }
    for mid, label_id in MODAL_LABELLEDBY.items():
        assert mid in modals, f"커스텀 모달이 사라졌습니다: {mid}"
        attrs = modals[mid]
        assert attrs.get("role") == "dialog", f"{mid} 에 role=\"dialog\" 가 필요합니다."
        assert attrs.get("aria-modal") == "true", f"{mid} 에 aria-modal=\"true\" 가 필요합니다."
        assert attrs.get("aria-labelledby") == label_id, (
            f"{mid} 의 aria-labelledby 는 '{label_id}' 여야 합니다(현재: {attrs.get('aria-labelledby')!r})."
        )
        if mid in react_labels:
            owner, component = react_labels[mid]
            src = owner.read_text(encoding="utf-8")
            assert f"export function {component}" in src
            assert src.count(f'id: "{label_id}"') == 1, (
                f"{mid} 의 React 제목 id '{label_id}' 생산자가 정확히 하나여야 합니다."
            )
            assert label_id not in ids, f"{label_id} 정적 골격이 React producer와 중복됩니다."
        else:
            assert label_id in ids, f"{mid} 의 aria-labelledby 대상 id '{label_id}' 가 DOM 에 없습니다."

    # R3-01 승계 형태 — 이전된 3종은 정적 **부재**(재도입 즉시 빨강)와 host 렌더 소유(같은
    # role·aria 짝)를 양면으로 단언한다. 렌더 산출 검증은 node overlay_host.test.js 가 진다.
    host_src = source_text(*next(iter(REACT_RENDER_CONTRACT)).split("/"))
    for mid, label_id in HOST_MODAL_LABELLEDBY.items():
        assert mid not in modals and mid not in ids, (
            f"{mid} 가 index.html 에 재도입됐습니다 — R3-01 뒤 이 골격은 React host 렌더 "
            "소유라 정적 재도입은 id 중복·두 세계 분열입니다."
        )
        assert f'id: "{mid}"' in host_src, f"host 렌더에 #{mid} 골격이 없습니다."
        assert f'"aria-labelledby": "{label_id}"' in host_src, (
            f"host 렌더 #{mid} 의 aria-labelledby('{label_id}') 연결이 사라졌습니다."
        )
    assert host_src.count('role: "dialog"') == len(HOST_MODAL_LABELLEDBY), (
        "host 렌더 다이얼로그의 role=dialog 수가 이전 3종과 다릅니다."
    )


def test_react_render_contract_records_static_and_runtime_twins():
    """React 렌더 소유 표면마다 정적 계약과 브라우저/runtime 검증 쌍이 모두 실재한다."""
    for source, contract in REACT_RENDER_CONTRACT.items():
        assert (SOURCE_ROOT / source).is_file(), f"React 렌더 소스가 없습니다: {source}"
        assert contract["static_owner"], f"{source}: 정적 소유 계약이 비었습니다."
        twins = contract["runtime_twins"]
        assert len(twins) >= 2, f"{source}: 브라우저/runtime 쌍이 둘보다 적습니다."
        for twin in twins:
            assert (REPO_ROOT / twin).is_file(), f"{source}: 검증 쌍이 실재하지 않습니다: {twin}"


#: 합성 루트가 등록하는 portal target 의 **오늘 수**. 폐포를 「bootstrap 이 부른 것 전수」로
#: 유도하므로 이 정수는 집합을 열거하지 않고 **추출기가 눈을 감는 것**만 막는다 — 정규식이
#: 죽어 빈 목록을 내면 폐포는 공허하게 닫히고 이 하한만 어긋난다.
REACT_PORTAL_TARGET_FLOOR = 10


def test_every_react_portal_target_stands_in_the_static_shell() -> None:
    """`screenPortal(...)` 이 겨눈 자리는 **하나도 빠짐없이** index 에 실재해야 한다.

    `resolvePortalTargets` 는 target 부재를 fail-closed 로 던진다 — 정적 골격에서 자리 하나가
    사라지면 React root mount 가 통째로 죽고 **앱이 부팅에서 추락한다**. 그 결함은 화면을 열어야
    보이므로 정적 층이 겨누지 않으면 실 WebView2 게이트까지 조용하다.

    형제 계약(`test_r4_static_to_js_successor_map`)이 같은 질문을 **손으로 연 열 개**에 대해
    묻는데, 오늘 등록은 스물넷이라 열넷이 무방비였다. 실제로 R4-03 이 overlay 구간을 재작성하며
    `libraryMoveModal` 자리를 지웠고 그 열넷 중 하나였다. 그래서 이 폐포는 목록을 손으로 들지
    않고 **합성 루트에서 유도한다** — 등록이 늘면 검사도 함께 는다.
    """
    bootstrap = SOURCE_BOOTSTRAP.read_text(encoding="utf-8")
    targets = ["reactScreenStage", *re.findall(
        r'productOverlayComponent\(\s*"([A-Za-z0-9_-]+)"',
        _strip_js_comments(bootstrap),
    )]
    assert len(targets) >= REACT_PORTAL_TARGET_FLOOR, (
        f"portal 등록을 {len(targets)} 개만 봤습니다(하한 {REACT_PORTAL_TARGET_FLOOR}) — "
        "추출기가 눈을 감았는지 보세요. 등록이 실제로 줄었으면 사유와 함께 하한을 고칩니다."
    )
    assert len(set(targets)) == len(targets), (
        f"portal target 이 중복 등록됐습니다: "
        f"{sorted(t for t, n in Counter(targets).items() if n > 1)}"
    )
    # 주석 안의 죽은 id 를 산 자리로 오독하지 않는다 — HTMLParser 는 주석에서 starttag 를
    # 부르지 않으므로 `_collect_ids()` 가 그 구분을 이미 진다.
    live = Counter(_collect_ids())
    missing = sorted(t for t in targets if live[t] == 0)
    assert not missing, (
        f"React portal target 이 정적 골격에 없습니다: {missing}. "
        "resolvePortalTargets 가 mount 전에 던지므로 이 상태의 앱은 부팅하지 못합니다."
    )
    duplicated = sorted(t for t in targets if live[t] > 1)
    assert not duplicated, (
        f"portal target id 가 index 에 둘 이상 있습니다: {duplicated} — "
        "getElementById 가 첫 요소만 돌려주므로 어느 자리에 그려질지가 문서 순서에 묶입니다."
    )


# 숨김 관례(슬라이스 7 PR-3 리뷰): 이 앱의 CSS 에는 **일반 `.hidden` 규칙이 없다** —
# `.modal.hidden{display:none}` 하나뿐이라 클래스 방식은 모달 전용이고, 그 밖의 숨김은
# 전부 `hidden` **속성**이다. 다른 앱 습관대로 `class="hidden"` 을 붙이면 아무 일도 안
# 일어나 요소가 계속 보인다 — 테두리만 남은 빈 경고 상자·항상 서 있는 dead 버튼이 되는데,
# 눈으로 안 보면 모르는 결함이라(실제로 리뷰에서 처음 잡혔다) 정적으로 막는다.
_HIDDEN_OK_JS = {"modal.js"}  # 모달 개폐 헬퍼만 클래스 토글의 임자
_CLASS_ATTR_RE = re.compile(r"""class\s*=\s*\\?["']([^"']*)\\?["']""")
_CLASSLIST_HIDDEN_RE = re.compile(r"""classList\s*\.\s*\w+\s*\(\s*["']hidden["']""")


class _HiddenClassCollector(HTMLParser):
    """``hidden`` 클래스를 단 요소를 (태그, id, class) 로 수집."""

    def __init__(self) -> None:
        super().__init__()
        self.found: "list[tuple[str, str, str]]" = []

    def handle_starttag(self, tag, attrs):
        d = {name: (value or "") for name, value in attrs}
        classes = d.get("class", "").split()
        if "hidden" in classes:
            self.found.append((tag, d.get("id", ""), d.get("class", "")))


def test_hidden_class_is_modal_only_elsewhere_use_the_attribute():
    """`.hidden` 은 모달 전용 — 그 밖의 숨김은 `hidden` 속성이어야 한다(무효 클래스 차단).

    세 갈래를 함께 본다: (a) CSS 에 일반 `.hidden` 규칙이 생기지 않았는가(생겼다면 관례가
    바뀐 것이니 이 테스트부터 고쳐야 한다), (b) index.html 의 `class="… hidden …"` 이 전부
    `.modal` 인가, (c) JS 가 modal.js 밖에서 hidden 클래스를 조작하거나 마크업에 심지 않는가.
    """
    css = WEB_CSS
    generic = re.search(r"(?m)^\s*\.hidden\s*[,{]", css)
    assert not generic, (
        "일반 `.hidden` 규칙이 생겼습니다 — 숨김 기제가 둘(속성·클래스)로 갈라지면 어느 쪽이"
        " 먹는지 사이트마다 달라집니다. 도입이 의도라면 이 가드와 관례 주석을 함께 고치세요."
    )
    assert ".modal.hidden" in css, "모달 숨김 규칙(.modal.hidden)이 사라졌습니다 — 모달이 항상 떠 있게 됩니다."

    parser = _HiddenClassCollector()
    parser.feed(WEB_INDEX.read_text(encoding="utf-8"))
    strays = [f"<{tag} id={mid!r} class={cls!r}>" for tag, mid, cls in parser.found
              if "modal" not in cls.split()]
    assert not strays, (
        "모달이 아닌 요소에 `hidden` 클래스가 붙었습니다 — 이 앱엔 일반 .hidden 규칙이 없어"
        " **숨겨지지 않습니다**. `hidden` 속성을 쓰세요:\n" + "\n".join(strays)
    )

    offenders: "list[str]" = []
    for js in sorted(WEB_JS_DIR.rglob("*.js")):
        if js.name in _HIDDEN_OK_JS:
            continue
        text = js.read_text(encoding="utf-8")
        for m in _CLASSLIST_HIDDEN_RE.finditer(text):
            offenders.append(f"{js.name}: {m.group(0)} — el.hidden = … 로 바꾸세요")
        for m in _CLASS_ATTR_RE.finditer(text):
            classes = m.group(1).split()
            if "hidden" in classes and "modal" not in classes:
                offenders.append(f"{js.name}: class={m.group(1)!r} — hidden 속성을 쓰세요")
    assert not offenders, "무효 hidden 클래스 사용:\n" + "\n".join(offenders)


def test_responsive_breakpoint_collapses_layout():
    """좁은 폭 경계에서 2판 레이아웃이 세로 단일열로 접히는 규칙이 CSS 에 있어야 한다(#27).

    실 렌더 검증(창을 실제로 줄여 되읽기)은 selftest 게이트가 한다 — 여기선 헤드리스 포함 전
    플랫폼에서 경계 규칙 자체의 존재를 정적으로 가드한다(경계·접힘 규칙 삭제 회귀 차단).
    """
    css = "".join(WEB_CSS.split())  # 공백 제거 → 포맷 불가지
    assert f"@media(max-width:{RESPONSIVE_BREAKPOINT_PX}px)" in css, (
        f"반응형 경계 @media(max-width:{RESPONSIVE_BREAKPOINT_PX}px) 가 사라졌습니다(#27)."
    )
    assert ".app{grid-template-columns:1fr}" in css, (
        ".app 세로 단일열 접힘 규칙이 사라졌습니다 — 최소 크기에서 가로 오버플로 회귀(#27)."
    )


# (test_milestone_l_draft_density_structure_and_values ·
#  test_milestone_l_draft_expansion_sheets_move_live_surfaces 삭제 — 대상(기안 duo·
#  draftTokPanel·draftMapSheet·draftsession.js)이 화면과 함께 사망(F6 PR-B). 살아남은
#  계약 — 기본창 수치·surface_sheet 실 DOM 이동/복귀·dataSheet — 는 아래 job 테스트가 진다.)


def test_milestone_l_job_density_and_expansion_sheets():
    """#272 승계 + 재작성 R1: 세션 패널 2열·420px 캡·두 펼침 면·편집 전 즉시 복귀 계약.

    R1 이 구 `.job-duo`(표|거울 가로 병치)를 v6 `screen-data` 2열로 대체했다 — 가로 축은
    이제 데이터 ↔ 문서 선택기이고, 표↔거울은 좌 열 안에서 **세로 인접**으로 남는다(같은
    시야 요구는 인접 + 펼침 면 ⤢ 가 승계). #272 의 나머지 계약(420px 캡·캡스트립·두 면의
    실 DOM 이동/복귀)은 그대로 살아 여기서 계속 고정된다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    product = R4_PRODUCT_SCREENS.read_text(encoding="utf-8")
    css = "".join(WEB_CSS.split())
    job_js = react_job_run_source()
    job_read = R4_JOB_READ.read_text(encoding="utf-8")
    data_zone = R4_DATA_ZONE.read_text(encoding="utf-8")
    sheets = (WEB_JS_DIR / "surface_sheet.js").read_text(encoding="utf-8")
    app_py = (REPO_ROOT / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(
        encoding="utf-8"
    )

    # 기본창 수치(#270)와 펼침 면의 실 DOM 이동/복귀 계약(#271)은 기안 테스트가 지다가
    # 화면 사망(F6 PR-B)으로 여기로 승계됐다 — 계약 자체는 매체 불가지라 그대로 산다.
    assert "DEFAULT_WINDOW_WIDTH = 1440" in app_py
    assert "DEFAULT_WINDOW_HEIGHT = 900" in app_py
    assert '<div id="dataSheet" class="modal sheet hidden"' in html
    assert ".cloneNode(" not in sheets
    assert "slot.appendChild(el)" in sheets
    assert "m.parent.insertBefore(m.el, m.next)" in sheets
    assert ".data-sheet-body.jobtbth:first-child" in css
    assert "position:sticky;left:0" in css

    assert 'className: "data-grid", id: "jobDataGrid"' in product
    assert 'class="duo job-duo"' not in html and ".job-duo{" not in css, (
        "구 표|거울 duo 가 재유입됐습니다 — R1 의 가로 축은 데이터↔문서 선택기입니다."
    )
    # 좌 열 = 현재 데이터 → 거울 → 결과(세로), 우 열 = 문서 선택기 → 생성 준비
    # (구 「선택한 작업」 존은 U2 §4 판정 A(#342)로 사망 — 아래 승계 계약 테스트가 잇는다).
    # 좌 열의 아래 두 자리(거울·결과)는 R4-03 에서 React 생산이라 정적 index 에는 **자리**만
    # 남는다 — 순서 계약이 겨눌 것도 그 자리다(안쪽 id 를 계속 찾으면 이동을 회귀로 오독한다).
    ordered = [
        'id: "jobDataGrid"', 'id: "jobPreflight"', 'location: "inline"',
        'id: "jobMirrorZone"', 'id: "jobResultZone"', 'id: "jobSideCard"',
        'id: "jobCandsRow"', 'id: "jobOutRow"', 'id: "jobActionBar"',
    ]
    positions = [product.index(needle) for needle in ordered]
    assert positions == sorted(positions), f"ProductScreens job 구획 순서가 어긋났습니다: {ordered}"
    assert 'id: "jobTableHost"' in data_zone and 'id: "jobCandidates"' in job_read
    # 본문 존 = 표 없는 한 줄(U2 §2.13) — 420px 캡·캡스트립은 표와 함께 사망했다.
    assert "jobMirrorCapstrip" not in html + product and "max-height:420px" not in css
    # 컬럼 템플릿은 한 곳에서만 선언한다(U2 §2.2) — 세션 카드와 그 아래 액션바가 같은
    # 기준면을 써야 「미리보기·생성」이 자기 입력(좌 열)과 같은 열의 오른쪽 끝에 선다.
    # 리터럴이 두 번 적히면 한쪽만 고쳐져 두 표면이 조용히 어긋난다.
    assert ".job-zones,.session-actionbar{--data-grid-cols:minmax(0,1fr)minmax(268px,.46fr)}" in css
    assert ".data-grid{display:grid;grid-template-columns:var(--data-grid-cols)}" in css
    assert ".session-actionbar{position:sticky;bottom:0;z-index:5;display:grid;" in css
    assert "grid-template-columns:var(--data-grid-cols);" in css
    # 가로 패딩은 **트랙 밖**이다(리뷰 R5): 패딩이 트랙 안에 있으면 액션바가 패딩 뺀 폭에서
    # 트랙을 계산해 1열 끝이 구분선보다 6px 앞에서 끝난다 — 같은 템플릿을 공유해도 **재는
    # 상자**가 다르면 기준면이 어긋난다. 카드의 좌 여백은 트랙 안의 행이 진다.
    assert "margin-top:var(--sp-12);padding:var(--sp-12)0;" in css
    assert (
        ".actionbar-row{display:flex;align-items:center;gap:var(--sp-12);flex-wrap:wrap;"
        "justify-content:flex-end;padding-left:var(--sp-16)}"
    ) in css
    # R4-03 — 액션바 안쪽은 React 생산이라 감싸개도 그쪽에 산다. 묻는 것은 그대로다:
    # 감싸개가 없으면 자식들이 두 열에 흩어진다(CSS 가 트랙을 그 한 겹에 건다).
    assert 'className: "actionbar-row"' in job_js, (
        "액션바 내용을 감싸지 않으면 자식들이 두 열에 흩어진다."
    )
    assert "@containersession-panel(max-width:900px)" in css
    assert ".job-zones,.session-actionbar{--data-grid-cols:1fr}" in css
    # 좁은 side-card 에서 라벨+입력+버튼을 한 줄에 밀어 넣으면 저장 폴더 경로가 몇 글자로
    # 잘려 "어디에 저장되는지"를 못 읽는다 — 감싸기 규칙이 그 되읽기를 지킨다.
    assert ".dg-side.run-row{flex-wrap:wrap;row-gap:var(--sp-4)}" in css
    assert ".dg-side.run-row>.field{flex:11100%}" in css
    # 거울 펼침 면(jobConfirmSheet — 2 pane)은 사망했다(U2 §2.13): 확인 면은 시트로
    # 승격한 생성 값 미리보기(#previewSheet) 하나이고, 본문 존 한 줄의 ⤢ 가 그 면을 연다.
    assert "jobConfirmSheet" not in html and "jobConfirmSheet" not in job_js
    assert ".sheet-duo" not in css and ".sheet-pane" not in css, (
        "확인 2 pane 골격이 재유입됐습니다(§2.13 — 1 pane 확정)."
    )
    assert "펼쳐서 행 고르기 ⤢" in job_read and "생성 값 미리보기 ⤢" in job_js
    # 확인 면 출구는 **안정 DOM** 이다(#364 리뷰 P2): 재렌더로 교체되는 트리거는 Modal 의
    # 복귀점에서 분리돼(`isConnected` 실패) 키보드 초점이 화면 루트로 떨어진다 — #280 이
    # 캡스트립에서 배운 결함이라 한 줄은 「버튼 고정 + 문안만 휘발」로 짓는다.
    # R4-03 — 세 노드가 전부 React 생산으로 갔다. 「안정 DOM」의 의미도 함께 옮긴다:
    # 종전엔 「정적 index 에 있고 렌더가 다시 짓지 않는다」였는데, React 소유에서는 **한
    # 생산자가 정확히 한 번** 적고 그 노드가 재조정으로 보존되는 것이 같은 보장이다
    # (교체가 아니라 갱신이라 `isConnected` 가 깨지지 않는다).
    for node_id in ("jobMirrorPreviewOpen", "jobMirrorSummary", "jobMirrorLine"):
        assert job_js.count(f'id: "{node_id}"') == 1, (
            f"확인 면 출구 계열 {node_id} 의 생산자가 하나가 아닙니다(#364)."
        )
        assert f'id="{node_id}"' not in html, (
            f"{node_id} 정적 골격이 React producer 와 중복됩니다."
        )
    for node_id in ("jobRecsHead", "jobFilterChips", "jobTableHost", "jobSelStrip"):
        assert f'id: "{node_id}"' in data_zone
    assert 'productOverlayComponent("dataSheetSlot", PRODUCT_OVERLAY_COMPONENTS.JobDataBody' in SOURCE_ROOT.joinpath(
        "src", "bootstrap.js"
    ).read_text(encoding="utf-8")
    # 화면을 떠날 때의 일괄 회수(재작성 F7) — 펼침 면은 실 DOM 을 오버레이로 옮겨 띄우므로
    # 열린 채 화면이 바뀌면 남의 화면 위에 이 화면의 DOM 이 뜬다. 소유가 화면 전환으로
    # 올라가 어느 화면이 늘어도 같은 회수가 걸린다(종전엔 편집 모드 진입이 그 자리에서 닫았다).
    bootstrap_src = SOURCE_BOOTSTRAP.read_text(encoding="utf-8")
    assert "reclaimSurfaces: () => SurfaceSheet.closeAllAndRestore()" in bootstrap_src, (
        "화면 전환이 펼침 면을 회수하지 않습니다 — 남의 화면 위에 실 DOM 이 남습니다."
    )
    assert "function closeAllAndRestore" in sheets
    assert "Modal.close(id);\n  restore(id);" in sheets
    # 펼침 트리거 포커스 복귀(#279 리뷰) — 실클릭 버튼→상시 ⤢ 순으로 해석하는
    # SurfaceSheet.trigger 만 쓴다(데이터 면 ⤢ 이 남은 소비자다).
    assert "trigger: trigger" in sheets
    assert "surfaceSheet.open({" in job_read
    assert "returnFocus: trigger" in job_read
    # sticky 첫 열의 행 상태 보존(#279 리뷰) — 무조건 --a-card 는 tr.on/호버 배경을 덮어
    # 문서 정체 셀만 미선택처럼 보인다. sticky 는 투명 불가라 불투명 등가색으로 맞춘다.
    assert ".data-sheet-body.jobtbtbodytr.ontd:first-child{background:var(--a-sel)}" in css
    assert ".data-sheet-body.jobtbtbodytr:hovertd:first-child{" in css
    assert "color-mix(insrgb,var(--a-sel)40%,var(--a-card))" in css


def test_job_generation_result_renders_partial_cancellation_honestly():
    """#278 리뷰 — 취소된 배치를 진행바 100% + danger 로 그리면 정확한 요약 문안 옆에서
    시각이 '완주했고 오류'라고 거짓말한다: 진행 = attempted/total, warn 채널 보존.

    F4 의 3태 구획으로 옮겨 온 뒤에도 **채널은 둘 그대로**다: 태(data-state)는 구조를,
    level(data-level)은 색을 정한다. JS 가 level 을 재판정하지 않고 Python 값을 그대로
    싣는 것이 이 계약의 새 표현이며, warn 이 실제로 danger 와 다른 색을 받는지는 CSS 가 진다.
    """
    result_src = R4_JOB_RESULT.read_text(encoding="utf-8")
    css = "".join(WEB_CSS.split())
    # 진행바 폭 — 취소된 배치는 **시도한 만큼**이다. 계산이 취소 여부를 안 보면 정확한 요약
    # 문안 옆에서 시각이 "완주했고 오류"라고 거짓말한다.
    block = result_src[result_src.index("let pct = 0;"):result_src.index("const shown")]
    assert "r.cancelled" in block and "r.attempted" in block
    assert 'width: `${pct}%`' in result_src, "진행바 폭이 계산 결과를 안 씁니다."
    # level 채널 — Python 값을 **그대로** 싣는다(표면이 재판정하지 않는다).
    assert '"data-level": shown?.level || ""' in result_src, (
        "level 채널을 렌더 층이 재판정하고 있습니다."
    )
    assert '.result3[data-level="warn"]' in css and '.result3[data-level="danger"]' in css


def test_job_status_pill_binds_its_class_to_the_level_selectors():
    """`data-level` 은 **혼자서 색을 내지 않는다** — 클래스와 짝일 때만 규칙이 붙는다.

    R4-03 이 `jobStatus` 를 React 생산으로 옮기며(D20) legacy 의 `div.status` 가
    `span.pill` 이 됐다. 속성은 그대로 실렸고 정적 계약도 실 게이트도 초록이었지만,
    `.status[data-level="ok"]`(base.css)에도 `.pill.ok`(overlay.css)에도 안 붙어 **색이
    죽었다**. 선언은 살고 결과가 죽는 그 형태다.

    그래서 클래스 이름을 **소스에서 유도**해 그 클래스의 level 선택자가 실재하는지 묻는다
    — 이름을 손으로 적으면 다음 개명이 같은 자리를 다시 통과한다.
    """
    src = react_job_run_source()
    match = re.search(
        r'\{\s*id:\s*"jobStatus",\s*className:\s*"([^"]+)",\s*"data-level"', src
    )
    assert match, (
        "`jobStatus` 의 클래스·level 속성을 한 자리에서 못 읽었습니다 — 겨눔을 다시 세워야 합니다."
    )
    classes = match.group(1).split()
    css = "".join(WEB_CSS.split())
    # 요소가 태를 **속성으로** 받으므로 속성 선택자만 붙는다. `.pill.ok` 같은 클래스 규칙이
    # 저장소에 있어도 이 요소에는 영영 안 붙는다 — 「규칙이 실재하는가」가 아니라 「이 요소가
    # 받는 채널로 붙는가」를 물어야 한다(첫 판이 전자를 물어 결함을 통과시켰다).
    for level in ("ok", "warn"):
        bound = any(f'.{cls}[data-level="{level}"]' in css for cls in classes)
        assert bound, (
            f"`jobStatus` 가 {classes} 클래스로 서는데 그 클래스의 "
            f'`[data-level="{level}"]` 규칙이 CSS 에 없습니다 — 속성만 살고 색이 죽습니다.'
        )


def test_milestone_l_wide_probes_do_not_depend_on_host_monitor_width():
    """Actions 가상 화면이 1440px 미만이어도 wide 컨테이너 분기를 직접 검증해야 한다.

    N-09 에서 프로브가 프런트로 옮겨가며 이 단언의 **대상 파일도 따라갔다**. 계약은 그대로다:
    호스트 모니터 폭에 기대지 않고 폭을 직접 세워 잰다. 파일이 바뀌었다고 단언을 지우면
    CI 의 좁은 가상 화면에서 wide 분기가 영영 안 돌고, 그 침묵은 아무도 못 듣는다.
    """
    probe_js = source_text("src", "selftest", "probes", "job.js")
    # draftPanel 프로브는 화면 사망(F6 PR-B)과 함께 걷혔다 — 남은 wide 분기는 job 하나.
    assert 'jobPanel.style.flex = "0 0 1100px"' in probe_js
    assert "jobPanel.style.flex = jobPanelFlex" in probe_js


def _forced_colors_block(css_text: str) -> str:
    """``@media (forced-colors:active)`` 블록의 **본문**만 공백 제거 형태로 반환.

    파일 전체가 아니라 블록 내부를 봐야 한다 — 그러지 않으면 블록 밖에 이미 존재하는
    ``tr.r-unconfirmed``/``border-left`` 같은 토큰이 검사를 통과시켜, 정작 고대비 보더
    신호를 떨궈도 잡지 못한다(원 테스트의 사각). 주석을 먼저 걷어 브레이스 계수를
    오염시키지 않고, 여는 ``{`` 부터 짝 맞는 ``}`` 까지 깊이로 잘라낸다. 블록이 없으면 "".
    """
    text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    css = "".join(text.split())
    marker = "@media(forced-colors:active){"
    i = css.find(marker)
    if i == -1:
        return ""
    depth, j = 1, i + len(marker)
    while j < len(css) and depth:
        depth += (css[j] == "{") - (css[j] == "}")
        j += 1
    return css[i + len(marker) : j - 1]


def _rule_body(block: str, selector: str) -> str:
    """공백 제거 블록에서 ``selector{...}`` 규칙의 **본문**만 반환(없으면 "").

    선언을 셀렉터에 묶어 검사하려는 것 — 블록 전역 부분문자열 검사는 한 셀렉터의
    선언을 비워도(예: ``tr.r-unmatched td{}``) 다른 셀렉터에 남은 같은 토큰
    (``border-left``)이 통과시켜, 특정 상태의 보더 신호 소실을 못 잡는다. 공백 제거로
    후손 결합자가 붙으므로(``tr.r-unmatched td`` → ``tr.r-unmatchedtd``) selector 도
    같은 형태로 넘긴다.
    """
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", block)
    return m.group(1) if m else ""


def test_forced_colors_media_query_exists():
    """web/ 강제 색상 모드(Windows 고대비) 보더 신호가 **블록 안에** 있어야 한다(#3, WCAG 1.4.3).

    실 고대비 렌더 검증은 헤드리스로 불가능(ST-14 원 보류 사유와 동일) — 여기선 규칙
    자체의 존재를 정적으로 가드해, 다음 웹 이관/리팩터가 조용히 이 블록을 떨구는
    회귀를 CI 에서 차단한다. 파일 전역이 아닌 **블록 본문**을 검사해, 배경 틴트 규칙만
    남고 고대비 보더 대체 신호가 사라지는 회귀도 잡는다.
    """
    block = _forced_colors_block(WEB_CSS)
    assert block, "강제 색상 모드 대응 @media(forced-colors:active) 블록이 사라졌습니다(#3)."
    # 두 행 상태 셀렉터가 '각자' 보더 신호를 가져야 한다 — 블록 전역 부분문자열 검사는
    # 한 셀렉터의 보더만 비워도(다른 셀렉터에 border-left 잔존) 통과하므로 셀렉터에 묶는다.
    for selector in ("tr.r-unconfirmedtd", "tr.r-unmatchedtd"):
        assert "border-left" in _rule_body(block, selector), (
            f"매핑 표 행 상태({selector})의 강제색 보더 대체 신호가 사라졌습니다 — "
            "배경 틴트만으론 고대비에서 행 상태가 사라집니다(#3)."
        )


# pickDataFile(=pick_data_file) 을 소비하는 모든 화면 — 브리지 반환 계약이 screen-불가지라
# needs_sheet 분기를 처리해야 다중 시트가 첫 시트로 강등되지 않는다(리뷰 P1: txt 누락 회귀).
# 「작업」·「기안」의 파일 선택은 데이터 선택 다이얼로그 한 곳으로 수렴했다(재작성 F1) —
# 두 화면이 같은 모듈을 쓰므로 계약도 그 모듈이 진다. 에디터는 아직 자기 경로를 쓴다(F7).
DATA_PICK_FILES = (R4_EDITOR, R4_DATA_PICKER)


def test_sheet_picker_loaded_and_wired_on_all_data_screens():
    """다중 시트 확정 게이트 배선 정적 가드(#33) — 조용한 첫 시트 로드 회귀 차단.

    실 시트 선택 거동(모달 개폐·확정 로드)은 Modal/브리지 계약 테스트가 본다 — 여기선
    (a) 헬퍼·모달 골격 존재, (b) 데이터를 붙이는 **모든** 화면(에디터·작업·txt·빠른 기안)이
    pickDataFile 의 needs_sheet 를 받아 SheetPicker 로 확정을 태우는 배선이 살아있는지를 정적
    가드한다. pickDataFile 계약이 screen-불가지라, 한 화면이라도 이 분기를 떨구면 그 화면에서
    다중 시트가 조용히 첫 시트로 강등되는 회귀(리뷰 P1 재발 차단).
    """
    index = WEB_INDEX.read_text(encoding="utf-8")
    picker = R4_SHEET_PICKER.read_text(encoding="utf-8")
    #: R4-02 — 헬퍼는 `src/screens/sheet_picker.ts` 로 이관됐고 모달 내용은 React portal 이
    #: 생산한다. 정적 골격은 root 하나뿐이라(중복 생산자 금지) 여기서는 **생산자**를 잰다.
    assert 'id="sheetModal"' in index, "시트 선택 모달 root 가 없습니다(#33)."
    assert 'id="sheetList"' not in index and 'id="sheetCancel"' not in index, (
        "시트 선택 모달 내용이 정적으로 재도입됐습니다 — React portal 과 두 생산자가 됩니다."
    )
    assert 'id: "sheetList"' in picker and 'id: "sheetCancel"' in picker, (
        "React 시트 선택 표면이 목록·취소 골격을 생산하지 않습니다(#33)."
    )
    assert '"data-first": index === 0 ? "1" : undefined' in picker and '"data-sheet"' in picker, (
        "명시 선택의 표지(data-sheet)와 초기 포커스 표지(data-first)가 사라졌습니다."
    )
    for path in DATA_PICK_FILES:
        src = path.read_text(encoding="utf-8")
        assert "needs_sheet" in src and (
            "SheetPicker.choose" in src
            or "sheetPicker.choose" in src
            or "sheetPicker.current().choose" in src
        ), (
            f"{path} 이 다중 시트 확정 게이트(needs_sheet→SheetPicker) 배선을 잃었습니다 — "
            "이 화면에서 다중 시트가 조용히 첫 시트로 강등됩니다(#33, 리뷰 P1)."
        )


def test_preserve_helper_loaded_and_wraps_screen_renders():
    """legacy renderer는 Preserve를, R4 React renderer는 reconciliation·stable id를 쓴다.

    실 재구성 가로지르기 거동(포커스·캐럿·스크롤 유지)은 selftest 게이트가 되읽어 단언한다 —
    여기선 헤드리스 포함 전 플랫폼에서 배선(스크립트 로드·화면별 래핑)의 존재를 정적으로 가드해
    어느 화면이 래핑을 조용히 떨구는 회귀를 막는다.
    """
    assert reaches_product_graph("preserve.js"), (
        "preserve.js 가 제품 그래프에 닿지 않습니다(#28)."
    )
    for rel in PRESERVE_WRAPPED_FILES:
        src = (WEB_JS_DIR / rel).read_text(encoding="utf-8")
        assert "Preserve.around" in src, (
            f"{rel} 의 render() 가 Preserve.around 래핑을 잃었습니다 — 재렌더 시 상호작용 유실(#28)."
        )
    for path in (R4_DATA_PICKER, R4_LIBRARY, R4_JOB_READ, R4_DATA_ZONE, R4_EDITOR, R4_WORKBENCH):
        src = path.read_text(encoding="utf-8")
        assert "Preserve.around" not in src
        assert "createElement" in src
    #: R4-02 — 편집 표면은 재구성이 없는 대신 **값의 소유**로 같은 것을 지킨다: 편집 가능한
    #: 컨트롤이 draft reducer 에서 값을 읽고(`valueOf(draft, …)`), push 흡수는 그 reducer 를
    #: 지난다. 이 두 축이 없으면 스냅샷이 입력 중인 값을 조용히 덮는다.
    for path in DRAFT_OWNED_FILES:
        src = path.read_text(encoding="utf-8")
        assert "valueOf(draft," in src, f"{path.name} 의 컨트롤이 draft 값을 읽지 않습니다."
        assert "ingestSnapshot(draft" in src, f"{path.name} 이 push 를 draft reducer 로 흡수하지 않습니다."
    assert "data-preserve-scroll" in R4_LIBRARY.read_text(encoding="utf-8")
    assert "jobRow-${row.index}" in R4_DATA_ZONE.read_text(encoding="utf-8")


def _mutable_module_state(src: str) -> list[str]:
    """본문(2칸 들여쓰기)의 `let`·`var` 선언 이름 — 렌더 층 가변 모듈 상태의 실측치.

    블록 주석을 먼저 지운다(주석 속 예시 코드가 예산을 먹지 않게). 이 앱의 렌더 층은 전부
    한 겹 래퍼 — 구 IIFE 든 N-06 의 `export function create…() {` factory 든 — 안에 살아
    **2칸 = 그 인스턴스의 상태 스코프**이고 함수 본문은 4칸 이상이다. 파서 없이 성립하는
    관례 기반 계측이며, 예산(천장)에는 이 정밀도로 충분하다. factory 파일의 모듈 최상위
    (0칸)에 `let`·`var` 를 두는 것은 이 계측 밖이지만, 그 자리는 build-graph 게이트의
    "구성 1회" 계약과 겹쳐 인스턴스 상태를 둘 곳이 아니다.
    """
    body = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.findall(r"^  (?:let|var)\s+([A-Za-z_$][\w$]*)", body, flags=re.M)


def test_render_layer_mutable_module_state_stays_within_budget():
    """렌더 층의 가변 모듈 상태가 예산을 넘지 않는다 — 파생 가능한 상태의 조용한 축적 차단.

    Python 단일소유 모델에서 JS 가변 모듈 상태는 "스냅샷이 답하지 않아 표면이 답하는 것"이다.
    늘어나면 그것을 읽어 DOM 을 미는 전이 함수가 딸려 오고, 상태 조합은 곱셈으로 늘어 전이가
    그만큼 갈린다 — F3·F4 리뷰가 상태-누수 P1·P2 로 실제로 밟은 자리다. 상한은 실측값이고
    비교가 `<=` 라 **정리는 항상 통과하고 축적만 시끄럽다**(정리 시점은 F5~F8 완주 후 일괄).

    이 계측이 잡는 것은 개수뿐이다 — 무효화 스킴이 여러 벌인지(캐시 무효화)나 표면이 판정을
    재계산하는지는 못 본다. 그 둘은 슬라이스별 계약 테스트와 실앱 101 순회가 맡는다.
    """
    for rel, ceiling in sorted(MUTABLE_MODULE_STATE_BUDGET.items()):
        path = R4_SCREENS_DIR / rel
        assert path.exists(), f"예산 대상 {rel} 이 사라졌습니다 — 파일이 죽었으면 예산에서도 지우세요."
        names = _mutable_module_state(path.read_text(encoding="utf-8"))
        assert len(names) <= ceiling, (
            f"{rel} 의 가변 모듈 상태가 {len(names)}개로 예산 {ceiling}개를 넘었습니다: "
            f"{', '.join(names)}. 먼저 두 출구를 보세요 — ①스냅샷에서 파생해 변수를 지운다 "
            f"②Python 스냅샷으로 승격한다(전이 함수가 렌더 팬아웃으로 붕괴). 순수 뷰 찌꺼기라 "
            f"둘 다 아니면 이 예산의 상한을 올리되 파생 불가 사유를 선언 옆 주석으로 남기세요."
        )


def test_render_layer_state_budget_covers_every_screen():
    """모든 화면 파일이 예산에 등재돼 있다 — 신설 화면이 예산 밖으로 조용히 새지 않게.

    커버리지 가드가 없으면 예산은 "등재된 파일만" 지키고 다음 화면은 처음부터 자유가 된다.
    F2 PR-A 의 건강 번역 커버리지 테스트와 같은 형태 — 다음 누락은 사람이 아니라 게이트가 잡는다.
    """
    # 등재 의무는 **가변 상태를 실제로 든 파일**에 건다. 0 인 파일까지 열거하면 표가 렌더 층
    # 파일 목록의 사본이 되어 리팩터마다 붉고, 그 마찰이 「예산을 지운다」는 처분을 부른다.
    carrying = {
        path.name for path in R4_SCREENS_DIR.glob("*.ts")
        if _mutable_module_state(path.read_text(encoding="utf-8"))
    }
    missing = sorted(carrying - set(MUTABLE_MODULE_STATE_BUDGET))
    assert not missing, (
        f"가변 모듈 상태를 든 렌더 층 파일이 예산에 없습니다: {', '.join(missing)}. "
        f"MUTABLE_MODULE_STATE_BUDGET 에 실측 상한을 등재하세요(기준선은 낮게 — 실행 표면 10 은 "
        f"긴 절차가 만든 부채지 목표가 아닙니다)."
    )


def test_job_overwrite_uses_shared_confirm_modal():
    """덮어쓰기 확인이 공용 Modal.confirm(수치 합성 본문)을 쓴다 — 전용 모달·window.confirm 무사용.

    슬라이스 2(A-2-22): 전용 jobOverwriteModal 폐기, 수치 합성(총량·파괴분·신규분)은
    overwriteBody 가 조립해 Modal.confirm 본문으로 넘긴다. 네이티브 window.confirm 무사용은
    별도 코멘트-인지 가드(test_web_native_dialog_guard)가 담보한다.
    """
    src = react_job_run_source()
    # R4-03 — 파사드는 주입으로 온다(`deps.modal`). 이름을 전역으로 찾으면 이관을 회귀로
    # 오독하지만, 묻는 것은 그대로다: **공용 확인 파사드**를 쓰는가.
    assert "deps.modal.confirm({" in src, "덮어쓰기 확인이 공용 Modal.confirm 을 쓰지 않습니다(A-2-22)."
    assert "export function overwriteBody(" in src, "수치 합성 본문(overwriteBody)이 없습니다(A-2-22)."


def test_job_overwrite_keeps_busy_lock_through_modal():
    """리뷰 #1 회귀 가드: 작업 화면 덮어쓰기 모달 대기 동안 생성 버튼이 재활성되지 않는다.

    modal.js 는 포커스 트랩이 없어(blocking window.confirm 과 다름) 모달 뒤 살아있는 생성
    버튼에 Tab+Enter 가 닿으면 두 번째 생성이 첫 확인 미결인 채 시작된다(같은 폴더 동시 기록).
    busy-lock 해제(``generating = false``)가 덮어쓰기 확인 await **뒤**에 와야 한다 — 소스
    순서로 정적 가드(실 거동은 selftest 게이트 소관).
    """
    src = react_job_run_source()
    # R4-03 — busy-lock 은 이제 `run.running` 파생이라 「해제」의 실물은 `endRun` 이다.
    # 겨눔은 needs_overwrite **갈래 안**으로 좁힌다: 그 밖에도 `endRun` 이 있어(토큰 계약
    # 위반·확인 취소) 파일 전체에서 첫 좌표를 잡으면 다른 자리를 재고 초록이 된다.
    branch = src[src.index("if (res.needs_overwrite === true) {"):]
    branch = branch[:branch.index("if (res.ok === false")]
    i_confirm = branch.index("await deps.modal.confirm({")
    i_release = branch.index("setRun(endRun(run));")
    assert i_confirm < i_release, (
        "busy-lock 해제가 덮어쓰기 모달 await 전에 온다 — 모달 열림 동안 생성 버튼 재활성으로 "
        "재진입 경합(리뷰 #1). op 종료를 needs_overwrite 흐름 뒤로 미뤄라."
    )
    # 확인 **전에** op 가 살아 있어야 그 잠금이 실제로 잠근다 — 갈래 진입 직후의 상태 반영이
    # `acceptDirect` 인 것이 그 증거다(needs_overwrite 는 running 을 끝내지 않는다).
    assert branch.index("setRun(acceptDirect(run, res));") < i_confirm


def test_job_completion_zone_reset_gated_by_session_change():
    """결과 처분은 지문 **성분별 2분기**다(U2 §2.18 · #340) — 매 push 무조건 리셋 금지(결정 7).

    작업 화면은 REFRESH_ON_NAV 에 있어 레일 복귀마다 full re-push 가 돈다 — 리셋이 무조건이면
    세션 불변인데도 생성 리포트가 소멸(결정 7: 완료 존 = 세션 스코프 보존 위배). 지문이 갈린
    경우의 처분은 성분별로 갈린다: 작업 전환·데이터 교체 = **초기화**(+ 퇴장 한 줄), 선택·
    규칙·저장 폴더 = **강등 유지**(판정 G 의 자기모순 논거가 사는 축 — 「실패한 N건만 선택」이
    자기 결과를 없애면 안 된다). 이름 변경은 전환이 아니다(주체 `own` 이 이름을 추종한다).
    """
    src = react_job_run_source()
    assert "export function sessionKeyOf(" in src, "완료 존 세션 지문(sessionKey)이 없습니다(#3)."
    # 지문은 단일 문자열이 아니라 성분 구조다(§2.18) — 문자열 하나로는 무엇이 갈렸는지 모른다.
    key_fn = src.split("export function sessionKeyOf", 1)[1].split("\n}", 1)[0]
    assert '.join("|")' not in key_fn, "세션 지문이 단일 문자열로 접혔습니다 — 성분 판독 불가(§2.18)."
    for comp in ("job:", "data:", "out:", "sel:", "rules:", "own:"):
        assert comp in key_fn, f"세션 지문 성분 누락: {comp}"
    # 데이터 성분은 **정체**(Python 이 낸 마운트 세대)이지 표시 라벨이 아니다(#363 리뷰 P2):
    # `data_source_label` 은 「파일: <basename>」이라 같은 이름의 다른 파일·같은 통합문서의
    # 다른 시트·같은 경로 재읽기가 전부 같은 문자열이고, 그러면 「데이터 교체 = 초기화」가
    # 그 경우들에서 서지 않는다. 표면이 경로·시트로 정체를 다시 조립해도 안 된다(두 층 판정).
    assert "data: String(snapshot.data_mount" in key_fn, (
        "데이터 성분이 마운트 정체가 아닙니다(§2.18 · #363)."
    )
    # 금지 이름은 **코드에서만** 센다 — 주석은 죽은 이름을 일부러 남겨 함정을 설명하므로
    # (`.job-item`·`.mir-row.miss` 선례와 같은 규율) 그것을 규칙으로 세면 거짓 실패가 난다.
    key_code = _strip_js_comments(key_fn)
    for banned in ("data_source_label", "data_target", "data_label"):
        assert banned not in key_code, (
            f"세션 지문이 {banned} 에서 파생됩니다 — 표시 라벨·자체 조립은 정체가 아닙니다"
            "(같은 basename 의 다른 파일이 교체로 안 읽힙니다)."
        )
    assert "disposeBySession(before, sessionKeyOf(before.lastFull)" in src, (
        "처분이 성분별 판정 단일 지점을 지나지 않습니다(§2.18)."
    )
    dispose = src.split("export function disposeBySession", 1)[1].split("\n}", 1)[0]
    # 초기화 축(작업 전환·데이터 교체)과 강등 축(선택·규칙·저장 폴더)이 각각 실재해야 한다.
    assert "prev.data !== next.data" in dispose and 'kind: "reset"' in dispose, (
        "데이터 교체가 결과를 초기화하지 않습니다(§2.18 — 링1 은 이미 증거를 죽였다)."
    )
    assert "next.own !== next.job" in dispose, (
        "작업 축 판정이 개명(주체 추종)과 전환을 가르지 않습니다 — 이름만 바꿔도 결과가 죽습니다."
    )
    assert 'kind: "stale"' in dispose, "선택·규칙·저장 폴더 축의 강등 유지가 사라졌습니다(판정 G)."
    for comp in ("prev.out !== next.out", "prev.sel !== next.sel", "prev.rules !== next.rules"):
        assert comp in dispose, f"강등 축 성분 비교 누락: {comp}"
    # 초기화의 퇴장 한 줄(경로 포함)은 리셋 **뒤에** 적는다 — 리셋이 실행 기록을 비우므로
    # 순서가 뒤집히면 한 줄이 함께 지워져 소멸이 조용해진다.
    # 판정(`disposeBySession`)과 그 판정의 소비(`ingestFull`)는 자리가 갈렸다. 순서 계약은
    # 소비 쪽에 산다 — 판정 함수만 보면 「리셋 뒤에 적는가」를 물을 대상이 없다.
    ingest = src.split("function ingestFull", 1)[1].split("\n  }", 1)[0]
    assert "resultExitLine(before.result," in ingest, (
        "퇴장 한 줄이 그 결과를 인자로 받지 않습니다 — 순수 합성기 계약(네 태 되읽기)."
    )
    # 재는 것은 **합성 위치가 아니라 기록 쓰기 위치**다. 합성은 `before` 사본에서 하므로
    # 언제 해도 같은 값이고, 리셋에 지워지는 것은 쓰기다 — 합성 위치를 대용으로 쓰면 순서를
    # 안 어긴 재배치가 빨갛고, 정작 쓰기가 앞서는 진짜 결함은 통과할 수 있다.
    assert "setRun(next);" in ingest, "스냅샷 유입이 상태를 세우지 않습니다."
    clear = "ui = { log: [], logOpen: false };"
    assert clear in ingest, (
        "초기화가 실행 기록을 비우지 않습니다 — 죽은 세션의 줄이 다음 세션 밑에 쌓여 "
        "「이어지는 한 실행」으로 읽힙니다(legacy `resetGenResult` 동등성)."
    )
    assert ingest.index(clear) < ingest.index("log(line)"), (
        "퇴장 한 줄이 기록을 비우기 전에 적혀 함께 지워집니다."
    )
    assert 'disposal.kind === "reset"' in ingest, (
        "퇴장 한 줄이 초기화 갈래에서만 나지 않습니다 — 강등에도 나면 그 줄이 거짓말이 됩니다."
    )
    exit_fn = src.split("export function resultExitLine", 1)[1].split("\n}", 1)[0]
    exit_code = _strip_js_comments(exit_fn)
    assert "r.out_dir" in exit_code, (
        "퇴장 한 줄이 경로를 재진술하지 않습니다(§2.18 — 손으로 고른 저장 폴더의 마지막 보관처)."
    )
    # 수치 몸통은 **Python 이 낸 퇴장 요약**을 그대로 쓴다(#363 리뷰 P2 2차): 구획
    # 제목은 머리라 일부러 짧아(취소 갈래가 실패 수를 접고 `failed` 태가 수치를 통째로
    # 생략) 초기화 뒤 남는 유일한 흔적이 되기엔 손실 함수다. 표면에서 되메우면 수치를
    # 두 층이 조립하게 되므로, 목적이 다른 합성기를 Python 에 두고 여기서는 고르기만 한다.
    assert "r.exit_summary" in exit_code, "퇴장 한 줄이 Python 퇴장 요약을 쓰지 않습니다."
    # 요약이 없는 실행 결과를 **조용히 건너뛰지 않는다**: 이 줄이 유일한 흔적이라 침묵은
    # 소멸을 흔적 없이 지우는 것이다(confirm-or-alarm). 수치는 지어내지 않고 모른다고 적는다.
    assert "수치 요약 없음" in exit_fn, (
        "요약 없는 결과에서 퇴장 한 줄이 조용히 사라집니다 — 소멸의 유일한 흔적입니다."
    )
    for banned in ("r.total", "r.title", "r.succeeded", "r.failed", "r.unstarted"):
        assert banned not in exit_code, (
            f"퇴장 한 줄이 수치를 표면에서 재조립합니다({banned}) — 합성기가 두 층에 생깁니다."
        )
    # 순수 합성기 — 실앱 게이트가 네 태의 산출을 되읽는다(overwriteBody·guardBody 와 같은 자리).
    # 인자 둘을 받는 **모듈 최상위** 함수라야 그 되읽기가 성립한다: 컨트롤러 클로저 안으로
    # 들어가면 상태를 읽을 수 있게 되고 게이트가 태를 하나씩 세울 seam 이 사라진다.
    assert "export function resultExitLine(r: Obj | null, owner: string): string {" in src, (
        "퇴장 한 줄이 모듈 상태를 읽습니다 — 네 태를 되읽을 seam 이 사라집니다."
    )
    assert "overwriteBody, guardBody, resultExitLine," in src, (
        "퇴장 한 줄 합성기가 실앱 게이트에 노출되지 않았습니다."
    )
    # 「결과 닫기」(명시 파기)는 로그 한 줄을 남기지 않는다(§2.18 파기 대칭) — 닫기 핸들러가
    # 퇴장 한 줄 경로를 타면 치우라는 행동이 흔적을 남긴다.
    close_wire = src.split("closeResult(): void {", 1)[1].split("\n    },", 1)[0]
    assert "resultExitLine" not in close_wire and "log(" not in close_wire, (
        "「결과 닫기」가 로그 흔적을 남깁니다(§2.18 파기 대칭 위반)."
    )
    # 옛 무조건 리셋이 남아 있으면 안 된다 — 실행 중 도착한 full 은 자기 결과를 처분하지
    # 않고(자기모순 차단), 그 밖의 처분은 전부 성분별 2분기를 지난다.
    assert "if (state.running) return { ...state, lastFull: snapshot };" in src, (
        "무조건 완료 존 리셋이 남아 있습니다 — nav 복귀마다 생성 리포트 소멸(리뷰 #3, 결정 7)."
    )


# (구 test_run_overwrite_keeps_busy_lock_through_modal 삭제 — run.js 사망(슬라이스 3).
#  동형 가드는 test_job_overwrite_keeps_busy_lock_through_modal 가 job.js 에서 이어받는다.)


def test_modal_promise_dialog_serialization_guards_present():
    """PR #92 리뷰 #1/#3/#4 정적 가드 — R3-01(#410) 뒤 세 다리의 **새 거처**를 겨눈다.

    실 거동(재진입 loud 거절·Tab 순환·개폐)은 selftest 게이트가 되읽는다 — 여기선 헤드리스
    포함 전 플랫폼에서 가드 코드의 존재를 정적으로 단언해 조용한 삭제 회귀를 막는다:
      - 재진입 가드(pendingDialog): 판정은 엔진(engine.ts)이 소유하고 파사드는 관측면으로
        같은 거절을 잇는다(리뷰 #1). modal.js 의 자기 불리언 **잔존은 금지 계약**이다 —
        남으면 legacy 와 React 다이얼로그의 직렬화가 두 세계로 갈린다(#410 §4.3).
      - 포커스 트랩(trapTab): legacy 집행은 modal.js, React 다이얼로그 집행은 host.ts —
        두 집행자가 같은 엔진 판정(최상위 소유) 아래 선다(리뷰 #1).
      - IME 조합 가드(isComposing): 문서 keydown 판정은 엔진, prompt Enter 는 host(리뷰 #3).
      - loud 거절(window.alert + console.error): 문안·거절 재진술은 파사드 소유 그대로(리뷰 #4).
    """
    src = (WEB_JS_DIR / "modal.js").read_text(encoding="utf-8")
    engine = source_text("src", "overlay", "engine.ts")
    host = source_text("src", "overlay", "host.ts")
    assert "pendingDialog" in engine and "acquireDialog" in engine, (
        "promise 다이얼로그 재진입 가드(pendingDialog)가 엔진에서 사라졌습니다(#92 #1)."
    )
    assert "pendingDialog" not in src, (
        "modal.js 에 자기 직렬화 불리언이 잔존합니다 — 판정 이원화(두 세계 분열, #410 §4.3)."
    )
    assert "const stack" not in src and "stack.push(" not in src, (
        "modal.js 에 자기 스택이 잔존합니다 — 판정 이원화(두 세계 분열, #410 §4.3)."
    )
    assert "overlayEngine.isDialogPending()" in src, (
        "파사드가 엔진 직렬화 관측면을 잇지 않습니다 — 재진입 거절 경로 상실(#92 #1)."
    )
    assert "trapTab" in src, "legacy 포커스 트랩(trapTab)이 사라졌습니다 — 배경 Tab 이탈 재개방(#92 #1)."
    assert "trapWithin" in host, "React 다이얼로그 포커스 트랩(trapWithin)이 사라졌습니다(#92 #1)."
    assert "isComposing" in engine and "isComposing" in host, (
        "IME 조합 가드(isComposing)가 사라졌습니다 — 조기 제출 회귀(#92 #3)."
    )
    assert "window.alert" in src and "console.error" in src, (
        "골격 부재/재진입 거절의 loud 경로(window.alert/console.error)가 사라졌습니다 — "
        "조용한 no-op 는 confirm-or-alarm 위반(#92 #4)."
    )


def test_component_gallery_links_real_stylesheets_drift_free():
    """살아있는 컴포넌트 갤러리(docs/UI_GALLERY.html)는 실 stylesheet 를 <link> 로 물어야 한다.

    갤러리의 유일한 존재 이유는 드리프트-0 — 앱 CSS 를 고치면 자동 반영되는 정직한 거울이다.
    CSS 를 인라인 복사하면 실앱과 조용히 어긋난다(목업 docs/UI_PROTOTYPE_APPB.html 이 그 함정:
    색만 생성기 동기, 나머지 드리프트). 따라서 갤러리는 반드시 (a) 실 스타일시트 전 조각을
    **셸과 같은 순서로** 링크하고 (b) 인라인 스타일에서 앱 색 토큰(--a-*)을 재정의하지
    않는다 — 복사본 재유입을 loud 하게 차단한다.

    순서까지 보는 이유: 앱 CSS 는 순서 보존 컷이라 **링크 순서가 곧 캐스케이드**다. "각
    파일명이 어딘가 있는가"만 검사하면 두 링크를 뒤바꿔도 초록이고, 그러면 갤러리는
    드리프트-0 을 표방한 채 실앱과 다른 화면을 그린다(PR #322 리뷰 P2).
    """
    assert GALLERY.exists(), f"컴포넌트 갤러리가 없습니다: {GALLERY}"
    html = GALLERY.read_text(encoding="utf-8")
    _IdCollector().feed(html)  # 구문 파싱 OK(기존 관례 HTMLParser).
    linked = linked_css(html, "../frontend/css/")
    assert linked == ALL_CSS_FILES, (
        "갤러리의 스타일시트 <link> 가 셸과 다릅니다 — 드리프트-0 불변식 위반.\n"
        f"  갤러리:     {linked}\n"
        f"  매니페스트: {ALL_CSS_FILES}\n"
        "전 조각을 같은 순서로 링크하세요(순서가 캐스케이드입니다)."
    )
    assert not re.search(r"--a-[\w-]+\s*:\s*#", html), (
        "갤러리 인라인 스타일이 앱 색 토큰(--a-*)을 재정의합니다 — "
        "링크된 tokens.css 만 쓰세요(인라인 복사는 드리프트 재도입)."
    )


def test_heading_typography_uses_three_shared_roles():
    """H-01: 화면·구획·존 제목은 세 역할 규칙만 소비한다."""
    css = "".join(WEB_CSS.split())
    assert ".scr-headh1{font-size:var(--fs-section);font-weight:700}" in css
    # (.tpl-band .tb-t 멤버는 tpl 화면 사망(F8)과 함께 역할군에서 걷혔다 — 정적 생존 표본은
    #  .modal-card h3, 실렌더 판은 selftest milestone-H 프로브가 같은 표본으로 잰다.)
    assert (
        ".lib-detail-name,.job-sec-head,.modal-cardh3{"
        "font-size:var(--fs-strong);font-weight:700}"
    ) in css
    assert (
        ".zone-cap,.paneh4,.qd-formpaneh4,.qd-prevpaneh4{"
        "font-size:var(--fs-dense);font-weight:700}"
    ) in css
    # 옛 컴포넌트별 값이 돌아오면 역할 규칙보다 뒤에서 덮어쓸 수 있다.
    for stale in (
        ".job-sec-head{display:flex;align-items:center;justify-content:space-between;gap:var(--sp-8);font-size:",
        ".zone-cap{display:block;margin-bottom:var(--sp-10);font-size:",
        ".lib-detail-name{font-size:",
    ):
        assert stale not in css, f"개별 제목 타이포 재정의가 돌아왔습니다: {stale}"


def test_gallery_exposes_heading_role_specimens():
    html = GALLERY.read_text(encoding="utf-8")
    for label in ("화면 제목", "구획 제목", "존·소제목"):
        assert label in html, f"갤러리에 제목 역할 표본이 없습니다: {label}"


def test_job_session_surface_uses_v6_two_column_captions():
    """재작성 R1: 「작업」 세션 표면의 구획 문법 — 번호 없는 v6 캡션 6종.

    H-03 의 znum 4존 문법은 **이 화면에서만** 은퇴한다: v6 `screen-data` 는 순서가 있는
    4단계가 아니라 마주 보는 두 열이고, 세로 1·2·3·4 를 2열에 얹으면 번호가 읽는 순서와
    어긋난다(우측 첫 구획이 ②가 되는 식). 기안(`draft`)의 znum 문법은 그대로 산다 —
    거기는 여전히 순서 있는 세션이었으나 화면째 사망했다(F6 PR-B) — znum 문법은 이제
    소비자가 없다. 번호의 정보(다음에 어디로)는 게이트 문안의 구획 지목(`gateStep`)이
    승계한다.
    """
    job_static = " ".join(R4_PRODUCT_SCREENS.read_text(encoding="utf-8").split())
    # 캡션 여섯의 생산자가 셋으로 갈렸다(정적 셸 · read 표면 · 실행 표면). 합쳐서 묻는
    # 이유는 계약이 재는 것이 **캡션의 존재**이지 어느 파일이 적었는가가 아니기 때문이다.
    job_react = " ".join(R4_JOB_READ.read_text(encoding="utf-8").split())
    job_run = " ".join(react_job_run_source().split())
    job = job_static + job_react + job_run
    # 「선택한 작업」 캡션은 존 사망(U2 §4 판정 A, #342)으로 이 목록에서 빠졌다 — 정체는
    # 활성 후보 카드·액션바 이름이 승계한다(승계 계약은 전용 테스트가 진다).
    for caption in (
        "현재 데이터", "본문 확인", "생성 결과",
        "이 데이터에 사용할 문서", "생성 준비",
    ):
        # 캡션 자리에 id 가 붙을 수 있다(「생성 준비」는 매체에 따라 「복사 준비」로 바뀐다) —
        # 계약이 세는 것은 **zone-cap 캡션의 존재**이지 속성 목록이 아니다.
        assert caption in job, f"세션 구획 캡션이 없습니다: {caption}"
    assert '<span class="znum">' not in job_static and 'className: "znum"' not in job_react, (
        "「작업」 세션 표면에 구 4존 서수가 재유입됐습니다."
    )
    # (znum 존치 단언 삭제 — 유일 소비자였던 「기안」이 화면째 사망, F6 PR-B.)


def test_job_result_zone_declares_the_three_state_contract():
    """F4(지도 §10.10): 결과 3태 구획의 정적 계약 — 태 소유자·행동 4종·증거·실행 기록 존치.

    태를 문안이 아니라 ``[data-state]`` 가 소유하는 것이 요점이다: 문안으로 태를 읽으면
    번역·재작문 한 번에 판정이 끊긴다. 실행 기록(로그 상자)은 **살아 있어야 한다** —
    결과 사건만 3태가 가져갔고 비-결과 사건(데이터 불러옴·검색 실패·중단 요청)은 이
    화면의 유일한 비모달 채널이라 함께 죽이지 않았다(§10.10 판정 D).
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    result_src = R4_JOB_RESULT.read_text(encoding="utf-8")
    flat = " ".join(result_src.split())
    # 태의 소유자 — 구조는 `data-state`, 색은 `data-level`. 문안이 아니다.
    assert 'id: "jobResult", className: "result3", "data-state": state,' in flat
    assert '"aria-live": "polite", hidden: shown === null,' in flat
    for bid in ("jobResultFailedSel", "jobResultRename", "jobResultClose"):
        assert re.search(rf'id: "{bid}", type: "button", "data-busy-lock": true', flat), (
            f"결과 구획 행동이 busy-lock 을 선언하지 않았습니다: {bid}"
        )
    for pid in ("jobResultTitle", "jobResultSummary", "jobResultStale",
                "jobResultDir", "jobResultTrack", "jobResultFails"):
        assert f'id: "{pid}"' in flat, f"결과 구획 조각 누락: {pid}"
    # 증거는 <details> 다 — 열림 상태를 DOM 이 소유해야 재렌더를 건넌다(계약면 1).
    assert 'h("details", { className: "result3-evidence", id: "jobResultEvidence"' in flat
    # 구 단일 요약 줄은 3태 구획이 승계했다(두 벌 병존 금지).
    assert 'id="jobGenResult"' not in html and 'id: "jobGenResult"' not in flat
    # 실행 기록은 존치하되 역할이 바뀌었고(캡션), **기본은 접힘**이다(평상시 노이즈 억제).
    # 단 접힘이 소음 제거가 되면 안 된다 — 마지막 기록 한 줄은 요약에 상시 남는다.
    assert 'h("details", { className: "runlog", id: "jobRunLog", open: run.logOpen }' in flat
    assert 'className: "zone-cap zone-cap-sub" }, "실행 기록")' in flat
    assert 'id: "jobRunLogLast"' in flat and 'id: "jobGenLog"' in flat
    assert 'lines.length ? lines[lines.length - 1] : "아직 기록이 없습니다."' in flat, (
        "접힌 실행 기록의 요약 줄이 갱신되지 않으면 실패 통보가 조용해집니다."
    )


def test_job_gate_adds_blocked_step_only_in_display_layer():
    """H-03 승계: gate.level 판정은 건드리지 않고 표시층에서 막힌 **구획 이름**만 결합한다.

    R1 이 4존 서수를 은퇴시켰으므로 지목도 실재하는 구획 캡션을 쓴다 — 죽은 번호를 남기면
    지목 자체가 거짓말이 된다. 지목 문자열은 반드시 실제 `zone-cap` 캡션과 일치해야 한다.
    """
    src = react_job_run_source()
    product = " ".join(R4_PRODUCT_SCREENS.read_text(encoding="utf-8").split())
    # 캡션 생산자가 셋으로 갈렸으므로 「지목이 실재하는 구획을 가리키는가」도 셋을 합쳐 묻는다.
    job = (
        product
        + " ".join(R4_JOB_READ.read_text(encoding="utf-8").split())
        + " ".join(src.split())
    )
    assert "function gateStep(s: Obj, g: Obj): string {" in src
    assert not re.search(r'return "[①②③]', src), "죽은 4존 서수가 남아 있습니다."
    # 「선택한 작업 · 」 지목은 존과 함께 죽었다(U2 §4, #342).
    assert '"선택한 작업 · "' not in src, "죽은 존을 가리키는 지목이 남아 있습니다."
    # 지목은 **링1 이 낸 축 이름**(gate.reason)에서 나온다(#342 리뷰 P2). 표면이 상태를
    # 다시 읽어 지목을 만들면 게이트 서열이 두 곳에 살고, 실제로 그렇게 샜다 — 템플릿
    # 부재를 직접 보고 접두를 붙여 **행 선택이 먼저인** 상태의 지목을 덮었다.
    step = src[src.index("const GATE_ZONE"):src.index("export function JobActionBar")]
    assert "GATE_ZONE[String(g.reason" in step, "게이트 지목이 축 이름을 읽지 않습니다."
    assert "s.template_missing" not in step, (
        "표면이 템플릿 상태로 지목을 재유도합니다 — 게이트 서열을 덮는 자리입니다."
    )
    # 템플릿 축은 가리킬 구획이 없다(존 사망) — 곁의 액션바 재연결이 답이라 빈 문자열이다.
    assert 'template_missing: ""' in step and 'template_unreadable: ""' in step
    for caption in ("현재 데이터", "이 데이터에 사용할 문서", "본문 확인"):
        assert f'"{caption} · "' in src or f'= "{caption} · "' in src, (
            f"게이트 구획 지목 누락: {caption}"
        )
        assert caption in job, f"지목이 실재하지 않는 구획을 가리킵니다: {caption}"
    # 「본문 확인」 지목은 **이름 있는 축**(drift·name_tokens)에만 남는다: 그 danger
    # 배너는 재편 뒤에도 그 존에 살기 때문이다. 반대로 **이름 없는 warn 의 폴백**은
    # 필드축 ack 폐기(U2 §2.13)로 마지막 소비자를 잃었다 — 남는 것(저장 폴더·이어채우기)
    # 은 본문 축이 아니라 그 자리를 가리키면 거짓 지목이 된다.
    assert 'drift: "본문 확인 · "' in step, "danger 배너의 축 지목이 사라졌습니다."
    assert "return GATE_ZONE.drift" not in step, (
        "이름 없는 warn 이 여전히 「본문 확인」을 가리킵니다 — 폐기된 필드축 지목입니다(§2.13)."
    )
    assert "`${gateStep(s, gate)}${String(gate.text || \"\")}`" in src
    assert not re.search(r"\b(?:g|gate)\.level\s*=(?!=)", src), (
        "표시층이 gate.level 판정을 변조하면 안 됩니다."
    )


def test_job_active_zone_death_and_candidate_card_succession():
    """U2 §4(#342): 「선택한 작업」 존 사망 + 후보 카드·액션바·라이브러리 상세 승계.

    존은 실측상 어포던스의 **세 번째 사본**이라 이관 없이 죽지만, 사망 조건 점검표의 전
    행이 새 거처에서 도달 가능해야 한다: 작업명=활성 카드 하이라이트+액션바 이름 · 템플릿
    파일명=활성 카드 확장 부제 · 열기/폴더에서 보기=활성 카드 ⋮ + **라이브러리 상세 신설**
    (§2.20 — 경보는 라이브러리가 내는데 조작이 거기 없었다) · 재연결=경고 카드 기본 클릭
    (판정 D — 선택이 아니다) · `template_missing` 경보=카드 「연결 상태」(판정 C — 텍스트가
    정본, 색은 강조). 편집기 「템플릿」 탭의 같은 어포던스는 그대로 산다(사본 셋→둘, §2.20 ⑷).
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    job_js = R4_JOB_READ.read_text(encoding="utf-8")
    run_js = react_job_run_source()
    lib_js = R4_LIBRARY.read_text(encoding="utf-8")
    editor_js = R4_EDITOR.read_text(encoding="utf-8")
    relink_js = (R4_SCREENS_DIR / "job_relink.ts").read_text(encoding="utf-8")
    css = "".join(WEB_CSS.split())

    # ① 존은 죽었다 — 조각(id·class)이 셸·화면 JS 어디에도 남지 않는다.
    for dead in ("jobHeadTitle", "jobHeadTpl", "jobRelink"):
        assert f'id="{dead}"' not in html and f'id: "{dead}"' not in job_js, (
            f"죽은 존 조각이 남았습니다: {dead}"
        )
    assert "job-active-zone" not in html and "job-active-zone" not in job_js
    # ② 작업명의 상시성(§4-A 상속 의무) — 활성 카드는 스크롤 위로 사라지므로 상수 높이
    #    층인 액션바가 이름을 겸한다. 빈 값은 자리도 비운다(capnote 와 같은 규칙).
    assert 'id: "jobActionName"' in run_js
    assert 'on ? String(s?.job_name || "") : ""' in run_js
    assert ".actionbar-job:empty{display:none}" in css
    # ②-b **재연결 도달 보장은 액션바(상수 층)가 진다**(#342 리뷰 3라운드 근본 조치).
    #    후보 구획은 데이터 마운트·호환성·순위 슬라이스 셋에 걸린 투영이라 그 위에 보장을
    #    얹으면 조건마다 구멍이 하나씩 난다(같은 결함류 3건). 이 층은 조건이 없다 —
    #    세션 스냅샷 두 값(template_missing·conn_label)만 읽는다. 상태 순회 단언은
    #    tests/test_webapp_job.py 의 불변식 테스트가 진다.
    for pid in ("jobActionConn", "jobActionRelink"):
        assert f'id: "{pid}"' in run_js, f"액션바 연결 상태·재연결 조각 누락: {pid}"
    assert "s?.template_missing" in run_js and "s?.conn_label" in run_js, (
        "액션바가 세션 축의 연결 상태를 읽지 않습니다 — 도달 보장이 다시 카드에 기생합니다."
    )
    # 부재는 `hidden` 이지 `disabled` 가 아니다 — 잠금(생성 중)과 부재(연결 온전)는 다른
    # 사건이고, 하나로 접으면 busy-lock 일괄 복원이 없는 버튼을 되살린다.
    assert 'id: "jobActionRelink", type: "button", "data-busy-lock": true,' in run_js
    assert "hidden: !missing, disabled: busy," in run_js, (
        "재연결 버튼을 disabled 로 가리면 busy-lock 일괄 복원이 되살립니다."
    )
    # 정렬 여백은 **묶음 하나**가 진다 — 「마지막 보이는 것」에 거는 규칙은 상태 열거가 되고,
    # 이 라운드가 고치는 결함류가 정확히 그 형태다.
    assert ".actionbar-identity{display:flex;align-items:center;gap:var(--sp-8);min-width:0;margin-right:auto}" in css
    # ③ 활성 카드 확장 부제 + ⋮ — 부유 메뉴 호스트(그룹 ⋮ 동형)와 PathTrack 위임 재사용.
    assert "cand-tpl" in job_js and '"data-cand-menu": true' in job_js
    assert 'className: "cand-inline-menu", role: "menu"' in job_js
    assert "h(PathActions as any" in job_js
    # ④ 「연결 상태」 — 문안은 Python(conn_label)이 내고 카드가 그린다. 색은 강조일 뿐이다.
    assert "row.conn_label" in job_js
    assert ".cand-conn{color:var(--a-warn);font-weight:700}" in css
    # 활성+경고 겹침은 경고가 이긴다 — 경고 규칙이 활성 규칙 **뒤에** 서야 한다.
    assert css.index(".job-cand-card.active{") < css.index(".job-cand-card.warn{")
    # 활성 카드 재클릭 무동작(pointer-events:none)은 경고 카드에서 걷는다 — 안 걷으면
    # 활성+경고의 기본 클릭(재연결 입구)이 마우스에서 죽는다.
    assert '.job-cand-card.warn.cand-pick[aria-pressed="true"]{pointer-events:auto}' in css
    # ⑤ 경고 카드 기본 클릭 = 재연결 리다이렉트(선택이 아님), 커밋 성사 뒤에만 이어서 선택.
    #    두 입구(경고 카드·액션바)는 **한 몸통**을 쓴다 — 각자 흐름을 들면 확인 문안·T1
    #    가드·발신 순서가 갈린다.
    assert '"data-missing": missing ? "1"' in job_js and "relinkTemplateFor" in job_js
    assert job_js.count("services.relink.current().relinkTemplate(") == 1, (
        "재연결 흐름의 입구가 둘인데 몸통도 둘이면 가드·문안이 갈립니다."
    )
    assert "await deps.services.relink.current().relinkTemplate" in job_js
    assert "return false" in relink_js and "return true" in relink_js, (
        "relink 공용 흐름이 커밋 성사 여부를 반환하지 않으면 「이어서 선택」이 실패 뒤에도 나갑니다."
    )
    # ⑥ 라이브러리 상세 신설(§2.20) — payload 한 칸(template_path)이 선행이고 그 칸을 겨눈다.
    assert "h(PathActions as any" in lib_js and "path: detail.template_path" in lib_js
    lib_py = (REPO_ROOT / "src" / "hwpxfiller" / "webapp" / "screen_library.py").read_text(
        encoding="utf-8"
    )
    assert '"template_path": job.template_path' in lib_py
    # ⑦ 편집기 「템플릿」 탭의 같은 어포던스는 그대로 산다(§2.20 ⑷ — 옮기는 것이 아니다).
    assert "path: snapshot.template_path" in editor_js


def test_needs_and_missing_template_redirect_to_different_places():
    """U2 §4 판정 E(#349) — 리다이렉트는 **2분기**이고 두 목적지가 서로 다르다.

    §18.7 의 6분기 중 넷은 짓지 않았다(1은 실행 게이트가·2·3은 데이터 축이 이미 풀고,
    5는 후보 목록의 정체를 바꾸는 별개 결정, 6은 계약이 리다이렉트를 금지). 남은 둘은
    같은 「연결 상태」 어휘 아래 **사유가 목적지를 가른다**:

    - 데이터 구조 불일치(`needs_action` 의 유일 원인) → 없는 열 열거 + **새 작업 마법사**
    - 템플릿 부재 → 「템플릿 없음」 + **재연결**(#342 의 자리 그대로)

    두 값을 한 테스트가 **대조**하는 이유는 이 판정의 내용이 「둘이 다르다」이기 때문이다 —
    각자 따로 단언하면 나중에 한쪽이 다른 쪽으로 접혀도 둘 다 초록이다.
    """
    job_js = R4_JOB_READ.read_text(encoding="utf-8")
    entry_js = R4_EDITOR_ENTRY.read_text(encoding="utf-8")
    bridge_js = (WEB_JS_DIR / "bridge.js").read_text(encoding="utf-8")
    editor_js = R4_EDITOR.read_text(encoding="utf-8")

    # ① 확인 필요 행은 죽은 줄이 아니라 마법사 입구다 — 사유 문안은 그대로 남는다.
    assert 'className: "browse-row off"' not in job_js, (
        "확인 필요 행이 여전히 비활성 div 입니다 — 판정 E 의 목적지가 서지 않았습니다."
    )
    assert "data-browse-new" in job_js and "현재 데이터에 없는 열" in job_js, (
        "확인 필요 행이 사유(없는 열)와 목적지를 함께 말하지 않습니다."
    )
    # ② 목적지가 갈린다 — needs 는 새 작업 흐름, 템플릿 부재는 재연결 흐름.
    needs_at = job_js.index("function BrowseRow(")
    assert "newWorkFromData" in job_js and "relinkTemplateFor" in job_js
    needs_branch = job_js[needs_at:job_js.index("export function JobBrowseDialog", needs_at)]
    assert "newWorkAfterBrowseClose" in needs_branch and "relinkTemplateFor" not in needs_branch, (
        "확인 필요 행이 재연결로 갑니다 — 두 사유의 목적지가 접혔습니다."
    )
    miss_at = job_js.index("function CandidateCard(")
    miss_branch = job_js[miss_at:job_js.index("function NewWorkButton", miss_at)]
    assert "relinkTemplateFor" in miss_branch and "newWorkFromData" not in miss_branch, (
        "템플릿 부재 카드가 마법사로 갑니다 — 재연결 자리(#342)가 소실됐습니다."
    )
    # ③ 두 입구(§2.4 후보 줄 버튼 · 판정 E 확인 필요 행)는 **한 몸통**을 쓴다.
    assert '"data-new-work"' in job_js and 'id: "jobCandNewWork"' in job_js
    assert job_js.count("editorEntry.current().newDraftFromData(") == 1, (
        "「이 데이터로 새 작업」의 입구가 둘인데 몸통도 둘이면 확인 문안·문맥이 갈립니다."
    )
    # ④ 진입 문맥은 보낸 표면이 싣고 편집기가 그 사유로 배너를 세운다(문맥 없는 진입 금지).
    assert 'entry_reason: "document_browser_new_work"' in job_js
    assert "document_browser_new_work:" in editor_js, (
        "편집기가 새 진입 사유의 배너 문안을 모릅니다 — 사유만 실리고 아무 말도 하지 않습니다."
    )
    # ⑤ 데이터의 정체는 웹이 싣지 않는다 — 지금 무엇이 올라와 있는지는 Python 이 답한다.
    assert 'invoke("new_job_from_data", context' in entry_js, (
        "진입 seam 이 문맥을 백엔드로 흘려보내지 않습니다 — 모든 진입이 자발적 진입으로 떨어집니다."
    )
    assert "newJobFromData(context)" in bridge_js and "new_job_from_data(context" in bridge_js
    assert "data_path" not in job_js, (
        "표면이 데이터 경로를 직접 들고 실어 보냅니다 — 마운트 정체의 단일 출처는 컨트롤러입니다."
    )


def test_every_new_work_entrance_passes_the_same_handoff_gate():
    """#349 리뷰 3R 근본 조치 — **마법사로 가는 입구는 전부 같은 게이트를 지난다**.

    세 라운드가 같은 뿌리였다: 승계 가부 판정은 Python 한 곳(`new_work_handoff` →
    스냅샷 `new_work`)에 있는데 **그 판정을 거치지 않는 입구**가 남아 있었다(1R 참조를
    잃는 입구 · 2R 슬롯을 재해석하는 입구 · 3R 막혔는데 열려 있는 입구). 그래서 이
    테스트가 세는 것은 「지금 두 입구가 옳게 그려지는가」가 아니라 **「게이트를 안 지나는
    입구를 지을 수 있는가」**다 — 훅 발행처를 한 표로 묶고, 그 표 밖의 발행을 금지한다.
    새 입구가 생겨도 헬퍼를 쓰지 않으면 여기서 먼저 걸린다(선언이 아니라 결과를 센다).
    """
    job_js = R4_JOB_READ.read_text(encoding="utf-8")

    body_at = job_js.index("function newWorkFromData(")
    body = job_js[body_at:job_js.index("async function relinkTemplateFor", body_at)]
    assert "current?.new_work" in body and "gate.can === false" in body
    assert "gate.reason" in body and "return false" in body
    assert body.count("editorEntry.current().newDraftFromData(") == 1

    # 후보 줄과 확인 필요 행은 둘 다 controller의 같은 재검증 몸통만 호출한다.
    assert job_js.count("controller.newWorkFromData(") == 2
    assert "cand-newwork-why muted" in job_js
    assert '"data-busy-lock": gate.can === false ? undefined : true' in job_js
    assert "disabled: gate.can === false" in job_js
    assert "title: gate.reason || \"\"" in job_js
    browse = job_js[job_js.index("function BrowseRow("):job_js.index("export function JobBrowseDialog")]
    assert '"data-browse-new": gate.can === false ? undefined : row.name' in browse
    assert "현재 데이터에 없는 열" in browse and "gate.reason" in browse


def test_browse_sheet_starts_the_next_flow_only_after_it_finished_closing():
    """#349 리뷰 4R — 닫히는 면 위에 확인 모달을 겹치지 않는다(초점 트랩 탈출 금지).

    탐색 면의 `onClose` 는 닫힘 경로 **전부**에서 무조건 배경으로 초점을 옮긴다(착지 결정은
    닫힘 1지점이라는 이 화면의 규율). 그래서 닫는 **중에** 폐기 확인을 열면, 뒤이어 도착한
    그 착지가 모달 **뒤 배경**(`#jobBrowseOpen`)으로 초점을 옮겨 키보드 사용자가 트랩을
    벗어난다. `Modal` 은 자기 `returnFocus` 를 `wasTop` 으로 지키지만 앱 콜백까지는 지킬 수
    없다 — 무엇을 겨눌지는 이 화면만 안다. 그래서 겹치는 창을 **순서로** 없앤다.

    이 단언이 세는 것은 「지금 초점이 어디 있나」(실렌더 층의 질문)가 아니라 **「겹칠 수 있는
    배선인가」**다: 확인을 여는 흐름이 닫힘 완료 슬롯을 거치지 않고 직접 불리면 실패한다.
    """
    job_js = R4_JOB_READ.read_text(encoding="utf-8")

    reserve = job_js[job_js.index("function newWorkAfterBrowseClose("):
                     job_js.index("async function openBrowseNeedsAction")]
    assert reserve.index("browseAfterClose =") < reserve.index('modal.close("jobBrowseSheet")')
    assert "controller.newWorkFromData" in reserve
    browse_open_at = job_js.index("async function openBrowse(")
    close_at = job_js.index("onClose: () => {", browse_open_at)
    close_cb = job_js[close_at:job_js.index("    });", close_at)]
    assert "const next = browseAfterClose" in close_cb
    assert "browseAfterClose = null" in close_cb
    assert "if (next !== null) next();" in close_cb
    open_fn = job_js[job_js.index("async function openBrowse("):
                     job_js.index("function newWorkAfterBrowseClose")]
    assert "browseAfterClose = null" in open_fn
    browse_row = job_js[job_js.index("function BrowseRow("):
                        job_js.index("export function JobBrowseDialog")]
    assert "newWorkAfterBrowseClose" in browse_row
    assert "closeBrowse();" not in browse_row


def test_job_data_first_prework_surface_contract():
    """데이터-우선(§18.2) 정적 계약 — 후보 구획 실재·빈 패널 은퇴·무작업 렌더 배선.

    구 미선택 빈 패널(jobEmptyPanel)의 재유입을 막고(안내 의무는 prework 게이트 문안이
    승계), 후보 카드 구획과 무작업 서수(②)가 배선돼 있는지 소스 수준에서 못박는다 —
    실렌더 동작판은 selftest ``job_data_first`` 프로브.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    product = R4_PRODUCT_SCREENS.read_text(encoding="utf-8")
    react = R4_JOB_READ.read_text(encoding="utf-8")
    assert 'id: "jobCandsRow"' in product and 'id: "jobCandidates"' in react, (
        "문서 작업 후보 구획이 없습니다(데이터-우선 §18.4)."
    )
    assert "jobEmptyPanel" not in html, (
        "은퇴한 미선택 빈 패널이 재유입됐습니다 — 세션 존은 무작업에도 살아야 합니다(§18.2)."
    )
    src = react_job_run_source()
    assert "export function JobCandidates" in react
    assert "jobEmptyPanel" not in src and "jobEmptyPanel" not in react
    # prework 게이트의 구획 지목 — 이제 **링1 이 낸 축 이름**을 읽는다(#342 리뷰 P2).
    # 서열(데이터 → 행 → 문서)은 `prework_gate` 가 이름으로 내고 표면은 자리로 옮기기만
    # 한다. 이름 없는 갈래(hwpx warn)만 자리로 유추하는 폴백이 남는다.
    assert "GATE_ZONE[String(g.reason" in src, "무작업 prework 게이트의 구획 지목 배선이 없습니다."
    assert "no_data:" in src and "no_job:" in src, "prework 축 이름의 자리 배선이 없습니다."
    assert "if (!s.has_job) return noRows ? GATE_ZONE.no_data : GATE_ZONE.no_job;" in src
    assert '"data-cand": row.name' in react  # 후보 카드 클릭 → select_job 위임
    # 활성 후보 재활성화 가드(#302 리뷰 P2) — pointer-events:none 은 키보드 합성 클릭을
    # 못 막으므로 핸들러가 aria-pressed 를 검사해야 한다(재선택=실행 증거 조용한 소실).
    assert "if (!active) void controller.selectJob(row.name)" in react, (
        "활성 후보 재활성화 가드가 없습니다."
    )


def test_job_display_order_axis_surface_contract():
    """재작성 F3 정적 계약 — 표시순서 축의 요소·2값·⤢ 동행·왕복 의도 보호.

    실행 거동(왕복 뒤 값 유지)은 selftest ``view_order`` 프로브가 본다. 여기서는 그 프로브가
    없으면 조용히 사라질 배선을 못박는다: ①축 요소 3종 ②계약이 정한 2값 그대로(§18.10)
    ③⤢ 펼침 면 이동 목록에 동행(축이 메인에만 남으면 펼친 면에서 도달 불가) ④왕복 중
    의도 보호(pendingOrder) — 셋 다 "지우면 조용히 나빠지는" 배선이다.
    """
    zone = R4_DATA_ZONE.read_text(encoding="utf-8")
    for element in ("jobOrderBar", "jobOrderSel", "jobOrderNote"):
        assert f'id: "{element}"' in zone, f"표시순서 축 요소가 없습니다: {element}"
    assert 'value: "sourceDesc"' in zone and 'value: "sourceAsc"' in zone, (
        "표시순서 2값(§18.10)이 계약 어휘와 다릅니다."
    )
    bootstrap = SOURCE_ROOT.joinpath("src", "bootstrap.js").read_text(encoding="utf-8")
    assert 'productOverlayComponent("dataSheetSlot", PRODUCT_OVERLAY_COMPONENTS.JobDataBody' in bootstrap
    assert 'location: "sheet"' in bootstrap
    assert 'value: snapshot.range_draft?.open' in zone
    assert 'controller.zone("set_view_order"' in zone
    controller = R4_JOB_READ.read_text(encoding="utf-8")
    assert "let zoneTail = Promise.resolve()" in controller


def test_job_range_draft_surface_contract():
    """재작성 F3 정적 계약 — 범위 편집기 footer 의 소유·출구 단일 관문·성사 뒤 열기.

    ①footer 는 화면 DOM 소유다(면 마크업에 두면 같은 면을 쓰는 「기안」에 남의 footer 가
    뜬다) ②모든 출구(취소·닫기·Escape)가 `beforeClose` 한 관문을 지난다 — 경로마다 가드를
    걸면 하나는 반드시 빠진다 ③초안 생성이 성사된 뒤에만 면을 연다.
    """
    src = R4_JOB_READ.read_text(encoding="utf-8")
    zone = R4_DATA_ZONE.read_text(encoding="utf-8")
    for element in ("jobRangeFoot", "jobRangeApply", "jobRangeCancel", "jobRangeSelectedOnly", "jobRangeNote"):
        assert f'id: "{element}"' in zone, f"범위 편집기 출구가 없습니다: {element}"

    open_fn = src[src.index("async function openDataSheet("):src.index("function dropPendingEdits")]
    assert open_fn.index("await flushPendingEdits()") < open_fn.index('await zone("range_draft_open"')
    assert open_fn.index('await zone("range_draft_open"') < open_fn.index("surfaceSheet.open({")
    assert "beforeClose: () => guardRangeClose()" in open_fn

    discard = src[src.index("async function discardRange("):src.index("function guardRangeClose")]
    assert discard.index("dropPendingEdits()") < discard.index('await zone("range_draft_cancel"')
    assert discard.index('await zone("range_draft_cancel"') < discard.index('surfaceSheet.close("dataSheet")')
    apply_fn = src[src.index("async function applyRange("):src.index("async function toggleFavorite")]
    assert apply_fn.index("await flushPendingEdits()") < apply_fn.index('await zone("range_draft_apply"')
    assert apply_fn.index('await zone("range_draft_apply"') < apply_fn.index('surfaceSheet.close("dataSheet")')

    guard = src[src.index("function guardRangeClose("):src.index("async function applyRange")]
    assert "draft.dirty" in guard and "ui.pendingSearch" in guard and "ui.pendingColumn" in guard
    assert "modal.confirm({" in guard and "void discardRange()" in guard
    assert 'props.controller.closeDataSheet();' in zone, (
        "범위 취소 버튼이 SurfaceSheet.close의 beforeClose 이탈 가드를 우회합니다."
    )
    # 모든 변이는 epoch를 싣고 zoneTail 하나로 직렬화하고, filter_panel 질의만 즉시 보낸다.
    call = src[src.index("function zone("):src.index("function browse(")]
    assert "zone_epoch" in call and "zoneTail.then(send, send)" in call
    assert "if (query) return send();" in call
    assert 'controller.zone("filter_panel", { column }, true)' in zone
    assert "job:view_order" not in src
    sheet = (WEB_JS_DIR / "surface_sheet.js").read_text(encoding="utf-8")
    assert "beforeClose" in sheet


def test_job_user_column_hiding_surface_contract():
    """사용자 열 선별(U2 §2.19, #341) 표면 배선 — 판정은 Python, 표면은 그리기만.

    헤드리스 테스트는 링1·컨트롤러 판정(`visible`·`hidden_columns`·`can_hide`)까지만 본다 —
    그 판정을 **소비하는 배선**이 빠지면 백엔드만 있고 표면이 침묵하는 반쪽이 된다(선언은
    살고 결과는 죽는 결함류). 여기서 그 소비를 센다.
    """
    zone = R4_DATA_ZONE.read_text(encoding="utf-8")
    # 표시 여부는 Python 플래그 소비 — 머리·셀이 같은 판정으로 함께 빠진다(ci 정렬 유지).
    assert zone.count("if (column.visible === false) return null") == 1
    assert zone.count("return column.visible === false") == 1, (
        "숨긴 열의 머리·셀 렌더 스킵이 한 쌍이 아닙니다 — 표와 머리가 어긋납니다."
    )
    # 패널 항목은 can_hide(Python 판정)에만 선다 — 시트로 이사한 패널에는 서지 않는다.
    assert "data.can_hide" in zone and '"data-act": "col-hide"' in zone
    assert '"hide_column"' in zone and '"unhide_columns"' in zone
    # 숨김 표지는 상시 칩 — 문안이 축을 말한다(숨김은 보기뿐, 생성 제외가 아니다).
    assert "hidden_columns" in zone and '"data-act": "unhide-cols"' in zone
    assert "생성에는 그대로 쓰입니다" in zone, "숨김 표지 문안이 축(보기≠생성)을 말하지 않습니다."
    assert "보기에서만 숨깁니다" in zone, "패널 항목 문안이 축(보기≠생성)을 말하지 않습니다."
    # 칩 줄은 필터가 없어도 숨김이 있으면 선다(상시 표지 — 0개가 아니면 칩이 선다).
    assert "filter.active || hiddenColumns.length" in zone, "숨김 표지가 필터 활성에 묶여 있습니다."
    css = (SOURCE_CSS_DIR / "jobdata.css").read_text(encoding="utf-8")
    assert ".fchip.hidecols" in css, "숨김 표지 칩 변형 스타일이 없습니다."


def test_job_document_browser_surface_contract():
    """슬라이스 3 정적 계약 — 문서 탐색 면은 `job` 화면의 **하위 화면**이고 판정은 Python 소유.

    별 라우트를 만들지 않는다(§18.6: 상단 내비게이션은 계속 「문서 만들기」 활성) —
    시트 루트·탭·검색·행 호스트가 실재하고, JS 는 목록을 자체 필터하지 않는다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    src = R4_JOB_READ.read_text(encoding="utf-8")
    assert 'id="jobBrowseSheet"' in html
    for dom_id in ("jobBrowseTabs", "jobBrowseQuery", "jobBrowseRows", "jobBrowseNote", "jobBrowseClose"):
        assert f'id: "{dom_id}"' in src, f"문서 탐색 React 요소 누락: {dom_id}"
        assert f'id="{dom_id}"' not in html, f"{dom_id} 정적 골격이 React producer와 중복됩니다."
    assert 'id="scr-browse"' not in html and "scr-documents" not in html
    assert 'browse("browse_tab"' in src and 'browse("browse_query"' in src
    assert '"data-browse-pick": row.name' in src
    for token in ('id: `jobBrowseTab-', 'id: `jobBrowseRow-', 'id: "jobBrowseOpen"'):
        assert token in src, f"탐색 면 안정 id 누락: {token}"
    assert "browseGeneration" in src and "generation !== browseGeneration" in src
    pick = src[src.index("async pickBrowse("):src.index("newWorkFromData,", src.index("async pickBrowse("))]
    assert pick.index("browseTail.then") < pick.index("selectJob(name)") < pick.index('modal.close("jobBrowseSheet")')
    browse_component = src[src.index("export function JobBrowseDialog"):src.index("export function JobReadEffects")]
    assert browse_component.count('"data-busy-lock": true') >= 3
    browse_row = src[src.index("function BrowseRow("):src.index("export function JobBrowseDialog")]
    assert '"data-busy-lock": true' in browse_row
    for banned in (".filter(", "toLowerCase", ".includes("):
        assert banned not in browse_component, f"탐색 렌더가 자체 필터를 합니다: {banned!r}"


def test_job_candidate_ranking_surface_contract():
    """슬라이스 2 정적 계약 — 순위 카드·별 토글·추천 표지·「외 N건」 고지 배선.

    판정·순위는 Python 소유라 JS 는 **받은 순서를 그대로** 그린다(정렬 재구현 금지).
    """
    src = R4_JOB_READ.read_text(encoding="utf-8")
    lib = R4_LIBRARY.read_text(encoding="utf-8")
    assert '"data-fav": row.name' in src and '"toggle_favorite"' in src
    assert 'className: "lib-fav", "data-fav": row.name' in lib
    for owner in (src, lib):
        assert owner.count("async function toggleFavorite(") == 1
        assert "favoriteIntent" in owner and "favoriteTail" in owner
        assert "const intended = !(favoriteIntent.get(name) ?? shown)" in owner
        assert "previous.then(async () =>" in owner
    # 최근 사용 문안은 **링1으로 이사했다**(F6): 두 매체가 다른 술어를 쓰므로(§19.4 HWPX
    # 완주 / TXT 복사 1건) 표면이 한 문구로 뭉치면 하필 구별이 중요한 자리에서 이력을
    # 거짓으로 말한다. 여기선 표면이 문구를 **다시 짓지 않는지**만 본다.
    assert "last_run_label" in src, "카드가 Python 이 낸 최근 사용 문안을 쓰지 않습니다."
    assert "마지막 성공 실행" not in src and "마지막 복사" not in src, (
        "표면이 최근 사용 문안을 손으로 다시 짓습니다 — 술어가 갈리면 두 문구가 어긋난다."
    )
    # 카드 부제의 작업 방식 텍스트는 구획이 퇴화해도 남는다(§19.3 마지막 문장).
    assert "cand-mode" in src and "mode_label" in src, (
        "카드 부제에 작업 방식 텍스트가 없습니다 — 색만으로 방식을 구별하지 않는다."
    )
    # 구획 여부·순서 판정은 Python 이고 표면은 머리글만 그린다(§19.3).
    assert "candidates.sections" in src and "sections.length > 1" in src, (
        "방식 구획이 Python 판정(sections)을 소비하지 않습니다."
    )
    assert "candidates.more" in src, "순위 밖 후보 수(외 N건) 고지가 없습니다 — 조용한 절단 금지."
    # 확인 필요 목록은 탐색 면으로 이사했다 — 후보 줄엔 수치 + 출구만 남는다(슬라이스 3).
    assert "candidates.needs_count" in src and '"data-browse-open": true' in src, (
        "확인 필요 수치·문서 탐색 출구가 후보 줄에 없습니다."
    )
    assert "cand-sug" in src, "추천 표지가 없습니다(§18.3 개정)."
    # JS 가 순위를 재계산하지 않는다(RC-23 동형 — 이중 진실 금지).
    for banned in ("favorited_at <", "sort(", "localeCompare"):
        assert banned not in src[src.index("export function JobCandidates"):src.index("function BrowseRow")], (
            f"후보 렌더가 자체 정렬을 합니다: {banned!r}"
        )
    css = "".join(WEB_CSS.split())
    # 추천은 활성과 시각으로 구별된다 — 점선(아직 고른 것 아님) vs 실선 강조(활성).
    assert ".job-cand-card.suggested:not(.active){border-style:dashed" in css
    assert ".job-cand-card.active{border-color:var(--a-primary)" in css


def test_template_media_sunken_surface_is_retired_with_the_screen():
    """H-04 은퇴(F8 §10.17) — 매체 sunken 2면은 tpl 화면 전용 표면이라 화면과 함께 죽었다.

    승계 표면(편집기 「템플릿」 탭 2밴드)은 .grp 문법이고 그 실렌더 계약은 selftest
    editor_lib_manage 프로브가 잰다. 죽은 표면 문법이 CSS·DOM 에 되살아나면 부활 통로다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    css = "".join(WEB_CSS.split())
    for dead in ('class="tpl-medium"', 'id="tplHwpxGroups"', 'id="tplTxtGroups"'):
        assert dead not in html, f"죽은 tpl 표면 DOM 이 되살아났습니다: {dead}"
    for dead in (".tpl-medium{", ".tpl-band{", ".tpl-libbar{", ".tpl-catalogs{"):
        assert dead not in css, f"죽은 tpl 표면 CSS 가 되살아났습니다: {dead}"
    # 승계 표면의 ⋮ 노출 배선 — .job-more 는 기본 hidden 이라 행 계열마다 호버·포커스 노출
    # 규칙이 있어야 실물이 보인다(101 눈검증 회수분: 프로브의 프로그램적 click 은 hidden 을
    # 통과해 은닉을 못 잡는다 — F2 PR-B 1R 「실물이 없던 자리」와 같은 부류).
    assert ".libselrow:hover.job-more,.libselrow:focus-within.job-more{visibility:visible}" in css, (
        "편집기 「템플릿」 탭 행 ⋮ 의 호버 노출 규칙이 없습니다 — 관리 동사가 영영 은닉됩니다."
    )


def test_card_families_share_hover_and_keep_persistent_state_separate():
    """H-14: 카드류 hover는 틴트뿐이고 막대는 선택·오류에만 남는다.

    구 홈 txt 목록(.tlist .titem)은 화면과 함께 사망했고(재작성 F2), 라이브러리 행(.lib-row)이
    같은 어휘의 새 소비자다 — 같은 규칙을 쓰는지 여기서 함께 본다.
    """
    css = "".join(WEB_CSS.split())
    assert ".jcard:hover,.tplcard:hover{background:var(--n-hover)}" in css
    assert ".lib-row:hover{background:var(--n-hover)}" in css
    assert (
        '.jcard[aria-current="true"],.tplcard[aria-current="true"]{background:var(--a-sel);'
        "border-left-color:var(--a-primary)}"
    ) in css
    assert ".lib-row.on{background:var(--a-sel);border-left-color:var(--a-primary)}" in css
    assert ".jcard.corrupt{border-left-color:var(--a-danger)}" in css
    for selector in (".jcard:hover", ".lib-row:hover", ".tplcard:hover"):
        body = re.search(re.escape(selector) + r"(?:,[^{]+)?\{([^}]*)\}", css)
        assert body and "border" not in body.group(1), f"hover가 상태 보더를 사용합니다: {selector}"


def test_card_families_keep_keyboard_focus_outline():
    css = "".join(WEB_CSS.split())
    assert (
        ".jcard:focus-visible,.tplcard:focus-visible{"
        "outline:2pxsolidvar(--a-primary);outline-offset:2px}"
    ) in css
    # 라이브러리 행은 버튼 2개(선택·즐겨찾기)라 아웃라인이 **버튼**에 붙는다 — 행 껍데기에
    # 붙이면 실제 포커스 대상과 표지가 어긋난다.
    assert (
        ".lib-row-main:focus-visible,.lib-fav:focus-visible{"
        "outline:2pxsolidvar(--a-primary);outline-offset:-2px}"
    ) in css


def test_disabled_primary_uses_light_neutral_surface_globally():
    """H-11: 비활성 primary는 무거운 솔리드 색 대신 전역 중립 상태 한 벌을 쓴다."""
    css = "".join(WEB_CSS.split())
    assert (
        ".btn.primary:disabled{background:var(--n-track);color:var(--a-muted);"
        "border-color:var(--a-border);opacity:1}"
    ) in css
    assert ".btn.primary:disabled{background:var(--a-muted)" not in css


def test_theme_helper_loaded_and_toggle_present():
    """다크모드 토글 배선 정적 가드 — theme.js 로드 + 레일 토글 버튼(접근 이름·툴팁).

    토글이 사라지면 사용자는 OS 자동에만 묶여 앱 내 override 를 잃는다. 버튼은 navbtn 이
    아니어야 한다(라우터가 .navbtn 전부에 go(data-scr) 를 배선 → data-scr 없는 토글이 navbtn
    이면 클릭이 화면을 지운다) — id 존재 + a11y 속성만 정적으로 단언한다.
    """
    index = WEB_INDEX.read_text(encoding="utf-8")
    assert reaches_product_graph("theme.js"), (
        "theme.js 가 제품 그래프에 닿지 않습니다(다크모드 토글)."
    )
    m = re.search(r'<button\b[^>]*\bid="themeToggle"[^>]*>', index)
    assert m, "테마 토글 버튼(id=themeToggle)이 없습니다."
    tag = m.group(0)
    assert "navbtn" not in tag, "themeToggle 은 navbtn 이 아니어야 합니다 — 라우터가 클릭 시 화면을 지웁니다."
    for attr in ("aria-label", "title"):
        am = re.search(attr + r'="([^"]*)"', tag)
        assert am and am.group(1).strip(), f"themeToggle 에 비어있지 않은 {attr} 이 필요합니다."


def test_theme_persistence_is_origin_independent():
    """테마 영속이 오리진(포트)에 결합된 localStorage 로 회귀하지 않도록 정적 가드(#74).

    #74 이전엔 head 동기 인라인이 ``localStorage['hwpxfiller.theme']`` 를 되읽어 FOUC 를 막았으나,
    localStorage 는 오리진(host:port) 스코프라 pywebview 내부 포트가 바뀌면 테마가 조용히
    리셋됐다. 영속을 오리진 비의존 Python 설정(app.py set_theme → settings.json)으로 옮기고
    (private_mode 기본 복원) FOUC 는 부팅 시 loaded 핸들러 주입으로 은닉한다. 그러므로:
      - index.html 은 테마용 localStorage 판독을 **가져선 안 된다**(원인 결합 재도입 금지).
      - theme.js 는 브리지(Bridge.setTheme)로 영속해야 하고 localStorage 를 **일절 쓰지 않는다**.
    브라우저 단독 프리뷰의 새로고침 간 미영속은 의도된 트레이드오프다(#75 리뷰4 #4/#7): 프리뷰를
    영속하려면 오리진 결합 localStorage 판독이 되살아나므로, 개발 전용 프리뷰 편의보다 불변식을 택한다.
    """
    index = WEB_INDEX.read_text(encoding="utf-8")
    assert not re.search(r'localStorage[^;]*hwpxfiller\.theme', index), (
        "index.html 이 테마를 localStorage 로 다룬다 — 오리진 결합 영속 회귀(#74). "
        "영속은 브리지(set_theme)/Python 설정으로만."
    )
    theme_js = (WEB_JS_DIR / "theme.js").read_text(encoding="utf-8")
    assert "bridge.setTheme" in theme_js, (
        "theme.js 가 브리지로 영속하지 않습니다(Bridge.setTheme 부재) — #74 영속 경로."
    )
    assert not re.search(r"localStorage\s*\.", theme_js), (
        "theme.js 가 localStorage 를 실사용 — 오리진 비의존 영속(#74)과 상충. 프리뷰 미영속은 의도(#75 리뷰4)."
    )


def test_boot_hides_window_until_theme_applied():
    """FOUC 은닉의 구조 가드(#74) — 창은 숨김 생성, 테마 주입이 show **앞**이어야 한다.

    옛 가드(head 인라인이 tokens.css 링크보다 앞)는 pre-paint 적용을 정적 순서로 보증했다.
    localStorage 이관으로 인라인이 사라진 뒤의 등가물: ``hidden=True`` 로 창을 만들고
    ``_apply_theme_then_show`` 안에서 Theme.apply 주입이 ``_show_once()`` 보다 먼저여야
    라이트 첫 페인트가 화면 밖에서 소진된다. 런타임 게이트(theme_persist)는 부팅 한참 뒤
    스냅샷이라 '주입이 show 앞이었나'를 구분 못 한다 — 순서는 여기서 정적으로 가드한다.
    """
    app_py = REPO_ROOT / "src" / "hwpxfiller" / "webapp" / "app.py"
    src = app_py.read_text(encoding="utf-8")
    # create_window 호출부 슬라이스 — 다음 문장(frontend._window 배선)까지가 호출 인자 범위.
    create = src[src.index("webview.create_window("): src.index("frontend._window")]
    assert "hidden=True" in create, (
        "create_window 에 hidden=True 가 없습니다 — 저장 테마 주입 전 라이트 첫 페인트가 "
        "화면에 노출됩니다(FOUC 회귀, #74)."
    )
    body_start = src.index("def _apply_theme_then_show")
    body = src[body_start: src.index("window.events.loaded")]
    apply_at = body.find("Theme.apply")
    show_at = body.find("_show_once()")
    assert apply_at != -1 and show_at != -1 and apply_at < show_at, (
        "_apply_theme_then_show 에서 Theme.apply 주입이 _show_once() 보다 앞이어야 합니다 — "
        "뒤집히면 창이 라이트로 뜬 뒤 다크로 스냅(FOUC, #74)."
    )


def test_native_close_and_editor_escape_affordances_are_wired():
    """#218: X 가드·신규 취소·편집기 이탈 경로가 DOM/JS에서 함께 살아 있어야 한다.

    편집기가 몰입 표면이 되며(재작성 F7) 「편집 계속」 재진입구는 사망했다 — 나가는 길이
    back 하나이고 그때 처분이 확정되므로 「처분 미확정으로 나온 세션」 자체가 없다.
    그 자리를 back·이탈 가드가 대신 지킨다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    app_py = (REPO_ROOT / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    app_js = (WEB_JS_DIR / "app.js").read_text(encoding="utf-8")
    editor_js = R4_EDITOR.read_text(encoding="utf-8")
    job_js = react_job_run_source()

    assert "window.events.closing += frontend._handle_window_closing" in app_py
    # N-07 — 셸은 `window.pywebview.api` 를 직접 뒤지지 않고 브리지 표면을 쓴다. 배선의
    # 존재를 세는 계약은 그대로고, 바뀐 것은 그 배선이 지나는 자리다. 호스트 메서드 이름을
    # 아는 파일이 하나뿐이라는 사실도 여기서 함께 센다 — 안 세면 셸이 다시 직접 알게 된다.
    assert "AppCloseGuard" in app_js and "confirmWindowClose" in app_js
    bridge_js = (WEB_JS_DIR / "bridge.js").read_text(encoding="utf-8")
    assert "confirm_window_close" in bridge_js and "cancel_window_close" in bridge_js, (
        "닫기 처분 통보가 브리지 표면에서 사라졌습니다."
    )
    assert "window.pywebview.api" not in app_js, (
        "앱 셸이 다시 호스트 API 를 직접 조회합니다 — private backend 는 bridge.js 하나입니다."
    )
    assert 'id: "editorBack"' in editor_js, "편집기 back 어포던스의 생산자가 없습니다."
    assert '"data-act": "cancel-new"' in editor_js
    assert 'sendEdit("discard_session", {})' in editor_js   # 체인 경유(5R P2)
    assert "async function leaveTo(" in editor_js, (
        "편집기 이탈의 단일 출구(leaveTo)가 없습니다 — 출구가 여럿이면 처분 가드가 새어 나갑니다."
    )
    # **section 밖의 편집도 잃을 것이다**(2R P1): 이름·자동등록 이름은 어느 section 에도 없어
    # 탭 표지엔 안 뜬다 — 그것만 보면 이름을 고치고 나가는 사람에게 아무것도 묻지 않고
    # 버린다. 몰입 표면엔 그 세션으로 되돌아올 길이 없어 조용한 파기가 된다.
    # (세션 dirty 단일 출처 계약은 아래 `test_edit_entries_carry_their_context` 가 센다.)
    # **대기 중 입력이 판정을 추월하지 않는다**(4R P2): blur 로 발화하는 `change` 는 아무도
    # 기다리지 않는 발신이라, 이름을 고치고 곧바로 back 을 누르면 가드가 그 발신보다 먼저
    # 판정해 방금 친 편집이 아무 확인 없이 좌초한다. 순서는 공용 체인(intent.js)이 세우고
    # 이탈·탭 이동은 정산 뒤에 판정한다 — job.js 존 체인과 같은 기제다(재발명 금지).
    # **편집기의 브리지 왕복은 한 줄에 선다**(5R P2): `change` 만 체인에 세우면 클릭 변이
    # (헤더 토글·확정·되돌리기…)가 밖에 남아, 누르자마자 back 을 누른 사용자의 편집이
    # 판정보다 늦게 도착한다. 체인 밖 예외는 둘뿐 — 첫 스냅샷 당김과 정산 **뒤** 컨트롤러
    # 직접 질의(자기가 기다리는 줄에 서면 안 된다).
    assert editor_js.count("chained(EDIT_CHAIN") == 2, (
        "편집기 왕복이 체인을 우회합니다 — 체인에 서는 자리는 `sendEdit` 와 "
        "`flushPendingEdits` 둘뿐입니다(발신과 정산)."
    )
    assert "chain.chained(EDIT_CHAIN" in editor_js, (
        "편집기 입력 변이가 체인에 서지 않습니다 — 도착 순서가 보장되지 않습니다."
    )
    # **확인 왕복도 정산 뒤에 연다**(§2.17 2R P2): 버리기가 blur 전에 눌릴 수 있게 된 뒤로
    # (1R), 정산 없이 모달을 열면 큐에 든 `set_*` 이 모달 뒤에 도착해 `#editor-foot` 을 갈아
    # 끼우고 저장해 둔 트리거가 분리된다 — 취소가 화면 루트로 떨어진다. 정산은 새 기제를
    # 만들지 않고 goto·leave 와 **같은** `flushPendingEdits` 를 쓴다.
    discard = editor_js[editor_js.index("async function discardPatch("):]
    discard = discard[:discard.index('sendEdit("discard_patch"')]
    assert "await flushPendingEdits()" in discard, (
        "버리기가 대기 편집을 정산하지 않고 확인을 엽니다 — 큐의 발신이 모달 뒤에 도착해"
        " 판정이 아직 도착하지 않은 편집 위에서 납니다(2R P2)."
    )
    assert discard.index("await flushPendingEdits()") < discard.index("modal.confirm"), (
        "정산이 확인보다 **뒤에** 섭니다 — 순서가 뒤집히면 정산의 존재가 무의미합니다."
    )
    # R4-02 — 트리거 재획득 요구는 **원인이 사라져** 승계하지 않는다: 정산이 부르는 것은
    # `innerHTML` 재구성이 아니라 React 재렌더이고 같은 버튼 노드가 그대로 산다(분리 없음).
    # 남는 계약은 「확인이 그 트리거로 돌아간다」 하나이고 그것은 그대로 잰다.
    assert "returnFocus: trigger" in discard, (
        "확인이 누른 트리거로 돌아가지 않습니다 — 취소 착지가 화면 루트로 떨어집니다."
    )
    assert "controller.discardPatch(event.currentTarget)" in editor_js, (
        "버리기 버튼이 자기 트리거를 넘기지 않습니다."
    )
    # 복귀는 **규칙을 다시 읽은 뒤** 목적 화면을 노출한다(8R P1 근본 조치). 5R 은 이 순서를
    # 미리보기 복귀에만 세웠고, 그래서 데이터·결과 복귀는 옛 규칙을 든 화면을 내보인 채
    # 「만들기」를 열어 뒀다 — 순서는 **모든** 복귀가 지나는 착지 절차 한 자리에 산다.
    land = _function_body(editor_js, "async function landOn(")
    assert land.index("await deps.navigation.refresh(") < land.index("navigation.go("), (
        "착지가 재적재를 기다리지 않고 화면을 노출합니다 — 편집 전 규칙으로 실행됩니다(8R P1)."
    )
    assert "refreshed: true" in land, (
        "착지가 전환에 기(既)대기를 알리지 않습니다 — 왕복이 두 벌이 되고 늦은 쪽이 면을 흔듭니다."
    )
    # 편집기를 나가는 길은 **모두** 그 절차를 지난다 — Nav.go 직행이 하나라도 남으면
    # 그 경로만 재적재를 건너뛰는 비대칭이 다시 생긴다(F7 이 네 라운드에 걸쳐 겪은 자리).
    assert editor_js.count("navigation.go(") == 1, (
        "편집기에 Nav.go 직행 경로가 남았습니다 — 착지 절차(landOn) 하나만 전환해야 합니다."
    )
    # **초점도 되돌린다**(9R P2) — 화면만 바꾸면 초점이 방금 숨겨진 편집기 back 버튼에 남아
    # 키보드 사용자가 보이는 초점 없이 착지한다. 되돌릴 자리를 아는 곳은 진입 seam 하나이고
    # (복귀처 넷에 focus_target 을 심으면 새 진입처가 조용히 빠진다), 되돌림 **규칙**은
    # 모달이 이미 가진 것을 쓴다(분리·비활성 요소 판정을 두 번 쓰지 않는다).
    assert "editorEntry.current().restoreEntryFocus()" in land, (
        "이탈이 초점을 되돌리지 않습니다 — 숨은 요소에 초점이 남습니다(9R P2)."
    )
    entry_js = R4_EDITOR_ENTRY.read_text(encoding="utf-8")
    assert entry_js.count("rememberEntryFocus()") == 4, (
        "진입 seam 이 띄운 자리를 기억하지 않습니다 — 정의 1 + 세 진입"
        "(newDraft·newDraftFromData·openGuarded). 진입이 늘 때 이 수도 함께 는다."
    )
    assert "modal.restoreFocus(" in entry_js, (
        "초점 되돌림 규칙이 두 벌입니다 — 모달의 restoreFocus 를 재사용해야 합니다."
    )
    modal_js = (WEB_JS_DIR / "modal.js").read_text(encoding="utf-8")
    assert re.search(r"export const Modal = \{[^}]*\brestoreFocus\b", modal_js), (
        "Modal.restoreFocus 가 내보내지지 않았습니다 — 이탈이 그 규칙을 쓸 수 없습니다."
    )
    for guard in ("async function leaveTo(", "async function gotoSection("):
        body = editor_js[editor_js.index(guard):]
        body = body[:body.index("\n  }") + 4]
        assert "await flushPendingEdits()" in body, (
            f"{guard} 가 대기 중 입력을 정산하지 않고 판정합니다(4R P2)."
        )
    # 탭 가드의 「버리고 이동」은 **모달이 말한 자리만** 되돌린다(2R P2).
    assert 'discard_patch", { section: result.section }' in editor_js, (
        "탭 가드의 되돌리기가 세션 전체를 겨눕니다 — 확인 문안보다 넓은 파기입니다."
    )
    assert "jobEditResume" not in job_js and "jobEditResume" not in html, (
        "구 편집 모드 재진입구가 부활했습니다(F7 판정 N — 삭제는 의무를 상속한다)."
    )


def test_unhandledrejection_backstop_present_in_shell():
    """비동기 실패 최종 백스톱 — 셸이 unhandledrejection 을 alert 로 재진술해야 한다.

    무대기·무catch 브리지 호출의 rejection 이 조용한 무반응으로 증발하는 결함류가
    파일 단위 봉합(F8·F9→#45 profile_*→PR #46 P2 onClick)으로 반복 재발했다 — 사이트별
    규율 대신 셸 전역 안전망으로 구조 차단한다. 지역 가드가 잡은 실패는 여기 오지
    않으므로 이 백스톱은 "가드를 잊은 곳" 전용이다. preventDefault 없이 alert 만 하면
    콘솔 소음이 남고, alert 없이 preventDefault 만 하면 완전 침묵(최악)이라 둘 다 단언한다.

    (diff 셸의 짝 백스톱은 hwpx-diff 저장소가 같은 단언으로 지킨다 — 분리 전에는 이
    루프가 두 셸을 함께 돌았다.)
    """
    # R3-02(#411) — 부착/해제 수명주기는 React ShellHost 가 소유하고, app.js 는 핸들러
    # 본문(재진술 집행)을 서술(attachments)로 캡처한다. 백스톱의 실물은 그 서술 행이다.
    app_js = WEB_JS_DIR / "app.js"
    src = app_js.read_text(encoding="utf-8")
    m = re.search(r'type: "unhandledrejection",[\s\S]*?\},\n  \}\);', src)
    assert m, f"{app_js} 에 unhandledrejection 백스톱 서술이 없습니다 — 조용한 무반응 결함류 재개방."
    block = m.group(0)
    assert "window.alert" in block, f"{app_js} 백스톱이 alert 로 재진술하지 않습니다."
    assert "preventDefault" in block, f"{app_js} 백스톱이 rejection 을 handled 처리하지 않습니다."
    # 서술은 부착자가 있어야 실물이 된다 — ShellHost 의 부착 실물(attachShell)이 전수를 건다.
    shell_host_ts = (WEB_JS_DIR.parent / "src" / "shell" / "host.ts").read_text(encoding="utf-8")
    assert "attachment.target.addEventListener(attachment.type, attachment.handler)" in shell_host_ts, (
        "ShellHost 가 리스너 서술을 부착하지 않습니다 — 백스톱 서술이 죽은 데이터가 됩니다."
    )


def test_editor_is_an_immersive_screen_with_one_exit():
    """편집기 = 몰입 표면(재작성 F7 PR-A, 지도 §10.13 사용자 확정 2행).

    편집 컨테이너 3종(editor-steps/-body/-foot)은 자기 화면(#scr-editor)에 살고, 「작업」
    화면의 편집 호스트(#jobEditHost)와 두 모드 배선은 **사망**했다(재유입 가드 — 삭제는
    의무를 상속한다). 요지는 미감이 아니라 가드다: 편집이 「문서 만들기」 안의 한 모드면
    상단 탭·화면 안 컨트롤이 전부 처분 미확정 이탈구가 되고 가드의 완전성이 표면 수에
    비례한다. 출구가 하나여야 patch 3택이 한 곳에서 끝난다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    product = R4_PRODUCT_SCREENS.read_text(encoding="utf-8")
    assert 'screenProps("editor", active)' in product, "ProductScreens 편집기 화면 root가 사라졌습니다."
    assert 'id="scr-editor"' not in html, "편집기 root가 정적 셸과 React에 이중 생산됩니다."
    #: R4-02 — 화면 안쪽 전부가 React 생산이라 컨테이너 3종·머리 컨트롤의 거처는 producer 다.
    #: 정적 재도입은 두 생산자가 되므로 **부재**도 함께 잰다(portal 이 mount 전에 거절한다).
    editor_src = R4_EDITOR.read_text(encoding="utf-8")
    for cid in ("editorBack", "editorName", "editorSaveState", "editorContext",
                "editor-steps", "editor-body", "editor-foot"):
        assert f'id: "{cid}"' in editor_src, f"{cid} 를 React 편집기가 생산하지 않습니다."
        assert f'id="{cid}"' not in html, f"{cid} 정적 골격이 React producer 와 중복됩니다."
    # 구 거처 재유입 가드 — 편집 호스트·두 모드 출구는 승계처가 섰으므로 되살아나면 안 된다.
    assert 'id="jobEditHost"' not in html, "구 편집 호스트가 부활했습니다(F7 판정 N)."
    assert 'id="jobEditExit"' not in html and 'id="jobEditExitNote"' not in html, (
        "구 편집 모드 출구·복귀 고지가 부활했습니다 — 그 소임은 patch 처분이 승계했습니다."
    )
    # 셸을 덮는다 — nav 은닉은 CSS 가, 편집 중 이탈은 Nav 위임이 진다. R3-02(#411)부터
    # 몰입 목록의 정본은 셸 상태기계(nav.ts)이고 app.js 는 그 목록으로 body 클래스를 집행한다.
    executor_ts = R4_PRODUCT_EXECUTOR.read_text(encoding="utf-8")
    bootstrap = SOURCE_BOOTSTRAP.read_text(encoding="utf-8")
    nav_ts = (WEB_JS_DIR.parent / "src" / "shell" / "nav.ts").read_text(encoding="utf-8")
    assert '{ id: "editor", cls: "editor-open" }' in nav_ts and "body.editor-open .nav" in WEB_CSS, (
        "편집기가 상단 2탭을 덮지 않습니다 — 화면 전환구가 살아 있으면 처분 미확정 이탈구다."
    )
    assert "IMMERSIVE_SURFACES.forEach" in executor_ts
    assert 'classList.toggle("editor-open", id === surface.id)' in executor_ts
    assert 'classList.toggle("workbench-open", id === surface.id)' in executor_ts
    assert "지원하지 않는 몰입 화면 표지입니다" in executor_ts, (
        "ProductScreens executor가 몰입 목록으로 셸 표지를 내리지 않습니다 — 판정만 있고 은닉이 죽습니다."
    )
    # 이탈 위임은 **몰입 표면 목록**으로 일반화됐다(F6 — 작업대 합류). 특례를 화면마다
    # 늘리면 가드의 완전성이 표면 수에 비례한다(이 표면이 존재하는 바로 그 이유). 그래서
    # 목록 판정(상태기계)과 위임 집행(adapter 의 leaveTo 호출)을 함께 센다.
    assert "IMMERSIVE_SURFACES.some" in nav_ts and "delegateLeave" in nav_ts, (
        "상태기계가 몰입 표면의 이탈 가드를 지나지 않습니다 — 프로그램적 이동이 처분을 건너뜁니다."
    )
    assert 'lifecycle.register("editor"' in bootstrap and 'lifecycle.register("workbench"' in bootstrap, (
        "합성 루트가 몰입 화면 lifecycle owner를 등록하지 않습니다 — 가드가 판정만 남습니다."
    )
    for surface in ('{ id: "editor", cls: "editor-open" }', '{ id: "workbench", cls: "workbench-open" }'):
        assert surface in nav_ts, f"몰입 표면 목록에 {surface} 가 없습니다."
    # 진입 흐름은 EditorEntry 단일 정의(land/newDraft/openGuarded — 축자 복붙=드리프트 표면).
    entry_src = R4_EDITOR_ENTRY.read_text(encoding="utf-8")
    for fn in ("function land", "function newDraft", "function openGuarded"):
        assert fn in entry_src, f"editor_entry.js 의 단일 정의({fn})가 사라졌습니다."
    assert 'navigate("editor"' in entry_src, "편집 진입이 편집기 화면으로 착지하지 않습니다."
    for path, needle in (
        (R4_LIBRARY, "editorEntry.current().newDraft"),
        (R4_LIBRARY, "editorEntry.current().openGuarded"),
        # (template.js 의 EditorEntry.land 소비는 화면 사망(F8)으로 은퇴 — 편집기 안 선택은
        #  이미 편집기 화면이라 착지 seam 이 필요 없다.)
    ):
        src = path.read_text(encoding="utf-8")
        assert needle in src, f"{path} 가 진입 단일 출처({needle})를 쓰지 않습니다."
    job_js = react_job_run_source()
    # 실행 표면 몫 — 전역이 아니라 주입 port 로 같은 단일 출처를 부른다.
    assert "deps.ports.editorEntry.current().openGuarded(" in job_js, (
        "실행 표면이 편집 진입 단일 출처를 쓰지 않습니다."
    )
    # **맨손 새 작업**은 여전히 라이브러리 소관이다(F8 승계). 금지의 근거는 "진입점이 둘이면
    # 중복"이었는데, U2 §2.4(#349)의 「이 데이터로 새 작업」은 그 중복이 아니다: 마운트된
    # 데이터를 들고 시작하는 진입이라 데이터가 없는 라이브러리에서는 **성립하지 않는다**.
    # 그래서 금지는 사라지지 않고 **좁아진다** — 데이터 없는 `newDraft(` 만 계속 막는다.
    assert "editorEntry.current().newDraft(" not in job_js and "editorEntry.current().newDraft(" not in R4_JOB_READ.read_text(encoding="utf-8"), (
        "「문서 만들기」에 맨손 새 작업 진입이 되살아났습니다 — 그 승계처는 라이브러리 "
        "`＋ 새 작업`이고, 여기서 여는 것은 데이터를 든 `newDraftFromData` 뿐입니다."
    )
    assert "showEditMode" not in job_js and "exitEditToRun" not in job_js, (
        "job.js 두 모드 배선이 되살아났습니다 — 편집은 자기 화면으로 나갔습니다(F7)."
    )
    editor_js = R4_EDITOR.read_text(encoding="utf-8")
    product_src = R4_PRODUCT_SCREENS.read_text(encoding="utf-8")
    assert 'screenProps("editor", active)' in product_src and 'createPortal(screens, targets.stage' in product_src, (
        "React 편집기 표면이 ProductScreens 단일 stage portal에 합성되지 않았습니다."
    )


def test_editor_folder_import_is_wired_without_session_confirm():
    """「폴더에서 가져오기…」(#339 · U2 §2.16 narrow) 배선 — 4자리가 한 계약으로 산다.

    ①행동 줄 버튼(data-act="import-folder") ②직접 브리지 메서드(importTemplatesFolder →
    import_templates_folder — action registry 밖이라 payload 검증은 메서드 본문 소유)
    ③핸들러는 재진술 확인(Modal.confirm) 뒤에만 확정 실행을 부른다 ④**채택하지 않으므로**
    새-세션 확인(confirmNewSessionIfUnsaved)이 이 경로에 서면 안 된다 — 세션 무변경 동사에
    세션 파괴 확인이 붙으면 확인이 거짓말이 된다.
    """
    editor = R4_EDITOR.read_text(encoding="utf-8")
    bridge = (WEB_JS_DIR / "bridge.js").read_text(encoding="utf-8")
    app_py = (REPO_ROOT / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(
        encoding="utf-8"
    )
    assert '"data-act": "import-folder"' in editor, "폴더 가져오기 버튼이 행동 줄에 없습니다."
    start = editor.index("async function importFolder(")
    block = _function_body(editor, "async function importFolder(")
    assert "import_templates_folder" in block, "핸들러가 직접 브리지 메서드를 부르지 않습니다."
    # 호출 형태로 잰다 — 주석의 언급(왜 안 거는지의 선언)은 결함이 아니다.
    assert "confirmNewSessionIfUnsaved()" not in block, (
        "채택 없는 일괄 등록에 새-세션 확인이 붙었습니다 — 세션 무변경 동사입니다(#339)."
    )
    assert block.index("modal.confirm") < block.index(
        '"import_templates_folder", scanned.folder, true, scanned.files'), (
        "확정 실행이 재진술 확인보다 앞에 있거나 재진술된 후보 목록(r.files)을 나르지"
        " 않습니다 — 확정 전에는 홈에 아무것도 쓰지 않고, 실행은 확인한 목록에 결속된다."
    )
    assert "importTemplatesFolder(folder, confirm, files)" in bridge, (
        "브리지에 importTemplatesFolder(확정 목록 나름)가 없습니다."
    )
    assert "def import_templates_folder(" in app_py, (
        "백엔드 직접 메서드 import_templates_folder 가 없습니다."
    )
    # 재진입 가드(PR #355 2R) — in-flight 플래그가 흐름 **전체**(스캔→확정→실행)를 덮고,
    # 취소·실패 출구 포함 어디로 나가든 풀린다(finally). 잠긴 채 남으면 버튼이 영구 사망.
    # 판정 정본은 Python(tpl import_folder 비차단 잠금)이고 이 플래그는 어포던스 잠금이다.
    assert "if (view.folderImportInFlight) return;" in block, (
        "폴더 가져오기에 in-flight 가드가 없습니다 — 느린 드라이브에서 재클릭이 두 번째"
        " 스캔/확정 모달/배치를 시작합니다(PR #355 2R)."
    )
    assert block.index("folderImportInFlight: true") < block.index(
        'invoke("import_templates_folder"'), (
        "가드가 첫 브리지 발신보다 늦게 섭니다 — 스캔·확정 모달이 가드 밖입니다."
    )
    assert "finally" in block and "folderImportInFlight: false" in block, (
        "in-flight 해제가 finally 에 없습니다 — 취소·실패 출구에서 버튼이 영구히 잠깁니다."
    )
    tpl_py = (REPO_ROOT / "src" / "hwpxfiller" / "webapp"
              / "screen_template.py").read_text(encoding="utf-8")
    assert "_folder_import_lock.acquire(blocking=False)" in tpl_py, (
        "배치 중복 실행의 정본 거절(tpl 비차단 잠금)이 없습니다 — JS 플래그만 남으면"
        " 어포던스가 뚫릴 때 두 배치가 교차합니다(거동은 test_webapp_template 이 잰다)."
    )
    # 빈 상태(이 기능의 주 부트스트래핑 시나리오)는 라이브러리를 채우는 경로를 **둘 다**
    # 광고한다(U2 §2.16 :946-949 — 3R P2): 두 밴드의 빈 힌트 모두 폴더 경로를 말해야 한다.
    empty_hints = [
        line for line in editor.splitlines()
        if "없습니다. '" in line and "추가하세요" in line
    ]
    assert len(empty_hints) == 2 and all("'폴더에서 가져오기…'" in h for h in empty_hints), (
        "빈 상태 힌트가 폴더 일괄 경로를 광고하지 않습니다 — 행동 줄 버튼만 있고 빈"
        f" 라이브러리의 첫 안내가 단건 경로만 말합니다: {empty_hints!r}"
    )


def test_edit_entries_carry_their_context():
    """편집 진입은 **문맥과 함께** 일어난다(계약 §5.1 · 지도 §10.13 판정 K).

    편집기는 스스로 열리지 않는다 — 늘 다른 표면의 문제가 사람을 보낸다. 사유·증거·복귀처를
    안 들고 오면 사용자는 "내가 왜 여기 왔더라"를 편집기에서 다시 재구성해야 하고 돌아갈
    자리도 잃는다. 그래서 **보낸 표면**이 자기가 본 것을 싣는다(편집기가 되계산하면 배너와
    사용자가 방금 본 화면이 갈린다).
    """
    job = react_job_run_source()
    lib = R4_LIBRARY.read_text(encoding="utf-8")
    bridge = (WEB_JS_DIR / "bridge.js").read_text(encoding="utf-8")
    entry = R4_EDITOR_ENTRY.read_text(encoding="utf-8")
    assert "openJobInEditor(name, context)" in bridge, (
        "브리지가 진입 문맥을 나르지 않습니다 — 문맥 없는 편집기는 나갈 곳이 없다."
    )
    # **단일 정의 seam 은 인자까지 단일이어야 한다**(1R P1 의 영구 가드): 호출자가 문맥을
    # 실어도 공용 seam 이 인자를 흘리면 모든 진입이 기본 자발적 진입으로 떨어져 배너·복귀처가
    # 통째로 사라진다. 종전 계약은 "호출자가 무엇을 싣는가"만 보고 "seam 이 흘려보내는가"를
    # 보지 않아 그 드리프트를 통과시켰다.
    assert "async function openGuarded(name: string, context?: Obj)" in entry, (
        "공용 진입 seam 이 문맥 인자를 받지 않습니다 — 호출자가 실은 문맥이 버려집니다."
    )
    assert 'invoke("open_job_in_editor", name, context' in entry, (
        "공용 진입 seam 이 문맥을 백엔드로 흘려보내지 않습니다."
    )
    for reason in ("document_browser_repair", "preview_result", "output_result", "run_failure"):
        assert reason in job, f"「문서 만들기」의 편집 진입이 사유({reason})를 싣지 않습니다."
    assert 'entry_reason: "library"' in lib, "라이브러리 편집 진입이 사유를 싣지 않습니다."
    ports = R4_PORTS.read_text(encoding="utf-8")
    for key in ("openGuarded", "newDraft", "newDraftFromData", "land", "confirmDiscard", "restoreEntryFocus"):
        assert key in ports, f"EditorEntry handoff 6키 중 {key}가 없습니다."
    # F4 가 남긴 빚의 회수 — 파일 이름 규칙 수리는 이제 전용 탭으로 곧장 착지한다.
    assert 'section: "filename"' in job, (
        "결과의 파일 이름 수리가 파일 이름 탭으로 착지하지 않습니다(F7 이 승격한 자리)."
    )
    # **약속한 복귀 상태는 실제로 되돌린다**(1R P2): 「미리보기로 돌아가기」가 보통의
    # 「문서 만들기」로 데려다 놓으면 라벨이 거짓이 된다. 보낸 표면이 세운 `reopen_drawer` 를
    # 복귀가 소비하고, 여는 절차는 그 화면의 seam 하나가 소유한다(열기 규율 두 벌 금지).
    editor = R4_EDITOR.read_text(encoding="utf-8")
    assert "reopen_drawer" in job and "reopen_drawer" in editor, (
        "미리보기 복귀 상태가 세워지기만 하고 소비되지 않습니다 — 라벨이 약속한 자리와"
        " 실제 착지가 다릅니다."
    )
    assert "jobRun.current().openPreview" in editor and "openPreview," in job, (
        "복귀가 미리보기 열기 seam 을 쓰지 않습니다 — 열기 절차가 두 벌이 됩니다."
    )


def test_preview_row_fix_deep_link_is_wired_end_to_end():
    """드로어 행별 「수정」 deep-link(F6 PR-B, §10.14.3) — 한 축(EditContext.target)의 배선.

    계약 §8 표: 미리보기 필드 → ``binding/<fieldId>``, 파일 이름 → ``filename/filenamePattern``,
    복귀 = 같은 previewIndex 와 같은 행. 행 정체성은 target 에서 파생한다 — `return_context`
    에 둘째 축을 만들지 않는다(§10.15.15 판정 B). 착지점은 「변경 저장」 하나이고 「이번
    생성에 적용」 배지는 없다(F7 PR-B 기각과 함께 죽은 상태다).
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    job = react_job_run_source()
    editor = R4_EDITOR.read_text(encoding="utf-8")
    # 발신 쪽 — 행 버튼·파일 이름 버튼·target 두 형태·preview_index 생산.
    assert '"data-act": "preview-fix"' in job, "행별 「수정」 버튼이 없습니다."
    assert 'id: "previewFixFilename"' in job, "파일 이름 「수정」 버튼 생산자가 없습니다."
    assert 'id="previewFixFilename"' not in html, (
        "파일 이름 「수정」 버튼이 정적으로 재도입됐습니다 — 생산자가 둘이 됩니다."
    )
    assert '`binding/${field}`' in job and '"filename/filenamePattern"' in job, (
        "deep-link target 두 형태(계약 §8)가 발신되지 않습니다."
    )
    assert "preview_index: at" in job, "복귀 자리(preview_index)를 싣지 않습니다."
    # `at` 은 Modal.close(→ preview_close 가 pos 를 리셋) **전에** 읽어야 한다 — 순서가
    # 뒤집히면 복귀가 늘 첫 행으로 선다(발신 순서 규약의 이 표면 표본).
    fix_body = job[job.index("async function previewFix"):job.index("function openEditForRepair")]
    assert fix_body.index(".pos") < fix_body.index('deps.modal.close("previewSheet")'), (
        "previewFix 가 확인 면을 닫은 뒤 pos 를 읽습니다 — 리셋된 0 이 실려 갑니다."
    )
    # 수신 쪽 — 편집기 조준(행 data-field·aimAt)과 복귀 소비(preview_index·focusTarget).
    assert "aimAt" in editor and 'tr[data-field="' in editor.replace("${CSS.escape(field)}", '"'), (
        "편집기가 target 행을 겨누지 않습니다(탭 착지만 하고 행을 버립니다)."
    )
    assert "ret.preview_index" in editor and "focusTarget: String(context.target" in editor, (
        "복귀가 같은 자리·같은 행(§10.14.3)을 소비하지 않습니다."
    )
    assert "focusPreviewTarget" in job, "재개 드로어가 복귀 행에 초점을 세우지 않습니다."
    # 배제 유지(판정 E) — 작업대는 편집기로 나가는 deep-link 를 갖지 않는다.
    wb = R4_WORKBENCH.read_text(encoding="utf-8")
    assert "openJobInEditor" not in wb and "EditorEntry" not in wb, (
        "작업대가 편집기 진입을 얻었습니다 — 판정 E(배제 선언)를 먼저 뒤집어야 합니다."
    )


def test_use_in_job_goes_straight_to_the_run_surface():
    """「문서 만들기에서 사용」은 실행 표면에 착지한다(F2 PR-B 의 계약, F7 에서 단순해짐).

    편집기가 자기 화면으로 나가면서 「편집 모드면 되돌린다」는 정산 자체가 불필요해졌다 —
    이 화면이 보이는 동안 편집기는 열려 있지 않다(몰입 표면은 셸을 덮는다). 승계처가 선
    뒤에도 옛 정산을 남겨 두면 죽은 배선이 계약처럼 읽힌다.
    """
    lib = R4_LIBRARY.read_text(encoding="utf-8")
    job = react_job_run_source()
    use = lib[lib.index("async function runPrimary("):lib.index("async function toggleFavorite(")]
    assert 'dispatch("job", "prefer_work", { name })' in use
    assert 'deps.navigation.go("job")' in use, "「문서 만들기에서 사용」이 실행 화면으로 가지 않습니다."
    assert "landRunMode" not in lib and "landRunMode" not in job, (
        "구 실행 모드 착지 seam 이 남아 있습니다 — 두 모드가 사라졌으므로 되돌릴 모드도 없습니다."
    )


def test_group_confirm_copy_states_the_rule_not_a_promised_count():
    """그룹 확인 문안이 **규칙**을 말하고 수치는 관측으로 적는다(#149).

    확인 왕복 사이 다른 표면이 소속을 옮기면 사전 카운트는 실제와 어긋난다 — "N개는 이동합니다"
    는 지킬 수 없는 약속이 되고, 확인한 내용과 실제 집합이 갈라진다(이 저장소의 지배 결함류).
    옮겨지는 집합의 규칙('전부')은 언제나 참이므로 그것을 본문으로 삼고, 수치는 '지금 기준'
    으로 덧붙인다. 실제 건수는 실행 뒤 재진술(``drift_note``)이 진다.
    """
    # 좌 목록 사망(F2 PR-B)으로 그룹 확인 문안의 거처가 라이브러리로 옮겼다 — 판정은 여전히
    # 「문서 만들기」 컨트롤러(교차 화면 dispatch)가 내고, 문안 계약은 표면을 따라간다.
    src = R4_LIBRARY.read_text(encoding="utf-8")
    assert "지금 기준" in src, "그룹 확인 수치가 관측으로 표기되지 않았습니다(#149)."
    assert "해산 시점의 소속 작업 전부" in src, "해산 확인이 이동 집합 규칙을 말하지 않습니다(#149)."
    assert "seen: result.count" in src and "seen: first.count" in src, (
        "확인 때 본 수를 확정 호출에 실어 보내지 않습니다 — 어긋남 판정(Python)이 불가(#149)."
    )
    assert "drift_note" in src, "실제 이동 건수의 어긋남 고지를 소비하지 않습니다(#149)."


def test_editor_overwrite_confirm_echoes_the_text_it_showed():
    """에디터 덮어쓰기 확정이 **본 문안을 되돌려** 준다(#149).

    Python 이 쓰기 잠금 안에서 문안을 다시 만들어 대조하고, 달라졌으면 새 문안으로 다시 묻는다
    — JS 는 무엇을 보여 줬는지만 실어 보낸다(판정은 Python 이 지금, JS 는 문안만).
    """
    src = R4_EDITOR.read_text(encoding="utf-8")
    assert "confirmed_overwrite_text: result.overwrite_text" in src, (
        "확정 호출이 본 문안을 되돌리지 않습니다 — 검증 불가한 확인이 됩니다(#149)."
    )


# (test_draft_has_return_path_to_volatile_session ·
#  test_draft_saved_source_has_fork_escape_hatch · test_draft_live_edit_refreshes_source_bar
#  삭제 — 대상(draft.js 좌 목록·draftsession.js 원문바·휘발 세션)이 화면과 함께 사망,
#  F6 PR-B. TXT 원문 편집의 승계 출구는 편집기 TXT 밴드·검토는 작업대다.)


def test_job_preview_drawer_surface_contract():
    """확인 면(생성 값 미리보기 **시트** — F5 드로어의 U2 §2.13 승격) 정적 계약.

    ①골격은 index.html 정적 DOM 이다(동적 생성은 role/aria 계약의 사각을 만든다 — 구
    `pool_picker.js` K12 교훈) ②열림·자리·「빈 값 있는 건만 보기」는 **Python 소유**라 웹은
    방향·의도 값만 보낸다(판정 M) ③성사 뒤에만 연다 ④승인은 명시 사건 하나이고 생성과
    다른 사건이다(§13-4) ⑤값·이름을 말하는 표면은 이 면 하나다(§2.13 C3 폐색).
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    drawer = R4_JOB_PREVIEW.read_text(encoding="utf-8")
    run_src = R4_JOB_RUN.read_text(encoding="utf-8")
    for element in (
        "previewTitle", "previewPos", "previewPrev", "previewNext",
        "previewBlankOnly", "previewNamePlan",
        "previewRows", "previewEvidence", "previewEvidenceRows", "previewEvidenceNote",
        "previewEvidenceReason",
        "previewFilename", "previewApprove", "previewClose", "previewEdit", "previewEmpty",
    ):
        assert f'id: "{element}"' in drawer, f"확인 면 노드가 없습니다: {element}"
        assert f'id="{element}"' not in html, f"확인 면 노드가 정적으로 재도입됐습니다: {element}"
    for element in ("jobPreviewOpen", "jobReviewFlag"):
        assert f'id: "{element}"' in run_src, f"확인 면 출구가 없습니다: {element}"
    # 시트 승격(§2.13) — 680px 모달이 아니라 전면 시트 골격을 쓴다(렌더러가 올 자리).
    # 껍데기(role·aria·sheet class)는 portal target 이 계속 든다: React 는 children 만 넣고
    # target 의 **속성은 만지지 않으므로**, 그 계약은 여전히 정적 index 소유다.
    assert '<div id="previewSheet" class="modal sheet hidden" role="dialog" aria-modal="true"' in html
    assert 'aria-labelledby="previewTitle"' in html, "확인 면 제목 연결이 끊겼습니다."
    assert "previewModal" not in html, "구 미리보기 모달 id 가 남아 있습니다(§2.13 시트 승격)."
    # 「적용 범위」 축은 없다(U2 §2.3) — runOverrides 기각·사망으로 값이 하나뿐인 축이 됐고,
    # 고를 수 없는 선택지를 암시하는 자리만 남았다. 페이로드 쪽 부재는 test_webapp_job 소관.
    assert 'id="previewScope"' not in html and 'id: "previewScope"' not in drawer, (
        "적용 범위 축이 재유입됐습니다."
    )
    assert '"aria-label": "이전 문서"' in drawer and '"aria-label": "다음 문서"' in drawer, (
        "레코드 이동 버튼에 접근 가능한 이름이 없습니다(‹ › 만으로는 무엇의 이동인지 모른다)."
    )
    # 「빈 값 있는 건만 보기」(§2.13) — 상태 표기는 aria-pressed, 이름 계획 한 줄과 동거.
    assert 'id: "previewBlankOnly", type: "button", "data-busy-lock": true' in drawer

    src = react_job_run_source()
    # 자리는 서수이고 Python 이 소유한다 — 웹이 index 를 되돌려주면 그 사이의 데이터 교체·
    # 표시순서 변경이 남의 행을 고른다(F4 판정 F·F3 판정 A 와 같은 뿌리).
    assert '"preview_move", { delta }' in src, (
        "레코드 이동이 방향이 아니라 좌표를 보냅니다(판정 M)."
    )
    assert "previewMove(-1)" in drawer and "previewMove(1)" in drawer, (
        "‹ › 가 방향 둘을 다 보내지 않습니다."
    )
    assert "preview_pos" not in src and "previewIndex" not in src, (
        "웹이 미리보기 자리를 들고 있습니다 — 상태의 주체는 Python 입니다."
    )
    # 「빈 값 있는 건만 보기」도 상태는 Python 소유 — 의도 값만 보내고 표시는 스냅샷 되읽기
    # (낙관 토글 없음, #215 동류). ‹ › 경계도 Python 이 낸 can_prev/can_next 를 그대로 쓴다.
    assert '"preview_blank_only", { value }' in src, "빈 값 한정 토글 발신이 없습니다."
    assert "previewBlankOnly(!p.blank_only)" in drawer, "토글이 스냅샷 값을 뒤집어 보내지 않습니다."
    assert 'p.blank_only ? "true" : "false"' in drawer, "토글 표시가 스냅샷을 되읽지 않습니다."
    assert "!p.can_prev" in drawer and "!p.can_next" in drawer, (
        "‹ › 가용성이 pos/total 재유도로 남아 있습니다 — 한정 경계와 갈립니다(§2.13)."
    )
    # 이름 계획 한 줄(§2.13) — 인라인 재진술의 이름 목록이 이주한 자리.
    assert 'id: "previewNamePlan"' in drawer, "이름 계획 한 줄 렌더가 없습니다."
    # 성사 뒤에만 연다(§9.3 4행 상속).
    open_fn = src.split("async function openPreview", 1)[1].split("\n  }", 1)[0]
    assert open_fn.index('"preview_open"') < open_fn.index('deps.modal.open("previewSheet"'), (
        "면을 먼저 열고 나서 성사를 묻습니다 — 거절되면 무엇을 미리보는 중인지 거짓이 됩니다."
    )
    assert "flushPendingEdits" in open_fn, (
        "열기가 대기 중 편집을 추월합니다 — 미리보는 범위가 사용자가 본 그것이 아닙니다."
    )
    # 승인은 명시 클릭 하나. 면을 여는 것이 승인이 아니다(§13-4).
    assert '"preview_approve"' in src
    assert '"preview_approve"' not in open_fn, (
        "면을 여는 경로가 승인을 발신합니다(생성 ≠ 승인)."
    )
    # 잠금 범위(§9.3 2행) — 종전엔 화면 루트 질의가 오버레이를 못 훑어 `setBusy` 가 확인
    # 면을 따로 순회했다. React 소유에서는 그 사각이 **구조적으로 없다**: 이 면의 컨트롤이
    # 전부 같은 `run.running` 파생을 읽으므로 훑을 트리가 애초에 없다. 그래서 계약도
    # 「순회하는가」에서 「같은 근거에서 잠그는가」로 옮긴다.
    assert "const busy = run.running;" in drawer, (
        "생성 중 확인 면이 잠기지 않습니다 — 잠금 근거가 실행 상태가 아닙니다."
    )
    for control in ("previewPrev", "previewNext", "previewBlankOnly"):
        segment = drawer.split(f'id: "{control}"', 1)[1].split("}, ", 1)[0]
        assert "disabled: busy" in segment, f"{control} 이 생성 중에 잠기지 않습니다."
    # 승인은 잠금이 아니라 **부재**로 답한다 — 요구가 남아 있을 때만 선다. 없는 사건의
    # 버튼을 회색으로 두면 "여기서 뭔가 해야 하나" 하는 미끼가 된다.
    approve = drawer.split('id: "previewApprove"', 1)[1].split("}, ", 1)[0]
    assert 'display: p.can_approve ? "" : "none"' in approve, (
        "승인 버튼이 요구 여부와 무관하게 서 있습니다."
    )


def test_job_mirror_zone_is_one_line_without_a_value_table():
    """U2 §2.13 — 본문 존은 표 없는 한 줄이고, 값을 말하는 표면은 확인 면 하나다.

    구 거울 테이블(필드 채움 표 + 클릭형 ack 행 + 420px 캡)과 인라인 재진술의 파일 이름
    목록이 함께 죽었는지 정적으로 못박는다 — 어느 하나가 부활하면 C3(같은 값을 말하는
    두 표면)이 되돌아온다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    src = react_job_run_source()
    css = "".join(WEB_CSS.split())
    # 죽은 표면 3종 — 거울 테이블·클릭형 ack 행·캡스트립.
    assert 'table class="tb mir"' not in src and "mirrorRow" not in src
    assert "ack_field" not in src and "unack_field" not in src, (
        "죽은 필드축 ack 액션을 표면이 발신합니다(§2.13)."
    )
    assert "jobMirrorCapstrip" not in html and "capstrip" not in html
    # 한 줄의 성분 — 빈 값 표지(이름 지목)·이름 건수는 값이라 렌더가 채운다.
    mirror_fn = src.split("export function JobMirrorZone", 1)[1].split("\nexport function", 1)[0]
    assert "blank_fields" in mirror_fn and "mir-blank-flag" in mirror_fn
    # 한 줄과 danger 배너는 **다른 노드**다. 종전엔 같은 자리를 innerHTML 로 다퉈 배너가
    # 서면 트리거까지 함께 죽었고, 그래서 표시 토글 둘을 이름으로 겨눴다. React 소유에서는
    # 두 노드가 상시 렌더되고 `hidden` 하나만 갈리므로 그 결함이 구조적으로 없다.
    assert 'h("div", { id: "jobMirror" }, banner)' in mirror_fn, "danger 배너의 자리가 없습니다."
    assert 'id: "jobMirrorLine", hidden: banner !== null' in mirror_fn, (
        "한 줄과 danger 배너가 같은 자리를 다투면 트리거가 함께 죽습니다."
    )
    # 복귀 트리거 해석은 공용 단일 정의를 쓴다 — 두 출구가 **같은 진입점**에 같은 인자를
    # 넘긴다(위임/직접 클릭을 각자 풀면 한쪽이 빠진다).
    assert src.count("props.controller.openPreviewFrom(event.currentTarget)") == 2, (
        "확인 면 출구 둘이 복귀 트리거를 같은 방식으로 넘기지 않습니다."
    )
    assert "returnFocus: previewTrigger ?? deps.doc.getElementById(\"jobPreviewOpen\")" in src
    # 두 출구의 가용성은 **한 지점**에서 정한다(둘이 갈리면 한쪽만 열린 채 남는다).
    for host in ("jobMirrorPreviewOpen", "jobPreviewOpen"):
        segment = src.split(f'id: "{host}"', 1)[1].split("}, ", 1)[0]
        assert "pv.can_open" in segment, f"{host} 의 가용성이 Python 판정을 안 읽습니다."
    # 인라인 재진술은 수치·경로만 말한다 — 이름 목록(.namelist)은 확인 면으로 이주했다.
    restate_fn = src.split("export function JobRestate", 1)[1].split("\nfunction gateStep", 1)[0]
    assert "namelist" not in restate_fn and ".namelist" not in css
    # 안내 문안도 죽은 상호작용을 약속하지 않는다(§2.10 어휘 상속 — 「승인」만 남는다).
    assert "눌러서 확인" not in html and "클릭=확인" not in src


def test_preview_button_states_are_decided_after_the_busy_restore():
    """실 창 프로브가 잡은 자리 — `setBusy` 는 렌더 말미에 `[data-busy-lock]` 을 **일괄
    복원**하므로, 그전에 끈 버튼은 되살아난다(`jobBtnPickFolder` 가 같은 이유로 거기 있다).

    미리보기 이동 버튼은 경계에서 멈추는 것이 계약인데(순환하지 않는다), 판정을
    `renderPreview` 에만 두면 마지막 건에서도 「다음」이 눌린다 — 정적 배선은 멀쩡해 보이고
    실물만 틀리는 결함류라 렌더 순서를 계약으로 못박는다.
    """
    src = react_job_run_source()
    # 종전 결함의 기계는 **두 곳이 같은 속성을 쓰는 것**이었다: 렌더가 끈 버튼을 `setBusy`
    # 의 `[data-busy-lock]` 일괄 복원이 되살렸다. React 소유에서는 `disabled` 가 렌더의
    # 산출이라 되살릴 두 번째 쓰기가 없다 — 그래서 계약을 「어디서 정하는가(순서)」에서
    # 「**한 식**으로 정하는가」로 옮긴다. 경계에서 멈추는 것이 계약이므로(순환하지 않는다)
    # 그 식은 잠금(busy)과 Python 이 낸 경계 둘을 함께 읽어야 한다.
    for btn, boundary in (
        ("previewPrev", "!p.can_prev"),
        ("previewNext", "!p.can_next"),
        ("jobPreviewOpen", "!pv.can_open"),
    ):
        segment = src.split(f'id: "{btn}"', 1)[1].split("}, ", 1)[0]
        assert "disabled: busy" in segment, (
            f"{btn} 가용성이 실행 잠금을 안 읽습니다 — 생성 중에도 눌립니다."
        )
        assert boundary in segment, (
            f"{btn} 가용성이 Python 이 낸 경계를 안 읽습니다 — 마지막 건에서도 눌립니다."
        )
    # 두 번째 쓰기가 **없다**는 것이 이 계약의 음성 절반이다(있으면 순서 결함이 돌아온다).
    assert '.disabled =' not in src, (
        "가용성을 렌더 밖에서 다시 씁니다 — 일괄 복원이 되살리는 그 결함류입니다."
    )


def test_job_screen_branches_the_output_surfaces_on_the_media_python_declared():
    """산출 재진술·거울·저장 폴더는 **매체 파생**이다(F6 판정 D · 리뷰 6R).

    TXT 작업은 파일을 만들지 않는다 — 「문서 N건 · 저장 폴더」도, 살아 있는 폴더 피커도,
    행을 다 고른 뒤에도 「행을 선택하면 …」이라고 말하는 거울도 전부 거짓이다. 분기의
    근거는 Python 이 낸 `run_action.key` 하나여야 한다: 표면이 확장자·매체를 다시 읽으면
    같은 판정이 두 곳에 산다.
    """
    job_js = react_job_run_source()
    assert 'run_action.key === "workbench"' in job_js, (
        "매체 분기의 근거가 Python 이 낸 실행 행동 키가 아닙니다."
    )
    # 거울 존은 통째로 걷힌다(빈 상태 문안이 이행 불가능한 지시로 남지 않게).
    assert 'jobMirrorZone' in job_js and 'id: "jobMirrorZone"' in R4_PRODUCT_SCREENS.read_text(
        encoding="utf-8")
    # 저장 폴더 행·피커는 이 매체에 없는 축이다 — 그 판정도 같은 실행 행동 키에서 나온다.
    # (portal target `#jobOutRow` 의 실재는 위 거울 존 단언과 successor map 이 함께 진다.)
    assert 'id: "jobOutRow"' not in job_js, (
        "저장 폴더 행이 자기 portal target 을 다시 만듭니다 — 생산자가 둘이 됩니다."
    )
    out_row = job_js.split("export function JobOutRow", 1)[1].split("\nexport function", 1)[0]
    assert "isCopyWork(s)" in out_row, out_row[:400]
    # 산출 문안이 파일 생성을 주장하지 않는다.
    assert "파일은 만들지 않습니다" in job_js


# 커밋(= 누적된 상태를 **읽어서** 되돌릴 수 없는 일을 하는 발신)과, 그 앞에서 미착지 발신을
# 정산해야 하는 관문. 값은 (파일, 함수, 정산 술어) 다.
#
# **왜 정적 가드인가**(F6 8R P1 근본 조치). 이 결함류는 리뷰에서 네 번 잡혔고 그때마다
# 백엔드에서 한 칸씩 막았다 — 토큰 결속(3R) · 복사 거래 원자화(5R) · 잠금을 세션 전이로
# 확대(7R). 전부 필요했지만 **끝낼 수 없는 층**이었다: 잠금은 겹치지 않게 할 뿐 도착 순서를
# 정하지 않는다(먼저 잡는 쪽이 이긴다). 순서는 쏘는 쪽에서만 정해지고, 그 규약을 세운 자리가
# 없어서 화면마다 각자 발명했다(job=Intent.chained · 기안=flushDeb · 작업대=아무것도 없음).
#
# 그래서 규약을 여기 못박는다: **같은 상태를 바꾸는 발신은 한 체인, 그 상태를 읽는 커밋은 그
# 체인을 먼저 정산한다.** 새 화면이 이걸 빠뜨리면 리뷰 라운드가 아니라 이 게이트가 잡는다.
COMMIT_SETTLE_GUARDS = (
    ("../src/screens/workbench.ts", "async function copyCard()", "chain.settle(WB_CHAIN)"),
    ("../src/screens/workbench.ts", "async function saveRules()", "chain.settle(WB_CHAIN)"),
    ("../src/screens/workbench.ts", "async function leaveTo(", "chain.settle(WB_CHAIN)"),
    ("../src/screens/job_run.ts", "async function doGenerate(",
     "deps.ports.jobData.current().flushPendingEdits()"),
    ("../src/screens/job_run.ts", "async function startGenerate(",
     "deps.ports.jobData.current().flushPendingEdits()"),
    # (「기안」 flushDeb 행 삭제 — draftsession.js 가 화면과 함께 사망, F6 PR-B.
    #  복사 커밋의 승계처는 작업대 copyCard 로 위에 이미 서 있다.)
)


def _function_body(text: str, header: str) -> str:
    """``header`` 로 시작하는 함수의 본문 — 여는 중괄호부터 짝이 맞는 닫는 중괄호까지."""
    at = text.index(header)
    open_at = text.index("{", at)
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at:i + 1]
    raise AssertionError(f"함수 본문을 닫지 못했습니다: {header}")


def test_commits_settle_pending_sends_before_they_read_state():
    """커밋은 **미착지 발신을 정산한 뒤에** 상태를 읽는다(F6 8R P1 규약).

    pywebview 는 브리지 호출마다 별도 스레드라 동시 발신의 도착 순서가 정의되지 않는다.
    한 사용자 동작이 호출 둘로 쪼개지는 자리(값을 타이핑하고 곧바로 복사·나가기)에서 정산이
    없으면, 화면엔 방금 친 값이 보이는데 클립보드엔 **이전 값**이 나가거나 이탈 가드가
    「잃을 것 없음」을 답한 뒤 그 편집이 조용히 사라진다.
    """
    for rel, header, guard in COMMIT_SETTLE_GUARDS:
        text = (WEB_JS_DIR / rel).read_text(encoding="utf-8")
        assert header in text, f"{rel}: 커밋 함수가 사라졌습니다 — {header}"
        body = _function_body(text, header)
        assert guard in body, f"{rel} {header}: 정산 관문이 없습니다 — {guard}"
        # 정산은 **첫 브리지 발신보다 앞**이어야 한다(뒤에 있으면 이미 옛 상태를 읽은 뒤다).
        first_call = min(
            (body.index(tok) for tok in ("Bridge.call(", "Bridge.copyClipboard(",
                                         "Bridge.generate(", "deps.client.invoke(",
                                         "dispatch(") if tok in body),
            default=len(body),
        )
        assert body.index(guard) < first_call, (
            f"{rel} {header}: 정산이 첫 발신보다 뒤에 있습니다."
        )


def test_workbench_sends_all_share_one_chain():
    """작업대의 상태 변이는 **한 체인**이다 — 축별로 가르면 서로를 추월한다.

    이 화면의 작업점·보기·전각·맞추기 표는 전부 같은 세션을 바꾸고 같은 카드를 다시 그린다.
    맨 `Bridge.call` 로 남은 변이가 하나라도 있으면 그것만 순서 밖으로 새므로, 커밋이 정산해도
    잡히지 않는다(정산은 체인에 든 것만 기다린다).
    """
    text = R4_WORKBENCH.read_text(encoding="utf-8")
    # 커밋 3종은 정산으로 순서를 지키므로 체인 밖 직접 발신이 정당하다(위 테스트가 담보).
    commit_bodies = "".join(
        _function_body(text, h) for h in
        ("async function copyCard()", "async function saveRules()", "async function leaveTo(")
    )
    stray = [
        line.strip() for line in text.splitlines()
        if "Bridge.call(SCREEN," in line
        and not line.lstrip().startswith(("//", "/*", "*"))   # 주석에 적힌 예시는 발신이 아니다
        and "sendWb(" not in line
        and line.strip() not in commit_bodies
    ]
    assert not stray, "체인 밖 작업대 변이 발신: " + " | ".join(stray)


def test_volatile_draft_retirement_notices_have_producer_and_consumer() -> None:
    """휘발 「기안」 폐지 고지 ①②(F6 PR-B, §10.15.15 점검표 6행) — 생산·소비가 한 벌인가.

    페이로드 키만 등록되고 그리는 자리가 없으면 고지는 영영 안 보인다(「등록만 되고 배선
    없는」 결함류 — F6 4R 표본). 문안 술어는 헤드리스(test_webapp_job·test_webapp_template)
    가 보고, 여기는 정적 배선만 센다.
    """
    src = REPO_ROOT / "src" / "hwpxfiller" / "webapp"
    job_py = (src / "screen_job.py").read_text(encoding="utf-8")
    tpl_py = (src / "screen_template.py").read_text(encoding="utf-8")
    job_js = R4_JOB_READ.read_text(encoding="utf-8")
    # ① 문서 만들기 후보 TXT 구획 빈 상태 — screen_job 이 내고 job.js 가 그린다.
    assert '"txt_note"' in job_py and "_txt_onboarding_note" in job_py
    assert "candidates.txt_note" in job_js
    # ② tpl TXT 밴드 고지는 화면과 함께 사망(F8 §10.17) — 생산이 되살아나면 소비 없는
    # 유령 페이로드다(「등록만 되고 배선 없는」 결함류의 역방향).
    assert 'txt["notice"]' not in tpl_py
