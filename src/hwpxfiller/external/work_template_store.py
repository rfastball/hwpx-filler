"""Work Template aggregate 의 file-atomic 저장 + 새 Work INITIALIZATION 서비스 (S3-03 #653).

Work 당 하나의 ``<work_id>.json`` 이 그 Work 의 전체 S3 상태다. 갱신은 writer lease 아래
read+decode+검증 → 메모리 새 상태 완성 → 같은 디렉터리 temp write → atomic replace 로 **한 번**
commit 한다. commit 실패·context 예외는 기존 파일을 무손상으로 남긴다(:mod:`.atomic`).

새 Work 생성은 exact PASS Evidence 를 받아 DocumentWork + INITIALIZATION Application 을 하나의
최초 commit 으로 만든다. Evidence 를 참조하기 전에 :class:`QualificationObjectStore` /
:class:`CandidateObjectStore` 에서 Evidence(PASS)·Revision·Profile Manifest 실재를 확인한다 —
missing object 를 latest 검색으로 보완하지 않는다(#650 정본 경계).

S3-01·S3-02 의 두 store 를 여기서 처음 함께 소비한다(그 둘은 병렬 슬라이스라 서로 import 하지
않았다). aggregate 값·불변식·코덱은 :mod:`hwpxfiller.application.work_template_state` 소유.
"""

from __future__ import annotations

import json
import re
import threading
import weakref
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from hwpxfiller.application.qualification_evidence import PASS
from hwpxfiller.application.work_template_state import (
    INITIALIZATION,
    SCHEMA_VERSION,
    DocumentWork,
    WorkTemplateApplication,
    WorkTemplateStateAggregate,
    decode_aggregate,
    encode_aggregate,
)
from .atomic import write_text_atomic
from .candidate_store import CandidateObjectStore
from .qualification_store import QualificationObjectStore

_SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")


class WorkTemplateStoreError(Exception):
    """Work aggregate 저장 경계의 loud failure 기반."""


class WorkAggregateNotFound(WorkTemplateStoreError):
    """참조한 Work aggregate 파일이 없다."""


class WorkAggregateExists(WorkTemplateStoreError):
    """이미 있는 Work 를 다시 initialize 하려 함(create-once)."""


class WorkAggregateCorrupt(WorkTemplateStoreError):
    """aggregate 파일이 JSON 으로 파싱되지 않는다 — 조용히 current 로 승격하지 않는다."""


class WorkTemplateReferenceError(WorkTemplateStoreError):
    """참조하려는 PASS Evidence·Revision·Manifest 가 계약을 만족하지 못한다."""


def _require_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise WorkTemplateStoreError(f"저장할 수 없는 work_id {value!r}")
    return value


# 프로세스 안 (root, work_id) 별 writer lease. 지원 topology 는 작업 디렉터리당 writer 프로세스
# 하나(#192)라 in-process 직렬화로 충분하다.
# ponytail: in-process RLock — cross-process 원자성은 v1 desktop 전제 밖(#650), 필요 시 #620 상향.
_WORK_LOCKS: "weakref.WeakValueDictionary[str, threading.RLock]" = (
    weakref.WeakValueDictionary()
)
_WORK_LOCKS_GUARD = threading.Lock()


def _work_lock(key: str) -> threading.RLock:
    with _WORK_LOCKS_GUARD:
        lock = _WORK_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _WORK_LOCKS[key] = lock
        return lock


class _Transaction:
    """``update`` 안에서 caller 가 새 frozen aggregate 로 갈아끼우는 홀더."""

    def __init__(self, aggregate: WorkTemplateStateAggregate) -> None:
        self.aggregate = aggregate


