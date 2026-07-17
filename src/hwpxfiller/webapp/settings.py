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


def home_dir() -> Path:
    """앱 홈 — ``HWPXFILLER_HOME`` 또는 ``~/.hwpxfiller`` (레지스트리들과 같은 규약)."""
    root = os.environ.get("HWPXFILLER_HOME") or (Path.home() / ".hwpxfiller")
    return Path(root)


def _settings_path() -> Path:
    """설정 파일 위치 — 홈 아래 ``settings.json``."""
    return home_dir() / "settings.json"


def _read() -> dict:
    """전체 설정 dict 반환 — 파일 부재·손상 시 빈 dict(조용한 폴백은 여기서만, 값 판독 아님)."""
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_for_update(path: Path) -> dict:
    """RMW 판독 — 부재·JSON 손상은 빈 dict 로 새 출발(손상 파일 위에 유효 내용을 쓰는 게 복구),
    그 외 OSError(잠김·권한)는 전파한다: 빈 dict 로 접으면 일시 장애가 다른 키 전멸로 조용히
    승격된다(read-modify-write 약속 위반, confirm-or-alarm)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except ValueError:
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
    data = _read_for_update(path)
    data["theme"] = mode
    # tmp 이름에 pid — 동시 실행 인스턴스(#74 지원 상태)가 같은 tmp 를 겹쳐 쓰면 한쪽 replace 가
    # FileNotFoundError 로 사용자 alert 까지 튄다. 프로세스별 이름이면 각자 원자 교체로 수렴.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # 원자 교체 — 부분 쓰기가 판독되지 않도록
