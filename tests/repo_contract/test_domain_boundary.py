"""P2가 세운 물리 Domain 경계와 legacy facade 형상을 검증한다."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]
DOMAIN_PACKAGE = ROOT / "src" / "hwpxfiller" / "domain"
LEGACY_FACADES = (
    (
        ROOT / "src" / "hwpxfiller" / "core" / "identity_summary.py",
        "hwpxfiller.domain.identity_summary",
        (
            "BLANK_CELL_MARK",
            "COGNITION_WIDTH",
            "MAX_COLUMNS",
            "DisqualifierStats",
            "SummaryStep",
            "IdentitySummary",
            "identity_summary",
        ),
    ),
    (
        ROOT / "src" / "hwpxfiller" / "core" / "source_profile.py",
        "hwpxfiller.domain.source_profile",
        ("SAMPLE_N", "FieldProfile", "tentative_type", "profile_fields"),
    ),
    (
        ROOT / "src" / "hwpxfiller" / "core" / "jamo.py",
        "hwpxfiller.domain.jamo",
        (
            "CHOSEONG",
            "JUNGSEONG",
            "JONGSEONG",
            "decompose",
            "jamo_find",
            "jamo_contains",
        ),
    ),
    (
        ROOT / "src" / "hwpxfiller" / "data" / "inline.py",
        "hwpxfiller.domain.inline",
        ("InlineDataSource",),
    ),
    (
        ROOT / "src" / "hwpxfiller" / "data" / "base.py",
        "hwpxfiller.domain.data_source",
        ("Record", "SUPPORTED_DATA_FILE_EXTENSIONS", "DataSource"),
    ),
)
ALLOWED_INTERNAL_PREFIXES = ("hwpxfiller.domain", "hwpxcore.domain")
CONCRETE_ADAPTER_ROOTS = {"lxml", "openpyxl", "webview"}
SRC = ROOT / "src"


def facade_consumers(
    facades: "tuple[tuple[Path, str, tuple[str, ...]], ...]",
) -> "list[str]":
    """구 경로를 지목하는 **제품** import 를 모은다 — 퇴역 가능성의 실측(#542 H-1).

    형상 검사(정의 0·동일 객체 재수출)는 facade 가 **정직한지**만 본다. 그것이 초록인
    채로 제품이 옛 주소를 계속 부르면 「이관 완료」 보고와 달리 파일을 지울 수 없다 —
    감사 PASS 조건(퇴역 승인)이 무는 것은 이쪽이다. 소비자가 0 이어야 #538 이 삭제를
    집행할 수 있고, 그때까지 이 단언이 재유입을 막는다.

    모집단에서 빼는 것은 facade 자신뿐이다(canonical 모듈은 구 경로를 부르지 않는다).
    """
    offenders: "list[str]" = []
    for legacy_facade, _canonical, _public_api in facades:
        legacy_module = _module_for_path(legacy_facade)
        for path in sorted(SRC.rglob("*.py")):
            if path == legacy_facade:
                continue
            offenders.extend(
                f"{path.relative_to(ROOT).as_posix()}:{lineno}: {module}"
                for module, lineno in _imports(path)
                if module == legacy_module or module.startswith(f"{legacy_module}.")
            )
    return offenders


def _module_for_path(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_from(package: str, *, level: int, module: str | None) -> str:
    if not level:
        return module or ""
    parts = package.split(".") if package else []
    keep = len(parts) - (level - 1)
    base = parts[: max(keep, 0)]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def _imports(path: Path) -> list[tuple[str, int]]:
    source = _module_for_path(path)
    package = source if path.name == "__init__.py" else source.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(package, level=node.level, module=node.module)
            if base:
                result.append((base, node.lineno))
            # 멤버까지 편다 — `from ..data import base` 처럼 패키지+멤버로 쪼갠 형이 base 로만
            # 접히면 모듈 단위 금지선(방향·facade 소비자)을 그대로 통과한다(기존 External
            # 경계 게이트의 관용구를 여기에도 맞춘다).
            result.extend(
                (f"{base}.{alias.name}" if base else alias.name, node.lineno)
                for alias in node.names
                if alias.name != "*"
            )
    return result


def _is_outward(module: str) -> bool:
    root = module.split(".", 1)[0]
    if root in CONCRETE_ADAPTER_ROOTS:
        return True
    if root not in {"hwpxcore", "hwpxfiller"}:
        return False
    return not any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in ALLOWED_INTERNAL_PREFIXES
    )


def test_hwpxfiller_domain_imports_point_inward() -> None:
    """Domain은 자기 경계나 독립 format Domain만 알고 바깥 제품 층은 모른다."""
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{lineno}: {module}"
        for path in sorted(DOMAIN_PACKAGE.rglob("*.py"))
        for module, lineno in _imports(path)
        if _is_outward(module)
    ]
    assert not offenders, "Domain의 바깥 방향 import:\n" + "\n".join(offenders)


def test_domain_legacy_facades_have_no_production_consumers() -> None:
    """구 Domain 경로를 부르는 제품 코드 0 — 형상이 정직해도 소비자가 있으면 못 지운다."""
    offenders = facade_consumers(LEGACY_FACADES)
    assert not offenders, (
        "구 경로 소비자가 남아 새 정본으로 옮기세요(퇴역 차단):\n" + "\n".join(offenders)
    )


def test_legacy_facades_only_reexport_domain_objects() -> None:
    """구 경로는 정의·wrapper 없이 각 새 정본의 공개 이름만 다시 노출한다."""
    for legacy_facade, domain_module, public_api in LEGACY_FACADES:
        tree = ast.parse(
            legacy_facade.read_text(encoding="utf-8"), filename=str(legacy_facade)
        )
        definitions = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert not definitions, (
            f"{legacy_facade.relative_to(ROOT)}에 새 정의가 있습니다: {definitions}"
        )

        domain_imports = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == domain_module
            and node.level == 0
        ]
        assert len(domain_imports) == 1, legacy_facade.relative_to(ROOT)
        imported = [(alias.name, alias.asname) for alias in domain_imports[0].names]
        assert imported == [(name, None) for name in public_api]

        assignments = [node for node in tree.body if isinstance(node, ast.Assign)]
        assert len(assignments) == 1, legacy_facade.relative_to(ROOT)
        assignment = assignments[0]
        assert [
            target.id for target in assignment.targets if isinstance(target, ast.Name)
        ] == ["__all__"]
        assert tuple(ast.literal_eval(assignment.value)) == public_api

        allowed_nodes = []
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                allowed_nodes.append(node)
            elif isinstance(node, ast.ImportFrom) and node.module in {
                "__future__",
                domain_module,
            }:
                allowed_nodes.append(node)
            elif node is assignment:
                allowed_nodes.append(node)
        assert allowed_nodes == tree.body
