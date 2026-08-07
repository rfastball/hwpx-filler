"""R4-01 static→React ID successor exact map.

R4-02 이 편집·매핑 표면을 같은 트리에 들이면서 이 파일의 정의역을 **자기 슬라이스가 옮긴
파일들**로 좁혔다. 좁히지 않으면 형제 슬라이스가 화면을 하나 더할 때마다 이 exact 집합이
빨개지고, 그 빨강을 끄려고 남의 ID 를 이쪽 표에 적게 된다(소유가 두 곳으로 갈린다).

좁힘이 사각을 만들지 않는다는 것은 형제 파일
``tests/test_r4_editor_static_to_js_successor_map.py`` 의 **분할 단언**이 진다 — 두 지도의
정의역 합집합이 `screens/` 의 ID 생산 파일 전수와 같은지 그쪽이 센다.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]

LIBRARY = {
    "libraryNewWork", "libraryAlerts", "libraryCorrupt", "librarySearch",
    "libraryViewLabel", "libraryViewTabs", "library-view-all", "library-view-recent",
    "library-view-favorites", "library-view-needsAction", "libraryModeLabel",
    "libraryModeFilters", "libraryFacets", "libraryPanel", "libraryCount",
    "libraryList", "libraryDetail",
}
JOB_READ = {
    "jobDataExpand", "jobDataLabel", "jobBtnPickData", "jobDataNotice",
    "jobRecsHead", "jobFilterSearch", "jobFilterReapply", "jobSelCount",
    "jobSelAll", "jobSelNone", "jobOrderBar", "jobOrderSel", "jobOrderNote",
    "jobFilterChips", "jobTableHost", "jobTableWrap", "jobTableHead", "jobTableBody",
    "jobTableEmpty", "jobSelStrip", "jobRangeFoot", "jobRangeNote",
    "jobRangeSelectedOnly", "jobRangeCancel", "jobRangeApply",
    "jobPickInLibrary", "jobCandidates",
}
OVERLAY = {
    "poolRegTitle", "poolRegName", "poolRegPath", "poolRegBrowse", "poolRegSheet",
    "poolRegNote", "poolRegCancel", "poolRegOk",
    "dataPickerTitle", "dataPickerNote", "dataPickerCurCap", "dataPickerCurrent",
    "dataPickerPinCap", "dataPickerPinned", "dataPickerDupes", "dataPickerCorrupt",
    "dataPickerOtherCap", "dataPickerBrowse", "dataPickerClose",
    "libraryMoveTitle", "libraryMoveName", "libraryMoveList", "libraryMoveErr",
    "libMoveCancel", "libMoveOk",
    "jobBrowseTitle", "jobBrowseClose", "jobBrowseTabs", "jobBrowseQuery",
    "jobBrowseNote", "jobBrowseRows",
}
EXISTING_STATIC = {
    "dataPickerPin", "libraryClearFacets", "jobCandMenuBtn", "jobCandNewWork",
    "jobBrowseOpen",
}


def _axes() -> dict[str, list[str]]:
    result = subprocess.run(
        ["node", "scripts/extract_js_ast_axes.mjs", "--repo-root", "."],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


#: 이 지도의 정의역 — R4-01 이 옮긴 파일들. 형제 슬라이스의 파일은 형제 지도가 든다.
OWNED_FILES = (
    "frontend/src/screens/library.ts",
    "frontend/src/screens/data_picker.ts",
    "frontend/src/screens/data_zone.ts",
    "frontend/src/screens/job_read.ts",
    "frontend/src/screens/path_actions.ts",
    "frontend/src/screens/host.ts",
)


def _screen_sites() -> list[tuple[str, str, str]]:
    rows = []
    for member in _axes()["js_template_ids"]:
        path_line, kind, value = member.rsplit(":", 2)
        if path_line.rsplit(":", 1)[0] not in OWNED_FILES:
            continue
        rows.append((path_line, kind, value))
    return rows


def test_r4_static_to_js_successor_sets_are_exact_and_unique() -> None:
    static = [value for _, kind, value in _screen_sites() if kind == "static"]
    counts = Counter(static)
    expected = LIBRARY | JOB_READ | OVERLAY
    assert len(LIBRARY) == 17
    assert len(JOB_READ) == 27
    assert len(OVERLAY) == 31
    assert all(counts[value] == 1 for value in expected), {
        value: counts[value] for value in expected if counts[value] != 1
    }
    assert set(static) == expected | EXISTING_STATIC | {"reactScreenStage"}


def test_migrated_ids_left_static_html_and_portal_targets_remain() -> None:
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    for migrated in LIBRARY | JOB_READ | OVERLAY:
        assert f'id="{migrated}"' not in html, migrated
    for target in {
        "scr-library", "poolRegModal", "dataPickerModal", "libraryMoveModal",
        "jobBrowseSheet", "jobDataHeaderReactHost", "jobDataBodyReactHost",
        "dataSheetSlot", "jobNoDataExit", "jobCandsRow",
    }:
        assert html.count(f'id="{target}"') == 1, target


def test_new_75_map_does_not_admit_unregistered_dynamic_ids() -> None:
    dynamic = {value for _, kind, value in _screen_sites() if kind == "dynamic"}
    assert dynamic == {
        "jobRow-", "jobFav-", "jobCand-", "jobBrowseTab-", "jobBrowseNeeds-",
        "jobBrowseRow-",
    }
