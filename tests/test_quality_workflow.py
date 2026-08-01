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


def test_press_geometry_browser_precondition_is_its_own_visible_step() -> None:
    """눌림 기하 게이트(U2 §2.11)의 전제인 **설치 Chrome** 을 별 단계로 확인한다.

    부재가 테스트 안쪽 오류로 번역돼 나오면 원인 판독이 늦고, 조용한 스킵으로 새면 이
    결함류(규칙은 있는데 결과가 틀림)가 또 세 슬라이스를 통과한다. 옵트아웃 변수도 CI 에서
    명시로 걷어 「러너에서만 조용히 꺼져 있는」 상태를 만들지 않는다.
    """
    text, _ = _workflow()
    assert "Press-geometry browser precondition" in text
    assert "HWPX_SKIP_MOTION_TESTS" in text
    assert "channel='chrome'" in text


def test_distribution_gate_builds_all_portable_targets() -> None:
    text, _ = _workflow()
    assert ".\\packaging\\build.ps1 -Target all" in text
    assert "distribution (filler + CLI)" in text


def test_every_quality_surface_builds_the_same_exact_frontend_artifact() -> None:
    text, _ = _workflow()

    assert text.count("actions/setup-node@v4") == 3
    assert text.count("node-version-file: .node-version") == 3
    assert text.count("Verify exact Node and npm") == 3
    assert text.count("'v24.18.1'") == 3
    assert text.count("'11.16.0'") == 3
    assert text.count("npm.cmd ci") == 3
    assert text.count("npm.cmd run build") == 3
    assert text.count("npm.cmd run verify:web") == 3


def test_release_builds_the_exact_frontend_before_tests_and_packaging() -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert release.count("actions/setup-node@v4") == 1
    assert "node-version-file: .node-version" in release
    assert "Verify exact Node and npm" in release
    assert "'v24.18.1'" in release and "'11.16.0'" in release
    assert release.index("npm.cmd ci") < release.index("npm.cmd run build")
    assert release.index("npm.cmd run verify:web") < release.index(".\\test.ps1")
    assert release.index("npm.cmd run verify:web") < release.index(".\\build.ps1")


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


def test_quickstart_101_live_precondition_is_its_own_visible_step() -> None:
    """101 실주행 게이트(#423)의 전제를 별 단계로 확인하고, 옵트아웃을 CI 에서 걷는다.

    press-geometry 와 같은 이유다. 다만 여기엔 축이 하나 더 있다 — 이 게이트는 **실행 산출물**
    (실 HWPX 3건)을 판정하므로, 전제 부재가 조용한 스킵으로 새면 「101 이 도는지 아무도 안 보는」
    상태로 돌아간다. 그 상태가 정확히 #423 의 출발점이었다(캡처 하니스가 몇 달 깨져 있었고
    이름을 보는 정적 단언들은 그동안 초록이었다).
    """
    text, _ = _workflow()
    assert "Quickstart 101 live precondition" in text
    assert "scripts/capture_101_screenshots.py check --preflight" in text
    assert "HWPX_SKIP_GUI_TESTS" in text


def test_no_gate_opt_out_is_switched_on_inside_the_workflow() -> None:
    """옵트아웃 변수를 **켜는** 줄은 워크플로 어디에도 없다.

    CI 는 셋 다 걷고 돈다(CLAUDE.md). 그런데 "걷는다"는 `Remove-Item` 단계로만 보이고, 어딘가
    한 줄이 그것을 다시 켜면 그 단계는 선언만 남고 결과가 죽는다 — 이 저장소가 반복해 만난
    결함류다. 그래서 부재를 직접 센다.
    """
    text, _ = _workflow()
    for variable in ("HWPX_SKIP_GUI_TESTS", "HWPX_SKIP_NATIVE_TESTS", "HWPX_SKIP_MOTION_TESTS"):
        assert f"{variable}:" not in text, f"{variable} 를 켜는 줄이 워크플로에 있습니다"
        assert f"{variable}=1" not in text, f"{variable} 를 켜는 줄이 워크플로에 있습니다"
        assert f'{variable} = "1"' not in text, f"{variable} 를 켜는 줄이 워크플로에 있습니다"
