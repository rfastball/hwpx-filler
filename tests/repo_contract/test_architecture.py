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
    """src 전체는 Qt-free이고 hwpxcore는 hwpxdiff로 역의존하지 않는다."""
    failures: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for module, lineno in _imports(path):
            root = module.split(".", 1)[0]
            if root in {"PySide6", "shiboken6"}:
                failures.append(f"{relative}:{lineno}: {module}")
            if "src/hwpxcore/" in f"{relative}/" and root == "hwpxdiff":
                failures.append(f"{relative}:{lineno}: core 역의존 {module}")
    assert not failures, "\n".join(failures)


#: 「비워 둠」 표시형 퇴역(U6 §2.10)이 남긴 **소비자 0** 심볼 — 되살아나면 같은 상태를 두
#: 이름이 판정한다(빈 고정값과 별도 유형). 산출물 소스 전역에서 0 이어야 한다.
RETIRED_BLANK_SYMBOLS = ("set_blank", "sp:blank", "is_blank", "declared_blank_fields")


def test_retired_blank_type_symbols_have_zero_producers_and_consumers() -> None:
    """`blank` 유형의 심볼이 src·frontend 어디에도 남지 않는다(U6 §2.10).

    문서는 대상이 아니다 — 퇴역 판정을 설명하려면 그 이름을 불러야 한다.
    """
    failures: list[str] = []
    for root in (ROOT / "src", ROOT / "frontend"):
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".py", ".ts", ".tsx", ".js", ".css", ".html"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for symbol in RETIRED_BLANK_SYMBOLS:
                    if symbol in line:
                        rel = path.relative_to(ROOT).as_posix()
                        failures.append(f"{rel}:{lineno}: {symbol}")
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
    """P2-24/P2-25 음성 게이트 — 화면 컨트롤러는 transport/presentation 층에 머문다.

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
    ④ concrete HWPX engine 조립은 ``webapp.app`` 만 소유하고 화면은 주입분을
       관통한다(``external.hwpx_engine`` 재유입 금지).
    """
    webapp = ROOT / "src" / "hwpxfiller" / "webapp"
    forbidden_for_job = (
        "hwpxfiller.batch",
        "hwpxfiller.external.job_store",
        "hwpxfiller.external.dataset_store",
    )
    forbidden_engine = "hwpxfiller.external.hwpx_engine"
    failures: list[str] = []
    for path in sorted(webapp.glob("screen*.py")):
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
                # alias 도 정규화한다(코덱스 #581 P2) — `from . import screen_workbench`·
                # `from ..external import job_store` 같은 패키지+멤버 형이 base 로만
                # 접혀 두 금지선을 모두 통과하는 사각을 막는다(기존 boundary 게이트 관용구).
                modules = [(full, node.lineno)] + [
                    (f"{full}.{alias.name}" if full else alias.name, node.lineno)
                    for alias in node.names
                    if alias.name != "*"
                ]
            for module, lineno in modules:
                if module.rsplit(".", 1)[-1].startswith("screen_"):
                    failures.append(f"{rel}:{lineno}: 화면 간 직접 import {module}")
                if module == forbidden_engine or module.startswith(forbidden_engine + "."):
                    failures.append(f"{rel}:{lineno}: concrete engine 조립 import {module}")
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
    pattern = re.compile(
        r"^\s*(?:.*[=(\s])?(open_file_dialog|open_folder_dialog|save_file_dialog)\("
    )
    # 세 native 대화상자 각각의 **단일 진입 한 줄**. 저장은 S7-03(#825)이 「다른 이름으로
    # 저장」을 열며 합류했다 — 입구가 하나여야 라이브 실행의 대체가 그 자리를 비껴가지 않는다.
    allowed = {
        "    return open_file_dialog(",
        "    return open_folder_dialog(",
        "    return save_file_dialog(",
    }
    offenders = [
        f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line) and not any(line.startswith(prefix) for prefix in allowed)
    ]
    assert not offenders, "\n".join(offenders)


def test_job_registry_writes_go_through_locked_boundaries() -> None:
    """통째 저장이 필요한 두 표면 외에는 잠금 소유 API를 우회할 수 없다.

    ``mutate`` 도 같은 선으로 본다(P2-99 #542 F-1): 통째 저장만 막고 잠긴
    읽기-수정-쓰기를 열어 두면, 링2 가 콜백 안에서 업무 규칙을 **재판정**하며 durable
    트랜잭션을 소유하는 경로가 그대로 남는다(``webapp/screens.py`` 의 재연결 커밋이 그
    모양이었고 이 게이트는 ``.save(`` 만 봐서 초록이었다). 링2 는 Application use case
    (:mod:`hwpxfiller.application.jobs`)를 지난다.
    """
    allowed = {
        "webapp/screen_editor.py",
        "webapp/screen_workbench.py",
    }
    other_registries = ("pool", "dataset", "pipeline", "template")
    pattern = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)\.(?:save|mutate)\(")
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
        "잠금 밖·잠금 안 Job durable 변이 재유입; application.jobs use case를 지나세요:\n"
        + "\n".join(offenders)
    )


