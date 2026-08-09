"""P1-03 중앙 합성 게이트(#518) — merge 일치·권위 귀속·migration DAG·최종 판정.

두 층으로 선다:

- **판별력 층**: 판정 본문(`_assign_authority`·`_merge_and_contradictions`·`_verdict`·
  `_shared_state_seams`)에 입력을 **실제로 뒤집는** mutation 을 먹여 결과가 빨강으로 도는지
  본다. 규칙의 존재가 아니라 결과를 검사한다([[declaration-lives-result-dies]]).
- **실원장 층**: 커밋된 원장이 재합성과 같은지, 여섯 shard 가 같은 기반 사실 위인지(모순 0),
  85 모듈이 단일 권위로 분류되고 unit 이 중복·공백 없이 피복하는지, 판정이 근거를 가진지.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from factgraph import authority_synthesis as A  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 판별력 층 — 순수 판정 함수의 red-first mutation
# ---------------------------------------------------------------------------


def test_domain_module_touching_concrete_effect_is_flagged() -> None:
    """업무 코어가 concrete 효과를 직접 만지면 조용히 DOMAIN 으로 넘기지 않는다(헌장 금지선)."""
    clean, _ = A._assign_authority(
        "hwpxfiller.core.mapping", ("x",), set(), set(), False, False
    )
    assert clean == "DOMAIN"
    # mutation: fs 효과 하나를 더하면 판정이 P_REVIEW 로 뒤집힌다.
    flagged, reason = A._assign_authority(
        "hwpxfiller.core.mapping", ("x",), {"fs"}, set(), False, False
    )
    assert flagged == "P_REVIEW_REQUIRED"
    assert "fs" in reason


def test_ambient_effect_in_core_needs_port_decision() -> None:
    ambient, reason = A._assign_authority(
        "hwpxfiller.core.fill_ledger", ("x",), {"clock"}, set(), True, False
    )
    assert ambient == "P_REVIEW_REQUIRED"
    assert "clock" in reason


def test_host_ring_absorbs_all_effects() -> None:
    """HOST 외곽 링은 OS·fs 효과 혼재를 P_REVIEW 로 과대flag 하지 않는다."""
    target, _ = A._assign_authority(
        "hwpxfiller.cli", ("x",), {"fs", "stdio"}, set(), False, False
    )
    assert target == "HOST"


def test_transport_surface_placement_discriminates() -> None:
    # 표현 링의 controller → FRONTEND_ADAPTER
    fe, _ = A._assign_authority(
        "hwpxfiller.webapp.screen_editor", ("x",), set(), {"endpoint"}, False, False
    )
    assert fe == "FRONTEND_ADAPTER"
    # transport facade → HOST
    host, _ = A._assign_authority(
        "hwpxfiller.webapp.app", ("x",), set(), {"host_method"}, False, False
    )
    assert host == "HOST"
    # 업무 코어에 transport 가 있으면 → P_REVIEW(표현/업무 분리)
    core, reason = A._assign_authority(
        "hwpxfiller.core.job", ("x",), set(), {"endpoint"}, True, False
    )
    assert core == "P_REVIEW_REQUIRED"
    assert "transport" in reason


def test_transport_ownership_does_not_suppress_effect_evidence() -> None:
    """transport 소유가 concrete/ambient 효과 증거를 조용히 억제하지 않는다(#532 리뷰)."""
    clean, _ = A._assign_authority(
        "hwpxfiller.webapp.screen_x", ("x",), set(), {"endpoint"}, False, False
    )
    assert clean == "FRONTEND_ADAPTER"
    # mutation: 같은 transport 모듈에 fs 효과를 더하면 P_REVIEW 로 뒤집힌다.
    flagged, reason = A._assign_authority(
        "hwpxfiller.webapp.screen_x", ("x",), {"fs", "clock"}, {"endpoint"}, False, False
    )
    assert flagged == "P_REVIEW_REQUIRED"
    assert "transport" in reason


def test_composition_root_in_core_is_flagged() -> None:
    """직접 외부 호출이 없어도 effect-bearing 클래스를 조립하면 adapter root(#532 리뷰)."""
    clean, _ = A._assign_authority(
        "hwpxfiller.data.factory", ("x",), set(), set(), False, False, composes=()
    )
    assert clean == "DOMAIN"
    flagged, reason = A._assign_authority(
        "hwpxfiller.data.factory", ("x",), set(), set(), False, False,
        composes=("hwpxfiller.data.excel:ExcelDataSource#class",),
    )
    assert flagged == "P_REVIEW_REQUIRED"
    assert "조립" in reason


def test_presentation_helper_with_effect_is_flagged() -> None:
    clean, _ = A._assign_authority(
        "hwpxfiller.webapp.screens", ("x",), set(), set(), False, False
    )
    assert clean == "FRONTEND_ADAPTER"
    flagged, _ = A._assign_authority(
        "hwpxfiller.webapp.settings", ("x",), {"registry"}, set(), False, False
    )
    assert flagged == "P_REVIEW_REQUIRED"


def test_native_host_vs_external_adapter_split() -> None:
    host, _ = A._assign_authority(
        "hwpxcore.native.clipboard", ("x",), {"host_native"}, set(), False, False
    )
    assert host == "HOST"
    adapter, _ = A._assign_authority(
        "hwpxcore.native._debug", ("x",), {"fs"}, set(), False, False
    )
    assert adapter == "EXTERNAL_ADAPTER"


def test_merge_detects_shard_base_mismatch() -> None:
    """여섯 shard 가 같은 기반 사실 위가 아니면 조용히 merge 하지 않고 contradiction 을 남긴다."""
    good = _fake_shards()
    problems, _ = A._merge_and_contradictions(
        REPO_ROOT, good, A.ANCHOR_BASE_FACTS, A.ANCHOR_GRAPH_FACTS, "eff"
    )
    assert problems == []
    # mutation: 02B 의 base 핀을 다른 값으로 바꾸면 shard_base_mismatch 가 선다.
    bad = _fake_shards()
    bad["02b"]["input"]["base_facts"] = "deadbeef"
    problems, _ = A._merge_and_contradictions(
        REPO_ROOT, bad, A.ANCHOR_BASE_FACTS, A.ANCHOR_GRAPH_FACTS, "eff"
    )
    kinds = {c.kind for c in problems}
    assert "shard_base_mismatch" in kinds


def test_merge_detects_live_drift_and_effect_mismatch() -> None:
    good = _fake_shards()
    # live 재계측이 앵커와 다르면(=src/ 가 원장보다 앞섬) live_base_drift.
    problems, _ = A._merge_and_contradictions(
        REPO_ROOT, good, "otherbase", A.ANCHOR_GRAPH_FACTS, "eff"
    )
    assert "live_base_drift" in {c.kind for c in problems}
    # 재계측 effect digest 가 02C 핀과 다르면 effect_digest_mismatch.
    problems, _ = A._merge_and_contradictions(
        REPO_ROOT, good, A.ANCHOR_BASE_FACTS, A.ANCHOR_GRAPH_FACTS, "different-effect"
    )
    assert "effect_digest_mismatch" in {c.kind for c in problems}


def test_shared_state_seam_only_crosses_modules() -> None:
    # 한 모듈 안의 공유는 central seam 이 아니다.
    within = {
        "shared_state": [
            {"state": "attr:m.a:C.f", "units": ["m.a", "m.a:C"]},
        ]
    }
    assert A._shared_state_seams(within) == []
    # 모듈 경계를 넘으면 seam.
    across = {
        "shared_state": [
            {"state": "attr:m.a:C.f", "units": ["m.a", "m.b:D"]},
        ]
    }
    seams = A._shared_state_seams(across)
    assert seams == [("attr:m.a:C.f", ("m.a", "m.b"))]


def test_verdict_reflects_blockers() -> None:
    clean = [_unit(unit_id="u1", target="DOMAIN", oracle_status="ENTRY")]
    verdict, _ = A._verdict([], clean, sccs=0, dynamic_open=0)
    assert verdict == "ONE_WAVE_READY"
    # 소유 불명 → BLOCKED
    unknown = [_unit(unit_id="u1", target="P_REVIEW_REQUIRED", oracle_status="ENTRY")]
    assert A._verdict([], unknown, 0, 0)[0] == "BLOCKED"
    # oracle 공백 → BLOCKED
    gap = [_unit(unit_id="u1", target="DOMAIN", oracle_status="NONE")]
    assert A._verdict([], gap, 0, 0)[0] == "BLOCKED"
    # 모순 → BLOCKED
    assert A._verdict([A.Contradiction("k", "d")], clean, 0, 0)[0] == "BLOCKED"
    # central seam 선행만 있으면 ORDERED_WAVES
    ordered = [
        _unit(unit_id="u1", target="DOMAIN", oracle_status="ENTRY", predecessors=("u2",)),
        _unit(unit_id="u2", target="DOMAIN", oracle_status="ENTRY", predecessors=("u1",)),
    ]
    assert A._verdict([], ordered, 0, 0)[0] == "ORDERED_WAVES_READY"
    # SCC(거대 원자 cluster) 존재 → BLOCKED
    assert A._verdict([], clean, sccs=3, dynamic_open=0)[0] == "BLOCKED"
    # 미해결 동적 call edge → BLOCKED(정적 그래프 밖 의존 은닉, #532 리뷰)
    assert A._verdict([], clean, sccs=0, dynamic_open=11)[0] == "BLOCKED"
    # entry-level oracle 공백(unit 집계가 ENTRY 여도) → BLOCKED(#532 리뷰)
    assert A._verdict([], clean, 0, 0, oracle_gaps=("cli:foo",))[0] == "BLOCKED"


def test_state_and_symbol_module_parsing() -> None:
    assert A._state_module("attr:hwpxfiller.core.job:Job.rows") == "hwpxfiller.core.job"
    assert A._state_module("attr:hwpxcore.lineseg:LINESEG_LOCAL") == "hwpxcore.lineseg"
    assert A._module_of_symbol("hwpxfiller.core.job:Job.save#method") == "hwpxfiller.core.job"
    assert A._unit_module("hwpxfiller.webapp:Facade") == "hwpxfiller.webapp"


# ---------------------------------------------------------------------------
# 실원장 층 — 커밋된 합성 결과의 불변식
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def result() -> A.SynthesisResult:
    return A.synthesize(REPO_ROOT)


def test_committed_ledger_matches_regeneration() -> None:
    assert A.check(REPO_ROOT) == []


def test_anchor_matches_pinned_constants(result: A.SynthesisResult) -> None:
    assert result.base_facts == A.ANCHOR_BASE_FACTS
    assert result.graph_facts == A.ANCHOR_GRAPH_FACTS


def test_source_digest_pins_actual_bytes(result: A.SynthesisResult) -> None:
    """facts_digest 가 못 보는 리터럴 편집을 잡는 바이트 digest 가 서 있다(#532 리뷰)."""
    assert len(result.source_digest) == 64
    assert all(c in "0123456789abcdef" for c in result.source_digest)
    # 재계산이 결정론적이다(같은 소스 → 같은 digest).
    assert A.synthesize(REPO_ROOT).source_digest == result.source_digest


def test_merge_consistency_zero_contradictions(result: A.SynthesisResult) -> None:
    """여섯 shard 가 같은 기반 사실 위 — merge 가 조용히 갈리지 않았다는 증거."""
    assert result.contradictions == ()


def test_every_module_assigned_single_authority(result: A.SynthesisResult) -> None:
    modules = [m.module for m in result.modules]
    assert len(modules) == len(set(modules))  # 이중 권위 없음
    for m in result.modules:
        assert m.target in A.AUTHORITIES  # 미분류 0


def test_units_cover_all_modules_without_overlap(result: A.SynthesisResult) -> None:
    inv_mods = {m.module for m in result.modules}
    slots = [mod for u in result.units for mod in u.modules]
    assert len(slots) == len(set(slots))  # 중복 0
    assert set(slots) == inv_mods  # 공백·잉여 0


def test_every_unit_has_compat_seam_and_removal(result: A.SynthesisResult) -> None:
    for u in result.units:
        assert u.compat_seam
        assert u.removal_condition
        assert u.closure_digest


def test_verdict_is_one_wave_ready_without_hidden_backlog(result: A.SynthesisResult) -> None:
    """사람 판정·실재 oracle·R handoff·패킷 공백을 모두 닫아 한 wave로 실행 가능하다."""
    assert result.verdict == "ONE_WAVE_READY"
    p_review = [m for m in result.modules if m.target == "P_REVIEW_REQUIRED"]
    assert p_review == []
    assert result.oracle_gaps == ()
    assert result.oracle_pointer_gaps == ()
    assert result.packet_gaps == ()
    assert result.source_write_overlaps == ()
    assert result.r_handoff_gaps == ()


def test_core_job_is_the_effect_hotspot(result: A.SynthesisResult) -> None:
    """core.job의 Domain 귀속이 효과를 숨기지 않고 P2 port 추출 의무로 이어진다."""
    job = next(m for m in result.modules if m.module == "hwpxfiller.core.job")
    assert job.target == "DOMAIN"
    assert len(job.effect_classes) >= 3
    unit = next(u for u in result.units if job.module in u.modules)
    assert {f"port:{kind}" for kind in job.effect_classes} <= set(
        unit.required_effect_contracts
    )
    assert unit.extraction_obligations


# ---------------------------------------------------------------------------
# 테스트 헬퍼
# ---------------------------------------------------------------------------


def _fake_shards() -> "dict[str, dict]":
    """여섯 shard 가 모두 앵커에 일치하는 최소 골격(merge 판정 함수 입력용)."""
    base = A.ANCHOR_BASE_FACTS
    graph = A.ANCHOR_GRAPH_FACTS
    return {
        "01": {"module": []},
        "02a": {"digests": {"base_facts": base, "graph_facts": graph}},
        "02b": {"input": {"base_facts": base, "graph_facts": graph}},
        "02c": {"digests": {"base_facts": base, "graph_facts": graph, "effect_facts": "eff"}},
        "02d": {"digests": {"base_facts_02a": base}},
        "02e": {"inputs": {"base_facts": base, "graph_facts": graph}},
    }


def _unit(**over: object) -> A.MigrationUnit:
    defaults: "dict[str, object]" = dict(
        unit_id="u",
        target="DOMAIN",
        modules=("m",),
        symbol_count=1,
        purpose="p",
        current_responsibilities=("public-symbols:1",),
        source_symbols=("m:f#function",),
        closure_digest="d",
        source_write_set=("src/m.py",),
        read_only_adjacent=(),
        write_set=(),
        state_reads=(),
        transaction_clusters=(),
        effect_edges=(),
        persistence_edges=(),
        transport_edges=(),
        target_inputs=(),
        target_outputs=("m:f#function",),
        required_effect_contracts=(),
        extraction_obligations=(),
        shared_with=(),
        oracle_status="ENTRY",
        oracle_entries=("tests/test_x.py::test_x",),
        positive_gates=("tests/test_x.py::test_x",),
        negative_gates=("tests/test_authority_gate_04.py::mutation",),
        predecessors=(),
        successors=(),
        compat_seam="c",
        removal_condition="r",
        rollback_condition="rb",
        stop_condition="s",
        blocking=(),
    )
    defaults.update(over)
    return A.MigrationUnit(**defaults)  # type: ignore[arg-type]
