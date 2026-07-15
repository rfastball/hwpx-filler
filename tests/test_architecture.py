from __future__ import annotations

import ast
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
