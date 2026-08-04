"""실 WebView2 스냅샷 store 게이트 — revision 마커 되읽기 + 재초기화 (R2-03 · #407).

node 계약 테스트는 store·hook 결속까지를 재고, 「Python push 가 실 창에서 store→React 로
실제로 흐른다」는 별개 사실이다 — 실 React 렌더 루프·실 브리지·실 `evaluate_js` 사슬은
node 에 없다. 그래서 트리의 StoreSignal 이 수신 총 revision 을 ``data-react-store-rev`` 로
반영하고(기입 주체는 target 을 닫은 ``boot.ts`` 클로저), 이 게이트가 실 창에서 그 마커를
되읽는다: 부팅 직후 ``"0"`` → 실 백엔드 push 뒤 양수 → **문서 재초기화(reload) 뒤 다시
``"0"`` → 재push 뒤 다시 양수**. 뒤 두 단계가 #407 의 「재초기화 검증」 축이다 — reload 는
``bootProduct()`` 전체 재구성이라 store·구독이 신품으로 서는 것을 실물로 잰다.

push 채널은 ``workbench`` 다 — legacy 렌더러가 ``s.open`` 없으면 조기 반환하는 유일한
채널이라(`workbench.js` 데이터 상태 게이트), 합성 스냅샷이 legacy 경로에 부작용을 만들지
않는다. push 는 컨트롤러들이 실제로 주입받는 sink(:meth:`WebFrontend._push`)를 그대로
소비한다 — dispatch→push 사슬은 selftest 게이트 소유라 여기서 재현하지 않는다.

창 하니스(실 백엔드 두 줄·절대 storage_path·단일 판정 술어·마커 줄 프로토콜)는
``test_react_root_live.py`` 의 착수 실측을 그대로 승계한다.

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

#: 창 안에서 되읽는 표현식 — 컨테이너·커밋 마커·store revision 마커를 **한 번에** 싣는다.
#: revision 만 물으면 「컨테이너째 사라짐」과 「미반영」이 뭉개진다(root live 게이트와 같은 결).
STORE_READBACK_EXPRESSION = (
    "(function () {"
    " var el = document.getElementById('reactRoot');"
    " return JSON.stringify({"
    "   present: el !== null,"
    "   mounted: el === null ? null : el.getAttribute('data-react-mounted'),"
    "   rev: el === null ? null : el.getAttribute('data-react-store-rev'),"
    " });"
    "})()"
)

#: 자식이 단계별 되읽기를 실어 내보내는 줄의 접두 — 부모는 이 줄만 신뢰한다.
_READBACK_LINE_PREFIX = "HWPX-STORE-READBACK="

#: 창 안 폴링 예산(4단계 합산)·자식 상한 — root live 게이트의 예산 산정을 승계한다.
_PROBE_BUDGET_S = 120.0
_CHILD_TIMEOUT_S = 240.0

#: 단계 이름 — 자식과 부모가 같은 순서를 공유한다(둘이 갈리면 판정이 갈린다).
PHASES = ("boot", "pushed", "reloaded", "repushed")


def judge_store_readback(raw: object, *, expect_positive: bool) -> "tuple[bool, str]":
    """되읽기 원문 → (통과, 사유). 컨테이너·커밋·revision 형상 전부를 판정한다.

    ``expect_positive=False`` 는 **신품 store**(부팅·재초기화 직후 ``"0"``)를,
    ``True`` 는 push 수신(양수)을 요구한다 — 「0 이 아니다」만 물으면 재초기화 단계가
    이전 세계의 잔존 값으로도 초록이 된다(부재판별력).
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
    if data.get("mounted") != "1":
        return False, (
            f"커밋 마커 부재(mounted={data.get('mounted')!r}) — React 미커밋 상태의 revision 은 "
            "판정 대상이 아닙니다"
        )
    rev = data.get("rev")
    if not isinstance(rev, str) or not rev.isdigit():
        return False, (
            f"store revision 마커 부재·붕괴(rev={rev!r}) — StoreSignal 이 반영하지 못했습니다"
        )
    if expect_positive and int(rev) < 1:
        return False, f"push 뒤에도 revision 이 오르지 않았습니다(rev={rev!r})"
    if not expect_positive and int(rev) != 0:
        return False, (
            f"신품 store 의 revision 이 0 이 아닙니다(rev={rev!r}) — 재초기화가 이전 세계를 "
            "이월했거나 예상 밖 push 가 섞였습니다"
        )
    return True, "store revision 마커 확인"


def phase_expectation(phase: str) -> bool:
    """단계 → ``expect_positive``. 자식 폴링과 부모 최종 판정이 같은 표를 쓴다."""
    return phase in ("pushed", "repushed")


# ─────────────────────────── 술어의 판별력 (창 없는 대조) ───────────────────────────


def test_the_verdict_passes_each_expected_shape() -> None:
    """양성 대조 — 아래 음성들이 「언제나 빨강」이 아님을 먼저 세운다."""
    fresh = '{"present": true, "mounted": "1", "rev": "0"}'
    pushed = '{"present": true, "mounted": "1", "rev": "3"}'

    assert judge_store_readback(fresh, expect_positive=False)[0]
    assert judge_store_readback(pushed, expect_positive=True)[0]


