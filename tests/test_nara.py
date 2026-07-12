"""나라장터 취득 DataSource 테스트 — 실 라이브 응답 픽스처로 파싱/프로토콜 검증.

네트워크 없이: ``fetcher`` 주입으로 픽스처 바이트를 반환시켜 실호출을 대체한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.data.base import DataSource
from hwpxfiller.data.nara import NaraFetchError, NaraStdDataSource

FIXTURES = Path(__file__).parent / "fixtures"

# base64-ish 실제 키 형태(+, /, = 포함).
_LIVE_KEY = "aB3+xY/z9Q==pLm4Kn7"


def _fixture_bytes() -> bytes:
    return (FIXTURES / "nara_std_response.json").read_bytes()


def _src(**kw) -> NaraStdDataSource:
    return NaraStdDataSource(
        service_key="DUMMY",
        bgn_dt="202606010000",
        end_dt="202606302359",
        fetcher=lambda url: _fixture_bytes(),
        **kw,
    )


# ------------------------------------------------------------------- parse
def test_parse_extracts_flat_records():
    recs = NaraStdDataSource.parse(_fixture_bytes())
    assert len(recs) == 2
    assert recs[0]["bidNtceNo"] == "R26BK01561738"
    # 모든 값이 문자열.
    assert all(isinstance(v, str) for v in recs[0].values())


def test_parse_normalizes_single_item_dict():
    """items 가 단건 dict 로 와도 리스트로 정규화한다."""
    raw = '{"response":{"body":{"items":{"bidNtceNo":"X1","bidNtceNm":"단건"}}}}'
    recs = NaraStdDataSource.parse(raw)
    assert recs == [{"bidNtceNo": "X1", "bidNtceNm": "단건"}]


def test_result_code_parsed():
    code, msg = NaraStdDataSource.result(_fixture_bytes())
    assert code == "00"


# ------------------------------------------------------- DataSource protocol
def test_records_and_fields_via_injected_fetcher():
    src = _src()
    recs = src.records()
    assert len(recs) == 2
    fields = src.fields()
    assert "bidNtceNo" in fields and "presmptPrce" in fields
    # 등장 순서 보존(첫 필드는 bidNtceNo).
    assert fields[0] == "bidNtceNo"


def test_satisfies_datasource_protocol():
    """records()+fields() 를 갖춰 DataSource 프로토콜을 만족 → 엔진/배치에 그대로 붙는다."""
    assert isinstance(_src(), DataSource)


# --------------------------------------------------------------------- url
def test_url_contains_endpoint_and_params():
    src = _src()
    url = src.url()
    assert url.startswith(
        "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo"
    )
    assert "ServiceKey=DUMMY" in url
    assert "bidNtceBgnDt=202606010000" in url
    assert "type=json" in url


# ----------------------------------------------------------- 마스킹 경계(N1)
def _live_src(fetcher) -> NaraStdDataSource:
    return NaraStdDataSource(
        service_key=_LIVE_KEY, bgn_dt="202606010000", end_dt="202606302359",
        fetcher=fetcher,
    )


def test_redacted_url_masks_key_but_url_keeps_it():
    import urllib.parse
    src = _live_src(lambda url: b"{}")
    encoded = urllib.parse.quote_plus(_LIVE_KEY)
    # 실취득용 url() 은 키(퍼센트인코딩형)를 그대로 담는다(호출부가 실제 요청에 써야 함).
    assert encoded in src.url()
    # 진단용 redacted_url() 은 마스킹(원문·인코딩형 모두).
    redacted = src.redacted_url()
    assert _LIVE_KEY not in redacted
    assert encoded not in redacted
    assert "[REDACTED]" in redacted


def test_fetch_error_redacts_key_in_exception():
    """fetcher 가 키/URL 을 품은 예외를 던지면 표면화된 예외에서 키가 마스킹된다."""
    def boom(url: str) -> bytes:
        raise RuntimeError(f"HTTP Error 401: Unauthorized for url {url}")

    src = _live_src(boom)
    with pytest.raises(NaraFetchError) as ei:
        src.records()
    msg = str(ei.value)
    assert _LIVE_KEY not in msg
    assert "[REDACTED]" in msg
    # 원예외 연쇄로도 키가 새지 않는다(__suppress_context__).
    assert ei.value.__cause__ is None


def test_fetch_error_redacts_percent_encoded_url():
    """실제 요청 URL(퍼센트인코딩된 키)을 담은 예외도 마스킹."""
    def boom(url: str) -> bytes:
        # stdlib HTTPError 의 str() 처럼 실제 URL 전체를 담는 상황.
        raise OSError(f"urlopen error for {url}")

    src = _live_src(boom)
    with pytest.raises(NaraFetchError) as ei:
        src.records()
    msg = str(ei.value)
    import urllib.parse
    assert _LIVE_KEY not in msg
    assert urllib.parse.quote_plus(_LIVE_KEY) not in msg
    assert "[REDACTED]" in msg


def test_timeout_error_redacted():
    def boom(url: str) -> bytes:
        raise TimeoutError(f"timed out contacting {url}")

    src = _live_src(boom)
    with pytest.raises(NaraFetchError) as ei:
        src.records()
    assert _LIVE_KEY not in str(ei.value)


def test_empty_response_fails_loudly_without_leak():
    """빈/불량 응답도 파싱 마스킹 경계 안에서 시끄럽게 실패하고 키를 흘리지 않는다."""
    src = _live_src(lambda url: b"")
    with pytest.raises(NaraFetchError) as ei:
        src.records()
    assert _LIVE_KEY not in str(ei.value)


def test_auth_failure_result_code_no_leak():
    """resultCode != '00' 응답(인증 실패류)은 items 부재로 빈 목록 — 키 누출 없음."""
    auth_fail = (
        b'{"response":{"header":{"resultCode":"07",'
        b'"resultMsg":"INVALID_REQUEST_PARAMETER_ERROR"},"body":{}}}'
    )
    code, msg = NaraStdDataSource.result(auth_fail)
    assert code == "07"
    src = _live_src(lambda url: auth_fail)
    recs = src.records()
    assert recs == []
    assert _LIVE_KEY not in repr(recs) and _LIVE_KEY not in msg
