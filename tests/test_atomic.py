"""원자 쓰기(hwpxfiller.external.atomic) — 쓰기 실패가 기존 파일을 파괴하지 않는 계약(RC-01).

truncate-then-write 는 실패가 기존 내용을 선파괴했다. 헬퍼는 임시 파일에 완성 후
``os.replace`` 원자 교체이므로: 성공 시 내용 일치, 실패 시 기존 파일 무손상 + 임시
파일 잔해 없음 + 예외는 시끄럽게 전파(확인-또는-경보).
"""

from __future__ import annotations

import os

import pytest

from hwpxfiller.external.atomic import (
    write_bytes_atomic,
    write_bytes_atomic_exclusive,
    write_text_atomic,
)


def _tmp_leftovers(directory) -> "list[str]":
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


# ------------------------------------------------------------------ 성공 경로
def test_write_bytes_roundtrip(tmp_path):
    target = tmp_path / "f.bin"
    write_bytes_atomic(target, b"\x00\x01PK")
    assert target.read_bytes() == b"\x00\x01PK"
    assert _tmp_leftovers(tmp_path) == []


def test_write_text_roundtrip_utf8_korean(tmp_path):
    target = tmp_path / "f.json"
    write_text_atomic(target, '{"공고명": "관급자재"}')
    assert target.read_text(encoding="utf-8") == '{"공고명": "관급자재"}'


def test_overwrite_replaces_existing(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("이전", encoding="utf-8")
    write_text_atomic(target, "새 내용")
    assert target.read_text(encoding="utf-8") == "새 내용"


# ------------------------------------------------------------------ no-clobber(S6-04 · #811)
def test_exclusive_write_creates_when_absent(tmp_path):
    target = tmp_path / "새문서.hwpx"
    write_bytes_atomic_exclusive(target, b"PK\x03\x04")
    assert target.read_bytes() == b"PK\x03\x04"
    assert _tmp_leftovers(tmp_path) == []


def test_exclusive_write_refuses_existing_and_keeps_it_intact(tmp_path):
    """관찰과 쓰기 사이에 생긴 파일은 조용히 파괴되지 않는다 — 생성 자체가 검사다."""
    target = tmp_path / "충돌.hwpx"
    target.write_bytes(b"interloper")
    with pytest.raises(FileExistsError):
        write_bytes_atomic_exclusive(target, b"NEW")
    assert target.read_bytes() == b"interloper"  # 기존 파일 무손상
    assert _tmp_leftovers(tmp_path) == []        # 잔해 없음


def test_exclusive_write_failure_cleans_tmp(tmp_path, monkeypatch):
    """이동 단계 실패 — 임시 파일 정리 + 예외 전파(부분 산출물 0)."""
    target = tmp_path / "f.hwpx"

    def _boom(src, dst):
        raise OSError(5, "I/O error")

    monkeypatch.setattr("hwpxfiller.external.atomic.os.rename", _boom)
    with pytest.raises(OSError):
        write_bytes_atomic_exclusive(target, b"NEW")
    assert not target.exists()
    assert _tmp_leftovers(tmp_path) == []


# ------------------------------------------------------------------ 실패 주입
def test_failed_write_preserves_existing_and_cleans_tmp(tmp_path, monkeypatch):
    """쓰기 도중 ENOSPC — 기존 파일 무손상 + 임시 파일 정리 + 예외 전파."""
    target = tmp_path / "f.json"
    target.write_text("기존 durable 내용", encoding="utf-8")

    class _EnospcFile:
        """ENOSPC 를 흉내내는 파일 핸들 — fd 는 닫아 잔해 unlink 가 가능하게."""

        def __init__(self, fd):
            self._fd = fd

        def __enter__(self):
            return self

        def __exit__(self, *args):
            os.close(self._fd)
            return False

        def write(self, data):
            raise OSError(28, "No space left on device")

    monkeypatch.setattr("hwpxfiller.external.atomic.os.fdopen", lambda fd, mode: _EnospcFile(fd))
    with pytest.raises(OSError):
        write_text_atomic(target, "새 내용" * 100)
    assert target.read_text(encoding="utf-8") == "기존 durable 내용"  # 무손상
    assert _tmp_leftovers(tmp_path) == []                              # 잔해 없음


def test_failed_replace_preserves_existing_and_cleans_tmp(tmp_path, monkeypatch):
    """교체 단계 실패 — 기존 파일 무손상 + 임시 파일 정리 + 예외 전파."""
    target = tmp_path / "f.json"
    target.write_text("기존", encoding="utf-8")

    def _boom(src, dst):
        raise OSError(5, "I/O error")

    monkeypatch.setattr("hwpxfiller.external.atomic.os.replace", _boom)
    with pytest.raises(OSError):
        write_bytes_atomic(target, b"NEW")
    assert target.read_text(encoding="utf-8") == "기존"
    assert _tmp_leftovers(tmp_path) == []
