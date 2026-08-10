"""Job 레지스트리의 프로세스 writer lease — Windows named mutex/POSIX flock/PID 소유권(P2-21, #569).

지원 topology 는 **한 작업 디렉터리당 writer 프로세스 하나**다(#192). 이 모듈은 그 계약의
OS 자원 획득·해제(named mutex·flock 파일·PID 판정)를 지는 Host 조립부이고,
:class:`~hwpxfiller.external.job_store.JobRegistry` 가 디렉터리별 공유 상태를
:func:`shared_write_state` 로 받아 첫 writer 진입 때 소유권을 확인한다.
:mod:`hwpxfiller.core.job` 에서 P2-21(#569)로 원문 이동했다.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import threading
import weakref
from pathlib import Path


class JobRegistryOwnershipError(RuntimeError):
    """다른 프로세스가 같은 작업 디렉터리의 writer 소유권을 가진 경우."""


class _RegistryWriteState:
    """한 프로세스 안에서 디렉터리별로 공유하는 스레드·프로세스 쓰기 상태."""

    def __init__(self, key: str):
        self.key = key
        self.lock = threading.RLock()
        self._owner: object | None = None
        self._owner_pid: "int | None" = None

    def claim_process_ownership(self) -> None:
        # 소유권은 **프로세스** 단위 계약이다(#234 리뷰) — POSIX fork 자식은 ``_owner`` 를
        # 그대로 상속해 조기 반환으로 원 writer 행세할 수 있었다(RLock 은 프로세스-로컬이라
        # 부모·자식이 무경보 동시 쓰기). 획득 시점 PID 를 기록하고, PID 가 다르면 상속분
        # 참조를 끊고(닫지 않는다 — flock OFD 는 부모와 공유라 닫으면 부모 락을 건드린다)
        # 새로 획득을 시도한다: 부모가 살아 있으면 flock 이 막혀 시끄럽게 거부된다.
        if self._owner is not None and self._owner_pid == os.getpid():
            return
        self._owner = None
        if sys.platform == "win32":
            self._claim_windows_mutex()
        else:
            self._claim_posix_lock()
        self._owner_pid = os.getpid()

    def _claim_windows_mutex(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        digest = hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:24]
        handle = kernel32.CreateMutexW(None, False, f"hwpx-job-registry-writer-{digest}")
        error = ctypes.get_last_error()
        if not handle:
            raise JobRegistryOwnershipError(
                f"작업 저장소 writer 소유권을 확인할 수 없습니다 (WinError {error})."
            )
        if error == 183:  # ERROR_ALREADY_EXISTS — 다른 프로세스의 writer가 생존 중.
            kernel32.CloseHandle(handle)
            raise JobRegistryOwnershipError(
                "이 작업 저장소는 이미 다른 문서나르미 프로세스가 쓰고 있습니다. "
                "기존 앱을 닫은 뒤 다시 시도하세요."
            )
        self._owner = handle

    def _claim_posix_lock(self) -> None:
        import fcntl

        lock_root = Path(tempfile.gettempdir()) / "hwpx-tools-job-locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:24]
        stream = (lock_root / f"{digest}.lock").open("a+b")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise JobRegistryOwnershipError(
                "이 작업 저장소는 이미 다른 문서나르미 프로세스가 쓰고 있습니다. "
                "기존 앱을 닫은 뒤 다시 시도하세요."
            ) from exc
        self._owner = stream

    def __del__(self) -> None:
        owner = self._owner
        if owner is None:
            return
        try:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes

                close = ctypes.WinDLL("kernel32").CloseHandle
                close.argtypes = [wintypes.HANDLE]
                close.restype = wintypes.BOOL
                close(owner)
            else:
                owner.close()  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass


class _OwnedWriteLock:
    """RLock 호환 표면 + 첫 writer의 프로세스 소유권 확인."""

    def __init__(self, state: _RegistryWriteState):
        self._state = state

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        acquired = (
            self._state.lock.acquire(blocking)
            if timeout == -1
            else self._state.lock.acquire(blocking, timeout)
        )
        if not acquired:
            return False
        try:
            self._state.claim_process_ownership()
        except Exception:
            self._state.lock.release()
            raise
        return True

    def release(self) -> None:
        self._state.lock.release()

    def __enter__(self) -> "_OwnedWriteLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


_JOB_WRITE_STATES: "weakref.WeakValueDictionary[str, _RegistryWriteState]" = (
    weakref.WeakValueDictionary()
)
_JOB_WRITE_STATES_GUARD = threading.Lock()


def _directory_key(directory: Path) -> str:
    try:
        directory = directory.resolve()
    except OSError:
        pass
    return os.path.normcase(os.path.abspath(os.fspath(directory)))


def shared_write_state(directory: Path) -> _RegistryWriteState:
    key = _directory_key(directory)
    with _JOB_WRITE_STATES_GUARD:
        state = _JOB_WRITE_STATES.get(key)
        if state is None:
            state = _RegistryWriteState(key)
            _JOB_WRITE_STATES[key] = state
        return state
