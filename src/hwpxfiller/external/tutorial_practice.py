"""Bundled tutorial originals and non-destructive practice copies."""

from __future__ import annotations

import hashlib
import shutil
import sys
import uuid
from pathlib import Path

from . import settings

ORIGINALS = (
    "물품 구매입찰 공고.hwpx",
    "낙찰자 선정 및 계약체결 안내.txt",
    "계약방법 결정 및 구매추진 안내.txt",
    "공고목록.xlsx",
)


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


class PracticeFiles:
    def __init__(self, template_root: Path, home: Path, jobs) -> None:
        self.template_root = template_root
        self.data_root = home / "tutorial_practice"
        self.jobs = jobs

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
                return False, "연습 파일이 없거나 이동했습니다."
            if fingerprint(path) != entry["sha256"]:
                return False, "연습 파일이 수정됐습니다. 현재 파일을 보존합니다."
            return True, ""
        except (KeyError, OSError, TypeError, ValueError):
            return False, "연습 파일 상태를 확인할 수 없습니다."

    def prepare(self, *, derived: str = "") -> dict:
        """Create one fresh batch; never overwrite an existing practice file."""
        if derived not in {"", "blank", "replacement"}:
            raise ValueError("알 수 없는 연습 데이터 종류입니다.")
        source = asset_root()
        missing = [name for name in ORIGINALS if not (source / name).is_file()]
        if missing:
            raise FileNotFoundError("동봉 예제를 찾을 수 없습니다: " + ", ".join(missing))
        manifest = self._manifest()
        created: list[Path] = []
        entries: list[dict] = []
        batch = uuid.uuid4().hex[:10]
        try:
            names = ORIGINALS if not derived else ("공고목록.xlsx",)
            for name in names:
                original = source / name
                root = self.data_root if name.endswith(".xlsx") else self.template_root
                root.mkdir(parents=True, exist_ok=True)
                target = root / f"{original.stem} (연습 {batch}){original.suffix}"
                with original.open("rb") as reader, target.open("xb") as writer:
                    created.append(target)
                    shutil.copyfileobj(reader, writer)
                if name.endswith(".xlsx") and derived == "blank":
                    from openpyxl import load_workbook

                    workbook = load_workbook(target)
                    workbook["계약"]["K2"] = None  # 계약보증금: 원본에는 빈 셀이 없다.
                    workbook.save(target)
                entry = {
                    "name": name, "path": str(target), "sha256": fingerprint(target),
                    "batch": batch, "derived": derived,
                }
                entries.append(entry)
            manifest["entries"].extend(entries)
            settings.save_tutorial_practice(manifest)
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return {"batch": batch, "entries": entries}

    def _referenced(self) -> set[str]:
        """Any registry failure aborts cleanup; unknown is never unreferenced."""
        return {
            str(Path(path).resolve())
            for job in self.jobs.list_jobs()
            for path in (job.template_path, job.data_path)
            if path
        }

    def cleanup_preview(self) -> dict:
        referenced = self._referenced()
        rows = []
        for entry in self._manifest()["entries"]:
            if not isinstance(entry, dict):
                raise ValueError("연습 파일 기록이 손상됐습니다. 정리를 중단했습니다.")
            ready, reason = self.validate(entry)
            path = Path(entry.get("path", ""))
            if ready and str(path.resolve()) in referenced:
                ready, reason = False, "저장한 작업이 참조합니다."
            rows.append({"name": entry.get("name", ""), "path": str(path),
                         "delete": ready, "reason": reason})
        token = hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()
        return {"token": token, "rows": rows, "delete_count": sum(row["delete"] for row in rows)}

    def cleanup(self, token: str) -> dict:
        preview = self.cleanup_preview()
        if token != preview["token"]:
            raise ValueError("연습 파일 상태가 바뀌었습니다. 정리 내용을 다시 확인하세요.")
        manifest = self._manifest()
        deletions = [row for row in preview["rows"] if row["delete"]]
        # Check the whole set before deleting anything. A changed file must not
        # turn a confirmed cleanup into a partial, surprising operation.
        for row in deletions:
            entry = next((item for item in manifest["entries"]
                          if item.get("path") == row["path"]), None)
            if entry is None or not self.validate(entry)[0]:
                raise ValueError("연습 파일 상태가 바뀌었습니다. 정리 내용을 다시 확인하세요.")
        removed = set()
        for row in deletions:
            Path(row["path"]).unlink()
            removed.add(row["path"])
        manifest["entries"] = [e for e in manifest["entries"] if e.get("path") not in removed]
        settings.save_tutorial_practice(manifest)
        return {"removed": len(removed), "preserved": len(preview["rows"]) - len(removed)}
