"""R4-01 기존 JS ID 11곳의 React successor 계약."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]
STATIC = {
    "dataPickerPin": "frontend/src/screens/data_picker.ts",
    "libraryClearFacets": "frontend/src/screens/library.ts",
    "jobCandMenuBtn": "frontend/src/screens/job_read.ts",
    "jobCandNewWork": "frontend/src/screens/job_read.ts",
    "jobBrowseOpen": "frontend/src/screens/job_read.ts",
}
DYNAMIC = {
    "jobRow-": "frontend/src/screens/data_zone.ts",
    "jobFav-": "frontend/src/screens/job_read.ts",
    "jobCand-": "frontend/src/screens/job_read.ts",
    "jobBrowseTab-": "frontend/src/screens/job_read.ts",
    "jobBrowseNeeds-": "frontend/src/screens/job_read.ts",
    "jobBrowseRow-": "frontend/src/screens/job_read.ts",
}


def _sites() -> list[tuple[str, str, str]]:
    result = subprocess.run(
        ["node", "scripts/extract_js_ast_axes.mjs", "--repo-root", "."],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    rows = json.loads(result.stdout)["js_template_ids"]
    parsed = []
    for row in rows:
        path_line, kind, value = row.rsplit(":", 2)
        parsed.append((path_line.rsplit(":", 1)[0], kind, value))
    return parsed


def test_existing_11_id_successors_have_exact_kind_path_and_one_site() -> None:
    sites = _sites()
    counts = Counter((path, kind, value) for path, kind, value in sites)
    expected = {
        **{value: (path, "static") for value, path in STATIC.items()},
        **{value: (path, "dynamic") for value, path in DYNAMIC.items()},
    }
    assert len(expected) == 11
    for value, (path, kind) in expected.items():
        assert counts[(path, kind, value)] == 1, (path, kind, value)


def test_dynamic_name_successors_keep_encoding_and_row_focus_prefix() -> None:
    job = (ROOT / "frontend/src/screens/job_read.ts").read_text(encoding="utf-8")
    zone = (ROOT / "frontend/src/screens/data_zone.ts").read_text(encoding="utf-8")
    assert "const key = encodeURIComponent(row.name);" in job
    for prefix in ("jobFav-", "jobCand-", "jobBrowseNeeds-", "jobBrowseRow-"):
        assert prefix in job
    assert "jobBrowseTab-${key}" in job
    assert "jobRow-${row.index}" in zone
