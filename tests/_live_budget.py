"""`live-webview2` 잡의 예산 산술 — **단일 출처**(#912).

이 잡의 바깥 상한(`timeout-minutes: 60`)이 정당한지는 그 아래 phase 예산들의 **합**이
결정한다. 그런데 종전에는 그 합(2955s = 49.25분)이 서로를 가리키는 세 개의 산문 주석에
손으로 복사돼 있었다:

- `.github/workflows/quality.yml` 의 live-webview2 주석 — 항을 나열하고 합을 적었다,
- `tests/test_web_selftest_gate.py` 의 합계 예산 주석 — 같은 합을 적고 「산술 정본은
  워크플로 주석」이라 선언했다(그 주석은 이 파일의 상수를 읽지 않았으므로 순환이었다),
- `tests/repo_contract/test_quality_workflow.py` 의 주석 — 같은 합을 세 번째로 적었다.

실제로 **실행되는** 검증은 `live["timeout-minutes"] == "60"` 리터럴 하나뿐이었다. 즉 어느
항을 늘려도(온보딩 여정 720s 가 실제로 그랬다) 합은 아무도 다시 계산하지 않았고, 세 주석은
사람이 셋 다 고칠 때만 맞았다. 「같은 상태를 두 곳이 판정하게 만들지 않는다」의 예산판이다.

그래서 항과 합을 여기 값으로 세우고, `tests/repo_contract/test_quality_workflow.py` 가
YAML 실값을 이 합과 **기계로** 견준다.

이 모듈은 `test_*` 가 아니라 pytest 가 수집하지 않는다(`tests/_web_source.py` 와 같은
역할·같은 이름 규약). 상수와 파생 함수만 살고, 하니스(`scripts/live101/`)를 import 하지
않아 어느 lane 에서도 값싸게 읽힌다.
"""

from __future__ import annotations

from hwpxfiller.webapp.boot_budget import COLD_BUDGET_SECONDS
from hwpxfiller.webapp.live_run import RUN_HARD_STOP_MARGIN_S

__all__ = [
    "SELFTEST_AGGREGATE_BOOT_S",
    "SELFTEST_HARNESS_MARGIN_S",
    "LIVE101_BOOT_GRACE_S",
    "QUALIFIED_COLD_BOOT_FAILURE_S",
    "LIVE101_OUTER_SLACK_S",
    "LIVE101_JOURNEY_BUDGET_S",
    "LIVE101_RESTART_BUDGET_S",
    "LIVE101_ONBOARDING_BUDGET_S",
    "outer",
    "LIVE_WEBVIEW2_WORST_CASE_S",
    "LIVE_WEBVIEW2_TIMEOUT_MINUTES",
    "LIVE_WEBVIEW2_WORST_CASE_TERMS",
    "LIVE_WEBVIEW2_HEADROOM_RATIO",
]

# ───────────────────────── selftest 게이트(`tests/test_web_selftest_gate.py`) ─────────────────────────

#: 부팅 **하나**의 상한에 얹는 부모 진단 여유(#477).
#:
#: 여유는 「러너가 이만큼은 느릴 수 있다」는 인내가 아니라 **판별 불능 구간의 정직한 폭**이다.
#: 상한이 무는 순간 "명백히 멈췄다"라고 말할 수 있어야 하므로 실측 최악(콜드 부팅 76.9초·
#: 40배 감속 여정)을 훨씬 웃돈다. 그 아래 구간의 성능은 차단이 아니라 보고의 몫이다.
SELFTEST_HARNESS_MARGIN_S = 400.0

#: 그 게이트가 태우는 **모든** 부팅의 합계 상한(#428 리뷰 P1 · #477).
#:
#: 부팅 하나의 상한을 늘리면 최악의 경우가 곱해진다 — 파라미터화 포함 십수 회 부팅하고
#: pytest 는 시한 초과 뒤에도 다음 테스트로 간다. 합계에 상한이 없으면 WebView2 전면 매달림
#: 하나가 잡 상한을 넘겨 `if: always()` 증거 회수 전에 러너가 잡을 죽인다.
#:
#: 최악 대기가 이 값으로 **유계**인 것이 요점이다: 매달림 한 번 뒤 남은 예산이 부팅 하나
#: 몫 아래로 떨어지면 나머지가 즉시 실패하므로, 대기 총량 ≤ 이 값이다.
SELFTEST_AGGREGATE_BOOT_S = 1200.0

