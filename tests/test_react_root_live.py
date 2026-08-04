"""실 WebView2 React 마운트 게이트 — 커밋 마커 되읽기 (R2-01 · #405).

정적 게이트는 ``#reactRoot`` 가 문서에 **존재한다**까지만 말한다. 「React 가 실 WebView2
에서 실제로 커밋했다」는 다른 사실이고, 빈 트리 + 정적 컨테이너는 관측자 없이 그 둘을
구별하지 못한다. 그래서 root 상태기계는 커밋 순간 ``data-react-mounted="1"`` 을 심고
(``frontend/src/react/root.ts``), 이 게이트가 실 창에서 그 마커를 ``evaluate_js`` 로
되읽는다.

**자체 pywebview 창으로 sealed artifact 를 직접 소비한다** — ``--selftest`` 는 재활용하지
않는다(프로브 레지스트리는 R2-04 소유 — 패킷 rev3 §7).

패킷은 「React 마운트는 호스트 브리지 없이 성립하므로 백엔드 조립이 불요하다」고 예정했고
그 전제 자체는 참이지만(설치 Chrome + loopback 실측: 호스트 없이 커밋 마커 초록), **pywebview
창은 「호스트 없음」을 만들 수 없다**(착수 실측): ``js_api`` 를 주지 않아도 ``window.pywebview``
와 **빈 ``api``(키 0)** 가 주입되고 ``pywebviewready`` 가 발화한다. 그 형상에서 셸은 호스트가
있다고 판정해 첫 호출에서 죽고, 그 실패는 설계대로 **시끄러운 경보(alert)** 로 착지한다 —
alert 는 JS 스레드를 세워 ``evaluate_js`` 가 영영 돌아오지 않는다. 페이지가 아니라 「깨진
호스트」를 만든 하니스의 결함이므로, 자식은 실제 앱과 같은 두 줄로 **실 백엔드**
(:class:`WebFrontend` + ``_window`` 대입)를 단다 — 가짜 호스트를 만들지 않고, 일반 실행과
같은 entry·부팅 사슬을 지나 커밋을 잰다(경계 계약의 「일반 실행·selftest 의 같은 entry 사용」).

판정 술어(:func:`judge_mount_readback`)는 창을 모는 자식 프로세스와 **같은 하나**다 —
자식은 이 모듈을 import 해 완주 조건을 묻고, 부모는 같은 술어로 최종 판정한다. 두 곳이
따로 판정하는 순간 「루프는 통과로 봤는데 게이트는 빨강」 같은 갈림이 생긴다.

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

#: 창 안에서 되읽는 표현식 — 컨테이너 존재와 커밋 마커를 **한 번에** 실어 온다. 존재만
#: 물으면 정적 사실과 구별이 안 되고, 마커만 물으면 「컨테이너째 사라짐」이 「미커밋」으로
#: 뭉개진다.
MOUNT_READBACK_EXPRESSION = (
    "(function () {"
    " var el = document.getElementById('reactRoot');"
    " return JSON.stringify({"
    "   present: el !== null,"
    "   marker: el === null ? null : el.getAttribute('data-react-mounted'),"
    " });"
    "})()"
)

#: 자식이 마커 줄로 내보내는 되읽기 원문의 접두 — 부모는 이 줄만 신뢰한다.
_READBACK_LINE_PREFIX = "HWPX-REACT-READBACK="

#: 창 안 폴링 예산. 콜드 부팅(초회 WebView2 런타임 기동·AV 스캔)까지 품는 값이고, 정상
#: 실행은 수 초 안에 커밋한다 — 이 예산이 무는 것은 「느림」이 아니라 매달림·미커밋이다.
_PROBE_BUDGET_S = 90.0
#: 자식 프로세스 상한 — 폴링 예산 + 부팅·정리 여유. 초과는 전면 매달림으로 즉시 실패다.
_CHILD_TIMEOUT_S = 240.0


def judge_mount_readback(raw: object) -> "tuple[bool, str]":
    """되읽기 원문 → (통과, 사유). 컨테이너 부재·마커 부재·형식 붕괴 전부 빨강이다.

    사유를 함께 돌려주는 이유: 실패가 「마운트 안 됨」 하나로 뭉개지면 컨테이너가 사라진
    것인지(정적 회귀) 커밋이 안 선 것인지(런타임 회귀) 원인 판독이 창 없이는 불가능해진다.
    """
    if not isinstance(raw, str) or not raw:
        return False, f"되읽기가 문자열이 아닙니다(창 미부팅·evaluate_js 실패): {raw!r}"
    try:
        data = json.loads(raw)
    except ValueError:
        return False, f"되읽기 JSON 붕괴: {raw!r}"
    if not isinstance(data, dict):
        return False, f"되읽기 형태 붕괴: {data!r}"
    if data.get("present") is not True:
        return False, "#reactRoot 컨테이너가 문서에 없습니다 — 정적 subtree 가 사라졌습니다"
    if data.get("marker") != "1":
        return False, (
            f"커밋 마커 부재(marker={data.get('marker')!r}) — React 가 실 창에서 커밋하지 못했습니다"
        )
    return True, "커밋 마커 확인"


# ─────────────────────────── 술어의 판별력 (창 없는 대조) ───────────────────────────


def test_the_verdict_passes_a_committed_readback() -> None:
    """양성 대조 — 아래 음성들이 「언제나 빨강」이 아님을 먼저 세운다."""
    ok, reason = judge_mount_readback('{"present": true, "marker": "1"}')

    assert ok, reason


def test_the_verdict_rejects_a_marker_absent_container() -> None:
    """마커 배선을 끊은 합성 형상 — 컨테이너는 있는데 커밋 마커가 없다(rev2 §7 음성).

    이 대조가 「초록이 마운트를 증명하는가」를 술어 수준에서 세운다: hidden 요소도
    통과시키는 프로브 클릭류의 결함이 이 게이트에는 설 자리가 없어야 한다.
    """
    ok, reason = judge_mount_readback('{"present": true, "marker": null}')

    assert not ok
    assert "커밋 마커 부재" in reason


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        (None, "문자열이 아닙니다"),
        ("", "문자열이 아닙니다"),
        ("not-json", "JSON 붕괴"),
        ('{"present": false, "marker": null}', "컨테이너가 문서에 없습니다"),
        ('{"present": true, "marker": "0"}', "커밋 마커 부재"),
    ],
)
def test_the_verdict_rejects_each_degraded_shape(raw: object, fragment: str) -> None:
    """음성 대조 — 붕괴 형상 각각이 자기 이름으로 빨갛다(원인 판독이 창 없이 선다)."""
    ok, reason = judge_mount_readback(raw)

    assert not ok
    assert fragment in reason, reason


# ────────────────────────────────── 실 창 게이트 ──────────────────────────────────

#: 자식 드라이버 — sealed artifact 를 실 백엔드가 달린 자체 창으로 싣고, 이 모듈의
#: 술어가 통과를 말할 때까지 되읽는다. storage_path 는 절대 경로여야 한다(상대 경로는
#: WebView2 생성 실패 → MSHTML 조용 폴백 — app.py 의 같은 함정). ``WebFrontend`` 구성과
#: ``_window`` 대입은 app.py 의 실제 부팅 두 줄을 그대로 소비한다(webapp 무변경).
_CHILD_DRIVER = """
import json, sys, tempfile, time
from pathlib import Path

