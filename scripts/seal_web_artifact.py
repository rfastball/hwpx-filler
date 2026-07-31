"""Produce the single fail-closed Vite web artifact seal for ``build/web``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hwpxfiller.web_artifact import (
    WebArtifactViolation,
    resolve_web_artifact,
    seal_repository_web_artifact,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--node-command")
    parser.add_argument("--npm-command")
    parser.add_argument("--vite-command")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify the existing source-checkout build/web seal without invoking build tools",
    )
    args = parser.parse_args(argv)
    try:
        if args.verify:
            if any((args.node_command, args.npm_command, args.vite_command)):
                parser.error("tool command overrides cannot be used with --verify")
            artifact = resolve_web_artifact(repo_root=args.repo_root)
        else:
            artifact = seal_repository_web_artifact(
                args.repo_root,
                node_command=args.node_command,
                npm_command=args.npm_command,
                vite_command=args.vite_command,
            )
    except (OSError, WebArtifactViolation) as exc:
        print(f"web artifact seal failed: {exc}", file=sys.stderr)
        return 2
    print(f"artifact_id={artifact.artifact_id}")
    print(f"tree_sha256={artifact.tree_sha256}")
    print(f"root={artifact.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
