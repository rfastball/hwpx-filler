"""External Adapter 정본 — 앱 설정의 오리진 비의존 영속.

테마 선택 같은 셸 상태는 원래 프런트 ``localStorage`` 에 있었으나, localStorage 는
오리진(``http://127.0.0.1:<port>``) 스코프라 pywebview 의 내부 HTTP 포트가 부팅마다 바뀌면
조용히 리셋됐다(#74). 영속을 여기 Python 홈 설정으로 옮겨 오리진 결합을 끊는다 — 그 대가로
``private_mode=True`` (랜덤 포트·인메모리 프로필)를 되찾아 포트 스쿼팅·캐시 스테일·서버
크로스톡 클래스를 구조적으로 소멸시킨다(#74). 저장 위치는 레지스트리들과 같은 홈 규약
(``HWPXFILLER_HOME`` 또는 ``~/.hwpxfiller``, 예: :func:`hwpxfiller.host.locations.default_jobs_dir`).
"""

from __future__ import annotations

import datetime
import json
import sys
import threading
import time
from pathlib import Path

from .atomic import write_text_atomic

# 앱 홈 해석은 core 단일 출처(#76). 이 모듈은 ``settings.home_dir()`` 로도 계속 불린다
# (app.py: 단일 인스턴스 뮤텍스 키·webview 루트) — 이름을 그대로 재노출해 호출 계약은 두고
# 해석만 위임한다. 관용구를 여기 다시 적으면 settings.json 과 레지스트리가 다른 홈으로
# 갈라질 수 있고, 그 조용한 갈라짐이 #76 이 없애려는 결함류다.
from hwpxfiller.host.locations import home_dir

__all__ = (
    "VALID_THEMES",
    "VALID_FONT_SCALES",
    "DEFAULT_MASTER_WIDTH",
    "MIN_MASTER_WIDTH",
    "MAX_MASTER_WIDTH",
    "VALID_DRAFT_FONTS",
    "PROPORTIONAL_DRAFT_FONTS",
    "BOOT_STAMP_UNKNOWN_VERSION",
    "VALID_TEMPLATE_MEDIA",
    "is_proportional_font",
    "alert",
    "home_dir",
    "load_theme",
    "save_theme",
    "load_font_scale",
    "save_font_scale",
    "load_master_width",
    "save_master_width",
    "load_window_geometry",
    "save_window_geometry",
    "load_draft_target_font",
    "save_draft_target_font",
    "load_boot_completed",
    "save_boot_completed",
    "load_last_output_directory",
    "save_last_output_directory",
    "VALID_DATA_SOURCES",
    "load_last_data_source",
    "save_last_data_source",
    "load_tutorial_progress",
    "save_tutorial_progress",
    "load_job_collapsed_groups",
    "recollapse_job_group",
    "save_job_collapsed_groups",
    "load_template_group_map",
    "save_template_group_map",
    "load_template_collapsed_groups",
    "save_template_collapsed_groups",
    "save_template_group_state",
)

# 설정 RMW 직렬화 잠금(#136 리뷰 F3) — 원자 교체는 개별 쓰기만 보호하고 판독→변이→쓰기 구간은
# 보호하지 않는다. pywebview 호출은 서로 다른 스레드에서 동시 진입하므로, 두 스레드가 같은
# 설정을 읽은 뒤 각각 hwpx·txt 그룹을 저장하면 마지막 교체가 먼저 저장분을 통째로 지운다(중첩
# 키 '다른 매체 보존' 계약 붕괴). 프로세스 내 단일 잠금으로 재시도 포함 RMW 전체를 직렬화한다
# (앱은 홈당 단일 인스턴스라 프로세스 간 경합은 없다 — 스레드 간만 막으면 족하다).
_MUTATE_LOCK = threading.Lock()

VALID_THEMES = ("system", "light", "dark")
VALID_FONT_SCALES = ("normal", "large", "larger")
DEFAULT_MASTER_WIDTH = 240
MIN_MASTER_WIDTH = 180
MAX_MASTER_WIDTH = 420

