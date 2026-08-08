"""P1-02C persistence·external effect·host 전수 분류의 판별력·드리프트 게이트(#515).

합성 저장소에서 효과/순수 분할·지역 import 폐쇄·INFERRED 렌즈·composes 의 양성·음성을
각각 세우고, 실 저장소에서는 커밋 원장을 독립 파싱해 02A digest 핀과의 교차 앵커까지
대조한다. 「이 초록이 재는 것」: 폐포의 모든 외부 접촉 좌표가 효과 분류 ∪ 명시 순수
제외의 정확히 한쪽에 앉는다는 분할 그 자체다.
"""

from __future__ import annotations

import subprocess
import textwrap
import tomllib
from pathlib import Path

import pytest
from factgraph.effect_graph import (
    BASELINE_SHA,
    LEDGER_REL_PATH,
    REGEN_COMMAND,
    build,
    check,
    classify_external,
    dual_assembly,
    effect_module_profiles,
    render,
    rewrite,
    uncovered_external_contacts,
    uncovered_local_import_calls,
)
from factgraph.schema import RELATIONS, Evidence, Fact, FactGraphError, Provenance

ROOT = Path(__file__).resolve().parents[1]


def _mini_repo(tmp_path: Path, files: "dict[str, str]", *, name: str = "repo") -> Path:
    repo = tmp_path / name
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        "[project]\nname = \"mini\"\nversion = \"0\"\n\n"
        '[tool.hatch.build.targets.wheel]\npackages = ["src/alpha"]\n',
        encoding="utf-8",
    )
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return repo


def test_effect_relations_are_registered_schema_vocabulary() -> None:
    """02C 어휘는 중앙 스키마에 산다 — 사설 relation 은 Fact 생성 시점에 죽는다."""
    for relation in ("reads_external", "writes_external", "invokes_external", "composes"):
        assert relation in RELATIONS
    fact = Fact(
        src="alpha.mod:#module",
        rel="reads_external",
        dst="ext:os.walk",
        grade="STATIC_CONFIRMED",
        evidence=Evidence("src/alpha/mod.py", 1),
        provenance=Provenance("factgraph.effect_graph", "effect_fs"),
    )
    assert fact.rel == "reads_external"


def test_pure_path_computation_is_never_promoted_to_effect(tmp_path: Path) -> None:
    """#515 불변식 — '파일을 다룬다'는 이유로 순수 path 계산을 효과로 승격하지 않는다."""
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/naming.py": """
                import os
                from pathlib import Path

                def plan(base, name):
                    joined = os.path.join(base, name)
                    return Path(os.path.normcase(joined)).name
            """,
        },
    )
    result = build(repo)
    assert result.effect_facts == ()
    assert result.composes_facts == ()
    labels = {r.label for r in result.pure_records}
    assert "path_value" in labels  # 제외가 침묵이 아니라 명시 기록이다
    assert uncovered_external_contacts(result) == []


def test_direct_effects_split_by_direction_and_class(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/store.py": """
                import os
                import shutil

                def read(path):
                    with open(path, encoding="utf-8") as fh:
                        return fh.read()

                def commit(tmp, final):
                    os.replace(tmp, final)

                def drop(tree):
                    shutil.rmtree(tree)

                def label(path):
                    return os.path.basename(path)
            """,
        },
    )
    result = build(repo)
    rows = {
        (f.rel, f.dst, f.provenance.rule)
        for f in result.effect_facts
    }
    assert ("invokes_external", "ext:builtins.open", "effect_fs") in rows
    assert ("writes_external", "ext:os.replace", "effect_fs") in rows
    assert ("writes_external", "ext:shutil.rmtree", "effect_fs") in rows
    # 같은 모듈의 순수 이름 계산은 효과 좌표가 아니다 — 분할의 음성 면.
    assert not any("basename" in f.dst for f in result.effect_facts)
    assert uncovered_external_contacts(result) == []


def test_unregistered_external_name_dies_loudly(tmp_path: Path) -> None:
    """조용한 세 번째 바구니 금지 — 미등록 외부 이름은 분류될 때까지 빨갛다."""
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                import madeuplib

                def go():
                    return madeuplib.launch()
            """,
        },
    )
    with pytest.raises(FactGraphError, match="미등록 외부 이름"):
        build(repo)


