"""Bundled tutorial originals and cleanup of legacy practice copies.

Since #1126 practice runs in its own workspace (:mod:`.tutorial_workspace`) and never copies
into the user's templates folder. :class:`PracticeFiles` remains only to clean up copies that
older versions left in the user's environment, using the same safety checks as before.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from . import settings

ORIGINALS = (
    "물품 구매입찰 공고.hwpx",
    "낙찰자 선정 및 계약체결 안내.txt",
    "계약방법 결정 및 구매추진 안내.txt",
    "공고목록.xlsx",
)

UNREADABLE_REFERENCES = "읽을 수 없는 작업이나 등록 데이터가 있어 연습 파일 정리를 중단했습니다."
JOB_REFERENCE = "저장한 작업이 참조합니다."
POOL_REFERENCE = "등록 데이터가 참조합니다."
MISSING = "연습 파일이 없거나 이동했습니다."


def asset_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "examples" / "tutorial"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[3] / "examples" / "tutorial"


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path_key(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


class PracticeFiles:
    def __init__(self, template_root: Path, home: Path, jobs, pools) -> None:
        self.template_root = template_root
        self.data_root = home / "tutorial_practice"
        self.jobs = jobs
        self.pools = pools

    def _manifest(self) -> dict:
        raw = settings.load_tutorial_practice()
        entries = raw.get("entries")
        if raw.get("version") != 1 or not isinstance(entries, list):
            raise ValueError("연습 파일 기록을 읽을 수 없습니다. 파일 정리를 중단했습니다.")
        return raw

    def latest(self, name: str) -> dict | None:
        for entry in reversed(self._manifest()["entries"]):
            if isinstance(entry, dict) and entry.get("name") == name:
                return entry
        return None

    def validate(self, entry: dict) -> tuple[bool, str]:
        try:
            name = entry["name"]
            path = Path(entry["path"])
            root = self.data_root if name.endswith(".xlsx") else self.template_root
            if name not in ORIGINALS or not path.is_relative_to(root) or path.is_symlink():
                return False, "연습 파일 경로를 확인할 수 없습니다."
            if path.resolve().parent != root.resolve():
                return False, "연습 파일이 다른 위치를 가리킵니다."
            if not path.is_file():
                return False, MISSING
            if fingerprint(path) != entry["sha256"]:
                return False, "연습 파일이 수정됐습니다. 현재 파일을 보존합니다."
            return True, ""
        except (KeyError, OSError, TypeError, ValueError):
            return False, "연습 파일 상태를 확인할 수 없습니다."

    def _referenced(self) -> dict[str, str]:
        """Path key -> preservation reason; unknown is never unreferenced.

        Any registry failure, and any job or pool entry that cannot be read, aborts
        cleanup: an unreadable record may be the one that needs a practice copy.
        """
        jobs, corrupt_jobs = self.jobs.list_jobs_with_corruption()
        entries, corrupt_pool = self.pools.list_references()
        if corrupt_jobs or corrupt_pool:
            raise ValueError(UNREADABLE_REFERENCES)
        referenced: dict[str, str] = {}
        for _key, item in entries:
            for raw in (item.opts.get("path"), item.opts.get("db")):
                if isinstance(raw, str) and raw:
                    referenced[_path_key(raw)] = POOL_REFERENCE
        for job in jobs:
            for path in (job.template_path, job.data_path):
                if path:
                    referenced[_path_key(path)] = JOB_REFERENCE
        return referenced

    def _vanished(self, entry: dict) -> bool:
        """True only for a record of this app's own copy path where nothing exists now.

        An interrupted cleanup (or a lost manifest save) leaves such records behind.
        Dropping one removes no file: anything present at the path, an unexpected
        name or location, or an unreadable state keeps the record.
        """
        try:
            name, batch, path = entry["name"], entry["batch"], Path(entry["path"])
            if name not in ORIGINALS or not isinstance(batch, str) or not batch:
                return False
            root = self.data_root if name.endswith(".xlsx") else self.template_root
            original = Path(name)
            if path != root / f"{original.stem} (연습 {batch}){original.suffix}":
                return False
            try:
                path.lstat()
            except FileNotFoundError:
                return True
            return False
        except (KeyError, OSError, TypeError, ValueError):
            return False

    def _scan(self) -> tuple[dict, dict, list[str | None]]:
        """(preview, manifest, per-entry action): ``unlink``, ``forget`` or ``None``."""
        referenced = self._referenced()
        manifest = self._manifest()
        rows, actions = [], []
        for entry in manifest["entries"]:
            if not isinstance(entry, dict):
                raise ValueError("연습 파일 기록이 손상됐습니다. 정리를 중단했습니다.")
            ready, reason = self.validate(entry)
            action = "unlink" if ready else None
            path = Path(entry.get("path", ""))
            if not ready and self._vanished(entry):
                # Nothing to delete; confirming cleanup drops the stale record.
                ready, reason, action = True, MISSING, "forget"
            key = _path_key(path)
            if ready and key in referenced:
                ready, reason, action = False, referenced[key], None
            rows.append({"name": entry.get("name", ""), "path": str(path),
                         "delete": ready, "reason": reason})
            actions.append(action)
        token = hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()
        preview = {"token": token, "rows": rows,
                   "delete_count": sum(row["delete"] for row in rows)}
        return preview, manifest, actions

    def cleanup_preview(self) -> dict:
        return self._scan()[0]

    def cleanup(self, token: str) -> dict:
        # Job and pool writers wait from the reference scan until the last unlink, so
        # a job save or data registration cannot slip in between and lose its file.
        # Order: job lock, then pool lock. No other writer nests the two.
        with self.jobs.write_lock(), self.pools.write_lock():
            return self._cleanup_locked(token)

    def _cleanup_locked(self, token: str) -> dict:
        preview, manifest, actions = self._scan()
        if token != preview["token"]:
            raise ValueError("연습 파일 상태가 바뀌었습니다. 정리 내용을 다시 확인하세요.")
        # Check the whole set before deleting anything. A changed file must not
        # turn a confirmed cleanup into a partial, surprising operation.
        targets: list[tuple[str, bool]] = []
        for entry, action in zip(manifest["entries"], actions, strict=True):
            if action == "unlink" and not self.validate(entry)[0]:
                raise ValueError("연습 파일 상태가 바뀌었습니다. 정리 내용을 다시 확인하세요.")
            if action is not None:
                targets.append((entry["path"], action == "unlink"))
        removed: set[str] = set()
        failure: BaseException | None = None
        try:
            for path, exists in targets:
                if exists:
                    Path(path).unlink()
                removed.add(path)
        except BaseException as exc:  # recorded below, then re-raised unchanged
            failure = exc
        # Record every removal that happened, even when a later unlink failed. If this
        # save fails too, the next preview recognises the leftovers as vanished copies.
        if removed:
            manifest["entries"] = [e for e in manifest["entries"] if e.get("path") not in removed]
            try:
                settings.save_tutorial_practice(manifest)
            except Exception as save_error:
                if failure is None:
                    raise
                # The deletion error says why cleanup stopped; keep it as the raised one.
                raise failure from save_error
        if failure is not None:
            raise failure
        return {"removed": len(removed), "preserved": len(preview["rows"]) - len(removed)}
