"""RunInputCapture.source_records 스냅샷 불변성(L-4)."""

from __future__ import annotations

import threading

from hwpxfiller.webapp.document_run_coordinator import DocumentRunCoordinator


def _coordinator() -> DocumentRunCoordinator:
    return DocumentRunCoordinator(threading.Lock())


def test_capture_input_source_records_is_immutable_snapshot() -> None:
    """캡처 이후 원본 리스트를 고쳐도 잠금 시점 값이 새지 않는다(불변 스냅샷)."""
    coordinator = _coordinator()
    records = [{"name": "A"}, {"name": "B"}]

    capture = coordinator.capture_input(
        datasource=None,
        records=records,
        indices=[0, 1],
        snapshot_generation=1,
        work_ref="job",
        source_schema_keys=("name",),
        output_directory="",
    )

    assert isinstance(capture.source_records, tuple)
    assert capture.source_records == ({"name": "A"}, {"name": "B"})

    # 원본 리스트에 대한 추가·삭제·재정렬은 스냅샷에 새지 않는다 — 리스트 별칭이 아니라
    # 리스트 자체의 얕은 복사(`data.records`와 같은 수준의 불변성; 개별 dict 값은
    # 여전히 공유된다 — `data.records`도 같은 한계다).
    records.append({"name": "C"})
    assert capture.source_records == ({"name": "A"}, {"name": "B"})
    assert capture.data.records == ({"name": "A"}, {"name": "B"})


def test_capture_input_records_identity_matches_original_list() -> None:
    """재마운트로 리스트 객체가 통째로 바뀌었는지 별칭 없이도 판별할 수 있어야 한다."""
    coordinator = _coordinator()
    records = [{"name": "A"}]

    capture = coordinator.capture_input(
        datasource=None,
        records=records,
        indices=[0],
        snapshot_generation=1,
        work_ref="job",
        source_schema_keys=("name",),
        output_directory="",
    )

    assert capture.source_records_identity == id(records)

    replacement = [{"name": "A"}]
    assert id(replacement) != capture.source_records_identity
