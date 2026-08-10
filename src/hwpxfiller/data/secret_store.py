"""비밀 저장소 포트와 concrete adapter — 나라장터 키의 안전 보관.

data.go.kr ServiceKey 는 **사용자별 비밀**이다. 하드코딩·프로파일/작업 JSON 직렬화·로그
어디에도 남지 않아야 하며, 저장이 필요하면 **OS 자격증명 저장소**(Windows Credential
Manager)에 사용자 스코프로 둔다. 이 모듈은 그 저장 축을 제공한다:

1. :class:`SecretStore` 포트 — ``get/set/delete/has`` 4메서드의 최소 인터페이스.
   - :class:`WindowsCredentialStore` — Win32 Credential Manager(``ctypes`` 만, 새 의존성 0).
   - :class:`MemorySecretStore` — 테스트 주입·비영속 개발용 인메모리 구현.
   - :class:`UnsupportedSecretStore` — 저장 불가 플랫폼에서 **조용히 속이지 않고** ``set``/
     ``delete`` 를 시끄럽게 실패시키는 폴백(``get``/``has`` 는 "저장된 키 없음"= None/False).
   - :func:`default_secret_store` — 플랫폼 선택기(win32 → 자격증명 저장소, 그 외 → Unsupported).

순수 마스킹 정책은 :mod:`hwpxfiller.domain.secret_redaction` 이 소유한다. 기존
``data.secret_store`` 소비자를 위해 ``REDACTED``·``redact``·``redact_url`` 은
그 정본 객체를 그대로 재수출한다.
"""

from __future__ import annotations

import sys
from typing import Protocol, runtime_checkable

from hwpxfiller.domain.secret_redaction import REDACTED, redact, redact_url

# --------------------------------------------------------------------- 상수
#: 논리적 비밀 이름(포트에 넘기는 키). Windows 타깃명·CLI 폴백이 공유하는 단일 출처.
NARA_SERVICE_KEY_NAME = "nara-service-key"

#: Windows Credential Manager Generic Credential 타깃명 접두어.
WINDOWS_TARGET_PREFIX = "hwpx-tools/"

#: 나라 ServiceKey 의 Windows 자격증명 타깃명(테스트가 검증하는 상수).
WINDOWS_NARA_TARGET = WINDOWS_TARGET_PREFIX + NARA_SERVICE_KEY_NAME


def windows_target_name(name: str) -> str:
    """논리 이름 → Windows 자격증명 타깃명(``hwpx-tools/<name>``)."""
    return WINDOWS_TARGET_PREFIX + name


# --------------------------------------------------------------------- 포트
@runtime_checkable
class SecretStore(Protocol):
    """비밀 저장소 최소 포트 — 논리 이름(str) ↔ 비밀값(str) 매핑.

    구현은 값을 **어디에도 평문 로그·직렬화하지 않는다.** 없는 키 조회는 ``None``,
    없는 키 삭제는 무연산(멱등)이다.
    """

    def get(self, name: str) -> "str | None":
        """저장된 값을 반환(없으면 ``None``)."""
        ...

    def set(self, name: str, value: str) -> None:
        """값을 저장(기존 값이 있으면 대체)."""
        ...

    def delete(self, name: str) -> None:
        """값을 삭제(없어도 오류 없이 무연산)."""
        ...

    def has(self, name: str) -> bool:
        """값 존재 여부."""
        ...


# ------------------------------------------------------------ 인메모리 구현
class MemorySecretStore:
    """인메모리 비밀 저장소 — 테스트 주입·비영속 개발용(프로세스 종료 시 소멸)."""

    def __init__(self, initial: "dict[str, str] | None" = None):
        self._data: "dict[str, str]" = dict(initial or {})

    def get(self, name: str) -> "str | None":
        return self._data.get(name)

    def set(self, name: str, value: str) -> None:
        self._data[name] = value

    def delete(self, name: str) -> None:
        self._data.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._data


# --------------------------------------------------------- 미지원 폴백 구현
class SecretStoreUnsupported(RuntimeError):
    """이 플랫폼에서 비밀 저장이 불가함을 알리는 시끄러운 실패."""


class UnsupportedSecretStore:
    """저장 불가 플랫폼용 폴백 — 조용히 속이지 않고 저장 시도를 시끄럽게 실패시킨다.

    ``get``/``has`` 는 "저장된 키 없음"= ``None``/``False`` 로 정직하게 답한다(그래서 CLI 는
    환경변수·파일 소스로 자연히 폴백). ``set``/``delete`` 는 :class:`SecretStoreUnsupported`
    로 실패해 "여기엔 못 담는다"를 사용자에게 명시한다(암묵적 비영속 착각 방지).
    """

    def __init__(self, reason: str = "이 플랫폼엔 OS 자격증명 저장소 연동이 없습니다"):
        self._reason = reason

    def get(self, name: str) -> "str | None":
        return None

    def set(self, name: str, value: str) -> None:
        raise SecretStoreUnsupported(
            f"{self._reason}. DATA_GO_KR_KEY 환경변수나 --service-key-file 을 쓰세요."
        )

    def delete(self, name: str) -> None:
        raise SecretStoreUnsupported(self._reason)

    def has(self, name: str) -> bool:
        return False