# ───────────────────────── 101 실주행(`tests/test_quickstart_101_live.py`) ─────────────────────────

#: 하니스가 부팅 예산 위에 얹는 유예 — 정본은 `scripts/live101/driver.BOOT_GRACE_S` 다.
#:
#: 이 모듈은 하니스를 import 하지 않으므로 값을 여기 두되, **드리프트는 침묵하지 않는다**:
#: `tests/test_quickstart_101_live.py` 가 실 `driver.BOOT_GRACE_S` 와 같은지 단언한다.
LIVE101_BOOT_GRACE_S = 15.0

#: 실 창이 끝내 뜨지 않았을 때의 **qualified** 실패까지 걸리는 시간.
#:
#: 종전에는 어느 상수도 아니고 워크플로 주석의 산문 「75s」로만 있었다. 실제로는 파생값이다 —
#: 콜드 부팅 예산이 소진되고 하니스 유예까지 지난 뒤에야 「환경」으로 판정하기 때문이다.
QUALIFIED_COLD_BOOT_FAILURE_S = COLD_BUDGET_SECONDS + LIVE101_BOOT_GRACE_S

#: 바깥 시한이 안쪽 하드 스톱 위에 두는 여유 — 드라이버가 구조화된 착지를 **끝낼** 시간.
LIVE101_OUTER_SLACK_S = 60.0

#: 101 완주 여정의 안쪽 예산(#477). 「명백히 멈춘 것」만 잡는 천장이지 성능 축이 아니다.
LIVE101_JOURNEY_BUDGET_S = 600.0

#: same-home restart(SX-05)의 안쪽 예산.
LIVE101_RESTART_BUDGET_S = 120.0

#: 온보딩 여정(#895)의 안쪽 예산. 실측 완주 77.5초(2026-08-25, 개발 기기).
LIVE101_ONBOARDING_BUDGET_S = 600.0


def outer(budget_s: float) -> float:
    """안쪽 예산 하나에서 **바깥** 시한(`subprocess.run(timeout=...)`)을 파생한다.

    예산 둘의 **순서가 계약이다**(#430 리뷰): 바깥 시한이 안쪽 하드 스톱보다 촘촘하면 CLI 가
    먼저 죽어 드라이버의 구조화된 착지가 통째로 사라지고, 남는 것은 맨 `TimeoutExpired`
    하나다 — 보고서도, 실패 항목도, 매달림 스택도 없다. 그래서 안쪽이 먼저 물게 파생시킨다.
    """
    return budget_s + RUN_HARD_STOP_MARGIN_S + LIVE101_OUTER_SLACK_S


# ───────────────────────────── 잡 상한 ─────────────────────────────

#: 최악 대기의 항 — 실패 메시지가 「어느 항이 합을 밀었나」를 말할 수 있게 이름과 함께 둔다.
LIVE_WEBVIEW2_WORST_CASE_TERMS: "tuple[tuple[str, float], ...]" = (
    ("selftest 합계", SELFTEST_AGGREGATE_BOOT_S),
    ("qualified 콜드부팅 실패", QUALIFIED_COLD_BOOT_FAILURE_S),
    ("101 바깥 상한", outer(LIVE101_JOURNEY_BUDGET_S)),
    ("same-home restart 바깥 상한", outer(LIVE101_RESTART_BUDGET_S)),
    ("온보딩 여정 바깥 상한", outer(LIVE101_ONBOARDING_BUDGET_S)),
)

#: 위 항의 합 — 전부 **매달림 상한**이지 정상 실행 시간이 아니다.
LIVE_WEBVIEW2_WORST_CASE_S = sum(seconds for _, seconds in LIVE_WEBVIEW2_WORST_CASE_TERMS)

#: `.github/workflows/quality.yml` 의 live-webview2 `timeout-minutes` 실값.
LIVE_WEBVIEW2_TIMEOUT_MINUTES = 60

#: 잡 상한이 최악 합보다 이만큼은 성겨야 한다 — 상한이 무는 순간이 테스트별 하드스톱보다
#: 먼저면 `if: always()` 증거 회수 전에 러너가 잡을 죽인다.
LIVE_WEBVIEW2_HEADROOM_RATIO = 0.9
