"""작업(Job) 데이터모델 — 생성 의도의 앵커.

트랙 C UX 결정([[hwpx-filler-scope]]): 생성 의도는 데이터도 템플릿도 아닌 **저장된 "작업"**에
붙는다. 작업은 durable 바인딩 ``{템플릿, 매핑 프로파일, 파일명 패턴}``(양식 측 {T·M·N})이다.
데이터·행은 매 실행 일회성이라 **작업에 저장하지 않는다**.

- **한 겹.** 데이터 측은 :class:`~hwpxfiller.domain.data_source.DataSource` 이음새로 추상 참조한다.
  누적치환(이전 출력을 소스로)·API 직결(미래)은 그 이음새 뒤의 *소스 종류*일 뿐 — 여기서 조인/
  데이터-뷰 계층을 세우지 않는다.
- **매핑은 작업 정의 때 1회 확정**(에디터의 명시성 게이트). 실행은 사전검증만 한다.
- ``source_shape``는 매핑 프로파일에 내포된다(별도 필드 없음) — :meth:`Job.source_keys` 가
  실행 시점에 그 형태를 실 DataSource 와 대조한다.

직렬화·레지스트리(durable JSON encode/decode·원자 쓰기 개시·디렉터리 레지스트리)는
P2-21(#569)에서 :mod:`hwpxfiller.external.job_store` 로, writer lease(프로세스 소유권)는
:mod:`hwpxfiller.host.job_writer_lease` 로 승계됐다 — 이 모듈은 모델·판정(순수 계산)만 남고
Qt·엔진·디스크에 의존하지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING

from .mapping import MappingProfile
from ..domain.validation import ValidationReport, validate

if TYPE_CHECKING:  # 런타임 결합 회피 — DataSource 는 덕타이핑으로 충분.
    from ..domain.data_source import DataSource

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

# (_slug·SlugCollisionError·JobSlugCollisionError·guard_slug_collision 은 P2-21(#569)에서
#  저장 경계와 함께 :mod:`hwpxfiller.external.job_store` 로 승계.)


def load_isolated(paths, loader, corrupted):
    """손상 격리 로드 루프 — 세 레지스트리 목록 메서드의 공용 몸통(RC-05 단일 출처).

    예전엔 이 try/except-수집 루프가 :meth:`JobRegistry.list_jobs`·:meth:`~hwpxfiller.external.
    dataset_store.DatasetPoolRegistry.list_items` 등에 바이트 단위로 복붙돼 있었다 —
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
#  (:func:`~hwpxfiller.domain.dataset_reference.excel_identity`)으로 바뀌며 둘 다 죽었다.
#  작업 축 slug 가드(:func:`guard_slug_collision`)는 그대로다.)


# (default_jobs_dir 는 P2-17(#565)에서 Host 로 승격 — :func:`hwpxfiller.host.locations.default_jobs_dir`.
#  레지스트리 *클래스* 는 위치-불가지라 이 모듈엔 기본값 해석이 남지 않는다.)


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


# (library_root_for — 「이식성의 경첩」 — 는 P2-21(#569)에서 홈 해석과 함께
#  :func:`hwpxfiller.host.locations.library_root_for` 로 승계.)


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


# (library_key_for 는 P2-21(#569)에서 직렬화와 함께 :func:`hwpxfiller.external.job_store.
#  library_key_for` 로 승계.)


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


# (resolve_library_key 는 P2-21(#569)에서 로드 경계와 함께 :func:`hwpxfiller.external.
#  job_store.resolve_library_key` 로 승계.)


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

    # (template_key 파생 property 는 P2-21(#569)에서 소비자가 직렬화뿐이라 property 를 걷고
    #  :func:`hwpxfiller.external.job_store.library_key_for` 호출로 승계.)

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

    # (직렬화 to_dict/from_dict/save/load 는 P2-21(#569)에서 :func:`hwpxfiller.external.
    #  job_store.encode_job`/`decode_job`/`save_job`/`load_job` 으로 승계 — dict 키 순서·값·
    #  저장 bytes 완전 동일.)


# (content_fingerprint 는 P2-21(#569)에서 직렬화와 함께 :func:`hwpxfiller.external.job_store.
#  content_fingerprint` 로 승계.)


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
        # 절대경로 유지는 위 선언의 실행부다(#348 · #368 P2) — 상대키
        # (:func:`hwpxfiller.external.job_store.library_key_for`)로
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


# (JobRegistryOwnershipError·_RegistryWriteState·_OwnedWriteLock·shared_write_state — 프로세스
#  writer lease — 는 P2-21(#569)에서 :mod:`hwpxfiller.host.job_writer_lease` 로,
#  JobRegistry 는 :mod:`hwpxfiller.external.job_store` 로 승계.)


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
