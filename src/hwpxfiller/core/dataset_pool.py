"""데이터셋 풀 — durable 데이터 *참조*(스냅샷 아님)의 홈 레지스트리.

ADR J 축확정: 데이터 수명 = 계약 사이클(발주~지급, 최소 60일)이라 세션-일회 recents 로는
부족 → 데이터는 **durable 풀 항목**이되 **연결/참조**(엑셀 경로·나라 쿼리)로만 저장하고
실행 때 재읽기("싱크")한다. 사이클 종료 = **보관**(add/delete 아닌 archive — 실행 후보에서만 제외).
"데이터·행 미저장" 불변식(포인터만 직렬화)을 유지한다 — 풀 항목은 **소스를 어떻게 다시
여는가**(kind + opts)만 담고 레코드는 담지 않는다.

**정체성 = 경로+시트, 이름 = 순수 라벨**(U2 §5.3 판정 C, #347): 엑셀/CSV 참조의 정체성은
``normcase(abspath(path)) + sheet`` 다(:func:`excel_identity`) — 같은 워크북의 다른 시트는
다른 데이터(#33)이고, 같은 경로·시트는 이름이 달라도 같은 데이터다. ``name`` 은 중복 허용·
개명 자유·정체성 무관의 표시 라벨로 강등됐다. 그래서 파일명도 이름 slug 가 아니라 **불투명
슬롯 키**(파일 stem)이고, 그 키는 **내용에서 파생되지 않는다**(내용물 교체가 정상 수명
사건이라 — 4R 판정, 클래스 주석 참조). 구판(slug 파일명) 파일은 그 stem 그대로 유효한
슬롯이라 디스크 마이그레이션이 없다(읽는 김에 디스크를 고치지 않는다). 같은 정체성을
가리키는 슬롯 2개(구판의 다른 이름·같은 경로 등록)는 조용히 하나 버리지 않고
:meth:`DatasetPoolRegistry.duplicate_identity_groups` 로 표면화해 사용자 확정 후
병합한다(confirm-or-alarm). ``guard_slug_collision``/``_slug`` 의 데이터셋 소비자는 이
재편으로 소멸했다(작업 축은 그대로).

**보안 불변식**([[confirm-or-alarm-principle]]): 나라장터 항목은 **ServiceKey 를 담지
않는다**. opts 는 쿼리(기간·건수·페이지)뿐이고, 키는 실행 복원 시점에만 OS 자격증명 저장소
(N1 SecretStore)에서 주입한다(복원 로직은 :func:`~hwpxfiller.data.factory.source_from_pool_item`).

직렬화는 :class:`~hwpxfiller.core.job.Job` 의 JSON 관례(UTF-8·``ensure_ascii=False``·``indent=2``·
``to_dict``/``from_dict``·가산 필드 하위호환)를 그대로 미러한다. Qt·엔진 비의존.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from hwpxcore.atomic import write_text_atomic

from ..domain.dataset_reference import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_RETIRED,
    DatasetReference,
    excel_identity,
    reference_identity,
)
from .job import load_isolated
from .paths import home_dir

# 기존 공개 이름은 Domain 정본의 동일 함수다.
item_identity = reference_identity


# 같은 데이터셋 디렉터리를 보는 컨트롤러·레지스트리 인스턴스는 하나의 쓰기 경계를 공유한다.
# pywebview 는 호출마다 다른 스레드로 진입하고 화면마다 레지스트리를 새로 만들 수 있으므로
# instance-local RLock 은 load→수정→save 사이의 lost update 를 막지 못한다. #182 범위는
# single-process 직렬화이며 cross-process lock 은 명시적 비목표다.
_WRITE_LOCKS: "dict[str, threading.RLock]" = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def _shared_write_lock(directory: Path) -> "threading.RLock":
    key = os.path.normcase(os.path.abspath(os.fspath(directory)))
    with _WRITE_LOCKS_GUARD:
        return _WRITE_LOCKS.setdefault(key, threading.RLock())


def default_dataset_pool_dir() -> Path:
    """GUI 기본 데이터셋 풀 레지스트리 위치 — 사용자 홈(``~/.hwpxfiller/datasets``).

    작업·txt 템플릿과 동일 홈 관례(:func:`~hwpxfiller.core.job.default_jobs_dir` 미러).
    ``HWPXFILLER_HOME`` 로 재지정 가능(해석은 :func:`~hwpxfiller.core.paths.home_dir`).
    레지스트리 *클래스* 는 위치-불가지(생성자가 디렉터리를 받는다) — 이 함수는 GUI 기본값
    해석기일 뿐이다.
    """
    return home_dir() / "datasets"


# ------------------------------------------------------------------ 영속 호환 모델
class DatasetPoolItem(DatasetReference):
    """기존 Core API를 보존하는 파일 영속 adapter.

    값·상태·정체성 규칙은 :class:`~hwpxfiller.domain.dataset_reference.DatasetReference`
    가 소유한다. ``save``/``load`` byte I/O만 이 호환 클래스에 남는다.
    """

    def save(self, path: "str | Path") -> None:
        # 원자 쓰기(RC-01) — 저장 중 실패가 기존 풀 항목 JSON 을 파괴하지 않는다.
        write_text_atomic(path, json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: "str | Path") -> "DatasetPoolItem":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _persistent_item(item: DatasetReference) -> DatasetPoolItem:
    """Domain 참조를 기존 byte-I/O 호환 타입으로 무손실 승격한다."""
    if isinstance(item, DatasetPoolItem):
        return item
    return DatasetPoolItem.from_dict(item.to_dict())


# ------------------------------------------------------------------ 레지스트리
class DatasetPoolRegistry:
    """데이터셋 풀 레지스트리 — 디렉터리에 항목당 JSON 1개. 데이터 선택 다이얼로그의 원천.

    위치-불가지: 생성자가 디렉터리를 받는다(테스트는 ``tmp_path``, GUI 는
    :func:`default_dataset_pool_dir`).

    **키 = 파일 stem(불투명 슬롯 키), 이름 = 라벨**(U2 §5.3 판정 C): 이름이 중복 허용
    라벨로 강등돼 파일명·조회 키가 될 수 없다. 항목 조작(:meth:`load`·:meth:`mutate`·
    :meth:`delete`)은 슬롯 키로 하고, 데이터 축의 **중복 판정**은 정체성
    (:func:`excel_identity` — :meth:`find_identity`)으로 한다.

    **키는 내용에서 파생되지 않는다**(코덱스 4R 근본 조치). 한때 새 슬롯 키가 정체성
    다이제스트였는데, 그것은 #347 이 ``dataset_id`` 를 기각한 근거(*"내용물 교체가 정상
    수명 사건"*)를 **파일명에 다시 심는** 구조였다: 파일 A 로 만든 슬롯을 B 로 재연결하면
    슬롯은 ``hash(identity(A))`` 를 계속 점유하고, 나중에 A 를 다시 고정하려는 사람은
    정체성 조회는 통과하는데(A 를 참조하는 항목이 없다) 키 충돌로 막혀 「없는 것과
    충돌한다」는 말을 듣는다. 수명 보존(슬롯은 산다)과 정체성 추적(내용은 갈린다)이 한
    값에 얹혀 있던 것이 원인이므로, 키는 **내용 무관 불투명 토큰**(:meth:`new_slot_key`)
    으로 발급하고 정체성은 내용에서 **읽을 때** 파생한다(:meth:`find_identity` — 인덱스가
    아니라 질의). 같은 데이터 2건 봉쇄는 키가 아니라 그 질의가 진다.

    구판(이름 slug) 파일은 그 stem 그대로 유효한 슬롯이다 — 키가 불투명해졌으므로
    디스크 마이그레이션은 여전히 없다. 구판이 남긴 다른 이름·같은 정체성 슬롯 2개는
    :meth:`duplicate_identity_groups` 가 표면화한다(조용한 병합·드롭 금지 — 사용자
    확정 후 삭제).
    """

    SUFFIX = ".dataset.json"

    def __init__(self, directory: "str | Path"):
        self.directory = Path(directory)
        self._write_lock = _shared_write_lock(self.directory)

    # ------------------------------------------------------------- 슬롯 키
    def slot_path(self, key: str) -> Path:
        """슬롯 키 → 파일 경로. 웹 페이로드가 흘러드는 자리라 경로 탈출을 loud 거절한다."""
        if (
            not key
            or key != Path(key).name  # 구분자·상위 참조가 들어간 키 = 경로 탈출 시도
            or key in (".", "..")
        ):
            raise ValueError(f"올바른 등록 데이터 키가 아닙니다: {key!r}")
        return self.directory / (key + self.SUFFIX)

    def new_slot_key(self) -> str:
        """빈 슬롯 키 발급 — **내용 무관 불투명 토큰**(위 클래스 주석의 4R 판정).

        내용에서 파생하지 않으므로 슬롯은 참조가 갈려도(다시 연결) 자기 자리를 지키고,
        놓아준 데이터는 다른 슬롯이 자유롭게 다시 고정할 수 있다 — 수명 보존과 정체성
        추적이 서로를 막지 않는다. 파일 존재로 재발급해 같은 디렉터리 안 충돌을 없앤다
        (쓰기 잠금 안에서 부른다 — 발급과 생성 사이의 경합 봉쇄).
        """
        for _ in range(8):
            key = uuid.uuid4().hex[:16]
            if not self.slot_path(key).exists():
                return key
        raise RuntimeError("빈 등록 데이터 슬롯 키를 발급하지 못했습니다.")  # 사실상 불가

    # ------------------------------------------------------------- 쓰기
    def add(self, item: DatasetReference) -> str:
        """새 항목 추가 → 슬롯 키 반환. 같은 정체성이 이미 있으면 loud 거절.

        중복 확인·병합은 호출측(등록 게이트)이 :meth:`find_identity` 로 먼저 판정해
        사용자에게 재진술한다 — 여기 거절은 그 판정을 우회한 호출을 잡는 백스톱이다.
        **거절 근거는 키가 아니라 정체성 질의**다(4R): 키가 내용에서 파생되던 시절엔
        「지금 아무도 안 쓰는 데이터」가 옛 슬롯 키와 부딪혀 거절됐다.
        """
        with self._write_lock:
            ident = item_identity(item)
            if ident is not None:
                found = self.find_identity_raw(ident)
                if found is not None:
                    raise ValueError(
                        f"같은 데이터(경로·시트)가 이미 '{found[1].name}' 으로 고정돼 "
                        "있습니다."
                    )
            self.directory.mkdir(parents=True, exist_ok=True)
            key = self.new_slot_key()
            _persistent_item(item).save(self.slot_path(key))
            return key

    def save_at(self, key: str, item: DatasetReference) -> None:
        """슬롯에 항목을 원자 저장 — 갱신은 :meth:`mutate` 를 쓰고 이건 그 몸통이다."""
        with self._write_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            _persistent_item(item).save(self.slot_path(key))

    def write_lock(self) -> "threading.RLock":
        """이 디렉터리의 모든 레지스트리 인스턴스가 공유하는 쓰기 잠금.

        레지스트리 밖에서 디스크 값을 바탕으로 갱신해야 하는 코드는 저장 한 번만 잠그지 말고
        :meth:`mutate` 를 사용한다. 이 accessor 는 writer 완결성 계약을 검증하는 테스트와 여러
        항목을 묶는 상위 트랜잭션을 위한 탈출구다.
        """
        return self._write_lock

    def mutate(self, key: str, change) -> DatasetPoolItem:
        """기존 항목을 잠금 안에서 다시 읽고 ``change(item)`` 적용 후 원자 저장한다.

        항목이 잠금 획득 전에 삭제됐으면 :meth:`load` 가 ``FileNotFoundError`` 를 내고 저장은
        수행되지 않는다. 오래된 화면 스냅샷이 삭제된 항목을 되살리는 것을 막는 핵심 경계다.
        """
        with self._write_lock:
            item = self.load(key)
            change(item)
            self.save_at(key, item)
            return item

    # ------------------------------------------------------------- 읽기
    def exists(self, key: str) -> bool:
        return self.slot_path(key).exists()

    def load(self, key: str) -> DatasetPoolItem:
        return DatasetPoolItem.load(self.slot_path(key))

    def delete(self, key: str) -> None:
        with self._write_lock:
            p = self.slot_path(key)
            if p.exists():
                p.unlink()

    def _files(self) -> "list[Path]":
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob("*" + self.SUFFIX), key=lambda p: p.name)

    def list_entries(
        self,
        status: "str | None" = None,
        *,
        corrupted: "list[tuple[Path, str]] | None" = None,
    ) -> "list[tuple[str, DatasetPoolItem]]":
        """(슬롯 키, 항목) 목록 — 이름순(동명은 키순). 격리 계약은 :meth:`list_items` 와 같다."""
        entries: "list[tuple[str, DatasetPoolItem]]" = load_isolated(
            self._files(),
            lambda p: (Path(p).name[: -len(self.SUFFIX)], DatasetPoolItem.load(p)),
            corrupted,
        )
        entries.sort(key=lambda e: (e[1].name, e[0]))
        if status is not None:
            entries = [e for e in entries if e[1].status == status]
        return entries

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
        return [item for _key, item in self.list_entries(status, corrupted=corrupted)]

    # ------------------------------------------------------------- 정체성 조회
    def find_identity_raw(
        self, ident: str
    ) -> "tuple[str, DatasetPoolItem] | None":
        """정체성 문자열로 슬롯 조회 — 손상 파일은 건너뛴다(손상 표면화는 목록 계약 소관)."""
        for key, item in self.list_entries(corrupted=[]):
            if item_identity(item) == ident:
                return (key, item)
        return None

    def find_identity(
        self, path: "str | Path", sheet: "str | None" = ""
    ) -> "tuple[str, DatasetPoolItem] | None":
        """경로+시트로 슬롯 조회 — 등록 게이트의 중복 판정 입구(같은 데이터인가?)."""
        return self.find_identity_raw(excel_identity(path, sheet))

    def find_by_name(self, name: str) -> "tuple[str, DatasetPoolItem] | None":
        """라벨로 첫 슬롯 조회 — 이름이 정체성이 아니게 된 뒤의 **편의 조회**다.

        동명이 허용되므로 유일성을 전제하는 판정에 쓰면 안 된다(첫 항목 반환) — 파킹된
        파이프라인 빌더처럼 이름이 실질 핸들인 비파일 참조 표면만 쓴다.
        """
        for key, item in self.list_entries(corrupted=[]):
            if item.name == name:
                return (key, item)
        return None

    def duplicate_identity_groups(
        self, *, corrupted: "list[tuple[Path, str]] | None" = None
    ) -> "list[list[tuple[str, DatasetPoolItem]]]":
        """같은 정체성을 가리키는 슬롯 2+개의 그룹 — 구판 마이그레이션의 병합 대상.

        구판(이름=키)은 다른 이름·같은 경로를 2건으로 허용했다. 재편 뒤 그 2건은 같은
        데이터라 **병합 판정이 필요**한데, 무손실이 아니므로(둘 중 하나의 이름·메모·상태가
        남는다) 조용히 하나 버리지 않고 이 그룹을 앱 표면이 loud 재진술한 뒤 사용자가
        남길 슬롯을 확정한다(U2 §5.3 — confirm-or-alarm).
        """
        by_ident: "dict[str, list[tuple[str, DatasetPoolItem]]]" = {}
        for key, item in self.list_entries(corrupted=corrupted):
            ident = item_identity(item)
            if ident is None:
                continue
            by_ident.setdefault(ident, []).append((key, item))
        return [group for group in by_ident.values() if len(group) > 1]

    def names(self) -> "list[str]":
        return [it.name for it in self.list_items()]
