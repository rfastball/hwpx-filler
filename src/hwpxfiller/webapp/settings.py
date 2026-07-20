"""GUI 앱 설정 — 오리진 비의존 영속(``~/.hwpxfiller/settings.json``).

테마 선택 같은 셸 상태는 원래 프런트 ``localStorage`` 에 있었으나, localStorage 는
오리진(``http://127.0.0.1:<port>``) 스코프라 pywebview 의 내부 HTTP 포트가 부팅마다 바뀌면
조용히 리셋됐다(#74). 영속을 여기 Python 홈 설정으로 옮겨 오리진 결합을 끊는다 — 그 대가로
``private_mode=True`` (랜덤 포트·인메모리 프로필)를 되찾아 포트 스쿼팅·캐시 스테일·서버
크로스톡 클래스를 구조적으로 소멸시킨다(#74). 저장 위치는 레지스트리들과 같은 홈 규약
(``HWPXFILLER_HOME`` 또는 ``~/.hwpxfiller``, 예: :func:`hwpxfiller.core.job.default_jobs_dir`).
"""

from __future__ import annotations

import datetime
import json
import os
import sys
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


def alert(msg: str) -> None:
    """내구성 경보 채널 — stderr + 홈 ``webapp-alerts.log``. 창(JS alert) 계층은 app._alarm 이
    이 위에 얹는다. settings 계층이 소유하는 이유: 홈 경로·경보 로그가 여기 있고, 이 모듈이 app 을
    import 하면 순환(app→settings)이다. 동결 exe 는 console=False 라 stderr 가 소실되므로 홈 로그가
    유일하게 남는 채널 — confirm-or-alarm 이 공집합 채널로 무력화되지 않게 반드시 파일에 남긴다."""
    print(f"[hwpx] {msg}", file=sys.stderr)
    try:
        log_path = home_dir() / "webapp-alerts.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        pass  # 로그 채널 자체의 실패로 부팅/저장을 막지 않는다 — stderr 는 이미 시도됨


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
    'system' 리셋으로 승격되지 않게(#75 리뷰 #6, confirm-or-alarm). save_theme 재시도와 대칭.

    재시도를 소진한 **지속** 실패는 빈 dict 로 접되(부팅을 테마 하나로 죽일 순 없다) 조용히
    넘기지 않고 시끄럽게 알린다(#75 리뷰4 #2) — 조용한 리셋은 곧 저장 선택의 무단 소실이다."""
    path = _settings_path()
    last_exc: "OSError | None" = None
    for attempt in range(_READ_RETRIES):
        try:
            return _parse_settings(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}  # 첫 실행 — 재시도·경보 무의미
        except OSError as exc:
            last_exc = exc
            if attempt < _READ_RETRIES - 1:
                time.sleep(0.05 * (attempt + 1))
    alert(f"설정 판독 지속 실패 — 테마 등 저장값을 회수 못 하고 기본값으로 진행: {last_exc!r}")
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


def _save_key(key: str, value) -> None:
    """단일 키 영속 공용 몸통 — 다른 키 보존(read-modify-write) + 원자 교체(정본 write_text_atomic).

    교체 경합(방어적): 앱은 홈당 단일 인스턴스(app.py 뮤텍스 가드)라 교차-프로세스 경합은
    구조적으로 없지만, AV 스캔 등 일시 파일 잠금이 원자 교체를 PermissionError(공유 위반 —
    CPython 은 FILE_SHARE_DELETE 없이 연다)로 튕길 수 있다. 아무 문제 없는 일시 충돌이 사용자
    alert 로 승격되지 않도록 유계 재시도 후에만 전파한다."""
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(_REPLACE_RETRIES):
        try:
            # 재판독을 try 안에 둔다 — 일시 공유 위반은 판독 쪽에서도 튈 수 있고(원자 교체 순간
            # 타 프로세스의 읽기 락), 이를 재시도로 흡수하지 않으면 쓰기만 관대하고 그 직전 읽기는
            # spurious alert 로 승격되는 비대칭이 된다(#75 리뷰4 #4). 재시도마다 재판독 = 손상·
            # 갱신된 다른 키 보존.
            data = _read_for_update(path)
            data[key] = value
            write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def save_theme(mode: str) -> None:
    """테마 선택 영속 — 비유효 ``mode`` 는 조용히 무시하지 않고 ``ValueError`` (confirm-or-alarm).

    보존·원자성·재시도 계약은 :func:`_save_key` 공용 몸통이 진다."""
    if mode not in VALID_THEMES:
        raise ValueError(f"유효하지 않은 테마: {mode!r} (허용: {VALID_THEMES})")
    _save_key("theme", mode)


def load_job_collapsed_groups() -> "list[str]":
    """「작업」 좌 목록의 접힌 그룹 이름들(``""``=「그룹 없음」 구획) — 마지막 상태 영속.

    미저장·비유효 값은 빈 리스트 = 전부 펼침(무상태 기본, R-info 1부 결정 6-①②). 새 그룹은
    이 목록에 없으므로 자동으로 펼침이다. 리스트 안의 비문자열 항목만 걸러낸다(부분 손상이
    전체 리셋으로 승격되지 않게)."""
    raw = _read().get("job_collapsed_groups")
    if not isinstance(raw, list):
        return []
    return [g for g in raw if isinstance(g, str)]


def save_job_collapsed_groups(groups: "list[str]") -> None:
    """접힌 그룹 집합 영속 — webview 저장소가 아니라 Python 설정(#74 전례: 오리진 결합 리셋).

    비유효 인자(비리스트·비문자열 포함)는 조용히 무시하지 않고 ``ValueError`` (confirm-or-alarm).
    저장은 정렬·중복 제거로 정규화한다 — 파일 diff 안정성."""
    if not isinstance(groups, list) or any(not isinstance(g, str) for g in groups):
        raise ValueError("접힌 그룹 목록은 문자열 리스트여야 합니다")
    _save_key("job_collapsed_groups", sorted(set(groups)))
