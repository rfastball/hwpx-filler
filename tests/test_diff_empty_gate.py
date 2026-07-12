"""빈 컨테이너 완전성 게이트(RC-18) — 양쪽 추출 본문 0 을 '변경 없음'으로 단언 금지.

mimetype 만 있는 zip 은 패키지 검증(mimetype 존재)과 추출(섹션 매치 0 → 빈 목록)을
조용히 통과한다 — 게이트 없이는 GUI/CLI 가 '두 판본이 동일합니다'라는 최악 방향의
거짓 음성을 낸다. 확인-또는-경보: 시끄럽게 실패해야 한다.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from hwpxdiff.cli import main as diff_cli_main
from hwpxdiff.diff import EmptyExtractionError, diff_files

CORPUS = Path(__file__).parent / "corpus" / "real"


def _empty_container(path: Path) -> str:
    """mimetype 엔트리만 있는 빈 HWPX 컨테이너(검증·추출을 조용히 통과하는 최소형)."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/hwp+zip")
    return str(path)


def test_diff_files_raises_on_empty_pair(tmp_path):
    """양쪽 다 추출 본문 0 → '변경 없음' 대신 EmptyExtractionError."""
    old = _empty_container(tmp_path / "old.hwpx")
    new = _empty_container(tmp_path / "new.hwpx")
    with pytest.raises(EmptyExtractionError) as ei:
        diff_files(old, new)
    assert "추출하지 못했습니다" in str(ei.value)  # 한국어 사유 + 경로 지목
    assert old in str(ei.value) and new in str(ei.value)


def test_diff_files_one_sided_empty_stays_loud_not_error(tmp_path):
    """실문서 vs 빈 컨테이너는 removed 로 이미 시끄럽다 — 게이트가 삼키지 않는다."""
    real = str(CORPUS / "spec_revision_2025.hwpx")
    empty = _empty_container(tmp_path / "empty.hwpx")
    r = diff_files(real, empty)
    assert r.summary["removed"] > 0


def test_diff_files_identical_real_pair_not_gated():
    """진짜 동일 문서 비교(본문 있음)는 게이트 비대상 — 정당한 '변경 없음'."""
    real = str(CORPUS / "form_purchase_v1.hwpx")
    r = diff_files(real, real)
    assert r.changes == []


def test_cli_empty_pair_exits_nonzero_with_korean_error(tmp_path, capsys):
    """CLI: 빈 쌍은 '(변경 없음)' + exit 0 이 아니라 stderr 사유 + exit 1."""
    old = _empty_container(tmp_path / "old.hwpx")
    new = _empty_container(tmp_path / "new.hwpx")
    rc = diff_cli_main([old, new])
    captured = capsys.readouterr()
    assert rc == 1
    assert "오류" in captured.err and "추출하지 못했습니다" in captured.err
    assert "변경 없음" not in captured.out  # 거짓 음성 문구 미출력
