"""원자 파일 쓰기 — 같은 볼륨 임시 파일에 기록 후 ``os.replace`` 로 교체.

truncate-then-write(``open('w'/'wb')`` 로 최종 경로 직접 기록)는 쓰기 도중 실패
(디스크풀·강제종료·네트워크 드라이브 오류)가 **기존 파일을 먼저 파괴**한다.
저장소의 durable 쓰기(HWPX 산출물·작업 JSON·매핑·원장·리포트)는 전부 이 헬퍼를
지난다: 페이로드를 임시 파일에 완성한 뒤 원자 교체하므로, 어느 단계에서 실패해도
기존 파일은 무손상으로 남고 실패는 예외로 시끄럽게 올라간다(확인-또는-경보).

hwpxdiff·hwpxfiller 양쪽이 쓰므로 공유 지점인 hwpxcore 에 둔다(제품 로직 없음).
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


def write_text_atomic(
    path: "str | os.PathLike[str]", text: str, encoding: str = "utf-8"
) -> None:
    """텍스트판 — ``text`` 를 인코딩해 :func:`write_bytes_atomic` 으로 저장한다."""
    write_bytes_atomic(path, text.encode(encoding))
