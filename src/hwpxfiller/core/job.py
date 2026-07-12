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

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .mapping import MappingProfile
from hwpxcore.atomic import write_text_atomic
from hwpxcore.validate import ValidationReport, validate

if TYPE_CHECKING:  # 런타임 결합 회피 — DataSource 는 덕타이핑으로 충분.
    from ..data.base import DataSource

# 미충족 공란 표식 — grep 가능 표적의 단일 출처(로드맵 ⑤ 출력검증 = 이 표식 grep).
# "누락은 시끄럽게"의 출력 짝: 있어야 할 값이 빈 필드에만 주입되고(의도적 공란은 매핑이
# 이미 키를 제외해 자동 면제), 누적치환의 다음 패스에서 그 필드가 매핑되면 덮인다.
MISSING_MARKER = "〘미입력·{field}〙"

# 출력 파일명 패턴 기본값 — 단일 출처(RC-20). dataclass 기본·from_dict 하위호환·
# 작업 에디터 프리필·CLI --pattern 이 전부 이 상수를 참조한다. 값은 사용자-가시
# 표면(에디터 프리필·디자인 목업)이 써온 '공고서-{{ID}}' — 화면에 등장한 적 없는
# 값이 파일명을 결정하는 조용한 폴백을 없앤다.
DEFAULT_FILENAME_PATTERN = "공고서-{{ID}}"


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
    # 이 작업의 매핑을 시드한 공유 베이스 이름(J3 계보, ""=베이스 무관). **순수 메타** —
    # 엔진은 여전히 합성된 ``mapping`` 만 소비한다(run-path 무영향). 베이스 편집 시 "이 베이스를
    # 참조하는 작업 N개" loud 경고의 근거(전파는 경고이지 자동 재투영 아님).
    base_mapping_name: str = ""

    def template_fields(self) -> "list[str]":
        """이 작업이 채우는 템플릿 필드(매핑이 방출하는 집합). 실행 사전검증의 요구필드."""
        return self.mapping.template_fields()

    def source_keys(self) -> "list[str]":
        """매핑이 읽는 소스 키 전체(문서순 중복제거). 실 DataSource 정합 검증의 대상."""
        seen: "dict[str, None]" = {}
        for m in self.mapping.mappings:
            if m.is_blank:
                # malformed/구 프로파일이 blank에 sources를 남겨도 의도 선언은
                # 소스 요구가 아니다. source drift와 실제 출력이 갈리지 않게 제외.
                continue
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
            "last_run_at": self.last_run_at,
            "base_mapping_name": self.base_mapping_name,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        return cls(
            name=d.get("name", ""),
            template_path=d.get("template_path", ""),
            mapping=MappingProfile.from_dict(d.get("mapping", {})),
            filename_pattern=d.get("filename_pattern", DEFAULT_FILENAME_PATTERN),
            version=d.get("version", 1),
            last_run_at=d.get("last_run_at", ""),
            base_mapping_name=d.get("base_mapping_name", ""),
        )

    def save(self, path: "str | Path") -> None:
        # 원자 쓰기(RC-01) — 재저장 중 실패가 기존 작업 JSON 을 절단하지 않는다.
        write_text_atomic(path, json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

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

    def list_jobs(
        self, *, corrupted: "list[tuple[Path, str]] | None" = None
    ) -> "list[Job]":
        """저장된 전 작업을 이름순으로. 빈/없는 디렉터리면 빈 리스트.

        **파일 단위 격리(RC-05):** 손상된 ``.job.json`` 1개가 목록 전체(→홈·앱 시작)를
        죽이지 않도록 파싱 실패를 파일별로 잡는다. 손상 항목은 결과에서 제외하되
        조용히 버리지 않는다 — ``corrupted`` 리스트를 넘기면 ``(경로, 오류 문자열)``
        로 수집되며, 홈이 이를 '손상됨' 행으로 시끄럽게 표면화한다(확인-또는-경보).
        """
        jobs: "list[Job]" = []
        for p in self._files():
            try:
                jobs.append(Job.load(p))
            except Exception as exc:  # noqa: BLE001 — 손상 1개의 전멸 방지(격리 후 표면화)
                if corrupted is not None:
                    corrupted.append((p, str(exc)))
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
