"""자가검증 호스트 어댑터 계약 가드 — ``hwpxfiller.webapp.selftest_api`` (N-09).

이 층이 지켜야 하는 것은 여섯 가지다.

1. **뿌리가 하나다.** 어댑터가 내는 JS 표현식에 등장하는 전역은 ``window.__hwpxTest`` 뿐이고,
   **호출**하는 멤버는 ``run`` 하나다(준비 확인은 호출이 아니라 ``version`` 읽기다).
   표현식 문자열 자체를 세어 그것을 못박는다.
2. **토큰이 새지 않는다.** 표현식·판정 결과·객체 repr·로그 줄 어디에도 토큰 문자열이 없다.
   이 단언이 없으면 "프로세스 메모리에만 산다"는 문장은 선언일 뿐이고, 선언은 살고 결과는
   죽는다(반복 결함류).
3. **실패가 갈린다.** 틀린 토큰 · 두 번째 악수 · 틀린 버전 · 망가진 payload · 미등록 op 는 서로
   다른 사건이다. 드라이버가 경보에서 그 차이를 말할 수 있어야 하므로 코드가 실제로 다른지 본다.
4. **JS 코드가 재라벨되지 않는다.** 와이어의 snake_case 11종은 명시 표로만 옮겨지고, 표에 없는
   코드는 **원문 그대로** 남는다 — 모르는 실패를 아는 실패의 이름으로 바꾸면 진단이 거짓말을 한다.
5. **실패한 실행도 증거를 낸다.** ``run_failed`` 는 "결과가 없다"가 아니라 "결과가 있고 그 안에
   ``error`` 가 서 있다"다. 증거를 버리면 실앱 게이트가 원인을 잘못 짚는다.
6. **11개 op 가 정확히 한 번씩 분류된다.** 분류표는 산문이 아니라 데이터라서 기계가 센다.
   그리고 그 11개 이름은 ``frontend/src/selftest/runner.js`` 의 ``HOST_OPS`` 와 **같아야** 한다.

WebView2 는 뜨지 않는다 — 평가기·시계·수면·네이티브 자원이 전부 주입이고 여기선 전부 가짜다.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest
from _web_source import source_path

from hwpxfiller.webapp import selftest_api as api
from hwpxfiller.webapp.selftest_api import (
    ACTIONS,
    CODES,
    HOST_OPS,
    JS_CODE_MAP,
    JS_CODES,
    OP_CLASSES,
    OP_CLASSIFICATION,
    ROOT,
    VERSION,
    FacadeAbsentError,
    HostOperations,
    ProcessDeadline,
    ProtocolError,
    RefusedError,
    SelftestApiError,
    SelftestClient,
    SelftestHostFacade,
    SelftestOutcome,
    TransportError,
)

#: 러너 소스는 **중앙 source 역할 접근자**로만 연다 — 물리 루트를 여기서 다시 조립하면
#: 다음 컷오버 때 이 테스트만 옛 사본을 읽고도 초록이다(``test_web_source_role.py`` 가 가드).
RUNNER_JS = source_path("src", "selftest", "runner.js")

#: 제품 경계(``window.__hwpx``)의 이름과 일반 eval — 자가검증 표현식에 있으면 두 경계가 섞인다.
FOREIGN_TOKENS = ("window.__hwpx ", "window.__hwpx.", "hwpx-product", "__push", "eval(")

TOKEN = "TESTTOKEN-xkLq9_Zr3Nn-abcdefghijklmnop"


def evidence(**extra) -> dict:
    """러너 ``toEvidence()`` 가 낼 법한 증거 묶음."""
    return {"url": "http://127.0.0.1/index.html", "nav_count": 2, **extra}


def poll_running() -> dict:
    return {"ok": True, "action": "poll", "runId": "r1", "state": "running",
            "elapsedMs": 10, "deadlineMs": 90000}


def poll_succeeded(**extra) -> dict:
    return {"ok": True, "action": "poll", "runId": "r1", "state": "succeeded", "mode": "boot",
            "evidence": evidence(), "order": ["p"], "timings": {"p": 1},
            "elapsedMs": 20, "deadlineMs": 90000, **extra}


def poll_failed(**extra) -> dict:
    return {"ok": False, "code": "run_failed", "action": "poll", "runId": "r1", "state": "failed",
            "mode": "boot", "evidence": evidence(error="[p/run/probe_threw] 터졌다"),
            "errors": [{"probe": "p", "phase": "run", "code": "probe_threw", "message": "터졌다"}],
            "skipped": [], "order": ["p"], "timings": {"p": 1},
            "elapsedMs": 20, "deadlineMs": 90000, **extra}


def start_ok(run_id: str = "r1") -> dict:
    return {"ok": True, "action": "start", "runId": run_id, "state": "running",
            "mode": "boot", "deadlineMs": 90000}


class FakeEvaluator:
    """표현식을 기록하고 미리 정한 값을 순서대로 돌려주는 가짜 ``evaluate_js``."""

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


class FakeClock:
    """가상 시계 — ``sleep`` 이 곧 시간 전진이다(실시간을 쓰지 않는다)."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def envelope_of(expression: str) -> dict:
    """표현식에 박힌 리터럴을 되판다 — 보낸 것이 정확히 무엇인지 확인하는 유일한 방법."""
    match = re.fullmatch(
        rf"{re.escape(ROOT)} \? {re.escape(ROOT)}\.run\((?P<arg>.*)\) : null", expression, re.S
    )
    assert match is not None, expression
    return json.loads(match.group("arg"))


def make_operations(**overrides) -> HostOperations:
    """모든 주입이 채워진 연산 창구 — 개별 테스트가 필요한 것만 덮어쓴다."""
    resized: list[tuple[int, int]] = []
    destroyed: list[bool] = []
    written: list[dict] = []

    class FakeSettings:
        def load_theme(self):
            return "dark"

        def load_font_scale(self):
            return "125"

    defaults = {
        "resize": lambda w, h: resized.append((w, h)),
        "geometry": lambda: {
            "x": 0, "y": 0, "width": 1920, "height": 1080,
            "avail_x": 0, "avail_y": 0, "avail_width": 1920, "avail_height": 1080,
        },
        "current_url": lambda: "http://127.0.0.1:51234/index.html",
        "artifact_identity": lambda: {"artifact_id": "A1", "tree_sha256": "deadbeef"},
        "settings_source": FakeSettings(),
        "inputs": {"theme": "dark", "font_scale": "125"},
        "mode": "boot",
        "write_output": lambda result: written.append(dict(result)) or "C:/out/selftest.json",
        "destroy": lambda: destroyed.append(True),
        "deadline": ProcessDeadline(90.0, FakeClock().now),
    }
    defaults.update(overrides)
    operations = HostOperations(**defaults)  # type: ignore[arg-type]
    operations.seen_resize = resized  # type: ignore[attr-defined]
    operations.seen_destroy = destroyed  # type: ignore[attr-defined]
    operations.seen_written = written  # type: ignore[attr-defined]
    return operations


