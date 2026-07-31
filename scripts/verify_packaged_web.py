"""Compare the source Vite artifact with a PyInstaller bundled web tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hwpxfiller.web_artifact import WebArtifactViolation, resolve_web_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-root",
        type=Path,
        required=True,
        help="PyInstaller _MEIPASS root containing exactly one sealed web/ tree",
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    try:
        source = resolve_web_artifact(repo_root=args.repo_root)
        bundled = resolve_web_artifact(frozen_root=args.bundle_root)
        if (
            source.artifact_id != bundled.artifact_id
            or source.tree_sha256 != bundled.tree_sha256
        ):
            raise WebArtifactViolation(
                "source and bundled web artifacts do not have the same identity"
            )
    except (OSError, WebArtifactViolation) as exc:
        print(f"packaged web verification failed: {exc}", file=sys.stderr)
        return 2

    evidence = {
        "artifact_id": source.artifact_id,
        "tree_sha256": source.tree_sha256,
        "source_root": str(source.root),
        "bundled_root": str(bundled.root),
        "same_artifact": True,
    }
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
