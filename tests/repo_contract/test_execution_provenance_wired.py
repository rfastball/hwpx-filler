"""S3-99 잔여 해소(S4-11 #681): `evaluate_execution_provenance` 는 production caller 를 가진다.

S3-99 감사는 이 guard 의 판정은 옳으나 **production caller 0** 이라 「Configuration mismatch 실행
차단」이 런타임 참이 아니라고 지목했다(죽은 seam). #681 이 slotless run bridge admission 에서
그 guard 를 부른다 — 이 게이트가 그 caller 의 존재를 정적으로 못박는다(양성 대조 포함).
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "hwpxfiller"
_GUARD = "evaluate_execution_provenance"
_DEFINING = "work_bootstrap.py"


def _referencing_modules(name: str) -> set[Path]:
    hits: set[Path] = set()
    for path in _SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Name) and node.id == name:
                hits.add(path)
    return hits


def test_guard_is_defined() -> None:
    # 양성 대조 — guard 가 실재(FunctionDef)해야 caller 부재를 「부재」로 셀 수 있다(정의역 확인).
    defined = any(
        isinstance(node, ast.FunctionDef) and node.name == _GUARD
        for path in _SRC.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
    )
    assert defined, f"{_GUARD} 정의 부재"


def test_guard_has_production_caller_outside_defining_module() -> None:
    callers = {p for p in _referencing_modules(_GUARD) if p.name != _DEFINING}
    assert callers, (
        f"{_GUARD} production caller 0 — S3-99 가 지목한 죽은 seam. "
        "slotless run bridge(#681)가 부르지 않으면 실행 provenance 차단이 런타임 참이 아니다."
    )
