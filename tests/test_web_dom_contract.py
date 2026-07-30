"""현재 배포 웹 프론트엔드의 정적 DOM 계약 — ``web/index.html`` 자체를 검사한다.

``test_ui_contract.py`` 는 목업(``docs/UI_PROTOTYPE_APPB.html``)의 ``data-vm`` 주석이
생존 ViewModel 표면과 정합한지만 보는 역사 가드다. 이 모듈이 현재 정본인 실제
``web/index.html``과 JavaScript/CSS 배선을 읽어 **전역 id 유일성**, 화면 구조와 정적 seam을
단언한다. 실제 렌더·클릭·브리지 왕복은 ``test_web_selftest_gate.py``의 WebView2 게이트가 맡는다.

배경(#27): ``id="dataLabel"`` 이 실행(run)·즉시기안(txt) 두 화면에 중복돼, 전역
``getElementById`` 가 항상 첫 화면 요소만 반환 → txt 갱신이 run 입력을 건드리는 크로스-스크린
오염이 있었다. 이 테스트가 그 재발을 CI 에서 직접 차단한다(접근성 계약 강화는 #27 잔여 범위).
"""
from __future__ import annotations

import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from _web_css import ALL_CSS_FILES, app_css, linked_css

WEB_INDEX = Path(__file__).resolve().parents[1] / "web" / "index.html"
# web/ 앱 스타일시트는 분할됐다 — 여기서만 **문자열**(조각을 링크 순서대로 이어붙인 구
# app.css 등가)이다.
WEB_CSS = app_css()
# (web-diff/ 짝 가드는 hwpx-diff 저장소 분리와 함께 그쪽 test_web_dom_contract.py 로 갔다.)

# 반응형 경계(#27): 창 최소폭(760)보다 넓은 이 경계에서 2판 레이아웃이 세로 적층으로 접혀야
# 최소 크기에서도 가로 오버플로 없이 쓸 수 있다. 경계나 접힘 규칙이 사라지면 회귀.
RESPONSIVE_BREAKPOINT_PX = 820

# 전체 스냅샷 재렌더가 포커스·캐럿·스크롤을 뭉개지 않도록 render() 를 Preserve.around 로 감싸는
# 화면들(#28). 어느 화면이 래핑을 조용히 떨구면 상호작용 유실 회귀 → 정적 가드로 차단.
WEB_JS_DIR = Path(__file__).resolve().parents[1] / "web" / "js"
# 렌더 래핑·데이터 피커 계약은 **표면을 소유한 파일**을 따라간다 — 화면 파일명과 1:1 이
# 아니다. draftsession.js 는 「기안」 화면과 함께 사망(F6 PR-B) — 승계 표면인 작업대가
# 맞추기 표 렌더를 같은 래핑으로 보존한다(workbench.js renderMap).
PRESERVE_WRAPPED_FILES = ("screens/editor.js", "screens/job.js", "screens/workbench.js")

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
MUTABLE_MODULE_STATE_BUDGET = {
    "screens/job.js": 17,
    # (screens/template.js 는 화면 사망으로 파일째 삭제 — F8 §10.17. 관리·저작 상태는
    #  editor.js 의 libMenuFor·txtEdit 2객체로 이주했다.)
    # screens/draft.js·draftsession.js 는 화면 사망으로 파일째 삭제(F6 PR-B).
    # 작업대(F6) — 스냅샷 1개(LAST)뿐이다. 작업점·복사 이력·미저장 변경·린트를 전부
    # Python 이 소유하므로 표면이 들 것이 없다(데이터 존이 없는 화면이라 더 그렇다).
    "screens/workbench.js": 1,
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
    "screens/editor.js": 8,
    "screens/library.js": 3,
    "data_picker.js": 4,
    "datazone.js": 0,
}

# 살아있는 컴포넌트 갤러리(개발 전용) — 실 tokens.css+app.css 를 <link> 로 물어 드리프트 0.
GALLERY = Path(__file__).resolve().parents[1] / "docs" / "UI_GALLERY.html"

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
    "confirmModal": "confirmModalTitle",  # 네이티브 window.confirm 대체(#86) + 덮어쓰기 확인
    "promptModal": "promptModalTitle",  # 네이티브 window.prompt 대체(#86)
    # 답이 셋인 자리(재작성 F7 — patch 처분: 저장하고 이동·버리고 이동·머무르기). 확인 모달로
    # 두 번 물으면 "취소가 무엇을 취소하는지"가 갈리고 그 모호함이 곧 조용한 파기다.
    "chooseModal": "chooseModalTitle",
    # draftMapSheet 은 「기안」과 함께 사망(F6 PR-B) — 맞추기 표는 작업대 #wbMapPanel 승계.
    "dataSheet": "dataSheetTitle",  # 작업 데이터 펼침 면(#271/#272 — 기안 몫은 F6 PR-B 사망)
    "jobConfirmSheet": "jobConfirmSheetTitle",  # 작업 거울·재진술 펼침 면(#272)
}


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
    assert WEB_INDEX.exists(), f"배포 웹 프론트엔드가 없습니다: {WEB_INDEX}"


def test_all_element_ids_are_globally_unique():
    """실제 DOM 의 전역 id 유일성 — 중복이 있으면 getElementById 가 크로스-스크린 오염(#27)."""
    counts = Counter(_collect_ids())
    dupes = {i: n for i, n in counts.items() if n > 1}
    assert not dupes, (
        "web/index.html 에 중복 id 가 있습니다(전역 getElementById 오염 위험): "
        + ", ".join(f"{i}×{n}" for i, n in sorted(dupes.items()))
    )


def test_screen_roots_present():
    ids = set(_collect_ids())
    missing = [r for r in SCREEN_ROOTS if r not in ids]
    assert not missing, f"화면 루트가 사라졌습니다: {missing}"