# ----------------------------------------------------- Windows 자격증명 구현
# UTF-16LE 블롭 인코딩(Credential Manager 는 임의 바이트 블롭; 키를 UTF-16LE 로 담는다).
def _encode_blob(value: str) -> bytes:
    return value.encode("utf-16-le")


def _decode_blob(data: bytes) -> str:
    return data.decode("utf-16-le")


class WindowsCredentialStore:
    """Windows Credential Manager Generic Credential 백엔드(``ctypes`` — 새 의존성 0).

    타깃명은 ``hwpx-tools/<name>``(사용자 자격증명 볼트에 저장되어 **현재 Windows 사용자
    스코프**). ``CRED_TYPE_GENERIC`` + ``CRED_PERSIST_LOCAL_MACHINE``(로밍 없이 이 머신의
    현재 사용자에 영속). 블롭은 UTF-16LE 인코딩한 키.
    """

    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2
    _ERROR_NOT_FOUND = 1168

    def __init__(self, target_prefix: str = WINDOWS_TARGET_PREFIX):
        self._prefix = target_prefix

    def _target(self, name: str) -> str:
        return self._prefix + name

    # -- ctypes 바인딩(지연 로드 — win32 아닌 곳에서 import 시 advapi32 접근 안 함) --
    @staticmethod
    def _bindings():
        import ctypes
        from ctypes import wintypes

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        class FILETIME(ctypes.Structure):
            _fields_ = [
                ("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD),
            ]

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        pcred = ctypes.POINTER(CREDENTIAL)
        advapi32.CredWriteW.argtypes = [pcred, wintypes.DWORD]
        advapi32.CredWriteW.restype = wintypes.BOOL
        advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pcred),
        ]
        advapi32.CredReadW.restype = wintypes.BOOL
        advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        advapi32.CredDeleteW.restype = wintypes.BOOL
        advapi32.CredFree.argtypes = [ctypes.c_void_p]
        advapi32.CredFree.restype = None
        return ctypes, advapi32, CREDENTIAL, pcred

    def get(self, name: str) -> "str | None":
        ctypes_mod, advapi32, _cred, pcred = self._bindings()
        ptr = pcred()
        ok = advapi32.CredReadW(
            self._target(name), self._CRED_TYPE_GENERIC, 0, ctypes_mod.byref(ptr)
        )
        if not ok:
            err = ctypes_mod.get_last_error()
            if err == self._ERROR_NOT_FOUND:
                return None
            raise OSError(err, f"CredReadW 실패(코드 {err})")
        try:
            cred = ptr.contents
            size = int(cred.CredentialBlobSize)
            if size == 0:
                return ""
            data = ctypes_mod.string_at(cred.CredentialBlob, size)
            return _decode_blob(data)
        finally:
            advapi32.CredFree(ptr)

    def set(self, name: str, value: str) -> None:
        ctypes_mod, advapi32, cred_type, _pcred = self._bindings()
        blob = _encode_blob(value)
        cred = cred_type()
        cred.Type = self._CRED_TYPE_GENERIC
        cred.TargetName = self._target(name)
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes_mod.cast(
            ctypes_mod.c_char_p(blob), ctypes_mod.POINTER(ctypes_mod.c_char)
        )
        cred.Persist = self._CRED_PERSIST_LOCAL_MACHINE
        ok = advapi32.CredWriteW(ctypes_mod.byref(cred), 0)
        if not ok:
            err = ctypes_mod.get_last_error()
            raise OSError(err, f"CredWriteW 실패(코드 {err})")

    def delete(self, name: str) -> None:
        ctypes_mod, advapi32, _cred, _pcred = self._bindings()
        ok = advapi32.CredDeleteW(self._target(name), self._CRED_TYPE_GENERIC, 0)
        if not ok:
            err = ctypes_mod.get_last_error()
            if err == self._ERROR_NOT_FOUND:
                return  # 멱등 삭제.
            raise OSError(err, f"CredDeleteW 실패(코드 {err})")

    def has(self, name: str) -> bool:
        return self.get(name) is not None


# ------------------------------------------------------------------ 선택기
def default_secret_store() -> SecretStore:
    """플랫폼 기본 비밀 저장소 — win32 → Credential Manager, 그 외 → 시끄러운 미지원 폴백.

    테스트는 이 팩토리를 거치지 않고 :class:`MemorySecretStore` 를 직접 주입한다(실 저장소
    무접촉).
    """
    if sys.platform == "win32":
        return WindowsCredentialStore()
    return UnsupportedSecretStore()
