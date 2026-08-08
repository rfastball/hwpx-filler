"""python symbol inventory — 폐포 전 모듈·심볼의 커밋 생성물과 드리프트 판정.

디자인 토큰·계약 생성기와 같은 4단 규약(render/check/rewrite/main)을 따른다. 생성물은
``docs/factgraph/python_symbol_inventory.toml`` 로 커밋되고, 신규 production 모듈·심볼이
생기면 재생성 전까지 게이트가 빨강이다 — P1 원장 밖에 계측되지 않은 표면이 조용히 서는
길을 막는다(#512 완료 조건).

이 파일은 **generated fact** 다. 사람이 판단을 적는 curated 원장(P1-03 Authority Ledger)
과 파일부터 분리한다. 기준 SHA 를 품지 않는 이유: 인벤토리는 살아있는 드리프트 기준이라
SHA 를 넣으면 모든 커밋이 드리프트가 된다(측정 스냅숏인 shard 와 역할이 다르다).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .closure import production_closure
from .collect import collect_symbols
from .schema import FactGraphError, parse_symbol_id

INVENTORY_REL_PATH = "docs/factgraph/python_symbol_inventory.toml"

REGEN_COMMAND = "uv run python scripts/gen_python_symbol_inventory.py"

_HEADER = f"""# 생성 파일 — 직접 편집 금지. production Python 심볼 인벤토리(P1-01 #512).
# 원천: pyproject wheel packages 폐포의 AST 심볼 전수(scripts/factgraph)
# 재생성: {REGEN_COMMAND}
# 검사:   {REGEN_COMMAND} --check
schema = "python-symbol-inventory/v1"
"""


def render(repo_root: Path) -> str:
    """폐포를 다시 계측해 인벤토리 본문을 만든다 — 결정론(정렬·개행 고정)."""
    repo_root = Path(repo_root)
    closure = production_closure(repo_root)
    symbols = collect_symbols(repo_root, closure)
    by_module: dict[str, list[str]] = {mf.module: [] for mf in closure.modules}
    for sym in symbols:
        if sym.kind == "module":
            continue  # 모듈 자체는 [[module]] 행이 담당한다
        by_module[sym.module].append(sym.id)
    parts = [_HEADER]
    for mf in closure.modules:
        parts.append("\n[[module]]\n")
        parts.append(f'name = "{mf.module}"\n')
        parts.append(f'path = "{mf.path}"\n')
        ids = sorted(by_module[mf.module])
        if not ids:
            parts.append("symbols = []\n")
        else:
            parts.append("symbols = [\n")
            parts.extend(f'  "{sid}",\n' for sid in ids)
            parts.append("]\n")
    return "".join(parts)


def check(repo_root: Path) -> "list[str]":
    """커밋본 ↔ 재생성본 대조. 문제 목록이 비면 초록이다."""
    repo_root = Path(repo_root)
    target = repo_root / INVENTORY_REL_PATH
    expected = render(repo_root)
    if not target.is_file():
        return [f"{INVENTORY_REL_PATH}: 생성물이 없습니다 — `{REGEN_COMMAND}` 로 생성하세요."]
    actual = target.read_text(encoding="utf-8")
    if actual == expected:
        return []
    problems = [f"{INVENTORY_REL_PATH}: 인벤토리 드리프트 — `{REGEN_COMMAND}` 로 재생성하세요."]
    problems.extend(_coordinate_diff(actual, expected))
    return problems


def rewrite(repo_root: Path) -> Path:
    repo_root = Path(repo_root)
    target = repo_root / INVENTORY_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(repo_root))
    return target


def _coordinate_diff(actual_text: str, expected_text: str) -> "list[str]":
    """무엇이 어긋났는지 좌표(모듈·심볼 이름)로 말한다 — 바이트 불일치만으로는 진단이 안 된다."""
    try:
        actual = _index(tomllib.loads(actual_text))
    except (tomllib.TOMLDecodeError, FactGraphError) as exc:
        return [f"커밋본을 파싱할 수 없다(직접 편집 흔적?): {exc}"]
    expected = _index(tomllib.loads(expected_text))
    out: list[str] = []
    for name in sorted(expected.keys() - actual.keys()):
        out.append(f"  커밋본에 없는 모듈: {name}")
    for name in sorted(actual.keys() - expected.keys()):
        out.append(f"  폐포에 더는 없는 모듈: {name}")
    for name in sorted(expected.keys() & actual.keys()):
        exp_syms, act_syms = expected[name], actual[name]
        for sid in sorted(exp_syms - act_syms):
            out.append(f"  커밋본에 없는 심볼: {sid}")
        for sid in sorted(act_syms - exp_syms):
            out.append(f"  폐포에 더는 없는 심볼: {sid}")
    return out


def _index(document: dict) -> "dict[str, set[str]]":
    out: dict[str, set[str]] = {}
    for row in document.get("module", []):
        name = row.get("name", "")
        if not name:
            raise FactGraphError("[[module]] 행에 name 이 없다")
        symbols = set(row.get("symbols", []))
        for sid in symbols:
            parse_symbol_id(sid)  # 형식 위반은 좌표 진단 이전에 구조 오류다
        out[name] = symbols
    return out
