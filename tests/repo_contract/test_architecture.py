"""제품 계층의 의존 방향과 우회 불가 공개 경계만 검증한다."""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

from _web_source import REPO_ROOT, SOURCE_JS_DIR

ROOT = REPO_ROOT


def _imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append((node.module, node.lineno))
    return result


def test_python_package_dependencies_point_inward() -> None:
    """src 전체는 Qt-free이고 core/data는 제품 상위 계층으로 역의존하지 않는다."""
    failures: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for module, lineno in _imports(path):
            root = module.split(".", 1)[0]
            if root in {"PySide6", "shiboken6"}:
                failures.append(f"{relative}:{lineno}: {module}")
            if "src/hwpxcore/" in f"{relative}/" and root in {"hwpxfiller", "hwpxdiff"}:
                failures.append(f"{relative}:{lineno}: core 역의존 {module}")
            if relative.startswith("src/hwpxfiller/data/") and module.startswith(
                "hwpxfiller.core"
            ):
                failures.append(f"{relative}:{lineno}: data→core 역의존 {module}")

        if relative.startswith("src/hwpxfiller/data/"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.level >= 2
                    and node.module
                    and node.module.split(".", 1)[0] == "core"
                ):
                    failures.append(f"{relative}:{node.lineno}: data→core 상대 역의존")
    assert not failures, "\n".join(failures)


