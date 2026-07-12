"""hwpxdiff CLI — --html 리포트 저장의 원자성(RC-01).

기존 구현은 truncate-then-render 라 렌더 실패가 기존 리포트를 0B 로 파괴했다.
수리 후: 렌더를 저장 전에 선평가 + 원자 쓰기 — 실패는 시끄럽게(예외), 기존 파일 무손상.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxdiff.cli import main

FIXTURE = str(Path(__file__).parent / "fixtures" / "template_v1.hwpx")


def test_html_report_written(tmp_path, capsys):
    out = tmp_path / "report.html"
    rc = main([FIXTURE, FIXTURE, "--html", str(out)])
    assert rc == 0
    assert out.exists() and out.stat().st_size > 0
    assert "HTML 리포트 저장" in capsys.readouterr().err


def test_render_failure_preserves_existing_report(tmp_path, monkeypatch):
    """렌더 실패 주입 — 기존 리포트가 truncate 되지 않고 그대로 남는다."""
    out = tmp_path / "report.html"
    out.write_text("<html>이전 리포트(5KB 상당)</html>", encoding="utf-8")
    existing = out.read_text(encoding="utf-8")

    import hwpxdiff.diff as diff_mod

    def _boom(result):
        raise RuntimeError("렌더 실패 주입")

    monkeypatch.setattr(diff_mod, "render_html", _boom)
    with pytest.raises(RuntimeError):
        main([FIXTURE, FIXTURE, "--html", str(out)])
    assert out.read_text(encoding="utf-8") == existing  # 기존 리포트 무손상
    assert [p.name for p in tmp_path.iterdir()] == ["report.html"]  # 임시 잔해 없음
