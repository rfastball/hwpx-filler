"""공유 베이스 매핑 레지스트리 — 재사용 가능한 명명 :class:`MappingProfile` 의 홈 저장소.

ADR J 축2(닫힘): 인별 재작성 공수를 없애려 **공유 베이스 매핑**(정준 어휘)을 1회 선언하고
여러 템플릿·작업이 참조한다. 정준 이름셋 = **사람이 확정·소유하는 베이스 매핑의 필드 집합**
(별도 vocab 아티팩트 불필요). 베이스는 데이터·ServiceKey 를 담지 않는 **매핑 전용** 산출물이다.

저장물은 :class:`~hwpxfiller.core.mapping.MappingProfile` 자체다 — 이미 ``name`` + ``to_dict``/
``from_dict`` + JSON 관례(UTF-8·``ensure_ascii=False``·``indent=2``)를 갖춰 래퍼가 불필요하다.
레지스트리는 :class:`~hwpxfiller.core.job.JobRegistry`·:class:`~hwpxfiller.core.dataset_pool.
DatasetPoolRegistry` 의 위치-불가지 + slug 파일명 관례를 그대로 미러한다. Qt·엔진 비의존.
"""

from __future__ import annotations

import os
from pathlib import Path

from .job import _slug, guard_slug_collision, load_isolated
from .mapping import MappingProfile


def default_mapping_bases_dir() -> Path:
    """GUI 기본 베이스 매핑 레지스트리 위치 — 사용자 홈(``~/.hwpxfiller/mapping_bases``).

    작업·데이터셋·txt 템플릿과 동일 홈 관례(:func:`~hwpxfiller.core.job.default_jobs_dir`
    미러). ``HWPXFILLER_HOME`` 로 재지정 가능. 레지스트리 *클래스* 는 위치-불가지(생성자가
    디렉터리를 받는다) — 이 함수는 GUI 기본값 해석기일 뿐이다.
    """
    root = os.environ.get("HWPXFILLER_HOME") or (Path.home() / ".hwpxfiller")
    return Path(root) / "mapping_bases"


class MappingBaseRegistry:
    """공유 베이스 매핑 레지스트리 — 디렉터리에 베이스당 JSON 1개(:class:`~hwpxfiller.core.job.
    JobRegistry` 미러). 매핑 프로파일 관리 화면의 데이터 원천.

    위치-불가지: 생성자가 디렉터리를 받는다(테스트는 ``tmp_path``, GUI 는
    :func:`default_mapping_bases_dir`). 파일명은 베이스 이름 slug + ``.mapping.json``. slug 이
    비단사라 서로 다른 이름이 같은 파일로 매핑될 수 있어(예: ``a/b`` 와 ``a_b``)
    :meth:`save` 는 :class:`~hwpxfiller.core.job.SlugCollisionError` 로 loud raise 하며
    명시적 ``allow_overwrite=True`` 로만 통과시킨다(JobRegistry 미러, #34).
    """

    SUFFIX = ".mapping.json"

    def __init__(self, directory: "str | Path"):
        self.directory = Path(directory)

    def path_for(self, name: str) -> Path:
        return self.directory / (_slug(name) + self.SUFFIX)

    def save(self, profile: MappingProfile, *, allow_overwrite: bool = False) -> None:
        """베이스 매핑을 저장한다. slug 충돌(다른 이름·같은 파일)은 loud 거부.

        대상 파일이 이미 **다른 베이스 이름**으로 존재하거나 손상돼 소유를 확인할 수 없으면
        ``allow_overwrite`` 없이는 :class:`~hwpxfiller.core.job.SlugCollisionError` 를 던진다
        (조용한 durable 매핑 소실 방지). 같은 이름 재저장(자기 갱신)은 충돌이 아니라 통과.
        """
        if not profile.name:
            raise ValueError("매핑 프로파일 이름이 비어 있습니다.")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(profile.name)
        if not allow_overwrite:
            guard_slug_collision(
                path, profile.name, lambda p: MappingProfile.load(p).name,
                kind="매핑 프로파일",
            )
        profile.save(path)

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()

    def load(self, name: str) -> MappingProfile:
        return MappingProfile.load(self.path_for(name))

    def delete(self, name: str) -> None:
        p = self.path_for(name)
        if p.exists():
            p.unlink()

    def _files(self) -> "list[Path]":
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob("*" + self.SUFFIX), key=lambda p: p.name)

    def list_bases(
        self, *, corrupted: "list[tuple[Path, str]] | None" = None
    ) -> "list[MappingProfile]":
        """베이스 목록(이름순).

        **파일 단위 격리(RC-05, :func:`~hwpxfiller.core.job.load_isolated` 공유):**
        손상된 base 파일 1개(손편집·구버전·미지 transform)가 목록 전체(→매핑 프로파일
        관리 패널·셸 재진입 ``refresh()``)를 죽이지 않도록 파싱 실패를 파일별로 잡는다.
        ``corrupted`` 리스트를 넘기면 ``(경로, 오류 문자열)`` 로 수집되어 호출측이
        시끄럽게 표면화한다(확인-또는-경보). **미전달 시 손상 파일은 목록에서 제외된다**
        — 베이스의 관리 표면(에디터 프로파일 목록·워크벤치)이 늘 수집·표면화하므로
        부속 소비자에선 제외를 허용한다(데이터셋 풀은 이 관용이 C5 로 봉합돼
        미전달=raise — 비대칭 유의)."""
        bases: "list[MappingProfile]" = load_isolated(
            self._files(), MappingProfile.load, corrupted if corrupted is not None else []
        )
        bases.sort(key=lambda b: b.name)
        return bases

    def names(self) -> "list[str]":
        return [b.name for b in self.list_bases()]
