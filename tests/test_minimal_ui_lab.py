"""백지 UI 랩 준비 계약.

이 단계의 목적은 워크플로 구현이 아니라 기존 표면과 분리된 빈 캔버스다.
"""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "web-minimal"


def test_lab_is_separate_and_bootable_without_workflow_calls():
    index = (LAB / "variants" / "blank" / "index.html").read_text(encoding="utf-8")
    bootstrap = (LAB / "shared" / "bootstrap.js").read_text(encoding="utf-8")

    assert 'id="ui-lab-root"' in index
    assert 'src="../../shared/bootstrap.js"' in index
    assert "window.Theme" in bootstrap
    assert "window.Personalization" in bootstrap
    assert "window.__push" in bootstrap
    assert "pywebview.api.initial" not in bootstrap
    assert "pywebview.api.dispatch" not in bootstrap


def test_surface_runner_can_select_lab_or_legacy():
    runner = (ROOT / "run-ui-surface.ps1").read_text(encoding="utf-8")

    assert "variants.json" in runner
    assert "$Variant" in runner
    assert "$Scenario" in runner
    assert "$ValidateOnly" in runner
    assert "Join-Path $root 'web'" in runner
    assert "HWPXFILLER_WEB_DIR" in runner
    assert "HWPXFILLER_HOME" in runner


def test_variant_manifest_and_scenarios_are_explicit():
    manifest = json.loads((LAB / "variants.json").read_text(encoding="utf-8"))

    assert manifest["default"] == "blank"
    assert {item["id"] for item in manifest["variants"]} == {"blank"}
    for item in manifest["variants"]:
        assert (LAB / item["path"] / "index.html").is_file()

    scenarios = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in (LAB / "scenarios").glob("*.json")
    }
    assert set(scenarios) == {"blank", "normal", "missing-values"}
    assert scenarios["blank"]["status"] == "baseline"
    assert scenarios["normal"]["fixture"] is None
    assert scenarios["missing-values"]["fixture"] is None
