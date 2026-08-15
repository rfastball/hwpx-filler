"""stable exact-byte 파일 capture 어댑터 (S3-02 #652).

pinned source 파일에서 exact bytes 를 읽되, **mtime+size 만으로 안정성을 주장하지 않는다**.
capture 는 파일 handle 을 열고 그 handle 의 identity 를 read 전후로 비교하며, 경로가 여전히
같은 file object 를 가리키는지(atomic replacement 검출)와 source binding generation 을
재확인한다. 안정성 판정은 순수 함수 :func:`classify_capture_stability` 가 지고, 어댑터는 실제
``os.fstat``/``os.stat``/``os.read`` 와 그 판정을 잇는 얇은 host 경계다.

버그는 stat 기계가 아니라 판정 논리에 산다 — 그래서 판정을 순수 함수로 갈라 fabricated
identity 로 전 음성 경계를 결정론적·cross-platform 으로 검사하고, 어댑터는 실 FS 로 happy
path 와 한 개의 간섭 사례만 확인한다.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from hwpxfiller.application.candidate_revision import (
    SOURCE_BINDING_CHANGED,
    SOURCE_CAPTURE_ERROR,
    CaptureResult,
    MutableSourceBinding,
    SourceCaptureError,
    StableCapture,
    blob_digest,
)

_READ_CHUNK = 1 << 20


@dataclass(frozen=True)
class FileIdentity:
    """capture 안정성 판정에 쓰는 file object identity(mtime 단독이 아니다)."""

    ino: int
    dev: int
    size: int
    mtime_ns: int


def file_identity(stat: os.stat_result) -> FileIdentity:
    return FileIdentity(stat.st_ino, stat.st_dev, stat.st_size, stat.st_mtime_ns)


def classify_capture_stability(
    *,
    pre: FileIdentity,
    post: FileIdentity,
    on_path: FileIdentity,
    expected_generation: int,
    probed_generation: int,
) -> str | None:
    """capture 가 불안정하면 error reason, 안정하면 ``None`` 을 낸다(순수)."""
    if pre != post:
        return SOURCE_CAPTURE_ERROR  # read 도중 파일이 변경됨(truncate/write)
    if (on_path.ino, on_path.dev) != (post.ino, post.dev):
        return SOURCE_CAPTURE_ERROR  # 경로가 다른 file object 를 가리킴(atomic replacement)
    if probed_generation != expected_generation:
        return SOURCE_BINDING_CHANGED  # source binding 이 재-pin 됨
    return None


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        block = os.read(fd, _READ_CHUNK)
        if not block:
            break
        chunks.append(block)
    return b"".join(chunks)


class FileTemplateSourceReader:
    """pinned 파일에서 안정된 exact bytes 를 읽는 :data:`TemplateSourceReader` 구현.

    ``probe_generation`` 은 source_binding_id 로 현재 generation 을 되읽는다(재-pin 검출).
    ``interference`` 는 테스트 전용 seam — read 직후 파일을 바꿔 불안정 경로를 결정론적으로
    재현한다(운영 기본값 None).
    """

    def __init__(
        self,
        probe_generation: Callable[[str], int],
        *,
        interference: Callable[[], None] | None = None,
    ) -> None:
        self._probe = probe_generation
        self._interference = interference

    def __call__(self, binding: MutableSourceBinding) -> CaptureResult:
        path = os.fspath(binding.host_reference)
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        except OSError:
            return SourceCaptureError(SOURCE_CAPTURE_ERROR)
        try:
            pre = file_identity(os.fstat(fd))
            data = _read_all(fd)
            if self._interference is not None:
                self._interference()
            post = file_identity(os.fstat(fd))
            # ponytail: open read handle 을 쥔 동안 Windows 는 경로 rename/replace/delete 를
            # 막으므로 os.stat 은 실패하지 않는다(atomic-replace 판정은 POSIX 용이고 순수
            # classifier 가 검사한다). exotic env 의 OSError 는 조용히 삼키지 않고 fail-loud.
            on_path = file_identity(os.stat(path))
            reason = classify_capture_stability(
                pre=pre,
                post=post,
                on_path=on_path,
                expected_generation=binding.generation,
                probed_generation=self._probe(binding.source_binding_id),
            )
        finally:
            os.close(fd)
        if reason is not None:
            return SourceCaptureError(reason)
        return StableCapture(
            exact_bytes=data,
            captured_content_digest=blob_digest(data),
            source_binding_id=binding.source_binding_id,
            source_binding_generation=binding.generation,
            capture_method="file-handle-stable",
            observed_metadata={"byte_length": len(data), "mtime_ns": post.mtime_ns},
        )