# 대상 글꼴 선언(R-flow 블록 3 결정 17) — 붙여넣는 곳(기안작성기)의 표준 글꼴. 클립보드
# 평문은 글꼴을 운반하지 않으므로(글꼴=목적지 소유) 이건 원문 렌더가 미리 따를 글꼴일 뿐이고,
# 열거형 3종이 공문 타이포를 사실상 전부 커버한다(굴림·돋움=고정폭, 맑은고딕=비례폭). 값은
# 배치가 아니라 전역 영속(워드프로세서 멘탈 모델 — 문서 위 툴바 드롭다운). 린트는 선언-조건부:
# 비례폭 선언에서만 연속 공백 정렬 경보(한글·전각은 전 글꼴 균일폭이라 견고).
VALID_DRAFT_FONTS = ("gulimche", "dotumche", "malgun")

# 비례폭 선언 — 정렬 린트(결정 17)가 이 선언에서만 발화한다. 열거형이 3종뿐이라 표 대신
# 튜플 하나로 족하고, 글꼴 성질의 단일 출처가 되어 표면·컨트롤러가 이름을 다시 판별하지 않는다.
PROPORTIONAL_DRAFT_FONTS = ("malgun",)


def is_proportional_font(font: str) -> bool:
    """선언된 대상 글꼴이 비례폭인가 — 정렬 린트 발화 조건(결정 17)."""
    return font in PROPORTIONAL_DRAFT_FONTS

_READ_RETRIES = 5   # 일시 판독 충돌(AV 스캔·원자 교체 순간의 공유 위반) 흡수 상한 — save 측과 대칭
_REPLACE_RETRIES = 5  # Windows 공유 위반(아래) 일시 충돌 흡수 상한 — 총 ~0.5s




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


def _mutate(mutator) -> None:
    """설정 dict 를 read-modify-write 로 갱신하는 공용 몸통 — 다른 키 보존 + 원자 교체.

    ``mutator(data)`` 는 판독한 dict 를 제자리에서 수정한다(단일 키·중첩 매체 등 갱신 형태
    불가지). 교체 경합(방어적): 앱은 홈당 단일 인스턴스(app.py 뮤텍스 가드)라 교차-프로세스
    경합은 구조적으로 없지만, AV 스캔 등 일시 파일 잠금이 원자 교체를 PermissionError(공유
    위반 — CPython 은 FILE_SHARE_DELETE 없이 연다)로 튕길 수 있다. 아무 문제 없는 일시 충돌이
    사용자 alert 로 승격되지 않도록 유계 재시도 후에만 전파한다.

    재판독을 try 안에 둔다 — 일시 공유 위반은 판독 쪽에서도 튈 수 있고(원자 교체 순간 타
    프로세스의 읽기 락), 이를 재시도로 흡수하지 않으면 쓰기만 관대하고 그 직전 읽기는 spurious
    alert 로 승격되는 비대칭이 된다(#75 리뷰4 #4). 재시도마다 재판독 = 손상·갱신된 다른 키 보존."""
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 판독→변이→쓰기 전체를 잠금 안에서(재시도 포함) — 동시 저장의 lost-update 차단(F3).
    with _MUTATE_LOCK:
        for attempt in range(_REPLACE_RETRIES):
            try:
                data = _read_for_update(path)
                mutator(data)
                write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))
                return
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))


def _save_key(key: str, value) -> None:
    """단일 키 영속 — RMW·원자성·재시도 계약은 :func:`_mutate` 공용 몸통이 진다."""
    _mutate(lambda data: data.__setitem__(key, value))


def _save_nested(top_key: str, sub_key: str, sub_value) -> None:
    """중첩 dict(``{top_key: {sub_key: sub_value}}``) 갱신 — **같은 top_key 아래 다른 sub_key
    를 보존**한다(매체별 그룹 상태처럼 한 top 아래 hwpx/txt 두 칸이 공존하는 경우, 한 매체
    저장이 다른 매체를 지우면 안 된다). top_key 가 dict 가 아니면(부재·손상) 새 dict 로 새 출발."""
    def mutate(data: dict) -> None:
        bucket = data.get(top_key)
        if not isinstance(bucket, dict):
            bucket = {}
        bucket[sub_key] = sub_value
        data[top_key] = bucket

    _mutate(mutate)


def save_theme(mode: str) -> None:
    """테마 선택 영속 — 비유효 ``mode`` 는 조용히 무시하지 않고 ``ValueError`` (confirm-or-alarm).

    보존·원자성·재시도 계약은 :func:`_save_key` 공용 몸통이 진다."""
    if mode not in VALID_THEMES:
        raise ValueError(f"유효하지 않은 테마: {mode!r} (허용: {VALID_THEMES})")
    _save_key("theme", mode)


