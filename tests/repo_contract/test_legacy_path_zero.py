"""폐기된 frontend 이전 source 경로가 현재 저장소에 재유입되지 않게 한다."""

from __future__ import annotations

import re
import subprocess
from collections import Counter
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

# 역사 문서는 당시의 실재 경로를 인용한다. 파일 전체가 아니라 정확한 다중집합만 허용한다.
HISTORICAL_CITATIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "docs/archive/DATA_FIRST_INTEGRATION_MAP.md": (
        "완료된 이관 원장의 당시 경로",
        (
            "{root}/js/data_picker.js",
            "{root}/js/intent.js",
            "{root}/js/screens/editor.js",
            "{root}/js/screens/home.js",
            "{root}/js/screens/home.js",
            "{root}/js/screens/library.js",
        ),
    ),
    "docs/r-flow-mockups/block4-filter-crystallize-demo.html": (
        "동결 시안의 출처 표기",
        (
            "{root}/js",
            "{root}/js",
            "{root}/js/screens/run.js",
            "{root}/js/screens/run.js",
        ),
    ),
    "docs/UX_FEEDBACK_U2.md": (
        "과거 commit의 경로를 설명하는 git 고고학",
        (
            "{root}/css",
            "{root}/css",
            "{root}/css/app.css",
            "{root}/css/app.css",
            "{root}/css/base.css",
            "{root}/css/job.css",
            "{root}/css/job.css",
            "{root}/css/job.css",
            "{root}/index.html",
        ),
    ),
}


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


def test_retired_source_paths_are_absent_except_exact_historical_citations() -> None:
    citations = _repository_citations()
    unexpected = {
        name: hits for name, hits in citations.items() if name not in HISTORICAL_CITATIONS
    }
    drift: list[str] = []
    for name, (reason, allowed) in HISTORICAL_CITATIONS.items():
        assert reason.strip()
        expected = Counter(item.format(root=_RETIRED_ROOT) for item in allowed)
        actual = Counter(citations.get(name, ()))
        added = sorted((actual - expected).elements())
        removed = sorted((expected - actual).elements())
        if added or removed:
            drift.append(f"{name}: added={added}, removed={removed}")

    assert not unexpected, "\n".join(
        f"{name}: {sorted(set(hits))}" for name, hits in unexpected.items()
    )
    assert not drift, "\n".join(drift)