def claimed_facade(**kwargs) -> SelftestHostFacade:
    facade = SelftestHostFacade(kwargs.pop("operations", make_operations()), token=TOKEN, **kwargs)
    assert facade.selftest_claim(VERSION)["ok"] is True
    return facade


def host_call(facade: SelftestHostFacade, op, payload=None, **kwargs) -> dict:
    return facade.selftest_host_op(op, payload, **kwargs)


# ------------------------------------------------------------------ 계약 상수


def test_contract_constants_are_the_agreed_v1():
    assert VERSION == 1
    assert ROOT == "window.__hwpxTest"
    assert ACTIONS == ("start", "poll")  # describe·consume 은 계약에 없다
    assert api.READINESS_MEMBER == "version"
    assert api.KEY_RUN_ID == "runId"  # 와이어 키는 camelCase
    assert api.STATES == ("running", "succeeded", "failed")
    assert api.TERMINAL_STATES == ("succeeded", "failed")


def test_stable_code_set_is_declared_once_and_has_no_duplicates():
    assert len(CODES) == len(set(CODES))
    required = {
        "facade-absent", "evaluate-failed", "unauthorized", "version-unsupported",
        "malformed-result", "already-consumed", "unknown-run", "run-failed",
        "deadline-exceeded", "internal",
    }
    assert required <= set(CODES)
    # 모듈이 내놓는 CODE_* 상수는 전부 목록에 있다 — 목록 밖 코드가 조용히 늘지 않는다.
    declared = {
        value for name, value in vars(api).items()
        if name.startswith("CODE_") and isinstance(value, str)
    }
    assert declared == set(CODES)


# ------------------------------------------------------- JS↔Python 코드 어휘


def test_js_code_vocabulary_is_the_eleven_wire_strings():
    assert len(JS_CODES) == 11 and len(set(JS_CODES)) == 11
    assert set(JS_CODES) == set(JS_CODE_MAP)
    assert all("-" not in name for name in JS_CODES)  # 와이어는 snake_case
    assert all(value in CODES for value in JS_CODE_MAP.values())  # 파이썬 쪽은 kebab-case 목록 안


@pytest.mark.parametrize(
    "js, expected",
    [
        ("malformed_request", api.CODE_MALFORMED_PAYLOAD),
        ("unsupported_version", api.CODE_VERSION_UNSUPPORTED),
        ("unknown_action", api.CODE_UNKNOWN_ACTION),
        ("unauthorized", api.CODE_UNAUTHORIZED),
        ("already_claimed", api.CODE_ALREADY_CLAIMED),
        ("already_running", api.CODE_ALREADY_RUNNING),
        ("unknown_run", api.CODE_UNKNOWN_RUN),
        ("already_consumed", api.CODE_ALREADY_CONSUMED),
        ("deadline_exceeded", api.CODE_DEADLINE_EXCEEDED),
        ("run_failed", api.CODE_RUN_FAILED),
        ("internal", api.CODE_INTERNAL),
    ],
)
def test_every_js_code_maps_to_exactly_one_python_code(js, expected):
    assert api.python_code(js) == expected


def test_unrecognised_js_code_is_preserved_verbatim_not_relabelled():
    assert api.python_code("quantum_flux") == "quantum_flux"
    # 빈 값·문자열 아님만 접는다 — 거절이라는 사실 자체는 남는다.
    assert api.python_code(None) == api.CODE_REJECTED
    assert api.python_code("") == api.CODE_REJECTED
    assert api.python_code(7) == api.CODE_REJECTED


# ------------------------------------------------------------------ 분류표


def test_classification_covers_all_eleven_ops_exactly_once():
    assert len(HOST_OPS) == 11
    assert len(set(HOST_OPS)) == 11
    assert tuple(OP_CLASSIFICATION) == HOST_OPS  # 순서까지 같다
    for name, spec in OP_CLASSIFICATION.items():
        assert spec.name == name
        assert spec.op_class in OP_CLASSES
        assert spec.reason.strip(), name  # 사유 없는 분류는 분류가 아니다
    flattened = [name for names in api.OPS_BY_CLASS.values() for name in names]
    assert sorted(flattened) == sorted(HOST_OPS)
    assert len(flattened) == 11  # 어떤 op 도 두 분류에 걸치지 않는다


def test_classification_assigns_the_four_expected_buckets():
    assert api.OPS_BY_CLASS[api.CLASS_RUNTIME_REQUEST] == (
        "input_select", "window_resize", "window_geometry",
        "current_url", "artifact_identity", "settings_readback",
    )
    assert api.OPS_BY_CLASS[api.CLASS_DRIVER_OWNED] == (
        "global_deadline", "output_write", "window_destroy",
    )
    assert api.OPS_BY_CLASS[api.CLASS_PACKAGING] == ("packaged_process",)
    assert api.OPS_BY_CLASS[api.CLASS_DECLARED_UNUSED] == ("mode_select",)


def test_python_host_ops_match_the_frontend_runner_declaration():
    """두 벌이 갈라지면 프런트는 요청하는데 호스트는 모르는 이름이 생긴다 — 소스를 직접 센다."""
    source = RUNNER_JS.read_text(encoding="utf-8")
    match = re.search(r"HOST_OPS\s*=\s*Object\.freeze\(\[(?P<body>.*?)\]\)", source, re.S)
    assert match is not None, "runner.js 에서 HOST_OPS 를 찾지 못했다"
    js_ops = tuple(re.findall(r'"([a-z_]+)"', match.group("body")))
    assert js_ops == HOST_OPS


def test_every_declared_op_has_a_handler():
    assert HostOperations.registered_ops() == HOST_OPS


# ------------------------------------------------------------------ 토큰


def test_minted_tokens_are_unique_and_long_enough():
    minted = {api.mint_token() for _ in range(64)}
    assert len(minted) == 64
    assert all(len(value) >= 32 for value in minted)


def test_token_leaks_reports_every_place_the_token_appears():
    assert api.token_leaks(TOKEN, "무해한 문자열", {"a": 1}) == ()
    leaked = api.token_leaks(TOKEN, f"expr({TOKEN})", {"t": TOKEN}, ["x"])
    assert len(leaked) == 2
    assert leaked[0].startswith("#0:") and leaked[1].startswith("#1:")


