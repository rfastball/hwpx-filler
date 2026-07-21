"""홈 경로 단일 출처(#76) — 해석 규약과 위임 대칭.

``tests/conftest.py`` 가 autouse 로 ``HWPXFILLER_HOME`` 을 임시 홈에 못박으므로, 미설정
경우를 보려면 여기서 명시적으로 지운다(실 사용자 홈은 읽기만 하고 만들지 않는다).
"""

from __future__ import annotations

from pathlib import Path

from hwpxfiller.core.dataset_pool import default_dataset_pool_dir
from hwpxfiller.core.job import default_jobs_dir
from hwpxfiller.core.paths import home_dir
from hwpxfiller.core.template_status import default_templates_dir
from hwpxfiller.core.text_registry import default_text_templates_dir
from hwpxfiller.webapp import settings


def test_env_override_wins(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "elsewhere"))
    assert home_dir() == tmp_path / "elsewhere"


def test_unset_falls_back_to_user_home(monkeypatch) -> None:
    monkeypatch.delenv("HWPXFILLER_HOME", raising=False)
    assert home_dir() == Path.home() / ".hwpxfiller"


def test_empty_override_is_treated_as_unset(monkeypatch) -> None:
    """빈 값이 상대경로(현재 작업 디렉터리)로 해석돼 홈이 repo 안으로 들어오면 안 된다."""
    monkeypatch.setenv("HWPXFILLER_HOME", "")
    assert home_dir() == Path.home() / ".hwpxfiller"


def test_all_default_roots_share_one_home(monkeypatch, tmp_path: Path) -> None:
    """5개 소비자가 같은 홈을 본다 — 재지정 뒤 하나라도 딴 곳을 보면 조용한 갈라짐(#76)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    assert default_jobs_dir() == home / "jobs"
    assert default_dataset_pool_dir() == home / "datasets"
    assert default_templates_dir() == home / "templates"
    assert default_text_templates_dir() == home / "text_templates"
    assert settings._settings_path() == home / "settings.json"


def test_settings_home_dir_is_the_shared_helper() -> None:
    """``settings.home_dir`` 는 재노출일 뿐 별도 구현이 아니다(app.py 가 이 이름으로 부른다)."""
    assert settings.home_dir is home_dir
