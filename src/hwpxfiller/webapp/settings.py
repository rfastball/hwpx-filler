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
import time
from pathlib import Path

from hwpxcore.atomic import write_text_atomic

VALID_THEMES = ("system", "light", "dark")

_READ_RETRIES = 5   # 일시 판독 충돌(AV 스캔·원자 교체 순간의 공유 위반) 흡수 상한 — save 측과 대칭
_REPLACE_RETRIES = 5  # Windows 공유 위반(아래) 일시 충돌 흡수 상한 — 총 ~0.5s


def home_dir() -> Path:
    """앱 홈 — ``HWPXFILLER_HOME`` 또는 ``~/.hwpxfiller`` (레지스트리들과 같은 규약)."""
    root = os.environ.get("HWPXFILLER_HOME") or (Path.home() / ".hwpxfiller")
    return Path(root)


def _settings_path() -> Path:
    """설정 파일 위치 — 홈 아래 ``settings.json``."""
    return home_dir() / "settings.json"


def _parse_settings(text: str) -> dict:
    """JSON 파싱 + dict 검증 — 손상(비-JSON·비-dict)은 빈 dict(복구 새 출발). ``_read`` ·
    ``_read_for_update`` 공용 파서(#75 리뷰 #8): 직렬화 형식 변경 시 한 곳만 고치면 된다."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _read() -> dict:
    """전체 설정 dict 반환 — 부재는 빈 dict(첫 실행). **일시 OSError 는 유계 재시도 후에만**
    폴백한다: AV 스캔·원자 교체 순간의 공유 위반 같은 일시 판독 장애가 저장 테마의 조용한
    'system' 리셋으로 승격되지 않게(#75 리뷰 #6, confirm-or-alarm). save_theme 재시도와 대칭 —
    지속 실패만 빈 dict 로 접되(부팅을 테마 하나로 죽일 순 없다) 그 전에 재시도를 거친다."""
    path = _settings_path()
    for attempt in range(_READ_RETRIES):
        try:
            return _parse_settings(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}  # 첫 실행 — 재시도 무의미
        except OSError:
            if attempt == _READ_RETRIES - 1:
                return {}
            time.sleep(0.05 * (attempt + 1))
    return {}


def _read_for_update(path: Path) -> dict:
    """RMW 판독 — 부재·JSON 손상은 빈 dict 로 새 출발(손상 파일 위에 유효 내용을 쓰는 게 복구),
    그 외 OSError(잠김·권한)는 전파한다: 빈 dict 로 접으면 일시 장애가 다른 키 전멸로 조용히
    승격된다(read-modify-write 약속 위반, confirm-or-alarm)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return _parse_settings(text)


def load_theme() -> str:
    """저장된 테마 선택 — ``{"system","light","dark"}`` 중 하나. 미저장·비유효 시 ``"system"``."""
    theme = _read().get("theme")
    return theme if theme in VALID_THEMES else "system"


def save_theme(mode: str) -> None:
    """테마 선택 영속 — 다른 키 보존(read-modify-write) + 원자 교체(정본 write_text_atomic).

    비유효 ``mode`` 는 조용히 무시하지 않고 ``ValueError`` (confirm-or-alarm).

    교체 경합(방어적): 앱은 홈당 단일 인스턴스(app.py 뮤텍스 가드)라 교차-프로세스 경합은
    구조적으로 없지만, AV 스캔 등 일시 파일 잠금이 원자 교체를 PermissionError(공유 위반 —
    CPython 은 FILE_SHARE_DELETE 없이 연다)로 튕길 수 있다. 아무 문제 없는 일시 충돌이 사용자
    alert 로 승격되지 않도록 유계 재시도 후에만 전파한다."""
    if mode not in VALID_THEMES:
        raise ValueError(f"유효하지 않은 테마: {mode!r} (허용: {VALID_THEMES})")
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(_REPLACE_RETRIES):
        data = _read_for_update(path)  # 재시도마다 재판독 — 손상·갱신된 다른 키를 보존
        data["theme"] = mode
        try:
            write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
