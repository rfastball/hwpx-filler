"""실제 웹 프론트엔드 DOM 계약 가드 — 배포되는 ``web/index.html`` 자체를 검사한다.

``test_ui_contract.py`` 는 목업(``docs/UI_PROTOTYPE_APPB.html``)의 ``data-vm`` 주석이
ViewModel 표면과 정합한지만 본다 — 실제 배포 DOM 은 전혀 읽지 않아 중복 ``id`` 같은
결함을 통과시켰다(#27). 이 모듈은 그 사각을 메운다: 실제 ``web/index.html`` 을 파싱해
**전역 id 유일성**과 화면 구조를 단언한다.

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
PRESERVE_WRAPPED_SCREENS = ("txt", "editor", "job", "quickdraft")  # run 사망(슬라이스 3) → job 이 생성 표면

# 살아있는 컴포넌트 갤러리(개발 전용) — 실 tokens.css+app.css 를 <link> 로 물어 드리프트 0.
GALLERY = Path(__file__).resolve().parents[1] / "docs" / "UI_GALLERY.html"

# 화면 루트 — 셸 라우터가 표시/숨김으로 전환하는 최상위 컨테이너(회귀 시 화면 소실).
SCREEN_ROOTS = (
    "scr-home", "scr-txt", "scr-tpl",
    "scr-pool",  # 데이터 관리(#26 #4)
    # 「작업」(R-flow · #90) — 유일 생성 표면(실행 화면=슬라이스 3 사망) + 편집 모드(작업
    # 에디터 별도 화면=슬라이스 5 사망, 결정 39 흡수 — 정의 surface 는 scr-job 내부).
    "scr-job",
    # 빠른 기안(R-flow 블록 5 · #90 슬라이스 7) — 작업의 휘발 쌍둥이(신설·공존, 레일 6 임시).
    "scr-quickdraft",
)

# 화면별 데이터 라벨은 반드시 고유 id 여야 한다(#27 dup-id 회귀 가드).
SCOPED_DATA_LABELS = ("txtDataLabel", "jobDataLabel")

# 접힘 상태에서 라벨이 사라지는 내비 버튼(회귀 시 접근 이름·툴팁 소실 → #27).
NAV_SCREENS = ("home", "job", "txt", "quickdraft", "tpl", "pool")  # run=슬라이스 3·editor=슬라이스 5 사망(흡수); quickdraft=슬라이스 7 신설(레일 6 임시)

# 커스텀 모달 → aria-labelledby 가 가리켜야 할 제목 id(다이얼로그 시맨틱, #27/#28).
# sheetModal 은 다중 시트 확정 게이트(#33) — 같은 Modal 헬퍼·다이얼로그 계약을 공유한다.
MODAL_LABELLEDBY = {
    "txtEditModal": "txtEditTitle",
    "pasteModal": "pasteTitle",
    "qdPasteModal": "qdPasteTitle",  # 빠른 기안 붙여넣기(#90 슬라이스 7) — txt 와 별개 id
    "qdSaveTplModal": "qdSaveTplTitle",  # 빠른 기안 「템플릿으로 저장」 승격(#135)
    "sheetModal": "sheetTitle",
    "poolRegModal": "poolRegTitle",  # 데이터 등록(#26 #4)
    "poolModal": "poolTitle",  # 등록 데이터 선택(#26 #6) — 정적 골격 이관(r3 K12)
    # 「작업」 덮어쓰기 확인은 슬라이스 2(A-2-22)에서 공용 confirmModal(수치 합성 본문)로 이관 —
    # 전용 jobOverwriteModal DOM 폐기(아래 test_job_overwrite_uses_shared_confirm_modal 가드).
    "confirmModal": "confirmModalTitle",  # 네이티브 window.confirm 대체(#86) + 덮어쓰기 확인
    "promptModal": "promptModalTitle",  # 네이티브 window.prompt 대체(#86)
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
    """접힘 상태에서 .n/.d 가 display:none 이 되어도 각 내비 버튼은 접근 이름과 툴팁을 유지해야 한다(#27).

    접힘 시 라벨 span 이 숨겨지면 aria-label 없는 버튼은 접근 이름이 사라지고 title 없는 버튼은
    호버 툴팁도 없다 — 둘 다 버튼별로 고정돼 있어야 회귀를 막는다.
    """
    buttons = _collect_nav_buttons()
    missing = [s for s in NAV_SCREENS if s not in buttons]
    assert not missing, f"내비 버튼이 사라졌습니다(data-scr): {missing}"
    for scr in NAV_SCREENS:
        attrs = buttons[scr]
        assert attrs.get("aria-label", "").strip(), (
            f"navbtn[data-scr={scr}] 에 비어있지 않은 aria-label 이 필요합니다"
            " — 접힘 시 접근 이름 소실(#27)."
        )
        assert attrs.get("title", "").strip(), (
            f"navbtn[data-scr={scr}] 에 비어있지 않은 title 이 필요합니다"
            " — 접힘 시 호버 툴팁 소실(#27)."
        )


def test_collapsed_nav_has_visual_marker():
    """각 내비 버튼에 상시 보이는 아이콘 표지(.ni SVG)가 있고, 접힘 시 라벨열(.lbl)이 숨겨져도
    그 표지는 남아야 한다(#27 개정).

    옛 계약은 '.ni 글자표지를 펼침엔 숨기고 접힘에만 노출'이었으나, 앱 디자인 언어 채택으로 .ni 가
    SVG 아이콘으로 승격돼 라벨과 상시 공존한다(중복이 아니라 스캔 보조). 따라서 계약을 뒤집는다 —
    아이콘 상시 표지 + 접힘 시 라벨열(.lbl)만 숨김. aria-label/title 은 SR 이름·호버 툴팁으로 유지.
    """
    index = WEB_INDEX.read_text(encoding="utf-8")
    marker_count = index.count('class="ni"')
    assert marker_count == len(NAV_SCREENS), (
        f"내비 시각 표지(.ni)가 {marker_count}개 — 버튼마다 정확히 1개여야 합니다(#27)."
    )
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
    # 아이콘(.ni svg)은 상시 표지 — 크기 규칙 존재로 SVG 아이콘 착지를 확인(펼침 숨김 규칙 폐기).
    assert ".navbtn.nisvg{width:18px" in css, (
        "내비 아이콘(.ni svg) 상시 표지 규칙이 사라졌습니다(#27 개정)."
    )
    # 접힘 시 라벨열(.lbl)을 숨겨 작업영역을 넓히되, 아이콘은 남아 표지를 잇는다.
    assert ".app.rail-collapsed.navbtn.lbl{display:none" in css, (
        "접힘 상태에서 라벨열(.lbl)을 숨기는 규칙이 사라졌습니다(#27)."
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
DATA_PICK_SCREENS = ("editor", "txt", "job", "quickdraft")  # run 사망(슬라이스 3);
# job=생성 표면 · quickdraft=휘발 표면의 임의 파일 선택(슬라이스 7 PR-3)


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
    for scr in DATA_PICK_SCREENS:
        src = (WEB_JS_DIR / "screens" / f"{scr}.js").read_text(encoding="utf-8")
        assert "needs_sheet" in src and "SheetPicker.choose" in src, (
            f"{scr}.js 가 다중 시트 확정 게이트(needs_sheet→SheetPicker) 배선을 잃었습니다 — "
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
    for scr in PRESERVE_WRAPPED_SCREENS:
        src = (WEB_JS_DIR / "screens" / f"{scr}.js").read_text(encoding="utf-8")
        assert "Preserve.around" in src, (
            f"{scr}.js 의 render() 가 Preserve.around 래핑을 잃었습니다 — 재렌더 시 상호작용 유실(#28)."
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
    job_sec = html.split('id="scr-job"')[1].split('id="scr-txt"')[0]
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
    # 소비처 전수(홈·템플릿 관리·작업 화면 — PR-5 리뷰 F5: job.js 가 가드 사각이었다)를 가드.
    entry_src = (WEB_JS_DIR / "editor_entry.js").read_text(encoding="utf-8")
    for fn in ("function land", "function newDraft", "function openGuarded"):
        assert fn in entry_src, f"editor_entry.js 의 단일 정의({fn})가 사라졌습니다."
    for fname, needle in (
        ("screens/home.js", "EditorEntry.newDraft"),
        ("screens/home.js", "EditorEntry.openGuarded"),
        ("screens/template.js", "EditorEntry.land"),
        ("screens/job.js", "EditorEntry.openGuarded"),
        ("screens/job.js", "EditorEntry.newDraft"),
    ):
        src = (WEB_JS_DIR / fname).read_text(encoding="utf-8")
        assert needle in src, f"{fname} 가 진입 단일 출처({needle})를 쓰지 않습니다."
    # 레일 항목 사망의 어포던스 승계(PR-5 리뷰 F1·F2) — 「작업」 구획 ＋ 새 작업 + T2 고지의
    # 비파괴 복귀 버튼(다른 진입은 전부 세션 초기화/재로드라 이 둘이 승계 실체다).
    assert 'id="jobNewBtn"' in job_sec, "「작업」 구획 ＋ 새 작업이 없습니다(결정 10·레일 승계 F2)."
    job_js = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert "return-to-edit" in job_js, "T2 고지의 비파괴 「편집으로 돌아가기」가 없습니다(F1)."
    editor_js = (WEB_JS_DIR / "screens" / "editor.js").read_text(encoding="utf-8")
    assert '$("jobEditHost")' in editor_js, "editor.js 위임 루트가 편집 호스트로 이사하지 않았습니다."
    assert "exitEditToRun" in job_js and "showEditMode" in job_js, (
        "job.js 패널 두 모드 배선(showEditMode/exitEditToRun)이 사라졌습니다(결정 39·40)."
    )


def test_group_confirm_copy_states_the_rule_not_a_promised_count():
    """그룹 확인 문안이 **규칙**을 말하고 수치는 관측으로 적는다(#149).

    확인 왕복 사이 다른 표면이 소속을 옮기면 사전 카운트는 실제와 어긋난다 — "N개는 이동합니다"
    는 지킬 수 없는 약속이 되고, 확인한 내용과 실제 집합이 갈라진다(이 저장소의 지배 결함류).
    옮겨지는 집합의 규칙('전부')은 언제나 참이므로 그것을 본문으로 삼고, 수치는 '지금 기준'
    으로 덧붙인다. 실제 건수는 실행 뒤 재진술(``drift_note``)이 진다.
    """
    src = (WEB_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    assert "지금 기준" in src, "그룹 확인 수치가 관측으로 표기되지 않았습니다(#149)."
    assert "해산 시점의 소속 작업 전부" in src, "해산 확인이 이동 집합 규칙을 말하지 않습니다(#149)."
    assert "seen: res.count" in src and "seen: r.count" in src, (
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
