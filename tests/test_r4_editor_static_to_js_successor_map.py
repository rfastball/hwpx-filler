"""R4-02 static→React ID successor exact map.

R4-01 형제(``tests/test_r4_static_to_js_successor_map.py``)와 같은 질문을 편집·매핑 표면에
묻는다: **정적 HTML 에 있던 안정 ID 가 어느 React 생산자로 갔는가**. 개수만 세면 「하나
빼고 하나 더하기」가 조용하므로 값 집합을 exact 로 든다.

46 = 편집기 9 + 작업대 20 + TXT 저작 7 + 시트 선택 4 + 그룹 이동 6. 이 다섯은 이관 전
``docs/react_ownership_inventory.toml`` 의 subtree ``members_expected`` 였고, 그 수가 0 이
되면서 같은 ID 들이 여기로 옮겨 왔다 — **두 자리가 같은 46 을 든다**.

React 생산자는 정적 골격이 안 들던 ID 도 만든다(레이아웃 컨테이너·행동 버튼). 그것을
「미분류」로 두면 지도가 실제보다 좁게 읽히므로 `ADDED_BY_REACT` 로 따로 든다 — 늘어난 쪽도
집합이라 조용히 자라지 못한다.
"""

from __future__ import annotations

from collections import Counter
import itertools
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]

OWNED_FILES = (
    "frontend/src/screens/editor.ts",
    "frontend/src/screens/workbench.ts",
    "frontend/src/screens/group_move_dialog.ts",
    "frontend/src/screens/sheet_picker.ts",
    "frontend/src/screens/segment_view.ts",
)

#: 이관 전 `#scr-editor` subtree 9.
EDITOR = {
    "editorBack", "editorTitle", "editorName", "editorSubtitle", "editorSaveState",
    "editorContext", "editor-steps", "editor-body", "editor-foot",
}
#: 이관 전 `#scr-workbench` subtree 20.
WORKBENCH = {
    "wbBack", "wbMode", "wbTitle", "wbPosition", "wbCopied", "wbRevision", "wbNotice",
    "wbDirtyNote", "wbSaveRules", "wbMapPanel", "wbTargetFont", "wbReview", "wbDots",
    "wbCard", "wbLint", "wbAdvance", "wbNote", "wbPrev", "wbNext", "wbCopy",
}
#: 이관 전 `#txtEditModal` subtree 7.
TXT_EDIT = {
    "txtEditTitle", "txtNameRow", "txtEditName", "txtEditContent", "txtEditError",
    "txtEditCancel", "txtEditOk",
}
#: 이관 전 `#sheetModal` subtree 4.
SHEET = {"sheetTitle", "sheetModalFile", "sheetList", "sheetCancel"}
#: 이관 전 `#tplMoveModal` subtree 6.
TPL_MOVE = {
    "tplMoveTitle", "tplMoveName", "tplMoveList", "tplMoveErr", "tplMoveCancel", "tplMoveOk",
}

#: 정적 골격에 없던 ID — React 생산자가 새로 만든다.
#: `save-msg` 는 legacy editor.js 가 만들던 자리라 정적 subtree 밖이었고,
#: `wbLintAction` 도 같은 부류(legacy workbench.js 생산), `tplMoveNewRadio`·`tplMoveNewName`
#: 는 legacy `GroupList.createMoveDialog` 의 동적 사이트 둘의 후계다.
ADDED_BY_REACT = {"save-msg", "wbLintAction", "tplMoveNewRadio", "tplMoveNewName"}

