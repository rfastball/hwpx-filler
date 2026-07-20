"""웹앱 설정(테마 영속) 단위 가드 — ``hwpxfiller.webapp.settings`` (#74).

리뷰(PR #75)가 드러낸 결함류를 회귀 차단한다:
- read-modify-write 약속: 다른 키를 보존해야 하고, **일시 판독 장애(OSError)를 빈 dict 로
  접어 다른 키를 조용히 전멸시키면 안 된다**(confirm-or-alarm — 실패는 전파).
- 손상(JSON) 파일은 어차피 판독 불능 — 유효 내용으로 덮는 것이 복구(조용한 예외).
- 비유효 테마는 ValueError(조용한 무시 금지).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwpxfiller.webapp import settings


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    return tmp_path


def test_load_theme_defaults_to_system(home):
    assert settings.load_theme() == "system"
    (home / "settings.json").write_text('{"theme": "그밖"}', encoding="utf-8")
    assert settings.load_theme() == "system"  # 비유효 저장값도 조용한 폴백은 판독뿐(부팅 불사)


def test_save_theme_roundtrip_and_invalid_raises(home):
    settings.save_theme("dark")
    assert settings.load_theme() == "dark"
    with pytest.raises(ValueError):
        settings.save_theme("네온")


def test_save_theme_preserves_other_keys(home):
    (home / "settings.json").write_text(
        json.dumps({"theme": "light", "future_key": [1, 2]}), encoding="utf-8")
    settings.save_theme("dark")
    data = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    assert data == {"theme": "dark", "future_key": [1, 2]}


def test_save_theme_recovers_over_corrupt_file(home):
    (home / "settings.json").write_text("{잘림", encoding="utf-8")
    settings.save_theme("light")
    assert settings.load_theme() == "light"


def test_save_theme_propagates_unreadable_file(home):
    # settings.json 이 '있는데 못 읽는' 상태(디렉터리로 위장 = OSError, FileNotFoundError 아님).
    # 빈 dict 로 접으면 다른 키가 조용히 전멸하므로 반드시 시끄럽게 전파돼야 한다.
    (home / "settings.json").mkdir()
    with pytest.raises(OSError):
        settings.save_theme("dark")


def test_save_theme_routes_through_canonical_atomic_write(home, monkeypatch):
    """durable 쓰기는 정본 hwpxcore.atomic 을 지나야 한다(#75 리뷰) — 수제 tmp+replace 는
    실패 시 고아 tmp 를 영구히 남기고, 같은 pid 의 두 스레드가 같은 tmp 를 겹쳐 쓴다."""
    calls: list[str] = []
    real = settings.write_text_atomic

    def spy(path, text, *a, **k):
        calls.append(Path(path).name)
        return real(path, text, *a, **k)

    monkeypatch.setattr(settings, "write_text_atomic", spy)
    settings.save_theme("dark")
    assert calls == ["settings.json"]
    assert settings.load_theme() == "dark"
    assert not list(home.glob("settings.json*.tmp"))  # 교체 후 잔여 tmp 없음


def test_save_theme_retries_transient_permission_error(home, monkeypatch):
    """다른 인스턴스(#74 지원 상태)가 읽는 순간의 교체는 PermissionError(Windows 공유 위반) —
    일시 충돌은 재시도로 흡수해야 하고(사용자 alert 승격 금지), 지속 실패만 전파한다(#75 리뷰)."""
    real = settings.write_text_atomic
    remaining = {"fails": 2}

    def flaky(path, text, *a, **k):
        if remaining["fails"] > 0:
            remaining["fails"] -= 1
            raise PermissionError(13, "공유 위반 모사")
        return real(path, text, *a, **k)

    monkeypatch.setattr(settings, "write_text_atomic", flaky)
    monkeypatch.setattr(settings.time, "sleep", lambda s: None)
    settings.save_theme("dark")
    assert settings.load_theme() == "dark"

    def always_fails(path, text, *a, **k):
        raise PermissionError(13, "지속 실패 모사")

    monkeypatch.setattr(settings, "write_text_atomic", always_fails)
    with pytest.raises(PermissionError):
        settings.save_theme("light")


def test_load_theme_retries_transient_read_error(home, monkeypatch):
    """일시 판독 장애(AV 스캔·원자 교체 순간의 공유 위반)는 재시도로 흡수하고, 저장 테마를
    조용한 'system' 리셋으로 승격하지 않는다(#75 리뷰 #6 — save 재시도와 대칭)."""
    settings.save_theme("dark")
    real_read_text = Path.read_text
    remaining = {"fails": 2}

    def flaky_read_text(self, *a, **k):
        if self.name == "settings.json" and remaining["fails"] > 0:
            remaining["fails"] -= 1
            raise PermissionError(13, "공유 위반 모사")
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(settings.time, "sleep", lambda s: None)
    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    assert settings.load_theme() == "dark"  # 일시 실패를 넘겨 저장값 회수(리셋 아님)


def test_load_theme_persistent_read_error_alarms_then_falls_back(home, monkeypatch):
    """지속 판독 실패는 재시도를 거친 뒤 'system' 으로 접되(테마 하나로 부팅 불사), **조용히
    넘기지 않고 경보한다**(#75 리뷰4 #2) — 조용한 리셋은 저장 선택의 무단 소실이다."""
    settings.save_theme("dark")
    real_read_text = Path.read_text

    def always_fails(self, *a, **k):
        if self.name == "settings.json":
            raise PermissionError(13, "지속 실패 모사")
        return real_read_text(self, *a, **k)

    alerts: list[str] = []
    monkeypatch.setattr(settings, "alert", lambda m: alerts.append(m))
    monkeypatch.setattr(settings.time, "sleep", lambda s: None)
    monkeypatch.setattr(Path, "read_text", always_fails)
    assert settings.load_theme() == "system"
    assert alerts and "판독" in alerts[0]  # 시끄러운 경보가 실제로 났다


def test_save_theme_retries_transient_read_share_violation(home, monkeypatch):
    """토글 순간의 일시 읽기 공유위반(RMW 재판독)도 재시도로 흡수해야 한다 — 쓰기만 관대하고
    그 직전 읽기는 spurious alert 로 승격되던 비대칭을 닫는다(#75 리뷰4 #4)."""
    settings.save_theme("light")  # 시드(다른 키 보존 확인용은 아니지만 파일 존재)
    real_read_text = Path.read_text
    remaining = {"fails": 2}

    def flaky_read(self, *a, **k):
        if self.name == "settings.json" and remaining["fails"] > 0:
            remaining["fails"] -= 1
            raise PermissionError(13, "읽기 공유 위반 모사")
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(settings.time, "sleep", lambda s: None)
    monkeypatch.setattr(Path, "read_text", flaky_read)
    settings.save_theme("dark")  # 재판독이 2회 튕겨도 재시도로 흡수 → 성공(예외 전파 없음)
    monkeypatch.setattr(Path, "read_text", real_read_text)
    assert settings.load_theme() == "dark"


# ------------------------------------------------ 대상 글꼴 선언 영속(R-flow 블록 3 결정 17)
def test_draft_font_defaults_to_gulimche(home):
    assert settings.load_draft_target_font() == "gulimche"  # 고정폭 표준 = 린트 침묵 기본
    (home / "settings.json").write_text('{"draft_target_font": "바탕체"}', encoding="utf-8")
    assert settings.load_draft_target_font() == "gulimche"  # 비유효 저장값도 조용한 폴백은 판독뿐


def test_draft_font_roundtrip_and_invalid_raises(home):
    settings.save_draft_target_font("malgun")
    assert settings.load_draft_target_font() == "malgun"
    with pytest.raises(ValueError):
        settings.save_draft_target_font("굴림")  # 열거형 밖은 조용한 무시 금지


def test_draft_font_preserves_other_keys(home):
    settings.save_theme("dark")
    settings.save_draft_target_font("dotumche")
    assert settings.load_theme() == "dark"  # RMW — 서로 다른 키 보존
    settings.save_theme("light")
    assert settings.load_draft_target_font() == "dotumche"


# ------------------------------------------------ 「작업」 그룹 접힘 영속(결정 43·R-info 결정 6)
def test_collapsed_groups_default_empty_and_roundtrip(home):
    assert settings.load_job_collapsed_groups() == []  # 무상태 기본 = 전부 펼침
    settings.save_job_collapsed_groups(["나", "가", "가", ""])  # ""=「그룹 없음」 구획
    assert settings.load_job_collapsed_groups() == ["", "가", "나"]  # 정렬·중복 제거 정규화


def test_collapsed_groups_preserve_theme_and_vice_versa(home):
    settings.save_theme("dark")
    settings.save_job_collapsed_groups(["입찰"])
    assert settings.load_theme() == "dark"  # RMW — 서로 다른 키 보존
    settings.save_theme("light")
    assert settings.load_job_collapsed_groups() == ["입찰"]


def test_collapsed_groups_invalid_arg_is_loud(home):
    with pytest.raises(ValueError):
        settings.save_job_collapsed_groups("입찰")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        settings.save_job_collapsed_groups(["입찰", 3])  # type: ignore[list-item]


def test_collapsed_groups_corrupt_value_falls_back_to_expanded(home):
    (home / "settings.json").write_text(
        json.dumps({"job_collapsed_groups": "입찰", "theme": "dark"}), encoding="utf-8")
    assert settings.load_job_collapsed_groups() == []  # 비리스트 = 전부 펼침(부팅 불사)
    (home / "settings.json").write_text(
        json.dumps({"job_collapsed_groups": ["입찰", 3, None]}), encoding="utf-8")
    assert settings.load_job_collapsed_groups() == ["입찰"]  # 부분 손상은 항목만 걸러낸다


def test_proportional_font_is_single_source(home):
    """비례폭 판정은 설정 모듈 소유 — 표면·컨트롤러가 글꼴 이름으로 재판별하지 않는다(결정 17)."""
    assert settings.is_proportional_font("malgun") is True
    assert settings.is_proportional_font("gulimche") is False
    assert settings.is_proportional_font("dotumche") is False
    # 비례폭 목록은 유효 열거형의 부분집합이어야 한다(오타 방지).
    assert set(settings.PROPORTIONAL_DRAFT_FONTS) <= set(settings.VALID_DRAFT_FONTS)