def load_font_scale() -> str:
    """앱 전역 글자 배율 — 기본/크게(125%)/더 크게(150%)."""
    scale = _read().get("font_scale")
    return scale if scale in VALID_FONT_SCALES else "normal"


def save_font_scale(scale: str) -> None:
    if scale not in VALID_FONT_SCALES:
        raise ValueError(f"유효하지 않은 글자 크기: {scale!r} (허용: {VALID_FONT_SCALES})")
    _save_key("font_scale", scale)


# 레일 접힘(``rail_collapsed``)은 상단 토바 셸 교체로 표면과 함께 사망했다(재작성 F2 PR-B,
# 지도 §10.9): 토바는 64px 한 줄이라 접을 것이 없다. 마이그레이션을 두지 않는다 — 옛 파일에
# 남은 키는 _read() 가 읽고 아무도 묻지 않으므로 무해하고, 되살릴 표면이 없다.


def load_master_width() -> int:
    """「기안」 좌 목록의 폭(px). 비유효 값은 240px 기본으로 폴백한다."""
    value = _read().get("master_width")
    if isinstance(value, int) and not isinstance(value, bool) and MIN_MASTER_WIDTH <= value <= MAX_MASTER_WIDTH:
        return value
    return DEFAULT_MASTER_WIDTH


def save_master_width(width: int) -> None:
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not MIN_MASTER_WIDTH <= width <= MAX_MASTER_WIDTH
    ):
        raise ValueError(
            f"목록 폭은 {MIN_MASTER_WIDTH}~{MAX_MASTER_WIDTH}px 정수여야 합니다"
        )
    _save_key("master_width", width)


def load_window_geometry() -> "dict[str, int | bool] | None":
    """마지막 정상 창 기하. 화면 가시성 판정은 현재 모니터를 아는 app 계층이 맡는다."""
    raw = _read().get("window_geometry")
    if not isinstance(raw, dict):
        return None
    x, y = raw.get("x"), raw.get("y")
    width, height = raw.get("width"), raw.get("height")
    maximized = raw.get("maximized")
    if not (
        isinstance(x, int) and not isinstance(x, bool)
        and isinstance(y, int) and not isinstance(y, bool)
        and isinstance(width, int) and not isinstance(width, bool)
        and isinstance(height, int) and not isinstance(height, bool)
        and isinstance(maximized, bool)
    ):
        return None
    if width < 760 or height < 600:
        return None
    return {"x": x, "y": y, "width": width, "height": height, "maximized": maximized}


def save_window_geometry(*, x: int, y: int, width: int, height: int, maximized: bool) -> None:
    geometry = {"x": x, "y": y, "width": width, "height": height, "maximized": maximized}
    if (
        any(not isinstance(geometry[key], int) or isinstance(geometry[key], bool) for key in ("x", "y", "width", "height"))
        or not isinstance(maximized, bool)
        or width < 760
        or height < 600
    ):
        raise ValueError("창 기하는 정수 좌표·최소 760×600 크기·bool 최대화 상태여야 합니다")
    _save_key("window_geometry", geometry)


def load_draft_target_font() -> str:
    """저장된 대상 글꼴 선언 — ``VALID_DRAFT_FONTS`` 중 하나. 미저장·비유효 시 기본 굴림체.

    기본이 굴림체인 이유: 공문 표준 고정폭이라 연속 공백 정렬이 정당한 저작이고(린트 침묵),
    비례폭(맑은고딕)을 기본으로 두면 첫 화면부터 정렬 경보가 서는 역효과가 난다."""
    font = _read().get("draft_target_font")
    return font if font in VALID_DRAFT_FONTS else "gulimche"


def save_draft_target_font(font: str) -> None:
    """대상 글꼴 선언 영속 — 비유효 값은 조용히 무시하지 않고 ``ValueError`` (confirm-or-alarm).

    보존·원자성·재시도 계약은 :func:`_save_key` 공용 몸통이 진다(테마·접힌 그룹과 동형)."""
    if font not in VALID_DRAFT_FONTS:
        raise ValueError(f"유효하지 않은 대상 글꼴: {font!r} (허용: {VALID_DRAFT_FONTS})")
    _save_key("draft_target_font", font)


