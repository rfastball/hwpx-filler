"""프런트 빌드의 잠긴 도구·단일 Vite entry·모듈 의존 폐포를 검증한다."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from _web_source import (
    SOURCE_ENTRY,
    SOURCE_INDEX,
    SOURCE_ROOT,
    module_imports,
    strip_comments,
)

ROOT = Path(__file__).resolve().parents[2]
NODE_VERSION = "24.18.1"
NPM_VERSION = "11.16.0"
DEPENDENCIES = {
    "@codemirror/state": "6.7.1",
    "@codemirror/view": "6.43.9",
    "react": "19.2.8",
    "react-dom": "19.2.8",
}
DEV_DEPENDENCIES = {
    "@types/react": "19.2.18",
    "@types/react-dom": "19.2.4",
    "typescript": "7.0.2",
    "vite": "8.1.5",
}


def _run(*command: str) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"{' '.join(command)} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    return completed.stdout.strip()


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
  build: {
    outDir: relative(config.build.outDir),
    emptyOutDir: config.build.emptyOutDir,
    manifest: config.build.manifest,
    cssCodeSplit: config.build.cssCodeSplit,
    assetsInlineLimit: config.build.assetsInlineLimit,
    modulePreload: config.build.modulePreload,
    minify: config.build.minify,
    sourcemap: config.build.sourcemap ?? false,
    treeshake: config.build.rolldownOptions?.treeshake,
  },
}));
"""
    return json.loads(_run(node, "--input-type=module", "--eval", script))


def test_node_npm_and_package_dependencies_are_exactly_locked() -> None:
    node = shutil.which("node")
    npm = shutil.which("npm.cmd")
    assert node is not None, f"Node {NODE_VERSION}이 PATH에 없습니다"
    assert npm is not None, f"npm {NPM_VERSION}이 PATH에 없습니다"
    assert _run(node, "--version") == f"v{NODE_VERSION}"
    assert _run(npm, "--version") == NPM_VERSION

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == NODE_VERSION
    assert package["packageManager"] == f"npm@{NPM_VERSION}"
    assert package["engines"] == {"node": NODE_VERSION, "npm": NPM_VERSION}
    assert package["dependencies"] == DEPENDENCIES
    assert package["devDependencies"] == DEV_DEPENDENCIES
    assert lock["lockfileVersion"] == 3
    assert lock["packages"][""]["dependencies"] == DEPENDENCIES
    assert lock["packages"][""]["devDependencies"] == DEV_DEPENDENCIES
    for name, version in (*DEPENDENCIES.items(), *DEV_DEPENDENCIES.items()):
        assert lock["packages"][f"node_modules/{name}"]["version"] == version
    assert (ROOT / ".npmrc").read_text(encoding="utf-8").splitlines() == [
        "engine-strict=true",
        "save-exact=true",
    ]


def test_package_scripts_vite_config_and_html_have_one_production_entry() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["private"] is True
    assert package["type"] == "module"
    assert package["scripts"] == {
        "build": "vite build && uv run python scripts/seal_web_artifact.py",
        "test": 'node --test --test-concurrency=4 --test-reporter=tap "tests/js/*.test.js"',
        "verify:web": "uv run python scripts/seal_web_artifact.py --verify",
    }
    assert _vite_config() == {
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
            "sourcemap": False,
            "treeshake": False,
        },
    }

    scripts = re.findall(
        r'<script\b[^>]*\bsrc="[^"]+"[^>]*></script>',
        SOURCE_INDEX.read_text(encoding="utf-8"),
    )
    assert scripts == ['<script type="module" src="./src/main.js"></script>']
    vite_source = (ROOT / "vite.config.mjs").read_text(encoding="utf-8")
    assert not any(
        forbidden in vite_source
        for forbidden in ("input:", "rollupOptions", "build.lib", "lib:")
    )


def test_typescript_boundary_is_erasable_strict_and_typechecks() -> None:
    config = json.loads((ROOT / "tsconfig.json").read_text(encoding="utf-8"))
    options = config["compilerOptions"]
    assert config["include"] == ["frontend/src/**/*"]
    assert {
        "strict": options["strict"],
        "noEmit": options["noEmit"],
        "erasableSyntaxOnly": options["erasableSyntaxOnly"],
        "verbatimModuleSyntax": options["verbatimModuleSyntax"],
        "allowImportingTsExtensions": options["allowImportingTsExtensions"],
        "skipLibCheck": options["skipLibCheck"],
    } == {
        "strict": True,
        "noEmit": True,
        "erasableSyntaxOnly": True,
        "verbatimModuleSyntax": True,
        "allowImportingTsExtensions": True,
        "skipLibCheck": False,
    }

    node = shutil.which("node")
    tsc = ROOT / "node_modules" / "typescript" / "bin" / "tsc"
    assert node is not None and tsc.is_file(), "npm ci가 이 계약의 전제입니다"
    _run(node, str(tsc), "-p", str(ROOT / "tsconfig.json"))


def _resolve_relative(owner: str, specifier: str) -> str:
    candidate = PurePosixPath(owner).parent / specifier
    parts: list[str] = []
    for part in candidate.parts:
        if part == "..":
            parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    return PurePosixPath(*parts).as_posix()


def test_entry_module_dependency_graph_is_closed_acyclic_and_pinned() -> None:
    entry = SOURCE_ENTRY.relative_to(SOURCE_ROOT).as_posix()
    state: dict[str, int] = {}
    missing: list[str] = []
    unpinned: list[str] = []
    build_branches: list[str] = []

    def visit(module: str, trail: tuple[str, ...]) -> None:
        if state.get(module) == 1:
            raise AssertionError(f"import cycle: {' -> '.join((*trail, module))}")
        if state.get(module) == 2:
            return
        state[module] = 1
        path = SOURCE_ROOT / module
        if not path.is_file():
            missing.append(module)
            state[module] = 2
            return

        source = path.read_text(encoding="utf-8")
        code = strip_comments(source)
        if "import.meta.env" in code or "process.env.NODE_ENV" in code:
            build_branches.append(module)
        for specifier in module_imports(source):
            if specifier.endswith(".css"):
                css = _resolve_relative(module, specifier)
                if not (SOURCE_ROOT / css).is_file():
                    missing.append(css)
            elif specifier.startswith("."):
                visit(_resolve_relative(module, specifier), (*trail, module))
            else:
                package = specifier.split("/", 1)[0]
                if specifier.startswith("@"):
                    package = "/".join(specifier.split("/", 2)[:2])
                if path.suffix == ".js" or package not in DEPENDENCIES:
                    unpinned.append(f"{module} -> {specifier}")
        state[module] = 2

    visit(entry, ())
    assert not missing, f"missing imports: {sorted(set(missing))}"
    assert not unpinned, f"unapproved bare imports: {unpinned}"
    assert not build_branches, f"build-time branches: {build_branches}"
