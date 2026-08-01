"""Generate version resources from the single version in pyproject.toml.

``build-metadata.json`` 은 릴리스에 함께 실려 나가는 **유일한 서술 자산**이다. 종전에는
version/commit/python/pyinstaller 넷뿐이라 "이 릴리스가 어떤 프런트 산출물을 실었는가"를
메타데이터만으로는 말할 수 없었다(#383). 그래서 잠금과 sealed web artifact 의 identity 를
같이 싣는다 — 값은 전부 이미 있는 단일 출처(`uv.lock`·seal)에서 읽어오고 여기서 새로
계산하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from hwpxfiller.web_artifact import (
    SEAL_FILENAME,
    WebArtifactViolation,
    resolve_web_artifact,
)

ROOT = Path(__file__).resolve().parents[1]

PRODUCTS = {
    "filler": {
        # 사용자 노출 제품명(#258). 기술 식별자(파일명·internal_name)는 hwpx-filler 유지.
        "product_name": "문서나르미",
        "description": "HWPX 누름틀 문서 생성기",
        "filename": "hwpx-filler-web.exe",
        "internal_name": "hwpx-filler-web",
    },
}


def _version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)["project"]["version"]


def _numeric_version(version: str) -> tuple[int, int, int, int]:
    # PEP440 프리릴리스(rc1)·dev(.dev1)·로컬(+meta) 식별자는 숫자가 아니라
    # 마지막 릴리스 세그먼트에 바로 붙거나("0.3.0rc1") 구분자로 붙는다
    # ("0.3.0.dev1", "0.3.0+meta"). Windows 버전 리소스는 숫자 4개뿐이라
    # 선두의 점-구분 숫자열만 취한다.
    match = re.match(r"\d+(\.\d+)*", version)
    if not match:
        raise ValueError(f"버전에서 숫자 부분을 찾을 수 없습니다: {version}")
    parts = [int(part) for part in match.group().split(".")]
    if len(parts) > 4:
        raise ValueError(f"Windows 버전은 숫자 4개 이하여야 합니다: {version}")
    return tuple((parts + [0] * 4)[:4])  # type: ignore[return-value]


def _resource(product: dict[str, str], version: str) -> str:
    numeric = ", ".join(str(value) for value in _numeric_version(version))
    return f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({numeric}), prodvers=({numeric}), mask=0x3F,
    flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable("040904B0", [
    StringStruct("ProductName", "{product['product_name']}"),
    StringStruct("FileDescription", "{product['description']}"),
    StringStruct("FileVersion", "{version}"),
    StringStruct("ProductVersion", "{version}"),
    StringStruct("OriginalFilename", "{product['filename']}"),
    StringStruct("InternalName", "{product['internal_name']}"),
    StringStruct("LegalCopyright", ""),
  ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
)
'''


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _web_metadata(repo_root: Path, *, required: bool) -> dict[str, object]:
    """검증된 sealed web artifact 의 identity 를 릴리스 메타데이터에 싣는다.

    ``resolve_web_artifact`` 는 fail-closed 다 — seal·전체 트리·source 신선도를 통과하지
    못하면 예외를 던진다. 그러므로 여기 실리는 값은 언제나 **검증을 통과한** 산출물의
    것이다. 서술용 부가 정보(toolchain·lock·source commit)는 그 검증된 seal 파일에서
    그대로 읽는다.

    filler 를 싣지 않는 빌드(CLI 전용)는 산출물이 아예 없는 것이 정상이다. 그때 키를
    조용히 비우면 "프런트를 안 실은 빌드"와 "프런트 검증에 실패한 빌드"가 같은 모양이
    된다 — 부재를 사유와 함께 명시 기록한다.
    """
    try:
        artifact = resolve_web_artifact(repo_root=repo_root)
    except (OSError, WebArtifactViolation) as exc:
        if required:
            raise SystemExit(
                f"sealed web artifact 를 요구했지만 검증에 실패했습니다: {exc}"
            ) from exc
        return {"present": False, "reason": str(exc)}

    seal = json.loads((artifact.root / SEAL_FILENAME).read_text(encoding="utf-8"))
    return {
        "present": True,
        "artifact_id": artifact.artifact_id,
        "tree_sha256": artifact.tree_sha256,
        "source_commit": seal["source"]["commit"],
        "package_lock_sha256": seal["package_lock"]["sha256"],
        "toolchain": seal["toolchain"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "version")
    parser.add_argument(
        "--require-web",
        action="store_true",
        help="sealed build/web 이 없거나 검증에 실패하면 실패한다(filler 를 싣는 빌드)",
    )
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    version = _version()
    for key, product in PRODUCTS.items():
        (args.out / f"hwpx_{key}_version.txt").write_text(
            _resource(product, version), encoding="utf-8"
        )
    version_info = ".".join(str(part) for part in _numeric_version(version))
    (args.out / "version.iss").write_text(
        f'#define AppVersion "{version}"\n'
        f'#define AppVersionInfo "{version_info}"\n',
        encoding="utf-8",
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    metadata = {
        "version": version,
        "commit": commit or None,
        "python": sys.version.split()[0],
        "pyinstaller": _package_version("pyinstaller"),
        "uv_lock_sha256": _file_sha256(ROOT / "uv.lock"),
        "web": _web_metadata(ROOT, required=args.require_web),
    }
    (args.out / "build-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"build metadata: {version} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
