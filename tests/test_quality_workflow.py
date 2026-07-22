from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / ".github" / "workflows" / "quality.yml"
CLI_ENTRY = ROOT / "packaging" / "hwpx_cli_entry.py"


def _workflow() -> tuple[str, dict[str, object]]:
    text = QUALITY.read_text(encoding="utf-8")
    loaded = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return text, loaded


def test_quality_workflow_has_three_parallel_required_surfaces() -> None:
    _, workflow = _workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == {"static", "pytest-package-floor", "distribution"}
    assert all("needs" not in job for job in jobs.values())


def test_pytest_job_keeps_native_and_package_floor_visible_separately() -> None:
    text, _ = _workflow()
    assert "Windows native positive scenarios" in text
    assert "tests/test_native_positive.py" in text
    assert "HWPX_SKIP_NATIVE_TESTS" in text
    assert "scripts/check_package_coverage.py" in text
    assert "package-coverage.md" in text


def test_distribution_gate_builds_all_three_portable_targets() -> None:
    text, _ = _workflow()
    assert ".\\packaging\\build.ps1 -Target all" in text
    assert "distribution (filler + diff + CLI)" in text


def test_installer_and_signing_remain_release_only() -> None:
    quality, _ = _workflow()
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for release_only in (
        "package-installer.ps1",
        "WINDOWS_CERTIFICATE_BASE64",
        "Install Inno Setup",
    ):
        assert release_only not in quality
        assert release_only in release


def test_frozen_cli_forces_utf8_for_redirected_windows_output(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("hwpx_cli_entry_contract", CLI_ENTRY)
    assert spec is not None and spec.loader is not None
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)

    class RedirectedStream:
        options: dict[str, str] | None = None

        def reconfigure(self, **kwargs: str) -> None:
            self.options = kwargs

    stdout = RedirectedStream()
    stderr = RedirectedStream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    entry._force_utf8_output()

    expected = {"encoding": "utf-8", "errors": "backslashreplace"}
    assert stdout.options == expected
    assert stderr.options == expected
