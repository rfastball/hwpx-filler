"""실 WebView2 셸 수명주기 게이트 — 랜딩·동기 전환·닫기 왕복·재초기화 (R3-02 · #411).

node 계약 테스트는 상태기계 판정(shell_nav)과 adapter 결합(n06 — attachShell 같은 실물)까지를
재고, 「React ShellHost 가 실 창에서 리스너를 실제로 부착해 탭이 응답하고, 부팅 시퀀스가
실제로 돌고, 닫기 확인이 실 브리지로 왕복한다」는 별개 사실이다 — 실 React 커밋·실 클릭
디스패치·실 pywebviewready 발화는 node 에 없다. 그래서 이 게이트가 실 창에서 재는 것은
다섯이다:

- **부팅 랜딩**: 커밋 마커가 서고 ``scr-job`` 에 ``.on``, job 탭에 ``aria-current`` — 기존
  부팅·라우팅 프로브(``job_on``·``nav_count``)와 같은 document 판독을 자체 창에서 잰다.
- **동기 전환**: library 탭 **실클릭과 같은 동기 턴**에 클래스·aria 전환이 완료돼 있다 —
  ShellHost 가 부착한 리스너의 실물 증거이자 n06 동기 핀의 live 쌍둥이(React 재렌더 비경유).
- **닫기 취소 왕복**: ``close-request`` 배달 → React overlay 위 확인창(종료 라벨·danger·
  「계속 작업」 문안 잔존 계약) → 취소 클릭 → 창 유지 + 확인창 닫힘(실 브리지
  ``cancel_window_close`` 경유).
- **재초기화**: ``location.reload()`` 가 ``bootProduct()`` 전체 재구성을 돌려 랜딩·전환이
  신품으로 다시 선다(상태기계·ShellHost 부착의 재구성 실측).
- **닫기 확정**: 두 번째 ``close-request`` 에서 「종료」 클릭 → 실 브리지
  ``confirm_window_close`` 가 창을 실제로 닫는다(``closed`` 이벤트로 잰다).

창 하니스(실 백엔드 두 줄·절대 storage_path·단일 판정 술어·마커 줄 프로토콜)는
``test_react_root_live.py``/``test_react_overlay_live.py`` 를 그대로 승계한다.

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

#: 랜딩 되읽기 — 커밋 마커·탭 수·job 랜딩·aria 를 한 번에 싣는다(부팅·reload 공용).
LANDING_READBACK_EXPRESSION = (
    "(function () {"
    " var root = document.getElementById('reactRoot');"
    " var job = document.getElementById('scr-job');"
    " var lib = document.getElementById('scr-library');"
    " var btn = document.querySelector('.navbtn[data-scr=\"job\"]');"
    " return JSON.stringify({"
    "   mounted: root === null ? null : root.getAttribute('data-react-mounted'),"
    "   nav_count: document.querySelectorAll('.navbtn').length,"
    "   job_on: job !== null && job.classList.contains('on'),"
    "   lib_on: lib !== null && lib.classList.contains('on'),"
    "   aria: btn === null ? null : btn.getAttribute('aria-current'),"
    " });"
    "})()"
)

#: 동기 전환 되읽기 — library 탭 실클릭과 **같은 동기 턴**의 판독. 폴링하지 않는다:
#: 마커가 선 뒤라면 ShellHost 부착은 같은 커밋 flush 에서 끝나 있고, go 는 synchronous 다.
NAV_CLICK_EXPRESSION = (
    "(function () {"
    " var btn = document.querySelector('.navbtn[data-scr=\"library\"]');"
    " if (btn === null) return JSON.stringify({ clicked: false });"
    " btn.click();"
    " var lib = document.getElementById('scr-library');"
    " var job = document.getElementById('scr-job');"
    " return JSON.stringify({"
    "   clicked: true,"
    "   lib_on: lib !== null && lib.classList.contains('on'),"
    "   job_on: job !== null && job.classList.contains('on'),"
    "   aria: btn.getAttribute('aria-current'),"
    " });"
    "})()"
)

#: 닫기 확인창 되읽기 — 표시 여부·문안·danger 잔존 계약(패킷 rev3 개정 5)의 live 쌍둥이.
CLOSE_PROMPT_READBACK_EXPRESSION = (
    "(function () {"
    " var cm = document.getElementById('confirmModal');"
    " var ok = document.getElementById('confirmModalOk');"
    " var cancel = document.getElementById('confirmModalCancel');"
    " if (cm === null || ok === null || cancel === null) return JSON.stringify({ present: false });"
    " return JSON.stringify({"
    "   present: true,"
    "   display: getComputedStyle(cm).display,"
    "   ok_label: ok.textContent,"
    "   ok_danger: ok.classList.contains('danger'),"
    "   cancel_label: cancel.textContent,"
    " });"
    "})()"
)

#: 취소 정착 되읽기 — 확인창이 닫혔고 문서가 살아 있다(창 유지의 증거는 이 평가 자체다).
CLOSE_SETTLED_READBACK_EXPRESSION = (
    "(function () {"
    " var cm = document.getElementById('confirmModal');"
    " return JSON.stringify({"
    "   display: cm === null ? null : getComputedStyle(cm).display,"
    " });"
    "})()"
)

#: 자식이 단계별 되읽기를 실어 내보내는 줄의 접두 — 부모는 이 줄만 신뢰한다.
_READBACK_LINE_PREFIX = "HWPX-SHELL-READBACK="

#: 창 안 폴링 예산(전 단계 합산)·자식 상한 — 형제 live 게이트의 예산 산정을 승계한다.
_PROBE_BUDGET_S = 120.0
_CHILD_TIMEOUT_S = 240.0

#: 폴링 단계 이름 — 부팅 랜딩 → 취소 확인창 → 취소 정착 → 재초기화 랜딩 → 확정 확인창.
#: (동기 전환 nav/renav 는 폴링이 아니라 단발 판독, confirm_closed 는 이벤트 불리언이다.)
PHASES = ("boot", "close_prompt", "close_cancelled", "reloaded", "confirm_prompt")


def judge_landing_readback(raw: object) -> "tuple[bool, str]":
    """되읽기 원문 → (통과, 사유). 커밋·탭 2·job 랜딩·aria 전부를 판정한다."""
    if not isinstance(raw, str) or not raw:
        return False, f"되읽기가 문자열이 아닙니다(창 미부팅·evaluate_js 실패): {raw!r}"
    try:
        data = json.loads(raw)
    except ValueError:
        return False, f"되읽기 JSON 붕괴: {raw!r}"
    if not isinstance(data, dict):
        return False, f"되읽기 형태 붕괴: {data!r}"
    if data.get("mounted") != "1":
        return False, f"커밋 마커 부재(mounted={data.get('mounted')!r}) — ShellHost 부착 전 형상"
    if data.get("nav_count") != 2:
        return False, f"탭 수가 2가 아닙니다({data.get('nav_count')!r}) — 화면 소실 회귀"
    if data.get("job_on") is not True:
        return False, "scr-job 에 .on 이 없습니다 — 콜드 부팅 랜딩(H-05) 위반"
    if data.get("lib_on") is not False:
        return False, "scr-library 가 함께 켜져 있습니다 — 단일 화면 계약 위반"
    if data.get("aria") != "true":
        return False, f"job 탭 aria-current 가 true 가 아닙니다({data.get('aria')!r})"
    return True, "랜딩 확인"


def judge_nav_click_readback(raw: object) -> "tuple[bool, str]":
    """동기 전환 판정 — 클릭과 같은 턴에 클래스·aria 가 전환돼 있어야 한다."""
    if not isinstance(raw, str) or not raw:
        return False, f"되읽기가 문자열이 아닙니다: {raw!r}"
    try:
        data = json.loads(raw)
    except ValueError:
        return False, f"되읽기 JSON 붕괴: {raw!r}"
    if not isinstance(data, dict):
        return False, f"되읽기 형태 붕괴: {data!r}"
    if data.get("clicked") is not True:
        return False, "library 탭이 문서에 없습니다 — 클릭 자체가 서지 않았습니다"
    if data.get("lib_on") is not True:
        return False, (
            "클릭과 같은 동기 턴에 scr-library 가 켜져 있지 않습니다 — ShellHost 리스너 부재 "
            "또는 동기 집행 계약(React 재렌더 비경유) 위반"
        )
    if data.get("job_on") is not False:
        return False, "전환 뒤에도 scr-job 이 켜져 있습니다"
    if data.get("aria") != "true":
        return False, f"library 탭 aria-current 가 같은 턴에 서지 않았습니다({data.get('aria')!r})"
    return True, "동기 전환 확인"


def judge_close_prompt_readback(raw: object) -> "tuple[bool, str]":
    """닫기 확인창 판정 — 표시·「종료」 danger·「계속 작업」 문안 잔존 계약."""
    if not isinstance(raw, str) or not raw:
        return False, f"되읽기가 문자열이 아닙니다: {raw!r}"
    try:
        data = json.loads(raw)
    except ValueError:
        return False, f"되읽기 JSON 붕괴: {raw!r}"
    if not isinstance(data, dict):
        return False, f"되읽기 형태 붕괴: {data!r}"
    if data.get("present") is not True:
        return False, "확인창 골격이 문서에 없습니다 — overlay host 미커밋 형상"
    if data.get("display") == "none":
        return False, "close-request 뒤에도 확인창이 닫혀 있습니다 — 셸 닫기 경로 미착지"
    if data.get("ok_label") != "종료":
        return False, f"확정 라벨이 「종료」가 아닙니다({data.get('ok_label')!r}) — 문안 잔존 계약 위반"
    if data.get("ok_danger") is not True:
        return False, "확정 버튼에 danger 가 없습니다 — 파괴 확정 감사 계약 위반"
    if data.get("cancel_label") != "계속 작업":
        return False, f"취소 라벨이 「계속 작업」이 아닙니다({data.get('cancel_label')!r})"
    return True, "닫기 확인창 확인"


def judge_close_settled_readback(raw: object) -> "tuple[bool, str]":
    """취소 정착 판정 — 확인창이 닫혔다(평가가 성립했다는 사실이 곧 창 유지의 증거다)."""
    if not isinstance(raw, str) or not raw:
        return False, f"되읽기가 문자열이 아닙니다: {raw!r}"
    try:
        data = json.loads(raw)
    except ValueError:
        return False, f"되읽기 JSON 붕괴: {raw!r}"
    if not isinstance(data, dict):
        return False, f"되읽기 형태 붕괴: {data!r}"
    if data.get("display") != "none":
        return False, f"취소 뒤에도 확인창이 열려 있습니다(display={data.get('display')!r})"
    return True, "취소 정착 확인"


#: 단계 → 판정 술어. 자식(폴링 완주 조건)과 부모(최종 판정)가 **같은 하나**를 쓴다.
PHASE_JUDGES = {
    "boot": judge_landing_readback,
    "close_prompt": judge_close_prompt_readback,
    "close_cancelled": judge_close_settled_readback,
    "reloaded": judge_landing_readback,
    "confirm_prompt": judge_close_prompt_readback,
}


# ─────────────────────────── 술어의 판별력 (창 없는 대조) ───────────────────────────


def test_the_verdicts_pass_the_expected_shapes() -> None:
    """양성 대조 — 아래 음성들이 「언제나 빨강」이 아님을 먼저 세운다."""
    landing = json.dumps({
        "mounted": "1", "nav_count": 2, "job_on": True, "lib_on": False, "aria": "true",
    })
    nav = json.dumps({"clicked": True, "lib_on": True, "job_on": False, "aria": "true"})
    prompt = json.dumps({
        "present": True, "display": "flex", "ok_label": "종료",
        "ok_danger": True, "cancel_label": "계속 작업",
    })
    settled = json.dumps({"display": "none"})

    for judge, raw in (
        (judge_landing_readback, landing),
        (judge_nav_click_readback, nav),
        (judge_close_prompt_readback, prompt),
        (judge_close_settled_readback, settled),
    ):
        ok, reason = judge(raw)
        assert ok, reason


@pytest.mark.parametrize(
    ("judge", "raw", "fragment"),
    [
        (judge_landing_readback, None, "문자열이 아닙니다"),
        (judge_landing_readback, "not-json", "JSON 붕괴"),
        (
            judge_landing_readback,
            '{"mounted": null, "nav_count": 2, "job_on": true, "lib_on": false, "aria": "true"}',
            "커밋 마커 부재",
        ),
        (
            judge_landing_readback,
            '{"mounted": "1", "nav_count": 2, "job_on": false, "lib_on": false, "aria": "true"}',
            "콜드 부팅 랜딩",
        ),
        (
            judge_nav_click_readback,
            '{"clicked": true, "lib_on": false, "job_on": true, "aria": "false"}',
            "동기 집행 계약",
        ),
        (
            judge_close_prompt_readback,
            '{"present": true, "display": "none", "ok_label": "종료", "ok_danger": true,'
            ' "cancel_label": "계속 작업"}',
            "닫기 경로 미착지",
        ),
        (
            judge_close_prompt_readback,
            '{"present": true, "display": "flex", "ok_label": "확인", "ok_danger": true,'
            ' "cancel_label": "계속 작업"}',
            "문안 잔존 계약",
        ),
        (
            judge_close_prompt_readback,
            '{"present": true, "display": "flex", "ok_label": "종료", "ok_danger": false,'
            ' "cancel_label": "계속 작업"}',
            "danger",
        ),
        (judge_close_settled_readback, '{"display": "flex"}', "열려 있습니다"),
    ],
)
def test_the_verdicts_reject_each_degraded_shape(judge, raw: object, fragment: str) -> None:
    """음성 대조 — 미커밋·랜딩 붕괴·전환 미완·닫기 미착지·문안 훼손 각각이 자기 이름으로 빨갛다."""
    ok, reason = judge(raw)

    assert not ok
    assert fragment in reason, reason


# ────────────────────────────────── 실 창 게이트 ──────────────────────────────────

#: 자식 드라이버 — 실 백엔드가 달린 자체 창에서 랜딩 → 동기 전환 → 닫기 취소 왕복 →
#: reload 재실측 → 닫기 확정(실제 창 닫힘)을 이 모듈의 술어로 폴링·단발 판독하고,
#: 단계별 마지막 되읽기를 한 줄로 내보낸다.
_CHILD_DRIVER = """
import json, sys, tempfile, threading, time
from pathlib import Path