def test_partition_oracle_bites_when_an_effect_fact_is_dropped(tmp_path: Path) -> None:
    """오러클의 양성 판별력 — 좌표는 남고 분류 사실만 사라진 상태를 빨갛게 만든다."""
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                def read(path):
                    return open(path).read()
            """,
        },
    )
    result = build(repo)
    assert uncovered_external_contacts(result) == []
    import dataclasses

    hollowed = dataclasses.replace(
        result,
        effect_facts=tuple(
            f for f in result.effect_facts if f.dst != "ext:builtins.open"
        ),
    )
    problems = uncovered_external_contacts(hollowed)
    assert problems and any("분할" in problem for problem in problems)


def test_local_import_call_closes_only_on_unique_binding(tmp_path: Path) -> None:
    """지역 import 경유 호출 — 유일 결속만 ext 로 닫고 재결속은 열린 원장 행으로 남긴다."""
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                def launch(cmd):
                    import subprocess

                    return subprocess.run(cmd, check=True)

                def rebound(cmd, fake):
                    import subprocess

                    subprocess = fake
                    return subprocess.run(cmd)
            """,
        },
    )
    result = build(repo)
    closed = [s for s in result.local_sites if s.verdict != "open"]
    opened = [s for s in result.local_sites if s.verdict == "open"]
    assert [s.resolved for s in closed] == ["ext:subprocess.run"]
    assert closed[0].verdict == "invokes_external"
    assert any(
        f.rel == "invokes_external"
        and f.dst == "ext:subprocess.run"
        and f.grade == "STATIC_CONFIRMED"
        and f.provenance.rule == "local_effect_process"
        for f in result.effect_facts
    )
    assert len(opened) == 1  # 재결속 자리 — 임의 추측 대신 열린 행
    assert not any(
        f.dst == "ext:subprocess.run" and f.evidence.line == opened[0].line
        for f in result.effect_facts
    )
    assert uncovered_local_import_calls(repo, result) == []


def test_receiver_unknown_path_methods_stay_inferred_not_fact(tmp_path: Path) -> None:
    """수신자 미상 Path 판별 메서드는 INFERRED 로만 적는다 — str 과 겹치는 이름은 침묵."""
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                def persist(target, body):
                    target.write_text(body, encoding="utf-8")
                    return target.exists()

                def rewrite_label(label):
                    return label.replace("a", "b")

                def snapshot(book, path):
                    return book.save(path)
            """,
        },
    )
    result = build(repo)
    inferred = {
        (f.rel, f.dst, f.grade)
        for f in result.effect_facts
        if f.provenance.rule.startswith("fs_name_")
    }
    assert ("writes_external", "?:local:target.write_text", "INFERRED") in inferred
    assert ("reads_external", "?:local:target.exists", "INFERRED") in inferred
    # str.replace·workbook.save 는 판별력이 없어 넣지 않는다 — 거짓 양성의 음성 대조.
    assert not any("replace" in dst for _rel, dst, _grade in inferred)
    assert not any(".save" in dst for _rel, dst, _grade in inferred)


def test_composes_marks_only_effect_bearing_concrete_classes(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/store.py": """
                class DiskStore:
                    def load(self, path):
                        return open(path).read()
            """,
            "src/alpha/model.py": """
                class Row:
                    pass
            """,
            "src/alpha/app.py": """
                from alpha.model import Row
                from alpha.store import DiskStore

                def wire():
                    return DiskStore(), Row()
            """,
        },
    )
    result = build(repo)
    composed = {f.dst for f in result.composes_facts}
    assert "alpha.store:DiskStore#class" in composed
    assert "alpha.model:Row#class" not in composed  # 효과 없는 모듈의 클래스는 조립 증거 밖
    assert all(f.rel == "composes" for f in result.composes_facts)


def test_native_direct_call_mutation_flips_module_into_effect_profile(
    tmp_path: Path,
) -> None:
    """native direct-call 판별력 — 순수 모듈에 FFI 호출 하나가 생기면 프로필에 나타난다."""
    body_clean = """
        def compute(a, b):
            return a + b
    """
    body_native = """
        import ctypes

        def compute(a, b):
            ctypes.WinDLL("user32")
            return a + b
    """
    repo = _mini_repo(
        tmp_path,
        {"src/alpha/__init__.py": "", "src/alpha/logic.py": body_clean},
        name="clean",
    )
    assert "alpha.logic" not in effect_module_profiles(build(repo))
    mutated = _mini_repo(
        tmp_path,
        {"src/alpha/__init__.py": "", "src/alpha/logic.py": body_native},
        name="mutated",
    )
    profiles = effect_module_profiles(build(mutated))
    assert profiles["alpha.logic"]["invokes"] == 1
    assert classify_external("ctypes.WinDLL") == (
        "effect", "invokes_external", "host_native"
    )


def test_dual_assembly_surfaces_cross_package_consumption(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/eff/__init__.py": "",
            "src/alpha/eff/store.py": """
                def persist(path, body):
                    open(path, "w").write(body)
            """,
            "src/alpha/one/__init__.py": "",
            "src/alpha/one/entry.py": """
                from alpha.eff.store import persist

                def run():
                    persist("a", "b")
            """,
            "src/alpha/two/__init__.py": "",
            "src/alpha/two/entry.py": """
                from alpha.eff.store import persist

                def run():
                    persist("c", "d")
            """,
        },
    )
    rows = dual_assembly(build(repo))
    row = next(r for r in rows if r["dst"] == "alpha.eff.store:persist#function")
    assert row["packages"] == ["alpha.one", "alpha.two"]


def test_generated_ledger_is_deterministic_and_drift_sensitive(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                def persist(path, body):
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(body)
            """,
        },
    )
    assert render(repo) == render(repo)
    target = rewrite(repo)
    assert target == repo / LEDGER_REL_PATH
    assert check(repo) == []
    document = tomllib.loads(target.read_text(encoding="utf-8"))
    assert document["baseline"]["git_sha"] == BASELINE_SHA
    assert document["counts"]["uncovered_external_contacts"] == 0
    assert document["counts"]["uncovered_local_import_calls"] == 0
    assert document["effect_by_class"]["fs"] >= 1

    with open(repo / "src/alpha/mod.py", "a", encoding="utf-8") as fh:
        fh.write("\ndef appeared(tree):\n    import shutil\n    shutil.rmtree(tree)\n")
    problems = check(repo)
    assert problems and "원장 드리프트" in problems[0]
    assert any("digest" in problem for problem in problems)
    assert REGEN_COMMAND in problems[0]