def test_web_controllers_use_ring1_public_seams() -> None:
    library = ROOT / "src" / "hwpxfiller" / "webapp" / "screen_library.py"
    library_tree = ast.parse(library.read_text(encoding="utf-8"), filename=str(library))
    bypasses = [
        node.lineno
        for node in ast.walk(library_tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "registry"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "vm"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "self"
    ]

    job = ROOT / "src" / "hwpxfiller" / "webapp" / "screen_job.py"
    job_tree = ast.parse(job.read_text(encoding="utf-8"), filename=str(job))
    imported = {
        alias.name
        for node in ast.walk(job_tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    forbidden = {
        "refresh",
        "gate_state",
        "validate_generate",
        "build_generation_plan",
        "unmet_blanks",
        "output_conflicts",
        "structure_drift",
        "mapped_records",
        "_compose_gate",
        "_compose_field_states",
        "_compose_preflight",
    }
    defined = {
        item.name
        for node in ast.walk(job_tree)
        if isinstance(node, ast.ClassDef)
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not bypasses, f"screen_library.py가 vm.registry를 직접 사용한다: {bypasses}"
    assert {"RunViewModel", "SelectionModel"} <= imported
    assert not (forbidden & defined), (
        f"screen_job.py가 링1 판정을 재구현한다: {sorted(forbidden & defined)}"
    )


def test_screen_controllers_stay_transport_thin() -> None:
    """P2-24 음성 게이트 — 화면 컨트롤러는 transport/presentation 층에 머문다.

    ① ``webapp/screen_*.py`` 상호 직접 import 0 — 화면 간 위임은 조립부(``webapp.app``)가
       결선하는 callable 하나뿐이다(controller-to-controller 결합 재유입 금지).
    ② ``screen_job.py`` 는 concrete 저장·배치 모듈(``hwpxfiller.batch``·
       ``external.job_store``·``external.dataset_store``)을 import 하지 않는다 —
       Presentation 은 Application(use case·port)을 경유한다.
    ③ generation run 자물쇠·취소 Event 를 화면이 자체 생성하지 않는다 — 정본은
       ``webapp.app`` 의 앱 전역 Lock 하나와 ``application.generation.GenerationRun`` 의
       Event 다. 판정은 파일명 allowlist 가 아니라 AST 의미다: ``threading.Event`` 생성은
       전 화면 금지, ``threading.Lock`` 생성은 ``generation_lock`` 을 아는(주입받는) 화면
       금지(화면-국소 직렬화 자물쇠는 그 심볼을 모른다).
    """
    webapp = ROOT / "src" / "hwpxfiller" / "webapp"
    forbidden_for_job = (
        "hwpxfiller.batch",
        "hwpxfiller.external.job_store",
        "hwpxfiller.external.dataset_store",
    )
    failures: list[str] = []
    for path in sorted(webapp.glob("screen_*.py")):
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        refs_generation_lock = any(
            (isinstance(n, ast.arg) and n.arg == "generation_lock")
            or (isinstance(n, ast.Name) and n.id == "generation_lock")
            for n in ast.walk(tree)
        )
        for node in ast.walk(tree):
            modules: list[tuple[str, int]] = []
            if isinstance(node, ast.Import):
                modules = [(alias.name, node.lineno) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = "hwpxfiller.webapp" if node.level == 1 else (
                    "hwpxfiller" if node.level == 2 else (node.module or "")
                )
                full = (
                    f"{base}.{node.module}" if node.level and node.module
                    else (base if node.level else (node.module or ""))
                )
                modules = [(full, node.lineno)]
            for module, lineno in modules:
                if module.rsplit(".", 1)[-1].startswith("screen_"):
                    failures.append(f"{rel}:{lineno}: 화면 간 직접 import {module}")
                if path.name == "screen_job.py" and any(
                    module == f or module.startswith(f + ".") for f in forbidden_for_job
                ):
                    failures.append(f"{rel}:{lineno}: concrete 모듈 import {module}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "threading"
                and (
                    node.func.attr == "Event"
                    or (node.func.attr == "Lock" and refs_generation_lock)
                )
            ):
                failures.append(
                    f"{rel}:{node.lineno}: run transaction 프리미티브 자체 생성 "
                    f"threading.{node.func.attr}()"
                )
    assert not failures, "\n".join(failures)


def test_native_file_dialogs_have_one_app_entry() -> None:
    path = ROOT / "src" / "hwpxfiller" / "webapp" / "app.py"
    pattern = re.compile(r"^\s*(?:.*[=(\s])?(open_file_dialog|open_folder_dialog)\(")
    allowed = {"    return open_file_dialog(", "    return open_folder_dialog("}
    offenders = [
        f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line) and not any(line.startswith(prefix) for prefix in allowed)
    ]
    assert not offenders, "\n".join(offenders)


def test_job_registry_writes_go_through_locked_boundaries() -> None:
    """통째 저장이 필요한 두 표면 외에는 잠금 소유 API를 우회할 수 없다."""
    allowed = {
        "webapp/screen_editor.py",
        "webapp/screen_workbench.py",
    }
    other_registries = ("pool", "dataset", "pipeline", "template")
    pattern = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)\.save\(")
    base = ROOT / "src" / "hwpxfiller"
    offenders: list[str] = []
    for subdir in ("webapp", "gui", "cli"):
        for path in sorted((base / subdir).rglob("*.py")):
            if any(word in path.name for word in other_registries):
                continue
            relative = path.relative_to(base).as_posix()
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for receiver in pattern.findall(line):
                    if (
                        receiver.endswith("registry")
                        and "pool" not in receiver.lower()
                        and relative not in allowed
                    ):
                        offenders.append(f"{relative}:{lineno}: {line.strip()}")
    assert not offenders, (
        "잠금 밖 Job 저장 재유입; JobRegistry.mutate/stamp_last_run을 사용하세요:\n"
        + "\n".join(offenders)
    )


def test_home_directory_resolution_has_one_source() -> None:
    pattern = re.compile(r"""environ(?:\.get)?[\[(]\s*["']HWPXFILLER_HOME["']""")
    owner = ROOT / "src" / "hwpxfiller" / "core" / "paths.py"
    offenders: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path == owner:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}")
    assert not offenders, "home_dir() 우회:\n" + "\n".join(offenders)


def test_ui_contract_documents_every_direct_bridge_method() -> None:
    bridge = (SOURCE_JS_DIR / "bridge.js").read_text(encoding="utf-8")
    contract = (ROOT / "docs" / "UI_CONTRACT.md").read_text(encoding="utf-8")
    methods = set(re.findall(r"\bapi\.(\w+)", bridge)) - {"initial", "dispatch"}
    undocumented = sorted(method for method in methods if f"`{method}`" not in contract)
    assert methods and not undocumented, f"문서화되지 않은 직접 브리지: {undocumented}"


def test_packaging_entry_imports_resolve() -> None:
    pattern = re.compile(r"^\s*from\s+(hwpxfiller[\w.]*)\s+import\s+(.+)$")
    failures: list[str] = []
    for path in sorted((ROOT / "packaging").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not (match := pattern.match(line)):
                continue
            module, names = match.groups()
            try:
                imported = importlib.import_module(module)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{path.name}:{lineno}: {module}: {exc}")
                continue
            for raw in names.split(","):
                symbol = raw.strip().split(" as ")[0].strip().strip("()")
                if symbol and not hasattr(imported, symbol):
                    failures.append(f"{path.name}:{lineno}: {module}.{symbol}")
    assert not failures, "\n".join(failures)
