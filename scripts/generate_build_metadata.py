"""Generate version resources from the single version in pyproject.toml."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRODUCTS = {
    "filler": {
        "product_name": "HWPX Filler",
        "description": "HWPX 누름틀 문서 생성기",
        "filename": "hwpx-filler.exe",
        "internal_name": "hwpx-filler",
    },
    "diff": {
        "product_name": "HWPX Diff",
        "description": "HWPX 규격서 개정 비교 리뷰어",
        "filename": "hwpx-diff.exe",
        "internal_name": "hwpx-diff",
    },
}


def _version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)["project"]["version"]


def _numeric_version(version: str) -> tuple[int, int, int, int]:
    core = version.split("+", 1)[0].split("-", 1)[0]
    parts = [int(part) for part in core.split(".")]
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "version")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    version = _version()
    for key, product in PRODUCTS.items():
        (args.out / f"hwpx_{key}_version.txt").write_text(
            _resource(product, version), encoding="utf-8"
        )
    (args.out / "version.iss").write_text(
        f'#define AppVersion "{version}"\n', encoding="utf-8"
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    metadata = {
        "version": version,
        "commit": commit or None,
        "python": sys.version.split()[0],
        "pyinstaller": _package_version("pyinstaller"),
    }
    (args.out / "build-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"build metadata: {version} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
