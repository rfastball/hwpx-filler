"""Job 영속 경계 — durable JSON 직렬화·저장 개시·레지스트리(External Adapter, P2-21 #569).

:mod:`hwpxfiller.core.job` 이 들고 있던 저장 개시(원자 쓰기)·durable encode/decode·
디렉터리 레지스트리를 원문 이동으로 승계한다. 판정·모델(:class:`~hwpxfiller.core.job.Job`·
rules 계열·매체 가드)은 Domain 에 남고, 여기는 그 값을 디스크와 오가게 하는 어댑터다.

직렬화는 :class:`~hwpxfiller.core.mapping.MappingProfile` 의 JSON 관례(UTF-8·
``ensure_ascii=False``·``indent=2``·``to_dict``/``from_dict``)를 그대로 미러한다.
구 ``Job.to_dict``/``from_dict``/``save``/``load`` 는 :func:`encode_job`/
:func:`decode_job`/:func:`save_job`/:func:`load_job` 이 됐다 — dict 키 순서·값·저장
bytes 는 완전 동일하다.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from hwpxcore.atomic import write_text_atomic
from hwpxfiller.core.job import (
    DEFAULT_FILENAME_PATTERN,
    Job,
    _copy_rules_values,
    _reject_unsafe_key,
    _rules_values_or_raise,
    advance_revisions,
    library_rel_key,
    load_isolated,
)
from hwpxfiller.core.mapping import MappingProfile
from hwpxfiller.host.job_writer_lease import _OwnedWriteLock, shared_write_state
from hwpxfiller.host.locations import library_root_for

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


def library_key_for(template_path: str) -> str:
    """템플릿 경로 → 라이브러리 루트 상대키. 루트 밖·미상 매체는 ``""``(승격 실패 = 절대경로 유지)."""
    return library_rel_key(template_path, library_root_for(template_path)) or ""


def resolve_library_key(key: str) -> str:
    """상대키 → **지금** 홈 기준 절대경로 문자열. 빈 키·미상 매체는 ``""``(호출측이 옛 경로 폴백).

    해석은 순수 경로 계산이다 — 파일이 실제로 있는지는 보지 않는다(부재는 라이브러리의
    「연결 안 됨」 표면이 이미 말한다). 디스크를 읽지도 쓰지도 않으므로 **읽기가 조용히
    저장을 승격시키는 일이 없다**: 승격은 :func:`encode_job` 을 지나는 저장에서만 일어난다.
    """
    if not key:
        return ""
    _reject_unsafe_key(key)
    root = library_root_for(key)
    if root is None:
        return ""
    return str(root / key)


# ------------------------------------------------------------------ 직렬화
def encode_job(job: Job) -> dict:
    """구 ``Job.to_dict`` — dict 키 순서·값 완전 동일(bytes 불변, P2-21 #569)."""
    return {
        "version": job.version,
        "name": job.name,
        "template_path": job.template_path,
        # 라이브러리 루트 상대키(#348) — **가산** 필드다: 절대경로도 그대로 함께 쓴다.
        # 구 코드는 새 키를 무시하고 경로로 계속 열리고, 신 코드는 키를 우선해 홈이
        # 옮겨져도 해석된다. 루트 밖 템플릿에선 ``""`` 라 경로만이 링크다(폴백 없음).
        "template_key": library_key_for(job.template_path),
        "filename_pattern": job.filename_pattern,
        "mapping": job.mapping.to_dict(),
        "last_run_at": job.last_run_at,
        "favorited_at": job.favorited_at,
        "tags": dict(job.tags),
        "group": job.group,
        "reviewed_rules": dict(job.reviewed_rules),
        "template_revision": job.template_revision,
        "binding_revision": job.binding_revision,
        "previous_rules": _copy_rules_values(job.previous_rules),
    }


def decode_job(d: dict) -> Job:
    """durable 로드 경계(구 ``Job.from_dict``) — 누락 필드는 ``.get(기본값)`` 으로 하위호환
    (구 JSON→기본값)하되, **존재하는데 타입이 깨진** durable 값(문자열 계약 필드가
    int/list/null 등)은 조용히 통과시키지 않고 loud 하게 던진다. 앱은 늘 str/에스케이프된
    값만 쓰므로 타입 불일치는 외부 훼손·버그 신호다 — 여기서 격리하면
    :meth:`JobRegistry.list_jobs` 의 파일단위 격리(RC-05)가 '손상됨' 행으로 표면화한다.
    무검증 대입은 손상 값을 조용히 통과시켜 뒤늦게 무관한 홈 렌더(혼합타입 ``sorted()``·
    ``_fmt_iso``)를 터뜨리는 지뢰가 됐다(confirm-or-alarm: 조기 loud 격리 > 지연
    크래시/무성 오염)."""
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
    return Job(
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


def save_job(path: "str | Path", job: Job) -> None:
    """구 ``Job.save`` — 원자 쓰기(RC-01): 재저장 중 실패가 기존 작업 JSON 을 절단하지 않는다."""
    write_text_atomic(path, json.dumps(encode_job(job), ensure_ascii=False, indent=2))


def load_job(path: "str | Path") -> Job:
    """구 ``Job.load`` — durable JSON 을 읽어 :func:`decode_job` 경계를 통과시킨다."""
    return decode_job(json.loads(Path(path).read_text(encoding="utf-8")))


def content_fingerprint(job: Job) -> str:
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
    지문을 쓰도록 한 곳에 둔다(복붙하면 한쪽만 고쳐지는 드리프트가 곧 조용한 파괴다)."""
    d = encode_job(job)
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


class JobRegistry:
    """작업 레지스트리 — 디렉터리에 작업당 JSON 1개. 홈 화면의 데이터 원천.

    위치-불가지: 생성자가 디렉터리를 받는다(테스트는 ``tmp_path``, GUI 는
    :func:`hwpxfiller.host.locations.default_jobs_dir`).
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
        self._write_state = shared_write_state(self.directory)
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
        대조해 :func:`~hwpxfiller.core.job.advance_revisions` 가 오른 축만 올린다. 쓰기 잠금
        안이라 대조와 쓰기 사이에 다른 writer 가 끼지 않는다(같은 잠금이 ``last_run_at``
        스탬프도 직렬화한다).
        """
        with self._write_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path_for(job.name)
            if not allow_overwrite:
                guard_slug_collision(
                    path, job.name, lambda p: load_job(p).name, kind="작업"
                )
            advance_revisions(job, self._previous_at(path))
            save_job(path, job)

    def _previous_at(self, path: Path) -> "Job | None":
        """저장 대상 자리의 직전 판본 — 없거나 **읽을 수 없으면** ``None``.

        손상 파일 위에 저장하는 경로(``allow_overwrite=True``)에서 예외를 올리면 저장 자체가
        막힌다 — 판본은 이력 메타지 저장의 전제가 아니다. 읽을 수 없는 과거를 추측해 잇는
        대신 인메모리 값으로 새로 세운다(없는 것을 지어내지 않는다).
        """
        try:
            return load_job(path)
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
        :class:`~hwpxfiller.host.job_writer_lease.JobRegistryOwnershipError`로 거절한다(#192).
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
        return load_job(self.path_for(name))

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
            # 증거가 보여준다. 새 자리 저장이라 :func:`~hwpxfiller.core.job.advance_revisions`
            # 는 손대지 않는다.
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
            return load_job(src).name

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

        **파일 단위 격리(RC-05, :func:`~hwpxfiller.core.job.load_isolated` 공유):** 손상된
        ``.job.json`` 1개가 목록 전체(→홈·앱 시작)를 죽이지 않도록 파싱 실패를 파일별로
        잡는다. ``corrupted`` 리스트를 넘기면 ``(경로, 오류 문자열)`` 로 수집되며, 홈이 이를
        '손상됨' 행으로 시끄럽게 표면화한다(확인-또는-경보). **미전달 시 손상 파일은 목록에서
        제외된다** — 작업의 주 표면(홈)이 늘 수집·표면화하므로 부속 소비자(피커·참조수
        집계)에선 제외를 허용한다(데이터셋 풀은 이 관용이 C5 로 봉합돼 미전달=raise —
        비대칭 유의).
        """
        jobs: "list[Job]" = load_isolated(
            self._files(), load_job, corrupted if corrupted is not None else []
        )
        return sorted(jobs, key=lambda j: j.name)

    def names(self) -> "list[str]":
        return [j.name for j in self.list_jobs()]
