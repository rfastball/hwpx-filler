"""H-05 부팅 랜딩·홈 정보 위생·첫 실행 CTA 계약."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
HOME = (ROOT / "web" / "js" / "screens" / "home.js").read_text(encoding="utf-8")
JOB = (ROOT / "web" / "js" / "screens" / "job.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")


def test_cold_boot_lands_on_jobs() -> None:
    assert 'data-scr="job" aria-current="true"' in INDEX
    assert '<section class="scr on" id="scr-job">' in INDEX
    assert 'data-scr="home" aria-current="true"' not in INDEX
    assert '<section class="scr on" id="scr-home">' not in INDEX
    assert 'const DEFAULT_SCREEN = "job"' in APP
    assert "go(DEFAULT_SCREEN)" in APP
    assert "if (!routingReady) return" in APP


def test_kpi_and_continue_surfaces_are_removed_with_their_layout() -> None:
    for dead in ("homeKpis", "homeContinue", "renderKpis", "renderContinue"):
        assert dead not in INDEX + HOME
    for dead_rule in (".kpis{", ".kpi{", ".continue-runs{", ".continue-run{"):
        assert dead_rule not in CSS


def test_home_keeps_conditional_alert_information() -> None:
    assert 'id="homeAlerts"' in INDEX
    assert "function renderAlerts" in HOME
    assert "missing_template_count" in HOME and "pool_corrupted" in HOME
    assert "renderCorrupt(s.corrupt_rows)" in HOME


def test_empty_job_list_has_a_direct_new_job_cta_without_a_new_surface() -> None:
    empty = INDEX.split('id="jobListHwpxEmpty"', 1)[1].split("</aside>", 1)[0]
    assert 'id="jobEmptyNewBtn"' in empty
    assert 'class="muted job-empty"' in INDEX
    assert 'class="empty"' not in empty
    assert '$("jobEmptyNewBtn").addEventListener("click", startNewJob)' in JOB
    assert "EditorEntry.newDraft()" in JOB
