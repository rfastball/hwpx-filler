"""실 WebView2 overlay host 게이트 — host 마커 되읽기 + 재초기화 (R3-01 · #410).

node 계약 테스트는 골격 렌더(실 서버 렌더)와 집행 계약까지를 재고, 「React host 가 실 창에서
골격 4 를 실제로 커밋하고 reload 뒤에도 신품으로 다시 선다」는 별개 사실이다 — 실 React
커밋·실 CSS 캐스케이드(`.modal.hidden{display:none}`)·실 문서 수명주기는 node 에 없다.
그래서 이 게이트가 실 창에서 되읽는 것은 넷이다:

- **host 커밋**: ``#reactOverlayHost`` 가 문서에 있고 ``#reactRoot`` 커밋 마커가 서 있다.
- **직속 자식 계약**: 골격 4(confirm·choose·prompt·토스트)가 host 컨테이너의 **직속**
  자식이다 — live 소유 술어(``overlay_children_owned``)가 참이 되는 바로 그 형상(개정 8).
- **닫힘 상태 상시 렌더**: 첫 open 전에 confirm 의 계산 display 가 ``none`` 이고 토스트가
  ``hidden`` 이다(개정 3-1 — 프로브의 선-판독 전제).
- **id 유일**: 골격 id 가 문서 전역에서 정확히 1회다 — index.html 재도입(정적 음성의
  런타임 절반)이 여기서도 붉는다.

그리고 **문서 재초기화(reload) 뒤 같은 넷을 다시** 잰다 — reload 는 ``bootProduct()`` 전체
재구성이라, host 마운트·다이얼로그 슬롯이 신품으로 다시 서는 것을 실물로 잰다(#410 §7 의
「창 재초기화 후 재개방」 축 — 상호작용 재개방 자체는 selftest 게이트의 ``modal_a11y`` 가
React 표면 위에서 무변경 초록으로 진다).

창 하니스(실 백엔드 두 줄·절대 storage_path·단일 판정 술어·마커 줄 프로토콜)는
``test_react_root_live.py``/``test_react_store_live.py`` 의 착수 실측을 그대로 승계한다.

**Windows/WebView2 전용.** 데스크톱 세션이 없는 러너는 ``HWPX_SKIP_GUI_TESTS=1`` 로 명시
옵트아웃한다 — 런타임 부재를 자동 감지해 조용히 스킵하지 않는다(confirm-or-alarm).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent

_GUI_GATE = sys.platform != "win32" or bool(os.environ.get("HWPX_SKIP_GUI_TESTS"))
_GATE_REASON = (
    "실앱 WebView2 게이트 — Windows 데스크톱 세션 전용(HWPX_SKIP_GUI_TESTS=1 로 옵트아웃)"
)

#: 창 안에서 되읽는 표현식 — host 컨테이너·커밋 마커·직속 자식·닫힘 상태·id 유일을
#: **한 번에** 싣는다. 낱개로 물으면 「host 째 사라짐」과 「자식 이탈」이 뭉개진다.
OVERLAY_READBACK_EXPRESSION = (
    "(function () {"
    " var ids = ['confirmModal', 'chooseModal', 'promptModal', 'undoToast'];"
    " var host = document.getElementById('reactOverlayHost');"
    " var root = document.getElementById('reactRoot');"
    " var cm = document.getElementById('confirmModal');"
    " var toast = document.getElementById('undoToast');"
    " return JSON.stringify({"
    "   host: host !== null,"
    "   mounted: root === null ? null : root.getAttribute('data-react-mounted'),"
    "   direct: host === null ? null : ids.every(function (id) {"
    "     var node = document.getElementById(id);"
    "     return node !== null && node.parentElement === host;"
    "   }),"
    "   closed: cm === null ? null : getComputedStyle(cm).display,"
    "   toast_hidden: toast === null ? null : toast.hidden === true,"
    "   unique: ids.every(function (id) {"
    "     return document.querySelectorAll('#' + id).length === 1;"
    "   }),"
    " });"
    "})()"
)

#: 자식이 단계별 되읽기를 실어 내보내는 줄의 접두 — 부모는 이 줄만 신뢰한다.
_READBACK_LINE_PREFIX = "HWPX-OVERLAY-READBACK="

#: 창 안 폴링 예산(2단계 합산)·자식 상한 — root/store live 게이트의 예산 산정을 승계한다.
_PROBE_BUDGET_S = 120.0
_CHILD_TIMEOUT_S = 240.0

#: 단계 이름 — 부팅 커밋 → 문서 재초기화(신품 마운트). 자식과 부모가 같은 순서를 공유한다.
PHASES = ("boot", "reloaded")


def judge_overlay_readback(raw: object) -> "tuple[bool, str]":
    """되읽기 원문 → (통과, 사유). host·커밋·직속 자식·닫힘·유일 형상 전부를 판정한다."""
    if not isinstance(raw, str) or not raw:
        return False, f"되읽기가 문자열이 아닙니다(창 미부팅·evaluate_js 실패): {raw!r}"
    try:
        data = json.loads(raw)
    except ValueError:
        return False, f"되읽기 JSON 붕괴: {raw!r}"
    if not isinstance(data, dict):
        return False, f"되읽기 형태 붕괴: {data!r}"
    if data.get("host") is not True:
        return False, "#reactOverlayHost 가 문서에 없습니다 — host 렌더가 서지 않았습니다"
    if data.get("mounted") != "1":
        return False, (
            f"커밋 마커 부재(mounted={data.get('mounted')!r}) — React 미커밋 상태의 골격은 "
            "판정 대상이 아닙니다"
        )
    if data.get("direct") is not True:
        return False, (
            "골격 4 가 host 컨테이너의 직속 자식이 아닙니다 — live 소유 술어"
            "(overlay_children_owned)가 무너지는 형상입니다"
        )
    if data.get("closed") != "none":
        return False, (
            f"첫 open 전 confirm 의 계산 display 가 none 이 아닙니다({data.get('closed')!r}) — "
            "닫힘 상태 상시 렌더(개정 3-1) 위반입니다"
        )
    if data.get("toast_hidden") is not True:
        return False, "토스트가 hidden 으로 시작하지 않습니다"
    if data.get("unique") is not True:
        return False, (
            "골격 id 가 문서 전역에서 유일하지 않습니다 — index.html 재도입(두 세계 분열)이 "
            "의심됩니다"
        )
    return True, "overlay host 마커 확인"


# ─────────────────────────── 술어의 판별력 (창 없는 대조) ───────────────────────────


def test_the_verdict_passes_the_expected_shape() -> None:
    """양성 대조 — 아래 음성들이 「언제나 빨강」이 아님을 먼저 세운다."""
    healthy = json.dumps({
        "host": True, "mounted": "1", "direct": True,
        "closed": "none", "toast_hidden": True, "unique": True,
    })

    ok, reason = judge_overlay_readback(healthy)

    assert ok, reason


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        (None, "문자열이 아닙니다"),
        ("not-json", "JSON 붕괴"),
        ('{"host": false}', "host 렌더가 서지 않았습니다"),
        (
            '{"host": true, "mounted": null, "direct": true, "closed": "none",'
            ' "toast_hidden": true, "unique": true}',
            "커밋 마커 부재",
        ),
        (
            '{"host": true, "mounted": "1", "direct": false, "closed": "none",'
            ' "toast_hidden": true, "unique": true}',
            "직속 자식이 아닙니다",
        ),
        (
            '{"host": true, "mounted": "1", "direct": true, "closed": "flex",'
            ' "toast_hidden": true, "unique": true}',
            "닫힘 상태 상시 렌더",
        ),
        (
            '{"host": true, "mounted": "1", "direct": true, "closed": "none",'
            ' "toast_hidden": false, "unique": true}',
            "hidden 으로 시작하지",
        ),
        (
            '{"host": true, "mounted": "1", "direct": true, "closed": "none",'
            ' "toast_hidden": true, "unique": false}',
            "유일하지 않습니다",
        ),
    ],
)
def test_the_verdict_rejects_each_degraded_shape(raw: object, fragment: str) -> None:
    """음성 대조 — host 소실·미커밋·자식 이탈·상시 렌더 위반·재도입 각각이 자기 이름으로 빨갛다."""
    ok, reason = judge_overlay_readback(raw)

    assert not ok
    assert fragment in reason, reason


# ────────────────────────────────── 실 창 게이트 ──────────────────────────────────

#: 자식 드라이버 — 실 백엔드가 달린 자체 창에서 2단계(부팅 커밋 → reload 신품 마운트)를
#: 이 모듈의 술어로 폴링하고, 단계별 마지막 되읽기를 한 줄로 내보낸다.
_CHILD_DRIVER = """
import json, sys, tempfile, threading, time
from pathlib import Path

