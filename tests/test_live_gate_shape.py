"""실 WebView2 게이트의 **형상** 계약 — 콜드 부팅 수와 예산 단일 출처 (#411 CI 왕복 승계).

정책 본문과 값은 :mod:`tests._live_gate` 가 든다. 이 파일은 그 정책이 **지켜지는지**를 수집
결과로 센다 — 선언이 아니라 저장소 실물을 본다.

두 축이다.

1. **콜드 부팅은 늘지 않는다.** 실 창을 띄우는 자식 드라이버의 집합을 정확히 못박는다. 새
   게이트가 자기 창을 하나 더 띄우면 여기서 이름을 대며 붉는다 — 「기존 창에 얹어라」가
   기본이고, 굳이 늘려야 한다면 그 판단이 이 목록을 고치는 **명시 행위**로 남는다.
   (조용히 느는 것만 막는다. 늘리는 것 자체를 금지하지는 않는다 — 금지는 필요할 때
   우회를 낳고, 우회는 기록을 남기지 않는다.)
2. **예산은 파일마다 제 숫자를 들지 않는다.** 리터럴을 되찾는 순간 형제 간 자릿수 차가
   조용히 벌어진다(`test_web_selftest_gate::test_the_tightest_probe_budget_is_not_an_outlier`
   가 JS 프로브 층에서 잡는 바로 그 결함류의 Python 판).
"""

from __future__ import annotations

import re
from pathlib import Path

from _live_gate import LIVE_CHILD_TIMEOUT_S, LIVE_PROBE_BUDGET_S

TESTS_DIR = Path(__file__).resolve().parent

#: 실 창을 띄우는 자식 드라이버를 **가진** 게이트 전수. 늘리려면 이 목록을 고쳐야 하고,
#: 그 변경 자체가 「부팅 하나 = 플레이크 주사위 하나」를 한 번 더 굴리겠다는 선언이다.
KNOWN_LIVE_WINDOW_DRIVERS = frozenset({
    "test_react_root_live.py",     # R2-01 #405 — 마운트 커밋 마커
    "test_react_store_live.py",    # R2-03 #407 — push→store→React 인과와 재초기화
    "test_react_overlay_live.py",  # R3-01 #410 — overlay host 골격·직속 자식·재초기화
    "test_react_shell_live.py",    # R3-02 #411 — 셸 랜딩·동기 전환·닫기 왕복·재초기화
})

#: 예산을 공용 상수로 받는 형태. 리터럴(`= 240.0`)로 되돌아가면 이 패턴이 깨진다.
_SHARED_BUDGET_BINDINGS = (
    "_PROBE_BUDGET_S = LIVE_PROBE_BUDGET_S",
    "_CHILD_TIMEOUT_S = LIVE_CHILD_TIMEOUT_S",
)

#: 관측된 정상값의 자릿수 — CI 정상 live 잡은 부팅 하나당 20~30 초다(#411 실측). 예산이
#: 그 언저리로 내려오면 「느림」이 빨강이 되기 시작한다. 이 하한은 그 퇴행의 문지기다.
_OBSERVED_NORMAL_BOOT_S = 30.0


def _window_driver_files() -> set[str]:
    """실물 수집 — 자식 드라이버 안에서 실제로 창을 만드는 파일만 센다.

    `create_window` 문자열을 **언급**하는 파일(app.py 원문을 단언하는 정적 계약들)과
    구분하는 것이 요점이다: 언급은 부팅을 만들지 않는다.
    """
    found: set[str] = set()
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        driver = re.search(r'^_CHILD_DRIVER = """(.*?)"""', text, re.DOTALL | re.MULTILINE)
        if driver is not None and "webview.create_window" in driver.group(1):
            found.add(path.name)
    return found


def test_the_collector_actually_finds_drivers() -> None:
    """양성 대조 — 아래 폐포가 「수집 0 이라 언제나 초록」이 아님을 먼저 세운다."""
    found = _window_driver_files()

    assert found, "자식 드라이버를 한 장도 못 읽었습니다 — 수집기가 헛돕니다."


def test_cold_boot_count_does_not_grow_silently() -> None:
    """실 창을 띄우는 게이트 전수가 등재와 정확히 같다.

    부팅 하나는 러너에서 플레이크 주사위 하나다(`packaging/build.ps1` 의
    `webview_boot_flake` 가 패키징 쪽에서 먼저 만난 그 계열). 단계마다 게이트를 하나씩
    더 띄우면 한 run 이 전부 초록일 확률은 단조 감소한다.
    """
    found = _window_driver_files()

    assert found == set(KNOWN_LIVE_WINDOW_DRIVERS), (
        "실 창 자식 드라이버 전수가 등재와 다릅니다.\n"
        f"  등재에만: {sorted(set(KNOWN_LIVE_WINDOW_DRIVERS) - found)}\n"
        f"  실물에만: {sorted(found - set(KNOWN_LIVE_WINDOW_DRIVERS))}\n"
        "새 실런타임 단언은 **기존 게이트의 창에 얹는 것**이 기본입니다"
        "(tests/_live_gate.py 정책 1 — test_web_selftest_gate 가 창 둘로 단언 80 을 뽑습니다). "
        "그래도 새 창이 필요하면 KNOWN_LIVE_WINDOW_DRIVERS 를 사유와 함께 고치세요."
    )


def test_every_live_gate_takes_its_budget_from_the_single_source() -> None:
    """예산 리터럴이 게이트로 되돌아오지 않았다 — 값은 `_live_gate` 한 곳에서만 산다."""
    offenders: list[str] = []
    for name in sorted(KNOWN_LIVE_WINDOW_DRIVERS):
        text = (TESTS_DIR / name).read_text(encoding="utf-8")
        for binding in _SHARED_BUDGET_BINDINGS:
            if binding not in text:
                offenders.append(f"  {name}: `{binding}` 결속이 없습니다")
        if re.search(r"_(?:PROBE_BUDGET|CHILD_TIMEOUT)_S\s*=\s*[0-9]", text):
            offenders.append(f"  {name}: 예산을 리터럴로 되돌렸습니다")

    assert not offenders, (
        "실 게이트가 예산을 제 숫자로 듭니다(형제 간 자릿수 차가 조용히 벌어집니다):\n"
        + "\n".join(offenders)
    )


def test_the_shared_budget_stays_generous() -> None:
    """공용 예산이 관측 정상값의 자릿수로 내려오지 않았다.

    예산이 하는 일은 매달림을 유한 시간에 빨강으로 만드는 것이지 느린 러너를 탈락시키는
    것이 아니다 — 느림으로 난 빨강은 정보가 0 이고 재주행 비용만 남긴다(#411 CI 왕복).
    """
    assert LIVE_PROBE_BUDGET_S >= _OBSERVED_NORMAL_BOOT_S * 5, (
        f"폴링 예산 {LIVE_PROBE_BUDGET_S}s 가 관측 정상 부팅({_OBSERVED_NORMAL_BOOT_S}s)의 "
        "자릿수에 가깝습니다 — 느린 러너가 빨강이 되기 시작합니다."
    )
    assert LIVE_CHILD_TIMEOUT_S >= LIVE_PROBE_BUDGET_S + 60.0, (
        f"자식 상한 {LIVE_CHILD_TIMEOUT_S}s 가 폴링 예산 {LIVE_PROBE_BUDGET_S}s 에 너무 붙어 "
        "있습니다 — 바깥 상한이 안쪽 진단보다 먼저 물면 매달림이 「출력 0」으로 뭉개집니다."
    )
