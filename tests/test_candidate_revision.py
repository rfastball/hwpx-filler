from __future__ import annotations

import json

import pytest

from hwpxfiller.application.candidate_revision import (
    MEDIA_MISMATCH,
    SOURCE_BINDING_CHANGED,
    SOURCE_CAPTURE_ERROR,
    CandidateRevisionCreated,
    CandidateRevisionError,
    ContentBlob,
    MutableSourceBinding,
    SourceCaptureError,
    StableCapture,
    TemplateLineage,
    blob_digest,
    capture_candidate_revision,
)
from hwpxfiller.external.candidate_store import (
    CandidateObjectStore,
    DanglingReference,
    ObjectAlreadyExists,
    ObjectCorrupt,
)
from hwpxfiller.external.template_source_reader import (
    FileIdentity,
    FileTemplateSourceReader,
    classify_capture_stability,
)

BYTES = b"PK\x03\x04 exact hwpx candidate bytes"
BINDING = MutableSourceBinding("SB1", "hwpx", "unused", {}, 7)
LINEAGE = TemplateLineage("L1", "hwpx", "SB1", 7, "t0")


def _reader(data=BYTES, *, binding=BINDING):
    def read(_binding):
        return StableCapture(
            exact_bytes=data,
            captured_content_digest=blob_digest(data),
            source_binding_id=binding.source_binding_id,
            source_binding_generation=binding.generation,
            capture_method="fake",
            observed_metadata={"byte_length": len(data)},
        )

    return read


def _capture(store, *, reader=None, binding=BINDING, lineage=LINEAGE, obs="O1", rev="R1"):
    return capture_candidate_revision(
        lineage=lineage,
        binding=binding,
        preparation_id="P1",
        reader=reader or _reader(),
        store=store,
        observation_id=obs,
        revision_id=rev,
        captured_at="t1",
        created_at="t1",
    )


# ── 순수 안정성 판정: 전 음성 경계를 fabricated identity 로 ────────────────────
_STABLE = FileIdentity(10, 1, 30, 111)


@pytest.mark.parametrize(
    ("post", "on_path", "probed", "reason"),
    (
        (_STABLE, _STABLE, 7, None),
        (FileIdentity(10, 1, 20, 222), _STABLE, 7, SOURCE_CAPTURE_ERROR),  # read 중 변경
        (_STABLE, FileIdentity(99, 1, 30, 111), 7, SOURCE_CAPTURE_ERROR),  # atomic replace
        (_STABLE, _STABLE, 8, SOURCE_BINDING_CHANGED),  # generation 7→8
    ),
)
def test_classify_capture_stability(post, on_path, probed, reason) -> None:
    assert (
        classify_capture_stability(
            pre=_STABLE, post=post, on_path=on_path,
            expected_generation=7, probed_generation=probed,
        )
        == reason
    )


def test_content_blob_rejects_digest_or_length_mismatch() -> None:
    with pytest.raises(CandidateRevisionError):
        ContentBlob(digest="sha256:0" * 8, media="hwpx", exact_bytes=BYTES, byte_length=len(BYTES))
    with pytest.raises(CandidateRevisionError):
        ContentBlob(digest=blob_digest(BYTES), media="hwpx", exact_bytes=BYTES, byte_length=1)


# ── service orchestration ─────────────────────────────────────────────────────
def test_capture_publishes_blob_observation_revision_with_exact_bytes(tmp_path) -> None:
    store = CandidateObjectStore(tmp_path)
    result = _capture(store)
    assert isinstance(result, CandidateRevisionCreated)
    assert store.get_blob(result.blob.digest).exact_bytes == BYTES  # 재serialize 없음
    assert store.get_revision("R1").exact_content_digest == blob_digest(BYTES)
    assert store.get_observation("O1").captured_content_digest == blob_digest(BYTES)


def test_same_bytes_reuse_one_blob_across_two_revisions(tmp_path) -> None:
    store = CandidateObjectStore(tmp_path)
    _capture(store, obs="O1", rev="R18")
    _capture(store, obs="O2", rev="R19")
    assert store.get_revision("R18").exact_content_digest == store.get_revision("R19").exact_content_digest
    assert sorted(p.name for p in (tmp_path / "blobs").iterdir()) == [f"{blob_digest(BYTES).split(':')[1]}.json"]


