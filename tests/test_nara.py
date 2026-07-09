"""나라장터 취득 DataSource 테스트 — 실 라이브 응답 픽스처로 파싱/프로토콜 검증.

네트워크 없이: ``fetcher`` 주입으로 픽스처 바이트를 반환시켜 실호출을 대체한다.
"""

from __future__ import annotations

from pathlib import Path

from hwpxfiller.data.base import DataSource
from hwpxfiller.data.nara import NaraStdDataSource

FIXTURES = Path(__file__).parent / "fixtures"


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
