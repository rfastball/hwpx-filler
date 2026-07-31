"""N-03 M1의 exact Vite build graph와 물리 source transition 계약."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from _web_source import (
    ALL_CSS_FILES,
    LEGACY_JS_FILES,
    SOURCE_ENTRY,
    SOURCE_INDEX,
    SOURCE_ROOT,
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
EXPECTED_COMPAT_GLOBALS = {
    "AppCloseGuard",
    "Bridge",
    "Copy",
    "DataPicker",
    "DataZone",
    "EditorEntry",
    "EditorScreen",
    "GroupList",
    "Guard",
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
    "SegView",
    "SheetPicker",
    "SurfaceSheet",
    "Theme",
    "UndoToast",
    "WorkbenchScreen",
    "__push",
    "escHtml",
}


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
        *(f"../js/{name}" for name in LEGACY_JS_FILES),
    )
    assert side_effect_imports(SOURCE_ENTRY.read_text(encoding="utf-8")) == (
        expected_imports
    )


def test_m1_preserves_legacy_iifes_and_compat_globals() -> None:
    legacy_scripts = tuple(sorted((SOURCE_ROOT / "js").rglob("*.js")))

    assert len(legacy_scripts) == 25
    assert {
        path.relative_to(SOURCE_ROOT / "js").as_posix()
        for path in legacy_scripts
    } == set(LEGACY_JS_FILES)
    sources = {
        path.relative_to(SOURCE_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in legacy_scripts
    }
    assert all(
        len(re.findall(r"(?m)^\(function \(\) \{", source)) == 1
        for source in sources.values()
    )
    compat_globals = {
        match
        for source in sources.values()
        for match in re.findall(
            r"(?m)^\s*window\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=",
            source,
        )
    }
    assert compat_globals == EXPECTED_COMPAT_GLOBALS
