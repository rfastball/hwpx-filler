"""P3-01 census 원장(`docs/p3_kernel_census.toml`)의 machine-readable 검증 게이트 (#593).

원장은 **임시 실행 원장**이다 — P3-03~P3-05 가 소비하고, P3-99(#586)에서 원장이 제거되거나
영구 계약으로 승격될 때 이 게이트도 **같은 변경에서** 처분한다(#585 완료 조건 13).

지키는 것: 원장이 (a) 남은 format kernel 모듈을 빠뜨리지 않고
(b) 스키마·disposition 어휘를 지키고 (c) P2 ring 판정(`docs/module_rings.toml`)과 어긋나지
않고 (d) behavior oracle 이 실제로 수집되는 상태.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
CENSUS = ROOT / "docs" / "p3_kernel_census.toml"
RINGS = ROOT / "docs" / "module_rings.toml"

DISPOSITIONS = {
    "FORMAT_KERNEL",
    "PRODUCT_DOMAIN",
    "APPLICATION",
    "EXTERNAL_ADAPTER",
    "HOST",
    "TEMP_SAME_OBJECT_FACADE",
    "REMOVE",
    "BLOCKED_NEEDS_P2_DECISION",
}

#: 스키마는 원장 자신의 선언이 아니라 **여기 고정된 기대**와 대조한다 — 원장과 선언을
#: 함께 지우면 초록이 되는 자기참조 검증을 막는다(코덱스 #595).
EXPECTED_SCHEMA = [
    "id", "current_module", "symbol", "visibility", "consumers", "consumer_kind",
    "product_semantics_awareness", "environment_or_effect", "p2_target_authority",
    "target_canonical_import", "behavior_oracle", "compatibility_evidence", "disposition",
]

#: entry ID 폐포 — census 는 module 단위가 아니라 **cluster 단위**가 정본이다. 모듈 폐포만
#: 세면 FC-08 을 남기고 FC-09(BLOCKED realpath cluster)를 지워도 초록(코덱스 #595).
#: 원장 entry 를 넣고 빼는 변경은 이 목록과 한 변경이어야 한다(module_rings 양방향 전례).
EXPECTED_ENTRY_IDS = {
    *(f"KC-{i:02d}" for i in (1, 2, 7, 8)),
}

#: 제품 의미를 모르는 hwpxcore DOMAIN 만 FORMAT_KERNEL 로 정제한다.
REFINEMENT_BY_PREFIX = {
    "hwpxcore": ("DOMAIN", "FORMAT_KERNEL"),
}

#: #592 이동 전 최소 동작 폐포. 비교 강도도 함께 고정해 byte 계약이 semantic 비교로
#: 조용히 약화되는 것을 막는다. 기존 owner nodeid만 재사용하며 별도 resource 실행은 없다.
BEHAVIOR_ORACLES = {
    "atomic-write-preservation": (
        "byte-exact",
        ("tests/test_atomic.py::test_failed_replace_preserves_existing_and_cleans_tmp",),
    ),
    "deterministic-package-serialization": (
        "byte-exact",
        ("tests/test_package.py::test_roundtrip_preserves_ocf_rules",),
    ),
    "duplicate-unsafe-member": (
        "semantic-equivalent",
        (
            "tests/test_package.py::test_open_rejects_invalid_ocf_contract",
            "tests/test_package.py::test_open_rejects_dangerous_zip_entry_names",
        ),
    ),
    "major-product-generation": (
        "semantic-equivalent",
        ("tests/test_scenario_e2e.py::test_direct_match_batch_fills_bid_notice",),
    ),
    "mimetype-ocf": (
        "semantic-equivalent",
        (
            "tests/test_package.py::test_roundtrip_preserves_ocf_rules",
            "tests/test_package.py::test_compressed_mimetype_is_accepted_then_normalized_to_stored",
        ),
    ),
    "motw-native-platform": (
        "semantic-equivalent",
        (
            "tests/test_motw.py",
            "tests/test_native_positive.py",
            "tests/test_single_instance.py",
            "tests/test_tracking_locate.py::test_reveal_and_open_missing_path_is_loud",
            "tests/test_webapp_bridge.py::test_pick_data_file_corrupt_workbook_returns_error_not_raise",
            "tests/test_webapp_bridge.py::test_win32_filter_block_derives_from_exts_and_is_double_null_terminated",
        ),
    ),
    "package-bytes-parse-validation": (
        "semantic-equivalent",
        (
            "tests/test_package.py::test_open_reads_entries",
            "tests/test_package.py::test_open_rejects_invalid_ocf_contract",
        ),
    ),
    "product-prevalidation": (
        "semantic-equivalent",
        (
            "tests/test_job.py::test_run_request_source_report_flags_missing_source_key",
            "tests/test_job.py::test_run_request_output_report_flags_empty_value",
            "tests/test_cli.py::test_cli_ack_empty_injects_marker",
        ),
    ),
    "text-extraction": (
        "byte-exact",
        ("tests/test_corpus_golden.py::test_golden_matches",),
    ),
    "text-lineseg": (
        "semantic-equivalent",
        ("tests/test_lineseg.py",),
    ),
}
EXPECTED_BEHAVIOR_RISKS = {
    "atomic-write-preservation",
    "deterministic-package-serialization",
    "duplicate-unsafe-member",
    "major-product-generation",
    "mimetype-ocf",
    "motw-native-platform",
    "package-bytes-parse-validation",
    "product-prevalidation",
    "text-extraction",
    "text-lineseg",
}


def _census() -> dict[str, object]:
    return tomllib.loads(CENSUS.read_text(encoding="utf-8"))


def _entries() -> "list[dict[str, object]]":
    return _census()["entry"]  # type: ignore[return-value]


def _governed_modules() -> "set[str]":
    """census 정의역 — hwpxcore의 실재 모듈 전부(__init__ 는 패키지명으로)."""
    out: set[str] = set()
    base_dir, package = ROOT / "src" / "hwpxcore", "hwpxcore"
    for path in base_dir.rglob("*.py"):
        parts = [
            part
            for part in path.relative_to(base_dir).with_suffix("").parts
            if part != "__init__"
        ]
        out.add(".".join([package, *parts]) if parts else package)
    return out


def test_census_schema_and_disposition_vocabulary() -> None:
    document = _census()
    assert document["schema"] == EXPECTED_SCHEMA, "원장 schema 선언이 게이트의 고정 기대와 다릅니다"
    fields = set(EXPECTED_SCHEMA)
    for entry in _entries():
        missing = fields - set(entry)
        assert not missing, f"{entry.get('id')}: 스키마 필드 누락 {sorted(missing)}"
        assert entry["disposition"] in DISPOSITIONS, f"{entry['id']}: 어휘 밖 disposition {entry['disposition']!r}"
        # 이동 대상은 목적지가, 제거·계류는 근거가 계약이다(#593 완료 증거 2).
        if entry["disposition"] in {"REMOVE", "BLOCKED_NEEDS_P2_DECISION"}:
            assert entry["compatibility_evidence"], f"{entry['id']}: 제거·계류 판정에 근거가 없습니다"
        else:
            assert entry["target_canonical_import"], f"{entry['id']}: 이동 대상에 target canonical import 가 없습니다"
        if entry["disposition"] == "BLOCKED_NEEDS_P2_DECISION":
            assert "#" in str(entry["compatibility_evidence"]), (
                f"{entry['id']}: BLOCKED 는 상향 이슈 링크가 있어야 합니다(#593 중단 조건)"
            )


def test_census_covers_kernel_package_completely() -> None:
    """양방향 닫힘 — 등재 모듈이 실재하고, 실재 모듈이 등재된다(#542 「정의역이 열거」 방지)."""
    entries = _entries()
    ids = [str(entry["id"]) for entry in entries]
    assert len(ids) == len(set(ids)), "entry id 중복"
    assert set(ids) == EXPECTED_ENTRY_IDS, (
        f"entry ID 폐포 어긋남 — cluster 를 넣고 빼는 변경은 게이트 목록과 한 변경이어야 "
        f"합니다: {sorted(set(ids) ^ EXPECTED_ENTRY_IDS)}"
    )
    listed = {str(entry["current_module"]) for entry in entries}
    census = _governed_modules()
    assert not listed - census, f"원장이 없는 모듈을 가리킵니다: {sorted(listed - census)}"
    assert not census - listed, (
        f"census 누락 — docs/p3_kernel_census.toml 에 등재하세요: {sorted(census - listed)}"
    )


def test_census_p2_authority_matches_module_rings() -> None:
    """P2 가 이미 결정한 owner 를 P3 가 재분류하지 않는다(#593 판정 규칙)."""
    def allows_refinement(
        recorded: str, disposition: str, product_semantics_awareness: bool
    ) -> bool:
        return (
            (recorded, disposition) == REFINEMENT_BY_PREFIX["hwpxcore"]
            and not product_semantics_awareness
        )

    # KC-06 오분류 회귀 음성 대조: 제품 의미를 아는 Domain은 format kernel로 정제할 수 없다.
    assert not allows_refinement("DOMAIN", "FORMAT_KERNEL", True)

    rings = tomllib.loads(RINGS.read_text(encoding="utf-8"))
    targets = {str(unit["module"]): str(unit["target"]) for unit in rings["unit"]}
    entries = _entries()
    for entry in entries:
        module = str(entry["current_module"])
        recorded = str(entry["p2_target_authority"])
        assert targets.get(module) == recorded, (
            f"{entry['id']}: p2_target_authority {recorded!r} 가 module_rings "
            f"{targets.get(module)!r} 와 다릅니다"
        )
        disposition = str(entry["disposition"])
        if disposition in {"REMOVE", "TEMP_SAME_OBJECT_FACADE", "BLOCKED_NEEDS_P2_DECISION"}:
            continue
        refinement_ok = allows_refinement(
            recorded,
            disposition,
            bool(entry["product_semantics_awareness"]),
        )
        assert disposition == recorded or refinement_ok, (
            f"{entry['id']}: disposition {disposition!r} 이 P2 판정 {recorded!r} 의 "
            "허용 정제가 아닙니다 — 재분류는 #538/#542/#582/#583 상향 대상"
        )


def test_census_behavior_oracles_still_collect() -> None:
    """이동 대상의 oracle 실재 — module_rings 게이트가 이미 수집을 보증하는 nodeid 는 제외."""
    assert set(BEHAVIOR_ORACLES) == EXPECTED_BEHAVIOR_RISKS
    assert {comparison for comparison, _ in BEHAVIOR_ORACLES.values()} == {
        "byte-exact",
        "semantic-equivalent",
    }
    rings = tomllib.loads(RINGS.read_text(encoding="utf-8"))
    already = {str(u["oracle_nodeid"]) for u in rings["unit"] if "oracle_nodeid" in u}
    required = {
        nodeid
        for _, nodeids in BEHAVIOR_ORACLES.values()
        for nodeid in nodeids
    }
    nodeids = sorted(
        (
            {str(e["behavior_oracle"]) for e in _entries() if e["behavior_oracle"]}
            | required
        )
        - already
    )
    if not nodeids:
        return
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--disable-warnings", *nodeids],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
