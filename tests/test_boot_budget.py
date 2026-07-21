"""부팅 폴백 예산(#77) — 첫 부트스트랩에만 넓히고, 그 판정이 조용히 퇴화하지 않는지.

실측 근거(설계 결정): 후보였던 '진행 증거 관찰' 안은 통제 실험에서 폐기됐다 —
loaded 미발화(응답 없는 서버)와 정상 부팅의 프로필 쓰기가 구분되지 않았다(부재 판별력 0).
그래서 판정은 관찰이 아니라 **완주 이력**이라는 선언적 사실로 내린다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.webapp import settings
from hwpxfiller.webapp.boot_budget import (
    COLD_BUDGET_SECONDS,
    WARM_BUDGET_SECONDS,
    decide,
    detect_runtime_version,
)


def test_no_completed_boot_gets_the_wide_budget() -> None:
    """완주 이력이 없으면 콜드 — 설치 후 첫 실행이 가장 느린 순간이다."""
    seconds, reason = decide("", "150.0.4078.83")
    assert seconds == COLD_BUDGET_SECONDS and "첫 실행" in reason


def test_same_runtime_after_a_completed_boot_gets_the_narrow_budget() -> None:
    """완주한 적 있는 같은 런타임은 웜 — 넓은 예산은 매달림 대기도 3배로 만든다."""
    seconds, reason = decide("150.0.4078.83", "150.0.4078.83")
    assert seconds == WARM_BUDGET_SECONDS and "있음" in reason


def test_runtime_replacement_reopens_the_wide_budget() -> None:
    """런타임이 교체되면 다시 콜드 — 업데이트 직후 첫 실행도 새 런타임을 펼친다."""
    seconds, reason = decide("149.0.0.1", "150.0.4078.83")
    assert seconds == COLD_BUDGET_SECONDS and "런타임 교체" in reason


def test_undetectable_version_after_a_completed_boot_stays_narrow() -> None:
    """버전 미검출은 콜드로 접지 않는다 — 접으면 그런 머신은 영구히 넓은 예산이다.

    대가(런타임 교체 미감지)는 모듈 docstring 에 명문화돼 있다 — 조용한 절충이 아니다.
    """
    seconds, _ = decide(settings.BOOT_STAMP_UNKNOWN_VERSION, "")
    assert seconds == WARM_BUDGET_SECONDS


def test_detect_runtime_version_never_raises() -> None:
    """예산 힌트 취득이 부팅을 죽이면 안 된다 — 못 읽으면 ``""``."""
    assert isinstance(detect_runtime_version(), str)


def test_boot_stamp_roundtrip_and_unknown_sentinel(tmp_path, monkeypatch) -> None:
    """완주 스탬프 영속 — 미검출 완주는 sentinel 로 남아 '완주한 적 없음'과 구분된다."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    assert settings.load_boot_completed() == ""            # 첫 실행
    settings.save_boot_completed("150.0.4078.83")
    assert settings.load_boot_completed() == "150.0.4078.83"
    settings.save_boot_completed("")                        # 완주했으나 버전 미검출
    assert settings.load_boot_completed() == settings.BOOT_STAMP_UNKNOWN_VERSION
    assert decide(settings.load_boot_completed(), "")[0] == WARM_BUDGET_SECONDS


@pytest.mark.parametrize("seen", ["", "150.0.4078.83", settings.BOOT_STAMP_UNKNOWN_VERSION])
def test_budget_is_always_one_of_the_two_declared_values(seen: str) -> None:
    """예산은 선언된 두 값뿐 — 판정이 임의 초로 흘러내리면 회귀를 눈으로 못 잡는다."""
    seconds, _ = decide(seen, "150.0.4078.83")
    assert seconds in (WARM_BUDGET_SECONDS, COLD_BUDGET_SECONDS)


def test_app_boot_wires_the_budget_and_stamps_only_on_completion() -> None:
    """부팅 코드가 판정을 실제로 소비한다(#77) — 리터럴 20.0 회귀·무조건 스탬프 차단.

    ①타이머가 고정 초로 돌아가면 이 모듈 전체가 죽은 코드가 되고(테스트는 계속 초록),
    ②스탬프가 loaded 밖에서 찍히면 한 번도 완주 못 한 환경이 좁은 예산을 물려받는다.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "hwpxfiller" / "webapp" / "app.py")
    text = src.read_text(encoding="utf-8")
    assert "threading.Timer(budget_seconds, _fallback_show)" in text, (
        "폴백 타이머가 판정 예산을 쓰지 않습니다(#77) — 고정 초 회귀."
    )
    i_loaded = text.index("def _apply_theme_then_show(")
    i_stamp = text.index("settings.save_boot_completed(")
    i_next = text.index("window.events.loaded +=")
    assert i_loaded < i_stamp < i_next, (
        "완주 스탬프가 loaded 핸들러 밖에 있습니다 — 완주하지 않은 부팅도 웜으로 기록됩니다."
    )
