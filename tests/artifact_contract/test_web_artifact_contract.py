"""독립 fixture로 artifact manifest·tree digest의 fail-closed 경계를 검증한다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from _web_artifact_contract import (
    ArtifactContractViolation,
    verify_test_fixture_artifact,
    write_test_fixture_manifest,
)


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
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_entry = source_root / "main.js"
    source_entry.write_bytes(b"export const boot = () => 'ready';\n")
    (source_root / "app.css").write_bytes(b":root { color-scheme: light dark; }\n")
    lock_path = tmp_path / "dependency.lock"
    lock_path.write_bytes(b'{"lockfileVersion":1,"packages":{}}\n')

    artifact_root = tmp_path / "web"
    assets = artifact_root / "assets"
    assets.mkdir(parents=True)
    built_index = artifact_root / "index.html"
    built_index.write_bytes(
        b'<!doctype html><script type="module" src="./assets/main.js"></script>\n'
    )
    built_entry = assets / "main.js"
    built_entry.write_bytes(b'const boot=()=> "ready";boot();\n')
    (assets / "app.css").write_bytes(b":root{color-scheme:light dark}\n")

    manifest_path = tmp_path / "fixture.json"
    write_test_fixture_manifest(
        artifact_root=artifact_root,
        manifest_path=manifest_path,
        source_root=source_root,
        lock_path=lock_path,
    )
    return ArtifactFixture(
        artifact_root,
        manifest_path,
        source_root,
        source_entry,
        lock_path,
        built_index,
        built_entry,
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


def test_valid_artifact_manifest_covers_the_exact_tree(valid_artifact: ArtifactFixture) -> None:
    verified = _verify(valid_artifact)
    assert verified.files == ("assets/app.css", "assets/main.js", "index.html")
    assert len(verified.artifact_sha256) == 64


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("artifact-missing", "artifact directory missing"),
        ("manifest-missing", "artifact manifest missing"),
        ("index-missing", r"listed artifact file missing: index\.html"),
        ("entry-missing", r"listed artifact file missing: assets/main\.js"),
        ("extra-output", r"extra stale artifact file: assets/stale\.js"),
        ("output-mutated", r"artifact byte digest mismatch: assets/main\.js"),
        ("source-stale", "source input stale"),
        ("lock-stale", "lock input stale"),
    ],
)
def test_artifact_verifier_rejects_incomplete_stale_or_mutated_trees(
    valid_artifact: ArtifactFixture,
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    overrides: dict[str, Path] = {}
    if case == "artifact-missing":
        overrides["artifact_root"] = tmp_path / "missing-web"
    elif case == "manifest-missing":
        overrides["manifest_path"] = tmp_path / "missing.json"
    elif case == "index-missing":
        valid_artifact.built_index.unlink()
    elif case == "entry-missing":
        valid_artifact.built_entry.unlink()
    elif case == "extra-output":
        (valid_artifact.artifact_root / "assets" / "stale.js").write_bytes(b"stale")
    elif case == "output-mutated":
        body = bytearray(valid_artifact.built_entry.read_bytes())
        body[0] ^= 1
        valid_artifact.built_entry.write_bytes(body)
    elif case == "source-stale":
        valid_artifact.source_entry.write_bytes(
            valid_artifact.source_entry.read_bytes() + b"\n"
        )
    elif case == "lock-stale":
        valid_artifact.lock_path.write_bytes(
            valid_artifact.lock_path.read_bytes().replace(b'"lockfileVersion":1', b'"lockfileVersion":2')
        )

    with pytest.raises(ArtifactContractViolation, match=message):
        _verify(valid_artifact, **overrides)
