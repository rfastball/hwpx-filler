"""데이터셋 풀 — durable 데이터 *참조*(스냅샷 아님)의 홈 레지스트리.

ADR J 축확정: 데이터 수명 = 계약 사이클(발주~지급, 최소 60일)이라 세션-일회 recents 로는
부족 → 데이터는 **durable 풀 항목**이되 **연결/참조**(엑셀 경로·나라 쿼리)로만 저장하고
실행 때 재읽기("싱크")한다. 사이클 종료 = **아카이브/은퇴**(add/delete 아닌 retire).
"데이터·행 미저장" 불변식(포인터만 직렬화)을 유지한다 — 풀 항목은 **소스를 어떻게 다시
여는가**(kind + opts)만 담고 레코드는 담지 않는다.

**보안 불변식**([[confirm-or-alarm-principle]]): 나라장터 항목은 **ServiceKey 를 담지
않는다**. opts 는 쿼리(기간·건수·페이지)뿐이고, 키는 실행 복원 시점에만 OS 자격증명 저장소
(N1 SecretStore)에서 주입한다(복원 로직은 :func:`~hwpxfiller.data.factory.source_from_pool_item`).

직렬화는 :class:`~hwpxfiller.core.job.Job` 의 JSON 관례(UTF-8·``ensure_ascii=False``·``indent=2``·
``to_dict``/``from_dict``·가산 필드 하위호환)를 그대로 미러한다. 레지스트리도 :class:`~hwpxfiller.
core.job.JobRegistry` 를 미러(위치-불가지 생성자 + slug 파일명). Qt·엔진 비의존.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .job import _slug, guard_slug_collision
from hwpxcore.atomic import write_text_atomic

# 항목 상태 — active(실행 대상) / archived(사이클 유휴, 복구 가능) / retired(은퇴, 숨김).
# add/delete 가 아니라 retire 로 수명 종료를 표현한다(참조는 남기되 실행 후보에서 제외).
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
STATUS_RETIRED = "retired"
_STATUSES = (STATUS_ACTIVE, STATUS_ARCHIVED, STATUS_RETIRED)


def default_dataset_pool_dir() -> Path:
    """GUI 기본 데이터셋 풀 레지스트리 위치 — 사용자 홈(``~/.hwpxfiller/datasets``).

    작업·txt 템플릿과 동일 홈 관례(:func:`~hwpxfiller.core.job.default_jobs_dir` 미러).
    ``HWPXFILLER_HOME`` 로 재지정 가능. 레지스트리 *클래스* 는 위치-불가지(생성자가 디렉터리
    를 받는다) — 이 함수는 GUI 기본값 해석기일 뿐이다.
    """
    root = os.environ.get("HWPXFILLER_HOME") or (Path.home() / ".hwpxfiller")
    return Path(root) / "datasets"


# ------------------------------------------------------------------ 모델
@dataclass
class DatasetPoolItem:
    """데이터셋 풀 1항목 — 소스를 다시 여는 **참조**(kind + opts) + 수명 상태.

    스키마 진화 규율: 가산 필드는 version 무증가(``from_dict`` 의 ``.get`` 하위호환).

    **``opts`` 규약(참조만, 데이터·비밀 없음):**
    - ``kind="excel"``: ``{"path": ..., ["sheet": ...], ["header_row": ...]}``.
    - ``kind="nara"``:  ``{"bgn_dt": ..., "end_dt": ..., ["num_rows": ...], ["page_no": ...]}``.
      **``service_key`` 는 절대 담지 않는다**(복원 시 OS 저장소에서 주입).
    """

    name: str
    kind: str  # "excel" | "nara"
    opts: "dict[str, object]" = field(default_factory=dict)
    status: str = STATUS_ACTIVE
    created_at: str = ""
    note: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"알 수 없는 데이터셋 상태입니다: {self.status!r}")

    # ----------------------------------------------------------- 상태 전이(순수)
    def archive(self) -> None:
        self.status = STATUS_ARCHIVED

    def retire(self) -> None:
        self.status = STATUS_RETIRED

    def activate(self) -> None:
        self.status = STATUS_ACTIVE

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE

    # ------------------------------------------------------------ 직렬화
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "name": self.name,
            "kind": self.kind,
            "opts": dict(self.opts),
            "status": self.status,
            "created_at": self.created_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DatasetPoolItem":
        return cls(
            name=d.get("name", ""),
            kind=d.get("kind", ""),
            opts=dict(d.get("opts", {})),
            status=d.get("status", STATUS_ACTIVE),
            created_at=d.get("created_at", ""),
            note=d.get("note", ""),
            version=d.get("version", 1),
        )

    def save(self, path: "str | Path") -> None:
        # 원자 쓰기(RC-01) — 저장 중 실패가 기존 풀 항목 JSON 을 파괴하지 않는다.
        write_text_atomic(path, json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: "str | Path") -> "DatasetPoolItem":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ------------------------------------------------------------------ 레지스트리
class DatasetPoolRegistry:
    """데이터셋 풀 레지스트리 — 디렉터리에 항목당 JSON 1개(:class:`~hwpxfiller.core.job.
    JobRegistry` 미러). 홈 대시보드 데이터 풀 표면의 데이터 원천.

    위치-불가지: 생성자가 디렉터리를 받는다(테스트는 ``tmp_path``, GUI 는
    :func:`default_dataset_pool_dir`). 파일명은 이름 slug + ``.dataset.json``. slug 이
    비단사라 서로 다른 이름이 같은 파일로 매핑될 수 있어(예: ``a/b`` 와 ``a_b``)
    :meth:`save` 는 :class:`~hwpxfiller.core.job.SlugCollisionError` 로 loud raise 하며
    명시적 ``allow_overwrite=True`` 로만 통과시킨다(JobRegistry 미러, #34).
    """

    SUFFIX = ".dataset.json"

    def __init__(self, directory: "str | Path"):
        self.directory = Path(directory)

    def path_for(self, name: str) -> Path:
        return self.directory / (_slug(name) + self.SUFFIX)

    def save(self, item: DatasetPoolItem, *, allow_overwrite: bool = False) -> None:
        """항목을 저장한다. slug 충돌(다른 이름·같은 파일)은 loud 거부.

        대상 파일이 이미 **다른 항목 이름**으로 존재하거나 손상돼 소유를 확인할 수 없으면
        ``allow_overwrite`` 없이는 :class:`~hwpxfiller.core.job.SlugCollisionError` 를 던진다
        (조용한 durable 참조 소실 방지). 같은 이름 재저장(상태 전이 등)은 충돌이 아니라 통과.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(item.name)
        if not allow_overwrite:
            guard_slug_collision(
                path, item.name, lambda p: DatasetPoolItem.load(p).name, kind="데이터셋"
            )
        item.save(path)

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()

    def load(self, name: str) -> DatasetPoolItem:
        return DatasetPoolItem.load(self.path_for(name))

    def delete(self, name: str) -> None:
        p = self.path_for(name)
        if p.exists():
            p.unlink()

    def _files(self) -> "list[Path]":
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob("*" + self.SUFFIX), key=lambda p: p.name)

    def list_items(self, status: "str | None" = None) -> "list[DatasetPoolItem]":
        """항목 목록(이름순). ``status`` 지정 시 그 상태만(예: 실행 후보=``STATUS_ACTIVE``).

        읽을 수 없는 파일은 조용히 감추지 않고 **건너뛰되** — 여기선 관대하게 무시하지 않고
        예외를 전파한다(손상 파일은 시끄럽게). 호출측(뷰모델)이 표면화한다.
        """
        items = [DatasetPoolItem.load(p) for p in self._files()]
        items.sort(key=lambda it: it.name)
        if status is not None:
            items = [it for it in items if it.status == status]
        return items

    def names(self) -> "list[str]":
        return [it.name for it in self.list_items()]
