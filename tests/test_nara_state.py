"""나라장터 취득 Application 상태의 순수 owner.

비밀 저장소와 gateway, clock을 모두 주입해 OS credential·실네트워크·wall clock을
사용하지 않는다. JSON/HTTP/redaction 구현은 ``tests/test_nara.py``가 별도로 소유한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from hwpxfiller.application.nara_acquire import (
    AcquiredNaraData,
    AcquireResult,
    NaraAcquireViewModel,
    NaraGatewayError,
    NaraGatewayResponse,
    _add_one_month,
)
from hwpxfiller.data.secret_store import NARA_SERVICE_KEY_NAME, MemorySecretStore

_LIVE_KEY = "aB3+xY/z9Q==pLm4Kn7"
_FIXED_NOW = datetime(2026, 6, 30, 12, 34)
_RECORDS = [
    {"bidNtceNo": "R26BK01561738", "bidNtceNm": "사무용 복합기 구매"},
    {"bidNtceNo": "R26BK01561739", "bidNtceNm": "전산장비 구매"},
]
_LABELS = {"bidNtceNo": "입찰공고번호", "bidNtceNm": "공고명"}


def _response(
    *,
    records: "list[dict[str, str]] | None" = None,
    code: str = "00",
    message: str = "정상",
) -> NaraGatewayResponse:
    return NaraGatewayResponse(
        records=list(_RECORDS if records is None else records),
        result_code=code,
        result_msg=message,
        field_labels=dict(_LABELS),
    )


class _Gateway:
    def __init__(self, *results):
        self.results = list(results or (_response(),))
        self.calls: "list[dict[str, object]]" = []
        self.fetch_calls: "list[dict[str, object]]" = []
        self.probe_calls: "list[dict[str, object]]" = []

    def _take(
        self,
        service_key: str,
        bgn: str,
        end: str,
        *,
        num_rows: int,
        page_no: int,
    ) -> NaraGatewayResponse:
        call = {
            "service_key": service_key,
            "bgn": bgn,
            "end": end,
            "num_rows": num_rows,
            "page_no": page_no,
        }
        self.calls.append(call)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def fetch(
        self,
        service_key: str,
        bgn: str,
        end: str,
        *,
        num_rows: int,
        page_no: int,
    ) -> NaraGatewayResponse:
        result = self._take(
            service_key, bgn, end, num_rows=num_rows, page_no=page_no
        )
        self.fetch_calls.append(self.calls[-1])
        return result

    def probe(
        self,
        service_key: str,
        bgn: str,
        end: str,
        *,
        num_rows: int,
        page_no: int,
    ) -> NaraGatewayResponse:
        result = self._take(
            service_key, bgn, end, num_rows=num_rows, page_no=page_no
        )
        self.probe_calls.append(self.calls[-1])
        return result


def _vm(store=None, gateway=None, *, clock=None) -> NaraAcquireViewModel:
    return NaraAcquireViewModel(
        store if store is not None else MemorySecretStore(),
        gateway if gateway is not None else _Gateway(),
        secret_name=NARA_SERVICE_KEY_NAME,
        clock=clock if clock is not None else (lambda: _FIXED_NOW),
    )


# ------------------------------------------------------------------ 키 등록
def test_register_replace_delete_roundtrip():
    store = MemorySecretStore()
    vm = _vm(store)
    assert not vm.is_registered()
    assert vm.status_label() == "미등록"

    vm.save_key("  KEY1  ")
    assert vm.is_registered()
    assert vm.status_label() == "등록됨"
    assert store.get(NARA_SERVICE_KEY_NAME) == "KEY1"

    vm.save_key("KEY2")
    assert store.get(NARA_SERVICE_KEY_NAME) == "KEY2"

    vm.delete_key()
    assert not vm.is_registered()
    vm.delete_key()


def test_save_empty_key_rejected_loudly():
    vm = _vm()
    with pytest.raises(ValueError):
        vm.save_key("   ")
    assert not vm.is_registered()


# ------------------------------------------------------------------ 기간 검증
def test_add_one_month_clamps_end_of_month():
    assert _add_one_month(datetime(2026, 1, 31, 9, 0)) == datetime(2026, 2, 28, 9, 0)
    assert _add_one_month(datetime(2026, 12, 15, 0, 0)) == datetime(2027, 1, 15, 0, 0)


def test_validate_range_accepts_within_one_month():
    assert NaraAcquireViewModel.validate_range("202606010000", "202606302359") is None


@pytest.mark.parametrize(
    "bgn,end",
    [
        ("2026060100", "202606302359"),
        ("20260601000a", "202606302359"),
        ("202613010000", "202613020000"),
    ],
)
def test_validate_range_rejects_bad_format(bgn, end):
    assert NaraAcquireViewModel.validate_range(bgn, end) is not None


def test_validate_range_rejects_reversed_and_over_one_month():
    assert "빠릅니다" in NaraAcquireViewModel.validate_range(
        "202606100000", "202606010000"
    )
    over = NaraAcquireViewModel.validate_range("202606010000", "202607150000")
    assert over is not None and "1개월" in over


# ------------------------------------------------------------------ 취득 성공
def test_acquire_success_maps_gateway_response_and_query():
    gateway = _Gateway(_response())
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    result = _vm(store, gateway).acquire(
        "202606010000", "202606302359", num_rows=50, page_no=2
    )
    assert result.ok and result.count == 2 and result.result_code == "00"
    assert result.fields == ["bidNtceNo", "bidNtceNm"]
    assert "2건" in result.summary()
    assert gateway.calls == [
        {
            "service_key": "DUMMY",
            "bgn": "202606010000",
            "end": "202606302359",
            "num_rows": 50,
            "page_no": 2,
        }
    ]
    assert gateway.fetch_calls == gateway.calls
    assert gateway.probe_calls == []
    positional = AcquireResult(
        True,
        [],
        [],
        "00",
        "정상",
        "",
        "202606010000",
        "202606302359",
        50,
        2,
    )
    assert positional.result_code == "00" and positional.page_no == 2
    assert positional.field_labels is None
    assert positional.as_datasource().field_labels()["bidNtceNm"] == "공고명"


def test_acquire_datasource_is_keyless_snapshot():
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    result = _vm(store).acquire("202606010000", "202606302359")
    datasource = result.as_datasource()
    assert isinstance(datasource, AcquiredNaraData)
    assert datasource.field_labels()["bidNtceNm"] == "공고명"
    assert len(datasource.records()) == 2
    assert _LIVE_KEY not in repr(datasource.__dict__)
    assert _LIVE_KEY not in repr(result)
    legacy = AcquiredNaraData([{"bidNtceNm": "공고"}], ["bidNtceNm"])
    assert legacy.field_labels()["bidNtceNm"] == "공고명"


def test_acquire_success_owns_atomic_snapshot_with_query():
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store)
    result = vm.acquire("202606010000", "202606302359", num_rows=50, page_no=2)
    assert result.acceptable and vm.last_result is result
    assert (result.bgn_dt, result.end_dt) == ("202606010000", "202606302359")
    assert (result.num_rows, result.page_no) == (50, 2)
    assert result.source_label() == "나라장터 · 202606010000~202606302359 · 2건"


def test_acquire_failure_resets_snapshot_atomically():
    gateway = _Gateway(_response(), NaraGatewayError("safe adapter detail"))
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, gateway)
    assert vm.acquire("202606010000", "202606302359").acceptable
    assert vm.last_result is not None
    failed = vm.acquire("202606010000", "202606302359")
    assert not failed.ok
    assert vm.last_result is None


def test_acquire_zero_records_ok_but_not_acceptable():
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store, _Gateway(_response(records=[])))
    result = vm.acquire("202606010000", "202606302359")
    assert result.ok and not result.acceptable
    assert result.summary().startswith("취득 0건")
    assert vm.last_result is None


def test_invalidate_discards_snapshot():
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    vm = _vm(store)
    vm.acquire("202606010000", "202606302359")
    assert vm.last_result is not None
    vm.invalidate()
    assert vm.last_result is None


# ------------------------------------------------------------------ 취득 실패
def test_acquire_without_key_fails_loudly():
    result = _vm(MemorySecretStore()).acquire("202606010000", "202606302359")
    assert not result.ok and "등록" in result.error


def test_acquire_bad_range_fails_before_gateway():
    gateway = _Gateway()
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    result = _vm(store, gateway).acquire("202606010000", "202607150000")
    assert not result.ok and "1개월" in result.error
    assert gateway.calls == []


def test_acquire_auth_failure_distinguished_from_empty():
    response = _response(records=[], code="07", message="INVALID_REQUEST_PARAMETER_ERROR")
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    result = _vm(store, _Gateway(response)).acquire("202606010000", "202606302359")
    assert not result.ok and result.result_code == "07"
    assert "07" in result.error and _LIVE_KEY not in result.error


def test_acquire_missing_result_code_fails_closed():
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    result = _vm(store, _Gateway(_response(code="", message=""))).acquire(
        "202606010000", "202606302359"
    )
    assert not result.ok and result.result_code == ""
    assert "API 오류" in result.error


def test_connection_missing_result_code_fails_closed():
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    result = _vm(store, _Gateway(_response(code="", message=""))).test_connection()
    assert not result.ok


def test_unexpected_gateway_error_never_echoes_service_key():
    error = RuntimeError(f"HTTP 401 ServiceKey={_LIVE_KEY}")
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    result = _vm(store, _Gateway(error)).acquire("202606010000", "202606302359")
    assert not result.ok
    assert "응답을 가져오지 못했습니다" in result.error
    assert _LIVE_KEY not in result.error
    assert "ServiceKey=" not in result.error

    connection = _vm(store, _Gateway(error)).test_connection()
    assert not connection.ok
    assert "응답을 가져오지 못했습니다" in connection.message
    assert _LIVE_KEY not in connection.message
    assert "ServiceKey=" not in connection.message


# ------------------------------------------------------------------ 연결 시험
def test_connection_no_key():
    result = _vm(MemorySecretStore()).test_connection()
    assert not result.ok and "등록" in result.message


def test_connection_success():
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    gateway = _Gateway()
    result = _vm(store, gateway).test_connection()
    assert result.ok and "성공" in result.message
    assert gateway.probe_calls == gateway.calls
    assert gateway.fetch_calls == []


def test_connection_auth_failure_reports_code_no_leak():
    response = _response(
        records=[], code="30", message="SERVICE_KEY_IS_NOT_REGISTERED_ERROR"
    )
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    result = _vm(store, _Gateway(response)).test_connection()
    assert not result.ok and "30" in result.message
    assert _LIVE_KEY not in result.message


def test_connection_uses_injected_clock_and_one_day_window():
    gateway = _Gateway()
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    result = _vm(store, gateway, clock=lambda: _FIXED_NOW).test_connection()
    assert result.ok
    assert gateway.calls[0]["bgn"] == (_FIXED_NOW - timedelta(days=1)).strftime(
        "%Y%m%d%H%M"
    )
    assert gateway.calls[0]["end"] == _FIXED_NOW.strftime("%Y%m%d%H%M")
    assert gateway.calls[0]["num_rows"] == 1
    assert gateway.calls[0]["page_no"] == 1