def test_token_leaks_refuses_the_empty_token():
    with pytest.raises(SelftestApiError) as err:
        api.token_leaks("", "무엇이든")
    assert err.value.code == api.CODE_INTERNAL


# ------------------------------------------------------------------ 표현식


def test_readiness_is_a_read_not_a_call():
    assert api.readiness_expression() == "window.__hwpxTest ? window.__hwpxTest.version : null"
    assert "(" not in api.readiness_expression()  # 호출이 아니다


def test_readiness_returns_null_instead_of_throwing_when_absent():
    """부재는 예외가 아니라 판정이다 — 단, 이제 **시한까지 기다린 뒤** 확정한다.

    가상 시계를 준다: 실제 예산으로 돌리면 이 한 줄이 90초를 먹는다(설치가 비동기라
    ``drive`` 가 준비를 폴링하기 때문). 시계 주입이 없으면 느린 테스트가 조용히 쌓인다.
    """
    clock = FakeClock()
    client = SelftestClient(
        FakeEvaluator(None), budget_s=1.0, now=clock.now, sleep=clock.sleep
    )
    assert client.drive("boot").code == api.CODE_FACADE_ABSENT


def test_every_emitted_expression_touches_only_the_one_root_and_calls_only_run():
    expressions = [
        api.readiness_expression(),
        api.start_expression("boot"),
        api.start_expression("boot", probe_input="dark", flags={"offline": True}),
        api.poll_expression("r1"),
    ]
    for expression in expressions:
        assert expression.count(ROOT) == 2  # 뿌리는 두 번(가드 + 접근)뿐
        called = re.findall(rf"{re.escape(ROOT)}\.([A-Za-z_$]+)\s*\(", expression)
        assert called in ([], ["run"]), expression  # 호출되는 멤버는 run 뿐
        read = re.findall(rf"{re.escape(ROOT)}\.([A-Za-z_$]+)", expression)
        assert read == ["run"] or read == ["version"], expression
        for foreign in FOREIGN_TOKENS:
            assert foreign not in expression, foreign


def test_only_the_run_method_may_be_emitted():
    assert api._METHODS == ("run",)
    with pytest.raises(SelftestApiError) as err:
        api._expression("destroy")
    assert err.value.code == api.CODE_INTERNAL


def test_start_envelope_is_flat_and_carries_no_token():
    envelope = envelope_of(
        api.start_expression("boot", probe_input="dark", flags={"offline": True})
    )
    assert envelope == {
        "version": 1,
        "action": "start",
        "mode": "boot",
        "input": "dark",
        "flags": {"offline": True},
    }
    assert "payload" not in envelope  # 중첩 봉투는 없다
    assert "token" not in json.dumps(envelope)


def test_start_envelope_omits_absent_input_and_flags():
    envelope = envelope_of(api.start_expression("geometry"))
    assert envelope == {"version": 1, "action": "start", "mode": "geometry"}
    # 부재는 값이 아니다 — 빈 값을 지어내지 않는다.
    assert "input" not in envelope and "flags" not in envelope
    assert envelope_of(api.start_expression("boot", flags={}))["flags"] == {}


def test_poll_envelope_uses_the_camel_case_wire_key():
    envelope = envelope_of(api.poll_expression("r7"))
    assert envelope == {"version": 1, "action": "poll", "runId": "r7"}
    assert "run_id" not in json.dumps(envelope)


def test_unknown_action_is_refused_before_any_string_is_built():
    for action in ("describe", "consume", "evaluate"):
        with pytest.raises(SelftestApiError) as err:
            api.request_envelope(action, {})
        assert err.value.code == api.CODE_INTERNAL
        assert action in err.value.detail


def test_envelope_skeleton_cannot_be_overwritten_by_fields():
    with pytest.raises(SelftestApiError) as err:
        api.request_envelope("poll", {"version": 99, "action": "start"})
    assert err.value.code == api.CODE_INTERNAL and "action" in err.value.detail


def test_empty_mode_and_empty_run_id_are_refused():
    with pytest.raises(SelftestApiError):
        api.start_expression("")
    with pytest.raises(SelftestApiError) as err:
        api.poll_expression("")
    assert err.value.code == api.CODE_INTERNAL and "runId" in err.value.detail


def test_unserializable_payload_is_loud_not_silent():
    with pytest.raises(SelftestApiError) as err:
        api.start_expression("boot", flags={"x": object()})
    assert err.value.code == api.CODE_PAYLOAD_UNSERIALIZABLE


def test_line_separators_are_escaped_like_the_product_boundary():
    expression = api.start_expression("boot", probe_input="a\u2028b\u2029c")
    assert "\u2028" not in expression and "\\u2028" in expression


# ------------------------------------------------------------------ 예산


def test_process_deadline_counts_down_and_expires():
    clock = FakeClock()
    deadline = ProcessDeadline(2.0, clock.now)
    assert not deadline.expired() and deadline.remaining_s() == 2.0
    clock.sleep(1.5)
    assert deadline.snapshot() == {
        "budget_ms": 2000, "elapsed_ms": 1500, "remaining_ms": 500, "expired": False
    }
    clock.sleep(0.5)
    assert deadline.expired() and deadline.snapshot()["expired"] is True


def test_non_positive_budget_is_refused():
    with pytest.raises(SelftestApiError) as err:
        ProcessDeadline(0.0)
    assert err.value.code == api.CODE_INTERNAL


# --------------------------------------------------------------- 파사드 부착


class FakeFrontend:
    """``js_api`` 로 넘어가는 객체를 흉내 낸다 — 공개 이름이 곧 표면이다."""

    def dispatch(self, screen, action, payload):
        return {}


def public_names(target: object) -> set:
    return {name for name in dir(target) if not name.startswith("_")}


def test_normal_mode_exposes_no_test_method_at_all():
    frontend = FakeFrontend()
    assert public_names(frontend) == {"dispatch"}
    assert not api.facade_attached(frontend)


