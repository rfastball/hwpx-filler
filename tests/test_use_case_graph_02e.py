"""P1-02E use-case·test responsibility 원장의 판별력·드리프트 게이트(#517).

합성 저장소에서 entry 분모 유도(CLI 가드/플래그/기본·GUI 액션/직접/부팅), 시임 홉 3규칙,
COMMON/DUPLICATE 분류, oracle 연결·characterization gap 의 양성·음성을 각각 세운다.
실저장소에서는 커밋 원장을 독립 파싱해 재유도 분모와 좌표 단위로 대조한다(「entry 미분류 0」
의 기계화 — 02A 호출-노드 전수성 오러클과 같은 형).

관측자 순환의 자기 검증: 이 파일 자체가 원장의 테스트 분모에 든다(제외 규칙 없음). 아래
실저장소 게이트가 자기 행의 존재와 제품 참조 0 을 단언해, 스캐너가 자기 산출물을 조용히
빼는 길과 이 파일이 제품 심볼을 들기 시작하는 길을 동시에 막는다.
"""

from __future__ import annotations

import textwrap
import tomllib
from pathlib import Path

import pytest
from factgraph.schema import FactGraphError
from factgraph.static_graph import LEDGER_REL_PATH as LEDGER_02A_REL_PATH
from factgraph.use_case_graph import (
    CORE_BASES,
    ENTRY_BASES,
    LEDGER_REL_PATH,
    OracleLink,
    build_use_cases,
    check,
    render,
    scan_test_files,
)

ROOT = Path(__file__).resolve().parents[1]
SELF_REL_PATH = Path(__file__).resolve().relative_to(ROOT).as_posix()


def _mini_repo(tmp_path: Path, files: "dict[str, str]", *, name: str = "repo") -> Path:
    repo = tmp_path / name
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "mini"
            version = "0"

            [project.scripts]
            runcli = "alpha.cli:main"

            [project.gui-scripts]
            runwin = "alpha.ui.win:main"

            [tool.hatch.build.targets.wheel]
            packages = ["src/alpha"]

            [tool.pytest.ini_options]
            markers = ["zeta: 합성 자원 축"]
            """
        ).lstrip(),
        encoding="utf-8",
    )
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return repo


_CORE = """
    def boil():
        return "boil"

    def steep():
        return "steep"

    def stir():
        return "stir"

    def whisk():
        return "whisk"

    def drain():
        return "drain"

    class Engine:
        def run(self):
            return boil()

    class Kettle:
        def warm(self):
            return None
"""

_CLI = """
    import argparse

    from .core import Kettle, boil, steep, stir


    def _brew_main(argv):
        steep()
        return 0


    def _mix_main(argv):
        stir()
        return 0


    def main(argv=None):
        return _run(argv or [])


    def _run(argv):
        if argv and argv[0] == "brew":
            return _brew_main(argv[1:])
        if argv and argv[0] == "mix":
            return _mix_main(argv[1:])
        if argv and argv[0] == "void":
            return 2
        ap = argparse.ArgumentParser()
        ap.add_argument("--input", required=True)
        ap.add_argument("--fast", action="store_true")
        args = ap.parse_args(argv)
        if args.fast:
            kettle = Kettle()
            kettle.warm()
            return 0
        boil()
        return 0
"""

_PANELS = """
    from ..core import Engine, drain, steep, whisk


    class JobPanel:
        name = "job"

        def __init__(self):
            self.engine = Engine()
            self.mist = dict()

        def initial(self):
            return {}

        def dispatch(self, action, payload):
            handler = getattr(self, f"_op_{action}", None)
            if handler is None:
                raise ValueError(action)
            return handler(payload)

        def _op_steep(self, payload):
            steep()
            return {}

        def _op_mix(self, payload):
            whisk()
            return {}

        def _op_local(self, payload):
            eng = Engine()
            eng.run()
            return {}

        def _op_attr(self, payload):
            self.engine.run()
            return {}

        def _op_fog(self, payload):
            self.mist.clear()
            return {}

        def ship(self):
            return self.engine.run()


    class PoolPanel:
        name = "pool"

        def initial(self):
            return {}

        def dispatch(self, action, payload):
            handler = getattr(self, f"_op_{action}", None)
            if handler is None:
                raise ValueError(action)
            return handler(payload)

        def _op_drain(self, payload):
            drain()
            return {}
