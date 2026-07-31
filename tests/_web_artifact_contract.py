"""미래 웹 빌드 산출물의 관찰 가능한 계약을 고정하는 테스트 전용 oracle.

이 모듈은 ``tmp_path`` 아래에서만 쓰는 fixture manifest를 만들고 검증한다. 제품 manifest의
파일명·배치·공개 schema, 산출물 locator, runtime resolver는 정의하지 않는다. 그 생산·해석
책임은 N-03의 중앙 seal에 남겨 두고, 여기서는 그 구현이 만족해야 할 결과만 고정한다:

- 산출물 디렉터리와 manifest가 모두 있어야 한다.
- manifest에 적힌 파일 집합과 실제 파일 집합이 정확히 같아야 한다.
- 각 파일의 바이트와 정렬된 전체 집합의 SHA-256이 일치해야 한다.
- canonical source tree와 dependency lock 입력이 seal 시점과 같아야 한다.

제품 코드나 runner가 이 모듈을 import하면 안 된다. 호출자는 모든 경로를 명시적으로 넘기며
저장소의 ``web/``, 미래 ``frontend/`` 또는 ``build/web/`` 경로를 이 모듈이 해석하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TEST_FIXTURE_SCHEMA = 1


class ArtifactContractViolation(RuntimeError):
    """테스트 산출물이 완전성·무결성·입력 신선도 계약을 어겼다."""


@dataclass(frozen=True)
class VerifiedTestArtifact:
    """양성 fixture 검증 결과 — 정렬된 파일 집합과 그 단일 식별자."""

    artifact_sha256: str
    files: tuple[str, ...]


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping_sha256(values: Mapping[str, str]) -> str:
    """경로 정렬을 포함한 mapping 전체의 안정적 SHA-256."""
    payload = json.dumps(
        dict(sorted(values.items())),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_map(root: Path, *, role: str) -> dict[str, str]:
    if not root.is_dir():
        raise ArtifactContractViolation(f"{role} directory missing: {root}")
    return {
        path.relative_to(root).as_posix(): _file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _required_file_sha256(path: Path, *, role: str) -> str:
    if not path.is_file():
        raise ArtifactContractViolation(f"{role} file missing: {path}")
    return _file_sha256(path)


def write_test_fixture_manifest(
    *,
    artifact_root: Path,
    manifest_path: Path,
    source_root: Path,
    lock_path: Path,
) -> None:
    """현재 temp fixture를 봉인한다.

    이것은 N-03 제품 seal producer가 아니다. 계약 테스트가 양성 기준점을 만든 뒤 파일 또는
    입력을 한 가지씩 훼손할 수 있게 하는 fixture 작성기일 뿐이다.
    """
    files = _file_map(artifact_root, role="artifact")
    if not files:
        raise ArtifactContractViolation("artifact directory is empty")
    source_files = _file_map(source_root, role="source input")
    lock_sha256 = _required_file_sha256(lock_path, role="lock input")
    fixture_manifest = {
        "test_fixture_schema": _TEST_FIXTURE_SCHEMA,
        "artifact": {
            "files": files,
            "sha256": _mapping_sha256(files),
        },
        "inputs": {
            "source_tree_sha256": _mapping_sha256(source_files),
            "lock_sha256": lock_sha256,
        },
    }
    manifest_path.write_text(
        json.dumps(fixture_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _string_mapping(value: Any, *, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ArtifactContractViolation(f"fixture manifest field is not an object: {field}")
    if not value or not all(isinstance(key, str) and isinstance(item, str)
                            for key, item in value.items()):
        raise ArtifactContractViolation(f"fixture manifest field is invalid: {field}")
    return dict(value)


def _load_test_fixture_manifest(
    manifest_path: Path,
) -> tuple[dict[str, str], str, str, str]:
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise TypeError("manifest root")
        if document["test_fixture_schema"] != _TEST_FIXTURE_SCHEMA:
            raise ValueError("fixture schema")
        artifact = document["artifact"]
        inputs = document["inputs"]
        if not isinstance(artifact, dict) or not isinstance(inputs, dict):
            raise TypeError("manifest sections")
        files = _string_mapping(artifact["files"], field="artifact.files")
        artifact_sha256 = artifact["sha256"]
        source_sha256 = inputs["source_tree_sha256"]
        lock_sha256 = inputs["lock_sha256"]
        if not all(
            isinstance(digest, str) and len(digest) == 64
            for digest in (artifact_sha256, source_sha256, lock_sha256)
        ):
            raise ValueError("digest")
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise ArtifactContractViolation(
            f"fixture manifest is invalid: {manifest_path}"
        ) from exc
    return files, artifact_sha256, source_sha256, lock_sha256


def verify_test_fixture_artifact(
    *,
    artifact_root: Path,
    manifest_path: Path,
    source_root: Path,
    lock_path: Path,
) -> VerifiedTestArtifact:
    """fixture 산출물의 존재·전수·바이트·입력 신선도를 fail-closed로 검증한다."""
    if not artifact_root.is_dir():
        raise ArtifactContractViolation(f"artifact directory missing: {artifact_root}")
    if not manifest_path.is_file():
        raise ArtifactContractViolation(f"artifact manifest missing: {manifest_path}")

    expected, declared_artifact, declared_source, declared_lock = (
        _load_test_fixture_manifest(manifest_path)
    )
    actual = _file_map(artifact_root, role="artifact")

    missing = sorted(set(expected) - set(actual))
    if missing:
        raise ArtifactContractViolation(
            "listed artifact file missing: " + ", ".join(missing)
        )
    extra = sorted(set(actual) - set(expected))
    if extra:
        raise ArtifactContractViolation(
            "extra stale artifact file: " + ", ".join(extra)
        )
    mutated = sorted(path for path in expected if expected[path] != actual[path])
    if mutated:
        raise ArtifactContractViolation(
            "artifact byte digest mismatch: " + ", ".join(mutated)
        )

    expected_artifact = _mapping_sha256(expected)
    if declared_artifact != expected_artifact:
        raise ArtifactContractViolation("fixture manifest artifact seal is inconsistent")
    actual_artifact = _mapping_sha256(actual)
    if actual_artifact != declared_artifact:
        raise ArtifactContractViolation("artifact seal mismatch")

    actual_source = _mapping_sha256(_file_map(source_root, role="source input"))
    if actual_source != declared_source:
        raise ArtifactContractViolation("source input stale")
    actual_lock = _required_file_sha256(lock_path, role="lock input")
    if actual_lock != declared_lock:
        raise ArtifactContractViolation("lock input stale")

    return VerifiedTestArtifact(
        artifact_sha256=actual_artifact,
        files=tuple(actual),
    )