import webview

from hwpxfiller.webapp.app import WebFrontend, default_text_templates_dir, web_artifact
from hwpxfiller.webapp.product_api import close_request_expression
from test_react_shell_live import (
    CLOSE_PROMPT_READBACK_EXPRESSION, CLOSE_SETTLED_READBACK_EXPRESSION,
    LANDING_READBACK_EXPRESSION, NAV_CLICK_EXPRESSION, PHASE_JUDGES,
    _PROBE_BUDGET_S, _READBACK_LINE_PREFIX,
)

artifact = web_artifact()
frontend = WebFrontend(default_text_templates_dir())
storage = Path(tempfile.mkdtemp(prefix="hwpx-shell-live-")).resolve()
window = webview.create_window(
    "hwpx-filler shell 게이트",
    str(artifact.index_path),
    js_api=frontend,
    hidden=True,
)
frontend._window = window
closed_event = threading.Event()
window.events.closed += closed_event.set

CLOSE_STATE = {"armed": True, "reasons": ["실 게이트 편집 세션"]}
PHASE_EXPRESSIONS = {
    "boot": LANDING_READBACK_EXPRESSION,
    "close_prompt": CLOSE_PROMPT_READBACK_EXPRESSION,
    "close_cancelled": CLOSE_SETTLED_READBACK_EXPRESSION,
    "reloaded": LANDING_READBACK_EXPRESSION,
    "confirm_prompt": CLOSE_PROMPT_READBACK_EXPRESSION,
}


