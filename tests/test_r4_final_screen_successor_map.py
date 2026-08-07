"""R4-04 최종 화면 shell successor 지도.

R4-01~03의 화면 내부 지도와 달리 이 파일은 네 화면의 **바깥 shell**만 소유한다. 정적 stage
한 곳에서 ProductScreens가 만드는 18개 안정 ID와, 마지막으로 삭제되는 migration host 셋을
양방향으로 고정한다.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_SCREENS = "frontend/src/screens/product_screens.ts"

SCREEN_ROOTS = {"scr-library", "scr-job", "scr-editor", "scr-workbench"}
JOB_SHELL = {
    "jobStatus",
    "jobPanel",
    "jobZones",
    "jobDataGrid",
    "jobActionBar",
    "jobMirrorZone",
    "jobResultZone",
    "jobSideCard",
    "jobPreflight",
    "jobNoDataExit",
    "jobCandsRow",
    "jobRunCap",
    "jobOutRow",
    "jobRestate",
}
FINAL_SUCCESSORS = SCREEN_ROOTS | JOB_SHELL
REMOVED_MIGRATION_HOSTS = {
    "jobStatusHost",
    "jobDataHeaderReactHost",
    "jobDataBodyReactHost",
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


def _product_screen_ids() -> list[str]:
    values: list[str] = []
    for member in _axes()["js_template_ids"]:
        path_line, kind, value = member.rsplit(":", 2)
        path = path_line.rsplit(":", 1)[0]
        if path.startswith("frontend/src/screens/") and kind == "static":
            values.append(value)
    source = (ROOT / PRODUCT_SCREENS).read_text(encoding="utf-8")
    values.extend(
        f"scr-{screen}"
        for screen in ("library", "job", "editor", "workbench")
        if f'screenProps("{screen}"' in source
    )
    return values


def test_final_successor_map_is_exact_and_nonoverlapping() -> None:
    assert len(SCREEN_ROOTS) == 4
    assert len(JOB_SHELL) == 14
    assert SCREEN_ROOTS.isdisjoint(JOB_SHELL)
    assert len(FINAL_SUCCESSORS) == 18

    counts = Counter(_product_screen_ids())
    missing = FINAL_SUCCESSORS - counts.keys()
    assert not missing, f"ProductScreens가 만들지 않는 최종 successor: {sorted(missing)}"
    duplicated = {name: counts[name] for name in FINAL_SUCCESSORS if counts[name] != 1}
    assert not duplicated, f"최종 successor 생산 지점은 이름마다 하나여야 합니다: {duplicated}"


def test_static_stage_is_the_only_screen_host_left_in_html() -> None:
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    assert html.count('id="reactScreenStage"') == 1
    for element_id in FINAL_SUCCESSORS | REMOVED_MIGRATION_HOSTS:
        assert f'id="{element_id}"' not in html, element_id


def test_migration_hosts_have_zero_source_sites() -> None:
    offenders: set[str] = set()
    for path in (ROOT / "frontend").rglob("*"):
        if not path.is_file() or path.suffix not in {".html", ".js", ".ts", ".tsx", ".mjs"}:
            continue
        source = path.read_text(encoding="utf-8")
        for host in REMOVED_MIGRATION_HOSTS:
            if host in source:
                offenders.add(f"{path.relative_to(ROOT).as_posix()}:{host}")
    assert offenders == set(), f"migration host가 남았습니다: {sorted(offenders)}"


def test_final_map_predicate_bites_a_synthetic_duplicate() -> None:
    values = [*FINAL_SUCCESSORS, "scr-job"]
    counts = Counter(values)
    assert {name: counts[name] for name in FINAL_SUCCESSORS if counts[name] != 1} == {
        "scr-job": 2
    }
