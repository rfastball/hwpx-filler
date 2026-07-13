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

from .job import _slug
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
    :func:`default_mapping_bases_dir`). 파일명은 베이스 이름 slug + ``.mapping.json``.
    """

    SUFFIX = ".mapping.json"

    def __init__(self, directory: "str | Path"):
        self.directory = Path(directory)

    def path_for(self, name: str) -> Path:
        return self.directory / (_slug(name) + self.SUFFIX)

    def save(self, profile: MappingProfile) -> None:
        if not profile.name:
            raise ValueError("매핑 프로파일 이름이 비어 있습니다.")
        self.directory.mkdir(parents=True, exist_ok=True)
        profile.save(self.path_for(profile.name))

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

    def list_bases(self) -> "list[MappingProfile]":
        """베이스 목록(이름순). 손상 파일은 감추지 않고 예외 전파(호출측이 표면화)."""
        bases = [MappingProfile.load(p) for p in self._files()]
        bases.sort(key=lambda b: b.name)
        return bases

    def names(self) -> "list[str]":
        return [b.name for b in self.list_bases()]
