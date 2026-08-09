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


def test_verdict_is_blocked_with_grounded_backlog(result: A.SynthesisResult) -> None:
    """현재 master 는 소유 결정·oracle 공백이 남아 BLOCKED 다 — 조용한 초록이 아니라 backlog."""
    assert result.verdict == "BLOCKED"
    p_review = [m for m in result.modules if m.target == "P_REVIEW_REQUIRED"]
    assert p_review, "P_REVIEW 가 0 이면 backlog 가 사라진 것 — 판정을 재검토"
    # 판정 사유가 실제 backlog 규모를 재진술한다.
    joined = " ".join(result.verdict_reasons)
    assert str(len(p_review)) in joined


def test_core_job_is_the_effect_hotspot(result: A.SynthesisResult) -> None:
    """core.job 이 다효과 god-module 로 드러난다 — 합성이 실제 경계 문제를 짚는다는 증거."""
    job = next(m for m in result.modules if m.module == "hwpxfiller.core.job")
    assert job.target == "P_REVIEW_REQUIRED"
    assert len(job.effect_classes) >= 3


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
