"""Durable document saves, recovery drafts, and explicitly saved trial cases."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .atomic import write_bytes_atomic, write_bytes_atomic_exclusive
from .write_locks import shared_write_lock


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ExternalChangeError(ValueError):
    def __init__(self, fingerprint: str | None):
        self.fingerprint = fingerprint
        super().__init__("파일이 편집 중 외부에서 변경되었습니다.")


class AuthoringStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    @staticmethod
    def key(path: Path) -> str:
        return digest(str(path.resolve()).casefold().encode("utf-8"))

    def _path(self, kind: str, key: str) -> Path:
        return self.directory / kind / f"{key}.json"

    def read_document(self, path: Path) -> tuple[bytes, str]:
        data = path.read_bytes()
        return data, digest(data)

    def current_fingerprint(self, path: Path) -> str | None:
        return digest(path.read_bytes()) if path.is_file() else None

    def save_document(self, path: Path, data: bytes, expected: str | None) -> str:
        """Check the observed file and write under one in-process directory lock."""
        path = Path(path)
        with shared_write_lock(path.parent):
            actual = self.current_fingerprint(path)
            if actual != expected:
                raise ExternalChangeError(actual)
            path.parent.mkdir(parents=True, exist_ok=True)
            if expected is None:
                write_bytes_atomic_exclusive(path, data)
            else:
                write_bytes_atomic(path, data)
        return digest(data)

    def write_draft(
        self, key: str, *, path: str, media: str, baseline: str | None,
        source_baseline: str | None, content: bytes
    ) -> str:
        target = self._path("drafts", key)
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "version": 1,
            "path": path,
            "media": media,
            "baseline": baseline,
            "source_baseline": source_baseline,
            "content": base64.b64encode(content).decode("ascii"),
        }
        write_bytes_atomic(target, json.dumps(record, ensure_ascii=False).encode("utf-8"))
        return datetime.now(timezone.utc).isoformat()

    def read_draft(self, key: str) -> dict | None:
        target = self._path("drafts", key)
        if not target.is_file():
            return None
        record = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or type(record.get("version")) is not int \
                or record["version"] != 1:
            raise ValueError("지원하지 않는 복구 초안 형식입니다.")
        if (not isinstance(record.get("path"), str)
                or not isinstance(record.get("media"), str)
                or record["media"] not in {"txt", "hwpx"}
                or (record.get("baseline") is not None
                    and not isinstance(record["baseline"], str))
                or (record.get("source_baseline") is not None
                    and not isinstance(record["source_baseline"], str))
                or not isinstance(record.get("content"), str)):
            raise ValueError("복구 초안의 내용이 올바르지 않습니다.")
        try:
            record["content"] = base64.b64decode(record["content"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("복구 초안의 내용이 손상되었습니다.") from exc
        return record

    def discard_draft(self, key: str) -> None:
        self._path("drafts", key).unlink(missing_ok=True)

    def list_drafts(self) -> list[dict]:
        directory = self.directory / "drafts"
        if not directory.is_dir():
            return []
        drafts = []
        for target in sorted(directory.glob("*.json")):
            try:
                updated_at = datetime.fromtimestamp(
                    target.stat().st_mtime, timezone.utc
                ).isoformat()
            except OSError:
                updated_at = ""
            try:
                record = self.read_draft(target.stem)
                if record is not None:
                    drafts.append({"key": target.stem, "path": record["path"],
                                   "media": record["media"], "updated_at": updated_at})
            except (OSError, UnicodeError, ValueError) as exc:
                drafts.append({"key": target.stem, "path": "", "media": "",
                               "updated_at": updated_at,
                               "error": f"복구 초안을 읽을 수 없습니다: {exc}"})
        return drafts

    def read_cases(self, key: str) -> list[dict]:
        target = self._path("cases", key)
        if not target.is_file():
            return []
        record = json.loads(target.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or type(record.get("version")) is not int
                or record["version"] != 1 or not isinstance(record.get("cases"), list)):
            raise ValueError("지원하지 않는 시험 케이스 형식입니다.")
        return record["cases"]

    def write_cases(self, key: str, cases: list[dict]) -> None:
        target = self._path("cases", key)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({"version": 1, "cases": cases}, ensure_ascii=False).encode("utf-8")
        write_bytes_atomic(target, data)

    @staticmethod
    def export_cases(path: Path, cases: list[dict]) -> None:
        data = json.dumps({"version": 1, "cases": cases}, ensure_ascii=False, indent=2)
        write_bytes_atomic_exclusive(path, data.encode("utf-8"))

    @staticmethod
    def import_cases(path: Path) -> list[dict]:
        record = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or type(record.get("version")) is not int
                or record["version"] != 1 or not isinstance(record.get("cases"), list)):
            raise ValueError("지원하지 않는 시험 케이스 형식입니다.")
        return record["cases"]

    @staticmethod
    def export_result(path: Path, data: bytes) -> None:
        write_bytes_atomic_exclusive(path, data)
