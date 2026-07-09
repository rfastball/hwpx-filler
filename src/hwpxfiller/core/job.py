"""작업(Job) 데이터모델 — 생성 의도의 앵커.

트랙 C UX 결정([[hwpx-filler-scope]]): 생성 의도는 데이터도 템플릿도 아닌 **저장된 "작업"**에
붙는다. 작업은 durable 바인딩 ``{템플릿, 매핑 프로파일, 파일명 패턴}``(양식 측 {T·M·N})이다.
데이터·행은 매 집행 일회성이라 **작업에 저장하지 않는다**.

- **한 겹.** 데이터 측은 :class:`~hwpxfiller.data.base.DataSource` 이음새로 추상 참조한다.
  누적치환(이전 출력을 소스로)·API 직결(미래)은 그 이음새 뒤의 *소스 종류*일 뿐 — 여기서 조인/
  데이터-뷰 계층을 세우지 않는다.
- **매핑은 작업 정의 때 1회 확정**(에디터의 명시성 게이트). 집행은 사전검증만 한다.
- ``source_shape``는 매핑 프로파일에 내포된다(별도 필드 없음) — :meth:`Job.source_keys` 가
  집행 시점에 그 형태를 실 DataSource 와 대조한다.

직렬화는 :class:`~hwpxfiller.core.mapping.MappingProfile` 의 JSON 관례(UTF-8·``ensure_ascii=False``·
``indent=2``·``to_dict``/``from_dict``)를 그대로 미러한다. 이 모듈은 Qt·엔진에 의존하지 않는다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .mapping import MappingProfile
from .validate import ValidationReport, validate

if TYPE_CHECKING:  # 런타임 결합 회피 — DataSource 는 덕타이핑으로 충분.
    from ..data.base import DataSource

# 레지스트리 파일명 slug — 파일시스템 금지문자만 정리(naming.clean_filename 과 동일 규칙).
_INVALID = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _slug(name: str) -> str:
    s = _INVALID.sub("_", name).strip()
    return s or "unnamed"


def default_jobs_dir() -> Path:
    """GUI 기본 작업 레지스트리 위치 — 사용자 홈(``~/.hwpxfiller/jobs``).

    작업은 작업 디렉터리·repo 체크아웃을 가로질러 살아남아야 하는 개인 durable 자산이라
    프로젝트-로컬이 아니라 홈에 둔다(패키징된 exe 엔 쓰기 가능한 프로젝트 폴더도 없다).
    ``HWPXFILLER_HOME`` 환경변수로 재지정 가능(테스트·CI·이식성). 레지스트리 *클래스* 자체는
    위치-불가지(생성자가 디렉터리를 받는다) — 이 함수는 GUI 기본값 해석기일 뿐이다.
    """
    root = os.environ.get("HWPXFILLER_HOME") or (Path.home() / ".hwpxfiller")
    return Path(root) / "jobs"


# ------------------------------------------------------------------ 모델
@dataclass
class Job:
    """저장되는 생성 작업 — durable 바인딩 {템플릿·매핑·파일명}. 데이터·행은 제외."""

    name: str = ""
    template_path: str = ""
    mapping: MappingProfile = field(default_factory=MappingProfile)
    filename_pattern: str = "output-{{ID}}"
    version: int = 1  # 전방호환 — 스키마 진화 시 마이그레이션 훅.

    def template_fields(self) -> "list[str]":
        """이 작업이 채우는 템플릿 필드(매핑이 방출하는 집합). 집행 사전검증의 요구필드."""
        return self.mapping.template_fields()

    def source_keys(self) -> "list[str]":
        """매핑이 읽는 소스 키 전체(문서순 중복제거). 실 DataSource 정합 검증의 대상."""
        seen: "dict[str, None]" = {}
        for m in self.mapping.mappings:
            for s in m.sources:
                seen.setdefault(s, None)
        return list(seen)

    # ------------------------------------------------------------ 직렬화
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "name": self.name,
            "template_path": self.template_path,
            "filename_pattern": self.filename_pattern,
            "mapping": self.mapping.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        return cls(
            name=d.get("name", ""),
            template_path=d.get("template_path", ""),
            mapping=MappingProfile.from_dict(d.get("mapping", {})),
            filename_pattern=d.get("filename_pattern", "output-{{ID}}"),
            version=d.get("version", 1),
        )

    def save(self, path: "str | Path") -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: "str | Path") -> "Job":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


class JobRegistry:
    """작업 레지스트리 — 디렉터리에 작업당 JSON 1개. 홈 화면의 데이터 원천.

    위치-불가지: 생성자가 디렉터리를 받는다(테스트는 ``tmp_path``, GUI 는 :func:`default_jobs_dir`).
    파일명은 작업 이름의 slug + ``.job.json``. **주의(스캐폴드 수용):** slug 이 같은 서로 다른
    이름은 파일이 충돌한다(예: ``a/b`` 와 ``a_b``) — 실사용에서 드물고 후일 보강.
    """

    SUFFIX = ".job.json"

    def __init__(self, directory: "str | Path"):
        self.directory = Path(directory)

    def path_for(self, name: str) -> Path:
        return self.directory / (_slug(name) + self.SUFFIX)

    def save(self, job: Job) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        job.save(self.path_for(job.name))

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()

    def load(self, name: str) -> Job:
        return Job.load(self.path_for(name))

    def delete(self, name: str) -> None:
        p = self.path_for(name)
        if p.exists():
            p.unlink()

    def _files(self) -> "list[Path]":
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob("*" + self.SUFFIX))

    def list_jobs(self) -> "list[Job]":
        """저장된 전 작업을 이름순으로. 빈/없는 디렉터리면 빈 리스트."""
        return sorted((Job.load(p) for p in self._files()), key=lambda j: j.name)

    def names(self) -> "list[str]":
        return [j.name for j in self.list_jobs()]


# ------------------------------------------------------------ 집행(Run) 요청
@dataclass
class RunRequest:
    """한 작업의 1회 집행 — 일회성(저장 안 함). 데이터 겨눔 + 행 선택을 담는다.

    집행 로직(선택·매핑 적용·사전검증)을 Qt 밖에 두어 헤드리스 테스트한다
    (:class:`MappingModel`·:class:`SelectionModel` 이 위저드에 한 역할). 뷰(run_view)는 이
    메서드들을 호출만 한다. **매핑 재확정 없음** — 매핑은 작업 정의 때 이미 확정됐다.
    """

    job: Job
    datasource: "DataSource"
    selected_indices: "list[int]"

    def selected_records(self) -> "list[dict]":
        recs = self.datasource.records()
        return [recs[i] for i in self.selected_indices]

    def mapped_records(self) -> "list[dict]":
        """선택 레코드에 작업 매핑을 적용 → {템플릿필드: 값}. generate_batch 가 소비한다."""
        return self.job.mapping.apply_all(self.selected_records())

    def source_report(self) -> ValidationReport:
        """소스키 사전검증 — 겨눈 DataSource 가 매핑이 읽는 키를 제공하는가.

        내포된 ``source_shape`` 를 실 소스와 대조하는 지점. 빠진 소스키는 *소스 수준*
        ``missing_columns`` 로 뜬다(매핑 출력만 보면 익명의 빈 필드로 뭉개져 어느 소스가
        빠졌는지 잃는다).
        """
        return validate(self.job.source_keys(), self.datasource.records())

    def output_report(self) -> ValidationReport:
        """출력 사전검증 — 매핑된 결과에 빈 값 필드. 집행 시점 '빈칸 허용?' 게이트의 근거.

        요구필드는 ``job.template_fields()``(매핑이 방출하는 집합)이지 ``engine.required_fields``
        가 아니다 — 후자는 사람이 **의도적으로 비운** 누름틀까지 되살려 매핑이 이미 해소한
        잡음을 재유입시킨다(집행 시 매핑 재확정 없음 원칙 위배).
        """
        return validate(self.job.template_fields(), self.mapped_records())
