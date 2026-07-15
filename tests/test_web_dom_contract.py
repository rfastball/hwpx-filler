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

# 여섯 화면 루트 — 셸 라우터가 표시/숨김으로 전환하는 최상위 컨테이너(회귀 시 화면 소실).
SCREEN_ROOTS = ("scr-home", "scr-editor", "scr-run", "scr-matrix", "scr-txt", "scr-tpl")

# 화면별 데이터 라벨은 반드시 고유 id 여야 한다(#27 dup-id 회귀 가드).
SCOPED_DATA_LABELS = ("runDataLabel", "txtDataLabel", "mxDataLabel")

# 접힘 상태에서 라벨이 사라지는 여섯 내비 버튼(회귀 시 접근 이름·툴팁 소실 → #27).
NAV_SCREENS = ("home", "editor", "run", "matrix", "txt", "tpl")


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


def _collect_ids() -> "list[str]":
    parser = _IdCollector()
    parser.feed(WEB_INDEX.read_text(encoding="utf-8"))
    return parser.ids


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