def probe() -> None:
    results = {}
    deadline = time.monotonic() + _PROBE_BUDGET_S

    def poll(phase):
        raw = None
        while time.monotonic() < deadline:
            try:
                raw = window.evaluate_js(PHASE_EXPRESSIONS[phase])
            except Exception:  # noqa: BLE001 — 부팅·reload 중 호출은 실패가 정상
                raw = None
            if PHASE_JUDGES[phase](raw)[0]:
                break
            time.sleep(0.25)
        results[phase] = raw if isinstance(raw, str) else None

    def shot(phase, expression):
        try:
            raw = window.evaluate_js(expression)
        except Exception:  # noqa: BLE001 — 최종 판정은 부모 몫
            raw = None
        results[phase] = raw if isinstance(raw, str) else None

    try:
        poll("boot")
        #: 동기 전환 — 폴링이 아니라 단발이다. 마커가 섰다면 부착은 끝나 있어야 하고,
        #: 전환은 클릭과 같은 턴에 완료돼야 한다(재시도는 그 계약의 위반을 가린다).
        shot("nav", NAV_CLICK_EXPRESSION)
        #: 닫기 취소 왕복 — Python 이 real closing 에서 보내는 것과 같은 배달 표현식.
        window.evaluate_js(close_request_expression(CLOSE_STATE))
        poll("close_prompt")
        window.evaluate_js("document.getElementById('confirmModalCancel').click()")
        poll("close_cancelled")
        #: 재초기화 — reload 가 bootProduct() 를 다시 돌려 상태기계·ShellHost 부착이
        #: 신품으로 선다. 랜딩·동기 전환을 같은 술어로 다시 잰다.
        try:
            window.evaluate_js("location.reload()")
        except Exception:  # noqa: BLE001 — 문서 해체 중 반환 실패는 정상
            pass
        poll("reloaded")
        shot("renav", NAV_CLICK_EXPRESSION)
        #: 닫기 확정 — 「종료」 클릭이 실 브리지 confirm_window_close 로 창을 실제로 닫는다.
        window.evaluate_js(close_request_expression(CLOSE_STATE))
        poll("confirm_prompt")
        try:
            window.evaluate_js("document.getElementById('confirmModalOk').click()")
        except Exception:  # noqa: BLE001 — 닫힘 경쟁으로 반환이 실패할 수 있다(정착은 이벤트가 잰다)
            pass
        results["confirm_closed"] = closed_event.wait(30.0)
    finally:
        print(_READBACK_LINE_PREFIX + json.dumps(results))
        sys.stdout.flush()
        if not closed_event.is_set():
            window.destroy()


