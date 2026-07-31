"""Vite 웹 산출물의 단일 seal과 fail-closed runtime resolver.

Source checkout의 제품 런타임은 ``frontend/``를 직접 읽지 않는다. 이 모듈은
``build/web/``의 seal과 전체 파일 트리를 검증하고, seal 시점의 frontend/build 입력이
현재 checkout과 같은지도 확인한다. Frozen 런타임은 PyInstaller가 번들한 ``web/`` 트리만
검증하며 Git, Node, npm 또는 frontend source를 찾지 않는다.

Seal 파일 자체는 자기 참조를 피하려고 output tree digest에서 제외한다. 그 파일 하나만
제외하며, Vite manifest를 포함한 나머지 파일은 전부 정렬된 path/size/SHA-256 레코드로
봉인한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

SEAL_SCHEMA = 1
SEAL_FILENAME = "web-artifact-seal.json"
VITE_MANIFEST_PATH = ".vite/manifest.json"

_SOURCE_CONFIG_PATHS = (
    ".node-version",
    ".npmrc",
    "package.json",
    "package-lock.json",
    "vite.config.mjs",
)
_TEXT_OUTPUT_SUFFIXES = {
    ".cjs",
    ".css",
    ".htm",
    ".html",
    ".js",
    ".json",
    ".map",
    ".mjs",
}
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SEMVER_IN_OUTPUT_RE = re.compile(r"(?<![\d.])v?(\d+\.\d+\.\d+)(?![\d.])")
_ABSOLUTE_ASSET_RE = re.compile(
    r"""(?ix)
    (?:
        ["'`(=:\s]
        |
        url\(\s*
    )
    /assets
    (?:
        /
        |
        (?=["'`)\s?#])
    )
    """
)
_FILE_URL_RE = re.compile(r"(?i)\bfile:(?://)?")
_EXTERNAL_URL_RE = re.compile(r"(?i)\bhttps?://")
_VITE_CLIENT_RE = re.compile(r"(?i)(?:/@vite/client|@vite/client)")


class WebArtifactViolation(RuntimeError):
    """웹 산출물이 완전성·무결성·입력 신선도 계약을 어겼다."""


@dataclass(frozen=True)
class VerifiedWebArtifact:
    """제품 런타임이 사용해도 되는 검증 완료 웹 루트."""

    root: Path
    index_path: Path
    artifact_id: str
    tree_sha256: str


@dataclass(frozen=True)
class ToolchainVersions:
    """Seal producer가 실제 명령에서 측정한 build toolchain."""

    node: str
    npm: str
    vite: str

    def as_dict(self) -> dict[str, str]:
        return {"node": self.node, "npm": self.npm, "vite": self.vite}


@dataclass(frozen=True)
class _FileRecord:
    path: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, str | int]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class _Seal:
    artifact_id: str
    source_commit: str
    source_input_sha256: str
    source_files: tuple[_FileRecord, ...]
    package_lock: _FileRecord
    toolchain: ToolchainVersions
    vite_manifest: _FileRecord
    tree_sha256: str
    output_files: tuple[_FileRecord, ...]

    def core_document(self) -> dict[str, Any]:
        return {
            "schema": SEAL_SCHEMA,
            "source": {
                "commit": self.source_commit,
                "input_sha256": self.source_input_sha256,
                "files": [record.as_dict() for record in self.source_files],
            },
            "package_lock": self.package_lock.as_dict(),
            "toolchain": self.toolchain.as_dict(),
            "vite_manifest": self.vite_manifest.as_dict(),
            "output": {
                "tree_sha256": self.tree_sha256,
                "files": [record.as_dict() for record in self.output_files],
            },
        }

    def document(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, **self.core_document()}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise WebArtifactViolation(f"web artifact file cannot be read: {path}") from exc


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _record_digest(records: Sequence[_FileRecord]) -> str:
    return _canonical_sha256([record.as_dict() for record in records])


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _validate_relative_path(value: str, *, role: str) -> None:
    posix = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or posix.is_absolute()
        or posix.as_posix() != value
        or any(part in {"", ".", ".."} for part in posix.parts)
        or ":" in posix.parts[0]
    ):
        raise WebArtifactViolation(f"{role} path is unsafe: {value!r}")


def _record(path: Path, *, relative_to: Path, role: str) -> _FileRecord:
    if _is_link(path):
        raise WebArtifactViolation(f"{role} contains a link: {path}")
    try:
        relative = path.relative_to(relative_to).as_posix()
        size = path.stat().st_size
    except OSError as exc:
        raise WebArtifactViolation(f"{role} file cannot be inspected: {path}") from exc
    _validate_relative_path(relative, role=role)
    return _FileRecord(path=relative, size=size, sha256=_file_sha256(path))


def _tree_records(
    root: Path,
    *,
    role: str,
    relative_to: Path | None = None,
    excluded: frozenset[str] = frozenset(),
) -> tuple[_FileRecord, ...]:
    if not root.is_dir():
        raise WebArtifactViolation(f"{role} directory missing: {root}")
    relative_to = relative_to or root
    paths: list[Path] = []
    try:
        candidates = list(root.rglob("*"))
    except OSError as exc:
        raise WebArtifactViolation(f"{role} directory cannot be scanned: {root}") from exc
    for path in candidates:
        if _is_link(path):
            raise WebArtifactViolation(f"{role} contains a link: {path}")
        if path.is_file() and path.relative_to(relative_to).as_posix() not in excluded:
            paths.append(path)
    records = tuple(
        _record(path, relative_to=relative_to, role=role)
        for path in sorted(paths, key=lambda item: item.relative_to(relative_to).as_posix())
    )
    if not records:
        raise WebArtifactViolation(f"{role} directory is empty: {root}")
    return records


def _required_file_record(path: Path, *, relative_to: Path, role: str) -> _FileRecord:
    if not path.is_file() or _is_link(path):
        raise WebArtifactViolation(f"{role} file missing: {path}")
    return _record(path, relative_to=relative_to, role=role)


def _source_records(repo_root: Path) -> tuple[_FileRecord, ...]:
    frontend_root = repo_root / "frontend"
    records = list(
        _tree_records(frontend_root, role="frontend source", relative_to=repo_root)
    )
    records.extend(
        _required_file_record(
            repo_root / relative,
            relative_to=repo_root,
            role="web build input",
        )
        for relative in _SOURCE_CONFIG_PATHS
    )
    return tuple(sorted(records, key=lambda item: item.path))


def _output_records(artifact_root: Path) -> tuple[_FileRecord, ...]:
    return _tree_records(
        artifact_root,
        role="web artifact",
        excluded=frozenset({SEAL_FILENAME}),
    )


def _find_record(
    records: Sequence[_FileRecord],
    relative_path: str,
    *,
    role: str,
) -> _FileRecord:
    matches = [record for record in records if record.path == relative_path]
    if len(matches) != 1:
        raise WebArtifactViolation(f"{role} record missing or duplicated: {relative_path}")
    return matches[0]


def _json_object(path: Path, *, role: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise WebArtifactViolation(f"{role} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise WebArtifactViolation(f"{role} is not a JSON object: {path}")
    return value


def _exact_semver(value: Any, *, role: str) -> str:
    if not isinstance(value, str) or _SEMVER_RE.fullmatch(value) is None:
        raise WebArtifactViolation(f"{role} must be an exact semantic version")
    return value


def _declared_toolchain(repo_root: Path) -> ToolchainVersions:
    try:
        node_pin = (repo_root / ".node-version").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise WebArtifactViolation("Node pin cannot be read: .node-version") from exc
    node = _exact_semver(node_pin.removeprefix("v"), role=".node-version")

    package = _json_object(repo_root / "package.json", role="package.json")
    package_manager = package.get("packageManager")
    if not isinstance(package_manager, str) or not package_manager.startswith("npm@"):
        raise WebArtifactViolation("package.json packageManager must pin npm exactly")
    npm = _exact_semver(
        package_manager.removeprefix("npm@"),
        role="package.json packageManager",
    )
    dev_dependencies = package.get("devDependencies")
    if not isinstance(dev_dependencies, dict):
        raise WebArtifactViolation("package.json devDependencies is missing")
    vite = _exact_semver(
        dev_dependencies.get("vite"),
        role="package.json devDependencies.vite",
    )

    lock = _json_object(repo_root / "package-lock.json", role="package-lock.json")
    packages = lock.get("packages")
    root_package = packages.get("") if isinstance(packages, dict) else None
    locked_dependencies = (
        root_package.get("devDependencies") if isinstance(root_package, dict) else None
    )
    locked_vite = (
        locked_dependencies.get("vite") if isinstance(locked_dependencies, dict) else None
    )
    if locked_vite != vite:
        raise WebArtifactViolation(
            "package-lock.json root devDependencies.vite does not match package.json"
        )
    return ToolchainVersions(node=node, npm=npm, vite=vite)


def _resolve_command(command: str | Path | None, *, fallback: str, role: str) -> str:
    if command is not None:
        return str(command)
    resolved = shutil.which(fallback)
    if resolved is None:
        raise WebArtifactViolation(f"{role} command missing: {fallback}")
    return resolved


def _command_version(command: str, *, cwd: Path, role: str) -> str:
    try:
        completed = subprocess.run(
            [command, "--version"],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WebArtifactViolation(f"{role} version command failed: {command}") from exc
    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    match = _SEMVER_IN_OUTPUT_RE.search(combined)
    if completed.returncode != 0 or match is None:
        raise WebArtifactViolation(f"{role} version command failed: {command}")
    return match.group(1)


def _detect_toolchain(
    repo_root: Path,
    *,
    node_command: str | Path | None = None,
    npm_command: str | Path | None = None,
    vite_command: str | Path | None = None,
) -> ToolchainVersions:
    expected = _declared_toolchain(repo_root)
    node = _command_version(
        _resolve_command(node_command, fallback="node", role="Node"),
        cwd=repo_root,
        role="Node",
    )
    npm_fallback = "npm.cmd" if os.name == "nt" else "npm"
    npm = _command_version(
        _resolve_command(npm_command, fallback=npm_fallback, role="npm"),
        cwd=repo_root,
        role="npm",
    )
    if vite_command is None:
        suffix = "vite.cmd" if os.name == "nt" else "vite"
        vite_command = repo_root / "node_modules" / ".bin" / suffix
    vite = _command_version(str(vite_command), cwd=repo_root, role="Vite")
    actual = ToolchainVersions(node=node, npm=npm, vite=vite)
    if actual != expected:
        raise WebArtifactViolation(
            "actual web toolchain does not match exact pins: "
            f"expected={expected.as_dict()} actual={actual.as_dict()}"
        )
    return actual


def _git_output(repo_root: Path, args: Sequence[str], *, role: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WebArtifactViolation(f"{role} failed") from exc
    if completed.returncode != 0:
        raise WebArtifactViolation(f"{role} failed")
    return completed.stdout.strip()


def _current_git_commit(repo_root: Path) -> str:
    commit = _git_output(repo_root, ("rev-parse", "HEAD"), role="Git commit lookup")
    if _COMMIT_RE.fullmatch(commit) is None:
        raise WebArtifactViolation("Git commit lookup returned an invalid full SHA")
    return commit


def _assert_source_inputs_clean(repo_root: Path) -> None:
    dirty = _git_output(
        repo_root,
        (
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "frontend",
            *_SOURCE_CONFIG_PATHS,
        ),
        role="Git source-input status lookup",
    )
    if dirty:
        raise WebArtifactViolation(
            "web build inputs are not committed; refusing to seal a dirty source tree"
        )


def _validate_vite_manifest(path: Path) -> None:
    manifest = _json_object(path, role="Vite manifest")
    if not manifest:
        raise WebArtifactViolation(f"Vite manifest is empty: {path}")


def _validate_output_references(
    artifact_root: Path,
    records: Sequence[_FileRecord],
) -> None:
    checks = (
        ("Vite dev client", _VITE_CLIENT_RE),
        ("absolute /assets URL", _ABSOLUTE_ASSET_RE),
        ("file: URL", _FILE_URL_RE),
        ("external HTTP(S) resource", _EXTERNAL_URL_RE),
    )
    for record in records:
        path = artifact_root / PurePosixPath(record.path)
        if path.suffix.lower() not in _TEXT_OUTPUT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise WebArtifactViolation(
                f"text web artifact is not valid UTF-8: {record.path}"
            ) from exc
        for label, pattern in checks:
            if pattern.search(text):
                raise WebArtifactViolation(
                    f"forbidden {label} in web artifact: {record.path}"
                )


def _assert_exact_keys(
    value: Mapping[str, Any],
    expected: frozenset[str],
    *,
    role: str,
) -> None:
    if set(value) != expected:
        raise WebArtifactViolation(f"web artifact seal has invalid fields: {role}")


def _parse_digest(value: Any, *, role: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise WebArtifactViolation(f"web artifact seal has invalid digest: {role}")
    return value


def _parse_record(value: Any, *, role: str) -> _FileRecord:
    if not isinstance(value, dict):
        raise WebArtifactViolation(f"web artifact seal has invalid file record: {role}")
    _assert_exact_keys(
        value,
        frozenset({"path", "size", "sha256"}),
        role=role,
    )
    path = value["path"]
    size = value["size"]
    if not isinstance(path, str):
        raise WebArtifactViolation(f"web artifact seal has invalid path: {role}")
    _validate_relative_path(path, role=role)
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise WebArtifactViolation(f"web artifact seal has invalid size: {role}")
    return _FileRecord(
        path=path,
        size=size,
        sha256=_parse_digest(value["sha256"], role=f"{role}.sha256"),
    )


def _parse_records(value: Any, *, role: str) -> tuple[_FileRecord, ...]:
    if not isinstance(value, list) or not value:
        raise WebArtifactViolation(f"web artifact seal has invalid file list: {role}")
    records = tuple(
        _parse_record(item, role=f"{role}[{index}]")
        for index, item in enumerate(value)
    )
    paths = tuple(record.path for record in records)
    if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        raise WebArtifactViolation(
            f"web artifact seal file list is not unique and sorted: {role}"
        )
    return records


def _load_seal(seal_path: Path) -> _Seal:
    document = _json_object(seal_path, role="web artifact seal")
    _assert_exact_keys(
        document,
        frozenset(
            {
                "schema",
                "artifact_id",
                "source",
                "package_lock",
                "toolchain",
                "vite_manifest",
                "output",
            }
        ),
        role="root",
    )
    if document["schema"] != SEAL_SCHEMA:
        raise WebArtifactViolation("unsupported web artifact seal schema")

    source = document["source"]
    toolchain = document["toolchain"]
    output = document["output"]
    if not isinstance(source, dict) or not isinstance(toolchain, dict) or not isinstance(
        output, dict
    ):
        raise WebArtifactViolation("web artifact seal has invalid sections")
    _assert_exact_keys(
        source,
        frozenset({"commit", "input_sha256", "files"}),
        role="source",
    )
    _assert_exact_keys(
        toolchain,
        frozenset({"node", "npm", "vite"}),
        role="toolchain",
    )
    _assert_exact_keys(
        output,
        frozenset({"tree_sha256", "files"}),
        role="output",
    )

    commit = source["commit"]
    if not isinstance(commit, str) or _COMMIT_RE.fullmatch(commit) is None:
        raise WebArtifactViolation("web artifact seal has invalid source commit")
    versions = ToolchainVersions(
        node=_exact_semver(toolchain["node"], role="seal toolchain.node"),
        npm=_exact_semver(toolchain["npm"], role="seal toolchain.npm"),
        vite=_exact_semver(toolchain["vite"], role="seal toolchain.vite"),
    )
    seal = _Seal(
        artifact_id=_parse_digest(document["artifact_id"], role="artifact_id"),
        source_commit=commit,
        source_input_sha256=_parse_digest(
            source["input_sha256"],
            role="source.input_sha256",
        ),
        source_files=_parse_records(source["files"], role="source.files"),
        package_lock=_parse_record(document["package_lock"], role="package_lock"),
        toolchain=versions,
        vite_manifest=_parse_record(document["vite_manifest"], role="vite_manifest"),
        tree_sha256=_parse_digest(
            output["tree_sha256"],
            role="output.tree_sha256",
        ),
        output_files=_parse_records(output["files"], role="output.files"),
    )
    if _record_digest(seal.source_files) != seal.source_input_sha256:
        raise WebArtifactViolation("source input digest in web artifact seal is inconsistent")
    lock_record = _find_record(
        seal.source_files,
        "package-lock.json",
        role="package-lock input",
    )
    if lock_record != seal.package_lock:
        raise WebArtifactViolation("package-lock digest in web artifact seal is inconsistent")
    if _record_digest(seal.output_files) != seal.tree_sha256:
        raise WebArtifactViolation("output tree digest in web artifact seal is inconsistent")
    manifest_record = _find_record(
        seal.output_files,
        VITE_MANIFEST_PATH,
        role="Vite manifest",
    )
    if manifest_record != seal.vite_manifest:
        raise WebArtifactViolation("Vite manifest digest in web artifact seal is inconsistent")
    if _canonical_sha256(seal.core_document()) != seal.artifact_id:
        raise WebArtifactViolation("web artifact ID mismatch")
    return seal


def _seal_candidates(artifact_root: Path) -> tuple[Path, ...]:
    try:
        return tuple(
            path
            for path in artifact_root.rglob(SEAL_FILENAME)
            if path.is_file() or _is_link(path)
        )
    except OSError as exc:
        raise WebArtifactViolation(
            f"web artifact directory cannot be scanned: {artifact_root}"
        ) from exc


def _verify_output_tree(artifact_root: Path, seal: _Seal) -> None:
    manifest_path = artifact_root / PurePosixPath(VITE_MANIFEST_PATH)
    if not manifest_path.is_file() or _is_link(manifest_path):
        raise WebArtifactViolation(f"Vite manifest missing: {manifest_path}")

    actual = _output_records(artifact_root)
    expected_by_path = {record.path: record for record in seal.output_files}
    actual_by_path = {record.path: record for record in actual}
    missing = sorted(set(expected_by_path) - set(actual_by_path))
    if missing:
        raise WebArtifactViolation("listed web artifact file missing: " + ", ".join(missing))
    extra = sorted(set(actual_by_path) - set(expected_by_path))
    if extra:
        raise WebArtifactViolation("extra stale web artifact file: " + ", ".join(extra))
    mutated = sorted(
        path
        for path in expected_by_path
        if expected_by_path[path] != actual_by_path[path]
    )
    if mutated:
        raise WebArtifactViolation("web artifact byte digest mismatch: " + ", ".join(mutated))
    if _record_digest(actual) != seal.tree_sha256:
        raise WebArtifactViolation("web artifact tree digest mismatch")
    _validate_vite_manifest(manifest_path)
    _validate_output_references(artifact_root, actual)


def _verify_source_state(repo_root: Path, seal: _Seal) -> None:
    current_commit = _current_git_commit(repo_root)
    if current_commit != seal.source_commit:
        raise WebArtifactViolation(
            "source commit mismatch: "
            f"sealed={seal.source_commit} current={current_commit}"
        )
    declared_toolchain = _declared_toolchain(repo_root)
    if seal.toolchain != declared_toolchain:
        raise WebArtifactViolation(
            "sealed toolchain does not match current exact pins: "
            f"sealed={seal.toolchain.as_dict()} "
            f"declared={declared_toolchain.as_dict()}"
        )
    actual_lock = _required_file_record(
        repo_root / "package-lock.json",
        relative_to=repo_root,
        role="package-lock input",
    )
    if actual_lock != seal.package_lock:
        raise WebArtifactViolation("package-lock input stale")
    actual_sources = _source_records(repo_root)
    if actual_sources != seal.source_files or _record_digest(actual_sources) != (
        seal.source_input_sha256
    ):
        raise WebArtifactViolation("frontend/config source input stale")


def _verify_artifact(
    artifact_root: Path,
    *,
    repo_root: Path | None,
) -> VerifiedWebArtifact:
    if not artifact_root.is_dir():
        raise WebArtifactViolation(f"web artifact directory missing: {artifact_root}")
    expected_seal = artifact_root / SEAL_FILENAME
    candidates = _seal_candidates(artifact_root)
    if not expected_seal.is_file() or _is_link(expected_seal):
        raise WebArtifactViolation(f"web artifact seal missing: {expected_seal}")
    if candidates != (expected_seal,):
        raise WebArtifactViolation(
            "web artifact must contain exactly one root seal: "
            + ", ".join(path.as_posix() for path in candidates)
        )
    seal = _load_seal(expected_seal)
    _verify_output_tree(artifact_root, seal)
    if repo_root is not None:
        _verify_source_state(repo_root, seal)
    index_path = artifact_root / "index.html"
    if not index_path.is_file() or _is_link(index_path):
        raise WebArtifactViolation(f"web artifact index missing: {index_path}")
    return VerifiedWebArtifact(
        root=artifact_root,
        index_path=index_path,
        artifact_id=seal.artifact_id,
        tree_sha256=seal.tree_sha256,
    )


def resolve_web_artifact(
    *,
    repo_root: Path | None = None,
    frozen_root: Path | None = None,
) -> VerifiedWebArtifact:
    """유일한 source 또는 frozen 제품 web artifact를 검증해 돌려준다.

    ``repo_root``와 ``frozen_root`` 중 정확히 하나만 전달해야 한다. Source checkout은
    ``<repo>/build/web``과 현재 source inputs/commit을 검증한다. Frozen 런타임은 전달받은
    PyInstaller ``_MEIPASS`` 아래 ``web``만 검증하며 source나 build tool을 탐색하지 않는다.
    """
    if (repo_root is None) == (frozen_root is None):
        raise WebArtifactViolation(
            "exactly one of repo_root or frozen_root is required"
        )
    if repo_root is not None:
        resolved_repo = repo_root.resolve()
        return _verify_artifact(
            (resolved_repo / "build" / "web").resolve(),
            repo_root=resolved_repo,
        )
    assert frozen_root is not None
    return _verify_artifact(
        (frozen_root.resolve() / "web").resolve(),
        repo_root=None,
    )


def seal_repository_web_artifact(
    repo_root: Path,
    *,
    node_command: str | Path | None = None,
    npm_command: str | Path | None = None,
    vite_command: str | Path | None = None,
) -> VerifiedWebArtifact:
    """현재 commit의 fresh ``build/web``을 actual pinned toolchain 증거와 함께 봉인한다."""
    repo_root = repo_root.resolve()
    artifact_root = (repo_root / "build" / "web").resolve()
    if not artifact_root.is_dir():
        raise WebArtifactViolation(f"web artifact directory missing: {artifact_root}")
    _assert_source_inputs_clean(repo_root)
    source_commit = _current_git_commit(repo_root)
    source_files = _source_records(repo_root)
    package_lock = _find_record(
        source_files,
        "package-lock.json",
        role="package-lock input",
    )
    toolchain = _detect_toolchain(
        repo_root,
        node_command=node_command,
        npm_command=npm_command,
        vite_command=vite_command,
    )
    output_files = _output_records(artifact_root)
    index_path = artifact_root / "index.html"
    if not index_path.is_file() or _is_link(index_path):
        raise WebArtifactViolation(f"web artifact index missing: {index_path}")
    manifest_path = artifact_root / PurePosixPath(VITE_MANIFEST_PATH)
    if not manifest_path.is_file() or _is_link(manifest_path):
        raise WebArtifactViolation(f"Vite manifest missing: {manifest_path}")
    _validate_vite_manifest(manifest_path)
    _validate_output_references(artifact_root, output_files)
    vite_manifest = _find_record(
        output_files,
        VITE_MANIFEST_PATH,
        role="Vite manifest",
    )
    core = _Seal(
        artifact_id="0" * 64,
        source_commit=source_commit,
        source_input_sha256=_record_digest(source_files),
        source_files=source_files,
        package_lock=package_lock,
        toolchain=toolchain,
        vite_manifest=vite_manifest,
        tree_sha256=_record_digest(output_files),
        output_files=output_files,
    )
    seal = _Seal(
        artifact_id=_canonical_sha256(core.core_document()),
        source_commit=core.source_commit,
        source_input_sha256=core.source_input_sha256,
        source_files=core.source_files,
        package_lock=core.package_lock,
        toolchain=core.toolchain,
        vite_manifest=core.vite_manifest,
        tree_sha256=core.tree_sha256,
        output_files=core.output_files,
    )
    seal_path = artifact_root / SEAL_FILENAME
    if seal_path.exists() and _is_link(seal_path):
        raise WebArtifactViolation(f"web artifact seal cannot be a link: {seal_path}")
    temporary = artifact_root / f".{SEAL_FILENAME}.tmp"
    if temporary.exists():
        raise WebArtifactViolation(f"stale seal temporary file exists: {temporary}")
    try:
        temporary.write_text(
            json.dumps(
                seal.document(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, seal_path)
    except OSError as exc:
        raise WebArtifactViolation(f"web artifact seal cannot be written: {seal_path}") from exc
    return _verify_artifact(artifact_root, repo_root=repo_root)
