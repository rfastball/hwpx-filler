"""S6-04(#811) delivery coordinator — current disposition 3종의 atomic 집행.

계약: (1) write 는 전건 PASS 뒤에만 시작하고 실패·거절 런은 filesystem 을 불변으로 남긴다
(S6-8, actual 대조), (2) WRITE_NEW/WRITE_ADD_SUFFIX 는 관찰 이후 생긴 파일을 조용히 파괴하지
않는다(no-clobber — 생성 자체가 검사), (3) WRITE_OVERWRITE 만 명시 확인된 파괴로 교체한다,
(4) bytes 생성과 disk 안착의 소유자가 다르다(S6-7 — coordinator 는 재판정 0).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.application.candidate_revision import blob_digest
from hwpxfiller.application.generation_delivery import (
    PATH_OCCUPANCY_OBSERVATION_MISMATCH,
    WRITE_ADD_SUFFIX,
    WRITE_NEW,
    WRITE_OVERWRITE,
    CurrentResolvedDelivery,
    CurrentResolvedDeliveryItem,
)
from hwpxfiller.domain.fields import FillNote
from hwpxfiller.external.delivery_coordinator import (
    DeliveryAborted,
    DeliveryCompleted,
    DeliveryContractError,
    DeliveryRefused,
    deliver_current_documents,
)
from hwpxfiller.external.materialization_conformance import ConformanceFailure
from hwpxfiller.external.materialization_runner import MaterializedDocumentBytes
from hwpxfiller.external.materialization_start_gate import StartMaterializationRefusal

from tests._materialization_case import AT, _build_case, _one_of_two
from tests.test_materialization_start_gate import _Kit


# ─── 조립 helper ──────────────────────────────────────────────────────────────────────
def _doc(data: bytes, *, notes: tuple[FillNote, ...] = ()) -> MaterializedDocumentBytes:
    return MaterializedDocumentBytes(
        plan_semantic_digest="sha256:" + "p" * 64,
        validated_record_ref="sha256:" + "v" * 64,
        output_bytes=data,
        output_digest=blob_digest(data),
        execution_notes=notes,
    )


def _resolved(out: Path, *items: CurrentResolvedDeliveryItem) -> CurrentResolvedDelivery:
    return CurrentResolvedDelivery(
        exact_pattern="공고서",
        captured_delivery_clock=AT,
        output_directory=str(out),
        collision_policy="ADD_SUFFIX",
        ordered_items=tuple(items),
    )


def _item(ordinal: int, path: str, disposition: str) -> CurrentResolvedDeliveryItem:
    return CurrentResolvedDeliveryItem(
        record_identity=f"rec-{ordinal}", item_ordinal=ordinal,
        resolved_output_relative_path=path, collision_disposition=disposition,
    )


def _fs_snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}


# ═══ 수직: start gate → 러너 → coordinator → 실제 HWPX 파일 ═══════════════════════════
def test_admitted_run_delivers_an_actual_hwpx_file(tmp_path) -> None:
    # MANAGED_RUN_STARTABLE_IN_S6 뒤에 실제 write 가 섰다 — planned disposition 의 실집행.
    kit = _Kit(_build_case(_one_of_two()))
    outcome = kit.start()
    assert isinstance(outcome, MaterializedDocumentBytes)
    out = tmp_path / "delivery"
    out.mkdir()
    result = deliver_current_documents(
        resolved=_resolved(out, _item(0, "공고서-001.hwpx", WRITE_NEW)),
        ordered_outcomes=[outcome],
    )
    assert isinstance(result, DeliveryCompleted), result
    written = (out / "공고서-001.hwpx").read_bytes()
    assert written == outcome.output_bytes
    assert blob_digest(written) == outcome.output_digest  # 앉은 bytes == 검증된 bytes


# ═══ disposition 3종의 집행 의미 ══════════════════════════════════════════════════════
def test_three_dispositions_execute_with_their_exact_meaning(tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "덮어쓰기.hwpx").write_bytes(b"OLD")
    result = deliver_current_documents(
        resolved=_resolved(
            out,
            _item(0, "새문서.hwpx", WRITE_NEW),
            _item(1, "새문서_2.hwpx", WRITE_ADD_SUFFIX),
            _item(2, "덮어쓰기.hwpx", WRITE_OVERWRITE),
        ),
        ordered_outcomes=[_doc(b"D0"), _doc(b"D1"), _doc(b"D2")],
    )
    assert isinstance(result, DeliveryCompleted)
    assert (out / "새문서.hwpx").read_bytes() == b"D0"
    assert (out / "새문서_2.hwpx").read_bytes() == b"D1"  # suffix 는 resolver 가 이미 계산했다
    assert (out / "덮어쓰기.hwpx").read_bytes() == b"D2"  # 명시 확인된 파괴만 교체
    assert [d.item_ordinal for d in result.delivered] == [0, 1, 2]


def test_delivered_document_carries_notes_and_digest(tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    note = FillNote("빈칸", "slot_synthesized")
    result = deliver_current_documents(
        resolved=_resolved(out, _item(0, "a.hwpx", WRITE_NEW)),
        ordered_outcomes=[_doc(b"D", notes=(note,))],
    )
    assert isinstance(result, DeliveryCompleted)
    delivered = result.delivered[0]
    assert delivered.execution_notes == (note,)  # 완화 사실은 원장(S6-05)까지 나른다
    assert delivered.output_digest == blob_digest(b"D")
    assert delivered.record_identity == "rec-0"


# ═══ S6-8 — 실패·거절 런은 filesystem 불변(actual 대조) ═══════════════════════════════
def test_any_materialization_failure_writes_nothing(tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "기존.hwpx").write_bytes(b"KEEP")
    before = _fs_snapshot(out)
    result = deliver_current_documents(
        resolved=_resolved(
            out, _item(0, "a.hwpx", WRITE_NEW), _item(1, "b.hwpx", WRITE_NEW)
        ),
        ordered_outcomes=[
            _doc(b"OK"),
            ConformanceFailure("REMOVAL_INCOMPLETE", "잔존"),
        ],
    )
    assert isinstance(result, DeliveryRefused)
    assert result.code == "REMOVAL_INCOMPLETE"  # 사유 재진술(재조립 0)
    assert result.failed_item_ordinal == 1
    assert _fs_snapshot(out) == before  # 앞 항목이 PASS 여도 write 0 — filesystem 불변


def test_start_refusal_writes_nothing(tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    before = _fs_snapshot(out)
    result = deliver_current_documents(
        resolved=_resolved(out, _item(0, "a.hwpx", WRITE_NEW)),
        ordered_outcomes=[StartMaterializationRefusal("DIGEST_MISMATCH", "stale")],
    )
    assert isinstance(result, DeliveryRefused)
    assert result.code == "DIGEST_MISMATCH"
    assert _fs_snapshot(out) == before


# ═══ no-clobber — 관찰 이후 생긴 파일은 조용히 파괴되지 않는다 ═══════════════════════
def test_interloper_at_write_new_target_aborts_without_destroying_it(tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "경쟁.hwpx").write_bytes(b"interloper")  # 관찰 이후 생긴 파일의 재현
    result = deliver_current_documents(
        resolved=_resolved(
            out,
            _item(0, "먼저.hwpx", WRITE_NEW),
            _item(1, "경쟁.hwpx", WRITE_NEW),
            _item(2, "이후.hwpx", WRITE_NEW),
        ),
        ordered_outcomes=[_doc(b"D0"), _doc(b"D1"), _doc(b"D2")],
    )
    assert isinstance(result, DeliveryAborted)
    assert result.code == PATH_OCCUPANCY_OBSERVATION_MISMATCH
    assert result.failed_item_ordinal == 1
    assert (out / "경쟁.hwpx").read_bytes() == b"interloper"  # 파괴 0
    assert (out / "먼저.hwpx").read_bytes() == b"D0"  # 이미 앉은 문서는 유효
    assert [d.item_ordinal for d in result.delivered] == [0]
    assert not (out / "이후.hwpx").exists()  # 실패 이후는 손대지 않는다


# ═══ 계약 밖 입력은 loud 예외 ═════════════════════════════════════════════════════════
def test_outcome_count_mismatch_is_loud(tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(DeliveryContractError):
        deliver_current_documents(
            resolved=_resolved(out, _item(0, "a.hwpx", WRITE_NEW)),
            ordered_outcomes=[_doc(b"D0"), _doc(b"D1")],
        )
    assert _fs_snapshot(out) == {}


def test_path_escaping_output_directory_is_loud(tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(DeliveryContractError):
        deliver_current_documents(
            resolved=_resolved(out, _item(0, "..\\탈출.hwpx", WRITE_NEW)),
            ordered_outcomes=[_doc(b"D0")],
        )
    assert not (tmp_path / "탈출.hwpx").exists()
    assert _fs_snapshot(out) == {}


def test_unknown_disposition_is_loud(tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(DeliveryContractError):
        deliver_current_documents(
            resolved=_resolved(out, _item(0, "a.hwpx", "WRITE_IF_ABSENT")),
            ordered_outcomes=[_doc(b"D0")],
        )
    assert _fs_snapshot(out) == {}  # plan-time 어휘는 이 층의 집행 대상이 아니다
