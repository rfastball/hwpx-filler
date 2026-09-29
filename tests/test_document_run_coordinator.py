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


def _capture(coordinator: DocumentRunCoordinator, records: list[dict]) -> "object":
    return coordinator.capture_input(
        datasource=None,
        records=records,
        indices=[0],
        snapshot_generation=1,
        work_ref="job",
        source_schema_keys=("name",),
        output_directory="",
    )


def test_capture_input_holds_the_original_list_as_an_identity_token() -> None:
    """source_records_ref는 잠금 시점 리스트 그 객체를 들고 있다(id() 재사용 위험 없음)."""
    coordinator = _coordinator()
    records = [{"name": "A"}]

    capture = _capture(coordinator, records)

    assert capture.source_records_ref is records


def test_same_list_object_is_not_stale() -> None:
    """실질 검사와 같은 모양: 캡처 시점과 같은 리스트 객체면 재마운트가 아니다."""
    coordinator = _coordinator()
    records = [{"name": "A"}]
    capture = _capture(coordinator, records)

    current_records = records  # 재마운트 없음 — 같은 객체
    assert capture.source_records_ref is current_records  # not stale


def test_new_list_with_equal_contents_is_stale() -> None:
    """id() 재사용을 막는 핵심 사례 — 내용이 똑같아도 다른 리스트 객체면 stale이다.

    id() 기반 비교였다면 원본이 GC된 뒤 새 리스트가 같은 id를 받을 수 있어 이 경우를
    "재마운트 없음"으로 오판할 위험이 있었다. 참조 자체를 들고 있으면 내용이 같아도
    `is`가 정확히 False를 낸다.
    """
    coordinator = _coordinator()
    records = [{"name": "A"}]
    capture = _capture(coordinator, records)

    del records  # 원본을 놓아 GC 후보로 만든다.
    remounted_records = [{"name": "A"}]  # 내용은 완전히 같은 새 리스트(재마운트)
    assert capture.source_records_ref is not remounted_records  # stale
