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
    # tsconfig 는 Vite 의 `.ts` 변환이 읽는 실빌드 입력이다(useDefineForClassFields 류가
    # 출력 바이트에 닿는다 — class field 실물은 react/boundary.ts). 여기 없으면 tsconfig 만
    # 고친 채 봉인해도 신선도 검사가 통과하는 사각이 남는다(R2-04 · #408, R2-01 인계 정산).
    "tsconfig.json",
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
#: 출하 가능한 산출물 **구성**의 exact 폐포(R5-03).
#:
#: 봉인은 Vite 가 낸 것을 기록하고 그 기록에서의 이탈을 거절한다 — 정체성은 지키지만 **성질은
#: 안 지킨다**. ``build.sourcemap`` 이 켜지거나 dev/test 자산이 산출물로 새면 봉인은 그것을
#: 함께 기록하고, 네 사본(source·dist·installed·portable) 전부 같은 값을 들고 초록으로
#: 출하된다. 그래서 "무엇이 실려도 되는가"를 여기서 따로 닫는다.
#:
#: 넓히는 것은 금지가 아니라 **의도된 편집**이다: 새 자산 형식이 정당하면 사유와 함께 이 집합에
#: 올린다. 자동 감지로 넓히지 않는다 — 그러면 sourcemap 하나가 조용히 출하된다.
_OUTPUT_EXACT_FILES = frozenset({"index.html", VITE_MANIFEST_PATH})
_OUTPUT_ASSET_DIR = "assets"
_OUTPUT_ASSET_SUFFIXES = frozenset({".css", ".js", ".svg", ".woff2"})
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
#: 외부 URL **토큰** — 스킴부터 토큰 끝(공백·따옴표·괄호·역슬래시)까지 한 번에 잡는다.
#: 토큰 전체를 대조해야 정확 열거 항목이 ``…/svg.evil.example`` 같은 연장으로 허용을
#: 훔치지 못한다.
_EXTERNAL_URL_RE = re.compile(r"(?i)\bhttps?://[^\s\"'`<>()\\]*")
_VITE_CLIENT_RE = re.compile(r"(?i)(?:/@vite/client|@vite/client)")
#: 산출물 텍스트에 존재해도 오프라인 부팅 계약(ADR-07)을 깨지 않는 **불활성** URL 전수
#: (R2-01 · #405 실측). XML 네임스페이스 식별자 넷은 React 가 ``createElementNS`` 의
#: 이름 인자로 쓰는 런타임 상수라 어떤 로더도 fetch 하지 않고, ``react.dev/errors`` 는
#: 프로덕션 오류 **메시지 본문**의 문서 링크다. 금지의 과녁은 외부 자원 *로드*이지 문자열
#: 등장이 아니다 — 무맥락 전면 금지는 프레임워크 번들 전부를 거짓 빨강으로 만든다.
#:
#: 면제는 **``.js`` 번들 텍스트에만** 선다. HTML·CSS 의 외부 URL 은 등장 자체가 로딩
#: 맥락(``src``·``href``·``url()``)일 개연성이 지배적이라 전면 금지를 유지한다 — 텍스트만
#: 보고 소비 맥락을 안 보면 ``<script src="http://www.w3.org/2000/svg">`` 가 면제를
#: 훔친다(#484 Codex P2). 실측 모집단(React 5종 + CodeMirror 계열 115종)은 전부 JS 문자열
#: 이거나 주석 본문이고, HTML·CSS 산출물의 외부 URL 은 여전히 0 이다.
#:
#: 이 열거 밖의 ``http(s)://`` 는 여전히 전부 거절이다(fail-closed 불변). 넓힐 때는
#: 「그 URL 을 소비하는 로더가 산출물 안에 있는가」를 먼저 반증한다.
_INERT_OUTPUT_URLS = frozenset(
    {
        "http://www.w3.org/1999/xlink",
        "http://www.w3.org/2000/svg",
        "http://www.w3.org/XML/1998/namespace",
        "http://www.w3.org/1998/Math/MathML",
        # CodeMirror 6 계열(S10-05 #862 · TXT 저작 린트메모장)이 데려온 **문서 주석** 링크
        # 전수. 반증 방법과 결과: 같은 그래프를 `minify: true` 로 다시 빌드하면
        # (주석만 사라지고 문자열 리터럴은 남는다) 산출물에 남는 외부 URL 은
        # `http://www.w3.org/2000/svg` **하나뿐**이다 — 아래 전부가 주석 본문이고 어떤
        # 로더도 이 값을 fetch 하지 않는다. 제품 빌드는 감사 가능성을 위해 `minify: false`
        # 라 주석이 그대로 실린다(그 결정이 이 목록의 존재 이유다).
        "https://code.haverbeke.berlin/marijn/style-mod#documentation",
        "https://developer.mozilla.org/en-US/docs/Web/CSS/direction",
        "https://developer.mozilla.org/en-US/docs/Web/CSS/white-space",
        "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference"
        "/Global_Objects/String/codePointAt",
        "https://en.wikipedia.org/wiki/Input_method",
        "https://en.wikipedia.org/wiki/Operational_transformation",
    }
)
#: 접두 면제 — 개별 열거가 무의미한 **한 문서 사이트의 API 레퍼런스 앵커 집합**만 받는다.
#: `react.dev/errors/` 는 프로덕션 오류 메시지 본문의 문서 링크,
#: `codemirror.net/6/docs/ref/` 는 CodeMirror 6 dts 주석의 `@link` 대상 109 종이다(실측).
#: 접두를 넓힐 때도 판정은 같다 — 「그 URL 을 소비하는 로더가 산출물 안에 있는가」를 먼저
#: 반증한다. 호스트 전체(`https://codemirror.net/`)로 넓히지 않은 것은 의도다: 경로까지
#: 좁혀 두면 같은 호스트의 **비주석** 등장이 여전히 빨강으로 남는다.
_INERT_OUTPUT_URL_PREFIXES = (
    "https://react.dev/errors/",
    "https://codemirror.net/6/docs/ref/",
)


