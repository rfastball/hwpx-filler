"""N-03 M1의 제품 entry, visible DOM, legacy runtime fallback 정적 계약."""

from __future__ import annotations

import ast
import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

from _web_source import (
    ALL_CSS_FILES,
    BOOTSTRAP_EXPORT,
    BOOTSTRAP_MODULE,
    LEAF_ESM_FILES,
    REPO_ROOT,
    SOURCE_INDEX,
    SOURCE_ROOT,
    entry_js_manifest,
    module_imports,
)

PRODUCT_ENTRY = SOURCE_ROOT / "src" / "main.js"
VISIBLE_DOM_SHA256 = "e037e81337ea8258de2a48438cdb6a7bab42bea838d661ab9c42498fe793b34c"

# M1이 25개 IIFE를 기존 실행 순서대로 import했고, N-04~N-07이 잎·서비스·화면·브리지를
# 차례로 ESM으로 빼내 합성 루트 뒤로 옮겼다. 남은 JS는 합성 루트 하나이고, N-10에서 그것을
# 싣는 형태가 부작용 import에서 **named import + 호출**로 바뀌었다.
LEGACY_IIFE_ORDER = entry_js_manifest()

# test_web_source_role의 source-root gate를 우회하지 않도록 물리 이름을 경로식으로
# 재조립하지 않는다. 이 집합은 product/runtime AST의 direct fallback만 분류한다.
_LEGACY_SOURCE_NAME = "w" + "eb"
_CANONICAL_SOURCE_NAME = "front" + "end"
_ENV_OVERRIDE = "HWPXFILLER_" + "WEB_DIR"
_REPO_ROOT_NAMES = {"ROOT", "REPO", "REPO_ROOT", "repo", "repo_root", "root"}


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "script":
            self.scripts.append(dict(attrs))


def _side_effect_imports(source: str) -> tuple[str, ...]:
    return tuple(
        re.findall(
            r"""^\s*import\s+["']([^"']+)["'];\s*$""",
            source,
            flags=re.M,
        )
    )


def _normalized_visible_dom(source: str) -> str:
    """Asset graph와 설명 주석만 버리고 사용자가 보는 정적 DOM을 정규화한다."""
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    source = re.sub(
        r"""<link\b[^>]*rel=["']stylesheet["'][^>]*>""",
        "",
        source,
        flags=re.I,
    )
    source = re.sub(
        r"<script\b[^>]*>.*?</script>",
        "",
        source,
        flags=re.I | re.S,
    )
    return re.sub(r"\s+", " ", source).strip()


def _is_repo_root_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _REPO_ROOT_NAMES
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_repo_root"
    )


def _direct_source_fallbacks(
    tree: ast.AST,
    *,
    forbidden_names: set[str],
) -> list[int]:
    """``REPO / source`` 형태만 찾는다; ``REPO / build / web``은 산출물이라 허용한다."""
    offenders: list[int] = []
    for node in ast.walk(tree):
        direct_division = (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and _is_repo_root_expression(node.left)
            and isinstance(node.right, ast.Constant)
            and node.right.value in forbidden_names
        )
        direct_join = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "joinpath"
            and _is_repo_root_expression(node.func.value)
            and any(
                isinstance(argument, ast.Constant)
                and argument.value in forbidden_names
                for argument in node.args
            )
        )
        if direct_division or direct_join:
            offenders.append(node.lineno)
    return offenders


def _python_runtime_sources() -> tuple[Path, ...]:
    paths = [
        *sorted((REPO_ROOT / "src" / "hwpxfiller" / "webapp").rglob("*.py")),
        *sorted((REPO_ROOT / "packaging").glob("*.py")),
        *sorted((REPO_ROOT / "packaging").glob("*.spec")),
    ]
    return tuple(paths)


def _python_source_tools() -> tuple[Path, ...]:
    return tuple(sorted((REPO_ROOT / "scripts").glob("*.py")))


def test_product_index_has_one_module_entry_and_no_classic_scripts() -> None:
    parser = _ScriptCollector()
    parser.feed(SOURCE_INDEX.read_text(encoding="utf-8"))

    assert parser.scripts == [{"type": "module", "src": "./src/main.js"}]
    assert PRODUCT_ENTRY.is_file()


