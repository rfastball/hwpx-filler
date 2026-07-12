"""나라장터 취득 ViewModel — Qt 비의존(링1). 키 등록/취득 결정의 단일 진실원.

위젯(:class:`~hwpxfiller.gui.nara_view.NaraAcquireDialog`)은 이 뷰모델을 들고
``save_key``/``delete_key``/``test_connection``/``acquire`` 로 **오케스트레이션만** 한다.
키 저장(N1 :class:`~hwpxfiller.data.secret_store.SecretStore`)·기간 검증(1개월 제한)·
취득/파싱·redaction 경계는 전부 여기 산다 — PySide6 임포트 없이 헤드리스로 테스트된다
(home_state↔home 분리를 그대로 미러링).

**보안 불변식**([[confirm-or-alarm-principle]]):
- 키는 **N1 SecretStore 경유로만** 오간다. 뷰모델은 키를 인스턴스 속성으로 붙들지 않고
  취득 순간에 저장소에서 읽어 :class:`~hwpxfiller.data.nara.NaraStdDataSource` 에 넘긴다.
- 취득 결과(:class:`AcquireResult`)는 **키 없는 스냅샷**(:class:`AcquiredNaraData`)만 노출한다
  — 위저드 세션이 드는 ``datasource`` 자리에 키가 남지 않는다(직렬화 표면 0).
- 모든 오류 문자열은 :func:`~hwpxfiller.data.secret_store.redact` 를 관통해 표면화한다
  (네트워크 예외가 요청 URL·키를 품어도 마스킹된 뒤에만 사용자에게 닿는다).

**새 코어 없음.** 취득/파싱/마스킹은 전부 N1 이 착지한 ``data.nara``·``data.secret_store`` 재사용.
"""

from __future__ import annotations

import calendar
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..data.nara import NaraFetchError, NaraStdDataSource
from ..data.secret_store import (
    NARA_SERVICE_KEY_NAME,
    SecretStore,
    default_secret_store,
    redact,
)

#: 나라 API 일시 포맷(``bidNtceBgnDt``/``bidNtceEndDt``) — YYYYMMDDHHMM.
DT_FMT = "%Y%m%d%H%M"

#: 정상 응답 헤더 코드(그 외는 인증/파라미터 오류로 시끄럽게 실패).
_OK_CODE = "00"


def _add_one_month(dt: datetime) -> datetime:
    """``dt`` 에 한 달을 더한다(말일 클램프: 1/31 + 1달 = 2/28·29)."""
    month = dt.month + 1
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def _union_fields(records: "list[dict[str, str]]") -> "list[str]":
    """레코드가 제공하는 필드 키를 등장 순서(중복 제거)로 — ``NaraStdDataSource.fields`` 와 동치.

    이미 취득한 레코드에서 계산하므로 재-fetch(재-키사용) 없이 매핑 후보 컬럼을 낸다.
    """
    seen: "set[str]" = set()
    keys: "list[str]" = []
    for rec in records:
        for k in rec:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    return keys


class AcquiredNaraData:
    """취득 완료된 나라장터 레코드 스냅샷 — **키 없이** 매핑 어휘·레코드만 노출.

    위저드 세션의 ``datasource`` 자리에 이걸 둔다: :class:`~hwpxfiller.data.base.DataSource`
    프로토콜(``records``+``fields``)을 만족하고 ``field_labels`` 로 소스 어휘를 제공하되,
    ServiceKey 는 **품지 않는다**(취득은 이미 끝났고, 매핑 단계는 어휘·샘플만 필요).
    이로써 키가 위저드/작업 직렬화 표면에 절대 닿지 않는다.
    """

    def __init__(self, records: "list[dict[str, str]]", fields: "list[str]"):
        self._records = list(records)
        self._fields = list(fields)

    def records(self) -> "list[dict[str, str]]":
        return list(self._records)

    def fields(self) -> "list[str]":
        return list(self._fields)

    def field_labels(self) -> "dict[str, str]":
        """소스 키(영문 코드) → 한글 라벨. 소스가 어휘를 소유한다(코어 아님, V1)."""
        return NaraStdDataSource.field_labels()