def test_attach_adds_exactly_the_two_bridge_names_and_detach_removes_them():
    frontend = FakeFrontend()
    facade = SelftestHostFacade(make_operations(), token=TOKEN)
    added = api.attach_selftest_facade(frontend, facade)
    assert added == ("selftest_claim", "selftest_host_op")
    assert public_names(frontend) == {"dispatch", "selftest_claim", "selftest_host_op"}
    assert api.facade_attached(frontend)
    # 심은 이름이 실제로 파사드로 가고, 인자 모양도 브리지가 부르는 그대로다.
    assert frontend.selftest_claim(1)["ok"] is True  # type: ignore[attr-defined]
    assert frontend.selftest_host_op("current_url", None)["ok"] is True  # type: ignore[attr-defined]
    assert api.detach_selftest_facade(frontend) == ("selftest_claim", "selftest_host_op")
    assert public_names(frontend) == {"dispatch"}
    assert not api.facade_attached(frontend)


def test_attached_methods_are_bound_methods_so_pywebview_reflects_them():
    """pywebview 의 ``get_functions`` 는 ``inspect.ismethod`` 를 보고 ``get_args(...)[1:]`` 한다."""
    frontend = FakeFrontend()
    api.attach_selftest_facade(frontend, SelftestHostFacade(make_operations(), token=TOKEN))
    claim = frontend.selftest_claim  # type: ignore[attr-defined]
    host_op = frontend.selftest_host_op  # type: ignore[attr-defined]
    assert inspect.ismethod(claim) and inspect.ismethod(host_op)
    assert "selftest_claim" in dir(frontend) and "selftest_host_op" in dir(frontend)
    assert inspect.getfullargspec(claim).args[1:] == ["version", "token"]
    assert inspect.getfullargspec(host_op).args[1:] == ["op", "payload", "token"]


def test_detach_is_idempotent():
    assert api.detach_selftest_facade(FakeFrontend()) == ()


def test_attach_refuses_to_overwrite_an_occupied_name():
    frontend = FakeFrontend()
    frontend.selftest_claim = lambda version: {}  # type: ignore[attr-defined]
    with pytest.raises(SelftestApiError) as err:
        api.attach_selftest_facade(frontend, SelftestHostFacade(make_operations()))
    assert err.value.code == api.CODE_INTERNAL
    # 부분 부착이 남지 않는다 — 검사가 심기보다 먼저 전부 돈다.
    assert not hasattr(frontend, "selftest_host_op")


def test_attach_refuses_a_non_facade():
    with pytest.raises(SelftestApiError):
        api.attach_selftest_facade(FakeFrontend(), object())  # type: ignore[arg-type]


# ------------------------------------------------------------------ 악수


def test_successful_claim_returns_the_token_and_the_serviceable_ops():
    facade = SelftestHostFacade(make_operations(), token=TOKEN)
    result = facade.selftest_claim(1)
    assert result["ok"] is True
    assert result["version"] == VERSION
    assert result["token"] == TOKEN
    # provides = **실제로 댈 수 있는** 것. 이 프로세스 밖의 일(packaged_process)은 빠진다 —
    # 그래야 그 op 를 요구하는 프로브가 계획 단계에서 붉어진다.
    assert result["provides"] == [name for name in HOST_OPS if name != "packaged_process"]
    assert facade.claim_state() == {"claimed": True, "claims": 1, "refusals": 0}


def test_provides_drops_ops_whose_injection_is_missing():
    facade = SelftestHostFacade(make_operations(resize=None, destroy=None), token=TOKEN)
    provides = facade.selftest_claim(1)["provides"]
    assert "window_resize" not in provides and "window_destroy" not in provides
    assert "current_url" in provides


def test_float_integer_version_is_accepted():
    """브리지가 수를 float 로 실어 올 수 있다 — ``1.0`` 은 1 이다."""
    assert SelftestHostFacade(make_operations(), token=TOKEN).selftest_claim(1.0)["ok"] is True


@pytest.mark.parametrize("version", [None, "1", True, 1.5, 2, 0, {"version": 1}])
def test_unsupported_claim_version_is_refused_without_burning_the_one_shot(version):
    facade = SelftestHostFacade(make_operations(), token=TOKEN)
    result = facade.selftest_claim(version)
    assert result["ok"] is False and result["code"] == api.CODE_VERSION_UNSUPPORTED
    assert facade.claim_state()["claimed"] is False
    assert facade.selftest_claim(1)["ok"] is True  # 악수는 아직 남아 있다


def test_claim_with_a_matching_pre_shared_token_passes():
    facade = SelftestHostFacade(make_operations(), token=TOKEN)
    assert facade.selftest_claim(1, TOKEN)["ok"] is True


def test_claim_with_a_bad_token_is_unauthorized_and_does_not_burn_the_one_shot():
    facade = SelftestHostFacade(make_operations(), token=TOKEN)
    refused = facade.selftest_claim(1, "틀린-토큰")
    assert refused["ok"] is False and refused["code"] == api.CODE_UNAUTHORIZED
    assert facade.claim_state()["claimed"] is False
    assert facade.selftest_claim(1)["ok"] is True


def test_second_claim_is_refused_with_its_own_code():
    facade = SelftestHostFacade(make_operations(), token=TOKEN)
    facade.selftest_claim(1)
    second = facade.selftest_claim(1)
    assert second["ok"] is False and second["code"] == api.CODE_ALREADY_CLAIMED
    assert facade.claim_state() == {"claimed": True, "claims": 1, "refusals": 1}


def test_claim_never_raises_even_when_the_operations_blow_up():
    class Exploding(HostOperations):
        def provides(self):
            raise RuntimeError("주입이 폭발했다")

    result = SelftestHostFacade(Exploding(), token=TOKEN).selftest_claim(1)
    assert result["ok"] is False and result["code"] == api.CODE_INTERNAL


# ------------------------------------------------------------ 호스트 요청 관문


def test_host_op_requires_a_claim_first():
    facade = SelftestHostFacade(make_operations(), token=TOKEN)
    assert host_call(facade, "current_url")["code"] == api.CODE_NOT_CLAIMED


def test_host_op_verifies_a_token_when_one_is_supplied():
    facade = claimed_facade()
    assert host_call(facade, "current_url", token="틀린-토큰")["code"] == api.CODE_UNAUTHORIZED
    assert host_call(facade, "current_url", token=TOKEN)["ok"] is True
    # 오늘의 브리지는 토큰을 안 넘긴다 — 그 경로도 악수만 있으면 통과한다.
    assert host_call(facade, "current_url")["ok"] is True


def test_host_op_refuses_an_unregistered_op_without_raising():
    facade = claimed_facade()
    result = host_call(facade, "rm_rf")
    assert result["ok"] is False and result["code"] == api.CODE_UNKNOWN_OP
    assert result["op"] == "rm_rf"
    assert host_call(facade, 17)["code"] == api.CODE_UNKNOWN_OP


