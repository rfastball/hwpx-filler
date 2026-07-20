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
import threading
import time
from pathlib import Path

from hwpxcore.atomic import write_text_atomic

# 설정 RMW 직렬화 잠금(#136 리뷰 F3) — 원자 교체는 개별 쓰기만 보호하고 판독→변이→쓰기 구간은
# 보호하지 않는다. pywebview 호출은 서로 다른 스레드에서 동시 진입하므로, 두 스레드가 같은
# 설정을 읽은 뒤 각각 hwpx·txt 그룹을 저장하면 마지막 교체가 먼저 저장분을 통째로 지운다(중첩
# 키 '다른 매체 보존' 계약 붕괴). 프로세스 내 단일 잠금으로 재시도 포함 RMW 전체를 직렬화한다
# (앱은 홈당 단일 인스턴스라 프로세스 간 경합은 없다 — 스레드 간만 막으면 족하다).
_MUTATE_LOCK = threading.Lock()

VALID_THEMES = ("system", "light", "dark")

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
        raise ValueError(f"유효하지 않은 템플릿 매체: {media!r} (허용: {VALID_TEMPLATE_MEDIA})")


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
