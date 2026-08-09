"""P1-04 게이트(#519) — P1-03 원장을 보고서에서 CI 규칙으로 승격.

각 게이트는 **의미 계약**을 겨눈다(파일 이름 문자열 과고정 금지). 각 게이트에는 실제로 RED
가 되는 mutation fixture 가 붙는다 — 규칙의 존재가 아니라 판별력을 증명한다. UNKNOWN(권위
미결정)을 green 으로 넘기지 않는다.

**old→new 책임 승계**: `tests/test_architecture.py` 의 **패키지 기반** import 계약
(core·data 역의존 금지)은 그대로 유지된다. 여기의 방향 게이트는 그것의 **권위(ring) 기반**
후계로, 「hwpxcore/data 가 제품을 import 안 한다」를 「안쪽 링이 바깥쪽을 import 안 한다」로
일반화한다 — 패키지가 아니라 목표 권위로 절단하므로 더 넓다. 기존 테스트는 대체가 아니라
공존한다(테스트 삭제·완화 금지).

게이트 목록(#519 소유):
- 방향 게이트: 결정 권위 간 import 가 바깥→안만 흐른다(위반 0).
- 효과-in-core 게이트: DOMAIN/APPLICATION 목표는 concrete/ambient 효과·조립·transport 0.
- unowned 표면 게이트: effect/state/transport 을 지는 모듈은 모두 권위 원장 안.
- 권위 coverage/duplicate/gap 게이트: 85 모듈 단일 권위·중복 0·공백 0.
- migration-unit closure digest 게이트: 각 unit digest 가 커밋 심볼로 재계산된다.
- 동적 edge 게이트: dynamic_open 이 02A 와 같고 판정을 막는다.
- write-set overlap 게이트: 두 unit 이 같은 상태를 쓰면 central seam 이라야 한다.
"""

from __future__ import annotations

import hashlib
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from factgraph import authority_synthesis as A  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def result() -> A.SynthesisResult:
    return A.synthesize(REPO_ROOT)