def test_host_op_refuses_a_non_object_payload():
    assert host_call(claimed_facade(), "current_url", "문자열")["code"] == (
        api.CODE_MALFORMED_PAYLOAD
    )


def test_host_op_never_raises_even_when_dispatch_blows_up():
    class Exploding(HostOperations):
        def dispatch(self, op, payload=None):
            raise RuntimeError("디스패치가 폭발했다")

    facade = SelftestHostFacade(Exploding(), token=TOKEN)
    facade.selftest_claim(1)
    assert host_call(facade, "current_url")["code"] == api.CODE_INTERNAL


def test_host_op_refusals_are_logged_with_their_code():
    lines: list[str] = []
    facade = claimed_facade(log=lines.append)
    host_call(facade, "packaged_process")
    assert any(api.CODE_OUT_OF_PROCESS in line for line in lines)
    assert facade.claim_state()["refusals"] == 1


# ------------------------------------------------------------ 개별 op 긍정


def test_mode_select_returns_the_driver_chosen_mode():
    assert host_call(claimed_facade(), "mode_select") == {
        "ok": True, "op": "mode_select", "code": api.CODE_OK, "detail": "",
        "value": {"mode": "boot"},
    }


def test_input_select_returns_the_named_input():
    """payload 는 ``setting``, 결과는 **값 그대로** — 프로브가 문자열과 직접 비교한다."""
    result = host_call(claimed_facade(), "input_select", {"setting": "theme"})
    assert result["ok"] is True and result["value"] == "dark"


def test_global_deadline_reports_the_python_budget():
    value = host_call(claimed_facade(), "global_deadline")["value"]
    assert value["budget_ms"] == 90000 and value["expired"] is False


def test_window_resize_reaches_the_injected_window():
    operations = make_operations()
    result = host_call(claimed_facade(operations=operations), "window_resize",
                       {"width": 720, "height": 500})
    assert result["ok"] is True and result["value"] == {"width": 720, "height": 500}
    assert operations.seen_resize == [(720, 500)]  # type: ignore[attr-defined]


def test_window_geometry_keeps_the_maximized_like_judgment_in_the_host():
    value = host_call(claimed_facade(), "window_geometry")["value"]
    assert value["maximized_like"] is True
    # 여유 밖으로 밀면 판정이 뒤집힌다 — 수치가 살아 있다는 증거.
    off = make_operations(geometry=lambda: {
        "x": 40, "y": 40, "width": 800, "height": 600,
        "avail_x": 0, "avail_y": 0, "avail_width": 1920, "avail_height": 1080,
    })
    assert host_call(claimed_facade(operations=off), "window_geometry")["value"][
        "maximized_like"
    ] is False


def test_current_url_and_artifact_identity_pass_through_verified():
    facade = claimed_facade()
    # `url` 은 `owner: "host"` 프로브의 **측정값**이라 값 그대로다 — 러너가 그것을 키 하나에
    # 그대로 싣고, `build.ps1` 이 loopback 오리진 정규식으로 그 문자열을 검사한다.
    assert host_call(facade, "current_url")["value"].startswith("http://127.0.0.1")
    assert host_call(facade, "artifact_identity")["value"] == {
        "artifact_id": "A1", "tree_sha256": "deadbeef"
    }


@pytest.mark.parametrize("key, expected", [("theme", "dark"), ("font_scale", "125")])
def test_settings_readback_reads_the_allowlisted_keys(key, expected):
    """결과는 **값 그대로** — 프로브가 `(await ctx.host(...)) === theme` 로 직접 비교한다."""
    result = host_call(claimed_facade(), "settings_readback", {"setting": key})
    assert result["ok"] is True and result["value"] == expected


def test_output_write_hands_the_result_to_the_injected_writer():
    operations = make_operations()
    result = host_call(claimed_facade(operations=operations), "output_write",
                       {"result": {"url": "http://x/"}})
    assert result["ok"] is True and result["value"] == {"path": "C:/out/selftest.json"}
    assert operations.seen_written == [{"url": "http://x/"}]  # type: ignore[attr-defined]
    assert operations.written == ("C:/out/selftest.json",)


def test_window_destroy_is_clean_and_one_shot():
    operations = make_operations()
    facade = claimed_facade(operations=operations)
    assert host_call(facade, "window_destroy")["ok"] is True
    assert operations.destroyed is True
    assert operations.seen_destroy == [True]  # type: ignore[attr-defined]
    second = host_call(facade, "window_destroy")
    assert second["ok"] is False and second["code"] == api.CODE_ALREADY_CONSUMED


def test_packaged_process_is_refused_loudly_not_silently():
    result = host_call(claimed_facade(), "packaged_process")
    assert result["ok"] is False and result["code"] == api.CODE_OUT_OF_PROCESS
    assert "build.ps1" in result["detail"]


# ------------------------------------------------------------ 개별 op 부정


@pytest.mark.parametrize(
    "op",
    ["mode_select", "global_deadline", "window_geometry", "current_url",
     "artifact_identity", "window_destroy"],
)
def test_payload_free_ops_refuse_any_payload(op):
    result = host_call(claimed_facade(), op, {"x": 1})
    assert result["ok"] is False and result["code"] == api.CODE_MALFORMED_PAYLOAD


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"width": 720},
        {"width": "720", "height": 500},
        {"width": True, "height": 500},
        {"width": 720.5, "height": 500},
    ],
)
def test_window_resize_refuses_malformed_dimensions(payload):
    assert host_call(claimed_facade(), "window_resize", payload)["code"] == (
        api.CODE_MALFORMED_PAYLOAD
    )


@pytest.mark.parametrize("payload", [{"width": 0, "height": 500}, {"width": 720, "height": 99999}])
def test_window_resize_refuses_out_of_range_dimensions(payload):
    result = host_call(claimed_facade(), "window_resize", payload)
    assert result["code"] == api.CODE_MALFORMED_PAYLOAD and "범위 밖" in result["detail"]


def test_input_select_refuses_a_missing_or_unknown_name():
    facade = claimed_facade()
    assert host_call(facade, "input_select", {})["code"] == api.CODE_MALFORMED_PAYLOAD
    unknown = host_call(facade, "input_select", {"setting": "무엇"})
    assert unknown["code"] == api.CODE_UNKNOWN_INPUT and "theme" in unknown["detail"]


def test_settings_readback_refuses_keys_outside_the_allowlist():
    facade = claimed_facade()
    assert host_call(facade, "settings_readback", {})["code"] == api.CODE_MALFORMED_PAYLOAD
    assert host_call(facade, "settings_readback", {"setting": "load_window_geometry"})["code"] == (
        api.CODE_UNKNOWN_OP
    )