def _external_url_offenders(text: str, *, allow_inert: bool) -> "list[str]":
    """외부 URL 토큰 위반 전수 — ``allow_inert`` 는 ``.js`` 번들에만 참이다."""
    return [
        token
        for token in _EXTERNAL_URL_RE.findall(text)
        if not (
            allow_inert
            and (
                token in _INERT_OUTPUT_URLS
                or token.startswith(_INERT_OUTPUT_URL_PREFIXES)
            )
        )
    ]


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


def _validate_output_composition(records: Sequence[_FileRecord]) -> None:
    """산출물이 **무엇으로 되어 있는가**를 exact 폐포로 판정한다(R5-03).

    정체성 대조(네 사본이 같은가)는 이 판정을 대신하지 않는다 — 사본이 전부 같은 sourcemap 을
    들고 있어도 정체성은 참이다. 여기서 거절하는 것은 그 참을 통과하는 성질 위반이다.
    """
    offenders = [
        record.path
        for record in records
        if record.path not in _OUTPUT_EXACT_FILES
        and (
            PurePosixPath(record.path).parent.as_posix() != _OUTPUT_ASSET_DIR
            or PurePosixPath(record.path).suffix.lower() not in _OUTPUT_ASSET_SUFFIXES
        )
    ]
    if offenders:
        raise WebArtifactViolation(
            "web artifact ships a file outside the shipped-composition closure: "
            + ", ".join(sorted(offenders))
            + " (정당한 자산이면 사유와 함께 _OUTPUT_ASSET_SUFFIXES/_OUTPUT_EXACT_FILES 를 넓힙니다)"
        )


def _validate_output_references(
    artifact_root: Path,
    records: Sequence[_FileRecord],
) -> None:
    checks = (
        ("Vite dev client", _VITE_CLIENT_RE),
        ("absolute /assets URL", _ABSOLUTE_ASSET_RE),
        ("file: URL", _FILE_URL_RE),
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
        #: 외부 URL 만은 무맥락 검색이 아니라 토큰 대조다 — `.js` 번들에서만 불활성
        #: 열거(선언 곁 주석 참조)를 감산하고 나머지는 전부 거절한다. 실패 문안이 첫 위반
        #: 토큰을 지목해 원인 판독이 재빌드 없이 선다.
        external = _external_url_offenders(
            text, allow_inert=path.suffix.lower() == ".js"
        )
        if external:
            raise WebArtifactViolation(
                "forbidden external HTTP(S) resource in web artifact: "
                f"{record.path} ({external[0]})"
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
    _validate_output_composition(actual)
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
    _validate_output_composition(output_files)
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
