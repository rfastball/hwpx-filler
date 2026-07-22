"""hwpxdiff 실 WebView2 창 게이트(#188).

실 구판/신판 corpus를 한 번의 WebView2 창 실행으로 로드한다. 다섯 pytest 계약이 같은
probe 결과를 공유하므로 독립 E2E 수는 5가 아니라 **실창 실행 단위 1개**다. Windows quality와
release에서 실행하며, 데스크톱이 없는 명시적 환경은 ``HWPX_SKIP_GUI_TESTS=1``로만 opt-out한다.
런타임 부재를 감지해 자동으로 건너뛰지 않는다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus" / "real"
OLD = CORPUS / "spec_revision_2025.hwpx"
NEW = CORPUS / "spec_revision_2026.hwpx"

_GUI_GATE = sys.platform != "win32" or bool(os.environ.get("HWPX_SKIP_GUI_TESTS"))
_GATE_REASON = (
    "hwpxdiff 실 WebView2 게이트 — HWPX_SKIP_GUI_TESTS=1로만 명시 옵트아웃"
)


@pytest.fixture(scope="module")
def diff_selftest_result(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("diff-selftest") / "result.json"
    home = tmp_path_factory.mktemp("diff-selftest-home")
    env = dict(
        os.environ,
        HWPXDIFF_HOME=str(home),
        HWPX_DIFF_SELFTEST_OUT=str(out),
        HWPX_DIFF_SELFTEST_OLD=str(OLD),
        HWPX_DIFF_SELFTEST_NEW=str(NEW),
    )
    proc = subprocess.run(
        [sys.executable, "-m", "hwpxdiff.webapp.app", "--selftest"],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert out.exists(), (
        "diff selftest 결과 파일 미생성 — 실창/브리지 실패 가능. "
        f"rc={proc.returncode}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
    )
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
class TestDiffWebSelftestGate:
    def test_probe_has_no_error(self, diff_selftest_result: dict) -> None:
        assert "error" not in diff_selftest_result, diff_selftest_result.get("error")

    def test_real_corpus_labels_and_title_render(self, diff_selftest_result: dict) -> None:
        assert diff_selftest_result["title_dom"] == "HWPX 규격서 개정 비교"
        assert diff_selftest_result["old_label"] == OLD.name
        assert diff_selftest_result["new_label"] == NEW.name

    def test_user_click_roundtrips_through_python_push(self, diff_selftest_result: dict) -> None:
        assert diff_selftest_result["compare_clicked"] is True
        assert diff_selftest_result["status_text"].startswith("변경 ")
        assert diff_selftest_result["status_level"] == "warn"

    def test_summary_and_change_list_render(self, diff_selftest_result: dict) -> None:
        assert diff_selftest_result["kpi_slots"] == 4
        assert sum(int(value) for value in diff_selftest_result["kpi_values"]) > 0
        assert diff_selftest_result["change_rows"] > 0

    def test_document_rows_and_result_surface_render(self, diff_selftest_result: dict) -> None:
        assert diff_selftest_result["document_rows"] > 0
        assert diff_selftest_result["result_visible"] is True