def test_settings_readback_refuses_a_source_without_the_reader():
    facade = claimed_facade(operations=make_operations(settings_source=object()))
    assert host_call(facade, "settings_readback", {"setting": "theme"})["code"] == api.CODE_UNAVAILABLE


def test_output_write_refuses_a_non_object_result():
    assert host_call(claimed_facade(), "output_write", {"result": "문자열"})["code"] == (
        api.CODE_MALFORMED_PAYLOAD
    )


@pytest.mark.parametrize(
    "geometry",
    [
        lambda: "객체가 아님",
        lambda: {"x": 0},
        lambda: dict.fromkeys(
            ("x", "y", "width", "height", "avail_x", "avail_y", "avail_width"), 0
        ),
    ],
)
def test_window_geometry_refuses_a_malformed_measurement(geometry):
    facade = claimed_facade(operations=make_operations(geometry=geometry))
    assert host_call(facade, "window_geometry")["code"] == api.CODE_MALFORMED_RESULT


@pytest.mark.parametrize(
    "op, override",
    [
        ("current_url", {"current_url": lambda: 42}),
        ("current_url", {"current_url": lambda: ""}),
        ("artifact_identity", {"artifact_identity": lambda: ["A1"]}),
        ("artifact_identity", {"artifact_identity": lambda: {"artifact_id": "A1"}}),
    ],
)
def test_malformed_native_returns_are_refused_not_forwarded(op, override):
    facade = claimed_facade(operations=make_operations(**override))
    assert host_call(facade, op)["code"] == api.CODE_MALFORMED_RESULT


def test_a_typed_adapter_error_from_a_handler_keeps_its_code():
    """처리기가 타입 있는 실패를 던지면 코드가 :data:`CODE_INTERNAL` 로 뭉개지지 않는다."""

    class Typed(HostOperations):
        def _op_current_url(self, op, payload):
            raise SelftestApiError(api.CODE_UNAVAILABLE, "판독기가 사라졌다")

    result = Typed(current_url=lambda: "http://x/").dispatch("current_url")
    assert result.code == api.CODE_UNAVAILABLE and result.detail == "판독기가 사라졌다"


def test_a_blowing_up_native_call_is_restated_not_swallowed():
    def boom():
        raise OSError("창이 죽었다")

    result = host_call(claimed_facade(operations=make_operations(current_url=boom)), "current_url")
    assert result["code"] == api.CODE_INTERNAL and "창이 죽었다" in result["detail"]


# ------------------------------------------------------------ 주입 없는 호스트


def test_a_host_without_injections_provides_nothing_and_says_why():
    bare = HostOperations()
    assert bare.provides() == ()  # 계획 단계가 붉어진다
    for op in HOST_OPS:
        result = bare.dispatch(op, {})
        assert result.ok is False, op
        if op == "packaged_process":
            assert result.code == api.CODE_OUT_OF_PROCESS  # 부재가 아니라 관할 밖이다
        else:
            assert result.code == api.CODE_UNAVAILABLE and "주입 없음" in result.detail


def test_dispatch_result_payload_shape_is_uniform():
    result = HostOperations().dispatch("packaged_process")
    assert set(result.to_payload()) == {"ok", "op", "code", "detail", "value"}


# ------------------------------------------------------------------ 판정


def test_readiness_parsing_accepts_integer_one():
    assert api.parse_readiness(1) == VERSION
    assert api.parse_readiness(1.0) == VERSION


@pytest.mark.parametrize(
    "raw, error, code",
    [
        (None, FacadeAbsentError, api.CODE_FACADE_ABSENT),
        ("1", ProtocolError, api.CODE_VERSION_UNSUPPORTED),
        (True, ProtocolError, api.CODE_VERSION_UNSUPPORTED),
        (1.5, ProtocolError, api.CODE_VERSION_UNSUPPORTED),
        (2, ProtocolError, api.CODE_VERSION_UNSUPPORTED),
        ({"version": 1}, ProtocolError, api.CODE_VERSION_UNSUPPORTED),
    ],
)
def test_readiness_violations_are_typed_and_distinct(raw, error, code):
    with pytest.raises(error) as err:
        api.parse_readiness(raw)
    assert err.value.code == code


@pytest.mark.parametrize(
    "raw, code",
    [
        (None, api.CODE_FACADE_ABSENT),
        ("문자열", api.CODE_MALFORMED_RESULT),
        ({"ok": "true"}, api.CODE_MALFORMED_RESULT),
        ({"ok": True}, api.CODE_MALFORMED_RESULT),
        ({"ok": True, "runId": ""}, api.CODE_MALFORMED_RESULT),
        ({"ok": True, "run_id": "r1"}, api.CODE_MALFORMED_RESULT),  # snake_case 는 와이어가 아니다
        ({"ok": False, "code": "already_running"}, api.CODE_ALREADY_RUNNING),
        ({"ok": False, "code": "unsupported_version"}, api.CODE_VERSION_UNSUPPORTED),
        ({"ok": False, "code": "quantum_flux"}, "quantum_flux"),
        ({"ok": False}, api.CODE_REJECTED),
    ],
)
def test_start_classification_never_invents_a_run_id(raw, code):
    run_id, actual, detail = api.classify_start(raw)
    assert run_id == "" and actual == code and detail


def test_start_classification_accepts_the_camel_case_run_id():
    assert api.classify_start(start_ok("r9")) == ("r9", api.CODE_OK, "")


@pytest.mark.parametrize(
    "raw, code",
    [
        (None, api.CODE_FACADE_ABSENT),
        (7, api.CODE_MALFORMED_RESULT),
        ({"ok": None}, api.CODE_MALFORMED_RESULT),
        ({"ok": True, "state": "maybe"}, api.CODE_MALFORMED_RESULT),
        ({"ok": True}, api.CODE_MALFORMED_RESULT),
        ({"ok": True, "state": "failed"}, api.CODE_MALFORMED_RESULT),  # 실패는 ok:false 로만 온다
        ({"ok": True, "state": "succeeded"}, api.CODE_MALFORMED_RESULT),  # evidence 없음
        ({"ok": False, "code": "unknown_run"}, api.CODE_UNKNOWN_RUN),
        ({"ok": False, "code": "already_consumed"}, api.CODE_ALREADY_CONSUMED),
        ({"ok": False, "code": "deadline_exceeded"}, api.CODE_DEADLINE_EXCEEDED),
        ({"ok": False}, api.CODE_REJECTED),
    ],
)
def test_poll_classification_never_folds_unknowns_into_running(raw, code):
    outcome = api.classify_poll("r1", raw)
    assert outcome.ok is False and outcome.code == code
    assert outcome.running is False and outcome.succeeded is False


