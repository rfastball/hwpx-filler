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
import re
import time
from pathlib import Path

from hwpxcore.atomic import write_text_atomic

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


_REPLACE_RETRIES = 5  # Windows 공유 위반(아래) 일시 충돌 흡수 상한 — 총 ~0.5s


def save_theme(mode: str) -> None:
    """테마 선택 영속 — 다른 키 보존(read-modify-write) + 원자 교체(정본 write_text_atomic).

    비유효 ``mode`` 는 조용히 무시하지 않고 ``ValueError`` (confirm-or-alarm).

    Windows 교체 경합: 다른 인스턴스(#74 지원 상태)가 settings.json 을 읽는 순간의 교체는
    PermissionError(공유 위반 — CPython 은 FILE_SHARE_DELETE 없이 연다)로 튄다. 아무 문제
    없는 일시 충돌이 사용자 alert 로 승격되지 않도록 유계 재시도 후에만 전파한다."""
    if mode not in VALID_THEMES:
        raise ValueError(f"유효하지 않은 테마: {mode!r} (허용: {VALID_THEMES})")
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(_REPLACE_RETRIES):
        data = _read_for_update(path)  # 재시도마다 재판독 — 경합 상대가 갱신한 다른 키를 보존
        data["theme"] = mode
        try:
            write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


# 구판 localStorage 값의 LevelDB 물리 표현 — 레코드는 키 바이트 직후(.ldb 는 0바이트,
# .log 는 값 길이 varint 1바이트 간격)에 값(``\x01`` 접두 + UTF-8)이 온다 → 유계 간격 스캔.
_LEGACY_THEME_RECORD = re.compile(rb"hwpxfiller\.theme.{0,8}?\x01(system|light|dark)", re.DOTALL)


def migrate_legacy_theme(legacy_leveldb_dir: Path) -> "str | None":
    """구판(#74 이전) 영속처에서 저장 테마를 일회 이관 — 업그레이드의 조용한 설정 소실 방지.

    구판은 고정 오리진(``http://127.0.0.1:42001``)의 localStorage ``hwpxfiller.theme`` 에
    저장했다(프로필 = 홈/webview). 신판 ``settings.json`` 에 ``theme`` 키가 없고 구 프로필이
    남아 있으면 LevelDB 파일에서 마지막 기록을 회수해 저장한다 — mtime 오름차순 × 파일 내
    마지막 매치가 최신 기록이다.

    반환: 이관·저장된 테마, 이관 대상 없으면 ``None``. 실패(예외)는 호출부가 경보한다."""
    if "theme" in _read():
        return None  # 신판 값이 이미 있다 — 구판이 이겨선 안 된다
    if not legacy_leveldb_dir.is_dir():
        return None
    try:
        files = sorted(legacy_leveldb_dir.iterdir(), key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    found: "str | None" = None
    for f in files:
        if f.suffix not in (".log", ".ldb"):
            continue
        try:
            blob = f.read_bytes()
        except OSError:
            continue
        for m in _LEGACY_THEME_RECORD.finditer(blob):
            found = m.group(1).decode("ascii")
    if found is None:
        return None
    save_theme(found)
    return found
