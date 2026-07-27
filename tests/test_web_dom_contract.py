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

WEB_INDEX = Path(__file__).resolve().parents[1] / "web" / "index.html"
WEB_CSS = Path(__file__).resolve().parents[1] / "web" / "css" / "app.css"
# web-diff(2판 diff 뷰어)는 별개 산출물이지만 강제색 대응은 web/ 와 짝 — 둘 다 가드한다.
WEB_DIFF_CSS = Path(__file__).resolve().parents[1] / "web-diff" / "css" / "app.css"
WEB_DIFF_INDEX = Path(__file__).resolve().parents[1] / "web-diff" / "index.html"

# 반응형 경계(#27): 창 최소폭(760)보다 넓은 이 경계에서 2판 레이아웃이 세로 적층으로 접혀야
# 최소 크기에서도 가로 오버플로 없이 쓸 수 있다. 경계나 접힘 규칙이 사라지면 회귀.
RESPONSIVE_BREAKPOINT_PX = 820

# 전체 스냅샷 재렌더가 포커스·캐럿·스크롤을 뭉개지 않도록 render() 를 Preserve.around 로 감싸는
# 화면들(#28). 어느 화면이 래핑을 조용히 떨구면 상호작용 유실 회귀 → 정적 가드로 차단.
WEB_JS_DIR = Path(__file__).resolve().parents[1] / "web" / "js"
# 렌더 래핑·데이터 피커 계약은 **표면을 소유한 파일**을 따라간다 — 화면 파일명과 1:1 이
# 아니다(기안 세션은 공용 팩토리 draftsession.js 소유, 「기안」 화면이 소비).
PRESERVE_WRAPPED_FILES = ("draftsession.js", "screens/editor.js", "screens/job.js")

# 살아있는 컴포넌트 갤러리(개발 전용) — 실 tokens.css+app.css 를 <link> 로 물어 드리프트 0.
GALLERY = Path(__file__).resolve().parents[1] / "docs" / "UI_GALLERY.html"

# 화면 루트 — 셸 라우터가 표시/숨김으로 전환하는 최상위 컨테이너(회귀 시 화면 소실).
SCREEN_ROOTS = (
    # 홈(scr-home)은 사망(재작성 F2 PR-A) — 저장된 작업을 찾는 자리는 「문서 작업」
    # 라이브러리(§19.6 browser+detail)가 잇는다.
    "scr-library", "scr-tpl",
    # 「데이터 관리」(scr-pool)는 사망(재작성 F1) — 등록 데이터의 목록·수명은 데이터 선택
    # 다이얼로그가 승계했다(PoolController 는 생존, 소비자만 바뀜).
    # 「작업」(R-flow · #90) — 유일 생성 표면(실행 화면=슬라이스 3 사망) + 편집 모드(작업
    # 에디터 별도 화면=슬라이스 5 사망, 결정 39 흡수 — 정의 surface 는 scr-job 내부).
    "scr-job",
    # 「기안」(R-info 3부 · #148) — TXT 작업-앵커. 구 「기안문 채우기」·「빠른 기안」을 흡수·삭제
    # (#148 슬라이스 6 — 레일 6→5).
    "scr-draft",
)

# 화면별 데이터 라벨은 반드시 고유 id 여야 한다(#27 dup-id 회귀 가드).
SCOPED_DATA_LABELS = ("draftDataLabel", "jobDataLabel")

# 상단 토바 탭(회귀 시 화면 소실·접근 이름 소실 → #27). run=슬라이스 3·editor=슬라이스 5
# 사망(흡수); 「기안」이 구 txt·quickdraft 를 흡수·삭제(#148 슬라이스 6); 「데이터 관리」는
# 데이터 선택 다이얼로그로 흡수·사망(F1); home 은 「문서 작업」 라이브러리로 사망(F2 PR-A).
# 좌 레일은 F2 PR-B 에서 상단 2탭으로 교체 — 계약 2탭(job·library) + 과도기 임시 2(draft·tpl).
NAV_SCREENS = ("library", "job", "draft", "tpl")
# 구분선 오른쪽 임시 항목 — 승계처가 서면(F6·F8) 죽는다. title 이 제거 예고를 진다(지도 §10.9 판정 B).
TEMP_NAV_SCREENS = ("draft", "tpl")