@dataclass
class AcquireResult:
    """취득 1회의 결과 — 성공(레코드·필드) 또는 시끄러운 실패(마스킹된 ``error``).

    ``bgn_dt``~``page_no`` 는 **취득 시점 쿼리 스냅샷** — 이후 위젯 편집과 무관하게
    이 결과가 어떤 쿼리의 산물인지 붙들어, 풀 등록·라벨이 위젯 현재값을 재독하지
    않게 한다(RC-13 이중 소스 차단).
    """

    ok: bool
    records: "list[dict[str, str]]" = field(default_factory=list)
    fields: "list[str]" = field(default_factory=list)
    result_code: str = ""
    result_msg: str = ""
    error: str = ""
    # 취득 시점 쿼리 스냅샷(acquire 가 스탬프) — 성공·실패 공통.
    bgn_dt: str = ""
    end_dt: str = ""
    num_rows: int = 0
    page_no: int = 0

    @property
    def count(self) -> int:
        return len(self.records)

    @property
    def acceptable(self) -> bool:
        """수용 가능(=매핑 진행 허용) 여부 — 성공 **그리고** 1건 이상(0건 수용 불가 정책).

        '0건 수용 불가' 도메인 정책의 단일 출처 — 뷰가 ``ok and records`` 를 재합성하지
        않는다(RC-24).
        """
        return self.ok and bool(self.records)

    def source_label(self) -> str:
        """수용 시 세션·풀에 표시할 소스 라벨 — 취득 시점 기간·건수로 조합(위젯값 아님)."""
        return f"나라장터 · {self.bgn_dt}~{self.end_dt} · {self.count}건"

    def as_datasource(self) -> AcquiredNaraData:
        """매핑에 붙일 키 없는 스냅샷 어댑터."""
        return AcquiredNaraData(self.records, self.fields)

    def summary(self) -> str:
        if not self.ok:
            return f"취득 실패: {self.error}"
        if not self.records:
            return "취득 0건 — 기간·페이지를 확인하세요(응답은 정상)."
        return f"{self.count}건 취득."


@dataclass
class ConnResult:
    """연결 시험 결과 — 키 유효성만 본다(레코드 취득 아님)."""

    ok: bool
    message: str


