"""제품 파사드 어댑터 계약 가드 — ``hwpxfiller.webapp.product_api`` (N-07).

이 층이 지켜야 하는 것은 세 가지다.

1. **뿌리가 하나다.** 어댑터가 내는 JS 표현식에 등장하는 전역은 ``window.__hwpx`` 뿐이다.
   구 전역 이름으로의 폴백이 한 글자라도 남으면, 파사드가 죽어도 앱이 반쯤 동작하며
   "이름을 옮겼다"는 사실이 조용히 묻힌다 — 그래서 표현식 문자열 자체를 센다.
2. **실패가 갈린다.** 파사드 부재(``None``)·프로토콜 불일치·버전 비지원·능력 부재·형태 위반·
   구조화된 거절은 서로 다른 사건이다. app.py 가 경보 문안에서 그 차이를 말할 수 있어야
   하므로 타입과 문안이 실제로 다른지 단언한다.
3. **접힌 두 호출의 갈림이 살아 있다.** 개인화·테마는 이제 ``preferences`` 한 번이지만
   "어느 쪽이 죽었나"는 종전과 같은 해상도로 남는다.

WebView2 는 뜨지 않는다 — 평가기는 주입이고 여기선 표현식을 기록하는 가짜다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hwpxfiller.webapp import product_api, settings
from hwpxfiller.webapp.product_api import (
    CAPABILITIES,
    PROTOCOL,
    ROOT,
    VERSION,
    DeliveryError,
    DeliveryOutcome,
    Descriptor,
    DescriptorError,
    FacadeAbsentError,
    ProductApiClient,
    ProductApiError,
    TransportError,
)

#: 구 전역 이름 — 어댑터가 내는 어떤 표현식에도, 모듈 소스에도 없어야 한다.
LEGACY_TOKENS = ("__push", "AppCloseGuard", "Theme", "Personalization", "window.alert")

GOOD_DESCRIPTOR = {
    "protocol": PROTOCOL,
    "version": VERSION,
    "capabilities": list(CAPABILITIES),
}


class FakeEvaluator:
    """표현식을 기록하고 미리 정한 값을 돌려주는 가짜 ``evaluate_js``."""

    def __init__(self, *returns, raises=None, log=None):
        self.calls: list[str] = []
        self.log = log if log is not None else []
        self._returns = list(returns)
        self._raises = raises

    def __call__(self, expression: str):
        self.calls.append(expression)
        self.log.append(("window", expression))
        if self._raises is not None:
            raise self._raises
        if not self._returns:
            return None
        return self._returns.pop(0)

    @property
    def last(self) -> str:
        return self.calls[-1]


def argument_of(expression: str) -> dict:
    """표현식에 박힌 리터럴을 되판다 — 배달된 것이 정확히 무엇인지 확인하는 유일한 방법."""
    match = re.fullmatch(
        rf"{re.escape(ROOT)} \? {re.escape(ROOT)}\.deliver\((?P<arg>.*)\) : null",
        expression,
        re.S,
    )
    assert match is not None, expression
    return json.loads(match.group("arg"))


# ------------------------------------------------------------------ 계약 상수


def test_contract_constants_are_the_agreed_v1():
    assert PROTOCOL == "hwpx-product"
    assert VERSION == 1
    assert CAPABILITIES == ("snapshot", "close-request", "preferences", "notice")
    assert ROOT == "window.__hwpx"
    # 능력과 이벤트는 v1 에서 같은 목록이다(표가 둘이면 갈라진다).
    assert product_api.EVENTS == CAPABILITIES
    assert (
        product_api.EVENT_SNAPSHOT,
        product_api.EVENT_CLOSE_REQUEST,
        product_api.EVENT_PREFERENCES,
        product_api.EVENT_NOTICE,
    ) == CAPABILITIES


# ------------------------------------------------------------------ describe


def test_descriptor_exact_match_passes():
    descriptor = product_api.verify_descriptor(GOOD_DESCRIPTOR)
    assert descriptor == Descriptor(PROTOCOL, 1, CAPABILITIES)


def test_descriptor_allows_extra_capabilities_but_not_missing_ones():
    forward = dict(GOOD_DESCRIPTOR, capabilities=[*CAPABILITIES, "future-thing"])
    assert product_api.verify_descriptor(forward).capabilities[-1] == "future-thing"


def test_describe_expression_is_rooted_and_names_nothing_else():
    expression = product_api.describe_expression()
    assert expression == "window.__hwpx ? window.__hwpx.describe() : null"
    for token in LEGACY_TOKENS:
        assert token not in expression


def test_facade_absent_is_its_own_type_and_not_a_descriptor_error():
    with pytest.raises(FacadeAbsentError) as absent:
        product_api.verify_descriptor(None)
    assert absent.value.code == product_api.CODE_FACADE_ABSENT
    # DescriptorError 와 형제일 뿐 상속 관계가 아니다 — except 로 갈린다.
    assert not isinstance(absent.value, DescriptorError)
    assert isinstance(absent.value, ProductApiError)


@pytest.mark.parametrize("raw", [42, "hwpx-product", ["snapshot"], True])
def test_malformed_descriptor_is_loud(raw):
    with pytest.raises(DescriptorError) as err:
        product_api.verify_descriptor(raw)
    assert err.value.code == product_api.CODE_DESCRIPTOR_MALFORMED


def test_wrong_protocol_is_its_own_code():
    with pytest.raises(DescriptorError) as err:
        product_api.verify_descriptor(dict(GOOD_DESCRIPTOR, protocol="hwpx-diff"))
    assert err.value.code == product_api.CODE_PROTOCOL_MISMATCH
    assert "hwpx-diff" in err.value.detail


def test_unsupported_versions_each_say_something_different():
    details: list[str] = []
    missing = {k: v for k, v in GOOD_DESCRIPTOR.items() if k != "version"}
    for raw in (missing, dict(GOOD_DESCRIPTOR, version=0), dict(GOOD_DESCRIPTOR, version=2)):
        with pytest.raises(DescriptorError) as err:
            product_api.verify_descriptor(raw)
        assert err.value.code == product_api.CODE_VERSION_UNSUPPORTED
        details.append(err.value.detail)
    for raw in (dict(GOOD_DESCRIPTOR, version="1"), dict(GOOD_DESCRIPTOR, version=True)):
        with pytest.raises(DescriptorError) as err:
            product_api.verify_descriptor(raw)
        assert err.value.code == product_api.CODE_VERSION_UNSUPPORTED
        details.append(err.value.detail)
    with pytest.raises(DescriptorError) as err:
        product_api.verify_descriptor(dict(GOOD_DESCRIPTOR, version=1.5))
    details.append(err.value.detail)
    # 부재 / 0 / 2 / 비수치 / bool / 소수 — 문안이 전부 다르다(진단이 뭉개지지 않는다).
    assert len(set(details)) == len(details)


def test_integral_float_version_is_accepted():
    """브리지가 JS 수를 float 로 실어 와도 1.0 은 1 이다 — 거짓 경보를 만들지 않는다."""
    assert product_api.verify_descriptor(dict(GOOD_DESCRIPTOR, version=1.0)).version == 1


@pytest.mark.parametrize("caps", [None, "snapshot", 7, ["snapshot", 3]])
def test_malformed_capabilities_are_loud(caps):
    with pytest.raises(DescriptorError) as err:
        product_api.verify_descriptor(dict(GOOD_DESCRIPTOR, capabilities=caps))
    assert err.value.code == product_api.CODE_DESCRIPTOR_MALFORMED


def test_missing_capability_names_what_is_missing():
    partial = dict(GOOD_DESCRIPTOR, capabilities=["snapshot", "notice"])
    with pytest.raises(DescriptorError) as err:
        product_api.verify_descriptor(partial)
    assert err.value.code == product_api.CODE_CAPABILITY_MISSING
    assert "close-request" in err.value.detail
    assert "preferences" in err.value.detail


def test_required_capabilities_can_be_narrowed():
    partial = dict(GOOD_DESCRIPTOR, capabilities=["snapshot"])
    assert product_api.verify_descriptor(partial, ["snapshot"]).capabilities == ("snapshot",)


def test_error_str_carries_event_and_code():
    err = ProductApiError("some-code", "사유", event="notice")
    assert "notice" in str(err) and "some-code" in str(err) and "사유" in str(err)
    assert "[some-code]" in str(ProductApiError("some-code", "사유"))


# ------------------------------------------------------------------ 표현식


def test_all_four_event_expressions_are_rooted_and_legacy_free():
    expressions = {
        "snapshot": product_api.snapshot_expression("job", {"rows": 3}),
        "close-request": product_api.close_request_expression({"armed": True, "reasons": []}),
        "preferences": product_api.preferences_expression({"font_scale": 1.0}, "dark"),
        "notice": product_api.notice_expression("무언가 잘못됐다"),
    }
    for event, expression in expressions.items():
        assert expression.startswith(f"{ROOT} ? {ROOT}.deliver("), event
        assert expression.endswith(") : null"), event
        # 뿌리 밖 전역 참조가 없다: window. 는 window.__hwpx 로만 등장한다.
        assert re.findall(r"window\.[A-Za-z_$]+", expression) == ["window.__hwpx"] * 2, event
        for token in LEGACY_TOKENS:
            assert token not in expression, (event, token)
        assert "__hwpxTest" not in expression


def test_envelope_shapes_match_the_agreed_table():
    assert argument_of(product_api.snapshot_expression("job", {"rows": 3})) == {
        "version": 1,
        "event": "snapshot",
        "payload": {"screen": "job", "snapshot": {"rows": 3}},
    }
    assert argument_of(product_api.close_request_expression({"armed": True})) == {
        "version": 1,
        "event": "close-request",
        "payload": {"state": {"armed": True}},
    }
    assert argument_of(product_api.preferences_expression({"font_scale": 1.0}, "dark")) == {
        "version": 1,
        "event": "preferences",
        "payload": {"personalization": {"font_scale": 1.0}, "theme": "dark"},
    }
    assert argument_of(product_api.notice_expression("경보")) == {
        "version": 1,
        "event": "notice",
        "payload": {"message": "[hwpx] 경보"},
    }


@pytest.mark.parametrize("theme", ["system", None, "", "네온", "Dark"])
def test_theme_key_is_absent_unless_light_or_dark(theme):
    payload = product_api.preferences_payload({"font_scale": 1.0}, theme)
    assert "theme" not in payload  # 빈 값을 실어 프런트가 추측하게 두지 않는다


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_persisted_light_dark_rides_along(theme):
    assert product_api.preferences_payload({}, theme)["theme"] == theme


def test_unknown_event_is_refused_not_guessed():
    with pytest.raises(ProductApiError) as err:
        product_api.request_envelope("teleport", {})
    assert err.value.code == product_api.CODE_INTERNAL


def test_only_describe_and_deliver_can_be_called():
    with pytest.raises(ProductApiError) as err:
        product_api._expression("eval", "1")
    assert err.value.code == product_api.CODE_INTERNAL
    assert product_api._expression("deliver", "1") == f"{ROOT} ? {ROOT}.deliver(1) : null"


# ------------------------------------------------------------------ 직렬화


def test_unicode_and_nested_payload_survives_the_literal():
    snapshot = {
        "제목": '따옴표 " 와 역슬래시 \\ 와\n줄바꿈',
        "목록": [{"깊이": {"더": ["끝", 1, True, None]}}, "文書", "🚚"],
        "빈": {},
    }
    expression = product_api.snapshot_expression("작업/일", snapshot)
    envelope = argument_of(expression)
    assert envelope["payload"]["snapshot"] == snapshot
    assert envelope["payload"]["screen"] == "작업/일"
    assert "따옴표" in expression  # ensure_ascii=False 관행 유지(로그에서 읽힌다)


def test_lone_surrogate_escapes_instead_of_breaking_the_expression():
    expression = product_api.notice_expression("깨진 \ud800 이름")
    expression.encode("utf-8")  # UTF-8 로 실려 나갈 수 있어야 한다(던지면 실패)
    assert argument_of(expression)["payload"]["message"] == "[hwpx] 깨진 \ud800 이름"


def test_js_line_terminators_are_escaped():
    """U+2028·U+2029 는 JS 소스에서 줄 종결자로 읽힐 수 있다 — 표현식이 쪼개지면 안 된다."""
    message = "앞\u2028뒤\u2029끝"
    expression = product_api.notice_expression(message)
    assert "\u2028" not in expression and "\u2029" not in expression
    assert argument_of(expression)["payload"]["message"] == "[hwpx] " + message


def test_non_json_values_are_refused_loudly():
    with pytest.raises(ProductApiError) as nan:
        product_api.encode_js_literal({"x": float("nan")})
    assert nan.value.code == product_api.CODE_PAYLOAD_UNSERIALIZABLE
    with pytest.raises(ProductApiError) as obj:
        product_api.encode_js_literal({"x": object()})
    assert obj.value.code == product_api.CODE_PAYLOAD_UNSERIALIZABLE


# ------------------------------------------------------------------ deliver 판정


def test_none_result_is_facade_absent_not_a_rejection():
    outcome = product_api.classify_result("snapshot", None)
    assert not outcome.ok
    assert outcome.code == product_api.CODE_FACADE_ABSENT
    assert outcome.facade_absent is True
    assert outcome.result is None
    rejected = product_api.classify_result("snapshot", {"ok": False, "code": "nope"})
    assert rejected.facade_absent is False  # 구조화된 거절과 확실히 갈린다
    assert rejected.code != outcome.code


@pytest.mark.parametrize("raw", [7, "ok", ["ok"], True])
def test_non_object_result_is_loud(raw):
    outcome = product_api.classify_result("notice", raw)
    assert outcome.code == product_api.CODE_RESULT_NOT_OBJECT
    assert not outcome.ok


def test_missing_ok_and_non_bool_ok_are_different_failures():
    missing = product_api.classify_result("notice", {"code": "x"})
    weird = product_api.classify_result("notice", {"ok": "true"})
    assert missing.code == product_api.CODE_RESULT_MISSING_OK
    assert weird.code == product_api.CODE_RESULT_OK_NOT_BOOL
    assert missing.result == {"code": "x"}  # 원본을 버리지 않는다


def test_ok_true_passes_and_keeps_the_result():
    outcome = product_api.classify_result("snapshot", {"ok": True, "rendered": 3})
    assert outcome.ok and outcome.code == "ok"
    assert outcome.result == {"ok": True, "rendered": 3}
    assert outcome.raise_for_failure() is outcome


def test_unknown_rejection_code_is_carried_not_swallowed():
    outcome = product_api.classify_result("close-request", {"ok": False, "code": "무슨코드"})
    assert outcome.code == "무슨코드"
    assert "무슨코드" in outcome.detail
    assert "close-request" in outcome.alarm_text


@pytest.mark.parametrize("code", [None, "", 7, {"a": 1}])
def test_rejection_without_usable_code_falls_back_to_rejected(code):
    outcome = product_api.classify_result("close-request", {"ok": False, "code": code})
    assert outcome.code == product_api.CODE_REJECTED
    bare = product_api.classify_result("close-request", {"ok": False})
    assert bare.code == product_api.CODE_REJECTED


def test_raise_for_failure_maps_codes_to_types():
    with pytest.raises(FacadeAbsentError):
        DeliveryOutcome("snapshot", False, product_api.CODE_FACADE_ABSENT, "x").raise_for_failure()
    with pytest.raises(TransportError):
        DeliveryOutcome(
            "snapshot", False, product_api.CODE_EVALUATE_FAILED, "x"
        ).raise_for_failure()
    with pytest.raises(DeliveryError):
        DeliveryOutcome("snapshot", False, "rejected", "x").raise_for_failure()


# ------------------------------------------------------- preferences 부분 귀속


def test_applied_map_splits_personalization_from_theme():
    only_theme_dead = product_api.classify_preferences(
        {"ok": False, "applied": {"personalization": True, "theme": False}}, theme_sent=True
    )
    only_personalization_dead = product_api.classify_preferences(
        {"ok": False, "applied": {"personalization": False, "theme": True}}, theme_sent=True
    )
    assert only_theme_dead.failed == ("theme",)
    assert only_theme_dead.applied == ("personalization",)
    assert only_personalization_dead.failed == ("personalization",)
    # 종전 두 문안이 갈렸던 그 구분이 문안에서도 살아 있다.
    assert "테마" in only_theme_dead.failure_text
    assert "개인화" in only_personalization_dead.failure_text
    assert only_theme_dead.failure_text != only_personalization_dead.failure_text


def test_partial_success_reported_as_ok_true_is_still_a_failure():
    outcome = product_api.classify_preferences(
        {"ok": True, "applied": {"personalization": True, "theme": False}}, theme_sent=True
    )
    assert not outcome.ok and outcome.failed == ("theme",)


def test_applied_contradicting_ok_false_is_not_swallowed():
    outcome = product_api.classify_preferences(
        {"ok": False, "applied": {"personalization": True, "theme": True}}, theme_sent=True
    )
    assert not outcome.ok
    assert outcome.failed == ("personalization", "theme")
    assert outcome.attributed is False
    assert outcome.notes == ("applied 와 ok 가 모순",)


def test_applied_name_array_is_the_first_clue():
    """v1 파사드 계약의 1차 단서는 ``applied`` **이름 배열**이다.

    파사드는 조각별 코드(``theme-unavailable`` 등)를 내지 않는다 — 부분 부재는
    ``handler_unavailable`` 하나로 오고, **어느 조각이 살고 죽었는지는 배열이 말한다**.
    """
    outcome = product_api.classify_preferences(
        {
            "ok": False,
            "code": "handler_unavailable",
            "applied": ["personalization"],
            "missing": ["theme"],
        },
        theme_sent=True,
    )
    assert outcome.applied == ("personalization",)
    assert outcome.failed == ("theme",)
    assert outcome.attributed


def test_missing_is_the_second_clue_when_applied_is_absent():
    theme_dead = product_api.classify_preferences(
        {"ok": False, "code": "handler_unavailable", "missing": ["theme"]}, theme_sent=True
    )
    personalization_dead = product_api.classify_preferences(
        {"ok": False, "code": "handler_unavailable", "missing": ["personalization"]},
        theme_sent=True,
    )
    assert theme_dead.failed == ("theme",) and theme_dead.attributed
    assert theme_dead.applied == ("personalization",)
    assert personalization_dead.failed == ("personalization",)


def test_theme_only_clue_when_no_theme_was_sent_is_unattributed():
    """보내지도 않은 조각을 지목당하면 귀속이 성립하지 않는다 — 전부 실패 + 불명 표식."""
    outcome = product_api.classify_preferences(
        {"ok": False, "code": "handler_unavailable", "missing": ["theme"]}, theme_sent=False
    )
    assert outcome.failed == ("personalization",)
    assert outcome.attributed is False
    assert "귀속 불명" in outcome.failure_text


def test_unknown_failure_blames_everything_and_says_so():
    outcome = product_api.classify_preferences({"ok": False, "code": "??"}, theme_sent=True)
    assert outcome.failed == ("personalization", "theme")
    assert outcome.attributed is False
    assert "귀속 불명" in outcome.failure_text
    assert "??" in outcome.failure_text


def test_facade_absent_during_preferences_is_total_and_unattributed():
    outcome = product_api.classify_preferences(None, theme_sent=True)
    assert outcome.delivery.facade_absent
    assert outcome.failed == ("personalization", "theme")
    assert outcome.attributed is False


def test_clean_success_has_no_failure_text():
    both = product_api.classify_preferences({"ok": True}, theme_sent=True)
    assert both.ok and both.failure_text is None
    assert both.applied == ("personalization", "theme")
    assert both.theme_sent is True
    without_theme = product_api.classify_preferences({"ok": True}, theme_sent=False)
    assert without_theme.expected == ("personalization",)
    assert without_theme.theme_sent is False


@pytest.mark.parametrize("applied", [None, 7, "yes", ["personalization", 7]])
def test_malformed_applied_falls_through_to_the_missing_clue(applied):
    """``applied`` 가 이름 배열도 map 도 아니면 2차 단서(``missing``)로 넘어간다.

    문자열 ``"yes"`` 는 반복 가능하지만 **배열이 아니다** — 글자로 쪼개 귀속하면 조용히
    틀린다. 원소 하나라도 문자열이 아니면 배열 전체를 단서로 쓰지 않는다.
    """
    outcome = product_api.classify_preferences(
        {
            "ok": False,
            "code": "handler_unavailable",
            "applied": applied,
            "missing": ["theme"],
        },
        theme_sent=True,
    )
    assert outcome.failed == ("theme",)


def test_applied_map_ignores_theme_when_theme_was_not_sent():
    outcome = product_api.classify_preferences(
        {"ok": True, "applied": {"personalization": True, "theme": False}}, theme_sent=False
    )
    assert outcome.ok and outcome.expected == ("personalization",)


# ------------------------------------------------------------------ 클라이언트


def test_client_describe_roundtrip():
    evaluator = FakeEvaluator(GOOD_DESCRIPTOR)
    client = ProductApiClient(evaluator)
    assert client.describe() == Descriptor(PROTOCOL, 1, CAPABILITIES)
    assert evaluator.last == product_api.describe_expression()


def test_client_describe_turns_evaluator_blowup_into_transport_error():
    client = ProductApiClient(FakeEvaluator(raises=RuntimeError("창이 죽었다")))
    with pytest.raises(TransportError) as err:
        client.describe()
    assert err.value.code == product_api.CODE_EVALUATE_FAILED
    assert "창이 죽었다" in err.value.detail


def test_client_describe_missing_facade_is_absent_not_transport():
    client = ProductApiClient(FakeEvaluator(None))
    with pytest.raises(FacadeAbsentError):
        client.describe()


def test_client_describe_can_narrow_required_capabilities():
    evaluator = FakeEvaluator(dict(GOOD_DESCRIPTOR, capabilities=["notice"]))
    assert ProductApiClient(evaluator).describe(["notice"]).capabilities == ("notice",)


def test_push_never_raises_and_stays_fire_and_forget():
    evaluator = FakeEvaluator(None)
    outcome = ProductApiClient(evaluator).push("job", {"rows": 1})
    assert outcome.facade_absent  # 판정은 돌려주되
    assert isinstance(outcome, DeliveryOutcome)  # 예외로 올리지 않는다
    assert argument_of(evaluator.last)["event"] == "snapshot"
    ok = ProductApiClient(FakeEvaluator({"ok": True})).push("job", {})
    assert ok.ok


def test_push_swallows_evaluator_blowup():
    outcome = ProductApiClient(FakeEvaluator(raises=RuntimeError("boom"))).push("job", {})
    assert outcome.code == product_api.CODE_EVALUATE_FAILED
    assert not outcome.ok


def test_close_request_fails_closed_and_is_raisable():
    evaluator = FakeEvaluator(None)
    outcome = ProductApiClient(evaluator).close_request({"armed": True, "reasons": ["작업"]})
    assert not outcome.ok  # 종전의 조용한 no-op 이 아니다
    assert argument_of(evaluator.last)["payload"]["state"]["reasons"] == ["작업"]
    with pytest.raises(FacadeAbsentError):
        outcome.raise_for_failure()


def test_client_preferences_sends_one_envelope_and_keeps_the_split():
    evaluator = FakeEvaluator(
        {
            "ok": False,
            "code": "handler_unavailable",
            "applied": ["personalization"],
            "missing": ["theme"],
        }
    )
    outcome = ProductApiClient(evaluator).preferences({"font_scale": 1.25}, "dark")
    envelope = argument_of(evaluator.last)
    assert envelope["event"] == "preferences"
    assert envelope["payload"] == {"personalization": {"font_scale": 1.25}, "theme": "dark"}
    assert len(evaluator.calls) == 1  # 두 왕복이 하나로 접혔다
    assert outcome.failed == ("theme",)


def test_client_preferences_without_persisted_theme_expects_one_part():
    evaluator = FakeEvaluator({"ok": True})
    outcome = ProductApiClient(evaluator).preferences({"font_scale": 1.0}, "system")
    assert "theme" not in argument_of(evaluator.last)["payload"]
    assert outcome.expected == ("personalization",) and outcome.ok


def test_client_preferences_survives_evaluator_blowup():
    client = ProductApiClient(FakeEvaluator(raises=RuntimeError("boom")))
    outcome = client.preferences({"font_scale": 1.0}, "light")
    assert not outcome.ok and outcome.attributed is False
    assert outcome.delivery.code == product_api.CODE_EVALUATE_FAILED


def test_deliver_keeps_the_serialization_code_when_payload_is_not_json():
    evaluator = FakeEvaluator({"ok": True})
    outcome = ProductApiClient(evaluator).push("job", {"x": object()})
    assert outcome.code == product_api.CODE_PAYLOAD_UNSERIALIZABLE
    assert evaluator.calls == []  # 창까지 가지도 않는다


def test_notice_puts_the_durable_channel_first():
    log: list = []
    evaluator = FakeEvaluator({"ok": True}, log=log)
    client = ProductApiClient(evaluator, durable_alert=lambda m: log.append(("durable", m)))
    outcome = client.notice("템플릿을 못 읽었다")
    assert log[0] == ("durable", "템플릿을 못 읽었다")
    assert log[1][0] == "window"
    assert outcome.ok
    assert argument_of(evaluator.last)["payload"]["message"] == "[hwpx] 템플릿을 못 읽었다"


def test_notice_window_failure_does_not_recurse_into_another_alarm():
    log: list = []
    client = ProductApiClient(
        FakeEvaluator(raises=RuntimeError("창 없음"), log=log),
        durable_alert=lambda m: log.append(("durable", m)),
    )
    outcome = client.notice("경보")
    assert [entry for entry in log if entry[0] == "durable"] == [("durable", "경보")]
    assert not outcome.ok and outcome.code == product_api.CODE_EVALUATE_FAILED


def test_notice_defaults_to_the_settings_durable_channel(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(settings, "alert", seen.append)
    ProductApiClient(FakeEvaluator(None)).notice("기본 채널")
    assert seen == ["기본 채널"]


def test_for_window_wraps_evaluate_js():
    class FakeWindow:
        def __init__(self):
            self.calls: list[str] = []

        def evaluate_js(self, expression):
            self.calls.append(expression)
            return GOOD_DESCRIPTOR

    window = FakeWindow()
    assert ProductApiClient.for_window(window).describe().version == 1
    assert window.calls == [product_api.describe_expression()]


# ------------------------------------------------------------------ 소스 감사


def test_module_source_has_no_test_hook_and_no_legacy_fallback():
    """선언이 아니라 **소스 전체**를 센다 — 폴백 한 줄이 계약을 조용히 되살린다."""
    source = Path(product_api.__file__).read_text(encoding="utf-8-sig")
    assert "__hwpxTest" not in source
    for token in LEGACY_TOKENS:
        assert token not in source, token
    # 뿌리는 상수 한 곳에서만 난다.
    assert source.count('"window.__hwpx"') == 1
    assert "import app" not in source and "from .app" not in source  # 순환 금지
