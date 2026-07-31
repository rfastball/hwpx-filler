"""Vite build graph·물리 source transition(N-03 M1)과 잎 ESM 전이(N-04) 계약."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from _web_source import (
    ALL_CSS_FILES,
    COMPAT_MODULE,
    ESM_FILES,
    LEGACY_JS_FILES,
    SOURCE_COMPAT,
    SOURCE_ENTRY,
    SOURCE_INDEX,
    SOURCE_JS_DIR,
    SOURCE_ROOT,
    compat_imports,
    entry_js_manifest,
    evaluated_modules,
    module_imports,
    side_effect_imports,
    strip_comments,
)

ROOT = Path(__file__).resolve().parents[1]

NODE_VERSION = "24.18.1"
NPM_VERSION = "11.16.0"
VITE_VERSION = "8.1.5"

EXPECTED_CSS_FILES = {
    "base.css",
    "draftcard.css",
    "editor.css",
    "forced-colors.css",
    "job.css",
    "jobdata.css",
    "library.css",
    "overlay.css",
    "tail.css",
    "tokens.css",
}
#: ESM 모듈이 내는 공개 이름 — 파일당 정확히 하나. 평범한 named export와 factory가 섞여
#: 있고, 그 갈림은 자의가 아니다: 의존이 다른 ESM 모듈뿐이면 named export, 아직 전역인
#: ``Bridge``/``Nav``를 쓰거나 factory 산물을 주입받아야 하면 ``create*`` factory다.
EXPECTED_ESM_EXPORTS = {
    # N-04 잎 넷
    "copy.js": "Copy",
    "esc.js": "escHtml",
    "guard.js": "Guard",
    "segview.js": "SegView",
    # N-05 서비스 — 포트가 필요 없어 모듈 평가가 곧 싱글턴인 일곱
    "popover.js": "Popover",
    "preserve.js": "Preserve",
    "intent.js": "Intent",
    "undo_toast.js": "UndoToast",
    "modal.js": "Modal",
    "surface_sheet.js": "SurfaceSheet",
    "grouplist.js": "GroupList",
    # N-05 서비스 — 포트를 받아 중앙에서 한 번 구성되는 여덟
    "theme.js": "createTheme",
    "personalization.js": "createPersonalization",
    "sheet_picker.js": "createSheetPicker",
    "pathtrack.js": "createPathTrack",
    "relink.js": "createRelink",
    "datazone.js": "createDataZone",
    "data_picker.js": "createDataPicker",
    "editor_entry.js": "createEditorEntry",
    # N-06 화면 넷 + 앱 셸 — Bridge·Nav·교차 화면 콜백·factory 산물을 주입받아
    # 중앙에서 한 번 구성되는 다섯
    "screens/library.js": "createLibraryScreen",
    "screens/editor.js": "createEditorScreen",
    "screens/job.js": "createJobScreen",
    "screens/workbench.js": "createWorkbenchScreen",
    "app.js": "createAppShell",
}

#: 중앙 compat 한 곳이 만드는 임시 전역 별칭 25개. factory 모듈의 별칭 이름은 export 이름
#: (``createTheme``)이 아니라 **구성된 산물의 이름**(``Theme``·``JobScreen``·``Nav``)이다.
#: 소비자(Python 직접 호출·selftest 프로브)가 그 이름으로 읽기 때문이다. N-06에서 화면 넷과
#: ``Nav``·``AppCloseGuard``가 자기 생산을 잃고 여기로 들어왔다 — 생산 자리는 하나여야
#: D-05의 "수량 단조 감소" 계측점이 산다.
EXPECTED_CENTRAL_COMPAT_GLOBALS = {
    "Copy",
    "Guard",
    "SegView",
    "escHtml",
    "DataPicker",
    "DataZone",
    "EditorEntry",
    "GroupList",
    "Intent",
    "Modal",
    "PathTrack",
    "Personalization",
    "Popover",
    "Preserve",
    "Relink",
    "SheetPicker",
    "SurfaceSheet",
    "Theme",
    "UndoToast",
    "LibraryScreen",
    "EditorScreen",
    "JobScreen",
    "WorkbenchScreen",
    "Nav",
    "AppCloseGuard",
}

#: 아직 자기 파일에서 자기 전역을 만드는 legacy IIFE 생산자 — ``bridge.js`` 하나(N-07 소유).
EXPECTED_LEGACY_GLOBALS = {
    "Bridge",
    "__push",
}

#: 런타임 전역 표면 전체 — N-04·N-05는 생산 **자리**만 옮기고 수량은 27 그대로다.
EXPECTED_RUNTIME_GLOBALS = (
    EXPECTED_LEGACY_GLOBALS | EXPECTED_CENTRAL_COMPAT_GLOBALS
)


def _run_text(*command: str) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"명령이 실패했습니다: {' '.join(command)}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stdout.strip()


def _vite_config() -> dict[str, Any]:
    node = shutil.which("node")
    assert node is not None, f"Node {NODE_VERSION}이 PATH에 없습니다"
    script = r"""
