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

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

WEB_INDEX = Path(__file__).resolve().parents[1] / "web" / "index.html"
WEB_CSS = Path(__file__).resolve().parents[1] / "web" / "css" / "app.css"

# 반응형 경계(#27): 창 최소폭(760)보다 넓은 이 경계에서 2판 레이아웃이 세로 적층으로 접혀야
# 최소 크기에서도 가로 오버플로 없이 쓸 수 있다. 경계나 접힘 규칙이 사라지면 회귀.
RESPONSIVE_BREAKPOINT_PX = 820

# 전체 스냅샷 재렌더가 포커스·캐럿·스크롤을 뭉개지 않도록 render() 를 Preserve.around 로 감싸는
# 화면들(#28). 어느 화면이 래핑을 조용히 떨구면 상호작용 유실 회귀 → 정적 가드로 차단.
WEB_JS_DIR = Path(__file__).resolve().parents[1] / "web" / "js"
PRESERVE_WRAPPED_SCREENS = ("txt", "editor", "run", "matrix")

# 여섯 화면 루트 — 셸 라우터가 표시/숨김으로 전환하는 최상위 컨테이너(회귀 시 화면 소실).
SCREEN_ROOTS = ("scr-home", "scr-editor", "scr-run", "scr-matrix", "scr-txt", "scr-tpl")

# 화면별 데이터 라벨은 반드시 고유 id 여야 한다(#27 dup-id 회귀 가드).
SCOPED_DATA_LABELS = ("runDataLabel", "txtDataLabel", "mxDataLabel")

# 접힘 상태에서 라벨이 사라지는 여섯 내비 버튼(회귀 시 접근 이름·툴팁 소실 → #27).
NAV_SCREENS = ("home", "editor", "run", "matrix", "txt", "tpl")

# 커스텀 모달 → aria-labelledby 가 가리켜야 할 제목 id(다이얼로그 시맨틱, #27/#28).
MODAL_LABELLEDBY = {"txtEditModal": "txtEditTitle", "pasteModal": "pasteTitle"}


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
    """접힘 상태에서 라벨(.n/.d)이 숨겨져도 각 내비 버튼에 눈에 보이는 시각적 표지(.ni)가 있어야 한다(#27).

    aria-label/title 는 SR 이름·호버 툴팁이고, 이건 접힘 상태에서 상시 보이는 시각 표지다 —
    #27 완료기준 '식별 가능한 이름과 시각적 표지'의 후자. 여섯 버튼 각각 1개 + 접힘 시 노출 규칙.
    """
    index = WEB_INDEX.read_text(encoding="utf-8")
    marker_count = index.count('class="ni"')
    assert marker_count == len(NAV_SCREENS), (
        f"내비 시각 표지(.ni)가 {marker_count}개 — 여섯 버튼 각각 정확히 1개여야 합니다(#27)."
    )
    css = "".join(WEB_CSS.read_text(encoding="utf-8").split())
    assert ".app.rail-collapsed.navbtn.ni{display:block" in css, (
        "접힘 상태에서 .ni 시각 표지를 노출하는 규칙이 사라졌습니다(#27)."
    )
    assert ".navbtn.ni{display:none" in css, (
        "펼침 상태에서 .ni 를 숨기는 규칙이 사라졌습니다 — 라벨과 중복 노출(#27)."
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