import webview

from hwpxfiller.webapp.app import WebFrontend, default_text_templates_dir, web_artifact
from test_react_overlay_live import (
    OVERLAY_READBACK_EXPRESSION, PHASES, _PROBE_BUDGET_S, _READBACK_LINE_PREFIX,
    judge_overlay_readback,
)

artifact = web_artifact()
frontend = WebFrontend(default_text_templates_dir())
storage = Path(tempfile.mkdtemp(prefix="hwpx-overlay-live-")).resolve()
window = webview.create_window(
    "hwpx-filler overlay host 게이트",
    str(artifact.index_path),
    js_api=frontend,
    hidden=True,
)
frontend._window = window
loaded_event = threading.Event()
window.events.loaded += loaded_event.set


def probe() -> None:
    results = {}
    deadline = time.monotonic() + _PROBE_BUDGET_S

    def poll(phase):
        raw = None
        while time.monotonic() < deadline:
            try:
                raw = window.evaluate_js(OVERLAY_READBACK_EXPRESSION)
            except Exception:  # noqa: BLE001 — 부팅·reload 중 호출은 실패가 정상
                raw = None
            if judge_overlay_readback(raw)[0]:
                break
            time.sleep(0.25)
        results[phase] = raw if isinstance(raw, str) else None

    try:
        poll("boot")
        #: 재초기화 — 문서 재적재가 bootProduct() 를 다시 돌려 host 마운트·다이얼로그
        #: 슬롯이 신품으로 선다(같은 문서 안 이중 마운트는 슬롯이 throw 로 막는 별개 축).
        #: evaluate 로 reload 를 쏘면 문서 해체가 평가 응답과 경합해 evaluate_js 가 영영
        #: 안 돌아올 수 있다(#411 shell 게이트가 실증·폐쇄한 경합 클래스) — load_url(file
        #: URI) + loaded 대기로 해체 구간 평가를 0 으로 만든다.
        loaded_event.clear()
        window.load_url(artifact.index_path.as_uri())
        loaded_event.wait(30.0)
        poll("reloaded")
    finally:
        print(_READBACK_LINE_PREFIX + json.dumps(results))
        sys.stdout.flush()
        window.destroy()


