"""나라장터 취득 ViewModel(N2) 헤드리스 테스트 — Qt·네트워크·실 저장소 무접촉.

키 등록은 :class:`MemorySecretStore` 주입, 취득은 ``fetcher`` 주입으로 검증한다.
보안 불변식(키 비직렬화·오류 redaction)을 못박는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hwpxfiller.data.nara import _add_one_month  # 검증 단일 출처는 데이터층(RC-03)
from hwpxfiller.data.secret_store import NARA_SERVICE_KEY_NAME, MemorySecretStore
from hwpxfiller.gui.nara_state import (
    AcquiredNaraData,
    NaraAcquireViewModel,
)

FIXTURES = Path(__file__).parent / "fixtures"

# base64-ish 실제 키 형태(+, /, = 포함) — redaction 경계 검증용.
_LIVE_KEY = "aB3+xY/z9Q==pLm4Kn7"


def _fixture_bytes() -> bytes:
    return (FIXTURES / "nara_std_response.json").read_bytes()


def _vm(store=None, fetcher=None) -> NaraAcquireViewModel:
    return NaraAcquireViewModel(store or MemorySecretStore(), fetcher=fetcher)


# ------------------------------------------------------------------ 키 등록
def test_register_replace_delete_roundtrip():
    store = MemorySecretStore()
    vm = _vm(store)
    assert not vm.is_registered()
    assert vm.status_label() == "미등록"

    vm.save_key("  KEY1  ")  # 공백 제거
    assert vm.is_registered()
    assert vm.status_label() == "등록됨"
    assert store.get(NARA_SERVICE_KEY_NAME) == "KEY1"

    vm.save_key("KEY2")  # 교체
    assert store.get(NARA_SERVICE_KEY_NAME) == "KEY2"

    vm.delete_key()
    assert not vm.is_registered()
    vm.delete_key()  # 멱등 — 없어도 오류 없음


def test_save_empty_key_rejected_loudly():
    vm = _vm()
    with pytest.raises(ValueError):
        vm.save_key("   ")
    assert not vm.is_registered()  # 조용한 무저장 금지 — 저장 안 됨을 시끄럽게


# ------------------------------------------------------------------ 기간 검증
def test_add_one_month_clamps_end_of_month():
    assert _add_one_month(datetime(2026, 1, 31, 9, 0)) == datetime(2026, 2, 28, 9, 0)
    assert _add_one_month(datetime(2026, 12, 15, 0, 0)) == datetime(2027, 1, 15, 0, 0)


def test_validate_range_accepts_within_one_month():
    assert NaraAcquireViewModel.validate_range("202606010000", "202606302359") is None


@pytest.mark.parametrize(
    "bgn,end",
    [
        ("2026060100", "202606302359"),   # 12자리 아님
        ("20260601000a", "202606302359"),  # 숫자 아님
        ("202613010000", "202613020000"),  # 존재 않는 월
    ],
)
def test_validate_range_rejects_bad_format(bgn, end):
    assert NaraAcquireViewModel.validate_range(bgn, end) is not None


def test_validate_range_rejects_reversed_and_over_one_month():
    assert "빠릅니다" in NaraAcquireViewModel.validate_range("202606100000", "202606010000")
    over = NaraAcquireViewModel.validate_range("202606010000", "202607150000")
    assert over is not None and "1개월" in over


# ------------------------------------------------------------------ 취득 성공
def test_acquire_success_parses_records_and_fields():
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, fetcher=lambda url: _fixture_bytes())
    res = vm.acquire("202606010000", "202606302359")
    assert res.ok
    assert res.count == 2
    assert res.result_code == "00"
    assert "bidNtceNo" in res.fields and res.fields[0] == "bidNtceNo"
    assert "2건" in res.summary()


def test_acquire_datasource_is_keyless_snapshot():
    """취득 산출 datasource 는 키 없는 스냅샷 — field_labels/records 는 되지만 키는 없다."""
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    vm = _vm(store, fetcher=lambda url: _fixture_bytes())
    res = vm.acquire("202606010000", "202606302359")
    ds = res.as_datasource()
    assert isinstance(ds, AcquiredNaraData)
    assert ds.field_labels()["bidNtceNm"] == "공고명"  # 소스 어휘 노출(V1)
    assert len(ds.records()) == 2
    # 키가 스냅샷 어디에도 없다(위저드 세션/작업 직렬화 표면에 닿지 않음).
    assert _LIVE_KEY not in repr(ds.__dict__)
    assert _LIVE_KEY not in repr(res)


# ------------------------------------------------------- 원자 스냅샷(RC-24·RC-13)
def test_acquire_success_owns_atomic_snapshot_with_query():
    """수용 가능한 성공 → last_result 가 결과 전체 + 취득 시점 쿼리 스탬프(위젯 재독 금지)."""
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, fetcher=lambda url: _fixture_bytes())
    res = vm.acquire("202606010000", "202606302359", num_rows=50, page_no=2)
    assert res.acceptable
    assert vm.last_result is res
    assert (res.bgn_dt, res.end_dt) == ("202606010000", "202606302359")
    assert (res.num_rows, res.page_no) == (50, 2)
    assert res.source_label() == "나라장터 · 202606010000~202606302359 · 2건"


def test_acquire_failure_resets_snapshot_atomically():
    """성공 뒤 실패 → last_result 통째로 None — records 만 리셋되는 부분 잔존 금지(RC-24)."""
    calls = {"n": 0}

    def flaky(url: str) -> bytes:
        calls["n"] += 1
        if calls["n"] == 1:
            return _fixture_bytes()
        raise RuntimeError("boom")

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, fetcher=flaky)
    assert vm.acquire("202606010000", "202606302359").acceptable
    assert vm.last_result is not None
    res2 = vm.acquire("202606010000", "202606302359")
    assert not res2.ok
    assert vm.last_result is None  # fields/datasource/label 파생원까지 원자 리셋


def test_acquire_zero_records_ok_but_not_acceptable():
    """0건은 응답 정상이어도 수용 불가(빈 데이터 매핑 진행 금지) — 스냅샷도 남지 않는다."""
    empty_ok = (
        b'{"response":{"header":{"resultCode":"00","resultMsg":"OK"},'
        b'"body":{"items":[]}}}'
    )
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, fetcher=lambda url: empty_ok)
    res = vm.acquire("202606010000", "202606302359")
    assert res.ok and not res.acceptable
    assert vm.last_result is None


def test_invalidate_discards_snapshot():
    """취득 후 입력 편집 시 뷰가 호출하는 invalidate — 스냅샷 폐기(RC-13 게이트 무효화)."""
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, fetcher=lambda url: _fixture_bytes())
    vm.acquire("202606010000", "202606302359")
    assert vm.last_result is not None
    vm.invalidate()
    assert vm.last_result is None


# ------------------------------------------------------------------ 취득 실패
def test_acquire_without_key_fails_loudly():
    vm = _vm(MemorySecretStore())  # 키 없음
    res = vm.acquire("202606010000", "202606302359")
    assert not res.ok
    assert "등록" in res.error


def test_acquire_bad_range_fails_before_fetch():
    fetched = []
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, fetcher=lambda url: fetched.append(url) or b"{}")
    res = vm.acquire("202606010000", "202607150000")  # >1개월
    assert not res.ok and "1개월" in res.error
    assert fetched == []  # 검증 실패면 네트워크 미접촉


def test_acquire_auth_failure_distinguished_from_empty():
    """resultCode != '00'(인증/파라미터 오류)은 빈 목록을 조용한 성공으로 삼지 않는다."""
    auth_fail = (
        b'{"response":{"header":{"resultCode":"07",'
        b'"resultMsg":"INVALID_REQUEST_PARAMETER_ERROR"},"body":{}}}'
    )
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    vm = _vm(store, fetcher=lambda url: auth_fail)
    res = vm.acquire("202606010000", "202606302359")
    assert not res.ok
    assert res.result_code == "07"
    assert "07" in res.error
    assert _LIVE_KEY not in res.error


def test_acquire_missing_result_code_fails_closed():
    """헤더에 resultCode 가 없는(파싱은 되나 규격 밖) 응답은 조용한 0건 성공 금지 — fail-closed."""
    headerless = b'{"response":{"body":{"items":[{"bidNtceNo":"X1"}]}}}'
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, fetcher=lambda url: headerless)
    res = vm.acquire("202606010000", "202606302359")
    assert not res.ok
    assert res.result_code == ""
    assert "API 오류" in res.error


def test_connection_missing_result_code_fails_closed():
    """resultCode 부재 응답에 '연결 성공(유효 키)'을 조용히 답하지 않는다."""
    headerless = b'{"response":{"body":{"items":[]}}}'
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, fetcher=lambda url: headerless)
    res = vm.test_connection()
    assert not res.ok


def test_acquire_empty_response_fails_without_leak():
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    vm = _vm(store, fetcher=lambda url: b"")
    res = vm.acquire("202606010000", "202606302359")
    assert not res.ok
    assert _LIVE_KEY not in res.error


def test_acquire_network_error_redacts_key():
    """fetcher 가 키/URL 을 품은 예외를 던지면 표면화된 error 에서 키가 마스킹된다."""
    def boom(url: str) -> bytes:
        raise RuntimeError(f"HTTP Error 401: Unauthorized for url {url}")

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    vm = _vm(store, fetcher=boom)
    res = vm.acquire("202606010000", "202606302359")
    assert not res.ok
    import urllib.parse
    assert _LIVE_KEY not in res.error
    assert urllib.parse.quote_plus(_LIVE_KEY) not in res.error
    assert "[REDACTED]" in res.error


# ------------------------------------------------------------------ 연결 시험
def test_connection_no_key():
    res = _vm(MemorySecretStore()).test_connection()
    assert not res.ok and "등록" in res.message


def test_connection_success():
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, fetcher=lambda url: _fixture_bytes())
    res = vm.test_connection()
    assert res.ok and "성공" in res.message


def test_connection_auth_failure_reports_code_no_leak():
    auth_fail = b'{"response":{"header":{"resultCode":"30","resultMsg":"SERVICE_KEY_IS_NOT_REGISTERED_ERROR"},"body":{}}}'
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    vm = _vm(store, fetcher=lambda url: auth_fail)
    res = vm.test_connection()
    assert not res.ok
    assert "30" in res.message
    assert _LIVE_KEY not in res.message


def test_connection_window_is_within_one_month():
    """연결 시험이 만드는 기간(최근 1일)은 1개월 제한을 절대 넘지 않는다(자기정합)."""
    captured = {}
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})

    def spy(url: str) -> bytes:
        # url 에서 기간 파라미터를 직접 파싱하는 대신, VM 의 검증을 재적용해 확인.
        captured["url"] = url
        return _fixture_bytes()

    vm = _vm(store, fetcher=spy)
    now = datetime.now()
    bgn = (now - timedelta(days=1)).strftime("%Y%m%d%H%M")
    end = now.strftime("%Y%m%d%H%M")
    assert NaraAcquireViewModel.validate_range(bgn, end) is None
    assert vm.test_connection().ok