import path from "node:path";
import config from "./vite.config.mjs";

const relative = (value) => path.relative(process.cwd(), value).replaceAll("\\", "/");
console.log(JSON.stringify({
  root: relative(config.root),
  base: config.base,
  server: config.server,
  preview: config.preview,
  build: {
    outDir: relative(config.build.outDir),
    emptyOutDir: config.build.emptyOutDir,
    manifest: config.build.manifest,
    cssCodeSplit: config.build.cssCodeSplit,
    assetsInlineLimit: config.build.assetsInlineLimit,
    modulePreload: config.build.modulePreload,
    minify: config.build.minify,
    treeshake: config.build.rolldownOptions?.treeshake,
  },
}));
"""
    return json.loads(_run_text(node, "--input-type=module", "--eval", script))


def test_exact_node_npm_vite_pins_are_locked() -> None:
    node = shutil.which("node")
    npm = shutil.which("npm.cmd")
    assert node is not None, f"Node {NODE_VERSION}이 PATH에 없습니다"
    assert npm is not None, f"bundled npm.cmd {NPM_VERSION}이 PATH에 없습니다"
    assert _run_text(node, "--version") == f"v{NODE_VERSION}"
    assert _run_text(npm, "--version") == NPM_VERSION

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))

    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == NODE_VERSION
    assert package["packageManager"] == f"npm@{NPM_VERSION}"
    assert package["engines"] == {"node": NODE_VERSION, "npm": NPM_VERSION}
    assert package["devDependencies"] == {"vite": VITE_VERSION}
    assert lock["lockfileVersion"] == 3
    assert lock["packages"][""]["devDependencies"] == {"vite": VITE_VERSION}
    assert lock["packages"]["node_modules/vite"]["version"] == VITE_VERSION

    npmrc = (ROOT / ".npmrc").read_text(encoding="utf-8").splitlines()
    assert npmrc == ["engine-strict=true", "save-exact=true"]


def test_product_scripts_offer_build_only() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["type"] == "module"
    assert package["scripts"] == {
        "build": "vite build && uv run python scripts/seal_web_artifact.py",
        "verify:web": "uv run python scripts/seal_web_artifact.py --verify",
    }
    assert {"dev", "serve", "start", "preview"}.isdisjoint(package["scripts"])


def test_vite_production_graph_is_atomic_and_relative() -> None:
    config = _vite_config()

    assert config == {
        "root": "frontend",
        "base": "./",
        "build": {
            "outDir": "build/web",
            "emptyOutDir": True,
            "manifest": True,
            "cssCodeSplit": False,
            "assetsInlineLimit": 0,
            "modulePreload": False,
            "minify": False,
            "treeshake": False,
        },
    }


def test_frontend_is_the_only_physical_source_tree() -> None:
    config = _vite_config()

    assert config["root"] == SOURCE_ROOT.relative_to(ROOT).as_posix()
    assert SOURCE_ROOT.is_dir()
    assert SOURCE_ROOT.name == "frontend"
    assert "web" not in {path.name for path in ROOT.iterdir() if path.is_dir()}
    assert {path.name for path in (SOURCE_ROOT / "css").glob("*.css")} == (
        EXPECTED_CSS_FILES
    )


def test_product_entry_is_one_module_with_ordered_side_effect_graph() -> None:
    html = SOURCE_INDEX.read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b[^>]*\bsrc=\"[^\"]+\"[^>]*></script>", html)

    assert scripts == ['<script type="module" src="./src/main.js"></script>']
    expected_imports = (
        *(f"../css/{name}" for name in ALL_CSS_FILES),
        *entry_js_manifest(),
    )
    assert side_effect_imports(SOURCE_ENTRY.read_text(encoding="utf-8")) == (
        expected_imports
    )


def test_converted_modules_are_esm_and_own_no_globals() -> None:
    """ESM 19개는 IIFE도 전역 생산자도 아니고 자기 공개 이름 하나만 낸다.

    M1의 "25 IIFE 전수"를 이 후계가 잇는다. 여기서 수량만 세면 모듈이 export를 내면서
    ``window.SegView`` 도 같이 남기는 이중 유지가 통과한다 — 그래서 파일별로 IIFE 0,
    자기 전역 write 0, 정확한 export 이름을 함께 단언한다.

    잎 넷과 달리 서비스 열다섯은 표준 Web API(``window.addEventListener``·``window.alert``·
    ``window.pywebview`` 등)를 정당하게 쓴다. 그래서 "``window.`` 문자열 0"으로는 셀 수 없고,
    금지 대상은 **제품 전역 이름**이다. 그 목록을 :data:`EXPECTED_RUNTIME_GLOBALS` 에서
    가져오므로, 새 제품 전역이 생기면 이 음성 검사도 저절로 넓어진다.
    """
    assert set(EXPECTED_ESM_EXPORTS) == set(ESM_FILES)
    assert len(ESM_FILES) == 24

    product_globals = re.compile(
        r"\b(?:window|globalThis)\.(?:"
        + "|".join(sorted(map(re.escape, EXPECTED_RUNTIME_GLOBALS)))
        + r")\b"
    )

    for name in ESM_FILES:
        source = (SOURCE_JS_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\(function \(\) \{", source), (
            f"{name} 이 아직 IIFE 로 감싸져 있습니다 — N-04·N-05 는 true ESM 입니다."
        )
        assert not re.search(
            r"(?m)^\s*(?:window|globalThis)\.[A-Za-z_$][A-Za-z0-9_$]*\s*=", source
        ), f"{name} 이 자기 전역을 만듭니다 — 별칭은 중앙 compat 하나가 만듭니다."
        leaked = product_globals.findall(source)
        assert not leaked, (
            f"{name} 이 제품 전역을 직접 조회합니다: {sorted(set(leaked))} — "
            "의존은 import 나 명시적 주입으로 드러나야 합니다."
        )
        assert "Object.assign(window" not in source.replace(" ", ""), (
            f"{name} 이 window 에 일괄 대입합니다."
        )
        exported = set(
            re.findall(
                r"(?m)^export\s+(?:const|let|var|function|class)\s+"
                r"([A-Za-z_$][A-Za-z0-9_$]*)",
                source,
            )
        )
        assert exported == {EXPECTED_ESM_EXPORTS[name]}, (
            f"{name} 의 공개 표면이 {sorted(exported)} 입니다 — "
            f"{EXPECTED_ESM_EXPORTS[name]} 하나여야 합니다."
        )
        assert "export default" not in source, f"{name} 이 default export 를 냅니다."


def test_service_dependencies_are_written_edges_not_global_lookups() -> None:
    """서비스 간·잎 의존이 **그래프에 적힌 단방향 간선**이다(암묵 로드 순서의 후계).

    N-05 전에는 ``modal.js`` 가 ``window.Popover`` 를, 다섯 파일이 ``window.escHtml`` 을
    모듈 로드 시점에 붙들었다. 그 계약들은 "누가 먼저 실리는가"를 entry 순서에서 물었는데,
    그 질문은 이제 import 문 자체가 답한다.
    """
    expected_edges = {
        "modal.js": {"./popover.js"},
        "surface_sheet.js": {"./modal.js"},
        "grouplist.js": {"./esc.js", "./popover.js", "./modal.js"},
        "datazone.js": {"./esc.js", "./popover.js", "./intent.js"},
        "pathtrack.js": {"./esc.js"},
        "relink.js": {"./modal.js"},
        "sheet_picker.js": {"./esc.js", "./modal.js"},
        "data_picker.js": {"./esc.js", "./modal.js", "./preserve.js"},
        "editor_entry.js": {"./modal.js"},
        "segview.js": {"./esc.js"},
        # N-06 화면 넷 — named export 서비스·잎만 import 간선으로 적는다. factory 산물
        # (EditorEntry·PathTrack 등)과 교차 화면·Nav 는 주입이라 여기 없어야 한다.
        "screens/library.js": {
            "../esc.js", "../grouplist.js", "../intent.js", "../modal.js",
            "../popover.js", "../preserve.js", "../undo_toast.js",
        },
        "screens/editor.js": {
            "../esc.js", "../grouplist.js", "../intent.js", "../modal.js",
            "../popover.js", "../preserve.js", "../undo_toast.js",
        },
        "screens/job.js": {
            "../esc.js", "../modal.js", "../popover.js", "../preserve.js",
            "../intent.js", "../surface_sheet.js", "../grouplist.js", "../guard.js",
        },
        "screens/workbench.js": {
            "../esc.js", "../intent.js", "../modal.js", "../preserve.js", "../segview.js",
        },
        "app.js": {"./modal.js", "./surface_sheet.js"},
    }

    for name, expected in expected_edges.items():
        source = (SOURCE_JS_DIR / name).read_text(encoding="utf-8")
        actual = {path for path in module_imports(source) if path.startswith(".")}
        assert actual == expected, (
            f"{name} 의 모듈 간선이 {sorted(actual)} 입니다 — {sorted(expected)} 여야 합니다."
        )

    #: 화면 간 직접 import 0 — 교차 간선은 compat 의 late-bound 콜백 테이블만 진다.
    for name in ("screens/library.js", "screens/editor.js", "screens/job.js",
                 "screens/workbench.js", "app.js"):
        source = (SOURCE_JS_DIR / name).read_text(encoding="utf-8")
        crossing = [p for p in module_imports(source)
                    if "screens/" in p or p.endswith("/app.js") or p == "./app.js"]
        assert not crossing, (
            f"{name} 이 다른 화면·셸을 직접 import 합니다: {crossing} — "
            "교차 간선은 중앙 콜백 테이블이 집니다."
        )

    #: 간선이 없어야 하는 모듈은 정말 없어야 한다(잎다움의 음성 대조).
    for name in ("copy.js", "esc.js", "guard.js", "popover.js", "preserve.js",
                 "intent.js", "undo_toast.js", "theme.js", "personalization.js"):
        source = (SOURCE_JS_DIR / name).read_text(encoding="utf-8")
        assert not [p for p in module_imports(source) if p.startswith("./")], (
            f"{name} 이 다른 제품 모듈을 import 합니다 — 잎이 아니게 됐습니다."
        )


def test_esm_module_graph_has_no_cycles() -> None:
    """제품 모듈 그래프에 순환이 0이다.

    N-05 의 순환 후보는 ``editor_entry ↔ app`` 하나였고, N-06 에서 화면 넷이 그래프에
    들어오며 ``editor ↔ job``·``library → job``·화면→Nav 가 새 후보로 늘었다. 그 간선들은
    전부 compat 의 late-bound 콜백 테이블이 그래프 밖에서 지므로 여기서 0이 나온다 —
    화면이 서로를(또는 앱 셸을) import 하는 구현으로 되돌아가면 이 게이트가 잡는다.
    """
    from posixpath import dirname, join, normpath

    graph = {
        name: [
            normpath(join(dirname(name), path))
            for path in module_imports((SOURCE_JS_DIR / name).read_text(encoding="utf-8"))
            if path.startswith(".")
        ]
        for name in ESM_FILES
    }
    graph[COMPAT_MODULE] = list(compat_imports())

    seen: dict[str, int] = {}

    def visit(node: str, trail: tuple[str, ...]) -> None:
        if seen.get(node) == 1:
            raise AssertionError(f"import 순환: {' -> '.join((*trail, node))}")
        if seen.get(node) == 2:
            return
        seen[node] = 1
        for nxt in graph.get(node, ()):
            visit(nxt, (*trail, node))
        seen[node] = 2

    for name in graph:
        visit(name, ())


def test_segview_imports_the_escaper_instead_of_reading_a_global() -> None:
    """SegView→esc 는 이제 그래프에 적힌 단방향 간선이다(로드 순서 암묵 계약의 후계)."""
    source = (SOURCE_JS_DIR / "segview.js").read_text(encoding="utf-8")

    assert re.search(
        r'(?m)^import\s+\{\s*escHtml\s*\}\s+from\s+"\./esc\.js";', source
    ), "segview.js 가 escHtml 을 ESM import 하지 않습니다."


def test_temporary_aliases_have_exactly_one_central_producer() -> None:
    """열아홉 별칭은 중앙 compat 한 파일에서만 만들어진다(D-05 단일 생산자).

    파일마다 되살리면 소비자는 그대로 동작하므로 **동작 테스트로는 안 보인다**. 생산 자리를
    세는 이 게이트만 그 회귀를 잡는다.
    """
    compat_source = SOURCE_COMPAT.read_text(encoding="utf-8")
    producers = re.findall(
        r"(?m)^\s*window\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=", compat_source
    )

    assert SOURCE_COMPAT.name == COMPAT_MODULE
    assert sorted(producers) == sorted(EXPECTED_CENTRAL_COMPAT_GLOBALS)
    assert len(producers) == len(set(producers)) == len(EXPECTED_CENTRAL_COMPAT_GLOBALS) == 25
    assert set(compat_imports()) == set(ESM_FILES), (
        "compat 의 import 집합이 ESM 모듈 전수와 어긋납니다 — 별칭이 export 와 갈라집니다."
    )

    elsewhere = {
        f"{path.relative_to(SOURCE_ROOT).as_posix()}:{alias}"
        for path in sorted(SOURCE_ROOT.rglob("*.js"))
        if path != SOURCE_COMPAT
        for alias in re.findall(
            r"(?m)^\s*window\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=",
            path.read_text(encoding="utf-8"),
        )
        if alias in EXPECTED_CENTRAL_COMPAT_GLOBALS
    }
    assert not elsewhere, (
        "전역 별칭이 중앙 compat 밖에서 다시 만들어집니다: " + ", ".join(sorted(elsewhere))
    )


def test_each_service_is_constructed_exactly_once_in_compat() -> None:
    """포트를 받는 factory 열셋(서비스 8 + 화면 4 + 앱 셸)은 compat 에서 **정확히 한 번** 불린다.

    두 번 부르면 ``pathtrack`` 의 위임 리스너가 겹치고 ``data_picker`` 의 ``onPush`` 가
    누적되며, 화면·앱 셸은 DOM 리스너와 부팅 랜딩이 두 벌이 된다. 모듈 안에 재호출 가드를
    두는 대신 호출 자리를 하나로 묶었으므로, 그 단일성은 여기서 세야 한다.
    """
    #: 이 파일의 헤더 주석은 ``Nav`` 를 값으로 붙들면 안 되는 **이유**를 적는다.
    #: 그 산문을 코드로 세면 "판독이 한 곳뿐인가"라는 질문이 주석 길이에 좌우된다.
    compat_source = strip_comments(SOURCE_COMPAT.read_text(encoding="utf-8"))
    factories = sorted(
        export for name, export in EXPECTED_ESM_EXPORTS.items()
        if export.startswith("create")
    )

    assert len(factories) == 13
    for factory in factories:
        calls = re.findall(rf"\b{re.escape(factory)}\s*\(", compat_source)
        assert len(calls) == 1, (
            f"compat 이 {factory} 를 {len(calls)}회 부릅니다 — 정확히 1회여야 합니다."
        )

    #: `navigate` 는 지연 호출 콜백이다 — N-05 의 `window.Nav` 판독은 Nav 생산이 compat 으로
    #: 들어오며(N-06) 지역 late-bound 참조로 좁혀졌다. 값으로 캡처하면 앱 셸 구성 전의
    #: `undefined` 를 붙든다.
    assert re.search(r"const navigate = \(\.\.\.args\) => Nav\.go\(\.\.\.args\);",
                     compat_source), "navigate 가 지연 호출 콜백이 아닙니다."
    #: `window.Nav` 는 이제 **별칭 대입 한 줄**뿐이다 — 판독이 되살아나면 순환이 전역 경유로
    #: 숨는다.
    assert re.findall(r"window\.Nav\b(?!\s*=)", compat_source) == []
    assert compat_source.count("window.Nav") == 1
    #: `bridge` 는 객체째 넘긴다 — 메서드를 뽑으면 Python 프로브의 스텁 교체가 우회된다.
    assert re.search(r"const bridge = window\.Bridge;", compat_source)
    assert compat_source.count("window.Bridge") == 1

    #: 교차 화면·Nav 콜백 테이블은 지연 호출이어야 한다 — 값 캡처(`JobScreen.refreshList` 를
    #: 프로퍼티로 뽑아 저장)로 되돌아가면 구성 순서에 따라 undefined 를 붙든다.
    for member in ("refreshList", "openPreview", "openBrowseNeedsAction"):
        assert re.search(
            rf"{member}: \(\.\.\.args\) => JobScreen\.{member}\(\.\.\.args\),",
            compat_source,
        ), f"jobCallbacks.{member} 가 지연 호출 콜백이 아닙니다."
    assert re.search(
        r"aimAt: \(\.\.\.args\) => EditorScreen\.aimAt\(\.\.\.args\),", compat_source
    ), "editorCallbacks.aimAt 가 지연 호출 콜백이 아닙니다."
    for member in ("go", "refresh"):
        assert re.search(
            rf"{member}: \(\.\.\.args\) => Nav\.{member}\(\.\.\.args\),", compat_source
        ), f"navigation.{member} 가 지연 호출 콜백이 아닙니다."

    #: 별칭 25개는 전부 **모든 구성 뒤**에 선다 — 구성 전의 별칭 대입은 undefined 를 걸어
    #: Python 소비자가 조용히 빈 통로를 읽는다(선언-사용 순서 계약, entry 순서 계약의 후계).
    last_construction = max(
        compat_source.rindex(f"{factory}(") for factory in factories
    )
    first_alias = min(
        compat_source.index(f"window.{alias} =")
        for alias in EXPECTED_CENTRAL_COMPAT_GLOBALS
    )
    assert last_construction < first_alias, (
        "compat 의 별칭 대입이 factory 구성보다 먼저 섭니다 — 미구성 값이 전역에 걸립니다."
    )


def test_remaining_legacy_iife_and_total_global_surface_are_unchanged() -> None:
    """남은 IIFE 는 ``bridge.js`` 하나뿐이고, 제품 전역 표면 전체는 여전히 27개다.

    M1 의 "25 IIFE / 27 globals" 계약의 마지막 후계다: 25 파일 중 24 가 ESM 이 됐고
    수량은 자리만 옮겼다(compat 25 + legacy 2 = 27). 새 전역이 생기거나 화면이 자기
    전역 생산을 되살리면 여기서 잡힌다.
    """
    legacy_scripts = tuple(sorted(SOURCE_JS_DIR.rglob("*.js")))
    legacy_only = tuple(
        path
        for path in legacy_scripts
        if path.relative_to(SOURCE_JS_DIR).as_posix() not in ESM_FILES
    )

    assert len(legacy_scripts) == 25
    assert len(legacy_only) == 1
    assert {
        path.relative_to(SOURCE_JS_DIR).as_posix() for path in legacy_only
    } == set(LEGACY_JS_FILES)

    sources = {
        path.relative_to(SOURCE_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in legacy_only
    }
    assert all(
        len(re.findall(r"(?m)^\(function \(\) \{", source)) == 1
        for source in sources.values()
    )
    legacy_globals = {
        match
        for source in sources.values()
        for match in re.findall(
            r"(?m)^\s*window\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=",
            source,
        )
    }

    assert legacy_globals == EXPECTED_LEGACY_GLOBALS
    assert len(legacy_globals) == 2
    assert legacy_globals.isdisjoint(EXPECTED_CENTRAL_COMPAT_GLOBALS)
    assert len(EXPECTED_RUNTIME_GLOBALS) == 27


def test_entry_evaluates_bridge_then_compat_only() -> None:
    """제품 entry 의 JS 는 정확히 ``bridge.js → compat.js`` 둘이고 그 순서다.

    "compat 이 모든 소비 IIFE 보다 먼저 평가된다"던 계약의 후계다 — 소비 IIFE 가 전부
    ESM 이 되어 entry 에서 사라졌으므로, 남은 순서 질문은 하나다: compat 은 평가 시점에
    ``window.Bridge`` 를 객체째 캡처하므로 **bridge 가 먼저**여야 한다. 화면·서비스가
    entry 에 직접 남아 있으면 모듈이 두 경로로 그래프에 들어와 compat 의 구성-후-별칭
    순서 추론이 무의미해지므로 그 부재도 같이 본다. compat 내부의 구성→별칭 순서는
    :func:`test_each_service_is_constructed_exactly_once_in_compat` 이, 그래프 순환 부재는
    :func:`test_esm_module_graph_has_no_cycles` 가 진다.
    """
    modules = evaluated_modules(SOURCE_ENTRY.read_text(encoding="utf-8"))

    assert modules == (*LEGACY_JS_FILES, COMPAT_MODULE) == ("bridge.js", COMPAT_MODULE)
    assert not set(modules) & set(ESM_FILES)
