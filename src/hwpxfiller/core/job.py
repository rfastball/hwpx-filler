"""작업(Job) 데이터모델 — 생성 의도의 앵커.

트랙 C UX 결정([[hwpx-filler-scope]]): 생성 의도는 데이터도 템플릿도 아닌 **저장된 "작업"**에
붙는다. 작업은 durable 바인딩 ``{템플릿, 매핑 프로파일, 파일명 패턴}``(양식 측 {T·M·N})이다.
데이터·행은 매 실행 일회성이라 **작업에 저장하지 않는다**.

- **한 겹.** 데이터 측은 :class:`~hwpxfiller.data.base.DataSource` 이음새로 추상 참조한다.
  누적치환(이전 출력을 소스로)·API 직결(미래)은 그 이음새 뒤의 *소스 종류*일 뿐 — 여기서 조인/
  데이터-뷰 계층을 세우지 않는다.
- **매핑은 작업 정의 때 1회 확정**(에디터의 명시성 게이트). 실행은 사전검증만 한다.
- ``source_shape``는 매핑 프로파일에 내포된다(별도 필드 없음) — :meth:`Job.source_keys` 가
  실행 시점에 그 형태를 실 DataSource 와 대조한다.

직렬화는 :class:`~hwpxfiller.core.mapping.MappingProfile` 의 JSON 관례(UTF-8·``ensure_ascii=False``·
``indent=2``·``to_dict``/``from_dict``)를 그대로 미러한다. 이 모듈은 Qt·엔진에 의존하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING

from .mapping import MappingProfile
from .paths import home_dir
from .template_status import default_templates_dir
from .text_registry import default_text_templates_dir
from hwpxcore.atomic import write_text_atomic
from hwpxcore.validate import ValidationReport, validate

if TYPE_CHECKING:  # 런타임 결합 회피 — DataSource 는 덕타이핑으로 충분.
    from ..data.base import DataSource

# 미충족 공란 표식 — grep 가능 표적의 단일 출처(로드맵 ⑤ 출력검증 = 이 표식 grep).
# "누락은 시끄럽게"의 출력 짝: 있어야 할 값이 빈 필드에만 주입되고(의도적 공란은 매핑이
# 이미 키를 제외해 자동 면제), 누적치환의 다음 패스에서 그 필드가 매핑되면 덮인다.
MISSING_MARKER = "〘미입력·{field}〙"

# 출력 파일명 패턴 기본값 — 단일 출처(RC-20). dataclass 기본·from_dict 하위호환·
# 작업 에디터 프리필·CLI --pattern 이 전부 이 상수를 참조한다. 예약 토큰만 쓴다(F34b):
# 데이터 필드 토큰(구 '공고서-{{ID}}')은 그 이름의 열이 없으면 기본값이 곧 보장된
# 미해소 파일명 + 전 레코드 동일명이 된다 — 예약 토큰은 데이터와 무관하게 항상
# 해소되고 {{seq}} 가 레코드별 유일성을 준다.
DEFAULT_FILENAME_PATTERN = "공고서-{{date}}-{{seq:001}}"


def mark_missing_values(
    records: "list[dict]", marker: str, *, fields: "list[str] | None" = None
) -> "list[dict]":
    """빈 값(``""``)에 미입력 표식을 주입한 사본을 만든다 — GUI·CLI 공유 규칙(RC-03).

    표식 주입 정책이 표면별로 재구현되면 동일 입력에서 두 표면의 문서 내용이 갈라진다
    (GUI 만 표식, CLI 는 누름틀 원문 잔존). :meth:`RunRequest.mapped_records` 와 CLI
    ``--ack-empty`` 가 이 한 함수를 쓴다. ``fields`` 가 주어지면 그 필드만 대상
    (CLI 직접 채우기 — 템플릿 요구 필드 외의 소스 열은 건드리지 않는다).
    """
    if not marker:
        return [dict(rec) for rec in records]
    allowed = None if fields is None else set(fields)
    return [
        {
            k: (
                marker.format(field=k)
                if v == "" and (allowed is None or k in allowed)
                else v
            )
            for k, v in rec.items()
        }
        for rec in records
    ]

# 레지스트리 파일명 slug — 파일시스템 금지문자만 정리(naming.clean_filename 과 동일 규칙).
_INVALID = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _slug(name: str) -> str:
    s = _INVALID.sub("_", name).strip()
    return s or "unnamed"


class SlugCollisionError(Exception):
    """서로 다른 이름이 같은 slug(=같은 파일)로 매핑돼 기존 항목을 덮으려 할 때 loud raise.

    slug 이 비단사라 ``예산/2026`` 과 ``예산_2026`` 이 같은 파일이 된다. 확인 없는 덮어쓰기는
    durable 데이터(템플릿·매핑·태그·참조)를 조용히 소실시키므로(confirm-or-alarm 위반),
    각 레지스트리의 ``save`` 가 명시적 ``allow_overwrite`` 없이는 여기서 막는다.
    (#1 JobRegistry 에서 확립, #34 레지스트리 일반화. 데이터셋 풀 소비자는 U2 §5.3
    재편(#347 — 파일명이 이름 slug 가 아니게 됨)으로 소멸 — 남은 소비자는 작업·TXT 축.)
    """


# 하위호환 별칭 — #1 이 도입한 이름. 기존 호출·테스트(webapp editor·test_job)가 잡던
# 예외 계약을 깨지 않도록 같은 클래스를 가리키게 둔다(`except JobSlugCollisionError` 유효).
JobSlugCollisionError = SlugCollisionError


def guard_slug_collision(path: Path, name: str, load_name, *, kind: str) -> None:
    """slug 충돌 loud 가드 — 저장 경계 공용(작업·TXT 레지스트리 공유, #34).

    ``path`` 가 이미 존재하면 저장된 이름을 ``load_name(path)`` 로 읽어 ``name`` 과
    비교한다. 다르면(다른 이름·같은 파일) 또는 읽을 수 없으면(손상) :class:`SlugCollisionError`
    를 던진다 — 조용한 durable 소실 방지. 같은 이름 재저장(자기 갱신)은 충돌이 아니라 통과.
    호출측이 확정 덮어쓰기를 받았으면 ``allow_overwrite`` 로 이 함수를 아예 건너뛴다.

    ``kind`` 는 메시지에 쓰는 항목 종류 라벨('작업'·'데이터셋').
    """
    if not path.exists():
        return
    try:
        existing_name = load_name(path)
    except Exception:  # noqa: BLE001 — 손상 파일: 이름 불명 → 덮어쓰기 판단 불가, loud
        raise SlugCollisionError(
            f"{kind} '{name}' 저장 대상 파일 {path.name} 이 이미 있으나 손상돼 "
            f"소유 {kind}을(를) 확인할 수 없습니다."
        ) from None
    if existing_name != name:
        raise SlugCollisionError(
            f"{kind} '{name}' 과 기존 {kind} '{existing_name}' 이 같은 파일"
            f"({path.name})로 매핑됩니다. 저장하면 '{existing_name}' 이 소실됩니다."
        )


def load_isolated(paths, loader, corrupted):
    """손상 격리 로드 루프 — 세 레지스트리 목록 메서드의 공용 몸통(RC-05 단일 출처).

    예전엔 이 try/except-수집 루프가 :meth:`JobRegistry.list_jobs`·:meth:`~hwpxfiller.core.
    dataset_pool.DatasetPoolRegistry.list_items` 등에 바이트 단위로 복붙돼 있었다 —
    여기로 수렴해 락스텝 편집 부담과 정책 표류를 없앤다.

    - ``corrupted`` 가 **리스트**면: ``loader(path)`` 실패를 파일별로 잡아
      ``(경로, 오류 문자열)`` 로 수집하고 정상 항목만 돌려준다 — 손상 1개가 목록 전체를
      죽이지 않되, 호출측이 수집분을 시끄럽게 표면화할 책임을 진다(확인-또는-경보).
    - ``corrupted`` 가 **None** 이면: 예외를 **그대로 전파**한다 — 수집처가 없는데
      격리하면 손상 항목이 무표시로 증발한다(조용한 드롭 금지, C5). 호출자는 둘 중
      하나를 명시적으로 고른다: 수집해 표면화하거나, raise 를 받아 실패를 표시하거나.
    """
    items = []
    for p in paths:
        if corrupted is None:
            items.append(loader(p))  # 수집처 없음 = 격리 없음 — 실패는 그대로 전파(loud)
            continue
        try:
            items.append(loader(p))
        except Exception as exc:  # noqa: BLE001 — 손상 1개의 전멸 방지(격리 후 표면화)
            corrupted.append((p, str(exc)))
    return items


# (classify_existing 은 #347 에서 제거 — 소비자가 데이터셋 게이트 둘(pool 수동 등록·에디터
#  자동등록)뿐이었고, U2 §5.3 재편으로 데이터 축 중복 판정이 이름이 아니라 **정체성**
#  (:func:`~hwpxfiller.core.dataset_pool.excel_identity`)으로 바뀌며 둘 다 죽었다.
#  작업 축 slug 가드(:func:`guard_slug_collision`)는 그대로다.)


def default_jobs_dir() -> Path:
    """GUI 기본 작업 레지스트리 위치 — 사용자 홈(``~/.hwpxfiller/jobs``).

    작업은 작업 디렉터리·repo 체크아웃을 가로질러 살아남아야 하는 개인 durable 자산이라
    프로젝트-로컬이 아니라 홈에 둔다(패키징된 exe 엔 쓰기 가능한 프로젝트 폴더도 없다).
    ``HWPXFILLER_HOME`` 환경변수로 재지정 가능(테스트·CI·이식성 — 해석은
    :func:`~hwpxfiller.core.paths.home_dir`). 레지스트리 *클래스* 자체는 위치-불가지(생성자가
    디렉터리를 받는다) — 이 함수는 GUI 기본값 해석기일 뿐이다.
    """
    return home_dir() / "jobs"


# ------------------------------------------------------------------ 매체 유도·가드
# 작업의 매체(hwpx/txt)는 **저장하지 않고 template_path 접미사에서 유도한다**(R-info 3부 결정 4).
# 선언 필드를 두면 선언과 실제가 갈라질 자리를 새로 만든다(이 저장소 지배 결함류) — 내재 속성
# (매체)은 읽어내고, 앱 부여 속성(그룹)만 저장한다. 순수 문자열 판정(I/O 없음)이라 단일 출처로
# 둔다: 임시변통 접미사 검사(naming·screen_template·template_groups)가 여기로 수렴할 표적이다.
HWPX_SUFFIX = ".hwpx"
TXT_SUFFIX = ".txt"


def template_media(template_path: str) -> str:
    """template_path 접미사 → 매체 코드. ``'hwpx'`` / ``'txt'`` / ``''``(미상·빈 경로). 대소문자 무시.

    I/O 없음(파일 존재 여부와 무관 — 순수 문자열 판정). 미상(``''``)을 조용히 hwpx 로 간주하지
    않는다 — :func:`require_hwpx` 가 loud 거부하도록 정직하게 빈 코드를 돌려준다.
    """
    low = template_path.lower()
    if low.endswith(HWPX_SUFFIX):
        return "hwpx"
    if low.endswith(TXT_SUFFIX):
        return "txt"
    return ""


# ------------------------------------------------------------------ 시스템 작업 방식(§19.1)
# 계약 §19.1: "작업 방식은 사용자 group 이나 tag 가 아니라 실행·편집·결과를 결정하는 **시스템
# 축**이다. 값은 불변 명목형이며 template_path 확장자에서만 파생한다."
#
# **매체(media)와 작업 방식(work mode)은 같은 것의 두 이름이 아니다** — 매체는 파일 형식이고
# 작업 방식은 그 형식이 결정하는 *일의 종류*다. 값 집합이 셋으로 같지만 미상(``''``)의 뜻이
# 갈린다: 매체의 ``''`` 는 "형식을 모른다"이고, 작업 방식의 ``unsupported`` 는 "이 앱이 할 수
# 있는 일이 아니다"라는 **판정**이다. 그래서 v6 어휘를 별칭이 아니라 파생 함수로 둔다.
#
# **연결 상태는 이 축이 아니다**(지도 §10.15 판정 A): 경로가 빈 저작 중 작업은 여기서
# ``unsupported`` 로 나오지만 그것은 "고장"이 아니라 "아직 방식을 정하지 않았다"이며, 그 사실을
# 말하는 축은 ``template_path`` 의 존재 여부다. 라이브러리 필터의 「미연결 → hwpx」 귀속
# (:func:`~hwpxfiller.gui.home_state.library_mode_of`)은 *필터 귀속 규칙*이지 방식 파생이
# 아니다 — 서로 다른 것을 같게 부르는 것도 드리프트라서 두 함수를 합치지 않는다.
WORK_MODE_HWPX = "hwpx_generate"
WORK_MODE_TEXT = "text_review_copy"
WORK_MODE_UNSUPPORTED = "unsupported"


def work_mode(template_path: str) -> str:
    """template_path → 시스템 작업 방식(§19.1 3값). I/O 없음(:func:`template_media` 파생).

    ``.txt`` 가 아니면 모두 hwpx 로 보던 v5 fallback 은 없다 — 미상 확장자와 빈 경로는
    ``unsupported`` 이고, 그 값은 메인 후보에서 제외되고 현재 데이터 문서 선택도 허용하지
    않는다(fail-closed). 모르는 것을 추측하지 않는 것이 이 축의 요점이다.
    """
    media = template_media(template_path)
    if media == "hwpx":
        return WORK_MODE_HWPX
    if media == "txt":
        return WORK_MODE_TEXT
    return WORK_MODE_UNSUPPORTED


class MediaMismatchError(Exception):
    """hwpx 전용 소비 경로에 hwpx 아닌(txt·미상) 작업/경로가 들어오면 loud raise(3부 결정 13).

    정상 경로에선 두 화면(「작업」·「기안」)이 각자 자기 매체만 조회하므로(조회 경계 = 1층)
    여기 닿지 않는다 — 이 예외는 그 경계가 새면 **조용한 오작동**(예: ``.txt`` 를 hwpx zip 으로
    파싱해 엉뚱한 오류 배지) 대신 시끄럽게 터지게 하는 backstop(2층)이다. 재유입 가드 테스트
    (:mod:`tests.test_architecture`)가 새 hwpx 소비자를 이 가드 없이 추가하는 것을 3층에서 막는다.
    """


def require_hwpx_template(template_path: str) -> str:
    """경로가 hwpx 매체가 아니면 :class:`MediaMismatchError`, 맞으면 그대로 반환(체이닝).

    **경로만** 손에 쥔 hwpx 소비 경계(생성 배치·홈 카드 컴파일 배지)용. Job 을 쥐고 있으면
    :func:`require_hwpx` 를 쓴다(같은 판정에 작업 이름 문맥 추가). ``bytes``/``HwpxPackage`` 를
    받는 공유 코어 프리미티브(``extract_schema``·``compile_status``)에는 넣지 않는다 — 그것들은
    CLI 가 생 hwpx 파일에 직접 쓰는 매체-내재 프리미티브라 가드 고도가 틀린다(경계에서만 막는다).
    """
    media = template_media(template_path)
    if media != "hwpx":
        raise MediaMismatchError(
            f"hwpx 전용 경로에 hwpx 아닌 템플릿이 들어왔습니다: "
            f"{template_path!r} (형식={media or '미상'})"
        )
    return template_path


def require_hwpx(job: "Job") -> "Job":
    """작업 템플릿이 **비어있지 않은데 hwpx 가 아니면** :class:`MediaMismatchError`, 아니면 그대로 반환.

    3부 결정 13 진입 가드. 실행뷰(:class:`~hwpxfiller.gui.run_state.RunViewModel`)·「작업」 화면
    등 hwpx 워크플로 진입점에서 부른다. 판정은 **두 부류를 가른다**:

    - **빈 ``template_path`` = 통과.** 템플릿을 아직 잇지 않은 hwpx **저작 중** 작업은 정당하게
      여기 흐르고, 「작업」 화면이 템플릿 재연결(relink) UI 로 복구를 돕는다. RunViewModel 도
      미링크 템플릿을 관용한다(``effective_template``/``_template_fields`` 가 빈/부재를 처리).
    - **비어있지 않은데 매체가 hwpx 가 아니면 = 거부.** txt 기안 작업(자기 화면 「기안」이 따로
      있음)은 물론, ``.docx`` 등 미지 접미사도 여기서 막는다 — 그대로 두면 RunViewModel 하위
      메서드가 그 경로를 hwpx zip 으로 파싱해 조용한 오작동이 된다. 실제 파싱 경계(``.hwpx``
      필수)는 :func:`require_hwpx_template` 가 별도로 엄격히 지킨다(배치 생성·홈 컴파일).
    """
    if job.template_path and job.media != "hwpx":
        where = "'기안' 화면 소관" if job.media == "txt" else "hwpx 아닌 템플릿"
        raise MediaMismatchError(
            f"작업 '{job.name}' 은(는) 이 hwpx 전용 경로를 쓸 수 없습니다 "
            f"({where} · 형식={job.media or '미상'} · 템플릿={job.template_path!r})"
        )
    return job


# ------------------------------------------------------------------ 라이브러리 상대키(#348)
# U2 §5.3 판정 B: 레지스트리는 위치-불가지인데(생성자가 디렉터리를 받는다) **내용물이 절대경로로
# 위치에 묶여 있었다** — 홈을 옮기면 모든 작업의 ``template_path`` 가 한꺼번에 끊기고, 라이브러리는
# 그 사실을 「템플릿이 연결되지 않은 **작업 N건**」이라고 작업 수로 셌다(간접층이 있었다면
# 데이터 축처럼 「참조 1건」이었다). 웹 표준의 처방과 같다: 경로를 **버리는** 것이 아니라 경로에서
# **기계 고유 부분만 이름으로 치환**한다(named root + root-relative).
#
# **새 관례를 만들지 않는다** — 라이브러리 루트 상대 POSIX 키는 템플릿 그룹 지정(결정 8)이 이미
# 쓰는 값이고 에디터 피커도 이미 그 키로 말한다. 저장만 경로였다. 그래서 키 계산의 몸통은 여기
# 링0 에 두고 :func:`~hwpxfiller.webapp.template_groups.rel_key` 가 이것을 감싼다.
#
# **폴백 정책만 다르다**(이 이슈의 유일한 새 규칙): 그룹 키는 루트 밖이면 파일명으로 폴백하지만,
# 작업 링크에서 그 폴백은 **다른 폴더의 동명 파일에 조용히 붙는다** — 끊긴 참조를 파일명으로
# 자동 매칭하는 것은 영상 편집 도구들이 대가를 치른 결함류다. 여기서는 폴백 없이 승격에
# **실패**하고 기존 절대경로를 유지한다("이 작업은 이식 대상이 아니다"를 정직하게 남긴다).
#
# **루트 선택도 확장자로** 한다 — 매체 파생이 이미 계약(:func:`template_media`)이라 매체를
# 선언하는 새 필드가 필요 없다. 신규 durable 필드는 상대키 하나뿐이다.
#
# **검토 지문(:func:`rules_values`)은 이 키를 쓰지 않는다** — 이식성을 여기서 멈추는 것은 누락이
# 아니라 판정이다(PR #368 P2). 근거는 그 함수의 선언에 있다: 지문을 키로 바꾸면 홈·사람을 건너온
# 작업이 한 번도 본 적 없는 템플릿에 대해 **구조 변경 병기까지 지운 채** 도착하고, 반대로 지금
# 판정이 무는 대가는 병기 1비트뿐이다(템플릿은 승인 축이 아니라 게이트가 서지 않는다).


def library_root_for(template_path: str) -> "Path | None":
    """매체별 라이브러리 루트(hwpx=``templates``/txt=``text_templates``) — 확장자에서만 고른다.

    I/O 없음. 미상 확장자·빈 경로는 ``None``(승격도 해석도 하지 않는다 — 모르는 것을 추측하지
    않는다는 :func:`work_mode` 와 같은 fail-closed). 두 루트 모두 ``HWPXFILLER_HOME`` 을 존중하는
    기본 해석기라 **홈을 옮기면 같은 키가 새 홈의 파일로 해석된다** — 이 함수가 이식성의 경첩이다.
    """
    media = template_media(template_path)
    if media == "hwpx":
        return default_templates_dir()
    if media == "txt":
        return default_text_templates_dir()
    return None


def _lexically_normal(path: "str | Path") -> Path:
    """``.``·``..`` 성분을 걷은 경로 — **어휘** 정규화이고 I/O 도 심볼릭 링크 해석도 없다.

    ``resolve()`` 를 쓰지 않는 근거가 셋이다(#368 2R):

    1. **관례가 갈라진다.** 라이브러리 표면은 ``rglob`` 로 훑고 그 결과를 그대로 키로 쓴다
       (:func:`~hwpxfiller.webapp.template_groups.rel_key`) — 링크를 해석하지 않는다. 작업 쪽만
       해석하면 **같은 파일이 두 키로 갈라져** 그룹 지정과 작업 링크가 어긋난다. 이 함수를 공유하는
       이유 자체가 그 갈라짐을 구조적으로 없애려는 것이라 여기서 되살릴 수 없다.
    2. **durable 정체성이 디스크 상태에 좌우된다.** 키는 :meth:`Job.to_dict` 가 저장할 때마다 다시
       뜬다. ``resolve()`` 는 파일이 있을 때와 없을 때(네트워크 드라이브 오프라인·일시 삭제) 다른
       값을 내므로, **템플릿이 잠깐 안 보이는 사이의 저장이 키를 조용히 바꿔** 링크를 끊는다.
    3. **대소문자·UNC 를 건드리지 않는다.** ``normcase`` 는 하지 않는다 — 그룹 키가 사용자 표기를
       보존하는데 여기서만 접으면 다시 두 키가 된다(윈도우 ``relative_to`` 는 이미 대소문자
       무시라 표기가 달라도 승격은 성립한다). UNC 루트(``\\\\srv\\share``)는 ``normpath`` 가
       보존한다(실측) — 별도 처리가 필요 없고, 루트와 경로가 서로 다른 볼륨이면 ``relative_to``
       가 실패해 정직하게 승격되지 않는다.

    링크의 대가는 하나 남는다: 심볼릭 링크 디렉터리를 ``..`` 로 거슬러 오르는 경로는 어휘 정규화가
    **다른 파일**을 이름한다. 그 경우는 :func:`library_rel_key` 가 왕복을 실측해 승격을 포기한다.
    """
    return Path(os.path.normpath(os.fspath(path)))


def _key_names_the_same_file(resolved: Path, original: "str | Path") -> bool:
    """정규화가 **같은 파일**을 이름하는지 실측 — 심볼릭 링크 경유 ``..`` 만 이 검사를 탄다.

    ``realpath`` 는 존재하지 않는 경로에 대해선 순수 어휘 계산이라(실측) 미설치 템플릿에서도
    결정적이다. 실패(OSError)는 ``False`` = 승격 포기 — 증명 못 하면 이식하지 않는다(fail-closed).
    """
    try:
        return os.path.normcase(os.path.realpath(resolved)) == os.path.normcase(
            os.path.realpath(original)
        )
    except OSError:
        return False


def library_rel_key(path: "str | Path", root: "Path | None") -> "str | None":
    """루트 상대 POSIX 키 — **폴백 없이** 루트 밖·루트 미지정이면 ``None``(위 절 참조).

    :func:`~hwpxfiller.webapp.template_groups.rel_key` 가 이 위에 파일명 폴백을 얹는다(그룹
    지정은 오연결의 대가가 없다).

    **쓰기는 읽기 방어에 걸릴 키를 만들지 않는다**(#368 2R): ``relative_to`` 는 ``.``·``..`` 를
    **보존**하므로 ``…/templates/sub/../x.hwpx`` 가 ``sub/../x.hwpx`` 라는 키가 됐고, 그 키는
    :func:`_reject_unsafe_key` 가 로드에서 loud 거절한다 — 앱이 **자기가 저장한 작업을 스스로
    손상됨으로 읽는** 구조였다. 양쪽을 같은 함수로 정규화해 그 키가 애초에 생기지 않게 하고,
    그래도 방어에 걸리는 값이 나오면(상대 루트 등 잔여 경로) 승격을 포기한다. 읽기 방어는
    **그대로 둔다** — 외부에서 손댄 JSON 은 여전히 loud 여야 하고, 쓰기 정규화가 그 의무를
    대신하지 않는다(두 방어는 서로 다른 위협을 본다).
    """
    if root is None:
        return None
    root_n, path_n = _lexically_normal(root), _lexically_normal(path)
    try:
        key = path_n.relative_to(root_n).as_posix()
    except ValueError:
        return None
    try:
        _reject_unsafe_key(key)
    except ValueError:
        return None  # 자기가 만든 키가 자기 방어에 걸리면 승격하지 않는다(절대경로 유지)
    if path_n != Path(path) or root_n != Path(root):
        # 정규화가 실제로 성분을 걷었다 — 걷힌 것이 심볼릭 링크 디렉터리였다면 키는 다른 파일을
        # 이름한다. **해석이 지나갈 그 길 그대로**(root/key) 왕복을 실측해 아니면 포기한다.
        if not _key_names_the_same_file(root_n / key, path):
            return None
    return key


def library_key_for(template_path: str) -> str:
    """템플릿 경로 → 라이브러리 루트 상대키. 루트 밖·미상 매체는 ``""``(승격 실패 = 절대경로 유지)."""
    return library_rel_key(template_path, library_root_for(template_path)) or ""


def _reject_unsafe_key(key: str) -> None:
    """durable 키의 탈출 방어 — 드라이브·루트·``..`` 는 loud raise.

    상대키는 루트에 이어 붙여 해석되므로 ``C:/x.hwpx``·``../../x.hwpx`` 같은 값이 들어오면
    **루트 밖으로 조용히 새어나간다**(``root / 절대경로`` 는 절대경로를 그대로 돌려준다).
    다른 durable 필드와 같은 규율으로 경계에서 막는다 — 격리는 :meth:`JobRegistry.list_jobs`
    의 파일 단위 격리가 '손상됨' 행으로 표면화한다. ``PureWindowsPath`` 로 판정하는 이유는
    두 구분자(``/``·``\\``)와 드라이브를 **모두** 인식하는 가장 엄격한 해석이기 때문이다.
    """
    p = PureWindowsPath(key)
    if p.drive or p.root or ".." in p.parts:
        raise ValueError(
            f"작업 필드 'template_key' 는 라이브러리 루트 상대경로여야 하는데 {key!r} 입니다"
        )


def resolve_library_key(key: str) -> str:
    """상대키 → **지금** 홈 기준 절대경로 문자열. 빈 키·미상 매체는 ``""``(호출측이 옛 경로 폴백).

    해석은 순수 경로 계산이다 — 파일이 실제로 있는지는 보지 않는다(부재는 라이브러리의
    「연결 안 됨」 표면이 이미 말한다). 디스크를 읽지도 쓰지도 않으므로 **읽기가 조용히
    저장을 승격시키는 일이 없다**: 승격은 :meth:`Job.to_dict` 를 지나는 저장에서만 일어난다.
    """
    if not key:
        return ""
    _reject_unsafe_key(key)
    root = library_root_for(key)
    if root is None:
        return ""
    return str(root / key)


# ------------------------------------------------------------------ 모델
@dataclass
class Job:
    """저장되는 생성 작업 — durable 바인딩 {템플릿·매핑·파일명}. 데이터·행은 제외.

    스키마 진화 규율: **가산적(additive) 필드는 version 을 올리지 않는다** —
    ``from_dict`` 의 ``.get(기본값)`` 관례가 하위호환(구 JSON→기본값, 구 코드는 신 키 무시)을
    보장한다. version 증가는 기존 키의 의미·형태가 깨지는 변경에 예약.
    """

    name: str = ""
    template_path: str = ""
    mapping: MappingProfile = field(default_factory=MappingProfile)
    filename_pattern: str = DEFAULT_FILENAME_PATTERN
    version: int = 1  # 전방호환 — 스키마 진화 시 마이그레이션 훅.
    # 마지막 성공 실행 시각(ISO-8601, ""=미실행). 작업 자체의 사용 메타 — 실행의
    # 데이터·행을 저장하는 게 아니므로 "Job 에 데이터 미포함" 불변식과 무관.
    last_run_at: str = ""
    # 즐겨찾기 시각(ISO-8601, ""=아님) — 메인 후보 정렬의 1순위 축(v6 계약 §18.5·§19.3,
    # 데이터-우선 봉합 슬라이스 2). bool 이 아니라 **시각**인 이유는 정렬 계약이
    # `favoritedAt` 최신순이기 때문이다(같은 즐겨찾기끼리의 순서가 있어야 한다).
    # 순수 정렬 메타 — 매핑·파일명·실행 경로에 무영향이라 내용 지문(content_fingerprint)에서
    # 빠지고, 데이터 참조의 '고정'과도 다른 사용자 어휘다(§18.5).
    favorited_at: str = ""
    # 브라우징용 분류 태그 {축이름 → 값}(차원-불가지·선택적, JOB_BROWSER_DESIGN D1·D2·D12·D13).
    # **순수 메타** — 코드는 "물품"·"금액구간"이 뭔지 모르고 얇은 매핑만 든다(run-path 무영향).
    # 축·값은 이름 문자열이지 enum/bool 타입 필드 발명 금지(도메인을 코드에 안 박는다).
    tags: "dict[str, str]" = field(default_factory=dict)
    # 좌 목록 사용자 그룹(앱 부여 1급 속성, R-info 1부 결정 5·R-flow 결정 43). ""=「그룹 없음」.
    # tags(브라우저 렌즈용 차원-불가지 축)와 별개다 — 그룹은 목록의 구조 자체라 전용 필드.
    # 소속이 곧 생성이고 해산은 ""(빈 그룹은 존재하지 않는다 — 퇴화 불변식).
    group: str = ""
    # (default_dataset_ref(#53-A 작업→데이터 결속)는 U2 §5.3 판정 D 로 **폐기** — v6
    #  데이터-우선 재작성을 살아남은 작업-앵커 잔재였고, 데이터↔작업 결속은 어느 방향으로도
    #  다시 들이지 않는다(#347). 구 JSON 의 해당 키는 미지 키로 무시된다 — 마이그레이션이
    #  아니라 폐기다: 「이 작업이 지난번 쓰던 데이터」 정보는 사용자 확인 하에 사라졌다.)
    # 마지막 **완주** 런이 쓴 규칙의 대상별 지문(재작성 F5, 지도 §10.12 판정 B).
    # ``{}`` = 아직 완주한 적 없음 = 새 작업이라 검토 요구가 선다(§13-3).
    # 왜 영속인가: §13-2("정상 반복 실행에서 미리보기는 선택")가 **앱 재시작을 넘어**
    # 성립해야 한다 — 세션 사건만으로 세우면 어제 규칙을 바꾸고 오늘 열었을 때 요구가
    # 조용히 사라진다. 반대로 **승인**은 영속시키지 않는다(승인만 하고 실행 안 한 채
    # 재시작하면 요구가 되돌아온다 = fail-closed).
    # ``content_fingerprint`` 에서 빠진다(tags·last_run_at·favorited_at·group 과 같은 줄):
    # 검토 메타를 내용 지문에 남기면 실행 한 번이 열어 둔 편집 세션에 「외부 변경을
    # 덮어씁니다」라는 거짓 파괴 확인을 띄운다.
    reviewed_rules: "dict[str, str]" = field(default_factory=dict)
    # Template·Binding **판본**(재작성 F7, 지도 §10.13 판정 F·G). 계약이 고정한 축은 이 둘뿐
    # (§13-6·7) — 파일 이름 규칙은 문서 구조가 아니라 산출물 규칙이라 Binding 쪽이 진다.
    # 저장 **횟수**가 아니라 **규칙이 갈린 횟수**다: 판본이 저장 횟수면 아무것도 안 바뀐
    # 저장에도 §13-6(판본 변경 = validation·approval 폐기)이 걸려 §13-2 의 조용한 반복이
    # 깨진다. 정산 주체는 :func:`JobRegistry.save` 하나다(판정 G).
    template_revision: int = 1
    binding_revision: int = 1
    # **직전 판본의 규칙 값**(1세대만, 지도 §10.13 판정 H). 지문이 아니라 값인 이유:
    # ``rules_fingerprints`` 는 ``\x1f`` 로 이어 붙인 **비교용** 문자열이라 거기서 값을
    # 되뽑으면 정규화 값에서 실체를 파생하는 것이고(F2 §10.8.6 규칙 ③), 지문 포맷이 바뀌는
    # 날 증거가 조용히 거짓말한다. 1세대만 두는 이유: 계약에 판본 이력 표면이 없다 —
    # 요구 없는 무한 누적을 durable 파일에 지불하지 않는다. 형상은 :func:`rules_values`.
    previous_rules: "dict" = field(default_factory=dict)

    @property
    def media(self) -> str:
        """이 작업의 매체 코드(``'hwpx'``/``'txt'``/``''``미상) — ``template_path`` 에서 유도(3부 결정 4).

        저장 필드가 아니다: 매체는 내재 속성이라 읽어낸다(그룹 같은 앱 부여 속성만 저장).
        분기 표면은 매체를 다 보는 「홈」 하나로 줄고, hwpx 전용 경로는 :func:`require_hwpx` 로 막는다.
        """
        return template_media(self.template_path)

    @property
    def work_mode(self) -> str:
        """이 작업의 **시스템 작업 방식**(§19.1 3값) — :func:`work_mode` 파생, 저장 필드 아님.

        :attr:`media` 와 나란히 두는 이유는 소비자가 갈리기 때문이다: 매체는 *파일을 어떻게
        읽는가*(파싱 경계·hwpx 가드)를, 작업 방식은 *무슨 일을 하는가*(후보 판정·구획·실행
        분기·편집기 탭 집합)를 정한다. 한 값으로 뭉치면 미연결 작업 하나에 두 뜻이 겹친다.
        """
        return work_mode(self.template_path)

    @property
    def template_key(self) -> str:
        """라이브러리 루트 상대키(``조달/공고서.hwpx``) — ``template_path`` 에서 **읽어낸다**(#348).

        :attr:`media`·:attr:`work_mode` 와 같은 줄의 파생 속성이다. 인메모리 선언 필드를 두지
        않는 이유는 이 파일이 매체에 대해 이미 말한 것과 같다: 선언 필드를 두면 선언과 실제가
        갈라질 자리를 새로 만든다. 키는 durable **표현**이지 별도 상태가 아니라서, 저장
        (:meth:`to_dict`)이 매번 현재 경로에서 다시 뜬다.

        루트 밖 템플릿은 ``""`` — 폴백 없는 승격 실패이고, 그 작업의 링크는 절대경로로 남는다.
        """
        return library_key_for(self.template_path)

    def template_fields(self) -> "list[str]":
        """이 작업이 채우는 템플릿 필드(매핑이 방출하는 집합). 실행 사전검증의 요구필드."""
        return self.mapping.template_fields()

    def source_keys(self) -> "list[str]":
        """매핑이 읽는 소스 키 전체(문서순 중복제거). 실 DataSource 정합 검증의 대상."""
        seen: "dict[str, None]" = {}
        for m in self.mapping.mappings:
            if m.is_blank:
                # malformed/구 프로파일이 blank에 source를 남겨도 의도 선언은
                # 소스 요구가 아니다. source drift와 실제 출력이 갈리지 않게 제외.
                continue
            if m.source:
                seen.setdefault(m.source, None)
        return list(seen)

    # ------------------------------------------------------------ 직렬화
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "name": self.name,
            "template_path": self.template_path,
            # 라이브러리 루트 상대키(#348) — **가산** 필드다: 절대경로도 그대로 함께 쓴다.
            # 구 코드는 새 키를 무시하고 경로로 계속 열리고, 신 코드는 키를 우선해 홈이
            # 옮겨져도 해석된다. 루트 밖 템플릿에선 ``""`` 라 경로만이 링크다(폴백 없음).
            "template_key": self.template_key,
            "filename_pattern": self.filename_pattern,
            "mapping": self.mapping.to_dict(),
            "last_run_at": self.last_run_at,
            "favorited_at": self.favorited_at,
            "tags": dict(self.tags),
            "group": self.group,
            "reviewed_rules": dict(self.reviewed_rules),
            "template_revision": self.template_revision,
            "binding_revision": self.binding_revision,
            "previous_rules": _copy_rules_values(self.previous_rules),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        """durable 로드 경계 — 누락 필드는 ``.get(기본값)`` 으로 하위호환(구 JSON→기본값)하되,
        **존재하는데 타입이 깨진** durable 값(문자열 계약 필드가 int/list/null 등)은 조용히
        통과시키지 않고 loud 하게 던진다. 앱은 늘 str/에스케이프된 값만 쓰므로 타입 불일치는
        외부 훼손·버그 신호다 — 여기서 격리하면 :meth:`JobRegistry.list_jobs` 의 파일단위
        격리(RC-05)가 '손상됨' 행으로 표면화한다. 무검증 대입은 손상 값을 조용히 통과시켜
        뒤늦게 무관한 홈 렌더(혼합타입 ``sorted()``·``_fmt_iso``)를 터뜨리는 지뢰가 됐다
        (confirm-or-alarm: 조기 loud 격리 > 지연 크래시/무성 오염)."""
        def _str(key: str, default: str = "") -> str:
            v = d.get(key, default)
            if not isinstance(v, str):
                raise ValueError(
                    f"작업 필드 '{key}' 는 문자열이어야 하는데 {type(v).__name__} 입니다"
                )
            return v

        def _revision(key: str) -> int:
            """판본은 1 이상의 정수 — durable 훼손을 조용히 통과시키지 않는다(``_str`` 미러).

            ``bool`` 을 거르는 이유: 파이썬에서 ``True`` 는 ``int`` 라 무검사면 ``r1`` 로
            조용히 읽힌다(구 JSON 훼손·수기 편집의 실제 표본류)."""
            v = d.get(key, 1)
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(
                    f"작업 필드 '{key}' 는 정수여야 하는데 {type(v).__name__} 입니다"
                )
            if v < 1:
                raise ValueError(f"작업 필드 '{key}' 는 1 이상이어야 하는데 {v} 입니다")
            return v

        raw_reviewed = d.get("reviewed_rules", {})
        if not isinstance(raw_reviewed, dict):
            raise ValueError(
                f"'reviewed_rules' 는 사전이어야 하는데 {type(raw_reviewed).__name__} 입니다"
            )
        reviewed: "dict[str, str]" = {}
        for k, v in raw_reviewed.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError("'reviewed_rules' 의 대상·지문은 모두 문자열이어야 합니다")
            reviewed[k] = v

        raw_tags = d.get("tags", {})
        if not isinstance(raw_tags, dict):
            raise ValueError(
                f"'tags' 는 사전이어야 하는데 {type(raw_tags).__name__} 입니다"
            )
        tags: "dict[str, str]" = {}
        for k, v in raw_tags.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError("'tags' 의 축·값은 모두 문자열이어야 합니다")
            tags[k] = v
        # 템플릿 링크 해석(#348): 상대키가 있으면 **지금** 홈 기준으로 풀고, 없으면(구 JSON·
        # 루트 밖 템플릿) 옛 절대경로를 그대로 쓴다. 마이그레이션은 없다 — 읽는 김에 디스크를
        # 고치지 않고(조용한 변이 금지), 승격은 저장이 지나갈 때만 일어난다.
        template_path = resolve_library_key(_str("template_key")) or _str("template_path")
        return cls(
            name=_str("name"),
            template_path=template_path,
            mapping=MappingProfile.from_dict(d.get("mapping", {})),
            filename_pattern=_str("filename_pattern", DEFAULT_FILENAME_PATTERN),
            version=d.get("version", 1),
            # base_mapping_name(구 J3 공유 베이스 계보)은 F22 로, default_dataset_ref
            # (#53-A 작업→데이터 결속)는 U2 §5.3 판정 D 로 개념째 제거 — 구 JSON 의
            # 해당 키는 미지 키로 무시된다(가산 스키마 규율의 역방향, 하위호환 무해).
            last_run_at=_str("last_run_at"),
            favorited_at=_str("favorited_at"),
            tags=tags,
            group=_str("group"),
            reviewed_rules=reviewed,
            template_revision=_revision("template_revision"),
            binding_revision=_revision("binding_revision"),
            previous_rules=_rules_values_or_raise(d.get("previous_rules", {})),
        )

    def save(self, path: "str | Path") -> None:
        # 원자 쓰기(RC-01) — 재저장 중 실패가 기존 작업 JSON 을 절단하지 않는다.
        write_text_atomic(path, json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: "str | Path") -> "Job":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def content_fingerprint(job: "Job") -> str:
    """저장 세션이 덮어쓰는 작업 **내용**의 지문 — 외부 변경 감지(자기-갱신 확인 게이트).

    태그·마지막 실행·즐겨찾기·그룹은 제외한다: 저장이 어차피 직전 디스크 값을 재읽어 보존하므로
    (홈 태그 편집·좌 목록 그룹 이동·후보 구획 즐겨찾기와의 공존) 그 넷의 변경은 파괴가 아니다.
    **그룹 제외는 보존과 같은 커밋에서 온다**(리뷰 P2): 보존하는 필드를 지문에 남기면
    편집 중 그룹 이동이 "외부 변경을 덮어씁니다"라는 **거짓 파괴 확인**을 띄운다 — 실제로는
    저장이 그 새 그룹을 그대로 되싣는다(과경고도 문안 부정직의 한 형태). 즐겨찾기는
    정렬 메타만 바꾼다는 계약(§18.5)의 코드측 귀결이기도 하다 — 별을 눌렀다는 이유로 열어 둔
    편집 세션이 '외부 변경' 확인을 요구하면 과경고다. 나머지(템플릿·매핑·파일명 패턴·계보)는
    세션 상태로 덮어써지므로, 로드 시점과 달라져 있으면 '열어 둔 사이 외부
    변경'으로 확인을 요구해야 한다(무확인 파괴 금지). 에디터·「기안」 저장 두 표면이 같은
    지문을 쓰도록 코어에 둔다(복붙하면 한쪽만 고쳐지는 드리프트가 곧 조용한 파괴다)."""
    d = job.to_dict()
    d.pop("tags", None)
    d.pop("last_run_at", None)
    d.pop("favorited_at", None)
    d.pop("group", None)
    # 검토 기준선도 뺀다(재작성 F5 판정 B) — 완주 스탬프가 갱신하는 사용 메타라 위 넷과
    # 같은 부류다. 남기면 실행 한 번이 열어 둔 편집 세션에 거짓 파괴 확인을 띄운다.
    d.pop("reviewed_rules", None)
    # 판본 3필드도 뺀다(재작성 F7 판정 G) — 저장이 **계산해서 다시 쓰는 파생 메타**라 위
    # 다섯과 같은 부류다. 남기면 실행 한 번(스탬프)이나 다른 표면의 저장이 열어 둔 편집
    # 세션에 「외부 변경을 덮어씁니다」라는 거짓 파괴 확인을 띄우고, 더 나쁘게는 세션이
    # 든 옛 판본 번호를 지문 대조의 근거로 만든다(판본은 편집의 대상이 아니다).
    d.pop("template_revision", None)
    d.pop("binding_revision", None)
    d.pop("previous_rules", None)
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


#: 검토 위험 축의 지문 키 접두사 — 표면·테스트가 문자열을 재조립하지 않게 한다.
_FP_TEMPLATE = "template"
_FP_FILENAME = "filename"


def rules_fingerprints(job: "Job") -> "dict[str, str]":
    """작업 규칙의 **대상별** 지문(재작성 F5, 지도 §10.12 판정 C).

    ``content_fingerprint`` 는 "바뀌었나"만 답하는 blob 이라 **무엇이** 바뀌었는지 못
    말한다 — 그 위에 승인을 세우면 F-06 이 P0 로 지목한 결함(표시형 변경과 source 변경이
    같은 증거로 승인됨)이 그대로 남는다. 그래서 축을 넷으로 쪼갠다:

    - ``template`` — 템플릿 경로(구조 위험)
    - ``filename`` — 파일명 패턴(파일명 집합 위험)
    - ``field:<이름>:source`` — 그 필드의 source·type·const·blank(의미 연결 위험)
    - ``field:<이름>:format`` — 그 필드의 표시형 코드(표시형 위험)

    키의 **등장·소멸**이 곧 필드 추가·삭제다(F-06 증거 표의 「의도적 미사용」 행) — 값만
    비교하는 대신 키 집합을 비교하는 이유다. 두 표면이 이 조립을 복붙하면 그 드리프트가
    곧 조용한 오판정이라 링0 에 단일 출처로 둔다(``content_fingerprint`` 와 같은 근거).
    """
    values = rules_values(job)
    out = {
        _FP_TEMPLATE: values["template"],
        _FP_FILENAME: values["filename"],
    }
    for name, axes in values["fields"].items():
        # source 축은 "이 필드가 어떤 값을 낼 것인가"를 결정하는 전부다 — 유형·리터럴·
        # 비움 선언이 여기 든다(표시형만 fmt 로 뺀다). 구분자는 필드 이름·값에 못 들어가는
        # ``\x1f`` 라 "a|b" 와 "a" + "|b" 가 같은 지문으로 붕괴하지 않는다.
        out[f"field:{name}:source"] = "\x1f".join(
            (axes["source"], axes["type"], axes["const"], axes["blank"])
        )
        out[f"field:{name}:format"] = axes["fmt"]
    return out


#: 필드별 규칙 축 — :func:`rules_values` 가 내는 사전의 키(표면·테스트가 문자열을 재조립하지
#: 않게). ``blank`` 는 ``"blank"``/``""`` 두 값만 갖는다(지문 문자열과 같은 표기를 쓴다 —
#: 표기를 바꾸면 디스크의 기존 검토 기준선이 전부 어긋나 한 번씩 헛 검토를 부른다).
RULE_AXES = ("source", "type", "const", "blank", "fmt")


def rules_values(job: "Job") -> "dict":
    """작업 규칙의 **값** 형상(재작성 F7, 지도 §10.13 판정 H) — 지문의 원재료이자 판본 보관형.

    ``{"template": 경로, "filename": 패턴, "fields": {필드: {축: 값}}}``.
    :func:`rules_fingerprints` 가 이 위에서 지문을 조립한다 — 두 함수가 각자 매핑을 훑으면
    한쪽만 고쳐지는 날 "무엇이 바뀌었나"(지문)와 "무엇이었나"(직전 판본)가 서로 다른 규칙을
    말한다. 판본 보관이 지문이 아니라 이 값을 쓰는 근거는 §10.13 판정 H.

    **템플릿 축은 상대키가 아니라 절대경로다 — 누락이 아니라 판정이다**(#348 · PR #368 P2).
    #348 이 작업→템플릿 링크를 라이브러리 루트 상대키로 이식 가능하게 만든 뒤 "지문도 키로 바꿔
    홈 이동 간 검토를 면제하라(또는 해석할 때 기준선을 새 경로로 재기입하라)"는 지적이 섰다.
    **바꾸지 않는다**. 근거는 셋이고, 첫째는 지적이 든 결과가 실측되지 않는다는 것이다:

    - **홈을 옮겨도 미리보기·검토가 강제되지 않는다.** 템플릿은 **승인 축이 아니다**(§10.12 판정 E
      — :data:`~hwpxfiller.gui.review_state.EVIDENCE_POLICY` 서열에 없다). 지문이 갈리면
      ``review_requirement`` 는 ``risk_class=""`` 로 ``required=False`` 를 내고 ``structure_changed``
      **병기 1비트**만 붙는다. 실제 구조 게이트(:func:`~hwpxfiller.core.fill_ledger.template_path_drift`)
      는 경로 문자열이 아니라 **템플릿 파일을 다시 읽어** 판정하므로, 같은 파일이 새 루트에 있는
      이사에는 조용하다. 즉 이 판정의 비용은 "1회 검토 요구"조차 아니다.
    - **키로 바꾸면 조용한 승인 통로가 열린다.** 기준선은 작업 JSON 에 실려 다니므로(#351 패키지
      부트스트래핑이 정확히 그 동선이다) 남에게서 받은 작업이 **한 번도 본 적 없는 템플릿에 대해
      구조 변경 병기까지 지운 채** 도착한다. :meth:`JobRegistry.stamp_last_run` 이 금지한 바로 그
      방향이다("한 번도 실행·확인된 적 없는 새 규칙을 검토받은 것으로 기록" — 되돌릴 수 없다).
    - **비용이 대칭이 아니다.** 지금 판정은 옮긴 사람에게 병기 1비트(과표시 = fail-safe), 키 판정은
      **전원 기준선 1회 무효 + 이후 영구 면제**(과소표시 = fail-open)다. 무효화는 게다가 조용하다 —
      어떤 표면도 "기준선 표기가 바뀌어 한 번 다시 확인합니다"라고 말해 줄 자리가 없다.

    지적의 대안(해석 시 기준선 재기입)은 더 나쁘다: 읽기가 durable 을 고치는 **조용한 변이**(#348 이
    명시로 거절한 것)인 데다, 그 재기입이 세우는 것은 어떤 실행도 벌지 않은 승인이다.

    회귀는 ``tests/test_review_state.py`` 의 홈 이동 두 케이스가 진다 — 선언만 남기고 결과를 안 세우면
    다음 사람이 같은 자리를 결함으로 다시 연다(이 저장소의 지배 결함류: 선언은 살고 결과는 죽는다).
    """
    return {
        # 절대경로 유지는 위 선언의 실행부다(#348 · #368 P2) — :attr:`Job.template_key` 로
        # 바꾸면 홈·사람을 건너온 사본이 구조 검토를 이미 통과한 채 도착한다. 바꾸지 않는다.
        "template": job.template_path,
        "filename": job.filename_pattern,
        "fields": {
            m.template_field: {
                "source": m.source,
                "type": m.type,
                "const": m.const,
                "blank": "blank" if m.is_blank else "",
                "fmt": m.fmt,
            }
            for m in job.mapping.mappings
        },
    }


def _copy_rules_values(values: "dict") -> "dict":
    """:func:`rules_values` 형상의 깊은 사본 — 보관·직렬화가 원본과 사전을 공유하지 않게."""
    fields = values.get("fields", {}) if isinstance(values, dict) else {}
    return {
        "template": values.get("template", "") if isinstance(values, dict) else "",
        "filename": values.get("filename", "") if isinstance(values, dict) else "",
        "fields": {name: dict(axes) for name, axes in fields.items()},
    } if values else {}


def _rules_values_or_raise(raw: "object") -> "dict":
    """durable 로드 경계의 ``previous_rules`` 검증 — 빈 사전은 「직전 판본 없음」.

    ``from_dict`` 의 다른 필드와 같은 규율(조기 loud 격리 > 지연 크래시): 형상이 깨진 값을
    통과시키면 증거 렌더가 뒤늦게 터지고, 그 자리는 사용자가 **변경을 확인하는** 자리라
    조용한 결손이 가장 비싸다."""
    # **형상을 먼저 본다**(3R P2): `not raw` 를 앞에 두면 ``null``·``[]``·``""``·``0`` 같은
    # 훼손 값이 「직전 판본 없음」이라는 **정상 상태로 위장**해 통과한다 — 다른 durable
    # 필드는 전부 loud 인데 여기만 조용히 이력을 잃는다. 빈 사전만이 「없음」이다.
    if not isinstance(raw, dict):
        raise ValueError(f"'previous_rules' 는 사전이어야 하는데 {type(raw).__name__} 입니다")
    if not raw:
        return {}
    fields = raw.get("fields", {})
    if not isinstance(fields, dict):
        raise ValueError("'previous_rules.fields' 는 사전이어야 합니다")
    out_fields: "dict[str, dict[str, str]]" = {}
    for name, axes in fields.items():
        if not isinstance(name, str) or not isinstance(axes, dict):
            raise ValueError("'previous_rules.fields' 의 항목은 필드이름→축사전이어야 합니다")
        if set(axes) != set(RULE_AXES) or not all(isinstance(v, str) for v in axes.values()):
            raise ValueError(
                f"'previous_rules.fields[{name}]' 의 축은 {list(RULE_AXES)} 문자열이어야 합니다"
            )
        out_fields[name] = dict(axes)
    template, filename = raw.get("template", ""), raw.get("filename", "")
    if not isinstance(template, str) or not isinstance(filename, str):
        raise ValueError("'previous_rules' 의 template·filename 은 문자열이어야 합니다")
    return {"template": template, "filename": filename, "fields": out_fields}


def advance_revisions(job: "Job", previous: "Job | None") -> None:
    """저장 직전 판본 정산 — **오른 축만** 올리고 직전 판본 값을 갈무리한다(§10.13 판정 G·H).

    판정 주체를 이 함수 하나로 두는 이유: 판본을 올리는 자리가 저장 표면마다 흩어지면
    (에디터·기안·재연결·복제) 한 표면만 빠뜨려도 **아무 테스트도 울지 않고** 그 작업의
    세대가 조용히 멈춘다 — 그 뒤 §13-7(Run 은 사용 판본을 고정)이 말하는 판본이 거짓이 된다.
    :meth:`JobRegistry.save` 가 쓰기 잠금 안에서 부른다.

    **잇는 기준은 이름이 아니라 파일 슬롯**이다: 같은 자리를 덮어쓰는 저장은 그 자리의 다음
    세대가 된다. `_preserved_for_target`(태그·이력·즐겨찾기·검토 기준선이 **대상 파일**의
    것으로 남는다)과 같은 규율이고, 이름 기준으로 하면 slug 이 같은 이름 변경(``a/b`` →
    ``a_b``)이 판본을 1 로 되돌려 열 세대 실행한 작업이 신참으로 표시된다.

    ``previous`` 가 없으면(새 자리·읽을 수 없는 자리) 인메모리 값을 그대로 둔다 — 이름
    변경으로 새 파일에 착지하는 저장이 세대를 잃지 않게. 계승하지 **않아야** 하는 경로
    (복제)는 :meth:`JobRegistry.clone` 이 이력·즐겨찾기와 같은 줄에서 명시적으로 지운다.
    """
    if previous is None:
        return
    old, new = rules_values(previous), rules_values(job)
    template_changed = old["template"] != new["template"]
    binding_changed = old["filename"] != new["filename"] or old["fields"] != new["fields"]
    job.template_revision = previous.template_revision + (1 if template_changed else 0)
    job.binding_revision = previous.binding_revision + (1 if binding_changed else 0)
    # 직전 판본은 **축별로** 밀린다(7R P2). 두 축이 한 스냅샷에 살지만 **각자의 세대**를
    # 가지므로, 한 축만 저장했다고 나머지 축의 직전 값까지 현재로 밀면 아직 검토받지 않은
    # 그 축의 증거가 「B → B」가 된다(연결을 A→B 로 바꿔 두고 템플릿만 저장한 경우가 실물).
    # 규칙이 그대로면 직전 판본도 그대로다 — 변경이 없다는 사실을 변경으로 재진술하지 않는다.
    if not (template_changed or binding_changed):
        job.previous_rules = _copy_rules_values(previous.previous_rules)
        return
    kept = _copy_rules_values(previous.previous_rules) or {
        "template": "", "filename": "", "fields": {},
    }
    if template_changed:
        kept["template"] = old["template"]
    if binding_changed:
        kept["filename"] = old["filename"]
        kept["fields"] = {name: dict(axes) for name, axes in old["fields"].items()}
    job.previous_rules = kept


class JobRegistryOwnershipError(RuntimeError):
    """다른 프로세스가 같은 작업 디렉터리의 writer 소유권을 가진 경우."""


class _RegistryWriteState:
    """한 프로세스 안에서 디렉터리별로 공유하는 스레드·프로세스 쓰기 상태."""

    def __init__(self, key: str):
        self.key = key
        self.lock = threading.RLock()
        self._owner: object | None = None
        self._owner_pid: "int | None" = None

    def claim_process_ownership(self) -> None:
        # 소유권은 **프로세스** 단위 계약이다(#234 리뷰) — POSIX fork 자식은 ``_owner`` 를
        # 그대로 상속해 조기 반환으로 원 writer 행세할 수 있었다(RLock 은 프로세스-로컬이라
        # 부모·자식이 무경보 동시 쓰기). 획득 시점 PID 를 기록하고, PID 가 다르면 상속분
        # 참조를 끊고(닫지 않는다 — flock OFD 는 부모와 공유라 닫으면 부모 락을 건드린다)
        # 새로 획득을 시도한다: 부모가 살아 있으면 flock 이 막혀 시끄럽게 거부된다.
        if self._owner is not None and self._owner_pid == os.getpid():
            return
        self._owner = None
        if sys.platform == "win32":
            self._claim_windows_mutex()
        else:
            self._claim_posix_lock()
        self._owner_pid = os.getpid()

    def _claim_windows_mutex(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        digest = hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:24]
        handle = kernel32.CreateMutexW(None, False, f"hwpx-job-registry-writer-{digest}")
        error = ctypes.get_last_error()
        if not handle:
            raise JobRegistryOwnershipError(
                f"작업 저장소 writer 소유권을 확인할 수 없습니다 (WinError {error})."
            )
        if error == 183:  # ERROR_ALREADY_EXISTS — 다른 프로세스의 writer가 생존 중.
            kernel32.CloseHandle(handle)
            raise JobRegistryOwnershipError(
                "이 작업 저장소는 이미 다른 문서나르미 프로세스가 쓰고 있습니다. "
                "기존 앱을 닫은 뒤 다시 시도하세요."
            )
        self._owner = handle

    def _claim_posix_lock(self) -> None:
        import fcntl

        lock_root = Path(tempfile.gettempdir()) / "hwpx-tools-job-locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:24]
        stream = (lock_root / f"{digest}.lock").open("a+b")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise JobRegistryOwnershipError(
                "이 작업 저장소는 이미 다른 문서나르미 프로세스가 쓰고 있습니다. "
                "기존 앱을 닫은 뒤 다시 시도하세요."
            ) from exc
        self._owner = stream

    def __del__(self) -> None:
        owner = self._owner
        if owner is None:
            return
        try:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes

                close = ctypes.WinDLL("kernel32").CloseHandle
                close.argtypes = [wintypes.HANDLE]
                close.restype = wintypes.BOOL
                close(owner)
            else:
                owner.close()  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass


class _OwnedWriteLock:
    """RLock 호환 표면 + 첫 writer의 프로세스 소유권 확인."""

    def __init__(self, state: _RegistryWriteState):
        self._state = state

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        acquired = (
            self._state.lock.acquire(blocking)
            if timeout == -1
            else self._state.lock.acquire(blocking, timeout)
        )
        if not acquired:
            return False
        try:
            self._state.claim_process_ownership()
        except Exception:
            self._state.lock.release()
            raise
        return True

    def release(self) -> None:
        self._state.lock.release()

    def __enter__(self) -> "_OwnedWriteLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


_JOB_WRITE_STATES: "weakref.WeakValueDictionary[str, _RegistryWriteState]" = (
    weakref.WeakValueDictionary()
)
_JOB_WRITE_STATES_GUARD = threading.Lock()


def _directory_key(directory: Path) -> str:
    try:
        directory = directory.resolve()
    except OSError:
        pass
    return os.path.normcase(os.path.abspath(os.fspath(directory)))


def _shared_write_state(directory: Path) -> _RegistryWriteState:
    key = _directory_key(directory)
    with _JOB_WRITE_STATES_GUARD:
        state = _JOB_WRITE_STATES.get(key)
        if state is None:
            state = _RegistryWriteState(key)
            _JOB_WRITE_STATES[key] = state
        return state


class JobRegistry:
    """작업 레지스트리 — 디렉터리에 작업당 JSON 1개. 홈 화면의 데이터 원천.

    위치-불가지: 생성자가 디렉터리를 받는다(테스트는 ``tmp_path``, GUI 는 :func:`default_jobs_dir`).
    파일명은 작업 이름의 slug + ``.job.json``. slug 이 비단사라 서로 다른 이름이 같은 파일로
    매핑될 수 있다(예: ``a/b`` 와 ``a_b``). :meth:`save` 는 이 충돌을 조용히 덮지 않고
    :class:`JobSlugCollisionError` 로 loud raise 하며, 명시적 ``allow_overwrite=True`` 로만
    통과시킨다(confirm-or-alarm — 웹 에디터는 victim 을 재진술 확인한 뒤 opt-in).
    """

    SUFFIX = ".job.json"
    TRASH_RETENTION_DAYS = 30

    def __init__(self, directory: "str | Path"):
        self.directory = Path(directory)
        # **쓰기 직렬화 잠금**(RLock) — pywebview 는 API 호출을 스레드별로 돌리므로 서로 다른
        # 표면의 저장이 진짜로 겹친다. 이 잠금이 덮는 것은 단순 저장이 아니라 **읽기-수정-쓰기
        # 임계구역**이다(#129 리뷰 2R P1): 생성 스레드가 A 를 읽는 사이 에디터가 A 를 저장하면
        # 뒤늦은 저장이 상대의 변경을 통째로 되돌린다(lost update) — 스탬프가 매핑 편집을
        # 지우거나, 에디터 저장이 방금 찍은 ``last_run_at`` 을 지운다. 그래서 잠금은
        # 디렉터리 경로가 소유하고(같은 프로세스의 모든 registry instance 공유) 바깥 표면도
        # :meth:`write_lock` 으로 자기 임계구역을 이 잠금 안에 넣는다. 재진입 가능(RLock)이라
        # 잠금 안에서 :meth:`save` 를 불러도 자기 교착이 없다. 첫 writer 는 프로세스 소유권도
        # 함께 잡아 지원하지 않는 두 번째 프로세스의 쓰기를 파일 변경 전에 loud 거절한다(#192).
        self._write_state = _shared_write_state(self.directory)
        self._write_lock = _OwnedWriteLock(self._write_state)

    def path_for(self, name: str) -> Path:
        return self.directory / (_slug(name) + self.SUFFIX)

    def save(self, job: Job, *, allow_overwrite: bool = False) -> None:
        """작업을 저장한다. slug 충돌(다른 이름·같은 파일)은 loud 거부.

        대상 파일이 이미 **다른 작업 이름**으로 존재하거나 읽을 수 없으면(손상)
        ``allow_overwrite`` 없이는 :class:`SlugCollisionError` 를 던진다 —
        조용한 durable 소실 방지. 같은 이름 재저장(자기 갱신)은 충돌이 아니라 그대로 통과.

        **판본 정산의 유일한 자리**(재작성 F7, §10.13 판정 G): 저장 표면이 각자 올리면 한
        표면만 빠뜨려도 그 작업의 세대가 조용히 멈춘다 — 여기 한 곳에서 디스크의 직전 판본과
        대조해 :func:`advance_revisions` 가 오른 축만 올린다. 쓰기 잠금 안이라 대조와 쓰기
        사이에 다른 writer 가 끼지 않는다(같은 잠금이 ``last_run_at`` 스탬프도 직렬화한다).
        """
        with self._write_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path_for(job.name)
            if not allow_overwrite:
                guard_slug_collision(
                    path, job.name, lambda p: Job.load(p).name, kind="작업"
                )
            advance_revisions(job, self._previous_at(path))
            job.save(path)

    def _previous_at(self, path: Path) -> "Job | None":
        """저장 대상 자리의 직전 판본 — 없거나 **읽을 수 없으면** ``None``.

        손상 파일 위에 저장하는 경로(``allow_overwrite=True``)에서 예외를 올리면 저장 자체가
        막힌다 — 판본은 이력 메타지 저장의 전제가 아니다. 읽을 수 없는 과거를 추측해 잇는
        대신 인메모리 값으로 새로 세운다(없는 것을 지어내지 않는다).
        """
        try:
            return Job.load(path)
        except Exception:  # noqa: BLE001 — 부재·손상·권한: 잇지 않는다(위 docstring)
            return None

    def write_lock(self) -> "_OwnedWriteLock":
        """읽기-수정-쓰기 임계구역을 감쌀 디렉터리 공유 잠금.

        레지스트리 밖에서 "디스크를 읽고 → 그 값을 반영한 Job 을 만들어 → 저장"하는 표면
        (에디터 저장의 태그·``last_run_at`` 보존 재읽기)은 그 구간 전체를 이 잠금 안에 넣어야
        한다. 저장 한 번만 원자적인 것으로는 lost update 가 막히지 않는다 — 되돌리는 쪽은
        **읽은 시점이 낡은** 저장이기 때문이다. 같은 디렉터리를 보는 여러
        :class:`JobRegistry` 인스턴스도 이 잠금을 공유한다. 첫 writer는 프로세스 소유권까지
        얻으며, 다른 프로세스가 이미 소유 중이면 파일을 만지기 전에
        :class:`JobRegistryOwnershipError`로 거절한다(#192).
        """
        return self._write_lock

    def mutate(self, name: str, change) -> Job:
        """잠긴 단일 항목 읽기-수정-쓰기 — ``change(job)`` 이 필드를 고치고 저장까지 원자적.

        ``load → 고치기 → save(allow_overwrite=True)`` 선례(그룹 지정·스탬프)의 공용 몸통.
        갱신된 Job 을 돌려준다.
        """
        with self._write_lock:
            job = self.load(name)
            change(job)
            self.save(job, allow_overwrite=True)  # 같은 이름 재저장 = 자기 갱신
            return job

    def stamp_last_run(
        self, name: str, when: str, *, rules: "dict[str, str] | None" = None,
    ) -> Job:
        """완주 스탬프(#129) — 다른 writer 와 직렬화된 갱신.

        시각과 **검토 기준선**을 같은 잠긴 왕복에서 함께 찍는다(재작성 F5 판정 B): 완료
        이벤트가 둘로 갈라지면 이력과 검토 요구가 서로 다른 실행을 완주로 부른다(#129 가
        가드·이력을 한 술어로 묶은 것과 같은 근거).

        ``rules`` 는 **그 런이 실제로 쓴 규칙**의 지문이다(1R P1). 디스크의 지금 규칙으로
        찍으면 안 된다: 같은 프로세스의 에디터가 배치가 도는 사이 이 작업을 저장하면, 완주가
        **한 번도 실행·확인된 적 없는 새 규칙**을 검토받은 것으로 기록한다(조용한 승인 —
        되돌릴 수 없는 방향이다). 반대로 런의 규칙을 찍으면 디스크의 새 규칙과 어긋나
        검토 요구가 **그대로 선다**: 안전한 방향이라 이쪽이 정본이다.

        ``None`` 은 "무엇을 실행했는지 모른다"는 뜻이고, 그때는 기준선을 **건드리지 않는다** —
        디스크 규칙으로 대신 찍는 폴백을 두면 그 폴백이 곧 위 결함의 통로다(안전한 기본값이
        없는 인자는 필수로 두는 것이 낫다).
        """
        def _stamp(job: Job) -> None:
            job.last_run_at = when
            if rules is not None:
                job.reviewed_rules = dict(rules)

        return self.mutate(name, _stamp)

    def set_favorite(self, name: str, favorited: bool, when: "str | None" = None) -> Job:
        """즐겨찾기 지정/해제(§18.5) — 다른 writer 와 직렬화된 단일 필드 갱신.

        정렬 계약이 `favoritedAt` 최신순이라 bool 이 아니라 시각을 적는다. 해제는 ``""``.
        **이미 같은 상태면 시각을 다시 쓰지 않는다**: 같은 별을 다시 눌러도 순위가 조용히
        앞으로 튀지 않게(재지정 의도가 없는 왕복까지 순서를 흔들면 사용자가 만든 우선순위가
        클릭 노이즈에 진다).

        ``when=None`` 이면 시각을 **쓰기 잠금 안에서** 찍는다(리뷰 P2): 호출측이 미리 찍으면
        서로 다른 작업 둘을 연속으로 별 찍을 때 pywebview 의 스레드 스케줄링이 나중 클릭에
        이른 시각을 줄 수 있어 순위가 클릭 순서와 어긋난다. 잠금 안 스탬프는 **쓰기 순서 =
        시각 순서**를 담보한다. 명시 ``when`` 은 결정적 테스트용 경로다.
        """
        def _set(job: Job) -> None:
            if favorited:
                if not job.favorited_at:
                    job.favorited_at = (
                        when if when is not None else datetime.now().isoformat()
                    )
            else:
                job.favorited_at = ""

        return self.mutate(name, _set)

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()

    def load(self, name: str) -> Job:
        return Job.load(self.path_for(name))

    def clone(self, name: str) -> str:
        """작업 복제 — '<이름> (복사본[ N])' 유일 이름으로 저장하고 새 이름을 반환(F22).

        매핑 재사용의 단일 동선이다: 공유 베이스 프로파일을 걷어낸 자리를 「복제 후
        필요한 부분만 수정」이 맡는다. 템플릿·매핑·파일명 패턴·태그·그룹·기본 데이터 참조는
        그대로 계승하되(그룹 계승 = 복사본이 원본 옆 같은 구획에 뜬다, 결정 43 인접) **실행 이력(last_run_at)과 즐겨찾기(favorited_at)는 계승하지 않는다** — 복사본은 아직
        실행된 적도 사용자가 고른 적도 없다는 사실을 홈 카드·후보 순위가 그대로 말하게
        (조용한 이력·우선순위 위조 금지).
        원본 부재·손상은 loud raise(호출측이 재진술). 자리 선점 검사는 파일 존재
        기준(:meth:`path_for`)이라 slug 충돌 자리도 건너뛴다 — 후보가 비어 있을 때만
        저장하므로 :meth:`save` 의 slug 가드는 백스톱으로 남는다.

        **원자화(리뷰 P2)**: pywebview 는 호출마다 별도 스레드라 빠른 연속 클릭이 동시
        진입한다 — 후보 선택과 저장 사이 무잠금이면 여러 호출이 같은 '(복사본)' 을
        고르고(파일 1개만 남고 일부는 원자 쓰기 교체 경합으로 PermissionError) 이름이
        조용히 중복 반환된다. 선점 검사~저장을 디렉터리 공유 잠금으로 직렬화하고, 다른
        프로세스의 writer는 같은 경계에서 소유권 오류로 거절한다.
        """
        with self._write_lock:
            job = self.load(name)
            base = f"{name} (복사본)"
            candidate, i = base, 2
            while self.path_for(candidate).exists():
                candidate = f"{base[:-1]} {i})"  # '… (복사본)' → '… (복사본 2)'
                i += 1
            job.name = candidate
            job.last_run_at = ""
            # 즐겨찾기도 미계승(슬라이스 2): 복사본이 사용자가 고르지도 않은 우선순위로
            # 메인 Top 5 를 점유하면 즐겨찾기가 '사용자 우선순위'라는 정의(§19.2)를 잃는다.
            job.favorited_at = ""
            # 검토 기준선도 미계승(재작성 F5 판정 B): 복사본은 아직 어떤 문서도 만들지
            # 않았으므로 처음부터 검토 요구를 진다 — 원본의 완주를 물려받으면 한 번도
            # 확인받지 않은 규칙이 열린 게이트로 시작한다.
            job.reviewed_rules = {}
            # 판본도 미계승(재작성 F7 판정 H 의 짝): 복사본의 규칙은 이 identity 에서 처음
            # 저장되는 것이라 「연결 r7」이라고 말하면 겪지 않은 여섯 세대를 지어내는 것이고,
            # 직전 판본 값을 물려받으면 **이 작업에서 일어난 적 없는 변경**을 before/after
            # 증거가 보여준다. 새 자리 저장이라 :func:`advance_revisions` 는 손대지 않는다.
            job.template_revision = 1
            job.binding_revision = 1
            job.previous_rules = {}
            self.save(job)
            return candidate

    def rename(self, name: str, new_name: str) -> None:
        """작업 이름 변경(결정 43) — 새 파일 저장 **후** 옛 파일 제거(중단 시 소실 없음, 잉여만).

        자리 선점(다른 작업이 새 이름의 파일을 소유)은 loud ``ValueError`` — :meth:`save` 의
        slug 가드는 저장 이름과 파일 소유 이름이 같으면 자기-갱신으로 통과시키므로, 동명 작업
        위에 조용히 덮이는 구멍을 여기 명시 검사로 막는다. slug 동일(예: ``a/b``→``a_b``)이면
        같은 파일 제자리 갱신이라 삭제가 없다. 선점 검사~저장은 clone 과 같은 잠금으로
        직렬화한다(연속 조작의 이름 경합)."""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("이름이 비어 있습니다")
        if new_name == name:
            return
        with self._write_lock:
            job = self.load(name)
            src, dst = self.path_for(name), self.path_for(new_name)
            if dst != src and dst.exists():
                raise ValueError(f"이름 '{new_name}' 은(는) 이미 사용 중입니다")
            job.name = new_name
            self.save(job, allow_overwrite=(dst == src))
            if dst != src:
                src.unlink()

    def set_group(self, name: str, group: str) -> None:
        """그룹 지정/해제(``""``=「그룹 없음」) — 소속이 곧 생성(빈 그룹은 존재하지 않는다)."""
        def _set(job: Job) -> None:
            job.group = group.strip()

        self.mutate(name, _set)

    def groups(self) -> "list[str]":
        """존재하는(=소속 작업이 있는) 그룹 이름들, 이름순 — 이동 다이얼로그의 후보 목록."""
        return sorted({j.group for j in self.list_jobs() if j.group})

    def rename_group(self, name: str, new_name: str) -> int:
        """그룹 이름 일괄 변경 — 소속 작업 수 반환. 새 이름이 기존 그룹이면 결과는 병합이다
        (병합의 확인 재진술은 화면 게이트 소관 — 레지스트리는 기계적 일괄 갱신만 진다)."""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("그룹 이름이 비어 있습니다")
        return self._update_group_members(name, new_name)

    def disband_group(self, name: str) -> int:
        """그룹 해산(결정 43) — 소속 작업은 「그룹 없음」(``group=""``)으로. 소속 수 반환."""
        return self._update_group_members(name, "")

    def _update_group_members(self, name: str, new_group: str) -> int:
        if not name:
            # ""(그룹 없음)는 그룹이 아니라 부재다 — 일괄 갱신 대상으로 받으면 무그룹 전원이
            # 조용히 이동한다(호출 버그의 파급 상한을 loud 로 자른다).
            raise ValueError("대상 그룹 이름이 비어 있습니다")
        count = 0
        with self._write_lock:  # 일괄 갱신 전체가 한 임계구역(부분 반영 상태 노출 금지)
            for job in self.list_jobs():
                if job.group == name:
                    job.group = new_group
                    self.save(job, allow_overwrite=True)
                    count += 1
        return count

    def delete(self, name: str) -> None:
        """작업 삭제 — **쓰기 잠금 안**에서(리뷰 3R P1: 삭제도 writer 다).

        잠금 밖이면 다음 순서가 성립한다: ①스탬프가 잠금 안에서 A 를 읽고 ②삭제가 A 파일을
        지운 뒤 성공을 반환하고 ③스탬프가 그 사본을 저장해 **지운 작업이 되살아난다**.
        "삭제했다"고 말한 뒤 되살아나는 것은 조용한 소실의 거울상이라 같은 등급의 결함이다.
        """
        with self._write_lock:
            p = self.path_for(name)
            if p.exists():
                p.unlink()

    def soft_delete(self, name: str) -> "tuple[Path, Path]":
        """작업 파일을 30일 보존 휴지통으로 옮기고 복원 슬롯을 반환한다.

        삭제와 복원은 기존 writer 경계 안에서 수행한다. 휴지통은 레지스트리 루트의
        ``.trash``라 일반 목록 glob에 섞이지 않는다. 슬롯은 프로세스 메모리에만 노출되고,
        실제 파일은 비정상 종료 뒤에도 보존 기간 동안 남는다.

        사용자 문안은 이 보존을 「휴지통」이라 부르지 않는다(U2 §2.12, #345) — 도달 표면
        (목록·선별 복원·비우기)이 아직 없다(별건 #350). 어휘가 내려가도 30일 보존과
        ``_purge_trash`` 컷오프는 삭제가 상속하는 의무라 지우지 않는다.
        """
        with self._write_lock:
            src = self.path_for(name)
            if not src.exists():
                raise ValueError(f"작업을 찾을 수 없습니다: {name}")
            trash = self.directory / ".trash"
            trash.mkdir(parents=True, exist_ok=True)
            self._purge_trash(trash)
            dst = trash / f"{int(time.time())}-{uuid.uuid4().hex}-{src.name}"
            src.replace(dst)
            return src, dst

    def restore_soft_deleted(self, slot: "tuple[Path, Path]") -> str:
        """최근 소프트 삭제 슬롯을 원래 위치로 복원하고 작업 이름을 반환한다."""
        src, trashed = slot
        with self._write_lock:
            if not trashed.exists():
                # 「휴지통」 없이 말한다(U2 §2.12, #345) — 도달 표면이 없는 장소를 사용자
                # 문안에 세우지 않는다. 실패 사실(파일 부재)만 재진술한다.
                raise ValueError("되돌릴 작업 파일을 찾을 수 없습니다.")
            if src.exists():
                raise ValueError("같은 이름의 작업이 이미 있어 복원할 수 없습니다.")
            self.directory.mkdir(parents=True, exist_ok=True)
            trashed.replace(src)
            return Job.load(src).name

    def _purge_trash(self, trash: Path) -> None:
        cutoff = time.time() - self.TRASH_RETENTION_DAYS * 24 * 60 * 60
        for path in trash.glob("*" + self.SUFFIX):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                # 오래된 한 파일의 정리 실패가 지금 삭제를 막아서는 안 된다.
                continue

    def _files(self) -> "list[Path]":
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob("*" + self.SUFFIX))

    def list_jobs(
        self, *, corrupted: "list[tuple[Path, str]] | None" = None
    ) -> "list[Job]":
        """저장된 전 작업을 이름순으로. 빈/없는 디렉터리면 빈 리스트.

        **파일 단위 격리(RC-05, :func:`load_isolated` 공유):** 손상된 ``.job.json`` 1개가
        목록 전체(→홈·앱 시작)를 죽이지 않도록 파싱 실패를 파일별로 잡는다. ``corrupted``
        리스트를 넘기면 ``(경로, 오류 문자열)`` 로 수집되며, 홈이 이를 '손상됨' 행으로
        시끄럽게 표면화한다(확인-또는-경보). **미전달 시 손상 파일은 목록에서 제외된다**
        — 작업의 주 표면(홈)이 늘 수집·표면화하므로 부속 소비자(피커·참조수 집계)에선
        제외를 허용한다(데이터셋 풀은 이 관용이 C5 로 봉합돼 미전달=raise — 비대칭 유의).
        """
        jobs: "list[Job]" = load_isolated(
            self._files(), Job.load, corrupted if corrupted is not None else []
        )
        return sorted(jobs, key=lambda j: j.name)

    def names(self) -> "list[str]":
        return [j.name for j in self.list_jobs()]


# ------------------------------------------------------------ 실행(Run) 요청
@dataclass
class RunRequest:
    """한 작업의 1회 실행 — 일회성(저장 안 함). 데이터 겨눔 + 행 선택을 담는다.

    실행 로직(선택·매핑 적용·사전검증)을 Qt 밖에 두어 헤드리스 테스트한다
    (:class:`MappingModel`·:class:`SelectionModel` 이 위저드에 한 역할). 뷰(run_view)는 이
    메서드들을 호출만 한다. **매핑 재확정 없음** — 매핑은 작업 정의 때 이미 확정됐다.
    """

    job: Job
    datasource: "DataSource"
    selected_indices: "list[int]"

    def selected_records(self) -> "list[dict]":
        recs = self.datasource.records()
        return [recs[i] for i in self.selected_indices]

    def mapped_records(self, *, mark_missing: str = "") -> "list[dict]":
        """선택 레코드에 작업 매핑을 적용 → {템플릿필드: 값}. generate_batch 가 소비한다.

        ``mark_missing`` 이 주어지면(예: :data:`MISSING_MARKER`) **값이 빈 키만**
        ``mark_missing.format(field=키)`` 표식으로 치환한다 — 능동 빈칸 게이트의
        "표식 넣고 생성" 경로. 의도적 공란(매핑 비움 확정)은 프로파일이 키 자체를
        제외하므로 자동으로 표식이 없다. 표식은 비어 있지 않은 값이라 엔진의 빈값
        스킵을 통과해 누름틀에 주입되고, 누적치환 다음 패스에서 매핑되면 덮인다.
        기본값(빈 문자열)이면 기존 동작 그대로.

        수용 에지: 파일명 패턴이 ``{{빈필드}}`` 를 쓰면 표식이 파일명에 들어간다 —
        빈 키 파일명은 어차피 이상 신호라 시끄러운 쪽을 택한다.
        """
        mapped = self.job.mapping.apply_all(self.selected_records())
        if not mark_missing:
            return mapped
        return mark_missing_values(mapped, mark_missing)

    def source_report(self) -> ValidationReport:
        """소스키 사전검증 — 겨눈 DataSource 가 매핑이 읽는 키를 제공하는가.

        내포된 ``source_shape`` 를 실 소스와 대조하는 지점. 빠진 소스키는 *소스 수준*
        ``missing_columns`` 로 뜬다(매핑 출력만 보면 익명의 빈 필드로 뭉개져 어느 소스가
        빠졌는지 잃는다).
        """
        return validate(self.job.source_keys(), self.datasource.records())

    def output_report(self) -> ValidationReport:
        """출력 사전검증 — 매핑된 결과에 빈 값 필드. 실행 시점 '빈칸 허용?' 게이트의 근거.

        요구필드는 ``job.template_fields()``(매핑이 방출하는 집합)이지 ``engine.required_fields``
        가 아니다 — 후자는 사람이 **의도적으로 비운** 누름틀까지 되살려 매핑이 이미 해소한
        잡음을 재유입시킨다(실행 시 매핑 재확정 없음 원칙 위배).
        """
        return validate(self.job.template_fields(), self.mapped_records())
