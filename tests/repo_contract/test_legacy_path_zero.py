"""폐기된 frontend 이전 source 경로가 현재 저장소에 재유입되지 않게 한다."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_RETIRED_ROOT = "w" + "eb"
_SEPARATOR = r"[\\/]"
_SEGMENT = r"[\w.\-]+"
_REFERENCE = re.compile(
    r"(?<![\w.\-])(?:(?P<parent>" + _SEGMENT + r")" + _SEPARATOR + r")?"
    + _RETIRED_ROOT
    + _SEPARATOR
    + r"(?:js|css|img|fonts|src|index\.html)(?:"
    + _SEPARATOR
    + _SEGMENT
    + r")*"
)
_BINARY_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff2", ".hwpx", ".xlsx", ".zip"}
)

def _tracked_files() -> tuple[Path, ...]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return tuple(Path(name) for name in listing.split("\0") if name)


def _scan(text: str) -> list[str]:
    hits: list[str] = []
    for match in _REFERENCE.finditer(text):
        if match.group("parent") == "build":
            continue
        start = match.start()
        if parent := match.group("parent"):
            start += len(parent) + 1
        hits.append(text[start : match.end()])
    return hits


def _repository_citations() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for relative in _tracked_files():
        if relative.suffix.lower() in _BINARY_SUFFIXES:
            continue
        try:
            hits = _scan((ROOT / relative).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if hits:
            found[relative.as_posix()] = hits
    return found


def test_retired_source_paths_are_absent() -> None:
    citations = _repository_citations()
    assert not citations, "\n".join(
        f"{name}: {sorted(set(hits))}" for name, hits in citations.items()
    )
