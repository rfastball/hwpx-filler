"""프런트엔드 정적 테스트가 source 역할 접근자를 우회하지 않는지 가드한다."""

from __future__ import annotations

import ast

from _web_source import REPO_ROOT, SOURCE_ENTRY, SOURCE_INDEX, SOURCE_ROOT, source_path


def test_source_role_accessor_is_internally_consistent() -> None:
    assert SOURCE_ROOT.parent == REPO_ROOT
    assert SOURCE_INDEX == source_path("index.html")
    assert SOURCE_ENTRY == source_path("src", "main.js")


def test_static_tests_do_not_rederive_physical_source_roots() -> None:
    """현재 ``frontend``와 폐기된 ``web`` 이름은 ``_web_source.py``만 소유한다.

    정적 계약이 저장소 루트에서 source 경로를 다시 조립하면 중앙 컷오버 때 그 테스트만 옛
    사본을 읽고도 초록일 수 있다. AST로 두 물리 이름의 직접 경로 조립을 막되, 설명 문자열과
    제품 코드의 runtime artifact resolver는 이 테스트의 범위에 넣지 않는다.
    """
    physical_roots = {"frontend", "web"}
    offenders: list[str] = []
    tests_dir = REPO_ROOT / "tests"
    for path in sorted(tests_dir.glob("*.py")):
        if path.name == "_web_source.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            direct_division = (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Div)
                and isinstance(node.right, ast.Constant)
                and node.right.value in physical_roots
            )
            direct_join = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "joinpath"
                and any(
                    isinstance(argument, ast.Constant)
                    and argument.value in physical_roots
                    for argument in node.args
                )
            )
            if direct_division or direct_join:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "정적 테스트가 source 역할 접근자를 우회해 물리 source 경로를 직접 조립합니다:\n"
        + "\n".join(offenders)
    )
