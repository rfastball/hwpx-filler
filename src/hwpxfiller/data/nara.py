"""나라장터 취득 DataSource — 조달청 공공데이터개방표준서비스(data.go.kr 15058815).

엔드포인트(라이브 검증됨)::

    https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo

표준 서비스라 카테고리(물품/용역/공사) 무관 **플랫 레코드 1콜**. envelope 는
``response.body.items[]`` 이며 각 item 이 평면 dict(레코드 1건). ``DataSource`` 프로토콜
(``records()``+``fields()``)을 구현해 엔진/배치/매핑에 그대로 붙는다.

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
    def url(self) -> str:
        query = urllib.parse.urlencode(
            {
                "ServiceKey": self.service_key,
                "pageNo": self.page_no,
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

    def _fetch(self) -> bytes:
        # urlopen/주입 fetcher 가 던지는 예외는 URL(키 포함)을 품을 수 있다 → 마스킹 후 재발생.
        try:
            if self._fetcher is not None:
                return self._fetcher(self.url())
            with urllib.request.urlopen(self.url(), timeout=self.timeout) as resp:
                return resp.read()
        except NaraFetchError:
            raise
        except Exception as exc:
            raise NaraFetchError(redact(str(exc), self.service_key)) from None

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
        raw = self._fetch()
        # 파싱 오류(빈/불량 응답)도 마스킹 경계 안에서 시끄럽게 실패시킨다.
        try:
            code, msg = self.result(raw)
            if code != OK_RESULT_CODE:
                raise NaraFetchError(
                    f"API 오류 [{code or '코드 없음'}] {msg or '메시지 없음'}"
                )
            return self.parse(raw)
        except NaraFetchError:
            raise
        except Exception as exc:
            # 인증 실패 XML 이면 파서 원문 대신 실원인(returnAuthMsg)을 표면화.
            detail = _auth_failure_detail(raw) or str(exc)
            raise NaraFetchError(redact(detail, self.service_key)) from None

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
        """API 응답(bytes/str)에서 ``response.body.items[]`` 를 평면 레코드 목록으로.

        item 이 단건이면 dict 로 오는 경우가 있어 리스트로 정규화한다. 모든 값은
        문자열로(누락은 빈 문자열). 매핑/엔진이 str 값을 기대한다.
        """
        data = json.loads(raw)
        body = (data.get("response") or {}).get("body") or {}
        items = body.get("items") or []
        if isinstance(items, dict):
            items = [items]
        out: "list[dict[str, str]]" = []
        for it in items:
            if isinstance(it, dict):
                out.append({k: ("" if v is None else str(v)) for k, v in it.items()})
        return out

    @staticmethod
    def result(raw: "bytes | str") -> "tuple[str, str]":
        """응답 헤더의 (resultCode, resultMsg). 정상은 ('00','정상')."""
        data = json.loads(raw)
        header = (data.get("response") or {}).get("header") or {}
        return header.get("resultCode", ""), header.get("resultMsg", "")
