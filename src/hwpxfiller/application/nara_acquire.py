"""나라장터 취득 Application 상태와 효과 계약.

키 저장·HTTP 취득·현재 시각 선택은 바깥 adapter가 소유한다. 이 모듈은 주입된
:class:`SecretStorePort`, :class:`NaraGatewayPort`, clock만 사용해 키 등록·조회 조건·
취득 결과의 수명과 사용자 판정을 오케스트레이션한다.

보안 불변식:

- ServiceKey는 취득 호출 순간에만 gateway로 전달하고 결과·스냅샷에 저장하지 않는다.
- gateway 계약 밖 예외의 원문은 표면화하지 않는다. 예외가 키를 품어도 고정 오류만
  반환하므로 Application 경계 밖으로 새지 않는다.
- 취득 성공 결과는 레코드·필드·라벨만 든 키 없는 스냅샷이다.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Protocol

#: 나라 API 일시 포맷(``bidNtceBgnDt``/``bidNtceEndDt``) — YYYYMMDDHHMM.
DT_FMT = "%Y%m%d%H%M"

#: 정상 응답 헤더 코드 — 그 외(인증/파라미터 오류, 부재)는 시끄럽게 실패한다.
OK_RESULT_CODE = "00"

# Adapter 예외 원문은 ServiceKey/URL을 품을 수 있다. Application은 고정 문구만 표면화한다.
_GATEWAY_FAILURE = "나라장터 서비스 응답을 가져오지 못했습니다. 잠시 후 다시 시도하세요."

# 나라장터 표준 입찰공고 응답 필드(소스 키) → 사람이 읽는 한글 라벨.
# 키 없는 스냅샷과 concrete DataSource가 같은 어휘를 쓰도록 canonical decision과 함께 둔다.
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


def _add_one_month(dt: datetime) -> datetime:
    """``dt``에 한 달을 더한다(말일 클램프: 1/31 + 1달 = 2/28·29)."""
    month = dt.month + 1
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def validate_range(bgn: str, end: str) -> "str | None":
    """시작~종료 일시 검증(YYYYMMDDHHMM·1개월 제한). 통과면 ``None``."""
    for label, value in (("시작", bgn), ("종료", end)):
        if not value or len(value) != 12 or not value.isdigit():
            return f"{label} 일시 형식이 올바르지 않습니다(YYYYMMDDHHMM 12자리)."
    try:
        begin = datetime.strptime(bgn, DT_FMT)
        finish = datetime.strptime(end, DT_FMT)
    except ValueError:
        return "일시를 해석할 수 없습니다(YYYYMMDDHHMM)."
    if finish < begin:
        return "종료 일시가 시작 일시보다 빠릅니다."
    if finish > _add_one_month(begin):
        return "조회 기간은 최대 1개월입니다(시작~종료 간격을 1개월 이내로)."
    return None


class SecretStorePort(Protocol):
    """Application이 요구하는 비밀 저장 효과의 최소 표면."""

    def get(self, name: str) -> "str | None": ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...

    def has(self, name: str) -> bool: ...


class NaraGatewayError(RuntimeError):
    """나라장터 concrete gateway 실패.

    Application은 이 예외를 포함한 모든 gateway 예외를 고정 문구로 접는다. adapter는
    자기 로그·테스트 경계를 위해서도 ServiceKey를 제거한 메시지만 담아야 한다.
    """


@dataclass(frozen=True)
class NaraGatewayResponse:
    """gateway가 돌려주는 한 페이지의 파싱 완료 응답."""

    records: "list[dict[str, str]]" = field(default_factory=list)
    result_code: str = ""
    result_msg: str = ""
    field_labels: "dict[str, str]" = field(default_factory=dict)


class NaraGatewayPort(Protocol):
    """Application이 요구하는 나라장터 취득 효과."""

    def fetch(
        self,
        service_key: str,
        bgn: str,
        end: str,
        *,
        num_rows: int,
        page_no: int,
    ) -> NaraGatewayResponse: ...

    def probe(
        self,
        service_key: str,
        bgn: str,
        end: str,
        *,
        num_rows: int,
        page_no: int,
    ) -> NaraGatewayResponse:
        """본문을 소비하지 않고 응답 헤더로 키 유효성만 확인한다."""
        ...


def _union_fields(records: "list[dict[str, str]]") -> "list[str]":
    """레코드 필드 키를 등장 순서로 중복 제거한다."""
    seen: "set[str]" = set()
    keys: "list[str]" = []
    for record in records:
        for key in record:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


class AcquiredNaraData:
    """취득 완료된 키 없는 나라장터 레코드 스냅샷."""

    def __init__(
        self,
        records: "list[dict[str, str]]",
        fields: "list[str]",
        field_labels: "dict[str, str] | None" = None,
    ):
        self._records = list(records)
        self._fields = list(fields)
        self._field_labels = dict(
            _FIELD_LABELS if field_labels is None else field_labels
        )

    def records(self) -> "list[dict[str, str]]":
        return list(self._records)

    def fields(self) -> "list[str]":
        return list(self._fields)

    def field_labels(self) -> "dict[str, str]":
        return dict(self._field_labels)

    def source_pointer(self) -> str:
        """원장에 남길 포인터-온리 소스 표기(DataSource 선택 프로토콜)."""
        return "nara:취득 스냅샷(키 미포함)"


@dataclass
class AcquireResult:
    """취득 1회의 결과와 그때의 조회 조건 스냅샷."""

    ok: bool
    records: "list[dict[str, str]]" = field(default_factory=list)
    fields: "list[str]" = field(default_factory=list)
    result_code: str = ""
    result_msg: str = ""
    error: str = ""
    bgn_dt: str = ""
    end_dt: str = ""
    num_rows: int = 0
    page_no: int = 0
    # 기존 positional ABI 뒤에만 확장 필드를 둔다.
    field_labels: "dict[str, str] | None" = None

    @property
    def count(self) -> int:
        return len(self.records)

    @property
    def acceptable(self) -> bool:
        """수용 가능 = 성공 그리고 1건 이상."""
        return self.ok and bool(self.records)

    def source_label(self) -> str:
        return f"나라장터 · {self.bgn_dt}~{self.end_dt} · {self.count}건"

    def as_datasource(self) -> AcquiredNaraData:
        return AcquiredNaraData(self.records, self.fields, self.field_labels)

    def summary(self) -> str:
        if not self.ok:
            return f"취득 실패: {self.error}"
        if not self.records:
            return "취득 0건 — 기간·페이지를 확인하세요(응답은 정상)."
        return f"{self.count}건 취득."


@dataclass
class ConnResult:
    """연결 시험 결과 — 키 유효성만 본다."""

    ok: bool
    message: str


class NaraAcquireViewModel:
    """나라장터 키 등록 + 취득 상태/결정.

    ``store``·``gateway``·``clock``은 composition root가 주입한다. 이 클래스는 OS
    credential backend, HTTP 구현, wall clock을 직접 선택하지 않는다.
    """

    validate_range = staticmethod(validate_range)

    def __init__(
        self,
        store: SecretStorePort,
        gateway: NaraGatewayPort,
        *,
        secret_name: str,
        clock: "Callable[[], datetime]",
    ):
        if not secret_name:
            raise ValueError("나라장터 비밀 이름이 비어 있습니다.")
        self._store = store
        self._gateway = gateway
        self._secret_name = secret_name
        self._clock = clock
        self.last_result: "AcquireResult | None" = None

    # --------------------------------------------------------------- 키 등록
    def is_registered(self) -> bool:
        return self._store.has(self._secret_name)

    def status_label(self) -> str:
        return "등록됨" if self.is_registered() else "미등록"

    def save_key(self, key: str) -> None:
        key = (key or "").strip()
        if not key:
            raise ValueError("서비스키가 비어 있습니다. 값을 입력하세요.")
        self._store.set(self._secret_name, key)

    def delete_key(self) -> None:
        self._store.delete(self._secret_name)

    # --------------------------------------------------------------- 취득
    def acquire(
        self, bgn: str, end: str, *, num_rows: int = 100, page_no: int = 1
    ) -> AcquireResult:
        result = self.acquire_result(bgn, end, num_rows=num_rows, page_no=page_no)
        self.commit(result)
        return result

    def acquire_result(
        self, bgn: str, end: str, *, num_rows: int = 100, page_no: int = 1
    ) -> AcquireResult:
        """취득 계산만 수행하고 ``last_result``는 바꾸지 않는다."""
        result = self._acquire(bgn, end, num_rows=num_rows, page_no=page_no)
        result.bgn_dt, result.end_dt = bgn, end
        result.num_rows, result.page_no = num_rows, page_no
        return result

    def commit(self, result: AcquireResult) -> None:
        self.last_result = result if result.acceptable else None

    def invalidate(self) -> None:
        self.last_result = None

    def _acquire(
        self, bgn: str, end: str, *, num_rows: int, page_no: int
    ) -> AcquireResult:
        key = self._store.get(self._secret_name)
        if not key:
            return AcquireResult(
                ok=False,
                error="서비스키가 등록되어 있지 않습니다. 먼저 키를 등록하세요.",
            )
        range_error = validate_range(bgn, end)
        if range_error:
            return AcquireResult(ok=False, error=range_error)
        try:
            response = self._gateway.fetch(
                key,
                bgn,
                end,
                num_rows=num_rows,
                page_no=page_no,
            )
        except Exception:  # noqa: BLE001 - adapter 원문/키는 Application 표면에 내보내지 않는다
            return AcquireResult(ok=False, error=_GATEWAY_FAILURE)
        if response.result_code != OK_RESULT_CODE:
            return AcquireResult(
                ok=False,
                result_code=response.result_code,
                result_msg=response.result_msg,
                error=(
                    f"API 오류 [{response.result_code or '코드 없음'}] "
                    f"{response.result_msg or '메시지 없음'}"
                ),
            )
        records = list(response.records)
        return AcquireResult(
            ok=True,
            records=records,
            fields=_union_fields(records),
            field_labels=dict(response.field_labels),
            result_code=response.result_code,
            result_msg=response.result_msg,
        )

    def test_connection(self) -> ConnResult:
        key = self._store.get(self._secret_name)
        if not key:
            return ConnResult(False, "서비스키가 등록되어 있지 않습니다. 먼저 키를 등록하세요.")
        now = self._clock()
        bgn = (now - timedelta(days=1)).strftime(DT_FMT)
        end = now.strftime(DT_FMT)
        try:
            response = self._gateway.probe(
                key,
                bgn,
                end,
                num_rows=1,
                page_no=1,
            )
        except Exception:  # noqa: BLE001 - adapter 원문/키는 Application 표면에 내보내지 않는다
            return ConnResult(False, f"연결 실패: {_GATEWAY_FAILURE}")
        if response.result_code != OK_RESULT_CODE:
            return ConnResult(
                False,
                "연결 실패 — API 오류 "
                f"[{response.result_code or '코드 없음'}] "
                f"{response.result_msg or '메시지 없음'}",
            )
        return ConnResult(True, "연결 성공 — 키가 유효합니다.")


__all__ = [
    "DT_FMT",
    "AcquiredNaraData",
    "AcquireResult",
    "ConnResult",
    "NaraAcquireViewModel",
    "NaraGatewayError",
    "NaraGatewayPort",
    "NaraGatewayResponse",
    "SecretStorePort",
    "validate_range",
]
