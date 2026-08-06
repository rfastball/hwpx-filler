"""H-07 스크롤 토폴로지 정적 계약(#241).

실 레이아웃 판정은 통합 WebView2 프로브가 소유한다. 여기서는 허용된 내부 스크롤포트와
sticky/gutter/체이닝 CSS가 DOM에서 이탈하지 않도록 가드한다.
"""
from __future__ import annotations

import re

from _web_source import SOURCE_INDEX, SOURCE_ROOT, app_css


CSS = app_css()
INDEX = SOURCE_INDEX.read_text(encoding="utf-8")
EDITOR = (SOURCE_ROOT / "src" / "screens" / "editor.ts").read_text(encoding="utf-8")
WORKBENCH = (SOURCE_ROOT / "src" / "screens" / "workbench.ts").read_text(encoding="utf-8")
SHEET_PICKER = (SOURCE_ROOT / "src" / "screens" / "sheet_picker.ts").read_text(encoding="utf-8")
DATAZONE = (SOURCE_ROOT / "src" / "screens" / "data_zone.ts").read_text(encoding="utf-8")
DATA_PICKER = (SOURCE_ROOT / "src" / "screens" / "data_picker.ts").read_text(encoding="utf-8")
JOB_READ = (SOURCE_ROOT / "src" / "screens" / "job_read.ts").read_text(encoding="utf-8")


def _declarations(selector: str) -> str:
    """단순 top-level 규칙에서 selector에 걸린 선언을 합친다."""
    bodies: list[str] = []
    css = re.sub(r"/\*[\s\S]*?\*/", "", CSS)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        members = {part.strip() for part in selectors.split(",")}
        if selector in members:
            bodies.append(re.sub(r"\s+", "", body))
    return ";".join(bodies)


def test_wizard_tables_share_a_real_vertical_scrollport() -> None:
    """위저드 표 3벌의 sticky 기준은 높이 제한이 있는 공용 tblwrap이다."""
    # R4-02 — 문자열 조립이 요소 트리가 됐다. 묻는 것은 그대로다: 세 표가 **같은**
    # `.tblwrap` 안에 산다(각자 자기 스크롤포트를 만들지 않는다).
    for table in ("schema-fields", "data-preview", "map"):
        assert f'h("div", {{ className: "tblwrap" }}' in EDITOR
        assert f'h("table", {{ className: "{table}" }}' in EDITOR

    wrap = _declarations(".tblwrap")
    assert "max-height:" in wrap
    assert "overflow:auto" in wrap
    assert "overflow-x:auto" not in wrap

    for header in ("table.schema-fields th", "table.data-preview th", "table.map th"):
        rule = _declarations(header)
        assert "position:sticky" in rule
        assert "top:0" in rule


def test_workbench_map_header_sticks_inside_a_bounded_host() -> None:
    """실제로 세로 스크롤되는 dmap host 와 불투명 sticky 헤더를 함께 고정한다.

    「기안」 사망(F6 PR-B)으로 dmap 표의 생존 host 는 작업대 좌 pane(#wbMapPanel) —
    표 클래스(dmap)와 sticky 헤더 계약은 그대로 승계됐다.

    **높이를 무엇이 가두는가는 열 수에 달렸다**(리뷰 R1). 2열에서는 고정 캡이 아니라
    `flex:1` 로 **남는 높이**를 받는다 — 캡은 창이 낮아지면 `.wb-body` 를 넘쳐 뒤따르는
    `.wb-foot` 이 마지막 매핑 행 위에 그려졌다. 1열 퇴화에서만 캡이 돌아온다(세로로 줄을
    서면 나눠 가질 남는 높이가 없다). 둘 중 무엇이든 **경계가 있어야** sticky 헤더가 뜻을
    갖는다 — 경계 없는 host 에서는 표가 바깥 면을 밀고 헤더는 붙을 데가 없다.
    """
    assert 'id: "wbMapPanel", "data-preserve-scroll": true' in WORKBENCH
    host = _declarations("#wbMapPanel")
    assert "overflow:auto" in host
    assert "flex:1" in host, "2열에서 남는 높이를 받지 않으면 캡 시절의 footer 침범이 돌아온다."
    assert "max-height:" in host, "1열 퇴화의 캡이 없으면 host 가 무한정 늘어난다."

    header = _declarations("table.dmap th")
    assert "position:sticky" in header and "top:0" in header
    assert "z-index:1" in header
    assert "background:var(--a-window)" in header


def test_capped_scrollport_inventory_matches_dom_and_behavior_contract() -> None:
    """허용된 캡 스크롤러는 DOM 에 있고 gutter/overscroll 계약을 공유한다.

    (「기안」 사망 정산 — F6 PR-B: .mapwrap 은 DOM 소비자가 죽어 목록에서 빠졌다.)

    **#wbMapPanel 편입(U2 §2.2).** 인벤토리 주석은 처음부터 「캡+헤더 지속 표」 셋에
    #wbMapPanel 을 세어 「이 여섯 종류」라고 적어 뒀는데 선택자 목록엔 다섯만 있었다 —
    주석과 규칙이 갈린 자리였다. 작업대 좌 pane 은 행 수가 매 작업점마다 바뀌는 캡 표라
    stable gutter 가 없으면 스크롤바 출현·소멸이 그대로 폭 점프가 된다. 우 pane
    .wb-preview 는 계속 목록 밖이다 — 표가 아니라 본문 면이고 주석의 여섯에도 없다.
    """
    inventory = {
        ".tblwrap": EDITOR,
        ".jobtbwrap": JOB_READ,
        "#wbMapPanel": WORKBENCH,
        ".tpllist": DATA_PICKER,
        ".sheet-list": SHEET_PICKER,
        ".colpanel .cp-vals": DATAZONE,
    }
    dom_needles = {
        ".tblwrap": 'className: "tblwrap"',
        ".jobtbwrap": "jobtbwrap",
        "#wbMapPanel": 'id: "wbMapPanel"',
        ".tpllist": "tpllist",
        ".sheet-list": "sheet-list",
        ".colpanel .cp-vals": "cp-vals",
    }

    for selector, source in inventory.items():
        assert dom_needles[selector] in source, f"{selector}가 실제 DOM에서 사라졌습니다."
        declarations = _declarations(selector)
        assert "scrollbar-gutter:stable" in declarations, selector
        assert "overscroll-behavior:contain" in declarations, selector