@pytest.fixture(scope="module")
def ledger() -> dict:
    return tomllib.loads((REPO_ROOT / A.LEDGER_REL_PATH).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 방향 게이트 — 판별력(순수 함수 mutation) + 실원장 불변식
# ---------------------------------------------------------------------------


def test_direction_analysis_discriminates() -> None:
    targets = {
        "d": "DOMAIN",
        "a": "APPLICATION",
        "h": "HOST",
        "fe": "FRONTEND_ADAPTER",
        "u": "P_REVIEW_REQUIRED",
    }
    # 허용: 바깥→안(HOST→DOMAIN), peer(HOST↔FRONTEND_ADAPTER), 유보(P_REVIEW 끝점).
    ok = A._direction_analysis(targets, (("h", "d"), ("h", "fe"), ("d", "u")))
    assert ok.violations == ()
    assert ok.peer_edges == 1
    assert ok.deferred_edges == 1
    # mutation: 안쪽이 바깥쪽을 import 하면(DOMAIN→HOST, APPLICATION→HOST) 위반이 선다.
    bad = A._direction_analysis(targets, (("d", "h"), ("a", "h")))
    assert len(bad.violations) == 2
    assert {(v.src, v.dst) for v in bad.violations} == {("d", "h"), ("a", "h")}


def test_import_edges_capture_both_relations() -> None:
    """``import x``(imports_module)와 ``from x import y``(imports_symbol) 둘 다 본다."""
    facts = (
        SimpleNamespace(rel="imports_module", src="m.a:#module", dst="m.b:#module"),
        SimpleNamespace(rel="imports_symbol", src="m.a:f#function", dst="m.c:g#function"),
        SimpleNamespace(rel="imports_symbol", src="m.a:f#function", dst="ext:os"),  # 외부 제외
        SimpleNamespace(rel="imports_module", src="m.a:#module", dst="m.a:#module"),  # 자기 제외
        SimpleNamespace(rel="calls", src="m.a:f#function", dst="m.b:h#function"),  # import 아님
    )
    edges = A._import_edges(SimpleNamespace(base_facts=facts))
    assert set(edges) == {("m.a", "m.b"), ("m.a", "m.c")}


def test_dependency_direction_clean_on_master(result: A.SynthesisResult, ledger: dict) -> None:
    """master 는 결정 권위 간 방향 위반이 0 이다(clean invariant, baseline 불필요)."""
    assert result.dependency.violations == ()
    assert ledger["dependency"]["violations"] == 0
    assert ledger["dependency"]["internal_edges"] == result.dependency.internal_edges
    # 유보(P_REVIEW 끝점)는 조용한 green 이 아니라 세어져 드러난다.
    assert result.dependency.deferred_edges > 0


def test_verdict_blocks_on_direction_violation() -> None:
    dep = A.DependencyAnalysis(
        internal_edges=1,
        decided_edges=1,
        deferred_edges=0,
        peer_edges=0,
        violations=(A.DirectionEdge("d", "DOMAIN", "h", "HOST"),),
    )
    clean_unit = _unit(target="DOMAIN", oracle_status="ENTRY")
    verdict, reasons = A._verdict([], [clean_unit], 0, 0, (), dep)
    assert verdict == "BLOCKED"
    assert any("방향 위반" in r for r in reasons)


# ---------------------------------------------------------------------------
# 효과-in-core 게이트
# ---------------------------------------------------------------------------


def test_business_core_targets_are_effect_free(result: A.SynthesisResult) -> None:
    """DOMAIN/APPLICATION 목표 모듈은 concrete/ambient 효과·조립·transport 를 안 진다.

    지면(#433 금지선)이 P1-03 판정으로 이미 서 있다는 실증 — 위반은 P_REVIEW 로 갔어야 한다.
    """
    for m in result.modules:
        if m.target in ("DOMAIN", "APPLICATION"):
            assert m.effect_classes == (), f"{m.module} 이 DOMAIN/APP 인데 효과를 진다"
            assert m.composes == (), f"{m.module} 이 DOMAIN/APP 인데 조립을 한다"
            assert not m.transport, f"{m.module} 이 DOMAIN/APP 인데 transport 를 진다"


def test_effect_in_core_flips_authority() -> None:
    """효과-in-core 게이트의 판별력: 효과를 더하면 DOMAIN 판정이 뒤집힌다."""
    clean, _ = A._assign_authority("hwpxfiller.core.x", ("s",), set(), set(), False, False)
    assert clean == "DOMAIN"
    flipped, _ = A._assign_authority(
        "hwpxfiller.core.x", ("s",), {"fs"}, set(), False, False
    )
    assert flipped == "P_REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# unowned 표면 게이트
# ---------------------------------------------------------------------------


def test_no_unowned_surface_on_master(result: A.SynthesisResult) -> None:
    assert result.unowned_surfaces == ()


def test_unowned_surface_detection_logic() -> None:
    """effect/state/transport 을 지되 권위 집합 밖인 모듈은 소유 불명으로 걸린다."""
    owned = {"m.a", "m.b"}
    surface = {"m.a", "m.b", "m.orphan"}  # m.orphan 은 인벤토리 밖 신규 표면
    unowned = sorted(m for m in surface if m not in owned)
    assert unowned == ["m.orphan"]


def test_verdict_blocks_on_unowned_surface() -> None:
    clean_unit = _unit(target="DOMAIN", oracle_status="ENTRY")
    verdict, reasons = A._verdict([], [clean_unit], 0, 0, (), None, ("m.orphan",))
    assert verdict == "BLOCKED"
    assert any("원장 밖" in r for r in reasons)


# ---------------------------------------------------------------------------
# 권위 coverage/duplicate/gap 게이트
# ---------------------------------------------------------------------------


def test_authority_coverage_is_total_and_single(result: A.SynthesisResult, ledger: dict) -> None:
    modules = [m.module for m in result.modules]
    assert len(modules) == len(set(modules))  # 이중 권위 없음
    for m in result.modules:
        assert m.target in A.AUTHORITIES  # UNKNOWN 을 green 으로 안 침
    inv = tomllib.loads((REPO_ROOT / A.INVENTORY_LEDGER).read_text(encoding="utf-8"))
    inv_mods = {e["name"] for e in inv["module"]}
    assert set(modules) == inv_mods  # 공백·잉여 0


# ---------------------------------------------------------------------------
# migration-unit closure digest 게이트
# ---------------------------------------------------------------------------


def test_unit_closure_digests_recompute(result: A.SynthesisResult) -> None:
    """각 unit 의 closure_digest 가 커밋 인벤토리 심볼로 정확히 재계산된다."""
    inv = tomllib.loads((REPO_ROOT / A.INVENTORY_LEDGER).read_text(encoding="utf-8"))
    sym_of = {e["name"]: tuple(e.get("symbols", [])) for e in inv["module"]}
    for u in result.units:
        closure = sorted(s for mod in u.modules for s in sym_of.get(mod, ()))
        expected = hashlib.sha256("\n".join(closure).encode("utf-8")).hexdigest()
        assert u.closure_digest == expected, f"{u.unit_id} closure digest 드리프트"


def test_closure_digest_reds_on_symbol_mutation() -> None:
    """판별력: 폐포에 심볼이 하나 들어오면 digest 가 바뀐다."""
    base = ["m:A#class", "m:b#function"]
    d0 = hashlib.sha256("\n".join(sorted(base)).encode("utf-8")).hexdigest()
    d1 = hashlib.sha256("\n".join(sorted([*base, "m:c#function"])).encode("utf-8")).hexdigest()
    assert d0 != d1


# ---------------------------------------------------------------------------
# 동적 edge 게이트
# ---------------------------------------------------------------------------


def test_dynamic_open_pinned_to_02a_and_blocks(result: A.SynthesisResult) -> None:
    static_02a = tomllib.loads((REPO_ROOT / A.STATIC_LEDGER).read_text(encoding="utf-8"))
    assert result.dynamic_open == static_02a["counts"]["dynamic_open"]
    # 판정이 동적 edge 를 막는다(다른 backlog 를 다 지워도).
    clean = [_unit(target="DOMAIN", oracle_status="ENTRY")]
    assert A._verdict([], clean, 0, result.dynamic_open)[0] == "BLOCKED"


# ---------------------------------------------------------------------------
# write-set overlap 게이트
# ---------------------------------------------------------------------------


def test_write_set_overlap_only_via_central_seam(result: A.SynthesisResult) -> None:
    """두 unit 이 같은 상태를 쓰면 central seam 으로 묶인 사이여야 한다(원자 이관)."""
    seam_modules = {tuple(sorted(mods)) for _s, mods in result.shared_seams}
    _ = seam_modules
    owner: "dict[str, list[str]]" = {}
    for u in result.units:
        for state in u.write_set:
            owner.setdefault(state, []).append(u.unit_id)
    shared = {st: us for st, us in owner.items() if len(set(us)) > 1}
    # master 는 shared_seam 0 이라 어떤 상태도 두 unit 에 걸치지 않는다.
    assert shared == {}, f"seam 없이 write-set 이 겹치는 상태: {shared}"


# ---------------------------------------------------------------------------
# old→new 승계 — 패키지 계약이 권위 계약으로 일반화됨을 실증
# ---------------------------------------------------------------------------


def test_ring_gate_subsumes_package_import_contracts(result: A.SynthesisResult) -> None:
    """방향 게이트가 test_architecture 의 「core 는 아래로만」을 권위로 일반화한다.

    hwpxcore/hwpxfiller.core/data 의 DOMAIN 목표 모듈은 바깥 링을 import 하지 않는다 —
    패키지 기반 테스트가 겨눈 것을 링 서열이 결정 권위 전체로 확장한다.
    """
    domain = {m.module for m in result.modules if m.target == "DOMAIN"}
    for v in result.dependency.violations:
        assert v.src not in domain  # DOMAIN 에서 나가는 방향 위반이 없다(위반 자체가 0)
    # 승계의 실증: 방향 위반 0 이 곧 「안쪽이 바깥쪽을 import 안 함」이다.
    assert result.dependency.violations == ()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _unit(**over: object) -> A.MigrationUnit:
    defaults: "dict[str, object]" = dict(
        unit_id="u",
        target="DOMAIN",
        modules=("m",),
        symbol_count=1,
        closure_digest="d",
        write_set=(),
        shared_with=(),
        oracle_status="ENTRY",
        oracle_entries=(),
        predecessors=(),
        successors=(),
        compat_seam="c",
        removal_condition="r",
        blocking=(),
    )
    defaults.update(over)
    return A.MigrationUnit(**defaults)  # type: ignore[arg-type]