webview.start(probe, gui="edgechromium", storage_path=str(storage))
"""


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_overlay_host_commits_skeletons_and_survives_reinit_in_a_real_window() -> None:
    """실 창에서 host 골격 커밋·직속 자식·닫힘 상시 렌더·id 유일이 reload 를 가로질러 선다."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(TESTS_DIR), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["PYTHONUTF8"] = "1"

    try:
        child = subprocess.run(
            [sys.executable, "-c", _CHILD_DRIVER],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CHILD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as expired:
        raise AssertionError(
            f"overlay 게이트 창이 {_CHILD_TIMEOUT_S:.0f}s 안에 종결하지 못했습니다 — "
            f"전면 매달림입니다.\nstdout 꼬리: {str(expired.stdout)[-2000:]}\n"
            f"stderr 꼬리: {str(expired.stderr)[-2000:]}"
        ) from None

    report = f"rc={child.returncode}\nstdout:\n{child.stdout}\nstderr:\n{child.stderr[-3000:]}"
    assert child.returncode == 0, f"overlay 게이트 창이 비정상 종료했습니다.\n{report}"

    lines = [
        line[len(_READBACK_LINE_PREFIX):]
        for line in child.stdout.splitlines()
        if line.startswith(_READBACK_LINE_PREFIX)
    ]
    assert len(lines) == 1, f"되읽기 마커 줄이 정확히 하나가 아닙니다.\n{report}"

    results = json.loads(lines[0])
    for phase in PHASES:
        ok, reason = judge_overlay_readback(results.get(phase))
        assert ok, f"[{phase}] {reason}\n{report}"
