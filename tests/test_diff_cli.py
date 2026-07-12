"""hwpxdiff CLI 계약 — --html 원자성(RC-01) + 오류 번역 경계(RC-16).

RC-01: 기존 구현은 truncate-then-render 라 렌더 실패가 기존 리포트를 0B 로 파괴했다.
수리 후: 렌더를 저장 전에 선평가 + 원자 쓰기 — 실패는 시끄럽게, 기존 파일 무손상.

RC-16: 일상 실패(부재·손상 파일)가 원시 traceback 대신 '[오류]' 한국어 1줄이 되고,
판본별 분리 로드로 **구판/신판 어느 쪽**이 문제인지 지목하며, 크래시 exit 2 가
정상 비교 exit 0 과 구분되는지 검증한다. Qt 불필요(순수 CLI).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxdiff.cli import main

FIXTURE = str(Path(__file__).parent / "fixtures" / "template_v1.hwpx")
CORPUS = Path(__file__).parent / "corpus" / "real"
OLD = str(CORPUS / "spec_revision_2025.hwpx")
NEW = str(CORPUS / "spec_revision_2026.hwpx")


# ---------------------------------------------------- 리포트 원자성(RC-01)
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


# ---------------------------------------------------- 오류 번역 경계(RC-16)
def test_identical_files_exit_0(capsys):
    assert main([OLD, OLD]) == 0
    assert "변경 없음" in capsys.readouterr().out


def test_real_revision_pair_exit_0(capsys):
    assert main([OLD, NEW]) == 0
    assert capsys.readouterr().out.strip()


def test_corrupt_old_names_old_version_exit_2(tmp_path, capsys):
    bad = tmp_path / "손상.hwpx"
    bad.write_text("zip 아님", encoding="utf-8")
    rc = main([str(bad), NEW])
    assert rc == 2
    err = capsys.readouterr().err
    assert "[오류]" in err and "구판" in err and "손상.hwpx" in err
    assert "신판" not in err          # 문제없는 판본을 끌어들이지 않는다
    assert "Traceback" not in err


def test_missing_new_names_new_version_exit_2(tmp_path, capsys):
    rc = main([OLD, str(tmp_path / "없음.hwpx")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "[오류]" in err and "신판" in err and "없음.hwpx" in err


def test_html_write_failure_translated_exit_2(tmp_path, capsys):
    target = tmp_path / "dir_as_html"
    target.mkdir()
    rc = main([OLD, OLD, "--html", str(target)])
    assert rc == 2
    assert "HTML 리포트" in capsys.readouterr().err
