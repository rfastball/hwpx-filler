"""나라장터 취득 DataSource — 조달청 공공데이터개방표준서비스(data.go.kr 15058815).

엔드포인트(라이브 검증됨)::

    https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo

표준 서비스라 카테고리(물품/용역/공사) 무관 플랫 레코드를 돌려준다. ``records()`` 는
``totalCount``/``numOfRows`` 를 기준으로 시작 ``page_no``부터 마지막 페이지까지 취득한다.
envelope 는 ``response.body.items[]`` 와 실제 게이트웨이 변형 ``items.item`` 을 모두 받으며
각 item 은 평면 dict(레코드 1건)다. ``DataSource`` 프로토콜(``records()``+``fields()``)을
구현해 엔진/배치/매핑에 그대로 붙는다.

설계 원칙:
- **의존성 0 추가** — stdlib ``urllib`` 만 사용(core 의 lxml+openpyxl 최소 의존 유지).
- **ServiceKey 는 런타임 인자** — 하드코딩·저장 금지. ``urlencode`` 가 키를 퍼센트
  인코딩하므로 data.go.kr 의 Encoding/Decoding 키 양쪽을 올바로 처리한다.
- **네트워크는 주입 가능** — ``fetcher``(url->bytes)로 테스트에서 실호출 없이 검증.
- 날짜 범위는 **1개월 제한**(``bidNtceBgnDt``/``bidNtceEndDt``, ``YYYYMMDDHHMM``).
"""

from __future__ import annotations

import calendar
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime

from .secret_store import redact

BASE = (
    "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/"
    "getDataSetOpnStdBidPblancInfo"
)

#: 나라 API 일시 포맷(``bidNtceBgnDt``/``bidNtceEndDt``) — YYYYMMDDHHMM.
DT_FMT = "%Y%m%d%H%M"

#: 정상 응답 헤더 코드 — 그 외(인증/파라미터 오류, 부재)는 시끄럽게 실패한다.
OK_RESULT_CODE = "00"


def _add_one_month(dt: datetime) -> datetime:
    """``dt`` 에 한 달을 더한다(말일 클램프: 1/31 + 1달 = 2/28·29)."""
    month = dt.month + 1
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def validate_range(bgn: str, end: str) -> "str | None":
    """시작~종료 일시 검증(YYYYMMDDHHMM·1개월 제한). 통과면 ``None``, 아니면 사유 문자열.

    검증의 단일 출처(RC-03) — 취득 경계(:meth:`NaraStdDataSource.records`)와 GUI
    뷰모델(:class:`~hwpxfiller.gui.nara_state.NaraAcquireViewModel`)이 공유한다.
    """
    for label, val in (("시작", bgn), ("종료", end)):
        if not val or len(val) != 12 or not val.isdigit():
            return f"{label} 일시 형식이 올바르지 않습니다(YYYYMMDDHHMM 12자리)."
    try:
        b = datetime.strptime(bgn, DT_FMT)
        e = datetime.strptime(end, DT_FMT)
    except ValueError:
        return "일시를 해석할 수 없습니다(YYYYMMDDHHMM)."
    if e < b:
        return "종료 일시가 시작 일시보다 빠릅니다."
    if e > _add_one_month(b):
        return "조회 기간은 최대 1개월입니다(시작~종료 간격을 1개월 이내로)."
    return None

# 나라장터 표준 입찰공고 응답 필드(소스 키) → 사람이 읽는 한글 라벨.
# 영문 코드 키를 한글 템플릿 필드에 퍼지 매칭하려면 이 사전이 퍼지 타겟이 된다.
# 근거: 공공데이터개방표준서비스(15058815) getDataSetOpnStdBidPblancInfo 실 라이브 응답.
# 이 어휘는 **소스가 소유한다**(코어 아님) — ``field_labels()`` 로 GUI 에 노출된다.
_FIELD_LABELS: "dict[str, str]" = {
    "bidNtceNo": "입찰공고번호",
    "bidNtceOrd": "입찰공고차수",
    "bidNtceNm": "공고명",
    "bidNtceSttusNm": "공고상태",
    "bidNtceDate": "공고일자",
    "bidNtceBgn": "공고시각",
    "bsnsDivNm": "업무구분",
    "cntrctCnclsMthdNm": "계약방법",
    "cntrctCnclsSttusNm": "계약체결형태",
    "bidwinrDcsnMthdNm": "낙찰자결정방법",
    "ntceInsttNm": "공고기관",
    "ntceInsttCd": "공고기관코드",
    "ntceInsttOfclDeptNm": "공고기관담당부서",
    "ntceInsttOfclNm": "공고기관담당자",
    "ntceInsttOfclTel": "공고기관담당자전화번호",
    "dmndInsttNm": "수요기관",
    "dmndInsttOfclDeptNm": "수요기관담당부서",
    "dmndInsttOfclNm": "수요기관담당자",
    "dmndInsttOfclTel": "수요기관담당자전화번호",
    "bidBeginDate": "입찰개시일자",
    "bidBeginTm": "입찰개시시각",
    "bidClseDate": "입찰마감일자",
    "bidClseTm": "입찰마감시각",
    "bidPrtcptQlfctRgstClseDate": "입찰참가자격등록마감일자",
    "bidPrtcptQlfctRgstClseTm": "입찰참가자격등록마감시각",
    "opengDate": "개찰일자",
    "opengTm": "개찰시각",
    "opengPlce": "개찰장소",
    "asignBdgtAmt": "배정예산",
    "presmptPrce": "추정가격",
    "rgnLmtYn": "지역제한여부",
    "prtcptPsblRgnNm": "참가가능지역",
    "indstrytyLmtYn": "업종제한여부",
    "bidprcPsblIndstrytyNm": "투찰가능업종",
    "bidNtceUrl": "공고URL",
}


