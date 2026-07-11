"""Fail when a release tag does not match the project version."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="release tag, for example v0.1.0")
    args = parser.parse_args()
    with (ROOT / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    expected = f"v{version}"
    if args.tag != expected:
        parser.error(f"tag {args.tag!r} does not match project version {expected!r}")
    print(f"release version: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