@pytest.mark.parametrize(
    ("binding", "lineage", "reader", "reason"),
    (
        (MutableSourceBinding("SB1", "txt", "u", {}, 7), LINEAGE, None, MEDIA_MISMATCH),
        (BINDING, LINEAGE, lambda _b: SourceCaptureError(SOURCE_CAPTURE_ERROR), SOURCE_CAPTURE_ERROR),
        (BINDING, TemplateLineage("L1", "hwpx", "SB-other", 7, "t0"), None, SOURCE_BINDING_CHANGED),
    ),
)
def test_capture_fails_closed_without_writing(tmp_path, binding, lineage, reader, reason) -> None:
    store = CandidateObjectStore(tmp_path)
    result = _capture(store, reader=reader, binding=binding, lineage=lineage)
    assert result == SourceCaptureError(reason)
    assert not (tmp_path / "revisions").exists()


# ── store 무결성 ──────────────────────────────────────────────────────────────
def test_store_rejects_same_revision_id_different_digest(tmp_path) -> None:
    store = CandidateObjectStore(tmp_path)
    _capture(store, rev="R1")
    with pytest.raises(ObjectAlreadyExists):
        _capture(store, reader=_reader(b"different exact bytes entirely"), obs="O2", rev="R1")


def test_store_refuses_revision_referencing_missing_blob_or_observation(tmp_path) -> None:
    from hwpxfiller.application.candidate_revision import TemplateRevision

    store = CandidateObjectStore(tmp_path)
    orphan = TemplateRevision("R1", "L1", "hwpx", blob_digest(BYTES), "O-missing", "t1")
    with pytest.raises(DanglingReference):  # blob 부재
        store.put_revision(orphan)

    store.put_blob(ContentBlob(blob_digest(BYTES), "hwpx", BYTES, len(BYTES)))
    with pytest.raises(DanglingReference):  # blob 은 있고 observation 부재
        store.put_revision(orphan)


def test_store_rejects_bad_id_and_missing_object(tmp_path) -> None:
    from hwpxfiller.external.candidate_store import InvalidObjectId, ObjectNotFound

    store = CandidateObjectStore(tmp_path)
    with pytest.raises(InvalidObjectId):
        store.get_observation("../evil")
    with pytest.raises(ObjectNotFound):
        store.get_revision("nope")


def test_get_blob_rejects_content_address_forgery(tmp_path) -> None:
    import base64

    from hwpxfiller.external.candidate_store import _object_digest

    store = CandidateObjectStore(tmp_path)
    store.put_blob(ContentBlob(blob_digest(BYTES), "hwpx", BYTES, len(BYTES)))
    path = tmp_path / "blobs" / f"{blob_digest(BYTES).split(':')[1]}.json"
    content = json.loads(path.read_text("utf-8"))["content"]
    content["exact_bytes_b64"] = base64.b64encode(b"forged").decode("ascii")  # digest 는 그대로
    path.write_text(json.dumps({"digest": _object_digest(content), "content": content}), "utf-8")
    with pytest.raises(ObjectCorrupt):
        store.get_blob(blob_digest(BYTES))


def test_read_detects_corrupted_revision(tmp_path) -> None:
    store = CandidateObjectStore(tmp_path)
    _capture(store, rev="R1")
    path = tmp_path / "revisions" / "R1.json"
    tampered = json.loads(path.read_text("utf-8"))
    tampered["content"]["exact_content_digest"] = "sha256:tampered"
    path.write_text(json.dumps(tampered), "utf-8")
    with pytest.raises(ObjectCorrupt):
        store.get_revision("R1")


# ── 실 파일 어댑터(happy path + 간섭) ─────────────────────────────────────────
def test_file_reader_captures_exact_bytes_and_detects_truncation(tmp_path) -> None:
    src = tmp_path / "template.hwpx"
    src.write_bytes(BYTES)
    binding = MutableSourceBinding("SB1", "hwpx", str(src), {}, 7)

    stable = FileTemplateSourceReader(lambda _sid: 7)(binding)
    assert isinstance(stable, StableCapture)
    assert stable.exact_bytes == BYTES and stable.captured_content_digest == blob_digest(BYTES)

    truncate = FileTemplateSourceReader(lambda _sid: 7, interference=lambda: src.write_bytes(b"x"))
    assert truncate(binding) == SourceCaptureError(SOURCE_CAPTURE_ERROR)

    repinned = FileTemplateSourceReader(lambda _sid: 8)(binding)
    assert repinned == SourceCaptureError(SOURCE_BINDING_CHANGED)

    absent = MutableSourceBinding("SB1", "hwpx", str(tmp_path / "gone.hwpx"), {}, 7)
    assert FileTemplateSourceReader(lambda _sid: 7)(absent) == SourceCaptureError(SOURCE_CAPTURE_ERROR)
