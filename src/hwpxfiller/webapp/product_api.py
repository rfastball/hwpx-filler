"""Python→웹 제품 통로의 **버전 있는 단일 파사드 어댑터**(N-07).

종전에 app.py 는 제품 자리 다섯 곳에서 웹 전역을 **이름으로** 직접 겨눴다: 화면 스냅샷 푸시,
종료 확인창, 개인화 주입, 테마 주입, 창 경보. 전역 이름 다섯 개가 곧 계약이었고, 프런트가
이름을 옮기면 Python 은 **조용히 `false`/`None` 을 받아** 아무 일도 안 일어난 것과 구분되지
않았다(테마 주입만 `err` 로 시끄러웠고 푸시·종료 확인은 무경보였다).

이 모듈은 그 다섯을 **하나의 뿌리** `window.__hwpx` 로 접는다. 파사드는 자기 프로토콜과
버전과 능력을 스스로 말하고(`describe()`), 요청은 봉투 하나로 들어가며(`deliver()`),
결과는 구조화돼 돌아온다. 그래서 "이름이 없다"와 "이름은 있는데 거절했다"가 서로 다른
타입의 실패로 갈린다 — 조용한 하강(구 전역으로의 폴백)은 **없다**. 여기 legacy 전역 이름은
한 글자도 등장하지 않는다.

## 계약 v1

    window.__hwpx.describe()
    // -> {protocol: "hwpx-product", version: 1,
    //     capabilities: ["snapshot", "close-request", "preferences", "notice"]}

    window.__hwpx.deliver({version: 1, event, payload})
    // -> 동기 JSON-직렬화 가능 결과. {ok: true, ...} 또는 {ok: false, code, ...}

| 오늘의 Python 호출 | event | payload |
|---|---|---|
| 화면 스냅샷 푸시 | ``snapshot`` | ``{screen, snapshot}`` |
| 종료 확인창 요청 | ``close-request`` | ``{state}`` |
| 개인화+테마 주입 | ``preferences`` | ``{personalization, theme?}`` |
| 창 경보 문안 | ``notice`` | ``{message}`` |

``preferences`` 는 **종전 두 호출을 하나로 접는다**. 종전엔 실패 문안이 개인화/테마로 갈렸고
그 구분은 진단에 실질이 있으므로(어느 주입이 죽었는지 = 어느 모듈이 안 실렸는지), 이 어댑터는
그 갈림을 **구조화된 결과에서 되찾는다** — :class:`PreferencesOutcome` 의 ``failed`` 가 그것이다.

## 경계

- app.py 를 import 하지 않는다(순환 회피). pywebview 도 모른다 — 평가기는 **주입**이라
  헤드리스로 단위 검증된다.
- JS 표현식 조립은 전부 여기 있다. app.py 가 문자열을 손으로 잇는 자리는 남기지 않는다.
- 이 모듈이 내는 모든 표현식의 뿌리는 `window.__hwpx` 뿐이고, 호출 메서드는
  ``describe`` · ``deliver`` 둘뿐이다(:data:`_METHODS` 가 강제).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from . import settings

# ------------------------------------------------------------------ 계약 상수

#: 파사드가 자기 정체로 말해야 하는 프로토콜 이름.
PROTOCOL = "hwpx-product"

#: 이 어댑터가 말할 줄 아는 유일한 버전. 다른 값은 협상이 아니라 **거절**이다.
VERSION = 1

#: 요구 능력 — 순서가 계약이다(파사드 describe() 의 배열과 같은 순서로 읽힌다).
CAPABILITIES: tuple[str, ...] = ("snapshot", "close-request", "preferences", "notice")

#: 파사드 뿌리. 이 모듈이 내는 표현식에 등장하는 유일한 전역이다.
ROOT = "window.__hwpx"

# 허용 메서드 화이트리스트 — 표현식 조립이 임의 이름으로 새지 않게 한다.
_METHODS = ("describe", "deliver")

EVENT_SNAPSHOT = "snapshot"
EVENT_CLOSE_REQUEST = "close-request"
EVENT_PREFERENCES = "preferences"
EVENT_NOTICE = "notice"

#: 능력 이름과 이벤트 이름은 v1 에서 1:1 이다(별도 표를 두면 둘이 갈라진다).
EVENTS: tuple[str, ...] = CAPABILITIES

#: 주입 대상 부분 — preferences 실패 귀속의 어휘.
PART_PERSONALIZATION = "personalization"
PART_THEME = "theme"

_PART_LABELS = {PART_PERSONALIZATION: "개인화", PART_THEME: "테마"}

#: 창에 실어 보내는 테마 값 — 그 밖(``system`` 등)은 payload 에서 **빠진다**.
THEME_VALUES = ("light", "dark")

#: 창 경보 문안 접두 — 내구성 채널(settings.alert)이 stderr 에 붙이는 것과 같은 표식.
NOTICE_PREFIX = "[hwpx] "

# ------------------------------------------------------------------ 실패 코드

CODE_FACADE_ABSENT = "facade-absent"
CODE_EVALUATE_FAILED = "evaluate-failed"
CODE_DESCRIPTOR_MALFORMED = "descriptor-malformed"
CODE_PROTOCOL_MISMATCH = "protocol-mismatch"
CODE_VERSION_UNSUPPORTED = "version-unsupported"
CODE_CAPABILITY_MISSING = "capability-missing"
CODE_RESULT_NOT_OBJECT = "result-not-object"
CODE_RESULT_MISSING_OK = "result-missing-ok"
CODE_RESULT_OK_NOT_BOOL = "result-ok-not-bool"
CODE_REJECTED = "rejected"
CODE_PAYLOAD_UNSERIALIZABLE = "payload-unserializable"
CODE_INTERNAL = "adapter-internal"


class ProductApiError(Exception):
    """제품 파사드 통로의 타입 있는 실패 — app.py 가 그대로 경보 문안으로 쓴다.

    ``code`` 는 기계가 가르는 안정 식별자, ``detail`` 은 사람이 읽는 사유,
    ``event`` 는 어느 통로였는지(describe 단계면 ``None``)다.
    """

    def __init__(self, code: str, detail: str, *, event: "str | None" = None) -> None:
        self.code = code
        self.detail = detail
        self.event = event
        where = f"{event} " if event else ""
        super().__init__(f"{where}[{code}] {detail}")


class FacadeAbsentError(ProductApiError):
    """`window.__hwpx` 자체가 없다 — 자산 미주입·평가 실패. 거절과 **다른 사건**이다."""


class TransportError(ProductApiError):
    """평가기(evaluate_js) 가 던졌다 — 창이 이미 죽었거나 백엔드가 실패했다."""


class DescriptorError(ProductApiError):
    """describe() 가 계약을 만족하지 못한다 — 버전·프로토콜·능력·형식."""


class DeliveryError(ProductApiError):
    """deliver() 가 거절했거나 계약 밖 형태로 답했다."""


# ------------------------------------------------------------------ 직렬화


def encode_js_literal(value: object) -> str:
    """JSON 값을 JS 표현식에 그대로 박을 수 있는 리터럴 문자열로.

    - ``ensure_ascii=False`` 가 기본이다(app.py 의 기존 관행 = 한글이 로그·표현식에서 읽힌다).
    - **짝 없는 서로게이트**는 UTF-8 로 실려 나갈 수 없다. 그 경우에만 ``ensure_ascii=True``
      로 다시 떠 ``\\uXXXX`` 이스케이프로 무손실 대피한다 — 값을 버리거나 대체 문자로
      갈아치우지 않는다(조용한 손실 금지).
    - ``U+2028``·``U+2029`` 는 JS 소스에서 줄 종결자로 읽힐 수 있어 항상 이스케이프한다.
    - ``NaN``·``Infinity``·직렬화 불가 객체는 JSON 이 아니므로 **시끄럽게** 거절한다.
    """
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ProductApiError(
            CODE_PAYLOAD_UNSERIALIZABLE, f"JSON 으로 실을 수 없는 값: {exc}"
        ) from exc
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = json.dumps(value, ensure_ascii=True, allow_nan=False)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def request_envelope(event: str, payload: Mapping[str, object]) -> dict:
    """`deliver()` 봉투 — ``{version, event, payload}``. 도메인 값은 손대지 않는다."""
    if event not in EVENTS:
        raise ProductApiError(CODE_INTERNAL, f"계약에 없는 event: {event!r}")
    return {"version": VERSION, "event": event, "payload": dict(payload)}


def _expression(method: str, argument: str = "") -> str:
    """`window.__hwpx` 만을 뿌리로 하는 표현식. 부재는 예외가 아니라 ``null`` 로 돌아온다."""
    if method not in _METHODS:
        raise ProductApiError(CODE_INTERNAL, f"허용되지 않은 파사드 메서드: {method!r}")
    return f"{ROOT} ? {ROOT}.{method}({argument}) : null"


def describe_expression() -> str:
    """파사드 자기소개 표현식."""
    return _expression("describe")


def deliver_expression(event: str, payload: Mapping[str, object]) -> str:
    """봉투 하나를 실어 보내는 표현식."""
    return _expression("deliver", encode_js_literal(request_envelope(event, payload)))


# --------------------------------------------------- 이벤트별 payload·표현식


def snapshot_payload(screen: str, snapshot: Mapping[str, object]) -> dict:
    """관측 푸시 payload — 화면 id 와 링1 스냅샷을 그대로."""
    return {"screen": screen, "snapshot": dict(snapshot)}


def close_request_payload(state: Mapping[str, object]) -> dict:
    """종료 확인 payload — `close_guard_state()` 판정을 그대로."""
    return {"state": dict(state)}


def preferences_payload(personalization: Mapping[str, object], theme: object = None) -> dict:
    """환경설정 payload. ``theme`` 은 영속값이 ``light``/``dark`` 일 때만 실린다.

    그 밖(``system``·미저장)은 **키 자체가 없다** — 빈 값을 실어 프런트가 추측하게 두지 않는다.
    """
    payload: dict = {"personalization": dict(personalization)}
    if theme in THEME_VALUES:
        payload["theme"] = theme
    return payload


def notice_payload(message: str) -> dict:
    """창 경보 payload. 접두는 내구성 채널이 stderr 에 붙이는 것과 같은 표식을 쓴다."""
    return {"message": NOTICE_PREFIX + message}


def snapshot_expression(screen: str, snapshot: Mapping[str, object]) -> str:
    return deliver_expression(EVENT_SNAPSHOT, snapshot_payload(screen, snapshot))


def close_request_expression(state: Mapping[str, object]) -> str:
    return deliver_expression(EVENT_CLOSE_REQUEST, close_request_payload(state))


def preferences_expression(personalization: Mapping[str, object], theme: object = None) -> str:
    return deliver_expression(EVENT_PREFERENCES, preferences_payload(personalization, theme))


def notice_expression(message: str) -> str:
    return deliver_expression(EVENT_NOTICE, notice_payload(message))


# ------------------------------------------------------------------ describe


@dataclass(frozen=True)
class Descriptor:
    """검증을 통과한 파사드 자기소개."""

    protocol: str
    version: int
    capabilities: tuple[str, ...]


def parse_descriptor(raw: object) -> Descriptor:
    """`describe()` 반환을 :class:`Descriptor` 로. 계약 위반은 전부 예외다(하강 없음).

    ``None`` 은 **파사드 부재**(:class:`FacadeAbsentError`)이고, 그 밖의 위반은
    :class:`DescriptorError` 다 — app.py 가 두 사건을 다른 문안으로 알릴 수 있게 타입이 갈린다.
    """
    if raw is None:
        raise FacadeAbsentError(CODE_FACADE_ABSENT, f"{ROOT} 부재(describe() 반환=None)")
    if not isinstance(raw, Mapping):
        raise DescriptorError(
            CODE_DESCRIPTOR_MALFORMED, f"describe() 반환이 객체가 아니다: {raw!r}"
        )
    protocol = raw.get("protocol")
    if protocol != PROTOCOL:
        raise DescriptorError(
            CODE_PROTOCOL_MISMATCH,
            f"프로토콜 불일치: {protocol!r} (기대 {PROTOCOL!r})",
        )
    version = _descriptor_version(raw)
    capabilities = _descriptor_capabilities(raw)
    return Descriptor(PROTOCOL, version, capabilities)


def _descriptor_version(raw: Mapping) -> int:
    """버전 필드 판독 — 부재·비수치·비지원을 **각각 다른 문안**으로 거절한다.

    JS 의 수는 브리지에 따라 float 로 실려 올 수 있어 정수값 float 는 받는다(``1.0`` = 1).
    소수부가 있으면 계약 밖이다.
    """
    if "version" not in raw:
        raise DescriptorError(CODE_VERSION_UNSUPPORTED, "describe() 에 version 필드가 없다")
    version = raw["version"]
    if isinstance(version, bool) or not isinstance(version, (int, float)):
        raise DescriptorError(CODE_VERSION_UNSUPPORTED, f"version 이 수가 아니다: {version!r}")
    if int(version) != version:
        raise DescriptorError(CODE_VERSION_UNSUPPORTED, f"version 이 정수가 아니다: {version!r}")
    if int(version) != VERSION:
        raise DescriptorError(
            CODE_VERSION_UNSUPPORTED,
            f"지원하지 않는 version: {version!r} (이 어댑터는 {VERSION})",
        )
    return VERSION


def _descriptor_capabilities(raw: Mapping) -> tuple[str, ...]:
    """능력 배열 판독 — 배열 아님·문자열 아닌 원소는 형식 위반."""
    capabilities = raw.get("capabilities")
    if isinstance(capabilities, (str, bytes)) or not isinstance(capabilities, Sequence):
        raise DescriptorError(
            CODE_DESCRIPTOR_MALFORMED,
            f"capabilities 가 배열이 아니다: {capabilities!r}",
        )
    if not all(isinstance(item, str) for item in capabilities):
        raise DescriptorError(
            CODE_DESCRIPTOR_MALFORMED,
            f"capabilities 원소가 문자열이 아니다: {capabilities!r}",
        )
    return tuple(capabilities)


def verify_descriptor(raw: object, required: "Iterable[str] | None" = None) -> Descriptor:
    """파싱 + 능력 점검. 하나라도 빠지면 부팅은 하강하지 않고 **거절**한다.

    파사드가 계약 밖 능력을 **더** 들고 있는 것은 막지 않는다(전방 호환) — 우리가 요구하는
    것이 전부 있는지만 본다.
    """
    descriptor = parse_descriptor(raw)
    wanted = tuple(CAPABILITIES if required is None else required)
    missing = [name for name in wanted if name not in descriptor.capabilities]
    if missing:
        raise DescriptorError(
            CODE_CAPABILITY_MISSING,
            f"능력 부재: {', '.join(missing)} (파사드 신고={list(descriptor.capabilities)})",
        )
    return descriptor


# ------------------------------------------------------------------ deliver 결과


@dataclass(frozen=True)
class DeliveryOutcome:
    """`deliver()` 한 번의 판정 — **던지지 않는 형태**.

    push 처럼 오늘 반환을 보지 않는 자리와, close-request 처럼 실패가 곧 경보인 자리가
    같은 판정을 공유하되 시끄러움의 정도는 호출자가 고른다(:meth:`raise_for_failure`).
    """

    event: str
    ok: bool
    code: str
    detail: str
    result: "dict | None" = None

    @property
    def facade_absent(self) -> bool:
        """파사드가 아예 없었나 — 구조화된 거절(`{ok: false}`)과 구분되는 축."""
        return self.code == CODE_FACADE_ABSENT

    @property
    def alarm_text(self) -> str:
        """경보 문안 — app.py 가 `_alarm(...)` 에 그대로 넣는다."""
        return f"{self.event} 전달 실패 [{self.code}] {self.detail}"

    def raise_for_failure(self) -> "DeliveryOutcome":
        """실패면 타입 있는 예외로 승격. 성공이면 자기 자신을 돌려준다(체이닝용)."""
        if self.ok:
            return self
        if self.code == CODE_FACADE_ABSENT:
            raise FacadeAbsentError(self.code, self.detail, event=self.event)
        if self.code == CODE_EVALUATE_FAILED:
            raise TransportError(self.code, self.detail, event=self.event)
        raise DeliveryError(self.code, self.detail, event=self.event)


def classify_result(event: str, raw: object) -> DeliveryOutcome:
    """`deliver()` 반환 판정. 형태 위반도 성공으로 접지 않는다.

    - ``None`` → 파사드 부재. 평가기가 없는 전역을 평가하면 이 값이 온다.
    - 객체 아님 / ``ok`` 부재 / ``ok`` 가 bool 아님 → 각각 다른 코드.
    - ``ok: false`` → 파사드가 준 ``code`` 를 그대로 진다(모르는 코드도 삼키지 않는다).
    """
    if raw is None:
        return DeliveryOutcome(
            event, False, CODE_FACADE_ABSENT, f"{ROOT} 부재(deliver() 반환=None)"
        )
    if not isinstance(raw, Mapping):
        return DeliveryOutcome(
            event, False, CODE_RESULT_NOT_OBJECT, f"deliver() 반환이 객체가 아니다: {raw!r}"
        )
    result = dict(raw)
    if "ok" not in result:
        return DeliveryOutcome(
            event, False, CODE_RESULT_MISSING_OK, f"결과에 ok 가 없다: {result!r}", result
        )
    ok = result["ok"]
    if not isinstance(ok, bool):
        return DeliveryOutcome(
            event, False, CODE_RESULT_OK_NOT_BOOL, f"ok 가 참/거짓이 아니다: {ok!r}", result
        )
    if ok:
        return DeliveryOutcome(event, True, "ok", "", result)
    code = result.get("code")
    code = code if isinstance(code, str) and code else CODE_REJECTED
    return DeliveryOutcome(event, False, code, f"파사드가 거절했다: {result!r}", result)


# ------------------------------------------------------------ preferences 귀속


@dataclass(frozen=True)
class PreferencesOutcome:
    """환경설정 주입 판정 — **어느 부분이 죽었는지**까지 진다.

    종전 두 호출(개인화·테마)이 하나로 접혔으므로, 그 갈림은 여기서 구조화된 결과로 되찾는다.
    귀속 단서가 하나도 없으면 (귀속 불명) 을 붙여 **전부 실패로** 본다 — 모르는 것을
    성공으로 접지 않는다.
    """

    delivery: DeliveryOutcome
    expected: tuple[str, ...]
    applied: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    attributed: bool = True
    notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def theme_sent(self) -> bool:
        return PART_THEME in self.expected

    @property
    def failure_text(self) -> "str | None":
        """경보 문안 — 실패가 없으면 ``None``."""
        if self.ok:
            return None
        parts = ", ".join(_PART_LABELS[name] for name in self.failed)
        suffix = "" if self.attributed else " (귀속 불명)"
        return f"환경설정 주입 실패: {parts}{suffix} [{self.delivery.code}] {self.delivery.detail}"


def classify_preferences(raw: object, *, theme_sent: bool) -> PreferencesOutcome:
    """`deliver()` 반환에서 곧장 환경설정 판정으로."""
    return preferences_outcome(classify_result(EVENT_PREFERENCES, raw), theme_sent=theme_sent)


def preferences_outcome(delivery: DeliveryOutcome, *, theme_sent: bool) -> PreferencesOutcome:
    """전달 판정에 **부분 귀속**을 얹는다 — ``applied`` 가 1차 단서, ``code`` 가 2차 단서.

    파사드가 ``{ok: true, applied: {personalization: true, theme: false}}`` 처럼 **부분 성공**을
    신고하면 ``ok`` 가 참이어도 실패로 본다(종전 ``personalized is not True`` 와 같은 엄격도).
    """
    expected = (PART_PERSONALIZATION,) + ((PART_THEME,) if theme_sent else ())
    applied_parts = _applied_parts(delivery.result)
    if applied_parts is not None:
        applied = tuple(name for name in expected if name in applied_parts)
        failed = tuple(name for name in expected if name not in applied)
        if not failed and not delivery.ok:
            # 파사드가 전부 적용했다면서 ok:false — 모순은 삼키지 않고 전부 실패로 본다.
            return PreferencesOutcome(
                delivery,
                expected,
                (),
                expected,
                attributed=False,
                notes=("applied 와 ok 가 모순",),
            )
        return PreferencesOutcome(delivery, expected, applied, failed)
    missing_parts = _named_parts(delivery.result, "missing")
    if missing_parts is not None:
        failed = tuple(name for name in expected if name in missing_parts)
        applied = tuple(name for name in expected if name not in failed)
        if failed:
            return PreferencesOutcome(delivery, expected, applied, failed)
    if delivery.ok:
        return PreferencesOutcome(delivery, expected, expected, ())
    return PreferencesOutcome(delivery, expected, (), expected, attributed=False)


def _applied_parts(result: "dict | None") -> "frozenset[str] | None":
    """결과가 신고한 **실제 적용 조각**의 이름 집합 — 단서가 없으면 ``None``.

    파사드 계약(v1)은 ``applied: ["personalization", "theme"]`` 처럼 **이름 배열**이다. 과거
    설계 초안의 ``{personalization: true, theme: false}`` 사상(map)도 받아 준다 — 형태가 갈려도
    귀속을 잃지 않게 하려는 것이지 두 계약을 허용하려는 게 아니다. 어느 쪽도 아니면 ``None``
    을 돌려 2차 단서(``missing``)로 넘긴다.
    """
    if not isinstance(result, dict):
        return None
    applied = result.get("applied")
    if isinstance(applied, Mapping):
        return frozenset(
            name for name, value in applied.items() if isinstance(name, str) and value is True
        )
    return _coerce_names(applied)


def _named_parts(result: "dict | None", field: str) -> "frozenset[str] | None":
    """결과의 이름 배열 필드(``missing`` 등) — 없거나 형태가 틀리면 ``None``."""
    if not isinstance(result, dict):
        return None
    return _coerce_names(result.get(field))


def _coerce_names(value: object) -> "frozenset[str] | None":
    """문자열 배열만 이름 집합으로 — 문자열 자체는 배열이 아니므로 거절한다."""
    if isinstance(value, (list, tuple)) and all(isinstance(name, str) for name in value):
        return frozenset(value)
    return None


# ------------------------------------------------------------------ 클라이언트


class ProductApiClient:
    """창(평가기)에 묶인 얇은 클라이언트. 표현식 조립·판정을 한 자리에서 진다.

    평가기는 주입이다 — pywebview 를 모르므로 헤드리스 단위 검증이 된다. app.py 는
    :meth:`for_window` 로 창을 넘긴다.
    """

    def __init__(
        self,
        evaluate: Callable[[str], object],
        *,
        durable_alert: "Callable[[str], None] | None" = None,
    ) -> None:
        self._evaluate = evaluate
        self._durable_alert = durable_alert

    @classmethod
    def for_window(cls, window: object, **kwargs) -> "ProductApiClient":
        """pywebview 창을 감싼다 — 이 모듈이 pywebview 를 아는 유일한 접점(덕 타이핑)."""
        return cls(lambda expr: window.evaluate_js(expr), **kwargs)  # type: ignore[attr-defined]

    # -------------------------------------------------------------- describe

    def describe(self, required: "Iterable[str] | None" = None) -> Descriptor:
        """파사드 검증. 실패는 전부 예외 — 부팅이 조용히 구 동작으로 내려가지 않는다."""
        try:
            raw = self._evaluate(describe_expression())
        except Exception as exc:  # noqa: BLE001 — 평가 실패는 부재와 다른 사건이다
            raise TransportError(CODE_EVALUATE_FAILED, f"describe() 평가 실패: {exc!r}") from exc
        return verify_descriptor(raw, required)

    # ---------------------------------------------------------------- 전달

    def _deliver(self, event: str, payload: Mapping[str, object]) -> DeliveryOutcome:
        """봉투 전달 — **던지지 않는다**. 시끄러움의 정도는 호출자가 고른다."""
        try:
            raw = self._evaluate(deliver_expression(event, payload))
        except ProductApiError as exc:  # 직렬화 거절 등 — 코드 보존
            return DeliveryOutcome(event, False, exc.code, exc.detail)
        except Exception as exc:  # noqa: BLE001 — 창이 죽었을 수 있다
            return DeliveryOutcome(
                event, False, CODE_EVALUATE_FAILED, f"deliver() 평가 실패: {exc!r}"
            )
        return classify_result(event, raw)

    def push(self, screen: str, snapshot: Mapping[str, object]) -> DeliveryOutcome:
        """관측 푸시 — fire-and-forget. **성공 ack 를 요구하지 않는다**.

        느린 렌더러에서 반환을 기다리게 만들면 오늘 동작이 바뀐다. 그래서 판정은 돌려주되
        예외로 올리지 않는다 — 호출자가 무시해도 오늘과 같고, 로그로 쓰고 싶으면 쓴다.
        """
        return self._deliver(EVENT_SNAPSHOT, snapshot_payload(screen, snapshot))

    def close_request(self, state: Mapping[str, object]) -> DeliveryOutcome:
        """종료 확인창 요청 — 실패는 **fail-CLOSED**.

        종전엔 가드 부재가 조용한 no-op 이었다(창은 닫히지 않고 아무 안내도 없음). 이제
        판정이 실패면 호출자는 창을 유지한 채 경보한다 — :meth:`DeliveryOutcome.raise_for_failure`
        또는 ``ok`` 판독 중 어느 쪽으로 받아도 실패가 보인다.
        """
        return self._deliver(EVENT_CLOSE_REQUEST, close_request_payload(state))

    def preferences(
        self, personalization: Mapping[str, object], theme: object = None
    ) -> PreferencesOutcome:
        """개인화(+테마) 주입. 창이 아직 숨어 있는 동안 부른다 — show 는 호출자가 진다."""
        payload = preferences_payload(personalization, theme)
        theme_sent = PART_THEME in payload
        delivery = self._deliver(EVENT_PREFERENCES, payload)
        return preferences_outcome(delivery, theme_sent=theme_sent)

    def notice(self, message: str) -> DeliveryOutcome:
        """경보 문안 전달 — **내구성 채널이 먼저이고 권위다**.

        창 채널은 최선노력이다. 여기서의 실패로 다시 경보를 내면 재귀한다(경보를 알리려다
        경보를 낸다) — 그래서 이 메서드는 판정만 돌려주고 스스로는 절대 경보하지 않는다.
        """
        alert = settings.alert if self._durable_alert is None else self._durable_alert
        alert(message)
        return self._deliver(EVENT_NOTICE, notice_payload(message))