#: TXT 템플릿 durable 쓰기의 단일 소유자(S10G-00 #857) — 잠금·경로 검증·원자 쓰기·드리프트
#: 판정이 전부 여기 산다.
_TEXT_STORE = "external/template_files.py"


def _terminal_name(node: ast.expr) -> str:
    """속성 체인의 말단 이름 — ``self.text_registry`` / ``store.text_registry`` 둘 다 잡는다."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def test_txt_template_write_lock_has_one_owner() -> None:
    """TXT 쓰기 잠금은 :mod:`~hwpxfiller.external.template_files` 밖에서 잡히지 않는다.

    #176 RC-A 가 기록한 결함류다: 잠금·경로 검증·원자 쓰기를 링2 가 **각자** 조립하면
    한 자리가 빠져도 조용히 지나간다(무락 check/write 교차, 라이브 목록 밖 경로 변이).
    소유자를 하나로 못박아야 새 TXT 쓰기 경로가 그 규율을 우회한 채 생길 수 없다.

    줄 grep 이 아니라 AST 로 본다 — ``screen_template.py`` 의 도크스트링이 이 잠금을
    **설명**하므로 문자열까지 세면 규칙이 제 문서에 걸려 영영 빨강이다(#216 회귀 금지).
    """
    base = ROOT / "src" / "hwpxfiller"
    offenders: list[str] = []
    for path in sorted(base.rglob("*.py")):
        relative = path.relative_to(base).as_posix()
        if relative == _TEXT_STORE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(
            f"{relative}:{node.lineno}: text_registry.write_lock 직접 획득"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == "write_lock"
            and _terminal_name(node.value) == "text_registry"
        )
    assert not offenders, (
        f"TXT 쓰기 잠금 우회; {_TEXT_STORE} 의 TemplateFileStore 를 지나세요:\n"
        + "\n".join(offenders)
    )


def test_template_channel_delegates_every_durable_write() -> None:
    """``screen_template.py`` 는 파일 I/O 프리미티브를 직접 부르지 않는다(#857 종료 조건).

    tpl 채널은 TXT·HWPX 템플릿을 durable 로 바꾸는 유일한 웹 표면이라, 여기서 프리미티브를
    한 번 직접 부르는 순간 그 경로만 잠금·경로 검증·드리프트 판정 밖에 선다(#176 RC-A).
    허용되는 유일한 수신자는 주입된 :class:`TemplateFileStore`(``self._files``) 다 —
    같은 이름의 위임 메서드(``_files.read_text``)는 프리미티브가 아니라 그 관문이다.
    """
    primitives = frozenset({"open", "write_text_atomic", "write_bytes_atomic"})
    methods = frozenset(
        {"write_text", "write_bytes", "read_text", "read_bytes", "replace", "unlink", "copy2"}
    )
    path = ROOT / "src" / "hwpxfiller" / "webapp" / "screen_template.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in primitives:
            offenders.append(f"{node.lineno}: {node.func.id}() 직접 호출")
        elif isinstance(node.func, ast.Attribute) and node.func.attr in methods:
            if _terminal_name(node.func.value) != "_files":
                offenders.append(f"{node.lineno}: .{node.func.attr}() 직접 호출")
    assert not offenders, (
        "screen_template 이 파일 I/O 를 직접 함; TemplateFileStore 에 위임하세요:\n"
        + "\n".join(offenders)
    )


def test_home_directory_resolution_has_one_source() -> None:
    pattern = re.compile(r"""environ(?:\.get)?[\[(]\s*["']HWPXFILLER_HOME["']""")
    owner = ROOT / "src" / "hwpxfiller" / "host" / "locations.py"
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


def test_job_content_fingerprints_go_through_the_registry_port():
    """지문은 **주입된 루트**를 지난 레지스트리 포트로만 낸다(U6-A 리뷰).

    모듈 함수를 직접 부르면 그 호출만 프로세스 기본 루트로 떨어져, 같은 작업의 지문을 두
    루트가 판정한다 — 「같은 상태를 두 곳이 판정하지 않는다」의 직접 위반이고, 증상은
    「열어 둔 편집 세션이 이유 없이 외부 변경 확인을 띄운다」로 나온다.
    """
    import re

    bare = re.compile(r"(?<![.\w])content_fingerprint\s*\(")
    offenders: "list[str]" = []
    for path in (ROOT / "src" / "hwpxfiller" / "webapp").glob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if bare.search(line) and not line.lstrip().startswith(("#", "def ", "*")):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == [], (
        "링2 가 job_store.content_fingerprint 를 직접 부릅니다 — "
        f"registry.content_fingerprint 로 보내세요: {offenders}"
    )