class AtomicWorkTemplateStateStore:
    """Work aggregate 의 create-once·file-atomic 저장소."""

    def __init__(self, root: "str | Path") -> None:
        self._root = Path(root)

    def _path(self, work_id: str) -> Path:
        return self._root / f"{_require_id(work_id)}.json"

    def _lock_key(self, work_id: str) -> str:
        return f"{self._root}\x00{work_id}"

    def load(self, work_id: str) -> WorkTemplateStateAggregate:
        path = self._path(work_id)
        if not path.exists():
            raise WorkAggregateNotFound(f"work {work_id} aggregate 없음")
        try:
            data = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkAggregateCorrupt(f"work {work_id} aggregate 손상") from exc
        return decode_aggregate(data)

    def create(self, aggregate: WorkTemplateStateAggregate) -> None:
        work_id = aggregate.work.work_id
        path = self._path(work_id)
        with _work_lock(self._lock_key(work_id)):
            if path.exists():
                raise WorkAggregateExists(f"work {work_id} 는 이미 존재한다")
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(
                path, json.dumps(encode_aggregate(aggregate), ensure_ascii=False, indent=2)
            )

    @contextmanager
    def update(self, work_id: str) -> Iterator[_Transaction]:
        """writer lease 아래 read→검증→(caller mutate)→atomic commit 을 한 번 수행한다."""
        with _work_lock(self._lock_key(work_id)):
            current = self.load(work_id)
            # object identity 가 아니라 값으로 변경을 판정한다. 스냅샷은 **직렬화 문자열**이라야
            # 한다 — encode 의 dict(payload) 는 얕은 사본이라 nested list/dict 를 원본과 공유해,
            # dict 비교로는 in-place 변경이 스냅샷에도 반영돼 안 잡힌다.
            before = json.dumps(encode_aggregate(current), ensure_ascii=False, sort_keys=True)
            txn = _Transaction(current)
            yield txn  # caller 예외는 여기서 전파돼 아래 write 를 건너뛴다(기존 파일 유지)
            new = txn.aggregate
            encoded_new = encode_aggregate(new)
            if json.dumps(encoded_new, ensure_ascii=False, sort_keys=True) == before:
                return  # 변경 없음 — commit 하지 않는다
            # payload nested dict/list 를 in-place 로 고쳐도(new is current, version 그대로) 값
            # 비교가 잡아 아래 version 문지기가 시끄럽게 거절한다 — 조용한 유실을 막는다.
            if new.work.work_id != work_id:
                raise WorkTemplateStoreError("update 안에서 다른 Work 로 바꿀 수 없다")
            if new.aggregate_version != current.aggregate_version + 1:
                raise WorkTemplateStoreError(
                    "commit 은 aggregate_version 을 정확히 1 올려야 한다"
                )
            write_text_atomic(
                self._path(work_id),
                json.dumps(encoded_new, ensure_ascii=False, indent=2),
            )


def _require_pass_evidence(
    qualification_store: QualificationObjectStore,
    candidate_store: CandidateObjectStore,
    pass_evidence_id: str,
    expected_lineage_id: str,
) -> None:
    """Evidence(PASS)·그 Revision·Profile Manifest 실재를 확인한다(latest 보완 금지).

    Revision 의 lineage 가 요청한 ``expected_lineage_id`` 와 다르면 거절한다 — 안 그러면
    DocumentWork 가 한 lineage 를 주장하면서 current application 은 다른 lineage 의 Evidence 를
    가리키는 모순 identity 로 영속된다(확인-또는-경보).
    """
    evidence = qualification_store.get_evidence(pass_evidence_id)  # 부재·손상은 loud
    if evidence.result != PASS:
        raise WorkTemplateReferenceError(
            f"evidence {pass_evidence_id} 는 PASS 가 아니다 ({evidence.result})"
        )
    revision = candidate_store.get_revision(evidence.revision_id)  # 부재는 ObjectNotFound
    if revision.template_lineage_id != expected_lineage_id:
        raise WorkTemplateReferenceError(
            f"evidence revision lineage {revision.template_lineage_id!r} 가 요청 "
            f"{expected_lineage_id!r} 와 불일치"
        )
    qualification_store.get_manifest(evidence.qualification_profile_id)


def initialize_work(
    store: AtomicWorkTemplateStateStore,
    qualification_store: QualificationObjectStore,
    candidate_store: CandidateObjectStore,
    *,
    work_id: str,
    template_lineage_id: str,
    application_id: str,
    pass_evidence_id: str,
    actor: str,
    applied_at: str,
) -> WorkTemplateStateAggregate:
    """exact PASS Evidence 로 새 Work 를 하나의 aggregate 최초 commit 으로 만든다."""
    _require_pass_evidence(
        qualification_store, candidate_store, pass_evidence_id, template_lineage_id
    )
    application = WorkTemplateApplication(
        application_id=application_id,
        work_id=work_id,
        application_epoch=1,
        pass_evidence_id=pass_evidence_id,
        previous_application_id=None,
        origin=INITIALIZATION,
        prepared_change_id=None,
        actor=actor,
        applied_at=applied_at,
    )
    aggregate = WorkTemplateStateAggregate(
        schema_version=SCHEMA_VERSION,
        aggregate_version=1,
        work=DocumentWork(
            work_id=work_id,
            template_lineage_id=template_lineage_id,
            current_template_application_id=application_id,
            current_template_preparation_id=None,
            prepare_seq=0,
        ),
        applications=(application,),
        preparations=(),
        prepared_changes=(),
        apply_provenance=(),
        outbox_events=(),
    )
    store.create(aggregate)
    return aggregate