@pytest.mark.parametrize(
    ("raw", "expect_positive", "fragment"),
    [
        (None, True, "문자열이 아닙니다"),
        ("not-json", True, "JSON 붕괴"),
        ('{"present": false, "mounted": null, "rev": null}', True, "컨테이너가 문서에 없습니다"),
        ('{"present": true, "mounted": null, "rev": "1"}', True, "커밋 마커 부재"),
        ('{"present": true, "mounted": "1", "rev": null}', True, "revision 마커 부재"),
        ('{"present": true, "mounted": "1", "rev": "0"}', True, "오르지 않았습니다"),
        ('{"present": true, "mounted": "1", "rev": "2"}', False, "0 이 아닙니다"),
    ],
)
def test_the_verdict_rejects_each_degraded_shape(
    raw: object, expect_positive: bool, fragment: str
) -> None:
    """음성 대조 — 붕괴·미반영·잔존 이월 각각이 자기 이름으로 빨갛다."""
    ok, reason = judge_store_readback(raw, expect_positive=expect_positive)

    assert not ok
    assert fragment in reason, reason


def test_the_phase_table_matches_the_reinit_contract() -> None:
    """단계 표 자체의 계약 — 재초기화 단계가 신품(0)을 요구하는 것이 이 게이트의 요지다."""
    assert [phase_expectation(p) for p in PHASES] == [False, True, False, True]


# ────────────────────────────────── 실 창 게이트 ──────────────────────────────────

#: 자식 드라이버 — 실 백엔드가 달린 자체 창에서 4단계(부팅 0 → push 양수 → reload 0 →
#: 재push 양수)를 이 모듈의 술어로 폴링하고, 단계별 마지막 되읽기를 한 줄로 내보낸다.
_CHILD_DRIVER = """
import json, sys, tempfile, time
from pathlib import Path

import webview

from hwpxfiller.webapp.app import WebFrontend, default_text_templates_dir, web_artifact
from test_react_store_live import (
    PHASES, STORE_READBACK_EXPRESSION, _PROBE_BUDGET_S, _READBACK_LINE_PREFIX,
    judge_store_readback, phase_expectation,
)

artifact = web_artifact()
frontend = WebFrontend(default_text_templates_dir())
storage = Path(tempfile.mkdtemp(prefix="hwpx-store-live-")).resolve()
window = webview.create_window(
    "hwpx-filler snapshot store 게이트",
    str(artifact.index_path),
    js_api=frontend,
    hidden=True,
)
frontend._window = window


def probe() -> None:
    results = {}
    deadline = time.monotonic() + _PROBE_BUDGET_S

    def poll(phase):
        raw = None
        while time.monotonic() < deadline:
            try:
                raw = window.evaluate_js(STORE_READBACK_EXPRESSION)
            except Exception:  # noqa: BLE001 — 부팅·reload 중 호출은 실패가 정상
                raw = None
            if judge_store_readback(raw, expect_positive=phase_expectation(phase))[0]:
                break
            time.sleep(0.25)
        results[phase] = raw if isinstance(raw, str) else None

    try:
        poll("boot")
        #: 컨트롤러가 주입받는 실제 sink 그대로 — workbench 렌더러는 open 없는 스냅샷에
        #: 조기 반환하므로 legacy 경로 부작용이 없다(모듈 머리말).
        frontend._push("workbench", {"probe": 1})
        poll("pushed")
        #: 재초기화 — 문서 reload 가 bootProduct() 를 다시 돌려 store 가 신품으로 선다.
        try:
            window.evaluate_js("location.reload()")
        except Exception:  # noqa: BLE001 — 문서 해체 중 반환 실패는 정상
            pass
        poll("reloaded")
        frontend._push("workbench", {"probe": 2})
        poll("repushed")
    finally:
        print(_READBACK_LINE_PREFIX + json.dumps(results))
        sys.stdout.flush()
        window.destroy()


webview.start(probe, gui="edgechromium", storage_path=str(storage))
"""


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_snapshot_store_receives_pushes_and_survives_reinit_in_a_real_window() -> None:
    """실 창에서 Python push→store→React 인과와 재초기화 신품성이 마커로 선다."""
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
            f"store 게이트 창이 {_CHILD_TIMEOUT_S:.0f}s 안에 종결하지 못했습니다 — "
            f"전면 매달림입니다.\nstdout 꼬리: {str(expired.stdout)[-2000:]}\n"
            f"stderr 꼬리: {str(expired.stderr)[-2000:]}"
        ) from None

    report = f"rc={child.returncode}\nstdout:\n{child.stdout}\nstderr:\n{child.stderr[-3000:]}"
    assert child.returncode == 0, f"store 게이트 창이 비정상 종료했습니다.\n{report}"

    lines = [
        line[len(_READBACK_LINE_PREFIX):]
        for line in child.stdout.splitlines()
        if line.startswith(_READBACK_LINE_PREFIX)
    ]
    assert len(lines) == 1, f"되읽기 마커 줄이 정확히 하나가 아닙니다.\n{report}"

    results = json.loads(lines[0])
    for phase in PHASES:
        ok, reason = judge_store_readback(
            results.get(phase), expect_positive=phase_expectation(phase)
        )
        assert ok, f"[{phase}] {reason}\n{report}"