def test_poll_classification_splits_running_from_succeeded():
    running = api.classify_poll("r1", poll_running())
    assert running.running and running.ok and not running.terminal
    assert running.evidence is None
    settled = api.classify_poll("r1", poll_succeeded())
    assert settled.succeeded and settled.terminal and settled.ok
    assert settled.evidence == evidence()
    assert settled.result is not None and settled.result["order"] == ["p"]


def test_run_failed_keeps_the_evidence_and_is_terminal():
    outcome = api.classify_poll("r1", poll_failed())
    assert outcome.code == api.CODE_RUN_FAILED
    assert outcome.failed and outcome.terminal and outcome.ok is False
    assert outcome.state == "failed"
    # **증거를 버리지 않는다** — 안의 error 가 실앱 게이트를 붉히는 그 값이다.
    assert outcome.evidence is not None and "error" in outcome.evidence
    assert outcome.detail == "프로브 실패 1건"
    assert outcome.result is not None and outcome.result["skipped"] == []


def test_run_failed_without_evidence_restates_the_second_defect():
    raw = dict(poll_failed())
    raw.pop("evidence")
    outcome = api.classify_poll("r1", raw)
    assert outcome.code == api.CODE_RUN_FAILED  # 실패는 그대로 실패다
    assert outcome.evidence is None
    assert "evidence 객체가 없다" in outcome.detail  # 두 번째 결함까지 재진술한다


def test_run_failed_counts_zero_when_errors_is_not_an_array():
    raw = dict(poll_failed(), errors="배열이 아님")
    assert api.classify_poll("r1", raw).detail.startswith("프로브 실패 0건")


# ------------------------------------------------------------------ 드라이버


def test_running_then_succeeded_flow_polls_until_settled():
    clock = FakeClock()
    evaluator = FakeEvaluator(1, start_ok(), poll_running(), poll_running(), poll_succeeded())
    client = SelftestClient(evaluator, now=clock.now, sleep=clock.sleep, poll_interval_s=0.05)
    outcome = client.drive("boot", probe_input="dark", flags={"offline": True})
    assert outcome.ok and outcome.code == api.CODE_OK and outcome.run_id == "r1"
    assert outcome.evidence == evidence() and outcome.has_evidence
    assert outcome.elapsed_ms == 100  # 폴 사이 수면 2회 × 50ms
    assert evaluator.calls[0] == api.readiness_expression()
    actions = [envelope_of(call)["action"] for call in evaluator.calls[1:]]
    assert actions == ["start", "poll", "poll", "poll"]
    assert envelope_of(evaluator.calls[1])["input"] == "dark"
    assert outcome.raise_for_failure() is outcome


def test_terminal_result_is_retrieved_exactly_once():
    evaluator = FakeEvaluator(poll_succeeded())
    client = SelftestClient(evaluator)
    assert client.poll("r1").succeeded
    replay = client.poll("r1")
    assert replay.code == api.CODE_ALREADY_CONSUMED and "r1" in replay.detail
    assert len(evaluator.calls) == 1  # 두 번째는 창까지 가지도 않는다


def test_a_failed_run_is_also_consumed_exactly_once():
    evaluator = FakeEvaluator(poll_failed())
    client = SelftestClient(evaluator)
    assert client.poll("r1").failed
    assert client.poll("r1").code == api.CODE_ALREADY_CONSUMED
    assert len(evaluator.calls) == 1


def test_failed_run_reaches_the_outcome_with_evidence_for_the_output_write():
    evaluator = FakeEvaluator(1, start_ok(), poll_failed())
    outcome = SelftestClient(evaluator).drive("boot")
    assert outcome.code == api.CODE_RUN_FAILED and outcome.ok is False
    assert outcome.has_evidence and outcome.evidence is not None
    assert "error" in outcome.evidence
    assert outcome.result is not None and outcome.result["errors"][0]["probe"] == "p"
    assert outcome.alarm_text.startswith("자가검증 boot 실패 [run-failed]")
    with pytest.raises(RefusedError):
        outcome.raise_for_failure()


def test_unknown_run_id_stops_the_loop_with_its_own_code_and_no_evidence():
    evaluator = FakeEvaluator(1, start_ok(), {"ok": False, "code": "unknown_run"})
    outcome = SelftestClient(evaluator).drive("boot")
    assert outcome.code == api.CODE_UNKNOWN_RUN and outcome.run_id == "r1"
    assert outcome.evidence is None and outcome.has_evidence is False


def test_python_deadline_expiry_is_loud_and_yields_no_partial_evidence():
    clock = FakeClock()
    evaluator = FakeEvaluator(1, start_ok(), *[poll_running() for _ in range(1000)])
    lines: list[str] = []
    client = SelftestClient(
        evaluator, budget_s=1.0, poll_interval_s=0.25,
        now=clock.now, sleep=clock.sleep, log=lines.append,
    )
    outcome = client.drive("boot")
    assert outcome.code == api.CODE_DEADLINE_EXCEEDED
    assert outcome.evidence is None  # 낡은 부분 결과를 성공으로 접지 않는다
    assert outcome.run_id == "r1"
    assert any("예산" in line for line in lines)
    with pytest.raises(RefusedError):
        outcome.raise_for_failure()


def test_facade_absent_stops_before_start():
    """파사드가 끝내 안 서면 **시한까지 기다린 뒤** 부재로 확정하고 start 는 시도하지 않는다.

    설치는 비동기라 한 번만 묻고 부재로 확정하면 아직 부팅 중인 창을 죽은 것으로 읽는다.
    그래서 `drive` 는 폴링한다 — 여기서는 예산을 0 으로 줘 첫 판정 직후 시한이 지나게 한다
    (실제 예산으로 돌리면 이 테스트가 80초 걸린다).
    """
    evaluator = FakeEvaluator(None)
    outcome = SelftestClient(evaluator, budget_s=0.001, sleep=lambda _s: None).drive("boot")
    assert outcome.facade_absent and outcome.code == api.CODE_FACADE_ABSENT
    # 준비 확인만 반복하고 start 표현식은 한 번도 내보내지 않는다.
    assert set(evaluator.calls) == {api.readiness_expression()}
    with pytest.raises(FacadeAbsentError):
        outcome.raise_for_failure()