def test_real_graph_ledger_and_02a_pins_match_exactly() -> None:
    """실폐포 게이트 — 02C 원장·02A digest 핀·오러클 0 을 한 측정에서 교차 대조한다."""
    baseline = subprocess.run(
        ["git", "cat-file", "-e", f"{BASELINE_SHA}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert baseline.returncode == 0, f"baseline commit 부재: {baseline.stderr}"
    source_diff = subprocess.run(
        ["git", "diff", "--quiet", BASELINE_SHA, "--", "src"],
        cwd=ROOT,
        check=False,
    )
    assert source_diff.returncode == 0, "baseline 이후 production src/가 바뀌었다 — SHA를 재확정하라"

    result = build(ROOT)
    assert uncovered_external_contacts(result) == []
    assert uncovered_local_import_calls(ROOT, result) == []
    assert check(ROOT) == [], f"`{REGEN_COMMAND}` 로 원장을 재생성해야 한다"

    document = tomllib.loads((ROOT / LEDGER_REL_PATH).read_text(encoding="utf-8"))
    assert document["digests"] == {
        "base_facts": result.static.base_digest,
        "graph_facts": result.static.graph_digest,
        "effect_facts": result.effect_digest,
    }
    # 교차 앵커 — 02C 는 02A 와 같은 측정 위의 shard 다(4개 슬라이스 공통 앵커).
    upstream = tomllib.loads(
        (ROOT / "docs/factgraph/static_graph_02a.toml").read_text(encoding="utf-8")
    )
    assert upstream["digests"]["base_facts"] == result.static.base_digest
    assert upstream["digests"]["graph_facts"] == result.static.graph_digest

    counts = document["counts"]
    assert counts["local_import_open"] == 0
    assert counts["local_import_closed"] >= 10
    assert counts["effect_facts_confirmed"] >= 100
    assert counts["effect_facts_inferred_fs"] >= 50
    assert counts["composes_edges"] >= 100
    assert counts["effect_modules"] >= 20

    by_class = document["effect_by_class"]
    for required in (
        "archive",
        "excel",
        "fs",
        "env",
        "clock",
        "host_native",
        "host_webview",
        "registry",
        "process",
    ):
        assert by_class.get(required, 0) >= 1, f"효과 분류 {required} 실측 0 — 폐포와 어긋난다"

    # durable persistence 연결 — 효과 모듈 전수가 소비자 목록을 들고, 프로필과 원장이 같다.
    profiles = effect_module_profiles(result)
    committed_rows = {row["module"]: row for row in document["effect_module"]}
    assert set(committed_rows) == set(profiles)
    for module, row in profiles.items():
        committed = committed_rows[module]
        assert committed["reads"] == row["reads"]
        assert committed["writes"] == row["writes"]
        assert committed["invokes"] == row["invokes"]
        assert committed["inferred_fs"] == row["inferred_fs"]
        assert tuple(committed["consumers"]) == row["consumers"]

    # GUI/CLI 조립 대조 — 이중 조립 표가 재계측과 좌표 단위로 같다.
    assert [
        (row["dst"], tuple(row["packages"]), tuple(row["consumers"]))
        for row in document.get("dual_assembly", [])
    ] == [
        (row["dst"], tuple(row["packages"]), tuple(row["consumers"]))
        for row in dual_assembly(result)
    ]
    assert counts["dual_assembly_rows"] >= 10

    # INFERRED 렌즈는 전부 INFERRED 등급이다 — FACT 위조 금지의 실폐포 단언.
    assert all(
        f.grade == "INFERRED"
        for f in result.effect_facts
        if f.provenance.rule.startswith("fs_name_")
    )