# 커스텀 모달 → aria-labelledby 가 가리켜야 할 제목 id(다이얼로그 시맨틱, #27/#28).
# sheetModal 은 다중 시트 확정 게이트(#33) — 같은 Modal 헬퍼·다이얼로그 계약을 공유한다.
MODAL_LABELLEDBY = {
    "txtEditModal": "txtEditTitle",  # 템플릿 관리의 「새 TXT」·편집(template.js) — 화면 아닌 관리 모달(생존)
    "pasteModal": "pasteTitle",  # 「기안」 붙여넣기(draftsession.js 공용 팩토리가 소비)
    "draftSaveTplModal": "draftSaveTplTitle",  # 「기안」 「템플릿으로 저장」 승격(#148 슬라이스 6, #135)
    "sheetModal": "sheetTitle",
    "poolRegModal": "poolRegTitle",  # 데이터 고정·등록(#26 #4 → F1 승계, 다이얼로그 위 스택)
    "dataPickerModal": "dataPickerTitle",  # 데이터 선택 통합 면(재작성 F1 — pool 화면 승계)
    # 「작업」 덮어쓰기 확인은 슬라이스 2(A-2-22)에서 공용 confirmModal(수치 합성 본문)로 이관 —
    # 전용 jobOverwriteModal DOM 폐기(아래 test_job_overwrite_uses_shared_confirm_modal 가드).
    "confirmModal": "confirmModalTitle",  # 네이티브 window.confirm 대체(#86) + 덮어쓰기 확인
    "promptModal": "promptModalTitle",  # 네이티브 window.prompt 대체(#86)
    "draftMapSheet": "draftMapSheetTitle",  # 기안 맞추기 펼침 면(#271)
    "dataSheet": "dataSheetTitle",  # 기안·작업 공용 데이터 펼침 면(#271/#272)
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


def test_transitional_tabs_announce_their_removal():
    """과도기 임시 탭(기안·템플릿 관리)은 구분선 오른쪽에 서고 title 이 제거를 예고해야 한다.

    지도 §10.9 판정 B: 아직 정상 동작하는 화면이라 상시 배너 대신 title 이 예고를 진다(없는
    소실을 큰 소리로 고지하면 경보가 싸구려가 된다 — §10.8.4 착지 정산과 같은 판단). 계약
    2탭은 그 반대로 **예고를 달지 않는다** — 최종 형상이 조용히 흐려지지 않게.
    """
    buttons = _collect_nav_buttons()
    index = WEB_INDEX.read_text(encoding="utf-8")
    assert index.count('class="nav-sep"') == 1, "탭 구분선(.nav-sep)이 정확히 1개여야 합니다."
    for scr in TEMP_NAV_SCREENS:
        assert "temp" in buttons[scr].get("class", ""), (
            f"navbtn[data-scr={scr}] 에 임시 표지(.temp)가 없습니다 — 최종 형상과 구분이 사라집니다."
        )
        assert "사라집니다" in buttons[scr].get("title", ""), (
            f"navbtn[data-scr={scr}] title 이 제거를 예고하지 않습니다(지도 §10.9 판정 B)."
        )
    # 구분선 왼쪽(계약 2탭)이 임시 표지를 얻으면 최종 형상이 흐려진다.
    for scr in ("job", "library"):
        assert "temp" not in buttons[scr].get("class", ""), (
            f"navbtn[data-scr={scr}] 는 계약 2탭이라 임시 표지가 붙으면 안 됩니다(§19 서문)."
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
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
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
    css = WEB_CSS.read_text(encoding="utf-8")
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
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())  # 공백 제거 → 포맷 불가지
    assert f"@media(max-width:{RESPONSIVE_BREAKPOINT_PX}px)" in css, (
        f"반응형 경계 @media(max-width:{RESPONSIVE_BREAKPOINT_PX}px) 가 사라졌습니다(#27)."
    )
    assert ".app{grid-template-columns:1fr}" in css, (
        ".app 세로 단일열 접힘 규칙이 사라졌습니다 — 최소 크기에서 가로 오버플로 회귀(#27)."
    )


def test_milestone_l_draft_density_structure_and_values():
    """#270: 기본창·duo·300px 캡·정직한 표지·컨테이너 쿼리를 정적으로 고정한다."""
    html = WEB_INDEX.read_text(encoding="utf-8")
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
    app_py = (WEB_INDEX.parents[1] / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(
        encoding="utf-8"
    )
    draft_js = (WEB_JS_DIR / "draftsession.js").read_text(encoding="utf-8")
    screen_js = (WEB_JS_DIR / "screens" / "draft.js").read_text(encoding="utf-8")

    assert "DEFAULT_WINDOW_WIDTH = 1440" in app_py
    assert "DEFAULT_WINDOW_HEIGHT = 900" in app_py
    assert 'class="duo draft-duo" id="draftDuo"' in html
    duo = html.split('id="draftDuo"', 1)[1].split("<!-- ④ 완료", 1)[0]
    assert duo.index('id="draftTokPanel"') < duo.index('id="draftCard"')
    assert 'id="draftMapCapstrip" role="status" hidden' in duo
    assert (
        ".job-panel{flex:1;min-width:0;overflow:auto;display:flex;flex-direction:column;"
        "container-type:inline-size;container-name:session-panel}" in css
    )
    assert "#draftTokPanel{max-height:300px;overflow:auto}" in css
    assert ".capstrip[hidden]{display:none}" in css
    assert "@containersession-panel(max-width:900px)" in css
    assert "host.scrollHeight > host.clientHeight + 1" in draft_js
    assert 'mapCapstrip: "draftMapCapstrip"' in screen_js
    assert "ResizeObserver(measureMapCap)" in draft_js


def test_milestone_l_draft_expansion_sheets_move_live_surfaces():
    """#271: 두 펼침 면의 골격·정확한 버튼 문안·실 DOM 이동/복귀 계약을 고정한다."""
    html = WEB_INDEX.read_text(encoding="utf-8")
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
    sheets = (WEB_JS_DIR / "surface_sheet.js").read_text(encoding="utf-8")
    draft_js = (WEB_JS_DIR / "draftsession.js").read_text(encoding="utf-8")

    assert html.count("펼쳐서 맞추기 ⤢") >= 1
    assert html.count("펼쳐서 행 고르기 ⤢") >= 1
    assert '<div id="draftMapSheet" class="modal sheet hidden"' in html
    assert '<div id="dataSheet" class="modal sheet hidden"' in html
    for key in ("tokPanel", "mapLegend", "cardReadout", "cardRender"):
        assert f"{{ id: id.{key}, slotId:" in draft_js
    for key in ("recsHead", "chips", "tableHost", "strip", "colPanel"):
        assert f"{{ id: id.{key}, slotId: \"dataSheetSlot\" }}" in draft_js
    assert ".cloneNode(" not in sheets
    assert "slot.appendChild(el)" in sheets
    assert "m.parent.insertBefore(m.el, m.next)" in sheets
    assert ".data-sheet-body.jobtbth:first-child" in css
    assert "position:sticky;left:0" in css


def test_milestone_l_job_density_and_expansion_sheets():
    """#272 승계 + 재작성 R1: 세션 패널 2열·420px 캡·두 펼침 면·편집 전 즉시 복귀 계약.

    R1 이 구 `.job-duo`(표|거울 가로 병치)를 v6 `screen-data` 2열로 대체했다 — 가로 축은
    이제 데이터 ↔ 문서 선택기이고, 표↔거울은 좌 열 안에서 **세로 인접**으로 남는다(같은
    시야 요구는 인접 + 펼침 면 ⤢ 가 승계). #272 의 나머지 계약(420px 캡·캡스트립·두 면의
    실 DOM 이동/복귀)은 그대로 살아 여기서 계속 고정된다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    sheets = (WEB_JS_DIR / "surface_sheet.js").read_text(encoding="utf-8")

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
    assert ".data-grid{display:grid;grid-template-columns:minmax(0,1fr)minmax(268px,.46fr)}" in css
    assert "@containersession-panel(max-width:900px)" in css
    assert ".data-grid{grid-template-columns:1fr}" in css
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
    assert 'closeAndRestore("dataSheet")' in job_js
    assert "window.Modal.close(id);\n    restore(id);" in sheets
    # 펼침 트리거 포커스 복귀(#279 리뷰) — 캡스트립 위임 클릭의 currentTarget 은 포커스
    # 불가능한 컨테이너 div: 실클릭 버튼→상시 ⤢ 순으로 해석하는 SurfaceSheet.trigger 만 쓴다.
    draft_session = (WEB_JS_DIR / "draftsession.js").read_text(encoding="utf-8")
    assert "trigger: trigger" in sheets
    for src in (job_js, draft_session):
        assert "window.SurfaceSheet.trigger(e," in src
        assert "returnFocus: e && e.currentTarget" not in src
    # 캡스트립 생성 버튼은 복귀 표적 제외(#280 리뷰) — afterRestore 의 measure* 가
    # innerHTML 을 갈아 방금 포커스한 버튼이 분리된다(안정 헤더 ⤢ 폴백 고정).
    assert 'btn.closest(".capstrip")' in sheets
    assert html.count('class="capstrip"') >= 2
    # sticky 첫 열의 행 상태 보존(#279 리뷰) — 무조건 --a-card 는 tr.on/호버 배경을 덮어
    # 문서 정체 셀만 미선택처럼 보인다. sticky 는 투명 불가라 불투명 등가색으로 맞춘다.
    assert ".data-sheet-body.jobtbtbodytr.ontd:first-child{background:var(--a-sel)}" in css
    assert ".data-sheet-body.jobtbtbodytr:hovertd:first-child{" in css
    assert "color-mix(insrgb,var(--a-sel)40%,var(--a-card))" in css


def test_diff_selftest_waits_for_renderer_registration_not_script_parse():
    """#252 리뷰 — `typeof window.DiffScreen === 'object'` 는 스크립트 파싱 즉시 참이라,
    pywebviewready → init() → onPush 등록 **전**에 push 하면 __push 가 조용히 버려 비교
    버튼이 비활성인 채 게이트가 간헐 실패한다. 게이트는 렌더러 등록 표지(ready)를 기다린다."""
    root = WEB_INDEX.parents[1]
    diff_js = (root / "web-diff" / "js" / "screens" / "diff.js").read_text(encoding="utf-8")
    diff_app = (root / "src" / "hwpxdiff" / "webapp" / "app.py").read_text(encoding="utf-8")
    assert "window.DiffScreen = { init, ready: false }" in diff_js
    assert "window.DiffScreen.ready = true" in diff_js
    # 표지는 initial 렌더 **완료 뒤**에만 선다(#280 리뷰) — onPush 등록 직후 세우면
    # 게이트 push 가 미해결 initial 응답과 경합해 빈 스냅샷이 push 를 덮어쓴다.
    assert diff_js.index("Bridge.onPush(SCREEN, render)") < diff_js.index(
        "render(await Bridge.initial(SCREEN))"
    ) < diff_js.index("window.DiffScreen.ready = true")
    assert "window.DiffScreen.ready === true" in diff_app


def test_job_generation_result_renders_partial_cancellation_honestly():
    """#278 리뷰 — 취소된 배치를 진행바 100% + danger 로 그리면 정확한 요약 문안 옆에서
    시각이 '완주했고 오류'라고 거짓말한다: 진행 = attempted/total, warn 채널 보존.

    F4 의 3태 구획으로 옮겨 온 뒤에도 **채널은 둘 그대로**다: 태(data-state)는 구조를,
    level(data-level)은 색을 정한다. JS 가 level 을 재판정하지 않고 Python 값을 그대로
    싣는 것이 이 계약의 새 표현이며, warn 이 실제로 danger 와 다른 색을 받는지는 CSS 가 진다.
    """
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
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
    assert "jobPanel.style.flex = '0 0 1100px'" in app_py
    assert "draftPanel.style.flex = '0 0 1100px'" in app_py
    assert "jobPanel.style.flex = jobPanelFlex" in app_py
    assert "draftPanel.style.flex = draftPanelFlex" in app_py


def _forced_colors_block(css_path: Path) -> str:
    """``@media (forced-colors:active)`` 블록의 **본문**만 공백 제거 형태로 반환.

    파일 전체가 아니라 블록 내부를 봐야 한다 — 그러지 않으면 블록 밖에 이미 존재하는
    ``tr.r-unconfirmed``/``border-left`` 같은 토큰이 검사를 통과시켜, 정작 고대비 보더
    신호를 떨궈도 잡지 못한다(원 테스트의 사각). 주석을 먼저 걷어 브레이스 계수를
    오염시키지 않고, 여는 ``{`` 부터 짝 맞는 ``}`` 까지 깊이로 잘라낸다. 블록이 없으면 "".
    """
    text = re.sub(r"/\*.*?\*/", "", css_path.read_text(encoding="utf-8"), flags=re.S)
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


def test_forced_colors_block_present_in_web_diff():
    """web-diff(2판 diff 뷰어)도 강제색 블록과 삽입(ins) 밑줄 신호를 가져야 한다(#3, web/ 와 짝).

    web/ 만 가드하면 web-diff 의 블록을 조용히 떨구는 이관/리팩터를 못 잡는다 — 이 PR 이
    봉합하려던 '웹 이관 시 조용한 회귀' 패턴 그 자체. ins 는 배경 틴트뿐이라 고대비에서
    색 외 신호(밑줄)가 반드시 있어야 한다.
    """
    block = _forced_colors_block(WEB_DIFF_CSS)
    assert block, "web-diff 강제 색상 모드 @media(forced-colors:active) 블록이 사라졌습니다(#3)."
    # 값까지 검사한다 — text-decoration 선언이 있어도 값이 none 이면 밑줄 신호가 무력화되므로
    # underline 값 자체를 단언(선언 존재만 보면 none 으로 바꿔도 통과).
    assert "underline" in _rule_body(block, ".doctableins"), (
        "diff 삽입(ins)의 강제색 밑줄(text-decoration:underline) 신호가 사라졌습니다 — "
        "배경 틴트만으론 고대비에서 삽입 구간이 사라집니다(#3)."
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

    갤러리의 유일한 존재 이유는 드리프트-0 — app.css 를 고치면 자동 반영되는 정직한 거울이다.
    CSS 를 인라인 복사하면 실앱과 조용히 어긋난다(목업 docs/UI_PROTOTYPE_APPB.html 이 그 함정:
    색만 생성기 동기, 나머지 드리프트). 따라서 갤러리는 반드시 (a) 실 tokens.css+app.css 를
    링크하고 (b) 인라인 스타일에서 앱 색 토큰(--a-*)을 재정의하지 않는다 — 복사본 재유입을
    loud 하게 차단한다.
    """
    assert GALLERY.exists(), f"컴포넌트 갤러리가 없습니다: {GALLERY}"
    html = GALLERY.read_text(encoding="utf-8")
    _IdCollector().feed(html)  # 구문 파싱 OK(기존 관례 HTMLParser).
    assert 'href="../web/css/tokens.css"' in html, (
        "갤러리가 실 tokens.css 를 링크하지 않습니다 — 드리프트-0 불변식 위반."
    )
    assert 'href="../web/css/app.css"' in html, (
        "갤러리가 실 app.css 를 링크하지 않습니다 — 드리프트-0 불변식 위반."
    )
    assert not re.search(r"--a-[\w-]+\s*:\s*#", html), (
        "갤러리 인라인 스타일이 앱 색 토큰(--a-*)을 재정의합니다 — "
        "링크된 tokens.css 만 쓰세요(인라인 복사는 드리프트 재도입)."
    )


def test_heading_typography_uses_three_shared_roles():
    """H-01: 화면·구획·존 제목은 세 역할 규칙만 소비한다."""
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
    assert ".scr-headh1{font-size:var(--fs-section);font-weight:700}" in css
    assert (
        ".lib-detail-name,.job-sec-head,.tpl-band.tb-t,.modal-cardh3{"
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
        ".tpl-band.tb-t{font-weight:",
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
    거기는 여전히 순서 있는 세션이다. 번호의 정보(다음에 어디로)는 게이트 문안의 구획
    지목(`gateStep`)이 승계한다.
    """
    html = " ".join(WEB_INDEX.read_text(encoding="utf-8").split())
    job = html.split('id="scr-job"', 1)[1].split('id="scr-draft"', 1)[0]
    for caption in (
        "현재 데이터", "본문 확인", "생성 결과",
        "이 데이터에 사용할 문서", "선택한 작업", "생성 준비",
    ):
        needle = rf'<div class="zone-cap[^"]*">(?:<span>)?{re.escape(caption)}'
        assert re.search(needle, job), f"세션 구획 캡션이 없습니다: {caption}"
    assert '<span class="znum">' not in job, (
        "「작업」 세션 표면에 구 4존 서수가 재유입됐습니다."
    )
    # 기안은 같은 은퇴에 휩쓸리지 않는다(순서 있는 세션 — 문법을 함께 지우면 회귀).
    assert '<span class="znum">' in html.split('id="scr-draft"', 1)[1]


def test_job_result_zone_declares_the_three_state_contract():
    """F4(지도 §10.10): 결과 3태 구획의 정적 계약 — 태 소유자·행동 4종·증거·실행 기록 존치.

    태를 문안이 아니라 ``[data-state]`` 가 소유하는 것이 요점이다: 문안으로 태를 읽으면
    번역·재작문 한 번에 판정이 끊긴다. 실행 기록(로그 상자)은 **살아 있어야 한다** —
    결과 사건만 3태가 가져갔고 비-결과 사건(데이터 불러옴·검색 실패·중단 요청)은 이
    화면의 유일한 비모달 채널이라 함께 죽이지 않았다(§10.10 판정 D).
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    job = html.split('id="scr-job"', 1)[1].split('id="scr-draft"', 1)[0]
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
    job = html.split('id="scr-job"', 1)[1].split('id="scr-draft"', 1)[0]
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
    # setBusy 가 그 루트도 훑고, 출구·탭·행이 busy-lock 을 달아야 한다.
    assert 'dataPickerModal")].forEach' in src, "setBusy 가 탐색 면을 잠그지 않습니다."
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
    # 문안은 완주 스탬프 의미와 일치해야 한다(성공 뒤 실패 런에서 거짓이 되지 않게).
    assert "마지막 성공 실행" in src and "마지막 실행 " not in src, (
        "카드 문안이 완주 스탬프 의미(마지막 성공 실행)와 어긋납니다."
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
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
    # 추천은 활성과 시각으로 구별된다 — 점선(아직 고른 것 아님) vs 실선 강조(활성).
    assert ".job-cand-card.suggested:not(.active){border-style:dashed" in css
    assert ".job-cand-card.active{border-color:var(--a-primary)" in css


def test_template_media_sections_use_sunken_surface_without_shared_catalog_drift():
    """H-04: HWPX/TXT만 sunken 표면을 쓰고 공유 tpl-catalogs는 독립적으로 남는다."""
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert html.count('class="tpl-medium"') == 2
    for medium, groups_id in (("hwpx", "tplHwpxGroups"), ("txt", "tplTxtGroups")):
        assert f'data-medium="{medium}"' in html
        assert f'id="{groups_id}"' in html

    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
    assert (
        ".tpl-medium{margin-top:var(--sp-16);padding:var(--sp-8)var(--sp-10)var(--sp-10);"
        "background:var(--n-surface-alt);border:1pxsolidvar(--a-border);"
        "border-radius:var(--rad-surface)}"
    ) in css
    assert ".tpl-medium.tplcard{border-color:var(--n-border-strong)}" in css
    assert ".tpl-catalogs{display:grid" in css


def test_gallery_exposes_template_media_surface():
    html = GALLERY.read_text(encoding="utf-8")
    assert ".tpl-medium — 매체 sunken 구획 / 카드 층" in html


def test_card_families_share_hover_and_keep_persistent_state_separate():
    """H-14: 카드류 hover는 틴트뿐이고 막대는 선택·오류에만 남는다.

    구 홈 txt 목록(.tlist .titem)은 화면과 함께 사망했고(재작성 F2), 라이브러리 행(.lib-row)이
    같은 어휘의 새 소비자다 — 같은 규칙을 쓰는지 여기서 함께 본다.
    """
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
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
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
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
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
    assert (
        ".btn.primary:disabled{background:var(--n-track);color:var(--a-muted);"
        "border-color:var(--a-border);opacity:1}"
    ) in css
    assert ".btn.primary:disabled{background:var(--a-muted)" not in css


def test_web_diff_pinned_to_light_until_tints_themed():
    """web-diff 는 다크 셀 틴트가 준비될 때까지 라이트로 고정돼야 한다(<html data-theme="light">).

    공유 tokens.css 가 다크 3블록을 함께 실어 web-diff 도 OS 다크를 자동 추종하게 되는데, diff
    표의 added/removed 셀 배경은 백엔드 스냅샷의 라이트 파스텔을 인라인 style 로 박아 테마를
    안 따른다 — 다크에선 밝은 본문 잉크가 밝은 틴트 위에 얹혀 판독 불가. 셀 틴트를 토큰화하기
    전까지 라이트 고정이 정답이며, 이 핀이 조용히 풀려 깨진 자동 다크가 재개방되는 걸 막는다.
    """
    html = WEB_DIFF_INDEX.read_text(encoding="utf-8")
    m = re.search(r"<html\b[^>]*>", html)
    assert m and 'data-theme="light"' in m.group(0), (
        "web-diff <html> 이 data-theme=\"light\" 로 고정돼야 합니다 — "
        "diff 셀 틴트가 테마-불가지라 자동 다크에서 표가 깨집니다."
    )


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
    """#218: X 가드·신규 취소·dismiss 뒤 편집 복귀 경로가 DOM/JS에서 함께 살아 있어야 한다."""
    html = WEB_INDEX.read_text(encoding="utf-8")
    app_py = (WEB_INDEX.parents[1] / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    app_js = (WEB_JS_DIR / "app.js").read_text(encoding="utf-8")
    editor_js = (WEB_JS_DIR / "screens" / "editor.js").read_text(encoding="utf-8")
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")

    assert "window.events.closing += frontend._handle_window_closing" in app_py
    assert "AppCloseGuard" in app_js and "confirm_window_close" in app_js
    assert 'id="jobEditResume"' in html and "jobEditResume" in job_js
    assert 'data-act="cancel-new"' in editor_js
    assert 'Bridge.call(SCREEN, "discard_session", {})' in editor_js
    assert "showRunMode" in job_js


def test_unhandledrejection_backstop_present_in_both_shells():
    """비동기 실패 최종 백스톱 — 두 셸이 unhandledrejection 을 alert 로 재진술해야 한다.

    무대기·무catch 브리지 호출의 rejection 이 조용한 무반응으로 증발하는 결함류가
    파일 단위 봉합(F8·F9→#45 profile_*→PR #46 P2 onClick)으로 반복 재발했다 — 사이트별
    규율 대신 셸 전역 안전망으로 구조 차단한다. 지역 가드가 잡은 실패는 여기 오지
    않으므로 이 백스톱은 "가드를 잊은 곳" 전용이다. preventDefault 없이 alert 만 하면
    콘솔 소음이 남고, alert 없이 preventDefault 만 하면 완전 침묵(최악)이라 둘 다 단언한다.
    """
    for app_js in (WEB_JS_DIR / "app.js",
                   WEB_JS_DIR.parents[1] / "web-diff" / "js" / "app.js"):
        src = app_js.read_text(encoding="utf-8")
        m = re.search(r'addEventListener\("unhandledrejection",[\s\S]*?\}\);', src)
        assert m, f"{app_js} 에 unhandledrejection 백스톱이 없습니다 — 조용한 무반응 결함류 재개방."
        block = m.group(0)
        assert "window.alert" in block, f"{app_js} 백스톱이 alert 로 재진술하지 않습니다."
        assert "preventDefault" in block, f"{app_js} 백스톱이 rejection 을 handled 처리하지 않습니다."


def test_editor_surface_lives_in_job_panel():
    """에디터 흡수 완결(R-flow 블록 2 개정, 결정 39~41) — 정의 surface 의 거처·진입 계약.

    에디터 컨테이너 3종(editor-steps/-body/-foot)은 「작업」 패널의 편집 호스트
    (#jobEditHost) 안에 살고, **scr-editor 별도 화면·레일 항목은 소멸**했다(슬라이스 5
    삭제 — 재유입 가드). 진입점은 전부 편집 모드로 착지해야 한다: ``Nav.go("editor")`` 는
    존재하지 않는 화면으로 보내는 죽은 경로라 금지한다.
    """
    html = WEB_INDEX.read_text(encoding="utf-8")
    # scr-job 다음 섹션은 이제 scr-draft(구 scr-txt 는 #148 슬라이스 6 삭제) — 그 경계까지가 「작업」 패널.
    job_sec = html.split('id="scr-job"')[1].split('id="scr-draft"')[0]
    for cid in ("jobEditHost", "editor-steps", "editor-body", "editor-foot"):
        assert cid in job_sec, f"{cid} 가 scr-job 편집 호스트에 없습니다(흡수 이사 회귀)."
    # 별도 화면·레일 항목 재유입 가드(삭제는 의무를 상속한다 — 조용한 부활 금지).
    assert 'id="scr-editor"' not in html, "scr-editor 별도 화면이 부활했습니다(결정 39 위반)."
    assert 'data-scr="editor"' not in html, "레일 「작업 에디터」 항목이 부활했습니다(결정 39 위반)."
    # 진입점 repoint — 죽은 목적지 금지 + 편집 모드 seam 배선.
    all_js = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(WEB_JS_DIR.rglob("*.js")))
    assert 'Nav.go("editor")' not in all_js, (
        'scr-editor 는 소멸 — Nav.go("editor") 는 존재하지 않는 화면으로 보내는 죽은 경로입니다'
        "(편집 진입은 EditorEntry.land 로)."
    )
    # 진입 흐름은 EditorEntry 단일 정의(land/newDraft/openGuarded — 축자 복붙=드리프트 표면).
    # 소비처 전수(라이브러리·템플릿 관리·작업 화면 — PR-5 리뷰 F5: job.js 가 가드 사각이었다).
    entry_src = (WEB_JS_DIR / "editor_entry.js").read_text(encoding="utf-8")
    for fn in ("function land", "function newDraft", "function openGuarded"):
        assert fn in entry_src, f"editor_entry.js 의 단일 정의({fn})가 사라졌습니다."
    for fname, needle in (
        ("screens/library.js", "EditorEntry.newDraft"),
        ("screens/library.js", "EditorEntry.openGuarded"),
        ("screens/template.js", "EditorEntry.land"),
        # 「문서 만들기」는 좌 목록 사망(F2 PR-B)으로 **새 작업 진입을 더는 갖지 않는다** —
        # `＋ 새 작업`은 라이브러리 화면 머리 한 곳이다(진입이 둘이면 폐기 확인이 갈린다).
        # 남는 것은 수리 동선(드리프트·파일명 토큰)의 편집 진입뿐이다.
        ("screens/job.js", "EditorEntry.openGuarded"),
    ):
        src = (WEB_JS_DIR / fname).read_text(encoding="utf-8")
        assert needle in src, f"{fname} 가 진입 단일 출처({needle})를 쓰지 않습니다."
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert "EditorEntry.newDraft" not in job_js, (
        "「문서 만들기」에 새 작업 진입이 되살아났습니다 — 승계처는 라이브러리 `＋ 새 작업`입니다."
    )
    # 편집 모드의 두 출구(F2 PR-B 판정 D) — 「편집으로 돌아가기」(T2 고지)와 「실행으로
    # 돌아가기」(결정 40 이 좌 목록 행 클릭에 줬던 소임의 승계처). 둘 다 비파괴다.
    assert "return-to-edit" in job_js, "T2 고지의 비파괴 「편집으로 돌아가기」가 없습니다(F1)."
    assert 'id="jobEditExit"' in job_sec, (
        "편집 → 실행 복귀 어포던스가 없습니다 — 좌 목록 사망 뒤 실행으로 돌아갈 길이 사라집니다"
        "(지도 §10.9 판정 D)."
    )
    editor_js = (WEB_JS_DIR / "screens" / "editor.js").read_text(encoding="utf-8")
    assert '$("jobEditHost")' in editor_js, "editor.js 위임 루트가 편집 호스트로 이사하지 않았습니다."
    assert "exitEditToRun" in job_js and "showEditMode" in job_js, (
        "job.js 패널 두 모드 배선(showEditMode/exitEditToRun)이 사라졌습니다(결정 39·40)."
    )


def test_use_in_job_lands_run_mode_not_the_editor():
    """「문서 만들기에서 사용」은 **실행 모드**에 착지한다(F2 PR-B).

    좌 목록이 살아 있을 땐 행 클릭이 이 정산을 겸했다(결정 40) — 편집 모드면 실행으로
    되돌리고 미저장 편집은 고지했다. 목록이 죽으면서 그 정산이 빠지면, 작업을 저장한 직후
    「문서 작업」에서 그것을 쓰겠다고 눌렀을 때 편집 호스트가 그대로 뜬다: 사용자가 요청한
    것과 다른 표면에 착지하는 결함(2R P2 「빈 화면 착지」와 같은 클래스). 전이는 비파괴다.
    """
    lib = (WEB_JS_DIR / "screens" / "library.js").read_text(encoding="utf-8")
    job = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    use = lib[lib.index('Bridge.call(JOB, "prefer_work"'):lib.index("window.Nav.go(JOB);")]
    assert "JobScreen.landRunMode" in use, (
        "「문서 만들기에서 사용」이 실행 모드 착지를 정산하지 않습니다 — 편집 호스트에 착지합니다."
    )
    assert "async function landRunMode(" in job and "landRunMode," in job, (
        "job.js 가 실행 모드 착지 seam(landRunMode)을 내보내지 않습니다."
    )
    body = job[job.index("async function landRunMode("):]
    body = body[:body.index("\n  }") + 4]
    assert "exitEditToRun()" in body and "showExitNote()" in body, (
        "실행 착지가 기존 비파괴 전이·미저장 고지를 쓰지 않습니다(새 전이를 만들지 않는다)."
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


def test_draft_has_return_path_to_volatile_session():
    """「기안」에서 저장 기안을 고른 뒤 **휘발 세션으로 돌아갈 길**이 있어야 한다(#148 리뷰 P2).

    미선택이 곧 휘발 진입구(R-info 3부 결정 5)라, 선택 해제 동사가 없으면 TXT 작업이 하나라도
    있는 사용자는 한 번 고른 뒤 붙여넣기 화면으로 못 돌아온다 — 행 재클릭은 무동작이고 빈
    영역 클릭도 해제가 아니라서 **앱 재시작이 유일한 출구**가 된다. 슬라이스 5a 에서 껍데기
    stub 이 사라지고(선택이 실제 복원이 되며) 귀환 동사는 좌 목록의 **상시 「이번 세션」 행**
    (``data-volatile``)이 승계했다 — 그 행 클릭이 곧 겨눔 해제(select_job 빈 이름)다.
    """
    src = (WEB_JS_DIR / "screens" / "draft.js").read_text(encoding="utf-8")
    assert "data-volatile" in src, "상시 「이번 세션」 행(휘발 귀환구)이 목록에 없습니다(막다른 상태)."
    # 「이번 세션」 행 클릭 → selectJob("") (진행 보존 가드 왕복을 겸하는 공용 경로, 리뷰 5a P1).
    assert re.search(r'data-volatile[\s\S]*?selectJob\(""\)', src, re.S), (
        "「이번 세션」 행 클릭이 selectJob(\"\") 로 배선되지 않았습니다 — 눌러도 아무 일이 없습니다."
    )
    # selectJob 은 select_job(빈 이름) 으로 겨눔을 푼다(무장이면 needs_confirm 왕복 후 confirm).
    assert re.search(r'function selectJob\([\s\S]*?select_job', src, re.S), (
        "selectJob 이 select_job 으로 배선되지 않았습니다."
    )


def test_draft_saved_source_has_fork_escape_hatch():
    """저장 원문은 읽기 전용이므로 「사본으로 편집」이 **유일한 편집 출구**여야 한다(#148 슬라이스 5b).

    읽기 전용만 걸고 사본 동사가 없으면 저장 기안의 원문은 손볼 길이 막힌다 — 원문바에 사본
    버튼이 있고 fork_to_volatile 로 배선돼야 편집이 열린다(값·데이터·큐 진행은 승계). 백엔드도
    저장 모드 edit_source 를 방어한다(표면 readonly 만 믿지 않는다 — 조용한 정의 분기 금지)."""
    index = WEB_INDEX.read_text(encoding="utf-8")
    assert 'id="draftSrcFork"' in index, "원문바에 「사본으로 편집」 버튼이 없습니다(읽기 전용 막다른 상태)."
    src = (WEB_JS_DIR / "draftsession.js").read_text(encoding="utf-8")
    assert re.search(
        r'id\.srcFork\)[\s\S]*?fork_to_volatile', src, re.S,
    ), "「사본으로 편집」이 fork_to_volatile 로 배선되지 않았습니다 — 눌러도 편집이 열리지 않습니다."


def test_draft_live_edit_refreshes_source_bar():
    """원문 라이브 편집(_NO_PUSH patchMap)도 원문바 이름·수정됨 표지를 갱신해야 한다(#148 5b, 리뷰 P2).

    깨끗한 휘발 원문을 고치면 `source_dirty=true`·`template_name` 소거인데, `edit_source` 는
    `_NO_PUSH` 라 full render 를 안 타 `patchMap` 이 원문바를 안 그리면 무관한 재렌더 전까지 옛
    이름·수정됨 부재로 남는다(stale). `patchMap` 이 공유 `renderSourceBar` 를 부르는지 못박는다."""
    src = (WEB_JS_DIR / "draftsession.js").read_text(encoding="utf-8")
    assert re.search(r"function patchMap\([\s\S]*?renderSourceBar\(", src), (
        "patchMap 이 renderSourceBar 를 부르지 않습니다 — 라이브 편집 뒤 원문바가 stale."
    )
