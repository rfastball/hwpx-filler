"""데이터셋 풀 — durable 데이터 *참조*(스냅샷 아님)의 홈 레지스트리.

ADR J 축확정: 데이터 수명 = 계약 사이클(발주~지급, 최소 60일)이라 세션-일회 recents 로는
부족 → 데이터는 **durable 풀 항목**이되 **연결/참조**(엑셀 경로·나라 쿼리)로만 저장하고
실행 때 재읽기("싱크")한다. 사이클 종료 = **보관**(add/delete 아닌 archive — 실행 후보에서만 제외).
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
from dataclasses import dataclass, field
from pathlib import Path

from .job import _slug, guard_slug_collision, load_isolated
from .paths import home_dir
from hwpxcore.atomic import write_text_atomic

# 항목 상태(2상태, #5) — active(실행 대상) / archived(지난 것: 실행 후보 제외, 참조 보존·복구 가능).
# add/delete 가 아니라 archive 로 수명 종료를 표현한다(참조는 남기되 실행 후보에서 제외).
#
# **왜 2상태인가**: 한때 archived 위에 retired("은퇴, 숨김") 3번째 상태가 있었으나, 행동 차이가
# 없었다 — 둘 다 실행 후보에서 빠지고(status=ACTIVE 로만 겨눔) 둘 다 풀 목록에 muted 로 표시됐다
# ("숨김"은 구현된 적 없는 허구). 명목만 다른 상태가 라벨↔버튼 desync 를 낳아(#5) archived 로
# 정준 병합했다. STATUS_RETIRED 는 **디스크 마이그레이션 별칭으로만** 남는다(아래 from_dict).
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
_STATUSES = (STATUS_ACTIVE, STATUS_ARCHIVED)

# 폐기된 상태(구 .dataset.json 호환). 읽기 시 archived 로 정규화 — 무손실(retired 와 archived 는
# 실행 후보 여부가 동일해 사용자 결정·데이터 소실 없음). 새로 이 값을 저장하지는 않는다.
STATUS_RETIRED = "retired"
_LEGACY_STATUS_ALIASES = {STATUS_RETIRED: STATUS_ARCHIVED}


def default_dataset_pool_dir() -> Path:
    """GUI 기본 데이터셋 풀 레지스트리 위치 — 사용자 홈(``~/.hwpxfiller/datasets``).

    작업·txt 템플릿과 동일 홈 관례(:func:`~hwpxfiller.core.job.default_jobs_dir` 미러).
    ``HWPXFILLER_HOME`` 로 재지정 가능(해석은 :func:`~hwpxfiller.core.paths.home_dir`).
    레지스트리 *클래스* 는 위치-불가지(생성자가 디렉터리를 받는다) — 이 함수는 GUI 기본값
    해석기일 뿐이다.
    """
    return home_dir() / "datasets"


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
        # 폐기된 상태(retired) 는 읽기 시 정준 상태로 접는다(migrate-on-read, #5) — 구 파일이
        # loud raise("알 수 없는 상태") 로 죽지 않고 조용히 forward-정규화된다(무손실이라 정당).
        status = d.get("status", STATUS_ACTIVE)
        status = _LEGACY_STATUS_ALIASES.get(status, status)
        return cls(
            name=d.get("name", ""),
            kind=d.get("kind", ""),
            opts=dict(d.get("opts", {})),
            status=status,
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

    def list_items(
        self,
        status: "str | None" = None,
        *,
        corrupted: "list[tuple[Path, str]] | None" = None,
    ) -> "list[DatasetPoolItem]":
        """항목 목록(이름순). ``status`` 지정 시 그 상태만(예: 실행 후보=``STATUS_ACTIVE``).

        **파일 단위 격리(RC-05, :func:`~hwpxfiller.core.job.load_isolated` 공유):**
        손상된 ``.dataset.json`` 1개(손편집·구버전·잘림)가 목록 전체(→풀 뷰모델·앱 부팅·
        실행 겨눔 피커)를 죽이지 않도록, ``corrupted`` 리스트를 넘긴 호출측에는 파싱 실패를
        파일별로 잡아 ``(경로, 오류 문자열)`` 로 수집해 준다 — 호출측이 시끄럽게 표면화할
        책임을 진다(확인-또는-경보).

        **``corrupted`` 미전달 시에는 읽기 실패가 그대로 raise 된다(C5)** — 한때 미전달
        호출자에게 손상 항목을 무표시로 드롭했는데, 실행 피커·카운트에서 데이터셋이
        조용히 증발하는 정합 결함이었다. 격리를 원하는 표면은 명시적으로 수집 리스트를
        넘기고 손상 건수를 병기하라(풀 화면·피커·홈 KPI 가 그렇게 한다).
        """
        items: "list[DatasetPoolItem]" = load_isolated(
            self._files(), DatasetPoolItem.load, corrupted
        )
        items.sort(key=lambda it: it.name)
        if status is not None:
            items = [it for it in items if it.status == status]
        return items

    def names(self) -> "list[str]":
        return [it.name for it in self.list_items()]
