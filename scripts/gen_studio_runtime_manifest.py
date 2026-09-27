"""Regenerate ``vendor/rhwp/studio-runtime.json`` from ``build/rhwp/studio``.

The manifest is the tracked pin that ``hwpxfiller.web_artifact`` compares the shipped
Studio runtime against (schema 1, upstream commit, every file with size and SHA-256,
sorted by path). Run it after ``scripts/build_rhwp.ps1`` whenever the tracked patch or
the pinned upstream changes; the seal refuses any output that differs from this file.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor" / "rhwp" / "source.json"
OUTPUT_DIR = ROOT / "build" / "rhwp" / "studio"
MANIFEST = ROOT / "vendor" / "rhwp" / "studio-runtime.json"


def build_manifest(output_dir: Path, source_commit: str) -> dict[str, object]:
    files = []
    for path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(output_dir).as_posix()
        if relative.lower().endswith(".map"):
            raise SystemExit(f"source map must not ship with the Studio runtime: {relative}")
        content = path.read_bytes()
        files.append({"path": f"studio/{relative}", "size": len(content),
                      "sha256": hashlib.sha256(content).hexdigest()})
    files.sort(key=lambda item: str(item["path"]))
    if not any(item["path"] == "studio/index.html" for item in files):
        raise SystemExit(f"Studio output has no index.html: {output_dir}")
    return {"schema": 1, "source_commit": source_commit, "files": files}


def main() -> int:
    if not OUTPUT_DIR.is_dir():
        print(f"Studio output missing; run scripts/build_rhwp.ps1 first: {OUTPUT_DIR}", file=sys.stderr)
        return 1
    source_commit = json.loads(SOURCE.read_text(encoding="utf-8"))["commit"]
    manifest = build_manifest(OUTPUT_DIR, source_commit)
    text = json.dumps(manifest, indent=2).replace("\n", "\r\n") + "\r\n"
    if "--check" in sys.argv[1:]:
        if MANIFEST.read_bytes() != text.encode("utf-8"):
            print(f"{MANIFEST} differs from {OUTPUT_DIR}", file=sys.stderr)
            return 1
        print(f"{MANIFEST} matches {len(manifest['files'])} files")  # type: ignore[arg-type]
        return 0
    MANIFEST.write_bytes(text.encode("utf-8"))
    print(f"wrote {MANIFEST} ({len(manifest['files'])} files)")  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
