"""Output-directory filesystem effects."""

from __future__ import annotations

from pathlib import Path


def existing_output_paths(out_dir: "str | Path", names: "list[str]") -> "list[str]":
    out = Path(out_dir)
    return [str(out / name) for name in names if (out / name).exists()]


def ensure_output_directory(out_dir: "str | Path") -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