# 부팅 완주 스탬프(#77) — 값은 그때 관측한 WebView2 런타임 버전, 못 읽었으면 아래 sentinel.
# 빈 문자열을 안 쓰는 이유: "완주한 적 없음"과 "완주했으나 버전 미검출"은 예산 판정이 갈리는
# 서로 다른 사실이고, 둘을 같은 값으로 접으면 버전을 못 읽는 머신이 영구히 첫 실행 취급된다.
BOOT_STAMP_UNKNOWN_VERSION = "unknown"


def load_boot_completed() -> str:
    """마지막으로 **부팅을 완주한** WebView2 런타임 버전 — 없으면 ``""``.

    완주 = ``loaded`` 발화(창을 실제로 띄웠다). 폴백으로 강제 표시된 부팅은 완주가 아니라
    기록하지 않는다 — 한 번도 끝까지 못 간 환경이 넓은 예산을 잃으면 안 된다."""
    raw = _read().get("boot_completed_runtime")
    return raw if isinstance(raw, str) else ""


def save_boot_completed(version: str) -> None:
    """부팅 완주 스탬프 영속 — 빈 버전은 '미검출로 완주'(sentinel)로 정규화한다."""
    _save_key("boot_completed_runtime", version.strip() or BOOT_STAMP_UNKNOWN_VERSION)


def load_last_output_directory() -> str:
    """마지막으로 **명시 지정**한 저장 폴더 — 없으면 ``""``(U3-06 · #879).

    다음 세션의 기본값 **재료**다: 도출·판정은
    :func:`hwpxfiller.domain.output_folder_default.resolve_output_folder` 가 하고, 이 값이
    실제로 쓰이려면 존재 확인을 통과해야 한다(사라진 폴더의 조용한 재사용 금지). 자동으로 잡힌
    기본값은 기억하지 않는다 — 기억하면 템플릿을 옮겨도 옛 템플릿 옆 폴더가 따라다닌다.

    비문자열(손상·구버전)은 미저장과 같이 다룬다 — 이 키가 없는 기존 ``settings.json`` 은
    그대로 기본 거동으로 산다."""
    raw = _read().get("last_output_directory")
    return raw if isinstance(raw, str) else ""


