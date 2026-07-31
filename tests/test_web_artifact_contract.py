"""N-02 P1: 미래 built web artifact의 테스트 전용 양성·음성 계약.

실제 제품 경로에는 연결하지 않는다. 모든 산출물·source·lock·manifest는 ``tmp_path`` 아래에
만들며 N-03의 중앙 producer/resolver가 생기기 전까지 독립적인 준비 게이트로만 존재한다.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

from _web_artifact_contract import (
    ArtifactContractViolation,
    verify_test_fixture_artifact,
    write_test_fixture_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ArtifactFixture:
    artifact_root: Path
    manifest_path: Path
    source_root: Path
    source_entry: Path
    lock_path: Path
    built_index: Path
    built_entry: Path


@pytest.fixture
def valid_artifact(tmp_path: Path) -> ArtifactFixture:
    source_root = tmp_path / "canonical-source"
    source_root.mkdir()
    source_entry = source_root / "main.js"
    source_entry.write_bytes(b"export const boot = () => 'ready';\n")
    (source_root / "app.css").write_bytes(b":root { color-scheme: light dark; }\n")

    lock_path = tmp_path / "dependency.lock"
    lock_path.write_bytes(b'{"lockfileVersion":1,"packages":{}}\n')

    artifact_root = tmp_path / "built-web"
    assets = artifact_root / "assets"
    assets.mkdir(parents=True)
    built_index = artifact_root / "index.html"
    built_index.write_bytes(
        b'<!doctype html><script type="module" src="./assets/main.js"></script>\n'
    )
    built_entry = assets / "main.js"
    built_entry.write_bytes(b"const boot=()=>\"ready\";boot();\n")
    (assets / "app.css").write_bytes(b":root{color-scheme:light dark}\n")

    manifest_path = tmp_path / "artifact-contract.fixture.json"
    write_test_fixture_manifest(
        artifact_root=artifact_root,
        manifest_path=manifest_path,
        source_root=source_root,
        lock_path=lock_path,
    )
    return ArtifactFixture(
        artifact_root=artifact_root,
        manifest_path=manifest_path,
        source_root=source_root,
        source_entry=source_entry,
        lock_path=lock_path,
        built_index=built_index,
        built_entry=built_entry,
    )


def _verify(fixture: ArtifactFixture, **overrides: Path):
    paths = {
        "artifact_root": fixture.artifact_root,
        "manifest_path": fixture.manifest_path,
        "source_root": fixture.source_root,
        "lock_path": fixture.lock_path,
    }
    paths.update(overrides)
    return verify_test_fixture_artifact(**paths)


def test_valid_fixture_web_artifact_is_accepted(valid_artifact: ArtifactFixture) -> None:
    verified = _verify(valid_artifact)

    assert verified.files == ("assets/app.css", "assets/main.js", "index.html")
    assert len(verified.artifact_sha256) == 64


def test_artifact_directory_missing_is_loud(
    valid_artifact: ArtifactFixture,
    tmp_path: Path,
) -> None:
    with pytest.raises(ArtifactContractViolation, match="artifact directory missing"):
        _verify(valid_artifact, artifact_root=tmp_path / "build-did-not-run")


def test_artifact_manifest_missing_is_loud(
    valid_artifact: ArtifactFixture,
    tmp_path: Path,
) -> None:
    with pytest.raises(ArtifactContractViolation, match="artifact manifest missing"):
        _verify(valid_artifact, manifest_path=tmp_path / "manifest-was-not-produced.json")


def test_listed_artifact_entry_missing_is_loud(valid_artifact: ArtifactFixture) -> None:
    valid_artifact.built_index.unlink()

    with pytest.raises(
        ArtifactContractViolation,
        match=r"listed artifact file missing: index\.html",
    ):
        _verify(valid_artifact)


def test_listed_artifact_file_missing_is_loud(valid_artifact: ArtifactFixture) -> None:
    valid_artifact.built_entry.unlink()

    with pytest.raises(
        ArtifactContractViolation,
        match=r"listed artifact file missing: assets/main\.js",
    ):
        _verify(valid_artifact)


def test_extra_stale_artifact_file_is_loud(valid_artifact: ArtifactFixture) -> None:
    stale = valid_artifact.artifact_root / "assets" / "stale-old-chunk.js"
    stale.write_bytes(b"stale")

    with pytest.raises(
        ArtifactContractViolation,
        match=r"extra stale artifact file: assets/stale-old-chunk\.js",
    ):
        _verify(valid_artifact)


def test_one_byte_artifact_mutation_is_loud(valid_artifact: ArtifactFixture) -> None:
    before = valid_artifact.built_entry.read_bytes()
    after = bytearray(before)
    after[0] ^= 1
    valid_artifact.built_entry.write_bytes(after)
    assert len(after) == len(before)
    assert sum(left != right for left, right in zip(before, after, strict=True)) == 1

    with pytest.raises(
        ArtifactContractViolation,
        match=r"artifact byte digest mismatch: assets/main\.js",
    ):
        _verify(valid_artifact)


def test_source_input_stale_is_loud(valid_artifact: ArtifactFixture) -> None:
    valid_artifact.source_entry.write_bytes(
        valid_artifact.source_entry.read_bytes() + b"\n"
    )

    with pytest.raises(ArtifactContractViolation, match="source input stale"):
        _verify(valid_artifact)


def test_lock_input_stale_is_loud(valid_artifact: ArtifactFixture) -> None:
    before = valid_artifact.lock_path.read_bytes()
    after = before.replace(b'"lockfileVersion":1', b'"lockfileVersion":2')
    assert len(after) == len(before) and after != before
    valid_artifact.lock_path.write_bytes(after)

    with pytest.raises(ArtifactContractViolation, match="lock input stale"):
        _verify(valid_artifact)


@dataclass(frozen=True)
class LegacyCallsiteEvidence:
    path: Path
    function: str
    asserted_exists_variables: tuple[str | None, ...] = ()
    assigned_exists_names: tuple[str, ...] = ()
    return_gate_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResponsibilityTrace:
    legacy: str
    successor: str
    legacy_callsites: tuple[LegacyCallsiteEvidence, ...]
    package_successor: PackageSealConsumerEvidence
    successor_test_path: Path
    successor_tests: tuple[str, ...]


@dataclass(frozen=True)
class PackageSealConsumerEvidence:
    path: Path
    function: str
    artifact_variable: str
    resolver: str
    consumed_attributes: tuple[str, ...]


_LEGACY_RESPONSIBILITY = "index-exists/assets-present/package-selfcheck"
_SUCCESSOR_RESPONSIBILITY = "sorted-full-artifact-file-set-and-seal"
_N02_FIXTURE_TESTS = (
    "test_valid_fixture_web_artifact_is_accepted",
    "test_listed_artifact_entry_missing_is_loud",
    "test_listed_artifact_file_missing_is_loud",
    "test_extra_stale_artifact_file_is_loud",
    "test_one_byte_artifact_mutation_is_loud",
)
_SUCCESSOR_TESTS = (
    "test_producer_writes_complete_stable_self_excluding_seal",
    "test_source_and_frozen_resolvers_return_same_artifact_identity",
    "test_frozen_resolver_never_uses_git_or_build_toolchain",
    "test_resolver_requires_exactly_one_runtime_mode",
    "test_artifact_directory_missing_is_loud",
    "test_artifact_seal_missing_is_loud",
    "test_multiple_artifact_seals_are_loud",
    "test_vite_manifest_missing_is_loud",
    "test_listed_output_missing_is_loud",
    "test_extra_stale_output_is_loud",
    "test_one_byte_output_mutation_is_loud",
    "test_frontend_source_stale_is_loud",
    "test_vite_config_stale_is_loud",
    "test_package_lock_stale_is_loud",
    "test_wrong_source_commit_is_loud",
    "test_wrong_declared_source_input_digest_is_loud",
    "test_wrong_artifact_id_is_loud",
    "test_source_resolver_rejects_sealed_toolchain_different_from_current_pins",
    "test_producer_rejects_forbidden_runtime_reference",
    "test_empty_vite_manifest_is_loud",
    "test_producer_records_versions_measured_from_actual_commands",
    "test_producer_rejects_actual_toolchain_different_from_pins",
    "test_producer_rejects_non_exact_vite_declaration",
    "test_producer_refuses_dirty_source_inputs",
)
_SUCCESSOR_TEST_PATH = ROOT / "tests" / "test_web_artifact_seal.py"

_RESPONSIBILITY_TRACE = (
    ResponsibilityTrace(
        legacy=_LEGACY_RESPONSIBILITY,
        successor=_SUCCESSOR_RESPONSIBILITY,
        legacy_callsites=(
            LegacyCallsiteEvidence(
                ROOT / "tests" / "test_web_dom_contract.py",
                "test_web_index_exists",
                asserted_exists_variables=(None,),
            ),
            LegacyCallsiteEvidence(
                ROOT / "tests" / "test_webapp_bridge.py",
                "test_web_assets_present_and_wired",
                asserted_exists_variables=("rel", "name"),
            ),
        ),
        package_successor=PackageSealConsumerEvidence(
            ROOT / "packaging" / "hwpx_filler_web_entry.py",
            "_selfcheck",
            artifact_variable="artifact",
            resolver="web_artifact",
            consumed_attributes=("artifact_id", "tree_sha256"),
        ),
        successor_test_path=_SUCCESSOR_TEST_PATH,
        successor_tests=_SUCCESSOR_TESTS,
    ),
)


def _is_exists_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exists"
    )


def _function_node(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    functions = [
        node
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(functions) == 1, f"old 책임 함수가 없거나 중복입니다: {name}"
    return functions[0]


def _asserts_exists_for(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    variable: str | None,
) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Assert):
            continue
        if not any(_is_exists_call(item) for item in ast.walk(node.test)):
            continue
        if variable is None or any(
            isinstance(item, ast.Name) and item.id == variable
            for item in ast.walk(node.test)
        ):
            return True
    return False


def _assigns_exists_to(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        assigns_name = any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        )
        if assigns_name and any(_is_exists_call(item) for item in ast.walk(node.value)):
            return True
    return False


def _return_mentions(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
) -> bool:
    return any(
        isinstance(node, ast.Return)
        and node.value is not None
        and any(
            isinstance(item, ast.Name) and item.id == name
            for item in ast.walk(node.value)
        )
        for node in ast.walk(function)
    )


def _assigns_call_to(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    variable: str,
    callable_name: str,
) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        value = node.value
        assigns_variable = any(
            isinstance(target, ast.Name) and target.id == variable
            for target in targets
        )
        calls_resolver = (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == callable_name
        )
        if assigns_variable and calls_resolver:
            return True
    return False


def _uses_attribute(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    variable: str,
    attribute: str,
) -> bool:
    return any(
        isinstance(node, ast.Attribute)
        and node.attr == attribute
        and isinstance(node.value, ast.Name)
        and node.value.id == variable
        for node in ast.walk(function)
    )


def _assert_package_seal_successor(evidence: PackageSealConsumerEvidence) -> None:
    source = evidence.path.read_text(encoding="utf-8")
    function = _function_node(source, evidence.function)

    assert not _assigns_exists_to(function, "web_ok"), (
        "패키지 selfcheck가 index 존재 검사로 되돌아갔습니다 — full seal resolver를 "
        f"통과해야 합니다: {evidence.path}"
    )
    assert _assigns_call_to(
        function,
        variable=evidence.artifact_variable,
        callable_name=evidence.resolver,
    ), (
        "패키지 selfcheck가 중앙 web artifact resolver 결과를 받지 않습니다: "
        f"{evidence.path}:{evidence.function}"
    )
    for attribute in evidence.consumed_attributes:
        assert _uses_attribute(
            function,
            variable=evidence.artifact_variable,
            attribute=attribute,
        ), (
            "패키지 selfcheck가 seal identity를 소비하지 않습니다: "
            f"{evidence.artifact_variable}.{attribute}"
        )


def _test_function_names(path: Path) -> set[str]:
    assert path.exists(), f"N-03 full-seal successor test module이 없습니다: {path}"
    return {
        node.name
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def _assert_legacy_callsite(
    callsite: LegacyCallsiteEvidence,
    *,
    source: str | None = None,
) -> None:
    source = source if source is not None else callsite.path.read_text(encoding="utf-8")
    function = _function_node(source, callsite.function)
    for variable in callsite.asserted_exists_variables:
        assert _asserts_exists_for(function, variable), (
            f"old 존재 assertion 책임이 사라졌습니다: {callsite.path}: "
            f"{callsite.function}({variable})"
        )
    for name in callsite.assigned_exists_names:
        assert _assigns_exists_to(function, name), (
            f"old selfcheck 존재 판정이 사라졌습니다: {callsite.path}: {name}"
        )
    for name in callsite.return_gate_names:
        assert _return_mentions(function, name), (
            f"old selfcheck 결과 게이트가 사라졌습니다: {callsite.path}: {name}"
        )


def test_old_to_new_responsibility_trace_has_unit_cardinality() -> None:
    """기존 존재 검사 묶음 하나가 전수+seal 후계 책임 하나로 정확히 이어진다."""
    legacy_counts = Counter(edge.legacy for edge in _RESPONSIBILITY_TRACE)
    successor_counts = Counter(edge.successor for edge in _RESPONSIBILITY_TRACE)

    assert legacy_counts == Counter({_LEGACY_RESPONSIBILITY: 1})
    assert successor_counts == Counter({_SUCCESSOR_RESPONSIBILITY: 1})

    (edge,) = _RESPONSIBILITY_TRACE
    assert edge.successor_tests == _SUCCESSOR_TESTS
    assert len(edge.successor_tests) == len(set(edge.successor_tests))
    for predecessor_test in _N02_FIXTURE_TESTS:
        assert callable(globals().get(predecessor_test)), (
            f"N-02 fixture contract gate가 사라졌습니다: {predecessor_test}"
        )

    successor_functions = _test_function_names(edge.successor_test_path)
    for successor_test in edge.successor_tests:
        assert successor_test in successor_functions, (
            f"N-03 full-seal 후계 게이트가 없습니다: {successor_test}"
        )
    for callsite in edge.legacy_callsites:
        _assert_legacy_callsite(callsite)
    _assert_package_seal_successor(edge.package_successor)
