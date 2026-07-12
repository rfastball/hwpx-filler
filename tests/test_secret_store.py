"""비밀 저장소 + ServiceKey 마스킹(redaction) 코어 테스트 — N1 보안 유닛.

핵심 불변식: ServiceKey 는 (1) OS 자격증명 저장소에만 영속되고, (2) URL·예외·로그 어디서도
``[REDACTED]`` 로 전면 마스킹되며, (3) 프로파일/작업 JSON 직렬화 경로엔 절대 실리지 않는다.

실 OS 자격증명 저장소는 건드리지 않는다 — :class:`MemorySecretStore` 를 직접 주입하고,
실 CredWrite/CredRead 왕복은 win32 에서만(throwaway 타깃, finally 정리) 스킵-게이트로 돈다.
"""

from __future__ import annotations

import sys
import urllib.parse
import uuid

import pytest

from hwpxfiller.core.job import Job
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.data.nara import NaraStdDataSource
from hwpxfiller.data.secret_store import (
    NARA_SERVICE_KEY_NAME,
    REDACTED,
    WINDOWS_NARA_TARGET,
    MemorySecretStore,
    SecretStore,
    SecretStoreUnsupported,
    UnsupportedSecretStore,
    _decode_blob,
    _encode_blob,
    default_secret_store,
    redact,
    redact_url,
    windows_target_name,
)

# base64-ish 실제 data.go.kr 키 형태(+, /, = 포함) — 인코딩 경계를 자극한다.
KEY = "aB3+xY/z9Q==pLm4Kn7"


# ------------------------------------------------------------- 1. 저장소 왕복
def test_memory_store_round_trip():
    store = MemorySecretStore()
    assert store.get(NARA_SERVICE_KEY_NAME) is None
    assert store.has(NARA_SERVICE_KEY_NAME) is False

    store.set(NARA_SERVICE_KEY_NAME, KEY)
    assert store.get(NARA_SERVICE_KEY_NAME) == KEY
    assert store.has(NARA_SERVICE_KEY_NAME) is True

    # 대체(set again).
    store.set(NARA_SERVICE_KEY_NAME, "NEWKEY")
    assert store.get(NARA_SERVICE_KEY_NAME) == "NEWKEY"

    store.delete(NARA_SERVICE_KEY_NAME)
    assert store.get(NARA_SERVICE_KEY_NAME) is None
    assert store.has(NARA_SERVICE_KEY_NAME) is False
    # 없는 키 삭제는 멱등(오류 없음).
    store.delete(NARA_SERVICE_KEY_NAME)


def test_memory_store_satisfies_port():
    assert isinstance(MemorySecretStore(), SecretStore)


def test_unsupported_store_fails_loudly_on_write():
    store = UnsupportedSecretStore()
    # 읽기는 "없음"으로 정직하게 답한다(환경변수·파일로 폴백 가능).
    assert store.get(NARA_SERVICE_KEY_NAME) is None
    assert store.has(NARA_SERVICE_KEY_NAME) is False
    # 저장 시도는 조용히 속이지 않고 시끄럽게 실패한다.
    with pytest.raises(SecretStoreUnsupported):
        store.set(NARA_SERVICE_KEY_NAME, KEY)


def test_default_store_selector():
    store = default_secret_store()
    if sys.platform == "win32":
        from hwpxfiller.data.secret_store import WindowsCredentialStore
        assert isinstance(store, WindowsCredentialStore)
    else:
        assert isinstance(store, UnsupportedSecretStore)


# ------------------------------------------------- 2. Windows 타깃명/인코딩
def test_windows_target_name_constant():
    assert WINDOWS_NARA_TARGET == "hwpx-tools/nara-service-key"
    assert windows_target_name(NARA_SERVICE_KEY_NAME) == WINDOWS_NARA_TARGET


def test_blob_encoding_round_trip():
    """UTF-16LE 블롭 인코딩이 +, /, = 를 포함한 키를 무손실 왕복(크로스플랫폼·헤르메틱)."""
    assert _decode_blob(_encode_blob(KEY)) == KEY
    # 빈 값·유니코드도 안전.
    assert _decode_blob(_encode_blob("")) == ""
    assert _decode_blob(_encode_blob("한글키🔑")) == "한글키🔑"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager 전용")
def test_windows_credential_store_real_round_trip():
    """실 CredWrite/CredRead/CredDelete 왕복 — throwaway 타깃, finally 로 반드시 정리."""
    from hwpxfiller.data.secret_store import WindowsCredentialStore

    store = WindowsCredentialStore()
    throwaway = f"nara-service-key-pytest-{uuid.uuid4().hex}"
    try:
        assert store.get(throwaway) is None
        store.set(throwaway, KEY)
        assert store.get(throwaway) == KEY
        assert store.has(throwaway) is True
        store.set(throwaway, "REPLACED")
        assert store.get(throwaway) == "REPLACED"
    finally:
        store.delete(throwaway)
    assert store.get(throwaway) is None
    store.delete(throwaway)  # 멱등.