class NaraFetchError(RuntimeError):
    """취득/파싱 경계에서 발생한 오류 — 메시지에서 ServiceKey 가 마스킹된 상태로만 표면화.

    ``urlopen``/주입 fetcher/파싱이 던지는 예외의 ``str()`` 은 요청 URL(키 포함)이나 키 자체를
    품을 수 있다. 그 원문을 **연쇄(chain)로도 남기지 않도록**(traceback 누출 방지) 원예외를
    끊고(``from None``) 마스킹된 메시지로 재발생시킨다.
    """


# data.go.kr 게이트웨이는 인증 실패를 JSON 이 아닌 **XML** 로 응답한다(type=json 이어도).
# JSON 파서 원문("Expecting value: ...")에 실원인이 묻히지 않게 여기서 추출한다(RC-16).
_XML_AUTH_MSG = re.compile(r"<returnAuthMsg>\s*([^<]+?)\s*</returnAuthMsg>")
_XML_REASON_CODE = re.compile(r"<returnReasonCode>\s*([^<]+?)\s*</returnReasonCode>")


def _auth_failure_detail(raw: "bytes | str") -> "str | None":
    """XML 오류 응답에서 returnAuthMsg(+returnReasonCode)를 뽑는다. 아니면 ``None``."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    m = _XML_AUTH_MSG.search(text)
    if not m:
        return None
    code = _XML_REASON_CODE.search(text)
    suffix = f" (코드 {code.group(1)})" if code else ""
    return f"인증 실패 — {m.group(1)}{suffix}"


class NaraStdDataSource:
    """조달청 표준 입찰공고 취득 소스."""

    def __init__(
        self,
        service_key: str,
        bgn_dt: str,
        end_dt: str,
        *,
        num_rows: int = 100,
        page_no: int = 1,
        timeout: float = 20.0,
        fetcher=None,
    ):
        self.service_key = service_key
        self.bgn_dt = bgn_dt  # YYYYMMDDHHMM
        self.end_dt = end_dt  # YYYYMMDDHHMM (bgn 과 1개월 이내)
        self.num_rows = num_rows
        self.page_no = page_no
        self.timeout = timeout
        self._fetcher = fetcher  # 테스트 주입: (url:str) -> bytes

    # --------------------------------------------------------------- request
    def url(self, page_no: "int | None" = None) -> str:
        query = urllib.parse.urlencode(
            {
                "ServiceKey": self.service_key,
                "pageNo": self.page_no if page_no is None else page_no,
                "numOfRows": self.num_rows,
                "type": "json",
                "bidNtceBgnDt": self.bgn_dt,
                "bidNtceEndDt": self.end_dt,
            }
        )
        return f"{BASE}?{query}"

    def redacted_url(self) -> str:
        """진단·로그용 URL — ServiceKey 가 마스킹된 형태(실취득엔 :meth:`url` 을 쓴다)."""
        return redact(self.url(), self.service_key)

    def _request(self, url: str) -> bytes:
        """한 URL을 취득한다. 예외 종류와 무관하게 키를 지운 새 경계 오류만 남긴다."""

        try:
            if self._fetcher is not None:
                return self._fetcher(url)
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return resp.read()
        except Exception as exc:
            raise NaraFetchError(redact(str(exc), self.service_key)) from None

    def _fetch(self) -> bytes:
        """첫(설정) 페이지 취득 이음새 — 기존 테스트/호출측 monkeypatch 계약을 보존한다."""

        return self._request(self.url())

    def _fetch_page(self, page_no: int) -> bytes:
        # 설정 시작 페이지는 오랜 테스트 이음새(_fetch monkeypatch)를 반드시 지난다. 이후 페이지만
        # 명시 URL로 취득한다. 실 fetcher 경로에서는 양쪽 모두 같은 _request 마스킹 경계다.
        if page_no == self.page_no:
            return self._fetch()
        return self._request(self.url(page_no))

    # ------------------------------------------------------ DataSource protocol
    def records(self) -> "list[dict[str, str]]":
        """취득 + **경계 검증**(RC-03) — 기간·resultCode 게이트는 데이터층이 소유한다.

        검증이 호출자(GUI 뷰모델)에게만 있으면 CLI·파이프라인·풀 복원 같은 새 호출측이
        자동으로 게이트 밖이 된다. 여기서 fail-closed:

        - 기간(1개월 제한·형식) 위반 → 요청 전에 :class:`NaraFetchError`.
        - ``resultCode != '00'``(인증/파라미터 오류, **부재 포함**) → 조용한 "0건"이
          아니라 :class:`NaraFetchError`. 오류 응답에 items 가 실려 있어도 오류 데이터로
          문서를 만들지 않는다.
        """
        rng_err = validate_range(self.bgn_dt, self.end_dt)
        if rng_err:
            raise NaraFetchError(f"조회 조건 오류: {rng_err}")
        try:
            if not isinstance(self.num_rows, int) or self.num_rows <= 0:
                raise NaraFetchError("조회 조건 오류: num_rows는 1 이상 정수여야 합니다.")
            if not isinstance(self.page_no, int) or self.page_no <= 0:
                raise NaraFetchError("조회 조건 오류: page_no는 1 이상 정수여야 합니다.")
            return self._records_paginated()
        except NaraFetchError as exc:
            # 우리가 만든 API 오류 메시지도 resultMsg가 키/URL을 되비출 수 있다. 기존에 안전한
            # NaraFetchError까지 포함해 경계 바깥으로 나가는 모든 문자열을 다시 마스킹하고,
            # 원예외 context/chain은 끊는다.
            raise NaraFetchError(redact(str(exc), self.service_key)) from None
        except Exception as exc:
            detail = str(exc)
            raise NaraFetchError(redact(detail, self.service_key)) from None

    def _records_paginated(self) -> "list[dict[str, str]]":
        """``totalCount`` 기준 다중 페이지 취득. 이상 징후는 부분 반환 없이 전체 실패."""

        start_page = self.page_no
        page_no = start_page
        expected_total: "int | None" = None
        response_page_size: "int | None" = None
        expected_remaining: "int | None" = None
        last_page: "int | None" = None
        records: "list[dict[str, str]]" = []
        seen: "set[tuple[str, ...]]" = set()

        while True:
            raw = self._fetch_page(page_no)
            try:
                code, msg = self.result(raw)
                if code != OK_RESULT_CODE:
                    raise NaraFetchError(
                        f"API 오류 [{code or '코드 없음'}] {msg or '메시지 없음'}"
                    )
                page_records = self.parse(raw)
                actual_page, page_size, total = self._page_meta(raw)
            except NaraFetchError:
                raise
            except Exception as exc:
                # 인증 실패 XML이면 JSON 오류 문구 대신 게이트웨이 실원인을 보존한다.
                detail = _auth_failure_detail(raw) or str(exc)
                raise NaraFetchError(detail) from None

            if actual_page != page_no:
                raise NaraFetchError(
                    f"페이지 응답 불일치: 요청 {page_no}, 응답 {actual_page}."
                )
            if expected_total is None:
                expected_total = total
                response_page_size = page_size
                skipped = (start_page - 1) * page_size
                expected_remaining = max(total - skipped, 0)
                last_page = (total + page_size - 1) // page_size
            else:
                if total != expected_total:
                    raise NaraFetchError(
                        f"페이지 취득 중 totalCount 변경: {expected_total} → {total}."
                    )
                if page_size != response_page_size:
                    raise NaraFetchError(
                        f"페이지 취득 중 numOfRows 변경: {response_page_size} → {page_size}."
                    )

            assert response_page_size is not None
            assert expected_remaining is not None
            assert last_page is not None
            if len(page_records) > response_page_size:
                raise NaraFetchError(
                    f"페이지 {page_no} 레코드 수가 numOfRows를 초과했습니다: "
                    f"{len(page_records)} > {response_page_size}."
                )

            for record in page_records:
                identity = self._record_identity(record)
                if identity in seen:
                    raise NaraFetchError(
                        f"페이지 {page_no}에 이전 페이지와 중복·겹침 레코드가 있습니다."
                    )
                seen.add(identity)
                records.append(record)

            # 시작 페이지가 이미 totalCount 범위 밖이면 그 한 페이지가 비어 있을 때만 정상 빈 결과.
            if start_page > last_page:
                if page_records:
                    raise NaraFetchError("totalCount 범위 밖 페이지가 레코드를 반환했습니다.")
                return []

            if page_no >= last_page:
                if len(records) != expected_remaining:
                    raise NaraFetchError(
                        "totalCount와 실제 취득 건수가 일치하지 않습니다: "
                        f"예상 {expected_remaining}, 실제 {len(records)}."
                    )
                return records
            if not page_records:
                raise NaraFetchError(
                    f"totalCount 도달 전 중간 페이지 {page_no}가 비어 있습니다."
                )
            page_no += 1

    @staticmethod
    def _record_identity(record: "dict[str, str]") -> "tuple[str, ...]":
        """페이지 겹침 판별 키. 공고 식별자가 없으면 정규화한 레코드 전체를 쓴다."""

        notice = record.get("bidNtceNo", "")
        if notice:
            return ("notice", notice, record.get("bidNtceOrd", ""))
        return ("record", json.dumps(record, ensure_ascii=False, sort_keys=True))

    @staticmethod
    def field_labels() -> "dict[str, str]":
        """이 소스의 어휘: 소스 키(영문 코드) → 사람이 읽는 한글 라벨.

        영문 코드 키를 한글 템플릿 필드에 퍼지 매칭할 때 GUI 가 이 사전을
        ``suggest_mappings(..., aliases=...)`` 로 주입한다(코어는 어휘-불가지).
        호출측 변형으로부터 보호하려 사본을 반환한다.
        """
        return dict(_FIELD_LABELS)

    def fields(self) -> "list[str]":
        """레코드가 제공하는 필드 키를 등장 순서(중복 제거)로 반환."""
        seen: "set[str]" = set()
        keys: "list[str]" = []
        for rec in self.records():
            for k in rec:
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        return keys

    # -------------------------------------------------------------- parsing
    @staticmethod
    def parse(raw: "bytes | str") -> "list[dict[str, str]]":
        """API 응답의 ``items[]``/``items.item`` 을 평면 레코드 목록으로.

        list·단건 dict·빈 봉투를 정규화한다. 그 밖의 shape는 레코드 일부를 조용히 버리지
        않고 실패한다. 모든 값은 문자열로(누락은 빈 문자열).
        """
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("응답 루트가 객체가 아닙니다.")
        response = data.get("response") or {}
        if not isinstance(response, dict):
            raise ValueError("response가 객체가 아닙니다.")
        body = response.get("body") or {}
        if not isinstance(body, dict):
            raise ValueError("response.body가 객체가 아닙니다.")
        items = body.get("items")
        if items in (None, "", [], {}):
            return []
        if isinstance(items, dict) and "item" in items:
            if set(items) != {"item"}:
                raise ValueError("items.item 봉투에 미등록 형제 키가 있습니다.")
            items = items["item"]
            if items in (None, "", [], {}):
                return []
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise ValueError("response.body.items.item은 레코드 객체 또는 목록이어야 합니다.")
        out: "list[dict[str, str]]" = []
        for it in items:
            if not isinstance(it, dict):
                raise ValueError("items 목록에 레코드 객체가 아닌 값이 있습니다.")
            out.append({k: ("" if v is None else str(v)) for k, v in it.items()})
        return out

    @staticmethod
    def _page_meta(raw: "bytes | str") -> "tuple[int, int, int]":
        """응답 body의 ``pageNo``, ``numOfRows``, ``totalCount``를 엄격 정수화한다."""

        data = json.loads(raw)
        body = (data.get("response") or {}).get("body") or {}

        def integer(name: str, *, positive: bool) -> int:
            value = body.get(name)
            if isinstance(value, bool):
                raise ValueError(f"{name}이 정수가 아닙니다.")
            # 비정수 수치 절단 금지(#253 리뷰) — ``int(2.9)`` 는 조용히 2 로 깎인다.
            # totalCount 가 깎이면 마지막 페이지 상한이 줄어 표방된 행을 다 요청하지
            # 않고도 성공 반환한다(fail-closed 정수 스키마 위반). 정수값 실수만 통과.
            if isinstance(value, float) and not value.is_integer():
                raise ValueError(f"{name}이 정수가 아닙니다: {value!r}")
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{name}이 정수가 아닙니다: {value!r}") from None
            if (positive and number <= 0) or (not positive and number < 0):
                raise ValueError(f"{name} 범위가 올바르지 않습니다: {number}.")
            return number

        return (
            integer("pageNo", positive=True),
            integer("numOfRows", positive=True),
            integer("totalCount", positive=False),
        )

    @staticmethod
    def result(raw: "bytes | str") -> "tuple[str, str]":
        """응답 헤더의 (resultCode, resultMsg). 정상은 ('00','정상')."""
        data = json.loads(raw)
        header = (data.get("response") or {}).get("header") or {}
        return header.get("resultCode", ""), header.get("resultMsg", "")
