"""R4-01~R4-03 semantic data-* producer successor exact sets."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]
PICKER = {"act", "busy-lock", "dup-keep", "key", "name", "row"}
LIBRARY = {
    "axis", "busy-lock", "clear-filters", "clone", "del-corrupt", "delete", "edit",
    "fav", "group", "group-more", "label", "move", "new-work",
    "preserve-scroll", "relink", "rename", "reveal", "tags", "use", "val", "work",
}
LIBRARY_VIEW = {"library-mode", "library-view"}
DATA_ZONE = {
    "act", "busy-lock", "col", "ctext", "i", "prune", "rerr", "rjoin", "rop",
    "rval", "unsel", "val", "val-all",
}
JOB_READ = {
    "browse-mode", "browse-new", "browse-open", "browse-pick", "browse-tab",
    "busy-lock", "cand", "cand-menu", "cand-mode", "cands-exit", "fav", "missing",
    "missing-cols", "new-work", "path", "preserve-scroll", "track-act",
}
JOB_RUN = {"act", "busy-lock", "field", "level", "state"}


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


def _names(rows: list[str], *paths: str) -> set[str]:
    prefixes = tuple(f"{path}:data-" for path in paths)
    return {row.split(":data-", 1)[1] for row in rows if row.startswith(prefixes)}


def test_r4_data_attribute_successor_groups_are_exact() -> None:
    rows = _axes()["js_planted_data_attrs"]
    picker = _names(rows, "frontend/src/screens/data_picker.ts")
    library_all = _names(rows, "frontend/src/screens/library.ts")
    data_zone = _names(rows, "frontend/src/screens/data_zone.ts")
    job_support = _names(
        rows, "frontend/src/screens/job_read.ts", "frontend/src/screens/path_actions.ts",
    )
    # R4-03 — 한 파일이 지던 다섯 이름이 React 세 장으로 갈렸다. **합집합이 계약**이다:
    # 파일별로 쪼개면 이름 하나가 이웃 파일로 옮겨 앉는 것까지 계약이 되어, 렌더 구조를
    # 바꿀 때마다 이 표가 붉는다(계약이 재려던 것은 「누가 심는가」이지 「어느 줄인가」가 아니다).
    job_run = _names(
        rows,
        "frontend/src/screens/job_run.ts",
        "frontend/src/screens/job_result.ts",
        "frontend/src/screens/job_preview.ts",
    )
    assert picker == PICKER and len(picker) == 6
    assert library_all == LIBRARY | LIBRARY_VIEW
    assert len(LIBRARY) == 21 and len(LIBRARY_VIEW) == 2
    assert data_zone == DATA_ZONE and len(data_zone) == 13
    assert job_support == JOB_READ and len(job_support) == 17
    assert job_run == JOB_RUN and len(job_run) == 5


def test_no_legacy_read_producer_or_dynamic_attribute_name_remains() -> None:
    axes = _axes()
    for path in (
        "frontend/js/data_picker.js", "frontend/js/datazone.js",
        "frontend/js/screens/library.js",
    ):
        assert not (ROOT / path).exists(), path
        assert all(not row.startswith(f"{path}:") for row in axes["js_planted_data_attrs"])
    assert axes["js_data_attr_dynamic"] == []
