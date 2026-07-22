"""나라장터 취득 DataSource 테스트 — 실 라이브 응답 픽스처로 파싱/프로토콜 검증.

네트워크 없이: ``fetcher`` 주입으로 픽스처 바이트를 반환시켜 실호출을 대체한다.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest

from hwpxfiller.data.base import DataSource
from hwpxfiller.data.nara import NaraFetchError, NaraStdDataSource

FIXTURES = Path(__file__).parent / "fixtures"

# base64-ish 실제 키 형태(+, /, = 포함).
_LIVE_KEY = "aB3+xY/z9Q==pLm4Kn7"


def _fixture_bytes() -> bytes:
    return (FIXTURES / "nara_std_response.json").read_bytes()


def _page(page_no: int, total: int, rows: list[dict], *, num_rows: int = 2) -> bytes:
    return json.dumps({
        "response": {
            "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {
                "pageNo": page_no,
                "numOfRows": num_rows,
                "totalCount": total,
                "items": {"item": rows},
            },
        },
    }, ensure_ascii=False).encode()


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


def test_parse_normalizes_real_items_item_envelope_fixture():
    raw = (FIXTURES / "nara_items_item_response.json").read_bytes()
    assert NaraStdDataSource.parse(raw) == [
        {"bidNtceNo": "R26BK09990001", "bidNtceOrd": "000", "bidNtceNm": "봉투 단건"}
    ]


@pytest.mark.parametrize(
    "items",
    [[], {}, None, "", {"item": []}, {"item": None}],
)
def test_parse_normalizes_supported_empty_envelopes(items):
    raw = json.dumps({"response": {"body": {"items": items}}})
    assert NaraStdDataSource.parse(raw) == []


def test_parse_rejects_unknown_items_shape_loudly():
    raw = '{"response":{"body":{"items":{"item":"not-a-list-or-record"}}}}'
    with pytest.raises(ValueError, match="items.item"):
        NaraStdDataSource.parse(raw)


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


def test_records_fetches_all_pages_until_total_count():
    pages = {
        1: _page(1, 5, [
            {"bidNtceNo": "N1", "bidNtceOrd": "000"},
            {"bidNtceNo": "N2", "bidNtceOrd": "000"},
        ]),
        2: _page(2, 5, [
            {"bidNtceNo": "N3", "bidNtceOrd": "000"},
            {"bidNtceNo": "N4", "bidNtceOrd": "000"},
        ]),
        3: _page(3, 5, [{"bidNtceNo": "N5", "bidNtceOrd": "000"}]),
    }
    calls: list[int] = []

    def fetch(url: str) -> bytes:
        page = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["pageNo"][0])
        calls.append(page)
        return pages[page]

    src = NaraStdDataSource(
        "DUMMY", "202606010000", "202606302359", num_rows=2, fetcher=fetch,
    )
    assert [r["bidNtceNo"] for r in src.records()] == ["N1", "N2", "N3", "N4", "N5"]
    assert calls == [1, 2, 3]  # totalCount=5, numOfRows=2: 다음 빈 페이지 요청 없음.


def test_records_honors_start_page_and_remaining_total_count():
    calls: list[int] = []

    def fetch(url: str) -> bytes:
        page = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["pageNo"][0])
        calls.append(page)
        return _page(page, 5, [
            {"bidNtceNo": f"N{2 * page - 1}", "bidNtceOrd": "000"}
        ] if page == 3 else [
            {"bidNtceNo": "N3", "bidNtceOrd": "000"},
            {"bidNtceNo": "N4", "bidNtceOrd": "000"},
        ])

    src = NaraStdDataSource(
        "DUMMY", "202606010000", "202606302359",
        num_rows=2, page_no=2, fetcher=fetch,
    )
    assert [r["bidNtceNo"] for r in src.records()] == ["N3", "N4", "N5"]
    assert calls == [2, 3]


def test_duplicate_or_overlapping_page_fails_closed():
    pages = {
        1: _page(1, 3, [
            {"bidNtceNo": "N1", "bidNtceOrd": "000"},
            {"bidNtceNo": "N2", "bidNtceOrd": "000"},
        ]),
        2: _page(2, 3, [{"bidNtceNo": "N2", "bidNtceOrd": "000"}]),
    }

    def fetch(url: str) -> bytes:
        page = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["pageNo"][0])
        return pages[page]

    src = NaraStdDataSource(
        "DUMMY", "202606010000", "202606302359", num_rows=2, fetcher=fetch,
    )
    with pytest.raises(NaraFetchError, match="중복|겹침"):
        src.records()


def test_empty_intermediate_page_fails_closed():
    pages = {1: _page(1, 3, [{"bidNtceNo": "N1"}, {"bidNtceNo": "N2"}]),
             2: _page(2, 3, [])}

    def fetch(url: str) -> bytes:
        page = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["pageNo"][0])
        return pages[page]

    src = NaraStdDataSource(
        "DUMMY", "202606010000", "202606302359", num_rows=2, fetcher=fetch,
    )
    with pytest.raises(NaraFetchError, match="중간 페이지|totalCount"):
        src.records()


def test_intermediate_fetch_failure_returns_no_partial_and_redacts_key():
    calls: list[int] = []

    def fetch(url: str) -> bytes:
        page = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["pageNo"][0])
        calls.append(page)
        if page == 2:
            raise TimeoutError(f"failed page url={url} key={_LIVE_KEY}")
        return _page(1, 3, [{"bidNtceNo": "N1"}, {"bidNtceNo": "N2"}])

    src = NaraStdDataSource(
        _LIVE_KEY, "202606010000", "202606302359", num_rows=2, fetcher=fetch,
    )
    with pytest.raises(NaraFetchError) as ei:
        src.records()
    message = str(ei.value)
    assert calls == [1, 2]
    assert _LIVE_KEY not in message
    assert urllib.parse.quote_plus(_LIVE_KEY) not in message
    assert "[REDACTED]" in message
    assert ei.value.__cause__ is None


def test_total_count_change_between_pages_fails_closed():
    def fetch(url: str) -> bytes:
        page = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["pageNo"][0])
        if page == 1:
            return _page(1, 3, [{"bidNtceNo": "N1"}, {"bidNtceNo": "N2"}])
        return _page(2, 4, [{"bidNtceNo": "N3"}, {"bidNtceNo": "N4"}])

    src = NaraStdDataSource(
        "DUMMY", "202606010000", "202606302359", num_rows=2, fetcher=fetch,
    )
    with pytest.raises(NaraFetchError, match="totalCount.*변경"):
        src.records()


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


def test_xml_auth_failure_surfaces_return_auth_msg():
    """게이트웨이 인증 실패 **XML** 응답이면 JSON 파서 원문 대신 returnAuthMsg 를 표면화(RC-16)."""
    xml = (
        b"<OpenAPI_ServiceResponse><cmmMsgHeader>"
        b"<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
        b"<returnReasonCode>30</returnReasonCode>"
        b"</cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    src = _live_src(lambda url: xml)
    with pytest.raises(NaraFetchError) as ei:
        src.records()
    msg = str(ei.value)
    assert "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in msg   # 실원인 보존
    assert "코드 30" in msg
    assert "Expecting value" not in msg                    # 파서 원문에 묻히지 않음
    assert _LIVE_KEY not in msg                            # 마스킹 경계 유지


def test_auth_failure_result_code_raises_loudly_no_leak():
    """resultCode != '00'(인증 실패류)은 조용한 빈 목록이 아니라 NaraFetchError(RC-03).

    게이트는 데이터 경계가 소유한다 — CLI·파이프라인·풀 복원 어느 호출자도 인증 실패
    응답(HTTP 200 + 오류 헤더)을 '0건 취득' 성공으로 통과시킬 수 없다. 키 누출도 없다.
    """
    auth_fail = (
        b'{"response":{"header":{"resultCode":"07",'
        b'"resultMsg":"INVALID_REQUEST_PARAMETER_ERROR"},"body":{}}}'
    )
    code, msg = NaraStdDataSource.result(auth_fail)
    assert code == "07"
    src = _live_src(lambda url: auth_fail)
    with pytest.raises(NaraFetchError) as ei:
        src.records()
    text = str(ei.value)
    assert "[07]" in text and "API 오류" in text
    assert _LIVE_KEY not in text


def test_auth_failure_with_items_still_raises():
    """오류 응답에 items 가 실려 있어도 오류 데이터로 문서를 만들지 않는다(RC-03 C2)."""
    poisoned = (
        b'{"response":{"header":{"resultCode":"07","resultMsg":"AUTH"},'
        b'"body":{"items":[{"bidNtceNo":"X1"}]}}}'
    )
    src = _live_src(lambda url: poisoned)
    with pytest.raises(NaraFetchError, match="API 오류"):
        src.records()


def test_api_result_message_echoing_service_key_is_redacted():
    """게이트웨이 resultMsg가 요청 키를 되비춰도 생성한 NaraFetchError를 재마스킹한다."""

    poisoned = json.dumps({
        "response": {
            "header": {
                "resultCode": "07",
                "resultMsg": f"rejected ServiceKey={_LIVE_KEY}",
            },
            "body": {},
        },
    }).encode()
    src = _live_src(lambda url: poisoned)
    with pytest.raises(NaraFetchError) as ei:
        src.records()
    message = str(ei.value)
    assert _LIVE_KEY not in message
    assert "ServiceKey=[REDACTED]" in message
    assert ei.value.__cause__ is None


def test_missing_result_code_fails_closed():
    """resultCode 부재도 규격 밖 — 조용한 성공 금지(fail-closed)."""
    src = _live_src(lambda url: b'{"response":{"body":{"items":[]}}}')
    with pytest.raises(NaraFetchError, match="코드 없음"):
        src.records()


def test_range_over_one_month_raises_before_fetch():
    """기간 검증도 데이터 경계 소유(RC-03) — 위반이면 네트워크 요청 자체가 없다."""
    calls: "list[str]" = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return _fixture_bytes()

    src = NaraStdDataSource(
        service_key="DUMMY", bgn_dt="202601010000", end_dt="202607010000",
        fetcher=fetcher,
    )
    with pytest.raises(NaraFetchError, match="1개월"):
        src.records()
    assert calls == []  # 요청 전 차단(키 소비 0회)
