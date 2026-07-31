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
    COMPAT_ENTRY_POSITION,
    COMPAT_MODULE,
    LEAF_ESM_FILES,
    LEGACY_JS_FILES,
    SOURCE_COMPAT,
    SOURCE_ENTRY,
    SOURCE_INDEX,
    SOURCE_JS_DIR,
    SOURCE_ROOT,
    entry_js_manifest,
    evaluated_modules,
    side_effect_imports,
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
#: N-04에서 중앙 compat 한 곳이 만드는 임시 전역 별칭 — 잎 넷의 named export와 1:1이다.
EXPECTED_CENTRAL_COMPAT_GLOBALS = {
    "Copy",
    "Guard",
    "SegView",
    "escHtml",
}

#: 아직 자기 파일에서 자기 전역을 만드는 legacy IIFE 생산자 23개.
EXPECTED_LEGACY_GLOBALS = {
    "AppCloseGuard",
    "Bridge",
    "DataPicker",
    "DataZone",
    "EditorEntry",
    "EditorScreen",
    "GroupList",
    "Intent",
    "JobScreen",
    "LibraryScreen",
    "Modal",
    "Nav",
    "PathTrack",
    "Personalization",
    "Popover",
    "Preserve",
    "Relink",
    "SheetPicker",
    "SurfaceSheet",
    "Theme",
    "UndoToast",
    "WorkbenchScreen",
    "__push",
}

#: 런타임 전역 표면 전체 — N-04는 생산 **자리**만 옮기고 수량은 27 그대로다.
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


def test_converted_leaves_are_esm_and_own_no_globals() -> None:
    """N-04 잎 넷은 IIFE도 전역 생산자도 아니고 자기 named export 하나만 낸다.

    M1의 "25 IIFE 전수"를 이 후계가 잇는다. 여기서 수량만 세면 잎이 export를 내면서
    ``window.SegView`` 도 같이 남기는 이중 유지가 통과한다 — 그래서 파일별로 IIFE 0,
    ``window``/``globalThis`` 접촉 0, 정확한 export 이름을 함께 단언한다.
    """
    expected_exports = {
        "copy.js": "Copy",
        "esc.js": "escHtml",
        "guard.js": "Guard",
        "segview.js": "SegView",
    }
    assert set(expected_exports) == set(LEAF_ESM_FILES)

    for name in LEAF_ESM_FILES:
        path = SOURCE_JS_DIR / name
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\(function \(\) \{", source), (
            f"{name} 이 아직 IIFE 로 감싸져 있습니다 — N-04 는 true ESM 입니다."
        )
        assert "window." not in source and "globalThis" not in source, (
            f"{name} 이 전역을 직접 읽거나 씁니다 — 잎 모듈은 window 를 모릅니다."
        )
        exported = set(
            re.findall(
                r"(?m)^export\s+(?:const|let|var|function|class)\s+"
                r"([A-Za-z_$][A-Za-z0-9_$]*)",
                source,
            )
        )
        assert exported == {expected_exports[name]}, (
            f"{name} 의 공개 표면이 {sorted(exported)} 입니다 — "
            f"{expected_exports[name]} 하나여야 합니다."
        )
        assert "export default" not in source, f"{name} 이 default export 를 냅니다."


def test_segview_imports_the_escaper_instead_of_reading_a_global() -> None:
    """SegView→esc 는 이제 그래프에 적힌 단방향 간선이다(로드 순서 암묵 계약의 후계)."""
    source = (SOURCE_JS_DIR / "segview.js").read_text(encoding="utf-8")

    assert re.search(
        r'(?m)^import\s+\{\s*escHtml\s*\}\s+from\s+"\./esc\.js";', source
    ), "segview.js 가 escHtml 을 ESM import 하지 않습니다."


def test_temporary_leaf_aliases_have_exactly_one_central_producer() -> None:
    """네 별칭은 중앙 compat 한 파일에서만 만들어진다(D-05 단일 생산자).

    파일마다 되살리면 소비자는 그대로 동작하므로 **동작 테스트로는 안 보인다**. 생산 자리를
    세는 이 게이트만 그 회귀를 잡는다.
    """
    compat_source = SOURCE_COMPAT.read_text(encoding="utf-8")
    producers = re.findall(
        r"(?m)^\s*window\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=", compat_source
    )

    assert SOURCE_COMPAT.name == COMPAT_MODULE
    assert sorted(producers) == sorted(EXPECTED_CENTRAL_COMPAT_GLOBALS)
    assert len(producers) == len(set(producers)) == 4
    for name in LEAF_ESM_FILES:
        assert f'from "../js/{name}"' in compat_source, (
            f"compat 이 {name} 을 import 하지 않습니다 — 별칭이 export 와 어긋납니다."
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
        "잎 전역 별칭이 중앙 compat 밖에서 다시 만들어집니다: " + ", ".join(sorted(elsewhere))
    )


def test_remaining_legacy_iifes_and_total_global_surface_are_unchanged() -> None:
    """남은 IIFE 21개는 그대로 IIFE 이고, 제품 전역 표면 전체는 여전히 27개다."""
    legacy_scripts = tuple(sorted(SOURCE_JS_DIR.rglob("*.js")))
    legacy_only = tuple(
        path
        for path in legacy_scripts
        if path.relative_to(SOURCE_JS_DIR).as_posix() not in LEAF_ESM_FILES
    )

    assert len(legacy_scripts) == 25
    assert len(legacy_only) == 21
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
    assert len(legacy_globals) == 23
    assert legacy_globals.isdisjoint(EXPECTED_CENTRAL_COMPAT_GLOBALS)
    assert len(EXPECTED_RUNTIME_GLOBALS) == 27


def test_compat_is_evaluated_before_every_legacy_consumer() -> None:
    """compat 은 소비 IIFE 보다 먼저 평가되고, 나머지 21개의 상대 순서는 보존된다.

    static import 는 entry 본문보다 먼저 평가되므로 compat 이 앞자리에 있는 한 별칭이 서기
    전에 읽히는 창은 없다. 잎이 직접 import 되지 않는지도 같이 본다 — 남아 있으면 모듈이
    두 경로로 그래프에 들어와 평가 순서 추론이 무의미해진다.
    """
    modules = evaluated_modules(SOURCE_ENTRY.read_text(encoding="utf-8"))

    assert COMPAT_MODULE in modules
    compat_index = modules.index(COMPAT_MODULE)
    assert modules.count(COMPAT_MODULE) == 1
    assert compat_index < min(
        modules.index(name)
        for name in LEGACY_JS_FILES[COMPAT_ENTRY_POSITION:]
    )
    assert set(modules) - {COMPAT_MODULE} == set(LEGACY_JS_FILES)
    assert tuple(name for name in modules if name != COMPAT_MODULE) == LEGACY_JS_FILES
    assert not set(modules) & set(LEAF_ESM_FILES)
