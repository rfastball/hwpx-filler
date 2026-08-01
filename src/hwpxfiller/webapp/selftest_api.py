"""``--selftest`` 호스트 경계의 **버전 있는 단일 파사드 어댑터**(N-09).

오늘의 ``_selftest_drive`` 는 창 하나를 붙들고 ①JS 프로브 문자열을 손으로 이어 붙이고
②전역 ``window.__*`` 스태시에 결과가 쌓이길 폴링하고 ③``window.resize`` · ``settings.load_*`` ·
``window.destroy`` 같은 **호스트 전용 연산**을 드라이버 본문에서 직접 수행한다. 그래서 세 가지가
조용히 틀린다:

- **폴링 만료에 else 가 없다.** 시한이 지나도 경보 없이 흘러가 모양만 맞는 낡은 스태시를 회수한다.
  이 어댑터의 폴링은 만료를 :data:`CODE_DEADLINE_EXCEEDED` 로 **확정**하고 부분 결과를 성공으로
  접지 않는다.
- **호스트 연산이 임의다.** 프런트가 무엇을 시킬 수 있는지 적힌 곳이 없다. 여기서는 11개
  이름(:data:`HOST_OPS`)만 통과하고, 이름·payload 모두 **연산별로** 검증된다. 일반 ``eval`` 은 없다.
- **테스트 훅이 제품에 상주한다.** pywebview 는 ``js_api`` 객체의 **공개**(밑줄 없는) 메서드를
  ``dir()`` 로 자동 반영하므로(``webview/util.py`` 의 ``get_functions``), 파사드 메서드를 그냥
  얹으면 정상 부팅에서도 웹이 호스트 연산을 부를 수 있다. 그래서 :class:`SelftestHostFacade` 는
  **조건부 부착**이다 — :func:`attach_selftest_facade` 가 ``--selftest`` 때만 이름 둘을 심고,
  평상시 js_api 표면에는 테스트 메서드가 **한 개도 없다**.

## 계약 v1 — 두 방향, 두 규율

**Python → 웹.** 전역은 ``Object.freeze({version: 1, run})`` 하나다. 준비 확인은 **호출이 아니라
읽기**(``window.__hwpxTest.version``)이고, 요청은 ``run(envelope)`` 하나로 들어간다. 봉투는
**평평하다** — ``action`` 과 ``mode``·``input``·``flags``·``runId`` 가 형제다:

    window.__hwpxTest ? window.__hwpxTest.version : null          // 준비 확인(읽기)
    window.__hwpxTest.run({version:1, action:"start", mode, input?, flags?})
    window.__hwpxTest.run({version:1, action:"poll", runId})

봉투에 **토큰은 실리지 않는다** — 이 방향은 신뢰 경계 안(우리 프로세스가 우리 페이지에 말한다)
이고, 토큰을 표현식에 박으면 그 문자열이 로그·예외 재진술·에러 스크린샷 어디로든 샌다. 그래서
이 모듈이 만드는 **어떤 표현식에도** 토큰은 등장하지 않는다(:func:`token_leaks` 가 그것을 센다).

**회수는 poll 이 진다.** 별도 consume 단계는 없다 — 정착을 처음 본 ``poll`` 이 종단 결과를 함께
돌려주고, 두 번째 ``poll`` 은 ``already_consumed`` 로 거절된다. 그래서 "회수를 두 번 했는데 두 번
다 뭔가 돌아왔다"는 상태가 아예 생기지 않는다.

**웹 → Python** (``pywebview.api.selftest_claim`` · ``selftest_host_op``). 이 방향은 신뢰 경계를
**넘어온다** — 페이지 안 아무 스크립트나 부를 수 있으므로 토큰이 필요하다. 토큰은
:func:`mint_token` 이 ``secrets`` 로 만들고 **파이썬 프로세스 메모리에만** 산다. 악수(claim)가
1회 성공하면 그 값이 JS 클로저로 건너간다.

위협 모델은 정직하게 적는다: claim 은 **선착순 1회**다. 토큰을 미리 아는 호출자가 없으므로 claim
자체를 암호로 막을 수는 없고, 대신 (i) 파사드는 ``--selftest`` 부팅에만 존재하고 (ii) 그 부팅의
페이지는 tree 해시가 검증된 loopback 산출물이며 (iii) 두 번째 claim 은 :data:`CODE_ALREADY_CLAIMED`
로 **거절**되어 조용한 탈취가 불가능하다. 드라이버는 :meth:`SelftestHostFacade.claim_state` 로
악수가 정확히 한 번 있었는지 되읽어 어긋나면 시끄럽게 실패할 수 있다.

**오늘의 ``bridge.js`` 는 호스트 요청에 토큰을 싣지 않는다**(``selftest_host_op(op, payload)``).
그래서 이 어댑터의 능력 관문은 "악수가 있었는가"이고, 토큰이 **실려 오면** 그때는 검증한다
(:data:`CODE_UNAUTHORIZED`). 토큰을 실제 관문으로 쓰려면 브리지가 세 번째 인자로 넘겨야 한다 —
그 전까지 토큰은 있는데 안 쓰는 게 아니라, **선택적 강화**로 배선돼 있다.

## 경계

- ``app.py`` 를 import 하지 않는다(순환 회피). **pywebview 도 모른다** — 창·설정·아티팩트·출력은
  전부 **주입**이라 이 모듈 전체가 헤드리스로 단위 검증된다.
- JS 표현식 조립은 전부 여기 있다. 이 모듈이 내는 표현식의 뿌리는 ``window.__hwpxTest`` 뿐이고,
  **호출**하는 멤버는 ``run`` 하나뿐이다(:data:`_METHODS` 가 강제). 그 밖에 읽는 멤버는
  준비 확인의 ``version`` 하나다(:data:`READINESS_MEMBER`).
- 직렬화 규율은 :mod:`hwpxfiller.webapp.product_api` 의 :func:`~product_api.encode_js_literal` 을
  **재사용**한다(짝 없는 서로게이트 무손실 대피 · U+2028/9 이스케이프 · NaN 거절). 규율을 복제하면
  둘이 갈라진다 — 그쪽이 정본이다.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .product_api import ProductApiError, encode_js_literal

# ------------------------------------------------------------------ 계약 상수

#: 이 어댑터가 말할 줄 아는 유일한 버전. 다른 값은 협상이 아니라 **거절**이다.
VERSION = 1

#: 파사드 뿌리. 이 모듈이 내는 표현식에 등장하는 유일한 전역이다.
ROOT = "window.__hwpxTest"

#: **호출** 허용 멤버 화이트리스트 — 오타 하나가 표면을 넓히지 못하게 한다.
_METHODS = ("run",)

#: 준비 확인이 **읽는** 멤버. 읽기지 호출이 아니다 — 파사드가 없어도 던지지 않고 ``null`` 이 온다.
READINESS_MEMBER = "version"

ACTION_START = "start"
ACTION_POLL = "poll"

#: 봉투가 실을 수 있는 action 전부. 순서가 곧 구동 순서다(준비 → 개시 → 폴링).
ACTIONS: "tuple[str, ...]" = (ACTION_START, ACTION_POLL)

#: 실행 식별자의 **와이어 키**. 파이썬 쪽 이름은 snake_case 지만 JS 가 읽는 키는 camelCase 다 —
#: 이 한 곳에서만 이름이 바뀐다(자리마다 문자열을 쓰면 하나가 조용히 어긋난다).
KEY_RUN_ID = "runId"

#: 실행 상태 — poll 이 돌려줄 수 있는 값 전부. 그 밖은 형태 위반이다.
STATE_RUNNING = "running"
STATE_SUCCEEDED = "succeeded"
STATE_FAILED = "failed"
STATES: "tuple[str, ...]" = (STATE_RUNNING, STATE_SUCCEEDED, STATE_FAILED)

#: 종단 상태 — 이 상태를 처음 본 poll 이 결과를 회수한다.
TERMINAL_STATES: "tuple[str, ...]" = (STATE_SUCCEEDED, STATE_FAILED)

#: 호스트 소유 연산 11종. **``frontend/src/selftest/runner.js`` 의 ``HOST_OPS`` 와 같은 목록이고
#: 같은 순서다** — 두 벌이 갈라지면 프런트는 요청하는데 호스트는 모르는 이름이 생긴다.
#: 그 드리프트는 ``tests/test_selftest_api.py`` 가 runner.js 를 직접 읽어 센다.
HOST_OPS: "tuple[str, ...]" = (
    "mode_select",
    "input_select",
    "global_deadline",
    "window_resize",
    "window_geometry",
    "current_url",
    "artifact_identity",
    "settings_readback",
    "output_write",
    "window_destroy",
    "packaged_process",
)

# ---------------------------------------------------------------- 연산 분류

#: (가) 프런트 러너가 **실행 중에 요청**하는 연산.
CLASS_RUNTIME_REQUEST = "runtime-request"
#: (나) 파이썬 드라이버가 **자기 책임으로** 수행하는 종료·출력·예산 연산(요청받지 않는다).
CLASS_DRIVER_OWNED = "driver-owned"
#: (다) 이 프로세스 **밖**의 패키징 오케스트레이션(build.ps1)에 속하는 연산.
CLASS_PACKAGING = "packaging-orchestration"
#: (라) HOST_OPS 에 선언은 됐지만 **오늘 아무도 요청하지 않는** 연산.
CLASS_DECLARED_UNUSED = "declared-unused"

OP_CLASSES: "tuple[str, ...]" = (
    CLASS_RUNTIME_REQUEST,
    CLASS_DRIVER_OWNED,
    CLASS_PACKAGING,
    CLASS_DECLARED_UNUSED,
)


@dataclass(frozen=True)
class HostOpSpec:
    """연산 하나의 **기계가 읽는** 신원: 이름 · 분류 · 사유.

    분류를 산문에 묻으면 "이 op 는 누가 부르나"가 사람 기억에만 남는다. 데이터로 두면 테스트가
    11개 전부를 정확히 한 번씩 덮는지 셀 수 있고, 새 op 가 분류 없이 늘 수 없다.
    """

    name: str
    op_class: str
    reason: str


#: 11개 op 의 분류표. **각 이름이 정확히 한 번** 등장한다.
OP_CLASSIFICATION: "dict[str, HostOpSpec]" = {
    spec.name: spec
    for spec in (
        HostOpSpec(
            "mode_select",
            CLASS_DECLARED_UNUSED,
            "환경변수→모드 판정은 창이 열리기 **전에** 끝나고 드라이버가 start 봉투의 mode 로 "
            "넘긴다 — 실행 중 요청 경로가 없다. 구현은 두되 소비자는 오늘 0명이다.",
        ),
        HostOpSpec(
            "input_select",
            CLASS_RUNTIME_REQUEST,
            "쓰기 단계 프로브(theme_write·font_scale_write)가 심을 값(테마 이름·배율 이름)을 "
            "호스트에게 묻는다 — persistence_geometry.js 의 requiresHost 에 실재한다.",
        ),
        HostOpSpec(
            "global_deadline",
            CLASS_DRIVER_OWNED,
            "프로세스 전체 시한(90초)은 드라이버의 예산이다. 프런트는 자기 프로브 시한만 알고, "
            "이 op 는 남은 예산을 되읽는 창구일 뿐 예산을 옮기지 않는다.",
        ),
        HostOpSpec(
            "window_resize",
            CLASS_RUNTIME_REQUEST,
            "네이티브 창 크기 변경은 문서 밖이라 프런트가 못 한다. boot_routing_overlay·job·"
            "persistence_geometry 세 클러스터가 hostSetup 으로 요청한다(오늘 app.py 의 resize 6회).",
        ),
        HostOpSpec(
            "window_geometry",
            CLASS_RUNTIME_REQUEST,
            "OS 창 프레임 실측(screenX/outerWidth/screen.avail*)과 **maximized_like 판정**은 "
            "호스트가 진다 — persistence_geometry.js 가 host 소유 프로브로 요청한다.",
        ),
        HostOpSpec(
            "current_url",
            CLASS_RUNTIME_REQUEST,
            "pywebview window.get_current_url() — 문서 안에서 읽는 location 과 달리 "
            "**네이티브가 실제로 어디에 있는지**를 말한다. host 소유 프로브가 요청한다.",
        ),
        HostOpSpec(
            "artifact_identity",
            CLASS_RUNTIME_REQUEST,
            "artifact_id · tree_sha256 은 디스크 산출물의 정체라 문서 안에서 알 수 없다. "
            "오프라인 런타임 증거의 **호스트 몫**(창 생성 후 산출물이 바뀌지 않았는가)도 여기다 — "
            "동일 오리진·금지 자원 판정은 프런트가 문서 안에서 진다.",
        ),
        HostOpSpec(
            "settings_readback",
            CLASS_RUNTIME_REQUEST,
            "settings.json 디스크 되읽기(load_theme/load_font_scale) — 오리진 비의존 영속의 "
            "확정이라 localStorage 로는 대체되지 않는다. persistence_geometry.js 가 요청한다.",
        ),
        HostOpSpec(
            "output_write",
            CLASS_DRIVER_OWNED,
            "증거 파일 쓰기(HWPX_SELFTEST_OUT)는 드라이버의 출력 책임이다 — 프로브가 부분 결과를 "
            "직접 디스크에 흘리면 '완주했는가'가 구조가 아니라 선택이 된다.",
        ),
        HostOpSpec(
            "window_destroy",
            CLASS_DRIVER_OWNED,
            "정식 종료는 출력 **뒤에** 정확히 한 번이다. 프로브가 부를 수 있으면 증거를 쓰기 전에 "
            "창이 죽는 경로가 생긴다 — 그래서 드라이버만 부르고 두 번째 호출은 거절된다.",
        ),
        HostOpSpec(
            "packaged_process",
            CLASS_PACKAGING,
            "동결 exe 프로세스 조율은 build.ps1 이 **이 프로세스 밖에서** 한다. 안에서 흉내 내면 "
            "패키징 게이트가 자기 자신을 검사하게 된다 — 그래서 provides 에서 빠지고(계획이 "
            "붉어진다) 호출되면 시끄럽게 거절한다(조용한 no-op 금지).",
        ),
    )
}

#: 분류별 이름 묶음 — 소비자가 "누가 부르는 op 인가"를 한 줄로 묻는다.
OPS_BY_CLASS: "dict[str, tuple[str, ...]]" = {
    op_class: tuple(name for name, spec in OP_CLASSIFICATION.items() if spec.op_class == op_class)
    for op_class in OP_CLASSES
}

#: 이 프로세스가 **댈 수 없는** op — 등록은 돼 있지만 ``provides`` 에서 빠진다.
#: 계획 단계에서 붉어져야지, 실행 중간에 죽으면 어디까지 갔는지가 증거에서 사라진다.
UNPROVIDABLE_OPS: "frozenset[str]" = frozenset({"packaged_process"})

#: ``settings_readback`` 이 되읽을 수 있는 키 → settings 모듈의 판독 함수. **이것도 화이트리스트다**
#: — 임의 ``load_*`` 이름을 payload 로 받으면 그게 곧 일반 invoke 다.
SETTINGS_READBACK_KEYS: "dict[str, str]" = {
    "theme": "load_theme",
    "font_scale": "load_font_scale",
}

#: ``window_geometry`` 가 측정값에서 반드시 봐야 하는 필드. 하나라도 없으면 형태 위반이다.
GEOMETRY_FIELDS: "tuple[str, ...]" = (
    "x", "y", "width", "height", "avail_x", "avail_y", "avail_width", "avail_height",
)

#: ``maximized_like`` 판정 여유(px). app.py 의 수치를 그대로 옮긴다 — 조용히 늘리지 않는다.
GEOMETRY_EDGE_SLACK = 32
GEOMETRY_SPAN_SLACK = 8

#: 창 크기 요청의 허용 범위(px). 최소 창 크기(760×600)보다 **작은 값도 허용한다** — 오늘의
#: overlay 프로브가 720×500 을 쓴다. 막는 것은 음수·0·비정상적으로 큰 값뿐이다.
RESIZE_MIN = 1
RESIZE_MAX = 10000

# ------------------------------------------------------------------ 실패 코드

CODE_OK = "ok"

# --- 통로(Python↔웹) 쪽
CODE_FACADE_ABSENT = "facade-absent"
CODE_EVALUATE_FAILED = "evaluate-failed"
CODE_VERSION_UNSUPPORTED = "version-unsupported"
CODE_MALFORMED_RESULT = "malformed-result"
CODE_UNKNOWN_RUN = "unknown-run"
CODE_ALREADY_RUNNING = "already-running"
CODE_ALREADY_CONSUMED = "already-consumed"
CODE_RUN_FAILED = "run-failed"
CODE_DEADLINE_EXCEEDED = "deadline-exceeded"
CODE_PAYLOAD_UNSERIALIZABLE = "payload-unserializable"
CODE_REJECTED = "rejected"

# --- 파사드(웹→Python) 쪽
CODE_UNAUTHORIZED = "unauthorized"
CODE_MALFORMED_PAYLOAD = "malformed-payload"
CODE_ALREADY_CLAIMED = "already-claimed"
CODE_NOT_CLAIMED = "not-claimed"
CODE_UNKNOWN_OP = "unknown-op"
CODE_UNKNOWN_ACTION = "unknown-action"
CODE_UNKNOWN_INPUT = "unknown-input"
CODE_UNAVAILABLE = "unavailable"
CODE_OUT_OF_PROCESS = "out-of-process"

CODE_INTERNAL = "internal"

#: 안정 코드 전부. 새 코드를 늘리면 여기에 올려야 하고, 그러면 소비자 테스트가 본다.
CODES: "tuple[str, ...]" = (
    CODE_OK,
    CODE_FACADE_ABSENT,
    CODE_EVALUATE_FAILED,
    CODE_VERSION_UNSUPPORTED,
    CODE_MALFORMED_RESULT,
    CODE_UNKNOWN_RUN,
    CODE_ALREADY_RUNNING,
    CODE_ALREADY_CONSUMED,
    CODE_RUN_FAILED,
    CODE_DEADLINE_EXCEEDED,
    CODE_PAYLOAD_UNSERIALIZABLE,
    CODE_REJECTED,
    CODE_UNAUTHORIZED,
    CODE_MALFORMED_PAYLOAD,
    CODE_ALREADY_CLAIMED,
    CODE_NOT_CLAIMED,
    CODE_UNKNOWN_OP,
    CODE_UNKNOWN_ACTION,
    CODE_UNKNOWN_INPUT,
    CODE_UNAVAILABLE,
    CODE_OUT_OF_PROCESS,
    CODE_INTERNAL,
)

#: JS 파사드가 쓰는 안정 코드 11종(**snake_case**) → 이 모듈의 코드(**kebab-case**).
#: 두 어휘를 하나로 합치지 않는 이유: 와이어 문자열을 그대로 파이썬 코드로 쓰면 JS 가 코드를
#: 하나 바꿀 때 파이썬 소비자의 분기가 조용히 죽는다. 대신 **번역표를 명시**하고, 표에 없는
#: 코드는 다른 뜻으로 재라벨하지 않고 **원문 그대로** 진다(:func:`python_code`).
JS_CODES: "tuple[str, ...]" = (
    "malformed_request",
    "unsupported_version",
    "unknown_action",
    "unauthorized",
    "already_claimed",
    "already_running",
    "unknown_run",
    "already_consumed",
    "deadline_exceeded",
    "run_failed",
    "internal",
)

JS_CODE_MAP: "dict[str, str]" = {
    "malformed_request": CODE_MALFORMED_PAYLOAD,
    "unsupported_version": CODE_VERSION_UNSUPPORTED,
    "unknown_action": CODE_UNKNOWN_ACTION,
    "unauthorized": CODE_UNAUTHORIZED,
    "already_claimed": CODE_ALREADY_CLAIMED,
    "already_running": CODE_ALREADY_RUNNING,
    "unknown_run": CODE_UNKNOWN_RUN,
    "already_consumed": CODE_ALREADY_CONSUMED,
    "deadline_exceeded": CODE_DEADLINE_EXCEEDED,
    "run_failed": CODE_RUN_FAILED,
    "internal": CODE_INTERNAL,
}


def python_code(js_code: object) -> str:
    """JS 코드를 이 모듈의 코드로. **모르는 코드는 삼키지도 재라벨하지도 않는다.**

    빈 값·문자열 아님만 :data:`CODE_REJECTED` 로 접고(거절이라는 사실은 남는다), 그 밖의 미지
    문자열은 **원문 그대로** 돌려준다 — 모르는 실패를 아는 실패의 이름으로 바꾸면 진단이
    거짓말을 한다.
    """
    if not isinstance(js_code, str) or not js_code:
        return CODE_REJECTED
    return JS_CODE_MAP.get(js_code, js_code)


class SelftestApiError(Exception):
    """자가검증 통로의 타입 있는 실패 — 드라이버가 그대로 경보 문안으로 쓴다.

    ``code`` 는 기계가 가르는 안정 식별자, ``detail`` 은 사람이 읽는 사유, ``action`` 은 어느
    국면이었는지(조립 단계면 ``None``)다. **토큰은 절대 담기지 않는다** — 예외 문자열이 로그로
    나가는 순간 프로세스 메모리 제약이 무의미해진다.
    """

    def __init__(self, code: str, detail: str, *, action: "str | None" = None) -> None:
        self.code = code
        self.detail = detail
        self.action = action
        where = f"{action} " if action else ""
        super().__init__(f"{where}[{code}] {detail}")


class FacadeAbsentError(SelftestApiError):
    """``window.__hwpxTest`` 자체가 없다 — 셀프테스트 번들 미주입. 거절과 **다른 사건**이다."""


class TransportError(SelftestApiError):
    """평가기(evaluate_js)가 던졌다 — 창이 이미 죽었거나 백엔드가 실패했다."""


class ProtocolError(SelftestApiError):
    """파사드가 계약 밖 형태로 답했다 — 버전·모양."""


class RefusedError(SelftestApiError):
    """파사드가 구조화된 거절(`{ok: false, code}`)로 답했다."""


# ------------------------------------------------------------------ 토큰


def mint_token() -> str:
    """프로세스 1회용 능력 토큰. ``secrets`` 로만 만든다 — 예측 가능한 값은 능력이 아니다."""
    return secrets.token_urlsafe(32)


def token_leaks(token: str, *places: object) -> "tuple[str, ...]":
    """토큰이 **샌 자리**를 되짚는다 — 테스트가 비유출을 단언하는 창구.

    표현식·판정 결과·객체 repr·로그 줄 어디에든 토큰 문자열이 있으면 그 자리를 돌려준다. 빈
    튜플이 곧 "안 샜다"다. 빈 토큰으로는 이 질문 자체가 성립하지 않으므로 시끄럽게 거절한다
    (빈 문자열은 모든 문자열에 들어 있어 언제나 '샜다'가 되거나 언제나 통과가 된다).
    """
    if not token:
        raise SelftestApiError(CODE_INTERNAL, "빈 토큰으로는 비유출을 물을 수 없다")
    leaked: "list[str]" = []
    for index, place in enumerate(places):
        text = place if isinstance(place, str) else repr(place)
        if token in text:
            leaked.append(f"#{index}: {type(place).__name__}")
    return tuple(leaked)


# ------------------------------------------------------------------ 예산


@dataclass
class ProcessDeadline:
    """**파이썬 프로세스**의 시한 — JS 프로브별 시한과 독립이다.

    둘을 하나로 합치면 렌더러가 통째로 매달렸을 때 파이썬도 같이 매달린다(감시자가 감시 대상
    안에 있다). 그래서 드라이버는 자기 시계로 따로 세고, 만료를 :data:`CODE_DEADLINE_EXCEEDED`
    로 확정한 뒤 **부분 결과를 성공으로 접지 않는다**.
    """

    budget_s: float
    now: "Callable[[], float]" = time.monotonic
    started_at: float = field(default=0.0)

    def __post_init__(self) -> None:
        if self.budget_s <= 0:
            raise SelftestApiError(CODE_INTERNAL, f"예산은 양수여야 한다: {self.budget_s!r}")
        self.started_at = self.now()

    def elapsed_s(self) -> float:
        return self.now() - self.started_at

    def remaining_s(self) -> float:
        return self.budget_s - self.elapsed_s()

    def expired(self) -> bool:
        return self.remaining_s() <= 0

    def snapshot(self) -> dict:
        """JSON-safe 예산 스냅샷 — ``global_deadline`` op 가 그대로 돌려준다."""
        return {
            "budget_ms": round(self.budget_s * 1000),
            "elapsed_ms": round(self.elapsed_s() * 1000),
            "remaining_ms": round(self.remaining_s() * 1000),
            "expired": self.expired(),
        }


# ------------------------------------------------------------------ 표현식


def _encode(value: object) -> str:
    """제품 경계의 직렬화 규율을 그대로 빌린다 — 규율을 복제하면 둘이 갈라진다."""
    try:
        return encode_js_literal(value)
    except ProductApiError as exc:
        raise SelftestApiError(CODE_PAYLOAD_UNSERIALIZABLE, exc.detail) from exc


def request_envelope(action: str, fields: "Mapping[str, object] | None" = None) -> dict:
    """``run()`` 봉투 — **평평하다**: ``{version, action, …}`` 로 필드가 형제로 선다.

    **토큰은 없다.** 이 방향(Python→웹)은 신뢰 경계 안이고, 표현식에 토큰을 박으면 그 문자열이
    로그·예외 재진술로 샌다. ``version``·``action`` 을 필드로 덮어쓰려는 시도는 거절한다 —
    봉투의 뼈대를 필드가 흔들면 파사드가 다른 요청을 받는다.
    """
    if action not in ACTIONS:
        raise SelftestApiError(CODE_INTERNAL, f"계약에 없는 action: {action!r}")
    body = dict(fields or {})
    collided = sorted(set(body) & {"version", "action"})
    if collided:
        raise SelftestApiError(CODE_INTERNAL, f"봉투 뼈대를 덮어쓸 수 없다: {collided}")
    return {"version": VERSION, "action": action, **body}


def _expression(method: str, argument: str = "") -> str:
    """``window.__hwpxTest`` 만을 뿌리로 하는 **호출** 표현식. 부재는 예외가 아니라 ``null`` 이다."""
    if method not in _METHODS:
        raise SelftestApiError(CODE_INTERNAL, f"허용되지 않은 파사드 메서드: {method!r}")
    return f"{ROOT} ? {ROOT}.{method}({argument}) : null"


def run_expression(action: str, fields: "Mapping[str, object] | None" = None) -> str:
    """봉투 하나를 실어 보내는 표현식."""
    return _expression("run", _encode(request_envelope(action, fields)))


def readiness_expression() -> str:
    """준비 확인 — **호출이 아니라 읽기**다.

    설치돼 있으면 ``1``, 없으면 ``null`` 이 온다. 호출로 물으면 파사드가 반쯤 선 상태(전역은
    있는데 ``run`` 이 없는)에서 예외가 나 "없다"와 "고장났다"가 같은 실패로 뭉개진다.
    """
    return f"{ROOT} ? {ROOT}.{READINESS_MEMBER} : null"


def start_fields(
    mode: str,
    *,
    probe_input: object = None,
    flags: "Mapping[str, object] | None" = None,
) -> dict:
    """개시 봉투의 필드 — ``mode`` 는 필수, ``input``·``flags`` 는 **없으면 키째 빠진다**.

    빈 값을 지어내 실으면 러너가 "호스트가 입력을 줬는데 비었다"와 "호스트가 입력을 안 줬다"를
    구별하지 못한다. 그래서 ``None`` 은 값이 아니라 **부재**로 옮긴다.
    """
    if not isinstance(mode, str) or not mode:
        raise SelftestApiError(CODE_INTERNAL, f"mode 는 비어 있지 않은 문자열이어야 한다: {mode!r}")
    fields: dict = {"mode": mode}
    if probe_input is not None:
        fields["input"] = probe_input
    if flags is not None:
        fields["flags"] = dict(flags)
    return fields


def poll_fields(run_id: str) -> dict:
    """폴 봉투의 필드 — 와이어 키는 camelCase ``runId`` 다."""
    if not isinstance(run_id, str) or not run_id:
        raise SelftestApiError(
            CODE_INTERNAL, f"{KEY_RUN_ID} 는 비어 있지 않은 문자열이어야 한다: {run_id!r}"
        )
    return {KEY_RUN_ID: run_id}


def start_expression(
    mode: str,
    *,
    probe_input: object = None,
    flags: "Mapping[str, object] | None" = None,
) -> str:
    """실행 개시 표현식. ``mode`` 는 드라이버가 환경에서 정한 값이다(프런트가 고르지 않는다)."""
    return run_expression(ACTION_START, start_fields(mode, probe_input=probe_input, flags=flags))


def poll_expression(run_id: str) -> str:
    """진행 확인 표현식 — ``evaluate_js`` 는 Promise 를 기다리지 않으므로 **폴링이 구조**다.

    정착을 처음 본 폴이 종단 결과까지 함께 받는다(별도 회수 단계 없음).
    """
    return run_expression(ACTION_POLL, poll_fields(run_id))


# ------------------------------------------------------------ 호스트 연산 결과


@dataclass(frozen=True)
class HostOpResult:
    """호스트 연산 한 번의 판정 — **던지지 않는 형태**. 거절도 값이다."""

    op: str
    ok: bool
    code: str
    detail: str
    value: object = None

    def to_payload(self) -> dict:
        """웹으로 돌려보낼 JSON-safe 형태. 성공이든 거절이든 **같은 모양**이다."""
        return {
            "ok": self.ok,
            "op": self.op,
            "code": self.code,
            "detail": self.detail,
            "value": self.value,
        }


def _ok(op: str, value: object = None) -> HostOpResult:
    return HostOpResult(op, True, CODE_OK, "", value)


def _refuse(op: str, code: str, detail: str) -> HostOpResult:
    return HostOpResult(op, False, code, detail)


# ------------------------------------------------------------ payload 검증기


def _as_mapping(payload: object) -> "Mapping[str, object] | None":
    """``None`` 은 빈 payload 로 본다(러너의 ``hostPayload`` 기본값). 그 밖은 매핑이어야 한다."""
    if payload is None:
        return {}
    if isinstance(payload, Mapping):
        return payload
    return None


def _int_field(payload: "Mapping[str, object]", key: str) -> "int | None":
    """정수 필드 판독 — ``bool`` 은 정수가 아니고, 소수부 있는 float 도 아니다."""
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if int(value) != value:
        return None
    return int(value)


def _str_field(payload: "Mapping[str, object]", key: str) -> "str | None":
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _integer_version(value: object) -> "int | None":
    """정수값 버전만 판독 — 브리지가 ``1.0`` 으로 실어 올 수 있고 ``True`` 는 1 이 아니다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if int(value) != value:
        return None
    return int(value)


