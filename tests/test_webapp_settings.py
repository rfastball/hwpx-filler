"""웹앱 설정(테마 영속) 단위 가드 — ``hwpxfiller.webapp.settings`` (#74).

리뷰(PR #75)가 드러낸 결함류를 회귀 차단한다:
- read-modify-write 약속: 다른 키를 보존해야 하고, **일시 판독 장애(OSError)를 빈 dict 로
  접어 다른 키를 조용히 전멸시키면 안 된다**(confirm-or-alarm — 실패는 전파).
- 손상(JSON) 파일은 어차피 판독 불능 — 유효 내용으로 덮는 것이 복구(조용한 예외).
- 비유효 테마는 ValueError(조용한 무시 금지).
"""
from __future__ import annotations

import json

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


def test_save_theme_tmp_name_is_per_process(home):
    """동시 실행 인스턴스(#74 지원 상태)가 같은 tmp 를 겹쳐 쓰면 한쪽 replace 가
    FileNotFoundError 로 사용자 alert 까지 튄다 — tmp 이름은 프로세스 고유여야 한다."""
    from pathlib import Path

    src = Path(settings.__file__).read_text(encoding="utf-8")
    assert "os.getpid()" in src.split("def save_theme")[1], (
        "save_theme 의 tmp 파일명에 pid 가 없습니다 — 동시 실행 교체 경합(#75 리뷰).")
    settings.save_theme("dark")
    assert not list(home.glob("settings.json.*.tmp"))  # 교체 후 잔여 tmp 없음
    assert settings.load_theme() == "dark"
