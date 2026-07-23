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
from pathlib import Path
from typing import TYPE_CHECKING

from .mapping import MappingProfile
from .paths import home_dir
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
    JobRegistry·DatasetPoolRegistry 가 :func:`guard_slug_collision` 로
    공유하는 단일 계약(#1 JobRegistry 에서 확립, #34 레지스트리 일반화).
    """


# 하위호환 별칭 — #1 이 도입한 이름. 기존 호출·테스트(webapp editor·test_job)가 잡던
# 예외 계약을 깨지 않도록 같은 클래스를 가리키게 둔다(`except JobSlugCollisionError` 유효).
JobSlugCollisionError = SlugCollisionError


def guard_slug_collision(path: Path, name: str, load_name, *, kind: str) -> None:
    """slug 충돌 loud 가드 — 저장 경계 공용(세 레지스트리 공유, #34).

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


def classify_existing(registry, name: str):
    """이름 자리(slug 파일)의 선점 상태 분류 — 동명 확인 승격·충돌 차단 게이트의 공용 판정.

    저장 전에 ``exists → load → 손상? → 이름 불일치? → 동명`` 사다리를 타는 화면 게이트
    (pool 수동 등록·에디터 데이터셋 자동등록)가 이 분류를 공유한다 —
    사본마다 확인 문구·비교 누락이 표류한 전력(e4ba3bd)을 봉인한다.

    ``registry`` 는 ``exists(name)``/``load(name)`` 을 가진 레지스트리
    (:class:`JobRegistry`·:class:`~hwpxfiller.core.dataset_pool.DatasetPoolRegistry`
    공통 표면).

    반환 ``(kind, item)``:

    - ``("absent", None)`` — 자리 비어 있음. 게이트 불필요, 바로 저장.
    - ``("same", item)`` — **같은 이름** 항목 존재. slug 가드는 자기-갱신으로 통과시켜
      조용한 덮어쓰기가 되므로, 호출측이 기존 내용을 재진술하고 **확인을 승격**해야 한다.
    - ``("collision", item)`` — **다른 이름·같은 slug 파일**. 덮어쓰기 경로를 열지 말고
      이름 변경만 안내한다(:func:`guard_slug_collision` 과 동일 판정 — ``item.name`` 이
      기존 소유자 이름).
    - ``("corrupt", None)`` — 자리 파일이 손상돼 소유 불명. 조용히 덮지 않는다
      (이름 변경 안내 또는 slug 가드의 loud 거절에 위임).
    """
    if not registry.exists(name):
        return ("absent", None)
    try:
        item = registry.load(name)
    except Exception:  # noqa: BLE001 — 손상: 소유 불명(추측 금지)
        return ("corrupt", None)
    if getattr(item, "name", "") != name:
        return ("collision", item)
    return ("same", item)


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

    **매체 교차 relink 는 예외** — 차단이 아니라 재확인이라 여기서 raise 하지 않고 화면 게이트가 받는다.
    """
    if job.template_path and job.media != "hwpx":
        where = "'기안' 화면 소관" if job.media == "txt" else "hwpx 아닌 템플릿"
        raise MediaMismatchError(
            f"작업 '{job.name}' 은(는) 이 hwpx 전용 경로를 쓸 수 없습니다 "
            f"({where} · 형식={job.media or '미상'} · 템플릿={job.template_path!r})"
        )
    return job


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
    # 브라우징용 분류 태그 {축이름 → 값}(차원-불가지·선택적, JOB_BROWSER_DESIGN D1·D2·D12·D13).
    # **순수 메타** — 코드는 "물품"·"금액구간"이 뭔지 모르고 얇은 매핑만 든다(run-path 무영향).
    # 축·값은 이름 문자열이지 enum/bool 타입 필드 발명 금지(도메인을 코드에 안 박는다).
    tags: "dict[str, str]" = field(default_factory=dict)
    # 좌 목록 사용자 그룹(앱 부여 1급 속성, R-info 1부 결정 5·R-flow 결정 43). ""=「그룹 없음」.
    # tags(브라우저 렌즈용 차원-불가지 축)와 별개다 — 그룹은 목록의 구조 자체라 전용 필드.
    # 소속이 곧 생성이고 해산은 ""(빈 그룹은 존재하지 않는다 — 퇴화 불변식).
    group: str = ""
    # 선택적 기본 데이터셋 참조(#53-A) = 데이터셋 풀 항목 이름(""=없음, 하위호환). 실행 화면이
    # 작업 선택 시 이 참조를 실행 시점에 다시 읽어 자동 조준하는 **조준 힌트**다 — 매핑의
    # 소스 키 계약(source_keys)이 실행의 진짜 게이트이지 이 참조가 아니다(파일이 월별로
    # 바뀌어도 헤더가 같으면 재사용). 참조가 유일 실행 의존이 되지 않게 한다.
    default_dataset_ref: str = ""

    @property
    def media(self) -> str:
        """이 작업의 매체 코드(``'hwpx'``/``'txt'``/``''``미상) — ``template_path`` 에서 유도(3부 결정 4).

        저장 필드가 아니다: 매체는 내재 속성이라 읽어낸다(그룹 같은 앱 부여 속성만 저장).
        분기 표면은 매체를 다 보는 「홈」 하나로 줄고, hwpx 전용 경로는 :func:`require_hwpx` 로 막는다.
        """
        return template_media(self.template_path)

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
            "filename_pattern": self.filename_pattern,
            "mapping": self.mapping.to_dict(),
            "last_run_at": self.last_run_at,
            "tags": dict(self.tags),
            "group": self.group,
            "default_dataset_ref": self.default_dataset_ref,
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
        return cls(
            name=_str("name"),
            template_path=_str("template_path"),
            mapping=MappingProfile.from_dict(d.get("mapping", {})),
            filename_pattern=_str("filename_pattern", DEFAULT_FILENAME_PATTERN),
            version=d.get("version", 1),
            # base_mapping_name(구 J3 공유 베이스 계보)은 F22 로 개념째 제거 — 구 JSON 의
            # 해당 키는 미지 키로 무시된다(가산 스키마 규율의 역방향, 하위호환 무해).
            last_run_at=_str("last_run_at"),
            tags=tags,
            group=_str("group"),
            default_dataset_ref=_str("default_dataset_ref"),
        )

    def save(self, path: "str | Path") -> None:
        # 원자 쓰기(RC-01) — 재저장 중 실패가 기존 작업 JSON 을 절단하지 않는다.
        write_text_atomic(path, json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: "str | Path") -> "Job":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def content_fingerprint(job: "Job") -> str:
    """저장 세션이 덮어쓰는 작업 **내용**의 지문 — 외부 변경 감지(자기-갱신 확인 게이트).

    태그·마지막 실행은 제외한다: 저장이 어차피 직전 디스크 값을 재읽어 보존하므로(홈 태그
    편집과의 공존) 그 둘의 변경은 파괴가 아니다. 나머지(템플릿·매핑·파일명 패턴·계보·기본
    데이터셋 참조)는 세션 상태로 덮어써지므로, 로드 시점과 달라져 있으면 '열어 둔 사이 외부
    변경'으로 확인을 요구해야 한다(무확인 파괴 금지). 에디터·「기안」 저장 두 표면이 같은
    지문을 쓰도록 코어에 둔다(복붙하면 한쪽만 고쳐지는 드리프트가 곧 조용한 파괴다)."""
    d = job.to_dict()
    d.pop("tags", None)
    d.pop("last_run_at", None)
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


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
                "이 작업 저장소는 이미 다른 HWPX Filler 프로세스가 쓰고 있습니다. "
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
                "이 작업 저장소는 이미 다른 HWPX Filler 프로세스가 쓰고 있습니다. "
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
        """
        with self._write_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path_for(job.name)
            if not allow_overwrite:
                guard_slug_collision(
                    path, job.name, lambda p: Job.load(p).name, kind="작업"
                )
            job.save(path)

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

    def stamp_last_run(self, name: str, when: str) -> Job:
        """마지막 실행 시각 스탬프(#129) — 다른 writer 와 직렬화된 단일 필드 갱신."""
        def _stamp(job: Job) -> None:
            job.last_run_at = when

        return self.mutate(name, _stamp)

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()

    def load(self, name: str) -> Job:
        return Job.load(self.path_for(name))

    def clone(self, name: str) -> str:
        """작업 복제 — '<이름> (복사본[ N])' 유일 이름으로 저장하고 새 이름을 반환(F22).

        매핑 재사용의 단일 동선이다: 공유 베이스 프로파일을 걷어낸 자리를 「복제 후
        필요한 부분만 수정」이 맡는다. 템플릿·매핑·파일명 패턴·태그·그룹·기본 데이터 참조는
        그대로 계승하되(그룹 계승 = 복사본이 원본 옆 같은 구획에 뜬다, 결정 43 인접) **실행 이력(last_run_at)은 계승하지 않는다** — 복사본은 아직
        실행된 적 없다는 사실을 홈 카드가 그대로 말하게(조용한 이력 위조 금지).
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
                raise ValueError("복원할 작업이 휴지통에 없습니다.")
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
