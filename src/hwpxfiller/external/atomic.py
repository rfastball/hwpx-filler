"""원자 파일 쓰기 — 같은 볼륨 임시 파일에 기록 후 ``os.replace`` 로 교체.

truncate-then-write(``open('w'/'wb')`` 로 최종 경로 직접 기록)는 쓰기 도중 실패
(디스크풀·강제종료·네트워크 드라이브 오류)가 **기존 파일을 먼저 파괴**한다.
저장소의 durable 쓰기(HWPX 산출물·작업 JSON·매핑·원장·리포트)는 전부 이 헬퍼를
지난다: 페이로드를 임시 파일에 완성한 뒤 원자 교체하므로, 어느 단계에서 실패해도
기존 파일은 무손상으로 남고 실패는 예외로 시끄럽게 올라간다(확인-또는-경보).

durable 파일 쓰기는 External Adapter 경계가 소유한다.
"""

from __future__ import annotations

import os
import tempfile


def write_bytes_atomic(path: "str | os.PathLike[str]", data: bytes) -> None:
    """``data`` 를 임시 파일에 완성한 뒤 ``path`` 로 원자 교체한다.

    임시 파일은 대상과 **같은 디렉터리**에 만든다 — ``os.replace`` 는 같은 볼륨
    안에서만 원자적이다. 쓰기·교체 어느 단계가 실패해도 임시 파일을 치우고 예외를
    그대로 올린다(기존 파일 무손상, 잔해 없음).
    """
    path = os.fspath(path)
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_bytes_atomic_exclusive(path: "str | os.PathLike[str]", data: bytes) -> None:
    """``data`` 를 임시 파일에 완성한 뒤 **비어 있는** ``path`` 로만 원자 이동한다(no-clobber).

    :func:`write_bytes_atomic` 의 ``os.replace`` 는 무조건 덮어쓴다 — 「이 이름은 관찰 시점에
    비어 있었다」는 계획(WRITE_NEW·WRITE_ADD_SUFFIX)을 그것으로 집행하면 관찰과 쓰기 사이에
    생긴 파일을 조용히 파괴한다(S6-04 · #811). 이 함수는 ``os.rename`` 을 쓴다 — Windows 는
    대상이 존재하면 :class:`FileExistsError` 로 거절하므로, 재관찰-후-쓰기의 경쟁 창 없이
    「생성 자체가 검사」다. 대상이 이미 있으면 기존 파일은 무손상으로 남고 임시 파일은
    치워지며 예외가 그대로 올라간다(확인-또는-경보).
    """
    path = os.fspath(path)
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.rename(tmp, path)  # 대상 존재 시 FileExistsError — no-clobber 원자 이동
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_text_atomic(
    path: "str | os.PathLike[str]", text: str, encoding: str = "utf-8"
) -> None:
    """텍스트판 — ``text`` 를 인코딩해 :func:`write_bytes_atomic` 으로 저장한다."""
    write_bytes_atomic(path, text.encode(encoding))