"""

_WIN = """
    from .panels import JobPanel, PoolPanel


    class Gateway:
        def __init__(self):
            job = JobPanel()
            pool = PoolPanel()
            self.panels = {job.name: job, pool.name: pool}

        def _sel(self, screen):
            return self.panels[screen]

        def initial(self, screen):
            return self._sel(screen).initial()

        def dispatch(self, screen, action, payload):
            return self._sel(screen).dispatch(action, payload)

        def ship(self, screen):
            return self._sel(screen).ship()


    def main():
        gate = Gateway()
        return gate
"""

_FIXTURE_SRC = {
    "src/alpha/__init__.py": "",
    "src/alpha/core.py": _CORE,
    "src/alpha/cli.py": _CLI,
    # GUI 표면은 전용 패키지에 산다(실저장소 구조와 동형 — core 투영 전제).
    "src/alpha/ui/__init__.py": "",
    "src/alpha/ui/panels.py": _PANELS,
    "src/alpha/ui/win.py": _WIN,
}


def test_entry_denominator_is_derived_from_both_hosts(tmp_path: Path) -> None:
    """CLI 가드/플래그/기본과 GUI 액션/직접/부팅 entry 가 구조 유도로 전수 선다."""
    repo = _mini_repo(tmp_path, {**_FIXTURE_SRC, "tests/test_stub.py": "def test_ok():\n    pass\n"})
    result = build_use_cases(repo)
    ids = {entry.entry_id for entry in result.entries}
    assert ids == {
        "cli:brew",
        "cli:mix",
        "cli:void",
        "cli:--fast",
        "cli:default",
        "gui:job/steep",
        "gui:job/mix",
        "gui:job/local",
        "gui:job/attr",
        "gui:job/fog",
        "gui:pool/drain",
        "gui:direct/ship",
        "gui:job/initial",
        "gui:pool/initial",
    }
    kinds = {entry.entry_id: entry.kind for entry in result.entries}
    assert kinds["cli:brew"] == "cli_subcommand"
    assert kinds["cli:--fast"] == "cli_flag"
    assert kinds["cli:default"] == "cli_default"
    assert kinds["gui:job/steep"] == "gui_action"
    assert kinds["gui:direct/ship"] == "gui_direct"
    assert kinds["gui:pool/initial"] == "gui_screen_boot"
    # 안내-전용 가드(cli:void)는 root 0 — 경로 없음을 지어내지 않는다.
    assert next(e for e in result.entries if e.entry_id == "cli:void").roots == ()
    # 라우터(전 컨트롤러 공유 공개 메서드)는 직접 entry 로 서지 않는다.
    assert not any(e.entry_id in ("gui:direct/initial", "gui:direct/dispatch") for e in result.entries)


def test_denominator_reacts_to_handler_and_guard_mutation(tmp_path: Path) -> None:
    """분모 오러클의 음성 판별력 — 핸들러/가드를 지우면 entry 가 함께 사라진다."""
    repo = _mini_repo(tmp_path, {**_FIXTURE_SRC, "tests/test_stub.py": "def test_ok():\n    pass\n"})
    before = {entry.entry_id for entry in build_use_cases(repo).entries}
    ledger_before = render(repo, _baseline_checked=True)

    panels = repo / "src/alpha/ui/panels.py"
    body = panels.read_text(encoding="utf-8")
    without_handler = body.replace(
        "    def _op_fog(self, payload):\n        self.mist.clear()\n        return {}\n", ""
    )
    assert without_handler != body
    panels.write_text(without_handler, encoding="utf-8")

    after = {entry.entry_id for entry in build_use_cases(repo).entries}
    assert before - after == {"gui:job/fog"}
    assert render(repo, _baseline_checked=True) != ledger_before  # 드리프트가 원장에 나타난다


def test_seam_rules_restore_only_provable_hops(tmp_path: Path) -> None:
    """attr/local/transport 3규칙의 양성과, 증명 불가 결속의 음성이 각각 선다."""
    repo = _mini_repo(tmp_path, {**_FIXTURE_SRC, "tests/test_stub.py": "def test_ok():\n    pass\n"})
    result = build_use_cases(repo)
    routes = result.routes
    run_sid = "alpha.core:Engine.run#method"
    boil_sid = "alpha.core:boil#function"

    attr_route = routes["gui:job/attr"]
    assert run_sid in attr_route.core_verbs and boil_sid in attr_route.core_verbs
    assert "attr_delegate" in attr_route.seam_rules

    local_route = routes["gui:job/local"]
    assert run_sid in local_route.core_verbs
    assert "local_construct" in local_route.seam_rules

    ship_route = routes["gui:direct/ship"]
    assert run_sid in ship_route.core_verbs
    assert "transport_delegate" in ship_route.seam_rules

    # 플래그 분기의 지역 구성 호출은 유도 시점에 root 로 해석된다(BFS 홉이 아니다).
    flag_route = routes["cli:--fast"]
    assert "alpha.core:Kettle.warm#method" in flag_route.entry.roots
    assert "alpha.core:Kettle.warm#method" in flag_route.core_verbs

    # 음성: builtin 결속(self.mist = dict())은 폐포 클래스가 아니다 — 홉을 지어내지 않고
    # 미해결 out-edge 로 정직하게 남는다.
    fog_route = routes["gui:job/fog"]
    assert fog_route.core_verbs == ()
    assert fog_route.unresolved_out >= 1


def test_common_anchor_and_duplicate_are_separated_by_shared_implementation(
    tmp_path: Path,
) -> None:
    """COMMON 은 fan(1,1) 공유 동사로, DUPLICATE 는 같은 어간의 무공유 구현으로 선다."""
    repo = _mini_repo(tmp_path, {**_FIXTURE_SRC, "tests/test_stub.py": "def test_ok():\n    pass\n"})
    result = build_use_cases(repo)
    assert result.classification["cli:brew"] == "COMMON"
    assert result.classification["gui:job/steep"] == "COMMON"
    assert result.counterpart["cli:brew"] == "gui:job/steep"
    assert result.counterpart["gui:job/steep"] == "cli:brew"
    assert result.anchor_verbs["alpha.core:steep#function"] == ("cli:brew", "gui:job/steep")

    # 같은 어간(mix)·양쪽 다 비어 있지 않은 core 경로·공유 0 → 이름 일치를 근거로
    # 병합하지도(불변식) 조용히 방치하지도 않는다 — DUPLICATE 후보로 시끄럽게 센다.
    assert result.classification["cli:mix"] == "DUPLICATE"
    assert result.classification["gui:job/mix"] == "DUPLICATE"
    assert result.counterpart["cli:mix"] == "gui:job/mix"

    # boil 은 양쪽이 공유하지만 GUI 쪽 fan 이 1 이 아니다 — 이름도 공유도 아닌
    # 「유일 쌍」만 앵커다.
    assert "alpha.core:boil#function" not in result.anchor_verbs
    assert result.classification["cli:default"] == "HOST_ONLY"


def test_oracle_bases_and_characterization_gap(tmp_path: Path) -> None:
    """entry/CORE 근거의 양성과, 근거가 사라졌을 때 gap 이 서는 음성을 함께 센다."""
    tests_files = {
        "tests/test_alpha_actions.py": """
            from alpha.ui.panels import JobPanel


            def _send(panel, action, payload):
                return panel.dispatch(action, payload)


            def test_steep_roundtrip():
                assert _send(JobPanel(), "steep", {}) == {}
        """,
        "tests/test_alpha_core.py": """
            from alpha.core import stir


            def test_stir():
                assert stir() == "stir"
        """,
        "tests/test_alpha_cli.py": """
            from alpha import cli


            def test_brew():
                assert cli.main(["brew"]) == 0


            def test_default_requires_input():
                assert cli.main(["--input", "x"]) == 0
        """,
        "tests/test_alpha_marked.py": """
            import pytest as pt

            pytestmark = pt.mark.zeta


            def test_marked():
                pass
        """,
    }
    repo = _mini_repo(tmp_path, {**_FIXTURE_SRC, **tests_files})
    result = build_use_cases(repo)

    def bases(entry_id: str) -> "set[tuple[str, str]]":
        return {(link.test_path, link.basis) for link in result.oracles[entry_id]}

    # 지역 헬퍼 경유 액션 dispatch 도 호출-인자 리터럴로 문다(실측 결함류의 재현 방지).
    assert ("tests/test_alpha_actions.py", "dispatch-literal") in bases("gui:job/steep")
    assert ("tests/test_alpha_cli.py", "argv-literal") in bases("cli:brew")
    assert ("tests/test_alpha_cli.py", "trunk-flag") in bases("cli:default")
    # core 동사 import 는 모듈-한정으로만 문다 — CORE 수준(간접) 근거.
    assert ("tests/test_alpha_core.py", "core-verb-import") in bases("cli:mix")
    assert result.oracle_status["cli:mix"] == "CORE"
    # 액션 리터럴이 없는 파일은 같은 이름 문자열이 있어도 물지 않는다(음성:
    # test_alpha_core.py 는 "stir" 만 들었고 액션 이름은 안 들었다).
    assert result.oracle_status["gui:pool/drain"] == "NONE"

    gap_ids = {entry_id for entry_id, _ in result.gaps}
    assert "gui:pool/drain" in gap_ids  # 비어 있지 않은 경로 + 근거 없음 → loud
    assert "cli:mix" in gap_ids  # CORE 만 → wrapper 무증인으로 loud

    # 축 표식은 별칭 import 로도 읽힌다.
    marked = next(tf for tf in result.test_files if tf.path == "tests/test_alpha_marked.py")
    assert marked.axes == ("zeta",)


def test_scan_accepts_bom_and_rejects_unparsable_loudly(tmp_path: Path) -> None:
    """BOM 실파일은 통과(실측 회귀), 구문 오류는 조용한 skip 이 아니라 오류다."""
    repo = _mini_repo(tmp_path, {**_FIXTURE_SRC, "tests/test_stub.py": "def test_ok():\n    pass\n"})
    bom_file = repo / "tests/test_bom.py"
    bom_file.write_bytes(b"\xef\xbb\xbf" + "def test_bom():\n    pass\n".encode("utf-8"))
    closure = build_use_cases(repo).graph.closure
    paths = {tf.path for tf in scan_test_files(repo, closure)}
    assert "tests/test_bom.py" in paths

    (repo / "tests/test_broken.py").write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(FactGraphError, match="test_broken"):
        scan_test_files(repo, closure)


def test_oracle_basis_vocabulary_is_locked() -> None:
    with pytest.raises(FactGraphError, match="basis"):
        OracleLink("tests/test_x.py", "vibes")
    assert set(ENTRY_BASES).isdisjoint(CORE_BASES)


# ─────────────────────────────── 실저장소 게이트 ───────────────────────────────


@pytest.fixture(scope="module")
def real_result():
    return build_use_cases(ROOT)


@pytest.fixture(scope="module")
def committed_ledger() -> dict:
    return tomllib.loads((ROOT / LEDGER_REL_PATH).read_text(encoding="utf-8"))


def test_real_committed_ledger_matches_regeneration() -> None:
    assert check(ROOT) == []


def test_real_entry_denominator_has_zero_unclassified(real_result, committed_ledger) -> None:
    """「entry 업무 호출 경로 미분류 0」 — 재유도 분모와 커밋 원장의 좌표 단위 전수 대조."""
    derived = {entry.entry_id for entry in real_result.entries}
    committed_rows = [row["id"] for row in committed_ledger["entry"]]
    assert len(committed_rows) == len(set(committed_rows))  # id 유일성
    assert set(committed_rows) == derived
    for row in committed_ledger["entry"]:
        assert row["classification"] in ("COMMON", "HOST_ONLY", "DUPLICATE")
        assert row["oracle_status"] in ("ENTRY", "CORE", "NONE")


def test_real_packet_baseline_counts_hold(committed_ledger) -> None:
    """#517 DISCOVERY 기준점의 재확인 — 값이 움직이면 조사가 아니라 표면이 움직인 것이다."""
    counts = committed_ledger["counts"]
    assert counts["entries_total"] == 155
    assert counts["entries_cli"] == 8
    assert counts["entries_gui"] == 147
    assert counts["common"] == 6
    assert counts["host_only"] == 149
    assert counts["duplicate"] == 0
    assert counts["entries_cli"] + counts["entries_gui"] == counts["entries_total"]
    assert (
        counts["common"] + counts["host_only"] + counts["duplicate"] == counts["entries_total"]
    )
    assert (
        counts["oracle_entry"] + counts["oracle_core"] + counts["oracle_none"]
        == counts["entries_total"]
    )


