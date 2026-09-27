"""복구 초안·시험 케이스 저장소(External) — 손상 입력은 조용히 넘어가지 않는다.

저장은 전부 원자 쓰기를 지난다: 교체·이동 실패는 기존 문서를 파괴하지 않고, 임시 파일
정리마저 실패해도 원래 예외가 그대로 올라간다(확인-또는-경보).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwpxfiller.external.authoring_store import AuthoringStore


def _store(tmp_path: Path) -> AuthoringStore:
    return AuthoringStore(tmp_path / "home")


def test_recovery_draft_roundtrip_and_corrupt_records_are_loud(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.read_draft("없는열쇠") is None
    stamp = store.write_draft("k", path="문서.txt", media="txt", baseline="b0",
                              source_baseline=None, content="내 편집".encode("utf-8"))
    assert stamp
    record = store.read_draft("k")
    assert record is not None
    assert (record["path"], record["media"], record["content"]) == (
        "문서.txt", "txt", "내 편집".encode("utf-8"))

    target = tmp_path / "home" / "drafts" / "k.json"
    for payload, message in (
        ({"version": 2, "path": "문서.txt", "media": "txt", "content": ""}, "지원하지 않는"),
        ({"version": 1, "path": "문서.txt", "media": "pdf", "content": ""}, "올바르지 않"),
        ({"version": 1, "path": "문서.txt", "media": "txt", "baseline": None,
          "source_baseline": None, "content": "!!아니다!!"}, "손상"),
    ):
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            store.read_draft("k")

    store.discard_draft("k")
    assert store.read_draft("k") is None


def test_draft_listing_survives_unreadable_entries(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    assert store.list_drafts() == []
    store.write_draft("ok", path="문서.txt", media="txt", baseline=None,
                      source_baseline=None, content=b"x")
    drafts = tmp_path / "home" / "drafts"
    (drafts / "폴더.json").mkdir()          # 파일이 아닌 항목은 목록에서 빠진다
    (drafts / "broken.json").write_text("{", encoding="utf-8")
    listed = {item["key"]: item for item in store.list_drafts()}
    assert set(listed) == {"ok", "broken"}
    assert listed["ok"]["path"] == "문서.txt" and listed["ok"]["updated_at"]
    assert listed["broken"]["error"] and listed["broken"]["path"] == ""

    real_stat = Path.stat

    def _stat(self: Path, **kwargs: object):
        if self.name == "ok.json":
            raise OSError(5, "I/O error")
        return real_stat(self, **kwargs)  # pyright: ignore[reportCallIssue]

    monkeypatch.setattr(Path, "stat", _stat)
    unstamped = {item["key"]: item for item in store.list_drafts()}
    assert unstamped["ok"]["updated_at"] == "" and unstamped["ok"]["error"]


def test_case_files_roundtrip_and_refuse_unknown_versions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.read_cases("k") == []
    store.write_cases("k", [{"name": "검토", "values": {"이름": "홍길동"}}])
    assert store.read_cases("k") == [{"name": "검토", "values": {"이름": "홍길동"}}]

    exported = tmp_path / "케이스.json"
    AuthoringStore.export_cases(exported, [{"name": "검토"}])
    assert AuthoringStore.import_cases(exported) == [{"name": "검토"}]
    with pytest.raises(FileExistsError):      # 내보내기는 기존 파일을 덮지 않는다
        AuthoringStore.export_cases(exported, [])

    unsupported = tmp_path / "옛판.json"
    unsupported.write_text(json.dumps({"version": 2, "cases": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="지원하지 않는"):
        AuthoringStore.import_cases(unsupported)
    (tmp_path / "home" / "cases" / "k.json").write_text(
        json.dumps({"version": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="지원하지 않는"):
        store.read_cases("k")


def test_write_failures_keep_the_existing_file_and_stay_loud(tmp_path: Path, monkeypatch) -> None:
    """교체·이동 실패는 물론 임시 파일 정리 실패도 원래 예외를 삼키지 않는다."""
    store = _store(tmp_path)
    document = tmp_path / "문서.txt"
    document.write_text("기존 내용", encoding="utf-8")
    fingerprint = store.current_fingerprint(document)

    def _boom(*args: object) -> None:
        raise OSError(5, "I/O error")

    monkeypatch.setattr("hwpxfiller.external.atomic.os.replace", _boom)
    monkeypatch.setattr("hwpxfiller.external.atomic.os.unlink", _boom)
    with pytest.raises(OSError):
        store.save_document(document, "새 내용".encode("utf-8"), fingerprint)
    assert document.read_text(encoding="utf-8") == "기존 내용"

    result = tmp_path / "결과.hwpx"
    result.write_bytes("기존".encode("utf-8"))
    with pytest.raises(FileExistsError):
        AuthoringStore.export_result(result, b"NEW")
    assert result.read_bytes() == "기존".encode("utf-8")


def test_workspace_records_roundtrip_and_refuse_unknown_shapes(tmp_path: Path) -> None:
    """U02 최근 작업 위치 — 모양만 확인하고, 읽을 수 없는 기록은 없는 것으로 치지 않는다."""
    store = _store(tmp_path)
    assert store.read_workspace("k") is None
    store.write_workspace("k", fingerprint="f0", mode="structure", selection={"start": 1, "end": 3})
    assert store.read_workspace("k") == {"version": 1, "fingerprint": "f0", "mode": "structure",
                                         "selection": {"start": 1, "end": 3}}
    store.write_workspace("k", fingerprint="f1", mode="template", selection=None)
    record = store.read_workspace("k")
    assert record is not None and record["selection"] is None

    target = tmp_path / "home" / "workspace" / "k.json"
    for payload, message in (
        ({"version": 2, "fingerprint": "f", "mode": "template", "selection": None}, "지원하지 않는"),
        ([], "지원하지 않는"),
        ({"version": 1, "fingerprint": 3, "mode": "template", "selection": None}, "올바르지 않"),
        ({"version": 1, "fingerprint": "f", "mode": None, "selection": None}, "올바르지 않"),
        ({"version": 1, "fingerprint": "f", "mode": "template", "selection": [1]}, "올바르지 않"),
    ):
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            store.read_workspace("k")
    target.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        store.read_workspace("k")