def test_scoped_data_labels_present_and_unique():
    """개명된 화면별 데이터 라벨이 각각 정확히 1회 존재(#27 — 공용 dataLabel 재도입 차단)."""
    counts = Counter(_collect_ids())
    for label in SCOPED_DATA_LABELS:
        assert counts[label] == 1, (
            f"{label} 가 {counts[label]}회 — 화면별 고유 데이터 라벨이 정확히 1개여야 합니다."
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
    for mid, label_id in MODAL_LABELLEDBY.items():
        assert mid in modals, f"커스텀 모달이 사라졌습니다: {mid}"
        attrs = modals[mid]
        assert attrs.get("role") == "dialog", f"{mid} 에 role=\"dialog\" 가 필요합니다."
        assert attrs.get("aria-modal") == "true", f"{mid} 에 aria-modal=\"true\" 가 필요합니다."
        assert attrs.get("aria-labelledby") == label_id, (
            f"{mid} 의 aria-labelledby 는 '{label_id}' 여야 합니다(현재: {attrs.get('aria-labelledby')!r})."
        )
        assert label_id in ids, f"{mid} 의 aria-labelledby 대상 id '{label_id}' 가 DOM 에 없습니다."


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
    css = "".join(WEB_CSS.split())
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    sheets = (WEB_JS_DIR / "surface_sheet.js").read_text(encoding="utf-8")
    app_py = (WEB_INDEX.parents[1] / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(
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
    assert ".capstrip[hidden]{display:none}" in css

    assert 'class="data-grid" id="jobDataGrid"' in html
    assert 'class="duo job-duo"' not in html and ".job-duo{" not in css, (
        "구 표|거울 duo 가 재유입됐습니다 — R1 의 가로 축은 데이터↔문서 선택기입니다."
    )
    grid = html.split('id="jobDataGrid"', 1)[1].split("job-edit-host", 1)[0]
    main, side = grid.split('class="dg-side"', 1)
    # 좌 열 = 현재 데이터 → 거울 → 결과(세로), 우 열 = 문서 선택기 → 선택한 작업 → 생성 준비.
    assert main.index('id="jobTableHost"') < main.index('id="jobMirror"') < main.index('id="jobGenLog"')
    assert side.index('id="jobCandidates"') < side.index('id="jobHeadTitle"') < side.index('id="jobOutDir"')
    assert 'id="jobMirrorCapstrip" role="status" hidden' in main
    assert "#jobMirror{max-height:420px;overflow:auto}" in css
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
    assert '<div class="actionbar-row">' in html, (
        "액션바 내용을 감싸지 않으면 자식들이 두 열에 흩어진다."
    )
    assert "@containersession-panel(max-width:900px)" in css
    assert ".job-zones,.session-actionbar{--data-grid-cols:1fr}" in css
    # 좁은 side-card 에서 라벨+입력+버튼을 한 줄에 밀어 넣으면 저장 폴더 경로가 몇 글자로
    # 잘려 "어디에 저장되는지"를 못 읽는다 — 감싸기 규칙이 그 되읽기를 지킨다.
    assert ".dg-side.run-row{flex-wrap:wrap;row-gap:var(--sp-4)}" in css
    assert ".dg-side.run-row>.field{flex:11100%}" in css
    assert '<div id="jobConfirmSheet" class="modal sheet hidden"' in html
    assert "펼쳐서 행 고르기 ⤢" in html and "펼쳐서 확인 ⤢" in html
    assert 'modalId: "jobConfirmSheet"' in job_js
    assert '{ id: "jobMirror", slotId: "jobConfirmSheetMirrorSlot" }' in job_js
    assert '{ id: "jobRestate", slotId: "jobConfirmSheetRestateSlot" }' in job_js
    for node_id in (
        "jobRecsHead", "jobFilterChips", "jobTableHost", "jobSelStrip", "jobColPanel",
    ):
        assert f'{{ id: "{node_id}", slotId: "dataSheetSlot" }}' in job_js
    assert 'closeAndRestore("jobConfirmSheet")' in job_js
    # 화면을 떠날 때의 일괄 회수(재작성 F7) — 펼침 면은 실 DOM 을 오버레이로 옮겨 띄우므로
    # 열린 채 화면이 바뀌면 남의 화면 위에 이 화면의 DOM 이 뜬다. 소유가 화면 전환으로
    # 올라가 어느 화면이 늘어도 같은 회수가 걸린다(종전엔 편집 모드 진입이 그 자리에서 닫았다).
    app_js_src = (WEB_JS_DIR / "app.js").read_text(encoding="utf-8")
    assert "SurfaceSheet.closeAllAndRestore()" in app_js_src, (
        "화면 전환이 펼침 면을 회수하지 않습니다 — 남의 화면 위에 실 DOM 이 남습니다."
    )
    assert "function closeAllAndRestore" in sheets
    assert "window.Modal.close(id);\n    restore(id);" in sheets
    # 펼침 트리거 포커스 복귀(#279 리뷰) — 캡스트립 위임 클릭의 currentTarget 은 포커스
    # 불가능한 컨테이너 div: 실클릭 버튼→상시 ⤢ 순으로 해석하는 SurfaceSheet.trigger 만 쓴다.
    # (기안 소비자 draftsession.js 는 화면과 함께 사망 — F6 PR-B. 소비자는 job 하나다.)
    assert "trigger: trigger" in sheets
    assert "window.SurfaceSheet.trigger(e," in job_js
    assert "returnFocus: e && e.currentTarget" not in job_js
    # 캡스트립 생성 버튼은 복귀 표적 제외(#280 리뷰) — afterRestore 의 measure* 가
    # innerHTML 을 갈아 방금 포커스한 버튼이 분리된다(안정 헤더 ⤢ 폴백 고정).
    assert 'btn.closest(".capstrip")' in sheets
    assert html.count('class="capstrip"') >= 1
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
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    css = "".join(WEB_CSS.split())
    block = job_js[job_js.index("function renderResult"):job_js.index("function warnResult")]
    assert "res.cancelled" in block and "res.attempted" in block
    assert '$("jobGenBar").style.width = "100%"' not in block
    panel = job_js[job_js.index("function renderResultPanel"):job_js.index("function failRow")]
    assert 'box.dataset.level = r.level' in panel, "level 채널을 JS 가 재판정하고 있습니다."
    assert '.result3[data-level="warn"]' in css and '.result3[data-level="danger"]' in css


def test_milestone_l_wide_probes_do_not_depend_on_host_monitor_width():
    """Actions 가상 화면이 1440px 미만이어도 wide 컨테이너 분기를 직접 검증해야 한다."""
    app_py = (WEB_INDEX.parents[1] / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(
        encoding="utf-8"
    )
    # draftPanel 프로브는 화면 사망(F6 PR-B)과 함께 걷혔다 — 남은 wide 분기는 job 하나.
    assert "jobPanel.style.flex = '0 0 1100px'" in app_py
    assert "jobPanel.style.flex = jobPanelFlex" in app_py


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
DATA_PICK_FILES = ("screens/editor.js", "data_picker.js")


def test_sheet_picker_loaded_and_wired_on_all_data_screens():
    """다중 시트 확정 게이트 배선 정적 가드(#33) — 조용한 첫 시트 로드 회귀 차단.

    실 시트 선택 거동(모달 개폐·확정 로드)은 Modal/브리지 계약 테스트가 본다 — 여기선
    (a) 헬퍼·모달 골격 존재, (b) 데이터를 붙이는 **모든** 화면(에디터·작업·txt·빠른 기안)이
    pickDataFile 의 needs_sheet 를 받아 SheetPicker 로 확정을 태우는 배선이 살아있는지를 정적
    가드한다. pickDataFile 계약이 screen-불가지라, 한 화면이라도 이 분기를 떨구면 그 화면에서
    다중 시트가 조용히 첫 시트로 강등되는 회귀(리뷰 P1 재발 차단).
    """
    index = WEB_INDEX.read_text(encoding="utf-8")
    assert 'src="js/sheet_picker.js"' in index, "sheet_picker.js 가 index.html 에 로드되지 않았습니다(#33)."
    assert 'id="sheetList"' in index and 'id="sheetCancel"' in index, "시트 선택 모달 골격이 없습니다(#33)."
    for rel in DATA_PICK_FILES:
        src = (WEB_JS_DIR / rel).read_text(encoding="utf-8")
        assert "needs_sheet" in src and "SheetPicker.choose" in src, (
            f"{rel} 이 다중 시트 확정 게이트(needs_sheet→SheetPicker) 배선을 잃었습니다 — "
            "이 화면에서 다중 시트가 조용히 첫 시트로 강등됩니다(#33, 리뷰 P1)."
        )


def test_preserve_helper_loaded_and_wraps_screen_renders():
    """상호작용 보존 헬퍼가 로드되고 4개 화면 render() 가 Preserve.around 로 감싸져 있어야 한다(#28).

    실 재구성 가로지르기 거동(포커스·캐럿·스크롤 유지)은 selftest 게이트가 되읽어 단언한다 —
    여기선 헤드리스 포함 전 플랫폼에서 배선(스크립트 로드·화면별 래핑)의 존재를 정적으로 가드해
    어느 화면이 래핑을 조용히 떨구는 회귀를 막는다.
    """
    index = WEB_INDEX.read_text(encoding="utf-8")
    assert 'src="js/preserve.js"' in index, "preserve.js 가 index.html 에 로드되지 않았습니다(#28)."
    for rel in PRESERVE_WRAPPED_FILES:
        src = (WEB_JS_DIR / rel).read_text(encoding="utf-8")
        assert "Preserve.around" in src, (
            f"{rel} 의 render() 가 Preserve.around 래핑을 잃었습니다 — 재렌더 시 상호작용 유실(#28)."
        )


def _mutable_module_state(src: str) -> list[str]:
    """IIFE 본문(2칸 들여쓰기)의 `let`·`var` 선언 이름 — 렌더 층 가변 모듈 상태의 실측치.

    블록 주석을 먼저 지운다(주석 속 예시 코드가 예산을 먹지 않게). 이 앱의 `web/js/*` 는 전부
    `(function () {` 즉시실행 래퍼라 **2칸 = 모듈 스코프**이고 함수 본문은 4칸 이상이다 —
    파서 없이 성립하는 관례 기반 계측이며, 예산(천장)에는 이 정밀도로 충분하다.
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
        path = WEB_JS_DIR / rel
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
    screens = {f"screens/{p.name}" for p in (WEB_JS_DIR / "screens").glob("*.js")}
    missing = sorted(screens - set(MUTABLE_MODULE_STATE_BUDGET))
    assert not missing, (
        f"화면 파일이 상태 예산에 없습니다: {', '.join(missing)}. "
        f"MUTABLE_MODULE_STATE_BUDGET 에 실측 상한을 등재하세요(신설 화면의 기준선은 낮게 — "
        f"job.js 17 은 긴 절차가 만든 부채지 목표가 아닙니다)."
    )


def test_job_overwrite_uses_shared_confirm_modal():
    """덮어쓰기 확인이 공용 Modal.confirm(수치 합성 본문)을 쓴다 — 전용 모달·window.confirm 무사용.

    슬라이스 2(A-2-22): 전용 jobOverwriteModal 폐기, 수치 합성(총량·파괴분·신규분)은
    overwriteBody 가 조립해 Modal.confirm 본문으로 넘긴다. 네이티브 window.confirm 무사용은
    별도 코멘트-인지 가드(test_web_native_dialog_guard)가 담보한다.
    """
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert "Modal.confirm({" in src, "덮어쓰기 확인이 공용 Modal.confirm 을 쓰지 않습니다(A-2-22)."
    assert "function overwriteBody(" in src, "수치 합성 본문(overwriteBody)이 없습니다(A-2-22)."


def test_job_overwrite_keeps_busy_lock_through_modal():
    """리뷰 #1 회귀 가드: 작업 화면 덮어쓰기 모달 대기 동안 생성 버튼이 재활성되지 않는다.

    modal.js 는 포커스 트랩이 없어(blocking window.confirm 과 다름) 모달 뒤 살아있는 생성
    버튼에 Tab+Enter 가 닿으면 두 번째 생성이 첫 확인 미결인 채 시작된다(같은 폴더 동시 기록).
    busy-lock 해제(``generating = false``)가 덮어쓰기 확인 await **뒤**에 와야 한다 — 소스
    순서로 정적 가드(실 거동은 selftest 게이트 소관).
    """
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    # doGenerate 안에서 busy 해제가 모달 await 보다 앞서면(옛 구조) 이 순서가 뒤집힌다.
    i_confirm = src.index("await window.Modal.confirm({")
    i_release = src.index("generating = false; setBusy(false);")
    assert i_confirm < i_release, (
        "busy-lock 해제가 덮어쓰기 모달 await 전에 온다 — 모달 열림 동안 생성 버튼 재활성으로 "
        "재진입 경합(리뷰 #1). finally 를 needs_overwrite 흐름 뒤로 미뤄라."
    )


def test_job_completion_zone_reset_gated_by_session_change():
    """리뷰 #3 회귀 가드: 완료 존 리셋이 매 push 가 아니라 세션 변경에 결속된다(결정 7).

    작업 화면은 REFRESH_ON_NAV 에 있어 레일 복귀마다 full re-push 가 돈다 — 리셋이 무조건이면
    세션 불변인데도 생성 리포트가 소멸(결정 7: 완료 존 = 세션 스코프 보존 위배). 세션 지문
    (``sessionKey``)이 바뀔 때만 리셋해야 한다.
    """
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert "function sessionKey(" in src, "완료 존 세션 지문(sessionKey)이 없습니다(#3)."
    assert "key !== lastSessionKey" in src, "리셋이 세션 변경에 결속되지 않았습니다(#3)."
    # 옛 무조건 리셋(if (!generating) resetGenResult();)이 남아 있으면 안 된다.
    assert "if (!generating) resetGenResult()" not in src, (
        "무조건 완료 존 리셋이 남아 있습니다 — nav 복귀마다 생성 리포트 소멸(리뷰 #3, 결정 7)."
    )


# (구 test_run_overwrite_keeps_busy_lock_through_modal 삭제 — run.js 사망(슬라이스 3).
#  동형 가드는 test_job_overwrite_keeps_busy_lock_through_modal 가 job.js 에서 이어받는다.)


def test_modal_promise_dialog_serialization_guards_present():
    """PR #92 리뷰 #1/#3/#4 정적 가드: modal.js 가 native 단일-실행 직렬화의 세 다리를 유지한다.

    실 거동(재진입 loud 거절·Tab 순환·개폐)은 selftest 게이트가 되읽는다 — 여기선 헤드리스
    포함 전 플랫폼에서 가드 코드의 존재를 정적으로 단언해 조용한 삭제 회귀를 막는다:
      - 재진입 가드(pendingDialog): promise 다이얼로그 동시 1건 — 없으면 공유 골격에 리스너가
        이중 바인딩돼 확인 1클릭으로 두 파괴 동작이 실행된다(리뷰 #1).
      - 포커스 트랩(trapTab): 배경 버튼 Tab+Enter 발화 차단(리뷰 #1).
      - IME 조합 가드(isComposing): 한글 조합 확정 Enter 조기 제출로 잘린 값 저장 방지(리뷰 #3).
      - loud 거절(window.alert + console.error): 골격 부재·재진입의 조용한 no-op 금지(리뷰 #4).
    """
    src = (WEB_JS_DIR / "modal.js").read_text(encoding="utf-8")
    assert "pendingDialog" in src, "promise 다이얼로그 재진입 가드(pendingDialog)가 사라졌습니다(#92 #1)."
    assert "trapTab" in src, "포커스 트랩(trapTab)이 사라졌습니다 — 배경 Tab 이탈 재개방(#92 #1)."
    assert "isComposing" in src, "IME 조합 가드(isComposing)가 사라졌습니다 — 조기 제출 회귀(#92 #3)."
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
    linked = linked_css(html, "../web/css/")
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
    html = " ".join(WEB_INDEX.read_text(encoding="utf-8").split())
    job = html.split('id="scr-job"', 1)[1].split('id="scr-editor"', 1)[0]
    for caption in (
        "현재 데이터", "본문 확인", "생성 결과",
        "이 데이터에 사용할 문서", "선택한 작업", "생성 준비",
    ):
        # 캡션 자리에 id 가 붙을 수 있다(「생성 준비」는 매체에 따라 「복사 준비」로 바뀐다) —
        # 계약이 세는 것은 **zone-cap 캡션의 존재**이지 속성 목록이 아니다.
        needle = rf'<div class="zone-cap[^"]*"[^>]*>(?:<span[^>]*>)?{re.escape(caption)}'
        assert re.search(needle, job), f"세션 구획 캡션이 없습니다: {caption}"
    assert '<span class="znum">' not in job, (
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
    job = html.split('id="scr-job"', 1)[1].split('id="scr-editor"', 1)[0]
    flat = " ".join(job.split())
    assert 'id="jobResult" class="result3" data-state="" aria-live="polite" hidden' in flat
    for bid in ("jobResultFailedSel", "jobResultRename", "jobResultClose"):
        assert re.search(rf'id="{bid}"[^>]*type="button"\s*data-busy-lock', flat), (
            f"결과 구획 행동이 busy-lock 을 선언하지 않았습니다: {bid}"
        )
    for pid in ("jobResultTitle", "jobResultSummary", "jobResultStale",
                "jobResultDir", "jobResultTrack", "jobResultFails"):
        assert f'id="{pid}"' in flat, f"결과 구획 조각 누락: {pid}"
    # 증거는 <details> 다 — 열림 상태를 DOM 이 소유해야 재렌더를 건넌다(계약면 1).
    assert '<details class="result3-evidence" id="jobResultEvidence" hidden>' in flat
    # 구 단일 요약 줄은 3태 구획이 승계했다(두 벌 병존 금지).
    assert 'id="jobGenResult"' not in html
    # 실행 기록은 존치하되 역할이 바뀌었고(캡션), **기본은 접힘**이다(평상시 노이즈 억제).
    # 단 접힘이 소음 제거가 되면 안 된다 — 마지막 기록 한 줄은 요약에 상시 남는다.
    assert '<details class="runlog" id="jobRunLog">' in flat and "<details open" not in flat
    assert '<span class="zone-cap zone-cap-sub">실행 기록</span>' in flat
    assert 'id="jobRunLogLast"' in flat and 'id="jobGenLog"' in flat
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    log_fn = job_js[job_js.index("function log(msg)"):job_js.index("function setBusy")]
    assert '$("jobRunLogLast").textContent = msg' in log_fn, (
        "접힌 실행 기록의 요약 줄이 갱신되지 않으면 실패 통보가 조용해집니다."
    )


def test_job_gate_adds_blocked_step_only_in_display_layer():
    """H-03 승계: gate.level 판정은 건드리지 않고 표시층에서 막힌 **구획 이름**만 결합한다.

    R1 이 4존 서수를 은퇴시켰으므로 지목도 실재하는 구획 캡션을 쓴다 — 죽은 번호를 남기면
    지목 자체가 거짓말이 된다. 지목 문자열은 반드시 실제 `zone-cap` 캡션과 일치해야 한다.
    """
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    html = " ".join(WEB_INDEX.read_text(encoding="utf-8").split())
    job = html.split('id="scr-job"', 1)[1].split('id="scr-editor"', 1)[0]
    assert "function gateStep(s, g)" in src
    assert not re.search(r'return "[①②③]', src), "죽은 4존 서수가 남아 있습니다."
    for caption in ("현재 데이터", "이 데이터에 사용할 문서", "선택한 작업", "본문 확인"):
        assert f'"{caption} · "' in src or f'= "{caption} · "' in src, (
            f"게이트 구획 지목 누락: {caption}"
        )
        assert caption in job, f"지목이 실재하지 않는 구획을 가리킵니다: {caption}"
    assert 'gateStep(s, g) + g.text' in src
    assert not re.search(r"\bg\.level\s*=(?!=)", src), (
        "표시층이 gate.level 판정을 변조하면 안 됩니다."
    )


def test_job_data_first_prework_surface_contract():
    """데이터-우선(§18.2) 정적 계약 — 후보 구획 실재·빈 패널 은퇴·무작업 렌더 배선.

    구 미선택 빈 패널(jobEmptyPanel)의 재유입을 막고(안내 의무는 prework 게이트 문안이
    승계), 후보 카드 구획과 무작업 서수(②)가 배선돼 있는지 소스 수준에서 못박는다 —
    실렌더 동작판은 selftest ``job_data_first`` 프로브.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert 'id="jobCandsRow"' in html and 'id="jobCandidates"' in html, (
        "문서 작업 후보 구획이 없습니다(데이터-우선 §18.4)."
    )
    assert "jobEmptyPanel" not in html, (
        "은퇴한 미선택 빈 패널이 재유입됐습니다 — 세션 존은 무작업에도 살아야 합니다(§18.2)."
    )
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert "function renderCandidates(s)" in src
    assert "jobEmptyPanel" not in src
    assert "if (!s.has_job) return noRows ? DATA : DOC;" in src, (
        "무작업 prework 게이트의 구획 지목 배선이 없습니다."
    )
    assert "data-cand" in src  # 후보 카드 클릭 → select_job 위임
    # 활성 후보 재활성화 가드(#302 리뷰 P2) — pointer-events:none 은 키보드 합성 클릭을
    # 못 막으므로 핸들러가 aria-pressed 를 검사해야 한다(재선택=실행 증거 조용한 소실).
    assert 'aria-pressed") !== "true"' in src, "활성 후보 재활성화 가드가 없습니다."


def test_job_display_order_axis_surface_contract():
    """재작성 F3 정적 계약 — 표시순서 축의 요소·2값·⤢ 동행·왕복 의도 보호.

    실행 거동(왕복 뒤 값 유지)은 selftest ``view_order`` 프로브가 본다. 여기서는 그 프로브가
    없으면 조용히 사라질 배선을 못박는다: ①축 요소 3종 ②계약이 정한 2값 그대로(§18.10)
    ③⤢ 펼침 면 이동 목록에 동행(축이 메인에만 남으면 펼친 면에서 도달 불가) ④왕복 중
    의도 보호(pendingOrder) — 셋 다 "지우면 조용히 나빠지는" 배선이다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    for element in ('id="jobOrderBar"', 'id="jobOrderSel"', 'id="jobOrderNote"'):
        assert element in html, f"표시순서 축 요소가 없습니다: {element}"
    assert 'value="sourceDesc"' in html and 'value="sourceAsc"' in html, (
        "표시순서 2값(§18.10)이 계약 어휘와 다릅니다."
    )
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    moves = src.split("openJobDataSheet", 1)[1].split("moves: [", 1)[1].split("]", 1)[0]
    assert "jobOrderBar" in moves, "⤢ 펼침 면에 표시순서 축이 따라가지 않습니다(판정 C)."
    assert "pendingOrder" in src, "왕복 중 의도 보호가 없습니다 — push 가 선택을 되돌립니다."
    assert "set_view_order" in src


def test_job_range_draft_surface_contract():
    """재작성 F3 정적 계약 — 범위 편집기 footer 의 소유·출구 단일 관문·성사 뒤 열기.

    ①footer 는 화면 DOM 소유다(면 마크업에 두면 같은 면을 쓰는 「기안」에 남의 footer 가
    뜬다) ②모든 출구(취소·닫기·Escape)가 `beforeClose` 한 관문을 지난다 — 경로마다 가드를
    걸면 하나는 반드시 빠진다 ③초안 생성이 성사된 뒤에만 면을 연다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert 'id="jobRangeFoot"' in html, "범위 편집기 footer 가 없습니다."
    # 소유 = 「문서 만들기」 화면 루트 안(공용 펼침 면 마크업 밖). 면 안에 두면 같은 면을
    # 쓰는 「기안」에 남의 footer 가 뜬다 — 실 DOM 이동이 소유를 대신 증명한다.
    job_screen = html.split('id="scr-job"', 1)[1].split('id="dataSheet"', 1)[0]
    assert 'id="jobRangeFoot"' in job_screen, (
        "footer 가 화면 소유가 아닙니다 — 공용 펼침 면 마크업에 있으면 「기안」에도 뜹니다."
    )
    for element in ("jobRangeApply", "jobRangeCancel", "jobRangeSelectedOnly", "jobRangeNote"):
        assert f'id="{element}"' in html, f"범위 편집기 출구가 없습니다: {element}"
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert "beforeClose: guardRangeClose" in src, "이탈 가드가 닫기 관문에 걸려 있지 않습니다."
    assert 'Bridge.call(SCREEN, "range_draft_open"' in src
    assert "SurfaceSheet.open" in src.split("range_draft_open", 1)[1], (
        "초안 생성 **뒤에** 면을 여는 순서가 아닙니다(성사 뒤에만 닫고 연다)."
    )
    # 열기도 **존 체인**에 선다(리뷰 5R): 방금 친 편집이 큐에 있는데 열기가 먼저 도착하면
    # 그 편집이 옛 세대로 거절돼 사용자가 본 변경이 커밋에도 초안에도 없이 사라진다.
    open_fn2 = src.split("function openJobDataSheet", 1)[1].split("\n  }", 1)[0]
    assert "flushPendingEdits" in open_fn2 and "Intent.chained(ZONE_CHAIN" in open_fn2, (
        "열기가 대기 중 편집을 추월합니다(정산·직렬화 없음)."
    )
    # 데이터-우선(§18.2): 데이터 면은 **렌더마다 닫지 않는다** — 작업 미선택 렌더마다 닫으면
    # 작업을 고르기 전엔 범위 편집기가 첫 왕복마다 취소돼 쓸 수 없다(리뷰 5R). 화면을 떠날
    # 때의 회수는 이제 전환이 진다(재작성 F7 — SurfaceSheet.closeAllAndRestore).
    mode_fn = src.split("function syncModeDisplay", 1)[1].split("\n  }", 1)[0]
    assert 'closeAndRestore("dataSheet")' not in mode_fn, (
        "데이터 면을 렌더마다 닫습니다 — 작업 미선택 세션에서 범위 편집기가 못 쓰게 됩니다."
    )
    assert '!hasJob) window.SurfaceSheet.closeAndRestore("jobConfirmSheet")' in mode_fn, (
        "거울 면은 작업이 없으면 닫혀야 합니다(작업의 것이라 설 자리가 없다)."
    )
    assert 'Bridge.call(SCREEN, "range_draft_cancel"' in src, "닫힘 경로가 초안을 버리지 않습니다."
    # 취소도 **성사 뒤에 닫는다**(리뷰 1R): 먼저 닫으면 느린 브리지에서 메인이 초안 기준
    # 행을 그리고, 발신이 거절되면 Python 초안만 고아로 남는다.
    discard = src.split("async function discardAndClose", 1)[1].split("\n  }", 1)[0]
    assert discard.index("await window.Intent.chained") < discard.index("SurfaceSheet.close"), (
        "취소가 폐기 성사 전에 면을 닫습니다."
    )
    # 디바운스 안에서 누른 취소는 대기 중 편집을 **보내지 않는다**(리뷰 2R P1) — 초안이
    # 사라진 뒤 도착하면 버린 검색어가 커밋된 필터에 착지한다. 적용 쪽은 반대로 정산한다.
    assert discard.index("dropPendingEdits") < discard.index("range_draft_cancel"), (
        "취소가 대기 중 편집을 폐기하지 않습니다."
    )
    apply_fn = src.split("async function applyRangeDraft", 1)[1].split("\n  }", 1)[0]
    assert apply_fn.index("flushPendingEdits") < apply_fn.index("range_draft_apply"), (
        "적용이 대기 중 편집을 정산하지 않습니다(방금 친 조건이 사라집니다)."
    )
    # 존 변이는 **대상 세계 세대**를 업고 간다(리뷰 4R) — 느린 출구 뒤에 줄 선 편집이
    # 커밋 범위에 착지하던 창을 원천에서 닫는다. 판정은 Python, 웹은 나르기만.
    assert "epoch: () => (LAST ? LAST.zone_epoch : undefined)" in src, (
        "존 변이가 대상 세계 세대를 싣지 않습니다."
    )
    assert "pendingZoneMutations" in src, "대기 중 편집 카운터가 없습니다(이탈 가드 소재)."
    guard = src.split("function guardRangeClose", 1)[1].split("\n  }", 1)[0]
    assert "pendingZoneMutations === 0" in guard, (
        "이탈 가드가 아직 푸시 안 온 편집을 못 봅니다 — 확인 없이 버립니다."
    )
    # 축 왕복 실패는 선택기를 되돌린다(스냅샷이 안 오므로 화면이 거짓말한 채 남는다).
    order_fail = src.split("async function onOrderChange", 1)[1].split("\n  }", 1)[0]
    assert "renderOrderBar(LAST)" in order_fail, "축 왕복 실패가 선택기를 되돌리지 않습니다."
    # 존 발신과 초안 출구가 **한 체인**을 쓴다 — 도착 순서가 뒤바뀌면 취소한 편집이 커밋된다.
    assert 'chainKey: ZONE_CHAIN' in src and 'ZONE_CHAIN = "job:zone"' in src
    zone = (WEB_JS_DIR / "datazone.js").read_text(encoding="utf-8")
    assert "window.Intent.chained(cfg.chainKey, send)" in zone, "존 발신이 체인을 타지 않습니다."
    # 무변이 질의는 체인 밖 — 응답이 늦는 질의 하나가 이후 모든 변이를 막지 않게.
    assert "ZONE_QUERIES" in zone and '"filter_panel"' in zone
    assert "Bridge.call(SCREEN" not in zone.split("function call(", 1)[1].split("}", 1)[1], (
        "존 발신 중 통로를 우회하는 호출이 남아 있습니다."
    )
    # 열기 왕복 중 화면 이탈 — 전역 면이 남의 화면 위에 뜨지 않게 열지 않고 초안을 거둔다.
    open_fn = src.split("function openJobDataSheet", 1)[1].split("\n  }", 1)[0]
    assert 'classList.contains("on")' in open_fn, (
        "열기 왕복 중 화면 이탈을 확인하지 않습니다."
    )
    # 결과 강등 판정은 표의 선택 표지가 아니라 Python 이 낸 커밋 지문을 쓴다(리뷰 1R P1).
    key = src.split("function sessionKey", 1)[1].split("\n  }", 1)[0]
    assert "selection_key" in key and ".selected" not in key, (
        "세션 지문이 표의 선택 표지에서 파생됩니다 — 초안이 결과를 강등시킵니다."
    )
    # 축 왕복도 **같은 체인**을 탄다(리뷰 1R P2·3R P1) — 체인 키는 상태 단위이지 위젯 단위가
    # 아니다. 축만 따로 세우면 취소가 먼저 초안을 지우고 늦은 축 변경이 커밋에 착지한다.
    order_fn = src.split("async function onOrderChange", 1)[1].split("\n  }", 1)[0]
    assert "Intent.chained(ZONE_CHAIN" in order_fn, "표시순서가 존 체인 밖에서 발신됩니다."
    assert "job:view_order" not in src, "축 전용 체인 키가 남아 있습니다(두 줄 = 순서 미보장)."
    sheet = (WEB_JS_DIR / "surface_sheet.js").read_text(encoding="utf-8")
    assert "beforeClose" in sheet, "펼침 면이 이탈 가드를 Modal 로 넘기지 않습니다."


def test_job_document_browser_surface_contract():
    """슬라이스 3 정적 계약 — 문서 탐색 면은 `job` 화면의 **하위 화면**이고 판정은 Python 소유.

    별 라우트를 만들지 않는다(§18.6: 상단 내비게이션은 계속 「문서 만들기」 활성) —
    시트 루트·탭·검색·행 호스트가 실재하고, JS 는 목록을 자체 필터하지 않는다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    for dom_id in ("jobBrowseSheet", "jobBrowseTabs", "jobBrowseQuery", "jobBrowseRows",
                   "jobBrowseNote", "jobBrowseClose"):
        assert f'id="{dom_id}"' in html, f"문서 탐색 면 요소 누락: {dom_id}"
    # 라우팅 화면은 다섯 개 그대로다 — 탐색은 시트라 SCREEN·컨트롤러가 늘지 않는다.
    assert 'id="scr-browse"' not in html and "scr-documents" not in html
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert "browse_tab" in src and "browse_query" in src, "탐색 액션 배선이 없습니다."
    assert "data-browse-pick" in src, "탐색 행 선택(명시 사건) 배선이 없습니다."
    # 재렌더를 가로지르는 포커스 계약(1R P2): 탭·행·출구에 안정 id 가 있고, 선택 뒤 착지는
    # Preserve 복원 **뒤에** 일어난다(안쪽이면 복원이 덮어써 탐색 면 컨트롤에 갇힌다).
    for token in ('id="jobBrowseTab-', 'id="jobBrowseRow-', 'id="jobBrowseOpen"'):
        assert token in src, f"탐색 면 안정 id 누락: {token}"
    # 포커스 착지는 **예약이 아니라** 닫은 직후 실 DOM 조회다(3R P2): 예약 방식은 왕복 순서에
    # 의존해 렌더보다 늦고, 남은 예약이 무관한 뒤 렌더를 흔들었다.
    assert "function focusAfterPick(" in src, "선택 후 포커스 착지가 없습니다."
    # 단순 닫기의 복귀도 노드 보관이 아니라 닫힘 시점 재조회다(6R P2 — 면 안 재렌더가
    # 붙잡아 둔 출구를 끊으면 Modal 은 복귀를 건너뛰고 포커스가 숨은 면에 남는다).
    assert "returnFocus: null" in src and "onClose:" in src, (
        "탐색 면 닫기 복귀가 보관 노드에 묶여 있습니다."
    )
    # 착지 결정은 닫힘 1지점에서만(사유 플래그) — 선택 경로가 따로 focus 하면 전이 종료 뒤
    # onClose 가 덮어써 두 착지가 경합한다.
    assert "browsePickedName" in src, "닫힘 사유 표식이 없습니다(착지 경합)."
    # 큐에 선 선택은 그 사이 면이 닫히면 무효다(P2): 취소한 전환이 뒤늦게 일어나고 표식이
    # 남아 다음 닫기의 착지까지 오염시킨다. 개폐 세대로 자기 것이 아닌 큐를 접는다.
    assert "browseOpenGen" in src and "gen !== browseOpenGen" in src, (
        "탐색 선택 큐의 개폐 세대 가드가 없습니다."
    )
    # 정의 1 + 호출 1 = 2 (호출이 늘면 닫힘 1지점 계약이 깨진 것)
    assert src.count("focusAfterPick(") == 2, "착지 호출이 닫힘 1지점 밖에도 있습니다."
    # 타이핑 중 스냅샷이 검색 입력을 덮지 않는다(4R P2 — 데이터 존과 같은 규칙).
    assert 'document.activeElement !== q' in src, "탐색 검색이 왕복 경합에 입력을 덮습니다."
    assert "pendingFocus" not in src, "예약 포커스 기제가 남아 있습니다(유령 착지)."
    # 선택 경로는 닫기까지만 하고 착지는 onClose 가 한다(아래 1지점 계약).
    # 생성 중 잠금(2R P2): 탐색 면은 오버레이 루트라 `#scr-job` 질의에 안 걸린다 —
    # setBusy 가 그 루트도 훑고, 출구·탭·행이 busy-lock 을 달아야 한다. ⤢ 펼침 면 2종도
    # 같은 자격이다(F3): 실 DOM 이동이라 잠글 요소가 면 안으로 **옮겨가** 화면 질의에서 빠진다.
    busy_roots = src.split("function setBusy", 1)[1].split("forEach", 1)[0]
    for root in ("jobBrowseSheet", "dataPickerModal", "dataSheet", "jobConfirmSheet"):
        assert f'$("{root}")' in busy_roots, f"setBusy 가 {root} 을(를) 잠그지 않습니다."
    assert src.count("data-busy-lock data-browse") == 3, (
        "탐색 면 출구·탭·행의 busy-lock 표식이 빠졌습니다."
    )
    # 검색·분류를 JS 가 재계산하지 않는다(RC-23 동형 — 판정은 Python 이 지금).
    browse = src.split("function renderBrowse")[1][:2200]
    for banned in ("filter(", "toLowerCase", "includes("):
        assert banned not in browse, f"탐색 렌더가 자체 필터를 합니다: {banned!r}"


def test_job_candidate_ranking_surface_contract():
    """슬라이스 2 정적 계약 — 순위 카드·별 토글·추천 표지·「외 N건」 고지 배선.

    판정·순위는 Python 소유라 JS 는 **받은 순서를 그대로** 그린다(정렬 재구현 금지).
    """
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert "data-fav" in src and "toggle_favorite" in src, "즐겨찾기 토글 배선이 없습니다."
    # 도달성(리뷰 2R P2 → F2 PR-B 이사): 카드 별은 상위 5장뿐이라 순위 밖 작업의 승격 경로는
    # **절단되지 않는 표면**이 져야 한다. 그 표면이던 좌 목록 ⋮ 메뉴가 죽었으므로(지도 §10.9)
    # 이제 「문서 작업」 라이브러리 **행**의 별이 그 자리다(§19.6: 행 선택 버튼 밖 형제).
    lib = (WEB_JS_DIR / "screens" / "library.js").read_text(encoding="utf-8")
    assert 'class="lib-fav" data-fav=' in lib, (
        "라이브러리 행에 즐겨찾기 별이 없습니다 — 순위 밖 승격 도달성이 끊깁니다(§8.4 2행)."
    )
    assert src.count("function toggleFavorite(") == 1, "즐겨찾기 전이 몸통이 둘입니다."
    # 왕복 중 두 번째 클릭이 의도를 뒤집으려면 다음 값을 DOM 이 아니라 미결 의도에서
    # 계산해야 하고(3R P2 — 멱등 재지정이 "껐다"를 삼키는 창), 쓰기 자체도 클릭 순서로
    # 직렬화돼야 한다(4R P2 — pywebview 는 호출마다 별도 스레드라 동시 발신이면 나중 클릭의
    # 쓰기가 먼저 잠금을 잡아 반대 상태가 영속될 수 있다).
    #
    # **기제는 공용 몸통(js/intent.js)이 소유한다**(재작성 F2 리뷰 3R 근본 조치): 라이브러리가
    # 같은 별을 새로 그리며 기제 없이 DOM 값만 보내 같은 결함류가 표면을 넘어 재발했다.
    # 그래서 가드도 몸통 하나를 보고, 두 소비 표면이 그것을 쓰는지 함께 본다.
    intent = (WEB_JS_DIR / "intent.js").read_text(encoding="utf-8")
    assert "function chained(" in intent and "CALL_CHAINS" in intent, "호출 직렬화 몸통이 없습니다."
    assert "function createFavorite(" in intent and "function pending(" in intent, (
        "즐겨찾기 미결 의도 직렬화가 공용 몸통에 없습니다."
    )
    assert 'chained("favorite"' in intent, "즐겨찾기 쓰기가 체인을 타지 않습니다."
    # 저장되는 링은 **절대 reject 하지 않는다**(5R): 실패한 promise 가 체인에 남으면 이후
    # 같은 키의 모든 호출이 거기 붙어 영영 실행되지 않는다. 실행 성질은 실앱 프로브가 본다.
    chain = intent[intent.index("function chained("):intent.index("const FAV_PENDING")]
    assert "result.catch(() => {})" in chain, "저장 링이 실패를 흡수하지 않습니다(5R)."
    assert "return result;" in chain, "호출자에게 실패를 전하지 않습니다 — 되돌리기가 죽습니다."
    for consumer in ("screens/job.js", "screens/library.js"):
        text = (WEB_JS_DIR / consumer).read_text(encoding="utf-8")
        assert "Intent.createFavorite(" in text, (
            f"{consumer} 가 즐겨찾기 기제를 공용 몸통에서 받지 않습니다 — 두 벌이면 또 갈린다."
        )
        assert "FAV_PENDING" not in text, f"{consumer} 에 손짠 의도 큐가 남아 있습니다."
    # 미결 의도 판독(`pending`)의 소비처였던 좌 목록 ⋮ 메뉴 문안은 표면과 함께 죽었다
    # (F2 PR-B) — 별은 두 표면 모두 aria-pressed 를 스냅샷에서 받으므로 「이 클릭이 할 일」을
    # 문장으로 말할 자리가 없다. 기제는 몸통에 남겨 둔다: 다음 표면이 다시 손으로 짜지 않게.
    assert "function pending(" in intent, "미결 의도 판독이 공용 몸통에서 사라졌습니다."
    assert src.count('Intent.chained("browse"') == 3, (
        "탐색 탭·검색·선택이 같은 체인을 타지 않습니다 — 늦은 옛 응답이 새 결과·선택을 되돌린다."
    )
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
    assert "c.sections" in src and "sections.length > 1" in src, (
        "방식 구획이 Python 판정(sections)을 소비하지 않습니다."
    )
    assert "c.more" in src, "순위 밖 후보 수(외 N건) 고지가 없습니다 — 조용한 절단 금지."
    # 확인 필요 목록은 탐색 면으로 이사했다 — 후보 줄엔 수치 + 출구만 남는다(슬라이스 3).
    assert "c.needs_count" in src and "data-browse-open" in src, (
        "확인 필요 수치·문서 탐색 출구가 후보 줄에 없습니다."
    )
    assert "cand-sug" in src, "추천 표지가 없습니다(§18.3 개정)."
    # JS 가 순위를 재계산하지 않는다(RC-23 동형 — 이중 진실 금지).
    for banned in ("favorited_at <", "sort(", "localeCompare"):
        assert banned not in src.split("renderCandidates")[1][:2000], (
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
    assert 'src="js/theme.js"' in index, "theme.js 가 index.html 에 로드되지 않았습니다(다크모드 토글)."
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
    assert "Bridge.setTheme" in theme_js, (
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
    app_py = Path(__file__).resolve().parents[1] / "src" / "hwpxfiller" / "webapp" / "app.py"
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
    app_py = (WEB_INDEX.parents[1] / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    app_js = (WEB_JS_DIR / "app.js").read_text(encoding="utf-8")
    editor_js = (WEB_JS_DIR / "screens" / "editor.js").read_text(encoding="utf-8")
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")

    assert "window.events.closing += frontend._handle_window_closing" in app_py
    assert "AppCloseGuard" in app_js and "confirm_window_close" in app_js
    assert 'id="editorBack"' in html and 'editorBack' in editor_js
    assert 'data-act="cancel-new"' in editor_js
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
    assert editor_js.count("Bridge.call(SCREEN") == 1, (
        "편집기 왕복이 체인을 우회합니다 — `sendEdit` 하나만 Bridge.call(SCREEN 을 씁니다."
    )
    assert "window.Intent.chained(EDIT_CHAIN" in editor_js, (
        "편집기 입력 변이가 체인에 서지 않습니다 — 도착 순서가 보장되지 않습니다."
    )
    # **확인 왕복도 정산 뒤에 연다**(§2.17 2R P2): 버리기가 blur 전에 눌릴 수 있게 된 뒤로
    # (1R), 정산 없이 모달을 열면 큐에 든 `set_*` 이 모달 뒤에 도착해 `#editor-foot` 을 갈아
    # 끼우고 저장해 둔 트리거가 분리된다 — 취소가 화면 루트로 떨어진다. 정산은 새 기제를
    # 만들지 않고 goto·leave 와 **같은** `flushPendingEdits` 를 쓴다.
    discard = editor_js[editor_js.index('case "discard-patch"'):]
    discard = discard[:discard.index('sendEdit("discard_patch"')]
    assert "await flushPendingEdits()" in discard, (
        "버리기가 대기 편집을 정산하지 않고 확인을 엽니다 — 큐의 발신이 모달 뒤에 도착해"
        " 트리거가 분리되고 취소 착지가 어긋납니다(2R P2)."
    )
    assert discard.index("await flushPendingEdits()") < discard.index("Modal.confirm"), (
        "정산이 확인보다 **뒤에** 섭니다 — 순서가 뒤집히면 정산의 존재가 무의미합니다."
    )
    assert 'querySelector(\'#editor-foot [data-act="discard-patch"]\')' in discard, (
        "정산 뒤 트리거를 다시 잡지 않습니다 — 정산이 부른 재구성으로 옛 참조는 분리됩니다."
    )
    assert "returnFocus: trigger" in discard, (
        "확인이 재획득한 트리거가 아니라 옛 참조로 돌아갑니다."
    )
    # 복귀는 **규칙을 다시 읽은 뒤** 목적 화면을 노출한다(8R P1 근본 조치). 5R 은 이 순서를
    # 미리보기 복귀에만 세웠고, 그래서 데이터·결과 복귀는 옛 규칙을 든 화면을 내보인 채
    # 「만들기」를 열어 뒀다 — 순서는 **모든** 복귀가 지나는 착지 절차 한 자리에 산다.
    land = editor_js[editor_js.index("async function landOn("):]
    land = land[:land.index("\n  }") + 4]
    assert land.index("await window.Nav.refresh(") < land.index("window.Nav.go("), (
        "착지가 재적재를 기다리지 않고 화면을 노출합니다 — 편집 전 규칙으로 실행됩니다(8R P1)."
    )
    assert "refreshed: true" in land, (
        "착지가 전환에 기(既)대기를 알리지 않습니다 — 왕복이 두 벌이 되고 늦은 쪽이 면을 흔듭니다."
    )
    # 편집기를 나가는 길은 **모두** 그 절차를 지난다 — Nav.go 직행이 하나라도 남으면
    # 그 경로만 재적재를 건너뛰는 비대칭이 다시 생긴다(F7 이 네 라운드에 걸쳐 겪은 자리).
    assert editor_js.count("window.Nav.go(") == 1, (
        "편집기에 Nav.go 직행 경로가 남았습니다 — 착지 절차(landOn) 하나만 전환해야 합니다."
    )
    # **초점도 되돌린다**(9R P2) — 화면만 바꾸면 초점이 방금 숨겨진 편집기 back 버튼에 남아
    # 키보드 사용자가 보이는 초점 없이 착지한다. 되돌릴 자리를 아는 곳은 진입 seam 하나이고
    # (복귀처 넷에 focus_target 을 심으면 새 진입처가 조용히 빠진다), 되돌림 **규칙**은
    # 모달이 이미 가진 것을 쓴다(분리·비활성 요소 판정을 두 번 쓰지 않는다).
    assert "window.EditorEntry.restoreEntryFocus()" in land, (
        "이탈이 초점을 되돌리지 않습니다 — 숨은 요소에 초점이 남습니다(9R P2)."
    )
    entry_js = (WEB_JS_DIR / "editor_entry.js").read_text(encoding="utf-8")
    assert entry_js.count("rememberEntryFocus()") == 3, (
        "진입 seam 이 띄운 자리를 기억하지 않습니다 — 정의 1 + 두 진입(newDraft·openGuarded)."
    )
    assert "window.Modal.restoreFocus(" in entry_js, (
        "초점 되돌림 규칙이 두 벌입니다 — 모달의 restoreFocus 를 재사용해야 합니다."
    )
    modal_js = (WEB_JS_DIR / "modal.js").read_text(encoding="utf-8")
    assert re.search(r"window\.Modal = \{[^}]*\brestoreFocus\b", modal_js), (
        "Modal.restoreFocus 가 내보내지지 않았습니다 — 이탈이 그 규칙을 쓸 수 없습니다."
    )
    for guard in ("async function leaveTo(", "async function gotoSection("):
        body = editor_js[editor_js.index(guard):]
        body = body[:body.index("\n  }") + 4]
        assert "await flushPendingEdits()" in body, (
            f"{guard} 가 대기 중 입력을 정산하지 않고 판정합니다(4R P2)."
        )
    # 탭 가드의 「버리고 이동」은 **모달이 말한 자리만** 되돌린다(2R P2).
    assert 'discard_patch", { section: r.section }' in editor_js, (
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
    app_js = WEB_JS_DIR / "app.js"
    src = app_js.read_text(encoding="utf-8")
    m = re.search(r'addEventListener\("unhandledrejection",[\s\S]*?\}\);', src)
    assert m, f"{app_js} 에 unhandledrejection 백스톱이 없습니다 — 조용한 무반응 결함류 재개방."
    block = m.group(0)
    assert "window.alert" in block, f"{app_js} 백스톱이 alert 로 재진술하지 않습니다."
    assert "preventDefault" in block, f"{app_js} 백스톱이 rejection 을 handled 처리하지 않습니다."


def test_editor_is_an_immersive_screen_with_one_exit():
    """편집기 = 몰입 표면(재작성 F7 PR-A, 지도 §10.13 사용자 확정 2행).

    편집 컨테이너 3종(editor-steps/-body/-foot)은 자기 화면(#scr-editor)에 살고, 「작업」
    화면의 편집 호스트(#jobEditHost)와 두 모드 배선은 **사망**했다(재유입 가드 — 삭제는
    의무를 상속한다). 요지는 미감이 아니라 가드다: 편집이 「문서 만들기」 안의 한 모드면
    상단 탭·화면 안 컨트롤이 전부 처분 미확정 이탈구가 되고 가드의 완전성이 표면 수에
    비례한다. 출구가 하나여야 patch 3택이 한 곳에서 끝난다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    editor_sec = html.split('id="scr-editor"')[1].split('id="scr-workbench"')[0]
    for cid in ("editorBack", "editorName", "editorSaveState", "editorContext",
                "editor-steps", "editor-body", "editor-foot"):
        assert cid in editor_sec, f"{cid} 가 편집기 화면에 없습니다."
    # 구 거처 재유입 가드 — 편집 호스트·두 모드 출구는 승계처가 섰으므로 되살아나면 안 된다.
    assert 'id="jobEditHost"' not in html, "구 편집 호스트가 부활했습니다(F7 판정 N)."
    assert 'id="jobEditExit"' not in html and 'id="jobEditExitNote"' not in html, (
        "구 편집 모드 출구·복귀 고지가 부활했습니다 — 그 소임은 patch 처분이 승계했습니다."
    )
    # 셸을 덮는다 — nav 은닉은 CSS 가, 편집 중 이탈은 Nav 위임이 진다.
    app_js = (WEB_JS_DIR / "app.js").read_text(encoding="utf-8")
    assert "editor-open" in app_js and "body.editor-open .nav" in WEB_CSS, (
        "편집기가 상단 2탭을 덮지 않습니다 — 화면 전환구가 살아 있으면 처분 미확정 이탈구다."
    )
    # 이탈 위임은 **몰입 표면 목록**으로 일반화됐다(F6 — 작업대 합류). 특례를 화면마다
    # 늘리면 가드의 완전성이 표면 수에 비례한다(이 표면이 존재하는 바로 그 이유). 그래서
    # 목록에 등록됐는지와, 목록이 leaveTo 로 위임하는지를 함께 센다.
    assert "IMMERSIVE" in app_js and "owner.leaveTo" in app_js, (
        "Nav 가 몰입 표면의 이탈 가드를 지나지 않습니다 — 프로그램적 이동이 처분을 건너뜁니다."
    )
    for owner in ("EditorScreen", "WorkbenchScreen"):
        assert owner in app_js, f"{owner} 이 몰입 표면 목록에 없습니다."
    # 진입 흐름은 EditorEntry 단일 정의(land/newDraft/openGuarded — 축자 복붙=드리프트 표면).
    entry_src = (WEB_JS_DIR / "editor_entry.js").read_text(encoding="utf-8")
    for fn in ("function land", "function newDraft", "function openGuarded"):
        assert fn in entry_src, f"editor_entry.js 의 단일 정의({fn})가 사라졌습니다."
    assert 'window.Nav.go("editor"' in entry_src, "편집 진입이 편집기 화면으로 착지하지 않습니다."
    for fname, needle in (
        ("screens/library.js", "EditorEntry.newDraft"),
        ("screens/library.js", "EditorEntry.openGuarded"),
        # (template.js 의 EditorEntry.land 소비는 화면 사망(F8)으로 은퇴 — 편집기 안 선택은
        #  이미 편집기 화면이라 착지 seam 이 필요 없다.)
        ("screens/job.js", "EditorEntry.openGuarded"),
    ):
        src = (WEB_JS_DIR / fname).read_text(encoding="utf-8")
        assert needle in src, f"{fname} 가 진입 단일 출처({needle})를 쓰지 않습니다."
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert "EditorEntry.newDraft" not in job_js, (
        "「문서 만들기」에 새 작업 진입이 되살아났습니다 — 승계처는 라이브러리 `＋ 새 작업`입니다."
    )
    assert "showEditMode" not in job_js and "exitEditToRun" not in job_js, (
        "job.js 두 모드 배선이 되살아났습니다 — 편집은 자기 화면으로 나갔습니다(F7)."
    )
    editor_js = (WEB_JS_DIR / "screens" / "editor.js").read_text(encoding="utf-8")
    assert '$("scr-editor")' in editor_js, "editor.js 위임 루트가 몰입 표면으로 이사하지 않았습니다."


def test_editor_folder_import_is_wired_without_session_confirm():
    """「폴더에서 가져오기…」(#339 · U2 §2.16 narrow) 배선 — 4자리가 한 계약으로 산다.

    ①행동 줄 버튼(data-act="import-folder") ②직접 브리지 메서드(importTemplatesFolder →
    import_templates_folder — action registry 밖이라 payload 검증은 메서드 본문 소유)
    ③핸들러는 재진술 확인(Modal.confirm) 뒤에만 확정 실행을 부른다 ④**채택하지 않으므로**
    새-세션 확인(confirmNewSessionIfUnsaved)이 이 경로에 서면 안 된다 — 세션 무변경 동사에
    세션 파괴 확인이 붙으면 확인이 거짓말이 된다.
    """
    editor = (WEB_JS_DIR / "screens" / "editor.js").read_text(encoding="utf-8")
    bridge = (WEB_JS_DIR / "bridge.js").read_text(encoding="utf-8")
    app_py = (WEB_INDEX.parents[1] / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(
        encoding="utf-8"
    )
    assert 'data-act="import-folder"' in editor, "폴더 가져오기 버튼이 행동 줄에 없습니다."
    start = editor.index('case "import-folder"')
    block = editor[start:editor.index('case "', start + 10)]
    assert "importTemplatesFolder" in block, "핸들러가 직접 브리지 메서드를 부르지 않습니다."
    # 호출 형태로 잰다 — 주석의 언급(왜 안 거는지의 선언)은 결함이 아니다.
    assert "confirmNewSessionIfUnsaved()" not in block, (
        "채택 없는 일괄 등록에 새-세션 확인이 붙었습니다 — 세션 무변경 동사입니다(#339)."
    )
    assert block.index("Modal.confirm") < block.index("importTemplatesFolder(r.folder, true, r.files)"), (
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
    assert "if (folderImportInFlight) break;" in block, (
        "폴더 가져오기에 in-flight 가드가 없습니다 — 느린 드라이브에서 재클릭이 두 번째"
        " 스캔/확정 모달/배치를 시작합니다(PR #355 2R)."
    )
    assert block.index("folderImportInFlight = true") < block.index("importTemplatesFolder()"), (
        "가드가 첫 브리지 발신보다 늦게 섭니다 — 스캔·확정 모달이 가드 밖입니다."
    )
    assert "finally" in block and "folderImportInFlight = false" in block, (
        "in-flight 해제가 finally 에 없습니다 — 취소·실패 출구에서 버튼이 영구히 잠깁니다."
    )
    tpl_py = (WEB_INDEX.parents[1] / "src" / "hwpxfiller" / "webapp"
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
    job = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    lib = (WEB_JS_DIR / "screens" / "library.js").read_text(encoding="utf-8")
    bridge = (WEB_JS_DIR / "bridge.js").read_text(encoding="utf-8")
    entry = (WEB_JS_DIR / "editor_entry.js").read_text(encoding="utf-8")
    assert "openJobInEditor(name, context)" in bridge, (
        "브리지가 진입 문맥을 나르지 않습니다 — 문맥 없는 편집기는 나갈 곳이 없다."
    )
    # **단일 정의 seam 은 인자까지 단일이어야 한다**(1R P1 의 영구 가드): 호출자가 문맥을
    # 실어도 공용 seam 이 인자를 흘리면 모든 진입이 기본 자발적 진입으로 떨어져 배너·복귀처가
    # 통째로 사라진다. 종전 계약은 "호출자가 무엇을 싣는가"만 보고 "seam 이 흘려보내는가"를
    # 보지 않아 그 드리프트를 통과시켰다.
    assert "async function openGuarded(name, context)" in entry, (
        "공용 진입 seam 이 문맥 인자를 받지 않습니다 — 호출자가 실은 문맥이 버려집니다."
    )
    assert "Bridge.openJobInEditor(name, context" in entry, (
        "공용 진입 seam 이 문맥을 백엔드로 흘려보내지 않습니다."
    )
    for reason in ("document_browser_repair", "preview_result", "output_result", "run_failure"):
        assert reason in job, f"「문서 만들기」의 편집 진입이 사유({reason})를 싣지 않습니다."
    assert 'entry_reason: "library"' in lib, "라이브러리 편집 진입이 사유를 싣지 않습니다."
    # F4 가 남긴 빚의 회수 — 파일 이름 규칙 수리는 이제 전용 탭으로 곧장 착지한다.
    assert 'section: "filename"' in job, (
        "결과의 파일 이름 수리가 파일 이름 탭으로 착지하지 않습니다(F7 이 승격한 자리)."
    )
    # **약속한 복귀 상태는 실제로 되돌린다**(1R P2): 「미리보기로 돌아가기」가 보통의
    # 「문서 만들기」로 데려다 놓으면 라벨이 거짓이 된다. 보낸 표면이 세운 `reopen_drawer` 를
    # 복귀가 소비하고, 여는 절차는 그 화면의 seam 하나가 소유한다(열기 규율 두 벌 금지).
    editor = (WEB_JS_DIR / "screens" / "editor.js").read_text(encoding="utf-8")
    assert "reopen_drawer" in job and "reopen_drawer" in editor, (
        "미리보기 복귀 상태가 세워지기만 하고 소비되지 않습니다 — 라벨이 약속한 자리와"
        " 실제 착지가 다릅니다."
    )
    assert "JobScreen.openPreview" in editor and "openPreview," in job, (
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
    job = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    editor = (WEB_JS_DIR / "screens" / "editor.js").read_text(encoding="utf-8")
    # 발신 쪽 — 행 버튼·파일 이름 버튼·target 두 형태·preview_index 생산.
    assert 'data-act="preview-fix"' in job, "행별 「수정」 버튼이 없습니다."
    assert 'id="previewFixFilename"' in html, "파일 이름 「수정」 버튼(정적 DOM)이 없습니다."
    assert '"binding/" + field' in job and '"filename/filenamePattern"' in job, (
        "deep-link target 두 형태(계약 §8)가 발신되지 않습니다."
    )
    assert "preview_index: at" in job, "복귀 자리(preview_index)를 싣지 않습니다."
    # `at` 은 Modal.close(→ preview_close 가 pos 를 리셋) **전에** 읽어야 한다 — 순서가
    # 뒤집히면 복귀가 늘 첫 행으로 선다(발신 순서 규약의 이 표면 표본).
    fix_body = job[job.index("async function previewFix"):job.index("function openEditForRepair")]
    assert fix_body.index(".pos") < fix_body.index('Modal.close("previewModal")'), (
        "previewFix 가 드로어를 닫은 뒤 pos 를 읽습니다 — 리셋된 0 이 실려 갑니다."
    )
    # 수신 쪽 — 편집기 조준(행 data-field·aimAt)과 복귀 소비(preview_index·focusTarget).
    assert "aimAt" in editor and 'tr[data-field="' in editor.replace("${CSS.escape(field)}", '"'), (
        "편집기가 target 행을 겨누지 않습니다(탭 착지만 하고 행을 버립니다)."
    )
    assert "ret.preview_index" in editor and "focusTarget: ctx.target" in editor, (
        "복귀가 같은 자리·같은 행(§10.14.3)을 소비하지 않습니다."
    )
    assert "focusPreviewTarget" in job, "재개 드로어가 복귀 행에 초점을 세우지 않습니다."
    # 배제 유지(판정 E) — 작업대는 편집기로 나가는 deep-link 를 갖지 않는다.
    wb = (WEB_JS_DIR / "screens" / "workbench.js").read_text(encoding="utf-8")
    assert "openJobInEditor" not in wb and "EditorEntry" not in wb, (
        "작업대가 편집기 진입을 얻었습니다 — 판정 E(배제 선언)를 먼저 뒤집어야 합니다."
    )


def test_use_in_job_goes_straight_to_the_run_surface():
    """「문서 만들기에서 사용」은 실행 표면에 착지한다(F2 PR-B 의 계약, F7 에서 단순해짐).

    편집기가 자기 화면으로 나가면서 「편집 모드면 되돌린다」는 정산 자체가 불필요해졌다 —
    이 화면이 보이는 동안 편집기는 열려 있지 않다(몰입 표면은 셸을 덮는다). 승계처가 선
    뒤에도 옛 정산을 남겨 두면 죽은 배선이 계약처럼 읽힌다.
    """
    lib = (WEB_JS_DIR / "screens" / "library.js").read_text(encoding="utf-8")
    job = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    use = lib[lib.index('Bridge.call(JOB, "prefer_work"'):]
    use = use[:use.index("window.Nav.go(JOB);") + len("window.Nav.go(JOB);")]
    assert "window.Nav.go(JOB);" in use, "「문서 만들기에서 사용」이 실행 화면으로 가지 않습니다."
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
    src = (WEB_JS_DIR / "screens" / "library.js").read_text(encoding="utf-8")
    assert "지금 기준" in src, "그룹 확인 수치가 관측으로 표기되지 않았습니다(#149)."
    assert "해산 시점의 소속 작업 전부" in src, "해산 확인이 이동 집합 규칙을 말하지 않습니다(#149)."
    assert src.count("seen: r.count") == 2, (
        "확인 때 본 수를 확정 호출에 실어 보내지 않습니다 — 어긋남 판정(Python)이 불가(#149)."
    )
    assert "drift_note" in src, "실제 이동 건수의 어긋남 고지를 소비하지 않습니다(#149)."


def test_editor_overwrite_confirm_echoes_the_text_it_showed():
    """에디터 덮어쓰기 확정이 **본 문안을 되돌려** 준다(#149).

    Python 이 쓰기 잠금 안에서 문안을 다시 만들어 대조하고, 달라졌으면 새 문안으로 다시 묻는다
    — JS 는 무엇을 보여 줬는지만 실어 보낸다(판정은 Python 이 지금, JS 는 문안만).
    """
    src = (WEB_JS_DIR / "screens" / "editor.js").read_text(encoding="utf-8")
    assert "confirmed_overwrite_text: res.overwrite_text" in src, (
        "확정 호출이 본 문안을 되돌리지 않습니다 — 검증 불가한 확인이 됩니다(#149)."
    )


# (test_draft_has_return_path_to_volatile_session ·
#  test_draft_saved_source_has_fork_escape_hatch · test_draft_live_edit_refreshes_source_bar
#  삭제 — 대상(draft.js 좌 목록·draftsession.js 원문바·휘발 세션)이 화면과 함께 사망,
#  F6 PR-B. TXT 원문 편집의 승계 출구는 편집기 TXT 밴드·검토는 작업대다.)


def test_job_preview_drawer_surface_contract():
    """재작성 F5 정적 계약(지도 §10.12) — 드로어의 소유·개폐 순서·판정 단일 출처.

    ①골격은 index.html 정적 DOM 이다(동적 생성은 role/aria 계약의 사각을 만든다 — 구
    `pool_picker.js` K12 교훈) ②열림·자리는 **Python 소유**라 웹은 방향만 보낸다(판정 M)
    ③성사 뒤에만 연다 ④승인은 명시 사건 하나이고 생성과 다른 사건이다(§13-4).
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    for element in (
        "previewModal", "previewTitle", "previewPos", "previewPrev", "previewNext",
        "previewRows", "previewEvidence", "previewEvidenceRows", "previewEvidenceNote",
        "previewEvidenceReason",
        "previewFilename", "previewApprove", "previewClose",
        "previewEdit", "previewEmpty", "jobPreviewOpen", "jobReviewFlag",
    ):
        assert f'id="{element}"' in html, f"미리보기 드로어 노드가 없습니다: {element}"
    # 「적용 범위」 축은 없다(U2 §2.3) — runOverrides 기각·사망으로 값이 하나뿐인 축이 됐고,
    # 고를 수 없는 선택지를 암시하는 자리만 남았다. 페이로드 쪽 부재는 test_webapp_job 소관.
    assert 'id="previewScope"' not in html, "적용 범위 축이 재유입됐습니다."
    # 경계는 다음 모달(libraryMoveModal) — 구 경계(붙여넣기 모달)는 「기안」과 함께 사망(F6 PR-B).
    drawer = html.split('id="previewModal"', 1)[1].split('id="libraryMoveModal"', 1)[0]
    assert 'role="dialog"' in drawer and 'aria-modal="true"' in drawer, (
        "드로어에 dialog 역할·모달 표기가 없습니다(정적 DOM 이 소유하는 계약)."
    )
    assert 'aria-label="이전 문서"' in drawer and 'aria-label="다음 문서"' in drawer, (
        "레코드 이동 버튼에 접근 가능한 이름이 없습니다(‹ › 만으로는 무엇의 이동인지 모른다)."
    )

    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    # 자리는 서수이고 Python 이 소유한다 — 웹이 index 를 되돌려주면 그 사이의 데이터 교체·
    # 표시순서 변경이 남의 행을 고른다(F4 판정 F·F3 판정 A 와 같은 뿌리).
    assert '"preview_move", { delta: -1 }' in src and '"preview_move", { delta: 1 }' in src, (
        "레코드 이동이 방향이 아니라 좌표를 보냅니다(판정 M)."
    )
    assert "preview_pos" not in src and "previewIndex" not in src, (
        "웹이 미리보기 자리를 들고 있습니다 — 상태의 주체는 Python 입니다."
    )
    # 성사 뒤에만 연다(§9.3 4행 상속).
    open_fn = src.split("async function openPreview", 1)[1].split("\n  }", 1)[0]
    assert open_fn.index('"preview_open"') < open_fn.index('Modal.open("previewModal"'), (
        "면을 먼저 열고 나서 성사를 묻습니다 — 거절되면 무엇을 미리보는 중인지 거짓이 됩니다."
    )
    assert "flushPendingEdits" in open_fn, (
        "열기가 대기 중 편집을 추월합니다 — 미리보는 범위가 사용자가 본 그것이 아닙니다."
    )
    # 승인은 명시 클릭 하나. 면을 여는 것이 승인이 아니다(§13-4).
    assert '"preview_approve"' in src
    assert 'Bridge.call(SCREEN, "preview_approve"' not in open_fn, (
        "면을 여는 경로가 승인을 발신합니다(생성 ≠ 승인)."
    )
    # 잠금 범위(§9.3 2행) — 오버레이 루트는 화면 루트 질의 밖이라 setBusy 가 따로 훑는다.
    busy_fn = src.split("function setBusy", 1)[1].split("\n  }", 1)[0]
    assert '$("previewModal")' in busy_fn, "생성 중 드로어가 잠기지 않습니다(오버레이 사각)."


def test_preview_button_states_are_decided_after_the_busy_restore():
    """실 창 프로브가 잡은 자리 — `setBusy` 는 렌더 말미에 `[data-busy-lock]` 을 **일괄
    복원**하므로, 그전에 끈 버튼은 되살아난다(`jobBtnPickFolder` 가 같은 이유로 거기 있다).

    미리보기 이동 버튼은 경계에서 멈추는 것이 계약인데(순환하지 않는다), 판정을
    `renderPreview` 에만 두면 마지막 건에서도 「다음」이 눌린다 — 정적 배선은 멀쩡해 보이고
    실물만 틀리는 결함류라 렌더 순서를 계약으로 못박는다.
    """
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    render_fn = src.split("function renderPreview", 1)[1].split("\n  }", 1)[0]
    for btn in ("previewPrev", "previewNext", "jobPreviewOpen"):
        assert f'$("{btn}").disabled' not in render_fn, (
            f"{btn} 가용성을 renderPreview 에서 정합니다 — setBusy 의 일괄 복원이 되살립니다."
        )
    busy_fn = src.split("function setBusy", 1)[1].split("\n  }", 1)[0]
    for btn in ("previewPrev", "previewNext", "jobPreviewOpen"):
        assert f'$("{btn}").disabled' in busy_fn, (
            f"{btn} 가용성이 렌더 말미 단일 지점에서 정해지지 않습니다."
        )


def test_job_screen_branches_the_output_surfaces_on_the_media_python_declared():
    """산출 재진술·거울·저장 폴더는 **매체 파생**이다(F6 판정 D · 리뷰 6R).

    TXT 작업은 파일을 만들지 않는다 — 「문서 N건 · 저장 폴더」도, 살아 있는 폴더 피커도,
    행을 다 고른 뒤에도 「행을 선택하면 …」이라고 말하는 거울도 전부 거짓이다. 분기의
    근거는 Python 이 낸 `run_action.key` 하나여야 한다: 표면이 확장자·매체를 다시 읽으면
    같은 판정이 두 곳에 산다.
    """
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert 'run_action.key === "workbench"' in job_js, (
        "매체 분기의 근거가 Python 이 낸 실행 행동 키가 아닙니다."
    )
    # 거울 존은 통째로 걷힌다(빈 상태 문안이 이행 불가능한 지시로 남지 않게).
    assert 'jobMirrorZone' in job_js and 'id="jobMirrorZone"' in WEB_INDEX.read_text(
        encoding="utf-8")
    # 저장 폴더 행·피커는 이 매체에 없는 축이다 — 피커 잠금은 setBusy 단일 지점이 진다.
    assert 'jobOutRow' in job_js
    picker = job_js.split('$("jobBtnPickFolder").disabled')[1].split(";")[0]
    assert "isCopyWork(LAST)" in picker, picker
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
    ("screens/workbench.js", "async function copyCard()", "Intent.settle(WB_CHAIN)"),
    ("screens/workbench.js", "async function saveRules()", "Intent.settle(WB_CHAIN)"),
    ("screens/workbench.js", "async function leaveTo(", "Intent.settle(WB_CHAIN)"),
    ("screens/job.js", "async function doGenerate(", "Intent.settle(ZONE_CHAIN)"),
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
                                         "Bridge.generate(") if tok in body),
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
    text = (WEB_JS_DIR / "screens" / "workbench.js").read_text(encoding="utf-8")
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
    src = Path(__file__).resolve().parents[1] / "src" / "hwpxfiller" / "webapp"
    job_py = (src / "screen_job.py").read_text(encoding="utf-8")
    tpl_py = (src / "screen_template.py").read_text(encoding="utf-8")
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    # ① 문서 만들기 후보 TXT 구획 빈 상태 — screen_job 이 내고 job.js 가 그린다.
    assert '"txt_note"' in job_py and "_txt_onboarding_note" in job_py
    assert "c.txt_note" in job_js
    # ② tpl TXT 밴드 고지는 화면과 함께 사망(F8 §10.17) — 생산이 되살아나면 소비 없는
    # 유령 페이로드다(「등록만 되고 배선 없는」 결함류의 역방향).
    assert 'txt["notice"]' not in tpl_py