def test_product_entry_preserves_exact_css_and_legacy_iife_order() -> None:
    """CSS 캐스케이드 순서는 부작용 import가, JS 도달은 형태 불가지 눈이 진다.

    N-10 전에는 둘을 한 목록으로 볼 수 있었다(합성 루트도 부작용 import였다). 이제
    ``import {bootProduct} from "./bootstrap.js";``라 부작용 목록에 없다 — 한 눈으로만
    보면 "JS가 아예 없다"와 "형태가 바뀌었다"가 구별되지 않으므로 두 눈으로 나눠 묻는다.
    """
    source = PRODUCT_ENTRY.read_text(encoding="utf-8")
    css_imports = _side_effect_imports(source)
    js_imports = tuple(
        path for path in module_imports(source) if not path.startswith("../css/")
    )

    assert css_imports == tuple(f"../css/{name}" for name in ALL_CSS_FILES)
    assert js_imports == LEGACY_IIFE_ORDER


def test_converted_leaves_left_the_entry_only_through_the_composition_root() -> None:
    """잎 넷은 entry에서 사라지고 그 자리를 합성 루트 한 줄이 정확히 메운다.

    "직접 import를 지웠다"만 보면 합성 루트를 잊은 채로도 초록이고, 그때 제품은 부팅
    자체를 하지 못한다 — 두 방향을 같이 단언한다.
    """
    source = PRODUCT_ENTRY.read_text(encoding="utf-8")
    imports = module_imports(source)

    assert imports.count(f"./{BOOTSTRAP_MODULE}") == 1
    for name in LEAF_ESM_FILES:
        assert f"../js/{name}" not in imports, (
            f"{name} 이 아직 제품 entry에 직접 import돼 있습니다 — 잎은 합성 루트만 거칩니다."
        )
    assert (SOURCE_ROOT / "src" / BOOTSTRAP_MODULE).is_file()
    #: 은퇴한 compat 계층이 파일로 되살아나지 않았다.
    assert not (SOURCE_ROOT / "src" / "compat.js").exists()
    #: 싣기만 하고 부르지 않으면 아무 일도 일어나지 않는다 — 부작용 import 시절엔 없던 축.
    assert f"{BOOTSTRAP_EXPORT}();" in source


def test_product_cutover_preserves_normalized_visible_dom() -> None:
    normalized = _normalized_visible_dom(SOURCE_INDEX.read_text(encoding="utf-8"))

    assert hashlib.sha256(normalized.encode("utf-8")).hexdigest() == (
        VISIBLE_DOM_SHA256
    )


def test_product_runtime_has_no_source_or_environment_fallback() -> None:
    """제품·패키지 Python은 sealed artifact만 소비하고 source escape hatch를 갖지 않는다."""
    offenders: list[str] = []
    forbidden = {_LEGACY_SOURCE_NAME, _CANONICAL_SOURCE_NAME}
    for path in _python_runtime_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == _ENV_OVERRIDE:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}:env")
        offenders.extend(
            f"{path.relative_to(REPO_ROOT)}:{line}:source-fallback"
            for line in _direct_source_fallbacks(tree, forbidden_names=forbidden)
        )

    assert not offenders, (
        "제품 runtime에 source/env fallback이 재유입됐습니다:\n"
        + "\n".join(offenders)
    )


def test_executable_source_tools_do_not_read_retired_web_tree() -> None:
    """generator/seal 등 source 도구는 frontend를 읽을 수 있지만 폐기된 source는 못 읽는다."""
    offenders: list[str] = []
    for path in _python_source_tools():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders.extend(
            f"{path.relative_to(REPO_ROOT)}:{line}"
            for line in _direct_source_fallbacks(
                tree,
                forbidden_names={_LEGACY_SOURCE_NAME},
            )
        )

    assert not offenders, (
        "실행 가능한 source 도구가 폐기된 source tree를 직접 읽습니다:\n"
        + "\n".join(offenders)
    )


def test_screenshot_capture_builds_before_replacing_outputs() -> None:
    source = (REPO_ROOT / "scripts" / "capture_101_screenshots.py").read_text(
        encoding="utf-8"
    )
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    build_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "run"
        and "build-web.ps1" in (ast.get_source_segment(source, node) or "")
    ]
    destructive_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "shutil"
        and node.func.attr == "rmtree"
    ]

    assert len(build_calls) == 1
    assert destructive_calls
    assert build_calls[0].lineno < min(node.lineno for node in destructive_calls)
