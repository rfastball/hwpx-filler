from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _import_roots(package: str) -> set[str]:
    roots: set[str] = set()
    for path in (ROOT / "src" / package).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def test_products_do_not_import_each_other() -> None:
    assert "hwpxfiller" not in _import_roots("hwpxdiff")
    assert "hwpxdiff" not in _import_roots("hwpxfiller")


def test_src_has_no_pyside6_runtime_imports() -> None:
    """웹 이관(#20·#22·#23) 후 src/ 전체에 PySide6/shiboken6 런타임 임포트가 0 임을 못박는다.

    Qt 위젯 계층은 물리 삭제됐고 두 제품 프론트엔드는 pywebview 다 — 어떤 모듈이든 Qt 를
    다시 끌어오면(위젯 부활·실수 임포트) 여기서 시끄럽게 막는다(재유입 차단). 링1 상태
    모듈이 docstring 에 'PySide6' 를 언급해도 실 임포트가 아니면 통과한다(AST 임포트만 스캔)."""
    forbidden = {"PySide6", "shiboken6"}
    offenders: list[str] = []
    for package in ("hwpxcore", "hwpxdiff", "hwpxfiller"):
        for path in (ROOT / "src" / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                if any(n.split(".", 1)[0] in forbidden for n in names):
                    offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"src 에 PySide6 런타임 임포트 재유입: {sorted(set(offenders))}"


def test_hwpxcore_native_stays_product_agnostic() -> None:
    """hwpxcore.native(공용 Win32 글루)는 제품·Qt 를 임포트하지 않는다.

    diff·filler 웹이 파일 다이얼로그·클립보드를 이 공용 계층으로만 공유한다 — core 가
    제품(hwpxfiller/hwpxdiff)이나 PySide6 로 역의존하면 그 공유 전제가 무너지므로 시끄럽게
    막는다. stdlib+ctypes 만 허용."""
    forbidden = {"PySide6", "shiboken6", "hwpxfiller", "hwpxdiff"}
    roots = _import_roots("hwpxcore")  # native 는 hwpxcore 하위 — 패키지 전체를 스캔
    native_roots: set[str] = set()
    for path in (ROOT / "src" / "hwpxcore" / "native").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                native_roots.update(a.name.split(".", 1)[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                native_roots.add(node.module.split(".", 1)[0])
    assert not (forbidden & native_roots), (
        f"hwpxcore.native 가 금지 패키지를 임포트한다: {forbidden & native_roots}"
    )
    assert forbidden.isdisjoint(roots), "hwpxcore 가 제품/Qt 로 역의존한다 — core 는 아래로만"


def test_hwpxdiff_core_module_is_qt_free() -> None:
    """hwpxdiff/diff.py(+cli.py)는 stdlib+hwpxcore 만 — 성형·그룹화·렌더 로직이 뷰로
    돌아가 GUI/CLI 표면이 갈라지는 회귀(RC-17)를 막는다."""
    for module in ("diff.py", "cli.py"):
        path = ROOT / "src" / "hwpxdiff" / module
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any(n.split(".", 1)[0] in ("PySide6", "shiboken6") for n in names), (
                f"hwpxdiff/{module} 에 Qt 임포트가 들어왔다 — 순수 계층을 지켜라"
            )


def test_filler_data_package_imports_no_core_or_qt() -> None:
    """data/ 는 헤드리스 어댑터 계층 — hwpxfiller.core·PySide6 역의존 금지.

    풀 항목 복원(source_from_pool_item)이 덕타입(.kind/.opts)만 읽는 이유가 이
    불변식이다. 시트 열거 헬퍼(sheet_overview) 등 신규 코드가 코어·Qt 를 끌어오면
    여기서 시끄럽게 알린다.
    """
    forbidden = {"PySide6", "shiboken6"}
    for path in (ROOT / "src" / "hwpxfiller" / "data").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
                # 상대 임포트(from ..core import …)도 core 역의존이다.
                if node.level >= 2:
                    assert node.module.split(".", 1)[0] != "core", (
                        f"data/{path.name} 가 상대 경로로 core 를 임포트한다 — 역의존 금지"
                    )
            for n in names:
                root = n.split(".", 1)[0]
                assert root not in forbidden, (
                    f"data/{path.name} 에 Qt 임포트가 들어왔다 — 헤드리스 계층을 지켜라"
                )
                assert not n.startswith("hwpxfiller.core"), (
                    f"data/{path.name} 가 hwpxfiller.core 를 임포트한다 — 역의존 금지"
                )


def test_pool_registry_construction_has_one_call_site() -> None:
    """webapp 의 ``DatasetPoolRegistry(...)`` 생성은 ``screens.py`` 의
    ``default_pool_registry()`` 단일 출처를 통해서만 — 인라인 재구현 재유입 차단.

    2026-07-16 high 코드리뷰(#26 웹 패리티 2차)에서 이 팩토리보다 나중에 커밋된
    ``screen_editor.py``가 팩토리를 쓰지 않고 ``DatasetPoolRegistry(default_dataset_pool_dir())``
    를 그대로 복붙한 결함이 확정됐다(``screen_pool.py`` 도 동형 — 다만 그쪽은 팩토리
    도입보다 먼저 작성돼 역사적으로는 이해 가능하나 지금은 정합 대상). 팩토리가 나중에
    바뀌면(캐싱·환경변수 오버라이드 등) 인라인 사본은 조용히 구식 동작을 유지한다 — 그
    드리프트를 재유입 즉시 차단한다. ``gui/`` 계층(Qt 시절 VM, 팩토리보다 먼저 존재)은
    이 규칙 밖이다 — webapp 이 아래로 임포트하는 방향이라 gui 가 webapp 을 참조할 수 없다.
    """
    pattern = re.compile(r"\bDatasetPoolRegistry\(")
    offenders: list[str] = []
    webapp_dir = ROOT / "src" / "hwpxfiller" / "webapp"
    for path in sorted(webapp_dir.glob("*.py")):
        if path.name == "screens.py":
            continue  # 단일 출처(default_pool_registry 정의부)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "DatasetPoolRegistry 인라인 재구현 재유입 — "
        "webapp/screens.py 의 default_pool_registry() 를 참조하라:\n" + "\n".join(offenders)
    )


def test_home_controller_does_not_bypass_vm_registry() -> None:
    """webapp/screen_home.py 는 ``self.vm.registry`` 에 직접 접근하지 않는다(#44).

    HomeViewModel 의 공개 표면(JobRow 필드 + 메서드)이 seam 계약이다(home_state.py
    docstring). 2026-07-16 리뷰에서 ``_do_set_tags`` 만 이 계약을 우회해 컨트롤러가
    ``vm.registry.load/save`` 를 직접 호출한 결함이 확정됐다 — 검증 규칙이 Qt-free
    계층 밖으로 새고, 다른 모든 액션(위임 규약)과 어긋난다. 스코프를 ``screen_home.py``
    단일 파일로 좁힌 이유: 저장소에는 별개 개념의 registry(데이터 풀)가 공존하고
    ``screen_pool.py`` 는 그걸 정당하게 직접 소유한다 — 파일 전역 문자열 grep 은
    두 개념을 뒤섞으므로 AST 로 ``self.vm.registry`` 접근 경로만 정확히 잡는다.
    """
    path = ROOT / "src" / "hwpxfiller" / "webapp" / "screen_home.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "registry"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "vm"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
        ):
            offenders.append(f"screen_home.py:{node.lineno}")
    assert not offenders, (
        "홈 컨트롤러가 VM seam 을 우회해 vm.registry 에 직접 접근한다 — "
        "HomeViewModel 메서드로 위임하라(#44): " + ", ".join(offenders)
    )


def test_core_mapping_carries_no_source_specific_vocabulary() -> None:
    """범용 코어(core/mapping.py)는 특정 API 어휘를 품지 않는다(V1 소스 어휘 소유권).

    어휘(예: 나라장터 영문 코드 키·NARA_ALIASES)는 소유 소스(data/nara.py)로
    승격됐다. suggest_mappings 의 aliases 는 순수 범용 인자다 — 코어에 API별
    문자열이 새로 스며들면 README "core = no product logic" 규칙 위반을 알린다.
    """
    text = (ROOT / "src" / "hwpxfiller" / "core" / "mapping.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("NARA_ALIASES", "bidNtce", "presmptPrce", "opengDate"):
        assert forbidden not in text, (
            f"core/mapping.py 에 소스별 어휘 {forbidden!r} 가 남아 있다 — 소스로 승격하라"
        )