# ------------------------------------------------------------ 호스트 연산 창구


class HostOperations:
    """**엄격 화이트리스트** 호스트 연산 디스패처.

    일반 ``eval`` 도, 무검증 invoke 도 없다. 이름은 :data:`HOST_OPS` 안에서만 통과하고, payload
    는 **연산별로** 모양·타입까지 본다. 미등록 이름은 예외가 아니라 **구조화된 거절**이다 —
    웹으로 예외가 새면 pywebview 가 그것을 rejection 으로 바꿔 사유가 문자열로 뭉개진다.

    네이티브 자원은 전부 주입이다(:mod:`webview` 를 import 하지 않는다). 주입되지 않은 연산은
    ``성공한 척``하지 않고 :data:`CODE_UNAVAILABLE` 로 **무엇이 없는지 이름을 대며** 거절하며,
    애초에 :meth:`provides` 에서 빠져 러너의 계획 단계가 붉어진다.
    """

    def __init__(
        self,
        *,
        resize: "Callable[[int, int], object] | None" = None,
        geometry: "Callable[[], object] | None" = None,
        current_url: "Callable[[], object] | None" = None,
        artifact_identity: "Callable[[], object] | None" = None,
        settings_source: "object | None" = None,
        inputs: "Mapping[str, object] | None" = None,
        mode: "str | None" = None,
        write_output: "Callable[[Mapping[str, object]], object] | None" = None,
        destroy: "Callable[[], object] | None" = None,
        deadline: "ProcessDeadline | None" = None,
    ) -> None:
        self._resize = resize
        self._geometry = geometry
        self._current_url = current_url
        self._artifact_identity = artifact_identity
        self._settings = settings_source
        self._inputs = dict(inputs or {})
        self._mode = mode
        self._write_output = write_output
        self._destroy = destroy
        self._deadline = deadline
        self._destroyed = False
        self._written: "list[object]" = []

    # ---------------------------------------------------------------- 표

    #: op 이름 → 처리 메서드 이름. **이 표 밖의 이름은 부를 수 없다** — ``getattr`` 의 인자가
    #: 사용자 입력이 아니라 이 리터럴이라는 것이 화이트리스트의 실질이다.
    _HANDLERS: "dict[str, str]" = {
        "mode_select": "_op_mode_select",
        "input_select": "_op_input_select",
        "global_deadline": "_op_global_deadline",
        "window_resize": "_op_window_resize",
        "window_geometry": "_op_window_geometry",
        "current_url": "_op_current_url",
        "artifact_identity": "_op_artifact_identity",
        "settings_readback": "_op_settings_readback",
        "output_write": "_op_output_write",
        "window_destroy": "_op_window_destroy",
        "packaged_process": "_op_packaged_process",
    }

    @classmethod
    def registered_ops(cls) -> "tuple[str, ...]":
        """실제로 부를 수 있는 이름 — 선언(:data:`HOST_OPS`)과 대조하라고 내놓는다."""
        return tuple(name for name in HOST_OPS if name in cls._HANDLERS)

    def provides(self) -> "tuple[str, ...]":
        """이 호스트가 **오늘 실제로 댈 수 있는** op — 주입이 없으면 이름이 빠진다.

        러너의 ``host.provides`` 로 그대로 넘어간다. 없는 것을 있다고 말하면 프로브가 계획
        단계에서 초록이었다가 실행에서 죽는다(선언은 살고 결과는 죽는 그 결함류).
        :data:`UNPROVIDABLE_OPS` 는 주입과 무관하게 빠진다 — 이 프로세스의 일이 아니다.
        """
        return tuple(
            name
            for name in self.registered_ops()
            if name not in UNPROVIDABLE_OPS and self._backing_missing(name) is None
        )

    def _backing_missing(self, op: str) -> "str | None":
        """이 op 를 대는 주입이 없으면 **무엇이 없는지** 이름을 돌려준다."""
        backing: "dict[str, object | None]" = {
            "mode_select": self._mode,
            "input_select": self._inputs or None,
            "global_deadline": self._deadline,
            "window_resize": self._resize,
            "window_geometry": self._geometry,
            "current_url": self._current_url,
            "artifact_identity": self._artifact_identity,
            "settings_readback": self._settings,
            "output_write": self._write_output,
            "window_destroy": self._destroy,
            # packaged_process 는 이 프로세스 밖의 일이라 주입 자체가 없다 — 부재가 정상이고,
            # 호출되면 처리기가 out-of-process 로 거절한다(unavailable 과 다른 사건이다).
            "packaged_process": True,
        }
        names = {
            "mode_select": "mode",
            "input_select": "inputs",
            "global_deadline": "deadline",
            "window_resize": "resize",
            "window_geometry": "geometry",
            "current_url": "current_url",
            "artifact_identity": "artifact_identity",
            "settings_readback": "settings_source",
            "output_write": "write_output",
            "window_destroy": "destroy",
            "packaged_process": "",
        }
        return None if backing.get(op) is not None else names[op]

    # ------------------------------------------------------------ 디스패치

    def dispatch(self, op: object, payload: object = None) -> HostOpResult:
        """이름·payload 를 **둘 다** 검증하고 처리기를 부른다. 예외를 밖으로 내지 않는다."""
        if not isinstance(op, str) or op not in self._HANDLERS:
            return _refuse(
                str(op),
                CODE_UNKNOWN_OP,
                f"허용 목록에 없는 호스트 연산: {op!r} (허용 {list(self.registered_ops())})",
            )
        body = _as_mapping(payload)
        if body is None:
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"payload 가 객체가 아니다: {payload!r}")
        missing = self._backing_missing(op)
        if missing:
            return _refuse(
                op, CODE_UNAVAILABLE, f"이 호스트는 {op} 를 대지 못한다(주입 없음: {missing})"
            )
        handler = getattr(self, self._HANDLERS[op])
        try:
            return handler(op, body)
        except SelftestApiError as exc:  # 조립 단계 거절 — 코드 보존
            return _refuse(op, exc.code, exc.detail)
        except Exception as exc:  # noqa: BLE001 — 네이티브가 죽었을 수 있다. 삼키지 말고 재진술.
            return _refuse(op, CODE_INTERNAL, f"{op} 수행 중 예외: {exc!r}")

    # ------------------------------------------------------------ 개별 연산

    def _op_mode_select(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        if payload:
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"{op} 은 payload 를 받지 않는다: {dict(payload)!r}")
        return _ok(op, {"mode": self._mode})

    def _op_input_select(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        name = _str_field(payload, "name")
        if name is None:
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"{op} 은 name(비어 있지 않은 문자열)이 필요하다")
        if name not in self._inputs:
            return _refuse(
                op, CODE_UNKNOWN_INPUT, f"모르는 입력 이름: {name!r} (있는 것 {sorted(self._inputs)})"
            )
        return _ok(op, {"name": name, "value": self._inputs[name]})

    def _op_global_deadline(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        if payload:
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"{op} 은 payload 를 받지 않는다: {dict(payload)!r}")
        assert self._deadline is not None  # _backing_missing 이 앞에서 걸렀다
        return _ok(op, self._deadline.snapshot())

    def _op_window_resize(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        width, height = _int_field(payload, "width"), _int_field(payload, "height")
        if width is None or height is None:
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"{op} 은 정수 width·height 가 필요하다: {dict(payload)!r}")
        if not (RESIZE_MIN <= width <= RESIZE_MAX and RESIZE_MIN <= height <= RESIZE_MAX):
            return _refuse(
                op,
                CODE_MALFORMED_PAYLOAD,
                f"창 크기 범위 밖: {width}×{height} (허용 {RESIZE_MIN}~{RESIZE_MAX})",
            )
        assert self._resize is not None
        self._resize(width, height)
        return _ok(op, {"width": width, "height": height})

    def _op_window_geometry(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        if payload:
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"{op} 은 payload 를 받지 않는다: {dict(payload)!r}")
        assert self._geometry is not None
        raw = self._geometry()
        if not isinstance(raw, Mapping):
            return _refuse(op, CODE_MALFORMED_RESULT, f"기하 측정이 객체가 아니다: {raw!r}")
        measured: "dict[str, int]" = {}
        for name in GEOMETRY_FIELDS:
            value = _int_field(raw, name)
            if value is None:
                return _refuse(op, CODE_MALFORMED_RESULT, f"기하 필드 {name} 가 정수가 아니다: {raw!r}")
            measured[name] = value
        # 판정은 **호스트가** 진다(app.py 의 수치 그대로) — 프런트가 다시 조립하면 두 곳이
        # 같은 상태를 판정하게 된다.
        measured["maximized_like"] = bool(
            measured["x"] <= measured["avail_x"] + GEOMETRY_EDGE_SLACK
            and measured["y"] <= measured["avail_y"] + GEOMETRY_EDGE_SLACK
            and measured["x"] + measured["width"]
            >= measured["avail_x"] + measured["avail_width"] - GEOMETRY_SPAN_SLACK
            and measured["y"] + measured["height"]
            >= measured["avail_y"] + measured["avail_height"] - GEOMETRY_SPAN_SLACK
        )
        return _ok(op, measured)

    def _op_current_url(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        if payload:
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"{op} 은 payload 를 받지 않는다: {dict(payload)!r}")
        assert self._current_url is not None
        url = self._current_url()
        if not isinstance(url, str) or not url:
            return _refuse(op, CODE_MALFORMED_RESULT, f"현재 URL 이 문자열이 아니다: {url!r}")
        return _ok(op, {"url": url})

    def _op_artifact_identity(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        if payload:
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"{op} 은 payload 를 받지 않는다: {dict(payload)!r}")
        assert self._artifact_identity is not None
        raw = self._artifact_identity()
        if not isinstance(raw, Mapping):
            return _refuse(op, CODE_MALFORMED_RESULT, f"산출물 정체가 객체가 아니다: {raw!r}")
        identity: "dict[str, str]" = {}
        for name in ("artifact_id", "tree_sha256"):
            value = _str_field(raw, name)
            if value is None:
                return _refuse(op, CODE_MALFORMED_RESULT, f"산출물 정체에 {name} 가 없다: {raw!r}")
            identity[name] = value
        return _ok(op, identity)

    def _op_settings_readback(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        key = _str_field(payload, "key")
        if key is None:
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"{op} 은 key(문자열)가 필요하다: {dict(payload)!r}")
        if key not in SETTINGS_READBACK_KEYS:
            return _refuse(
                op,
                CODE_UNKNOWN_OP,
                f"되읽을 수 없는 설정 키: {key!r} (허용 {sorted(SETTINGS_READBACK_KEYS)})",
            )
        reader = getattr(self._settings, SETTINGS_READBACK_KEYS[key], None)
        if not callable(reader):
            return _refuse(
                op, CODE_UNAVAILABLE, f"설정 판독기 {SETTINGS_READBACK_KEYS[key]} 가 없다"
            )
        return _ok(op, {"key": key, "value": reader()})

    def _op_output_write(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        result = payload.get("result")
        if not isinstance(result, Mapping):
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"{op} 은 result(객체)가 필요하다: {dict(payload)!r}")
        assert self._write_output is not None
        written = self._write_output(dict(result))
        self._written.append(written)
        return _ok(op, {"path": str(written)})

    def _op_window_destroy(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        if payload:
            return _refuse(op, CODE_MALFORMED_PAYLOAD, f"{op} 은 payload 를 받지 않는다: {dict(payload)!r}")
        if self._destroyed:
            # 두 번째 종료는 조용한 no-op 이 아니다 — 누가 두 번 불렀는지가 진단이다.
            return _refuse(op, CODE_ALREADY_CONSUMED, "창은 이미 정식 종료됐다(두 번째 요청)")
        assert self._destroy is not None
        self._destroy()
        self._destroyed = True
        return _ok(op, {"destroyed": True})

    def _op_packaged_process(self, op: str, payload: "Mapping[str, object]") -> HostOpResult:
        # 분류 (다) — 이 프로세스가 할 수 없는 일이다. 조용히 넘기지 않고 사유를 재진술한다.
        return _refuse(
            op,
            CODE_OUT_OF_PROCESS,
            "동결 exe 프로세스 조율은 packaging/build.ps1 이 이 프로세스 밖에서 한다",
        )

    # ------------------------------------------------------------ 되읽기

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    @property
    def written(self) -> "tuple[object, ...]":
        return tuple(self._written)


# ------------------------------------------------------------------ 파사드


class SelftestHostFacade:
    """``js_api`` 에 **조건부로** 얹히는 테스트 파사드.

    pywebview 는 ``js_api`` 객체의 공개 메서드를 ``dir()`` 로 자동 반영한다. 그래서 이 파사드를
    ``WebFrontend`` 에 상시로 두면 **정상 부팅에서도** 페이지가 호스트 연산을 부를 수 있다.
    부착은 :func:`attach_selftest_facade` 가 ``--selftest`` 때만 한다(반영은 ``_pywebviewready``
    시점이라 페이지 로드 전이면 언제든 늦지 않다).

    공개 메서드는 둘뿐이고, 이름과 인자 모양은 ``frontend/js/bridge.js`` 가 정한다:

    - :meth:`selftest_claim` ``(version)`` — 선착순 1회 악수. 토큰과 provides 를 돌려준다.
    - :meth:`selftest_host_op` ``(op, payload)`` — 호스트 연산 요청.

    두 메서드 모두 **예외를 밖으로 내지 않는다**. 파이썬 예외가 pywebview 브리지를 건너면
    사유가 문자열로 뭉개져 "거절"과 "고장"이 구별되지 않는다.
    """

    def __init__(
        self,
        operations: HostOperations,
        *,
        token: "str | None" = None,
        log: "Callable[[str], None] | None" = None,
    ) -> None:
        self._operations = operations
        # 토큰은 이 속성에만 산다. 밑줄 접두라 pywebview 반영에도 걸리지 않고, 기본 ``repr`` 도
        # 값을 보이지 않는다(:func:`token_leaks` 가 그것을 센다).
        self._token = token if token is not None else mint_token()
        self._log = log
        self._claimed = False
        self._claims = 0
        self._refusals = 0

    # ---------------------------------------------------------------- 보조

    def _note(self, what: str, code: str, detail: str) -> None:
        """거절을 **코드와 함께** 남긴다. 토큰은 인자로 오지 않으므로 실릴 수 없다."""
        self._refusals += 1
        if self._log is not None:
            self._log(f"selftest {what} 거절 [{code}] {detail}")

    def _reject(self, what: str, code: str, detail: str) -> dict:
        self._note(what, code, detail)
        return {"ok": False, "code": code, "detail": detail}

    def _authorized(self, candidate: object) -> bool:
        """상수 시간 비교 — 토큰 비교로 타이밍 단서를 흘리지 않는다.

        ``compare_digest`` 는 비-ASCII 문자열을 **거부한다**(TypeError). 우리 토큰은 언제나
        URL-safe base64 라 ASCII 이므로, 비-ASCII 후보는 비교할 것도 없이 틀린 토큰이다 —
        예외로 새어 나가 :data:`CODE_INTERNAL` 로 뭉개지지 않게 여기서 먼저 가른다.
        """
        if not isinstance(candidate, str) or not candidate.isascii():
            return False
        return secrets.compare_digest(candidate, self._token)

    # ---------------------------------------------------------------- 악수

    def selftest_claim(self, version: object = None, token: object = None) -> dict:
        """능력 토큰 악수 — **선착순 1회**. ``version`` 은 스칼라 ``1`` 이다(dict 아님).

        성공하면 ``{ok, version, token, provides}``. ``provides`` 는 이 호스트가 **실제로 댈 수
        있는** op 목록이라 러너가 계획 단계에서 붉어질 수 있다.

        실패는 전부 **다른 코드**다: 지원하지 않는 버전(:data:`CODE_VERSION_UNSUPPORTED`, 악수를
        **태우지 않는다**) · 틀린 토큰(:data:`CODE_UNAUTHORIZED`, 역시 태우지 않는다) ·
        두 번째 악수(:data:`CODE_ALREADY_CLAIMED`).

        ``token`` 은 오늘의 브리지가 넘기지 않는 **선택적 사전 공유 경로**다 — 넘어오면 맞아야 한다.
        """
        try:
            if _integer_version(version) != VERSION:
                return self._reject(
                    "claim",
                    CODE_VERSION_UNSUPPORTED,
                    f"지원하지 않는 version: {version!r} (이 호스트는 {VERSION})",
                )
            if token is not None and not self._authorized(token):
                return self._reject("claim", CODE_UNAUTHORIZED, "제시한 토큰이 이 호스트의 것이 아니다")
            if self._claimed:
                return self._reject(
                    "claim", CODE_ALREADY_CLAIMED, "이 프로세스의 악수는 이미 끝났다(1회 한정)"
                )
            self._claimed = True
            self._claims += 1
            return {
                "ok": True,
                "version": VERSION,
                "token": self._token,
                "provides": list(self._operations.provides()),
            }
        except Exception as exc:  # noqa: BLE001 — 브리지를 건너는 예외 금지
            return self._reject("claim", CODE_INTERNAL, f"악수 중 예외: {exc!r}")

    def claim_state(self) -> dict:
        """악수 회계 — **토큰은 없다**. 드라이버가 "정확히 한 번이었나"를 되읽는 창구다."""
        return {"claimed": self._claimed, "claims": self._claims, "refusals": self._refusals}

    # ------------------------------------------------------------ 호스트 요청

    def selftest_host_op(
        self, op: object = None, payload: object = None, token: object = None
    ) -> dict:
        """호스트 연산 요청 — ``(op, payload)``. 오늘의 브리지는 두 인자만 넘긴다.

        능력 관문은 **악수가 있었는가**이고(:data:`CODE_NOT_CLAIMED`), ``token`` 이 실려 오면
        그때 검증한다(:data:`CODE_UNAUTHORIZED`). 그 아래 :class:`HostOperations` 가 이름·payload
        를 연산별로 다시 본다 — 여기는 **능력** 관문이고 아래는 **모양** 관문이다.
        """
        try:
            if token is not None and not self._authorized(token):
                return self._reject("host_op", CODE_UNAUTHORIZED, "호스트 연산의 토큰이 맞지 않는다")
            if not self._claimed:
                return self._reject(
                    "host_op", CODE_NOT_CLAIMED, "악수 전에는 호스트 연산을 받지 않는다"
                )
            result = self._operations.dispatch(op, payload)
            if not result.ok:
                self._note("host_op", result.code, result.detail)
            return result.to_payload()
        except Exception as exc:  # noqa: BLE001 — 브리지를 건너는 예외 금지
            return self._reject("host_op", CODE_INTERNAL, f"호스트 연산 중 예외: {exc!r}")


# ------------------------------------------------------------ 부착·해제

#: ``js_api`` 에 심는 이름 → 파사드 메서드. **정상 부팅에는 이 이름들이 없다.**
#: 이름은 ``frontend/js/bridge.js`` 가 부르는 것 그대로다.
FACADE_METHODS: "tuple[tuple[str, str], ...]" = (
    ("selftest_claim", "selftest_claim"),
    ("selftest_host_op", "selftest_host_op"),
)

#: 심는 속성 이름만.
FACADE_ATTRIBUTES: "tuple[str, ...]" = tuple(name for name, _ in FACADE_METHODS)


def attach_selftest_facade(target: object, facade: SelftestHostFacade) -> "tuple[str, ...]":
    """파사드 메서드를 ``js_api`` 객체에 심는다 — ``--selftest`` 부팅에서만.

    바인드된 메서드를 **인스턴스 속성**으로 심는다: pywebview 의 ``get_functions`` 는 ``dir()``
    를 돌며 ``inspect.ismethod`` 를 보고, 바인드 메서드는 둘 다 만족한다(``get_args(attr)[1:]``
    가 ``self`` 를 떼므로 JS 쪽 인자도 맞는다). 반영 시점은 ``_pywebviewready`` 라 페이지 로드
    전이면 부착이 늦지 않다.

    이미 같은 이름이 점유돼 있으면 덮어쓰지 않고 시끄럽게 실패한다(조용한 교체 = 어느 파사드가
    실렸는지 모르는 상태). 검사는 **심기 전에 전부** 돌아 부분 부착을 남기지 않는다.
    """
    if not isinstance(facade, SelftestHostFacade):
        raise SelftestApiError(CODE_INTERNAL, f"파사드가 아니다: {facade!r}")
    for attribute in FACADE_ATTRIBUTES:
        if hasattr(target, attribute):
            raise SelftestApiError(CODE_INTERNAL, f"이미 점유된 js_api 이름: {attribute}")
    for attribute, method in FACADE_METHODS:
        setattr(target, attribute, getattr(facade, method))
    return FACADE_ATTRIBUTES


def detach_selftest_facade(target: object) -> "tuple[str, ...]":
    """심었던 이름을 걷는다. 걷힌 이름을 돌려준다(없던 것은 조용히 지나간다 — 해제는 멱등)."""
    removed: "list[str]" = []
    for attribute in FACADE_ATTRIBUTES:
        if hasattr(target, attribute):
            delattr(target, attribute)
            removed.append(attribute)
    return tuple(removed)


def facade_attached(target: object) -> bool:
    """``js_api`` 표면에 테스트 메서드가 **하나라도** 있는가."""
    return any(hasattr(target, attribute) for attribute in FACADE_ATTRIBUTES)


# ------------------------------------------------------------------ 판정


@dataclass(frozen=True)
class PollOutcome:
    """폴 한 번의 판정 — 아직 도는가 · 끝났는가 · 계약을 깼는가.

    ``code`` 가 :data:`CODE_RUN_FAILED` 일 때도 ``evidence`` 는 **살아 있다**. 실패한 실행은
    "결과가 없다"가 아니라 "결과가 있고 그 안에 ``error`` 가 서 있다"이고, 실앱 게이트가 읽는
    것이 바로 그 ``error`` 다. 여기서 증거를 버리면 게이트는 "파일이 없다"는 **엉뚱한 사유**를
    보고한다 — 실패는 같아도 진단이 거짓말이 된다.
    """

    run_id: str
    ok: bool
    code: str
    detail: str
    state: str = ""
    evidence: "dict | None" = None
    result: "dict | None" = None

    @property
    def running(self) -> bool:
        return self.ok and self.state == STATE_RUNNING

    @property
    def succeeded(self) -> bool:
        return self.ok and self.state == STATE_SUCCEEDED

    @property
    def failed(self) -> bool:
        return self.code == CODE_RUN_FAILED

    @property
    def terminal(self) -> bool:
        """이 폴이 **회수**였나 — 성공 정착이든 실패 정착이든 결과를 들고 왔다."""
        return self.succeeded or self.failed


@dataclass(frozen=True)
class SelftestOutcome:
    """구동 한 번의 최종 판정. **토큰을 담지 않는다** — 이 객체는 로그·파일로 나간다."""

    mode: str
    ok: bool
    code: str
    detail: str
    run_id: str = ""
    evidence: "dict | None" = None
    result: "dict | None" = None
    elapsed_ms: int = 0

    @property
    def facade_absent(self) -> bool:
        return self.code == CODE_FACADE_ABSENT

    @property
    def has_evidence(self) -> bool:
        """쓸 증거가 있는가 — 실패한 실행도 증거를 낸다(그 안의 ``error`` 가 게이트를 붉힌다)."""
        return self.evidence is not None

    @property
    def alarm_text(self) -> str:
        """경보 문안 — 드라이버가 그대로 증거의 ``error`` 로 쓴다."""
        return f"자가검증 {self.mode} 실패 [{self.code}] {self.detail}"

    def raise_for_failure(self) -> "SelftestOutcome":
        """실패면 타입 있는 예외로 승격. 성공이면 자기 자신을 돌려준다(체이닝용)."""
        if self.ok:
            return self
        if self.code == CODE_FACADE_ABSENT:
            raise FacadeAbsentError(self.code, self.detail, action=self.mode)
        if self.code == CODE_EVALUATE_FAILED:
            raise TransportError(self.code, self.detail, action=self.mode)
        if self.code in (CODE_VERSION_UNSUPPORTED, CODE_MALFORMED_RESULT):
            raise ProtocolError(self.code, self.detail, action=self.mode)
        raise RefusedError(self.code, self.detail, action=self.mode)


def parse_readiness(raw: object) -> int:
    """준비 확인 반환 판정 — ``window.__hwpxTest.version`` 을 읽은 값.

    ``None`` 은 **파사드 부재**(번들 미주입)이고, 정수 1 이 아닌 값은 전부
    :data:`CODE_VERSION_UNSUPPORTED` 다 — 미지 버전을 v1 로 강등해 절반만 도는 경로는 없다.
    """
    if raw is None:
        raise FacadeAbsentError(CODE_FACADE_ABSENT, f"{ROOT} 부재(version 읽기=None)")
    parsed = _integer_version(raw)
    if parsed is None:
        raise ProtocolError(CODE_VERSION_UNSUPPORTED, f"version 이 정수가 아니다: {raw!r}")
    if parsed != VERSION:
        raise ProtocolError(
            CODE_VERSION_UNSUPPORTED, f"지원하지 않는 version: {raw!r} (이 어댑터는 {VERSION})"
        )
    return VERSION


def _mapping_field(raw: "Mapping[str, object]", key: str) -> "dict | None":
    value = raw.get(key)
    return dict(value) if isinstance(value, Mapping) else None


def classify_start(raw: object) -> "tuple[str, str, str]":
    """``start`` 반환 → ``(run_id, code, detail)``. 성공이면 ``code`` 는 :data:`CODE_OK`."""
    if raw is None:
        return "", CODE_FACADE_ABSENT, f"{ROOT} 부재(start 반환=None)"
    if not isinstance(raw, Mapping):
        return "", CODE_MALFORMED_RESULT, f"start 반환이 객체가 아니다: {raw!r}"
    ok = raw.get("ok")
    if not isinstance(ok, bool):
        return "", CODE_MALFORMED_RESULT, f"start 결과에 참/거짓 ok 가 없다: {dict(raw)!r}"
    if not ok:
        return "", python_code(raw.get("code")), f"파사드가 개시를 거절했다: {dict(raw)!r}"
    run_id = _str_field(raw, KEY_RUN_ID)
    if run_id is None:
        return "", CODE_MALFORMED_RESULT, f"start 결과에 {KEY_RUN_ID} 가 없다: {dict(raw)!r}"
    return run_id, CODE_OK, ""


def classify_poll(run_id: str, raw: object) -> PollOutcome:
    """``poll`` 반환 판정. 모르는 상태를 "아직 도는 중"으로 접지 않는다.

    실패 정착(``ok:false, code:"run_failed"``)은 **통로 고장이 아니다** — 실행이 실패했고 증거는
    있다. 그 둘을 같은 실패로 접으면 출력이 사라지고 게이트가 원인을 잘못 짚는다.
    """
    if raw is None:
        return PollOutcome(run_id, False, CODE_FACADE_ABSENT, f"{ROOT} 부재(poll 반환=None)")
    if not isinstance(raw, Mapping):
        return PollOutcome(run_id, False, CODE_MALFORMED_RESULT, f"poll 반환이 객체가 아니다: {raw!r}")
    ok = raw.get("ok")
    if not isinstance(ok, bool):
        return PollOutcome(
            run_id, False, CODE_MALFORMED_RESULT, f"poll 결과에 참/거짓 ok 가 없다: {dict(raw)!r}"
        )
    if ok:
        return _classify_settled_ok(run_id, raw)

    code = python_code(raw.get("code"))
    if code != CODE_RUN_FAILED:
        return PollOutcome(
            run_id, False, code, f"파사드가 폴을 거절했다: {dict(raw)!r}", "", None, dict(raw)
        )
    # 실패 정착 — 증거는 반드시 살린다.
    evidence = _mapping_field(raw, "evidence")
    errors = raw.get("errors")
    count = len(errors) if isinstance(errors, (list, tuple)) else 0
    detail = f"프로브 실패 {count}건"
    if evidence is None:
        # 증거 없는 실패는 **두 번째 결함**이다. 실패를 삼키지 않고 그 사실까지 재진술한다.
        detail += " (evidence 객체가 없다 — 파사드 계약 위반)"
    return PollOutcome(run_id, False, CODE_RUN_FAILED, detail, STATE_FAILED, evidence, dict(raw))


def _classify_settled_ok(run_id: str, raw: "Mapping[str, object]") -> PollOutcome:
    """``ok: true`` 폴의 상태 판정 — 진행 중이거나 성공 정착 둘뿐이다."""
    state = raw.get("state")
    if state == STATE_RUNNING:
        return PollOutcome(run_id, True, CODE_OK, "", STATE_RUNNING, None, dict(raw))
    if state != STATE_SUCCEEDED:
        return PollOutcome(
            run_id,
            False,
            CODE_MALFORMED_RESULT,
            f"ok:true 가 낼 수 없는 상태: {state!r} (허용 {[STATE_RUNNING, STATE_SUCCEEDED]})",
        )
    evidence = _mapping_field(raw, "evidence")
    if evidence is None:
        return PollOutcome(
            run_id, False, CODE_MALFORMED_RESULT, f"성공 정착에 evidence 객체가 없다: {dict(raw)!r}"
        )
    return PollOutcome(run_id, True, CODE_OK, "", STATE_SUCCEEDED, evidence, dict(raw))


# ------------------------------------------------------------------ 드라이버


class SelftestClient:
    """창(평가기)에 묶인 얇은 드라이버. 표현식 조립 · 폴링 · 판정을 한 자리에서 진다.

    평가기는 주입이다 — pywebview 를 모르므로 헤드리스 단위 검증이 된다. 시계·수면도 주입이라
    테스트가 실시간을 쓰지 않는다.

    **``evaluate_js`` 는 Promise 를 기다리지 않는다**(오늘 app.py 주석이 여러 번 적어 둔 성질).
    그래서 개시는 즉시 돌아오고 완주는 폴링으로 확정한다. 폴링 만료는 **경보**이지 통과가
    아니다 — 낡은 부분 결과를 성공으로 접는 경로가 여기서 끊긴다.
    """

    def __init__(
        self,
        evaluate: "Callable[[str], object]",
        *,
        budget_s: float = 90.0,
        poll_interval_s: float = 0.1,
        now: "Callable[[], float]" = time.monotonic,
        sleep: "Callable[[float], None]" = time.sleep,
        log: "Callable[[str], None] | None" = None,
    ) -> None:
        self._evaluate = evaluate
        self._budget_s = budget_s
        self._poll_interval_s = poll_interval_s
        self._now = now
        self._sleep = sleep
        self._log = log
        self._consumed: "set[str]" = set()

    @classmethod
    def for_window(cls, window: object, **kwargs) -> "SelftestClient":
        """pywebview 창을 감싼다 — 이 모듈이 창을 아는 유일한 접점(덕 타이핑)."""
        return cls(lambda expr: window.evaluate_js(expr), **kwargs)  # type: ignore[attr-defined]

    def new_deadline(self) -> ProcessDeadline:
        """이 드라이버의 예산으로 :class:`ProcessDeadline` 을 만든다(``global_deadline`` 주입용)."""
        return ProcessDeadline(self._budget_s, self._now)

    # ---------------------------------------------------------------- 평가

    def _eval(self, expression: str, action: "str | None") -> object:
        try:
            return self._evaluate(expression)
        except SelftestApiError:
            raise
        except Exception as exc:  # noqa: BLE001 — 창이 죽었을 수 있다
            where = action or "readiness"
            raise TransportError(
                CODE_EVALUATE_FAILED, f"{where} 평가 실패: {exc!r}", action=action
            ) from exc

    def _note(self, message: str) -> None:
        if self._log is not None:
            self._log(message)

    # ---------------------------------------------------------------- 단계

    def readiness(self) -> int:
        """준비 확인 — 파사드가 서 있고 버전이 맞는가. 실패는 전부 예외다(하강 없음)."""
        return parse_readiness(self._eval(readiness_expression(), None))

    def await_readiness(self, deadline: ProcessDeadline) -> int:
        """파사드가 **설 때까지** 기다린다 — 설치는 비동기다.

        프런트의 능력 설치는 호스트 왕복(``selftest_claim``)을 한 번 거치고, 그 왕복은
        페이지가 부트스트랩을 마친 뒤에야 일어난다. 그래서 **한 번만 물으면** 아직 부팅
        중인 창을 "파사드 부재"로 확정한다 — 첫 실엔진 대면에서 실제로 그렇게 났다.

        레거시는 이 자리를 고정 4.5초 ``sleep`` 으로 어림했다. 고정 대기는 두 방향으로
        틀린다: 느린 콜드부트에서는 모자라고 빠른 부팅에서는 그만큼 버린다. 여기서는
        **조건을** 폴링하되 시한을 프로세스 예산에 묶는다 — 새 시간 상수를 만들지 않는다.

        시한이 지나면 조용히 넘어가지 않고 마지막 판정을 그대로 올린다(confirm-or-alarm).
        버전 불일치처럼 **기다린다고 바뀌지 않는** 실패는 즉시 올린다.
        """
        last: "SelftestApiError | None" = None
        while True:
            try:
                return self.readiness()
            except SelftestApiError as exc:
                if exc.code != CODE_FACADE_ABSENT:
                    raise
                last = exc
            if deadline.expired():
                self._note(
                    f"selftest 파사드 준비 시한 초과({deadline.elapsed_s():.1f}s)"
                    " — 능력이 설치되지 않았다"
                )
                assert last is not None
                raise last
            self._sleep(self._poll_interval_s)

    def start(
        self,
        mode: str,
        *,
        probe_input: object = None,
        flags: "Mapping[str, object] | None" = None,
    ) -> str:
        """실행 개시 — ``runId`` 를 돌려준다. 거절·형태 위반은 예외다."""
        raw = self._eval(
            start_expression(mode, probe_input=probe_input, flags=flags), ACTION_START
        )
        run_id, code, detail = classify_start(raw)
        if code != CODE_OK:
            self._raise(code, detail, ACTION_START)
        return run_id

    def poll(self, run_id: str) -> PollOutcome:
        """진행 확인 겸 **1회 한정 회수** — 던지지 않는다.

        정착을 이미 회수한 실행을 다시 물으면 창까지 가지 않고 :data:`CODE_ALREADY_CONSUMED`
        로 거절한다. 파사드도 같은 거절을 하지만, 여기서 먼저 끊어야 "회수를 두 번 했는데 두 번
        다 뭔가 돌아왔다"는 상태가 아예 생기지 않는다.
        """
        if run_id in self._consumed:
            return PollOutcome(
                run_id, False, CODE_ALREADY_CONSUMED, f"{run_id} 결과는 이미 회수됐다"
            )
        try:
            raw = self._eval(poll_expression(run_id), ACTION_POLL)
        except SelftestApiError as exc:
            return PollOutcome(run_id, False, exc.code, exc.detail)
        outcome = classify_poll(run_id, raw)
        if outcome.terminal:
            self._consumed.add(run_id)
        return outcome

    def _raise(self, code: str, detail: str, action: str) -> None:
        if code == CODE_FACADE_ABSENT:
            raise FacadeAbsentError(code, detail, action=action)
        if code in (CODE_VERSION_UNSUPPORTED, CODE_MALFORMED_RESULT):
            raise ProtocolError(code, detail, action=action)
        raise RefusedError(code, detail, action=action)

    # ---------------------------------------------------------------- 구동

    def drive(
        self,
        mode: str,
        *,
        probe_input: object = None,
        flags: "Mapping[str, object] | None" = None,
    ) -> SelftestOutcome:
        """준비 → 개시 → 폴링(겸 회수)을 한 번에. **던지지 않고** 판정을 돌려준다.

        파이썬 예산은 JS 프로브 시한과 독립이다 — 렌더러가 통째로 멈춰도 이 루프는 끝난다.
        실패한 실행은 ``evidence`` 를 **들고** 돌아온다(드라이버가 그대로 출력에 쓴다).
        """
        deadline = self.new_deadline()
        try:
            # 한 번 묻지 않고 **선다는 것을 확인할 때까지** 기다린다 — 설치는 비동기다.
            self.await_readiness(deadline)
            run_id = self.start(mode, probe_input=probe_input, flags=flags)
        except SelftestApiError as exc:
            return self._outcome(mode, exc.code, exc.detail, deadline)

        while True:
            if deadline.expired():
                self._note(f"selftest {mode} 프로세스 예산 초과 — 부분 결과를 내지 않는다")
                return self._outcome(
                    mode,
                    CODE_DEADLINE_EXCEEDED,
                    f"프로세스 예산 {self._budget_s:.0f}s 초과 — 낡은 부분 결과를 내보내지 않는다",
                    deadline,
                    run_id,
                )
            state = self.poll(run_id)
            if state.terminal:
                return self._outcome(
                    mode, state.code, state.detail, deadline, run_id, state.evidence, state.result
                )
            if not state.ok:
                return self._outcome(
                    mode, state.code, state.detail, deadline, run_id, None, state.result
                )
            self._sleep(self._poll_interval_s)

    def _outcome(
        self,
        mode: str,
        code: str,
        detail: str,
        deadline: ProcessDeadline,
        run_id: str = "",
        evidence: "dict | None" = None,
        result: "dict | None" = None,
    ) -> SelftestOutcome:
        outcome = SelftestOutcome(
            mode=mode,
            ok=code == CODE_OK,
            code=code,
            detail=detail,
            run_id=run_id,
            evidence=evidence,
            result=result,
            elapsed_ms=round(deadline.elapsed_s() * 1000),
        )
        if not outcome.ok:
            self._note(outcome.alarm_text)
        return outcome
