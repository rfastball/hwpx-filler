"""R4-04 ProductScreens 전환의 fail-closed 소스 census.

이 파일은 최종 형상의 **부재**를 함께 센다. ``ProductScreens``가 생겼다는 양성만 보면
옛 portal/집행자/위임 listener가 같이 남아도 초록이기 때문이다. 각 census는 합성 음성
표본에도 다시 적용해, 정규식이 빈 결과만 내는 공허한 초록을 막는다.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from _web_source import SOURCE_INDEX, SOURCE_ROOT, module_imports


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_SCREENS = SOURCE_ROOT / "src/screens/product_screens.ts"
BOOTSTRAP = SOURCE_ROOT / "src/bootstrap.js"
APP = SOURCE_ROOT / "src/shell/app.ts"

SCREEN_IDS = ("library", "job", "editor", "workbench")
FINAL_SUCCESSORS = {
    "scr-library",
    "scr-job",
    "scr-editor",
    "scr-workbench",
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
MIGRATION_HOSTS = {
    "jobStatusHost",
    "jobDataHeaderReactHost",
    "jobDataBodyReactHost",
}


def _product_sources() -> dict[str, str]:
    return {
        path.relative_to(SOURCE_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in SOURCE_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in {".js", ".ts", ".tsx", ".mjs"}
        and "src/selftest/" not in path.relative_to(SOURCE_ROOT).as_posix()
    }


def _strip_comments(source: str) -> str:
    """C-가족 주석만 걷는다. 문자열까지 지우면 import/호출 census가 공허해진다."""
    return re.sub(r"/\*.*?\*/|//[^\r\n]*", "", source, flags=re.S)


def _bare_call_census(sources: dict[str, str], callee: str) -> dict[str, int]:
    """정의·멤버 호출을 뺀 날 ``callee(…)`` 전수."""
    pattern = re.compile(rf"(?<![.\w$])(?<!function ){re.escape(callee)}\s*\(")
    return {
        name: count
        for name, source in sources.items()
        if (count := len(pattern.findall(_strip_comments(source))))
    }


def _legacy_screen_offenders(sources: dict[str, str]) -> set[str]:
    """PathTrack/GroupList의 import·factory·문서 위임 listener 회귀 전수."""
    offenders: set[str] = set()
    for name, raw in sources.items():
        source = _strip_comments(raw)
        for specifier in module_imports(source):
            if specifier.endswith(("/pathtrack.js", "/grouplist.js")):
                offenders.add(f"{name}:import:{Path(specifier).name}")
        if re.search(r"(?<![.\w$])createPathTrack\s*\(", source):
            offenders.add(f"{name}:factory:createPathTrack")
        if re.search(r"\bGroupList\s*\.\s*createMenu\s*\(", source):
            offenders.add(f"{name}:factory:GroupList.createMenu")
        # 구 PathTrack은 document click 위임과 data-track-act 판독을 한 파일에 함께 뒀다.
        if re.search(r"document\s*\.\s*addEventListener\s*\(\s*[\"']click[\"']", source) \
                and "data-track-act" in source:
            offenders.add(f"{name}:listener:pathtrack-document-click")
        # 구 GroupList 소비자는 안정 menu id를 찾아 click listener를 직접 붙였다.
        if re.search(
            r"getElementById\s*\(\s*[\"'](?:libraryGroupMenu|tplRowMenu)[\"']\s*\)"
            r"[\s\S]{0,500}?addEventListener\s*\(\s*[\"']click[\"']",
            source,
        ):
            offenders.add(f"{name}:listener:grouplist-menu-click")
    return offenders


def _migration_host_sites(texts: dict[str, str]) -> set[str]:
    return {
        f"{name}:{host}"
        for name, text in texts.items()
        for host in MIGRATION_HOSTS
        if host in _strip_comments(text)
    }


def test_one_static_stage_and_one_react_root_factory() -> None:
    """HTML stage 하나 + 날 createRoot 한 곳이 화면 네 개를 모두 품는다."""
    html = SOURCE_INDEX.read_text(encoding="utf-8")
    sources = _product_sources()

    assert html.count('id="reactScreenStage"') == 1
    assert all(html.count(f'id="scr-{screen}"') == 0 for screen in SCREEN_IDS)
    assert _bare_call_census(sources, "createRoot") == {"src/react/boot.ts": 1}


def test_product_screen_set_and_visibility_projection_are_exact() -> None:
    """화면 집합과 `.on`·hidden·inert·aria-hidden은 같은 ``on`` 판정의 투영이다."""
    source = PRODUCT_SCREENS.read_text(encoding="utf-8")
    match = re.search(
        r"PRODUCT_SCREEN_IDS\s*=\s*Object\.freeze\s*\(\s*\[([^]]+)]",
        _strip_comments(source),
    )
    assert match is not None, "PRODUCT_SCREEN_IDS 리터럴을 찾지 못했습니다."
    assert tuple(re.findall(r'[\"\']([^\"\']+)[\"\']', match.group(1))) == SCREEN_IDS

    props = re.search(
        r"function\s+screenProps\b[\s\S]*?\n}\s*\n\s*function\s+JobScreen",
        _strip_comments(source),
    )
    assert props is not None, "네 화면의 공용 visibility projection을 찾지 못했습니다."
    body = props.group(0)
    for needle in (
        'className: `scr${on ? " on" : ""}`',
        "hidden: !on",
        "inert: !on",
        '"aria-hidden": on ? "false" : "true"',
    ):
        assert needle in body, f"visibility 네 축이 한 판정에서 갈리지 않습니다: {needle}"


def test_final_successor_and_removed_host_census_is_exact() -> None:
    """최종 18 successor는 ProductScreens가 만들고 migration host 셋은 전 소스 0이다."""
    sources = _product_sources()
    produced = {
        value
        for source in sources.values()
        for value in re.findall(r'\bid:\s*[`\"\']([^`\"\']+)[`\"\']', source)
    }
    product_source = PRODUCT_SCREENS.read_text(encoding="utf-8")
    produced |= {
        f"scr-{screen}"
        for screen in SCREEN_IDS
        if re.search(rf'screenProps\(\s*[\"\']{screen}[\"\']', product_source)
    }
    assert FINAL_SUCCESSORS <= produced, sorted(FINAL_SUCCESSORS - produced)
    assert len(FINAL_SUCCESSORS) == 18

    texts = sources
    texts["index.html"] = SOURCE_INDEX.read_text(encoding="utf-8")
    assert _migration_host_sites(texts) == set()


def test_shell_executor_has_one_binding_and_app_adapter_has_none() -> None:
    sources = _product_sources()
    sites = {
        name: len(re.findall(r"\.bindExecutor\s*\(", _strip_comments(source)))
        for name, source in sources.items()
        if re.search(r"\.bindExecutor\s*\(", _strip_comments(source))
    }
    assert sites == {"src/bootstrap.js": 1}
    assert ".bindExecutor(" not in _strip_comments(APP.read_text(encoding="utf-8"))


def test_pathtrack_and_grouplist_execution_paths_are_retired() -> None:
    sources = _product_sources()
    assert not (SOURCE_ROOT / "js/pathtrack.js").exists()
    assert not (SOURCE_ROOT / "js/grouplist.js").exists()
    assert _legacy_screen_offenders(sources) == set()


def test_r4_product_screens_inventory_metric_is_fail_closed() -> None:
    """rev5의 11개 독립 눈을 그대로 든다 — 한 합성 정규식으로 11을 접지 않는다."""
    document = tomllib.loads(
        (ROOT / "docs/react_ownership_inventory.toml").read_text(encoding="utf-8")
    )
    metrics = {row["id"]: row for row in document["metric"]}
    metric = metrics["r4_product_screens_integration"]
    assert metric["value"] == 1, "main은 날 createRoot invocation 정확히 하나다."
    assert "createRoot" in metric["predicate"]["pattern"]
    assert metric["scope"]
    assert metric["unit"]

    aliases = metric.get("aliases", [])
    assert [alias["value"] for alias in aliases] == [1, 1, 1, 0, 1, 2, 0, 0, 0, 5], (
        "rev5 독립 측정 순서(stage/ProductScreens/bind/app-bind/flush/owners/legacy-screen/"
        "PathTrack/GroupList/ledger)가 어긋났습니다."
    )
    for index, alias in enumerate(aliases):
        assert alias.get("predicate"), f"alias {index}: 술어가 없습니다."
        assert alias.get("scope"), f"alias {index}: scope가 없습니다."
        assert alias.get("unit"), f"alias {index}: unit이 없습니다."


def test_census_predicates_bite_synthetic_negative_fixtures() -> None:
    create_root_probe = {
        "src/react/boot.ts": 'import { createRoot } from "react-dom/client"; createRoot(a);',
        "src/react/island.ts": 'import { createRoot } from "react-dom/client"; createRoot(b);',
        "src/react/disguised.ts": "function createRoot(x) {} deps.createRoot(x);",
    }
    assert _bare_call_census(create_root_probe, "createRoot") == {
        "src/react/boot.ts": 1,
        "src/react/island.ts": 1,
    }

    legacy_probe = {
        "src/a.js": 'import { createPathTrack } from "../js/pathtrack.js"; createPathTrack({});',
        "src/b.js": 'import { GroupList } from "../js/grouplist.js"; GroupList.createMenu({});',
        "src/c.js": (
            'document.addEventListener("click", handler); '
            'target.closest("[data-track-act]");'
        ),
        "src/d.js": (
            'document.getElementById("libraryGroupMenu")'
            '.addEventListener("click", handler);'
        ),
    }
    assert _legacy_screen_offenders(legacy_probe) == {
        "src/a.js:import:pathtrack.js",
        "src/a.js:factory:createPathTrack",
        "src/b.js:import:grouplist.js",
        "src/b.js:factory:GroupList.createMenu",
        "src/c.js:listener:pathtrack-document-click",
        "src/d.js:listener:grouplist-menu-click",
    }

    assert _migration_host_sites({"probe.ts": 'el("div", {id:"jobStatusHost"})'}) == {
        "probe.ts:jobStatusHost"
    }