def save_last_output_directory(path: str) -> None:
    """명시 지정한 저장 폴더 영속 — 빈 경로는 조용히 무시하지 않고 ``ValueError``.

    빈 값 저장을 허용하면 '지정한 적 없음'과 '빈 경로를 지정함'이 한 값으로 접혀 다음 세션의
    도출이 침묵한다(confirm-or-alarm). 보존·원자성·재시도 계약은 :func:`_save_key` 가 진다."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"유효하지 않은 저장 폴더 경로: {path!r}")
    _save_key("last_output_directory", path)


# 마지막으로 성사된 데이터 마운트의 출처 축(U3-07 · #880) — 세션의 `data_source` 플래그와
# 같은 열거형이다('' = 미겨눔이라 기억할 것이 없다). 오타 키는 loud 로 자른다.
# ``pclm``(계약 목록, #937)은 풀 슬롯 없이 서는 마운트라 파일 갈래와 같은 성분을 쓴다 —
# ``path`` 가 db, ``sheet`` 가 뷰다(엑셀 참조와 **같은 자리를 다른 이름으로** 쓰는 규율,
# `pool_reference_quad`). 종류 축을 따로 저장하지 않는 이유는 출처가 이미 그것을 말하기
# 때문이다: 여기 두 번 적으면 둘이 어긋난 descriptor 가 성립한다.
VALID_DATA_SOURCES = ("file", "pool", "pclm")


def load_last_data_source() -> "dict | None":
    """마지막으로 **성사된** 데이터 마운트의 성분 — 없으면 ``None``(U3-07 · #880).

    성분은 세션이 마운트 시점에 한 벌로 포획하는 그것이다(``path``·``sheet``·
    ``header_row``·``pool_key`` + 출처 축) — :meth:`~hwpxfiller.webapp.data_zone.
    DataZoneMixin.new_work_handoff` 가 내는 참조와 같은 재료다. 앱 시작 시 이 성분으로
    다시 마운트하는 것이 매 세션 데이터를 다시 고르게 하던 결함(#880)의 조치다.

    **판정은 여기 없다**: 그 파일이 지금도 있는지·읽히는지는 마운트가 답하고, 실패는 조용한
    빈 상태가 아니라 사유 문구로 재진술된다(:mod:`hwpxfiller.webapp.screen_job`).

    비dict·형 불일치·필수 성분 부재(파일인데 경로 없음, 풀인데 슬롯 키 없음, 계약 목록인데
    db·뷰 없음)는 미저장과 같이 다룬다 — 이 키가 없는 기존 ``settings.json`` 은 그대로 빈
    부팅으로 산다."""
    raw = _read().get("last_data_source")
    if not isinstance(raw, dict):
        return None
    source = raw.get("source")
    if source not in VALID_DATA_SOURCES:
        return None
    path = raw.get("path")
    sheet = raw.get("sheet")
    pool_key = raw.get("pool_key")
    header_row = raw.get("header_row")
    if not (isinstance(path, str) and isinstance(sheet, str) and isinstance(pool_key, str)):
        return None
    if not isinstance(header_row, int) or isinstance(header_row, bool) or header_row < 0:
        return None
    if source == "file" and not path:
        return None
    if source == "pool" and not pool_key:
        return None
    if source == "pclm" and not (path and sheet):
        return None
    return {
        "source": source,
        "path": path,
        "sheet": sheet,
        "header_row": header_row,
        "pool_key": pool_key,
    }


def save_last_data_source(
    *,
    source: str,
    path: str = "",
    sheet: str = "",
    header_row: int = 0,
    pool_key: str = "",
) -> None:
    """성사된 데이터 마운트 성분 영속 — 다음 부팅 자동 마운트의 재료.

    필수 성분이 빠진 저장은 조용히 무시하지 않고 ``ValueError`` 다(confirm-or-alarm): 반쪽
    descriptor 를 받아 두면 다음 부팅이 무엇을 열어야 할지 모른 채 침묵한다. 보존·원자성·
    재시도 계약은 :func:`_save_key` 공용 몸통이 진다."""
    if source not in VALID_DATA_SOURCES:
        raise ValueError(f"유효하지 않은 데이터 출처: {source!r} (허용: {VALID_DATA_SOURCES})")
    if not all(isinstance(v, str) for v in (path, sheet, pool_key)):
        raise ValueError("데이터 마운트 성분(경로·시트·슬롯 키)은 문자열이어야 합니다")
    if not isinstance(header_row, int) or isinstance(header_row, bool) or header_row < 0:
        raise ValueError(f"유효하지 않은 헤더 행: {header_row!r}")
    if source == "file" and not path.strip():
        raise ValueError("파일 마운트 기억에는 데이터 파일 경로가 필요합니다")
    if source == "pool" and not pool_key.strip():
        raise ValueError("등록 데이터 마운트 기억에는 슬롯 키가 필요합니다")
    if source == "pclm" and not (path.strip() and sheet.strip()):
        raise ValueError("계약 목록 마운트 기억에는 DB 경로와 뷰가 필요합니다")
    _save_key(
        "last_data_source",
        {
            "source": source,
            "path": path,
            "sheet": sheet,
            "header_row": header_row,
            "pool_key": pool_key,
        },
    )


# 온보딩 튜토리얼 진행(#893 · 설계 정본 ONBOARDING_TUTORIAL.md §4.4) — 중첩 키 ``tutorial``
# 아래 ``achieved``(달성 단계 식별자)·``dismissed``(명시 종료) 두 칸. 중첩으로 두는 이유는
# 설치 manifest 참조가 같은 top_key 아래 뒤에 붙기 때문이다(슬라이스 B 소유) — 진행 저장이
# 그 칸을 지우지 않게 판독-보존-쓰기로 다룬다. 단계 식별자 자체는 여기서 검증하지 않는다:
# 열거 정본은 링1(``gui/tutorial_state.py``)이고, 옛 버전이 남긴 죽은 단계 키는 그 층이
# 복원할 때 걸러낸다(죽은 키 무시 전례). localStorage 금지(#74)는 여기서도 같다.
def load_tutorial_progress() -> "dict":
    """튜토리얼 진행 — ``{"achieved": [단계 식별자], "dismissed": bool}``.

    미저장·비유효는 ``{"achieved": [], "dismissed": False}``(시작 전과 같은 상태). 부분
    손상(리스트 안 비문자열)은 그 항목만 걸러낸다 — 전체 리셋으로 승격 금지(접힌 그룹 전례).
    """
    raw = _read().get("tutorial")
    if not isinstance(raw, dict):
        return {"achieved": [], "dismissed": False}
    achieved = raw.get("achieved")
    steps = [s for s in achieved if isinstance(s, str)] if isinstance(achieved, list) else []
    return {"achieved": steps, "dismissed": raw.get("dismissed") is True}


def save_tutorial_progress(*, achieved: "list[str]", dismissed: bool) -> None:
    """진행·종료 상태를 **한 번의 원자 변이**로 저장 — 같은 ``tutorial`` 아래 다른 칸 보존.

    둘을 따로 쓰면 앞은 성공하고 뒤가 실패해 반쪽 상태(달성은 늘었는데 닫힘은 옛 값)가
    디스크에 남는다(:func:`save_template_group_state` 와 같은 이유). 비유효 인자(비리스트·
    비문자열 항목·비bool)는 조용히 무시하지 않고 ``ValueError`` (confirm-or-alarm).

    달성 목록은 중복만 걷고 **순서는 준 대로** 둔다 — 정본 순서는 링1 이 안다.
    """
    if not isinstance(achieved, list) or any(not isinstance(s, str) for s in achieved):
        raise ValueError("튜토리얼 달성 단계는 문자열 리스트여야 합니다")
    if not isinstance(dismissed, bool):
        raise ValueError(f"튜토리얼 종료 상태는 bool 이어야 합니다: {dismissed!r}")
    steps = list(dict.fromkeys(achieved))

    def mutate(data: dict) -> None:
        bucket = data.get("tutorial")
        if not isinstance(bucket, dict):
            bucket = {}
        bucket["achieved"] = steps
        bucket["dismissed"] = dismissed
        data["tutorial"] = bucket

    _mutate(mutate)


# 예제 세트 설치 manifest(#891 · 설계 정본 ONBOARDING_TUTORIAL.md §1 D4) — 같은 ``tutorial``
# 중첩 키 아래 ``manifest`` 칸이다(#893 진행 칸이 예고한 자리). 그룹은 실체가 아니라 소속이라
# 「그룹 삭제 한 번으로 통째 제거」가 성립하지 않는다: 제거(슬라이스 C)는 **여기 기재된 항목만**
# 걷어야 사용자가 직접 넣은 이웃 파일을 건드리지 않는다. 값의 의미(무엇을 설치하는가)는
# ``external/example_pack.py`` 가 소유하고 여기는 형상만 검증한다.
def load_tutorial_manifest() -> "dict | None":
    """설치 manifest — 미설치는 ``None``. 손상·구형상도 미설치로 접는다(부분 해석 금지).

    반쯤 읽은 manifest 로 제거를 돌리면 「무엇을 지우는지」가 흔들린다 — 형상이 계약과
    다르면 없는 것으로 보고, 재설치가 정상 기재를 다시 쓰게 둔다(되돌리기 = 재설치, D4).
    """
    raw = _read().get("tutorial")
    if not isinstance(raw, dict):
        return None
    manifest = raw.get("manifest")
    if not isinstance(manifest, dict):
        return None
    templates = manifest.get("templates")
    if not isinstance(templates, list) or any(
        not isinstance(t, dict) or not isinstance(t.get("path"), str) for t in templates
    ):
        return None
    return manifest


def save_tutorial_manifest(
    *,
    group: str,
    templates: "list[dict]",
    data_files: "list[str]",
    pool_keys: "list[str]",
) -> None:
    """설치 manifest 를 **한 번의 원자 변이**로 저장 — 같은 ``tutorial`` 아래 진행 칸 보존.

    스키마(슬라이스 C 가 읽는 계약):

    - ``group``: 설치된 템플릿이 묶인 그룹 이름(hwpx·txt 공통).
    - ``templates``: ``{"media": "hwpx"|"txt", "path": 절대경로, "key": 라이브러리 상대 식별키}``.
    - ``data_files``: 홈으로 복사한 예제 데이터 파일 절대경로 전수.
    - ``pool_keys``: 데이터 풀에 고정된 슬롯 키.

    비유효 인자는 조용히 무시하지 않고 ``ValueError`` (:func:`save_tutorial_progress` 전례).
    """
    if not isinstance(group, str) or not group.strip():
        raise ValueError("예제 그룹 이름이 비어 있습니다")
    if not isinstance(templates, list) or any(
        not isinstance(t, dict)
        or t.get("media") not in VALID_TEMPLATE_MEDIA
        or not isinstance(t.get("path"), str)
        or not isinstance(t.get("key"), str)
        for t in templates
    ):
        raise ValueError("설치 manifest 의 템플릿 기재가 올바르지 않습니다")
    if not isinstance(data_files, list) or any(not isinstance(p, str) for p in data_files):
        raise ValueError("설치 manifest 의 데이터 파일 기재가 올바르지 않습니다")
    if not isinstance(pool_keys, list) or any(not isinstance(k, str) for k in pool_keys):
        raise ValueError("설치 manifest 의 풀 등록 키 기재가 올바르지 않습니다")
    record = {
        "group": group.strip(),
        "templates": [
            {"media": t["media"], "path": t["path"], "key": t["key"]} for t in templates
        ],
        "data_files": list(data_files),
        "pool_keys": list(pool_keys),
    }

    def mutate(data: dict) -> None:
        bucket = data.get("tutorial")
        if not isinstance(bucket, dict):
            bucket = {}
        bucket["manifest"] = record
        data["tutorial"] = bucket

    _mutate(mutate)


def clear_tutorial_manifest() -> None:
    """설치 manifest 칸만 지운다(제거 · 슬라이스 C #892) — **진행 칸은 남긴다**.

    제거해도 학습 진행(``achieved``·``dismissed``)은 남는 것이 D4 의 계약이다: 되돌리기가
    재설치이므로, 다시 설치한 사용자는 **이어서** 배운다(진행 초기화는 다른 동사다).
    미설치·부재 키에 대해서도 조용히 성공한다 — 지우는 동사의 멱등은 거짓말이 아니다.
    """

    def mutate(data: dict) -> None:
        bucket = data.get("tutorial")
        if isinstance(bucket, dict):
            bucket.pop("manifest", None)
            data["tutorial"] = bucket

    _mutate(mutate)


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


def recollapse_job_group(old: str, new: str = "") -> None:
    """사라진 그룹 이름의 접힘 영속 정리 — ``new`` 가 있으면 그 이름으로 승계.

    그룹 개명·해산 동사의 곁들이 semantic op(P2-24): 읽기-수정-쓰기가 컨트롤러에 남으면
    설정 영속의 두 번째 조립자가 생긴다. 메모리 사본을 들지 않고 영속 키를 그때그때 읽고
    쓴다 — 표면(라이브러리 접힘)과 키를 계속 공유하되 제2 정본을 만들지 않는다."""
    collapsed = set(load_job_collapsed_groups())
    if old not in collapsed:
        return
    collapsed.discard(old)
    if new:
        collapsed.add(new)
    save_job_collapsed_groups(sorted(collapsed))


# (구 「기안」 좌 목록 접힘 키 `draft_collapsed_groups` 는 화면 사망(F6 PR-B)과 함께 걷혔다.
#  저장 파일에 남은 죽은 키는 `_read` 가 그냥 무시한다 — 마이그레이션 불요.)


# 템플릿 라이브러리 그룹(R-info 2부 결정 2·8) — 작업 그룹과 **같은 기제**(Python 설정,
# webview 저장소 금지 #74 전례). 단 템플릿엔 매체 축(HWPX/TXT)이 있어(작업엔 없음, 결정 3)
# 매체별로 칸을 나눈다: 같은 이름 그룹이 두 매체에 독립 존재할 수 있고(소비 표면이 매체를
# 가르므로) 한 매체 접힘이 다른 매체를 접지 않는다. 저장 형상:
#   "template_groups":          {media: {식별키: 그룹명}}   — 그룹 지정(빈 그룹명은 미저장)
#   "template_collapsed_groups": {media: [그룹명, …]}       — 접힘 영속(""=「그룹 없음」 구획)
# 식별키 = 라이브러리 루트 상대경로(결정 8: 루트 내 파일명 — 루트 파일은 곧 파일명, 관용된
# 하위폴더 파일은 상대경로). Explorer 개명·이동으로 키가 살아있는 파일과 안 맞으면 그 지정은
# 고아가 되어 조용히 소멸하지 않고 「그룹 없음」으로 복귀한다(그루핑이 live 행만 묶으므로 —
# 퇴화-코퍼스 불변식 동형). 매체 열거는 두 칸뿐이라 오타 키를 loud 로 자른다.
VALID_TEMPLATE_MEDIA = ("hwpx", "txt")


def _check_media(media: str) -> None:
    if media not in VALID_TEMPLATE_MEDIA:
        raise ValueError(f"유효하지 않은 템플릿 형식: {media!r} (허용: {VALID_TEMPLATE_MEDIA})")


def load_template_group_map(media: str) -> "dict[str, str]":
    """매체별 템플릿 그룹 지정(``{식별키: 그룹명}``) — 미저장·비유효는 빈 dict(전부 「그룹 없음」).

    부분 손상(비문자열 키/값·빈 그룹명)은 그 항목만 걸러낸다(전체 리셋으로 승격 금지) —
    빈 그룹명은 「그룹 없음」과 같으므로 애초에 저장되지 않아야 하고, 있어도 무시한다."""
    _check_media(media)
    root = _read().get("template_groups")
    if not isinstance(root, dict):
        return {}
    sub = root.get(media)
    if not isinstance(sub, dict):
        return {}
    return {
        k: v
        for k, v in sub.items()
        if isinstance(k, str) and isinstance(v, str) and v
    }


def save_template_group_map(media: str, mapping: "dict[str, str]") -> None:
    """매체별 그룹 지정 영속 — **다른 매체 칸을 보존**(:func:`_save_nested`). 빈 그룹명 항목은
    「그룹 없음」이라 저장 전 걷어낸다(모델의 set_group 해제와 동형 — 스토어에 부재=무그룹).

    비유효 인자(비dict·비문자열 키/값)는 조용히 무시하지 않고 ``ValueError`` (confirm-or-alarm)."""
    _check_media(media)
    _save_nested("template_groups", media, _clean_group_map(mapping))


def load_template_collapsed_groups(media: str) -> "list[str]":
    """매체별 접힌 그룹 이름들(``""``=「그룹 없음」) — 미저장·비유효는 빈 리스트(전부 펼침).

    작업 접힘(:func:`load_job_collapsed_groups`)과 동형: 비리스트는 전부 펼침, 리스트 안
    비문자열 항목만 걸러낸다(부분 손상이 전체 리셋으로 승격되지 않게)."""
    _check_media(media)
    root = _read().get("template_collapsed_groups")
    if not isinstance(root, dict):
        return []
    raw = root.get(media)
    if not isinstance(raw, list):
        return []
    return [g for g in raw if isinstance(g, str)]


def save_template_collapsed_groups(media: str, groups: "list[str]") -> None:
    """매체별 접힌 그룹 집합 영속 — **다른 매체 칸 보존** + 정렬·중복 제거 정규화(diff 안정).

    비유효 인자는 조용히 무시하지 않고 ``ValueError`` (job 접힘과 동형)."""
    _check_media(media)
    _save_nested("template_collapsed_groups", media, _norm_collapsed(groups))


def _clean_group_map(mapping: "dict[str, str]") -> "dict[str, str]":
    if not isinstance(mapping, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in mapping.items()
    ):
        raise ValueError("템플릿 그룹 지정은 {문자열: 문자열} 이어야 합니다")
    return {k: v for k, v in mapping.items() if v}  # 빈 그룹명 = 미지정


def _norm_collapsed(groups: "list[str]") -> "list[str]":
    if not isinstance(groups, list) or any(not isinstance(g, str) for g in groups):
        raise ValueError("접힌 그룹 목록은 문자열 리스트여야 합니다")
    return sorted(set(groups))


def save_template_group_state(
    media: str, mapping: "dict[str, str]", collapsed: "list[str]"
) -> None:
    """매체의 그룹 지정 **+** 접힘을 **한 번의 원자 변이**로 함께 저장(#136 리뷰 F5).

    지정과 접힘을 두 번의 별도 저장으로 쓰면 앞은 성공하고 뒤가 실패해 반쪽 상태(개명된
    멤버 + 옛 이름 접힘)가 디스크에 남을 수 있다. 그룹 모델이 지정+접힘의 단일 소유자이므로
    두 값을 하나의 ``_mutate`` 안에서 함께 기록한다(다른 매체 칸은 보존). 비유효 인자는 loud."""
    _check_media(media)
    cleaned = _clean_group_map(mapping)
    norm = _norm_collapsed(collapsed)

    def mutate(data: dict) -> None:
        for top_key, value in (
            ("template_groups", cleaned),
            ("template_collapsed_groups", norm),
        ):
            bucket = data.get(top_key)
            if not isinstance(bucket, dict):
                bucket = {}
            bucket[media] = value
            data[top_key] = bucket

    _mutate(mutate)