def test_readiness_wait_settles_once_the_facade_appears():
    """양성 대조 — 늦게 서는 파사드는 **기다려서** 잡는다(폴링이 실제로 재시도한다).

    음성만 있으면 "언제나 부재"도 통과한다.
    """
    answers = [None, None, 1]

    class LateFacade:
        def __init__(self):
            self.calls: "list[str]" = []

        def __call__(self, expression: str) -> object:
            self.calls.append(expression)
            return answers.pop(0) if answers else 1

    evaluator = LateFacade()
    client = SelftestClient(evaluator, budget_s=5.0, sleep=lambda _s: None)

    assert client.await_readiness(client.new_deadline()) == 1
    assert len(evaluator.calls) == 3, "부재 두 번을 지나 세 번째에 잡아야 한다"


def test_unsupported_facade_version_stops_before_start():
    evaluator = FakeEvaluator(2)
    outcome = SelftestClient(evaluator).drive("boot")
    assert outcome.code == api.CODE_VERSION_UNSUPPORTED and len(evaluator.calls) == 1
    with pytest.raises(ProtocolError):
        outcome.raise_for_failure()


def test_evaluator_blowup_becomes_a_transport_outcome():
    outcome = SelftestClient(FakeEvaluator(raises=RuntimeError("창이 죽었다"))).drive("boot")
    assert outcome.code == api.CODE_EVALUATE_FAILED and "창이 죽었다" in outcome.detail
    assert "readiness" in outcome.detail
    with pytest.raises(TransportError):
        outcome.raise_for_failure()


def test_evaluator_blowup_during_polling_is_carried_as_a_poll_failure():
    class Flaky:
        def __init__(self):
            self.calls = 0

        def __call__(self, expression):
            self.calls += 1
            if self.calls == 1:
                return 1
            if self.calls == 2:
                return start_ok()
            raise RuntimeError("폴 도중 창이 죽었다")

    outcome = SelftestClient(Flaky()).drive("boot")
    assert outcome.code == api.CODE_EVALUATE_FAILED and outcome.run_id == "r1"


def test_a_typed_error_from_the_evaluator_is_not_relabelled_as_transport():
    """평가기가 이미 타입 있는 실패를 던지면 그대로 올라간다 — 코드가 두 번 뭉개지지 않는다."""
    raiser = FakeEvaluator(raises=SelftestApiError(api.CODE_UNAUTHORIZED, "브리지가 거절했다"))
    outcome = SelftestClient(raiser).drive("boot")
    assert outcome.code == api.CODE_UNAUTHORIZED and outcome.detail == "브리지가 거절했다"


def test_malformed_start_result_is_a_protocol_error():
    client = SelftestClient(FakeEvaluator(1, {"ok": True}))
    client.readiness()
    with pytest.raises(ProtocolError):
        client.start("boot")


def test_start_refusal_is_a_refused_error():
    client = SelftestClient(FakeEvaluator(1, {"ok": False, "code": "already_running"}))
    client.readiness()
    with pytest.raises(RefusedError) as err:
        client.start("boot")
    assert err.value.code == api.CODE_ALREADY_RUNNING


def test_start_on_an_absent_facade_is_facade_absent():
    with pytest.raises(FacadeAbsentError):
        SelftestClient(FakeEvaluator(None)).start("boot")


def test_new_deadline_uses_the_client_budget_and_clock():
    clock = FakeClock()
    deadline = SelftestClient(FakeEvaluator(), budget_s=12.0, now=clock.now).new_deadline()
    assert deadline.snapshot()["budget_ms"] == 12000


def test_for_window_wraps_evaluate_js():
    class FakeWindow:
        def __init__(self):
            self.calls: list[str] = []

        def evaluate_js(self, expression):
            self.calls.append(expression)
            return 1

    window = FakeWindow()
    assert SelftestClient.for_window(window).readiness() == VERSION
    assert window.calls == [api.readiness_expression()]


def test_outcome_alarm_text_names_the_code_and_the_mode():
    outcome = SelftestOutcome("geometry", False, api.CODE_INTERNAL, "무언가")
    assert outcome.alarm_text == "자가검증 geometry 실패 [internal] 무언가"


# ------------------------------------------------------------------ 비유출


def test_the_token_never_reaches_an_expression_a_result_a_repr_or_a_log():
    """토큰이 사는 곳은 파이썬 프로세스 메모리 + JS 클로저뿐이다 — 나머지 전부를 센다."""
    lines: list[str] = []
    operations = make_operations()
    facade = SelftestHostFacade(operations, token=TOKEN, log=lines.append)
    claimed = facade.selftest_claim(1)
    assert claimed["token"] == TOKEN  # 악수 반환만이 토큰을 건네는 유일한 자리다

    results = [
        host_call(facade, "current_url"),
        host_call(facade, "window_resize", {"width": 900, "height": 820}),
        host_call(facade, "settings_readback", {"setting": "theme"}),
        host_call(facade, "packaged_process"),
        host_call(facade, "rm_rf"),
        host_call(facade, "current_url", token="틀린-토큰"),
        facade.selftest_claim(1),
        facade.selftest_claim(9),
        facade.claim_state(),
    ]
    assert api.token_leaks(TOKEN, *results) == ()
    assert api.token_leaks(TOKEN, facade, operations, repr(facade), repr(operations)) == ()
    assert api.token_leaks(TOKEN, lines, *lines) == ()

    # 드라이버가 내는 표현식·판정 어디에도 없다.
    evaluator = FakeEvaluator(1, start_ok(), poll_succeeded())
    driver_log: list[str] = []
    outcome = SelftestClient(evaluator, log=driver_log.append).drive("boot", probe_input="dark")
    assert api.token_leaks(TOKEN, *evaluator.calls) == ()
    assert api.token_leaks(TOKEN, outcome, repr(outcome), str(outcome)) == ()
    assert api.token_leaks(TOKEN, driver_log) == ()


def test_module_source_carries_no_literal_token_and_no_eval_and_no_cycle():
    """선언이 아니라 **소스 전체**를 센다 — 우회 한 줄이 계약을 조용히 되살린다."""
    source = Path(api.__file__).read_text(encoding="utf-8-sig")
    assert "import webview" not in source and "from webview" not in source
    assert "from .app import" not in source and "import app" not in source  # 순환 금지
    assert re.search(r"\beval\(", source) is None  # 일반 eval 은 없다
    assert source.count('"window.__hwpxTest"') == 1  # 뿌리는 상수 한 곳에서만 난다
    # 토큰을 로그·표현식으로 흘릴 수 있는 유일한 이름은 self._token 이고, 그 등장 자리를 못박는다.
    assert source.count("self._token") == 3  # 대입 · 비교 · 악수 반환