webview.start(probe, gui="edgechromium", storage_path=str(storage))
"""


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_shell_lifecycle_lands_navigates_and_closes_in_a_real_window() -> None:
    """실 창에서 랜딩·동기 전환·닫기 취소/확정 왕복·reload 재초기화가 전부 선다."""
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
            f"shell 게이트 창이 {_CHILD_TIMEOUT_S:.0f}s 안에 종결하지 못했습니다 — "
            f"전면 매달림입니다.\nstdout 꼬리: {str(expired.stdout)[-2000:]}\n"
            f"stderr 꼬리: {str(expired.stderr)[-2000:]}"
        ) from None

    report = f"rc={child.returncode}\nstdout:\n{child.stdout}\nstderr:\n{child.stderr[-3000:]}"
    assert child.returncode == 0, f"shell 게이트 창이 비정상 종료했습니다.\n{report}"

    lines = [
        line[len(_READBACK_LINE_PREFIX):]
        for line in child.stdout.splitlines()
        if line.startswith(_READBACK_LINE_PREFIX)
    ]
    assert len(lines) == 1, f"되읽기 마커 줄이 정확히 하나가 아닙니다.\n{report}"

    results = json.loads(lines[0])
    for phase, judge in PHASE_JUDGES.items():
        ok, reason = judge(results.get(phase))
        assert ok, f"[{phase}] {reason}\n{report}"
    for nav_phase in ("nav", "renav"):
        ok, reason = judge_nav_click_readback(results.get(nav_phase))
        assert ok, f"[{nav_phase}] {reason}\n{report}"
    assert results.get("confirm_closed") is True, (
        f"「종료」 확정이 실 창을 닫지 못했습니다 — confirm_window_close 경로 미착지.\n{report}"
    )