import webview

from hwpxfiller.webapp.app import WebFrontend, default_text_templates_dir, web_artifact
from test_react_root_live import (
    MOUNT_READBACK_EXPRESSION, _PROBE_BUDGET_S, _READBACK_LINE_PREFIX, judge_mount_readback,
)

artifact = web_artifact()
frontend = WebFrontend(default_text_templates_dir())
storage = Path(tempfile.mkdtemp(prefix="hwpx-react-live-")).resolve()
window = webview.create_window(
    "hwpx-filler React root 게이트",
    str(artifact.index_path),
    js_api=frontend,
    hidden=True,
)
frontend._window = window


def probe() -> None:
    raw = None
    deadline = time.monotonic() + _PROBE_BUDGET_S
    try:
        while time.monotonic() < deadline:
            try:
                raw = window.evaluate_js(MOUNT_READBACK_EXPRESSION)
            except Exception:  # noqa: BLE001 — 부팅 전 호출은 실패가 정상, 최종 판정은 부모 몫
                raw = None
            if judge_mount_readback(raw)[0]:
                break
            time.sleep(0.25)
    finally:
        print(_READBACK_LINE_PREFIX + json.dumps(raw if isinstance(raw, str) else None))
        sys.stdout.flush()
        window.destroy()


webview.start(probe, gui="edgechromium", storage_path=str(storage))
"""


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_react_root_commits_in_a_real_webview2_window() -> None:
    """sealed artifact 하나로 실 창을 세우면 React 가 커밋 마커를 실제로 심는다."""
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
            f"React root 게이트 창이 {_CHILD_TIMEOUT_S:.0f}s 안에 종결하지 못했습니다 — "
            f"전면 매달림입니다.\nstdout 꼬리: {str(expired.stdout)[-2000:]}\n"
            f"stderr 꼬리: {str(expired.stderr)[-2000:]}"
        ) from None

    report = f"rc={child.returncode}\nstdout:\n{child.stdout}\nstderr:\n{child.stderr[-3000:]}"
    assert child.returncode == 0, f"React root 게이트 창이 비정상 종료했습니다.\n{report}"

    lines = [
        line[len(_READBACK_LINE_PREFIX):]
        for line in child.stdout.splitlines()
        if line.startswith(_READBACK_LINE_PREFIX)
    ]
    assert len(lines) == 1, f"되읽기 마커 줄이 정확히 하나가 아닙니다.\n{report}"

    ok, reason = judge_mount_readback(json.loads(lines[0]))
    assert ok, f"{reason}\n{report}"
