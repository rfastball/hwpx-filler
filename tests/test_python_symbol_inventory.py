"""python symbol inventory 드리프트 게이트(#512 P1-01).

커밋된 ``docs/factgraph/python_symbol_inventory.toml`` 이 폐포 재계측과 일치하는지
판정하고, 그 판정의 판별력을 합성 변이로 증명한다(승계 형질 S1·S7 — 늘어도 줄어도
빨강이고, 초록은 실측으로 뒷받침된다). 폐포 대조는 생성기 코드를 거치지 않는 독립
오러클(tomllib 직접 파싱)로도 한 번 더 선다 — 생성기와 판독기가 같은 코드를 쓰면
같은 결함이 양쪽에서 상쇄된다(계약 생성기 게이트의 규율).
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

from factgraph import (
    INVENTORY_REL_PATH,
    REGEN_COMMAND,
    check,
    collect_symbols,
    parse_symbol_id,
    production_closure,
    render,
    rewrite,
)

ROOT = Path(__file__).resolve().parents[1]


def test_pristine_inventory_is_green() -> None:
    problems = check(ROOT)
    assert not problems, "인벤토리 드리프트: " + " / ".join(problems)


def test_render_is_deterministic() -> None:
    assert render(ROOT) == render(ROOT)


def test_committed_header_declares_generated_artifact() -> None:
    text = (ROOT / INVENTORY_REL_PATH).read_text(encoding="utf-8")
    assert "직접 편집 금지" in text
    assert REGEN_COMMAND in text  # 복구 명령이 파일 자신에 실려 있다


def test_committed_inventory_covers_closure_exactly() -> None:
    """독립 오러클 — 생성기(render)를 부르지 않고 커밋본과 폐포를 직접 대조한다."""
    document = tomllib.loads((ROOT / INVENTORY_REL_PATH).read_text(encoding="utf-8"))
    rows = {row["name"]: row for row in document["module"]}
    closure = production_closure(ROOT)
    assert set(rows) == {m.module for m in closure.modules}, "모듈 집합이 폐포와 다르다"
    for mf in closure.modules:
        assert rows[mf.module]["path"] == mf.path
    committed_ids = {sid for row in rows.values() for sid in row["symbols"]}
    for sid in committed_ids:
        module, _qualname, kind = parse_symbol_id(sid)
        assert module in rows, f"심볼이 미등재 모듈을 가리킨다: {sid}"
        assert kind != "module", f"모듈 심볼은 [[module]] 행이 담당한다: {sid}"
    measured_ids = {s.id for s in collect_symbols(ROOT, closure) if s.kind != "module"}
    assert committed_ids == measured_ids, (
        f"커밋본 심볼 {len(committed_ids)} ≠ 실측 {len(measured_ids)} — `{REGEN_COMMAND}`"
    )


# ---------------------------------------------------------------------------
# 판별력 — 합성 저장소 1좌표 변이가 각각 빨강을 낸다
# ---------------------------------------------------------------------------


def _mini_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "alpha").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        "[project]\nname = \"mini\"\nversion = \"0\"\n\n"
        '[tool.hatch.build.targets.wheel]\npackages = ["src/alpha"]\n',
        encoding="utf-8",
    )
    (repo / "src" / "alpha" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "src" / "alpha" / "mod.py").write_text(
        "def existing():\n    pass\n", encoding="utf-8"
    )
    rewrite(repo)
    assert check(repo) == []
    return repo


def _copy(repo: Path, tmp_path: Path, name: str) -> Path:
    clone = tmp_path / name
    shutil.copytree(repo, clone)
    return clone


def test_missing_inventory_is_loud(tmp_path: Path) -> None:
    repo = _mini_repo(tmp_path)
    (repo / INVENTORY_REL_PATH).unlink()
    problems = check(repo)
    assert problems and "생성물이 없습니다" in problems[0]


def test_mutations_each_turn_the_gate_red(tmp_path: Path) -> None:
    base = _mini_repo(tmp_path)

    new_module = _copy(base, tmp_path, "new_module")
    (new_module / "src" / "alpha" / "fresh.py").write_text("A = 1\n", encoding="utf-8")
    problems = check(new_module)
    assert problems and any("alpha.fresh" in p for p in problems), problems

    new_symbol = _copy(base, tmp_path, "new_symbol")
    with open(new_symbol / "src" / "alpha" / "mod.py", "a", encoding="utf-8") as fh:
        fh.write("\ndef appeared():\n    pass\n")
    problems = check(new_symbol)
    assert problems and any("alpha.mod:appeared#function" in p for p in problems), problems

    removed_symbol = _copy(base, tmp_path, "removed_symbol")
    (removed_symbol / "src" / "alpha" / "mod.py").write_text("A = 1\n", encoding="utf-8")
    problems = check(removed_symbol)
    assert problems and any("alpha.mod:existing#function" in p for p in problems), problems

    renamed = _copy(base, tmp_path, "renamed")
    (renamed / "src" / "alpha" / "mod.py").write_text(
        "def renamed_fn():\n    pass\n", encoding="utf-8"
    )
    problems = check(renamed)
    assert any("alpha.mod:renamed_fn#function" in p for p in problems), problems
    assert any("alpha.mod:existing#function" in p for p in problems), problems

    edited = _copy(base, tmp_path, "edited")
    target = edited / INVENTORY_REL_PATH
    text = target.read_text(encoding="utf-8")
    target.write_text(
        text.replace("alpha.mod:existing#function", "alpha.mod:forged#function"),
        encoding="utf-8",
    )
    problems = check(edited)
    assert problems, "손편집 1좌표가 초록을 통과했다"
    assert any("forged" in p for p in problems), problems

    # 복구 명령이 실패 메시지에 실린다 — 좌표만 말하고 복구법을 숨기지 않는다
    assert any(REGEN_COMMAND in p for p in check(new_symbol)), "복구 명령 부재"