def test_real_input_digests_pin_the_02a_call_axis(committed_ledger) -> None:
    """02E 는 02A 의 read-only 소비자다 — 입력 핀이 02A 커밋 원장과 문자 그대로 같다."""
    ledger_02a = tomllib.loads((ROOT / LEDGER_02A_REL_PATH).read_text(encoding="utf-8"))
    assert committed_ledger["inputs"]["base_facts"] == ledger_02a["digests"]["base_facts"]
    assert committed_ledger["inputs"]["graph_facts"] == ledger_02a["digests"]["graph_facts"]


def test_real_anchor_rows_bind_common_pairs_symmetrically(committed_ledger) -> None:
    rows = {row["id"]: row for row in committed_ledger["entry"]}
    anchors = committed_ledger.get("anchor", [])
    assert anchors, "COMMON 판정 근거(anchor)가 원장에 없다"
    for anchor in anchors:
        cli_row, gui_row = rows[anchor["cli_entry"]], rows[anchor["gui_entry"]]
        assert cli_row["classification"] == "COMMON"
        assert gui_row["classification"] == "COMMON"
        assert cli_row["counterpart"] == anchor["gui_entry"]
        assert gui_row["counterpart"] == anchor["cli_entry"]
        assert anchor["verb"] in cli_row["anchor_verbs"]
        assert anchor["verb"] in gui_row["anchor_verbs"]


def test_real_characterization_gaps_are_loud_and_grounded(committed_ledger) -> None:
    rows = {row["id"]: row for row in committed_ledger["entry"]}
    gaps = committed_ledger.get("characterization_gap", [])
    assert gaps, "gap 0 은 실측과 어긋난다 — 스캐너 침묵을 의심하라"
    for gap in gaps:
        row = rows[gap["entry"]]
        assert row["oracle_status"] in ("CORE", "NONE")
        assert row["core_verb_count"] > 0  # 비어 있지 않은 경로만 characterization 대상
        assert gap["reason"]


def test_real_self_row_exists_with_zero_product_refs(committed_ledger) -> None:
    """관측자 순환의 명문화 — 이 게이트 자신이 분모에 있고 제품 참조 0 인 고정점이다."""
    rows = {row["path"]: row for row in committed_ledger["test_file"]}
    assert SELF_REL_PATH in rows
    assert rows[SELF_REL_PATH]["product_modules"] == []
    assert rows[SELF_REL_PATH]["axis"] == "deterministic"