# ----------------------------------------------------------------- 3. 마스킹
def test_redact_removes_raw_key_everywhere():
    url = f"https://apis.data.go.kr/x?ServiceKey={KEY}&type=json"
    exc_msg = f"HTTP Error 500: Internal Server Error for url {url}"
    log_line = f"요청 실패: 키={KEY} 재시도"
    for text in (url, exc_msg, log_line):
        out = redact(text, KEY)
        assert KEY not in out
        assert REDACTED in out


def test_redact_removes_percent_encoded_key():
    encoded = urllib.parse.quote(KEY, safe="")
    text = f"https://apis.data.go.kr/x?ServiceKey={encoded}&type=json"
    out = redact(text, KEY)
    assert encoded not in out
    assert KEY not in out
    assert REDACTED in out


def test_redact_by_param_name_without_known_key():
    """키 값을 주지 않아도 ServiceKey= 파라미터 값이 지워진다(값 미상 예외 대비)."""
    unknown = "someUnknownSecretValue12345"
    url = f"https://apis.data.go.kr/x?ServiceKey={unknown}&pageNo=1"
    out = redact(url)  # secret 미제공
    assert unknown not in out
    assert "ServiceKey=" + REDACTED in out
    # 다른 파라미터는 보존.
    assert "pageNo=1" in out


def test_redact_case_insensitive_param_variants():
    for name in ("serviceKey", "ServiceKey", "service_key", "SERVICE_KEY"):
        url = f"http://h/x?{name}=SEKRET&a=1"
        out = redact(url)
        assert "SEKRET" not in out
        assert REDACTED in out


def test_redact_url_helper_and_empty_inputs():
    assert redact_url("http://h/x?ServiceKey=zzz").endswith(f"ServiceKey={REDACTED}")
    assert redact("") == ""
    assert redact("아무 비밀 없음") == "아무 비밀 없음"


# -------------------------------------------------- 4. urlencode 후에도 마스킹
def test_redact_after_urlencode():
    """+, /, = 를 담은 키가 urlencode(quote_plus) 를 거쳐도 완전히 지워진다."""
    query = urllib.parse.urlencode({"ServiceKey": KEY, "type": "json"})
    url = f"https://apis.data.go.kr/x?{query}"
    # 키가 확실히 퍼센트인코딩됐는지 전제 확인.
    assert KEY not in url
    out = redact(url, KEY)
    assert REDACTED in out
    # 인코딩 잔여 조각도 남지 않아야 한다.
    assert urllib.parse.quote_plus(KEY) not in out
    assert urllib.parse.quote(KEY, safe="") not in out


# ------------------------------------- 6. 키가 직렬화 경로에 실리지 않음(불변식)
def test_service_key_absent_from_nara_datasource_diagnostics():
    """키를 실제로 보유하는 표면(``NaraStdDataSource.service_key``)의 진단 노출을 가드.

    유일한 영속 표면은 SecretStore 다. 소스 객체는 취득 동안 키를 들지만, repr/진단
    문자열로 새면 로그에 유출된다 — 기본 ``object.__repr__`` 은 속성을 안 보여 오늘은
    안전하나, 미래에 누출성 ``__repr__`` 이 추가되는 회귀를 이 가드가 잡는다.
    """
    src = NaraStdDataSource(service_key=KEY, bgn_dt="202606010000", end_dt="202606302359")
    # 기본 repr 은 속성을 노출하지 않는다 — 누출성 __repr__ 회귀를 이 가드가 잡는다.
    assert KEY not in repr(src)
    assert KEY not in str(src)
    # 주: 인스턴스 __dict__(vars) 는 취득에 쓰려 키를 정당하게 보유한다 — 그 자체는 누출
    # 표면이 아니다(로그에 vars() 를 찍지 않는 한). 누출 표면은 repr/직렬화다.


def test_service_key_never_serialized_in_profile_and_job(tmp_path):
    """프로파일·작업 JSON 직렬화 경로 어디에도 ServiceKey 가 실리지 않는다.

    유일한 영속 표면은 SecretStore 다. 매핑 프로파일과 작업(Job)을 왕복시켜 그 산출물에
    키 문자열이 부재함을 가드한다(직렬화가 키를 우연히 포획하지 않음을 문서화).
    """
    profile = MappingProfile(name="나라", mappings=[
        FieldMapping("입찰공고번호", ["bidNtceNo"]),
        FieldMapping("추정가격", ["presmptPrce"], transform="amount"),
    ])
    pf = tmp_path / "map.json"
    profile.save(pf)
    profile_text = pf.read_text(encoding="utf-8")
    assert KEY not in profile_text
    # to_dict 자체에도 없음.
    assert KEY not in repr(profile.to_dict())

    job = Job(name="공고작업", template_path="T.hwpx", mapping=profile,
              filename_pattern="n-{{입찰공고번호}}")
    jf = tmp_path / "job.json"
    job.save(jf)
    job_text = jf.read_text(encoding="utf-8")
    assert KEY not in job_text
    assert KEY not in repr(job.to_dict())

    # SecretStore 에 넣어도 그 값은 위 직렬화 산출물과 무관(별개 표면).
    store = MemorySecretStore()
    store.set(NARA_SERVICE_KEY_NAME, KEY)
    assert store.get(NARA_SERVICE_KEY_NAME) == KEY
    assert KEY not in profile_text and KEY not in job_text
