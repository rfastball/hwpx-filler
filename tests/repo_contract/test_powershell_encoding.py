"""추적되는 PowerShell 진입점이 Windows PowerShell 5.1에서도 UTF-8로 읽혀야 한다."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UTF8_BOM = b"\xef\xbb\xbf"


def test_tracked_powershell_sources_are_bom_prefixed_utf8() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.ps1", "*.psm1", "*.psd1"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    paths = [ROOT / name for name in completed.stdout.decode("utf-8").split("\0") if name]
    assert ROOT / "test.ps1" in paths

    failures: list[str] = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        body = path.read_bytes()
        if not body.startswith(UTF8_BOM):
            failures.append(f"{relative}: UTF-8 BOM 없음")
            continue
        try:
            body.removeprefix(UTF8_BOM).decode("utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{relative}: UTF-8 해독 실패: {exc}")
    assert not failures, "\n".join(failures)