class NaraAcquireViewModel:
    """나라장터 키 등록 + 취득 상태/결정. 위젯은 이 뷰모델을 구독해 렌더한다(Qt 비의존).

    ``store`` 는 주입 가능(테스트는 :class:`~hwpxfiller.data.secret_store.MemorySecretStore`
    를 넣어 실 자격증명 저장소 무접촉). ``fetcher``(url->bytes)도 주입 가능 —
    네트워크 없이 취득 경로를 검증한다(NaraStdDataSource 의 주입 이음새와 동일).
    """

    def __init__(
        self,
        store: "SecretStore | None" = None,
        *,
        fetcher=None,
        timeout: float = 20.0,
    ):
        self._store = store if store is not None else default_secret_store()
        self._fetcher = fetcher
        self._timeout = timeout
        #: '현재 취득' 원자 스냅샷 — 수용 가능한 성공 결과 전체 or None(부분 잔존 금지, RC-24).
        self.last_result: "AcquireResult | None" = None

    # --------------------------------------------------------------- 키 등록
    def is_registered(self) -> bool:
        return self._store.has(NARA_SERVICE_KEY_NAME)

    def status_label(self) -> str:
        return "등록됨" if self.is_registered() else "미등록"

    def save_key(self, key: str) -> None:
        """키 등록/교체 — 공백 제거 후 저장. 빈 키는 시끄럽게 거절(조용한 무저장 금지).

        저장은 N1 SecretStore 경유(OS 자격증명, 사용자 스코프). 값은 여기서 로그·직렬화하지
        않는다 — 저장소만이 값을 안다.
        """
        key = (key or "").strip()
        if not key:
            raise ValueError("서비스키가 비어 있습니다. 값을 입력하세요.")
        self._store.set(NARA_SERVICE_KEY_NAME, key)

    def delete_key(self) -> None:
        """저장된 키 삭제(없어도 무연산 — 멱등)."""
        self._store.delete(NARA_SERVICE_KEY_NAME)

    # --------------------------------------------------------------- 기간 검증
    @staticmethod
    def validate_range(bgn: str, end: str) -> "str | None":
        """시작~종료 일시 검증(YYYYMMDDHHMM·1개월 제한). 통과면 ``None``, 아니면 사유 문자열."""
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

    # --------------------------------------------------------------- 취득
    def _build_source(
        self, key: str, bgn: str, end: str, num_rows: int, page_no: int
    ) -> NaraStdDataSource:
        return NaraStdDataSource(
            key, bgn, end,
            num_rows=num_rows, page_no=page_no,
            timeout=self._timeout, fetcher=self._fetcher,
        )

    def _fetch_raw(self, src: NaraStdDataSource) -> bytes:
        """원시 응답 바이트 취득 — 예외는 키 마스킹 후 :class:`NaraFetchError` 로 재발생.

        ``records()`` 대신 raw 를 잡는 이유: 응답 헤더의 ``resultCode`` 를 봐야 인증 실패
        (HTTP 200 + 빈 body)를 진짜 0건과 구별할 수 있다(브리핑 인수조건). 파싱은 호출측이
        ``NaraStdDataSource.parse``/``result`` 로 수행한다(어휘·파싱 로직 재사용, 중복 0).
        """
        try:
            if self._fetcher is not None:
                return self._fetcher(src.url())
            with urllib.request.urlopen(src.url(), timeout=src.timeout) as resp:
                return resp.read()
        except NaraFetchError:
            raise
        except Exception as exc:
            # urlopen/주입 fetcher 예외는 요청 URL(키 포함)을 품을 수 있다 → 마스킹 후 재발생.
            raise NaraFetchError(redact(str(exc), src.service_key)) from None

    def acquire(
        self, bgn: str, end: str, *, num_rows: int = 100, page_no: int = 1
    ) -> AcquireResult:
        """저장된 키로 취득. 키 미등록/기간 오류/네트워크 오류/인증 실패를 각각 시끄럽게 구별.

        성공은 레코드+필드+정상 코드, 실패는 **마스킹된** 사유. 키는 저장소에서 이 순간에만
        읽어 소스에 넘기고 반환값엔 남기지 않는다.

        결과엔 취득 시점 쿼리(기간·건수)가 스탬프되고, :attr:`last_result` 는 **원자로**
        갱신된다 — 수용 가능한 성공이면 결과 전체, 아니면 ``None``(이전 성공값의 부분
        잔존 금지, RC-24).
        """
        res = self._acquire(bgn, end, num_rows=num_rows, page_no=page_no)
        res.bgn_dt, res.end_dt = bgn, end
        res.num_rows, res.page_no = num_rows, page_no
        self.last_result = res if res.acceptable else None
        return res

    def invalidate(self) -> None:
        """현재 취득 스냅샷 폐기 — 취득 후 입력(기간·건수)이 편집돼 결과와 어긋날 때(RC-13).

        수용 게이트가 이 스냅샷 유무를 따르므로, 폐기는 곧 '다시 가져오기 전 수용 불가'다.
        """
        self.last_result = None

    def _acquire(
        self, bgn: str, end: str, *, num_rows: int, page_no: int
    ) -> AcquireResult:
        key = self._store.get(NARA_SERVICE_KEY_NAME)
        if not key:
            return AcquireResult(
                ok=False,
                error="서비스키가 등록되어 있지 않습니다. 먼저 키를 등록하세요.",
            )
        rng_err = self.validate_range(bgn, end)
        if rng_err:
            return AcquireResult(ok=False, error=rng_err)
        src = self._build_source(key, bgn, end, num_rows, page_no)
        try:
            raw = self._fetch_raw(src)
            code, msg = NaraStdDataSource.result(raw)
            records = NaraStdDataSource.parse(raw)
        except NaraFetchError as exc:
            return AcquireResult(ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - 파싱 오류도 마스킹 경계 안에서 시끄럽게
            return AcquireResult(ok=False, error=redact(str(exc), key))
        if code != _OK_CODE:
            # 정상('00') 아닌 모든 응답은 시끄럽게 실패 — 인증/파라미터 오류(예 "07")뿐 아니라
            # **resultCode 부재(빈 코드)** 도 규격 밖이라 fail-closed(빈 목록을 조용한 성공 금지).
            return AcquireResult(
                ok=False, result_code=code, result_msg=msg,
                error=f"API 오류 [{code or '코드 없음'}] {msg or '메시지 없음'}",
            )
        return AcquireResult(
            ok=True, records=records, fields=_union_fields(records),
            result_code=code, result_msg=msg,
        )

    def test_connection(self) -> ConnResult:
        """저장된 키의 유효성만 시험 — 최근 1일·1건 요청으로 인증 응답을 확인(취득 아님)."""
        key = self._store.get(NARA_SERVICE_KEY_NAME)
        if not key:
            return ConnResult(False, "서비스키가 등록되어 있지 않습니다. 먼저 키를 등록하세요.")
        now = datetime.now()
        bgn = (now - timedelta(days=1)).strftime(DT_FMT)
        end = now.strftime(DT_FMT)
        src = self._build_source(key, bgn, end, 1, 1)
        try:
            raw = self._fetch_raw(src)
            code, msg = NaraStdDataSource.result(raw)
        except NaraFetchError as exc:
            return ConnResult(False, f"연결 실패: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ConnResult(False, f"연결 실패: {redact(str(exc), key)}")
        if code != _OK_CODE:
            # resultCode 부재('')도 규격 밖 → "유효한 키" 라고 조용히 답하지 않는다(fail-closed).
            return ConnResult(
                False, f"연결 실패 — API 오류 [{code or '코드 없음'}] {msg or '메시지 없음'}"
            )
        return ConnResult(True, "연결 성공 — 키가 유효합니다.")