#: 동적 prefix — 값이 아니라 **접두**가 계약이다(신원은 인코딩된 키가 진다).
DYNAMIC_PREFIXES = {
    "libgrp-",
    "wbMap-row-", "wbMap-src-", "wbMap-sug-", "wbMap-rev-",
    "wbMap-type-", "wbMap-fmt-", "wbMap-val-", "wbMap-ck-",
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


def _sites() -> list[tuple[str, str, str]]:
    rows = []
    for member in _axes()["js_template_ids"]:
        path_line, kind, value = member.rsplit(":", 2)
        path = path_line.rsplit(":", 1)[0]
        if path in OWNED_FILES:
            rows.append((path, kind, value))
    return rows


def test_r4_02_static_to_js_successor_sets_are_exact() -> None:
    static = [value for _, kind, value in _sites() if kind == "static"]
    migrated = EDITOR | WORKBENCH | TXT_EDIT | SHEET | TPL_MOVE
    assert (len(EDITOR), len(WORKBENCH), len(TXT_EDIT), len(SHEET), len(TPL_MOVE)) == (
        9, 20, 7, 4, 6,
    )
    assert len(migrated) == 46, "다섯 subtree 사이에 같은 ID 가 겹치면 안 됩니다."
    assert set(static) == migrated | ADDED_BY_REACT


def test_r4_02_ids_are_produced_once_each() -> None:
    """같은 ID 를 두 자리가 만들면 DOM 이 둘을 낳고 되읽기가 어느 쪽을 본지 모른다.

    예외는 **분기**다: 한 render 안에서 조건별로 갈리는 자리는 같은 ID 를 두 번 적지만
    동시에 서지 않는다. 그 셋을 이름으로 들어 둔다 — 목록이 자라면 이 단언이 먼저 붉다.
    """
    counts = Counter(value for _, kind, value in _sites() if kind == "static")
    branched = {name for name, count in counts.items() if count > 1}
    assert branched == {"editorContext", "editor-foot", "wbBack", "wbLintAction"}, branched


def test_r4_02_dynamic_prefixes_are_registered() -> None:
    dynamic = {value for _, kind, value in _sites() if kind == "dynamic"}
    assert dynamic == DYNAMIC_PREFIXES


def test_migrated_ids_left_static_html_and_portal_targets_remain() -> None:
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    for migrated in EDITOR | WORKBENCH | TXT_EDIT | SHEET | TPL_MOVE:
        assert f'id="{migrated}"' not in html, migrated
    for target in {"scr-editor", "scr-workbench", "txtEditModal", "sheetModal", "tplMoveModal"}:
        assert html.count(f'id="{target}"') == 1, target


def test_the_successor_maps_partition_the_screens_tree() -> None:
    """지도들의 정의역 합집합 = `screens/` 의 ID 생산 파일 전수.

    각 지도가 자기 슬라이스로 정의역을 좁혔으므로, 좁힘이 사각을 만들지 않는다는 사실을
    여기서 센다 — 새 화면 파일이 어느 지도에도 안 들면 그 ID 들은 exact 집합들 **밖**에서
    조용히 산다. 열거를 늘리는 대신 저장소가 답하게 한다.

    R4-03 이 실행·결과 표면을 들이며 지도가 셋이 됐다. 여기서 세는 것은 **개수가 아니라
    분할**이므로 지도가 몇이든 같은 두 문장(피복·비겹침)이면 된다 — 슬라이스마다 이 함수를
    고쳐 쓰면 그 자체가 다음 드리프트다.
    """
    from test_r4_static_to_js_successor_map import OWNED_FILES as R4_01_FILES
    from test_r4_job_run_static_to_js_successor_map import OWNED_FILES as R4_03_FILES

    maps = {"R4-01": set(R4_01_FILES), "R4-02": set(OWNED_FILES), "R4-03": set(R4_03_FILES)}
    producing = {
        member.rsplit(":", 2)[0].rsplit(":", 1)[0]
        for member in _axes()["js_template_ids"]
        if member.startswith("frontend/src/screens/")
    }
    claimed = set().union(*maps.values())
    assert producing - claimed == set(), (
        "어느 지도도 들지 않는 화면 파일이 ID 를 만듭니다: " f"{sorted(producing - claimed)}"
    )
    # 비겹침은 쌍마다 본다 — 합집합 크기 비교로 접으면 어느 둘이 부딪혔는지를 못 말한다.
    for left, right in itertools.combinations(sorted(maps), 2):
        overlap = maps[left] & maps[right]
        assert not overlap, f"{left}·{right} 지도가 같은 파일을 주장합니다: {sorted(overlap)}"


def test_segment_view_carries_token_identity_as_a_literal() -> None:
    """`data-token` 은 전개가 아니라 리터럴이라야 소유권 추출기가 본다.

    조건부 객체 전개(`...token`)로 쓰면 산출은 같은데 축의 분모에서 조용히 빠진다 —
    선언은 살고 결과가 죽는 그 결함류라 생산 형태 자체를 계약으로 든다.
    """
    source = (ROOT / "frontend/src/screens/segment_view.ts").read_text(encoding="utf-8")
    assert source.count('"data-token": token,') == 3
    assert "...token" not in source
    planted = _axes()["js_planted_data_attrs"]
    assert "frontend/src/screens/segment_view.ts:data-token" in planted
    assert "frontend/src/screens/sheet_picker.ts:data-first" in planted
