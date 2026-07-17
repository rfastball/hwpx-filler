"""GUI 앱 설정 — 오리진 비의존 영속(``~/.hwpxfiller/settings.json``).

테마 선택 같은 셸 상태는 원래 프런트 ``localStorage`` 에 있었으나, localStorage 는
오리진(``http://127.0.0.1:<port>``) 스코프라 pywebview 의 내부 HTTP 포트가 부팅마다 바뀌면
조용히 리셋됐다(#74). 영속을 여기 Python 홈 설정으로 옮겨 오리진 결합을 끊는다 — 그 대가로
``private_mode=True`` (랜덤 포트·인메모리 프로필)를 되찾아 포트 스쿼팅·캐시 스테일·서버
크로스톡 클래스를 구조적으로 소멸시킨다(#74). 저장 위치는 레지스트리들과 같은 홈 규약
(``HWPXFILLER_HOME`` 또는 ``~/.hwpxfiller``, 예: :func:`hwpxfiller.core.job.default_jobs_dir`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

VALID_THEMES = ("system", "light", "dark")


def _settings_path() -> Path:
    """설정 파일 위치 — 홈 아래 ``settings.json``. ``HWPXFILLER_HOME`` 로 재지정 가능."""
    root = os.environ.get("HWPXFILLER_HOME") or (Path.home() / ".hwpxfiller")
    return Path(root) / "settings.json"


def _read() -> dict:
    """전체 설정 dict 반환 — 파일 부재·손상 시 빈 dict(조용한 폴백은 여기서만, 값 판독 아님)."""
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_theme() -> str:
    """저장된 테마 선택 — ``{"system","light","dark"}`` 중 하나. 미저장·비유효 시 ``"system"``."""
    theme = _read().get("theme")
    return theme if theme in VALID_THEMES else "system"


def save_theme(mode: str) -> None:
    """테마 선택 영속 — 다른 키 보존(read-modify-write) + 원자 교체.

    비유효 ``mode`` 는 조용히 무시하지 않고 ``ValueError`` (confirm-or-alarm)."""
    if mode not in VALID_THEMES:
        raise ValueError(f"유효하지 않은 테마: {mode!r} (허용: {VALID_THEMES})")
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read()
    data["theme"] = mode
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # 원자 교체 — 부분 쓰기가 판독되지 않도록
